"""Shift-work checkpoint operations for the MCP flavor: mirror the driver, never diverge.

The driver (tools/shiftwork/driver.py) spawns sessions from outside; these
functions serve the inverse topology — an already-running orchestrator session
clocking subagents in and out of one checkpoint. Same contract, same schema
asset, same discipline:

* every read full-schema-validates first (`load_schema("shiftwork-checkpoint")`
  + the `schema_error` engine sessions use under the driver);
* ESCALATE (non-empty `handoff.open_questions`) and SUCCESS (every unit
  done/dropped) come back as structured refusals, never exceptions;
* clock-out accepts the cursor unit OR a unit briefed since its own last
  clock-out (job60/D2) — a wave of briefs has to be clockable out in whatever
  order it finishes; a unit that was never dispatched still cannot be, and the
  refusal keeps its existing sentence word for word;
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
* clock-out refuses an accounting line that does not fit the shape the
  `shiftwork_clock_out` tool asset declares (job50/F5: `tokens` and
  `duration_ms` required, non-negative integers; `model` a string; any other
  key passes through) — checked AFTER the roles gate and BEFORE any mutation,
  so a refused line is never appended and the checkpoint is byte-unchanged.
  `accounting: null` stays legal: a null line is not an audit record, and
  where `job.roles` names the role the missing `model` already refuses it.
  J50-9A: a pack that cannot supply that shape — no `tools/` at all, or a
  `shiftwork_clock_out` asset that is not JSON, not the manifest shape, or not
  a schema — is refused there too, by one fixed sentence: a declaration this
  code cannot read allows no accounting line, exactly J47-4's ruling one asset
  over, and it is the same structured return in the same place, writing nothing;
* every clock-out appends one line to `<checkpoint>.log.jsonl` beside the
  checkpoint (unit, role, status, ts, `briefed`, plus orchestrator-reported
  accounting) — the driver-log shape, so the history ring's 5-entry cap never
  loses measurement data. The log is append-only;
* AND SO DOES EVERY CLOCK-IN THAT ISSUES A BRIEF (job50/F6). The ledger is no
  longer "one line per clock-out": a `{"event": "brief", ...}` line lands when
  `clock_in` answers `brief` (never on escalate/success/error — no brief was
  issued), and `clock_out` reads the ledger back to write `briefed` into the
  accounting line: whether a brief was issued for this unit since its last
  clock-out. Measured before this existed (2026-09-13, `cat .shiftwork/*.log.jsonl`):
  217 accounting lines in this repo's ledgers, and the only trace of a unit run
  without a brief is 9 lines that SAY `"executed_by": "orchestrator-inline"` —
  a self-report, which is the point: nothing could tell the rest apart.
  `clock_out` NEVER refuses on it — a unit with no brief clocks out with
  `briefed: false`, because the user's recovery practice is to recover the
  accounting, never drop it. The brief line is best-effort: a ledger that
  cannot be written costs the orchestrator the record, never the brief (the
  eventlog's rule, and job48's lesson — a CLI that assumed it could write died
  at startup). A reader tells the two line kinds apart at a glance by the
  `event` key, which none of those 217 lines carries (`grep -c '"event"'`
  is 0 on every ledger); the key is the hook log's own spelling,
  `hook-log.jsonl`'s `"event"`.

Log-then-commit ordering: the accounting line is appended BEFORE the atomic
checkpoint rename, so a partial failure can lose the commit but never the
accounting. The recovery semantic is one line: a log line whose commit failed
is detectable by re-reading the checkpoint (its unit is still the non-terminal
cursor unit), so a retried clock-out may leave one duplicate log line — never
a missing one.

Cursor advance FOLLOWS THE GRAPH (job60/D3). It was v1-linear — the first
non-terminal unit in `plan.units` order, `depends_on` ignored — while
`plan_batches` answered `ready` from the graph, so the pointer could land on a
unit whose dependencies were unmet and the two surfaces disagreed about one
document. It now moves to `ready[0]` of the batch view recomputed on the
mutated document, falling back to plan order over the remaining non-terminal
units only when the graph cannot batch AT ALL (cycle, unknown dependency) — a
recording surface does not acquire a new way to refuse — and to the clocked-out
unit when nothing non-terminal remains. On a linear chain the two orders
coincide, which is why every case written before this holds its value.

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

import jsonschema

from bantamkit import workplan
from bantamkit.assets import AssetNotFound, load_schema, load_tool_asset
from bantamkit.contract import schema_error

SCHEMA_NAME = "shiftwork-checkpoint"
TOOL_ASSET = "shiftwork_clock_out"  # the accounting line's shape lives on the tool (F5)
#: J50-9A: the one sentence for a pack that cannot supply the accounting shape. FIXED —
#: no path, no exception text, no unit — so the Node side reproduces it byte for byte and
#: a differential case can compare the two; which of the shapes below failed is not said,
#: because the property is the same for all of them (see `_accounting_schema`).
ACCOUNTING_SHAPE_UNREADABLE = (
    "cannot clock out: the shiftwork_clock_out tool asset cannot be read as the "
    "accounting line's shape, so it allows no accounting line"
)
TERMINAL_UNIT_STATUS = frozenset({"done", "dropped"})  # the driver's SUCCESS test
#: F6: the `event` value of the ledger line `clock_in` appends when it issues a brief. The
#: word is the register's own — `clock_in` answers `result: "brief"` — so the ledger names
#: the thing it recorded with the same word the wire used.
BRIEF_EVENT = "brief"
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


def _log_path(path: Path) -> Path:
    # String concatenation on purpose (not `with_suffix`): `cp.json` -> `cp.json.log.jsonl`.
    return Path(str(path) + ".log.jsonl")


def _record_brief(log_path: Path, unit_id: str, role: str) -> None:
    """F6: append the brief line — best effort, NEVER raises, never changes the brief.

    One line per call. A unit clocked in twice before it clocks out (a relaunch after a
    crashed subagent — twice in job50 alone, J50-2A and J50-8) leaves two brief lines, and a
    reader should conclude exactly that: two sessions were handed this unit's brief before
    one of them clocked out. The ledger records events, not state — the same posture as
    the log-then-commit rule, under which a retried clock-out may leave a duplicate
    accounting line and never a missing one.

    Every filesystem failure is one `except OSError` that returns: a read-only directory,
    a directory where the file belongs, a full disk. The record disappears; the brief
    does not. That is the eventlog's rule word for word ("FAILING TO LOG NEVER FAILS THE
    TOOL"), and it is the property job48 paid for: a store that refuses writes costs the
    orchestrator nothing but the record. NOT swallowed: anything that is not an OSError —
    that would be a programming error here, and hiding it would leave every unit
    `briefed: false` forever with no red anywhere.
    """
    record = {
        "event": BRIEF_EVENT,
        "ts": _timestamp(time.time()),
        "unit": unit_id,
        "role": role,
    }
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        return


def _briefed(log_path: Path, unit_id: str) -> bool:
    """F6: was a brief issued for `unit_id` since its last clock-out? Read off the ledger.

    Walk the ledger in order, tracking only lines that name this unit: a brief line sets
    the flag, an accounting line (any line that is not a brief event) clears it. The
    answer is the flag at the end. So:

    * brief, brief, clock-out            -> `briefed: true` (a relaunch; both briefs count);
    * brief, clock-out(blocked), clock-out -> the second is `briefed: false` — nobody was
      handed a brief for the second run, which is the inline-execution case F6 exists to
      surface (the cursor stays on a blocked unit, and re-running it without `clock_in`
      is the `"executed_by": "orchestrator-inline"` shape the job41 ledger self-reports);
    * brief, clock-out(blocked), brief, clock-out -> both `true`.

    The one edge this rule gets "wrong" is chosen over the one the alternative gets wrong:
    a clock-out retried after a failed commit (the documented orphan line) reads
    `briefed: false` on its duplicate — but two consecutive accounting lines for one unit
    with no brief between them are VISIBLE to a ledger reader, and the module already
    documents that shape as a retry. The alternative ("any brief line ever") would mark the
    blocked-then-inline re-run `true`, which is a false positive nobody can detect, i.e.
    the defect class this feature was built to end. Detectable false negatives beat
    undetectable false positives.

    Reads the ledger the way a reader must: a missing or unreadable log is `false`, a line
    that is not JSON or not an object is skipped, never fatal — all 217 lines in this
    repo's ledgers parse, but a ledger is a file people edit by hand during recovery.
    """
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError:
        return False
    briefed = False
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("unit") != unit_id:
            continue
        briefed = record.get("event") == BRIEF_EVENT
    return briefed


def _batch_view(document: dict) -> dict[str, Any]:
    """The `depends_on` graph of an IN-MEMORY checkpoint document. THE module's only one.

    Three callers, one loop, on purpose (job60). `plan_batches` reads a file and
    publishes the read-only batch view; `clock_in` (D1) needs the same answer to
    decide whether a requested unit may run; `clock_out` (D3) needs it about a
    document it has just MUTATED and not yet written. A second walk over
    `depends_on` written for any one of them is precisely how `plan.cursor` and
    `ready` came to answer differently about one document — the contradiction this
    job exists to close — so the loop is written once and the callers differ only
    in what they do with it.

    Returns Layer 1's answer verbatim (`{"batches", "sequence", "width"}`) or
    Layer 1's refusal verbatim (`{"result": "error", ...}` — duplicate id, unknown
    dependency, cycle). Nothing here composes, rewrites or swallows either: the
    sentences are the core's.

    The three adapter decisions moved here from `plan_batches` unchanged. A `done`
    or `dropped` unit is SATISFIED, which is two things and not one: it leaves the
    graph AND every edge pointing at it is resolved — only the first alone would be
    a defect, because `workplan.plan` refuses an edge into an id no node declares,
    so dropping the unit while keeping the edge would make every checkpoint with
    one finished unit unplannable, which is every checkpoint after its first
    clock-out. Every unit gets priority 0, the checkpoint schema having no priority
    field, so the tie-break inside a batch falls through to the core's insertion
    order — `plan.units` order. And `plan.cursor` is not read here at all: this is
    what the graph PERMITS, and what the single pointer says is the caller's
    business.
    """
    nodes = [
        # `depends_on` is required by the schema, so `_read_valid` has already refused a
        # unit without it and the default below cannot fire here. It is written anyway
        # because the Node adapter reaches the same mapping and MUST default it too: a
        # default on one side only is how two runtimes come to disagree about real data.
        {"id": unit["id"], "depends_on": list(unit.get("depends_on") or []), "priority": 0}
        for unit in document["plan"]["units"]
        if unit["status"] not in TERMINAL_UNIT_STATUS
    ]
    satisfied = {
        unit["id"] for unit in document["plan"]["units"] if unit["status"] in TERMINAL_UNIT_STATUS
    }
    for node in nodes:
        node["depends_on"] = [dep for dep in node["depends_on"] if dep not in satisfied]

    return workplan.plan(nodes)


def _ready(document: dict) -> tuple[list[str] | None, dict[str, Any] | None]:
    """`(ready, None)` or `(None, refusal)` — the ready batch of an in-memory document.

    `ready` is `batches[0]`, or `[]` when no non-terminal unit remains, which is an
    ANSWER and not a refusal — the same judgement `plan_batches` already publishes.
    The refusal arm is the core's, handed back untouched for the caller to return.
    """
    answer = _batch_view(document)
    if answer.get("result") == "error":
        return None, answer
    batches = answer["batches"]
    return (batches[0] if batches else []), None


def clock_in(checkpoint: str, unit_id: str | None = None) -> dict[str, Any]:
    """Validate the checkpoint and return a unit's brief, or a refusal.

    Refusals mirror the driver's terminal exits: ``escalate`` when
    `handoff.open_questions` is non-empty or the cursor names no unit,
    ``success`` when every unit is done/dropped. The ``brief`` payload is what
    the orchestrator hands to the spawned agent verbatim.

    WHICH UNIT (job60/D1). `unit_id` omitted is the whole prior contract, byte for
    byte — `plan.cursor`, including its `escalate` when the cursor names no unit —
    and the order of judgements above the selection is unmoved, so no existing
    refusal changes its place or its wording. `unit_id` GIVEN must name a unit the
    graph says may run now: a member of `_ready`'s batch, which is exactly
    `shiftwork_plan`'s `ready`. That is what lets an orchestrator spend the `width`
    the batch view reports instead of only ever being handed the single pointer.

    ONE refusal covers both ways that can fail, because they are one property — the
    unit is not ready — and a `unit_id` that names no unit at all is the limiting
    case of it, not a second thing to spell:

        {"result": "error", "reason": "unit C is not ready; ready is B"}

    `ready` is joined in batch order and included because the caller's next move is
    to pick from it. It cannot be empty at that point: the all-terminal check above
    has already answered `success` for a plan with no non-terminal unit, so no
    sentence is written for a case that cannot be reached. A refusal from the batch
    view ITSELF — cycle, unknown dependency — passes through VERBATIM, exactly as
    `plan_batches` passes `_read_valid`'s.

    AND CLOCK-IN STILL NEVER WRITES `plan.cursor`. A wave of N briefs leaves the
    pointer exactly where it was; `clock_out` is the only thing that moves it, and
    D3 changes only where to. The brief line records the unit ACTUALLY briefed, so
    `clock_out`'s `briefed` flag keeps working per unit with no change at all to how
    it is computed — which is what makes D2 possible with no new field anywhere.
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
    if unit_id is None:
        selected = document["plan"]["cursor"]
        unit = _find_unit(document, selected)
        if unit is None:
            return {"result": "escalate", "reason": f"cursor {selected} names no unit"}
    else:
        ready, batch_refusal = _ready(document)
        if batch_refusal is not None:
            return batch_refusal  # the core's sentence, verbatim — `_read_valid`'s idiom
        unit = _find_unit(document, unit_id)
        if unit is None or unit_id not in ready:
            return _error(f"unit {unit_id} is not ready; ready is {', '.join(ready)}")
        selected = unit_id
    # F6: the brief is issued, so say so in the ledger — best effort, and only on this
    # branch: a refusal above issued nothing and therefore records nothing.
    _record_brief(_log_path(Path(checkpoint)), selected, unit["role"])
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


