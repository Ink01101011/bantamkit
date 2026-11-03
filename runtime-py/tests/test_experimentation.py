"""#265 — experimentation flavor: candidates in worktrees, validated at the exact SHA, ranked.

Literals for every sentence; the disk byte-unchanged on a refusal. Each case sets the new
field, so a check both runtimes dropped together is still red here.
"""

import json

from bantamkit import experiment
from bantamkit import shiftwork as ops

SHA_A = "a" * 40
SHA_B = "b" * 40
EXPERIMENT = {
    "objective": "p95 latency, ms",
    "direction": "minimize",
    "base_sha": "c" * 40,
    "harness": "make bench",
    "concurrency_cap": 2,
}


def _unit(uid, role="implementer", depends_on=(), status="todo", **extra):
    return {
        "id": uid,
        "title": uid,
        "brief_path": f"b/{uid}.md",
        "status": status,
        "role": role,
        "depends_on": list(depends_on),
        "verify": "true",
        **extra,
    }


def _candidate(uid, **extra):
    worktree = {"workspace": f".worktrees/{uid}", "author_role": "implementer"}
    return _unit(uid, candidate=worktree, touches=["src/hot.py"], **extra)


def _plan():
    """Candidates A and B, validators VA and VB in another role."""
    return [
        _candidate("A"),
        _candidate("B"),
        _unit("VA", role="reviewer", depends_on=["A"], reviews=["A"]),
        _unit("VB", role="reviewer", depends_on=["B"], reviews=["B"]),
    ]


