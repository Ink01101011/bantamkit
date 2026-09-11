"""Shift-work: the checkpoint schema asset, its loader, the driver loop, the MCP-flavor ops."""

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
from conftest import windows_cannot_construct

from bantamkit import shiftwork as ops
from bantamkit.assets import AssetNotFound, load_schema
from bantamkit.contract import schema_error

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIFTWORK = REPO_ROOT / "tools" / "shiftwork"
EXAMPLE = SHIFTWORK / "example-checkpoint.json"
CODEFIX = SHIFTWORK / "example-codefix-checkpoint.json"

sys.path.insert(0, str(SHIFTWORK))
import driver as shiftwork  # noqa: E402  (repo tool, not a package on the wheel)


@pytest.fixture
def schema():
    return load_schema("shiftwork-checkpoint")


@pytest.fixture
def example():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


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


def test_history_beyond_five_entries_rejected(schema, example):
    """The ring buffer is structural: a journal in `history` is a rejected file."""
    ckpt = copy.deepcopy(example)
    entry = ckpt["history"][0]
    six = [dict(entry, unit=f"U{i}") for i in range(6)]
    assert schema_error(json.dumps(mutate(example, ["history"], six)), schema) is not None
    assert schema_error(json.dumps(mutate(example, ["history"], six[:5])), schema) is None


# --- MCP flavor: clock_in --------------------------------------------------


def write_checkpoint(tmp_path, ckpt):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(ckpt) if isinstance(ckpt, dict) else ckpt, encoding="utf-8")
    return path


def test_clock_in_returns_the_cursor_units_brief_faithfully(tmp_path, example):
    path = write_checkpoint(tmp_path, example)
    brief = ops.clock_in(str(path))
    assert brief["result"] == "brief"
    assert brief["unit"] == example["plan"]["units"][1]  # U3, the cursor unit, verbatim
    assert brief["role"] == "implementer"
    assert brief["invariants"] == example["job"]["constraints"]
    assert brief["handoff"] == example["handoff"]
    assert brief["do_not"] == example["handoff"]["do_not"]
    assert brief["files"] == example["state"]["artifacts"]


def test_clock_in_escalates_on_open_questions(tmp_path, example):
    example["handoff"]["open_questions"] = ["Which layer owns SCHEMA_INSTRUCTION?"]
    r = ops.clock_in(str(write_checkpoint(tmp_path, example)))
    assert r["result"] == "escalate"
    assert "Which layer owns SCHEMA_INSTRUCTION?" in r["reason"]
    assert r["open_questions"] == example["handoff"]["open_questions"]


def test_clock_in_refuses_success_when_all_units_terminal(tmp_path, example):
    for unit in example["plan"]["units"]:
        unit["status"] = "dropped" if unit["id"] == "U4" else "done"
    r = ops.clock_in(str(write_checkpoint(tmp_path, example)))
    assert r == {"result": "success", "reason": "all units done or dropped"}


def test_clock_in_errors_on_unparseable_checkpoint(tmp_path):
    r = ops.clock_in(str(write_checkpoint(tmp_path, "{not json at all")))
    assert r["result"] == "error"
    assert "not parseable as JSON" in r["reason"]


def test_clock_in_errors_on_schema_invalid_checkpoint(tmp_path, example):
    example["version"] = 2
    r = ops.clock_in(str(write_checkpoint(tmp_path, example)))
    assert r["result"] == "error"
    assert "checkpoint invalid" in r["reason"]


def test_clock_in_errors_on_missing_file(tmp_path):
    r = ops.clock_in(str(tmp_path / "nope.json"))
    assert r["result"] == "error"
    assert "unreadable" in r["reason"]


def test_clock_in_escalates_on_dangling_cursor(tmp_path, example):
    example["plan"]["cursor"] = "U99"
    r = ops.clock_in(str(write_checkpoint(tmp_path, example)))
    assert r == {"result": "escalate", "reason": "cursor U99 names no unit"}


# --- MCP flavor: clock_out --------------------------------------------------


ACCOUNTING = {"tokens": 1234, "duration": 88.2, "model": "haiku"}


def read_log(path):
    log = Path(str(path) + ".log.jsonl")
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_clock_out_round_trips_a_valid_update(tmp_path, schema, example):
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(
        str(path),
        "U3",
        "done",
        {"next_action": "Review the U3 diff per briefs/U4.md."},
        {"unit": "U3", "outcome": "done", "notes": "moved in one commit"},
        ACCOUNTING,
    )
    assert r["result"] == "ok"
    assert r["cursor"] == "U4"
    written = path.read_text(encoding="utf-8")
    assert schema_error(written, schema) is None  # the re-read passes the full schema
    doc = json.loads(written)
    assert doc["plan"]["units"][1]["status"] == "done"
    assert doc["plan"]["cursor"] == "U4"
    assert doc["handoff"]["next_action"] == "Review the U3 diff per briefs/U4.md."
    assert doc["history"][-1]["unit"] == "U3"


def test_clock_out_rejects_bad_status_enum_without_writing(tmp_path, example):
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    r = ops.clock_out(str(path), "U3", "in-progress", {}, {"unit": "U3", "outcome": "done"})
    assert r["result"] == "error"
    assert "refused to write" in r["reason"]
    assert path.read_bytes() == before  # atomicity: failure leaves the prior bytes
    assert read_log(path) == []


def test_clock_out_rejects_overlong_history_ring_without_writing(tmp_path, example):
    entry = {"unit": "U0", "outcome": "done"}
    example["history"] = [dict(entry, unit=f"U{i}") for i in range(6)]
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"})
    assert r["result"] == "error"
    assert "checkpoint invalid" in r["reason"]
    assert path.read_bytes() == before
    assert read_log(path) == []


