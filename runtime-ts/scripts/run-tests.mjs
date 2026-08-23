/**
 * Thin wrapper over `node --test` so that `npm test -- <substring>` selects test files.
 *
 * `node --test` takes positional paths, not name filters, so the bare npm form
 * (`npm test -- packaging`) would otherwise hand it a path that does not exist. This is
 * eleven lines of argv handling, not a test framework: the runner, the assertions and
 * the reporter are all Node's own.
 */
import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const testDir = join(dirname(dirname(fileURLToPath(import.meta.url))), 'test');
const filters = process.argv.slice(2);
const files = readdirSync(testDir)
  .filter((f) => f.endsWith('.test.mjs'))
  .filter((f) => filters.length === 0 || filters.some((s) => f.includes(s)))
  .sort()
  .map((f) => join(testDir, f));

if (files.length === 0) {
  console.error(`run-tests: no test file matched ${JSON.stringify(filters)}`);
  process.exit(1);
}
process.exit(spawnSync(process.execPath, ['--test', ...files], { stdio: 'inherit' }).status ?? 1);
