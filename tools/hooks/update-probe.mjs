#!/usr/bin/env node
// THE WRITER. Ask both package indexes what the latest version is, and put the answer in
// `<homedir>/.bantamkit/update-check.json` where `bantamkit_status` and the SessionStart hook
// can read it without ever touching the network themselves.
//
//   node tools/hooks/update-probe.mjs
//
// IT ASKS THE PACKAGE MANAGERS, NOT A URL (#201, job67 J67-9). Until 0.36.0 this file fetched
// `registry.npmjs.org/bantamkit-mcp/latest` and `pypi.org/pypi/bantamkit/json` by hard-coded URL,
// the shape J65-19 (#135) moved `--update` off: behind a mirror the SessionStart line compared
// against the public index while `--update` compared against the configured one. Now the npm
// half runs `selfupdate.indexCommand` (`npm view … bantamkit-mcp@latest --json`) through
// `selfupdate.fetchIndex` and parses it with `latestFromIndexPayload`, imported from the built
// `runtime-ts/dist/selfupdate.js`; the PyPI half runs the checkout's `.venv` interpreter on
// `bantamkit.selfupdate`'s own `index_command()` / `fetch_index` / `latest_from_index_payload`
// (`pip install --dry-run … --report -`). No third spelling of either question exists here, so
// `npm_config_registry`, `.npmrc`, `PIP_INDEX_URL`, `pip.conf` and the proxies reach the record
// exactly as they reach `--update`. An unbuilt `dist/` writes nothing; a missing `.venv` leaves
// the `pypi` key as found (a failing manager).
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
// AMENDED 2026-09-21 (job62, J62-13): "leaves the other exactly as found" was true of the
// other ENTRY and false of the record. This program also stamped the record's own
// `checked_at` whenever EITHER registry answered — and that field is the fallback that dates
// every entry without a stamp of its own, so a partial success was written down as a clean
// check of both registries. Two things followed, both measured on this branch: the runtime
// reading the half that did NOT answer printed `is current as of <today>` about a number
// from weeks earlier, and the 24 h TTL in `bantamkit-hook.mjs` — which reads exactly this
// field — went quiet for the whole interval instead of retrying the half that failed.
//
// SO THERE ARE TWO STAMPS NOW, AND THE RULE IS ONE SENTENCE: an ENTRY's `checked_at` is when
// THAT registry answered, and the RECORD's `checked_at` is when a writer refreshed the record
// AS A WHOLE. This program is the only writer in the repo that asks both registries, so it is
// the only one that may ever write the record's — and it writes it only when both answered.
// A partial success stamps its own entry, leaves the record's stamp where it was, and is
// therefore still DUE at the next session rather than fresh for a day.
//
// THE COST OF THAT, STATED. A machine that can reach one registry and not the other now
// spawns a detached probe once per SESSION rather than once per day, until the other registry
// answers. That is exactly the cost the both-failed case has always paid — nothing is
// written, so the record stays due — and nothing waits for the child: measured 0.14-0.46 s
// per GET on a good network, in a process given `stdio: 'ignore'` and `unref()`ed. The
// alternative, a "last attempted" field, would mean writing on total failure, which the
// paragraph above rules out for a better reason than this one is worth.
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
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

// --- the two registries -----------------------------------------------------------------
// Each half is asked through the runtime that owns it: npm through `runtime-ts/dist/
// selfupdate.js`, PyPI through `runtime-py`'s `bantamkit.selfupdate` under the checkout's venv.
// THIS program is still the only thing in the repo that asks BOTH — the Node runtime knows only
// npm and the Python runtime knows only PyPI, by construction.

/** The npm package. Equal to `npminstall.PACKAGE`. */
const NPM_PACKAGE = 'bantamkit-mcp';

/** The PyPI distribution. `runtime-py/src/bantamkit/selfupdate.py` — `DISTRIBUTION`. */
const PYPI_DISTRIBUTION = 'bantamkit';

/**
 * The record's two registry keys. `updatecheck.KEY` is `npm` in the Node runtime and `pypi` in
 * the Python one — the `docs/porting.md` divergence row. This writer fills both.
 */
const NPM_KEY = 'npm';
const PYPI_KEY = 'pypi';

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
 * Past `TIMEOUT_MS`, how long the Python process gets to report pip's own timeout before it is
 * killed. `fetch_index` kills pip at the bound; this covers the interpreter's start around it.
 */
