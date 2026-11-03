"""#264 — investigation flavor: hypotheses first, a replay by another role before a conclusion.

Literals for every sentence; the disk byte-unchanged on a refusal. Each case sets the new
field, so a check both runtimes dropped together is still red here.
"""

import json

from bantamkit import shiftwork as ops

H = [
    {"id": "H1", "claim": "the cache is stale", "falsified_by": "a cold run reproduces it"},
    {"id": "H2", "claim": "แคชไม่เกี่ยว", "falsified_by": "a warm run is clean"},
]
OBSERVED = [{"kind": "run-output", "ref": "logs/run.txt"}]


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


def _plan():
    """Run R tests H1, replay P in another role, review V of both, conclusion C."""
    return [
        _unit("R", tests=["H1"], procedure="make repro"),
        _unit("P", role="reviewer", depends_on=["R"], replay_of="R", procedure="make repro"),
        _unit("V", role="reviewer", depends_on=["R", "P"], reviews=["R"]),
        _unit("C", depends_on=["V"], concludes=True),
    ]


def _write(tmp_path, units=None, job_extra=None, cursor=None):
    job = {"id": "t264", "goal": "g", "done_definition": "d", "constraints": ["c"]}
    job.update({"kind": "investigation", "question": "why is it slow?", "hypotheses": H})
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


def _out(path, uid, status="done", produced=None, conclusion=None):
    entry = {"unit": uid, "outcome": status}
    if produced is not None:
        entry["produced"] = produced
    return ops.clock_out(str(path), uid, status, {}, entry, None, None, None, conclusion)


def _refused(path, answer, sentence):
    before = path.read_bytes()
    assert answer() == {"result": "error", "reason": sentence}
    assert path.read_bytes() == before


def test_one_hypothesis_without_a_rationale_is_refused(tmp_path):
    path = _write(tmp_path, job_extra={"hypotheses": H[:1]})
    sentence = (
        "investigation declares 1 hypotheses; it needs two, "
        "or one with job.single_hypothesis_rationale"
    )
    assert ops.plan_batches(str(path)) == {"result": "error", "reason": sentence}
    assert ops.clock_in(str(path)) == {"result": "error", "reason": sentence}


def test_one_hypothesis_with_a_rationale_plans(tmp_path):
    extra = {"hypotheses": H[:1], "single_hypothesis_rationale": "only one path touches it"}
    assert ops.plan_batches(str(_write(tmp_path, job_extra=extra)))["result"] == "plan"


def test_the_fields_outside_an_investigation_need_no_hypotheses(tmp_path):
    units = [_unit("A"), _unit("B")]
    extra = {"kind": None}
    path = _write(tmp_path, units=units, job_extra=extra)
    doc = json.loads(path.read_text(encoding="utf-8"))
    for key in ("kind", "question", "hypotheses"):
        doc["job"].pop(key)
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert ops.clock_in(str(path))["result"] == "brief"


def test_a_run_testing_an_undeclared_hypothesis_is_refused(tmp_path):
    units = [_unit("R", tests=["H9"], procedure="x")]
    path = _write(tmp_path, units=units)
    assert ops.plan_batches(str(path))["reason"] == "unit R tests H9, which no hypothesis declares"


def test_replay_refusals(tmp_path):
    cases = [
        (dict(replay_of="Z", procedure="make repro"), "unit P replays Z, which no unit declares"),
        (
            dict(role="implementer", replay_of="R", procedure="make repro"),
            "unit P replays R in the same role implementer; a replay needs another role",
        ),
        (
            dict(replay_of="R", procedure="make  repro"),
            "unit P replays R with a different procedure",
        ),
    ]
    for n, (extra, sentence) in enumerate(cases):
        d = tmp_path / str(n)
        d.mkdir()
        p = {"role": "reviewer", **extra}
        run = _unit("R", tests=["H1"], procedure="make repro")
        units = [run, _unit("P", depends_on=["R"], **p)]
        assert ops.plan_batches(str(_write(d, units=units)))["reason"] == sentence
    units = [_unit("R", tests=["H1"]), _unit("P", role="reviewer", replay_of="R", procedure="x")]
    answer = ops.plan_batches(str(_write(tmp_path, units=units)))
    assert answer["reason"] == "unit P replays R, which names no procedure"


