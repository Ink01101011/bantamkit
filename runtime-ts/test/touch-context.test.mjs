/**
 * #200 Task 5: `w_context` in the ranker and the via admission path — the same tests as
 * runtime-py/tests/test_touch_context.py and the via hook tests in test_hookadapter.py.
 * `touch-context` conformance compares the two runtimes.
 */
import './_sandbox.mjs';
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as retrieval from '../dist/memory/retrieval.js';
import * as tc from '../dist/touch/context.js';

const CLI = path.join(path.dirname(path.dirname(fileURLToPath(import.meta.url))), 'dist', 'cli.js');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'bk-touch-context-'));
after(() => fs.rmSync(scratch, { recursive: true, force: true }));

const G = {
  files: ['src/a.py', 'src/b.py', 'docs/x.md'],
  strong: { 'src/a.py': [['fa', null], ['fb', null]], 'docs/x.md': [['fx', null]] },
  weak: { 'src/b.py': { fw: ['2026-10-16T00:00:00Z', '2026-10-02T00:00:00Z'] } },
};
const row = (seq, p, op = 'edit') => ({ ts: '2026-10-16T00:00:00Z', session: 's', seq, op, path: p });
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-12, `${a} != ${b}`);

test('ctx defaults to zero and is clamped', () => {
  retrieval.setContextWeight(0.5);
  try {
    close(retrieval.weightOf('project', false, 0.0), 1.1);
    close(retrieval.weightOf('project', false, 0.0, 1.0), 1.6);
    close(retrieval.weightOf('project', false, 0.0, 7.0), 1.6);
    close(retrieval.weightOf('project', false, 0.0, -1.0), 1.1);
    close(retrieval.weightOf('project', false, 0.0, NaN), 1.1);
    close(retrieval.weightOf('project', false, 0.0, 0.5), 1.35);
  } finally {
    retrieval.setContextWeight(0.0);
  }
});

test('W_CONTEXT is still zero and VIA_ON false until Task 8', () => {
  assert.equal(retrieval.W_CONTEXT, 0.0);
  assert.equal(tc.VIA_ON, false);
});

test('window is the last twenty calls, most recent first', () => {
  const rows = [row(1, 'docs/x.md'), row(25, 'src/a.py'), row(30, 'src/b.py', 'read'), row(31, 'src/a.py')];
  assert.deepEqual(tc.window(rows, 31), ['src/a.py', 'src/b.py']);
});

test('window boundary; uses and folds are not touches', () => {
  const rows = [row(11, 'edge.py'), row(10, 'out.py'), { seq: 12, op: 'use', fact: 'f' }, { seq: 13, op: 'folded', path: 'folded.py' }];
  assert.deepEqual(tc.window(rows, 30), ['edge.py']);
});

test('context weights: strong full, weak partial', () => {
  const w = tc.contextWeights(G, ['src/a.py', 'src/b.py'], '2026-10-16T00:00:00Z');
  assert.equal(w.get('fa'), 1.0);
  assert.equal(w.get('fb'), 1.0);
  close(w.get('fw'), 0.75);
  assert.equal(w.has('fx'), false);
});

test('context weights: the cap, strong wins, a bad stamp is skipped', () => {
  const g = {
    files: ['p'],
    strong: { p: [['both', null]] },
    weak: { p: { both: ['2026-10-16T00:00:00Z'], many: Array(9).fill('2026-10-16T00:00:00Z'), bad: ['nope', '2026-10-16T00:00:00Z'] } },
  };
  assert.deepEqual(Object.fromEntries(tc.contextWeights(g, ['p'], '2026-10-16T00:00:00Z')), { both: 1.0, many: 1.0, bad: 0.5 });
});

