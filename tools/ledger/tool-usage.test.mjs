#!/usr/bin/env node
// Agreement test for tools/ledger/tool-usage.mjs.
//
//   node tools/ledger/tool-usage.test.mjs
//
// WHAT IT PINS, and why each case exists rather than one end-to-end number:
//
//   Every assertion here is about ONE of the three corrections the ledger makes over a naive
//   scan. A single "the fixture totals N" assertion would go green again if two of them broke
//   in opposite directions, so each is isolated and each has a NEGATIVE control — a run with
//   the correction disabled, asserted to give the WRONG answer. A test that cannot be made to
//   fail is not measuring anything.
//
//   The fixture is checked in at fixtures/tool-usage/ and its right answer is readable off the
//   four small files by eye. It is deliberately NOT this machine's live corpus: `--group skill`
//   over ~/.claude reports 148 calls today and a different number tomorrow, so asserting that
//   would pin the calendar, not the code.
//
// Exit 0 on success, 1 on the first failure, with the actual and expected value printed.

import { execFileSync } from 'node:child_process';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const LEDGER = path.join(here, 'tool-usage.mjs');
const FIX = path.join(here, 'fixtures', 'tool-usage');
const ROOT = path.join(FIX, 'projects');
const EVENTS = path.join(FIX, 'events.jsonl');

function run(extra = []) {
  const out = execFileSync(process.execPath,
    [LEDGER, '--root', ROOT, '--events', EVENTS, '--json', ...extra],
    { encoding: 'utf8' });
  const parsed = JSON.parse(out);
  parsed.byKey = Object.fromEntries(parsed.rows.map((r) => [r.key, r.calls]));
  return parsed;
}

let failures = 0;
function check(label, actual, expected) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) { console.log(`  ok    ${label}`); return; }
  console.log(`  FAIL  ${label}\n          expected ${e}\n          actual   ${a}`);
  failures += 1;
}

// ---- the fixture, stated so a reader can check the expectations without opening it --------
// sess1.jsonl                     tool_use t1 Skill(alpha), t2 Read
// sess1/subagents/agent-1.jsonl   tool_use t3 Skill(beta)
// sess2.jsonl                     tool_use t1 Skill(alpha) AGAIN (a resume), t4 Agent(Explore)
// events.jsonl                    sess1 Skill(alpha)  — transcript still on disk
//                                 gone1 Skill(gamma)  — transcript deleted
//
// So: four distinct tool_use ids on disk, plus exactly one recoverable call.

console.log('tool-usage.mjs — fixture agreement');

const skill = run(['--group', 'skill']);

// 1. Dedupe by tool_use id. t1 appears in two transcripts; alpha must be 1, not 2.
check('resumed tool_use id counted once', skill.byKey.alpha, 1);

// 2. Subagent transcripts are walked. beta lives only under <session>/subagents/.
check('subagent transcript counted', skill.byKey.beta, 1);

// 3. The events log covers ONLY sessions with no transcript. gone1 is recovered...
check('call recovered for a deleted transcript', skill.byKey.gamma, 1);
// ...and sess1's duplicate row in the same log must not inflate alpha, asserted above.
check('one call recovered, not two', skill.recovered_from_events, 1);

check('skill rows', Object.keys(skill.byKey).sort(), ['alpha', 'beta', 'gamma']);
check('total calls', skill.total, 5); // t1 t2 t3 t4 + gone1
check('transcripts walked', skill.transcripts, 3);

// 4. Agent grouping reads subagent_type off the tool's own input.
const agent = run(['--group', 'agent']);
check('agent grouping', agent.byKey, { Explore: 1 });

// 5. Grouping that no call carries yields no rows rather than an "other" bucket.
const server = run(['--group', 'server']);
check('server grouping counts every call', server.byKey.builtin, 5);

// ---- negative controls: each correction, switched off, must give the WRONG answer ---------
// Without them a broken correction and a broken assertion look identical from here.

const noEvents = run(['--group', 'skill', '--no-events']);
check('control: without the events log, gamma is unreachable', noEvents.byKey.gamma, undefined);
check('control: without the events log, the total drops', noEvents.total, 4);

if (failures) { console.log(`\n${failures} failed`); process.exit(1); }
console.log('\nall passed');
