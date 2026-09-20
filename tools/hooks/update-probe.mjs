#!/usr/bin/env node
// THE WRITER. Ask both package indexes what the latest version is, and put the answer in
// `<homedir>/.bantamkit/update-check.json` where `bantamkit_status` and the SessionStart hook
// can read it without ever touching the network themselves.
//
//   node tools/hooks/update-probe.mjs
//
// WHY THIS IS A SEPARATE PROCESS AND NOT A FUNCTION. Measured 2026-09-19 on this machine
// (`docs/superpowers/specs/2026-09-19-stale-version-signal-design.md`): a cold stdio boot of
// the MCP server is 0.09 s, one registry GET is 0.14-0.46 s on a good network, and 10.0 s
// (`DEFAULT_TIMEOUT_SECONDS`) on a captive one. Asking the index on any path a session waits
// for costs 1.5x to 100x the whole server start. So `bantamkit-hook.mjs` forks this file
// `detached`, `stdio: 'ignore'`, `.unref()`s it and returns; the answer lands for the NEXT
// session. Nothing ever waits for this program.
//
// IT IS SILENT, ALWAYS. No stdout, no stderr, no exit code anyone reads. It is a grandchild of
// a hook, and a hook that produces output the host did not expect is rendered on the user's
// screen as an error (see `bantamkit-hook.mjs`, property 2). A machine that is offline forever
// behaves exactly like one that has never been checked, and THAT state has its own sentence
// (`update: never checked.`), so there is nothing here worth saying out loud.
//
// IT CREATES NO DIRECTORY. `<homedir>/.bantamkit` is made by an install. A probe on a machine
// that has never had one writes nothing rather than deciding where this toolbox's home lives.
// A `.bantamkit` relative to a CWD is a MEMORY STORE (J54-3, `hostinstall.ts:362`), and every
// path here comes from `recordPath()`, which hangs off `homedir()` and nothing else.
//
// IT LEAVES THE PREVIOUS RECORD INTACT ON ANY FAILURE. Both fetches failing writes nothing at
// all — not an empty record, not a `checked_at` with no versions under it — because a record
// that cannot say what the index serves is worse than the absent one it would replace. A
// single registry answering fills its own key and leaves the other exactly as found: npm and
// PyPI are two registries that can disagree at one version number, and job56 shipped a day
// where they did.
//
// THE BYTES ARE `selfupdate.recordUpdate`'s BYTES. `JSON.stringify(payload, null, 2)` plus one
// trailing newline, a temp file in the SAME directory, and `renameSync` — atomic on POSIX and
// on Windows, and never across a filesystem. Two writers (this probe and `--update`) can race
// and lose one key's update; the cost is one delayed check and the next writer fixes it. No
// lock, because a lock is a durable thing to get wrong in exchange for a day of freshness.
//
// THE TTL IS NOT HERE. `bantamkit-hook.mjs` decides once per 24 h whether to run this at all,
// from the `checked_at` of the record it has already loaded for its own line. Running this
// file directly always asks, which is what makes it testable and what an operator debugging a
// stale record would expect.
//
// Layer: `tools/`. One implementation, no port, no conformance case — it is not a runtime
// surface, it is the thing that feeds one.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// --- the two registries -----------------------------------------------------------------
// The npm URL and JSON path are `selfupdate.ts`'s (`INDEX_URL`, top-level `version`); the PyPI
// URL and JSON path are `selfupdate.py`'s (`INDEX_URL`, `info.version`). They are spelled here
// rather than imported because THIS program is the only thing in the repo that asks BOTH — the
// Node runtime knows only npm and the Python runtime knows only PyPI, by construction.

/** The npm package. Equal to `npminstall.PACKAGE`, and imported from it below when it loads. */
const NPM_PACKAGE = 'bantamkit-mcp';

/** The PyPI distribution. `runtime-py/src/bantamkit/selfupdate.py:75` — `DISTRIBUTION`. */
const PYPI_DISTRIBUTION = 'bantamkit';

