"""Shift-work: the checkpoint schema asset, its loader, the driver loop, the MCP-flavor ops."""

import ast
import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
from conftest import windows_cannot_construct

from bantamkit import shiftwork as ops
from bantamkit.assets import AssetNotFound, assets_root, load_schema
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


# `duration` beside `duration_ms` ON PURPOSE (job50/F5): the schema requires the pair
# `tokens` + `duration_ms` and lets any other key through, and the fixture carries an
# odd key so the tests that read it back keep measuring the pass-through, not just the
# required pair. Drop `duration` and that guarantee is retired without a red test.
ACCOUNTING = {"tokens": 1234, "duration_ms": 88200, "duration": 88.2, "model": "haiku"}


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
    assert first["tokens"] == 1234 and first["duration_ms"] == 88200 and first["model"] == "haiku"
    assert first["duration"] == 88.2  # the odd key passed through verbatim (F5 keeps this)
    assert first["ts"].endswith("Z")
    # accounting omitted -> base shape; `briefed` is the runtime's (F6), written on every line
    assert set(second) == {"ts", "unit", "role", "status", "briefed"}
    assert second["role"] == "reviewer"
    assert first["briefed"] is False and second["briefed"] is False  # no clock_in was called


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
    assert (
        ops.clock_out(str(path), "U4", "done", {}, {"unit": "U4", "outcome": "done"})["result"]
        == "ok"
    )
    assert ops.clock_in(str(path))["result"] == "success"
    # F6: the ledger is brief/out/brief/out — the final `success` clock_in issued no brief.
    lines = read_log(path)
    assert [(line.get("event"), line["unit"]) for line in lines] == [
        ("brief", "U3"),
        (None, "U3"),
        ("brief", "U4"),
        (None, "U4"),
    ]
    assert [line["briefed"] for line in lines if "status" in line] == [True, True]


# --- MCP flavor: F6, the ledger records whether a brief was ever issued -------
#
# Measured before this existed (2026-09-13, `cat .shiftwork/*.log.jsonl | wc -l`): 217
# accounting lines in this repo's ledgers, zero carrying an `event` key, and the only
# trace of a unit executed without a brief is nine `"executed_by": "orchestrator-inline"`
# self-reports in job41's ledger. Nothing linked clock_in to clock_out. Now clock_in
# appends a brief line and clock_out reads it back into `briefed` — and NEVER refuses.


def test_clock_in_appends_one_brief_line_with_the_event_key(tmp_path, example):
    path = write_checkpoint(tmp_path, example)
    assert ops.clock_in(str(path))["result"] == "brief"
    raw = Path(str(path) + ".log.jsonl").read_text(encoding="utf-8")
    assert raw.endswith("\n") and raw.count("\n") == 1
    line = json.loads(raw)
    assert set(line) == {"event", "ts", "unit", "role"}  # no `status`: not an accounting line
    assert line["event"] == "brief" and line["unit"] == "U3" and line["role"] == "implementer"
    assert line["ts"].endswith("Z")
    # the verbatim shape, keys sorted the way every ledger line is written
    assert raw == json.dumps(line, sort_keys=True) + "\n"
    assert raw.startswith('{"event": "brief", "role": "implementer", "ts": "')


def test_clock_in_refusals_record_no_brief_line(tmp_path, example):
    """escalate, success, error: no brief was issued, so the ledger says nothing."""
    questions = copy.deepcopy(example)
    questions["handoff"]["open_questions"] = ["who owns the deploy key?"]
    done = copy.deepcopy(example)
    for unit in done["plan"]["units"]:
        unit["status"] = "done"
    dangling = copy.deepcopy(example)
    dangling["plan"]["cursor"] = "U99"
    for name, ckpt, expected in [
        ("q", questions, "escalate"),
        ("d", done, "success"),
        ("c", dangling, "escalate"),
        ("e", "{not json", "error"),
    ]:
        sub = tmp_path / name
        sub.mkdir()
        path = write_checkpoint(sub, ckpt)
        assert ops.clock_in(str(path))["result"] == expected
        assert not Path(str(path) + ".log.jsonl").exists()


def test_clock_out_after_a_brief_writes_briefed_true(tmp_path, example):
    path = write_checkpoint(tmp_path, example)
    ops.clock_in(str(path))
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
    assert r["result"] == "ok"
    lines = read_log(path)
    assert len(lines) == 2 and lines[0]["event"] == "brief"
    assert lines[1]["briefed"] is True and lines[1]["status"] == "done"
    assert lines[1]["tokens"] == 1234  # the accounting still passes through beside it


def test_clock_out_without_a_brief_records_false_and_never_refuses(tmp_path, example):
    """F6 RECORDS. A unit that was never clocked in clocks out normally — the user's
    recovery practice (recover the accounting, never drop it) depends on it."""
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
    assert r["result"] == "ok" and r["cursor"] == "U4"
    lines = read_log(path)
    assert len(lines) == 1 and lines[0]["briefed"] is False
    assert json.loads(path.read_text(encoding="utf-8"))["plan"]["cursor"] == "U4"


def test_briefed_is_written_on_a_null_accounting_line_too(tmp_path, example):
    """`accounting: null` is not an audit record, but `briefed` is not the orchestrator's
    field — it is the runtime's, like ts/unit/role/status, so it is on every line."""
    path = write_checkpoint(tmp_path, example)
    ops.clock_in(str(path))
    ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"})
    line = read_log(path)[-1]
    assert set(line) == {"ts", "unit", "role", "status", "briefed"} and line["briefed"] is True


def test_two_briefs_before_one_clock_out_is_a_relaunch_and_counts_as_briefed(tmp_path, example):
    """One line per clock_in call: a relaunch after a crashed subagent leaves two brief
    lines, and the clock-out that follows is briefed. A reader concludes: two sessions were
    handed this unit's brief before one clocked out."""
    path = write_checkpoint(tmp_path, example)
    assert ops.clock_in(str(path))["unit"]["id"] == "U3"
    assert ops.clock_in(str(path))["unit"]["id"] == "U3"
    ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
    lines = read_log(path)
    assert [line.get("event") for line in lines] == ["brief", "brief", None]
    assert lines[2]["briefed"] is True


def test_a_clock_out_consumes_the_brief_so_an_unbriefed_rerun_reads_false(tmp_path, example):
    """brief -> blocked -> re-run WITHOUT clock_in -> `false`; then clock_in -> `true`.

    The cursor stays on a blocked unit, so re-running it inline is exactly the shape F6
    exists to surface. `briefed` means "since this unit's last clock-out", not "ever"."""
    path = write_checkpoint(tmp_path, example)
    ops.clock_in(str(path))
    ops.clock_out(str(path), "U3", "blocked", {}, {"unit": "U3", "outcome": "blocked"})
    ops.clock_out(str(path), "U3", "blocked", {}, {"unit": "U3", "outcome": "blocked"})
    ops.clock_in(str(path))
    ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
    lines = read_log(path)
    assert [line.get("event") for line in lines] == ["brief", None, None, "brief", None]
    assert [line["briefed"] for line in lines if "status" in line] == [True, False, True]


