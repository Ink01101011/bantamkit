#!/usr/bin/env node
// Did shrinking a skill's description stop it being found?
//
//   node tools/ledger/skill-discovery-check.mjs
//
// THE QUESTION THIS ANSWERS. On 2026-09-05 the descriptions of 16 skills were cut to roughly a
// quarter of their length, with the trigger list, the "Also use when" clause and the "Do NOT
// use" clause relocated from the always-on frontmatter into the body. The catalogue went from
// 34 skills / 13,949 B to 22 / 3,396 B. Nothing about that is free: the description is the ONLY
// thing the model sees when deciding whether to invoke a skill, so a shorter one could plausibly
// stop matching tasks it used to match. That risk cannot be measured on the day it is taken —
// it needs invocations that have not happened yet.
//
// So this script exists instead of a promise to remember. Run it a few days later and it
// compares each skill's calls-per-day AFTER the cut against the same figure BEFORE, off the
// same ledger the numbers above came from. No baseline is retyped: BEFORE is recomputed from
// the transcripts every run, so the comparison cannot drift from a stale constant.
//
// READING THE RESULT. A rate that holds or rises is the trim doing what it was meant to. A rate
// that falls to zero for a skill that used to fire regularly is the thing to act on — the fix is
// to put the distinguishing trigger words back in that one description, not to revert the trim.
// Small counts move loudly: `feedback-additive-changes` fired ONCE in a month, so its rate is
// noise either way, and the script says so rather than letting a 1 -> 0 read as a regression.

import { execFileSync } from 'node:child_process';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const LEDGER = path.join(HERE, 'tool-usage.mjs');

// The day the trimmed descriptions actually reached the plugin cache — not the day they were
// committed. `claude plugin update` is what moved them; a commit alone changes nothing the host
// reads, which is the trap that made an earlier trim invisible for a day.
const CUT = '2026-09-05';

// The skills whose descriptions were cut, and what each was reduced to. `user-profile` was
// deliberately NOT cut to the same target: its triggers are Thai literals costing 3 bytes a
// character, and removing them would have removed exactly what earns it its calls.
const TRIMMED = [
  ['kkskills-essentials:plan-decompose-orchestrate', 617, 170],
  ['kkskills-essentials:proactive-task-reminders', 620, 166],
  ['kkskills-essentials:feedback-no-duplicate-docs', 620, 167],
  ['kkskills-essentials:feedback-additive-changes', 535, 163],
  ['kkskills-essentials:reference-conventional-commits', 499, 102],
  ['kkskills-personal:feedback-use-full-filenames', 513, 162],
  ['kkskills-personal:user-profile', 636, 258],
];

function usage(sinceArgs) {
  const out = execFileSync(process.execPath,
    [LEDGER, '--group', 'skill', '--json', ...sinceArgs], { encoding: 'utf8' });
  const parsed = JSON.parse(out);
  return Object.fromEntries(parsed.rows.map((r) => [r.key, r.calls]));
}

const days = (from, to) => Math.max(1, Math.round((to - from) / 86400e3));
const cut = Date.parse(`${CUT}T00:00:00Z`);
const now = Date.now();
const daysAfter = days(cut, now);

if (daysAfter < 3) {
  console.log(`Only ${daysAfter} day(s) since the cut on ${CUT}. Rates this short are noise —`);
  console.log('come back at 3 days or more. Nothing below is worth acting on yet.\n');
}

const after = usage(['--since', CUT]);
const all = usage([]);
// BEFORE is everything the ledger holds minus what landed after the cut. The corpus starts
// 2026-08-04, the first transcript on this machine.
const CORPUS_START = Date.parse('2026-08-04T00:00:00Z');
const daysBefore = days(CORPUS_START, cut);

console.log(`skill discovery after the ${CUT} description cut`);
console.log(`  before: ${daysBefore} days   after: ${daysAfter} days\n`);
console.log(`${'skill'.padEnd(50)} ${'bytes'.padStart(11)} ${'before/day'.padStart(11)} ${'after/day'.padStart(10)}  verdict`);

for (const [id, was, now_] of TRIMMED) {
  const a = after[id] ?? 0;
  const b = (all[id] ?? 0) - a;
  const rb = b / daysBefore, ra = a / daysAfter;
  // Two independent reasons a verdict is not available, and BOTH have to gate it. Printing
  // "STOPPED" one day after the cut is the same error as printing it for a skill that fired
  // once in a month: a rate needs a window on both sides before it says anything.
  const verdict = daysAfter < 3 ? 'too early to judge'
    : b < 5 ? 'too few calls before to judge'
      : ra >= rb * 0.7 ? 'holding'
        : ra === 0 ? 'STOPPED — check this description'
          : 'down — worth a look';
  console.log(`${id.padEnd(50)} ${`${was}→${now_}`.padStart(11)} ${rb.toFixed(2).padStart(11)} ${ra.toFixed(2).padStart(10)}  ${verdict}`);
}

console.log('\nThe catalogue this bought: 34 skills / 13,949 B -> 22 / 3,396 B, measured as UTF-8');
console.log('bytes of `description:` values over the enabled set. `node tools/ledger/tool-usage.mjs');
console.log('--group skill` is the raw feed; `skill_audit` prices the catalogue itself.');
