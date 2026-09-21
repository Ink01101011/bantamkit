/**
 * Ask the package index what the latest version is, and update when it differs — `--update`.
 *
 * THE PORT OF `runtime-py/src/bantamkit/selfupdate.py`, AND THE SENTENCES ARE COPIED FROM IT
 * BYTE FOR BYTE. That module's docstring carries the whole argument — why `docs/roadmap-agent-
 * stack.md` AS-7's "do NOT build `--update`" was reversed by the user on 2026-09-11, and why
 * three of AS-7's four reasons survive the reversal as facts that decide what the flag PRINTS
 * rather than whether it exists. It is not restated here; read it there. What belongs HERE is
 * the part that could not be copied.
 *
 * EXACTLY THREE THINGS DIFFER FROM THE REFERENCE, and each is a genuinely different object
 * rather than a different spelling of one object:
 *
 *   1. THE URL AND THE JSON PATH. PyPI answers `pypi.org/pypi/bantamkit/json` and the version
 *      sits at `info.version`; the npm registry answers `registry.npmjs.org/bantamkit-mcp/
 *      latest` and it sits at the top level as `version`. Measured 2026-09-11 against the real
 *      registry: the `/latest` document is the manifest of the `latest` dist-tag, 26 keys, and
 *      `version` is `0.30.0`.
 *   2. THE COMMAND. `pip install --upgrade` there; `npm install` here, and WHICH `npm install`
 *      is a measured question — see `upgradeCommand`.
 *   3. THE FOUR `ROUTES` SENTENCES, which name those commands and the things they update.
 *      `ephemeral`'s is not a translation of the reference's and must not be made into one:
 *      see the note on that row.
 *
 * `COMPARISON`, `UP_TO_DATE`, `AHEAD`, `UPDATING`, `PRINTED`, `UPDATED`, `RESTART`, `NO_ROUTE`,
 * `TIMED_OUT`, `UNREACHABLE`, `NOT_A_VERSION`, `COMMAND_FAILED`, `SHAPE_UNKNOWN`, `NOT_JSON`,
 * `NO_VERSION_FIELD` and `NO_OUTPUT` are byte-for-byte identical to the reference's. They
 * deliberately say `bantamkit-mcp` and never a package name: the PyPI distribution is
 * `bantamkit`, the npm package is `bantamkit-mcp`, and only the COMMAND the operator typed is
 * the same word on both sides — so naming the command is what keeps these sentences identical
 * instead of ruled, and still names something true.
 *
 * NO NEW DEPENDENCY. The HTTP call is the platform's own `fetch` (Node >= 20, which
 * `package.json` already requires) with `AbortSignal.timeout`; the version comparison, the
 * `shlex.join` rendering and the `str.format` substitution are hand-rolled here in the
 * `pyyaml.ts` / `pyjson.ts` / `pyargparse.ts` idiom.
 *
 * Layer 5 (Composition): this module reaches the network and shells out to an installer.
 * `cli.ts` is the ONLY module in `src/` that imports it — asserted structurally in
 * `test/selfupdate.test.mjs` — and it calls `runUpdate` from the flag and returns before a
 * memory store or a transport exists, the same shape `--assets-root` and `--install` use.
 */
import { readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { currentInstall, Undetermined } from './mcp/identity.js';
import { compareVersions, keptCli, keptManifest, keptPrefix, PACKAGE, runInstaller, shlexJoin } from './npminstall.js';
import { KEY as RECORD_KEY, loadRecord, recordPath, SOURCE_RECORD } from './updatecheck.js';

// `PACKAGE`, `shlexJoin` and `runInstaller` moved to `npminstall.ts` in job51 so `--install` can
// share the npm spawner without importing this module (see that file's header). Re-exported so
// this module's surface — and every test importing these from `dist/selfupdate.js` — is unchanged.
// `compareVersions` followed in J51-9a, for the same reason: `--install` from an `npx` cache orders
// the kept install's version against its own, and must not import this module to do it.
export { compareVersions, PACKAGE, runInstaller, shlexJoin };

/**
 * The command the operator typed, on BOTH runtimes. Not the package name — see the module
 * docstring: PyPI has `bantamkit`, npm has `bantamkit-mcp`, and only this word is the same on
 * both, so only this word can appear in a sentence the reference and this file share verbatim.
 */
export const PROGRAM = 'bantamkit-mcp';

/**
 * The one URL this toolbox ever fetches. Divergent by construction (`INDEX_URL`).
 *
 * `/latest` and not the full packument: the packument carries every version ever published and
 * grows without bound, and the question here is one string. Measured 2026-09-11 — this document
 * is 26 keys and carries `version` at the top level.
 */
export const INDEX_URL = `https://registry.npmjs.org/${PACKAGE}/latest`;

/**
 * Explicit, and short enough that a person who typed the flag does not think it hung.
 * AS-7(3): the network is not on any other path here, so nothing else inherits this.
 */
export const DEFAULT_TIMEOUT_SECONDS = 10;

/**
 * What stands in for an installer that printed nothing, so the report has ONE shape rather
 * than a line that is sometimes there. A conditional line is a second thing to port.
 */
export const NO_OUTPUT = '(nothing)';

// --- the sentences ------------------------------------------------------------------
// Every one of these was copied out of `runtime-py/src/bantamkit/selfupdate.py`, which is
// where they are DEFINED. Changing one is a change to both runtimes and to the conformance
// suite, never to this file alone.

/**
 * Line 1 of every report, and the opening of the no-route refusal. It carries BOTH numbers
 * because "up to date" without them is unfalsifiable by the person reading it.
 */
export const COMPARISON = '{program} {installed} is installed; the package index has {latest}.';

/** The user asked for this word specifically: "ถ้า match ให้แสดงคำ uptodate". */
export const UP_TO_DATE = 'up to date.';

/**
 * The registry BEHIND the installed version. A real state, not a curiosity: a checkout build,
 * or a release that has not been published yet, both land here.
 */
export const AHEAD =
  'the installed version is ahead of the package index; there is nothing to update to.';

/** What the command is about to run. The command itself is divergent; this line is not. */
export const UPDATING = 'updating from the package index: {command}';

/** The installer's own words, never summarised. Both runtimes print the block the same way. */
export const PRINTED = 'the command printed:';

export const UPDATED = 'updated {program} from {installed} to {latest}.';

/** AS-7(1), measured. This is the line that makes the success true rather than plausible. */
export const RESTART =
  'restart the server: a running {program} keeps serving the code it loaded at startup, ' +
  'so bantamkit_status will report {installed} until the host reconnects.';

// --- the refusals -------------------------------------------------------------------
// Thrown as `UpdateRefused`; `runUpdate` prints `error: <message>` on stderr and exits 1.
// Exit 1 and not 0 for ALL of them, including the no-route one: an operator who typed
// `--update` asked for an update, and a command that exits 0 having changed nothing is the
// J46-4 defect. Exit 1 and not 2, because argparse already owns 2 for a usage error and
// `--update` is not one.

export const NO_ROUTE =
  '{program} {installed} is installed and the package index has {latest}, but this is a ' +
  '{shape} install, which --update will not touch. {route}';

export const TIMED_OUT =
  'the package index did not answer within {timeout} seconds; --update needs the network, ' +
  'and nothing was changed.';

export const UNREACHABLE =
  'the package index could not be reached: {reason}; --update needs the network, and ' +
  'nothing was changed.';

export const NOT_A_VERSION =
  'the package index answered, but not with a version for {program}: {why}; nothing was ' +
  'changed.';

/**
 * Multi-line on purpose. The installer's output is the only thing that says WHY it failed,
 * and a refusal that swallowed it would send the operator to re-run the command by hand.
 */
export const COMMAND_FAILED =
  'the update command exited {code}: {command}\n' +
  '{program} {installed} is still installed; nothing was changed.\n' +
  '{printed}\n' +
  '{output}';

/**
 * The install shape itself could not be derived — `identity.Undetermined`, which is what an
 * origin that is neither an index nor a path on this machine raises (`git+https://…`). That
 * exception already carries the operator's next step, so this sentence quotes it rather than
 * paraphrasing it, and refuses rather than picking a route.
 */
export const SHAPE_UNKNOWN =
  '--update could not tell how this install was made, so it will not guess an update ' +
  'route: {reason}';

/**
 * The two ways a well-formed HTTP response can still not carry a version, as the `{why}` of
 * `NOT_A_VERSION`. Both runtimes ask a different URL and read a different JSON path, so what
 * is compared is that the same two failures produce the same two sentences.
 */
export const NOT_JSON = 'the response is not JSON';
export const NO_VERSION_FIELD = 'the response carries no version string';

/**
 * The fallthrough for a shape word `ROUTES` has never heard of — `INSTALL_SHAPES` growing a
 * sixth word. Not divergent: it names no package manager, so it is the reference's sentence.
 */
export const NO_RECORDED_ROUTE =
  'There is no recorded update route for a {shape} install, so --update will not guess one.';

/**
 * Per shape, what the real update route is — the answer to "then how DO I update this?".
 * DIVERGENT BY CONSTRUCTION and registered in `docs/porting.md` by J46-31: the reference's
 * rows name pip and a Python tree; these name npm and a BUILT one.
 *
 * `registry` is absent on purpose, exactly as it is there. It is the one shape that HAS a
 * route through this flag, so a sentence telling its operator to go do it by hand would never
 * be reachable, and an unreachable sentence is one more thing for nobody to check.
 *
 * `{command}` is the SAME string `upgradeCommand` builds and `UPDATING` prints, never a second
 * spelling of it — `local-file` is the one row whose advice is an actual command, and the
 * README's measured fix for the real incident is exactly this: `npm i --prefix
 * ~/.local/share/bantamkit-mcp bantamkit-mcp@latest`.
 *
 * `linked` and `checkout` BOTH say "rebuild it". That is not padding and it is the difference
 * from the reference that matters most on this side: an editable Python install serves the
 * `.py` files a `git pull` just changed, and a Node install serves `dist/`, which is build
 * output. `README.md#updating`'s checkout row already says `git pull && npm ci && npm run
 * build`, and a route that stopped at `git pull` would be a remedy that changes nothing.
 *
 * `ephemeral` IS NOT A TRANSLATION OF THE REFERENCE'S ROW, and making it one would make it
 * false. There it says "the next run fetches {latest} by itself", which is true of a `pipx
 * run` environment; here the shape is an `npx` cache, and `README.md#silent-version-float`
 * measured that `npx -y bantamkit-mcp` RESOLVES `latest` ONCE AND CACHES IT — two people with
 * byte-identical config can be running builds resolved weeks apart. So this row is true of the
 * cache that actually exists rather than of a fresh resolve that does not happen, and it names
 * the only thing that changes it: the spec on the host's command line.
 *
 * Since J51-5 this row is reached only when there is NO kept install (`keptInstall`): with one,
 * `runUpdate` updates that install instead, so the sentence stays true of what it describes.
 */
export const ROUTES: Record<string, string> = {
  'local-file':
    'It was installed from the file {source}, which is not the package index: reinstall it ' +
    'from that path, or run {command} to move it onto the index.',
  linked:
    'It is a linked install of the tree at {source}: update that tree where it was cloned, ' +
    'with git pull, and rebuild it — dist/ is build output, so a pull alone changes nothing.',
  checkout:
    'It is running out of a source tree at {source} that no installer recorded: update that ' +
    'tree where it was cloned, with git pull, and rebuild it — dist/ is build output, so a ' +
    'pull alone changes nothing.',
  ephemeral:
    'It is running from an npx cache that is discarded after the run and never updated in ' +
    'place, so there is nothing here to update: the next run serves the same cached ' +
    '{installed} unless the host command line asks for {package}@latest.',
};

/**
 * A refusal carrying the sentence the operator should read. Never a stack trace.
 *
 * The same contract `hostinstall.InstallError` has, and for the same reason: `--update` can
 * fail for four reasons that are all somebody else's to fix, and a stack trace names none.
 */
export class UpdateRefused extends Error {}

/**
 * The clock ran out. THE CONTRACT BETWEEN `fetchIndex` AND `update` IS THIS TYPE.
 *
 * On the reference side the distinction is `TimeoutError` vs any other `OSError`, and the
 * ORDER of the two `except` clauses is load-bearing because `TimeoutError` IS an `OSError`.
 * The Node hazard is the same one with different names, and it is MEASURED (Node v25.2.1):
 * an `AbortSignal.timeout` abort arrives as a `DOMException` whose `name` is `'TimeoutError'`
 * — and `DOMException` IS `instanceof Error`. So a `catch` that tested `instanceof Error`
 * first would swallow every timeout into the unreachable arm, which names the wrong problem
 * and sends the operator to check a network that is working. `test/selfupdate.test.mjs` pins
 * both halves: that this class is an `Error`, and that the real abort reason is one too.
 */
export class IndexTimeout extends Error {}

/**
 * The install shape and the path it can be pointed at, as `--update` needs them.
 *
 * DELIBERATELY NOT `identity.Install`. That record carries `sourceReason`, which is the
 * `build_identity` wire shape's business and not this flag's; and this keeps the whole
 * decision table testable by constructing a shape directly, including shape words this
 * runtime would never derive. `runUpdate` does the one-line translation.
 */
export interface Origin {
  readonly shape: string;
  readonly source: string;
}

/**
 * WHERE an `npm install` would have to point to replace THIS copy, and whether that is the
 * global tree. Not a second install-shape detector — it derives no shape and answers no shape
 * question; the shape comes from `currentInstall()` and from nowhere else.
 *
 * `global` IS A RECORD, NOT A GUESS, AND THE DIFFERENCE IS DESTRUCTIVE. Measured on this
 * machine 2026-09-11 with npm 11.6.2:
 *
 *   - `npm install --prefix <dir> <pkg>` installs into `<dir>/node_modules` and, when `<dir>`
 *     already has the `package.json` npm itself wrote there, leaves every sibling package
 *     alone.
 *   - with NO `package.json` in `<dir>` — which is exactly the global tree's shape, confirmed
 *     at `/Users/kktest/.local/share/mise/installs/node/25.2.1/lib`, where `node_modules` holds
 *     `@shopify`, `eas-cli` and `npm` and there is no `package.json` beside it — the same
 *     command PRUNES the siblings. A fixture with two packages came back with one.
 *
 * So the presence of that `package.json` is the discriminator, and it is a file npm writes for
 * a `--prefix` install and does not write for a global one. Getting this backwards would make
 * `--update` delete a developer's other global CLIs, which is worse than every failure this
 * flag has a sentence for.
 *
 * `root` is `''` when no `node_modules` ancestor exists at all. That arm cannot be reached
 * from the `registry` shape — `deriveInstall` answers `registry` only from inside a
 * `node_modules` — and the pairing is pinned in `test/selfupdate.test.mjs` rather than left as
 * a comment, because the global command it produces needs no root and would otherwise be
 * silently plausible.
 */
export interface Environment {
  readonly root: string;
  readonly global: boolean;
}

export function installEnvironment(
  runningFile: string = fileURLToPath(import.meta.url),
): Environment {
  let here = dirname(resolve(runningFile));
  for (;;) {
    if (basename(here) === 'node_modules') {
      const root = dirname(here);
      let owned = false;
      try {
        readFileSync(join(root, 'package.json'));
        owned = true;
      } catch {
        owned = false;
      }
      return { root, global: !owned };
    }
    const parent = dirname(here);
    if (parent === here) return { root: '', global: true };
    here = parent;
  }
}

/**
 * `str.format` over the one substitution shape these sentences use — `{name}` and nothing else.
 *
 * A missing key THROWS, the way `str.format` raises `KeyError`, rather than leaving `{name}`
 * in the text: an unsubstituted placeholder reaching the operator is a defect the reference's
 * suite asserts against by name, and a silent passthrough is how one ships.
 */
export function fill(template: string, values: Readonly<Record<string, string | number>>): string {
  return template.replace(/\{(\w+)\}/g, (_whole, key: string) => {
    if (!(key in values)) throw new Error(`no value for {${key}} in a --update sentence`);
    return String(values[key]);
  });
}

/**
 * The version string out of the registry's JSON, or a named refusal. Pure — no network here.
 *
 * SPLIT FROM THE FETCH SO THE GARBAGE CASE IS TESTED THROUGH THE REAL PARSER, exactly as the
 * reference splits it: a test that stubbed a parsed version would prove nothing about what
 * happens when a captive-portal login page comes back with a 200, which is the realistic shape
 * of "the index answered and it was not the index".
 *
 * THE JSON PATH IS THE DIVERGENCE. PyPI nests it at `info.version`; `registry.npmjs.org/<pkg>/
 * latest` carries it at the top level. Both refusals below are the same two sentences.
 */
export function latestFromIndexPayload(text: string): string {
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new UpdateRefused(fill(NOT_A_VERSION, { program: PROGRAM, why: NOT_JSON }));
  }
  let version = '';
  if (typeof payload === 'object' && payload !== null && !Array.isArray(payload)) {
    const raw = (payload as Record<string, unknown>)['version'];
    if (typeof raw === 'string') version = raw.trim();
  }
  if (version === '') {
    throw new UpdateRefused(fill(NOT_A_VERSION, { program: PROGRAM, why: NO_VERSION_FIELD }));
  }
  return version;
}

