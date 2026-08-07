"""Conformance suite keyed to the asset pack (spec §6).

The phase-2 TS runtime must implement these same checks against the same files.
"""

import json
from collections import Counter

import jsonschema
import yaml

from bantamkit.assets import assets_root

SKILL_BUDGET_BYTES = 6000  # "kept to a page"
SCORING_KINDS = {"json_equal", "contains", "tool_trace"}
FAMILIES = {"structured-extraction", "tool-use", "memory-recall"}
MEMORY_TYPES = {"user", "feedback", "project", "reference"}


def test_tool_assets_are_valid():
    tool_files = sorted((assets_root() / "tools").glob("*.json"))
    assert {f.stem for f in tool_files} >= {"memory_save", "memory_recall"}
    for f in tool_files:
        data = json.loads(f.read_text())
        assert set(data) == {"name", "description", "parameters"}
        assert data["name"] == f.stem
        jsonschema.Draft202012Validator.check_schema(data["parameters"])


def test_rubric_assets_are_valid():
    rubric_files = sorted((assets_root() / "rubrics").glob("*.yaml"))
    assert {f.stem for f in rubric_files} >= {"code-quality", "task-completion"}
    for f in rubric_files:
        data = yaml.safe_load(f.read_text())
        assert data["name"] == f.stem
        assert isinstance(data["threshold"], int) and not isinstance(data["threshold"], bool)
        assert "{task}" in data["prompt"] and "{output}" in data["prompt"]
        jsonschema.Draft202012Validator.check_schema(data["schema"])


def test_skill_assets_fit_budget():
    skill_files = sorted((assets_root() / "skills").glob("*.md"))
    assert {f.stem for f in skill_files} >= {"memory"}
    for f in skill_files:
        size = len(f.read_bytes())
        assert 0 < size <= SKILL_BUDGET_BYTES, f"{f.name} is {size} bytes"


def test_eval_tasks_are_valid():
    task_files = sorted((assets_root() / "evals" / "tasks").glob("*.yaml"))
    assert len(task_files) >= 6
    families = []
    for f in task_files:
        task = yaml.safe_load(f.read_text())
        assert task["name"] == f.stem
        assert task["family"] in FAMILIES
        families.append(task["family"])
        assert task["prompt"].strip()
        assert task["scoring"]["kind"] in SCORING_KINDS
        assert "expected" in task["scoring"]
        # Validate tools
        assert set(task.get("tools", [])) <= {"price_lookup", "stock_lookup"}
        # Validate scoring expected shape per kind
        scoring_kind = task["scoring"]["kind"]
        expected = task["scoring"]["expected"]
        if scoring_kind == "json_equal":
            assert isinstance(expected, dict), f"{f.stem}: json_equal must be dict"
        elif scoring_kind == "contains":
            assert isinstance(expected, list) and len(expected) > 0, (
                f"{f.stem}: contains must be non-empty list"
            )
            assert all(isinstance(v, str) for v in expected), (
                f"{f.stem}: contains must be list of str"
            )
        elif scoring_kind == "tool_trace":
            assert isinstance(expected, list) and len(expected) > 0, (
                f"{f.stem}: tool_trace must be non-empty list"
            )
            assert all(isinstance(v, str) for v in expected), (
                f"{f.stem}: tool_trace must be list of str"
            )
        if "schema" in task:
            jsonschema.Draft202012Validator.check_schema(task["schema"])
        for fact in task.get("memory_setup", []):
            assert fact["type"] in MEMORY_TYPES
            assert set(fact) >= {"type", "name", "description", "body"}
    # Verify all families covered and balanced (at least 2 each)
    family_counts = Counter(families)
    assert set(family_counts.keys()) == FAMILIES  # all three families present
    for family in FAMILIES:
        count = family_counts[family]
        assert count >= 2, f"{family} appears {count} times, need >= 2"


def test_eval_fixture_catalog_shape():
    catalog = json.loads((assets_root() / "evals" / "fixtures" / "catalog.json").read_text())
    # Ensure required items are present
    assert {"widget", "gadget"} <= set(catalog)
    for item, entry in catalog.items():
        assert set(entry) == {"price", "stock"}, item
        # Validate price and stock are numbers (not bool)
        for key in ("price", "stock"):
            v = entry[key]
            assert isinstance(v, (int, float)) and not isinstance(v, bool), (
                f"{item}[{key}] = {v} must be int or float, not bool"
            )
    # Enforce determinism invariant: widget stock value
    assert catalog["widget"]["price"] * catalog["widget"]["stock"] == 100
    assert catalog["gadget"]["price"] > catalog["widget"]["price"]  # shop-cheapest depends on it
    assert catalog["gadget"]["price"] * catalog["gadget"]["stock"] == 540  # shop-gadget-value
