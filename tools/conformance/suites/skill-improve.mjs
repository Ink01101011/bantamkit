/**
 * skill-improve — self-improvement, part 1 (#206 Task 10a), Python against Node: versions, the
 * counts, the 5-use judge, automatic rollback and the edited guard.
 *
 * THE PROPERTY: the two runtimes keep, count, judge and roll back a learned skill's versions
 * the same way. `skills-state.json` and the skill directories are shared on disk, so the
 * history files, the restored SKILL.md bytes, every counter and verdict, and every sentence
 * must agree; and the judge is a decision taken on integers at a fixed bar (`JUDGE_USES` = 5),
 * so the two sides must take it at the same use, on the same rates.
 *
 * HOW. One op list (the table is in `ref/skillimprove_ref.py`) runs in order twice: by the
 * reference in its own bed and by `runNode` below against `dist/` in another. Each op that
 * touches a home answers the state and the home's whole tree, the bed masked, so a SKILL.md
 * not restored, a history file not kept, an edited skill changed or a counter off by one all
 * show as a difference.
 *
 * WHAT THE FIXTURES ARE AIMED AT. The use bar one below and at it (4 never judged, 5 judged);
 * a success rate one below the base's (3/5 vs 4/5) and equal to it (4/5, and 8/10 against 4/5:
 * equal after cross-multiplying); a false-fire rate one above (3/5 vs 2/5) and equal; the zero
 * denominators (a base with no injections, a version with none); an edited skill with a worse
 * version (never judged) and a new version of it (refused); a rollback whose directory swap
 * fails (v2 left whole, no verdict); the next number after a rollback (v3, from v1); each count
 * row in, before the window, after `now`, without a session, and counted once only; the
 * gate's own-skill variant; the daily run doing all three steps off the ledgers on disk.
 *
 * THE LITERALS. A rule both runtimes lose together (`JUDGE_USES = 4`, say) leaves every
 * differential green, so the constants, the 4-and-5 verdicts and the rollback's bytes are also
 * pinned per side.
 */
import * as fs from 'node:fs';
import { mkdtempSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'skill-improve';
export const summary = 'self-improvement: versions, the counts, the 5-use judge, rollback and the edited guard';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'skillimprove_ref.py');

const NOW = '2026-10-27T12:00:00.000Z';
const LATER = '2026-10-28T12:00:00.000Z';
const MINER_FILES = ['skill-miner-cache.json', 'skill-proposals.json'];

const draft = (n, step = 'Do it', words = 'Does {n}. Use when {n} is asked.') =>
  `---\nname: ${n}\ndescription: ${words.split('{n}').join(n)}\n---\n\n` +
  `## When to use\n\nWhen asked.\n\n## Steps\n\n1. ${step} [job1/U1].\n\n## Pitfalls\n\nNone.\n\n## Example\n\nx\n`;

const SOURCES = {
  injects: [
    { names: ['sk-c'], session: 'aaaaaaaa-1', ts: '2026-10-27T12:00:01.000Z' },
    { names: ['sk-c', 'other'], session: 'bbbbbbbb-2', ts: '2026-10-27T12:00:02.000Z' },
    { names: ['sk-c'], session: 'cccccccc-3', ts: '2026-10-27T12:00:03.000Z' },
    { names: ['other'], session: 'aaaaaaaa-1', ts: '2026-10-27T12:00:04.000Z' },
    { names: ['sk-c'], session: '', ts: '2026-10-27T12:00:05.000Z' },
    { names: ['sk-c'], session: 'dddddddd-4', ts: '2026-10-26T12:00:00.000Z' },
    { names: ['sk-c'], session: 'eeeeeeee-5', ts: '2026-10-29T12:00:00.000Z' },
    { names: 'sk-c', session: 'ffffffff-6', ts: '2026-10-27T12:00:06.000Z' },
    { names: ['sk-c'], session: 'ffffffff-6', ts: 'yesterday' },
    { names: ['sk-c', 7], session: 'ffffffff-6', ts: '2026-10-27T12:00:07Z' },
  ],
  turns: [
    { id: 'saaaaaaaa#1', ok: true, ts: '2026-10-27T12:00:00.000Z' },
    { id: 'sbbbbbbbb#1', ok: true, ts: '2026-10-27T11:00:00.000Z' },
    { id: 'sbbbbbbbb#2', ok: false, ts: '2026-10-27T12:00:00.000Z' },
    { id: 'sffffffff#2', ok: true, ts: '2026-10-27T12:00:20.000Z' },
    { id: 'sffffffff#1', ok: true, ts: '2026-10-27T12:00:00.000Z' },
    { id: 'not-a-turn', ok: true, ts: '2026-10-27T12:00:00.000Z' },
  ],
  uses: [
    { fact: 'sk-c', session: 'aaaaaaaa-1', ts: '2026-10-27T12:00:10.000Z' },
    { fact: 'sk-c', session: 'bbbbbbbb-2', ts: '2026-10-27T12:00:10.000Z' },
    { fact: 'sk-c', session: 'zzzzzzzz-9', ts: '2026-10-27T12:00:10.000Z' },
    { fact: 'sk-c', session: 'ffffffff-6', ts: '2026-10-27T12:00:15.000Z' },
    { fact: 'other', session: 'cccccccc-3', ts: '2026-10-27T12:00:10.000Z' },
    { fact: 'sk-c', session: 'aaaaaaaa-1', ts: '2026-10-26T00:00:00.000Z' },
    { fact: 'sk-c', session: null, ts: '2026-10-27T12:00:10.000Z' },
    { fact: 'sk-c', session: 'aaaaaaaa-1', ts: '2026-10-27T12:00:10Z', extra: 1 },
  ],
};

const RATES = [
  ['success 3/5 against 4/5 falls: rolled back', { successes: 4, uses: 5 }, { successes: 3, uses: 5 }],
  ['success 4/5 against 4/5 is equal: kept', { successes: 4, uses: 5 }, { successes: 4, uses: 5 }],
  ['success 8/10 against 4/5 is equal on integers: kept', { successes: 4, uses: 5 }, { successes: 8, uses: 10 }],
  ['success 7/9 against 4/5 falls: rolled back', { successes: 4, uses: 5 }, { successes: 7, uses: 9 }],
  ['false fires 3/5 against 2/5 rise: rolled back', { false_fires: 2, injects: 5, uses: 5 }, { false_fires: 3, injects: 5, uses: 5 }],
  ['false fires 2/5 against 2/5 are equal: kept', { false_fires: 2, injects: 5, uses: 5 }, { false_fires: 2, injects: 5, uses: 5 }],
  ['false fires 1/1 against a base with no injections rise: rolled back', { injects: 0, uses: 5 }, { false_fires: 1, injects: 1, uses: 5 }],
  ['no injections against 1/1: a rate of 0, kept', { false_fires: 1, injects: 1, uses: 5 }, { injects: 0, uses: 5 }],
  ['a base with no uses: kept', { uses: 0 }, { successes: 0, uses: 5 }],
];

