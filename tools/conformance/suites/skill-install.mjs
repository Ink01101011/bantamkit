/**
 * skill-install — the installer (#206 Task 7), Python against Node.
 *
 * THE PROPERTY: the two runtimes install, keep and remove a learned skill the same way. Every
 * file an install writes (`SKILL.md` stamped with its hash, `references/evidence.md`, the
 * "absent" backup) and `skills-state.json` are shared on disk between the runtimes, so the
 * bytes must agree; the auto rule (twice the bar, a passed draft, 1 a day, 5 live,
 * `BANTAMKIT_SKILL_AUTO`), probation (removed when unused and unedited, proposed when edited,
 * left when used) and undo decide what a user finds in their skills root, so the events and
 * the whole home after each op must agree too.
 *
 * HOW. One op list (see `ref/skillinstall_ref.py` for the table) runs in order twice: by the
 * reference in its own bed and by `runNode` below against `dist/skillinstall.js` in another.
 * Each answer is one case; every op that touches a home answers that home's whole tree with
 * every file's text, the bed masked, so a temp dir left behind, a missing backup or a wrong
 * byte all show as a difference.
 *
 * WHAT THE FIXTURES ARE AIMED AT. Each bar at the bar and one below it (5 and 6 successes
 * against an auto bar of 6; a forged record whose flag and count disagree each way); the
 * per-day cap at 23:59:59.999 the same day and the next day; the live cap at 5 and the 6th
 * after an undo; every off spelling of the switch; probation on day 29 and day 30, unused,
 * edited and used; undo after a probation removal (byte for byte) and after an install; an
 * injected rename failure; every refusal sentence; the evidence file of a project-level and a
 * user-level skill (the Q8 cut at 80 and 500 code points, commit subjects whole, a lone
 * surrogate, a planted tool result that must appear nowhere).
 *
 * THE LITERALS. A rule both runtimes lose together (PROBATION_DAYS 29 on both sides, say)
 * leaves every differential green, so the constants, one install's `probation_until` and the
 * event sequences of the two caps are also pinned per side.
 */
import * as fs from 'node:fs';
import { mkdtempSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'skill-install';
export const summary = 'the installer: the auto rule, the caps, probation, undo and the evidence file';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'skillinstall_ref.py');

const NOW = '2026-10-27T12:00:00.000Z';
const DAY = 86_400_000;
const at = (days) => new Date(Date.parse(NOW) + days * DAY).toISOString();
const PLANT = 'PLANTED TOOL OUTPUT 7f3a';

const draft = (n, extra = '') =>
  `---\nname: ${n}\ndescription: Does ${n}. Use when ${n} is asked.\n${extra}---\n\n` +
  '## When to use\n\nWhen asked.\n\n## Steps\n\n1. Do it [job1/U1].\n\n## Pitfalls\n\nNone.\n\n## Example\n\nx\n';

function record(n, successes = 6, o = {}) {
  const bar = o.bar ?? 3;
  const rec = {
    auto_bar: 2 * bar,
    auto_eligible: o.autoEligible ?? successes >= 2 * bar,
    bar,
    eligible: successes >= bar,
    evidence: Array.from({ length: successes }, (_, i) => ({
      commits: i === 0 ? ['feat(x): the subject, kept whole even past eighty characters of text (#206)'] : [],
      failure: null,
      id: `job1/U${i + 1}`,
      ok: true,
      paths: ['src/a.py'],
      prompt: `fix the thing number ${i}`,
      repo: '/r/.git',
      signals: { commit: true, tests: false },
      source: 'shiftwork',
      tools: ['Read', 'Edit'],
      ts: o.ts ?? '2026-01-01T00:00:00Z',
    })),
    id: `c-${n}`,
    keywords: Array.from({ length: 20 }, (_, i) => `k${i}`),
    level: o.level ?? 'user',
    members: successes,
    pitfalls: [],
    repos: [],
    source: 'shiftwork',
    status: o.status ?? 'pending',
    steps: [],
    successes,
    top: o.top ?? null,
  };
  if (o.okDraft !== false) rec.draft = { drafter: 'endpoint m', ok: o.draftOk ?? true, text: o.text ?? draft(n), ts: NOW };
  return rec;
}

