#!/usr/bin/env node
// Was an injected memory name later USED? — roadmap #6's measurement, and nothing more.
//
//   node tools/ledger/injection-precision.mjs
//   node tools/ledger/injection-precision.mjs --json
//   node tools/ledger/injection-precision.mjs --log <hook-log.jsonl> --projects <dir>
//
// THE QUESTION. `tools/hooks/bantamkit-hook.mjs` injects up to three recall headers ahead of
// a user prompt. Roadmap #6 wants a precision gate on that — inject only a hit whose score
// clears a threshold — and a gate needs a hit rate to be set against. This joins each
// injection to the host's own transcript for the SAME session and asks whether any injected
// name was afterwards passed to `memory_recall` or written back by the assistant.
//
// HISTORY STARTS THE DAY THE NEW HOOK RECORD SHIPS. The 487 injection records written before
// it carry `hits` and `bytes` only: no names, no scores, and no `session`, so they cannot even
// be matched to a transcript. There is no retroactive baseline and no honest way to build one,
// so this tool counts only records carrying `injected[]` and says so on every run.
//
// WHAT THE TWO SIGNALS PROVE, EXACTLY.
//
//   recall  — the name appears in the arguments of a later `mcp__bantamkit__memory_recall`
//             call in the same session's MAIN transcript. Strong: the header line tells the
//             model to pass the name to that tool, so this is the injection's own call to
//             action being followed. It still does not prove the recall was USEFUL, only that
//             the name reached the model and the model acted on it.
//   quoted  — the name appears in a later assistant message in that transcript. Weak, and
//             CONFOUNDED BY DESIGN: the SessionStart arm injects the whole index — every fact
//             name in the store — once per session, so every name is already in context before
//             any prompt-level injection happens. A quote is therefore consistent with the
//             prompt injection having done nothing at all.
//
// Which is why there is a CONTROL. For each injection, the same two signals are measured over
// names that were NOT injected in that session (drawn from the names this log has seen
// injected under the same cwd). If control and injected rates match, the injection is not what
// caused the use, whatever the injected rate looks like on its own. Never quote the injected
// rate without the control beside it.
//
// NEITHER SIGNAL IS CAUSAL. Both are "the name appears later in the same session". A name that
// would have been used anyway counts as a hit; a fact whose CONTENT steered the model without
// its name being written counts as a miss. The rate is a floor on usefulness measured through
// a keyhole, and the control is the only thing keeping it honest.
//
// SIDECHAINS ARE NOT COUNTED. `<project>/<session>/subagents/*.jsonl` carry the parent
// `sessionId` with `isSidechain: true`. A subagent has its own context and never received the
// parent's UserPromptSubmit injection, so a name it writes is not evidence about the
// injection. They are counted separately and reported, uncounted, so the exclusion is visible.
//
// IT REFUSES ON THIN DATA, the way `skill-discovery-check.mjs` does. A ratio computed off six
// samples is not a measurement, and the failure mode it invites — cutting a threshold to chase
// a number that was noise — is exactly what #6 must not do. The floors below are SAMPLE-SIZE
// floors. This tool chooses no precision threshold: that is J45-6/J45-7's job, off the data
// this starts collecting.
//
// Pure Node, no dependencies, read-only. It opens the hook log and the host's transcripts and
// writes nothing anywhere; it never touches a memory store.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// ---------------------------------------------------------------- sample floors
// Not a precision threshold — a floor on how much data will be spoken about at all.
//
// 100 injections: the measure roadmap #6 names is "hit rate per 100 injections". Below 100
// the "per 100" is extrapolation from a smaller number, and the reader cannot see that in a
// percentage. At n=100 a rate near 20% still carries a 95% interval about ±8 points wide, so
// 100 is the floor for saying anything, not the point at which the number is precise.
//
// 5 sessions: one session is one operator on one task, and injected names track what that
// task was about. A rate off a single session measures the task, not the gate.
const MIN_INJECTIONS = 100;
const MIN_SESSIONS = 5;

const args = process.argv.slice(2);
const flag = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };
const JSON_OUT = args.includes('--json');
const HOME = os.homedir();
const LOG = flag('--log', path.join(HOME, '.bantamkit', 'hooks', 'hook-log.jsonl'));
const PROJECTS = flag('--projects', path.join(HOME, '.claude', 'projects'));