function opList() {
  const ops = [];
  const label = [];
  const add = (l, op) => {
    label.push(l);
    ops.push(op);
  };
  add('constants', { op: 'constants' });

  // h1: new versions, the refusals, rollback, the next number
  const h = 'h1';
  add('h1: install sk-a', { op: 'install', home: h, name: 'sk-a', text: draft('sk-a'), now: NOW });
  add('new_version: a bad kind', { op: 'new_version', home: h, name: 'sk-a', text: draft('sk-a', 'Do it better'), now: NOW, kind: 'manual' });
  add('new_version: not installed', { op: 'new_version', home: h, name: 'nope', text: draft('nope'), now: NOW, kind: 'auto' });
  add('new_version: named another skill', { op: 'new_version', home: h, name: 'sk-a', text: draft('sk-b'), now: NOW, kind: 'auto' });
  add('new_version: not a valid skill', { op: 'new_version', home: h, name: 'sk-a', text: draft('sk-a').replace('## Steps', '## Stops'), now: NOW, kind: 'auto' });
  add('new_version: a bad now', { op: 'new_version', home: h, name: 'sk-a', text: draft('sk-a'), now: 'today', kind: 'auto' });
  add('new_version: the swap fails, v1 stays', { op: 'new_version', home: h, name: 'sk-a', text: draft('sk-a', 'Do it better'), now: NOW, kind: 'auto', fail_at: 'rename3' });
  add('new_version: v2, v1 in history', { op: 'new_version', home: h, name: 'sk-a', text: draft('sk-a', 'Do it better'), now: NOW, kind: 'auto' });
  add('h1: v1 succeeded 4 of 5', { op: 'set_stats', home: h, name: 'sk-a', version: '1', stats: { successes: 4, uses: 5 } });
  add('h1: v2 succeeded 0 of 4', { op: 'set_stats', home: h, name: 'sk-a', version: '2', stats: { successes: 0, uses: 4 } });
  add('judge_step: 4 uses are never judged', { op: 'judge_step', home: h, now: NOW });
  add('h1: v2 reaches 5 uses', { op: 'set_stats', home: h, name: 'sk-a', version: '2', stats: { uses: 5 } });
  add('judge_step: the rollback fails, v2 stays unjudged', { op: 'judge_step', home: h, now: NOW, fail_at: 'rename3' });
  add('judge_step: 5 uses are judged, rolled back to v1', { op: 'judge_step', home: h, now: LATER });
  add('edited: a rolled-back skill is not edited', { op: 'edited', home: h, name: 'sk-a' });
  add('judge_step: judged once', { op: 'judge_step', home: h, now: LATER });
  add('new_version: the next number is v3, from v1', { op: 'new_version', home: h, name: 'sk-a', text: draft('sk-a', 'Do it a third way'), now: LATER, kind: 'approved' });

  // h2: the rates, one home per fixture
  RATES.forEach(([l, one, two], i) => {
    const r = `r${i}`;
    add(`${r}: install`, { op: 'install', home: r, name: 'sk-r', text: draft('sk-r'), now: NOW });
    add(`${r}: v2`, { op: 'new_version', home: r, name: 'sk-r', text: draft('sk-r', 'Do it better'), now: NOW, kind: 'auto' });
    add(`${r}: v1 stats`, { op: 'set_stats', home: r, name: 'sk-r', version: '1', stats: one });
    add(`${r}: v2 stats`, { op: 'set_stats', home: r, name: 'sk-r', version: '2', stats: two });
    add(`judge_step: ${l}`, { op: 'judge_step', home: r, now: NOW });
  });

  // h3: the edited guard
  const e = 'h3';
  add('h3: install sk-e', { op: 'install', home: e, name: 'sk-e', text: draft('sk-e'), now: NOW });
  add('h3: v2', { op: 'new_version', home: e, name: 'sk-e', text: draft('sk-e', 'Do it better'), now: NOW, kind: 'auto' });
  add('h3: v1 4 of 5', { op: 'set_stats', home: e, name: 'sk-e', version: '1', stats: { successes: 4, uses: 5 } });
  add('h3: v2 0 of 9', { op: 'set_stats', home: e, name: 'sk-e', version: '2', stats: { successes: 0, uses: 9 } });
  add('h3: the user edits sk-e', { op: 'append', home: e, rel: '.bantamkit/skills/sk-e/SKILL.md', text: 'my own line\n' });
  add('edited: sk-e is edited', { op: 'edited', home: e, name: 'sk-e' });
  add('judge_step: an edited skill is never judged', { op: 'judge_step', home: e, now: NOW });
  add('new_version: an edited skill is never versioned', { op: 'new_version', home: e, name: 'sk-e', text: draft('sk-e', 'Do it a third way'), now: NOW, kind: 'auto' });

  // h4: the counts
  const c = 'h4';
  add('h4: install sk-c', { op: 'install', home: c, name: 'sk-c', text: draft('sk-c'), now: NOW });
  add('stats_step: each row in, out, or counted once', { op: 'stats_step', home: c, sources: SOURCES, now: LATER });
  add('stats_step: the same rows again add nothing', { op: 'stats_step', home: c, sources: SOURCES, now: LATER });
  add('stats_step: a bad now', { op: 'stats_step', home: c, sources: SOURCES, now: 'today' });
  add('stats_step: sources of the wrong shape', { op: 'stats_step', home: c, sources: { injects: 'x', turns: null, uses: [1, 'a', null] }, now: LATER });
  add('h4: v2 of sk-c', { op: 'new_version', home: c, name: 'sk-c', text: draft('sk-c', 'Do it better'), now: LATER, kind: 'auto' });
  add('stats_step: after the new version, into v2 only', {
    op: 'stats_step',
    home: c,
    sources: { injects: [], turns: [], uses: [{ fact: 'sk-c', session: 's-1', ts: '2026-10-28T12:00:00.000Z' }, { fact: 'sk-c', session: 's-1', ts: '2026-10-28T12:00:00.001Z' }] },
    now: '2026-10-29T00:00:00.000Z',
  });

  // h5: the gate's own-skill variant
  const g = 'h5';
  const words = 'Does {n}. Use when asked to "ship the thing".';
  add('h5: install sk-g', { op: 'install', home: g, name: 'sk-g', text: draft('sk-g', 'Do it', words), now: NOW });
  add('gate: a new version of sk-g without own collides and shares', { op: 'gate', home: g, text: draft('sk-g', 'Do it better', words) });
  add('gate: with own it passes', { op: 'gate', home: g, text: draft('sk-g', 'Do it better', words), own: 'sk-g' });
  add('h5: install sk-h with the same phrase', { op: 'install', home: g, name: 'sk-h', text: draft('sk-h', 'Do it', words), now: NOW });
  add('gate: with own, another skill still shares', { op: 'gate', home: g, text: draft('sk-g', 'Do it better', words), own: 'sk-g' });
  add('gate: with own, renaming onto another skill collides', { op: 'gate', home: g, text: draft('sk-h', 'Do it better'), own: 'sk-g' });

  // h6: the daily run (AMENDED job73 C15: automatic promotion follows BANTAMKIT_SKILL_AUTO, so
  // the daily op carries `env`; h6 opts in, h7 is the same home with the switch off, then on)
  const dailyBed = (d) => {
    add(`${d}: ~/.claude exists`, { op: 'mkdir', home: d, rel: '.claude' });
    add(`${d}: install sk-d`, { op: 'install', home: d, name: 'sk-d', text: draft('sk-d'), now: NOW });
    add(`${d}: v1 4 of 5`, { op: 'set_stats', home: d, name: 'sk-d', version: '1', stats: { successes: 4, uses: 5 } });
    add(`${d}: v2`, { op: 'new_version', home: d, name: 'sk-d', text: draft('sk-d', 'Do it better'), now: NOW, kind: 'auto' });
    add(`${d}: v2 0 of 4`, { op: 'set_stats', home: d, name: 'sk-d', version: '2', stats: { successes: 0, uses: 4 } });
    const usage = Array(3).fill(JSON.stringify({ fact: 'sk-d', kind: 'recall_hit', ts: '2026-10-27T13:00:00Z' })).join('\n') + '\n';
    add(`${d}: three uses in the usage ledger`, { op: 'write', home: d, rel: '.bantamkit/usage/store.jsonl', text: usage });
    const touch = [
      { ts: '2026-10-27T13:00:00Z', session: 's-1', seq: 1, op: 'use', fact: 'sk-d', kind: 'recall_hit' },
      { ts: '2026-10-27T13:00:00Z', session: 's-1', seq: 2, op: 'use', fact: 'sk-d', kind: 'save' },
      { ts: '2026-10-27T11:00:00Z', session: 's-1', seq: 3, op: 'use', fact: 'sk-d', kind: 'recall_hit' },
    ];
    add(`${d}: the touch log`, { op: 'write', home: d, rel: '.bantamkit/touch/repo.jsonl', text: touch.map((r) => `${JSON.stringify(r)}\n`).join('') });
    const hooks = [
      { ts: '2026-10-27T13:00:00.000Z', event: 'UserPromptSubmit', action: 'inject', session: 's-2', injected: [{ name: 'sk-d' }] },
      { ts: '2026-10-27T13:00:00.000Z', event: 'UserPromptSubmit', action: 'skip', session: 's-2', injected: [{ name: 'sk-d' }] },
      { ts: '2026-10-27T13:00:01.000Z', event: 'UserPromptSubmit', action: 'inject', session: 's-1', injected: [{ name: 'sk-d' }, { nam: 'x' }] },
    ];
    add(`${d}: the hook log`, { op: 'write', home: d, rel: '.bantamkit/hooks/hook-log.jsonl', text: hooks.map((r) => `${JSON.stringify(r)}\n`).join('') });
  };
  dailyBed('h6');
  add('daily: counts, promotes, judges', { op: 'daily', home: 'h6', now: LATER, env: 'on' });
  add('daily: the next day adds nothing', { op: 'daily', home: 'h6', now: '2026-10-29T12:00:00.000Z', env: 'on' });
  dailyBed('h7');
  add('daily: BANTAMKIT_SKILL_AUTO=off counts and judges, promotes nothing', { op: 'daily', home: 'h7', now: LATER, env: 'off' });
  add('daily: the next day with the switch on promotes', { op: 'daily', home: 'h7', now: '2026-10-29T12:00:00.000Z', env: 'on' });
  part2(add);
  return { ops, label };
}

