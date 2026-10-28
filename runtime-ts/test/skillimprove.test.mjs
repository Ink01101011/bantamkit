/**
 * Self-improvement, part 1 (#206 Task 10a), port side: mirrors
 * `runtime-py/tests/test_skillimprove.py`, so a Node-only regression is red here before
 * `skill-improve` sees it. Every home is a tmp dir; every fixture is synthetic.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { appendFileSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';

import * as sd from '../dist/skilldraft.js';
import * as sf from '../dist/skillfile.js';
import * as si from '../dist/skillinstall.js';
import * as sm from '../dist/skillmine.js';

const NOW = '2026-10-27T12:00:00.000Z';
const LATER = '2026-10-28T12:00:00.000Z';
const home = () => mkdtempSync(join(tmpdir(), 'skillimprove-'));

const draft = (n, words = 'Does {n}. Use when {n} is asked.', step = 'Do it') =>
  `---\nname: ${n}\ndescription: ${words.split('{n}').join(n)}\n---\n\n` +
  `## When to use\n\nWhen asked.\n\n## Steps\n\n1. ${step} [job1/U1].\n\n## Pitfalls\n\nNone.\n\n## Example\n\nx\n`;

const cluster = (n) => ({
  evidence: [{ id: 'job1/U1', ok: true, ts: '2026-01-01T00:00:00Z' }],
  id: `c-${n}`,
  keywords: ['k1'],
  level: 'user',
  members: 3,
  source: 'shiftwork',
  status: 'pending',
  successes: 3,
  top: null,
});

function installed(h, n = 'sk-one') {
  si.install(cluster(n), draft(n), null, h, NOW, false);
  return join(sf.skillsRoot(h), n);
}

function setStats(h, n, version, stats) {
  sf.updateState(h, (state) => {
    const versions = state.skills[n].versions;
    versions[version] = { ...(versions[version] ?? {}), ...stats };
  });
}

function v2(h, n = 'sk-one') {
  const d = installed(h, n);
  si.newVersion(n, draft(n, undefined, 'Do it better'), h, NOW, 'auto');
  return d;
}

function failThirdRename(fn) {
  const saved = sf.seams.rename;
  let calls = 0;
  sf.seams.rename = (s, d) => {
    calls += 1;
    if (calls === 3) {
      const e = new Error('injected');
      e.code = 'EIO';
      throw e;
    }
    saved(s, d);
  };
  try {
    return fn();
  } finally {
    sf.seams.rename = saved;
  }
}

function files(d) {
  const out = {};
  const walk = (p) => {
    for (const e of readdirSync(p, { withFileTypes: true })) {
      const q = join(p, e.name);
      if (e.isDirectory()) walk(q);
      else out[q] = readFileSync(q).toString('base64');
    }
  };
  walk(d);
  return out;
}

test('constants', () => {
  assert.deepEqual([si.JUDGE_USES, si.VERDICT_KEPT, si.VERDICT_ROLLED_BACK, si.HISTORY_DIR], [5, 'kept', 'rolled back', 'references/history']);
});

test('a new version keeps the old one in history', () => {
  const h = home();
  const d = installed(h);
  const v1 = readFileSync(join(d, 'SKILL.md'));
  assert.equal(si.newVersion('sk-one', draft('sk-one', undefined, 'Do it better'), h, NOW, 'auto'), 'updated skill sk-one to v2');
  assert.deepEqual(readFileSync(join(d, 'references/history/v1.md')), v1);
  assert.ok(existsSync(join(d, 'references/evidence.md')));
  const text = readFileSync(join(d, 'SKILL.md'), 'utf8');
  const doc = sf.parseSkill(text);
  assert.equal(doc.metadata['bantamkit-version'], '2');
  assert.equal(doc.metadata['bantamkit-cluster'], 'c-sk-one');
  assert.equal(sf.isEdited(text), false);
  const e = sf.readState(h).skills['sk-one'];
  assert.equal(e.version, 2);
  assert.equal(e.sha256, sf.canonicalHash(text));
  assert.deepEqual(e.versions['2'], { at: NOW, false_fires: 0, from: 1, injects: 0, kind: 'auto', successes: 0, uses: 0 });
});

test('new version refusals', () => {
  const h = home();
  const d = installed(h);
  assert.throws(() => si.newVersion('sk-one', draft('sk-one'), h, NOW, 'manual'), { message: 'kind must be auto or approved' });
  assert.throws(() => si.newVersion('nope', draft('nope'), h, NOW, 'auto'), { message: "no skill named 'nope' is installed" });
  assert.throws(() => si.newVersion('sk-one', draft('sk-two'), h, NOW, 'auto'), { message: "the new version is named 'sk-two', not 'sk-one'" });
  assert.throws(() => si.newVersion('sk-one', draft('sk-one').replace('## Steps', '## Stops'), h, NOW, 'auto'), { message: '## Steps is missing or empty' });
  assert.ok(!existsSync(join(d, 'references/history')));
});

test('an edited skill is never versioned', () => {
  const h = home();
  const d = installed(h);
  appendFileSync(join(d, 'SKILL.md'), 'my own line\n');
  const before = readFileSync(join(d, 'SKILL.md'));
  assert.throws(() => si.newVersion('sk-one', draft('sk-one', undefined, 'Do it better'), h, NOW, 'auto'), {
    message: 'sk-one was edited by hand; it only receives proposed changes',
  });
  assert.deepEqual(readFileSync(join(d, 'SKILL.md')), before);
  assert.equal(si.editedByHand(sf.readState(h).skills['sk-one']), true);
});

test('a failed swap leaves the live version', () => {
  const h = home();
  const d = installed(h);
  const v1 = readFileSync(join(d, 'SKILL.md'));
  const before = sf.stateBytes(sf.readState(h));
  assert.throws(() => failThirdRename(() => si.newVersion('sk-one', draft('sk-one', undefined, 'Do it better'), h, NOW, 'auto')));
  assert.deepEqual(readFileSync(join(d, 'SKILL.md')), v1);
  assert.ok(!existsSync(join(d, 'references/history')));
  assert.deepEqual(sf.stateBytes(sf.readState(h)), before);
  assert.deepEqual(readdirSync(dirname(d)), ['sk-one']);
});

test('the next number skips a rolled-back one', () => {
  const h = home();
  const d = v2(h);
  setStats(h, 'sk-one', '1', { successes: 4, uses: 5 });
  setStats(h, 'sk-one', '2', { successes: 1, uses: 5 });
  assert.deepEqual(si.judgeStep(sf.readState(h), h, NOW), ['rolled back sk-one to v1']);
  assert.equal(si.newVersion('sk-one', draft('sk-one', undefined, 'Do it a third way'), h, LATER, 'approved'), 'updated skill sk-one to v3');
  const e = sf.readState(h).skills['sk-one'];
  assert.deepEqual([e.version, e.versions['3'].from, e.versions['3'].kind], [3, 1, 'approved']);
  assert.deepEqual(readdirSync(join(d, 'references/history')).sort(), ['v1.md', 'v2.md']);
});

const sources = (n) => ({
  injects: [
    { names: [n], session: 'aaaaaaaa-1', ts: '2026-10-27T12:00:01.000Z' },
    { names: [n, 'other'], session: 'bbbbbbbb-2', ts: '2026-10-27T12:00:02.000Z' },
    { names: [n], session: 'cccccccc-3', ts: '2026-10-27T12:00:03.000Z' },
    { names: ['other'], session: 'aaaaaaaa-1', ts: '2026-10-27T12:00:04.000Z' },
    { names: [n], session: '', ts: '2026-10-27T12:00:05.000Z' },
    { names: [n], session: 'dddddddd-4', ts: '2026-10-26T12:00:00.000Z' },
    { names: [n], session: 'eeeeeeee-5', ts: '2026-10-29T12:00:00.000Z' },
  ],
  turns: [
    { id: 'saaaaaaaa#1', ok: true, ts: '2026-10-27T12:00:00.000Z' },
    { id: 'sbbbbbbbb#1', ok: true, ts: '2026-10-27T11:00:00.000Z' },
    { id: 'sbbbbbbbb#2', ok: false, ts: '2026-10-27T12:00:00.000Z' },
  ],
  uses: [
    { fact: n, session: 'aaaaaaaa-1', ts: '2026-10-27T12:00:10.000Z' },
    { fact: n, session: 'bbbbbbbb-2', ts: '2026-10-27T12:00:10.000Z' },
    { fact: n, session: 'zzzzzzzz-9', ts: '2026-10-27T12:00:10.000Z' },
    { fact: 'other', session: 'cccccccc-3', ts: '2026-10-27T12:00:10.000Z' },
    { fact: n, session: 'aaaaaaaa-1', ts: '2026-10-26T00:00:00.000Z' },
  ],
});

test('stats count once into the live version', () => {
  const h = home();
  installed(h);
  const state = sf.readState(h);
  si.statsStep(state, sources('sk-one'), h, LATER);
  assert.deepEqual(state.skills['sk-one'].versions['1'], { false_fires: 1, injects: 3, successes: 1, uses: 3 });
  assert.equal(state.skills['sk-one'].counted_to, LATER);
  si.statsStep(state, sources('sk-one'), h, LATER);
  assert.equal(state.skills['sk-one'].versions['1'].uses, 3);
  assert.deepEqual(sf.readState(h), state);
});

test('stats after a new version go to it and freeze the old', () => {
  const h = home();
  v2(h);
  const state = sf.readState(h);
  si.statsStep(state, sources('sk-one'), h, LATER);
  assert.deepEqual(state.skills['sk-one'].versions['1'], { false_fires: 0, injects: 0, successes: 0, uses: 0 });
  assert.equal(state.skills['sk-one'].versions['2'].uses, 3);
  assert.equal(state.skills['sk-one'].versions['2'].injects, 3);
});

const RATES = [
  [{ successes: 4, uses: 5 }, { successes: 3, uses: 5 }, 'rolled back'],
  [{ successes: 4, uses: 5 }, { successes: 4, uses: 5 }, 'kept'],
  [{ successes: 4, uses: 5 }, { successes: 8, uses: 10 }, 'kept'],
  [{ successes: 4, uses: 5 }, { successes: 7, uses: 9 }, 'rolled back'],
  [{ false_fires: 2, injects: 5, uses: 5 }, { false_fires: 3, injects: 5, uses: 5 }, 'rolled back'],
  [{ false_fires: 2, injects: 5, uses: 5 }, { false_fires: 2, injects: 5, uses: 5 }, 'kept'],
  [{ injects: 0, uses: 5 }, { false_fires: 1, injects: 1, uses: 5 }, 'rolled back'],
  [{ false_fires: 1, injects: 1, uses: 5 }, { injects: 0, uses: 5 }, 'kept'],
  [{ uses: 0 }, { successes: 0, uses: 5 }, 'kept'],
];

for (const [one, two, verdict] of RATES) {
  test(`judge: ${JSON.stringify(one)} then ${JSON.stringify(two)} is ${verdict}`, () => {
    const h = home();
    v2(h);
    setStats(h, 'sk-one', '1', one);
    setStats(h, 'sk-one', '2', two);
    const state = sf.readState(h);
    const events = si.judgeStep(state, h, NOW);
    assert.equal(state.skills['sk-one'].versions['2'].verdict, verdict);
    assert.deepEqual(events, verdict === 'rolled back' ? ['rolled back sk-one to v1'] : []);
  });
}

test('four uses are never judged, five are', () => {
  const h = home();
  v2(h);
  setStats(h, 'sk-one', '1', { successes: 4, uses: 5 });
  setStats(h, 'sk-one', '2', { successes: 0, uses: 4 });
  const state = sf.readState(h);
  assert.deepEqual(si.judgeStep(state, h, NOW), []);
  assert.ok(!Object.hasOwn(state.skills['sk-one'].versions['2'], 'verdict'));
  setStats(h, 'sk-one', '2', { uses: 5 });
  assert.deepEqual(si.judgeStep(sf.readState(h), h, NOW), ['rolled back sk-one to v1']);
});

test('a rollback restores v1 bytes and keeps v2 in history', () => {
  const h = home();
  const d = installed(h);
  const v1 = readFileSync(join(d, 'SKILL.md'));
  si.newVersion('sk-one', draft('sk-one', undefined, 'Do it better'), h, NOW, 'auto');
  const v2b = readFileSync(join(d, 'SKILL.md'));
  setStats(h, 'sk-one', '1', { successes: 4, uses: 5 });
  setStats(h, 'sk-one', '2', { successes: 3, uses: 5 });
  assert.deepEqual(si.judgeStep(sf.readState(h), h, LATER), ['rolled back sk-one to v1']);
  assert.deepEqual(readFileSync(join(d, 'SKILL.md')), v1);
  assert.deepEqual(readFileSync(join(d, 'references/history/v2.md')), v2b);
  const e = sf.readState(h).skills['sk-one'];
  assert.deepEqual([e.version, e.rolled_back, e.counted_to], [1, 2, LATER]);
  assert.equal(si.editedByHand(e), false);
  assert.deepEqual(si.judgeStep(sf.readState(h), h, LATER), []);
});

test('an edited skill is never judged', () => {
  const h = home();
  const d = v2(h);
  setStats(h, 'sk-one', '1', { successes: 4, uses: 5 });
  setStats(h, 'sk-one', '2', { successes: 0, uses: 9 });
  appendFileSync(join(d, 'SKILL.md'), 'mine\n');
  const before = sf.stateBytes(sf.readState(h));
  const edited = readFileSync(join(d, 'SKILL.md'));
  assert.deepEqual(si.judgeStep(sf.readState(h), h, NOW), []);
  assert.deepEqual(readFileSync(join(d, 'SKILL.md')), edited);
  assert.deepEqual(sf.stateBytes(sf.readState(h)), before);
});

test('a failed rollback leaves v2 intact and unjudged', () => {
  const h = home();
  const d = v2(h);
  setStats(h, 'sk-one', '1', { successes: 4, uses: 5 });
  setStats(h, 'sk-one', '2', { successes: 3, uses: 5 });
  const tree = files(d);
  assert.deepEqual(
    failThirdRename(() => si.judgeStep(sf.readState(h), h, NOW)),
    [],
  );
  assert.deepEqual(files(d), tree);
  assert.ok(!Object.hasOwn(sf.readState(h).skills['sk-one'].versions['2'], 'verdict'));
});

test('the gate lets a skill be improved only as itself', () => {
  const h = home();
  const words = 'Does {n}. Use when asked to "ship the thing".';
  si.install(cluster('sk-one'), draft('sk-one', words), null, h, NOW, false);
  const d = join(sf.skillsRoot(h), 'sk-one');
  const b = sd.bundle(cluster('sk-one'));
  const text = draft('sk-one', words, 'Do it better');
  const plain = sd.gate(text, b, h, null);
  assert.equal(plain.ok, false);
  assert.ok(plain.reasons.some((r) => r.includes('already exists at')));
  assert.ok(plain.reasons.some((r) => r.includes('is shared with sk-one')));
  assert.deepEqual(sd.gate(text, b, h, null, d).reasons, []);
  si.install(cluster('sk-two'), draft('sk-two', words), null, h, NOW, false);
  assert.ok(sd.gate(text, b, h, null, d).reasons.some((r) => r.includes('is shared with sk-two')));
});

function jsonl(p, rows) {
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, rows.map((r) => `${JSON.stringify(r)}\n`).join(''));
}

// AMENDED job73 C15: automatic promotion follows BANTAMKIT_SKILL_AUTO; the judge does not.
for (const auto of ['on', 'off']) test(`daily counts, promotes and judges (BANTAMKIT_SKILL_AUTO=${auto})`, async () => {
  const saved = [process.env.BANTAMKIT_SKILL_AUDIT, process.env.BANTAMKIT_SKILL_AUTO];
  process.env.BANTAMKIT_SKILL_AUDIT = 'on';
  process.env.BANTAMKIT_SKILL_AUTO = auto;
  try {
    const h = home();
    mkdirSync(join(h, '.claude'));
    const d = installed(h);
    setStats(h, 'sk-one', '1', { successes: 4, uses: 5 });
    si.newVersion('sk-one', draft('sk-one', undefined, 'Do it better'), h, NOW, 'auto');
    setStats(h, 'sk-one', '2', { successes: 0, uses: 4 });
    jsonl(join(h, '.bantamkit/usage/store.jsonl'), Array(3).fill({ fact: 'sk-one', kind: 'recall_hit', ts: '2026-10-27T13:00:00Z' }));
    jsonl(join(h, '.bantamkit/touch/repo.jsonl'), [
      { ts: '2026-10-27T13:00:00Z', session: 's-1', seq: 1, op: 'use', fact: 'sk-one', kind: 'recall_hit' },
      { ts: '2026-10-27T13:00:00Z', session: 's-1', seq: 2, op: 'use', fact: 'sk-one', kind: 'save' },
    ]);
    jsonl(join(h, '.bantamkit/hooks/hook-log.jsonl'), [
      { ts: '2026-10-27T13:00:00.000Z', event: 'UserPromptSubmit', action: 'inject', session: 's-2', injected: [{ name: 'sk-one' }] },
      { ts: '2026-10-27T13:00:00.000Z', event: 'UserPromptSubmit', action: 'skip', session: 's-2', injected: [{ name: 'sk-one' }] },
    ]);
    await sm.daily(h, null, LATER);
    const state = sf.readState(h);
    const e = state.skills['sk-one'];
    assert.deepEqual(e.versions['2'], { at: NOW, false_fires: 1, from: 1, injects: 1, kind: 'auto', successes: 0, uses: 5, verdict: 'rolled back' });
    assert.equal(e.version, 1);
    if (auto === 'off') {
      assert.ok(!('promoted' in e) && !('promote_refused' in e));
      assert.deepEqual(state.events.map((x) => x.event), ['rolled back sk-one to v1']);
      assert.ok(!existsSync(join(h, '.claude/skills')));
      assert.ok(existsSync(join(d, 'references/history/v2.md')));
      return;
    }
    assert.equal(e.promoted.mode, 'symlink');
    assert.deepEqual(
      state.events.map((x) => x.event),
      ['promoted skill sk-one', 'rolled back sk-one to v1'],
    );
    assert.ok(lstatSync(join(h, '.claude/skills/sk-one')).isSymbolicLink());
    assert.ok(existsSync(join(d, 'references/history/v2.md')));
  } finally {
    for (const [k, v] of [
      ['BANTAMKIT_SKILL_AUDIT', saved[0]],
      ['BANTAMKIT_SKILL_AUTO', saved[1]],
    ]) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
});
