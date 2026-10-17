/**
 * Retention (#204, S4; job69 J69-6): the same trap fixture and tests as
 * runtime-py/tests/test_storage_retention.py. `storage-retention` conformance runs one fixture
 * through both runtimes and compares the trees and the reports.
 *
 * THE BAR: zero files deleted that are not verified in an archive or past their TTL. Every test
 * asserts the whole tree before and after as `{relative path: sha256}`.
 *
 * `scripts/run-tests.mjs` sets `BANTAMKIT_RETENTION=off` for the run; `bed()` deletes it and
 * points HOME at the scratch bed for the duration of each test, so nothing here can reach the
 * operator's home.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import * as retention from '../dist/storage/retention.js';
import { ColdIndex } from '../dist/storage/index.js';
import * as shiftwork from '../dist/shiftwork.js';
import { toJs } from '../dist/pyjson.js';

const NOW = '2026-10-16T00:00:00.000Z';
const NOW_S = retention.parseNow(NOW) / 1000;
const DAY = 86_400;

const units = (...statuses) =>
  statuses.map((s, i) => ({
    id: `U${i + 1}`,
    title: `unit ${i + 1}`,
    brief_path: `b${i + 1}.md`,
    status: s,
    role: 'implementer',
    depends_on: [],
    verify: 'true',
  }));
const cp = (goal, ...statuses) =>
  Buffer.from(
    JSON.stringify(
      {
        version: 1,
        job: { id: goal, goal, done_definition: 'd', constraints: [] },
        state: { repo: { branch: 'b', head_sha: 'h', dirty: false }, artifacts: [], external: [] },
        plan: { cursor: 'U1', units: units(...statuses) },
        handoff: { next_action: 'x', open_questions: [], do_not: [], notes: '' },
        history: [],
        retro: [],
      },
      null,
      2,
    ),
  );
const B = (s) => Buffer.from(s, 'utf8');

function trapFiles() {
  const ledger = B('{"seen":{}}');
  const hook = B(
    [
      { ts: '2026-09-06T10:00:00.000Z', ms: 1, event: 'SessionStart' },
      { ts: '2026-09-06T11:00:00.000Z', ms: 1, event: 'SessionStart' },
      { ts: '2026-09-06T12:00:00.000Z', ms: 1, event: 'PostToolUse', tool: 'Read' },
      { ts: '2026-09-15T12:00:00.000Z', ms: 1, event: 'UserPromptSubmit' },
      { ts: '2026-09-20T12:00:00.000Z', ms: 1, event: 'Stop' },
    ]
      .map((r) => `${JSON.stringify(r)}\n`)
      .join(''),
  );
  const usage = B(
    '{"ts":"2026-09-01T00:00:00Z","fact":"f1","kind":"recall_hit"}\n' +
      '{"ts":"2026-09-02T00:00:00Z","fact":"f1","kind":"save","keywords":["k"]}\n' +
      '{"ts":"2026-10-10T00:00:00Z","fact":"f1","kind":"body_read"}\n',
  );
  const sw = 'a/.shiftwork';
  return [
    ['home/.bantamkit/hooks/ledger-old.json', ledger, 8],
    ['home/.bantamkit/hooks/ledger-new.json', ledger, 6],
    ['home/.bantamkit/hooks/ledger-edge.json', ledger, 7],
    ['home/.bantamkit/hooks/ledger-notes.txt', ledger, 30],
    ['home/.bantamkit/hooks/hook-log.jsonl', hook, 0],
    ['home/.bantamkit/usage/aaaa.jsonl', usage, 0],
    ['home/.bantamkit/usage/idle.jsonl', B('{"ts":"2026-09-10T00:00:00Z","fact":"g","kind":"seed"}\n'), 31],
    ['home/.bantamkit/memory/facts/keep.md', B('---\nname: keep\n---\n'), 400],
    [`${sw}/checkpoint-open.json`, cp('open', 'done', 'todo'), 30],
    [`${sw}/briefs-open/U1.md`, B('open brief\n'), 30],
    [`${sw}/checkpoint-closed8.json`, cp('closed eight release', 'done', 'dropped'), 8],
    [`${sw}/checkpoint-closed8.json.log.jsonl`, B('{"brief":"U1"}\n'), 8],
    [`${sw}/briefs-closed8/U1.md`, B('brief ไทย release notes\nsecond line\n'), 8],
    [`${sw}/notes-closed8/sub/U1.md`, B('note: release tag measured\n'), 9],
    [`${sw}/notes-closed8/bin.dat`, Buffer.from([0xff, 0xfe, 0x00, 0x72, 0x61, 0x77]), 8],
    [`${sw}/checkpoint-closed6.json`, cp('closed six', 'done'), 6],
    [`${sw}/checkpoint-mixed.json`, cp('mixed', 'done'), 8],
    [`${sw}/notes-mixed/late.md`, B('late\n'), 6],
    [`${sw}/checkpoint-bad.json`, B('{not json'), 30],
    [`${sw}/checkpoint-empty.json`, cp('empty'), 30],
    [`${sw}/checkpoint-clash.json`, cp('clash', 'done'), 8],
    [`${sw}/archive/clash.json.gz`, zlib.gzipSync(B('{}')), 8],
    [`${sw}/checkpoint.json`, cp('bare', 'dropped'), 8],
    [`${sw}/backlog.md`, B('backlog\n'), 30],
    ['b/.shiftwork/checkpoint-blocked.json', cp('blocked', 'done'), 8],
    ['b/.shiftwork/archive', B('a file where the archive dir goes\n'), 8],
  ];
}

function tree(base) {
  const out = {};
  const walk = (d) => {
    for (const n of fs.readdirSync(d)) {
      const p = path.join(d, n);
      if (fs.statSync(p).isDirectory()) walk(p);
      else if (!n.endsWith('.lock')) out[path.relative(base, p).split(path.sep).join('/')] = createHash('sha256').update(fs.readFileSync(p)).digest('hex');
    }
  };
  walk(base);
  return out;
}

/** A scratch bed with the trap fixture; retention ON and HOME pointed at the bed until `t` ends. */
function bed(t) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'retention-')));
  for (const [rel, data, age] of trapFiles()) {
    const p = path.join(base, rel);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, data);
    const when = NOW_S - Math.trunc(age * DAY);
    fs.utimesSync(p, when, when);
  }
  const saved = { r: process.env.BANTAMKIT_RETENTION, h: process.env.HOME, u: process.env.USERPROFILE, i: process.env.BANTAMKIT_INDEX_DIR };
  delete process.env.BANTAMKIT_RETENTION;
  process.env.HOME = path.join(base, 'home');
  process.env.USERPROFILE = path.join(base, 'home');
  process.env.BANTAMKIT_INDEX_DIR = path.join(base, 'idx');
  t.after(() => {
    const put = (k, v) => (v === undefined ? delete process.env[k] : (process.env[k] = v));
    put('BANTAMKIT_RETENTION', saved.r);
    put('HOME', saved.h);
    put('USERPROFILE', saved.u);
    put('BANTAMKIT_INDEX_DIR', saved.i);
  });
  return base;
}

