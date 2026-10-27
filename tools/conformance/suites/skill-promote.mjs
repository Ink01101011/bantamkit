/**
 * skill-promote — promotion to a native link and demotion (#206 Task 9), Python against Node.
 *
 * THE PROPERTY: the two runtimes promote and demote a learned skill the same way. A promotion
 * writes into the host's own skills directory (`~/.claude/skills` or `<project>/.claude/skills`)
 * and `skills-state.json` is shared on disk, so the link (its relative target), the Windows
 * copy, the state record and every sentence must agree; and promotion is the one step that
 * costs standing context, so the Q4 budget (8192 bytes of descriptions, `BANTAMKIT_SKILL_BUDGET`)
 * must refuse at the same byte on both sides.
 *
 * HOW. One op list (the table is in `ref/skillpromote_ref.py`) runs in order twice: by the
 * reference in its own bed and by `runNode` below against `dist/skillpromote.js` in another.
 * Each op that touches a home answers the state and the home's whole tree (every file's text,
 * every symlink's target), the bed masked, so a link where a copy belongs, a source a demotion
 * deleted or a foreign skill overwritten all show as a difference.
 *
 * WHAT THE FIXTURES ARE AIMED AT. The budget one byte over and exactly at it (36 bytes against
 * 35 and 36), a second promotion that must count the first one's SYMLINK (72 against 71 and
 * 72: the #205 audit never walks into a symlinked directory), the env budget and its bad
 * spellings; the use bar at 2 and 3; a refusal recorded and not retried the same UTC day,
 * retried the next; a foreign directory and a foreign symlink at the link path; each symlink
 * failure (EPERM, EACCES and Windows 1314 copy, ENOENT refuses); a copy demoted unchanged and
 * refused once edited; the source byte-identical after every demotion; the `[skill]` layer
 * leaving a promoted skill out and taking a demoted one back; a host with no `~/.claude`; a
 * project-level link.
 *
 * THE LITERALS. A rule both runtimes lose together (`>=` for `>` at the budget, say) leaves
 * every differential green, so the constants, the at-budget pair, the link target, the
 * copy modes and the step's events are also pinned per side.
 */
import * as fs from 'node:fs';
import { mkdtempSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'skill-promote';
export const summary = 'promotion to a native link: the budget, the copy fallback, demotion and the use bar';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'skillpromote_ref.py');

const NOW = '2026-10-27T12:00:00.000Z';
const LATER = '2026-10-27T23:59:59.999Z';
const NEXT = '2026-10-28T00:00:00.000Z';

