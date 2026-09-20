/**
 * shiftwork — the checkpoint writer, Python against Node, byte for byte.
 *
 * THE PROPERTY: given the same checkpoint and the same call, Node writes byte-identical
 * files and returns the identical result object. Three artefacts, and only one of them is
 * ever read back — the rewritten checkpoint, the `.log.jsonl` line, and the returned dict.
 * A wrong log line is invisible to the code that wrote it, so the differential is the only
 * instrument that can see it at all.
 *
 * WHAT IS COMPARED
 *   1. `json.dumps` over a corpus built for the four ways the two runtimes disagree:
 *      `ensure_ascii`, separators, codepoint `sort_keys`, and `5.0`. Each document is run
 *      at both indent settings and both sort settings, so 4 answers per document.
 *   2. `shiftwork._timestamp` over a sweep of epoch values — UTC, second precision, floored.
 *   3. Whole SESSIONS: a temp directory, a checkpoint written into it byte for byte, and a
 *      list of calls. After every call the harness compares the returned dict, the
 *      checkpoint's bytes, the log's bytes, and whether a `.tmp` was left behind. The
 *      refusal arms are in here too, and for those the file bytes ARE the assertion: a
 *      refusal that wrote something would show up as a checkpoint that differs from the one
 *      the reference did not touch.
 *
 * Python runs first over `${scratch}/c<N>`, the directories are then deleted, and Node runs
 * over the SAME paths. That is not tidiness: the log path and every errno sentence embed
 * the absolute path, so two different directories would compare two different strings and
 * the run would fail for a reason that is not the port's.
 *
 * The checkpoint corpus is `tools/shiftwork/example-codefix-checkpoint.json`, COPIED into
 * scratch and exercised there — see the note on `REAL_CHECKPOINT` below for why it is the
 * tracked template and not the live job file it used to be.
 */
import { chmodSync, cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'shiftwork';
export const summary = 'the checkpoint writer: ensure_ascii, sort_keys, separators, 5.0';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'shiftwork_ref.py');
/**
 * THE CHECKPOINT CORPUS IS THE TRACKED TEMPLATE, and it used to be the live job file.
 *
 * `.shiftwork/job38-npx-public-install/checkpoint.json` is excluded by `.gitignore`, so
 * this module threw at IMPORT time on a runner — MEASURED, run 32643739343: an uncaught
 * ENOENT that took `store`, `validate` and `wire` down with it, on all four cells, because
 * `run.mjs` imports the suites in order. Three suites that had never been run anywhere but
 * one laptop were not even reached.
 *
 * Machine-dependence was only half of it. The live file MUTATES while the job runs — its
 * `plan.cursor` advances, its history grows — so two runs an hour apart compared different
 * documents under one case name. A conformance corpus whose bytes move on their own cannot
 * fail honestly and cannot pass honestly either.
 *
 * `tools/shiftwork/example-codefix-checkpoint.json` is tracked, is the template CLAUDE.md
 * points at, and is schema-valid by construction. It is smaller and it carries one em dash
 * where the live file carried Thai — so the `ensure_ascii` property does NOT rest on it:
 * the Thai and the `\u2014` that prove that property are written inline into the sessions
 * below and into the `dumps` corpus, where they are visible in this file instead of
 * depending on what somebody's working directory happened to contain.
 */
const REAL_CHECKPOINT = join(repoRoot, 'tools', 'shiftwork', 'example-codefix-checkpoint.json');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');
const b64bytes = (buf) => buf.toString('base64');
const unb64bytes = (s) => Buffer.from(s, 'base64');

// ============================================================================ documents

/** A checkpoint the shipped schema accepts, with the job's own Thai ruling inside it. */
function baseDocument(over = {}) {
  return {
    version: 1,
    job: {
      id: 'job38-npx-public-install',
      goal: 'byte-compatible with the Python server it stands beside',
      done_definition: 'a tarball that answers a handshake — with no Python',
      constraints: [
        'PURE NODE at runtime.',
        'เป้าหมายในการ publish คือทีมฉันใช้ node npx ก็ควรใช้แค่ npx แล้วรัน node แทน pipe/uv',
        'BYTE-COMPATIBILITY IS THE PRODUCT — a difference is a ruling, never an accident',
      ],
    },
    plan: {
      cursor: 'N1',
      units: [
        { id: 'N1', title: 'first — with a dash', brief_path: 'briefs/N1.md', status: 'todo', role: 'implementer', depends_on: [], verify: 'npm test' },
        { id: 'N2', title: 'second', brief_path: 'briefs/N2.md', status: 'todo', role: 'reviewer', depends_on: ['N1'], verify: 'npm test' },
        { id: 'N3', title: 'ที่สาม', brief_path: 'briefs/N3.md', status: 'blocked', role: 'planner', depends_on: [], verify: 'npm test' },
      ],
    },
    state: {
      repo: { branch: 'feat/npx-public-install', head_sha: 'cb5c328', dirty: true },
      artifacts: [
        { path: '.shiftwork/job38-npx-public-install/probe-findings.md', role: 'evidence — read first' },
        { path: 'runtime-ts/src/pyjson.ts', role: 'the seam' },
      ],
      external: [{ kind: 'pr', ref: '#66', status: 'merged' }],
    },
    history: [],
    retro: [],
    handoff: {
      next_action: 'clock in N1 — hand the brief verbatim',
      open_questions: [],
      do_not: ['do not npm publish', 'อย่าแก้ runtime-py'],
    },
    ...over,
  };
}

/** Raw UTF-8 on disk, which is what a human writes and what Python then re-escapes. */
const raw = (document) => `${JSON.stringify(document, null, 2)}\n`;

const realCheckpointText = readFileSync(REAL_CHECKPOINT, 'utf8');
/** The SAME real document, written back out with its Thai and em dashes un-escaped. */
const realCheckpointRaw = `${JSON.stringify(JSON.parse(realCheckpointText), null, 2)}\n`;
/** The unit these sessions clock out. Read from the document, never hardcoded. */
const CURSOR = JSON.parse(realCheckpointText).plan.cursor;

// ================================================================= the json.dumps corpus

/**
 * Raw JSON TEXT, because the point is what the DECODER built: a text of `5.0` and a text of
 * `5` differ on both sides, and handing over a parsed object would erase the difference.
 */
const DUMP_TEXTS = [
  ['ascii', '{"a": 1, "b": "two", "c": [true, false, null]}'],
  ['thai', '{"ruling": "เป้าหมายในการ publish คือทีมฉันใช้ node npx"}'],
  ['emdash', '{"note": "the em dash \\u2014 and the en dash \\u2013"}'],
  ['thai-and-emdash', '{"k": "แ\\u2014 mixed \\u0e01\\u0e02 \\u2014"}'],
  ['astral', '{"face": "\\ud83d\\ude00", "chicken": "\\ud83d\\udc14"}'],
  ['del-and-c0', '{"del": "\\u007f", "c0": "\\u0000\\u0001\\u001f", "vt": "\\u000b"}'],
  ['short-escapes', '{"s": "\\b\\f\\n\\r\\t"}'],
  ['quote-and-backslash', '{"s": "quote \\" backslash \\\\ solidus /"}'],
  ['bom-and-separators', '{"s": "\\ufeff\\u2028\\u2029\\u00a0\\u00ad"}'],
  ['surrogate-boundary', '{"s": "\\ud7ff\\ue000\\uffff"}'],
  ['empty-containers', '{"d": {}, "l": [], "nested": {"a": [], "b": {}}}'],
  ['nested-deep', '{"a": {"b": {"c": [1, [2, [3, {"d": 4}]]]}}}'],
  ['top-level-list', '[1, "two", {"three": 3}, [], {}]'],
  ['top-level-scalar', '"just a \\u0e01 string"'],
  // ---- floats. Every one of these is a place JS and Python format differently.
  ['float-5.0', '{"n": 5.0}'],
  ['float-neg-zero', '{"n": -0.0, "m": 0.0}'],
  ['float-17-sig', '{"n": 0.30000000000000004}'],
  ['float-round-trip-17', '{"n": 1234567890123456.7}'],
  ['float-1e16', '{"n": 1e16}'],
  ['float-1e17', '{"n": 1e17}'],
  ['float-1e15', '{"n": 1e15}'],
  ['float-1e-4', '{"n": 1e-4}'],
  ['float-1e-5', '{"n": 1e-5}'],
  ['float-1e-7', '{"n": 1e-7}'],
  ['float-1e21', '{"n": 1e21}'],
  ['float-1e22', '{"n": 1e22}'],
  ['float-min-subnormal', '{"n": 5e-324}'],
  ['float-max', '{"n": 1.7976931348623157e308}'],
  ['float-tenth', '{"n": 0.1, "m": 0.2, "s": 0.30000000000000004}'],
  ['float-negatives', '{"a": -5.0, "b": -1e16, "c": -1e-5}'],
  ['float-exponent-width', '{"a": 1e100, "b": 1e-100, "c": 1e5}'],
  // ---- integers. Python's are unbounded; a double is not.
  ['int-2-53', '{"n": 9007199254740992}'],
  ['int-2-53-plus-1', '{"n": 9007199254740993}'],
  ['int-huge', '{"n": 12345678901234567890123456789}'],
  ['int-huge-negative', '{"n": -12345678901234567890123456789}'],
  ['int-zero-and-neg', '{"a": 0, "b": -0, "c": -1}'],
  // ---- key order. The first is the case UTF-16 gets wrong.
  ['keys-astral-vs-pua', '{"\\ud83d\\ude00": 1, "\\ue000": 2, "z": 3, "\\uffff": 4}'],
  ['keys-ascii', '{"b": 1, "A": 2, "a": 3, "_": 4, "": 5, "0": 6, "~": 7}'],
  ['keys-thai', '{"\\u0e01": 1, "z": 2, "\\u0e5b": 3, "A": 4}'],
  ['keys-prefix', '{"ab": 1, "a": 2, "abc": 3, "b": 4}'],
  ['keys-combining', '{"e\\u0301": 1, "\\u00e9": 2}'],
];

// ==================================================================== the timestamp sweep

const TIMESTAMPS = [
  0, 1, -1, 0.9, 1.999999, 951782400, 951782400.5, 1755930000, 1755930000.999,
  2147483647, 2147483648, 4102444800, 1709164800, 1709251199.99, 1735689599, 1735689600,
  946684800, 1078012800, 1583020800, 32503680000,
];

// =========================================================================== the sessions

/**
 * A call list is executed left to right, and the harness snapshots the world after each
 * step. `handoff_patch`, `history_entry` and `accounting` travel as JSON TEXT so that each
 * runtime's own decoder builds them — which is the route that keeps `5.0` a float.
 */
/**
 * `IN()` is the cursor unit — the whole contract before job60, unchanged. `IN('N2')` names a
 * unit and is the D1 argument: both sides receive it in the same positional slot, so a case
 * that asks for a specific unit is one field on the shared call list and not two code paths.
 */
const IN = (unitId = null) => ({ fn: 'clock_in', unit_id: unitId });
/** The note the F8 sessions write, read back per side below — so it is one literal, not two. */
const HANDOFF_NOTE = 'gate baseline at plan time — 3989 cases, 0 failures; เป้าหมาย: parity';
const ST = () => ({ fn: 'status' });
const OUT = (unit, status, over = {}) => ({
  fn: 'clock_out',
  unit,
  status,
  now: 1755930000,
  handoff_patch: null,
  history_entry: b64(JSON.stringify({ unit, outcome: status })),
  accounting: null,
  ...over,
});

