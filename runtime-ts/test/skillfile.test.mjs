/**
 * `skillfile` (#206 Task 1), the Node half. Mirrors `runtime-py/tests/test_skillfile.py`
 * test for test, so a Node-only regression is red here before `skill-file` sees it.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, readlinkSync, realpathSync, statSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, sep } from 'node:path';
import { test } from 'node:test';

import * as sf from '../dist/skillfile.js';

const tmp = () => realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-skillfile-')));
const NOW = '2026-10-27T12:00:00.000Z';
const BODY =
  '## When to use\n\nWhen tests break.\n\n## Steps\n\n1. Run it (J1-1).\n\n## Pitfalls\n\nNone.\n\n## Example\n\nx';
const doc = (kw = {}) => ({
  name: 'fixing-windows-encoding',
  description: 'Fixes things. Use when x.',
  metadata: {},
  body: BODY,
  ...kw,
});
const sentences = (kw) => sf.validate(doc(kw));
const repr = (s) => `'${s}'`;

function listing(root) {
  const out = [];
  const walk = (dir) => {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const p = join(dir, e.name);
      out.push(relative(root, p).split(sep).join('/'));
      if (e.isDirectory()) walk(p);
    }
  };
  walk(root);
  return out.sort();
}

const throwsSentence = (fn, sentence) =>
  assert.throws(fn, (e) => e instanceof sf.SkillFileError && (sentence instanceof RegExp ? sentence.test(e.message) : e.message === sentence));

// ------------------------------------------------------------------- validate

test('a valid doc has no finding', () => assert.deepEqual(sentences(), []));

test('names that pass', () => {
  for (const name of ['a', 'a-b', 'a1-b2-c3', 'x'.repeat(64), 'using-utils', '0x1a']) {
    assert.deepEqual(sentences({ name }), [], name);
  }
});

test('names that fail the shape rule', () => {
  for (const name of ['', 'x'.repeat(65), 'a--b', '-a', 'a-', 'A', 'a_b', 'ไทย', 'a b']) {
    assert.deepEqual(sentences({ name }), [
      `name ${repr(name)} must be 1-64 characters of a-z, 0-9 and single inner hyphens`,
    ]);
  }
});

test('generic names fail', () => {
  for (const name of ['helper', 'helpers', 'util', 'utils']) {
    assert.deepEqual(sentences({ name }), [`name ${repr(name)} is a generic word; name the action instead`]);
  }
});

test('name must match its directory', () => {
  assert.deepEqual(sf.validate(doc({ name: 'a-b' }), 'a-b'), []);
  assert.deepEqual(sf.validate(doc({ name: 'a-b' }), 'a-c'), ["name 'a-b' does not match its directory 'a-c'"]);
});

test('description is counted in code points', () => {
  assert.deepEqual(sentences({ description: 'ก'.repeat(1024) }), []);
  assert.deepEqual(sentences({ description: 'ก'.repeat(1025) }), ['description is 1025 characters; at most 1024']);
  assert.deepEqual(sentences({ description: '😀'.repeat(1024) }), []);
});

test('body line limit', () => {
  const ok = '## Steps\n\n1. x\n' + Array(497).fill('y').join('\n');
  assert.equal(sf.bodyLines(ok), 500);
  assert.deepEqual(sentences({ body: ok }), []);
  assert.deepEqual(sentences({ body: ok + '\nz' }), ['body is 501 lines; at most 500']);
});

test('metadata values must be strings', () => {
  assert.deepEqual(
    sentences({ metadata: { 'bantamkit-a': '1', 'bantamkit-b': 1, 'bantamkit-c': { d: 'e' }, 'bantamkit-d': ['x'] } }),
    ['metadata bantamkit-b must be a string', 'metadata bantamkit-c must be a string', 'metadata bantamkit-d must be a string'],
  );
});

test('steps missing or empty / present', () => {
  for (const body of ['', '## When to use\n\nx', '## Steps\n', '## Steps\n\n   \n## Pitfalls\n\nx', '## Stepsx\n\n1. a', '# Steps\n\n1. a']) {
    assert.deepEqual(sentences({ body }), ['## Steps is missing or empty'], body);
  }
  for (const body of ['## Steps\n1. a', '## Steps  \n\n### Sub\n\n1. a', '## Steps\n\n- a\n## Next']) {
    assert.deepEqual(sentences({ body }), [], body);
  }
});

test('findings come in the fixed order', () => {
  const got = sf.validate(
    doc({ name: 'utils', description: 'd'.repeat(1025), metadata: { 'bantamkit-x': 3 }, body: Array(501).fill('l').join('\n') }),
    'other',
  );
  assert.deepEqual(got, [
    "name 'utils' is a generic word; name the action instead",
    "name 'utils' does not match its directory 'other'",
    'description is 1025 characters; at most 1024',
    'body is 501 lines; at most 500',
    'metadata bantamkit-x must be a string',
    '## Steps is missing or empty',
  ]);
});

// ------------------------------------------------------------- parse / render

test('render then parse round trips', () => {
  const d = doc({
    description: 'Quotes " and \\ and tab\t and ไทย and \u2028 and \x7f. Use when "x".',
    metadata: { 'bantamkit-version': '2', 'bantamkit-evidence': 'J1-1,a1b2c3d' },
  });
  const text = sf.render(d);
  assert.deepEqual(sf.parseSkill(text), d);
  assert.equal(sf.render(sf.parseSkill(text)), text);
});

test('render shape', () => {
  const text = sf.render(doc({ metadata: { 'bantamkit-z': '1', 'bantamkit-a': '2' }, body: '## Steps\n\n1. x' }));
  assert.equal(
    text,
    '---\nname: fixing-windows-encoding\ndescription: "Fixes things. Use when x."\nmetadata:\n' +
      '  bantamkit-a: "2"\n  bantamkit-z: "1"\n---\n\n## Steps\n\n1. x\n',
  );
});

test('a name YAML would not read as a string is quoted', () => {
  for (const name of ['yes', 'null', '123', '0x1a', '2026-10-27', 'A']) {
    assert.equal(sf.parseSkill(sf.render(doc({ name }))).name, name);
  }
});

test('parse reads CRLF as LF and non-string metadata', () => {
  const text = '---\r\nname: a-b\r\ndescription: d\r\nmetadata:\r\n  bantamkit-x: 3\r\n---\r\n\r\n## Steps\r\n\r\n1. x\r\n';
  const d = sf.parseSkill(text);
  assert.equal(d.name, 'a-b');
  assert.deepEqual(sf.validate(d), ['metadata bantamkit-x must be a string']);
});

test('RULED: metadata nested below one level is refused by the port (#120), named by the reference', () => {
  // docs/porting.md row `skillfile`; Python's twin test reads it and validate names the key.
  for (const text of [
    '---\nname: a\nmetadata:\n  bantamkit-x:\n    deep: v\n---\n',
    '---\nname: a\nmetadata:\n  k:\n  - a\n---\n',
  ]) {
    throwsSentence(() => sf.parseSkill(text), 'SKILL.md frontmatter is not a readable mapping');
  }
});

test('parse refusals', () => {
  for (const [text, sentence] of [
    ['no fences', 'SKILL.md has no frontmatter at the top of the file'],
    ['x\n---\nname: a\n---\n', 'SKILL.md has no frontmatter at the top of the file'],
    ['---\n- a\n---\n', 'SKILL.md frontmatter is not a readable mapping'],
    ['---\nname: [a\n---\n', 'SKILL.md frontmatter is not a readable mapping'],
    ['---\ndescription: d\n---\n', 'SKILL.md has no string name'],
    ['---\nname: 12\n---\n', 'SKILL.md has no string name'],
    ['---\nname: a\ndescription: [x]\n---\n', 'SKILL.md description is not a string'],
    ['---\nname: a\nmetadata: x\n---\n', 'SKILL.md metadata is not a mapping'],
  ]) {
    throwsSentence(() => sf.parseSkill(text), sentence);
  }
});

// ------------------------------------------------------------------ the hash

test('hash is stable under restamp and moved by an edit', () => {
  const text = sf.stamp(sf.render(doc()), { 'bantamkit-generated-by': 'bantamkit' });
  const h = sf.parseSkill(text).metadata['bantamkit-sha256'];
  assert.equal(h.length, 64);
  assert.equal(h, sf.canonicalHash(text));
  assert.equal(sf.isEdited(text), false);
  assert.equal(sf.stamp(text, {}), text);
  const edited = text.replace('Fixes things.', 'Fixes thing.');
  assert.equal(sf.isEdited(edited), true);
  assert.notEqual(sf.canonicalHash(edited), h);
  assert.equal(sf.canonicalHash(text.split('\n').join('\r\n')), h);
});

test('hash blanks only the hash value', () => {
  const a = '---\nname: a\nmetadata:\n  bantamkit-sha256: "abc"\n---\n\nbody\n';
  const b = '---\nname: a\nmetadata:\n  bantamkit-sha256: "zzz"\n---\n\nbody\n';
  assert.equal(sf.canonicalHash(a), sf.canonicalHash(b));
  const blank = '---\nname: a\nmetadata:\n  bantamkit-sha256: ""\n---\n\nbody\n';
  assert.equal(sf.canonicalHash(a), createHash('sha256').update(blank).digest('hex'));
  assert.notEqual(sf.canonicalHash(a + 'bantamkit-sha256: x\n'), sf.canonicalHash(a + 'bantamkit-sha256: y\n'));
});

test('unstamped or unreadable is edited', () => {
  assert.equal(sf.isEdited(sf.render(doc())), true);
  assert.equal(sf.isEdited('garbage'), true);
});

test('stamp refuses a foreign key', () => {
  throwsSentence(() => sf.stamp(sf.render(doc()), { version: '1' }), "metadata key 'version' is not a bantamkit- key");
});

// --------------------------------------------------------- the atomic write

const FILES = { 'SKILL.md': Buffer.from('---\nname: a-b\n---\n'), 'references/evidence.md': Buffer.from('ev\n') };

test('writeDirAtomic writes every file', () => {
  const root = tmp();
  const target = join(root, 'skills', 'a-b');
  sf.writeDirAtomic(target, FILES);
  assert.deepEqual(readFileSync(join(target, 'SKILL.md')), FILES['SKILL.md']);
  assert.equal(readFileSync(join(target, 'references', 'evidence.md'), 'utf8'), 'ev\n');
  assert.deepEqual(listing(join(root, 'skills')), ['a-b', 'a-b/SKILL.md', 'a-b/references', 'a-b/references/evidence.md']);
});

test('writeDirAtomic refuses an existing target', () => {
  const root = tmp();
  mkdirSync(join(root, 'a-b'));
  throwsSentence(() => sf.writeDirAtomic(join(root, 'a-b'), FILES), /^a skill already exists at /);
});

test('writeDirAtomic refuses a path that is not plain', () => {
  for (const rel of ['../x', '/abs', 'a//b', './a', 'a\\b', '']) {
    const root = tmp();
    throwsSentence(() => sf.writeDirAtomic(join(root, 'a-b'), { [rel]: Buffer.from('x') }), /is not a plain relative path$/);
    assert.deepEqual(listing(root), []);
  }
});

test('writeDirAtomic leaves nothing after a failure at each step', () => {
  const saved = { ...sf.seams };
  const boom = () => {
    throw new Error('injected');
  };
  for (const step of ['write', 'fsync', 'rename']) {
    const root = join(tmp(), 'skills');
    try {
      if (step === 'write') {
        let calls = 0;
        sf.seams.write = (file, data) => {
          calls += 1;
          saved.write(file, data);
          if (calls === 2) throw new Error('injected');
        };
      } else if (step === 'fsync') sf.seams.fsync = boom;
      else sf.seams.rename = boom;
      assert.throws(() => sf.writeDirAtomic(join(root, 'a-b'), FILES), /injected/);
      assert.deepEqual(listing(root), [], step);
    } finally {
      Object.assign(sf.seams, saved);
    }
  }
});

// ------------------------------------------------- replace, history, undo

test('undo after install removes', () => {
  const root = tmp();
  const target = join(root, 'skills', 'a-b');
  const backups = join(root, 'backups');
  sf.backupAbsent(backups, 'a-b', NOW);
  sf.writeDirAtomic(target, FILES);
  assert.equal(sf.undo(backups, 'a-b', target), 'removed a-b; it did not exist before 20261027T120000.000Z');
  assert.equal(existsSync(target), false);
  assert.deepEqual(listing(join(root, 'skills')), []);
  assert.deepEqual(listing(backups), ['a-b']);
  throwsSentence(() => sf.undo(backups, 'a-b', target), 'no backup of a-b to undo');
});

test('undo after replace restores the previous bytes', () => {
  const root = tmp();
  const target = join(root, 'skills', 'a-b');
  const backups = join(root, 'backups');
  sf.writeDirAtomic(target, FILES);
  const b = sf.replaceDirAtomic(target, { 'SKILL.md': Buffer.from('new\n') }, backups, NOW);
  assert.equal(b, join(backups, 'a-b', '20261027T120000.000Z'));
  assert.deepEqual(listing(target), ['SKILL.md']);
  assert.equal(sf.undo(backups, 'a-b', target), 'restored a-b from its backup of 20261027T120000.000Z');
  assert.deepEqual(readFileSync(join(target, 'SKILL.md')), FILES['SKILL.md']);
  assert.deepEqual(listing(join(root, 'skills')), ['a-b', 'a-b/SKILL.md', 'a-b/references', 'a-b/references/evidence.md']);
});

test('two backups in one millisecond are both kept, newest first', () => {
  const root = tmp();
  const target = join(root, 'a-b');
  const backups = join(root, 'backups');
  sf.writeDirAtomic(target, { 'SKILL.md': Buffer.from('1') });
  sf.replaceDirAtomic(target, { 'SKILL.md': Buffer.from('2') }, backups, NOW);
  const second = sf.replaceDirAtomic(target, { 'SKILL.md': Buffer.from('3') }, backups, NOW);
  assert.ok(second.endsWith('20261027T120000.000Z-2'));
  assert.ok(sf.undo(backups, 'a-b', target).endsWith('20261027T120000.000Z-2'));
  assert.equal(readFileSync(join(target, 'SKILL.md'), 'utf8'), '2');
  sf.undo(backups, 'a-b', target);
  assert.equal(readFileSync(join(target, 'SKILL.md'), 'utf8'), '1');
});

test('a replace failure keeps the old dir and drops the backup', () => {
  const root = tmp();
  const target = join(root, 'a-b');
  const backups = join(root, 'backups');
  sf.writeDirAtomic(target, FILES);
  const saved = { ...sf.seams };
  let n = 0;
  sf.seams.rename = (src, dst) => {
    n += 1;
    if (n === 3) throw new Error('injected');
    saved.rename(src, dst);
  };
  try {
    assert.throws(() => sf.replaceDirAtomic(target, { 'SKILL.md': Buffer.from('new') }, backups, NOW), /injected/);
  } finally {
    Object.assign(sf.seams, saved);
  }
  assert.deepEqual(readFileSync(join(target, 'SKILL.md')), FILES['SKILL.md']);
  assert.deepEqual(listing(root), ['a-b', 'a-b/SKILL.md', 'a-b/references', 'a-b/references/evidence.md', 'backups', 'backups/a-b']);
});

test('replace refuses a missing skill', () => {
  const root = tmp();
  throwsSentence(() => sf.replaceDirAtomic(join(root, 'nope'), FILES, join(root, 'b'), NOW), /^no skill at /);
});

test('historyAdd keeps every version', () => {
  const root = tmp();
  const target = join(root, 'a-b');
  sf.writeDirAtomic(target, FILES);
  sf.historyAdd(target, 1);
  assert.deepEqual(readFileSync(join(target, 'references', 'history', 'v1.md')), FILES['SKILL.md']);
  throwsSentence(() => sf.historyAdd(target, 1), 'history already holds v1 of a-b');
  throwsSentence(() => sf.historyAdd(target, 0), 'version must be a whole number from 1, not 0');
});

test('backupStamp refuses a bad now', () => {
  assert.equal(sf.backupStamp('2026-01-02T03:04:05Z'), '20260102T030405.000Z');
  throwsSentence(() => sf.backupStamp('yesterday'), "not a timestamp: 'yesterday'");
});

// ------------------------------------------------------------------ paths, state

test('paths', () => {
  const h = tmp();
  assert.equal(sf.skillsRoot(h), join(h, '.bantamkit', 'skills'));
  assert.equal(sf.projectSkillsRoot(h), join(h, '.bantamkit', 'skills'));
  assert.equal(sf.backupRoot(h), join(h, '.bantamkit', 'skill-backups'));
  assert.equal(sf.statePath(h), join(h, '.bantamkit', 'skills-state.json'));
});

test('state round trip and refusals', () => {
  const h = tmp();
  assert.deepEqual(sf.readState(h), { version: 1, skills: {} });
  sf.writeState(h, { skills: { b: { n: 1 }, ไทย: {} }, version: 7 });
  assert.equal(
    readFileSync(sf.statePath(h), 'utf8'),
    '{\n  "skills": {\n    "b": {\n      "n": 1\n    },\n    "ไทย": {}\n  },\n  "version": 1\n}\n',
  );
  assert.deepEqual(sf.readState(h).skills.b, { n: 1 });
  assert.deepEqual(readdirSync(join(h, '.bantamkit')), ['skills-state.json']);
  const got = sf.updateState(h, (s) => {
    s.skills.c = {};
  });
  assert.deepEqual(Object.keys(got.skills).sort(), ['b', 'c', 'ไทย']);
  writeFileSync(sf.statePath(h), '{bad');
  throwsSentence(() => sf.readState(h), 'skills-state.json is not readable JSON');
  for (const body of ['{"version": 2, "skills": {}}', '{"version": 1.0, "skills": {}}', '{"version": true, "skills": {}}']) {
    writeFileSync(sf.statePath(h), body);
    throwsSentence(() => sf.readState(h), 'skills-state.json is not a version 1 skills state');
  }
});

test('repeated state writes replace previous contents', () => {
  const h = tmp();
  sf.writeState(h, { skills: { 'old-skill': { description: 'old'.repeat(100) } } });
  const expected = { version: 1, skills: { 'new-skill': {} } };
  sf.writeState(h, expected);
  assert.deepEqual(sf.readState(h), expected);
  assert.deepEqual(readFileSync(sf.statePath(h)), sf.stateBytes(expected));
  assert.deepEqual(readdirSync(join(h, '.bantamkit')), ['skills-state.json']);
});

for (const step of ['write', 'fsync', 'rename']) {
  test(`failed state update at ${step} preserves previous bytes`, () => {
    const h = tmp();
    sf.writeState(h, { skills: { 'old-skill': {} } });
    const previous = readFileSync(sf.statePath(h));
    const saved = { ...sf.seams };
    sf.seams[step] = (...args) => {
      if (step === 'write') saved.write(...args);
      throw new Error('injected state write failure');
    };
    try {
      assert.throws(() => sf.updateState(h, (state) => { state.skills.new = {}; }), /injected state write failure/);
    } finally {
      Object.assign(sf.seams, saved);
    }
    assert.deepEqual(readFileSync(sf.statePath(h)), previous);
    assert.deepEqual(readdirSync(join(h, '.bantamkit')), ['skills-state.json']);
    assert.deepEqual(sf.updateState(h, (state) => { state.skills.new = {}; }), {
      version: 1, skills: { 'old-skill': {}, new: {} },
    });
  });
}

// The real name is `<target>.<kind>-<pid>-<n>`: predictable, so pin it the way an attacker
// would predict it.
const withPlantedTemp = (fn) => {
  const saved = { ...sf.seams };
  sf.seams.temp = (target, kind) => `${target}.${kind}-planted`;
  try {
    return fn();
  } finally {
    Object.assign(sf.seams, saved);
  }
};

for (const plant of ['symlink', 'file']) {
  // #250: the temp was opened 'w' through a symlink, so a planted link overwrote its target
  // with the state bytes.
  test(`state write refuses a taken temp (${plant}) and leaves it alone`, (t) => {
    const root = tmp();
    const home = join(root, 'home');
    sf.writeState(home, { skills: { 'old-skill': {} } });
    const previous = readFileSync(sf.statePath(home));
    const victim = join(root, 'victim');
    writeFileSync(victim, 'KEEP');
    const planted = `${sf.statePath(home)}.tmp-planted`;
    if (plant === 'symlink') {
      try {
        symlinkSync(victim, planted);
      } catch {
        t.skip('this platform will not make a symlink here');
        return;
      }
    } else writeFileSync(planted, 'THEIRS');
    withPlantedTemp(() =>
      throwsSentence(
        () => sf.writeState(home, { skills: { injected: {} } }),
        `temp path ${planted} already exists; refusing to write through it`,
      ),
    );
    assert.equal(readFileSync(victim, 'utf8'), 'KEEP');
    assert.deepEqual(readFileSync(sf.statePath(home)), previous);
    if (plant === 'symlink') assert.equal(readlinkSync(planted), victim);
    else assert.equal(readFileSync(planted, 'utf8'), 'THEIRS');
    assert.ok(lstatSync(planted));
  });
}

test('a taken temp dir is refused, not removed', () => {
  const root = join(tmp(), 'backups');
  const taken = join(root, 'c-d', `${sf.backupStamp(NOW)}.tmp-planted`);
  mkdirSync(join(taken, 'theirs'), { recursive: true });
  withPlantedTemp(() => {
    throwsSentence(() => sf.backupAbsent(root, 'c-d', NOW), /already exists; refusing to write through it$/);
    assert.ok(statSync(join(taken, 'theirs')).isDirectory());
    throwsSentence(
      () => sf.writeDirAtomic(join(root, 'c-d', sf.backupStamp(NOW)), { 'SKILL.md': Buffer.from('x') }),
      /already exists; refusing to write through it$/,
    );
  });
  assert.deepEqual(readdirSync(join(root, 'c-d')), [`${sf.backupStamp(NOW)}.tmp-planted`]);
});

// An EMPTY dir is the one a bare rename onto the `.old-` name would replace (POSIX allows it).
const plantOld = (t, at, plant, victim) => {
  if (plant === 'dir') {
    mkdirSync(at);
    return true;
  }
  try {
    symlinkSync(victim, at);
    return true;
  } catch {
    t.skip('this platform will not make a symlink here');
    return false;
  }
};
const plantedOldLeft = (at, plant, victim) => {
  if (plant === 'dir') {
    assert.ok(lstatSync(at).isDirectory());
    assert.deepEqual(readdirSync(at), []);
  } else assert.equal(readlinkSync(at), victim);
};

for (const plant of ['dir', 'symlink']) {
  // #250: the live skill was renamed onto the bare `.old-` name, which on POSIX replaces an
  // empty dir planted there; the rmtree after the swap then removed what took its place.
  test(`replace refuses a taken old name (${plant}) and leaves it alone`, (t) => {
    const root = tmp();
    const target = join(root, 'skills', 'a-b');
    sf.writeDirAtomic(target, { 'SKILL.md': Buffer.from('live\n') });
    const victim = join(root, 'victim');
    writeFileSync(victim, 'KEEP');
    const at = `${target}.old-planted`;
    if (!plantOld(t, at, plant, victim)) return;
    withPlantedTemp(() =>
      throwsSentence(
        () => sf.replaceDirAtomic(target, { 'SKILL.md': Buffer.from('new\n') }, join(root, 'backups'), NOW),
        `temp path ${at} already exists; refusing to write through it`,
      ),
    );
    assert.equal(readFileSync(join(target, 'SKILL.md'), 'utf8'), 'live\n');
    assert.equal(readFileSync(victim, 'utf8'), 'KEEP');
    plantedOldLeft(at, plant, victim);
    assert.deepEqual(readdirSync(join(root, 'skills')).sort(), ['a-b', 'a-b.old-planted']);
    assert.deepEqual(readdirSync(join(root, 'backups', 'a-b')), []);
  });

  test(`undo of an install refuses a taken old name (${plant})`, (t) => {
    const root = tmp();
    const backups = join(root, 'backups');
    const target = join(root, 'skills', 'c-d');
    sf.backupAbsent(backups, 'c-d', NOW);
    sf.writeDirAtomic(target, { 'SKILL.md': Buffer.from('c\n') });
    const victim = join(root, 'victim');
    writeFileSync(victim, 'KEEP');
    const at = `${target}.old-planted`;
    if (!plantOld(t, at, plant, victim)) return;
    withPlantedTemp(() => throwsSentence(() => sf.undo(backups, 'c-d', target), /already exists; refusing to write through it$/));
    assert.equal(readFileSync(join(target, 'SKILL.md'), 'utf8'), 'c\n');
    plantedOldLeft(at, plant, victim);
    assert.equal(readdirSync(join(backups, 'c-d')).length, 1); // the backup is not spent
  });
}

test('a swap leaves no old dir behind', () => {
  const root = tmp();
  const target = join(root, 'skills', 'a-b');
  sf.writeDirAtomic(target, { 'SKILL.md': Buffer.from('v1\n') });
  sf.replaceDirAtomic(target, { 'SKILL.md': Buffer.from('v2\n') }, join(root, 'backups'), NOW);
  assert.deepEqual(readdirSync(join(root, 'skills')), ['a-b']);
  assert.equal(readFileSync(join(target, 'SKILL.md'), 'utf8'), 'v2\n');
});

test('parse refuses what the reader refuses, as the reference now does (job73 C8)', () => {
  for (const line of ['metadata: {}', 'metadata: {k: 1}', 'metadata: {bantamkit-k: "v"}', 'metadata:\n  k: {}',
    'metadata:\n  k: [a, {b: c}]', 'description: {x: 1}', 'description: &a d', 'description: !!str d']) {
    const text = `---\nname: a-b\n${line}\n---\n\n## Steps\n\n1. x\n`;
    throwsSentence(() => sf.parseSkill(text), 'SKILL.md frontmatter is not a readable mapping');
    assert.equal(sf.isEdited(text), true);
  }
  const doc = sf.parseSkill("---\nname: a-b\ndescription: fish & chips!\nmetadata:\n  k: a {b} c\n  j: '{}'\n---\n");
  assert.equal(doc.description, 'fish & chips!');
  assert.deepEqual(doc.metadata, { k: 'a {b} c', j: '{}' });
});