test('via: strong only, window only, one fact', () => {
  const m = { fa: 1.1, fb: 1.3, fw: 9.0, fx: 9.0 };
  const weigh = (n) => m[n] ?? null;
  assert.deepEqual(tc.viaPick(G, ['src/b.py', 'src/a.py'], new Set(), weigh), ['fb', 'src/a.py']);
  assert.deepEqual(tc.viaPick(G, ['src/a.py'], new Set(['fb']), weigh), ['fa', 'src/a.py']);
  assert.equal(tc.viaPick(G, [], new Set(), weigh), null);
  assert.equal(tc.viaPick(G, ['src/a.py'], new Set(['fa', 'fb']), weigh), null);
  assert.deepEqual(tc.viaPick(G, ['src/a.py'], new Set(), (n) => ({ fa: 1.0, fb: 1.0 })[n] ?? null), ['fa', 'src/a.py']);
});

test('via label uses the shortest suffix', () => {
  assert.equal(tc.viaLabel('src/a.py', G), ' [via a.py]');
});

test('the via switch', () => {
  const saved = process.env.BANTAMKIT_VIA;
  try {
    delete process.env.BANTAMKIT_VIA;
    assert.equal(tc.viaEnabled(), tc.VIA_ON);
    process.env.BANTAMKIT_VIA = 'on';
    assert.equal(tc.viaEnabled(), true);
    process.env.BANTAMKIT_VIA = 'off';
    tc.setViaOn(true);
    assert.equal(tc.viaEnabled(), false);
    process.env.BANTAMKIT_VIA = 'yes';
    assert.equal(tc.viaEnabled(), true);
  } finally {
    tc.setViaOn(false);
    if (saved === undefined) delete process.env.BANTAMKIT_VIA;
    else process.env.BANTAMKIT_VIA = saved;
  }
});

// ------------------------------------------------------------------------- the hook

const PROMPT = 'explain the gateway rollout plan please';
const VIA_LINE = '[project] [fa] (project) notes about src/a.py [via a.py]';
const GATE_LINE = '[project] [gate-fact] (project) gateway rollout plan details';
let n = 0;

function factFile(store, nm, desc, body) {
  const d = path.join(store, 'facts');
  fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(
    path.join(d, `${nm}.md`),
    `---\nname: ${nm}\ndescription: ${desc}\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\nlinks: []\n---\n\n${body}\n`,
  );
}

function bed() {
  const root = path.join(scratch, `bed-${n++}`);
  const home = path.join(root, 'home');
  const r = path.join(root, 'repo');
  fs.mkdirSync(home, { recursive: true });
  fs.mkdirSync(path.join(r, 'src'), { recursive: true });
  fs.writeFileSync(path.join(r, 'src', 'a.py'), 'a\n');
  const git = (...a) => execFileSync('git', ['-c', 'user.email=t@t', '-c', 'user.name=t', '-c', 'commit.gpgsign=false', '-C', r, ...a], { stdio: 'pipe' });
  git('init', '-q');
  git('add', 'src/a.py');
  git('commit', '-qm', 'one');
  const store = path.join(r, '.bantamkit', 'memory');
  factFile(store, 'fa', 'notes about src/a.py', 'kept short');
  factFile(store, 'gate-fact', 'gateway rollout plan details', 'the plan');
  return { home, r: fs.realpathSync(r), store };
}

function hook(b, payload, env = {}, session = 's1') {
  const e = { ...process.env, HOME: b.home, USERPROFILE: b.home, ...env };
  delete e.BANTAMKIT_MEMORY_DIR;
  if (!('BANTAMKIT_VIA' in env)) delete e.BANTAMKIT_VIA;
  const res = spawnSync(process.execPath, [CLI, '--hook'], {
    cwd: b.r,
    input: JSON.stringify({ cwd: b.r, session_id: session, ...payload }),
    encoding: 'utf8',
    env: e,
  });
  assert.equal(res.status, 0, res.stderr);
  return res.stdout;
}
const edit = (b, env) => hook(b, { hook_event_name: 'PostToolUse', tool_name: 'Edit', tool_input: { file_path: path.join(b.r, 'src', 'a.py') } }, env);
const ups = (b, env, session) => {
  const out = hook(b, { hook_event_name: 'UserPromptSubmit', prompt: PROMPT }, env, session);
  return out ? JSON.parse(out).hookSpecificOutput.additionalContext.split('\n') : [];
};
const lastUps = (b) =>
  fs
    .readFileSync(path.join(b.home, '.bantamkit', 'hooks', 'hook-log.jsonl'), 'utf8')
    .trim()
    .split('\n')
    .map((l) => JSON.parse(l))
    .filter((x) => x.event === 'UserPromptSubmit')
    .at(-1);