function sessions(packDir, anyPackDir, brokenPacks) {
  const cases = [];
  const add = (name, checkpoint, calls, extra = {}) => cases.push({ name, file: 'checkpoint.json', checkpoint, calls, ...extra });

  add('template-checkpoint-read', b64(realCheckpointText), [IN(), ST()]);
  add('template-checkpoint-write', b64(realCheckpointText), [
    IN(),
    OUT(CURSOR, 'done', {
      handoff_patch: b64(JSON.stringify({ next_action: 'clock in N7 — the MCP wiring' })),
      history_entry: b64(JSON.stringify({ unit: CURSOR, outcome: 'done', notes: 'ensure_ascii ruled — เป้าหมาย' })),
      accounting: b64('{"tokens": 110623, "duration_ms": 745045.0, "model": "claude-opus-5[1m]", "\\u0e01": "\\u2014"}'),
    }),
    ST(),
  ]);
  // The SAME document, written to disk un-escaped. The first clock-out must put every one
  // of those bytes back into `\uXXXX` form, or the two servers stop producing the same file.
  add('template-checkpoint-raw-utf8', b64(realCheckpointRaw), [IN(), OUT(CURSOR, 'done'), ST()]);

  add('sequence-to-success', b64(raw(baseDocument())), [
    IN(),
    OUT('N1', 'done', { now: 1755930000.25 }),
    IN(),
    OUT('N2', 'dropped', { now: 1755930061.75 }),
    IN(),
    ST(),
  ]);

  add('cursor-stays-when-nothing-remains', b64(raw(baseDocument({
    plan: { cursor: 'N1', units: [{ id: 'N1', title: 't', brief_path: 'b', status: 'todo', role: 'implementer', depends_on: [], verify: 'v' }] },
  }))), [OUT('N1', 'done'), IN(), ST()]);

  add('handoff-shallow-merge-keeps-key-slots', b64(raw(baseDocument())), [
    OUT('N1', 'done', { handoff_patch: b64(JSON.stringify({ do_not: ['only this'], next_action: 'ต่อไป — N2' })) }),
  ]);
  add('handoff-patch-empty-object', b64(raw(baseDocument())), [OUT('N1', 'done', { handoff_patch: b64('{}') })]);
  add('handoff-patch-null', b64(raw(baseDocument())), [OUT('N1', 'done', { handoff_patch: null })]);

  // ---- job50/F8: `handoff.notes` is a declared key. The first session is the accept path
  // through the runtime's OWN schema loader — which is the route the `validate` suite does
  // not take (it hands both sides the schema text itself), and the route on which a stale
  // vendored `runtime-ts/assets/` copy refused `notes` for J50-5 while `assets/` accepted
  // it. The Thai and the em dash are there so the note's bytes go through `ensure_ascii`
  // like every other string in the document. The second session is the overwrite the
  // schema's description promises: the empty string replaces an older note, it does not
  // leave it standing.
  add('handoff-notes-accepted', b64(raw(baseDocument())), [
    OUT('N1', 'done', { handoff_patch: b64(JSON.stringify({ notes: HANDOFF_NOTE })) }),
    ST(),
  ]);
  const olderNote = baseDocument();
  olderNote.handoff.notes = 'older note — should not survive';
  add('handoff-notes-empty-string-overwrites', b64(raw(olderNote)), [
    OUT('N1', 'done', { handoff_patch: b64(JSON.stringify({ notes: '' })) }),
  ]);

  const ring = baseDocument();
  ring.history = [1, 2, 3, 4, 5].map((n) => ({ unit: `old${n}`, outcome: 'done', notes: `note ${n} — kept` }));
  add('history-ring-overflow', b64(raw(ring)), [ST(), OUT('N1', 'done'), ST()]);

  const four = baseDocument();
  four.history = [1, 2, 3, 4].map((n) => ({ unit: `old${n}`, outcome: 'done' }));
  add('history-ring-exactly-full', b64(raw(four)), [OUT('N1', 'done')]);

  // ---- accounting: the four base keys are overridable, and the sort is by codepoint.
  //
  // J50-10: every line here carries `tokens` and `duration_ms`. Since job50/F5 `clock_out`
  // refuses a line without them, and a refused line writes NO log — so these three sessions
  // had gone on comparing `(absent)` to `(absent)` under names that promise a written line.
  // The two keys are put where they also do work: `tokens` is the big integer and
  // `duration_ms` the `5.0` in the second session, so the shape check has to agree that an
  // unbounded integer and a whole float are both `integer`, before the serializer is reached.
  add('accounting-overrides-and-sorts', b64(raw(baseDocument())), [
    OUT('N1', 'done', {
      accounting: b64('{"ts": "overridden", "role": "planner", "\\ud83d\\ude00": 1, "\\ue000": 2, "z": 3, "": 4, "tokens": 1, "duration_ms": 2}'),
    }),
  ]);
  add('accounting-float-and-bigint', b64(raw(baseDocument())), [
    OUT('N1', 'done', {
      accounting: b64('{"n": 5.0, "neg0": -0.0, "tokens": 12345678901234567890123, "duration_ms": 5.0, "sci": 1e16, "tiny": 1e-5, "s": "\\u0e01 \\u2014"}'),
    }),
  ]);
  add('accounting-nested', b64(raw(baseDocument())), [
    OUT('N1', 'done', { accounting: b64('{"nested": {"b": [1, 2.0, {"z": null}], "a": true}, "empty": {}, "tokens": 1, "duration_ms": 1}') }),
  ]);

  // ---- escalate / success arms
  const questions = baseDocument();
  questions.handoff.open_questions = ['เป้าหมาย — should the tag move?', 'second question'];
  add('open-questions-escalate', b64(raw(questions)), [IN(), ST()]);

  // The order of clock_in's two terminal tests, made observable: a job whose units are ALL
  // terminal but whose handoff still carries an open question must ESCALATE, not report
  // success. Nothing else in the corpus has both at once, so nothing else can see the order.
  const questionsAndDone = baseDocument();
  questionsAndDone.handoff.open_questions = ['เป้าหมาย — answer before closing'];
  for (const u of questionsAndDone.plan.units) u.status = 'done';
  add('open-questions-outrank-all-terminal', b64(raw(questionsAndDone)), [IN(), ST()]);

  const allDone = baseDocument();
  for (const u of allDone.plan.units) u.status = u.id === 'N2' ? 'dropped' : 'done';
  add('all-terminal-success', b64(raw(allDone)), [IN(), ST()]);

  const emptyPlan = baseDocument();
  emptyPlan.plan.units = [];
  add('empty-plan-is-success-not-escalate', b64(raw(emptyPlan)), [IN(), ST()]);

  const dangling = baseDocument();
  dangling.plan.cursor = 'ZZ';
  add('dangling-cursor-escalates', b64(raw(dangling)), [IN(), ST(), OUT('N1', 'done')]);

  // ---- refusals. The FILE BYTES after each are the assertion.
  //
  // J50-6: the unknown key here USED TO BE `notes`. job50/F8 declared `handoff.notes`, so
  // from that change on this case clocked out fine on both sides and stayed green under a
  // name that said "refuse" — a differential cannot see a refusal that stopped happening on
  // both sides at once. `note` is one letter short of the key that now exists, which is the
  // typo the F8 amendment promises is still refused, and the per-side `handoff/` block
  // below pins that refusal as a BIT so a schema that opened `handoff` would go red here.
  add('refuse-handoff-additional-properties', b64(raw(baseDocument())), [
    OUT('N1', 'done', { handoff_patch: b64(JSON.stringify({ note: 'nope' })) }),
    IN(),
  ]);
  add('refuse-handoff-notes-not-a-string', b64(raw(baseDocument())), [
    OUT('N1', 'done', { handoff_patch: b64(JSON.stringify({ notes: 5 })) }),
    IN(),
  ]);
  add('refuse-history-missing-unit', b64(raw(baseDocument())), [
    OUT('N1', 'done', { history_entry: b64(JSON.stringify({ outcome: 'done' })) }),
    IN(),
  ]);
  add('refuse-history-not-an-object', b64(raw(baseDocument())), [
    OUT('N1', 'done', { history_entry: b64('"just a string"') }),
  ]);
  add('refuse-history-null-entry', b64(raw(baseDocument())), [OUT('N1', 'done', { history_entry: null })]);
  add('refuse-status-outside-enum', b64(raw(baseDocument())), [OUT('N1', 'finished')]);
  add('refuse-status-non-ascii', b64(raw(baseDocument())), [OUT('N1', 'เสร็จ')]);
  add('refuse-not-the-cursor-unit', b64(raw(baseDocument())), [OUT('N2', 'done'), IN()]);
  add('refuse-unit-not-in-plan', b64(raw(baseDocument())), [OUT('ZZ', 'done'), IN()]);
  add('refuse-handoff-open-question-empty-string', b64(raw(baseDocument())), [
    OUT('N1', 'done', { handoff_patch: b64(JSON.stringify({ open_questions: [''] })) }),
  ]);

  // ---- the read side's three refusals
  add('missing-checkpoint', null, [IN(), ST(), OUT('N1', 'done')]);
  add('unparseable-checkpoint', b64('{"version": 1,}\n'), [IN(), ST()]);
  add('unparseable-trailing-data', b64('{"version": 1} trailing\n'), [IN()]);
  add('unparseable-non-ascii-offset', b64('{"\\u0e01\\ud83d\\ude00": 1,}\n'.replace('\\u0e01\\ud83d\\ude00', 'ก😀')), [IN()]);
  const invalid = baseDocument();
  delete invalid.retro;
  add('schema-invalid-checkpoint', b64(raw(invalid)), [IN(), ST(), OUT('N1', 'done')]);
  const invalidDeep = baseDocument();
  invalidDeep.plan.units[0].role = 'nobody';
  add('schema-invalid-deep', b64(raw(invalidDeep)), [IN()]);
  add('checkpoint-is-a-list', b64('[1, 2, 3]\n'), [IN()]);

  // ---- a UTF-8 BOM in front of the document. `read_text(encoding="utf-8")` KEEPS the
  // U+FEFF (`utf-8-sig` is the codec that strips it) and `json.loads` then refuses with
  // `Unexpected UTF-8 BOM (decode using utf-8-sig)`. This port's `pyDecodeUtf8` used to drop
  // it — `TextDecoder` defaults `ignoreBOM` to false — so a BOM'd checkpoint PARSED here and
  // a clock-out WROTE to it, while the reference server refused the same file. The second
  // case puts the BOM on an otherwise-broken document, so the offsets in the decoder's
  // message are counted over a string that still holds the BOM character.
  add('bom-checkpoint', b64(`\ufeff${raw(baseDocument())}`), [IN(), ST(), OUT('N1', 'done')]);
  add('bom-then-unparseable', b64('\ufeff{"version": 1,}\n'), [IN()]);
  add('bom-mid-document', b64(raw(baseDocument()).replace('"version"', '"\ufeffversion"')), [IN()]);

  // ---- CRLF: `read_text` translates, so a CRLF checkpoint must behave like an LF one.
  // A CRLF document that FAILS to parse on a later line. `read_text` folds `\r\n` to `\n`
  // before `json.loads` sees it, so the decoder's `line N column M (char P)` counts one
  // character per line break and not two. Without the fold every offset past line 1 drifts.
  add('crlf-unparseable-on-a-later-line', b64('{\r\n  "version": 1,\r\n  "job": {,\r\n  }\r\n}\r\n'), [IN()]);
  add('crlf-unparseable-deep', b64(`${JSON.stringify(baseDocument(), null, 2).replace(/\n/g, '\r\n').slice(0, -1)},\r\n`), [IN()]);
  add('lone-cr-inside-a-string', b64('{"version": 1, "job": "a\rb"}\n'), [IN()]);
  add('crlf-checkpoint', b64(raw(baseDocument()).replace(/\n/g, '\r\n')), [IN(), OUT('N1', 'done')]);

  // ---- path shapes. Every one of these reaches a STRING the caller reads.
  cases.push({
    name: 'path-normalized-before-use',
    file: 'checkpoint.json',
    checkpoint: b64(raw(baseDocument())),
    targetSuffix: '//./checkpoint.json',
    calls: [IN(), OUT('N1', 'done')],
  });
  cases.push({
    name: 'path-normalized-missing-file',
    file: 'checkpoint.json',
    checkpoint: null,
    targetSuffix: '//./nope.json',
    calls: [IN()],
  });
  cases.push({
    name: 'filename-with-no-suffix',
    file: 'cp',
    checkpoint: b64(raw(baseDocument())),
    calls: [OUT('N1', 'done')],
  });
  cases.push({
    name: 'filename-with-two-dots',
    file: 'cp.a.json',
    checkpoint: b64(raw(baseDocument())),
    calls: [OUT('N1', 'done')],
  });
  cases.push({
    name: 'filename-non-ascii',
    file: 'จุดตรวจ—1.json',
    checkpoint: b64(raw(baseDocument())),
    calls: [OUT('N1', 'done')],
  });
  cases.push({
    name: 'filename-non-ascii-missing',
    file: 'จุดตรวจ—2.json',
    checkpoint: null,
    calls: [IN()],
  });

  // ---- write failure AFTER the log line landed. The directory goes read-only between two
  // clock-outs, so the append to the EXISTING log still succeeds (file permission) and the
  // temp-file create does not (directory permission). That is the only arm that reaches
  // `checkpoint unwritable, last log line uncommitted`.
  cases.push({
    name: 'readonly-directory-after-the-log-line',
    file: 'checkpoint.json',
    checkpoint: b64(raw(baseDocument())),
    calls: [
      OUT('N1', 'done'),
      { fn: 'chmod', path: '', mode: 0o555 },
      OUT('N2', 'done', { now: 1755930100 }),
      { fn: 'chmod', path: '', mode: 0o755 },
      IN(),
    ],
  });
  // The ONLY thing that makes the temp file's NAME observable. `path.with_suffix(
  // path.suffix + ".tmp")` is `checkpoint.json.tmp`, not `checkpoint.tmp`; on every other
  // path the temp file is renamed on success and unlinked on failure, so its name never
  // reaches a caller. With a DIRECTORY planted there the write fails EISDIR and the name is
  // in the sentence — and the `contextlib.suppress(OSError)` around the cleanup unlink is
  // exercised too, since unlinking a directory fails.
  cases.push({
    name: 'temp-file-name-is-observable-when-a-directory-is-in-the-way',
    file: 'checkpoint.json',
    checkpoint: b64(raw(baseDocument())),
    calls: [{ fn: 'mkdir', path: 'checkpoint.json.tmp' }, OUT('N1', 'done'), IN()],
  });
  cases.push({
    name: 'temp-file-name-two-dots',
    file: 'cp.a.json',
    checkpoint: b64(raw(baseDocument())),
    calls: [{ fn: 'mkdir', path: 'cp.a.json.tmp' }, OUT('N1', 'done')],
  });
  cases.push({
    name: 'temp-file-name-no-suffix',
    file: 'cp',
    checkpoint: b64(raw(baseDocument())),
    calls: [{ fn: 'mkdir', path: 'cp.tmp' }, OUT('N1', 'done')],
  });

  // `PurePath('.json').suffix` is '' — a leading dot is not a suffix — so the temp file is
  // `.json.tmp` and not `.json.json.tmp`. Only the planted-directory arm can see the name.
  cases.push({
    name: 'temp-file-name-all-leading-dot',
    file: '.json',
    checkpoint: b64(raw(baseDocument())),
    calls: [{ fn: 'mkdir', path: '.json.tmp' }, OUT('N1', 'done')],
  });
  cases.push({
    name: 'temp-file-name-trailing-dot',
    file: 'cp.',
    checkpoint: b64(raw(baseDocument())),
    calls: [{ fn: 'mkdir', path: 'cp..tmp' }, OUT('N1', 'done')],
  });

  // And the arm where the log itself cannot be created: a fresh read-only directory.
  cases.push({
    name: 'readonly-directory-before-the-log-line',
    file: 'checkpoint.json',
    checkpoint: b64(raw(baseDocument())),
    calls: [
      { fn: 'chmod', path: '', mode: 0o555 },
      OUT('N1', 'done'),
      { fn: 'chmod', path: '', mode: 0o755 },
      IN(),
    ],
  });

  // ------------------------------------------------- AS-2: `job.roles`, the model check
  //
  // BEFORE THIS BLOCK, NO GATE IN THIS REPOSITORY REACHED THE FEATURE AT ALL. The corpus
  // above is built on `baseDocument()` and on the tracked template, and NEITHER declares
  // `job.roles` — deliberately, since the whole point of the template is that a checkpoint
  // written before AS-2 keeps working. So `--suite shiftwork` passed THROUGH J46-8's and
  // J46-9's change without once executing it, exactly as `--suite validate` had passed
  // through J46-7's and `pytest` through J46-4's. The sessions below are what make the two
  // refusals reachable, and the per-side block after the loop is what makes them decidable:
  // a differential compares Node to Python and stays green through a sentence changed on
  // both sides, which is the failure mode this repository has now been bitten by three times.
  //
  // The two roles get DIFFERENT lists on purpose, so a per-role lookup is distinguishable
  // from one that reads whichever entry it finds first, and N1 (implementer) is the cursor
  // while N2 is the reviewer.
  for (const [name, doc, calls] of rolesSessions()) cases.push({ name, file: 'checkpoint.json', checkpoint: doc, calls });
  for (const [name, doc, calls] of packSessions()) {
    cases.push({ name, file: 'checkpoint.json', checkpoint: doc, calls, assets: packDir });
  }
  for (const [name, doc, calls] of anyPackSessions()) {
    cases.push({ name, file: 'checkpoint.json', checkpoint: doc, calls, assets: anyPackDir });
  }

  // ------------------------------------------- job50/F5 (J50-10): the accounting line's shape
  //
  // The gate is reached by nothing above on purpose: every session there either offers a
  // conforming line or is refused by the roles gate first. The sessions here are the ones
  // that REACH the shape check, on `baseDocument()` — no `job.roles`, so the roles gate is
  // silent and the sentence can only be this one. `OUT` alone is a null line and is never
  // validated, so a refusal here writes nothing and the next call sees the same file.
  for (const [name, doc, calls] of accountingSessions()) cases.push({ name, file: 'checkpoint.json', checkpoint: doc, calls });
  // And the packs that cannot supply the shape at all (J50-9A/9B), one session per shape.
  for (const [label, dir] of brokenPacks) {
    for (const [name, doc, calls] of unreadableShapeSessions(label)) {
      cases.push({ name, file: 'checkpoint.json', checkpoint: doc, calls, assets: dir });
    }
  }

  // ------------------------------------------- job50/F6 (J50-13): `briefed`, measured off the ledger
  //
  // Nothing above was written to reach this: `sequence-to-success` happens to clock in and
  // out, but under a name that promises the cursor's walk, and no session above clocks a
  // unit out WITHOUT a clock-in on purpose — which is the case F6 exists for. Every session
  // here is on `baseDocument()` (no `job.roles`), so the roles gate is silent and the only
  // thing the ledger can differ by is this feature.
  for (const [name, doc, calls] of briefedSessions()) cases.push({ name, file: 'checkpoint.json', checkpoint: doc, calls });

  // ------------------------------------------- job60 (J60-4): `clock_in(unit_id)`, D2 and D3
  //
  // Nothing above reaches this either, and for a reason worth stating: every checkpoint in this
  // file declares its units in dependency order, so `plan.cursor` and `ready[0]` agree in all of
  // them and the new argument can only be handed the unit the old code would have picked. A
  // feature that is unobservable on the whole existing corpus needs its own documents — see
  // `unitIdSessions`.
  for (const [name, doc, calls] of unitIdSessions()) cases.push({ name, file: 'checkpoint.json', checkpoint: doc, calls });

  return cases;
}

