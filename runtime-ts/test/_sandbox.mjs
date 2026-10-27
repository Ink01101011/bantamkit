/**
 * The per-file sandbox (#204, J69-9 F5). Every `*.test.mjs` imports this FIRST.
 *
 * `npm test` goes through `scripts/run-tests.mjs`, which hands every file one scratch
 * `BANTAMKIT_INDEX_DIR` and `BANTAMKIT_RETENTION=off` and marks the run with
 * `SANDBOX_ENV`. A file run directly — `node --test runtime-ts/test/<file>` — gets none of
 * that: the operator's HOME, no index override, Retention armed. An in-process store then
 * writes the real `~/.bantamkit/index/` and `cold/`, and a spawned server or SessionStart
 * could start the detached Retention child against real data.
 *
 * So when the marker is absent this module, before any other import of the test file is
 * evaluated (ES modules evaluate their imports in source order), points HOME and USERPROFILE
 * (Windows reads the second, not the first) at a fresh scratch home, the index at a scratch
 * dir, and turns Retention and the daily skill audit off — every value OVERRIDDEN, not defaulted, because an operator
 * shell may carry any of them pointing at real data. Under the runner it does nothing, so
 * `npm test` behaves exactly as before. The scratch is removed when the process exits.
 */
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

/** Set by `scripts/run-tests.mjs`; its presence means the runner already sandboxed this run. */
export const SANDBOX_ENV = 'BANTAMKIT_TEST_SANDBOX';

if (!process.env[SANDBOX_ENV]) {
  const scratch = mkdtempSync(join(tmpdir(), 'bk-test-sandbox-'));
  const home = join(scratch, 'home');
  const index = join(scratch, 'index');
  mkdirSync(home);
  process.env.HOME = home;
  process.env.USERPROFILE = home;
  process.env.BANTAMKIT_INDEX_DIR = index;
  process.env.BANTAMKIT_RETENTION = 'off';
  process.env.BANTAMKIT_SKILL_AUDIT = 'off'; // #205 A3: the audit wakes the same child
  process.env[SANDBOX_ENV] = scratch;
  process.on('exit', () => rmSync(scratch, { recursive: true, force: true }));
}