def test_briefed_is_measured_by_the_runtime_not_reported_by_the_orchestrator(tmp_path, example):
    """A `briefed` key in the accounting dict is overwritten by what the ledger shows.
    F5 lets odd keys through and this one still passes the gate — but the ledger's whole
    point is a fact the reporter cannot assert, so the measured value wins."""
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(
        str(path),
        "U3",
        "done",
        {},
        {"unit": "U3", "outcome": "done"},
        dict(ACCOUNTING, briefed=True),
    )
    assert r["result"] == "ok"  # not refused
    assert read_log(path)[-1]["briefed"] is False


def test_briefed_reader_skips_lines_it_cannot_parse(tmp_path, example):
    """A ledger people edit by hand during recovery: junk lines are skipped, never fatal,
    and a brief line before the junk still counts."""
    path = write_checkpoint(tmp_path, example)
    ops.clock_in(str(path))
    with Path(str(path) + ".log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("not json\n[1, 2]\n\n")
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
    assert r["result"] == "ok"
    last = Path(str(path) + ".log.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    assert json.loads(last)["briefed"] is True


def test_clock_in_unwritable_log_as_a_directory_still_returns_the_brief(tmp_path, example):
    """Portable arm (a directory where the file belongs raises on every platform): the
    record is lost, the brief is not, and the later clock-out's own log refusal is
    unchanged."""
    path = write_checkpoint(tmp_path, example)
    Path(str(path) + ".log.jsonl").mkdir()
    brief = ops.clock_in(str(path))
    assert brief["result"] == "brief" and brief["unit"]["id"] == "U3"
    assert Path(str(path) + ".log.jsonl").is_dir()  # nothing was written anywhere


@windows_cannot_construct(
    because=(
        "the rig is `dir.chmod(0o555)`, and clearing a DIRECTORY's write bit is a POSIX "
        "permission fact with no Windows counterpart -- `chmod` there toggles the "
        "read-only attribute on files and is a no-op for directories, so the append "
        "SUCCEEDS and the brief line lands"
    ),
    unmeasured=(
        "that a genuinely read-only store (not a monkeypatched open) costs clock_in "
        "nothing but the record: the brief still returns, no exception escapes, no log "
        "file appears, and the checkpoint is byte-unchanged. The sibling node "
        "`test_clock_in_unwritable_log_as_a_directory_still_returns_the_brief` still "
        "covers the property on Windows through a directory where the file belongs"
    ),
)
def test_clock_in_read_only_store_costs_only_the_record(tmp_path, example):
    """The stronger arm: the DIRECTORY refuses writes (job48's shape — a CLI that assumed
    it could write died at startup). Genuine permission failure, not a patched function."""
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    tmp_path.chmod(0o555)
    try:
        brief = ops.clock_in(str(path))
    finally:
        tmp_path.chmod(0o755)
    assert brief["result"] == "brief" and brief["unit"]["id"] == "U3"
    assert brief["invariants"] == example["job"]["constraints"]  # the brief is whole
    assert not Path(str(path) + ".log.jsonl").exists()  # the record is what it cost
    assert path.read_bytes() == before
    # and a clock-out after the store is writable again reads the truth: no brief landed
    ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
    assert read_log(path)[-1]["briefed"] is False


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
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
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
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
    assert r["result"] == "ok" and r["cursor"] == "U4"
    assert read_log(path)[-1]["model"] == "haiku"


def test_clock_out_is_unchanged_for_a_role_the_map_does_not_name(tmp_path, example):
    """An absent role is unconstrained (the schema's shape, deliberately preserved).

    U3 is the implementer; this map names only the reviewer, so U3 may report
    anything -- including nothing at all.
    """
    example["job"]["roles"] = {"reviewer": ["claude-opus-5"]}
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
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
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING)
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
    _with_shipped_tools(root)
    return root


def _with_shipped_tools(root):
    """Since job50/F5 `clock_out` reads the `shiftwork_clock_out` TOOL asset for the
    accounting line's shape, so a pack that mutates only the checkpoint schema must still
    carry the shipped tools/ — or a clock-out that survives the roles gate is refused with
    `ACCOUNTING_SHAPE_UNREADABLE` (J50-9A; before it, it DIED on AssetNotFound) instead of
    reaching the thing these packs exist to measure."""
    shutil.copytree(assets_root() / "tools", root / "tools")
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
            "unit U3 in role implementer reported no model, but job.roles.implementer allows only: "
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
    assert (
        "does not allow"
        in ops.clock_out(
            str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
        )["reason"]
    )


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
    _with_shipped_tools(root)
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
    assert (
        "is not a list of model identifiers"
        in ops.clock_out(
            str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"}, ACCOUNTING
        )["reason"]
    )


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


# --- job50/F5: the accounting line has a shape, and a wrong one writes nothing -------
#
# The shape is J50-7's, declared on `assets/tools/shiftwork_clock_out.json`; this side
# ENFORCES it. Per-side literals again (see the AS-2 note above): the sentence is pinned
# here in full because a differential case cannot see a sentence changed on both sides.


#: The refusal's fixed frame; what follows it is the same `schema_error` rendering the
#: checkpoint refusals use, so the whole sentence is one renderer, not a second one.
REFUSED = "unit U3 in role implementer reported an accounting line the schema refuses: "

#: The fixture this file used until job50 — the exact shape the ledger census measured
#: 43 times in this repo: a `duration` spelled its own way and no `duration_ms`.
OLD_SHAPE = {"tokens": 1234, "duration": 88.2, "model": "haiku"}


def _attempt(path, accounting, unit="U3"):
    return ops.clock_out(str(path), unit, "done", {}, {"unit": unit, "outcome": "done"}, accounting)


def test_an_accounting_line_without_duration_ms_is_refused_and_nothing_is_written(
    tmp_path, example
):
    """The property, measured: bytes before == bytes after, and the log gained no line.

    `OLD_SHAPE` is the fixture every test here used until this job, so this is also the
    record that the old ledger shape is now refused rather than silently written.
    """
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    r = _attempt(path, OLD_SHAPE)
    assert r == {
        "result": "error",
        "reason": REFUSED
        + "JSON does not match schema at 'accounting': 'duration_ms' is a required property",
    }
    assert path.read_bytes() == before  # the checkpoint is byte-unchanged
    assert not Path(str(path) + ".log.jsonl").exists()  # and no line was ever appended
    assert read_log(path) == []
    assert ops.clock_in(str(path))["unit"]["id"] == "U3"  # the cursor never moved


def test_an_accounting_line_without_tokens_is_refused(tmp_path, example):
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    r = _attempt(path, {"duration_ms": 88200, "model": "haiku"})
    assert r == {
        "result": "error",
        "reason": REFUSED
        + "JSON does not match schema at 'accounting': 'tokens' is a required property",
    }
    assert path.read_bytes() == before
    assert read_log(path) == []


#: (line, the pointed detail the sentence ends with). Every value here was MEASURED
#: against jsonschema 4.26.0 before it was written down; a port reproduces the rendering
#: (Python reprs: `True`, `['a', 'b']`, `{'name': 'x'}`, `None`), it does not reason
#: about it.
WRONG_TYPES = [
    pytest.param(
        {"tokens": -1, "duration_ms": 1},
        "'accounting/tokens': -1 is less than the minimum of 0",
        id="tokens-negative",
    ),
    pytest.param(
        {"tokens": "1234", "duration_ms": 1},
        "'accounting/tokens': '1234' is not of type 'integer'",
        id="tokens-string",
    ),
    pytest.param(
        {"tokens": 12.5, "duration_ms": 1},
        "'accounting/tokens': 12.5 is not of type 'integer'",
        id="tokens-fraction",
    ),
    pytest.param(
        {"tokens": True, "duration_ms": 1},
        "'accounting/tokens': True is not of type 'integer'",
        id="tokens-bool",
    ),
    pytest.param(
        {"tokens": 1, "duration_ms": -5},
        "'accounting/duration_ms': -5 is less than the minimum of 0",
        id="duration-negative",
    ),
    pytest.param(
        {"tokens": 1, "duration_ms": 1, "cache_read_tokens": -1},
        "'accounting/cache_read_tokens': -1 is less than the minimum of 0",
        id="cache-read-negative",
    ),
    pytest.param(
        {"tokens": 1, "duration_ms": 1, "tool_uses": "3"},
        "'accounting/tool_uses': '3' is not of type 'integer'",
        id="tool-uses-string",
    ),
    pytest.param(
        {"tokens": 1, "duration_ms": 1, "note": 5},
        "'accounting/note': 5 is not of type 'string'",
        id="note-number",
    ),
    pytest.param(
        {"tokens": 1, "duration_ms": 1, "model": 5},
        "'accounting/model': 5 is not of type 'string'",
        id="model-int",
    ),
    pytest.param(
        {"tokens": 1, "duration_ms": 1, "model": 5.0},
        "'accounting/model': 5.0 is not of type 'string'",
        id="model-float",
    ),
    pytest.param(
        {"tokens": 1, "duration_ms": 1, "model": True},
        "'accounting/model': True is not of type 'string'",
        id="model-bool",
    ),
    pytest.param(
        {"tokens": 1, "duration_ms": 1, "model": ["a", "b"]},
        "'accounting/model': ['a', 'b'] is not of type 'string'",
        id="model-list",
    ),
    pytest.param(
        {"tokens": 1, "duration_ms": 1, "model": {"name": "x"}},
        "'accounting/model': {'name': 'x'} is not of type 'string'",
        id="model-dict",
    ),
    pytest.param(
        {"tokens": 1, "duration_ms": 1, "model": None},
        "'accounting/model': None is not of type 'string'",
        id="model-null",
    ),
]


@pytest.mark.parametrize(("line", "detail"), WRONG_TYPES)
def test_a_named_key_of_the_wrong_type_is_refused_and_nothing_is_written(
    tmp_path, example, line, detail
):
    """No `job.roles` here, so the schema is the only gate a wrong `model` can meet."""
    assert "roles" not in example["job"]
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    r = _attempt(path, line)
    assert r == {
        "result": "error",
        "reason": REFUSED + "JSON does not match schema at " + detail,
    }
    assert path.read_bytes() == before
    assert not Path(str(path) + ".log.jsonl").exists()


def test_a_whole_number_float_is_an_integer_to_the_schema(tmp_path, example):
    """A MEASURED fact, pinned so a port reproduces it instead of reasoning about it:
    under the 2020-12 semantics `jsonschema` applies, `1234.0` satisfies `integer`. It
    is written back as it arrived. The three shapes that are NOT integers are in
    `WRONG_TYPES` above (`12.5`, `"1234"`, `True`)."""
    path = write_checkpoint(tmp_path, example)
    r = _attempt(path, {"tokens": 1234.0, "duration_ms": 88200.0})
    assert r["result"] == "ok"
    assert read_log(path)[-1]["tokens"] == 1234.0


def test_when_two_keys_are_wrong_the_required_one_is_the_sentence(tmp_path, example):
    """`jsonschema.validate` raises `best_match`, which prefers the SHALLOWER error: a
    missing required key (at `accounting`) over a wrong type one level down. A port that
    reported the first error in document order would say `model` here; pinned."""
    path = write_checkpoint(tmp_path, example)
    r = _attempt(path, {"tokens": -1, "model": 5})
    assert r["reason"] == (
        REFUSED + "JSON does not match schema at 'accounting': 'duration_ms' is a required property"
    )
    assert read_log(path) == []


def test_an_odd_key_still_passes_through_beside_the_required_pair(tmp_path, example):
    """`additionalProperties: true` is J50-7's deliberate choice — a refused key is
    friction, not safety — and this is the test that keeps it a measurement. Two odd
    keys, one of them the OLD duration spelling, one a shape the schema never names."""
    path = write_checkpoint(tmp_path, example)
    line = {"tokens": 1, "duration_ms": 2, "duration": 88.2, "wall": ["x", {"y": 1}]}
    assert _attempt(path, line)["result"] == "ok"
    written = read_log(path)[-1]
    assert written["duration"] == 88.2 and written["wall"] == ["x", {"y": 1}]
    assert written["tokens"] == 1 and written["duration_ms"] == 2


def test_accounting_null_stays_legal_and_writes_the_base_shape(tmp_path, example):
    """The container is NOT required (J50-7 kept it optional on purpose). A null line is
    not an audit record; where `job.roles` names the role, the missing `model` already
    refuses it — see `test_clock_out_refuses_a_constrained_role_with_no_accounting_at_all`.
    Both spellings of nothing: the argument omitted, and `None` passed explicitly."""
    assert "roles" not in example["job"]
    path = write_checkpoint(tmp_path, example)
    r = ops.clock_out(str(path), "U3", "done", {}, {"unit": "U3", "outcome": "done"})
    assert r["result"] == "ok"
    assert _attempt(path, None, unit="U4")["result"] == "ok"
    for written in read_log(path):
        # the base shape, plus F6's `briefed` — the runtime's field, on every line
        assert set(written) == {"ts", "unit", "role", "status", "briefed"}


def test_a_non_string_model_gets_the_roles_sentence_when_the_role_is_named(tmp_path, example):
    """THE ORDER, decided: the roles gate runs first and keeps its sentence.

    J50-7 left this open. The precedent is `test_clock_out_role_check_runs_after_the_
    cursor_check`: the refusal that was already there keeps its sentence. So a non-string
    `model` under a constrained role answers with `reported model 5, which …` rendered by
    `str()` exactly as before — whether or not the rest of the line is well-formed — and
    the five `roles/non-string-models` conformance cases keep the sentence they pin. The
    schema's `model: string` only fires when the roles gate is silent (the test below).
    """
    example["job"]["roles"] = ROLES
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    roles_sentence = (
        "unit U3 in role implementer reported model 5, which "
        "job.roles.implementer does not allow: claude-opus-5, claude-sonnet-5"
    )
    # the line is ALSO missing the required pair — the roles gate still speaks first
    assert _attempt(path, {"model": 5})["reason"] == roles_sentence
    # and a line that is otherwise well-formed gets the same sentence
    assert _attempt(path, {"tokens": 1, "duration_ms": 1, "model": 5})["reason"] == (roles_sentence)
    assert path.read_bytes() == before
    assert read_log(path) == []


def test_a_well_formed_model_on_the_list_then_meets_the_shape_check(tmp_path, example):
    """After a roles PASS the shape check still runs: a listed model on a line with no
    `duration_ms` is refused by the schema, not waved through by the roles gate."""
    example["job"]["roles"] = ROLES
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    r = _attempt(path, {"tokens": 1, "model": "claude-sonnet-5"})
    assert r["reason"] == (
        REFUSED + "JSON does not match schema at 'accounting': 'duration_ms' is a required property"
    )
    assert path.read_bytes() == before
    assert read_log(path) == []
    ok = _attempt(path, {"tokens": 1, "duration_ms": 1, "model": "claude-sonnet-5"})
    assert ok["result"] == "ok"


def test_the_shape_check_runs_after_the_cursor_check(tmp_path, example):
    """Same ordering ruling as the roles gate: a non-cursor unit is refused for being
    non-cursor, whatever its accounting looks like."""
    path = write_checkpoint(tmp_path, example)
    r = _attempt(path, OLD_SHAPE, unit="U4")
    assert r == {"result": "error", "reason": "unit U4 is not the cursor unit U3"}
    assert read_log(path) == []


def test_the_shape_check_runs_before_any_mutation_is_validated(tmp_path, example):
    """A history entry the checkpoint schema would refuse (`refused to write: …`) AND a
    bad accounting line: the accounting sentence wins, because it is taken before the
    document is mutated at all — not discovered after, when the whole-document
    validation runs over the mutated copy."""
    path = write_checkpoint(tmp_path, example)
    before = path.read_bytes()
    r = ops.clock_out(str(path), "U3", "done", {}, {"outcome": "no unit key"}, OLD_SHAPE)
    assert r["reason"].startswith(REFUSED)
    assert path.read_bytes() == before
    assert read_log(path) == []
    # and with a GOOD line the same history entry is what gets refused — the gate above
    # was confirmed to be the accounting check and not this one
    r2 = ops.clock_out(str(path), "U3", "done", {}, {"outcome": "no unit key"}, ACCOUNTING)
    assert r2["reason"].startswith("refused to write: ")
    assert path.read_bytes() == before


def _pack_whose_clock_out_asset_requires_nothing(tmp_path):
    """A full copy of the shipped pack whose `shiftwork_clock_out` asset has lost its
    `required` list on the accounting object — the instrument that shows the check
    READS THE ASSET rather than carrying a second copy of the shape."""
    root = tmp_path / "loose"
    shutil.copytree(assets_root(), root)
    asset_path = root / "tools" / "shiftwork_clock_out.json"
    asset = json.loads(asset_path.read_text(encoding="utf-8"))
    arm = next(
        a
        for a in asset["parameters"]["properties"]["accounting"]["anyOf"]
        if a.get("type") == "object"
    )
    del arm["required"]
    asset_path.write_text(json.dumps(asset), encoding="utf-8")
    return root


def test_the_shape_is_read_off_the_tool_asset_not_a_second_copy(tmp_path, monkeypatch, example):
    """The gate is confirmed to reach the thing it checks: with the SHIPPED asset the old
    shape is refused; under a pack whose asset requires nothing, the same line clocks
    out. A check that carried its own `required` list would refuse both."""
    path = write_checkpoint(tmp_path, example)
    assert _attempt(path, OLD_SHAPE)["result"] == "error"
    monkeypatch.setenv(
        "BANTAMKIT_ASSETS", str(_pack_whose_clock_out_asset_requires_nothing(tmp_path))
    )
    r = _attempt(path, OLD_SHAPE)
    assert r["result"] == "ok", r
    assert read_log(path)[-1]["duration"] == 88.2


def test_the_shape_check_does_not_fire_on_clock_in_or_status(tmp_path, example):
    """Like AS-2, F5 constrains what a unit REPORTS, so only clock-out can check it."""
    path = write_checkpoint(tmp_path, example)
    assert ops.clock_in(str(path))["result"] == "brief"
    assert ops.status(str(path))["result"] == "status"


# --- J50-9A: a pack that cannot supply the shape REFUSES, it does not raise ----------
#
# Reading the tool asset (F5) gave `clock_out` a dependency the roles gate never had. A
# pack trimmed to `schemas/` — the shape `_pack_without_min_items` builds before
# `_with_shipped_tools` patches it — made `clock_out` raise `AssetNotFound`, the one exit
# the module's first paragraph forbids. Ruled fail CLOSED on J47-4's precedent: a
# declaration this code cannot read allows nothing. One fixed sentence, no interpolation,
# pinned as a literal so the Node side has to reproduce the bytes.

UNREADABLE = (
    "cannot clock out: the shiftwork_clock_out tool asset cannot be read as the "
    "accounting line's shape, so it allows no accounting line"
)

#: A well-formed line — under the SHIPPED pack this clocks out, which is the control that
#: shows the refusals below come from the pack and not from the line.
GOOD_LINE = {"tokens": 1234, "duration_ms": 88200, "model": "claude-opus-5"}


def _pack_with_schemas_only(tmp_path):
    """The orchestrator's repro: the shipped checkpoint schema and NOTHING else."""
    root = tmp_path / "schemas-only"
    (root / "schemas").mkdir(parents=True)
    shutil.copy(
        assets_root() / "schemas" / "shiftwork-checkpoint.json",
        root / "schemas" / "shiftwork-checkpoint.json",
    )
    return root


def _pack_whose_clock_out_asset_is(tmp_path, content):
    """The shipped schema plus ONE tool asset holding `content` (raw bytes when given as
    bytes, else JSON) — the present-but-malformed family."""
    root = _pack_with_schemas_only(tmp_path)
    (root / "tools").mkdir()
    target = root / "tools" / "shiftwork_clock_out.json"
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(json.dumps(content), encoding="utf-8")
    return root


def _assert_refused_and_untouched(path, before, r):
    assert r == {"result": "error", "reason": UNREADABLE}
    assert path.read_bytes() == before  # the checkpoint is byte-unchanged
    assert not Path(str(path) + ".log.jsonl").exists()  # the log gained no line
    assert not path.with_suffix(".json.tmp").exists()  # and no temp file was left
    assert ops.clock_in(str(path))["unit"]["id"] == "U3"  # the cursor never moved


def test_a_pack_with_no_tools_dir_refuses_the_line_and_writes_nothing(
    tmp_path, monkeypatch, example
):
    """The property, measured the way the roles refusals are: bytes before == bytes
    after, the log does not exist, the cursor is still U3 — and the answer is a dict,
    not `AssetNotFound`. The same call under the shipped pack is the control."""
    path = write_checkpoint(tmp_path, example)
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(_pack_with_schemas_only(tmp_path)))
    before = path.read_bytes()
    _assert_refused_and_untouched(path, before, _attempt(path, GOOD_LINE))
    monkeypatch.delenv("BANTAMKIT_ASSETS")
    assert _attempt(path, GOOD_LINE)["result"] == "ok"  # the line was never the problem


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"{not json", id="not-json"),
        pytest.param(b"\xff\xfe\x00", id="not-utf8"),
        pytest.param({"name": "shiftwork_clock_out"}, id="no-parameters"),
        pytest.param({"parameters": {"properties": {}}}, id="no-accounting"),
        pytest.param(
            {"parameters": {"properties": {"accounting": {"type": "object"}}}}, id="no-anyOf"
        ),
        pytest.param(
            {"parameters": {"properties": {"accounting": {"anyOf": "object"}}}},
            id="anyOf-not-a-list",
        ),
        pytest.param(
            {"parameters": {"properties": {"accounting": {"anyOf": [{"type": "null"}]}}}},
            id="no-object-arm",
        ),
        pytest.param(
            {
                "parameters": {
                    "properties": {"accounting": {"anyOf": [{"type": "object", "required": 5}]}}
                }
            },
            id="arm-is-not-a-schema",
        ),
        pytest.param({"parameters": "yes"}, id="parameters-not-a-dict"),
    ],
)
def test_a_present_but_malformed_asset_is_the_same_refusal_not_a_second_one(
    tmp_path, monkeypatch, example, content
):
    """MISSING AND MALFORMED ARE ONE CASE. Each row here raised a DIFFERENT exception out
    of `clock_out` before J50-9A (`JSONDecodeError`, `UnicodeDecodeError`, `KeyError`,
    `TypeError`, `StopIteration`, `jsonschema.SchemaError`); each now gets the one
    sentence, because the property is one: the shape cannot be read, so the line cannot
    be checked, so it is not allowed. A per-shape sentence would render exception text
    the two runtimes spell differently."""
    path = write_checkpoint(tmp_path, example)
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(_pack_whose_clock_out_asset_is(tmp_path, content)))
    before = path.read_bytes()
    _assert_refused_and_untouched(path, before, _attempt(path, GOOD_LINE))