// the evidence fixture: every field shape, Q8's two cuts, X4
const EVIDENCE = {
  ...record('fixing-a', 2),
  evidence: [
    {
      commits: ['fix: one', 'fix: one', 42, 'ไทย 😀 subject'],
      failure: null,
      id: 'sa1b2c3d4#2',
      ok: true,
      paths: ['src/a.py', 'docs/x.md'],
      prompt: `${'ก'.repeat(79)}😀${'x'.repeat(500)}`,
      signals: { uncorrected: true, commit: false, tests: 'yes' },
      tools: ['Bash', 'Edit'],
      ts: '2026-03-01T00:00:00Z',
      tool_result: PLANT,
    },
    {
      failure: `corrected in the next turn: ${'n'.repeat(600)}`,
      id: 'sa1b2c3d4#3',
      ok: false,
      paths: [],
      prompt: 'line one\n\nline \ud800 three',
      signals: {},
      tools: [],
      ts: '2026-03-02T00:00:00Z',
    },
    { id: 'job9/U1', ok: null, failure: 'escalated: the unit could not proceed', prompt: '', tools: 'x', paths: null },
    { id: '', prompt: 'no id' },
    'not a dict',
  ],
  result: PLANT,
};

function opList() {
  const ops = [];
  const label = [];
  const add = (l, op) => {
    label.push(l);
    ops.push(op);
  };
  add('constants', { op: 'constants' });
  for (const level of ['user', 'project']) add(`evidence.md, ${level} level`, { op: 'evidence', cluster: EVIDENCE, name: 'fixing-a', level });

  // h1: the auto rule and the caps
  const h = 'h1';
  add('auto: one below the auto bar, a forged flag each way, at the plain bar', {
    op: 'auto',
    env: 'on',
    home: h,
    now: NOW,
    proposals: {
      clusters: [
        record('below', 5),
        record('at-plain-bar', 3),
        record('flag-forged-true', 5, { autoEligible: true }),
        record('flag-forged-false', 6, { autoEligible: false }),
      ],
    },
  });
  add('auto: no draft, a failed gate, rejected, installed, failed', {
    op: 'auto',
    env: 'on',
    home: h,
    now: NOW,
    proposals: {
      clusters: [
        record('no-draft', 9, { okDraft: false }),
        record('gate-failed', 9, { draftOk: false }),
        record('rejected', 9, { status: 'rejected' }),
        record('installed', 9, { status: 'installed' }),
        record('failed', 9, { status: 'failed' }),
      ],
    },
  });
  for (const env of ['off', 'OFF', ' 0 ', 'false', 'no']) {
    add(`auto: BANTAMKIT_SKILL_AUTO=${JSON.stringify(env)} installs nothing`, { op: 'auto', home: h, now: NOW, env, proposals: { clusters: [record('skill-a', 8)] } });
  }
  // job73 C13b: OFF by default in 0.37.0 — only on/1/true/yes (any case, trimmed) opt in; unset,
  // empty and any unknown word leave it off. Each on spelling gets its own home (one a day).
  for (const env of [null, '', 'banana', 'enabled', 'on please']) {
    add(`auto: BANTAMKIT_SKILL_AUTO=${JSON.stringify(env)} (default off) installs nothing`, { op: 'auto', home: 'h0', now: NOW, env, proposals: { clusters: [record('skill-a', 8)] } });
  }
  for (const [i, env] of [' ON ', '1', 'true', 'YES', 'On'].entries()) {
    add(`auto: BANTAMKIT_SKILL_AUTO=${JSON.stringify(env)} opts in`, { op: 'auto', home: `hon${i}`, now: NOW, env, proposals: { clusters: [record('skill-a', 8)] } });
  }
  add('mkdir a skill dir named taken', { op: 'mkdir', home: h, rel: '.bantamkit/skills/taken' });
  add('auto: a name already on disk is failed, the next installed (best first)', {
    op: 'auto',
    home: h,
    now: NOW,
    env: 'on',
    proposals: { clusters: [record('skill-b', 7), record('skill-a', 8), record('taken', 9), record('skill-c', 7, { ts: '2025-12-31T00:00:00Z' })] },
  });
  add('auto: the same UTC day at 23:59:59.999 installs nothing', { op: 'auto', env: 'on', home: h, now: '2026-10-27T23:59:59.999Z', proposals: { clusters: [record('skill-c', 7, { ts: '2025-12-31T00:00:00Z' }), record('skill-b', 7)] } });
  add('auto: the next day, oldest first on a tie', { op: 'auto', env: 'on', home: h, now: at(1), proposals: { clusters: [record('skill-b', 7), record('skill-c', 7, { ts: '2025-12-31T00:00:00Z' })] } });
  for (const [i, n] of [[2, 'skill-d'], [3, 'skill-e'], [4, 'skill-f']]) {
    add(`auto: day ${i} installs ${n}`, { op: 'auto', env: 'on', home: h, now: at(i), proposals: { clusters: [record(n)] } });
  }
  add('auto: five live, the sixth waits', { op: 'auto', env: 'on', home: h, now: at(5), proposals: { clusters: [record('skill-g')] } });
  add('undo the first auto install', { op: 'undo', home: h, name: 'skill-a' });
  add('auto: four live, the sixth goes in', { op: 'auto', env: 'on', home: h, now: at(6), proposals: { clusters: [record('skill-g')] } });

  // h2: probation and undo
  const p = 'h2';
  for (const n of ['unused-a', 'used-b', 'edited-c', 'approved-d']) {
    add(`install ${n}`, { op: 'install', home: p, cluster: record(n), text: draft(n), level: null, now: NOW, auto: n !== 'approved-d' });
  }
  add('edit edited-c by hand', { op: 'edit', home: p, rel: '.bantamkit/skills/edited-c/SKILL.md', find: 'When asked.', replace: 'When I ask.' });
  add('probation: a use on day 10 leaves probation', { op: 'probation', home: p, uses: { 'used-b': 1, 'unused-a': 0 }, now: at(10) });
  add('probation on day 29: nothing', { op: 'probation', home: p, uses: {}, now: at(29) });
  add('probation on day 30: unused removed, edited proposed, used and approved kept', { op: 'probation', home: p, uses: {}, now: at(30) });
  add('probation on day 60: nothing more', { op: 'probation', home: p, uses: {}, now: at(60) });
  add('undo the probation removal: back byte for byte', { op: 'undo', home: p, name: 'unused-a' });
  add('undo again: the install undone', { op: 'undo', home: p, name: 'unused-a' });
  add('undo with nothing left', { op: 'undo', home: p, name: 'unused-a' });
  add('undo an unknown name', { op: 'undo', home: p, name: 'never' });

  // h3: installs and refusals
  const r = 'h3';
  add('install a project-level skill under its top', { op: 'install', home: r, cluster: record('in-project', 6, { level: 'project', top: '<bed>/proj' }), text: draft('in-project'), level: null, now: NOW, auto: false });
  add('install with the level overridden to user', { op: 'install', home: r, cluster: record('to-user', 6, { level: 'project', top: '<bed>/proj' }), text: draft('to-user'), level: 'user', now: NOW, auto: false });
  add('refused: project level with no top', { op: 'install', home: r, cluster: record('no-top', 6, { level: 'project' }), text: draft('no-top'), level: null, now: NOW, auto: true });
  add('refused: a level that is neither', { op: 'install', home: r, cluster: record('x-y'), text: draft('x-y'), level: 'global', now: NOW, auto: true });
  add('refused: a draft with no steps', { op: 'install', home: r, cluster: record('x-y'), text: '---\nname: x-y\ndescription: d\n---\n', level: null, now: NOW, auto: true });
  add('refused: a draft with metadata: {} (job73 C8)', { op: 'install', home: r, cluster: record('x-y'), text: draft('x-y', 'metadata: {}\n'), level: null, now: NOW, auto: true });
  add('refused: a draft that is not a skill file', { op: 'install', home: r, cluster: record('x-y'), text: 'hello', level: null, now: NOW, auto: true });
  add('refused: already installed', { op: 'install', home: r, cluster: record('to-user'), text: draft('to-user'), level: null, now: NOW, auto: true });
  add('refused: a bad now', { op: 'install', home: r, cluster: record('x-y'), text: draft('x-y'), level: null, now: 'yesterday', auto: true });
  add('refused: no cluster id', { op: 'install', home: r, cluster: { ...record('x-y'), id: '' }, text: draft('x-y'), level: null, now: NOW, auto: true });
  add('install fails at the directory rename: nothing left', { op: 'install', home: r, cluster: record('half-z'), text: draft('half-z'), level: null, now: NOW, auto: true, fail_at: 'rename2' });
  add('install fails writing evidence.md: nothing left', { op: 'install', home: r, cluster: record('half-w'), text: draft('half-w'), level: null, now: NOW, auto: true, fail_at: 'write3' });
  add('the draft carries its own metadata, kept beside the stamp', { op: 'install', home: r, cluster: record('own-meta'), text: draft('own-meta', 'metadata:\n  bantamkit-note: "kept"\n'), level: null, now: NOW, auto: true });
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
      if (e.isDirectory()) {
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

async function runNode(ctx, bed, ops) {
  const dist = (m) => pathToFileURL(join(ctx.runtimeTs, 'dist', m)).href;
  const si = await import(dist('skillinstall.js'));
  const sf = await import(dist('skillfile.js'));
  const results = [];
  for (const raw of ops) {
    const op = sub(raw, bed);
    const home = op.home !== undefined ? join(bed, op.home) : bed;
    const savedEnv = process.env[si.AUTO_ENV];
    if (op.env === undefined || op.env === null) delete process.env[si.AUTO_ENV];
    else process.env[si.AUTO_ENV] = op.env;
    const savedRename = sf.seams.rename;
    const savedWrite = sf.seams.write;
    try {
      if (op.op === 'constants') {
        results.push([si.AUTO_PER_DAY, si.AUTO_LIVE_MAX, si.PROBATION_DAYS, si.KEYWORDS_MAX, si.EVIDENCE_PROJECT_CHARS, si.EVIDENCE_USER_CHARS, si.AUTO_ENV]);
        continue;
      }
      if (op.op === 'evidence') {
        results.push({ text: si.evidenceMarkdown(op.cluster, op.name, op.level) });
        continue;
      }
      if (op.op === 'mkdir') {
        fs.mkdirSync(join(home, op.rel), { recursive: true });
        results.push({});
        continue;
      }
      if (op.op === 'edit') {
        const p = join(home, op.rel);
        fs.writeFileSync(p, fs.readFileSync(p, 'utf8').split(op.find).join(op.replace));
        results.push({ tree: mask(tree(home, bed), bed) });
        continue;
      }
      if (op.fail_at === 'write3') {
        let writes = 0;
        sf.seams.write = (f, d) => {
          writes += 1;
          savedWrite(f, d);
          if (writes === 3) throw new Error('injected');
        };
      }
      if (op.fail_at === 'rename2') {
        let calls = 0;
        sf.seams.rename = (s, d) => {
          calls += 1;
          if (calls === 2) throw new Error('injected');
          savedRename(s, d);
        };
      }
      let out = {};
      try {
        if (op.op === 'install') {
          const got = si.install(op.cluster, op.text, op.level ?? null, home, op.now, op.auto);
          out.installed = { name: got.name, level: got.level, path: got.path, event: got.event, entry: got.entry };
        } else if (op.op === 'auto') {
          const state = sf.readState(home);
          out.events = si.autoStep(op.proposals, state, home, op.now);
          out.statuses = op.proposals.clusters.map((c) => c.status);
          out.state = state;
        } else if (op.op === 'probation') {
          const state = sf.readState(home);
          out.events = si.probationStep(state, op.uses, home, op.now);
          out.state = state;
        } else if (op.op === 'undo') {
          out.said = si.undo(op.name, home);
        } else {
          throw new Error(`skill-install: unknown op ${op.op}`);
        }
      } catch (e) {
        if (e instanceof sf.SkillFileError) out = { error: e.message };
        else if (/injected/.test(String(e?.message))) out = { error: 'raised' };
        else throw e;
      }
      if (op.op === 'install') out.status = op.cluster.status ?? null;
      out.tree = tree(home, bed);
      results.push(mask(JSON.parse(JSON.stringify(out)), bed));
    } finally {
      sf.seams.rename = savedRename;
      sf.seams.write = savedWrite;
      if (savedEnv === undefined) delete process.env[si.AUTO_ENV];
      else process.env[si.AUTO_ENV] = savedEnv;
    }
  }
  return results;
}

// ---------------------------------------------------------------------------- cases

export async function run(ctx) {
  const cases = [];
  const bed = (side) => mkdtempSync(join(ctx.scratch, `skill-install-${side}-`));
  const { ops, label } = opList();
  const py = ctx.runPython(REF, { bed: bed('py'), ops }).results;
  const nd = await runNode(ctx, bed('node'), ops);
  ops.forEach((op, i) => {
    const isText = op.op === 'evidence';
    cases.push({
      name: label[i],
      kind: isText ? 'string' : 'json',
      expected: isText ? py[i].text : py[i],
      actual: isText ? nd[i].text : nd[i],
    });
  });

  // per-side literals: what a change made to BOTH runtimes alike would move
  const find = (l) => label.indexOf(l);
  const iFirst = find('auto: a name already on disk is failed, the next installed (best first)');
  const iSame = find('auto: the same UTC day at 23:59:59.999 installs nothing');
  const iNext = find('auto: the next day, oldest first on a tie');
  const iSixth = find('auto: five live, the sixth waits');
  const iAfter = find('auto: four live, the sixth goes in');
  const iBar = find('auto: one below the auto bar, a forged flag each way, at the plain bar');
  const iOff = find('auto: BANTAMKIT_SKILL_AUTO="off" installs nothing');
  const iDefaults = [null, '', 'banana', 'enabled', 'on please'].map((e) => find(`auto: BANTAMKIT_SKILL_AUTO=${JSON.stringify(e)} (default off) installs nothing`));
  const iOns = [' ON ', '1', 'true', 'YES', 'On'].map((e) => find(`auto: BANTAMKIT_SKILL_AUTO=${JSON.stringify(e)} opts in`));
  const iDay30 = find('probation on day 30: unused removed, edited proposed, used and approved kept');
  const iUndo = find('undo the probation removal: back byte for byte');
  const iHalf = find('install fails at the directory rename: nothing left');
  const iBefore = find('refused: no cluster id');
  const iHalfW = find('install fails writing evidence.md: nothing left');
  const iEvU = find('evidence.md, user level');
  const iEvP = find('evidence.md, project level');
  const iUnused = find('install unused-a');
  for (const [side, got] of [
    ['python', py],
    ['node', nd],
  ]) {
    const unusedTree = got[iUnused].tree;
    const skillFiles = (t, n) => Object.fromEntries(Object.entries(t).filter(([k]) => k.startsWith(`.bantamkit/skills/${n}/`)));
    cases.push({
      name: `LITERAL: constants [per day, live, probation days, keywords, Q8 project cut, user cut, switch] — ${side}`,
      kind: 'json',
      expected: [1, 5, 30, 16, 80, 500, 'BANTAMKIT_SKILL_AUTO'],
      actual: got[0],
    });
    cases.push({
      name: `LITERAL: an automatic install at ${NOW} is on probation until ${at(30)} — ${side}`,
      kind: 'json',
      expected: at(30),
      actual: got[iUnused].installed?.entry?.probation_until ?? null,
    });
    cases.push({
      name: `LITERAL: the caps, as events [bar, off, first, same day, next day, sixth, after an undo] — ${side}`,
      kind: 'json',
      expected: [[], [], ['installed skill skill-a'], [], ['installed skill skill-c'], [], ['installed skill skill-g']],
      actual: [iBar, iOff, iFirst, iSame, iNext, iSixth, iAfter].map((i) => got[i].events),
    });
    cases.push({
      name: `LITERAL: BANTAMKIT_SKILL_AUTO is off unless on/1/true/yes [unset, "", banana, enabled, "on please" | " ON ", 1, true, YES, On] — ${side}`,
      kind: 'json',
      expected: [[], [], [], [], [], ['installed skill skill-a'], ['installed skill skill-a'], ['installed skill skill-a'], ['installed skill skill-a'], ['installed skill skill-a']],
      actual: [...iDefaults, ...iOns].map((i) => got[i].events ?? null),
    });
    cases.push({
      name: `LITERAL: probation day 30 and the undo after it — ${side}`,
      kind: 'json',
      expected: {
        events: ['proposed removing edited skill edited-c', 'removed unused skill unused-a'],
        said: 'restored unused-a from its backup of 20261126T120000.000Z',
        back: true,
      },
      actual: {
        events: got[iDay30].events,
        said: got[iUndo].said,
        back: JSON.stringify(skillFiles(got[iUndo].tree, 'unused-a')) === JSON.stringify(skillFiles(unusedTree, 'unused-a')),
      },
    });
    cases.push({
      name: `LITERAL: a failed directory rename or file write leaves the home as it was — ${side}`,
      kind: 'json',
      expected: { rename: { tree: got[iBefore].tree, error: 'raised' }, write: { tree: got[iBefore].tree, error: 'raised' } },
      actual: { rename: { tree: got[iHalf].tree, error: got[iHalf].error }, write: { tree: got[iHalfW].tree, error: got[iHalfW].error } },
    });
    const evU = got[iEvU].text;
    const evP = got[iEvP].text;
    cases.push({
      name: `LITERAL: evidence.md — Q8 cut 80 / 500, commits whole, X4 — ${side}`,
      kind: 'json',
      expected: { project80: true, project81: false, user: true, commits: true, planted: false },
      actual: {
        project80: evP.includes(`  > ${'ก'.repeat(79)}😀\n`),
        project81: evP.includes(`😀x`),
        user: evU.includes(`  > ${'ก'.repeat(79)}😀${'x'.repeat(420)}\n`),
        commits: evP.includes('- Commits:\n  - fix: one\n  - fix: one\n  - ไทย 😀 subject\n'),
        planted: evU.includes(PLANT) || evP.includes(PLANT),
      },
    });
  }
  return { cases, notes: [] };
}
