"""#266 — a unit's subagent: clock_out records `agent_id`, the hook stamps use rows with it,
and the X10 signals attribute those uses to the unit.

Literals for the refusal, the ledger key and the use row; the disk byte-unchanged on a
refusal. Spec: the #266 comment "Spec — #266, option (a)". `runtime-ts/test/unit-agent-id.test.mjs`
mirrors this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bantamkit import shiftwork as ops
from bantamkit import skillfile as sf
from bantamkit import skillinstall as si
from bantamkit import skillmine as sm
from bantamkit.touch.log import TouchLog, agent_of

AGENT = "a9443875b21b8ca8f"  # the shape the probe of 2026-11-03 saw on a real run
NOW = "2026-10-27T12:00:00.000Z"
LATER = "2026-10-28T12:00:00.000Z"
AFTER = "2026-10-27T13:00:00.000Z"


def _write(tmp_path: Path) -> Path:
    doc = {
        "version": 1,
        "job": {"id": "t266", "goal": "g", "done_definition": "d", "constraints": ["c"]},
        "plan": {
            "cursor": "A",
            "units": [
                {
                    "id": u,
                    "title": u,
                    "brief_path": f"b/{u}.md",
                    "status": "todo",
                    "role": "implementer",
                    "depends_on": [],
                    "verify": "true",
                }
                for u in ("A", "B")
            ],
        },
        "state": {
            "repo": {"branch": "b", "head_sha": "0", "dirty": False},
            "artifacts": [],
            "external": [],
        },
        "history": [],
        "retro": [],
        "handoff": {"next_action": "go", "open_questions": [], "do_not": [], "notes": ""},
    }
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _out(path: Path, agent_id, accounting=None):
    entry = {"unit": "A", "outcome": "done"}
    return ops.clock_out(str(path), "A", "done", {}, entry, accounting, None, None, None, agent_id)


def _ledger(path: Path) -> list[dict]:
    log = Path(f"{path}.log.jsonl")
    if not log.exists():
        return []
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x]


# ------------------------------------------------------------------ D1/D2: clock_out


def test_the_agent_id_goes_on_the_accounting_line_and_nowhere_else(tmp_path):
    path = _write(tmp_path)
    assert _out(path, AGENT, {"tokens": 5, "duration_ms": 9})["result"] == "ok"
    (line,) = _ledger(path)
    assert line["agent_id"] == AGENT and line["tokens"] == 5
    assert AGENT not in path.read_text(encoding="utf-8")  # never in the checkpoint


def test_an_accounting_null_line_carries_it_too(tmp_path):
    path = _write(tmp_path)
    assert _out(path, AGENT)["result"] == "ok"
    assert _ledger(path)[0]["agent_id"] == AGENT


def test_without_one_the_line_is_todays(tmp_path):
    path = _write(tmp_path)
    assert _out(path, None)["result"] == "ok"
    assert "agent_id" not in _ledger(path)[0]


@pytest.mark.parametrize("bad", ["", "a" * 65, "a b", "a/b", "ä", "a\n", 7, ["a"]])
def test_a_bad_agent_id_is_refused_and_nothing_is_written(tmp_path, bad):
    path = _write(tmp_path)
    before = path.read_bytes()
    r = _out(path, bad)
    assert r == {"result": "error", "reason": ops.AGENT_ID_REFUSAL}
    assert ops.AGENT_ID_REFUSAL == (
        "agent_id must be 1 to 64 characters, each a letter, a digit, - or _"
    )
    assert path.read_bytes() == before and _ledger(path) == []


def test_sixty_four_characters_pass(tmp_path):
    path = _write(tmp_path)
    assert _out(path, "A-_9" * 16)["result"] == "ok"


def test_a_self_reported_agent_id_is_a_reserved_key(tmp_path):
    path = _write(tmp_path)
    before = path.read_bytes()
    r = _out(path, None, {"tokens": 1, "duration_ms": 1, "agent_id": AGENT})
    assert r["reason"] == (
        "unit A in role implementer reported an accounting line "
        "that sets the runtime's own keys: agent_id"
    )
    assert path.read_bytes() == before and _ledger(path) == []


# -------------------------------------------------------------------- D3: the use row


def test_agent_of_takes_only_a_well_formed_id():
    assert agent_of({"agent_id": AGENT}) == AGENT
    for bad in ({}, {"agent_id": ""}, {"agent_id": "a b"}, {"agent_id": 1}, {"agent_id": None}):
        assert agent_of(bad) is None


def test_a_use_row_inside_a_subagent_ends_with_its_agent_id(tmp_path):
    log = TouchLog(tmp_path, "r1")
    assert log.append_use("s1", 3, "sk-one", "recall_hit", "2026-01-01T00:00:00Z", AGENT)
    assert log.append_use("s1", 4, "sk-one", "recall_hit", "2026-01-01T00:00:01Z")
    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        '{"ts":"2026-01-01T00:00:00Z","session":"s1","seq":3,"op":"use","fact":"sk-one",'
        f'"kind":"recall_hit","agent_id":"{AGENT}"}}',
        '{"ts":"2026-01-01T00:00:01Z","session":"s1","seq":4,"op":"use","fact":"sk-one",'
        '"kind":"recall_hit"}',
    ]


# ------------------------------------------------------------------- D4: the miner


def _job(root: Path, lines: list[dict], status: str = "done") -> None:
    sw = root / ".shiftwork"
    sw.mkdir(parents=True)
    units = [
        {"id": u, "title": f"fix {u}", "brief_path": f"b/{u}.md", "status": status}
        for u in sorted({ln["unit"] for ln in lines})
    ]
    doc = {"job": {"id": "j"}, "plan": {"units": units}, "history": []}
    (sw / "checkpoint-job9.json").write_text(json.dumps(doc), encoding="utf-8")
    (sw / "checkpoint-job9.json.log.jsonl").write_text(
        "".join(json.dumps(ln) + "\n" for ln in lines), encoding="utf-8"
    )


def test_a_piece_keeps_the_counting_clock_outs_agent_id_out_of_its_dict(tmp_path):
    _job(
        tmp_path,
        [
            {"unit": "U1", "status": "done", "ts": "2026-01-01T00:00:00Z", "agent_id": "old"},
            {"unit": "U1", "status": "done", "ts": "2026-01-02T00:00:00Z", "agent_id": AGENT},
            {"unit": "U2", "status": "done", "ts": "2026-01-02T00:00:00Z", "agent_id": "a b"},
            {"unit": "U3", "status": "done", "ts": "2026-01-02T00:00:00Z"},
        ],
    )
    got = {p.id: p for p in sm.shiftwork_pieces(tmp_path)}
    assert {k: p.agent_id for k, p in got.items()} == {
        "job9/U1": AGENT,
        "job9/U2": None,
        "job9/U3": None,
    }
    assert "agent_id" not in got["job9/U1"].as_dict()


def test_improve_sources_lists_the_units_and_stamps_the_uses(tmp_path):
    home = tmp_path / "home"
    touch = home / ".bantamkit" / "touch"
    touch.mkdir(parents=True)
    rows = [
        {"ts": AFTER, "session": "s1", "seq": 1, "op": "use", "fact": "sk-one",
         "kind": "recall_hit", "agent_id": AGENT},
        {"ts": AFTER, "session": "s1", "seq": 2, "op": "use", "fact": "sk-one",
         "kind": "recall_hit", "agent_id": "a b"},
    ]  # fmt: skip
    (touch / "r1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    pieces = [
        sm.Piece(id="job9/U1", source=sm.SOURCE_SHIFTWORK, ts=AFTER, repo="", prompt="p",
                 ok=False, failure="blocked on the lexer", agent_id=AGENT),
        sm.Piece(id="job9/U2", source=sm.SOURCE_SHIFTWORK, ts=AFTER, repo="", prompt="p", ok=True),
    ]  # fmt: skip
    out = sm.improve_sources(home, pieces, {"skills": {"sk-one": {}}})
    assert out["units"] == [
        {"agent_id": AGENT, "failure": "blocked on the lexer", "id": "job9/U1", "ok": False,
         "ts": AFTER}
    ]  # fmt: skip
    assert out["uses"] == [
        {"agent_id": AGENT, "fact": "sk-one", "session": "s1", "ts": AFTER},
        {"fact": "sk-one", "session": "s1", "ts": AFTER},
    ]


# ------------------------------------------------------------ D5: the X10 attribution


DESC = "Does sk-one. Use when sk-one is asked."


def _draft() -> str:
    return (
        f"---\nname: sk-one\ndescription: {DESC}\n---\n\n"
        "## When to use\n\nWhen asked.\n\n## Steps\n\n1. Do it [job1/U1].\n\n"
        "## Pitfalls\n\nNone.\n\n## Example\n\nx\n"
    )


def _record(evidence=None) -> dict:
    return {
        "evidence": evidence or [{"id": "job1/U1", "ok": True, "ts": "2026-01-01T00:00:00Z"}],
        "id": "c-sk-one",
        "keywords": ["k1"],
        "level": "user",
        "members": 3,
        "source": "shiftwork",
        "status": "pending",
        "steps": [],
        "successes": 3,
        "top": None,
    }


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv(si.AUTO_ENV, "on")
    si.install(_record(), _draft(), None, tmp_path, NOW, False)
    return tmp_path


def _unit(uid: str, ok, agent: str = AGENT, failure=None) -> dict:
    return {"agent_id": agent, "failure": failure, "id": uid, "ok": ok, "ts": AFTER}


def _use(agent=AGENT, session="1111aaaa-x") -> dict:
    u = {"fact": "sk-one", "session": session, "ts": "2026-10-27T13:00:01.000Z"}
    if agent is not None:
        u["agent_id"] = agent
    return u


# the session's own turn failed: only the unit can make the use a success
_FAILED_TURN = {"id": "s1111aaaa#1", "ok": False, "ts": AFTER}


def test_a_use_inside_a_done_unit_is_a_success_whatever_the_session_turn(home):
    state = sf.read_state(home)
    sources = {"turns": [_FAILED_TURN], "units": [_unit("job9/U1", True)], "uses": [_use()]}
    si.stats_step(state, sources, home, LATER)
    v = state["skills"]["sk-one"]["versions"]["1"]
    assert (v["uses"], v["successes"]) == (1, 1)


def test_an_agent_id_two_units_claim_keeps_the_session_rule(home):
    state = sf.read_state(home)
    units = [_unit("job9/U1", True), _unit("job9/U2", True)]
    si.stats_step(state, {"turns": [_FAILED_TURN], "units": units, "uses": [_use()]}, home, LATER)
    v = state["skills"]["sk-one"]["versions"]["1"]
    assert (v["uses"], v["successes"]) == (1, 0)


def test_a_use_without_an_agent_id_keeps_the_session_rule(home):
    state = sf.read_state(home)
    sources = {"turns": [_FAILED_TURN], "units": [_unit("job9/U1", True)], "uses": [_use(None)]}
    si.stats_step(state, sources, home, LATER)
    assert state["skills"]["sk-one"]["versions"]["1"]["successes"] == 0


def _improve(home: Path, sources: dict, doc=None):
    state = sf.read_state(home)
    return si.improve_step(state, sources, doc, home, None, LATER, []), state


def _skill(home: Path) -> str:
    return (sf.skills_root(home) / "sk-one" / "SKILL.md").read_text(encoding="utf-8")


def test_a_use_inside_a_blocked_unit_is_a_pitfall_citing_the_unit(home):
    units = [_unit("job9/U1", False, failure="blocked on the lexer\nmore")]
    events, state = _improve(home, {"units": units, "uses": [_use()]})
    assert events == ["improved skill sk-one to v2", "proposed a change to sk-one"]
    doc = sf.parse_skill(_skill(home))
    assert "## Pitfalls\n\n- [job9/U1] blocked on the lexer\n\n## Example" in doc.body
    assert doc.metadata["bantamkit-evidence"] == "job1/U1,job9/U1"


def test_a_unit_that_named_its_subagent_and_never_used_the_skill_is_a_miss(home):
    ev = [{"id": "job9/U1", "ok": True, "prompt": "fix the lexer", "ts": AFTER},
          {"id": "job9/U2", "ok": True, "prompt": "fix the lexer", "ts": AFTER},
          {"id": "job9/U3", "ok": True, "prompt": "fix the lexer", "ts": AFTER}]  # fmt: skip
    units = [_unit("job9/U1", True, "a1"), _unit("job9/U2", True, "a2")]
    # U1 used it, U2 did not (a miss), U3 named no subagent (skipped, as before #266)
    _, state = _improve(home, {"units": units, "uses": [_use("a1")]}, {"clusters": [_record(ev)]})
    assert state["skills"]["sk-one"]["versions"]["1"]["misses"] == 1


# --------------------------------------------------------------- D3 through the hook


def _hook_use_rows(tmp_path: Path, extra: dict) -> list[dict]:
    import os
    import subprocess
    import sys

    home, cwd = tmp_path / "home", tmp_path / "repo"
    home.mkdir()
    cwd.mkdir()
    subprocess.run(["git", "init", "-q", str(cwd)], check=True)
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env.pop("BANTAMKIT_MEMORY_DIR", None)
    payload = {
        "cwd": str(cwd),
        "session_id": "parent-session",
        "hook_event_name": "PostToolUse",
        "tool_name": "mcp__bantamkit__memory_recall",
        "tool_input": {"query": "x"},
        "tool_response": [{"type": "text", "text": "[sk-one] (feedback) d\nbody"}],
        **extra,
    }
    subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", "--hook"],
        input=json.dumps(payload).encode("utf-8"),
        cwd=str(cwd),
        env=env,
        capture_output=True,
        timeout=120,
        check=True,
    )
    rows = []
    for p in sorted((home / ".bantamkit" / "touch").glob("*.jsonl")):
        rows += [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x]
    return [r for r in rows if r.get("op") == "use"]


def test_the_hook_stamps_a_use_row_fired_inside_a_subagent(tmp_path):
    (row,) = _hook_use_rows(tmp_path, {"agent_id": AGENT, "agent_type": "general-purpose"})
    assert (row["session"], row["fact"], row["agent_id"]) == ("parent-session", "sk-one", AGENT)
    assert list(row)[-1] == "agent_id"


@pytest.mark.parametrize("extra", [{}, {"agent_id": "a b"}, {"agent_id": 3}])
def test_the_hook_writes_todays_row_otherwise(tmp_path, extra):
    (row,) = _hook_use_rows(tmp_path, extra)
    assert "agent_id" not in row and row["fact"] == "sk-one"
