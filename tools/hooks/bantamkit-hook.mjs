#!/usr/bin/env node
// The Claude Code HOOK adapter. One file, every event, dispatched on `hook_event_name`.
//
// WHY THIS EXISTS. Measured 2026-08-27 over the host's own MCP logs, last 7 days: 103
// bantamkit connections, 8 `memory_recall` calls, 3 of them outside this repo. An MCP
// server is PASSIVE — nothing in the host invokes a tool the model did not decide to call,
// and the model does not decide to call a recall whose answer already rides free in the
// system prompt. Hooks are the only deterministic channel the host offers, so the
// automatic half of the toolbox — recall before the turn, refuse a repeat read, nudge a
// save before the session ends, compact the index when it is nearly full — lives HERE,
// at the host boundary, and the MCP tools stay what the model calls when it wants more.
//
// THE THREE PROPERTIES, same as the statusline adapter beside it:
//   1. CHEAP. Loads `runtime-ts/dist/memory` in-process; never starts an MCP server.
//   2. NEVER LOUD. Every arm ends in exit 0. A hook that throws would be rendered by the
//      host as an error on the user's screen, so every failure is LOGGED and swallowed.
//   3. MEASURED. Every decision appends one line to `~/.bantamkit/hooks/hook-log.jsonl`
//      (event, action, bytes injected, ms) so the claim "it fires and it is cheap" is a
//      number the user can rerun, not a sentence.
//
// Registration (user scope, `~/.claude/settings.json`): see `docs/hooks.md`.
// Pure Node, POSIX + Windows; nothing here shells Python.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const T0 = Date.now();
const HOME = os.homedir();
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..', '..');
const DIST = path.join(REPO, 'runtime-ts', 'dist', 'memory');
const STATE = path.join(HOME, '.bantamkit', 'hooks');
const LOG = path.join(STATE, 'hook-log.jsonl');
const PROFILE = path.join(HOME, '.bantamkit', 'memory');

// Budgets, in BYTES of injected context. SessionStart is paid once; UserPromptSubmit is
// paid on every later call of the session, which is why it is the small one.
const SESSION_INJECT_MAX = 3000;
const PROMPT_INJECT_MAX = 700;
const PROMPT_MIN_CHARS = 12;
const STOP_NUDGE_MIN_TOOL_CALLS = 20;
const COMPACT_AT = 0.9;   // index >= 90% of budget → compact …
const COMPACT_TO = 0.8;   // … down to 80%, past the no-op band measured in job40 (C6)

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
const CHECKPOINT_LINE_MAX = 600;   // one checkpoint line: an absolute path, a cursor, a title

function log(record) {
  try {
    fs.mkdirSync(STATE, { recursive: true });
    fs.appendFileSync(LOG, JSON.stringify({ ts: new Date().toISOString(), ms: Date.now() - T0, ...record }) + '\n');
  } catch { /* logging is best-effort */ }
}

