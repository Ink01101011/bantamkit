/**
 * touch-log — the touch log, the per-session tool-call counter and the PostToolUse arm (#200,
 * Task 1; job70 T200-1), Python against Node.
 *
 * THE PROPERTY: the two runtimes write the same touch-log BYTES for the same calls (key order,
 * raw UTF-8, `via`/`from` only when given), read back the same rows and the same skipped count,
 * tail the same session rows across a first line the seek cut, count the same per-session
 * `seq` into the same `ledger-<session>.seq.json` bytes, read the same fact names out of a
 * `memory_recall` reply, fold the same rows per path in code-point order, find the same repo
 * from the same directory and make the same repo-relative path. As PROCESSES, one hook script
 * (Edit, Bash, Read, Write outside the repo, NotebookEdit, a two-header `memory_recall`, a
 * `memory_save`) leaves the same touch log and the same counter; outside a repo both leave
 * nothing; an unwritable touch path is one `touch: miss` that `bantamkit_status` counts. The
 * touch log is shared on disk between the runtimes, so a disagreement is two runtimes writing
 * one user's history two ways.
 *
 * HOW. Module scenarios are op scripts run twice, by `ref/touch_ref.py` (`run_log`) against
 * `bantamkit.touch` and by `runNode` below against `dist/touch/index.js`, each over its own bed
 * built the same way. Hook beds are built at ONE path, driven by the reference, read, wiped,
 * rebuilt and driven by the port, so the repo id (a hash of the toplevel's realpath) is the
 * same on both sides; only `ts` is masked.
 *
 * THE LITERALS. A change applied to both sides leaves every differential green, so per side:
 * the first hook touch line's bytes (ts masked), the hook script's `[op, seq]` list, the
 * refusal bits of an append into an unwritable touch directory, and the status lines.
 *
 * WHAT IT DOES NOT COVER: the lock under contention and Windows paths (Task 9's manual run).
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'touch-log';
export const summary = 'touch log: line bytes, tail, per-session seq, use names, fold, repo finder; the PostToolUse arm as a process';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'touch_ref.py');
const CLI_REF = join(here, 'ref', 'cli_ref.py');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');
const SCRUBBED = ['BANTAMKIT_MEMORY_DIR', 'CLAUDE_COWORK_MEMORY_PATH_OVERRIDE', 'TOOL_METRICS_DIR', 'BANTAMKIT_DREAM_TIMEOUT_MS', 'BANTAMKIT_ASSETS'];

const ID = '0123456789abcdef';
const TS = '2026-10-16T00:00:00Z';
const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const line = (o) => `${JSON.stringify(o)}\n`;
const touch = (session, seq, kind, path, extra = {}) => ({ op: 'append_touch', session, seq, kind, path, ts: TS, ...extra });
const RECALL = 'mcp__bantamkit__memory_recall';
const SAVE = 'mcp__bantamkit__memory_save';
const REPLY = '[project] [fact-a] (project) d\nbody\n\n[profile] [fact-b] (feedback) e\nbody [x] (y) z';

/** Over TOUCH_TAIL_BYTES (65536), so the tail's seek lands inside a line. */
const BIG = Array.from({ length: 900 }, (_, i) =>
  line({ ts: TS, session: i % 3 === 0 ? 's2' : 's1', seq: i + 1, op: 'read', path: `dir/${'p'.repeat(40)}-${i}.ts` }),
).join('');

