"""Codex event conversion must preserve real usage, including cache subsets."""

import importlib
import json
from pathlib import Path

import pytest


def convert(events):
    module = importlib.import_module("tools.eval.grouped_review.codex_adapter")
    return module.normalize_events("\n".join(json.dumps(e) for e in events), "gpt-6.1-sol")


def final_event():
    return {
        "type": "item.completed",
        "item": {
            "type": "agent_message",
            "text": json.dumps(
                {
                    "findings": [],
                    "evidence": [],
                    "reviewer_context_id": "review-1",
                }
            ),
        },
    }


def test_cache_reads_are_a_subset_of_codex_input_not_extra_tokens():
    got = convert(
        [
            final_event(),
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 60,
                    "output_tokens": 8,
                },
            },
        ]
    )
    assert got["usage"] == {
        "input_tokens": 40,
        "output_tokens": 8,
        "cache_read_input_tokens": 60,
        "cache_creation_input_tokens": 0,
    }
    assert sum(got["usage"].values()) == 108
    assert got["model"] == "gpt-6.1-sol"


def test_missing_usage_stays_unknown():
    assert convert([final_event()])["usage"] == {}


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": True, "cached_input_tokens": 0, "output_tokens": 8},
        {"input_tokens": 10, "cached_input_tokens": 11, "output_tokens": 8},
        {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": -1},
    ],
)
def test_invalid_usage_is_refused(usage):
    with pytest.raises(ValueError):
        convert([final_event(), {"type": "turn.completed", "usage": usage}])


def test_failed_turn_cannot_be_converted_to_success():
    with pytest.raises(ValueError, match="failed"):
        convert([final_event(), {"type": "turn.failed", "error": {"message": "quota"}}])


def test_non_json_agent_answer_is_refused():
    with pytest.raises(ValueError):
        convert(
            [{"type": "item.completed", "item": {"type": "agent_message", "text": "looks good"}}]
        )


def test_adapter_clocks_real_mcp_receipts_with_fake_model_process(tmp_path):
    import asyncio
    import sys

    module = importlib.import_module("tools.eval.grouped_review.codex_adapter")
    fake = tmp_path / "fake.py"
    fake.write_text(
        "import json,sys\np=sys.stdin.read()\n"
        'assert "invariants" in p and "Use only supplied" in p\n'
        f"print({json.dumps(json.dumps(final_event()))})\n"
        'print(json.dumps({"type":"turn.completed","usage":'
        '{"input_tokens":10,"cached_input_tokens":2,"output_tokens":3}}))\n',
        encoding="utf-8",
    )
    result = asyncio.run(
        module.review(
            {"reviewer_context_id": "review-1"}, tmp_path / "clock", [sys.executable, str(fake)]
        )
    )
    checkpoint = __import__("pathlib").Path(result["receipts"]["checkpoint"])
    assert result["receipts"]["clock_out"] == "ok"
    document = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert document["plan"]["units"][0]["status"] == "done"
    records = [
        json.loads(s)
        for s in checkpoint.with_suffix(".json.log.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["event"] == "brief"
    assert records[-1]["tokens"] == 11  # input 10 + output 3 minus cache reads 2
    assert records[-1]["cache_read_tokens"] == 2


def test_bad_model_json_still_clocks_out_blocked(tmp_path):
    import asyncio
    import sys

    module = importlib.import_module("tools.eval.grouped_review.codex_adapter")
    fake = tmp_path / "bad.py"
    fake.write_text("print('not JSON')\n", encoding="utf-8")
    with pytest.raises(module.ReviewFailed) as exc:
        asyncio.run(
            module.review(
                {"reviewer_context_id": "review-1"}, tmp_path / "clock", [sys.executable, str(fake)]
            )
        )
    assert exc.value.envelope["status"] == "blocked"
    assert exc.value.envelope["usage"] == {}  # nothing reported stays unknown, never zero
    checkpoint = next((tmp_path / "clock").glob("*/checkpoint.json"))
    assert (
        json.loads(checkpoint.read_text(encoding="utf-8"))["plan"]["units"][0]["status"]
        == "blocked"
    )


SPENT = {
    "type": "turn.completed",
    "usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 8},
}
NOT_JSON = {"type": "item.completed", "item": {"type": "agent_message", "text": "looks good"}}


def test_usage_is_extracted_even_when_the_answer_is_invalid():
    module = importlib.import_module("tools.eval.grouped_review.codex_adapter")
    raw = "\n".join(json.dumps(e) for e in [NOT_JSON, SPENT])
    with pytest.raises(ValueError):
        module.normalize_events(raw, "gpt-6.1-sol")
    usage = module.extract_usage(raw)
    assert usage == {
        "input_tokens": 60,
        "output_tokens": 8,
        "cache_read_input_tokens": 40,
        "cache_creation_input_tokens": 0,
    }
    assert sum(usage.values()) == 108


def test_failed_answer_keeps_known_cost_in_envelope_and_ledger(tmp_path):
    import asyncio
    import sys

    module = importlib.import_module("tools.eval.grouped_review.codex_adapter")
    fake = tmp_path / "invalid.py"
    fake.write_text(
        f"print({json.dumps(json.dumps(NOT_JSON))})\nprint({json.dumps(json.dumps(SPENT))})\n",
        encoding="utf-8",
    )
    with pytest.raises(module.ReviewFailed) as exc:
        asyncio.run(
            module.review(
                {"reviewer_context_id": "review-1"}, tmp_path / "clock", [sys.executable, str(fake)]
            )
        )
    envelope = exc.value.envelope
    assert envelope["status"] == "blocked"
    assert envelope["error"]
    assert envelope["model"] == "gpt-6.1-sol"
    assert sum(envelope["usage"].values()) == 108
    checkpoint = Path(envelope["receipts"]["checkpoint"])
    assert (
        json.loads(checkpoint.read_text(encoding="utf-8"))["plan"]["units"][0]["status"]
        == "blocked"
    )
    last = json.loads(
        checkpoint.with_suffix(".json.log.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert last["tokens"] == 68
    assert last["cache_read_tokens"] == 40
    assert last.get("estimate") is not True


def test_main_prints_failed_envelope_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    import io

    module = importlib.import_module("tools.eval.grouped_review.codex_adapter")
    envelope = {"status": "blocked", "error": "No reviewer answer", "usage": {"output_tokens": 8}}

    async def failing(request, clock_dir, codex_command=None):
        raise module.ReviewFailed(envelope)

    monkeypatch.setattr(module, "review", failing)
    monkeypatch.setattr("sys.argv", ["codex_adapter", "--clock-dir", str(tmp_path)])
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    with pytest.raises(SystemExit) as exit_:
        module.main()
    assert exit_.value.code == 1
    assert json.loads(capsys.readouterr().out) == envelope