def test_clock_out_rejects_invalid_handoff_patch_without_writing(tmp_path, example):
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    entry = {"unit": "U3", "outcome": "done"}
    r = ops.clock_out(str(path), "U3", "done", {"journal": "strays are a smell"}, entry)
    assert r["result"] == "error"
    assert path.read_bytes() == before
    assert read_log(path) == []


def test_clock_out_pushes_the_history_ring_with_driver_identical_truncation(
    tmp_path, schema, example
):
    example["history"] = [{"unit": f"H{i}", "outcome": "done"} for i in range(5)]
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"})
    assert r["result"] == "ok"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert [h["unit"] for h in doc["history"]] == ["H1", "H2", "H3", "H4", "U3"]
    assert schema_error(path.read_text(encoding="utf-8"), schema) is None


def test_clock_out_unknown_unit_errors_without_writing(tmp_path, example):
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    r = ops.clock_out(str(path), "U99", "done", {}, {"unit": "U99", "outcome": "done"})
    assert r == {"result": "error", "reason": "unit U99 is not in the plan"}
    assert path.read_bytes() == before
    assert read_log(path) == []


def test_clock_out_rejects_a_non_cursor_unit(tmp_path, example):
    """The contract is execute-the-cursor-unit (driver parity), never pick-a-unit.

    The accept side is the round-trip test above: U3 IS the cursor and clocks out fine.
    """
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    r = ops.clock_out(str(path), "U4", "done", {}, {"unit": "U4", "outcome": "done"})
    assert r == {"result": "error", "reason": "unit U4 is not the cursor unit U3"}
    assert path.read_bytes() == before
    assert read_log(path) == []


@windows_cannot_construct(
    because=(
        "the rig is `dir.chmod(0o555)`, and clearing a DIRECTORY's write bit is a POSIX "
        "permission fact with no Windows counterpart -- `chmod` there toggles the "
        "read-only attribute on files and is a no-op for directories, so the write "
        "SUCCEEDS and nothing raises. MEASURED on real Windows, not inferred: "
        "windows-latest / CPython 3.12.10, CI run 32508028806 of 2026-08-21, this node "
        "read `assert 'ok' == 'error'`"
    ),
    unmeasured=(
        "that an OSError on the WRITE path comes back as a structured refusal carrying "
        "'unwritable' with the checkpoint's prior bytes and an empty log intact, rather "
        "than as an exception out of `clock_out`. The sibling node "
        "`test_clock_out_unwritable_log_leaves_the_checkpoint_untouched` still covers "
        "the log leg on Windows (a directory where a file belongs is portable); what is "
        "uncovered there is the CHECKPOINT leg's own refusal"
    ),
)
def test_clock_out_read_only_dir_is_a_structured_refusal(tmp_path, example):
    """A write-path OSError mirrors the read side: structured error, never an exception."""
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    tmp_path.chmod(0o555)
    try:
        r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"})
    finally:
        tmp_path.chmod(0o755)
    assert r["result"] == "error"
    assert "unwritable" in r["reason"]
    assert path.read_bytes() == before
    assert read_log(path) == []


def test_clock_out_unwritable_log_leaves_the_checkpoint_untouched(tmp_path, example):
    """Log-then-commit, leg one: if the accounting line cannot land, nothing lands."""
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    Path(str(path) + ".log.jsonl").mkdir()  # a directory: open("a") raises OSError
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"})
    assert r["result"] == "error"
    assert "accounting log unwritable" in r["reason"]
    assert path.read_bytes() == before


def test_clock_out_commit_failure_keeps_prior_bytes_and_the_orphan_log_line(
    tmp_path, monkeypatch, example
):
    """Log-then-commit, leg two: a failed rename loses the commit, never the accounting.

    The orphan line is the documented recovery semantic — re-reading the
    checkpoint shows its unit still non-terminal at the cursor.
    """
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()

    def refuse(self, target):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(Path, "replace", refuse)
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
    assert r["result"] == "error"
    assert "uncommitted" in r["reason"]
    assert path.read_bytes() == before  # atomicity: the prior checkpoint survives
    lines = read_log(path)
    assert len(lines) == 1 and lines[0]["unit"] == "U3"  # the accounting line landed
    assert not Path(str(path) + ".tmp").exists()  # the temp file is cleaned up
    assert ops.clock_in(str(path))["unit"]["id"] == "U3"  # the orphan is detectable


def test_clock_out_appends_one_accounting_line_per_success(tmp_path, example):
    path = write_checkpoint(tmp_path, example)
    ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
    ops.clock_out(str(path), "U4", "done", {}, {"unit": "U4", "outcome": "done"})
    lines = read_log(path)
    assert len(lines) == 2
    first, second = lines
    assert first["unit"] == "U3" and first["role"] == "implementer" and first["status"] == "done"
    assert first["tokens"] == 1234 and first["duration"] == 88.2 and first["model"] == "haiku"
    assert first["ts"].endswith("Z")
    assert set(second) == {"ts", "unit", "role", "status"}  # accounting omitted -> base shape
    assert second["role"] == "reviewer"


def test_blocked_clock_out_keeps_the_cursor_on_the_blocked_unit(tmp_path, example):
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(
        str(path),
        "U3",
        "blocked",
        {"open_questions": ["head_sha moved under us"]},
        {"unit": "U3", "outcome": "blocked"},
    )
    assert r["result"] == "ok"
    assert r["cursor"] == "U3"  # non-terminal: still THE next unit
    assert ops.clock_in(str(path))["result"] == "escalate"


