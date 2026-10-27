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
 * TASK 4 (the daily run). Every bed also gets a `.bantamkit/` and runs `status` (never ran, with
 * and without `BANTAMKIT_SKILL_AUDIT=off`), `daily` (the bytes of `skill-audit.json`), `status`
 * again, and `status` over a corrupt file, a wrong version and an error record. `report-full`
 * and `claude-full` also carry `surfaced` over (`resurface`, then `daily` a day later). The
 * `daily-trap` bed runs the Retention child in process (`child`) over a retention trap: with
 * `BANTAMKIT_RETENTION=off` and the audit on, every path and mtime under the bed is snapshotted
 * before and after, and the ONLY changes allowed are `retention.json`'s claim and
 * `skill-audit.json` (Amendment A3; J69-6's incident class — the most important case here).
 *
 * THE LITERALS. A change made on both sides alike (a 30-day window moved to 29, say) leaves
 * every differential green, so the counts, the spans, the adapter and the version choice are
 * pinned per side.
 */
import { createHash } from 'node:crypto';
import { chmodSync, lstatSync, mkdirSync, readFileSync, readdirSync, readlinkSync, rmSync, symlinkSync, unlinkSync, utimesSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'skill-host';
export const summary = 'skill audit host adapters: roots, enabled plugins, versions, 30-day Skill and typed-command counts';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'skillhost_ref.py');
const NOW = '2026-10-16T00:00:00.000Z';
const NOW_S = Date.parse(NOW) / 1000;
const DAY_S = 86_400;
const B = (s) => (Buffer.isBuffer(s) ? s : Buffer.from(s, 'utf8'));
const unb64 = (s) => (s === null ? null : Buffer.from(s, 'base64').toString('utf8'));
const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
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
    case 'daily-trap':
      return { cwd: 'proj', files: trapFiles() };
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

/** Task 4: a retention trap the sweep WOULD change: a ledger past its 7 days, a hook-log line past
 * 30, an idle usage log, a closed job 8 days old. With the sweep off none of it may move. */
function trapFiles() {
  const checkpoint = B(
    JSON.stringify(
      {
        version: 1,
        job: { id: 'closed8', goal: 'closed8', done_definition: 'd', constraints: [] },
        state: { repo: { branch: 'b', head_sha: 'h', dirty: false }, artifacts: [], external: [] },
        plan: { cursor: 'U1', units: [{ id: 'U1', title: 'u', brief_path: 'b1.md', status: 'done', role: 'implementer', depends_on: [], verify: 'true' }] },
        handoff: { next_action: 'x', open_questions: [], do_not: [], notes: '' },
        history: [],
        retro: [],
      },
      null,
      2,
    ),
  );
  const hook = B(
    `${JSON.stringify({ ts: '2026-08-01T10:00:00.000Z', ms: 1, event: 'SessionStart' })}\n` +
      `${JSON.stringify({ ts: '2026-10-15T10:00:00.000Z', ms: 1, event: 'SessionStart' })}\n`,
  );
  return [
    ['home/.claude/skills/solo/SKILL.md', B(skill('Use "x" now.')), 1],
    ['home/.claude/projects/p/s.jsonl', lines(use('t1', 'solo')), 1],
    ['home/.bantamkit/hooks/ledger-old.json', B('{"seen":{}}'), 8],
    ['home/.bantamkit/hooks/hook-log.jsonl', hook, 0],
    ['home/.bantamkit/usage/idle.jsonl', B('{"ts":"2026-09-10T00:00:00Z","fact":"g","kind":"seed"}\n'), 31],
    ['proj/.shiftwork/checkpoint-closed8.json', checkpoint, 8],
    ['proj/.shiftwork/briefs-closed8/U1.md', B('brief\n'), 8],
  ];
}

const REPORT_BEDS = ['report-full', 'report-young', 'report-mixed', 'report-minified', 'report-armed'];
const BEDS = ['claude-full', 'claude-young', 'two-shapes', 'no-settings', 'project-scope', ...(WIN ? [] : ['links']), 'null', ...REPORT_BEDS, 'daily-trap'];
const LATER = '2026-10-17T00:00:00.000Z';
const SAME_DAY = '2026-10-16T12:00:00.000Z';

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
  // ------------------------------------------------------------------ Task 4 ops
  mkdirSync(join(home, '.bantamkit'), { recursive: true });
  const state = join(home, '.bantamkit', 'skill-audit.json');
  const put = (text) => ({ op: 'put', path: state, data: b64(text) });
  const on = { BANTAMKIT_SKILL_AUDIT: null };
  const off = { BANTAMKIT_SKILL_AUDIT: 'off' };
  ops.push(
    { op: 'status', home, env: on, tag: 'status never ran' },
    { op: 'status', home, env: off, tag: 'status never ran, audit off' },
    { op: 'status', home, env: { BANTAMKIT_SKILL_AUDIT: null, BANTAMKIT_RETENTION: 'off' }, tag: 'status never ran, retention off' },
    { op: 'daily', ...at, tag: 'daily' },
    { op: 'status', home, env: on, tag: 'status ran' },
    { op: 'status', home, env: off, tag: 'status ran, audit off' },
  );
  if (label === 'report-full' || label === 'claude-full') {
    ops.push({ op: 'resurface', home, tag: 'resurface' }, { op: 'daily', home, cwd: cwdAbs, now: LATER, tag: 'daily carries surfaced' });
  }
  ops.push(
    put('not json'),
    { op: 'status', home, env: on, tag: 'status corrupt' },
    put('{"version": 2, "ts": "t", "host": "h", "surfaced": [], "error": "e"}'),
    { op: 'status', home, env: on, tag: 'status wrong version' },
    put('{"version": 1.0, "ts": "2026-10-16T00:00:00.000Z", "host": "claude-code", "surfaced": [], "error": "the gather failed"}'),
    { op: 'status', home, env: off, tag: 'status error record, audit off' },
    put('\ufeff{}'),
    { op: 'status', home, env: on, tag: 'status BOM' },
  );
  if (label === 'daily-trap') {
    const child = (tag, now, env, fresh) => ({ op: 'child', base, home, cwd: cwdAbs, now, env: { BANTAMKIT_INDEX_DIR: join(base, 'idx'), ...env }, fresh, tag });
    ops.push(
      child('child retention off, audit on', NOW, { BANTAMKIT_RETENTION: 'off', BANTAMKIT_SKILL_AUDIT: null }, 'both'),
      child('child again the same day', SAME_DAY, { BANTAMKIT_RETENTION: 'off', BANTAMKIT_SKILL_AUDIT: null }, 'audit'),
      child('child retention off, audit off', NOW, { BANTAMKIT_RETENTION: 'off', BANTAMKIT_SKILL_AUDIT: 'off' }, 'both'),
      child('child retention on, audit off', NOW, { BANTAMKIT_RETENTION: null, BANTAMKIT_SKILL_AUDIT: 'off' }, 'both'),
      child('child retention on, audit on', LATER, { BANTAMKIT_RETENTION: null, BANTAMKIT_SKILL_AUDIT: null }, 'both'),
    );
    // A3 (1): the hook spawns the child when EITHER switch is on. retention.json is stamped at
    // the wall clock first, so the word is `off` or `fresh` and no child is ever started.
    for (const [r, s] of [['off', 'off'], ['off', null], [null, 'off'], ['OFF', 'No']]) {
      ops.push({ op: 'spawn', home, env: { BANTAMKIT_RETENTION: r, BANTAMKIT_SKILL_AUDIT: s }, tag: `spawn retention=${r ?? 'on'} audit=${s ?? 'on'}` });
    }
  }
  const kept = settings === null ? null : { path: join(base, settings), bytes: files.find(([rel]) => rel === settings)[1] };
  return { ops, kept };
}

