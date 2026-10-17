/**
 * touch-context — `w_context` in the ranker and the via admission path (#200, Task 5; job70
 * T200-5).
 *
 * THE PROPERTY: over the same touch rows, graph and clock the two runtimes give the same window
 * (this session's read/edit/write paths in its last `TOUCH_WINDOW` = 20 tool calls, newest
 * first), the same per-fact context (1.0 on a strong edge, else `CONTEXT_WEAK_SHARE` times the
 * decayed weak co-use count, capped at 1.0), the same via pick (strong edges only, the first
 * window path that has one, its heaviest fact, ties by name) and label (` [via <shortest
 * unique suffix>]`), and the same `weight_of` for every `ctx` (clamped into `[0, 1]`, NaN is
 * none). And the hook, two processes per side over one git bed with `BANTAMKIT_VIA=on`,
 * prints the same UserPromptSubmit bytes: the via line after the gated hits when a strong
 * edge is in the window, nothing extra when the edit is 21 calls back, when the only edge is
 * weak, more than one line never, a via fact already shown suppressed by the seen-set, and
 * outside a repo stdout as before #200.
 *
 * HOW. One payload to `ref/touch_ref.py` (`run_context`), the same calls in-process against
 * `dist/touch/context.js` and `dist/memory/retrieval.js` (`setContextWeight` for the ref's
 * in-process `W_CONTEXT` assignment; `setViaOn` for its `VIA_ON`). The hook beds are built
 * by this harness with one script per side; each run's exit, stdout and stderr is compared,
 * and so is each UserPromptSubmit log record with `ts`/`ms` removed (it carries `context`, the
 * count of facts with context, and `via`).
 *
 * THE LITERALS. A change made to both sides leaves every differential green, so two answers
 * are pinned per side: the via line bytes of the first bed, and `via_pick` of the unit test's
 * fixture, `["fb", "src/a.py"]`.
 */
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'touch-context';
export const summary =
  'touch context: window (last 20 calls), context_weights (strong 1.0, weak decayed and capped), via_pick/via_label, weight_of ctx clamp, BANTAMKIT_VIA; hook UserPromptSubmit bytes with the [via <file>] line';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'touch_ref.py');
const CLI_REF = join(here, 'ref', 'cli_ref.py');
const SCRUBBED = ['BANTAMKIT_MEMORY_DIR', 'CLAUDE_COWORK_MEMORY_PATH_OVERRIDE', 'TOOL_METRICS_DIR', 'BANTAMKIT_DREAM_TIMEOUT_MS', 'BANTAMKIT_ASSETS', 'BANTAMKIT_VIA'];
const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');

// ----------------------------------------------------------------------- module fixtures

const G = {
  files: ['src/a.py', 'src/b.py', 'docs/x.md'],
  strong: { 'src/a.py': [['fa', null], ['fb', null]], 'docs/x.md': [['fx', null]] },
  weak: { 'src/b.py': { fw: ['2026-10-16T00:00:00Z', '2026-10-02T00:00:00Z'] } },
};
const NOW = '2026-10-16T00:00:00Z';
const row = (seq, path, op = 'edit', extra = {}) => ({ ts: NOW, session: 's', seq, op, path, ...extra });

/** [tag, [rows, seqNow]] */
const WINDOWS = [
  ['the unit test fixture', [[row(1, 'docs/x.md'), row(25, 'src/a.py'), row(30, 'src/b.py', 'read'), row(31, 'src/a.py')], 31]],
  ['the boundary seq_now - 20: 11 in, 10 out', [[row(11, 'in.py'), row(10, 'out.py')], 30]],
  ['uses and folded lines are not touches', [[{ seq: 12, op: 'use', fact: 'f' }, row(13, 'folded.py', 'folded'), row(14, 'w.py', 'write')], 20]],
  ['equal seqs keep log order; a repeat is listed once', [[row(5, 'b.py'), row(5, 'a.py'), row(4, 'b.py'), row(6, 'c.py', 'read')], 6]],
  ['malformed seq and path are skipped; an integral float seq counts', [[row('7', 'str.py'), row(true, 'bool.py'), row(2.5, 'half.py'), row(3.0, 'float.py'), { seq: 3, op: 'edit', path: 9 }], 10]],
  ['empty', [[], 0]],
];

