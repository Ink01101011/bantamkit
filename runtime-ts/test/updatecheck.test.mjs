/**
 * The update record: where it is read from, what the five states are, and what it never does.
 *
 * The Node half of `runtime-py/tests/test_updatecheck.py`, test for test. Every case there has
 * one here, constructed the same way and asserting the same bytes, because the two runtimes
 * share this record on disk and a state one side reaches that the other does not is a way for
 * them to disagree about a user's install.
 *
 * EVERY STATE HERE IS CONSTRUCTED BY WRITING A RECORD. Both installs on the machine this was
 * written on are 0.35.1, so there is no naturally stale install to point at, and a test that
 * waited for one would be a test that passes on a Tuesday. Nothing below reaches the network
 * either — there is nothing in `updatecheck.ts` that could, and one case asserts exactly that
 * off the source rather than off this sentence.
 *
 * THE HOME IS REDIRECTED IN EVERY CASE THAT TOUCHES A PATH. `updatecheck` derives its path from
 * `homedir()` and nothing else, and `os.homedir()` reads the environment on every call on every
 * platform this ships to — so pointing `HOME`/`USERPROFILE` at a scratch directory makes the
 * redirection total and no case here can read, or notice, the operator's own record. That is
 * asserted inside the helper rather than assumed, the way `test/hostinstall.test.mjs` does it.
 *
 * THE VERSION PAIRS ARE THE AWKWARD ONES ON PURPOSE. `0.35.1` against `0.36.0` is the pair every
 * implementation gets right, including a wrong one, so it is the floor and not the proof. The
 * pair that decides anything is `0.9.0` against `0.10.0`, where a string compare says the index
 * is BEHIND and would print `ahead` over a genuinely stale install.
 */
import assert from 'node:assert/strict';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, isAbsolute, join, relative } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { compareVersions as npmCompareVersions } from '../dist/npminstall.js';
import { PROGRAM as SELFUPDATE_PROGRAM, compareVersions as selfupdateCompareVersions } from '../dist/selfupdate.js';
import {
  KEY,
  PROGRAM,
  RECORD_DIR,
  RECORD_NAME,
  SOURCE_ABSENT,
  SOURCE_RECORD,
  SOURCE_UNREADABLE,
  STATES,
  STATE_AHEAD,
  STATE_AVAILABLE,
  STATE_CURRENT,
  STATE_NEVER,
  STATE_UNREADABLE,
  UPDATE_AHEAD,
  UPDATE_AVAILABLE,
  UPDATE_CURRENT,
  UPDATE_NEVER,
  UPDATE_UNREADABLE,
  compareVersions,
  decide,
  loadRecord,
  readRecord,
  recordPath,
  updateLine,
  updateStatus,
} from '../dist/updatecheck.js';

const SRC = join(dirname(dirname(fileURLToPath(import.meta.url))), 'src', 'updatecheck.ts');

const CHECKED_AT = '2026-09-19T21:04:11Z';
const DATE = '2026-09-19';

/**
 * Run `body` with HOME pointed at a home nobody lives in, carrying the `.bantamkit` a real
 * machine would already have — then put the world back and delete it.
 */
function withHome(body) {
  const root = mkdtempSync(join(tmpdir(), 'bk-updatecheck-'));
  const previous = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  process.env.HOME = root;
  process.env.USERPROFILE = root;
  mkdirSync(join(root, RECORD_DIR));
  try {
    // The isolation, asserted rather than believed: without it every case below would be
    // reading the operator's own record and passing for a reason that is not this code.
    assert.equal(homedir(), root, 'homedir() did not follow HOME; this test would read a real record');
    assert.equal(recordPath(), join(root, RECORD_DIR, RECORD_NAME));
    body(root);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    rmSync(root, { recursive: true, force: true });
  }
}

/** A bare home: no `.bantamkit` at all, which is the state of a machine that installed nothing. */
function withBareHome(body) {
  const root = mkdtempSync(join(tmpdir(), 'bk-updatecheck-bare-'));
  const previous = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  process.env.HOME = root;
  process.env.USERPROFILE = root;
  try {
    assert.equal(homedir(), root, 'homedir() did not follow HOME');
    body(root);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    rmSync(root, { recursive: true, force: true });
  }
}

