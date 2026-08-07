import json

from conftest import FakeClient, assistant, call

from bantamkit import evalrun
from bantamkit.client import BantamError, Message, ToolCall
from bantamkit.evalrun import (
    CONFIGS,
    TaskResult,
    TrackingClient,
    format_report,
    load_tasks,
    run_task,
    score_output,
)
from bantamkit.memory.store import MemoryStore


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


def test_score_contains_case_insensitive():
    task = get_task("recall-owner")
    assert score_output(task, "It is owned by Team ATLAS.", []) is True
    assert score_output(task, "no idea", []) is False


def test_score_contains_matches_on_word_boundaries_not_substrings():
    """`100` inside `1000` is a wrong answer, not a pass (shop-total's expected value)."""
    task = get_task("shop-total")
    assert score_output(task, "The total stock value is 100.", []) is True
    assert score_output(task, "The total stock value is 1000", []) is False
    assert score_output(task, "It is 4100 in total", []) is False
    assert score_output(task, "100.50 dollars", []) is True  # `.` is not a word character


def test_score_contains_allows_punctuation_and_hyphens_around_the_term():
    task = get_task("recall-deploy")
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
            assistant(content="Run make ship-prod."),
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
GOOD_VERDICT = '{"score": 9, "feedback": "looks good"}'


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


def test_cli_json_flag_streams_jsonl(monkeypatch, tmp_path):
    out = tmp_path / "results.jsonl"

    def fake_run_suite(client, configs=None, tasks_dir=None, repeats=1, on_result=None):
        result = make_result()
        on_result(result)
        return [result]

    monkeypatch.setattr(evalrun, "OpenAICompatible", lambda **kw: object())
    monkeypatch.setattr(evalrun, "run_suite", fake_run_suite)
    monkeypatch.setattr(evalrun, "format_report", lambda results: "")
    evalrun.main(["--base-url", "http://x", "--model", "m", "--json", str(out)])
    lines = out.read_text().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
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
            assistant(content=GOOD_VERDICT),
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
            assistant(content='{"score": 2, "feedback": "wrong email"}'),
            assistant(content=CONTACT),
            assistant(content=GOOD_VERDICT),
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
    assert result.critique_rounds == 2  # feedback issued twice; third violation raises


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
    client = FakeClient([assistant(content=CONTACT), assistant(content=GOOD_VERDICT)])
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is True and result.error is None
    assert len(client.calls) == 2  # agent turn + critique turn
    prompts = [m.content or "" for c in client.calls for m in c["messages"]]
    assert any("reviewer checking" in p for p in prompts)


def test_full_config_schema_task_retries_on_low_critique_score(tmp_path):
    client = FakeClient(
        [
            assistant(content='{"name": "Ann", "email": "wrong@example.com"}'),
            assistant(content='{"score": 2, "feedback": "wrong email"}'),
            assistant(content=CONTACT),
            assistant(content=GOOD_VERDICT),
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
            assistant(content=GOOD_VERDICT),
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


def test_full_config_non_json_output_recorded_not_raised(tmp_path):
    client = FakeClient([assistant(content="sorry, no idea")] * 3)
    result = run_task(client, get_task("extract-contact"), "full", tmp_path)
    assert result.passed is False
    assert "StructuredOutputError" in result.error and "not parseable JSON" in result.error


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
    assert CONFIGS == ["bare", "structured", "critique", "memory", "lean", "full"]


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
    assert seeded >= 6  # exactly 6 facts today (5 recall tasks); adjust when retiring
