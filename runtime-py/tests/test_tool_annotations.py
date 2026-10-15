"""#182 and #198 (job67): what `tools/list` says about each tool, and `prompts/get` refusing.

#182: every served tool carries a human `title` and MCP 2025-06-18 `annotations`. The hint
that matters to a host is `readOnlyHint`, and it is `true` ONLY for a tool that writes
nothing on any path. The opt-in event log (`BANTAMKIT_EVENT_LOG`) does not count: the user
ruled (#182 Q1, option (b), 2026-10-15) that it is a diagnostic, not a side effect a hint
describes, so the hints come straight from the asset with the log on or off. J67-2 had an
overlay (`served_annotations` / `EVENT_LOG_HINTS`) that turned the eight read-only tools into
append-only writers while the log was on; J67-9 removed it in both runtimes, and the two
tests that pinned it moved to the ruling (their names say so).

#198 (user ruling 2026-10-15): an unknown prompt name is `-32602` with the sentence
`Unknown prompt: <name>` and `data: null`, the port's frame byte for byte. The SDK answered
`code: 0`.

The port's half is `runtime-ts/test/tool-annotations.test.mjs`; the two wires are compared
by `tools/conformance/suites/wire.mjs` (`j67-2:` cases).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bantamkit.assets import assets_root

pytest.importorskip("mcp")

from bantamkit import mcpserver  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src"
HINT_KEYS = {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}

#: The tools that write NOTHING while the event log is off, read off each handler in both
#: runtimes (`.shiftwork/notes-job67/J67-2.md` has the per-tool reading). Spelled here, not
#: derived from the assets, so an asset that flips a hint is a red and not a new truth.
READ_ONLY = {
    "validate_json",
    "shiftwork_status",
    "build_identity",
    "bantamkit_status",
    "skill_audit",
    "token_ledger",
    "work_plan",
    "shiftwork_plan",
}


def _served_assets() -> dict[str, dict]:
    out = {}
    for path in sorted((assets_root() / "tools").glob("*.json")):
        asset = json.loads(path.read_text(encoding="utf-8"))
        if "mcp" in asset["surfaces"]:
            out[asset["name"]] = asset
    return out


def test_every_served_asset_carries_a_title_and_only_mcp_hint_keys():
    assets = _served_assets()
    assert len(assets) == 14
    for name, asset in assets.items():
        assert isinstance(asset["title"], str) and asset["title"].strip(), name
        hints = asset["annotations"]
        assert set(hints) <= HINT_KEYS, name
        assert all(isinstance(v, bool) for v in hints.values()), name
        # Every one is stated, none left to a client's default: no tool reaches the network.
        assert hints["openWorldHint"] is False, name
        assert "readOnlyHint" in hints, name
        if hints["readOnlyHint"]:
            # The other two are meaningless on a read-only tool (MCP 2025-06-18), so a
            # read-only asset carrying them would be claiming something nobody reads.
            assert set(hints) == {"readOnlyHint", "openWorldHint"}, name
    assert {n for n, a in assets.items() if a["annotations"]["readOnlyHint"]} == READ_ONLY


def test_182_q1_ruling_b_no_hint_depends_on_the_event_log():
    # Was `test_served_annotations_flip_only_the_read_only_tools_while_the_log_is_on`, which
    # pinned J67-2's overlay on purpose; moved to the user's ruling (b) by J67-9.
    assert not hasattr(mcpserver, "EVENT_LOG_HINTS")
    assert not hasattr(mcpserver, "served_annotations")
    for name, asset in _served_assets().items():
        tool = mcpserver._from_manifest(lambda: None, name)
        served = tool.annotations.model_dump(by_alias=True, exclude_none=True)
        assert served == asset["annotations"], name


def _exchange(tmp_path: Path, requests: list[dict], event_log: bool) -> list[dict]:
    """Lock-step raw stdio against `python -m bantamkit.mcpserver`: one answer per request."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["HOME"] = env["USERPROFILE"] = str(home)
    env.pop("BANTAMKIT_EVENT_LOG", None)
    if event_log:
        env["BANTAMKIT_EVENT_LOG"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "bantamkit.mcpserver", "--store", str(tmp_path / "store")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=str(tmp_path),
        env=env,
        encoding="utf-8",
    )
    assert proc.stdin is not None and proc.stdout is not None

    def send(message: dict) -> None:
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    answers = []
    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "j67-2", "version": "0"},
                },
            }
        )
        json.loads(proc.stdout.readline())
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        for request in requests:
            send(request)
            answers.append(proc.stdout.readline())
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
    return answers


@pytest.mark.parametrize("event_log", [False, True])
def test_the_wire_advertises_the_asset_title_and_hints_whatever_the_log_state(tmp_path, event_log):
    # #182 Q1 ruling (b): the log moves no hint (J67-9; until then the log-on run expected the
    # overlay on the eight read-only tools).
    [line] = _exchange(tmp_path, [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], event_log)
    tools = json.loads(line)["result"]["tools"]
    assets = _served_assets()
    assert len(tools) == 14
    for tool in tools:
        asset = assets[tool["name"]]
        assert tool["title"] == asset["title"]
        assert tool["annotations"] == asset["annotations"], tool["name"]


def test_198_an_unknown_prompt_name_is_invalid_params_with_data_null(tmp_path):
    [unknown, known] = _exchange(
        tmp_path,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "prompts/get", "params": {"name": "nosuch"}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "prompts/get",
                "params": {"name": "bantamkit_status"},
            },
        ],
        False,
    )
    assert json.loads(unknown) == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32602, "message": "Unknown prompt: nosuch", "data": None},
    }
    # The registered prompt is still served through the wrapped `get_prompt`.
    assert json.loads(known)["result"]["messages"][0]["role"] == "user"
