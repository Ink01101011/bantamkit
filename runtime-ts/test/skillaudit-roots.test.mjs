/**
 * `auditRoots` / `scanRoots`: several LABELLED roots audited as one catalogue (#205).
 * Mirrors `runtime-py/tests/test_skillaudit_roots.py` test for test; the byte-for-byte
 * differential is the `audit_roots` block of `tools/conformance/suites/skillaudit.mjs`.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { after, test } from 'node:test';

import { audit, auditRoots, scanRoots, SkillAuditError } from '../dist/skillaudit.js';

const scratch = [];
after(() => {
  for (const dir of scratch) rmSync(dir, { recursive: true, force: true });
});

function tmp() {
  const dir = mkdtempSync(join(tmpdir(), 'skillaudit-roots-'));
  scratch.push(dir);
  return dir;
}

function skill(base, rel, description) {
  const p = join(base, rel, 'SKILL.md');
  mkdirSync(dirname(p), { recursive: true });
  const name = rel.split('/').pop();
  writeFileSync(p, `---\nname: ${name}\ndescription: ${description}\n---\nbody\n`, 'utf8');
}

function bed() {
  const base = tmp();
  const cache = join(base, 'cache');
  const user = join(base, 'user');
  skill(cache, 'mk/alpha/1.0.0/skills/a1', 'Use when you "deploy the thing" now.');
  skill(user, 'solo', 'Also "deploy the thing" here.');
  return { cache, user };
}

test('a phrase shared across two roots is found', () => {
  const { cache, user } = bed();
  const doc = auditRoots(
    [
      { label: 'plugins', path: cache },
      { label: 'user', path: user },
    ],
    { enabled: ['alpha@mk'] },
  ).asDict();
  assert.deepEqual(doc.roots, [cache, user]);
  assert.equal(doc.skills, 2);
  assert.deepEqual(doc.findings[0], {
    kind: 'shared-trigger-phrase',
    severity: 'high',
    skills: ['alpha:a1', 'solo'],
    detail: 'deploy the thing',
  });
});

test('relpaths carry the label', () => {
  const { cache, user } = bed();
  const found = scanRoots(
    [
      { label: 'plugins', path: cache },
      { label: 'user', path: user },
    ],
    [],
  );
  assert.deepEqual(
    found.map((s) => s.relpath),
    ['plugins/mk/alpha/1.0.0/skills/a1/SKILL.md', 'user/solo/SKILL.md'],
  );
  assert.deepEqual(
    found.map((s) => s.omitted),
    ['plugin-not-enabled', null],
  );
});

test('same bare name in two roots is a duplicate and the later root wins', () => {
  const base = tmp();
  const a = join(base, 'a');
  const b = join(base, 'b');
  skill(a, 'solo', 'first');
  skill(b, 'solo', 'second');
  const doc = auditRoots([
    { label: 'project', path: a },
    { label: 'user', path: b },
  ]).asDict();
  assert.equal(doc.skills, 1);
  assert.equal(doc.catalogue_bytes, 'second'.length);
  assert.deepEqual(doc.omissions, [
    { subject: 'duplicate-skill', count: 1, size: 5, what: 'project/solo/SKILL.md' },
  ]);
});

test('plugin skill and user skill of one name are both counted (Amendment A1)', () => {
  const base = tmp();
  const cache = join(base, 'cache');
  const user = join(base, 'user');
  skill(cache, 'mk/alpha/1.0.0/skills/solo', 'plugin copy');
  skill(user, 'solo', 'personal copy');
  const doc = auditRoots(
    [
      { label: 'plugins', path: cache },
      { label: 'user', path: user },
    ],
    { enabled: ['alpha@mk'] },
  ).asDict();
  assert.equal(doc.skills, 2);
  assert.equal(doc.catalogue_bytes, 'plugin copy'.length + 'personal copy'.length);
  assert.deepEqual(doc.omissions, []);
});

test('one root answers the same bytes as audit', () => {
  const { cache } = bed();
  const one = audit(cache, { enabled: ['alpha@mk'], usage: new Map() });
  const many = auditRoots([{ label: 'x', path: cache }], { enabled: ['alpha@mk'], usage: new Map() });
  assert.deepEqual(JSON.parse(one.asJson()).findings, JSON.parse(many.asJson()).findings);
  assert.equal(one.skills, many.skills);
  assert.equal(one.catalogueBytes, many.catalogueBytes);
});

for (const [roots, message] of [
  [[], 'roots must not be empty; name at least one directory of skills'],
  [[{ label: '', path: 'x' }], "root label '' must be unique, non-empty and hold no '/'"],
  [[{ label: 'a/b', path: 'x' }], "root label 'a/b' must be unique, non-empty and hold no '/'"],
]) {
  test(`refusal: ${message}`, () => {
    assert.throws(
      () => auditRoots(roots),
      (err) => err instanceof SkillAuditError && err.message === message,
    );
  });
}

test('a repeated label is refused', () => {
  const base = tmp();
  assert.throws(
    () =>
      auditRoots([
        { label: 'a', path: base },
        { label: 'a', path: base },
      ]),
    (err) => err instanceof SkillAuditError && err.message === "root label 'a' must be unique, non-empty and hold no '/'",
  );
});

test('check is refused before roots, and a root with audit sentence', () => {
  const base = tmp();
  assert.throws(
    () => auditRoots([], { check: 'nope' }),
    (err) => err instanceof SkillAuditError && err.message.startsWith("unknown check 'nope'"),
  );
  const missing = join(base, 'missing');
  assert.throws(
    () =>
      auditRoots([
        { label: 'a', path: base },
        { label: 'b', path: missing },
      ]),
    (err) => err instanceof SkillAuditError && err.message === `no such directory: ${missing}`,
  );
});