def test_a_null_line_never_needs_the_shape_so_a_trimmed_pack_can_still_clock_it_out(
    tmp_path, monkeypatch, example
):
    """The null arm is the caller's (F5 ruling NULL STAYS LEGAL), so the asset is not
    read for it: a unit that reports no accounting clocks out under a schemas-only pack
    exactly as it does under the shipped one. The refusal is about a LINE the pack cannot
    check, not about the pack's existence."""
    path = write_checkpoint(tmp_path, example)
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(_pack_with_schemas_only(tmp_path)))
    r = _attempt(path, None)
    assert r["result"] == "ok", r
    assert read_log(path)[-1]["unit"] == "U3"


def test_the_unreadable_shape_refusal_runs_after_the_roles_gate(tmp_path, monkeypatch, example):
    """Same ordering as every F5 ruling: the roles gate keeps its sentence. A constrained
    role reporting a model off its list is refused for THAT, whatever the pack holds."""
    example["job"]["roles"] = ROLES
    path = write_checkpoint(tmp_path, example)
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(_pack_with_schemas_only(tmp_path)))
    r = _attempt(path, ACCOUNTING)  # model haiku, not on the implementer's list
    assert r["reason"].startswith("unit U3 in role implementer reported model haiku, which")
    assert read_log(path) == []