const snapshotDir = (d) => {
  const out = {};
  const walk = (p) => {
    let ents = [];
    try {
      ents = fs.readdirSync(p, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of ents) {
      const q = path.join(p, e.name);
      if (e.isDirectory()) walk(q);
      else out[q] = fs.readFileSync(q, 'base64');
    }
  };
  walk(d);
  return out;
};

test('hook: a via line after an edit, once; no fact or usage write', () => {
  const b = bed();
  const on = { BANTAMKIT_VIA: 'on' };
  edit(b, on);
  const facts = snapshotDir(path.join(b.store, 'facts'));
  const usage = snapshotDir(path.join(b.home, '.bantamkit', 'usage'));
  assert.deepEqual(ups(b, on).slice(1), [GATE_LINE, VIA_LINE]);
  assert.deepEqual(snapshotDir(path.join(b.store, 'facts')), facts);
  assert.deepEqual(snapshotDir(path.join(b.home, '.bantamkit', 'usage')), usage);
  const rec = lastUps(b);
  assert.equal(rec.via, 'fa');
  assert.equal(rec.context, 1);
  assert.deepEqual(rec.injected.map((x) => x.name), ['gate-fact', 'fa']);
  assert.equal(rec.injected[1].score, 0);
  assert.deepEqual(ups(b, on), []);
});

test('hook: via off by default and by the switch', () => {
  const b = bed();
  edit(b);
  const lines = ups(b, { BANTAMKIT_VIA: 'unset-means-default' });
  assert.equal(lines.includes(VIA_LINE), false);
  assert.equal(lines.length, 2);
  const rec = lastUps(b);
  assert.equal('via' in rec, false);
  // T200-10: with W_CONTEXT 0 and via off no context is built, so none is counted (it was
  // `rec.context === 1`, the dead work the reviewer named; the reply is unchanged).
  assert.equal('context' in rec, false);
  assert.equal(ups(b, { BANTAMKIT_VIA: 'off' }, 's2').includes(VIA_LINE), false);
});

test('hook: no context work while it cannot move the reply (T200-10)', () => {
  const b = bed();
  const graph = path.join(b.home, '.bantamkit', 'graph');
  edit(b);
  hook(b, { hook_event_name: 'PostToolUse', tool_name: 'Edit', tool_input: { file_path: path.join(b.r, 'src', 'a.py') } }, {}, 's2');
  const skipped = ups(b, {}, 's1');
  assert.equal(fs.existsSync(graph), false, 'the inert state builds no graph');
  assert.equal('context' in lastUps(b), false);
  // Via on builds the context (and the graph); its reply minus the via line is the same.
  const built = ups(b, { BANTAMKIT_VIA: 'on' }, 's2');
  assert.equal(fs.readdirSync(graph).length, 1);
  assert.equal(lastUps(b).context, 1);
  assert.deepEqual(built.filter((l) => !l.includes(' [via ')), skipped);
});

test('hook: no via when the edit is 21 calls back', () => {
  const b = bed();
  const on = { BANTAMKIT_VIA: 'on' };
  edit(b, on);
  for (let i = 0; i < 21; i += 1) hook(b, { hook_event_name: 'PostToolUse', tool_name: 'Bash', tool_input: { command: 'ls' } }, on);
  assert.deepEqual(ups(b, on).slice(1), [GATE_LINE]);
  const rec = lastUps(b);
  assert.equal('context' in rec, false);
  assert.equal('via' in rec, false);
});
