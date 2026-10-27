/**
 * skill-host — the skill audit's host adapters and the transcript scan (#205 Task 2), Python
 * against Node.
 *
 * THE PROPERTY: over the same beds the two runtimes pick the same adapter, list the same skill
 * roots in the same order (`plugins, project, user`, Amendment A1), read the same switched-on
 * plugins and the file each won in, the same served version directories, and count the same
 * skill calls over the last 30 days: a `Skill` tool_use deduped by its `id`, a typed
 * `/<skill>` command record deduped by its `uuid` and counted only when it names a skill the
 * roots hold (Amendment A2), subagent transcripts walked, a file older than the cutoff not
 * read, an undecodable or unparseable candidate line skipped and counted.
 *
 * HOW. Every bed is built by `buildBed` at ONE absolute path under `ctx.scratch`, with mtimes
 * pinned relative to `NOW`, and rebuilt from nothing before each side — so a path in an answer
 * is the same string on both sides and is compared as it is. The reference runs the product's
 * `skillhost` (`ref/skillhost_ref.py`); the port runs `dist/skillhost.js` in process. Both
 * answers are the product's own serialisation (`hotindex.dumps` / `dumpIndex`).
 *
 * TASK 3 (`skillreport`). Every bed is also run through `record` and `render` (`run_live`, the
 * stored record and the report a person reads), and the `report-*` beds hold the disable
 * proposals: `report-full` proposes exactly `alpha@mk`, with the settings line located;
 * `report-young` spans 12 days (D2), `report-mixed` has one alpha skill called (D3),
 * `report-minified` cannot be located, `report-armed` holds `"alpha@mk": true` under another key
 * first, CRLF (D4). D1 (usage is null) is unobservable through `record` — `build_record` hands a
 * missing measurement a span of 0, which the span condition already refuses — so a `propose` op
 * shows it on its own at 30 days. `report-full` also switches on `"@"`, the id a personal skill
 * would group under, so the plugin-only grouping is reachable (D5). Each side's run must leave
 * every settings file byte-identical: K2, the report never edits it.
 *
 * THE LITERALS. A change made on both sides alike (a 30-day window moved to 29, say) leaves
 * every differential green, so the counts, the spans, the adapter and the version choice are
 * pinned per side.
 */
import { chmodSync, mkdirSync, readFileSync, rmSync, symlinkSync, utimesSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'skill-host';
export const summary = 'skill audit host adapters: roots, enabled plugins, versions, 30-day Skill and typed-command counts';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'skillhost_ref.py');
const NOW = '2026-10-16T00:00:00.000Z';
const NOW_S = Date.parse(NOW) / 1000;
const DAY_S = 86_400;
const B = (s) => (Buffer.isBuffer(s) ? s : Buffer.from(s, 'utf8'));
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');
const WIN = process.platform === 'win32';
const ROOT = typeof process.getuid === 'function' && process.getuid() === 0;

const use = (id, skill, ts = '2026-10-15T00:00:00.000Z') => {
  const block = { type: 'tool_use', name: 'Skill', input: { skill } };
  if (id !== null) block.id = id;
  return JSON.stringify({ timestamp: ts, message: { content: [block] } });
};
const typed = (cmd, uuid = null, extra = {}) => {
  const rec = {
    type: 'user',
    timestamp: '2026-10-15T00:00:00.000Z',
    message: { role: 'user', content: `<command-name>/${cmd}</command-name>\n<command-message>${cmd}</command-message>\n<command-args></command-args>` },
    ...extra,
  };
  if (uuid !== null) rec.uuid = uuid;
  return JSON.stringify(rec);
};
const lines = (...xs) => Buffer.concat(xs.map((x) => Buffer.concat([B(x), B('\n')])));
const skill = (desc) => `---\ndescription: ${desc}\n---\nbody\n`;

