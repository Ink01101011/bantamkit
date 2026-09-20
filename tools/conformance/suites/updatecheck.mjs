/**
 * updatecheck — the stale-install signal: one record on disk, five states, two registry keys.
 *
 * WHAT THIS SUITE IS FOR. `runtime-py/src/bantamkit/updatecheck.py` and
 * `runtime-ts/src/updatecheck.ts` are the same reader written twice: they open
 * `<homedir>/.bantamkit/update-check.json`, compare the version that is RUNNING against the
 * version the record last saw, and answer with one of five sentences. CLAUDE.md's rule is the
 * reason this file exists — "a feature is not ported because someone wrote it twice; it is
 * ported when `node tools/conformance/run.mjs --all` compares the two answers and they match".
 *
 * EVERY RECORD IS A FILE BOTH RUNTIMES OPEN, AND IT IS THE SAME FILE. The fixtures are written
 * once, under the harness scratch, and both sides are handed the same absolute path — the idiom
 * `install.mjs` uses for its origins, and for the same reason: a suite that wrote its own copy
 * per side would compare two fixtures rather than two readers. Nothing here is mocked; the bytes
 * on disk are the input, including the ones that are not UTF-8.
 *
 * THE ONE DELIBERATE DIFFERENCE, AND WHAT IT IS NOT. The reference reads `pypi` and the port
 * reads `npm`; the reference WRITES `{"distribution": …}` and the port writes `{"package": …}`.
 * That is a genuinely different object rather than a different spelling of one — npm and PyPI
 * are two registries that can disagree at one version number, and job56 shipped a day where they
 * did. It is registered in `docs/porting.md`'s divergence table and pinned by the three `ruling:`
 * cases below.
 *
 * ITS COMPANION IS NOT A REFUSAL BIT, AND THE REASON IS WORTH WRITING DOWN. CLAUDE.md requires,
 * "where the difference is a refusal rather than a spelling, a second non-ruled case comparing
 * the refusal bit". NEITHER RUNTIME REFUSES ANYTHING HERE: every malformed shape is a STATE with
 * its own sentence and both readers are documented to raise for nothing, so there is no refusal
 * bit to compare. The blind spot a ruling leaves open here is a different one — both sides
 * reading the same key, or both sides landing in a different state for one record — so the
 * companion is the KEY-EXPLICIT differential: every arm is asked of BOTH runtimes under BOTH
 * registry keys, and under a given key the two must agree on the source, the state, the record
 * and the whole sentence. The analogue of the refusal bit is pinned too: `raised` per arm per
 * side, because "this reader never raises" is a claim a differential over two answers cannot
 * see if both sides start throwing at once.
 *
 * A UTF-8 BOM IS NOT A DIVERGENCE, AND THESE ARE THE CASES THAT PROVE IT. It was one until
 * J57-5b: the reference opened the record with `encoding="utf-8"` and `json.loads` refused the
 * BOM (`unreadable`) while the port's `TextDecoder` stripped it (`available`) — one record, two
 * answers, found by writing this suite and left red on purpose rather than hidden. It is closed
 * in the RUNTIME, not here: the reference reads with `utf-8-sig`, both sides now ACCEPT the BOM
 * (PowerShell writes one by default and a record a reader can act on is not unreadable), and the
 * four `utf-8-bom` / `bom-not-json` arms below are compared in every table like any other shape.
 * It is deliberately NOT a `ruling:` and NOT a `docs/porting.md` row: a ruling asserts a
 * difference somebody chose, and there is no difference left here to assert.
 *
 * THE MACHINE'S OWN RECORD IS NEVER TOUCHED. `HOME` and `USERPROFILE` are redirected for every
 * arm that can reach a home directory — on the reference through the child's environment, on the
 * port around the in-process call with a `finally` that puts them back. MEASURED ON THIS JOB: an
 * arm that ran under the real HOME wrote a fixture version into the operator's own
 * `~/.bantamkit/update-check.json`. The reader arms do not need the redirection (they are handed
 * an explicit path) and get it anyway, because the cost is nothing and the failure is silent.
 */
import { chmodSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'updatecheck';
export const summary = 'the stale-install signal: one record, five states, two registry keys';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'updatecheck_ref.py');

// --------------------------------------------------------------------------- the vocabulary
// Spelled here as LITERALS, never imported from either runtime: these are what the per-side
// cases compare against, and a constant imported from the thing under test proves nothing.

const PROGRAM = 'bantamkit-mcp';
const NPM_PACKAGE = 'bantamkit-mcp';
const PYPI_DISTRIBUTION = 'bantamkit';
const STATES = ['never', 'available', 'current', 'ahead', 'unreadable'];
const SOURCES = ['absent', 'unreadable', 'record'];
const RECORD_DIR = '.bantamkit';
const RECORD_NAME = 'update-check.json';

/** The five sentences, byte for byte, as `updatecheck.py` declares them. */
const SENTENCES = {
  never: 'update: never checked.',
  available:
    'update: {program} {installed} is running; the package index has {latest} — run ' +
    '`{program} --update`, then reconnect the host.',
  current: 'update: {program} {installed} is current as of {date}.',
  ahead: 'update: {program} {installed} is ahead of the package index, which has {latest}.',
  unreadable: 'update: the update record could not be read.',
};

/** The five RENDERED lines, for the five arms named in `LINE_ARMS`. Hand-written, not filled. */
const LINES = {
  'never/absent': 'update: never checked.',
  'available/one-minor-behind':
    'update: bantamkit-mcp 0.35.1 is running; the package index has 0.36.0 — run ' +
    '`bantamkit-mcp --update`, then reconnect the host.',
  'current/exactly': 'update: bantamkit-mcp 0.36.0 is current as of 2026-09-19.',
  'ahead/one-minor': 'update: bantamkit-mcp 0.37.0 is ahead of the package index, which has 0.36.0.',
  'unreadable/not-json': 'update: the update record could not be read.',
};
const LINE_ARMS = Object.keys(LINES);

/** `YYYY-MM-DDTHH:MM:SSZ` — `selfupdate.STAMP`, and what `runtime-ts` strips its `.000` to reach. */
const STAMP_SHAPE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

/** The stamp every fixture carries, so `current`'s date is a constant this file can assert. */
const STAMPED = '2026-09-19T21:04:11Z';

