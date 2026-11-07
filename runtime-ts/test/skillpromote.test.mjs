/**
 * skillpromote (#206 Task 9), port side: mirrors `runtime-py/tests/test_skillpromote.py`, so a
 * Node-only regression is red here before `skill-promote` sees it. Every home is a tmp dir and
 * every link lands under that home's (or a tmp project's) `.claude/skills`. Synthetic fixtures.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { appendFileSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, readlinkSync, realpathSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, sep } from 'node:path';
import { test } from 'node:test';

import { SkillStore } from '../dist/memory/skills.js';
import * as sf from '../dist/skillfile.js';
import * as si from '../dist/skillinstall.js';
import * as sp from '../dist/skillpromote.js';

const NOW = '2026-10-27T12:00:00.000Z';
const NEXT = '2026-10-28T00:00:00.000Z';

const draft = (name) =>
  `---\nname: ${name}\ndescription: Does ${name}. Use when ${name} is asked.\n---\n\n` +
  '## When to use\n\nWhen asked.\n\n## Steps\n\n1. Do it [job1/U1].\n\n## Pitfalls\n\nNone.\n\n## Example\n\nx\n';
const descBytes = (name) => Buffer.byteLength(`Does ${name}. Use when ${name} is asked.`);

function install(home, name, level = 'user', top = null) {
  const rec = { evidence: [{ id: 'job1/U1', ok: true }], id: `c-${name}`, keywords: ['k1'], level, members: 3, source: 'shiftwork', successes: 3, top };
  return si.install(rec, draft(name), null, home, NOW, false).path;
}

function claudeHome() {
  const h = join(mkdtempSync(join(tmpdir(), 'skillpromote-')), 'home');
  mkdirSync(join(h, '.claude'), { recursive: true });
  return h;
}

const lexists = (p) => {
  try {
    lstatSync(p);
    return true;
  } catch {
    return false;
  }
};

function snapshot(d) {
  const out = {};
  const walk = (x) => {
    for (const e of readdirSync(x, { withFileTypes: true })) {
      const p = join(x, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.isFile()) out[relative(d, p).split(sep).join('/')] = readFileSync(p).toString('base64');
    }
  };
  walk(d);
  return out;
}

const offered = (home) => new SkillStore([sf.skillsRoot(home)], home).candidates().map((f) => f.name);
const raising = (code) => () => {
  const e = new Error(`${code}: injected`);
  e.code = code;
  throw e;
};
const linkOf = (home, name) => join(home, '.claude', 'skills', name);

test('constants', () => {
  assert.deepEqual([sp.PROMOTE_USES, sp.PROMOTE_DAYS, sp.BUDGET_DEFAULT, sp.BUDGET_ENV], [3, 30, 8192, 'BANTAMKIT_SKILL_BUDGET']);
});

test('the budget env', () => {
  const saved = process.env[sp.BUDGET_ENV];
  try {
    for (const [raw, want] of [[null, 8192], ['100', 100], [' 100 ', 100], ['1e3', 8192], ['-5', 8192], ['', 8192]]) {
      if (raw === null) delete process.env[sp.BUDGET_ENV];
      else process.env[sp.BUDGET_ENV] = raw;
      assert.equal(sp.skillBudget(), want, String(raw));
    }
  } finally {
    if (saved === undefined) delete process.env[sp.BUDGET_ENV];
    else process.env[sp.BUDGET_ENV] = saved;
  }
});

/** Automatic promotion follows BANTAMKIT_SKILL_AUTO (job73 ruling): `promoteStep` tests opt in. */
function withAuto(value, fn) {
  const saved = process.env[si.AUTO_ENV];
  if (value === null) delete process.env[si.AUTO_ENV];
  else process.env[si.AUTO_ENV] = value;
  try {
    return fn();
  } finally {
    if (saved === undefined) delete process.env[si.AUTO_ENV];
    else process.env[si.AUTO_ENV] = saved;
  }
}