/** The record, exactly as given — including the shapes no writer would produce. */
function writeRecord(home, text) {
  const path = join(home, RECORD_DIR, RECORD_NAME);
  writeFileSync(path, text);
  return path;
}

/** The well-formed record from the spec: both registries, because they are two. */
function record({ npm = '0.36.0', pypi = '0.36.0', checked_at = CHECKED_AT } = {}) {
  return JSON.stringify({
    checked_at,
    npm: { package: 'bantamkit-mcp', latest: npm },
    pypi: { distribution: 'bantamkit', latest: pypi },
  });
}

// ============================================================ the five sentences
// Golden bytes, spelled out here rather than imported and compared to themselves. The reference
// spells the same five out in `test_the_five_sentences_are_these_bytes`; this case is what
// notices if someone edits one on one side only, before the conformance suite gets a chance to.

test('the five sentences are these bytes', () => {
  assert.equal(UPDATE_NEVER, 'update: never checked.');
  assert.equal(
    UPDATE_AVAILABLE,
    'update: {program} {installed} is running; the package index has {latest} — run ' +
      '`{program} --update`, then reconnect the host.',
  );
  assert.equal(UPDATE_CURRENT, 'update: {program} {installed} is current as of {date}.');
  assert.equal(
    UPDATE_AHEAD,
    'update: {program} {installed} is ahead of the package index, which has {latest}.',
  );
  assert.equal(UPDATE_UNREADABLE, 'update: the update record could not be read.');
});

test('the sentences name the command and never a package', () => {
  // `bantamkit` is the PyPI distribution and `bantamkit-mcp` is the npm package. Only the
  // COMMAND is the same word on both sides, so only the command can appear in a sentence the
  // reference and this file share verbatim. A sentence naming a distribution would be one the
  // port has to change, and a changed sentence is a divergence nobody declared.
  assert.equal(PROGRAM, 'bantamkit-mcp');
  // Equal to `selfupdate`'s, pinned here because `updatecheck.ts` may not IMPORT that module:
  // `test/selfupdate.test.mjs` pins that `cli.ts` is its only importer in `src/`, and this
  // module is reached from `bantamkit_status`. The reference asserts the same equality with
  // `is`, where an import is free.
  assert.equal(PROGRAM, SELFUPDATE_PROGRAM);
  for (const sentence of [UPDATE_NEVER, UPDATE_AVAILABLE, UPDATE_CURRENT, UPDATE_AHEAD, UPDATE_UNREADABLE]) {
    const rendered = sentence
      .replaceAll('{program}', PROGRAM)
      .replaceAll('{installed}', '0.35.1')
      .replaceAll('{latest}', '0.36.0')
      .replaceAll('{date}', DATE);
    // With every occurrence of the COMMAND removed, the PyPI distribution must not be left
    // behind — which is what a sentence naming a package rather than a command would leave.
    assert.ok(!rendered.replaceAll('bantamkit-mcp', '').includes('bantamkit'), rendered);
  }
});

// ============================================================ the five states

test('no record is never checked', () => {
  withHome(() => {
    const status = updateStatus('0.35.1');
    assert.equal(status.state, STATE_NEVER);
    assert.equal(status.line, 'update: never checked.');
  });
});

test('running behind the index says run --update and reconnect', () => {
  withHome((home) => {
    writeRecord(home, record({ npm: '0.36.0' }));
    const status = updateStatus('0.35.1');
    assert.equal(status.state, STATE_AVAILABLE);
    assert.equal(
      status.line,
      'update: bantamkit-mcp 0.35.1 is running; the package index has 0.36.0 — run ' +
        '`bantamkit-mcp --update`, then reconnect the host.',
    );
  });
});

test('running the index version is current as of the recorded date', () => {
  withHome((home) => {
    writeRecord(home, record({ npm: '0.35.1' }));
    const status = updateStatus('0.35.1');
    assert.equal(status.state, STATE_CURRENT);
    assert.equal(status.line, 'update: bantamkit-mcp 0.35.1 is current as of 2026-09-19.');
  });
});

