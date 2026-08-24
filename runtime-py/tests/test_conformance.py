"""Conformance suite keyed to the asset pack (spec §6).

The phase-2 TS runtime must implement these same checks against the same files.
"""

import json
from collections import Counter

import jsonschema
import yaml

from bantamkit.assets import assets_root
from bantamkit.evalrun import load_tasks

SKILL_BUDGET_BYTES = 6000  # "kept to a page"
SCORING_KINDS = {"json_equal", "contains", "tool_trace"}
# file-nav is forward-declared: its tasks land via calibration promotion.
FAMILIES = {"structured-extraction", "tool-use", "memory-recall", "file-nav"}
CORE_FAMILIES = {"structured-extraction", "tool-use", "memory-recall"}
MEMORY_TYPES = {"user", "feedback", "project", "reference"}
TOOL_SURFACES = {"agent", "mcp"}  # the eval agent's tool list, and `tools/list`


def test_tool_assets_are_valid():
    """The tool-asset shape, pinned at FIVE keys (it pinned three until 2026-08-23).

    The contract grew because three keys could not express a registration. `surfaces`
    says which of the two tool surfaces sharing this directory a tool belongs to — eleven
    files serve two surfaces, and without it a runtime that reads the directory serves
    all eleven. `output_schema` says what the tool returns — every MCP tool advertises one
    over the wire, so a manifest without it describes a surface the server does not have.

    The assertion is EXACT (`==`, not `>=`) for the same reason it always was: a manifest
    an implementer cannot read to completion is not a manifest, and an unannounced key is
    a contract change that no port would learn about until it diverged.
    """
    tool_files = sorted((assets_root() / "tools").glob("*.json"))
    assert {f.stem for f in tool_files} >= {"memory_save", "memory_recall"}
    for f in tool_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        assert set(data) == {"name", "description", "surfaces", "parameters", "output_schema"}
        assert data["name"] == f.stem
        jsonschema.Draft202012Validator.check_schema(data["parameters"])

        surfaces = data["surfaces"]
        assert surfaces, f.stem
        assert set(surfaces) <= TOOL_SURFACES, (f.stem, surfaces)
        assert surfaces == sorted(set(surfaces)), (f.stem, surfaces)

        # Only the MCP surface has an output schema to state. An agent-side tool is
        # handed to a model as name/description/parameters and advertises no return
        # shape, so `null` is the honest entry — and a REQUIRED one, because an absent
        # key and a deliberate "there is none" must not read the same to a port.
        if "mcp" in surfaces:
            assert data["output_schema"] is not None, f.stem
            jsonschema.Draft202012Validator.check_schema(data["output_schema"])
        else:
            assert data["output_schema"] is None, f.stem


def test_rubric_assets_are_valid():
    rubric_files = sorted((assets_root() / "rubrics").glob("*.yaml"))
    assert {f.stem for f in rubric_files} >= {"code-quality", "task-completion"}
    for f in rubric_files:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
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
    assert len(task_files) >= 22
    families = []
    for f in task_files:
        task = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert task["name"] == f.stem
        assert task["family"] in FAMILIES
        families.append(task["family"])
        assert task["prompt"].strip()
        assert task["scoring"]["kind"] in SCORING_KINDS
        assert "expected" in task["scoring"]
        # Validate tools
        allowed_tools = {"price_lookup", "stock_lookup", "read_file", "list_files"}
        assert set(task.get("tools", [])) <= allowed_tools
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
    assert set(family_counts.keys()) <= FAMILIES
    assert CORE_FAMILIES <= set(family_counts.keys())  # core families always present
    for family, count in family_counts.items():
        assert count >= 2, f"{family} appears {count} times, need >= 2"


def test_eval_fixture_catalog_shape():
    catalog = json.loads(
        (assets_root() / "evals" / "fixtures" / "catalog.json").read_text(encoding="utf-8")
    )
    # Ensure required items are present
    assert {"widget", "gadget", "doohickey", "sprocket"} <= set(catalog)
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


def test_workspace_tasks_are_well_formed():
    """Tasks using the workspace file tools carry a valid workspace; others carry none."""
    for task in load_tasks():
        uses_workspace = any(t in ("read_file", "list_files") for t in task.get("tools", []))
        if not uses_workspace:
            assert "workspace" not in task, task["name"]
            continue
        assert "workspace" in task, task["name"]
        ws = task["workspace"]
        assert isinstance(ws, dict) and ws, f"{task['name']}: workspace must be non-empty"
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in ws.items()), task["name"]
        assert task["family"] == "file-nav", task["name"]