def test_a_run_done_without_run_output_is_refused_and_writes_nothing(tmp_path):
    path = _write(tmp_path)
    sentence = "run R produced no run-output; record what it observed"
    _refused(path, lambda: _out(path, "R"), sentence)
    _refused(path, lambda: _out(path, "R", produced=[{"kind": "commit", "ref": "abc"}]), sentence)
    assert _out(path, "R", status="blocked")["result"] == "ok"


def test_a_run_with_run_output_clocks_out(tmp_path):
    path = _write(tmp_path)
    assert _out(path, "R", produced=OBSERVED)["result"] == "ok"


def _to_conclusion(tmp_path, units=None):
    """Every unit before C done, C the cursor."""
    units = _plan() if units is None else units
    for unit in units:
        if unit["id"] != "C":
            unit["status"] = "done"
    return _write(tmp_path, units=units, cursor="C")


def test_a_full_resolved_run(tmp_path):
    path = _write(tmp_path)
    assert _out(path, "R", produced=OBSERVED)["result"] == "ok"
    assert _out(path, "P", produced=OBSERVED)["result"] == "ok"
    assert _out(path, "V")["result"] == "ok"
    conclusion = {"outcome": "resolved", "supported": "H1", "evidence": ["logs/run.txt"]}
    assert _out(path, "C", conclusion=conclusion)["result"] == "ok"
    assert json.loads(path.read_text(encoding="utf-8"))["job"]["conclusion"] == conclusion


def test_only_a_concluding_unit_concludes(tmp_path):
    path = _write(tmp_path)
    conclusion = {"outcome": "stopped", "evidence": []}
    sentence = "unit R does not conclude; job.conclusion is set only by a unit with concludes: true"
    _refused(path, lambda: _out(path, "R", produced=OBSERVED, conclusion=conclusion), sentence)


def test_resolved_refusals_write_nothing(tmp_path):
    base = {"outcome": "resolved", "evidence": ["e"]}
    path = _to_conclusion(tmp_path)
    _refused(path, lambda: _out(path, "C", conclusion=base),
             "a resolved conclusion names no supported hypothesis")
    _refused(path, lambda: _out(path, "C", conclusion={**base, "supported": "H9"}),
             "conclusion supports H9, which no hypothesis declares")
    _refused(path, lambda: _out(path, "C", conclusion={**base, "supported": "H2"}),
             "conclusion supports H2, but no run testing it is done")

    def without(uid, tag):
        d = tmp_path / tag
        d.mkdir()
        units = _plan()
        for unit in units:
            if unit["id"] != "C":
                unit["status"] = "done"
        next(u for u in units if u["id"] == uid)["status"] = "todo"
        return _write(d, units=units, cursor="C")

    p = without("P", "no-replay")
    _refused(p, lambda: _out(p, "C", conclusion={**base, "supported": "H1"}),
             "conclusion supports H1, but no run testing it has a done replay")
    v = without("V", "no-review")
    _refused(v, lambda: _out(v, "C", conclusion={**base, "supported": "H1"}),
             "conclusion supports H1, but no review of its runs is done")


def test_inconclusive_and_stopped_are_never_refused(tmp_path):
    for n, outcome in enumerate(["inconclusive", "stopped"]):
        d = tmp_path / str(n)
        d.mkdir()
        path = _write(d, cursor="C")
        conclusion = {"outcome": outcome, "supported": "H1", "evidence": []}
        assert _out(path, "C", conclusion=conclusion)["result"] == "ok"
