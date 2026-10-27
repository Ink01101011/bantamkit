/**
 * skillinstall (#206 Task 7), port side: mirrors `runtime-py/tests/test_skillinstall.py`, so a
 * Node-only regression is red here before `skill-install` sees it. Every home is a tmp dir;
 * every fixture is synthetic.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, sep } from 'node:path';
import { test } from 'node:test';

import * as sf from '../dist/skillfile.js';
import * as si from '../dist/skillinstall.js';
import { parseNow } from '../dist/storage/retention.js';

const NOW = '2026-10-27T12:00:00.000Z';
const at = (days) => si.iso(parseNow(NOW) + days * si.DAY_MS);
const home = () => mkdtempSync(join(tmpdir(), 'skillinstall-'));
const target = (h, name) => join(sf.skillsRoot(h), name);

const draft = (name) =>
  `---\nname: ${name}\ndescription: Does ${name}. Use when ${name} is asked.\n---\n\n` +
  '## When to use\n\nWhen asked.\n\n## Steps\n\n1. Do it [job1/U1].\n\n## Pitfalls\n\nNone.\n\n## Example\n\nx\n';

function record(name, successes = 6, o = {}) {
  const bar = o.bar ?? 3;
  const rec = {
    auto_bar: 2 * bar,
    auto_eligible: o.autoEligible ?? successes >= 2 * bar,
    bar,
    eligible: successes >= bar,
    evidence: Array.from({ length: successes }, (_, i) => ({
      commits: i === 0 ? ['feat: a (#1)'] : [],
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
    keywords: Array.from({ length: 20 }, (_, i) => `k${i}`),
    level: o.level ?? 'user',
    members: successes,
    pitfalls: [],
    repos: [],
    source: 'shiftwork',
    status: o.status ?? 'pending',
    steps: [],
    successes,
    top: o.top ?? null,
  };
  if (o.okDraft !== false) rec.draft = si.draftEntry('endpoint m', draft(name), NOW);
  return rec;
}

const files = (dir) => {
  const out = {};
  const walk = (d) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const p = join(d, e.name);
      if (e.isDirectory()) walk(p);
      else out[relative(dir, p).split(sep).join('/')] = readFileSync(p).toString('base64');
    }
  };
  walk(dir);
  return out;
};

const throwsSentence = (fn, re) =>
  assert.throws(fn, (e) => e instanceof si.InstallError && re.test(e.message));

delete process.env[si.AUTO_ENV];

test('install stamps, writes and records', () => {
  const h = home();
  const rec = record('fixing-a');
  const got = si.install(rec, draft('fixing-a'), null, h, NOW, true);
  const text = readFileSync(join(target(h, 'fixing-a'), 'SKILL.md'), 'utf8');
  const doc = sf.parseSkill(text);
  assert.equal(doc.metadata['bantamkit-generated-by'], 'bantamkit');
  assert.deepEqual(doc.metadata['bantamkit-evidence'].split(',').slice(0, 2), ['job1/U1', 'job1/U2']);
  assert.equal(doc.metadata['bantamkit-keywords'].split(',').length, si.KEYWORDS_MAX);
  assert.equal(doc.metadata['bantamkit-version'], '1');
  assert.equal(doc.metadata['bantamkit-cluster'], 'c-fixing-a');
  assert.equal(sf.isEdited(text), false);
  const state = sf.readState(h);
  const entry = state.skills['fixing-a'];
  assert.equal(entry.probation_until, at(30));
  assert.equal(entry.sha256, doc.metadata['bantamkit-sha256']);
  assert.deepEqual(entry.versions, { 1: { false_fires: 0, injects: 0, successes: 0, uses: 0 } });
  assert.deepEqual(state.auto_dates, ['2026-10-27']);
  assert.equal(rec.status, 'installed');
  assert.equal(got.event, 'installed skill fixing-a');
});

test('an approved install has no probation', () => {
  const h = home();
  si.install(record('fixing-a'), draft('fixing-a'), null, h, NOW, false);
  assert.equal('probation_until' in sf.readState(h).skills['fixing-a'], false);
  assert.equal('auto_dates' in sf.readState(h), false);
});

test('evidence cuts prompts by level and keeps commit subjects whole; X4-clean', () => {
  const h = home();
  const rec = record('fixing-a', 6, { level: 'project', top: join(h, 'repo') });
  const user = si.evidenceMarkdown(rec, 'fixing-a', 'user');
  const project = si.evidenceMarkdown(rec, 'fixing-a', 'project');
  assert.ok(user.includes(`  > ${'p'.repeat(120)}`));
  assert.ok(project.includes(`  > ${'p'.repeat(80)}\n`) && !project.includes('p'.repeat(81)));
  assert.ok(project.includes('  - feat: a (#1)'));
  si.install(rec, draft('fixing-a'), null, h, NOW, false);
  assert.equal(readFileSync(join(h, 'repo', '.bantamkit', 'skills', 'fixing-a', 'references', 'evidence.md'), 'utf8'), project);
  const planted = record('fixing-a');
  planted.evidence[0].tool_result = 'PLANTED';
  planted.result = 'PLANTED';
  assert.equal(si.evidenceMarkdown(planted, 'fixing-a', 'user').includes('PLANTED'), false);
});

test('install refusals', () => {
  const h = home();
  throwsSentence(() => si.install(record('fixing-a', 6, { level: 'project' }), draft('fixing-a'), null, h, NOW, true), /names no project/);
  throwsSentence(() => si.install(record('fixing-a'), draft('fixing-a'), 'global', h, NOW, true), /^level must be project or user$/);
  throwsSentence(() => si.install(record('x'), '---\nname: x\ndescription: d\n---\n', null, h, NOW, true), /## Steps is missing/);
  si.install(record('fixing-a'), draft('fixing-a'), null, h, NOW, false);
  throwsSentence(() => si.install(record('fixing-a'), draft('fixing-a'), null, h, NOW, false), /is already installed/);
});

test('a failed rename leaves nothing', () => {
  for (const seam of ['first', 'second']) {
    const h = home();
    const saved = sf.seams.rename;
    let calls = 0;
    sf.seams.rename = (s, d) => {
      calls += 1;
      if (seam === 'first' || calls === 2) throw new Error('injected');
      saved(s, d);
    };
    try {
      assert.throws(() => si.install(record('fixing-a'), draft('fixing-a'), null, h, NOW, true), /injected/);
    } finally {
      sf.seams.rename = saved;
    }
    assert.equal(existsSync(target(h, 'fixing-a')), false);
    assert.deepEqual(sf.readState(h).skills, {});
    const b = join(sf.backupRoot(h), 'fixing-a');
    assert.ok(!existsSync(b) || readdirSync(b).length === 0);
    assert.ok(!existsSync(sf.skillsRoot(h)) || readdirSync(sf.skillsRoot(h)).every((n) => !n.startsWith('fixing-a.')));
  }
});

test('autoStep installs at twice the bar, not at the bar', () => {
  const h = home();
  const state = sf.readState(h);
  assert.deepEqual(si.autoStep({ clusters: [record('at-bar', 3), record('one-below', 5)] }, state, h, NOW), []);
  const props = { clusters: [record('at-auto', 6)] };
  assert.deepEqual(si.autoStep(props, state, h, NOW), ['installed skill at-auto']);
  assert.equal(props.clusters[0].status, 'installed');
  assert.ok('at-auto' in state.skills);
});

test('autoStep needs a passed draft and an open status', () => {
  const h = home();
  const failed = record('gate-failed');
  failed.draft.ok = false;
  const props = {
    clusters: [record('no-draft', 6, { okDraft: false }), record('rejected', 6, { status: 'rejected' }), record('installed', 6, { status: 'installed' }), failed],
  };
  assert.deepEqual(si.autoStep(props, sf.readState(h), h, NOW), []);
  assert.equal(existsSync(sf.skillsRoot(h)), false);
});

test('one a day, the second the next day; best first, then oldest', () => {
  const h = home();
  const state = sf.readState(h);
  const props = { clusters: [record('first', 8), record('second', 7)] };
  assert.deepEqual(si.autoStep(props, state, h, NOW), ['installed skill first']);
  assert.deepEqual(si.autoStep(props, state, h, '2026-10-27T23:59:59.999Z'), []);
  assert.deepEqual(si.autoStep(props, state, h, at(1)), ['installed skill second']);
  const h2 = home();
  const props2 = { clusters: [record('newer', 6, { ts: '2026-02-01T00:00:00Z' }), record('older', 6, { ts: '2026-01-01T00:00:00Z' })] };
  assert.deepEqual(si.autoStep(props2, sf.readState(h2), h2, NOW), ['installed skill older']);
});

test('five live, the sixth waits', () => {
  const h = home();
  const state = sf.readState(h);
  const names = 'abcdef'.split('').map((c) => `skill-${c}`);
  names.slice(0, 5).forEach((n, i) => assert.deepEqual(si.autoStep({ clusters: [record(n)] }, state, h, at(i)), [`installed skill ${n}`]));
  assert.deepEqual(si.autoStep({ clusters: [record(names[5])] }, state, h, at(5)), []);
  si.undo('skill-a', h);
  assert.deepEqual(si.autoStep({ clusters: [record(names[5])] }, sf.readState(h), h, at(6)), ['installed skill skill-f']);
});

test('BANTAMKIT_SKILL_AUTO off', () => {
  for (const value of ['off', 'OFF', ' 0 ', 'false', 'no']) {
    const h = home();
    process.env[si.AUTO_ENV] = value;
    try {
      assert.deepEqual(si.autoStep({ clusters: [record('a-b')] }, sf.readState(h), h, NOW), []);
    } finally {
      delete process.env[si.AUTO_ENV];
    }
  }
});

test('a refused candidate is failed and the next is tried', () => {
  const h = home();
  mkdirSync(join(sf.skillsRoot(h), 'taken'), { recursive: true });
  const props = { clusters: [record('taken', 8), record('free', 7)] };
  assert.deepEqual(si.autoStep(props, sf.readState(h), h, NOW), ['installed skill free']);
  assert.deepEqual(props.clusters.map((r) => r.status), ['failed', 'installed']);
});

const installed = (h) => {
  const state = sf.readState(h);
  si.autoStep({ clusters: [record('fixing-a')] }, state, h, NOW);
  return state;
};

test('probation day 29 kept, day 30 removed, undo restores byte for byte', () => {
  const h = home();
  const state = installed(h);
  const t = target(h, 'fixing-a');
  const before = files(t);
  assert.deepEqual(si.probationStep(state, {}, h, at(29)), []);
  assert.ok(statSync(t).isDirectory());
  assert.deepEqual(si.probationStep(state, {}, h, at(30)), ['removed unused skill fixing-a']);
  assert.equal(existsSync(t), false);
  assert.equal('fixing-a' in state.skills, false);
  assert.equal(si.undo('fixing-a', h), 'restored fixing-a from its backup of 20261126T120000.000Z');
  assert.deepEqual(files(t), before);
  assert.equal('probation_until' in sf.readState(h).skills['fixing-a'], false);
  assert.ok(si.undo('fixing-a', h).startsWith('removed fixing-a; it did not exist before'));
  assert.equal(existsSync(t), false);
  assert.deepEqual(sf.readState(h).skills, {});
});

test('probation day 30 edited is proposed, never deleted', () => {
  const h = home();
  const state = installed(h);
  const skill = join(target(h, 'fixing-a'), 'SKILL.md');
  writeFileSync(skill, readFileSync(skill, 'utf8').replace('When asked.', 'When I ask.'));
  assert.deepEqual(si.probationStep(state, {}, h, at(30)), ['proposed removing edited skill fixing-a']);
  assert.ok(existsSync(skill));
  const entry = sf.readState(h).skills['fixing-a'];
  assert.deepEqual(entry.proposal, { at: at(30), kind: 'remove', status: 'pending' });
  assert.equal('probation_until' in entry, false);
  assert.deepEqual(si.probationStep(state, {}, h, at(60)), []);
});

test('a use leaves probation for good', () => {
  const h = home();
  const state = installed(h);
  assert.deepEqual(si.probationStep(state, { 'fixing-a': 1 }, h, at(10)), []);
  assert.equal('probation_until' in state.skills['fixing-a'], false);
  assert.deepEqual(si.probationStep(state, {}, h, at(90)), []);
  assert.ok(statSync(target(h, 'fixing-a')).isDirectory());
});

test('undo right after an install removes it', () => {
  const h = home();
  installed(h);
  assert.equal(si.undo('fixing-a', h), 'removed fixing-a; it did not exist before 20261027T120000.000Z');
  assert.equal(existsSync(target(h, 'fixing-a')), false);
  assert.deepEqual(sf.readState(h).skills, {});
  throwsSentence(() => si.undo('fixing-a', h), /^no skill named 'fixing-a' is installed$/);
});

test('constants', () => {
  assert.deepEqual([si.AUTO_PER_DAY, si.AUTO_LIVE_MAX, si.PROBATION_DAYS], [1, 5, 30]);
  assert.deepEqual([si.KEYWORDS_MAX, si.EVIDENCE_PROJECT_CHARS, si.EVIDENCE_USER_CHARS], [16, 80, 500]);
});
