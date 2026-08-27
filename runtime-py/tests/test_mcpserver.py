"""MCP surface: tools mirror the asset pack, memory round-trips, validation feedback."""

import asyncio
import json
import os
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client, MCPError  # noqa: E402

import bantamkit  # noqa: E402
from bantamkit.assets import load_skill, load_tool  # noqa: E402

# The checkout under test, so a subprocess can be pointed at IT rather than at whatever
# `bantamkit` is installed in the interpreter that spawns it.
SRC = Path(__file__).resolve().parents[1] / "src"
from bantamkit.mcpserver import (  # noqa: E402
    _build_memory,
    _parse_args,
    _version,
    build_server,
)
from bantamkit.memory import Memory, RecallOutcome  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def make_server(tmp_path):
    return build_server(Memory(store=tmp_path / "store"))


VALID_SCHEMA = {
    "type": "object",
    "required": ["total"],
    "properties": {"total": {"type": "integer"}},
}


def test_lists_exactly_the_ten_tools(tmp_path):
    """One server, one entry point: memory and shiftwork ride the same instance.

    Seven since `build_identity` (RB-P84's second half) and EIGHT since
    `bantamkit_status` (`docs/status.md`): the list is EXACT, so a tool added to the
    server is a deliberate edit here. The assertion is not relaxed to a membership check —
    an exact list is the only form that notices a tool arriving.
    """

    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            names = sorted(t.name for t in (await c.list_tools()).tools)
            assert names == [
                "bantamkit_read",
                "bantamkit_status",
                "build_identity",
                "memory_compact",
                "memory_recall",
                "memory_save",
                "shiftwork_clock_in",
                "shiftwork_clock_out",
                "shiftwork_status",
                "validate_json",
            ]

    run(scenario())


