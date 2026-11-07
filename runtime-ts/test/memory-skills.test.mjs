/**
 * bantamkit's learned skills as the read-only `[skill]` recall layer (#206 Task 2, X8).
 *
 * The port's half of `runtime-py/tests/test_memory_skills.py`. The differential is
 * `tools/conformance/suites/skill-layer.mjs`. Every test gets its own HOME.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { existsSync, mkdirSync, mkdtempSync, rmSync, readdirSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { Memory } from '../dist/memory/component.js';
import {
  keywordsOf,
  promotedNames,
  SkillStore,
  skillRoots,
  TRIGGERS_DEFAULT,
  triggersEnabled,
  triggersOf,
} from '../dist/memory/skills.js';
import { UsageLedger } from '../dist/memory/usage.js';
import { MemoryStore, RECALL_MIN_SCORE_RATIO } from '../dist/memory/store.js';
import { writeState } from '../dist/skillfile.js';

const STEPS = '## Steps\n\n1. Run it.\n';

function skill(root, name, description, { keywords = null, body = STEPS, dirname = null, triggers = null } = {}) {
  const d = join(root, dirname ?? name);
  mkdirSync(d, { recursive: true });
  const rows = [
    ...(keywords === null ? [] : [`  bantamkit-keywords: "${keywords}"\n`]),
    ...(triggers === null ? [] : [`  bantamkit-triggers: "${triggers}"\n`]),
  ];
  const meta = rows.length === 0 ? '' : `metadata:\n${rows.join('')}`;
  writeFileSync(join(d, 'SKILL.md'), `---\nname: ${name}\ndescription: "${description}"\n${meta}---\n\n${body}`);
  return d;
}

function tree(root) {
  const out = {};
  const walk = (d, rel) => {
    for (const n of readdirSync(d).sort()) {
      const p = join(d, n);
      const r = rel ? `${rel}/${n}` : n;
      if (statSync(p).isDirectory()) walk(p, r);
      else out[r] = [readFileSync(p, 'latin1'), statSync(p).mtimeMs];
    }
  };
  walk(root, '');
  return out;
}

const quiet = (mem, q, k = null) => mem.recallOutcome(q, k, RECALL_MIN_SCORE_RATIO, false);

function withBed(fn) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'bk-skills-')));
  const home = join(root, 'home');
  mkdirSync(home);
  const before = [process.env.HOME, process.env.USERPROFILE];
  process.env.HOME = home;
  process.env.USERPROFILE = home;
  try {
    const project = join(root, 'companyA');
    const store = join(project, '.bantamkit', 'memory');
    new MemoryStore(store).save('project', 'deploy', 'how we deploy', 'b');
    return fn({
      root,
      home,
      project,
      store,
      proj: join(project, '.bantamkit', 'skills'),
      user: join(home, '.bantamkit', 'skills'),
    });
  } finally {
    [process.env.HOME, process.env.USERPROFILE] = before;
  }
}

test('the layer is bound only when a skills root is there', () =>
  withBed(({ project, user }) => {
    assert.deepEqual(Memory.layered(project).layerLabels(), ['project', 'profile']);
    mkdirSync(user, { recursive: true });
    assert.deepEqual(Memory.layered(project).layerLabels(), ['project', 'profile', 'skill']);
  }));

test('the layer is after profile and before native', () =>
  withBed(({ root, project, proj }) => {
    skill(proj, 'fixing-windows-encoding', 'fixes utf-8 decode failures on windows');
    const native = join(root, 'host');
    mkdirSync(native);
    assert.deepEqual(Memory.layered(project, { native }).layerLabels(), ['project', 'profile', 'skill', 'native']);
  }));

test('a matching prompt injects exactly its one header', () =>
  withBed(({ project, proj }) => {
    skill(proj, 'fixing-windows-encoding', 'fixes utf-8 decode failures on windows');
    assert.deepEqual(quiet(Memory.layered(project), 'windows decode failures').headers, [
      '[skill] [fixing-windows-encoding] (skill) fixes utf-8 decode failures on windows',
    ]);
    assert.deepEqual(quiet(Memory.layered(project), 'kubernetes ingress').headers, []);
  }));

test('recall by name returns the body', () =>
  withBed(({ project, proj }) => {
    skill(proj, 'fixing-windows-encoding', 'fixes decode failures', { body: '## Steps\n\n1. Do X.\n' });
    assert.equal(
      Memory.layered(project).recall('fixing-windows-encoding'),
      '[skill] [fixing-windows-encoding] (skill) fixes decode failures\n## Steps\n\n1. Do X.',
    );
  }));

test('a keyword alone matches', () =>
  withBed(({ project, proj }) => {
    skill(proj, 'fixing-windows-encoding', 'fixes decode failures', { keywords: 'cp1252, mojibake' });
    assert.deepEqual(quiet(Memory.layered(project), 'mojibake').headers, [
      '[skill] [fixing-windows-encoding] (skill) fixes decode failures',
    ]);
  }));

test('a fact of the same name shadows the skill', () =>
  withBed(({ project, proj }) => {
    skill(proj, 'deploy', 'deploy deploy deploy runbook', { body: '## Steps\n\n1. skill copy\n' });
    const mem = Memory.layered(project);
    assert.deepEqual(quiet(mem, 'deploy runbook').headers, ['[project] [deploy] (project) how we deploy']);
    assert.ok(!mem.recall('deploy').includes('skill copy'));
  }));

test('a skill shadows a native fact of its name', () =>
  withBed(({ root, project, proj }) => {
    skill(proj, 'fixing-windows-encoding', 'fixes decode failures');
    const native = join(root, 'host');
    mkdirSync(native);
    writeFileSync(
      join(native, 'x.md'),
      '---\nname: fixing-windows-encoding\ndescription: decode failures decode\ntype: project\n---\n\nhost copy\n',
    );
    assert.deepEqual(quiet(Memory.layered(project, { native }), 'decode failures').headers, [
      '[skill] [fixing-windows-encoding] (skill) fixes decode failures',
    ]);
  }));

test('a promoted skill is never injected nor recalled', () =>
  withBed(({ home, project, proj }) => {
    skill(proj, 'fixing-windows-encoding', 'fixes decode failures on windows');
    writeState(home, { skills: { 'fixing-windows-encoding': { promoted: 'symlink' } } });
    const mem = Memory.layered(project);
    assert.deepEqual(quiet(mem, 'windows decode failures').headers, []);
    assert.ok(!mem.recall('fixing-windows-encoding').includes('fixes decode'));
  }));

test('promoted means set and not null or false', () =>
  withBed(({ home }) => {
    for (const [value, promoted] of [['symlink', true], [{ mode: 'copy' }, true], [null, false], [false, false], [0, true]]) {
      writeState(home, { skills: { a: { promoted: value }, b: {}, c: 3 } });
      assert.deepEqual([...promotedNames(home)], promoted ? ['a'] : []);
    }
  }));

test('an unreadable state excludes nothing', () =>
  withBed(({ home, project, proj }) => {
    skill(proj, 'fixing-windows-encoding', 'fixes decode failures on windows');
    mkdirSync(join(home, '.bantamkit'), { recursive: true });
    writeFileSync(join(home, '.bantamkit', 'skills-state.json'), '{not json');
    assert.equal(quiet(Memory.layered(project), 'windows decode failures').headers.length, 1);
  }));

test('an invalid skill is skipped and named', () =>
  withBed(({ project, proj }) => {
    skill(proj, 'fixing-windows-encoding', 'fixes decode failures on windows');
    skill(proj, 'no-steps', 'decode failures without steps', { body: 'nothing\n' });
    skill(proj, 'a-b', 'decode failures misnamed', { dirname: 'other' });
    mkdirSync(join(proj, 'bad-yaml'));
    writeFileSync(join(proj, 'bad-yaml', 'SKILL.md'), 'no fences');
    mkdirSync(join(proj, 'latin'));
    writeFileSync(join(proj, 'latin', 'SKILL.md'), Buffer.from('---\nname: latin\ndescription: \xe9\n---\n', 'latin1'));
    const out = quiet(Memory.layered(project), 'windows decode failures');
    assert.deepEqual(out.headers, ['[skill] [fixing-windows-encoding] (skill) fixes decode failures on windows']);
    const p = (d) => join(proj, d, 'SKILL.md');
    assert.deepEqual(
      Object.fromEntries(out.skipped.map((s) => [s.file, [s.layer, s.reason]])),
      {
        'bad-yaml/SKILL.md': ['skill', `malformed skill ${p('bad-yaml')}: SKILL.md has no frontmatter at the top of the file`],
        'latin/SKILL.md': ['skill', `malformed skill ${p('latin')}: SKILL.md is not UTF-8`],
        'no-steps/SKILL.md': ['skill', `malformed skill ${p('no-steps')}: ## Steps is missing or empty`],
        'other/SKILL.md': ['skill', `malformed skill ${p('other')}: name 'a-b' does not match its directory 'other'`],
      },
    );
  }));

test('build and hidden directories are not skills', () =>
  withBed(({ proj }) => {
    skill(proj, 'a-b', 'decode', { dirname: 'a-b.tmp-123-0' });
    skill(proj, 'a-b', 'decode', { dirname: 'a-b.old-123-4' });
    skill(proj, 'a-b', 'decode', { dirname: '.hidden' });
    mkdirSync(join(proj, 'empty'));
    writeFileSync(join(proj, 'loose.md'), 'x');
    const store = new SkillStore([proj]);
    assert.equal(store.count(), 0);
    const skipped = [];
    assert.deepEqual(store.candidates(skipped), []);
    assert.deepEqual(skipped, []);
  }));

test('project first and a duplicate name is skipped', () =>
  withBed(({ project, proj, user }) => {
    skill(proj, 'fixing-windows-encoding', 'project copy decode failures');
    skill(user, 'fixing-windows-encoding', 'user copy decode failures');
    skill(user, 'user-only', 'user only decode failures');
    const out = quiet(Memory.layered(project), 'decode failures', 5);
    assert.deepEqual([...out.headers].sort(), [
      '[skill] [fixing-windows-encoding] (skill) project copy decode failures',
      '[skill] [user-only] (skill) user only decode failures',
    ]);
    const first = join(proj, 'fixing-windows-encoding', 'SKILL.md');
    assert.deepEqual(out.skipped, [
      {
        layer: 'skill',
        file: 'fixing-windows-encoding/SKILL.md',
        reason: `duplicate name 'fixing-windows-encoding': ${first} holds it`,
      },
    ]);
  }));

test('roots are project then user and one directory is one root', () => {
  const root = mkdtempSync(join(tmpdir(), 'bk-skill-roots-'));
  const home = join(root, 'h');
  assert.deepEqual(skillRoots(join(root, 'p', '.bantamkit', 'memory'), home), [
    join(root, 'p', '.bantamkit', 'skills'),
    join(home, '.bantamkit', 'skills'),
  ]);
  assert.deepEqual(skillRoots(join(home, '.bantamkit', 'memory'), home), [join(home, '.bantamkit', 'skills')]);
  assert.deepEqual(skillRoots(join(root, 'pinned'), home), [join(home, '.bantamkit', 'skills')]);
});

test('keywords are split on commas and stripped', () => {
  assert.deepEqual(keywordsOf(' a, b ,,c '), ['a', 'b', 'c']);
  assert.deepEqual(keywordsOf(''), []);
  assert.deepEqual(keywordsOf(null), []);
});

test('recall writes nothing into the skills dir and counts one hit', () =>
  withBed(({ project, proj, store }) => {
    skill(proj, 'fixing-windows-encoding', 'fixes decode failures on windows', { keywords: 'cp1252' });
    const before = tree(proj);
    const mem = Memory.layered(project);
    mem.recall('windows decode failures');
    assert.deepEqual(tree(proj), before);
    assert.equal(mem.repaired, 0);
    const ledger = readFileSync(mem.usage().path, 'utf8');
    assert.deepEqual(
      ledger.trim().split('\n').map((l) => JSON.parse(l)).map((e) => [e.fact, e.kind]),
      [['fixing-windows-encoding', 'recall_hit']],
    );
    assert.ok(store);
    mem.recall('fixing-windows-encoding');
    assert.deepEqual(tree(proj), before);
  }));

test('a skills root that is not a directory is a root of nothing', () =>
  withBed(({ home, project, proj }) => {
    mkdirSync(join(proj, '..'), { recursive: true });
    writeFileSync(proj, 'not a directory');
    mkdirSync(join(home, '.bantamkit', 'skills'), { recursive: true });
    assert.deepEqual(quiet(Memory.layered(project), 'deploy').headers, ['[project] [deploy] (project) how we deploy']);
  }));

test('layeredForEval takes skill roots', () =>
  withBed(({ root }) => {
    const s = join(root, 's');
    skill(s, 'fixing-windows-encoding', 'fixes decode failures');
    const mem = Memory.layeredForEval(join(root, 'p'), join(root, 'q'), 'v2', null, [s]);
    assert.deepEqual(mem.layerLabels(), ['project', 'profile', 'skill']);
    assert.deepEqual(mem.injectCandidates('decode failures').map((f) => f.name), ['fixing-windows-encoding']);
  }));

// ---------------------------------------------------------------------- trigger firing (#301)

const CHROME = { description: 'drive the browser', triggers: 'เปิด chrome|chrome tab' };
const ENV = 'BANTAMKIT_SKILL_TRIGGERS';

/** Run `fn` with the switch set to `value` (`undefined` unsets it), the old value restored. */
function withSwitch(value, fn) {
  const before = process.env[ENV];
  if (value === undefined) delete process.env[ENV];
  else process.env[ENV] = value;
  try {
    return fn();
  } finally {
    if (before === undefined) delete process.env[ENV];
    else process.env[ENV] = before;
  }
}