function scenarios() {
  return [
    {
      label: 'bytes: each op, via+from, Thai, astral and a lone surrogate',
      ops: [
        touch('s1', 3, 'edit', 'src/a.py'),
        touch('s1', 9, 'write', 'b.txt', { via: 'bash-turn', from: 4 }),
        { op: 'append_use', session: 's1', seq: 10, fact: 'fact-a', kind: 'recall_hit', ts: TS },
        { op: 'append_use', session: 's1', seq: 11, fact: 'ข้อเท็จจริง', kind: 'save', ts: TS },
        touch('ไทย', 12, 'read', 'เอกสาร/บันทึก.md'),
        touch('s1', 13, 'read', '😀/x\u2028y.ts'),
        touch('s1', 14, 'read', 'x\ud800y'),
        { op: 'bytes' },
        { op: 'read' },
        { op: 'skipped' },
      ],
    },
    {
      label: 'corrupt: bad lines are skipped and counted by read and by tail',
      ops: [
        touch('s1', 1, 'read', 'a'),
        { op: 'raw', b64: b64('{not json\n[1]\n"s"\n{"ts":"x","session":"s1","seq":"2","op":"read","path":"str-seq"}\n') },
        { op: 'raw', b64: b64('{"ts":"x","session":"s1","seq":true,"op":"read","path":"bool-seq"}\n{"cut":') },
        touch('s1', 5, 'read', 'b'),
        { op: 'read' },
        { op: 'skipped' },
        { op: 'tail', session: 's1', after: 0 },
        { op: 'skipped' },
        { op: 'bytes' },
      ],
    },
    {
      label: 'tail: this session after seq, across a first line the seek cut',
      ops: [
        { op: 'raw', b64: b64(BIG) },
        { op: 'tail', session: 's1', after: 0 },
        { op: 'skipped' },
        { op: 'tail', session: 's1', after: 890 },
        { op: 'tail', session: 's2', after: 895 },
        { op: 'tail', session: 'nobody', after: 0 },
      ],
    },
    {
      label: 'seq: counts per session, survives junk, names the file by the ledger rule',
      ops: [
        { op: 'current_seq', session: 's1' },
        { op: 'next_seq', session: 's1' },
        { op: 'next_seq', session: 's1' },
        { op: 'next_seq', session: 's1' },
        { op: 'next_seq', session: 's2' },
        { op: 'current_seq', session: 's1' },
        { op: 'seqfile', name: 'ledger-s1.seq.json' },
        { op: 'next_seq', session: 'a/b.c ไทย' },
        { op: 'seqfile', name: 'ledger-a_b_c____.seq.json' },
        { op: 'next_seq', session: '' },
        { op: 'seqfile', name: 'ledger-nosession.seq.json' },
        { op: 'seqraw', name: 'ledger-junk.seq.json', b64: b64('{"seq":-4}') },
        { op: 'current_seq', session: 'junk' },
        { op: 'seqraw', name: 'ledger-junk.seq.json', b64: b64('[7]') },
        { op: 'current_seq', session: 'junk' },
        { op: 'seqraw', name: 'ledger-junk.seq.json', b64: b64('{"seq":') },
        { op: 'next_seq', session: 'junk' },
        { op: 'seqfile', name: 'ledger-junk.seq.json' },
        { op: 'statelist' },
      ],
    },
    {
      label: 'unwritable: the touch path and the state path are files',
      unwritable: true,
      ops: [
        touch('s', 1, 'read', 'a'),
        { op: 'append_use', session: 's', seq: 1, fact: 'f', kind: 'save', ts: TS },
        { op: 'read' },
        { op: 'tail', session: 's', after: 0 },
        { op: 'bytes' },
        { op: 'next_seq', session: 's' },
        { op: 'current_seq', session: 's' },
      ],
    },
    {
      label: 'use names: replies, blocks, a content dict, separators, other tools',
      ops: [
        { op: 'use_names', tool: RECALL, input: { query: 'q' }, response: [{ type: 'text', text: REPLY }] },
        { op: 'use_names', tool: RECALL, input: {}, response: REPLY },
        { op: 'use_names', tool: RECALL, input: {}, response: { content: [{ type: 'text', text: '[a] (user) x' }, { type: 'image' }, { type: 'text', text: '[b] (user) y\n[a] (user) again' }] } },
        { op: 'use_names', tool: RECALL, input: {}, response: { result: '[r] [ก ไทย] (project) t' } },
        { op: 'use_names', tool: RECALL, input: {}, response: { content: null, result: '[never] (user) x' } },
        // A body line spelled like a header IS a header: the reply cannot tell them apart.
        { op: 'use_names', tool: RECALL, input: {}, response: 'intro\n[looks] (like) a header\n[x] (Caps) no\n[y](user) no' },
        { op: 'use_names', tool: RECALL, input: {}, response: 'x\r[cr] (user) d\nx\u2028[ls] (user) d\nx\u2029[ps] (user) d\n[ok] (user) d\r' },
        { op: 'use_names', tool: RECALL, input: {}, response: 42 },
        { op: 'use_names', tool: SAVE, input: { name: 'n1' }, response: 'saved' },
        { op: 'use_names', tool: SAVE, input: { name: '' }, response: 'saved' },
        { op: 'use_names', tool: SAVE, input: { name: 7 }, response: 'saved' },
        { op: 'use_names', tool: 'Bash', input: { command: 'ls' }, response: REPLY },
        { op: 'use_names', tool: 'mcp__other__memory_recall', input: {}, response: REPLY },
      ],
    },
    {
      label: 'reduce: folded and live rows per path, code-point order, uses dropped',
      ops: [
        {
          op: 'reduce',
          rows: [
            { ts: '2026-09-01T00:00:00Z', session: 'a', seq: 1, op: 'read', path: 'p' },
            { ts: '2026-09-02T00:00:00Z', session: 'a', seq: 2, op: 'edit', path: 'p' },
            { ts: '2026-09-03T00:00:00Z', session: 'a', seq: 3, op: 'use', fact: 'f', kind: 'save' },
            { ts: '2026-08-01T00:00:00Z', session: '', seq: 0, op: 'folded', path: 'p', n: 5 },
            { ts: '2026-08-01T00:00:00Z', session: '', seq: 0, op: 'folded', path: 'q', n: 'x' },
            { ts: '2026-09-04T00:00:00Z', op: 'write', path: '\uff5e.md' },
            { ts: '2026-09-05T00:00:00Z', op: 'write', path: '😀.md' },
            { ts: 5, op: 'read', path: 'ไทย' },
            { op: 'read', path: 7 },
            { op: 'delete', path: 'z' },
          ],
        },
      ],
    },
    {
      label: 'find_repo and relpath: nested, a gitdir file, no repo, outside, a symlink out',
      repo: true,
      ops: [
        { op: 'find_repo', cwd: 'repo/src' },
        { op: 'find_repo', cwd: 'repo' },
        { op: 'find_repo', cwd: 'repo/no/such/dir' },
        { op: 'find_repo', cwd: 'wt/deep' },
        { op: 'find_repo', cwd: 'plain' },
        { op: 'relpath', top: 'repo', path: 'repo/src/a.py' },
        { op: 'relpath', top: 'repo/src', path: 'repo/src/a.py' },
        { op: 'relpath', top: 'repo', path: 'repo' },
        { op: 'relpath', top: 'repo', path: 'outside.py' },
        { op: 'relpath', top: 'repo', path: 'repo/ไทย/😀.md' },
        { op: 'relpath', top: 'repo', path: 'repo/src/missing.py' },
        { op: 'relpath', top: 'repo', path: 'repo/src/../src/a.py' },
        { op: 'relpath', top: 'repo', path: 'repo/out-link/x.py' },
        { op: 'relpath', top: 'repo', path: 'repo/..repo-like' },
      ],
    },
    {
      label: 'retention: old touch lines fold per path, old uses drop, a second pass is a no-op',
      ops: [
        {
          op: 'raw',
          b64: b64(
            line({ ts: '2026-08-01T00:00:00Z', session: 'a', seq: 1, op: 'read', path: 'b.md' }) +
              line({ ts: '2026-08-02T00:00:00Z', session: 'a', seq: 2, op: 'edit', path: 'a.py' }) +
              line({ ts: '2026-08-03T00:00:00Z', session: 'a', seq: 3, op: 'use', fact: 'f', kind: 'recall_hit' }) +
              line({ ts: '2026-08-04T00:00:00Z', session: 'a', seq: 4, op: 'edit', path: 'a.py' }) +
              line({ ts: '2026-10-15T00:00:00Z', session: 'b', seq: 1, op: 'read', path: 'a.py' }) +
              line({ ts: '2026-10-15T00:00:01Z', session: 'b', seq: 2, op: 'use', fact: 'g', kind: 'save' }),
          ),
        },
        { op: 'retention', now: '2026-10-16T00:00:00.000Z' },
        { op: 'bytes' },
        { op: 'retention', now: '2026-10-17T00:00:00.000Z' },
        { op: 'bytes' },
        { op: 'status' },
        { op: 'listdir', dir: '.bantamkit/touch' },
      ],
    },
  ];
}

