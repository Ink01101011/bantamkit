/**
 * skillpropose (#206 Task 11), port side: mirrors `runtime-py/tests/test_skillpropose.py`, so a
 * Node-only regression is red here before `skill-propose` sees it. Every home is a tmp dir; every
 * LLM is a stub (the sampler is the test's function, the endpoint a local server that counts).
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';

import * as sf from '../dist/skillfile.js';
import * as si from '../dist/skillinstall.js';
import * as sm from '../dist/skillmine.js';
import * as sp from '../dist/skillpropose.js';
import { DRAFT_SYSTEM } from '../dist/skilldraft.js';

const NOW = '2026-10-27T12:00:00.000Z';
const C = sp.COMMAND;

const draft = (name, cite = 'job1/U1') =>
  `---\nname: ${name}\ndescription: Does ${name}. Use when ${name} is asked.\n---\n\n` +
  `## When to use\n\nWhen asked.\n\n## Steps\n\n1. Do it [${cite}].\n\n## Pitfalls\n\nNone.\n\n## Example\n\nx\n`;

function record(name, o = {}) {
  const successes = o.successes ?? 6;
  const rec = {
    auto_bar: 6,
    auto_eligible: successes >= 6,
    bar: 3,
    eligible: successes >= 3,
    evidence: Array.from({ length: successes }, (_, i) => ({
      commits: [],
      failure: null,
      id: `job1/U${i + 1}`,
      ok: true,
      paths: ['src/a.py'],
      prompt: 'p'.repeat(120),
      repo: '/r/.git',
      signals: { commit: true, tests: false },
      source: 'shiftwork',
      tools: ['Read', 'Edit'],
      ts: '2026-01-01T00:00:00Z',
    })),
    id: `c-${name}`,
    keywords: ['fix', name],
    level: 'user',
    members: successes,
    pitfalls: [],
    repos: [],
    source: 'shiftwork',
    status: o.status ?? 'pending',
    steps: [],
    successes,
    top: null,
  };
  if (o.stored !== false) rec.draft = si.draftEntry('endpoint m', draft(name), NOW);
  return rec;
}

function home(claude = true) {
  const base = mkdtempSync(join(tmpdir(), 'skillpropose-'));
  const h = join(base, 'home');
  mkdirSync(join(h, '.bantamkit'), { recursive: true });
  if (claude) mkdirSync(join(h, '.claude'));
  mkdirSync(join(base, 'cwd'));
  return h;
}

const write = (h, ...clusters) =>
  sm.writeProposals(h, { clusters, miner: { error: null, ms: 0, pieces: { session: 0, shiftwork: 6 } }, ts: NOW, version: 1 });
const doc = (h) => sm.readProposals(h);
const render = (h, action = null, target = null, level = null, sampler = null) =>
  sp.render(action, target, level, h, join(dirname(h), 'cwd'), NOW, sampler);

async function endpoint(t) {
  let hits = 0;
  const server = createServer((req, res) => {
    hits += 1;
    res.statusCode = 500;
    res.end();
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  process.env.BANTAMKIT_LLM_URL = `http://127.0.0.1:${server.address().port}/v1`;
  process.env.BANTAMKIT_LLM_MODEL = 'stub';
  t.after(() => {
    delete process.env.BANTAMKIT_LLM_URL;
    delete process.env.BANTAMKIT_LLM_MODEL;
    server.close();
  });
  return () => hits;
}

test('an empty home is the fixed text', async () => {
  assert.equal(await render(home()), sp.EMPTY);
});

test('list shows at most three pending and never a rejected one', async () => {
  const h = home();
  write(h, ...['p-a', 'p-b', 'p-c', 'p-d'].map((n) => record(n, { stored: false })), record('p-e', { status: 'rejected' }));
  const text = await render(h, 'list');
  assert.ok(text.includes('Pending (3 of at most 3):'));
  for (const n of ['p-a', 'p-b', 'p-c']) assert.ok(text.includes(`- c-${n}:`));
  assert.ok(!text.includes('c-p-d') && !text.includes('c-p-e'));
});

test('approve with a stored draft installs it off probation; again is refused', async () => {
  const h = home();
  write(h, record('fixing-a'));
  const path = join(sf.skillsRoot(h), 'fixing-a');
  assert.equal(await render(h, 'approve', 'c-fixing-a'), `installed skill fixing-a at ${path} (user level).\nundo: ${C} undo fixing-a`);
  const entry = sf.readState(h).skills['fixing-a'];
  assert.equal(entry.auto, false);
  assert.ok(!('probation_until' in entry));
  assert.equal(doc(h).clusters[0].status, 'installed');
  assert.equal(await render(h, 'approve', 'c-fixing-a'), 'proposal c-fixing-a is already installed');
});

test('approve with no draft drafts through sampling and never hits the endpoint', async (t) => {
  const hits = await endpoint(t);
  const h = home();
  write(h, record('fixing-a', { stored: false }));
  const asked = [];
  const text = await render(h, 'approve', 'c-fixing-a', null, async (system, user) => {
    asked.push([system, user]);
    return draft('fixing-a');
  });
  assert.ok(text.startsWith('installed skill fixing-a at '));
  assert.equal(asked.length, 1);
  assert.equal(asked[0][0], DRAFT_SYSTEM);
  assert.equal(hits(), 0);
  assert.equal(doc(h).clusters[0].draft.drafter, 'sampling');
});

test('a sampling draft that fails the gate does not fall through', async (t) => {
  const hits = await endpoint(t);
  const h = home();
  write(h, record('fixing-a', { stored: false }));
  const text = await render(h, 'approve', 'c-fixing-a', null, async () => draft('fixing-a', 'job9/U9'));
  assert.ok(text.startsWith('The draft from sampling did not pass the gate'));
  assert.ok(text.includes('step 1 cites job9/U9, which is not in the evidence'));
  assert.equal(hits(), 0);
  assert.ok(!existsSync(join(sf.skillsRoot(h), 'fixing-a')));
});

test('the host agent is told the path and the second approve installs', async () => {
  const h = home();
  write(h, record('fixing-a', { stored: false }));
  const staged = sp.handoffPath(h, 'c-fixing-a');
  const text = await render(h, 'approve', 'c-fixing-a');
  assert.ok(text.includes(`1. Write ONE file, ${staged}, with your own file tools`));
  mkdirSync(dirname(staged), { recursive: true });
  writeFileSync(staged, draft('fixing-a', 'nope'));
  assert.ok((await render(h, 'approve', 'c-fixing-a')).includes('did not pass the gate, so nothing was installed'));
  assert.ok(existsSync(staged) && !existsSync(join(sf.skillsRoot(h), 'fixing-a')));
  writeFileSync(staged, draft('fixing-a'));
  assert.ok((await render(h, 'approve', 'c-fixing-a')).startsWith('installed skill fixing-a at '));
  const skill = readFileSync(join(sf.skillsRoot(h), 'fixing-a', 'SKILL.md'), 'utf8');
  assert.ok(skill.includes('bantamkit-sha256:') && !sf.isEdited(skill));
  assert.ok(existsSync(join(sf.skillsRoot(h), 'fixing-a', 'references', 'evidence.md')));
  assert.ok(!existsSync(dirname(staged)));
});

test('without an adapter the file is printed and nothing written', async () => {
  const h = home(false);
  write(h, record('fixing-a'));
  const text = await render(h, 'approve', 'c-fixing-a');
  assert.ok(text.startsWith('No Claude Code skill directory was found on this host'));
  assert.ok(!existsSync(sf.skillsRoot(h)));
  assert.equal(doc(h).clusters[0].status, 'pending');
});

test('undo after an approve removes it and rejects its proposal', async () => {
  const h = home();
  write(h, record('fixing-a'));
  await render(h, 'approve', 'c-fixing-a');
  assert.ok((await render(h, 'undo', 'fixing-a')).endsWith('; proposal c-fixing-a is marked rejected'));
  assert.ok(!('fixing-a' in sf.readState(h).skills));
  assert.equal(doc(h).clusters[0].status, 'rejected');
  assert.equal(doc(h).clusters[0].rejected_at, 6);
});

test('refusals are sentences in the message', async () => {
  const h = home();
  assert.equal(await render(h, 'bogus', 'x'), "unknown action 'bogus'; one of list, approve, reject, undo, promote, demote");
  assert.equal(await render(h, 'approve'), `action approve needs a target: ${C} approve <id or name>`);
  assert.equal(await render(h, 'approve', 'c-x', 'global'), 'level must be project or user');
  assert.equal(await render(h, 'reject', 'nope'), "no pending proposal or change is named 'nope'");
  assert.equal(await render(h, 'undo', 'nope'), "no skill named 'nope' is installed");
});

// ------------------------------------------------------------------------------- the line

const events = (h, ...evs) =>
  sf.writeState(h, { skills: {}, events: evs.map((e, i) => ({ at: `2026-10-27T00:00:0${i}.000Z`, event: e })) });

test('the line: nothing new is null and writes nothing; one install once; four cut on an item', () => {
  const saved = process.env.BANTAMKIT_SKILL_AUDIT;
  delete process.env.BANTAMKIT_SKILL_AUDIT;
  try {
    const h = home();
    assert.equal(sp.sessionLine(h), null);
    assert.ok(!existsSync(sf.statePath(h)));
    events(h, 'installed skill fixing-a');
    const one = sp.sessionLine(h);
    assert.equal(one, `[bantamkit] skills: installed fixing-a on probation (undo: ${C} undo fixing-a) — ${C} lists them.`);
    assert.equal(sp.sessionLine(h), null);
    const h2 = home();
    events(h2, 'installed skill fixing-a', 'removed unused skill old-b', 'promoted skill used-c', 'rolled back used-c to v1');
    const four = sp.sessionLine(h2);
    assert.equal(four, `[bantamkit] skills: installed fixing-a on probation (undo: ${C} undo fixing-a); +3 more — ${C} lists them.`);
    assert.ok(Buffer.byteLength(four) <= sp.LINE_MAX_BYTES);
    assert.equal(sp.sessionLine(h2), null);
  } finally {
    if (saved === undefined) delete process.env.BANTAMKIT_SKILL_AUDIT;
    else process.env.BANTAMKIT_SKILL_AUDIT = saved;
  }
});

test('the line: the audit switch off silences it and writes nothing', () => {
  const saved = process.env.BANTAMKIT_SKILL_AUDIT;
  process.env.BANTAMKIT_SKILL_AUDIT = 'off';
  try {
    const h = home();
    events(h, 'installed skill fixing-a');
    const before = readFileSync(sf.statePath(h));
    assert.equal(sp.sessionLine(h), null);
    assert.deepEqual(readFileSync(sf.statePath(h)), before);
  } finally {
    if (saved === undefined) delete process.env.BANTAMKIT_SKILL_AUDIT;
    else process.env.BANTAMKIT_SKILL_AUDIT = saved;
  }
});