/** [relative path, bytes, age in days] per bed; `cwd` relative to the bed or null. */
function bedFiles(label) {
  const plugins = [
    ['home/.claude/plugins/cache/mk/alpha/1.0.0/skills/a1/SKILL.md', skill('Use when you "deploy the thing" now.')],
    ['home/.claude/plugins/cache/mk/alpha/1.0.0/skills/a2/SKILL.md', skill('Alpha two.')],
    ['home/.claude/plugins/cache/mk/beta/1.0.0/skills/b1/SKILL.md', skill('Beta one.')],
    ['home/.claude/plugins/cache/mk/beta/1.0.0/skills/b2/SKILL.md', skill('Also "deploy the thing" here.')],
    ['home/.claude/plugins/cache/mk/gamma/1.0.0/skills/g1/SKILL.md', skill('Gamma one.')],
  ].map(([p, d]) => [p, B(d), 1]);
  const P = 'home/.claude/projects';
  switch (label) {
    case 'claude-full':
      return {
        cwd: 'proj',
        files: [
          ...plugins,
          ['home/.claude/skills/solo/SKILL.md', B(skill('Solo.')), 1],
          ['proj/.claude/skills/proj/SKILL.md', B(skill('Project.')), 1],
          ['home/.claude/settings.json', B(JSON.stringify({ enabledPlugins: { 'alpha@mk': true, 'beta@mk': true, 'gamma@mk': false } }, null, 2)), 1],
          [
            `${P}/p1/s1.jsonl`,
            lines(
              use('t1', 'beta:b1'),
              use(null, 'solo'),
              use('t3', 'alpha:a1', '2026-09-01T00:00:00.000Z'),
              '{"bad "Skill" "tool_use"',
              Buffer.concat([Buffer.from([0xff]), B(' "Skill" "tool_use"')]),
              '{"text": "Skill without the block type"}',
              // Valid JSON once a lossy decoder repairs the 0xff; refused by a strict one.
              Buffer.concat([
                B('{"timestamp":"2026-10-15T00:00:00.000Z","message":{"content":[{"type":"tool_use","name":"Skill","id":"t7","input":{"skill":"bad'),
                Buffer.from([0xff]),
                B('"}}]}}'),
              ]),
              use('t6', 'solo'),
              JSON.stringify({ timestamp: '2026-10-15T00:00:00.000Z', message: { content: [{ type: 'tool_use', name: 'Skill', id: 't5', input: { skill: 7 } }] } }),
              // Amendment A2: a typed skill, a built-in, its expansion record, the tag as text.
              typed('alpha:a1', 'u1'),
              typed('clear', 'u0'),
              typed('solo', 'u2', { isMeta: true }),
              JSON.stringify({
                type: 'user',
                timestamp: '2026-10-15T00:00:00.000Z',
                message: { role: 'user', content: [{ type: 'tool_result', content: '<command-name>/solo</command-name>' }] },
              }),
            ),
            1,
          ],
          [`${P}/p1/s2.jsonl`, lines(use('t1', 'beta:b1'), use(null, 'solo'), typed('alpha:a1', 'u1'), typed('proj')), 1],
          [`${P}/p1/s1/subagents/agent-a.jsonl`, lines(use('t4', 'beta:b1')), 1],
          [`${P}/p2/old.jsonl`, lines(use('t9', 'alpha:a2')), 40],
          [`${P}/p3/unreadable.jsonl`, lines(use('t8', 'solo')), 1, 'unreadable'],
        ],
      };
    case 'claude-young':
      return { cwd: null, files: [[`${P}/p/s.jsonl`, lines(use('t1', 'x', '2026-10-04T00:00:00.000Z')), 0]] };
    case 'two-shapes':
      return {
        cwd: null,
        files: [
          ...plugins,
          ['home/.claude/skills/solo/SKILL.md', B(skill('Solo.')), 1],
          [`${P}/p/s.jsonl`, lines(use('t1', 'solo'), typed('alpha:a1', 'u1')), 1],
        ],
      };
    case 'no-settings':
      return { cwd: 'proj', files: [plugins[0]] };
    case 'project-scope':
      return {
        cwd: 'proj',
        files: [
          plugins[0],
          ['home/.claude/settings.json', B(JSON.stringify({ enabledPlugins: { 'alpha@mk': true, 'beta@mk': true, 'delta@mk': 'yes' } })), 1],
          // A BOM before the JSON: skipped on both sides, so zeta is never switched on.
          ['proj/.claude/settings.json', Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), B(JSON.stringify({ enabledPlugins: { 'zeta@mk': true } }))]), 1],
          ['proj/.claude/settings.local.json', B(JSON.stringify({ enabledPlugins: { 'beta@mk': false, 'gamma@mk': true } })), 1],
          ['home/.claude/plugins/installed_plugins.json', null, 1, 'installed'],
        ],
      };
    case 'links':
      return {
        cwd: null,
        files: [
          ['home/.claude/skills/solo/SKILL.md', B(skill('Solo.')), 1],
          ['outside/dir/x.jsonl', lines(use('t1', 'solo')), 1],
          ['outside/y.jsonl', lines(use('t2', 'solo')), 1],
        ],
        links: [
          ['home/.claude/projects/linked-dir', 'outside/dir'],
          ['home/.claude/projects/p/linked.jsonl', 'outside/y.jsonl'],
        ],
      };
    case 'report-full':
    case 'report-young':
    case 'report-mixed':
    case 'report-minified':
    case 'report-armed':
      return reportBed(label, plugins, P);
    case 'null':
      return { cwd: null, files: [['home/.keep', B(''), 1]] };
    default:
      throw new Error(label);
  }
}

