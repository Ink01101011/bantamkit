"""Shift-work: the checkpoint schema asset, its loader, and the driver loop."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from bantamkit.assets import AssetNotFound, load_schema
from bantamkit.contract import schema_error

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_ROOT / "tools" / "shiftwork" / "example-checkpoint.json"


@pytest.fixture
def schema():
    return load_schema("shiftwork-checkpoint")


@pytest.fixture
def example():
    return json.loads(EXAMPLE.read_text())


# --- load_schema -----------------------------------------------------------


def test_load_schema_returns_parsed_dict(schema):
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["version"]["const"] == 1


def test_load_schema_missing_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    with pytest.raises(AssetNotFound, match="schema asset not found"):
        load_schema("shiftwork-checkpoint")


def test_shipped_schema_is_a_valid_2020_12_schema(schema):
    jsonschema.Draft202012Validator.check_schema(schema)


# --- the example checkpoint validates --------------------------------------


def test_example_checkpoint_validates(schema, example):
    assert schema_error(json.dumps(example), schema) is None


def test_example_carries_the_two_driver_deltas(example):
    """role (model dispatch) and until_cmd (machine-checkable wait) are why v1 exists."""
    assert {u["role"] for u in example["plan"]["units"]} == {"implementer", "reviewer"}
    process = next(e for e in example["state"]["external"] if e["kind"] == "process")
    assert "until_cmd" in process


def test_replanning_needs_no_schema_change(schema, example):
    """A planner unit is just a unit — that is the whole re-plan mechanism."""
    ckpt = copy.deepcopy(example)
    ckpt["plan"]["units"].append(
        {
            "id": "U9",
            "title": "Re-cut remaining units after QA failures",
            "brief_path": ".shiftwork/briefs/U9.md",
            "status": "todo",
            "role": "planner",
            "depends_on": [],
            "verify": "test -f .shiftwork/briefs/U10.md",
        }
    )
    assert schema_error(json.dumps(ckpt), schema) is None


# --- mutations are rejected ------------------------------------------------


def mutate(example, path, value):
    ckpt = copy.deepcopy(example)
    node = ckpt
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return ckpt


def test_wrong_major_version_rejected(schema, example):
    assert schema_error(json.dumps(mutate(example, ["version"], 2)), schema) is not None


def test_missing_cursor_rejected(schema, example):
    ckpt = copy.deepcopy(example)
    del ckpt["plan"]["cursor"]
    assert schema_error(json.dumps(ckpt), schema) is not None


def test_bad_status_enum_rejected(schema, example):
    ckpt = mutate(example, ["plan", "units", 1, "status"], "in-progress")
    assert schema_error(json.dumps(ckpt), schema) is not None


def test_bad_role_enum_rejected(schema, example):
    ckpt = mutate(example, ["plan", "units", 1, "role"], "qa")
    assert schema_error(json.dumps(ckpt), schema) is not None


def test_non_list_open_questions_rejected(schema, example):
    ckpt = mutate(example, ["handoff", "open_questions"], "none")
    assert schema_error(json.dumps(ckpt), schema) is not None


def test_bad_external_kind_rejected(schema, example):
    ckpt = mutate(example, ["state", "external", 1, "kind"], "webhook")
    assert schema_error(json.dumps(ckpt), schema) is not None


def test_unknown_top_level_key_rejected(schema, example):
    """The checkpoint is an index, not a journal: strays are a smell, not a feature."""
    assert schema_error(json.dumps(mutate(example, ["journal"], [])), schema) is not None


def test_history_entries_allow_extra_annotation(schema, example):
    """history/retro are the free-text space — extra keys there must stay legal."""
    ckpt = copy.deepcopy(example)
    ckpt["history"][0]["seq"] = 4
    assert schema_error(json.dumps(ckpt), schema) is None