// --------------------------------------------------------------------- the beds

function git(args, cwd) {
  const r = spawnSync('git', args, { cwd, encoding: 'utf8' });
  if (r.status !== 0) throw new Error(`touch-log: git ${args.join(' ')} failed: ${r.stderr}`);
}

function buildBed(root, s) {
  rmSync(root, { recursive: true, force: true });
  mkdirSync(join(root, 'home'), { recursive: true });
  if (s.unwritable) {
    mkdirSync(join(root, 'home', '.bantamkit'), { recursive: true });
    writeFileSync(join(root, 'home', '.bantamkit', 'touch'), 'a file, not a dir');
    writeFileSync(join(root, 'state'), 'a file, not a dir');
  } else {
    mkdirSync(join(root, 'state'));
  }
  if (s.repo) {
    mkdirSync(join(root, 'repo', 'src'), { recursive: true });
    git(['init', '-q', join(root, 'repo')], root);
    writeFileSync(join(root, 'repo', 'src', 'a.py'), 'x\n');
    mkdirSync(join(root, 'repo', 'ไทย'));
    writeFileSync(join(root, 'repo', 'ไทย', '😀.md'), 'x\n');
    mkdirSync(join(root, 'elsewhere'));
    symlinkSync(join(root, 'elsewhere'), join(root, 'repo', 'out-link'));
    mkdirSync(join(root, 'wt', 'deep'), { recursive: true });
    mkdirSync(join(root, 'wtgit'));
    writeFileSync(join(root, 'wt', '.git'), 'gitdir: ../wtgit\n');
    mkdirSync(join(root, 'plain'));
  }
}