function emit(obj) {
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
function emitText(text) {
  const out = String(text).trim();
  if (!out) return 0;
  process.stdout.write(out);
  return Buffer.byteLength(out);
}

/** Truncate to at most `max` BYTES without splitting a UTF-8 character. */
function capBytes(text, max) {
  const buf = Buffer.from(String(text), 'utf8');
  if (buf.length <= max) return String(text);
  let end = max;
  while (end > 0 && (buf[end] & 0xc0) === 0x80) end -= 1;   // back off a continuation byte
  return buf.subarray(0, end).toString('utf8');
}

function capLines(text, max) {
  if (Buffer.byteLength(text) <= max) return text;
  const out = [];
  let size = 0;
  for (const line of text.split('\n')) {
    const n = Buffer.byteLength(line) + 1;
    if (size + n > max) break;
    out.push(line);
    size += n;
  }
  return out.join('\n');
}

function ledgerPath(sessionId) {
  return path.join(STATE, `ledger-${String(sessionId || 'nosession').replace(/[^\w-]/g, '_')}.json`);
}
function readLedger(sessionId) {
  try { return JSON.parse(fs.readFileSync(ledgerPath(sessionId), 'utf8')); } catch { return { reads: {} }; }
}
function writeLedger(sessionId, ledger) {
  fs.mkdirSync(STATE, { recursive: true });
  fs.writeFileSync(ledgerPath(sessionId), JSON.stringify(ledger));
}

async function loadMemory() {
  const mod = path.join(DIST, 'component.js');
  if (!fs.existsSync(mod)) throw new Error(`runtime-ts is not built: ${mod} missing (run npm run build in runtime-ts)`);
  return import(mod);
}

/** `~/.claude/projects/<slug>/memory/MEMORY.md` — the host's own auto-memory for this cwd. */
function nativeMemoryExists(cwd) {
  const slug = cwd.replace(/[\\/:]/g, '-');
  return fs.existsSync(path.join(HOME, '.claude', 'projects', slug, 'memory', 'MEMORY.md'));
}

/** The index as the store computes it — `index.md` on disk is only rewritten by a save. */
async function indexText(root) {
  const { MemoryStore } = await import(path.join(DIST, 'store.js'));
  return new MemoryStore(root).indexText();
}

function countFacts(store) {
  try { return fs.readdirSync(path.join(store, 'facts')).filter((n) => n.endsWith('.md')).length; } catch { return 0; }
}

// ---------------------------------------------------------------- SessionStart
async function sessionStart(input) {
  const cwd = input.cwd || process.cwd();
  const parts = [];
  const profileFacts = countFacts(PROFILE);
  if (profileFacts > 0) {
    const idx = await indexText(PROFILE);
    parts.push(`[bantamkit profile memory — ${profileFacts} facts learned across projects]\n${capLines(idx, SESSION_INJECT_MAX)}`);
  }
  // A project store that is NOT the profile dir and has no native MEMORY.md beside it:
  // inject its index too, otherwise the host already carries an index for this cwd.
  try {
    const { discoverProjectStore } = await import(path.join(DIST, 'layers.js'));
    const store = discoverProjectStore(cwd);
    if (path.resolve(store) !== path.resolve(PROFILE) && countFacts(store) > 0 && !nativeMemoryExists(cwd)) {
      const idx = await indexText(store);
      parts.push(`[bantamkit project memory — ${countFacts(store)} facts]\n${capLines(idx, SESSION_INJECT_MAX)}`);
    }
  } catch (e) { log({ event: 'SessionStart', warn: String(e.message || e) }); }
  parts.push('[bantamkit] Toolbox is live: mcp__bantamkit__memory_recall reads the body of any fact above; memory_save stores a durable lesson (feedback|user|project|reference — never something derivable from the repo). Repeat reads of an unchanged file are refused once by the filegraph hook; a save nudge fires once at session end when nothing was saved.');
  const ctx = parts.join('\n\n');
  if (input.source === 'compact') {
    // context was just rebuilt: earlier reads are gone, so the read ledger must not refuse them
    try { fs.unlinkSync(ledgerPath(input.session_id)); } catch { /* none */ }
  }
  log({ event: 'SessionStart', source: input.source, cwd, bytes: Buffer.byteLength(ctx), profileFacts });
  emit({ hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: ctx } });
}

// ------------------------------------------------------------ UserPromptSubmit
async function userPromptSubmit(input) {
  const prompt = String(input.prompt || '').trim();
  if (prompt.length < PROMPT_MIN_CHARS || prompt.startsWith('/')) {
    log({ event: 'UserPromptSubmit', action: 'skip', reason: 'short-or-command' });
    return;
  }
  const { Memory } = await loadMemory();
  const m = Memory.layered(input.cwd || process.cwd());
  const o = m.recallOutcome(prompt, 3);
  if (o.status !== 'answered') {
    log({ event: 'UserPromptSubmit', action: 'none', status: o.status, candidates: o.candidates });
    return;
  }
  // Only the HEADER line of each hit — `[layer] [name] (type) description`. The body costs
  // ~1.5 KB a fact and would be re-sent on every later call; the header is ~150 B and
  // tells the model exactly which name to pass to memory_recall if it wants the body.
  const heads = o.reply.split('\n').filter((l) => /^\[[^\]]+\] \[[^\]]+\] \([a-z]+\) /.test(l));
  if (heads.length === 0) { log({ event: 'UserPromptSubmit', action: 'none', reason: 'no-headers' }); return; }
  const ctx = capLines(`[bantamkit recall — memories that match this prompt; call mcp__bantamkit__memory_recall with the name for the body]\n${heads.join('\n')}`, PROMPT_INJECT_MAX);
  log({ event: 'UserPromptSubmit', action: 'inject', hits: heads.length, bytes: Buffer.byteLength(ctx), source: o.source });
  emit({ hookSpecificOutput: { hookEventName: 'UserPromptSubmit', additionalContext: ctx } });
}

