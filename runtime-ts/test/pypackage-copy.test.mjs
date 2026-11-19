/**
 * `copyPythonPackage` (`tools/conformance/lib/pypackage.mjs`) takes the mypyc group library
 * along with `bantamkit/` (#316 G4, J90-RF3, J90-RR2 F1).
 *
 * WHY A SYNTHETIC TREE. The suites that call `copyPythonPackage` (`version`, `cli`) run their
 * copies under the reference interpreter, and under the compiled gate that interpreter's venv
 * has an editable install: `_editable_impl_bantamkit.pth` puts the checkout's `runtime-py/src`
 * on `sys.path`, so a copy that left `<hash>__mypyc.<ext>` behind still imports it from the
 * checkout. J90-RR2 made the copy loop copy nothing and saw `--suite version --suite cli` PASS
 * 368. Only a tree in which the copy is the one way the file can arrive can see that break, so
 * this file builds `<repoRoot>/runtime-py/src/` itself, pure and compiled, and asserts on what
 * lands in the import root. The fake library is bytes, not a loadable extension.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, sep } from 'node:path';
import { test } from 'node:test';

import { copyPythonPackage } from '../../tools/conformance/lib/pypackage.mjs';

const GROUP_SO = '0123abcd__mypyc.cpython-312-darwin.so';
const GROUP_PYD = '4567ef01__mypyc.cp312-win_amd64.pyd';

function filesUnder(root) {
  const out = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else out.push(relative(root, p).split(sep).join('/'));
    }
  };
  walk(root);
  return out.sort();
}

function syntheticRepo(groups) {
  const repoRoot = mkdtempSync(join(tmpdir(), 'pypackage-copy-'));
  const src = join(repoRoot, 'runtime-py', 'src');
  mkdirSync(join(src, 'bantamkit', '_generated'), { recursive: true });
  mkdirSync(join(src, 'bantamkit', '__pycache__'));
  writeFileSync(join(src, 'bantamkit', '__init__.py'), 'x = 1\n');
  writeFileSync(join(src, 'bantamkit', '_generated', 'mod.py'), 'y = 2\n');
  writeFileSync(join(src, 'bantamkit', '__pycache__', 'stale.pyc'), 'stale');
  writeFileSync(join(src, 'README.txt'), 'not part of the build\n');
  for (const name of groups) writeFileSync(join(src, name), Buffer.from(`group library ${name}\x00\x7f`));
  return { repoRoot, src };
}

for (const [layout, groups] of [
  ['pure', []],
  ['compiled', [GROUP_SO]],
  ['compiled, Windows naming', [GROUP_PYD]],
]) {
  test(`copyPythonPackage copies the build beside it: ${layout} layout`, () => {
    const { repoRoot, src } = syntheticRepo(groups);
    const importRoot = mkdtempSync(join(tmpdir(), 'pypackage-dest-'));
    try {
      const returned = copyPythonPackage(repoRoot, importRoot);
      assert.deepEqual(returned.sort(), [...groups].sort(), 'the returned list names the group libraries copied');
      assert.deepEqual(
        filesUnder(importRoot),
        ['bantamkit/__init__.py', 'bantamkit/_generated/mod.py', ...groups].sort(),
        `the import root is not the ${layout} build: bantamkit/ without caches, plus every group library`,
      );
      for (const name of groups) {
        assert.deepEqual(readFileSync(join(importRoot, name)), readFileSync(join(src, name)));
      }
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
      rmSync(importRoot, { recursive: true, force: true });
    }
  });
}