// ------------------------------------------------------------------------------ the records
// One entry per SHAPE the reader can be handed. A string is written as UTF-8; a `Uint8Array` is
// written as the bytes it is, which is how the undecodable arm gets on disk at all.

const text = (value) => `${JSON.stringify(value, null, 2)}\n`;
const entries = (latest) => ({
  npm: { package: NPM_PACKAGE, latest },
  pypi: { distribution: PYPI_DISTRIBUTION, latest },
});
const both = (latest, checked_at = STAMPED) => text({ checked_at, ...entries(latest) });

const RECORDS = {
  // --- well-formed, and the only difference between them is the version or the stamp
  'both-0.36.0': both('0.36.0'),
  'both-0.10.0': both('0.10.0'),
  'both-0.36': both('0.36'),
  'both-prerelease': both('0.36.0rc1'),
  'both-padded': text({ checked_at: STAMPED, ...entries('  0.36.0  ') }),
  'offset-date': both('0.36.0', '2026-09-19T21:04:11+00:00'),
  'date-only': both('0.36.0', '2026-09-19'),
  // --- the two registries disagree, which is the whole reason the record carries both
  disagree: text({
    checked_at: STAMPED,
    npm: { package: NPM_PACKAGE, latest: '0.34.0' },
    pypi: { distribution: PYPI_DISTRIBUTION, latest: '0.36.0' },
  }),
  'npm-only': text({ checked_at: STAMPED, npm: { package: NPM_PACKAGE, latest: '0.36.0' } }),
  'pypi-only': text({ checked_at: STAMPED, pypi: { distribution: PYPI_DISTRIBUTION, latest: '0.36.0' } }),
  // --- a record that is JSON and an object and still says nothing this reader can act on
  'no-keys': text({ checked_at: STAMPED }),
  'no-checked-at': text({ ...entries('0.36.0') }),
  'checked-at-not-a-date': text({ checked_at: 'yesterday', ...entries('0.36.0') }),
  'checked-at-not-a-string': text({ checked_at: 20260919, ...entries('0.36.0') }),
  'checked-at-unpadded': text({ checked_at: '2026-9-19T21:04:11Z', ...entries('0.36.0') }),
  'latest-not-a-version': both('nightly'),
  'latest-v-prefixed': both('v1.2.3'),
  'latest-not-a-string': text({ checked_at: STAMPED, npm: { package: NPM_PACKAGE, latest: 36 }, pypi: { distribution: PYPI_DISTRIBUTION, latest: 36 } }),
  'latest-missing': text({ checked_at: STAMPED, npm: { package: NPM_PACKAGE }, pypi: { distribution: PYPI_DISTRIBUTION } }),
  'entry-a-string': text({ checked_at: STAMPED, npm: '0.36.0', pypi: '0.36.0' }),
  'entry-an-array': text({ checked_at: STAMPED, npm: ['0.36.0'], pypi: ['0.36.0'] }),
  'entry-null': text({ checked_at: STAMPED, npm: null, pypi: null }),
  // --- not a record at all
  'not-json': '{"checked_at": "2026-09-19T21:04:11Z"\n',
  'json-array': '[]\n',
  'json-number': '7\n',
  'json-null': 'null\n',
  'json-string': '"a record"\n',
  empty: '',
  whitespace: '   \n',
  // A truncated two-byte sequence: not UTF-8, and the reason the port decodes with `fatal`.
  'not-utf8': Uint8Array.from([0x7b, 0x22, 0x63, 0x22, 0x3a, 0x22, 0xc3, 0x22, 0x7d, 0x0a]),
  // A WELL-FORMED record with a UTF-8 BOM in front of it — what Windows PowerShell's
  // `Set-Content`/`Out-File` writes by default, so an operator who edits this file by hand on
  // Windows produces exactly these bytes. BOTH RUNTIMES ACCEPT IT (J57-5b): the reference reads
  // with `utf-8-sig`, the port's `TextDecoder` strips it at its default `ignoreBOM: false`. The
  // three arms below answer it at three running versions, so the BOM changes the state in
  // neither direction; `bom-not-json` is the control that says the BOM is not a blanket pass.
  bom: `﻿${both('0.36.0')}`,
  // THE CONTROL. A BOM in front of bytes that are still not a record: stripping the BOM must not
  // turn a broken record into a readable one, on either side.
  'bom-not-json': `﻿{"checked_at": "${STAMPED}"\n`,
};

// ---------------------------------------------------------------------------------- the arms
// `record` names a fixture above, or one of the four PATH shapes the suite constructs instead of
// writing: `@absent`, `@under-a-file`, `@a-directory`, `@denied`.

