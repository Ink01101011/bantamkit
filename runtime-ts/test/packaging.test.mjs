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
import { execFileSync, spawn, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoPack = join(dirname(packageRoot), 'assets');

/**
 * AMENDED 2026-09-13 (job50, J50-15, I5): 91 files / 237,831 bytes, measured at that commit by the
 * walk the byte node below performs over the repository pack, where `assets/tools/bantamkit_read.json`
 * and `assets/tools/repo_map.json` each lost 13 bytes — `"surfaces": ["mcp"]` became `[]` — because
 * both tools left the MCP roster on the user's ruling of 2026-09-12. NEITHER FILE LEFT THE PACK: the
 * contract is kept whole so the dormant handlers on both runtimes have the same schema to return to,
 * which is why the file count did not move and the second decrease this ledger records is 26 bytes
 * rather than two manifests. Every earlier line stands as it was written.
 *
 * AMENDED 2026-09-12 (job50, J50-3, J49-B4): 91 files / 233,073 bytes, measured at that commit
 * by `npm pack --dry-run --json` in `runtime-ts/`, where the DESCRIPTIONS of two manifests were
 * cut: `assets/tools/skill_audit.json` 10,503 -> 4,109 bytes (8,161 -> 1,826 decoded chars) and
 * `assets/tools/token_ledger.json` 7,459 -> 3,361 bytes (5,985 -> 1,883 chars). Claude Code
 * truncates a served tool description at 2,048 characters, mid-sentence and without an error,
 * so the half that said WHEN to call each tool was the half no host ever showed; the cut text
 * moved to `docs/skill-audit.md` and `docs/ledger.md`. The file count did not move. The first
 * DECREASE this ledger records, and the reason the node below pins a number rather than a
 * floor. Every earlier line stands as it was written.
 *
 * AMENDED 2026-09-11 (job46, J46-18, AS-1(c)): 91 files / 243,565 bytes, measured at that
 * commit, where `assets/tools/token_ledger.json` arrived at 7,459 bytes — the manifest for the
 * fourteenth served tool, the transcript ledger. Every earlier line stands as it was written.
 *
 * AMENDED 2026-09-11 (job46, J46-17, AS-1(b)): 90 files / 236,106 bytes, measured at that
 * commit, where `assets/pricing/default.json` arrived at 1,041 bytes — the price table, which
 * ships with an EMPTY `rates` map on purpose. The sentence below is left as it stood; note
 * that its own "231,821 bytes at HEAD" had already gone stale against the byte node, exactly
 * as the 224,195 before it did, and for the same reason — the file count and the byte total
 * are two records and only one of them is asserted in this paragraph.
 *
 * The size of the pack, measured: 89 files / 231,821 bytes at HEAD, where job45's J45-11
 * added `assets/tools/repo_map.json` at 2,358 bytes (88 files / 229,463 bytes before it,
 * where J45-3 added
 * `assets/tools/memory_dream.json` at 1,605 bytes (87 files / 227,858 bytes before it — the
 * figure the byte node below asserts, and NOT the 224,195 this paragraph used to carry, which
 * had gone stale against it while `skill_audit.json` grew four times; where job44's SA2b grew
 * `assets/tools/skill_audit.json` by 1,743 bytes with the whole-value-quote rule (87 files /
 * 222,452 bytes at 56f8a52, where SA1 added that manifest; 86 files / 217,310 bytes at
 * 92661f7, where job43's R1
 * added `assets/tools/bantamkit_read.json` and two contract sentences (85 files / 214,969
 * bytes at 39c5a74, where job42's MC1 added `assets/tools/memory_compact.json` and
 * `"agent",` later joined its surfaces; 84 files / 213,773 bytes at 8634632, where U11
 * added `assets/tools/bantamkit_status.json`; 83 / 212,480 before that). Pinned as a
 * NUMBER and not derived, because the number is the thing `build_identity` hashes — a
 * pack that grows or shrinks moves `assets_digest` and therefore `build_id`, and that
 * must be a deliberate edit here rather than a silent one.
 */
const EXPECTED_ASSET_FILES = 91;

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
  assert.equal(bytes, 238751); // +454: assets/tools/shiftwork_clock_in.json and +466: assets/tools/shiftwork_clock_out.json, the descriptions say what clock_in WRITES (one best-effort brief line per brief) and that `briefed` is runtime-measured, never a gate (job50 J50-16A, F6); -26: assets/tools/bantamkit_read.json and assets/tools/repo_map.json, `"surfaces": ["mcp"]` -> `[]` (13 bytes each) — both tools retired from the MCP roster by the user's ruling of 2026-09-12, assets kept whole, handlers DORMANT (job50 J50-14/J50-15, I5); +3137: assets/tools/shiftwork_clock_out.json, the accounting line's declared shape — `tokens` and `duration_ms` required, five named keys typed, any other key passes (job50 J50-7, F5); +1647: assets/schemas/shiftwork-checkpoint.json gains the optional handoff.notes prose key and the $comment that explains it (job50 J50-5); -6394: assets/tools/skill_audit.json and -4098: assets/tools/token_ledger.json, their descriptions cut to 1,826 and 1,883 decoded chars under the host's 2,048-char truncation, the reference text moved to docs/ (job50 J50-3, J49-B4); +7459: assets/tools/token_ledger.json, the fourteenth served tool's manifest — the transcript ledger promoted off `tools/ledger/token-ledger.mjs` (job46 J46-18, AS-1(c)); +1041: assets/pricing/default.json, the price table, shipped with an empty `rates` map because no rate in it could have been sourced (job46 J46-17, AS-1(b)); +320: assets/tools/shiftwork_clock_out.json says the AS-2 roles check exists, so the surprise reaches the reader of the tool schema (job46 J46-10); +2924: assets/schemas/shiftwork-checkpoint.json gains the optional job.roles map and the $comment amendment that explains it (job46 J46-7, AS-2); +2358: assets/tools/repo_map.json (job45 J45-11, roadmap row 10); +1605: assets/tools/memory_dream.json (job45 J45-3, roadmap row 5); +509: skill_audit.json's empty-root refusal (F5); +1739: skill_audit.json's `versions` argument, host truth over the byte-order guess (F4); +1415: its version-resolution rule (SA6); +1743: its whole-value-quote rule (SA2b); +5097 at 56f8a52: assets/tools/skill_audit.json (SA1); +2341 at 92661f7: bantamkit_read.json and its two contract sentences; +8 when its part example became "document"; +37 when offset gained maximum 2^53-1 (F1)
});