def test_the_unreadable_shape_refusal_runs_after_the_cursor_check(tmp_path, monkeypatch, example):
    path = write_checkpoint(tmp_path, example)
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(_pack_with_schemas_only(tmp_path)))
    r = _attempt(path, GOOD_LINE, unit="U4")
    assert r == {"result": "error", "reason": "unit U4 is not the cursor unit U3"}
    assert read_log(path) == []


def test_the_sentence_is_the_modules_constant_and_interpolates_nothing():
    """J50-9B reproduces this literal byte for byte; a template would drift per input."""
    assert ops.ACCOUNTING_SHAPE_UNREADABLE == UNREADABLE
    assert "{" not in UNREADABLE and "/" not in UNREADABLE  # no format slot, no path


# --- job60: clock_in takes a unit, clock_out takes a briefed one, the cursor follows ---
#
# The contradiction these close, both halves MEASURED 2026-09-20 against the live MCP and
# the Python module before any of it was written:
#
#   shape 1  units N1, N2 independent, N3 on both. `shiftwork_plan` said width 2 and
#            ready [N1, N2]; three `clock_in` calls answered N1, N1, N1, and
#            `clock_out N2` answered "unit N2 is not the cursor unit N1". The width was
#            announced by one surface and unspendable on the other.
#   shape 2  units [A, C(depends_on B), B], cursor A. `clock_out A done` moved the cursor
#            to C in PLAN order, `shiftwork_plan` said ready [B], and `clock_in` handed
#            out C's brief with no refusal and no warning — work whose input does not
#            exist yet.
#
# Why nothing was red: every `plan_batches` case above picks a checkpoint where
# `cursor == ready[0]`, the two-wide one included, so nothing ever compared the two
# FIELDS. These cases compare them against each other, which is the assertion that was
# missing rather than the code that was wrong.


