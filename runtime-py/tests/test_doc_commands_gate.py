"""A command block that tells a reader to run a program names a program that is here.

WHAT THE DEFECT IS. `docs/mcp.md` said, of whether the declared MCP endpoint actually
reaches and whether it serves *this* checkout's source, that it "is not a thing to reason
about", and then handed the reader:

    ```bash
    python tools/mcpreach/mcpreach.py check          # from any checkout or worktree
    ```

with a five-value exit-code interface documented underneath it. MEASURED 2026-08-24, on
this branch, over every ref this repository has:

    $ git log --all --diff-filter=A -- '*mcpreach*'
    $

empty. `tools/mcpreach/mcpreach.py` has never been added on any ref. `docs/eval.md`
records why -- the half-built checker "had never been seen to fire" and was deliberately
not merged with `RB-P96` -- while two other files went on citing it as the runnable
answer (`tools/bantamkit-mcp:47` claimed it as `--which`'s consumer). So the one page
that told an operator not to reason about reachability pointed them at vaporware.

AND THE FAILURE IS NOT INERT, WHICH IS WHY THIS IS A GATE AND NOT A TYPO. Running the
documented command gives, verbatim:

    $ .venv/bin/python tools/mcpreach/mcpreach.py check
    can't open file '.../tools/mcpreach/mcpreach.py': [Errno 2] No such file or directory
    $ echo $?
    2

and `2` is the value that same page documents as `FOREIGN` -- "it launched, but it is
serving a *different* checkout's source". To anything scripting the documented interface,
a program that is absent and a silent wrong-checkout server are the same number.

WHAT THIS KEYS ON: RUNNABILITY, NOT MENTION. The rule is **a `tools/...` path appearing
inside a fenced code block whose info string names a shell** (```` ```bash ````, ```sh``,
```shell``, ```console``, ```zsh``) in a tracked `.md` file. That is the shape of an
instruction to run something. It is deliberately NOT "any mention of the path", because
four files in this tree cite `tools/mcpreach/mcpreach.py` in prose precisely in order to
record that it does not exist -- `docs/install.md`, `runtime-ts/README.md`,
`runtime-py/tests/test_mcp_endpoint.py`'s docstring and `runtime-ts/src/cli.ts`. A gate
that forbade the mention would demand deleting the record of the defect, which is the
opposite of the property. A comment cannot satisfy this gate either: the assertion is
`Path.exists()` on the named path, so the only way to go green is for the file to be in
the tree or for the command block to stop naming it.

THE SCOPE IS `tools/`, AND THE NARROWING IS DECLARED. `tools/` is where this
repository's runnable programs live. MEASURED over the tracked `.md` files at `893ed89`:
the `tools/` scope yields **30** distinct (file, line, path) command references, of which
exactly **one** -- `docs/mcp.md:155` -- was missing. Widening the prefix set to
`runtime-py/`, `runtime-ts/` and `.github/` yields 110 references and three misses, and
the two extra ones are transcripts of runs that already happened rather than instructions:
`docs/eval.md:5111` names a scratch `runtime-py/src/bantamkit/_probe.py` written and
deleted inside one measurement, and `docs/superpowers/plans/2026-08-06-bantamkit-v1.md:78`
names the `runtime-ts/.gitkeep` that the real `runtime-ts/` replaced. Both are historical
records in dated documents; failing them would mean editing history to satisfy a gate.

WHAT THIS GATE CANNOT SEE. A command block naming a program by a bare name resolved
through `PATH`, an absolute path, or a path built by shell interpolation. And a *claim*
about a program that is not phrased as a command -- `tools/bantamkit-mcp:47`'s "reads it"
was exactly that shape, and it is closed in the same commit by hand, not by this file.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# A fence opens and closes with three or more backticks; the info string follows the
# opening fence only. `console`/`zsh` are here because a reader treats them the same way.
_FENCE = re.compile(r"^(`{3,})\s*([^\s`]*)")
_SHELL_INFO = frozenset({"bash", "sh", "shell", "console", "zsh"})

# A repo-relative path into `tools/`. The lookbehind stops the match starting in the
# middle of a longer path, and the trailing punctuation strip handles a path that ends a
# sentence or sits inside a shell string.
_TOOL_PATH = re.compile(r"(?<![\w./-])(tools/[A-Za-z0-9_.\-/]+)")
_TRAILING = ".,;:)]}\"'`"


def command_tool_paths(markdown: str) -> list[tuple[int, str]]:
    """`(line number, path)` for every `tools/...` path inside a shell command block."""
    found: list[tuple[int, str]] = []
    in_shell_block = False
    fence: str | None = None
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
        if not in_shell_block:
            continue
        for token in _TOOL_PATH.findall(line):
            found.append((lineno, token.rstrip(_TRAILING)))
    return found


def _tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    ).stdout
    return [REPO_ROOT / name for name in out.split("\0") if name]


def _scan_tree() -> list[tuple[str, int, str]]:
    references: list[tuple[str, int, str]] = []
    for path in _tracked_markdown():
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, token in command_tool_paths(text):
            references.append((rel, lineno, token))
    return references


def test_the_scan_reaches_the_tracked_markdown() -> None:
    """Without this, a broken glob makes the gate below vacuously green.

    No count is asserted -- a number here would be a function of how much documentation
    the repo happens to carry, not of whether the scanner works. Non-empty is the claim.
    """
    references = _scan_tree()
    assert references, "no shell command block in any tracked .md named a tools/ path"


def test_every_program_a_command_block_names_is_in_the_tree() -> None:
    """The gate. `docs/mcp.md:155` is what made this red."""
    missing = [
        f"{rel}:{lineno} names {token}, which is not in the tree"
        for rel, lineno, token in _scan_tree()
        if not (REPO_ROOT / token).exists()
    ]
    assert not missing, (
        "a fenced shell block instructs a reader to run a program that does not exist:\n"
        + "\n".join(missing)
    )


def test_the_extractor_fires_on_a_command_naming_a_missing_program() -> None:
    """Pinned on a fixture, so the gate's teeth do not depend on repo content."""
    markdown = (
        "Whether it reaches is not a thing to reason about:\n"
        "\n"
        "```bash\n"
        "python tools/nowhere/nowhere.py check          # from any worktree\n"
        "```\n"
    )
    assert command_tool_paths(markdown) == [(4, "tools/nowhere/nowhere.py")]


