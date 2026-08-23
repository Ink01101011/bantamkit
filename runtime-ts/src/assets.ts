/**
 * Locate and load the language-agnostic asset pack.
 *
 * A port of `runtime-py/src/bantamkit/assets.py`, arm for arm. The Python module is the
 * reference; where this file deviates the deviation is a comment, not an accident.
 */
import { existsSync, realpathSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { BantamError } from './errors.js';
import { pyReadText } from './memory/pyfs.js';

export class AssetNotFound extends BantamError {}

/** The agent-facing view of a tool asset — Python's `bantamkit.client.Tool`. */
export interface Tool {
  name: string;
  description: string;
  parameters: unknown;
}

/**
 * `Path.read_text(encoding="utf-8")`, which is `memory/pyfs.pyReadText` and NOT a second
 * spelling of it.
 *
 * It WAS a second spelling — `readFileSync(p, 'utf8').replace(/\r\n?/g, '\n')` — and N8
 * measured the two decoders disagreeing: `pyReadText` dropped a leading UTF-8 BOM (its
 * `TextDecoder` defaults `ignoreBOM` to false) while this one kept it, so one package held
 * two UTF-8 decodes with opposite answers on the same three bytes. This one happened to be
 * the one that matched CPython; the fix is not to keep the right copy but to keep ONE, so
 * the next divergence has nowhere to hide. What this arm gains in the trade: `pyReadText`
 * decodes STRICTLY, so a tool asset that is not valid UTF-8 now raises CPython's
 * `UnicodeDecodeError` here instead of reaching a model with U+FFFD substituted into the
 * description it reads. Universal-newline translation is unchanged and lives there too.
 */
function readTextUniversal(path: string): string {
  return pyReadText(path);
}

/**
 * The three arms, in Python's order.
 *
 *   1. `$BANTAMKIT_ASSETS`, verbatim, no existence check — the override wins even when
 *      it is wrong, so a wrong override fails naming itself rather than falling through
 *      to a pack the operator did not ask for.
 *   2. The packaged pack, resolved off THIS module. When installed from the tarball
 *      this module is `<pkg>/dist/assets.js`, so `../assets/` is `<pkg>/assets/`.
 *      **This is the arm npx uses.**
 *   3. The repository pack, for a dev checkout, where nothing has been vendored into
 *      `runtime-ts/assets/`. This module is `<repo>/runtime-ts/dist/assets.js`, so the
 *      repo root is two levels up — the count is proved by `test/assets.test.mjs`,
 *      which builds the layout in a temp dir and imports the real build output out of
 *      it. Python reaches the same place with `Path(__file__).resolve().parents[3]`
 *      from `<repo>/runtime-py/src/bantamkit/assets.py`, and resolves symlinks on this
 *      arm only; that asymmetry is mirrored here.
 */
export function assetsRoot(): string {
  const env = process.env.BANTAMKIT_ASSETS;
  if (env) {
    return env;
  }
  const hereDir = dirname(fileURLToPath(import.meta.url));
  const packaged = join(hereDir, '..', 'assets');
  if (existsSync(packaged)) {
    return packaged;
  }
  const repo = join(realpathSync(hereDir), '..', '..', 'assets');
  if (existsSync(repo)) {
    return repo;
  }
  throw new AssetNotFound('no assets directory found; set BANTAMKIT_ASSETS');
}

/**
 * Return one tool asset VERBATIM — every key, including the ones no surface uses.
 *
 * `loadTool` below narrows the same file to the three fields a model is shown. This
 * returns the whole manifest entry, because a server has to read `surfaces` (may I
 * register this at all?) and `output_schema` (what do I advertise as the return shape?)
 * and neither belongs on the agent-facing `Tool`.
 */
export function loadToolAsset(name: string): Record<string, unknown> {
  const path = join(assetsRoot(), 'tools', `${name}.json`);
  if (!existsSync(path)) {
    throw new AssetNotFound(`tool asset not found: ${path}`);
  }
  return JSON.parse(readTextUniversal(path)) as Record<string, unknown>;
}

/**
 * The agent-facing view of a tool asset: name, description, input schema.
 *
 * The three keys are named EXPLICITLY rather than splatted. `assets/tools/` is shared by
 * two tool surfaces and carries fields that only the MCP one consumes; a loader that
 * passed the dict through would add them to every tool definition an eval-run model is
 * shown, changing the agent surface every time the manifest grows.
 */
export function loadTool(name: string): Tool {
  const data = loadToolAsset(name);
  return {
    name: data['name'] as string,
    description: data['description'] as string,
    parameters: data['parameters'],
  };
}

/** Return a JSON Schema asset (parsed) — e.g. the shift-work checkpoint contract. */
export function loadSchema(name: string): Record<string, unknown> {
  const path = join(assetsRoot(), 'schemas', `${name}.json`);
  if (!existsSync(path)) {
    throw new AssetNotFound(`schema asset not found: ${path}`);
  }
  return JSON.parse(readTextUniversal(path)) as Record<string, unknown>;
}

export function loadSkill(name: string): string {
  const path = join(assetsRoot(), 'skills', `${name}.md`);
  if (!existsSync(path)) {
    throw new AssetNotFound(`skill asset not found: ${path}`);
  }
  return readTextUniversal(path);
}