// --------------------------------------------------------------------- the Node half

const b64file = (p) => {
  try {
    return readFileSync(p).toString('base64');
  } catch {
    return null;
  }
};
const relTo = (root, p) => relative(root, p).split('\\').join('/');
const absIn = (root, p) => (isAbsolute(p) ? p : join(root, p));

function runNodeBed(touch, tiers, retention, bed) {
  const root = bed.root;
  const log = new touch.TouchLog(bed.home, bed.repo_id);
  const out = [];
  for (const op of bed.ops) {
    switch (op.op) {
      case 'append_touch':
        out.push(log.appendTouch(op.session, op.seq, op.kind, op.path, op.via ?? null, op.from ?? null, op.ts));
        break;
      case 'append_use':
        out.push(log.appendUse(op.session, op.seq, op.fact, op.kind, op.ts));
        break;
      case 'raw':
        mkdirSync(dirname(log.path), { recursive: true });
        writeFileSync(log.path, Buffer.from(op.b64, 'base64'), { flag: 'a' });
        out.push(null);
        break;
      case 'read':
        out.push(log.read());
        break;
      case 'tail':
        out.push(log.tail(op.session, op.after));
        break;
      case 'skipped':
        out.push(log.skipped);
        break;
      case 'bytes':
        out.push(b64file(log.path));
        break;
      case 'next_seq':
        try {
          out.push(touch.nextSeq(bed.state, op.session));
        } catch {
          out.push('error');
        }
        break;
      case 'current_seq':
        out.push(touch.currentSeq(bed.state, op.session));
        break;
      case 'seqfile':
        out.push(b64file(join(bed.state, op.name)));
        break;
      case 'seqraw':
        writeFileSync(join(bed.state, op.name), Buffer.from(op.b64, 'base64'));
        out.push(null);
        break;
      case 'statelist':
        try {
          out.push(readdirSync(bed.state).sort());
        } catch {
          out.push(null);
        }
        break;
      case 'use_names':
        out.push(touch.useNames(op.tool, op.input, op.response));
        break;
      case 'reduce':
        out.push(touch.touchReducer(op.rows));
        break;
      case 'find_repo': {
        const r = touch.findRepo(absIn(root, op.cwd));
        out.push(r === null ? null : { top_rel: relTo(root, r.top), gitdir_rel: relTo(root, r.gitdir), id_len: r.id.length });
        break;
      }
      case 'relpath': {
        const r = touch.findRepo(absIn(root, op.top));
        out.push(r === null ? null : touch.relPath(r, absIn(root, op.path)));
        break;
      }
      case 'status':
        out.push([...tiers.logLines(bed.home).filter((l) => l.startsWith('logs: touch/')), tiers.touchLine(bed.home)]);
        break;
      case 'retention': {
        const saved = process.env.BANTAMKIT_RETENTION;
        delete process.env.BANTAMKIT_RETENTION;
        let rep;
        try {
          rep = retention.runRetention(bed.home, [], op.now);
        } finally {
          if (saved !== undefined) process.env.BANTAMKIT_RETENTION = saved;
        }
        out.push({ folded: rep.folded.map((p) => relTo(bed.home, p)), rotated: rep.rotated.map((p) => relTo(bed.home, p)) });
        break;
      }
      case 'listdir':
        try {
          out.push(readdirSync(join(bed.home, op.dir)).sort());
        } catch {
          out.push(null);
        }
        break;
      default:
        throw new Error(`touch-log: unknown op ${op.op}`);
    }
  }
  return out;
}

