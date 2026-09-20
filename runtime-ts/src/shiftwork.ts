/**
 * Shift-work checkpoint operations — a port of `runtime-py/src/bantamkit/shiftwork.py`,
 * statement for statement.
 *
 * The control flow is 78 executable statements and none of it is hard. The risk is
 * entirely in how the two runtimes SERIALIZE, and the checkpoint bantamkit's own jobs are
 * run from is one of the files at stake. Three artefacts leave this module and only one of
 * them is ever read back:
 *
 *   * the rewritten checkpoint — `json.dumps(document, indent=2) + "\n"`, `.tmp` then
 *     `replace()`;
 *   * the `.log.jsonl` line — `json.dumps(record, sort_keys=True) + "\n"`, append mode,
 *     read back by exactly ONE thing since job50/F6 — `briefed()`, which looks at the `unit`
 *     and `event` keys and nothing else — so a wrong line is still never noticed by the
 *     code that wrote it;
 *   * the returned dict, which the MCP surface hands straight to the model.
 *
 * THE ensure_ascii RULING. `json.dumps` defaults to `ensure_ascii=True` and
 * `JSON.stringify` has no such mode. Node must reproduce Python's escaping, not the other
 * way round: the reference implementation is the one that has already written every
 * checkpoint on disk (measured — `.shiftwork/job38-npx-public-install/checkpoint.json`
 * carries 1 `เ` run and 16 `—`, and not one raw non-ASCII byte), and a Node
 * clock_out that emitted raw UTF-8 would rewrite all 29 KB of it on its first successful
 * call. Nothing would error: the file still parses to the same strings. It would just stop
 * being diffable against the Python server's output, silently, from then on. So the escape
 * is the contract, and `pyjson.dumpJson` is where it lives — with the other three rules
 * (separators, codepoint `sort_keys`, `5.0` stays a float) that a `JSON.stringify` would
 * also have got wrong.
 *
 * WHY THE DOCUMENT IS A `PyValue` AND NOT A PLAIN OBJECT. `1` and `1.0` are one type in JS.
 * A checkpoint or an accounting record that came off the wire holding `5.0` has to leave
 * holding `5.0`, and an integer past 2^53 has to survive; both need the tagged model
 * `pyjson.ts` already carries. The three entry points therefore return `PyValue`, and the
 * MCP layer converts with `pyjson.toJs` at the last moment.
 *
 * THE AS-2 REFUSAL IS A SENTENCE, AND THE SENTENCE IS THE PORT. `clockOut` refuses an
 * accounting entry naming a model the unit's role is not allowed (`job.roles`, J46-7). The
 * rule is four lines of comparison and none of the risk is in them: it is in the two
 * refusal strings, which exist once per runtime and are copied, so the differential half of
 * the harness compares Node to Python and cannot see a change made to both. They are
 * therefore pinned as per-side literals in each runtime's own tests. The check runs at
 * validation time — after the cursor check, before the first mutation, and so before the
 * log-then-commit pair below — because a refusal taken after the append would leave an
 * orphan accounting line claiming a model that was rejected. J47-5: a role the map DOES
 * name whose value is not a list of model identifiers is refused there too — an unreadable
 * declaration allows no model, and the refusal is the same structured one, taken in the
 * same place. That makes three refusal strings, not two, and the third is likewise a
 * per-side literal.
 *
 * WHAT IS NOT PORTED, DELIBERATELY. There is no lock (the MCP topology has one orchestrator
 * by construction), and log-then-commit ordering is preserved exactly: the accounting line is
 * appended BEFORE the atomic rename, so a partial failure can lose the commit but never the
 * accounting.
 *
 * `depends_on` USED TO BE LISTED ABOVE, AND NO LONGER BELONGS THERE. `planBatches` below
 * READS `depends_on` and answers the batch view, so the module no longer ignores the field;
 * what still ignores it is CURSOR ADVANCE, which stays v1-linear (the Python module's own
 * ruling) — it moves to the first non-terminal unit in `plan.units` order, and a non-linear
 * plan still needs a planner unit to reorder `plan.units` first. The batch view is read-only
 * and moves nothing.
 *
 * AMENDED 2026-09-20 (job60). The paragraph above stands as the history and is now FALSE as a
 * description of this code: cursor advance no longer ignores `depends_on`. A read-only surface
 * answering from the graph beside a dispatch surface answering from a single pointer is two
 * answers to one question, and they were MEASURED disagreeing two ways — a two-wide `ready`
 * the driver gives no way to spend, and a cursor landing on a unit whose `depends_on` has not
 * run. `docs/superpowers/specs/2026-09-20-clock-in-unit-id-design.md` is the other half of the
 * 2026-09-18 design, not a repair of it. Three changes, all below: `clockIn` takes an optional
 * `unitId` and briefs it IF the graph says it is ready; `clockOut` accepts the cursor unit OR
 * one it briefed, keeping its existing refusal sentence; and cursor advance is `ready[0]`,
 * falling back to `plan.units` order only for a graph that cannot batch at all. There is ONE
 * loop over `depends_on` in this module (`batchView`) and three callers, because a second one
 * is precisely how the two surfaces came to disagree.
 */
import { AssetNotFound, loadSchema, loadToolAsset } from './assets.js';
import { schemaError } from './contract.js';
import {
  pyAppendText,
  pyJoin,
  PyOSError,
  pyReplace,
  pySuffix,
  pyUnlink,
  pyWithSuffix,
  pyWriteText,
  pyReadText,
  PyUnicodeDecodeError,
} from './memory/pyfs.js';
import { dumpJson, fromJs, parseJson, PyJSONDecodeError, reprValue, type PyValue } from './pyjson.js';
import { checkSchema, PyJsonSchemaUnsupported } from './pyjsonschema.js';
import { plan, type PlanNode, type PlanResult } from './workplan.js';

