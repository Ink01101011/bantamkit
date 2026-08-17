import json
import math
from contextlib import contextmanager

import pytest
import yaml
from conftest import FakeClient, assistant, call

from bantamkit import evalrun
from bantamkit.agent import response_format_for
from bantamkit.assets import assets_root
from bantamkit.budget import _BudgetedClient
from bantamkit.client import BantamError, Message, Response, ToolCall, Usage
from bantamkit.contract import loop_note
from bantamkit.evalrun import (
    CONFIG_CHOICES,
    CONFIGS,
    TaskResult,
    TrackingClient,
    format_report,
    load_tasks,
    request_wire_bytes,
    run_seed,
    run_task,
    score_output,
)
from bantamkit.memory.store import MemoryStore
from bantamkit.profile import load_profile


def get_task(name):
    return next(t for t in load_tasks() if t["name"] == name)


def test_load_tasks_reads_asset_suite():
    names = {t["name"] for t in load_tasks()}
    assert {"extract-contact", "shop-total", "recall-deploy"} <= names


def test_score_json_equal():
    task = get_task("extract-contact")
    good = '{"name": "Ann Chen", "email": "ann.chen@example.com"}'
    assert score_output(task, good, []) is True
    assert score_output(task, '{"name": "Ann Chen"}', []) is False
    assert score_output(task, "not json", []) is False


def contains_task(expected):
    return {"scoring": {"kind": "contains", "expected": expected}}


def test_score_contains_case_insensitive():
    task = contains_task(["atlas"])
    assert score_output(task, "It is owned by Team ATLAS.", []) is True
    assert score_output(task, "no idea", []) is False


def test_score_contains_matches_on_word_boundaries_not_substrings():
    """`100` inside `1000` is a wrong answer, not a pass."""
    task = contains_task(["100"])
    assert score_output(task, "The total stock value is 100.", []) is True
    assert score_output(task, "The total stock value is 1000", []) is False
    assert score_output(task, "It is 4100 in total", []) is False
    assert score_output(task, "100.50 dollars", []) is True  # `.` is not a word character


def test_score_contains_allows_punctuation_and_hyphens_around_the_term():
    task = contains_task(["ship-prod"])
    assert score_output(task, "Run `make ship-prod` from the root.", []) is True
    assert score_output(task, "Run make ship-production.", []) is False


def test_score_tool_trace_subsequence():
    task = get_task("shop-compare")
    trace = [
        Message(
            role="assistant",
            tool_calls=[ToolCall(id="1", name="price_lookup", arguments={"item": "widget"})],
        ),
        Message(
            role="assistant",
            tool_calls=[ToolCall(id="2", name="price_lookup", arguments={"item": "gadget"})],
        ),
    ]
    assert score_output(task, "gadget", trace) is True
    assert score_output(task, "gadget", trace[:1]) is False


def test_tracking_client_accumulates_usage():
    inner = FakeClient([assistant(content="a"), assistant(content="b")])
    tracking = TrackingClient(inner)
    tracking.chat([Message(role="user", content="x")])
    tracking.chat([Message(role="user", content="y")])
    assert tracking.usage.prompt_tokens == 20 and tracking.usage.completion_tokens == 10


def test_run_task_bare_passes_and_counts_tokens(tmp_path):
    content = '{"name": "Ann Chen", "email": "ann.chen@example.com"}'
    client = FakeClient([assistant(content=content)])
    result = run_task(client, get_task("extract-contact"), "bare", tmp_path)
    assert result.passed is True and result.tokens == 15 and result.error is None


def test_run_task_memory_config_seeds_store(tmp_path):
    client = FakeClient(
        [
            assistant(tool_calls=[call("memory_recall", {"query": "deploy production"})]),
            assistant(content='{"command": "make ship-prod"}'),
        ]
    )
    result = run_task(client, get_task("recall-deploy"), "memory", tmp_path)
    assert result.passed is True
    # The scripted answer passes regardless, so assert the seeded fact actually came back:
    # an unseeded store answers "no memories matched" and this fails.
    recall_obs = client.calls[1]["messages"][-1].content
    assert "[deploy-command]" in recall_obs
    assert "make ship-prod" in recall_obs


def test_run_task_explicit_failure_recorded_not_raised(tmp_path):
    client = FakeClient([assistant(content="not json")] * 3)
    result = run_task(client, get_task("extract-contact"), "structured", tmp_path)
    assert result.passed is False
    assert "StructuredOutputError" in result.error


CONTACT = '{"name": "Ann Chen", "email": "ann.chen@example.com"}'
GROUNDED_VERDICT = '{"reasoning": "checked against evidence", "score": 9, "feedback": "ok"}'


def make_result(**kw):
    base = dict(
        task="t",
        config="bare",
        family="structured-extraction",
        passed=True,
        tokens=100,
        outcome="pass",
        model_calls=1,
        tool_calls=0,
        schema_retries=0,
        critique_rounds=0,
        error=None,
    )
    base.update(kw)
    return TaskResult(**base)


TINY_TASK = """\
name: tiny
family: structured-extraction
prompt: say hi
scoring:
  kind: contains
  expected: ["hi"]
"""

TINY_MEMORY_TASK = """\
name: tinymem
family: memory-recall
prompt: recall the deploy command
memory_setup:
  - type: project
    name: deploy-command
    description: how we deploy to production
    body: Deploy with make ship-prod.
scoring:
  kind: contains
  expected: ["ship-prod"]
"""


def test_load_tasks_from_custom_dir(tmp_path):
    (tmp_path / "tiny.yaml").write_text(TINY_TASK)
    tasks = evalrun.load_tasks(tmp_path)
    assert [t["name"] for t in tasks] == ["tiny"]


def test_load_tasks_empty_dir_raises(tmp_path):
    import pytest

    from bantamkit.evalrun import EvalConfigError

    with pytest.raises(EvalConfigError):
        evalrun.load_tasks(tmp_path)


def test_run_suite_repeats_and_streams_results(tmp_path):
    taskdir = tmp_path / "tasks"
    taskdir.mkdir()
    (taskdir / "tiny.yaml").write_text(TINY_TASK)
    client = FakeClient([assistant(content="hi")] * 3)
    seen = []
    results = evalrun.run_suite(
        client,
        configs=["bare"],
        workdir=tmp_path / "work",
        tasks_dir=taskdir,
        repeats=3,
        on_result=seen.append,
    )
    assert len(results) == 3
    assert seen == results
    assert all(r.passed for r in results)


def test_run_suite_repeats_reseed_memory_freshly(tmp_path):
    taskdir = tmp_path / "tasks"
    taskdir.mkdir()
    (taskdir / "tinymem.yaml").write_text(TINY_MEMORY_TASK)
    client = FakeClient(
        [
            assistant(tool_calls=[call("memory_recall", {"query": "deploy"})]),
            assistant(content="Run make ship-prod."),
        ]
        * 2
    )
    results = evalrun.run_suite(
        client, configs=["memory"], workdir=tmp_path / "work", tasks_dir=taskdir, repeats=2
    )
    assert [r.passed for r in results] == [True, True]
    assert (tmp_path / "work" / "repeat-0" / "tinymem-memory-mem").is_dir()
    assert (tmp_path / "work" / "repeat-1" / "tinymem-memory-mem").is_dir()


def test_cli_new_flags_reach_run_suite(monkeypatch, tmp_path):
    captured = {}

    def fake_run_suite(client, configs=None, tasks_dir=None, repeats=1, on_result=None):
        captured.update(configs=configs, tasks_dir=tasks_dir, repeats=repeats)
        return []

    monkeypatch.setattr(evalrun, "OpenAICompatible", lambda **kw: object())
    monkeypatch.setattr(evalrun, "run_suite", fake_run_suite)
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    evalrun.main(
        [
            "--base-url",
            "http://x",
            "--model",
            "m",
            "--repeats",
            "3",
            "--tasks",
            str(tmp_path),
        ]
    )
    assert captured["repeats"] == 3
    assert captured["tasks_dir"] == tmp_path


def test_cli_json_flag_appends_and_flushes(monkeypatch, tmp_path):
    out = tmp_path / "results.jsonl"
    out.write_text('{"task": "earlier-run"}\n')

    def fake_run_suite(client, configs=None, tasks_dir=None, repeats=1, on_result=None):
        result = make_result()
        on_result(result)
        # flushed mid-run: the line must be on disk before run_suite returns
        assert out.read_text().count("\n") == 2
        return [result]

    monkeypatch.setattr(evalrun, "OpenAICompatible", lambda **kw: object())
    monkeypatch.setattr(evalrun, "run_suite", fake_run_suite)
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    evalrun.main(["--base-url", "http://x", "--model", "m", "--json", str(out)])
    lines = out.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"task": "earlier-run"}
    data = json.loads(lines[1])
    assert data["task"] == "t" and data["outcome"] == "pass" and data["tokens"] == 100


def test_task_result_records_outcome_and_counters_on_pass(tmp_path):
    client = FakeClient([assistant(content=CONTACT)])
    result = run_task(client, get_task("extract-contact"), "bare", tmp_path)
    assert result.outcome == "pass"
    assert result.family == "structured-extraction"
    assert result.model_calls == 1
    assert result.tool_calls == 0
    assert result.schema_retries == 0 and result.critique_rounds == 0


def test_outcome_wrong_answer_vs_malformed_output(tmp_path):
    task = get_task("extract-contact")
    wrong = run_task(
        FakeClient([assistant(content='{"name": "Bob", "email": "b@x.com"}')]),
        task,
        "bare",
        tmp_path,
    )
    assert wrong.passed is False and wrong.outcome == "wrong-answer"
    malformed = run_task(FakeClient([assistant(content="no json here")]), task, "bare", tmp_path)
    assert malformed.passed is False and malformed.outcome == "malformed-output"


def test_outcome_schema_exhausted_and_retry_count_structured(tmp_path):
    client = FakeClient([assistant(content="not json")] * 3)
    result = run_task(client, get_task("extract-contact"), "structured", tmp_path)
    assert result.outcome == "schema-exhausted"
    assert result.model_calls == 3
    assert result.schema_retries == 2  # 3 attempts = 2 retries after the first


def test_schema_gate_counts_retries_in_full(tmp_path):
    client = FakeClient(
        [
            assistant(content='{"name": "Ann Chen"}'),  # missing email -> schema retry
            assistant(content=CONTACT),
            assistant(content=GROUNDED_VERDICT),
        ]
    )
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is True
    assert result.schema_retries == 1
    assert result.critique_rounds == 0
    assert result.model_calls == 3


def test_critique_rounds_counted_in_full(tmp_path):
    client = FakeClient(
        [
            assistant(content='{"name": "Ann", "email": "wrong@example.com"}'),
            assistant(
                content='{"reasoning": "wrong email", "score": 2, "feedback": "wrong email"}'
            ),
            assistant(content=CONTACT),
            assistant(content=GROUNDED_VERDICT),
        ]
    )
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is True
    assert result.critique_rounds == 1
    assert result.model_calls == 4


def test_outcome_critique_exhausted_counts_rounds(tmp_path):
    bad_verdict = '{"score": 2, "feedback": "still wrong"}'
    client = FakeClient(
        [
            assistant(content="answer one"),
            assistant(content=bad_verdict),
            assistant(content="answer two"),
            assistant(content=bad_verdict),
            assistant(content="answer three"),
            assistant(content=bad_verdict),
        ]
    )
    result = run_task(client, get_task("recall-owner"), "critique", tmp_path)
    assert result.passed is False
    assert result.outcome == "critique-exhausted"
    # Three critic calls, three rounds recorded — the column used to read 2 while the
    # error text beside it said "after 3 rounds".
    assert result.critique_rounds == 3