test('running ahead of the index says so', () => {
  withHome((home) => {
    writeRecord(home, record({ npm: '0.35.1' }));
    const status = updateStatus('0.36.0');
    assert.equal(status.state, STATE_AHEAD);
    assert.equal(
      status.line,
      'update: bantamkit-mcp 0.36.0 is ahead of the package index, which has 0.35.1.',
    );
  });
});

test('a record that is not JSON is unreadable', () => {
  withHome((home) => {
    writeRecord(home, '<html>captive portal</html>');
    const status = updateStatus('0.35.1');
    assert.equal(status.state, STATE_UNREADABLE);
    assert.equal(status.line, 'update: the update record could not be read.');
  });
});

test('the ten ordering that a string compare gets backwards', () => {
  // `0.9.0` against `0.10.0`: string order says the index is behind. It is ahead. This is the
  // pair `versionKey` exists for, and the reason this module imports that comparator instead of
  // writing a second one. An implementation that compared strings would print `ahead` at a
  // genuinely stale install and the operator would never update.
  withHome((home) => {
    writeRecord(home, record({ npm: '0.10.0' }));
    assert.equal(updateStatus('0.9.0').state, STATE_AVAILABLE);
    writeRecord(home, record({ npm: '0.9.0' }));
    assert.equal(updateStatus('0.10.0').state, STATE_AHEAD);
  });
});

test('padding makes an unpadded release agree', () => {
  // `0.36` and `0.36.0` are one release on either registry, so they are `current`.
  withHome((home) => {
    writeRecord(home, record({ npm: '0.36' }));
    assert.equal(updateStatus('0.36.0').state, STATE_CURRENT);
  });
});

test('there is no second comparator', () => {
  // The ordering is the shared `compareVersions` itself, not a copy that agrees today. It comes
  // from `npminstall.ts`, which is where it lives; `selfupdate.ts` re-exports the same binding,
  // so all three are one function and this asserts it by identity.
  assert.equal(compareVersions, npmCompareVersions);
  assert.equal(compareVersions, selfupdateCompareVersions);

  // And structurally, the way the reference walks its own AST: nothing comparator-shaped is
  // DEFINED in this module. Comments are stripped first, because the docstring explains at
  // length that it does not define one and a gate that reddens on its own explanation is a gate
  // whoever hits it next deletes.
  const source = code(readFileSync(SRC, 'utf8'));
  for (const forbidden of ['function compareVersions', 'versionKey', 'localeCompare', 'semver']) {
    assert.ok(!source.includes(forbidden), `\`${forbidden}\` appears in updatecheck.ts's CODE`);
  }

  // RED-PROOF ON A SAMPLE: the first is the mutation this gate exists for, the second is the
  // prose that must stay green.
  assert.ok(code('export function compareVersions(a, b) { return 0; }').includes('function compareVersions'));
  assert.ok(!code('/** `compareVersions` is imported, not defined: no versionKey here. */\n').includes('versionKey'));
  assert.ok(!code('  // versionKey is never written in this module\n').includes('versionKey'));
});

// ============================================================ this runtime reads the npm key

test('node reads npm and python reads pypi', () => {
  // The divergence row, pinned: the two keys are asked separately and can disagree. A record
  // whose registries disagree is not hypothetical — job56 shipped exactly one (npm at a stale
  // dist while PyPI was current). If this reader took whichever key it found first, that day's
  // record would have told a Node operator the wrong thing.
  withHome((home) => {
    writeRecord(home, record({ npm: '0.35.1', pypi: '0.99.0' }));
    assert.equal(KEY, 'npm');
    assert.equal(updateStatus('0.35.1').state, STATE_CURRENT);
    assert.equal(updateStatus('0.35.1', 'pypi').state, STATE_AVAILABLE);
  });
});

// ============================================================ every malformed shape

