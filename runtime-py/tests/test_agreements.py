"""#261 — agreements: a lesson adopted once rides on every later brief.

Literals for the brief key, the retro entry and both refusals; the disk byte-unchanged on a
refusal. Spec: `docs/superpowers/specs/2026-11-03-shiftwork-agreements-design.md`.
"""

import json

from bantamkit import shiftwork as ops


def _write(tmp_path, agreements=None):
    job = {"id": "t261", "goal": "g", "done_definition": "d", "constraints": ["c"]}
    if agreements is not None:
        job["agreements"] = agreements
    doc = {
        "version": 1,
        "job": job,
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


def _out(path, change):
    entry = {"unit": "A", "outcome": "done"}
    return ops.clock_out(str(path), "A", "done", {}, entry, None, None, change)


def _doc(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_brief_with_none_adopted_carries_an_empty_list(tmp_path):
    assert ops.clock_in(str(_write(tmp_path)))["agreements"] == []


def test_adopt_then_every_later_brief_carries_it_and_retro_records_it(tmp_path):
    path = _write(tmp_path)
    assert _out(path, {"adopt": ["run --all under Node 20", "อ่านก่อนเขียน"]})["result"] == "ok"
    assert ops.clock_in(str(path))["agreements"] == ["run --all under Node 20", "อ่านก่อนเขียน"]
    assert _doc(path)["retro"] == [
        {
            "trigger": "A",
            "patch_applied_to": "job.agreements",
            "adopted": ["run --all under Node 20", "อ่านก่อนเขียน"],
            "retired": [],
        }
    ]


def test_retire_by_exact_text_then_adopt_and_a_duplicate_is_a_no_op(tmp_path):
    path = _write(tmp_path, ["one", "two"])
    assert _out(path, {"retire": ["one"], "adopt": ["two", "three"]})["result"] == "ok"
    assert _doc(path)["job"]["agreements"] == ["two", "three"]
    assert _doc(path)["retro"][0]["adopted"] == ["three"]
    assert _doc(path)["retro"][0]["retired"] == ["one"]


def test_a_change_that_moves_nothing_records_nothing(tmp_path):
    path = _write(tmp_path, ["one"])
    assert _out(path, {"adopt": ["one"]})["result"] == "ok"
    assert _doc(path)["retro"] == []


def test_retiring_text_not_on_the_list_is_refused_and_nothing_written(tmp_path):
    path = _write(tmp_path, ["one"])
    before = path.read_bytes()
    refused = {"result": "error", "reason": "no agreement reads 'One'"}
    assert _out(path, {"retire": ["One"]}) == refused
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".log.jsonl").exists()


def test_over_twenty_is_refused(tmp_path):
    path = _write(tmp_path, [f"a{n}" for n in range(19)])
    assert ops.AGREEMENTS_MAX == 20
    assert _out(path, {"adopt": ["x", "y"]}) == {
        "result": "error",
        "reason": "agreements would number 21; retire one first (at most 20)",
    }
    assert _out(path, {"adopt": ["x", "y"], "retire": ["a0"]})["result"] == "ok"