const run = (base) => retention.runRetention(path.join(base, 'home'), [path.join(base, 'a'), path.join(base, 'b')], NOW);

const ARCHIVED_AWAY = [
  'a/.shiftwork/checkpoint-closed8.json',
  'a/.shiftwork/checkpoint-closed8.json.log.jsonl',
  'a/.shiftwork/briefs-closed8/U1.md',
  'a/.shiftwork/notes-closed8/sub/U1.md',
  'a/.shiftwork/notes-closed8/bin.dat',
  'a/.shiftwork/checkpoint.json',
];
const CHANGED = new Set(['home/.bantamkit/hooks/hook-log.jsonl', 'home/.bantamkit/usage/aaaa.jsonl', 'home/.bantamkit/usage/idle.jsonl']);

test('the trap fixture deletes only what is past its TTL or verified in an archive', (t) => {
  const base = bed(t);
  const before = tree(base);
  const report = run(base);
  const after = tree(base);
  const gone = Object.keys(before).filter((r) => !(r in after)).sort();
  assert.deepEqual(gone, [...ARCHIVED_AWAY, 'home/.bantamkit/hooks/ledger-old.json'].sort());
  for (const r of Object.keys(before)) if (r in after && !CHANGED.has(r)) assert.equal(after[r], before[r], r);
  const fresh = Object.keys(after).filter((r) => !(r in before) && !r.startsWith('idx/')).sort();
  assert.deepEqual(fresh, ['a/.shiftwork/archive/checkpoint.json.gz', 'a/.shiftwork/archive/closed8.json.gz', 'home/.bantamkit/usage/idle.jsonl.1.gz']);
  const files = new Map(trapFiles().map(([r, d]) => [r, d]));
  for (const job of ['closed8', 'checkpoint']) {
    const bundle = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(base, 'a/.shiftwork/archive', `${job}.json.gz`))).toString('utf8'));
    for (const [r, v] of Object.entries(bundle)) {
      const got = typeof v === 'string' ? B(v) : Buffer.from(v.base64, 'base64');
      assert.ok(got.equals(files.get(`a/${r}`)), r);
    }
  }
  assert.equal(fs.existsSync(path.join(base, 'a/.shiftwork/briefs-closed8')), false);
  assert.equal(fs.existsSync(path.join(base, 'a/.shiftwork/notes-closed8')), false);
  assert.deepEqual(report.deleted, [path.join(base, 'home/.bantamkit/hooks/ledger-old.json')]);
  assert.deepEqual(report.refused, [
    { path: path.join(base, 'a/.shiftwork/archive/clash.json.gz'), reason: 'archive exists and differs' },
    { path: path.join(base, 'b/.shiftwork/checkpoint-blocked.json'), reason: 'archive write failed' },
  ]);
  assert.deepEqual(report.archived, [path.join(base, 'a/.shiftwork/archive/closed8.json.gz'), path.join(base, 'a/.shiftwork/archive/checkpoint.json.gz')]);
  assert.deepEqual(report.rotated, [path.join(base, 'home/.bantamkit/usage/idle.jsonl')]);
});

