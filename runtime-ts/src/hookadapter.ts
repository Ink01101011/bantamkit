/**
 * The Claude Code HOOK adapter. One module, every event, dispatched on `hook_event_name`.
 *
 * MOVED HERE 2026-09-20 (job61, J61-2) FROM `tools/hooks/bantamkit-hook.mjs`, AND THE MOVE IS
 * THE POINT. The adapter worked and was unreachable from the product: `tools/` is not in the
 * npm package. Measured at 0.35.3 with `npm pack --dry-run` — 174 files in the tarball,
 * `package.json` declaring `files: ["dist","assets"]`, and zero entries matching `hook`. So an
 * operator who installed bantamkit the only way it is published (`npx bantamkit-mcp`) had no
 * adapter on disk at all, and `docs/hooks.md`'s registration line could not be written without
 * a checkout. Living in `src/` puts it in `dist/`, which ships, and `bantamkit-mcp --hook` is
 * the surface that reaches it.
 *
 * `src/` IS TYPESCRIPT, WHICH IS WHY THIS IS A PORT AND NOT A COPY. `tsconfig.json` sets
 * `include: ["src"]` and no `allowJs`, so a `.mjs` dropped into `src/` would be neither
 * compiled nor copied to `dist/` and would still not ship. There is exactly ONE adapter after
 * this change: `tools/hooks/bantamkit-hook.mjs` is now a four-line shim onto this module, so
 * the registration in every operator's `~/.claude/settings.json` keeps working and there is no
 * second copy to drift.
 *
 * WHY THIS EXISTS AT ALL. Measured 2026-08-27 over the host's own MCP logs, last 7 days: 103
 * bantamkit connections, 8 `memory_recall` calls, 3 of them outside this repo. An MCP
 * server is PASSIVE — nothing in the host invokes a tool the model did not decide to call,
 * and the model does not decide to call a recall whose answer already rides free in the
 * system prompt. Hooks are the only deterministic channel the host offers, so the
 * automatic half of the toolbox — recall before the turn, refuse a repeat read, nudge a
 * save before the session ends, compact the index when it is nearly full — lives HERE,
 * at the host boundary, and the MCP tools stay what the model calls when it wants more.
 *
 * THE THREE PROPERTIES, same as the statusline adapter beside it:
 *   1. CHEAP. Loads the memory layer in-process; never starts an MCP server.
 *   2. NEVER LOUD. Every arm ends in exit 0. A hook that throws would be rendered by the
 *      host as an error on the user's screen, so every failure is LOGGED and swallowed.
 *   3. MEASURED. Every decision appends one line to `~/.bantamkit/hooks/hook-log.jsonl`
 *      (event, action, bytes injected, ms) so the claim "it fires and it is cheap" is a
 *      number the user can rerun, not a sentence.
 *
 * THE CONTRACT THE FLAG PINS, and it is deliberately narrow so both runtimes can be compared:
 * one JSON object in on stdin, AT MOST ONE JSON object out on stdout, exit 0 ALWAYS.
 *
 * Registration (user scope, `~/.claude/settings.json`): see `docs/hooks.md`.
 * Pure Node, POSIX + Windows; nothing here shells Python.
 */
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { Memory } from './memory/component.js';
import { discoverProjectStore, resolveProjectStore } from './memory/layers.js';
import { DURABLE_TYPES, MemoryStore, RECALL_MIN_SCORE_RATIO, pyEqualValue, pyText, tokens } from './memory/store.js';
import type { Fact } from './memory/store.js';
import { keptManifest, keptPrefix } from './npminstall.js';
import {
  decide as decideUpdate,
  KEY as UPDATE_KEY,
  loadRecord,
  PROGRAM as UPDATE_PROGRAM,
  recordPath,
  STATE_AVAILABLE,
  type State as UpdateState,
} from './updatecheck.js';

/**
 * The directory `p` names, as the KERNEL names it. `realpathSync.native`, not `realpathSync`.
 *
 * Added 2026-09-11 (J47-7); the mechanism is J47-3B's (`6766033`) and the reason is the same.
 * `fs.realpathSync` hands its argument to `path.resolve` before it resolves anything, and
 * `path.resolve` pops `..` LEXICALLY — before the symlink in front of it has been followed —
 * so it throws `ENOENT` on a directory that is there. `realpathSync.native` is libuv's
 * `uv_fs_realpath`, the platform's own `realpath(3)` / `GetFinalPathNameByHandle`: it pops
 * `..` in the kernel's order, agrees with `os.path.realpath` byte for byte, and keeps the
 * macOS `/var` vs `/private/var` resolution every comparison in this file was written for.
 * `statSync` identity (`dev` + `ino`) was the other candidate and was not taken, for J47-3B's
 * reason: `ino` is not dependable on every Windows filesystem, and this file runs there too.
 *
 * A path that is genuinely not on disk cannot be realpathed at all, and `path.resolve` is the
 * fallback — it can only under-report a match, never invent one.
 */
function realDir(p: string): string {
  try {
    return fs.realpathSync.native(p);
  } catch {
    return path.resolve(p);
  }
}

const T0 = Date.now();
// HOME IS RESOLVED, NOT TAKEN AS SPELLED (2026-09-11, J47-7). `os.homedir()` hands back
// `$HOME` verbatim, and every `path.join` below pops a `..` inside it LEXICALLY. Measured on
// J47-3B's bed (`link -> <bed>/deep/real`, `HOME=<bed>/link/..`, the real home being
// `<bed>/deep`): `PROFILE` came out `<bed>/.bantamkit/memory`, a directory nothing had
// created, so the single-layer guard at the bottom of this file could not answer `true` no
// matter what predicate it used — and `STATE` put this hook's own log OUTSIDE the home. One
// kernel-order resolution here fixes both, and for a `HOME` with no symlink and no `..` it
// is the identity.
//
// IT IS READ PER RUN, NOT AT MODULE LOAD. `--hook` is one short-lived process, so the two are
// the same in production; but `HOME` is also the seam every test in `hooks.test.mjs` and
// `hookadapter.test.mjs` points at a scratch directory, and a module-level constant would
// freeze whatever the FIRST import saw. `runHook()` takes the reading once, at the top.
function homeDir(): string {
  return realDir(os.homedir());
}

/** This module's own directory: `<package>/dist` in an install, `runtime-ts/dist` in a checkout. */
const HERE = path.dirname(fileURLToPath(import.meta.url));
/** The built memory layer, beside this module. Was `<repo>/runtime-ts/dist/memory`. */
const DIST = path.join(HERE, 'memory');

// Budgets, in BYTES of injected context. SessionStart is paid once; UserPromptSubmit is
// paid on every later call of the session, which is why it is the small one.
const SESSION_INJECT_MAX = 3000;
const PROMPT_INJECT_MAX = 700;
const PROMPT_MIN_CHARS = 12;
const STOP_NUDGE_MIN_TOOL_CALLS = 20;
const COMPACT_AT = 0.9; // index >= 90% of budget → compact …
const COMPACT_TO = 0.8; // … down to 80%, past the no-op band measured in job40 (C6)
//
// AMENDED 2026-09-10 (job46, J46-6). The half-sentence "past the no-op band measured in
// job40 (C6)" is a record of a defect that is now CLOSED, and it stays because it is why
// this number exists at all. `docs/porting.md` register item 7 was that band: the degraded
// report warned at COMPACT_AT and named `compact`, while `compact`'s default target sat at
// `budget - largest index line`, so between the two the command archived nothing. Both
// runtimes closed it in job46 (`87cc1f7`, `55575c3`) by measuring the default reserve from
// the warning line instead of from the budget.
//
// COMPACT_TO STAYS, and NOT because the workaround is harmless — it is not. What it was
// doing was naming a budget this store does not have (0.8 * budget) so that `compact` would
// aim below the real one. Now that `compact` derives its own floor FROM the budget it is
// given, that lie COMPOUNDS: the aim became 0.9 * (0.8 * budget) - largest line. MEASURED on
// a read-only copy of this machine's project store (101 facts, 21819 bytes, largest index
// line 361, budget 24000), one auto-compaction:
//
//     before job46, `--budget 19200`, default reserve : target 18839, archived 15
//     after  job46, `--budget 19200`, default reserve : target 16918, archived 23
//     today,        `--budget 24000 --reserve 4800`   : target 19200, archived 13
//
// So the arm was quietly archiving eight more of the user's facts per fire than the 80% it
// advertises, and landing 2379 bytes below the number its own message prints. The fix is not
// to drop the aim — 80% is the HYSTERESIS that keeps this arm from re-firing on the next
// save, which matters more now that the default target sits just under the warning line — it
// is to ask for the aim in the argument that MEANS it. `--reserve` is the documented escape
// hatch from the new floor (both runtimes, both conformance suites), so the hook now names
// the real budget and the headroom it wants, and gets `budget - reserve` exactly. That is
// also why this is the durable spelling: it cannot be moved again by a future change to the
// DEFAULT reserve, which is exactly what moved it this time.

// PreCompact's steering, in BYTES. This string is paid TWICE: once as the summariser's
// `newCustomInstructions`, and once echoed onto the user's screen as
// `PreCompact [<command>] completed successfully: <output>` — the same bytes are both the
// steering and the display, and there is no quieter variant (see the channel note below).
// Unbounded, the arm's own worst case is PRECOMPACT_FILES_MAX absolute paths, and a single
// malformed unit title put 35,315 B on the user's screen in one probe. 4000 B is the bound:
// a third more than SESSION_INJECT_MAX, which buys the checkpoint line and the tail on top
// of a useful slice of the list, and it is paid per compaction rather than per prompt. The
// FIXED lines are never cut; the file list absorbs the whole trim.
const PRECOMPACT_STDOUT_MAX = 4000;
const PRECOMPACT_FILES_MAX = 40;
const CHECKPOINT_LINE_MAX = 600; // one checkpoint line: an absolute path, a cursor, a title

// The host kills the WHOLE hook at 10 s (`timeout: 10` in the registration), so the child's
// bound has to sit under that. A measured consolidation of the 121 facts on this machine
// took 72 ms, so the headroom is two orders of magnitude.
//
// THE ENV OVERRIDE IS A TEST SEAM AND NOTHING ELSE. Without it the timeout is a constant no
// test can reach, and this repo has been bitten twice by arithmetic in this file that drifted
// because nothing ran it. With it, `hooks.test.mjs` sets a 1 ms bound and exercises a REAL
// SIGTERM kill of a real child, which is the only way to show that a slow pass degrades to a
// log line instead of eating the session.
function dreamTimeoutMs(): number {
  return Number(process.env['BANTAMKIT_DREAM_TIMEOUT_MS']) || 8000;
}

// ---------------------------------------------------------------- the payload

/**
 * The host's hook payload. Every field is optional because the host sends a DIFFERENT shape
 * per event and this module is handed whatever arrives — including, on a malformed line,
 * nothing at all. Narrowing happens in the arm that needs the field, never here.
 */
export interface HookInput {
  hook_event_name?: string;
  session_id?: string;
  transcript_path?: string;
  cwd?: string;
  source?: string;
  prompt?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  tool_use_id?: string;
  trigger?: string;
  stop_hook_active?: boolean;
}

/** One `hook-log.jsonl` record, before the `ts`/`ms` stamp is prepended. */
type LogRecord = Record<string, unknown>;

/**
 * Everything one `--hook` process carries between its arms.
 *
 * It was module state when this was a standalone script, and it may not be here: `dist/` is
 * imported by the server too, and a module-level `HOME` would be whatever the FIRST import
 * saw. One object, threaded, is also what makes `STORE_SCOPE` (below) not a global.
 */
interface HookRun {
  readonly home: string;
  readonly state: string;
  readonly log: string;
  readonly profile: string;
  readonly dreamState: string;
  /** The scope whose entry pinned the store this process binds, for the log. */
  storeScope: string | null;
}

function newRun(): HookRun {
  const home = homeDir();
  const state = path.join(home, '.bantamkit', 'hooks');
  return {
    home,
    state,
    log: path.join(state, 'hook-log.jsonl'),
    profile: path.join(home, '.bantamkit', 'memory'),
    dreamState: path.join(state, 'dream-state.json'),
    storeScope: null,
  };
}

function log(run: HookRun, record: LogRecord): void {
  try {
    fs.mkdirSync(run.state, { recursive: true });
    fs.appendFileSync(
      run.log,
      `${JSON.stringify({ ts: new Date().toISOString(), ms: Date.now() - T0, ...record })}\n`,
    );
  } catch {
    /* logging is best-effort */
  }
}

function emit(obj: unknown): void {
  process.stdout.write(JSON.stringify(obj));
}

/**
 * PLAIN stdout, for the events whose steering the host reads as text rather than as the
 * `hookSpecificOutput` envelope. See `preCompact` for why that distinction is not cosmetic.
 *
 * It used to carry a leading-`{` refusal here. That branch could not fire — every part
 * `preCompact` assembles begins with one of three constant prefixes — and had it ever
 * fired it would have DROPPED the whole steering with no trace, which is the exact failure
 * this arm exists to have fixed. The channel contract it was guarding ("output that does not
 * start with `{` is taken as plain text") is now pinned where it can actually go red: the
 * `hooks.test.mjs` case "the steering never starts with { — for every shape of input the
 * arm accepts", which drives user-controlled strings (a `{braces}` path, a `{odd}.json`
 * checkpoint, a `{C}` cursor) through the real dispatch and judges stdout the way the host
 * does. Returns the number of bytes ACTUALLY written, so the caller's log line cannot claim
 * bytes that never left the process.
 */