/**
 * J49-B4 (job50, J50-3). Claude Code truncates a served MCP tool description at 2,048
 * characters — mid-sentence, without an error, and keeping the input schema, so the call stays
 * syntactically possible and semantically unguided. Observed only in the host's own log line,
 * never documented, hence the margin: 1,900 DECODED characters of the JSON string, not bytes
 * (`skill_audit`'s old description was 8,161 chars and 8,201 bytes). Both servers serve
 * `asset["description"]` verbatim from one shared file, so a differential between the two
 * runtimes can never see this; it is a per-pack literal or it is nothing. Asserted over the
 * VENDORED copy, the artifact npm publishes, as every other node in this file is.
 */
const DESCRIPTION_BUDGET = 1900;

test('no served tool description exceeds the budget the host truncates at', () => {
  packListing(); // prepack vendors runtime-ts/assets as a side effect
  const tools = join(packageRoot, 'assets', 'tools');
  const manifests = readdirSync(tools).filter((f) => f.endsWith('.json')).sort();
  assert.ok(manifests.length > 0, `no tool manifests under ${tools}`);
  for (const file of manifests) {
    const { name, description } = JSON.parse(readFileSync(join(tools, file), 'utf8'));
    assert.equal(typeof description, 'string', `${file}: description is not a string`);
    assert.ok(
      description.length <= DESCRIPTION_BUDGET,
      `${name} (${file}): description is ${description.length} decoded chars, over the ${DESCRIPTION_BUDGET} budget — the host cuts at 2,048 and shows no error`,
    );
  }
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

// ---- L5: vendoring must never take the pack away from a concurrent reader ---------------

test('sync-assets never leaves the vendored pack absent while it runs', async () => {
  // MEASURED, review round 4 (L5): `npm test` fails intermittently — 2 of ~20 full runs on
  // this machine — with `AssetNotFound: contract asset not found: runtime-ts/assets/
  // contracts/default.yaml`, and the test it lands on moves with the schedule
  // (`launcher.test.mjs:250` for the reviewer, a `documentManifest` case here). `node --test`
  // runs the files CONCURRENTLY, this file's `packListing()` runs `npm pack --dry-run` whose
  // `prepack` runs `scripts/sync-assets.mjs`, and that script used to `rmSync` the whole
  // vendored tree before copying it back. Every other test file reading an asset in that
  // window fails, and the failure names a file that is present before and after.
  //
  // The property: the vendored pack is a directory the whole suite reads, so vendoring must
  // never make it absent. A copy that OVERWRITES in place, then removes only what the
  // checkout no longer has, holds the script's own guarantee — byte-for-byte, no stale
  // files, because `build_identity` hashes every byte — with no window at all.
  //
  // This case is deterministic where the flake is not: it watches the path while the script
  // runs instead of hoping the schedule lands on it. Against the pre-fix script it goes red
  // on the first run.
  const { readFileSync: read, writeFileSync: write } = await import('node:fs');
  const vendored = join(packageRoot, 'assets');
  const witness = join(vendored, 'contracts', 'default.yaml');
  const before = read(witness);
  const watchBed = mkdtempSync(join(realpathSync.native(tmpdir()), 'l5-'));
  const verdict = join(watchBed, 'verdict.json');
  const stop = join(watchBed, 'stop');

  // The watcher is a CHILD PROCESS and not a promise in this one. `spawnSync` blocks the
  // event loop for its whole duration, so an in-process poll — however it yields — cannot
  // run while the thing it is watching runs, and would report a clean window that it never
  // actually looked at. A second process is the only observer that is awake at the time.
  const watcher = spawn(
    process.execPath,
    [
      '-e',
      // `short` is the half a readability counter cannot see. `copyFileSync` opens the
      // destination with O_TRUNC and streams into it, so a reader can succeed and still get a
      // PARTIAL file — which counts as `ok` to a watcher that only asks whether the read threw.
      // The file is byte-identical before and after, so any read of a different length is a
      // view of the copy in progress and nothing else.
      // A STOP FILE, NOT A SIGNAL. `child.kill('SIGTERM')` on Windows is `TerminateProcess`:
      // there is no SIGTERM to handle, the `process.on('SIGTERM')` arm never runs, and the
      // verdict is never written — which is precisely how this test failed there, with
      // `ENOENT ... verdict.json` and nothing said about the pack at all. Measured on CI
      // 2026-09-05. A file both sides can see ends the watcher the same way everywhere.
      `const fs=require('fs');const [w,v,s,n]=process.argv.slice(1);const want=Number(n);` +
        `let gone=0,ok=0,short=0;const end=Date.now()+30000;` +
        `while(Date.now()<end&&!fs.existsSync(s)){` +
        `try{const b=fs.readFileSync(w);if(b.length===want)ok++;else short++}catch{gone++}}` +
        `fs.writeFileSync(v,JSON.stringify({gone,ok,short}));`,
      witness,
      verdict,
      stop,
      String(before.length),
    ],
    { stdio: 'ignore' },
  );
  await new Promise((r) => setTimeout(r, 250)); // let it get going

  const run = spawnSync(process.execPath, [join(packageRoot, 'scripts', 'sync-assets.mjs')], {
    cwd: packageRoot,
    encoding: 'utf8',
  });
  await new Promise((r) => setTimeout(r, 250)); // and let it see the aftermath
  write(stop, '');
  await new Promise((r) => watcher.on('exit', r));
  const seen = JSON.parse(read(verdict, 'utf8'));

  assert.equal(run.status, 0, run.stderr);
  assert.ok(seen.ok > 0, 'the watcher has to have actually looked');
  assert.equal(seen.gone, 0, `the pack was unreadable ${seen.gone} times while sync-assets ran`);
  // WHAT THIS COUNTER PROVES TODAY, AND IT IS LESS THAN THE SENTENCE THAT USED TO BE HERE.
  // The old comment credited `short` to "a temp file and a rename". There is no rename — it
  // was written, measured EPERM on Windows, and removed (`sync-assets.mjs` says why). And in
  // the steady state this assertion cannot fail at all: `sameBytes` skips a file whose
  // destination already holds the source's bytes, and the vendored witness always does after
  // a build, so `copyFileSync` never opens it and the watcher can never catch a prefix.
  // Measured 2026-09-05: the witness's mtime is unchanged across a full `sync-assets.mjs`.
  //
  // It is kept because it is not vacuous where it matters — on the FIRST sync after the
  // checkout's assets change, which is the only moment the prefix window is open at all, and
  // the moment a developer running this suite mid-edit is actually in. `gone` carries the L5
  // property proper and has the same shape: both are red against the pre-fix script, which is
  // what this case was written against.
  assert.equal(seen.short, 0, `the witness was read half-written ${seen.short} times`);
  assert.deepEqual(read(witness), before, 'and it is byte-identical afterwards');
});