const MALFORMED = {
  'not json at all': 'not json at all',
  'empty file': '',
  'whitespace only': '   \n',
  'a json list': '[]',
  'a bare json number': '7',
  'a bare json string': '"0.36.0"',
  'json null': 'null',
  'no key for this runtime': JSON.stringify({ checked_at: CHECKED_AT, pypi: { latest: '0.36.0' } }),
  'the key is not an object': JSON.stringify({ checked_at: CHECKED_AT, npm: '0.36.0' }),
  'the key is a list': JSON.stringify({ checked_at: CHECKED_AT, npm: ['0.36.0'] }),
  'no latest in the key': JSON.stringify({ checked_at: CHECKED_AT, npm: { package: 'bantamkit-mcp' } }),
  'latest is null': JSON.stringify({ checked_at: CHECKED_AT, npm: { latest: null } }),
  'latest is a number': JSON.stringify({ checked_at: CHECKED_AT, npm: { latest: 36 } }),
  'latest is empty': JSON.stringify({ checked_at: CHECKED_AT, npm: { latest: '' } }),
  'latest is not a version': JSON.stringify({ checked_at: CHECKED_AT, npm: { latest: 'nightly' } }),
  'latest is v-prefixed': JSON.stringify({ checked_at: CHECKED_AT, npm: { latest: 'v0.36.0' } }),
  'no checked_at': JSON.stringify({ npm: { latest: '0.36.0' } }),
  'checked_at is null': JSON.stringify({ checked_at: null, npm: { latest: '0.36.0' } }),
  'checked_at is a number': JSON.stringify({ checked_at: 1758315851, npm: { latest: '0.36.0' } }),
  'checked_at is prose': JSON.stringify({ checked_at: 'yesterday', npm: { latest: '0.36.0' } }),
  'checked_at is a locale date': JSON.stringify({ checked_at: '19/09/2026', npm: { latest: '0.36.0' } }),
};

for (const shape of Object.keys(MALFORMED).sort()) {
  test(`every malformed shape is unreadable and nothing throws: ${shape}`, () => {
    withHome((home) => {
      writeRecord(home, MALFORMED[shape]);
      const status = updateStatus('0.35.1');
      assert.equal(status.state, STATE_UNREADABLE);
      assert.equal(status.line, 'update: the update record could not be read.');
    });
  });
}

// ============================================================ a UTF-8 BOM
// NOT A DIVERGENCE, AND THESE CASES ARE WHY. Until J57-5b the reference opened the record with
// `encoding="utf-8"`, `json.loads` refused the leading BOM by name, and the same file was
// `unreadable` there while THIS side's `TextDecoder` stripped the BOM and answered `available`.
// The reference now reads with `utf-8-sig` and this side is unchanged: `ignoreBOM` stays at its
// default of `false`, which strips it. What has to be accepted is the three bytes `EF BB BF`,
// whoever wrote them, and a record a reader can plainly act on is not a shape it cannot act on.
// The bytes go to disk as BYTES below, never through an encoder that might add or eat one.
//
// AMENDED 2026-09-21 (J62-16). This block used to name PowerShell's `Set-Content`/`Out-File`
// defaults as the source of those bytes. Measured in `mcr.microsoft.com/powershell:latest`,
// PowerShell 7.4.2 writes NO BOM from any of `Set-Content`, `Out-File`, `>` or `Add-Content`;
// only an explicit `-Encoding utf8BOM` produces one. Windows PowerShell 5.1 is UNMEASURED here
// — it needs a Windows kernel this machine does not have. The cases below never depended on the
// writer; see `updatecheck.ts`'s `UTF8` comment for the full amendment.

const BOM = Buffer.from([0xef, 0xbb, 0xbf]);

/** The record as exact bytes — the only way to put a BOM on disk without trusting a codec. */
function writeBytesRecord(home, raw) {
  const path = join(home, RECORD_DIR, RECORD_NAME);
  writeFileSync(path, raw);
  return path;
}

for (const [id, installed, latest, state, line] of [
  [
    'available',
    '0.35.1',
    '0.36.0',
    STATE_AVAILABLE,
    'update: bantamkit-mcp 0.35.1 is running; the package index has 0.36.0 — run ' +
      '`bantamkit-mcp --update`, then reconnect the host.',
  ],
  ['current', '0.35.1', '0.35.1', STATE_CURRENT, 'update: bantamkit-mcp 0.35.1 is current as of 2026-09-19.'],
  [
    'ahead',
    '0.36.0',
    '0.35.1',
    STATE_AHEAD,
    'update: bantamkit-mcp 0.36.0 is ahead of the package index, which has 0.35.1.',
  ],
]) {
  test(`a record with a UTF-8 BOM lands where the same record without one does: ${id}`, () => {
    // Three states, one record, with and without the BOM: the BOM may move neither.
    withHome((home) => {
      const body = Buffer.from(record({ npm: latest }), 'utf8');
      writeBytesRecord(home, Buffer.concat([BOM, body]));
      const withBom = updateStatus(installed);
      assert.equal(withBom.state, state);
      assert.equal(withBom.line, line);

      writeBytesRecord(home, body);
      const without = updateStatus(installed);
      assert.equal(withBom.state, without.state);
      assert.equal(withBom.line, without.line);
    });
  });
}

