/**
 * Vendor the repository-root asset pack into this package so `npm pack` can see it.
 *
 * This is the Node counterpart of `runtime-py/hatch_build.py`, and it exists for the
 * same reason (RB-P85): the pack lives at the REPOSITORY root, one level above this
 * package root, and no packaging system can reach outside its own package directory.
 * npm is stricter than hatchling here — there is no `force-include`, so the pack has to
 * physically exist under `runtime-ts/` before the tarball is built.
 *
 * Two rules carried over from the hatch hook:
 *
 *   1. LOCATE, don't hardcode a relative path and hope. `../assets` is the checkout
 *      layout; a populated local `assets/` is the already-vendored layout (`npm pack`
 *      run inside an extracted tarball). Prefer the checkout, so a stale vendored copy
 *      can never win over the pack `runtime-py` actually publishes.
 *   2. Neither found or found empty -> THROW. A build that cannot include the pack must
 *      FAIL, not succeed short. The Python defect this rule comes from was a build that
 *      returned 0 and shipped an artifact without its data.
 *
 * The vendored copy is byte-for-byte (`copyFileSync`), and stale files are deleted,
 * because `build_identity` hashes every byte of the whole tree — an extra file moves
 * `assets_digest` exactly as surely as a missing one.
 *
 * THE COPY GOES FIRST AND THE DELETE IS A PRUNE, which is review round 4 (L5). This used
 * to be `rmSync(vendored, { recursive: true })` and then `cpSync`, and the vendored pack
 * is a directory the whole TEST SUITE reads: `node --test` runs its files concurrently,
 * `packaging.test.mjs` runs `npm pack --dry-run` whose `prepack` runs this script, and
 * every other file reading an asset inside that window failed. MEASURED: `npm test` went
 * red on 2 of ~20 full runs with `AssetNotFound: contract asset not found:
 * runtime-ts/assets/contracts/default.yaml`, on a test that moved with the schedule; a
 * process watching one asset for the length of one sync saw it unreadable 1,745 times.
 * Overwriting in place and then removing only what the checkout no longer has holds the
 * same two guarantees — byte-for-byte, no stale files — and never makes an asset absent.
 *
 * U9, 2026-08-24. THE LICENCE IS THE SAME PROBLEM AND IT IS NOT SOLVED BY npm's RULE.
 * npm is documented to include `LICENSE` in every tarball regardless of `files`, and
 * that documentation is true of a `LICENSE` sitting in the PACKAGE root. This repo's
 * licence sits at the REPOSITORY root, one level up, and MEASURED with the file in
 * place and no vendoring step: `npm pack --dry-run --json` listed 129 files and the
 * only two outside `dist/` and `assets/` were `README.md` and `package.json`. npm
 * cannot reach above the package directory any more than hatchling can. So the licence
 * is vendored here, by the same two rules and in the same pass.
 */
import { copyFileSync, existsSync, mkdirSync, readdirSync, renameSync, rmSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const vendored = join(packageRoot, 'assets');
const checkout = join(dirname(packageRoot), 'assets');

function countFiles(dir) {
  let n = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true, recursive: true })) {
    if (entry.isFile()) n += 1;
  }
  return n;
}

function populated(dir) {
  return existsSync(dir) && statSync(dir).isDirectory() && countFiles(dir) > 0;
}

/** Every path under `dir`, relative to it — files and directories both. */
function entriesUnder(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true, recursive: true }).map((e) =>
    join(e.parentPath ?? e.path, e.name).slice(dir.length + 1),
  );
}