// --------------------------------------------------------------------- the hook half

function runHookPy(ctx, { cwd, home, payload }) {
  const env = { HOME: home, USERPROFILE: home };
  for (const k of SCRUBBED) env[k] = null;
  const a = ctx.runPython(CLI_REF, { argv: ['--hook'], cwd, env, timeout: 120, stdin: b64(JSON.stringify(payload)) });
  if (a.error) throw new Error(`cli_ref.py: ${a.error}`);
  return { exit: a.exit, stdout: Buffer.from(a.stdout ?? '', 'base64').toString('utf8'), stderr: Buffer.from(a.stderr ?? '', 'base64').toString('utf8') };
}

function runHookNode(_ctx, { cwd, home, payload }) {
  const env = { ...process.env, HOME: home, USERPROFILE: home };
  for (const k of SCRUBBED) delete env[k];
  const r = spawnSync(process.execPath, [CLI, '--hook'], { cwd, env, input: JSON.stringify(payload), encoding: 'utf8', timeout: 120_000 });
  return { exit: r.status, stdout: r.stdout ?? '', stderr: r.stderr ?? '' };
}

/** The hook script. `R` is the repo toplevel; every payload carries `cwd: R`. */
function hookScript(R, outside) {
  const p = (tool, tool_input, extra = {}) => ({ hook_event_name: 'PostToolUse', session_id: 's1', cwd: R, tool_name: tool, tool_input, ...extra });
  return [
    p('Edit', { file_path: join(R, 'src', 'a.py'), old_string: 'x', new_string: 'y' }),
    p('Bash', { command: 'cat src/a.py > /dev/null' }),
    p('Read', { file_path: join(R, 'src', 'a.py') }),
    p('Write', { file_path: join(outside, 'elsewhere.txt'), content: 'z' }),
    p('NotebookEdit', { notebook_path: join(R, 'nb.ipynb'), new_source: '' }),
    p(RECALL, { query: 'store' }, { tool_response: [{ type: 'text', text: REPLY }] }),
    p(SAVE, { name: 'saved-fact', type: 'project', description: 'd', body: 'b' }, { tool_response: 'saved saved-fact' }),
  ];
}

const HOOK_BEDS = [
  { label: 'a git repo', repo: true },
  { label: 'no repo', repo: false },
  { label: 'an unwritable touch path', repo: true, unwritable: true, only: 3 },
];