for (const raw of [null, '', 'off', '0', 'banana', 'on please']) {
  test(`promoteStep with BANTAMKIT_SKILL_AUTO=${JSON.stringify(raw)} promotes and records nothing`, () =>
    withAuto(raw, () => {
      const home = claudeHome();
      install(home, 'skill-a');
      install(home, 'skill-b');
      const before = readFileSync(sf.statePath(home));
      const state = sf.readState(home);
      assert.deepEqual(sp.promoteStep(state, { 'skill-a': 3, 'skill-b': 9 }, home, null, NOW, 1), []);
      assert.deepEqual(readFileSync(sf.statePath(home)), before);
      assert.ok(!existsSync(join(home, '.claude', 'skills')));
      assert.ok(!('promote_refused' in state.skills['skill-a']));
      // the person asking still promotes: `promote` never reads the switch
      assert.equal(sp.promote('skill-a', home, null, NOW, 8192).reason, 'promoted skill skill-a');
    }));
}

test('two uses wait, three promote as a symlink to the source', () => withAuto('on', () => {
  const home = claudeHome();
  const src = install(home, 'skill-a');
  install(home, 'skill-b');
  const state = sf.readState(home);
  assert.deepEqual(sp.promoteStep(state, { 'skill-a': 3, 'skill-b': 2 }, home, null, NOW, 8192), ['promoted skill skill-a']);
  const link = linkOf(home, 'skill-a');
  assert.ok(lstatSync(link).isSymbolicLink());
  assert.equal(readlinkSync(link), join('..', '..', '.bantamkit', 'skills', 'skill-a'));
  assert.equal(realpathSync(link), realpathSync(src));
  assert.ok(!lexists(linkOf(home, 'skill-b')));
  assert.equal(state.skills['skill-a'].promoted.mode, 'symlink');
  assert.ok(!('promoted' in state.skills['skill-b']));
}));

test('the budget refuses one byte over and passes exactly at it', () => {
  const home = claudeHome();
  install(home, 'skill-a');
  const n = descBytes('skill-a');
  const over = sp.promote('skill-a', home, null, NOW, n - 1);
  assert.equal(over.ok, false);
  assert.equal(over.reason, `promoting skill-a would take the catalogue to ${n} bytes, over the budget of ${n - 1}`);
  assert.ok(!lexists(linkOf(home, 'skill-a')));
  const at = sp.promote('skill-a', home, null, NOW, n);
  assert.deepEqual([at.ok, at.mode], [true, 'symlink']);
});

test('a second promotion counts the first link', () => {
  const home = claudeHome();
  install(home, 'skill-a');
  install(home, 'skill-b');
  const [a, b] = [descBytes('skill-a'), descBytes('skill-b')];
  assert.ok(sp.promote('skill-a', home, null, NOW, a).ok);
  assert.ok(!sp.promote('skill-b', home, null, NOW, a + b - 1).ok);
  assert.ok(sp.promote('skill-b', home, null, NOW, a + b).ok);
});

test('a foreign skill is never replaced', () => {
  const home = claudeHome();
  install(home, 'skill-a');
  const foreign = linkOf(home, 'skill-a');
  mkdirSync(foreign, { recursive: true });
  const text = '---\nname: skill-a\ndescription: mine\n---\n';
  writeFileSync(join(foreign, 'SKILL.md'), text);
  const got = sp.promote('skill-a', home, null, NOW, 8192);
  assert.equal(got.ok, false);
  assert.equal(got.reason, `${foreign} already exists and is not this skill's link`);
  assert.equal(readFileSync(join(foreign, 'SKILL.md'), 'utf8'), text);
});

for (const code of ['EPERM', 'EACCES']) {
  test(`no symlink right (${code}) copies`, () => {
    const home = claudeHome();
    const src = install(home, 'skill-a');
    const got = sp.promote('skill-a', home, null, NOW, 8192, { symlink: raising(code) });
    assert.deepEqual([got.ok, got.mode], [true, 'copy']);
    const copy = linkOf(home, 'skill-a');
    assert.ok(statSync(copy).isDirectory() && !lstatSync(copy).isSymbolicLink());
    assert.deepEqual(snapshot(copy), snapshot(src));
    const rec = sf.readState(home).skills['skill-a'].promoted;
    assert.equal(rec.mode, 'copy');
    assert.equal(rec.tree_sha256, sp.treeHash(copy));
  });
}