/**
 * Copy one file so a concurrent reader sees ALL of the old bytes or ALL of the new ones.
 *
 * `cpSync` opens the destination with O_TRUNC and streams into it, so a reader that opens the
 * same path mid-copy gets a short or empty file. Removing the rm-then-copy window left THIS
 * one, and it is narrower rather than gone: the whole suite reads this directory while
 * `prepack` rewrites it. Measured 2026-09-05 — `sync-assets never leaves the vendored pack
 * absent while it runs` reports `the pack was unreadable 1 times` on node 18 and on Windows,
 * and passes on node 22, which is a timing difference and not a platform one.
 *
 * A temp file plus `renameSync` is atomic within a filesystem, and the temp name carries the
 * pid so two `prepack`s cannot collide on it.
 *
 * HONESTLY: THE MEASURED DEFECT IS FIXED BY THE PER-FILE LOOP, NOT BY THIS. Replacing the
 * bulk `cpSync(checkout, vendored, {recursive, force})` with a walk is what takes the failure
 * from 3/3 red to 5/5 green on node 18. Swapping this function for a plain `copyFileSync`
 * leaves the test green 5/5 even after the watcher was taught to catch a partial read —
 * macOS's `copyFileSync` can clone the file, and a clone has no window to observe.
 *
 * It is kept because the window is real where the copy is a read/write loop, which is Linux
 * and Windows, and CI runs both. That is REASONING, not a measurement taken here, and the
 * `short` counter in `packaging.test.mjs` is the thing that could turn it into one.
 */
function copyFileAtomically(from, to) {
  const tmp = `${to}.sync-${process.pid}`;
  try {
    copyFileSync(from, tmp);
    renameSync(tmp, to);
  } catch (e) {
    rmSync(tmp, { force: true });
    throw e;
  }
}

if (populated(checkout)) {
  // Overwrite first, so no reader ever meets a missing file...
  const stale = new Set(entriesUnder(vendored));
  for (const rel of entriesUnder(checkout)) {
    const source = join(checkout, rel);
    const target = join(vendored, rel);
    if (statSync(source).isDirectory()) mkdirSync(target, { recursive: true });
    else {
      mkdirSync(dirname(target), { recursive: true });
      copyFileAtomically(source, target);
    }
  }
  for (const kept of entriesUnder(checkout)) stale.delete(kept);
  // ...then prune only what the checkout no longer has, deepest first so a directory is
  // empty by the time it is removed.
  for (const gone of [...stale].sort((a, b) => b.length - a.length)) {
    rmSync(join(vendored, gone), { recursive: true, force: true });
  }
  process.stderr.write(
    `sync-assets: vendored ${countFiles(vendored)} files from ${checkout}\n`,
  );
} else if (populated(vendored)) {
  process.stderr.write(
    `sync-assets: reusing already-vendored pack (${countFiles(vendored)} files) at ${vendored}\n`,
  );
} else {
  throw new Error(
    'bantamkit asset pack not found or empty; refusing to build an artifact ' +
      `without it. Looked in: ${checkout}, ${vendored}`,
  );
}

/**
 * The licence, by the same two rules. `../LICENSE` is the checkout; a local `LICENSE`
 * is the already-vendored layout (`npm pack` inside an extracted tarball). Neither
 * found -> throw, because `package.json` DECLARES `"license": "MIT"` and a tarball that
 * carries the declaration without the text states a licence it does not grant.
 */
const vendoredLicense = join(packageRoot, 'LICENSE');
const checkoutLicense = join(dirname(packageRoot), 'LICENSE');

function isFile(path) {
  return existsSync(path) && statSync(path).isFile();
}

if (isFile(checkoutLicense)) {
  copyFileSync(checkoutLicense, vendoredLicense);
  process.stderr.write(`sync-assets: vendored LICENSE from ${checkoutLicense}\n`);
} else if (isFile(vendoredLicense)) {
  process.stderr.write(`sync-assets: reusing already-vendored LICENSE at ${vendoredLicense}\n`);
} else {
  throw new Error(
    'bantamkit LICENSE not found; refusing to build a tarball that declares MIT ' +
      `without carrying its text. Looked in: ${checkoutLicense}, ${vendoredLicense}`,
  );
}
