"""#310 live runner: real Shiftwork over MCP stdio, a fake Codex executable, no model calls."""

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
# Red-proofs point this at a deliberately broken copy; the default is the real runner.
TARGET = Path(os.environ.get("LIVE_RUN_UNDER_TEST", HERE / "live_run.py"))


def load():
    spec = importlib.util.spec_from_file_location("grouped_live_run", TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lr = load()
CASES = {c["id"]: c for c in lr.live_cases.live_cases()}
FRESH = {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 10}
RESUMED = {"input_tokens": 300, "cached_input_tokens": 250, "output_tokens": 7}

FAKE = r'''
import json, os, re, shutil, sys, time, uuid
from pathlib import Path

scn = json.loads(Path(os.environ["FAKE_CODEX_SCENARIO"]).read_text())
argv = sys.argv[1:]
if argv == ["--version"]:
    print("fake-codex 0.0.0")
    sys.exit(0)
if argv[:2] == ["features", "list"]:
    print("fake_feature  stable  true")
    sys.exit(0)
prompt = sys.stdin.read()
resume = argv[:2] == ["exec", "resume"]
# T1 drops --output-schema: a tools-disabled call carrying a review request is a review;
# any other tools-disabled call is a T2 patch repair.
tools_off = "shell_tool" in argv
# RR: a resumed re-review carries only a delta turn, not a REVIEW REQUEST.
rereview = resume and tools_off and "RE-REVIEW DELTA:\n" in prompt
review = ("--output-schema" in argv or (tools_off and "REVIEW REQUEST:\n" in prompt)
          or rereview)
patch = tools_off and not review
cwd = Path(argv[argv.index("-C") + 1]) if "-C" in argv else Path.cwd()
thread = argv[-2] if resume else str(uuid.uuid4())
reference = Path(scn["reference_dir"])
owned = re.findall(r"^Files you own: (.+)$", prompt, re.M)
files = [f.strip() for f in owned[-1].split(",")] if owned else []


def emit(obj):
    print(json.dumps(obj), flush=True)


def bump(name):
    counter = Path(scn["log"] + "." + name)
    n = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(n + 1))
    return n


if not (review and not resume and "--ephemeral" not in argv
        and bump("first_reviews") < scn.get("no_thread_first", 0)):
    emit({"type": "thread.started", "thread_id": thread})
if review and scn.get("fail_review"):
    sys.exit(4)
if rereview and bump("rereviews_started") < scn.get("fail_resume", 0):
    sys.exit(5)
if (review and not resume and "--ephemeral" not in argv
        and bump("persistent_reviews") < scn.get("garbage_persistent_reviews", 0)):
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "not json"}})
    emit({"type": "turn.completed", "usage": scn["fresh"]})
    sys.exit(0)
if rereview and bump("rereviews") < scn.get("garbage_rereviews", 0):
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "not json"}})
    emit({"type": "turn.completed", "usage": scn["resumed"]})
    sys.exit(0)
if not review and any(f in scn.get("fail_for", []) for f in files):
    sys.exit(3)
if review and bump("reviews") < scn.get("garbage_reviews", 0):
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "not json"}})
    emit({"type": "turn.completed", "usage": scn["fresh"]})
    sys.exit(0)
if (review and "--output-schema" not in argv
        and bump("schemaless_reviews") < scn.get("garbage_tuned_reviews", 0)):
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "not json"}})
    emit({"type": "turn.completed", "usage": scn["fresh"]})
    sys.exit(0)
if review:
    state_file = Path(scn["log"] + ".request." + thread)
    if rereview:
        # The thread remembers its last request; the delta updates it.
        delta = json.loads(prompt.split("RE-REVIEW DELTA:\n", 1)[1])
        request = json.loads(state_file.read_text())
        by_id = {u["id"]: u for u in delta["units"]}
        for u in request["units"]:
            u["revision"] = by_id[u["id"]]["revision"]
            u["fast_check_passed"] = by_id[u["id"]]["fast_check_passed"]
        request["context_files"].update(delta["changed_files"])
        request["reviewer_context_id"] = delta["reviewer_context_id"]
    else:
        request = json.loads(prompt.split("REVIEW REQUEST:\n", 1)[1])
    state_file.write_text(json.dumps(request))
    findings = []
    for unit in request["units"]:
        ids = [c["id"] for c in unit["criteria"]]
        if scn["reviewer"] == "detect":
            differs = any(
                request["context_files"].get(f) != (reference / f).read_text()
                for f in unit["files"]
            )
            if differs:
                findings += [{"unit": unit["id"], "criterion": c, "detail": "differs"} for c in ids]
        elif scn["reviewer"] == "reject":
            findings.append({"unit": unit["id"], "criterion": ids[0], "detail": "never good"})
    answer = {
        "reviewer_context_id": request["reviewer_context_id"],
        "findings": findings,
        "evidence": [
            {"unit": u["id"], "revision": u["revision"], "criteria": [c["id"] for c in u["criteria"]]}
            for u in request["units"]
        ],
    }
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(answer)}})
elif patch:
    # One answer per patch call, in order: good | garbage | foreign | red.
    modes = scn.get("patch", [])
    n = bump("patches")
    mode = modes[n] if n < len(modes) else "good"
    rows = [{"path": f, "content": (reference / f).read_text()} for f in files]
    if mode == "red":
        rows = [{"path": f, "content": "this is not python (\n"} for f in files]
    if mode == "foreign":
        rows.append({"path": scn["foreign_path"], "content": "# overwritten\n"})
    text = "not json" if mode == "garbage" else json.dumps({"files": rows})
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": text}})
else:
    time.sleep(scn.get("delay", 0))
    for rel in files:
        (cwd / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(reference / rel, cwd / rel)
        # Restores another unit's file to the reference (an unowned write).
        for other in scn.get("also_write", {}).get(rel, []):
            shutil.copyfile(reference / other, cwd / other)
        if rel in scn.get("audit_for", {}):
            emit({"type": "item.completed", "item": {
                "id": "cmd1", "type": "command_execution", "status": "completed",
                "command": scn["audit_for"][rel]}})
    for n in range(scn.get("steps", 0)):
        emit({"type": "item.completed", "item": {
            "id": f"step{n}", "type": "command_execution", "status": "completed",
            "command": "true"}})
    if scn.get("change_items"):
        for rel in files:
            emit({"type": "item.completed", "item": {
                "type": "file_change", "status": "completed",
                "changes": [{"path": rel, "kind": "update"}]}})
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "done"}})
# Like the real CLI (probe 2026-11-13), a resumed call reports the SESSION's running
# total, not its own usage; a fresh call's total is its own. The session spends tokens
# even when this call reports none, so the total grows either way.
own = scn["resumed"] if resume else scn["fresh"]
state = Path(scn["log"] + ".total." + thread)
before = json.loads(state.read_text()) if resume and state.exists() else {}
total = {k: before.get(k, 0) + v for k, v in own.items()}
state.write_text(json.dumps(total))
if not any(f in scn.get("no_usage_for", []) for f in files) and not (
        rereview and scn.get("no_usage_rereview")):
    # per_turn_for: a call that reports its own usage, not the running total.
    per_turn = any(f in scn.get("per_turn_for", []) for f in files)
    emit({"type": "turn.completed", "usage": own if per_turn else total})
with open(scn["log"], "a") as log:
    log.write(json.dumps({"argv": argv, "cwd": str(cwd), "resume": resume, "review": review,
                          "patch": patch, "thread": thread, "files": files,
                          "rereview": bool(rereview)}) + "\n")
'''


def fake_codex(tmp_path, monkeypatch, case_id, **scenario):
    script = tmp_path / "fake_codex.py"
    script.write_text(FAKE, encoding="utf-8")
    log = tmp_path / "fake-log.jsonl"
    config = {
        "reference_dir": CASES[case_id]["reference_dir"],
        "reviewer": "detect",
        "fresh": FRESH,
        "resumed": RESUMED,
        "log": str(log),
        **scenario,
    }
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", str(path))
    return [sys.executable, str(script)], log


def run(tmp_path, monkeypatch, case_id, smoke=False, **scenario):
    codex, log = fake_codex(tmp_path, monkeypatch, case_id, **scenario)
    out = tmp_path / "out"
    summary = lr.run_live(out, [CASES[case_id]], repeats=1, smoke=smoke, codex_bin=codex)
    records = lr.read_runs(out)
    calls = [json.loads(s) for s in log.read_text().splitlines()]
    return out, summary, {r["arm"]: r for r in records}, calls


def checkpoint(out, record):
    return json.loads((out / record["checkpoint"]).read_text(encoding="utf-8"))


def ledger(out, record):
    path = out / (record["checkpoint"] + ".log.jsonl")
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]


def units_of(document):
    return {u["id"]: u for u in document["plan"]["units"]}


def usage_of(fresh, resumed):
    calls = [(FRESH, fresh), (RESUMED, resumed)]
    return {
        "uncached_input": sum((u["input_tokens"] - u["cached_input_tokens"]) * n for u, n in calls),
        "cache_read": sum(u["cached_input_tokens"] * n for u, n in calls),
        "output": sum(u["output_tokens"] * n for u, n in calls),
        "turns": fresh + resumed,
    }


# --- plan shapes ------------------------------------------------------------------


async def _plan_all(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command="node", args=[str(lr.ROOT / "runtime-ts/dist/cli.js")], cwd=str(lr.ROOT)
    )
    answers = {}
    async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        for case_id, case in CASES.items():
            for arm in lr.ARMS:
                base = tmp_path / f"{case_id}-{arm}"
                drafted = await client.call_tool(
                    "shiftwork_draft",
                    {
                        "checkpoint": str(base / "ck.json"),
                        "briefs_dir": str(base / "briefs"),
                        "write": True,
                        "job": {"id": "j", "goal": "g", "done_definition": "d", "constraints": [],
                                "roles": {"implementer": [lr.MODEL], "reviewer": [lr.MODEL]}},
                        "repo": {"branch": "b", "head_sha": "x", "dirty": False},
                        "tickets": lr.arm_tickets(case, arm),
                    },
                )
                assert drafted.structured_content["result"] == "draft", drafted.structured_content
                plan = await client.call_tool("shiftwork_plan", {"checkpoint": str(base / "ck.json")})
                answers[(case_id, arm)] = plan.structured_content
    return answers


def test_arm_plans_have_the_design_shape_and_real_shiftwork_plan_accepts_them(tmp_path):
    answers = asyncio.run(_plan_all(tmp_path))
    assert all(a["result"] == "plan" for a in answers.values())
    for case in CASES.values():
        for arm in lr.ARMS:
            tickets = {t["id"]: t for t in lr.arm_tickets(case, arm)}
            reviewers = {k: t for k, t in tickets.items() if t["role"] == "reviewer"}
            for t in reviewers.values():
                assert set(t["reviews"]) <= set(t["depends_on"])
            if arm == "per-task":
                for unit in case["units"]:
                    assert reviewers[f"QA_{unit['id']}"]["reviews"] == [unit["id"]]
                    assert tickets[unit["id"]]["depends_on"] == [
                        f"QA_{d}" for d in unit["depends_on"]
                    ]
    grouped = {t["id"]: t for t in lr.arm_tickets(CASES["native-chain"], "grouped")}
    assert grouped["R"]["reviews"] == ["A", "B", "C"]
    assert grouped["C"]["depends_on"] == ["B"]
    fork = {t["id"]: t for t in lr.arm_tickets(CASES["mixed-fork-join"], "grouped")}
    assert fork["QA_K"]["reviews"] == ["K"]
    assert fork["B"]["depends_on"] == fork["C"]["depends_on"] == ["QA_K"]
    assert fork["R"]["reviews"] == ["B", "C", "I"]
    # Both arms brief the authors with the same task text; nothing hidden reaches a brief.
    for case in CASES.values():
        texts = [t["brief"] for t in lr.arm_tickets(case, "per-task")]
        assert all("oracle" not in text.lower() for text in texts)


# --- end to end with a fake Codex ----------------------------------------------------


def test_native_chain_detecting_reviewer_full_protocol(tmp_path, monkeypatch):
    out, summary, arms, calls = run(tmp_path, monkeypatch, "native-chain")
    # The summary written to disk is exactly what runs.jsonl recomputes to.
    written = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(lr.summarize_live(lr.read_runs(out))))
    assert written == json.loads(json.dumps(summary))
    meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert meta["codex_cli_version"] == "fake-codex 0.0.0"
    # The features probe says what it probed: role flags, user config NOT ignored.
    features = meta["codex_environment"]["features"]
    assert "config.toml applied" in features["label"]
    assert features["author"]["argv"][:2] == ["features", "list"]
    assert {"apps", "multi_agent"} <= set(features["author"]["argv"])
    assert {"shell_tool", "unified_exec"} <= set(features["review"]["argv"])
    assert features["author"]["output"] == "fake_feature  stable  true"
    assert set(meta["harness_sha256"]) == {"live_run", "live_cases", "run_eval", "codex_adapter"}
    # Counterbalanced: repeat 0 runs per-task first.
    assert [r["arm"] for r in lr.read_runs(out)] == ["per-task", "grouped"]

    for record in arms.values():
        assert record["status"] == "accepted", record["stop_reason"]
        assert record["quality"]["quality_failure"] is False
        assert record["observations"]["holds"] is True
        # Both seeds were applied and caught at the review that saw them.
        assert [s["caught"] for s in record["quality"]["seeds"]] == [True, True]
        assert all(s["status"] == "caught" and s["presence"] == "present"
                   for s in record["quality"]["seeds"])
        assert record["stop_kind"] is None and record["access_audit"]["clean"]
        assert record["writes"]["unowned"] == [] and record["writes"]["conflict_free"] is True
        assert record["human_interventions_label"].startswith("unattended")
        assert record["codex_env_sha256"] == meta["codex_environment"]["sha256"]
        # Workspaces were opaque temp dirs outside the repo and the output, now removed.
        tmp_ws = Path(record["workspace_tmp"]).resolve()
        assert not tmp_ws.exists() and (out / record["workspace"]).is_dir()
        assert lr.ROOT not in tmp_ws.parents and out not in tmp_ws.parents
        # No prompt names the repository, the output dir or a brief path.
        for call in record["calls"]:
            prompt = (out / call["artifact_dir"] / "prompt.txt").read_text(encoding="utf-8")
            assert str(lr.ROOT) not in prompt and str(out) not in prompt
            assert "brief_path" not in prompt and "next_action" not in prompt
            assert call["turn_usages"] and call["reported_cumulative"]
            assert call["usage_raw"] is not None and "usage_unknown_reason" not in call
        assert record["usage_unknown"] == [] and record["cache_write"]["calls"] == []
        # clock_in precedes every model call and clock_out follows it.
        trace = record["trace"]
        for i, row in enumerate(trace):
            if row["event"] == "model_start":
                before = [r for r in trace[:i] if r["unit"] == row["unit"]]
                assert before[-1]["event"] == "clock_in"
                after = [r["event"] for r in trace[i + 1:] if r["unit"] == row["unit"]
                         and r["event"] in ("model_end", "clock_out", "clock_in", "model_start")]
                assert after[:2] == ["model_end", "clock_out"]
        # Every model call has a brief before it and an accounting line after it.
        lines = ledger(out, record)
        briefs = [x for x in lines if x.get("event") == "brief"]
        outs = [x for x in lines if "event" not in x]
        deterministic = [u for u in record["units"] if u.get("i2_path") == "deterministic"]
        assert len(briefs) == len(outs) == len(record["calls"]) + len(deterministic)
        for line in outs:
            if line["model"] == lr.HARNESS_MODEL:
                assert line["tokens"] == 0 and "no model call" in line["note"]
                continue
            assert line["model"] == lr.MODEL and line["duration_ms"] >= 0
            assert line["tokens"] == 70 or line["tokens"] == 57
            assert line["agent_id"]
        # Planner/dispatch spend is an explicit, labelled zero.
        assert record["planner_dispatch"]["model_tokens"] == 0

    # Native mode: one parent session, resumed per unit; every resumed turn is counted.
    for arm in lr.ARMS:
        ws = Path(arms[arm]["workspace_tmp"]).resolve()
        authors = [c for c in calls if not c["review"] and Path(c["cwd"]).resolve() == ws]
        assert len(authors) >= 3
        assert not authors[0]["resume"] and all(c["resume"] for c in authors[1:])
        assert len({c["thread"] for c in authors}) == 1
        assert {c["thread"] for c in authors}.isdisjoint(
            {c["thread"] for c in calls if c["review"]}
        )
    for record in arms.values():
        author_calls = [c for c in record["calls"] if c["kind"] != "reviewer"]
        review_calls = [c for c in record["calls"] if c["kind"] == "reviewer"]
        resumed = sum(c["resumed"] for c in author_calls)
        assert resumed == len(author_calls) - 1
        # The fake reports running totals; per call, the harness counts only the delta.
        assert record["usage"]["total"] == usage_of(
            len(review_calls) + 1, resumed
        )
        parent = [c for c in record["calls"] if c["context"] == "parent"]
        assert len(parent) >= 3 and len({c["thread_id"] for c in parent}) == 1
        for n, call in enumerate(parent):
            want = {k: FRESH[k] + n * RESUMED[k] for k in FRESH}
            assert call["reported_cumulative"] == want
            assert call["usage_raw"] == (FRESH if n == 0 else RESUMED)
            assert call["usage"] == usage_of(n == 0, n > 0)
        assert record["review_tokens"] == 110 * len(review_calls)

    per, grouped = arms["per-task"], arms["grouped"]
    # Per-task: QA_A rejects the seeded A, A2 repairs it before B runs; no recheck needed.
    doc = units_of(checkpoint(out, per))
    assert doc["QA_A"]["reviews"] == ["A", "A2-r1"] and "A2-r1" in doc["QA_A"]["depends_on"]
    assert not any(u.startswith("I2") for u in doc)
    # Grouped: R rejects A and C; repairs plus an integration recheck join both arrays.
    doc = units_of(checkpoint(out, grouped))
    added = ["A2-r1", "C2-r1", "I2-R-r1"]
    assert doc["R"]["reviews"] == ["A", "B", "C", *added]
    assert set(added) <= set(doc["R"]["depends_on"])
    assert doc["I2-R-r1"]["depends_on"] == ["A2-r1", "C2-r1", "B"]
    assert all(doc[u]["status"] == "done" for u in doc)
    # B's fast check stayed green after the repairs: the recheck made no model call.
    i2 = next(u for u in grouped["units"] if u["id"] == "I2-R-r1")
    assert i2["i2_path"] == "deterministic" and i2["calls"] == []
    assert i2["usage"] == {"uncached_input": 0, "cache_read": 0, "output": 0, "turns": 0}
    edit = out / grouped["plan_edits"][0]
    before = units_of(json.loads((edit / "before.json").read_text(encoding="utf-8")))
    after = units_of(json.loads((edit / "after.json").read_text(encoding="utf-8")))
    assert before["R"]["status"] == "blocked" and after["R"]["status"] == "todo"
    assert grouped["repair_rounds"] == {"R": 1}
    assert sorted(grouped["rework"]["units"]) == sorted(added)
    pair = summary["pairs"][0]
    assert pair["seeds"]["grouped_missed_caught_by_per_task"] == []
    assert pair["review_saving"] == 1 - grouped["review_tokens"] / per["review_tokens"]
    assert summary["adoption"] != "adopt"