const decay = { files: ['p'], strong: {}, weak: { p: { d0: ['2026-10-16T00:00:00Z'], d14: ['2026-10-02T00:00:00Z'], d28: ['2026-09-18T00:00:00Z'], future: ['2026-10-20T00:00:00Z'] } } };
const many = { files: ['p'], strong: {}, weak: { p: { many: Array.from({ length: 9 }, (_, i) => `2026-10-1${i % 7}T00:00:00Z`), two: ['2026-10-16T00:00:00Z'] } } };
const both = {
  files: ['p', 'q'],
  strong: { p: [['both', null]], __proto__x: [['nope', null]] },
  weak: { p: { both: ['2026-10-16T00:00:00Z'], bad: ['not-a-stamp', '2026-10-16T00:00:00Z'] }, q: { q1: ['2026-10-09T00:00:00Z'] } }, // `both`'s weak share is 0.5, not 1.0: a weak-wins side answers 0.5
};

/** [tag, [graph, paths, now]] */
const WEIGHTS = [
  ['the unit test fixture', [G, ['src/a.py', 'src/b.py'], NOW]],
  ['decay at 0, 14 and 28 days; a future stamp is age 0', [decay, ['p'], NOW]],
  ['the cap at 1.0 with many weak stamps', [many, ['p'], NOW]],
  ['a strong and a weak edge: strong wins; a bad stamp is skipped; two paths sum', [both, ['p', 'q'], NOW]],
  ['a path outside the graph', [G, ['nowhere.py', '__proto__'], NOW]],
  ['no paths', [G, [], NOW]],
];

const ties = { files: ['a/x.py', 'b/x.py', 'y.py'], strong: { 'a/x.py': [['zz', null], ['mm', 'f'], ['aa', null]], 'y.py': [['yy', null]] }, weak: { 'b/x.py': { heavy: [NOW] } } };

/** [tag, [graph, paths, exclude, weights]] */
const PICKS = [
  ['the unit test fixture: the weak fw never admits', [G, ['src/b.py', 'src/a.py'], [], { fa: 1.1, fb: 1.3, fw: 9.0, fx: 9.0 }]],
  ['exclude takes the heavier', [G, ['src/a.py'], ['fb'], { fa: 1.1, fb: 1.3 }]],
  ['an exclude that empties the first path: the second answers', [G, ['src/a.py', 'docs/x.md'], ['fa', 'fb'], { fa: 1.1, fb: 1.3, fx: 0.2 }]],
  ['a fact no layer holds is passed over', [G, ['src/a.py'], [], { fb: 0.5 }]],
  ['ties by name', [ties, ['a/x.py'], [], { zz: 1.0, mm: 1.0, aa: 1.0 }]],
  ['the first path wins over a heavier later one', [ties, ['y.py', 'a/x.py'], [], { yy: 0.1, zz: 9.0 }]],
  ['nothing in the window', [G, [], [], { fa: 1.0 }]],
  ['nothing weighs', [G, ['src/a.py', 'docs/x.md'], [], {}]],
];
const PICK_LITERAL = ['fb', 'src/a.py'];

const LABELS = [
  ['src/a.py', G],
  ['a/x.py', ties],
  ['y.py', ties],
  ['docs/x.md', { files: ['docs/x.md', 'x.md'], strong: {}, weak: {} }],
];

const WEIGHT_OF = {
  w_context: 0.5,
  cases: [0, 0.5, 1, 7, -1, 'nan'].flatMap((c) => [
    ['project', false, 0, c],
    ['feedback', true, 2, c],
    ['other', false, 'nan', c],
  ]),
};
const SWITCH = [
  [null, false],
  [null, true],
  ['on', false],
  ['off', true],
  ['yes', false],
  ['yes', true],
  ['', true],
  ['ON', false],
];