/** `{name: {description, ...}}` written as the project's only skills; the layered `Memory`. */
function memWithSkills({ project, proj }, skills) {
  rmSync(proj, { recursive: true, force: true });
  for (const [name, { description, ...kw }] of Object.entries(skills)) skill(proj, name, description, kw);
  return Memory.layered(project);
}

/** The same recall with the switch off, the switch restored to `on` afterwards. */
const off = (m, prompt) => withSwitch('off', () => quiet(m, prompt, 3));

function uses({ home, project }, name) {
  const ledger = new UsageLedger(home, join(project, '.bantamkit', 'memory')).path;
  if (!existsSync(ledger)) return [];
  return readFileSync(ledger, 'utf8')
    .split('\n')
    .filter((l) => l !== '')
    .map((l) => JSON.parse(l))
    .filter((r) => r.fact === name);
}

const firedOf = (o) => o.fired ?? null;

test('a trigger fires one line after the top-k', () =>
  withBed((bed) =>
    withSwitch('on', () => {
      const m = memWithSkills(bed, { 'web-driving': CHROME });
      const prompt = 'ช่วย เปิด chrome ให้หน่อย';
      const base = off(m, prompt);
      const o = quiet(m, prompt, 3);
      assert.equal(o.fired, 'web-driving');
      assert.equal(firedOf(base), null);
      if (base.status === 'answered') {
        assert.ok(o.reply.startsWith(base.reply + '\n\n'));
        assert.deepEqual(o.headers.slice(0, base.headers.length), base.headers);
      }
      assert.equal(o.headers.at(-1), '[skill] [web-driving] (skill) drive the browser');
      assert.ok(o.reply.endsWith('[skill] [web-driving] (skill) drive the browser\n' + STEPS.trimEnd()));
      assert.equal(o.headers.filter((h) => h.startsWith('[skill] [web-driving]')).length, 1);
      assert.equal(o.status, 'answered');
      assert.equal(o.returned, base.returned + 1);
    }),
  ));