export const SCHEMA_NAME = 'shiftwork-checkpoint';
/** The accounting line's shape lives on the TOOL asset, not in a second copy here (F5). */
const TOOL_ASSET = 'shiftwork_clock_out';
/**
 * J50-9A/9B: the one sentence for a pack that cannot supply the accounting shape. FIXED —
 * no path, no exception text, no unit — read out of `ACCOUNTING_SHAPE_UNREADABLE` in the
 * Python module byte for byte, so a differential case can compare the two; which of the
 * shapes failed is not said, because the property is the same for all of them (see
 * `accountingSchema`).
 */
export const ACCOUNTING_SHAPE_UNREADABLE =
  "cannot clock out: the shiftwork_clock_out tool asset cannot be read as the " +
  "accounting line's shape, so it allows no accounting line";
/** The driver's SUCCESS test. */
export const TERMINAL_UNIT_STATUS: ReadonlySet<string> = new Set(['done', 'dropped']);
/** The schema's `maxItems` — older entries fall off the ring. */
export const HISTORY_RING_SIZE = 5;
/**
 * F6: the `event` value of the ledger line `clockIn` appends when it issues a brief. The word
 * is the register's own — `clock_in` answers `result: "brief"` — so the ledger names the
 * thing it recorded with the same word the wire used. `BRIEF_EVENT` in `shiftwork.py`.
 */
export const BRIEF_EVENT = 'brief';

type PyDict = Extract<PyValue, { t: 'dict' }>;
type PyList = Extract<PyValue, { t: 'list' }>;

// ------------------------------------------------------------------- tagged-value sugar

const str = (v: string): PyValue => ({ t: 'str', v });
const int = (v: number): PyValue => ({ t: 'int', v: BigInt(v) });
const dict = (entries: [string, PyValue][]): PyDict => ({ t: 'dict', v: new Map(entries) });

/** The document is schema-valid before any of these run, so the shapes are guaranteed. */
const field = (d: PyDict, key: string): PyValue => d.v.get(key)!;
const subDict = (d: PyDict, key: string): PyDict => field(d, key) as PyDict;
const subList = (d: PyDict, key: string): PyList => field(d, key) as PyList;
const text = (v: PyValue): string => (v as { v: string }).v;

/**
 * Whatever the caller handed over, as a `PyValue`.
 *
 * A value that is already tagged passes through EXACTLY — that is the route that keeps
 * `5.0` a float, and the MCP layer should take it wherever it still holds the wire bytes
 * (`pyjson.parseJson` over the raw arguments). A plain JS value goes through `fromJs` and
 * takes its one documented loss: an integral JS number cannot remember that its JSON text
 * said `5.0`, so a `{"tokens": 5.0}` that has already been through an SDK's `JSON.parse`
 * logs as `5` where Python logs `5.0`. Ruled and pinned in
 * `tools/conformance/suites/shiftwork.mjs`; the loss is upstream of this module, not in it.
 */
function asPyValue(value: unknown): PyValue {
  return isPyValue(value) ? value : fromJs(value);
}

function isPyValue(value: unknown): value is PyValue {
  return (
    typeof value === 'object' &&
    value !== null &&
    't' in value &&
    typeof (value as { t: unknown }).t === 'string' &&
    ['null', 'bool', 'int', 'float', 'str', 'list', 'dict'].includes((value as { t: string }).t)
  );
}

/** `dict(x) if x else {}` — `None` and `{}` are both the empty patch. */
function asPatch(value: unknown): Map<string, PyValue> {
  if (value === null || value === undefined) return new Map();
  const lifted = asPyValue(value);
  return lifted.t === 'dict' ? lifted.v : new Map();
}

// ------------------------------------------------------------------------------- shared

function errorResult(reason: string): PyValue {
  return dict([
    ['result', str('error')],
    ['reason', str(reason)],
  ]);
}

interface ReadResult {
  document: PyDict | null;
  refusal: PyValue | null;
}

/**
 * Read and full-schema-validate. Returns `{document}` or `{refusal}`.
 *
 * Three refusals in Python's order, and the exceptions that are NOT caught matter as much
 * as the ones that are: `read_text` raises `UnicodeDecodeError` on invalid UTF-8 and that
 * is a `ValueError`, not an `OSError`, so it escapes to the caller in both runtimes.
 *
 * `schema_error` is handed the raw TEXT rather than the parsed document, exactly as Python
 * does, so the checkpoint goes through `extract_json` + the decoder a second time and any
 * disagreement between the two parses would show up here rather than at write time.
 */
function readValid(path: string): ReadResult {
  let raw: string;
  try {
    raw = pyReadText(path);
  } catch (e) {
    if (e instanceof PyOSError) return { document: null, refusal: errorResult(`checkpoint unreadable: ${e.message}`) };
    throw e;
  }
  let document: PyValue;
  try {
    document = parseJson(raw);
  } catch (e) {
    if (e instanceof PyJSONDecodeError) {
      return { document: null, refusal: errorResult(`checkpoint is not parseable as JSON: ${e.message}`) };
    }
    throw e;
  }
  const problem = schemaError(raw, loadSchema(SCHEMA_NAME));
  if (problem !== null) return { document: null, refusal: errorResult(`checkpoint invalid: ${problem}`) };
  return { document: document as PyDict, refusal: null };
}

function findUnit(document: PyDict, unitId: string): PyDict | null {
  for (const unit of subList(subDict(document, 'plan'), 'units').v) {
    if ((unit as PyDict).v.get('id') !== undefined && text((unit as PyDict).v.get('id')!) === unitId) {
      return unit as PyDict;
    }
  }
  return null;
}

/**
 * `time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))` — UTC, SECOND precision.
 *
 * `Date.prototype.toISOString` would write `2025-08-23T06:20:00.000Z`: three digits and a
 * dot that no line Python ever appended to a `.log.jsonl` contains. `gmtime` also FLOORS
 * its float argument rather than rounding it, which is visible for every `.999`.
 */
export function timestamp(now: number): string {
  const when = new Date(Math.floor(now) * 1000);
  const pad = (n: number, w = 2): string => String(n).padStart(w, '0');
  return (
    `${pad(when.getUTCFullYear(), 4)}-${pad(when.getUTCMonth() + 1)}-${pad(when.getUTCDate())}` +
    `T${pad(when.getUTCHours())}:${pad(when.getUTCMinutes())}:${pad(when.getUTCSeconds())}Z`
  );
}