// ------------------------------------------------------------- part 2 (#206 Task 10b)

const AFTER = '2026-10-27T13:00:00.000Z';
const DAY3 = '2026-10-29T12:00:00.000Z';
const NARROW = (n) => `Does ${n} for parsers only. Use when a parser of ${n} is asked.`;
const narrowed = (n) => draft(n).replace(`description: Does ${n}. Use when ${n} is asked.`, `description: ${NARROW(n)}`);
const rec = (n, evidence = null, keywords = null, steps = null) => ({
  evidence: evidence ?? [{ id: 'job1/U1', ok: true, ts: '2026-01-01T00:00:00Z' }],
  id: `c-${n}`,
  keywords: keywords ?? ['k1'],
  level: 'user',
  members: 3,
  source: 'shiftwork',
  status: 'pending',
  steps: steps ?? [],
  successes: 3,
  top: null,
});
const missedDoc = (n, k) => ({
  clusters: [
    rec(
      n,
      Array.from({ length: k }, (_, j) => ({ id: `s${j + 1}${j + 1}${j + 1}${j + 1}aaaa#1`, ok: true, prompt: 'fix the lexer tokens', ts: AFTER })),
      ['k1', 'lexer', 'tokens', 'absent'],
    ),
  ],
});
const corrected = (n, text = 'no, use the other parser\nand more') => ({
  turns: [{ failure: `corrected in the next turn: ${text}`, id: 's1111aaaa#1', ok: false, tools: ['Read', 'Edit'], ts: AFTER }],
  uses: [{ fact: n, session: '1111aaaa-x', ts: '2026-10-27T13:00:01.000Z' }],
});
const together = (k, extra = 0) => ({
  injects: [
    ...Array.from({ length: k }, (_, i) => ({ names: ['sk-ma', 'sk-mb'], session: `s-${i}`, ts: AFTER })),
    ...Array.from({ length: extra }, (_, i) => ({ names: ['sk-ma'], session: `x-${i}`, ts: AFTER })),
  ],
});