def test_full_cycle_on_the_v1_example(tmp_path, example):
    """Bar 2: the shipped example drives clock_in -> clock_out -> clock_in."""
    path = write_checkpoint(tmp_path, example)
    first = ops.clock_in(str(path))
    assert first["result"] == "brief" and first["unit"]["id"] == "U3"
    out = ops.clock_out(
        str(path),
        "U3",
        "done",
        {"next_action": "Review the extraction diff per briefs/U4.md."},
        {"unit": "U3", "outcome": "done"},
        ACCOUNTING,
    )
    assert out["result"] == "ok"
    second = ops.clock_in(str(path))
    assert second["result"] == "brief" and second["unit"]["id"] == "U4"
    assert second["role"] == "reviewer"
    assert ops.clock_out(str(path), "U4", "done", {}, {"unit": "U4", "outcome": "done"})[
        "result"
    ] == "ok"
    assert ops.clock_in(str(path))["result"] == "success"
    assert len(read_log(path)) == 2


# --- MCP flavor: clock_out, the AS-2 role/model check ------------------------
#
# `job.roles` (J46-7, contract 3fe21ac) maps a role to the model identifiers a
# session in that role may report. A role the map does not name -- and a
# checkpoint with no map at all -- is unconstrained, so these tests carry the
# before-and-after in one place: the refusal, and the four shapes that must
# still behave exactly as they did before the feature existed.
#
# The sentences are pinned as TEXT, not as "an error was raised": the rule
# lives in one place per runtime and is copied to the other side, so a
# differential conformance case cannot see a change to it (J46-7 measured
# that on the schema itself). Per-side literals are the teeth.

ROLES = {"implementer": ["claude-opus-5", "claude-sonnet-5"], "reviewer": ["claude-opus-5"]}


def test_clock_out_refuses_a_model_the_role_is_not_allowed(tmp_path, example):
    """U3 is the implementer cursor unit; haiku is not on the implementer's list."""
    example["job"]["roles"] = ROLES
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    r = ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
    )
    assert r == {
        "result": "error",
        "reason": (
            "unit U3 in role implementer reported model haiku, which "
            "job.roles.implementer does not allow: claude-opus-5, claude-sonnet-5"
        ),
    }
    # Nothing was written: not the checkpoint, and not the accounting line. The
    # check is BEFORE the log-then-commit pair, so there is no orphan line
    # claiming a model that was rejected.
    assert path.read_bytes() == before
    assert not Path(str(path) + ".log.jsonl").exists()
    assert read_log(path) == []
    assert ops.clock_in(str(path))["unit"]["id"] == "U3"  # the cursor never moved


def test_clock_out_accepts_a_model_on_the_roles_list(tmp_path, example):
    example["job"]["roles"] = ROLES
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(
        str(path),
        "U3",
        "done",
        {},
        {"unit": "U3", "outcome": "done"},
        dict(ACCOUNTING, model="claude-sonnet-5"),
    )
    assert r["result"] == "ok" and r["cursor"] == "U4"
    assert read_log(path)[-1]["model"] == "claude-sonnet-5"


def test_clock_out_compares_the_model_string_exactly(tmp_path, example):
    """No normalisation, no prefix match, no strip-the-brackets rule (the J46-7 ruling).

    Sibling jobs on this machine log `claude-opus-5[1m]`; the map lists
    `claude-opus-5`. Those are different strings and the refusal says so.
    """
    example["job"]["roles"] = ROLES
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(
        str(path),
        "U3",
        "done",
        {},
        {"unit": "U3", "outcome": "done"},
        {"model": "claude-opus-5[1m]"},
    )
    assert r["result"] == "error"
    assert "reported model claude-opus-5[1m]" in r["reason"]
    assert read_log(path) == []


def test_clock_out_refuses_a_constrained_role_that_reports_no_model(tmp_path, example):
    """Case 3, decided: a role the map names must SAY which model it ran.

    Otherwise the rule is enforced only against the honest -- omit the field
    and the list stops applying.
    """
    example["job"]["roles"] = ROLES
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    r = ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, {"tokens": 1234}
    )
    assert r == {
        "result": "error",
        "reason": (
            "unit U3 in role implementer reported no model, but "
            "job.roles.implementer allows only: claude-opus-5, claude-sonnet-5"
        ),
    }
    assert path.read_bytes() == before
    assert read_log(path) == []


def test_clock_out_refuses_a_constrained_role_with_no_accounting_at_all(tmp_path, example):
    """Same refusal for a missing accounting object as for a missing model key."""
    example["job"]["roles"] = ROLES
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"})
    assert r["result"] == "error"
    assert "reported no model" in r["reason"]
    assert read_log(path) == []


def test_clock_out_is_unchanged_when_the_checkpoint_declares_no_roles(tmp_path, example):
    """Property 2: a checkpoint written before this feature clocks out unchanged.

    The shipped example has no `job.roles`, and ACCOUNTING names `haiku` --
    a model no list anywhere would allow.
    """
    assert "roles" not in example["job"]
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
    )
    assert r["result"] == "ok" and r["cursor"] == "U4"
    assert read_log(path)[-1]["model"] == "haiku"


def test_clock_out_is_unchanged_for_a_role_the_map_does_not_name(tmp_path, example):
    """An absent role is unconstrained (the schema's shape, deliberately preserved).

    U3 is the implementer; this map names only the reviewer, so U3 may report
    anything -- including nothing at all.
    """
    example["job"]["roles"] = {"reviewer": ["claude-opus-5"]}
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
    )
    assert r["result"] == "ok"
    assert read_log(path)[-1]["model"] == "haiku"


