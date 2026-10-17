/**
 * touch-bound — the three reviewer fixes of #200 (job70 T200-10), Python against Node.
 *
 * THE PROPERTIES.
 * 1. No git, nothing recorded (spec, Error handling: "No git, or not inside a repo | Nothing
 *    is recorded"). `git_on_path` / `gitOnPath` answer whether a `git` executable is on PATH by
 *    a stat walk (never a subprocess): POSIX `<dir>/git`, a regular file with an execute bit;
 *    Windows `<dir>/git<ext>` per `PATHEXT` (default `.COM;.EXE;.BAT;.CMD`). As PROCESSES, a
 *    PostToolUse Read and Edit inside a repo with no git on PATH write no counter and no touch
 *    log on either side; the same calls with git reachable through a symlinked PATH dir do.
 * 2. No dead work. While `W_CONTEXT == 0` and via is off, UserPromptSubmit builds no touch
 *    context: no graph file is written, the hook-log record carries no `context` count, and the
 *    reply bytes are each runtime's same answer. With `BANTAMKIT_VIA=on` the graph is built.
 * 3. A bounded log. An append that leaves the live touch log over `TOUCH_LOG_CAP_BYTES`
 *    (1,000,000) folds the older half (`fold_cutoff`: every line with `ts <=` the `ts` of the
 *    first object line ending past the byte midpoint) through `touch_reducer`, under the lock.
 *    Compared as bytes after the append; a log written within one second folds too.
 *
 * THE LITERALS. A change applied to both sides leaves every differential green, so per side:
 * the `git_on_path` answers, the cutoffs, the bounded log's size under the cap with the new
 * line last, no counter and no touch directory with no git, the touch lines with git, no graph
 * directory and no `context` key in the default state, one graph file with via on.
 *
 * 4. (T200-11) The bound HOLDS. `bound_body` leaves any log at or under
 *    `TOUCH_LOG_FOLD_TARGET_BYTES` (750,000): the midpoint fold, then folded rows aged out
 *    oldest `ts` first (ties by path), and the whole file folded when the newer half alone is
 *    over the target. Beds: a folded block alone over half the cap (6,000 distinct paths, the
 *    re-review's stuck state) and alone over the cap (12,000), no `ts` on any line, `ts` out
 *    of order. Appends after the fold, past the target, do not rewrite (no thrash). A held lock skips
 *    the fold (`bound` answers false, the append lands as a plain line), and `bound` on a
 *    directory answers false, never throws.
 *
 * THE LITERALS. A change applied to both sides leaves every differential green, so per side:
 * the `git_on_path` answers, the cutoffs, the bounded log's size under the cap with the new
 * line last, no counter and no touch directory with no git, the touch lines with git, no graph
 * directory and no `context` key in the default state, one graph file with via on; and
 * (T200-11) every body at or under 750,000 bytes, the stuck bed's kept folded rows a suffix
 * of the (ts, path) order with their count, four appends after the fold past the target and
 * still plain appends, the held-lock
 * log the raw bytes plus one line, `bound` on a directory false.
 *
 * WHAT IT DOES NOT COVER: a real Windows PATH (the Windows rule runs simulated, `windows: true`,
 * over POSIX directories), and two appenders folding at once (the per-runtime race tests in
 * `test_touch_log.py` / `touch-log.test.mjs` run that, as processes).
 */
import { execFileSync, spawnSync } from 'node:child_process';
import { chmodSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'touch-bound';
export const summary = 'touch fixes: no git on PATH records nothing (stat walk, PATHEXT), no context work while W_CONTEXT is 0 and via off, the touch log folded on append over its byte cap';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'touch_ref.py');
const CLI_REF = join(here, 'ref', 'cli_ref.py');
const SCRUBBED = ['BANTAMKIT_MEMORY_DIR', 'CLAUDE_COWORK_MEMORY_PATH_OVERRIDE', 'TOOL_METRICS_DIR', 'BANTAMKIT_DREAM_TIMEOUT_MS', 'BANTAMKIT_ASSETS', 'BANTAMKIT_VIA'];
const ID = '0123456789abcdef';
const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const line = (o) => `${JSON.stringify(o)}\n`;
const CAP = 1_000_000;