@pytest.mark.parametrize(
    "markdown",
    [
        pytest.param(
            "`tools/nowhere/nowhere.py` has never existed on any ref.\n",
            id="prose-citation",
        ),
        pytest.param(
            "```\ntools/nowhere/nowhere.py\n```\n",
            id="unmarked-fence",
        ),
        pytest.param(
            "```text\n$ tools/nowhere/nowhere.py\nNo such file or directory\n```\n",
            id="transcript-fence",
        ),
        pytest.param(
            "```python\nPATH = 'tools/nowhere/nowhere.py'\n```\n",
            id="python-fence",
        ),
    ],
)
def test_a_citation_is_not_an_instruction(markdown: str) -> None:
    """The record of a program that does not exist must stay writable.

    Four files cite `tools/mcpreach/mcpreach.py` in exactly these shapes in order to say
    it is absent. If any of these returned a reference, closing the gate would mean
    deleting the evidence.
    """
    assert command_tool_paths(markdown) == []


def test_a_closing_fence_ends_the_block() -> None:
    """A path after the block is prose again, and a nested fence does not leak."""
    markdown = (
        "```bash\n"
        "tools/mcpdrift/mcpdrift.py check\n"
        "```\n"
        "\n"
        "and then `tools/nowhere/nowhere.py` is only mentioned.\n"
    )
    assert command_tool_paths(markdown) == [(2, "tools/mcpdrift/mcpdrift.py")]
