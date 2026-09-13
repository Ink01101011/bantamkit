"""The asset pack is the manifest for the MCP tool surface, checked AGAINST THE WIRE.

Why the oracle is a live `tools/list` and not `mcpserver.py`: this job's whole point is
that the Python source stops being the source of truth for the tool contract. A node that
compared the assets to the decorators would agree with them by construction and would
still agree after a port to a runtime that has no decorators. So every expectation here
is read off a real stdio handshake — the same bytes a host sees.

Two spawn details that cost a sibling job an hour, recorded so the next reader does not
re-derive them:

* `--store`, never `--start`. `--start` feeds `Memory.layered()`, which walks ancestors
  looking for `.bantamkit/memory`; a linked git worktree has none of its own, so it climbs
  out of the checkout and into `~/.bantamkit/memory`. `--store` takes the
  `Memory(store=...)` branch and never walks.
* `env["PYTHONPATH"]` is set DELIBERATELY, for the reason `test_mcpserver.py` states at
  length: `StdioServerParameters` defaults to `get_default_environment()`, which strips
  PYTHONPATH, so without this line the subprocess serves whatever `bantamkit` is
  INSTALLED rather than the checkout under test.
"""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

from bantamkit.assets import assets_root, load_tool  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src"

#: Every surface name the manifest may claim. `agent` is the eval agent's tool list
#: (`evalrun`, `filegraph`, `memory.component`); `mcp` is `tools/list`. A tool may claim
#: BOTH — `memory_save` and `memory_recall` do — so membership is a set, never a single
#: value. Which assets are agent-only is NOT hardcoded here on purpose: that fact now
#: lives in the manifest, and a test that also stated it would let the two disagree.
SURFACES = {"agent", "mcp"}

#: Tools RETIRED from every surface — `"surfaces": []` in the manifest. These ARE named
#: here, unlike the agent-only set, because retirement is a ruling (user, 2026-09-12,
#: job50 I5) and not a fact the manifest derives: an asset that quietly lost its `mcp`
#: claim must be a red diff, not a silently shorter roster. The asset stays in the pack
#: — the contract as it was last served, whole — and the handlers stay in `mcpserver.py`
#: as DORMANT code, so restoring either tool is the roster line plus the `"mcp"` claim.
RETIRED = {"bantamkit_read", "repo_map"}


