"""#259 — unit results: a brief carries what its dependencies produced and its own attempts.

Literals for the cap, the order and the refusal, because a differential stays green when both
runtimes drop the same key.
Spec: `docs/superpowers/specs/2026-11-03-shiftwork-unit-results-design.md`.
"""

import json

from bantamkit import shiftwork as ops


def _checkpoint(units):
    return {
        "version": 1,
        "job": {"id": "t259", "goal": "g", "done_definition": "d", "constraints": ["c"]},
        "plan": {
            "cursor": units[0]["id"],
            "units": [
                {
                    "title": f"unit {u['id']}",
                    "brief_path": f"b/{u['id']}.md",
                    "status": "todo",
                    "role": "implementer",
                    "depends_on": [],
                    "verify": "true",
                    **u,
                }
                for u in units
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


def _write(tmp_path, units):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(_checkpoint(units)), encoding="utf-8")
    return path


def _out(path, unit, status, **entry):
    return ops.clock_out(str(path), unit, status, {}, {"unit": unit, **entry})


def _units(path):
    return {u["id"]: u for u in json.loads(path.read_text(encoding="utf-8"))["plan"]["units"]}


def test_a_brief_without_attempts_carries_both_keys_empty(tmp_path):
    path = _write(tmp_path, [{"id": "A"}, {"id": "B", "depends_on": ["A"]}])
    brief = ops.clock_in(str(path))
    assert brief["upstream"] == []
    assert brief["prior_attempts"] == []


def test_clock_out_appends_an_attempt_from_status_and_history_entry(tmp_path):
    path = _write(tmp_path, [{"id": "A"}, {"id": "B", "depends_on": ["A"]}])
    produced = [{"kind": "commit", "ref": "abc123"}]
    assert _out(path, "A", "done", outcome="done", notes="n", produced=produced)["result"] == "ok"
    assert _units(path)["A"]["attempts"] == [
        {"status": "done", "outcome": "done", "notes": "n", "produced": produced}
    ]


def test_upstream_follows_depends_on_order_and_names_the_newest_attempt(tmp_path):
    units = [
        {"id": "A"},
        {"id": "Z", "title": "zed"},
        {"id": "C", "depends_on": ["Z", "A"]},
    ]
    path = _write(tmp_path, units)
    assert _out(path, "A", "done", outcome="a done")["result"] == "ok"
    ops.clock_in(str(path), "Z")
    assert _out(path, "Z", "done", outcome="z done")["result"] == "ok"
    brief = ops.clock_in(str(path), "C")
    z_last = {"status": "done", "outcome": "z done"}
    a_last = {"status": "done", "outcome": "a done"}
    assert brief["upstream"] == [
        {"unit": "Z", "title": "zed", "status": "done", "last": z_last},
        {"unit": "A", "title": "unit A", "status": "done", "last": a_last},
    ]


def test_a_dependency_with_no_attempt_reads_last_null(tmp_path):
    path = _write(tmp_path, [{"id": "A", "status": "done"}, {"id": "B", "depends_on": ["A"]}])
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["plan"]["cursor"] = "B"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert ops.clock_in(str(path))["upstream"] == [
        {"unit": "A", "title": "unit A", "status": "done", "last": None}
    ]


def test_attempts_are_capped_at_three_oldest_dropped_and_a_rework_sees_them(tmp_path):
    path = _write(tmp_path, [{"id": "A"}, {"id": "B", "depends_on": ["A"]}])
    for n in range(1, 5):
        assert _out(path, "A", "todo", outcome=f"try {n}")["result"] == "ok"
    assert ops.ATTEMPTS_KEPT == 3
    assert [a["outcome"] for a in _units(path)["A"]["attempts"]] == ["try 2", "try 3", "try 4"]
    assert [a["outcome"] for a in ops.clock_in(str(path))["prior_attempts"]] == [
        "try 2",
        "try 3",
        "try 4",
    ]


def test_notes_over_the_cap_are_refused_and_nothing_is_written(tmp_path):
    path = _write(tmp_path, [{"id": "A"}, {"id": "B"}])
    before = path.read_bytes()
    # 2001 code points, each three bytes in UTF-8: the count is code points, not bytes
    out = _out(path, "A", "done", outcome="done", notes="ก" * 2001)
    assert out == {
        "result": "error",
        "reason": "history_entry notes are 2001 code points; an attempt keeps at most 2000",
    }
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".log.jsonl").exists()
    assert _out(path, "A", "done", outcome="done", notes="ก" * 2000)["result"] == "ok"


def test_a_malformed_produced_is_refused_by_the_schema(tmp_path):
    path = _write(tmp_path, [{"id": "A"}, {"id": "B"}])
    out = _out(path, "A", "done", outcome="done", produced=[{"kind": "commit"}])
    assert out["result"] == "error"
    assert out["reason"].startswith("refused to write:")
