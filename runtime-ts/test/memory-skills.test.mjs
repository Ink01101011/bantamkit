/**
 * bantamkit's learned skills as the read-only `[skill]` recall layer (#206 Task 2, X8).
 *
 * The port's half of `runtime-py/tests/test_memory_skills.py`. The differential is
 * `tools/conformance/suites/skill-layer.mjs`. Every test gets its own HOME.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { Memory } from '../dist/memory/component.js';
import { keywordsOf, promotedNames, SkillStore, skillRoots } from '../dist/memory/skills.js';
import { MemoryStore, RECALL_MIN_SCORE_RATIO } from '../dist/memory/store.js';
import { writeState } from '../dist/skillfile.js';

const STEPS = '## Steps\n\n1. Run it.\n';

function skill(root, name, description, { keywords = null, body = STEPS, dirname = null } = {}) {
  const d = join(root, dirname ?? name);
  mkdirSync(d, { recursive: true });
  const meta = keywords === null ? '' : `metadata:\n  bantamkit-keywords: "${keywords}"\n`;
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