def _accounting_schema() -> dict | None:
    """The accounting line's shape, read off the clock_out TOOL asset — never a second copy.

    J50-7 put the definition on `parameters.properties.accounting` of the tool manifest,
    which is what the wire advertises; but the MCP call path enforces only the Python
    signature (`dict | None`), so a host is held to what it was promised only if this
    function reads the same file. The declared value is `anyOf: [object, null]`. The null
    arm is the caller's (a null line is legal and is not an audit record), so only the
    object arm is validated here, wrapped under the key `accounting` so the pointed error
    names `accounting` / `accounting/<key>` exactly the way `checkpoint invalid:` names
    a path — one renderer for every schema refusal this module makes, not a second one.

    Returns None when the pack CANNOT SUPPLY the shape (J50-9A). Reading the asset gave
    this module a dependency the roles gate never had, and a `--assets-root` pack trimmed
    to `schemas/` — the very pack both runtimes' roles tests build — made `clock_out` die
    on `AssetNotFound` where the module's first paragraph promises a structured refusal.
    The caller turns None into `ACCOUNTING_SHAPE_UNREADABLE`, fail CLOSED, per J47-4:
    a declaration this code cannot read is not a licence. MISSING AND MALFORMED ARE ONE
    CASE, not two, because the property is one — the line cannot be checked, so it is
    not allowed — and a second sentence would either render an exception message that
    the two runtimes spell differently, or split one property into per-shape cases that
    can each be missed. The shapes folded in, each measured to raise before this existed:
    no `tools/` dir or no file (`AssetNotFound`); a file that is not UTF-8 JSON
    (`ValueError`, which is `JSONDecodeError`'s and `UnicodeDecodeError`'s base); a manifest
    without `parameters.properties.accounting.anyOf` at each step of that path (`KeyError`
    / `TypeError`); an `anyOf` with no object arm (`StopIteration` out of `next`); and an
    object arm the engine cannot use as a schema (`jsonschema.SchemaError` out of
    `schema_error`, checked here so `_accounting_refusal` only ever validates a schema).
    """
    try:
        manifest = load_tool_asset(TOOL_ASSET)
    except (AssetNotFound, OSError, ValueError):
        return None
    declared: Any = manifest
    for key in ("parameters", "properties", "accounting", "anyOf"):
        if not isinstance(declared, dict) or key not in declared:
            return None
        declared = declared[key]
    if not isinstance(declared, list):
        return None
    arm = next((a for a in declared if isinstance(a, dict) and a.get("type") == "object"), None)
    if arm is None:
        return None
    schema = {"type": "object", "properties": {"accounting": arm}}
    try:
        jsonschema.validators.validator_for(schema).check_schema(schema)
    except jsonschema.SchemaError:
        return None
    return schema


