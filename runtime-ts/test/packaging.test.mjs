/**
 * RB-P85, one build system over. The asset pack is asserted in the ARTIFACT npm would
 * publish, never in the source tree.
 *
 * The Python half of this bar (`runtime-py/tests/test_packaging.py`) exists because
 * `build_sdist` once succeeded and shipped a tarball whose only `assets` entry was the
 * module that READS the pack. Asserting that `<repo>/assets/` exists on disk would have
 * passed on the day that defect was introduced and every day after. So would asserting
 * that `package.json` contains the string `"assets"`. Both are restatements of the
 * checkout, not bars.
 *
 * `npm pack --dry-run --json` reports exactly what npm would put in the tarball, without
 * writing one. Measured on npm 11.6.2: `files[].path` is package-relative and NOT
 * prefixed `package/`, and `prepack` DOES run under `--dry-run`, so the vendoring step
 * is inside what this test observes.
 *
 * The property has two halves, one node each:
 *   * the artifact carries the pack, byte for byte and file for file;
 *   * a build that CANNOT locate the pack fails instead of succeeding short.
 */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoPack = join(dirname(packageRoot), 'assets');

/**
 * The size of the pack, measured: 84 files / 213,773 bytes at 8634632, where U11 added
 * `assets/tools/bantamkit_status.json` (83 files / 212,480 bytes before it). Pinned as a
 * NUMBER and not derived, because the number is the thing `build_identity` hashes — a
 * pack that grows or shrinks moves `assets_digest` and therefore `build_id`, and that
 * must be a deliberate edit here rather than a silent one.
 */
const EXPECTED_ASSET_FILES = 84;

function walk(dir) {
  const out = new Map();
  for (const entry of readdirSync(dir, { withFileTypes: true, recursive: true })) {
    if (!entry.isFile()) continue;
    const abs = join(entry.parentPath ?? entry.path, entry.name);
    out.set(relative(dir, abs).split(sep).join('/'), abs);
  }
  return out;
}