const ARMS = [
  { id: 'never/absent', record: '@absent', installed: '0.35.1' },
  { id: 'never/under-a-file', record: '@under-a-file', installed: '0.35.1' },
  { id: 'unreadable/a-directory', record: '@a-directory', installed: '0.35.1' },
  { id: 'unreadable/denied', record: '@denied', installed: '0.35.1' },

  { id: 'available/one-minor-behind', record: 'both-0.36.0', installed: '0.35.1' },
  // `0.9.0 < 0.10.0` — the pair a string compare gets wrong, and the reason
  // `selfupdate.compare_versions` exists. There is no second comparator in this codebase.
  { id: 'available/nine-against-ten', record: 'both-0.10.0', installed: '0.9.0' },
  // WRONG BY PEP 440 AND RIGHT BY `_version_key`'s documented contract: `0.36.0 < 0.36.0rc1`.
  // Both runtimes are wrong in the SAME direction, which is the part a gate can hold.
  { id: 'available/prerelease-ahead', record: 'both-prerelease', installed: '0.36.0' },

  { id: 'current/exactly', record: 'both-0.36.0', installed: '0.36.0' },
  { id: 'current/zero-padded', record: 'both-0.36', installed: '0.36.0' },
  { id: 'current/padded-latest', record: 'both-padded', installed: '0.36.0' },
  { id: 'current/offset-date', record: 'offset-date', installed: '0.36.0' },
  { id: 'current/date-only', record: 'date-only', installed: '0.36.0' },

  { id: 'ahead/one-minor', record: 'both-0.36.0', installed: '0.37.0' },
  { id: 'ahead/ten-against-nine', record: 'both-0.10.0', installed: '0.11.0' },
  { id: 'ahead/prerelease-installed', record: 'both-0.36.0', installed: '0.36.0rc1' },

  // The three arms where the two registries do not say the same thing. Every one of them is
  // answered under BOTH keys by BOTH runtimes below; their DEFAULT-key answers are the ruling.
  { id: 'keys/disagree', record: 'disagree', installed: '0.35.1' },
  { id: 'keys/npm-only', record: 'npm-only', installed: '0.35.1' },
  { id: 'keys/pypi-only', record: 'pypi-only', installed: '0.35.1' },

  { id: 'unreadable/no-keys', record: 'no-keys', installed: '0.35.1' },
  { id: 'unreadable/no-checked-at', record: 'no-checked-at', installed: '0.35.1' },
  { id: 'unreadable/checked-at-not-a-date', record: 'checked-at-not-a-date', installed: '0.35.1' },
  { id: 'unreadable/checked-at-not-a-string', record: 'checked-at-not-a-string', installed: '0.35.1' },
  { id: 'unreadable/checked-at-unpadded', record: 'checked-at-unpadded', installed: '0.35.1' },
  { id: 'unreadable/latest-not-a-version', record: 'latest-not-a-version', installed: '0.35.1' },
  { id: 'unreadable/latest-v-prefixed', record: 'latest-v-prefixed', installed: '0.35.1' },
  { id: 'unreadable/latest-not-a-string', record: 'latest-not-a-string', installed: '0.35.1' },
  { id: 'unreadable/latest-missing', record: 'latest-missing', installed: '0.35.1' },
  { id: 'unreadable/entry-a-string', record: 'entry-a-string', installed: '0.35.1' },
  { id: 'unreadable/entry-an-array', record: 'entry-an-array', installed: '0.35.1' },
  { id: 'unreadable/entry-null', record: 'entry-null', installed: '0.35.1' },
  { id: 'unreadable/not-json', record: 'not-json', installed: '0.35.1' },
  { id: 'unreadable/json-array', record: 'json-array', installed: '0.35.1' },
  { id: 'unreadable/json-number', record: 'json-number', installed: '0.35.1' },
  { id: 'unreadable/json-null', record: 'json-null', installed: '0.35.1' },
  { id: 'unreadable/json-string', record: 'json-string', installed: '0.35.1' },
  { id: 'unreadable/empty', record: 'empty', installed: '0.35.1' },
  { id: 'unreadable/whitespace', record: 'whitespace', installed: '0.35.1' },
  { id: 'unreadable/not-utf8', record: 'not-utf8', installed: '0.35.1' },

  // THE SAME RECORD AS `both-0.36.0`, WITH A BOM IN FRONT OF IT, at the same three running
  // versions the BOM-less arms use above. Compared in every table like any other arm, because
  // after J57-5b there is nothing here the two runtimes disagree about — see the suite header.
  { id: 'available/utf-8-bom', record: 'bom', installed: '0.35.1' },
  { id: 'current/utf-8-bom', record: 'bom', installed: '0.36.0' },
  { id: 'ahead/utf-8-bom', record: 'bom', installed: '0.37.0' },
  { id: 'unreadable/bom-not-json', record: 'bom-not-json', installed: '0.35.1' },
];

/**
 * The state every arm must land in, hand-written, per registry key.
 *
 * THIS TABLE IS THE NON-VACUITY HALF. The differential below compares the two runtimes to each
 * other and is blind to a change that lands on both at once — three parity bugs in this repo's
 * history were missed exactly that way. So every arm is ALSO compared, per side, to the word
 * written here by a person reading the two sources.
 */
const COMMON_STATES = {
  'never/absent': 'never',
  'never/under-a-file': 'never',
  'unreadable/a-directory': 'unreadable',
  'unreadable/denied': 'unreadable',
  'available/one-minor-behind': 'available',
  'available/nine-against-ten': 'available',
  'available/prerelease-ahead': 'available',
  'current/exactly': 'current',
  'current/zero-padded': 'current',
  'current/padded-latest': 'current',
  'current/offset-date': 'current',
  'current/date-only': 'current',
  'ahead/one-minor': 'ahead',
  'ahead/ten-against-nine': 'ahead',
  'ahead/prerelease-installed': 'ahead',
  'unreadable/no-keys': 'unreadable',
  'unreadable/no-checked-at': 'unreadable',
  'unreadable/checked-at-not-a-date': 'unreadable',
  'unreadable/checked-at-not-a-string': 'unreadable',
  'unreadable/checked-at-unpadded': 'unreadable',
  'unreadable/latest-not-a-version': 'unreadable',
  'unreadable/latest-v-prefixed': 'unreadable',
  'unreadable/latest-not-a-string': 'unreadable',
  'unreadable/latest-missing': 'unreadable',
  'unreadable/entry-a-string': 'unreadable',
  'unreadable/entry-an-array': 'unreadable',
  'unreadable/entry-null': 'unreadable',
  'unreadable/not-json': 'unreadable',
  'unreadable/json-array': 'unreadable',
  'unreadable/json-number': 'unreadable',
  'unreadable/json-null': 'unreadable',
  'unreadable/json-string': 'unreadable',
  'unreadable/empty': 'unreadable',
  'unreadable/whitespace': 'unreadable',
  'unreadable/not-utf8': 'unreadable',
  // A BOM changes nothing about which state a record lands in — the whole point of J57-5b.
  'available/utf-8-bom': 'available',
  'current/utf-8-bom': 'current',
  'ahead/utf-8-bom': 'ahead',
  'unreadable/bom-not-json': 'unreadable',
};

const STATES_BY_KEY = {
  // A key the record does not carry is UNREADABLE and not `never`: something IS there, and this
  // reader cannot use it. Collapsing the two would print `never checked` over a real record.
  pypi: { ...COMMON_STATES, 'keys/disagree': 'available', 'keys/npm-only': 'unreadable', 'keys/pypi-only': 'available' },
  npm: { ...COMMON_STATES, 'keys/disagree': 'ahead', 'keys/npm-only': 'available', 'keys/pypi-only': 'unreadable' },
};