test('a BOM in front of a broken record is still unreadable', () => {
  // The control. Accepting the BOM is not accepting whatever follows it.
  withHome((home) => {
    writeBytesRecord(home, Buffer.concat([BOM, Buffer.from('{"checked_at": "2026-09-19T21:04:11Z"\n', 'utf8')]));
    const status = updateStatus('0.35.1');
    assert.equal(status.state, STATE_UNREADABLE);
    assert.equal(status.line, 'update: the update record could not be read.');
  });
});

test('a BOM is stripped and not smuggled into the parsed record', () => {
  // `loadRecord` returns the record itself — no leading `\uFEFF` anywhere in a key.
  withHome((home) => {
    writeBytesRecord(home, Buffer.concat([BOM, Buffer.from(record({ npm: '0.36.0' }), 'utf8')]));
    const loaded = loadRecord();
    assert.equal(loaded.source, SOURCE_RECORD);
    assert.notEqual(loaded.record, null);
    assert.deepEqual(Object.keys(loaded.record), ['checked_at', 'npm', 'pypi']);
    assert.equal(Object.keys(loaded.record).some((key) => key.startsWith('\uFEFF')), false);
  });
});

test('undecodable bytes are unreadable and do not throw', () => {
  // A half-written record, or one from a writer that raced. Bytes, not text — and the reason
  // this module decodes with a FATAL `TextDecoder` rather than `readFileSync(path, 'utf8')`,
  // which would substitute U+FFFD and reach a different state than the reference does.
  withHome((home) => {
    writeFileSync(join(home, RECORD_DIR, RECORD_NAME), Buffer.from('7b22636865636b65645f6174223a2022fffe227d', 'hex'));
    assert.equal(updateStatus('0.35.1').state, STATE_UNREADABLE);
  });
});

test('a directory where the record should be is unreadable', () => {
  // Something IS there and this reader cannot use it — which is not `never checked`.
  withHome((home) => {
    mkdirSync(join(home, RECORD_DIR, RECORD_NAME));
    assert.equal(updateStatus('0.35.1').state, STATE_UNREADABLE);
  });
});

test('a missing .bantamkit directory is never checked', () => {
  // The state of a fresh machine. Not an error, and NOT a reason to create the directory. The
  // writer creates no directory either (it writes only when `.bantamkit` already exists), so
  // this is the state a machine that has installed nothing else stays in.
  withBareHome((root) => {
    assert.equal(updateStatus('0.35.1').state, STATE_NEVER);
    assert.equal(existsSync(join(root, RECORD_DIR)), false);
  });
});

test('a .bantamkit that is a file is never checked', () => {
  // `ENOTDIR`: nothing is at the path, so the operator is exactly where an unchecked one is.
  withBareHome((root) => {
    writeFileSync(join(root, RECORD_DIR), 'not a directory');
    assert.equal(updateStatus('0.35.1').state, STATE_NEVER);
  });
});

// ============================================================ readRecord and loadRecord

test('loadRecord names which of the two nothings it found', () => {
  withHome((home) => {
    assert.deepEqual(loadRecord(), { source: SOURCE_ABSENT, record: null });
    writeRecord(home, '{oops');
    assert.deepEqual(loadRecord(), { source: SOURCE_UNREADABLE, record: null });
    writeRecord(home, record());
    const { source, record: parsed } = loadRecord();
    assert.equal(source, SOURCE_RECORD);
    assert.equal(parsed.npm.latest, '0.36.0');
  });
});

test('readRecord returns the object or null', () => {
  withHome((home) => {
    assert.equal(readRecord(), null);
    writeRecord(home, record());
    assert.equal(readRecord().checked_at, CHECKED_AT);
  });
});

