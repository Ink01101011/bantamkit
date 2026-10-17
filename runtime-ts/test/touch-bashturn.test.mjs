/**
 * bash-turn (#200, E5, Task 3), port side. Mirrors `runtime-py/tests/test_touch_bashturn.py` and
 * the two bash-turn tests at the end of `test_hookadapter.py`, so a Node-only regression is red
 * here before `touch-turn` sees it.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { changed, findRepo, loadTurn, saveTurn, snapshot } from '../dist/touch/index.js';

const CLI = join(dirname(dirname(fileURLToPath(import.meta.url))), 'dist', 'cli.js');
const tmp = () => realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-touch-turn-')));

function g(r, ...a) {
  const x = spawnSync('git', ['-C', r, ...a], { encoding: 'utf8' });
  assert.equal(x.status, 0, x.stderr);
}

function repoBed(d) {
  const r = join(d, 'repo');
  mkdirSync(r);
  g(r, 'init', '-q');
  g(r, 'config', 'user.email', 't@t');
  g(r, 'config', 'user.name', 't');
  writeFileSync(join(r, 'a.txt'), '1\n');
  writeFileSync(join(r, 'dirty.txt'), '1\n');
  g(r, 'add', '.');
  g(r, 'commit', '-qm', 'c');
  writeFileSync(join(r, 'dirty.txt'), '2\n'); // dirty before the turn
  return r;
}

test('the diff sees new, modified and re-dirtied paths', () => {
  const r = repoBed(tmp());
  const repo = findRepo(r);
  const before = snapshot(repo);
  writeFileSync(join(r, 'a.txt'), 'changed by bash\n');
  mkdirSync(join(r, 'new'));
  writeFileSync(join(r, 'new', 'n.txt'), 'n\n');
  writeFileSync(join(r, 'dirty.txt'), '3, longer\n'); // already dirty: only the stat moves
  assert.deepEqual(changed(before, snapshot(repo)), ['a.txt', 'dirty.txt', 'new/n.txt']);
});

test('a revert to clean is a change', () => {
  const r = repoBed(tmp());
  const repo = findRepo(r);
  const before = snapshot(repo);
  writeFileSync(join(r, 'dirty.txt'), '1\n');
  assert.deepEqual(changed(before, snapshot(repo)), ['dirty.txt']);
});

test('a rename keys on the destination', () => {
  const r = repoBed(tmp());
  g(r, 'mv', 'a.txt', 'b.txt');
  const snap = snapshot(findRepo(r));
  assert.ok(snap.has('b.txt') && !snap.has('a.txt'));
  assert.equal(snap.get('b.txt')[0], 'R ');
});

test('snapshot is null when git fails', () => {
  const r = join(tmp(), 'notgit');
  mkdirSync(join(r, '.git'), { recursive: true });
  assert.equal(snapshot(findRepo(r)), null);
});

test('the turn round-trips with sorted keys', () => {
  const d = tmp();
  saveTurn(d, 's/1', new Map([['a', ['??', '1', 2]]]), 7);
  const t = loadTurn(d, 's/1');
  assert.equal(t[0], 7);
  assert.deepEqual([...t[1]], [['a', ['??', '1', 2]]]);
  assert.equal(readFileSync(join(d, 'ledger-s_1.turn.json'), 'utf8'), '{"seq":7,"status":{"a":["??","1",2]}}');
});

test('loadTurn refuses junk', () => {
  const d = tmp();
  assert.equal(loadTurn(d, 'none'), null);
  for (const junk of ['{"seq":', '[1]', '{"seq":"7","status":{}}', '{"seq":7,"status":[]}', '{"seq":true,"status":{}}']) {
    writeFileSync(join(d, 'ledger-j.turn.json'), junk);
    assert.equal(loadTurn(d, 'j'), null, junk);
  }
});

function hook(payload, { home, cwd, session = 's1' }) {
  const r = spawnSync(process.execPath, [CLI, '--hook'], {
    input: JSON.stringify({ cwd, session_id: session, ...payload }),
    encoding: 'utf8',
    env: { ...process.env, HOME: home, USERPROFILE: home },
  });
  assert.equal(r.status, 0, r.stderr);
  return r;
}

test('Stop records a bash-turn write once and never an edited file', () => {
  const d = tmp();
  const home = join(d, 'home');
  mkdirSync(home);
  const r = join(d, 'repo');
  mkdirSync(r);
  g(r, 'init', '-q');
  writeFileSync(join(r, 'a.txt'), '1\n');
  hook({ hook_event_name: 'PostToolUse', tool_name: 'Bash', tool_input: { command: 'ls' } }, { home, cwd: r });
  hook({ hook_event_name: 'UserPromptSubmit', prompt: 'hi' }, { home, cwd: r }); // short: the skip still opens
  hook({ hook_event_name: 'PostToolUse', tool_name: 'Edit', tool_input: { file_path: join(r, 'a.txt') } }, { home, cwd: r });
  writeFileSync(join(r, 'b.txt'), 'by bash\n');
  writeFileSync(join(r, 'a.txt'), 'again, longer\n');
  hook({ hook_event_name: 'Stop' }, { home, cwd: r });
  const dir = join(home, '.bantamkit', 'touch');
  const log = join(dir, readdirSync(dir).find((n) => n.endsWith('.jsonl')));
  const rows = readFileSync(log, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  const turns = rows.filter((x) => x.via === 'bash-turn').map((x) => [x.op, x.path, x.from, x.seq]);
  assert.deepEqual(turns, [['write', 'b.txt', 1, 2]]);
  const before = readFileSync(log);
  hook({ hook_event_name: 'Stop', stop_hook_active: true }, { home, cwd: r });
  assert.deepEqual(readFileSync(log), before);
});

test('Stop outside a repo or without a turn records nothing', () => {
  const d = tmp();
  const home = join(d, 'home');
  mkdirSync(home);
  const plain = join(d, 'plain');
  mkdirSync(plain);
  hook({ hook_event_name: 'UserPromptSubmit', prompt: 'hi' }, { home, cwd: plain });
  hook({ hook_event_name: 'Stop' }, { home, cwd: plain });
  assert.ok(!existsSync(join(home, '.bantamkit', 'touch')));
  assert.ok(!existsSync(join(home, '.bantamkit', 'hooks', 'ledger-s1.turn.json')));
  const r = join(d, 'repo');
  mkdirSync(r);
  g(r, 'init', '-q');
  writeFileSync(join(r, 'x.txt'), 'x\n');
  hook({ hook_event_name: 'Stop' }, { home, cwd: r, session: 's2' });
  assert.ok(!existsSync(join(home, '.bantamkit', 'touch')));
});