/** Task 3's beds: proposals, each diff condition on its own, and where the settings line is. */
function reportBed(label, plugins, P) {
  const enabled = { 'alpha@mk': true, 'beta@mk': true, 'gamma@mk': false, '@': true };
  let settings = B(JSON.stringify({ enabledPlugins: enabled }, null, 2));
  if (label === 'report-minified') settings = B(JSON.stringify({ enabledPlugins: enabled }));
  if (label === 'report-armed') {
    settings = B(
      '{\r\n  "otherPlugins": {\r\n    "alpha@mk": true\r\n  },\r\n' +
        '  "enabledPlugins": {\r\n    "alpha@mk" : true ,\r\n    "beta@mk": true\r\n  }\r\n}\r\n',
    );
  }
  const recent =
    label === 'report-young'
      ? [use('t1', 'beta:b1', '2026-10-04T00:00:00.000Z')]
      : label === 'report-mixed'
        ? [use('t1', 'beta:b1'), use('t2', 'alpha:a2')]
        : [use('t1', 'beta:b1')];
  const files = [
    ...plugins,
    ['home/.claude/skills/solo/SKILL.md', B(skill('Solo.')), 1],
    ['proj/.claude/skills/proj/SKILL.md', B(skill('Project.')), 1],
    ['home/.claude/settings.json', settings, 1],
    [`${P}/p1/s.jsonl`, lines(...recent), 0],
  ];
  // A file last written 40 days ago is not read, but proves the transcripts reach back 30 days.
  if (label !== 'report-young') files.push([`${P}/p2/old.jsonl`, lines(use('t9', 'alpha:a1', '2026-09-06T00:00:00.000Z')), 40]);
  return { cwd: 'proj', files, settings: 'home/.claude/settings.json' };
}

const REPORT_BEDS = ['report-full', 'report-young', 'report-mixed', 'report-minified', 'report-armed'];
const BEDS = ['claude-full', 'claude-young', 'two-shapes', 'no-settings', 'project-scope', ...(WIN ? [] : ['links']), 'null', ...REPORT_BEDS];