// ----------------------------------------------------------------------------- hook beds

const PROMPT = 'explain the gateway rollout plan please';
const VIA_LINE = '[project] [fa] (project) notes about src/a.py [via a.py]';

function git(cwd, ...a) {
  execFileSync('git', ['-c', 'user.email=t@t', '-c', 'user.name=t', '-c', 'commit.gpgsign=false', '-C', cwd, ...a], {
    stdio: 'pipe',
    env: { ...process.env, GIT_CONFIG_NOSYSTEM: '1', LC_ALL: 'C' },
  });
}

function factFile(store, nm, desc, body) {
  const d = join(store, 'facts');
  mkdirSync(d, { recursive: true });
  writeFileSync(join(d, `${nm}.md`), `---\nname: ${nm}\ndescription: ${desc}\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\nlinks: []\n---\n\n${body}\n`);
}

const FACTS = {
  fa: 'notes about src/a.py',
  fb: 'more about src/a.py',
  fw: 'a weak only memory',
  'gate-fact': 'gateway rollout plan details',
};

/** One bed per side: the same script, so every repo-relative answer is the same. */
function buildBed(root, b) {
  rmSync(root, { recursive: true, force: true });
  const home = join(root, 'home');
  const R = join(root, 'repo');
  mkdirSync(home, { recursive: true });
  mkdirSync(join(R, 'src'), { recursive: true });
  writeFileSync(join(R, 'src', 'a.py'), 'a\n');
  writeFileSync(join(R, 'src', 'b.py'), 'b\n');
  if (b.repo) {
    git(R, 'init', '-q');
    git(R, 'add', 'src');
    git(R, 'commit', '-qm', 'one');
  }
  const store = join(R, '.bantamkit', 'memory');
  for (const nm of b.facts) factFile(store, nm, FACTS[nm], 'body text');
  return { home: realpathSync.native(home), R: realpathSync.native(R) };
}

const p = (R, extra) => ({ session_id: 's1', cwd: R, ...extra });
const editA = (R) => p(R, { hook_event_name: 'PostToolUse', tool_name: 'Edit', tool_input: { file_path: join(R, 'src', 'a.py') } });
const bash = (R) => p(R, { hook_event_name: 'PostToolUse', tool_name: 'Bash', tool_input: { command: 'ls' } });
const ups = (R) => p(R, { hook_event_name: 'UserPromptSubmit', prompt: PROMPT });

const HOOK_BEDS = [
  { label: 'a strong edge in the window', repo: true, facts: ['fa', 'gate-fact'], script: (R) => [editA(R), ups(R)] },
  { label: 'the same edge 21 calls back', repo: true, facts: ['fa', 'gate-fact'], script: (R) => [editA(R), ...Array.from({ length: 21 }, () => bash(R)), ups(R)] },
  {
    label: 'only a weak edge',
    repo: true,
    facts: ['fa', 'fw', 'gate-fact'],
    script: (R) => [
      p(R, { hook_event_name: 'PostToolUse', tool_name: 'Read', tool_input: { file_path: join(R, 'src', 'b.py') } }),
      p(R, {
        hook_event_name: 'PostToolUse',
        tool_name: 'mcp__bantamkit__memory_recall',
        tool_input: { query: 'weak' },
        tool_response: [{ type: 'text', text: '[project] [fw] (project) a weak only memory\nbody text' }],
      }),
      ups(R),
    ],
  },
  { label: 'two strong facts: one line', repo: true, facts: ['fa', 'fb', 'gate-fact'], script: (R) => [editA(R), ups(R)] },
  { label: 'a via fact already injected earlier', repo: true, facts: ['fa', 'gate-fact'], script: (R) => [editA(R), ups(R), bash(R), ups(R)] },
  { label: 'no git', repo: false, facts: ['fa', 'gate-fact'], script: (R) => [editA(R), ups(R)] },
];

