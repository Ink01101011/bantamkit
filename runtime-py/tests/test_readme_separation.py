"""The npm README and the PyPI README do not hand a reader the other package's commands.

WHAT SHIPS WHERE, AND WHY THIS IS TWO PAGES AND NOT ONE. `runtime-ts/package.json`
declares `files: ["dist", "assets"]` and no README -- and does not need to: npm always
includes `README.md` from the *package root* regardless of `files`, the same rule
`runtime-ts/test/packaging.test.mjs` already records for `package.json`. On the other
side `runtime-py/pyproject.toml` says `readme = "README.md"`. So:

    runtime-ts/README.md  ->  the npm landing page, read by someone who ran `npx`
    runtime-py/README.md  ->  the PyPI long description, read by someone who ran `pip`
    README.md (repo root) ->  GitHub, read by someone who has chosen NEITHER

WHAT THE DEFECT WAS. Measured 2026-09-20 over the two pages, counting hits per token:

    file                  npx   npm   pip/pipx/uv   PyPI   python   node
    runtime-py/README.md    0     4        23         3      23       8
    runtime-ts/README.md   41    27         3         2      16      32

The PyPI side's four `npm` hits were all links. The npm side's were not. Its clearest
defect was a **table cell**: a table headed "How to update" carried the row

    | PyPI (`pip install "bantamkit[mcp]"`) | `pip install -U "bantamkit[mcp]"` * pipx:
      `pipx upgrade bantamkit` * uv: `uv tool upgrade bantamkit` |

which hands a reader who installed with `npx` three upgrade commands for a package they
do not have. Beside it, the host-config table offered `| Python venv |
`/absolute/path/to/env/bin/bantamkit-mcp` | `[]` |` as a route.

WHAT THIS KEYS ON: RUNNABILITY, NOT MENTION -- carried from
`tests/test_doc_commands_gate.py`, which keys on a command inside a fenced block whose
info string names a shell and deliberately does NOT key on mention, because files in this
tree cite a thing precisely in order to say something about it. The same distinction
holds here and for the same reason. These pages MUST be able to say

  - "No Python, `pip`, `uv`, `pipx` or venv" (the npm page's selling point, line 6),
  - "`bantamkit-mcp`'s help is byte-compared with `python -m bantamkit.mcpserver -h`",
  - "the operator CLI is `python -m bantamkit.memory` here and `bantamkit-memory` there",

and link to the sibling package. All three are claims *about* the other runtime, and the
repo's whole divergence discipline depends on them staying readable from either side.

AND IT KEYS ON TABLE CELLS TOO, WHICH IS A DELIBERATE WIDENING.
`test_doc_commands_gate.py` looks only inside fenced blocks because that was the shape of
its defect. The worst leak here was a table cell, so a code span inside a table row counts
as an instruction site here. It is written down rather than buried in a regex because it
is the one place this gate is stricter than its sibling. A table cell that is prose or a
link is not an instruction: `| npm package | The pure-Node server |` stays legal.

WHAT IS NOT FORBIDDEN, AND WHY.

  - The repo-root `README.md` is EXEMPT. Its reader has chosen neither package, and
    offering both installs is its job. The exemption is asserted below, not implied, so
    that nobody later widens the scan and quietly deletes half that page.
  - `node tools/conformance/run.mjs --all` in the PyPI page's Development section. Both
    pages carry a Development section, and its reader has cloned the repository: it is
    neither package's customer. `tools/` is repo tooling, not the npm package, and the
    cross-runtime gate genuinely needs Node. The forbidden set below names package entry
    points (`npx`, `npm install`, `dist/cli.js`, `bantamkit-memory`; `pip`, `pipx`,
    `uv tool`, `python -m bantamkit`, `python -m venv`, a venv's `bin/bantamkit-mcp`),
    never the word `node` or the word `python` on its own.

WHAT THIS GATE CANNOT SEE. A command written without backticks inside a table cell, an
instruction phrased as prose ("upgrade it with pipx"), and a command reached through a
link. Those are the same blind spots `test_doc_commands_gate.py` declares, for the same
reason: the shape of an instruction is what is checkable, not the intent behind it.

RULING S3.3 -- THIS GATE LANDS ON BOTH SIDES. It reads tracked markdown, so it is not a
runtime surface and has no conformance case, but the two landing pages are owned one per
runtime and each runtime's own release gate must catch its own page. The Node mirror is
`runtime-ts/test/readme-separation.test.mjs`; the two hold the same property over the
same two files with the same forbidden sets, so neither runtime can ship a mixed page
through its own gate. Change one and change the other.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

NPM_README = REPO_ROOT / "runtime-ts" / "README.md"
PYPI_README = REPO_ROOT / "runtime-py" / "README.md"
ROOT_README = REPO_ROOT / "README.md"

# Same fence handling as tests/test_doc_commands_gate.py: a fence opens and closes with
# three or more backticks and the info string follows the opening fence only.
_FENCE = re.compile(r"^(`{3,})\s*([^\s`]*)")
_SHELL_INFO = frozenset({"bash", "sh", "shell", "console", "zsh"})

# A markdown table row, and the separator row that is not one.
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

# An inline code span inside a table cell. RULING S3.2: this is the "presented as a
# command" shape. Prose and links in the same cell are left alone.
_CODE_SPAN = re.compile(r"`([^`\n]+)`")

# Commands that install, upgrade or launch the PYTHON package. Forbidden on the npm page.
PYTHON_PACKAGE_COMMANDS: tuple[tuple[str, str], ...] = (
    (r"\bpipx\b", "pipx"),
    (r"\bpip3?\s+(install|download|wheel|uninstall)\b", "pip install/download/wheel"),
    (r"\bpython3?\s+-m\s+pip\b", "python -m pip"),
    (r"\bpython3?\s+-m\s+venv\b", "python -m venv"),
    (r"\bpython3?\s+-m\s+bantamkit\b", "python -m bantamkit..."),
    (r"\buv\s+(tool|pip)\b", "uv tool/uv pip"),
    (r"/bin/bantamkit-mcp\b", "a venv's bin/bantamkit-mcp"),
)

# Commands that install, upgrade or launch the NODE package. Forbidden on the PyPI page.
# `node tools/...` is deliberately absent -- see the module docstring.
NODE_PACKAGE_COMMANDS: tuple[tuple[str, str], ...] = (
    (r"\bnpx\b", "npx"),
    (r"\bnpm\s+(i|install|ci|exec)\b", "npm install/ci/exec"),
    (r"\bbantamkit-memory\b", "the Node operator CLI bantamkit-memory"),
    (r"\bdist/cli\.js\b", "dist/cli.js"),
)


def instruction_sites(markdown: str) -> list[tuple[int, str, str]]:
    """`(line number, kind, text)` for every place this page instructs a reader.

    Two kinds. `shell` is a line inside a fenced block whose info string names a shell.
    `cell` is one inline code span inside a markdown table row -- RULING S3.2's widening.
    Everything else (prose, links, unmarked fences, `python`/`ts`/`json` fences) is not
    an instruction and is not returned.
    """
    sites: list[tuple[int, str, str]] = []
    fence: str | None = None
    in_shell_block = False
    for lineno, line in enumerate(markdown.splitlines(), start=1):
        match = _FENCE.match(line)
        if match is not None:
            ticks, info = match.group(1), match.group(2).lower()
            if fence is None:
                fence = ticks
                in_shell_block = info in _SHELL_INFO
            elif len(ticks) >= len(fence):
                fence = None
                in_shell_block = False
            continue
        if fence is not None:
            if in_shell_block and line.strip():
                sites.append((lineno, "shell", line.strip()))
            continue
        if _TABLE_ROW.match(line) and not _TABLE_RULE.match(line):
            for span in _CODE_SPAN.findall(line):
                sites.append((lineno, "cell", span))
    return sites


def foreign_instructions(
    path: Path, forbidden: tuple[tuple[str, str], ...]
) -> list[str]:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(REPO_ROOT).as_posix()
    hits: list[str] = []
    for lineno, kind, body in instruction_sites(text):
        for pattern, name in forbidden:
            if re.search(pattern, body):
                hits.append(f"{rel}:{lineno} ({kind}) runs {name}: {body}")
                break
    return hits


def test_the_scan_reaches_both_landing_pages() -> None:
    """Without this, a broken fence or table parser makes the two gates below green.

    No count is asserted: the number of instruction sites is a function of how much
    documentation each page happens to carry. Non-empty, on both, is the claim.
    """
    for path in (NPM_README, PYPI_README):
        sites = instruction_sites(path.read_text(encoding="utf-8"))
        assert sites, f"{path} yielded no instruction site at all"


def test_the_npm_page_never_runs_the_python_package() -> None:
    """The gate. `runtime-ts/README.md`'s PyPI update row is what made this red."""
    hits = foreign_instructions(NPM_README, PYTHON_PACKAGE_COMMANDS)
    assert not hits, (
        "the npm landing page instructs its reader to run the PyPI package:\n"
        + "\n".join(hits)
    )


