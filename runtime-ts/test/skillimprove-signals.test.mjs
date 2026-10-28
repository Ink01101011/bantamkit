/**
 * Self-improvement, part 2 (#206 Task 10b), port side: mirrors
 * `runtime-py/tests/test_skillimprove_signals.py` (the transcript-built X4 case stays on the
 * reference side; the conformance suite compares every byte of the two). Every home is a tmp
 * dir; every fixture is synthetic; no drafter is real.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';

import * as sd from '../dist/skilldraft.js';
import * as sf from '../dist/skillfile.js';
import * as si from '../dist/skillinstall.js';
import * as sp from '../dist/skillpropose.js';

const NOW = '2026-10-27T12:00:00.000Z';
const LATER = '2026-10-28T12:00:00.000Z';
const AFTER = '2026-10-27T13:00:00.000Z';
const DESC = 'Does sk-one. Use when sk-one is asked.';
const NARROW = 'Does sk-one for parsers only. Use when a parser of sk-one is asked.';
const home = () => mkdtempSync(join(tmpdir(), 'skillsignals-'));

// AMENDED job73 C13b: automatic edits follow BANTAMKIT_SKILL_AUTO, OFF by default in 0.37.0 (and
// pinned off by the runner); these tests are of the automatic path, so they opt in. The off
// path is tested below with the switch unset.
process.env[si.AUTO_ENV] = 'on';
const withAuto = async (value, fn) => {
  if (value === undefined) delete process.env[si.AUTO_ENV];
  else process.env[si.AUTO_ENV] = value;
  try {
    await fn();
  } finally {
    process.env[si.AUTO_ENV] = 'on';
  }
};

const draft = (name = 'sk-one', desc = DESC, steps = '1. Do it [job1/U1].') =>
  `---\nname: ${name}\ndescription: ${desc}\n---\n\n## When to use\n\nWhen asked.\n\n## Steps\n\n${steps}\n\n` +
  '## Pitfalls\n\nNone.\n\n## Example\n\nx\n';

const record = (name = 'sk-one', evidence = null, keywords = null, steps = null) => ({
  evidence: evidence ?? [{ id: 'job1/U1', ok: true, ts: '2026-01-01T00:00:00Z' }],
  id: `c-${name}`,
  keywords: keywords ?? ['k1'],
  level: 'user',
  members: 3,
  source: 'shiftwork',
  status: 'pending',
  steps: steps ?? [],
  successes: 3,
  top: null,
});

function installed(h, name = 'sk-one') {
  si.install(record(name), draft(name), null, h, NOW, false);
  return join(sf.skillsRoot(h), name);
}

function setV(h, name, stats, version = '1') {
  sf.updateState(h, (state) => {
    const vs = state.skills[name].versions;
    vs[version] = { ...(vs[version] ?? {}), ...stats };
  });
}

class Stub {
  label = 'endpoint stub';
  asked = [];
  constructor(answer) {
    this.answer = answer;
  }
  async ask(system, user) {
    this.asked.push([system, user]);
    return this.answer;
  }
}

async function step(h, { sources = {}, doc = null, chain = [], now = LATER } = {}) {
  const state = sf.readState(h);
  const events = await si.improveStep(state, sources, doc, h, null, now, chain);
  return [events, state];
}

const skill = (h, name = 'sk-one') => readFileSync(join(sf.skillsRoot(h), name, 'SKILL.md'), 'utf8');
const drafts = (h) => {
  const p = sd.draftsLog(h);
  return existsSync(p) ? readFileSync(p, 'utf8').split('\n').filter((x) => x).map((x) => JSON.parse(x)) : [];
};

test('constants', () => {
  assert.deepEqual(
    [si.TUNE_MIN_INJECTS, [...si.FALSE_FIRE_TUNE], si.MISS_TUNE, si.PITFALL_CHARS, si.TOGETHER_SESSIONS, [...si.TOGETHER_SHARE]],
    [5, [1, 2], 2, 200, 5, [1, 2]],
  );
});

test('four injects, all false: no tune', async () => {
  const h = home();
  installed(h);
  setV(h, 'sk-one', { injects: 4, false_fires: 4 });
  const stub = new Stub(draft('sk-one', NARROW));
  const [events, state] = await step(h, { chain: [stub] });
  assert.deepEqual(events, []);
  assert.equal(stub.asked.length, 0);
  assert.equal(state.skills['sk-one'].version, 1);
});

test('five injects, three false: narrowed as v2', async () => {
  const h = home();
  installed(h);
  setV(h, 'sk-one', { injects: 5, false_fires: 3 });
  const stub = new Stub(draft('sk-one', NARROW));
  const [events, state] = await step(h, { chain: [stub] });
  assert.deepEqual(events, ['improved skill sk-one to v2']);
  assert.ok(stub.asked[0][1].startsWith(sd.IMPROVE_NARROW));
  const doc = sf.parseSkill(skill(h));
  assert.equal(doc.description, NARROW);
  assert.equal(doc.metadata['bantamkit-version'], '2');
  assert.deepEqual(state.skills['sk-one'].versions['1'].tried, ['narrow']);
  assert.equal(drafts(h).at(-1).ok, true);
  setV(h, 'sk-one', { injects: 5, false_fires: 3 }, '1');
  assert.deepEqual((await step(h, { chain: [stub], now: '2026-10-29T12:00:00.000Z' }))[0], []);
});

test('five injects, two false: no tune', async () => {
  const h = home();
  installed(h);
  setV(h, 'sk-one', { injects: 5, false_fires: 2 });
  const stub = new Stub(draft('sk-one', NARROW));
  assert.deepEqual((await step(h, { chain: [stub] }))[0], []);
  assert.equal(stub.asked.length, 0);
});

test('a narrow that fails the gate: no version, a log line', async () => {
  const h = home();
  installed(h);
  setV(h, 'sk-one', { injects: 5, false_fires: 3 });
  const before = skill(h);
  const [events, state] = await step(h, { chain: [new Stub(draft('sk-one', 'x'.repeat(1100)))] });
  assert.deepEqual(events, []);
  assert.equal(skill(h), before);
  assert.equal(state.skills['sk-one'].version, 1);
  const line = drafts(h).at(-1);
  assert.equal(line.ok, false);
  assert.deepEqual(line.reasons, ['description is 1100 characters; at most 1024']);
});

test('no drafter: the narrow waits and the command applies the hand-off', async () => {
  const h = home();
  installed(h);
  setV(h, 'sk-one', { injects: 5, false_fires: 3 });
  const [events, state] = await step(h);
  assert.deepEqual(events, ['waiting on a drafter to tune sk-one']);
  assert.deepEqual(state.skills['sk-one'].tune, { at: LATER, kinds: ['narrow'] });
  assert.ok(sp.renderList(h).includes('Waiting on a drafter'));
  let said = await sp.render('approve', 'sk-one', null, h, null, LATER);
  const p = sp.handoffPath(h, 'tune-sk-one');
  assert.ok(said.includes(p) && said.includes(sd.IMPROVE_NARROW));
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, draft('sk-one', NARROW));
  said = await sp.render('approve', 'sk-one', null, h, null, LATER);
  assert.equal(said, 'improved skill sk-one to v2, its description tuned (narrow)');
  assert.equal(sf.parseSkill(skill(h)).description, NARROW);
  assert.equal(Object.hasOwn(sf.readState(h).skills['sk-one'], 'tune'), false);
  assert.equal(existsSync(dirname(p)), false);
});

test('the command drafts a tune through sampling; reject drops one', async () => {
  const h = home();
  installed(h);
  setV(h, 'sk-one', { injects: 5, false_fires: 3 });
  await step(h);
  const said = await sp.render('approve', 'sk-one', null, h, null, LATER, async () => draft('sk-one', NARROW));
  assert.equal(said, 'improved skill sk-one to v2, its description tuned (narrow)');
  const h2 = home();
  installed(h2);
  setV(h2, 'sk-one', { injects: 5, false_fires: 3 });
  await step(h2);
  assert.equal(await sp.render('reject', 'sk-one', null, h2, null, LATER), 'kept skill sk-one as it is; the tune of its description is dropped');
});

const missed = (n) => ({
  clusters: [
    record(
      'sk-one',
      Array.from({ length: n }, (_, k) => {
        const i = k + 1;
        return { id: `s${i}${i}${i}${i}aaaa#1`, ok: true, prompt: 'fix the lexer tokens', ts: AFTER };
      }),
      ['k1', 'lexer', 'tokens', 'absent'],
    ),
  ],
});

test('one miss never widens; two do', async () => {
  const h = home();
  installed(h);
  let [events, state] = await step(h, { doc: missed(1) });
  assert.deepEqual(events, []);
  assert.equal(state.skills['sk-one'].versions['1'].misses, 1);
  [events] = await step(h, { doc: missed(1), now: '2026-10-29T12:00:00.000Z' });
  assert.deepEqual(events, []);
  const h2 = home();
  installed(h2);
  [events, state] = await step(h2, { doc: missed(2) });
  assert.deepEqual(events, ['improved skill sk-one to v2', 'waiting on a drafter to tune sk-one']);
  assert.equal(sf.parseSkill(skill(h2)).metadata['bantamkit-keywords'], 'k1,lexer,tokens');
  assert.deepEqual(state.skills['sk-one'].tune.kinds, ['widen']);
});

const corrected = (text = 'no, use the other parser\nand more') => ({
  turns: [{ failure: si.CORRECTED + text, id: 's1111aaaa#1', ok: false, tools: ['Read', 'Edit'], ts: AFTER }],
  uses: [{ fact: 'sk-one', session: '1111aaaa-x', ts: '2026-10-27T13:00:01.000Z' }],
});

test('a correction adds one pitfall and proposes a steps change', async () => {
  const h = home();
  installed(h);
  const [events, state] = await step(h, { sources: corrected() });
  assert.deepEqual(events, ['improved skill sk-one to v2', 'proposed a change to sk-one']);
  const doc = sf.parseSkill(skill(h));
  assert.ok(doc.body.includes('## Pitfalls\n\n- [s1111aaaa#1] no, use the other parser\n\n## Example'));
  assert.ok(doc.body.includes('## Steps\n\n1. Do it [job1/U1].\n\n## Pitfalls'));
  assert.equal(doc.metadata['bantamkit-evidence'], 'job1/U1,s1111aaaa#1');
  const p = state.skills['sk-one'].proposal;
  assert.deepEqual([p.kind, p.status], ['steps', 'pending']);
  assert.deepEqual((await step(h, { sources: corrected(), now: '2026-10-29T12:00:00.000Z' }))[0], []);
  assert.equal(await sp.render('approve', 'sk-one', null, h, null, LATER), 'updated skill sk-one to v3');
  assert.ok(skill(h).includes('2. Before you finish'));
});

test('auto off makes no version and proposes the same signals (job73 C13b)', async () => {
  for (const value of [undefined, 'off', 'banana']) {
    await withAuto(value, async () => {
      const h = home();
      const target = installed(h);
      const before = readFileSync(join(target, 'SKILL.md'));
      const [events, state] = await step(h, { sources: corrected() });
      assert.deepEqual(events, ['proposed a change to sk-one']);
      assert.deepEqual(readFileSync(join(target, 'SKILL.md')), before);
      const entry = state.skills['sk-one'];
      assert.equal(entry.version, 1);
      assert.equal(existsSync(join(target, si.HISTORY_DIR)), false);
      assert.deepEqual([entry.proposal.kind, entry.proposal.status], ['improve', 'pending']);
      assert.ok(
        entry.proposal.text.includes(
          '## Steps\n\n1. Do it [job1/U1].\n2. Before you finish, check for what [s1111aaaa#1] ' +
            'was corrected for: no, use the other parser\n\n## Pitfalls\n\n' +
            '- [s1111aaaa#1] no, use the other parser\n\n## Example',
        ),
      );
      const said = await sp.render('approve', 'sk-one', null, h, null, LATER);
      assert.equal(said, 'updated skill sk-one to v2');
      const after = sf.readState(h).skills['sk-one'];
      assert.deepEqual([after.version, after.versions['2'].kind], [2, 'approved']);
      assert.ok(skill(h).includes('- [s1111aaaa#1] no, use the other parser'));
    });
  }
});

test('auto off: a drafted narrow is proposed, a tune with no drafter waits', async () => {
  await withAuto(undefined, async () => {
    const h = home();
    installed(h);
    setV(h, 'sk-one', { injects: 5, false_fires: 3 });
    let [events, state] = await step(h, { chain: [new Stub(draft('sk-one', NARROW))] });
    assert.deepEqual(events, ['proposed a change to sk-one']);
    assert.equal(state.skills['sk-one'].version, 1);
    assert.ok(state.skills['sk-one'].proposal.text.includes(NARROW));
    assert.ok(skill(h).includes(DESC));
    const other = home();
    installed(other);
    setV(other, 'sk-one', { injects: 5, false_fires: 3 });
    [events, state] = await step(other);
    assert.deepEqual(events, ['waiting on a drafter to tune sk-one']);
    assert.deepEqual(state.skills['sk-one'].tune.kinds, ['narrow']);
    assert.equal(state.skills['sk-one'].version, 1);
  });
});

test('auto off: the judge still rolls back', async () => {
  await withAuto(undefined, async () => {
    const h = home();
    installed(h);
    si.newVersion('sk-one', draft('sk-one', NARROW), h, LATER, 'auto');
    setV(h, 'sk-one', { uses: 5, successes: 5 });
    setV(h, 'sk-one', { uses: 5, successes: 1 }, '2');
    assert.deepEqual(si.judgeStep(sf.readState(h), h, '2026-10-29T12:00:00.000Z'), ['rolled back sk-one to v1']);
    assert.ok(skill(h).includes(DESC));
  });
});

test('a pitfall note is cut to 200 code points', async () => {
  const h = home();
  installed(h);
  await step(h, { sources: corrected('ก'.repeat(300)) });
  const line = skill(h).split('\n').find((x) => x.startsWith('- [s1111aaaa#1]'));
  assert.equal(line, `- [s1111aaaa#1] ${'ก'.repeat(200)}`);
});

test('different steps propose; shared steps do not', async () => {
  const h = home();
  installed(h);
  const doc = { clusters: [record('sk-one', null, null, ['Read>Edit', 'Edit>Bash'])] };
  const before = skill(h);
  const [events, state] = await step(h, {
    doc,
    sources: { turns: [{ id: 's1111aaaa#1', ok: true, tools: ['Grep', 'Write', 'Grep'], ts: AFTER }], uses: [{ fact: 'sk-one', session: '1111aaaa-x', ts: AFTER }] },
  });
  assert.deepEqual(events, ['proposed a change to sk-one']);
  assert.equal(skill(h), before);
  assert.ok(state.skills['sk-one'].proposal.text.includes('It also worked as Grep > Write > Grep [s1111aaaa#1].'));
  const h2 = home();
  installed(h2);
  const [ev2] = await step(h2, {
    doc,
    sources: { turns: [{ id: 's1111aaaa#1', ok: true, tools: ['Read', 'Edit', 'Bash'], ts: AFTER }], uses: [{ fact: 'sk-one', session: '1111aaaa-x', ts: AFTER }] },
  });
  assert.deepEqual(ev2, []);
});

const together = (n, extraA = 0) => ({
  injects: [
    ...Array.from({ length: n }, (_, i) => ({ names: ['sk-a', 'sk-b'], session: `s-${i}`, ts: AFTER })),
    ...Array.from({ length: extraA }, (_, i) => ({ names: ['sk-a'], session: `x-${i}`, ts: AFTER })),
  ],
});

test('a merge pair is a proposal only; 4 sessions or under half never', async () => {
  const h = home();
  installed(h, 'sk-a');
  installed(h, 'sk-b');
  const before = [skill(h, 'sk-a'), skill(h, 'sk-b')];
  const [events, state] = await step(h, { sources: together(5) });
  assert.deepEqual(events, ['proposed merging sk-a with sk-b']);
  assert.deepEqual(state.skills['sk-a'].proposal, { at: LATER, kind: 'merge', status: 'pending', with: 'sk-b' });
  const said = await sp.render('approve', 'sk-a', null, h, null, LATER);
  assert.ok(said.startsWith('merging sk-a with sk-b is not done for you'));
  assert.deepEqual([skill(h, 'sk-a'), skill(h, 'sk-b')], before);
  const h2 = home();
  installed(h2, 'sk-a');
  installed(h2, 'sk-b');
  assert.deepEqual((await step(h2, { sources: together(4) }))[0], []);
  assert.deepEqual((await step(h2, { sources: together(5, 6) }))[0], []);
});

test('on an edited skill everything is a proposal; approving keeps it edited', async () => {
  const h = home();
  const d = installed(h);
  appendFileSync(join(d, 'SKILL.md'), 'my own line\n');
  const edited = readFileSync(join(d, 'SKILL.md'));
  setV(h, 'sk-one', { injects: 5, false_fires: 3 });
  const stub = new Stub(draft('sk-one', NARROW));
  const [events, state] = await step(h, { sources: corrected(), chain: [stub] });
  assert.deepEqual(events, ['proposed a change to sk-one']);
  assert.ok(readFileSync(join(d, 'SKILL.md')).equals(edited));
  const e = state.skills['sk-one'];
  assert.equal(e.version, 1);
  assert.equal(e.proposal.kind, 'improve');
  assert.ok(e.proposal.diff.includes('+- [s1111aaaa#1] no, use the other parser'));
  assert.equal(await sp.render('approve', 'sk-one', null, h, null, LATER), 'updated skill sk-one to v2');
  const e2 = sf.readState(h).skills['sk-one'];
  assert.equal(e2.edited, true);
  assert.equal(si.editedByHand(e2), true);
  setV(h, 'sk-one', { injects: 9, false_fires: 9 }, '2');
  const [ev3] = await step(h, { chain: [stub], now: '2026-10-29T12:00:00.000Z' });
  assert.deepEqual(ev3, ['proposed a change to sk-one']);
  assert.equal(sf.readState(h).skills['sk-one'].version, 2);
});

test('a proposal whose file changed since is refused; an automatic change to an edited skill too', async () => {
  const h = home();
  const d = installed(h);
  await step(h, { sources: corrected() });
  appendFileSync(join(d, 'SKILL.md'), 'later\n');
  assert.equal(
    await sp.render('approve', 'sk-one', null, h, null, LATER),
    'could not apply the proposed change to sk-one: sk-one changed after this change was proposed; reject it and wait for a new one',
  );
  assert.throws(() => si.newVersion('sk-one', draft('sk-one', NARROW), h, LATER, 'auto'), {
    message: 'sk-one was edited by hand; it only receives proposed changes',
  });
});

test('event items and text helpers', () => {
  const c = sp.COMMAND;
  assert.equal(sp.eventItem('improved skill sk-one to v2'), 'improved sk-one to v2');
  assert.equal(sp.eventItem('proposed a change to sk-one'), 'a change to sk-one waits on you');
  assert.equal(sp.eventItem('proposed merging a with b'), 'merging a with b waits on you');
  assert.equal(sp.eventItem('waiting on a drafter to tune sk-one'), `sk-one waits on a drafter (${c} approve sk-one)`);
  assert.equal(si.appendToSection('## Pitfalls\n\nNone.\n\n## Example', '## Pitfalls', ['- a']), '## Pitfalls\n\n- a\n\n## Example');
  assert.equal(si.appendToSection('## Pitfalls\n\n- x\n## Example', '## Pitfalls', ['- a']), '## Pitfalls\n\n- x\n- a\n\n## Example');
  assert.equal(si.appendToSection('## Steps\n\n1. x', '## Pitfalls', ['- a']), '## Steps\n\n1. x\n\n## Pitfalls\n\n- a');
  assert.equal(si.nextStepNumber('## Steps\n\n1. a\n2) b\n- c\n## X\n3. d'), 3);
  assert.equal(si.skillDiff(draft(), draft()), '');
});
