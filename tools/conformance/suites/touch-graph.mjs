/**
 * touch-graph — the touch graph, a derived index with a git half and a touch-log half (#200,
 * Task 4; job70 T200-4).
 *
 * THE PROPERTY: over the same refs, files and renames the two runtimes build the same strong
 * edges (`path -> [[fact, symbol|null], ...]`, first layer first, then name order); over the same
 * touch-log rows the same weak edges (same session, `|use.seq - touch.seq| <= WEAK_SPAN`, or for
 * a bash turn `from < use.seq <= seq`; the newest `WEAK_TS_MAX` distinct use timestamps); and
 * `TouchGraph.load` over the same repo, stores and log writes the same file bytes, rebuilds the
 * same half at the same step, and reads the OTHER runtime's file as fresh. The graph feeds
 * `w_context` and the `[via <file>]` pick (#200 Task 5), so a disagreement here is the two
 * runtimes ranking one prompt's facts differently.
 *
 * HOW. One payload to `ref/touch_ref.py` (`run_graph`), the same calls in-process against
 * `dist/touch/graph.js`. `strong`/`weak` answers are compared as `dumpIndex` strings (the bytes
 * the file holds, key order included). Each runtime gets its own bed, built by this harness
 * with the same script (a git repo with one `git mv`, a project store of three facts, a
 * read-only layer naming one fact again): load, load unchanged, touch lines, a commit, a fact
 * write, a corrupt file. The strong print is masked to `<print>` because it folds in
 * `mtime_ns`; the weak print (log size and segment count) is compared as is. `load_nogit` runs
 * a load with PATH empty: a strong rebuild then cannot run git and the load answers null, so a
 * side that rebuilds the git half on a weak-only change is red there. Two more beds are shared:
 * one side loads, the other loads after it and must not rewrite the file.
 *
 * THE LITERALS. A change made to both sides leaves every differential green, so two answers
 * are pinned per side: `build_strong` of the unit test's fixture, and the boundary pair
 * `[edge at 20, edge at 21]` = `[true, false]`.
 */
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, realpathSync, renameSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'touch-graph';
export const summary =
  'touch graph: build_strong/build_weak (±WEAK_SPAN, bash-turn from, WEAK_TS_MAX), TouchGraph.load file bytes and per-half rebuilds, cross-runtime freshness';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'touch_ref.py');

const STEP1 = {
  layers: [{ zeta: ['a.py#run'], alpha: ['src/a.py', 'missing.py'] }, { alpha: ['docs/x.md'] }],
  files: ['src/a.py', 'src/b.py', 'docs/x.md'],
  renames: {},
  top: '/r',
};
const STEP1_LITERAL = '{"docs/x.md":[["alpha",null]],"src/a.py":[["alpha",null],["zeta","run"]]}';

/** [tag, case] */
const STRONG = [
  ['the unit test fixture', STEP1],
  [
    'a fact in two layers, symbols, a rename, an ambiguous name, __proto__, a numeric path',
    {
      layers: [
        { 'names-a': ['src/a.py', 'b.py#run', 'src/a.py#run', 'src/a.py'], __proto__x: ['old.py#f'], m: ['store.ts', '123'] },
        { 'names-a': ['docs/x.md', 'src/a.py'], __proto__: ['/r/docs/x.md'], a: ['nope.py'] },
      ],
      files: ['src/a.py', 'src/b.py', 'docs/x.md', 'a/store.ts', 'b/store.ts', '123', '__proto__/q.py'],
      renames: { 'old.py': 'src/b.py' },
      top: '/r',
    },
  ],
  ['no layers', { layers: [], files: ['a.py'], renames: {}, top: '/r' }],
  ['a layer of no refs', { layers: [{ f: [] }, {}], files: ['a.py'], renames: {}, top: '/r' }],
];

const ts = (n) => `2026-10-16T00:${String(Math.floor(n / 60)).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}Z`;
const t = (seq, path, extra = {}) => ({ ts: ts(seq), session: 's', seq, op: 'edit', path, ...extra });
const u = (seq, fact, extra = {}) => ({ ts: ts(seq), session: 's', seq, op: 'use', fact, kind: 'recall_hit', ...extra });

