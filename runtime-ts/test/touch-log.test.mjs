/**
 * The touch log, the per-session counter and the repo finder (#200, Task 1), port side. Mirrors
 * `runtime-py/tests/test_touch_log.py` and the three touch tests at the end of
 * `test_hookadapter.py`, so a Node-only regression is red here before `touch-log` sees it.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { appendFileSync, chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, statSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { TOUCH_LOG_CAP_BYTES, TOUCH_LOG_FOLD_TARGET_BYTES, TOUCH_TAIL_BYTES, TouchLog, boundBody, currentSeq, findRepo, foldCutoff, gitOnPath, nextSeq, relPath, touchReducer, useNames } from '../dist/touch/index.js';

const CLI = join(dirname(dirname(fileURLToPath(import.meta.url))), 'dist', 'cli.js');
const tmp = () => realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-touch-log-')));

function gitRepo(d) {
  const r = join(d, 'repo');
  mkdirSync(join(r, 'src'), { recursive: true });
  const g = spawnSync('git', ['init', '-q', r]);
  assert.equal(g.status, 0, String(g.stderr));
  writeFileSync(join(r, 'src', 'a.py'), 'x\n');
  return r;
}

function hook(payload, { home, cwd }) {
  return spawnSync(process.execPath, [CLI, '--hook'], {
    input: JSON.stringify({ cwd, session_id: 's1', ...payload }),
    encoding: 'utf8',
    env: { ...process.env, HOME: home, USERPROFILE: home },
  });
}

test('findRepo walks up and ids the realpath', () => {
  const d = tmp();
  const r = gitRepo(d);
  const found = findRepo(join(r, 'src'));
  assert.ok(found !== null && found.top === realpathSync.native(r) && found.id.length === 16);
  assert.equal(findRepo(d), null);
});

test('findRepo reads a gitdir file', () => {
  const d = tmp();
  mkdirSync(join(d, 'wt', 'deep'), { recursive: true });
  mkdirSync(join(d, 'real-gitdir'));
  writeFileSync(join(d, 'wt', '.git'), 'gitdir: ../real-gitdir\n');
  const found = findRepo(join(d, 'wt', 'deep'));
  assert.ok(found !== null && found.top === join(d, 'wt'));
  assert.equal(found.gitdir, join(d, 'real-gitdir'));
});

test('relPath is slash separated and null outside', () => {
  const d = tmp();
  const r = gitRepo(d);
  const repo = findRepo(r);
  assert.equal(relPath(repo, join(r, 'src', 'a.py')), 'src/a.py');
  assert.equal(relPath(repo, join(d, 'elsewhere.py')), null);
  assert.equal(relPath(repo, r), null);
});

test('touch line bytes', () => {
  const log = new TouchLog(join(tmp(), 'home'), '0123456789abcdef');
  assert.equal(log.appendTouch('s1', 3, 'edit', 'src/a.py', null, null, '2026-10-16T00:00:00Z'), true);
  assert.equal(log.appendTouch('s1', 9, 'write', 'b.txt', 'bash-turn', 4, '2026-10-16T00:00:01Z'), true);
  assert.equal(log.appendUse('s1', 10, 'fact-a', 'recall_hit', '2026-10-16T00:00:02Z'), true);
  assert.deepEqual(readFileSync(log.path, 'utf8').split('\n').filter(Boolean), [
    '{"ts":"2026-10-16T00:00:00Z","session":"s1","seq":3,"op":"edit","path":"src/a.py"}',
    '{"ts":"2026-10-16T00:00:01Z","session":"s1","seq":9,"op":"write","path":"b.txt","via":"bash-turn","from":4}',
    '{"ts":"2026-10-16T00:00:02Z","session":"s1","seq":10,"op":"use","fact":"fact-a","kind":"recall_hit"}',
  ]);
});

test('tail is this session after seq', () => {
  const log = new TouchLog(join(tmp(), 'home'), '0123456789abcdef');
  for (const [seq, session] of [[1, 's1'], [2, 's2'], [5, 's1'], [6, 's1']]) {
    log.appendTouch(session, seq, 'read', `f${seq}`, null, null, '2026-10-16T00:00:00Z');
  }
  assert.deepEqual(log.tail('s1', 1).map((r) => r.seq), [5, 6]);
});

test('tail drops the line the seek cut', () => {
  const log = new TouchLog(join(tmp(), 'home'), '0123456789abcdef');
  let n = 0;
  while (!existsSync(log.path) || statSync(log.path).size <= TOUCH_TAIL_BYTES) {
    n += 1;
    log.appendTouch('s1', n, 'read', 'p'.repeat(40), null, null, '2026-10-16T00:00:00Z');
  }
  const rows = log.tail('s1', 0);
  assert.ok(log.skipped === 0 && rows[rows.length - 1].seq === n && rows[0].seq > 1);
});

test('corrupt line is skipped and counted', () => {
  const log = new TouchLog(join(tmp(), 'home'), '0123456789abcdef');
  log.appendTouch('s1', 1, 'read', 'a', null, null, '2026-10-16T00:00:00Z');
  appendFileSync(log.path, '{not json\n');
  assert.equal(log.read().length, 1);
  assert.equal(log.skipped, 1);
});

test('unwritable log answers false', () => {
  const home = join(tmp(), 'home');
  mkdirSync(join(home, '.bantamkit'), { recursive: true });
  writeFileSync(join(home, '.bantamkit', 'touch'), 'a file, not a dir');
  const log = new TouchLog(home, '0123456789abcdef');
  assert.equal(log.appendTouch('s', 1, 'read', 'a'), false);
  assert.equal(log.appendUse('s', 1, 'f', 'save'), false);
});

test('seq counts up per session', () => {
  const state = join(tmp(), 'state');
  assert.equal(currentSeq(state, 's1'), 0);
  assert.deepEqual([1, 2, 3].map(() => nextSeq(state, 's1')), [1, 2, 3]);
  assert.equal(nextSeq(state, 's2'), 1);
  assert.equal(currentSeq(state, 's1'), 3);
  assert.equal(readFileSync(join(state, 'ledger-s1.seq.json'), 'utf8'), '{"seq":3}');
  assert.equal(nextSeq(state, 'a/b.c'), 1);
  assert.ok(existsSync(join(state, 'ledger-a_b_c.seq.json')));
});

test('useNames from a recall reply and a save', () => {
  const reply = '[project] [fact-a] (project) d\nbody\n\n[profile] [fact-b] (feedback) e\nbody [x] (y) z';
  const blocks = [{ type: 'text', text: reply }];
  assert.deepEqual(useNames('mcp__bantamkit__memory_recall', { query: 'q' }, blocks), [
    ['fact-a', 'recall_hit'],
    ['fact-b', 'recall_hit'],
  ]);
  assert.deepEqual(useNames('mcp__bantamkit__memory_recall', {}, { content: blocks })[0], ['fact-a', 'recall_hit']);
  assert.deepEqual(useNames('mcp__bantamkit__memory_recall', {}, '[solo] (user) one-layer header\nb'), [['solo', 'recall_hit']]);
  assert.deepEqual(useNames('mcp__bantamkit__memory_save', { name: 'n1' }, 'saved'), [['n1', 'save']]);
  assert.deepEqual(useNames('Bash', { command: 'ls' }, 'x'), []);
});

test('useNames starts a line after a newline only', () => {
  for (const sep of ['\r', ' ', ' ']) {
    assert.deepEqual(useNames('mcp__bantamkit__memory_recall', {}, `x${sep}[f] (user) d`), []);
  }
});

test('reducer keeps the last touch per path and drops uses', () => {
  const rows = [
    { ts: '2026-09-01T00:00:00Z', session: 'a', seq: 1, op: 'read', path: 'p' },
    { ts: '2026-09-02T00:00:00Z', session: 'a', seq: 2, op: 'edit', path: 'p' },
    { ts: '2026-09-03T00:00:00Z', session: 'a', seq: 3, op: 'use', fact: 'f', kind: 'save' },
  ];
  assert.deepEqual(touchReducer(rows), [{ ts: '2026-09-02T00:00:00Z', session: '', seq: 0, op: 'folded', path: 'p', n: 2 }]);
});

test('reducer of a fold is the same fold', () => {
  const rows = [
    { ts: '2026-09-01T00:00:00Z', session: 'a', seq: 1, op: 'read', path: 'b' },
    { ts: '2026-09-02T00:00:00Z', session: 'a', seq: 2, op: 'edit', path: 'a' },
    { ts: '2026-09-03T00:00:00Z', session: 'a', seq: 3, op: 'edit', path: 'a' },
  ];
  const once = touchReducer(rows);
  assert.deepEqual(once.map((r) => [r.path, r.n]), [['a', 2], ['b', 1]]);
  assert.deepEqual(touchReducer(once), once);
});

test('PostToolUse records an Edit and never a Bash', () => {
  const d = tmp();
  const home = join(d, 'home');
  mkdirSync(home);
  const r = gitRepo(d);
  for (const [tool, ti] of [
    ['Edit', { file_path: join(r, 'src', 'a.py') }],
    ['Bash', { command: 'cat src/a.py' }],
    ['Read', { file_path: join(r, 'src', 'a.py') }],
  ]) {
    const done = hook({ hook_event_name: 'PostToolUse', tool_name: tool, tool_input: ti }, { home, cwd: r });
    assert.equal(done.status, 0, done.stderr);
    assert.equal(done.stdout, '');
  }
  const dir = join(home, '.bantamkit', 'touch');
  const [name] = readdirSync(dir).filter((n) => n.endsWith('.jsonl'));
  const lines = readFileSync(join(dir, name), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  assert.deepEqual(lines.map((x) => [x.op, x.path, x.seq]), [
    ['edit', 'src/a.py', 1],
    ['read', 'src/a.py', 3],
  ]);
});

test('PostToolUse outside a repo records nothing', () => {
  const d = tmp();
  const home = join(d, 'home');
  const plain = join(d, 'plain');
  mkdirSync(home);
  mkdirSync(plain);
  hook({ hook_event_name: 'PostToolUse', tool_name: 'Edit', tool_input: { file_path: join(plain, 'a.py') } }, { home, cwd: plain });
  assert.equal(existsSync(join(home, '.bantamkit', 'touch')), false);
  assert.equal(existsSync(join(home, '.bantamkit', 'hooks', 'ledger-s1.seq.json')), false);
});

test('PostToolUse with an unwritable touch log is a logged miss', () => {
  const d = tmp();
  const home = join(d, 'home');
  mkdirSync(join(home, '.bantamkit'), { recursive: true });
  writeFileSync(join(home, '.bantamkit', 'touch'), 'a file, not a dir');
  const r = join(d, 'repo');
  mkdirSync(r);
  assert.equal(spawnSync('git', ['init', '-q', r]).status, 0);
  const done = hook({ hook_event_name: 'PostToolUse', tool_name: 'Read', tool_input: { file_path: join(r, 'x') } }, { home, cwd: r });
  assert.equal(done.status, 0);
  assert.equal(done.stdout, '');
  assert.equal(done.stderr, '');
  const misses = readFileSync(join(home, '.bantamkit', 'hooks', 'hook-log.jsonl'), 'utf8')
    .split('\n')
    .filter(Boolean)
    .map((l) => JSON.parse(l))
    .filter((x) => x.touch === 'miss');
  assert.equal(misses.length, 1);
  assert.deepEqual([misses[0].event, misses[0].touch, misses[0].tool], ['PostToolUse', 'miss', 'Read']);
});

// --- T200-10: git on PATH by stats, the log bounded on append (test_touch_log.py's mirror)

test('gitOnPath is a stat walk', () => {
  const d = tmp();
  const [exe, plain, win] = ['exe', 'plain', 'win'].map((n) => join(d, n));
  for (const x of [exe, plain, win]) mkdirSync(x);
  writeFileSync(join(exe, 'git'), '#!/bin/sh\n');
  chmodSync(join(exe, 'git'), 0o755);
  writeFileSync(join(plain, 'git'), 'x');
  chmodSync(join(plain, 'git'), 0o644);
  writeFileSync(join(win, 'git.exe'), 'x');
  assert.equal(gitOnPath(exe, '', false), true);
  assert.equal(gitOnPath(plain, '', false), false); // no execute bit
  assert.equal(gitOnPath(`::${plain}:${exe}`, '', false), true);
  assert.equal(gitOnPath('', '', false), false);
  assert.equal(gitOnPath(win, '', true), true); // PATHEXT unset: .COM;.EXE;.BAT;.CMD
  assert.equal(gitOnPath(win, '.COM;.BAT', true), false);
  assert.equal(gitOnPath(exe, '', true), false); // Windows wants an extension
});

test('foldCutoff names the line past the byte midpoint', () => {
  const row = (s) => `{"ts":"2026-10-17T00:00:0${s}Z","op":"read","path":"p"}\n`;
  assert.equal(foldCutoff(Buffer.alloc(0)), null);
  assert.equal(foldCutoff(Buffer.from(row(1) + row(2) + row(3) + row(4))), '2026-10-17T00:00:03Z~');
  assert.equal(foldCutoff(Buffer.from(`${row(1)}${'z'.repeat(400)}\n`)), null);
});

test('an append over the cap folds the older half', () => {
  const d = tmp();
  const log = new TouchLog(d, '0123456789abcdef');
  mkdirSync(dirname(log.path), { recursive: true });
  const rows = [];
  let size = 0;
  for (let i = 0; size <= TOUCH_LOG_CAP_BYTES; i++) {
    const r = `{"ts":"2026-10-${String(1 + Math.floor(i / 1000)).padStart(2, '0')}T00:00:00Z","session":"s","seq":${i + 1},"op":"read","path":"f${i % 30}"}\n`;
    rows.push(r);
    size += Buffer.byteLength(r);
  }
  writeFileSync(log.path, rows.join(''));
  assert.equal(log.appendTouch('now', 1, 'read', 'new.py', null, null, '2026-10-17T00:00:00Z'), true);
  const lines = readFileSync(log.path, 'utf8').split('\n').filter(Boolean);
  assert.ok(statSync(log.path).size <= TOUCH_LOG_CAP_BYTES);
  assert.ok(lines[0].includes('"op":"folded"') && lines[lines.length - 1].endsWith('"path":"new.py"}'));
  const kept = new Set(lines);
  assert.ok(rows.slice(-Math.floor(rows.length / 3)).every((r) => kept.has(r.slice(0, -1))), 'the newer half is kept');
});

test('PostToolUse with no git on PATH records nothing', () => {
  const d = tmp();
  const home = join(d, 'home');
  mkdirSync(home);
  const r = gitRepo(d);
  mkdirSync(join(d, 'nogit'));
  const run = (pathDir, tool) =>
    spawnSync(process.execPath, [CLI, '--hook'], {
      input: JSON.stringify({ cwd: r, session_id: 's1', hook_event_name: 'PostToolUse', tool_name: tool, tool_input: { file_path: join(r, 'src', 'a.py') } }),
      encoding: 'utf8',
      env: { ...process.env, HOME: home, USERPROFILE: home, PATH: pathDir },
    });
  for (const tool of ['Read', 'Edit']) assert.equal(run(join(d, 'nogit'), tool).status, 0);
  assert.equal(existsSync(join(home, '.bantamkit', 'touch')), false);
  assert.equal(existsSync(join(home, '.bantamkit', 'hooks', 'ledger-s1.seq.json')), false);
  // The control: git reachable through a symlink in a PATH directory records the call.
  mkdirSync(join(d, 'gitlink'));
  const real = spawnSync('/bin/sh', ['-c', 'command -v git'], { encoding: 'utf8' }).stdout.trim();
  symlinkSync(real, join(d, 'gitlink', 'git'));
  assert.equal(run(join(d, 'gitlink'), 'Read').status, 0);
  const dir = join(home, '.bantamkit', 'touch');
  const [name] = readdirSync(dir).filter((n) => n.endsWith('.jsonl'));
  assert.deepEqual(readFileSync(join(dir, name), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l).op), ['read']);
});

// --- T200-11: the cap holds, no thrash, no fold without the lock (test_touch_log.py's mirror)

/** The re-review's stuck log: `n` folded rows, then live lines past the cap. */
function stuck(n) {
  const out = [];
  let size = 0;
  for (let i = 0; i < n; i++) {
    const r = `${JSON.stringify({ ts: `2026-09-${String(1 + ((i * 7919) % 28)).padStart(2, '0')}T00:00:00Z`, session: '', seq: 0, op: 'folded', path: `src/module_${String(i).padStart(6, '0')}/component_file.py`, n: 1 })}\n`;
    out.push(r);
    size += Buffer.byteLength(r);
  }
  for (let i = 0; size <= TOUCH_LOG_CAP_BYTES; i++) {
    const r = `{"ts":"2026-10-02T00:00:${String(i % 60).padStart(2, '0')}Z","session":"s","seq":${i + 1},"op":"read","path":"src/x${i}.py"}\n`;
    out.push(r);
    size += Buffer.byteLength(r);
  }
  return Buffer.from(out.join(''));
}