def graph_checkpoint(example, units, cursor):
    """`example` with its plan replaced: `units` is [(id, [deps]), ...], every one `todo`.

    Built off the shipped example so the rest of the document (job, handoff, state,
    history) is a real validating checkpoint and only the graph under test varies.
    """
    ckpt = copy.deepcopy(example)
    ckpt["plan"]["units"] = [
        {
            "id": unit_id,
            "title": f"unit {unit_id}",
            "brief_path": f".shiftwork/briefs/{unit_id}.md",
            "status": "todo",
            "role": "implementer",
            "depends_on": list(deps),
            "verify": "true",
        }
        for unit_id, deps in units
    ]
    ckpt["plan"]["cursor"] = cursor
    return ckpt


def out(path, unit_id, status="done"):
    return ops.clock_out(str(path), unit_id, status, {}, {"unit": unit_id, "outcome": status})


def test_clock_in_with_no_unit_id_answers_exactly_what_it_always_did(tmp_path):
    """D1's whole promise to a caller that never heard of it: the default path is unmoved.

    Asserted field by field against the file rather than "result == brief", and then
    asserted AGAIN against the explicit call naming the same unit — the two routes into
    the brief must build one payload, or `unit_id` is a second implementation of it.
    """
    path = write_checkpoint(tmp_path, json.loads(CODEFIX.read_text(encoding="utf-8")))
    ckpt = json.loads(CODEFIX.read_text(encoding="utf-8"))
    brief = ops.clock_in(str(path))
    assert brief["result"] == "brief"
    assert ckpt["plan"]["cursor"] == "CF1"
    assert brief["unit"] == ckpt["plan"]["units"][0]  # CF1, the cursor unit, verbatim
    assert brief["role"] == "implementer"
    assert brief["invariants"] == ckpt["job"]["constraints"]
    assert brief["handoff"] == ckpt["handoff"]
    assert brief["do_not"] == ckpt["handoff"]["do_not"]
    assert brief["files"] == ckpt["state"]["artifacts"]
    assert ops.clock_in(str(path), "CF1") == brief