test('the hook log folds to one row per day and keeps newer lines as read', (t) => {
  const base = bed(t);
  run(base);
  assert.deepEqual(fs.readFileSync(path.join(base, 'home/.bantamkit/hooks/hook-log.jsonl'), 'utf8').split('\n').filter(Boolean), [
    '{"ts":"2026-09-06T00:00:00.000Z","event":"Folded","counts":{"PostToolUse/Read":1,"SessionStart":2}}',
    '{"ts":"2026-09-15T00:00:00.000Z","event":"Folded","counts":{"UserPromptSubmit":1}}',
    '{"ts":"2026-09-20T12:00:00.000Z","ms":1,"event":"Stop"}',
  ]);
});

test('an archive write that fails deletes nothing and is refused', (t) => {
  const base = bed(t);
  const real = retention.retentionFs.writeArchive;
  retention.retentionFs.writeArchive = () => {
    throw Object.assign(new Error('disk full'), { code: 'ENOSPC' });
  };
  t.after(() => {
    retention.retentionFs.writeArchive = real;
  });
  const before = tree(base);
  const report = run(base);
  const after = tree(base);
  for (const r of ARCHIVED_AWAY) assert.equal(after[r], before[r], r);
  assert.ok(report.refused.some((x) => x.reason === 'archive write failed'));
  assert.deepEqual(report.archived, []);
});

