"""Pin `tools/mcpdrift/mcpdrift.py` on SYNTHETIC MCP servers and on nothing else.

WHAT GUARDS WHAT, STATED ONCE.

  * this file guards the checker's LOGIC — that two servers which differ are red, that
    two which agree are green, and that a checker which found nothing says so;
  * the checker guards THIS MACHINE'S REGISTRATIONS, run deliberately as a command;
  * and CI runs only the first half. That is not an oversight and it is not papered
    over with a skip. `mcpdrift check` needs a live `~/.claude.json` and a user-scope
    install; CI has neither, so a node that ran it would either be red for a reason
    nobody could fix or would `pytest.skip` — and `RB-P51` is exactly the finding that a
    node which skips is a node which measured nothing while reporting success. Every
    node here runs everywhere, because every node here builds its own servers.

RB-P14 GATE 2 IS WHY THE SERVERS ARE SYNTHETIC. An acceptance criterion may not assert a
fact about the world. No node below reads `~/.claude.json`, names a real install path,
asserts what version any endpoint on this machine advertises, or asserts that the two
registered endpoints agree. `test_no_registration_at_all_is_undetermined_not_agreement`
is the only node that touches the real home directory, and it asserts the checker's
behaviour when it finds NOTHING — under a server name nothing could plausibly register.

THE NODE THIS FILE EXISTS FOR IS
`test_a_behavioural_difference_under_one_version_string_is_red`. The version string has
already lied in this program's history (`RB-P45`: an editable `v0.25.0` checkout
advertised `0.3.0`), so "the two endpoints report the same version" is evidence about one
string. That node builds two servers whose `serverInfo.version` is byte-identical and
whose ANSWERS differ, asserts the verdict is red, AND asserts that `server_version` is
not among the surfaces that made it red. A checker that quietly regressed to comparing
version strings would pass every other node in this file and fail that one.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "tools" / "mcpdrift" / "mcpdrift.py"


def _module():
    assert CHECKER.exists(), "the rule and its checker land together; the checker is missing"
    spec = importlib.util.spec_from_file_location("mcpdrift_under_test", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


mcpdrift = _module()


# --------------------------------------------------------------- the synthetic server

# A whole MCP stdio server in one file, parametrised by a personality dict inlined at
# write time. It answers `initialize`, `tools/list` and `tools/call` and nothing else,
# which is exactly the surface the checker uses. `recall_lines` controls how many facts
# `memory_recall` returns, so the RB-P1 k-floor — the discriminator the checker leans on
# — can be simulated in either direction without installing a second bantamkit.
_SERVER_SOURCE = '''\
import json, os, sys

P = {personality}

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

def recall_text(arguments):
    n = P["recall_lines"] if arguments.get("query") != "MISS" else 0
    if not n:
        return "no memories matched."
    return "\\n\\n".join(
        "[project] [fact-%d] (project) a seeded fact\\nbody %d" % (i, i) for i in range(n)
    )

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        continue
    if method == "initialize":
        send({{"jsonrpc": "2.0", "id": mid, "result": {{
            "capabilities": P["capabilities"],
            "instructions": P["instructions"],
            "serverInfo": {{"name": "bantamkit", "version": P["version"]}},
        }}}})
    elif method == "tools/list":
        send({{"jsonrpc": "2.0", "id": mid, "result": {{"tools": P["tools"]}}}})
    elif method == "tools/call":
        name = msg["params"]["name"]
        arguments = msg["params"].get("arguments") or {{}}
        if name == "memory_recall":
            text = recall_text(arguments)
        elif name == "__env__":
            text = json.dumps({{
                "BANTAMKIT_ASSETS": os.environ.get("BANTAMKIT_ASSETS"),
                "HOME": os.environ.get("HOME"),
                "cwd": os.getcwd(),
            }})
        else:
            text = P["replies"].get(name, "synthetic " + name)
        send({{"jsonrpc": "2.0", "id": mid, "result": {{
            "content": [{{"type": "text", "text": text}}], "isError": False}}}})
    else:
        send({{"jsonrpc": "2.0", "id": mid, "result": {{}}}})
'''


def _personality(**overrides):
    base = {
        "version": "9.9.9",
        "instructions": "# Memory\\n\\nsynthetic instructions",
        "capabilities": {"tools": {"listChanged": False}},
        "tools": [
            {"name": "memory_recall", "description": "recall", "inputSchema": {"type": "object"}},
            {"name": "validate_json", "description": "validate", "inputSchema": {"type": "object"}},
            {
                "name": "shiftwork_status",
                "description": "status",
                "inputSchema": {"type": "object"},
            },
        ],
        "replies": {"validate_json": "invalid: 'b' is required", "shiftwork_status": "cursor U3"},
        "recall_lines": 3,
    }
    base.update(overrides)
    return base


def _server(tmp_path: Path, name: str, **overrides) -> str:
    """Write one executable synthetic server and return its command path."""
    path = tmp_path / f"{name}-server.py"
    source = _SERVER_SOURCE.format(personality=repr(_personality(**overrides)))
    path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def _check(*endpoints: str, extra: list[str] | None = None):
    """Drive the checker in-process and return (exit code, parsed JSON report)."""
    argv = ["check", "--json", *[f"--endpoint={spec}" for spec in endpoints], *(extra or [])]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = mcpdrift.main(argv)
    text = buffer.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else None)


# ------------------------------------------------------------------ guards on the guard


def test_the_checker_and_its_fixture_source_are_both_present():
    """A parametrised-empty guard reports success; so does a checker with no fixture.

    `shiftwork_status` is probed over a committed example checkpoint. If that file moved,
    the probe would degrade into "both endpoints failed identically", which compares
    equal — a surface that silently stops discriminating. The checker refuses to run in
    that state and this node is why that refusal cannot be dropped unnoticed.
    """
    assert CHECKER.is_file()
    assert mcpdrift.EXAMPLE_CHECKPOINT.is_file(), "the checker's fixture source moved"
    assert mcpdrift.probes(), "the behavioural probe set is empty; every call would compare equal"
    assert len(mcpdrift.FIXTURE_FACTS) >= 3, "the k-floor probe needs more facts than the floor"


def test_the_fixture_seeds_more_matching_facts_than_the_recall_floor():
    """Why four facts and not one.

    With a single seeded fact, a build that honours `k=1` and a build that raises it to
    the store default both answer with one fact, and the only discriminator this program
    ever had would read identical on both. The fixture is sized so the two answers cannot
    coincide — a property of the instrument, asserted here, not a hope in a comment.
    """
    matching = [f for f in mcpdrift.FIXTURE_FACTS if mcpdrift.FIXTURE_QUERY in f[0]]
    assert len(matching) >= 4, "too few facts share the probe query for the floor to show"


# ------------------------------------------------------------------------- the verdicts


def test_two_identical_servers_agree(tmp_path):
    code, report = _check(f"a={_server(tmp_path, 'a')}", f"b={_server(tmp_path, 'b')}")
    assert report["verdict"] == "AGREE", report["differing"]
    assert code == 0
    assert report["differing"] == []
    # Vacuity guard: AGREE over zero compared surfaces is not agreement.
    assert len(report["endpoints"][0]["surfaces"]) >= 10


def test_a_behavioural_difference_under_one_version_string_is_red(tmp_path):
    """THE node. Same version, different answers — and the version is not what fired.

    This is the RB-P1 shape reproduced without installing a second bantamkit: one server
    honours `k=1` and answers with one fact, the other applies the store floor and
    answers with three, and both call themselves `9.9.9`.
    """
    code, report = _check(
        f"floored={_server(tmp_path, 'floored', recall_lines=3)}",
        f"literal={_server(tmp_path, 'literal', recall_lines=1)}",
    )
    assert code == 1
    assert report["verdict"] == "DIFFER"
    assert "server_version" not in report["differing"], (
        "the two servers advertise the same version; a checker that reported the version "
        "as differing is comparing something other than what it claims to compare"
    )
    assert "behaviour[recall_k1_fact_count]" in report["differing"]
    counts = {
        endpoint["scope"]: endpoint["surfaces"]["behaviour[recall_k1_fact_count]"]
        for endpoint in report["endpoints"]
    }
    assert counts == {"floored": 3, "literal": 1}


def test_a_version_difference_alone_is_red(tmp_path):
    code, report = _check(
        f"old={_server(tmp_path, 'old', version='0.13.0')}",
        f"new={_server(tmp_path, 'new', version='0.25.0')}",
    )
    assert code == 1
    assert report["differing"] == ["server_version"]


@pytest.mark.parametrize(
    "surface,overrides",
    [
        ("instructions", {"instructions": "# Memory\\n\\nDIFFERENT skill asset"}),
        ("tool_names", {"tools": [{"name": "memory_recall", "inputSchema": {}}]}),
        ("behaviour[validate_json_invalid]", {"replies": {"validate_json": "other wording"}}),
        ("capabilities", {"capabilities": {"tools": {"listChanged": True}}}),
    ],
)
def test_each_non_version_surface_can_fire_on_its_own(tmp_path, surface, overrides):
    """Four surfaces beyond the version string, each shown firing alone.

    A fingerprint field that no test can make red is decoration. One parametrised case
    per surface keeps them honest, and each case changes exactly one thing.
    """
    code, report = _check(
        f"base={_server(tmp_path, 'base')}",
        f"changed={_server(tmp_path, 'changed', **overrides)}",
    )
    assert code == 1
    assert surface in report["differing"], report["differing"]


def test_a_dead_endpoint_is_error_not_agreement(tmp_path):
    """Cannot compare is a different statement from compared and agreed."""
    dead = tmp_path / "dead"
    dead.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(3)\n", encoding="utf-8")
    dead.chmod(dead.stat().st_mode | stat.S_IXUSR)
    code, report = _check(f"live={_server(tmp_path, 'live')}", f"dead={dead}")
    assert code == 2
    assert report["verdict"] == "ERROR"
    assert any(endpoint["error"] for endpoint in report["endpoints"])


def test_a_missing_binary_is_error_not_agreement(tmp_path):
    code, report = _check(
        f"live={_server(tmp_path, 'live')}", f"gone={tmp_path / 'not-installed'}"
    )
    assert code == 2
    assert report["verdict"] == "ERROR"


def test_one_endpoint_is_single_and_names_itself(tmp_path):
    """One name, one endpoint: nothing can drift, and the verdict says which case it is."""
    code, report = _check(f"only={_server(tmp_path, 'only')}")
    assert code == 0
    assert report["verdict"] == "SINGLE"


def test_no_registration_at_all_is_undetermined_not_agreement(tmp_path, capsys):
    """RB-P51 in one node: a checker that discovered nothing must not exit 0.

    The server name is one nothing on any machine registers, so this asserts the
    checker's behaviour on an empty discovery rather than a fact about this machine.
    """
    code = mcpdrift.main(
        ["check", "--server", "mcpdrift-synthetic-absent-server", "--repo", str(tmp_path)]
    )
    assert code == 3
    assert "UNDETERMINED" in capsys.readouterr().out


# -------------------------------------------------------------------------- discovery


def test_discovery_reads_all_three_scopes_from_a_synthetic_config(tmp_path):
    """Both scopes found, and a relative project command resolved against the project.

    The relative form is the one the repo actually commits (`.venv/bin/bantamkit-mcp`),
    and it is the reason the same `.mcp.json` means a different binary in a worktree.
    """
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / ".venv" / "bin" / "bantamkit-mcp").write_text("#!/bin/sh\n", encoding="utf-8")
    home.mkdir()
    (home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {"bantamkit": {"command": "/pinned/bin/bantamkit-mcp", "args": []}},
                "projects": {
                    str(repo): {"mcpServers": {"bantamkit": {"command": "/local/bin/bk"}}}
                },
            }
        ), encoding="utf-8"
    )
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"bantamkit": {"command": ".venv/bin/bantamkit-mcp"}}}),
        encoding="utf-8",
    )
    found = mcpdrift.discover("bantamkit", repo, home)
    assert [endpoint.scope for endpoint in found] == ["user", "local", "project"]
    assert found[0].argv == ["/pinned/bin/bantamkit-mcp"]
    assert found[2].argv == [str(repo / ".venv" / "bin" / "bantamkit-mcp")]


def test_discovery_of_an_unregistered_name_is_empty(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "/x"}}}), encoding="utf-8"
    )
    assert mcpdrift.discover("bantamkit", tmp_path, home) == []


# ------------------------------------------------------------- the controlled environment


def test_the_child_never_inherits_the_asset_override_and_never_sees_the_real_home(
    tmp_path, monkeypatch
):
    """The two environment facts the whole comparison rests on, asserted from the child.

    If `BANTAMKIT_ASSETS` leaked in, both builds would read ONE asset pack and asset
    drift — the thing the `instructions` and `tools` surfaces exist to catch — would be
    invisible. If `HOME` leaked in, the profile memory layer would be the operator's own
    store and the recall probes would measure that store instead of the build. The
    synthetic server reports its own environment, so this is read out of the process the
    checker actually launched.
    """
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path / "some-other-pack"))
    real_home = os.path.expanduser("~")
    project, home = mcpdrift._write_fixture(tmp_path / "fixture")
    session = mcpdrift._Session([_server(tmp_path, "env")], project, home, 30.0)
    try:
        session.request(
            "initialize",
            {
                "protocolVersion": mcpdrift.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            },
        )
        session.notify("notifications/initialized")
        seen = json.loads(mcpdrift._call_text(session, "__env__", {}).removeprefix("OK "))
    finally:
        session.close()
    assert seen["BANTAMKIT_ASSETS"] is None
    assert seen["HOME"] != real_home
    assert Path(seen["HOME"]).is_dir() and not (Path(seen["HOME"]) / ".bantamkit").exists()
    assert (Path(seen["cwd"]) / ".bantamkit" / "memory" / "facts").is_dir()
    assert len(list((Path(seen["cwd"]) / ".bantamkit" / "memory" / "facts").iterdir())) == len(
        mcpdrift.FIXTURE_FACTS
    )