function emitText(text: string): number {
  const out = String(text).trim();
  if (!out) return 0;
  process.stdout.write(out);
  return Buffer.byteLength(out);
}

/** Truncate to at most `max` BYTES without splitting a UTF-8 character. */
function capBytes(text: string, max: number): string {
  const buf = Buffer.from(String(text), 'utf8');
  if (buf.length <= max) return String(text);
  let end = max;
  while (end > 0 && ((buf[end] ?? 0) & 0xc0) === 0x80) end -= 1; // back off a continuation byte
  return buf.subarray(0, end).toString('utf8');
}

function capLines(text: string, max: number): string {
  if (Buffer.byteLength(text) <= max) return text;
  const out: string[] = [];
  let size = 0;
  for (const line of text.split('\n')) {
    const n = Buffer.byteLength(line) + 1;
    if (size + n > max) break;
    out.push(line);
    size += n;
  }
  return out.join('\n');
}

// ------------------------------------------------------------------- the ledger

interface ReadRecord {
  sig: string;
  at: string;
  count: number;
  refused: boolean;
  transcript?: string;
  file?: string;
}

interface Ledger {
  reads: Record<string, ReadRecord>;
  saved?: number;
  stopNudged?: boolean;
}

function ledgerPath(run: HookRun, sessionId: string | undefined): string {
  return path.join(run.state, `ledger-${String(sessionId || 'nosession').replace(/[^\w-]/g, '_')}.json`);
}

function readLedger(run: HookRun, sessionId: string | undefined): Ledger {
  try {
    const parsed = JSON.parse(fs.readFileSync(ledgerPath(run, sessionId), 'utf8')) as Ledger;
    if (!parsed || typeof parsed !== 'object') return { reads: {} };
    if (!parsed.reads || typeof parsed.reads !== 'object') parsed.reads = {};
    return parsed;
  } catch {
    return { reads: {} };
  }
}

function writeLedger(run: HookRun, sessionId: string | undefined, ledger: Ledger): void {
  fs.mkdirSync(run.state, { recursive: true });
  fs.writeFileSync(ledgerPath(run, sessionId), JSON.stringify(ledger));
}

// ------------------------------------- the host's auto-memory directory, and A's export
//
// WHAT THIS REPLACED, AND WHY IT HAD TO GO (2026-09-20, job62 / J62-6). Until this change the
// question "does the host have an auto-memory store here" was answered by
//
//     const slug = cwd.replace(/[\\/:]/g, '-');
//     fs.existsSync(path.join(run.home, '.claude', 'projects', slug, 'memory', 'MEMORY.md'))
//
// — an incomplete reimplementation of Claude Code's own slug, on the hook path. S0
// (`.shiftwork/notes-job62/S0-prep-probe.md`) dumped the real resolver out of `2.1.278`:
//
//     resolveEntry() = CLAUDE_COWORK_MEMORY_PATH_OVERRIDE
//                   ?? autoMemoryDirectory from policySettings, flagSettings,
//                      [localSettings, projectSettings], userSettings   (in that order)
//                   ?? defaultPath()
//     defaultPath()  = join(<root>, "projects", ok(gitRoot(projectRoot) ?? projectRoot), "memory")
//     ok(e)          = k(e).length <= 200 ? k(e) : k(e).slice(0,200) + "-" + base36(hash(e))
//
// Three things the old rule is missing, and each one is a wrong answer on a real machine: the
// 200-character cap with its base36 hash suffix; the four-branch precedence in front of
// `defaultPath` at all; and — the one that matters most here — the KEY, which is the
// canonicalized git WORKTREE ROOT and not the session cwd. Job62 itself runs inside a
// worktree, which is precisely the case the old rule gets wrong.
//
// The fix is not a better slug. RULING Q1.2/Q1.6 of `.shiftwork/notes-job62/S1-delivery-path.md`
// forbids reimplementing `oS`/`ok`/`Gr` at all, because re-deriving a four-branch resolver from
// a minified binary is the exact instruction/surface drift job60 built its gate to stop. A
// learns the directory by OBSERVATION WITH VERIFICATION instead, and when no branch answers it
// exports nothing rather than guessing (RULING Q1.3): a directory at a slug the host does not
// resolve to is a store nobody reads and nobody prunes.
//
// `native_store_root()` in `runtime-py/src/bantamkit/memory/divergence.py` is a DIFFERENT
// function, off the MCP path, and RULING Q1.6 leaves it exactly where it is.

/** The file whose presence makes a candidate directory an ANSWER rather than a guess. */
const NATIVE_INDEX = 'MEMORY.md';
/** The host's top-precedence branch, and the one on the MCP passthrough allowlist. */
const NATIVE_OVERRIDE_ENV = 'CLAUDE_COWORK_MEMORY_PATH_OVERRIDE';
/**
 * The one heading in the host's index that A writes under.
 *
 * A owns this line and nothing else in the file. It does NOT sort its entries into the host's
 * own sections, because the host's taxonomy is the host's to change and a writer that guesses
 * at it has to keep guessing right forever. One heading, appended once, at the end.
 */
const NATIVE_SECTION = '## bantamkit';
/** Names exported per hook run. The binding bound in practice; see `exportToNative`. */
const NATIVE_EXPORT_MAX = 10;
/**
 * Bytes A may append to `MEMORY.md` per hook run.
 *
 * This is the budget that means anything, because these are the only bytes the export puts in
 * front of the model: the host injects its index, and reads a fact file only when something
 * asks for it. 2000 B is two thirds of `SESSION_INJECT_MAX`, paid at most once per session and
 * — unlike an injection — never paid again for a name already there.
 */
const NATIVE_INDEX_BYTES_MAX = 2000;
/**
 * A fact name A is willing to join into a path.
 *
 * `MemoryStore.save` enforces `^[a-z0-9][a-z0-9-]*$`, but `facts()` does NOT revalidate on
 * READ — measured 2026-09-20: a hand-written `facts/*.md` whose frontmatter says
 * `name: ../escape` parses and is handed out with that name. So this guard is reachable from
 * disk, and `nativeexport.test.mjs` drives it with exactly that file.
 */
const NATIVE_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

/** The host's own auto-memory directory, and which branch named it. */
interface NativeMemory {
  /** The directory, or `null` when no branch answered. */
  dir: string | null;
  branch: 'env' | 'settings' | 'transcript' | 'unknown';
  /** The branches tried and REJECTED, in order — the one line RULING Q1.3 asks for. */
  tried: string[];
}

/** `p` is a regular file this process can read. Not "exists": a directory is not an index. */
function readableFile(p: string): boolean {
  try {
    if (!fs.statSync(p).isFile()) return false;
    fs.accessSync(p, fs.constants.R_OK);
    return true;
  } catch {
    return false;
  }
}

/**
 * `os.path.lexists`: something is AT this path, symlink or not.
 *
 * `existsSync` follows links, so a dangling symlink would read as absent and A would write
 * THROUGH it into whatever it points at. A dangling link is an entry A did not create, and
 * "absent" is the only condition under which A writes.
 */
function lexists(p: string): boolean {
  try {
    fs.lstatSync(p);
    return true;
  } catch {
    return false;
  }
}

/**
 * RULING Q1.2 — the four branches, first one that ANSWERS wins.
 *
 *   1. `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE`, non-empty → that value IS the directory, with no
 *      verification: it is the host's own top-precedence branch, so there is nothing above it
 *      that could overrule what A sees.
 *   2. `autoMemoryDirectory` from `<home>/.claude/settings.json` ONLY. A CANDIDATE, never an
 *      answer: three higher-precedence sources exist in the host (`policySettings`,
 *      `flagSettings`, and the env var) that A cannot read, so the candidate is accepted only
 *      when it holds a readable `MEMORY.md`.
 *   3. `dirname(transcript_path)/memory`, with the same `MEMORY.md` test. This is reading back
 *      the slug the HOST computed, which is the whole distinction invariant 5 is about.
 *   4. UNKNOWN. No fallback slug, no mkdir.
 *
 * Branch 3 is why A is a rider on B and not a feature of its own (RULING Q1.4): only a hook
 * receives `transcript_path`.
 */
function resolveNativeMemory(run: HookRun, input: HookInput): NativeMemory {
  const tried: string[] = [];

  const override = String(process.env[NATIVE_OVERRIDE_ENV] ?? '').trim();
  if (override) return { dir: override, branch: 'env', tried };
  tried.push('env');

  try {
    const raw = fs.readFileSync(path.join(run.home, '.claude', 'settings.json'), 'utf8');
    const settings = JSON.parse(raw) as Record<string, unknown>;
    const configured = settings['autoMemoryDirectory'];
    if (typeof configured === 'string' && configured.trim()) {
      const dir = configured.trim();
      if (readableFile(path.join(dir, NATIVE_INDEX))) return { dir, branch: 'settings', tried };
    }
  } catch {
    /* no settings file, unreadable, or not JSON — all of them mean "this branch has no answer" */
  }
  tried.push('settings');

  const transcript = String(input.transcript_path ?? '').trim();
  if (transcript) {
    const dir = path.join(path.dirname(transcript), 'memory');
    if (readableFile(path.join(dir, NATIVE_INDEX))) return { dir, branch: 'transcript', tried };
  }
  tried.push('transcript');

  return { dir: null, branch: 'unknown', tried };
}

/** What one export run did, in numbers the operator can rerun the arm against. */
interface NativeExport {
  /** Names for which SOMETHING was written this run. */
  exported: number;
  files: number;
  indexLines: number;
  bytes: number;
  indexBytes: number;
  skipped: string[];
  /** Whether the host's index was there to append to. A never creates it. */
  index: 'present' | 'absent';
  error?: string;
}

/**
 * Whitespace collapsed to single spaces, then trimmed.
 *
 * THE CLASS IS SPELLED OUT rather than `\s`, and the Python half must spell it the same way:
 * `\s` is not the same set in the two languages (JavaScript's includes NBSP, BOM and the
 * Unicode separators; Python's `str` pattern includes its own list), so a description carrying
 * one of those characters would be exported differently by the two runtimes — a divergence
 * invented by a helper nobody would think to compare.
 */
function collapseWhitespace(text: string): string {
  return String(text)
    .replace(/[ \t\n\r\f\u000b]+/g, ' ')
    .trim();
}

/**
 * One exported file, in the host's own auto-memory shape: `name`, `description`,
 * `metadata.type`, and a body.
 *
 * THE BODY IS NOT THE FACT'S BODY, and the unit is titled for it: A exports DESCRIPTIONS. The
 * file is an entry that names where the body lives, for two reasons. The description is what
 * the host injects; and copying a user's fact bodies into a store whose dream rewords and
 * deletes them would be duplicating the user's data into a place bantamkit does not own.
 *
 * `metadata.source: bantamkit` is provenance, so an operator reading this directory can see at
 * a glance which entries are exports. Nothing reads it back — RULING Q1.5 forbids A treating
 * its own writes as state, and the test that deletes both halves and re-runs pins that.
 *
 * The description is a JSON string, which is a valid YAML 1.2 double-quoted scalar, so the
 * escaping needs no YAML writer on either side. `json.dumps(desc, ensure_ascii=False)` agrees
 * with `JSON.stringify` byte for byte on this input.
 */
function nativeFactText(name: string, type: string, description: string): string {
  return [
    '---',
    `name: ${name}`,
    `description: ${JSON.stringify(description)}`,
    'metadata:',
    '  node_type: memory',
    `  type: ${type}`,
    '  source: bantamkit',
    '---',
    '',
    "Exported from bantamkit's project memory store. The body of this fact is not here: call",
    `\`mcp__bantamkit__memory_recall\` with the name \`${name}\` to read it.`,
    '',
    'Written once, only because the name was absent from this directory. bantamkit never',
    'rewrites and never deletes an entry here, so whatever the host does to this file stands.',
    '',
  ].join('\n');
}

/** One index line, in the host's own index shape. The em dash is a raw U+2014. */
function nativeIndexLine(name: string, description: string): string {
  return `- [${name}](${name}.md) — ${description}\n`;
}

/**
 * A — the export, one way and non-destructive (RULING Q1.5).
 *
 * WRITE A NAME ONLY WHEN IT IS ABSENT. The two halves are gated INDEPENDENTLY: the fact file
 * is written when nothing is at its path, the index line is appended when `](<name>.md)` does
 * not appear in the index. They are independent because job59 measured Claude Code's own dream
 * rewording or removing 8 of 8 foreign index lines and deleting one file, so the two halves
 * really do go missing separately, and A must do exactly the one thing that is missing.
 *
 * A NEVER READS BACK ITS OWN WRITES AS STATE. The presence check above is not "did we export
 * this" — it is "is this name in the host's directory right now", which is the write-when-absent
 * predicate itself. When the dream removes an entry, A puts it back next session; when the
 * dream REWORDS one, A leaves it alone, because the name is still there. Any later unit that
 * wants "have we exported X" must answer it from bantamkit's own store.
 *
 * A NEVER CREATES ANYTHING THE HOST WOULD NOT HAVE. No `mkdir`, and no `MEMORY.md`: when the
 * index is absent (reachable only through branch 1, which accepts its directory unverified)
 * the files are written and no index is conjured into existence.
 *
 * ORDER IS `SESSION_DROP_RULE`, the same order the session block keeps facts in, so a store
 * larger than one run's budget exports its most durable and most recently used facts first and
 * the rest on later sessions. A failed write is caught, recorded and ends the run: an arm whose
 * whole posture is exit 0 does not get to throw, and retrying every remaining name against a
 * directory that just refused one is spending syscalls to learn the same thing again.
 */