/** [tag, rows] */
const WEAK = [
  ['the boundary: 20 apart is an edge, 21 is none', [t(1, 'p'), u(21, 'edge20'), u(22, 'none21')]],
  ['the boundary below the touch', [t(30, 'p'), u(10, 'edge20'), u(9, 'none21')]],
  ['two sessions never pair', [t(5, 'p'), u(6, 'f', { session: 'other' }), t(6, 'q', { session: 'other' }), u(7, 'g')]],
  [
    'a bash turn with from: (from, seq]',
    [u(3, 'at-from'), u(4, 'after-from'), u(9, 'at-seq'), u(10, 'after-seq'), t(9, 'b.txt', { op: 'write', via: 'bash-turn', from: 3 })],
  ],
  ['a bash turn without from falls back to the span', [u(3, 'f'), u(40, 'g'), t(9, 'b.txt', { op: 'write', via: 'bash-turn' })]],
  ['duplicate timestamps count once', [t(1, 'p'), u(2, 'f'), u(3, 'f', { ts: ts(2) }), u(4, 'f')]],
  ['40 uses of one pair: WEAK_TS_MAX cut', [t(50, 'p'), ...Array.from({ length: 40 }, (_, i) => u(40 + (i % 20), 'f', { ts: ts(i * 7) }))]],
  ['__proto__ and numeric paths and facts', [t(1, '__proto__'), t(1, '10'), u(2, '__proto__'), u(3, '2')]],
  [
    'malformed rows are skipped',
    [
      t(1, 'p'),
      { session: 's', seq: 2, op: 'use', fact: 'no-ts' },
      { ts: ts(2), session: 's', seq: '2', op: 'use', fact: 'string-seq' },
      { ts: ts(2), session: 7, seq: 2, op: 'use', fact: 'number-session' },
      { ts: ts(2), session: 's', seq: true, op: 'use', fact: 'bool-seq' },
      { ts: ts(2), session: 's', seq: 2.5, op: 'use', fact: 'half-seq' },
      { ts: ts(2), session: 's', seq: 2, op: 'use', fact: 5 },
      { ts: ts(2), session: 's', seq: 2, op: 'folded', path: 'p' },
      { ts: ts(2), session: 's', seq: 2, op: 'use', fact: 'ok' },
    ],
  ],
  ['several touches of one path and reads and writes', [t(1, 'p', { op: 'read' }), t(30, 'p', { op: 'write' }), u(15, 'f'), u(45, 'g'), u(60, 'h')]],
  ['empty', []],
];

const git = (top, ...a) =>
  execFileSync('git', ['-c', 'user.email=t@t', '-c', 'user.name=t', '-c', 'commit.gpgsign=false', '-C', top, ...a], {
    stdio: 'pipe',
    env: { ...process.env, GIT_CONFIG_NOSYSTEM: '1', LC_ALL: 'C' },
  });

function factFile(store, nm, desc, body) {
  const d = join(store, 'facts');
  mkdirSync(d, { recursive: true });
  const tmp = join(d, `.${nm}.tmp`);
  writeFileSync(
    tmp,
    `---\nname: ${nm}\ndescription: ${desc}\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\nlinks: []\n---\n\n${body}\n`,
  );
  renameSync(tmp, join(d, `${nm}.md`));
}

/** One bed: the same script for every side, so the repo-relative graph is the same. */
function makeBed(scratch, tag) {
  const root = join(scratch, 'touch-graph', tag);
  const repo = join(root, 'repo');
  mkdirSync(join(repo, 'src'), { recursive: true });
  mkdirSync(join(repo, 'docs'), { recursive: true });
  writeFileSync(join(repo, 'src', 'a.py'), 'a\n');
  writeFileSync(join(repo, 'src', 'b.py'), 'b\n');
  writeFileSync(join(repo, 'docs', 'x.md'), 'x\n');
  writeFileSync(join(repo, 'old.py'), 'o\n');
  git(repo, 'init', '-q');
  git(repo, 'add', '-A');
  git(repo, 'commit', '-qm', 'one');
  git(repo, 'mv', 'old.py', 'src/new.py');
  git(repo, 'commit', '-qm', 'two');
  const store = join(root, 'store');
  const extra = join(root, 'extra');
  factFile(store, 'names-a', 'touches src/a.py', 'b');
  factFile(store, 'symbol', 'x', 'see b.py#run and old.py');
  factFile(store, 'shared', 'y', 'docs/x.md');
  factFile(extra, 'shared', 'z', 'src/a.py');
  const home = join(root, 'home');
  const index = join(root, 'index');
  mkdirSync(home, { recursive: true });
  mkdirSync(index, { recursive: true });
  return {
    home: realpathSync(home),
    index: realpathSync(index),
    repo: realpathSync(repo),
    store: realpathSync(store),
    layers: [
      ['project', realpathSync(store), true],
      ['extra', realpathSync(extra), false],
    ],
  };
}