/**
 * `[name, checkpoint, calls]` triples for job50/F6, one per ruling J50-11 fixed.
 *
 * `blocked` is NOT terminal, so a `blocked` clock-out leaves the cursor on N1 and the same
 * unit can be clocked out again — that is the shape every consume case below needs, and it
 * is also how the brief line's timestamp is made DETERMINISTIC: the reference stamps a
 * brief with the harness's process-global clock, which holds whatever the LAST `clock_out`
 * set, across sessions. A session that clocks out first pins the clock before it clocks
 * in, so the brief line's exact bytes can be a literal in the per-side block.
 */
function briefedSessions() {
  const LINE = (text) => ({ accounting: b64(text) });
  const base = () => b64(raw(baseDocument()));
  const LATER = { now: 1755930061 };
  const N2 = (over = {}) => OUT('N2', 'done', { ...LATER, history_entry: b64('{"unit": "N2", "outcome": "done"}'), ...over });
  return [
    // ---- 1. the plain pair: a brief, then the clock-out that consumes it. `accounting: null`
    // on purpose — the flag is the runtime's field and lands on a null line too.
    ['briefed/in-then-out', base(), [IN(), OUT('N1', 'done'), IN()]],
    // ---- 2. THE CASE: no clock_in at all. The clock-out SUCCEEDS, the line says `false`,
    // the cursor moves. Once with a conforming line, once with a null one.
    ['briefed/out-without-in', base(), [OUT('N1', 'done', { accounting: CONFORMING }), IN(), ST()]],
    ['briefed/out-without-in-null-line', base(), [OUT('N1', 'done'), IN()]],
    // ---- 3. clocked in twice: TWO brief lines. The ledger records events, not state.
    ['briefed/clocked-in-twice', base(), [IN(), IN(), OUT('N1', 'done')]],
    // ---- 4. THE CONSUME RULE. brief -> blocked -> re-run with no clock_in reads `false`.
    ['briefed/consumed-by-a-clock-out', base(), [IN(), OUT('N1', 'blocked'), OUT('N1', 'done', LATER)]],
    // ---- 5. and its other half: brief -> blocked -> clock_in -> done reads `true` twice.
    ['briefed/re-briefed-after-blocked', base(), [IN(), OUT('N1', 'blocked'), IN(), OUT('N1', 'done', LATER)]],
    // ---- 6. the brief line's exact bytes. The blocked clock-out pins the clock at
    // 1755930000 first, so the brief that follows carries a stamp both sides must spell.
    ['briefed/brief-line-shape', base(), [OUT('N1', 'blocked'), IN(), OUT('N1', 'done', LATER)]],
    // ---- 7. the flag is PER UNIT: N1's brief does not count for N2.
    ['briefed/brief-is-per-unit', base(), [IN(), OUT('N1', 'done'), N2()]],
    // ---- 8. a self-reported value is OVERWRITTEN by the measured one, in both directions.
    ['briefed/self-report-true-overwritten', base(), [OUT('N1', 'done', LINE('{"tokens": 1, "duration_ms": 1, "briefed": true}'))]],
    ['briefed/self-report-false-overwritten', base(), [IN(), OUT('N1', 'done', LINE('{"tokens": 1, "duration_ms": 1, "briefed": false}'))]],
    // ---- 9. an unwritable ledger: clock_in still returns the brief, and the record is the
    // only cost — so the clock-out that follows reads `false`, since nothing was recorded.
    ['briefed/clock-in-on-an-unwritable-log', base(), [
      { fn: 'chmod', path: '', mode: 0o555 },
      IN(),
      { fn: 'chmod', path: '', mode: 0o755 },
      OUT('N1', 'done'),
    ]],
  ];
}

/** A line the shipped shape accepts: the two required keys, the model, and the cache figure. */
const CONFORMING = b64('{"tokens": 110623, "duration_ms": 745045, "model": "claude-sonnet-5", "cache_read_tokens": 9876543}');

/** One unit of a `plan.units` list, spelled once so a graph below is only its ids and edges. */
const unit = (id, dependsOn, over = {}) => ({
  id,
  title: `unit ${id} — with a dash`,
  brief_path: `briefs/${id}.md`,
  status: 'todo',
  role: 'implementer',
  depends_on: dependsOn,
  verify: 'npm test',
  ...over,
});

/**
 * job60 shape 2: `[A, C(depends_on B), B]` — plan order and graph order are DIFFERENT orders.
 *
 * The whole point of this document is that no other one in this file has it. Every checkpoint
 * above declares its units in an order the graph agrees with, so `plan.cursor` and the batch
 * view's `ready[0]` name the same unit in all of them and no case could ever have compared the
 * two fields. Here they come apart: with `A` satisfied the only runnable unit is `B`, while the
 * pointer a pre-job60 `clock_out` advanced in `plan.units` order lands on `C`, whose dependency
 * has not run.
 */
const shape2 = (cursor, aStatus) => baseDocument({
  plan: {
    cursor,
    units: [
      unit('A', [], { status: aStatus }),
      unit('C', ['B'], { role: 'reviewer' }),
      unit('B', []),
    ],
  },
});

/** job60 shape 1: two independent units and one that joins them — a ready batch of WIDTH 2. */
const waveDocument = () => baseDocument({
  plan: {
    cursor: 'N1',
    units: [unit('N1', []), unit('N2', [], { role: 'reviewer' }), unit('N3', ['N1', 'N2'], { role: 'planner' })],
  },
});

/**
 * `[name, checkpoint, calls]` triples for job60 — `clock_in(unit_id)`, D2 and D3.
 *
 * WHY THESE DOCUMENTS AND NOT THE ONES ABOVE. `baseDocument()` and the shipped codefix
 * template are both LINEAR chains whose units are declared in dependency order, so on either
 * of them `plan.cursor == ready[0]` at every step and `clock_in(unit_id)` can only ever be
 * handed the unit `clock_in()` would have picked anyway. That is precisely the corpus gap the
 * spec names: the feature is unobservable on every checkpoint this suite already carried, so
 * it needs documents whose two orders disagree. The template is still driven below — as the
 * case that must NOT move.
 */
function unitIdSessions() {
  const LATER = { now: 1755930061 };
  const N2OUT = (over = {}) => OUT('N2', 'done', { history_entry: b64('{"unit": "N2", "outcome": "done"}'), ...over });
  return [
    // ---- 1a. THE CASE WHOSE ABSENCE HID THE BUG. The pointer is already on `C` — the state a
    // pre-job60 `clock_out A` left on disk — and the graph says `B`. Both surfaces are asked,
    // against the same bytes at the same instant: `clock_in()` hands out `C`'s brief exactly as
    // it always did, and `clock_in('C')` refuses it by name. Then `B`, the unit that is ready,
    // and finally `status`, because D1 says a wave of briefs never moves the cursor.
    ['unit-id/cursor-disagrees-with-ready', b64(raw(shape2('C', 'done'))), [IN(), IN('C'), IN('B'), ST()]],
    // ---- 1b. and the repair, on the SAME graph driven from the top: D3 advances to `ready[0]`,
    // so the pointer lands on `B` and not on the `C` that plan order would have chosen.
    ['unit-id/advance-follows-the-graph', b64(raw(shape2('A', 'todo'))), [OUT('A', 'done'), ST(), IN()]],

    // ---- 2. A WAVE. Width 2, both briefed against one cursor, and `N2` clocked out FIRST —
    // which is the move D2 exists for and which the pre-job60 runtime refused. Then the cursor
    // value after each, and the brief for `N3` once both its dependencies are satisfied.
    ['unit-id/wave', b64(raw(waveDocument())), [IN(), IN('N2'), N2OUT(), OUT('N1', 'done', LATER), ST(), IN()]],

    // ---- 3. the not-ready refusal: a unit whose dependencies have not run, and — the limiting
    // case of the same property, not a second sentence — a `unit_id` that names no unit at all.
    // `status` last, because a refusal writes nothing and the pointer must still be `N1`.
    ['unit-id/not-ready-refusal', b64(raw(waveDocument())), [IN('N3'), IN('nope'), ST()]],

    // ---- 4. D2 DID NOT BECOME PERMISSIVE. `N2` is ready and could have been briefed, but this
    // session never briefs it, so the clock-out is refused with the sentence it has always had.
    // Read against case 2, where the same call on the same document succeeds: the brief is the
    // only difference between them, which is exactly what D2 says the rule is.
    ['unit-id/never-briefed-clock-out-still-refuses', b64(raw(waveDocument())), [N2OUT(), ST()]],

    // ---- 5. THE DEFAULT PATH, on the shipped codefix template — a linear chain where
    // `cursor == ready[0]`, so naming the unit and naming nothing must answer the same thing.
    // This is the case that pins "a caller that never passes `unit_id` sees byte-identical
    // behaviour", and it is also the control for cases 1a and 3: the refusal there is a
    // property of the graph, not something `unit_id` does to every checkpoint it touches.
    ['unit-id/default-path-on-the-template', b64(realCheckpointText), [IN(), IN(CURSOR), ST()]],
  ];
}

/**
 * `[name, checkpoint, calls]` triples for the shape check, the pack being the SHIPPED one.
 *
 * WHERE THE TWO SIDES COULD DISAGREE, which is what each refusal below was picked for. The
 * sentence's frame is a copied string and a differential cannot see a copy; what the two
 * runtimes compute SEPARATELY is the `{problem}` inside it — `jsonschema`'s `best_match` on
 * one side and the port's on the other — so the refusals vary exactly that: which of two
 * missing keys is named (`{}`), whether a required-key error outranks a `minimum` on another
 * key, which of two wrongly-typed keys is named first, and the `repr()` of the offending value
 * (`True`, `None`, `'1234'`, `['x']`, `{'a': None, 'b': 1.5}`, a Thai string) — the spellings a
 * port reaching for JSON's `true`/`null`/`"1234"` would get wrong. The accept side varies the
 * two integer readings the port carries as rules: a whole float and an unbounded integer.
 */
function accountingSessions() {
  const LINE = (text) => ({ accounting: b64(text) });
  const base = () => b64(raw(baseDocument()));
  return [
    // ---- the refusal the roles sessions used to hide: a real-looking line short one key
    ['accounting/refuse-missing-duration-ms', base(), [OUT('N1', 'done', LINE('{"tokens": 7, "model": "claude-sonnet-5"}')), IN(), ST()]],
    // ---- `best_match`: a missing required key outranks a `minimum` violation elsewhere
    ['accounting/refuse-missing-tokens-outranks-a-negative-tool-uses', base(), [OUT('N1', 'done', LINE('{"duration_ms": 1, "tool_uses": -3}')), IN()]],
    // ---- two keys missing: ONE is named, and which one is the `required` list's order
    ['accounting/refuse-empty-object', base(), [OUT('N1', 'done', LINE('{}')), IN()]],
    // ---- two keys wrong: ONE is named, and which one is the properties' order
    ['accounting/refuse-two-wrong-types', base(), [OUT('N1', 'done', LINE('{"tokens": "a", "duration_ms": "b"}')), IN()]],
    // ---- the `repr()` of the offending value, one refusal per spelling, all on one file
    ['accounting/refuse-wrong-types', base(), [
      OUT('N1', 'done', LINE('{"tokens": 12.5, "duration_ms": 1}')),
      OUT('N1', 'done', LINE('{"tokens": true, "duration_ms": 1}')),
      OUT('N1', 'done', LINE('{"tokens": "1234", "duration_ms": 1}')),
      OUT('N1', 'done', LINE('{"tokens": null, "duration_ms": 1}')),
      OUT('N1', 'done', LINE('{"tokens": [], "duration_ms": 1}')),
      OUT('N1', 'done', LINE('{"tokens": {"a": null, "b": 1.5}, "duration_ms": 1}')),
      OUT('N1', 'done', LINE('{"tokens": "\\u0e01\\u2014", "duration_ms": 1}')),
      OUT('N1', 'done', LINE('{"tokens": -1, "duration_ms": 1}')),
      OUT('N1', 'done', LINE('{"tokens": 1, "duration_ms": 1, "cache_read_tokens": -5}')),
      OUT('N1', 'done', LINE('{"tokens": 1, "duration_ms": 1, "note": ["x"]}')),
      OUT('N1', 'done', LINE('{"tokens": 1, "duration_ms": 1, "model": 5}')),
      IN(),
    ]],
    // ---- ORDER: the roles gate first (a conforming line, wrong model), then the shape
    // (a model ON the list, `duration_ms` missing) — same document, two sentences.
    ['accounting/order-roles-gate-then-shape', withRoles(), [
      OUT('N1', 'done', LINE('{"tokens": 1, "duration_ms": 1, "model": "haiku"}')),
      OUT('N1', 'done', LINE('{"tokens": 1, "model": "claude-sonnet-5"}')),
      IN(),
    ]],
    // ---- the ACCEPT side: the full line, then the two integer readings, then odd keys
    ['accounting/accept-full-line', base(), [OUT('N1', 'done', { accounting: CONFORMING }), IN(), ST()]],
    ['accounting/accept-whole-floats-are-integers', base(), [OUT('N1', 'done', LINE('{"tokens": 1e16, "duration_ms": -0.0}'))]],
    ['accounting/accept-unbounded-integer', base(), [OUT('N1', 'done', LINE('{"tokens": 12345678901234567890123, "duration_ms": 1234.0}'))]],
    ['accounting/accept-odd-keys-pass', base(), [OUT('N1', 'done', LINE('{"tokens": 1, "duration_ms": 1, "duration": "88.2s", "\\u0e01": "\\u2014"}'))]],
    // ---- the boundary: a null line is not an audit record and is never validated
    ['accounting/null-line-is-not-validated', base(), [OUT('N1', 'done'), IN()]],
  ];
}

/**
 * `[name, checkpoint, calls]` triples for ONE broken pack: a conforming line is refused,
 * the cursor has not moved, and then a NULL line clocks the same unit out under the same
 * pack — `accounting: null` never reads the asset, and that boundary is the half a
 * fail-closed gate can get wrong in the other direction (refusing everything). Plus the
 * order, driven on the same pack: the roles gate still speaks first.
 */
function unreadableShapeSessions(label) {
  const LINE = (text) => ({ accounting: b64(text) });
  return [
    [`shape-unreadable/${label}`, b64(raw(baseDocument())), [
      OUT('N1', 'done', { accounting: CONFORMING }),
      IN(),
      OUT('N1', 'done'),
      ST(),
    ]],
    [`shape-unreadable/${label}/roles-gate-first`, withRoles(), [
      OUT('N1', 'done', LINE('{"tokens": 1, "duration_ms": 1, "model": "haiku"}')),
      OUT('N1', 'done', LINE('{"tokens": 1, "duration_ms": 1, "model": "claude-sonnet-5"}')),
    ]],
  ];
}

/** The allowed-model map these sessions declare. Non-alphabetical, and that is the point. */
const ROLES = { implementer: ['claude-sonnet-5', 'claude-opus-5'], reviewer: ['claude-opus-5'] };
/**
 * `haiku` is on nobody's list; the other two fields are what a real accounting line carries —
 * and since job50/F5 they are the two the shape REQUIRES, so a session that expects this line
 * to clock out (`no-map-at-all`, `absent-role`) cannot carry `duration` where `duration_ms`
 * is the key. J50-10 renamed it: with `duration: 88.2` every one of those sessions had been
 * refused for a missing `duration_ms` on both sides, and the `bit(..., 'ok')` rows below
 * could not be built at all.
 */
const WRONG = b64('{"tokens": 1234, "duration_ms": 88200, "model": "haiku"}');