def _accounting_refusal(unit_id: str, unit: dict, accounting: dict | None) -> str | None:
    """F5 (job50): an accounting line that does not fit its declared shape is refused.

    Returns the refusal sentence, or None when the clock-out may proceed. The sentence is
    a fixed frame around the SAME `schema_error` rendering the checkpoint refusals use
    (`checkpoint invalid: …`, `refused to write: …`), so the Node side reproduces it with
    its `schemaError` over the same wrapper and the differential can compare the two.

    Measured against the ledger before this existed (J50-7): 43 of 211 lines in this repo
    carried no `duration_ms`, spelling duration eight ways, and `model` held prose 24
    times — a ledger no reader could sum. The shape is now a gate, and it is checked BEFORE
    anything is written: no accounting line, no cursor advance, the checkpoint
    byte-unchanged. Same posture as `_model_refusal`, same place in `clock_out`.

    THREE RULINGS, each pinned by a test:

    * ORDER. The roles gate runs first and keeps its sentence; this check runs second.
      That is the file's own precedent (`test_clock_out_role_check_runs_after_the_cursor_
      check`: the refusal that was already there keeps its sentence), and it decides the
      open question J50-7 left — a NON-STRING `model` under a role `job.roles` names gets
      the roles sentence (`reported model 5, which job.roles.implementer does not allow…`),
      rendered by `str()` as before; the schema's `model: string` fires only when the
      roles gate is silent (no map, or a role the map omits). A string on the role's list
      is a string, so after a roles PASS the type check on `model` cannot fire at all.
    * NULL STAYS LEGAL. `accounting: None` is not validated — the container is not
      required (J50-7 kept it optional on purpose: every OUT() conformance session and
      both call signatures default it to null). A null line is not an audit record, and
      the role gate already refuses a constrained role that reports no model.
    * ODD KEYS PASS. `additionalProperties: true` — a key the schema does not name is
      written verbatim (a refused key is friction, not safety). Only the NAMED keys have
      a type, and only `tokens` and `duration_ms` are required.
    * NO SHAPE, NO LINE (J50-9A). When the pack cannot supply the shape the line is
      refused with `ACCOUNTING_SHAPE_UNREADABLE`, in this same place, writing nothing —
      not skipped. Skipping is the fail-open this file has already had once: job47's
      record names `modelRefusal` returning unconstrained on an unreadable declaration
      as a DEFECT, and a gate that a trimmed pack silently disarms would put the ledger
      back exactly where J50-7's census found it. A null line is still not validated,
      so a pack with no `tools/` can clock out a unit that reports no accounting.

    One measured fact a port must reproduce rather than reason about: under the 2020-12
    semantics `jsonschema` applies, a float that is a whole number (`1234.0`) IS an
    `integer`; `12.5`, `"1234"`, `True` and `-1` are not. Pinned in the tests as a fact,
    not as a preference.
    """
    if accounting is None:
        return None
    schema = _accounting_schema()
    if schema is None:
        return ACCOUNTING_SHAPE_UNREADABLE
    problem = schema_error(json.dumps({"accounting": accounting}), schema)
    if problem is None:
        return None
    return (
        f"unit {unit_id} in role {unit['role']} reported an accounting line "
        f"the schema refuses: {problem}"
    )


