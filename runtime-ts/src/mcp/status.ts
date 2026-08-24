/**
 * `bantamkit_status`, the degraded footer, and the conditions both are built from.
 *
 * A port of the block of the same name in `runtime-py/src/bantamkit/mcpserver.py`. The
 * contract both runtimes emit is `docs/status.md`, and `tools/conformance/suites/wire.mjs`
 * compares the two reports with line 2's build digest masked — the one value
 * `docs/porting.md` already rules divergent, because it fingerprints the executing tree and
 * these are two trees. If you find yourself needing a SECOND mask, something is diverging
 * that the contract says should not.
 *
 * WHY A TOOL RESULT AND NOT A NOTIFICATION, MEASURED BEFORE ANY OF THIS WAS WRITTEN.
 * The request this answers is "let me SEE that the server is alive", and the obvious
 * implementation — push a line at the host — does not exist on any of the five hosts
 * bantamkit targets. Claude Code's own binary carries the sentence `modern protocol
 * revision with no unsolicited notification path`, and its proprietary `claude/channel`
 * capability is gated six ways, one of which is `provider !== "firstParty"` — that rules
 * out Copilot on its own. bantamkit's host log says the same from the running side:
 * `"protocolEra":"modern"` in every `Connection established` record, and ten records of
 * `Channel notifications skipped: server did not declare claude/channel capability`. So the
 * only surface every host is guaranteed to render is a TOOL RESULT, and that is what all
 * three pieces are. Nothing here pushes and nothing here declares `claude/channel`.
 *
 * THE THREE PIECES AND WHO EACH ONE IS FOR:
 *   * `bantamkit_status` — a tool. The MODEL can call it, so an agent mid-conversation can
 *     answer "is this thing working" without the operator leaving the transcript.
 *   * a same-named PROMPT — `prompts/list` was empty on both runtimes while both advertised
 *     `prompts: {listChanged: false}`. A prompt is what a PERSON invokes.
 *   * the FOOTER — one line appended to the OTHER tools' results, and only when something is
 *     wrong. Never on a healthy call: a footer on every result is noise, noise trains the
 *     reader to stop reading, and the one time it matters it is then invisible.
 */
import { statSync } from 'node:fs';
import { join } from 'node:path';

import { AssetNotFound, assetsRoot } from '../assets.js';
import type { EventLog } from '../eventlog.js';
import { Memory } from '../memory/component.js';
import type { MemoryStore } from '../memory/store.js';

/**
 * The tool AND the prompt answer to this one name. Deliberately the same word: the operator
 * who read `bantamkit_status` in a footer must find it in their prompt menu without
 * translating, and a model that read it in a prompt must find the tool.
 */
export const STATUS_NAME = 'bantamkit_status';

/** The prompt's own title, as `prompts/list` advertises it. */
export const STATUS_PROMPT_TITLE = 'bantamkit status';

/**
 * The prompt's description — the sentence a person reads in the host's own command menu,
 * which is why it is addressed to them and not to a model.
 */
export const STATUS_PROMPT_DESCRIPTION =
  "Is bantamkit actually working? Inserts the running server's own status report — active " +
  'or degraded, its version and build fingerprint, the memory store it is bound to, whether ' +
  'the event log is on, and every degraded condition in full. Invoke it when you want the ' +
  'server to answer for itself rather than ask a model to go and check.';

/**
 * What the prompt says after the report. The report is the payload; this is the one line
 * that tells the model what the person wanted with it, and it asks for a RELAY rather than
 * an interpretation — the operator invoked this to read the server's own words.
 */
export const STATUS_PROMPT_TAIL =
  'Show me that report as it stands. If it says Degraded, tell me which of the problems ' +
  'above you would deal with first and why; if it says Active, say so in one line and stop.';

/**
 * The prompt and resource-template counts `statusReport` prints.
 *
 * Named here for the same reason the reference names them: neither SDK offers a public count
 * of its own registrations, and reaching into a manager's private map is the habit
 * `fromManifest` exists to have ended. They are PINNED AGAINST THE WIRE — the `advertisement`
 * wire session drives a real `prompts/list` and `resources/templates/list` against both
 * runtimes, so a registration added or removed without moving these fails the suite.
 */
export const SERVED_PROMPTS = 1;
export const SERVED_RESOURCE_TEMPLATES = 2;

/**
 * Percent of the index budget that has to be SPENT before the store is called degraded.
 *
 * 90 and not 100 because the useful moment is before the refusal, not after it: at 100% the
 * next `memory_save` has already failed and the operator has already seen the error. An
 * INTEGER percent, compared by cross-multiplication below, so the two runtimes cannot land
 * on opposite sides of the line through a float they rounded differently.
 */
export const INDEX_PRESSURE_PERCENT = 90;

