/**
 * skillmine.daily (#206 Task 8), port side: mirrors `runtime-py/tests/test_skillmine_daily.py`,
 * so a Node-only regression is red here before `skill-miner` sees it. Every home and repo is a
 * tmp dir; the endpoint is a stub HTTP server on 127.0.0.1 in this process. Every fixture is
 * synthetic.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, utimesSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { dirname, join, relative, sep } from 'node:path';
import { test } from 'node:test';

import * as sf from '../dist/skillfile.js';
import * as si from '../dist/skillinstall.js';
import * as sm from '../dist/skillmine.js';
import * as retention from '../dist/storage/retention.js';

const NOW = '2026-10-27T00:00:00.000Z';
const DAY_S = 86_400;
const NAME = 'fixing-lexer-crashes';
const FILLERS = ['amber', 'birch', 'cedar', 'delta', 'ember', 'fjord', 'grove'];

const goodDraft = (name = NAME) =>
  `---\nname: ${name}\ndescription: Fixes lexer crashes. Use when the lexer crashes.\n---\n\n` +
  '## When to use\n\nThe lexer crashes on input.\n\n## Steps\n\n1. Read the crash [j/U1].\n' +
  '2. Fix the token table [j/U2].\n\n## Pitfalls\n\nNone.\n\n## Example\n\nx\n';

const draft = (name) =>
  `---\nname: ${name}\ndescription: Does ${name}. Use when ${name} is asked.\n---\n\n` +
  '## When to use\n\nWhen asked.\n\n## Steps\n\n1. Do it [job1/U1].\n\n## Pitfalls\n\nNone.\n\n## Example\n\nx\n';

function record(name, successes = 6, o = {}) {
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
      ts: o.ts ?? '2026-01-01T00:00:00Z',
    })),
    id: `c-${name}`,
    keywords: ['k0', 'k1'],
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
  if (o.okDraft !== false) rec.draft = si.draftEntry('endpoint m', draft(name), NOW);
  return rec;
}

const age = (p, days) => {
  const t = retention.parseNow(NOW) / 1000 - days * DAY_S;
  utimesSync(p, t, t);
};
function put(p, text, days = null) {
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, text);
  if (days !== null) age(p, days);
}

function bed(trap = true, units = 6) {
  const base = mkdtempSync(join(tmpdir(), 'skillmine-daily-'));
  const home = join(base, 'home');
  const proj = join(base, 'proj');
  mkdirSync(join(home, '.bantamkit'), { recursive: true });
  mkdirSync(join(proj, '.git'), { recursive: true });
  const ids = [...Array.from({ length: units }, (_, i) => `U${i + 1}`), ...FILLERS.map((_, i) => `F${i + 1}`)];
  const titles = [...Array(units).fill('fix the lexer crash'), ...FILLERS.map((w) => `${w} ${w}notes`)];
  const ckpt = {
    version: 1,
    job: { id: 'j', goal: 'g', done_definition: 'd', constraints: [] },
    plan: {
      cursor: 'U1',
      units: ids.map((id, i) => ({ id, title: titles[i], brief_path: 'x.md', status: 'done', role: 'implementer', depends_on: [], verify: 'true' })),
    },
    history: [],
  };
  const sw = join(proj, '.shiftwork');
  put(join(sw, 'checkpoint-j.json'), JSON.stringify(ckpt));
  put(join(sw, 'checkpoint-j.json.log.jsonl'), ids.map((u, i) => JSON.stringify({ unit: u, role: 'implementer', status: 'done', ts: `2026-10-0${1 + (i % 9)}T00:00:00Z` })).join('\n') + '\n');
  if (trap) {
    put(join(home, '.bantamkit', 'hooks', 'ledger-old.json'), '{"seen":{}}', 8);
    put(join(home, '.bantamkit', 'usage', 'idle.jsonl'), '{"ts":"2026-09-10T00:00:00Z","fact":"g","kind":"seed"}\n', 31);
  }
  return { base, home, proj };
}

function snapshot(base) {
  const out = new Map();
  const walk = (d) => {
    for (const n of readdirSync(d)) {
      const p = join(d, n);
      const st = lstatSync(p, { bigint: true });
      const rel = relative(base, p).split(sep).join('/');
      if (st.isDirectory()) {
        out.set(rel, 'dir');
        walk(p);
      } else out.set(rel, `${createHash('sha256').update(readFileSync(p)).digest('hex')} ${st.mtimeNs}`);
    }
  };
  walk(base);
  return out;
}
const changed = (a, b) => [...new Set([...a.keys(), ...b.keys()])].filter((k) => a.get(k) !== b.get(k)).sort();

async function withStub(fn) {
  let hits = 0;
  const server = createServer((req, res) => {
    req.resume();
    req.on('end', () => {
      hits += 1;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ choices: [{ message: { role: 'assistant', content: goodDraft() }, finish_reason: 'stop' }] }));
    });
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try {
    return await fn(`http://127.0.0.1:${server.address().port}`, () => hits);
  } finally {
    await new Promise((r) => server.close(r));
  }
}

const SWITCHES = ['BANTAMKIT_RETENTION', 'BANTAMKIT_SKILL_AUDIT', si.AUTO_ENV, 'BANTAMKIT_LLM_URL', 'BANTAMKIT_LLM_MODEL'];
async function withEnv(env, fn) {
  const saved = Object.fromEntries(SWITCHES.map((k) => [k, process.env[k]]));
  const base = { BANTAMKIT_RETENTION: 'off', BANTAMKIT_SKILL_AUDIT: null, [si.AUTO_ENV]: 'off', BANTAMKIT_LLM_URL: null, BANTAMKIT_LLM_MODEL: null };
  try {
    for (const [k, v] of Object.entries({ ...base, ...env })) {
      if (v === null) delete process.env[k];
      else process.env[k] = v;
    }
    return await fn();
  } finally {
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

const bk = (home, name) => join(home, '.bantamkit', name);
const child = (b) => retention.childMain([b.proj, b.home], NOW);

// ----------------------------------------------------------------------------- the child

test('the child with the audit on writes the proposals file', async () => {
  const b = bed();
  await withEnv({}, async () => {
    assert.equal(await child(b), 0);
    const doc = sm.readProposals(b.home);
    assert.equal(doc.ts, NOW);
    assert.equal(doc.miner.error, null);
    assert.deepEqual(doc.miner.pieces, { session: 0, shiftwork: 13 });
    const [c] = doc.clusters.filter((x) => x.successes === 6);
    assert.deepEqual([c.auto_eligible, c.status, c.level], [true, 'pending', 'project']);
    assert.ok(existsSync(bk(b.home, sm.CACHE_NAME)));
    assert.ok(!existsSync(bk(b.home, 'skill-drafts.jsonl')));
  });
});

test('the audit off writes no proposals file', async () => {
  const b = bed();
  await withEnv({ BANTAMKIT_SKILL_AUDIT: 'off' }, () => sm.daily(b.home, b.proj, NOW));
  await withEnv({ BANTAMKIT_SKILL_AUDIT: 'off', BANTAMKIT_RETENTION: null }, () => child(b));
  assert.ok(existsSync(retention.statePath(b.home)));
  assert.ok(!existsSync(bk(b.home, sm.PROPOSALS_NAME)));
  assert.ok(!existsSync(bk(b.home, sm.CACHE_NAME)));
});

test('J69-6: retention off changes only the listed files', async () => {
  const b = bed();
  const old = record('old-skill', 6, { okDraft: false });
  si.install(old, draft('old-skill'), null, b.home, si.iso(retention.parseNow('2026-10-27T12:00:00.000Z') - 31 * si.DAY_MS), true);
  await withStub(async (url, hits) => {
    await withEnv({ BANTAMKIT_LLM_URL: url, BANTAMKIT_LLM_MODEL: 'm', [si.AUTO_ENV]: 'on' }, async () => {
      const before = snapshot(b.base);
      assert.equal(await child(b), 0);
      const got = changed(before, snapshot(b.base));
      const backups = got.filter((p) => p.startsWith('home/.bantamkit/skill-backups/'));
      assert.deepEqual(
        got.filter((p) => !backups.includes(p)),
        [
          'home/.bantamkit/retention.json',
          'home/.bantamkit/skill-audit.json',
          'home/.bantamkit/skill-drafts.jsonl',
          'home/.bantamkit/skill-miner-cache.json',
          'home/.bantamkit/skill-proposals.json',
          'home/.bantamkit/skills-state.json',
          'home/.bantamkit/skills/old-skill',
          'home/.bantamkit/skills/old-skill/SKILL.md',
          'home/.bantamkit/skills/old-skill/references',
          'home/.bantamkit/skills/old-skill/references/evidence.md',
          'proj/.bantamkit',
          'proj/.bantamkit/skills',
          `proj/.bantamkit/skills/${NAME}`,
          `proj/.bantamkit/skills/${NAME}/SKILL.md`,
          `proj/.bantamkit/skills/${NAME}/references`,
          `proj/.bantamkit/skills/${NAME}/references/evidence.md`,
        ],
      );
      assert.ok(backups.some((p) => p.includes('old-skill')));
      assert.equal(hits(), 1);
      const state = sf.readState(b.home);
      assert.deepEqual(Object.keys(state.skills), [NAME]);
      assert.deepEqual(state.events.map((e) => e.event), [`installed skill ${NAME}`, 'removed unused skill old-skill']);
      const [c] = sm.readProposals(b.home).clusters.filter((x) => x.successes === 6);
      assert.equal(c.status, 'installed');
      assert.equal(c.draft.drafter, 'endpoint m');
      const line = sm.statusLine(b.home);
      assert.ok(line.startsWith('skills: mined 2026-10-27T00:00:00.000Z in '), line);
      assert.ok(line.endsWith(' ms; 0 pending, 1 of 5 auto-installed live, 0 promoted; drafter endpoint m'), line);
    });
  });
});

test('with auto off the child neither drafts nor installs', async () => {
  const b = bed();
  await withStub(async (url, hits) => {
    await withEnv({ BANTAMKIT_LLM_URL: url, BANTAMKIT_LLM_MODEL: 'm' }, () => child(b));
    assert.equal(hits(), 0);
  });
  assert.ok(!existsSync(join(b.proj, '.bantamkit')));
  assert.deepEqual(sf.readState(b.home).skills, {});
});

test('a miner error is recorded and no later step runs', async () => {
  const b = bed();
  const ready = record('ready-skill');
  put(bk(b.home, sm.PROPOSALS_NAME), JSON.stringify({ version: 1, clusters: [ready], ts: 't' }));
  mkdirSync(bk(b.home, sm.CACHE_NAME));
  await withEnv({ [si.AUTO_ENV]: 'on' }, async () => {
    await child(b);
    const doc = sm.readProposals(b.home);
    assert.equal(doc.miner.error, 'OSError');
    assert.equal(doc.ts, NOW);
    assert.deepEqual(doc.clusters, [ready]);
    assert.ok(!existsSync(join(b.home, '.bantamkit', 'skills')));
    assert.equal(sm.statusLine(b.home), `skills: miner failed at ${NOW}: OSError; drafter host agent`);
  });
});

test('an unreadable proposals file is left alone', async () => {
  const b = bed();
  put(bk(b.home, sm.PROPOSALS_NAME), '{not json');
  await withEnv({}, async () => {
    await sm.daily(b.home, b.proj, NOW);
    assert.equal(readFileSync(bk(b.home, sm.PROPOSALS_NAME), 'utf8'), '{not json');
    assert.ok(!existsSync(bk(b.home, sm.CACHE_NAME)));
    assert.equal(sm.statusLine(b.home), 'skills: miner refused: skill-proposals.json is not readable JSON; drafter host agent');
  });
});

// ------------------------------------------------------------------------- the status line

test('status: never ran, and off', async () => {
  const h = mkdtempSync(join(tmpdir(), 'skillmine-status-'));
  await withEnv({}, () => assert.equal(sm.statusLine(h), 'skills: miner never ran; drafter host agent'));
  await withEnv({ BANTAMKIT_SKILL_AUDIT: 'OFF' }, () => assert.equal(sm.statusLine(h), 'skills: off; miner never ran; drafter host agent'));
  await withEnv({ BANTAMKIT_SKILL_AUDIT: 'OFF', BANTAMKIT_LLM_URL: 'http://127.0.0.1:9', BANTAMKIT_LLM_MODEL: 'qwen' }, () => {
    assert.equal(sm.statusLine(h, true), 'skills: off; miner never ran; drafter sampling');
    assert.equal(sm.statusLine(h), 'skills: off; miner never ran; drafter endpoint qwen');
  });
});

test('status: mined counts pending, live autos and promoted', async () => {
  const h = mkdtempSync(join(tmpdir(), 'skillmine-status-'));
  const clusters = ['pending', 'pending', 'new', 'rejected', 'pending'].map((status) => ({ status }));
  put(bk(h, sm.PROPOSALS_NAME), JSON.stringify({ version: 1, clusters, ts: NOW, miner: { error: null, ms: 42 } }));
  const state = {
    version: 1,
    skills: { a: { auto: true }, b: { auto: true, promoted: { mode: 'symlink' } }, c: { auto: false, promoted: { mode: 'copy' } }, d: { auto: false, promoted: null } },
  };
  put(bk(h, sf.STATE_NAME), JSON.stringify(state));
  await withEnv({}, () => {
    assert.equal(sm.statusLine(h), `skills: mined ${NOW} in 42 ms; 3 pending, 2 of 5 auto-installed live, 2 promoted; drafter host agent`);
    put(bk(h, sf.STATE_NAME), '[]');
    assert.equal(sm.statusLine(h), `skills: mined ${NOW} in 42 ms; 3 pending, ? of 5 auto-installed live, ? promoted; drafter host agent`);
  });
});

test('status: a wrong version is refused', async () => {
  const h = mkdtempSync(join(tmpdir(), 'skillmine-status-'));
  put(bk(h, sm.PROPOSALS_NAME), '{"version": 2, "clusters": []}');
  await withEnv({}, () =>
    assert.equal(sm.statusLine(h), 'skills: miner refused: skill-proposals.json is not a version 1 proposals file; drafter host agent'),
  );
});

// ------------------------------------------------------------------------------ the helpers

test('draftCandidate takes the most successes, then the oldest', () => {
  const a = record('a', 7, { okDraft: false, ts: '2026-02-01T00:00:00Z' });
  const b = record('b', 7, { okDraft: false, ts: '2026-01-01T00:00:00Z' });
  const c = record('c', 8);
  const d = record('d', 6, { okDraft: false, status: 'installed' });
  const e = record('e', 5, { okDraft: false });
  assert.equal(sm.draftCandidate({ clusters: [a, b, c, d, e] }), b);
  assert.equal(sm.draftCandidate({ clusters: [c, d, e] }), null);
});

test('skillUses counts uses at or after the install', () => {
  const h = mkdtempSync(join(tmpdir(), 'skillmine-uses-'));
  const at = '2026-10-01T00:00:00.000Z';
  const state = { skills: { s: { auto: true, at }, t: { auto: false, at } } };
  const rows = [
    { ts: '2026-09-30T23:59:59Z', fact: 's', kind: 'recall_hit' },
    { ts: '2026-10-01T00:00:00Z', fact: 's', kind: 'recall_hit' },
    { ts: '2026-10-02T00:00:00Z', fact: 's', kind: 'body_read' },
    { ts: '2026-10-03T00:00:00Z', fact: 's', kind: 'seed' },
    { ts: '2026-10-03T00:00:00Z', fact: 's', kind: 'folded', weight: 1.0, last: '2026-10-05T00:00:00Z' },
    { ts: '2026-10-03T00:00:00Z', fact: 't', kind: 'recall_hit' },
  ];
  put(join(h, '.bantamkit', 'usage', 'abc.jsonl'), rows.map((r) => JSON.stringify(r) + '\n').join(''));
  put(join(h, '.bantamkit', 'usage', 'notes.txt'), JSON.stringify(rows[1]) + '\n');
  assert.deepEqual(sm.skillUses(h, state), { s: 3 });
  assert.deepEqual(sm.skillUses(h, { skills: {} }), {});
});

test('errorName is OSError for any filesystem error', () => {
  const fsError = (code, syscall) => Object.assign(new Error('x'), { code, syscall });
  assert.equal(sm.errorName(fsError('EISDIR', 'rename')), 'OSError');
  assert.equal(sm.errorName(fsError('EPERM', 'open')), 'OSError');
  assert.equal(sm.errorName(new sm.ProposalsError('x')), 'ProposalsError');
  assert.equal(sm.errorName(new TypeError('x')), 'TypeError');
});