def test_clock_out_role_check_runs_after_the_cursor_check(tmp_path, example):
    """A non-cursor unit is refused for being non-cursor, not for its model.

    Ordering matters for the message a human acts on: the structural refusal
    that was already there keeps its sentence.
    """
    example["job"]["roles"] = ROLES
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(str(path), "U4", "done", {}, {"unit": "U4", "outcome": "done"}, ACCOUNTING)
    assert r == {"result": "error", "reason": "unit U4 is not the cursor unit U3"}
    assert read_log(path) == []


def test_roles_refusal_does_not_fire_on_clock_in_or_status(tmp_path, example):
    """AS-2 constrains what a unit REPORTS, so it can only be checked at clock-out."""
    example["job"]["roles"] = ROLES
    path = write_checkpoint(tmp_path, example)
    assert ops.clock_in(str(path))["result"] == "brief"
    assert ops.status(str(path))["result"] == "status"


# --- AS-2, the two J46-10 rulings -------------------------------------------


def test_the_allowed_list_is_rendered_in_checkpoint_order_not_sorted(tmp_path, example):
    """RULING 2. `ROLES` above lists its models ALPHABETICALLY, so every test that
    uses it passes whether the renderer joins in checkpoint order or in
    `sorted()` order -- `tests-that-pick-the-input-that-cannot-fail` by name.
    runtime-ts already carried a `['zzz-last', 'aaa-first']` case and this side
    did not, so a `sorted()` introduced HERE passed this suite, and introduced in
    both passed the differential too. This is the mirror.
    """
    example["job"]["roles"] = {"implementer": ["zzz-last", "aaa-first"]}
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
    )
    assert r["reason"] == (
        "unit U3 in role implementer reported model haiku, "
        "which job.roles.implementer does not allow: zzz-last, aaa-first"
    )


def _pack_without_min_items(tmp_path, schema):
    """An asset pack whose checkpoint schema has lost `minItems: 1` on the roles list.

    The ONLY way to reach the empty-list branch of `_model_refusal`: with the
    shipped schema, `roles: {implementer: []}` is refused during the read and the
    check is never called. `BANTAMKIT_ASSETS` is the same override both runtimes
    honour, so the Node half of this ruling is measured the same way.
    """
    mutated = copy.deepcopy(schema)
    del mutated["properties"]["job"]["properties"]["roles"]["additionalProperties"]["minItems"]
    root = tmp_path / "pack"
    (root / "schemas").mkdir(parents=True)
    (root / "schemas" / "shiftwork-checkpoint.json").write_text(
        json.dumps(mutated), encoding="utf-8"
    )
    return root


def test_an_empty_allowed_list_still_refuses_when_the_schema_stops_catching_it(
    tmp_path, monkeypatch, schema, example
):
    """RULING 1, decided for J46-9: the check FAILS CLOSED on an empty list.

    `if not allowed` used to read `[]` as unconstrained, so the day `minItems`
    moves, an empty list becomes a silent opt-out of the rule the checkpoint just
    declared. The declaration is the KEY: a role the map names is held to its
    list, and an empty list allows nothing.

    This test is what makes that a measurement rather than a promise -- it drives
    the real `clock_out` against a pack whose schema no longer refuses `[]`.
    """
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(_pack_without_min_items(tmp_path, schema)))
    example["job"]["roles"] = {"implementer": []}
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    assert ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
    ) == {
        "result": "error",
        "reason": (
            "unit U3 in role implementer reported model haiku, "
            "which job.roles.implementer does not allow: "
        ),
    }
    # And no model is not an escape either.
    assert ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, {"tokens": 1}
    ) == {
        "result": "error",
        "reason": (
            "unit U3 in role implementer reported no model, "
            "but job.roles.implementer allows only: "
        ),
    }
    assert path.read_bytes() == before
    assert read_log(path) == []


def test_the_mutated_pack_really_is_the_thing_that_lets_the_empty_list_through(
    tmp_path, monkeypatch, schema, example
):
    """The companion that keeps the test above honest: with the SHIPPED schema the
    same document never reaches the model check at all, and the two refusals are
    different sentences. A gate has to be confirmed to reach the thing it checks.
    """
    example["job"]["roles"] = {"implementer": []}
    path = write_checkpoint(tmp_path, example)
    assert ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
    ) == {
        "result": "error",
        "reason": (
            "checkpoint invalid: JSON does not match schema at "
            "'job/roles/implementer': [] should be non-empty"
        ),
    }
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(_pack_without_min_items(tmp_path, schema)))
    assert "does not allow" in ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
    )["reason"]