const PYTHON_GRACE_MS = 2_000;

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
 * `{updatecheck, selfupdate, npminstall}` from the built Node runtime, or `null`.
 *
 * IMPORTED RATHER THAN RESPELLED. `recordPath()` is where `<homedir>/.bantamkit/
 * update-check.json` is defined, and `indexCommand` / `fetchIndex` / `latestFromIndexPayload`
 * are what `--update` asks npm with; a second spelling here would be a second place for the
 * writer and the readers to disagree. The repo's own `dist/` is the one the hook beside this
 * file already loads its memory component from.
 *
 * An unbuilt `dist/` means this program does nothing, silently — the same answer it gives for a
 * missing `.bantamkit`, and the hook that spawns it already requires that build.
 */
async function runtime() {
  const dist = path.join(REPO, 'runtime-ts', 'dist');
  try {
    // `pathToFileURL`, not a `file://` template: a repo checked out under a path with a space
    // or a `#` in it is the normal case on macOS, and a raw string import would truncate at it.
    const load = (name) => import(pathToFileURL(path.join(dist, name)).href);
    const [updatecheck, selfupdate, npminstall] = await Promise.all([
      load('updatecheck.js'), load('selfupdate.js'), load('npminstall.js'),
    ]);
    if (typeof updatecheck.recordPath !== 'function' || typeof updatecheck.loadRecord !== 'function') return null;
    for (const name of ['indexCommand', 'fetchIndex', 'latestFromIndexPayload', 'installEnvironment']) {
      if (typeof selfupdate[name] !== 'function') return null;
    }
    if (typeof npminstall.keptCli !== 'function') return null;
    return { updatecheck, selfupdate, npminstall };
  } catch {
    return null;
  }
}

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

/** A version string the readers accept, or `null`. */
function accepted(raw) {
  if (typeof raw !== 'string') return null;
  const version = raw.trim();
  return VERSION.test(version) ? version : null;
}

/**
 * The checkout's venv interpreter, or `null`. The PyPI question is `bantamkit.selfupdate`'s and
 * is asked by the interpreter that would install, as `index_command()` says (`sys.executable`).
 */
function venvPython() {
  const candidates = process.platform === 'win32'
    ? [path.join(REPO, '.venv', 'Scripts', 'python.exe')]
    : [path.join(REPO, '.venv', 'bin', 'python')];
  return candidates.find((p) => fs.existsSync(p)) ?? null;
}

/**
 * What the Python runtime's `--update` would compare against, or `null`. Throws for nothing.
 *
 * `index_command()`, `fetch_index()` and `latest_from_index_payload()` are run, not copied, so
 * the argv (`-m pip install --dry-run … --report - bantamkit`), the deadline and the JSON path
 * (`install[0].metadata.version`) are the reference's own. Asynchronous, so it runs while the
 * npm half (synchronous, `spawnSync` inside `fetchIndex`) is asked.
 */
function askPip() {
  const python = venvPython();
  if (python === null) return Promise.resolve(null);
  const code = [
    'import sys',
    'from bantamkit import selfupdate as s',
    'sys.stdout.write(s.latest_from_index_payload(s.fetch_index(s.index_command(), float(sys.argv[1]))))',
  ].join('\n');
  return new Promise((resolve) => {
    let out = '';
    let child;
    try {
      child = spawn(python, ['-c', code, String(TIMEOUT_MS / 1000)], {
        stdio: ['ignore', 'pipe', 'ignore'],
        timeout: TIMEOUT_MS + PYTHON_GRACE_MS,
        windowsHide: true,
      });
    } catch {
      resolve(null);
      return;
    }
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk) => { out += chunk; });
    child.on('error', () => resolve(null));
    child.on('close', (status) => resolve(status === 0 ? accepted(out) : null));
  });
}

/**
 * What the Node runtime's `--update` would compare against, or `null`. Throws for nothing.
 *
 * The environment is the KEPT install's (`~/.bantamkit/mcp`), because that is the install the
 * SessionStart line names and whose `cli.js --update` it tells the operator to run: npm reads
 * the project `.npmrc` relative to the prefix, so asking from anywhere else could read another
 * `registry=`. Without a kept install `installEnvironment` answers `--global`, as it would for
 * that `cli.js`.
 */