/** The User-Agent's version half, or nothing. A header, never an output — never a refusal. */
function packageVersion(): string {
  try {
    const manifest = JSON.parse(
      readFileSync(new URL('../package.json', import.meta.url), 'utf8'),
    ) as { version?: unknown };
    return typeof manifest.version === 'string' ? manifest.version : '0';
  } catch {
    return '0';
  }
}

/**
 * The ONLY network call in this runtime. One request, one timeout, two failure words.
 *
 * THE PLATFORM'S `fetch`, NOT A DEPENDENCY. `package.json` declares exactly one runtime
 * dependency and the pure-node `npx` install is a standing ruling, so the HTTP client is the
 * one Node ships (>= 18, and `engines` already requires >= 20) and the deadline is
 * `AbortSignal.timeout`, which is the same object the abort arrives as.
 *
 * THE CONTRACT WITH `update` IS THE EXCEPTION TYPE — see `IndexTimeout`. Measured on Node
 * v25.2.1 against a local socket that accepts and never answers: the rejection is a
 * `DOMException` named `TimeoutError`. Everything else is a `TypeError: fetch failed` whose
 * `cause` carries the sentence worth printing — `connect ECONNREFUSED 127.0.0.1:49999`,
 * `getaddrinfo ENOTFOUND …` — so the cause's message is what `UNREACHABLE` interpolates and
 * the bare "fetch failed" never reaches an operator.
 *
 * A non-2xx is an `Error` and not a timeout, the way the reference turns `HTTPError` into a
 * plain `OSError`; and the body is decoded leniently, because a body that is not UTF-8 is not
 * a version either and should be refused BY NAME in `latestFromIndexPayload`.
 */
