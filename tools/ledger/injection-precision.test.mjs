#!/usr/bin/env node
// Agreement test for tools/ledger/injection-precision.mjs.
//
//   node tools/ledger/injection-precision.test.mjs
//
// WHAT IT PINS. Every assertion is about ONE decision the join makes, isolated, because a
// single end-to-end count would go green again if two of them broke in opposite directions:
//
//   the REFUSAL       — the feature, not the fallback. A rate off six samples is the failure
//                       mode roadmap #6 has to avoid, so the refusal path is exercised FIRST
//                       and asserted to print no percentage at all.
//   the legacy split  — records without `injected`/`session` are unjoinable and must not be
//                       counted as if they were instrumented.
//   the direction     — a use BEFORE the injection is not caused by it.
//   the sidechain     — a subagent never saw the parent's injection; its use is not evidence.
//   the boundary      — `fact-a` must not be found inside `fact-abc`.
//   the CONTROL arm   — names that were not injected, measured in the same window.
//
// THE FIXTURE IS GENERATED, NOT CHECKED IN, and the recipe is stated below in full. The
// verdict path needs 100 injections across 5 sessions before the tool will speak; a hundred
// checked-in JSON lines is not a fixture a reader can verify by eye, whereas the twenty-line
// recipe below is. `fixtures/tool-usage/` is checked in because it is four small files.
//
// Exit 0 on success, 1 on the first failure, with the actual and expected value printed.

import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const TOOL = path.join(here, 'injection-precision.mjs');
const scratch = mkdtempSync(path.join(tmpdir(), 'bk-precision-'));
process.on('exit', () => rmSync(scratch, { recursive: true, force: true }));

let failures = 0;
function check(label, actual, expected) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) { console.log(`  ok    ${label}`); return; }
  console.log(`  FAIL  ${label}\n          expected ${e}\n          actual   ${a}`);
  failures += 1;
}

let caseN = 0;
/**
 * Write one case's hook log and transcript tree, and run the tool over them.
 *
 * `log` is a list of injection records; `sessions` maps a session id to the assistant
 * records that session's MAIN transcript holds, plus optional `sidechain` records. Every
 * timestamp is an offset in milliseconds from `T0`, so a case states its ordering rather
 * than its clock.
 */
const T0 = Date.parse('2026-09-06T12:00:00.000Z');
const at = (ms) => new Date(T0 + ms).toISOString();

function run({ log, sessions, cwd = '/proj', text = false }) {
  const dir = path.join(scratch, `case-${caseN++}`);
  const proj = path.join(dir, 'projects', '-proj');
  mkdirSync(proj, { recursive: true });
  writeFileSync(path.join(dir, 'hook-log.jsonl'), log.map((r) => JSON.stringify(r)).join('\n') + '\n');
  for (const [sid, spec] of Object.entries(sessions)) {
    const lines = [JSON.stringify({ type: 'user', sessionId: sid, cwd, timestamp: at(0) })];
    for (const e of spec.main ?? []) lines.push(JSON.stringify({ type: 'assistant', sessionId: sid, cwd, timestamp: at(e.t), message: { content: [e.block] } }));
    writeFileSync(path.join(proj, `${sid}.jsonl`), lines.join('\n') + '\n');
    if (spec.sidechain?.length) {
      mkdirSync(path.join(proj, sid, 'subagents'), { recursive: true });
      const sub = spec.sidechain.map((e) => JSON.stringify({ type: 'assistant', sessionId: sid, cwd, isSidechain: true, timestamp: at(e.t), message: { content: [e.block] } }));
      writeFileSync(path.join(proj, sid, 'subagents', 'agent-1.jsonl'), sub.join('\n') + '\n');
    }
  }
  const argv = [TOOL, '--log', path.join(dir, 'hook-log.jsonl'), '--projects', path.join(dir, 'projects')];
  const out = execFileSync(process.execPath, text ? argv : [...argv, '--json'], { encoding: 'utf8' });
  return text ? out : JSON.parse(out);
}

const inject = (session, t, names, scores = null) => ({
  ts: at(t), event: 'UserPromptSubmit', action: 'inject', hits: names.length, bytes: 400, source: 'project',
  session, prompt: { sha256: 'x'.repeat(64), chars: 40, bytes: 40 },
  injected: names.map((n, i) => ({ name: n, layer: 'project', type: 'project', score: scores ? scores[i] : 1 })),
  dropped: 0,
});
const assistantText = (t, s) => ({ t, block: { type: 'text', text: s } });
const recallCall = (t, q) => ({ t, block: { type: 'tool_use', name: 'mcp__bantamkit__memory_recall', input: { query: q, k: 5 } } });

console.log('injection-precision.mjs — fixture agreement\n');

// ---- 1. the refusal, which is the feature ------------------------------------------------
// Six injections in one session, one of them a real hit. A tool that printed "16.7%" here
// would be doing exactly what roadmap #6 must not: cutting a threshold to chase noise.
{
  const log = [];
  for (let i = 0; i < 6; i += 1) log.push(inject('s1', i * 1000, ['fact-a', 'fact-b']));
  const sessions = { s1: { main: [recallCall(50_000, 'fact-a body please')] } };
  const j = run({ log, sessions });
  check('thin data refuses a verdict', j.refused, true);
  check('and says how many joinable injections it has', j.joined, 6);
  check('and names both shortfalls', j.needs.length, 3);
  check('the raw counts are still reported — the RATE is what is withheld', j.counts.recallSignal, 6);

  const printed = run({ log, sessions, text: true });
  check('the refusal prints no percentage', /\d%/.test(printed), false);
  check('the refusal says REFUSED', printed.includes('REFUSED'), true);
  check('and states there is no retroactive baseline', printed.includes('NO retroactive baseline'), true);
}