/** Wilson score interval, so a rate is never printed without its width. */
function wilson(hits, n, z = 1.96) {
  if (n === 0) return [0, 0];
  const p = hits / n;
  const d = 1 + (z * z) / n;
  const centre = p + (z * z) / (2 * n);
  const half = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n));
  return [Math.max(0, (centre - half) / d), Math.min(1, (centre + half) / d)];
}

/**
 * A fact name matches only on its own token boundaries.
 *
 * `deploy-flag` must not be found inside `deploy-flag-v2`, and the names are slugs made of
 * `[a-z0-9-]`, so the boundary is "not another slug character on either side". Case-insensitive
 * because an assistant writing a name mid-sentence may capitalise it.
 */
function nameMatcher(name) {
  const esc = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`(?<![a-z0-9-])${esc}(?![a-z0-9-])`, 'i');
}

// ---------------------------------------------------------------- the hook log
function readInjections(file) {
  let lines = [];
  try { lines = fs.readFileSync(file, 'utf8').split('\n'); } catch { return { records: [], legacy: 0, total: 0 }; }
  const records = [];
  let legacy = 0;
  let total = 0;
  for (const line of lines) {
    if (!line) continue;
    let r; try { r = JSON.parse(line); } catch { continue; }
    if (r.event !== 'UserPromptSubmit' || r.action !== 'inject') continue;
    total += 1;
    // The pre-instrument shape. `injected` absent is the whole reason this tool has no
    // history before today; a record without `session` could not be joined even if it had
    // names, so both are required before a record is counted.
    if (!Array.isArray(r.injected) || !r.session) { legacy += 1; continue; }
    records.push({ ts: Date.parse(r.ts), session: r.session, injected: r.injected, bytes: r.bytes, hits: r.hits });
  }
  return { records, legacy, total };
}

// ------------------------------------------------------------- the transcripts
/**
 * `sessionId` → the events a name could later appear in.
 *
 * Main-transcript `memory_recall` arguments and assistant text, each with a timestamp, plus
 * the sidechain text kept apart. `<project>/<session>/subagents/*.jsonl` carry the parent
 * `sessionId`, so the split is on `isSidechain`, not on the path — see `token-ledger.mjs`,
 * which walks the same tree for the same reason.
 */