/** The injectable clock. Python reads `time.time()`; a test and the differential pin it. */
export interface ClockOptions {
  /** Seconds since the epoch, as `time.time()` returns them. */
  now?: number;
}

// ------------------------------------------------------------------------ F6: the ledger

/**
 * `Path(str(path) + ".log.jsonl")` — string concatenation on the NORMALIZED path, not
 * `with_suffix`, so `cp.json` gets `cp.json.log.jsonl` and not `cp.log.jsonl`.
 */
function logPath(path: string): string {
  return `${path}.log.jsonl`;
}

/**
 * `_record_brief`: append the brief line — best effort, NEVER throws for a store that
 * refuses writes, never changes the brief.
 *
 * One line per call. A unit clocked in twice before it clocks out (a relaunch after a
 * crashed subagent) leaves two brief lines, and a reader should conclude exactly that. The
 * ledger records events, not state.
 *
 * THE NARROWNESS IS THE PORT OF `except OSError`. `pyAppendText` converts every filesystem
 * failure into a `PyOSError` — a read-only directory, a directory where the file belongs, a
 * full disk — and that is the ONLY class swallowed here. Anything else out of this block (a
 * `TypeError` from a record that could not be dumped, a bug in this function) is not an
 * OSError in Python and is rethrown here, because hiding it would leave every unit
 * `briefed: false` forever with no red anywhere. The same `instanceof PyOSError` test the
 * two write legs of `clockOut` already use, for the same reason.
 */
function recordBrief(log: string, unitId: string, role: PyValue, now: number): void {
  const record = new Map<string, PyValue>([
    ['event', str(BRIEF_EVENT)],
    ['ts', str(timestamp(now))],
    ['unit', str(unitId)],
    ['role', role],
  ]);
  try {
    pyAppendText(log, `${dumpJson({ t: 'dict', v: record }, { sortKeys: true })}\n`);
  } catch (e) {
    if (!(e instanceof PyOSError)) throw e;
  }
}

/**
 * `str.splitlines()` — the boundaries CPython splits on, which are more than `\n`. The
 * CRLF and bare CR forms are already folded by `pyReadText` (universal newlines, as
 * `Path.read_text` folds them), so they do not need to be here, but nothing is lost by it.
 */
const SPLITLINES = /\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]/;

/**
 * `_briefed`: was a brief issued for `unitId` since its last clock-out? Read off the ledger.
 *
 * Walk the ledger in order, tracking only lines that name this unit: a brief line sets the
 * flag, an accounting line (any line that is not a brief event) clears it. The answer is the
 * flag at the end — so a clock-out CONSUMES the brief: brief, blocked, re-run without a
 * clock_in reads `false`; brief, blocked, clock_in, done reads `true`. Detectable false
 * negatives (a retried clock-out's duplicate line) beat undetectable false positives (an
 * inline re-run marked briefed because a brief was issued once, ever).
 *
 * Reads the ledger the way a reader must: a missing or unreadable log is `false`, a line
 * that is not JSON or not an object is skipped, never fatal. `record.get("unit") != unit_id`
 * is a Python `!=`, so a `unit` that is not a string never equals the id; and the read is
 * `except OSError` — a ledger that does not DECODE as UTF-8 raises out of Python's
 * `clock_out` (`UnicodeDecodeError` is a `ValueError`), so `PyUnicodeDecodeError` is
 * rethrown here for the same reason `recordBrief` rethrows: the port does not swallow what
 * the reference does not.
 */
function briefed(log: string, unitId: string): boolean {
  let content: string;
  try {
    content = pyReadText(log);
  } catch (e) {
    if (!(e instanceof PyOSError)) throw e;
    return false;
  }
  let flag = false;
  for (const line of content.split(SPLITLINES)) {
    let record: PyValue;
    try {
      record = parseJson(line);
    } catch (e) {
      if (!(e instanceof PyJSONDecodeError)) throw e;
      continue;
    }
    if (record.t !== 'dict') continue;
    const unit = record.v.get('unit');
    if (unit === undefined || unit.t !== 'str' || unit.v !== unitId) continue;
    const event = record.v.get('event');
    flag = event !== undefined && event.t === 'str' && event.v === BRIEF_EVENT;
  }
  return flag;
}

// -------------------------------------------------------------------------- the graph

/**
 * The batch view of an IN-MEMORY document — the module's ONE loop over `depends_on`.
 *
 * J60. Three callers need the same answer and only one of them has a file to read:
 * `planBatches` answers it for a checkpoint on disk, `clockIn` needs it to judge a
 * requested `unitId`, and `clockOut` needs it on the document it has just MUTATED and has
 * not written yet. A second loop for the in-memory callers is exactly how the advisory
 * surface and the dispatch surface came to disagree, which is the defect this job closes,
 * so the loop lives here and the three callers share its answer.
 *
 * The three decisions it holds are the ones `planBatches` documents — a `done` or
 * `dropped` unit is SATISFIED (it leaves the graph and every edge into it is resolved),
 * every unit has priority 0, and the cursor is not consulted at all. Refusals are the
 * core's own: a `PlanResult` that is a `PlanError` carries the duplicate-id, unknown-
 * dependency or cycle sentence, and every caller passes it on verbatim rather than
 * rewording it.
 */
function batchView(doc: PyDict): PlanResult {
  const units = subList(subDict(doc, 'plan'), 'units').v;
  const terminal = (unit: PyDict): boolean => TERMINAL_UNIT_STATUS.has(text(unit.v.get('status')!));
  const satisfied = new Set<string>();
  for (const unit of units) {
    if (terminal(unit as PyDict)) satisfied.add(text((unit as PyDict).v.get('id')!));
  }
  const nodes: PlanNode[] = [];
  for (const unit of units) {
    const u = unit as PyDict;
    if (terminal(u)) continue;
    // `list(unit.get("depends_on") or [])`. `depends_on` is REQUIRED by the schema, so
    // `readValid` has already refused a unit without it and this default cannot fire —
    // it is written anyway because the reference writes it, and a default on one side
    // only is how two runtimes come to disagree about real data.
    const declared = u.v.get('depends_on');
    const deps = declared !== undefined && declared.t === 'list' ? declared.v.map(text) : [];
    nodes.push({ id: text(u.v.get('id')!), depends_on: deps.filter((dep) => !satisfied.has(dep)), priority: 0 });
  }
  return plan(nodes);
}

