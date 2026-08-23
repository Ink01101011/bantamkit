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
import { chmodSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
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
const IN = () => ({ fn: 'clock_in' });
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

function sessions() {
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

  const ring = baseDocument();
  ring.history = [1, 2, 3, 4, 5].map((n) => ({ unit: `old${n}`, outcome: 'done', notes: `note ${n} — kept` }));
  add('history-ring-overflow', b64(raw(ring)), [ST(), OUT('N1', 'done'), ST()]);

  const four = baseDocument();
  four.history = [1, 2, 3, 4].map((n) => ({ unit: `old${n}`, outcome: 'done' }));
  add('history-ring-exactly-full', b64(raw(four)), [OUT('N1', 'done')]);

  // ---- accounting: the four base keys are overridable, and the sort is by codepoint.
  add('accounting-overrides-and-sorts', b64(raw(baseDocument())), [
    OUT('N1', 'done', {
      accounting: b64('{"ts": "overridden", "role": "planner", "\\ud83d\\ude00": 1, "\\ue000": 2, "z": 3, "": 4}'),
    }),
  ]);
  add('accounting-float-and-bigint', b64(raw(baseDocument())), [
    OUT('N1', 'done', {
      accounting: b64('{"n": 5.0, "neg0": -0.0, "big": 12345678901234567890123, "sci": 1e16, "tiny": 1e-5, "s": "\\u0e01 \\u2014"}'),
    }),
  ]);
  add('accounting-nested', b64(raw(baseDocument())), [
    OUT('N1', 'done', { accounting: b64('{"nested": {"b": [1, 2.0, {"z": null}], "a": true}, "empty": {}}') }),
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
  add('refuse-handoff-additional-properties', b64(raw(baseDocument())), [
    OUT('N1', 'done', { handoff_patch: b64(JSON.stringify({ notes: 'nope' })) }),
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

  return cases;
}

// ================================================================================== node

/** The Node side of one session — the same loop the reference script runs. */
async function runNodeSession(shiftwork, pyjson, caseSpec, dir) {
  const { dumpJson, parseJson } = pyjson;
  mkdirSync(dir, { recursive: true });
  const path = join(dir, caseSpec.file);
  if (caseSpec.checkpoint !== null && caseSpec.checkpoint !== undefined) {
    writeFileSync(path, unb64bytes(caseSpec.checkpoint));
  }
  const target = caseSpec.targetSuffix ? dir + caseSpec.targetSuffix : path;
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
    if (call.fn === 'clock_in') answer = shiftwork.clockIn(target);
    else if (call.fn === 'status') answer = shiftwork.status(target);
    else {
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
  return { steps };
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
  const specs = sessions();
  const dirs = specs.map((_, i) => join(ctx.scratch, `c${i}`));
  const pythonPayload = {
    op: 'session',
    cases: specs.map((s, i) => ({
      name: s.name,
      dir: dirs[i],
      file: s.file,
      checkpoint: s.checkpoint ?? null,
      target: s.targetSuffix ? dirs[i] + s.targetSuffix : join(dirs[i], s.file),
      calls: s.calls,
    })),
  };
  const pythonSessions = ctx.runPython(REF, pythonPayload).results;
  // Same paths for Node: every log field and every errno sentence embeds the absolute path.
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });

  for (let i = 0; i < specs.length; i += 1) {
    const spec = specs[i];
    const mine = await runNodeSession(shiftwork, pyjson, spec, dirs[i]);
    const theirs = pythonSessions[i];
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
        calls: [OUT('N1', 'done', { accounting: b64('{"tokens": 5.0, "ratio": 2.0}') })],
      }],
    }).results[0];
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });
    writeFileSync(path, unb64bytes(bytes));
    shiftwork.clockOut(path, 'N1', 'done', null, { unit: 'N1', outcome: 'done' }, fromJs({ tokens: 5.0, ratio: 2.0 }), {
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
