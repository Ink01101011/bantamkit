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
 *     **never read back**, so a wrong line is never noticed by the code that wrote it;
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
 * WHAT IS NOT PORTED, DELIBERATELY. The `depends_on` field is ignored on cursor advance
 * (v1-linear, the Python module's own ruling), there is no lock (the MCP topology has one
 * orchestrator by construction), and log-then-commit ordering is preserved exactly: the
 * accounting line is appended BEFORE the atomic rename, so a partial failure can lose the
 * commit but never the accounting.
 */
import { loadSchema } from './assets.js';
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
} from './memory/pyfs.js';
import { dumpJson, fromJs, parseJson, PyJSONDecodeError, reprValue, type PyValue } from './pyjson.js';

export const SCHEMA_NAME = 'shiftwork-checkpoint';
/** The driver's SUCCESS test. */
export const TERMINAL_UNIT_STATUS: ReadonlySet<string> = new Set(['done', 'dropped']);
/** The schema's `maxItems` — older entries fall off the ring. */
export const HISTORY_RING_SIZE = 5;

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

// ----------------------------------------------------------------------------- clock_in

/**
 * Validate the checkpoint and return the cursor unit's brief, or a refusal.
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
export function clockIn(checkpoint: string): PyValue {
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
  const unit = findUnit(doc, cursor);
  if (unit === null) {
    return dict([
      ['result', str('escalate')],
      ['reason', str(`cursor ${cursor} names no unit`)],
    ]);
  }
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
 * Apply the cursor unit's result, validate the WHOLE mutated document, write atomically.
 *
 * `unitId` must name the cursor unit — the contract is execute-the-cursor (driver parity),
 * never pick-a-unit. When `job.roles` names the unit's role, `accounting.model` must be one
 * of that role's models, spelled exactly; a wrong or missing model is refused here, before
 * any mutation and before the accounting line. Mutations: set the unit's status, advance
 * `plan.cursor` to the first non-terminal unit in PLAN order (`depends_on` is ignored),
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
  if (unitId !== cursor) return errorResult(`unit ${unitId} is not the cursor unit ${cursor}`);
  const wrongModel = modelRefusal(doc, unitId, unit, accounting);
  if (wrongModel !== null) return errorResult(wrongModel);

  unit.v.set('status', str(status));
  const remaining = subList(plan, 'units').v.filter(
    (u) => !TERMINAL_UNIT_STATUS.has(text((u as PyDict).v.get('status')!)),
  );
  plan.v.set('cursor', remaining.length > 0 ? field(remaining[0] as PyDict, 'id') : str(unitId));
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

  // `Path(str(path) + ".log.jsonl")` — string concatenation on the NORMALIZED path, not
  // `with_suffix`, so `cp.json` gets `cp.json.log.jsonl` and not `cp.log.jsonl`.
  const logPath = `${path}.log.jsonl`;
  try {
    pyAppendText(logPath, `${dumpJson({ t: 'dict', v: record }, { sortKeys: true })}\n`);
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
    ['log', str(logPath)],
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
