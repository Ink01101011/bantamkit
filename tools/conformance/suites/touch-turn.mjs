/**
 * touch-turn — writes made by Bash, captured once per turn from two `git status` snapshots
 * (#200, E5, Task 3; job70 T200-3), Python against Node.
 *
 * THE PROPERTY: over the same working tree the two runtimes read the same `git status` into
 * the same `path -> [xy, mtime_ns, size]` map (a rename or copy keyed on its destination, a
 * deletion as `"-"`/`-1`), call the same paths changed (added, removed, or whose triple moved,
 * so a path dirty before the turn and touched again IS a change, and so is a revert to clean),
 * write the same `ledger-<session>.turn.json` bytes (keys sorted) and read the same junk as no
 * turn. As PROCESSES, UserPromptSubmit → an Edit → Bash-like writes → Stop leaves the same
 * touch log: one `write` line `via: "bash-turn"` with `from` the seq the turn opened at, for
 * the file no Edit explains, and a second Stop in the same turn adds nothing. Outside a repo,
 * or at a Stop with no open turn, both write nothing. The touch log is shared on disk, so a
 * disagreement is two runtimes writing one user's history two ways.
 *
 * HOW. Module scenarios are op scripts run twice, by `ref/touch_ref.py` (`run_turn`) and by
 * `runNode` below against `dist/touch/index.js`, each over its own repo built the same way;
 * every `mtime_ns` is masked to `<ns>` (two beds never share a clock). Hook beds are built at
 * ONE path, driven by the reference, wiped, rebuilt and driven by the port, so the repo id is
 * the same; `ts` and `mtime_ns` are masked.
 *
 * THE LITERALS. A change made to both sides leaves every differential green, so per side: the
 * unit test's changed list `["a.txt","dirty.txt","new/n.txt"]`, the hook's one bash-turn line,
 * and the log unchanged by the second Stop.
 *
 * WHAT IT DOES NOT COVER: git absent from PATH (both sides take `git`'s `None`, pinned by the
 * failing-git scenario instead), Windows paths (Task 9's manual run), and latency (the bench).
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'touch-turn';
export const summary = 'bash-turn: git status snapshots, the changed list, the turn file; UserPromptSubmit/Stop as processes';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'touch_ref.py');
const CLI_REF = join(here, 'ref', 'cli_ref.py');
const SCRUBBED = ['BANTAMKIT_MEMORY_DIR', 'CLAUDE_COWORK_MEMORY_PATH_OVERRIDE', 'TOOL_METRICS_DIR', 'BANTAMKIT_DREAM_TIMEOUT_MS', 'BANTAMKIT_ASSETS'];
const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');

function scenarios() {
  return [
    {
      label: 'unit: new, modified and an already-dirty path touched again',
      ops: [
        { op: 'snapshot', as: 'before' },
        { op: 'write', path: 'a.txt', text: 'changed by bash\n' },
        { op: 'write', path: 'new/n.txt', text: 'n\n' },
        { op: 'write', path: 'dirty.txt', text: '3, longer\n' },
        { op: 'snapshot', as: 'after' },
        { op: 'changed', a: 'before', b: 'after' },
      ],
    },
    {
      label: 'every status form: staged, unstaged, untracked in a new dir, a rename, a deletion, Thai',
      ops: [
        { op: 'snapshot', as: 'before' },
        { op: 'write', path: 'stage.txt', text: 'staged, longer\n' },
        { op: 'git', args: ['add', 'stage.txt'] },
        { op: 'write', path: 'a.txt', text: 'unstaged\n' },
        { op: 'write', path: 'deep/er/n.txt', text: 'n\n' },
        { op: 'git', args: ['mv', 'ren.txt', 'ren2.txt'] },
        { op: 'rm', path: 'gone.txt' },
        { op: 'write', path: 'ไทย/😀 x.txt', text: 't\n' },
        { op: 'write', path: 'dirty.txt', text: 'dirty again, longer\n' },
        { op: 'snapshot', as: 'after' },
        { op: 'changed', a: 'before', b: 'after' },
        { op: 'changed', a: 'after', b: 'before' },
        { op: 'changed', a: 'after', b: 'after' },
        { op: 'save_turn', session: 's/1 ไทย', snap: 'after', seq: 41 },
        { op: 'turnfile', name: 'ledger-s_1____.turn.json' },
        { op: 'load_turn', session: 's/1 ไทย' },
      ],
    },
    {
      label: 'a revert to clean is a change; nothing moved is none',
      ops: [
        { op: 'snapshot', as: 'before' },
        { op: 'write', path: 'dirty.txt', text: '1\n' },
        { op: 'snapshot', as: 'after' },
        { op: 'changed', a: 'before', b: 'after' },
        { op: 'snapshot', as: 'again' },
        { op: 'changed', a: 'after', b: 'again' },
      ],
    },
    {
      label: 'git fails, no repo, junk turn files, a __proto__ path',
      ops: [
        { op: 'snapshot_at', dir: 'notgit', as: 'bad' },
        { op: 'snapshot_at', dir: 'plain', as: 'none' },
        { op: 'write', path: '__proto__', text: 'p\n' },
        { op: 'snapshot', as: 'proto' },
        { op: 'save_turn', session: '', snap: 'proto', seq: 0 },
        { op: 'turnfile', name: 'ledger-nosession.turn.json' },
        { op: 'load_turn', session: '' },
        { op: 'load_turn', session: 'missing' },
        { op: 'turnraw', name: 'ledger-j.turn.json', b64: b64('{"seq":') },
        { op: 'load_turn', session: 'j' },
        { op: 'turnraw', name: 'ledger-j.turn.json', b64: b64('[1]') },
        { op: 'load_turn', session: 'j' },
        { op: 'turnraw', name: 'ledger-j.turn.json', b64: b64('{"seq":"7","status":{}}') },
        { op: 'load_turn', session: 'j' },
        { op: 'turnraw', name: 'ledger-j.turn.json', b64: b64('{"seq":true,"status":{}}') },
        { op: 'load_turn', session: 'j' },
        { op: 'turnraw', name: 'ledger-j.turn.json', b64: b64('{"seq":7,"status":[]}') },
        { op: 'load_turn', session: 'j' },
        { op: 'turnraw', name: 'ledger-j.turn.json', b64: b64('{"seq":7.0,"status":{"x":["??","-",-1]}}') },
        { op: 'load_turn', session: 'j' },
      ],
    },
  ];
}

// --------------------------------------------------------------------- the beds

function git(args, cwd) {
  const r = spawnSync('git', args, { cwd, encoding: 'utf8' });
  if (r.status !== 0) throw new Error(`touch-turn: git ${args.join(' ')} failed: ${r.stderr}`);
}

function buildBed(root) {
  rmSync(root, { recursive: true, force: true });
  const R = join(root, 'repo');
  mkdirSync(R, { recursive: true });
  mkdirSync(join(root, 'state'));
  mkdirSync(join(root, 'plain'));
  mkdirSync(join(root, 'notgit', '.git'), { recursive: true }); // found by findRepo, refused by git
  git(['init', '-q'], R);
  for (const f of ['a.txt', 'dirty.txt', 'stage.txt', 'ren.txt', 'gone.txt']) writeFileSync(join(R, f), '1\n');
  git(['add', '.'], R);
  git(['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'c'], R);
  writeFileSync(join(R, 'dirty.txt'), '2\n'); // dirty before the turn
}

// --------------------------------------------------------------------- the Node half

const b64file = (p) => {
  try {
    return readFileSync(p).toString('base64');
  } catch {
    return null;
  }
};

const mask = (snap) => (snap === null ? null : Object.fromEntries([...snap].map(([p, e]) => [p, [e[0], e[1] === '-' ? '-' : '<ns>', e[2]]])));

function runNodeBed(touch, bed) {
  const R = join(bed.root, 'repo');
  const snaps = new Map();
  const out = [];
  for (const op of bed.ops) {
    switch (op.op) {
      case 'write':
        mkdirSync(dirname(join(R, op.path)), { recursive: true });
        writeFileSync(join(R, op.path), op.text);
        out.push(null);
        break;
      case 'rm':
        unlinkSync(join(R, op.path));
        out.push(null);
        break;
      case 'git':
        git(op.args, R);
        out.push(null);
        break;
      case 'snapshot':
      case 'snapshot_at': {
        const r = touch.findRepo(join(bed.root, op.dir ?? 'repo'));
        const snap = r === null ? null : touch.snapshot(r);
        snaps.set(op.as ?? '', snap);
        out.push(mask(snap));
        break;
      }
      case 'changed':
        out.push(touch.changed(snaps.get(op.a), snaps.get(op.b)));
        break;
      case 'save_turn':
        try {
          touch.saveTurn(bed.state, op.session, snaps.get(op.snap), op.seq);
          out.push(null);
        } catch {
          out.push('error');
        }
        break;
      case 'load_turn': {
        const t = touch.loadTurn(bed.state, op.session);
        out.push(t === null ? null : [t[0], mask(t[1])]);
        break;
      }
      case 'turnfile':
        out.push(b64file(join(bed.state, op.name)));
        break;
      case 'turnraw':
        writeFileSync(join(bed.state, op.name), Buffer.from(op.b64, 'base64'));
        out.push(null);
        break;
      default:
        throw new Error(`touch-turn: unknown op ${op.op}`);
    }
  }
  return out;
}

/** Python's `json.dumps(..., sort_keys=True)` object order is code-point order; so is this. */
const sortKeys = (v) =>
  v === null || typeof v !== 'object' || Array.isArray(v)
    ? v
    : Object.fromEntries(Object.keys(v).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)).map((k) => [k, sortKeys(v[k])]));