async function askNpm({ selfupdate, npminstall }) {
  try {
    const environment = selfupdate.installEnvironment(npminstall.keptCli());
    const body = await selfupdate.fetchIndex(selfupdate.indexCommand(environment), TIMEOUT_MS / 1000);
    return accepted(selfupdate.latestFromIndexPayload(body));
  } catch {
    // A timeout, a refused registry, no npm, a captive portal's HTML: every one of them is the
    // same answer here — this registry did not tell us anything.
    return null;
  }
}

async function main() {
  const rt = await runtime();
  if (rt === null) return;
  const { updatecheck } = rt;

  const file = updatecheck.recordPath();
  const directory = path.dirname(file);
  try {
    if (!fs.statSync(directory).isDirectory()) return;
  } catch {
    // No `<homedir>/.bantamkit` at all. Writing nothing is the answer — see the header.
    return;
  }

  // NO CACHE OUTLIVES THE PROBE. `npm view` and `pip install --dry-run` each keep an HTTP cache
  // under the home directory (`~/.npm`, `~/Library/Caches/pip`). This process is DETACHED and
  // outlives the session that spawned it, so those writes landed in a HOME after its owner had
  // finished with it: the hook tests' throwaway HOMEs were removed while pip was still writing
  // there (`ENOTEMPTY` from `rmSync`, which failed the 0.36.0 publish at phase 1). Nothing here
  // needs a cache — one question per registry per day — so pip runs with none and npm gets a
  // private one under the temp directory, removed on the way out. The registry, proxy and auth
  // config #201 is about are untouched: a cache location is not a registry.
  let npmCache = null;
  try {
    npmCache = fs.mkdtempSync(path.join(os.tmpdir(), 'bantamkit-probe-npm-'));
    process.env.npm_config_cache = npmCache;
  } catch {
    // No private cache: npm falls back to its own default. A cache is not worth a lost answer.
  }
  process.env.PIP_NO_CACHE_DIR = '1';
  try {
    await ask(rt, updatecheck, file, directory);
  } finally {
    if (npmCache !== null) {
      try { fs.rmSync(npmCache, { recursive: true, force: true }); } catch { /* best effort */ }
    }
  }
}

async function ask(rt, updatecheck, file, directory) {
  // BOTH QUESTIONS AT ONCE. They are two independent requests to two hosts, and a detached
  // child that takes 20 s instead of 10 on a captive network is 10 s of a process nobody is
  // waiting for — but it is also 10 s longer that a laptop lid can close on it half-done. pip
  // is spawned first and runs on its own while `fetchIndex` blocks this thread on npm.
  const pending = askPip();
  const npm = await askNpm(rt);
  const pypi = await pending;
  if (npm === null && pypi === null) return;   // nothing learned: the old record stands

  const loaded = updatecheck.loadRecord(file);
  // An UNREADABLE record is replaced rather than merged: there is nothing in it to preserve.
  const payload = loaded.source === updatecheck.SOURCE_RECORD && loaded.record !== null
    ? { ...loaded.record }
    : {};
  const at = stamp();
  // THE RECORD'S STAMP ONLY WHEN THE RECORD AS A WHOLE WAS REFRESHED — see the header. A
  // partial success leaves it exactly where it was, which is what keeps the entry it did not
  // fill dated by the check that actually wrote it, and keeps the hook's TTL due.
  if (npm !== null && pypi !== null) payload.checked_at = at;
  if (npm !== null) payload[NPM_KEY] = { package: NPM_PACKAGE, latest: npm, checked_at: at };
  if (pypi !== null) {
    payload[PYPI_KEY] = { distribution: PYPI_DISTRIBUTION, latest: pypi, checked_at: at };
  }

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
// `process.exit` RATHER THAN FALLING OFF THE END, and that is measured, not tidiness. (The
// measurement below is of the old `fetch`; since #201 the network is in child processes with
// their own deadlines, and the exit still guarantees nothing here outlives the write.) An
// aborted `fetch` rejects on time but does NOT release undici's connection attempt: against
// `192.0.2.1:8080` (RFC 5737, a connect that hangs) the promise settled at 1001 ms and the
// process stayed alive for 10.54 s waiting on the pool's own connect timeout. Everything this
// program produces is already on disk by here — the write is synchronous and there is no
// stdout to flush — so a detached child idling ten more seconds on a dead socket is pure cost.
main().then(() => process.exit(0), () => process.exit(0));