/** Every path under `base` → `<sha256|link target> <mtime ns>`, or `dir`: the `child` op's snapshot,
 * the same walk as the reference's `_snapshot`. Paths are ASCII here, so `<` is code-point order. */
const cmpCp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
function snapshot(base) {
  const out = new Map();
  const walk = (d) => {
    for (const n of readdirSync(d)) {
      const p = join(d, n);
      const st = lstatSync(p, { bigint: true });
      const rel = relative(base, p).split(sep).join('/');
      if (st.isSymbolicLink()) out.set(rel, `link ${readlinkSync(p)} ${st.mtimeNs}`);
      else if (st.isDirectory()) {
        out.set(rel, 'dir'); // a directory's mtime moves with any lock file; adds and removes show as paths
        walk(p);
      } else out.set(rel, `${createHash('sha256').update(readFileSync(p)).digest('hex')} ${st.mtimeNs}`);
    }
  };
  walk(base);
  return out;
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
  const RT = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'storage', 'retention.js')).href);
  const withEnv = (env, fn) => {
    const saved = Object.fromEntries(Object.keys(env ?? {}).map((k) => [k, process.env[k]]));
    try {
      for (const [k, v] of Object.entries(env ?? {})) {
        if (v === null) delete process.env[k];
        else process.env[k] = v;
      }
      return fn();
    } finally {
      for (const [k, v] of Object.entries(saved)) {
        if (v === undefined) delete process.env[k];
        else process.env[k] = v;
      }
    }
  };
  const readOr = (p) => {
    try {
      return readFileSync(p, 'utf8');
    } catch {
      return null;
    }
  };
  const task4 = (op) => {
    if (op.op === 'put') {
      mkdirSync(dirname(op.path), { recursive: true });
      writeFileSync(op.path, Buffer.from(op.data, 'base64'));
      return '';
    }
    if (op.op === 'resurface') {
      const rec = JSON.parse(readFileSync(R.statePath(op.home), 'utf8'));
      rec.surfaced = [...rec.findings.map((f) => R.surfaceKey(f)), 'gone\t\t'];
      writeFileSync(R.statePath(op.home), JSON.stringify(rec));
      return '';
    }
    if (op.op === 'daily') {
      R.daily(op.home, op.cwd, op.now);
      return readOr(R.statePath(op.home));
    }
    if (op.op === 'status') return withEnv(op.env, () => R.statusLine(op.home));
    if (op.op === 'spawn') {
      writeFileSync(RT.statePath(op.home), JSON.stringify({ ran_at: RT.nowStamp() }));
      return withEnv(op.env, () => RT.maybeSpawn(op.home, op.home));
    }
    // child
    const rm = (p) => {
      try {
        unlinkSync(p);
      } catch {
        /* absent */
      }
    };
    if (op.fresh === 'both' || op.fresh === 'audit') rm(R.statePath(op.home));
    if (op.fresh === 'both') rm(RT.statePath(op.home));
    const before = snapshot(op.base);
    withEnv(op.env, () => RT.childMain([op.cwd, op.home], op.now));
    const after = snapshot(op.base);
    const changed = [...new Set([...before.keys(), ...after.keys()])].filter((k) => before.get(k) !== after.get(k)).sort(cmpCp);
    return dumpIndex({ audit: readOr(R.statePath(op.home)), state: readOr(RT.statePath(op.home)), changed });
  };
  const nodeOne = (op) => {
    if (['put', 'resurface', 'daily', 'status', 'child', 'spawn'].includes(op.op)) return task4(op);
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
    const read = (o, s) =>
      s === null || o.op === 'put' || o.op === 'resurface'
        ? s
        : o.op === 'render' || o.op === 'status' || o.op === 'spawn'
          ? maskText(s)
          : JSON.parse(mask(s));
    answers[label] = { py: py.map((s, i) => read(ops[i], s)), nd: nd.map((s, i) => read(ops[i], s)), kept: { py: pyKept, nd: ndKept } };
    answers[label].tag = Object.fromEntries(ops.map((o, i) => [o.tag, i]).filter(([t]) => t !== undefined));
    ops.forEach((o, i) => {
      if (o.op === 'put') return;
      const what =
        o.tag !== undefined
          ? o.tag
          : o.op === 'usage'
          ? `usage known=${o.known === null ? 'null' : o.known.length}`
          : o.op === 'propose'
            ? `propose usage=${o.usage === null ? 'null' : 'measured'} span=${o.span_days}`
            : `${o.op}${o.no_usage ? ' no_usage' : ''}`;
      cases.push({ name: `${label} — ${what}`, kind: 'string', expected: py[i] ?? '<null>', actual: nd[i] ?? '<null>' });
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

  // ------------------------------------------------------------------- Task 4 literals
  const T = (bed, tag) => (a, side) => a[bed][side][a[bed].tag[tag]];
  literal('null: never ran, audit off, is exactly the off sentence', 'skill audit: off; never ran; usage adapter none', T('null', 'status never ran, audit off'));
  literal('null: retention off does NOT print the off prefix (A3: the prefix reads the audit switch)', 'skill audit: never ran; usage adapter none', T('null', 'status never ran, retention off'));
  literal(
    'report-full: the status line after the daily run',
    'skill audit: last ran 2026-10-16T00:00:00.000Z on claude-code; 6 skills, 97 catalogue bytes; findings 1 high, 0 medium, 5 low; usage over 30 days; 1 change proposed',
    T('report-full', 'status ran'),
  );
  literal('report-full: the daily record is the record op\'s record', true, (a, s) => JSON.stringify(T('report-full', 'daily')(a, s)) === JSON.stringify(a['report-full'][s][3]));
  literal('report-full: surfaced keeps every key still a finding, drops the gone one, sorted', true, (a, s) => {
    const r = T('report-full', 'daily carries surfaced')(a, s);
    const keys = r.findings.map((f) => `${f.kind}\t${f.skills.join(',')}\t${f.detail}`).sort(cmpCp);
    return keys.length > 0 && JSON.stringify(r.surfaced) === JSON.stringify(keys) && r.ts === LATER;
  });
  literal('claude-full: a corrupt record is unreadable', 'skill audit: the last record is unreadable; the next run recomputes it', T('claude-full', 'status corrupt'));
  literal('claude-full: a wrong version is unreadable', 'skill audit: the last record is unreadable; the next run recomputes it', T('claude-full', 'status wrong version'));
  literal('claude-full: an error record (version 1.0 reads as 1)', 'skill audit: off; last ran 2026-10-16T00:00:00.000Z; no report — the gather failed', T('claude-full', 'status error record, audit off'));
  literal('claude-full: a BOM is unreadable', 'skill audit: the last record is unreadable; the next run recomputes it', T('claude-full', 'status BOM'));
  literal('null: the daily record is the no-roots error record', { host: 'none', error: 'no skill directory was found for this host', surfaced: [] }, (a, s) => {
    const r = T('null', 'daily')(a, s);
    return { host: r.host, error: r.error, surfaced: r.surfaced };
  });
  // THE MOST IMPORTANT CASE (Amendment A3, J69-6's class): retention off, audit on — over a trap
  // the sweep would change, the child touches only the claim and the audit record.
  literal(
    'daily-trap: retention off, audit on changes ONLY retention.json\'s claim and skill-audit.json',
    { changed: ['home/.bantamkit/retention.json', 'home/.bantamkit/skill-audit.json'], state: `{"ran_at":"${NOW}"}\n`, audited: NOW },
    (a, s) => {
      const r = T('daily-trap', 'child retention off, audit on')(a, s);
      return { changed: r.changed, state: r.state, audited: r.audit === null ? null : JSON.parse(r.audit).ts };
    },
  );
  literal('daily-trap: a second child the same day neither audits nor sweeps (the claimed TTL)', { audit: null, changed: [] }, (a, s) => {
    const r = T('daily-trap', 'child again the same day')(a, s);
    return { audit: r.audit, changed: r.changed };
  });
  literal('daily-trap: both switches off — the child does nothing at all', { audit: null, state: null, changed: [] }, T('daily-trap', 'child retention off, audit off'));
  literal('daily-trap: retention on, audit off — the sweep runs, no audit record', { audit: null, deleted: true }, (a, s) => {
    const r = T('daily-trap', 'child retention on, audit off')(a, s);
    const st = r.state === null ? null : JSON.parse(r.state);
    return { audit: r.audit, deleted: st !== null && st.report.deleted.some((p) => p.split('\\').join('/').endsWith('home/.bantamkit/hooks/ledger-old.json')) };
  });
  literal(
    'daily-trap: the spawn stands down only when BOTH switches are off (A3)',
    ['off', 'fresh', 'fresh', 'off'],
    (a, s) => ['spawn retention=off audit=off', 'spawn retention=off audit=on', 'spawn retention=on audit=off', 'spawn retention=OFF audit=No'].map((t) => T('daily-trap', t)(a, s)),
  );
  literal('daily-trap: both on — the audit runs under the claimed stamp', LATER, (a, s) => {
    const r = T('daily-trap', 'child retention on, audit on')(a, s);
    return r.audit === null ? null : JSON.parse(r.audit).ts;
  });

  notes.push(`${BEDS.length} beds, both runtimes, over identical paths under ${join(ctx.scratch, 'skill-host')}`);
  return { cases, notes };
}