// ------------------------------------------------------------------- git_on_path beds

/** The PATH fixtures under `root`; each entry `[label, path, pathext, windows]`. */
function gitBeds(root) {
  rmSync(root, { recursive: true, force: true });
  const d = (n) => {
    const p = join(root, n);
    mkdirSync(p, { recursive: true });
    return p;
  };
  const exe = d('exe');
  writeFileSync(join(exe, 'git'), '#!/bin/sh\n');
  chmodSync(join(exe, 'git'), 0o755);
  const noexec = d('noexec');
  writeFileSync(join(noexec, 'git'), 'x');
  chmodSync(join(noexec, 'git'), 0o644);
  const dirgit = d('dirgit');
  mkdirSync(join(dirgit, 'git'));
  const empty = d('empty');
  const link = d('link');
  symlinkSync(join(exe, 'git'), join(link, 'git'));
  const dangling = d('dangling');
  symlinkSync(join(root, 'nowhere', 'git'), join(dangling, 'git'));
  const winexe = d('winexe');
  writeFileSync(join(winexe, 'git.exe'), 'x');
  const wincmd = d('wincmd');
  writeFileSync(join(wincmd, 'git.CMD'), 'x');
  return [
    ['posix: an executable git', exe, '', false],
    ['posix: git without an execute bit', noexec, '', false],
    ['posix: a directory named git', dirgit, '', false],
    ['posix: an empty dir, then the executable', `${empty}:${exe}`, '', false],
    ['posix: empty entries only', '::', '', false],
    ['posix: an empty PATH', '', '', false],
    ['posix: a symlink to git', link, '', false],
    ['posix: a dangling symlink', dangling, '', false],
    ['posix: a ;-joined PATH is one entry', `${empty};${exe}`, '', false],
    ['windows: git.exe with PATHEXT .EXE', winexe, '.EXE', true],
    ['windows: git.exe with PATHEXT unset (default)', winexe, '', true],
    ['windows: git.CMD by the default', wincmd, '', true],
    ['windows: git.exe, PATHEXT .COM;.BAT', winexe, '.COM;.BAT', true],
    ['windows: a bare git is not enough', exe, '', true],
    ['windows: ;-joined, empty entries skipped', `;${empty};;${winexe}`, '.exe;.EXE', true],
    ['windows: a :-joined PATH is one entry', `${empty}:${winexe}`, '.EXE', true],
  ];
}

// --------------------------------------------------------------------- fold_cutoff

const ts = (s) => `2026-10-17T00:00:${String(s).padStart(2, '0')}Z`;
const row = (s, seq, p) => ({ ts: ts(s), session: 'a', seq, op: 'read', path: p });
const CUTOFFS = [
  ['empty', ''],
  ['one line', line(row(1, 1, 'a'))],
  ['four lines, four seconds', [1, 2, 3, 4].map((s) => line(row(s, s, `p${s}`))).join('')],
  ['midpoint on junk, then a line', `${'{bad\n'.repeat(40)}${line(row(9, 1, 'x'))}`],
  ['midpoint after the last object', `${line(row(1, 1, 'x'))}${'z'.repeat(400)}\n`],
  ['no ts / an empty ts / a numeric ts past the midpoint', `${line(row(1, 1, 'x'))}${line({ op: 'read', path: 'y' })}${line({ ts: '', op: 'read' })}${line({ ts: 5, op: 'read' })}${line(row(7, 2, 'z'))}`],
  ['a cut last line', `${line(row(1, 1, 'a'))}${line(row(2, 2, 'b'))}{"ts":"2026-10-17T00:00:03Z","se`],
  ['Thai paths count bytes, not characters', [line(row(1, 1, 'ไ'.repeat(30))), line(row(2, 2, 'b')), line(row(3, 3, 'c'))].join('')],
];