function part2(add) {
  add('constants2', { op: 'constants2' });
  add('improve_prompt: narrow and widen, the bytes', {
    op: 'improve_prompt',
    kinds: ['narrow', 'widen'],
    text: draft('sk-p'),
    doc: rec('sk-p'),
    ids: ['job1/U1', 's9#1'],
    counts: { false_fires: 3, injects: 5, misses: 2 },
  });
  add('improve_prompt: no record, widen only', { op: 'improve_prompt', kinds: ['widen'], text: draft('sk-p'), doc: null, ids: ['job1/U1'], counts: {} });
  add('diff: a pitfall line', { op: 'diff', old: draft('sk-p'), new: draft('sk-p').replace('None.', '- [x#1] y') });
  add('diff: nothing changed', { op: 'diff', old: draft('sk-p'), new: draft('sk-p') });
  add('pitfall: a correction, its first line', { op: 'pitfall', id: 's1#1', failure: 'corrected in the next turn:  no, the other one \nsecond' });
  add('pitfall: 300 code points cut to 200', { op: 'pitfall', id: 's1#1', failure: `interrupted ${'ก'.repeat(300)}` });
  add('pitfall: a lone surrogate', { op: 'pitfall', id: 's1#1', failure: 'bad \ud800 text' });

  // n: false fires
  const n = 'n1';
  add('n1: install sk-n', { op: 'install', home: n, name: 'sk-n', text: draft('sk-n'), now: NOW });
  add('n1: 4 injects, 4 false', { op: 'set_stats', home: n, name: 'sk-n', version: '1', stats: { injects: 4, false_fires: 4 } });
  add('improve_step: 4 injects never tune', { op: 'improve_step', env: 'on', home: n, sources: {}, now: LATER, drafter: { answer: narrowed('sk-n') } });
  add('n1: 5 injects, 3 false', { op: 'set_stats', home: n, name: 'sk-n', version: '1', stats: { injects: 5, false_fires: 3 } });
  add('improve_step: 5 injects, 3 false: narrowed as v2', { op: 'improve_step', env: 'on', home: n, sources: {}, now: DAY3, drafter: { answer: narrowed('sk-n') } });
  add('n2: install sk-n', { op: 'install', home: 'n2', name: 'sk-n', text: draft('sk-n'), now: NOW });
  add('n2: 5 injects, 2 false', { op: 'set_stats', home: 'n2', name: 'sk-n', version: '1', stats: { injects: 5, false_fires: 2 } });
  add('improve_step: 5 injects, 2 false never tune', { op: 'improve_step', env: 'on', home: 'n2', sources: {}, now: LATER, drafter: { answer: narrowed('sk-n') } });
  add('n3: install sk-n', { op: 'install', home: 'n3', name: 'sk-n', text: draft('sk-n'), now: NOW });
  add('n3: 5 injects, 3 false', { op: 'set_stats', home: 'n3', name: 'sk-n', version: '1', stats: { injects: 5, false_fires: 3 } });
  add('improve_step: a narrow that fails the gate', { op: 'improve_step', env: 'on', home: 'n3', sources: {}, now: LATER, drafter: { answer: draft('sk-n').replace('Does sk-n.', 'x'.repeat(1100)) } });
  add('n4: install sk-n', { op: 'install', home: 'n4', name: 'sk-n', text: draft('sk-n'), now: NOW });
  add('n4: 5 injects, 3 false', { op: 'set_stats', home: 'n4', name: 'sk-n', version: '1', stats: { injects: 5, false_fires: 3 } });
  add('improve_step: an unreachable drafter: the tune waits', { op: 'improve_step', env: 'on', home: 'n4', sources: {}, now: LATER, drafter: 'unreachable' });

  // t: no drafter, the command drafts
  const t = 't1';
  add('t1: install sk-t', { op: 'install', home: t, name: 'sk-t', text: draft('sk-t'), now: NOW });
  add('t1: 5 injects, 3 false', { op: 'set_stats', home: t, name: 'sk-t', version: '1', stats: { injects: 5, false_fires: 3 } });
  add('improve_step: no drafter, the narrow waits', { op: 'improve_step', env: 'on', home: t, sources: {}, now: LATER });
  add('render: list shows the waiting tune', { op: 'render', home: t, action: 'list', target: null, now: LATER });
  add('render: approve the tune: the host agent hand-off', { op: 'render', home: t, action: 'approve', target: 'sk-t', now: LATER });
  add('t1: the agent writes the file', { op: 'write', home: t, rel: '.bantamkit/skill-handoff/tune-sk-t/SKILL.md', text: narrowed('sk-t') });
  add('render: approve the tune again: applied', { op: 'render', home: t, action: 'approve', target: 'sk-t', now: LATER });
  add('t2: install sk-t', { op: 'install', home: 't2', name: 'sk-t', text: draft('sk-t'), now: NOW });
  add('t2: 5 injects, 3 false', { op: 'set_stats', home: 't2', name: 'sk-t', version: '1', stats: { injects: 5, false_fires: 3 } });
  add('t2: the narrow waits', { op: 'improve_step', env: 'on', home: 't2', sources: {}, now: LATER });
  add('render: approve the tune through sampling', { op: 'render', home: 't2', action: 'approve', target: 'sk-t', now: LATER, answer: narrowed('sk-t') });
  add('t3: install sk-t', { op: 'install', home: 't3', name: 'sk-t', text: draft('sk-t'), now: NOW });
  add('t3: 5 injects, 3 false', { op: 'set_stats', home: 't3', name: 'sk-t', version: '1', stats: { injects: 5, false_fires: 3 } });
  add('t3: the narrow waits', { op: 'improve_step', env: 'on', home: 't3', sources: {}, now: LATER });
  add('render: reject drops the tune', { op: 'render', home: 't3', action: 'reject', target: 'sk-t', now: LATER });

  // m: misses
  add('m1: install sk-m', { op: 'install', home: 'm1', name: 'sk-m', text: draft('sk-m'), now: NOW });
  add('improve_step: 1 miss never widens', { op: 'improve_step', env: 'on', home: 'm1', sources: {}, doc: missedDoc('sk-m', 1), now: LATER });
  add('improve_step: the same miss is counted once', { op: 'improve_step', env: 'on', home: 'm1', sources: {}, doc: missedDoc('sk-m', 1), now: DAY3 });
  add('m2: install sk-m', { op: 'install', home: 'm2', name: 'sk-m', text: draft('sk-m'), now: NOW });
  add('improve_step: 2 misses widen the keywords', { op: 'improve_step', env: 'on', home: 'm2', sources: {}, doc: missedDoc('sk-m', 2), now: LATER });
  add('m3: install sk-m', { op: 'install', home: 'm3', name: 'sk-m', text: draft('sk-m'), now: NOW });
  add('improve_step: a session that injected or used it is no miss', {
    op: 'improve_step',
    env: 'on',
    home: 'm3',
    sources: { injects: [{ names: ['sk-m'], session: '1111aaaa-x', ts: AFTER }], uses: [{ fact: 'sk-m', session: '2222aaaa-y', ts: AFTER }] },
    doc: missedDoc('sk-m', 2),
    now: LATER,
  });

  // c: a correction after a use
  add('c1: install sk-c', { op: 'install', home: 'c1', name: 'sk-c', text: draft('sk-c'), now: NOW });
  add('improve_step: a correction: a pitfall applied, a steps change proposed', { op: 'improve_step', env: 'on', home: 'c1', sources: corrected('sk-c'), now: LATER });
  add('improve_step: the same correction is never added twice', { op: 'improve_step', env: 'on', home: 'c1', sources: corrected('sk-c'), now: DAY3 });
  add('render: list shows the steps change and its diff', { op: 'render', home: 'c1', action: 'list', target: null, now: DAY3 });
  add('render: approve the steps change', { op: 'render', home: 'c1', action: 'approve', target: 'sk-c', now: DAY3 });
  add('c2: install sk-c', { op: 'install', home: 'c2', name: 'sk-c', text: draft('sk-c'), now: NOW });
  add('improve_step: a 300-code-point correction', { op: 'improve_step', env: 'on', home: 'c2', sources: corrected('sk-c', 'ก'.repeat(300)), now: LATER });
  add('c3: install sk-c', { op: 'install', home: 'c3', name: 'sk-c', text: draft('sk-c'), now: NOW });
  add('improve_step: c3 proposes', { op: 'improve_step', env: 'on', home: 'c3', sources: corrected('sk-c'), now: LATER });
  add('c3: the file changes after the proposal', { op: 'append', home: 'c3', rel: '.bantamkit/skills/sk-c/SKILL.md', text: 'later\n' });
  add('render: approve a proposal whose file changed', { op: 'render', home: 'c3', action: 'approve', target: 'sk-c', now: LATER });

  // s: different steps
  const steps = { clusters: [rec('sk-s', null, null, ['Read>Edit', 'Edit>Bash'])] };
  const used = (tools) => ({ turns: [{ id: 's1111aaaa#1', ok: true, tools, ts: AFTER }], uses: [{ fact: 'sk-s', session: '1111aaaa-x', ts: AFTER }] });
  add('s1: install sk-s', { op: 'install', home: 's1', name: 'sk-s', text: draft('sk-s'), now: NOW });
  add('improve_step: different steps: a proposal only', { op: 'improve_step', env: 'on', home: 's1', sources: used(['Grep', 'Write', 'Grep']), doc: steps, now: LATER });
  add('s2: install sk-s', { op: 'install', home: 's2', name: 'sk-s', text: draft('sk-s'), now: NOW });
  add('improve_step: shared steps: nothing', { op: 'improve_step', env: 'on', home: 's2', sources: used(['Read', 'Edit', 'Bash']), doc: steps, now: LATER });

  // g: two skills that fire together
  for (const [h, k, extra, l] of [
    ['g1', 5, 0, 'five sessions: a merge proposed'],
    ['g2', 4, 0, 'four sessions: nothing'],
    ['g3', 5, 6, 'under half of one: nothing'],
  ]) {
    add(`${h}: install sk-ma`, { op: 'install', home: h, name: 'sk-ma', text: draft('sk-ma'), now: NOW });
    add(`${h}: install sk-mb`, { op: 'install', home: h, name: 'sk-mb', text: draft('sk-mb'), now: NOW });
    add(`improve_step: ${l}`, { op: 'improve_step', env: 'on', home: h, sources: together(k, extra), now: LATER });
  }
  add('render: approve the merge: never done for you', { op: 'render', home: 'g1', action: 'approve', target: 'sk-ma', now: LATER });
  add('improve_step: a merge is not proposed twice', { op: 'improve_step', env: 'on', home: 'g1', sources: together(5), now: DAY3 });

  // e: the edited guard
  add('e1: install sk-x', { op: 'install', home: 'e1', name: 'sk-x', text: draft('sk-x'), now: NOW });
  add('e1: the user edits sk-x', { op: 'append', home: 'e1', rel: '.bantamkit/skills/sk-x/SKILL.md', text: 'my own line\n' });
  add('e1: 5 injects, 3 false', { op: 'set_stats', home: 'e1', name: 'sk-x', version: '1', stats: { injects: 5, false_fires: 3 } });
  add('improve_step: on an edited skill everything is a proposal', {
    op: 'improve_step',
    env: 'on',
    home: 'e1',
    sources: corrected('sk-x'),
    now: LATER,
    drafter: { answer: narrowed('sk-x') },
  });
  add('render: approve the change to the edited skill', { op: 'render', home: 'e1', action: 'approve', target: 'sk-x', now: LATER });
  add('edited: still edited after the approval', { op: 'edited', home: 'e1', name: 'sk-x' });
  add('e1: v2 9 injects, 9 false', { op: 'set_stats', home: 'e1', name: 'sk-x', version: '2', stats: { injects: 9, false_fires: 9 } });
  add('improve_step: an approved edited skill still only gets proposals', { op: 'improve_step', env: 'on', home: 'e1', sources: {}, now: DAY3, drafter: { answer: narrowed('sk-x') } });
  add('new_version: an automatic version of the edited skill is refused', { op: 'new_version', home: 'e1', name: 'sk-x', text: draft('sk-x'), now: DAY3, kind: 'auto' });

  // x (job73 C13b): BANTAMKIT_SKILL_AUTO is OFF by default in 0.37.0 and gates the automatic
  // edits too: no version is made, the same signals become the skill's one proposal (a steps
  // line due in the same run rides in it), a tune with no drafter still waits
  add('x1: install sk-c', { op: 'install', home: 'x1', name: 'sk-c', text: draft('sk-c'), now: NOW });
  add('improve_step: auto unset: the correction is proposed, pitfall and step together', { op: 'improve_step', home: 'x1', sources: corrected('sk-c'), now: LATER });
  add('render: auto unset: list shows the one change', { op: 'render', home: 'x1', action: 'list', target: null, now: LATER });
  add('render: auto unset: approve applies it as v2', { op: 'render', home: 'x1', action: 'approve', target: 'sk-c', now: LATER });
  add('x2: install sk-n', { op: 'install', home: 'x2', name: 'sk-n', text: draft('sk-n'), now: NOW });
  add('x2: 5 injects, 3 false', { op: 'set_stats', home: 'x2', name: 'sk-n', version: '1', stats: { injects: 5, false_fires: 3 } });
  add('improve_step: auto off: a drafted narrow is proposed', { op: 'improve_step', env: 'off', home: 'x2', sources: {}, now: LATER, drafter: { answer: narrowed('sk-n') } });
  add('x3: install sk-m', { op: 'install', home: 'x3', name: 'sk-m', text: draft('sk-m'), now: NOW });
  add('improve_step: auto "banana": the widened keywords are proposed, the tune waits', { op: 'improve_step', env: 'banana', home: 'x3', sources: {}, doc: missedDoc('sk-m', 2), now: LATER });
  add('x4: install sk-t', { op: 'install', home: 'x4', name: 'sk-t', text: draft('sk-t'), now: NOW });
  add('x4: 5 injects, 3 false', { op: 'set_stats', home: 'x4', name: 'sk-t', version: '1', stats: { injects: 5, false_fires: 3 } });
  add('improve_step: auto " OFF ", no drafter: the narrow waits', { op: 'improve_step', env: ' OFF ', home: 'x4', sources: {}, now: LATER });
  add('x5: install sk-s', { op: 'install', home: 'x5', name: 'sk-s', text: draft('sk-s'), now: NOW });
  add('improve_step: auto "": different steps: a steps proposal as before', { op: 'improve_step', env: '', home: 'x5', sources: used(['Grep', 'Write', 'Grep']), doc: steps, now: LATER });
  for (const [h, env] of [['x6', ' Yes '], ['x7', '1'], ['x8', 'TRUE']]) {
    add(`${h}: install sk-c`, { op: 'install', home: h, name: 'sk-c', text: draft('sk-c'), now: NOW });
    add(`improve_step: auto ${JSON.stringify(env)}: the pitfall applied as v2`, { op: 'improve_step', env, home: h, sources: corrected('sk-c'), now: LATER });
  }
}

