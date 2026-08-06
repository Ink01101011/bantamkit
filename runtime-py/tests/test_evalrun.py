from conftest import FakeClient, assistant, call

from bantamkit.client import Message, ToolCall
from bantamkit.evalrun import (
    CONFIGS,
    TrackingClient,
    format_report,
    load_tasks,
    run_task,
    score_output,
)


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


def test_run_task_explicit_failure_recorded_not_raised(tmp_path):
    client = FakeClient([assistant(content="not json")] * 3)
    result = run_task(client, get_task("extract-contact"), "structured", tmp_path)
    assert result.passed is False
    assert "StructuredOutputError" in result.error


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


def test_configs_matrix():
    assert CONFIGS == ["bare", "structured", "critique", "memory", "full"]
