#!/usr/bin/env node
/**
 * The Claude Code hook adapter — A SHIM, since 2026-09-20 (job61, J61-2). The adapter itself
 * is `runtime-ts/src/hookadapter.ts`, and this file is four lines of delegation to it.
 *
 * WHY IT MOVED. This file was the adapter, all 1407 lines of it, and it was unreachable from
 * the shipped product: `tools/` is not in the npm package. MEASURED at 0.35.3 with
 * `npm pack --dry-run` — the tarball carries 174 files, `runtime-ts/package.json` declares
 * `files: ["dist","assets"]`, and nothing in the printed manifest matches `hook`. So an
 * operator who installed bantamkit the only way it is published (`npx bantamkit-mcp`) had no
 * adapter on disk at all, and the registration line in `docs/hooks.md` could not be written
 * without a checkout. `bantamkit-mcp --hook` is the surface that closes that, and the code had
 * to live under `runtime-ts/src/` to reach `dist/` and therefore the tarball.
 *
 * WHY THIS FILE STILL EXISTS RATHER THAN BEING DELETED. It is the command in every
 * `~/.claude/settings.json` that already registers bantamkit's hooks, in `tools/hooks/
 * install.mjs`, and in the probes beside it. Deleting it would silently unhook every machine
 * that has it registered. It is a SHIM and not a second copy: there is exactly one adapter,
 * so the two cannot drift.
 *
 * IT REQUIRES A BUILT `runtime-ts/dist`, which is what it always required — the old file
 * imported `runtime-ts/dist/memory/*.js` on every arm. `npm run build` in `runtime-ts`.
 *
 * Registration and the event list: `docs/hooks.md`.
 */
const adapter = new URL('../../runtime-ts/dist/hookadapter.js', import.meta.url);
const { runHook, logHookFailure } = await import(adapter.href);

// The same last line the adapter has always had: every failure is LOGGED and swallowed, and
// the process exits 0 whatever happened, because a hook that throws is rendered by the host
// as an error on the user's screen.
await runHook().catch((e) => logHookFailure(e));
process.exit(0);
