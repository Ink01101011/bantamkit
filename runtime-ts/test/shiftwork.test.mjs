/**
 * shiftwork — 78 statements of control flow wrapped around four ways to corrupt a file.
 *
 * THE PROPERTY: given the same checkpoint and the same call, Node writes byte-identical
 * files and returns the identical result object. Three artefacts are at stake — the
 * rewritten checkpoint, the `.log.jsonl` line, and the returned dict — and the log is read
 * back only by `briefed` (job50/F6), which looks at two keys, so a wrong log line is
 * otherwise invisible to the code that wrote it.
 *
 * The Python differential lives in `tools/conformance/suites/shiftwork.mjs`. This file is
 * the fast loop: it pins the four serializer rules, the refusal sentences, and the
 * write-nothing-on-refusal property that no differential can state as clearly.
 *
 * Nothing here opens a real `.shiftwork/` checkpoint. Every fixture is built under the OS
 * temp directory; the job whose checkpoint this unit is being run from is exactly the file
 * a careless port would rewrite un-escaped on its first successful clock-out.
 */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { appendFileSync, chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const dist = new URL('../dist/', import.meta.url);
const { clockIn, clockOut, planBatches, status, HISTORY_RING_SIZE } = await import(new URL('shiftwork.js', dist));
const { dumpJson, fromJs, parseJson, toJs } = await import(new URL('pyjson.js', dist));
const { pyNewlineOut, pyReadText, pyReplace, pyRepr, pySuffix, PyUnicodeDecodeError } =
  await import(new URL('memory/pyfs.js', dist));
const { assetsRoot, loadSchema } = await import(new URL('assets.js', dist));

/**
 * A path as `str(OSError)` prints it: `%r`, which ESCAPES A BACKSLASH.
 *
 * Interpolating the path raw passes on POSIX and fails on Windows for a reason that has
 * nothing to do with the port. MEASURED, run 32646521489: three nodes here differed only in
 * that `C:\Users\...` came back from the port as `C:\\Users\\...`, which is exactly what
 * CPython's `repr` prints and what the conformance suite's `oserror` case confirms against
 * the running Python. The expectation was wrong, not the sentence.
 */
const asRepr = (path) => pyRepr(path);

// `realpathSync`: `os.tmpdir()` is not canonical — a `/var` symlink on macOS, the 8.3
// short name on Windows CI. See the note in test/store.test.mjs.
const fresh = () => realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-shiftwork-')));
const bytes = (p) => readFileSync(p);
const text = (p) => readFileSync(p, 'utf8');
/**
 * The same file as `Path.read_text` reads it — universal-newline, so the assertions about
 * CONTENT are spelled in LF on every platform.
 *
 * `Path.write_text` translates `\n` to `os.linesep` on the way out, so on Windows the
 * checkpoint and the accounting log are CRLF on disk, exactly as the reference writes them.
 * A test that reads the raw bytes and compares to an LF string is asserting the port
 * disagrees with CPython there. MEASURED, run 32649940727: four nodes here.
 */
const read = (p) => pyReadText(p);
/** Expected ON-DISK text, where the bytes themselves are the property. */
const disk = (expected) => pyNewlineOut(expected);
const js = (v) => toJs(v);

/** A minimal checkpoint that satisfies the shipped schema, written VERBATIM (raw UTF-8). */
function checkpointDocument(over = {}) {
  return {
    version: 1,
    job: {
      id: 'j',
      goal: 'g',
      done_definition: 'd',
      constraints: ['PURE NODE at runtime.', 'เป้าหมาย — no pipe/uv'],
    },
    plan: {
      cursor: 'N1',
      units: [
        { id: 'N1', title: 't1', brief_path: 'b1.md', status: 'todo', role: 'implementer', depends_on: [], verify: 'v1' },
        { id: 'N2', title: 't2', brief_path: 'b2.md', status: 'todo', role: 'reviewer', depends_on: ['N1'], verify: 'v2' },
      ],
    },
    state: {
      repo: { branch: 'main', head_sha: 'abc', dirty: false },
      artifacts: [{ path: 'probe.md', role: 'evidence' }],
      external: [],
    },
    history: [],
    retro: [],
    handoff: { next_action: 'go', open_questions: [], do_not: ['do not guess'] },
    ...over,
  };
}

function writeCheckpoint(root, document = checkpointDocument(), name = 'checkpoint.json') {
  const path = join(root, name);
  // RAW, not escaped: this is what a human-written checkpoint looks like on disk, and the
  // whole ensure_ascii question is what the first clock-out does to it.
  writeFileSync(path, `${JSON.stringify(document, null, 2)}\n`, 'utf8');
  return path;
}

// ============================================================ the four serializer rules

test('ensure_ascii: every non-ASCII codepoint leaves as \\uXXXX, astral as a surrogate pair', () => {
  assert.equal(dumpJson(fromJs({ th: 'แ', dash: '—', face: '😀' })), '{"th": "\\u0e41", "dash": "\\u2014", "face": "\\ud83d\\ude00"}');
});

test('ensure_ascii escapes DEL and every C0 control, and does NOT escape a solidus', () => {
  assert.equal(dumpJson(fromJs('\x7f')), '"\\u007f"');
  assert.equal(dumpJson(fromJs('\b\f\n\r\t\v\x07\0')), '"\\b\\f\\n\\r\\t\\u000b\\u0007\\u0000"');
  assert.equal(dumpJson(fromJs('a/b')), '"a/b"');
  assert.equal(dumpJson(fromJs('  ')), '"\\u00a0\\u2028"');
});

test('separators: `, ` and `: ` with no indent, `,` and `: ` with one', () => {
  assert.equal(dumpJson(fromJs({ a: 1, b: [1, 2] })), '{"a": 1, "b": [1, 2]}');
  assert.equal(dumpJson(fromJs({ a: 1, b: [1, 2] }), { indent: 2 }), '{\n  "a": 1,\n  "b": [\n    1,\n    2\n  ]\n}');
  assert.equal(dumpJson(fromJs({ a: {}, b: [] }), { indent: 2 }), '{\n  "a": {},\n  "b": []\n}');
  assert.equal(dumpJson(fromJs([]), { indent: 2 }), '[]');
});

test('sort_keys is a CODEPOINT sort, which UTF-16 gets wrong for every astral key', () => {
  // 'z' < U+E000 < U+1F600 by codepoint. By UTF-16 unit the lead surrogate 0xD83D sorts
  // BEFORE 0xE000, so a bare `.sort()` emits these three keys in the wrong order.
  assert.equal(
    dumpJson(fromJs(new Map([['\u{1F600}', 1], ['', 2], ['z', 3]])), { sortKeys: true }),
    '{"z": 3, "\\ue000": 2, "\\ud83d\\ude00": 1}',
  );
  assert.equal(
    dumpJson(fromJs(new Map([['b', 1], ['A', 2], ['a', 3], ['_', 4], ['', 5]])), { sortKeys: true }),
    '{"": 5, "A": 2, "_": 4, "a": 3, "b": 1}',
  );
});

test('sort_keys off keeps insertion order, and an update to an existing key keeps its slot', () => {
  const m = new Map([['a', 1], ['b', 2]]);
  m.set('a', 9);
  m.set('c', 3);
  assert.equal(dumpJson(fromJs(m)), '{"a": 9, "b": 2, "c": 3}');
});

test('float boundaries: repr is shortest-round-trip in BOTH runtimes and formats in neither the same way', () => {
  const dump = (literal) => dumpJson(parseJson(`{"n": ${literal}}`));
  assert.equal(dump('5.0'), '{"n": 5.0}'); // JSON.stringify says 5
  assert.equal(dump('-0.0'), '{"n": -0.0}'); // JSON.stringify says 0
  assert.equal(dump('0.30000000000000004'), '{"n": 0.30000000000000004}'); // 17 significant digits
  assert.equal(dump('1234567890123456.7'), '{"n": 1234567890123456.8}');
  assert.equal(dump('1e16'), '{"n": 1e+16}'); // JS: 10000000000000000
  assert.equal(dump('1e-5'), '{"n": 1e-05}'); // JS: 0.00001, and no zero-padded exponent
  assert.equal(dump('1e-4'), '{"n": 0.0001}');
  assert.equal(dump('1e21'), '{"n": 1e+21}');
  assert.equal(dump('5e-324'), '{"n": 5e-324}');
  assert.equal(dump('1.7976931348623157e308'), '{"n": 1.7976931348623157e+308}');
});

test('an integer too large for a double survives exactly, because it is not a double', () => {
  assert.equal(dumpJson(parseJson('{"n": 12345678901234567890123}')), '{"n": 12345678901234567890123}');
  // The same digits through a JS number lose the tail.
  assert.equal(dumpJson(fromJs({ n: 12345678901234567890123 })), '{"n": 1.2345678901234568e+22}');
});

test('allow_nan is on: NaN and Infinity leave as bare words no JSON parser accepts', () => {
  assert.equal(dumpJson(parseJson('{"a": NaN, "b": Infinity, "c": -Infinity}')), '{"a": NaN, "b": Infinity, "c": -Infinity}');
});

// ========================================================================== clock_in

test('clock_in returns the brief, and `invariants` is SYNTHESIZED from job.constraints', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const answer = js(clockIn(path));
  assert.equal(answer.result, 'brief');
  assert.equal(answer.unit.id, 'N1');
  assert.equal(answer.role, 'implementer');
  // Not a key of the checkpoint. This is the whole reason a brief must be handed to a
  // subagent verbatim and not as a path: the path does not contain this array.
  assert.equal(JSON.parse(text(path)).invariants, undefined);
  assert.deepEqual(answer.invariants, ['PURE NODE at runtime.', 'เป้าหมาย — no pipe/uv']);
  assert.deepEqual(answer.do_not, ['do not guess']);
  assert.deepEqual(answer.files, [{ path: 'probe.md', role: 'evidence' }]);
  assert.deepEqual(Object.keys(answer), ['result', 'unit', 'role', 'invariants', 'handoff', 'do_not', 'files']);
  rmSync(root, { recursive: true, force: true });
});

test('clock_in escalates on the FIRST open question, and carries them all', () => {
  const root = fresh();
  const doc = checkpointDocument();
  doc.handoff.open_questions = ['is the tag withheld?', 'second'];
  const answer = js(clockIn(writeCheckpoint(root, doc)));
  assert.deepEqual(answer, {
    result: 'escalate',
    reason: 'open question: is the tag withheld?',
    open_questions: ['is the tag withheld?', 'second'],
  });
  rmSync(root, { recursive: true, force: true });
});

test('clock_in reports success when every unit is done or dropped — and on an EMPTY plan', () => {
  const root = fresh();
  const doc = checkpointDocument();
  doc.plan.units[0].status = 'done';
  doc.plan.units[1].status = 'dropped';
  assert.deepEqual(js(clockIn(writeCheckpoint(root, doc))), { result: 'success', reason: 'all units done or dropped' });
  // `all([])` is True in Python, so a plan with no units is SUCCESS and never escalates on
  // its dangling cursor. That ordering is the behaviour, not an accident of the port.
  const empty = checkpointDocument();
  empty.plan.units = [];
  assert.deepEqual(js(clockIn(writeCheckpoint(root, empty, 'empty.json'))), {
    result: 'success',
    reason: 'all units done or dropped',
  });
  rmSync(root, { recursive: true, force: true });
});

test('clock_in escalates on a cursor that names no unit', () => {
  const root = fresh();
  const doc = checkpointDocument();
  doc.plan.cursor = 'N9';
  assert.deepEqual(js(clockIn(writeCheckpoint(root, doc))), { result: 'escalate', reason: 'cursor N9 names no unit' });
  rmSync(root, { recursive: true, force: true });
});