def test_approving_reviewer_misses_seeds_and_oracle_failure_is_a_quality_failure(
    tmp_path, monkeypatch
):
    _, summary, arms, _ = run(tmp_path, monkeypatch, "native-chain", reviewer="approve")
    for record in arms.values():
        assert record["status"] == "accepted"
        assert [s["caught"] for s in record["quality"]["seeds"]] == [False, False]
        assert record["quality"]["seeded_missed"] == 2
        assert record["quality"]["final_oracle"]["failing"]
        assert record["quality"]["quality_failure"] is True
    verdict = summary["modes"]["native-chain"]["verdict"]
    assert verdict["checks"]["approval_coverage_holds"] is False
    assert summary["adoption"] == "blocked"


def test_third_rejection_censors_the_arm(tmp_path, monkeypatch):
    out, _, arms, _ = run(tmp_path, monkeypatch, "native-chain", reviewer="reject")
    for record in arms.values():
        assert record["status"] == "failed/censored"
        assert record["accepted"] is False and record["elapsed_to_accepted_ms"] is None
        assert record["elapsed_to_stop_ms"] > 0
        assert "repair rounds" in record["stop_reason"]
        assert max(record["repair_rounds"].values()) == lr.MAX_REPAIR_ROUNDS + 1
        assert record["rework"]["rounds"] == lr.MAX_REPAIR_ROUNDS + 1
        doc = units_of(checkpoint(out, record))
        assert not any(u.endswith("-r3") for u in doc)
        reviewer = next(u for u, x in doc.items() if x["role"] == "reviewer"
                        and x["status"] == "blocked")
        assert sum(1 for u in doc if u.endswith("-r2")) >= 1
        assert reviewer


def test_unknown_usage_stays_none_and_makes_the_total_unknown(tmp_path, monkeypatch):
    out, summary, arms, _ = run(
        tmp_path, monkeypatch, "native-chain", reviewer="approve",
        no_usage_for=["ledgerkit/lines.py"],
    )
    for record in arms.values():
        unit = next(u for u in record["units"] if u["id"] == "B")
        assert unit["usage"] is None
        assert record["total_tokens"] is None and record["total_tokens_excl_cache"] is None
        assert record["usage"]["by_kind"]["author"] is None
        assert record["review_tokens"] is not None
        line = next(x for x in ledger(out, record) if x.get("unit") == "B" and "tokens" in x)
        assert line["estimate"] is True and "unknown" in line["note"]
        # C resumes after B reported nothing: no earlier total on the thread, so unknown,
        # never C's running total counted as its own.
        c = next(u for u in record["units"] if u["id"] == "C")
        assert c["usage"] is None
        reasons = {r["unit"]: r["reason"] for r in record["usage_unknown"]}
        assert reasons["B"] == "no turn.completed usage"
        assert reasons["C"] == "resumed call with no earlier reported total on its thread"
        line = next(x for x in ledger(out, record) if x.get("unit") == "C" and "tokens" in x)
        assert line["estimate"] is True and "no earlier reported total" in line["note"]
    assert summary["pairs"][0]["total_saving"] is None
    assert summary["modes"]["native-chain"]["verdict"]["checks"][
        "median_total_tokens_decrease"
    ] is None


def test_a_resumed_total_that_falls_is_unknown_not_counted(tmp_path, monkeypatch):
    """B reports its own usage instead of the running total: output falls 10 -> 7, a
    negative delta, so B is unknown; C has no trustworthy baseline after it."""
    out, summary, arms, _ = run(
        tmp_path, monkeypatch, "native-chain", reviewer="approve",
        per_turn_for=["ledgerkit/lines.py"],
    )
    for record in arms.values():
        units = {u["id"]: u for u in record["units"]}
        assert units["A"]["usage"] == usage_of(1, 0)
        assert units["B"]["usage"] is None and units["C"]["usage"] is None
        b = next(c for c in record["calls"] if c["unit"] == "B")
        assert b["reported_cumulative"] == RESUMED and b["usage_raw"] is None
        reasons = {r["unit"]: r["reason"] for r in record["usage_unknown"]}
        assert reasons["B"] == "output_tokens fell from 10 to 7: not a cumulative total"
        assert reasons["C"] == "resumed call with no earlier reported total on its thread"
        assert record["total_tokens"] is None and record["review_tokens"] is not None


def test_smoke_runs_the_fork_join_pair_with_concurrent_delegates(tmp_path, monkeypatch, capsys):
    out, summary, arms, calls = run(tmp_path, monkeypatch, "mixed-fork-join", smoke=True,
                                    delay=0.6)
    assert set(arms) == {"per-task", "grouped"}
    assert all(r["smoke"] for r in arms.values())
    assert summary["run_count"] == 0 and summary["pairs"] == []
    smoke = summary["smoke"]
    total = sum(r["total_tokens"] for r in arms.values())
    assert smoke["projected_tokens_for_18_jobs"] == total / 2 * 18
    assert smoke["exceeds_gate"] is False
    for record in arms.values():
        assert record["status"] == "accepted", record["stop_reason"]
        obs = record["observations"]
        assert obs["contract_approval_before_consumers"] is True
        assert obs["integration_before_review"] is True
        assert obs["conflicting_writes_deferred"] is True
        assert obs["holds"] is True
        spans = {}
        for row in record["trace"]:
            if row["event"] in ("model_start", "model_end") and row["unit"] in ("B", "C"):
                spans.setdefault(row["unit"], []).append(row["t_ms"])
        assert spans["B"][0] < spans["C"][1] and spans["C"][0] < spans["B"][1]
        contexts = {c["unit"]: c["context"] for c in record["calls"] if c["kind"] == "author"}
        assert contexts == {"K": "parent", "B": "delegate", "C": "delegate", "I": "parent"}
        resumed = {c["unit"]: c["resumed"] for c in record["calls"] if c["kind"] == "author"}
        assert resumed == {"K": False, "B": False, "C": False, "I": True}
        # I resumes K's session: its report is K + I, its usage only I's.
        i = next(c for c in record["calls"] if c["unit"] == "I" and c["kind"] == "author")
        assert i["reported_cumulative"] == {k: FRESH[k] + RESUMED[k] for k in FRESH}
        assert i["usage"] == usage_of(0, 1)
        repairs = [c for c in record["calls"] if c["kind"] in ("repair", "integration")]
        assert repairs and all(c["context"] == "delegate" for c in repairs)
    assert len([c for c in calls if c["resume"]]) == 2


# --- summary and thresholds on hand-built records ----------------------------------


def record(case_id, arm, repeat=0, total=1000, review=400, latency=100.0, caught=(True, True),
           accepted=True, quality_failure=False, holds=True):
    seeds = [
        {"unit": u, "applied": c is not None, "caught": c}
        for u, c in zip(("A", "C"), caught, strict=True)
    ]
    return {
        "case_id": case_id, "mode": case_id, "repeat": repeat, "arm": arm, "smoke": False,
        "job_id": f"{case_id}-{repeat}-{arm}", "status": "accepted" if accepted else "x",
        "accepted": accepted, "total_tokens": total, "review_tokens": review,
        "total_tokens_excl_cache": total, "review_tokens_excl_cache": review,
        "elapsed_to_accepted_ms": latency if accepted else None, "elapsed_to_stop_ms": latency,
        "rework": {"rounds": 0, "units": []}, "escalations": 0, "human_interventions": 0,
        "quality": {"seeds": seeds, "quality_failure": quality_failure, "seeded_caught": 0,
                    "seeded_missed": 0, "seed_unavailable": 0, "true_findings": 0,
                    "false_findings": 0, "unknown_findings": 0, "author_defects_missed": []},
        "observations": {"holds": holds},
    }


MODES = ("native-chain", "sequential-delegates", "mixed-fork-join")


def good_run(**grouped_overrides):
    records = []
    for mode in MODES:
        for repeat in range(3):
            records.append(record(mode, "per-task", repeat))
            grouped = {"total": 600, "review": 150, "latency": 90.0}
            records.append(record(mode, "grouped", repeat,
                                  **(grouped | grouped_overrides.get(mode, {}))))
    return records


def test_all_core_modes_passing_is_still_not_adoption():
    summary = lr.summarize_live(good_run())
    assert all(m["verdict"]["result"] == "pass" for m in summary["modes"].values())
    assert summary["adoption"] == "pending-scenarios"
    assert summary["pairs"][0]["total_saving"] == pytest.approx(0.4)
    assert summary["pairs"][0]["review_saving"] == pytest.approx(0.625)
    assert summary["modes"]["native-chain"]["total_saving"]["sample_size"] == 3


@pytest.mark.parametrize(
    ("override", "check"),
    [
        ({"caught": (False, True)}, "grouped_misses_none_caught_by_per_task"),
        ({"total": 1000}, "median_total_tokens_decrease"),
        ({"latency": 101.0}, "median_accepted_latency_not_increase"),
        ({"quality_failure": True}, "approval_coverage_holds"),
        ({"holds": False}, "approval_coverage_holds"),
        ({"accepted": False}, "approval_coverage_holds"),
    ],
)
def test_each_frozen_threshold_fails_its_mode_and_blocks_adoption(override, check):
    summary = lr.summarize_live(good_run(**{"sequential-delegates": override}))
    verdict = summary["modes"]["sequential-delegates"]["verdict"]
    assert verdict["checks"][check] is False
    assert verdict["result"] == "fail"
    assert summary["modes"]["native-chain"]["verdict"]["result"] == "pass"
    assert summary["adoption"] == "blocked"


def test_unknowns_are_inconclusive_never_a_pass():
    summary = lr.summarize_live(good_run(**{"mixed-fork-join": {"total": None}}))
    verdict = summary["modes"]["mixed-fork-join"]["verdict"]
    assert verdict["checks"]["median_total_tokens_decrease"] is None
    assert verdict["result"] == "inconclusive"
    assert summary["adoption"] == "inconclusive"
    unavailable = good_run(**{"native-chain": {"caught": (None, True)}})
    for r in unavailable:
        if r["case_id"] == "native-chain":
            r["quality"]["seeds"][0].update(applied=False, caught=None)
    pair = next(p for p in lr.summarize_live(unavailable)["pairs"] if p["case_id"] == "native-chain")
    assert pair["seeds"]["excluded_unavailable"] == ["A"]
    assert pair["seeds"]["compared_units"] == ["C"]


def test_saving_needs_a_nonzero_known_baseline_and_smoke_is_kept_apart():
    assert lr.saving(0, 10) is None and lr.saving(None, 1) is None and lr.saving(10, None) is None
    assert lr.saving(200, 50) == 0.75
    records = good_run()
    smoke = [dict(record("mixed-fork-join", a, total=3_000_000), smoke=True) for a in lr.ARMS]
    summary = lr.summarize_live(records + smoke)
    assert summary["run_count"] == len(records)
    # Two smoke jobs at 3M each: 3M per job, 18 jobs.
    assert summary["smoke"]["projected_tokens_for_18_jobs"] == 54_000_000
    assert summary["smoke"]["exceeds_gate"] is True


def test_schedule_is_counterbalanced_and_smoke_is_one_fork_join_pair():
    cases = list(CASES.values())
    jobs = [(c["id"], r, a, o) for c, r, a, o in lr.schedule(cases, 3, False)]
    assert len(jobs) == 18
    assert [a for c, r, a, o in jobs if c == "native-chain"] == [
        "per-task", "grouped", "grouped", "per-task", "per-task", "grouped"
    ]
    assert [(c, r, a) for c, r, a, _ in [(c["id"], r, a, o) for c, r, a, o in
                                         lr.schedule(cases, 3, True)]] == [
        ("mixed-fork-join", 0, "per-task"), ("mixed-fork-join", 0, "grouped")
    ]


def test_usage_parsing_counts_every_turn_and_unknown_is_none():
    turns = "\n".join(json.dumps({"type": "turn.completed", "usage": u}) for u in (FRESH, RESUMED))
    assert lr.parse_usage(turns) == usage_of(1, 1)
    assert lr.parse_usage(json.dumps({"type": "thread.started"})) is None
    partial = turns + "\n" + json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1}})
    assert lr.parse_usage(partial) is None
    assert lr.sum_usage([usage_of(1, 0), None]) is None
    assert lr.usage_tokens(None) is None
    line = lr.clock_accounting(None, 5, "n")
    assert line["estimate"] is True and "cache_read_tokens" not in line


# --- harness censors, the rerun rule, isolation and real writes (QW findings) -------


def run_all(tmp_path, monkeypatch, case_id, **scenario):
    codex, log = fake_codex(tmp_path, monkeypatch, case_id, **scenario)
    out = tmp_path / "out"
    summary = lr.run_live(out, [CASES[case_id]], repeats=1, codex_bin=codex)
    return out, summary, lr.read_runs(out)


def assert_censored_twice(out, summary, records, reason):
    # Run output still written; the summary is what runs.jsonl recomputes to.
    written = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(lr.summarize_live(records)))
    # Per-task runs first, is censored, the pair is void; one rerun, same order, censored again.
    assert [(r["arm"], r["attempt"]) for r in records] == [("per-task", 0), ("per-task", 1)]
    for record in records:
        assert record["stop_kind"] == "harness" and record["accepted"] is False
        assert reason in record["stop_reason"]
    pair = summary["pairs"][0]
    assert pair["harness_censored"] is True and pair["complete"] is False
    verdict = summary["modes"][records[0]["case_id"]]["verdict"]
    # Never a fail: approval/coverage is unknown, the mode inconclusive.
    assert verdict["checks"]["approval_coverage_holds"] is None
    assert verdict["result"] == "inconclusive" and verdict["harness_censored_pairs"]
    assert summary["adoption"] == "inconclusive"
    assert [v["attempt"] for v in summary["voided_attempts"]["records"]] == [0]


def test_failed_author_call_is_a_harness_censor_and_the_pair_is_rerun_once(
    tmp_path, monkeypatch
):
    out, summary, records = run_all(tmp_path, monkeypatch, "native-chain",
                                    fail_for=["ledgerkit/lines.py"])
    assert_censored_twice(out, summary, records, "codex exited 3")
    doc = units_of(checkpoint(out, records[0]))
    assert doc["B"]["status"] == "blocked"


def test_reviewer_call_error_is_a_harness_censor(tmp_path, monkeypatch):
    out, summary, records = run_all(tmp_path, monkeypatch, "native-chain", fail_review=True)
    assert_censored_twice(out, summary, records, "reviewer call failed")
    assert all(r["rework"]["rounds"] == 0 for r in records)


def test_access_audit_hit_censors_the_arm(tmp_path, monkeypatch):
    command = "/bin/zsh -lc 'cat ../../live_fixtures/native-chain/oracle/oracle.py'"
    out, summary, records = run_all(tmp_path, monkeypatch, "native-chain",
                                    audit_for={"ledgerkit/lines.py": command})
    assert_censored_twice(out, summary, records, "access audit")
    for record in records:
        hits = record["access_audit"]["hits"]
        assert record["access_audit"]["clean"] is False
        assert [h["unit"] for h in hits] == ["B"] and hits[0]["text"] == command