test('any other symlink failure refuses and copies nothing', () => {
  const home = claudeHome();
  install(home, 'skill-a');
  const got = sp.promote('skill-a', home, null, NOW, 8192, { symlink: raising('ENOENT') });
  const link = linkOf(home, 'skill-a');
  assert.deepEqual([got.ok, got.reason], [false, `could not link ${link}: ENOENT`]);
  assert.ok(!lexists(link));
  assert.ok(!('promoted' in sf.readState(home).skills['skill-a']));
});

test('demote removes the link and leaves the source byte-identical', () => {
  const home = claudeHome();
  const src = install(home, 'skill-a');
  const before = snapshot(src);
  assert.ok(sp.promote('skill-a', home, null, NOW, 8192).ok);
  assert.equal(sp.demote('skill-a', home), 'demoted skill skill-a');
  assert.ok(!lexists(linkOf(home, 'skill-a')));
  assert.deepEqual(snapshot(src), before);
  assert.ok(!('promoted' in sf.readState(home).skills['skill-a']));
});

test('demote of a changed copy refuses', () => {
  const home = claudeHome();
  install(home, 'skill-a');
  sp.promote('skill-a', home, null, NOW, 8192, { symlink: raising('EPERM') });
  const copy = linkOf(home, 'skill-a');
  appendFileSync(join(copy, 'SKILL.md'), 'mine now\n');
  assert.throws(() => sp.demote('skill-a', home), (e) => e instanceof sp.PromoteError && e.message === `${copy} was changed after promotion; remove it yourself or keep it`);
  assert.ok(existsSync(copy));
});

test('demote of an unchanged copy removes it', () => {
  const home = claudeHome();
  const src = install(home, 'skill-a');
  const before = snapshot(src);
  sp.promote('skill-a', home, null, NOW, 8192, { symlink: raising('EACCES') });
  assert.equal(sp.demote('skill-a', home), 'demoted skill skill-a');
  assert.ok(!lexists(linkOf(home, 'skill-a')));
  assert.deepEqual(snapshot(src), before);
});

test('the layer leaves a promoted skill out and takes a demoted one back', () => {
  const home = claudeHome();
  install(home, 'skill-a');
  install(home, 'skill-b');
  assert.deepEqual(offered(home), ['skill-a', 'skill-b']);
  sp.promote('skill-a', home, null, NOW, 8192);
  assert.deepEqual(offered(home), ['skill-b']);
  sp.demote('skill-a', home);
  assert.deepEqual(offered(home), ['skill-a', 'skill-b']);
});

test('no Claude Code, no promotion', () => {
  const h = join(mkdtempSync(join(tmpdir(), 'skillpromote-')), 'bare');
  install(h, 'skill-a');
  assert.equal(sp.promote('skill-a', h, null, NOW, 8192).reason, 'promotion is Claude Code only; this host has no skill directory');
  assert.ok(!existsSync(join(h, '.claude')));
});

test('a project skill links into the project', () => {
  const home = claudeHome();
  const top = join(home, '..', 'proj');
  mkdirSync(top);
  install(home, 'skill-p', 'project', top);
  assert.ok(sp.promote('skill-p', home, top, NOW, 8192).ok);
  assert.equal(readlinkSync(join(top, '.claude', 'skills', 'skill-p')), join('..', '..', '.bantamkit', 'skills', 'skill-p'));
  assert.ok(!lexists(linkOf(home, 'skill-p')));
});

test('a refusal is recorded and not retried the same day', () => withAuto('on', () => {
  const home = claudeHome();
  install(home, 'skill-a');
  const state = sf.readState(home);
  assert.deepEqual(sp.promoteStep(state, { 'skill-a': 3 }, home, null, NOW, 1), []);
  assert.equal(state.skills['skill-a'].promote_refused.at, NOW);
  assert.deepEqual(sp.promoteStep(state, { 'skill-a': 3 }, home, null, '2026-10-27T23:59:59.999Z'), []);
  assert.deepEqual(sp.promoteStep(state, { 'skill-a': 3 }, home, null, NEXT, 8192), ['promoted skill skill-a']);
  assert.ok(!('promote_refused' in state.skills['skill-a']));
}));