test("the unreadable refusal embeds Python's OSError.__str__, errno number included", () => {
  const root = fresh();
  assert.deepEqual(js(clockIn(join(root, 'nope.json'))), {
    result: 'error',
    reason: `checkpoint unreadable: [Errno 2] No such file or directory: ${asRepr(join(root, 'nope.json'))}`,
  });
  // `Path(checkpoint)` NORMALIZES before the open, so the errno sentence names the
  // normalized path and not the string the caller passed.
  assert.deepEqual(js(clockIn(`${root}//./nope.json`)), {
    result: 'error',
    reason: `checkpoint unreadable: [Errno 2] No such file or directory: ${asRepr(join(root, 'nope.json'))}`,
  });
  rmSync(root, { recursive: true, force: true });
});

test('an unparseable checkpoint refuses with the decoder’s own offsets', () => {
  const root = fresh();
  const path = join(root, 'bad.json');
  writeFileSync(path, '{"version": 1,}\n', 'utf8');
  assert.deepEqual(js(clockIn(path)), {
    result: 'error',
    reason: 'checkpoint is not parseable as JSON: Expecting property name enclosed in double quotes: line 1 column 15 (char 14)',
  });
  rmSync(root, { recursive: true, force: true });
});

test('a parseable checkpoint that fails the schema refuses with the validator’s sentence', () => {
  const root = fresh();
  const doc = checkpointDocument();
  delete doc.retro;
  assert.deepEqual(js(clockIn(writeCheckpoint(root, doc))), {
    result: 'error',
    reason: "checkpoint invalid: JSON does not match schema at 'root': 'retro' is a required property",
  });
  rmSync(root, { recursive: true, force: true });
});

// ========================================================================= clock_out

const OK_ENTRY = { unit: 'N1', outcome: 'done' };

test('clock_out writes the checkpoint ASCII-ONLY, and that is the whole ensure_ascii ruling', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const before = bytes(path);
  assert.ok(before.some((b) => b > 0x7f), 'fixture must actually contain non-ASCII');
  const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, null, { now: 1755930000.9 }));
  assert.deepEqual(answer, { result: 'ok', unit: 'N1', status: 'done', cursor: 'N2', log: `${path}.log.jsonl` });
  const after = bytes(path);
  assert.equal(after.every((b) => b < 0x80), true, 'ensure_ascii=True: the rewritten checkpoint is pure ASCII');
  assert.ok(text(path).includes('\\u0e40'), 'Thai leaves as \\uXXXX');
  assert.ok(text(path).includes('\\u2014'), 'the em dash leaves as \\u2014');
  // And it still round-trips to the same STRING, which is why the corruption is silent.
  assert.deepEqual(JSON.parse(text(path)).job.constraints, ['PURE NODE at runtime.', 'เป้าหมาย — no pipe/uv']);
  assert.equal(text(path).endsWith(disk('\n}\n')), true, 'indent=2 plus a trailing newline');
  rmSync(root, { recursive: true, force: true });
});

test('the log line is sort_keys=True, one line, appended, and read back only by `briefed`', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1, model: 'claude-opus-5[1m]', duration_ms: 2 }, { now: 1755930000.9 });
  const log = text(`${path}.log.jsonl`);
  assert.equal(
    log,
    disk('{"briefed": false, "duration_ms": 2, "model": "claude-opus-5[1m]", "role": "implementer", "status": "done", ' +
      '"tokens": 1, "ts": "2025-08-23T06:20:00Z", "unit": "N1"}\n'),
  );
  clockOut(path, 'N2', 'done', {}, { unit: 'N2', outcome: 'done' }, null, { now: 1755930001 });
  assert.equal(read(`${path}.log.jsonl`).split('\n').filter(Boolean).length, 2, 'append, not truncate');
});

test('accounting can OVERRIDE the four keys the record starts with', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  // `tokens` + `duration_ms` because the line is a real accounting line since job50/F5; the
  // two OVERRIDING keys are still the point of the test.
  clockOut(path, 'N1', 'done', {}, OK_ENTRY, { ts: 'whenever', role: 'planner', tokens: 1, duration_ms: 2 }, { now: 1755930000 });
  assert.equal(
    text(`${path}.log.jsonl`),
    disk('{"briefed": false, "duration_ms": 2, "role": "planner", "status": "done", "tokens": 1, "ts": "whenever", "unit": "N1"}\n'),
  );
  rmSync(root, { recursive: true, force: true });
});

test('the timestamp is UTC at SECOND precision, floored — toISOString would add `.000`', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  clockOut(path, 'N1', 'done', {}, OK_ENTRY, null, { now: 1755930000.999 });
  assert.match(text(`${path}.log.jsonl`), /"ts": "2025-08-23T06:20:00Z"/);
  rmSync(root, { recursive: true, force: true });
});

test('the cursor advances to the first non-terminal unit in PLAN order, ignoring depends_on', () => {
  const root = fresh();
  const doc = checkpointDocument();
  doc.plan.units.push({ id: 'N3', title: 't3', brief_path: 'b3.md', status: 'todo', role: 'planner', depends_on: [], verify: 'v3' });
  doc.plan.units[1].status = 'done';
  const path = writeCheckpoint(root, doc);
  assert.equal(js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, null, { now: 1 })).cursor, 'N3');
  // With nothing left, the cursor STAYS on the unit that just closed.
  assert.equal(js(clockOut(path, 'N3', 'done', {}, { unit: 'N3', outcome: 'done' }, null, { now: 2 })).cursor, 'N3');
  rmSync(root, { recursive: true, force: true });
});

test('the handoff patch is a SHALLOW merge that keeps each existing key in its slot', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  clockOut(path, 'N1', 'done', { next_action: 'next thing', do_not: ['x'] }, OK_ENTRY, null, { now: 1 });
  const written = read(path);
  assert.ok(
    written.includes('"handoff": {\n    "next_action": "next thing",\n    "open_questions": [],\n    "do_not": [\n      "x"\n    ]\n  }'),
    `handoff key order changed:\n${written.slice(written.indexOf('"handoff"'))}`,
  );
  rmSync(root, { recursive: true, force: true });
});

test('history is a 5-entry ring: the oldest falls off, and the file never grows a sixth', () => {
  const root = fresh();
  const doc = checkpointDocument();
  doc.history = [1, 2, 3, 4, 5].map((n) => ({ unit: `old${n}`, outcome: 'done' }));
  const path = writeCheckpoint(root, doc);
  clockOut(path, 'N1', 'done', {}, { unit: 'N1', outcome: 'done', notes: 'kept' }, null, { now: 1 });
  const history = JSON.parse(text(path)).history;
  assert.equal(history.length, HISTORY_RING_SIZE);
  assert.deepEqual(history.map((h) => h.unit), ['old2', 'old3', 'old4', 'old5', 'N1']);
  rmSync(root, { recursive: true, force: true });
});

test('clock_out only accepts the cursor unit', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  assert.deepEqual(js(clockOut(path, 'N2', 'done', {}, OK_ENTRY, null, { now: 1 })), {
    result: 'error',
    reason: 'unit N2 is not the cursor unit N1',
  });
  assert.deepEqual(js(clockOut(path, 'ZZ', 'done', {}, OK_ENTRY, null, { now: 1 })), {
    result: 'error',
    reason: 'unit ZZ is not in the plan',
  });
  rmSync(root, { recursive: true, force: true });
});

// ------------------------------------------- validate before writing, write nothing after

test('a schema refusal writes NOTHING — not a partial checkpoint, not a log line', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const before = bytes(path);
  // `handoff` is additionalProperties:false and allows only next_action/open_questions/do_not
  // and, since job50 J50-5, `notes`. The unknown key here was `notes` until J50-5 legalised
  // it and this test started clocking out for real — the same vacuous-gate defect J50-6
  // found in the conformance suite, in a second home. `note`, one letter off, is unknown.
  const answer = js(clockOut(path, 'N1', 'done', { note: 'nope' }, OK_ENTRY, null, { now: 1 }));
  assert.deepEqual(answer, {
    result: 'error',
    reason: "refused to write: JSON does not match schema at 'handoff': Additional properties are not allowed ('note' was unexpected)",
  });
  assert.deepEqual(bytes(path), before, 'the checkpoint is byte-unchanged');
  // The log append WOULD have succeeded — the directory is writable and the very same call
  // with a legal patch writes a line — and it still did not happen.
  assert.equal(existsSync(`${path}.log.jsonl`), false, 'no log line either');
  assert.equal(existsSync(`${path}.tmp`), false, 'no temp file left behind');
  assert.equal(js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, null, { now: 1 })).result, 'ok');
  assert.equal(existsSync(`${path}.log.jsonl`), true, 'which proves the log append was available');
  rmSync(root, { recursive: true, force: true });
});

test('the history ring items require `unit` and `outcome`, and the refusal names the index', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const before = bytes(path);
  assert.deepEqual(js(clockOut(path, 'N1', 'done', {}, { outcome: 'done' }, null, { now: 1 })), {
    result: 'error',
    reason: "refused to write: JSON does not match schema at 'history/0': 'unit' is a required property",
  });
  assert.deepEqual(bytes(path), before);
  assert.equal(existsSync(`${path}.log.jsonl`), false);
  rmSync(root, { recursive: true, force: true });
});

test('a status outside the unit enum is refused, and the unit status is not left mutated on disk', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const before = bytes(path);
  const answer = js(clockOut(path, 'N1', 'finished', {}, OK_ENTRY, null, { now: 1 }));
  assert.equal(answer.result, 'error');
  assert.ok(answer.reason.startsWith("refused to write: JSON does not match schema at 'plan/units/0/status':"));
  assert.deepEqual(bytes(path), before);
  rmSync(root, { recursive: true, force: true });
});

/**
 * Put a directory into a state and MEASURE whether the OS honoured it, the way
 * `withUnlistable` does in test/store.test.mjs. `chmod` is inert on a directory on Windows
 * and a root uid bypasses the mode bits, so the scenario silently does not exist there —
 * MEASURED on windows-latest, run 32644269451: the clock-out answered `ok` where this test
 * wanted `error`, because the write it was supposed to be refused had simply succeeded.
 * A bare `skipif` would have hidden that; saying it out loud prices what stops being
 * measured, per RB-P51.
 */
function withUnwritable(
  dir,
  t,
  unmeasured = 'the ORDER of the two writes — that the accounting log line is ' +
    'committed before the checkpoint is attempted, and that the refusal names which of ' +
    'the two got out. Nothing else in this file reaches that ordering.',
) {
  chmodSync(dir, 0o555);
  const probe = join(dir, '.probe');
  try {
    writeFileSync(probe, 'x');
    rmSync(probe, { force: true });
  } catch {
    return true;
  }
  chmodSync(dir, 0o755);
  t.diagnostic(
    `NOT MEASURED: this platform wrote into ${dir} at mode 0o555 anyway (Windows, where ` +
      'chmod is inert on a directory, or a uid that bypasses the mode bits). What goes ' +
      `unchecked here is ${unmeasured}`,
  );
  return false;
}