function exportToNative(dir: string, store: string): NativeExport {
  const result: NativeExport = {
    exported: 0,
    files: 0,
    indexLines: 0,
    bytes: 0,
    indexBytes: 0,
    skipped: [],
    index: 'absent',
  };
  const indexFile = path.join(dir, NATIVE_INDEX);
  let seeded = '';
  if (readableFile(indexFile)) {
    try {
      seeded = fs.readFileSync(indexFile, 'utf8');
      result.index = 'present';
    } catch {
      /* readable a moment ago, not now: treat it as absent rather than as empty */
    }
  }
  let named = seeded;
  const appended: string[] = [];
  try {
    const { facts, indexLine } = new MemoryStore(store).internals();
    const ranked = rankBySessionDropRule(
      facts().map((fact, position) => ({
        fact,
        position,
        line: indexLine(fact),
        name: pyText(fact.name),
      })),
    );
    for (const f of ranked) {
      if (result.exported >= NATIVE_EXPORT_MAX) break;
      const name = f.name;
      if (!NATIVE_NAME_RE.test(name) || name === 'MEMORY') {
        result.skipped.push(name);
        continue;
      }
      const file = path.join(dir, `${name}.md`);
      const needFile = !lexists(file);
      const needLine = result.index === 'present' && !named.includes(`](${name}.md)`);
      if (!needFile && !needLine) continue;
      const description = collapseWhitespace(f.fact.description == null ? '' : pyText(f.fact.description));
      const line = needLine ? nativeIndexLine(name, description) : '';
      if (result.indexBytes + Buffer.byteLength(line) > NATIVE_INDEX_BYTES_MAX) break;
      if (needFile) {
        const text = nativeFactText(name, pyText(f.fact.type), description);
        fs.writeFileSync(file, text, { flag: 'wx' });
        result.files += 1;
        result.bytes += Buffer.byteLength(text);
      }
      if (needLine) {
        appended.push(line);
        named += line;
        result.indexLines += 1;
        result.indexBytes += Buffer.byteLength(line);
        result.bytes += Buffer.byteLength(line);
      }
      result.exported += 1;
    }
    if (appended.length) {
      // The heading is emitted only when the file does not already carry it as a whole LINE,
      // so a second session appends under the first session's heading. If the host later moves
      // that heading, A's later lines land at the end of the file rather than under it — a
      // cosmetic limit, accepted, because the alternative is A rewriting the host's index.
      const separator = seeded.endsWith('\n') ? '' : '\n';
      const heading = seeded.split('\n').includes(NATIVE_SECTION) ? '' : `\n${NATIVE_SECTION}\n\n`;
      fs.appendFileSync(indexFile, `${separator}${heading}${appended.join('')}`);
    }
  } catch (e) {
    result.error = message(e);
  }
  return result;
}

// The rule a capped session block keeps facts by, in the words the block, the log and
// `docs/hooks.md` all quote. Until J50-2E (2026-09-12) the block was `capLines` over the
// store's index text, so what was dropped was whatever sorted LAST in the index — the
// alphabet, not any property of the fact. Reproduced on this machine's 20-fact profile
// store: the header said 20, the body carried 15, and the two facts the user had written
// to say that every job ends measured and that verification comes from a run were among
// the five nobody was told about. The rule below is the store's own eviction order
// (`MemoryStore.byEviction`) read backwards — the facts `compact` would archive LAST are the
// ones a session should see FIRST — so the hook invents no new notion of worth: durable
// types (`DURABLE_TYPES`) before decaying ones, then the most recent evidence of use
// (`last_recalled`, falling back to `created`), then name. Inside one class the date is
// the ONLY signal a fact carries on disk, and `last_recalled` is stamped by the recall path
// before its own byte cap (J49-B3), so this is a stated rule, not a claim of importance.
const SESSION_DROP_RULE =
  'durable types first, then most recently recalled (else created) first, then name';

interface IndexedFact {
  fact: Fact;
  position: number;
  line: string;
  name: string;
}

interface CappedIndex {
  block: string;
  total: number;
  injected: number;
  dropped: string[];
  facts?: number;
}

/**
 * The index of `root` as ONE capped block: a header whose number is the number of fact
 * lines IN the block, the fact lines that fit under `max` bytes, and — only when something
 * did not fit — one disclosure line saying how many are missing and where they are named.
 *
 * Selection walks the facts in `SESSION_DROP_RULE` order and keeps each one whose whole
 * index line still fits; a line that does not fit is skipped, never split, and never a
 * barrier for a shorter one after it. The kept lines are then shown in the index's own
 * order, so a block that lost nothing is byte-for-byte the index text, as before. The lines
 * come from `MemoryStore.internals().indexLine`, the same function `indexText` joins, so
 * the block never says a fact differently from the index the runtime would write.
 *
 * `header(count)` is handed `"15 of 20"` when something was dropped and `"20"` when not, so
 * a reader who sees a bare number knows the block is whole.
 */
/**
 * `SESSION_DROP_RULE` as a sort, extracted 2026-09-20 (J62-6) so that the session block and
 * A's export cannot come to disagree about which facts matter most.
 *
 * It was inline in `cappedIndex` and had exactly one caller; the export is the second, and a
 * second copy of a four-key comparator is how "the same rule" stops being the same rule.
 */
function rankBySessionDropRule(all: readonly IndexedFact[]): IndexedFact[] {
  const text = (value: unknown): string => (value == null ? '' : pyText(value));
  const decays = (f: IndexedFact): number =>
    DURABLE_TYPES.some((durable) => pyEqualValue(f.fact.type, durable)) ? 0 : 1;
  const evidence = (f: IndexedFact): string => text(f.fact.last_recalled) || text(f.fact.created);
  const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
  return [...all].sort(
    (a, b) =>
      decays(a) - decays(b) || cmp(evidence(b), evidence(a)) || cmp(a.name, b.name) || a.position - b.position,
  );
}

function cappedIndex(root: string, header: (count: string) => string, max: number): CappedIndex {
  const { facts, indexLine } = new MemoryStore(root).internals();
  const all: IndexedFact[] = facts().map((fact, position) => ({
    fact,
    position,
    line: indexLine(fact),
    name: pyText(fact.name),
  }));
  const ranked = rankBySessionDropRule(all);
  const kept = new Set<IndexedFact>();
  let size = 0;
  for (const f of ranked) {
    const n = Buffer.byteLength(f.line);
    if (size + n > max) continue;
    kept.add(f);
    size += n;
  }
  const shown = all.filter((f) => kept.has(f));
  const dropped = ranked.filter((f) => !kept.has(f)).map((f) => f.name);
  const body = capLines(
    shown
      .map((f) => f.line)
      .join('')
      .replace(/\n$/, ''),
    max,
  );
  const lines = [header(dropped.length ? `${shown.length} of ${all.length}` : String(all.length))];
  if (body) lines.push(body);
  if (dropped.length) {
    lines.push(
      `[${dropped.length} of ${all.length} not shown — the block is capped at ${max} bytes; kept by rule: ${SESSION_DROP_RULE}; ~/.bantamkit/hooks/hook-log.jsonl names the dropped; mcp__bantamkit__memory_recall reads any fact by name]`,
    );
  }
  return { block: lines.join('\n'), total: all.length, injected: shown.length, dropped };
}

function countFacts(store: string): number {
  try {
    return fs.readdirSync(path.join(store, 'facts')).filter((n) => n.endsWith('.md')).length;
  } catch {
    return 0;
  }
}

// ------------------------------------------------------- the stale-install signal
// Reader 2 and Writer 1 of `docs/superpowers/specs/2026-09-19-stale-version-signal-design.md`.
// One line at SessionStart when the install this hook can SEE is older than what the package
// index serves, and a detached probe that keeps the record it reads from fresh.
//
// NOTHING ON THIS PATH REACHES THE NETWORK. The line is decided from one file on disk; the
// only thing here that asks a registry anything is `update-probe.mjs`, which is spawned
// `detached` with `stdio: 'ignore'` and never waited for. That is the whole design: measured
// 2026-09-19, one registry GET is 0.14-0.46 s on a good network and 10.0 s on a captive one,
// against a 0.09 s cold server boot, so a fetch anywhere on this function's path would be a
// visible pause at the top of every session for a fact that is not urgent.

/**
 * The detached writer, which lives in the CHECKOUT and not in the package.
 *
 * `tools/hooks/update-probe.mjs` is 239 lines that no operator running `npx bantamkit-mcp`
 * has on disk, for the same measured reason this module moved: `files: ["dist","assets"]`.
 * Resolved relative to THIS module, `../../tools/hooks/update-probe.mjs` is the repo path in
 * a checkout (`<repo>/runtime-ts/dist` → `<repo>/tools/hooks`) and is simply absent in an
 * install — where `maybeProbe` already answers `'missing'` and the SessionStart arm is
 * otherwise unchanged. That degradation is DELIBERATE and named rather than hidden: porting
 * the probe into the package is a separate surface with its own network reach, and a unit
 * that quietly gave an npx install a background registry fetch would be the opposite of the
 * "defaults off" rule `--update` is registered under.
 */
const UPDATE_PROBE = path.resolve(HERE, '..', '..', 'tools', 'hooks', 'update-probe.mjs');

/**
 * At most one probe per 24 h, decided from the `checked_at` of the record already in hand.
 *
 * THE TTL LIVES HERE AND NOWHERE ELSE. Neither runtime's reader has one, deliberately: the
 * comparison is between the version that is RUNNING and the version the record last saw, so an
 * old record cannot manufacture a false "you are stale" — if the operator updated since,
 * running >= recorded and the line goes quiet by itself. Freshness is the writer's problem, and
 * this is the writer's side of the fence.
 */
const UPDATE_TTL_MS = 24 * 60 * 60 * 1000;

/**
 * The line's byte budget, the same mechanism `SESSION_INJECT_MAX` and `PROMPT_INJECT_MAX` are:
 * nothing this file injects is unbounded. The sentence itself is 137 bytes plus two version
 * numbers; the one component that is not fixed is the operator's home path inside `{path}`, so
 * the cap is generous and exists to bound that, not to trim the sentence.
 */
const UPDATE_LINE_MAX = 500;

/**
 * THE SENTENCE. Only in the stale state, silent in the other four.
 *
 * It is NOT `updatecheck.UPDATE_AVAILABLE` and must not be made into it: that one is the status
 * tool's, prefixed `update:` and naming no path, because a caller of `bantamkit_status` already
 * knows which endpoint answered it. This hook does not — the host may talk to any registered
 * endpoint, and this line names the install it ACTUALLY compared so the claim can be checked.
 * Same reason `_install_source_condition` is the one condition allowed to name a path.
 *
 * `{program}` is `updatecheck.PROGRAM` — the COMMAND, `bantamkit-mcp`, never a package name:
 * the PyPI distribution is `bantamkit` and the npm package is `bantamkit-mcp`, and the command
 * is the one word that is true on both sides.
 *
 * "then reconnect the host" is measured reason 1 in `selfupdate.py:13-20`: a running server
 * keeps serving the code it loaded at startup, so an updated install does nothing for THIS
 * session.
 */
const UPDATE_LINE =
  '[bantamkit] {program} {installed} at {path} is running; the package index has {latest} — run `{program} --update`, then reconnect the host.';

/** `{name}` substitution. A missing key is left alone rather than rendered `undefined`. */
function fillLine(template: string, values: Readonly<Record<string, string>>): string {
  return template.replace(/\{([a-z]+)\}/g, (whole, name: string) => values[name] ?? whole);
}

/**
 * The kept install's `{path, version}`, or `null`.
 *
 * `<homedir>/.bantamkit/mcp/node_modules/bantamkit-mcp/package.json` — the install `--install`
 * makes and a host launches. It is the only install this hook can see; the endpoint the host
 * actually talks to may be another one entirely, which is exactly why the line names this path
 * instead of claiming to speak for all of them. No manifest means no line: a machine with no
 * kept install has nothing here to be stale.
 *
 * `keptPrefix`/`keptManifest` are IMPORTED rather than respelled, and that is the point:
 * `npminstall` owns the kept install's paths and `updatecheck` owns the record path, the
 * record key and the five-state decision. Writing any of those a second time here would be a
 * second thing to keep in step with two runtimes. There is no comparator in this file.
 */