// ------------------------------------------------------------------------- Node side

function tree(root, bed, skip = []) {
  const out = {};
  if (!fs.existsSync(root)) return out;
  const walk = (dir) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name);
      const r = relative(root, p).split(sep).join('/');
      if (skip.includes(r)) continue;
      if (e.isSymbolicLink()) {
        out[r] = `-> ${fs.readlinkSync(p).split(bed).join('<bed>')}`;
      } else if (e.isDirectory()) {
        out[`${r}/`] = null;
        walk(p);
      } else if (e.isFile()) {
        let text;
        try {
          text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(fs.readFileSync(p));
        } catch {
          text = '<not utf-8>';
        }
        out[r] = text.split(bed).join('<bed>');
      }
    }
  };
  walk(root);
  return Object.fromEntries(Object.entries(out).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
}

const sub = (v, bed) => {
  if (typeof v === 'string') return v.split('<bed>').join(bed);
  if (Array.isArray(v)) return v.map((x) => sub(x, bed));
  if (v !== null && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, sub(x, bed)]));
  return v;
};
const mask = (v, bed) => {
  if (typeof v === 'string') {
    const escaped = JSON.stringify(bed).slice(1, -1);
    return v.split(escaped).join('<bed>').split(bed).join('<bed>');
  }
  if (Array.isArray(v)) return v.map((x) => mask(x, bed));
  if (v !== null && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, mask(x, bed)]));
  return v;
};