function buildBed(base, label) {
  rmSync(base, { recursive: true, force: true });
  const { cwd, files, links = [], settings = null } = bedFiles(label);
  const cwdAbs = cwd === null ? null : join(base, cwd);
  if (cwdAbs !== null) mkdirSync(cwdAbs, { recursive: true });
  for (const [rel, data0, age, special] of files) {
    const p = join(base, rel);
    mkdirSync(dirname(p), { recursive: true });
    let data = data0;
    if (special === 'installed') {
      data = B(
        JSON.stringify({
          version: 2,
          plugins: {
            'alpha@mk': [
              { scope: 'user', installPath: join(base, 'home/.claude/plugins/cache/mk/alpha/1.0.0') },
              { scope: 'project', projectPath: join(base, 'elsewhere'), installPath: '/x/mk/alpha/9.9.9' },
              { scope: 'project', projectPath: cwdAbs, installPath: '/x/mk/alpha/2.0.0/' },
            ],
            'beta@mk': { scope: 'user', installPath: 'C:\\x\\mk\\beta\\3.1.0\\' },
            'gamma@mk': [],
            'delta@mk': 'not a list',
            'eps@mk': [{ scope: 'project', projectPath: cwdAbs, installPath: 5 }, { scope: 'local', installPath: '/x/mk/eps/0.1.0' }],
          },
        }),
      );
    }
    writeFileSync(p, data);
    const when = NOW_S - Math.trunc(age * DAY_S);
    utimesSync(p, when, when);
    // platform-checked: `0o000` denies nothing on Windows (or to root), and this suite knows it:
    // the chmod is skipped there and the one literal that depends on it is not pinned (a note says so).
    if (special === 'unreadable' && !WIN && !ROOT) chmodSync(p, 0o000);
  }
  for (const [rel, target] of links) {
    mkdirSync(dirname(join(base, rel)), { recursive: true });
    symlinkSync(join(base, target), join(base, rel));
  }
  const home = join(base, 'home');
  const at = { home, cwd: cwdAbs, now: NOW };
  const ops = [
    { op: 'gather', ...at },
    { op: 'usage', projects: join(home, '.claude', 'projects'), now: NOW, known: null },
    { op: 'usage', projects: join(home, '.claude', 'projects'), now: NOW, known: ['alpha:a1', 'proj', 'solo'] },
    { op: 'record', ...at },
    { op: 'render', ...at },
  ];
  if (label === 'report-full') {
    ops.push(
      { op: 'record', ...at, no_usage: true },
      { op: 'render', ...at, no_usage: true },
      { op: 'propose', ...at, usage: null, span_days: 30 },
      { op: 'propose', ...at, usage: {}, span_days: 30 },
    );
  }
  const kept = settings === null ? null : { path: join(base, settings), bytes: files.find(([rel]) => rel === settings)[1] };
  return { ops, kept };
}

/** Whether a side left the bed's settings file byte-identical (K2: the report never edits it). */
const untouched = (kept) => {
  if (kept === null) return 'no settings file in this bed';
  try {
    return readFileSync(kept.path).equals(kept.bytes) ? 'byte-identical' : 'CHANGED';
  } catch {
    return 'GONE';
  }
};

/** chmod back, so the harness can remove the scratch. platform-checked: restoring `0o644` is a no-op
 * wherever the `0o000` above was skipped (win32, root), so it needs no platform branch. */
function release(base) {
  try {
    chmodSync(join(base, 'home/.claude/projects/p3/unreadable.jsonl'), 0o644);
  } catch {
    /* not in this bed */
  }
}