def test_the_pypi_page_never_runs_the_node_package() -> None:
    """The mirror. Kept even though the measured leak was one-sided.

    A gate that only guards the side that happened to be dirty is a gate that lets the
    next job dirty the other one.
    """
    hits = foreign_instructions(PYPI_README, NODE_PACKAGE_COMMANDS)
    assert not hits, (
        "the PyPI landing page instructs its reader to run the npm package:\n"
        + "\n".join(hits)
    )


def test_each_page_still_points_at_its_sibling() -> None:
    """Separation is not silence.

    The two runtimes share one memory store on disk, so a reader who lands on the wrong
    package must be able to find the right one. A gate that only forbade would be
    satisfiable by deleting the cross-reference, which is the opposite of the property.
    """
    npm_text = NPM_README.read_text(encoding="utf-8")
    pypi_text = PYPI_README.read_text(encoding="utf-8")
    assert "https://pypi.org/project/bantamkit/" in npm_text, (
        "the npm page does not link the PyPI package anywhere"
    )
    assert "https://www.npmjs.com/package/bantamkit-mcp" in pypi_text, (
        "the PyPI page does not link the npm package anywhere"
    )


def test_the_repo_root_readme_is_exempt_and_offers_both() -> None:
    """RULING S3.1's exemption, asserted rather than implied.

    Its reader has chosen neither package. If a later job widens the scan to every
    tracked `.md`, this node goes red first and says why.
    """
    text = ROOT_README.read_text(encoding="utf-8")
    sites = instruction_sites(text)
    node_hits = [
        body
        for _, _, body in sites
        if any(re.search(p, body) for p, _ in NODE_PACKAGE_COMMANDS)
    ]
    python_hits = [
        body
        for _, _, body in sites
        if any(re.search(p, body) for p, _ in PYTHON_PACKAGE_COMMANDS)
    ]
    assert node_hits, "the repo-root README stopped offering the npm install"
    assert python_hits, "the repo-root README stopped offering the PyPI install"