def _served_listing(tmp_path, pack: Path | None = None) -> tuple[list[str], dict[str, dict]]:
    """The whole `tools/list` answer: the ORDER it arrived in, and the tools keyed by name.

    Order comes back separately rather than staying implicit in a mapping because it is the
    one part of the served surface the manifest does not carry: `assets/tools/` is a
    directory, a directory read is alphabetical, and the wire serves `memory_save` first. A
    helper that only ever handed back a dict made that difference unsayable.

    `pack` redirects the server's asset pack through `BANTAMKIT_ASSETS`, which is what lets
    a node serve a MUTATED pack and see what actually reaches the wire. When it is not
    given the subprocess is pinned to `assets_root()` — the same pack `_asset()` and
    `_manifest()` read in-process — so an operator who already has `BANTAMKIT_ASSETS` set
    cannot end up with one half of a comparison describing one pack and the other another.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["BANTAMKIT_ASSETS"] = str(pack if pack is not None else assets_root())
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "bantamkit.mcpserver", "--store", str(tmp_path / "store")],
        cwd=str(tmp_path),
        env=env,
    )

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                return [tool.name for tool in listing.tools], {
                    tool.name: {
                        "description": tool.description,
                        "inputSchema": tool.input_schema,
                        "outputSchema": tool.output_schema,
                    }
                    for tool in listing.tools
                }

    return asyncio.run(scenario())


def _served_tools(tmp_path) -> dict[str, dict]:
    """`{name: {description, inputSchema, outputSchema}}` as advertised over stdio."""
    return _served_listing(tmp_path)[1]


def _asset(name: str) -> dict:
    return json.loads((assets_root() / "tools" / f"{name}.json").read_text(encoding="utf-8"))


def _manifest() -> dict[str, dict]:
    """The whole asset pack, keyed by name — what a second runtime reads and nothing else."""
    return {f.stem: _asset(f.stem) for f in sorted((assets_root() / "tools").glob("*.json"))}


def test_every_served_tool_has_an_asset(tmp_path):
    """No tool reaches a host without a manifest entry — named, not counted.

    A count would say "not ten". This says WHICH tool a second runtime would have to
    read Python to discover.
    """
    served = _served_tools(tmp_path)
    have = {f.stem for f in (assets_root() / "tools").glob("*.json")}
    assert sorted(served) == [
        "bantamkit_status",
        "build_identity",
        "memory_compact",
        "memory_dream",
        "memory_recall",
        "memory_save",
        "shiftwork_clock_in",
        "shiftwork_clock_out",
        "shiftwork_status",
        "skill_audit",
        "token_ledger",
        "validate_json",
    ]
    assert sorted(set(served) - have) == []


def test_each_asset_advertises_what_the_server_actually_advertises(tmp_path):
    """Description, INPUT schema and OUTPUT schema, per tool, byte-equal to the wire.

    Not "a tidied-up version of it": a pydantic-generated `title` in a served schema is
    part of what hosts receive today, so it is part of the manifest today.

    WHAT THIS NODE DOES NOT DO, corrected because it used to claim the opposite. It said
    "correcting a schema is a different change from recording one, and this node is what
    makes the difference visible — it goes red for BOTH". It goes red for NEITHER, and
    that was measured, not argued: dropping `build_identity.output_schema.title` and
    adding the five-value enum to `shiftwork_clock_out.status` moved the served surface
    (7712 -> 7820 bytes of captured `tools/list`, sha256 71de1e87… -> ed180696…) and left
    this file, `test_mcpserver.py`, `test_conformance.py` and `test_build_identity.py` at
    57 passed. Since `_from_manifest` builds the wire FROM this asset, the comparison is a
    function equalling itself; it can only catch a runtime that stops reading the manifest
    at all, which is what `test_the_advertised_surface_is_read_from_the_asset_pack_at_
    startup` covers by mutation. The node that makes a schema change visible is
    `test_the_served_surface_is_the_one_the_committed_golden_declares`.
    """
    served = _served_tools(tmp_path)
    for name, wire in sorted(served.items()):
        asset = _asset(name)
        assert asset["name"] == name
        assert asset["description"] == wire["description"], name
        assert asset["parameters"] == wire["inputSchema"], name
        assert asset["output_schema"] == wire["outputSchema"], name


#: The largest description a host will show whole. Claude Code truncates a tool
#: description at 2,048 characters and reports nothing when it does; the cut is undocumented,
#: hence the margin. The SAME number as `DESCRIPTION_BUDGET` in
#: `runtime-ts/test/packaging.test.mjs`, deliberately: a budget that differed per runtime
#: would be a divergence, and this is not one.
DESCRIPTION_BUDGET = 1900


def test_no_served_tool_description_exceeds_the_budget_the_host_truncates_at(tmp_path):
    """Every description, AS IT ARRIVES ON THE WIRE, fits under the host's silent cut.

    Why this is a second literal and not a conformance case: both runtimes serve
    `asset["description"]` verbatim from one shared file, so a differential between them
    agrees while both are over budget — it was 8,161 chars on both sides and green. The
    Node case measures the vendored asset; this one measures what the Python serving path
    actually hands a host, so it is an independent witness that nothing between the asset
    and `tools/list` re-expands what the asset trimmed. Reading the asset here would make
    it a copy of the Node case, not a second witness.

    Counted in DECODED characters — what the host sees after JSON decoding — not bytes.
    """
    served = _served_tools(tmp_path)
    assert served, "tools/list served nothing; a bound over an empty set holds vacuously"
    over = {
        name: len(wire["description"])
        for name, wire in sorted(served.items())
        if len(wire["description"]) > DESCRIPTION_BUDGET
    }
    assert not over, (
        f"served descriptions over the {DESCRIPTION_BUDGET}-character budget: {over}. "
        "The host cuts at 2,048 and shows no error; move the excess into docs/, do not "
        "raise the budget."
    )


def test_the_manifest_names_the_surface_each_tool_serves(tmp_path):
    """Gap 1, executable: `tools/list` is reproducible from the JSON alone.

    Before this field existed, `assets/tools/` was ten files serving two surfaces with
    nothing in them saying which. (served-tools: dated — both numbers below describe a
    hypothetical at a past commit, not the surface today.) A second runtime that
    registered the directory would
    have served ten tools instead of seven and grown the surface by three, and no test
    would have noticed, because the only machine-readable statement of the split was a
    Python set inside this file.

    The check runs in BOTH directions on purpose. `served == mcp-claiming assets` alone
    would pass if a tool quietly stopped claiming `mcp` AND stopped being served; pinning
    the served names too is what makes this a manifest rather than an echo.
    """
    served = _served_tools(tmp_path)
    manifest = _manifest()

    for name, asset in manifest.items():
        surfaces = asset["surfaces"]
        assert surfaces or name in RETIRED, name
        assert set(surfaces) <= SURFACES, (name, surfaces)
        assert surfaces == sorted(set(surfaces)), (name, surfaces)

    assert sorted(n for n, a in manifest.items() if "mcp" in a["surfaces"]) == sorted(served)

    # The proof case for "a tool can be on both": these two are registered by
    # `memory.component` for the eval agent AND by `mcpserver` for hosts. A shape that
    # forced one answer would have to lie about one of the two registrations.
    assert manifest["memory_save"]["surfaces"] == ["agent", "mcp"]
    assert manifest["memory_recall"]["surfaces"] == ["agent", "mcp"]


def test_the_eval_agent_assets_are_not_judged_against_the_mcp_surface(tmp_path):
    """Invariant 1, executable: two tool surfaces share this directory.

    `document_list`, `document_read` and `file_graph` are the eval agent's and are
    ABSENT from `tools/list` by design. A future tidy-up that "removes the orphans"
    breaks `evalrun` and `filegraph` silently; this node is the thing that stops it.

    It used to name those three in a constant. It now DERIVES them from `surfaces`, which
    is the whole point of gap 1 closing: if the derivation went wrong the set would come
    back empty and the two assertions below would pass vacuously, so the count is pinned.
    """
    served = _served_tools(tmp_path)
    manifest = _manifest()
    agent_only = {n for n, a in manifest.items() if a["surfaces"] == ["agent"]}

    assert agent_only == {"document_list", "document_read", "file_graph"}
    assert agent_only & set(served) == set()


def test_the_retired_tools_are_exactly_the_ruled_ones_and_none_is_served(tmp_path):
    """I5 (job50), executable in both directions: `repo_map` and `bantamkit_read` are off.

    The ruling retired two names and kept a third (`escalate` — never an MCP tool here, so
    there is nothing for it to keep). Two directions, for the reason the manifest test
    gives: `served ∩ RETIRED == ∅` alone would pass if a retired asset were deleted or
    renamed, and `assets with [] == RETIRED` alone would pass if the server registered a
    tool the manifest says is on no surface — which `_from_manifest` refuses at startup,
    so that half is what turns a re-added roster line into a server that will not start
    rather than a tool that quietly ships. Put a name back on the roster tomorrow and the
    startup refusal takes every node in this file with it; put `"mcp"` back on its asset
    too and this node and the served-name pin above go red instead. The cross-runtime
    half — that Node's `tools/list` dropped the same two — is `tools/conformance`, not
    this file.
    """
    served = _served_tools(tmp_path)
    manifest = _manifest()
    retired = {n for n, a in manifest.items() if a["surfaces"] == []}

    assert retired == RETIRED
    assert retired & set(served) == set()
    for name in RETIRED:
        # The contract is kept WHOLE, not hollowed: a port's dormant handler and this
        # one still have the same description and both schemas to agree on.
        assert manifest[name]["description"]
        assert manifest[name]["parameters"]["type"] == "object"
        assert manifest[name]["output_schema"] is not None


def test_the_new_manifest_fields_do_not_reach_the_eval_agents_tool_objects():
    """Invariant 1's other half: adding to the manifest must not change what the model sees.

    `load_tool` builds the agent-facing `Tool` by naming three keys, so `surfaces` and
    `output_schema` are invisible to `evalrun`, `filegraph` and `memory.component`. That
    is a property, not an accident — a loader that splatted the dict would have quietly
    added two keys to every tool definition an eval-run model is shown, moving the OTHER
    surface inside a change that claims to have moved neither.
    """
    tool = load_tool("document_list")
    assert not hasattr(tool, "surfaces")
    assert not hasattr(tool, "output_schema")
    assert tool.parameters == _asset("document_list")["parameters"]


# ---------------------------------------------------------------------------
# The declaration gate: the served surface, frozen, in a file the server never reads.
#
# WHY A SECOND COPY OF SOMETHING THE ASSETS ALREADY SAY. Since `_from_manifest` builds
# every advertised field out of `assets/tools/`, every node that compares an asset to the
# wire is comparing a function to itself and stays green through any schema edit. Nothing
# in the tree could tell "the contract changed" from "the contract is fine". This file is
# the other end of a double entry: it was captured OFF THE WIRE, it lives under
# `runtime-py/tests/data/` where no runtime loads it (deliberately not under `assets/`,
# which would fold it into `assets_digest` and ship it to hosts), and it is edited by hand.
# A wire move now has to be written down twice or the suite is red.
#
# WHY IT DOES NOT GET RE-BASELINED INTO NOTHING, which is the objection this repo already
# sustained once — `test_build_identity.py:25` refuses a literal digest because "a golden
# that co-moves with every file in the package would be re-baselined into meaninglessness
# within a week". Three properties keep this one narrow:
#
# * It co-moves with the TOOL CONTRACT and with nothing else. Editing any `.py`, any
#   skill, any rubric, adding a test, bumping a version — none of it touches this file.
#   At `da9079a` the only inputs are seven descriptions and fourteen schemas.
# * It is not a digest. The failing node names the JSON path that moved and prints old
#   and new, so the diff a reviewer reads is `build_identity.outputSchema.title:
#   'build_identity_toolDictOutput' -> <absent>`, not two hex strings.
# * There is no regeneration command, on purpose. Updating means editing this JSON by
#   hand in the same commit as the asset, which is the declaration; a `--update-golden`
#   flag would restore exactly the reflex this node exists to break.
#
# HOW IT WAS CAPTURED: a real stdio `initialize` + `tools/list` against
# `python -m bantamkit.mcpserver --store <tmp>` with `PYTHONPATH` pointed at
# `runtime-py/src`, at `da9079a`, the same instrument `_served_listing` uses.
GOLDEN = Path(__file__).resolve().parent / "data" / "served-tool-surface.json"


def _golden() -> dict:
    """The committed surface. Its shape is pinned so junk cannot accumulate beside it."""
    blob = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(blob) == {"order", "tools"}, sorted(blob)
    return blob


def _leaves(value, prefix: str = "") -> dict[str, object]:
    """Flatten a JSON value to `{dotted.path[i]: leaf}`, so a diff can NAME what moved.

    Empty containers become a marker leaf rather than vanishing: `{"properties": {}}` and
    `{"properties": []}` are different wire bytes, and a flattener that dropped both would
    call them equal.
    """
    if isinstance(value, dict):
        if not value:
            return {prefix: "<empty object>"}
        out: dict[str, object] = {}
        for key, sub in value.items():
            out.update(_leaves(sub, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list):
        if not value:
            return {prefix: "<empty array>"}
        out = {}
        for index, sub in enumerate(value):
            out.update(_leaves(sub, f"{prefix}[{index}]"))
        return out
    return {prefix: value}


def _surface_differences(golden: dict, wire: dict) -> list[str]:
    """Every place the two disagree, one line each, path first."""
    left, right = _leaves(golden), _leaves(wire)
    absent = "<absent>"
    return [
        f"  {path}: {left.get(path, absent)!r} -> {right.get(path, absent)!r}"
        for path in sorted(set(left) | set(right))
        if left.get(path, absent) != right.get(path, absent)
    ]


def test_the_served_surface_is_the_one_the_committed_golden_declares(tmp_path):
    """A change to what hosts are told must be DECLARED, not merely noticed.

    This is the node the job was missing. Until it existed the only thing between an
    accidental wire move and a green suite was that four consecutive units each happened
    to run a manual before/after capture by hand; the next unit — the one that fixes the
    five recorded schema defects — would have had no automated guard at all.

    It pins CONTENT, keyed by name, and says nothing about order; the order lives one node
    below so that a reordering and a contract change cannot arrive as the same failure.
    """
    _, wire = _served_listing(tmp_path)
    golden = _golden()
    differences = _surface_differences(golden["tools"], wire)
    assert not differences, (
        "the served tool surface no longer matches "
        f"{GOLDEN.relative_to(Path(__file__).resolve().parents[2])}:\n"
        + "\n".join(differences)
        + "\n\nIf the move is intended, edit that file by hand in THIS commit so the new "
        "contract is written down where a reviewer reads it. There is no regeneration "
        "command on purpose. If it is not intended, you just changed what every host and "
        "the Node port are told."
    )


def test_the_golden_records_the_order_the_wire_actually_serves(tmp_path):
    """Order is served, is NOT in the manifest, and so is pinned here or nowhere.

    `assets/tools/` is a directory: read it and you get alphabetical, `build_identity`
    first. The wire serves registration order from `build_server`, `memory_save` first.
    Every "the manifest reproduces the wire byte-for-byte" claim in this job holds only up
    to tool ordering, and this is the node that says so out loud.

    It is SEPARATE from the content node deliberately. A reorder is a different kind of
    move from a schema change — cheap to make by accident while editing the `tools` list,
    harmless to most hosts, and something the Node port has to decide about explicitly
    rather than inherit — so it gets its own red with its own message instead of being
    buried in a content diff.
    """
    order, wire = _served_listing(tmp_path)
    golden = _golden()
    assert order == golden["order"], (
        "the order tools/list serves moved: "
        f"{golden['order']} -> {order}. Nothing in assets/tools/ records order, so this "
        "file is the only place it is written down."
    )
    # Vacuity: an order pinned over a set that no longer matches the surface is a golden
    # agreeing with itself. The names must be the served names, and all of them.
    assert sorted(order) == sorted(wire) == sorted(golden["tools"])


# ---------------------------------------------------------------------------
# The other half: registration must READ the manifest, not merely agree with it.


def _mutant_schemas(name: str) -> tuple[str, dict, dict]:
    """A description and two schemas no signature could ever derive, per tool."""
    return (
        f"MUTATED BY THE GATE: {name} description reached the wire from the asset pack.",
        {
            "type": "object",
            "title": f"{name}MutatedArguments",
            "properties": {"only_the_manifest_says_this": {"type": "string", "const": name}},
            "required": ["only_the_manifest_says_this"],
        },
        {
            "type": "object",
            "title": f"{name}MutatedOutput",
            "properties": {"only_the_manifest_says_this": {"type": "string", "const": name}},
        },
    )


def test_the_advertised_surface_is_read_from_the_asset_pack_at_startup(tmp_path):
    """Mutate the pack the server loads; every advertised field must move with it.

    THIS IS THE NODE THAT MAKES `surfaces` AND `output_schema` LOAD-BEARING FOR ALL EIGHT
    TOOLS, and it exists because the previous evidence was the wrong instrument. T3 called
    both fields "load-bearing, measured by mutation" — but that mutation was performed BY
    HAND on a copy, which proves the asset REACHES the wire and proves nothing about
    whether any node GUARDS it. Reducing `_from_manifest` to description-only, so the
    schemas come back off the Python signature the way `main` served them, left the wire
    byte-identical and the surface suite at 57 passed; removing the `output_schema`
    override entirely was equally invisible. Only `memory_save` and `memory_recall` were
    covered, and only by accident — their assets predate this job and happen to differ
    from what pydantic derives.

    The mutation is committed here instead. `BANTAMKIT_ASSETS` points a real server at a
    copied pack whose ten served entries carry a description and two schemas pydantic
    could not produce from a zero-argument or six-argument Python function, and the wire
    is required to carry them verbatim. A runtime that derived any of the three from the
    signature reddens on all ten.

    It says nothing about WHICH schema is right — that is the golden's job. It says the
    JSON is what is being served, which is the premise the whole Node port rests on.
    """
    pack = tmp_path / "pack"
    shutil.copytree(assets_root(), pack)
    expected = {}
    for path in sorted((pack / "tools").glob("*.json")):
        asset = json.loads(path.read_text(encoding="utf-8"))
        if "mcp" not in asset["surfaces"]:
            continue
        description, parameters, output_schema = _mutant_schemas(asset["name"])
        asset["description"] = description
        asset["parameters"] = parameters
        asset["output_schema"] = output_schema
        path.write_text(json.dumps(asset, indent=2) + "\n", encoding="utf-8")
        expected[asset["name"]] = {
            "description": description,
            "inputSchema": parameters,
            "outputSchema": output_schema,
        }

    assert sorted(expected) == sorted(_golden()["tools"])  # the mutation covered all ten

    run = tmp_path / "run"
    run.mkdir()
    order, wire = _served_listing(run, pack=pack)
    assert sorted(order) == sorted(expected)
    assert not _surface_differences(expected, wire), "\n".join(
        _surface_differences(expected, wire)
    )
