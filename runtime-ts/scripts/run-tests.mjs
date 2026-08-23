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

/**
 * Under CI, pin the reporter. `node --test`'s DEFAULT reporter is NOT stable across the
 * versions `engines` claims — MEASURED on one unchanged file, `test/assets.test.mjs`:
 * v18.20.8, v20.20.2 and v22.22.3 print TAP (`# pass 10`), v25.2.1 prints spec
 * (`ℹ pass 10`). The CI job's whole instruction is "confirm from the log, not from the
 * colour", and a summary whose SHAPE moves with the interpreter is a log nobody can write
 * that instruction against: a grep for `# pass` finds nothing on a newer Node and reads
 * exactly like a step that never ran. Interactively the default is left alone — there the
 * reader is a human, not a grep.
 */
const reporter = process.env.CI ? ['--test-reporter=tap'] : [];
process.exit(
  spawnSync(process.execPath, ['--test', ...reporter, ...files], { stdio: 'inherit' }).status ?? 1,
);