test('a trigger appends after a live top-k byte for byte', () =>
  withBed((bed) =>
    withSwitch('on', () => {
      const m = memWithSkills(bed, { 'web-driving': CHROME });
      const prompt = 'deploy then เปิด chrome tab';
      const base = off(m, prompt);
      assert.deepEqual(base.headers, ['[project] [deploy] (project) how we deploy']);
      const o = quiet(m, prompt, 3);
      assert.equal(o.reply, base.reply + '\n\n[skill] [web-driving] (skill) drive the browser\n' + STEPS.trimEnd());
      assert.deepEqual(o.headers, [...base.headers, '[skill] [web-driving] (skill) drive the browser']);
      assert.deepEqual([o.fired, o.returned, o.source], ['web-driving', 2, 'project']);
    }),
  ));

test('a trigger inside a pasted block does not fire', () =>
  withBed((bed) =>
    withSwitch('on', () => {
      const m = memWithSkills(bed, { 'web-driving': CHROME });
      assert.equal(firedOf(quiet(m, 'look at this\n```\nเปิด chrome\n```', 3)), null);
    }),
  ));

test('the trigger switch off is byte identical', () =>
  withBed((bed) => {
    const m = memWithSkills(bed, { 'web-driving': CHROME });
    const o = withSwitch('off', () => quiet(m, 'เปิด chrome tab', 3));
    assert.equal(firedOf(o), null);
    assert.deepEqual(o.headers, []);
    const on = withSwitch('on', () => quiet(m, 'เปิด chrome tab', 3));
    assert.equal(on.fired, 'web-driving');
    assert.ok(on.reply.startsWith(o.reply) || o.status !== 'answered');
  }));