// --------------------------------------------------------------------- the hook half

function runHookPy(ctx, { cwd, home, payload }) {
  const env = { HOME: home, USERPROFILE: home };
  for (const k of SCRUBBED) env[k] = null;
  const a = ctx.runPython(CLI_REF, { argv: ['--hook'], cwd, env, timeout: 120, stdin: b64(JSON.stringify(payload)) });
  if (a.error) throw new Error(`cli_ref.py: ${a.error}`);
  return { exit: a.exit, stdout: Buffer.from(a.stdout ?? '', 'base64').toString('utf8'), stderr: Buffer.from(a.stderr ?? '', 'base64').toString('utf8') };
}

function runHookNode(ctx, { cwd, home, payload }) {
  const env = { ...process.env, HOME: home, USERPROFILE: home };
  for (const k of SCRUBBED) delete env[k];
  const r = spawnSync(process.execPath, [join(ctx.runtimeTs, 'dist', 'cli.js'), '--hook'], { cwd, env, input: JSON.stringify(payload), encoding: 'utf8', timeout: 120_000 });
  return { exit: r.status, stdout: r.stdout ?? '', stderr: r.stderr ?? '' };
}

/**
 * The Step 1 hook scenario. A step is a payload or a function run between hooks (the writes a
 * Bash call would make). `view` marks where the touch log and the turn file are read.
 */