def test_an_absent_role_and_an_empty_list_are_different_inputs(
    tmp_path, monkeypatch, schema, example
):
    """They look alike and they are not the same case. Under the SAME pack, where
    neither is refused by the schema, an absent role clocks out and `[]` refuses.
    """
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(_pack_without_min_items(tmp_path, schema)))
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    def with_roles(name, roles):
        document = copy.deepcopy(example)
        document["job"]["roles"] = roles
        return write_checkpoint(tmp_path / name, document)

    absent = with_roles("a", {"reviewer": ["claude-opus-5"]})
    empty = with_roles("b", {"implementer": []})
    args = ("U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
    assert ops.clock_out(str(absent), *args)["result"] == "ok"
    assert ops.clock_out(str(empty), *args)["result"] == "error"


# --- J47-4: a roles value this code cannot read is not a licence -------------


def _pack_with_unconstrained_roles_values(tmp_path, schema):
    """An asset pack whose checkpoint schema no longer says what a roles value IS.

    `additionalProperties: true` on `job.roles` is the loosest the shared asset
    could ever drift to, so it is the instrument that reaches every non-list
    shape at once. Same `BANTAMKIT_ASSETS` override the empty-list ruling uses,
    for the same reason: the check must hold without the schema's help.
    """
    mutated = copy.deepcopy(schema)
    mutated["properties"]["job"]["properties"]["roles"]["additionalProperties"] = True
    root = tmp_path / "anyroles"
    (root / "schemas").mkdir(parents=True)
    (root / "schemas" / "shiftwork-checkpoint.json").write_text(
        json.dumps(mutated), encoding="utf-8"
    )
    return root


NOT_A_MODEL_LIST = [
    pytest.param("claude-opus-5", id="str"),
    pytest.param({"a": 1}, id="dict"),
    pytest.param(5, id="int"),
    pytest.param(None, id="null"),
    pytest.param(True, id="bool"),
    pytest.param([5], id="list-of-int"),
    pytest.param(["ok", None], id="list-with-a-non-string"),
]


@pytest.mark.parametrize("value", NOT_A_MODEL_LIST)
def test_a_roles_value_that_is_not_a_list_of_model_names_refuses_closed(
    tmp_path, monkeypatch, schema, example, value
):
    """The J46-10 ruling's other half. A role the map NAMES is constrained by what
    it names, and a value this code cannot read as a list of model identifiers
    names nothing -- so it allows nothing.

    Measured before the fix, with `accounting['model'] = 'haiku'`: `str` and
    `dict` refused with the declared value mangled into single characters
    (`', '.join` over a string iterates CHARACTERS), and `int`, `null`, `bool`
    and a list holding a non-string all died with an uncaught `TypeError` out of
    `clock_out` -- no structured answer at all, which is the one exit shape the
    ruling forbids.
    """
    monkeypatch.setenv(
        "BANTAMKIT_ASSETS", str(_pack_with_unconstrained_roles_values(tmp_path, schema))
    )
    example["job"]["roles"] = {"implementer": value}
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    assert ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
    ) == {
        "result": "error",
        "reason": (
            "unit U3 in role implementer cannot clock out: job.roles.implementer "
            "is not a list of model identifiers, so it allows no model"
        ),
    }
    # Offering no model is the same refusal: which model was reported cannot
    # matter when the declaration that would judge it is unreadable.
    assert ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, {"tokens": 1}
    ) == {
        "result": "error",
        "reason": (
            "unit U3 in role implementer cannot clock out: job.roles.implementer "
            "is not a list of model identifiers, so it allows no model"
        ),
    }
    assert path.read_bytes() == before
    assert read_log(path) == []


def test_an_unreadable_roles_value_never_mangles_the_declaration_into_characters(
    tmp_path, monkeypatch, schema, example
):
    """The specific pre-fix defect, pinned so it cannot come back: a string value
    refused, but rendered `claude-opus-5` as `c, l, a, u, d, e, -, o, p, u, s, -, 5`
    -- a refusal sentence that misdescribes the checkpoint it is refusing.
    """
    monkeypatch.setenv(
        "BANTAMKIT_ASSETS", str(_pack_with_unconstrained_roles_values(tmp_path, schema))
    )
    example["job"]["roles"] = {"implementer": "claude-opus-5"}
    path = write_checkpoint(tmp_path, example)
    reason = ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
    )["reason"]
    assert "c, l, a, u" not in reason


def test_the_relaxed_pack_is_what_lets_a_non_list_roles_value_through(
    tmp_path, monkeypatch, schema, example
):
    """The companion that keeps the tests above honest, the empty-list ruling's own
    companion by name: with the SHIPPED schema the same document is refused during
    the read and never reaches the model check, so the two refusals are different
    sentences and the gate is confirmed to reach the thing it checks.
    """
    example["job"]["roles"] = {"implementer": 5}
    path = write_checkpoint(tmp_path, example)
    assert ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
    ) == {
        "result": "error",
        "reason": (
            "checkpoint invalid: JSON does not match schema at "
            "'job/roles/implementer': 5 is not of type 'array'"
        ),
    }
    monkeypatch.setenv(
        "BANTAMKIT_ASSETS", str(_pack_with_unconstrained_roles_values(tmp_path, schema))
    )
    assert "is not a list of model identifiers" in ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
    )["reason"]


def test_an_empty_list_is_still_the_j46_10_sentence_not_the_unreadable_one(
    tmp_path, monkeypatch, schema, example
):
    """`[]` IS a list of model identifiers -- an empty one. It stays on the J46-10
    branch with the sentence that ruling pinned, and does not fall into the
    unreadable-declaration branch added here.
    """
    monkeypatch.setenv(
        "BANTAMKIT_ASSETS", str(_pack_with_unconstrained_roles_values(tmp_path, schema))
    )
    example["job"]["roles"] = {"implementer": []}
    path = write_checkpoint(tmp_path, example)
    assert ops.clock_out(
        str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
    )["reason"] == (
        "unit U3 in role implementer reported model haiku, "
        "which job.roles.implementer does not allow: "
    )


# --- MCP flavor: status -----------------------------------------------------


def test_status_summarizes_without_mutating(tmp_path, example):
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    r = ops.status(str(path))
    assert r == {
        "result": "status",
        "cursor": "U3",
        "units": {"done": 1, "todo": 2},
        "open_questions": 0,
        "last_history": example["history"][-1],
    }
    assert path.read_bytes() == before
    assert read_log(path) == []


def test_status_reports_empty_history_as_none(tmp_path, example):
    example["history"] = []
    r = ops.status(str(write_checkpoint(tmp_path, example)))
    assert r["last_history"] is None


def test_status_errors_on_invalid_checkpoint(tmp_path):
    r = ops.status(str(write_checkpoint(tmp_path, "{not json at all")))
    assert r["result"] == "error"