def test_a_claim_about_the_other_runtime_is_not_an_instruction() -> None:
    """The divergence record must stay writable from either side.

    These are the three shapes the two pages actually use to describe each other. If any
    of them counted, closing the gate would mean deleting the honest record of a
    deliberate difference -- which S3 forbids by name.
    """
    for markdown in (
        "every later launch starts offline. No Python, `pip`, `uv`, `pipx` or venv.\n",
        "`bantamkit-mcp`'s help is byte-compared with `python -m bantamkit.mcpserver -h`.\n",
        "there the same CLI is `python -m bantamkit.memory`, identical bytes apart.\n",
        "The same server in pure Node is on npm as [`bantamkit-mcp`](https://npm/x).\n",
    ):
        assert instruction_sites(markdown) == []


@pytest.mark.parametrize(
    "markdown",
    [
        pytest.param("```\npip install bantamkit\n```\n", id="unmarked-fence"),
        pytest.param("```python\nimport bantamkit\n```\n", id="python-fence"),
        pytest.param("```json\n{\"command\": \"npx\"}\n```\n", id="json-fence"),
        pytest.param("|---|---|\n", id="table-rule"),
    ],
)
def test_shapes_that_are_not_instructions(markdown: str) -> None:
    assert instruction_sites(markdown) == []


def test_the_extractor_fires_on_a_fenced_command() -> None:
    markdown = "```bash\npip install -U \"bantamkit[mcp]\"\n```\n"
    assert instruction_sites(markdown) == [(2, "shell", 'pip install -U "bantamkit[mcp]"')]


def test_the_extractor_fires_on_a_table_cell() -> None:
    """The widening, pinned on the row that was actually in the shipped npm README."""
    markdown = (
        "| How it was installed | How to update |\n"
        "|---|---|\n"
        '| PyPI (`pip install "bantamkit[mcp]"`) | `pipx upgrade bantamkit` |\n'
    )
    assert instruction_sites(markdown) == [
        (3, "cell", 'pip install "bantamkit[mcp]"'),
        (3, "cell", "pipx upgrade bantamkit"),
    ]


@pytest.mark.parametrize(
    ("body", "forbidden"),
    [
        pytest.param('pip install "bantamkit[mcp]"', PYTHON_PACKAGE_COMMANDS, id="pip"),
        pytest.param("pipx upgrade bantamkit", PYTHON_PACKAGE_COMMANDS, id="pipx"),
        pytest.param("uv tool upgrade bantamkit", PYTHON_PACKAGE_COMMANDS, id="uv"),
        pytest.param("python -m bantamkit.memory status", PYTHON_PACKAGE_COMMANDS, id="module"),
        pytest.param("python -m venv <env>", PYTHON_PACKAGE_COMMANDS, id="venv"),
        pytest.param(
            "/absolute/path/to/env/bin/bantamkit-mcp",
            PYTHON_PACKAGE_COMMANDS,
            id="venv-bin",
        ),
        pytest.param("npx -y bantamkit-mcp@latest --update", NODE_PACKAGE_COMMANDS, id="npx"),
        pytest.param("npm i -g bantamkit-mcp@latest", NODE_PACKAGE_COMMANDS, id="npm-i"),
        pytest.param(
            "npx -y -p bantamkit-mcp bantamkit-memory status",
            NODE_PACKAGE_COMMANDS,
            id="memory-cli",
        ),
        pytest.param(
            "node ~/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js",
            NODE_PACKAGE_COMMANDS,
            id="cli-js",
        ),
    ],
)
def test_every_forbidden_pattern_fires_on_a_real_command(
    body: str, forbidden: tuple[tuple[str, str], ...]
) -> None:
    """A pattern that never matches anything is a gate with a dead branch.

    Each string here was copied out of a page that really carried it.
    """
    assert any(re.search(pattern, body) for pattern, _ in forbidden)


def test_the_dev_section_command_that_must_stay_legal() -> None:
    """`node tools/conformance/run.mjs --all` on the PyPI page is not a Node-package run.

    If this ever goes red, the forbidden set has been widened to the word `node` and the
    PyPI page's Development section is about to lose the cross-runtime gate.
    """
    body = "node tools/conformance/run.mjs --all"
    assert not any(re.search(pattern, body) for pattern, _ in NODE_PACKAGE_COMMANDS)
