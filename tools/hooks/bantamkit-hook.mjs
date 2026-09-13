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
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

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
function realDir(p) {
  try { return fs.realpathSync.native(p); } catch { return path.resolve(p); }
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
const HOME = realDir(os.homedir());
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
const CHECKPOINT_LINE_MAX = 600;   // one checkpoint line: an absolute path, a cursor, a title

// The Stop-triggered consolidation pass. See `maybeDream` for why the event is `Stop`.
const DREAM_STATE = path.join(STATE, 'dream-state.json');
// The host kills the WHOLE hook at 10 s (`timeout: 10` in the registration), so the child's
// bound has to sit under that. A measured consolidation of the 121 facts on this machine
// took 72 ms, so the headroom is two orders of magnitude.
//
// THE ENV OVERRIDE IS A TEST SEAM AND NOTHING ELSE. Without it the timeout is a constant no
// test can reach, and this repo has been bitten twice by arithmetic in this file that drifted
// because nothing ran it. With it, `hooks.test.mjs` sets a 1 ms bound and exercises a REAL
// SIGTERM kill of a real child, which is the only way to show that a slow pass degrades to a
// log line instead of eating the session.
const DREAM_TIMEOUT_MS = Number(process.env.BANTAMKIT_DREAM_TIMEOUT_MS) || 8000;

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
const SESSION_DROP_RULE = 'durable types first, then most recently recalled (else created) first, then name';

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
async function cappedIndex(root, header, max) {
  const { MemoryStore, DURABLE_TYPES, pyEqualValue, pyText } = await import(path.join(DIST, 'store.js'));
  const { facts, indexLine } = new MemoryStore(root).internals();
  const all = facts().map((fact, position) => ({ fact, position, line: indexLine(fact), name: pyText(fact.name) }));
  const text = (value) => (value == null ? '' : pyText(value));
  const decays = (f) => (DURABLE_TYPES.some((durable) => pyEqualValue(f.fact.type, durable)) ? 0 : 1);
  const evidence = (f) => text(f.fact.last_recalled) || text(f.fact.created);
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const ranked = [...all].sort((a, b) =>
    decays(a) - decays(b) || cmp(evidence(b), evidence(a)) || cmp(a.name, b.name) || a.position - b.position);
  const kept = new Set();
  let size = 0;
  for (const f of ranked) {
    const n = Buffer.byteLength(f.line);
    if (size + n > max) continue;
    kept.add(f);
    size += n;
  }
  const shown = all.filter((f) => kept.has(f));
  const dropped = ranked.filter((f) => !kept.has(f)).map((f) => f.name);
  const body = capLines(shown.map((f) => f.line).join('').replace(/\n$/, ''), max);
  const lines = [header(dropped.length ? `${shown.length} of ${all.length}` : String(all.length))];
  if (body) lines.push(body);
  if (dropped.length) {
    lines.push(`[${dropped.length} of ${all.length} not shown — the block is capped at ${max} bytes; kept by rule: ${SESSION_DROP_RULE}; ~/.bantamkit/hooks/hook-log.jsonl names the dropped; mcp__bantamkit__memory_recall reads any fact by name]`);
  }
  return { block: lines.join('\n'), total: all.length, injected: shown.length, dropped };
}

function countFacts(store) {
  try { return fs.readdirSync(path.join(store, 'facts')).filter((n) => n.endsWith('.md')).length; } catch { return 0; }
}

// ---------------------------------------------------------------- SessionStart
async function sessionStart(input) {
  const cwd = input.cwd || process.cwd();
  const parts = [];
  const profileFacts = countFacts(PROFILE);
  let profile = { injected: 0, dropped: [] };
  if (profileFacts > 0) {
    profile = await cappedIndex(PROFILE, (count) => `[bantamkit profile memory — ${count} facts learned across projects]`, SESSION_INJECT_MAX);
    parts.push(profile.block);
  }
  // A project store that is NOT the profile dir and has no native MEMORY.md beside it:
  // inject its index too, otherwise the host already carries an index for this cwd.
  let project = null;
  try {
    const { discoverProjectStore } = await import(path.join(DIST, 'layers.js'));
    const store = discoverProjectStore(cwd);
    if (path.resolve(store) !== path.resolve(PROFILE) && countFacts(store) > 0 && !nativeMemoryExists(cwd)) {
      project = await cappedIndex(store, (count) => `[bantamkit project memory — ${count} facts]`, SESSION_INJECT_MAX);
      project.facts = countFacts(store);
      parts.push(project.block);
    }
  } catch (e) { log({ event: 'SessionStart', warn: String(e.message || e) }); }
  parts.push('[bantamkit] Toolbox is live: mcp__bantamkit__memory_recall reads the body of any fact above; memory_save stores a durable lesson (feedback|user|project|reference — never something derivable from the repo). Repeat reads of an unchanged file are refused once by the filegraph hook; a save nudge fires once at session end when nothing was saved.');
  const ctx = parts.join('\n\n');
  if (input.source === 'compact') {
    // context was just rebuilt: earlier reads are gone, so the read ledger must not refuse them
    try { fs.unlinkSync(ledgerPath(input.session_id)); } catch { /* none */ }
  }
  // `profileFacts` keeps its old meaning — files in the store — so older records stay
  // comparable; `profileInjected` / `profileDropped` are what the block carried and did
  // not, and `dropRule` is the order the drop followed. The project trio appears only when
  // a project block was injected at all.
  log({
    event: 'SessionStart', source: input.source, cwd, bytes: Buffer.byteLength(ctx),
    profileFacts, profileInjected: profile.injected, profileDropped: profile.dropped,
    ...(project ? { projectFacts: project.facts, projectInjected: project.injected, projectDropped: project.dropped } : {}),
    dropRule: SESSION_DROP_RULE, storeScope: STORE_SCOPE,
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
function scoreHeader(head, queryTokens, tokenize) {
  const m = RECALL_HEADER.exec(head);
  if (!m) return null;
  const [, layer, name, type, description] = m;
  let score = 0;
  for (const t of tokenize(`${name} ${description}`)) if (queryTokens.has(t)) score += 1;
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
function promptFingerprint(prompt) {
  return {
    sha256: createHash('sha256').update(prompt, 'utf8').digest('hex'),
    chars: prompt.length,
    bytes: Buffer.byteLength(prompt),
  };
}

async function userPromptSubmit(input) {
  const prompt = String(input.prompt || '').trim();
  if (prompt.length < PROMPT_MIN_CHARS || prompt.startsWith('/')) {
    log({ event: 'UserPromptSubmit', action: 'skip', reason: 'short-or-command' });
    return;
  }
  const { Memory } = await loadMemory();
  const { tokens } = await import(path.join(DIST, 'store.js'));
  const m = Memory.layered(input.cwd || process.cwd());
  const o = m.recallOutcome(prompt, 3);
  if (o.status !== 'answered') {
    log({ event: 'UserPromptSubmit', action: 'none', status: o.status, candidates: o.candidates });
    return;
  }
  // Only the HEADER line of each hit — `[layer] [name] (type) description`. The body costs
  // ~1.5 KB a fact and would be re-sent on every later call; the header is ~150 B and
  // tells the model exactly which name to pass to memory_recall if it wants the body.
  const heads = o.reply.split('\n').filter((l) => RECALL_HEADER.test(l));
  if (heads.length === 0) { log({ event: 'UserPromptSubmit', action: 'none', reason: 'no-headers' }); return; }
  const ctx = capLines(`[bantamkit recall — memories that match this prompt; call mcp__bantamkit__memory_recall with the name for the body]\n${heads.join('\n')}`, PROMPT_INJECT_MAX);
  // `injected` is read back off `ctx`, NOT off `heads`. The byte cap drops whole lines, so a
  // header that `recallOutcome` picked need not have left the process — and roadmap #6 asks
  // "was an INJECTED name later used", a question a name the model never saw would poison.
  // `hits` keeps its old meaning (headers picked, pre-cap) so the 487 records written before
  // this change stay comparable; `dropped` is the difference the old shape could not show.
  const queryTokens = tokens(prompt);
  const injected = ctx.split('\n')
    .map((l) => scoreHeader(l, queryTokens, tokens))
    .filter((x) => x !== null);
  log({
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
function appendUsageEvent(input) {
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
    detail: tool === 'Skill' ? String(ti.skill ?? '')
      : tool === 'Agent' ? String(ti.subagent_type || 'general-purpose')
        : '',
  };
  const dir = process.env.TOOL_METRICS_DIR
    || path.join(os.homedir(), '.claude', 'tool-metrics');
  const file = path.join(dir, 'events.jsonl');
  try {
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(file, `${JSON.stringify(record)}\n`);
    pruneUsageEvents(file);
  } catch { /* the log is a convenience; never fail a tool call over it */ }
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
function pruneUsageEvents(file) {
  let size = 0;
  try { size = fs.statSync(file).size; } catch { return; }
  if (size <= EVENTS_MAX_BYTES) return;

  const projects = path.join(HOME, '.claude', 'projects');
  const onDisk = new Set();
  const walk = (dir) => {
    let entries = [];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      if (e.isDirectory()) { onDisk.add(e.name); walk(path.join(dir, e.name)); }
      else if (e.name.endsWith('.jsonl')) onDisk.add(e.name.slice(0, -'.jsonl'.length));
    }
  };
  walk(projects);
  // A walk that found nothing is an unreadable projects dir, not a machine with no
  // transcripts. Pruning on that reading would delete the whole log.
  if (onDisk.size === 0) { log({ event: 'PostToolUse', action: 'prune-skipped', reason: 'no transcripts found', size }); return; }

  const kept = [];
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    let record;
    try { record = JSON.parse(line); } catch { kept.push(line); continue; }  // keep what we cannot judge
    if (!record?.session || !onDisk.has(record.session)) kept.push(line);
  }
  const tmp = `${file}.prune-${process.pid}`;
  fs.writeFileSync(tmp, kept.length ? `${kept.join('\n')}\n` : '');
  fs.renameSync(tmp, file);
  log({ event: 'PostToolUse', action: 'prune', before: size, after: fs.statSync(file).size, kept: kept.length });
}

// ---------------------------------------------- the server's actual --index-budget
// (and, since J50-1, the server's actual store pin — the walk below is shared by both)
// `Memory.layered(cwd)` opens the project store at DEFAULT_INDEX_BUDGET unless told
// otherwise, and the MCP server honours `--index-budget N` (`runtime-ts/src/cli.ts:123-130`).
// A RUNNING server never writes that number down anywhere: `MemoryStore` keeps `indexBudget`
// in memory only (`runtime-ts/src/memory/store.ts:483`), so nothing publishes it and this
// file cannot be made to (that would be a change inside `runtime-ts/src/memory`, a different
// layer and a different unit). The one place the value survives between "the operator
// configured it" and "this short-lived hook process needs it" is the SAME configuration a
// Claude Code session itself reads to decide which server to start.
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
function readJsonSafe(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return {}; }
}

/** Best-effort marker write. A marker that cannot be written costs a repeated dream, not a crash. */
function writeJsonSafe(file, value) {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(value));
  } catch { /* the gate degrades to "always fires", which is safe and merely not free */ }
}

function indexBudgetFromArgs(args) {
  if (!Array.isArray(args)) return undefined;
  for (let i = 0; i < args.length; i += 1) {
    const a = args[i];
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

/**
 * The `--index-budget` the `bantamkit` registration a session in `cwd` would actually launch
 * carries — resolved by Claude Code's own MCP scope precedence, `local > project > user`, over
 * the WHOLE entry. Cheap: two small file reads, and none of it requires the server to be up.
 *
 * Returns `{ budget, scope }`. `budget` is `undefined` when the winning entry configures no
 * `--index-budget` and when no scope registers `bantamkit` at all; `scope` names the entry
 * that won, or is `null` when none did, so the log says WHICH file the number came from.
 */
function configuredIndexBudget(cwd) {
  const { entry, scope } = winningRegistration(cwd);
  return entry ? { budget: indexBudgetFromArgs(entry.args), scope } : { budget: undefined, scope: null };
}

/**
 * The `bantamkit` registration entry a session in `cwd` actually launched, and the scope it
 * came from — the walk `configuredIndexBudget` has always done, lifted out (J50-1) so that
 * `env` is read off the SAME entry as `args`. One walk, two fields; a second walk would be
 * the second place the precedence rule could be got wrong.
 *
 * Returns `{ entry, scope }`, both `null` when no scope registers `bantamkit` at all.
 */
function winningRegistration(cwd) {
  const repo = path.resolve(cwd);
  const claudeJson = readJsonSafe(path.join(HOME, '.claude.json'));
  const mcpJson = readJsonSafe(path.join(repo, '.mcp.json'));
  // Highest precedence first. Order is the whole point; do not sort or reorder.
  const scopes = [
    ['local', claudeJson?.projects?.[repo]?.mcpServers?.bantamkit],
    ['project', mcpJson?.mcpServers?.bantamkit],
    ['user', claudeJson?.mcpServers?.bantamkit],
  ];
  for (const [scope, entry] of scopes) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue;
    return { entry, scope };
  }
  return { entry: null, scope: null };
}

// ------------------------------------------------ the server's actual store pin (J50-1)
//
// `discoverProjectStore`, `resolveProjectStore` and `Memory.layered` — every store the hook
// binds, in every arm — resolve through `pinnedStore()` in `dist/memory/layers.js`, which
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
let STORE_SCOPE = null;   // the scope whose entry pinned the store this process binds, for the log

function applyRegistrationStorePin(cwd) {
  const { entry, scope } = winningRegistration(cwd);
  const env = entry && entry.env;
  if (!env || typeof env !== 'object' || Array.isArray(env)) return;
  if (!Object.prototype.hasOwnProperty.call(env, 'BANTAMKIT_MEMORY_DIR')) return;
  const value = env.BANTAMKIT_MEMORY_DIR;
  if (typeof value !== 'string') return;
  process.env.BANTAMKIT_MEMORY_DIR = value;
  STORE_SCOPE = value.trim() === '' ? null : scope;
}

// ---------------------------------------------- PostToolUse memory_save → compact
async function postSave(input) {
  const ledger = readLedger(input.session_id);
  ledger.saved = (ledger.saved || 0) + 1;
  writeLedger(input.session_id, ledger);
  const cwd = input.cwd || process.cwd();
  const configured = configuredIndexBudget(cwd);
  const budgetSource = configured.budget !== undefined ? 'configured' : 'default';
  const budgetScope = configured.budget !== undefined ? configured.scope : null;
  const { Memory } = await loadMemory();
  const m = Memory.layered(cwd, configured.budget !== undefined ? { indexBudget: configured.budget } : {});
  const [bytes, budget] = m.indexAccounting();
  if (bytes == null || bytes < COMPACT_AT * budget) {
    log({ event: 'PostToolUse', action: 'saved', bytes, budget, budgetSource, budgetScope });
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
  const r = spawnSync(process.execPath, [path.join(DIST, 'cli.js'), 'compact', '--store', m.store.root ?? m.store.path ?? '', '--budget', String(budget), '--reserve', String(reserve)], { encoding: 'utf8', timeout: 8000 });
  const out = `${r.stdout || ''}${r.stderr || ''}`.trim();
  log({ event: 'PostToolUse', action: 'auto-compact', bytes, budget, target, reserve, budgetSource, budgetScope, exit: r.status, out: out.slice(0, 400) });
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
 * A path that cannot be realpathed (it does not exist yet) falls back to `resolve`, which is
 * the honest answer for a directory nothing has created.
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
 * `PROFILE`, and the directory it names EXISTS: `realpathSync` threw because it had already
 * looked in the wrong place. `resolve` was not "the honest answer" there, it was the wrong
 * one, and this function answered `false` for one directory spelled two ways — so the trigger
 * below launched the dream it exists to skip.
 *
 * AND ON THAT BED THE `..` NEVER REACHED THIS FUNCTION, which is why repairing only this
 * predicate did not flip the decision and is worth writing down: `path.join` at the top of the
 * file had already popped it, so `PROFILE` arrived here as `<bed>/.bantamkit/memory`, a
 * directory nothing had created — a real instance of the sentence above, arrived at by the
 * defect rather than by anyone's intent. The repair is therefore at BOTH ends: `HOME` is
 * resolved before it is joined, and this predicate no longer lets `path`'s lexical `..` decide.
 */
function samePath(a, b) {
  return realDir(a) === realDir(b);
}

function storeFingerprint(roots) {
  const h = createHash('sha256');
  for (const root of roots) {
    h.update(`\u0000${root}\u0000`);
    let names = [];
    try {
      names = fs.readdirSync(path.join(root, 'facts')).filter((n) => n.endsWith('.md')).sort();
    } catch { /* a layer with no facts/ contributes its name and nothing else */ }
    for (const n of names) {
      let st;
      try { st = fs.statSync(path.join(root, 'facts', n)); } catch { continue; }
      h.update(`${n}\u0000${st.size}\u0000${st.mtimeMs}\u0000`);
    }
  }
  return h.digest('hex');
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
async function maybeDream(input) {
  const cwd = input.cwd || process.cwd();
  let projectRoot;
  try {
    const { resolveProjectStore } = await import(path.join(DIST, 'layers.js'));
    projectRoot = resolveProjectStore(cwd).path;
  } catch (e) {
    log({ event: 'Stop', action: 'dream-skip', reason: 'unresolved-store', error: String(e && e.message || e) });
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
  // THE GUARD LIVES HERE, IN THE TRIGGER, NOT IN `dream`. The defect is `Memory.layered`
  // binding one directory twice, and `memory_dream`'s behaviour is pinned by a conformance
  // suite in both runtimes — changing it is a different layer and a different unit, and it is
  // registered as such in `docs/roadmap-toolbox.md`. What this unit owns is WHEN to fire, and
  // "when the two layers are the same directory" is never.
  //
  // AMENDED 2026-09-11 (J47-7). "THE GUARD LIVES HERE, IN THE TRIGGER, NOT IN `dream`" IS NO
  // LONGER TRUE. Everything above it stands as the reason this guard was written, and as the
  // record of the incident that caused it; it is no longer the reason it is the only guard,
  // because it is not. `Memory.layered` now refuses to bind one directory as two layers in
  // BOTH runtimes — `_same_directory` in Python (J47-1, `0844ccb`), `sameDirectory` in Node
  // (J47-2, `a3afb7c`, corrected by J47-3B, `6766033`) — and the refusal is gated by
  // conformance cases (J47-3 `ecaf427`, J47-3B `1bd1a43`), which is exactly what row 13 of
  // `docs/roadmap-toolbox.md` predicted would make this guard "redundant rather than
  // load-bearing". It is kept anyway, deliberately: it costs one realpath compare, it refuses
  // BEFORE a child process is spawned rather than inside it, and a working refusal is not
  // deleted on the strength of a change that shipped the same day.
  //
  // AND UNTIL THIS UNIT IT WAS NOT ANSWERING CORRECTLY, which is the other half of J47-7 and
  // the reason the redundancy was worth having. On J47-3B's bed (`link -> <bed>/deep/real`,
  // store at `<bed>/deep/.bantamkit/memory`, `HOME=<bed>/link/..`) this trigger fired the
  // dream it exists to skip — measured, the hook's own log line was
  //   {"event":"Stop","action":"dream","status":"no-profile-layer","merged":0,"consumed":0}
  // i.e. the MECHANISM refused and the TRIGGER did not: defence in depth working in the
  // direction nobody planned for. Two things were wrong and both are repaired above — `HOME`
  // is resolved in the kernel's order before it is joined (`path.join` was popping the `..`
  // lexically, so `PROFILE` named a directory that does not exist), and `samePath` no longer
  // uses `fs.realpathSync`, which pops `..` the same lexical way. Same bed, after:
  //   {"event":"Stop","action":"dream-skip","reason":"single-layer","root":".../deep/.bantamkit/memory"}
  if (samePath(projectRoot, PROFILE)) {
    log({ event: 'Stop', action: 'dream-skip', reason: 'single-layer', root: projectRoot });
    return;
  }
  const roots = [projectRoot, PROFILE];
  const fingerprint = storeFingerprint(roots);
  const prior = readJsonSafe(DREAM_STATE);
  if (prior.fingerprint === fingerprint) {
    log({ event: 'Stop', action: 'dream-skip', reason: 'unchanged', fingerprint: fingerprint.slice(0, 12) });
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
  const r = spawnSync(process.execPath, ['-e', script, cwd], { encoding: 'utf8', timeout: DREAM_TIMEOUT_MS });
  const ms = Date.now() - t;
  let outcome = null;
  try { outcome = JSON.parse(r.stdout || ''); } catch { /* a child that died has no JSON to give */ }
  if (outcome === null) {
    // A failed or timed-out pass must NOT record the new fingerprint: the next Stop should
    // try again rather than treat an unconsolidated store as already dreamt.
    // `timedOut` AND NOT `signal`. `spawnSync` reports the timeout kill as an `ETIMEDOUT`
    // error on every platform, whereas `signal` is a POSIX notion: on Windows the kill is
    // `TerminateProcess` and there is no SIGTERM to report. `signal` is kept because it is
    // informative where it exists, but the field that MEANS "the bound stopped this" is the
    // portable one, and it is the one anything asserting on this arm should read.
    log({ event: 'Stop', action: 'dream-failed', ms, exit: r.status, signal: r.signal ?? null,
      timedOut: r.error !== undefined && r.error.code === 'ETIMEDOUT',
      error: `${r.stderr || ''}`.trim().slice(0, 400) || String(r.error && r.error.message || '') });
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
  writeJsonSafe(DREAM_STATE, { fingerprint: after, at: new Date().toISOString(), status: outcome.status, dryRun: true });
  log({
    event: 'Stop', action: 'dream-preview', ms, dryRun: true, status: outcome.status,
    wouldMerge: outcome.merged, wouldConsume: outcome.consumed,
    wouldAbsolutise: outcome.absolutised, wouldSupersede: outcome.superseded,
    changes: outcome.changes, indexBefore: outcome.indexBefore, indexProjected: outcome.indexAfter,
    budget: outcome.budget, storeMoved: after !== fingerprint,
  });
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
  // Before ANY arm binds a store: the winning registration's `BANTAMKIT_MEMORY_DIR`, applied
  // to this process so `pinnedStore()` sees what the server sees (J50-1). Two small file
  // reads, measured at 0.6 ms on this machine's 164 kB `~/.claude.json`.
  applyRegistrationStorePin(input.cwd || process.cwd());
  switch (ev) {
    case 'SessionStart': return sessionStart(input);
    case 'UserPromptSubmit': return userPromptSubmit(input);
    case 'PreToolUse': return input.tool_name === 'Read' ? preToolUseRead(input) : undefined;
    case 'PostToolUse':
      appendUsageEvent(input); // every tool, not just bantamkit's — it is a usage denominator
      return input.tool_name === 'mcp__bantamkit__memory_save' ? postSave(input) : undefined;
    case 'PreCompact': return preCompact(input);
    case 'PostCompact': return postCompact(input);
    case 'Stop':
      await maybeDream(input);   // gated on the store changing; logs only, never emits
      return stop(input);
    default: log({ event: ev, action: 'ignored' });
  }
}

main().catch((e) => log({ event: 'error', error: String(e && e.stack || e) })).finally(() => process.exit(0));
