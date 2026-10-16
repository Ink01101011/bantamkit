/**
 * touch-summary — the B summaries (#200, E1-B, Task 6; job70 T200-6), Python against Node.
 *
 * THE PROPERTY: over the same touch rows the two runtimes say the same line, byte for byte:
 * the previous session (latest touch `ts`, a tie to the smaller session id BY CODE POINT, the
 * current session, `""` and malformed rows never chosen), its edited files most recently touched
 * first (reads never listed), the commits and the uncommitted count, every line cut to 600
 * BYTES of UTF-8 and never inside a character; after a compaction, this session's edits only.
 * As PROCESSES, SessionStart `startup` and `compact` over one git bed inject the same context,
 * with the B line just before the toolbox part, git's `--since/--until` read as UTC under
 * `TZ=Asia/Bangkok`. A disagreement is the two runtimes telling one user two histories.
 *
 * HOW. One module request to `ref/touch_ref.py` (`run_summary`) against `bantamkit.touch.summary`,
 * the same calls in-process against `dist/touch/index.js`; `display` is a fixed table on both
 * sides. Hook beds are built at ONE path, driven by the reference, wiped, rebuilt and driven by
 * the port, so the repo id is the same; the age is masked (`\d+ (min|h|d) ago|just now`).
 *
 * THE LITERALS. A change made to both sides leaves every differential green, so per side: the
 * unit test's line bytes, the exactly-600-byte fixture kept whole (600) and the 601-byte one
 * cut to 598, and the hook's startup line.
 *
 * WHAT IT DOES NOT COVER: git absent from PATH (both take `git`'s `None`/`null`, pinned in
 * touch-turn), Windows (Task 9's manual run), and latency (the bench).
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'touch-summary';
export const summary = 'B summaries: the last session line, the compact line, the 600-byte cap; SessionStart as processes';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'touch_ref.py');
const CLI_REF = join(here, 'ref', 'cli_ref.py');
const SCRUBBED = ['BANTAMKIT_MEMORY_DIR', 'CLAUDE_COWORK_MEMORY_PATH_OVERRIDE', 'TOOL_METRICS_DIR', 'BANTAMKIT_DREAM_TIMEOUT_MS', 'BANTAMKIT_ASSETS'];
const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');

// --------------------------------------------------------------------- fixtures

const r = (seq, path, op = 'edit', session = 'old', ts = null, extra = {}) => ({
  ts: ts || `2026-10-15T10:00:${String(seq).padStart(2, '0')}Z`,
  session,
  seq,
  op,
  path,
  ...extra,
});

const ROWS = [
  r(1, 'src/store.ts'),
  r(2, 'src/retrieval.ts', 'read'),
  r(3, 'src/retrieval.ts'),
  r(4, 'src/factfile.ts', 'write'),
  r(5, 'x.txt', 'write', 'old', null, { via: 'bash-turn', from: 4 }),
  r(6, 'y.txt'),
  r(7, 'now.py', 'edit', 'current', '2026-10-15T13:00:00Z'),
];
const MINE = ROWS.slice(0, 6);
const BASE = { 'src/store.ts': 'store.ts', 'src/retrieval.ts': 'retrieval.ts', 'src/factfile.ts': 'factfile.ts' };
const STEP1 =
  '[bantamkit touch] last session here (2026-10-15, 3 h ago): edited 5 files — y.txt, x.txt, factfile.ts (+2); commits: feat: one (#199); fix: two; uncommitted: 4 files';

/** A one-edit line whose uncapped bytes are `600 + over`, the last character `tail`. */
function sized(over, tail) {
  const head = '[bantamkit touch] last session here (2026-10-15, just now): edited 1 file — ';
  const pad = 600 + over - Buffer.byteLength(head) - Buffer.byteLength(tail);
  return { rows: [r(1, 'p')], now: '2026-10-15T10:00:01Z', table: { p: 'a'.repeat(pad) + tail }, commits: [], u: 0 };
}

