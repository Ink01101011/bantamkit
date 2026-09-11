"""Shift-work checkpoint operations for the MCP flavor: mirror the driver, never diverge.

The driver (tools/shiftwork/driver.py) spawns sessions from outside; these
functions serve the inverse topology — an already-running orchestrator session
clocking subagents in and out of one checkpoint. Same contract, same schema
asset, same discipline:

* every read full-schema-validates first (`load_schema("shiftwork-checkpoint")`
  + the `schema_error` engine sessions use under the driver);
* ESCALATE (non-empty `handoff.open_questions`) and SUCCESS (every unit
  done/dropped) come back as structured refusals, never exceptions;
* clock-out only accepts the cursor unit — the contract is
  execute-the-cursor-unit (driver parity), never pick-a-unit;
* clock-out validates the ENTIRE mutated document before writing, then writes
  atomically (temp file + rename, the driver's pattern) — a validation failure
  writes nothing, and every write-path OSError comes back as a structured
  `{"result": "error"}` refusal, mirroring the read side;
* clock-out refuses an accounting entry naming a model the unit's role is not
  allowed, when `job.roles` names that role (AS-2) — a validation-time refusal
  taken BEFORE the log line is appended, so a rejected model never leaves an
  orphan accounting line behind; a role the map omits, or a checkpoint with no
  map, is unconstrained and behaves exactly as it did before the map existed.
  J47-4: a role the map DOES name whose value is not a list of model identifiers
  is refused there too — an unreadable declaration allows no model, and the
  refusal is the same structured one, taken in the same place;
* every clock-out appends one line to `<checkpoint>.log.jsonl` beside the
  checkpoint (unit, role, status, ts, plus orchestrator-reported accounting)
  — the driver-log shape, so the history ring's 5-entry cap never loses
  measurement data. The log is append-only and never read here.

Log-then-commit ordering: the accounting line is appended BEFORE the atomic
checkpoint rename, so a partial failure can lose the commit but never the
accounting. The recovery semantic is one line: a log line whose commit failed
is detectable by re-reading the checkpoint (its unit is still the non-terminal
cursor unit), so a retried clock-out may leave one duplicate log line — never
a missing one.

Cursor advance is v1-linear: it moves to the first non-terminal unit in plan
order and ignores `depends_on` — non-linear plans need a planner unit to
reorder `plan.units` first.

No lock: the MCP topology has one orchestrator by construction. The driver's
O_EXCL lock guards cross-process races this shape does not have, and clock-out
re-validates before writing so a concurrent driver run fails validation-visibly.
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any

from bantamkit.assets import load_schema
from bantamkit.contract import schema_error

SCHEMA_NAME = "shiftwork-checkpoint"
TERMINAL_UNIT_STATUS = frozenset({"done", "dropped"})  # the driver's SUCCESS test
HISTORY_RING_SIZE = 5  # the schema's maxItems — older entries fall off the ring


def _error(reason: str) -> dict[str, Any]:
    return {"result": "error", "reason": reason}


def _read_valid(path: Path) -> tuple[dict | None, dict[str, Any] | None]:
    """Read and full-schema-validate. Returns (document, None) or (None, refusal)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, _error(f"checkpoint unreadable: {e}")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as e:
        return None, _error(f"checkpoint is not parseable as JSON: {e}")
    problem = schema_error(text, load_schema(SCHEMA_NAME))
    if problem is not None:
        return None, _error(f"checkpoint invalid: {problem}")
    return document, None


def _find_unit(document: dict, unit_id: str) -> dict | None:
    for unit in document["plan"]["units"]:
        if unit.get("id") == unit_id:
            return unit
    return None