test('an unwritable checkpoint directory refuses AFTER the log line, and says so', (t) => {
  const root = fresh();
  const inner = join(root, 'ro');
  mkdirSync(inner);
  const path = writeCheckpoint(inner);
  if (!withUnwritable(inner, t)) {
    rmSync(root, { recursive: true, force: true });
    return;
  }
  try {
    const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, null, { now: 1 }));
    assert.equal(answer.result, 'error');
    assert.ok(
      answer.reason.startsWith('accounting log unwritable, checkpoint untouched: [Errno 13]') ||
        answer.reason.startsWith('checkpoint unwritable, last log line uncommitted: [Errno 13]'),
      answer.reason,
    );
    assert.equal(existsSync(`${path}.tmp`), false, 'the temp file is unlinked on the way out');
  } finally {
    chmodSync(inner, 0o755);
    rmSync(root, { recursive: true, force: true });
  }
});
// --------------------------------------------- AS-2: the role/model check at clock_out
//
// `job.roles` (J46-7) maps a unit role to the model identifiers a session in that role may
// report; J46-8 made clock_out refuse a mismatch in runtime-py and this is the other half.
// The SENTENCES ARE PINNED AS TEXT, byte-for-byte what `runtime-py` renders, because the
// rule lives in one place per runtime: the differential half of the harness compares Node
// to Python and would stay green through a change made to BOTH (measured twice in job46 —
// on a reverted default, and on the schema's own `propertyNames`). A per-side literal is
// the only thing that turns red here.
//
// The fixture's cursor unit N1 is the implementer and N2 is the reviewer, and the two roles
// deliberately get DIFFERENT lists: a map whose roles all allow the same models cannot tell
// a per-role lookup from a lookup that reads whichever entry it finds first.

const ROLES = { implementer: ['claude-sonnet-5', 'claude-opus-5'], reviewer: ['claude-opus-5'] };
/**
 * The orchestrator's accounting as the tool receives it — `haiku` is on nobody's list.
 * `duration` beside `duration_ms` ON PURPOSE (job50/F5): the schema requires the pair
 * `tokens` + `duration_ms` and lets any other key through, and the fixture carries an odd
 * key so a pass-through that stopped passing would show here.
 */
const ACCOUNTING = { tokens: 1234, duration_ms: 88200, duration: 88.2, model: 'haiku' };
const withRoles = (roles = ROLES) => {
  const doc = checkpointDocument();
  doc.job.roles = roles;
  return doc;
};
const logLine = (path) => JSON.parse(read(`${path}.log.jsonl`).split('\n').filter(Boolean).pop());

test('clock_out refuses a model the role is not allowed, and the refused path writes NOTHING', () => {
  const root = fresh();
  const path = writeCheckpoint(root, withRoles());
  const before = bytes(path);
  const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 }));
  assert.deepEqual(answer, {
    result: 'error',
    reason:
      'unit N1 in role implementer reported model haiku, which job.roles.implementer ' +
      'does not allow: claude-sonnet-5, claude-opus-5',
  });
  // The check sits BEFORE the log-then-commit pair, so there is no orphan accounting line
  // claiming a model that was rejected. Asserting the file does not EXIST is what catches a
  // check moved below the append; asserting `result === 'error'` would not.
  assert.deepEqual(bytes(path), before, 'the checkpoint is byte-unchanged');
  assert.equal(existsSync(`${path}.log.jsonl`), false, 'no accounting line was appended');
  assert.equal(existsSync(`${path}.tmp`), false, 'no temp file left behind');
  assert.equal(js(clockIn(path)).unit.id, 'N1', 'the cursor never moved');
  // And the append WOULD have worked — the same call with an allowed model writes one.
  assert.equal(js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, { ...ACCOUNTING, model: 'claude-opus-5' }, { now: 1 })).result, 'ok');
  assert.equal(existsSync(`${path}.log.jsonl`), true, 'which proves the log append was available');
  rmSync(root, { recursive: true, force: true });
});

test('the allowed list is rendered in CHECKPOINT order, not sorted', () => {
  const root = fresh();
  // `zzz-last` before `aaa-first` is as far from sorted as two entries get, so a `sorted()`
  // on either side shows up here. A map already in alphabetical order cannot state this
  // property at all — which is exactly why runtime-py's own fixture could not fail, and why
  // J46-10 added the mirror there (`ROLES` above is non-alphabetical for the same reason,
  // but two entries one swap apart is a weaker witness than this one).
  const path = writeCheckpoint(root, withRoles({ implementer: ['zzz-last', 'aaa-first'] }));
  assert.equal(
    js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })).reason,
    'unit N1 in role implementer reported model haiku, which job.roles.implementer does not allow: zzz-last, aaa-first',
  );
  rmSync(root, { recursive: true, force: true });
});

test('a model ON the role’s list clocks out, and the accounting line keeps it', () => {
  const root = fresh();
  const path = writeCheckpoint(root, withRoles());
  const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, { ...ACCOUNTING, model: 'claude-sonnet-5' }, { now: 1 }));
  assert.equal(answer.result, 'ok');
  assert.equal(answer.cursor, 'N2');
  assert.equal(logLine(path).model, 'claude-sonnet-5');
  rmSync(root, { recursive: true, force: true });
});

test('the model compares EXACTLY: `claude-opus-5[1m]` is not `claude-opus-5`', () => {
  const root = fresh();
  // The standing ruling: no normalisation, no prefix match, no strip-the-brackets rule.
  // Sibling jobs on this machine log `claude-opus-5[1m]` and the map lists `claude-opus-5`;
  // those are different strings, and this case is pinned as a REFUSAL so that any future
  // attempt at a fuzzy compare turns it red.
  const path = writeCheckpoint(root, withRoles());
  const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, { model: 'claude-opus-5[1m]' }, { now: 1 }));
  assert.equal(answer.result, 'error');
  assert.ok(answer.reason.startsWith('unit N1 in role implementer reported model claude-opus-5[1m], which'), answer.reason);
  assert.equal(existsSync(`${path}.log.jsonl`), false);
  rmSync(root, { recursive: true, force: true });
});

test('a model that is not a string is rendered by `str()`, not by reaching for the tag', () => {
  const root = fresh();
  // `accounting` carries no schema, so `model` is whatever the orchestrator sent, and
  // Python interpolates it with `str()`. Reaching for the tagged `.v` instead would print
  // `5` for a float and `true` for a bool, and print a list as `[object Object]`. MEASURED
  // against the running CPython: all four of these came back byte-identical from both
  // runtimes. The float arrives TAGGED because that is the MCP path — `parseJson` over the
  // wire bytes — where a plain JS `5.0` has already lost the `.0` before this module sees it.
  const path = writeCheckpoint(root, withRoles());
  const rendered = (accounting) =>
    js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, accounting, { now: 1 })).reason.split(' reported model ')[1].split(', which')[0];
  assert.equal(rendered({ model: 5 }), '5');
  assert.equal(rendered({ model: true }), 'True');
  assert.equal(rendered(parseJson('{"model": 5.0}')), '5.0');
  assert.equal(rendered({ model: ['a', 'b'] }), "['a', 'b']");
  assert.equal(existsSync(`${path}.log.jsonl`), false, 'and none of the four wrote a line');
  rmSync(root, { recursive: true, force: true });
});

test('a role the map NAMES must say which model it ran — an absent `model` is refused too', () => {
  const root = fresh();
  // Case 3, J46-8's decision: a rule you escape by omitting a field is enforced only
  // against the honest.
  const path = writeCheckpoint(root, withRoles());
  const before = bytes(path);
  const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1234 }, { now: 1 }));
  assert.deepEqual(answer, {
    result: 'error',
    reason:
      'unit N1 in role implementer reported no model, but job.roles.implementer ' +
      'allows only: claude-sonnet-5, claude-opus-5',
  });
  assert.deepEqual(bytes(path), before);
  assert.equal(existsSync(`${path}.log.jsonl`), false);
  rmSync(root, { recursive: true, force: true });
});

test('no accounting at all, and an explicit `model: null`, get that same refusal', () => {
  const root = fresh();
  const path = writeCheckpoint(root, withRoles());
  // `(accounting or {}).get("model") is None` covers all three spellings in Python; in Node
  // the absent key and the tagged `null` are two different values and both must land here.
  for (const accounting of [null, undefined, { model: null }, {}]) {
    const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, accounting, { now: 1 }));
    assert.equal(answer.result, 'error', `accounting ${JSON.stringify(accounting) ?? 'undefined'}`);
    assert.ok(answer.reason.startsWith('unit N1 in role implementer reported no model, but'), answer.reason);
  }
  assert.equal(existsSync(`${path}.log.jsonl`), false);
  rmSync(root, { recursive: true, force: true });
});

test('the list consulted is the UNIT’s role, not the first entry in the map', () => {
  const root = fresh();
  // N2 is the reviewer, whose list does NOT carry `claude-sonnet-5` even though the
  // implementer's does. Close N1 first so the reviewer is the cursor.
  const path = writeCheckpoint(root, withRoles());
  assert.equal(js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, { ...ACCOUNTING, model: 'claude-opus-5' }, { now: 1 })).result, 'ok');
  const answer = js(clockOut(path, 'N2', 'done', {}, { unit: 'N2', outcome: 'done' }, { model: 'claude-sonnet-5' }, { now: 2 }));
  assert.deepEqual(answer, {
    result: 'error',
    reason: 'unit N2 in role reviewer reported model claude-sonnet-5, which job.roles.reviewer does not allow: claude-opus-5',
  });
  assert.equal(read(`${path}.log.jsonl`).split('\n').filter(Boolean).length, 1, 'still just N1’s line');
  rmSync(root, { recursive: true, force: true });
});

test('a checkpoint with no `job.roles` clocks out exactly as it did before AS-2 existed', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  assert.equal('roles' in checkpointDocument().job, false, 'the fixture must not declare roles');
  const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 }));
  assert.equal(answer.result, 'ok');
  assert.equal(logLine(path).model, 'haiku', 'a model no list anywhere would allow');
  rmSync(root, { recursive: true, force: true });
});

test('a role the map does NOT name is unconstrained — declaring one role forbids nothing else', () => {
  const root = fresh();
  // N1 is the implementer; this map names only the reviewer.
  const path = writeCheckpoint(root, withRoles({ reviewer: ['claude-opus-5'] }));
  assert.equal(js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })).result, 'ok');
  assert.equal(logLine(path).model, 'haiku');
  rmSync(root, { recursive: true, force: true });
});

test('an EMPTY allowed list is not the absent case: the schema refuses the whole checkpoint', () => {
  const root = fresh();
  // These two look alike and are not the same test. An absent role falls through to
  // unconstrained (above); a role declared with `[]` never reaches the model check at all,
  // because `minItems: 1` refuses the document during the read — "a role allowed no model
  // is a typo, not a policy". If this ever answered `ok`, an empty list would have become a
  // silent way to opt out of the rule you just declared.
  const path = writeCheckpoint(root, withRoles({ implementer: [] }));
  assert.deepEqual(js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })), {
    result: 'error',
    reason: "checkpoint invalid: JSON does not match schema at 'job/roles/implementer': [] should be non-empty",
  });
  assert.equal(existsSync(`${path}.log.jsonl`), false);
  rmSync(root, { recursive: true, force: true });
});

/**
 * An asset pack whose checkpoint schema has lost `minItems: 1` on the roles list.
 *
 * The ONLY way to reach the empty-list branch of `modelRefusal`: with the shipped schema
 * `roles: {implementer: []}` is refused during the read and the check is never called.
 * `BANTAMKIT_ASSETS` is the same override `runtime-py` honours, so the two halves of the
 * J46-10 ruling are measured by the same instrument on both sides.
 */
function packWithoutMinItems(root) {
  // `loadSchema`, not a hand-built path: the pack this run would otherwise have used is the
  // one whose copy must be mutated, and a second guess at where it lives is a second way to
  // be wrong. The companion test below is what proves the copy actually took effect.
  const shipped = loadSchema('shiftwork-checkpoint');
  delete shipped.properties.job.properties.roles.additionalProperties.minItems;
  const pack = join(root, 'pack');
  mkdirSync(join(pack, 'schemas'), { recursive: true });
  withShippedTools(pack);
  writeFileSync(join(pack, 'schemas', 'shiftwork-checkpoint.json'), JSON.stringify(shipped), 'utf8');
  return pack;
}