test('recordRefusal sets the entry and ignores an unknown name', () => {
  const home = claudeHome();
  install(home, 'p-one');
  sp.recordRefusal(home, 'p-one', NOW, 'why');
  assert.deepEqual(sf.readState(home).skills['p-one'].promote_refused, { at: NOW, reason: 'why' });
  const before = sf.readState(home);
  sp.recordRefusal(home, 'nope', NOW, 'why');
  assert.deepEqual(sf.readState(home), before);
});

test('unknown and unpromoted names', () => {
  const home = claudeHome();
  assert.equal(sp.promote('nope', home, null, NOW, 8192).reason, "no skill named 'nope' is installed");
  assert.throws(() => sp.demote('nope', home), /no skill named 'nope' is installed/);
  install(home, 'skill-a');
  assert.throws(() => sp.demote('skill-a', home), /skill skill-a is not promoted/);
});

// ------------------------------------------------------------- #244: a copy follows its source

const draft2 = (name) => draft(name).replace('1. Do it [job1/U1].\n', '1. Do it [job1/U1].\n2. Check it [job1/U1].\n');

function promotedByCopy(home, name) {
  const src = install(home, name);
  const got = sp.promote(name, home, null, NOW, 8192, { symlink: raising('EPERM') });
  assert.deepEqual([got.ok, got.mode], [true, 'copy']);
  return src;
}
const recorded = (home, name) => sf.readState(home).skills[name].promoted.tree_sha256;
const skillText = (d) => readFileSync(join(d, 'SKILL.md'), 'utf8');

test('#244: newVersion refreshes the copy and its recorded hash', () => {
  const home = claudeHome();
  const src = promotedByCopy(home, 'skill-a');
  assert.equal(si.newVersion('skill-a', draft2('skill-a'), home, NOW, 'auto'), 'updated skill skill-a to v2');
  const copy = linkOf(home, 'skill-a');
  assert.deepEqual(snapshot(copy), snapshot(src));
  assert.ok(skillText(copy).includes('2. Check it'));
  assert.equal(recorded(home, 'skill-a'), sp.treeHash(copy));
  assert.equal(sp.demote('skill-a', home), 'demoted skill skill-a');
});

test('#244: an approved change refreshes the copy', () => {
  const home = claudeHome();
  const src = promotedByCopy(home, 'skill-a');
  si.newVersion('skill-a', draft2('skill-a'), home, NOW, 'approved');
  assert.deepEqual(snapshot(linkOf(home, 'skill-a')), snapshot(src));
});

test('#244: a rollback and an undo refresh the copy', () => {
  const home = claudeHome();
  const src = promotedByCopy(home, 'skill-a');
  si.newVersion('skill-a', draft2('skill-a'), home, NOW, 'auto');
  sf.updateState(home, (fresh) => {
    const vs = (fresh.skills['skill-a'].versions ??= {});
    vs['1'] = { ...(vs['1'] ?? {}), uses: 5, successes: 5, injects: 0, false_fires: 0 };
    vs['2'] = { ...vs['2'], uses: 5, successes: 0, injects: 0, false_fires: 0 };
  });
  const state = sf.readState(home);
  assert.deepEqual(si.judgeStep(state, home, NEXT), ['rolled back skill-a to v1']);
  const copy = linkOf(home, 'skill-a');
  assert.deepEqual(snapshot(copy), snapshot(src));
  assert.ok(!skillText(copy).includes('2. Check it'));
  assert.equal(state.skills['skill-a'].promoted.tree_sha256, sp.treeHash(copy));
  assert.equal(recorded(home, 'skill-a'), sp.treeHash(copy));

  si.undo('skill-a', home); // the newest backup is v2, taken by the rollback
  assert.ok(skillText(copy).includes('2. Check it'));
  assert.deepEqual(snapshot(copy), snapshot(src));
  assert.equal(recorded(home, 'skill-a'), sp.treeHash(copy));
});

test('#244: a copy edited by hand is left as it is and said so', () => {
  const home = claudeHome();
  const src = promotedByCopy(home, 'skill-a');
  const copy = linkOf(home, 'skill-a');
  appendFileSync(join(copy, 'SKILL.md'), 'mine now\n');
  const mine = snapshot(copy);
  const before = recorded(home, 'skill-a');
  assert.equal(
    si.newVersion('skill-a', draft2('skill-a'), home, NOW, 'auto'),
    `updated skill skill-a to v2; left the promoted copy at ${copy} as it is: it was changed after promotion`,
  );
  assert.deepEqual(snapshot(copy), mine);
  assert.notDeepEqual(snapshot(src), mine);
  assert.equal(recorded(home, 'skill-a'), before);
});

