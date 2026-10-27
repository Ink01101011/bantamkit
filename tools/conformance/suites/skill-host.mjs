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
 * THE LITERALS. A change made on both sides alike (a 30-day window moved to 29, say) leaves
 * every differential green, so the counts, the spans, the adapter and the version choice are
 * pinned per side.
 */
import { chmodSync, mkdirSync, rmSync, symlinkSync, utimesSync, writeFileSync } from 'node:fs';
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
    case 'null':
      return { cwd: null, files: [['home/.keep', B(''), 1]] };
    default:
      throw new Error(label);
  }
}

const BEDS = ['claude-full', 'claude-young', 'two-shapes', 'no-settings', 'project-scope', ...(WIN ? [] : ['links']), 'null'];

function buildBed(base, label) {
  rmSync(base, { recursive: true, force: true });
  const { cwd, files, links = [] } = bedFiles(label);
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
  return {
    ops: [
      { op: 'gather', home, cwd: cwdAbs, now: NOW },
      { op: 'usage', projects: join(home, '.claude', 'projects'), now: NOW, known: null },
      { op: 'usage', projects: join(home, '.claude', 'projects'), now: NOW, known: ['alpha:a1', 'proj', 'solo'] },
    ],
  };
}

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
  const nodeOne = (op) => {
    const now = parseNow(op.now);
    if (op.op === 'usage') return dumpIndex(H.countSkillUsage(op.projects, now, H.USAGE_DAYS, op.known === null ? null : new Set(op.known)).summary());
    return dumpIndex(H.selectAdapter(op.home).gather(op.home, op.cwd, now).asDict());
  };

  const cases = [];
  const notes = [];
  const answers = {};
  for (const label of BEDS) {
    const base = join(ctx.scratch, 'skill-host', label);
    const { ops } = buildBed(base, label);
    const py = ctx.runPython(REF, { ops }).answers.map(unb64);
    release(base);
    buildBed(base, label);
    let nd;
    try {
      nd = ops.map(nodeOne);
    } finally {
      release(base);
    }
    // The bed's path as it appears inside a JSON string (backslashes escaped on win32).
    const mask = (s) => s.split(JSON.stringify(base).slice(1, -1)).join('<BED>');
    answers[label] = { py: py.map((s) => JSON.parse(mask(s))), nd: nd.map((s) => JSON.parse(mask(s))) };
    ops.forEach((o, i) => {
      const what = o.op === 'usage' ? `usage known=${o.known === null ? 'null' : o.known.length}` : 'gather';
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
  notes.push(`${BEDS.length} beds, both runtimes, over identical paths under ${join(ctx.scratch, 'skill-host')}`);
  return { cases, notes };
}