/**
 * Since job50/F5 `clockOut` reads the `shiftwork_clock_out` TOOL asset for the accounting
 * line's shape, so a pack that mutates only the checkpoint schema must still carry the
 * shipped tools/ — or a clock-out that survives the roles gate dies on AssetNotFound
 * instead of reaching the thing these packs exist to measure.
 */
function withShippedTools(pack) {
  cpSync(join(assetsRoot(), 'tools'), join(pack, 'tools'), { recursive: true });
  return pack;
}

/** Run `body` with the asset root pointed at `dir`, and put the environment back. */
function withAssets(dir, body) {
  const before = process.env.BANTAMKIT_ASSETS;
  process.env.BANTAMKIT_ASSETS = dir;
  try {
    return body();
  } finally {
    if (before === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = before;
  }
}

test('an empty allowed list still REFUSES once the schema stops catching it — the check fails closed', () => {
  const root = fresh();
  // RULING 1 (J46-10), decided for J46-9. `if not allowed` read `[]` as unconstrained on
  // both sides, so the day `minItems` moves, an empty list becomes a silent opt-out of the
  // rule the checkpoint just declared — and the schema is a SHARED asset, which the
  // differential half of the harness cannot see change. The DECLARATION is the key: a role
  // the map names is held to its list, and a list of nothing allows nothing. `names` renders
  // empty and the sentence says so, rather than growing a third string to keep in sync.
  const pack = packWithoutMinItems(root);
  const path = writeCheckpoint(root, withRoles({ implementer: [] }));
  const before = bytes(path);
  withAssets(pack, () => {
    assert.deepEqual(js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })), {
      result: 'error',
      reason: 'unit N1 in role implementer reported model haiku, which job.roles.implementer does not allow: ',
    });
    // And reporting no model is not an escape from a list of nothing either.
    assert.deepEqual(js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1 }, { now: 1 })), {
      result: 'error',
      reason: 'unit N1 in role implementer reported no model, but job.roles.implementer allows only: ',
    });
  });
  assert.deepEqual(bytes(path), before);
  assert.equal(existsSync(`${path}.log.jsonl`), false);
  rmSync(root, { recursive: true, force: true });
});

test('the mutated pack is what lets the empty list through — the gate reaches what it claims to check', () => {
  const root = fresh();
  // The companion that keeps the test above honest. Under the SHIPPED schema the same
  // document comes back with the SCHEMA's sentence and never reaches the model check; under
  // the pack it reaches it. Without this pair, a `packWithoutMinItems` that silently failed
  // to load would leave the test above asserting nothing it thinks it asserts.
  const pack = packWithoutMinItems(root);
  const path = writeCheckpoint(root, withRoles({ implementer: [] }));
  const call = () => js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })).reason;
  assert.equal(call(), "checkpoint invalid: JSON does not match schema at 'job/roles/implementer': [] should be non-empty");
  assert.ok(withAssets(pack, call).startsWith('unit N1 in role implementer reported model haiku, which'));
  rmSync(root, { recursive: true, force: true });
});

test('under one pack, an ABSENT role and an EMPTY list are different inputs', () => {
  const root = fresh();
  // Neither is refused by this pack's schema, so the difference that shows is the runtime's
  // own reading: absent means unconstrained, `[]` means nothing is allowed.
  const pack = packWithoutMinItems(root);
  const absent = writeCheckpoint(root, withRoles({ reviewer: ['claude-opus-5'] }), 'absent.json');
  const empty = writeCheckpoint(root, withRoles({ implementer: [] }), 'empty.json');
  withAssets(pack, () => {
    assert.equal(js(clockOut(absent, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })).result, 'ok');
    assert.equal(js(clockOut(empty, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })).result, 'error');
  });
  rmSync(root, { recursive: true, force: true });
});

// --- J47-5: a roles value this code cannot read is not a licence -------------

/**
 * An asset pack whose checkpoint schema no longer says what a roles value IS.
 *
 * `additionalProperties: true` on `job.roles` is the loosest the shared asset could ever
 * drift to, so it is the instrument that reaches every non-list shape at once — where
 * `packWithoutMinItems` above only reaches `[]`. Same `BANTAMKIT_ASSETS` override, and the
 * same one `runtime-py` uses for the twin of this block (J47-4), so both sides of the
 * parity are measured by one instrument.
 */
function packWithUnconstrainedRolesValues(root) {
  const shipped = loadSchema('shiftwork-checkpoint');
  shipped.properties.job.properties.roles.additionalProperties = true;
  const pack = join(root, 'anyroles');
  mkdirSync(join(pack, 'schemas'), { recursive: true });
  withShippedTools(pack);
  writeFileSync(join(pack, 'schemas', 'shiftwork-checkpoint.json'), JSON.stringify(shipped), 'utf8');
  return pack;
}

/**
 * The shapes a `job.roles.<role>` can take that are not a list of model identifiers.
 *
 * The last two are the ones the register and the prep probe both missed and that only an
 * end-to-end probe found: a LIST holding a non-string is a list, so a bare kind test lets
 * it through. MEASURED on this port before the fix, through `clockOut` under the pack
 * above with `model: 'haiku'`:
 *
 *     str, dict, int, null, bool  -> {"result":"ok", …} — status done, cursor CF2,
 *                                    history 1, accounting line WRITTEN. Fail-open.
 *     [5]                         -> refused, but '… does not allow: 5'
 *     ['ok', null]                -> refused, but '… does not allow: ok, None'
 *
 * So the port failed open five ways and mangled the unreadable declaration into the
 * sentence the other two — two different defects, one cause: the arm at `modelRefusal`
 * decided nothing about what `allowed` IS before rendering it.
 */
const NOT_A_MODEL_LIST = [
  ['str', 'claude-opus-5'],
  ['dict', { a: 1 }],
  ['int', 5],
  ['null', null],
  ['bool', true],
  ['list-of-int', [5]],
  ['list-with-a-non-string', ['ok', null]],
];

/** The one sentence, byte-for-byte `runtime-py`'s (shiftwork.py:181-184), for unit N1. */
const UNREADABLE =
  'unit N1 in role implementer cannot clock out: job.roles.implementer ' +
  'is not a list of model identifiers, so it allows no model';

for (const [id, value] of NOT_A_MODEL_LIST) {
  test(`a roles value that is not a list of model names refuses closed — ${id}`, () => {
    const root = fresh();
    // The J46-10 ruling's other half (J47-4). A role the map NAMES is constrained by what
    // it names, and a value this code cannot read as a list of model identifiers names
    // nothing — so it allows nothing. Nothing is written, and the proof is the bytes and
    // the log holding no accounting line, not the `result` field. (Since job50/F6 the
    // `clockIn` below writes its OWN brief line, so "absent file" is no longer the test.)
    const pack = packWithUnconstrainedRolesValues(root);
    const path = writeCheckpoint(root, withRoles({ implementer: value }));
    const before = bytes(path);
    withAssets(pack, () => {
      assert.deepEqual(js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })), {
        result: 'error',
        reason: UNREADABLE,
      });
      // Offering no model is the SAME refusal, not the no-model twin: which model was
      // reported cannot matter when the declaration that would judge it is unreadable.
      assert.deepEqual(js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1 }, { now: 1 })), {
        result: 'error',
        reason: UNREADABLE,
      });
      // Inside the pack: under the SHIPPED schema this document cannot be READ at all, so
      // a `clockIn` out here would report the schema's refusal and prove nothing about the
      // cursor. The status and the cursor are read back from the same relaxed pack that
      // reached the branch.
      const unit = js(clockIn(path)).unit;
      assert.equal(unit.id, 'N1', 'the cursor never moved');
      assert.equal(unit.status, 'todo', 'and the status was never set');
    });
    assert.deepEqual(bytes(path), before, 'the checkpoint is byte-unchanged');
    assert.deepEqual(logLines(path).filter((l) => 'status' in l), [], 'no accounting line was appended');
    assert.deepEqual(logLines(path).map((l) => l.event), ['brief'], 'only clockIn’s own brief line');
    assert.equal(existsSync(`${path}.tmp`), false, 'no temp file left behind');
    rmSync(root, { recursive: true, force: true });
  });
}

test('an unreadable roles value renders NO part of the declaration and names NO type', () => {
  const root = fresh();
  // Two properties of the sentence, both deliberate and both what make it portable.
  // Rendering the value is what mangled it before — `['ok', null]` came back as
  // '… does not allow: ok, None' on this port and raised `TypeError: sequence item 0`
  // on the reference. Naming a type would not port at all: Python would say `int` where
  // Node says `number`, and the two runtimes' sentences must be one string.
  const pack = packWithUnconstrainedRolesValues(root);
  const reason = (value) => {
    const path = writeCheckpoint(root, withRoles({ implementer: value }), `${JSON.stringify(value)}.json`.replace(/[^\w.]/g, '_'));
    return withAssets(pack, () => js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })).reason);
  };
  for (const fragment of ['claude-opus-5', 'c, l, a, u']) {
    assert.equal(reason('claude-opus-5').includes(fragment), false, fragment);
  }
  assert.equal(reason(['ok', null]).includes('ok'), false, 'the list entry is not rendered');
  assert.equal(reason(['ok', null]).includes('None'), false, 'nor is the non-string beside it');
  assert.equal(reason([5]).includes('5'), false, 'nor a number in the list');
  for (const named of ['int', 'number', 'str', 'string', 'dict', 'object', 'bool', 'boolean', 'NoneType', 'null']) {
    assert.equal(reason(5).includes(named), false, `the sentence names no type: ${named}`);
  }
  rmSync(root, { recursive: true, force: true });
});

test('the relaxed pack is what lets a non-list roles value through — the gate reaches it', () => {
  const root = fresh();
  // The companion that keeps the block above honest, `packWithoutMinItems`'s own companion
  // by name: under the SHIPPED schema the same document is refused during the READ and
  // never reaches the model check, so the two refusals are different sentences.
  const pack = packWithUnconstrainedRolesValues(root);
  const path = writeCheckpoint(root, withRoles({ implementer: 5 }));
  const call = () => js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })).reason;
  assert.equal(call(), "checkpoint invalid: JSON does not match schema at 'job/roles/implementer': 5 is not of type 'array'");
  assert.equal(withAssets(pack, call), UNREADABLE);
  rmSync(root, { recursive: true, force: true });
});

test('an empty list is still the J46-10 sentence, not the unreadable-declaration one', () => {
  const root = fresh();
  // `[]` IS a list of model identifiers — an empty one. It stays on the J46-10 branch with
  // the sentence that ruling pinned (trailing space, empty `names`) and does NOT fall into
  // the branch added here. The Node twin of runtime-py's
  // `test_an_empty_list_is_still_the_j46_10_sentence_not_the_unreadable_one`: the boundary
  // has to be pinned from both sides or a later edit can slide the ruled case across it.
  const pack = packWithUnconstrainedRolesValues(root);
  const path = writeCheckpoint(root, withRoles({ implementer: [] }));
  withAssets(pack, () => {
    assert.equal(
      js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })).reason,
      'unit N1 in role implementer reported model haiku, which job.roles.implementer does not allow: ',
    );
    assert.equal(
      js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1 }, { now: 1 })).reason,
      'unit N1 in role implementer reported no model, but job.roles.implementer allows only: ',
    );
  });
  rmSync(root, { recursive: true, force: true });
});

