"""Conformance suite keyed to the asset pack (spec §6).

The phase-2 TS runtime must implement these same checks against the same files.
"""

import json

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
        assert isinstance(data["threshold"], int)
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
    families = set()
    for f in task_files:
        task = yaml.safe_load(f.read_text())
        assert task["name"] == f.stem
        assert task["family"] in FAMILIES
        families.add(task["family"])
        assert task["prompt"].strip()
        assert task["scoring"]["kind"] in SCORING_KINDS
        assert "expected" in task["scoring"]
        if "schema" in task:
            jsonschema.Draft202012Validator.check_schema(task["schema"])
        for fact in task.get("memory_setup", []):
            assert fact["type"] in MEMORY_TYPES
            assert set(fact) >= {"type", "name", "description", "body"}
    assert families == FAMILIES  # all three families covered


def test_eval_fixture_catalog_shape():
    catalog = json.loads((assets_root() / "evals" / "fixtures" / "catalog.json").read_text())
    for item, entry in catalog.items():
        assert set(entry) == {"price", "stock"}, item