function runHookPy(ctx, { cwd, home, payload }) {
  const env = { HOME: home, USERPROFILE: home, BANTAMKIT_INDEX_DIR: join(home, 'index'), BANTAMKIT_RETENTION: 'off' };
  for (const k of SCRUBBED) env[k] = null;
  env.BANTAMKIT_VIA = 'on';
  const a = ctx.runPython(CLI_REF, { argv: ['--hook'], cwd, env, timeout: 120, stdin: b64(JSON.stringify(payload)) });
  if (a.error) throw new Error(`cli_ref.py: ${a.error}`);
  return { exit: a.exit, stdout: Buffer.from(a.stdout ?? '', 'base64').toString('utf8'), stderr: Buffer.from(a.stderr ?? '', 'base64').toString('utf8') };
}

function runHookNode(ctx, { cwd, home, payload }) {
  const env = { ...process.env, HOME: home, USERPROFILE: home, BANTAMKIT_INDEX_DIR: join(home, 'index'), BANTAMKIT_RETENTION: 'off' };
  for (const k of SCRUBBED) delete env[k];
  env.BANTAMKIT_VIA = 'on';
  const r = spawnSync(process.execPath, [join(ctx.runtimeTs, 'dist', 'cli.js'), '--hook'], { cwd, env, input: JSON.stringify(payload), encoding: 'utf8', timeout: 120_000 });
  return { exit: r.status, stdout: r.stdout ?? '', stderr: r.stderr ?? '' };
}

/** The UserPromptSubmit log records, `ts`/`ms` removed. */
function upsRecords(home) {
  let text = '';
  try {
    text = readFileSync(join(home, '.bantamkit', 'hooks', 'hook-log.jsonl'), 'utf8');
  } catch {
    return null;
  }
  return text
    .split('\n')
    .filter(Boolean)
    .map((l) => JSON.parse(l))
    .filter((x) => x.event === 'UserPromptSubmit')
    .map(({ ts: _ts, ms: _ms, ...rest }) => rest);
}

const viaLines = (runs) => runs.flatMap((r) => (r.stdout ? JSON.parse(r.stdout).hookSpecificOutput.additionalContext.split('\n') : [])).filter((l) => l.includes(' [via '));

function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `${label} — python`, kind, expected, actual: pySide },
    { name: `${label} — node`, kind, expected, actual: nodeSide },
  ];
}

const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const num = (v) => (v === 'nan' ? NaN : v);