/**
 * One thing that is wrong, carried in the two forms the two surfaces need.
 *
 * `key` is an ASCII token from a closed set, which is the ONLY form that may reach the event
 * log (`docs/eventlog.md`'s metadata-only rule); nothing here writes one today, and the field
 * exists so that a future record cannot be tempted to log the prose. `sentence` is what a
 * person reads. It never carries a tool argument, a memory body, a validated output, or a
 * grant NAME — a layer's KIND is reportable, its name is not.
 */
export interface Condition {
  readonly key: string;
  readonly sentence: string;
}

/** `1 prompt` / `2 prompts`. Spelled once so the two runtimes cannot disagree twice. */
export function plural(count: number, word: string): string {
  return count === 1 ? `${count} ${word}` : `${count} ${word}s`;
}

/**
 * The size of the writable store's `index.md` on disk, or `null` if it cannot be read.
 *
 * THE STAT, NOT THE PARSE, and the difference is the reason this can run on every tool call.
 * `Memory.indexAccounting()` re-derives the index by reading every fact file — its own
 * docstring says so, and the event log only calls it when a log is actually enabled. A footer
 * that has to decide on EVERY call cannot pay that, so this reads the rendered artefact the
 * store itself keeps up to date (`MemoryStore.rebuildIndex` writes it on every save) with one
 * `stat`.
 *
 * What that trade costs, said plainly: a store whose facts were edited on disk behind the
 * server's back has a stale `index.md`, and this reports the stale size. The condition is a
 * WARNING that the budget is nearly spent, not the budget check itself —
 * `MemoryStore.checkIndexBudget` is still the thing that refuses a save, and it still
 * measures the parse. The two cannot disagree about a store only bantamkit has written.
 *
 * ABSENT IS 0 AND UNREADABLE IS `null`, split on the errno rather than collapsed. A store
 * that has never been saved to has no `index.md` and really does spend nothing of its budget;
 * a store whose directory refuses a `stat` has an unknown index, and reporting that as 0 would
 * claim infinite headroom at exactly the moment there may be none.
 */
export function indexBytes(memory: Memory): number | null {
  try {
    return statSync(join(memory.store.root, 'index.md')).size;
  } catch (e) {
    // `ENOENT` is the reference's `FileNotFoundError`; every other system error is its bare
    // `OSError`. A non-system throw is a bug here and is not swallowed.
    const code = (e as NodeJS.ErrnoException).code;
    if (code === undefined) throw e;
    return code === 'ENOENT' ? 0 : null;
  }
}

/**
 * Is the pack this build loads still there?
 *
 * `buildServer` reads every manifest eagerly at startup, so a server that is RUNNING resolved
 * its pack once. It can still lose it afterwards — an upgrade that replaces the directory, a
 * `BANTAMKIT_ASSETS` pointed at a scratch tree that gets cleaned up — and the failure is
 * quiet: the tool descriptions were read at startup and keep being served, while
 * `resources/read` and every later `loadSkill` have nothing behind them.
 *
 * Deliberately no path in the sentence. `assetsRoot()` resolves to DIFFERENT paths in the two
 * runtimes by construction, so a path here would be the one line of this surface that cannot
 * be compared across them, to buy what `--assets-root` prints on demand.
 */
export function assetPackCondition(): Condition | null {
  let root: string;
  try {
    root = assetsRoot();
  } catch (e) {
    if (!(e instanceof AssetNotFound)) throw e;
    return {
      key: 'asset-pack-missing',
      sentence:
        'the asset pack cannot be resolved at all, so skills, rubrics and tool ' +
        'descriptions have nothing behind them — reinstall the package, or point ' +
        'BANTAMKIT_ASSETS at a real pack and restart the server.',
    };
  }
  if (!isDir(root)) {
    return {
      key: 'asset-pack-missing',
      sentence:
        'the asset pack is gone from where this server resolved it, so skills, ' +
        'rubrics and tool descriptions can no longer be re-read — run ' +
        '`bantamkit-mcp --assets-root` to see where it is looking, then restart.',
    };
  }
  return null;
}

/** `Path.is_dir()`: false for a missing path and for anything that is not a directory. */
function isDir(path: string): boolean {
  try {
    return statSync(path).isDirectory();
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === undefined) throw e;
    return false;
  }
}

/**
 * A memory layer that could not be LISTED — which is not a layer that held nothing.
 *
 * This is the sharpest of the four, because it is the one whose damage is a wrong ANSWER
 * rather than a missing one: `Memory.nothingToReport` already refuses to say "nothing is
 * saved" when a layer is unreadable, but that sentence only reaches a person who happened to
 * run an empty recall. The footer says it on every call.
 *
 * KIND, NEVER NAME. A layer's label is `project`, `extra:<grant name>` or `profile`, and the
 * grant name is the operator's own words for somebody's directory. The kind is the part that
 * is reportable; the split is here rather than at the call site so there is exactly one place
 * it can be got wrong.
 *
 * It reaches `Memory`'s private `layers` and `factCount` through element access on purpose,
 * exactly as the reference reads `_layers` and `_fact_count`. A public accessor would be the
 * right shape and would be a change to the MEMORY layer, which this unit is not authorised to
 * make. Nothing is re-implemented: `factCount` is the same counter `unreadableLayers` uses, so
 * "unreadable" means here exactly what it means to recall.
 */