function keptInstall(home: string): { path: string; version: string } | null {
  const manifest = keptManifest(keptPrefix(home));
  try {
    const parsed = JSON.parse(fs.readFileSync(manifest, 'utf8')) as { version?: unknown };
    const version = parsed && typeof parsed.version === 'string' ? parsed.version.trim() : '';
    return version === '' ? null : { path: manifest, version };
  } catch {
    return null;
  }
}

interface UpdateSignal {
  line: string | null;
  state: UpdateState | null;
  probe: string;
}

/**
 * The line to inject (or `null`), and what was done about the record. Never throws.
 *
 * ORDER IS DELIBERATE: the record is read ONCE, the line is decided from it, and the probe
 * decision is made from the SAME load. A second read would be a second answer.
 */
function updateSignal(run: HookRun): UpdateSignal {
  const file = recordPath(run.home);
  const { source, record } = loadRecord(file);

  let line: string | null = null;
  let state: UpdateState | null = null;
  const kept = keptInstall(run.home);
  if (kept) {
    // `updatecheck.KEY` is `npm` in this runtime, which is the registry the kept install came
    // from — so the key the reader picks is right by construction, not by a choice made here.
    const status = decideUpdate(kept.version, source, record, UPDATE_KEY);
    state = status.state;
    if (state === STATE_AVAILABLE) {
      const entry = record ? (record[UPDATE_KEY] as { latest?: unknown } | undefined) : undefined;
      const latest = entry ? String(entry.latest) : '';
      line = capBytes(
        fillLine(UPDATE_LINE, {
          program: UPDATE_PROGRAM,
          installed: kept.version,
          path: kept.path,
          latest,
        }),
        UPDATE_LINE_MAX,
      );
    }
  }

  return { line, state, probe: maybeProbe(run, record) };
}

/**
 * Fork the probe and forget it, at most once per 24 h. Returns the word the log records.
 *
 * `detached: true` + `stdio: 'ignore'` + `.unref()` is the whole mechanism, and each third of
 * it is load-bearing: `detached` puts the child in its own process group so the host reaping
 * this hook does not reap it, `stdio: 'ignore'` means nothing it might ever print can reach the
 * host's screen or hold a pipe open, and `unref()` releases the event loop so THIS process can
 * exit while the child keeps running. Take any one away and SessionStart waits on a registry.
 *
 * A record that cannot say when it was written is treated as due, not as fresh — the same
 * direction `updatecheck` takes it (an unparseable `checked_at` is not a record), and the safe
 * one: the cost of an extra probe is a detached GET nobody waits for.
 */
function maybeProbe(run: HookRun, record: Record<string, unknown> | null): string {
  const stamp = record && typeof record['checked_at'] === 'string' ? record['checked_at'] : null;
  const checkedAt = stamp === null ? NaN : Date.parse(stamp);
  if (Number.isFinite(checkedAt) && Date.now() - checkedAt < UPDATE_TTL_MS) return 'fresh';
  if (!fs.existsSync(UPDATE_PROBE)) return 'missing';
  try {
    const child = spawn(process.execPath, [UPDATE_PROBE], { detached: true, stdio: 'ignore' });
    child.unref();
    return 'spawned';
  } catch (e) {
    // A spawn this hook cannot make is a log line, never a session that fails to start.
    log(run, { event: 'SessionStart', warn: `update-probe: ${message(e)}` });
    return 'failed';
  }
}

/** `String(e.message || e)`, which is what every `catch` in the original wrote by hand. */
function message(e: unknown): string {
  if (e instanceof Error) return e.message || String(e);
  return String(e);
}

// ---------------------------------------------------------------- SessionStart
function sessionStart(run: HookRun, input: HookInput): void {
  const cwd = input.cwd || process.cwd();
  const parts: string[] = [];
  const profileFacts = countFacts(run.profile);
  let profile: CappedIndex = { block: '', total: 0, injected: 0, dropped: [] };
  if (profileFacts > 0) {
    profile = cappedIndex(
      run.profile,
      (count) => `[bantamkit profile memory — ${count} facts learned across projects]`,
      SESSION_INJECT_MAX,
    );
    parts.push(profile.block);
  }
  // WHERE THE HOST'S OWN AUTO-MEMORY DIRECTORY IS, resolved ONCE per session and used twice:
  // it decides whether the project index has to be injected at all, and it is where A exports.
  // SessionStart is the event because it is the one that already had to answer this question,
  // it is paid once per session, and `transcript_path` — branch 3, the only branch that works
  // on a machine the operator has not configured — arrives on it.
  const native = resolveNativeMemory(run, input);
  //
  // A project store that is NOT the profile dir, and one of two things:
  //   - the host has no auto-memory store we can find → inject the index, as before;
  //   - the host HAS one → export into it instead. Injecting as well would pay twice for the
  //     same facts, which is the cost the old `nativeMemoryExists` branch existed to avoid.
  // ONLY THE PROJECT LAYER IS EXPORTED. The native directory is keyed on the host's project
  // root, so a cross-project profile fact placed in it would be copied into every project's
  // store — and the profile index is injected above on every session anyway, so exporting it
  // buys nothing and costs the collision job50/J50-2A already paid for once.
  let project: CappedIndex | null = null;
  let exported: NativeExport | null = null;
  try {
    const store = discoverProjectStore(cwd);
    if (path.resolve(store) !== path.resolve(run.profile) && countFacts(store) > 0) {
      if (native.dir === null) {
        project = cappedIndex(store, (count) => `[bantamkit project memory — ${count} facts]`, SESSION_INJECT_MAX);
        project.facts = countFacts(store);
        parts.push(project.block);
      } else {
        exported = exportToNative(native.dir, store);
      }
    }
  } catch (e) {
    log(run, { event: 'SessionStart', warn: message(e) });
  }
  parts.push(
    '[bantamkit] Toolbox is live: mcp__bantamkit__memory_recall reads the body of any fact above; memory_save stores a durable lesson (feedback|user|project|reference — never something derivable from the repo). Repeat reads of an unchanged file are refused once by the filegraph hook; a save nudge fires once at session end when nothing was saved.',
  );
  // LAST, AND ONLY WHEN IT IS TRUE. The toolbox line above is constant boilerplate the agent
  // sees every session; this one appears in one of five states and asks for an action, so it
  // gets the strongest position in the block. Everything above it is unchanged when it is
  // absent, which is the other four states and most sessions.
  let update: UpdateSignal = { line: null, state: null, probe: 'error' };
  try {
    update = updateSignal(run);
  } catch (e) {
    log(run, { event: 'SessionStart', warn: `update-signal: ${message(e)}` });
  }
  if (update.line) parts.push(update.line);
  const ctx = parts.join('\n\n');
  if (input.source === 'compact') {
    // context was just rebuilt: earlier reads are gone, so the read ledger must not refuse them
    try {
      fs.unlinkSync(ledgerPath(run, input.session_id));
    } catch {
      /* none */
    }
  }
  // `profileFacts` keeps its old meaning — files in the store — so older records stay
  // comparable; `profileInjected` / `profileDropped` are what the block carried and did
  // not, and `dropRule` is the order the drop followed. The project trio appears only when
  // a project block was injected at all.
  log(run, {
    event: 'SessionStart',
    source: input.source,
    cwd,
    bytes: Buffer.byteLength(ctx),
    profileFacts,
    profileInjected: profile.injected,
    profileDropped: profile.dropped,
    ...(project
      ? { projectFacts: project.facts, projectInjected: project.injected, projectDropped: project.dropped }
      : {}),
    dropRule: SESSION_DROP_RULE,
    // A — the host's auto-memory directory. `nativeBranch` / `nativeTried` are the one line
    // RULING Q1.3 asks for when nothing answered: they say WHICH branches were tried, so
    // "bantamkit exported nothing" is never indistinguishable from "bantamkit did not look".
    // The export trio appears only when an export actually ran.
    nativeBranch: native.branch,
    nativeTried: native.tried,
    nativeDir: native.dir,
    ...(exported
      ? {
          nativeExported: exported.exported,
          nativeFiles: exported.files,
          nativeIndexLines: exported.indexLines,
          nativeBytes: exported.bytes,
          nativeIndexBytes: exported.indexBytes,
          nativeSkipped: exported.skipped,
          nativeIndex: exported.index,
          ...(exported.error ? { nativeError: exported.error } : {}),
        }
      : {}),
    storeScope: run.storeScope,
    // The stale-install signal, in three fields so the claim "it fired / it stayed quiet / it
    // asked the registry" is a number the operator can rerun rather than a sentence. `state` is
    // one of `updatecheck`'s five (or `null` when there is no kept install to compare);
    // `probe` is `spawned` / `fresh` / `unbuilt` / `missing` / `failed` / `error`.
    updateState: update.state,
    updateProbe: update.probe,
    updateBytes: Buffer.byteLength(update.line || ''),
  });
  emit({ hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: ctx } });
}

// ------------------------------------------------------------ UserPromptSubmit
/**
 * One injected recall header, parsed: `[layer] [name] (type) description`.
 *
 * ONE regex, used both to FILTER the reply's lines and to read the fields off them, so the
 * set of lines called headers cannot drift from the set of lines the log describes.
 */
const RECALL_HEADER = /^\[([^\]]+)\] \[([^\]]+)\] \(([a-z]+)\) (.*)$/;

interface ScoredHeader {
  name: string;
  layer: string;
  type: string;
  score: number;
}

/**
 * The store's own score for one injected header against this prompt.
 *
 * `MemoryStore.recall` computes `score` and throws it away — it returns `Fact[]`, and
 * `recallOutcome` carries counts but no per-fact score, so no runtime API surfaces the
 * number roadmap #6 has to gate on. It does not need to. The score IS
 *
 *     |tokens(name + " " + description) ∩ tokens(query)|
 *
 * and all three inputs are here: `tokens` is exported from the runtime's own `store.js`
 * (so this is the shipped tokenizer, not a second copy of it), the query is the prompt, and
 * `name`/`description` are the two fields `Memory.format` interpolated into this very line.
 * Re-deriving it is exact, not an estimate — for every fact `memory_save` writes, whose
 * description is one line by construction. A hand-edited multi-line description would have
 * already broken the header this parses, and would score its first line.
 */
function scoreHeader(head: string, queryTokens: Set<string>): ScoredHeader | null {
  const m = RECALL_HEADER.exec(head);
  if (!m) return null;
  const layer = m[1] ?? '';
  const name = m[2] ?? '';
  const type = m[3] ?? '';
  const description = m[4] ?? '';
  let score = 0;
  for (const t of tokens(`${name} ${description}`)) if (queryTokens.has(t)) score += 1;
  return { name, layer, type, score };
}

/**
 * The prompt, as a fingerprint that cannot be read back.
 *
 * THE LOG PERSISTS TO DISK AND THE PROMPTS ARE THE USER'S. Nothing reconstructible goes in:
 * a SHA-256 hex digest and two sizes, and no substring of the prompt at any length. The
 * digest exists to tell two prompts apart and to recognise the same prompt twice — that is
 * all #6 needs from it. It is a one-way function, not a secret: someone holding a GUESS at
 * the prompt can confirm the guess by hashing it. That is inherent to any stable hash, and
 * the alternative — a per-machine salt — would buy nothing here (the guesser has the salt
 * too, it sits in the same home directory) at the cost of digests that stop matching across
 * machines. So: stable, unsalted, and documented rather than dressed up.
 */
function promptFingerprint(prompt: string): { sha256: string; chars: number; bytes: number } {
  return {
    sha256: createHash('sha256').update(prompt, 'utf8').digest('hex'),
    chars: prompt.length,
    bytes: Buffer.byteLength(prompt),
  };
}

function userPromptSubmit(run: HookRun, input: HookInput): void {
  const prompt = String(input.prompt || '').trim();
  if (prompt.length < PROMPT_MIN_CHARS || prompt.startsWith('/')) {
    log(run, { event: 'UserPromptSubmit', action: 'skip', reason: 'short-or-command' });
    return;
  }
  const m = Memory.layered(input.cwd || process.cwd());
  // `stamp = false` (job64, J64-1): an injection is the HOOK reading the store, not the model
  // asking for a fact, so it must not date `last_recalled`. Before this it did, on every
  // prompt, for up to three files — and the rules keyed on that date (compaction's
  // stalest-first, the SessionStart drop rule, the Stop dream's store fingerprint) were
  // reading this arm's traffic. An explicit `memory_recall` still stamps.
  const o = m.recallOutcome(prompt, 3, RECALL_MIN_SCORE_RATIO, false);
  if (o.status !== 'answered') {
    log(run, { event: 'UserPromptSubmit', action: 'none', status: o.status, candidates: o.candidates });
    return;
  }
  // Only the HEADER line of each hit — `[layer] [name] (type) description`. The body costs
  // ~1.5 KB a fact and would be re-sent on every later call; the header is ~150 B and
  // tells the model exactly which name to pass to memory_recall if it wants the body.
  const heads = o.reply.split('\n').filter((l) => RECALL_HEADER.test(l));
  if (heads.length === 0) {
    log(run, { event: 'UserPromptSubmit', action: 'none', reason: 'no-headers' });
    return;
  }
  const ctx = capLines(
    `[bantamkit recall — memories that match this prompt; call mcp__bantamkit__memory_recall with {"query":"<name>"} for the body]\n${heads.join('\n')}`,
    PROMPT_INJECT_MAX,
  );
  // `injected` is read back off `ctx`, NOT off `heads`. The byte cap drops whole lines, so a
  // header that `recallOutcome` picked need not have left the process — and roadmap #6 asks
  // "was an INJECTED name later used", a question a name the model never saw would poison.
  // `hits` keeps its old meaning (headers picked, pre-cap) so the 487 records written before
  // this change stay comparable; `dropped` is the difference the old shape could not show.
  const queryTokens = tokens(prompt);
  const injected = ctx
    .split('\n')
    .map((l) => scoreHeader(l, queryTokens))
    .filter((x): x is ScoredHeader => x !== null);
  log(run, {
    event: 'UserPromptSubmit',
    action: 'inject',
    hits: heads.length,
    bytes: Buffer.byteLength(ctx),
    source: o.source,
    // The join key. Without it an injection record cannot be matched to the transcript that
    // says what the model did next, which is why the 487 pre-existing records answer nothing.
    session: input.session_id ?? null,
    prompt: promptFingerprint(prompt),
    injected,
    dropped: heads.length - injected.length,
  });
  emit({ hookSpecificOutput: { hookEventName: 'UserPromptSubmit', additionalContext: ctx } });
}

