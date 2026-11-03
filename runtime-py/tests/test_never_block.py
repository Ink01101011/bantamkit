"""#225 — never block on the human: relay questions, irreversible units, prove.

Literals for every sentence; the disk byte-unchanged on a refusal. Each case sets the new
field, so a check both runtimes dropped together is still red here.
"""

import json

from bantamkit import shiftwork as ops


def _write(tmp_path, questions=(), job_extra=None, unit_extra=None):
    (tmp_path / ".git").mkdir(exist_ok=True)
    job = {"id": "t225", "goal": "g", "done_definition": "d", "constraints": ["c"]}
    job.update(job_extra or {})
    unit = {
        "id": "A",
        "title": "A",
        "brief_path": "b/A.md",
        "status": "todo",
        "role": "implementer",
        "depends_on": [],
        "verify": "true",
    }
    unit.update(unit_extra or {})
    doc = {
        "version": 1,
        "job": job,
        "plan": {"cursor": "A", "units": [unit, {**unit, "id": "B", "title": "B"}]},
        "state": {
            "repo": {"branch": "b", "head_sha": "0", "dirty": False},
            "artifacts": [],
            "external": [],
        },
        "history": [],
        "retro": [],
        "handoff": {
            "next_action": "go",
            "open_questions": list(questions),
            "do_not": [],
            "notes": "",
        },
    }
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _ledger(path):
    log = path.with_name(path.name + ".log.jsonl")
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_a_bare_string_is_a_decision_and_escalates_as_before(tmp_path):
    path = _write(tmp_path, ["ship it?"])
    assert ops.clock_in(str(path)) == {
        "result": "escalate",
        "reason": "open question: ship it?",
        "open_questions": ["ship it?"],
    }


def test_a_relay_its_probe_answers_does_not_escalate_and_is_logged(tmp_path):
    relay = {"q": "is the marker there?", "kind": "relay", "probe": "test -f marker"}
    (tmp_path / "marker").write_text("x", encoding="utf-8")
    path = _write(tmp_path, [relay])
    assert ops.clock_in(str(path))["result"] == "brief"
    resolved = [r for r in _ledger(path) if r.get("event") == "resolved"]
    assert [(r["q"], r["probe"]) for r in resolved] == [("is the marker there?", "test -f marker")]


def test_a_relay_whose_probe_fails_escalates_with_its_text(tmp_path):
    relay = {"q": "is the marker there?", "kind": "relay", "probe": "test -f marker"}
    path = _write(tmp_path, [relay])
    answer = ops.clock_in(str(path))
    assert answer["result"] == "escalate"
    assert answer["reason"] == "open question: is the marker there?"
    assert answer["open_questions"] == [relay]
    assert _ledger(path) == []


def test_a_passing_relay_does_not_hide_a_decision_behind_it(tmp_path):
    relay = {"q": "r?", "kind": "relay", "probe": "true"}
    decision = {"q": "d?", "kind": "decision"}
    answer = ops.clock_in(str(_write(tmp_path, [relay, decision])))
    assert answer["reason"] == "open question: d?"


def test_the_probe_runs_from_the_repo_root(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "marker").write_text("x", encoding="utf-8")
    sub = tmp_path / ".shiftwork"
    sub.mkdir()
    path = _write(sub, [{"q": "q", "kind": "relay", "probe": "test -f marker"}])
    (sub / ".git").rmdir()
    assert ops.clock_in(str(path))["result"] == "brief"


def test_clock_out_refuses_a_relay_with_no_probe_and_writes_nothing(tmp_path):
    path = _write(tmp_path)
    before = path.read_bytes()
    patch = {"open_questions": [{"q": "does CI pass?", "kind": "relay"}]}
    out = ops.clock_out(str(path), "A", "done", patch, {"unit": "A", "outcome": "done"})
    assert out == {"result": "error", "reason": "relay question has no probe: does CI pass?"}
    assert path.read_bytes() == before
    assert _ledger(path) == []


def test_clock_out_accepts_a_relay_with_a_probe(tmp_path):
    path = _write(tmp_path)
    patch = {"open_questions": [{"q": "q", "kind": "relay", "probe": "true"}]}
    out = ops.clock_out(str(path), "A", "done", patch, {"unit": "A", "outcome": "done"})
    assert out["result"] == "ok"


def test_an_irreversible_unit_without_prove_is_refused(tmp_path):
    path = _write(tmp_path, unit_extra={"irreversible": "publish"})
    assert ops.clock_in(str(path)) == {
        "result": "error",
        "reason": "unit A is irreversible (publish) and names no prove command",
    }
    assert _ledger(path) == []


def test_an_unauthorized_verb_escalates(tmp_path):
    extra = {"irreversible": "publish", "prove": "true"}
    path = _write(tmp_path, job_extra={"authorized": ["merge", "tag"]}, unit_extra=extra)
    assert ops.clock_in(str(path)) == {
        "result": "escalate",
        "reason": "unit A is irreversible (publish); job.authorized does not grant publish",
    }
    assert _ledger(path) == []


def test_an_empty_authorized_list_grants_nothing(tmp_path):
    extra = {"irreversible": "merge", "prove": "true"}
    path = _write(tmp_path, job_extra={"authorized": []}, unit_extra=extra)
    assert ops.clock_in(str(path))["result"] == "escalate"


def test_a_granted_verb_briefs_and_so_does_no_declaration(tmp_path):
    extra = {"irreversible": "merge", "prove": "true"}
    granted = _write(tmp_path, job_extra={"authorized": ["merge"]}, unit_extra=extra)
    assert ops.clock_in(str(granted))["result"] == "brief"
    (tmp_path / "x").mkdir()
    undeclared = _write(tmp_path / "x", unit_extra=extra)
    assert ops.clock_in(str(undeclared))["result"] == "brief"