test('a file written while its job is bundled keeps the job whole (J69-8)', (t) => {
  // A live session writes a job file between the bundle and the delete: nothing of the job is
  // deleted, the archive this run wrote is removed, the job is refused `changed since bundled`.
  const base = bed(t);
  const real = retention.retentionFs.writeArchive;
  const note = path.join(base, 'a/.shiftwork/notes-closed8/sub/U1.md');
  retention.retentionFs.writeArchive = (target, data) => {
    real(target, data);
    if (path.basename(target) === 'closed8.json.gz') fs.appendFileSync(note, 'written by a live session\n');
  };
  t.after(() => {
    retention.retentionFs.writeArchive = real;
  });
  const report = run(base);
  const after = tree(base);
  for (const r of ARCHIVED_AWAY.filter((x) => x !== 'a/.shiftwork/checkpoint.json')) assert.ok(r in after, r);
  assert.ok(fs.readFileSync(note, 'utf8').endsWith('written by a live session\n'));
  assert.equal(fs.existsSync(path.join(base, 'a/.shiftwork/archive/closed8.json.gz')), false);
  assert.ok(report.refused.some((x) => x.reason === 'changed since bundled' && x.path === path.join(base, 'a/.shiftwork/checkpoint-closed8.json')));
  assert.ok(!report.archived.includes(path.join(base, 'a/.shiftwork/archive/closed8.json.gz')));
});

test('every archive written is synced to the disk (J69-8)', (t) => {
  // A read-back is served from the page cache: the archive is fsynced, and its directory on
  // POSIX, inside the write, which runs before the verify and the unlinks.
  const base = bed(t);
  const before = retention.retentionFs.syncs;
  const report = run(base);
  assert.ok(report.archived.length > 0);
  const per = process.platform === 'win32' ? 1 : 2;
  assert.equal(retention.retentionFs.syncs - before, per * report.archived.length);
});

test('an archive that reads back wrong deletes nothing', (t) => {
  const base = bed(t);
  const real = retention.retentionFs.writeArchive;
  retention.retentionFs.writeArchive = (target, data) => real(target, Buffer.concat([data, B(' ')]));
  t.after(() => {
    retention.retentionFs.writeArchive = real;
  });
  const before = tree(base);
  const report = run(base);
  const after = tree(base);
  for (const r of ARCHIVED_AWAY) assert.equal(after[r], before[r], r);
  assert.ok(report.refused.some((x) => x.reason === 'archive did not verify'));
});

test('opt-out changes nothing', (t) => {
  const base = bed(t);
  process.env.BANTAMKIT_RETENTION = 'off';
  const before = tree(base);
  const report = run(base);
  assert.deepEqual(tree(base), before);
  assert.deepEqual(report, { archived: [], compacted: [], deleted: [], folded: [], refused: [], rotated: [] });
  assert.equal(retention.maybeSpawn(path.join(base, 'home'), path.join(base, 'a')), 'off');
  assert.equal(retention.childMain([path.join(base, 'a'), path.join(base, 'home')], NOW), 0);
  assert.equal(fs.existsSync(path.join(base, 'home/.bantamkit/retention.json')), false);
});

test('a second run is a no-op on the tree', (t) => {
  const base = bed(t);
  run(base);
  const once = tree(base);
  run(base);
  assert.deepEqual(tree(base), once);
});

test('the TTL is once a day', (t) => {
  const base = bed(t);
  const home = path.join(base, 'home');
  assert.equal(retention.due(home, NOW), true);
  assert.equal(retention.childMain([path.join(base, 'a'), home], NOW), 0);
  const state = JSON.parse(fs.readFileSync(path.join(home, '.bantamkit/retention.json'), 'utf8'));
  assert.equal(state.ran_at, NOW);
  assert.ok(state.report.archived.length > 0);
  assert.equal(retention.due(home, '2026-10-16T23:59:59.999Z'), false);
  assert.equal(retention.due(home, '2026-10-17T00:00:00.000Z'), true);
  assert.equal(retention.due(home, '2026-10-15T00:00:00.000Z'), true);
  // maybeSpawn reads the wall clock, so re-stamp the run at the real now: a run within the
  // last 24 h is fresh (pinning NOW here failed the day after NOW, 2026-10-17).
  state.ran_at = retention.nowStamp();
  fs.writeFileSync(path.join(home, '.bantamkit/retention.json'), JSON.stringify(state));
  assert.equal(retention.maybeSpawn(home, path.join(base, 'a')), 'fresh');
});