// ---------------------------------------------------------------------- bound beds

/** A log just past the cap, its lines over `secs` distinct seconds; the next append folds. */
function bigLog(secs) {
  let out = '';
  let i = 0;
  while (Buffer.byteLength(out) <= CAP) {
    const s = Math.floor((i * secs) / 11000);
    out += i % 10 === 9
      ? line({ ts: ts(s % 60), session: `s${i % 3}`, seq: i + 1, op: 'use', fact: `f${i % 7}`, kind: 'recall_hit' })
      : line({ ts: ts(s % 60), session: `s${i % 3}`, seq: i + 1, op: i % 3 ? 'read' : 'edit', path: `src/f${i % 50}.ts` });
    i += 1;
  }
  return out;
}
const NEW = { op: 'append_touch', session: 'now', seq: 1, kind: 'read', path: 'src/new.ts', ts: '2026-10-17T00:01:00Z' };
const BOUND = [
  { label: 'under the cap: no fold', ops: [{ op: 'raw', b64: b64(bigLog(40).slice(0, 5000).replace(/[^\n]*$/, '')) }, NEW, { op: 'bytes' }] },
  { label: 'over the cap: the older half folds', ops: [{ op: 'raw', b64: b64(bigLog(40)) }, NEW, { op: 'bytes' }, NEW, { op: 'bytes' }] },
  { label: 'over the cap within one second: still folds', ops: [{ op: 'raw', b64: b64(bigLog(0)) }, NEW, { op: 'bytes' }] },
  { label: 'a use line crosses the cap', ops: [{ op: 'raw', b64: b64(bigLog(40)) }, { op: 'append_use', session: 'now', seq: 2, fact: 'f', kind: 'save', ts: '2026-10-17T00:01:00Z' }, { op: 'bytes' }] },
];

// ------------------------------------------------------------ T200-11 beds

const TARGET = 750_000;
const STUCK_KEPT = 3843; // the reference's count; `maximal` below checks it independently
/** The re-review's stuck state: `f` folded rows (ts spread over 28 days), then live lines past the cap. */
function stuckLog(f) {
  let out = '';
  for (let i = 0; i < f; i++) {
    out += line({ ts: `2026-09-${String(1 + ((i * 7919) % 28)).padStart(2, '0')}T00:00:00Z`, session: '', seq: 0, op: 'folded', path: `src/module_${String(i).padStart(6, '0')}/component_file.py`, n: 1 + (i % 5) });
  }
  for (let i = 0; Buffer.byteLength(out) <= CAP; i++) out += line({ ts: `2026-10-02T00:00:${String(i % 60).padStart(2, '0')}Z`, session: 's', seq: i + 1, op: 'read', path: `src/x${i}.py` });
  return out;
}
function noTsLog() {
  let out = '';
  for (let i = 0; Buffer.byteLength(out) <= CAP; i++) out += line({ session: 's', seq: i + 1, op: 'read', path: `src/n${i % 9000}.py` });
  return out;
}
/** The older half stamped LATER than the newer half: the midpoint cutoff keeps nearly everything. */
function outOfOrderLog() {
  let out = '';
  for (let i = 0; Buffer.byteLength(out) <= CAP / 2; i++) out += line({ ts: '2026-10-09T00:00:00Z', session: 's', seq: i + 1, op: 'read', path: `src/late${i % 4000}.py` });
  for (let i = 0; Buffer.byteLength(out) <= CAP; i++) out += line({ ts: '2026-10-01T00:00:00Z', session: 's', seq: i + 1, op: 'edit', path: `src/early${i % 4000}.py` });
  return out;
}
const STUCK = stuckLog(6000);
const BODIES = [
  ['the folded block alone over half the cap (6,000 paths)', STUCK],
  ['the folded block alone over the cap (12,000 paths)', stuckLog(12000)],
  ['no line carries a ts', noTsLog()],
  ['ts out of order', outOfOrderLog()],
  ['an ordinary log just past the cap', bigLog(40)],
  ['empty', ''],
];
/** Four appends after the fold: the slack under the target is under one folded line, so these cross it. */
const AFTER = [2, 3, 4, 5].map((k) => ({ ...NEW, seq: k, path: `src/new${k}.ts` }));
const HELD = [
  { label: 'stuck: the folded block alone over half the cap', ops: [{ op: 'raw', b64: b64(STUCK) }, NEW, { op: 'bytes' }, ...AFTER, { op: 'bytes' }] },
  { label: 'the lock is held: the append lands, no fold', ops: [{ op: 'raw', b64: b64(bigLog(40)) }, { op: 'lock' }, NEW, { op: 'bytes' }, { op: 'bound' }, { op: 'unlock' }, { op: 'bytes' }] },
  { label: 'bound on a directory', ops: [{ op: 'logdir' }, { op: 'bound' }] },
];