/**
 * `batches[0]`, or `[]` — for a plan that is all terminal AND for a graph that refuses.
 *
 * The empty answer is what makes the refusal case fall through to the caller's own
 * fallback instead of acquiring a new way to refuse: `clockOut` RECORDS, and a recording
 * surface does not stop working because the graph it was handed cannot be batched.
 * `clockIn` never reaches this with a refusal — it returns the core's sentence first.
 */
function readyIds(view: PlanResult): string[] {
  if ('result' in view) return [];
  return view.batches.length > 0 ? view.batches[0]! : [];
}

// ----------------------------------------------------------------------------- clock_in

/**
 * Validate the checkpoint and return a unit's brief, or a refusal.
 *
 * `unitId` OMITTED IS THE CURSOR UNIT, BYTE FOR BYTE WHAT IT WAS (J60/D1). Given, it is
 * briefed instead — IF the batch view says it is ready. That is the only new judgement, it
 * is taken LAST, and the three above it are untouched, so no existing refusal moves and no
 * caller that never passes a unit can see a difference. A unit that is not ready, including
 * an id naming no unit at all, is ONE refusal carrying the list the caller's next move is to
 * pick from; a batch view that refuses (cycle, unknown dependency) passes through verbatim,
 * in both directions, exactly as `planBatches` already passes `readValid`'s.
 *
 * `ready` cannot be empty here: the all-terminal test above has already answered `success`
 * for a plan with no non-terminal unit, and a non-terminal unit that cannot batch is a
 * refusal rather than an empty list. No sentence is written for a case that cannot be
 * reached.
 *
 * STILL NEVER WRITES `plan.cursor`. A wave of N briefs leaves the pointer where it was; it
 * is `clockOut` that moves it. What each brief DOES write is its own ledger line, naming the
 * unit actually briefed, so `clockOut`'s `briefed` flag keeps working per unit with no
 * change to how it is computed — which is what makes D2 possible.
 *
 * `invariants` IS SYNTHESIZED HERE. It is not a key of the checkpoint — it is
 * `document["job"]["constraints"]` under a different name — which is precisely why a brief
 * has to be handed to a subagent verbatim and not as a path: the file at that path does not
 * contain the array. Same for `do_not`, which is `handoff.do_not`, and `files`, which is
 * `state.artifacts`.
 *
 * Order is load-bearing: open questions are checked BEFORE the all-terminal test, and the
 * all-terminal test before the cursor lookup — so an empty plan reports success rather than
 * escalating on its dangling cursor, because `all([])` is true.
 */
export function clockIn(checkpoint: string, unitId: string | null = null, options: ClockOptions = {}): PyValue {
  const { document, refusal } = readValid(pyJoin(checkpoint));
  if (refusal !== null) return refusal;
  const doc = document!;
  const handoff = subDict(doc, 'handoff');
  const openQuestions = subList(handoff, 'open_questions');
  if (openQuestions.v.length > 0) {
    return dict([
      ['result', str('escalate')],
      ['reason', str(`open question: ${text(openQuestions.v[0]!)}`)],
      ['open_questions', openQuestions],
    ]);
  }
  const units = subList(subDict(doc, 'plan'), 'units');
  if (units.v.every((u) => TERMINAL_UNIT_STATUS.has(text((u as PyDict).v.get('status')!)))) {
    return dict([
      ['result', str('success')],
      ['reason', str('all units done or dropped')],
    ]);
  }
  const cursor = text(field(subDict(doc, 'plan'), 'cursor'));
  // D1: selection, and it is the LAST judgement. `selected` differs from `cursor` only on
  // the new branch, so the dangling-cursor escalation below still says `cursor` truthfully:
  // a `unitId` that reached `selected` came out of `ready`, whose ids are `plan.units`' own,
  // and `findUnit` cannot fail for it.
  let selected = cursor;
  if (unitId !== null && unitId !== undefined) {
    const view = batchView(doc);
    if ('result' in view) return errorResult(view.reason);
    const ready = readyIds(view);
    // `", "` in BATCH order, not sorted: the order the caller would dispatch them in.
    if (!ready.includes(unitId)) return errorResult(`unit ${unitId} is not ready; ready is ${ready.join(', ')}`);
    selected = unitId;
  }
  const unit = findUnit(doc, selected);
  if (unit === null) {
    return dict([
      ['result', str('escalate')],
      ['reason', str(`cursor ${cursor} names no unit`)],
    ]);
  }
  // F6: the brief is issued, so say so in the ledger — best effort, and only on this branch:
  // a refusal above issued nothing and therefore records nothing. `pyJoin` is the same
  // normalisation `clockOut` applies before it builds ITS log path, so the two land in one file.
  // The line names the unit ACTUALLY briefed, which is what D2 reads back.
  recordBrief(logPath(pyJoin(checkpoint)), selected, field(unit, 'role'), options.now ?? Date.now() / 1000);
  return dict([
    ['result', str('brief')],
    ['unit', unit],
    ['role', field(unit, 'role')],
    ['invariants', field(subDict(doc, 'job'), 'constraints')],
    ['handoff', handoff],
    ['do_not', field(handoff, 'do_not')],
    ['files', field(subDict(doc, 'state'), 'artifacts')],
  ]);
}

// ---------------------------------------------------------------------------- clock_out

/**
 * `f"{value}"` — `str()`, which is `repr()` for everything except a string itself.
 *
 * `accounting` carries no schema, so `model` is whatever the orchestrator sent. Python
 * interpolates it with `str()` and prints `5`, `5.0`, `True`, `None`; a Node port that
 * reached for the tagged `.v` would print `5` for both floats and ints and `true` for a
 * bool. `reprValue` already spells all six the way CPython does.
 */