# --- the code-fix example checkpoint ----------------------------------------


def test_codefix_example_validates(schema):
    assert schema_error(CODEFIX.read_text(encoding="utf-8"), schema) is None


def test_codefix_example_shapes_the_job(schema):
    ckpt = json.loads(CODEFIX.read_text(encoding="utf-8"))
    units = ckpt["plan"]["units"]
    assert [u["id"] for u in units] == ["CF1", "CF2", "CF3", "CF4"]
    assert ckpt["plan"]["cursor"] == "CF1"
    # reproduce -> locate -> fix are implementer; the fix is gated by the reviewer unit.
    assert [u["role"] for u in units] == ["implementer", "implementer", "implementer", "reviewer"]
    brief = ops.clock_in(str(CODEFIX))
    assert brief["result"] == "brief" and brief["unit"]["id"] == "CF1"


# --- driver: harness -------------------------------------------------------


class Done:
    def __init__(self, returncode=0):
        self.returncode = returncode


class FakeRunner:
    """Stands in for subprocess.run: shell probes, scripted sessions, notifications."""

    def __init__(self, sessions=(), until_results=()):
        self.sessions = list(sessions)
        self.until_results = list(until_results)
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if isinstance(cmd, str):  # until_cmd runs with shell=True
            code = self.until_results.pop(0) if self.until_results else 0
            return Done(code)
        if cmd and cmd[0] == "claude":
            behavior = self.sessions.pop(0) if self.sessions else None
            return Done(behavior() or 0 if callable(behavior) else 0)
        return Done(0)  # notify_cmd

    @property
    def sessions_run(self):
        return [c for c in self.calls if not isinstance(c, str) and c[0] == "claude"]

    @property
    def notifications(self):
        return [c for c in self.calls if not isinstance(c, str) and c[0] == "notify"]


class FakeClock:
    def __init__(self, step=1.0):
        self.t = 0.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


def base_checkpoint():
    ckpt = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    ckpt["plan"]["units"] = [u for u in ckpt["plan"]["units"] if u["id"] in {"U1", "U3"}]
    ckpt["state"]["external"] = []
    return ckpt


def make_driver(tmp_path, ckpt, *, sessions=(), until=(), alive=False, **config):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(ckpt) if isinstance(ckpt, dict) else ckpt, encoding="utf-8")
    runner = FakeRunner(sessions=sessions, until_results=until)
    sleeps = []
    config.setdefault("notify_cmd", ["notify"])
    driver = shiftwork.Driver(
        path,
        shiftwork.Config.from_dict(config),
        runner=runner,
        sleep=sleeps.append,
        clock=FakeClock(),
        now=lambda: 1770000000.0,
        pid=4242,
        is_alive=lambda pid: alive,
        out=None,
    )
    return SimpleNamespace(driver=driver, path=path, runner=runner, sleeps=sleeps, dir=tmp_path)


def edit(path, **changes):
    """Return a session behavior that mutates the checkpoint (i.e. clocks out)."""

    def behave():
        ckpt = json.loads(path.read_text(encoding="utf-8"))
        if changes.get("finish"):
            for unit in ckpt["plan"]["units"]:
                unit["status"] = "done"
        if changes.get("note"):
            ckpt["handoff"]["next_action"] = changes["note"]
        if changes.get("escalate"):
            ckpt["handoff"]["open_questions"] = [changes["escalate"]]
        path.write_text(json.dumps(ckpt), encoding="utf-8")
        return changes.get("code", 0)

    return behave


def noop(code=0):
    """A session that exits without writing the checkpoint — no progress."""
    return lambda: code


def log_lines(harness):
    log = harness.dir / "driver-log.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def driver_state(harness):
    return json.loads((harness.dir / "driver-state.json").read_text(encoding="utf-8"))


# --- driver: exits ---------------------------------------------------------


def test_success_when_all_units_terminal(tmp_path):
    ckpt = base_checkpoint()
    for unit in ckpt["plan"]["units"]:
        unit["status"] = "dropped"
    h = make_driver(tmp_path, ckpt)
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert h.runner.sessions_run == []
    assert h.runner.notifications  # the driver always notifies on a terminal exit


def test_success_after_a_session_finishes_the_job(tmp_path):
    h = make_driver(tmp_path, base_checkpoint())
    h.runner.sessions = [edit(h.path, finish=True)]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert len(h.runner.sessions_run) == 1
    assert driver_state(h)["sessions"] == 1


def test_escalate_on_open_questions(tmp_path):
    ckpt = base_checkpoint()
    ckpt["handoff"]["open_questions"] = ["Which layer owns SCHEMA_INSTRUCTION?"]
    h = make_driver(tmp_path, ckpt)
    assert h.driver.run() == shiftwork.EXIT_ESCALATE
    assert h.runner.sessions_run == []


def test_escalate_when_a_session_raises_an_open_question(tmp_path):
    h = make_driver(tmp_path, base_checkpoint())
    h.runner.sessions = [edit(h.path, escalate="head_sha moved under us")]
    assert h.driver.run() == shiftwork.EXIT_ESCALATE
    assert len(h.runner.sessions_run) == 1


def test_escalate_on_unparseable_checkpoint_without_overwriting(tmp_path):
    h = make_driver(tmp_path, "{not json at all")
    before = h.path.read_bytes()
    assert h.driver.run() == shiftwork.EXIT_ESCALATE
    assert h.path.read_bytes() == before
    assert h.runner.sessions_run == []


def test_escalate_on_unknown_major_version(tmp_path):
    ckpt = base_checkpoint()
    ckpt["version"] = 2
    h = make_driver(tmp_path, ckpt)
    assert h.driver.run() == shiftwork.EXIT_ESCALATE