export async function fetchIndex(
  url: string = INDEX_URL,
  timeout: number = DEFAULT_TIMEOUT_SECONDS,
): Promise<string> {
  const deadline = AbortSignal.timeout(Math.max(1, Math.round(timeout * 1000)));
  try {
    const response = await fetch(url, {
      headers: { Accept: 'application/json', 'User-Agent': `${PROGRAM}/${packageVersion()}` },
      signal: deadline,
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} ${response.statusText}`.trimEnd());
    }
    const raw = await response.arrayBuffer();
    return new TextDecoder('utf-8').decode(raw);
  } catch (e) {
    if (e instanceof IndexTimeout) throw e;
    if (e instanceof Error && e.name === 'TimeoutError') throw new IndexTimeout(e.message);
    const cause = (e as { cause?: unknown }).cause;
    const detail = cause instanceof Error && cause.message !== '' ? cause.message : null;
    throw new Error(detail ?? (e instanceof Error ? e.message : String(e)));
  }
}

/**
 * What a `registry` install upgrades with, ON THE TREE IT IS ACTUALLY IN.
 *
 * The reference's reason transfers exactly: "the server may be running from a venv whose `pip`
 * is not the one first on `PATH`, and upgrading the wrong environment is a failure that
 * reports success." Here the wrong environment is a different `node_modules`, and `--prefix` is
 * npm's own way of naming the right one.
 *
 * `--global` FOR THE GLOBAL TREE AND NEVER `--prefix`. See `installEnvironment`: on a tree with
 * no `package.json` beside `node_modules`, `npm install --prefix` prunes every sibling package.
 * Both arms are the rows `README.md#updating` already documents.
 *
 * `@latest` IS NOT DECORATION. `npm install <pkg>` in a tree that already declares `<pkg>`
 * satisfies the existing range rather than moving it, which is a command that exits 0 having
 * changed nothing — the J46-4 defect, arrived at through npm's semantics rather than through
 * this code's.
 */
export function upgradeCommand(environment: Environment): string[] {
  if (environment.global) return ['npm', 'install', '--global', `${PACKAGE}@latest`];
  return ['npm', 'install', '--prefix', environment.root, `${PACKAGE}@latest`];
}


/**
 * `10` rather than `10.0`, because the sentence is read by a person, not parsed.
 *
 * The reference spells this out so that Node's default rendering of a whole number is what
 * both sides print, which is what keeps `TIMED_OUT` byte-identical instead of ruled. Here it
 * is the identity function on a number, and it exists so the pairing is visible from both
 * files rather than only from one.
 */
export function seconds(timeout: number): string {
  return String(timeout);
}

export interface UpdateOptions {
  readonly fetch?: (url: string, timeout: number) => Promise<string> | string;
  readonly installer?: (command: string[]) => [number, string];
  readonly url?: string;
  readonly timeout?: number;
  readonly environment?: Environment;
  /**
   * Which install is running, as `runUpdate` asks it. Default: `currentInstall()`, and nothing
   * else in `src/` passes one. A seam so the `ephemeral` arms are reachable from a test running
   * in a checkout; `update()` itself never reads it.
   */
  readonly install?: () => { readonly shape: string; readonly source: string | null };
}

/** The kept install `--update` targets from an `npx` cache: its version and its `--prefix` tree. */
export interface KeptInstall {
  readonly version: string;
  readonly environment: Environment;
}

/**
 * The kept install `--install` left at `keptPrefix()` (J51-4), or `null` when there is none to
 * patch. A local read and nothing more — no network, no spawn.
 *
 * WHY `--update` LOOKS FOR IT. From an `npx` cache there is nothing to update in place, but the
 * hosts do not launch the cache: `--install` recorded the kept install's `cli.js`. So an operator
 * who types `npx -y bantamkit-mcp@latest --update` is asking about THAT install, and it is a
 * `--prefix` tree `npm install --prefix` updates in place (measured: 0.32.1 to 0.33.0, exit 0).
 *
 * THERE IS ONE ONLY WHEN ALL OF THIS HOLDS, and anything short of it is `null` — which leaves
 * today's `ephemeral` refusal exactly as it was:
 *
 *   - the kept manifest (`keptManifest`, never respelled) is readable JSON with a non-blank
 *     string `version`;
 *   - `installEnvironment` on the kept `cli.js` says it is NOT the global tree. npm writes a
 *     `package.json` at a `--prefix` it installed into, so a real kept install always passes.
 *     One without it would render `npm install --global`, which updates some other install and
 *     reports success about this one — worse than refusing.
 */
export function keptInstall(prefix: string = keptPrefix()): KeptInstall | null {
  let version: unknown;
  try {
    version = (JSON.parse(readFileSync(keptManifest(prefix), 'utf8')) as { version?: unknown }).version;
  } catch {
    return null;
  }
  if (typeof version !== 'string' || version.trim() === '') return null;
  const environment = installEnvironment(keptCli(prefix));
  if (environment.global) return null;
  return { version, environment };
}

/**
 * The whole flag: ask the index, compare, and act — or refuse, by name.
 *
 * THE TWO SEAMS ARE `fetch` AND `installer`, and they are options with real defaults rather
 * than module bindings a test rewrites. A test that reached the registry would fail on a plane
 * and pass for the wrong reason off a cache; a test that ran a real installer would rewrite the
 * developer's own `node_modules` mid-suite. Both substitutes are handed in here, so every arm
 * below is reachable offline and the npm command is CAPTURED, never run.
 *
 * THE INDEX IS ASKED BEFORE THE SHAPE IS JUDGED, and that order is the reference's and is
 * deliberate. The user asked the flag to go and check the latest version; an operator on a
 * checkout five releases behind is owed that number even though this flag will not be the thing
 * that installs it. The shape decides the ACTION, never whether the question is asked.
 */
/**
 * The `checked_at` stamp's shape, spelled rather than defaulted.
 *
 * `toISOString()` renders `.000Z` and CPython's `isoformat()` renders `+00:00`, so a record
 * written by the two runtimes would differ in bytes neither reader cares about. The reference
 * formats `%Y-%m-%dT%H:%M:%SZ`; this strips the milliseconds to reach the same shape.
 */
function stamp(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/**
 * Put the version this flag just fetched into the record `bantamkit_status` reads.
 *
 * THE PORT OF `selfupdate.record_update`. Its docstring carries the argument and is not
 * restated: no second network call and no new failure mode (`update` already holds `latest`),
 * no directory is ever created, the other runtime's key is left exactly as found, and the
 * write goes through a temp file and a rename so no reader sees half a record. That includes
 * its AMENDED 2026-09-21 clause — this writer stamps its OWN entry's `checked_at` and never
 * the record's, because the record's stamp means "a writer refreshed the whole record" and
 * `--update` holds one registry's answer by construction.
 *
 * WHY THE WRITER IS HERE AND NOT IN `updatecheck.ts`. That module is the READER, and
 * `test/updatecheck.test.mjs` gates its source against `writeFileSync`, `renameSync`,
 * `mkdirSync` and the rest by name — the same claim `test_updatecheck.py` makes over the
 * reference's AST. The split is structural on both sides, so a future reader cannot grow a
 * write by accident. `updatecheck.js` is imported here for the PATH and the KEY, which is the
 * direction that keeps one spelling of each.
 *
 * `renameSync` is atomic on POSIX and on Windows, and the temp file is made in the SAME
 * directory so the rename is never across a filesystem.
 *
 * RETURNS whether it wrote, and THROWS FOR NOTHING. A failed write must not turn a successful
 * `--update` into a failure: the operator's install was updated either way, and the worst case
 * is a status line that still says `never checked`.
 */
export function recordUpdate(latest: string, now?: string): boolean {
  const path = recordPath();
  const directory = dirname(path);
  try {
    if (!statSync(directory).isDirectory()) return false;
  } catch {
    // No `<homedir>/.bantamkit` at all: an install makes that directory, and `--update` does
    // not get to decide where this toolbox's home lives. Writing nothing is the answer.
    return false;
  }
  const { source, record } = loadRecord(path);
  // An UNREADABLE record is replaced rather than merged: there is nothing in it to preserve.
  const payload: Record<string, unknown> =
    source === SOURCE_RECORD && record !== null ? { ...record } : {};
  const at = now ?? stamp();
  payload[RECORD_KEY] = { package: PACKAGE, latest, checked_at: at };
  const temporary = join(directory, `.update-check-${process.pid}-${Date.now()}.json`);
  try {
    writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
    renameSync(temporary, path);
  } catch {
    try {
      unlinkSync(temporary);
    } catch {
      /* the temp file never existed, or is already gone: either way there is nothing to do */
    }
    return false;
  }
  return true;
}

export async function update(
  installed: string,
  origin: Origin,
  options: UpdateOptions = {},
): Promise<string> {
  const ask = options.fetch ?? fetchIndex;
  const installer = options.installer ?? runInstaller;
  const url = options.url ?? INDEX_URL;
  const timeout = options.timeout ?? DEFAULT_TIMEOUT_SECONDS;
  const environment = options.environment ?? installEnvironment();

  let body: string;
  try {
    body = await ask(url, timeout);
  } catch (e) {
    // ORDER IS LOAD-BEARING: `IndexTimeout` IS an `Error`, exactly as `TimeoutError` IS an
    // `OSError` in the reference. Swap these two and every timeout reads as "could not be
    // reached", which names the wrong problem and nobody notices.
    if (e instanceof IndexTimeout) {
      throw new UpdateRefused(fill(TIMED_OUT, { timeout: seconds(timeout) }));
    }
    if (e instanceof Error) throw new UpdateRefused(fill(UNREACHABLE, { reason: e.message }));
    throw e;
  }

  const latest = latestFromIndexPayload(body);

  // THE RECORD IS WRITTEN HERE AND NOT IN ONE OF THE ARMS BELOW, because what it records is
  // "the index said X on this date" — which is true the moment the fetch returned, whatever
  // this flag then decides to do about it. An operator whose shape has no route gets the
  // refusal AND a `bantamkit_status` that now knows the number; one who is already current
  // gets a line that says so with a date. The return value is deliberately dropped: a record
  // that could not be written is not a reason to fail an update that worked.
  recordUpdate(latest);

  const header = fill(COMPARISON, { program: PROGRAM, installed, latest });
  const order = compareVersions(installed, latest);
  if (order === 0) return `${header}\n${UP_TO_DATE}`;
  if (order > 0) return `${header}\n${AHEAD}`;

  const command = upgradeCommand(environment);
  const rendered = shlexJoin(command);

  if (origin.shape !== 'registry') {
    // An unknown shape word is a fact about THIS code being behind `INSTALL_SHAPES`, not about
    // the operator's machine, and inventing a route for it would be the guess the whole
    // install-shape surface refuses to make.
    const route = ROUTES[origin.shape] ?? NO_RECORDED_ROUTE;
    throw new UpdateRefused(
      fill(NO_ROUTE, {
        program: PROGRAM,
        installed,
        latest,
        shape: origin.shape,
        route: fill(route, {
          source: origin.source,
          package: PACKAGE,
          command: rendered,
          installed,
          latest,
          shape: origin.shape,
        }),
      }),
    );
  }

  const [code, output] = installer(command);
  const printed = output.trim() === '' ? NO_OUTPUT : output.trim();
  if (code !== 0) {
    throw new UpdateRefused(
      fill(COMMAND_FAILED, {
        code,
        command: rendered,
        program: PROGRAM,
        installed,
        printed: PRINTED,
        output: printed,
      }),
    );
  }
  return [
    header,
    fill(UPDATING, { command: rendered }),
    PRINTED,
    printed,
    fill(UPDATED, { program: PROGRAM, installed, latest }),
    fill(RESTART, { program: PROGRAM, installed }),
  ].join('\n');
}

/**
 * `--update` on the CLI: ask the package index, act on the answer, print what happened, exit.
 *
 * THE SENTENCES ARE NOT HERE. This function owns three things and nothing else: where the
 * shape comes from, which stream each outcome is written to, and the exit code.
 *
 * STDOUT + EXIT 0 IS ONLY FOR AN ANSWER THAT IS ALREADY TRUE — up to date, the index behind,
 * or an update that actually ran. Everything else is `error: <sentence>` on stderr and exit 1,
 * including the install shapes this flag will not touch: an operator who typed `--update`
 * asked for an update, and a command that exits 0 having changed nothing is the J46-4 defect
 * by name. Exit 1 rather than 2 because argparse already owns 2 for a usage error.
 *
 * THE SHAPE IS `currentInstall()`'s ANSWER AND NOT A SECOND DETECTOR. J46-12 (`c9372ca`)
 * shipped it as a module-level function taking no arguments and touching no server state,
 * explicitly so this flag could ask it before a store or a transport exists.
 *
 * `Undetermined` — a `git+https://…` origin, which is neither an index nor a path on this
 * machine — is a refusal and not a fallback. Its own message already names the route, so it is
 * quoted rather than paraphrased.
 *
 * THE WRITERS ARE ARGUMENTS so this arm is testable without a subprocess and without rewriting
 * `process.stdout`. `cli.ts` hands in the real two. Both receive a UTF-8 string, which is LF
 * on every platform — the same reason the reference goes through `sys.stdout.buffer`, where
 * `print` would emit CRLF on Windows and a byte-comparing conformance runner would read that
 * as a divergence belonging to the writer rather than to the product.
 */
export async function runUpdate(
  out: (text: string) => void,
  err: (text: string) => void,
  installed: string,
  packageDirectory: string,
  options: UpdateOptions = {},
): Promise<number> {
  let shape: string;
  let recorded: string | null;
  try {
    const install = (options.install ?? currentInstall)();
    shape = install.shape;
    recorded = install.source;
  } catch (e) {
    if (!(e instanceof Undetermined)) throw e;
    err(`error: ${fill(SHAPE_UNKNOWN, { reason: e.message })}\n`);
    return 1;
  }
  // `source` is `null` for the shapes that HAVE no recorded origin rather than for one whose
  // path could not be read — `registry`, where the route is this flag itself, and `checkout`,
  // whose tree IS the thing to update. The running package directory is not a guess: it is
  // where the code being executed lives, and it is the tree the route says to `git pull`.
  let origin: Origin = { shape, source: recorded ?? packageDirectory };
  let current = installed;
  let chosen = options;
  // J51-5: an `npx` cache WITH a kept install updates the kept install — its version is the one
  // compared and printed, and its prefix is where npm points — through exactly the registry
  // route's lines. Decided HERE and not in `update()`, so `update()` stays a function of its
  // arguments and never of whatever `~/.bantamkit/mcp` the machine running it happens to hold.
  // No kept install: nothing below changes and the `ephemeral` refusal is today's.
  if (shape === 'ephemeral') {
    const kept = keptInstall();
    if (kept !== null) {
      origin = { shape: 'registry', source: kept.environment.root };
      current = kept.version;
      chosen = { ...options, environment: kept.environment };
    }
  }
  try {
    out(`${await update(current, origin, chosen)}\n`);
  } catch (e) {
    if (!(e instanceof UpdateRefused)) throw e;
    err(`error: ${e.message}\n`);
    return 1;
  }
  return 0;
}