def _write(tmp_path, units=None, experiment_extra=None, job_extra=None, cursor=None):
    job = {"id": "t265", "goal": "g", "done_definition": "d", "constraints": ["c"]}
    declared = {**EXPERIMENT, **(experiment_extra or {})}
    job.update({"kind": "experimentation", "experiment": declared})
    job.update(job_extra or {})
    units = _plan() if units is None else units
    doc = {
        "version": 1,
        "job": job,
        "plan": {"cursor": cursor or units[0]["id"], "units": units},
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


def _out(path, uid, produced=None, status="done", accounting=None):
    entry = {"unit": uid, "outcome": status}
    if produced is not None:
        entry["produced"] = produced
    return ops.clock_out(str(path), uid, status, {}, entry, accounting)


def _submit(sha, score):
    return [{"kind": "commit", "ref": sha}, {"kind": "score", "ref": score}]


def _refused(path, answer, sentence):
    before = path.read_bytes()
    log = path.with_name(path.name + ".log.jsonl")
    lines = log.read_bytes() if log.exists() else None
    assert answer() == {"result": "error", "reason": sentence}
    assert path.read_bytes() == before
    assert (log.read_bytes() if log.exists() else None) == lines


def test_rank_orders_by_direction_then_id():
    entries = [
        {"id": "B", "score": "2", "sha": SHA_B},
        {"id": "A", "score": "2.0", "sha": SHA_A},
        {"id": "C", "score": "-1e1", "sha": SHA_A},
    ]
    assert [e["id"] for e in experiment.rank(entries, "minimize")] == ["C", "A", "B"]
    assert [e["id"] for e in experiment.rank(entries, "maximize")] == ["A", "B", "C"]


def test_score_and_sha_grammar():
    assert [experiment.score_value(s) for s in ["1", "-0.5", "1e3", "01", "1.", "nan", " 1"]] == [
        1.0, -0.5, 1000.0, None, None, None, None
    ]
    assert experiment.full_sha(SHA_A) and experiment.full_sha("f" * 64)
    assert not experiment.full_sha("A" * 40) and not experiment.full_sha("a" * 39)


def test_an_experimentation_job_needs_its_experiment(tmp_path):
    path = _write(tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    del doc["job"]["experiment"]
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert ops.plan_batches(str(path)) == {
        "result": "error",
        "reason": "experimentation declares no job.experiment",
    }


def test_a_candidate_runs_as_its_author(tmp_path):
    units = [_candidate("A", role="reviewer")]
    sentence = "unit A is a candidate authored by implementer but runs as reviewer"
    assert ops.plan_batches(str(_write(tmp_path, units=units)))["reason"] == sentence


def test_candidates_sharing_touches_are_not_held(tmp_path):
    path = _write(tmp_path)
    answer = ops.plan_batches(str(path))
    assert answer["ready"] == ["A", "B"] and "held" not in answer
    assert ops.clock_in(str(path))["result"] == "brief"
    assert ops.clock_in(str(path), "B")["result"] == "brief"


def test_the_concurrency_cap_refuses_the_next_candidate(tmp_path):
    units = [_candidate("A"), _candidate("B"), _candidate("C")]
    path = _write(tmp_path, units=units)
    assert ops.clock_in(str(path))["result"] == "brief"
    assert ops.clock_in(str(path), "B")["result"] == "brief"
    _refused(path, lambda: ops.clock_in(str(path), "C"),
             "experiment allows 2 candidates in flight; A, B hold them")


def test_a_candidate_past_its_budget_is_refused(tmp_path):
    path = _write(tmp_path, experiment_extra={"candidate_budget": {"tokens": 100}})
    line = {"tokens": 100, "duration_ms": 1}
    assert _out(path, "A", status="todo", accounting=line)["result"] == "ok"
    _refused(path, lambda: ops.clock_in(str(path), "A"),
             "candidate A budget tokens spent: 100 of 100; "
             "drop it or raise job.experiment.candidate_budget")
    assert ops.clock_in(str(path), "B")["result"] == "brief"


def test_base_sha_and_harness_are_frozen_at_first_read(tmp_path):
    path = _write(tmp_path)
    assert ops.clock_in(str(path))["result"] == "brief"
    log = path.with_name(path.name + ".log.jsonl").read_text(encoding="utf-8")
    frozen = [
        json.loads(line) for line in log.splitlines() if json.loads(line).get("event") == "frozen"
    ]
    assert [(f["base_sha"], f["harness"]) for f in frozen] == [("c" * 40, "make bench")]
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["job"]["experiment"]["harness"] = "make bench-fast"
    path.write_text(json.dumps(doc), encoding="utf-8")
    sentence = "job.experiment.harness is frozen at make bench; the checkpoint says make bench-fast"
    _refused(path, lambda: ops.clock_in(str(path), "B"), sentence)
    _refused(path, lambda: _out(path, "A", _submit(SHA_A, "1")), sentence)


def test_submit_refusals_write_nothing(tmp_path):
    path = _write(tmp_path)
    cases = [
        (None, "candidate A submitted no commit; report {kind: commit, ref: <full sha>}"),
        (_submit("abc123", "1"), "candidate A commit abc123 is not a full sha"),
        ([{"kind": "commit", "ref": SHA_A}],
         "candidate A submitted no score; report {kind: score, ref: <number>}"),
        (_submit(SHA_A, "fast"), "candidate A score fast is not a number"),
    ]
    for produced, sentence in cases:
        _refused(path, lambda produced=produced: _out(path, "A", produced), sentence)
    assert _out(path, "A", status="blocked")["result"] == "ok"


def test_validation_refusals_write_nothing(tmp_path):
    path = _write(tmp_path)
    assert _out(path, "A", _submit(SHA_A, "12.5"))["result"] == "ok"
    ops.clock_in(str(path), "VA")
    _refused(path, lambda: _out(path, "VA", []),
             "unit VA validates A but reports no validated-sha")
    _refused(path, lambda: _out(path, "VA", [{"kind": "validated-sha", "ref": SHA_B}]),
             f"unit VA validated {SHA_B}, but A submitted {SHA_A}")
    (tmp_path / "vb").mkdir()
    early = _write(tmp_path / "vb", cursor="VB")
    _refused(early, lambda: _out(early, "VB", [{"kind": "validated-sha", "ref": SHA_B}]),
             "unit VB validates B, which has submitted no commit")


def test_the_ranking_names_validated_candidates_only(tmp_path):
    path = _write(tmp_path)
    assert ops.plan_batches(str(path))["winner"] is None
    assert _out(path, "A", _submit(SHA_A, "12.5"))["result"] == "ok"
    assert _out(path, "B", _submit(SHA_B, "9"))["result"] == "ok"
    assert ops.plan_batches(str(path))["ranking"] == []
    assert _out(path, "VA", [{"kind": "validated-sha", "ref": SHA_A}])["result"] == "ok"
    answer = ops.plan_batches(str(path))
    assert answer["ranking"] == [{"id": "A", "score": "12.5", "sha": SHA_A}]
    assert answer["winner"] == "A"
    assert _out(path, "VB", [{"kind": "validated-sha", "ref": SHA_B}])["result"] == "ok"
    answer = ops.plan_batches(str(path))
    assert [e["id"] for e in answer["ranking"]] == ["B", "A"]
    assert answer["winner"] == "B"


def test_a_plan_outside_an_experiment_has_no_ranking(tmp_path):
    units = [_unit("A"), _unit("B")]
    path = _write(tmp_path, units=units)
    doc = json.loads(path.read_text(encoding="utf-8"))
    del doc["job"]["kind"], doc["job"]["experiment"]
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert "ranking" not in ops.plan_batches(str(path))