test('a trigger never fires a promoted skill', () =>
  withBed((bed) =>
    withSwitch('on', () => {
      writeState(bed.home, { skills: { 'web-driving': { promoted: 'symlink' } } });
      const m = memWithSkills(bed, { 'web-driving': CHROME });
      assert.equal(firedOf(quiet(m, 'เปิด chrome tab', 3)), null);
    }),
  ));

test('a trigger never fires a shadowed skill', () =>
  withBed((bed) =>
    withSwitch('on', () => {
      // f2 (#301): a project fact holding the skill's name shadows it in `pooled`, so the skill
      // never fires either -- a `[skill] [web-driving]` line whose name recalls the fact would
      // name one thing and answer another.
      new MemoryStore(bed.store).save('project', 'web-driving', 'the project note on driving', 'fact copy');
      const m = memWithSkills(bed, { 'web-driving': CHROME, 'tab-other': { description: 'o' } });
      const o = quiet(m, 'zzz เปิด chrome zzz', 3);
      assert.equal(firedOf(o), null);
      assert.ok(!o.headers.some((h) => h.startsWith('[skill] [web-driving]')));
      assert.ok(m.recall('web-driving').includes('fact copy'));
      // an unshadowed skill still fires on the same walk
      const m2 = memWithSkills(bed, { 'web-drive-2': CHROME });
      assert.equal(quiet(m2, 'zzz เปิด chrome zzz', 3).fired, 'web-drive-2');
    }),
  ));

