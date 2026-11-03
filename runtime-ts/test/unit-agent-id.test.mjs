/**
 * #266 — a unit's subagent, the same literals as `runtime-py/tests/test_unit_agent_id.py`:
 * clockOut records `agent_id`, the hook stamps use rows with it, and the X10 signals attribute
 * those uses to the unit. The conformance suites compare the two runtimes' bytes.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const dist = new URL('../dist/', import.meta.url);
const ops = await import(new URL('shiftwork.js', dist));
const { toJs } = await import(new URL('pyjson.js', dist));
const { TouchLog, agentOf } = await import(new URL('touch/log.js', dist));
const sm = await import(new URL('skillmine.js', dist));
const sf = await import(new URL('skillfile.js', dist));
const si = await import(new URL('skillinstall.js', dist));

const CLI = join(dirname(dirname(fileURLToPath(import.meta.url))), 'dist', 'cli.js');
const AGENT = 'a9443875b21b8ca8f'; // the shape the probe of 2026-11-03 saw on a real run
const NOW = '2026-10-27T12:00:00.000Z';
const LATER = '2026-10-28T12:00:00.000Z';
const AFTER = '2026-10-27T13:00:00.000Z';
const tmp = (p) => mkdtempSync(join(tmpdir(), p));

const write = () => {
  const path = join(tmp('t266-'), 'checkpoint.json');
  writeFileSync(
    path,
    JSON.stringify({
      version: 1,
      job: { id: 't266', goal: 'g', done_definition: 'd', constraints: ['c'] },
      plan: {
        cursor: 'A',
        units: ['A', 'B'].map((id) => ({ id, title: id, brief_path: `b/${id}.md`, status: 'todo', role: 'implementer', depends_on: [], verify: 'true' })),
      },
      state: { repo: { branch: 'b', head_sha: '0', dirty: false }, artifacts: [], external: [] },
      history: [],
      retro: [],
      handoff: { next_action: 'go', open_questions: [], do_not: [], notes: '' },
    }),
  );
  return path;
};
const out = (path, agentId, accounting = null) =>
  toJs(ops.clockOut(path, 'A', 'done', {}, { unit: 'A', outcome: 'done' }, accounting, { agentId }));
const ledger = (path) => {
  const log = `${path}.log.jsonl`;
  if (!existsSync(log)) return [];
  return readFileSync(log, 'utf8').split('\n').filter(Boolean).map((x) => JSON.parse(x));
};

// ------------------------------------------------------------------ D1/D2: clockOut

test('the agent_id goes on the accounting line and nowhere else', () => {
  const path = write();
  assert.equal(out(path, AGENT, { tokens: 5, duration_ms: 9 }).result, 'ok');
  const [line] = ledger(path);
  assert.equal(line.agent_id, AGENT);
  assert.equal(line.tokens, 5);
  assert.ok(!readFileSync(path, 'utf8').includes(AGENT));
});

test('an accounting null line carries it too', () => {
  const path = write();
  assert.equal(out(path, AGENT).result, 'ok');
  assert.equal(ledger(path)[0].agent_id, AGENT);
});

test('without one the line is today\'s', () => {
  const path = write();
  assert.equal(out(path, null).result, 'ok');
  assert.ok(!('agent_id' in ledger(path)[0]));
});

for (const bad of ['', 'a'.repeat(65), 'a b', 'a/b', 'ä', 'a\n', 7, ['a']]) {
  test(`a bad agent_id ${JSON.stringify(bad)} is refused and nothing is written`, () => {
    const path = write();
    const before = readFileSync(path);
    assert.deepEqual(out(path, bad), { result: 'error', reason: ops.AGENT_ID_REFUSAL });
    assert.equal(ops.AGENT_ID_REFUSAL, 'agent_id must be 1 to 64 characters, each a letter, a digit, - or _');
    assert.deepEqual(readFileSync(path), before);
    assert.deepEqual(ledger(path), []);
  });
}

test('sixty-four characters pass', () => {
  assert.equal(out(write(), 'A-_9'.repeat(16)).result, 'ok');
});

test('a self-reported agent_id is a reserved key', () => {
  const path = write();
  const before = readFileSync(path);
  const r = out(path, null, { tokens: 1, duration_ms: 1, agent_id: AGENT });
  assert.equal(r.reason, "unit A in role implementer reported an accounting line that sets the runtime's own keys: agent_id");
  assert.deepEqual(ops.RESERVED_LEDGER_KEYS, ['unit', 'role', 'status', 'ts', 'event', 'agent_id']);
  assert.deepEqual(readFileSync(path), before);
  assert.deepEqual(ledger(path), []);
});

// -------------------------------------------------------------------- D3: the use row

test('agentOf takes only a well-formed id', () => {
  assert.equal(agentOf({ agent_id: AGENT }), AGENT);
  for (const bad of [{}, { agent_id: '' }, { agent_id: 'a b' }, { agent_id: 1 }, { agent_id: null }]) {
    assert.equal(agentOf(bad), null);
  }
});

test('a use row inside a subagent ends with its agent_id', () => {
  const log = new TouchLog(tmp('t266h-'), 'r1');
  assert.ok(log.appendUse('s1', 3, 'sk-one', 'recall_hit', '2026-01-01T00:00:00Z', AGENT));
  assert.ok(log.appendUse('s1', 4, 'sk-one', 'recall_hit', '2026-01-01T00:00:01Z'));
  assert.deepEqual(readFileSync(log.path, 'utf8').split('\n').filter(Boolean), [
    `{"ts":"2026-01-01T00:00:00Z","session":"s1","seq":3,"op":"use","fact":"sk-one","kind":"recall_hit","agent_id":"${AGENT}"}`,
    '{"ts":"2026-01-01T00:00:01Z","session":"s1","seq":4,"op":"use","fact":"sk-one","kind":"recall_hit"}',
  ]);
});

// ------------------------------------------------------------------- D4: the miner

function job(root, lines) {
  const sw = join(root, '.shiftwork');
  mkdirSync(sw, { recursive: true });
  const units = [...new Set(lines.map((l) => l.unit))].sort().map((u) => ({ id: u, title: `fix ${u}`, brief_path: `b/${u}.md`, status: 'done' }));
  writeFileSync(join(sw, 'checkpoint-job9.json'), JSON.stringify({ job: { id: 'j' }, plan: { units }, history: [] }));
  writeFileSync(join(sw, 'checkpoint-job9.json.log.jsonl'), lines.map((l) => `${JSON.stringify(l)}\n`).join(''));
}

test('a piece keeps the counting clock-out\'s agent_id out of its dict', () => {
  const root = tmp('t266m-');
  job(root, [
    { unit: 'U1', status: 'done', ts: '2026-01-01T00:00:00Z', agent_id: 'old' },
    { unit: 'U1', status: 'done', ts: '2026-01-02T00:00:00Z', agent_id: AGENT },
    { unit: 'U2', status: 'done', ts: '2026-01-02T00:00:00Z', agent_id: 'a b' },
    { unit: 'U3', status: 'done', ts: '2026-01-02T00:00:00Z' },
  ]);
  const got = Object.fromEntries(sm.shiftworkPieces(root).map((p) => [p.id, p]));
  assert.deepEqual(
    Object.fromEntries(Object.entries(got).map(([k, p]) => [k, p.agentId])),
    { 'job9/U1': AGENT, 'job9/U2': null, 'job9/U3': null },
  );
  assert.ok(!('agent_id' in sm.pieceDict(got['job9/U1'])));
  assert.ok(!('agentId' in sm.pieceDict(got['job9/U1'])));
});

test('improveSources lists the units and stamps the uses', () => {
  const home = tmp('t266s-');
  const touch = join(home, '.bantamkit', 'touch');
  mkdirSync(touch, { recursive: true });
  const rows = [
    { ts: AFTER, session: 's1', seq: 1, op: 'use', fact: 'sk-one', kind: 'recall_hit', agent_id: AGENT },
    { ts: AFTER, session: 's1', seq: 2, op: 'use', fact: 'sk-one', kind: 'recall_hit', agent_id: 'a b' },
  ];
  writeFileSync(join(touch, 'r1.jsonl'), rows.map((r) => `${JSON.stringify(r)}\n`).join(''));
  const piece = (id, ok, failure, agentId) => ({
    id, source: sm.SOURCE_SHIFTWORK, ts: AFTER, repo: '', prompt: 'p', tools: [], paths: new Set(), ok, signals: {}, failure, agentId,
  });
  const got = sm.improveSources(home, [piece('job9/U1', false, 'blocked on the lexer', AGENT), piece('job9/U2', true, null, null)], { skills: { 'sk-one': {} } });
  assert.deepEqual(got.units, [{ agent_id: AGENT, failure: 'blocked on the lexer', id: 'job9/U1', ok: false, ts: AFTER }]);
  assert.deepEqual(got.uses, [
    { agent_id: AGENT, fact: 'sk-one', session: 's1', ts: AFTER },
    { fact: 'sk-one', session: 's1', ts: AFTER },
  ]);
});

// ------------------------------------------------------------ D5: the X10 attribution

const DESC = 'Does sk-one. Use when sk-one is asked.';
const draft = () =>
  `---\nname: sk-one\ndescription: ${DESC}\n---\n\n## When to use\n\nWhen asked.\n\n## Steps\n\n1. Do it [job1/U1].\n\n` +
  '## Pitfalls\n\nNone.\n\n## Example\n\nx\n';
const record = (evidence = null) => ({
  evidence: evidence ?? [{ id: 'job1/U1', ok: true, ts: '2026-01-01T00:00:00Z' }],
  id: 'c-sk-one',
  keywords: ['k1'],
  level: 'user',
  members: 3,
  source: 'shiftwork',
  status: 'pending',
  steps: [],
  successes: 3,
  top: null,
});
process.env[si.AUTO_ENV] = 'on';
const installed = () => {
  const h = tmp('t266i-');
  si.install(record(), draft(), null, h, NOW, false);
  return h;
};
const unit = (id, ok, agent = AGENT, failure = null) => ({ agent_id: agent, failure, id, ok, ts: AFTER });
const use = (agent = AGENT, session = '1111aaaa-x') => ({
  fact: 'sk-one', session, ts: '2026-10-27T13:00:01.000Z', ...(agent === null ? {} : { agent_id: agent }),
});
// the session's own turn failed: only the unit can make the use a success
const FAILED_TURN = { id: 's1111aaaa#1', ok: false, ts: AFTER };
const v1 = (state) => state.skills['sk-one'].versions['1'];

test('a use inside a done unit is a success whatever the session turn', () => {
  const h = installed();
  const state = sf.readState(h);
  si.statsStep(state, { turns: [FAILED_TURN], units: [unit('job9/U1', true)], uses: [use()] }, h, LATER);
  assert.deepEqual([v1(state).uses, v1(state).successes], [1, 1]);
});

test('an agent_id two units claim keeps the session rule', () => {
  const h = installed();
  const state = sf.readState(h);
  si.statsStep(state, { turns: [FAILED_TURN], units: [unit('job9/U1', true), unit('job9/U2', true)], uses: [use()] }, h, LATER);
  assert.deepEqual([v1(state).uses, v1(state).successes], [1, 0]);
});

test('a use without an agent_id keeps the session rule', () => {
  const h = installed();
  const state = sf.readState(h);
  si.statsStep(state, { turns: [FAILED_TURN], units: [unit('job9/U1', true)], uses: [use(null)] }, h, LATER);
  assert.equal(v1(state).successes, 0);
});

const improve = async (h, sources, doc = null) => {
  const state = sf.readState(h);
  return [await si.improveStep(state, sources, doc, h, null, LATER, []), state];
};

test('a use inside a blocked unit is a pitfall citing the unit', async () => {
  const h = installed();
  const [events] = await improve(h, { units: [unit('job9/U1', false, AGENT, 'blocked on the lexer\nmore')], uses: [use()] });
  assert.deepEqual(events, ['improved skill sk-one to v2', 'proposed a change to sk-one']);
  const doc = sf.parseSkill(readFileSync(join(sf.skillsRoot(h), 'sk-one', 'SKILL.md'), 'utf8'));
  assert.ok(doc.body.includes('## Pitfalls\n\n- [job9/U1] blocked on the lexer\n\n## Example'));
  assert.equal(doc.metadata['bantamkit-evidence'], 'job1/U1,job9/U1');
});

test('a unit that named its subagent and never used the skill is a miss', async () => {
  const h = installed();
  const ev = ['job9/U1', 'job9/U2', 'job9/U3'].map((id) => ({ id, ok: true, prompt: 'fix the lexer', ts: AFTER }));
  // U1 used it, U2 did not (a miss), U3 named no subagent (skipped, as before #266)
  const [, state] = await improve(h, { units: [unit('job9/U1', true, 'a1'), unit('job9/U2', true, 'a2')], uses: [use('a1')] }, { clusters: [record(ev)] });
  assert.equal(v1(state).misses, 1);
});

// --------------------------------------------------------------- D3 through the hook

function hookUseRows(extra) {
  const home = tmp('t266home-');
  const cwd = tmp('t266repo-');
  spawnSync('git', ['init', '-q', cwd]);
  const payload = {
    cwd,
    session_id: 'parent-session',
    hook_event_name: 'PostToolUse',
    tool_name: 'mcp__bantamkit__memory_recall',
    tool_input: { query: 'x' },
    tool_response: [{ type: 'text', text: '[sk-one] (feedback) d\nbody' }],
    ...extra,
  };
  const r = spawnSync(process.execPath, [CLI, '--hook'], {
    input: JSON.stringify(payload),
    cwd,
    encoding: 'utf8',
    env: { ...process.env, HOME: home, USERPROFILE: home },
  });
  assert.equal(r.status, 0, r.stderr);
  const d = join(home, '.bantamkit', 'touch');
  const rows = [];
  for (const n of existsSync(d) ? readdirSync(d).sort() : []) {
    if (n.endsWith('.jsonl')) rows.push(...readFileSync(join(d, n), 'utf8').split('\n').filter(Boolean).map((x) => JSON.parse(x)));
  }
  return rows.filter((r) => r.op === 'use');
}

test('the hook stamps a use row fired inside a subagent', () => {
  const [row, ...rest] = hookUseRows({ agent_id: AGENT, agent_type: 'general-purpose' });
  assert.deepEqual(rest, []);
  assert.deepEqual([row.session, row.fact, row.agent_id], ['parent-session', 'sk-one', AGENT]);
  assert.equal(Object.keys(row).at(-1), 'agent_id');
});

for (const extra of [{}, { agent_id: 'a b' }, { agent_id: 3 }]) {
  test(`the hook writes today's row otherwise ${JSON.stringify(extra)}`, () => {
    const [row, ...rest] = hookUseRows(extra);
    assert.deepEqual(rest, []);
    assert.ok(!('agent_id' in row));
    assert.equal(row.fact, 'sk-one');
  });
}