test('decide is pure and needs no filesystem', () => {
  // The state is decided from the record alone — no path, no clock, no home. HOME is pointed at
  // a directory that does not exist: if `decide` reached a disk at all, this is where it shows.
  const previous = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  const nowhere = join(tmpdir(), 'bk-updatecheck-nowhere-does-not-exist');
  process.env.HOME = nowhere;
  process.env.USERPROFILE = nowhere;
  try {
    assert.equal(existsSync(nowhere), false);
    const parsed = JSON.parse(record({ npm: '0.36.0' }));
    assert.equal(decide('0.35.1', SOURCE_RECORD, parsed).state, STATE_AVAILABLE);
    assert.equal(decide('0.35.1', SOURCE_ABSENT, null).state, STATE_NEVER);
    assert.equal(decide('0.35.1', SOURCE_UNREADABLE, null).state, STATE_UNREADABLE);
    assert.equal(existsSync(nowhere), false);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
});

test('updateLine is the line of updateStatus', () => {
  withHome((home) => {
    writeRecord(home, record({ npm: '0.36.0' }));
    assert.equal(updateLine('0.35.1'), updateStatus('0.35.1').line);
  });
});

test('an explicit path is read instead of the home one', () => {
  // The seam the conformance harness drives, so it need not own a HOME.
  withHome((home) => {
    const elsewhere = join(home, 'elsewhere.json');
    writeFileSync(elsewhere, record({ npm: '0.36.0' }));
    writeRecord(home, record({ npm: '0.35.1' }));
    assert.equal(updateStatus('0.35.1', KEY, elsewhere).state, STATE_AVAILABLE);
    assert.equal(updateStatus('0.35.1').state, STATE_CURRENT);
  });
});

// ============================================================ the date is sliced, never rendered

test('the date is the prefix of checked_at and not a locale rendering', () => {
  // A rendered date would make the two runtimes disagree on a machine set to another locale. So
  // the assertion is on the BYTES of the prefix, and on the absence of anything a renderer would
  // have added — a month name, a slash, a time.
  withHome((home) => {
    writeRecord(home, record({ npm: '0.35.1', checked_at: '2026-01-02T03:04:05Z' }));
    const line = updateLine('0.35.1');
    assert.equal(line, 'update: bantamkit-mcp 0.35.1 is current as of 2026-01-02.');
    assert.ok(!line.includes('Jan') && !line.includes('/') && !line.includes('03:04'), line);
  });
});

test('a bare date with no time is still a date', () => {
  withHome((home) => {
    writeRecord(home, record({ npm: '0.35.1', checked_at: '2026-09-19' }));
    assert.ok(updateLine('0.35.1').endsWith('current as of 2026-09-19.'));
  });
});

test('a stale checked_at does not become a state of its own', () => {
  // NO TTL LIVES IN THIS READER, and this is the case that would go red if one were added. A
  // record from 2019 that says the index has what is running is still `current`: the comparison
  // is running-versus-recorded, and freshness is the writer's problem alone.
  withHome((home) => {
    writeRecord(home, record({ npm: '0.35.1', checked_at: '2019-01-01T00:00:00Z' }));
    const status = updateStatus('0.35.1');
    assert.equal(status.state, STATE_CURRENT);
    assert.equal(status.line, 'update: bantamkit-mcp 0.35.1 is current as of 2019-01-01.');
  });
});

test('an old record cannot manufacture a false stale', () => {
  // The self-correcting half of the no-TTL argument: update, and the line goes quiet.
  withHome((home) => {
    writeRecord(home, record({ npm: '0.36.0', checked_at: '2019-01-01T00:00:00Z' }));
    assert.equal(updateStatus('0.35.1').state, STATE_AVAILABLE);
    assert.equal(updateStatus('0.36.0').state, STATE_CURRENT);
    assert.equal(updateStatus('0.37.0').state, STATE_AHEAD);
  });
});

// ==================================== two stamps, and which one dates which number (J62-13)
//
// An ENTRY's `checked_at` is when THAT registry answered; the record's is when a writer
// refreshed the record AS A WHOLE, and is the fallback for an entry without one. Before this,
// a writer that filled ONE key stamped the record — so the reader of the OTHER key dated its
// stale number by a check that never touched its registry. The reference's half of these is
// `runtime-py/tests/test_updatecheck.py`; the two are compared in
// `tools/conformance/suites/updatecheck.mjs`.

const ENTRY_CHECKED_AT = '2026-09-20T09:12:00Z';

/** The record stamped 2026-09-19, with an entry stamp of 2026-09-20 on npm. */
function twoStamps(pypiStamp) {
  const pypi = { distribution: 'bantamkit', latest: '0.36.0' };
  if (pypiStamp !== undefined) pypi.checked_at = pypiStamp;
  return JSON.stringify({
    checked_at: CHECKED_AT,
    npm: { package: 'bantamkit-mcp', latest: '0.36.0', checked_at: ENTRY_CHECKED_AT },
    pypi,
  });
}

test("an entry's own stamp dates that entry's number", () => {
  // One file, two keys, TWO DATES — and this reader takes the one that dates ITS number.
  withHome((home) => {
    writeRecord(home, twoStamps());
    assert.ok(updateLine('0.36.0', 'npm').endsWith('current as of 2026-09-20.'));
    assert.ok(updateLine('0.36.0', 'pypi').endsWith('current as of 2026-09-19.'));
  });
});

test("an entry without a stamp falls back to the record's", () => {
  // The fallback is not a leniency: such an entry WAS last written by a whole-record write.
  // This is the arm that keeps every record written before J62-13 answering byte for byte as
  // it did, which is why the whole pre-existing conformance table stayed green.
  withHome((home) => {
    writeRecord(home, record({ npm: '0.35.1', checked_at: '2026-01-02T03:04:05Z' }));
    assert.equal(updateLine('0.35.1'), 'update: bantamkit-mcp 0.35.1 is current as of 2026-01-02.');
  });
});

test("a record with no record-level stamp is read through the entry's", () => {
  // What `--update` leaves on a machine that had no record: an entry stamp and nothing else.
  // Before this, such a record was `could not be read` — which is why `recordUpdate` used to
  // stamp the record and why fixing THAT alone would have broken the fresh-install path.
  withHome((home) => {
    writeRecord(
      home,
      JSON.stringify({ npm: { package: 'bantamkit-mcp', latest: '0.36.0', checked_at: ENTRY_CHECKED_AT } }),
    );
    assert.equal(updateLine('0.36.0'), 'update: bantamkit-mcp 0.36.0 is current as of 2026-09-20.');
  });
});

for (const bad of ['yesterday', '19/09/2026', 20260920, null, '']) {
  test(`a garbage entry stamp (${JSON.stringify(bad)}) is unreadable and never falls back`, () => {
    // ONE SELECTION, THEN ONE RULE — not two rules, and not the more flattering of two dates.
    // The record's own stamp here is perfectly good. An entry that CARRIES the name is the
    // entry's answer, so a garbage value there is unreadable exactly as a garbage top-level
    // one is; a reader that fell back would date this number by a check of the OTHER registry,
    // which is the defect this whole change exists to remove. `hasOwnProperty` is how this
    // side spells CPython's `in` on a dict, and `null` is the arm that says the two agree.
    withHome((home) => {
      writeRecord(home, twoStamps(bad));
      assert.equal(updateStatus('0.36.0', 'npm').state, STATE_CURRENT);
      assert.equal(updateStatus('0.36.0', 'pypi').state, STATE_UNREADABLE);
    });
  });
}

// ============================================================ what this module never does

/** Every file under `root` as (size, mtimeNs, bytes) — enough to notice any write. */
function tree(root) {
  const out = {};
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : 1))) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (entry.isFile()) {
        const stat = statSync(path, { bigint: true });
        out[relative(root, path)] = [String(stat.size), String(stat.mtimeNs), readFileSync(path).toString('hex')];
      }
    }
  };
  walk(root);
  return out;
}