test('the model check runs AFTER the cursor check, so a non-cursor unit keeps its sentence', () => {
  const root = fresh();
  const path = writeCheckpoint(root, withRoles());
  // N2 is the reviewer and `haiku` is not on the reviewer's list either — the refusal that
  // comes back still has to be the structural one that was already there.
  assert.deepEqual(js(clockOut(path, 'N2', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })), {
    result: 'error',
    reason: 'unit N2 is not the cursor unit N1',
  });
  assert.deepEqual(js(clockOut(path, 'ZZ', 'done', {}, OK_ENTRY, ACCOUNTING, { now: 1 })), {
    result: 'error',
    reason: 'unit ZZ is not in the plan',
  });
  assert.equal(existsSync(`${path}.log.jsonl`), false);
  rmSync(root, { recursive: true, force: true });
});

test('AS-2 constrains what a unit REPORTS, so clock_in and status are untouched by it', () => {
  const root = fresh();
  const path = writeCheckpoint(root, withRoles());
  assert.equal(js(clockIn(path)).result, 'brief');
  assert.equal(js(status(path)).result, 'status');
  rmSync(root, { recursive: true, force: true });
});

// ============================================================================ status

test('status counts units in FIRST-SEEN order and never mutates', () => {
  const root = fresh();
  const doc = checkpointDocument();
  doc.plan.units[0].status = 'blocked';
  doc.history = [{ unit: 'N0', outcome: 'done' }];
  const path = writeCheckpoint(root, doc);
  const before = bytes(path);
  assert.equal(
    dumpJson(status(path)),
    '{"result": "status", "cursor": "N1", "units": {"blocked": 1, "todo": 1}, ' +
      '"open_questions": 0, "last_history": {"unit": "N0", "outcome": "done"}}',
  );
  assert.deepEqual(bytes(path), before);
  rmSync(root, { recursive: true, force: true });
});

test('status reports last_history as null on an empty ring, and refuses like the others', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  assert.equal(js(status(path)).last_history, null);
  assert.equal(js(status(join(root, 'gone.json'))).result, 'error');
  rmSync(root, { recursive: true, force: true });
});

// ------------------------------------------ the three the differential caught and this did not

test('an open question outranks an all-terminal plan — order, not coincidence', () => {
  const root = fresh();
  const doc = checkpointDocument();
  for (const u of doc.plan.units) u.status = 'done';
  doc.handoff.open_questions = ['answer before closing'];
  // Both terminal tests are true at once here, and only one of them may answer.
  assert.equal(js(clockIn(writeCheckpoint(root, doc))).result, 'escalate');
  rmSync(root, { recursive: true, force: true });
});

test('read_text folds CRLF before the decoder counts characters', () => {
  const root = fresh();
  const path = join(root, 'crlf.json');
  writeFileSync(path, '{\r\n  "version": 1,\r\n  "job": {,\r\n  }\r\n}\r\n', 'utf8');
  // 28, not 31: three line breaks worth one character each. Without the fold every offset
  // past the first line drifts by one per line, silently, in a sentence the model reads.
  assert.deepEqual(js(clockIn(path)), {
    result: 'error',
    reason: 'checkpoint is not parseable as JSON: Expecting property name enclosed in double quotes: line 3 column 11 (char 28)',
  });
  rmSync(root, { recursive: true, force: true });
});

test('PurePath.suffix: a leading dot is not a suffix, so the temp file is `.json.tmp`', () => {
  assert.equal(pySuffix('/a/.json'), '');
  assert.equal(pySuffix('/a/cp.json'), '.json');
  assert.equal(pySuffix('/a/cp.a.json'), '.json');
  assert.equal(pySuffix('/a/cp.'), '');
  assert.equal(pySuffix('/a/cp'), '');
  // Which is the whole reason clock_out writes `path.with_suffix(path.suffix + ".tmp")`
  // rather than appending: `cp.json` gets `cp.json.tmp`, and `.json` gets `.json.tmp`.
  const root = fresh();
  const path = join(root, '.json');
  writeFileSync(path, `${JSON.stringify(checkpointDocument(), null, 2)}\n`, 'utf8');
  mkdirSync(`${path}.tmp`);
  const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, null, { now: 1 }));
  // Opening a directory for WRITE goes through the C runtime, not the Win32 API: CPython
  // reports `[Errno 13] Permission denied` there where libuv says `EISDIR`. MEASURED,
  // run 32646521489, over six consecutive conformance cases of this exact shape.
  const isdir = process.platform === 'win32'
    ? '[Errno 13] Permission denied'
    : '[Errno 21] Is a directory';
  assert.equal(
    answer.reason,
    `checkpoint unwritable, last log line uncommitted: ${isdir}: ${asRepr(`${path}.tmp`)}`,
  );
  rmSync(root, { recursive: true, force: true });
});

test('os.replace prints BOTH names: OSError.filename2 is not decoration', () => {
  const root = fresh();
  const src = join(root, 'a.tmp');
  writeFileSync(src, 'x', 'utf8');
  const dst = join(root, 'missing', 'b.json');
  assert.throws(() => pyReplace(src, dst), (e) => {
    // `os.replace` is a Win32 call on Windows, so the reference carries a `winerror` and
    // prints `[WinError 3] The system cannot find the path specified` for a destination
    // whose DIRECTORY is missing — 2 is the missing-file arm. MEASURED, run 32646521489.
    const head = process.platform === 'win32'
      ? '[WinError 3] The system cannot find the path specified'
      : '[Errno 2] No such file or directory';
    assert.equal(e.message, `${head}: ${asRepr(src)} -> ${asRepr(dst)}`);
    return true;
  });
  rmSync(root, { recursive: true, force: true });
});

// ------------------------------------------------------- the ruled float at the boundary

test('RULING: a patch that arrived as a JS object cannot say 5.0; one parsed from bytes can', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  // `n` is the odd key whose float is the property; the required pair rides beside it.
  clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1, duration_ms: 1, n: 5.0 }, { now: 1 });
  assert.match(text(`${path}.log.jsonl`), /"n": 5,/, 'the JS-object route loses the decimal point');
  const path2 = writeCheckpoint(root, checkpointDocument(), 'two.json');
  clockOut(path2, 'N1', 'done', {}, OK_ENTRY, parseJson('{"tokens": 1, "duration_ms": 1, "n": 5.0}'), { now: 1 });
  assert.match(text(`${path2}.log.jsonl`), /"n": 5\.0,/, 'the parsed-from-bytes route keeps it');
  rmSync(root, { recursive: true, force: true });
});

// ================================ F5 (job50): the accounting line's shape is a gate

// The refusal's fixed frame, J50-8's, read out of `_accounting_refusal`; what follows it
// is the same `schemaError` rendering the checkpoint refusals use, so the whole sentence
// is one renderer, not a second one.
const REFUSED = 'unit N1 in role implementer reported an accounting line the schema refuses: ';
// The fixture this file used until job50 — the exact shape the ledger census measured 43
// times in this repo: a `duration` spelled its own way and no `duration_ms`.
const OLD_SHAPE = { tokens: 1234, duration: 88.2, model: 'haiku' };
const attempt = (path, accounting, unit = 'N1') =>
  js(clockOut(path, unit, 'done', {}, { unit, outcome: 'done' }, accounting, { now: 1 }));
const logLines = (path) =>
  existsSync(`${path}.log.jsonl`) ? read(`${path}.log.jsonl`).split('\n').filter(Boolean).map((l) => JSON.parse(l)) : [];

test('an accounting line without duration_ms is refused and nothing is written', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const before = bytes(path);
  assert.deepEqual(attempt(path, OLD_SHAPE), {
    result: 'error',
    reason: `${REFUSED}JSON does not match schema at 'accounting': 'duration_ms' is a required property`,
  });
  assert.deepEqual(bytes(path), before, 'the checkpoint is byte-unchanged');
  assert.equal(existsSync(`${path}.log.jsonl`), false, 'no line was ever appended');
  assert.equal(existsSync(`${path}.tmp`), false, 'no temp file left behind');
  assert.equal(js(clockIn(path)).unit.id, 'N1', 'the cursor never moved');
  rmSync(root, { recursive: true, force: true });
});

test('an accounting line without tokens is refused', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const before = bytes(path);
  assert.deepEqual(attempt(path, { duration_ms: 88200, model: 'haiku' }), {
    result: 'error',
    reason: `${REFUSED}JSON does not match schema at 'accounting': 'tokens' is a required property`,
  });
  assert.deepEqual(bytes(path), before);
  assert.deepEqual(logLines(path), []);
  rmSync(root, { recursive: true, force: true });
});

// [id, the line AS JSON TEXT, the pointed detail the sentence ends with]. JSON text and
// `parseJson`, not object literals, so `5.0` reaches the validator as the float it is in
// Python (the JS-object route would hand over `5`). Every detail here is the one the
// Python suite MEASURED against jsonschema 4.26.0; the port reproduces the rendering
// (`True`, `['a', 'b']`, `{'name': 'x'}`, `None`), it does not reason about it.
const WRONG_TYPES = [
  ['tokens-negative', '{"tokens": -1, "duration_ms": 1}', "'accounting/tokens': -1 is less than the minimum of 0"],
  ['tokens-string', '{"tokens": "1234", "duration_ms": 1}', "'accounting/tokens': '1234' is not of type 'integer'"],
  ['tokens-fraction', '{"tokens": 12.5, "duration_ms": 1}', "'accounting/tokens': 12.5 is not of type 'integer'"],
  ['tokens-bool', '{"tokens": true, "duration_ms": 1}', "'accounting/tokens': True is not of type 'integer'"],
  ['duration-negative', '{"tokens": 1, "duration_ms": -5}', "'accounting/duration_ms': -5 is less than the minimum of 0"],
  ['cache-read-negative', '{"tokens": 1, "duration_ms": 1, "cache_read_tokens": -1}', "'accounting/cache_read_tokens': -1 is less than the minimum of 0"],
  ['tool-uses-string', '{"tokens": 1, "duration_ms": 1, "tool_uses": "3"}', "'accounting/tool_uses': '3' is not of type 'integer'"],
  ['note-number', '{"tokens": 1, "duration_ms": 1, "note": 5}', "'accounting/note': 5 is not of type 'string'"],
  ['model-int', '{"tokens": 1, "duration_ms": 1, "model": 5}', "'accounting/model': 5 is not of type 'string'"],
  ['model-float', '{"tokens": 1, "duration_ms": 1, "model": 5.0}', "'accounting/model': 5.0 is not of type 'string'"],
  ['model-bool', '{"tokens": 1, "duration_ms": 1, "model": true}', "'accounting/model': True is not of type 'string'"],
  ['model-list', '{"tokens": 1, "duration_ms": 1, "model": ["a", "b"]}', "'accounting/model': ['a', 'b'] is not of type 'string'"],
  ['model-dict', '{"tokens": 1, "duration_ms": 1, "model": {"name": "x"}}', "'accounting/model': {'name': 'x'} is not of type 'string'"],
  ['model-null', '{"tokens": 1, "duration_ms": 1, "model": null}', "'accounting/model': None is not of type 'string'"],
];

for (const [id, line, detail] of WRONG_TYPES) {
  test(`a named key of the wrong type is refused and nothing is written: ${id}`, () => {
    const root = fresh();
    // No `job.roles` here, so the schema is the only gate a wrong `model` can meet.
    const path = writeCheckpoint(root);
    const before = bytes(path);
    assert.deepEqual(attempt(path, parseJson(line)), {
      result: 'error',
      reason: `${REFUSED}JSON does not match schema at ${detail}`,
    });
    assert.deepEqual(bytes(path), before);
    assert.equal(existsSync(`${path}.log.jsonl`), false);
    rmSync(root, { recursive: true, force: true });
  });
}