function buildHookBed(root, b) {
  rmSync(root, { recursive: true, force: true });
  const home = join(root, 'home');
  const R = join(root, 'repo');
  mkdirSync(home, { recursive: true });
  mkdirSync(join(R, 'src'), { recursive: true });
  mkdirSync(join(root, 'outside'));
  if (b.repo) git(['init', '-q', R], root);
  writeFileSync(join(R, 'src', 'a.py'), 'x\n');
  if (b.unwritable) {
    mkdirSync(join(home, '.bantamkit'), { recursive: true });
    writeFileSync(join(home, '.bantamkit', 'touch'), 'a file, not a dir');
  }
  return { home, R: realpathSync.native(R), outside: realpathSync.native(join(root, 'outside')) };
}

const maskTs = (s) => s.replace(/"ts":"[^"]*"/g, '"ts":"<ts>"');

function hookView(home) {
  const dir = join(home, '.bantamkit', 'touch');
  let names = null;
  try {
    names = readdirSync(dir).sort();
  } catch {
    /* no touch directory */
  }
  const logName = names?.find((n) => n.endsWith('.jsonl'));
  const logText = logName ? readFileSync(join(dir, logName), 'utf8') : null;
  let misses = [];
  try {
    misses = readFileSync(join(home, '.bantamkit', 'hooks', 'hook-log.jsonl'), 'utf8')
      .split('\n')
      .filter(Boolean)
      .map((l) => JSON.parse(l))
      .filter((r) => r.touch === 'miss')
      .map((r) => ({ event: r.event, touch: r.touch, tool: r.tool ?? null }));
  } catch {
    /* no hook log */
  }
  return {
    names: names === null ? null : names.map((n) => n.replace(/^[0-9a-f]{16}\.jsonl$/, '<id>.jsonl')),
    log: logText === null ? null : maskTs(logText),
    seq: b64file(join(home, '.bantamkit', 'hooks', 'ledger-s1.seq.json')),
    misses,
  };
}

// ------------------------------------------------------------------------- literals

function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `${label} — python`, kind, expected, actual: pySide },
    { name: `${label} — node`, kind, expected, actual: nodeSide },
  ];
}

// ------------------------------------------------------------------------------ run