function hookScript(R) {
  const p = (extra) => ({ session_id: 's1', cwd: R, ...extra });
  return [
    p({ hook_event_name: 'PostToolUse', tool_name: 'Bash', tool_input: { command: 'ls' } }),
    p({ hook_event_name: 'UserPromptSubmit', prompt: 'hi' }), // short: the skip still opens the turn
    p({ hook_event_name: 'PostToolUse', tool_name: 'Edit', tool_input: { file_path: join(R, 'a.txt'), old_string: '1', new_string: '2' } }),
    () => {
      writeFileSync(join(R, 'b.txt'), 'by bash\n');
      writeFileSync(join(R, 'a.txt'), 'again, longer\n');
    },
    p({ hook_event_name: 'Stop' }),
    'view',
    p({ hook_event_name: 'Stop', stop_hook_active: true }),
    'view',
    () => writeFileSync(join(R, 'c.txt'), 'next turn\n'),
    p({ hook_event_name: 'UserPromptSubmit', prompt: '/clear' }),
    p({ hook_event_name: 'PostToolUse', tool_name: 'Bash', tool_input: { command: 'touch d.txt' } }),
    () => writeFileSync(join(R, 'd.txt'), 'd\n'),
    p({ hook_event_name: 'Stop' }),
    'view',
  ];
}