function pyFormat(value: PyValue): string {
  return value.t === 'str' ? value.v : reprValue(value);
}

/**
 * AS-2: a role named in `job.roles` may only report a model on its list.
 *
 * Returns the refusal sentence, or `null` when the clock-out may proceed. A role the map
 * does not name — and a checkpoint carrying no map at all — is unconstrained: that is the
 * schema's shape (J46-7) and it is what lets a checkpoint written before this feature clock
 * out unchanged, model and all.
 *
 * A role the map DOES name must say which model it ran: a missing `model` is refused with
 * the same force as a wrong one, because a rule you can escape by omitting a field is
 * enforced only against the honest. `accounting: null`, `{}` and `{"model": null}` are one
 * case in Python (`(accounting or {}).get("model") is None`) and three values here.
 *
 * Models compare exactly — no normalisation, no prefix match, no strip-the-suffix rule. The
 * map's whole value is that it is the literal list of the spellings a session logs, so a
 * spelling this job has never produced is a finding to rule on, not a string to massage.
 *
 * The two sentences are BYTE-IDENTICAL to `runtime-py`'s and are copied, never paraphrased.
 *
 * THE TEST IS KEY PRESENCE, NOT TRUTHINESS, AND THAT IS A RULING (J46-10). Both runtimes
 * spelled this `if not allowed`, which reads `roles: {implementer: []}` as unconstrained and
 * so makes an empty list a silent opt-out of the rule the checkpoint just declared. Today
 * `minItems: 1` refuses such a document during the read and nothing reaches here — but the
 * schema is a SHARED asset, the class job46 has measured three times as invisible to the
 * differential half of the harness, and a check whose safety rests on another layer's
 * keyword fails open the day that keyword moves. The DECLARATION is the key: a role the map
 * names is held to its list, and a list of nothing allows nothing. `names` is then the empty
 * string and the sentence says so. Reachable, and therefore measured: `BANTAMKIT_ASSETS` is
 * honoured by both runtimes, so the tests and the conformance corpus drive this branch
 * through a pack whose schema has lost `minItems`.
 *
 * AND A DECLARATION THIS CODE CANNOT READ IS NOT A LICENCE (J47-4, ported here as J47-5).
 * The same ruling, one step further out: a role the map names is constrained by what it
 * NAMES, and a value that is not a list of model identifiers names nothing, so it allows
 * nothing. This port failed open five ways and mangled the declaration two more. MEASURED
 * end to end under a pack whose `job.roles.additionalProperties` is `true`, with
 * `model: 'haiku'`: a string, a dict, a number, a null and a bool all came back
 * `{"result":"ok"}` with the status set, the cursor advanced and an accounting line
 * written — the clock-out COMPLETED — while `[5]` and `['ok', null]` refused with the
 * unreadable value rendered into the sentence as `5` and `ok, None`. A list holding a
 * non-string is the shape a bare kind test cannot catch, which is why the property is
 * LIST OF STRINGS and not merely list; the reference raised `TypeError: sequence item 0`
 * on exactly that input. Fail CLOSED, through the same structured `_error` return, saying
 * only what is true — the declaration cannot be read, therefore no model is allowed —
 * naming no type (a Python type name would not port: `int` against `number`) and
 * rendering no part of the value. ONE sentence for both accounting shapes: which model
 * was reported cannot matter when the declaration that would judge it is unreadable.
 * `[]` is untouched by this — an empty list IS a list of model identifiers and keeps the
 * sentence J46-10 pinned.
 */
function modelRefusal(document: PyDict, unitId: string, unit: PyDict, accounting: unknown): string | null {
  const role = text(field(unit, 'role'));
  const roles = subDict(document, 'job').v.get('roles');
  const allowed = roles === undefined || roles.t !== 'dict' ? undefined : roles.v.get(role);
  // `role not in roles`. The `t !== 'list'` arm is a TYPE guard and not a policy: the schema
  // pins the value to an array, so the only way past it is a document no read would accept.
  // AMENDED 2026-09-11 (J47-5): the two lines above stand as written and are now FALSE as a
  // description of this code. A document no read would accept is exactly what a shared asset
  // drifting produces, the arm answered `unconstrained` for every such document and the
  // clock-out completed, and `t === 'list'` was never the property anyway — `['ok', null]`
  // passed the kind test and mangled `None` into the sentence. The arm below is a POLICY.
  if (allowed === undefined) return null;
  if (allowed.t !== 'list' || !allowed.v.every((model) => model.t === 'str')) {
    return `unit ${unitId} in role ${role} cannot clock out: job.roles.${role} is not a list of model identifiers, so it allows no model`;
  }
  const names = allowed.v.map((model) => pyFormat(model)).join(', ');
  const offered = asPatch(accounting).get('model');
  if (offered === undefined || offered.t === 'null') {
    return `unit ${unitId} in role ${role} reported no model, but job.roles.${role} allows only: ${names}`;
  }
  // `offered not in allowed`. The schema pins every entry to a non-empty STRING, so the
  // only equality Python's `in` can find here is string-to-string: a `{"model": 5}` is
  // unequal to every entry and is refused, with `5` in the sentence.
  if (!allowed.v.some((model) => model.t === 'str' && offered.t === 'str' && model.v === offered.v)) {
    return `unit ${unitId} in role ${role} reported model ${pyFormat(offered)}, which job.roles.${role} does not allow: ${names}`;
  }
  return null;
}