function opList() {
  const ops = [];
  const label = [];
  const add = (l, op) => {
    label.push(l);
    ops.push(op);
  };
  add('constants', { op: 'constants' });
  for (const env of [null, '100', ' 100 ', '1e3', '-5', '', '0']) add(`budget with BANTAMKIT_SKILL_BUDGET=${JSON.stringify(env)}`, { op: 'budget', env });

  // h1: the user level, the budget, the layer, foreign paths
  const h = 'h1';
  add('h1: ~/.claude exists', { op: 'mkdir', home: h, rel: '.claude' });
  for (const n of ['p-one', 'p-two', 'p-three']) add(`h1: install ${n}`, { op: 'install', home: h, name: n, level: 'user', now: NOW });
  add('promote: unknown name', { op: 'promote', home: h, name: 'nope', now: NOW, budget: 8192 });
  add('promote p-one: 36 bytes over a budget of 35 is refused', { op: 'promote', home: h, name: 'p-one', now: NOW, budget: 35 });
  add('promote p-one: BANTAMKIT_SKILL_BUDGET=35 refuses too', { op: 'promote', home: h, name: 'p-one', now: NOW, budget: null, env: '35' });
  add('promote p-one: exactly at a budget of 36 passes (a symlink)', { op: 'promote', home: h, name: 'p-one', now: NOW, budget: 36 });
  add('promote p-two: the first link counts, 72 over 71', { op: 'promote', home: h, name: 'p-two', now: NOW, budget: 71 });
  add('promote p-two: 72 at 72 passes', { op: 'promote', home: h, name: 'p-two', now: NOW, budget: 72 });
  add('promote p-two again: already promoted', { op: 'promote', home: h, name: 'p-two', now: NOW, budget: 0 });
  add('the layer leaves the promoted out', { op: 'layer', home: h });
  add('demote p-one: the link goes, the source stays', { op: 'demote', home: h, name: 'p-one' });
  add('the layer takes p-one back', { op: 'layer', home: h });
  add('demote p-one again: not promoted', { op: 'demote', home: h, name: 'p-one' });
  add('demote: unknown name', { op: 'demote', home: h, name: 'nope' });
  add('h1: a foreign skill at p-three', { op: 'write', home: h, rel: '.claude/skills/p-three/SKILL.md', text: '---\nname: p-three\ndescription: mine\n---\nbody\n' });
  add('promote p-three: a foreign directory is never replaced', { op: 'promote', home: h, name: 'p-three', now: NOW, budget: 8192 });
  add('h1: a foreign symlink at p-one', { op: 'symlink', home: h, rel: '.claude/skills/p-one', target: '../../elsewhere' });
  add('promote p-one: a foreign symlink is never replaced', { op: 'promote', home: h, name: 'p-one', now: NOW, budget: 8192 });
  add('h1: a second, user-made link to p-two', { op: 'symlink', home: h, rel: '.claude/skills/p-two-x', target: '../../.bantamkit/skills/p-two' });
  add('demote p-two: unchanged link removed', { op: 'demote', home: h, name: 'p-two' });

  // h2: the copy path
  const c = 'h2';
  add('h2: ~/.claude exists', { op: 'mkdir', home: c, rel: '.claude' });
  for (const n of ['c-one', 'c-two', 'c-three', 'c-four']) add(`h2: install ${n}`, { op: 'install', home: c, name: n, level: 'user', now: NOW });
  add('promote c-one: EPERM copies', { op: 'promote', home: c, name: 'c-one', now: NOW, budget: 8192, symlink_fails: 'EPERM' });
  add('promote c-two: EACCES copies', { op: 'promote', home: c, name: 'c-two', now: NOW, budget: 8192, symlink_fails: 'EACCES' });
  add('promote c-three: Windows 1314 copies', { op: 'promote', home: c, name: 'c-three', now: NOW, budget: 8192, symlink_fails: 'WIN1314' });
  add('promote c-four: ENOENT refuses, nothing copied', { op: 'promote', home: c, name: 'c-four', now: NOW, budget: 8192, symlink_fails: 'ENOENT' });
  add('promote c-four: three copies count, 150 over 149', { op: 'promote', home: c, name: 'c-four', now: NOW, budget: 149 });
  add('demote c-one: an unchanged copy is removed', { op: 'demote', home: c, name: 'c-one' });
  add('h2: someone edits the c-two copy', { op: 'append', home: c, rel: '.claude/skills/c-two/SKILL.md', text: 'mine now\n' });
  add('demote c-two: a changed copy is refused', { op: 'demote', home: c, name: 'c-two' });
  add('h2: someone adds a file to the c-three copy', { op: 'write', home: c, rel: '.claude/skills/c-three/notes.md', text: 'n\n' });
  add('demote c-three: a file added is a change', { op: 'demote', home: c, name: 'c-three' });

  // h3: no Claude Code
  add('h3: install x-one (no ~/.claude)', { op: 'install', home: 'h3', name: 'x-one', level: 'user', now: NOW });
  add('promote x-one: Claude Code only', { op: 'promote', home: 'h3', name: 'x-one', now: NOW, budget: 8192 });
  add('promote_step on h3: the refusal is recorded', { op: 'promote_step', home: 'h3', uses: { 'x-one': 3 }, now: NOW, budget: 8192 });

  // h4: a project-level skill
  add('h4: ~/.claude exists', { op: 'mkdir', home: 'h4', rel: '.claude' });
  add('h4: install a project skill', { op: 'install', home: 'h4', name: 'proj-one', level: 'project', top: 'h4/proj', now: NOW });
  add('promote proj-one into the project', { op: 'promote', home: 'h4', cwd: 'h4/proj', name: 'proj-one', now: NOW, budget: 8192 });
  add('demote proj-one', { op: 'demote', home: 'h4', name: 'proj-one' });

  // h5: the daily step
  const s = 'h5';
  add('h5: ~/.claude exists', { op: 'mkdir', home: s, rel: '.claude' });
  for (const n of ['s-two', 's-three', 's-zbig']) add(`h5: install ${n}`, { op: 'install', home: s, name: n, level: 'user', now: NOW });
  add('promote_step: 2 uses waits, 3 promotes, the next is over budget', {
    op: 'promote_step', home: s, uses: { 's-two': 2, 's-three': 3, 's-zbig': 5, 'not-installed': 9 }, now: NOW, budget: 70,
  });
  add('promote_step: the same UTC day at 23:59:59.999 does not retry', { op: 'promote_step', home: s, uses: { 's-two': 2, 's-three': 3, 's-zbig': 5 }, now: LATER, budget: 1000 });
  add('promote_step: the next day retries and promotes', { op: 'promote_step', home: s, uses: { 's-two': 2, 's-three': 3, 's-zbig': 5 }, now: NEXT, budget: 1000 });
  add('promote_step: uses of the wrong type count as none', { op: 'promote_step', home: s, uses: { 's-two': '3' }, now: NEXT, budget: 1000 });
  add('promote_step: a bad now', { op: 'promote_step', home: s, uses: {}, now: 'yesterday', budget: 1000 });
  return { ops, label };
}