test('a whole-number float is an integer to the schema', () => {
  const root = fresh();
  // A MEASURED fact, pinned so the port reproduces it instead of reasoning about it: under
  // the 2020-12 semantics `1234.0` satisfies `integer`, and it is written back as it
  // arrived. Only the parsed-from-bytes route can carry the float this far (see the RULING
  // test above); the JS-object route hands over `1234` and is the trivial half.
  const path = writeCheckpoint(root);
  assert.equal(attempt(path, parseJson('{"tokens": 1234.0, "duration_ms": 88200.0}')).result, 'ok');
  assert.match(text(`${path}.log.jsonl`), /"tokens": 1234\.0\b/, 'written back as it arrived');
  const path2 = writeCheckpoint(root, checkpointDocument(), 'two.json');
  assert.equal(attempt(path2, { tokens: 1234.0, duration_ms: 88200.0 }).result, 'ok');
  rmSync(root, { recursive: true, force: true });
});

test('when two keys are wrong the required one is the sentence', () => {
  const root = fresh();
  // `best_match` prefers the SHALLOWER error: a missing required key (at `accounting`) over
  // a wrong type one level down. A port that reported the first error in document order
  // would say `model` here.
  const path = writeCheckpoint(root);
  assert.equal(
    attempt(path, { tokens: -1, model: 5 }).reason,
    `${REFUSED}JSON does not match schema at 'accounting': 'duration_ms' is a required property`,
  );
  assert.deepEqual(logLines(path), []);
  rmSync(root, { recursive: true, force: true });
});

test('an odd key still passes through beside the required pair', () => {
  const root = fresh();
  // `additionalProperties: true` is J50-7's deliberate choice — a refused key is friction,
  // not safety. Two odd keys, one of them the OLD duration spelling, one a shape the schema
  // never names.
  const path = writeCheckpoint(root);
  assert.equal(attempt(path, { tokens: 1, duration_ms: 2, duration: 88.2, wall: ['x', { y: 1 }] }).result, 'ok');
  const written = logLines(path).pop();
  assert.equal(written.duration, 88.2);
  assert.deepEqual(written.wall, ['x', { y: 1 }]);
  assert.equal(written.tokens, 1);
  assert.equal(written.duration_ms, 2);
  rmSync(root, { recursive: true, force: true });
});

test('accounting null stays legal and writes the base shape — all three spellings of nothing', () => {
  const root = fresh();
  // The container is NOT required (J50-7 kept it optional on purpose). Python has one
  // spelling, `None`; this side has the JS `null`, the omitted argument, and the tagged
  // `{t: 'null'}` the MCP server hands over — every one must skip the shape check.
  const path = writeCheckpoint(root);
  assert.equal(js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, undefined, { now: 1 })).result, 'ok');
  assert.equal(js(clockOut(path, 'N2', 'done', {}, { unit: 'N2', outcome: 'done' }, null, { now: 1 })).result, 'ok');
  const path2 = writeCheckpoint(root, checkpointDocument(), 'two.json');
  assert.equal(js(clockOut(path2, 'N1', 'done', {}, OK_ENTRY, { t: 'null' }, { now: 1 })).result, 'ok');
  for (const written of [...logLines(path), ...logLines(path2)]) {
    // `briefed` is the runtime's field (F6), on every line — a null line included.
    assert.deepEqual(Object.keys(written).sort(), ['briefed', 'role', 'status', 'ts', 'unit']);
  }
  rmSync(root, { recursive: true, force: true });
});

test('a non-string model gets the ROLES sentence when the role is named — the order, decided', () => {
  const root = fresh();
  // J50-8's ruling: the roles gate runs first and keeps its sentence, whether or not the
  // rest of the line is well-formed. The schema's `model: string` fires only when the roles
  // gate is silent (the WRONG_TYPES rows above have no `job.roles`).
  const path = writeCheckpoint(root, withRoles());
  const before = bytes(path);
  const rolesSentence =
    'unit N1 in role implementer reported model 5, which job.roles.implementer does not allow: claude-sonnet-5, claude-opus-5';
  // the line is ALSO missing the required pair — the roles gate still speaks first
  assert.equal(attempt(path, { model: 5 }).reason, rolesSentence);
  // and a line that is otherwise well-formed gets the same sentence
  assert.equal(attempt(path, { tokens: 1, duration_ms: 1, model: 5 }).reason, rolesSentence);
  assert.deepEqual(bytes(path), before);
  assert.deepEqual(logLines(path), []);
  rmSync(root, { recursive: true, force: true });
});

test('a well-formed model on the list then meets the shape check', () => {
  const root = fresh();
  // After a roles PASS the shape check still runs: a listed model on a line with no
  // `duration_ms` is refused by the schema, not waved through by the roles gate.
  const path = writeCheckpoint(root, withRoles());
  const before = bytes(path);
  assert.equal(
    attempt(path, { tokens: 1, model: 'claude-sonnet-5' }).reason,
    `${REFUSED}JSON does not match schema at 'accounting': 'duration_ms' is a required property`,
  );
  assert.deepEqual(bytes(path), before);
  assert.deepEqual(logLines(path), []);
  assert.equal(attempt(path, { tokens: 1, duration_ms: 1, model: 'claude-sonnet-5' }).result, 'ok');
  rmSync(root, { recursive: true, force: true });
});

test('the shape check runs after the cursor check', () => {
  const root = fresh();
  // Same ordering ruling as the roles gate: a non-cursor unit is refused for being
  // non-cursor, whatever its accounting looks like.
  const path = writeCheckpoint(root);
  assert.deepEqual(attempt(path, OLD_SHAPE, 'N2'), { result: 'error', reason: 'unit N2 is not the cursor unit N1' });
  assert.deepEqual(logLines(path), []);
  rmSync(root, { recursive: true, force: true });
});

test('the shape check runs before any mutation is validated', () => {
  const root = fresh();
  // A history entry the checkpoint schema would refuse (`refused to write: …`) AND a bad
  // accounting line: the accounting sentence wins, because it is taken before the document
  // is mutated at all — not discovered after, over the mutated copy.
  const path = writeCheckpoint(root);
  const before = bytes(path);
  const r = js(clockOut(path, 'N1', 'done', {}, { outcome: 'no unit key' }, OLD_SHAPE, { now: 1 }));
  assert.ok(r.reason.startsWith(REFUSED), r.reason);
  assert.deepEqual(bytes(path), before);
  assert.deepEqual(logLines(path), []);
  // and with a GOOD line the same history entry is what gets refused — the gate above was
  // confirmed to be the accounting check and not this one
  const r2 = js(clockOut(path, 'N1', 'done', {}, { outcome: 'no unit key' }, ACCOUNTING, { now: 1 }));
  assert.ok(r2.reason.startsWith('refused to write: '), r2.reason);
  assert.deepEqual(bytes(path), before);
  rmSync(root, { recursive: true, force: true });
});

/**
 * A full copy of the shipped pack whose `shiftwork_clock_out` asset has lost its `required`
 * list on the accounting object — the instrument that shows the check READS THE ASSET
 * rather than carrying a second copy of the shape.
 */
function packWhoseClockOutAssetRequiresNothing(root) {
  const pack = join(root, 'loose');
  cpSync(assetsRoot(), pack, { recursive: true });
  const assetPath = join(pack, 'tools', 'shiftwork_clock_out.json');
  const asset = JSON.parse(readFileSync(assetPath, 'utf8'));
  const arm = asset.parameters.properties.accounting.anyOf.find((a) => a.type === 'object');
  delete arm.required;
  writeFileSync(assetPath, JSON.stringify(asset), 'utf8');
  return pack;
}

test('the shape is read off the tool asset, not a second copy', () => {
  const root = fresh();
  // The gate is confirmed to reach the thing it checks: with the SHIPPED asset the old
  // shape is refused; under a pack whose asset requires nothing, the same line clocks out.
  // A check that carried its own `required` list would refuse both.
  const path = writeCheckpoint(root);
  assert.equal(attempt(path, OLD_SHAPE).result, 'error');
  const pack = packWhoseClockOutAssetRequiresNothing(root);
  assert.equal(withAssets(pack, () => attempt(path, OLD_SHAPE)).result, 'ok');
  rmSync(root, { recursive: true, force: true });
});

// ============================ J50-9B: a pack that cannot supply the shape allows no line

// The one sentence, read out of `ACCOUNTING_SHAPE_UNREADABLE` in the Python module and
// pinned here as a per-side LITERAL, for the same reason every roles refusal is: the
// differential compares Node to Python and cannot see a change made to both. No path, no
// exception text, no unit id — nothing to interpolate, so nothing to drift per input.
const SHAPE_UNREADABLE =
  "cannot clock out: the shiftwork_clock_out tool asset cannot be read as the " +
  "accounting line's shape, so it allows no accounting line";
/** A well-formed line — the control: under the SHIPPED pack this clocks out. */
const GOOD_LINE = { tokens: 1234, duration_ms: 88200, model: 'claude-opus-5' };

/** The orchestrator's repro: the shipped checkpoint schema and NOTHING else. */
function packWithSchemasOnly(root) {
  const pack = join(root, 'schemas-only');
  mkdirSync(join(pack, 'schemas'), { recursive: true });
  cpSync(join(assetsRoot(), 'schemas', 'shiftwork-checkpoint.json'), join(pack, 'schemas', 'shiftwork-checkpoint.json'));
  return pack;
}

/**
 * The shipped schema plus ONE tool asset holding `content` (raw bytes when given as a
 * Buffer, else JSON) — the present-but-malformed family.
 */
function packWhoseClockOutAssetIs(root, content) {
  const pack = packWithSchemasOnly(root);
  mkdirSync(join(pack, 'tools'));
  const target = join(pack, 'tools', 'shiftwork_clock_out.json');
  if (Buffer.isBuffer(content)) writeFileSync(target, content);
  else writeFileSync(target, JSON.stringify(content), 'utf8');
  return pack;
}

function assertRefusedAndUntouched(path, before, r) {
  assert.deepEqual(r, { result: 'error', reason: SHAPE_UNREADABLE });
  assert.deepEqual(bytes(path), before, 'the checkpoint is byte-unchanged');
  assert.equal(existsSync(`${path}.log.jsonl`), false, 'the log gained no line');
  assert.equal(existsSync(`${path}.tmp`), false, 'no temp file was left');
  assert.equal(js(clockIn(path)).unit.id, 'N1', 'the cursor never moved');
}

test('a pack with no tools dir refuses the line and writes nothing — and the answer is a dict, not a throw', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const pack = packWithSchemasOnly(root);
  const before = bytes(path);
  // The override is what makes this the BROKEN pack and not the vendored one: `assetsRoot`
  // returns `$BANTAMKIT_ASSETS` verbatim, and the pack has no `tools/` at all.
  withAssets(pack, () => {
    assert.equal(assetsRoot(), pack, 'the run reads the trimmed pack, not runtime-ts/assets');
    assert.equal(existsSync(join(assetsRoot(), 'tools')), false, 'and that pack has no tools/');
    assertRefusedAndUntouched(path, before, attempt(path, GOOD_LINE));
  });
  assert.equal(attempt(path, GOOD_LINE).result, 'ok', 'the line was never the problem');
  rmSync(root, { recursive: true, force: true });
});