def test_the_cursor_lands_on_the_graphs_next_unit_not_the_plans(tmp_path, example):
    """SHAPE 2, and the one assertion that would have caught it: cursor B, never C.

    `plan.units` declares [A, C, B] and C depends on B, so plan order and graph order
    disagree by construction. Before D3 the cursor advanced in plan order and landed on
    C — a unit whose input had not run — while `shiftwork_plan` said ready [B]. The
    assertion is the two fields against EACH OTHER, which is what no case did.
    """
    ckpt = graph_checkpoint(example, [("A", []), ("C", ["B"]), ("B", [])], "A")
    path = write_checkpoint(tmp_path, ckpt)
    assert ops.plan_batches(str(path))["ready"] == ["A", "B"]

    assert out(path, "A")["cursor"] == "B"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["plan"]["cursor"] == "B"
    view = ops.plan_batches(str(path))
    assert view["ready"] == ["B"] and view["cursor"] == view["ready"][0]

    brief = ops.clock_in(str(path))
    assert brief["result"] == "brief" and brief["unit"]["id"] == "B"


def test_clock_in_refuses_a_unit_the_graph_has_not_released(tmp_path, example):
    """The D1 sentence, exact. C is declared before B and depends on it, so it is the
    unit an orchestrator reading `plan.units` would reach for — and it is not ready."""
    ckpt = graph_checkpoint(example, [("A", []), ("C", ["B"]), ("B", [])], "A")
    path = write_checkpoint(tmp_path, ckpt)
    assert out(path, "A")["cursor"] == "B"
    assert ops.clock_in(str(path), "C") == {
        "result": "error",
        "reason": "unit C is not ready; ready is B",
    }
    assert not any(line.get("unit") == "C" for line in read_log(path))


def test_a_unit_id_naming_no_unit_gets_the_same_not_ready_sentence(tmp_path, example):
    """One property, one sentence: a name the plan does not carry is the limiting case of
    not-ready, not a second refusal to spell (and to drift between two runtimes)."""
    ckpt = graph_checkpoint(example, [("A", []), ("C", ["B"]), ("B", [])], "A")
    path = write_checkpoint(tmp_path, ckpt)
    assert out(path, "A")["cursor"] == "B"
    assert ops.clock_in(str(path), "nope") == {
        "result": "error",
        "reason": "unit nope is not ready; ready is B",
    }


def test_the_not_ready_sentence_joins_the_whole_ready_batch(tmp_path, example):
    """`ready` is listed because the caller's next move is to pick from it, so a two-wide
    batch must name both, joined with ", " in batch order."""
    ckpt = graph_checkpoint(example, [("N1", []), ("N2", []), ("N3", ["N1", "N2"])], "N1")
    path = write_checkpoint(tmp_path, ckpt)
    assert ops.clock_in(str(path), "N3")["reason"] == "unit N3 is not ready; ready is N1, N2"


def test_clock_in_briefs_a_second_ready_unit_and_leaves_the_cursor_alone(tmp_path, example):
    """SHAPE 1: the width `shiftwork_plan` reports is now spendable.

    And the invariant that makes a wave safe — clock-in NEVER writes `plan.cursor`. Both
    briefs are issued against one pointer, and the pointer does not move until a
    clock-out moves it.
    """
    ckpt = graph_checkpoint(example, [("N1", []), ("N2", []), ("N3", ["N1", "N2"])], "N1")
    path = write_checkpoint(tmp_path, ckpt)
    assert ops.plan_batches(str(path))["width"] == 2

    first = ops.clock_in(str(path))
    second = ops.clock_in(str(path), "N2")
    assert first["unit"]["id"] == "N1" and second["unit"]["id"] == "N2"
    assert second["invariants"] == ckpt["job"]["constraints"]

    briefs = [line for line in read_log(path) if line.get("event") == "brief"]
    assert [line["unit"] for line in briefs] == ["N1", "N2"]  # the unit ACTUALLY briefed
    assert json.loads(path.read_text(encoding="utf-8"))["plan"]["cursor"] == "N1"


def test_clock_out_accepts_a_briefed_non_cursor_unit(tmp_path, example):
    """D2. Without it the wave above is unusable: N2 was briefed against cursor N1, so
    its result would have nowhere to go until N1 happened to finish first."""
    ckpt = graph_checkpoint(example, [("N1", []), ("N2", []), ("N3", ["N1", "N2"])], "N1")
    path = write_checkpoint(tmp_path, ckpt)
    assert ops.clock_in(str(path), "N2")["result"] == "brief"

    r = out(path, "N2")
    assert r["result"] == "ok" and r["unit"] == "N2"
    assert r["cursor"] == "N1"  # N1 is still the only ready unit; N3 waits on it
    line = read_log(path)[-1]
    assert line["unit"] == "N2" and line["status"] == "done" and line["briefed"] is True

    # And the brief is CONSUMED. `briefed` means "briefed since this unit's own last
    # clock-out", so the clock-out above spent it: a SECOND clock-out of N2 has no brief
    # left to stand on and meets the same sentence, unreworded. Without this half the
    # gate is an open door — one brief would license a unit to report forever.
    written = len(read_log(path))
    assert out(path, "N2") == {"result": "error", "reason": "unit N2 is not the cursor unit N1"}
    assert len(read_log(path)) == written  # the refusal wrote nothing beside it


def test_clock_out_of_a_unit_never_briefed_keeps_its_existing_refusal(tmp_path, example):
    """D2 widened the MEANING and not the WORDING — every ruled case on this sentence
    stays green — and it did NOT become permissive: a unit nobody dispatched is refused,
    with nothing written on either surface."""
    ckpt = graph_checkpoint(example, [("N1", []), ("N2", []), ("N3", ["N1", "N2"])], "N1")
    path = write_checkpoint(tmp_path, ckpt)
    before = path.read_bytes()
    assert out(path, "N2") == {"result": "error", "reason": "unit N2 is not the cursor unit N1"}
    assert path.read_bytes() == before
    assert read_log(path) == []


def test_a_graph_that_cannot_batch_refuses_clock_in_and_still_drives_to_the_end(
    tmp_path, example
):
    """The core's refusal passes through VERBATIM — the same bytes `plan_batches` answers,
    so a caller cannot tell which surface it asked — and D3's second arm keeps clock-out
    RECORDING: a checkpoint whose graph is unplannable is still driven to its end in plan
    order. B and C cycle around each other and A does not, so the cycle survives A's
    clock-out; that is what makes the fallback reachable at all.
    """
    ckpt = graph_checkpoint(example, [("A", []), ("B", ["C"]), ("C", ["B"])], "A")
    path = write_checkpoint(tmp_path, ckpt)
    cycle = {"result": "error", "reason": "the graph has a cycle: B -> C -> B"}
    assert ops.plan_batches(str(path)) == cycle
    assert ops.clock_in(str(path), "A") == cycle
    assert ops.clock_in(str(path), "nope") == cycle  # the batch view refuses FIRST
    assert read_log(path) == []

    assert out(path, "A")["cursor"] == "B"  # plan order over the remaining units
    assert out(path, "B")["cursor"] == "C"  # C's edge into B is satisfied: ready again
    assert out(path, "C")["cursor"] == "C"  # nothing non-terminal left: the unit itself
    assert ops.clock_in(str(path)) == {"result": "success", "reason": "all units done or dropped"}