/** The `SOURCE_*` word each arm's loader must report — a separate fact from the state. */
const SOURCES_BY_ARM = Object.fromEntries(
  ARMS.map((arm) => {
    if (arm.record === '@absent' || arm.record === '@under-a-file') return [arm.id, 'absent'];
    if (arm.record === '@a-directory' || arm.record === '@denied') return [arm.id, 'unreadable'];
    const unreadableBytes = ['not-json', 'json-array', 'json-number', 'json-null', 'json-string', 'empty', 'whitespace', 'not-utf8', 'bom-not-json'];
    return [arm.id, unreadableBytes.includes(arm.record) ? 'unreadable' : 'record'];
  }),
);

// ------------------------------------------------------------------------------ the writers
// `selfupdate.record_update` / `selfupdate.recordUpdate`: the other half of the divergence, and
// the only thing in either runtime that WRITES this file. Each home below is built by this suite
// so both sides start from identical bytes, and each side gets its OWN home because they write.

const WRITE_LATEST = '0.36.0';
const WRITE_NOW = '2026-09-19T21:04:11Z';

/** The record a `write/merge` home starts from: both keys filled, and a key neither owns. */
const EXISTING = text({
  checked_at: '2026-09-01T00:00:00Z',
  npm: { package: NPM_PACKAGE, latest: '0.30.0' },
  pypi: { distribution: PYPI_DISTRIBUTION, latest: '0.30.0' },
  extra: { kept: true },
});

const WRITES = [
  { id: 'write/fresh', dir: 'directory', existing: null, now: WRITE_NOW },
  { id: 'write/merge', dir: 'directory', existing: EXISTING, now: WRITE_NOW },
  { id: 'write/unreadable-existing', dir: 'directory', existing: '{oops\n', now: WRITE_NOW },
  { id: 'write/no-directory', dir: 'nothing', existing: null, now: WRITE_NOW },
  { id: 'write/directory-is-a-file', dir: 'file', existing: null, now: WRITE_NOW },
  { id: 'write/own-stamp', dir: 'directory', existing: null, now: null },
];

// --------------------------------------------------------------------------------- fixtures

const writeFile = (path, body) => {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, body);
};

/** Write every record once, and return the path each arm is handed. */
function buildRecords(root) {
  const paths = {};
  for (const [id, body] of Object.entries(RECORDS)) {
    paths[id] = join(root, `${id}.json`);
    writeFile(paths[id], body);
  }
  // A path with nothing at it. Never created, by anything, ever — that is the arm.
  paths['@absent'] = join(root, 'there-is-nothing-here.json');
  // A regular file with a path UNDERNEATH it: ENOTDIR, which is still "nothing is there".
  paths['@under-a-file'] = join(paths['both-0.36.0'], RECORD_NAME);
  // A directory where the record should be: something IS there and it cannot be read.
  paths['@a-directory'] = join(root, 'a-directory.json');
  mkdirSync(paths['@a-directory'], { recursive: true });
  // A real record behind a mode nobody may read. Chmodded around both sides' reads, below.
  paths['@denied'] = join(root, 'denied.json');
  writeFile(paths['@denied'], RECORDS['both-0.36.0']);
  return paths;
}

/** One side's homes for the writer arms, built identically on both sides. */
function buildWriteHomes(root) {
  const homes = {};
  for (const write of WRITES) {
    const home = join(root, write.id.replace('/', '-'));
    mkdirSync(home, { recursive: true });
    const inside = join(home, RECORD_DIR);
    if (write.dir === 'directory') {
      mkdirSync(inside, { recursive: true });
      if (write.existing !== null) writeFileSync(join(inside, RECORD_NAME), write.existing, 'utf8');
    } else if (write.dir === 'file') {
      writeFileSync(inside, 'a regular file where the toolbox directory should be\n', 'utf8');
    }
    homes[write.id] = home;
  }
  return homes;
}

/**
 * A written body with the divergence spelled out of it, so the BYTES can be compared.
 *
 * The registry key, the field naming the thing on that registry, and that thing's name are the
 * three strings the ruling licenses; everything else — the indentation, the key order, the
 * separators and the trailing newline — is compared as it was written. `"bantamkit-mcp"` is
 * replaced before `"bantamkit"`, and the quotes make the two unambiguous anyway.
 */
const normaliseBody = (body) =>
  body === null || body === undefined
    ? null
    : body
        .replace(/"pypi"/g, '"<key>"')
        .replace(/"npm"/g, '"<key>"')
        .replace(/"distribution"/g, '"<field>"')
        .replace(/"package"/g, '"<field>"')
        .replace(/"bantamkit-mcp"/g, '"<name>"')
        .replace(/"bantamkit"/g, '"<name>"');

/** Compare each side to a typed constant — the only shape a symmetric regression reddens. */
function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `${label} — the reference`, kind, expected, actual: pySide },
    { name: `${label} — the port`, kind, expected, actual: nodeSide },
  ];
}

// ------------------------------------------------------------------------------- the port side

