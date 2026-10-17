// job66 J66-6: one-shot flags refused together (#139), a missing assets root counted as zero
// files (#140), and `--k`/`--index-budget` parsed exactly as CPython's `int()` (#174).
// Each literal here is the reference's measured answer, so a regression that landed in BOTH
// runtimes (which the `cli` conformance differential cannot see) still reddens this file.
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmodSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { packFileCount } from '../dist/mcp/identity.js';
import { pyIntStrict } from '../dist/pyargparse.js';

const OWN_CLI = join(dirname(dirname(fileURLToPath(import.meta.url))), 'dist', 'cli.js');

function withHome(fn) {
  const home = mkdtempSync(join(tmpdir(), 'bk-oneshot-'));
  try {
    return fn(home);
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
}

function runCli(argv, home, env = {}) {
  const base = { ...process.env, HOME: home, USERPROFILE: home };
  delete base.BANTAMKIT_ASSETS;
  delete base.COLUMNS;
  return spawnSync(process.execPath, [OWN_CLI, ...argv], { input: '', cwd: home, encoding: 'utf8', env: { ...base, ...env } });
}

const STACKED = [
  [['--install', 'cursor', '--assets-root'], '--install', '--assets-root'],
  [['--install-hooks', '--remove-hooks', '--yes'], '--remove-hooks', '--install-hooks'],
  [['--mcp-report', '--install', 'cursor'], '--install', '--mcp-report'],
  [['--update', '--hook'], '--update', '--hook'],
  [['--statusline', '--mcp-report', '--assets-root'], '--mcp-report', '--assets-root'],
];

for (const [argv, second, first] of STACKED) {
  test(`#139: ${argv.join(' ')} is a usage error and writes nothing`, () =>
    withHome((home) => {
      const r = runCli(argv, home);
      assert.equal(r.status, 2, r.stderr);
      assert.equal(r.stdout, '');
      assert.ok(r.stderr.startsWith('usage: bantamkit-mcp '), r.stderr);
      assert.ok(r.stderr.endsWith(`bantamkit-mcp: error: argument ${second}: not allowed with argument ${first}\n`), r.stderr);
      assert.deepEqual(readdirSync(home), []);
    }));
}

const MODIFIERS = [
  [['--hook', '--store', 'x'], '--store is not meaningful with --hook'],
  [['--hook', '--start', 'x'], '--start is not meaningful with --hook'],
  [['--hook', '--yes'], '--yes is only meaningful with --install-hooks or --remove-hooks'],
  [['--hook', '--force'], '--force is only meaningful with --install'],
  [['--statusline', '--force'], '--force is only meaningful with --install'],
  [['--install-hooks', '--force'], '--force is only meaningful with --install'],
  [['--install', 'cursor', '--yes'], '--yes is only meaningful with --install-hooks or --remove-hooks'],
];

for (const [argv, sentence] of MODIFIERS) {
  test(`#139: ${argv.join(' ')} is refused before anything acts`, () =>
    withHome((home) => {
      const r = runCli(argv, home);
      assert.deepEqual([r.status, r.stdout, r.stderr], [1, '', `${sentence}\n`]);
      assert.deepEqual(readdirSync(home), []);
    }));
}

test('#139: the one-shot rule leaves the usage line without a group', () =>
  withHome((home) => {
    const usage = runCli(['-h'], home).stdout.split('\n\n')[0];
    assert.equal(usage.split('|').length - 1, 1, usage);
  }));

test('#140: --assets-root at a missing BANTAMKIT_ASSETS prints the path and 0 files, exit 0', () =>
  withHome((home) => {
    const missing = join(home, 'nope');
    const r = runCli(['--assets-root'], home, { BANTAMKIT_ASSETS: missing });
    assert.deepEqual([r.status, r.stdout, r.stderr], [0, `${missing}\n0 files\n`, '']);
  }));

test('#140: packFileCount mirrors rglob — a missing root, a file root and an unlistable directory count nothing', () =>
  withHome((home) => {
    writeFileSync(join(home, 'file'), 'x');
    mkdirSync(join(home, 'pack', 'locked'), { recursive: true });
    writeFileSync(join(home, 'pack', 'a'), 'a');
    writeFileSync(join(home, 'pack', 'locked', 'b'), 'b');
    assert.equal(packFileCount(join(home, 'nope')), 0);
    assert.equal(packFileCount(join(home, 'file')), 0);
    if (process.platform !== 'win32' && process.getuid?.() !== 0) {
      chmodSync(join(home, 'pack', 'locked'), 0o000);
      try {
        assert.equal(packFileCount(join(home, 'pack')), 1);
      } finally {
        chmodSync(join(home, 'pack', 'locked'), 0o755);
      }
    }
  }));

// CPython 3.12's answers, measured with `int(text)`.
const ACCEPTED = [['٣', 3], [' ٣ ', 3], ['٣_٣', 33], ['1٣', 13], ['𝟑', 3], ['𝟘𝟙', 1], [' 7　', 7], ['\x853', 3], ['١٢', 12], ['๓', 3], ['-0', 0], ['+٣', 3], ['007', 7], ['1'.repeat(4300).slice(0, 15), 111111111111111]];
const REFUSED = ['﻿3', '3\x1c', '_1', '1_', '1__0', '+_1', '²', 'Ⅳ', '1 2', '', '  ', '1.0', '0x10', '1'.repeat(4301)];

test('#174: pyIntStrict accepts what CPython int() accepts', () => {
  for (const [text, value] of ACCEPTED) assert.equal(Object.is(pyIntStrict(text), value), true, JSON.stringify(text));
  assert.doesNotThrow(() => pyIntStrict('1'.repeat(4300)));
});

test('#174: pyIntStrict refuses what CPython int() refuses', () => {
  for (const text of REFUSED) assert.throws(() => pyIntStrict(text), TypeError, JSON.stringify(text));
});

test('#174: --k with an Arabic-Indic digit is parsed, not refused', () =>
  withHome((home) => {
    const r = runCli(['--k', '٣', '--assets-root'], home);
    assert.equal(r.status, 0, r.stderr);
  }));
