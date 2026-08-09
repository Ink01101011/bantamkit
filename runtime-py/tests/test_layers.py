"""The layer boundary, made executable: byte-identity, core purity, import direction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bantamkit.client import BantamError, Message, ToolCall
from bantamkit.contract import (
    critique_feedback,
    json_answer_retry,
    load_contract,
    render_evidence,
    schema_error,
    schema_instruction,
    schema_retry_feedback,
)
from bantamkit.profile import default as profile_default
from bantamkit.profile import default_float as profile_default_float
from bantamkit.profile import load_profile

SRC = Path(__file__).resolve().parents[1] / "src" / "bantamkit"

# The exact pre-split literals. If any golden test below fails, the refactor
# changed prompt bytes — that is a defect in the refactor, never in this file.
GOLDEN_SCHEMA_INSTRUCTION = "Return ONLY a JSON object matching this JSON Schema. No prose.\n"
GOLDEN_SCHEMA_RETRY = "boom\nReturn ONLY a JSON object matching the schema."
GOLDEN_CRITIQUE = (
    "A reviewer scored your answer 2/10 (needs >= 7). Feedback: too short\n"
    "Revise and answer again."
)
GOLDEN_EVIDENCE_EMPTY = "(no tool calls were made)"
# New in the contract-robustness cycle (P4), so not a "pre-split" literal — but it is
# model-facing wording and pinned here for the same reason all the others are.
GOLDEN_JSON_ANSWER_RETRY = (
    "Your answer contains no JSON. Restate your final answer as ONLY the JSON "
    "requested by the task, with no prose around it."
)

# Fragments that must never reappear in core sources.
MOVED_FRAGMENTS = (
    "Return ONLY",
    "A reviewer scored",
    "(no tool calls",
    "not parseable JSON",
    "contains no JSON",
)
CORE_MODULES = (
    "agent.py",
    "budget.py",
    "structured.py",
    "critique.py",
    "evalrun.py",
    "mcpserver.py",
)
LAYER_MODULES = ("contract.py", "profile.py")
FORBIDDEN_IMPORTS = ("agent", "structured", "critique", "evalrun", "filegraph", "memory")

PRE_SPLIT_DEFAULTS = {
    ("agent", "max_turns"): 10,
    ("agent", "observation_budget"): 4096,
    ("structured", "max_retries"): 3,
    ("schema_gate", "max_attempts"): 3,
    ("critique", "max_rounds"): 3,
    ("critique", "evidence_budget"): 4096,
}


def test_schema_instruction_bytes():
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    assert schema_instruction(schema) == GOLDEN_SCHEMA_INSTRUCTION + json.dumps(schema)


def test_schema_retry_bytes():
    assert schema_retry_feedback("boom") == GOLDEN_SCHEMA_RETRY


def test_critique_feedback_bytes():
    assert critique_feedback(score=2, threshold=7, feedback="too short") == GOLDEN_CRITIQUE


def test_render_evidence_bytes():
    messages = [
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="t1", name="lookup", arguments={"key": "port"})],
        ),
        Message(role="tool", content="5432", tool_call_id="t1"),
    ]
    assert render_evidence(messages) == 'lookup({"key": "port"}) -> 5432'
    assert render_evidence([]) == GOLDEN_EVIDENCE_EMPTY


def test_json_answer_retry_bytes():
    assert json_answer_retry() == GOLDEN_JSON_ANSWER_RETRY


def test_schema_error_bytes():
    err = schema_error("not json at all", {"type": "object"})
    assert err is not None and err.startswith("output was not parseable JSON: ")
    err = schema_error(
        '{"a": "x"}',
        {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]},
    )
    assert err == "JSON does not match schema at 'a': 'x' is not of type 'integer'"
    assert schema_error('{"a": 1}', {"type": "object"}) is None


@pytest.mark.parametrize("module", CORE_MODULES)
def test_core_purity(module):
    source = (SRC / module).read_text()
    for fragment in MOVED_FRAGMENTS:
        assert fragment not in source, f"contract literal {fragment!r} leaked back into {module}"


@pytest.mark.parametrize("module", LAYER_MODULES)
def test_import_direction(module):
    source = (SRC / module).read_text()
    for target in FORBIDDEN_IMPORTS:
        imported = (
            f"from bantamkit.{target}" in source or f"import bantamkit.{target}" in source
        )
        assert not imported, (
            f"{module} imports core module '{target}' — contract/profile must not depend on core"
        )


def test_profile_values_match_pre_split_defaults():
    for (section, key), expected in PRE_SPLIT_DEFAULTS.items():
        assert profile_default(section, key) == expected, (
            f"profile {section}.{key} changed from the pre-split default {expected} — "
            "recalibration must be an explicit, measured decision, not a refactor side effect"
        )


def test_json_answer_default_is_one_attempt():
    """New in this cycle, so not a pre-split default — pinned separately, same intent."""
    assert profile_default("json_answer", "max_attempts") == 1


def test_token_budget_ceiling_default():
    """New in the policy/budget cycle — pinned separately, same intent as the pre-split guard."""
    assert profile_default("token_budget", "ceiling") == 6000


def test_token_budget_optional_cutoff_default():
    assert profile_default_float("token_budget", "optional_cutoff") == 0.75


def test_patient_profile_differs_from_default_only_in_max_turns():
    """`patient` is a turn-budget hypothesis, not a second set of policy numbers."""
    patient = load_profile("patient")
    baseline = load_profile("default")
    assert patient["name"] == "patient"
    assert patient["agent"]["max_turns"] == 16
    patient["name"], patient["agent"]["max_turns"] = "default", baseline["agent"]["max_turns"]
    assert patient == baseline


def test_load_contract_missing_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    from bantamkit.assets import AssetNotFound

    with pytest.raises(AssetNotFound):
        load_contract()


def test_load_contract_missing_key(tmp_path, monkeypatch):
    (tmp_path / "contracts").mkdir(parents=True)
    (tmp_path / "contracts" / "default.yaml").write_text('name: default\nschema_instruction: "x"\n')
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    with pytest.raises(BantamError, match="missing key"):
        load_contract()


def test_load_profile_missing_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    from bantamkit.assets import AssetNotFound

    with pytest.raises(AssetNotFound):
        load_profile()


def test_load_profile_missing_key(tmp_path, monkeypatch):
    (tmp_path / "profiles").mkdir(parents=True)
    (tmp_path / "profiles" / "default.yaml").write_text("name: default\nagent:\n  max_turns: 10\n")
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    with pytest.raises(BantamError, match="missing key"):
        load_profile()
