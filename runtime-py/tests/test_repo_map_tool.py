"""`repo_map` (job45, roadmap row 10): the ranked definition map on the MCP surface.

WHAT THIS FILE IS FOR, AND WHAT IT IS NOT FOR. `test_repomap.py` owns the engine — the
scanner, the graph, the ranking, the budget and every omission. This file owns the SURFACE:
the registration, the three refusals, the reply's shape, and the event log's silence about
the paths it was handed. Nothing here calls the handler directly; a node that did would
agree with itself through any registration mistake, and the registration is half of what
this unit added.

THE FIXTURE IS A BUILT TREE, NEVER THE REPOSITORY. J45-10 measured three separate wrong
answers from using this repository as a repo-map corpus while the unit was writing into it:
adding a test file produced 40 phantom edge rows, and creating one note moved
`unknown-language` from 1689 to 1690 and scored four equivalent mutants as KILLED. A
fixture tree is the only corpus whose denominator does not co-move with the unit's own
output.
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("mcp")

#: RETIRED FROM THE ROSTER, NOT DELETED. `repo_map` left `tools/list` on the user's ruling
#: of 2026-09-12 (job50 I5): measured over the transcript corpus it was never called, and
#: every request re-sent its description. Every node here drives the tool THROUGH the
#: server by design (see the module docstring), so none can run while the handler is
#: DORMANT in `mcpserver.py`. The module stays as the record of what the surface promised
#: and what will have to hold again if the roster line returns; the skip is the honest
#: state, not a silenced pin. `test_tool_manifest.py::RETIRED` pins that it is off.
pytestmark = pytest.mark.skip(
    reason="repo_map left the MCP roster by ruling (job50 I5, 2026-09-12); handler DORMANT"
)

from mcp import Client  # noqa: E402

from bantamkit import repomap  # noqa: E402
from bantamkit.assets import load_tool_asset  # noqa: E402
from bantamkit.eventlog import EventLog  # noqa: E402
from bantamkit.mcpserver import REPO_MAP_EMPTY, REPO_MAP_TAIL, build_server  # noqa: E402
from bantamkit.memory import Memory  # noqa: E402

FIXED_MS = 1756029153412

SERVED_ORDER = [
    "memory_save",
    "memory_recall",
    "validate_json",
    "shiftwork_clock_in",
    "shiftwork_clock_out",
    "shiftwork_status",
    "build_identity",
    "bantamkit_status",
    "memory_compact",
    "bantamkit_read",
    "skill_audit",
    "memory_dream",
    "repo_map",
    "token_ledger",
]

#: Every path segment, file name and definition name in the fixture is a sentinel, so the
#: privacy node below can assert on the STRING rather than on a policy someone read.
SENTINEL = "SECRET-TREE-4c1b"


def make(tmp_path):
    log = tmp_path / "log.jsonl"
    server = build_server(Memory(store=tmp_path / "store"), EventLog(log, clock=lambda: FIXED_MS))
    return server, log


def records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_bytes().decode("utf-8").splitlines()]


def call(server, **args):
    """`(is_error, text)` — the refusals are ANSWERS here, not exceptions, so both come back."""

    async def scenario():
        async with Client(server) as c:
            answer = await c.call_tool("repo_map", args)
            return answer.is_error, answer.content[0].text

    return asyncio.run(scenario())


def tree(tmp_path):
    """A two-file Python package plus one file the scanner has no dialect for.

    `dream.py` names `Store`, `save` and `load`, all of which only `store.py` defines, so
    there is exactly one edge and the ranking is not a coin toss. `README` is the
    `unknown-language` omission, which is what proves the footer reaches the reply.
    """
    root = tmp_path / SENTINEL
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "store.py").write_text(
        '"""A docstring naming Store, so the strip is load-bearing."""\n'
        "class Store:\n"
        "    def save(self, fact):\n"
        "        return fact\n"
        "    def load(self, key):\n"
        "        return key\n",
        encoding="utf-8",
    )
    (root / "pkg" / "dream.py").write_text(
        "from pkg.store import Store\n"
        "def dream(store):\n"
        "    s = Store()\n"
        "    s.save(1)\n"
        "    return s.load(2)\n",
        encoding="utf-8",
    )
    (root / "README").write_text("not source\n", encoding="utf-8")
    return root


# ------------------------------------------------------------------ registration


def test_the_tool_is_served_thirteenth_and_its_schema_is_the_asset(tmp_path):
    """Registration order IS served order, and the schema comes from the manifest.

    The index is pinned rather than `[-1]`: this node is about where `repo_map` sits, and a
    later tool moving in behind it must not be able to satisfy it.
    """
    server, _ = make(tmp_path)

    async def scenario():
        async with Client(server) as c:
            listed = (await c.list_tools()).tools
            assert [t.name for t in listed] == SERVED_ORDER
            assert listed[12].name == "repo_map"
            return listed[12]

    served = asyncio.run(scenario())
    manifest = load_tool_asset("repo_map")
    assert served.description == manifest["description"]
    assert served.input_schema == manifest["parameters"]
    assert served.output_schema == manifest["output_schema"]


# ---------------------------------------------------------------------- refusals


def test_an_empty_root_is_refused_and_never_the_servers_own_cwd(tmp_path):
    """`""` would resolve to the server's working directory, which is a machine-wide tree
    the caller did not ask for. It is refused before any walk, exactly as `skill_audit`
    refuses it."""
    server, log = make(tmp_path)
    is_error, text = call(server, root="")
    assert not is_error
    assert "root must not be empty; name the directory to map" in text
    assert [r["outcome"] for r in records(log)] == ["refused"]
    # A refusal carries no detail at all: `skill_audit`'s rule, and the reason is the same —
    # the only facts available at this point are the caller's own arguments.
    assert records(log)[0]["detail"] == {}


def test_a_missing_root_and_a_file_root_refuse_differently(tmp_path):
    """The two are different problems and they get different sentences.

    This is the node that earns putting the checks in the HANDLER: `repomap.repo_map` over
    a missing directory answers an empty map on both runtimes, so without these a typo
    would come back as "this tree holds no source".
    """
    server, _ = make(tmp_path)
    missing = tmp_path / "nowhere"
    _, text = call(server, root=str(missing))
    assert f"no such directory: {missing}" in text

    plain = tmp_path / "plain.py"
    plain.write_text("def f():\n    return 1\n", encoding="utf-8")
    _, text = call(server, root=str(plain))
    assert f"{plain} is a file, not a directory to map" in text


def test_a_negative_budget_is_refused_and_zero_is_not(tmp_path):
    """Zero is a legal budget — it renders nothing and reports the whole tree as a `budget`
    omission — so the refusal has to be strictly negative or the boundary case is lost."""
    root = tree(tmp_path)
    server, _ = make(tmp_path)
    _, text = call(server, root=str(root), budget=-1)
    assert "budget must not be negative; got -1" in text

    _, zero = call(server, root=str(root), budget=0)
    assert "budget must not be negative" not in zero
    assert "budget=" in zero


def test_a_dangling_symlink_root_is_a_missing_directory_and_not_a_crash(tmp_path):
    """`Path.exists()` follows, so a dangling link is not-here rather than an error.

    Named because it is one of the two shapes `reference-windows-dangling-symlink-two-shapes`
    records, and because the Node port reaches the same answer through a different mechanism
    (`statSync` plus an ignored-errno set) rather than by translating a line.
    """
    import os

    link = tmp_path / "dangling"
    if os.name == "nt":  # pragma: no cover - the POSIX arm is what CI runs
        pytest.skip("a dangling directory symlink needs a privilege Windows may not grant")
    link.symlink_to(tmp_path / "nowhere")
    server, _ = make(tmp_path)
    _, text = call(server, root=str(link))
    assert f"no such directory: {link}" in text


# ------------------------------------------------------------------------ answers


def test_the_reply_is_the_module_s_own_map_plus_the_header_and_the_tail(tmp_path):
    """The tool adds a header and a fixed tail and changes not one byte of the listing."""
    root = tree(tmp_path)
    server, _ = make(tmp_path)
    _, text = call(server, root=str(root), focus=["pkg/dream.py"])
    result = repomap.repo_map(root, focus=["pkg/dream.py"])
    assert result.text in text
    assert text.startswith(
        f"repo map: {result.nodes} files scanned, {result.definitions} definitions, "
        f"{result.edges} edges.\n"
    )
    assert "focus: pkg/dream.py\n" in text
    assert text.endswith(REPO_MAP_TAIL)
    # The footer travels: `README` has no dialect and must be counted, not dropped.
    assert "# omitted:" in text
    assert "unknown-language=1" in text


def test_no_focus_is_plain_centrality_and_says_so(tmp_path):
    root = tree(tmp_path)
    server, _ = make(tmp_path)
    _, text = call(server, root=str(root))
    assert "focus: (none) — plain centrality over the whole tree\n" in text


def test_an_empty_tree_names_the_reason_rather_than_rendering_nothing(tmp_path):
    """Two blank lines are not an answer. `REPO_MAP_EMPTY` says why there is no listing."""
    empty = tmp_path / "empty"
    empty.mkdir()
    server, _ = make(tmp_path)
    _, text = call(server, root=str(empty))
    assert REPO_MAP_EMPTY in text
    assert "repo map: 0 files scanned, 0 definitions, 0 edges." in text


def test_a_focus_that_is_not_a_scanned_source_is_ignored_and_never_refused(tmp_path):
    """Refusing here would break the tool the moment a caller named a `.md` they are editing."""
    root = tree(tmp_path)
    server, _ = make(tmp_path)
    is_error, text = call(server, root=str(root), focus=["docs/nothing-here.md"])
    assert not is_error
    assert "focus: docs/nothing-here.md\n" in text


def test_the_tail_never_claims_a_token_saving(tmp_path):
    """The one sentence this feature is not allowed to say.

    Row 10's build gate was REFUTED (`docs/roadmap-toolbox.md`): discovery is 0.114 % of
    real prompt tokens. A reply that implied otherwise would be the product contradicting
    the measurement that let it ship.
    """
    root = tree(tmp_path)
    server, _ = make(tmp_path)
    _, text = call(server, root=str(root))
    assert "precision pass, not a token saving" in text
    assert "0.114%" in text
    assert "REFUTED" in text
    assert "UTF-8 BYTES" in text
    # And the words a saving would be claimed IN. `cheaper` appears once, negated, so the
    # search runs over the text with that clause removed — otherwise the node passes on the
    # very sentence it exists to police.
    rest = text.replace("so a map does not make a session cheaper", "")
    for claim in ("saves tokens", "fewer tokens", "cheaper", "saving of"):
        assert claim not in rest, claim


# --------------------------------------------------------------------- the record


def test_the_event_log_records_the_decision_and_no_path_of_it(tmp_path):
    """`root` is what the operator typed and `focus` names the file they are editing.

    Neither is a decision this handler made, so neither is written down. The fixture's every
    path segment is a sentinel, so this asserts on bytes rather than on a policy.
    """
    root = tree(tmp_path)
    server, log = make(tmp_path)
    call(server, root=str(root), focus=["pkg/dream.py"])
    written = records(log)
    assert [r["tool"] for r in written] == ["repo_map"]
    assert written[0]["outcome"] == "mapped"
    assert sorted(written[0]["detail"]) == [
        "definitions",
        "edges",
        "files_rendered",
        "listing_bytes",
        "nodes",
    ]
    raw = log.read_bytes()
    assert SENTINEL.encode() not in raw
    assert b"dream.py" not in raw
    assert b"store.py" not in raw