const cluster = (n) => ({
  evidence: [{ id: 'job1/U1', ok: true, ts: '2026-01-01T00:00:00Z' }],
  id: `c-${n}`,
  keywords: ['k1'],
  level: 'user',
  members: 3,
  source: 'shiftwork',
  status: 'pending',
  successes: 3,
  top: null,
});

async function runNode(ctx, bed, ops) {
  const dist = (m) => pathToFileURL(join(ctx.runtimeTs, 'dist', m)).href;
  const si = await import(dist('skillinstall.js'));
  const sf = await import(dist('skillfile.js'));
  const sd = await import(dist('skilldraft.js'));
  const sm = await import(dist('skillmine.js'));
  const results = [];
  for (const raw of ops) {
    const op = sub(raw, bed);
    const home = op.home !== undefined ? join(bed, op.home) : bed;
    if (op.op === 'constants') {
      results.push([si.JUDGE_USES, si.VERDICT_KEPT, si.VERDICT_ROLLED_BACK, si.HISTORY_DIR, [...si.VERSION_KINDS]]);
      continue;
    }
    if (op.op === 'install') {
      si.install(cluster(op.name), op.text, null, home, op.now, false);
      results.push({ tree: mask(tree(home, bed), bed) });
      continue;
    }
    if (op.op === 'constants2') {
      results.push([si.TUNE_MIN_INJECTS, [...si.FALSE_FIRE_TUNE], si.MISS_TUNE, si.PITFALL_CHARS, si.TOGETHER_SESSIONS, [...si.TOGETHER_SHARE], [...si.ITEM_KINDS], [...sd.TUNE_KINDS]]);
      continue;
    }
    if (op.op === 'improve_prompt') {
      results.push(sd.improvePrompt(op.kinds, op.text, sd.improveBundle(op.doc, 'c-x', op.ids), op.counts));
      continue;
    }
    if (op.op === 'diff') {
      results.push(si.skillDiff(op.old, op.new));
      continue;
    }
    if (op.op === 'pitfall') {
      results.push(si.pitfallLine(op.id, op.failure));
      continue;
    }
    if (op.op === 'render') {
      const sp = await import(dist('skillpropose.js'));
      const answer = op.answer;
      const sampler = answer !== undefined ? async () => answer : null;
      const said = await sp.render(op.action, op.target, null, home, null, op.now, sampler);
      results.push(mask({ said, state: sf.readState(home), tree: tree(home, bed) }, bed));
      continue;
    }
    if (op.op === 'mkdir') {
      fs.mkdirSync(join(home, op.rel), { recursive: true });
      results.push({});
      continue;
    }
    if (op.op === 'append') {
      fs.appendFileSync(join(home, op.rel), op.text);
      results.push({});
      continue;
    }
    if (op.op === 'write') {
      fs.mkdirSync(dirname(join(home, op.rel)), { recursive: true });
      fs.writeFileSync(join(home, op.rel), op.text);
      results.push({});
      continue;
    }
    if (op.op === 'set_stats') {
      sf.updateState(home, (state) => {
        const versions = state.skills[op.name].versions;
        versions[op.version] = { ...(versions[op.version] ?? {}), ...op.stats };
      });
      results.push({});
      continue;
    }
    if (op.op === 'edited') {
      results.push(si.editedByHand(sf.readState(home).skills[op.name]));
      continue;
    }
    if (op.op === 'gate') {
      const own = op.own ? join(sf.skillsRoot(home), op.own) : null;
      results.push(mask(sd.gate(op.text, sd.bundle(cluster('x')), home, null, own).reasons, bed));
      continue;
    }
    if (op.op === 'daily') {
      const saved = { BANTAMKIT_SKILL_AUDIT: process.env.BANTAMKIT_SKILL_AUDIT, BANTAMKIT_SKILL_AUTO: process.env.BANTAMKIT_SKILL_AUTO };
      process.env.BANTAMKIT_SKILL_AUDIT = 'on';
      process.env.BANTAMKIT_SKILL_AUTO = op.env ?? 'off';
      try {
        await sm.daily(home, null, op.now);
      } finally {
        for (const [k, v] of Object.entries(saved)) {
          if (v === undefined) delete process.env[k];
          else process.env[k] = v;
        }
      }
      const skip = MINER_FILES.map((n) => `.bantamkit/${n}`);
      results.push(mask({ state: sf.readState(home), tree: tree(home, bed, skip) }, bed));
      continue;
    }
    const savedRename = sf.seams.rename;
    if (op.fail_at === 'rename3') {
      let calls = 0;
      sf.seams.rename = (s, d) => {
        calls += 1;
        if (calls === 3) {
          const e = new Error('injected');
          e.code = 'EIO';
          throw e;
        }
        savedRename(s, d);
      };
    }
    let out = {};
    try {
      if (op.op === 'new_version') {
        out.said = si.newVersion(op.name, op.text, home, op.now, op.kind);
      } else if (op.op === 'stats_step') {
        const state = sf.readState(home);
        si.statsStep(state, op.sources, home, op.now);
        out.returned_state = state;
      } else if (op.op === 'improve_step') {
        const state = sf.readState(home);
        const d = op.drafter;
        const chain =
          d === undefined
            ? []
            : [
                {
                  label: 'endpoint stub',
                  ask: async () => {
                    if (d === 'unreachable') throw new Error('unreachable');
                    return d.answer;
                  },
                },
              ];
        const savedAuto = process.env[si.AUTO_ENV];
        if (op.env === undefined || op.env === null) delete process.env[si.AUTO_ENV];
        else process.env[si.AUTO_ENV] = op.env;
        try {
          out.events = await si.improveStep(state, op.sources, op.doc ?? null, home, null, op.now, chain);
        } finally {
          if (savedAuto === undefined) delete process.env[si.AUTO_ENV];
          else process.env[si.AUTO_ENV] = savedAuto;
        }
        out.returned_state = state;
      } else if (op.op === 'judge_step') {
        const state = sf.readState(home);
        out.events = si.judgeStep(state, home, op.now);
        out.returned_state = state;
      } else {
        throw new Error(`skill-improve: unknown op ${op.op}`);
      }
    } catch (e) {
      if (e instanceof sf.SkillFileError) out = { error: e.message };
      else if (e instanceof Error && typeof e.code === 'string') out = { error: 'OSError' };
      else throw e;
    } finally {
      sf.seams.rename = savedRename;
    }
    out.state = sf.readState(home);
    if (op.op !== 'stats_step') out.tree = tree(home, bed);
    results.push(mask(JSON.parse(JSON.stringify(out)), bed));
  }
  return results;
}

