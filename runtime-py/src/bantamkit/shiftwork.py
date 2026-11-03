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
a missing one. Since job65 (#162) the orphan line is followed by an
`{"event": "uncommitted", ...}` marker, appended in the same failure arm, so
`_briefed` hands the brief back and the retry is ACCEPTED for a briefed
non-cursor unit too — before the marker the orphan line spent the brief and
the documented retry was refused `unit B is not the cursor unit A`. Since
job65 (#117) the caller's accounting cannot set the five keys the runtime
writes (`RESERVED_LEDGER_KEYS`): such a line is refused before anything is
written, because `record.update(accounting)` let `{"unit": "C", "event":
"brief"}` forge a brief of another unit that `_briefed` then trusted. And
since job65 (#164) `clock_in()` with no `unit_id` applies the same readiness
test as `clock_in(unit_id)`: a cursor left on a done/dropped unit or on a
unit whose dependencies have not run is refused with the one not-ready
sentence, never briefed.

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

A lock, since job65 (#116). The paragraph that stood here said the MCP topology
has one orchestrator by construction and needs none; job60's waves made that
false — a wave clocks out from several processes at once — and it was MEASURED:
two clock-outs of DIFFERENT units at one instant, 10 trials, lost 10 of 20 `ok`
answers and committed up to 5 `error` ones, on each runtime and across the two.
The whole read-modify-write now runs under `<checkpoint>.lock` (O_EXCL, the same
primitive as `driver.lock` and the hook ledger's lock, so a Python writer and a
Node writer serialise against each other on the one file they share), the temp
file is a per-writer name created exclusively, and the rename lands on the
checkpoint's resolved target (#137) so a symlinked checkpoint stays a link. A
writer that cannot take the lock is REFUSED, nothing written — never let through,
because through is the race.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

import jsonschema

from bantamkit import jobbudget, workplan
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
#: job65/#162: the `event` value of the line `clock_out` appends right after an accounting line
#: whose COMMIT failed (the temp file or the rename refused). Log-then-commit keeps the
#: accounting; this marker says the line above it did not count, so `_briefed` hands the
#: brief back and the documented retry is accepted instead of refused as "not the cursor".
UNCOMMITTED_EVENT = "uncommitted"
#: job65/#117: the keys the runtime writes on every accounting line. A caller line that sets
#: one is refused before anything is written: `record.update(accounting)` used to let
#: `{"unit": "C", "event": "brief"}` turn A's clock-out into a forged brief of C that
#: `_briefed` then trusted, and a `unit` overwritten is a cost booked to the wrong unit.
#: `briefed` is NOT here on purpose: F6 ruled a self-reported `briefed` is OVERWRITTEN by the
#: measured value, pinned on both sides, and #117 lists exactly these five.
RESERVED_LEDGER_KEYS = ("unit", "role", "status", "ts", "event")
HISTORY_RING_SIZE = 5  # the schema's maxItems — older entries fall off the ring

#: #261: the most agreements a job carries; past it, one must be retired first.
AGREEMENTS_MAX = 20
#: #225: the `event` value of the ledger line clock_in appends when a relay question's probe
#: answered it, so the escalation it replaced is counted instead of answered in chat.
RESOLVED_EVENT = "resolved"
#: #225: how long one relay probe may run, in seconds, before it counts as unanswered.
PROBE_TIMEOUT_S = 30
#: #259: the attempts a unit keeps, newest last; the oldest is dropped past this.
ATTEMPTS_KEPT = 3
#: #259: an attempt's `notes`, in code points, so both runtimes count non-ASCII text alike.
ATTEMPT_NOTES_MAX = 2000
#: job65/#116: the checkpoint's read-modify-write runs under `<checkpoint>.lock`, taken with
#: O_EXCL — the one primitive both platforms and both runtimes share without a dependency,
#: and the shape `driver.lock` and the hook ledger's lock (J65-4, #167) already use, so a
#: Python writer and a Node writer serialise against each other on the one file they share.
#: One policy differs from the ledger's: a writer that cannot take the lock within
#: `LOCK_WAIT_MS` is REFUSED, nothing written — never let through unlocked, because through
#: is exactly the race #116 measured. A lock older than `LOCK_STALE_MS` is a dead holder's.
LOCK_WAIT_MS = 5000
LOCK_STALE_MS = 30_000
LOCK_POLL_MS = 5


def _error(reason: str) -> dict[str, Any]:
    return {"result": "error", "reason": reason}


def _read_valid(path: Path) -> tuple[dict | None, dict[str, Any] | None]:
    """Read and full-schema-validate. Returns (document, None) or (None, refusal)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        # #163: invalid UTF-8 is `UnicodeDecodeError`, a ValueError and not an OSError, and it
        # escaped every tool as a raised exception while a missing file answered
        # `result: error`. Same sentence head as the missing file: the bytes could not be read.
        return None, _error(f"checkpoint unreadable: {e}")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as e:
        return None, _error(f"checkpoint is not parseable as JSON: {e}")
    problem = schema_error(text, load_schema(SCHEMA_NAME))
    if problem is not None:
        return None, _error(f"checkpoint invalid: {problem}")
    # #165: the schema cannot say that unit ids are unique, so this is the only check, and it
    # sits on the read every tool starts with: status, clock_in and clock_out now answer what
    # `shiftwork_plan` already answered through the core. Before it, `_find_unit` took the
    # first match and a clock-out of the first `A` of two left a document no job could finish.
    # The sentence is `workplan`'s, verbatim, so the plan view's answer does not move.
    seen: set[str] = set()
    for unit in document["plan"]["units"]:
        if unit["id"] in seen:
            return None, _error(f"duplicate node id {unit['id']}")
        seen.add(unit["id"])
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
    _record_event(log_path, BRIEF_EVENT, unit_id, role)


def _record_event(log_path: Path, event: str, unit_id: str, role: str) -> None:
    """One `{event, ts, unit, role}` line, best effort: the brief line (F6) and, since
    job65/#162, the `uncommitted` marker share this shape so a reader tells every event
    line from an accounting line by the one key, `event`, and never by `status`."""
    record = {
        "event": event,
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
    the flag, an accounting line (any line that is not a brief event) clears it, and —
    since job65/#162 — an `uncommitted` line restores whatever the flag was before the
    accounting line it follows, because that line's commit failed and it did not count.
    The answer is the flag at the end. So:

    * brief, brief, clock-out            -> `briefed: true` (a relaunch; both briefs count);
    * brief, clock-out(blocked), clock-out -> the second is `briefed: false` — nobody was
      handed a brief for the second run, which is the inline-execution case F6 exists to
      surface (the cursor stays on a blocked unit, and re-running it without `clock_in`
      is the `"executed_by": "orchestrator-inline"` shape the job41 ledger self-reports);
    * brief, clock-out(blocked), brief, clock-out -> both `true`.

    * brief, clock-out(uncommitted), clock-out -> the retry is `briefed: true` (#162).

    Until job65 this docstring CHOSE the opposite edge: a clock-out retried after a failed
    commit (the documented orphan line) read `briefed: false` on its duplicate, on the
    argument that two consecutive accounting lines with no brief between them are visible
    to a reader. Issue #162 measured what that cost: the orphan line also SPENT the brief,
    so the retry of a briefed non-cursor unit was refused `unit B is not the cursor unit A`
    and the documented recovery (retry) did not exist. The ruling stands for the
    blocked-then-inline re-run — "any brief line ever" would mark it `true`, an
    undetectable false positive — and the failed commit is now told apart from it by the
    `uncommitted` marker `clock_out` appends in that one place, so the reader still sees
    the retry and the runtime no longer mistakes it for an inline re-run.

    Reads the ledger the way a reader must: a missing or unreadable log is `false`, a line
    that is not JSON or not an object is skipped, never fatal — all 217 lines in this
    repo's ledgers parse, but a ledger is a file people edit by hand during recovery.
    """
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError:
        return False
    briefed = False
    before_last_accounting = False
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("unit") != unit_id:
            continue
        event = record.get("event")
        if event == BRIEF_EVENT:
            briefed = True
        elif event == UNCOMMITTED_EVENT:
            briefed = before_last_accounting
        else:
            before_last_accounting = briefed
            briefed = False
    return briefed


def _reviews_refusal(units: list[dict], declared: dict[str, list[str]]) -> str | None:
    """#263: the sentence for a reviewing unit that is not independent of its work, or None.

    A unit's `reviews` names the units it reviews. Each reviewed id must be declared by some
    unit, must be in the reviewer's own `depends_on` (a review runs after the work), and
    must belong to a unit in a different role. Units are read in `plan.units` order, each
    `reviews` in its own order, and the three tests in that order per id — first fault wins:

        unit <id> reviews <r>, which no unit declares
        unit <id> reviews <r> but does not depend on it
        unit <id> reviews <r> in the same role <role>; a review needs another role

    Terminal units are checked too: a finished review that was never independent is still
    a fault in the record. The model is not compared — AS-2 checks it per role already.
    """
    by_id = {unit["id"]: unit for unit in units}
    for unit in units:
        for reviewed in unit.get("reviews") or []:
            target = by_id.get(reviewed)
            if target is None:
                return f"unit {unit['id']} reviews {reviewed}, which no unit declares"
            if reviewed not in declared[unit["id"]]:
                return f"unit {unit['id']} reviews {reviewed} but does not depend on it"
            if target["role"] == unit["role"]:
                return (
                    f"unit {unit['id']} reviews {reviewed} in the same role {unit['role']}; "
                    "a review needs another role"
                )
    return None


def _investigation_refusal(document: dict) -> str | None:
    """#264: the sentence for an investigation whose plan cannot be trusted, or None.

    Read in this order, first fault wins: the hypothesis count (only under `job.kind:
    investigation`), then per unit in `plan.units` order its `tests`, then its `replay_of`:

        investigation declares <n> hypotheses; it needs two,
            or one with job.single_hypothesis_rationale   (one line)
        unit <id> tests <h>, which no hypothesis declares
        unit <id> replays <r>, which no unit declares
        unit <id> replays <r> in the same role <role>; a replay needs another role
        unit <id> replays <r>, which names no procedure
        unit <id> replays <r> with a different procedure

    A replay repeats the run's `procedure` as exact text (user ruling, job76): no
    normalisation, no hash. The unit keys are checked wherever they appear, so a run
    that names a hypothesis outside an investigation is a fault too, not a silent no-op.
    """
    job = document["job"]
    hypotheses = [h["id"] for h in job.get("hypotheses") or []]
    if job.get("kind") == "investigation":
        rationale = bool(job.get("single_hypothesis_rationale"))
        if len(hypotheses) < 2 and not (len(hypotheses) == 1 and rationale):
            return (
                f"investigation declares {len(hypotheses)} hypotheses; it needs two, "
                "or one with job.single_hypothesis_rationale"
            )
    units = document["plan"]["units"]
    by_id = {unit["id"]: unit for unit in units}
    for unit in units:
        for tested in unit.get("tests") or []:
            if tested not in hypotheses:
                return f"unit {unit['id']} tests {tested}, which no hypothesis declares"
        replayed = unit.get("replay_of")
        if replayed is None:
            continue
        target = by_id.get(replayed)
        if target is None:
            return f"unit {unit['id']} replays {replayed}, which no unit declares"
        if target["role"] == unit["role"]:
            return (
                f"unit {unit['id']} replays {replayed} in the same role {unit['role']}; "
                "a replay needs another role"
            )
        if target.get("procedure") is None:
            return f"unit {unit['id']} replays {replayed}, which names no procedure"
        if target["procedure"] != unit.get("procedure"):
            return f"unit {unit['id']} replays {replayed} with a different procedure"
    return None


def _run_output_refusal(unit: dict, status: str, history_entry: Any) -> str | None:
    """#264/D2: a run (`tests` or `replay_of`) clocked out done must say what it observed."""
    if status != "done" or not (unit.get("tests") or unit.get("replay_of")):
        return None
    produced = history_entry.get("produced") if isinstance(history_entry, dict) else None
    kinds = [p.get("kind") for p in produced or [] if isinstance(p, dict)]
    if "run-output" in kinds:
        return None
    return f"run {unit['id']} produced no run-output; record what it observed"


def _conclusion_refusal(document: dict, unit: dict, status: str, conclusion: Any) -> str | None:
    """#264/D4: who may conclude, and what `resolved` needs. Nothing is written on a refusal.

    Only a unit with `concludes: true` sends a conclusion. `inconclusive` and `stopped` are
    never refused past that; a conclusion that is not an object, or an outcome off the
    enum, is the schema's to refuse. `resolved` is judged on the plan as it will be once
    this clock-out lands (this unit at `status`), first fault wins:

        a resolved conclusion names no supported hypothesis
        conclusion supports <h>, which no hypothesis declares
        conclusion supports <h>, but no run testing it is done
        conclusion supports <h>, but no run testing it has a done replay
        conclusion supports <h>, but no review of its runs is done

    A refuted hypothesis needs no replay (user ruling, job76): only `supported` is checked.
    The replay's other role is the batch view's rule; the review's, #263's.
    """
    if not unit.get("concludes"):
        return (
            f"unit {unit['id']} does not conclude; "
            "job.conclusion is set only by a unit with concludes: true"
        )
    if not isinstance(conclusion, dict) or conclusion.get("outcome") != "resolved":
        return None
    supported = conclusion.get("supported")
    if supported is None:
        return "a resolved conclusion names no supported hypothesis"
    if supported not in [h["id"] for h in document["job"].get("hypotheses") or []]:
        return f"conclusion supports {supported}, which no hypothesis declares"

    def done(other: dict) -> bool:
        return (status if other is unit else other["status"]) == "done"

    units = document["plan"]["units"]
    runs = {u["id"] for u in units if supported in (u.get("tests") or []) and done(u)}
    if not runs:
        return f"conclusion supports {supported}, but no run testing it is done"
    replays = {u["id"] for u in units if u.get("replay_of") in runs and done(u)}
    if not replays:
        return f"conclusion supports {supported}, but no run testing it has a done replay"
    if not any(done(u) and set(u.get("reviews") or []) & (runs | replays) for u in units):
        return f"conclusion supports {supported}, but no review of its runs is done"
    return None


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
    units = document["plan"]["units"]
    # `depends_on` is required by the schema, so `_read_valid` has already refused a unit
    # without it and the default below cannot fire here. It is written anyway because the
    # Node adapter reaches the same mapping and MUST default it too: a default on one side
    # only is how two runtimes come to disagree about real data. Read ONCE per unit,
    # terminal units included, because the #263 review check reads them too.
    declared = {unit["id"]: list(unit.get("depends_on") or []) for unit in units}
    # #263: review independence is a property of the graph, so it is read where the graph
    # is, before the core. `review` marks it for `clock_out`, which must refuse it by name;
    # every caller that returns a batch-view refusal rebuilds it as `{result, reason}`.
    reviews = _reviews_refusal(units, declared)
    if reviews is not None:
        return {**_error(reviews), "review": True}
    # #264: an investigation's plan is a property of the graph too, refused by name the same way.
    investigation = _investigation_refusal(document)
    if investigation is not None:
        return {**_error(investigation), "review": True}
    nodes = [
        {"id": unit["id"], "depends_on": list(declared[unit["id"]]), "priority": 0}
        # #257: `touches` is passed through only when the unit declares it, so a checkpoint
        # with no `touches` anywhere gets the core's answer with no `held` key — today's.
        | ({"touches": unit["touches"]} if "touches" in unit else {})
        for unit in document["plan"]["units"]
        if unit["status"] not in TERMINAL_UNIT_STATUS
    ]
    satisfied = {
        unit["id"] for unit in document["plan"]["units"] if unit["status"] in TERMINAL_UNIT_STATUS
    }
    for node in nodes:
        node["depends_on"] = [dep for dep in node["depends_on"] if dep not in satisfied]

    answer = workplan.plan(nodes)
    if answer.get("result") != "error":
        # #259: the one read of `depends_on`, handed back for `clock_in`'s `upstream` order so
        # no second walk is written there. Callers build their own replies, so it never leaks.
        answer["declared"] = declared
    return answer


def _ready(
    document: dict,
) -> tuple[list[str] | None, dict[str, Any] | None, dict[str, list[str]]]:
    """`(ready, None, declared)` or `(None, refusal, {})` — the ready batch of a document.

    `ready` is `batches[0]`, or `[]` when no non-terminal unit remains, which is an
    ANSWER and not a refusal — the same judgement `plan_batches` already publishes.
    The refusal arm is the core's, handed back untouched for the caller to return.
    """
    answer = _batch_view(document)
    if answer.get("result") == "error":
        return None, answer, {}
    batches = answer["batches"]
    return (batches[0] if batches else []), None, answer["declared"]


def _contention(path: Path, document: dict, unit: dict) -> str | None:
    """#257/D4: the sentence when `unit` writes a file a unit still in flight writes.

    The batch view sees the checkpoint, not the briefs, so a unit briefed and not yet
    clocked out only claims its files in batch 0 if it sorts first — order cannot promise
    that. In flight is the set job60 already measures: a unit briefed since its own last
    clock-out, read by `_briefed`, CALLED and never reimplemented. The first path in
    `unit`'s `touches` order that an in-flight unit also touches is named, with the first
    such unit in `plan.units` order:

        unit <id> touches <path>, which <other> holds until its clock-out

    Checked after readiness, so a held unit (not in `ready`) keeps the readiness sentence.
    """
    mine = unit.get("touches") or []
    if not mine:
        return None
    log_path = _log_path(path)
    holders = [
        other
        for other in document["plan"]["units"]
        if other["id"] != unit["id"] and other.get("touches") and _briefed(log_path, other["id"])
    ]
    for file in mine:
        for other in holders:
            if file in other["touches"]:
                return (
                    f"unit {unit['id']} touches {file}, "
                    f"which {other['id']} holds until its clock-out"
                )
    return None


def _ledger(log_path: Path) -> list[Any]:
    """The ledger's lines, parsed, in order — a missing file is `[]`, a bad line is skipped.

    The same reader's posture as `_briefed`: a ledger is a file people edit by hand during
    recovery, so nothing in it is fatal to the reader.
    """
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError:
        return []
    lines: list[Any] = []
    for line in text.splitlines():
        try:
            lines.append(json.loads(line))
        except ValueError:
            continue
    return lines


def _budget_view(path: Path, document: dict, exclude: str | None = None) -> dict | None:
    """#262: Layer 1's budget view of this checkpoint, or None when `job.budget` is absent.

    In flight is the set job60 measures — units briefed since their own last clock-out, read
    by `_briefed` — each reserving one unit and one per-unit token estimate. `exclude` leaves
    out the unit being briefed now, so a relaunch does not reserve against itself.
    """
    limit = document["job"].get("budget")
    if limit is None:
        return None
    log_path = _log_path(path)
    in_flight = sum(
        1
        for unit in document["plan"]["units"]
        if unit["id"] != exclude and _briefed(log_path, unit["id"])
    )
    return jobbudget.budget(_ledger(log_path), limit, in_flight)


def _upstream(document: dict, dep: str) -> dict[str, Any]:
    """#259: what a dependency produced — `{unit, title, status, last}`, `last` its newest attempt.

    The graph check has already refused an edge into an id no unit declares, so `dep` is a
    unit here; a dependency with no attempts yet (finished before #259, or hand-marked done)
    answers `last: null` rather than inventing one.
    """
    unit = _find_unit(document, dep)
    attempts = unit.get("attempts") or []
    return {
        "unit": dep,
        "title": unit["title"],
        "status": unit["status"],
        "last": attempts[-1] if attempts else None,
    }


def clock_in(checkpoint: str, unit_id: str | None = None) -> dict[str, Any]:
    """Validate the checkpoint and return a unit's brief, or a refusal.

    Refusals mirror the driver's terminal exits: ``escalate`` when
    `handoff.open_questions` is non-empty or the cursor names no unit,
    ``success`` when every unit is done/dropped. The ``brief`` payload is what
    the orchestrator hands to the spawned agent verbatim.

    WHICH UNIT (job60/D1, amended job65/#164). `unit_id` omitted selects
    `plan.cursor`, including its `escalate` when the cursor names no unit, and the
    order of judgements above the selection is unmoved. `unit_id` GIVEN selects that
    unit. EITHER WAY the selected unit must be one the graph says may run now: a
    member of `_ready`'s batch, which is exactly `shiftwork_plan`'s `ready`. Until
    job65 the default path skipped that test — "the whole prior contract, byte for
    byte" — and #164 measured what the exemption cost: a cursor left on a `done` unit
    by a hand edit, or on a unit whose dependency had not run by a re-plan, was
    briefed with no refusal and no warning, which is the exact hazard job60 closed
    for the named path. The two paths now apply ONE test, so the sentence below is
    the same sentence whichever way the unit was chosen, and a graph that cannot
    batch at all refuses the default path with the core's sentence exactly as it
    refuses the named one.

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
        # #225: only a decision, or a relay its probe did not answer, is the user's.
        pending = _pending_questions(Path(checkpoint), open_questions)
        if pending:
            return {
                "result": "escalate",
                "reason": f"open question: {_question_text(pending[0])}",
                "open_questions": open_questions,
            }
    units = document["plan"]["units"]
    if all(u["status"] in TERMINAL_UNIT_STATUS for u in units):
        return {"result": "success", "reason": "all units done or dropped"}
    selected = document["plan"]["cursor"] if unit_id is None else unit_id
    unit = _find_unit(document, selected)
    if unit_id is None and unit is None:
        return {"result": "escalate", "reason": f"cursor {selected} names no unit"}
    # #164: one readiness test for both paths. A terminal cursor unit is not in `ready`
    # (the batch view drops done/dropped units), so it meets the same sentence as a unit
    # whose dependencies have not run — one property, one sentence, as D1 ruled.
    ready, batch_refusal, declared = _ready(document)
    if batch_refusal is not None:
        return _error(batch_refusal["reason"])  # the sentence verbatim, `_read_valid`'s idiom
    if unit is None or selected not in ready:
        return _error(f"unit {selected} is not ready; ready is {', '.join(ready)}")
    gate = _irreversible_gate(document, unit)
    if gate is not None:
        return gate
    contention = _contention(Path(checkpoint), document, unit)
    if contention is not None:
        return _error(contention)
    # #262/D5: last, so every refusal above keeps its sentence; nothing is written on it.
    view = _budget_view(Path(checkpoint), document, exclude=selected)
    over = jobbudget.refusal(view) if view is not None else None
    if over is not None:
        return _error(over)
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
        # #259: always present, so a brief's shape does not depend on the plan.
        "upstream": [_upstream(document, dep) for dep in declared[selected]],
        "prior_attempts": list(unit.get("attempts") or []),
        # #261: always present, `[]` when the job has adopted none.
        "agreements": list(document["job"].get("agreements") or []),
    }


def _question_text(question: Any) -> str:
    """#225: a bare string is its own text; the object form carries it in `q`."""
    return question["q"] if isinstance(question, dict) else question


def _pending_questions(path: Path, questions: list[Any]) -> list[Any]:
    """#225: the open questions still the user's, in list order; each answered relay logged.

    A bare string is a decision, as it always was, so a list of strings is pending whole
    and clock_in answers exactly what it answered before. A relay is answered when its
    probe exits 0 within PROBE_TIMEOUT_S, run by the shell from the repo root; a relay
    with no probe, a probe that fails, times out or cannot start stays pending. Each
    answered relay appends one `{event: resolved, ts, q, probe}` line, best effort, so the
    escalation it replaced is counted.
    """
    pending: list[Any] = []
    root = _repo_root(path)
    for question in questions:
        if not (isinstance(question, dict) and question.get("kind") == "relay"):
            pending.append(question)
            continue
        probe = question.get("probe")
        if not probe or not _probe_passes(probe, root):
            pending.append(question)
            continue
        record = {"event": RESOLVED_EVENT, "ts": _timestamp(time.time())}
        record.update({"q": question["q"], "probe": probe})
        try:
            with _log_path(path).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            pass
    return pending


def _probe_passes(probe: str, root: Path) -> bool:
    """#225: run one relay probe; True only on exit 0 within the timeout."""
    try:
        done = subprocess.run(
            probe,
            shell=True,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _irreversible_gate(document: dict, unit: dict) -> dict[str, Any] | None:
    """#225: an irreversible unit needs a `prove` and, under job.authorized, a granted verb.

    `irreversible` names the verb (merge, tag, publish, ...). A unit naming one without a
    `prove` command is refused; with `job.authorized` declared — the key, not its
    truthiness, as job.roles rules — a verb off the list escalates instead of briefing.
    Declaring neither keeps today's clock-in.
    """
    verb = unit.get("irreversible")
    if verb is None:
        return None
    if not unit.get("prove"):
        return _error(
            f"unit {unit['id']} is irreversible ({verb}) and names no prove command"
        )
    job = document["job"]
    if "authorized" in job and verb not in job["authorized"]:
        return {
            "result": "escalate",
            "reason": (
                f"unit {unit['id']} is irreversible ({verb}); "
                f"job.authorized does not grant {verb}"
            ),
        }
    return None


def _relay_refusal(handoff_patch: Any) -> str | None:
    """#225: a relay question a clock-out adds must carry the probe that answers it."""
    questions = handoff_patch.get("open_questions") if isinstance(handoff_patch, dict) else None
    if not isinstance(questions, list):
        return None
    for question in questions:
        relay = isinstance(question, dict) and question.get("kind") == "relay"
        if relay and not question.get("probe"):
            return f"relay question has no probe: {question.get('q')}"
    return None


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
      written verbatim (a refused key is friction, not safety), EXCEPT the five the
      runtime writes itself (`unit`, `role`, `status`, `ts`, `event`), which
      `_reserved_refusal` refuses before anything is written (job65, #117). Only the
      NAMED keys have a type, and only `tokens` and `duration_ms` are required.
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


def _zero_tokens_refusal(document: dict, unit_id: str, accounting: dict | None) -> str | None:
    """#262/D6: with `job.budget` declared, a line reporting 0 tokens is refused unless marked.

    A self-reported zero bends every later figure — the median, the remaining, the refusal —
    so a job that has a budget must either record the host's figure or say it is a guess
    with `estimate: true`. Without `job.budget` nothing reads the figure back and the line
    passes as before. Runs after the shape and reserved-key checks, before any write.
    """
    if document["job"].get("budget") is None or accounting is None:
        return None
    tokens = accounting.get("tokens")
    if tokens == 0 and not isinstance(tokens, bool) and accounting.get("estimate") is not True:
        return (
            f"accounting for {unit_id} reports 0 tokens; "
            "record the host's figure, or mark it estimate"
        )
    return None


def _agreements_change(
    document: dict, change: dict[str, Any]
) -> str | tuple[list[str], list[str], list[str]] | None:
    """#261/D2: `job.agreements` after a clock-out's `{adopt?, retire?}`, or a refusal sentence.

    `retire` removes by exact text first, then `adopt` appends what is not already listed (an
    exact duplicate is a no-op, not an error). Returns `(listed, adopted, retired)` for a
    change that moved something, `None` for one that moved nothing, or the sentence:

        no agreement reads <repr>
        agreements would number <n>; retire one first (at most 20)

    `<repr>` is the text's Python repr, the spelling the port's `reprValue` reproduces.
    """
    listed = list(document["job"].get("agreements") or [])
    retired: list[str] = []
    for text in change.get("retire") or []:
        if text not in listed:
            return f"no agreement reads {text!r}"
        listed.remove(text)
        retired.append(text)
    adopted: list[str] = []
    for text in change.get("adopt") or []:
        if text not in listed:
            listed.append(text)
            adopted.append(text)
    if len(listed) > AGREEMENTS_MAX:
        return f"agreements would number {len(listed)}; retire one first (at most {AGREEMENTS_MAX})"
    if not adopted and not retired:
        return None
    return listed, adopted, retired


def _repo_root(path: Path) -> Path:
    """#260: where a follow-up's `brief_path` is resolved — the repo the checkpoint lives in.

    The nearest ancestor of the checkpoint's directory (itself included) that holds a `.git`
    entry, or the checkpoint's directory when none does. No `git` is run; the entry's mere
    presence is the test, so a worktree's `.git` file counts as a checkout's directory does.
    """
    start = path.absolute().parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def _follow_up_unit(parent: dict, item: dict) -> dict[str, Any]:
    """#260: a follow-up as a `todo` unit. The ONE place outside `_batch_view` that names
    `depends_on` — it WRITES the key (the parent's id when the item gives none) and never
    reads the graph, which stays `_batch_view`'s alone. `verify` defaults to the parent's:
    work a unit discovered is proven the way the unit was until its brief says otherwise.
    """
    built: dict[str, Any] = {
        "id": item.get("id"),
        "title": item.get("title"),
        "brief_path": item.get("brief_path"),
        "status": "todo",
        "role": item.get("role"),
        "depends_on": item["depends_on"] if "depends_on" in item else [parent["id"]],
        "verify": item.get("verify", parent["verify"]),
    }
    if "touches" in item:
        built["touches"] = item["touches"]
    return built


def _follow_ups_refusal(
    path: Path, document: dict, unit: dict, follow_ups: list[dict[str, Any]]
) -> str | None:
    """#260/D2: the first fault in a clock-out's follow-ups, checked whole before any write.

    In this order, so a list carrying two faults names the same one on both sides:

    1. an id already in `plan.units`, or twice in the list:
       `follow-up <id> is already a unit`;
    2. a `brief_path` that is not a file under the repo (`_repo_root`):
       `follow-up <id> names brief <path>, which is not a file`;
    3. and 4. the graph with the follow-ups appended, read by `_batch_view`: an unknown
       dependency or a cycle is the planner's own sentence, verbatim;
    5. a role `job.roles` does not declare, when it declares any:
       `follow-up <id> has role <r>, which job.roles does not declare`.

    A graph that could not batch BEFORE the follow-ups is not theirs to answer for, so the
    graph refusal counts only when the document without them batches.
    """
    known = {u["id"] for u in document["plan"]["units"]}
    for item in follow_ups:
        if item.get("id") in known:
            return f"follow-up {item.get('id')} is already a unit"
        known.add(item.get("id"))
    root = _repo_root(path)
    for item in follow_ups:
        brief = item.get("brief_path")
        if not isinstance(brief, str) or not (root / brief).is_file():
            return f"follow-up {item.get('id')} names brief {brief}, which is not a file"
    before = _batch_view(document)
    after = _batch_view(
        {
            **document,
            "plan": {
                **document["plan"],
                "units": document["plan"]["units"]
                + [_follow_up_unit(unit, item) for item in follow_ups],
            },
        }
    )
    if before.get("result") != "error" and after.get("result") == "error":
        return after["reason"]
    roles = document["job"].get("roles")
    if roles is not None:
        for item in follow_ups:
            if item.get("role") not in roles:
                return (
                    f"follow-up {item.get('id')} has role {item.get('role')}, "
                    "which job.roles does not declare"
                )
    return None


def _reserved_refusal(unit_id: str, unit: dict, accounting: dict | None) -> str | None:
    """#117: an accounting line that sets a key the runtime writes is refused, nothing written.

    `record.update(accounting)` ran AFTER the base keys, so a caller could overwrite them:
    `{"unit": "C", "event": "brief"}` on A's clock-out wrote a line that `_briefed` then read
    as a brief of C, and the next `clock_out("C")` was accepted although C was never briefed,
    was not the cursor, and had a dependency still `todo` (measured: A=done B=todo C=done);
    a `unit` overwritten also books the cost to the wrong unit. The fix is a refusal rather
    than a silent merge-under because a line whose keys are dropped is a line the
    orchestrator believes it wrote. Runs after the shape check (`additionalProperties: true`
    lets these keys through it) and before any mutation, like the two gates above it.
    The keys are named in `RESERVED_LEDGER_KEYS` order, not the caller's, so both runtimes
    spell one sentence for one line. `briefed` is deliberately not here (F6: overwritten).
    """
    if accounting is None:
        return None
    present = [key for key in RESERVED_LEDGER_KEYS if key in accounting]
    if not present:
        return None
    return (
        f"unit {unit_id} in role {unit['role']} reported an accounting line "
        f"that sets the runtime's own keys: {', '.join(present)}"
    )


def clock_out(
    checkpoint: str,
    unit_id: str,
    status: str,
    handoff_patch: dict[str, Any],
    history_entry: dict[str, Any],
    accounting: dict[str, Any] | None = None,
    follow_ups: list[dict[str, Any]] | None = None,
    agreements: dict[str, Any] | None = None,
    conclusion: dict[str, Any] | None = None,
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
    real = _real_target(path)
    lock = Path(f"{real}.lock")
    held, refusal = _acquire_lock(lock)
    if refusal is not None:
        return refusal
    try:
        return _clock_out_locked(
            path,
            real,
            unit_id,
            status,
            handoff_patch,
            history_entry,
            accounting,
            follow_ups,
            agreements,
            conclusion,
        )
    finally:
        if held:
            with contextlib.suppress(OSError):
                lock.unlink()


def _real_target(path: Path) -> Path:
    """#137: the file the rename lands on — a symlinked checkpoint's TARGET, so the link stays
    a link and every other path to the same file sees the clock-out. Only the write side
    resolves: the read, the ledger and every sentence use the path as given."""
    try:
        return path.resolve()
    except (OSError, RuntimeError):  # a symlink loop, or a path the OS will not resolve
        return path


def _acquire_lock(lock: Path) -> tuple[bool, dict[str, Any] | None]:
    """Take `<checkpoint>.lock` with O_EXCL. Answers `(held, refusal)`.

    `held` is False without a refusal in exactly one case: the directory will not hold a
    lock file for a reason other than one existing (read-only, gone). The clock-out then
    goes on UNLOCKED, because the temp file that follows cannot be created there either
    and ITS refusal is the one that names the cause — the `readonly-directory-*` arms keep
    their sentences. A lock that exists is waited on; one older than `LOCK_STALE_MS` is a
    dead holder's and is removed; past `LOCK_WAIT_MS` the clock-out is refused with
    nothing written, so the caller can retry — never let through, which is the race.
    """
    deadline = time.monotonic() + LOCK_WAIT_MS / 1000
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            pass
        except OSError:
            return False, None
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(f"{os.getpid()}\n")
            return True, None
        with contextlib.suppress(OSError):
            if time.time() - os.stat(lock).st_mtime > LOCK_STALE_MS / 1000:
                os.unlink(lock)
        if time.monotonic() >= deadline:
            return False, _error(f"checkpoint locked by another clock-out, nothing written: {lock}")
        time.sleep(LOCK_POLL_MS / 1000)


def _at(e: OSError, path: Path) -> str:
    """`str(e)` with the checkpoint's own path in the filename slot (see the write path)."""
    if e.errno is None:
        return str(e)
    winerror = getattr(e, "winerror", None)
    if winerror is not None:
        return str(OSError(e.errno, e.strerror, str(path), winerror))
    return str(OSError(e.errno, e.strerror, str(path)))


def _clock_out_locked(
    path: Path,
    real: Path,
    unit_id: str,
    status: str,
    handoff_patch: dict[str, Any],
    history_entry: dict[str, Any],
    accounting: dict[str, Any] | None,
    follow_ups: list[dict[str, Any]] | None = None,
    agreements: dict[str, Any] | None = None,
    conclusion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`clock_out`'s body, run under the lock its caller holds: mutate, validate, write."""
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
    forged = _reserved_refusal(unit_id, unit, accounting)
    if forged is not None:
        return _error(forged)
    zero = _zero_tokens_refusal(document, unit_id, accounting)
    if zero is not None:
        return _error(zero)
    # A `history_entry` that is not an object is the schema's to refuse below, with the
    # sentence it has always had, so #259 reads it only when it is one.
    entry = history_entry if isinstance(history_entry, dict) else None
    notes = entry.get("notes") if entry is not None else None
    if isinstance(notes, str) and len(notes) > ATTEMPT_NOTES_MAX:
        return _error(
            f"history_entry notes are {len(notes)} code points; "
            f"an attempt keeps at most {ATTEMPT_NOTES_MAX}"
        )

    relay = _relay_refusal(handoff_patch)
    if relay is not None:
        return _error(relay)
    unobserved = _run_output_refusal(unit, status, history_entry)
    if unobserved is not None:
        return _error(unobserved)
    if conclusion is not None:
        refused = _conclusion_refusal(document, unit, status, conclusion)
        if refused is not None:
            return _error(refused)
        document["job"]["conclusion"] = conclusion

    if follow_ups:
        refused = _follow_ups_refusal(path, document, unit, follow_ups)
        if refused is not None:
            return _error(refused)
        document["plan"]["units"].extend(_follow_up_unit(unit, item) for item in follow_ups)
    if agreements:
        changed = _agreements_change(document, agreements)
        if isinstance(changed, str):
            return _error(changed)
        if changed is not None:
            listed, adopted, retired = changed
            document["job"]["agreements"] = listed
            document["retro"].append(
                {
                    "trigger": unit_id,
                    "patch_applied_to": "job.agreements",
                    "adopted": adopted,
                    "retired": retired,
                }
            )
    unit["status"] = status
    # #259: the durable per-unit record the 5-entry history ring cannot be. Built only from
    # what clock_out already receives; a malformed `produced` meets the schema check below.
    if entry is not None:
        attempt: dict[str, Any] = {"status": status, "outcome": entry.get("outcome")}
        for key in ("notes", "produced"):
            if key in entry:
                attempt[key] = entry[key]
        unit["attempts"] = ((unit.get("attempts") or []) + [attempt])[-ATTEMPTS_KEPT:]
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
    ready, batch_refusal, declared = _ready(document)
    if ready:
        document["plan"]["cursor"] = ready[0]
    else:
        document["plan"]["cursor"] = remaining[0]["id"] if remaining else unit_id
    document["handoff"].update(handoff_patch or {})
    document["history"] = (document["history"] + [history_entry])[-HISTORY_RING_SIZE:]

    problem = schema_error(json.dumps(document), load_schema(SCHEMA_NAME))
    if problem is not None:
        return _error(f"refused to write: {problem}")
    # #263: on the mutated document, before anything is written. `_ready` above swallows a
    # batch-view refusal into the plan-order fallback (a recording surface does not refuse
    # an unbatchable graph), so the review check is asked here by name.
    if batch_refusal is not None and batch_refusal.get("review"):
        return _error(batch_refusal["reason"])

    record: dict[str, Any] = {
        "ts": _timestamp(time.time()),
        "unit": unit_id,
        "role": unit["role"],
        "status": status,
    }
    record.update(accounting or {})  # #117: none of the five base keys can be in it
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

    # #116: a PER-WRITER temp name, created exclusively — never `with_suffix(".tmp")`, which
    # gave every writer of one checkpoint the same temp file (two renames of one file, so one
    # `ok` answer with nothing of it on disk) and gave a suffix-less `checkpoint` the name of
    # an unrelated sibling, `checkpoint.tmp`, which it overwrote and renamed away. #137: the
    # rename lands on `real`, the link's target. The refusal names the checkpoint AS GIVEN and
    # not the temp name: a random name in a sentence is not reproducible, and the file the
    # caller could not write is, to the caller, the checkpoint.
    tmp = Path(f"{real}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as fh:
            fh.write(json.dumps(document, indent=2) + "\n")
        tmp.replace(real)
    except OSError as e:
        with contextlib.suppress(OSError):
            tmp.unlink()
        # #162: the accounting line above is kept (log-then-commit: never lose the
        # accounting) and MARKED: this line says it did not count, so `_briefed` hands the
        # brief back and the retry the sentence invites is accepted. Best effort, like the
        # brief line — the append that just succeeded can still fail here, and then the
        # old edge (brief spent, retry refused) is what remains; the refusal is unchanged.
        _record_event(log_path, UNCOMMITTED_EVENT, unit_id, unit["role"])
        return _error(f"checkpoint unwritable, last log line uncommitted: {_at(e, path)}")

    return {
        "result": "ok",
        "unit": unit_id,
        "status": status,
        "cursor": document["plan"]["cursor"],
        "log": str(log_path),
    }


def status(checkpoint: str, search: str | None = None) -> dict[str, Any]:
    """Read-only progress summary. Never mutates the checkpoint.

    `search` (#204, J69-6) adds a `search` key: `{job, file, line}` for each line of a job
    Retention archived under this checkpoint's `.shiftwork/archive/` that holds every term of
    the query (`storage.retention.search_archived`). Without it the answer is unchanged.
    """
    document, refusal = _read_valid(Path(checkpoint))
    if refusal is not None:
        return refusal
    counts: dict[str, int] = {}
    for unit in document["plan"]["units"]:
        counts[unit["status"]] = counts.get(unit["status"], 0) + 1
    history = document["history"]
    out = {
        "result": "status",
        "cursor": document["plan"]["cursor"],
        "units": counts,
        "open_questions": len(document["handoff"]["open_questions"]),
        "last_history": history[-1] if history else None,
    }
    if search is not None:
        from bantamkit.storage.retention import search_archived

        out["search"] = search_archived(checkpoint, search)
    return out


def _budget_key(path: Path, document: dict) -> dict[str, Any]:
    """#262/D4: `{"budget": view}` when `job.budget` is declared, `{}` otherwise."""
    view = _budget_view(path, document)
    return {} if view is None else {"budget": view}


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
        return _error(answer["reason"])
    batches = answer["batches"]
    return {
        "result": "plan",
        "batches": batches,
        "ready": batches[0] if batches else [],
        "sequence": answer["sequence"],
        "width": answer["width"],
        "cursor": document["plan"]["cursor"],
    } | ({"held": answer["held"]} if "held" in answer else {}) | _budget_key(
        Path(checkpoint), document
    )