/**
 * The record's two registry keys. `updatecheck.KEY` is `npm` in the Node runtime and `pypi` in
 * the Python one — the `docs/porting.md` divergence row. This writer fills both.
 */
const NPM_KEY = 'npm';
const PYPI_KEY = 'pypi';

const NPM_URL = process.env.BANTAMKIT_UPDATE_NPM_URL
  || `https://registry.npmjs.org/${NPM_PACKAGE}/latest`;
const PYPI_URL = process.env.BANTAMKIT_UPDATE_PYPI_URL
  || `https://pypi.org/pypi/${PYPI_DISTRIBUTION}/json`;

/**
 * 10 s per registry, matching `selfupdate.DEFAULT_TIMEOUT_SECONDS` on both sides. Nothing waits
 * for this process, so the bound exists to stop a captive portal holding a detached child open
 * forever, not to protect anybody's latency.
 *
 * THE ENV OVERRIDE IS A TEST SEAM AND NOTHING ELSE, the same seam and the same reason as
 * `BANTAMKIT_DREAM_TIMEOUT_MS` in `bantamkit-hook.mjs`: without it the timeout is a constant no
 * test can reach, and a failure path nothing runs is a failure path nobody has seen work.
 */
const TIMEOUT_MS = Number(process.env.BANTAMKIT_UPDATE_TIMEOUT_MS) || 10_000;

/**
 * The same shape check both readers apply to `latest` (`updatecheck.py:_VERSION`,
 * `updatecheck.ts:VERSION`): a first component of digits and dotted parts after it.
 *
 * IT IS HERE SO THIS WRITER CANNOT PRODUCE A RECORD ITS OWN READERS CALL UNREADABLE. A registry
 * that answers `{"version": "nightly"}` would otherwise turn a perfectly good `never checked`
 * into `the update record could not be read`, which is a worse sentence about a machine nothing
 * is wrong with. Not a parser, for `updatecheck`'s reason: a PEP 440 parse is a second, larger
 * thing to reproduce exactly in service of strings neither index serves.
 */
const VERSION = /^[0-9]+(?:\.[0-9A-Za-z_+-]+)*$/;

/**
 * `YYYY-MM-DDTHH:MM:SSZ` — `selfupdate.py`'s `STAMP`, reached the way `selfupdate.ts:stamp()`
 * reaches it. `toISOString()` renders `.000Z` and `datetime.isoformat()` renders `+00:00`, so
 * the two runtimes would write records differing in bytes neither reader cares about; both
 * render this one shape instead, and so does this. `stamp()` is not exported from
 * `selfupdate.ts`, which is the only reason this is four words rather than an import.
 */
function stamp() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/**
 * `{recordPath, loadRecord, SOURCE_RECORD}` from the built Node runtime, or `null`.
 *
 * IMPORTED RATHER THAN RESPELLED. `recordPath()` is where `<homedir>/.bantamkit/
 * update-check.json` is defined; a second spelling here would be a second place for the writer
 * and the readers to disagree about which file this feature lives in. The repo's own `dist/` is
 * the one the hook beside this file already loads its memory component from.
 *
 * An unbuilt `dist/` means this program does nothing, silently — the same answer it gives for a
 * missing `.bantamkit`, and the hook that spawns it already requires that build.
 */
async function reader() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const dist = path.resolve(here, '..', '..', 'runtime-ts', 'dist');
  try {
    // `pathToFileURL`, not a `file://` template: a repo checked out under a path with a space
    // or a `#` in it is the normal case on macOS, and a raw string import would truncate at it.
    const mod = await import(pathToFileURL(path.join(dist, 'updatecheck.js')).href);
    if (typeof mod.recordPath !== 'function' || typeof mod.loadRecord !== 'function') return null;
    return mod;
  } catch {
    return null;
  }
}

/**
 * The version one registry serves, or `null`. Reaches the network; throws for nothing.
 *
 * `pick` is the JSON path, passed in rather than branched on, because the two registries differ
 * in EXACTLY that and nothing else: npm's `/latest` document carries `version` at the top level
 * and PyPI's carries it at `info.version`.
 */