def test_tool_calls_counted(tmp_path):
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call("price_lookup", {"item": "widget"}),
                    call("price_lookup", {"item": "gadget"}),
                ]
            ),
            assistant(content='{"cheaper": "widget"}'),
        ]
    )
    result = run_task(client, get_task("shop-cheapest"), "bare", tmp_path)
    assert result.passed is True
    assert result.tool_calls == 2
    assert result.model_calls == 2


def test_outcome_transport_error(tmp_path):
    class Boom:
        def chat(self, messages, tools=None):
            raise BantamError("connection refused")

    result = run_task(Boom(), get_task("extract-contact"), "bare", tmp_path)
    assert result.outcome == "transport-error"
    assert "BantamError" in result.error


def test_outcome_config_error(tmp_path):
    task = {
        "name": "synthetic-schema-trace2",
        "family": "tool-use",
        "prompt": "do the thing",
        "schema": {"type": "object"},
        "scoring": {"kind": "tool_trace", "expected": ["price_lookup"]},
    }
    result = run_task(FakeClient([]), task, "structured", tmp_path)
    assert result.outcome == "config-error"


def test_structured_config_schema_task_bypasses_agent(tmp_path):
    """`structured` is unchanged: one direct structured() call, no agent, no critique."""
    client = FakeClient([assistant(content=CONTACT)])
    result = run_task(client, get_task("extract-contact"), "structured", tmp_path)
    assert result.passed is True and result.error is None
    assert len(client.calls) == 1
    system = client.calls[0]["messages"][0]
    assert system.role == "system" and "JSON Schema" in system.content


def test_structured_config_schema_with_tool_trace_scoring_is_explicit_failure(tmp_path):
    """The structured path has no transcript, so tool_trace scoring must fail loudly."""
    task = {
        "name": "synthetic-schema-trace",
        "family": "tool-use",
        "prompt": "do the thing",
        "schema": {"type": "object"},
        "scoring": {"kind": "tool_trace", "expected": ["price_lookup"]},
    }
    client = FakeClient([])
    result = run_task(client, task, "structured", tmp_path)
    assert result.passed is False
    assert "tool_trace" in result.error and "EvalConfigError" in result.error
    assert client.calls == []


def test_full_config_schema_task_runs_agent_and_critique(tmp_path):
    """`full` must exercise the agent so CritiqueGate actually participates."""
    client = FakeClient([assistant(content=CONTACT), assistant(content=GROUNDED_VERDICT)])
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is True and result.error is None
    assert len(client.calls) == 2  # agent turn + critique turn
    prompts = [m.content or "" for c in client.calls for m in c["messages"]]
    assert any("reviewer checking" in p for p in prompts)


def test_full_config_schema_task_retries_on_low_critique_score(tmp_path):
    client = FakeClient(
        [
            assistant(content='{"name": "Ann", "email": "wrong@example.com"}'),
            assistant(
                content='{"reasoning": "wrong email", "score": 2, "feedback": "wrong email"}'
            ),
            assistant(content=CONTACT),
            assistant(content=GROUNDED_VERDICT),
        ]
    )
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is True and result.error is None
    revision_prompt = client.calls[2]["messages"][-1].content
    assert "wrong email" in revision_prompt


def test_full_config_schema_violation_triggers_revision_round(tmp_path):
    """Schema parity with structured(): a violation is fed back, not scored as a loss."""
    client = FakeClient(
        [
            assistant(content='{"name": "Ann Chen"}'),  # missing email
            assistant(content=CONTACT),
            assistant(content=GROUNDED_VERDICT),
        ]
    )
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is True and result.error is None
    revision = client.calls[1]["messages"][-1].content
    assert "email" in revision and "ONLY a JSON object" in revision


def test_full_config_schema_violation_recorded_not_raised(tmp_path):
    """Same total attempt budget as structured() (3), then an explicit recorded failure."""
    client = FakeClient([assistant(content='{"name": "Ann Chen"}')] * 3)
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is False
    assert "StructuredOutputError" in result.error
    assert "3 attempts" in result.error and "email" in result.error
    assert len(client.calls) == 3  # no critique call: the schema gate runs first
    assert result.outcome == "schema-exhausted"
    assert result.schema_retries == 2


def test_full_config_non_json_output_recorded_not_raised(tmp_path):
    client = FakeClient([assistant(content="sorry, no idea")] * 3)
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is False
    assert "StructuredOutputError" in result.error and "not parseable JSON" in result.error


def test_full_config_uses_grounded_gate(tmp_path):
    client = FakeClient(
        [
            assistant(content=CONTACT),
            assistant(content=GROUNDED_VERDICT),
        ]
    )
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is True
    critic_prompt = client.calls[1]["messages"][-1].content
    assert "(no tool calls were made)" in critic_prompt


def test_format_report_has_score_per_1k():
    results = [
        make_result(task="t1", config="bare", passed=True, tokens=500),
        make_result(task="t2", config="bare", passed=False, outcome="wrong-answer", tokens=500),
        make_result(task="t1", config="full", passed=True, tokens=250),
        make_result(task="t2", config="full", passed=True, tokens=250),
    ]
    report = format_report(results)
    assert "score/1k tok" in report
    assert "| bare" in report and "| full" in report
    assert "1/2" in report and "2/2" in report