function request() {
  // the three most recent names are long enough that both near-cap lines are CUT, inside them
  const thai = { 'y.txt': 'ไทย'.repeat(25) + 'y', 'x.txt': '😀'.repeat(60) + 'x', 'src/factfile.ts': 'ก😀'.repeat(12), 'src/store.ts': 'ไทย'.repeat(20) };
  const lines = [
    { rows: MINE, now: '2026-10-15T13:00:06Z', table: { ...BASE, 'x.txt': 'x.txt', 'y.txt': 'y.txt' }, commits: ['feat: one (#199)', 'fix: two'], u: 4 },
    { rows: [r(1, 'a', 'read')], now: '2026-10-15T13:00:00Z', table: {}, commits: [], u: 9 },
    { rows: [r(1, 'a', 'read')], now: '2026-10-15T10:00:01Z', table: {}, commits: ['a', 'b', 'c', 'd', 'e'], u: 1 },
    { rows: MINE, now: '2026-10-18T10:00:06Z', table: BASE, commits: Array.from({ length: 7 }, (_, i) => `J68-${i} ` + 'ก'.repeat(25)), u: 0 },
    { rows: MINE, now: '2026-10-15T10:59:59Z', table: thai, commits: ['ก'.repeat(300), '😀'.repeat(40), 'x'], u: 12 },
    { rows: MINE, now: '2026-10-15T10:00:06Z', table: thai, commits: [], u: 1 },
    sized(0, 'ก'), // exactly 600 bytes: kept whole
    sized(1, 'ก'), // 601: the Thai character is dropped whole
    sized(0, '😀'),
    sized(2, '😀'),
    { rows: [r(1, 'a'), r(1, 'b'), r(2, 'a', 'read'), { ts: 'bad', session: 'old', seq: 9, op: 'edit', path: 'z' }], now: '2026-10-15T10:01:00Z', table: {}, commits: [], u: 0 },
    { rows: [r(1, 'a', 'edit', 'old', null, { seq: 1.0 }), r(3, 'b', 'write', 'old', null, { seq: 'x' }), r(2, 'c')], now: '2026-10-15T10:00:03Z', table: {}, commits: [], u: 0 },
  ];
  const tie = [r(1, 'a', 'edit', '￿'), r(1, 'a', 'edit', '😀'), r(1, 'a', 'edit', 'b')];
  const prev = [
    [ROWS, 'current'],
    [[...ROWS, { ts: '2026-10-16T00:00:00Z', session: '', seq: 0, op: 'folded', path: 'p', n: 3 }], 'current'],
    [tie, 'b'], // U+FFFF beats U+1F600 by code point; UTF-16 would say the opposite
    [[r(1, 'a', 'edit', 'b'), r(1, 'a', 'edit', 'a'), r(1, 'a', 'edit', 'c')], 'x'],
    [[r(1, 'a', 'edit', 's')], 's'],
    [[r(1, 'a', 'use', 'u', null, { fact: 'f' }), { ts: '2026-02-30T00:00:00Z', session: 'd', seq: 1, op: 'edit', path: 'a' }, { ts: '2026-10-15T10:00:00Z', session: 7, seq: 1, op: 'edit', path: 'a' }], 'x'],
    [[r(1, 'a', 'read', 'early', '2026-10-15T09:00:00Z'), r(1, 'a', 'read', 'late', '2026-10-15T11:00:00Z'), r(2, 'b', 'edit', 'early', '2026-10-15T10:00:00Z')], 'x'],
    [[], 'x'],
  ];
  const twelve = Array.from({ length: 12 }, (_, i) => r(i + 1, `f${String(i + 1).padStart(2, '0')}.py`, i % 3 === 0 ? 'write' : 'edit', 's'));
  const compact = [
    [twelve, 's', {}],
    [[r(1, 'a.py', 'edit', 's'), r(2, 'b.py', 'read', 's'), r(3, 'c.py', 'write', 's')], 's', {}],
    [[r(1, 'a.py', 'read', 's')], 's', {}],
    [[r(1, 'a.py', 'edit', 'other')], 's', {}],
    [[r(1, 'a/b.py', 'edit', 's'), r(2, 'a/b.py', 'edit', 's')], 's', { 'a/b.py': 'b.py' }],
    [Array.from({ length: 10 }, (_, i) => r(i + 1, `p${i}`, 'edit', 's')), 's', Object.fromEntries(Array.from({ length: 10 }, (_, i) => [`p${i}`, 'ไทย'.repeat(10) + i]))],
  ];
  return {
    ages: [0, 59, 60, 3599, 3600, 172799, 172800, -5, 3 * 86400 + 1],
    prev,
    lines: lines.map((l) => [l.rows, l.now, l.table, l.commits, l.u]),
    compact,
    uncommitted: ['', 'R  b.txt\0ab c.txt\0 M d.txt\0?? e.txt\0', 'C  x\0y\0RM z\0w\0', ' M ไทย/😀.txt\0', 'garbage', 'MM a\0'],
    shift: [['2026-10-15T23:50:00Z', 1800], ['2026-12-31T23:59:59Z', 1], ['2028-02-28T23:45:00Z', 1800]],
  };
}

