/**
 * Copy the checkout's Python package into a scratch import root, compiled build included
 * (#316 G4, J90-RF2).
 *
 * With the mypyc extensions beside the `.py` files (the compiled gate,
 * `tools/release/compiled-gate.sh`), each compiled module of `bantamkit/_generated/` imports ONE
 * shared library that mypyc writes for the whole group, `<hash>__mypyc.<ext suffix>`, by that
 * TOP-LEVEL name: it sits in `runtime-py/src/` beside `bantamkit/`, exactly where a wheel puts it
 * (`site-packages/<hash>__mypyc...`, `runtime-py/hatch_build.py`). J90-RR measured what a copy of
 * `bantamkit/` alone does on that layout: the copied compiled modules cannot import, the `cli`
 * suite's update-registry beds failed 12 cases, and `version`'s server children died on import.
 *
 * So a copy takes the group library too, and the scratch tree runs the same build the checkout
 * runs: compiled when the checkout is, pure when it is not (a pure tree has no such file and
 * nothing extra is copied).
 */

import { cpSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

/** mypyc's group library: `<hash>__mypyc.cpython-312-darwin.so`, `...pyd` on Windows. */
export const isMypycGroupLibrary = (name) => /__mypyc\.[^/\\]*\.(so|pyd)$/.test(name);

/** The group libraries beside the package in `<repoRoot>/runtime-py/src`, as file names. */
export function mypycGroupLibraries(repoRoot) {
  return readdirSync(join(repoRoot, 'runtime-py', 'src')).filter(isMypycGroupLibrary);
}

/**
 * `<repoRoot>/runtime-py/src/bantamkit` -> `<importRoot>/bantamkit`, without bytecode caches,
 * plus every group library -> `<importRoot>/`. Returns the group libraries copied.
 */
export function copyPythonPackage(repoRoot, importRoot) {
  const src = join(repoRoot, 'runtime-py', 'src');
  cpSync(join(src, 'bantamkit'), join(importRoot, 'bantamkit'), {
    recursive: true,
    filter: (path) => !path.includes('__pycache__'),
  });
  const groups = mypycGroupLibraries(repoRoot);
  for (const name of groups) cpSync(join(src, name), join(importRoot, name));
  return groups;
}