test('a skill already shown is not appended twice', () =>
  withBed((bed) =>
    withSwitch('on', () => {
      const m = memWithSkills(bed, { 'web-driving': CHROME });
      const o = quiet(m, 'drive the browser chrome เปิด chrome', 3);
      assert.equal(firedOf(o), null);
      assert.equal(o.headers.filter((h) => h.startsWith('[skill] [web-driving]')).length, 1);
    }),
  ));

test('the longest trigger then the name wins', () =>
  withBed((bed) =>
    withSwitch('on', () => {
      const m = memWithSkills(bed, {
        'b-two': { description: 'b', triggers: 'open chrome' },
        'a-two': { description: 'a', triggers: 'open chrome' },
        'c-three': { description: 'c', triggers: 'open chrome tab' },
      });
      assert.equal(quiet(m, 'zzz open chrome tab zzz', 3).fired, 'c-three');
      const m2 = memWithSkills(bed, {
        'b-two': { description: 'b', triggers: 'open chrome' },
        'a-two': { description: 'a', triggers: 'open chrome' },
      });
      assert.equal(quiet(m2, 'zzz open chrome zzz', 3).fired, 'a-two');
    }),
  ));

test('the exact-name walk never fires a trigger', () =>
  withBed((bed) =>
    withSwitch('on', () => {
      const m = memWithSkills(bed, { 'web-driving': CHROME, 'chrome-tab': { description: 'x' } });
      const o = quiet(m, 'chrome-tab', 3);
      assert.equal(o.lookup, 'hit');
      assert.deepEqual(o.headers, ['[skill] [chrome-tab] (skill) x']);
      assert.equal(firedOf(o), null);
    }),
  ));

test('a fired skill is a recall hit only when stamped', () =>
  withBed((bed) =>
    withSwitch('on', () => {
      const m = memWithSkills(bed, { 'web-driving': CHROME });
      m.recallOutcome('เปิด chrome tab', 3, RECALL_MIN_SCORE_RATIO, false);
      assert.deepEqual(uses(bed, 'web-driving'), []);
      m.recallOutcome('เปิด chrome tab', 3, RECALL_MIN_SCORE_RATIO, true);
      assert.deepEqual(uses(bed, 'web-driving').map((r) => r.kind), ['recall_hit']);
    }),
  ));

test('triggersEnabled parses the switch', () => {
  for (const [v, want] of [
    ['on', true],
    [' TRUE ', true],
    ['1', true],
    ['yes', true],
    ['off', false],
    ['0', false],
    ['nah', false],
  ]) {
    withSwitch(v, () => assert.equal(triggersEnabled(), want));
  }
  for (const v of ['', '  ']) withSwitch(v, () => assert.equal(triggersEnabled(), TRIGGERS_DEFAULT));
  withSwitch(undefined, () => assert.equal(triggersEnabled(), TRIGGERS_DEFAULT));
});

test('triggersOf splits on bars and spaces', () => {
  assert.deepEqual(triggersOf('เปิด chrome|chrome  tab|solo||'), [
    ['เปิด', 'chrome'],
    ['chrome', 'tab'],
  ]);
  assert.deepEqual(triggersOf(['a b']), []);
  assert.deepEqual(triggersOf(null), []);
});

test('a skipped duplicate lends the kept skill no triggers', () =>
  withBed(({ project, proj, user }) =>
    withSwitch('on', () => {
      skill(proj, 'web-driving', 'drive the browser', { triggers: 'เปิด chrome' });
      skill(user, 'web-driving', 'user copy', { triggers: 'chrome tab' });
      const m = Memory.layered(project);
      assert.equal(firedOf(quiet(m, 'zzz chrome tab zzz', 3)), null);
      assert.equal(quiet(m, 'zzz เปิด chrome zzz', 3).fired, 'web-driving');
    }),
  ));