// MISSING AND MALFORMED ARE ONE CASE. Each row is a different failure of the loader —
// the decoder, the parser, a missing key at each step of the path, a wrong kind at each
// step, no object arm, an arm the validator refuses as a schema — and every one gets the
// one sentence, because the property is one: the shape cannot be read, so the line cannot
// be checked, so it is not allowed.
for (const [id, content] of [
  ['not-json', Buffer.from('{not json')],
  ['not-utf8', Buffer.from([0xff, 0xfe, 0x00])],
  ['no-parameters', { name: 'shiftwork_clock_out' }],
  ['no-accounting', { parameters: { properties: {} } }],
  ['no-anyOf', { parameters: { properties: { accounting: { type: 'object' } } } }],
  ['anyOf-not-a-list', { parameters: { properties: { accounting: { anyOf: 'object' } } } }],
  ['no-object-arm', { parameters: { properties: { accounting: { anyOf: [{ type: 'null' }] } } } }],
  ['arm-is-not-a-schema', { parameters: { properties: { accounting: { anyOf: [{ type: 'object', required: 5 }] } } } }],
  ['parameters-not-a-dict', { parameters: 'yes' }],
]) {
  test(`a present but malformed asset is the same refusal, not a second one — ${id}`, () => {
    const root = fresh();
    const path = writeCheckpoint(root);
    const pack = packWhoseClockOutAssetIs(root, content);
    const before = bytes(path);
    withAssets(pack, () => assertRefusedAndUntouched(path, before, attempt(path, GOOD_LINE)));
    rmSync(root, { recursive: true, force: true });
  });
}

test('a null line never needs the shape, so a trimmed pack can still clock it out', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const pack = packWithSchemasOnly(root);
  const r = withAssets(pack, () => attempt(path, null));
  assert.equal(r.result, 'ok', JSON.stringify(r));
  assert.equal(logLines(path).at(-1).unit, 'N1');
  rmSync(root, { recursive: true, force: true });
});

test('the unreadable shape refusal runs after the roles gate', () => {
  const root = fresh();
  const path = writeCheckpoint(root, checkpointDocument({ job: { ...checkpointDocument().job, roles: { implementer: ['claude-opus-5'] } } }));
  const pack = packWithSchemasOnly(root);
  const r = withAssets(pack, () => attempt(path, { ...GOOD_LINE, model: 'haiku' }));
  assert.ok(r.reason.startsWith('unit N1 in role implementer reported model haiku, which'), r.reason);
  assert.deepEqual(logLines(path), []);
  rmSync(root, { recursive: true, force: true });
});

test('the unreadable shape refusal runs after the cursor check', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const pack = packWithSchemasOnly(root);
  const r = withAssets(pack, () => attempt(path, GOOD_LINE, 'N2'));
  assert.deepEqual(r, { result: 'error', reason: 'unit N2 is not the cursor unit N1' });
  assert.deepEqual(logLines(path), []);
  rmSync(root, { recursive: true, force: true });
});

test('the sentence is the module’s constant and interpolates nothing', async () => {
  const { ACCOUNTING_SHAPE_UNREADABLE } = await import(new URL('shiftwork.js', dist));
  assert.equal(ACCOUNTING_SHAPE_UNREADABLE, SHAPE_UNREADABLE);
  assert.ok(!SHAPE_UNREADABLE.includes('{') && !SHAPE_UNREADABLE.includes('/'), 'no format slot, no path');
});

// ------------------------------------------ job50/F6: the ledger records that a brief was issued
//
// Before this, nothing linked clock_in to clock_out: the only trace of a unit run without a
// brief was a self-reported `"executed_by": "orchestrator-inline"`. Now `clockIn` appends a
// `{"event": "brief", ...}` line and `clockOut` reads it back into `briefed` — and NEVER
// refuses on it. The line shape is read out of `runtime-py/src/bantamkit/shiftwork.py`
// (`_record_brief`) and pinned here as bytes; the differential half is every
// `session/*/log` case in `tools/conformance/suites/shiftwork.mjs`.

const { BRIEF_EVENT } = await import(new URL('shiftwork.js', dist));
const briefLine = (role, ts, unit) => `{"event": "brief", "role": "${role}", "ts": "${ts}", "unit": "${unit}"}\n`;

test('clock_in appends ONE brief line — `{"event", "role", "ts", "unit"}`, sorted, no `status`', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const answer = js(clockIn(path, { now: 1755930000.9 }));
  assert.equal(answer.result, 'brief');
  assert.equal(BRIEF_EVENT, 'brief');
  // The verbatim shape: keys sorted the way every ledger line is written, the clock floored.
  assert.equal(text(`${path}.log.jsonl`), disk(briefLine('implementer', '2025-08-23T06:20:00Z', 'N1')));
  const line = logLines(path)[0];
  assert.deepEqual(Object.keys(line).sort(), ['event', 'role', 'ts', 'unit']);
  // Without a clock the line is stamped from `Date.now()` in the same UTC second format.
  clockIn(path);
  const lines = logLines(path);
  assert.equal(lines.length, 2, 'one line per call, appended');
  assert.match(lines[1].ts, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/);
  rmSync(root, { recursive: true, force: true });
});

test('clock_in refusals — escalate, success, error — record no brief line', () => {
  const root = fresh();
  const questions = checkpointDocument();
  questions.handoff.open_questions = ['who owns the deploy key?'];
  const done = checkpointDocument();
  for (const unit of done.plan.units) unit.status = 'done';
  const dangling = checkpointDocument();
  dangling.plan.cursor = 'N99';
  for (const [name, doc, expected] of [
    ['q.json', questions, 'escalate'],
    ['d.json', done, 'success'],
    ['c.json', dangling, 'escalate'],
  ]) {
    const path = writeCheckpoint(root, doc, name);
    assert.equal(js(clockIn(path, { now: 1 })).result, expected);
    assert.equal(existsSync(`${path}.log.jsonl`), false, `${name}: a refusal issued nothing`);
  }
  const broken = join(root, 'e.json');
  writeFileSync(broken, '{not json', 'utf8');
  assert.equal(js(clockIn(broken, { now: 1 })).result, 'error');
  assert.equal(existsSync(`${broken}.log.jsonl`), false);
  rmSync(root, { recursive: true, force: true });
});

test('a clock-out after a brief writes `briefed: true`, and the accounting still passes beside it', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  clockIn(path, { now: 1755930000 });
  const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1234, duration_ms: 88200 }, { now: 1755930001 }));
  assert.equal(answer.result, 'ok');
  const lines = logLines(path);
  assert.equal(lines.length, 2);
  assert.equal(lines[0].event, 'brief');
  assert.equal(lines[1].briefed, true);
  assert.equal(lines[1].status, 'done');
  assert.equal(lines[1].tokens, 1234);
  // the bytes of the accounting line, `briefed` sorting first as `b` < `d`
  assert.equal(
    text(`${path}.log.jsonl`),
    disk(briefLine('implementer', '2025-08-23T06:20:00Z', 'N1') +
      '{"briefed": true, "duration_ms": 88200, "role": "implementer", "status": "done", "tokens": 1234, ' +
      '"ts": "2025-08-23T06:20:01Z", "unit": "N1"}\n'),
  );
  rmSync(root, { recursive: true, force: true });
});

test('a clock-out WITHOUT a brief records `briefed: false` and never refuses — F6 records', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1234, duration_ms: 88200 }, { now: 1 }));
  assert.equal(answer.result, 'ok');
  assert.equal(answer.cursor, 'N2');
  const lines = logLines(path);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].briefed, false);
  assert.equal(JSON.parse(read(path)).plan.cursor, 'N2', 'the checkpoint committed');
  rmSync(root, { recursive: true, force: true });
});

test('`briefed` is written on a null accounting line too — it is the runtime’s field', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  clockIn(path, { now: 1 });
  clockOut(path, 'N1', 'done', {}, OK_ENTRY, null, { now: 2 });
  const line = logLines(path).at(-1);
  assert.deepEqual(Object.keys(line).sort(), ['briefed', 'role', 'status', 'ts', 'unit']);
  assert.equal(line.briefed, true);
  rmSync(root, { recursive: true, force: true });
});

test('two briefs before one clock-out is a relaunch: TWO lines, and the clock-out is briefed', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  assert.equal(js(clockIn(path, { now: 1 })).unit.id, 'N1');
  assert.equal(js(clockIn(path, { now: 2 })).unit.id, 'N1');
  clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1, duration_ms: 1 }, { now: 3 });
  const lines = logLines(path);
  assert.deepEqual(lines.map((l) => l.event ?? null), ['brief', 'brief', null]);
  assert.equal(lines[2].briefed, true);
  rmSync(root, { recursive: true, force: true });
});

test('a clock-out CONSUMES the brief: brief→blocked→re-run reads false, then brief→done reads true', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const BLOCKED = { unit: 'N1', outcome: 'blocked' };
  clockIn(path, { now: 1 });
  clockOut(path, 'N1', 'blocked', {}, BLOCKED, null, { now: 2 });
  clockOut(path, 'N1', 'blocked', {}, BLOCKED, null, { now: 3 }); // the inline re-run, no clock_in
  clockIn(path, { now: 4 });
  clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1, duration_ms: 1 }, { now: 5 });
  const lines = logLines(path);
  assert.deepEqual(lines.map((l) => l.event ?? null), ['brief', null, null, 'brief', null]);
  assert.deepEqual(lines.filter((l) => 'status' in l).map((l) => l.briefed), [true, false, true]);
  rmSync(root, { recursive: true, force: true });
});

test('`briefed` is MEASURED off the ledger — a self-reported `briefed: true` is overwritten, not refused', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1, duration_ms: 1, briefed: true }, { now: 1 }));
  assert.equal(answer.result, 'ok', 'an odd key passes the F5 shape');
  assert.equal(logLines(path).at(-1).briefed, false, 'and the measured value wins');
  rmSync(root, { recursive: true, force: true });
});

test('the briefed reader skips lines it cannot parse or that do not name the unit as a string', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  clockIn(path, { now: 1 });
  // A ledger people edit by hand during recovery: junk, a list, a blank, a unit that is not a
  // string (`5 != "N1"` in Python, so it is skipped rather than compared), an accounting line
  // for the OTHER unit — none of them clears N1's brief.
  appendFileSync(`${path}.log.jsonl`, 'not json\n[1, 2]\n\n{"unit": 5, "status": "done"}\n{"unit": "N2", "status": "done"}\n', 'utf8');
  const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1, duration_ms: 1 }, { now: 2 }));
  assert.equal(answer.result, 'ok');
  assert.equal(logLine(path).briefed, true); // `logLine`, not `logLines`: the junk does not parse
  rmSync(root, { recursive: true, force: true });
});

test('a ledger that does not DECODE is not swallowed — `except OSError` is narrow on both sides', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  writeFileSync(`${path}.log.jsonl`, Buffer.from([0x7b, 0xff, 0x7d, 0x0a]));
  // Python: `read_text` raises `UnicodeDecodeError` (a ValueError, not an OSError) out of
  // `clock_out`. The port rethrows the same class for the same reason: what the reference
  // does not swallow, the port does not either.
  assert.throws(
    () => clockOut(path, 'N1', 'done', {}, OK_ENTRY, null, { now: 1 }),
    (e) => e instanceof PyUnicodeDecodeError,
  );
  rmSync(root, { recursive: true, force: true });
});

test('clock_in with a DIRECTORY where the log belongs still returns the brief (portable arm)', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  mkdirSync(`${path}.log.jsonl`);
  const brief = js(clockIn(path, { now: 1 }));
  assert.equal(brief.result, 'brief');
  assert.equal(brief.unit.id, 'N1');
  assert.ok(statSync(`${path}.log.jsonl`).isDirectory(), 'nothing was written anywhere');
  // and the later clock-out's OWN log refusal is unchanged by it
  const answer = js(clockOut(path, 'N1', 'done', {}, OK_ENTRY, null, { now: 2 }));
  assert.equal(answer.result, 'error');
  assert.ok(answer.reason.startsWith('accounting log unwritable, checkpoint untouched: '), answer.reason);
  rmSync(root, { recursive: true, force: true });
});