test('#244: a removed copy is not brought back', () => {
  const home = claudeHome();
  promotedByCopy(home, 'skill-a');
  const copy = linkOf(home, 'skill-a');
  rmSync(copy, { recursive: true });
  assert.ok(si.newVersion('skill-a', draft2('skill-a'), home, NOW, 'auto').endsWith('as it is: it was changed after promotion'));
  assert.equal(lexists(copy), false);
});

test('#244: a failed swap keeps the old copy, and the next write refreshes', () => {
  const home = claudeHome();
  const src = promotedByCopy(home, 'skill-a');
  const copy = linkOf(home, 'skill-a');
  const old = snapshot(copy);
  const before = recorded(home, 'skill-a');
  const saved = { ...sf.seams };
  const under = `${sep}.claude${sep}skills${sep}`;
  sf.seams.write = (file, data) => {
    if (file.includes(under)) {
      const e = new Error('EACCES: injected');
      e.code = 'EACCES';
      throw e;
    }
    saved.write(file, data);
  };
  try {
    assert.equal(
      si.newVersion('skill-a', draft2('skill-a'), home, NOW, 'auto'),
      `updated skill skill-a to v2; could not refresh the promoted copy at ${copy}: EACCES`,
    );
  } finally {
    Object.assign(sf.seams, saved);
  }
  assert.deepEqual(snapshot(copy), old);
  assert.deepEqual(readdirSync(join(home, '.claude', 'skills')), ['skill-a']);
  assert.equal(recorded(home, 'skill-a'), before);
  si.undo('skill-a', home);
  si.newVersion('skill-a', draft2('skill-a'), home, NOW, 'auto');
  assert.deepEqual(snapshot(copy), snapshot(src));
});

test('#244: a symlink needs no refresh', () => {
  const home = claudeHome();
  install(home, 'skill-a');
  assert.equal(sp.promote('skill-a', home, null, NOW, 8192).mode, 'symlink');
  assert.equal(si.newVersion('skill-a', draft2('skill-a'), home, NOW, 'auto'), 'updated skill skill-a to v2');
  assert.ok(lstatSync(linkOf(home, 'skill-a')).isSymbolicLink());
});

test('#244: a copy already matching the source only has its record brought up', () => {
  const home = claudeHome();
  const src = promotedByCopy(home, 'skill-a');
  si.newVersion('skill-a', draft2('skill-a'), home, NOW, 'auto');
  sf.updateState(home, (fresh) => {
    fresh.skills['skill-a'].promoted.tree_sha256 = '0'.repeat(64);
  });
  assert.equal(sp.refreshCopy('skill-a', home), null);
  assert.equal(recorded(home, 'skill-a'), sp.treeHash(src));
});

test('#244: refresh of no copy says nothing', () => {
  const home = claudeHome();
  assert.equal(sp.refreshCopy('nope', home), null);
  install(home, 'skill-a');
  assert.equal(sp.refreshCopy('skill-a', home), null);
});

test('#244: rewriteDirAtomic replaces in place and refuses what is not a directory', () => {
  const root = mkdtempSync(join(tmpdir(), 'rewrite-'));
  const d = join(root, 'd');
  sf.writeDirAtomic(d, { 'a.md': Buffer.from('old'), 'sub/b.md': Buffer.from('b') });
  sf.rewriteDirAtomic(d, { 'a.md': Buffer.from('new') });
  assert.deepEqual(snapshot(d), { 'a.md': Buffer.from('new').toString('base64') });
  assert.deepEqual(readdirSync(root), ['d']);
  assert.throws(() => sf.rewriteDirAtomic(join(root, 'missing'), { 'a.md': Buffer.from('x') }), /no skill at/);
  symlinkSync(d, join(root, 'link'), 'dir');
  assert.throws(() => sf.rewriteDirAtomic(join(root, 'link'), { 'a.md': Buffer.from('x') }), /no skill at/);
  assert.deepEqual(snapshot(d), { 'a.md': Buffer.from('new').toString('base64') });
});
