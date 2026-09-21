#!/usr/bin/env node
/**
 * The `ntpath.splitroot` guard in tools/conformance/ref/store_ref.py, at the 3.11 floor.
 *
 *   node --test 'tools/conformance/*.test.mjs'
 *
 * THE QUOTED GLOB, for the reason tools/hooks/update-signal.test.mjs gives: on Node 25 a bare
 * directory argument is resolved as a module, not walked.
 *
 * WHY THIS FILE EXISTS. `runtime-py/pyproject.toml` declares `requires-python = ">=3.11"`, and
 * CPython added `ntpath.splitroot` in 3.12. The reference's `winpaths` op called it unguarded,
 * so a contributor on 3.11 had `--suite store` exit 2 on `AttributeError: module 'ntpath' has no
 * attribute 'splitroot'` and `--all` stop at `store` (measured 2026-09-21, J63-1, reference on
 * `python:3.11-slim` 3.11.16). `store_ref.py` now carries `_splitroot_ported`, CPython 3.12.13's
 * `Lib/ntpath.py:splitroot` copied verbatim, and binds `_splitroot` to the native function where
 * it exists and to the port where it does not. No gate this repo owns runs at 3.11 (CI's
 * conformance job pins 3.12, and Actions is off), so the port would otherwise be a function no
 * host run ever executes — this file executes it on EVERY interpreter, 3.12 included.
 *
 * WHAT IT PINS, in three assertions that fail separately:
 *   1. the PORT against a table of (drive, root, tail) triples. The table is not typed from
 *      memory: every row is what CPython 3.12.13's native `ntpath.splitroot` printed on
 *      2026-09-21 for that raw, and assertion 2 keeps it honest.
 *   2. the NATIVE function, wherever the interpreter has one, against the SAME table — so if a
 *      future CPython changes an answer, the table and the port go red together and the row
 *      says which one moved. On an interpreter without it (3.11) this arm asserts the absence
 *      instead of skipping, so a run at the floor still reports a real result.
 *   3. which function `winpaths` is BOUND to: `native` where one exists, `ported` where not.
 *      The brief's rule was "on 3.12 the native function must still be the one called", and
 *      that is a property of the binding, not of the answers, so it is asserted by identity.
 *
 * WHICH PYTHON. The same resolution the harness uses in run.mjs, first two steps only:
 * `BANTAMKIT_CONFORMANCE_PYTHON`, else `<repo>/.venv/bin/python` or `.venv/Scripts/python.exe`.
 * Set the variable to a 3.11 to run the port as the bound function:
 *   docker run --rm -v "$PWD":/src -w /src -e BANTAMKIT_CONFORMANCE_PYTHON=/usr/local/bin/python \
 *     bk-py311-node:j63-1 node --test tools/conformance/splitroot-fallback.test.mjs
 * (the image is python:3.11-slim plus Debian's nodejs 20 and pyyaml/jsonschema/httpx; the
 * Dockerfile is in docs/conformance.md, "The reference at the 3.11 floor". The FILE PATH, not
 * the glob: node 20 answers `Could not find '/src/tools/conformance/*.test.mjs'` to the quoted
 * form, measured 2026-09-21 — glob arguments to `--test` arrived in node 21.)
 *
 * SEEN RED before it was trusted (J63-1 note, RED-THEN-GREEN): with the port's
 * `start = 8 if normp[:8].upper() == unc_prefix else 2` mutated to `start = 2`, assertion 1
 * went red on BOTH interpreters (three rows moved: `//?/UNC/srv/share/x`, `\\?\UNC\srv\share`,
 * `//?/unc/srv/share/x`) while 2 and 3 stayed green; with the binding mutated to
 * `_splitroot = _splitroot_ported` unconditionally, assertion 3 went red on 3.12 alone — on 3.11
 * the port IS the right binding, so that mutation is correctly invisible there. Both reverted,
 * hash-verified; the printed counts are in the note.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const REF_DIR = join(here, 'ref');

function findPython() {
  const explicit = process.env.BANTAMKIT_CONFORMANCE_PYTHON;
  if (explicit) return explicit;
  for (const candidate of [
    join(repoRoot, '.venv', 'bin', 'python'),
    join(repoRoot, '.venv', 'Scripts', 'python.exe'),
  ]) {
    if (existsSync(candidate)) return candidate;
  }
  throw new Error(
    'no reference interpreter: set BANTAMKIT_CONFORMANCE_PYTHON or create <repo>/.venv (docs/install.md)',
  );
}

// [raw, [drive, root, tail]] — CPython 3.12.13 `ntpath.splitroot`, printed 2026-09-21. The first
// 26 rows are `winRaws` from tools/conformance/suites/store.mjs, in its order, so the store suite's
// own fixtures are covered here by name; the rest are edges the suite does not feed: `\\.\` device
// paths, a lower-case `unc` prefix (the port upper-cases before comparing), a bare `\\?\`, a
// two-character `//?`, lower-case and colon-only drives, `C::`, a share with a trailing separator,
// and non-ASCII in both a drive letter and a UNC host.
const TABLE = [
  ["//a", ["//a", "", ""]],
  ["///a", ["///a", "", ""]],
  ["////a/b", ["///", "/", "a/b"]],
  ["//a/b", ["//a/b", "", ""]],
  ["//a/b/c", ["//a/b", "/", "c"]],
  ["//a/", ["//a/", "", ""]],
  ["//", ["//", "", ""]],
  ["/a", ["", "/", "a"]],
  ["/a/b/c", ["", "/", "a/b/c"]],
  ["a", ["", "", "a"]],
  ["a/b", ["", "", "a/b"]],
  ["", ["", "", ""]],
  [".", ["", "", "."]],
  ["/", ["", "/", ""]],
  ["/a/b/../c", ["", "/", "a/b/../c"]],
  ["C:x", ["C:", "", "x"]],
  ["C:/x", ["C:", "/", "x"]],
  ["C:", ["C:", "", ""]],
  ["\\\\srv\\share\\x", ["\\\\srv\\share", "\\", "x"]],
  ["//?/C:/x", ["//?/C:", "/", "x"]],
  ["//?/UNC/srv/share/x", ["//?/UNC/srv/share", "/", "x"]],
  ["a.md", ["", "", "a.md"]],
  ["/f/.md", ["", "/", "f/.md"]],
  ["/f/a.", ["", "/", "f/a."]],
  ["x/y.md", ["", "", "x/y.md"]],
  ["\\\\a/b\\c", ["\\\\a/b", "\\", "c"]],
  ["//./C:/x", ["//./C:", "/", "x"]],
  ["\\\\.\\PhysicalDrive0", ["\\\\.\\PhysicalDrive0", "", ""]],
  ["\\\\?\\UNC\\srv\\share", ["\\\\?\\UNC\\srv\\share", "", ""]],
  ["//?/unc/srv/share/x", ["//?/unc/srv/share", "/", "x"]],
  ["\\\\?\\", ["\\\\?\\", "", ""]],
  ["//?", ["//?", "", ""]],
  ["c:", ["c:", "", ""]],
  ["c:\\", ["c:", "\\", ""]],
  [":", ["", "", ":"]],
  [":x", ["", "", ":x"]],
  ["\\", ["", "\\", ""]],
  ["\\\\", ["\\\\", "", ""]],
  ["\\\\\\", ["\\\\\\", "", ""]],
  ["C::", ["C:", "", ":"]],
  ["//srv/share/", ["//srv/share", "/", ""]],
  ["C:\\a\\..\\b", ["C:", "\\", "a\\..\\b"]],
  ["é:/x", ["é:", "/", "x"]],
  ["//sérv/shäre/x", ["//sérv/shäre", "/", "x"]],
];

// One Python process, three facts. `store_ref` is imported the way the harness runs it, so the
// binding under test is the one `winpaths` really calls, not a copy of the selection logic.
const SNIPPET = `
import json, sys, ntpath
sys.path.insert(0, sys.argv[1])
import store_ref
raws = json.load(sys.stdin)
native = getattr(ntpath, "splitroot", None)
bound = ("native" if native is not None and store_ref._splitroot is native
         else "ported" if store_ref._splitroot is store_ref._splitroot_ported
         else "other")
json.dump({
    "version": sys.version.split()[0],
    "hasNative": native is not None,
    "bound": bound,
    "ported": [list(store_ref._splitroot_ported(r)) for r in raws],
    "native": None if native is None else [list(native(r)) for r in raws],
}, sys.stdout, ensure_ascii=False)
`;

function ask() {
  const python = findPython();
  const r = spawnSync(python, ['-c', SNIPPET, REF_DIR], {
    input: JSON.stringify(TABLE.map(([raw]) => raw)),
    encoding: 'utf8',
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
  });
  assert.equal(r.status, 0, `${python} exited ${r.status}\n${r.stderr}`);
  return { python, ...JSON.parse(r.stdout) };
}

const answer = ask();
const expected = TABLE.map(([, triple]) => triple);

test(`the ported splitroot answers the 3.12 table on ${answer.version}`, () => {
  assert.deepEqual(answer.ported, expected);
});

test(`the native splitroot, where ${answer.version} has one, answers the same table`, () => {
  if (answer.hasNative) {
    assert.deepEqual(answer.native, expected);
  } else {
    assert.equal(answer.native, null);
    assert.ok(answer.version.startsWith('3.11.'), `no ntpath.splitroot on ${answer.version}`);
  }
});

test(`winpaths is bound to the native function where it exists, the port where not (${answer.version})`, () => {
  assert.equal(answer.bound, answer.hasNative ? 'native' : 'ported');
});