def _timestamp(now: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


def clock_in(checkpoint: str) -> dict[str, Any]:
    """Validate the checkpoint and return the cursor unit's brief, or a refusal.

    Refusals mirror the driver's terminal exits: ``escalate`` when
    `handoff.open_questions` is non-empty or the cursor names no unit,
    ``success`` when every unit is done/dropped. The ``brief`` payload is what
    the orchestrator hands to the spawned agent verbatim.
    """
    document, refusal = _read_valid(Path(checkpoint))
    if refusal is not None:
        return refusal
    open_questions = document["handoff"]["open_questions"]
    if open_questions:
        return {
            "result": "escalate",
            "reason": f"open question: {open_questions[0]}",
            "open_questions": open_questions,
        }
    units = document["plan"]["units"]
    if all(u["status"] in TERMINAL_UNIT_STATUS for u in units):
        return {"result": "success", "reason": "all units done or dropped"}
    cursor = document["plan"]["cursor"]
    unit = _find_unit(document, cursor)
    if unit is None:
        return {"result": "escalate", "reason": f"cursor {cursor} names no unit"}
    return {
        "result": "brief",
        "unit": unit,
        "role": unit["role"],
        "invariants": document["job"]["constraints"],
        "handoff": document["handoff"],
        "do_not": document["handoff"]["do_not"],
        "files": document["state"]["artifacts"],
    }


def _model_refusal(document: dict, unit_id: str, unit: dict, accounting: dict | None) -> str | None:
    """AS-2: a role named in `job.roles` may only report a model on its list.

    Returns the refusal sentence, or None when the clock-out may proceed. A role
    the map does not name — and a checkpoint carrying no map at all — is
    unconstrained: that is the schema's shape (J46-7) and it is what lets a
    checkpoint written before this feature clock out unchanged.

    A role the map DOES name must say which model it ran: a missing `model` is
    refused with the same force as a wrong one, because a rule you can escape by
    omitting a field is enforced only against the honest.

    Models compare exactly — no normalisation, no prefix match, no
    strip-the-suffix rule. The map's whole value is that it is the literal list
    of the spellings a session logs, so a spelling this job has never produced is
    a finding to rule on, not a string to massage.

    THE TEST IS KEY PRESENCE, NOT TRUTHINESS, AND THAT IS A RULING (J46-10).
    `if not allowed` read `roles: {implementer: []}` as unconstrained, which
    makes an empty list a silent opt-out of the very rule the checkpoint just
    declared. Today `minItems: 1` refuses such a document during the read, so
    nothing reaches here — but the schema is a SHARED asset, exactly the class
    job46 has now measured three times as invisible to a differential suite, and
    a check whose safety rests on another layer's keyword is a check that fails
    open the day that keyword moves. The declaration is the KEY: a role the map
    names is constrained by its list, and an empty list allows nothing, so every
    model and no model alike are refused. `names` is then the empty string and
    the sentence says so. Measured, not asserted: the conformance corpus and
    both runtimes' tests drive this through a `BANTAMKIT_ASSETS` pack whose
    schema has no `minItems`, which is the only way to reach the branch at all.

    AND A DECLARATION THIS CODE CANNOT READ IS NOT A LICENCE (J47-4). The same
    ruling, one step further out: a role the map names is constrained by what it
    NAMES, and a value that is not a list of model identifiers names nothing, so
    it allows nothing. What made this a second case rather than a corollary is
    that `", ".join(allowed)` answered for every shape without ever deciding one
    — over a string it iterated CHARACTERS and refused while misquoting the
    checkpoint back at its author, and over a number, a null, a bool or a list
    holding a non-string it raised `TypeError` straight out of `clock_out`, which
    is the one exit the ruling forbids: not a structured refusal, so not an
    answer at all. Fail CLOSED and say only what is true — the declaration cannot
    be read, therefore no model is allowed — without rendering the unreadable
    value into the sentence. `[]` is untouched by this: an empty list IS a list
    of model identifiers, and it keeps the sentence J46-10 pinned.
    """
    role = unit["role"]
    roles = document["job"].get("roles", {})
    if role not in roles:
        return None
    allowed = roles[role]
    if not isinstance(allowed, list) or not all(isinstance(m, str) for m in allowed):
        return (
            f"unit {unit_id} in role {role} cannot clock out: job.roles.{role} "
            f"is not a list of model identifiers, so it allows no model"
        )
    names = ", ".join(allowed)
    offered = (accounting or {}).get("model")
    if offered is None:
        return (
            f"unit {unit_id} in role {role} reported no model, "
            f"but job.roles.{role} allows only: {names}"
        )
    if offered not in allowed:
        return (
            f"unit {unit_id} in role {role} reported model {offered}, "
            f"which job.roles.{role} does not allow: {names}"
        )
    return None


def clock_out(
    checkpoint: str,
    unit_id: str,
    status: str,
    handoff_patch: dict[str, Any],
    history_entry: dict[str, Any],
    accounting: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply the cursor unit's result to the checkpoint, validate whole, write atomically.

    `unit_id` must name the cursor unit — the contract is execute-the-cursor
    (driver parity); anything else is a structured error. When `job.roles` names
    the unit's role, `accounting["model"]` must be one of that role's models,
    spelled exactly; a wrong or missing model is refused here, before any
    mutation and before the accounting line. Extended 2026-09-11 (job47): so is a
    `job.roles` value for that role that is not a list of model identifiers —
    an unreadable declaration allows no model, and it is refused in the same
    place, by the same structured return, writing nothing. Mutations: set the
    unit's status, advance `plan.cursor` to the first non-terminal unit
    (v1-linear, `depends_on` is ignored), shallow-merge `handoff_patch` into
    `handoff`, push `history_entry` onto the 5-entry ring. The mutated
    document is validated against the full schema BEFORE any write — a
    validation failure writes nothing. Then log-then-commit: the accounting
    line is appended to `<checkpoint>.log.jsonl` first, the checkpoint is
    renamed into place second, and either step's OSError is a structured
    error that leaves the prior checkpoint bytes intact (a log line whose
    commit failed is the detectable, tolerable leftover).
    """
    path = Path(checkpoint)
    document, refusal = _read_valid(path)
    if refusal is not None:
        return refusal
    unit = _find_unit(document, unit_id)
    if unit is None:
        return _error(f"unit {unit_id} is not in the plan")
    cursor = document["plan"]["cursor"]
    if unit_id != cursor:
        return _error(f"unit {unit_id} is not the cursor unit {cursor}")
    wrong_model = _model_refusal(document, unit_id, unit, accounting)
    if wrong_model is not None:
        return _error(wrong_model)

    unit["status"] = status
    remaining = [u for u in document["plan"]["units"] if u["status"] not in TERMINAL_UNIT_STATUS]
    document["plan"]["cursor"] = remaining[0]["id"] if remaining else unit_id
    document["handoff"].update(handoff_patch or {})
    document["history"] = (document["history"] + [history_entry])[-HISTORY_RING_SIZE:]

    problem = schema_error(json.dumps(document), load_schema(SCHEMA_NAME))
    if problem is not None:
        return _error(f"refused to write: {problem}")

    record: dict[str, Any] = {
        "ts": _timestamp(time.time()),
        "unit": unit_id,
        "role": unit["role"],
        "status": status,
    }
    record.update(accounting or {})
    log_path = Path(str(path) + ".log.jsonl")
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as e:
        return _error(f"accounting log unwritable, checkpoint untouched: {e}")

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return _error(f"checkpoint unwritable, last log line uncommitted: {e}")

    return {
        "result": "ok",
        "unit": unit_id,
        "status": status,
        "cursor": document["plan"]["cursor"],
        "log": str(log_path),
    }


def status(checkpoint: str) -> dict[str, Any]:
    """Read-only progress summary. Never mutates."""
    document, refusal = _read_valid(Path(checkpoint))
    if refusal is not None:
        return refusal
    counts: dict[str, int] = {}
    for unit in document["plan"]["units"]:
        counts[unit["status"]] = counts.get(unit["status"], 0) + 1
    history = document["history"]
    return {
        "result": "status",
        "cursor": document["plan"]["cursor"],
        "units": counts,
        "open_questions": len(document["handoff"]["open_questions"]),
        "last_history": history[-1] if history else None,
    }