function withRoles(roles = ROLES) {
  const document = baseDocument();
  document.job.roles = roles;
  return b64(raw(document));
}

/**
 * `[name, checkpoint, calls]` triples. `assetsPack` is filled in by `run` for the two cases
 * that need a schema without `minItems` — see `PACK_NOTE`.
 */
function rolesSessions() {
  const ACC = (text) => ({ accounting: b64(text) });
  return [
    // ---- the refusal, and the four spellings of "no model at all"
    ['roles/refuse-wrong-model', withRoles(), [OUT('N1', 'done', ACC('{"tokens": 1234, "duration_ms": 88200, "model": "haiku"}')), IN(), ST()]],
    ['roles/refuse-no-model-key', withRoles(), [OUT('N1', 'done', ACC('{"tokens": 1234}')), IN()]],
    ['roles/refuse-accounting-null', withRoles(), [OUT('N1', 'done'), IN()]],
    ['roles/refuse-accounting-empty', withRoles(), [OUT('N1', 'done', ACC('{}')), IN()]],
    ['roles/refuse-model-null', withRoles(), [OUT('N1', 'done', ACC('{"model": null}')), IN()]],
    // ---- the allowed path, and that the log line keeps the model
    ['roles/allowed-model-clocks-out', withRoles(), [OUT('N1', 'done', ACC('{"tokens": 7, "duration_ms": 1, "model": "claude-sonnet-5"}')), IN(), ST()]],
    // ---- the list consulted is the UNIT's role. N1 closes on opus (which the reviewer also
    // allows), then N2 offers sonnet, which ONLY the implementer allows.
    ['roles/per-role-not-the-first-entry', withRoles(), [
      OUT('N1', 'done', ACC('{"tokens": 1, "duration_ms": 1, "model": "claude-opus-5"}')),
      OUT('N2', 'done', { now: 1755930061, history_entry: b64('{"unit": "N2", "outcome": "done"}'), ...ACC('{"model": "claude-sonnet-5"}') }),
      IN(),
    ]],
    // ---- exact compare. The standing ruling, pinned as a REFUSAL on both sides so that any
    // future normalisation, prefix match or strip-the-brackets rule turns this red.
    ['roles/exact-compare-1m-suffix', withRoles(), [OUT('N1', 'done', ACC('{"model": "claude-opus-5[1m]"}')), IN()]],
    ['roles/exact-compare-case-shift', withRoles(), [OUT('N1', 'done', ACC('{"model": "Claude-Opus-5"}'))]],
    // ---- CHECKPOINT ORDER, not `sorted()`. A map already in alphabetical order cannot state
    // this property, which is exactly why runtime-py's own fixture could not fail.
    ['roles/checkpoint-order-not-sorted', withRoles({ implementer: ['zzz-last', 'aaa-first'] }), [OUT('N1', 'done', { accounting: WRONG })]],
    // ---- `accounting` has no schema, so `model` is whatever the orchestrator sent. Python
    // interpolates with `str()`; a port reaching for the tagged `.v` would print `5` for a
    // float, `true` for a bool and `[object Object]` for a list. Four refusals in one
    // session, because a refusal writes nothing and so leaves the next one the same file.
    ['roles/non-string-models', withRoles(), [
      OUT('N1', 'done', ACC('{"model": 5}')),
      OUT('N1', 'done', ACC('{"model": 5.0}')),
      OUT('N1', 'done', ACC('{"model": true}')),
      OUT('N1', 'done', ACC('{"model": ["a", "b"]}')),
      OUT('N1', 'done', ACC('{"model": {"name": "x"}}')),
      IN(),
    ]],
    // ---- the sentence itself goes through `ensure_ascii` on the way back to the caller, so
    // a non-ASCII model name and a non-ASCII allowed list are a serializer case as well.
    ['roles/non-ascii-model-and-list', withRoles({ implementer: ['รุ่น—ก', 'claude-opus-5'] }), [
      OUT('N1', 'done', ACC('{"tokens": 1, "duration_ms": 1, "model": "\\u0e23\\u0e38\\u0e48\\u0e19\\u2014\\u0e02"}')),
      OUT('N1', 'done', ACC('{"tokens": 1, "duration_ms": 1, "model": "\\u0e23\\u0e38\\u0e48\\u0e19\\u2014\\u0e01"}')),
    ]],
    // ---- BACKWARDS COMPATIBILITY, the case an existing user's checkpoint depends on. The
    // model offered is `haiku`, which no list anywhere would allow.
    ['roles/no-map-at-all-is-unchanged', b64(raw(baseDocument())), [OUT('N1', 'done', { accounting: WRONG }), IN(), ST()]],
    ['roles/absent-role-is-unconstrained', withRoles({ reviewer: ['claude-opus-5'] }), [OUT('N1', 'done', { accounting: WRONG }), IN()]],
    // ---- an EMPTY list and an ABSENT role are DIFFERENT INPUTS. Under the shipped schema
    // the empty one never reaches the check: `minItems: 1` refuses the whole document.
    ['roles/empty-list-refused-by-the-schema', withRoles({ implementer: [] }), [OUT('N1', 'done', { accounting: WRONG }), IN()]],
    // ---- and the check does not fire on the read side.
    ['roles/clock-in-and-status-are-untouched', withRoles(), [IN(), ST()]],
  ];
}

/**
 * The two sessions that run against a schema WITHOUT `minItems: 1`, and why they exist.
 *
 * J46-10's ruling: the model check FAILS CLOSED on an empty allowed list. `if not allowed`
 * read `roles: {implementer: []}` as unconstrained, which turns a typo into a silent opt-out
 * of the rule the checkpoint just declared. The shipped schema refuses that document during
 * the read, so the branch is unreachable — and the schema is a SHARED asset, the class this
 * job has measured three times as invisible to a differential. A check whose safety rests on
 * another layer's keyword fails open the day that keyword moves, so the branch is given a
 * reading on purpose and then MEASURED by taking the keyword away.
 *
 * `BANTAMKIT_ASSETS` is the same override in both runtimes, so one instrument reaches both
 * sides. The pair is deliberate: the `absent` arm proves the pack did not simply break every
 * clock-out, which is the only other way this could have come back green.
 */
function packSessions() {
  return [
    ['roles/pack/empty-list-fails-closed', withRoles({ implementer: [] }), [
      OUT('N1', 'done', { accounting: WRONG }),
      OUT('N1', 'done', { accounting: b64('{"tokens": 1}') }),
      IN(),
    ]],
    ['roles/pack/absent-role-still-unconstrained', withRoles({ reviewer: ['claude-opus-5'] }), [
      OUT('N1', 'done', { accounting: WRONG }),
      IN(),
    ]],
  ];
}

/**
 * The eight values a `job.roles.<role>` can hold once the schema stops saying `array`, and
 * why all eight are here rather than the three the unit brief names as a minimum (J47-6).
 *
 * SEVEN ARE UNREADABLE AND ONE IS NOT, and the whole point of the set is the boundary between
 * them. Measured before the fix, the seven failed in THREE different ways and in ways the two
 * runtimes did not share: the reference iterated a string's CHARACTERS and a dict's KEYS and
 * refused while quoting the checkpoint back at its author as `c, l, a, u, d, e, …`, raised an
 * uncaught `TypeError` on a number, a null, a bool and `[5]`, and the port answered
 * `unconstrained` for the first five — completing the clock-out, status set, cursor advanced,
 * accounting line written — while rendering `5` and `ok, None` into the sentence for the last
 * two. So a set that stops at "an int, a string and a null" omits the two LIST shapes, which
 * are the ones where a bare kind test passes and the property (a list OF STRINGS) is what
 * actually decides, and they are the half neither the roadmap register nor the prep probe
 * predicted.
 *
 * THE EIGHTH IS `[]` AND IT MUST NOT MOVE. An empty list IS a list of model identifiers, so
 * it keeps J46-10's `… does not allow: ` with its trailing empty `names` — not J47-4's
 * sentence. That line is the one a later edit would slide across (`if (!allowed.v.length)`
 * folded into the same arm reads as a tidy-up and is a regression of a ruling), and it is
 * driven here under `additionalProperties: true` as well as under the no-`minItems` pack so
 * that what separates the two sentences is demonstrably the CODE and not the schema.
 *
 * Each shape is clocked out TWICE — once offering `haiku`, once offering no model at all —
 * because "one sentence for both accounting shapes" is a deliberate choice on both sides:
 * which model was reported cannot matter when the declaration that would judge it is
 * unreadable. Then `clock_in`, so the cursor can be shown never to have moved.
 */
const UNREADABLE_ROLES = [
  ['str', 'claude-opus-5'],
  ['dict', { a: 'claude-opus-5' }],
  ['int', 5],
  ['null', null],
  ['bool', true],
  ['list-of-int', [5]],
  ['list-with-a-non-string', ['ok', null]],
];

function anyPackSessions() {
  const drive = (accounting) => OUT('N1', 'done', { accounting });
  const calls = [drive(WRONG), drive(b64('{"tokens": 1}')), IN()];
  const cases = UNREADABLE_ROLES.map(([label, value]) => [
    `roles/any/unreadable/${label}`,
    withRoles({ implementer: value }),
    calls,
  ]);
  // The boundary, on the same instrument as the seven above it.
  cases.push(['roles/any/empty-list-is-still-a-list', withRoles({ implementer: [] }), calls]);
  // And the companion that keeps this pack honest, the same way `roles/pack/absent-role-…`
  // keeps the other one honest: the pack did not simply break every clock-out.
  cases.push(['roles/any/absent-role-still-unconstrained', withRoles({ reviewer: ['claude-opus-5'] }), [
    drive(WRONG),
    IN(),
  ]]);
  return cases;
}

// ================================================================================== node

/**
 * The Node side of one session — the same loop the reference script runs.
 *
 * platform-checked: the `chmod` step below is a CALL IN THE SHARED SCRIPT, not a fixture this
 * side builds. `caseSpec.calls` is one list; `shiftwork_ref.py` walks it and answers
 * `os.chmod(...)` for the same entry (`ref/shiftwork_ref.py`, `if fn == "chmod"`). So a
 * platform that ignores the mode makes the write SUCCEED on both sides, both sessions record
 * the same step, and the comparison stays symmetric. Same caveat as the `applyModes` helpers
 * in `store.mjs` / `memorycli.mjs` / `recall-strings.mjs`, and same honest limit: that the
 * case then proves less is asserted, that it still passes is not measured on Windows.
 */