def clock_out(
    checkpoint: str,
    unit_id: str,
    status: str,
    handoff_patch: dict[str, Any],
    history_entry: dict[str, Any],
    accounting: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a dispatched unit's result to the checkpoint, validate whole, write atomically.

    `unit_id` must name THE CURSOR UNIT OR A UNIT BRIEFED SINCE ITS OWN LAST
    CLOCK-OUT (job60/D2) — the `briefed` value `_briefed` already measures off
    `<checkpoint>.log.jsonl` and already refuses to take from the caller; anything
    else is a structured error. The widening is what makes `clock_in(unit_id=...)`
    spendable: a two-wide wave is briefed against one cursor, so if only the cursor
    could clock out, the second unit's result would have nowhere to go. A unit that
    was never dispatched still cannot clock out, and THE REFUSAL KEEPS ITS EXISTING
    SENTENCE, `unit N2 is not the cursor unit N1`, byte for byte — widened meaning,
    unwidened wording, so every ruled case pinning it stays green and
    `docs/shiftwork.md` carries the fuller meaning. The gate still runs before the
    AS-2 role/model check and before anything at all is written.

    When `job.roles` names
    the unit's role, `accounting["model"]` must be one of that role's models,
    spelled exactly; a wrong or missing model is refused here, before any
    mutation and before the accounting line. Extended 2026-09-11 (job47): so is a
    `job.roles` value for that role that is not a list of model identifiers —
    an unreadable declaration allows no model, and it is refused in the same
    place, by the same structured return, writing nothing. Extended 2026-09-13
    (job50/F5): and so is an accounting line that does not fit the shape the
    `shiftwork_clock_out` asset declares — checked after the roles gate, before
    any mutation, same structured return, nothing written; `accounting=None`
    is not validated and stays legal. Extended 2026-09-13 (J50-9A): and so is
    a non-null line under a pack that cannot supply that shape at all — one
    fixed sentence, `ACCOUNTING_SHAPE_UNREADABLE`, never `AssetNotFound` out of
    this function. Mutations: set the
    unit's status, advance `plan.cursor` to the first unit of the ready batch
    recomputed on the mutated document (job60/D3 — the graph's order, not
    `plan.units` order; see below), shallow-merge `handoff_patch` into
    `handoff`, push `history_entry` onto the 5-entry ring. The mutated
    document is validated against the full schema BEFORE any write — a
    validation failure writes nothing. Then log-then-commit: the accounting
    line is appended to `<checkpoint>.log.jsonl` first, the checkpoint is
    renamed into place second, and either step's OSError is a structured
    error that leaves the prior checkpoint bytes intact (a log line whose
    commit failed is the detectable, tolerable leftover).
    """
    path = Path(checkpoint)
    log_path = _log_path(path)
    document, refusal = _read_valid(path)
    if refusal is not None:
        return refusal
    unit = _find_unit(document, unit_id)
    if unit is None:
        return _error(f"unit {unit_id} is not in the plan")
    cursor = document["plan"]["cursor"]
    # D2: the cursor unit, OR one this checkpoint's ledger says was briefed since its own
    # last clock-out. `_briefed` is CALLED, never reimplemented — its rule (a brief line
    # sets, an accounting line clears) is the same one that writes `briefed` onto the
    # accounting line below, so the gate and the record can never disagree about a unit.
    if unit_id != cursor and not _briefed(log_path, unit_id):
        return _error(f"unit {unit_id} is not the cursor unit {cursor}")
    wrong_model = _model_refusal(document, unit_id, unit, accounting)
    if wrong_model is not None:
        return _error(wrong_model)
    bad_line = _accounting_refusal(unit_id, unit, accounting)
    if bad_line is not None:
        return _error(bad_line)

    unit["status"] = status
    # D3: the cursor follows the GRAPH, on the document as just mutated. Three arms, in
    # this order. `ready[0]` is the answer `shiftwork_plan` would publish for the same
    # bytes, so the pointer and the batch view can no longer name different units. Plan
    # order over the remaining non-terminal units is reachable ONLY when the graph cannot
    # batch at all — `ready` is computed over exactly those units, so an empty `ready`
    # with units left means the core refused (cycle, unknown dependency) — and it exists
    # so such a checkpoint can still be driven to its end: clock-out RECORDS, and a
    # recording surface does not acquire a new way to refuse. `unit_id` is the last arm,
    # unchanged from before this job. On a linear chain `ready[0] == remaining[0]["id"]`,
    # which is why every case written before D3 keeps its value.
    remaining = [u for u in document["plan"]["units"] if u["status"] not in TERMINAL_UNIT_STATUS]
    ready, _batch_refusal = _ready(document)
    if ready:
        document["plan"]["cursor"] = ready[0]
    else:
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
    # F6: `briefed` is MEASURED off the ledger, after the orchestrator's keys are merged, so
    # the runtime's answer wins over a self-reported one. `executed_by: orchestrator-inline`
    # in the job41 ledger IS a self-report, and it is the only kind the ledger ever had; a
    # key the reporter could assert would be that blind spot under a new name. It is written
    # on every line, `accounting: null` included — the base shape (ts/unit/role/status) is
    # the runtime's, and so is this field. Never a refusal.
    record["briefed"] = _briefed(log_path, unit_id)
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


def plan_batches(checkpoint: str) -> dict[str, Any]:
    """Read-only batch view of a checkpoint. Never mutates.

    The adapter over `_batch_view`, and it holds no graph logic of its own: a loop over
    `depends_on` here would be Layer 1's work done in Layer 5, and a loop over it here
    AND in `clock_in`/`clock_out` is the job60 contradiction re-created by hand. Its
    whole content is reading the file and the shape it answers in. The three decisions
    that used to be written out below — a `done`/`dropped` unit is SATISFIED (it leaves
    the graph and its edges are resolved), every unit has priority 0 so the tie-break is
    `plan.units` order, and `plan.cursor` is not consulted by the graph at all — moved
    to `_batch_view` verbatim, where all three callers now get them.

    **The cursor is ECHOED here, never written.** `clock_out` remains the only thing that
    moves it. Since job60/D3 it moves it to `ready[0]` of this same view, so the two
    fields no longer name different units — but this tool still only reports, and the
    orchestrator still reads `ready` beside `cursor` and decides. Advisory, in one
    direction only.

    Returns `{"result": "plan", "batches", "ready", "sequence", "width", "cursor"}` —
    `ready` is `batches[0]`, or `[]` when the plan is all terminal, which is an ANSWER
    and not a refusal. Refusals pass through verbatim in both directions: `_read_valid`'s
    for a checkpoint that cannot be read or does not validate, and the core's own
    duplicate-id / unknown-dependency / cycle sentences for a graph that cannot batch.
    """
    document, refusal = _read_valid(Path(checkpoint))
    if refusal is not None:
        return refusal
    answer = _batch_view(document)
    if answer.get("result") == "error":
        return answer
    batches = answer["batches"]
    return {
        "result": "plan",
        "batches": batches,
        "ready": batches[0] if batches else [],
        "sequence": answer["sequence"],
        "width": answer["width"],
        "cursor": document["plan"]["cursor"],
    }