// ------------------------------------------------------------- PreToolUse Read
// The filegraph, over the OPERATOR's reads. `filegraph.md` measured the mechanism as net
// positive and never a loss (cache pays only on a repeat); it could not reach these reads
// because they never pass through bantamkit's Agent. A PreToolUse hook is the one place
// that does see them. Keyed by transcript (a subagent has its own transcript and has NOT
// seen the parent's read), by path+offset+limit, and by mtime+size so an edit re-arms it.
// REFUSES ONCE: the second identical call goes through, so nothing can be hard-blocked.
function preToolUseRead(run: HookRun, input: HookInput): void {
  const ti = input.tool_input ?? {};
  const file = typeof ti['file_path'] === 'string' ? ti['file_path'] : '';
  if (!file) return;
  let st: fs.Stats;
  try {
    st = fs.statSync(file);
  } catch {
    return; // missing file: let Read produce its own error
  }
  const offset = ti['offset'];
  const limit = ti['limit'];
  // The transcript is the CONTEXT dimension: a subagent has its own transcript and has not
  // seen the parent's reads. It is carried on the record as well as in the key, because
  // `preCompact` must filter on it and a path may itself contain the key's delimiter.
  const transcript = String(input.transcript_path || input.session_id || '');
  const key = `${transcript}|${file}|${offset ?? ''}|${limit ?? ''}`;
  const ledger = readLedger(run, input.session_id);
  const prev = ledger.reads[key];
  const sig = `${st.mtimeMs}|${st.size}`;
  if (prev && prev.sig === sig && !prev.refused) {
    prev.refused = true;
    prev.count += 1;
    writeLedger(run, input.session_id, ledger);
    const reason = `bantamkit filegraph: ${file}${offset != null ? ` (offset ${offset}${limit != null ? `, limit ${limit}` : ''})` : ''} was already read in this context at ${prev.at} and is unchanged on disk (same mtime and size). Use the content from that earlier read. If you genuinely need it again, repeat the exact same call — this refusal fires only once per unchanged file.`;
    log(run, { event: 'PreToolUse', action: 'refuse', file, size: st.size });
    emit({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: reason,
      },
    });
    return;
  }
  ledger.reads[key] = {
    sig,
    at: new Date().toISOString(),
    count: (prev ? prev.count : 0) + 1,
    refused: false,
    transcript,
    file,
  };
  writeLedger(run, input.session_id, ledger);
  log(run, {
    event: 'PreToolUse',
    action: prev ? 'allow-after-refuse-or-change' : 'record',
    file,
    size: st.size,
  });
}

// ---------------------------------------------- PostToolUse → the usage events log
// One line per tool call, for `tools/ledger/tool-usage.mjs` to read when a transcript is gone.
// The transcript is authoritative while it exists; this is the durable copy behind it, and it
// is the ONLY record of a session whose transcript the host has since deleted (4 of 110 logged
// sessions, measured 2026-09-04).
//
// `appendFileSync` and not the read-modify-write `writeLedger` above: the host fires one hook
// PROCESS per tool call and a parallel tool block fires them concurrently, which loses 40–50 %
// of a read-modify-write's records (roadmap-toolbox row 8, follow-up (q)). An append of a line
// this size is atomic on both platforms, so this half has no such race.
//
// Folded in from tool-metrics' `hooks/scripts/log_event.py`; the field names are that file's,
// so an events.jsonl written by either program reads in either.
function appendUsageEvent(run: HookRun, input: HookInput): void {
  const tool = input.tool_name || '?';
  const ti = input.tool_input && typeof input.tool_input === 'object' ? input.tool_input : {};
  const record = {
    ts: new Date().toISOString(),
    session: input.session_id || '',
    // The HOST's slug, not tool-metrics' — `token-ledger.mjs` uses this same expression.
    // log_event.py mapped `.` to a dash as well, which the host does not: this machine has
    // both `-private-tmp-r3-p3.p1ex6K` and `-private-tmp-r3-p3-p1ex6K` as separate project
    // dirs, so the python slug split one project into two keys under `--group project` and
    // made `--project` miss the recovered rows entirely.
    project: String(input.cwd || '').replace(/[\\/:]/g, '-'),
    tool,
    server: tool.startsWith('mcp__') && tool.split('__').length >= 3 ? tool.split('__')[1] : 'builtin',
    // The dedupe key. Two writers append to this file by design and one machine can register
    // the hook at both user and project scope, so a call can be logged twice; the reader
    // dedupes on this the same way it dedupes transcript blocks. Rows written before this
    // field existed simply carry none.
    tool_use_id: String(input.tool_use_id ?? ''),
    detail:
      tool === 'Skill'
        ? String(ti['skill'] ?? '')
        : tool === 'Agent'
          ? String(ti['subagent_type'] || 'general-purpose')
          : '',
  };
  const dir = process.env['TOOL_METRICS_DIR'] || path.join(os.homedir(), '.claude', 'tool-metrics');
  const file = path.join(dir, 'events.jsonl');
  try {
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(file, `${JSON.stringify(record)}\n`);
    pruneUsageEvents(run, file);
  } catch {
    /* the log is a convenience; never fail a tool call over it */
  }
}

// The log's ONLY reader is `tools/ledger/tool-usage.mjs`, and it reads ONLY the sessions whose
// transcript the host has deleted — 4 of 110 when this was written, holding 115 of 40,873
// lines. The other 99.7 % are dead weight that the reader re-materialises on every run, and
// now that this arm is matcher-less the file grows once per tool call (~42k/month here).
//
// So: a line whose session still has a transcript is redundant BY CONSTRUCTION, and dropping
// it loses nothing the reader would have used. Above the cap, that is exactly what this drops.
//
// The cost is paid the right way round. `statSync` runs on every call and is a few
// microseconds; the walk and rewrite run only when the file is over the cap, and each prune
// puts it far enough under that the next one is thousands of calls away. The walk reads
// DIRECTORY ENTRIES, never file contents.
const EVENTS_MAX_BYTES = 4_000_000;

function pruneUsageEvents(run: HookRun, file: string): void {
  let size = 0;
  try {
    size = fs.statSync(file).size;
  } catch {
    return;
  }
  if (size <= EVENTS_MAX_BYTES) return;

  const projects = path.join(run.home, '.claude', 'projects');
  const onDisk = new Set<string>();
  const walk = (dir: string): void => {
    let entries: fs.Dirent[] = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      if (e.isDirectory()) {
        onDisk.add(e.name);
        walk(path.join(dir, e.name));
      } else if (e.name.endsWith('.jsonl')) {
        onDisk.add(e.name.slice(0, -'.jsonl'.length));
      }
    }
  };
  walk(projects);
  // A walk that found nothing is an unreadable projects dir, not a machine with no
  // transcripts. Pruning on that reading would delete the whole log.
  if (onDisk.size === 0) {
    log(run, { event: 'PostToolUse', action: 'prune-skipped', reason: 'no transcripts found', size });
    return;
  }

  const kept: string[] = [];
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    let record: { session?: unknown } | null;
    try {
      record = JSON.parse(line) as { session?: unknown };
    } catch {
      kept.push(line); // keep what we cannot judge
      continue;
    }
    if (!record?.session || !onDisk.has(String(record.session))) kept.push(line);
  }
  const tmp = `${file}.prune-${process.pid}`;
  fs.writeFileSync(tmp, kept.length ? `${kept.join('\n')}\n` : '');
  fs.renameSync(tmp, file);
  log(run, { event: 'PostToolUse', action: 'prune', before: size, after: fs.statSync(file).size, kept: kept.length });
}

// ---------------------------------------------- the server's actual --index-budget
// (and, since J50-1, the server's actual store pin — the walk below is shared by both)
// `Memory.layered(cwd)` opens the project store at DEFAULT_INDEX_BUDGET unless told
// otherwise, and the MCP server honours `--index-budget N` (`runtime-ts/src/cli.ts`).
// A RUNNING server never writes that number down anywhere: `MemoryStore` keeps `indexBudget`
// in memory only, so nothing publishes it and this file cannot be made to (that would be a
// change inside `runtime-ts/src/memory`, a different layer and a different unit). The one
// place the value survives between "the operator configured it" and "this short-lived hook
// process needs it" is the SAME configuration a Claude Code session itself reads to decide
// which server to start.
// `tools/mcpdrift/mcpdrift.py`'s `discover()` already names the three scopes that can change
// which server answers a session for a given project directory (user, local, project); this
// reads the same three, for the same reason — those are the configs that can actually change
// the answer, not a fourth format guessed at.
//
// WHAT THIS DELIBERATELY DOES NOT COVER: Claude Desktop / Cursor / Copilot configs (this
// hook only ever runs under Claude Code, `docs/hooks.md`), enterprise-managed settings, and a
// server started by hand outside all three files. None of those were covered before this fix
// either — the old code always assumed the default — so leaving them uncovered narrows an
// existing gap rather than regressing it.
//
// SCOPES DO NOT DISAGREE — THEY HAVE A PRECEDENCE, AND THIS FOLLOWS IT. Until 2026-09-06
// this collected the DISTINCT `--index-budget` values across the three scopes and refused to
// compact ("AMBIGUITY IS A REFUSAL, NOT A GUESS") whenever it found more than one. That
// refusal fired on the NORMAL case: a machine with a user-scope default and a project-scope
// override is configured, not ambiguous, and the cost was that automatic compaction silently
// stopped for that project with nothing but a log line to show for it. Verified against the
// host's own documentation on 2026-09-06 rather than reasoned about
// (https://code.claude.com/docs/en/mcp, "MCP installation scopes"): when the same server name
// is defined in more than one scope Claude Code connects to it ONCE, using the definition
// from the highest-precedence source, and the precedence is
//
//     local  >  project  >  user
//
// — local being `~/.claude.json` `.projects[<resolved cwd>].mcpServers`, project being
// `<cwd>/.mcp.json`, user being `~/.claude.json` `.mcpServers`.
//
// THE UNIT OF PRECEDENCE IS THE WHOLE ENTRY, NOT THE FLAG, which is the part that is easy to
// get wrong: the same page says fields are NEVER merged across scopes. So the search below is
// for the highest-precedence scope that registers `bantamkit` AT ALL, and `--index-budget` is
// then read from that entry alone. A local-scope entry with no `--index-budget` therefore
// means the DEFAULT, even when a user-scope entry names a number — because the user-scope
// entry is not what the session launched. Reading the flag scope-by-scope instead would
// reintroduce exactly the wrong-denominator bug this arm exists to fix.
//
// THERE IS NO AMBIGUOUS CASE LEFT, so there is no refusal branch — dead code shaped like a
// safety net is worse than none. Precedence is total over the three scopes, each scope holds
// at most one `bantamkit` entry, and each entry yields at most one `--index-budget`. Finding
// no entry at all means nothing configures it anywhere this hook can see, and the default is
// then the honest answer, not a guess: it is the same default the CLI itself falls back to
// when `--index-budget` is absent.
//
// ONE RESIDUAL, NAMED RATHER THAN GUESSED AT: a project-scope `.mcp.json` server is not
// launched until the user approves it, and that answer is recorded in the SAME file, as
// `.projects[<cwd>].enabledMcpjsonServers` / `.disabledMcpjsonServers` — both keys are real
// and present in this machine's `~/.claude.json`, both empty here. This hook does NOT consult
// them, because the pending state (in neither list) is not resolvable from the file and the
// disabled state has not been reproduced end to end from a live host. Registered in
// `docs/roadmap-toolbox.md` rather than half-implemented.
function readJsonSafe(file: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8')) as unknown;
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

/** Best-effort marker write. A marker that cannot be written costs a repeated dream, not a crash. */
function writeJsonSafe(file: string, value: unknown): void {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(value));
  } catch {
    /* the gate degrades to "always fires", which is safe and merely not free */
  }
}