/**
 * The accounting line's shape, read off the clock_out TOOL asset — never a second copy.
 *
 * J50-7 put the definition on `parameters.properties.accounting` of the tool manifest,
 * which is what the wire advertises; but the MCP call path enforces only the argument
 * kind (`dict`), so a host is held to what it was promised only if this function reads
 * the same file. The declared value is `anyOf: [object, null]`. The null arm is the
 * caller's (a null line is legal and is not an audit record), so only the object arm is
 * validated here, wrapped under the key `accounting` so the pointed error names
 * `accounting` / `accounting/<key>` exactly the way `checkpoint invalid:` names a path —
 * one renderer for every schema refusal this module makes, not a second one.
 *
 * Returns null when the pack CANNOT SUPPLY the shape (J50-9A, ported J50-9B). Reading the
 * asset gave this module a dependency the roles gate never had, and a `BANTAMKIT_ASSETS`
 * pack trimmed to `schemas/` — the very pack both runtimes' roles tests build — made
 * `clockOut` die on `AssetNotFound` where the module promises a structured refusal. The
 * caller turns null into `ACCOUNTING_SHAPE_UNREADABLE`, fail CLOSED, per J47-4: a
 * declaration this code cannot read is not a licence. MISSING AND MALFORMED ARE ONE CASE,
 * not two, because the property is one — the line cannot be checked, so it is not allowed —
 * and a second sentence would either render an exception message the two runtimes spell
 * differently, or split one property into per-shape cases that can each be missed. The
 * shapes folded in, each MEASURED to throw out of `clockOut` before this existed: no
 * `tools/` dir or no file (`AssetNotFound`); bytes that are not UTF-8
 * (`PyUnicodeDecodeError`) or not JSON (`SyntaxError`); a manifest without
 * `parameters.properties.accounting.anyOf` at each step of that path (`TypeError`, five
 * ways); an `anyOf` with no object arm (a hand-thrown `Error`); and an object arm the
 * validator refuses as a schema (`PyJsonSchemaUnsupported`, checked here so
 * `accountingRefusal` only ever validates a schema).
 */
function accountingSchema(): Record<string, unknown> | null {
  let manifest: unknown;
  try {
    manifest = loadToolAsset(TOOL_ASSET);
  } catch (e) {
    // `except (AssetNotFound, OSError, ValueError)`: no `tools/` dir or no file; a file the
    // OS will not hand over; bytes that are not UTF-8 (`UnicodeDecodeError`, a `ValueError`
    // there and `PyUnicodeDecodeError` here); text that is not JSON (`JSONDecodeError` there,
    // `SyntaxError` out of `JSON.parse` here). Anything else is a defect and still escapes.
    if (
      e instanceof AssetNotFound ||
      e instanceof PyOSError ||
      e instanceof PyUnicodeDecodeError ||
      e instanceof SyntaxError
    ) {
      return null;
    }
    throw e;
  }
  // `isinstance(declared, dict) and key in declared`, at each step of the path. A JSON
  // array is not a dict, and neither is `null` — `typeof null === 'object'` is not a policy.
  let declared: unknown = manifest;
  for (const key of ['parameters', 'properties', 'accounting', 'anyOf']) {
    if (!isDict(declared) || !(key in declared)) return null;
    declared = declared[key];
  }
  if (!Array.isArray(declared)) return null;
  // `next((a for a in declared if isinstance(a, dict) and a.get("type") == "object"), None)`
  const arm = declared.find((a) => isDict(a) && a.type === 'object');
  if (arm === undefined) return null;
  const schema = { type: 'object', properties: { accounting: arm } };
  // `check_schema`, taken HERE so `accountingRefusal` only ever validates a schema. The
  // port's `validate` runs the same check first and would throw the same class out of
  // `schemaError`; catching it there would make one property two sites.
  try {
    checkSchema(fromJs(schema));
  } catch (e) {
    if (e instanceof PyJsonSchemaUnsupported) return null;
    throw e;
  }
  return schema;
}