// ------------------------------------------------------------------------- Node side

function tree(root, bed) {
  const out = {};
  if (!fs.existsSync(root)) return out;
  const walk = (dir) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name);
      const r = relative(root, p).split(sep).join('/');
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
  if (typeof v === 'string') return v.split(bed).join('<bed>');
  if (Array.isArray(v)) return v.map((x) => mask(x, bed));
  if (v !== null && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, mask(x, bed)]));
  return v;
};

const draft = (n) =>
  `---\nname: ${n}\ndescription: Does ${n}. Use when ${n} is asked.\n---\n\n` +
  '## When to use\n\nWhen asked.\n\n## Steps\n\n1. Do it [job1/U1].\n\n## Pitfalls\n\nNone.\n\n## Example\n\nx\n';

const cluster = (n, level, top) => ({
  evidence: [{ id: 'job1/U1', ok: true, ts: '2026-01-01T00:00:00Z' }],
  id: `c-${n}`,
  keywords: ['k1'],
  level,
  members: 3,
  source: 'shiftwork',
  status: 'pending',
  successes: 3,
  top,
});

function failing(kind) {
  return () => {
    const code = kind === 'WIN1314' ? 'EPERM' : kind;
    const e = new Error(`${code}: injected symlink failure`);
    e.code = code;
    throw e;
  };
}

async function runNode(ctx, bed, ops) {
  const dist = (m) => pathToFileURL(join(ctx.runtimeTs, 'dist', m)).href;
  const sp = await import(dist('skillpromote.js'));
  const si = await import(dist('skillinstall.js'));
  const sf = await import(dist('skillfile.js'));
  const { SkillStore } = await import(dist('memory/skills.js'));
  const results = [];
  for (const raw of ops) {
    const op = sub(raw, bed);
    const home = op.home !== undefined ? join(bed, op.home) : bed;
    const cwd = op.cwd ? join(bed, op.cwd) : null;
    const savedEnv = process.env[sp.BUDGET_ENV];
    if (op.env === undefined || op.env === null) delete process.env[sp.BUDGET_ENV];
    else process.env[sp.BUDGET_ENV] = op.env;
    try {
      if (op.op === 'constants') {
        results.push([sp.PROMOTE_USES, sp.PROMOTE_DAYS, sp.BUDGET_DEFAULT, sp.BUDGET_ENV, sp.MODE_SYMLINK, sp.MODE_COPY]);
        continue;
      }
      if (op.op === 'budget') {
        results.push(sp.skillBudget());
        continue;
      }
      if (op.op === 'mkdir') {
        fs.mkdirSync(join(home, op.rel), { recursive: true });
        results.push({});
        continue;
      }
      if (op.op === 'write') {
        fs.mkdirSync(dirname(join(home, op.rel)), { recursive: true });
        fs.writeFileSync(join(home, op.rel), op.text);
        results.push({});
        continue;
      }
      if (op.op === 'append') {
        fs.appendFileSync(join(home, op.rel), op.text);
        results.push({});
        continue;
      }
      if (op.op === 'symlink') {
        fs.mkdirSync(dirname(join(home, op.rel)), { recursive: true });
        fs.symlinkSync(op.target, join(home, op.rel), 'dir');
        results.push({});
        continue;
      }
      if (op.op === 'layer') {
        results.push(new SkillStore([sf.skillsRoot(home)], home).candidates().map((f) => f.name));
        continue;
      }
      if (op.op === 'install') {
        const top = op.top ? join(bed, op.top) : null;
        si.install(cluster(op.name, op.level, top), draft(op.name), null, home, op.now, false);
        results.push({ tree: mask(tree(home, bed), bed) });
        continue;
      }
      const symlink = op.symlink_fails ? failing(op.symlink_fails) : null;
      let out = {};
      try {
        if (op.op === 'promote') {
          const got = sp.promote(op.name, home, cwd, op.now, op.budget ?? null, { symlink });
          out.result = { mode: got.mode, ok: got.ok, reason: got.reason };
        } else if (op.op === 'demote') {
          out.said = sp.demote(op.name, home);
        } else if (op.op === 'promote_step') {
          const state = sf.readState(home);
          out.events = sp.promoteStep(state, op.uses, home, cwd, op.now, op.budget ?? null, { symlink });
          out.returned_state = state;
        } else {
          throw new Error(`skill-promote: unknown op ${op.op}`);
        }
      } catch (e) {
        if (e instanceof sf.SkillFileError) out = { error: e.message };
        else throw e;
      }
      out.state = sf.readState(home);
      out.tree = tree(home, bed);
      results.push(mask(JSON.parse(JSON.stringify(out)), bed));
    } finally {
      if (savedEnv === undefined) delete process.env[sp.BUDGET_ENV];
      else process.env[sp.BUDGET_ENV] = savedEnv;
    }
  }
  return results;
}