function runNodeHeld(touch, bed) {
  const log = new touch.TouchLog(bed.home, bed.repo_id);
  const out = [];
  for (const op of bed.ops) {
    if (['raw', 'bytes', 'append_touch'].includes(op.op)) {
      out.push(...runNodeBed(touch, { ...bed, ops: [op] }));
      continue;
    }
    if (op.op === 'bound') {
      try {
        out.push(log.bound());
      } catch {
        out.push('threw');
      }
      continue;
    }
    mkdirSync(dirname(log.path), { recursive: true });
    if (op.op === 'lock') writeFileSync(`${log.path}.lock`, '');
    else if (op.op === 'unlock') rmSync(`${log.path}.lock`, { force: true });
    else if (op.op === 'logdir') mkdirSync(log.path);
    else throw new Error(`touch-bound: unknown op ${op.op}`);
    out.push(null);
  }
  return out;
}

function runNodeBed(touch, bed) {
  const log = new touch.TouchLog(bed.home, bed.repo_id);
  const out = [];
  for (const op of bed.ops) {
    if (op.op === 'append_touch') out.push(log.appendTouch(op.session, op.seq, op.kind, op.path, null, null, op.ts));
    else if (op.op === 'append_use') out.push(log.appendUse(op.session, op.seq, op.fact, op.kind, op.ts));
    else if (op.op === 'raw') {
      mkdirSync(dirname(log.path), { recursive: true });
      writeFileSync(log.path, Buffer.from(op.b64, 'base64'), { flag: 'a' });
      out.push(null);
    } else if (op.op === 'bytes') {
      try {
        out.push(readFileSync(log.path).toString('base64'));
      } catch {
        out.push(null);
      }
    } else throw new Error(`touch-bound: unknown op ${op.op}`);
  }
  return out;
}

// ----------------------------------------------------------------------- hook beds

function git(cwd, ...a) {
  execFileSync('git', ['-c', 'user.email=t@t', '-c', 'user.name=t', '-c', 'commit.gpgsign=false', '-C', cwd, ...a], {
    stdio: 'pipe',
    env: { ...process.env, GIT_CONFIG_NOSYSTEM: '1', LC_ALL: 'C' },
  });
}

function factFile(store, nm, desc) {
  const d = join(store, 'facts');
  mkdirSync(d, { recursive: true });
  writeFileSync(join(d, `${nm}.md`), `---\nname: ${nm}\ndescription: ${desc}\ntype: project\ncreated: '2026-10-15'\nlast_recalled: null\nlinks: []\n---\n\nbody text\n`);
}

/** `pathMode`: 'nogit' (an empty bin dir), 'link' (a dir holding a symlink to git), 'inherit'. */
function buildHookBed(root) {
  rmSync(root, { recursive: true, force: true });
  const home = join(root, 'home');
  const R = join(root, 'repo');
  mkdirSync(home, { recursive: true });
  mkdirSync(join(R, 'src'), { recursive: true });
  writeFileSync(join(R, 'src', 'a.py'), 'a\n');
  git(R, 'init', '-q');
  git(R, 'add', 'src');
  git(R, 'commit', '-qm', 'one');
  const store = join(R, '.bantamkit', 'memory');
  factFile(store, 'fa', 'notes about src/a.py');
  factFile(store, 'gate-fact', 'gateway rollout plan details');
  mkdirSync(join(root, 'nogit'));
  mkdirSync(join(root, 'gitlink'));
  const realGit = execFileSync('/bin/sh', ['-c', 'command -v git'], { encoding: 'utf8' }).trim();
  symlinkSync(realGit, join(root, 'gitlink', 'git'));
  return { home: realpathSync.native(home), R: realpathSync.native(R), nogit: join(root, 'nogit'), gitlink: join(root, 'gitlink') };
}

