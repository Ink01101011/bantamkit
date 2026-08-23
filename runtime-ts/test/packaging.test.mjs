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
import { mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoPack = join(dirname(packageRoot), 'assets');

/**
 * The size of the pack, measured: 83 files / 212,480 bytes at d8ee85f. Pinned as a
 * NUMBER and not derived, because the number is the thing `build_identity` hashes — a
 * pack that grows or shrinks moves `assets_digest` and therefore `build_id`, and that
 * must be a deliberate edit here rather than a silent one.
 */
const EXPECTED_ASSET_FILES = 83;

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

function packListing(cwd = packageRoot) {
  const stdout = execFileSync('npm', ['pack', '--dry-run', '--json'], {
    cwd,
    encoding: 'utf8',
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
  assert.equal(bytes, 212480);
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
  const tmp = mkdtempSync(join(tmpdir(), 'bk-nopack-'));
  const pkg = join(tmp, 'runtime-ts');
  execFileSync('mkdir', ['-p', join(pkg, 'scripts')]);
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