const HOOK_BEDS = [
  { label: 'a git repo', repo: true },
  { label: 'no repo', repo: false },
  { label: 'a Stop with no open turn', repo: true, from: 3, to: 6 },
];

function buildHookBed(root, b) {
  rmSync(root, { recursive: true, force: true });
  const home = join(root, 'home');
  const R = join(root, 'repo');
  mkdirSync(home, { recursive: true });
  mkdirSync(R, { recursive: true });
  if (b.repo) git(['init', '-q', R], root);
  writeFileSync(join(R, 'a.txt'), '1\n');
  return { home, R: realpathSync.native(R) };
}

const maskTs = (s) => s.replace(/"ts":"[^"]*"/g, '"ts":"<ts>"');
const maskNs = (s) => s.replace(/("[^"]{2}",)"[0-9]+"/g, '$1"<ns>"');

function hookView(home) {
  const dir = join(home, '.bantamkit', 'touch');
  let names = null;
  try {
    names = readdirSync(dir).sort();
  } catch {
    /* no touch directory */
  }
  const logName = names?.find((n) => n.endsWith('.jsonl'));
  const turn = b64file(join(home, '.bantamkit', 'hooks', 'ledger-s1.turn.json'));
  return {
    names: names === null ? null : names.map((n) => n.replace(/^[0-9a-f]{16}\.jsonl$/, '<id>.jsonl')),
    log: logName ? maskTs(readFileSync(join(dir, logName), 'utf8')) : null,
    turn: turn === null ? null : maskNs(Buffer.from(turn, 'base64').toString('utf8')),
  };
}

function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `${label} — python`, kind, expected, actual: pySide },
    { name: `${label} — node`, kind, expected, actual: nodeSide },
  ];
}

// ------------------------------------------------------------------------------ run

