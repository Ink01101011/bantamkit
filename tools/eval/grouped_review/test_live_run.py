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
review = "--output-schema" in argv
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


emit({"type": "thread.started", "thread_id": thread})
if review and scn.get("fail_review"):
    sys.exit(4)
if not review and any(f in scn.get("fail_for", []) for f in files):
    sys.exit(3)
if review and bump("reviews") < scn.get("garbage_reviews", 0):
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "not json"}})
    emit({"type": "turn.completed", "usage": scn["fresh"]})
    sys.exit(0)
if review:
    request = json.loads(prompt.split("REVIEW REQUEST:\n", 1)[1])
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
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "done"}})
# Like the real CLI (probe 2026-11-13), a resumed call reports the SESSION's running
# total, not its own usage; a fresh call's total is its own. The session spends tokens
# even when this call reports none, so the total grows either way.
own = scn["resumed"] if resume else scn["fresh"]
state = Path(scn["log"] + ".total." + thread)
before = json.loads(state.read_text()) if resume and state.exists() else {}
total = {k: before.get(k, 0) + v for k, v in own.items()}
state.write_text(json.dumps(total))
if not any(f in scn.get("no_usage_for", []) for f in files):
    # per_turn_for: a call that reports its own usage, not the running total.
    per_turn = any(f in scn.get("per_turn_for", []) for f in files)
    emit({"type": "turn.completed", "usage": own if per_turn else total})
with open(scn["log"], "a") as log:
    log.write(json.dumps({"argv": argv, "cwd": str(cwd), "resume": resume, "review": review,
                          "thread": thread, "files": files}) + "\n")
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