def test_exception_inside_a_unit_does_not_abort_the_run(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("seeding exploded")

    monkeypatch.setattr(lr.live_cases, "seed_defect", boom)
    out, summary, records = run_all(tmp_path, monkeypatch, "native-chain")
    assert_censored_twice(out, summary, records, "seeding exploded")
    error = records[0]["harness_errors"][0]
    assert error["where"] == "unit A" and error["type"] == "RuntimeError"


def test_invalid_reviewer_answer_is_a_reviewer_error_round_not_a_rejection(
    tmp_path, monkeypatch
):
    _, summary, records = run_all(tmp_path, monkeypatch, "native-chain", garbage_reviews=1)
    per = next(r for r in records if r["arm"] == "per-task")
    assert per["status"] == "accepted", per["stop_reason"]
    assert per["rework"]["reviewer_error_rounds"] == 1
    assert per["rework"]["rejection_rounds"] >= 1
    assert per["rework"]["rounds"] == (per["rework"]["reviewer_error_rounds"]
                                       + per["rework"]["rejection_rounds"])
    first = per["reviews"][0]
    assert first["valid_answer"] is False and first["round_kind"] == "reviewer-error"
    # The seed is judged at the first VALID review that covered it.
    seed_a = next(s for s in per["quality"]["seeds"] if s["unit"] == "A")
    assert seed_a["seen_by"] == "QA_A#1" and seed_a["caught"] is True
    assert summary["modes"]["native-chain"]["per-task"]["reviewer_error_rounds"] == 1


def test_seed_removed_before_review_and_unowned_write_are_reported(tmp_path, monkeypatch):
    # B's author also restores A's file: in the grouped arm that removes A's seed before
    # R ever sees it, and it is a write to a file B does not own.
    _, summary, records = run_all(tmp_path, monkeypatch, "native-chain",
                                  also_write={"ledgerkit/lines.py": ["ledgerkit/money.py"]})
    arms = {r["arm"]: r for r in records}
    grouped, per = arms["grouped"], arms["per-task"]
    seed_a = next(s for s in grouped["quality"]["seeds"] if s["unit"] == "A")
    assert seed_a["status"] == "removed-before-review" and seed_a["caught"] is None
    assert seed_a["presence_check"]["by"] == "oracle"
    assert grouped["quality"]["seed_removed_before_review"] == 1
    assert grouped["quality"]["seeded_missed"] == 0
    assert {"unit": "B", "file": "ledgerkit/money.py"} in [
        {k: w[k] for k in ("unit", "file")} for w in grouped["writes"]["unowned"]
    ]
    # Per-task reviewed A before B ran; B's restore rewrote identical bytes: no write.
    assert next(s for s in per["quality"]["seeds"] if s["unit"] == "A")["caught"] is True
    assert per["writes"]["unowned"] == []
    seeds = summary["pairs"][0]["seeds"]
    assert seeds["compared_units"] == ["C"]
    assert seeds["excluded_removed_before_review"] == ["A"]
    assert seeds["grouped_missed_caught_by_per_task"] == []


def test_integration_recheck_calls_the_model_only_when_a_fast_check_is_red(
    tmp_path, monkeypatch
):
    original = lr.Arm.fast_check
    seen = []

    def red_once(self, base, root, label):
        if label.startswith("I2") and not seen:
            seen.append(label)
            return {"unit": base, "label": label, "passed": False, "output": "red", "ts": ""}
        return original(self, base, root, label)

    monkeypatch.setattr(lr.Arm, "fast_check", red_once)
    _, _, records = run_all(tmp_path, monkeypatch, "native-chain")
    grouped = next(r for r in records if r["arm"] == "grouped")
    assert grouped["status"] == "accepted", grouped["stop_reason"]
    i2 = next(u for u in grouped["units"] if u["id"] == "I2-R-r1")
    assert i2["i2_path"] == "model" and len(i2["calls"]) == 1
    assert [c["kind"] for c in grouped["calls"] if c["unit"] == "I2-R-r1"] == ["integration"]


def test_run_output_inside_the_repository_is_refused(tmp_path, monkeypatch):
    # A stand-in repository, so even a broken runner can never write into the real one.
    monkeypatch.setattr(lr, "ROOT", tmp_path / "repo")
    with pytest.raises(ValueError, match="inside the repository"):
        lr.run_live(tmp_path / "repo" / "out", [CASES["native-chain"]], repeats=1,
                    codex_bin=["false"])
    assert not (tmp_path / "repo" / "out").exists()


def test_access_audit_rules(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()

    def hits(command=None, path=None):
        item = ({"type": "command_execution", "command": command} if command is not None
                else {"type": "file_change", "changes": [{"path": path, "kind": "update"}]})
        return lr.audit_items([item], ws)

    assert hits("/bin/zsh -lc 'python checks/check_A.py'") == []
    assert hits(f"/bin/zsh -lc 'cat {ws}/ledgerkit/money.py'") == []
    assert hits("/bin/zsh -lc 'ls -la && cat x.py 2>/dev/null'") == []
    assert hits(f"cat {lr.ROOT}/README.md")
    assert hits("cat /tmp/elsewhere/file.py")
    assert hits("cd .. && ls")
    assert hits("cat ~/.codex/auth.json")
    assert hits("ls ~")
    assert hits("cat reference/ledgerkit/money.py")
    assert hits("grep -r x live_fixtures")
    assert hits(path=str(ws / "ledgerkit" / "money.py")) == []
    assert hits(path="ledgerkit/money.py") == []
    assert hits(path=str(tmp_path / "other.py"))


def test_access_audit_slash_is_a_path_only_when_a_name_follows(tmp_path):
    """QW round 2, finding 1: division, floor division, heredoc arithmetic and URLs are
    not paths; a bare `/` is the root only as a filesystem command's argument."""
    ws = tmp_path / "ws"
    ws.mkdir()

    def reasons(command):
        return [h["reason"] for h in
                lr.audit_items([{"type": "command_execution", "command": command}], ws)]

    negatives = [
        "/bin/zsh -lc 'python -c \"from decimal import Decimal; print(Decimal(7) * 3 / 100)\"'",
        "/bin/zsh -lc 'python -c \"print(250 // 100, 7 / 2)\"'",
        "/bin/zsh -lc \"python - <<'PY'\nfrom ledgerkit.lines import line_total\n"
        "print(250 // 100, 7 / 2)\nPY\"",
        "/bin/zsh -lc \"cat > ledgerkit/invoice.py <<'EOF'\ntax = subtotal * rate / 100\nEOF\"",
        "/bin/zsh -lc 'echo \"see https://docs.python.org/3/library/decimal.html\"'",
        "/bin/zsh -lc 'python -c \"print(1/2)\"'",
        "grep x /",  # not recursive: grep reads no directory
        "python -c 'print(~5)'",
        # QW round 3, H2: sed/awk pattern addresses and spaced division name no real path.
        "/bin/zsh -lc \"sed -n '/def merge/,/^$/p' stockplan/merge.py\"",
        "/bin/zsh -lc \"awk '/reorder/ {print NR}' stockplan/reorder.py\"",
        "/bin/zsh -lc \"sed -i '' '/import os/d' stockplan/merge.py\"",
        "/bin/zsh -lc \"cat > stockplan/x.py <<'EOF'\nper_unit = total /count\nEOF\"",
        "/bin/zsh -lc \"python -c 'print(7 /2)'\"",
    ]
    for command in negatives:
        assert reasons(command) == [], command
    positives = {
        "/bin/zsh -lc 'ls /'": "filesystem root",
        "find / -name '*.py'": "filesystem root",
        "grep -rn needle /": "filesystem root",
        "rg needle /": "filesystem root",
        "du -sh /*": "filesystem root",
        "tree '/'": "filesystem root",
        "cat /": "filesystem root",
        "cd / && ls": "filesystem root",
        "cat /tmp/x": "outside workspace: /tmp/x",
        "cat file:///tmp/x": "outside workspace: /tmp/x",
        "cat </tmp/x": "outside workspace: /tmp/x",
        "echo hi >/tmp/x": "outside workspace: /tmp/x",
    }
    for command, reason in positives.items():
        assert reasons(command) == [reason], command


def test_seed_claims_every_unit_file_once_its_mutant_loop_ran():
    """QW round 3, H1: a trial mutant seen at a concurrent author's boundary belongs to the
    seed, so a seed that kept nothing must not hand C's file to B as a false conflict."""
    files = ["stockplan/merge.py"]
    assert lr.seed_claims(True, files) == files
    assert lr.seed_claims(False, files) == []
    writers = {
        "b": {"kind": "call", "unit": "B", "window_ms": [0, 70],
              "owned": ["stockplan/reorder.py"], "event_paths": ["stockplan/reorder.py"]},
        "c": {"kind": "call", "unit": "C", "window_ms": [0, 50],
              "owned": ["stockplan/merge.py"], "event_paths": ["stockplan/merge.py"]},
        "seed-C-0": {"kind": "seed", "unit": "C", "window_ms": [50, 90],
                     "claims": lr.seed_claims(True, files)},
    }
    owned = {"stockplan/reorder.py", "stockplan/merge.py", "stockplan/contract.py"}
    spans = [
        span(0, 50, ["b", "c"], ["stockplan/merge.py"]),
        span(50, 70, ["b", "seed-C-0"], ["stockplan/merge.py", "stockplan/reorder.py"]),
        span(70, 90, ["seed-C-0"], ["stockplan/merge.py"]),
    ]
    result = lr.attribute_writes(spans, writers, owned)
    assert result["conflict_free"] is True
    assert result["unowned"] == []
    assert result["unattributed"] == []


def test_file_hashes_skips_a_file_that_vanishes_mid_listing(tmp_path, monkeypatch):
    """QW round 3, N1: a sibling's temp file deleted between listing and reading is skipped."""
    (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "gone.tmp").write_text("y\n", encoding="utf-8")
    real = Path.read_bytes

    def flaky(self):
        if self.name == "gone.tmp":
            raise FileNotFoundError(self)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", flaky)
    assert set(lr.file_hashes(tmp_path)) == {"keep.py"}


def span(t0, t1, active, changed):
    return {"window_ms": [t0, t1], "active": active, "changed": changed}


def test_write_attribution_from_boundary_hashes():
    """QW round 2, finding 3 (p_writes.py a, b, c). B runs 0-100, C runs 10-50, the
    harness seeds C's merge.py 50-70 while B still runs."""
    owned = {"stockplan/reorder.py", "stockplan/merge.py", "stockplan/plan.py"}
    writers = {
        "b": {"kind": "call", "unit": "B", "window_ms": [0, 100],
              "owned": ["stockplan/reorder.py"], "event_paths": []},
        "c": {"kind": "call", "unit": "C", "window_ms": [10, 50],
              "owned": ["stockplan/merge.py"], "event_paths": []},
        "seed": {"kind": "seed", "unit": "C", "window_ms": [50, 70],
                 "claims": ["stockplan/merge.py"]},
    }
    # (a) B shell-writes C's file after C finished (no file_change event): B's write,
    # and a conflict with the concurrently running owner.
    a = lr.attribute_writes(
        [span(10, 50, ["b", "c"], ["stockplan/merge.py", "stockplan/reorder.py"]),
         span(50, 70, ["b", "seed"], ["stockplan/merge.py"]),
         span(70, 100, ["b"], ["stockplan/merge.py"])],
        writers, owned,
    )
    rows = {r["unit"]: r for r in a["calls"]}
    assert rows["B"]["written"] == ["stockplan/merge.py", "stockplan/reorder.py"]
    assert rows["B"]["basis"]["stockplan/merge.py"] == "only-writer"
    assert {"call": "b", "unit": "B", "file": "stockplan/merge.py"} in a["unowned"]
    assert a["conflict_free"] is False
    assert a["conflicts"] == [{"calls": ["b", "c"], "files": ["stockplan/merge.py"]}]
    assert a["harness"] == [{"writer": "seed", "file": "stockplan/merge.py"}]
    # (b) a scratch file no unit owns, written while both ran: unattributed, and it does
    # not make the observation unknown.
    b = lr.attribute_writes(
        [span(10, 50, ["b", "c"],
              ["scratch_test.py", "stockplan/merge.py", "stockplan/reorder.py"])],
        writers, owned,
    )
    assert b["unattributed"] == [{"file": "scratch_test.py", "window_ms": [10, 50],
                                  "active": ["b", "c"], "owned_by_a_unit": False}]
    assert b["conflict_free"] is True and b["unowned"] == []
    # ...but an unattributable change to a file some unit owns is unknown, not clean.
    owned_b = lr.attribute_writes(
        [span(10, 50, ["b", "c"], ["stockplan/plan.py"])], writers, owned
    )
    assert owned_b["unattributed"][0]["owned_by_a_unit"] is True
    assert owned_b["conflict_free"] is None
    # (c) the seed window claims only the seeded file: B's own write during seeding is
    # B's, never swallowed by the harness; a seed that applied nothing claims nothing.
    c = lr.attribute_writes(
        [span(50, 70, ["b", "seed"], ["stockplan/merge.py", "stockplan/reorder.py"])],
        writers, owned,
    )
    assert {r["unit"]: r["written"] for r in c["calls"]}["B"] == ["stockplan/reorder.py"]
    assert c["conflict_free"] is True
    nothing = dict(writers, seed=dict(writers["seed"], claims=[]))
    c2 = lr.attribute_writes([span(50, 70, ["b", "seed"], ["stockplan/merge.py"])],
                             nothing, owned)
    assert {r["unit"]: r["written"] for r in c2["calls"]}["B"] == ["stockplan/merge.py"]
    assert c2["conflict_free"] is False
    # A file_change event decides inside a concurrent span; ownership decides otherwise.
    named = dict(writers, b=dict(writers["b"], event_paths=["stockplan/merge.py"]))
    d = lr.attribute_writes([span(10, 50, ["b", "c"], ["stockplan/merge.py"])], named, owned)
    assert {r["unit"]: r["written"] for r in d["calls"]} == {"B": ["stockplan/merge.py"],
                                                             "C": []}
    assert d["conflict_free"] is False
    e = lr.attribute_writes([span(10, 50, ["b", "c"], ["stockplan/merge.py"])], writers, owned)
    assert {r["unit"]: r["basis"] for r in e["calls"]}["C"] == {"stockplan/merge.py": "owner"}
    assert e["conflict_free"] is True
    # A change while no writer ran is unattributed.
    f = lr.attribute_writes([span(100, 120, [], ["stockplan/reorder.py"])], writers, owned)
    assert f["conflict_free"] is None and f["unattributed"][0]["active"] == []


# The three real usages of the 2026-11-13 resume probe (Codex CLI 0.167.1, one session,
# fresh then resumed twice, each turn replying "OK").
PROBE = [
    {"input_tokens": 19499, "cached_input_tokens": 12288, "cache_write_input_tokens": 0,
     "output_tokens": 5, "reasoning_output_tokens": 0},
    {"input_tokens": 39023, "cached_input_tokens": 24576, "cache_write_input_tokens": 0,
     "output_tokens": 10, "reasoning_output_tokens": 0},
    {"input_tokens": 58572, "cached_input_tokens": 43904, "cache_write_input_tokens": 0,
     "output_tokens": 15, "reasoning_output_tokens": 0},
]


def probe_arm(rows_per_call):
    """Run Arm.account over hand-made calls on one thread, as Arm.model would."""
    arm = lr.Arm.__new__(lr.Arm)
    arm.thread_totals, arm.usage_unknown = {}, []
    calls, resume = [], None
    for n, rows in enumerate(rows_per_call):
        raw = "\n".join(json.dumps({"type": "turn.completed", "usage": u}) for u in rows)
        call = {"id": f"c{n}", "usage": lr.parse_usage(raw), "turn_usages": lr.turn_usages(raw),
                "thread_id": "t"}
        arm.account(call, f"U{n}", resume)
        calls.append(call)
        resume = "t"
    return arm, calls


def test_probe_running_totals_become_per_call_usage():
    _, calls = probe_arm([[u] for u in PROBE])
    inputs = [c["usage"]["uncached_input"] + c["usage"]["cache_read"] for c in calls]
    assert inputs == [19499, 19524, 19549]
    assert [c["usage"]["output"] for c in calls] == [5, 5, 5]
    assert [c["usage"]["cache_read"] for c in calls] == [12288, 12288, 19328]
    assert [c["usage_raw"]["input_tokens"] for c in calls] == [19499, 19524, 19549]
    # Raw totals kept beside the per-call figures; cache writes and reasoning recorded raw.
    assert [c["reported_cumulative"] for c in calls] == PROBE
    for c in calls:
        assert c["usage_raw"]["cache_write_input_tokens"] == 0
        assert c["usage_raw"]["reasoning_output_tokens"] == 0
        assert not lr.cache_writes(c)
    # The clock-out line uses the per-call figures, not the running total.
    line = lr.clock_accounting(calls[2]["usage"], 1, "n")
    assert line["tokens"] == 58572 - 43904 - (39023 - 24576) + 5


def test_resumed_call_without_an_earlier_total_is_unknown_never_zero():
    arm = lr.Arm.__new__(lr.Arm)
    arm.thread_totals, arm.usage_unknown = {}, []
    raw = json.dumps({"type": "turn.completed", "usage": PROBE[1]})
    call = {"id": "c1", "usage": lr.parse_usage(raw), "turn_usages": lr.turn_usages(raw),
            "thread_id": "t"}
    arm.account(call, "B", "t")
    assert call["usage"] is None and call["usage_raw"] is None
    assert call["reported_cumulative"] == PROBE[1]
    assert arm.usage_unknown == [{"call": "c1", "unit": "B", "reason":
                                  "resumed call with no earlier reported total on its thread"}]
    assert lr.sum_usage([usage_of(1, 0), call["usage"]]) is None
    assert lr.clock_accounting(call["usage"], 1, "n")["estimate"] is True


def test_negative_delta_is_unknown_and_poisons_the_next_baseline():
    # A per-turn report after a running total: input falls, so not cumulative.
    _, calls = probe_arm([[PROBE[1]], [PROBE[0]], [PROBE[2]]])
    assert calls[0]["usage"] is not None
    assert calls[1]["usage"] is None and calls[2]["usage"] is None
    assert calls[1]["usage_unknown_reason"] == (
        "cached_input_tokens fell from 24576 to 12288: not a cumulative total")
    assert calls[2]["usage_unknown_reason"] == (
        "resumed call with no earlier reported total on its thread")
    # Output falling alone is enough (a true running total never shrinks).
    shrunk = dict(PROBE[1], output_tokens=4)
    assert lr.call_delta(shrunk, PROBE[0]) == (
        None, "output_tokens fell from 5 to 4: not a cumulative total")
    # A field with no baseline has an unknown delta; the usage stays known.
    delta, why = lr.call_delta(dict(PROBE[1], extra_tokens=3), PROBE[0])
    assert why is None and delta["extra_tokens"] is None and delta["output_tokens"] == 5


def test_fresh_calls_are_their_own_report():
    for rows in ([FRESH], [FRESH, RESUMED]):
        _, calls = probe_arm([rows])
        assert calls[0]["usage"] == usage_of(1, len(rows) - 1)
        assert calls[0]["reported_cumulative"] == rows[-1]


def test_nonzero_cache_write_is_flagged_in_the_summary():
    _, calls = probe_arm([[PROBE[0]], [dict(PROBE[1], cache_write_input_tokens=64)]])
    assert [lr.cache_writes(c) for c in calls] == [False, True]
    assert calls[1]["usage_raw"]["cache_write_input_tokens"] == 64
    records = good_run()
    assert lr.summarize_live(records)["cache_write"] == {"nonzero": False, "jobs": []}
    records[0]["cache_write"] = {"label": "x", "calls": ["c1"]}
    flagged = lr.summarize_live(records)["cache_write"]
    assert flagged == {"nonzero": True, "jobs": [f"{records[0]['job_id']}/c1"]}


def test_smoke_projection_needs_both_arms_uncensored():
    """QW round 2, finding 2."""
    base = {"smoke": True, "case_id": "mixed-fork-join", "repeat": 0, "attempt": 0,
            "job_id": "s", "accepted": False, "total_tokens": 60000, "review_tokens": 0}
    censored = dict(base, arm="per-task", status="failed/censored", stop_kind="harness")
    one = lr.summarize_live([censored])["smoke"]
    assert one["harness_censored"] == 1
    assert one["projected_tokens_for_18_jobs"] is None and one["exceeds_gate"] is None
    clean = dict(base, arm="per-task", status="accepted", accepted=True, stop_kind=None)
    alone = lr.summarize_live([clean])["smoke"]
    assert alone["projected_tokens_for_18_jobs"] is None and alone["exceeds_gate"] is None
    both = lr.summarize_live([clean, dict(clean, arm="grouped", job_id="g")])["smoke"]
    assert both["projected_tokens_for_18_jobs"] == 60000 * 18
    assert both["exceeds_gate"] is False
    half = lr.summarize_live([clean, dict(censored, arm="grouped")])["smoke"]
    assert half["projected_tokens_for_18_jobs"] is None and half["exceeds_gate"] is None


def test_censored_pair_is_left_out_of_every_check():
    """QW round 2, finding 4: a censored pair's arms count in no check, and with clean
    pairs all passing the verdict is inconclusive, not pass and not fail."""
    records = good_run()
    for r in records:
        if (r["case_id"], r["repeat"]) == ("native-chain", 0):
            if r["arm"] == "per-task":
                # Would fail approval/coverage and the latency median if it still counted.
                r["observations"]["holds"] = False
                r["elapsed_to_accepted_ms"] = 1.0
            else:
                r.update(stop_kind="harness", accepted=False)
    verdict = lr.summarize_live(records)["modes"]["native-chain"]["verdict"]
    assert verdict["checks"]["approval_coverage_holds"] is True
    assert verdict["checks"]["median_accepted_latency_not_increase"] is True
    assert verdict["result"] == "inconclusive"
    assert verdict["harness_censored_pairs"] == ["native-chain#r0"]


def test_final_failures_are_attributed_by_the_unit_isolated_oracle(tmp_path):
    """QW round 2, finding 7: a downstream criterion failing only because an upstream seed
    survived is not an author defect of the downstream unit."""
    case = CASES["native-chain"]
    ws = lr.live_cases.make_workspace(case, tmp_path / "w", reference=True)
    seed_a = lr.live_cases.seed_defect(case, "A", ws)
    assert seed_a["applied"]
    final = lr.live_cases.run_hidden_oracle(case, ws)
    failing = sorted(c for c, ok in final["results"].items() if not ok)
    units = lr._units(case)
    split = lr.classify_failures(units, failing, [seed_a], case, ws)
    assert split["seeded_still_failing"] == sorted(seed_a["failing"])
    assert split["caused_by_other_units"]  # downstream of the surviving seed
    assert split["author_defects_missed"] == [] and split["unknown"] == []
    assert sorted(split["seeded_still_failing"] + split["caused_by_other_units"]) == failing
    # Without the seed record, A's own failure is an author defect; others stay upstream.
    unseeded = lr.classify_failures(units, failing, [], case, ws)
    assert unseeded["author_defects_missed"] == sorted(seed_a["failing"])
    assert unseeded["caused_by_other_units"] == split["caused_by_other_units"]


def test_harness_time_only_leaves_latency_when_no_model_call_ran():
    assert lr.only_in([[0, 10]], [[5, 20]]) == 5
    assert lr.only_in([[0, 10], [30, 40]], [], limit=35) == 15
    assert lr.only_in([[0, 10]], [[0, 10]]) == 0


def test_protocol_stop_fails_the_mode_even_beside_a_censored_pair():
    protocol = good_run(**{"native-chain": {"accepted": False}})
    assert lr.summarize_live(protocol)["modes"]["native-chain"]["verdict"]["result"] == "fail"
    harness = good_run(**{"native-chain": {"accepted": False}})
    for r in harness:
        if r["case_id"] == "native-chain" and r["arm"] == "grouped" and r["repeat"] == 0:
            r["stop_kind"] = "harness"
    verdict = lr.summarize_live(harness)["modes"]["native-chain"]["verdict"]
    assert verdict["checks"]["approval_coverage_holds"] is False  # repeats 1, 2: protocol
    # Design, *Harness censors and the rerun rule*: a check false on the clean pairs fails
    # the mode; a still-censored pair cannot rescue it.
    assert verdict["result"] == "fail"
    assert verdict["harness_censored_pairs"] == ["native-chain#r0"]
    only_harness = good_run()
    for r in only_harness:
        if r["case_id"] == "native-chain" and r["arm"] == "grouped" and r["repeat"] == 0:
            r.update(stop_kind="harness", accepted=False)
    verdict = lr.summarize_live(only_harness)["modes"]["native-chain"]["verdict"]
    # Every check holds on the clean pairs; the censored pair keeps it from a pass.
    assert verdict["checks"]["approval_coverage_holds"] is True
    assert verdict["result"] == "inconclusive"
    # A voided attempt is kept apart, with its spend.
    voided = dict(record("native-chain", "per-task", 0, total=77), attempt=0,
                  stop_kind="harness", accepted=False)
    rerun = [dict(r, attempt=1) if (r["case_id"], r["repeat"]) == ("native-chain", 0) else r
             for r in good_run()]
    summary = lr.summarize_live([voided, *rerun])
    assert summary["voided_attempts"]["total_tokens"] == 77
    assert summary["modes"]["native-chain"]["verdict"]["result"] == "pass"


def test_rejection_findings_merge_per_finding_and_no_prompt_names_the_harness(
    tmp_path, monkeypatch
):
    """QW round 2, findings 6 and 10. At R's first review A (seeded, so the model flags
    it) and B (clean) fail their fast checks with output naming the snapshot root."""
    original = lr.live_cases.run_fast_check
    seen = set()

    def red_at_first_r(case, unit_id, root):
        root = Path(root)
        if root.name == "R-0" and unit_id in ("A", "B") and unit_id not in seen:
            seen.add(unit_id)
            return {"passed": False, "output": (
                f'Traceback:\n  File "{root}/ledgerkit/money.py", line 3\nAssertionError')}
        return original(case, unit_id, root)

    monkeypatch.setattr(lr.live_cases, "run_fast_check", red_at_first_r)
    out, _, records = run_all(tmp_path, monkeypatch, "native-chain")
    grouped = next(r for r in records if r["arm"] == "grouped")
    assert grouped["status"] == "accepted", grouped["stop_reason"]
    first = grouped["reviews"][0]
    # The model flagged the seeded A and C; both red fast checks join them, A's included.
    assert {f["unit"] for f in first["findings"]} == {"A", "C"}
    assert {(f["unit"], f.get("source")) for f in first["repair_findings"]} == {
        ("A", None), ("C", None), ("A", "harness"), ("B", "harness")
    }
    assert first["round_kind"] == "rejection"
    assert "B2-r1" in grouped["rework"]["units"]
    briefs = out / Path(grouped["checkpoint"]).parent / "briefs"
    repair_a = (briefs / "A2-r1.md").read_text(encoding="utf-8")
    assert "Fast check failed" in repair_a and 'File \\"./ledgerkit/money.py\\"' in repair_a
    # No prompt names an arm, a job id, the run's calls/ or snapshots/, or any harness path.
    prompts = {p.parent.name: p.read_text(encoding="utf-8")
               for p in (out / "calls").glob("*/prompt.txt")}
    assert len(prompts) == sum(len(r["calls"]) for r in records)
    sent = [t for t in prompts.values() if "Fast check failed" in t]
    assert sent  # the scrubbed output did reach a prompt
    for name, text in prompts.items():
        for word in ("arms/", "calls/", "snapshots/", "per-task", "grouped", "<harness>",
                     str(out), str(lr.ROOT)):
            assert word not in text, (name, word)
        for record in records:
            assert record["job_id"] not in text, (name, record["job_id"])


def test_limits_name_the_round_two_gaps():
    """QW round 2, finding 9: the four limits are published with every summary."""
    limits = "\n".join(lr.summarize_live(good_run())["limitations"])
    for phrase in ("reads command text only", "silently fix its own earlier seed",
                   "is judged false", "A2 and C2 can run concurrently"):
        assert phrase in limits, phrase


def test_isolated_codex_home_links_auth_and_restores_everything(tmp_path, monkeypatch):
    """User ruling 2026-11-13: Codex runs under a temp CODEX_HOME holding only a symlink to
    the real auth file, so personal skills and app connectors never load; nothing is
    copied, the environment is restored, and the auth link never reaches the run output."""
    auth = tmp_path / "real-home" / "auth.json"
    auth.parent.mkdir()
    auth.write_text('{"token": "secret"}', encoding="utf-8")
    (auth.parent / "skills" / "personal").mkdir(parents=True)
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("CODEX_HOME", "/previous/home")
    with lr.isolated_codex_home(auth, out) as home:
        assert os.environ["CODEX_HOME"] == str(home)
        link = home / "auth.json"
        assert link.is_symlink() and link.resolve() == auth.resolve()
        assert not (home / "skills" / "personal").exists()
        assert sorted(p.name for p in home.iterdir()) == ["auth.json"]
        (home / "sessions" / "2026").mkdir(parents=True)
        (home / "sessions" / "2026" / "rollout.jsonl").write_text("{}\n", encoding="utf-8")
    assert os.environ["CODEX_HOME"] == "/previous/home"
    assert not home.exists()
    assert auth.read_text(encoding="utf-8") == '{"token": "secret"}'
    kept = out / "codex-sessions"
    assert (kept / "2026" / "rollout.jsonl").is_file()
    assert not any(p.name == "auth.json" for p in out.rglob("*"))


def test_isolated_codex_home_refuses_a_missing_auth_file(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    with pytest.raises(ValueError, match="auth"):
        with lr.isolated_codex_home(tmp_path / "nope" / "auth.json", tmp_path):
            pass
    assert "CODEX_HOME" not in os.environ


def test_run_live_isolates_home_only_for_codex_processes(tmp_path, monkeypatch):
    """~/.agents/skills is found through HOME, so Codex processes (and only they) start with
    HOME and CODEX_HOME set to the isolated home; the run still completes end to end."""
    auth = tmp_path / "real" / "auth.json"
    auth.parent.mkdir()
    auth.write_text("{}", encoding="utf-8")
    codex, _ = fake_codex(tmp_path, monkeypatch, "mixed-fork-join")
    real_home = os.environ.get("HOME")
    out = tmp_path / "out"
    summary = lr.run_live(out, [CASES["mixed-fork-join"]], repeats=1, smoke=True,
                          codex_bin=codex, codex_auth=auth)
    meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    argv = meta["codex_command"]
    assert argv[0] == "/usr/bin/env"
    home = argv[1].removeprefix("HOME=")
    assert argv[1].startswith("HOME=") and argv[2] == f"CODEX_HOME={home}"
    assert argv[3:] == codex
    assert not Path(home).exists()
    assert os.environ.get("HOME") == real_home
    assert meta["codex_environment"]["codex_home_isolated"]["isolated"] is True
    assert summary["smoke"]["harness_censored"] == 0


# --- #310 tuning (job84 TW): the default stays byte-for-byte, tuned levers behind flags ---

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def sent_calls(out, tmp_path, codex):
    """Every call's argv and prompt as sent, keyed (job, unit, nth call of that unit) and
    normalized: run paths, temp dirs, reviewer context ids and thread ids are masked."""
    import re

    rows = {}
    seen = {}
    for record in lr.read_runs(out):
        for call in record["calls"]:
            key = (record["job_id"], call["unit"])
            n = seen[key] = seen.get(key, -1) + 1
            d = out / call["artifact_dir"]
            text = (d / "prompt.txt").read_text(encoding="utf-8") + "\n--argv--\n" + (
                d / "argv.json").read_text(encoding="utf-8")
            for path in sorted({str(p) for p in (out, out.resolve(), tmp_path,
                                                  tmp_path.resolve())}, key=len, reverse=True):
                text = text.replace(path, "<tmp>")
            text = text.replace(json.dumps(codex[0])[1:-1], "<python>")
            text = re.sub(r"/[^\s\"']*glr-[A-Za-z0-9_]+", "<scratch>", text)
            text = re.sub(r"reviewer-[0-9a-f]{32}", "reviewer-<id>", text)
            text = re.sub(UUID, "<thread>", text)
            rows[f"{key[0]}|{key[1]}|{n}"] = text
    return rows


def golden_digest(tmp_path, monkeypatch, case_id):
    import hashlib

    codex, _ = fake_codex(tmp_path, monkeypatch, case_id)
    out = tmp_path / "out"
    lr.run_live(out, [CASES[case_id]], repeats=1, codex_bin=codex)
    rows = sent_calls(out, tmp_path, codex)
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(), rows


# Captured from the #310 harness as committed (1f9c1f5f) before any tuning code existed:
# every call's argv and prompt of a default run, normalized (see sent_calls).
GOLDEN_310 = {
    "mixed-fork-join": ("58f9e0747cd61e9318d4de346ac4dd3f40b0ed1ec419e9a1f2519a9165179331", 22),
    "native-chain": ("0c33362b1d33389551397c5200438de73f8c98008b19aee743c2357c9b328e21", 17),
    "sequential-delegates": (
        "2386b5b2462fa8467f58e57d92e5704b0871af481124778f6cfdc3eb16c2670d", 17),
}
GOLDEN_PLANS = "db3498a3f3c217da8471506e183407161b79c72217f560f990e512ee4919d246"
GOLDEN_PROMPTS = "b913365e11729c6f4d62b8a2e2836c2e9999e06c647004e945afd546f45accc9"


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_default_310_argv_and_prompts_are_byte_for_byte_as_before(tmp_path, monkeypatch,
                                                                   case_id):
    import hashlib

    digest, rows = golden_digest(tmp_path, monkeypatch, case_id)
    assert (digest, len(rows)) == GOLDEN_310[case_id]
    assert all("--output-schema" in t for k, t in rows.items() if "|QA_" in k or "|R|" in k)
    plans = {c["id"]: {a: lr.arm_tickets(c, a) for a in lr.ARMS} for c in CASES.values()}
    assert hashlib.sha256(json.dumps(plans, sort_keys=True).encode()).hexdigest() == GOLDEN_PLANS
    assert hashlib.sha256(json.dumps(lr.PROMPTS, sort_keys=True).encode()).hexdigest() == (
        GOLDEN_PROMPTS)
    for record in lr.read_runs(tmp_path / "out"):
        assert record["variant"] == record["arm"] and record["levers"] == []


def run_tuning(tmp_path, monkeypatch, case_id, smoke=False, budget=10**12, **scenario):
    codex, log = fake_codex(tmp_path, monkeypatch, case_id, **scenario)
    out = tmp_path / "out"
    summary = lr.run_live(out, [CASES[case_id]], repeats=1, smoke=smoke, codex_bin=codex,
                          comparison="tuning", budget_tokens=budget)
    records = lr.read_runs(out) if (out / "runs.jsonl").exists() else []
    calls = [json.loads(s) for s in log.read_text().splitlines()] if log.exists() else []
    return out, summary, records, calls


def sent(out, call, name):
    text = (out / call["artifact_dir"] / name).read_text(encoding="utf-8")
    return json.loads(text) if name.endswith(".json") else text


def test_baseline_grouped_sends_exactly_the_310_grouped_calls(tmp_path, monkeypatch):
    """baseline-grouped is the #310 grouped arm: same argv, same prompts, call for call."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    codex_a, _ = fake_codex(a, monkeypatch, "native-chain")
    lr.run_live(a / "out", [CASES["native-chain"]], repeats=1, codex_bin=codex_a)
    rows_310 = sent_calls(a / "out", a, codex_a)
    codex_b, _ = fake_codex(b, monkeypatch, "native-chain")
    lr.run_live(b / "out", [CASES["native-chain"]], repeats=1, codex_bin=codex_b,
                comparison="tuning", budget_tokens=10**12)
    rows_tuning = sent_calls(b / "out", b, codex_b)

    def arm(rows, job):
        return {k.split("|", 1)[1]: v for k, v in rows.items() if k.split("|")[0] == job}

    grouped = arm(rows_310, "native-chain-r0-grouped")
    assert grouped and grouped == arm(rows_tuning, "native-chain-r0-baseline-grouped")
    assert arm(rows_tuning, "native-chain-r0-tuned-grouped") != grouped


def test_tuned_arm_runs_t1_to_t4_and_baseline_none(tmp_path, monkeypatch):
    out, summary, records, log = run_tuning(tmp_path, monkeypatch, "native-chain")
    # Counterbalanced: repeat 0 runs baseline first.
    assert [r["variant"] for r in records] == ["baseline-grouped", "tuned-grouped"]
    base, tuned = records
    assert base["levers"] == [] and tuned["levers"] == ["T1", "T2", "T3", "T4"]
    assert {r["arm"] for r in records} == {"grouped"}
    for record in records:
        assert record["status"] == "accepted", record["stop_reason"]
        assert record["quality"]["quality_failure"] is False
        assert record["observations"]["holds"] is True
        assert [s["caught"] for s in record["quality"]["seeds"]] == [True, True]
        assert record["writes"]["unowned"] == [] and record["writes"]["conflict_free"] is True
        # Every call clocked in before and out after, as today.
        lines = ledger(out, record)
        briefs = [x for x in lines if x.get("event") == "brief"]
        outs = [x for x in lines if "event" not in x]
        deterministic = [u for u in record["units"] if u.get("i2_path") == "deterministic"]
        assert len(briefs) == len(outs) == len(record["calls"]) + len(deterministic)
        for call in record["calls"]:
            assert call["tokens_excl_cache"] == (call["usage"]["uncached_input"]
                                                 + call["usage"]["output"])
            assert call["tokens"] == call["tokens_excl_cache"] + call["usage"]["cache_read"]

    def calls(record, kind):
        return [c for c in record["calls"] if c["kind"] == kind]

    # T1: the tuned reviewer has no --output-schema, tools still disabled, shape in prompt.
    for call in calls(tuned, "reviewer"):
        argv = sent(out, call, "argv.json")
        assert "--output-schema" not in argv
        assert {"shell_tool", "unified_exec", "apps", "multi_agent"} <= set(argv)
        assert 'model_reasoning_effort="medium"' in argv
        prompt = sent(out, call, "prompt.txt")
        assert prompt.startswith(lr.TUNED_REVIEW_PROMPT)
        assert prompt.index('"evidence": [{"unit"') < prompt.index("REVIEW REQUEST:")
    for call in calls(base, "reviewer"):
        assert "--output-schema" in sent(out, call, "argv.json")
        assert sent(out, call, "prompt.txt").startswith(lr.REVIEW_PROMPT + "{")
    assert sum(c["review"] and "--output-schema" not in c["argv"] for c in log) == 2
    # T2 + T4: each tuned repair is one fresh tools-disabled patch call at low effort.
    repairs = calls(tuned, "repair")
    assert [c["unit"] for c in repairs] == ["A2-r1", "C2-r1"]
    for call in repairs:
        argv = sent(out, call, "argv.json")
        assert call["repair_mode"] == "patch" and call["context"] == "patch"
        assert call["resumed"] is False and "resume" not in argv
        assert 'model_reasoning_effort="low"' in argv and "shell_tool" in argv
        assert "read-only" in argv and "--output-schema" not in argv
        prompt = sent(out, call, "prompt.txt")
        assert prompt.startswith(lr.PATCH_PROMPT)
        assert "Reviewer findings (verbatim)" in prompt
        assert "OWNED FILES (current text):" in prompt
    for record in records:
        for call in calls(record, "author") + calls(record, "reviewer"):
            assert 'model_reasoning_effort="medium"' in sent(out, call, "argv.json")
    for call in calls(base, "repair"):
        argv = sent(out, call, "argv.json")
        assert 'model_reasoning_effort="medium"' in argv and "repair_mode" not in call
    # The patch write is the repair unit's own write, from the boundary hashes.
    rows = {r["unit"]: r for r in tuned["writes"]["calls"]}
    assert rows["A2-r1"]["written"] == ["ledgerkit/money.py"]
    assert rows["C2-r1"]["written"] == CASES["native-chain"]["units"][2]["files"]
    assert {u["id"]: u.get("repair_path") for u in tuned["units"]}["A2-r1"] == "patch"
    # T3: the tuned re-review carries the previous findings and per-member change flags.
    first, second = [sent(out, c, "request.json") for c in calls(tuned, "reviewer")]
    assert "previous_findings" not in first
    assert all("changed_since_last_review" not in u for u in first["units"])
    assert second["previous_findings"] == tuned["reviews"][0]["repair_findings"]
    assert {u["id"]: u["changed_since_last_review"] for u in second["units"]} == {
        "A": True, "B": False, "C": True}
    assert second["instructions"].endswith(lr.DELTA_INSTRUCTIONS)
    assert tuned["reviews"][1]["delta"] is True
    assert tuned["reviews"][1]["changed_members"] == ["A", "C"]
    for call in calls(base, "reviewer"):
        request = sent(out, call, "request.json")
        assert "previous_findings" not in request
        assert request["instructions"] == lr.REVIEW_INSTRUCTIONS
    assert tuned["tuning"]["patch_calls"] == 2 and tuned["tuning"]["fallbacks"] == 0
    assert tuned["tuning"]["delta_reviews"] == 1
    assert base["tuning"]["patch_calls"] == base["tuning"]["delta_reviews"] == 0
    # The metric per kind and per arm.
    patch = tuned["tuning"]["repair_modes"]["patch"]
    assert tuned["kind_tokens_excl_cache"]["repair"] == patch["uncached_input"] + patch["output"]
    assert summary["comparison"] == "tuning"
    assert summary["modes"]["native-chain"]["tuned-grouped"]["patch_calls"] == 2
    meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert meta["comparison"] == "tuning"
    assert meta["variants"]["tuned-grouped"]["levers"] == ["T1", "T2", "T3", "T4"]
    written = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert written.pop("budget")["cap"] == 10**12  # only the run's own summary has it
    assert written == json.loads(json.dumps(lr.summarize_tuning(records, 10**12)))


@pytest.mark.parametrize(
    ("mode", "reason", "counter"),
    [
        ("foreign", "invalid patch answer: patch names a file the unit does not own: "
                    "ledgerkit/lines.py", "patch_invalid_answers"),
        ("garbage", "invalid patch answer: patch answer is not JSON", "patch_invalid_answers"),
        ("red", "fast check red after the patch", "patch_red_checks"),
    ],
)
def test_patch_repair_falls_back_exactly_once(tmp_path, monkeypatch, mode, reason, counter):
    out, _, records, _ = run_tuning(tmp_path, monkeypatch, "native-chain", patch=[mode],
                                    foreign_path="ledgerkit/lines.py")
    tuned = next(r for r in records if r["variant"] == "tuned-grouped")
    assert tuned["status"] == "accepted", tuned["stop_reason"]
    a2 = [c for c in tuned["calls"] if c["unit"] == "A2-r1"]
    assert [c["repair_mode"] for c in a2] == ["patch", "fallback-shell"]
    assert a2[0]["fallback_reason"] == reason == a2[1]["fallback_reason"]
    # The fallback is today's shell path (native chain: the parent session), at low effort.
    fallback = sent(out, a2[1], "argv.json")
    assert a2[1]["context"] == "parent" and fallback[fallback.index("exec") + 1] == "resume"
    assert 'model_reasoning_effort="low"' in fallback and "shell_tool" not in fallback
    assert sent(out, a2[1], "prompt.txt").startswith(lr.REPAIR_PROMPT)
    assert [c["repair_mode"] for c in tuned["calls"] if c["unit"] == "C2-r1"] == ["patch"]
    unit = next(u for u in tuned["units"] if u["id"] == "A2-r1")
    assert unit["repair_path"] == "fallback-shell" and unit["fallback_reason"] == reason
    counts = tuned["tuning"]
    assert counts[counter] == 1 and counts["fallbacks"] == 1 and counts["patch_calls"] == 2
    # Each call has its own brief and clock-out; the patch call hands the unit back open.
    lines = [x for x in ledger(out, tuned) if x.get("unit") == "A2-r1"]
    assert sum(x.get("event") == "brief" for x in lines) == 2
    assert sum("event" not in x for x in lines) == 2
    doc = units_of(checkpoint(out, tuned))
    assert doc["A2-r1"]["status"] == "done"
    patch_row = next(r for r in tuned["writes"]["calls"] if r["call"] == a2[0]["id"])
    if mode == "red":
        # Written, then red, then repaired by the fallback.
        assert patch_row["written"] == ["ledgerkit/money.py"]
        assert [c["passed"] for c in tuned["fast_checks"]["A"] if c["label"] == "A2-r1"] == [
            False, True]
    else:
        # A rejected answer writes nothing at all, the foreign path least of all.
        assert patch_row["written"] == [] and patch_row["changed"] == []
    assert tuned["writes"]["unowned"] == []
    lines_py = out / tuned["workspace"] / "ledgerkit" / "lines.py"
    assert lines_py.read_text(encoding="utf-8") != "# overwritten\n"


def test_parse_patch_rules():
    def raw(text, tool=False):
        rows = [{"type": "item.completed", "item": {"type": "agent_message", "text": text}}]
        if tool:
            rows.insert(0, {"type": "item.completed",
                            "item": {"type": "command_execution", "command": "ls"}})
        return "\n".join(json.dumps(r) for r in rows)

    owned = ["a.py", "b.py"]
    good = {"files": [{"path": "a.py", "content": "x = 1\n"}]}
    assert lr.parse_patch(raw(json.dumps(good)), owned) == (good["files"], None)
    bad = {
        "not json": "patch answer is not JSON",
        json.dumps({"files": []}): "patch answer has no files list",
        json.dumps([good]): "patch answer has no files list",
        json.dumps({"files": [{"path": "a.py"}]}): "patch file row is not {path, content}",
        json.dumps({"files": [{"path": "a.py", "content": 1}]}):
            "patch file row is not {path, content}",
        json.dumps({"files": [dict(good["files"][0], extra=1)]}):
            "patch file row is not {path, content}",
        json.dumps({"files": good["files"] + [{"path": "../c.py", "content": ""}]}):
            "patch names a file the unit does not own: ../c.py",
        json.dumps({"files": good["files"] * 2}): "patch names a.py twice",
    }
    for text, reason in bad.items():
        assert lr.parse_patch(raw(text), owned) == (None, reason), text
    assert lr.parse_patch(raw(json.dumps(good), tool=True), owned) == (
        None, "patch call used a tool")
    assert lr.parse_patch("", owned) == (None, "no patch answer")


def test_tuned_invalid_reviewer_answer_is_a_counted_reviewer_error_round(tmp_path, monkeypatch):
    _, _, records, _ = run_tuning(tmp_path, monkeypatch, "native-chain",
                                  garbage_tuned_reviews=1)
    base, tuned = records
    assert tuned["status"] == "accepted", tuned["stop_reason"]
    assert tuned["reviews"][0]["valid_answer"] is False
    assert tuned["reviews"][0]["round_kind"] == "reviewer-error"
    assert tuned["tuning"]["reviewer_invalid_answers"] == 1
    assert tuned["rework"]["reviewer_error_rounds"] == 1
    assert base["tuning"]["reviewer_invalid_answers"] == 0
    # No delta after an error round: the next review of that group is a full one.
    assert tuned["tuning"]["delta_skipped_after_error"] == 1
    assert not tuned["reviews"][1].get("delta")


def test_patch_target_refuses_symlinks_and_paths_outside_the_workspace(tmp_path):
    from types import SimpleNamespace
    ws = tmp_path / "ws"
    (ws / "pkg").mkdir(parents=True)
    (ws / "pkg" / "ok.py").write_text("x = 1\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    (ws / "pkg" / "link.py").symlink_to(outside)
    (ws / "linkdir").symlink_to(tmp_path)
    # A link that stays inside the workspace still names another file than the owned path.
    (ws / "pkg" / "other.py").write_text("y = 2\n")
    (ws / "pkg" / "alias.py").symlink_to(ws / "pkg" / "other.py")
    arm = SimpleNamespace(workspace=ws)
    assert lr.Arm.patch_target(arm, "pkg/ok.py") == ws / "pkg" / "ok.py"
    assert lr.Arm.patch_target(arm, "pkg/new.py") == ws / "pkg" / "new.py"
    assert lr.Arm.patch_target(arm, "pkg/link.py") is None
    assert lr.Arm.patch_target(arm, "linkdir/outside.txt") is None
    assert lr.Arm.patch_target(arm, "../outside.txt") is None
    assert lr.Arm.patch_target(arm, "pkg/alias.py") is None
    assert outside.read_text() == "secret\n"


def test_a_full_tuning_run_refuses_to_start_without_a_budget(tmp_path):
    with pytest.raises(ValueError, match="needs budget_tokens"):
        lr.run_live(tmp_path / "out", [CASES["native-chain"]], comparison="tuning")
    assert not (tmp_path / "out").exists()


def test_tuning_smoke_is_the_fork_join_pair_with_a_twelve_job_projection(tmp_path, monkeypatch):
    out, summary, records, _ = run_tuning(tmp_path, monkeypatch, "mixed-fork-join", smoke=True,
                                          budget=None)
    assert [(r["variant"], r["repeat"], r["smoke"]) for r in records] == [
        ("baseline-grouped", 0, True), ("tuned-grouped", 0, True)]
    for record in records:
        assert record["status"] == "accepted", record["stop_reason"]
        assert record["observations"]["holds"] is True
    tuned = records[1]
    # The contract gate QA_K stays in both arms; the tuned repairs are patch calls.
    assert any(r["unit"] == "QA_K" for r in tuned["reviews"])
    assert all(c["repair_mode"] == "patch" for c in tuned["calls"] if c["kind"] == "repair")
    smoke = summary["smoke"]
    raw = sum(r["total_tokens"] for r in records)
    assert summary["run_count"] == 0 and summary["pairs"] == []
    assert smoke["projected_tokens_for_12_jobs"] == max(r["total_tokens"] for r in records) * 12
    assert smoke["mean_projected_tokens_for_12_jobs"] == raw / 2 * 12
    # Unequal jobs: the projection takes the larger one, never the mean.
    uneven = [dict(records[0], total_tokens=100), dict(records[1], total_tokens=300)]
    again = lr.summarize_tuning(uneven, 3000)["smoke"]
    assert again["projected_tokens_for_12_jobs"] == 3600 and again["fits_budget"] is False
    assert again["mean_projected_tokens_for_12_jobs"] == 2400
    assert smoke["fits_budget"] is None


def test_budget_stops_cleanly_before_the_job_that_would_cross_it(tmp_path, monkeypatch):
    out, summary, records, _ = run_tuning(tmp_path, monkeypatch, "native-chain", budget=1)
    # The first job is projected at nothing yet; after it, spend + projection > 1.
    assert [r["variant"] for r in records] == ["baseline-grouped"]
    budget = summary["budget"]
    assert budget["stopped"] is True and budget["jobs_run"] == 1
    assert budget["stop"]["before_job"] == "native-chain-r0-tuned-grouped"
    assert budget["spent"] == sum(c["tokens"] for c in records[0]["calls"]) > 1
    assert json.loads((out / "budget.json").read_text(encoding="utf-8")) == budget
    written = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(summary))
    verdict = summary["modes"]["native-chain"]["verdict"]
    assert verdict["result"] == "inconclusive"
    assert verdict["incomplete_pairs"] == ["native-chain#r0"]


def test_budget_lets_a_run_that_fits_finish(tmp_path, monkeypatch):
    out, summary, records, _ = run_tuning(tmp_path, monkeypatch, "native-chain",
                                          budget=10**9)
    assert len(records) == 2 and summary["budget"]["stopped"] is False
    assert summary["budget"]["spent"] == sum(c["tokens"] for r in records for c in r["calls"])
    assert summary["budget"]["largest_job"] == max(
        sum(c["tokens"] for c in r["calls"]) for r in records)


def test_budget_stops_when_a_calls_spend_is_unknown(tmp_path, monkeypatch):
    _, summary, records, _ = run_tuning(tmp_path, monkeypatch, "native-chain", budget=10**9,
                                        no_usage_for=["ledgerkit/lines.py"])
    assert len(records) == 1
    assert summary["budget"]["unknown_spend_calls"] >= 1
    assert "unknown" in summary["budget"]["stop"]["reason"]


def test_budget_projection_and_unknown_spend_rules():
    budget = lr.Budget(1000)
    assert budget.allows("j0")
    budget.add({"calls": [{"usage": usage_of(1, 0)}]})  # 110 raw
    assert budget.spent == budget.largest == 110 and budget.allows("j1")
    budget.add({"calls": [{"usage": None, "reported_cumulative": RESUMED}]})  # 307 bound
    assert budget.spent == 417 and budget.largest == 307 and budget.allows("j2")
    budget.add({"calls": [{"usage": usage_of(0, 1)}]})  # 307 raw
    assert budget.spent == 724 and not budget.allows("j3")  # 724 + 307 > 1000
    assert budget.stopped["before_job"] == "j3"
    assert not budget.allows("j4") and budget.stopped["before_job"] == "j3"
    with pytest.raises(ValueError, match="budget_tokens"):
        lr.run_live("unused", budget_tokens=0)
    with pytest.raises(ValueError, match="unknown comparison"):
        lr.run_live("unused", comparison="nope")


def test_tuning_schedule_is_counterbalanced_and_310_is_the_default():
    cases = list(CASES.values())
    jobs = [(c["id"], r, a) for c, r, a, _ in lr.schedule(cases, 2, False, "tuning")]
    assert len(jobs) == lr.TUNING_JOBS == 12
    assert [a for c, r, a in jobs if c == "native-chain"] == [
        "baseline-grouped", "tuned-grouped", "tuned-grouped", "baseline-grouped"]
    assert [(c["id"], r, a) for c, r, a, _ in lr.schedule(cases, 2, True, "tuning")] == [
        ("mixed-fork-join", 0, "baseline-grouped"), ("mixed-fork-join", 0, "tuned-grouped")]
    assert lr.schedule(cases, 3, False) == lr.schedule(cases, 3, False, "310")
    assert lr.DEFAULT_REPEATS == {"310": 3, "tuning": 2}


# --- summarize_tuning on hand-built records --------------------------------------------


def trecord(case_id, variant, repeat=0, cost=1000, raw=5000, review=400, repair=200,
            latency=100.0, caught=(True, True), accepted=True, quality_failure=False,
            false_findings=0, stop_kind="unset", invalid=0, fallbacks=0):
    r = record(case_id, "grouped", repeat, total=raw, review=review * 4, latency=latency,
               caught=caught, accepted=accepted, quality_failure=quality_failure)
    r.update(variant=variant, job_id=f"{case_id}-r{repeat}-{variant}",
             total_tokens_excl_cache=cost, review_tokens_excl_cache=review,
             kind_tokens_excl_cache={"author": 100, "repair": repair, "integration": 0,
                                     "reviewer": review},
             kind_tokens={"author": 900, "repair": repair * 5, "integration": 0,
                          "reviewer": review * 4},
             tuning={"patch_calls": 0, "patch_invalid_answers": invalid,
                     "patch_red_checks": 0, "fallbacks": fallbacks,
                     "reviewer_invalid_answers": 0, "delta_reviews": 0})
    r["quality"]["false_findings"] = false_findings
    if stop_kind != "unset":
        r["stop_kind"] = stop_kind
    return r


def good_tuning(**tuned_overrides):
    records = []
    for mode in MODES:
        for repeat in range(2):
            records.append(trecord(mode, "baseline-grouped", repeat))
            tuned = {"cost": 700, "raw": 4000, "review": 300, "repair": 100, "latency": 90.0,
                     "invalid": 1, "fallbacks": 1}
            records.append(trecord(mode, "tuned-grouped", repeat,
                                   **(tuned | tuned_overrides.get(mode, {}))))
    return records


def test_tuning_summary_better_when_every_gate_holds_and_cost_falls():
    summary = lr.summarize_tuning(good_tuning())
    assert summary["verdicts"] == {m: "better" for m in MODES}
    pair = summary["pairs"][0]
    assert pair["uncached_plus_output_saving"] == pytest.approx(0.3)
    assert pair["raw_total_saving"] == pytest.approx(0.2)
    assert pair["review_uncached_plus_output_saving"] == pytest.approx(0.25)
    assert pair["repair_uncached_plus_output_saving"] == pytest.approx(0.5)
    assert pair["review_raw_saving"] == pytest.approx(0.25)
    assert pair["repair_raw_saving"] == pytest.approx(0.5)
    mode = summary["modes"]["native-chain"]
    assert mode["verdict"]["median_saving_uncached_plus_output"] == pytest.approx(0.3)
    assert mode["tuned-grouped"]["uncached_plus_output"]["median"] == 700
    assert mode["baseline-grouped"]["raw_total"]["median"] == 5000
    assert mode["tuned-grouped"]["by_kind_uncached_plus_output"]["repair"]["median"] == 100
    assert mode["tuned-grouped"]["patch_invalid_answers"] == 2
    assert summary["counts"]["tuned-grouped"]["fallbacks"] == 6
    assert summary["counts"]["baseline-grouped"]["fallbacks"] == 0
    assert all(v is True for v in mode["verdict"]["gates"].values())


@pytest.mark.parametrize(
    ("override", "gate"),
    [
        ({"caught": (False, True)}, "no_seed_missed_that_baseline_caught"),
        ({"quality_failure": True}, "no_quality_failure"),
        ({"accepted": False, "quality_failure": None, "stop_kind": "protocol"},
         "no_extra_protocol_stop"),
        ({"false_findings": 1}, "false_findings_not_more"),
        ({"latency": 101.0}, "median_accepted_latency_not_higher"),
    ],
)
def test_each_tuning_gate_fails_its_mode_whatever_it_saves(override, gate):
    summary = lr.summarize_tuning(good_tuning(**{"sequential-delegates": override}))
    verdict = summary["modes"]["sequential-delegates"]["verdict"]
    assert verdict["gates"][gate] is False
    assert verdict["result"] == "fail"
    assert verdict["median_saving_uncached_plus_output"] > 0
    assert summary["verdicts"]["native-chain"] == "better"


def test_a_protocol_stop_the_baseline_also_had_is_not_extra():
    records = good_tuning(**{"native-chain": {"accepted": False, "quality_failure": None}})
    for r in records:
        if r["case_id"] == "native-chain" and r["variant"] == "baseline-grouped":
            r.update(accepted=False, elapsed_to_accepted_ms=None)
            r["quality"]["quality_failure"] = None
    verdict = lr.summarize_tuning(records)["modes"]["native-chain"]["verdict"]
    assert verdict["gates"]["no_extra_protocol_stop"] is True
    assert verdict["gates"]["median_accepted_latency_not_higher"] is None
    assert verdict["result"] == "inconclusive"


def test_tuning_censored_pair_is_inconclusive_unless_a_gate_fails():
    records = good_tuning()
    for r in records:
        if (r["case_id"], r["repeat"], r["variant"]) == ("native-chain", 0, "tuned-grouped"):
            r.update(stop_kind="harness", accepted=False)
    verdict = lr.summarize_tuning(records)["modes"]["native-chain"]["verdict"]
    assert verdict["result"] == "inconclusive"
    assert verdict["harness_censored_pairs"] == ["native-chain#r0"]
    assert verdict["gates"]["no_quality_failure"] is None
    failing = good_tuning(**{"native-chain": {"latency": 500.0}})
    for r in failing:
        if (r["case_id"], r["repeat"], r["variant"]) == ("native-chain", 0, "tuned-grouped"):
            r.update(stop_kind="harness", accepted=False)
    verdict = lr.summarize_tuning(failing)["modes"]["native-chain"]["verdict"]
    assert verdict["gates"]["median_accepted_latency_not_higher"] is False
    assert verdict["result"] == "fail"
    # The rerun rule: the final attempt counts, the voided one is kept with its spend.
    voided = dict(trecord("native-chain", "tuned-grouped", 0, raw=77), attempt=0,
                  stop_kind="harness", accepted=False)
    rerun = [dict(r, attempt=1) if (r["case_id"], r["repeat"]) == ("native-chain", 0) else r
             for r in good_tuning()]
    summary = lr.summarize_tuning([voided, *rerun])
    assert summary["voided_attempts"]["total_tokens"] == 77
    assert summary["verdicts"]["native-chain"] == "better"


def test_tuning_no_saving_and_unknown_cost_are_never_better():
    flat = lr.summarize_tuning(good_tuning(**{"native-chain": {"cost": 1000}}))
    assert flat["modes"]["native-chain"]["verdict"]["result"] == "not-better"
    unknown = lr.summarize_tuning(good_tuning(**{"native-chain": {"cost": None}}))
    verdict = unknown["modes"]["native-chain"]["verdict"]
    assert verdict["median_saving_uncached_plus_output"] is None
    assert verdict["result"] == "inconclusive"


def test_tuning_smoke_projection_against_the_budget_and_dispatch():
    smoke = [dict(trecord("mixed-fork-join", v, raw=100_000), smoke=True)
             for v in lr.TUNING_VARIANTS]
    fits = lr.summarize_tuning(good_tuning() + smoke, budget_tokens=4_683_504)
    assert fits["run_count"] == 12
    assert fits["smoke"]["projected_tokens_for_12_jobs"] == 1_200_000
    assert fits["smoke"]["fits_budget"] is True
    assert lr.summarize_tuning(smoke, budget_tokens=1_000_000)["smoke"]["fits_budget"] is False
    assert lr.summarize(good_tuning())["comparison"] == "tuning"
    assert "comparison" not in lr.summarize(good_run())
    assert lr.summarize(good_run()) == lr.summarize_live(good_run())


def test_cli_passes_comparison_and_budget_and_summarizes_tuning(tmp_path, monkeypatch, capsys):
    seen = {}

    def fake_run_live(out, cases, repeats, smoke, codex_bin, author_timeout, review_timeout,
                      **kwargs):
        seen.update(repeats=repeats, smoke=smoke, **kwargs)
        return {}

    monkeypatch.setattr(lr, "run_live", fake_run_live)
    monkeypatch.setattr(sys, "argv", ["live_run", "--out", str(tmp_path / "o"), "--smoke",
                                      "--comparison", "tuning", "--budget-tokens", "4683504"])
    lr.main()
    assert seen["comparison"] == "tuning" and seen["budget_tokens"] == 4683504
    assert seen["repeats"] is None and seen["smoke"] is True
    runs = tmp_path / "runs.jsonl"
    runs.write_text("".join(json.dumps(r) + "\n" for r in good_tuning()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["live_run", "--summarize", str(runs)])
    capsys.readouterr()
    lr.main()
    assert json.loads(capsys.readouterr().out)["verdicts"] == {m: "better" for m in MODES}


# --- the RR comparison: reviewer thread resume (RR_DESIGN) --------------------------------


def run_rr(tmp_path, monkeypatch, case_id, smoke=False, budget=10**12, **scenario):
    codex, log = fake_codex(tmp_path, monkeypatch, case_id, **scenario)
    out = tmp_path / "out"
    summary = lr.run_live(out, [CASES[case_id]], repeats=1, smoke=smoke, codex_bin=codex,
                          comparison="rr", budget_tokens=budget)
    records = lr.read_runs(out) if (out / "runs.jsonl").exists() else []
    calls = [json.loads(s) for s in log.read_text().splitlines()] if log.exists() else []
    return out, summary, records, calls


def reviewer_calls(record):
    return [c for c in record["calls"] if c["kind"] == "reviewer"]


def test_rr_variants_levers_schedule_and_defaults():
    assert lr.COMPARISONS["rr"] == ("repair-tuned", "repair-tuned-rr")
    assert lr.VARIANTS["repair-tuned"] == {"arm": "grouped", "levers": ("T1", "T2", "T4")}
    assert lr.VARIANTS["repair-tuned-rr"] == {"arm": "grouped",
                                              "levers": ("T1", "T2", "T4", "RR")}
    cases = list(CASES.values())
    jobs = [(c["id"], r, a) for c, r, a, _ in lr.schedule(cases, 2, False, "rr")]
    assert len(jobs) == 12 and lr.RR_JOBS == 8 and lr.RR_REPEATS == 2
    assert [a for c, r, a in jobs if c == "native-chain"] == [
        "repair-tuned", "repair-tuned-rr", "repair-tuned-rr", "repair-tuned"]
    assert [(c["id"], r, a) for c, r, a, _ in lr.schedule(cases, 2, True, "rr")] == [
        ("mixed-fork-join", 0, "repair-tuned"), ("mixed-fork-join", 0, "repair-tuned-rr")]
    assert lr.RR_CASES == ("native-chain", "sequential-delegates")
    # The #310 and tuning defaults are untouched.
    assert lr.DEFAULT_REPEATS == {"310": 3, "tuning": 2}


def test_a_full_rr_run_refuses_to_start_without_a_cap(tmp_path):
    with pytest.raises(ValueError, match="rr run needs budget_tokens"):
        lr.run_live(tmp_path / "out", [CASES["native-chain"]], comparison="rr")
    assert not (tmp_path / "out").exists()


def test_rr_defaults_to_two_modes_two_repeats_and_smoke_keeps_fork_join(tmp_path, monkeypatch):
    codex, _ = fake_codex(tmp_path, monkeypatch, "native-chain")
    seen = []

    async def fake_inner(out, cases, repeats, smoke, *args, **kwargs):
        seen.append(([c["id"] for c in cases], repeats, smoke))
        return []

    monkeypatch.setattr(lr, "_run", fake_inner)
    lr.run_live(tmp_path / "a", comparison="rr", budget_tokens=10**9, codex_bin=codex)
    lr.run_live(tmp_path / "b", comparison="rr", smoke=True, codex_bin=codex)
    assert seen[0] == (["native-chain", "sequential-delegates"], 2, False)
    # A smoke keeps every case so the schedule can pick mixed-fork-join (repeat 0 only).
    assert sorted(seen[1][0]) == sorted(CASES) and seen[1][2] is True


def test_rr_argv_first_review_persists_and_a_re_review_resumes_the_same_thread(
        tmp_path, monkeypatch):
    out, summary, records, log = run_rr(tmp_path, monkeypatch, "native-chain")
    # Counterbalanced: repeat 0 runs the base arm first.
    assert [r["variant"] for r in records] == ["repair-tuned", "repair-tuned-rr"]
    base, rr = records
    assert base["levers"] == ["T1", "T2", "T4"] and rr["levers"] == ["RR", "T1", "T2", "T4"]
    for record in records:
        assert record["status"] == "accepted", record["stop_reason"]
        assert record["quality"]["quality_failure"] is False
        assert [s["caught"] for s in record["quality"]["seeds"]] == [True, True]
        assert record["writes"]["unowned"] == [] and record["usage_unknown"] == []
        lines = ledger(out, record)
        briefs = [x for x in lines if x.get("event") == "brief"]
        outs = [x for x in lines if "event" not in x]
        deterministic = [u for u in record["units"] if u.get("i2_path") == "deterministic"]
        assert len(briefs) == len(outs) == len(record["calls"]) + len(deterministic)

    no_tools = {"shell_tool", "unified_exec", "apps", "multi_agent"}
    first, again = reviewer_calls(rr)
    a1, a2 = sent(out, first, "argv.json"), sent(out, again, "argv.json")
    # First review: fresh, tools disabled, no schema, read-only, NOT --ephemeral.
    assert "exec" in a1 and "resume" not in a1 and "--ephemeral" not in a1
    assert "--output-schema" not in a1 and no_tools <= set(a1)
    assert a1[a1.index("--sandbox") + 1] == "read-only"
    assert sent(out, first, "prompt.txt").startswith(lr.TUNED_REVIEW_PROMPT)
    # Re-review: `exec resume <the first review's thread>`, tools disabled, read-only by
    # config override, no --sandbox / --ephemeral / schema / -C.
    i = a2.index("resume")
    assert a2[i - 1] == "exec" and a2[-2:] == [first["thread_id"], "-"]
    assert no_tools <= set(a2) and "--ephemeral" not in a2 and "--output-schema" not in a2
    assert 'sandbox_mode="read-only"' in a2 and "--sandbox" not in a2 and "-C" not in a2
    assert again["resumed"] is True and again["thread_id"] == first["thread_id"]
    # The process cwd of both reviewer calls is the reviewer cwd, never the workspace.
    rows = [c for c in log if c["review"] and "--ephemeral" not in c["argv"]]
    assert len(rows) == 2 and rows[0]["cwd"] == rows[1]["cwd"]
    assert rows[1]["rereview"] is True and rows[1]["thread"] == first["thread_id"]
    assert rr["reviews"][0]["resumed"] is False and rr["reviews"][1]["resumed"] is True
    assert rr["reviews"][1]["calls"] == [again["id"]]
    # The base arm re-reviews fresh and ephemeral, with the full request.
    b1, b2 = reviewer_calls(base)
    for call in (b1, b2):
        argv = sent(out, call, "argv.json")
        assert "--ephemeral" in argv and "resume" not in argv
        assert "REVIEW REQUEST:" in sent(out, call, "prompt.txt")
    assert not any(r.get("resumed") for r in base["reviews"])

    # The delta turn: new context id, every member's revision and fast check with its flag,
    # and the text of only the changed files. B did not change, so none of B's text is sent.
    prompt = sent(out, again, "prompt.txt")
    assert prompt.startswith(lr.RR_DELTA_PROMPT) and "REVIEW REQUEST:" not in prompt
    delta = json.loads(prompt[len(lr.RR_DELTA_PROMPT):])
    assert sent(out, again, "delta.json") == delta
    request = sent(out, again, "request.json")
    assert delta["reviewer_context_id"] == request["reviewer_context_id"] != (
        sent(out, first, "request.json")["reviewer_context_id"])
    assert {u["id"]: u["changed_since_last_review"] for u in delta["units"]} == {
        "A": True, "B": False, "C": True}
    assert all(u["fast_check_passed"] is True and u["revision"] for u in delta["units"])
    files = {u["id"]: u["files"] for u in CASES["native-chain"]["units"]}
    assert set(delta["changed_files"]) == set(files["A"]) | set(files["C"])
    reference = Path(CASES["native-chain"]["reference_dir"])
    for rel in files["B"]:
        assert (reference / rel).read_text() not in prompt
    assert "previous_findings" not in delta and "context_files" not in delta
    assert len(prompt) < len(sent(out, first, "prompt.txt"))

    # Accounting is by per-thread delta: the resumed call is its own usage, not the total.
    assert again["usage"] == {"uncached_input": 50, "cache_read": 250, "output": 7, "turns": 1}
    assert again["tokens_excl_cache"] == 57
    # Counts, the re-review-only cost per arm, and every reviewer call's cache read.
    assert rr["tuning"]["resumed_reviews"] == 1 and rr["tuning"]["resume_fallbacks"] == 0
    assert rr["tuning"]["fresh_after_error"] == 0 and rr["tuning"]["reviewer_invalid_answers"] == 0
    assert base["tuning"]["resumed_reviews"] == 0
    assert rr["rereview_tokens_excl_cache"] == 57 and base["rereview_tokens_excl_cache"] == 70
    assert rr["first_review_tokens_excl_cache"] == base["first_review_tokens_excl_cache"] == 70
    assert [(c["review_index"], c["review_mode"], c["cache_read"])
            for c in rr["reviewer_cache"]] == [(0, "fresh", 40), (1, "resumed", 250)]
    assert [(c["review_index"], c["review_mode"], c["cache_read"])
            for c in base["reviewer_cache"]] == [(0, "fresh", 40), (1, "fresh", 40)]
    assert base["reviewer_zero_cache_calls"] == 0
    # Only RR changes how a re-review is delivered: the repairs are the same patch calls.
    assert [c["repair_mode"] for c in rr["calls"] if c["kind"] == "repair"] == ["patch"] * 2
    assert [c["repair_mode"] for c in base["calls"] if c["kind"] == "repair"] == ["patch"] * 2
    # The summary on disk is what runs.jsonl recomputes to, and says it is the RR comparison.
    assert summary["comparison"] == "rr" and summary["design"] == lr.RR_DESIGN
    written = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert written.pop("budget")["cap"] == 10**12
    assert written == json.loads(json.dumps(lr.summarize_rr(records, 10**12)))
    assert summary["modes"]["native-chain"]["repair-tuned-rr"]["resumed_reviews"] == 1
    meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert meta["comparison"] == "rr" and meta["design"] == lr.RR_DESIGN
    assert meta["variants"]["repair-tuned-rr"]["levers"] == ["T1", "T2", "T4", "RR"]
    assert meta["rr_prompts"] == {"review_rr_delta_turn": lr.RR_DELTA_PROMPT}


def test_after_a_reviewer_error_round_the_next_review_is_fresh_on_a_new_thread(
        tmp_path, monkeypatch):
    _, _, records, _ = run_rr(tmp_path, monkeypatch, "native-chain",
                              garbage_persistent_reviews=1)
    base, rr = records
    assert rr["status"] == "accepted", rr["stop_reason"]
    r0, r1, r2 = rr["reviews"]
    assert (r0["valid_answer"], r0["round_kind"]) == (False, "reviewer-error")
    # Not a resume: the review after the error round is fresh, persistent, new thread.
    assert r1["resumed"] is False and r1["thread_id"] != r0["thread_id"]
    call = next(c for c in rr["calls"] if c["id"] == r1["call"])
    assert call["review_mode"] == "fresh" and call["resumed"] is False
    # The thread of the review after that is the new one.
    assert r2["resumed"] is True and r2["thread_id"] == r1["thread_id"]
    assert rr["tuning"]["fresh_after_error"] == 1 and rr["tuning"]["resumed_reviews"] == 1
    assert rr["tuning"]["resume_fallbacks"] == 0
    assert rr["tuning"]["reviewer_invalid_answers"] == 1
    assert base["tuning"]["fresh_after_error"] == 0


@pytest.mark.parametrize("scenario", [{"fail_resume": 1}, {"no_usage_rereview": True}])
def test_a_resume_that_fails_at_harness_level_gets_exactly_one_counted_fresh_review(
        tmp_path, monkeypatch, scenario):
    out, _, records, _ = run_rr(tmp_path, monkeypatch, "native-chain", **scenario)
    rr = records[1]
    assert rr["status"] == "accepted", rr["stop_reason"]
    first, failed, fresh = reviewer_calls(rr)
    assert failed["resumed"] is True and failed["review_mode"] == "resumed"
    assert fresh["review_mode"] == "fresh-fallback" and fresh["resumed"] is False
    assert fresh["fallback_reason"] and failed["review_index"] == fresh["review_index"] == 1
    argv = sent(out, fresh, "argv.json")
    assert "resume" not in argv and "--ephemeral" not in argv
    assert "REVIEW REQUEST:" in sent(out, fresh, "prompt.txt")
    assert fresh["thread_id"] not in (None, first["thread_id"])
    # Exactly one fallback, one review row for the round, and the failed call is clocked.
    reviews = [r for r in rr["reviews"] if r["unit"] == "R"]
    assert len(reviews) == 2 and reviews[1]["resumed"] is False
    assert reviews[1]["resume_fallback"] == fresh["fallback_reason"]
    assert rr["tuning"]["resume_fallbacks"] == 1 and rr["tuning"]["resumed_reviews"] == 0
    assert len(reviewer_calls(rr)) == 3
    lines = ledger(out, rr)
    briefs = [x for x in lines if x.get("event") == "brief"]
    outs = [x for x in lines if "event" not in x]
    deterministic = [u for u in rr["units"] if u.get("i2_path") == "deterministic"]
    assert len(briefs) == len(outs) == len(rr["calls"]) + len(deterministic)
    trace = [(t["event"], t.get("status")) for t in rr["trace"] if t["unit"] == "R"]
    assert ("clock_out", "in_progress") in trace
    # The next review, if any, would resume the fallback's new thread.
    assert records[0]["tuning"]["resume_fallbacks"] == 0


def test_a_first_review_with_no_thread_is_followed_by_one_counted_fresh_review(
        tmp_path, monkeypatch):
    out, _, records, _ = run_rr(tmp_path, monkeypatch, "native-chain", no_thread_first=1)
    rr = records[1]
    assert rr["status"] == "accepted", rr["stop_reason"]
    calls = reviewer_calls(rr)
    assert len(calls) == 2 and calls[0]["thread_id"] is None
    # No resume was possible, so none was attempted: one fresh full review, counted.
    assert calls[1]["resumed"] is False and "resume" not in sent(out, calls[1], "argv.json")
    assert rr["tuning"]["resume_fallbacks"] == 1 and rr["tuning"]["resumed_reviews"] == 0


def test_an_invalid_resumed_answer_is_a_reviewer_error_round_not_a_fallback(
        tmp_path, monkeypatch):
    _, _, records, _ = run_rr(tmp_path, monkeypatch, "native-chain", garbage_rereviews=1)
    rr = records[1]
    assert rr["status"] == "accepted", rr["stop_reason"]
    r0, r1, r2 = rr["reviews"]
    assert r1["resumed"] is True and r1["valid_answer"] is False
    assert r1["round_kind"] == "reviewer-error"
    assert r2["resumed"] is False  # fresh after the error round, on a new thread
    assert r2["thread_id"] != r1["thread_id"]
    assert rr["tuning"]["resume_fallbacks"] == 0 and rr["tuning"]["fresh_after_error"] == 1
    assert rr["tuning"]["reviewer_invalid_answers"] == 1


def test_resumes_are_capped_per_thread_and_state_follows_the_rules():
    arm = lr.Arm.__new__(lr.Arm)
    arm.levers = {"RR"}
    arm.counts = {"resume_fallbacks": 0, "fresh_after_error": 0, "resume_capped": 0}
    arm.rr_state = {}
    assert arm.rr_thread("R", 0) is None and arm.counts["fresh_after_error"] == 0
    arm.rr_state["R"] = {"thread": "t1", "resumes": 0}
    assert arm.rr_thread("R", 1) == "t1"
    arm.rr_state["R"] = {"thread": "t1", "resumes": lr.MAX_RESUMES}
    assert arm.rr_thread("R", 3) is None and arm.counts["resume_capped"] == 1
    arm.rr_state["R"] = {"thread": None, "resumes": 0}
    assert arm.rr_thread("R", 1) is None and arm.counts["resume_fallbacks"] == 1
    del arm.rr_state["R"]
    assert arm.rr_thread("R", 1) is None and arm.counts["fresh_after_error"] == 1
    arm.levers = set()  # no RR: never a resume, nothing counted
    arm.rr_state["R"] = {"thread": "t1", "resumes": 0}
    assert arm.rr_thread("R", 1) is None and arm.counts["resume_capped"] == 1
    assert lr.MAX_RESUMES == 2


def test_convergence_counts_findings_on_members_unchanged_since_the_previous_review():
    prior = {"revisions": {"A": "a1", "B": "b1", "C": "c1"}}
    findings = [{"unit": "A", "criterion": "x", "detail": "d"},
                {"unit": "B", "criterion": "x", "detail": "d"},
                {"unit": "B", "criterion": "y", "detail": "d"},
                {"unit": "C", "criterion": "x", "detail": "d"}]
    now = {"A": "a2", "B": "b1", "C": "c1"}  # only A changed
    assert [f["unit"] for f in lr.convergence_findings(prior, now, findings)] == [
        "B", "B", "C"]
    assert lr.convergence_findings(prior, {"A": "a2", "B": "b2", "C": "c2"}, findings) == []
    assert lr.convergence_findings(None, now, findings) == []  # no previous review
    assert lr.convergence_findings(prior, now, []) == []


def test_convergence_is_counted_per_review_in_a_real_run(tmp_path, monkeypatch):
    # A reviewer that finds something on every unit, every time: after the repair only A
    # and C changed, so the finding on B is a finding on an unchanged member.
    _, _, records, _ = run_rr(tmp_path, monkeypatch, "native-chain", reviewer="reject")
    for record in records:
        reviews = record["reviews"]
        assert reviews[0]["convergence_findings"] == 0
        assert reviews[1]["convergence_findings"] == 1
        assert [f["unit"] for f in reviews[1]["convergence_detail"]] == ["B"]
        assert record["tuning"]["convergence_findings"] == sum(
            r["convergence_findings"] for r in reviews)
    rr = records[1]
    assert rr["tuning"]["resumed_reviews"] == 2  # two resumes on one thread: the cap
    assert [r["resumed"] for r in rr["reviews"]] == [False, True, True]
    assert len({r["thread_id"] for r in rr["reviews"]}) == 1
    assert rr["stop_kind"] == "protocol"


def test_rr_smoke_is_the_fork_join_pair_with_an_eight_job_projection(tmp_path, monkeypatch):
    out, summary, records, _ = run_rr(tmp_path, monkeypatch, "mixed-fork-join", smoke=True,
                                      budget=3_000_000)
    assert [(r["variant"], r["repeat"], r["smoke"]) for r in records] == [
        ("repair-tuned", 0, True), ("repair-tuned-rr", 0, True)]
    for record in records:
        assert record["status"] == "accepted", record["stop_reason"]
        assert record["observations"]["holds"] is True
    rr = records[1]
    # The contract gate QA_K is reviewed once and approved; R is re-reviewed by resume.
    assert any(c["unit"] == "QA_K" and c["kind"] == "reviewer" for c in rr["calls"])
    assert rr["tuning"]["resumed_reviews"] >= 1
    smoke = summary["smoke"]
    assert smoke["projected_tokens_for_8_jobs"] == max(r["total_tokens"] for r in records) * 8
    spent = sum(r["total_tokens"] for r in records)
    assert smoke["tokens_measured"] == spent
    assert smoke["projected_plus_smoke_tokens"] == smoke["projected_tokens_for_8_jobs"] + spent
    assert smoke["run_cap_after_smoke"] == 3_000_000 - spent - lr.RR_CAP_MARGIN


# --- summarize_rr on hand-built records ------------------------------------------------


def rrrecord(case_id, variant, repeat=0, rereview=300, resumed=0, fallbacks=0, converged=0,
             **kwargs):
    r = trecord(case_id, "repair-tuned", repeat, **kwargs)
    r.update(variant=variant, job_id=f"{case_id}-r{repeat}-{variant}",
             rereview_tokens_excl_cache=rereview, rereview_tokens=rereview * 3)
    r["tuning"].update(resumed_reviews=resumed, resume_fallbacks=fallbacks,
                       fresh_after_error=0, resume_capped=0, convergence_findings=converged)
    return r


def good_rr(**rr_overrides):
    records = []
    for mode in MODES:
        for repeat in range(2):
            records.append(rrrecord(mode, "repair-tuned", repeat))
            rr = {"cost": 800, "raw": 4500, "review": 300, "repair": 200, "latency": 90.0,
                  "rereview": 60, "resumed": 1}
            records.append(rrrecord(mode, "repair-tuned-rr", repeat,
                                    **(rr | rr_overrides.get(mode, {}))))
    return records


def test_rr_summary_better_when_every_gate_holds_and_cost_falls():
    summary = lr.summarize_rr(good_rr())
    assert summary["comparison"] == "rr" and summary["design"] == lr.RR_DESIGN
    assert summary["verdicts"] == {m: "better" for m in MODES}
    pair = summary["pairs"][0]
    assert pair["arms_present"] == ["repair-tuned", "repair-tuned-rr"]
    assert pair["uncached_plus_output_saving"] == pytest.approx(0.2)
    assert pair["rereview_uncached_plus_output_saving"] == pytest.approx(0.8)
    assert pair["rereview_raw_saving"] == pytest.approx(0.8)
    mode = summary["modes"]["native-chain"]
    assert mode["verdict"]["median_saving_uncached_plus_output"] == pytest.approx(0.2)
    assert mode["repair-tuned-rr"]["rereview_uncached_plus_output"]["median"] == 60
    assert mode["repair-tuned"]["rereview_uncached_plus_output"]["median"] == 300
    assert mode["repair-tuned-rr"]["resumed_reviews"] == 2
    assert summary["counts"]["repair-tuned-rr"]["resumed_reviews"] == 6
    assert summary["counts"]["repair-tuned"]["resumed_reviews"] == 0
    assert "tuned-grouped" not in mode and "baseline-grouped" not in mode
    assert all(v is True for v in mode["verdict"]["gates"].values())
    assert lr.summarize(good_rr())["comparison"] == "rr"
    assert lr.summarize(good_tuning())["comparison"] == "tuning"


@pytest.mark.parametrize(
    ("override", "gate"),
    [
        ({"caught": (False, True)}, "no_seed_missed_that_baseline_caught"),
        ({"quality_failure": True}, "no_quality_failure"),
        ({"accepted": False, "quality_failure": None, "stop_kind": "protocol"},
         "no_extra_protocol_stop"),
        ({"false_findings": 1}, "false_findings_not_more"),
        ({"latency": 101.0}, "median_accepted_latency_not_higher"),
    ],
)
def test_each_rr_gate_fails_its_mode_whatever_it_saves(override, gate):
    summary = lr.summarize_rr(good_rr(**{"sequential-delegates": override}))
    verdict = summary["modes"]["sequential-delegates"]["verdict"]
    assert verdict["gates"][gate] is False
    assert verdict["result"] == "fail"
    assert verdict["median_saving_uncached_plus_output"] > 0
    assert summary["verdicts"]["native-chain"] == "better"


def test_rr_censored_pair_flat_cost_and_rerun_follow_the_tuning_rules():
    records = good_rr()
    for r in records:
        if (r["case_id"], r["repeat"], r["variant"]) == ("native-chain", 0, "repair-tuned-rr"):
            r.update(stop_kind="harness", accepted=False)
    verdict = lr.summarize_rr(records)["modes"]["native-chain"]["verdict"]
    assert verdict["result"] == "inconclusive"
    assert verdict["harness_censored_pairs"] == ["native-chain#r0"]
    flat = lr.summarize_rr(good_rr(**{"native-chain": {"cost": 1000}}))
    assert flat["modes"]["native-chain"]["verdict"]["result"] == "not-better"
    voided = dict(rrrecord("native-chain", "repair-tuned-rr", 0, raw=77), attempt=0,
                  stop_kind="harness", accepted=False)
    rerun = [dict(r, attempt=1) if (r["case_id"], r["repeat"]) == ("native-chain", 0) else r
             for r in good_rr()]
    again = lr.summarize_rr([voided, *rerun])
    assert again["voided_attempts"]["total_tokens"] == 77
    assert again["verdicts"]["native-chain"] == "better"


def test_rr_smoke_projection_needs_the_whole_pair_and_fits_with_its_own_spend():
    smoke = [dict(rrrecord("mixed-fork-join", v, raw=100_000), smoke=True)
             for v in lr.RR_VARIANTS]
    s = lr.summarize_rr(smoke, budget_tokens=3_000_000)["smoke"]
    assert s["projected_tokens_for_8_jobs"] == 800_000
    assert s["projected_plus_smoke_tokens"] == 1_000_000 and s["fits_budget"] is True
    assert s["run_cap_after_smoke"] == 3_000_000 - 200_000 - 400_000
    assert lr.summarize_rr(smoke, budget_tokens=900_000)["smoke"]["fits_budget"] is False
    uneven = [dict(smoke[0], total_tokens=100), dict(smoke[1], total_tokens=300)]
    again = lr.summarize_rr(uneven, 3000)["smoke"]
    assert again["projected_tokens_for_8_jobs"] == 2400  # larger job x 8, never the mean
    assert again["mean_projected_tokens_for_8_jobs"] == 1600
    assert again["projected_plus_smoke_tokens"] == 2800 and again["fits_budget"] is True
    half = lr.summarize_rr(smoke[:1], 3_000_000)["smoke"]
    assert half["projected_tokens_for_8_jobs"] is None and half["fits_budget"] is None
    assert half["run_cap_after_smoke"] == 3_000_000 - 100_000 - 400_000


def test_cli_passes_rr_comparison_cases_and_summarizes_rr(tmp_path, monkeypatch, capsys):
    seen = {}

    def fake_run_live(out, cases, repeats, smoke, codex_bin, author_timeout, review_timeout,
                      **kwargs):
        seen.update(cases=[c["id"] for c in cases], repeats=repeats, smoke=smoke, **kwargs)
        return {}

    monkeypatch.setattr(lr, "run_live", fake_run_live)
    monkeypatch.setattr(sys, "argv", ["live_run", "--out", str(tmp_path / "o"),
                                      "--comparison", "rr", "--budget-tokens", "2000000"])
    lr.main()
    assert seen["comparison"] == "rr" and seen["budget_tokens"] == 2_000_000
    assert seen["cases"] == ["native-chain", "sequential-delegates"] and seen["repeats"] is None
    monkeypatch.setattr(sys, "argv", ["live_run", "--out", str(tmp_path / "o"), "--smoke",
                                      "--comparison", "rr", "--budget-tokens", "3000000"])
    lr.main()
    assert "mixed-fork-join" in seen["cases"] and seen["smoke"] is True
    monkeypatch.setattr(sys, "argv", ["live_run", "--out", str(tmp_path / "o"),
                                      "--comparison", "rr", "--budget-tokens", "1",
                                      "--cases", "mixed-fork-join"])
    lr.main()
    assert seen["cases"] == ["mixed-fork-join"]
    runs = tmp_path / "runs.jsonl"
    runs.write_text("".join(json.dumps(r) + "\n" for r in good_rr()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["live_run", "--summarize", str(runs)])
    capsys.readouterr()
    lr.main()
    assert json.loads(capsys.readouterr().out)["verdicts"] == {m: "better" for m in MODES}


def test_host_argv_default_reviewer_is_unchanged_and_rr_only_adds_persist_and_resume():
    host = lr.Host.__new__(lr.Host)
    host.codex_bin, host.response_schema = ["codex"], Path("/s.json")
    base = host.argv("review", Path("/w"), "review", None)
    assert "--ephemeral" in base and "--output-schema" in base and "resume" not in base
    assert host.argv("review", Path("/w"), "review", None, persist=False) == base
    persisted = host.argv("review", Path("/w"), "review", None, schema=False, persist=True)
    assert "--ephemeral" not in persisted and persisted.count("--sandbox") == 1
    resumed = host.argv("review", Path("/w"), "review", "thr-1", schema=False, persist=True)
    assert resumed[:3] == ["codex", "exec", "resume"] and resumed[-2:] == ["thr-1", "-"]
    assert "--sandbox" not in resumed and 'sandbox_mode="read-only"' in resumed
    assert {"shell_tool", "unified_exec", "apps", "multi_agent"} <= set(resumed)


# --- the AB comparison (batched author prompt): --comparison batch ------------------------


def run_batch(tmp_path, monkeypatch, case_id, smoke=False, budget=10**12, **scenario):
    codex, log = fake_codex(tmp_path, monkeypatch, case_id, **scenario)
    out = tmp_path / "out"
    summary = lr.run_live(out, [CASES[case_id]], repeats=1, smoke=smoke, codex_bin=codex,
                          comparison="batch", budget_tokens=budget)
    records = lr.read_runs(out) if (out / "runs.jsonl").exists() else []
    calls = [json.loads(s) for s in log.read_text().splitlines()] if log.exists() else []
    return out, summary, records, calls, codex


def test_batch_variants_levers_schedule_and_defaults():
    assert lr.COMPARISONS["batch"] == ("rr-base", "rr-batched")
    # rr-base is the RR comparison's repair-tuned-rr, lever for lever; AB is the only add.
    assert lr.VARIANTS["rr-base"] == lr.VARIANTS["repair-tuned-rr"]
    assert lr.VARIANTS["rr-batched"] == {"arm": "grouped",
                                         "levers": ("T1", "T2", "T4", "RR", "AB")}
    cases = list(CASES.values())
    jobs = [(c["id"], r, a) for c, r, a, _ in lr.schedule(cases, 2, False, "batch")]
    assert len(jobs) == 12 and lr.BATCH_JOBS == 8 and lr.BATCH_REPEATS == 2
    # Counterbalanced: even repeats run rr-base first.
    assert [a for c, r, a in jobs if c == "native-chain"] == [
        "rr-base", "rr-batched", "rr-batched", "rr-base"]
    assert [(c["id"], r, a) for c, r, a, _ in lr.schedule(cases, 2, True, "batch")] == [
        ("mixed-fork-join", 0, "rr-base"), ("mixed-fork-join", 0, "rr-batched")]
    assert lr.BATCH_CASES == ("native-chain", "sequential-delegates")
    assert lr.BATCH_CAP_MARGIN == 400_000
    assert lr.DEFAULT_REPEATS == {"310": 3, "tuning": 2}
    # The other comparisons' arms are untouched.
    assert lr.COMPARISONS["rr"] == ("repair-tuned", "repair-tuned-rr")


def test_a_full_batch_run_refuses_to_start_without_a_cap(tmp_path):
    with pytest.raises(ValueError, match="batch run needs budget_tokens"):
        lr.run_live(tmp_path / "out", [CASES["native-chain"]], comparison="batch")
    assert not (tmp_path / "out").exists()


def test_batch_defaults_to_two_modes_two_repeats_and_smoke_keeps_fork_join(
        tmp_path, monkeypatch):
    codex, _ = fake_codex(tmp_path, monkeypatch, "native-chain")
    seen = []

    async def fake_inner(out, cases, repeats, smoke, *args, **kwargs):
        seen.append(([c["id"] for c in cases], repeats, smoke))
        return []

    monkeypatch.setattr(lr, "_run", fake_inner)
    lr.run_live(tmp_path / "a", comparison="batch", budget_tokens=10**9, codex_bin=codex)
    lr.run_live(tmp_path / "b", comparison="batch", smoke=True, codex_bin=codex)
    assert seen[0] == (["native-chain", "sequential-delegates"], 2, False)
    assert sorted(seen[1][0]) == sorted(CASES) and seen[1][2] is True


def test_tool_steps_counts_only_command_executions_and_file_changes():
    items = [{"type": "command_execution"}, {"type": "file_change"},
             {"type": "agent_message"}, {"type": "reasoning"}, {"type": "command_execution"}]
    assert lr.tool_steps(items) == 3 and lr.tool_steps([]) == 0


@pytest.mark.parametrize("case_id", ["native-chain", "sequential-delegates"])
def test_batched_prompt_is_on_every_author_call_once_and_nothing_else_differs(
        tmp_path, monkeypatch, case_id):
    out, summary, records, log, codex = run_batch(tmp_path, monkeypatch, case_id)
    assert [r["variant"] for r in records] == ["rr-base", "rr-batched"]
    base, batched = records
    assert base["levers"] == ["RR", "T1", "T2", "T4"]
    assert batched["levers"] == ["AB", "RR", "T1", "T2", "T4"]
    for record in records:
        assert record["status"] == "accepted", record["stop_reason"]
        assert record["quality"]["quality_failure"] is False
    # The paragraph is the design's, verbatim.
    assert lr.AB_PARAGRAPH == (
        "Work in as few tool steps as you can: do not explore or re-read files you "
        "already have in this prompt; write each file you own completely in a single "
        "edit; then run the fast check once. Only if it fails, fix and run it again.\n")
    kinds = {c["kind"] for c in batched["calls"]}
    assert "author" in kinds and "reviewer" in kinds and "repair" in kinds
    for record in records:
        for call in record["calls"]:
            prompt = sent(out, call, "prompt.txt")
            want = 1 if record is batched and call["kind"] == "author" else 0
            assert prompt.count(lr.AB_PARAGRAPH) == want, (record["variant"], call["id"])
            if want:
                assert prompt.startswith(lr.AUTHOR_PROMPT + lr.AB_PARAGRAPH)
            elif call["kind"] == "author":
                assert prompt.startswith(lr.AUTHOR_PROMPT)
                assert not prompt.startswith(lr.AUTHOR_PROMPT + "Work in")
    # Nothing else differs: with the paragraph taken out, the batched arm's calls are the
    # base arm's, argv and prompt, call for call.
    rows = sent_calls(out, tmp_path, codex)

    def arm(job):
        return {k.split("|", 1)[1]: v for k, v in rows.items() if k.split("|")[0] == job}

    one, two = arm(f"{case_id}-r0-rr-base"), arm(f"{case_id}-r0-rr-batched")
    assert one and set(one) == set(two)
    assert {k: v.replace(lr.AB_PARAGRAPH, "") for k, v in two.items()} == one
    assert two != one
    # Both arms carry the RR comparison's counts and figures, and both resume re-reviews.
    for record in records:
        assert record["tuning"]["resumed_reviews"] >= 1 or case_id != "native-chain"
        assert {"rereview_tokens_excl_cache", "reviewer_cache", "reviewer_zero_cache_calls",
                "first_review_tokens_excl_cache"} <= set(record)
        assert {"resume_fallbacks", "fresh_after_error", "resume_capped",
                "convergence_findings"} <= set(record["tuning"])
    delegates = [c for c in batched["calls"] if c["kind"] == "author" and c["context"] != "parent"]
    assert bool(delegates) == (case_id == "sequential-delegates")


def test_rr_base_sends_exactly_the_rr_comparisons_repair_tuned_rr_calls(tmp_path, monkeypatch):
    """rr-base is repair-tuned-rr: same argv, same prompts, call for call."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    codex_a, _ = fake_codex(a, monkeypatch, "native-chain")
    lr.run_live(a / "out", [CASES["native-chain"]], repeats=1, codex_bin=codex_a,
                comparison="rr", budget_tokens=10**12)
    rows_rr = sent_calls(a / "out", a, codex_a)
    codex_b, _ = fake_codex(b, monkeypatch, "native-chain")
    lr.run_live(b / "out", [CASES["native-chain"]], repeats=1, codex_bin=codex_b,
                comparison="batch", budget_tokens=10**12)
    rows_batch = sent_calls(b / "out", b, codex_b)

    def arm(rows, job):
        return {k.split("|", 1)[1]: v for k, v in rows.items() if k.split("|")[0] == job}

    base = arm(rows_rr, "native-chain-r0-repair-tuned-rr")
    assert base and base == arm(rows_batch, "native-chain-r0-rr-base")
    assert arm(rows_batch, "native-chain-r0-rr-batched") != base


def test_author_tool_steps_are_counted_per_author_call_and_only_for_authors(
        tmp_path, monkeypatch):
    out, summary, records, _, _ = run_batch(tmp_path, monkeypatch, "native-chain",
                                            steps=3, change_items=True)
    own = {u["id"]: u["files"] for u in CASES["native-chain"]["units"]}
    for record in records:
        authors = [c for c in record["calls"] if c["kind"] == "author"]
        assert authors and record["author_calls"] == len(authors)
        rows = {r["call"]: r for r in record["author_tool_steps"]}
        assert list(rows) == [c["id"] for c in authors]
        for call in authors:
            # 3 commands, plus one file_change per owned file; messages are not steps.
            assert call["tool_steps"] == 3 + len(own[call["unit"]])
            assert rows[call["id"]]["tool_steps"] == call["tool_steps"]
        assert record["author_tool_steps_total"] == sum(c["tool_steps"] for c in authors)
        # Author-only cost: the author kind's uncached + output, and its raw total.
        assert record["author_tokens_excl_cache"] == record["kind_tokens_excl_cache"]["author"]
        assert record["author_tokens"] == record["kind_tokens"]["author"]
        assert record["author_tokens_excl_cache"] == sum(
            c["tokens_excl_cache"] for c in authors)
        # A repair (patch) call carries no step figure into the author total.
        assert [c["kind"] for c in record["calls"]].count("repair") >= 1
    assert summary["modes"]["native-chain"]["rr-batched"]["author_tool_steps"][
        "median"] == records[1]["author_tool_steps_total"]
    # A #310 or RR record has none of these keys.
    codex, _ = fake_codex(tmp_path, monkeypatch, "native-chain")
    other = tmp_path / "rr-out"
    lr.run_live(other, [CASES["native-chain"]], repeats=1, codex_bin=codex, comparison="rr",
                budget_tokens=10**12)
    for record in lr.read_runs(other):
        assert "author_tool_steps" not in record and "tool_steps" not in record["calls"][0]


def test_batch_smoke_is_the_fork_join_pair_with_an_eight_job_projection(tmp_path, monkeypatch):
    out, summary, records, _, _ = run_batch(tmp_path, monkeypatch, "mixed-fork-join",
                                            smoke=True, budget=3_000_000)
    assert [(r["variant"], r["repeat"], r["smoke"]) for r in records] == [
        ("rr-base", 0, True), ("rr-batched", 0, True)]
    for record in records:
        assert record["status"] == "accepted", record["stop_reason"]
    smoke = summary["smoke"]
    assert smoke["projected_tokens_for_8_jobs"] == max(r["total_tokens"] for r in records) * 8
    spent = sum(r["total_tokens"] for r in records)
    assert smoke["projected_plus_smoke_tokens"] == smoke["projected_tokens_for_8_jobs"] + spent
    assert smoke["run_cap_after_smoke"] == 3_000_000 - spent - 400_000
    assert summary["comparison"] == "batch" and summary["design"] == lr.BATCH_DESIGN
    written = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert written["budget"]["cap"] == 3_000_000
    assert (out / "budget.json").exists()
    assert written.pop("budget") and written == json.loads(
        json.dumps(lr.summarize_batch(records, 3_000_000)))
    meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert meta["comparison"] == "batch" and meta["design"] == lr.BATCH_DESIGN
    assert meta["variants"]["rr-batched"]["levers"] == ["T1", "T2", "T4", "RR", "AB"]
    assert meta["batch_prompts"] == {"author_batching_paragraph_ab": lr.AB_PARAGRAPH}


def test_a_full_batch_run_stops_cleanly_at_the_cap(tmp_path, monkeypatch):
    out, summary, records, _, _ = run_batch(tmp_path, monkeypatch, "native-chain", budget=1)
    # The first job runs (nothing was spent yet); the second would cross the cap.
    assert [r["variant"] for r in records] == ["rr-base"]
    assert summary["budget"]["stopped"] is True


# --- summarize_batch on hand-built records ---------------------------------------------


def bkrecord(case_id, variant, repeat=0, steps=6, author=100, author_raw=900, **kwargs):
    r = rrrecord(case_id, variant, repeat, **kwargs)
    r.update(author_calls=2, author_tool_steps_total=steps, author_tokens_excl_cache=author,
             author_tokens=author_raw)
    return r


def good_batch(**batched_overrides):
    records = []
    for mode in MODES:
        for repeat in range(2):
            records.append(bkrecord(mode, "rr-base", repeat))
            batched = {"cost": 800, "raw": 4500, "review": 300, "repair": 200, "latency": 90.0,
                       "steps": 2, "author": 40, "author_raw": 300}
            records.append(bkrecord(mode, "rr-batched", repeat,
                                    **(batched | batched_overrides.get(mode, {}))))
    return records


def test_batch_summary_better_reports_author_cost_and_steps_and_dispatches():
    summary = lr.summarize_batch(good_batch())
    assert summary["comparison"] == "batch" and summary["design"] == lr.BATCH_DESIGN
    assert summary["limitations"] == lr.BATCH_LIMITS
    assert summary["verdicts"] == {m: "better" for m in MODES}
    pair = summary["pairs"][0]
    assert pair["arms_present"] == ["rr-base", "rr-batched"]
    assert pair["uncached_plus_output_saving"] == pytest.approx(0.2)
    assert pair["author_uncached_plus_output_saving"] == pytest.approx(0.6)
    assert pair["author_raw_saving"] == pytest.approx(1 - 300 / 900)
    assert pair["author_tool_steps_saving"] == pytest.approx(1 - 2 / 6)
    mode = summary["modes"]["native-chain"]
    assert mode["verdict"]["median_saving_uncached_plus_output"] == pytest.approx(0.2)
    assert mode["rr-batched"]["author_uncached_plus_output"]["median"] == 40
    assert mode["rr-base"]["author_tool_steps"]["median"] == 6
    assert mode["rr-batched"]["raw_total"]["median"] == 4500
    assert "repair-tuned" not in mode
    assert all(v is True for v in mode["verdict"]["gates"].values())
    assert set(summary["counts"]) == {"rr-base", "rr-batched"}
    assert lr.summarize(good_batch())["comparison"] == "batch"
    assert lr.summarize(good_rr())["comparison"] == "rr"
    # The cost verdict does not follow the author-only figure: flat total cost is not-better.
    flat = lr.summarize_batch(good_batch(**{"native-chain": {"cost": 1000}}))
    assert flat["modes"]["native-chain"]["verdict"]["result"] == "not-better"


@pytest.mark.parametrize(
    ("override", "gate"),
    [
        ({"caught": (False, True)}, "no_seed_missed_that_baseline_caught"),
        ({"quality_failure": True}, "no_quality_failure"),
        ({"accepted": False, "quality_failure": None, "stop_kind": "protocol"},
         "no_extra_protocol_stop"),
        ({"false_findings": 1}, "false_findings_not_more"),
        ({"latency": 101.0}, "median_accepted_latency_not_higher"),
    ],
)
def test_each_batch_gate_fails_its_mode_whatever_it_saves(override, gate):
    summary = lr.summarize_batch(good_batch(**{"sequential-delegates": override}))
    verdict = summary["modes"]["sequential-delegates"]["verdict"]
    assert verdict["gates"][gate] is False
    assert verdict["result"] == "fail"
    assert verdict["median_saving_uncached_plus_output"] > 0
    assert summary["verdicts"]["native-chain"] == "better"


def test_batch_censored_pair_and_rerun_follow_the_tuning_rules():
    records = good_batch()
    for r in records:
        if (r["case_id"], r["repeat"], r["variant"]) == ("native-chain", 0, "rr-batched"):
            r.update(stop_kind="harness", accepted=False)
    verdict = lr.summarize_batch(records)["modes"]["native-chain"]["verdict"]
    assert verdict["result"] == "inconclusive"
    assert verdict["harness_censored_pairs"] == ["native-chain#r0"]
    voided = dict(bkrecord("native-chain", "rr-batched", 0, raw=77), attempt=0,
                  stop_kind="harness", accepted=False)
    rerun = [dict(r, attempt=1) if (r["case_id"], r["repeat"]) == ("native-chain", 0) else r
             for r in good_batch()]
    again = lr.summarize_batch([voided, *rerun])
    assert again["voided_attempts"]["total_tokens"] == 77
    assert again["verdicts"]["native-chain"] == "better"


def test_batch_smoke_projection_counts_its_own_spend_and_keeps_a_400k_margin():
    smoke = [dict(bkrecord("mixed-fork-join", v, raw=100_000), smoke=True)
             for v in lr.BATCH_VARIANTS]
    s = lr.summarize_batch(smoke, budget_tokens=2_500_000)["smoke"]
    assert s["projected_tokens_for_8_jobs"] == 800_000
    assert s["projected_plus_smoke_tokens"] == 1_000_000 and s["fits_budget"] is True
    assert s["run_cap_after_smoke"] == 2_500_000 - 200_000 - 400_000
    assert s["run_cap_margin"] == 400_000
    assert lr.summarize_batch(smoke, budget_tokens=900_000)["smoke"]["fits_budget"] is False
    uneven = [dict(smoke[0], total_tokens=100), dict(smoke[1], total_tokens=300)]
    again = lr.summarize_batch(uneven, 3000)["smoke"]
    assert again["projected_tokens_for_8_jobs"] == 2400  # larger job x 8, never the mean
    assert again["projected_plus_smoke_tokens"] == 2800 and again["fits_budget"] is True
    # The RR comparison keeps its own margin.
    rr = [dict(rrrecord("mixed-fork-join", v, raw=100_000), smoke=True) for v in lr.RR_VARIANTS]
    assert lr.summarize_rr(rr, 2_500_000)["smoke"]["run_cap_margin"] == 400_000


def test_cli_passes_batch_comparison_cases_and_summarizes_batch(tmp_path, monkeypatch, capsys):
    seen = {}

    def fake_run_live(out, cases, repeats, smoke, codex_bin, author_timeout, review_timeout,
                      **kwargs):
        seen.update(cases=[c["id"] for c in cases], repeats=repeats, smoke=smoke, **kwargs)
        return {}

    monkeypatch.setattr(lr, "run_live", fake_run_live)
    monkeypatch.setattr(sys, "argv", ["live_run", "--out", str(tmp_path / "o"),
                                      "--comparison", "batch", "--budget-tokens", "2000000"])
    lr.main()
    assert seen["comparison"] == "batch" and seen["budget_tokens"] == 2_000_000
    assert seen["cases"] == ["native-chain", "sequential-delegates"] and seen["repeats"] is None
    monkeypatch.setattr(sys, "argv", ["live_run", "--out", str(tmp_path / "o"), "--smoke",
                                      "--comparison", "batch", "--budget-tokens", "2500000"])
    lr.main()
    assert "mixed-fork-join" in seen["cases"] and seen["smoke"] is True
    runs = tmp_path / "runs.jsonl"
    runs.write_text("".join(json.dumps(r) + "\n" for r in good_batch()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["live_run", "--summarize", str(runs)])
    capsys.readouterr()
    lr.main()
    out = json.loads(capsys.readouterr().out)
    assert out["comparison"] == "batch" and out["verdicts"] == {m: "better" for m in MODES}


def test_an_integration_model_call_never_carries_the_batching_paragraph(tmp_path, monkeypatch):
    original = lr.Arm.fast_check
    seen = set()

    def red_once(self, base, root, label):
        if label.startswith("I2") and self.job_id not in seen:
            seen.add(self.job_id)
            return {"unit": base, "label": label, "passed": False, "output": "red", "ts": ""}
        return original(self, base, root, label)

    monkeypatch.setattr(lr.Arm, "fast_check", red_once)
    out, _, records, _, _ = run_batch(tmp_path, monkeypatch, "native-chain")
    assert seen == {r["job_id"] for r in records} and len(records) == 2
    for record in records:
        assert record["status"] == "accepted", record["stop_reason"]
        integrations = [c for c in record["calls"] if c["kind"] == "integration"]
        assert len(integrations) == 1
        prompt = sent(out, integrations[0], "prompt.txt")
        assert prompt.startswith(lr.INTEGRATION_PROMPT) and lr.AB_PARAGRAPH not in prompt