def test_clock_in_with_a_unit_id_refuses_before_it_reads_the_graph(tmp_path, example):
    """The order of judgements above the selection is UNMOVED, so no existing refusal
    changed place: escalate and success still answer first, whatever `unit_id` says."""
    def sub(name, ckpt):
        directory = tmp_path / name
        directory.mkdir()
        return write_checkpoint(directory, ckpt)

    questions = copy.deepcopy(example)
    questions["handoff"]["open_questions"] = ["who owns the deploy key?"]
    q = sub("q", questions)
    assert ops.clock_in(str(q), "U4")["result"] == "escalate"
    done = copy.deepcopy(example)
    for unit in done["plan"]["units"]:
        unit["status"] = "done"
    d = sub("d", done)
    assert ops.clock_in(str(d), "U4") == {
        "result": "success",
        "reason": "all units done or dropped",
    }
    e = sub("e", "{not json")
    bad = ops.clock_in(str(e), "U4")
    assert bad["result"] == "error" and "not parseable as JSON" in bad["reason"]

    # None of the three handed out a brief, so none of them recorded one — the same
    # assertion the Node node makes, per arm, because one empty log beside two written
    # ones would read as green. Same idiom as the cycle test above.
    for path in (q, d, e):
        assert read_log(path) == [], f"{path}: an answer that is not a brief recorded none"


def test_the_three_callers_give_one_answer_about_one_document(tmp_path, example):
    """The bug was two answers about one document. Measured on the ANSWERS: `clock_in`'s
    refusal quotes the batch `plan_batches` publishes, and the cursor `clock_out` writes
    is that batch's first id — on a checkpoint where plan order would say something else.

    This is the half a second loop can PASS, which is why the source-level test below
    exists beside it: two loops that agree today agree here too.
    """
    ckpt = graph_checkpoint(example, [("A", []), ("C", ["B"]), ("B", [])], "A")
    path = write_checkpoint(tmp_path, ckpt)
    out(path, "A")
    ready = ops.plan_batches(str(path))["ready"]
    assert ops.clock_in(str(path), "C")["reason"].endswith(f"ready is {', '.join(ready)}")
    assert json.loads(path.read_text(encoding="utf-8"))["plan"]["cursor"] == ready[0]


def code_mentions(node, name):
    """How many times `name` is EXECUTED under `node` — prose does not count.

    A docstring naming `depends_on` is documentation, not a walk over it, so every
    string that stands alone as a statement is dropped before counting. What remains is
    a dict key, a subscript, an attribute, a parameter — a use.
    """
    prose = {
        id(n.value)
        for n in ast.walk(node)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
    }
    hits = 0
    for n in ast.walk(node):
        if id(n) in prose:
            continue
        if isinstance(n, ast.Constant) and n.value == name:
            hits += 1
        elif isinstance(n, (ast.Name, ast.Attribute, ast.arg)) and name in (
            getattr(n, "id", None),
            getattr(n, "attr", None),
            getattr(n, "arg", None),
        ):
            hits += 1
    return hits


def depends_on_owners(source):
    """{top-level def that executes `depends_on`: how many times}, parsed from SOURCE."""
    tree = ast.parse(source)
    owners = {}
    for top in tree.body:
        hits = code_mentions(top, "depends_on")
        if hits:
            owners[getattr(top, "name", "<module>")] = hits
    return owners


def test_the_module_walks_depends_on_in_exactly_one_place():
    """The claim in the name, measured where it lives: the SOURCE of `bantamkit.
    shiftwork`. The answer-level test above cannot fail on a second loop that happens to
    agree — and "two loops that agree today are the next divergence" is the whole reason
    job60 merged them — so this one reads the module and counts.

    Two counts, because one walk over `depends_on` is only half of it: the graph logic
    itself is Layer 1's, so the module must also enter the planner exactly once. The
    import form is pinned too — `from bantamkit.workplan import plan` would put a second
    door in the wall that `workplan.plan` is counted through.
    """
    source = Path(ops.__file__).read_text(encoding="utf-8")
    assert set(depends_on_owners(source)) == {"_batch_view"}

    tree = ast.parse(source)

    def planner_calls(node):
        return [
            n
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "plan"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "workplan"
        ]

    assert len(planner_calls(tree)) == 1
    assert {getattr(top, "name", "<module>") for top in tree.body if planner_calls(top)} == {
        "_batch_view"
    }
    assert [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "bantamkit.workplan"
    ] == []


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


# --- MCP flavor: plan_batches -----------------------------------------------
#
# The adapter over `workplan.plan`. It owns exactly three decisions — which units are
# still in the graph, that every unit has priority 0, and that the cursor is echoed —
# and no graph logic at all; the batching itself is Layer 1's and is gated there.


def digests(path):
    """(checkpoint bytes, ledger bytes-or-None) — the pair a read-only tool must not move.

    The ledger is included because it is the surface a "read-only" tool would break
    FIRST: `clock_in` is also read-only about the checkpoint and still appends a brief
    line beside it. A hash of the checkpoint alone would call that read-only.
    """
    log = Path(str(path) + ".log.jsonl")
    return (
        hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        hashlib.sha256(log.read_bytes()).hexdigest() if log.exists() else None,
    )


def test_plan_batches_of_the_codefix_chain_is_four_batches_of_one(tmp_path):
    """CF1 -> CF2 -> CF3 -> CF4, all `todo`: a straight line has nothing to parallelize."""
    path = tmp_path / "checkpoint.json"
    path.write_text(CODEFIX.read_text(encoding="utf-8"), encoding="utf-8")
    assert ops.plan_batches(str(path)) == {
        "result": "plan",
        "batches": [["CF1"], ["CF2"], ["CF3"], ["CF4"]],
        "ready": ["CF1"],
        "sequence": ["CF1", "CF2", "CF3", "CF4"],
        "width": 1,
        "cursor": "CF1",
    }


def test_a_done_unit_leaves_the_graph_and_its_edges_are_satisfied(tmp_path):
    """Marking CF1 done drops it AND resolves CF2's edge into it — otherwise the whole
    remaining graph would be unplannable the moment the first unit finished."""
    ckpt = json.loads(CODEFIX.read_text(encoding="utf-8"))
    ckpt["plan"]["units"][0]["status"] = "done"
    ckpt["plan"]["cursor"] = "CF2"
    r = ops.plan_batches(str(write_checkpoint(tmp_path, ckpt)))
    assert r["batches"] == [["CF2"], ["CF3"], ["CF4"]]
    assert r["ready"] == ["CF2"]
    assert r["sequence"] == ["CF2", "CF3", "CF4"]
    assert r["cursor"] == "CF2"


