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
import { lstatSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { AssetNotFound, assetsRoot } from '../assets.js';
import { sortedPathParts } from '../memory/pyfs.js';
import { PyOSError, asPyOSError } from '../memory/pyfs.js';

export const SERVER_NAME = 'bantamkit';

/** A build fact that could not be derived, carrying WHY. Never becomes a value. */
class Undetermined extends Error {}

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
const notBytecodeCache = (parts: string[]): boolean => !parts.includes('__pycache__');

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
