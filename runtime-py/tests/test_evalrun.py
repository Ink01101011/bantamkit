from conftest import FakeClient, assistant, call

from bantamkit import evalrun
from bantamkit.client import Message, ToolCall
from bantamkit.evalrun import (
    CONFIGS,
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
    from bantamkit.evalrun import TaskResult

    results = [
        TaskResult(task="t1", config="bare", passed=True, tokens=500, error=None),
        TaskResult(task="t2", config="bare", passed=False, tokens=500, error=None),
        TaskResult(task="t1", config="full", passed=True, tokens=250, error=None),
        TaskResult(task="t2", config="full", passed=True, tokens=250, error=None),
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
    monkeypatch.setattr(evalrun, "run_suite", lambda client, configs=None: [])
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
    monkeypatch.setattr(evalrun, "run_suite", lambda client, configs=None: [])
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
    assert seeded >= 6  # memory-recall family carries seeded facts; 0 means the guard went blind