function runNode(touch, req) {
  const show = (table) => {
    const m = new Map(Object.entries(table));
    return (p) => (m.has(p) ? m.get(p) : p);
  };
  return {
    ages: req.ages.map((s) => touch.ageText(s)),
    prev: req.prev.map(([rows, cur]) => touch.previousSession(rows, cur)),
    lines: req.lines.map(([rows, now, t, commits, u]) => touch.lastSessionLine(rows, now, show(t), commits, u)),
    compact: req.compact.map(([rows, sid, t]) => touch.compactLine(rows, sid, show(t))),
    uncommitted: req.uncommitted.map((s) => touch.uncommittedCount(s)),
    shift: req.shift.map(([ts, n]) => touch.shiftTs(ts, n)),
  };
}

// --------------------------------------------------------------------- the hook half

function git(args, cwd, date = null) {
  const env = { ...process.env, ...(date ? { GIT_COMMITTER_DATE: date, GIT_AUTHOR_DATE: date } : {}) };
  const x = spawnSync('git', args, { cwd, env, encoding: 'utf8' });
  if (x.status !== 0) throw new Error(`touch-summary: git ${args.join(' ')} failed: ${x.stderr}`);
}

/** One git bed: three tracked files sharing a basename, two commits at fixed dates, one dirty. */
function buildHookBed(root, touch, seed) {
  rmSync(root, { recursive: true, force: true });
  const home = join(root, 'home');
  const R0 = join(root, 'repo');
  mkdirSync(home, { recursive: true });
  mkdirSync(R0, { recursive: true });
  const R = realpathSync.native(R0);
  git(['init', '-q'], R);
  for (const f of ['src/store.ts', 'lib/store.ts', 'src/retrieval.ts', 'ไทย/😀.txt', 'a.txt', 'b.txt']) {
    mkdirSync(dirname(join(R, f)), { recursive: true });
    writeFileSync(join(R, f), '1\n');
  }
  git(['add', '.'], R);
  git(['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'before the session'], R, '2026-10-15T09:00:00Z');
  writeFileSync(join(R, 'a.txt'), '2\n');
  git(['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qam', 'J68-3 keywords (#199)'], R, '2026-10-15T10:20:00Z');
  writeFileSync(join(R, 'b.txt'), '3\n');
  git(['mv', 'a.txt', 'c.txt'], R);
  if (seed) {
    const log = new touch.TouchLog(home, touch.findRepo(R).id);
    log.appendTouch('old', 1, 'edit', 'src/store.ts', null, null, '2026-10-15T10:00:01Z');
    log.appendTouch('old', 2, 'read', 'src/retrieval.ts', null, null, '2026-10-15T10:00:02Z');
    log.appendTouch('old', 3, 'write', 'ไทย/😀.txt', null, null, '2026-10-15T10:00:03Z');
    log.appendTouch('old', 4, 'write', 'b.txt', 'bash-turn', 3, '2026-10-15T10:00:04Z');
    log.appendTouch('now', 1, 'edit', 'src/retrieval.ts', null, null, '2026-10-17T10:00:00Z');
    log.appendTouch('now', 2, 'read', 'lib/store.ts', null, null, '2026-10-17T10:00:01Z');
  }
  return { home, R };
}

function runHook(ctx, side, { cwd, home, payload }) {
  if (side === 'py') {
    const env = { HOME: home, USERPROFILE: home, TZ: 'Asia/Bangkok' };
    for (const k of SCRUBBED) env[k] = null;
    const a = ctx.runPython(CLI_REF, { argv: ['--hook'], cwd, env, timeout: 120, stdin: b64(JSON.stringify(payload)) });
    if (a.error) throw new Error(`cli_ref.py: ${a.error}`);
    return { exit: a.exit, stdout: Buffer.from(a.stdout ?? '', 'base64').toString('utf8'), stderr: Buffer.from(a.stderr ?? '', 'base64').toString('utf8') };
  }
  const env = { ...process.env, HOME: home, USERPROFILE: home, TZ: 'Asia/Bangkok' };
  for (const k of SCRUBBED) delete env[k];
  const x = spawnSync(process.execPath, [join(ctx.runtimeTs, 'dist', 'cli.js'), '--hook'], { cwd, env, input: JSON.stringify(payload), encoding: 'utf8', timeout: 120_000 });
  return { exit: x.status, stdout: x.stdout ?? '', stderr: x.stderr ?? '' };
}

const HOOK_BEDS = [
  { label: 'startup, a seeded touch log', source: 'startup', seed: true },
  { label: 'compact, a seeded touch log', source: 'compact', seed: true },
  { label: 'resume, no touch log', source: 'resume', seed: false },
];

const maskAge = (s) => s.replace(/\d+ (min|h|d) ago|just now/g, '<age>');
const touchPart = (stdout) => {
  try {
    return JSON.parse(stdout).hookSpecificOutput.additionalContext.split('\n\n').find((p) => p.startsWith('[bantamkit touch]')) ?? null;
  } catch {
    return null;
  }
};

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

  const req = request();
  const py = ctx.runPython(REF, { suite: 'touch-summary', ...req });
  const nd = runNode(touch, req);
  for (const key of ['ages', 'prev', 'lines', 'compact', 'uncommitted', 'shift']) {
    req[key].forEach((_, i) => {
      const bytes = key === 'lines' || key === 'compact';
      cases.push({
        name: `${key} #${String(i).padStart(2, '0')}`,
        kind: bytes ? 'bytes' : 'json',
        expected: bytes ? Buffer.from(py[key][i]) : py[key][i],
        actual: bytes ? Buffer.from(nd[key][i]) : nd[key][i],
      });
    });
  }
  notes.push(`module: ${['ages', 'prev', 'lines', 'compact', 'uncommitted', 'shift'].map((k) => `${req[k].length} ${k}`).join(', ')}`);

  // ----------------------------------------------------------------- hook beds
  const runs = { py: [], node: [] };
  HOOK_BEDS.forEach((b, i) => {
    const root = join(ctx.scratch, `touch-summary-hook-${i + 1}`);
    for (const side of ['py', 'node']) {
      const { home, R } = buildHookBed(root, touch, b.seed);
      const payload = { hook_event_name: 'SessionStart', source: b.source, session_id: 'now', cwd: R };
      const got = runHook(ctx, side, { cwd: R, home, payload });
      runs[side].push({ ...got, stdout: maskAge(got.stdout) });
    }
    cases.push({ name: `hook, ${b.label}: exit/stdout/stderr`, kind: 'json', expected: runs.py[i], actual: runs.node[i] });
  });

  // ------------------------------------------------------------------ literals
  const len = (s) => Buffer.byteLength(s);
  cases.push(
    ...literalCases(py.lines[0], nd.lines[0], 'LITERAL: the unit test line', STEP1),
    ...literalCases(len(py.lines[6]), len(nd.lines[6]), 'LITERAL: the exactly-600-byte line is kept whole', 600),
    ...literalCases(len(py.lines[7]), len(nd.lines[7]), 'LITERAL: the 601-byte line is cut to 598, never inside a character', 598),
    ...literalCases(
      [len(py.lines[4]) <= 600 && len(py.lines[4]) > 590, len(py.lines[5]) <= 600 && len(py.lines[5]) > 590],
      [len(nd.lines[4]) <= 600 && len(nd.lines[4]) > 590, len(nd.lines[5]) <= 600 && len(nd.lines[5]) > 590],
      'LITERAL: the Thai/astral lines are cut, to within a character of 600 bytes',
      [true, true],
    ),
    ...literalCases(py.prev[2]?.[0], nd.prev[2]?.[0], 'LITERAL: a tie goes to the smaller id by code point', '￿'),
    ...literalCases(
      touchPart(runs.py[0].stdout),
      touchPart(runs.node[0].stdout),
      'LITERAL: the hook startup line',
      '[bantamkit touch] last session here (2026-10-15, <age>): edited 3 files — b.txt, 😀.txt, src/store.ts; commits: J68-3 keywords (#199); uncommitted: 2 files',
    ),
    ...literalCases(touchPart(runs.py[1].stdout), touchPart(runs.node[1].stdout), 'LITERAL: the hook compact line lists edits only', '[bantamkit touch] edited in this session before compaction: retrieval.ts'),
    ...literalCases(touchPart(runs.py[2].stdout), touchPart(runs.node[2].stdout), 'LITERAL: no touch log, no line', null),
  );
  notes.push(`${HOOK_BEDS.length} hook beds (TZ=Asia/Bangkok)`);
  return { cases, notes };
}
