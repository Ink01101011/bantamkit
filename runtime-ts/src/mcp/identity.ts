/**
 * `build_identity` — the one function in the port that could not be ported, and why.
 *
 * THE QUESTION THE TOOL EXISTS TO ANSWER is "which code is actually executing?", and
 * `RB-P84` is the case that made it a tool rather than a field on `initialize`: two
 * `bantamkit` endpoints registered under one name on one machine, both spawned, and their
 * advertised surfaces byte-identical over 6864 bytes. `npx` makes that worse rather than
 * better — it resolves `latest` and caches it per machine, so two developers on one config
 * line can be running two different tarballs and nothing in the handshake says so.
 *
 * WHAT COULD NOT BE PORTED. `_code_fingerprint` hashes 24 `.py` files. A Node build has
 * none, so `code_digest` cannot mean what it means over there, and `build_id` — which is
 * sha256 over `{server_name, version, code_digest, assets_digest}` — cannot be made to
 * agree between the runtimes for one release. Reproducing that shape while silently
 * changing what it measures would be the worst outcome available: a caller comparing two
 * `build_id`s would read "different builds" and could not tell whether the difference is a
 * release, an edit, or the language.
 *
 * SO THE SHAPE IS CHANGED ON PURPOSE, IN THREE PLACES, AND EACH IS VISIBLE ON THE WIRE:
 *
 *   1. `runtime` is a NEW field, `"node"`. Its presence is itself the discriminator — the
 *      Python endpoint has no such key — so a caller never has to infer the lineage from a
 *      digest that happens not to match.
 *   2. `runtime` is folded INTO `build_id`. That is domain separation, not decoration: with
 *      it, a Node and a Python `build_id` cannot collide even in the impossible case where
 *      their code digests agreed, so `build_id` equality never means "same build" across
 *      lineages by accident.
 *   3. `cross_runtime` says all of it in a sentence, in the output, next to the fields it is
 *      about — because the caller who needs it is a model holding one tool result, not a
 *      person reading this file.
 *
 * WHAT IS UNCHANGED, AND IS THE POINT. `assets_digest` / `assets_files` / `assets_root` are
 * computed exactly as Python computes them, over the same 84 files and 213,773 bytes, in
 * `sorted(Path)` order, with the same per-file feed. The asset pack is language-agnostic and
 * is the one thing the two runtimes genuinely share, so it is the one field that IS
 * comparable across them — and `tools/conformance/suites/wire.mjs` compares the two live
 * servers' `assets_digest` to prove it, rather than asserting it here.
 *
 * `RB-P84`'s ruling stands unchanged: `build_id` DECLINES when an input is underivable. A
 * partial identity would agree with every other build that lost the same input.
 */
