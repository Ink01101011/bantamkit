#!/usr/bin/env node
/**
 * Compile `dist/` before npm cuts a tarball, so a pack can never ship stale code.
 *
 * THE DEFECT THIS CLOSES, MEASURED (job56). `prepack` used to be `sync-assets` alone, so
 * `npm pack` vendored CURRENT assets over whatever `dist/` happened to be sitting on disk.
 * `dist/` is gitignored, so it survives a checkout: compile at one commit, check `src/` back
 * to another, and the tree is silently inconsistent. That is not a hypothetical — it is what
 * shipped. `bantamkit-mcp@0.35.0` on npm serves 12 tools where `bantamkit==0.35.0` on PyPI
 * serves 14, and the two missing ones (`work_plan`, `shiftwork_plan`) are present in the
 * published tarball's `assets/tools/*.json` and absent from every one of its 37 `.js` files.
 * Assets from the checkout, code from an older build: the fingerprint of an unbuilt pack.
 *
 * The Python half needs no counterpart. `runtime-py` ships `src/` into the wheel with no
 * compile step, so it has no build artifact that can go stale; `hatch_build.py` vendors the
 * asset pack and that is the whole of its packaging work. Recorded as a divergence row in
 * `docs/porting.md`.
 *
 * WHY THIS IS A SCRIPT AND NOT `"prepack": "npm run build && npm run sync-assets"`.
 * -------------------------------------------------------------------------------
 * Because that one-liner was written first, measured, and it reddens the test suite.
 *
 * `runtime-ts/test/packaging.test.mjs` shells `npm pack --dry-run --json` six times, and
 * `node --test` runs the suite's files CONCURRENTLY. Building on every `prepack` therefore
 * rewrites all 37 files of `dist/` six times WHILE other test files are spawning
 * `dist/cli.js`. MEASURED on this machine, fifteen full `npm test` runs per arm:
 *
 *   prepack = sync only (before)            7.03 s,  0 / 15 runs failed
 *   prepack = npm run build && sync         10.95 s, 3 / 15 runs failed
 *   prepack = this script && sync           7.17 s,  0 / 15 runs failed
 *
 * The three failures were all the same case — `server.test.mjs`'s `a float argument reaches
 * the accounting log as 5.0, not 5`, dying on `TypeError: Cannot read properties of
 * undefined (reading 'result')`, i.e. a server that never answered. A CONTROL separates the
 * cause from mere CPU load: run the identical `tsc` on every `prepack` but emit to
 * `dist-control/` instead, so the load is the same and `dist/` is never touched — 0 / 10
 * runs failed. The cost is the REWRITE of a tree the suite executes, not the compile.
 *
 * This is the same hazard `scripts/sync-assets.mjs` documents under "THE COPY GOES FIRST AND
 * THE DELETE IS A PRUNE" (review round 4, L5), reached by a different mutator: vendoring made
 * the asset pack briefly ABSENT, and compiling makes each module briefly TRUNCATED.
 *
 * SO THE GUARD IS THE PROPERTY ITSELF, NOT A CONVENIENCE. A `--dry-run` cuts no tarball.
 * Nothing it produces can be installed, published or served, so there is nothing that could
 * ship stale, and compiling for it buys no safety while costing the suite one in five runs.
 * Every pack that actually writes a `.tgz`, and every `npm publish`, builds. npm exports the
 * flag as `npm_config_dry_run` (verified here: `"true"` under `npm pack --dry-run` and under
 * `npm publish --dry-run`, undefined under a real `npm pack`).
 *
 * THE PRICE OF THE GUARD, stated so nobody has to find it: `npm publish --dry-run` and
 * `npm pack --dry-run` now report a file list and byte sizes computed over the `dist/` that
 * is on disk, which a rehearsal-minded reader might take for the bytes a real publish would
 * cut. Names and count are the same either way; sizes can differ. The gate that measures
 * what a real publish would ship is `tools/conformance/npx-cold-start.mjs`, which does a
 * REAL `npm pack` and drives the tarball over stdio.
 *
 * `--incremental` WAS TRIED AND IS DISQUALIFIED. It would make repeat builds free and
 * non-rewriting (464 ms, output mtimes unmoved), but MEASURED: with a `.tsbuildinfo` on disk
 * and `dist/` deleted, `tsc -p tsconfig.json` emitted NOTHING — zero `.js` files, no `dist/`
 * at all, exit 0. A build that silently produces no output is a worse version of the very
 * defect this file exists to close, so the build stays a full one.
 */
import { spawnSync } from 'node:child_process';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));

if (process.env.npm_config_dry_run === 'true') {
  console.error('build-for-pack: --dry-run cuts no tarball, so nothing can ship stale; build skipped.');
  process.exit(0);
}

// `npm_execpath` is npm's own CLI path and is the cross-platform way to re-enter npm from a
// lifecycle script: `node <npm-cli.js> run build` needs no shell and no `.cmd` resolution,
// which is what breaks a bare `npm` spawn on Windows. The fallback covers a direct
// `node scripts/build-for-pack.mjs` run by hand, outside any npm lifecycle.
const npmCli = process.env.npm_execpath;
const run = npmCli
  ? spawnSync(process.execPath, [npmCli, 'run', 'build'], { cwd: packageRoot, stdio: 'inherit' })
  : spawnSync('npm', ['run', 'build'], {
      cwd: packageRoot,
      stdio: 'inherit',
      shell: process.platform === 'win32',
    });

if (run.error) {
  console.error(`build-for-pack: could not run the build: ${run.error.message}`);
  process.exit(1);
}
// A pack whose build did not succeed must FAIL, never succeed short — the same rule
// `scripts/sync-assets.mjs` applies to a missing asset pack.
process.exit(run.status ?? 1);
