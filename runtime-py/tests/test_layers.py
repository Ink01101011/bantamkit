"""The layer boundary, made executable: byte-identity, core purity, import direction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bantamkit.client import BantamError, Message, ToolCall
from bantamkit.contract import (
    critique_feedback,
    document_error,
    document_manifest,
    document_offset_past_end,
    document_page,
    document_paste,
    document_unknown,
    json_answer_retry,
    load_contract,
    loop_note,
    loop_warn,
    render_evidence,
    schema_error,
    schema_instruction,
    schema_retry_feedback,
    tool_arguments,
    tool_failed,
)
from bantamkit.profile import default as profile_default
from bantamkit.profile import default_float as profile_default_float
from bantamkit.profile import load_profile

SRC = Path(__file__).resolve().parents[1] / "src" / "bantamkit"

# The exact pre-split literals. If any golden test below fails, the refactor
# changed prompt bytes — that is a defect in the refactor, never in this file.
GOLDEN_SCHEMA_INSTRUCTION = "Return ONLY a JSON object matching this JSON Schema. No prose.\n"
GOLDEN_SCHEMA_RETRY = "boom\nReturn ONLY a JSON object matching the schema."
# Updated deliberately in the RB-P5 cycle (RP4d): the retry verb was the defect.
# "Revise and answer again." points the answerer at its own previous string, so a
# 4b told "the version is not present in the evidence" edited `imgproc-cli-0.1.0`
# into `imgproc-cli-<version>` instead of reading the VERSION file it had never
# opened. The replacement names the missing-evidence case and its remedy.
GOLDEN_CRITIQUE = (
    "A reviewer scored your answer 2/10 (needs >= 7). Feedback: too short\n"
    "If the feedback says a value is missing, unverified, or absent from your "
    "evidence, that is a fact you never looked up: call your tools and read the "
    "source that has it. Do not reword, generalise, or hedge the previous answer "
    "to work around the gap. Then answer again."
)
GOLDEN_EVIDENCE_EMPTY = "(no tool calls were made)"
# New in the contract-robustness cycle (P4), so not a "pre-split" literal — but it is
# model-facing wording and pinned here for the same reason all the others are.
GOLDEN_JSON_ANSWER_RETRY = (
    "Your answer contains no JSON. Restate your final answer as ONLY the JSON "
    "requested by the task, with no prose around it."
)
# The LoopGuard injection wording (spec §2), pinned before the component exists:
# the words are the contract, the streak mechanics are not.
GOLDEN_LOOP_NOTE = (
    "(you have now received this exact result 4 times; it will not change. "
    "Do something different or give your final answer now)"
)
GOLDEN_LOOP_WARN = (
    "(STOP calling tools. Give your final answer now, in exactly the format the task asked for.)"
)
# New in the document-reader cycle (J10 X3), so not a "pre-split" literal — pinned here for
# the same reason all the others are: these are the ONLY sentences the reader pair puts in
# front of the model, and the layer rule exists because model-facing wording is exactly what
# did not transfer cross-model. A golden here changing is a contract change, never a refactor.
GOLDEN_DOCUMENT_MANIFEST = (
    'inventory.xlsx (xlsx) part 0 "stock": 3 rows, numbered 0 to 2\n'
    "  row 0 is the header: sku\tunits\n"
    "  row 1 is the first data row: SKU-000001\t7\n"
    "  row 2 is the last data row: SKU-000002\t9"
)
GOLDEN_DOCUMENT_MANIFEST_EMPTY = "no documents are attached to this task"
GOLDEN_DOCUMENT_PAGE = (
    'inventory.xlsx "stock" rows 4-5 of 12001; each line below begins with its own row number\n'
    "4\tSKU-000004\n"
    "5\tSKU-000005\n"
    "more rows follow: call document_read again with offset=6"
)
GOLDEN_DOCUMENT_PAGE_END = (
    'inventory.xlsx "stock" rows 11999-12000 of 12001; each line below begins with its own '
    "row number\n"
    "11999\tSKU-011999\n"
    "12000\tSKU-012000\n"
    'that was the last row of "stock"'
)
GOLDEN_DOCUMENT_PAGE_TRUNCATED = (
    'wide.xlsx "wide" rows 3-3 of 10; each line below begins with its own row number\n'
    "3\tXXX\n"
    "row 3 was too long for one page and was cut: 400 bytes dropped\n"
    "more rows follow: call document_read again with offset=4"
)
GOLDEN_DOCUMENT_UNKNOWN = (
    "error: no document named sales.xlsx; this task has: inventory.xlsx, notes.docx"
)
GOLDEN_DOCUMENT_OFFSET_PAST_END = (
    'error: offset 99999 is past the end of "stock", which has 12001 rows numbered 0 to 12000'
)
GOLDEN_DOCUMENT_ERROR = "error: no part 'sales'; this document has 1: 'stock'"
# New in the document-reader cycle (J10 X5): the `paste` arm's system message. Pinned for a
# reason the reader pair's goldens do not have — `paste` registers NO tool, so these lines are
# the only thing standing between the model and reading a 4.76% head as the whole sheet. The
# completeness sentence is the arm's honesty, and the bar's §10.2 clause 4 makes changing it a
# change of ARM, not a change of wording.
GOLDEN_DOCUMENT_PASTE_COMPLETE = (
    "The following document content is attached to this task. Fields in a row are separated "
    "by tabs, rows are given in order, and row 0 of each part is its header.\n"
    'inventory-small.xlsx (xlsx) part 0 "stock": 3 rows, numbered 0 to 2; 3 of them are '
    "shown below.\n"
    '  rows 0 to 2 are shown, which is every row of "stock": this copy is COMPLETE.\n'
    "sku\tunits\n"
    "SKU-000001\t7\n"
    "SKU-000002\t9"
)
GOLDEN_DOCUMENT_PASTE_TRUNCATED = (
    "The following document content is attached to this task. Fields in a row are separated "
    "by tabs, rows are given in order, and row 0 of each part is its header.\n"
    'inventory.xlsx (xlsx) part 0 "stock": 12001 rows, numbered 0 to 12000; 2 of them are '
    "shown below.\n"
    '  rows 0 to 1 are shown; rows 2 to 12000 of "stock" are NOT shown and no tool is '
    "attached that can fetch them. This copy is PARTIAL.\n"
    "sku\tunits\n"
    "SKU-000001\t7"
)
GOLDEN_DOCUMENT_PASTE_NONE = (
    "The following document content is attached to this task. Fields in a row are separated "
    "by tabs, rows are given in order, and row 0 of each part is its header.\n"
    'second.xlsx (xlsx) part 0 "notes": 9 rows, numbered 0 to 8; 0 of them are shown below.\n'
    '  no rows of "notes" are shown and no tool is attached that can fetch them.'
)

# Fragments that must never reappear in core sources.
MOVED_FRAGMENTS = (
    "Return ONLY",
    "A reviewer scored",
    "(no tool calls",
    "not parseable JSON",
    "contains no JSON",
    "you have now received",
    "STOP calling tools",
    "rows, numbered 0 to",
    "is the first data row",
    "begins with its own row number",
    "more rows follow",
    "no document named",
    "is past the end of",
    "The following document content",
    "of them are shown below",
    "this copy is COMPLETE",
    "This copy is PARTIAL",
    "no tool is attached that can fetch them",
    # 2026-08-20. `Agent._dispatch` formatted these itself and interpolated the exception,
    # so a model that sent one undeclared argument was handed a Python qualname.
    "fix the arguments and retry",
    "does not take the arguments",
    "takes no arguments at all",
)
CORE_MODULES = (
    "agent.py",
    "budget.py",
    "docread.py",
    "loopguard.py",
    "structured.py",
    "critique.py",
    "evalrun.py",
    "mcpserver.py",
)
LAYER_MODULES = ("contract.py", "profile.py")
FORBIDDEN_IMPORTS = (
    "agent",
    "docread",
    "structured",
    "critique",
    "evalrun",
    "filegraph",
    "loopguard",
    "memory",
)

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


def test_loop_note_bytes():
    assert loop_note(4) == GOLDEN_LOOP_NOTE


def test_loop_warn_bytes():
    assert loop_warn() == GOLDEN_LOOP_WARN


def test_document_manifest_bytes():
    assert (
        document_manifest(
            [
                {
                    "document": "inventory.xlsx",
                    "kind": "xlsx",
                    "index": 0,
                    "part": "stock",
                    "row_count": 3,
                    "rows": ["sku\tunits", "SKU-000001\t7", "SKU-000002\t9"],
                }
            ]
        )
        == GOLDEN_DOCUMENT_MANIFEST
    )
    assert document_manifest([]) == GOLDEN_DOCUMENT_MANIFEST_EMPTY


def test_document_page_bytes():
    assert (
        document_page(
            document="inventory.xlsx",
            part="stock",
            offset=4,
            rows=["SKU-000004", "SKU-000005"],
            row_count=12001,
            next_offset=6,
        )
        == GOLDEN_DOCUMENT_PAGE
    )
    assert (
        document_page(
            document="inventory.xlsx",
            part="stock",
            offset=11999,
            rows=["SKU-011999", "SKU-012000"],
            row_count=12001,
            next_offset=None,
        )
        == GOLDEN_DOCUMENT_PAGE_END
    )
    assert (
        document_page(
            document="wide.xlsx",
            part="wide",
            offset=3,
            rows=["XXX"],
            row_count=10,
            next_offset=4,
            truncated_bytes=400,
        )
        == GOLDEN_DOCUMENT_PAGE_TRUNCATED
    )


def test_document_error_bytes():
    assert (
        document_unknown("sales.xlsx", ["inventory.xlsx", "notes.docx"])
        == GOLDEN_DOCUMENT_UNKNOWN
    )
    assert document_offset_past_end("stock", 99999, 12001) == GOLDEN_DOCUMENT_OFFSET_PAST_END
    assert (
        document_error("no part 'sales'; this document has 1: 'stock'") == GOLDEN_DOCUMENT_ERROR
    )


def test_document_paste_bytes():
    """All three completeness cases, because they are three different claims to the model."""
    complete = [
        {
            "document": "inventory-small.xlsx",
            "kind": "xlsx",
            "index": 0,
            "part": "stock",
            "row_count": 3,
            "rows": ["sku\tunits", "SKU-000001\t7", "SKU-000002\t9"],
        }
    ]
    assert document_paste(complete) == GOLDEN_DOCUMENT_PASTE_COMPLETE
    truncated = [
        {
            "document": "inventory.xlsx",
            "kind": "xlsx",
            "index": 0,
            "part": "stock",
            "row_count": 12001,
            "rows": ["sku\tunits", "SKU-000001\t7"],
        }
    ]
    assert document_paste(truncated) == GOLDEN_DOCUMENT_PASTE_TRUNCATED
    nothing = [
        {
            "document": "second.xlsx",
            "kind": "xlsx",
            "index": 0,
            "part": "notes",
            "row_count": 9,
            "rows": [],
        }
    ]
    assert document_paste(nothing) == GOLDEN_DOCUMENT_PASTE_NONE


def test_schema_error_bytes():
    err = schema_error("not json at all", {"type": "object"})
    assert err is not None and err.startswith("output was not parseable JSON: ")
    err = schema_error(
        '{"a": "x"}',
        {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]},
    )
    assert err == "JSON does not match schema at 'a': 'x' is not of type 'integer'"
    assert schema_error('{"a": 1}', {"type": "object"}) is None


# The dispatcher's own sentences, 2026-08-20. `tool_failed` is BYTE-IDENTICAL to the literal
# `Agent._dispatch` used to format inline: this move is a refactor of ownership, not a contract
# change, and a golden is what makes that claim falsifiable rather than asserted.
GOLDEN_TOOL_FAILED = "error: lookup failed: boom. fix the arguments and retry."
GOLDEN_TOOL_ARGUMENTS = (
    "error: lookup does not take the arguments it was given. it takes: item, limit. "
    "fix the arguments and retry."
)
GOLDEN_TOOL_ARGUMENTS_NONE = (
    "error: document_list takes no arguments at all. call it with none and retry."
)


def test_tool_failed_bytes():
    assert tool_failed("lookup", ValueError("boom")) == GOLDEN_TOOL_FAILED


def test_tool_arguments_bytes():
    assert tool_arguments("lookup", ["item", "limit"]) == GOLDEN_TOOL_ARGUMENTS
    assert tool_arguments("document_list", []) == GOLDEN_TOOL_ARGUMENTS_NONE


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


def test_loop_guard_defaults():
    """New in the loop-guard cycle — pinned separately, same intent as the pre-split guard."""
    assert profile_default("loop_guard", "inject_at") == 3
    assert profile_default("loop_guard", "warn_at") == 5


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