function steps(store) {
  return [
    { op: 'load' },
    { op: 'load' },
    { op: 'touch', session: 's', seq: 1, kind: 'edit', path: 'src/a.py', ts: ts(1) },
    { op: 'use', session: 's', seq: 2, fact: 'names-a', ts: ts(2) },
    { op: 'touch', session: 's', seq: 25, kind: 'read', path: 'docs/x.md', ts: ts(25) },
    { op: 'use', session: 's', seq: 45, fact: 'shared', ts: ts(45) },
    { op: 'use', session: 's', seq: 46, fact: 'symbol', ts: ts(46) },
    { op: 'touch', session: 's', seq: 50, kind: 'write', path: 'src/b.py', via: 'bash-turn', from: 45, ts: ts(50) },
    { op: 'load_nogit' },
    { op: 'commit', path: 'src/c.py', text: 'c\n' },
    { op: 'load' },
    { op: 'fact', store, name: 'late', description: 'names src/c.py', body: 'b' },
    { op: 'load' },
    { op: 'corrupt', text: '{nope' },
    { op: 'load' },
    { op: 'load_nogit' },
  ];
}

const PRINT = /"strong_print":"[0-9a-f]{16}"/g;
const masked = (s) => s.replace(PRINT, '"strong_print":"<print>"');