function indexBudgetFromArgs(args: unknown): number | undefined {
  if (!Array.isArray(args)) return undefined;
  for (let i = 0; i < args.length; i += 1) {
    const a: unknown = args[i];
    if (a === '--index-budget' && i + 1 < args.length) {
      const n = Number(args[i + 1]);
      if (Number.isFinite(n)) return n;
    } else if (typeof a === 'string' && a.startsWith('--index-budget=')) {
      const n = Number(a.slice('--index-budget='.length));
      if (Number.isFinite(n)) return n;
    }
  }
  return undefined;
}

interface Registration {
  entry: Record<string, unknown> | null;
  scope: string | null;
}

/**
 * The `--index-budget` the `bantamkit` registration a session in `cwd` would actually launch
 * carries — resolved by Claude Code's own MCP scope precedence, `local > project > user`, over
 * the WHOLE entry. Cheap: two small file reads, and none of it requires the server to be up.
 *
 * Returns `{ budget, scope }`. `budget` is `undefined` when the winning entry configures no
 * `--index-budget` and when no scope registers `bantamkit` at all; `scope` names the entry
 * that won, or is `null` when none did, so the log says WHICH file the number came from.
 */
function configuredIndexBudget(
  run: HookRun,
  cwd: string,
): { budget: number | undefined; scope: string | null } {
  const { entry, scope } = winningRegistration(run, cwd);
  return entry ? { budget: indexBudgetFromArgs(entry['args']), scope } : { budget: undefined, scope: null };
}

/**
 * The `bantamkit` registration entry a session in `cwd` actually launched, and the scope it
 * came from — the walk `configuredIndexBudget` has always done, lifted out (J50-1) so that
 * `env` is read off the SAME entry as `args`. One walk, two fields; a second walk would be
 * the second place the precedence rule could be got wrong.
 *
 * Returns `{ entry, scope }`, both `null` when no scope registers `bantamkit` at all.
 */
function winningRegistration(run: HookRun, cwd: string): Registration {
  const repo = path.resolve(cwd);
  const claudeJson = readJsonSafe(path.join(run.home, '.claude.json'));
  const mcpJson = readJsonSafe(path.join(repo, '.mcp.json'));
  const dig = (root: Record<string, unknown>, keys: readonly string[]): unknown => {
    let node: unknown = root;
    for (const key of keys) {
      if (!node || typeof node !== 'object' || Array.isArray(node)) return undefined;
      node = (node as Record<string, unknown>)[key];
    }
    return node;
  };
  // Highest precedence first. Order is the whole point; do not sort or reorder.
  const scopes: readonly (readonly [string, unknown])[] = [
    ['local', dig(claudeJson, ['projects', repo, 'mcpServers', 'bantamkit'])],
    ['project', dig(mcpJson, ['mcpServers', 'bantamkit'])],
    ['user', dig(claudeJson, ['mcpServers', 'bantamkit'])],
  ];
  for (const [scope, entry] of scopes) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue;
    return { entry: entry as Record<string, unknown>, scope };
  }
  return { entry: null, scope: null };
}

// ------------------------------------------------ the server's actual store pin (J50-1)
//
// `discoverProjectStore`, `resolveProjectStore` and `Memory.layered` — every store the hook
// binds, in every arm — resolve through `pinnedStore()` in `memory/layers.js`, which
// reads `process.env.BANTAMKIT_MEMORY_DIR` and outranks the walk. The SERVER sees a
// registration's `env` because the host merges it into the server's process before spawning
// it; this hook is spawned by the host too, but from the host's OWN environment, and the
// registration's `env` never reaches it. So a registration that pins the store had the
// server saving into the pinned directory while this hook injected from whatever the walk
// found — from any cwd the walk would not have led to the pin, two different stores.
//
// MEASURED LATENT, NOT LIVE, on 2026-09-12: the only pin on this machine is the bantamkit
// repo's LOCAL-scope entry, and it names the directory the walk finds from that cwd anyway
// (`.shiftwork/notes-job50/PROBE.md`, B2). The user-scope pin that DID split the two was
// removed on 2026-09-11. This closes the shape, not one instance of it.
//
// THE FIX FEEDS THE ONE RESOLUTION RATHER THAN ADDING A SECOND: the winning entry's value is
// applied to this process's environment before any arm runs, and the same `pinnedStore()`
// the server runs then sees the same value. Host merge semantics are what decide the edge
// cases, and they are `{ ...inherited, ...entry.env }`: a key PRESENT in the winning entry
// overrides whatever this process inherited (a blank one included — `pinnedStore` already
// reads blank as "no pin", so the server and the hook then both walk), and a key ABSENT from
// it leaves the inherited value alone, because that is what the server inherits too. The
// whole-entry rule applies exactly as it does to `--index-budget`: a winning entry with no
// `env` means the walk, even when a lower scope pins.
//
// NOT DONE HERE, NAMED RATHER THAN HALF-BUILT: the host expands `${VAR}` and `${VAR:-default}`
// in `.mcp.json` `env` values before spawning the server. A pin written that way reaches
// `pinnedStore` unexpanded here, and is refused by it as a relative path — loudly, on the
// log, never silently as the wrong store. No registration on this machine uses the syntax.
function applyRegistrationStorePin(run: HookRun, cwd: string): void {
  const { entry, scope } = winningRegistration(run, cwd);
  const env = entry ? entry['env'] : null;
  if (!env || typeof env !== 'object' || Array.isArray(env)) return;
  if (!Object.prototype.hasOwnProperty.call(env, 'BANTAMKIT_MEMORY_DIR')) return;
  const value = (env as Record<string, unknown>)['BANTAMKIT_MEMORY_DIR'];
  if (typeof value !== 'string') return;
  process.env['BANTAMKIT_MEMORY_DIR'] = value;
  run.storeScope = value.trim() === '' ? null : scope;
}

// ---------------------------------------------- PostToolUse memory_save → compact
function postSave(run: HookRun, input: HookInput): void {
  const ledger = readLedger(run, input.session_id);
  ledger.saved = (ledger.saved || 0) + 1;
  writeLedger(run, input.session_id, ledger);
  const cwd = input.cwd || process.cwd();
  const configured = configuredIndexBudget(run, cwd);
  const budgetSource = configured.budget !== undefined ? 'configured' : 'default';
  const budgetScope = configured.budget !== undefined ? configured.scope : null;
  const m = Memory.layered(cwd, configured.budget !== undefined ? { indexBudget: configured.budget } : {});
  const [bytes, budget] = m.indexAccounting();
  if (bytes == null || bytes < COMPACT_AT * budget) {
    log(run, { event: 'PostToolUse', action: 'saved', bytes, budget, budgetSource, budgetScope });
    return;
  }
  // The user ruled compaction automatic (2026-08-24). `compact` archives the stalest facts
  // until the index sits at --budget; aiming at 80% skips the 90–99.2% band where the
  // default reserve makes it a no-op.
  //
  // AMENDED 2026-09-10 (job46, J46-6): the band is closed, and the aim is now asked for as a
  // RESERVE against the real budget rather than as a fake budget — see COMPACT_TO above for
  // the measurement. `compact`'s target is `budget - reserve`, so this lands at exactly
  // `target` instead of at whatever the default reserve makes of a budget it was misled
  // about. `reserve` is at least 1 for every budget >= 1 (both parsers refuse 0), and
  // 0.2 * budget is always under the `budget // 2` cap, so neither edge is reachable here.
  const target = Math.floor(COMPACT_TO * budget);
  const reserve = budget - target;
  const r = spawnSync(
    process.execPath,
    [
      path.join(DIST, 'cli.js'),
      'compact',
      '--store',
      m.store.root,
      '--budget',
      String(budget),
      '--reserve',
      String(reserve),
    ],
    { encoding: 'utf8', timeout: 8000 },
  );
  const out = `${r.stdout || ''}${r.stderr || ''}`.trim();
  log(run, {
    event: 'PostToolUse',
    action: 'auto-compact',
    bytes,
    budget,
    target,
    reserve,
    budgetSource,
    budgetScope,
    exit: r.status,
    out: out.slice(0, 400),
  });
  emit({
    hookSpecificOutput: {
      hookEventName: 'PostToolUse',
      additionalContext: `[bantamkit] memory index was ${bytes}/${budget} B; auto-compacted to ≤${target} B. ${out.slice(0, 600)}`,
    },
  });
}

// -------------------------------------------------------------------- PreCompact
// Steering for the summariser, derived from state the hook already holds: which files this
// context read (from the read ledger) and which shiftwork unit is open. The ledger measured
// 160k cache-read tokens per request; a summary that keeps the file list means the rebuilt
// context does not re-read them, and the PostCompact reset lets the gate allow the ones it
// genuinely needs.
//
// THE CHANNEL IS PLAIN STDOUT, NOT `hookSpecificOutput`. Verified against the host binary
// (`2.1.259`, the PreCompact dispatcher `fK`): the summariser's instructions are
//
//     newCustomInstructions: C.length > 0 ? C.join("\n\n") : undefined
//     C = results.filter(r => r.succeeded && !r.blocked && r.output.trim().length > 0)
//                .map(r => r.output.trim())
//
// — the hook's own trimmed stdout, verbatim. The `hookSpecificOutput` discriminated union
// in that build has NO `"PreCompact"` member (its arms are PreToolUse, PostToolUse,
// PostToolUseFailure, PostToolBatch, PermissionRequest, PermissionDenied, UserPromptSubmit,
// UserPromptExpansion, SessionStart, Setup, Stop, SubagentStart, SubagentStop,
// PreModelSwitch, PostModelSwitch, Notification, MessageDisplay, FileChanged, CwdChanged,
// Elicitation, ElicitationResult, WorktreeCreate), so emitting that envelope here made the
// host reject the output with "Hook JSON output validation failed", set `succeeded` false,
// and DROP the text. Between b3625d9 and this change every compaction was unsteered.
// Non-JSON stdout is accepted as-is ("Hook output does not start with {, treating as plain
// text"), which is why `emitText` refuses a leading brace.
//
// The cost of the working channel is that the host also echoes the text back to the user as
// `PreCompact [<command>] completed successfully: <output>`. There is no quieter variant —
// the same string is both the steering and the display — so the arm stays short on purpose.
const CHECKPOINT_MAX_BYTES = 4_000_000; // ONE checkpoint file
// … and an AGGREGATE, because nothing bounded the COUNT. `.shiftwork` accumulates a
// checkpoint per archived job and is never pruned: measured on this repo on 2026-09-04,
// 136,885 B across 6 files, 11 KB of it added by a single session's orchestrator. Every one
// of them was read and JSON-parsed on every compaction, so the worst case was n × 4 MB.
// Candidates are scanned newest-first — the order that already decides the winner — so the
// scan stops at the first OPEN one (on this repo: 1 file, 20,417 B, down from 6 and 136,885)
// and what a spent budget drops is always the OLDEST, the least likely to be the open one.
const CHECKPOINT_SCAN_MAX_BYTES = 1_000_000;
const CHECKPOINT_SCAN_MAX_FILES = 64;

interface CheckpointUnit {
  id: string;
  status: string;
  title?: string;
}

interface CheckpointShape {
  cursor: string;
  units: CheckpointUnit[];
}

/**
 * The structure `assets/schemas/shiftwork-checkpoint.json` requires of the parts this arm
 * reads: `plan.cursor` is a non-empty string and `plan.units` is a non-empty array of units
 * carrying `id` and `status`. Deliberately NOT a full schema validation — a hook that loads
 * a JSON-Schema validator stops being cheap, and a checkpoint that satisfies this shape but
 * fails the full schema still yields a true steering line.
 */
function checkpointShape(doc: unknown): CheckpointShape | null {
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return null;
  const plan = (doc as Record<string, unknown>)['plan'];
  if (!plan || typeof plan !== 'object' || Array.isArray(plan)) return null;
  const cursor = (plan as Record<string, unknown>)['cursor'];
  const units = (plan as Record<string, unknown>)['units'];
  if (typeof cursor !== 'string' || cursor.length === 0) return null;
  if (!Array.isArray(units) || units.length === 0) return null;
  const ok = units.every(
    (u: unknown) =>
      !!u &&
      typeof u === 'object' &&
      typeof (u as Record<string, unknown>)['id'] === 'string' &&
      typeof (u as Record<string, unknown>)['status'] === 'string',
  );
  return ok ? { cursor, units: units as CheckpointUnit[] } : null;
}

interface CheckpointScan {
  winner: (CheckpointShape & { file: string; mtimeMs: number }) | null;
  scanned: number;
  bytes: number;
  skipped: number;
}

/**
 * The OPEN checkpoint under `<cwd>/.shiftwork`, whatever it is called. Real jobs write named
 * checkpoints (`checkpoint-readlever.json`, `checkpoint-job41.json`, …), so the old hardcoded
 * `checkpoint.json` read whichever stale job happened to own that name. Open means: at least
 * one unit is neither `done` nor `dropped`. Most recently written wins, filename breaks the
 * tie, so the choice is deterministic. Every failure — no directory, unreadable file,
 * malformed JSON, wrong shape — is a SKIP, never a throw.
 *
 * Returns `null` when there is no `.shiftwork` at all, else the scan's accounting:
 * `{ winner, scanned, bytes, skipped }` — the caller logs the last three, because a scan
 * that silently stops on a budget is a scan nobody can audit.
 */
