"""#226: `shiftwork.draft` — tickets in, a schema-valid checkpoint and its briefs out."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from bantamkit import shiftwork

JOB = {
    "id": "job-x",
    "goal": "ship the thing",
    "done_definition": "the thing is shipped",
    "constraints": ["both runtimes"],
}
REPO = {"branch": "feat/x", "head_sha": "abc1234", "dirty": False}


def _ticket(ticket_id: str, **extra) -> dict:
    return {
        "id": ticket_id,
        "title": f"do {ticket_id}",
        "role": "implementer",
        "verify": f"make test-{ticket_id}",
        "data_shape": f"{ticket_id}.json: {{id, value}}",
        "brief": f"Build {ticket_id}.",
    } | extra


def _three() -> list[dict]:
    return [
        _ticket("a"),
        _ticket("b", depends_on=["a"]),
        _ticket("c", depends_on=["a"], priority=5),
        _ticket("d", depends_on=["b", "c"]),
    ]


def test_dry_run_composes_a_valid_checkpoint_and_touches_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    answer = shiftwork.draft(JOB, _three(), REPO)
    assert answer["result"] == "draft", answer
    assert answer["written"] == []
    assert list(tmp_path.iterdir()) == []
    doc = answer["checkpoint"]
    assert doc["version"] == 1 and doc["job"] == JOB
    assert doc["plan"]["cursor"] == "a" == answer["cursor"]
    assert answer["batches"] == [["a"], ["c", "b"], ["d"]]
    assert answer["width"] == 2
    unit = doc["plan"]["units"][1]
    assert unit == {
        "id": "b",
        "title": "do b",
        "brief_path": ".shiftwork/briefs/b.md",
        "status": "todo",
        "role": "implementer",
        "depends_on": ["a"],
        "verify": "make test-b",
    }
    assert "priority" not in doc["plan"]["units"][2]
    assert doc["state"] == {
        "repo": REPO,
        "artifacts": [{"path": f".shiftwork/briefs/{x}.md", "role": "brief"} for x in "abcd"],
        "external": [],
    }
    assert doc["history"] == [] and doc["retro"] == []
    assert doc["handoff"] == {
        "next_action": "Read .shiftwork/briefs/a.md and clock in a.",
        "open_questions": [],
        "do_not": [],
    }


def test_brief_bytes_are_lf_with_one_trailing_newline_folded():
    ticket = _ticket("t", title="ทดสอบ title", brief="line one\r\nline two\r\n\r\n")
    answer = shiftwork.draft(JOB, [ticket], REPO, briefs_dir="briefs/")
    brief = answer["briefs"][0]
    assert brief["path"] == "briefs/t.md"
    assert brief["bytes"] == (
        "# t — ทดสอบ title\n\nline one\nline two\n\n"
        "## Data shape\n\nt.json: {id, value}\n\n## Verify\n\n`make test-t`\n"
    )


def test_caller_handoff_and_artifacts_are_kept():
    answer = shiftwork.draft(
        JOB,
        [_ticket("a")],
        REPO,
        handoff={"do_not": ["no force push"], "notes": "n", "next_action": "ignored"},
        artifacts=[{"path": "docs/spec.md", "role": "spec"}],
    )
    doc = answer["checkpoint"]
    assert doc["handoff"]["do_not"] == ["no force push"]
    assert doc["handoff"]["notes"] == "n"
    assert doc["handoff"]["next_action"] == "Read .shiftwork/briefs/a.md and clock in a."
    assert doc["state"]["artifacts"][-1] == {"path": "docs/spec.md", "role": "spec"}


def test_refusals_in_their_fixed_order():
    cases = [
        ((None, [_ticket("a")], REPO), "job must be an object"),
        ((JOB, [], REPO), "tickets must be a non-empty list"),
        ((JOB, [_ticket("a")], "x"), "repo must be an object"),
        ((JOB, ["x"], REPO), "tickets[0] must be an object"),
        ((JOB, [{"title": "t"}], REPO), "tickets[0].id must be a non-empty string"),
        (
            (JOB, [_ticket("../a")], REPO),
            "ticket ../a cannot name a brief file; "
            "an id holds no /, \\ or : and does not start with .",
        ),
        ((JOB, [_ticket("a", title="")], REPO), "ticket a has no title"),
        ((JOB, [_ticket("a", role=None)], REPO), "ticket a has no role"),
        (
            (JOB, [_ticket("a", verify="")], REPO),
            "ticket a has no verify; done-ness is a command, not a claim",
        ),
        (
            (JOB, [_ticket("a", data_shape="")], REPO),
            "ticket a has no data_shape; a ticket without one is not ready to execute",
        ),
        ((JOB, [_ticket("a", brief=3)], REPO), "ticket a has no brief"),
        (
            (JOB, [_ticket("a", depends_on="b")], REPO),
            "nodes[0].depends_on must be a list of strings",
        ),
        ((JOB, [_ticket("a"), _ticket("a")], REPO), "duplicate node id a"),
        (
            (JOB, [_ticket("a", depends_on=["z"])], REPO),
            "node a depends on z, which no node declares",
        ),
        (
            (JOB, [_ticket("a", depends_on=["b"]), _ticket("b", depends_on=["a"])], REPO),
            "the graph has a cycle: a -> b -> a",
        ),
        (
            (JOB | {"roles": {"reviewer": ["m"], "planner": ["m"]}}, [_ticket("a")], REPO),
            "ticket a names role implementer, which job.roles does not declare; "
            "declared is planner, reviewer",
        ),
    ]
    for args, reason in cases:
        assert shiftwork.draft(*args) == {"result": "error", "reason": reason}, reason


def test_the_ticket_shape_wins_over_the_graph_and_the_graph_over_roles():
    jobs = JOB | {"roles": {"reviewer": ["m"]}}
    tickets = [_ticket("a", depends_on=["z"]), _ticket("b", verify="")]
    assert shiftwork.draft(jobs, tickets, REPO)["reason"].startswith("ticket b has no verify")
    tickets = [_ticket("a", depends_on=["z"])]
    assert shiftwork.draft(jobs, tickets, REPO)["reason"] == (
        "node a depends on z, which no node declares"
    )


def test_unknown_ticket_keys_go_to_the_unit_and_the_schema_judges_them():
    answer = shiftwork.draft(
        JOB, [_ticket("a", touches=["x.py"], irreversible="pushes a tag")], REPO
    )
    assert answer["result"] == "draft", answer
    assert answer["checkpoint"]["plan"]["units"][0]["touches"] == ["x.py"]
    refused = shiftwork.draft(JOB, [_ticket("a", colour="red")], REPO)
    assert refused["result"] == "error"
    assert "colour" in refused["reason"]
    refused = shiftwork.draft(JOB, [_ticket("a", role="driver")], REPO)
    assert refused["result"] == "error" and "driver" in refused["reason"]


def test_a_review_the_plan_would_refuse_is_refused_here():
    tickets = [_ticket("a"), _ticket("r", depends_on=["a"], reviews=["a"])]
    assert shiftwork.draft(JOB, tickets, REPO) == {
        "result": "error",
        "reason": "unit r reviews a in the same role implementer; a review needs another role",
    }


def test_write_lands_briefs_then_checkpoint_and_round_trips(tmp_path):
    checkpoint = tmp_path / "sw" / "job.json"
    briefs_dir = str(tmp_path / "sw" / "briefs")
    answer = shiftwork.draft(
        JOB, _three(), REPO, checkpoint=str(checkpoint), briefs_dir=briefs_dir, write=True
    )
    assert answer["result"] == "draft", answer
    assert answer["written"] == [f"{briefs_dir}/{x}.md" for x in "abcd"] + [str(checkpoint)]
    assert json.loads(checkpoint.read_text(encoding="utf-8")) == answer["checkpoint"]
    assert checkpoint.read_bytes() == (json.dumps(answer["checkpoint"], indent=2) + "\n").encode()
    for brief in answer["briefs"]:
        assert Path(brief["path"]).read_bytes() == brief["bytes"].encode("utf-8")
    assert not Path(f"{checkpoint}.lock").exists()
    plan = shiftwork.plan_batches(str(checkpoint))
    assert plan["result"] == "plan" and plan["ready"] == ["a"]
    brief = shiftwork.clock_in(str(checkpoint))
    assert brief["result"] == "brief" and brief["unit"]["brief_path"] == f"{briefs_dir}/a.md"


def test_a_second_write_is_refused_and_changes_nothing(tmp_path):
    checkpoint = tmp_path / "job.json"
    kwargs = {"checkpoint": str(checkpoint), "briefs_dir": str(tmp_path / "b"), "write": True}
    shiftwork.draft(JOB, _three(), REPO, **kwargs)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    again = shiftwork.draft(JOB, _three(), REPO, **kwargs)
    assert again == {
        "result": "error",
        "reason": f"checkpoint {checkpoint} already exists; shiftwork_draft never overwrites a job",
        "written": [],
    }
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_an_existing_brief_with_other_bytes_is_refused_and_identical_is_kept(tmp_path):
    briefs = tmp_path / "b"
    briefs.mkdir()
    (briefs / "a.md").write_bytes(b"someone else's brief\n")
    kwargs = {"checkpoint": str(tmp_path / "job.json"), "briefs_dir": str(briefs), "write": True}
    refused = shiftwork.draft(JOB, _three(), REPO, **kwargs)
    assert refused == {
        "result": "error",
        "reason": f"brief {briefs}/a.md already exists with different content",
        "written": [],
    }
    assert sorted(p.name for p in tmp_path.rglob("*")) == ["a.md", "b"]
    dry = shiftwork.draft(JOB, _three(), REPO, briefs_dir=str(briefs))
    (briefs / "a.md").write_bytes(dry["briefs"][0]["bytes"].encode("utf-8"))
    answer = shiftwork.draft(JOB, _three(), REPO, **kwargs)
    assert answer["result"] == "draft"
    assert f"{briefs}/a.md" not in answer["written"]
    assert len(answer["written"]) == 4


def test_the_input_is_not_mutated():
    tickets = _three()
    before = copy.deepcopy(tickets)
    shiftwork.draft(JOB, tickets, REPO, handoff={"do_not": ["x"]})
    assert tickets == before