def test_lean_config_schema_task_uses_schema_gate_without_critique(tmp_path):
    task = {
        "name": "t",
        "family": "structured-extraction",
        "prompt": "extract",
        "schema": {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
        "scoring": {"kind": "json_equal", "expected": {"a": 1}},
    }
    client = FakeClient([assistant(content='{"a": 1}')])
    result = run_task(client, task, "lean", tmp_path)
    assert result.passed is True
    assert len(client.calls) == 1  # no critique-scoring call
    joined = " ".join(m.content or "" for call in client.calls for m in call["messages"])
    assert "strict reviewer" not in joined and "reviewer" not in joined.lower()
    assert any("JSON Schema" in (m.content or "") for m in client.calls[0]["messages"])


def test_lean_config_schema_violation_gets_revision_round(tmp_path):
    task = {
        "name": "t",
        "family": "structured-extraction",
        "prompt": "extract",
        "schema": {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
        "scoring": {"kind": "json_equal", "expected": {"a": 1}},
    }
    client = FakeClient([assistant(content="not json"), assistant(content='{"a": 1}')])
    result = run_task(client, task, "lean", tmp_path)
    assert result.passed is True
    assert len(client.calls) == 2
    assert "not parseable" in client.calls[1]["messages"][-1].content


def test_lean_config_seeds_memory_store(tmp_path):
    task = {
        "name": "t",
        "family": "memory-recall",
        "prompt": "recall the deploy command",
        "memory_setup": [
            {
                "type": "project",
                "name": "deploy-command",
                "description": "how we deploy to production",
                "body": "Deploy with make ship-prod.",
            }
        ],
        "scoring": {"kind": "contains", "expected": ["ship-prod"]},
    }
    client = FakeClient(
        [
            assistant(tool_calls=[call("memory_recall", {"query": "deploy command"})]),
            assistant(content="Run make ship-prod."),
        ]
    )
    result = run_task(client, task, "lean", tmp_path)
    assert result.passed is True
    observation = client.calls[1]["messages"][-1].content
    assert "ship-prod" in observation  # recall actually hit the seeded store


def test_configs_matrix():
    expected = ["bare", "structured", "critique", "grounded", "graph", "memory", "lean", "full"]
    assert CONFIGS == expected


def test_cli_timeout_flag_reaches_client(monkeypatch):
    """Custom timeout flag is passed to OpenAICompatible constructor."""
    captured = {}

    class FakeAdapter:
        def __init__(self, base_url, model, timeout):
            captured["base_url"] = base_url
            captured["model"] = model
            captured["timeout"] = timeout

    monkeypatch.setattr(evalrun, "OpenAICompatible", FakeAdapter)
    monkeypatch.setattr(evalrun, "run_suite", lambda client, **kw: [])
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    evalrun.main(["--base-url", "http://x", "--model", "m", "--timeout", "120.5"])
    assert captured["base_url"] == "http://x"
    assert captured["model"] == "m"
    assert captured["timeout"] == 120.5


def test_cli_timeout_flag_default_value(monkeypatch):
    """Timeout defaults to 60.0 when not specified."""
    captured = {}

    class FakeAdapter:
        def __init__(self, base_url, model, timeout):
            captured["base_url"] = base_url
            captured["model"] = model
            captured["timeout"] = timeout

    monkeypatch.setattr(evalrun, "OpenAICompatible", FakeAdapter)
    monkeypatch.setattr(evalrun, "run_suite", lambda client, **kw: [])
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    evalrun.main(["--base-url", "http://x", "--model", "m"])
    assert captured["base_url"] == "http://x"
    assert captured["model"] == "m"
    assert captured["timeout"] == 60.0


def test_all_memory_setups_seed_without_jaccard_collisions(tmp_path):
    """save() silently returns 'duplicate' on similar facts — a task file that trips it
    would seed an incomplete store and fail mysteriously only at eval time."""
    seeded = 0
    for task in load_tasks():
        facts = task.get("memory_setup") or []
        store = MemoryStore(tmp_path / task["name"])
        for fact in facts:
            result = store.save(fact["type"], fact["name"], fact["description"], fact["body"])
            seeded += 1
            assert result.status == "saved", (
                f"task '{task['name']}': fact '{fact['name']}' collides with "
                f"'{result.similar}' — make descriptions more distinct"
            )
    assert seeded >= 15  # exactly 15 facts today (9 recall tasks); adjust when retiring


def test_missing_family_is_config_error(tmp_path):
    task = {"name": "nofam", "prompt": "hi", "scoring": {"kind": "contains", "expected": ["hi"]}}
    result = run_task(FakeClient([]), task, "bare", tmp_path)
    assert result.passed is False
    assert result.outcome == "config-error"
    assert result.family == "unknown"
    assert "family" in result.error


def test_outcome_wrong_answer_for_contains_task(tmp_path):
    result = run_task(
        FakeClient([assistant(content="I have no idea what the total is")]),
        get_task("shop-total"),
        "bare",
        tmp_path,
    )
    assert result.passed is False and result.outcome == "wrong-answer"


def test_gate_counters_reset_per_attach():
    from bantamkit.critique import CritiqueGate
    from bantamkit.evalrun import SchemaGate

    class StubAgent:
        def add_post_hook(self, hook):
            pass

    schema_gate = SchemaGate({"type": "object"})
    schema_gate.retries_used = 5
    schema_gate.setup(StubAgent())
    assert schema_gate.retries_used == 0

    critique_gate = CritiqueGate("task-completion", client=FakeClient([]))
    critique_gate.rounds_used = 3
    critique_gate.setup(StubAgent())
    assert critique_gate.rounds_used == 0


def test_cli_repeats_zero_rejected(monkeypatch):
    import pytest

    monkeypatch.setattr(evalrun, "OpenAICompatible", lambda **kw: object())
    monkeypatch.setattr(evalrun, "run_suite", lambda client, **kw: [])
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    with pytest.raises(SystemExit):
        evalrun.main(["--base-url", "http://x", "--model", "m", "--repeats", "0"])


def test_format_report_family_table():
    results = [
        make_result(task="e1", config="bare", passed=True, tokens=100),
        make_result(
            task="m1",
            config="bare",
            family="memory-recall",
            passed=False,
            outcome="wrong-answer",
            tokens=50,
        ),
        make_result(task="e1", config="full", passed=True, tokens=200),
        make_result(task="m1", config="full", family="memory-recall", passed=True, tokens=300),
    ]
    report = format_report(results)
    assert "Per family (score · tokens):" in report
    assert "memory-recall" in report and "structured-extraction" in report
    assert "0/1 · 50 tok" in report
    assert "1/1 · 300 tok" in report


def test_format_report_family_table_omitted_for_single_family():
    report = format_report([make_result()])
    assert "Per family" not in report


def test_format_report_outcome_histogram():
    results = [
        make_result(task="a", passed=False, outcome="wrong-answer"),
        make_result(task="b", passed=False, outcome="wrong-answer"),
        make_result(task="c", passed=False, outcome="malformed-output"),
        make_result(task="d", passed=True),
    ]
    report = format_report(results)
    assert "Failure outcomes:" in report
    assert "- bare: malformed-output ×1, wrong-answer ×2" in report


def test_format_report_rescue_matrix_counts_discriminating():
    results = [
        # e1: passes everywhere -> excluded from the matrix entirely
        make_result(task="e1", config="bare", passed=True),
        make_result(task="e1", config="full", passed=True),
        # m1: bare fails, full passes -> discriminating
        make_result(task="m1", config="bare", passed=False, outcome="wrong-answer"),
        make_result(task="m1", config="full", passed=True),
        # m2: fails everywhere -> shown in the matrix but NOT discriminating
        make_result(task="m2", config="bare", passed=False, outcome="wrong-answer"),
        make_result(task="m2", config="full", passed=False, outcome="wrong-answer"),
    ]
    report = format_report(results)
    assert "Discriminating tasks: 1/3" in report
    matrix = report.split("Discriminating tasks:")[1]
    assert "| m1 | 0/1 | 1/1 |" in matrix
    assert "| m2 | 0/1 | 0/1 |" in matrix
    assert "| e1 |" not in matrix


def test_format_report_rescue_matrix_shows_repeat_fractions():
    results = (
        [make_result(task="m1", config="bare", passed=False, outcome="wrong-answer")] * 2
        + [make_result(task="m1", config="bare", passed=True)]
        + [make_result(task="m1", config="full", passed=True)] * 3
    )
    report = format_report(results)
    assert "| m1 | 1/3 | 3/3 |" in report
    # 1/3 < 3/3 but bare did pass once: not fully-failed, so not "discriminating"
    assert "Discriminating tasks: 0/1" in report


def test_format_report_no_matrix_for_single_config():
    report = format_report([make_result(passed=False, outcome="wrong-answer")])
    assert "Discriminating" not in report


def test_format_report_section_order():
    results = [
        make_result(task="e1", config="bare", passed=True),
        make_result(
            task="m1",
            config="bare",
            family="memory-recall",
            passed=False,
            outcome="wrong-answer",
        ),
        make_result(task="e1", config="full", passed=True),
        make_result(
            task="m1",
            config="full",
            family="memory-recall",
            passed=False,
            outcome="critique-exhausted",
            error="CritiqueExhausted: below threshold",
        ),
    ]
    report = format_report(results)
    markers = [
        "| config | score | tokens | score/1k tok |",
        "Per family (score · tokens):",
        "Failure outcomes:",
        "Discriminating tasks:",
        "Explicit failures:",
    ]
    positions = [report.index(m) for m in markers]
    assert positions == sorted(positions)


def test_format_report_config_rows_follow_configs_order():
    results = [
        make_result(task="t1", config="critique", passed=True),
        make_result(task="t1", config="structured", passed=True),
    ]
    report = format_report(results)
    assert report.index("| structured |") < report.index("| critique |")


def test_format_report_family_cells_align_with_columns():
    results = [
        make_result(task="e1", config="bare", passed=True, tokens=100),
        make_result(
            task="m1",
            config="bare",
            family="memory-recall",
            passed=False,
            outcome="wrong-answer",
            tokens=50,
        ),
        make_result(task="e1", config="full", passed=True, tokens=200),
        make_result(task="m1", config="full", family="memory-recall", passed=True, tokens=300),
    ]
    report = format_report(results)
    assert "| config | memory-recall | structured-extraction |" in report
    assert "| bare | 0/1 · 50 tok | 1/1 · 100 tok |" in report
    assert "| full | 1/1 · 300 tok | 1/1 · 200 tok |" in report


def test_format_report_all_pass_still_prints_zero_headline():
    results = [
        make_result(task="e1", config="bare", passed=True),
        make_result(task="e1", config="full", passed=True),
    ]
    report = format_report(results)
    assert "Discriminating tasks: 0/1" in report


def test_classify_outcome_returns_only_documented_outcomes(tmp_path):
    from bantamkit.critique import CritiqueExhausted
    from bantamkit.evalrun import OUTCOMES, EvalConfigError, classify_outcome
    from bantamkit.structured import StructuredOutputError

    task_json = {"scoring": {"kind": "json_equal", "expected": {}}}
    task_txt = {"scoring": {"kind": "contains", "expected": ["x"]}}
    cases = [
        classify_outcome(task_txt, True, "x", None),
        classify_outcome(task_txt, False, "nope", None),
        classify_outcome(task_json, False, "not json", None),
        classify_outcome(task_json, False, None, StructuredOutputError("s")),
        classify_outcome(task_json, False, None, CritiqueExhausted("c")),
        classify_outcome(task_json, False, None, EvalConfigError("e")),
        classify_outcome(task_json, False, None, BantamError("t")),
    ]
    assert cases == [
        "pass",
        "wrong-answer",
        "malformed-output",
        "schema-exhausted",
        "critique-exhausted",
        "config-error",
        "transport-error",
    ]
    assert set(cases) <= set(OUTCOMES)


def test_score_contains_rejects_comma_grouped_superstrings():
    task = contains_task(["200"])
    assert score_output(task, "The quota is 200 requests per minute.", []) is True
    assert score_output(task, "It handles 1,200 requests per minute.", []) is False
    assert score_output(task, "About 200, give or take.", []) is True


def test_configs_include_grounded_after_critique():
    assert "grounded" in CONFIGS
    assert CONFIGS.index("grounded") == CONFIGS.index("critique") + 1


def test_grounded_config_critic_sees_tool_evidence(tmp_path):
    # shop-total: tools [price_lookup, stock_lookup], contains scoring on "100"
    client = FakeClient(
        [
            assistant(
                tool_calls=[ToolCall(id="c1", name="price_lookup", arguments={"item": "widget"})]
            ),
            assistant(content='{"total": 999}'),
            assistant(
                content='{"reasoning": "widget costs 25, not 999", '
                '"score": 2, "feedback": "evidence says widget costs 25"}'
            ),
            assistant(content='{"total": 100}'),
            assistant(
                content='{"reasoning": "matches evidence", "score": 9, "feedback": "consistent"}'
            ),
        ]
    )
    result = run_task(client, get_task("shop-total"), "grounded", tmp_path)
    assert result.critique_rounds == 1
    critic_prompt = client.calls[2]["messages"][-1].content
    assert 'price_lookup({"item": "widget"})' in critic_prompt
    assert result.passed is True


def workspace_task(**overrides):
    task = {
        "name": "nav-fixture",
        "family": "file-nav",
        "tools": ["read_file", "list_files"],
        "workspace": {"notes/a.md": "alpha", "b.txt": "bravo"},
        "prompt": 'Answer with ONLY this JSON, nothing else: {"x": 1}',
        "scoring": {"kind": "json_equal", "expected": {"x": 1}},
    }
    task.update(overrides)
    return task


def test_workspace_read_file_and_list_files(tmp_path):
    client = FakeClient(
        [
            assistant(tool_calls=[call("list_files", {})]),
            assistant(tool_calls=[call("read_file", {"path": "notes/a.md"}, id="c2")]),
            assistant(content='{"x": 1}'),
        ]
    )
    result = run_task(client, workspace_task(), "bare", tmp_path)
    assert result.passed is True
    listing = client.calls[1]["messages"][-1].content
    assert "b.txt" in listing and "notes/a.md" in listing
    assert client.calls[2]["messages"][-1].content == "alpha"


def test_workspace_read_file_unknown_path_error(tmp_path):
    client = FakeClient(
        [
            assistant(tool_calls=[call("read_file", {"path": "nope.txt"})]),
            assistant(content='{"x": 1}'),
        ]
    )
    run_task(client, workspace_task(), "bare", tmp_path)
    obs = client.calls[1]["messages"][-1].content
    assert obs.startswith("error: unknown file 'nope.txt'")
    assert "b.txt" in obs and "notes/a.md" in obs


def test_graph_config_collapses_repeat_read(tmp_path):
    client = FakeClient(
        [
            assistant(tool_calls=[call("read_file", {"path": "notes/a.md"})]),
            assistant(tool_calls=[call("read_file", {"path": "notes/a.md"}, id="c2")]),
            assistant(content='{"x": 1}'),
        ]
    )
    result = run_task(client, workspace_task(), "graph", tmp_path)
    assert result.passed is True
    assert client.calls[1]["messages"][-1].content == "alpha"
    second = client.calls[2]["messages"][-1].content
    assert second.startswith("[file-graph]") and "alpha" not in second
    assert "file_graph" in [t.name for t in client.calls[0]["tools"]]


def test_graph_annotate_ablation_annotates_without_collapsing(tmp_path):
    """The calibration signal: cache=False keeps full content, query=False no file_graph tool."""
    client = FakeClient(
        [
            assistant(tool_calls=[call("read_file", {"path": "notes/a.md"})]),
            assistant(tool_calls=[call("read_file", {"path": "notes/a.md"}, id="c2")]),
            assistant(content='{"x": 1}'),
        ]
    )
    result = run_task(client, workspace_task(), "graph-annotate", tmp_path)
    assert result.passed is True
    second = client.calls[2]["messages"][-1].content
    assert second.startswith("[file-graph]") and second.endswith("alpha")
    assert "file_graph" not in [t.name for t in client.calls[0]["tools"]]


def test_graph_config_is_noop_without_workspace_tools(tmp_path):
    client = FakeClient([assistant(content="The total stock value is 100.")])
    result = run_task(client, get_task("shop-total"), "graph", tmp_path)
    assert result.passed is True
    assert "file_graph" not in [t.name for t in client.calls[0]["tools"]]


def test_graph_config_in_configs():
    assert "graph" in CONFIGS


RECALL_TASKS = sorted(t["name"] for t in load_tasks() if t["family"] == "memory-recall")
assert len(RECALL_TASKS) >= 9, "memory-recall family shrank below 9"


@pytest.mark.parametrize("name", RECALL_TASKS)
def test_recall_tasks_score_json_equal(name):
    """Dump-the-store answers must not pass: recall tasks demand an exact JSON answer."""
    task = get_task(name)
    assert task["scoring"]["kind"] == "json_equal"
    assert "Answer with ONLY this JSON" in task["prompt"]


def test_recall_store_dump_containing_the_fact_scores_false():
    """The failure mode the conversion kills: a dump that contains the right fact is not a pass."""
    task = get_task("recall-owner")
    dump = "[service-owner] The checkout service is owned by Team Atlas. [db-port] port 5433."
    assert score_output(task, dump, []) is False
    assert score_output(task, '{"team": "Atlas"}', []) is True


def test_ablation_configs_are_choices_but_not_in_configs():
    assert "graph-annotate" in CONFIG_CHOICES and "graph-cache" in CONFIG_CHOICES
    assert "graph-annotate" not in CONFIGS and "graph-cache" not in CONFIGS
    assert "graph-off" in CONFIG_CHOICES and "graph-off" not in CONFIGS


def _repeat_read_trajectory():
    return [
        assistant(tool_calls=[call("list_files", {})]),
        assistant(tool_calls=[call("read_file", {"path": "notes/a.md"}, id="c2")]),
        assistant(tool_calls=[call("read_file", {"path": "notes/a.md"}, id="c3")]),
        assistant(content='{"x": 1}'),
    ]


def test_graph_off_observations_are_identical_to_bare(tmp_path):
    """The null control: `graph-off` records the ledger and changes nothing sent.

    This is the arm the token-reduction bar is written against
    (docs/eval-data/2026-08-17-devteam-bar-preregistration.md), so it has to be
    meaning-preserving in the literal sense — byte-identical observations and no
    extra tool. Falsifying mutation: flip `cache` or `query` True in
    GRAPH_CONFIGS["graph-off"] and this node goes red.
    """
    bare = FakeClient(_repeat_read_trajectory())
    off = FakeClient(_repeat_read_trajectory())
    bare_result = run_task(bare, workspace_task(), "bare", tmp_path)
    off_result = run_task(off, workspace_task(), "graph-off", tmp_path)
    assert bare_result.passed is off_result.passed is True
    def observations(client):
        return [[m.content for m in c["messages"] if m.role == "tool"] for c in client.calls]

    bare_obs, off_obs = observations(bare), observations(off)
    assert off_obs == bare_obs
    # The repeat read is NOT collapsed: full content both times, no marker anywhere.
    assert off_obs[-1] == ["b.txt\nnotes/a.md", "alpha", "alpha"]
    assert not any("[file-graph]" in obs for turn in off_obs for obs in turn)
    for client in (bare, off):
        assert "file_graph" not in [t.name for t in client.calls[0]["tools"]]


def test_devteam_workload_asset_loads_and_declares_a_repo_surface():
    """Regression guard on the new asset, not evidence about it (RB-P28 stays open).

    The workload lives beside the frozen suite and is loaded through the same
    `--tasks` path. What this pins is that it stays loadable, that every task keeps
    the workspace tools the graph attaches on (`evalrun.py:535`), and that all eight
    share one identical surface — a task whose workspace drifted would be a
    different workload wearing the same name.
    """
    tasks = load_tasks(assets_root() / "evals" / "devteam" / "tasks")
    assert len(tasks) == 8
    assert {t["family"] for t in tasks} == {"dev-repo-code", "dev-repo-history"}
    surfaces = set()
    for task in tasks:
        assert task["tools"] == ["read_file", "list_files"]
        assert task["scoring"]["kind"] == "json_equal"
        surfaces.add(tuple(sorted(task["workspace"])))
    assert len(surfaces) == 1
    paths = surfaces.pop()
    assert sum(p.endswith(".py") for p in paths) >= 8  # code, which the frozen suite has none of
    assert any(p.endswith(".patch") for p in paths)  # a diff
    assert "HISTORY.md" in paths  # history


DEVTEAM = assets_root() / "evals" / "devteam"


def _devteam_manifest():
    return yaml.safe_load((DEVTEAM / "manifest.yaml").read_text())


@pytest.mark.parametrize("arm", ["graph-off", "graph-annotate", "graph-cache", "graph"])
def test_devteam_reference_walk_scores_under_every_ladder_arm(arm, tmp_path):
    """All four pre-registered arms plumb onto the workload, and its walks answer it.

    Not evidence about the mechanism — no model is called; a FakeClient replays each
    task's committed reference walk. What it guards is that the arms M4 is briefed to
    run actually attach to these tasks, and that every task is answerable from the
    surface by the walk the manifest declares. A task that stopped scoring here would
    mean the surface and the walk had drifted apart.
    """
    tasks = {t["name"]: t for t in load_tasks(DEVTEAM / "tasks")}
    for spec in _devteam_manifest()["tasks"]:
        task = tasks[spec["name"]]
        needs_list = "list_files" in task["prompt"] or any(
            hop.get("pointer_in") == "listing" for hop in spec["walk"]
        )
        replies = [assistant(tool_calls=[call("list_files", {})])] if needs_list else []
        replies += [
            assistant(tool_calls=[call("read_file", {"path": hop["path"]}, id=f"c{i}")])
            for i, hop in enumerate(spec["walk"])
        ]
        replies.append(assistant(content=json.dumps(task["scoring"]["expected"])))
        result = run_task(FakeClient(replies), task, arm, tmp_path / spec["name"])
        assert result.passed, (spec["name"], arm, result.outcome, result.error)


def test_graph_off_token_count_matches_bare(tmp_path):
    """Same trajectory, same tokens: the null control costs nothing to attach."""
    bare = run_task(FakeClient(_repeat_read_trajectory()), workspace_task(), "bare", tmp_path)
    off = run_task(FakeClient(_repeat_read_trajectory()), workspace_task(), "graph-off", tmp_path)
    assert off.tokens == bare.tokens
    assert (off.model_calls, off.tool_calls) == (bare.model_calls, bare.tool_calls)


class _PayloadSensitiveClient:
    """Scripted client whose `Usage` is a FUNCTION OF THE REQUEST, not a constant.

    `conftest.FakeClient` returns a fixed `Usage` regardless of what the observation
    contains, so no in-process token figure can move when the observation moves. That
    is why the token half of the `graph-off` null-control claim was recorded UNPINNED
    (`docs/eval-data/2026-08-17-devteam-bar-preregistration.md` §9/A1): the assertion
    `off.tokens == bare.tokens` was true by construction of the double.

    Here `prompt_tokens` is `ceil(bytes/4)` over the payload `OpenAICompatible.chat`
    serializes (`client.py:155-161`), so it moves whenever the observations, the tool
    roster or the system prompt move. A surrogate for an endpoint's tokenizer, not a
    tokenizer — the assumption is the workload doc's Table 5b assumption, tokens
    monotone in bytes. The field measurement is
    `docs/eval-data/2026-08-17-devteam-null-control-field-measurement.py`; this node is
    the regression guard, and RB-P28 stays open.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.prompt_tokens_per_call = []

    def chat(self, messages, tools=None):
        payload = {
            "messages": [m.to_wire() for m in messages],
            "tools": [t.to_wire() for t in (tools or [])],
        }
        self.calls.append(payload)
        prompt_tokens = math.ceil(len(json.dumps(payload).encode()) / 4)
        self.prompt_tokens_per_call.append(prompt_tokens)
        reply = self.responses.pop(0)
        completion = reply.message.content or json.dumps(
            [tc.arguments for tc in reply.message.tool_calls]
        )
        return Response(
            message=reply.message,
            usage=Usage(prompt_tokens, math.ceil(len(completion.encode()) / 4)),
        )


def test_graph_off_token_count_is_pinned_by_a_payload_sensitive_client(tmp_path):
    """The token half of the null control, pinned on a quantity that can actually move.

    Falsifying mutation: flip `cache`, `annotate` or `query` True in
    GRAPH_CONFIGS["graph-off"] and THIS node goes red on the token assertion —
    `cache` collapses the repeat read (fewer bytes), `annotate` prepends a marker
    (more bytes), `query` adds the `file_graph` tool and the skill (more bytes).
    `::test_graph_off_token_count_matches_bare` cannot: its client's `Usage` is fixed.
    """
    bare = _PayloadSensitiveClient(_repeat_read_trajectory())
    off = _PayloadSensitiveClient(_repeat_read_trajectory())
    bare_result = run_task(bare, workspace_task(), "bare", tmp_path)
    off_result = run_task(off, workspace_task(), "graph-off", tmp_path)
    # First: the instrument. A client whose usage does not respond to the payload
    # would make the assertion below vacuous, which is the defect being closed —
    # so the sensitivity is asserted, not assumed (RB-P14 Gate 2: test the instrument).
    assert len(set(bare.prompt_tokens_per_call)) == len(bare.prompt_tokens_per_call)
    assert bare.prompt_tokens_per_call == sorted(bare.prompt_tokens_per_call)
    # Then the claim: the null control costs nothing a payload-derived counter can see.
    assert off_result.tokens == bare_result.tokens
    assert off.prompt_tokens_per_call == bare.prompt_tokens_per_call


# ---- M3.5: bar §8's accounting columns, pinned as an INSTRUMENT ----
#
# RB-P14 Gate 2: an acceptance criterion may not assert a fact about the world. So no
# node below asserts that some workload has some number of repeat reads — pinning the
# asset would turn red the first time the workload changed honestly. What is pinned is
# the instrument: that the recorded column equals what the ledger holds, and that it
# MOVES when the ledger moves. The workload's actual counts live in the field report,
# docs/eval-data/2026-08-17-devteam-accounting-grain.md, and RB-P28 stays open.


@contextmanager
def _captured_graphs():
    """Reach the `FileAccessGraph` instances a run builds, as the reference to check against.

    The accounting columns are the delivery route under test; this is the ledger they
    are compared with. Observation-only subclass — the same device M3's field program
    used when it was the ONLY route (bar §7.2) — so the run it watches is the run that
    would have happened anyway.
    """
    seen: list = []
    original = evalrun.FileAccessGraph

    class Capturing(original):  # type: ignore[misc,valid-type]
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            seen.append(self)

    evalrun.FileAccessGraph = Capturing
    try:
        yield seen
    finally:
        evalrun.FileAccessGraph = original


def _read_same_file_n_times(n):
    return [
        assistant(tool_calls=[call("read_file", {"path": "notes/a.md"}, id=f"c{i}")])
        for i in range(n)
    ] + [assistant(content='{"x": 1}')]


def test_accounting_columns_equal_the_ledger_the_run_built(tmp_path):
    """The count survives the run: what the row carries is what the ledger held.

    Falsifying mutation: drop `repeat_reader_calls=accounting.repeat_reader_calls` from
    the `TaskResult(...)` construction in `run_task` — i.e. discard the ledger again,
    which is the defect this unit exists to fix — and this node goes red on
    `assert result.repeat_reader_calls == ledger_repeats`.
    """
    with _captured_graphs() as seen:
        result = run_task(FakeClient(_read_same_file_n_times(3)), workspace_task(), "graph-off",
                          tmp_path)
    (graph,) = seen
    ledger_reads = sum(r.count for r in graph.reads.values())
    ledger_repeats = sum(r.count - 1 for r in graph.reads.values())
    # Not vacuous: the fixture makes the ledger say something non-zero. This is a fact
    # about the fixture built three lines up, not a fact about a committed asset.
    assert ledger_repeats > 0
    assert result.reader_calls - result.unrecorded_reader_calls == ledger_reads
    assert result.repeat_reader_calls == ledger_repeats
    assert result.reader_calls == graph.accounting.reader_calls
    assert result.collapsed_calls == graph.accounting.collapsed_calls == 0  # graph-off
    assert result.collapsed_bytes == result.annotate_marker_bytes == result.query_bytes == 0


def test_accounting_columns_move_when_the_ledger_moves(tmp_path):
    """The instrument responds. A column that could not move would pin nothing."""
    seen_counts = {}
    for n in (2, 5):
        with _captured_graphs() as seen:
            result = run_task(FakeClient(_read_same_file_n_times(n)), workspace_task(),
                              "graph-off", tmp_path / f"reads-{n}")
        (graph,) = seen
        seen_counts[n] = (
            result.repeat_reader_calls,
            sum(r.count - 1 for r in graph.reads.values()),
        )
    assert seen_counts[2][0] == seen_counts[2][1]
    assert seen_counts[5][0] == seen_counts[5][1]
    assert seen_counts[5][0] > seen_counts[2][0]


def test_collapsed_columns_track_the_arm_that_can_collapse(tmp_path):
    """Column 3 answers "did the mechanism FIRE", which column 2 alone cannot.

    Bar §5 R3 needs both: a task can realise repeats (column 2 > 0) under an arm that
    cannot act on them (column 3 == 0), and telling those apart is the whole difference
    between a refutation and an UNINFORMATIVE run. No arm delta is computed here — the
    two rows are not compared on tokens.
    """
    with _captured_graphs() as seen:
        cached = run_task(FakeClient(_read_same_file_n_times(3)), workspace_task(), "graph-cache",
                          tmp_path / "cache")
    (graph,) = seen
    assert cached.repeat_reader_calls == graph.accounting.repeat_reader_calls > 0
    assert cached.collapsed_calls == graph.accounting.collapsed_calls == cached.repeat_reader_calls
    assert cached.collapsed_bytes == graph.accounting.collapsed_bytes

    off = run_task(FakeClient(_read_same_file_n_times(3)), workspace_task(), "graph-off",
                   tmp_path / "off")
    assert off.repeat_reader_calls == cached.repeat_reader_calls  # same opportunity
    assert off.collapsed_calls == 0  # no firing


def test_unrecorded_reader_calls_carry_the_failed_reads(tmp_path):
    """The `error:` gap, now visible in the row instead of missing from the denominator."""
    client = FakeClient(
        [
            assistant(tool_calls=[call("read_file", {"path": "nope.txt"}, id="c1")]),
            assistant(tool_calls=[call("read_file", {"path": "notes/a.md"}, id="c2")]),
            assistant(content='{"x": 1}'),
        ]
    )
    with _captured_graphs() as seen:
        result = run_task(client, workspace_task(), "graph-off", tmp_path)
    (graph,) = seen
    assert result.reader_calls == 2
    assert result.unrecorded_reader_calls == 1
    assert result.reader_calls - result.unrecorded_reader_calls == sum(
        r.count for r in graph.reads.values()
    )


def test_context_bytes_sent_equals_the_serialized_requests(tmp_path):
    """Column 7, pinned against the serializer it mirrors, call for call."""
    client = FakeClient(_read_same_file_n_times(2))
    result = run_task(client, workspace_task(), "graph-off", tmp_path)
    per_call = [request_wire_bytes(c["messages"], c["tools"]) for c in client.calls]
    assert result.model_calls == len(client.calls)
    assert result.context_bytes_sent == sum(per_call)
    # The re-send weighting is the point: the transcript grows, so every call costs more
    # than the one before it. A counter that read a single request would not show this.
    assert per_call == sorted(per_call) and len(set(per_call)) == len(per_call)


def test_accounting_columns_are_zero_when_no_graph_is_attached(tmp_path):
    """A `bare` row's zeros mean "no ledger existed", not "the ledger measured zero"."""
    result = run_task(
        FakeClient([assistant(content=CONTACT)]), get_task("extract-contact"), "bare", tmp_path
    )
    assert (result.reader_calls, result.repeat_reader_calls, result.collapsed_calls) == (0, 0, 0)
    assert result.context_bytes_sent > 0  # column 7 needs no graph


def test_accounting_columns_reach_the_jsonl_row(monkeypatch, tmp_path):
    """The route bar §7.2 said did not exist: `--json` now carries the realised count."""
    out = tmp_path / "results.jsonl"

    def fake_run_suite(client, configs=None, tasks_dir=None, repeats=1, on_result=None):
        on_result(make_result(config="graph-off", reader_calls=5, repeat_reader_calls=2))
        return []

    monkeypatch.setattr(evalrun, "OpenAICompatible", lambda **kw: object())
    monkeypatch.setattr(evalrun, "run_suite", fake_run_suite)
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    evalrun.main(["--base-url", "http://x", "--model", "m", "--json", str(out)])
    row = json.loads(out.read_text().splitlines()[0])
    assert (row["reader_calls"], row["repeat_reader_calls"]) == (5, 2)
    assert set(row) >= {
        "reader_calls",
        "unrecorded_reader_calls",
        "repeat_reader_calls",
        "collapsed_calls",
        "collapsed_bytes",
        "annotate_marker_bytes",
        "query_bytes",
        "context_bytes_sent",
    }


# ---- P7: turns-exhausted ----


def test_outcome_turns_exhausted_not_transport_error(tmp_path):
    """Turn exhaustion is agent behaviour; filing it under transport blames the server."""

    class NeverAnswers:
        """Always calls a tool, never gives a final answer — the agent runs out of turns."""

        def chat(self, messages, tools=None):
            return assistant(tool_calls=[call("price_lookup", {"item": "widget"})])

    result = run_task(NeverAnswers(), get_task("shop-cheapest"), "bare", tmp_path)
    assert result.passed is False
    assert result.outcome == "turns-exhausted"
    assert "MaxTurnsExceeded" in result.error


def test_outcome_transport_error_still_classifies_transport(tmp_path):
    from bantamkit.client import TransportError

    class Boom:
        def chat(self, messages, tools=None):
            raise TransportError("chat failed after 3 attempts")

    result = run_task(Boom(), get_task("extract-contact"), "bare", tmp_path)
    assert result.outcome == "transport-error"


def test_classify_outcome_maps_max_turns_to_its_own_bucket():
    from bantamkit.agent import MaxTurnsExceeded
    from bantamkit.evalrun import OUTCOMES, classify_outcome

    task = {"scoring": {"kind": "contains", "expected": ["x"]}}
    outcome = classify_outcome(task, False, None, MaxTurnsExceeded("no final answer"))
    assert outcome == "turns-exhausted"
    assert outcome in OUTCOMES


# ---- P8: --transcripts ----


def read_transcript(directory, config, task, repeat=0):
    return json.loads((directory / f"{config}--{task}--r{repeat}.json").read_text())


def test_transcript_written_with_run_fields(tmp_path):
    transcripts = tmp_path / "t"
    transcripts.mkdir()
    client = FakeClient([assistant(content=CONTACT)])
    result = run_task(
        client, get_task("extract-contact"), "bare", tmp_path, transcripts_dir=transcripts
    )
    data = read_transcript(transcripts, "bare", "extract-contact")
    assert data["task"] == "extract-contact" and data["config"] == "bare"
    assert data["repeat"] == 0
    assert data["passed"] is result.passed is True
    assert data["outcome"] == result.outcome == "pass"
    assert data["output"] == CONTACT
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    assert data["messages"][-1]["content"] == CONTACT


def test_transcript_records_tool_calls_and_repeat_index(tmp_path):
    transcripts = tmp_path / "t"
    transcripts.mkdir()
    client = FakeClient(
        [
            assistant(tool_calls=[call("price_lookup", {"item": "widget"})]),
            assistant(content='{"cheaper": "widget"}'),
        ]
    )
    run_task(
        client,
        get_task("shop-cheapest"),
        "bare",
        tmp_path,
        transcripts_dir=transcripts,
        repeat=2,
    )
    data = read_transcript(transcripts, "bare", "shop-cheapest", repeat=2)
    assert data["repeat"] == 2
    tool_calls = [tc for m in data["messages"] for tc in m["tool_calls"]]
    assert tool_calls == [{"id": "c1", "name": "price_lookup", "arguments": {"item": "widget"}}]
    observation = next(m for m in data["messages"] if m["role"] == "tool")
    assert observation["tool_call_id"] == "c1"


def test_transcript_written_for_gate_raising_run(tmp_path):
    transcripts = tmp_path / "t"
    transcripts.mkdir()
    client = FakeClient([assistant(content="not json")] * 3)
    result = run_task(
        client,
        get_task("extract-contact"),
        "structured",
        tmp_path,
        transcripts_dir=transcripts,
    )
    data = read_transcript(transcripts, "structured", "extract-contact")
    assert result.passed is False
    assert data["passed"] is False and data["outcome"] == "schema-exhausted"
    assert data["output"] is None
    # structured() drives its own loop: documented limitation, but the file still exists.
    assert data["messages"] == []


def test_transcript_write_failure_does_not_change_the_result(tmp_path, capsys):
    """Measurement must not change what it measures: an unwritable dir only warns."""
    missing = tmp_path / "nope" / "deeper"
    client = FakeClient([assistant(content=CONTACT)])
    result = run_task(
        client, get_task("extract-contact"), "bare", tmp_path, transcripts_dir=missing
    )
    assert result.passed is True and result.outcome == "pass" and result.error is None
    assert not missing.exists()
    assert "could not write transcript" in capsys.readouterr().err


def test_run_suite_passes_transcripts_dir_and_repeat_index(tmp_path):
    taskdir = tmp_path / "tasks"
    taskdir.mkdir()
    (taskdir / "tiny.yaml").write_text(TINY_TASK)
    transcripts = tmp_path / "t"
    transcripts.mkdir()
    client = FakeClient([assistant(content="hi")] * 2)
    evalrun.run_suite(
        client,
        configs=["bare"],
        workdir=tmp_path / "work",
        tasks_dir=taskdir,
        repeats=2,
        transcripts_dir=transcripts,
    )
    assert sorted(p.name for p in transcripts.iterdir()) == [
        "bare--tiny--r0.json",
        "bare--tiny--r1.json",
    ]
    assert read_transcript(transcripts, "bare", "tiny", repeat=1)["repeat"] == 1


def test_cli_transcripts_flag_creates_dir_and_reaches_run_suite(monkeypatch, tmp_path):
    captured = {}
    target = tmp_path / "dumps" / "run-1"

    def fake_run_suite(client, transcripts_dir=None, **kw):
        captured["transcripts_dir"] = transcripts_dir
        return []

    monkeypatch.setattr(evalrun, "OpenAICompatible", lambda **kw: object())
    monkeypatch.setattr(evalrun, "run_suite", fake_run_suite)
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    evalrun.main(["--base-url", "http://x", "--model", "m", "--transcripts", str(target)])
    assert captured["transcripts_dir"] == target
    assert target.is_dir()  # created with parents=True


# ---- P9: deterministic per-(model, task, repeat) seed ----


class SeedableClient(FakeClient):
    """A fake with the one attribute `run_task` duck-types on, plus a `model` name."""

    def __init__(self, responses, model="qwen3:4b-instruct"):
        super().__init__(responses)
        self.model = model
        self.seed = None

    def chat(self, messages, tools=None):
        self.calls.append(
            {"messages": list(messages), "tools": list(tools or []), "seed": self.seed}
        )
        return self.responses.pop(0)


def test_run_seed_golden_values():
    """Hardcoded on purpose: the point of the seed is stability across processes."""
    assert run_seed("qwen3:4b-instruct", "extract-contact", 0) == 1861749954
    assert run_seed("llama3.2:3b", "recall-owner", 0) == 1390078982


def test_run_seed_is_32_bit_and_stable_within_a_process():
    value = run_seed("m", "t", 0)
    assert 0 <= value < 2**32
    assert value == run_seed("m", "t", 0)


def test_run_seed_varies_with_repeat_and_model():
    assert run_seed("m", "t", 0) != run_seed("m", "t", 1)
    assert run_seed("m", "t", 0) != run_seed("other", "t", 0)
    assert run_seed("m", "t", 0) != run_seed("m", "other", 0)


def test_run_seed_excludes_config_so_configs_share_it(tmp_path):
    """bare vs graph on the same (task, repeat) must sample identically to be comparable."""
    seeds = []
    for config in ("bare", "graph"):
        client = SeedableClient([assistant(content=CONTACT)])
        run_task(client, get_task("extract-contact"), config, tmp_path, repeat=1)
        seeds.append(client.seed)
    assert seeds[0] == seeds[1] == run_seed("qwen3:4b-instruct", "extract-contact", 1)


def test_run_task_pins_the_seed_before_the_first_call_and_records_it(tmp_path):
    client = SeedableClient([assistant(content=CONTACT)])
    result = run_task(client, get_task("extract-contact"), "bare", tmp_path)
    assert result.seed == 1861749954
    assert client.calls[0]["seed"] == 1861749954  # pinned before the run, not after


def test_run_task_leaves_seedless_clients_alone_and_records_none(tmp_path):
    """A seed the client ignored would be provenance fiction, so it is not recorded."""
    client = FakeClient([assistant(content=CONTACT)])
    result = run_task(client, get_task("extract-contact"), "bare", tmp_path)
    assert result.seed is None
    assert not hasattr(client, "seed")


def test_run_suite_reseeds_per_repeat(tmp_path):
    taskdir = tmp_path / "tasks"
    taskdir.mkdir()
    (taskdir / "tiny.yaml").write_text(TINY_TASK)
    client = SeedableClient([assistant(content="hi")] * 2)
    results = evalrun.run_suite(
        client, configs=["bare"], workdir=tmp_path / "work", tasks_dir=taskdir, repeats=2
    )
    assert [r.seed for r in results] == [
        run_seed("qwen3:4b-instruct", "tiny", 0),
        run_seed("qwen3:4b-instruct", "tiny", 1),
    ]


def test_seed_lands_in_the_jsonl_line_as_the_last_field(monkeypatch, tmp_path):
    out = tmp_path / "results.jsonl"

    def fake_run_suite(client, configs=None, tasks_dir=None, repeats=1, on_result=None):
        on_result(make_result(seed=1861749954))
        return []

    monkeypatch.setattr(evalrun, "OpenAICompatible", lambda **kw: object())
    monkeypatch.setattr(evalrun, "run_suite", fake_run_suite)
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    evalrun.main(["--base-url", "http://x", "--model", "m", "--json", str(out)])
    data = json.loads(out.read_text().splitlines()[0])
    assert data["seed"] == 1861749954
    # Additive: appended, never inserted mid-row. `seed` was terminal when this node was
    # written; M3.5's accounting columns were appended AFTER it, so the invariant this
    # pins is that nothing moved at or above `seed`'s position — which is what the
    # convention actually protects for a reader of an older row.
    keys = list(data)
    assert keys[: keys.index("seed") + 1] == [
        "task",
        "config",
        "family",
        "passed",
        "tokens",
        "outcome",
        "model_calls",
        "tool_calls",
        "schema_retries",
        "critique_rounds",
        "error",
        "seed",
    ]


def test_seed_lands_in_the_transcript(tmp_path):
    transcripts = tmp_path / "t"
    transcripts.mkdir()
    client = SeedableClient([assistant(content=CONTACT)])
    run_task(
        client, get_task("extract-contact"), "bare", tmp_path, transcripts_dir=transcripts
    )
    assert read_transcript(transcripts, "bare", "extract-contact")["seed"] == 1861749954


def test_format_report_keeps_ablation_config_rows():
    results = [
        TaskResult(
            task="nav-x", config="graph-annotate", family="file-nav", passed=True,
            tokens=100, outcome="pass", model_calls=1, tool_calls=0,
            schema_retries=0, critique_rounds=0, error=None,
        )
    ]
    report = format_report(results)
    assert "graph-annotate" in report


# ---- P2: response_format forwarding through TrackingClient ----


class ConstrainedClient(FakeClient):
    """A fake that understands the kwarg, like OpenAICompatible."""

    def __init__(self, responses, unsupported=False):
        super().__init__(responses)
        self._response_format_unsupported = unsupported
        self.response_formats = []

    def chat(self, messages, tools=None, response_format=None):
        self.response_formats.append(response_format)
        return super().chat(messages, tools)


def test_tracking_client_forwards_response_format_to_a_capable_inner():
    inner = ConstrainedClient([assistant(content="a")])
    TrackingClient(inner).chat([Message(role="user", content="x")], response_format={"t": 1})
    assert inner.response_formats == [{"t": 1}]


def test_tracking_client_omits_response_format_when_not_asked_for():
    inner = ConstrainedClient([assistant(content="a")])
    TrackingClient(inner).chat([Message(role="user", content="x")])
    assert inner.response_formats == [None]


def test_tracking_client_never_sends_the_kwarg_to_a_two_arg_fake():
    """conftest's FakeClient takes (messages, tools); passing more would be a TypeError."""
    inner = FakeClient([assistant(content="a")])
    tracking = TrackingClient(inner)
    tracking.chat([Message(role="user", content="x")], response_format={"t": 1})
    assert tracking.calls == 1 and len(inner.calls) == 1


def test_tracking_client_mirrors_the_capability_memo_of_its_inner():
    inner = ConstrainedClient([])
    tracking = TrackingClient(inner)
    assert hasattr(tracking, "_response_format_unsupported")
    assert tracking._response_format_unsupported is False
    inner._response_format_unsupported = True  # as a 400 fallback would
    assert tracking._response_format_unsupported is True  # live, not snapshotted
    assert not hasattr(TrackingClient(FakeClient([])), "_response_format_unsupported")


def test_structured_config_reaches_the_inner_client_with_response_format(tmp_path):
    """End to end: the tier survives the wrapper the harness always puts in the way."""
    inner = ConstrainedClient([assistant(content=CONTACT)])
    run_task(inner, get_task("extract-contact"), "structured", tmp_path)
    assert inner.response_formats[0]["json_schema"]["name"] == "output"
    assert inner.response_formats[0]["json_schema"]["schema"] == get_task("extract-contact")[
        "schema"
    ]


# ---- P4: JsonAnswerGate wiring ----

JSON_TASK = {
    "name": "t",
    "family": "memory-recall",
    "prompt": "answer",
    "scoring": {"kind": "json_equal", "expected": {"a": 1}},
}
CONTAINS_TASK = {
    "name": "t",
    "family": "memory-recall",
    "prompt": "answer",
    "scoring": {"kind": "contains", "expected": ["a"]},
}


@pytest.mark.parametrize("config", ["memory", "lean", "full"])
def test_json_answer_gate_rescues_a_prose_answer(config, tmp_path):
    client = FakeClient(
        [assistant(content="the answer is a=1"), assistant(content='{"a": 1}')]
        # `full` also runs the grounded critic on the rescued answer
        + [assistant(content=GROUNDED_VERDICT)]
    )
    result = run_task(client, dict(JSON_TASK), config, tmp_path)
    assert result.passed is True
    assert "contains no JSON" in client.calls[1]["messages"][-1].content


def test_bare_stays_the_floor_and_gets_no_json_answer_gate(tmp_path):
    client = FakeClient([assistant(content="the answer is a=1")])
    result = run_task(client, dict(JSON_TASK), "bare", tmp_path)
    assert result.passed is False and result.outcome == "malformed-output"
    assert len(client.calls) == 1


def test_json_answer_gate_not_attached_for_non_json_scoring(tmp_path):
    client = FakeClient([assistant(content="the answer is a")])
    result = run_task(client, dict(CONTAINS_TASK), "memory", tmp_path)
    assert result.passed is True and len(client.calls) == 1


def test_json_answer_gate_fails_open_and_the_run_is_still_scored(tmp_path):
    """A second prose answer is a scorable wrong answer, never an exception."""
    client = FakeClient([assistant(content="prose one"), assistant(content="prose two")])
    result = run_task(client, dict(JSON_TASK), "memory", tmp_path)
    assert result.passed is False and result.error is None
    assert result.outcome == "malformed-output"


def test_schema_gate_still_owns_schema_tasks_in_lean(tmp_path):
    """Where a schema exists its error is more informative, so it is registered first."""
    task = {
        "name": "t",
        "family": "structured-extraction",
        "prompt": "extract",
        "schema": {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
        "scoring": {"kind": "json_equal", "expected": {"a": 1}},
    }
    client = FakeClient([assistant(content="not json"), assistant(content='{"a": 1}')])
    result = run_task(client, task, "lean", tmp_path)
    assert result.passed is True
    assert "not parseable" in client.calls[1]["messages"][-1].content
    assert "contains no JSON" not in client.calls[1]["messages"][-1].content


# ---- P7 follow-up: turns-exhausted transcripts are no longer empty ----


def test_turns_exhausted_transcript_carries_the_messages(tmp_path):
    transcripts = tmp_path / "t"
    transcripts.mkdir()

    class NeverAnswers:
        def chat(self, messages, tools=None):
            return assistant(tool_calls=[call("price_lookup", {"item": "widget"})])

    result = run_task(
        NeverAnswers(), get_task("shop-cheapest"), "bare", tmp_path, transcripts_dir=transcripts
    )
    assert result.outcome == "turns-exhausted"
    data = read_transcript(transcripts, "bare", "shop-cheapest")
    assert data["messages"], "turns-exhausted runs used to write messages: []"
    assert any(m["tool_calls"] for m in data["messages"])
    # JSONL semantics unchanged this cycle: the column still reads 0 for a raised run.
    assert result.tool_calls == 0


def test_gate_raised_transcript_stays_empty_without_an_agent_loop(tmp_path):
    """The `structured` config has no agent transcript to fill the slot with."""
    transcripts = tmp_path / "t"
    transcripts.mkdir()
    client = FakeClient([assistant(content="not json")] * 3)
    result = run_task(
        client, get_task("extract-contact"), "structured", tmp_path, transcripts_dir=transcripts
    )
    assert result.outcome == "schema-exhausted"
    assert read_transcript(transcripts, "structured", "extract-contact")["messages"] == []


# ---- RP4a: gate-exhausted transcripts are no longer empty either ----


def test_schema_exhausted_transcript_carries_the_messages(tmp_path):
    """RP1 probe: a `lean` schema-exhausted run wrote `{"output": null, "messages": []}`."""
    transcripts = tmp_path / "t"
    transcripts.mkdir()
    client = FakeClient([assistant(content='{"name": "Ann"}')] * 3)
    result = run_task(
        client, get_task("extract-contact"), "lean", tmp_path, transcripts_dir=transcripts
    )
    assert result.outcome == "schema-exhausted"
    data = read_transcript(transcripts, "lean", "extract-contact")
    assert data["messages"], "schema-exhausted runs used to write messages: []"
    assert [m["role"] for m in data["messages"]].count("assistant") == 3
    assert data["messages"][-1]["content"] == '{"name": "Ann"}'


def test_critique_exhausted_transcript_carries_the_messages(tmp_path):
    """Same gap on the other gate: RP2 had to monkeypatch the runtime to see this run."""
    transcripts = tmp_path / "t"
    transcripts.mkdir()
    bad_verdict = '{"score": 2, "feedback": "still wrong"}'
    client = FakeClient(
        [
            assistant(content="answer one"),
            assistant(content=bad_verdict),
            assistant(content="answer two"),
            assistant(content=bad_verdict),
            assistant(content="answer three"),
            assistant(content=bad_verdict),
        ]
    )
    result = run_task(
        client, get_task("recall-owner"), "critique", tmp_path, transcripts_dir=transcripts
    )
    assert result.outcome == "critique-exhausted"
    data = read_transcript(transcripts, "critique", "recall-owner")
    assert data["messages"], "critique-exhausted runs used to write messages: []"
    assert [m["content"] for m in data["messages"] if m["role"] == "assistant"] == [
        "answer one",
        "answer two",
        "answer three",
    ]


# ---- P6: --eval-profile threads explicit constructor args ----


class NeverAnswers:
    """Always calls a tool, never gives a final answer — the run dies of turn exhaustion."""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        return assistant(tool_calls=[call("price_lookup", {"item": "widget"})])


def test_no_profile_keeps_the_default_turn_budget(tmp_path):
    client = NeverAnswers()
    result = run_task(client, get_task("shop-cheapest"), "bare", tmp_path)
    assert result.outcome == "turns-exhausted" and client.calls == 10


def test_patient_profile_max_turns_reaches_the_agent(tmp_path):
    client = NeverAnswers()
    result = run_task(
        client, get_task("shop-cheapest"), "bare", tmp_path, profile=load_profile("patient")
    )
    assert result.outcome == "turns-exhausted" and client.calls == 16


def test_profile_critique_rounds_reach_the_gate(tmp_path):
    """Profile threading is not agent-only: gates get explicit args too."""
    profile = load_profile()
    profile["critique"]["max_rounds"] = 1
    bad_verdict = '{"score": 2, "feedback": "still wrong"}'
    client = FakeClient([assistant(content="answer one"), assistant(content=bad_verdict)])
    result = run_task(client, get_task("recall-owner"), "critique", tmp_path, profile=profile)
    assert result.outcome == "critique-exhausted"
    assert result.critique_rounds == 1  # max_rounds=1: the first violation raises, and counts


def test_run_suite_threads_the_profile_to_every_task(tmp_path, monkeypatch):
    taskdir = tmp_path / "tasks"
    taskdir.mkdir()
    (taskdir / "tiny.yaml").write_text(TINY_TASK)
    seen = {}

    def spy(client, task, config, workdir, transcripts_dir=None, repeat=0, profile=None):
        seen["profile"] = profile
        return make_result()

    monkeypatch.setattr(evalrun, "run_task", spy)
    evalrun.run_suite(
        FakeClient([]),
        configs=["bare"],
        workdir=tmp_path / "work",
        tasks_dir=taskdir,
        profile={"marker": True},
    )
    assert seen["profile"] == {"marker": True}


def test_cli_eval_profile_flag_loads_and_reaches_run_suite(monkeypatch):
    captured = {}

    def fake_run_suite(client, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(evalrun, "OpenAICompatible", lambda **kw: object())
    monkeypatch.setattr(evalrun, "run_suite", fake_run_suite)
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    evalrun.main(["--base-url", "http://x", "--model", "m", "--eval-profile", "patient"])
    assert captured["profile"]["agent"]["max_turns"] == 16


def test_cli_without_eval_profile_sends_no_profile_kwarg(monkeypatch):
    captured = {}

    def fake_run_suite(client, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(evalrun, "OpenAICompatible", lambda **kw: object())
    monkeypatch.setattr(evalrun, "run_suite", fake_run_suite)
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    evalrun.main(["--base-url", "http://x", "--model", "m"])
    assert "profile" not in captured


def test_cli_unknown_eval_profile_fails_loudly(monkeypatch):
    from bantamkit.assets import AssetNotFound

    monkeypatch.setattr(evalrun, "OpenAICompatible", lambda **kw: object())
    monkeypatch.setattr(evalrun, "run_suite", lambda client, **kw: [])
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    with pytest.raises(AssetNotFound):
        evalrun.main(["--base-url", "http://x", "--model", "m", "--eval-profile", "nope"])


# ---- P3: the `budgeted` calibration config ----


def budget_profile(ceiling, optional_cutoff=0.75):
    profile = load_profile()
    profile["token_budget"] = {"ceiling": ceiling, "optional_cutoff": optional_cutoff}
    return profile


def test_budgeted_is_a_choice_but_not_in_the_default_matrix():
    assert "budgeted" in CONFIG_CHOICES and "budgeted" not in CONFIGS


def test_budgeted_is_full_plus_a_budget(tmp_path):
    """Same script as the `full` schema-retry test, same counters — only the label differs."""
    client = FakeClient(
        [
            assistant(content='{"name": "Ann Chen"}'),  # missing email -> schema retry
            assistant(content=CONTACT),
            assistant(content=GROUNDED_VERDICT),
        ]
    )
    result = run_task(client, get_task("extract-contact"), "budgeted", tmp_path)
    assert result.config == "budgeted"
    assert result.passed is True and result.outcome == "pass"
    assert result.schema_retries == 1 and result.critique_rounds == 0
    assert result.model_calls == 3


def test_budgeted_skips_the_critic_past_the_cutoff(tmp_path):
    """Also the ordering guard: a budget attached after the gate would never be asked."""
    client = FakeClient([assistant(content=CONTACT)])  # no critic verdict is scripted
    result = run_task(
        client,
        get_task("extract-contact"),
        "budgeted",
        tmp_path,
        profile=budget_profile(ceiling=20, optional_cutoff=0.5),
    )
    assert result.passed is True and result.model_calls == 1


def test_budget_exhausted_outcome_on_a_failed_truncated_run(tmp_path):
    client = FakeClient(
        [
            assistant(content='{"name": "Ann Chen"}'),  # schema retry keeps the loop alive
            assistant(content=CONTACT),  # never reached: the ceiling fires first
        ]
    )
    result = run_task(
        client,
        get_task("extract-contact"),
        "budgeted",
        tmp_path,
        profile=budget_profile(ceiling=10),
    )
    assert result.passed is False
    assert result.outcome == "budget-exhausted"
    assert result.model_calls == 1


def test_a_budget_truncated_but_correct_answer_still_counts_pass(tmp_path):
    """P7 lesson: the answer is scored first, so nothing swallows a scorable answer."""
    client = FakeClient(
        [
            assistant(content='{"name": "Ann Chen"}', prompt_tokens=100),  # schema retry
            assistant(content=CONTACT, prompt_tokens=100),  # correct, and past the ceiling
        ]
    )
    result = run_task(
        client,
        get_task("extract-contact"),
        "budgeted",
        tmp_path,
        profile=budget_profile(ceiling=200, optional_cutoff=0.5),
    )
    assert result.passed is True and result.outcome == "pass"
    assert result.model_calls == 2


def test_headline_configs_carry_no_budget(tmp_path):
    """`full` is untouched: no governor, so no round is ever denied."""
    client = FakeClient(
        [
            assistant(content=CONTACT, prompt_tokens=10_000),
            assistant(content=GROUNDED_VERDICT),
        ]
    )
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is True and result.model_calls == 2


def test_budget_exhausted_is_a_known_outcome():
    assert "budget-exhausted" in evalrun.OUTCOMES


# ---- the gates inherit `agent.client`, so the governor sees the critic ----


def capture_gate(monkeypatch, name):
    """Grab the gate instance `run_task` builds, at the moment it is set up."""
    captured = []
    original = getattr(evalrun, name)

    class Capturing(original):
        def setup(self, agent):
            super().setup(agent)
            captured.append(self)

    monkeypatch.setattr(evalrun, name, Capturing)
    return captured


def test_budgeted_gate_client_is_the_budget_wrapper(tmp_path, monkeypatch):
    """The point of the cycle: the critic call goes through the governor's wrapper."""
    captured = capture_gate(monkeypatch, "GroundedCritiqueGate")
    client = FakeClient([assistant(content=CONTACT), assistant(content=GROUNDED_VERDICT)])
    result = run_task(client, get_task("extract-contact"), "budgeted", tmp_path)
    (gate,) = captured
    assert isinstance(gate.client, _BudgetedClient)
    assert gate.client.budget is gate.budget
    assert isinstance(gate.client.inner, TrackingClient)
    # One agent turn (15) plus one critic call (15): the critic used to be invisible.
    assert gate.budget.spent == 30
    assert result.passed is True and result.model_calls == 2 and result.tokens == 30


def test_full_gate_client_is_the_tracking_client(tmp_path, monkeypatch):
    """Behaviour pin for the non-budgeted configs: exactly what `client=tracking` gave."""
    captured = capture_gate(monkeypatch, "GroundedCritiqueGate")
    client = FakeClient([assistant(content=CONTACT), assistant(content=GROUNDED_VERDICT)])
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    (gate,) = captured
    assert isinstance(gate.client, TrackingClient)
    assert gate.client.inner is client
    assert gate.budget is None
    assert result.passed is True and result.model_calls == 2 and result.tokens == 30


def test_both_critique_gates_affirm_deterministic_sampling(tmp_path, monkeypatch):
    """RP5b: the memo is off in the library until a caller affirms, and the harness is
    the caller that can. It pins a seed per run and measures against a seed-honouring
    local endpoint, so a bar it produced is already unreproducible on a backend that
    resamples — the affirmation adds no assumption the methodology did not already make.
    Without it the RP4e livelock bar (10,571 tokens, 7 model calls per run) would not
    reproduce."""
    grounded = capture_gate(monkeypatch, "GroundedCritiqueGate")
    blind = capture_gate(monkeypatch, "CritiqueGate")
    run_task(
        FakeClient([assistant(content=CONTACT), assistant(content=GROUNDED_VERDICT)]),
        get_task("extract-contact"),
        "full",
        tmp_path,
    )
    run_task(
        FakeClient(
            [
                assistant(content='{"team": "Atlas"}'),
                assistant(content='{"score": 9, "feedback": "ok"}'),
            ]
        ),
        get_task("recall-owner"),
        "critique",
        tmp_path,
    )
    (grounded_gate,) = grounded
    (blind_gate,) = blind
    assert grounded_gate.deterministic_sampling is True
    assert blind_gate.deterministic_sampling is True


def test_critique_gate_client_is_the_tracking_client(tmp_path, monkeypatch):
    captured = capture_gate(monkeypatch, "CritiqueGate")
    client = FakeClient(
        [
            assistant(content='{"team": "Atlas"}'),
            assistant(content='{"score": 9, "feedback": "ok"}'),
        ]
    )
    result = run_task(client, get_task("recall-owner"), "critique", tmp_path)
    (gate,) = captured
    assert isinstance(gate.client, TrackingClient)
    assert gate.client.inner is client
    assert result.passed is True and result.model_calls == 2


# ---- LoopGuard: the `graph-guarded` / `memory-guarded` calibration configs ----


def guard_profile(inject_at, warn_at=5):
    profile = load_profile()
    profile["loop_guard"] = {"inject_at": inject_at, "warn_at": warn_at}
    return profile


def test_guarded_configs_are_choices_but_not_in_the_default_matrix():
    for name in ("graph-guarded", "memory-guarded"):
        assert name in CONFIG_CHOICES and name not in CONFIGS


def test_graph_guarded_is_graph_plus_a_guard(tmp_path):
    """Same script as the graph collapse test, same collapse — only the label differs."""
    client = FakeClient(
        [
            assistant(tool_calls=[call("read_file", {"path": "notes/a.md"})]),
            assistant(tool_calls=[call("read_file", {"path": "notes/a.md"}, id="c2")]),
            assistant(content='{"x": 1}'),
        ]
    )
    result = run_task(client, workspace_task(), "graph-guarded", tmp_path)
    assert result.config == "graph-guarded"
    assert result.passed is True
    second = client.calls[2]["messages"][-1].content
    assert second.startswith("[file-graph]") and "alpha" not in second
    assert "file_graph" in [t.name for t in client.calls[0]["tools"]]


def test_memory_guarded_is_memory_plus_a_guard(tmp_path):
    """Same script as the memory seeding test: the seeded fact still comes back."""
    client = FakeClient(
        [
            assistant(tool_calls=[call("memory_recall", {"query": "deploy production"})]),
            assistant(content='{"command": "make ship-prod"}'),
        ]
    )
    result = run_task(client, get_task("recall-deploy"), "memory-guarded", tmp_path)
    assert result.config == "memory-guarded"
    assert result.passed is True
    recall_obs = client.calls[1]["messages"][-1].content
    assert "[deploy-command]" in recall_obs
    assert "make ship-prod" in recall_obs


def test_guard_note_fires_at_the_default_threshold(tmp_path):
    """Three identical listings: the third carries the note, and the run still scores."""
    client = FakeClient(
        [
            assistant(tool_calls=[call("list_files", {})]),
            assistant(tool_calls=[call("list_files", {}, id="c2")]),
            assistant(tool_calls=[call("list_files", {}, id="c3")]),
            assistant(content='{"x": 1}'),
        ]
    )
    result = run_task(client, workspace_task(), "graph-guarded", tmp_path)
    obs = [client.calls[i]["messages"][-1].content for i in (1, 2, 3)]
    assert obs[0] == obs[1]  # below the threshold: byte-unchanged
    assert obs[2] == f"{loop_note(3)}\n{obs[0]}"
    assert result.passed is True and result.outcome == "pass"  # injection-only


def test_guard_wraps_the_late_registered_memory_tools(tmp_path):
    """memory_recall is registered by Memory.setup, so the note firing on it proves
    the guard attached last — after every other component put its tools in place."""
    query = call("memory_recall", {"query": "deploy production"})
    client = FakeClient(
        [
            assistant(tool_calls=[query]),
            assistant(tool_calls=[call("memory_recall", query.arguments, id="c2")]),
            assistant(tool_calls=[call("memory_recall", query.arguments, id="c3")]),
            assistant(content='{"command": "make ship-prod"}'),
        ]
    )
    result = run_task(client, get_task("recall-deploy"), "memory-guarded", tmp_path)
    obs = [client.calls[i]["messages"][-1].content for i in (1, 2, 3)]
    assert obs[0] == obs[1]
    assert obs[2] == f"{loop_note(3)}\n{obs[0]}"
    assert result.passed is True


def test_guard_thresholds_come_from_the_profile(tmp_path):
    client = FakeClient(
        [
            assistant(tool_calls=[call("list_files", {})]),
            assistant(tool_calls=[call("list_files", {}, id="c2")]),
            assistant(content='{"x": 1}'),
        ]
    )
    result = run_task(
        client,
        workspace_task(),
        "graph-guarded",
        tmp_path,
        profile=guard_profile(inject_at=2),
    )
    second = client.calls[2]["messages"][-1].content
    assert second.startswith(loop_note(2))
    assert result.passed is True


def test_guard_hashes_the_graph_output_not_the_raw_reader_bytes(tmp_path):
    """Ordering pin: in run_task the graph wraps first and the guard wraps LAST,
    so the guard hashes what the model sees — the graph's markers, which carry a
    per-repeat read # and therefore never streak on cached repeats of one
    unchanged file. If the attach orders were swapped, the guard would see the
    raw 'alpha' three times and inject its note, and the graph would then book
    the note-carrying bytes as a CHANGED read — this test fails both ways."""
    reads = [call("read_file", {"path": "notes/a.md"}, id=f"c{i}") for i in range(4)]
    client = FakeClient(
        [assistant(tool_calls=[r]) for r in reads] + [assistant(content='{"x": 1}')]
    )
    result = run_task(client, workspace_task(), "graph-guarded", tmp_path)
    obs = [client.calls[i]["messages"][-1].content for i in (1, 2, 3, 4)]
    assert obs[0] == "alpha"
    for repeat, o in zip((2, 3, 4), obs[1:], strict=True):
        assert o.startswith("[file-graph]") and f"read #{repeat}" in o
        assert "unchanged" in o and "CHANGED" not in o
    assert not any(loop_note(n) in o for n in (2, 3, 4) for o in obs)
    assert result.passed is True


def test_headline_configs_carry_no_guard(tmp_path):
    """`graph` is untouched: three identical listings come back byte-unchanged."""
    client = FakeClient(
        [
            assistant(tool_calls=[call("list_files", {})]),
            assistant(tool_calls=[call("list_files", {}, id="c2")]),
            assistant(tool_calls=[call("list_files", {}, id="c3")]),
            assistant(content='{"x": 1}'),
        ]
    )
    result = run_task(client, workspace_task(), "graph", tmp_path)
    obs = [client.calls[i]["messages"][-1].content for i in (1, 2, 3)]
    assert obs[0] == obs[1] == obs[2]
    assert result.passed is True


# ---- RB-P3: lean/full engage the constrained-decoding tier ----
# (reuses `ConstrainedClient` above — the same fake that pins TrackingClient's forwarding)


@pytest.mark.parametrize("config", ["lean", "full"])
def test_schema_configs_constrain_the_first_decode(config, tmp_path):
    """RP1's finding: the gate can only react, so the FIRST call has to be constrained."""
    task = get_task("extract-contact")
    client = ConstrainedClient([assistant(content=CONTACT), assistant(content=GROUNDED_VERDICT)])
    result = run_task(client, task, config, tmp_path)
    assert result.passed is True
    assert client.response_formats[0] == response_format_for(task["schema"])


def test_the_gate_retry_is_constrained_too(tmp_path):
    task = get_task("extract-contact")
    client = ConstrainedClient(
        [assistant(content='{"name": "Ann Chen"}'), assistant(content=CONTACT)]
    )
    run_task(client, task, "lean", tmp_path)
    assert client.response_formats == [response_format_for(task["schema"])] * 2


def test_the_critique_verdict_keeps_its_own_schema(tmp_path):
    """`full` sends two different schemas: the task's on the answer, the rubric's on the verdict."""
    task = get_task("extract-contact")
    client = ConstrainedClient([assistant(content=CONTACT), assistant(content=GROUNDED_VERDICT)])
    run_task(client, task, "full", tmp_path)
    task_rf, verdict_rf = client.response_formats
    assert task_rf == response_format_for(task["schema"])
    assert verdict_rf != task_rf
    assert "score" in verdict_rf["json_schema"]["schema"]["properties"]


@pytest.mark.parametrize("config", ["bare", "critique", "grounded", "graph", "memory"])
def test_non_schema_configs_are_left_unconstrained(config, tmp_path):
    """The tier rides on the schema gate's registration, nowhere else."""
    client = ConstrainedClient(
        [assistant(content=CONTACT), assistant(content=GROUNDED_VERDICT)] * 2
    )
    run_task(client, get_task("extract-contact"), config, tmp_path)
    assert client.response_formats[0] is None


def test_structured_config_is_untouched(tmp_path):
    """It already drove its own constrained loop; this change must not move it."""
    task = get_task("extract-contact")
    client = ConstrainedClient([assistant(content=CONTACT)])
    result = run_task(client, task, "structured", tmp_path)
    assert result.passed is True
    assert client.response_formats == [response_format_for(task["schema"])]


def test_a_schemaless_task_stays_unconstrained_under_lean(tmp_path):
    client = ConstrainedClient([assistant(content="The total is 42 dollars.")])
    run_task(client, get_task("shop-total"), "lean", tmp_path)
    assert client.response_formats == [None]


# ---- RB-P8: the grounded critic needs a source, and this recipe removed it ----


LOW_GROUNDED_VERDICT = (
    '{"reasoning": "nothing supports this", "score": 2, "feedback": "unverified"}'
)


def test_grounded_skips_the_critic_when_it_withheld_the_answer_source(tmp_path):
    """`grounded` runs `memory_setup` tasks storeless, so the critic has nothing to check."""
    client = FakeClient([assistant(content='{"team": "Atlas"}')])
    result = run_task(client, get_task("recall-owner"), "grounded", tmp_path)
    assert len(client.calls) == 1  # the agent answered; no critic was asked
    assert result.critique_rounds == 0
    assert result.passed is True and result.outcome == "pass"


def test_grounded_scores_a_wrong_storeless_recall_instead_of_exhausting_a_critic(tmp_path):
    """The ten runs RB-P8 measured: honest verdicts, three rounds, unfixable answers."""
    client = FakeClient([assistant(content='{"team": "Nobody"}')])
    result = run_task(client, get_task("recall-owner"), "grounded", tmp_path)
    assert result.passed is False
    assert result.outcome == "wrong-answer" and result.error is None
    assert result.critique_rounds == 0 and len(client.calls) == 1


def test_full_still_critiques_a_memory_task_because_it_attached_the_store(tmp_path):
    """`full` never trips the guard: a `memory_setup` task under `full` gets its store."""
    client = FakeClient(
        [assistant(content='{"team": "Atlas"}'), assistant(content=GROUNDED_VERDICT)]
    )
    result = run_task(client, get_task("recall-owner"), "full", tmp_path)
    assert len(client.calls) == 2
    assert "score" in client.calls[1]["messages"][-1].content
    assert result.passed is True


def test_grounded_still_critiques_a_task_that_has_tools(tmp_path):
    client = FakeClient(
        [
            assistant(content="the total is 999"),
            assistant(content=LOW_GROUNDED_VERDICT),
            assistant(content="the total is 100"),
            assistant(content=GROUNDED_VERDICT),
        ]
    )
    result = run_task(client, get_task("shop-total"), "grounded", tmp_path)
    assert result.critique_rounds == 1 and result.passed is True


def test_grounded_still_critiques_a_toolless_task_whose_source_is_its_prompt(tmp_path):
    """Deliberate scope boundary: extraction reaches the critic with empty evidence too,
    but its source is the prompt and it burns no exhausted runs, so it keeps the gate."""
    client = FakeClient([assistant(content=CONTACT), assistant(content=GROUNDED_VERDICT)])
    result = run_task(client, get_task("extract-contact"), "grounded", tmp_path)
    assert len(client.calls) == 2 and result.passed is True
    assert "(no tool calls were made)" in client.calls[1]["messages"][-1].content


def test_memory_and_bare_configs_are_untouched_by_the_guard(tmp_path):
    """The guard gates one gate, not the control arms: `grounded` still runs the task."""
    for config in ("bare", "critique", "memory"):
        client = FakeClient([assistant(content='{"team": "Atlas"}')] * 4)
        result = run_task(client, get_task("recall-owner"), config, tmp_path)
        assert result.task == "recall-owner" and result.config == config