// ---------------------------------------------------------------------------- cases

export async function run(ctx) {
  const cases = [];
  const bed = (side) => mkdtempSync(join(ctx.scratch, `skill-promote-${side}-`));
  const { ops, label } = opList();
  const py = ctx.runPython(REF, { bed: bed('py'), ops }).results;
  const nd = await runNode(ctx, bed('node'), ops);
  ops.forEach((op, i) => {
    cases.push({ name: label[i], kind: 'json', expected: py[i], actual: nd[i] });
  });

  // per-side literals: what a change made to BOTH runtimes alike would move
  const find = (l) => {
    const i = label.indexOf(l);
    if (i < 0) throw new Error(`skill-promote: no op labelled ${l}`);
    return i;
  };
  const iOver = find('promote p-one: 36 bytes over a budget of 35 is refused');
  const iAt = find('promote p-one: exactly at a budget of 36 passes (a symlink)');
  const iLinkOver = find('promote p-two: the first link counts, 72 over 71');
  const iFirstStep = find('promote_step: 2 uses waits, 3 promotes, the next is over budget');
  const iSame = find('promote_step: the same UTC day at 23:59:59.999 does not retry');
  const iNext = find('promote_step: the next day retries and promotes');
  const copies = ['promote c-one: EPERM copies', 'promote c-two: EACCES copies', 'promote c-three: Windows 1314 copies', 'promote c-four: ENOENT refuses, nothing copied'].map(find);
  const iDemote = find('demote p-one: the link goes, the source stays');
  const iInstallOne = find('h1: install p-one');
  for (const [side, got] of [
    ['python', py],
    ['node', nd],
  ]) {
    const src = (t) => Object.fromEntries(Object.entries(t).filter(([k]) => k.startsWith('.bantamkit/skills/p-one/')));
    cases.push({
      name: `LITERAL: constants [uses, days, budget, env, modes] — ${side}`,
      kind: 'json',
      expected: [3, 30, 8192, 'BANTAMKIT_SKILL_BUDGET', 'symlink', 'copy'],
      actual: got[0],
    });
    cases.push({
      name: `LITERAL: the budget refuses one byte over and passes exactly at it — ${side}`,
      kind: 'json',
      expected: [
        { mode: null, ok: false, reason: 'promoting p-one would take the catalogue to 36 bytes, over the budget of 35' },
        { mode: 'symlink', ok: true, reason: 'promoted skill p-one' },
        { mode: null, ok: false, reason: 'promoting p-two would take the catalogue to 72 bytes, over the budget of 71' },
      ],
      actual: [iOver, iAt, iLinkOver].map((i) => got[i].result ?? got[i]),
    });
    cases.push({
      name: `LITERAL: the link is relative, and demotion leaves the source byte-identical — ${side}`,
      kind: 'json',
      expected: { link: '-> ../../.bantamkit/skills/p-one', source: true, gone: true },
      actual: {
        link: got[iAt].tree?.['.claude/skills/p-one'] ?? null,
        source: JSON.stringify(src(got[iDemote].tree ?? {})) === JSON.stringify(src(got[iInstallOne].tree ?? {})),
        gone: !Object.hasOwn(got[iDemote].tree ?? {}, '.claude/skills/p-one'),
      },
    });
    cases.push({
      name: `LITERAL: EPERM, EACCES and 1314 copy; ENOENT refuses — ${side}`,
      kind: 'json',
      expected: ['copy', 'copy', 'copy', null],
      actual: copies.map((i) => (got[i].result ? got[i].result.mode : 'error')),
    });
    cases.push({
      name: `LITERAL: the daily step's events [first, same day, next day] — ${side}`,
      kind: 'json',
      expected: [['promoted skill s-three'], [], ['promoted skill s-zbig']],
      actual: [iFirstStep, iSame, iNext].map((i) => got[i].events ?? got[i]),
    });
  }
  return { cases, notes: [] };
}