/** `isinstance(x, dict)` for a value that came out of `JSON.parse`. */
function isDict(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * F5 (job50): an accounting line that does not fit its declared shape is refused.
 *
 * Returns the refusal sentence, or null when the clock-out may proceed. The sentence is
 * a fixed frame around the SAME `schemaError` rendering the checkpoint refusals use
 * (`checkpoint invalid: …`, `refused to write: …`), over the same `{"accounting": …}`
 * wrapper the reference builds, so the differential compares like with like. The frame
 * is J50-8's, read out of `_accounting_refusal` and reproduced to the character:
 * `unit {unit_id} in role {role} reported an accounting line the schema refuses: {problem}`.
 *
 * Checked BEFORE anything is written: no accounting line, no cursor advance, the
 * checkpoint byte-unchanged. Same posture as `modelRefusal`, same place in `clockOut`.
 *
 * THREE RULINGS, decided in Python and binding here:
 *
 *   * ORDER. The roles gate runs first and keeps its sentence; this check runs second. A
 *     non-string `model` under a role `job.roles` names gets the ROLES sentence (`reported
 *     model 5, which job.roles.implementer does not allow…`); the schema's `model: string`
 *     fires only when the roles gate is silent (no map, or a role the map omits).
 *   * NULL STAYS LEGAL. `accounting: null` is not validated — the container is not
 *     required. In Node that is three spellings of nothing: the JS `null`, an omitted
 *     argument (`undefined`), and the tagged `{t: 'null'}` the MCP server hands over.
 *   * ODD KEYS PASS. `additionalProperties: true` — a key the schema does not name is
 *     written verbatim. Only the NAMED keys have a type, and only `tokens` and
 *     `duration_ms` are required.
 *   * NO SHAPE, NO LINE (J50-9A). When the pack cannot supply the shape the line is
 *     refused with `ACCOUNTING_SHAPE_UNREADABLE`, in this same place, writing nothing —
 *     not skipped. Skipping is the fail-open this file has already had once (job47's
 *     `modelRefusal` returning unconstrained on an unreadable declaration). A null line
 *     is still not validated, so a pack with no `tools/` can clock out a unit that
 *     reports no accounting.
 *
 * One measured fact reproduced rather than reasoned about: under 2020-12 semantics a float
 * that is a whole number (`1234.0`) IS an `integer`; `12.5`, `"1234"`, `true` and `-1` are
 * not. `pyjsonschema` already carries that rule (`instance.t === 'float' &&
 * Number.isInteger(instance.v)`), and the float only survives to reach it on the
 * parsed-from-bytes route — a JS-object `1234.0` is `1234` before this code sees it.
 */
function accountingRefusal(unitId: string, unit: PyDict, accounting: unknown): string | null {
  if (accounting === null || accounting === undefined) return null;
  const line = asPyValue(accounting);
  if (line.t === 'null') return null;
  const schema = accountingSchema();
  if (schema === null) return ACCOUNTING_SHAPE_UNREADABLE;
  const problem = schemaError(dumpJson(dict([['accounting', line]])), schema);
  if (problem === null) return null;
  return `unit ${unitId} in role ${text(field(unit, 'role'))} reported an accounting line the schema refuses: ${problem}`;
}

/**
 * Apply the cursor unit's result, validate the WHOLE mutated document, write atomically.
 *
 * `unitId` must name the cursor unit OR a unit briefed since its own last clock-out
 * (J60/D2) — the `briefed` value this module already computes off `<checkpoint>.log.jsonl`
 * for the accounting line and already refuses to take from the caller, so a wave of briefs
 * can be clocked out in the order the agents actually return. A unit that was never
 * dispatched still cannot be clocked out, and it is refused with the sentence it has always
 * had, unchanged in both runtimes, so every ruled case pinning it stays green;
 * `docs/shiftwork.md` carries the fuller meaning. The gate still runs BEFORE the AS-2
 * role/model check and before the first mutation. When `job.roles` names the unit's role, `accounting.model` must be one
 * of that role's models, spelled exactly; a wrong or missing model is refused here, before
 * any mutation and before the accounting line. Extended 2026-09-11 (job47): so is a
 * `job.roles` value for that role that is not a list of model identifiers — an unreadable
 * declaration allows no model, and it is refused in the same place, by the same structured
 * return, writing nothing. Extended 2026-09-13 (job50/F5): and so is an accounting line
 * that does not fit the shape the `shiftwork_clock_out` asset declares — checked after the
 * roles gate, before any mutation, same structured return, nothing written; a null
 * accounting is not validated and stays legal. Mutations: set the unit's status, advance
 * `plan.cursor` to the first unit the GRAPH says is ready (J60/D3 — `ready[0]` of the
 * mutated document, falling back to the first non-terminal unit in `plan.units` order only
 * when the graph cannot batch at all, and to `unitId` when nothing is left),
 * shallow-merge `handoffPatch` into `handoff`, push `historyEntry` onto the 5-entry ring.
 *
 * VALIDATE BEFORE WRITING, AND WRITE NOTHING ON REFUSAL. The mutated document goes through
 * the full schema before the first byte leaves; a failure returns `refused to write: …` and
 * has touched neither the checkpoint nor the log — not even in the case where the log
 * append would have succeeded, which is the one a reader assumes is safe because the log is
 * append-only.
 *
 * Key ORDER survives the mutation because a `Map.set` on an existing key keeps its slot,
 * exactly as CPython's dict does, and `json.dumps` here runs with `sort_keys=False`. A port
 * that rebuilt the document from an object literal would reorder `handoff` on every merge.
 */
export function clockOut(
  checkpoint: string,
  unitId: string,
  status: string,
  handoffPatch: unknown,
  historyEntry: unknown,
  accounting: unknown = null,
  options: ClockOptions = {},
): PyValue {
  const path = pyJoin(checkpoint);
  const { document, refusal } = readValid(path);
  if (refusal !== null) return refusal;
  const doc = document!;
  const unit = findUnit(doc, unitId);
  if (unit === null) return errorResult(`unit ${unitId} is not in the plan`);
  const plan = subDict(doc, 'plan');
  const cursor = text(field(plan, 'cursor'));
  const log = logPath(path);
  // D2: the cursor unit, or one this checkpoint's ledger says was briefed and not yet
  // clocked out. `briefed` is the SAME helper the accounting line's own field is measured
  // with, called here rather than reimplemented — two readers of one ledger is the shape
  // this job exists to remove. The sentence is unchanged, deliberately: it is pinned by
  // ruled conformance cases, and widening the wording would move every one of them.
  if (unitId !== cursor && !briefed(log, unitId)) {
    return errorResult(`unit ${unitId} is not the cursor unit ${cursor}`);
  }
  const wrongModel = modelRefusal(doc, unitId, unit, accounting);
  if (wrongModel !== null) return errorResult(wrongModel);
  const badLine = accountingRefusal(unitId, unit, accounting);
  if (badLine !== null) return errorResult(badLine);

  unit.v.set('status', str(status));
  // D3: the cursor follows the GRAPH, on the MUTATED document — the unit just finished is
  // already out of it. Three steps, and the middle one is only reachable for a graph that
  // cannot batch at all (a cycle, an unknown dependency), because `ready` is computed over
  // exactly the units `remaining` holds: a recording surface does not acquire a new way to
  // refuse, so such a checkpoint can still be driven to its end in plan order. For a linear
  // chain `ready[0] === remaining[0]`, which is why every case written before this holds its
  // value.
  const remaining = subList(plan, 'units').v.filter(
    (u) => !TERMINAL_UNIT_STATUS.has(text((u as PyDict).v.get('status')!)),
  );
  const ready = readyIds(batchView(doc));
  if (ready.length > 0) plan.v.set('cursor', str(ready[0]!));
  else plan.v.set('cursor', remaining.length > 0 ? field(remaining[0] as PyDict, 'id') : str(unitId));
  const handoff = subDict(doc, 'handoff');
  for (const [key, value] of asPatch(handoffPatch)) handoff.v.set(key, value);
  const history = subList(doc, 'history');
  doc.v.set('history', {
    t: 'list',
    v: [...history.v, asPyValue(historyEntry)].slice(-HISTORY_RING_SIZE),
  });

  const problem = schemaError(dumpJson(doc), loadSchema(SCHEMA_NAME));
  if (problem !== null) return errorResult(`refused to write: ${problem}`);

  // `record.update(accounting or {})`: the four keys the record starts with are OVERRIDABLE
  // by the orchestrator's accounting, and `sort_keys=True` means the merge order never
  // reaches the file anyway.
  const record = new Map<string, PyValue>([
    ['ts', str(timestamp(options.now ?? Date.now() / 1000))],
    ['unit', str(unitId)],
    ['role', field(unit, 'role')],
    ['status', str(status)],
  ]);
  for (const [key, value] of asPatch(accounting)) record.set(key, value);

  // F6: `briefed` is MEASURED off the ledger, AFTER the orchestrator's keys are merged, so the
  // runtime's answer wins over a self-reported one — the order is load-bearing. It is written
  // on every line, `accounting: null` included: the base shape (ts/unit/role/status) is the
  // runtime's, and so is this field. Never a refusal.
  record.set('briefed', { t: 'bool', v: briefed(log, unitId) });
  try {
    pyAppendText(log, `${dumpJson({ t: 'dict', v: record }, { sortKeys: true })}\n`);
  } catch (e) {
    if (!(e instanceof PyOSError)) throw e;
    return errorResult(`accounting log unwritable, checkpoint untouched: ${e.message}`);
  }

  const tmp = pyWithSuffix(path, `${pySuffix(path)}.tmp`);
  try {
    pyWriteText(tmp, `${dumpJson(doc, { indent: 2 })}\n`);
    pyReplace(tmp, path);
  } catch (e) {
    if (!(e instanceof PyOSError)) throw e;
    // `contextlib.suppress(OSError)` — the cleanup's own failure is not the story.
    try {
      pyUnlink(tmp);
    } catch (cleanup) {
      if (!(cleanup instanceof PyOSError)) throw cleanup;
    }
    return errorResult(`checkpoint unwritable, last log line uncommitted: ${e.message}`);
  }

  return dict([
    ['result', str('ok')],
    ['unit', str(unitId)],
    ['status', str(status)],
    ['cursor', field(plan, 'cursor')],
    ['log', str(log)],
  ]);
}

// ------------------------------------------------------------------------------- status

/**
 * Read-only progress summary. Never mutates.
 *
 * `units` is a count per status in FIRST-SEEN order — a plain `dict` built by iteration, so
 * its key order is the order the statuses appear in the plan and not an alphabetical one.
 * The result is dumped without `sort_keys` on the wire, so that order is observable.
 */
export function status(checkpoint: string): PyValue {
  const { document, refusal } = readValid(pyJoin(checkpoint));
  if (refusal !== null) return refusal;
  const doc = document!;
  const counts = new Map<string, PyValue>();
  for (const unit of subList(subDict(doc, 'plan'), 'units').v) {
    const key = text((unit as PyDict).v.get('status')!);
    const seen = counts.get(key);
    counts.set(key, int(seen === undefined ? 1 : Number((seen as { v: bigint }).v) + 1));
  }
  const history = subList(doc, 'history');
  return dict([
    ['result', str('status')],
    ['cursor', field(subDict(doc, 'plan'), 'cursor')],
    ['units', { t: 'dict', v: counts }],
    ['open_questions', int(subList(subDict(doc, 'handoff'), 'open_questions').v.length)],
    ['last_history', history.v.length > 0 ? history.v[history.v.length - 1]! : { t: 'null' }],
  ]);
}

// ------------------------------------------------------------------------- plan_batches

/**
 * Read-only batch view of a checkpoint. Never mutates.
 *
 * The adapter over `workplan.plan`, and it holds no graph logic of its own: a loop over
 * `depends_on` here would be Layer 1's work done in Layer 5. Its whole content is the three
 * decisions below plus the shape it answers in — and since J60 even the loop that applies
 * them is `batchView`'s, because `clockIn` and `clockOut` judge by the same three and a
 * second copy is how they would drift apart again.
 *
 * **A `done` or `dropped` unit is SATISFIED**, which is two things and not one: it leaves
 * the graph, AND every edge pointing at it is treated as already resolved. Only the first
 * would be a defect rather than a simplification — `workplan.plan` refuses an edge into an
 * id no node declares, so dropping the unit while keeping the edge would make every
 * checkpoint with one finished unit unplannable, which is every checkpoint after its first
 * clock-out. `todo`, `in_progress` and `blocked` are all still work and all stay in. The
 * terminal pair is `TERMINAL_UNIT_STATUS`, the same constant the driver's success test
 * uses, so "finished" means one thing in this module.
 *
 * **Every unit gets priority 0.** The checkpoint schema has no priority field and this
 * design does not add one, so the tie-break inside a batch falls through to the core's
 * insertion order — `plan.units` order, which is the order a reader of the checkpoint
 * already sees.
 *
 * **The cursor is ECHOED, never written.** `clockOut` remains the only thing that moves it;
 * this tool reports what the graph PERMITS beside the single pointer that says what the
 * driver will actually do next, so an orchestrator can read the two side by side and
 * decide. Advisory, in one direction only. Since J60 the pointer is moved BY this same view
 * (`ready[0]`), so the two fields can no longer contradict each other on a plannable graph
 * — which was the whole defect — but the echo stays an echo.
 *
 * Returns `{result: 'plan', batches, ready, sequence, width, cursor}` — `ready` is
 * `batches[0]`, or `[]` when the plan is all terminal, which is an ANSWER and not a
 * refusal. Refusals pass through verbatim in both directions: `readValid`'s for a
 * checkpoint that cannot be read or does not validate, and the core's own duplicate-id /
 * unknown-dependency / cycle sentences for a graph that cannot batch.
 */
export function planBatches(checkpoint: string): PyValue {
  const { document, refusal } = readValid(pyJoin(checkpoint));
  if (refusal !== null) return refusal;
  const doc = document!;
  const answer = batchView(doc);
  if ('result' in answer) return errorResult(answer.reason);
  const batches = answer.batches.map((batch) => ({ t: 'list', v: batch.map(str) }) as PyValue);
  return dict([
    ['result', str('plan')],
    ['batches', { t: 'list', v: batches }],
    ['ready', batches.length > 0 ? batches[0]! : { t: 'list', v: [] }],
    ['sequence', { t: 'list', v: answer.sequence.map(str) }],
    ['width', int(answer.width)],
    ['cursor', field(subDict(doc, 'plan'), 'cursor')],
  ]);
}