def test_escalate_on_dangling_cursor(tmp_path):
    ckpt = base_checkpoint()
    ckpt["plan"]["cursor"] = "U99"
    h = make_driver(tmp_path, ckpt)
    assert h.driver.run() == shiftwork.EXIT_ESCALATE


def test_budget_exit_on_session_cap(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_sessions=1)
    h.runner.sessions = [edit(h.path, note="partial work landed")]
    assert h.driver.run() == shiftwork.EXIT_BUDGET
    assert len(h.runner.sessions_run) == 1


def test_budget_exit_on_wall_clock_cap(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_wall_clock_seconds=1)
    assert h.driver.run() == shiftwork.EXIT_BUDGET
    assert h.runner.sessions_run == []


def test_stalled_after_max_retries_of_no_progress(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_retries=2)
    h.runner.sessions = [noop(), noop(), noop(), noop()]
    assert h.driver.run() == shiftwork.EXIT_STALLED
    assert len(h.runner.sessions_run) == 3  # max_retries + 1
    assert driver_state(h)["retries"] == {"U3": 3}


def test_clean_exit_without_clock_out_counts_as_a_retry(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_retries=0)
    h.runner.sessions = [noop(0)]
    assert h.driver.run() == shiftwork.EXIT_STALLED
    assert log_lines(h)[0]["exit"] == 0
    assert log_lines(h)[0]["progressed"] is False


def test_hash_delta_resets_the_retry_counter(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_retries=1)
    h.runner.sessions = [
        noop(),  # retries[U3] = 1
        edit(h.path, note="landed half the unit"),  # progress -> reset
        noop(),  # retries[U3] = 1 again, not 2
        edit(h.path, finish=True),
    ]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert len(h.runner.sessions_run) == 4


def test_non_zero_exit_with_progress_is_trusted_and_flagged(tmp_path):
    h = make_driver(tmp_path, base_checkpoint())
    h.runner.sessions = [edit(h.path, finish=True, code=1)]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert log_lines(h)[0]["anomaly"]


def test_session_timeout_counts_as_no_progress(tmp_path):
    def timeout():
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    h = make_driver(tmp_path, base_checkpoint(), max_retries=0)
    h.runner.sessions = [timeout]
    assert h.driver.run() == shiftwork.EXIT_STALLED
    assert log_lines(h)[0]["exit"] == -1


# --- driver: waiting on externals ------------------------------------------


def running_external(ckpt, until_cmd="grep -q DONE sweep.log"):
    ckpt["state"]["external"] = [
        {"kind": "process", "ref": "pid 13031", "until_cmd": until_cmd, "status": "running"}
    ]
    return ckpt


def test_until_cmd_polls_with_backoff_then_proceeds(tmp_path):
    h = make_driver(tmp_path, running_external(base_checkpoint()), until=[1, 1, 0])
    h.runner.sessions = [edit(h.path, finish=True)]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert h.sleeps == [30, 60]  # 30s -> exponential, capped at 300s
    assert len(h.runner.sessions_run) == 1


def test_backoff_is_capped(tmp_path):
    h = make_driver(tmp_path, running_external(base_checkpoint()), until=[1] * 8 + [0])
    h.runner.sessions = [edit(h.path, finish=True)]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert h.sleeps == [30, 60, 120, 240, 300, 300, 300, 300]


def test_until_cmd_that_never_succeeds_escalates(tmp_path):
    h = make_driver(
        tmp_path,
        running_external(base_checkpoint()),
        until=[1] * 10,
        external_timeout_seconds=30,
    )
    assert h.driver.run() == shiftwork.EXIT_ESCALATE
    assert h.runner.sessions_run == []


def test_settled_external_is_not_waited_on(tmp_path):
    ckpt = base_checkpoint()
    ckpt["state"]["external"] = [{"kind": "pr", "ref": "#12", "status": "open"}]
    h = make_driver(tmp_path, ckpt)
    h.runner.sessions = [edit(h.path, finish=True)]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert h.sleeps == []


# --- driver: lock, log, dispatch -------------------------------------------


def test_second_driver_refuses_to_start(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), alive=True)
    (tmp_path / "driver.lock").write_text(
        json.dumps({"pid": 999, "started": 1.0}), encoding="utf-8"
    )
    assert h.driver.run() == shiftwork.EXIT_LOCKED
    assert h.runner.sessions_run == []
    assert json.loads((tmp_path / "driver.lock").read_text(encoding="utf-8"))["pid"] == 999


def test_lock_refusal_notifies_naming_the_holder(tmp_path):
    """A refusal that only prints to stderr is invisible to whoever walked away."""
    h = make_driver(tmp_path, base_checkpoint(), alive=True)
    (tmp_path / "driver.lock").write_text(
        json.dumps({"pid": 999, "started": 1.0}), encoding="utf-8"
    )
    assert h.driver.run() == shiftwork.EXIT_LOCKED
    message = h.runner.notifications[0][-1]
    assert message.startswith("shift-work refused to start:")
    assert "pid 999" in message


def test_lock_acquisition_is_atomic(tmp_path):
    """Two drivers racing on a free lock: exactly one wins, no read-then-write gap."""
    lock = tmp_path / "driver.lock"
    first = shiftwork.DriverLock(lock, pid=1001, now=lambda: 1.0, is_alive=lambda pid: True)
    second = shiftwork.DriverLock(lock, pid=1002, now=lambda: 2.0, is_alive=lambda pid: True)
    assert first.acquire() is None
    assert "pid 1001" in second.acquire()
    assert second.held is False
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == 1001
    second.release()  # a loser must never delete the winner's lock
    assert lock.exists()