// ---- 2. records that predate the instrument are not counted as instrumented ---------------
{
  const log = [];
  for (let i = 0; i < 40; i += 1) log.push({ ts: at(i), event: 'UserPromptSubmit', action: 'inject', hits: 3, bytes: 500, source: 'project' });
  // A record with names but NO session is just as unjoinable as one with neither.
  log.push({ ...inject('s1', 9000, ['fact-a']), session: undefined });
  for (let i = 0; i < 6; i += 1) log.push(inject('s1', 10_000 + i, ['fact-a']));
  const j = run({ log, sessions: { s1: { main: [] } } });
  check('legacy records counted, and kept out of the instrumented total', j.injectionRecords, { total: 47, legacyNoNamesOrSession: 41, instrumented: 6 });
}

// ---- 3. a use BEFORE the injection is not a hit -------------------------------------------
{
  const log = [inject('s1', 60_000, ['fact-a'])];
  const j = run({ log, sessions: { s1: { main: [recallCall(10_000, 'fact-a'), assistantText(20_000, 'fact-a')] } } });
  check('a recall that happened before the injection is not a hit', j.counts.recallSignal, 0);
  check('nor is an earlier quote', j.counts.eitherSignal, 0);
}

// ---- 4. sidechains are reported, never counted --------------------------------------------
{
  const log = [inject('s1', 1000, ['fact-a'])];
  const j = run({
    log,
    sessions: { s1: { main: [], sidechain: [recallCall(50_000, 'fact-a'), assistantText(51_000, 'fact-a is the one')] } },
  });
  check('a name used only by a subagent is a miss', j.counts.eitherSignal, 0);
  check('and is reported separately so the exclusion is visible', j.counts.sidechainOnly, 1);
}

// ---- 5. the name boundary ------------------------------------------------------------------
{
  const log = [inject('s1', 1000, ['fact-a'])];
  const j = run({ log, sessions: { s1: { main: [assistantText(50_000, 'I will read fact-abc now')] } } });
  check('fact-a is not found inside fact-abc', j.counts.eitherSignal, 0);
  const k = run({ log, sessions: { s1: { main: [assistantText(50_000, 'I will read fact-a now')] } } });
  check('control: the same case with the real name IS a hit', k.counts.eitherSignal, 1);
}

// ---- 6. the verdict path, and the control arm ----------------------------------------------
// THE RECIPE. Five sessions s1..s5, twenty injections each = 100, at t = i*1000 in each.
//   s1..s4 inject [fact-a, fact-b];  s5 injects [fact-c, fact-d].
//   So the universe of names seen under this cwd is {a,b,c,d}, and the control pool for a
//   record is the universe minus everything its own session ever injected: {c,d} for s1..s4,
//   {a,b} for s5, sliced to the injection's own width (2) so both arms weigh the same.
//   s1, s2: one memory_recall at t=100s naming fact-a  -> 40 recall hits.
//   s3:     one assistant message at t=100s naming fact-b -> 20 quote-only hits.
//   s4:     nothing.
//   s5:     fact-c named only in a SIDECHAIN -> 20 sidechain-only, 0 hits.
//   No main transcript ever names a control name, so both control rows must be 0 of 200.
{
  const log = [];
  const sessions = {};
  for (let s = 1; s <= 5; s += 1) {
    const sid = `s${s}`;
    const names = s === 5 ? ['fact-c', 'fact-d'] : ['fact-a', 'fact-b'];
    for (let i = 0; i < 20; i += 1) log.push(inject(sid, i * 1000, names, [3, 1]));
    sessions[sid] = { main: [] };
  }
  sessions.s1.main.push(recallCall(100_000, 'fact-a'));
  sessions.s2.main.push(recallCall(100_000, 'tell me about fact-a'));
  sessions.s3.main.push(assistantText(100_000, 'per fact-b we should not force it'));
  sessions.s5.sidechain = [assistantText(100_000, 'fact-c says so')];

  const j = run({ log, sessions });
  check('100 injections across 5 sessions clears both floors', j.refused, false);
  check('joined', j.joined, 100);
  check('sessions', j.sessions, 5);
  check('recall signal', j.counts.recallSignal, 40);
  check('either signal', j.counts.eitherSignal, 60);
  check('the control arm is measured over the same number of name-windows', j.counts.control.n, 200);
  check('and no control name was used', { r: j.counts.control.recall, q: j.counts.control.quoted }, { r: 0, q: 0 });
  check('sidechain-only uses stay uncounted', j.counts.sidechainOnly, 20);
  // The breakdown is per NAME, not per record, and it separates the two signals: `fact-a`
  // (score 3 in every record) is the one the recalls name, `fact-b` (score 1) the one the
  // assistant quotes. This expectation was written the other way round first and the tool
  // refuted it — which is the point of asserting the split rather than the total.
  check('the per-score breakdown is per name and keeps the two signals apart', j.counts.byScore, {
    1: { n: 100, recall: 0, quoted: 20 }, 3: { n: 100, recall: 40, quoted: 0 },
  });

  const printed = run({ log, sessions, text: true });
  check('a verdict prints the control rows beside the injected ones', printed.includes('CONTROL not-injected'), true);
  check('and every rate carries an interval', (printed.match(/\[\d+\.\d–\d+\.\d\]/g) || []).length, 4);
  check('and it still names no threshold', printed.includes('names no precision threshold'), true);
}

if (failures) { console.log(`\n${failures} failed`); process.exit(1); }
console.log('\nall passed');
