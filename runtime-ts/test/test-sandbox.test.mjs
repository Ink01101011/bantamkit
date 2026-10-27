/**
 * The per-file sandbox guard (#204, J69-9 F5): `node --test runtime-ts/test/<file>` run
 * directly — without `scripts/run-tests.mjs` — must not reach the operator's HOME, hot or cold
 * index, or arm Retention. `test/_sandbox.mjs` does that; these nodes pin that every test file
 * loads it first and that it moves what it must, and only when the runner has not.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const GUARD = pathToFileURL(path.join(HERE, '_sandbox.mjs')).href;
const KEYS = ['HOME', 'USERPROFILE', 'BANTAMKIT_INDEX_DIR', 'BANTAMKIT_RETENTION', 'BANTAMKIT_SKILL_AUDIT', 'BANTAMKIT_TEST_SANDBOX'];

/** The env a child that imported the guard sees, given `env` (no inherited marker). */
function guarded(env) {
  const base = { ...process.env };
  for (const k of KEYS) delete base[k];
  const script =
    `await import(${JSON.stringify(GUARD)});` +
    `const os = await import('node:os');` +
    `console.log(JSON.stringify({ homedir: os.homedir(), ` +
    KEYS.map((k) => `${JSON.stringify(k)}: process.env[${JSON.stringify(k)}] ?? null`).join(', ') +
    ` }));`;
  const done = spawnSync(process.execPath, ['--input-type=module', '-e', script], {
    env: { ...base, ...env },
    encoding: 'utf8',
  });
  assert.equal(done.status, 0, done.stderr);
  return JSON.parse(done.stdout);
}

test('every test file imports the sandbox guard before anything else', () => {
  const files = fs.readdirSync(HERE).filter((f) => f.endsWith('.test.mjs')).sort();
  assert.ok(files.length > 50, `only ${files.length} test files found`);
  const late = files.filter((f) => {
    const first = fs.readFileSync(path.join(HERE, f), 'utf8').split('\n').find((l) => /^import\b/.test(l));
    return first !== "import './_sandbox.mjs';";
  });
  assert.deepEqual(late, []);
});

test('run directly, the guard moves HOME, USERPROFILE and the index off the operator and turns Retention off', () => {
  const real = fs.mkdtempSync(path.join(os.tmpdir(), 'sandbox-real-'));
  try {
    const seen = guarded({
      HOME: real,
      USERPROFILE: real,
      BANTAMKIT_INDEX_DIR: path.join(real, '.bantamkit', 'index'),
      BANTAMKIT_RETENTION: 'on',
      BANTAMKIT_SKILL_AUDIT: 'on',
    });
    assert.notEqual(seen.homedir, real);
    assert.ok(!seen.HOME.startsWith(real), seen.HOME);
    assert.equal(seen.USERPROFILE, seen.HOME);
    assert.equal(seen.homedir, seen.HOME);
    assert.ok(seen.BANTAMKIT_TEST_SANDBOX, 'no marker set');
    assert.ok(seen.HOME.startsWith(seen.BANTAMKIT_TEST_SANDBOX), seen.HOME);
    assert.ok(seen.BANTAMKIT_INDEX_DIR.startsWith(seen.BANTAMKIT_TEST_SANDBOX), seen.BANTAMKIT_INDEX_DIR);
    assert.equal(seen.BANTAMKIT_RETENTION, 'off');
    assert.equal(seen.BANTAMKIT_SKILL_AUDIT, 'off');
    // The scratch is gone once the child exits.
    assert.equal(fs.existsSync(seen.BANTAMKIT_TEST_SANDBOX), false);
    assert.deepEqual(fs.readdirSync(real), []);
  } finally {
    fs.rmSync(real, { recursive: true, force: true });
  }
});

test('under the runner (marker set) the guard leaves the environment exactly as given', () => {
  const env = {
    HOME: '/runner/home',
    USERPROFILE: '/runner/profile',
    BANTAMKIT_INDEX_DIR: '/runner/index',
    BANTAMKIT_RETENTION: 'off',
    BANTAMKIT_SKILL_AUDIT: 'off',
    BANTAMKIT_TEST_SANDBOX: '/runner/index',
  };
  const seen = guarded(env);
  for (const [k, v] of Object.entries(env)) assert.equal(seen[k], v, k);
});