export function unreadableLayerCondition(memory: Memory): Condition | null {
  const layers = memory['layers'] as ReadonlyArray<readonly [string, MemoryStore, boolean]>;
  const unreadable = layers.filter(([, store]) => Memory['factCount'](store.root) === null);
  if (unreadable.length === 0) return null;
  const kinds = [...new Set(unreadable.map(([label]) => label.split(':')[0]!))].sort();
  return {
    key: 'memory-layer-unreadable',
    sentence:
      `${plural(unreadable.length, 'memory layer')} could not be read ` +
      `(${plural(kinds.length, 'kind')}: ${kinds.join(', ')}), so an empty recall is not ` +
      'evidence that nothing is saved — check that those store directories exist and ' +
      'are readable.',
  };
}

/**
 * The index is nearly as big as the budget that has to hold it.
 *
 * THE REMEDY NAMES THE COMMAND *THIS* INSTALL PROVIDES, and that is the one place this
 * sentence is allowed to differ from `mcpserver.py`'s. The reference spells
 * `python -m bantamkit.memory compact`; a pure-npm install has no `bantamkit.memory` module
 * and no interpreter to run it with, so printing that here would hand the operator a command
 * that cannot run. `runtime-ts` ships the same lifecycle as the `bantamkit-memory` bin
 * (`src/memory/cli.ts`), so that is what is named. Ruled in `docs/porting.md`'s divergence
 * table and pinned on both sides by `tools/conformance/suites/wire.mjs`.
 *
 * IT IS A LITERAL AND NOT AN IMPORT, exactly as the reference's is. `memory/cli.ts`'s `PROG`
 * is the CLI's own name for itself and the MCP server does not import that module — the
 * coupling is held from the OUTSIDE instead, by `runtime-ts/test/server.test.mjs` here and by
 * `tests/test_status_surface.py`'s
 * `test_the_index_remedy_names_the_command_this_install_actually_provides` there.
 *
 * WHAT THE REMEDY DOES NOT PROMISE. `index-budget-low` fires at >= 90% of budget, while
 * `compact` archives only while the index is above `budget - reserve` and `reserve` defaults
 * to the largest surviving index line. So across most of the band that prints this sentence
 * the command exits 0 having archived nothing. That is the SAME arithmetic in both runtimes
 * (`INDEX_PRESSURE_PERCENT` here, `MemoryStore.compact`'s default `reserve` there), so it is
 * not a divergence and is not fixed here; it is registered in `docs/porting.md`. The sentence
 * says "archive or shorten facts", which is what the operator has to do either way.
 */
export function indexPressureCondition(memory: Memory): Condition | null {
  const size = indexBytes(memory);
  const budget = memory.store.indexBudget;
  // INTEGER CROSS-MULTIPLICATION, never `size / budget >= 0.9`. Two runtimes that each
  // rounded their own float could land on opposite sides of the line for the same store,
  // and this comparison is the whole reason they cannot.
  if (size === null || size * 100 < INDEX_PRESSURE_PERCENT * budget) return null;
  return {
    key: 'index-budget-low',
    sentence:
      `the memory index is ${size} bytes of a ${budget}-byte budget, so the next save ` +
      'is close to being refused — archive or shorten facts with ' +
      '`bantamkit-memory compact`.',
  };
}

/**
 * The log was asked for and a record has already been lost.
 *
 * THE `enabled` GUARD IS LOAD-BEARING, not decorative. `writeFailed` is set inside `record`'s
 * `catch` and is never cleared, so a log that was switched on, failed, and was switched off
 * again would still be carrying the flag — and a server whose operator never asked for a log
 * would then report itself degraded for a diagnostic that is not running. Only a log that is
 * BOTH on and known to have lost a record is a problem anyone can act on.
 */
export function eventLogCondition(log: EventLog): Condition | null {
  if (!(log.enabled && log.writeFailed)) return null;
  return {
    key: 'event-log-unwritable',
    sentence:
      'the event log is switched on but a write to it has already failed, so tool ' +
      'outcomes are going unrecorded — check the path in BANTAMKIT_EVENT_LOG and ' +
      'whether its directory is writable.',
  };
}