async function runNodeSession(shiftwork, pyjson, caseSpec, dir, clock) {
  const { dumpJson, parseJson } = pyjson;
  mkdirSync(dir, { recursive: true });
  const path = join(dir, caseSpec.file);
  if (caseSpec.checkpoint !== null && caseSpec.checkpoint !== undefined) {
    writeFileSync(path, unb64bytes(caseSpec.checkpoint));
  }
  const target = caseSpec.targetSuffix ? dir + caseSpec.targetSuffix : path;
  // `BANTAMKIT_ASSETS` for this session only, put back afterwards — the same override the
  // reference applies to `os.environ` around its own loop. `assetsRoot()` reads the variable
  // on every call, so setting it here reaches the `loadSchema` inside `clockOut`.
  const previousAssets = process.env.BANTAMKIT_ASSETS;
  if (caseSpec.assets) process.env.BANTAMKIT_ASSETS = caseSpec.assets;
  const steps = [];
  const snapshot = (result) => ({
    result: b64(result),
    checkpoint: existsSync(path) ? b64bytes(readFileSync(path)) : null,
    log: existsSync(`${path}.log.jsonl`) ? b64bytes(readFileSync(`${path}.log.jsonl`)) : null,
    tmp_left: existsSync(`${path}.tmp`),
  });
  for (const call of caseSpec.calls) {
    if (call.fn === 'chmod') {
      chmodSync(call.path ? join(dir, call.path) : dir, call.mode);
      steps.push({ result: b64('null'), checkpoint: null, log: null, tmp_left: false });
      continue;
    }
    if (call.fn === 'mkdir') {
      mkdirSync(join(dir, call.path), { recursive: true });
      steps.push({ result: b64('null'), checkpoint: null, log: null, tmp_left: false });
      continue;
    }
    let answer;
    // job60/D1: `unitId` is the SECOND positional argument on both sides now
    // (`clockIn(checkpoint, unitId, options)` against `clock_in(checkpoint, unit_id)`), so a
    // call that names no unit must pass an explicit `null` and let the options object keep
    // the third slot. Before this line was widened the options object sat in the unit slot
    // and every clock-in in the suite asked for a unit named `[object Object]`.
    if (call.fn === 'clock_in') answer = shiftwork.clockIn(target, call.unit_id ?? null, { now: clock.now });
    else if (call.fn === 'status') answer = shiftwork.status(target);
    else {
      clock.now = call.now;
      answer = shiftwork.clockOut(
        target,
        call.unit,
        call.status,
        call.handoff_patch === null || call.handoff_patch === undefined ? null : parseJson(unb64(call.handoff_patch)),
        call.history_entry === null || call.history_entry === undefined ? null : parseJson(unb64(call.history_entry)),
        call.accounting === null || call.accounting === undefined ? null : parseJson(unb64(call.accounting)),
        { now: call.now },
      );
    }
    steps.push(snapshot(dumpJson(answer)));
  }
  if (caseSpec.assets) {
    if (previousAssets === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = previousAssets;
  }
  return { steps };
}

/**
 * A pack whose checkpoint schema has lost `minItems: 1` on the roles list, and nothing else.
 *
 * Built from the SHIPPED schema so it cannot drift from it, and written outside the session
 * directories, which the harness deletes between the Python run and the Node one.
 */
function writeSchemaPackWithoutMinItems(scratch) {
  const schema = JSON.parse(readFileSync(join(repoRoot, 'assets', 'schemas', 'shiftwork-checkpoint.json'), 'utf8'));
  delete schema.properties.job.properties.roles.additionalProperties.minItems;
  const pack = join(scratch, 'roles-pack');
  mkdirSync(join(pack, 'schemas'), { recursive: true });
  writeFileSync(join(pack, 'schemas', 'shiftwork-checkpoint.json'), JSON.stringify(schema), 'utf8');
  return withShippedTools(pack);
}

/**
 * Since job50/F5 `clock_out` reads the `shiftwork_clock_out` TOOL asset for the accounting
 * line's shape, so a pack that mutates only the checkpoint schema must still carry the
 * shipped `tools/` — or every clock-out that survives the roles gate is refused with
 * `ACCOUNTING_SHAPE_UNREADABLE` (J50-9A/9B) instead of reaching the thing the pack exists to
 * measure. Both runtimes' own test helpers do this (`_with_shipped_tools`, `withShippedTools`);
 * this is the same copy. The broken packs below are built the other way round on purpose.
 */
function withShippedTools(pack) {
  cpSync(join(repoRoot, 'assets', 'tools'), join(pack, 'tools'), { recursive: true });
  return pack;
}

/**
 * A pack whose roles VALUE has lost its shape entirely — `additionalProperties: true` — and
 * nothing else. The keys are still the role enum; only what a key may hold is unconstrained.
 *
 * J47-4's ruling is J46-10's one step further out: a role the map NAMES is constrained by
 * what it names, and a value that is not a list of model identifiers names nothing, so it
 * allows nothing. Reaching that branch needs strictly more than the pack above — `[]` is the
 * only value `type: "array"` lets through while `minItems` is gone, and the seven shapes this
 * arm exists for are all refused by `type` before any code sees them. Hence a SECOND pack
 * rather than a looser first one: the J46-10 cases keep the exact instrument they were ruled
 * under, and the empty list is driven through BOTH so the boundary between the two sentences
 * is pinned on a schema that could not be the thing separating them.
 *
 * Written outside the session directories, which the harness deletes between the two runs.
 */
function writeSchemaPackWithAnyRolesValue(scratch) {
  const schema = JSON.parse(readFileSync(join(repoRoot, 'assets', 'schemas', 'shiftwork-checkpoint.json'), 'utf8'));
  schema.properties.job.properties.roles.additionalProperties = true;
  const pack = join(scratch, 'roles-any-pack');
  mkdirSync(join(pack, 'schemas'), { recursive: true });
  writeFileSync(join(pack, 'schemas', 'shiftwork-checkpoint.json'), JSON.stringify(schema), 'utf8');
  return withShippedTools(pack);
}

/**
 * J50-10: the packs that CANNOT supply the accounting shape, `[label, dir]` each.
 *
 * Every one carries the shipped `schemas/` — the checkpoint must read, or the refusal under
 * test is never reached — and breaks the `tools/` side in ONE way. The shapes are chosen
 * OUTSIDE the validator port's documented gap (J50-9B: Node's `checkSchema` is a shape table,
 * not the metaschema, so an object arm with a non-compiling `pattern` or duplicate `required`
 * entries is refused by Python and accepted by Node, and an arm using `$ref` the other way
 * round). None of these six touches the arm's contents: they remove the file, the directory,
 * the parse, the path to the arm, or the arm itself — the cases the two sides fold into one
 * sentence on purpose, so a case here that differed would be this job's, not the port's.
 */
function writeBrokenAccountingPacks(scratch) {
  const shippedSchema = readFileSync(join(repoRoot, 'assets', 'schemas', 'shiftwork-checkpoint.json'));
  const manifest = () => JSON.parse(readFileSync(join(repoRoot, 'assets', 'tools', 'shiftwork_clock_out.json'), 'utf8'));
  const shapes = [
    // the very pack that took the suite down: `schemas/` and nothing else
    ['no-tools-dir', null],
    // a `tools/` directory with every OTHER tool in it
    ['tool-file-missing', (pack) => rmSync(join(pack, 'tools', 'shiftwork_clock_out.json'))],
    ['not-json', (pack) => writeFileSync(join(pack, 'tools', 'shiftwork_clock_out.json'), '{"name": "shiftwork_clock_out",', 'utf8')],
    ['not-utf8', (pack) => writeFileSync(join(pack, 'tools', 'shiftwork_clock_out.json'), Buffer.from([0x7b, 0xff, 0xfe, 0x7d]))],
    ['manifest-is-a-list', (pack) => writeFileSync(join(pack, 'tools', 'shiftwork_clock_out.json'), '[]', 'utf8')],
    ['accounting-without-anyof', (pack) => {
      const m = manifest();
      m.parameters.properties.accounting = { type: 'object', title: 'Accounting' };
      writeFileSync(join(pack, 'tools', 'shiftwork_clock_out.json'), JSON.stringify(m), 'utf8');
    }],
    ['anyof-without-an-object-arm', (pack) => {
      const m = manifest();
      m.parameters.properties.accounting.anyOf = [{ type: 'null' }];
      writeFileSync(join(pack, 'tools', 'shiftwork_clock_out.json'), JSON.stringify(m), 'utf8');
    }],
  ];
  return shapes.map(([label, breakIt]) => {
    const pack = join(scratch, 'broken-accounting', label);
    mkdirSync(join(pack, 'schemas'), { recursive: true });
    writeFileSync(join(pack, 'schemas', 'shiftwork-checkpoint.json'), shippedSchema);
    if (breakIt !== null) {
      withShippedTools(pack);
      breakIt(pack);
    }
    return [label, pack];
  });
}

// =================================================================================== run

export async function run(ctx) {
  const dist = pathToFileURL(join(ctx.runtimeTs, 'dist', '/'));
  const shiftwork = await import(new URL('shiftwork.js', dist));
  const pyjson = await import(new URL('pyjson.js', dist));
  const pyfs = await import(new URL('memory/pyfs.js', dist));
  const { dumpJson, parseJson, fromJs } = pyjson;

  const cases = [];
  const notes = [];

  // ------------------------------------------------------------------------ json.dumps
  const dumpCases = [];
  for (const [label, text] of DUMP_TEXTS) {
    for (const indent of [null, 2]) {
      for (const sort of [false, true]) {
        dumpCases.push({ label: `${label}/indent=${indent}/sort=${sort}`, text: b64(text), indent, sort });
      }
    }
  }
  // The tracked checkpoint template and the shipped schema, through the same four settings.
  for (const [label, text] of [
    ['template-checkpoint', realCheckpointText],
    ['real-schema', readFileSync(join(repoRoot, 'assets', 'schemas', 'shiftwork-checkpoint.json'), 'utf8')],
  ]) {
    for (const indent of [null, 2]) {
      for (const sort of [false, true]) {
        dumpCases.push({ label: `${label}/indent=${indent}/sort=${sort}`, text: b64(text), indent, sort });
      }
    }
  }
  const dumped = ctx.runPython(REF, { op: 'dumps', cases: dumpCases }).results;
  dumpCases.forEach((c, i) => {
    const expected = dumped[i];
    cases.push({
      name: `dumps/${c.label}`,
      kind: 'bytes',
      expected: typeof expected === 'string' ? unb64(expected) : JSON.stringify(expected),
      actual: dumpJson(parseJson(unb64(c.text)), { indent: c.indent, sortKeys: c.sort }),
    });
  });

  // ------------------------------------------------------------------------- timestamp
  const stamps = ctx.runPython(REF, { op: 'timestamp', values: TIMESTAMPS }).stamps;
  TIMESTAMPS.forEach((v, i) => {
    cases.push({ name: `timestamp/${v}`, kind: 'bytes', expected: stamps[i], actual: shiftwork.timestamp(v) });
  });

  // -------------------------------------------------------------- os.replace's filename2
  //
  // `OSError.__str__` prints BOTH names when `filename2` is set, and `os.replace` is the
  // only call shiftwork makes that sets it. No session can stage that failure — the rename
  // happens microseconds after a successful write into the same directory — so the sentence
  // is measured head-on rather than left to a branch nothing has ever run.
  {
    const dir = join(ctx.scratch, 'osreplace');
    const replaceCases = [
      { src: join(dir, 'a.tmp'), dst: join(dir, 'missing', 'b.json'), create: true },
      { src: join(dir, 'gone.tmp'), dst: join(dir, 'b.json'), create: false },
      { src: join(dir, 'th—.tmp'), dst: join(dir, 'ไม่มี', 'b.json'), create: true },
    ];
    const answers = ctx.runPython(REF, { op: 'os_replace', cases: replaceCases }).results;
    rmSync(dir, { recursive: true, force: true });
    replaceCases.forEach((c, i) => {
      mkdirSync(dirname(c.src), { recursive: true });
      if (c.create) writeFileSync(c.src, 'x', 'utf8');
      let mine = '(no error)';
      try {
        pyfs.pyReplace(c.src, c.dst);
      } catch (e) {
        mine = e.message;
      }
      cases.push({ name: `os_replace/${i}`, kind: 'bytes', expected: unb64(answers[i]), actual: mine });
    });
    rmSync(dir, { recursive: true, force: true });
  }

  // -------------------------------------------------------------------------- sessions
  const brokenPacks = writeBrokenAccountingPacks(ctx.scratch);
  const specs = sessions(
    writeSchemaPackWithoutMinItems(ctx.scratch),
    writeSchemaPackWithAnyRolesValue(ctx.scratch),
    brokenPacks,
  );
  const dirs = specs.map((_, i) => join(ctx.scratch, `c${i}`));
  const pythonPayload = {
    op: 'session',
    cases: specs.map((s, i) => ({
      name: s.name,
      dir: dirs[i],
      file: s.file,
      checkpoint: s.checkpoint ?? null,
      target: s.targetSuffix ? dirs[i] + s.targetSuffix : join(dirs[i], s.file),
      assets: s.assets ?? null,
      calls: s.calls,
    })),
  };
  const pythonSessions = ctx.runPython(REF, pythonPayload).results;
  // Same paths for Node: every log field and every errno sentence embeds the absolute path.
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });

  /** `name -> {spec, python, node}`, so the per-side block below can read either side alone. */
  const ran = new Map();
  // job50/F6: the reference pins `time.time()` through ONE process-wide `_FrozenTime` — its
  // `now` starts at 0.0, every `clock_out` call sets it, and `clock_in` stamps its brief line
  // with whatever it holds at that moment, ACROSS sessions, since all of them run in the one
  // `runPython` call above. The same seam here, shared across the loop in the same order —
  // measured: a per-session reset left 15 `session/*/log` cases differing by a `1970-01-01`
  // stamp that neither runtime chose.
  const clock = { now: 0 };
  for (let i = 0; i < specs.length; i += 1) {
    const spec = specs[i];
    const mine = await runNodeSession(shiftwork, pyjson, spec, dirs[i], clock);
    const theirs = pythonSessions[i];
    ran.set(spec.name, { spec, python: theirs, node: mine });
    const steps = Math.max(mine.steps.length, theirs.steps.length);
    for (let s = 0; s < steps; s += 1) {
      const a = theirs.steps[s] ?? { result: b64('(missing)'), checkpoint: null, log: null, tmp_left: false };
      const b = mine.steps[s] ?? { result: b64('(missing)'), checkpoint: null, log: null, tmp_left: false };
      const label = `${spec.name}/${s}:${spec.calls[s]?.fn ?? '?'}`;
      cases.push({ name: `session/${label}/result`, kind: 'bytes', expected: unb64(a.result), actual: unb64(b.result) });
      cases.push({
        name: `session/${label}/checkpoint`,
        kind: 'bytes',
        expected: a.checkpoint === null ? Buffer.from('(absent)') : unb64bytes(a.checkpoint),
        actual: b.checkpoint === null ? Buffer.from('(absent)') : unb64bytes(b.checkpoint),
      });
      cases.push({
        name: `session/${label}/log`,
        kind: 'bytes',
        expected: a.log === null ? Buffer.from('(absent)') : unb64bytes(a.log),
        actual: b.log === null ? Buffer.from('(absent)') : unb64bytes(b.log),
      });
      cases.push({ name: `session/${label}/tmp-left`, kind: 'json', expected: a.tmp_left, actual: b.tmp_left });
    }
  }

  // ------------------------------------- AS-2: the refusal BIT and the sentence, per side
  //
  // WHY THE SESSIONS ABOVE ARE NOT ENOUGH, IN TWO SEPARATE WAYS.
  //
  // 1. A DIFFERENTIAL CANNOT SEE A SYMMETRIC REGRESSION. The two refusal sentences exist
  //    once per runtime and were COPIED between them; a paraphrase applied to both leaves
  //    every `session/*/result` case green. The same is true of the rule itself: delete the
  //    check from both and the differential still agrees. So the sentence is pinned here as
  //    a literal against EACH side, which is the instrument J46-6 arrived at on a shared
  //    default and J46-7 reused on the schema's `propertyNames`.
  //
  // 2. A REFUSAL NEEDS TWO CASES, NOT ONE. Asserting the sentence proves what was said; it
  //    does not, on its own, say that a refusal happened rather than a success carrying an
  //    odd `reason`. The `bit` rows below assert `result` alone, separately from the text —
  //    the same discipline a `ruling:` case needs, where the ruling proves the two sides
  //    DIFFER and a second non-ruled case has to prove both still refuse.
  //
  // 3. AND "NOTHING WAS WRITTEN" IS NOT A DIFFERENTIAL PROPERTY EITHER. `session/*/checkpoint`
  //    compares Node's bytes to Python's; if the check moved BELOW the log-then-commit pair
  //    on both sides, both would write the same orphan line and both would advance the same
  //    cursor, and every one of those cases would stay green. The `untouched` rows compare
  //    each side's post-refusal bytes to THE BYTES THE HARNESS WROTE, which is a statement
  //    about one runtime and cannot be satisfied by agreeing with the other.
  {
    const at = (name, step) => {
      const entry = ran.get(name);
      const pick = (side) => entry[side].steps[step];
      return {
        python: JSON.parse(unb64(pick('python').result)),
        node: JSON.parse(unb64(pick('node').result)),
        pythonRaw: pick('python'),
        nodeRaw: pick('node'),
        wrote: entry.spec.checkpoint,
      };
    };
    const both = (v) => ({ python: v, node: v });
    /** The `result` field alone: did it refuse at all? */
    const bit = (label, name, step, expected) => {
      const got = at(name, step);
      cases.push({
        name: `roles/bit/${label}`,
        kind: 'json',
        expected: both(expected),
        actual: { python: got.python.result, node: got.node.result },
      });
    };
    /** The refusal SENTENCE, as a literal on each side. */
    const says = (label, name, step, sentence) => {
      const got = at(name, step);
      cases.push({
        name: `roles/sentence/${label}`,
        kind: 'json',
        expected: both(sentence),
        actual: { python: got.python.reason ?? null, node: got.node.reason ?? null },
      });
    };
    /**
     * The refusal is TOTAL: this side's checkpoint is still the bytes the harness wrote, and
     * no accounting line exists. Compared against the input, never against the other runtime.
     */
    const untouched = (label, name, step) => {
      const got = at(name, step);
      const state = (raw_) => ({
        checkpoint: raw_.checkpoint === got.wrote ? 'as written' : 'REWRITTEN',
        log: raw_.log === null ? 'no log file' : `log exists: ${unb64(raw_.log)}`,
        tmp: raw_.tmp_left,
      });
      cases.push({
        name: `roles/untouched/${label}`,
        kind: 'json',
        expected: both({ checkpoint: 'as written', log: 'no log file', tmp: false }),
        actual: { python: state(got.pythonRaw), node: state(got.nodeRaw) },
      });
    };

    const WRONG_MODEL =
      'unit N1 in role implementer reported model haiku, which job.roles.implementer ' +
      'does not allow: claude-sonnet-5, claude-opus-5';
    const NO_MODEL =
      'unit N1 in role implementer reported no model, but job.roles.implementer ' +
      'allows only: claude-sonnet-5, claude-opus-5';

    // ---- 1. the refusal: the bit, the sentence, and that nothing moved.
    bit('wrong-model', 'roles/refuse-wrong-model', 0, 'error');
    says('wrong-model', 'roles/refuse-wrong-model', 0, WRONG_MODEL);
    untouched('wrong-model', 'roles/refuse-wrong-model', 0);
    // ---- 2. the refusal is total, and the cursor did not move: clock_in still offers N1.
    cases.push({
      name: 'roles/cursor-never-moved-after-a-refusal',
      kind: 'json',
      expected: both('N1'),
      actual: {
        python: at('roles/refuse-wrong-model', 1).python.unit?.id ?? null,
        node: at('roles/refuse-wrong-model', 1).node.unit?.id ?? null,
      },
    });

    // ---- 3. the four spellings of "no model at all" are ONE sentence.
    for (const [label, name] of [
      ['no-model-key', 'roles/refuse-no-model-key'],
      ['accounting-null', 'roles/refuse-accounting-null'],
      ['accounting-empty', 'roles/refuse-accounting-empty'],
      ['model-null', 'roles/refuse-model-null'],
    ]) {
      bit(label, name, 0, 'error');
      says(label, name, 0, NO_MODEL);
      untouched(label, name, 0);
    }

    // ---- 4. the allowed path: it clocks out, and the log line keeps the model.
    bit('allowed-model', 'roles/allowed-model-clocks-out', 0, 'ok');
    cases.push({
      name: 'roles/allowed-model-reaches-the-accounting-line',
      kind: 'json',
      expected: both('claude-sonnet-5'),
      actual: {
        python: JSON.parse(unb64(at('roles/allowed-model-clocks-out', 0).pythonRaw.log)).model,
        node: JSON.parse(unb64(at('roles/allowed-model-clocks-out', 0).nodeRaw.log)).model,
      },
    });

    // ---- 5. NOTHING DECLARED — the backwards-compatibility case, and the one an existing
    // user's checkpoint depends on. `haiku` is on no list anywhere and clocks out fine.
    bit('no-roles-map', 'roles/no-map-at-all-is-unchanged', 0, 'ok');
    bit('absent-role', 'roles/absent-role-is-unconstrained', 0, 'ok');
    cases.push({
      name: 'roles/no-roles-map-still-logs-the-model-it-was-given',
      kind: 'json',
      expected: both('haiku'),
      actual: {
        python: JSON.parse(unb64(at('roles/no-map-at-all-is-unchanged', 0).pythonRaw.log)).model,
        node: JSON.parse(unb64(at('roles/no-map-at-all-is-unchanged', 0).nodeRaw.log)).model,
      },
    });

    // ---- 6. THE EMPTY LIST IS NOT THE ABSENT KEY. Two inputs, two answers, twice over:
    // under the shipped schema the empty one is refused before the check is reached, and
    // under a schema without `minItems` it is refused BY the check (J46-10's ruling), while
    // the absent role clocks out in both worlds. Pinning only the first pair would leave the
    // ruling resting on a keyword in a shared asset.
    bit('empty-list-shipped-schema', 'roles/empty-list-refused-by-the-schema', 0, 'error');
    says(
      'empty-list-shipped-schema',
      'roles/empty-list-refused-by-the-schema',
      0,
      "checkpoint invalid: JSON does not match schema at 'job/roles/implementer': [] should be non-empty",
    );
    bit('empty-list-fails-closed', 'roles/pack/empty-list-fails-closed', 0, 'error');
    says(
      'empty-list-fails-closed',
      'roles/pack/empty-list-fails-closed',
      0,
      'unit N1 in role implementer reported model haiku, which job.roles.implementer does not allow: ',
    );
    says(
      'empty-list-fails-closed-no-model',
      'roles/pack/empty-list-fails-closed',
      1,
      'unit N1 in role implementer reported no model, but job.roles.implementer allows only: ',
    );
    untouched('empty-list-fails-closed', 'roles/pack/empty-list-fails-closed', 0);
    // The companion that keeps the pack honest: it did not simply break every clock-out.
    bit('pack-absent-role-still-ok', 'roles/pack/absent-role-still-unconstrained', 0, 'ok');

    // ---- 7. checkpoint ORDER, and the model spelling, compared EXACTLY.
    says(
      'checkpoint-order-not-sorted',
      'roles/checkpoint-order-not-sorted',
      0,
      'unit N1 in role implementer reported model haiku, which job.roles.implementer does not allow: zzz-last, aaa-first',
    );
    bit('exact-compare-1m-suffix', 'roles/exact-compare-1m-suffix', 0, 'error');
    says(
      'exact-compare-1m-suffix',
      'roles/exact-compare-1m-suffix',
      0,
      'unit N1 in role implementer reported model claude-opus-5[1m], which job.roles.implementer ' +
        'does not allow: claude-sonnet-5, claude-opus-5',
    );
    bit('exact-compare-case-shift', 'roles/exact-compare-case-shift', 0, 'error');

    // ---- 8. the list consulted is the UNIT's role, not the map's first entry.
    says(
      'per-role-not-the-first-entry',
      'roles/per-role-not-the-first-entry',
      1,
      'unit N2 in role reviewer reported model claude-sonnet-5, which job.roles.reviewer does not allow: claude-opus-5',
    );

    // ---- 9. `accounting` has no schema, so a non-string model is rendered by `str()`.
    const NON_STRING = ['5', '5.0', 'True', "['a', 'b']", "{'name': 'x'}"];
    NON_STRING.forEach((rendered, step) => {
      says(
        `non-string-model/${rendered}`,
        'roles/non-string-models',
        step,
        `unit N1 in role implementer reported model ${rendered}, which job.roles.implementer ` +
          'does not allow: claude-sonnet-5, claude-opus-5',
      );
    });

    notes.push(
      'AS-2: the roles check is reached by 18 sessions and pinned by ' +
        `${cases.filter((c) => c.name.startsWith('roles/')).length} per-side cases — ` +
        'the differential alone is blind to a sentence changed on both sides, to a check ' +
        'deleted from both, and to a refusal that started writing on both.',
    );
    const ruledCount = cases.filter((c) => c.name.startsWith('roles/')).length;

    // ------------------- J47-4 / J47-5: A DECLARATION THIS CODE CANNOT READ IS NOT A LICENCE
    //
    // The count above is taken BEFORE this block on purpose: J46-10's reading is pinned by
    // exactly the 38 cases it was ruled with, and the block below must be addable without
    // moving that number. Everything from here down is J47-6.
    //
    // MEASURED, NOT ASSUMED, THAT THIS ARM HAD NO COVERAGE: with the reference's guard
    // deleted outright, `--suite shiftwork` printed the same line it prints with the guard
    // in place — 806 cases, 0 failures. Neither J47-4 nor J47-5 added a conformance case, so
    // the parity they claim is, until this block exists, a claim nobody can rerun.
    //
    // AND A DIFFERENTIAL ALONE STILL WOULD NOT BE ENOUGH, for the reason J47-3 demonstrated
    // live one unit earlier in this same job: revert BOTH guards and every `session/*` case
    // goes green again, because the two sides agree perfectly about being wrong together.
    // Both guards were written from the same sentence and copied across — precisely the
    // shape a symmetric regression takes. So each shape below is pinned as a LITERAL against
    // EACH RUNTIME (`bit`, `says` and `untouched` all compare to a constant, never to the
    // other side) and the differential session cases sit underneath as a second net.
    const UNREADABLE =
      'unit N1 in role implementer cannot clock out: job.roles.implementer ' +
      'is not a list of model identifiers, so it allows no model';

    // ---- 10. the seven unreadable shapes: one sentence, both accounting shapes, nothing
    // written. `str` and `dict` are the two that USED to refuse — with the checkpoint's own
    // value minced into the sentence — so their `says` rows are what stop that regressing;
    // `int`, `null` and `bool` are the three that used to raise `TypeError` out of the
    // reference and complete the clock-out on the port; and the two LIST shapes are the ones
    // a bare kind test lets through, which is why the property is list-OF-STRINGS.
    for (const [label] of UNREADABLE_ROLES) {
      const name = `roles/any/unreadable/${label}`;
      for (const step of [0, 1]) {
        const offered = step === 0 ? 'model-haiku' : 'no-model';
        bit(`unreadable/${label}/${offered}`, name, step, 'error');
        says(`unreadable/${label}/${offered}`, name, step, UNREADABLE);
        untouched(`unreadable/${label}/${offered}`, name, step);
      }
    }
    // ---- 11. the refusal is total here too: the cursor never moved, so `clock_in` still
    // offers N1 after two refused clock-outs. Driven on the shape that used to COMPLETE the
    // clock-out on the port — status set, cursor advanced, accounting line written.
    cases.push({
      name: 'roles/any/cursor-never-moved-after-an-unreadable-declaration',
      kind: 'json',
      expected: both('N1'),
      actual: {
        python: at('roles/any/unreadable/int', 2).python.unit?.id ?? null,
        node: at('roles/any/unreadable/int', 2).node.unit?.id ?? null,
      },
    });

    // ---- 12. THE BOUNDARY, and it is the line this block exists to hold. `[]` is a list of
    // model identifiers, so it stays on J46-10's sentence — the SAME document, the SAME
    // relaxed pack as the seven above, and a different answer. Fold the empty case into the
    // unreadable arm (`if (!allowed.length)` reads like a tidy-up) and these two rows are
    // what go red; the schema cannot be what tells them apart, because here there is no
    // schema constraint left on the value at all.
    bit('any/empty-list-model-haiku', 'roles/any/empty-list-is-still-a-list', 0, 'error');
    says(
      'any/empty-list-model-haiku',
      'roles/any/empty-list-is-still-a-list',
      0,
      'unit N1 in role implementer reported model haiku, which job.roles.implementer does not allow: ',
    );
    untouched('any/empty-list-model-haiku', 'roles/any/empty-list-is-still-a-list', 0);
    bit('any/empty-list-no-model', 'roles/any/empty-list-is-still-a-list', 1, 'error');
    says(
      'any/empty-list-no-model',
      'roles/any/empty-list-is-still-a-list',
      1,
      'unit N1 in role implementer reported no model, but job.roles.implementer allows only: ',
    );
    untouched('any/empty-list-no-model', 'roles/any/empty-list-is-still-a-list', 1);

    // ---- 13. the companion that keeps the instrument honest. A pack that refused every
    // document, or a `modelRefusal` that refused everything, would satisfy all of §10-§12
    // and nothing above would notice. An unnamed role still clocks out under this pack.
    bit('any/absent-role-still-ok', 'roles/any/absent-role-still-unconstrained', 0, 'ok');

    notes.push(
      'AS-2 / J47-4+J47-5: an unreadable `job.roles.<role>` is pinned by ' +
        `${cases.filter((c) => c.name.startsWith('roles/')).length - ruledCount} further ` +
        'per-side cases over 9 sessions on a second pack (`additionalProperties: true`) — ' +
        'seven unreadable shapes x two accounting shapes x (bit, sentence, disk untouched), ' +
        'plus `[]` held on J46-10\'s sentence against the same schema, so the line between ' +
        'the two refusals is the code and not the asset.',
    );
  }

  // --------------------------------- job50/F8: `handoff.notes` — the bit, per side
  //
  // F8 LOOSENED a schema: `handoff` gained a key. The sessions above compare the two sides
  // to each other, and for a loosening that is the wrong instrument twice over. Open
  // `handoff` entirely (`additionalProperties: true`) and both runtimes accept the typo
  // together, so `refuse-handoff-additional-properties` stays green under its own name —
  // which is exactly what happened to that case between J50-5's schema edit and this
  // block, with `notes` as the "unknown" key. And a ruling-style case would be no help:
  // a ruling proves the two sides DIFFER, never that both still REFUSE. So the refusal is
  // pinned here as a BIT against a constant on EACH side, the way the `roles/` block does
  // it, and the accept path is pinned the same way so the pair cannot both be satisfied
  // by a schema that refuses everything or one that accepts everything.
  //
  // The names start with `handoff/`, not `roles/`: the AS-2 note above counts `roles/`
  // cases and that number is pinned at what J46-10 ruled with.
  {
    const at = (name, step) => {
      const entry = ran.get(name);
      const pick = (side) => entry[side].steps[step];
      return {
        python: JSON.parse(unb64(pick('python').result)),
        node: JSON.parse(unb64(pick('node').result)),
        pythonRaw: pick('python'),
        nodeRaw: pick('node'),
        wrote: entry.spec.checkpoint,
      };
    };
    const both = (v) => ({ python: v, node: v });
    const bit = (label, name, step, expected) => {
      const got = at(name, step);
      cases.push({
        name: `handoff/bit/${label}`,
        kind: 'json',
        expected: both(expected),
        actual: { python: got.python.result, node: got.node.result },
      });
    };
    const says = (label, name, step, sentence) => {
      const got = at(name, step);
      cases.push({
        name: `handoff/sentence/${label}`,
        kind: 'json',
        expected: both(sentence),
        actual: { python: got.python.reason ?? null, node: got.node.reason ?? null },
      });
    };
    const untouched = (label, name, step) => {
      const got = at(name, step);
      const state = (raw_) => ({
        checkpoint: raw_.checkpoint === got.wrote ? 'as written' : 'REWRITTEN',
        log: raw_.log === null ? 'no log file' : `log exists: ${unb64(raw_.log)}`,
        tmp: raw_.tmp_left,
      });
      cases.push({
        name: `handoff/untouched/${label}`,
        kind: 'json',
        expected: both({ checkpoint: 'as written', log: 'no log file', tmp: false }),
        actual: { python: state(got.pythonRaw), node: state(got.nodeRaw) },
      });
    };
    /** What each side's REWRITTEN checkpoint carries under `handoff.notes`, read from its bytes. */
    const notesOnDisk = (label, name, step, expected) => {
      const got = at(name, step);
      const read = (raw_) => (raw_.checkpoint === null ? '(absent)' : JSON.parse(unb64bytes(raw_.checkpoint).toString('utf8')).handoff.notes ?? '(no notes key)');
      cases.push({
        name: `handoff/on-disk/${label}`,
        kind: 'json',
        expected: both(expected),
        actual: { python: read(got.pythonRaw), node: read(got.nodeRaw) },
      });
    };

    // ---- 1. the accept path: the bit, and the note is in the file each side wrote.
    bit('notes-accepted', 'handoff-notes-accepted', 0, 'ok');
    notesOnDisk('notes-accepted', 'handoff-notes-accepted', 0, HANDOFF_NOTE);
    bit('notes-empty-string', 'handoff-notes-empty-string-overwrites', 0, 'ok');
    notesOnDisk('notes-empty-string-overwrites', 'handoff-notes-empty-string-overwrites', 0, '');

    // ---- 2. THE CASE THIS BLOCK EXISTS FOR: a key that is not `notes` is still refused,
    // as a bit, on each side — and totally: nothing written, cursor never moved.
    bit('unknown-key', 'refuse-handoff-additional-properties', 0, 'error');
    says(
      'unknown-key',
      'refuse-handoff-additional-properties',
      0,
      "refused to write: JSON does not match schema at 'handoff': Additional properties are not allowed ('note' was unexpected)",
    );
    untouched('unknown-key', 'refuse-handoff-additional-properties', 0);
    cases.push({
      name: 'handoff/cursor-never-moved-after-an-unknown-key',
      kind: 'json',
      expected: both('N1'),
      actual: {
        python: at('refuse-handoff-additional-properties', 1).python.unit?.id ?? null,
        node: at('refuse-handoff-additional-properties', 1).node.unit?.id ?? null,
      },
    });

    // ---- 3. the key is a STRING: the right name with the wrong shape is refused too.
    bit('notes-not-a-string', 'refuse-handoff-notes-not-a-string', 0, 'error');
    says(
      'notes-not-a-string',
      'refuse-handoff-notes-not-a-string',
      0,
      "refused to write: JSON does not match schema at 'handoff/notes': 5 is not of type 'string'",
    );
    untouched('notes-not-a-string', 'refuse-handoff-notes-not-a-string', 0);

    notes.push(
      'job50/F8: `handoff.notes` is pinned by ' +
        `${cases.filter((c) => c.name.startsWith('handoff/')).length} per-side cases over 4 sessions ` +
        'through each runtime\'s own schema loader — the accept bit and the note on disk, ' +
        'and the refusal bit for an unknown key, which is the one a loosened schema needs.',
    );
  }

  // ------------------------- job50/F5 (J50-10): the accounting line's shape — the bit, per side
  //
  // TWO PROPERTIES, both refusals, pinned the way the `roles/` and `handoff/` blocks pin
  // theirs: the BIT, the SENTENCE and the DISK, each against a constant on EACH side, never
  // against the other runtime. The sessions above compare the two sides and would stay green
  // through a check deleted from both, a sentence paraphrased on both, or a refusal that
  // started writing on both — and one of these two refusals was a crash (`AssetNotFound` out
  // of `clock_out`) four hours before this block was written, which no differential row saw.
  //
  //   1. THE SHAPE REFUSAL. `unit {unit} in role {role} reported an accounting line the schema
  //      refuses: {problem}` — the frame is a copied string; the `{problem}` is each side's own
  //      validator, and the literals below are Python's, taken by running it, not by reading it.
  //   2. THE UNREADABLE-SHAPE REFUSAL. `ACCOUNTING_SHAPE_UNREADABLE`, one sentence with no
  //      interpolation slot at all, for every way a pack can fail to supply the shape — and
  //      the boundary that keeps that from being "refuse everything": a null line under the
  //      same pack still clocks out. Missing and malformed are ONE sentence by ruling (J50-9A).
  //
  // The names start with `accounting/` and `shape-unreadable/`, not `roles/`: the AS-2 note
  // counts `roles/` cases and that number is pinned at what J46-10 ruled with.
  {
    const perSide = (prefix) => {
      const at = (name, step) => {
        const entry = ran.get(name);
        const pick = (side) => entry[side].steps[step];
        return {
          python: JSON.parse(unb64(pick('python').result)),
          node: JSON.parse(unb64(pick('node').result)),
          pythonRaw: pick('python'),
          nodeRaw: pick('node'),
          wrote: entry.spec.checkpoint,
        };
      };
      const both = (v) => ({ python: v, node: v });
      const bit = (label, name, step, expected) => {
        const got = at(name, step);
        cases.push({
          name: `${prefix}/bit/${label}`,
          kind: 'json',
          expected: both(expected),
          actual: { python: got.python.result, node: got.node.result },
        });
      };
      const says = (label, name, step, sentence) => {
        const got = at(name, step);
        cases.push({
          name: `${prefix}/sentence/${label}`,
          kind: 'json',
          expected: both(sentence),
          actual: { python: got.python.reason ?? null, node: got.node.reason ?? null },
        });
      };
      const untouched = (label, name, step) => {
        const got = at(name, step);
        const state = (raw_) => ({
          checkpoint: raw_.checkpoint === got.wrote ? 'as written' : 'REWRITTEN',
          log: raw_.log === null ? 'no log file' : `log exists: ${unb64(raw_.log)}`,
          tmp: raw_.tmp_left,
        });
        cases.push({
          name: `${prefix}/untouched/${label}`,
          kind: 'json',
          expected: both({ checkpoint: 'as written', log: 'no log file', tmp: false }),
          actual: { python: state(got.pythonRaw), node: state(got.nodeRaw) },
        });
      };
      /** The cursor after a refusal, read off the NEXT step's `clock_in`. */
      const cursorStill = (label, name, step, unitId) => {
        const got = at(name, step);
        cases.push({
          name: `${prefix}/cursor-never-moved/${label}`,
          kind: 'json',
          expected: both(unitId),
          actual: { python: got.python.unit?.id ?? null, node: got.node.unit?.id ?? null },
        });
      };
      /** The LAST line of each side's log, parsed, projected onto `keys` — read from its bytes. */
      const logLine = (label, name, step, keys, expected) => {
        const got = at(name, step);
        const read = (raw_) => {
          if (raw_.log === null) return '(no log file)';
          const line = JSON.parse(unb64(raw_.log).trim().split('\n').at(-1));
          return Object.fromEntries(keys.map((k) => [k, k in line ? line[k] : '(absent)']));
        };
        cases.push({
          name: `${prefix}/on-disk/${label}`,
          kind: 'json',
          expected: both(expected),
          actual: { python: read(got.pythonRaw), node: read(got.nodeRaw) },
        });
      };
      return { at, both, bit, says, untouched, cursorStill, logLine };
    };

    // ======================================================== 1. the shape refusal
    {
      const { bit, says, untouched, cursorStill, logLine } = perSide('accounting');
      const FRAME = 'unit N1 in role implementer reported an accounting line the schema refuses: JSON does not match schema at ';
      const refused = (label, name, step, problem) => {
        bit(label, name, step, 'error');
        says(label, name, step, `${FRAME}${problem}`);
        untouched(label, name, step);
      };

      // ---- a. the missing key, and the refusal is total: cursor still N1, no line written
      refused('missing-duration-ms', 'accounting/refuse-missing-duration-ms', 0, "'accounting': 'duration_ms' is a required property");
      cursorStill('missing-duration-ms', 'accounting/refuse-missing-duration-ms', 1, 'N1');
      // ---- b. `best_match`: which error is named when there is more than one
      refused('missing-tokens-outranks-minimum', 'accounting/refuse-missing-tokens-outranks-a-negative-tool-uses', 0, "'accounting': 'tokens' is a required property");
      refused('empty-object-names-tokens-first', 'accounting/refuse-empty-object', 0, "'accounting': 'tokens' is a required property");
      refused('two-wrong-types-names-tokens-first', 'accounting/refuse-two-wrong-types', 0, "'accounting/tokens': 'a' is not of type 'integer'");
      // ---- c. the repr of the value, one per spelling
      const REPR = [
        ['float', "'accounting/tokens': 12.5 is not of type 'integer'"],
        ['bool', "'accounting/tokens': True is not of type 'integer'"],
        ['numeric-string', "'accounting/tokens': '1234' is not of type 'integer'"],
        ['null', "'accounting/tokens': None is not of type 'integer'"],
        ['empty-list', "'accounting/tokens': [] is not of type 'integer'"],
        ['dict', "'accounting/tokens': {'a': None, 'b': 1.5} is not of type 'integer'"],
        ['thai-string', "'accounting/tokens': '\u0e01\u2014' is not of type 'integer'"],
        ['negative', "'accounting/tokens': -1 is less than the minimum of 0"],
        ['negative-cache-read', "'accounting/cache_read_tokens': -5 is less than the minimum of 0"],
        ['note-not-a-string', "'accounting/note': ['x'] is not of type 'string'"],
        ['model-not-a-string', "'accounting/model': 5 is not of type 'string'"],
      ];
      REPR.forEach(([label, problem], step) => refused(`wrong-type/${label}`, 'accounting/refuse-wrong-types', step, problem));
      cursorStill('after-eleven-refusals', 'accounting/refuse-wrong-types', REPR.length, 'N1');
      // ---- d. ORDER: the roles gate speaks first, the shape second, on one document
      bit('order/roles-first', 'accounting/order-roles-gate-then-shape', 0, 'error');
      says(
        'order/roles-first',
        'accounting/order-roles-gate-then-shape',
        0,
        'unit N1 in role implementer reported model haiku, which job.roles.implementer does not allow: claude-sonnet-5, claude-opus-5',
      );
      refused('order/shape-second', 'accounting/order-roles-gate-then-shape', 1, "'accounting': 'duration_ms' is a required property");
      cursorStill('order', 'accounting/order-roles-gate-then-shape', 2, 'N1');
      // ---- e. the ACCEPT side: the bit, the four fields on disk, and the cursor moved
      bit('accept-full-line', 'accounting/accept-full-line', 0, 'ok');
      logLine('accept-full-line', 'accounting/accept-full-line', 0, ['tokens', 'duration_ms', 'model', 'cache_read_tokens', 'unit', 'status'], {
        tokens: 110623,
        duration_ms: 745045,
        model: 'claude-sonnet-5',
        cache_read_tokens: 9876543,
        unit: 'N1',
        status: 'done',
      });
      cursorStill('accept-full-line-advanced', 'accounting/accept-full-line', 1, 'N2');
      bit('accept-whole-floats', 'accounting/accept-whole-floats-are-integers', 0, 'ok');
      bit('accept-unbounded-integer', 'accounting/accept-unbounded-integer', 0, 'ok');
      bit('accept-odd-keys', 'accounting/accept-odd-keys-pass', 0, 'ok');
      logLine('accept-odd-keys', 'accounting/accept-odd-keys-pass', 0, ['duration', 'ก'], { duration: '88.2s', 'ก': '—' });
      // ---- f. the boundary: a null line is not validated, and writes the base shape only
      bit('null-line', 'accounting/null-line-is-not-validated', 0, 'ok');
      logLine('null-line-base-shape', 'accounting/null-line-is-not-validated', 0, ['tokens', 'duration_ms', 'unit', 'role', 'status'], {
        tokens: '(absent)',
        duration_ms: '(absent)',
        unit: 'N1',
        role: 'implementer',
        status: 'done',
      });

      notes.push(
        'job50/F5 (J50-10): the accounting line\'s shape is pinned by ' +
          `${cases.filter((c) => c.name.startsWith('accounting/')).length} per-side cases over ` +
          `${specs.filter((s) => s.name.startsWith('accounting/')).length} sessions — the refusal bit, ` +
          'Python\'s sentence as a literal on each side (best_match choice and repr spelling included), ' +
          'the disk untouched, and the accept bit with the four fields read back off each side\'s log.',
      );
    }

    // ================================================ 2. the unreadable-shape refusal
    {
      const { bit, says, untouched, cursorStill, logLine } = perSide('shape-unreadable');
      // The sentence, 131 bytes, no slot. Measured on both sides before this block existed:
      // sha256 prefix 3f3cbb02da98552f out of `bantamkit.shiftwork` and out of `dist/shiftwork.js`.
      const UNREADABLE_SHAPE =
        "cannot clock out: the shiftwork_clock_out tool asset cannot be read as the accounting line's shape, " +
        'so it allows no accounting line';
      for (const [label] of brokenPacks) {
        const name = `shape-unreadable/${label}`;
        // ---- a. a CONFORMING line is refused, with the one sentence, and nothing is written
        bit(label, name, 0, 'error');
        says(label, name, 0, UNREADABLE_SHAPE);
        untouched(label, name, 0);
        // ---- b. the refusal is total: the cursor did not move
        cursorStill(label, name, 1, 'N1');
        // ---- c. THE BOUNDARY: a null line never reads the asset, so it clocks out under the
        // same pack — and the log line it writes is the base shape, nothing more.
        bit(`${label}/null-line-still-clocks-out`, name, 2, 'ok');
        logLine(`${label}/null-line-base-shape`, name, 2, ['tokens', 'unit', 'role', 'status'], {
          tokens: '(absent)',
          unit: 'N1',
          role: 'implementer',
          status: 'done',
        });
        // ---- d. ORDER: the roles gate is still first, and only a model ON the list reaches this
        bit(`${label}/roles-gate-first`, `${name}/roles-gate-first`, 0, 'error');
        says(
          `${label}/roles-gate-first`,
          `${name}/roles-gate-first`,
          0,
          'unit N1 in role implementer reported model haiku, which job.roles.implementer does not allow: claude-sonnet-5, claude-opus-5',
        );
        says(`${label}/roles-pass-then-unreadable`, `${name}/roles-gate-first`, 1, UNREADABLE_SHAPE);
      }

      notes.push(
        'J50-9A/9B (J50-10): the unreadable-shape refusal is pinned by ' +
          `${cases.filter((c) => c.name.startsWith('shape-unreadable/')).length} per-side cases over ` +
          `${brokenPacks.length} broken packs x 2 sessions — one sentence for every shape, the bit, ` +
          'the disk untouched, the cursor still N1, and a null line clocking out under the same pack.',
      );
    }
  }

  // ------------------------- job50/F6 (J50-13): `briefed` — the ledger, read per side
  //
  // F6 is a field on a line nobody reads back but `_briefed` itself, so the differential
  // rows above are the ONLY thing that has ever compared the two ledgers — and they compare
  // Node's bytes to Python's. Drop the field from both and every `session/*/log` stays
  // green; make `briefed` mean "ever" on both and they stay green too. So each ruling below
  // is a constant read off EACH side's ledger, never off the other runtime:
  //
  //   1. THE BIT. A clock-out with no clock-in SUCCEEDS. That is the sentence in the job's
  //      DO-NOT list — "F6 RECORDS, it never refuses" — and it is pinned as `result: ok`
  //      plus the cursor having moved, separately from the flag. A future "helpful"
  //      refusal turns exactly these rows red and nothing else in the suite.
  //   2. THE TRAIL. Every line of the ledger, projected to `brief N1` / `out N1 true`, so a
  //      brief line that stopped landing, a flag that stopped being consumed, or one that
  //      stopped being per unit each have a row whose expected value they cannot produce.
  //   3. THE LINE. The brief line's exact bytes, as a literal — key set, key order, and the
  //      stamp the harness's clock put there.
  //
  // The names start with `briefed/`: the AS-2 note counts `roles/` and that number is pinned.
  {
    const at = (name, step) => {
      const entry = ran.get(name);
      const pick = (side) => entry[side].steps[step];
      return {
        python: JSON.parse(unb64(pick('python').result)),
        node: JSON.parse(unb64(pick('node').result)),
        pythonRaw: pick('python'),
        nodeRaw: pick('node'),
      };
    };
    const both = (v) => ({ python: v, node: v });
    const row = (label, name, step, expected, read) => {
      const got = at(name, step);
      cases.push({
        name: `briefed/${label}`,
        kind: 'json',
        expected: both(expected),
        actual: { python: read(got.python, got.pythonRaw), node: read(got.node, got.nodeRaw) },
      });
    };
    /** Every ledger line, in order: `brief <unit>` or `out <unit> <briefed>` — `(absent)` if the key is gone. */
    const ledger = (raw_) => {
      if (raw_.log === null) return '(no log file)';
      return unb64(raw_.log)
        .trim()
        .split('\n')
        .map((text) => {
          const line = JSON.parse(text);
          if (line.event === 'brief') return `brief ${line.unit}`;
          return `out ${line.unit} ${'briefed' in line ? String(line.briefed) : '(absent)'}`;
        });
    };
    const bit = (label, name, step, expected) => row(`bit/${label}`, name, step, expected, (r) => r.result);
    const trail = (label, name, step, expected) => row(`trail/${label}`, name, step, expected, (_, raw_) => ledger(raw_));
    const cursor = (label, name, step, unitId) => row(`cursor/${label}`, name, step, unitId, (r) => r.unit?.id ?? null);
    const line = (label, name, step, index, text) =>
      row(`line/${label}`, name, step, text, (_, raw_) => (raw_.log === null ? '(no log file)' : unb64(raw_.log).split('\n')[index]));

    // ---- 1. the pair: brief, then a clock-out that reads it. `accounting: null` still gets the flag.
    bit('in-then-out', 'briefed/in-then-out', 1, 'ok');
    trail('in-then-out', 'briefed/in-then-out', 1, ['brief N1', 'out N1 true']);
    cursor('in-then-out-advanced', 'briefed/in-then-out', 2, 'N2');

    // ---- 2. THE CASE: never clocked in. It SUCCEEDS, the line says `false`, the cursor moved.
    bit('out-without-in-succeeds', 'briefed/out-without-in', 0, 'ok');
    trail('out-without-in', 'briefed/out-without-in', 0, ['out N1 false']);
    cursor('out-without-in-advanced', 'briefed/out-without-in', 1, 'N2');
    bit('out-without-in-null-line-succeeds', 'briefed/out-without-in-null-line', 0, 'ok');
    trail('out-without-in-null-line', 'briefed/out-without-in-null-line', 0, ['out N1 false']);

    // ---- 3. two clock-ins, two brief lines, and the clock-out counts both as one brief.
    trail('clocked-in-twice', 'briefed/clocked-in-twice', 2, ['brief N1', 'brief N1', 'out N1 true']);

    // ---- 4. THE CONSUME RULE, the subtlest one: the blocked clock-out used the brief up, so
    // the re-run with no clock_in reads `false` — and it still succeeds.
    trail('consumed-by-a-clock-out', 'briefed/consumed-by-a-clock-out', 2, ['brief N1', 'out N1 true', 'out N1 false']);
    bit('consumed-re-run-still-succeeds', 'briefed/consumed-by-a-clock-out', 2, 'ok');
    // ---- 5. and a fresh clock_in after the block is a fresh brief.
    trail('re-briefed-after-blocked', 'briefed/re-briefed-after-blocked', 3, ['brief N1', 'out N1 true', 'brief N1', 'out N1 true']);

    // ---- 6. the brief line's exact bytes: four keys, codepoint order, the clock's stamp.
    line(
      'brief-line-shape',
      'briefed/brief-line-shape',
      1,
      1,
      '{"event": "brief", "role": "implementer", "ts": "2025-08-23T06:20:00Z", "unit": "N1"}',
    );
    trail('brief-line-shape', 'briefed/brief-line-shape', 2, ['out N1 false', 'brief N1', 'out N1 true']);

    // ---- 7. per unit: N1's brief is not N2's.
    trail('brief-is-per-unit', 'briefed/brief-is-per-unit', 2, ['brief N1', 'out N1 true', 'out N2 false']);

    // ---- 8. the measured value overwrites a self-reported one, both ways.
    bit('self-report-true-accepted', 'briefed/self-report-true-overwritten', 0, 'ok');
    trail('self-report-true-overwritten', 'briefed/self-report-true-overwritten', 0, ['out N1 false']);
    trail('self-report-false-overwritten', 'briefed/self-report-false-overwritten', 1, ['brief N1', 'out N1 true']);

    // ---- 9. an unwritable ledger: the brief is still returned, no line lands, and the
    // clock-out that follows reads `false` because the record — not the brief — was the cost.
    bit('clock-in-on-an-unwritable-log-still-briefs', 'briefed/clock-in-on-an-unwritable-log', 1, 'brief');
    row('clock-in-on-an-unwritable-log-returns-the-brief', 'briefed/clock-in-on-an-unwritable-log', 1, 'N1', (r) => r.unit?.id ?? null);
    trail('clock-in-on-an-unwritable-log-writes-nothing', 'briefed/clock-in-on-an-unwritable-log', 1, '(no log file)');
    trail('clock-in-on-an-unwritable-log-then-out', 'briefed/clock-in-on-an-unwritable-log', 3, ['out N1 false']);

    notes.push(
      'job50/F6 (J50-13): `briefed` is pinned by ' +
        `${cases.filter((c) => c.name.startsWith('briefed/')).length} per-side cases over ` +
        `${specs.filter((s) => s.name.startsWith('briefed/')).length} sessions — the success bit for a clock-out ` +
        'that was never clocked in, the ledger trail read off each side (two brief lines for two clock-ins, ' +
        'the brief consumed by a clock-out, per unit, self-report overwritten), and the brief line as a literal.',
    );
  }

  // ------------------------- job60 (J60-4): `clock_in(unit_id)` — read per side
  //
  // The session rows above compare Node's bytes to Python's, and this feature landed in the two
  // runtimes as two hand-written copies of one design. Delete the readiness check from both and
  // every one of those rows stays green; paraphrase the refusal on both and they stay green;
  // advance the cursor in plan order on both again and they stay green — which is the shape the
  // `differential-is-blind-to-symmetric-regression` note in this file already names twice. So
  // each ruling below is a constant read off EACH side's answer, never off the other runtime:
  //
  //   1. THE RELATIONSHIP, not each field on its own. The bug hid for a release because
  //      `cursor` and `ready` were only ever asserted separately, on checkpoints where they
  //      happened to agree. `disagreement` reads BOTH surfaces of ONE document at one instant
  //      and pins them as a single value: the cursor briefs `C` while the graph says `B`.
  //   2. THE SENTENCES, as literals — the not-ready refusal with its `", "` join and its batch
  //      order, and `clock_out`'s cursor sentence, which D2 deliberately did NOT widen.
  //   3. THE BIT, separately from the text: a refusal happened, not a success carrying an odd
  //      `reason` — and, on the accept arms, a brief was issued and not a refusal.
  //   4. AND NOTHING WAS WRITTEN. Compared against the bytes the harness wrote, which is a
  //      statement about one runtime and cannot be satisfied by agreeing with the other.
  {
    const at = (name, step) => {
      const entry = ran.get(name);
      const pick = (side) => entry[side].steps[step];
      return {
        python: JSON.parse(unb64(pick('python').result)),
        node: JSON.parse(unb64(pick('node').result)),
        pythonRaw: pick('python'),
        nodeRaw: pick('node'),
        wrote: entry.spec.checkpoint,
      };
    };
    const both = (v) => ({ python: v, node: v });
    const row = (label, name, step, expected, read) => {
      const got = at(name, step);
      cases.push({
        name: `unit-id/${label}`,
        kind: 'json',
        expected: both(expected),
        actual: { python: read(got.python, got.pythonRaw), node: read(got.node, got.nodeRaw) },
      });
    };
    /** `result` alone: did it refuse, or brief, at all? */
    const bit = (label, name, step, expected) => row(`bit/${label}`, name, step, expected, (r) => r.result);
    /** The refusal SENTENCE as a literal, on each side. */
    const says = (label, name, step, sentence) => row(`sentence/${label}`, name, step, sentence, (r) => r.reason ?? null);
    /** Which unit's brief came back — `(not a brief)` when the call refused. */
    const briefed = (label, name, step, unitId) =>
      row(`briefed/${label}`, name, step, unitId, (r) => (r.result === 'brief' ? r.unit.id : '(not a brief)'));
    /** The cursor, off `status`'s answer or off `clock_out`'s. */
    const cursor = (label, name, step, unitId) => row(`cursor/${label}`, name, step, unitId, (r) => r.cursor ?? null);
    /** This side's checkpoint is still the bytes the harness wrote, and no ledger exists. */
    const untouched = (label, name, step) => {
      const got = at(name, step);
      const state = (raw_) => ({
        checkpoint: raw_.checkpoint === got.wrote ? 'as written' : 'REWRITTEN',
        log: raw_.log === null ? 'no log file' : `log exists: ${unb64(raw_.log)}`,
      });
      cases.push({
        name: `unit-id/untouched/${label}`,
        kind: 'json',
        expected: both({ checkpoint: 'as written', log: 'no log file' }),
        actual: { python: state(got.pythonRaw), node: state(got.nodeRaw) },
      });
    };
    /** Every ledger line in order, `brief <unit>` / `out <unit> <briefed>` — the shape F6 uses. */
    const ledger = (raw_) => {
      if (raw_.log === null) return '(no log file)';
      return unb64(raw_.log)
        .trim()
        .split('\n')
        .map((text) => {
          const line = JSON.parse(text);
          return line.event === 'brief' ? `brief ${line.unit}` : `out ${line.unit} ${String(line.briefed)}`;
        });
    };
    const trail = (label, name, step, expected) => row(`trail/${label}`, name, step, expected, (_, raw_) => ledger(raw_));

    // ==================== 1. cursor != ready[0] — the two fields against EACH OTHER
    const DISAGREE = 'unit-id/cursor-disagrees-with-ready';
    // The one row this whole block exists for. It is a single value because the two fields are
    // a single claim: on these bytes the pointer surface and the graph surface name different
    // units. Make `clock_out` advance in plan order again and the cursor half changes; drop the
    // readiness check and the graph half changes; agree with the other runtime about either and
    // this row still fails, because its expected value is a constant written here.
    cases.push({
      name: 'unit-id/disagreement/cursor-briefs-C-while-ready-is-B',
      kind: 'json',
      expected: both('cursor briefs C; ready is B'),
      actual: (() => {
        const noArg = at(DISAGREE, 0);
        const named = at(DISAGREE, 1);
        const read = (side) => {
          const brief = noArg[side];
          const refusal = named[side];
          const head = brief.result === 'brief' ? brief.unit.id : `(${brief.result})`;
          const tail = /ready is (.*)$/.exec(refusal.reason ?? '')?.[1] ?? `(${refusal.result}: no ready list)`;
          return `cursor briefs ${head}; ready is ${tail}`;
        };
        return { python: read('python'), node: read('node') };
      })(),
    });
    // and the same disagreement spelled out call by call, so a red row above has a cause here.
    bit('no-unit-id-still-briefs-the-cursor-unit', DISAGREE, 0, 'brief');
    briefed('no-unit-id-is-the-cursor-unit', DISAGREE, 0, 'C');
    bit('cursor-unit-named-is-refused', DISAGREE, 1, 'error');
    says('cursor-unit-named-is-refused', DISAGREE, 1, 'unit C is not ready; ready is B');
    bit('the-ready-unit-is-briefed', DISAGREE, 2, 'brief');
    briefed('the-ready-unit-is-briefed', DISAGREE, 2, 'B');
    // D1: a wave of briefs never moves the pointer. Three clock-ins, cursor still `C`.
    cursor('clock-in-never-writes-the-cursor', DISAGREE, 3, 'C');
    // the ledger records the units ACTUALLY briefed — the refusal issued nothing, so it logged
    // nothing, which is what keeps `clock_out`'s `briefed` flag honest for a named unit.
    trail('refusal-records-no-brief', DISAGREE, 3, ['brief C', 'brief B']);

    // ==================== 1b. D3 — the pointer lands on the graph's head, not plan order's
    const ADVANCE = 'unit-id/advance-follows-the-graph';
    // `plan.units` order would say `C` here, and said `C` in the measurement that opened job60.
    cursor('advance-lands-on-ready-head-not-plan-order', ADVANCE, 0, 'B');
    cursor('and-status-agrees', ADVANCE, 1, 'B');
    briefed('and-the-brief-that-follows-is-B', ADVANCE, 2, 'B');

    // ==================== 2. a wave: width 2, briefed together, clocked out out of order
    const WAVE = 'unit-id/wave';
    briefed('wave-default-is-the-cursor-unit', WAVE, 0, 'N1');
    briefed('wave-names-the-second-ready-unit', WAVE, 1, 'N2');
    // THE MOVE D2 EXISTS FOR: N2 clocked out before N1, which the pre-job60 runtime refused.
    bit('wave-clock-out-N2-before-N1', WAVE, 2, 'ok');
    // and the pointer did not follow N2 anywhere: N1 is still the only ready unit.
    cursor('wave-cursor-after-N2', WAVE, 2, 'N1');
    cursor('wave-cursor-after-N1', WAVE, 3, 'N3');
    cursor('wave-status-agrees', WAVE, 4, 'N3');
    briefed('wave-N3-once-both-dependencies-are-done', WAVE, 5, 'N3');
    // the ledger: both briefs landed, and BOTH clock-outs read `true` — the named brief counts
    // for the unit it named, which is the whole reason D2 needs no new field.
    trail('wave', WAVE, 5, ['brief N1', 'brief N2', 'out N2 true', 'out N1 true', 'brief N3']);

    // ==================== 3. the not-ready refusal, and the unit that does not exist
    const NOTREADY = 'unit-id/not-ready-refusal';
    bit('not-ready', NOTREADY, 0, 'error');
    says('not-ready', NOTREADY, 0, 'unit N3 is not ready; ready is N1, N2');
    untouched('not-ready', NOTREADY, 0);
    // the limiting case of the same property, refused by the same sentence and not a second one
    bit('no-such-unit', NOTREADY, 1, 'error');
    says('no-such-unit', NOTREADY, 1, 'unit nope is not ready; ready is N1, N2');
    untouched('no-such-unit', NOTREADY, 1);
    cursor('refusals-left-the-cursor-alone', NOTREADY, 2, 'N1');

    // ==================== 4. `clock_out` did NOT become permissive
    const NEVER = 'unit-id/never-briefed-clock-out-still-refuses';
    bit('never-briefed', NEVER, 0, 'error');
    // D2 kept this sentence deliberately, so every ruled case pinning it stays green. A widened
    // wording is a docs change in `docs/shiftwork.md`, never a change here.
    says('never-briefed', NEVER, 0, 'unit N2 is not the cursor unit N1');
    untouched('never-briefed', NEVER, 0);
    cursor('never-briefed-cursor-unmoved', NEVER, 1, 'N1');

    // ==================== 5. the default path, on the shipped template — unmoved
    const TEMPLATE = 'unit-id/default-path-on-the-template';
    bit('template-default-path', TEMPLATE, 0, 'brief');
    briefed('template-default-path', TEMPLATE, 0, CURSOR);
    // cursor == ready[0] here, so NAMING the unit answers the same thing as naming nothing —
    // which is why no checkpoint in this suite could see the bug before these sessions existed.
    bit('template-naming-the-cursor-unit', TEMPLATE, 1, 'brief');
    briefed('template-naming-the-cursor-unit', TEMPLATE, 1, CURSOR);
    cursor('template-cursor-unmoved', TEMPLATE, 2, CURSOR);

    notes.push(
      'job60/D1-D3 (J60-4): `clock_in(unit_id)` is pinned by ' +
        `${cases.filter((c) => c.name.startsWith('unit-id/')).length} per-side cases over ` +
        `${specs.filter((s) => s.name.startsWith('unit-id/')).length} sessions on documents whose plan order and ` +
        'graph order DISAGREE — the one row holding `cursor` and `ready` against each other, the ' +
        'not-ready sentence (a unit with unmet dependencies and one that names no unit at all), ' +
        'the cursor landing on `ready[0]` rather than plan order, a two-wide wave clocked out ' +
        'in the other order, `clock_out`\'s unwidened cursor sentence, and the shipped template ' +
        'answering identically with and without the argument.',
    );
  }

  // ------------------------------------------------------------------- the ruled cases
  //
  // The ONE place this port cannot recover Python's answer, and it is upstream of this
  // module: a value that has already been through an SDK's `JSON.parse` cannot remember
  // that its text said `5.0`. `parseJson` over the wire bytes is the exact route and every
  // session case above uses it; `fromJs` is the fallback, and this is what it costs.
  {
    const dir = join(ctx.scratch, 'ruled-float');
    mkdirSync(dir, { recursive: true });
    const path = join(dir, 'checkpoint.json');
    const bytes = b64(raw(baseDocument()));
    const pyAnswer = ctx.runPython(REF, {
      op: 'session',
      cases: [{
        name: 'ruled-float',
        dir,
        file: 'checkpoint.json',
        checkpoint: bytes,
        target: path,
        calls: [OUT('N1', 'done', { accounting: b64('{"tokens": 5.0, "duration_ms": 1, "ratio": 2.0}') })],
      }],
    }).results[0];
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });
    writeFileSync(path, unb64bytes(bytes));
    shiftwork.clockOut(path, 'N1', 'done', null, { unit: 'N1', outcome: 'done' }, fromJs({ tokens: 5.0, duration_ms: 1, ratio: 2.0 }), {
      now: 1755930000,
    });
    cases.push({
      name: 'ruled/accounting-through-a-js-object-loses-5.0',
      kind: 'bytes',
      expected: unb64bytes(pyAnswer.steps[0].log),
      actual: readFileSync(`${path}.log.jsonl`),
      ruling:
        'a JS number carries no record of a decimal point, so an accounting value that ' +
        'already went through JSON.parse logs as `5` where Python logs `5.0`. The exact ' +
        'route is pyjson.parseJson over the wire bytes, which every session case above ' +
        'uses and which matches byte for byte; this is what the fallback costs.',
    });
    notes.push(
      'the fromJs route for accounting is RULED to differ on an integral float; ' +
        'the parseJson route is byte-identical (see every session/*/log case).',
    );
  }

  notes.push(`${DUMP_TEXTS.length + 2} documents x 2 indents x 2 sort settings through json.dumps`);
  notes.push(`${specs.length} sessions, ${specs.reduce((n, s) => n + s.calls.length, 0)} calls, 4 comparisons each`);

  return { cases, notes };
}
