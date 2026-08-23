/**
 * shiftwork — 78 statements of control flow wrapped around four ways to corrupt a file.
 *
 * THE PROPERTY: given the same checkpoint and the same call, Node writes byte-identical
 * files and returns the identical result object. Three artefacts are at stake — the
 * rewritten checkpoint, the `.log.jsonl` line, and the returned dict — and only the first
 * is ever read back, so a wrong log line is invisible to the code that wrote it.
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
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const { clockIn, clockOut, status, HISTORY_RING_SIZE } = await import(new URL('shiftwork.js', dist));
const { dumpJson, fromJs, parseJson, toJs } = await import(new URL('pyjson.js', dist));
const { pyReplace, pySuffix } = await import(new URL('memory/pyfs.js', dist));

// `realpathSync`: `os.tmpdir()` is not canonical — a `/var` symlink on macOS, the 8.3
// short name on Windows CI. See the note in test/store.test.mjs.
const fresh = () => realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-shiftwork-')));
const bytes = (p) => readFileSync(p);
const text = (p) => readFileSync(p, 'utf8');
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
    reason: `checkpoint unreadable: [Errno 2] No such file or directory: '${join(root, 'nope.json')}'`,
  });
  // `Path(checkpoint)` NORMALIZES before the open, so the errno sentence names the
  // normalized path and not the string the caller passed.
  assert.deepEqual(js(clockIn(`${root}//./nope.json`)), {
    result: 'error',
    reason: `checkpoint unreadable: [Errno 2] No such file or directory: '${join(root, 'nope.json')}'`,
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
  assert.equal(text(path).endsWith('\n}\n'), true, 'indent=2 plus a trailing newline');
  rmSync(root, { recursive: true, force: true });
});

test('the log line is sort_keys=True, one line, appended, and never read back', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  clockOut(path, 'N1', 'done', {}, OK_ENTRY, { tokens: 1, model: 'claude-opus-5[1m]', duration_ms: 2 }, { now: 1755930000.9 });
  const log = text(`${path}.log.jsonl`);
  assert.equal(
    log,
    '{"duration_ms": 2, "model": "claude-opus-5[1m]", "role": "implementer", "status": "done", ' +
      '"tokens": 1, "ts": "2025-08-23T06:20:00Z", "unit": "N1"}\n',
  );
  clockOut(path, 'N2', 'done', {}, { unit: 'N2', outcome: 'done' }, null, { now: 1755930001 });
  assert.equal(text(`${path}.log.jsonl`).split('\n').filter(Boolean).length, 2, 'append, not truncate');
});

test('accounting can OVERRIDE the four keys the record starts with', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  clockOut(path, 'N1', 'done', {}, OK_ENTRY, { ts: 'whenever', role: 'planner' }, { now: 1755930000 });
  assert.equal(text(`${path}.log.jsonl`), '{"role": "planner", "status": "done", "ts": "whenever", "unit": "N1"}\n');
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
  const written = text(path);
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
  // `handoff` is additionalProperties:false and allows only next_action/open_questions/do_not.
  const answer = js(clockOut(path, 'N1', 'done', { notes: 'nope' }, OK_ENTRY, null, { now: 1 }));
  assert.deepEqual(answer, {
    result: 'error',
    reason: "refused to write: JSON does not match schema at 'handoff': Additional properties are not allowed ('notes' was unexpected)",
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
function withUnwritable(dir, t) {
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
      'unchecked here is the ORDER of the two writes — that the accounting log line is ' +
      'committed before the checkpoint is attempted, and that the refusal names which of ' +
      'the two got out. Nothing else in this file reaches that ordering.',
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
  assert.equal(answer.reason, `checkpoint unwritable, last log line uncommitted: [Errno 21] Is a directory: '${path}.tmp'`);
  rmSync(root, { recursive: true, force: true });
});

test('os.replace prints BOTH names: OSError.filename2 is not decoration', () => {
  const root = fresh();
  const src = join(root, 'a.tmp');
  writeFileSync(src, 'x', 'utf8');
  const dst = join(root, 'missing', 'b.json');
  assert.throws(() => pyReplace(src, dst), (e) => {
    assert.equal(e.message, `[Errno 2] No such file or directory: '${src}' -> '${dst}'`);
    return true;
  });
  rmSync(root, { recursive: true, force: true });
});

// ------------------------------------------------------- the ruled float at the boundary

test('RULING: a patch that arrived as a JS object cannot say 5.0; one parsed from bytes can', () => {
  const root = fresh();
  const path = writeCheckpoint(root);
  clockOut(path, 'N1', 'done', {}, OK_ENTRY, { n: 5.0 }, { now: 1 });
  assert.match(text(`${path}.log.jsonl`), /"n": 5,/, 'the JS-object route loses the decimal point');
  const path2 = writeCheckpoint(root, checkpointDocument(), 'two.json');
  clockOut(path2, 'N1', 'done', {}, OK_ENTRY, parseJson('{"n": 5.0}'), { now: 1 });
  assert.match(text(`${path2}.log.jsonl`), /"n": 5\.0,/, 'the parsed-from-bytes route keeps it');
  rmSync(root, { recursive: true, force: true });
});
