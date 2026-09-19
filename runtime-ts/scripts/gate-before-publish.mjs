#!/usr/bin/env node
/**
 * Run the install gate before npm publishes anything, and REFUSE the publish if it fails.
 *
 * Wired as `prepublishOnly`, which npm runs FIRST and ONLY on `npm publish` — measured here
 * with npm 11.6.2, a hook per lifecycle event writing a log line:
 *
 *   prepublishOnly -> prepack -> prepare -> postpack -> (upload)
 *
 * and with a hook that exits 1, the log shows prepublishOnly and NOTHING after it: npm exits
 * 1 at the hook, so nothing is packed and nothing reaches the registry. That ordering is the
 * whole point of choosing this event. `prepublish` is deprecated and also fires on install;
 * `prepare` fires on `npm ci` in every consumer's tree, where this repository's `tools/`
 * directory does not exist. `prepublishOnly` runs in the PUBLISHER's tree and nowhere else.
 *
 * WHAT IT RUNS: `tools/conformance/npx-cold-start.mjs`, unmodified, in its plain form. That
 * gate does a REAL `npm pack`, installs the tarball through `npx` into a cache that has never
 * seen it, and drives it over stdio — and it derives the tool roster it expects from
 * `MCP_TOOLS` in `src/mcp/server.ts`, a declaration the pack did not produce. It is therefore
 * the only check in the repository that can see a tarball whose advertised surface disagrees
 * with the source, which is exactly what `bantamkit-mcp@0.35.0` shipped (job56; the numbers
 * are in `docs/porting.md`'s divergence table). The `--offline` arm is NOT used: job56
 * measured it at 140-590 s against roughly 30 s plain, and a release step nobody will wait
 * for is a release step somebody will bypass.
 *
 * `scripts/build-for-pack.mjs` already closed this hazard at source, so on a healthy tree
 * this hook should never fire. It is the belt to that braces: `prepack` guarantees the
 * `dist/` in the tarball was compiled from the `src/` beside it, and this hook independently
 * checks what the tarball ACTUALLY answers to `tools/list` from an install.
 *
 * THE DRY-RUN LEAK, WHICH IS WHY THIS IS A SCRIPT AND NOT A PLAIN COMMAND STRING.
 * ------------------------------------------------------------------------------
 * `npm publish --dry-run` exports `npm_config_dry_run="true"` into the hook's environment,
 * and npm reads its own config from `npm_config_*`, so EVERY npm that the hook spawns
 * inherits the flag. Measured: a child `npm pack` under that environment exits 0, prints the
 * tarball's name on stdout, and writes NO FILE. The gate would then fail on
 * `readdirSync(packDir).find(...)` being `undefined` — a spurious red on a perfectly good
 * tree, with a `TypeError` for a message. A rehearsal that fails on a healthy tree teaches
 * people to skip the rehearsal, so the flag is stripped from the child environment here and
 * the gate does the same real work under `--dry-run` as under a real publish.
 *
 * The price of stripping it, stated so nobody has to find it: `npm publish --dry-run` now
 * compiles `runtime-ts/dist/` (the gate's real `npm pack` runs `prepack`), cuts a tarball in
 * a temp directory and installs it into a temp `npx` cache. It still publishes nothing. The
 * side effect on `dist/` is the same one `npm test` already causes through `pretest`.
 *
 * WHAT THIS HOOK DOES NOT PROTECT, measured rather than assumed:
 *   - `npm publish --ignore-scripts` skips it silently. Measured: the failing hook above,
 *     under `--ignore-scripts`, did not run and npm went on to report a publish.
 *   - `npm publish <tarball.tgz>` skips it. Measured: a tarball built with `--ignore-scripts`,
 *     published by path from a directory with no `package.json`, exited 0 with the hook
 *     never running. npm runs no lifecycle script out of a pre-built tarball.
 *   - The PyPI half. `twine upload` has no hook of any kind, and the Python wheel has no
 *     build artifact that can go stale anyway (`docs/porting.md`).
 *   - Anything about the tree that is not what the gate checks: it gates the WORKING TREE the
 *     publisher is standing in, not the commit, so uncommitted edits are gated and a tag is
 *     not.
 * The release pipeline is what closes those, by running the gates itself and never reaching
 * `npm publish` when one is red; this hook is the last thing standing between a hand-typed
 * `npm publish` and the registry.
 */
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(packageRoot);
const gate = join(repoRoot, 'tools', 'conformance', 'npx-cold-start.mjs');

// REFUSE, never skip. A publish from a tree where the gate is missing is a publish nobody
// checked, and "the check was not there" is not a reason to ship — it is the reason not to.
if (!existsSync(gate)) {
  console.error(`gate-before-publish: the install gate is not at ${gate}.`);
  console.error('gate-before-publish: refusing to publish a tarball nothing has checked.');
  process.exit(1);
}

const env = { ...process.env };
if (env.npm_config_dry_run === 'true') {
  // See THE DRY-RUN LEAK above: left in place, this silently turns the gate's own `npm pack`
  // into a dry run that writes no tarball.
  delete env.npm_config_dry_run;
  console.error('gate-before-publish: --dry-run rehearses the gate for real; it publishes nothing.');
}

console.error('gate-before-publish: running tools/conformance/npx-cold-start.mjs before npm publishes.');
const run = spawnSync(process.execPath, [gate], { cwd: repoRoot, stdio: 'inherit', env });

if (run.error) {
  console.error(`gate-before-publish: could not run the install gate: ${run.error.message}`);
  process.exit(1);
}
if (run.status !== 0) {
  console.error(`gate-before-publish: the install gate failed (exit ${run.status ?? 'signal ' + run.signal}).`);
  console.error('gate-before-publish: REFUSING to publish. Nothing has been sent to the registry.');
}
// A gate that did not pass must stop the publish — and a signalled death is not a pass.
process.exit(run.status ?? 1);