// ---------------------------------------------------------------------------- cases

export async function run(ctx) {
  const cases = [];
  const bed = (side) => mkdtempSync(join(ctx.scratch, `skill-improve-${side}-`));
  const { ops, label } = opList();
  const py = ctx.runPython(REF, { bed: bed('py'), ops }).results;
  const nd = await runNode(ctx, bed('node'), ops);
  ops.forEach((op, i) => {
    cases.push({ name: label[i], kind: 'json', expected: py[i], actual: nd[i] });
  });

  // per-side literals: what a change made to BOTH runtimes alike would move
  const find = (l) => {
    const i = label.indexOf(l);
    if (i < 0) throw new Error(`skill-improve: no op labelled ${l}`);
    return i;
  };
  const iFour = find('judge_step: 4 uses are never judged');
  const iFive = find('judge_step: 5 uses are judged, rolled back to v1');
  const iInstall = find('h1: install sk-a');
  const iV2 = find('new_version: v2, v1 in history');
  const verdicts = RATES.map(([l]) => find(`judge_step: ${l}`));
  const iStats = find('stats_step: each row in, out, or counted once');
  const iEdited = find('judge_step: an edited skill is never judged');
  const iDailyOn = find('daily: counts, promotes, judges');
  const iDailyOff = find('daily: BANTAMKIT_SKILL_AUTO=off counts and judges, promotes nothing');
  const iDailyNext = find('daily: the next day with the switch on promotes');
  for (const [side, got] of [
    ['python', py],
    ['node', nd],
  ]) {
    cases.push({
      name: `LITERAL: constants [uses, kept, rolled back, history, kinds] — ${side}`,
      kind: 'json',
      expected: [5, 'kept', 'rolled back', 'references/history', ['auto', 'approved']],
      actual: got[0],
    });
    cases.push({
      name: `LITERAL: 4 uses are not judged, 5 are — ${side}`,
      kind: 'json',
      expected: [[], false, ['rolled back sk-a to v1'], 'rolled back'],
      actual: [
        got[iFour].events,
        Object.hasOwn(got[iFour].state?.skills?.['sk-a']?.versions?.['2'] ?? {}, 'verdict'),
        got[iFive].events,
        got[iFive].state?.skills?.['sk-a']?.versions?.['2']?.verdict ?? null,
      ],
    });
    const skill = (t) => t?.['.bantamkit/skills/sk-a/SKILL.md'] ?? null;
    cases.push({
      name: `LITERAL: the rollback restores v1's bytes and keeps v2 in history — ${side}`,
      kind: 'json',
      expected: { restored: true, v2kept: true, v1kept: true, version: 1, rolled_back: 2 },
      actual: {
        restored: skill(got[iFive].tree) === skill(got[iInstall].tree),
        v2kept: got[iFive].tree?.['.bantamkit/skills/sk-a/references/history/v2.md'] === skill(got[iV2].tree),
        v1kept: got[iFive].tree?.['.bantamkit/skills/sk-a/references/history/v1.md'] === skill(got[iInstall].tree),
        version: got[iFive].state?.skills?.['sk-a']?.version ?? null,
        rolled_back: got[iFive].state?.skills?.['sk-a']?.rolled_back ?? null,
      },
    });
    cases.push({
      name: `LITERAL: the verdict of each rate fixture — ${side}`,
      kind: 'json',
      expected: ['rolled back', 'kept', 'kept', 'rolled back', 'rolled back', 'kept', 'rolled back', 'kept', 'kept'],
      actual: verdicts.map((i) => got[i].state?.skills?.['sk-r']?.versions?.['2']?.verdict ?? null),
    });
    cases.push({
      name: `LITERAL: the counts of the one stats fixture — ${side}`,
      kind: 'json',
      expected: { false_fires: 1, injects: 4, successes: 3, uses: 5 },
      actual: got[iStats].state?.skills?.['sk-c']?.versions?.['1'] ?? null,
    });
    const promotedOf = (r) => [
      r?.state?.skills?.['sk-d']?.promoted?.mode ?? null,
      Object.hasOwn(r?.state?.skills?.['sk-d'] ?? {}, 'promote_refused'),
      r?.tree?.['.claude/skills/sk-d'] ?? null,
      (r?.state?.events ?? []).map((x) => x.event),
    ];
    cases.push({
      name: `LITERAL: the daily run promotes only with BANTAMKIT_SKILL_AUTO on [on, off, then on] — ${side}`,
      kind: 'json',
      expected: [
        ['symlink', false, `-> ${join('..', '..', '.bantamkit', 'skills', 'sk-d')}`, ['promoted skill sk-d', 'rolled back sk-d to v1']],
        [null, false, null, ['rolled back sk-d to v1']],
        ['symlink', false, `-> ${join('..', '..', '.bantamkit', 'skills', 'sk-d')}`, ['rolled back sk-d to v1', 'promoted skill sk-d']],
      ],
      actual: [iDailyOn, iDailyOff, iDailyNext].map((i) => promotedOf(got[i])),
    });
    cases.push({
      name: `LITERAL: an edited skill is never judged — ${side}`,
      kind: 'json',
      expected: [[], false],
      actual: [got[iEdited].events, Object.hasOwn(got[iEdited].state?.skills?.['sk-e']?.versions?.['2'] ?? {}, 'verdict')],
    });
  }
  const i2 = {
    four: find('improve_step: 4 injects never tune'),
    five: find('improve_step: 5 injects, 3 false: narrowed as v2'),
    two: find('improve_step: 5 injects, 2 false never tune'),
    m1: find('improve_step: 1 miss never widens'),
    m2: find('improve_step: 2 misses widen the keywords'),
    corr: find('improve_step: a correction: a pitfall applied, a steps change proposed'),
    diff: find('improve_step: different steps: a proposal only'),
    g1: find('improve_step: five sessions: a merge proposed'),
    g1approve: find('render: approve the merge: never done for you'),
    edited: find('improve_step: on an edited skill everything is a proposal'),
    x1: find('improve_step: auto unset: the correction is proposed, pitfall and step together'),
    x1list: find('render: auto unset: list shows the one change'),
    x1approve: find('render: auto unset: approve applies it as v2'),
    x2: find('improve_step: auto off: a drafted narrow is proposed'),
    x3: find('improve_step: auto "banana": the widened keywords are proposed, the tune waits'),
    x4: find('improve_step: auto " OFF ", no drafter: the narrow waits'),
    x5: find('improve_step: auto "": different steps: a steps proposal as before'),
    on: ['x6', 'x7', 'x8'].map((h, i) => find(`improve_step: auto ${JSON.stringify([' Yes ', '1', 'TRUE'][i])}: the pitfall applied as v2`)),
  };
  const skillOf = (r, n) => r?.tree?.[`.bantamkit/skills/${n}/SKILL.md`] ?? null;
  for (const [side, got] of [
    ['python', py],
    ['node', nd],
  ]) {
    cases.push({
      name: `LITERAL: part-2 constants — ${side}`,
      kind: 'json',
      expected: [5, [1, 2], 2, 200, 5, [1, 2], ['improve', 'merge', 'remove', 'steps'], ['narrow', 'widen']],
      actual: got[find('constants2')],
    });
    cases.push({
      name: `LITERAL: 4 injects never tune, 5 with 3 false do, 5 with 2 do not — ${side}`,
      kind: 'json',
      expected: [[], ['improved skill sk-n to v2'], []],
      actual: [got[i2.four].events, got[i2.five].events, got[i2.two].events],
    });
    cases.push({
      name: `LITERAL: 1 miss never widens, 2 do — ${side}`,
      kind: 'json',
      expected: [[], ['improved skill sk-m to v2', 'waiting on a drafter to tune sk-m'], 'k1,lexer,tokens'],
      actual: [got[i2.m1].events, got[i2.m2].events, (skillOf(got[i2.m2], 'sk-m') ?? '').match(/bantamkit-keywords: "([^"]*)"/)?.[1] ?? null],
    });
    const body = skillOf(got[i2.corr], 'sk-c') ?? '';
    cases.push({
      name: `LITERAL: the Pitfalls line lands under ## Pitfalls, ## Steps unchanged, a steps change pending — ${side}`,
      kind: 'json',
      expected: [true, false, 'steps', 'pending'],
      actual: [
        body.includes('## Steps\n\n1. Do it [job1/U1].\n\n## Pitfalls\n\n- [s1111aaaa#1] no, use the other parser\n\n## Example'),
        body.includes('2. Before you finish'),
        got[i2.corr].state?.skills?.['sk-c']?.proposal?.kind ?? null,
        got[i2.corr].state?.skills?.['sk-c']?.proposal?.status ?? null,
      ],
    });
    cases.push({
      name: `LITERAL: different steps change nothing on disk; a merge is a proposal only — ${side}`,
      kind: 'json',
      expected: [['proposed a change to sk-s'], 1, ['proposed merging sk-ma with sk-mb'], 'merge', true, true],
      actual: [
        got[i2.diff].events,
        got[i2.diff].state?.skills?.['sk-s']?.version ?? null,
        got[i2.g1].events,
        got[i2.g1].state?.skills?.['sk-ma']?.proposal?.kind ?? null,
        skillOf(got[i2.g1approve], 'sk-ma') === skillOf(got[find('g1: install sk-ma')], 'sk-ma'),
        skillOf(got[i2.g1approve], 'sk-mb') !== null,
      ],
    });
    cases.push({
      name: `LITERAL: an edited skill is never changed automatically — ${side}`,
      kind: 'json',
      expected: [['proposed a change to sk-x'], 1, 'improve', true],
      actual: [
        got[i2.edited].events,
        got[i2.edited].state?.skills?.['sk-x']?.version ?? null,
        got[i2.edited].state?.skills?.['sk-x']?.proposal?.kind ?? null,
        (skillOf(got[i2.edited], 'sk-x') ?? '').endsWith('my own line\n') && !(skillOf(got[i2.edited], 'sk-x') ?? '').includes('s1111aaaa#1'),
      ],
    });
    const x = (i, n) => got[i]?.state?.skills?.[n] ?? {};
    const x1 = x(i2.x1, 'sk-c');
    const unchanged = (i, h, n) => skillOf(got[i], n) === skillOf(got[find(`${h}: install ${n}`)], n);
    cases.push({
      name: `LITERAL: auto unset: no version, ONE improve proposal holding the pitfall AND the step — ${side}`,
      kind: 'json',
      expected: [['proposed a change to sk-c'], 1, true, 'improve', 'pending', true, true],
      actual: [
        got[i2.x1].events,
        x1.version ?? null,
        unchanged(i2.x1, 'x1', 'sk-c'),
        x1.proposal?.kind ?? null,
        x1.proposal?.status ?? null,
        (x1.proposal?.text ?? '').includes(
          '## Steps\n\n1. Do it [job1/U1].\n2. Before you finish, check for what [s1111aaaa#1] was corrected for: no, use the other parser\n\n## Pitfalls\n\n- [s1111aaaa#1] no, use the other parser\n\n## Example',
        ),
        (got[i2.x1list].said ?? '').includes('+2. Before you finish'),
      ],
    });
    cases.push({
      name: `LITERAL: auto unset: approving the proposal makes v2, approved — ${side}`,
      kind: 'json',
      expected: [2, 'approved', true],
      actual: [
        x(i2.x1approve, 'sk-c').version ?? null,
        x(i2.x1approve, 'sk-c').versions?.['2']?.kind ?? null,
        (skillOf(got[i2.x1approve], 'sk-c') ?? '').includes('- [s1111aaaa#1] no, use the other parser'),
      ],
    });
    cases.push({
      name: `LITERAL: auto off / "banana" / " OFF " / "": proposals and a waiting tune, never a version — ${side}`,
      kind: 'json',
      expected: [
        [['proposed a change to sk-n'], 1, true, 'improve', true],
        [['proposed a change to sk-m', 'waiting on a drafter to tune sk-m'], 1, true, 'improve', true],
        [['waiting on a drafter to tune sk-t'], 1, true, null, ['narrow']],
        [['proposed a change to sk-s'], 1, true, 'steps', true],
      ],
      actual: [
        [i2.x2, 'x2', 'sk-n', (p) => (p?.text ?? '').includes(NARROW('sk-n'))],
        [i2.x3, 'x3', 'sk-m', (p) => (p?.text ?? '').includes('bantamkit-keywords: "k1,lexer,tokens"')],
        [i2.x4, 'x4', 'sk-t', () => x(i2.x4, 'sk-t').tune?.kinds ?? null],
        [i2.x5, 'x5', 'sk-s', (p) => (p?.text ?? '').includes('It also worked as Grep > Write > Grep [s1111aaaa#1].')],
      ].map(([i, h, n, f]) => [got[i].events, x(i, n).version ?? null, unchanged(i, h, n), x(i, n).proposal?.kind ?? null, f(x(i, n).proposal)]),
    });
    cases.push({
      name: `LITERAL: auto " Yes " / "1" / "TRUE": the pitfall applied as v2, the step proposed — ${side}`,
      kind: 'json',
      expected: [
        [['improved skill sk-c to v2', 'proposed a change to sk-c'], 2, 'steps'],
        [['improved skill sk-c to v2', 'proposed a change to sk-c'], 2, 'steps'],
        [['improved skill sk-c to v2', 'proposed a change to sk-c'], 2, 'steps'],
      ],
      actual: i2.on.map((i) => [got[i].events, x(i, 'sk-c').version ?? null, x(i, 'sk-c').proposal?.kind ?? null]),
    });
  }
  return { cases, notes: [] };
}
