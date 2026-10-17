/**
 * The B summaries (#200, E1-B, Task 6), port side. Mirrors `runtime-py/tests/test_touch_summary.py`,
 * so a Node-only regression is red here before `touch-summary` sees it.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  SUMMARY_MAX,
  TouchLog,
  ageText,
  capBytes,
  compactLine,
  findRepo,
  lastSessionLine,
  previousSession,
  shiftTs,
  uncommittedCount,
} from '../dist/touch/index.js';

const CLI = join(dirname(dirname(fileURLToPath(import.meta.url))), 'dist', 'cli.js');
const tmp = () => realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-touch-summary-')));

const r = (seq, path, op = 'edit', session = 'old', ts = null, extra = {}) => ({
  ts: ts || `2026-10-15T10:00:${String(seq).padStart(2, '0')}Z`,
  session,
  seq,
  op,
  path,
  ...extra,
});

const ROWS = [
  r(1, 'src/store.ts'),
  r(2, 'src/retrieval.ts', 'read'),
  r(3, 'src/retrieval.ts'),
  r(4, 'src/factfile.ts', 'write'),
  r(5, 'x.txt', 'write', 'old', null, { via: 'bash-turn', from: 4 }),
  r(6, 'y.txt'),
  r(7, 'now.py', 'edit', 'current', '2026-10-15T13:00:00Z'),
];
const base = (p) => p.split('/').at(-1);
const id = (p) => p;

test('ageText', () => {
  assert.deepEqual([5, 120, 3 * 3600, 3 * 86400].map(ageText), ['just now', '2 min ago', '3 h ago', '3 d ago']);
  assert.deepEqual(
    [59, 60, 3599, 3600, 172799, 172800, -5].map(ageText),
    ['just now', '1 min ago', '59 min ago', '1 h ago', '47 h ago', '2 d ago', 'just now'],
  );
});

test('previousSession skips the current session and folded rows; a tie goes to the smaller id', () => {
  const rows = [...ROWS, { ts: '2026-10-16T00:00:00Z', session: '', seq: 0, op: 'folded', path: 'p', n: 3 }];
  const [sid, mine] = previousSession(rows, 'current');
  assert.equal(sid, 'old');
  assert.equal(mine.length, 6);
  assert.equal(previousSession([r(1, 'a', 'edit', 'b'), r(1, 'a', 'edit', 'a'), r(1, 'a', 'edit', 'c')], 'x')[0], 'a');
  assert.equal(previousSession([r(1, 'a', 'edit', 's')], 's'), null);
});

test('the line shape, and silence', () => {
  const [, mine] = previousSession(ROWS, 'current');
  assert.equal(
    lastSessionLine(mine, '2026-10-15T13:00:06Z', base, ['feat: one (#199)', 'fix: two'], 4),
    '[bantamkit touch] last session here (2026-10-15, 3 h ago): edited 5 files — y.txt, x.txt, factfile.ts (+2); commits: feat: one (#199); fix: two; uncommitted: 4 files',
  );
  assert.equal(lastSessionLine([r(1, 'a', 'read')], '2026-10-15T13:00:00Z', id, [], 9), '');
});

test('zero edits with commits, and singulars', () => {
  assert.equal(
    lastSessionLine([r(1, 'a', 'read')], '2026-10-15T10:00:01Z', id, ['a', 'b', 'c', 'd', 'e'], 1),
    '[bantamkit touch] last session here (2026-10-15, just now): edited no files; commits: a; b; c (+2); uncommitted: 1 file',
  );
  assert.equal(lastSessionLine([r(1, 'a')], '2026-10-15T10:00:01Z', id, [], 0), '[bantamkit touch] last session here (2026-10-15, just now): edited 1 file — a');
});

test('the cap is 600 BYTES', () => {
  const [, mine] = previousSession(ROWS, 'current');
  const line = lastSessionLine(mine, '2026-10-15T13:00:06Z', (p) => 'ไทย'.repeat(40) + p, ['ก'.repeat(300), 'ก'.repeat(300), 'ก'.repeat(300)], 1);
  assert.ok(Buffer.byteLength(line) <= 600);
  assert.ok(!line.includes('�'), 'never split inside a character');
  const s600 = 'a'.repeat(597) + 'ก';
  assert.equal(capBytes(s600, SUMMARY_MAX), s600);
  assert.equal(capBytes('a'.repeat(598) + 'ก', SUMMARY_MAX), 'a'.repeat(598));
  assert.equal(capBytes('a'.repeat(599) + '😀', SUMMARY_MAX), 'a'.repeat(599));
});

test('a subject is cut at 60 bytes', () => {
  assert.ok(lastSessionLine([r(1, 'a')], '2026-10-15T10:00:01Z', id, ['ก'.repeat(30)], 0).endsWith('; commits: ' + 'ก'.repeat(20)));
});

test('compactLine lists edits only, at most ten', () => {
  const rows = [r(1, 'a.py', 'edit', 's'), r(2, 'b.py', 'read', 's'), r(3, 'c.py', 'write', 's')];
  assert.equal(compactLine(rows, 's', id), '[bantamkit touch] edited in this session before compaction: c.py, a.py');
  assert.equal(compactLine([r(1, 'a.py', 'read', 's')], 's', id), '');
  const twelve = Array.from({ length: 12 }, (_, i) => r(i + 1, `f${String(i + 1).padStart(2, '0')}.py`, 'edit', 's'));
  const names = Array.from({ length: 10 }, (_, i) => `f${String(12 - i).padStart(2, '0')}.py`).join(', ');
  assert.equal(compactLine(twelve, 's', id), `[bantamkit touch] edited in this session before compaction: ${names} (+2)`);
});

test('shiftTs and uncommittedCount', () => {
  assert.equal(shiftTs('2026-10-15T23:50:00Z', 1800), '2026-10-16T00:20:00Z');
  assert.equal(uncommittedCount('R  b.txt\0ab c.txt\0 M d.txt\0?? e.txt\0'), 3);
  assert.equal(uncommittedCount(''), 0);
});

// ------------------------------------------------------------------- the hook, as a process

function g(repo, args, date = null) {
  const env = { ...process.env, ...(date ? { GIT_COMMITTER_DATE: date, GIT_AUTHOR_DATE: date } : {}) };
  const x = spawnSync('git', ['-C', repo, ...args], { encoding: 'utf8', env });
  assert.equal(x.status, 0, x.stderr);
}

function bed() {
  const d = tmp();
  const home = join(d, 'home');
  mkdirSync(home);
  const R = join(d, 'repo');
  mkdirSync(R);
  g(R, ['init', '-q']);
  g(R, ['config', 'user.email', 't@t']);
  g(R, ['config', 'user.name', 't']);
  for (const f of ['src/store.ts', 'src/retrieval.ts', 'lib/store.ts', 'a.txt', 'b.txt']) {
    mkdirSync(dirname(join(R, f)), { recursive: true });
    writeFileSync(join(R, f), '1\n');
  }
  g(R, ['add', '.']);
  g(R, ['commit', '-qm', 'before the session'], '2026-10-15T09:00:00Z');
  writeFileSync(join(R, 'a.txt'), '2\n');
  g(R, ['commit', '-qam', 'J68-3 keywords (#199)'], '2026-10-15T10:20:00Z');
  writeFileSync(join(R, 'b.txt'), '3\n');
  g(R, ['mv', 'a.txt', 'c.txt']);
  const log = new TouchLog(home, findRepo(R).id);
  log.appendTouch('old', 1, 'edit', 'src/store.ts', null, null, '2026-10-15T10:00:01Z');
  log.appendTouch('old', 2, 'read', 'src/retrieval.ts', null, null, '2026-10-15T10:00:02Z');
  log.appendTouch('old', 3, 'write', 'b.txt', null, null, '2026-10-15T10:00:03Z');
  log.appendTouch('now', 1, 'edit', 'src/retrieval.ts', null, null, '2026-10-17T10:00:00Z');
  return { home, R };
}

function sessionStart(home, cwd, source) {
  const env = { ...process.env, HOME: home, USERPROFILE: home, TZ: 'Asia/Bangkok' };
  delete env.BANTAMKIT_MEMORY_DIR;
  const payload = { hook_event_name: 'SessionStart', source, session_id: 'now', cwd };
  const x = spawnSync(process.execPath, [CLI, '--hook'], { cwd, env, input: JSON.stringify(payload), encoding: 'utf8', timeout: 120_000 });
  assert.equal(x.status, 0, x.stderr);
  const ctx = JSON.parse(x.stdout).hookSpecificOutput.additionalContext;
  const recs = readFileSync(join(home, '.bantamkit', 'hooks', 'hook-log.jsonl'), 'utf8')
    .split('\n')
    .filter((l) => l.includes('"SessionStart"'))
    .map((l) => JSON.parse(l));
  return { ctx, rec: recs.at(-1) };
}

test('hook: startup appends the line just before the toolbox part; git reads the window as UTC', () => {
  const { home, R } = bed();
  const { ctx, rec } = sessionStart(home, R, 'startup');
  const parts = ctx.split('\n\n');
  const i = parts.findIndex((p) => p.startsWith('[bantamkit touch]'));
  assert.ok(i >= 0, ctx);
  assert.ok(parts[i + 1].startsWith('[bantamkit] Toolbox is live'));
  assert.equal(
    parts[i].replace(/\d+ (min|h|d) ago|just now/g, '<age>'),
    '[bantamkit touch] last session here (2026-10-15, <age>): edited 2 files — b.txt, src/store.ts; commits: J68-3 keywords (#199); uncommitted: 2 files',
  );
  assert.equal(rec.touchBytes, Buffer.byteLength(parts[i]));
});

test('hook: compact lists this session’s edits', () => {
  const { home, R } = bed();
  const { ctx, rec } = sessionStart(home, R, 'compact');
  const line = '[bantamkit touch] edited in this session before compaction: retrieval.ts';
  assert.ok(ctx.split('\n\n').includes(line), ctx);
  assert.equal(rec.touchBytes, Buffer.byteLength(line));
});

test('hook: outside a repo, nothing', () => {
  const d = tmp();
  const home = join(d, 'home');
  const cwd = join(d, 'plain');
  mkdirSync(home);
  mkdirSync(cwd);
  const { ctx, rec } = sessionStart(home, cwd, 'startup');
  assert.ok(!ctx.includes('[bantamkit touch]'));
  assert.equal(rec.touchBytes, 0);
});