export async function run(ctx) {
  const touch = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'touch', 'index.js')).href);
  const tiers = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'storage', 'tiers.js')).href);
  const retention = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'storage', 'retention.js')).href);
  const cases = [];
  const notes = [];

  // ----------------------------------------------------------- module scenarios
  const all = scenarios();
  const beds = { py: [], node: [] };
  all.forEach((s, i) => {
    for (const side of ['py', 'node']) {
      const root = join(ctx.scratch, `touch-log-${String(i + 1).padStart(2, '0')}`, side);
      buildBed(root, s);
      const real = realpathSync.native(root);
      beds[side].push({ root: real, home: join(real, 'home'), state: join(real, 'state'), repo_id: ID, ops: s.ops });
    }
  });
  const py = ctx.runPython(REF, { suite: 'touch-log', beds: beds.py });
  const nd = { beds: beds.node.map((bed) => runNodeBed(touch, tiers, retention, bed)) };
  const isBytes = (op) => op.op === 'bytes' || op.op === 'seqfile';
  const asBytes = (v) => (v === null ? Buffer.from('<no file>') : Buffer.from(v, 'base64'));
  all.forEach((s, i) => {
    s.ops.forEach((op, j) => {
      const what = [op.op, op.kind, op.session !== undefined ? JSON.stringify(op.session) : '', op.name ?? '', op.cwd ?? '', op.path ?? '', op.tool ?? '']
        .filter(Boolean)
        .join(' ');
      cases.push({
        name: `${s.label} — #${String(j).padStart(2, '0')} ${what}`,
        kind: isBytes(op) ? 'bytes' : 'json',
        expected: isBytes(op) ? asBytes(py.beds[i][j]) : py.beds[i][j],
        actual: isBytes(op) ? asBytes(nd.beds[i][j]) : nd.beds[i][j],
      });
    });
  });
  notes.push(`${all.length} module scenarios, ${all.reduce((n, s) => n + s.ops.length, 0)} ops per side`);

  // ----------------------------------------------------------------- hook beds
  const views = { py: [], node: [] };
  HOOK_BEDS.forEach((b, i) => {
    const root = join(ctx.scratch, `touch-log-hook-${i + 1}`);
    for (const side of ['py', 'node']) {
      const { home, R, outside } = buildHookBed(root, b);
      const script = hookScript(R, outside);
      const steps = b.only ? script.slice(b.only - 1, b.only) : script;
      const runs = steps.map((payload) => (side === 'py' ? runHookPy : runHookNode)(ctx, { cwd: R, home, payload }));
      const status = side === 'py'
        ? ctx.runPython(REF, { suite: 'touch-log', beds: [{ root, home, state: join(home, '.bantamkit', 'hooks'), repo_id: ID, ops: [{ op: 'status' }] }] }).beds[0][0]
        : runNodeBed(touch, tiers, retention, { root, home, state: join(home, '.bantamkit', 'hooks'), repo_id: ID, ops: [{ op: 'status' }] })[0];
      views[side].push({
        ...hookView(home),
        status: status.map((l) => l.replace(/^logs: touch\/[0-9a-f]{16} /, 'logs: touch/<id> ')),
        runs: runs.map((r) => ({ exit: r.exit, stdout: r.stdout, stderr: r.stderr })),
      });
    }
    for (const key of ['names', 'log', 'seq', 'misses', 'status', 'runs']) {
      cases.push({
        name: `hook, ${b.label}: ${key}`,
        kind: key === 'log' || key === 'seq' ? 'bytes' : 'json',
        expected: key === 'log' || key === 'seq' ? Buffer.from(String(views.py[i][key])) : views.py[i][key],
        actual: key === 'log' || key === 'seq' ? Buffer.from(String(views.node[i][key])) : views.node[i][key],
      });
    }
  });

  // ------------------------------------------------------------------ literals
  const firstLine = (v) => (v.log === null ? '<no log>' : v.log.split('\n')[0]);
  cases.push(
    ...literalCases(
      firstLine(views.py[0]),
      firstLine(views.node[0]),
      'LITERAL: the first hook touch line',
      '{"ts":"<ts>","session":"s1","seq":1,"op":"edit","path":"src/a.py"}',
    ),
  );
  const opSeq = (v) => (v.log === null ? null : v.log.split('\n').filter(Boolean).map((l) => [JSON.parse(l).op, JSON.parse(l).seq]));
  cases.push(
    ...literalCases(opSeq(views.py[0]), opSeq(views.node[0]), 'LITERAL: the hook script records [op, seq]', [
      ['edit', 1],
      ['read', 3],
      ['edit', 5],
      ['use', 6],
      ['use', 6],
      ['use', 7],
    ]),
  );
  cases.push(
    ...literalCases(views.py[0].seq, views.node[0].seq, 'LITERAL: the counter after seven calls', b64('{"seq":7}')),
    ...literalCases(views.py[1].names, views.node[1].names, 'LITERAL: no repo, no touch directory', null),
    ...literalCases(views.py[1].seq, views.node[1].seq, 'LITERAL: no repo, no counter', null),
  );
  const unw = all.findIndex((s) => s.unwritable);
  cases.push(
    ...literalCases([py.beds[unw][0], py.beds[unw][1]], [nd.beds[unw][0], nd.beds[unw][1]], 'LITERAL: appends into an unwritable touch directory', [false, false]),
  );
  cases.push(
    ...literalCases(views.py[0].status, views.node[0].status, 'LITERAL: status after the hook script', [
      `logs: touch/<id> ${Buffer.byteLength(views.py[0].log ?? '') - 6 * ('<ts>'.length - TS.length)} (0 rotated, 0 skipped)`,
      'touch: 0 missed writes (hook log)',
    ]),
    ...literalCases(views.py[1].status, views.node[1].status, 'LITERAL: status with no touch directory', ['touch: none']),
    ...literalCases(views.py[2].status, views.node[2].status, 'LITERAL: status after one forced miss', ['touch: 1 missed write (hook log)']),
  );
  notes.push(`${HOOK_BEDS.length} hook beds; hook script ${hookScript('/R', '/O').length} PostToolUse calls`);
  return { cases, notes };
}