test('no home means no child and no directory', (t) => {
  const d = bed(t);
  const bare = path.join(d, 'bare');
  fs.mkdirSync(bare);
  assert.equal(retention.maybeSpawn(bare, bare), 'nohome');
  assert.equal(retention.childMain([bare, bare], NOW), 0);
  assert.equal(fs.existsSync(path.join(bare, '.bantamkit')), false);
});

test('the server stands down when a hook ran within the TTL', (t) => {
  const d = bed(t);
  const home = path.join(d, 'h2');
  fs.mkdirSync(path.join(home, '.bantamkit', 'hooks'), { recursive: true });
  fs.writeFileSync(path.join(home, '.bantamkit', 'hooks', 'hook-log.jsonl'), '{}\n');
  assert.equal(retention.maybeSpawn(home, home, { server: true }), 'hooked');
  fs.writeFileSync(path.join(home, '.bantamkit', 'retention.json'), JSON.stringify({ ran_at: retention.nowStamp() }));
  assert.equal(retention.maybeSpawn(home, home), 'fresh');
});

test('the spawned child runs detached against the given home', async (t) => {
  const base = bed(t);
  const home = path.join(base, 'home');
  assert.equal(retention.maybeSpawn(home, path.join(base, 'a')), 'spawned');
  const state = path.join(home, '.bantamkit/retention.json');
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    if (fs.existsSync(state) && fs.readFileSync(state, 'utf8').includes('report')) break;
    await new Promise((r) => setTimeout(r, 50));
  }
  const report = JSON.parse(fs.readFileSync(state, 'utf8')).report;
  assert.ok(report.archived.includes(path.join(base, 'a/.shiftwork/archive/closed8.json.gz')));
});

test('compact prunes names whose file is gone, and search finds archived lines', (t) => {
  const base = bed(t);
  run(base);
  const cpPath = path.join(base, 'a/.shiftwork/checkpoint-open.json');
  const hits = toJs(shiftwork.status(cpPath, 'release notes'));
  assert.deepEqual(hits.search, [{ job: 'closed8', file: '.shiftwork/briefs-closed8/U1.md', line: 1 }]);
  assert.equal('search' in toJs(shiftwork.status(cpPath)), false);
  const cold = retention.shiftworkCold(path.join(base, 'home'), path.join(base, 'a'));
  assert.deepEqual([...cold.docs().keys()].sort(), ['checkpoint', 'clash', 'closed8']);
  cold.add(new Map([['ghost', { ...cold.doc('closed8'), name: 'ghost', file: '.shiftwork/archive/ghost.json.gz' }]]));
  const report = run(base);
  assert.ok(report.compacted.includes(cold.name));
  assert.deepEqual([...cold.docs().keys()].sort(), ['checkpoint', 'clash', 'closed8']);
  assert.equal(cold.manifest().segments.length, 1);
});

test('compact without keep is unchanged', () => {
  const d = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'retention-c-')));
  const cold = new ColdIndex('t', d);
  const doc = { file: 'x', name: 'x', description: 'd', type: 't', keywords: [], links: [], tags: [], refs: [], mtime_ns: '0', size: 0 };
  cold.add(new Map([['x', doc]]));
  assert.equal(cold.compact(), null);
  assert.equal(cold.compact(() => true), null);
  assert.equal(cold.compact(() => false), '000002');
  assert.equal(cold.docs().size, 0);
});