function openCheckpoint(cwd: string): CheckpointScan | null {
  const dir = path.join(cwd, '.shiftwork');
  let names: string[];
  try {
    names = fs.readdirSync(dir).filter((n) => n.endsWith('.json'));
  } catch {
    return null;
  }

  // stat first (cheap, and the mtime is what orders the scan), read second (the expensive
  // half, and the one the budget bounds). Same comparator the winner was already chosen by,
  // so applying it before the read changes which files are READ, never which one wins.
  const candidates: { file: string; mtimeMs: number; size: number }[] = [];
  for (const name of names) {
    const file = path.join(dir, name);
    try {
      const st = fs.statSync(file);
      if (!st.isFile() || st.size > CHECKPOINT_MAX_BYTES) continue;
      candidates.push({ file, mtimeMs: st.mtimeMs, size: st.size });
    } catch {
      /* unreadable: skip */
    }
  }
  candidates.sort((a, b) => b.mtimeMs - a.mtimeMs || a.file.localeCompare(b.file));

  let bytes = 0;
  let read = 0;
  let winner: CheckpointScan['winner'] = null;
  for (const c of candidates) {
    // The budget is checked BEFORE each read and never before the first, so the newest
    // candidate is always considered however large it is (bounded by CHECKPOINT_MAX_BYTES).
    if (read > 0 && (bytes >= CHECKPOINT_SCAN_MAX_BYTES || read >= CHECKPOINT_SCAN_MAX_FILES)) break;
    let doc: unknown;
    try {
      doc = JSON.parse(fs.readFileSync(c.file, 'utf8'));
    } catch {
      read += 1;
      bytes += c.size;
      continue;
    }
    read += 1;
    bytes += c.size;
    const shape = checkpointShape(doc);
    if (!shape) continue;
    if (!shape.units.some((u) => u.status !== 'done' && u.status !== 'dropped')) continue;
    winner = { file: c.file, mtimeMs: c.mtimeMs, ...shape };
    break; // newest-first: the first open one IS the most recent open one
  }
  return { winner, scanned: read, bytes, skipped: candidates.length - read };
}

/**
 * "Already read in THIS context" is a claim about one transcript, not about one session. The
 * ledger file is per session, and a session holds the parent's reads and every subagent's:
 * `preToolUseRead` keys on the transcript for exactly that reason (docs/hooks.md — "a
 * subagent has its own transcript and is never refused for the parent's read"). Measured
 * before this filter existed, on this repo's own tree: of the 30 files handed to a parent's
 * summariser, 7 had been read only by a subagent whose output the parent never saw — so the
 * summary carried a false premise, and the PostCompact ledger reset cannot undo it because
 * the summary is already written. The predicate here is the one the refusal arm writes with.
 */
function transcriptFiles(ledger: Ledger, transcript: string | undefined): string[] {
  const me = String(transcript || '');
  const files: string[] = [];
  const seen = new Set<string>();
  for (const [key, rec] of Object.entries(ledger.reads || {})) {
    // Record fields where the entry has them; the key is the fallback for a ledger written
    // by an older adapter, so an in-flight session degrades quietly instead of losing its list.
    const parts = key.split('|');
    const owner = rec?.transcript ?? parts[0];
    const file = rec?.file ?? parts[1];
    if (!file || String(owner) !== me || seen.has(file)) continue;
    seen.add(file);
    files.push(file);
  }
  return files;
}

function preCompact(run: HookRun, input: HookInput): void {
  const ledger = readLedger(run, input.session_id);
  const mine = transcriptFiles(ledger, input.transcript_path || input.session_id);
  const files = mine.slice(0, PRECOMPACT_FILES_MAX);

  let scan: CheckpointScan | null = null;
  try {
    scan = openCheckpoint(input.cwd || process.cwd());
  } catch {
    scan = null;
  }
  const cp = scan && scan.winner;

  // The FIXED lines are assembled first and are never cut: they carry the instruction, and a
  // trimmed instruction steers worse than a trimmed list. Whatever budget they leave is what
  // the file list gets.
  const fixed: string[] = [];
  if (cp) {
    // The cursor names THE next unit; the schema keeps it at `plan.cursor`, never top level.
    const unit = cp.units.find((u) => u.id === cp.cursor);
    const at = unit
      ? `unit ${unit.id} (${unit.status})${unit.title ? ` — ${unit.title}` : ''}`
      : `unit ${cp.cursor}, which is not present in plan.units`;
    fixed.push(
      `${capBytes(`Open shiftwork checkpoint: ${cp.file}, cursor ${JSON.stringify(cp.cursor)} → ${at}.`, CHECKPOINT_LINE_MAX)} Preserve unit status and the next unit to clock in.`,
    );
  }
  fixed.push(
    'Preserve verbatim: every number the user was shown, every decision the user made, and any pending operator step.',
  );

  const room = PRECOMPACT_STDOUT_MAX - Buffer.byteLength(fixed.join('\n\n')) - 2;
  let block = files.length
    ? capLines(
        `Files already read in this context (keep the list; do not re-read unchanged ones after compaction):\n${files.map((f) => `- ${f}`).join('\n')}`,
        Math.max(0, room),
      )
    : '';
  // A header the budget left with no file under it steers nothing and costs bytes.
  const listed = (block.match(/^- /gm) || []).length;
  if (listed === 0) block = '';

  const ctx = [block, ...fixed].filter(Boolean).join('\n\n');
  const bytes = emitText(ctx);
  log(run, {
    event: 'PreCompact',
    trigger: input.trigger,
    ledgerFiles: mine.length,
    capped: files.length,
    listed,
    checkpoint: cp ? cp.file : null,
    cursor: cp ? cp.cursor : null,
    cpScanned: scan ? scan.scanned : 0,
    cpSkipped: scan ? scan.skipped : 0,
    cpBytes: scan ? scan.bytes : 0,
    bytes, // what LEFT the process, not what was considered
  });
}

// ------------------------------------------------------------------- PostCompact
function postCompact(run: HookRun, input: HookInput): void {
  try {
    fs.unlinkSync(ledgerPath(run, input.session_id));
  } catch {
    /* none */
  }
  log(run, { event: 'PostCompact', action: 'ledger-reset' });
}

// ------------------------------------------------------------------ Stop -> dream
// Row 5 of `docs/roadmap-toolbox.md` shipped `memory_dream`'s MECHANISM and left its TRIGGER
// open — the row still carries its own `STILL OPEN: the trigger` sentence. Before this arm
// the string `dream` did not occur anywhere in this file, so the consolidation ran only when
// a model chose to call the tool, which is precisely the operator-only design the user has
// already overruled once: `memory_compact` was built as the model's path on refusal and the
// user ruled compaction AUTOMATIC (2026-08-24). `postSave` is what that ruling produced, and
// this arm is the same move for consolidation.
//
// AMENDED 2026-09-12 (J50-2A). "THE SAME MOVE" WAS ONE STEP TOO FAR, AND THE USER RULED IT
// BACK. `postSave` moves facts inside ONE store. This arm moves facts OUT OF THE PROFILE
// STORE, which is machine-wide, and J45 had bounded exactly that cost by making `dry_run`
// default to TRUE — a real cross-layer merge was something somebody asked for. Firing the
// dream from `Stop` with `dry_run=false` made the mitigation stop existing: every session
// that ends inside a project whose store shares a name with the profile store archived the
// profile copy, silently, at the end of a turn nobody was watching. Measured on the user's
// own machine before this amendment: 14 of 20 profile facts in `~/.bantamkit/memory/archive/`,
// and a restore of 4 consumed again at the very next Stop (`.shiftwork/backlog.md` J49-B1).
//
// THE RULING: THE AUTOMATIC TRIGGER RUNS THE DREAM IN DRY-RUN ONLY. It never writes to any
// store. A real merge stays a deliberate call — the `memory_dream` MCP tool with
// `dry_run=false`. What the arm keeps is its early-warning value: the log says what a merge
// WOULD do, once per change to either layer, and a human decides. The accepted cost is
// stated rather than hidden: duplicates across the two layers now ACCUMULATE until somebody
// asks. This is not the self-merge of 2026-09-10 (row 13, closed by job47) — that was one
// directory bound as two layers; this is the designed cross-layer merge (row 5) firing
// without anyone asking for it. The tool is untouched; the TRIGGER is what changed.
//
// THE EVENT IS `Stop`, AND IT IS NOT THE ONE THE ROW NAMED. The row's spec said "run from a
// `SessionEnd`/cron". Re-derived from the user's own `~/.claude/settings.json` on
// 2026-09-10, the events that actually reach this hook are
//
//     PostCompact · PostToolUse · PreCompact · PreToolUse[Read]
//     SessionStart[startup|resume|clear|compact] · Stop · UserPromptSubmit
//
// and `SessionEnd` is NOT among them. The host supports the event; this registration simply
// does not carry it. A `SessionEnd` arm would therefore be INERT until the user edited their
// own settings file, and a unit may not edit the user's permission and hook surface. `Stop`
// already fires, already reads the per-session ledger, already decides whether to act, and
// fires at the END of a turn when no tool call is in flight. The row named a mechanism; the
// property it was after is that the consolidation happens without anyone asking, and `Stop`
// is the event on this machine that delivers it the moment this merges.
//
// THE GATE IS THE STORE'S OWN FINGERPRINT, because `Stop` fires every turn and a dream on
// every turn is a cost with no benefit. The pass runs only when a `facts/*.md` in either
// layer has appeared, vanished, or changed size or mtime since the last dream. A quiet turn
// costs one small JSON read, two `readdir`s and one `stat` per fact — measured at ~6 ms over
// the 121 facts on this machine, with no store loaded and no subprocess spawned.
//
// BOTH LAYERS ARE FINGERPRINTED ON PURPOSE. The profile store is machine-wide, so another
// project's session can add the very duplicate this session should consolidate. A gate keyed
// on THIS session's saves would never see it. For the same reason the marker lives beside the
// log in `~/.bantamkit/hooks/`, not in the per-session ledger: the question "has the store
// changed since the last dream" outlives any one session.
/**
 * Do two paths name the same directory? REALPATH, not `path.resolve`.
 *
 * `resolveProjectStore` hands back a realpath-resolved path and `os.homedir()` does not, so
 * on macOS the SAME directory arrives as `/private/var/folders/...` from one and
 * `/var/folders/...` from the other. `path.resolve` normalises `..` and makes a path
 * absolute; it does not follow symlinks, so it calls those two different and the guard below
 * would let a self-merge through. Measured: the first version of this guard did exactly that,
 * and the test that seeds a store under `tmpdir()` is what caught it.
 *
 * AMENDED 2026-09-11 (J47-7). Everything above stands as the reason this compares resolved
 * directories rather than strings, and the fallback's behaviour is unchanged. Two things it
 * says are now measured wrong.
 *
 * (1) THE MECHANISM. `fs.realpathSync` is not the kernel's realpath. It hands its argument to
 * `path.resolve` first, and `path.resolve` pops `..` LEXICALLY, before the symlink in front of
 * it has been followed. The comparison is now `realDir` (`realpathSync.native`) for J47-3B's
 * reasons (`6766033`), which closed the identical defect in the identical predicate in
 * `runtime-ts`'s `sameDirectory`.
 *
 * (2) "A PATH THAT CANNOT BE REALPATHED (IT DOES NOT EXIST YET)" IS THE WRONG DIAGNOSIS, and
 * it is wrong in the dangerous direction. Measured on J47-3B's bed (`link -> <bed>/deep/real`,
 * store at `<bed>/deep/.bantamkit/memory`, `HOME=<bed>/link/..`), the throwing argument was
 * the profile store, and the directory it names EXISTS: `realpathSync` threw because it had
 * already looked in the wrong place. `resolve` was not "the honest answer" there, it was the
 * wrong one, and this function answered `false` for one directory spelled two ways — so the
 * trigger below launched the dream it exists to skip.
 *
 * AND ON THAT BED THE `..` NEVER REACHED THIS FUNCTION, which is why repairing only this
 * predicate did not flip the decision and is worth writing down: `path.join` at the top of the
 * file had already popped it, so the profile path arrived here as `<bed>/.bantamkit/memory`, a
 * directory nothing had created — a real instance of the sentence above, arrived at by the
 * defect rather than by anyone's intent. The repair is therefore at BOTH ends: `HOME` is
 * resolved before it is joined, and this predicate no longer lets `path`'s lexical `..` decide.
 */
function samePath(a: string, b: string): boolean {
  return realDir(a) === realDir(b);
}

function storeFingerprint(roots: readonly string[]): string {
  const h = createHash('sha256');
  for (const root of roots) {
    h.update(`\u0000${root}\u0000`);
    let names: string[] = [];
    try {
      names = fs
        .readdirSync(path.join(root, 'facts'))
        .filter((n) => n.endsWith('.md'))
        .sort();
    } catch {
      /* a layer with no facts/ contributes its name and nothing else */
    }
    for (const n of names) {
      let st: fs.Stats;
      try {
        st = fs.statSync(path.join(root, 'facts', n));
      } catch {
        continue;
      }
      h.update(`${n}\u0000${st.size}\u0000${st.mtimeMs}\u0000`);
    }
  }
  return h.digest('hex');
}