def test_memory_tool_schemas_match_asset_pack_exactly(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert tools["memory_save"].input_schema == load_tool("memory_save").parameters
            assert tools["memory_recall"].input_schema == load_tool("memory_recall").parameters

    run(scenario())


def test_server_instructions_are_the_memory_skill(tmp_path):
    assert make_server(tmp_path).instructions == load_skill("memory")


def test_save_then_recall_round_trip(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            saved = await c.call_tool(
                "memory_save",
                {
                    "type": "project",
                    "name": "payments-owner",
                    "description": "who owns the payments API",
                    "body": "the billing team owns the payments API",
                },
            )
            assert "saved 'payments-owner'" in saved.content[0].text
            recalled = await c.call_tool("memory_recall", {"query": "who owns the payments API"})
            assert "the billing team owns the payments API" in recalled.content[0].text

    run(scenario())


def test_save_reports_validation_error_as_text(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            # `BAD NAME` used to belong here; P1b normalization now saves it as
            # `bad-name` (see test_save_normalizes_over_mcp below). A name with
            # characters no normalization can rescue keeps this test's subject —
            # validation errors come back as text, not as a raised tool error.
            saved = await c.call_tool(
                "memory_save",
                {"type": "project", "name": "bad/name!", "description": "d", "body": "b"},
            )
            assert saved.content[0].text.startswith("error:")

    run(scenario())


def test_save_normalizes_over_mcp(tmp_path):
    """The MCP surface goes through the same component, so P1b applies there too."""

    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            saved = await c.call_tool(
                "memory_save",
                {"type": "project", "name": "BAD NAME", "description": "d", "body": "b"},
            )
            assert saved.content[0].text == "saved 'bad-name'"

    run(scenario())


def test_layered_recall_reads_granted_store_readonly(tmp_path, monkeypatch):
    grant = tmp_path / "teamdocs" / ".bantamkit" / "memory"
    Memory(store=grant).store.save(
        "reference", "prod-endpoint", "prod api host", "api.example-prod.io serves /v3", ()
    )
    project_root = tmp_path / "proj"
    (project_root / ".bantamkit" / "memory").mkdir(parents=True)
    (project_root / ".bantamkit" / "config.yaml").write_text(
        f"extra_stores:\n  - {grant}\n", encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    server = build_server(Memory.layered(start=project_root))

    async def scenario():
        async with Client(server) as c:
            recalled = await c.call_tool("memory_recall", {"query": "prod api host"})
            text = recalled.content[0].text
            assert "api.example-prod.io" in text
            assert "[extra:teamdocs]" in text

    run(scenario())


def test_validate_json_accepts_valid_output(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            r = await c.call_tool(
                "validate_json", {"output": '{"total": 42}', "schema": VALID_SCHEMA}
            )
            assert r.structured_content == {"valid": True, "feedback": None}

    run(scenario())


def test_validate_json_returns_pointed_feedback_on_violation(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            r = await c.call_tool(
                "validate_json", {"output": '{"total": "x"}', "schema": VALID_SCHEMA}
            )
            sc = r.structured_content
            assert sc["valid"] is False
            assert "total" in sc["feedback"]
            assert "Return ONLY a JSON object matching the schema." in sc["feedback"]

    run(scenario())


def test_validate_json_flags_unparseable_output(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            r = await c.call_tool(
                "validate_json", {"output": "not json at all", "schema": VALID_SCHEMA}
            )
            sc = r.structured_content
            assert sc["valid"] is False
            assert "not parseable JSON" in sc["feedback"]

    run(scenario())


def test_skill_resource_serves_memory_skill(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            res = await c.read_resource("bantamkit://skills/memory")
            assert "memory_save" in res.contents[0].text

    run(scenario())


def test_rubric_resource_serves_yaml_verbatim(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            res = await c.read_resource("bantamkit://rubrics/task-completion")
            assert "threshold" in res.contents[0].text

    run(scenario())


def test_missing_resource_errors_name_the_asset(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            with pytest.raises(MCPError, match="unknown rubric asset: nope"):
                await c.read_resource("bantamkit://rubrics/nope")
            with pytest.raises(MCPError, match="unknown skill asset: nope"):
                await c.read_resource("bantamkit://skills/nope")

    run(scenario())


def test_resource_templates_listed(tmp_path):
    async def scenario():
        async with Client(make_server(tmp_path)) as c:
            listed = await c.list_resource_templates()
            uris = sorted(rt.uri_template for rt in listed.resource_templates)
            assert uris == ["bantamkit://rubrics/{name}", "bantamkit://skills/{name}"]

    run(scenario())


EXAMPLE_CHECKPOINT = (
    Path(__file__).resolve().parents[2] / "tools" / "shiftwork" / "example-checkpoint.json"
)


def checkpoint_copy(tmp_path):
    path = tmp_path / "checkpoint.json"
    path.write_text(EXAMPLE_CHECKPOINT.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_shiftwork_round_trip_beside_memory_on_one_server(tmp_path):
    """The whole workflow over MCP, on the same instance that serves memory_save."""

    async def scenario():
        path = checkpoint_copy(tmp_path)
        async with Client(make_server(tmp_path)) as c:
            saved = await c.call_tool(
                "memory_save",
                {"type": "project", "name": "shiftwork-job", "description": "d", "body": "b"},
            )
            assert "saved" in saved.content[0].text
            brief = (await c.call_tool("shiftwork_clock_in", {"checkpoint": str(path)}))
            assert brief.structured_content["result"] == "brief"
            assert brief.structured_content["unit"]["id"] == "U3"
            out = await c.call_tool(
                "shiftwork_clock_out",
                {
                    "checkpoint": str(path),
                    "unit_id": "U3",
                    "status": "done",
                    "handoff_patch": {"next_action": "Review the diff per briefs/U4.md."},
                    "history_entry": {"unit": "U3", "outcome": "done"},
                    "accounting": {"tokens": 99, "duration": 1.5, "model": "haiku"},
                },
            )
            assert out.structured_content["result"] == "ok"
            assert out.structured_content["cursor"] == "U4"
            again = (await c.call_tool("shiftwork_clock_in", {"checkpoint": str(path)}))
            assert again.structured_content["unit"]["id"] == "U4"
            status = await c.call_tool("shiftwork_status", {"checkpoint": str(path)})
            assert status.structured_content["units"] == {"done": 2, "todo": 1}
        log = json.loads(
            (tmp_path / "checkpoint.json.log.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        assert log["model"] == "haiku" and log["unit"] == "U3"

    run(scenario())


def test_shiftwork_refusals_come_back_structured_not_raised(tmp_path):
    async def scenario():
        path = checkpoint_copy(tmp_path)
        ckpt = json.loads(path.read_text(encoding="utf-8"))
        ckpt["handoff"]["open_questions"] = ["ask the user"]
        path.write_text(json.dumps(ckpt), encoding="utf-8")
        async with Client(make_server(tmp_path)) as c:
            r = await c.call_tool("shiftwork_clock_in", {"checkpoint": str(path)})
            assert r.structured_content["result"] == "escalate"
            bad = await c.call_tool(
                "shiftwork_clock_out",
                {
                    "checkpoint": str(path),
                    "unit_id": "U3",
                    "status": "not-a-status",
                    "handoff_patch": {},
                    "history_entry": {"unit": "U3", "outcome": "done"},
                },
            )
            assert bad.structured_content["result"] == "error"

    run(scenario())


def test_store_and_start_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        _parse_args(["--store", "a", "--start", "b"])


def test_build_memory_store_flag_yields_single_layer(tmp_path):
    mem = _build_memory(_parse_args(["--store", str(tmp_path / "s"), "--k", "5"]))
    assert mem.k == 5
    assert len(mem._layers) == 1


def test_build_memory_default_is_layered(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    mem = _build_memory(_parse_args(["--start", str(tmp_path / "proj")]))
    assert len(mem._layers) >= 2


def test_the_store_flag_outranks_the_env_pin_and_start_does_not(tmp_path, monkeypatch):
    """`docs/mcp.md` tells operators `--store` still wins; this is that claim, run.

    They are not two settings of one dial. `--store` names a store outright and
    never enters resolution, so the pin has nothing to outrank; `--start` only says
    where a walk would begin, and `BANTAMKIT_MEMORY_DIR` replaces the walk.
    """
    from bantamkit.memory.layers import MEMORY_DIR_ENV

    named = tmp_path / "named"
    pinned = tmp_path / "pinned"
    for d in (named, pinned):
        (d / "facts").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    monkeypatch.setenv(MEMORY_DIR_ENV, str(pinned))

    assert _build_memory(_parse_args(["--store", str(named)])).store.root == named
    assert _build_memory(_parse_args(["--start", str(tmp_path)])).store.root == pinned


def test_missing_extra_yields_install_hint(tmp_path, monkeypatch):
    import bantamkit.mcpserver as m

    monkeypatch.setattr(m, "MCPServer", None)
    with pytest.raises(SystemExit, match=r"bantamkit\[mcp\]"):
        m.build_server(Memory(store=tmp_path / "store"))


def test_recall_k_clamped_to_advertised_bounds(tmp_path):
    seen = {}

    # `recall_outcome`, not `recall`: the handler needs the layer walk's counts for the
    # event log, so that is the method it calls and the one a probe has to intercept. The
    # clamp under test has not moved — it still happens in the handler, before the
    # component sees `k` at all.
    class Probe(Memory):
        def recall_outcome(self, query, k=None):
            seen["k"] = k
            return RecallOutcome(
                reply="ok",
                status="answered",
                budget=self.k,
                layers=1,
                reached=1,
                returned=1,
                candidates=1,
                source="project",
            )

    server = build_server(Probe(store=tmp_path / "store"))

    async def scenario():
        async with Client(server) as c:
            await c.call_tool("memory_recall", {"query": "q", "k": 999})
            assert seen["k"] == 5
            await c.call_tool("memory_recall", {"query": "q", "k": 0})
            assert seen["k"] == 1
            await c.call_tool("memory_recall", {"query": "q"})
            assert seen["k"] is None

    run(scenario())


def test_empty_store_flag_is_rejected():
    with pytest.raises(SystemExit, match="non-empty"):
        _build_memory(_parse_args(["--store", ""]))


def test_stdio_subprocess_initializes(tmp_path):
    import sys

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    # THE ENVIRONMENT IS PASSED EXPLICITLY, and that is the point of this line.
    # `StdioServerParameters` defaults to `get_default_environment()`, which passes only
    # HOME/LOGNAME/PATH/SHELL/TERM/USER — **`PYTHONPATH` is stripped**. So this node used
    # to serve whatever `bantamkit` happened to be INSTALLED in the interpreter's
    # environment, never the checkout under test. On a developer machine with a stale
    # install that is a different build from the one being reviewed, and the node passed
    # while asserting a tool count that the checkout had already moved past; CI, which
    # installs the branch, was the only place it could fail. That is `RB-P55`/`RB-P70`
    # reaching through a subprocess.
    #
    # AMENDED 2026-08-25 (served-tools: dated — the 6 and 7 below are a quotation of a
    # measurement this machine can no longer reproduce, not a claim about the surface).
    # This paragraph used to end "it is measured: with the default
    # environment this server answers with 6 tools, and with the line below it answers
    # with 7." That delta was real when it was written and THIS MACHINE CAN NO LONGER
    # PRODUCE IT. Driving both environments over stdio (`initialize` ->
    # `notifications/initialized` -> `tools/list`, `cwd` and `HOME` in a fresh temp dir)
    # measures 8 AND 8. The reason is structural, not drift: this venv holds an EDITABLE
    # install — `.venv/lib/python3.*/site-packages/_editable_impl_bantamkit.pth`, and
    # `import bantamkit` resolves to `runtime-py/src/bantamkit/__init__.py` — so the
    # stripped-`PYTHONPATH` arm reaches the same checkout as the pinned arm and the two
    # arms cannot differ. The 6/7 reading needed a STALE NON-EDITABLE install, and that
    # environment is gone from this machine.
    #
    # 8 and 8 is therefore NOT restated here as a live property: it would assert that
    # this node still discriminates, when what it currently shows is that it cannot. The
    # `env=` line below stays exactly as it is — it is correct, and it is the only thing
    # standing between this node and the stale-install failure mode above on any machine
    # that does have one.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from bantamkit.mcpserver import main; main()", "--start", str(tmp_path)],
        cwd=str(tmp_path),
        env=env,
    )

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.server_info.name == "bantamkit"
                assert init.server_info.version == bantamkit.__version__
                assert (init.instructions or "").startswith("# Memory")
                tools = await session.list_tools()
                # An EXACT list, not a count, for the reason the sibling node states: a
                # count says "not six" and an exact list says WHICH tool arrived.
                assert sorted(t.name for t in tools.tools) == [
                    "bantamkit_read",
                    "bantamkit_status",
                    "build_identity",
                    "memory_compact",
                    "memory_recall",
                    "memory_save",
                    "shiftwork_clock_in",
                    "shiftwork_clock_out",
                    "shiftwork_status",
                    "validate_json",
                ]

    run(scenario())


def test_module_entrypoint_serves_over_stdio(tmp_path):
    """`python -m bantamkit.mcpserver` must SERVE, not exit 0 in silence.

    Its sibling above spawns `-c "from bantamkit.mcpserver import main; main()"`, which
    routes around the module entry point entirely. That workaround is why the missing
    `__main__` guard survived: with no guard, `-m` imported the module, defined `main`,
    and exited 0 with zero bytes on both streams, so every client reported
    CONNECTION_CLOSED -- the symptom, never the cause -- while this suite stayed green.
    Measured 2026-08-21 with the guard deleted: this node fails at `initialize`; with the
    guard present it completes the handshake. `-m` is the invocation a host config
    reaches for when the console script is not on PATH, so it is a contract surface and
    it gets its own node.

    `env=` is not optional here, for the reason the sibling states at length: the mcp
    stdio client's `get_default_environment()` strips PYTHONPATH, so without this the
    subprocess would serve whatever `bantamkit` is INSTALLED rather than this checkout.
    """
    import sys

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "bantamkit.mcpserver", "--start", str(tmp_path)],
        cwd=str(tmp_path),
        env=env,
    )

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.server_info.name == "bantamkit"
                assert init.server_info.version == bantamkit.__version__
                tools = await session.list_tools()
                # An EXACT list, matching both siblings: a count says "not seven" and a
                # list names WHICH tool the module entry point is or is not serving.
                assert sorted(t.name for t in tools.tools) == [
                    "bantamkit_read",
                    "bantamkit_status",
                    "build_identity",
                    "memory_compact",
                    "memory_recall",
                    "memory_save",
                    "shiftwork_clock_in",
                    "shiftwork_clock_out",
                    "shiftwork_status",
                    "validate_json",
                ]

    run(scenario())


def test_nonpositive_k_flag_is_rejected():
    with pytest.raises(SystemExit, match=">= 1"):
        _build_memory(_parse_args(["--k", "0"]))


@pytest.mark.parametrize("budget", [1, 512, 4096, 24_000, 100_000])
def test_index_budget_reaches_the_store_on_both_deployment_paths(tmp_path, monkeypatch, budget):
    """P5, swept: the flag has to survive BOTH branches of `_build_memory`, not one.

    `--store` and the layered default build the store through different calls, so a
    flag threaded into only one of them passes a single-value node and ships broken
    for whichever deployment the fixture did not pick.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    single = _build_memory(
        _parse_args(["--store", str(tmp_path / "s"), "--index-budget", str(budget)])
    )
    assert single.store.index_budget == budget
    layered = _build_memory(
        _parse_args(["--start", str(tmp_path / "proj"), "--index-budget", str(budget)])
    )
    assert layered.store.index_budget == budget


def test_index_budget_defaults_to_the_store_default_not_a_restated_number(tmp_path):
    """A second literal here would drift from `store.py`; read the one that ships."""
    from bantamkit.memory import DEFAULT_INDEX_BUDGET

    mem = _build_memory(_parse_args(["--store", str(tmp_path / "s")]))
    assert mem.store.index_budget == DEFAULT_INDEX_BUDGET


@pytest.mark.parametrize("budget", ["0", "-1"])
def test_nonpositive_index_budget_flag_is_rejected(tmp_path, budget):
    with pytest.raises(SystemExit, match=">= 1"):
        _build_memory(_parse_args(["--store", str(tmp_path / "s"), "--index-budget", budget]))


PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_server_advertises_the_version_this_checkout_declares(tmp_path):
    """RB-P45. The advertised version is a property of the tree, not of the last `pip`.

    Both sides of this equality are read out of the checkout, so the node is a repo-content
    check: it cannot be reddened or greened by reinstalling anything.
    """
    assert make_server(tmp_path).version == bantamkit.__version__


def test_advertised_version_does_not_come_from_installed_metadata(monkeypatch):
    """The regression RB-P45 names, pinned so a fresh-install CI can still see it.

    A stale editable install is not a `PackageNotFoundError`, so reading `dist-info` returns
    a confidently wrong number rather than falling back. Standing in a wrong answer where
    `importlib.metadata` would be consulted proves the answer is not sourced from there --
    and unlike comparing against the real install, this stays red on any machine.
    """
    import importlib.metadata

    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "9.9.9-from-dist-info")
    assert _version() == bantamkit.__version__


def test_packaging_reads_the_same_declaration_the_server_reads():
    """One source of truth: the wheel's version and the served version are the same bytes."""
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert "version" in config["project"]["dynamic"]
    assert "version" not in config["project"], "a static version would shadow the module's"
    declared = PYPROJECT.parent / config["tool"]["hatch"]["version"]["path"]
    assert declared.resolve() == Path(bantamkit.__file__).resolve()


# --- `--assets-root`: the flag runtime-ts had and runtime-py did not ---------------------
#
# CLAUDE.md, "Two runtimes, one surface". `runtime-ts/src/cli.ts` has carried `--assets-root`
# since it shipped; nothing here compared the two CLIs, so nothing noticed. These nodes drive
# the Python half through a real process, because the claim is about a wire -- exit code,
# which stream, how many lines -- and an in-process `_parse_args([...])` cannot see any of it.


def _run_cli(argv, cwd):
    """`python -m bantamkit.mcpserver ...` against THIS checkout, from an unrelated cwd.

    PYTHONPATH is set explicitly: without it the child imports whatever `bantamkit` the
    interpreter has installed, which in a worktree is the OTHER checkout's source.
    """
    import subprocess
    import sys

    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env.pop("BANTAMKIT_ASSETS", None)  # arm 1 of the resolver would make the node vacuous
    return subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", *argv],
        capture_output=True,
        cwd=str(cwd),
        env=env,
    )


def test_assets_root_flag_prints_the_root_and_a_file_count_on_stdout(tmp_path):
    """Two lines, `<root>\\n<count> files\\n`, exit 0, nothing on stderr.

    The count is recomputed here with `os.walk`, not with the `rglob` the implementation
    uses, so a fix that counted directories as well as files stays red.

    The ROOT is not compared against runtime-ts and never will be: Python resolves the
    repo-root `assets/`, Node resolves the `runtime-ts/assets/` that `sync-assets.mjs`
    vendors. Same bytes, different paths, by construction. The COUNT is the comparable half.
    """
    from bantamkit.assets import assets_root

    root = assets_root()
    expected = sum(len(names) for _dirpath, _dirnames, names in os.walk(root))
    done = _run_cli(["--assets-root"], tmp_path)

    assert done.returncode == 0
    assert done.stderr == b""
    assert done.stdout == f"{root}\n{expected} files\n".encode()
    assert done.stdout.count(b"\n") == 2


def test_assets_root_flag_returns_before_a_store_or_a_transport_exists(monkeypatch, capsysbinary):
    """The Node arm returns ahead of `new RawStdioTransport()`; so does this one.

    Every path that could reach a server is replaced with a detonator. If the flag ever
    falls through to the server, one of them fires instead of the assertion below.
    """
    import sys

    import bantamkit.mcpserver as m

    def boom(*_args, **_kwargs):
        raise AssertionError("--assets-root reached the server path")

    monkeypatch.setattr(sys, "argv", ["bantamkit-mcp", "--assets-root"])
    monkeypatch.setattr(m, "_build_memory", boom)
    monkeypatch.setattr(m, "build_server", boom)
    monkeypatch.setattr(m.asyncio, "run", boom)

    m.main()  # returns; does not raise SystemExit

    captured = capsysbinary.readouterr()
    assert captured.err == b""
    assert captured.out.count(b"\n") == 2
    assert captured.out.endswith(b" files\n")


def test_assets_root_appears_in_the_generated_help_in_the_documented_position(tmp_path):
    """The point of the unit: the flag is IN `-h`, and where it sits is pinned.

    argparse orders optionals by registration, so this string is the contract the Node
    formatter has to reproduce. `--assets-root` sits beside `-h` because both print and
    return 0 without starting anything; the flags that configure a running server follow.
    """
    done = _run_cli(["-h"], tmp_path)

    assert done.returncode == 0
    assert done.stderr == b""
    first = done.stdout.decode().splitlines()[0]
    assert first == "usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES]"
    assert "--assets-root" in done.stdout.decode()


def test_assets_root_defaults_off_so_a_bare_invocation_still_serves():
    """The production invocation passes no arguments at all. It must not print and exit."""
    assert _parse_args([]).assets_root is False
    assert _parse_args(["--assets-root"]).assets_root is True


def test_assets_root_writes_lf_even_when_the_text_stream_would_translate(monkeypatch):
    """LF on every platform, not CRLF -- and made visible on a platform that cannot see it.

    `sys.stdout` is a text stream with newline translation, so on Windows `print` emits
    CRLF where Node's `process.stdout.write` emits LF; a byte-comparing conformance runner
    would report a divergence that belongs to the writer, not to the product. That is
    unobservable on POSIX, where the translation is a no-op, so this node stands in a
    stream that DOES translate. Mutating `sys.stdout.buffer.write(...)` back to two
    `print()` calls leaves every other node in this file green and reddens only this one.
    """
    import io
    import sys

    import bantamkit.mcpserver as m

    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="utf-8", newline="\r\n"))
    m._print_assets_root()
    sys.stdout.flush()

    written = raw.getvalue()
    assert b"\r" not in written
    assert written.endswith(b" files\n")
    assert written.count(b"\n") == 2