test('a folded block over half the cap is bounded, then left alone', () => {
  const d = tmp();
  const log = new TouchLog(d, '0123456789abcdef');
  mkdirSync(dirname(log.path), { recursive: true });
  writeFileSync(log.path, stuck(6000));
  assert.equal(log.appendTouch('now', 1, 'read', 'new.py', null, null, '2026-10-17T00:00:00Z'), true);
  const first = readFileSync(log.path);
  assert.ok(first.length <= TOUCH_LOG_FOLD_TARGET_BYTES);
  assert.ok(first.toString('utf8').endsWith('"path":"new.py"}\n'));
  const key = (r) => `${r.ts}\u0000${r.path}`;
  const kept = first.toString('utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((r) => r.op === 'folded');
  const keptPaths = new Set(kept.map((r) => r.path));
  const dropped = stuck(6000).toString('utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((r) => r.op === 'folded' && !keptPaths.has(r.path));
  assert.ok(kept.map(key).sort()[0] > dropped.map(key).sort().at(-1), 'oldest (ts, path) aged out first');
  const ino = statSync(log.path).ino;
  for (let k = 2; k < 10; k++) assert.equal(log.appendTouch('now', k, 'read', `new${k}.py`, null, null, '2026-10-17T00:00:01Z'), true); // past the target
  const after = readFileSync(log.path);
  assert.ok(after.length > TOUCH_LOG_FOLD_TARGET_BYTES);
  assert.ok(after.subarray(0, first.length).equals(first) && statSync(log.path).ino === ino, 'no rewrite under the cap');
});

test('boundBody is under the target for any log', () => {
  const noTs = Buffer.from(Array.from({ length: 60000 }, (_, i) => `{"op":"read","path":"p${i % 9000}"}\n`).join(''));
  const late = (i) => `{"ts":"2026-10-09T00:00:00Z","session":"s","seq":1,"op":"read","path":"late${i % 4000}"}\n`;
  const early = (i) => `{"ts":"2026-10-01T00:00:00Z","session":"s","seq":1,"op":"edit","path":"early${i % 4000}"}\n`;
  const outOfOrder = Buffer.from(Array.from({ length: 7000 }, (_, i) => late(i)).join('') + Array.from({ length: 7000 }, (_, i) => early(i)).join(''));
  for (const data of [stuck(6000), stuck(12000), noTs, outOfOrder, Buffer.alloc(0), Buffer.from('junk\n'.repeat(300000))]) {
    assert.ok(boundBody(data).length <= TOUCH_LOG_FOLD_TARGET_BYTES);
  }
});

test('a held lock skips the fold', () => {
  const d = tmp();
  const log = new TouchLog(d, '0123456789abcdef');
  mkdirSync(dirname(log.path), { recursive: true });
  const data = stuck(6000);
  writeFileSync(log.path, data);
  writeFileSync(`${log.path}.lock`, ''); // a live holder: the 2 s wait runs out
  assert.equal(log.bound(), false);
  assert.ok(readFileSync(log.path).equals(data), 'never rewritten unlocked');
});

test('bound never throws', () => {
  const d = tmp();
  const log = new TouchLog(d, '0123456789abcdef');
  mkdirSync(log.path, { recursive: true }); // a directory where the log should be
  assert.equal(log.bound(), false);
});

test('parallel appenders on a stuck log lose nothing', async () => {
  const d = tmp();
  const log = new TouchLog(d, '0123456789abcdef');
  mkdirSync(dirname(log.path), { recursive: true });
  writeFileSync(log.path, stuck(6000));
  const mod = new URL('../dist/touch/index.js', import.meta.url).href;
  const child = `const { TouchLog } = await import(${JSON.stringify(mod)}); const l = new TouchLog(process.argv[1], '0123456789abcdef'); const j = Number(process.argv[2]); for (let k = 0; k < 10; k++) l.appendTouch('race', j * 100 + k, 'read', 'r' + j + '_' + k + '.py', null, null, '2026-10-03T00:00:00Z');`;
  const codes = await Promise.all(
    Array.from({ length: 12 }, (_, j) => new Promise((res) => spawn(process.execPath, ['--input-type=module', '-e', child, d, String(j)], { stdio: 'inherit' }).on('exit', res))),
  );
  assert.deepEqual(codes, Array(12).fill(0));
  const race = new Set(readFileSync(log.path, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((r) => r.session === 'race').map((r) => r.path));
  assert.equal(race.size, 120, `${120 - race.size} appends lost`);
  assert.ok(statSync(log.path).size <= TOUCH_LOG_CAP_BYTES);
  assert.deepEqual(readdirSync(dirname(log.path)).filter((n) => n.endsWith('.tmp') || n.endsWith('.lock')), []);
});