/** Every answer the port produces, with `HOME` pointed somewhere nobody lives for all of it. */
async function nodeAnswers(ctx, paths, homes, defaultHome, defaultCwd) {
  const updatecheck = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'updatecheck.js')).href);
  const selfupdate = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'selfupdate.js')).href);

  const readArm = (arm, key) => {
    try {
      const path = paths[arm.record];
      const { source, record } = updatecheck.loadRecord(path);
      const status = updatecheck.decide(arm.installed, source, record, key);
      const line = updatecheck.updateLine(arm.installed, key, path);
      const again = updatecheck.readRecord(path);
      return {
        raised: null,
        source,
        state: status.state,
        line: status.line,
        line_via_update_line: line,
        record,
        read_record_agrees: JSON.stringify(again ?? null) === JSON.stringify(record ?? null),
      };
    } catch (error) {
      return { raised: `${error?.constructor?.name}: ${error?.message}` };
    }
  };

  const listing = (directory) => {
    try {
      return readdirSync(directory).sort();
    } catch {
      return null;
    }
  };
  const read = (path) => {
    try {
      return readFileSync(path, 'utf8');
    } catch {
      return null;
    }
  };

  const before = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  const cwdBefore = process.cwd();
  const setHome = (home) => {
    process.env.HOME = home;
    process.env.USERPROFILE = home;
  };
  try {
    setHome(defaultHome);
    const answers = {};
    for (const key of ['pypi', 'npm']) {
      answers[key] = Object.fromEntries(ARMS.map((arm) => [arm.id, readArm(arm, key)]));
    }
    const defaults = Object.fromEntries(ARMS.map((arm) => [arm.id, readArm(arm, updatecheck.KEY)]));

    const writes = {};
    for (const write of WRITES) {
      const home = homes[write.id];
      setHome(home);
      const directory = join(home, RECORD_DIR);
      const path = join(directory, RECORD_NAME);
      try {
        const wrote = selfupdate.recordUpdate(WRITE_LATEST, write.now ?? undefined);
        const body = read(path);
        let parsed = null;
        try {
          parsed = body === null ? null : JSON.parse(body);
        } catch {
          parsed = null;
        }
        writes[write.id] = {
          raised: null,
          wrote,
          listing: listing(directory),
          body,
          record: parsed,
          path_under_home: relative(home, updatecheck.recordPath()).split(sep).join('/'),
        };
      } catch (error) {
        writes[write.id] = { raised: `${error?.constructor?.name}: ${error?.message}` };
      }
    }

    // The default path, read from a cwd that HAS a `.bantamkit` of its own: a reader that
    // resolved against the cwd would find that one and say something else.
    setHome(defaultHome);
    process.chdir(defaultCwd);
    const status = updatecheck.updateStatus('0.35.1');
    const defaultPath = {
      state: status.state,
      line: status.line,
      path_under_home: relative(defaultHome, updatecheck.recordPath()).split(sep).join('/'),
      home_listing: listing(defaultHome),
      cwd_listing: listing(join(defaultCwd, RECORD_DIR)),
    };

    return {
      constants: {
        PROGRAM: updatecheck.PROGRAM,
        KEY: updatecheck.KEY,
        RECORD_DIR: updatecheck.RECORD_DIR,
        RECORD_NAME: updatecheck.RECORD_NAME,
        STATES: [...updatecheck.STATES],
        SOURCES: [updatecheck.SOURCE_ABSENT, updatecheck.SOURCE_UNREADABLE, updatecheck.SOURCE_RECORD],
      },
      sentences: {
        never: updatecheck.UPDATE_NEVER,
        available: updatecheck.UPDATE_AVAILABLE,
        current: updatecheck.UPDATE_CURRENT,
        ahead: updatecheck.UPDATE_AHEAD,
        unreadable: updatecheck.UPDATE_UNREADABLE,
      },
      // The port declares `PROGRAM` rather than importing it, so `selfupdate.ts` stays off the
      // path a host reaches; the equality is the thing that has to hold, and here it travels.
      program_is_selfupdates: updatecheck.PROGRAM === selfupdate.PROGRAM,
      answers,
      defaults,
      writes,
      default_path: defaultPath,
    };
  } finally {
    process.chdir(cwdBefore);
    for (const [key, value] of Object.entries(before)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

// -------------------------------------------------------------------------------- the run

export async function run(ctx) {
  const root = join(ctx.scratch, 'updatecheck');
  const records = join(root, 'records');
  const paths = buildRecords(records);
  const homes = { py: buildWriteHomes(join(root, 'write-py')), node: buildWriteHomes(join(root, 'write-node')) };
  const defaultHome = { py: join(root, 'default-home-py'), node: join(root, 'default-home-node') };
  const defaultCwd = { py: join(root, 'default-cwd-py'), node: join(root, 'default-cwd-node') };
  for (const side of ['py', 'node']) {
    mkdirSync(defaultHome[side], { recursive: true });
    // A cwd-relative `.bantamkit` is a MEMORY STORE (J54-3), and this is the arm that says the
    // reader never confuses the two: the directory exists, with a store in it, and is ignored.
    mkdirSync(join(defaultCwd[side], RECORD_DIR, 'memory', 'facts'), { recursive: true });
  }

  const listingBefore = readdirSync(records).sort();

  let py;
  let node;
  // The mode is closed for exactly as long as both sides are being asked, and reopened in a
  // `finally` so a throw in here cannot leave harness scratch undeletable.
  //
  // platform-checked: a `0o000` mode denies nothing on Windows (which honours only the
  // read-only bit) and nothing as root, and this suite already knows it — the
  // `unreadable/denied` arm is SKIPPED with a note, and dropped from every table, whenever
  // either side's read got THROUGH. So the scenario loses its teeth there rather than failing
  // there, and it loses them out loud. The skip is narrow on purpose: it fires only where a
  // side actually reached the record, never where a side answered `unreadable`.
  chmodSync(paths['@denied'], 0o000);
  try {
    node = await nodeAnswers(ctx, paths, homes.node, defaultHome.node, defaultCwd.node);
    py = ctx.runPython(
      REF,
      {
        keys: ['pypi', 'npm'],
        arms: ARMS.map((arm) => ({ id: arm.id, path: paths[arm.record], installed: arm.installed })),
        writes: WRITES.map((write) => ({ id: write.id, home: homes.py[write.id], latest: WRITE_LATEST, now: write.now })),
        default_path: { home: defaultHome.py, cwd: defaultCwd.py, installed: '0.35.1' },
      },
      { HOME: defaultHome.py, USERPROFILE: defaultHome.py },
    );
  } finally {
    chmodSync(paths['@denied'], 0o644);
  }

  const cases = [];
  const notes = [];

  // ---------------------------------------------------------------- the shared vocabulary

  cases.push({
    name: 'updatecheck: the five state names, in the same order',
    kind: 'json',
    expected: py.constants.STATES,
    actual: node.constants.STATES,
  });
  cases.push(...literalCases(py.constants.STATES, node.constants.STATES, 'updatecheck: the five state names against a literal', STATES));
  cases.push({
    name: 'updatecheck: the three loader outcomes, in the same order',
    kind: 'json',
    expected: py.constants.SOURCES,
    actual: node.constants.SOURCES,
  });
  cases.push(...literalCases(py.constants.SOURCES, node.constants.SOURCES, 'updatecheck: the three loader outcomes against a literal', SOURCES));

  // THE SENTENCES ARE THE PRODUCT. One case for all five side to side, and one literal pin per
  // side, because a sentence edited in both runtimes at once leaves the differential green.
  cases.push({
    name: 'updatecheck: the five sentences, side to side',
    kind: 'json',
    expected: py.sentences,
    actual: node.sentences,
  });
  cases.push(...literalCases(py.sentences, node.sentences, 'updatecheck: the five sentences against literals', SENTENCES));
  for (const state of STATES) {
    cases.push({
      name: `updatecheck: the \`${state}\` sentence, byte for byte`,
      kind: 'bytes',
      expected: py.sentences[state],
      actual: node.sentences[state],
    });
  }

  // The sentences name the COMMAND and never a package: the PyPI distribution is `bantamkit`,
  // the npm package is `bantamkit-mcp`, and a sentence naming either could not be identical.
  cases.push(
    ...literalCases(
      Object.values(py.sentences).some((s) => /bantamkit(?!-mcp)/.test(s.replace(/\{program\}/g, ''))),
      Object.values(node.sentences).some((s) => /bantamkit(?!-mcp)/.test(s.replace(/\{program\}/g, ''))),
      'updatecheck: no sentence names a package rather than the command',
      false,
    ),
  );
  cases.push(...literalCases(py.constants.PROGRAM, node.constants.PROGRAM, 'updatecheck: the program named in every sentence', PROGRAM, 'string'));
  cases.push(
    ...literalCases(py.program_is_selfupdates, node.program_is_selfupdates, 'updatecheck: the program is `selfupdate`\'s, not a second spelling', true),
  );
  cases.push(
    ...literalCases(
      [py.constants.RECORD_DIR, py.constants.RECORD_NAME],
      [node.constants.RECORD_DIR, node.constants.RECORD_NAME],
      'updatecheck: the two path components of the record',
      [RECORD_DIR, RECORD_NAME],
    ),
  );

  // ------------------------------------------------- every arm, under every key, side to side

  /**
   * THE COMPANION THE RULING CANNOT BE. Given ONE record and ONE running version, the two
   * runtimes must land in the same state — and say the same sentence, report the same loader
   * outcome and parse the same record. The key is passed EXPLICITLY here, which is what holds
   * the comparison steady across the one thing the two are licensed to differ about.
   */
  const denied = { py: py.answers.pypi['unreadable/denied'], node: node.answers.pypi['unreadable/denied'] };
  const deniedGotThrough = denied.py.source === 'record' || denied.node.source === 'record';
  if (deniedGotThrough) {
    notes.push(
      'unreadable/denied: SKIPPED — a read got through a 0o000 file on this filesystem ' +
        `(reference ${JSON.stringify(denied.py.source)}, port ${JSON.stringify(denied.node.source)}), ` +
        'so there is nothing here to deny. Expected as root and on Windows; any other answer is NOT skipped.',
    );
  }
  // EVERY arm is compared: nothing in this suite is held out of the tables.
  const compared = ARMS.filter((arm) => !(deniedGotThrough && arm.id === 'unreadable/denied'));

  for (const key of ['pypi', 'npm']) {
    for (const arm of compared) {
      cases.push({
        name: `updatecheck: ${arm.id} under \`${key}\` — the same source, state, record and sentence`,
        kind: 'json',
        expected: py.answers[key][arm.id],
        actual: node.answers[key][arm.id],
      });
    }
    // The per-side half: the word a person wrote down, against what each runtime answered.
    const states = (side) => Object.fromEntries(compared.map((arm) => [arm.id, side[key][arm.id].state]));
    const expectedStates = Object.fromEntries(compared.map((arm) => [arm.id, STATES_BY_KEY[key][arm.id]]));
    cases.push(...literalCases(states(py.answers), states(node.answers), `updatecheck: every arm's state under \`${key}\`, against the table`, expectedStates));
  }

  // The loader outcome is a SEPARATE fact from the state — `absent` and `unreadable` both reach
  // a sentence, and collapsing them would print `never checked` over a corrupted record.
  const sources = (side) => Object.fromEntries(compared.map((arm) => [arm.id, side.pypi[arm.id].source]));
  cases.push(...literalCases(sources(py.answers), sources(node.answers), 'updatecheck: what the loader found, per arm, against the table', Object.fromEntries(compared.map((arm) => [arm.id, SOURCES_BY_ARM[arm.id]]))));

  // NOTHING RAISES, EVER, ON EITHER SIDE. This is the analogue of `install`'s refusal bit: a
  // differential over two answers cannot see both sides starting to throw at once.
  const raised = (side) => Object.fromEntries(compared.map((arm) => [arm.id, side.pypi[arm.id].raised ?? side.npm[arm.id].raised ?? null]));
  cases.push(...literalCases(raised(py.answers), raised(node.answers), 'updatecheck: not one shape raises, on either side', Object.fromEntries(compared.map((arm) => [arm.id, null]))));

  // The five RENDERED lines, per side, against sentences written out in full by hand.
  for (const arm of LINE_ARMS) {
    cases.push(
      ...literalCases(py.answers.pypi[arm].line, node.answers.pypi[arm].line, `updatecheck: the line for \`${arm}\``, LINES[arm], 'bytes'),
    );
  }

  // The one-call surface agrees with the two-step one, on both sides and for every arm.
  const viaOneCall = (side) => Object.fromEntries(compared.map((arm) => [arm.id, side.pypi[arm.id].line === side.pypi[arm.id].line_via_update_line]));
  cases.push(...literalCases(viaOneCall(py.answers), viaOneCall(node.answers), 'updatecheck: `update_line` says what `decide` says, per arm', Object.fromEntries(compared.map((arm) => [arm.id, true]))));

  // ------------------------------------------------------------------- a read creates nothing

  // THE FIXTURE DIRECTORY IS UNTOUCHED after both runtimes have read every record in it, twice
  // over, under two keys. A reader that created anything — a lock, a stamp, a rewritten record —
  // would show up here as an entry nobody wrote.
  cases.push({
    name: 'updatecheck: a read creates nothing — the record directory after both runtimes read every shape',
    kind: 'json',
    expected: listingBefore,
    actual: readdirSync(records).sort(),
  });
  cases.push(
    ...literalCases(listingBefore, readdirSync(records).sort(), 'updatecheck: the record directory holds exactly the fixtures the suite wrote', [
      ...Object.keys(RECORDS).map((id) => `${id}.json`),
      'a-directory.json',
      'denied.json',
    ].sort()),
  );

  // And the default path: a read through `record_path()` on a home with NO `.bantamkit` answers
  // `never checked` and leaves the home exactly as empty as it found it.
  cases.push({
    name: 'updatecheck: the default record path — the same answer, the same suffix, and nothing created',
    kind: 'json',
    expected: py.default_path,
    actual: node.default_path,
  });
  cases.push(
    ...literalCases(py.default_path, node.default_path, 'updatecheck: the default path hangs off the home directory, and a read creates nothing', {
      state: 'never',
      line: SENTENCES.never,
      path_under_home: `${RECORD_DIR}/${RECORD_NAME}`,
      home_listing: [],
      // The cwd's own `.bantamkit` is a memory store and is left alone: the reader never looked.
      cwd_listing: ['memory'],
    }),
  );

  // ---------------------------------------------------------------------------- the writers

  for (const write of WRITES) {
    const [p, n] = [py.writes[write.id], node.writes[write.id]];
    // What must NOT differ: whether it wrote, what it left in the directory, where it wrote, and
    // — for the merge arm — the key it did not own and the stamp it put on the record.
    cases.push({
      name: `updatecheck: ${write.id} — wrote or not, the directory afterwards, and the path used`,
      kind: 'json',
      expected: { raised: p.raised, wrote: p.wrote, listing: p.listing, path_under_home: p.path_under_home },
      actual: { raised: n.raised, wrote: n.wrote, listing: n.listing, path_under_home: n.path_under_home },
    });
  }
  const wrote = (side) => Object.fromEntries(WRITES.map((w) => [w.id, side[w.id].wrote]));
  cases.push(
    ...literalCases(wrote(py.writes), wrote(node.writes), 'updatecheck: which writer arms wrote, against the table', {
      'write/fresh': true,
      'write/merge': true,
      'write/unreadable-existing': true,
      // NO DIRECTORY IS EVER CREATED. `<homedir>/.bantamkit` is made by an install, and an
      // `--update` on a machine that never had one writes nothing rather than deciding where
      // this toolbox's home directory should be.
      'write/no-directory': false,
      'write/directory-is-a-file': false,
      'write/own-stamp': true,
    }),
  );
  const listings = (side) => Object.fromEntries(WRITES.map((w) => [w.id, side[w.id].listing]));
  cases.push(
    ...literalCases(listings(py.writes), listings(node.writes), 'updatecheck: the directory after each write — one record, and no temp file left behind', {
      'write/fresh': [RECORD_NAME],
      'write/merge': [RECORD_NAME],
      'write/unreadable-existing': [RECORD_NAME],
      'write/no-directory': null,
      'write/directory-is-a-file': null,
      'write/own-stamp': [RECORD_NAME],
    }),
  );

  // THE BYTES, with the three licensed strings spelled out of them: indentation, key order,
  // separators and the trailing newline are compared exactly.
  for (const id of ['write/fresh', 'write/unreadable-existing']) {
    cases.push({
      name: `updatecheck: ${id} — the same bytes but for the registry it names`,
      kind: 'bytes',
      expected: normaliseBody(py.writes[id].body),
      actual: normaliseBody(node.writes[id].body),
    });
  }
  cases.push(
    ...literalCases(
      normaliseBody(py.writes['write/fresh'].body),
      normaliseBody(node.writes['write/fresh'].body),
      'updatecheck: what a fresh record looks like, to the byte',
      `{\n  "checked_at": "${WRITE_NOW}",\n  "<key>": {\n    "<field>": "<name>",\n    "latest": "${WRITE_LATEST}"\n  }\n}\n`,
      'bytes',
    ),
  );

  // THE MERGE ARM IS THE COMPANION THAT MATTERS: the key each writer does not own is left
  // EXACTLY as found, and so is a key neither of them knows about. A writer that replaced the
  // whole record would destroy the other runtime's half of it on every `--update`.
  const otherKey = { py: 'npm', node: 'pypi' };
  // `?? {}` ON EVERY REACH INTO A WRITTEN RECORD: a runtime that stopped writing hands this
  // suite a `null` here, and a `TypeError` thrown while BUILDING cases costs the whole suite
  // (the runner reports "could not build its cases" and no case names itself). Measured on this
  // job's own mutation run. An empty object reddens the cases below by name instead.
  const merged = (side, which) => {
    const record = side.writes['write/merge'].record ?? {};
    const other = record[otherKey[which]] ?? {};
    return {
      key_order: Object.keys(record),
      checked_at: record.checked_at,
      // The other registry's entry names a DIFFERENT thing on each side (a package there, a
      // distribution here), so what travels is the part that must be equal: it still says
      // `0.30.0`, and it still has both of its fields. The entry itself is pinned per side.
      untouched_other_latest: other.latest,
      untouched_other_fields: Object.keys(other).length,
      untouched_stranger: record.extra,
      own_latest: (record[side.constants.KEY] ?? {}).latest ?? null,
      own_entry_fields: Object.keys(record[side.constants.KEY] ?? {}).length,
    };
  };
  cases.push({
    name: 'updatecheck: write/merge — the other registry, the stranger key, the stamp and the key order all survive',
    kind: 'json',
    expected: merged(py, 'py'),
    actual: merged(node, 'node'),
  });
  cases.push(
    ...literalCases(merged(py, 'py'), merged(node, 'node'), 'updatecheck: what a merge leaves behind, against a literal', {
      key_order: ['checked_at', 'npm', 'pypi', 'extra'],
      checked_at: WRITE_NOW,
      untouched_other_latest: '0.30.0',
      untouched_other_fields: 2,
      untouched_stranger: { kept: true },
      own_latest: WRITE_LATEST,
      own_entry_fields: 2,
    }),
  );
  // The entry each writer did NOT own, byte for byte, per side: the whole point of the merge is
  // that the other runtime's half of the record comes back out exactly as it went in.
  cases.push({
    name: 'updatecheck: write/merge — the reference left npm exactly as it found it',
    kind: 'json',
    expected: { package: NPM_PACKAGE, latest: '0.30.0' },
    actual: (py.writes['write/merge'].record ?? {}).npm ?? null,
  });
  cases.push({
    name: 'updatecheck: write/merge — the port left pypi exactly as it found it',
    kind: 'json',
    expected: { distribution: PYPI_DISTRIBUTION, latest: '0.30.0' },
    actual: (node.writes['write/merge'].record ?? {}).pypi ?? null,
  });

  // An UNREADABLE record is replaced rather than merged — there is nothing in it to preserve.
  const replaced = (side) => Object.keys(side.writes['write/unreadable-existing'].record ?? {}).length;
  cases.push(...literalCases(replaced(py), replaced(node), 'updatecheck: an unreadable record is replaced, not merged', 2, 'json'));

  // A `.bantamkit` that is a regular FILE is left exactly as it was: not opened, not replaced.
  const fileKept = (homesFor) => readFileSync(join(homesFor['write/directory-is-a-file'], RECORD_DIR), 'utf8');
  cases.push(
    ...literalCases(fileKept(homes.py), fileKept(homes.node), 'updatecheck: a regular file where the directory should be is not touched', 'a regular file where the toolbox directory should be\n', 'bytes'),
  );

  // The stamp's SHAPE, on the one arm that let each runtime use its own clock. The two clocks
  // cannot be compared; the shape they render is the thing that must be the same.
  const stamped = (side) => STAMP_SHAPE.test(String((side.writes['write/own-stamp'].record ?? {}).checked_at));
  cases.push(...literalCases(stamped(py), stamped(node), 'updatecheck: an unstamped write renders `YYYY-MM-DDTHH:MM:SSZ`', true));

  // ------------------------------------------------------------- the one deliberate difference

  cases.push({
    name: 'updatecheck: the registry key each runtime reads',
    kind: 'string',
    expected: py.constants.KEY,
    actual: node.constants.KEY,
    ruling:
      'RULED DIFFERENT, and carried in `docs/porting.md`. The record holds BOTH registries and ' +
      'each runtime reads its own: the reference is installed from PyPI and the port from npm, ' +
      'and the two indexes can disagree at one version number — job56 shipped a day where they ' +
      'did. A single shared key would make one of the two runtimes report the other ecosystem’s ' +
      'version as its own. This is the same genuinely-different-object as `--update`\'s index ' +
      'URL, not a new kind of one. What does NOT differ is compared unruled above: every arm is ' +
      'asked of both runtimes under BOTH keys, and under a given key the two answers are equal ' +
      'field for field, sentence included.',
  });
  cases.push({ name: 'updatecheck: the registry key against a literal — the reference', kind: 'string', expected: 'pypi', actual: py.constants.KEY });
  cases.push({ name: 'updatecheck: the registry key against a literal — the port', kind: 'string', expected: 'npm', actual: node.constants.KEY });

  const KEY_SENSITIVE = ['keys/disagree', 'keys/npm-only', 'keys/pypi-only'];
  cases.push({
    name: 'updatecheck: one record, two registries — the default-key answer on the three arms where they disagree',
    kind: 'json',
    expected: Object.fromEntries(KEY_SENSITIVE.map((id) => [id, { state: py.defaults[id].state, line: py.defaults[id].line }])),
    actual: Object.fromEntries(KEY_SENSITIVE.map((id) => [id, { state: node.defaults[id].state, line: node.defaults[id].line }])),
    ruling:
      'RULED DIFFERENT, the same row as the key above and its whole observable consequence. A ' +
      'record whose two registries disagree puts the two runtimes in two different STATES, ' +
      'which is correct: each is telling the operator about the index its own install came ' +
      'from. Pinned per side just below, because this case would stay green if both runtimes ' +
      'started reading some third key.',
  });
  cases.push({
    name: 'updatecheck: the default-key states on the three key-sensitive arms — the reference reads pypi',
    kind: 'json',
    expected: { 'keys/disagree': 'available', 'keys/npm-only': 'unreadable', 'keys/pypi-only': 'available' },
    actual: Object.fromEntries(KEY_SENSITIVE.map((id) => [id, py.defaults[id].state])),
  });
  cases.push({
    name: 'updatecheck: the default-key states on the three key-sensitive arms — the port reads npm',
    kind: 'json',
    expected: { 'keys/disagree': 'ahead', 'keys/npm-only': 'available', 'keys/pypi-only': 'unreadable' },
    actual: Object.fromEntries(KEY_SENSITIVE.map((id) => [id, node.defaults[id].state])),
  });

  const writtenEntry = (side) => {
    const record = side.writes['write/fresh'].record ?? {};
    const key = side.constants.KEY;
    return { key, field: Object.keys(record[key] ?? {}).find((f) => f !== 'latest') ?? null };
  };
  cases.push({
    name: 'updatecheck: the registry key each runtime WRITES, and the field naming the thing on it',
    kind: 'json',
    expected: writtenEntry(py),
    actual: writtenEntry(node),
    ruling:
      'RULED DIFFERENT, the writer half of the same row. `--update` records what it just ' +
      'fetched under the key of the registry it fetched it FROM, and names the thing that ' +
      'registry serves: PyPI serves a DISTRIBUTION called `bantamkit`, npm serves a PACKAGE ' +
      'called `bantamkit-mcp`. Neither name is a translation of the other and a shared field ' +
      'would be wrong on one side. What does not differ — the stamp, the key order, the ' +
      'indentation, the trailing newline, and the other registry\'s entry left exactly as ' +
      'found — is compared unruled above.',
  });
  cases.push({ name: 'updatecheck: the written entry against a literal — the reference', kind: 'json', expected: { key: 'pypi', field: 'distribution' }, actual: writtenEntry(py) });
  cases.push({ name: 'updatecheck: the written entry against a literal — the port', kind: 'json', expected: { key: 'npm', field: 'package' }, actual: writtenEntry(node) });

  // --------------------------------------------------------------------------------- notes

  notes.push(`${ARMS.length} arms over ${Object.keys(RECORDS).length} records and 4 path shapes, each answered under both registry keys by both runtimes, under ${records}`);
  notes.push(`${WRITES.length} writer arms, each side in its own scratch home; HOME and USERPROFILE are redirected for every arm on both sides, and the real ~/.bantamkit is never on any path here`);
  notes.push(`the available sentence (the port): ${JSON.stringify(node.answers.pypi['available/one-minor-behind'].line)}`);
  notes.push(`a fresh record (the reference): ${JSON.stringify(py.writes['write/fresh'].body)}`);

  return { cases, notes };
}