interface DreamChildOutcome {
  status?: string;
  dryRun?: boolean;
  merged?: number;
  consumed?: number;
  absolutised?: number;
  superseded?: number;
  changes?: number;
  indexBefore?: number;
  indexAfter?: number;
  budget?: number;
}

/**
 * PREVIEW the consolidation, at most once per change to either layer, in a bounded child
 * process. Since J50-2A the child runs `dreamOutcome(true)` — a dry run — so nothing this
 * arm does moves a file; see the amendment in the header above for the ruling and the cost.
 *
 * NOTHING IS EMITTED. `stop` may answer the host with `decision: 'block'`, and two JSON
 * objects on one stdout is not a protocol — so this arm reports only into the hook log.
 *
 * THE CHILD IS `node -e`, NOT A CLI SUBCOMMAND, because there is no `dream` subcommand to
 * call: `memory_dream` is an MCP tool over `Memory.dreamOutcome`, and the memory CLI's
 * choices are status/lint/compact/archived/archive/restore. Adding one would be a runtime
 * change in both runtimes plus a conformance case — a different layer and a different unit.
 * The child gets `postSave`'s discipline: a `spawnSync` with a timeout, everything logged,
 * and any failure degrading to a log line rather than an exception.
 *
 * WHAT IS LOGGED IS WHAT THE PASS ACTUALLY FOUND, parsed out of the child's stdout — `status`,
 * `changes`, the index before and projected, and the counts it WOULD merge and consume. J46-6
 * measured the cost of the other habit: a log record whose fields are computed BEFORE the
 * spawn is vacuous, and its own first repair of that was itself vacuous for exactly that
 * reason.
 *
 * THE LOG LINE IS A DIFFERENT ACTION WITH DIFFERENT FIELD NAMES, ON PURPOSE. A dry run's line
 * is `action: 'dream-preview'` carrying `dryRun: true`, `wouldMerge` and `wouldConsume`; the
 * line a real merge wrote was `action: 'dream'` with `merged` and `consumed`. The log is the
 * only place a human sees this arm, and "would have merged 14" must never read as "merged 14"
 * — so the preview carries NO field named `merged` at all, rather than the same field under a
 * flag a reader could miss.
 */
function maybeDream(run: HookRun, input: HookInput): void {
  const cwd = input.cwd || process.cwd();
  let projectRoot: string;
  try {
    projectRoot = resolveProjectStore(cwd).path;
  } catch (e) {
    log(run, { event: 'Stop', action: 'dream-skip', reason: 'unresolved-store', error: message(e) });
    return;
  }
  // THE TWO LAYERS MUST BE TWO DIRECTORIES, AND MEASURED ON 2026-09-10 THEY ARE NOT ALWAYS.
  // `resolveProjectStore` WALKS UP from the cwd, so a session whose cwd has no project store
  // above it resolves the profile store itself as the "project" store — `~/.bantamkit/memory`
  // bound as BOTH layers. `dream` then merges that store with ITSELF: every fact matches
  // itself by name, is merged into itself, and the "profile copy" — the same file — is
  // archived, which empties `facts/`.
  //
  // THIS IS NOT HYPOTHETICAL. It happened to the user's real profile store while this arm was
  // being written: a live `Stop` in a session running outside any project consolidated 20 of
  // 20 facts into the archive with `indexBefore == indexAfter == 3974`, the giveaway that the
  // "project" index and the profile index were one number because they were one store. The
  // facts were restored from `archive/` (`dream` is reversible by design, which is the only
  // reason that was recoverable) and this guard is why it cannot recur.
  //
  // AMENDED 2026-09-11 (J47-7). "THE GUARD LIVES HERE, IN THE TRIGGER, NOT IN `dream`" IS NO
  // LONGER TRUE. It is kept anyway, deliberately: `Memory.layered` now refuses to bind one
  // directory as two layers in BOTH runtimes — `_same_directory` in Python (J47-1, `0844ccb`),
  // `sameDirectory` in Node (J47-2, `a3afb7c`, corrected by J47-3B, `6766033`) — and the
  // refusal is gated by conformance cases (J47-3 `ecaf427`, J47-3B `1bd1a43`). This guard
  // costs one realpath compare, it refuses BEFORE a child process is spawned rather than
  // inside it, and a working refusal is not deleted on the strength of a change that shipped
  // the same day.
  //
  // AND UNTIL J47-7 IT WAS NOT ANSWERING CORRECTLY, which is the other half of that unit and
  // the reason the redundancy was worth having. On J47-3B's bed this trigger fired the dream
  // it exists to skip — measured, the hook's own log line was
  //   {"event":"Stop","action":"dream","status":"no-profile-layer","merged":0,"consumed":0}
  // i.e. the MECHANISM refused and the TRIGGER did not: defence in depth working in the
  // direction nobody planned for. Two things were wrong and both are repaired above — `HOME`
  // is resolved in the kernel's order before it is joined (`path.join` was popping the `..`
  // lexically), and `samePath` no longer uses `fs.realpathSync`, which pops `..` the same way.
  if (samePath(projectRoot, run.profile)) {
    log(run, { event: 'Stop', action: 'dream-skip', reason: 'single-layer', root: projectRoot });
    return;
  }
  const roots = [projectRoot, run.profile];
  const fingerprint = storeFingerprint(roots);
  const prior = readJsonSafe(run.dreamState);
  if (prior['fingerprint'] === fingerprint) {
    log(run, { event: 'Stop', action: 'dream-skip', reason: 'unchanged', fingerprint: fingerprint.slice(0, 12) });
    return;
  }
  const script = `(async () => {
    const { Memory } = await import(${JSON.stringify(path.join(DIST, 'component.js'))});
    // DRY RUN, by the ruling of 2026-09-12 (J50-2A). Passing \`false\` here is what archived
    // the user's profile facts; \`true\` is the J45 default and the only value this arm may pass.
    const o = Memory.layered(process.argv[1]).dreamOutcome(true);
    process.stdout.write(JSON.stringify({ status: o.status, dryRun: o.dryRun, merged: o.merged, consumed: o.consumed,
      absolutised: o.absolutised, superseded: o.superseded, changes: o.result ? o.result.changes : 0,
      indexBefore: o.indexBefore, indexAfter: o.indexAfter, budget: o.budget }));
  })().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });`;
  const t = Date.now();
  const r = spawnSync(process.execPath, ['-e', script, cwd], {
    encoding: 'utf8',
    timeout: dreamTimeoutMs(),
  });
  const ms = Date.now() - t;
  let outcome: DreamChildOutcome | null = null;
  try {
    outcome = JSON.parse(r.stdout || '') as DreamChildOutcome;
  } catch {
    /* a child that died has no JSON to give */
  }
  if (outcome === null) {
    // A failed or timed-out pass must NOT record the new fingerprint: the next Stop should
    // try again rather than treat an unconsolidated store as already dreamt.
    // `timedOut` AND NOT `signal`. `spawnSync` reports the timeout kill as an `ETIMEDOUT`
    // error on every platform, whereas `signal` is a POSIX notion: on Windows the kill is
    // `TerminateProcess` and there is no SIGTERM to report. `signal` is kept because it is
    // informative where it exists, but the field that MEANS "the bound stopped this" is the
    // portable one, and it is the one anything asserting on this arm should read.
    const err = r.error as (Error & { code?: string }) | undefined;
    log(run, {
      event: 'Stop',
      action: 'dream-failed',
      ms,
      exit: r.status,
      signal: r.signal ?? null,
      timedOut: err !== undefined && err.code === 'ETIMEDOUT',
      error: `${r.stderr || ''}`.trim().slice(0, 400) || String(err?.message || ''),
    });
    return;
  }
  // THE MARKER ADVANCES AFTER A DRY RUN, DELIBERATELY. It answers "has either layer changed
  // since the last look", never "is the store consolidated" — the status it records is the
  // pass's own (`previewed`, `nothing-to-consolidate`, ...), so a preview cannot mark anything
  // as merged. NOT advancing it would spawn a child on every Stop for as long as one duplicate
  // exists, which is the every-turn cost the header rules out; advancing it keeps the cadence
  // the arm always had — one report per change to either layer — and the deliberate
  // `memory_dream` merge that finally consumes the duplicate moves a file, so it re-arms the
  // gate by itself and the next Stop reports the store clean.
  //
  // The fingerprint is still recomputed AFTER the pass, as it was when the pass could move
  // files. For a dry run the two numbers must be equal, and `storeMoved` on the log line says
  // whether they were: a preview that moved anything is the bug this unit closed, come back.
  const after = storeFingerprint(roots);
  writeJsonSafe(run.dreamState, {
    fingerprint: after,
    at: new Date().toISOString(),
    status: outcome.status,
    dryRun: true,
  });
  log(run, {
    event: 'Stop',
    action: 'dream-preview',
    ms,
    dryRun: true,
    status: outcome.status,
    wouldMerge: outcome.merged,
    wouldConsume: outcome.consumed,
    wouldAbsolutise: outcome.absolutised,
    wouldSupersede: outcome.superseded,
    changes: outcome.changes,
    indexBefore: outcome.indexBefore,
    indexProjected: outcome.indexAfter,
    budget: outcome.budget,
    storeMoved: after !== fingerprint,
  });
}

// -------------------------------------------------------------------------- Stop
// The experience collector. Once per session, when the session did real work and nothing
// durable was written, hand the turn back with one instruction. The host's `type:prompt`
// hook could judge this with a model call; a grep over the transcript is free.
function stop(run: HookRun, input: HookInput): void {
  if (input.stop_hook_active) return;
  const ledger = readLedger(run, input.session_id);
  if (ledger.stopNudged) return;
  let text = '';
  try {
    text = fs.readFileSync(String(input.transcript_path ?? ''), 'utf8');
  } catch {
    return;
  }
  const toolUses = (text.match(/"type":\s*"tool_use"/g) || []).length;
  const saved =
    (ledger.saved || 0) > 0 ||
    /"name":\s*"mcp__bantamkit__memory_save"/.test(text) ||
    /"file_path":"[^"]*[\\/]memory[\\/][^"]*\.md"/.test(text);
  if (toolUses < STOP_NUDGE_MIN_TOOL_CALLS || saved) {
    log(run, { event: 'Stop', action: 'pass', toolUses, saved });
    return;
  }
  ledger.stopNudged = true;
  writeLedger(run, input.session_id, ledger);
  log(run, { event: 'Stop', action: 'nudge', toolUses });
  emit({
    decision: 'block',
    reason: `bantamkit: this session made ${toolUses} tool calls and saved no memory. Before stopping, decide whether anything durable was learned that is NOT derivable from the repo, git history, or docs — a correction or preference the user stated (feedback), a fact about ongoing work or a decision (project), a URL/ticket/dashboard (reference). If so, call mcp__bantamkit__memory_save for each (at most 3, description written as the words a future query would use). If nothing qualifies, stop with one line saying so. This nudge fires once per session.`,
  });
}

// ---------------------------------------------------------------------- dispatch

/** Read the whole of stdin. One JSON object is the entire input contract. */
async function readStdin(): Promise<string> {
  let raw = '';
  for await (const chunk of process.stdin) raw += chunk;
  return raw;
}

/**
 * `bantamkit-mcp --hook`: ONE JSON object in, AT MOST ONE JSON object out, and the caller
 * exits 0 whatever happens.
 *
 * NOTHING HERE THROWS PAST THE CALLER. `cli.ts` wraps this in the same `catch → log → 0` the
 * standalone script's last line was, because a hook that exits non-zero or writes a stack to
 * stderr is rendered by the host as an error on the user's screen.
 */
export async function runHook(): Promise<void> {
  const run = newRun();
  const raw = await readStdin();
  let input: HookInput = {};
  try {
    const parsed: unknown = JSON.parse(raw || '{}');
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) input = parsed as HookInput;
  } catch {
    log(run, { event: 'parse-error', raw: raw.slice(0, 200) });
    return;
  }
  const ev = input.hook_event_name;
  // Before ANY arm binds a store: the winning registration's `BANTAMKIT_MEMORY_DIR`, applied
  // to this process so `pinnedStore()` sees what the server sees (J50-1). Two small file
  // reads, measured at 0.6 ms on this machine's 164 kB `~/.claude.json`.
  applyRegistrationStorePin(run, input.cwd || process.cwd());
  switch (ev) {
    case 'SessionStart':
      return sessionStart(run, input);
    case 'UserPromptSubmit':
      return userPromptSubmit(run, input);
    case 'PreToolUse':
      return input.tool_name === 'Read' ? preToolUseRead(run, input) : undefined;
    case 'PostToolUse':
      appendUsageEvent(run, input); // every tool, not just bantamkit's — it is a usage denominator
      return input.tool_name === 'mcp__bantamkit__memory_save' ? postSave(run, input) : undefined;
    case 'PreCompact':
      return preCompact(run, input);
    case 'PostCompact':
      return postCompact(run, input);
    case 'Stop':
      maybeDream(run, input); // gated on the store changing; logs only, never emits
      return stop(run, input);
    default:
      log(run, { event: ev, action: 'ignored' });
  }
}

/** The `catch` half of the contract, so `cli.ts` states it in one line. */
export function logHookFailure(e: unknown): void {
  log(newRun(), { event: 'error', error: String((e instanceof Error && e.stack) || e) });
}