test('a read leaves the filesystem byte-unchanged', () => {
  withHome((home) => {
    writeRecord(home, record({ npm: '0.36.0' }));
    const before = tree(home);
    for (let i = 0; i < 3; i += 1) {
      updateStatus('0.35.1');
      readRecord();
      loadRecord();
      recordPath();
    }
    assert.deepEqual(tree(home), before);
  });
});

test('nothing here creates a cwd-relative .bantamkit', () => {
  // `.bantamkit` relative to a cwd is a MEMORY STORE (J54-3). This module never builds one. The
  // cwd is a directory that has none, the home has one, and every entry point is called —
  // including the ones that find nothing, because "it was missing so I made it" is the shape of
  // the defect this guards.
  withHome((home) => {
    // REALPATH'd: `/var` is a symlink to `/private/var` on macOS and `process.cwd()` resolves
    // before it answers, so an unresolved bed would have this case asserting a path node never
    // prints. The same reason `test/layers.test.mjs` resolves its bed.
    const workdir = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-updatecheck-repo-')));
    const cwd = process.cwd();
    try {
      process.chdir(workdir);
      recordPath();
      readRecord();
      loadRecord();
      updateStatus('0.35.1');
      updateLine('0.35.1');
      writeRecord(home, record({ npm: '0.36.0' }));
      updateLine('0.35.1');

      assert.equal(existsSync(join(workdir, RECORD_DIR)), false);
      assert.deepEqual(readdirSync(workdir), []);
      assert.equal(process.cwd(), workdir);
    } finally {
      process.chdir(cwd);
      rmSync(workdir, { recursive: true, force: true });
    }
  });
});

