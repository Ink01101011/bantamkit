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

function log(record) {
  try {
    fs.mkdirSync(STATE, { recursive: true });
    fs.appendFileSync(LOG, JSON.stringify({ ts: new Date().toISOString(), ms: Date.now() - T0, ...record }) + '\n');
  } catch { /* logging is best-effort */ }
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj));
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
  const key = `${input.transcript_path || input.session_id}|${file}|${ti.offset ?? ''}|${ti.limit ?? ''}`;
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
  ledger.reads[key] = { sig, at: new Date().toISOString(), count: (prev ? prev.count : 0) + 1, refused: false };
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
    case 'PostCompact': return postCompact(input);
    case 'Stop': return stop(input);
    default: log({ event: ev, action: 'ignored' });
  }
}

main().catch((e) => log({ event: 'error', error: String(e && e.stack || e) })).finally(() => process.exit(0));