function sha256(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

/**
 * `npm` on Windows is `npm.cmd`, and it takes BOTH of these to run. MEASURED across two
 * runs: `execFileSync('npm', ...)` is `spawnSync npm ENOENT` (there is no extensionless
 * `npm`), and naming the file gets `spawnSync npm.cmd EINVAL` — the CVE-2024-27980
 * mitigation, which refuses to spawn a `.cmd` or `.bat` unless `shell` is set. So all four
 * tests in this file failed on both Windows cells and the whole RB-P85 packaging gate had
 * never once run on the platform half of this matrix. The argv here is three fixed flags
 * with no metacharacter in them, which is what makes handing it to cmd.exe safe.
 */
const NPM = process.platform === 'win32' ? 'npm.cmd' : 'npm';

function packListing(cwd = packageRoot) {
  const stdout = execFileSync(NPM, ['pack', '--dry-run', '--json'], {
    cwd,
    encoding: 'utf8',
    shell: process.platform === 'win32',
    stdio: ['ignore', 'pipe', 'ignore'],
  });
  return JSON.parse(stdout)[0].files.map((f) => f.path);
}

test('the tarball npm would publish carries the whole asset pack', () => {
  const paths = packListing();
  const packed = paths.filter((p) => p.startsWith('assets/')).sort();
  const source = walk(repoPack);

  assert.deepEqual(
    packed,
    [...source.keys()].sort().map((p) => `assets/${p}`),
    'the packed pack and the repository pack are not the same set of files',
  );
  assert.equal(packed.length, EXPECTED_ASSET_FILES);
});

test('every packed asset is byte-identical to the repository pack', () => {
  packListing(); // prepack vendors runtime-ts/assets as a side effect
  const vendored = walk(join(packageRoot, 'assets'));
  const source = walk(repoPack);
  let bytes = 0;
  for (const [rel, abs] of source) {
    const mirror = vendored.get(rel);
    assert.ok(mirror, `vendored copy is missing ${rel}`);
    assert.equal(sha256(mirror), sha256(abs), `vendored copy of ${rel} differs`);
    bytes += readFileSync(abs).length;
  }
  assert.equal(bytes, 213773);
});

test('the tarball carries the executable entry point and its module', () => {
  const paths = packListing();
  for (const wanted of ['dist/cli.js', 'dist/assets.js', 'dist/errors.js', 'package.json']) {
    assert.ok(paths.includes(wanted), `tarball is missing ${wanted}`);
  }
});

test('the five .gitkeep placeholders survive packing', () => {
  // npm filters a documented list of dotfiles out of every tarball, and these five are
  // exactly the entries a filter would take. They are not decoration: `build_identity`
  // rglobs the whole tree, so a dropped `.gitkeep` moves `assets_digest` and `build_id`
  // while every functional asset still loads — a failure with no symptom at the surface.
  const packed = packListing().filter((p) => p.endsWith('/.gitkeep')).sort();
  assert.deepEqual(packed, [
    'assets/evals/fixtures/.gitkeep',
    'assets/evals/tasks/.gitkeep',
    'assets/rubrics/.gitkeep',
    'assets/skills/.gitkeep',
    'assets/tools/.gitkeep',
  ]);
});

test('a build that cannot locate the asset pack fails instead of succeeding short', () => {
  // A package directory with no `../assets` above it and no vendored `assets/` inside.
  // `realpathSync`: `os.tmpdir()` is not canonical — a `/var` symlink on macOS, the 8.3
  // short name on Windows CI. See the note in test/store.test.mjs.
  const tmp = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-nopack-')));
  const pkg = join(tmp, 'runtime-ts');
  // `mkdirSync`, not `execFileSync('mkdir', ['-p'])`: there is no `mkdir.exe` on Windows,
  // and this line only ever resolved there because the runner image happens to put
  // Git-for-Windows' `usr/bin` on PATH. A test that depends on that is a test that fails
  // on somebody's laptop for a reason with nothing to do with what it measures.
  mkdirSync(join(pkg, 'scripts'), { recursive: true });
  writeFileSync(
    join(pkg, 'scripts', 'sync-assets.mjs'),
    readFileSync(join(packageRoot, 'scripts', 'sync-assets.mjs')),
  );
  const run = spawnSync(process.execPath, [join(pkg, 'scripts', 'sync-assets.mjs')], {
    encoding: 'utf8',
  });
  assert.notEqual(run.status, 0, 'sync-assets exited 0 with no pack to vendor');
  assert.match(run.stderr, /asset pack not found or empty; refusing to build an artifact/);
});

/**
 * U9. `package.json` has declared `"license": "MIT"` since it existed, and there was no
 * LICENSE file anywhere in the repository to back it. There is one now, at the
 * REPOSITORY root — and npm's documented rule that it always includes `LICENSE`
 * regardless of `files` does not reach it.
 *
 * MEASURED with the file at the repo root and no vendoring step: `npm pack --dry-run
 * --json` listed 129 files, and the only two outside `dist/` and `assets/` were
 * `README.md` and `package.json`. npm's rule is about the PACKAGE root, exactly like
 * hatchling's inability to see `../assets`. `scripts/sync-assets.mjs` vendors it in the
 * same pass and by the same two rules, which takes the listing to 130.
 *
 * This node reads the pack listing rather than the file on disk, because the vendored
 * copy is gitignored and a test that asserted it exists would be asserting the last
 * `npm pack` ran, not that the next one ships it.
 */
test('the tarball carries the licence text package.json declares', () => {
  const paths = packListing();
  assert.ok(
    paths.includes('LICENSE'),
    `package.json declares "license": "${JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8')).license}" ` +
      'but the tarball carries no LICENSE; a declaration with no text grants nothing',
  );
  assert.equal(
    sha256(join(packageRoot, 'LICENSE')),
    sha256(join(dirname(packageRoot), 'LICENSE')),
    'the vendored LICENSE is not byte-identical to the repository-root one',
  );
});

/**
 * U9. The Node half of the version-agreement gate. Its Python twin is
 * `runtime-py/tests/test_version_agreement.py`, and both exist on purpose: whoever bumps
 * `package.json` runs `npm test`, whoever bumps `__version__` runs pytest, and a gate
 * that lives only in the other side's suite is a gate the person making the mistake
 * never runs.
 *
 * `__version__` is authoritative and `package.json` follows — the ruling is in
 * `docs/release-npm.md` under "Version agreement". Nothing compared these two strings
 * before this node; the only cross-reference in the repository was prose, and that prose
 * named a symbol (`runtime_py.__version__`) that does not exist.
 */
test('the two version declarations agree', () => {
  const nodeVersion = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8')).version;
  const pySource = readFileSync(
    join(dirname(packageRoot), 'runtime-py', 'src', 'bantamkit', '__init__.py'),
    'utf8',
  );
  const match = /^__version__ = "([^"]+)"$/m.exec(pySource);
  assert.ok(match, 'no `__version__ = "..."` line in runtime-py/src/bantamkit/__init__.py');
  assert.equal(
    nodeVersion,
    match[1],
    'the two runtimes declare different versions, so a client reading one cannot tell ' +
      'which half answered it. `__version__` is authoritative — see docs/release-npm.md.',
  );
});