test('the record path hangs off home and not the cwd', () => {
  // The path does not move when the cwd does — which is the whole of J54-3's lesson.
  withHome((home) => {
    const workdir = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-updatecheck-arepo-')));
    const cwd = process.cwd();
    try {
      process.chdir(workdir);
      const path = recordPath();
      assert.ok(isAbsolute(path));
      assert.equal(path, join(home, RECORD_DIR, RECORD_NAME));
      assert.ok(!path.startsWith(workdir));
      process.chdir(tmpdir());
      assert.equal(recordPath(), path);
    } finally {
      process.chdir(cwd);
      rmSync(workdir, { recursive: true, force: true });
    }
  });
});

/**
 * Block comments and whole-line `//` comments, removed — and NOTHING ELSE.
 *
 * The gates below are scans for identifiers, and a scan that read the prose too would be the
 * over-eager half of the vacuity pair: this module's own docstring EXPLAINS why it holds no
 * `fetch` and defines no comparator, naming both to say so, and a gate that reddened on the
 * explanation is one the next person deletes. The same helper `test/selfupdate.test.mjs` uses.
 */
function code(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

test('the source writes nothing and reaches no network', () => {
  // Off the SOURCE, not off a sentence in a docstring. Two properties in one scan, because they
  // are the same kind of claim: every name this module can reach must be in neither the writing
  // set nor the network set. The reference makes the same claim over its own AST.
  const source = code(readFileSync(SRC, 'utf8'));

  const imported = [...source.matchAll(/from '([^']+)'/g)].map((m) => m[1]);
  assert.deepEqual(imported.sort(), ['./npminstall.js', 'node:fs', 'node:os', 'node:path']);

  for (const forbidden of [
    'fetch(',
    'node:http',
    'node:https',
    'node:net',
    'node:tls',
    'node:dgram',
    'XMLHttpRequest',
    'WebSocket',
    'node:child_process',
    'spawnSync',
    'execSync',
    'writeFileSync',
    'appendFileSync',
    'mkdirSync',
    'rmSync',
    'renameSync',
    'unlinkSync',
    'openSync',
    'createWriteStream',
  ]) {
    assert.ok(!source.includes(forbidden), `\`${forbidden}\` appears in updatecheck.ts's CODE`);
  }

  // RED-PROOF ON A SAMPLE, watched rather than asserted from the shape of the regex: the first
  // is the mutation these gates exist for, the second is the prose that must stay green.
  assert.ok(code('  const r = await fetch(INDEX_URL);\n').includes('fetch('));
  assert.ok(!code('/** it holds no fetch( and calls mkdirSync nowhere. */\n').includes('mkdirSync'));
  assert.ok(!code('  // mkdirSync is never called here\n').includes('mkdirSync'));
});

test('the states are five and named', () => {
  assert.deepEqual([...STATES], [STATE_NEVER, STATE_AVAILABLE, STATE_CURRENT, STATE_AHEAD, STATE_UNREADABLE]);
  assert.equal(new Set(STATES).size, 5);
});