/**
 * Everything wrong right now, worst first. An empty array means healthy.
 *
 * ORDER IS SEVERITY AND IT IS LOAD-BEARING, because the footer shows the first one: a pack
 * that vanished breaks every asset-backed surface; an unreadable layer makes recall ANSWER
 * WRONGLY rather than fail; a full index refuses the next save; a broken event log costs
 * diagnostics only.
 *
 * EVERY CONDITION IS OBSERVED, NOT INFERRED — no heartbeat, no timer, no last-seen timestamp.
 * Each one is a state a test can construct and then watch this report: delete the pack, make a
 * layer's `facts/` a file, build a store whose index already exceeds nine tenths of its
 * budget, point the log at an unwritable path. A condition that cannot be constructed is not
 * claimed.
 *
 * THE COST, because this runs on every tool call: one `stat` for the index, one `stat` for the
 * pack, one directory listing per memory layer (two to four), and a field read for the log. No
 * fact file is opened and no index is parsed.
 */
export function degradedConditions(memory: Memory, log: EventLog): Condition[] {
  return [
    assetPackCondition(),
    unreadableLayerCondition(memory),
    indexPressureCondition(memory),
    eventLogCondition(log),
  ].filter((condition): condition is Condition => condition !== null);
}

/**
 * The one line other tools' results carry when something is wrong. `''` when nothing is.
 *
 * THE EMPTY STRING FOR A HEALTHY SERVER IS THE WHOLE POINT, and it is checked in a pair: the
 * notice must be present on a degraded call AND absent on a healthy one, because only the pair
 * proves it is conditional. A footer on every result is noise, and noise trains a reader to
 * skip it — at which point the one time it matters it is invisible.
 *
 * ONE SHAPE, ALWAYS, including for a single condition — a count of 1 reads fine, and a second
 * shape is a second thing for the port to get right. The worst condition is spelt out because
 * a bare count is not actionable; the rest are a number and a pointer, because this is a
 * FOOTER on somebody else's answer and has no licence to become the answer.
 */
export function degradedNotice(conditions: readonly Condition[]): string {
  if (conditions.length === 0) return '';
  return (
    `⚠️ bantamkit degraded (${conditions.length}): ${conditions[0]!.sentence} ` +
    'Call `bantamkit_status` for the full report.'
  );
}

/**
 * The whole answer `bantamkit_status` returns — prose, for a person, in a transcript.
 *
 * THE FIRST LINE IS THE ANSWER and it is the line the operator asked for by name:
 * `bantamkit Active 🟢`, or `bantamkit Degraded 🟠` when `conditions` is non-empty. A reader
 * who stops after eight characters has still learned the thing they came for.
 *
 * THE ONE FIELD THAT IS NOT COMPARABLE ACROSS RUNTIMES is `build`. It is `build_id`, a
 * fingerprint of the running source, and the two runtimes fingerprint two different trees by
 * construction — `docs/porting.md`'s divergence table already rules exactly this. It is here
 * anyway because "which bantamkit" is half the question this tool exists to answer: two
 * endpoints registered under one name is the situation RB-P84 filed, and a version string
 * cannot tell them apart.
 *
 * `identity` ARRIVES AS AN ARGUMENT rather than being built here, which is the one shape
 * difference from the reference. `buildIdentity` needs the package version and the SDK version
 * — both of which the server resolves and neither of which this module can see — so the
 * alternative was a cycle between this file and `server.ts`. Nothing about the report changes:
 * it reads the same two fields off the same object the `build_identity` tool answers with.
 *
 * NO ARGUMENT VALUE CAN REACH THIS. The tool takes none, and every input above is server state.
 */
export function statusReport(
  memory: Memory,
  log: EventLog,
  conditions: readonly Condition[],
  identity: ReadonlyMap<string, unknown>,
  tools: number,
  prompts: number,
  templates: number,
): string {
  const build = identity.get('build_id');
  const facts = Memory['factCount'](memory.store.root);
  const size = indexBytes(memory);
  const budget = memory.store.indexBudget;
  const lines = [
    `bantamkit ${conditions.length > 0 ? 'Degraded 🟠' : 'Active 🟢'}`,
    `version ${identity.get('version') as string}, build ` +
      (typeof build === 'string' ? build : 'unavailable'),
    `serving ${plural(tools, 'tool')}, ${plural(prompts, 'prompt')}, ` +
      `${plural(templates, 'resource template')}`,
    'memory: ' +
      (facts === null
        ? 'the project store could not be read'
        : `${plural(facts, 'fact')} in the project store`) +
      ', index ' +
      (size === null ? 'unreadable' : String(size)) +
      ` of ${budget} bytes`,
    `event log: ${log.enabled ? 'on' : 'off'}`,
  ];
  if (conditions.length > 0) {
    lines.push(`${plural(conditions.length, 'problem')}:`);
    for (const condition of conditions) lines.push(`- ${condition.sentence}`);
  }
  return lines.join('\n');
}