def test_a_dropped_unit_is_satisfied_exactly_like_a_done_one(tmp_path):
    """`dropped` is terminal for the driver's success test, so it is terminal here too:
    a unit nobody will ever run cannot be a reason to hold its dependants back."""
    ckpt = json.loads(CODEFIX.read_text(encoding="utf-8"))
    ckpt["plan"]["units"][0]["status"] = "dropped"
    ckpt["plan"]["cursor"] = "CF2"
    assert ops.plan_batches(str(write_checkpoint(tmp_path, ckpt)))["batches"] == [
        ["CF2"],
        ["CF3"],
        ["CF4"],
    ]


def test_in_progress_and_blocked_units_stay_in_the_graph(tmp_path, example):
    """The three non-terminal statuses are all still work, so all three still batch."""
    example["plan"]["units"][0]["status"] = "in_progress"
    example["plan"]["units"][1]["status"] = "blocked"
    r = ops.plan_batches(str(write_checkpoint(tmp_path, example)))
    assert r["batches"] == [["U1"], ["U3"], ["U4"]]
    assert r["ready"] == ["U1"]


def test_independent_units_share_one_batch_and_width_reports_the_fan_out(tmp_path, example):
    """The number the whole design exists to produce: two units that may run at once."""
    example["plan"]["units"][2]["depends_on"] = ["U1"]  # U4 waits for U1, not for U3
    r = ops.plan_batches(str(write_checkpoint(tmp_path, example)))
    assert r["batches"] == [["U3", "U4"]]  # U1 is done and out of the graph
    assert r["ready"] == ["U3", "U4"]
    assert r["width"] == 2


def test_order_inside_a_batch_is_plan_units_order_not_sorted(tmp_path, example):
    """Every unit gets priority 0 — the checkpoint schema has no priority field and this
    job does not add one — so the tie-break is the order `plan.units` declares, and that
    is contract. Reversing the declaration reverses the batch; a sorted answer would not
    move, so this is what distinguishes the two."""
    example["plan"]["units"][2]["depends_on"] = ["U1"]
    example["plan"]["units"] = [
        example["plan"]["units"][0],
        example["plan"]["units"][2],
        example["plan"]["units"][1],
    ]
    assert ops.plan_batches(str(write_checkpoint(tmp_path, example)))["ready"] == ["U4", "U3"]


def test_an_all_terminal_plan_is_an_empty_answer_not_a_refusal(tmp_path, example):
    """The same judgement `clock_in` already makes: a finished job is an ANSWER."""
    for unit in example["plan"]["units"]:
        unit["status"] = "done"
    r = ops.plan_batches(str(write_checkpoint(tmp_path, example)))
    assert r["result"] == "plan"
    assert r["batches"] == [] and r["ready"] == [] and r["sequence"] == [] and r["width"] == 0


def test_the_schema_refusal_passes_through_unchanged(tmp_path, example):
    """`_read_valid`'s refusal is returned verbatim, so a caller cannot tell which
    read-only tool it asked. Both shapes: unparseable, and parseable-but-invalid."""
    assert ops.plan_batches(str(write_checkpoint(tmp_path, "{not json at all")))["result"] == (
        "error"
    )
    bad = ops.plan_batches(str(write_checkpoint(tmp_path, mutate(example, ["version"], 99))))
    assert bad["result"] == "error" and bad["reason"].startswith("checkpoint invalid: ")
    missing = ops.plan_batches(str(tmp_path / "nope.json"))
    assert missing["result"] == "error" and missing["reason"].startswith("checkpoint unreadable")


def test_a_cycle_among_the_remaining_units_is_the_core_refusal(tmp_path, example):
    """Layer 1 composes the sentence; the adapter neither rewrites nor swallows it."""
    example["plan"]["units"][1]["depends_on"] = ["U4"]  # U3 <-> U4
    r = ops.plan_batches(str(write_checkpoint(tmp_path, example)))
    assert r == {"result": "error", "reason": "the graph has a cycle: U3 -> U4 -> U3"}


def test_an_edge_into_a_unit_no_longer_in_the_graph_is_not_an_unknown_dependency(
    tmp_path, example
):
    """The load-bearing half of "satisfied": U3 depends on U1, U1 is `done` and therefore
    absent from the nodes handed to Layer 1. If the adapter passed the edge through, the
    core's unknown-dependency refusal would fire on every checkpoint with a finished
    unit — which is every checkpoint after the first clock-out."""
    r = ops.plan_batches(str(write_checkpoint(tmp_path, example)))
    assert r["result"] == "plan"
    assert r["batches"] == [["U3"], ["U4"]]


def test_plan_batches_writes_nothing(tmp_path, example):
    """THE load-bearing test of the design. Without it, "read-only" is a comment.

    Hashes, not `exists()`: a ledger line appended to an existing log, or a checkpoint
    rewritten with the same key order, would both survive a weaker check. The log must
    still be ABSENT afterwards, which is the state `clock_in` would have changed.
    """
    path = write_checkpoint(tmp_path, example)
    log = Path(str(path) + ".log.jsonl")
    assert not log.exists()
    before = digests(path)
    assert ops.plan_batches(str(path))["result"] == "plan"
    assert digests(path) == before
    assert not log.exists(), "plan_batches appended a ledger line beside the checkpoint"

    # And on a checkpoint that ALREADY has a ledger: the bytes of both must not move.
    ops.clock_in(str(path))
    assert log.exists()
    with_log = digests(path)
    assert ops.plan_batches(str(path))["result"] == "plan"
    assert digests(path) == with_log


def test_plan_batches_does_not_move_the_repo_s_own_example_checkpoints():
    """Run against the shipped files themselves, at their real paths. A tool that writes
    only when it can — beside a checkpoint in a real tree rather than in `tmp_path` —
    would pass every test above and be caught here."""
    for checkpoint in (EXAMPLE, CODEFIX):
        before = digests(checkpoint)
        assert ops.plan_batches(str(checkpoint))["result"] == "plan"
        assert digests(checkpoint) == before, f"{checkpoint} moved"


# --- the code-fix example checkpoint ----------------------------------------


def test_codefix_example_validates(schema):
    assert schema_error(CODEFIX.read_text(encoding="utf-8"), schema) is None


def test_codefix_example_shapes_the_job(tmp_path, schema):
    ckpt = json.loads(CODEFIX.read_text(encoding="utf-8"))
    units = ckpt["plan"]["units"]
    assert [u["id"] for u in units] == ["CF1", "CF2", "CF3", "CF4"]
    assert ckpt["plan"]["cursor"] == "CF1"
    # reproduce -> locate -> fix are implementer; the fix is gated by the reviewer unit.
    assert [u["role"] for u in units] == ["implementer", "implementer", "implementer", "reviewer"]
    # Briefed from a COPY, like every other template test here: `clock_in` appends a
    # brief line beside the checkpoint it is handed, so calling it on the tracked
    # template in place made `git status` dirty after every pytest run.
    brief = ops.clock_in(str(write_checkpoint(tmp_path, ckpt)))
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