// ------------------------------------------------------------- PreToolUse Read
// The filegraph, over the OPERATOR's reads. `filegraph.md` measured the mechanism as net
// positive and never a loss (cache pays only on a repeat); it could not reach these reads
// because they never pass through bantamkit's Agent. A PreToolUse hook is the one place
// that does see them. Keyed by transcript (a subagent has its own transcript and has NOT
// seen the parent's read), by path+offset+limit, and by mtime+size so an edit re-arms it.
// REFUSES ONCE: the second identical call goes through, so nothing can be hard-blocked.
function preToolUseRead(input) {
  const ti = input.tool_input || {};
  const file = ti.file_path;
  if (!file) return;
  let st;
  try { st = fs.statSync(file); } catch { return; } // missing file: let Read produce its own error
  // The transcript is the CONTEXT dimension: a subagent has its own transcript and has not
  // seen the parent's reads. It is carried on the record as well as in the key, because
  // `preCompact` must filter on it and a path may itself contain the key's delimiter.
  const transcript = String(input.transcript_path || input.session_id || '');
  const key = `${transcript}|${file}|${ti.offset ?? ''}|${ti.limit ?? ''}`;
  const ledger = readLedger(input.session_id);
  const prev = ledger.reads[key];
  const sig = `${st.mtimeMs}|${st.size}`;
  if (prev && prev.sig === sig && !prev.refused) {
    prev.refused = true;
    prev.count += 1;
    writeLedger(input.session_id, ledger);
    const reason = `bantamkit filegraph: ${file}${ti.offset != null ? ` (offset ${ti.offset}${ti.limit != null ? `, limit ${ti.limit}` : ''})` : ''} was already read in this context at ${prev.at} and is unchanged on disk (same mtime and size). Use the content from that earlier read. If you genuinely need it again, repeat the exact same call — this refusal fires only once per unchanged file.`;
    log({ event: 'PreToolUse', action: 'refuse', file, size: st.size });
    emit({ hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: reason } });
    return;
  }
  ledger.reads[key] = { sig, at: new Date().toISOString(), count: (prev ? prev.count : 0) + 1, refused: false, transcript, file };
  writeLedger(input.session_id, ledger);
  log({ event: 'PreToolUse', action: prev ? 'allow-after-refuse-or-change' : 'record', file, size: st.size });
}

// ---------------------------------------------- PostToolUse memory_save → compact
async function postSave(input) {
  const ledger = readLedger(input.session_id);
  ledger.saved = (ledger.saved || 0) + 1;
  writeLedger(input.session_id, ledger);
  const { Memory } = await loadMemory();
  const m = Memory.layered(input.cwd || process.cwd());
  const [bytes, budget] = m.indexAccounting();
  if (bytes == null || bytes < COMPACT_AT * budget) {
    log({ event: 'PostToolUse', action: 'saved', bytes, budget });
    return;
  }
  // The user ruled compaction automatic (2026-08-24). `compact` archives the stalest facts
  // until the index sits at --budget; aiming at 80% skips the 90–99.2% band where the
  // default reserve makes it a no-op.
  const target = Math.floor(COMPACT_TO * budget);
  const r = spawnSync(process.execPath, [path.join(DIST, 'cli.js'), 'compact', '--store', m.store.root ?? m.store.path ?? '', '--budget', String(target)], { encoding: 'utf8', timeout: 8000 });
  const out = `${r.stdout || ''}${r.stderr || ''}`.trim();
  log({ event: 'PostToolUse', action: 'auto-compact', bytes, budget, target, exit: r.status, out: out.slice(0, 400) });
  emit({ hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: `[bantamkit] memory index was ${bytes}/${budget} B; auto-compacted to ≤${target} B. ${out.slice(0, 600)}` } });
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
const CHECKPOINT_MAX_BYTES = 4_000_000;        // ONE checkpoint file
// … and an AGGREGATE, because nothing bounded the COUNT. `.shiftwork` accumulates a
// checkpoint per archived job and is never pruned: measured on this repo on 2026-09-04,
// 136,885 B across 6 files, 11 KB of it added by a single session's orchestrator. Every one
// of them was read and JSON-parsed on every compaction, so the worst case was n × 4 MB.
// Candidates are scanned newest-first — the order that already decides the winner — so the
// scan stops at the first OPEN one (on this repo: 1 file, 20,417 B, down from 6 and 136,885)
// and what a spent budget drops is always the OLDEST, the least likely to be the open one.
const CHECKPOINT_SCAN_MAX_BYTES = 1_000_000;
const CHECKPOINT_SCAN_MAX_FILES = 64;