function runNodeBed(mods, bed) {
  const { graph, store: storeMod, log: logMod, repo: repoMod, hot } = mods;
  const keys = ['HOME', 'USERPROFILE', 'BANTAMKIT_INDEX_DIR', 'PATH'];
  const saved = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
  Object.assign(process.env, { HOME: bed.home, USERPROFILE: bed.home, BANTAMKIT_INDEX_DIR: bed.index });
  try {
    const repo = repoMod.findRepo(bed.repo);
    const layers = bed.layers.map(([lab, p, w]) => [lab, new storeMod.MemoryStore(p), w]);
    const g = new graph.TouchGraph(bed.home, repo);
    const log = new logMod.TouchLog(bed.home, repo.id);
    const mtime = () => {
      try {
        return String(statSync(g.path, { bigint: true }).mtimeNs);
      } catch {
        return null;
      }
    };
    let prev = null;
    const out = [];
    for (const st of bed.steps) {
      if (st.op === 'load' || st.op === 'load_nogit') {
        const before = mtime();
        if (st.op === 'load_nogit') process.env.PATH = '';
        let data;
        try {
          data = g.load(layers);
        } finally {
          process.env.PATH = saved.PATH;
        }
        let file = null;
        try {
          file = masked(readFileSync(g.path, 'utf8'));
        } catch {
          /* no file */
        }
        let moved = null;
        if (data !== null && prev !== null) moved = [data.strong_print !== prev.strong_print, data.weak_print !== prev.weak_print];
        if (data !== null) prev = data;
        out.push({ data: data === null ? null : masked(hot.dumpIndex(data)), file, rewritten: mtime() !== before, moved });
      } else if (st.op === 'touch') {
        log.appendTouch(st.session, st.seq, st.kind, st.path, st.via ?? null, st.from ?? null, st.ts);
        out.push(null);
      } else if (st.op === 'use') {
        log.appendUse(st.session, st.seq, st.fact, 'recall_hit', st.ts);
        out.push(null);
      } else if (st.op === 'fact') {
        factFile(st.store, st.name, st.description, st.body);
        out.push(null);
      } else if (st.op === 'commit') {
        const p = join(bed.repo, st.path);
        mkdirSync(dirname(p), { recursive: true });
        writeFileSync(p, st.text);
        git(bed.repo, 'add', '-A');
        git(bed.repo, 'commit', '-qm', st.path);
        out.push(null);
      } else if (st.op === 'corrupt') {
        writeFileSync(g.path, st.text);
        out.push(null);
      } else {
        throw new Error(`touch-graph: unknown op ${st.op}`);
      }
    }
    return out;
  } finally {
    for (const k of keys) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
}

function literalCases(pySide, nodeSide, label, expected) {
  return [
    { name: `${label} — python`, kind: 'json', expected, actual: pySide },
    { name: `${label} — node`, kind: 'json', expected, actual: nodeSide },
  ];
}

/** `[edge at 20, edge at 21]` from the boundary case's dumped weak edges. */
const boundary = (dumped) => {
  const facts = JSON.parse(dumped)['p'] ?? {};
  return ['edge20', 'none21'].map((f) => Object.hasOwn(facts, f));
};

export async function run(ctx) {
  const dist = (p) => pathToFileURL(join(ctx.runtimeTs, 'dist', ...p.split('/'))).href;
  const mods = {
    graph: await import(dist('touch/graph.js')),
    refs: await import(dist('touch/refs.js')),
    log: await import(dist('touch/log.js')),
    repo: await import(dist('touch/repo.js')),
    store: await import(dist('memory/store.js')),
    hot: await import(dist('storage/hotindex.js')),
  };
  const cases = [];
  const notes = [];

  const pyBed = makeBed(ctx.scratch, 'py');
  const ndBed = makeBed(ctx.scratch, 'node');
  const crossA = makeBed(ctx.scratch, 'py-then-node');
  const crossB = makeBed(ctx.scratch, 'node-then-py');
  const warm = [
    { op: 'touch', session: 's', seq: 1, kind: 'edit', path: 'src/a.py', ts: ts(1) },
    { op: 'use', session: 's', seq: 2, fact: 'names-a', ts: ts(2) },
    { op: 'load' },
  ];

  const req = {
    suite: 'touch-graph',
    strong: STRONG.map(([, c]) => c),
    weak: WEAK.map(([, rows]) => rows),
    beds: [
      { ...pyBed, steps: steps(pyBed.store) },
      { ...crossA, steps: warm },
    ],
  };
  const py = ctx.runPython(REF, req);
  const ndStrong = STRONG.map(([, c]) =>
    mods.hot.dumpIndex(mods.graph.buildStrong(c.layers, new mods.refs.FileSet(c.files), c.renames, c.top)),
  );
  const ndWeak = WEAK.map(([, rows]) => mods.hot.dumpIndex(mods.graph.buildWeak(rows)));
  const ndSteps = runNodeBed(mods, { ...ndBed, steps: steps(ndBed.store) });
  const crossANode = runNodeBed(mods, { ...crossA, steps: [{ op: 'load' }] });
  const crossBNode = runNodeBed(mods, { ...crossB, steps: warm });
  const crossBPy = ctx.runPython(REF, { suite: 'touch-graph', strong: [], weak: [], beds: [{ ...crossB, steps: [{ op: 'load' }] }] });

  STRONG.forEach(([tag], i) => cases.push({ name: `build_strong — ${tag}`, kind: 'json', expected: py.strong[i], actual: ndStrong[i] }));
  WEAK.forEach(([tag], i) => cases.push({ name: `build_weak — ${tag}`, kind: 'json', expected: py.weak[i], actual: ndWeak[i] }));
  const pySteps = py.beds[0];
  steps('').forEach((st, i) => {
    if (st.op !== 'load' && st.op !== 'load_nogit') return;
    cases.push({
      name: `TouchGraph.load step ${i} (${st.op}, after ${i === 0 ? 'nothing' : steps('')[i - 1].op}) — data, file bytes, rewritten, moved`,
      kind: 'json',
      expected: pySteps[i],
      actual: ndSteps[i],
    });
  });
  // The behaviour each step exists for holds on each side by itself, not only equally.
  const expectations = { 0: [true, null], 1: [false, [false, false]], 8: [true, [false, true]], 10: [true, [true, false]], 12: [true, [true, false]], 14: [true, [false, false]], 15: [false, [false, false]] };
  for (const [side, got] of [['python', pySteps], ['node', ndSteps]]) {
    cases.push({
      name: `per step [rewritten, moved]: first write, unchanged, weak-only without git, commit, fact write, corrupt file, unchanged without git — ${side}`,
      kind: 'json',
      expected: expectations,
      actual: Object.fromEntries(Object.keys(expectations).map((k) => [k, [got[k]?.rewritten, got[k]?.moved]])),
    });
  }
  cases.push({
    name: 'a graph written by python is fresh to node: not rewritten, same data',
    kind: 'json',
    expected: { rewritten: false, data: py.beds[1][2].data },
    actual: { rewritten: crossANode[0].rewritten, data: crossANode[0].data },
  });
  cases.push({
    name: 'a graph written by node is fresh to python: not rewritten, same data',
    kind: 'json',
    expected: { rewritten: false, data: crossBNode[2].data },
    actual: { rewritten: crossBPy.beds[0][0].rewritten, data: crossBPy.beds[0][0].data },
  });

  cases.push(...literalCases(py.strong[0], ndStrong[0], 'LITERAL: build_strong of the unit test fixture', STEP1_LITERAL));
  cases.push(...literalCases(boundary(py.weak[0]), boundary(ndWeak[0]), 'LITERAL: [edge at seq 20 apart, edge at 21 apart]', [true, false]));
  notes.push(`${STRONG.length} strong and ${WEAK.length} weak fixtures; beds under <scratch>/touch-graph/`);
  for (const [side, got] of [['python', pySteps], ['node', ndSteps]]) {
    const last = got[14]?.data === null || got[14]?.data === undefined ? null : JSON.parse(got[14].data);
    notes.push(`${side} step 14: ${last === null ? 'no graph' : `${Object.keys(last.strong).length} strong paths, ${Object.keys(last.weak).length} weak paths, weak_print ${last.weak_print}`}`);
  }
  return { cases, notes };
}