export async function run(ctx) {
  const touch = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'touch', 'index.js')).href);
  const cases = [];
  const notes = [];

  // ----------------------------------------------------------- module scenarios
  const all = scenarios();
  const beds = { py: [], node: [] };
  all.forEach((s, i) => {
    for (const side of ['py', 'node']) {
      const root = join(ctx.scratch, `touch-turn-${String(i + 1).padStart(2, '0')}`, side);
      buildBed(root);
      const real = realpathSync.native(root);
      beds[side].push({ root: real, state: join(real, 'state'), ops: s.ops });
    }
  });
  const py = ctx.runPython(REF, { suite: 'touch-turn', beds: beds.py });
  const nd = beds.node.map((bed) => runNodeBed(touch, bed));
  const isBytes = (op) => op.op === 'turnfile';
  const asBytes = (v) => (v === null ? Buffer.from('<no file>') : Buffer.from(maskNs(Buffer.from(v, 'base64').toString('utf8'))));
  all.forEach((s, i) => {
    s.ops.forEach((op, j) => {
      if (['write', 'rm', 'git', 'turnraw'].includes(op.op)) return;
      const what = [op.op, op.as ?? '', op.a ? `${op.a}->${op.b}` : '', op.session !== undefined ? JSON.stringify(op.session) : '', op.name ?? ''].filter(Boolean).join(' ');
      cases.push({
        name: `${s.label} — #${String(j).padStart(2, '0')} ${what}`,
        kind: isBytes(op) ? 'bytes' : 'json',
        expected: isBytes(op) ? asBytes(py.beds[i][j]) : sortKeys(py.beds[i][j]),
        actual: isBytes(op) ? asBytes(nd[i][j]) : sortKeys(nd[i][j]),
      });
    });
  });
  notes.push(`${all.length} module scenarios, ${all.reduce((n, s) => n + s.ops.length, 0)} ops per side`);

  // ----------------------------------------------------------------- hook beds
  const views = { py: [], node: [] };
  HOOK_BEDS.forEach((b, i) => {
    const root = join(ctx.scratch, `touch-turn-hook-${i + 1}`);
    for (const side of ['py', 'node']) {
      const { home, R } = buildHookBed(root, b);
      const script = hookScript(R).slice(b.from ?? 0, b.to);
      const runs = [];
      const seen = [];
      for (const step of script) {
        if (step === 'view') seen.push(hookView(home));
        else if (typeof step === 'function') step();
        else runs.push((side === 'py' ? runHookPy : runHookNode)(ctx, { cwd: R, home, payload: step }));
      }
      views[side].push({ seen, final: hookView(home), runs });
    }
    const vp = views.py[i];
    const vn = views.node[i];
    vp.seen.forEach((_, k) => {
      for (const key of ['names', 'log', 'turn']) {
        cases.push({
          name: `hook, ${b.label}: view ${k + 1} ${key}`,
          kind: 'bytes',
          expected: Buffer.from(String(JSON.stringify(vp.seen[k][key]))),
          actual: Buffer.from(String(JSON.stringify(vn.seen[k]?.[key]))),
        });
      }
    });
    for (const key of ['names', 'log', 'turn']) {
      cases.push({ name: `hook, ${b.label}: final ${key}`, kind: 'bytes', expected: Buffer.from(String(JSON.stringify(vp.final[key]))), actual: Buffer.from(String(JSON.stringify(vn.final[key]))) });
    }
    cases.push({ name: `hook, ${b.label}: exit/stdout/stderr`, kind: 'json', expected: vp.runs, actual: vn.runs });
  });

  // ------------------------------------------------------------------ literals
  cases.push(...literalCases(py.beds[0][5], nd[0][5], 'LITERAL: the unit changed list', ['a.txt', 'dirty.txt', 'new/n.txt']));
  const turnLines = (v) => (v.log === null ? null : v.log.split('\n').filter((l) => l.includes('"via":"bash-turn"')));
  const ONE = '{"ts":"<ts>","session":"s1","seq":2,"op":"write","path":"b.txt","via":"bash-turn","from":1}';
  cases.push(
    ...literalCases(turnLines(views.py[0].seen[0]), turnLines(views.node[0].seen[0]), 'LITERAL: the hook records one bash-turn line', [ONE]),
    ...literalCases(
      views.py[0].seen[1].log === views.py[0].seen[0].log,
      views.node[0].seen[1].log === views.node[0].seen[0].log,
      'LITERAL: a second Stop in the turn adds nothing',
      true,
    ),
    ...literalCases(turnLines(views.py[0].final), turnLines(views.node[0].final), 'LITERAL: a slash-command turn still records its Bash writes', [
      ONE,
      '{"ts":"<ts>","session":"s1","seq":3,"op":"write","path":"d.txt","via":"bash-turn","from":2}',
    ]),
    ...literalCases(views.py[1].final, views.node[1].final, 'LITERAL: no repo, nothing written', { names: null, log: null, turn: null }),
    ...literalCases(views.py[2].final.names, views.node[2].final.names, 'LITERAL: a Stop with no open turn writes no touch log', null),
  );
  notes.push(`${HOOK_BEDS.length} hook beds; hook script ${hookScript('/R').filter((s) => typeof s === 'object').length} hook calls`);
  return { cases, notes };
}