/**
 * The structure `assets/schemas/shiftwork-checkpoint.json` requires of the parts this arm
 * reads: `plan.cursor` is a non-empty string and `plan.units` is a non-empty array of units
 * carrying `id` and `status`. Deliberately NOT a full schema validation — a hook that loads
 * a JSON-Schema validator stops being cheap, and a checkpoint that satisfies this shape but
 * fails the full schema still yields a true steering line.
 */
function checkpointShape(doc) {
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return null;
  const plan = doc.plan;
  if (!plan || typeof plan !== 'object' || Array.isArray(plan)) return null;
  const { cursor, units } = plan;
  if (typeof cursor !== 'string' || cursor.length === 0) return null;
  if (!Array.isArray(units) || units.length === 0) return null;
  const ok = units.every((u) => u && typeof u === 'object' && typeof u.id === 'string' && typeof u.status === 'string');
  return ok ? { cursor, units } : null;
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
function openCheckpoint(cwd) {
  const dir = path.join(cwd, '.shiftwork');
  let names;
  try { names = fs.readdirSync(dir).filter((n) => n.endsWith('.json')); } catch { return null; }

  // stat first (cheap, and the mtime is what orders the scan), read second (the expensive
  // half, and the one the budget bounds). Same comparator the winner was already chosen by,
  // so applying it before the read changes which files are READ, never which one wins.
  const candidates = [];
  for (const name of names) {
    const file = path.join(dir, name);
    try {
      const st = fs.statSync(file);
      if (!st.isFile() || st.size > CHECKPOINT_MAX_BYTES) continue;
      candidates.push({ file, mtimeMs: st.mtimeMs, size: st.size });
    } catch { /* unreadable: skip */ }
  }
  candidates.sort((a, b) => b.mtimeMs - a.mtimeMs || a.file.localeCompare(b.file));

  let bytes = 0;
  let read = 0;
  let winner = null;
  for (const c of candidates) {
    // The budget is checked BEFORE each read and never before the first, so the newest
    // candidate is always considered however large it is (bounded by CHECKPOINT_MAX_BYTES).
    if (read > 0 && (bytes >= CHECKPOINT_SCAN_MAX_BYTES || read >= CHECKPOINT_SCAN_MAX_FILES)) break;
    let doc;
    try { doc = JSON.parse(fs.readFileSync(c.file, 'utf8')); } catch { read += 1; bytes += c.size; continue; }
    read += 1;
    bytes += c.size;
    const shape = checkpointShape(doc);
    if (!shape) continue;
    if (!shape.units.some((u) => u.status !== 'done' && u.status !== 'dropped')) continue;
    winner = { file: c.file, mtimeMs: c.mtimeMs, ...shape };
    break;   // newest-first: the first open one IS the most recent open one
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
function transcriptFiles(ledger, transcript) {
  const me = String(transcript || '');
  const files = [];
  const seen = new Set();
  for (const [key, rec] of Object.entries(ledger.reads || {})) {
    // Record fields where the entry has them; the key is the fallback for a ledger written
    // by an older adapter, so an in-flight session degrades quietly instead of losing its list.
    const parts = key.split('|');
    const owner = (rec && rec.transcript) ?? parts[0];
    const file = (rec && rec.file) ?? parts[1];
    if (!file || String(owner) !== me || seen.has(file)) continue;
    seen.add(file);
    files.push(file);
  }
  return files;
}

function preCompact(input) {
  const ledger = readLedger(input.session_id);
  const mine = transcriptFiles(ledger, input.transcript_path || input.session_id);
  const files = mine.slice(0, PRECOMPACT_FILES_MAX);

  let scan = null;
  try { scan = openCheckpoint(input.cwd || process.cwd()); } catch { scan = null; }
  const cp = scan && scan.winner;

  // The FIXED lines are assembled first and are never cut: they carry the instruction, and a
  // trimmed instruction steers worse than a trimmed list. Whatever budget they leave is what
  // the file list gets.
  const fixed = [];
  if (cp) {
    // The cursor names THE next unit; the schema keeps it at `plan.cursor`, never top level.
    const unit = cp.units.find((u) => u.id === cp.cursor);
    const at = unit
      ? `unit ${unit.id} (${unit.status})${unit.title ? ` — ${unit.title}` : ''}`
      : `unit ${cp.cursor}, which is not present in plan.units`;
    fixed.push(capBytes(`Open shiftwork checkpoint: ${cp.file}, cursor ${JSON.stringify(cp.cursor)} → ${at}.`, CHECKPOINT_LINE_MAX)
      + ' Preserve unit status and the next unit to clock in.');
  }
  fixed.push('Preserve verbatim: every number the user was shown, every decision the user made, and any pending operator step.');

  const room = PRECOMPACT_STDOUT_MAX - Buffer.byteLength(fixed.join('\n\n')) - 2;
  let block = files.length
    ? capLines(`Files already read in this context (keep the list; do not re-read unchanged ones after compaction):\n${files.map((f) => `- ${f}`).join('\n')}`, Math.max(0, room))
    : '';
  // A header the budget left with no file under it steers nothing and costs bytes.
  const listed = (block.match(/^- /gm) || []).length;
  if (listed === 0) block = '';

  const ctx = [block, ...fixed].filter(Boolean).join('\n\n');
  const bytes = emitText(ctx);
  log({
    event: 'PreCompact', trigger: input.trigger,
    ledgerFiles: mine.length, capped: files.length, listed,
    checkpoint: cp ? cp.file : null, cursor: cp ? cp.cursor : null,
    cpScanned: scan ? scan.scanned : 0, cpSkipped: scan ? scan.skipped : 0, cpBytes: scan ? scan.bytes : 0,
    bytes,   // what LEFT the process, not what was considered
  });
}

// ------------------------------------------------------------------- PostCompact
function postCompact(input) {
  try { fs.unlinkSync(ledgerPath(input.session_id)); } catch { /* none */ }
  log({ event: 'PostCompact', action: 'ledger-reset' });
}

// -------------------------------------------------------------------------- Stop
// The experience collector. Once per session, when the session did real work and nothing
// durable was written, hand the turn back with one instruction. The host's `type:prompt`
// hook could judge this with a model call; a grep over the transcript is free.
function stop(input) {
  if (input.stop_hook_active) return;
  const ledger = readLedger(input.session_id);
  if (ledger.stopNudged) return;
  let text = '';
  try { text = fs.readFileSync(input.transcript_path, 'utf8'); } catch { return; }
  const toolUses = (text.match(/"type":\s*"tool_use"/g) || []).length;
  const saved = (ledger.saved || 0) > 0 || /"name":\s*"mcp__bantamkit__memory_save"/.test(text) || /"file_path":"[^"]*[\\/]memory[\\/][^"]*\.md"/.test(text);
  if (toolUses < STOP_NUDGE_MIN_TOOL_CALLS || saved) {
    log({ event: 'Stop', action: 'pass', toolUses, saved });
    return;
  }
  ledger.stopNudged = true;
  writeLedger(input.session_id, ledger);
  log({ event: 'Stop', action: 'nudge', toolUses });
  emit({
    decision: 'block',
    reason: `bantamkit: this session made ${toolUses} tool calls and saved no memory. Before stopping, decide whether anything durable was learned that is NOT derivable from the repo, git history, or docs — a correction or preference the user stated (feedback), a fact about ongoing work or a decision (project), a URL/ticket/dashboard (reference). If so, call mcp__bantamkit__memory_save for each (at most 3, description written as the words a future query would use). If nothing qualifies, stop with one line saying so. This nudge fires once per session.`,
  });
}

// ---------------------------------------------------------------------- dispatch
async function main() {
  let raw = '';
  for await (const chunk of process.stdin) raw += chunk;
  let input = {};
  try { input = JSON.parse(raw || '{}'); } catch { log({ event: 'parse-error', raw: raw.slice(0, 200) }); return; }
  const ev = input.hook_event_name;
  switch (ev) {
    case 'SessionStart': return sessionStart(input);
    case 'UserPromptSubmit': return userPromptSubmit(input);
    case 'PreToolUse': return input.tool_name === 'Read' ? preToolUseRead(input) : undefined;
    case 'PostToolUse': return input.tool_name === 'mcp__bantamkit__memory_save' ? postSave(input) : undefined;
    case 'PreCompact': return preCompact(input);
    case 'PostCompact': return postCompact(input);
    case 'Stop': return stop(input);
    default: log({ event: ev, action: 'ignored' });
  }
}

main().catch((e) => log({ event: 'error', error: String(e && e.stack || e) })).finally(() => process.exit(0));
