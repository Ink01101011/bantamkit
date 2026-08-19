// The ORACLE's configuration, pinned OUTSIDE the agent's write surface.
//
// RB-P72 (docs/eval.md) is the open, escalation-class finding this file closes
// forward: the oracle used to auto-discover its configuration from its own cwd,
// `<worktree>/packages/shared`, which is exactly the directory the harness's
// committed tool roster can WRITE. A single WRITE of `vitest.config.ts` there
// produced `exit 0` with every declared guard reporting clean. Measured beyond
// what RB-P72 records: `vitest.workspace.ts` and `vite.config.ts` do the same,
// and reach exit 0 at 15 of 141 tests.
//
// This file lives in bantamkit, a DIFFERENT repository from the workload the
// roster can write, and `2026-08-18-loop-harness.py` names it by absolute path
// on the oracle's argv (`--config`). `_resolve` -- the roster's path check --
// cannot produce a path outside `realpath(<worktree>/packages/shared)`, so no
// WRITE the agent can issue names this file.
//
// AMENDMENT TO BAR SECTION 1.3, which pre-registered the oracle command as
// `./node_modules/.bin/vitest run` from `packages/shared`. The command is now
// that command plus `--config <this file>`. The amendment BINDS RUNS MADE AFTER
// IT and makes no claim whatever about J7's committed arms: those rows ran under
// an unpinned oracle and always will have. RB-P72's "deliberately not fixed"
// disposition stands as J7's.
//
// `root` is `process.cwd()`, not a path baked in here, for two reasons. It makes
// the file independent of which throwaway worktree the harness was handed, and
// -- load-bearing -- it is what stops a `root` written into the worktree from
// re-pointing the run. Measured against vitest 2.1.9 (the version resolved by
// `packnplan-mono`'s `^2.0.0` on this machine): with this config pinned, vitest
// neither merges nor re-discovers a second config, including a
// `vitest.workspace.ts`. That precedence behaviour is a property of THAT VERSION
// and is recorded, not assumed.
//
// The include/exclude below are not a new scope: they are the scope vitest
// auto-discovered before, restated explicitly. Both baselines are the controls
// that say so -- pristine `10 passed (10)` / `141 passed (141)` exit 0, and
// DEFECT-SET-5 `5 failed | 5 passed (10)` / `7 failed | 134 passed (141)` exit 1
// -- and if either moves, this file is wrong, not the baseline.

// A PLAIN OBJECT, and deliberately not `defineConfig` from "vitest/config".
// `defineConfig` is a typing helper with no runtime effect, and importing it
// here costs two things that were MEASURED, not assumed:
//   * an `.mts`/`.mjs` spelling of this file cannot resolve `vitest` at all
//     ("Cannot find package 'vitest'"), because this directory has no
//     `node_modules` anywhere up its ancestry -- which is the whole point of
//     where it lives;
//   * the `.ts` spelling that DOES resolve it makes vitest 2.1.9 load Vite's
//     CJS Node API, which prints "The CJS build of Vite's Node API is
//     deprecated" ON STDERR -- and `run_oracle` returns `stdout + stderr`, so
//     that line would land in the agent's ORACLE tool output. Adding a line to
//     what the agent reads is a TASK change, not an instrument change.
// With no import there is no warning and no resolution to do, and the oracle's
// agent-visible stream is byte-identical to the unpinned oracle's: CANON-1
// sha256 of the pristine and of the DEFECT-SET-5 output both match `ba7a38b`'s
// exactly.
export default {
  root: process.cwd(),
  test: {
    include: ["src/**/*.test.ts"],
    exclude: ["**/node_modules/**"],
  },
};