const PROMPT = 'explain the gateway rollout plan please';
const HOOK_BEDS = [
  { label: 'no git on PATH', path: 'nogit', via: null, events: ['read', 'edit'] },
  { label: 'git through a symlinked PATH dir', path: 'gitlink', via: null, events: ['read', 'edit'] },
  { label: 'UserPromptSubmit, W_CONTEXT 0 and via off', path: 'inherit', via: null, events: ['edit', 'ups'] },
  { label: 'UserPromptSubmit, BANTAMKIT_VIA=on', path: 'inherit', via: 'on', events: ['edit', 'ups'] },
];

function payloadOf(ev, R) {
  const p = { session_id: 's1', cwd: R };
  if (ev === 'read') return { ...p, hook_event_name: 'PostToolUse', tool_name: 'Read', tool_input: { file_path: join(R, 'src', 'a.py') } };
  if (ev === 'edit') return { ...p, hook_event_name: 'PostToolUse', tool_name: 'Edit', tool_input: { file_path: join(R, 'src', 'a.py') } };
  return { ...p, hook_event_name: 'UserPromptSubmit', prompt: PROMPT };
}

function envFor(bed, b) {
  const env = { HOME: bed.home, USERPROFILE: bed.home, BANTAMKIT_INDEX_DIR: join(bed.home, 'index'), BANTAMKIT_RETENTION: 'off' };
  if (b.path === 'nogit') env.PATH = bed.nogit;
  if (b.path === 'gitlink') env.PATH = bed.gitlink;
  if (b.via !== null) env.BANTAMKIT_VIA = b.via;
  return env;
}

function runHookPy(ctx, bed, b, payload) {
  const env = envFor(bed, b);
  for (const k of SCRUBBED) if (!(k in env)) env[k] = null;
  const a = ctx.runPython(CLI_REF, { argv: ['--hook'], cwd: bed.R, env, timeout: 120, stdin: b64(JSON.stringify(payload)) });
  if (a.error) throw new Error(`cli_ref.py: ${a.error}`);
  return { exit: a.exit, stdout: Buffer.from(a.stdout ?? '', 'base64').toString('utf8'), stderr: Buffer.from(a.stderr ?? '', 'base64').toString('utf8') };
}

function runHookNode(ctx, bed, b, payload) {
  const env = { ...process.env };
  for (const k of SCRUBBED) delete env[k];
  Object.assign(env, envFor(bed, b));
  const r = spawnSync(process.execPath, [join(ctx.runtimeTs, 'dist', 'cli.js'), '--hook'], { cwd: bed.R, env, input: JSON.stringify(payload), encoding: 'utf8', timeout: 120_000 });
  return { exit: r.status, stdout: r.stdout ?? '', stderr: r.stderr ?? '' };
}

const listdir = (p) => {
  try {
    return readdirSync(p).sort();
  } catch {
    return null;
  }
};