export async function run(ctx) {
  const dist = (q) => pathToFileURL(join(ctx.runtimeTs, 'dist', ...q.split('/'))).href;
  const tc = await import(dist('touch/context.js'));
  const retrieval = await import(dist('memory/retrieval.js'));
  const cases = [];
  const notes = [];

  // ----------------------------------------------------------------- module half
  const py = ctx.runPython(REF, {
    suite: 'touch-context',
    windows: WINDOWS.map(([, c]) => c),
    weights: WEIGHTS.map(([, c]) => c),
    picks: PICKS.map(([, c]) => c),
    labels: LABELS,
    weight_of: WEIGHT_OF,
    switch: SWITCH,
  });
  const nd = {
    windows: WINDOWS.map(([, [rows, seq]]) => tc.window(rows, seq)),
    weights: WEIGHTS.map(([, [g, paths, now]]) => [...tc.contextWeights(g, paths, now)].sort((a, b) => cmp(a[0], b[0]))),
    picks: PICKS.map(([, [g, paths, exclude, table]]) => tc.viaPick(g, paths, new Set(exclude), (n) => (Object.hasOwn(table, n) ? table[n] : null))),
    labels: LABELS.map(([q, g]) => tc.viaLabel(q, g)),
  };
  retrieval.setContextWeight(WEIGHT_OF.w_context);
  try {
    nd.weight_of = WEIGHT_OF.cases.map(([t, st, u, c]) => retrieval.weightOf(t, st, num(u), num(c)));
  } finally {
    retrieval.setContextWeight(0.0);
  }
  const saved = process.env[tc.VIA_ENV];
  try {
    nd.switch = SWITCH.map(([env, on]) => {
      if (env === null) delete process.env[tc.VIA_ENV];
      else process.env[tc.VIA_ENV] = env;
      tc.setViaOn(on);
      return tc.viaEnabled();
    });
  } finally {
    tc.setViaOn(false);
    if (saved === undefined) delete process.env[tc.VIA_ENV];
    else process.env[tc.VIA_ENV] = saved;
  }
  WINDOWS.forEach(([tag], i) => cases.push({ name: `window — ${tag}`, kind: 'json', expected: py.windows[i], actual: nd.windows[i] }));
  WEIGHTS.forEach(([tag], i) => cases.push({ name: `context_weights — ${tag}`, kind: 'json', expected: py.weights[i], actual: nd.weights[i] }));
  PICKS.forEach(([tag], i) => cases.push({ name: `via_pick — ${tag}`, kind: 'json', expected: py.picks[i], actual: nd.picks[i] }));
  cases.push({ name: 'via_label — shortest unique suffix, four paths', kind: 'json', expected: py.labels, actual: nd.labels });
  cases.push({ name: 'weight_of at W_CONTEXT = 0.5, ctx in {0, 0.5, 1, 7, -1, NaN} x three types', kind: 'json', expected: py.weight_of, actual: nd.weight_of });
  cases.push({ name: 'via_enabled — BANTAMKIT_VIA on/off/other/unset against VIA_ON', kind: 'json', expected: py.switch, actual: nd.switch });

  // ----------------------------------------------------------------- hook half
  const views = { py: [], node: [] };
  HOOK_BEDS.forEach((b, i) => {
    const root = join(ctx.scratch, `touch-context-hook-${i + 1}`);
    for (const side of ['py', 'node']) {
      const { home, R } = buildBed(join(root, side), b);
      const runs = b.script(R).map((payload) => (side === 'py' ? runHookPy : runHookNode)(ctx, { cwd: R, home, payload }));
      views[side].push({ runs, records: upsRecords(home) });
    }
    const vp = views.py[i];
    const vn = views.node[i];
    cases.push({ name: `hook, ${b.label}: exit/stdout/stderr of every run`, kind: 'json', expected: vp.runs, actual: vn.runs });
    cases.push({ name: `hook, ${b.label}: the UserPromptSubmit log records`, kind: 'json', expected: vp.records, actual: vn.records });
  });

  // ------------------------------------------------------------------ literals
  cases.push(...literalCases(viaLines(views.py[0].runs), viaLines(views.node[0].runs), 'LITERAL: the via line bytes of the first bed', [VIA_LINE]));
  cases.push(...literalCases(py.picks[0], nd.picks[0], 'LITERAL: via_pick of the unit test fixture', PICK_LITERAL));
  // Each bed's via-line count on each side by itself, not only equally.
  const expectVia = [1, 0, 0, 1, 1, 0];
  for (const [side, v] of [['python', views.py], ['node', views.node]]) {
    cases.push({
      name: `per bed via-line count: strong, 21 back, weak only, two strong, already shown, no git — ${side}`,
      kind: 'json',
      expected: expectVia,
      actual: v.map((x) => viaLines(x.runs).length),
    });
  }
  // The context count each bed's last record carries: the weak-only bed must HAVE context
  // (so a weak edge reaching the via pick would show), the 21-back and no-git beds none.
  const expectContext = [1, null, 1, 2, 1, null];
  for (const [side, v] of [['python', views.py], ['node', views.node]]) {
    cases.push({
      name: `per bed "context" of the last UserPromptSubmit record — ${side}`,
      kind: 'json',
      expected: expectContext,
      actual: v.map((x) => x.records?.at(-1)?.context ?? null),
    });
  }
  notes.push(`${WINDOWS.length} window, ${WEIGHTS.length} weight, ${PICKS.length} pick fixtures; ${HOOK_BEDS.length} hook beds under <scratch>/touch-context-hook-*`);
  return { cases, notes };
}