async function ask(url, pick) {
  let text;
  try {
    const response = await fetch(url, {
      headers: { Accept: 'application/json', 'User-Agent': `${NPM_PACKAGE}/update-probe` },
      signal: AbortSignal.timeout(Math.max(1, Math.round(TIMEOUT_MS))),
    });
    if (!response.ok) return null;
    text = new TextDecoder('utf-8').decode(await response.arrayBuffer());
  } catch {
    // A timeout, a refused connection, a DNS failure, a captive portal serving HTML: every one
    // of them is the same answer here — this registry did not tell us anything.
    return null;
  }
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    return null;
  }
  const raw = pick(payload);
  if (typeof raw !== 'string') return null;
  const version = raw.trim();
  return VERSION.test(version) ? version : null;
}

/** npm's `/latest` manifest: `version` at the top level. Measured 2026-09-11, 26 keys. */
const npmVersion = (payload) => (payload && typeof payload === 'object' && !Array.isArray(payload)
  ? payload.version
  : undefined);

/** PyPI's project JSON: `info.version`. */
const pypiVersion = (payload) => (payload && typeof payload === 'object' && !Array.isArray(payload)
  && payload.info && typeof payload.info === 'object' && !Array.isArray(payload.info)
  ? payload.info.version
  : undefined);

async function main() {
  const updatecheck = await reader();
  if (updatecheck === null) return;

  const file = updatecheck.recordPath();
  const directory = path.dirname(file);
  try {
    if (!fs.statSync(directory).isDirectory()) return;
  } catch {
    // No `<homedir>/.bantamkit` at all. Writing nothing is the answer — see the header.
    return;
  }

  // BOTH GETS AT ONCE. They are two independent requests to two hosts, and a detached child
  // that takes 20 s instead of 10 on a captive network is 10 s of a process nobody is waiting
  // for — but it is also 10 s longer that a laptop lid can close on it half-done.
  const [npm, pypi] = await Promise.all([
    ask(NPM_URL, npmVersion),
    ask(PYPI_URL, pypiVersion),
  ]);
  if (npm === null && pypi === null) return;   // nothing learned: the old record stands

  const loaded = updatecheck.loadRecord(file);
  // An UNREADABLE record is replaced rather than merged: there is nothing in it to preserve.
  const payload = loaded.source === updatecheck.SOURCE_RECORD && loaded.record !== null
    ? { ...loaded.record }
    : {};
  payload.checked_at = stamp();
  if (npm !== null) payload[NPM_KEY] = { package: NPM_PACKAGE, latest: npm };
  if (pypi !== null) payload[PYPI_KEY] = { distribution: PYPI_DISTRIBUTION, latest: pypi };

  let body;
  try {
    body = `${JSON.stringify(payload, null, 2)}\n`;
  } catch {
    return;
  }
  const temporary = path.join(directory, `.update-check-${process.pid}-${Date.now()}.json`);
  try {
    fs.writeFileSync(temporary, body, 'utf8');
    fs.renameSync(temporary, file);
  } catch {
    try {
      fs.unlinkSync(temporary);
    } catch {
      /* the temp file never existed, or is already gone: either way there is nothing to do */
    }
  }
}

// EVERY failure ends here, unsaid. `exitCode` is left at 0 and both streams stay empty: the
// hook that spawned this passed `stdio: 'ignore'` and read neither, and an operator running it
// by hand learns what happened by looking at the record, which is the only thing it produces.
//
// `process.exit` RATHER THAN FALLING OFF THE END, and that is measured, not tidiness. An
// aborted `fetch` rejects on time but does NOT release undici's connection attempt: against
// `192.0.2.1:8080` (RFC 5737, a connect that hangs) the promise settled at 1001 ms and the
// process stayed alive for 10.54 s waiting on the pool's own connect timeout. Everything this
// program produces is already on disk by here — the write is synchronous and there is no
// stdout to flush — so a detached child idling ten more seconds on a dead socket is pure cost.
main().then(() => process.exit(0), () => process.exit(0));