function readSessions(root) {
  const files = [];
  const walk = (d) => {
    let es = [];
    try { es = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
    for (const e of es) {
      const q = path.join(d, e.name);
      if (e.isDirectory()) walk(q);
      else if (e.name.endsWith('.jsonl')) files.push(q);
    }
  };
  walk(root);

  const sessions = new Map();
  const get = (id) => {
    if (!sessions.has(id)) sessions.set(id, { cwd: null, recalls: [], assistant: [], sidechain: [] });
    return sessions.get(id);
  };
  for (const p of files) {
    let text; try { text = fs.readFileSync(p, 'utf8'); } catch { continue; }
    for (const line of text.split('\n')) {
      if (!line) continue;
      let r; try { r = JSON.parse(line); } catch { continue; }
      const sid = r.sessionId; if (!sid) continue;
      const s = get(sid);
      if (r.cwd && !s.cwd) s.cwd = r.cwd;
      if (r.type !== 'assistant') continue;
      const t = Date.parse(r.timestamp || '') || 0;
      for (const b of r.message?.content || []) {
        if (b.type === 'tool_use' && b.name === 'mcp__bantamkit__memory_recall') {
          const where = r.isSidechain ? s.sidechain : s.recalls;
          where.push({ t, text: JSON.stringify(b.input ?? '') });
        } else if (b.type === 'text' && typeof b.text === 'string') {
          (r.isSidechain ? s.sidechain : s.assistant).push({ t, text: b.text });
        }
      }
    }
  }
  return sessions;
}

/** Did `name` appear in any event strictly after `after`? */
function usedAfter(events, re, after) {
  for (const e of events) if (e.t > after && re.test(e.text)) return true;
  return false;
}

// ------------------------------------------------------------------- the join
const { records, legacy, total } = readInjections(LOG);
const sessions = readSessions(PROJECTS);

// The control universe, per cwd: every name this log has ever seen injected in a session whose
// transcript reports the same cwd. Drawn from the LOG, never from the user's memory store —
// nothing here opens a store.
const namesByCwd = new Map();
const cwdOf = (sid) => sessions.get(sid)?.cwd ?? null;
for (const r of records) {
  const cwd = cwdOf(r.session); if (!cwd) continue;
  if (!namesByCwd.has(cwd)) namesByCwd.set(cwd, new Set());
  for (const inj of r.injected) if (inj?.name) namesByCwd.get(cwd).add(inj.name);
}
const injectedInSession = new Map();
for (const r of records) {
  if (!injectedInSession.has(r.session)) injectedInSession.set(r.session, new Set());
  for (const inj of r.injected) if (inj?.name) injectedInSession.get(r.session).add(inj.name);
}

const matchers = new Map();
const matcher = (n) => { if (!matchers.has(n)) matchers.set(n, nameMatcher(n)); return matchers.get(n); };

const joined = [];        // one entry per injection record that HAS a transcript
const unjoinable = [];    // records whose session is not on disk
let sidechainOnly = 0;    // names used only by a subagent — reported, never counted
const byScore = new Map();
const control = { n: 0, recall: 0, quoted: 0 };

for (const r of records) {
  const s = sessions.get(r.session);
  if (!s) { unjoinable.push(r); continue; }
  const names = r.injected.map((i) => i?.name).filter(Boolean);
  let anyRecall = false;
  let anyQuote = false;
  for (const inj of r.injected) {
    if (!inj?.name) continue;
    const re = matcher(inj.name);
    const recalled = usedAfter(s.recalls, re, r.ts);
    const quoted = usedAfter(s.assistant, re, r.ts);
    if (!recalled && !quoted && usedAfter(s.sidechain, re, r.ts)) sidechainOnly += 1;
    anyRecall ||= recalled;
    anyQuote ||= quoted;
    const key = Number(inj.score) || 0;
    if (!byScore.has(key)) byScore.set(key, { n: 0, recall: 0, quoted: 0 });
    const b = byScore.get(key);
    b.n += 1; if (recalled) b.recall += 1; if (quoted) b.quoted += 1;
  }
  joined.push({ ts: r.ts, session: r.session, names, recall: anyRecall, quoted: anyQuote });

  // CONTROL, same window, same session, same two signals — over names this session never had
  // injected. Sampled to the size of the real injection so the two arms weigh the same.
  const pool = [...(namesByCwd.get(s.cwd) ?? [])].filter((n) => !injectedInSession.get(r.session)?.has(n));
  for (const n of pool.slice(0, names.length)) {
    const re = matcher(n);
    control.n += 1;
    if (usedAfter(s.recalls, re, r.ts)) control.recall += 1;
    if (usedAfter(s.assistant, re, r.ts)) control.quoted += 1;
  }
}

const sessionCount = new Set(joined.map((j) => j.session)).size;
const hitRecall = joined.filter((j) => j.recall).length;
const hitEither = joined.filter((j) => j.recall || j.quoted).length;
const firstTs = records.length ? Math.min(...records.map((r) => r.ts)) : null;

const shortfall = [];
if (joined.length < MIN_INJECTIONS) shortfall.push(`${MIN_INJECTIONS - joined.length} more joinable injections (have ${joined.length}, need ${MIN_INJECTIONS})`);
if (sessionCount < MIN_SESSIONS) shortfall.push(`${MIN_SESSIONS - sessionCount} more distinct sessions (have ${sessionCount}, need ${MIN_SESSIONS})`);
if (control.n === 0) shortfall.push('a control arm — no session has a name it did not inject, so there is nothing to compare against');
const refused = shortfall.length > 0;

const pct = (h, n) => (n === 0 ? '—' : `${(100 * h / n).toFixed(1)}%`);
const ci = (h, n) => {
  if (n === 0) return '';
  const [lo, hi] = wilson(h, n);
  return `[${(100 * lo).toFixed(1)}–${(100 * hi).toFixed(1)}]`;
};

if (JSON_OUT) {
  console.log(JSON.stringify({
    log: LOG,
    injectionRecords: { total, legacyNoNamesOrSession: legacy, instrumented: records.length },
    joined: joined.length,
    unjoinable: unjoinable.length,
    sessions: sessionCount,
    historyStarts: firstTs ? new Date(firstTs).toISOString() : null,
    refused,
    needs: shortfall,
    floors: { minInjections: MIN_INJECTIONS, minSessions: MIN_SESSIONS },
    // Reported whether or not a verdict is refused: the counts are facts, the RATE is what
    // the refusal withholds. A consumer that divides these itself has chosen to.
    counts: {
      recallSignal: hitRecall,
      eitherSignal: hitEither,
      control: { n: control.n, recall: control.recall, quoted: control.quoted },
      sidechainOnly,
      byScore: Object.fromEntries([...byScore.entries()].sort((a, b) => a[0] - b[0])),
    },
    signalMeaning: {
      recall: 'name appears in a later memory_recall argument in the same main transcript',
      quoted: 'name appears in a later assistant message — confounded by the SessionStart index injection',
      causal: false,
    },
  }, null, 1));
  process.exit(0);
}

console.log('injection precision — was an injected memory name later used?\n');
console.log(`  log                     ${LOG}`);
console.log(`  injection records       ${total} total, ${records.length} carry names+scores+session, ${legacy} predate this instrument`);
console.log(`  history starts          ${firstTs ? new Date(firstTs).toISOString() : '— nothing instrumented yet'}`);
console.log(`  joined to a transcript  ${joined.length} across ${sessionCount} session(s); ${unjoinable.length} record(s) had no transcript on disk`);
console.log(`  control arm             ${control.n} name-window(s) that were NOT injected\n`);

if (refused) {
  console.log('REFUSED — the sample cannot support a rate, so none is printed.\n');
  for (const s of shortfall) console.log(`  needs: ${s}`);
  console.log(`\n  Raw counts, which are facts even when the ratio is not: ${hitRecall} of ${joined.length}`);
  console.log(`  injection(s) were followed by a memory_recall carrying an injected name;`);
  console.log(`  ${hitEither} by either signal. Dividing those is exactly what this refusal withholds.`);
  console.log('\n  There is NO retroactive baseline. The records that predate this instrument carry');
  console.log('  neither the injected names nor a session id, so they cannot be joined to anything.');
  console.log('  Hit-rate history starts at the timestamp above and grows one prompt at a time.');
  console.log('\n  Nothing here names a precision threshold. Setting one is J45-6/J45-7\'s job, and it');
  console.log('  has to be set off this tool returning a verdict — not off these counts.');
  process.exit(0);
}

console.log(`${'signal'.padEnd(34)} ${'hits'.padStart(6)} ${'of'.padStart(6)} ${'rate'.padStart(7)}  95% CI`);
console.log(`${'injected → later memory_recall'.padEnd(34)} ${String(hitRecall).padStart(6)} ${String(joined.length).padStart(6)} ${pct(hitRecall, joined.length).padStart(7)}  ${ci(hitRecall, joined.length)}`);
console.log(`${'injected → recall or quoted'.padEnd(34)} ${String(hitEither).padStart(6)} ${String(joined.length).padStart(6)} ${pct(hitEither, joined.length).padStart(7)}  ${ci(hitEither, joined.length)}`);
console.log(`${'CONTROL not-injected → recall'.padEnd(34)} ${String(control.recall).padStart(6)} ${String(control.n).padStart(6)} ${pct(control.recall, control.n).padStart(7)}  ${ci(control.recall, control.n)}`);
console.log(`${'CONTROL not-injected → quoted'.padEnd(34)} ${String(control.quoted).padStart(6)} ${String(control.n).padStart(6)} ${pct(control.quoted, control.n).padStart(7)}  ${ci(control.quoted, control.n)}`);
console.log('\nIf the CONTROL rows sit inside the injected rows\' intervals, the injection is not what');
console.log('caused the use, and no threshold cut off the injected rate alone will change that.\n');

console.log(`${'score'.padStart(6)} ${'names'.padStart(7)} ${'recall'.padStart(8)} ${'quoted'.padStart(8)}`);
for (const [score, b] of [...byScore.entries()].sort((a, b2) => a[0] - b2[0])) {
  console.log(`${String(score).padStart(6)} ${String(b.n).padStart(7)} ${pct(b.recall, b.n).padStart(8)} ${pct(b.quoted, b.n).padStart(8)}`);
}
console.log(`\n${sidechainOnly} injected name(s) were used ONLY inside a subagent transcript and are counted as`);
console.log('misses: a subagent never received the parent\'s injection, so its use is not evidence.');
console.log('\nThis tool names no precision threshold. It reports what happened.');