import { createHash } from 'node:crypto';
import { lstatSync, readFileSync, readdirSync, readlinkSync, realpathSync, statSync } from 'node:fs';
import { basename, dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import { AssetNotFound, assetsRoot } from '../assets.js';
import { sortedPathParts } from '../memory/pyfs.js';
import { PyOSError, asPyOSError } from '../memory/pyfs.js';

export const SERVER_NAME = 'bantamkit';

/**
 * A build fact that could not be derived, carrying WHY. Never becomes a value.
 *
 * Exported since job46: `bantamkit_status` has to distinguish "this install could not be
 * classified" — which is a REPORTED gap and not a degraded server — from a real fault, and
 * `instanceof` is the only way to do that without matching on a message.
 */
export class Undetermined extends Error {}

/**
 * The shape an underivable fact takes on the wire — `RB-P51`, unchanged from Python.
 *
 * A sentinel string (`""`, `"unknown"`) sits in a field typed as a path or a digest and a
 * caller comparing fields reads it as one. An object cannot: every derivable field here is a
 * string, an int or a bool, so a caller that got a dict knows it got no answer.
 */
const unavailable = (reason: string): { unavailable: string } => ({ unavailable: reason });

/**
 * `sorted(root.rglob("*") if p.is_file())` — the walk, in `Path` order.
 *
 * `rglob` does not descend into a symlinked DIRECTORY (CPython 3.12), and `is_file()` DOES
 * follow a symlink to a file. Both are mirrored: a symlinked directory is listed and not
 * entered, a symlinked file is included and read through. The asset pack contains neither
 * today; the behaviour is matched anyway, because a pack that grew one would otherwise
 * fingerprint differently under the two runtimes and nothing would say so.
 */
function walkFiles(root: string): string[][] {
  const found: string[][] = [];
  const descend = (parts: string[]): void => {
    const here = parts.length === 0 ? root : join(root, ...parts);
    for (const entry of readdirSync(here, { withFileTypes: true })) {
      const next = [...parts, entry.name];
      if (entry.isDirectory()) {
        descend(next);
      } else if (entry.isFile()) {
        found.push(next);
      } else if (entry.isSymbolicLink()) {
        // `is_file()` resolves; a dangling link is neither a file nor a directory and
        // `rglob` yields it while the `is_file()` filter drops it.
        let resolved;
        try {
          resolved = statSync(join(here, entry.name));
        } catch {
          continue;
        }
        if (resolved.isFile()) found.push(next);
      }
    }
  };
  descend([]);
  return sortedPathParts(found);
}

/**
 * sha256 over (relative path, size, bytes) of every file, in sorted path order.
 *
 * The feed is `update(relpath.as_posix().utf8)`, `update(b"\0%d\0" % len(payload))`,
 * `update(payload)` — paths folded in so a move is a different build, sizes so a
 * concatenation cannot be re-partitioned into the same stream. `len(payload)` is a BYTE
 * count, which is why the payload is read as a Buffer and never as a string.
 *
 * `as_posix()` is why the parts are joined with `/` here and not with `path.sep`: on Windows
 * the walk yields the same components and the digest must not change with the separator.
 */
export function treeDigest(
  root: string,
  keep?: (parts: string[]) => boolean,
): { digest: string; files: number } {
  const walked = walkFiles(root);
  const files = keep === undefined ? walked : walked.filter(keep);
  const running = createHash('sha256');
  for (const parts of files) {
    const payload = readFileSync(join(root, ...parts));
    running.update(Buffer.from(parts.join('/'), 'utf8'));
    running.update(Buffer.from(`\0${payload.length}\0`, 'utf8'));
    running.update(payload);
  }
  return { digest: `sha256:${running.digest('hex')}`, files: files.length };
}

/**
 * Fingerprint the code that is actually executing — `dist/**\/*.js`.
 *
 * The Node analogue of `bantamkit.__file__` is this module's own URL: it is the resolution
 * the loader already performed, so it names the tree serving the call and not a checkout
 * that happens to be nearby (`RB-P55`, inside a worktree). Compiled to `dist/mcp/identity.js`,
 * one level up is `dist/`, which is the code root in a checkout AND in an installed tarball.
 *
 * `*.js` and nothing else, mirroring Python's `*.py`. The `.d.ts` files ship but never
 * execute, and folding them in would make a build that changed only a type annotation report
 * as different code. `assets/` is excluded for the reason Python excludes it — in a tarball
 * the pack is a SIBLING of `dist/` so the exclusion is inert today, and it stays because the
 * pack carries eleven `.py`-shaped fixture files whose Node equivalents would otherwise be
 * counted twice: once here and once under `assets_digest`, where they belong.
 */
function codeFingerprint(): { digest: string; files: number; root: string } {
  const root = dirname(dirname(fileURLToPath(import.meta.url)));
  const jsOnly = (parts: string[][]): string[][] =>
    parts.filter((p) => p[p.length - 1]!.endsWith('.js') && p[0] !== 'assets');
  const files = jsOnly(walkFiles(root));
  if (files.length === 0) {
    // A digest over nothing is a constant, and two servers that both computed one would
    // agree — the vacuity this whole surface exists to prevent.
    throw new Undetermined(`no .js source found under ${root}`);
  }
  const running = createHash('sha256');
  try {
    for (const parts of files) {
      const payload = readFileSync(join(root, ...parts));
      running.update(Buffer.from(parts.join('/'), 'utf8'));
      running.update(Buffer.from(`\0${payload.length}\0`, 'utf8'));
      running.update(payload);
    }
  } catch (e) {
    const error = e instanceof PyOSError ? e : asPyOSError(e, root);
    throw new Undetermined(`unreadable source under ${root}: ${error.message}`);
  }
  return { digest: `sha256:${running.digest('hex')}`, files: files.length, root };
}

/**
 * Fingerprint the asset pack this build would load — every file, not just the loaded ones.
 *
 * `contracts/default.yaml` is the reason: `RB-P84` measured it as the one asset that differed
 * between two live builds while no resource template exposed it, so it was invisible on every
 * probed surface. It is also why N1 ships all 84 files rather than the 20 that are read.
 *
 * EXCEPT bytecode caches, and that exception is the whole point of this field. The pack ships
 * `.py` fixture files, so `pip install` byte-compiles them into `__pycache__` on the way in and
 * the digest of an INSTALLED Python pack stopped matching the digest of the identical npm pack
 * — measured on the published 0.27.0 artifacts, `sha256:fa8372f6…` over 98 files against
 * `sha256:d47dcf4b…` over 87, and deleting `__pycache__` from the wheel's pack reproduced the
 * npm digest byte for byte. `cross_runtime` tells the caller to compare `assets_digest` across
 * runtimes; without this rule that instruction returned a false "different" on every real
 * install. The pack is what was SHIPPED, never what an interpreter later wrote beside it.
 *
 * The rule is spelled identically in `runtime-py`'s `_assets_fingerprint`, and it has to be:
 * this side never creates a `__pycache__`, so a Node-only exclusion would still agree today
 * and diverge again the moment a pack carrying one reached both runtimes.
 */
export const notBytecodeCache = (parts: string[]): boolean => !parts.includes('__pycache__');

/**
 * The pack as SHIPPED, counted — what `--assets-root` prints.
 *
 * Exported so the CLI shares this walk rather than keeping a second one. There are TWO
 * walks over this directory and a rule spelled twice is a rule that gets fixed once: the
 * first version of this fix filtered the digest alone, and a `pip install` then had one
 * process contradicting itself, `build_identity` answering 87 files while `--assets-root`
 * printed 98 for the pack it had just loaded. The CLI's own `readdirSync(recursive)` is
 * gone with it — `walkFiles` is the walk that mirrors CPython's `rglob`, which is what the
 * reference's printer uses and what the conformance case compares the count against.
 */
export function packFileCount(root: string): number {
  return walkFiles(root).filter(notBytecodeCache).length;
}

function assetsFingerprint(): { digest: string; files: number; root: string } {
  let root: string;
  try {
    root = assetsRoot();
  } catch (e) {
    if (e instanceof AssetNotFound) throw new Undetermined(`assets_root() could not resolve a pack: ${e.message}`);
    throw e;
  }
  let walked;
  try {
    walked = treeDigest(root, notBytecodeCache);
  } catch (e) {
    const error = e instanceof PyOSError ? e : asPyOSError(e, root);
    // A root that does not exist at all is the `BANTAMKIT_ASSETS` typo, and Python reaches
    // the same place: `rglob` over a missing directory yields nothing, so "contains no files".
    if (error.code === 'ENOENT' || error.code === 'ENOTDIR') {
      throw new Undetermined(`asset pack at ${root} contains no files`);
    }
    throw new Undetermined(`unreadable asset under ${root}: ${error.message}`);
  }
  if (walked.files === 0) throw new Undetermined(`asset pack at ${root} contains no files`);
  return { digest: walked.digest, files: walked.files, root };
}

// ---------------------------------------------------------------------------------------
// WHICH INSTALL SHAPE IS RUNNING — offline, from this server's own location.
//
// THE DEFECT IS A NODE DEFECT AND IT IS MEASURED (`docs/roadmap-agent-stack.md` AS-7). A
// Claude Desktop entry sat on 0.25.0 from 2026-08-24 through five releases with nothing in
// the config, the logs or any tool reply saying so — and its `package.json` declared the
// dependency as `"bantamkit-mcp": "file:/private/tmp/.../scratchpad/bantamkit-mcp-0.25.0.tgz"`,
// a local tarball in a temp directory that no longer existed. An update run where that install
// lives is a no-op BY CONSTRUCTION, and nothing anywhere said which of those two things was
// wrong. Four of those caches are still on this machine under `~/.npm/_npx/*/`.
//
// WHY THIS IS A REFUSAL AND NOT A LOOKUP. The origin is written down by the installer, on this
// disk, in `node_modules/.package-lock.json` — npm's hidden lockfile, the Node counterpart of
// PEP 610's `direct_url.json`. Whether that path still exists is a `stat`. NO NETWORK IS
// TOUCHED ON ANY PATH BELOW: comparing the running version against a registry is AS-7(b), a
// separate unit, gated behind this one, and deliberately opt-in because an offline toolbox
// must not grow a network call in its health check.
//
// SHAPE IS LOCATION, NEVER IDENTITY. It is reported for the same reason `package_path` and
// `interpreter` are — it is what a person acts on — and it is kept OUT of `build_id` for the
// same reason they are: one build installed two ways is ONE build, and
// `test/install-shape.test.mjs` recomputes the hash from its five named inputs to prove it.
//
// WHAT NPM ACTUALLY WRITES, MEASURED AGAINST npm 11.6.2 BEFORE ANY OF THIS WAS WRITTEN — every
// branch below is a record that was read off this machine, not a shape recalled from docs:
//
//   tarball      `{"resolved": "file:../x.tgz"}` — `file:` then a RAW path, relative to the
//                directory that owns `node_modules`, and NOT percent-encoded (measured with a
//                space in the directory name, which is the case that actually turns up).
//   `file:` dir  `{"resolved": "../src", "link": true}` — no `file:` prefix at all, and the
//                package directory under `node_modules` is a real symlink.
//   registry     `{"resolved": "https://registry.npmjs.org/…"}`.
//   global       `<npm prefix -g>/lib/node_modules` carries NO `.package-lock.json` at all,
//                and npm 7+ writes no `_resolved` into the installed `package.json` either.
//   npx          the cache project's own `package.json` carries `"_npx": {"packages": [...]}`.
// ---------------------------------------------------------------------------------------

/**
 * The closed vocabulary, spelled the same way in both runtimes, and it answers ONE question:
 * what would updating this install even mean?
 *
 *   registry     came from a package index (npm here, PyPI there). Reinstall by name.
 *   local-file   came from a path on THIS machine — an archive or a directory whose contents
 *                were copied in. The path is recorded and may be gone.
 *   linked       a directory on this machine is still the source being read: a `file:` dir or
 *                an `npm link` symlink here, an editable install there. Update that tree.
 *   checkout     no installer recorded this tree at all. Git.
 *   ephemeral    a temporary environment discarded after the run. Nothing to update.
 *
 * `ephemeral` IS ANSWERED HERE AND NEVER BY `runtime-py`, which is the one divergence in this
 * surface: npm writes an `_npx` marker into the cache project's own `package.json`, so this is
 * a RECORD, while a `pipx run` or `uvx` environment is not distinguishable from an ordinary
 * venv without pattern-matching cache directory names — a guess, and that surface does not
 * guess. The word is declared on BOTH sides anyway so a consumer of either runtime handles ONE
 * set of five rather than two sets it has to reconcile.
 */
export const INSTALL_SHAPES = ['registry', 'local-file', 'linked', 'checkout', 'ephemeral'] as const;

/**
 * Where the running code came from, and the origin path it can still be checked against.
 *
 * `source` is `null` for the shapes that HAVE no origin path rather than for the ones whose
 * path could not be read — `sourceReason` carries which, in the operator's words, and
 * `buildIdentity` turns it into the `{"unavailable": ...}` shape RB-P51 requires. A shape that
 * could not be derived at all is an `Undetermined`, never a sixth word.
 */
export interface Install {
  readonly shape: string;
  readonly source: string | null;
  readonly sourceReason: string;
}

const NODE_MODULES = 'node_modules';

const REGISTRY = (): Install => ({
  shape: 'registry',
  source: null,
  sourceReason:
    'a registry install records no origin path on this machine: npm writes a local origin ' +
    'into `node_modules/.package-lock.json` only for a `file:` path or a link, and this ' +
    'install has none. Reinstall by name to move it.',
});

const CHECKOUT_REASON =
  'no installer recorded this tree, so there is no origin path to check — the source IS ' +
  '`package_path`, and it is updated where it was cloned.';

const EPHEMERAL_REASON =
  'an ephemeral install records no origin path on this machine: npm resolves the `npx` cache ' +
  'again on the next run rather than updating it in place, so there is nothing here to ' +
  'refresh. Change the spec the host command line names to move it.';

/** Parsed JSON from a file, or `null` when the file is missing, unreadable or not an object. */
function readJsonObject(path: string): Record<string, unknown> | null {
  let raw: string;
  try {
    raw = readFileSync(path, 'utf8');
  } catch {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
    ? (parsed as Record<string, unknown>)
    : null;
}

/**
 * A recorded origin as a path on this machine, or `null` when it names neither.
 *
 * TWO FORMS, AND THE DIFFERENCE IS MEASURED. npm writes `file:` followed by a RAW path — a
 * space in a person's own directory arrives as a space, not as `%20`, so decoding that form
 * would corrupt any real filename containing a literal `%`. The `file://` URL form IS
 * percent-encoded, carries a leading slash before a Windows drive letter that is not part of
 * the path, and may name `localhost`; `url.fileURLToPath` handles it, and is not used here
 * because it throws on the bare form npm actually writes and would have to be guarded either
 * way. A `file://` URL with a real authority (`file://otherhost/share`) names a path on a
 * machine that is not this one, so it is not a local origin and the caller is told so.
 */
function localOriginPath(resolved: string, base: string): string | null {
  if (!resolved.startsWith('file:')) return null;
  const rest = resolved.slice('file:'.length);
  if (!rest.startsWith('//')) return resolve(base, rest);
  let path = rest.slice(2);
  if (path.startsWith('localhost/')) path = path.slice('localhost'.length);
  if (!path.startsWith('/')) return null;
  path = decodeURIComponent(path);
  // `/C:/x` is `C:/x`; a POSIX path never matches this shape.
  if (path.length > 2 && /[A-Za-z]/.test(path[1] as string) && path[2] === ':') path = path.slice(1);
  return resolve(base, path);
}

/** `Path.is_relative_to`, tolerating a `parent` that is a symlink or does not exist. */
function isWithin(child: string, parent: string): boolean {
  for (const candidate of [parent, safeRealpath(parent)]) {
    if (candidate === null) continue;
    const step = relative(candidate, child);
    if (step === '' || (!step.startsWith('..') && !step.startsWith(`${sep}`))) return true;
  }
  return false;
}

/** `Path.is_symlink()`: false for a missing path and for anything that is not a link. */
function isSymlink(path: string): boolean {
  try {
    return lstatSync(path).isSymbolicLink();
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === undefined) throw e;
    return false;
  }
}

function safeRealpath(path: string): string | null {
  try {
    return realpathSync.native(path);
  } catch {
    return null;
  }
}

/**
 * The package that OWNS the running file: the nearest `package.json` above it.
 *
 * The nearest one and not a named one, so a rename of the published package does not silently
 * turn every install into a `checkout`. It is the same question `_dist_owns` asks on the
 * Python side — which distribution put the file that is running on disk — answered the way
 * Node's own resolver answers it.
 */
function packageRootFor(startDir: string): { root: string; name: string } | null {
  let here = resolve(startDir);
  for (;;) {
    const manifest = readJsonObject(join(here, 'package.json'));
    if (manifest !== null) {
      const name = manifest['name'];
      return { root: here, name: typeof name === 'string' ? name : '' };
    }
    const parent = dirname(here);
    if (parent === here) return null;
    here = parent;
  }
}

interface Installed {
  readonly projectRoot: string;
  readonly nodeModules: string;
  readonly key: string;
}

/**
 * Every `node_modules` this package sits under, nearest first, with the lockfile key each one
 * would use.
 *
 * There can be more than one: a nested `a/node_modules/b/node_modules/c` is keyed from the
 * OUTERMOST project, which is the only place npm writes the hidden lockfile, while a plain
 * install is keyed from the nearest. Both are tried rather than guessed between.
 */
function nodeModulesAncestors(packageRoot: string): Installed[] {
  const found: Installed[] = [];
  let here = dirname(packageRoot);
  for (;;) {
    if (basename(here) === NODE_MODULES) {
      const projectRoot = dirname(here);
      found.push({
        projectRoot,
        nodeModules: here,
        key: relative(projectRoot, packageRoot).split(sep).join('/'),
      });
    }
    const parent = dirname(here);
    if (parent === here) return found;
    here = parent;
  }
}

/** npm's own record for this package, from the hidden lockfile, or `null` when there is none. */
function lockfileEntry(place: Installed): Record<string, unknown> | null {
  const lock = readJsonObject(join(place.nodeModules, '.package-lock.json'));
  const packages = lock?.['packages'];
  if (typeof packages !== 'object' || packages === null) return null;
  const entry = (packages as Record<string, unknown>)[place.key];
  return typeof entry === 'object' && entry !== null && !Array.isArray(entry)
    ? (entry as Record<string, unknown>)
    : null;
}

/** npm's own marker for an `npx` cache project — a record it writes, not a directory name. */
function isNpxProject(projectRoot: string): boolean {
  const manifest = readJsonObject(join(projectRoot, 'package.json'));
  return manifest !== null && typeof manifest['_npx'] === 'object' && manifest['_npx'] !== null;
}

/** The origin npm wrote down, as one of the five words. */
function originFromEntry(entry: Record<string, unknown>, projectRoot: string): Install {
  const raw = entry['resolved'];
  const recorded = typeof raw === 'string' ? raw : '';
  if (entry['link'] === true && recorded !== '') {
    // A link entry carries a bare relative path with no `file:` prefix at all (measured).
    return { shape: 'linked', source: resolve(projectRoot, recorded), sourceReason: '' };
  }
  // AN http(s) ORIGIN IS `registry` AND NOT A REFUSAL, which is where this parts company with
  // the reference. There, an http `direct_url.json` is underivable; here the registry IS an
  // https URL, and telling a published tarball URL from the configured index would mean
  // knowing which index was configured — a guess. Either way the origin is REMOTE, so it can
  // never be the dangling-local-path defect this surface exists for, and the route out is a
  // reinstall by name.
  if (/^https?:\/\//i.test(recorded)) return REGISTRY();
  const path = localOriginPath(recorded, projectRoot);
  if (path !== null) return { shape: 'local-file', source: path, sourceReason: '' };
  if (recorded === '') return REGISTRY();
  throw new Undetermined(
    `this install records its origin as ${recorded}, which is neither a package index nor a ` +
      `path on this machine, so its shape is not one of ${INSTALL_SHAPES.join(', ')}. A git ` +
      'or http origin is updated by reinstalling from that same URL.',
  );
}

/** Every path a symlink chain passes through, starting with the one it was handed. */
function symlinkChain(start: string): string[] {
  const chain: string[] = [];
  let here = resolve(start);
  for (let step = 0; step < 40; step += 1) {
    chain.push(here);
    let target: string;
    try {
      target = readlinkSync(here);
    } catch {
      break;
    }
    here = resolve(dirname(here), target);
    if (chain.includes(here)) break;
  }
  return chain;
}

/** Does this path pass through `node_modules/<name>` — the entry npm's link would occupy? */
function passesThroughEntry(path: string, name: string): boolean {
  const parts = path.split(/[\\/]/);
  const wanted = name.split('/');
  for (let i = 0; i < parts.length; i += 1) {
    if (parts[i] !== NODE_MODULES) continue;
    if (wanted.every((segment, j) => parts[i + 1 + j] === segment)) return true;
  }
  return false;
}

/**
 * Is this tree being SERVED through an `npm link`, even though it does not sit in node_modules?
 *
 * MEASURED, AND IT IS THE REASON THIS FUNCTION EXISTS AT ALL. Node realpaths ESM specifiers,
 * so a linked install's `import.meta.url` names the SOURCE tree and the `node_modules` ancestor
 * is gone from it — which would make every `npm link` and every `file:` directory dependency
 * report `checkout`. `process.argv[1]` is the half Node does NOT resolve: driving the same file
 * through a `file:` dir install printed `import.meta.url = …/src/dist/index.js` beside
 * `argv[1] = …/node_modules/bantamkit-mcp/dist/index.js`. So the pair is the evidence, and both
 * halves are location — neither is server state, and both are fixed for the life of a process.
 *
 * The entry has to actually BE this tree (its realpath lands inside the package root) and it
 * has to pass through `node_modules/<this package>` (npm's link, not somebody else's): a
 * checkout keeps its own `node_modules` for devDependencies, so the bare segment proves nothing.
 */
function servedThroughNodeModules(entryPath: string, packageRoot: string, name: string): boolean {
  if (name === '') return false;
  const chain = symlinkChain(entryPath);
  const last = chain[chain.length - 1];
  if (last === undefined) return false;
  const landing = safeRealpath(last);
  if (landing === null || !isWithin(landing, packageRoot)) return false;
  return chain.some((step) => passesThroughEntry(step, name));
}

/**
 * The whole diagnosis, over a running file and the path the process was launched through.
 *
 * Taken as ARGUMENTS rather than read from the process so that every shape can be built as a
 * real `node_modules` tree with a real hidden lockfile, a real symlink and a really-absent
 * tarball, and read back through the same code the server runs. A stubbed filesystem here
 * would assert this function's own reasoning back at it, and the entire question is what npm
 * actually writes down.
 */
export function deriveInstall(runningFile: string, entryPath: string | null): Install {
  const owner = packageRootFor(dirname(resolve(runningFile)));
  if (owner === null) {
    throw new Undetermined(
      `no package.json owns ${runningFile}, so there is no installer record to read and this ` +
        'build cannot say where it came from.',
    );
  }
  const places = nodeModulesAncestors(owner.root);
  for (const place of places) {
    const entry = lockfileEntry(place);
    if (entry === null) continue;
    return withEnvironment(originFromEntry(entry, place.projectRoot), places);
  }
  // Under `node_modules` with no record anywhere: the global-install shape measured above. The
  // ABSENCE is positive evidence, because the two alternatives both leave a trace — a `file:`
  // origin in the lockfile, or a symlink where the package directory should be — and an
  // installed copy that left neither came from an index.
  if (places.length > 0) {
    // A package directory that IS a symlink is npm's link, whatever the lockfile says or fails
    // to say. Reached only where the symlink survived to here — Node realpaths ESM specifiers,
    // so in practice that is `--preserve-symlinks` — and it is checked before falling back to
    // the absence-is-evidence branch, because an absence proves nothing next to a symlink.
    const linkedTarget = safeRealpath(owner.root);
    if (linkedTarget !== null && isSymlink(owner.root)) {
      return { shape: 'linked', source: linkedTarget, sourceReason: '' };
    }
    return withEnvironment(REGISTRY(), places);
  }
  if (entryPath !== null && servedThroughNodeModules(entryPath, owner.root, owner.name)) {
    return { shape: 'linked', source: owner.root, sourceReason: '' };
  }
  return { shape: 'checkout', source: null, sourceReason: CHECKOUT_REASON };
}

/**
 * `ephemeral` is the ENVIRONMENT and the origin is the ORIGIN — two axes, and only one word.
 *
 * The environment wins the word, because it is the half that is true whatever the origin was:
 * an `npx` cache is not updated in place at all, so what has to change is the spec on the
 * host's command line. The origin is NOT lost with it — `source` and `install_source_exists`
 * still carry it, and `install-source-missing` still fires and still names the path. Collapsing
 * the two would have thrown away exactly the fact AS-7 was filed about, since the measured
 * incident is both at once: an `npx` cache filled from a tarball that no longer exists.
 */
function withEnvironment(origin: Install, places: readonly Installed[]): Install {
  if (!places.some((place) => isNpxProject(place.projectRoot))) return origin;
  return {
    shape: 'ephemeral',
    source: origin.source,
    sourceReason: origin.source === null ? EPHEMERAL_REASON : '',
  };
}

/**
 * The errnos that mean "not there" rather than "could not look" — the reference's
 * `pathlib._ignore_error` set, which is what makes `Path.exists()` return `False` instead of
 * raising. Everything else is a check that did not happen, and saying `false` for one of those
 * would report a deleted origin where the truth is a directory nobody may read.
 */
const NOT_THERE = new Set(['ENOENT', 'ENOTDIR', 'EBADF', 'ELOOP', 'EINVAL', 'ENAMETOOLONG']);

/**
 * Is the recorded origin still on disk? `present: null` when the check itself could not be made.
 *
 * `existsSync` is deliberately not used: it swallows EVERY error and answers `false`, so an
 * origin under a directory the server may not read would be reported as DELETED — a wrong
 * answer where the reference gives none. This is the half that is re-read on every tool call,
 * so it is one `stat` and nothing else.
 */
export function originStat(path: string): { present: boolean | null; reason: string } {
  try {
    statSync(path);
    return { present: true, reason: '' };
  } catch (e) {
    const code = (e as NodeJS.ErrnoException).code;
    if (code === undefined) throw e;
    if (NOT_THERE.has(code)) return { present: false, reason: '' };
    return {
      present: null,
      reason: `the recorded origin path could not be checked: ${(e as Error).message}`,
    };
  }
}

let installOnce: { readonly install: Install | null; readonly error: Undetermined | null } | null = null;

/**
 * Which install shape is running. Importable, and NOT owned by the status path.
 *
 * DERIVED ONCE, because the bytes that were imported cannot change under a process. The footer
 * runs `degradedConditions` on every tool call and `docs/status.md` promises what that costs;
 * walking `node_modules` for a hidden lockfile is not on that list. So the SHAPE is memoised
 * and only the EXISTENCE of the recorded path is re-read — which is the half that can actually
 * change while a server is running, and the half the measured defect is about. The failure is
 * memoised too: a derivation that already failed would fail identically a second time.
 *
 * Deliberately a module-level function taking no arguments and touching no server state: the
 * `--update` flag planned as J46-29 has to be shape-aware — two of the five shapes have no
 * registry route at all — and it must be able to ask this question from the CLI, before a
 * memory store or a transport exists, without building an MCP server to do it.
 */
export function currentInstall(): Install {
  if (installOnce === null) {
    try {
      installOnce = {
        install: deriveInstall(fileURLToPath(import.meta.url), process.argv[1] ?? null),
        error: null,
      };
    } catch (e) {
      if (!(e instanceof Undetermined)) throw e;
      installOnce = { install: null, error: e };
    }
  }
  if (installOnce.install === null) {
    throw installOnce.error ?? new Undetermined('the install shape was not derived');
  }
  return installOnce.install;
}

/** `sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")))` — the identity. */
export function buildIdFor(inputs: Record<string, string>): string {
  const canonical = `{${Object.keys(inputs)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${JSON.stringify(inputs[k])}`)
    .join(',')}}`;
  return `sha256:${createHash('sha256').update(Buffer.from(canonical, 'utf8')).digest('hex')}`;
}

const GIT_COMMIT_REFUSAL =
  'refused, not missing. An installed npm tarball carries no repository at all, and ' +
  "reading a checkout's HEAD would describe the TREE rather than the bytes that " +
  'were imported — an edited working copy serves different code under an unchanged ' +
  'sha, which is precisely the confusion RB-P84 filed. A commit reported that way ' +
  'would be a value that is sometimes a lie; `code_digest` is derived from the ' +
  'bytes themselves and cannot be.';

const CROSS_RUNTIME =
  'assets_digest is comparable across runtimes: the asset pack is language-agnostic and ' +
  'both endpoints digest the same files, in sorted(Path) order, with the same per-file ' +
  'feed. code_digest and build_id are NOT comparable across runtimes. This endpoint ' +
  'digests dist/**/*.js and folds runtime="node" into build_id; the Python endpoint ' +
  'digests **/*.py and folds no runtime at all, so the two build_id values are domain-' +
  'separated by construction and cannot agree for any release. Compare build_id only ' +
  'between endpoints whose `runtime` agrees; across runtimes compare `version` and ' +
  '`assets_digest`.';

/**
 * The tool body. Key order is the wire order and is deliberate: what this build IS, then
 * where it lives, then what it refuses, then the environment, then the identity.
 */
export function buildIdentity(version: string, sdkVersion: string | { unavailable: string }): Map<string, unknown> {
  const identity = new Map<string, unknown>();
  identity.set('runtime', 'node');
  identity.set('server_name', SERVER_NAME);
  identity.set('version', version);

  try {
    const code = codeFingerprint();
    identity.set('code_digest', code.digest);
    identity.set('code_files', code.files);
    identity.set('package_path', code.root);
  } catch (e) {
    if (!(e instanceof Undetermined)) throw e;
    for (const field of ['code_digest', 'code_files', 'package_path']) identity.set(field, unavailable(e.message));
  }

  try {
    const pack = assetsFingerprint();
    identity.set('assets_digest', pack.digest);
    identity.set('assets_files', pack.files);
    identity.set('assets_root', pack.root);
  } catch (e) {
    if (!(e instanceof Undetermined)) throw e;
    for (const field of ['assets_digest', 'assets_files', 'assets_root']) identity.set(field, unavailable(e.message));
  }

  // Location, never identity: `BANTAMKIT_ASSETS` redirects the pack, so whether the root was
  // chosen by the operator or resolved by the package is a fact a caller comparing two
  // endpoints needs. A bool, so it is never confusable with a missing one.
  identity.set('assets_root_from_env', Boolean(process.env.BANTAMKIT_ASSETS));

  // Location too, and the same rule: which install SHAPE is running says what updating this
  // server would even mean, and says nothing about which build it is. A `file:` install whose
  // tarball was deleted answers with a path that no longer exists — the measured defect AS-7
  // filed — and `install_source_exists` is the bit that says so. No network is consulted for
  // any of the three.
  try {
    const install = currentInstall();
    identity.set('install_shape', install.shape);
    if (install.source === null) {
      identity.set('install_source', unavailable(install.sourceReason));
      identity.set(
        'install_source_exists',
        unavailable(
          `a ${install.shape} install records no origin path, so there is nothing here to check for.`,
        ),
      );
    } else {
      identity.set('install_source', install.source);
      const origin = originStat(install.source);
      identity.set(
        'install_source_exists',
        origin.present === null ? unavailable(origin.reason) : origin.present,
      );
    }
  } catch (e) {
    if (!(e instanceof Undetermined)) throw e;
    for (const field of ['install_shape', 'install_source', 'install_source_exists']) {
      identity.set(field, unavailable(e.message));
    }
  }

  identity.set('git_commit', unavailable(GIT_COMMIT_REFUSAL));

  identity.set('interpreter', process.execPath || unavailable('process.execPath is empty; this process cannot name its own binary'));
  identity.set('node_version', process.versions.node);
  identity.set('v8_version', process.versions.v8);
  identity.set('mcp_sdk_version', sdkVersion);

  const inputNames = ['runtime', 'server_name', 'version', 'code_digest', 'assets_digest'] as const;
  const missing = inputNames.filter((key) => typeof identity.get(key) !== 'string').sort();
  if (missing.length > 0) {
    identity.set(
      'build_id',
      unavailable(
        'computed from runtime, server_name, version, code_digest and assets_digest; could ' +
          `not derive ${missing.join(', ')}. A build_id short of an input would agree ` +
          'with every other build that lost the same input, so none is reported.',
      ),
    );
  } else {
    const inputs: Record<string, string> = {};
    for (const key of inputNames) inputs[key] = identity.get(key) as string;
    identity.set('build_id', buildIdFor(inputs));
  }

  identity.set('cross_runtime', CROSS_RUNTIME);
  identity.set(
    'unavailable',
    [...identity].filter(([, v]) => typeof v === 'object' && v !== null && 'unavailable' in v).map(([k]) => k).sort(),
  );
  return identity;
}