test('clock_in in a READ-ONLY store costs only the record: the brief returns whole, nothing is written', (t) => {
  const root = fresh();
  const inner = join(root, 'ro');
  mkdirSync(inner);
  const doc = checkpointDocument();
  const path = writeCheckpoint(inner, doc);
  const before = bytes(path);
  // The stronger arm — a genuine permission failure (job48's shape), not a patched function.
  if (!withUnwritable(
    inner,
    t,
    'that a genuinely read-only store costs clock_in nothing but the record: the brief still ' +
      'returns, no exception escapes, no log file appears, and the checkpoint is byte-unchanged. ' +
      'The sibling test with a DIRECTORY where the log belongs still covers the property here.',
  )) {
    rmSync(root, { recursive: true, force: true });
    return;
  }
  let brief;
  try {
    brief = js(clockIn(path, { now: 1 }));
  } finally {
    chmodSync(inner, 0o755);
  }
  assert.equal(brief.result, 'brief');
  assert.equal(brief.unit.id, 'N1');
  assert.deepEqual(brief.invariants, doc.job.constraints, 'the brief is whole');
  assert.equal(existsSync(`${path}.log.jsonl`), false, 'the record is what it cost');
  assert.deepEqual(bytes(path), before);
  // and a clock-out after the store is writable again reads the truth: no brief landed
  clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1, duration_ms: 1 }, { now: 2 });
  assert.equal(logLines(path).at(-1).briefed, false);
  rmSync(root, { recursive: true, force: true });
});

// ================================================== the MCP flavor: planBatches (W5)
//
// The adapter over `workplan.plan` — the Node half of `shiftwork.plan_batches`. It owns
// exactly three decisions (which units are still in the graph, that every unit has
// priority 0, and that the cursor is echoed) and NO graph logic at all; the batching is
// Layer 1's and is gated in `test/workplan.test.mjs` beside its own implementation.
//
// These are the same twelve nodes the reference's `test_shiftwork.py` runs, against the
// same two shipped checkpoints, because the failure this unit exists to avoid is the two
// adapters mapping one checkpoint differently while both cores agree.

/**
 * The two SHIPPED example checkpoints — tracked templates under `tools/shiftwork/`, NOT a
 * live `.shiftwork/` job. The file header's rule is about the latter: a live checkpoint
 * mutates while a job runs. `test/server.test.mjs` already reads the codefix one this way.
 */
const repoShiftwork = join(dirname(dirname(fileURLToPath(import.meta.url))), '..', 'tools', 'shiftwork');
const EXAMPLE_CHECKPOINT = join(repoShiftwork, 'example-checkpoint.json');
const CODEFIX_CHECKPOINT = join(repoShiftwork, 'example-codefix-checkpoint.json');

/**
 * `[checkpoint digest, ledger digest or null]` — the pair a read-only tool must not move.
 *
 * The ledger is in here because it is the surface a "read-only" tool would break FIRST:
 * `clock_in` is also read-only about the CHECKPOINT and still appends a brief line beside
 * it. A hash of the checkpoint alone would call that read-only.
 */
const digests = (path) => [
  createHash('sha256').update(readFileSync(path)).digest('hex'),
  existsSync(`${path}.log.jsonl`)
    ? createHash('sha256').update(readFileSync(`${path}.log.jsonl`)).digest('hex')
    : null,
];

/** The shipped example, as a mutable document. */
const exampleDocument = () => JSON.parse(readFileSync(EXAMPLE_CHECKPOINT, 'utf8'));

test('plan_batches of the codefix chain is four batches of one', () => {
  // CF1 -> CF2 -> CF3 -> CF4, all `todo`: a straight line has nothing to parallelize.
  const root = fresh();
  const path = join(root, 'checkpoint.json');
  writeFileSync(path, readFileSync(CODEFIX_CHECKPOINT, 'utf8'), 'utf8');
  assert.deepEqual(js(planBatches(path)), {
    result: 'plan',
    batches: [['CF1'], ['CF2'], ['CF3'], ['CF4']],
    ready: ['CF1'],
    sequence: ['CF1', 'CF2', 'CF3', 'CF4'],
    width: 1,
    cursor: 'CF1',
  });
  rmSync(root, { recursive: true, force: true });
});

test('a done unit leaves the graph and its edges are satisfied', () => {
  // Marking CF1 done drops it AND resolves CF2's edge into it — otherwise the whole
  // remaining graph would be unplannable the moment the first unit finished.
  const root = fresh();
  const doc = JSON.parse(readFileSync(CODEFIX_CHECKPOINT, 'utf8'));
  doc.plan.units[0].status = 'done';
  doc.plan.cursor = 'CF2';
  const r = js(planBatches(writeCheckpoint(root, doc)));
  assert.deepEqual(r.batches, [['CF2'], ['CF3'], ['CF4']]);
  assert.deepEqual(r.ready, ['CF2']);
  assert.deepEqual(r.sequence, ['CF2', 'CF3', 'CF4']);
  assert.equal(r.cursor, 'CF2');
  rmSync(root, { recursive: true, force: true });
});

test('a dropped unit is satisfied exactly like a done one', () => {
  // `dropped` is terminal for the driver's success test, so it is terminal here too: a
  // unit nobody will ever run cannot be a reason to hold its dependants back.
  const root = fresh();
  const doc = JSON.parse(readFileSync(CODEFIX_CHECKPOINT, 'utf8'));
  doc.plan.units[0].status = 'dropped';
  doc.plan.cursor = 'CF2';
  assert.deepEqual(js(planBatches(writeCheckpoint(root, doc))).batches, [['CF2'], ['CF3'], ['CF4']]);
  rmSync(root, { recursive: true, force: true });
});

test('in_progress and blocked units stay in the graph', () => {
  // The three non-terminal statuses are all still work, so all three still batch.
  const root = fresh();
  const doc = exampleDocument();
  doc.plan.units[0].status = 'in_progress';
  doc.plan.units[1].status = 'blocked';
  const r = js(planBatches(writeCheckpoint(root, doc)));
  assert.deepEqual(r.batches, [['U1'], ['U3'], ['U4']]);
  assert.deepEqual(r.ready, ['U1']);
  rmSync(root, { recursive: true, force: true });
});

test('independent units share one batch and width reports the fan-out', () => {
  // The number the whole design exists to produce: two units that may run at once.
  const root = fresh();
  const doc = exampleDocument();
  doc.plan.units[2].depends_on = ['U1']; // U4 waits for U1, not for U3
  const r = js(planBatches(writeCheckpoint(root, doc)));
  assert.deepEqual(r.batches, [['U3', 'U4']]); // U1 is done and out of the graph
  assert.deepEqual(r.ready, ['U3', 'U4']);
  assert.equal(r.width, 2);
  rmSync(root, { recursive: true, force: true });
});

test('order inside a batch is plan.units order, not sorted', () => {
  // Every unit gets priority 0 — the checkpoint schema has no priority field and this job
  // does not add one — so the tie-break is the order `plan.units` declares, and that is
  // contract. Reversing the declaration reverses the batch; a sorted answer would not
  // move, so this is what distinguishes the two.
  const root = fresh();
  const doc = exampleDocument();
  doc.plan.units[2].depends_on = ['U1'];
  doc.plan.units = [doc.plan.units[0], doc.plan.units[2], doc.plan.units[1]];
  assert.deepEqual(js(planBatches(writeCheckpoint(root, doc))).ready, ['U4', 'U3']);
  rmSync(root, { recursive: true, force: true });
});

test('an all-terminal plan is an empty answer, not a refusal', () => {
  // The same judgement `clock_in` already makes: a finished job is an ANSWER.
  const root = fresh();
  const doc = exampleDocument();
  for (const unit of doc.plan.units) unit.status = 'done';
  const r = js(planBatches(writeCheckpoint(root, doc)));
  assert.equal(r.result, 'plan');
  assert.deepEqual([r.batches, r.ready, r.sequence, r.width], [[], [], [], 0]);
  rmSync(root, { recursive: true, force: true });
});

test('the schema refusal passes through planBatches unchanged', () => {
  // `readValid`'s refusal is returned verbatim, so a caller cannot tell which read-only
  // tool it asked. All three shapes: unparseable, parseable-but-invalid, unreadable.
  const root = fresh();
  const notJson = join(root, 'broken.json');
  writeFileSync(notJson, '{not json at all', 'utf8');
  assert.equal(js(planBatches(notJson)).result, 'error');

  const doc = exampleDocument();
  doc.version = 99;
  const bad = js(planBatches(writeCheckpoint(root, doc, 'bad.json')));
  assert.equal(bad.result, 'error');
  assert.ok(bad.reason.startsWith('checkpoint invalid: '), bad.reason);

  const missing = js(planBatches(join(root, 'nope.json')));
  assert.equal(missing.result, 'error');
  assert.ok(missing.reason.startsWith('checkpoint unreadable'), missing.reason);
  rmSync(root, { recursive: true, force: true });
});

test('a cycle among the remaining units is the core refusal, verbatim', () => {
  // Layer 1 composes the sentence; the adapter neither rewrites nor swallows it. The
  // sentence is pinned as a per-side LITERAL for the reason the module header gives: a
  // string both runtimes copied is invisible to the differential half of the harness.
  const root = fresh();
  const doc = exampleDocument();
  doc.plan.units[1].depends_on = ['U4']; // U3 <-> U4
  assert.deepEqual(js(planBatches(writeCheckpoint(root, doc))), {
    result: 'error',
    reason: 'the graph has a cycle: U3 -> U4 -> U3',
  });
  rmSync(root, { recursive: true, force: true });
});

test('an edge into a unit no longer in the graph is not an unknown dependency', () => {
  // The load-bearing half of "satisfied": U3 depends on U1, U1 is `done` and therefore
  // absent from the nodes handed to Layer 1. If the adapter passed the edge through, the
  // core's unknown-dependency refusal would fire on every checkpoint with a finished unit
  // — which is every checkpoint after the first clock-out.
  const root = fresh();
  const r = js(planBatches(writeCheckpoint(root, exampleDocument())));
  assert.equal(r.result, 'plan');
  assert.deepEqual(r.batches, [['U3'], ['U4']]);
  rmSync(root, { recursive: true, force: true });
});

test('planBatches writes nothing — the checkpoint AND the ledger are byte-unchanged', () => {
  // THE load-bearing test of the design. Without it, "read-only" is a comment.
  //
  // Hashes, not `existsSync`: a ledger line appended to an existing log, or a checkpoint
  // rewritten with the same key order, would both survive a weaker check. The log must
  // still be ABSENT after the first call, which is the state `clock_in` would have changed.
  const root = fresh();
  const path = writeCheckpoint(root, exampleDocument());
  const log = `${path}.log.jsonl`;
  assert.equal(existsSync(log), false);
  const before = digests(path);
  assert.equal(js(planBatches(path)).result, 'plan');
  assert.deepEqual(digests(path), before);
  assert.equal(existsSync(log), false, 'planBatches appended a ledger line beside the checkpoint');

  // And on a checkpoint that ALREADY has a ledger: the bytes of both must not move.
  clockIn(path, { now: 1 });
  assert.equal(existsSync(log), true);
  const withLog = digests(path);
  assert.equal(js(planBatches(path)).result, 'plan');
  assert.deepEqual(digests(path), withLog);
  rmSync(root, { recursive: true, force: true });
});

test('planBatches does not move the repo’s own example checkpoints', () => {
  // Run against the shipped files themselves, at their real paths. A tool that writes only
  // when it CAN — beside a checkpoint in a real tree rather than under the temp directory
  // — would pass every node above and be caught here.
  for (const checkpoint of [EXAMPLE_CHECKPOINT, CODEFIX_CHECKPOINT]) {
    const before = digests(checkpoint);
    assert.equal(js(planBatches(checkpoint)).result, 'plan');
    assert.deepEqual(digests(checkpoint), before, `${checkpoint} moved`);
  }
});