export async function run(ctx) {
  const H = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'skillhost.js')).href);
  const { dumpIndex } = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'storage', 'hotindex.js')).href);
  const { parseNow } = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'storage', 'retention.js')).href);
  const R = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'skillreport.js')).href);
  const { scanRoots } = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'skillaudit.js')).href);
  const nodeOne = (op) => {
    const now = parseNow(op.now);
    if (op.op === 'usage') return dumpIndex(H.countSkillUsage(op.projects, now, H.USAGE_DAYS, op.known === null ? null : new Set(op.known)).summary());
    if (op.op === 'record' || op.op === 'render') {
      let rec;
      if (op.no_usage) {
        const g = H.selectAdapter(op.home).gather(op.home, op.cwd, now);
        rec = R.buildRecord(new H.Gathered(g.host, g.roots, g.enabled, g.versions, g.sources, null), op.now);
      } else {
        rec = R.runLive(op.home, op.cwd, op.now);
      }
      return op.op === 'record' ? dumpIndex(rec) : R.renderReport(rec);
    }
    if (op.op === 'propose') {
      const g = H.selectAdapter(op.home).gather(op.home, op.cwd, now);
      const versions = g.versions === null ? null : new Map(Object.entries(g.versions));
      const found = scanRoots(g.roots.map(([label, path]) => ({ label, path })), [...g.enabled], versions);
      const usage = op.usage === null ? null : new Map(Object.entries(op.usage));
      return dumpIndex(R.propose(found, usage, op.span_days, g.sources));
    }
    return dumpIndex(H.selectAdapter(op.home).gather(op.home, op.cwd, now).asDict());
  };

  const cases = [];
  const notes = [];
  const answers = {};
  for (const label of BEDS) {
    const base = join(ctx.scratch, 'skill-host', label);
    const { ops, kept } = buildBed(base, label);
    const py = ctx.runPython(REF, { ops }).answers.map(unb64);
    const pyKept = untouched(kept);
    release(base);
    buildBed(base, label);
    let nd;
    try {
      nd = ops.map(nodeOne);
    } finally {
      release(base);
    }
    const ndKept = untouched(kept);
    // The bed's path as it appears inside a JSON string (backslashes escaped on win32); a
    // rendered report holds it raw, with `/` as the separator so the literals read one way.
    const mask = (s) => s.split(JSON.stringify(base).slice(1, -1)).join('<BED>');
    const maskText = (s) => s.split(base).join('<BED>').split('\\').join('/');
    const read = (o, s) => (o.op === 'render' ? maskText(s) : JSON.parse(mask(s)));
    answers[label] = { py: py.map((s, i) => read(ops[i], s)), nd: nd.map((s, i) => read(ops[i], s)), kept: { py: pyKept, nd: ndKept } };
    ops.forEach((o, i) => {
      const what =
        o.op === 'usage'
          ? `usage known=${o.known === null ? 'null' : o.known.length}`
          : o.op === 'propose'
            ? `propose usage=${o.usage === null ? 'null' : 'measured'} span=${o.span_days}`
            : `${o.op}${o.no_usage ? ' no_usage' : ''}`;
      cases.push({ name: `${label} — ${what}`, kind: 'string', expected: py[i], actual: nd[i] });
    });
  }

  // ------------------------------------------------------------------- the literals
  const literal = (label, expected, get) => {
    for (const side of ['py', 'nd']) {
      cases.push({ name: `LITERAL: ${label} — ${side === 'py' ? 'python' : 'node'}`, kind: 'json', expected, actual: get(answers, side) });
    }
  };
  const A = (bed, i) => (a, side) => a[bed][side][i];
  literal('claude-full Skill tool_use counts (dedupe by id, subagents, a numeric skill ignored)', { 'beta:b1': 2, solo: 3 }, (a, s) => A('claude-full', 1)(a, s).counts);
  literal(
    'claude-full gather counts (A2: typed /alpha:a1 deduped by uuid, typed /proj, /clear and the meta record not counted)',
    { 'alpha:a1': 1, 'beta:b1': 2, proj: 1, solo: 3 },
    (a, s) => A('claude-full', 0)(a, s).usage.counts,
  );
  literal(
    'claude-full transcripts read, lines skipped, span',
    { transcripts: 3, skipped_lines: 3, span_days: 30 },
    (a, s) => {
      const u = A('claude-full', 1)(a, s);
      return { transcripts: u.transcripts, skipped_lines: u.skipped_lines, span_days: u.span_days };
    },
  );
  literal('claude-full roots in order plugins, project, user', ['plugins', 'project', 'user'], (a, s) => A('claude-full', 0)(a, s).roots.map(([l]) => l));
  literal('claude-full enabled and the file each won in', [['alpha@mk', 'beta@mk'], { 'alpha@mk': '<BED>/home/.claude/settings.json', 'beta@mk': '<BED>/home/.claude/settings.json' }], (a, s) => {
    const g = A('claude-full', 0)(a, s);
    return [g.enabled, Object.fromEntries(Object.entries(g.sources).map(([k, v]) => [k, v.split('\\').join('/')]))];
  });
  literal('claude-young span_days', 12, (a, s) => A('claude-young', 0)(a, s).usage.span_days);
  literal('two-shapes: one Skill tool_use and one typed /alpha:a1 are 2 calls', { calls: 2, counts: { 'alpha:a1': 1, solo: 1 } }, (a, s) => {
    const u = A('two-shapes', 0)(a, s).usage;
    return { calls: u.calls, counts: u.counts };
  });
  literal('no-settings: nothing enabled, no versions', { enabled: [], sources: {}, versions: null }, (a, s) => {
    const g = A('no-settings', 0)(a, s);
    return { enabled: g.enabled, sources: g.sources, versions: g.versions };
  });
  literal(
    'project-scope: the project install for this cwd wins; a BOM settings file is skipped; local overrides user',
    { enabled: ['alpha@mk', 'gamma@mk'], versions: { 'alpha@mk': '2.0.0', 'beta@mk': '3.1.0', 'eps@mk': '0.1.0' } },
    (a, s) => {
      const g = A('project-scope', 0)(a, s);
      return { enabled: g.enabled, versions: g.versions };
    },
  );
  if (!WIN) {
    literal('links: a symlinked transcript FILE is read, a symlinked DIRECTORY is not walked', { counts: { solo: 1 }, transcripts: 1 }, (a, s) => {
      const u = A('links', 0)(a, s).usage;
      return { counts: u.counts, transcripts: u.transcripts };
    });
  } else {
    notes.push('links bed skipped on win32: a file symlink needs a privilege the runner may lack');
  }
  literal('null: host none, usage null, no roots', { host: 'none', usage: null, roots: [] }, (a, s) => {
    const g = A('null', 0)(a, s);
    return { host: g.host, usage: g.usage, roots: g.roots };
  });
  if (WIN || ROOT) notes.push('unreadable.jsonl not made unreadable (win32 or root): its unreadable count is not pinned');
  else {
    literal('claude-full a mode-000 transcript is unreadable, not a transcript', 1, (a, s) => A('claude-full', 1)(a, s).unreadable);
  }
  // ------------------------------------------------------------------- Task 3 literals
  const R3 = (bed) => (a, side) => a[bed][side][3];
  const T3 = (bed) => (a, side) => a[bed][side][4];
  literal('report-full proposes exactly alpha@mk (beta called, gamma off, "@" holds no plugin skill)', ['alpha@mk'], (a, s) => R3('report-full')(a, s).proposals.map((p) => p.plugin));
  literal(
    'report-full render holds exactly the five diff lines',
    ['--- <BED>/home/.claude/settings.json', '+++ <BED>/home/.claude/settings.json', '@@ -3 +3 @@', '-    "alpha@mk": true,', '+    "alpha@mk": false,'],
    (a, s) => T3('report-full')(a, s).split('\n').filter((l) => /^(--- |\+\+\+ |@@ |-    |\+    )/.test(l)),
  );
  literal('report-full render says the change is NOT applied', true, (a, s) => T3('report-full')(a, s).includes('proposed change — NOT applied; bantamkit never edits settings.json:'));
  literal('report-young render ends with the span sentence (D2)', true, (a, s) => T3('report-young')(a, s).endsWith('proposed change: none — the transcripts span 12 days; a change needs 30'));
  literal('report-young: 12 days of transcripts propose nothing (D2)', [], (a, s) => R3('report-young')(a, s).proposals);
  literal('report-mixed: one called alpha skill keeps alpha, one called beta skill keeps beta (D3)', [], (a, s) => R3('report-mixed')(a, s).proposals);
  literal('report-minified: not located, the hand-edit sentence instead', [[null], true], (a, s) => [
    R3('report-minified')(a, s).proposals.map((p) => p.line),
    T3('report-minified')(a, s).includes('set enabledPlugins["alpha@mk"] to false in <BED>/home/.claude/settings.json (the line could not be located)'),
  ]);
  literal('report-armed: the line inside enabledPlugins, not the earlier one (D4)', [6, '    "alpha@mk" : false ,'], (a, s) => {
    const p = R3('report-armed')(a, s).proposals[0];
    return p === undefined ? 'no proposal' : [p.line, p.after];
  });
  literal('report-full no_usage: no proposal, the no-adapter sentence (D1 through record)', [[], true], (a, s) => [
    a['report-full'][s][5].proposals,
    a['report-full'][s][6].endsWith('proposed change: none — this host has no usage adapter, so no skill is called never-invoked and nothing is proposed'),
  ]);
  literal('report-full propose: usage null at 30 days proposes nothing (D1 on its own)', [], (a, s) => a['report-full'][s][7]);
  literal('report-full propose: an empty measurement at 30 days proposes every enabled plugin', ['alpha@mk', 'beta@mk'], (a, s) => a['report-full'][s][8].map((p) => p.plugin));
  literal(
    'null render is the could-not-run sentence',
    'skill audit — could not run: no skill directory was found for this host. The `skill_audit` tool still audits any directory you name as `root`.',
    (a, s) => T3('null')(a, s),
  );
  literal('claude-young: a claude-code home with no skill directory is the no-roots error record', { host: 'claude-code', error: 'no skill directory was found for this host' }, (a, s) => {
    const r = R3('claude-young')(a, s);
    return { host: r.host, error: r.error };
  });
  for (const label of REPORT_BEDS) {
    literal(`${label}: settings.json byte-identical after the run (K2)`, 'byte-identical', (a, s) => a[label].kept[s]);
  }

  notes.push(`${BEDS.length} beds, both runtimes, over identical paths under ${join(ctx.scratch, 'skill-host')}`);
  return { cases, notes };
}
