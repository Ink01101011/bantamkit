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
 * The vendored copy is byte-for-byte (`copyFileSync`), and stale files are deleted
 * first, because `build_identity` hashes every byte of the whole tree — an extra file
 * moves `assets_digest` exactly as surely as a missing one.
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
import { copyFileSync, cpSync, existsSync, readdirSync, rmSync, statSync } from 'node:fs';
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

if (populated(checkout)) {
  rmSync(vendored, { recursive: true, force: true });
  cpSync(checkout, vendored, { recursive: true });
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