function hookView(home) {
  const touchDir = join(home, '.bantamkit', 'touch');
  const names = listdir(touchDir);
  const logName = names?.find((n) => n.endsWith('.jsonl'));
  const ops = logName
    ? readFileSync(join(touchDir, logName), 'utf8').split('\n').filter(Boolean).map((l) => [JSON.parse(l).op, JSON.parse(l).seq, JSON.parse(l).path])
    : null;
  let seq = null;
  try {
    seq = readFileSync(join(home, '.bantamkit', 'hooks', 'ledger-s1.seq.json'), 'utf8');
  } catch {
    /* no counter */
  }
  let ups = [];
  try {
    ups = readFileSync(join(home, '.bantamkit', 'hooks', 'hook-log.jsonl'), 'utf8')
      .split('\n')
      .filter(Boolean)
      .map((l) => JSON.parse(l))
      .filter((x) => x.event === 'UserPromptSubmit')
      .map(({ ts: _ts, ms: _ms, ...rest }) => rest);
  } catch {
    /* no hook log */
  }
  const graph = listdir(join(home, '.bantamkit', 'graph'));
  return {
    touch: names === null ? null : names.map((n) => n.replace(/^[0-9a-f]{16}\.jsonl$/, '<id>.jsonl')),
    ops,
    seq,
    graph: graph === null ? null : graph.map((n) => n.replace(/^[0-9a-f]{16}\.json$/, '<id>.json')),
    ups,
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

  // ------------------------------------------------- git_on_path, fold_cutoff, bound
  const gb = gitBeds(join(ctx.scratch, 'touch-bound-git'));
  const beds = { py: [], node: [] };
  const held = { py: [], node: [] };
  const mkBeds = (list, prefix, into) =>
    list.forEach((s, i) => {
      for (const side of ['py', 'node']) {
        const root = join(ctx.scratch, `${prefix}-${i + 1}`, side);
        rmSync(root, { recursive: true, force: true });
        mkdirSync(join(root, 'home'), { recursive: true });
        const real = realpathSync.native(root);
        into[side].push({ root: real, home: join(real, 'home'), state: join(real, 'state'), repo_id: ID, ops: s.ops });
      }
    });
  mkBeds(BOUND, 'touch-bound', beds);
  mkBeds(HELD, 'touch-bound-held', held);
  const py = ctx.runPython(REF, {
    suite: 'touch-bound',
    git: gb.map(([, p, e, w]) => [p, e, w]),
    cutoffs: CUTOFFS.map(([, d]) => b64(d)),
    beds: beds.py,
    bodies: BODIES.map(([, d]) => b64(d)),
    held: held.py,
  });
  const nd = {
    git: gb.map(([, p, e, w]) => touch.gitOnPath(p, e, w)),
    cutoffs: CUTOFFS.map(([, d]) => touch.foldCutoff(Buffer.from(d, 'utf8'))),
    beds: beds.node.map((bed) => runNodeBed(touch, bed)),
    bodies: BODIES.map(([, d]) => touch.boundBody(Buffer.from(d, 'utf8')).toString('base64')),
    held: held.node.map((bed) => runNodeHeld(touch, bed)),
  };
  gb.forEach(([label], i) => cases.push({ name: `git_on_path: ${label}`, kind: 'json', expected: py.git[i], actual: nd.git[i] }));
  CUTOFFS.forEach(([label], i) => cases.push({ name: `fold_cutoff: ${label}`, kind: 'json', expected: py.cutoffs[i], actual: nd.cutoffs[i] }));
  const asBytes = (v) => (v === null ? Buffer.from('<no file>') : Buffer.from(v, 'base64'));
  BOUND.forEach((s, i) => {
    s.ops.forEach((op, j) => {
      cases.push({
        name: `bound, ${s.label} — #${j} ${op.op}`,
        kind: op.op === 'bytes' ? 'bytes' : 'json',
        expected: op.op === 'bytes' ? asBytes(py.beds[i][j]) : py.beds[i][j],
        actual: op.op === 'bytes' ? asBytes(nd.beds[i][j]) : nd.beds[i][j],
      });
    });
  });

  const GIT_EXPECTED = [true, false, false, true, false, false, true, false, false, true, true, true, false, false, true, false];
  cases.push(...literalCases(py.git, nd.git, 'LITERAL: git_on_path over the sixteen PATHs', GIT_EXPECTED));
  cases.push(
    ...literalCases(py.cutoffs, nd.cutoffs, 'LITERAL: fold_cutoff', [
      null,
      `${ts(1)}~`,
      `${ts(3)}~`,
      `${ts(9)}~`,
      null,
      `${ts(7)}~`,
      `${ts(2)}~`,
      `${ts(1)}~`,
    ]),
  );
  /** [size <= cap, a folded line first, the appended line last, lines] after an append. */
  const shape = (v, last) => {
    const text = asBytes(v).toString('utf8');
    const ls = text.split('\n').filter(Boolean);
    return [Buffer.byteLength(text) <= CAP, ls.length > 0 && JSON.parse(ls[0]).op === 'folded', ls.length > 0 && JSON.parse(ls[ls.length - 1])[last[0]] === last[1], ls.length];
  };
  const sideShape = (b, i, j, last) => shape(b[i][j], last);
  const under = (b) => sideShape(b, 0, 2, ['path', 'src/new.ts']).slice(0, 3);
  cases.push(...literalCases(under(py.beds), under(nd.beds), 'LITERAL: under the cap nothing folds', [true, false, true]));
  const over = (b) => [sideShape(b, 1, 2, ['path', 'src/new.ts']).slice(0, 3), sideShape(b, 1, 4, ['path', 'src/new.ts']).slice(0, 3)];
  cases.push(...literalCases(over(py.beds), over(nd.beds), 'LITERAL: over the cap, [under the cap, folded first, new line last] twice', [[true, true, true], [true, true, true]]));
  const flat = (b) => sideShape(b, 2, 2, ['path', 'src/new.ts']);
  cases.push(...literalCases(flat(py.beds), flat(nd.beds), 'LITERAL: one second folds everything into one line per path (45), then the new line', [true, true, true, 46]));
  const use = (b) => sideShape(b, 3, 2, ['fact', 'f']).slice(0, 3);
  cases.push(...literalCases(use(py.beds), use(nd.beds), 'LITERAL: a use append folds too', [true, true, true]));
  notes.push(`${gb.length} PATH fixtures, ${CUTOFFS.length} cutoffs, ${BOUND.length} bound beds (cap ${CAP})`);

  // ------------------------------------------------ T200-11: the bound holds, no thrash, no unlocked fold
  BODIES.forEach(([label], i) => cases.push({ name: `bound_body: ${label}`, kind: 'bytes', expected: asBytes(py.bodies[i]), actual: asBytes(nd.bodies[i]) }));
  HELD.forEach((s, i) => {
    s.ops.forEach((op, j) => {
      cases.push({
        name: `held, ${s.label} — #${j} ${op.op}`,
        kind: op.op === 'bytes' ? 'bytes' : 'json',
        expected: op.op === 'bytes' ? asBytes(py.held[i][j]) : py.held[i][j],
        actual: op.op === 'bytes' ? asBytes(nd.held[i][j]) : nd.held[i][j],
      });
    });
  });
  const sizes = (side) => side.bodies.map((v) => asBytes(v).length <= TARGET);
  cases.push(...literalCases(sizes(py), sizes(nd), 'LITERAL: every bound_body at or under 750,000 bytes', BODIES.map(() => true)));
  /** The stuck bed's first fold: [size <= target, kept folded rows are a suffix of the (ts, path) order, their count, the new line last]. */
  const stuckRule = (side) => {
    const ls = asBytes(side.held[0][2]).toString('utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
    const kept = new Set(ls.filter((r) => r.op === 'folded').map((r) => r.path));
    const order = STUCK.split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((r) => r.op === 'folded')
      .sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
    const firstKept = order.findIndex((r) => kept.has(r.path));
    const suffix = firstKept >= 0 && order.slice(firstKept).every((r) => kept.has(r.path));
    // maximal: the newest row aged out would not have fit (its folded line, `n` as written)
    const size = asBytes(side.held[0][2]).length;
    const maximal = firstKept > 0 && size + Buffer.byteLength(line(order[firstKept - 1])) > TARGET;
    return [size <= TARGET, suffix, maximal, kept.size, ls[ls.length - 1].path];
  };
  cases.push(...literalCases(stuckRule(py), stuckRule(nd), 'LITERAL: stuck log, [under the target, oldest folded rows aged out, no more than needed, kept, new line last]', [true, true, true, STUCK_KEPT, 'src/new.ts']));
  const lineOf = (o) => Buffer.from(line({ ts: o.ts, session: o.session, seq: o.seq, op: o.kind, path: o.path }));
  const noThrash = (side) => {
    const end = asBytes(side.held[0][7]);
    return [end.length > TARGET, end.equals(Buffer.concat([asBytes(side.held[0][2]), ...AFTER.map(lineOf)]))];
  };
  cases.push(...literalCases(noThrash(py), noThrash(nd), 'LITERAL: four appends after the fold, [past the target, plain appends (no rewrite)]', [true, true]));
  const lockedNoFold = (side) => [
    asBytes(side.held[1][3]).equals(Buffer.concat([Buffer.from(bigLog(40)), Buffer.from(line({ ts: NEW.ts, session: NEW.session, seq: NEW.seq, op: NEW.kind, path: NEW.path }))])),
    side.held[1][4],
    asBytes(side.held[1][6]).equals(asBytes(side.held[1][3])),
  ];
  cases.push(...literalCases(lockedNoFold(py), lockedNoFold(nd), 'LITERAL: lock held, [raw plus the line, bound false, still unchanged]', [true, false, true]));
  cases.push(...literalCases(py.held[2][1], nd.held[2][1], 'LITERAL: bound on a directory answers false', false));
  notes.push(`${BODIES.length} bound bodies, ${HELD.length} held beds (target ${TARGET})`);

  // ----------------------------------------------------------------- hook beds
  const views = { py: [], node: [] };
  HOOK_BEDS.forEach((b, i) => {
    const root = join(ctx.scratch, `touch-bound-hook-${i + 1}`);
    for (const side of ['py', 'node']) {
      const bed = buildHookBed(root);
      const runs = b.events.map((ev) => (side === 'py' ? runHookPy : runHookNode)(ctx, bed, b, payloadOf(ev, bed.R)));
      views[side].push({ ...hookView(bed.home), runs });
    }
    for (const key of ['touch', 'ops', 'seq', 'graph', 'ups', 'runs']) {
      cases.push({ name: `hook, ${b.label}: ${key}`, kind: 'json', expected: views.py[i][key], actual: views.node[i][key] });
    }
  });
  const pick = (i, f) => [f(views.py[i]), f(views.node[i])];
  cases.push(...literalCases(...pick(0, (v) => [v.touch, v.seq]), 'LITERAL: no git on PATH, no touch directory and no counter', [null, null]));
  cases.push(
    ...literalCases(...pick(1, (v) => [v.ops, v.seq]), 'LITERAL: git through a symlink, two touch lines and the counter', [
      [
        ['read', 1, 'src/a.py'],
        ['edit', 2, 'src/a.py'],
      ],
      '{"seq":2}',
    ]),
  );
  cases.push(
    ...literalCases(
      ...pick(2, (v) => [v.graph, v.ups.map((r) => 'context' in r), v.runs.map((r) => r.exit)]),
      'LITERAL: default state, no graph directory, no context key, exits 0',
      [null, [false], [0, 0]],
    ),
  );
  cases.push(...literalCases(...pick(3, (v) => [v.graph, v.ups.map((r) => r.context)]), 'LITERAL: via on, the graph is built and the context counted', [['<id>.json'], [1]]));
  // The default reply is what the via-on reply is minus its via line: the context moved nothing.
  const reply = (v) => {
    const out = v.runs[v.runs.length - 1].stdout;
    return out ? JSON.parse(out).hookSpecificOutput.additionalContext.split('\n').filter((l) => !l.includes(' [via ')) : null;
  };
  cases.push(...literalCases(reply(views.py[2]), reply(views.node[2]), 'LITERAL: default reply equals the via-on reply without its via line', reply(views.py[3])));
  notes.push(`${HOOK_BEDS.length} hook beds as processes`);
  return { cases, notes };
}