def test_stale_lock_is_taken_over(tmp_path):
    ckpt = base_checkpoint()
    for unit in ckpt["plan"]["units"]:
        unit["status"] = "done"
    h = make_driver(tmp_path, ckpt, alive=False)  # pid 999 is dead
    (tmp_path / "driver.lock").write_text(
        json.dumps({"pid": 999, "started": 1.0}), encoding="utf-8"
    )
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert not (tmp_path / "driver.lock").exists()  # released on exit


def test_one_log_line_per_session(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_retries=1)
    h.runner.sessions = [noop(), edit(h.path, finish=True)]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    lines = log_lines(h)
    assert len(lines) == 2
    assert [line["seq"] for line in lines] == [1, 2]
    assert {line["cursor"] for line in lines} == {"U3"}
    assert lines[0]["role"] == "implementer"
    assert lines[1]["progressed"] is True
    assert set(lines[0]) >= {"ts", "seq", "cursor", "role", "exit", "duration", "progressed"}


def test_role_selects_model_and_allowed_tools(tmp_path):
    ckpt = base_checkpoint()
    ckpt["plan"]["units"][1]["role"] = "reviewer"
    h = make_driver(tmp_path, ckpt)
    h.runner.sessions = [edit(h.path, finish=True)]
    h.driver.run()
    cmd = h.runner.sessions_run[0]
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    assert cmd[cmd.index("--allowedTools") + 1] == "Read,Grep,Glob"
    assert "--permission-mode" in cmd and "acceptEdits" in cmd
    assert "--dangerously-skip-permissions" not in cmd


def test_skip_permissions_only_behind_explicit_opt_in(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), dangerously_skip_permissions=True)
    h.runner.sessions = [edit(h.path, finish=True)]
    h.driver.run()
    cmd = h.runner.sessions_run[0]
    assert "--dangerously-skip-permissions" in cmd
    assert "--permission-mode" not in cmd


def test_unknown_role_escalates(tmp_path):
    ckpt = base_checkpoint()
    ckpt["plan"]["units"][1]["role"] = "qa"
    h = make_driver(tmp_path, ckpt)
    assert h.driver.run() == shiftwork.EXIT_ESCALATE


def test_clock_in_prompt_is_constant_and_carries_no_unit_state(tmp_path):
    ckpt = base_checkpoint()
    h = make_driver(tmp_path, ckpt, max_retries=1)
    h.runner.sessions = [noop(), edit(h.path, finish=True)]
    h.driver.run()
    prompts = {cmd[cmd.index("-p") + 1] for cmd in h.runner.sessions_run}
    assert len(prompts) == 1
    prompt = prompts.pop()
    assert str(h.path) in prompt
    assert "U3" not in prompt
    assert prompt == shiftwork.CLOCK_IN_PROMPT.replace("<path>", str(h.path))
    # v1 reads the checkpoint with `json` alone, so the prompt must say so.
    assert "keeping it JSON" in prompt


def test_notify_cmd_receives_the_terminal_message(tmp_path):
    ckpt = base_checkpoint()
    ckpt["handoff"]["open_questions"] = ["ask the user"]
    h = make_driver(tmp_path, ckpt)
    h.driver.run()
    assert h.runner.notifications[0][-1].startswith("shift-work ESCALATE:")


def test_retry_counters_live_outside_the_checkpoint(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_retries=0)
    h.runner.sessions = [noop()]
    h.driver.run()
    assert "retries" not in h.path.read_text(encoding="utf-8")
    assert driver_state(h)["retries"] == {"U3": 1}


def test_driver_resumes_from_persisted_state(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_sessions=2)
    (tmp_path / "driver-state.json").write_text(
        json.dumps({"seq": 5, "sessions": 2, "retries": {"U3": 1}}), encoding="utf-8"
    )
    assert h.driver.run() == shiftwork.EXIT_BUDGET
    assert h.runner.sessions_run == []


# --- driver: config --------------------------------------------------------


def test_shipped_driver_config_covers_every_role(schema):
    config = shiftwork.Config.load(SHIFTWORK / "driver.json")
    unit = schema["properties"]["plan"]["properties"]["units"]["items"]
    roles = set(unit["properties"]["role"]["enum"])
    assert set(config.roles) >= roles
    assert config.dangerously_skip_permissions is False


def test_config_defaults_apply_without_a_file():
    config = shiftwork.Config.load(None)
    assert set(config.roles) == {"planner", "implementer", "reviewer"}
    assert config.max_retries == 3


def test_empty_notify_cmd_disables_notification(tmp_path):
    ckpt = base_checkpoint()
    for unit in ckpt["plan"]["units"]:
        unit["status"] = "done"
    h = make_driver(tmp_path, ckpt, notify_cmd=[])
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert h.runner.calls == []


def test_main_runs_end_to_end_without_spawning(tmp_path):
    """CLI smoke: an already-finished job needs no session, so no real subprocess runs."""
    ckpt = base_checkpoint()
    for unit in ckpt["plan"]["units"]:
        unit["status"] = "done"
    (tmp_path / "checkpoint.json").write_text(json.dumps(ckpt), encoding="utf-8")
    (tmp_path / "driver.json").write_text(json.dumps({"notify_cmd": []}), encoding="utf-8")
    code = shiftwork.main(
        [
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            "--config",
            str(tmp_path / "driver.json"),
        ]
    )
    assert code == shiftwork.EXIT_SUCCESS
    assert (tmp_path / "driver-state.json").exists()
    assert not (tmp_path / "driver.lock").exists()
