#!/usr/bin/env node
/**
 * The Python/Node conformance harness.
 *
 *   node tools/conformance/run.mjs --suite codec --require-byte-identical
 *   node tools/conformance/run.mjs --all
 *   node tools/conformance/run.mjs --list
 *
 * WHY THERE IS A PYTHON IN HERE, AND WHY THAT IS NOT A VIOLATION
 * -------------------------------------------------------------
 * This harness shells out to the repo venv's CPython to produce the REFERENCE side of
 * every comparison. That is a DEVELOPMENT-TIME dependency of the test tooling. The
 * invariant the job is under — "the published package must run under npx with no Python at
 * runtime" — is about the SHIPPED package, and nothing under `tools/` ships: `runtime-ts`
 * declares `files: ["dist", "assets"]`. `npm test` never runs this. If you are reading this
 * because you found a Python reference in a Node port and it looked wrong: it is the
 * opposite. Deleting it would mean the port's claim of byte-compatibility rests on someone
 * having read two sources and agreed that they match, which is exactly the check that has
 * never once caught the difference that mattered.
 *
 * ADDING A SUITE
 * --------------
 * Drop a module in `suites/`. Nothing here changes — suites are discovered by directory
 * listing, not by a registry someone has to remember to edit. A suite module exports:
 *
 *   export const name = 'codec';                  // must equal the filename stem
 *   export const summary = 'one line';
 *   export async function run(ctx) { return { cases, notes } }
 *
 * and each case is
 *
 *   { name, kind: 'bytes' | 'string' | 'json', expected, actual, ruling? }
 *
 * `expected` is Python's answer, `actual` is Node's. `kind` decides how they are compared
 * AND which `--require-*` flag the case satisfies. `ruling` is for a case that is SUPPOSED
 * to differ: it carries the reason, the case is required to differ, and a ruling whose case
 * has quietly started matching fails too — a stale ruling is a lie in a comment.
 *
 * ctx = { python, repoRoot, runtimeTs, scratch, runPython(scriptPath, payload) }
 */
import { spawn, spawnSync } from 'node:child_process';
import { closeSync, existsSync, mkdirSync, mkdtempSync, openSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = dirname(dirname(here));
const suitesDir = join(here, 'suites');

// ------------------------------------------------------------------- process group

/**
 * NO CHILD OUTLIVES THE RUN (#316 G4, J90-RF3, J90-RR2 F4).
 *
 * Suites run in this process and spawn their children from it, so when the suite bound below
 * fires, the stuck suite's children are still running. MEASURED by J90-RR2: a `version` suite
 * hung on a spawned `sleep 417`, bound 60 s, and the sleep was still alive after the run had
 * exited 1.
 *
 * POSIX. The run re-executes itself as the leader of a NEW process group (`detached: true` is
 * `setsid()`), so every child any suite starts, and every grandchild whose parent has already
 * gone, carries this group's id. Then:
 *   - when the suite bound fires, the runner SIGKILLs every member of its group but itself
 *     (`ps -A -o pid=,pgid=`, the one listing macOS and Linux spell the same way) and carries on;
 *   - when the run ends, however it ends, the launcher SIGKILLs whatever is left of the group;
 *   - SIGINT, SIGTERM and SIGHUP to the launcher are forwarded to the group, and if the launcher
 *     itself disappears (SIGKILL) the runner notices within a second and kills its own group.
 * A child that deliberately starts its OWN session (`detached: true`) is outside the group and
 * is not touched: no suite does that (the Retention child is kept off below).
 *
 * WINDOWS has no process groups, and Job Objects are not reachable from Node without a native
 * addon. There is no re-exec; when the bound fires, and at the end of a run in which it fired,
 * the runner lists its own children (`Get-CimInstance Win32_Process`, by ParentProcessId) and
 * ends each one's whole tree with `taskkill /T /F`. What that cannot reach: a grandchild whose
 * parent already exited, because Windows keeps no live parent link for it. Not exercised on
 * this machine (macOS); the CI matrix runs this file on windows-latest.
 */
const GROUP_ENV = 'BANTAMKIT_CONFORMANCE_GROUP_LAUNCHER';

if (process.platform !== 'win32' && !process.env[GROUP_ENV]) {
  const runner = spawn(process.execPath, [...process.execArgv, fileURLToPath(import.meta.url), ...process.argv.slice(2)], {
    stdio: 'inherit',
    detached: true,
    env: { ...process.env, [GROUP_ENV]: String(process.pid) },
  });
  const killGroup = (signal) => {
    try {
      process.kill(-runner.pid, signal);
    } catch {
      /* ESRCH: the group is already empty */
    }
  };
  for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(signal, () => killGroup(signal));
  runner.on('error', (e) => {
    console.error(`conformance: could not start the runner: ${e.message}`);
    process.exit(2);
  });
  runner.on('exit', (code, signal) => {
    killGroup('SIGKILL');
    if (signal) {
      // End the same way, so the caller sees the signal it would have seen without the re-exec.
      process.removeAllListeners(signal);
      process.kill(process.pid, signal);
    }
    process.exit(code ?? 1);
  });
  // Nothing below runs in the launcher. The runner keeps the loop alive until it exits.
  await new Promise(() => {});
}

const launcherPid = Number(process.env[GROUP_ENV] ?? 0);
delete process.env[GROUP_ENV];

/** Every process this run started that is still alive, ended; the runner itself excepted. */
function killRunChildren() {
  if (process.platform === 'win32') {
    const listed = spawnSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-NonInteractive',
        '-Command',
        `Get-CimInstance Win32_Process -Filter "ParentProcessId=${process.pid}" | ForEach-Object { $_.ProcessId }`,
      ],
      { encoding: 'utf8', timeout: 60_000, windowsHide: true },
    );
    for (const pid of (listed.stdout ?? '').split(/\s+/).filter(Boolean)) {
      spawnSync('taskkill', ['/T', '/F', '/PID', pid], { stdio: 'ignore', timeout: 60_000, windowsHide: true });
    }
    return;
  }
  if (!launcherPid) return; // not the group leader: nothing here owns a group to clear
  const listed = spawnSync('ps', ['-A', '-o', 'pid=,pgid='], { encoding: 'utf8' });
  for (const line of (listed.stdout ?? '').split('\n')) {
    const [pid, pgid] = line.trim().split(/\s+/).map(Number);
    if (pgid !== process.pid || pid === process.pid) continue;
    try {
      process.kill(pid, 'SIGKILL');
    } catch {
      /* already gone */
    }
  }
}

if (launcherPid) {
  setInterval(() => {
    try {
      process.kill(launcherPid, 0);
    } catch (e) {
      if (e.code === 'ESRCH') process.kill(-process.pid, 'SIGKILL');
    }
  }, 1000).unref();
}

// ------------------------------------------------------------------------------ argv

const argv = process.argv.slice(2);
const wanted = [];
let all = false;
let list = false;
let requireByteIdentical = false;
let requireExactStrings = false;
const options = {};
for (let i = 0; i < argv.length; i += 1) {
  const a = argv[i];
  if (a === '--suite') wanted.push(argv[(i += 1)]);
  else if (a === '--all') all = true;
  else if (a === '--list') list = true;
  else if (a === '--require-byte-identical') requireByteIdentical = true;
  else if (a === '--require-exact-strings') requireExactStrings = true;
  else if (a.startsWith('--') && a.includes('=')) {
    const [k, v] = [a.slice(2, a.indexOf('=')), a.slice(a.indexOf('=') + 1)];
    options[k] = v;
  } else if (a.startsWith('--')) {
    options[a.slice(2)] = argv[(i += 1)];
  } else {
    die(`unexpected argument ${JSON.stringify(a)}`);
  }
}

function die(message) {
  console.error(`conformance: ${message}`);
  process.exit(2);
}

const available = existsSync(suitesDir)
  ? readdirSync(suitesDir).filter((f) => f.endsWith('.mjs')).map((f) => f.slice(0, -4)).sort()
  : [];

if (list) {
  for (const s of available) console.log(s);
  process.exit(0);
}

const selected = all ? available : wanted;
if (selected.length === 0) {
  die('nothing to run: pass --suite <name>, --all, or --list');
}
for (const s of selected) {
  if (!available.includes(s)) die(`no such suite ${JSON.stringify(s)}; have: ${available.join(', ') || '(none)'}`);
}

// ------------------------------------------------------------------------- python side

/**
 * The reference interpreter. Default is the repo venv, because that is the interpreter
 * whose PyYAML version the port was measured against — a system Python with a different
 * PyYAML would compare the port to something the product does not ship.
 *
 * A git WORKTREE has no `.venv` of its own; `git rev-parse --git-common-dir` names the main
 * checkout, which does. Falling back there beats hardcoding a sibling path, and beats
 * making every worktree run pass `--python`.
 */
function findPython() {
  const explicit = options.python ?? process.env.BANTAMKIT_CONFORMANCE_PYTHON;
  if (explicit) return { path: explicit, tried: [explicit] };
  const tried = [join(repoRoot, '.venv', 'bin', 'python'), join(repoRoot, '.venv', 'Scripts', 'python.exe')];
  try {
    const commonDir = spawnSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], {
      cwd: repoRoot,
      encoding: 'utf8',
    }).stdout?.trim();
    if (commonDir) {
      const main = dirname(commonDir);
      tried.push(join(main, '.venv', 'bin', 'python'), join(main, '.venv', 'Scripts', 'python.exe'));
    }
  } catch {
    /* not a checkout; the venv candidates still apply */
  }
  return { path: tried.find((p) => existsSync(p)) ?? tried[0], tried };
}

const { path: python, tried: pythonTried } = findPython();

if (!existsSync(python)) {
  die(
    `reference interpreter not found; tried:\n    ${pythonTried.join('\n    ')}\n` +
      '  pass --python <path> or set BANTAMKIT_CONFORMANCE_PYTHON.\n' +
      '  this is a DEV dependency of the harness; the shipped package needs no Python.',
  );
}

/**
 * How long one reference child may take before it is treated as stuck.
 *
 * MEASURED, not chosen: instrumenting `runPython` over a full `--all` run timed 355 calls,
 * and the slowest was `store_ref.py` at 50,139 ms. Everything else finished under 1.5 s.
 * Ten minutes is twelve times the slowest honest call, which puts it firmly in "this is
 * stuck" rather than "this machine is loaded" — a Windows runner is several times slower
 * than the laptop this was taken on and still has an order of magnitude of room.
 *
 * WHY THE BOUND EXISTS AT ALL. On 2026-09-05 a full run sat for 1h09m with a
 * `shiftwork_ref.py` child stuck, producing NO output — no case, no note, no error — and
 * ended only because it was killed by hand. `spawnSync` waits forever by default, so
 * nothing in this file would ever have ended it.
 *
 * WHY IT IS SMALLER THAN THE CI JOB DEADLINE, DELIBERATELY. `.github/workflows/ci.yml`
 * caps each job at 30 minutes. That cap kills the runner and reports "took too long",
 * which names nothing. This one fires first and names the script, the interpreter, and
 * whether the child had written anything at all — the three facts that decide where to
 * look next. A job deadline is a backstop; this is the diagnostic.
 *
 * `BANTAMKIT_CONFORMANCE_REF_TIMEOUT_MS` overrides it. That exists so the arm can be
 * DEMONSTRATED rather than asserted — see the note in `docs/conformance.md` — and not so a
 * slow machine can be papered over. If a real call needs more than ten minutes, the call is
 * the thing to look at.
 */
const DEFAULT_REF_TIMEOUT_MS = 600_000;
const REF_TIMEOUT_MS = Number(process.env.BANTAMKIT_CONFORMANCE_REF_TIMEOUT_MS ?? DEFAULT_REF_TIMEOUT_MS);

/**
 * A SUITE THAT DOES NOT SETTLE IS ONE RED SUITE, NOT A SILENT EXIT (#316 G4, J90-RF2).
 *
 * MEASURED by J90-RR with the mypyc extensions in-tree: `version.mjs` awaited an answer from a
 * server child that had already died on import, so `mod.run(ctx)` never settled; with nothing
 * left on the event loop Node ended the process with exit 13 ("Warning: Detected unsettled
 * top-level await" at the `await mod.run(ctx)` below), printed no PASS/FAIL line, and the
 * suites after `version` never ran. Two ways a suite can fail to settle, two arms:
 *
 *   - NOTHING LEFT TO RUN. Node emits `beforeExit` when the loop drains; the pending suite is
 *     rejected from there (through `setImmediate`, so the loop has work again and a second
 *     stalled suite gets its own `beforeExit`), and the run carries on to the next suite.
 *   - STILL BUSY, FOREVER (a child that never exits, a timer that never stops). The per-suite
 *     bound below, 15 minutes. It must fire BEFORE the CI job deadline (`.github/workflows/
 *     ci.yml`, `timeout-minutes: 30` on both jobs, which also covers checkout, installs and
 *     `npm test`): a bound equal to the deadline never fires there, and the job dies naming
 *     nothing (J90-RR2 F4). MEASURED (J90-RF3, each suite alone, `--suite <name>`, macOS
 *     laptop, all 56 PASS): the slowest suite is `wire` at 219.3 s, then `instructions` 100.9 s
 *     and `hooks` 100.7 s. 15 minutes is about four times the slowest, for slower runners, and
 *     sits above the 10-minute reference-child bound, so a stuck reference child is still named
 *     by that sharper diagnostic first. When the bound fires, every child the run started is
 *     killed (see *process group* above) and the run carries on to the next suite.
 *
 * `BANTAMKIT_CONFORMANCE_SUITE_TIMEOUT_MS` overrides the bound, so the arm can be demonstrated
 * (`runtime-py/tests/test_conformance_harness_resilience.py`). Anything else that ends the
 * process inside a suite (an uncaught exception in a suite's callback, a `die`) still prints a
 * FAIL line naming the suite, from the `exit` listener below.
 */
const DEFAULT_SUITE_TIMEOUT_MS = 900_000;
const SUITE_TIMEOUT_MS = Number(process.env.BANTAMKIT_CONFORMANCE_SUITE_TIMEOUT_MS ?? DEFAULT_SUITE_TIMEOUT_MS);

class SuiteDidNotSettle extends Error {}

let boundFired = false;

let onDrain = null;
process.on('beforeExit', () => {
  if (onDrain === null) return;
  const fire = onDrain;
  onDrain = null;
  setImmediate(fire);
});

function settled(promise) {
  return new Promise((resolve, reject) => {
    const finish = (how) => (value) => {
      clearTimeout(timer);
      onDrain = null;
      how(value);
    };
    const timer = setTimeout(() => {
      onDrain = null;
      boundFired = true;
      killRunChildren();
      reject(
        new SuiteDidNotSettle(
          `the suite did not settle within ${SUITE_TIMEOUT_MS / 1000}s (still busy: a child or a timer ` +
            'kept the process alive; every child the run had started was killed); ' +
            'BANTAMKIT_CONFORMANCE_SUITE_TIMEOUT_MS overrides the bound',
        ),
      );
    }, SUITE_TIMEOUT_MS);
    timer.unref();
    onDrain = () => {
      clearTimeout(timer);
      reject(
        new SuiteDidNotSettle(
          'the suite did not settle: its run() was still pending with nothing left to run ' +
            '(Node would have exited 13, "unsettled top-level await", and skipped every suite after it)',
        ),
      );
    };
    Promise.resolve(promise).then(finish(resolve), finish(reject));
  });
}

let runningSuite = null;
let summarised = false;
process.on('exit', (code) => {
  if (summarised || runningSuite === null) return;
  console.log(
    `\nFAIL: the run ended (exit ${code}) inside suite ${runningSuite}, before its summary; ` +
      'the suites after it did not run',
  );
});

/**
 * Run a reference script with a JSON payload on stdin and parse its JSON on stdout.
 *
 * `env` is merged over the parent environment, so a suite can pin `TZ` and compare a
 * LOCAL-clock answer across runtimes instead of comparing two guesses about local time.
 *
 * STDIN IS A FILE, NOT `input:`. MEASURED 2026-10-29 (#246, #238), Node 25.2.1 on macOS
 * arm64: `spawnSync(..., { input })` with a payload larger than the pipe buffer, into a child
 * that starts reading late (a reference imports `bantamkit` first), left the child blocked in
 * `sys.stdin.read()` forever in 7 of 200 calls while pytest ran beside it, and 0 of 200
 * without load. A bare `python -c` repro with no bantamkit in it hung the same way. With the
 * payload in a file handed over as fd 0, the same load gave 0 of 200. The real hangs it
 * explains: `skilldraft_ref.py` (199,583 bytes in) and `skillpropose_ref.py` (71,738 bytes),
 * each with nothing on stdout or stderr until the bound below killed it, and a faulthandler
 * stack showing the child parked at `sys.stdin.read()`. The references still read stdin;
 * only what stands behind it changed, and a regular file always reaches EOF.
 */
let payloadSeq = 0;
function runPython(scriptPath, payload, env = {}) {
  const payloadPath = join(scratch, `ref-payload-${process.pid}-${(payloadSeq += 1)}.json`);
  writeFileSync(payloadPath, JSON.stringify(payload));
  const stdin = openSync(payloadPath, 'r');
  let r;
  try {
    r = spawnSync(python, [scriptPath], {
      stdio: [stdin, 'pipe', 'pipe'],
      encoding: 'utf8',
      maxBuffer: 256 * 1024 * 1024,
      env: { ...process.env, ...env },
      timeout: REF_TIMEOUT_MS,
      killSignal: 'SIGKILL',
    });
  } finally {
    closeSync(stdin);
    rmSync(payloadPath, { force: true });
  }
  // The timeout arm comes FIRST, because `spawnSync` reports it as an ordinary `r.error`
  // and the generic message below would blame the interpreter for being unlaunchable when
  // it launched fine and then stopped answering. Those are different failures and they
  // send a reader to different places.
  if (r.error && (r.error.code === 'ETIMEDOUT' || r.signal === 'SIGKILL')) {
    die(
      `reference script did not finish within ${REF_TIMEOUT_MS / 1000}s and was killed\n` +
        `  script : ${scriptPath}\n` +
        `  python : ${python}\n` +
        `  stdout : ${r.stdout ? `${r.stdout.length} bytes` : 'nothing at all'}\n` +
        `  stderr : ${r.stderr ? `${r.stderr.length} bytes` : 'nothing at all'}\n` +
        (r.stderr ? `--- stderr ---\n${r.stderr.slice(0, 2000)}\n` : '') +
        // Only claimed when the bound is the measured one. Under an override the sentence
        // would be false, and a diagnostic that lies about its own threshold is worse than
        // one that says nothing — the reader is here precisely because they are confused.
        (REF_TIMEOUT_MS === DEFAULT_REF_TIMEOUT_MS
          ? '  this is a HANG, not a slow run: the slowest reference call measured on a full\n' +
            '  run takes 50s, and this bound is twelve times that.'
          : `  the bound was overridden by BANTAMKIT_CONFORMANCE_REF_TIMEOUT_MS; the default is\n` +
            `  ${DEFAULT_REF_TIMEOUT_MS / 1000}s.`),
    );
  }
  if (r.error) die(`could not run ${python}: ${r.error.message}`);
  if (r.status !== 0) {
    die(`reference script failed (exit ${r.status})\n--- stderr ---\n${r.stderr}`);
  }
  try {
    return JSON.parse(r.stdout);
  } catch (e) {
    die(`reference script did not emit JSON: ${e.message}\n--- stdout head ---\n${r.stdout.slice(0, 2000)}`);
  }
}

// -------------------------------------------------------------------------- comparison

const enc = new TextEncoder();
/**
 * A case's side as bytes, and it REFUSES what it cannot read rather than throwing a sentence
 * about someone else's variable.
 *
 * MEASURED, J46-13 mutation M4: a runtime that stopped refusing `git_commit` made
 * `py.git_commit.unavailable` read `undefined`, `Uint8Array.from(undefined)` raised
 * `TypeError: undefined is not iterable`, and that exception left the comparison loop, left
 * the `for` over suites, and ENDED THE PROCESS. 7000-odd cases produced a stack trace rather
 * than a failure report, and the one thing the operator could not learn from it is which case
 * was malformed. The message below names the offending value's type so the catch that now
 * wraps the comparison can print something a reader can act on.
 */
const toBytes = (v) => {
  if (typeof v === 'string') return enc.encode(v);
  if (v instanceof Uint8Array) return v;
  if (Array.isArray(v)) return Uint8Array.from(v);
  throw new TypeError(
    `cannot compare a value of type ${v === null ? 'null' : typeof v} as bytes: ${clip(JSON.stringify(v) ?? String(v), 120)}`,
  );
};

function bytesDiffer(a, b) {
  if (a.length !== b.length) return true;
  for (let i = 0; i < a.length; i += 1) if (a[i] !== b[i]) return true;
  return false;
}

function firstDifference(a, b) {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i += 1) if (a[i] !== b[i]) return i;
  return a.length === b.length ? -1 : n;
}

/** Show a byte string the way a human reads one: visible escapes, and a hex window. */
function render(bytes, at) {
  const text = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
  const escaped = JSON.stringify(text);
  const from = Math.max(0, at - 24);
  const to = Math.min(bytes.length, at + 24);
  const hexed = [...bytes.slice(from, to)]
    .map((b, i) => (from + i === at ? `[${b.toString(16).padStart(2, '0')}]` : b.toString(16).padStart(2, '0')))
    .join(' ');
  return { escaped, hexed, from, to };
}

function reportMismatch(suite, c, expected, actual) {
  const at = firstDifference(expected, actual);
  const e = render(expected, at);
  const a = render(actual, at);
  console.log(`\n  ✖ ${suite}/${c.name}`);
  console.log(`      first difference at byte ${at} of ${expected.length} (python) / ${actual.length} (node)`);
  console.log(`      python : ${clip(e.escaped)}`);
  console.log(`      node   : ${clip(a.escaped)}`);
  console.log(`      python hex [${e.from}..${e.to}) : ${e.hexed}`);
  console.log(`      node   hex [${a.from}..${a.to}) : ${a.hexed}`);
}

function clip(s, n = 400) {
  return s.length <= n ? s : `${s.slice(0, n)}… (+${s.length - n} chars)`;
}

// ---------------------------------------------------------------------------- the run

/**
 * `realpathSync.native`, not the bare temp path. `scrub()` removes the fixture root from
 * every message by STRING replacement, and on Windows CI `os.tmpdir()` is the 8.3 SHORT
 * name (`C:\\Users\\RUNNER~1\\...`) while CPython's `Path.resolve()` returns the long one
 * (`C:\\Users\\runneradmin\\...`). MEASURED, run 32643739343: the substitution matched
 * Node's side and missed Python's, so `recall-strings` reported 30 of 96 differing on a
 * difference the harness had manufactured. Plain `realpathSync` is not enough -- it
 * resolves symlinks but PRESERVES the 8.3 name; only the `.native` binding expands it.
 */
const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-conformance-')));

// #339: THE OPERATOR'S HOME, captured before anything below moves it. A nested run (the
// `instructions` suite re-runs this file) must still name the operator and not the outer run's
// scratch, so the outer run hands it down in BANTAMKIT_CONFORMANCE_OPERATOR_HOME together with the
// scratch home it set (BANTAMKIT_CONFORMANCE_SCRATCH_HOME). The handoff is TRUSTED only when this
// process's own HOME is that exported scratch home: a nested run inherits exactly that HOME. A stale
// operator variable in an operator's shell (no matching scratch HOME) is ignored and HOME is
// captured instead, or the guard below would list names under a directory the run never touches and
// pass blind. Read-only from here on: the guard lists names under it, `ts2py-codec` copies stores
// out of it, and nothing writes to it.
const ownHome = process.env.HOME || process.env.USERPROFILE || homedir();
const handoffTrusted =
  !!process.env.BANTAMKIT_CONFORMANCE_OPERATOR_HOME &&
  !!process.env.BANTAMKIT_CONFORMANCE_SCRATCH_HOME &&
  process.env.BANTAMKIT_CONFORMANCE_SCRATCH_HOME === ownHome;
const operatorHome = handoffTrusted ? process.env.BANTAMKIT_CONFORMANCE_OPERATOR_HOME : ownHome;
process.env.BANTAMKIT_CONFORMANCE_OPERATOR_HOME = operatorHome;
const GUARDED_UNDER_HOME = ['.bantamkit/index', '.bantamkit/usage'];
function operatorHomeNames() {
  const names = new Set();
  const walk = (dir, rel) => {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      if (e.isDirectory()) walk(join(dir, e.name), `${rel}/${e.name}`);
      else names.add(`${rel}/${e.name}`);
    }
  };
  for (const rel of GUARDED_UNDER_HOME) walk(join(operatorHome, ...rel.split('/')), rel);
  return names;
}
const operatorNamesAtStart = operatorHomeNames();
// The cargo toolchain lives under the operator's home (`~/.cargo/bin`, rustup's `~/.rustup`), and
// the `ts2py` suites find it there. Pin it by absolute path BEFORE HOME moves, or they go red
// with `spawnSync cargo ENOENT` the moment the scratch home hides it.
{
  const cargoBin = join(operatorHome, '.cargo', 'bin', process.platform === 'win32' ? 'cargo.exe' : 'cargo');
  if (!process.env.TS2PY_CARGO && existsSync(cargoBin)) process.env.TS2PY_CARGO = cargoBin;
  if (!process.env.CARGO_HOME && existsSync(join(operatorHome, '.cargo'))) process.env.CARGO_HOME = join(operatorHome, '.cargo');
  if (!process.env.RUSTUP_HOME && existsSync(join(operatorHome, '.rustup'))) process.env.RUSTUP_HOME = join(operatorHome, '.rustup');
}
// Every runtime a suite spawns, both sides, inherits a scratch HOME and USERPROFILE (memory save
// and recall append to `<home>/.bantamkit/usage/`; npm and pip fill their caches there), removed
// with `scratch` on exit. #339: `hooks.seedStore` spawned the reference with no `env` and wrote
// 24 usage ledgers into the operator's home per `--all`. A suite that needs a particular home
// sets its own on the child (hooks, install, storage-* do).
const scratchHome = join(scratch, 'home');
mkdirSync(scratchHome, { recursive: true });
process.env.HOME = scratchHome;
process.env.USERPROFILE = scratchHome;
process.env.BANTAMKIT_CONFORMANCE_SCRATCH_HOME = scratchHome;
// Every store a suite makes keeps its hot index (#204) in this run's scratch, never in the
// operator's `~/.bantamkit/index/`: both runtimes honour `BANTAMKIT_INDEX_DIR`, and every
// reference child inherits `process.env` (`runPython`). Forced, not defaulted (#339): a caller's
// exported value would be the operator's real index. A suite that pins it sets its own.
process.env.BANTAMKIT_INDEX_DIR = join(scratch, 'hot-index');
// No suite's SessionStart or server start spawns the detached Retention child (#204, J69-6): it
// deletes under the HOME and archives `.shiftwork` jobs under the cwd it is given, and a suite
// may run with the checkout as its cwd. `storage-retention` turns it back on per call.
process.env.BANTAMKIT_RETENTION = 'off';
// #205 Amendment A3: the daily skill audit wakes the same child on its own switch. `skill-host`
// turns it back on per call.
process.env.BANTAMKIT_SKILL_AUDIT = 'off';
// #206 Task 8: that child now mines, drafts and installs. No suite installs a skill or reaches an
// endpoint unless it says so per call: the auto switch is off and no endpoint is named.
process.env.BANTAMKIT_SKILL_AUTO = 'off';
delete process.env.BANTAMKIT_LLM_URL;
delete process.env.BANTAMKIT_LLM_MODEL;
const ctx = { python, repoRoot, runtimeTs: join(repoRoot, 'runtime-ts'), scratch, runPython, options };

let totals = { cases: 0, bytes: 0, strings: 0, json: 0, failed: 0, rulings: 0 };
const notes = [];

try {
  for (const suiteName of selected) {
    const mod = await import(pathToFileURL(join(suitesDir, `${suiteName}.mjs`)).href);
    if (mod.name !== suiteName) {
      die(`suite ${suiteName}.mjs exports name ${JSON.stringify(mod.name)}; the two must match`);
    }
    // ONE BROKEN SUITE IS ONE RED SUITE, NOT A DEAD RUN. A suite builds its cases by reaching
    // into two runtimes' answers, so a regression on either side can make the BUILDING throw
    // before any case exists — `py.git_commit.unavailable` on a `py.git_commit` that is no
    // longer an object. Before 2026-09-11 that ended `--all`, and the operator got a stack
    // trace instead of the other eighteen suites' verdicts. The regression is now one red
    // suite that names itself and the run reaches its own summary line.
    let cases = [];
    let suiteNotes = [];
    let failed = 0;
    runningSuite = suiteName;
    try {
      ({ cases, notes: suiteNotes = [] } = await settled(mod.run(ctx)));
    } catch (e) {
      failed += 1;
      cases = [];
      suiteNotes = [];
      if (e instanceof SuiteDidNotSettle) {
        console.log(`\n  ✖ ${suiteName}: ${e.message}`);
      } else {
        console.log(`\n  ✖ ${suiteName}: the suite could not build its cases`);
        console.log(`      ${e && e.stack ? e.stack.split('\n').slice(0, 4).join('\n      ') : String(e)}`);
      }
    }
    for (const c of cases) {
      totals.cases += 1;
      if (c.kind === 'bytes') totals.bytes += 1;
      else if (c.kind === 'string') totals.strings += 1;
      else if (c.kind === 'json') totals.json += 1;
      else die(`suite ${suiteName} case ${c.name} has unknown kind ${JSON.stringify(c.kind)}`);

      // A CASE THAT CANNOT READ WHAT IT EXPECTED REPORTS A FAILURE NAMING ITSELF. Encoding is
      // inside the `try` on purpose: `toBytes` and `stable` are where a malformed side is
      // first touched, and one malformed answer must cost ONE red case rather than the run.
      let expected;
      let actual;
      try {
        expected = c.kind === 'json' ? enc.encode(stable(c.expected)) : toBytes(c.expected);
        actual = c.kind === 'json' ? enc.encode(stable(c.actual)) : toBytes(c.actual);
      } catch (e) {
        failed += 1;
        console.log(`\n  ✖ ${suiteName}/${c.name} — MALFORMED CASE: ${e.message}`);
        console.log(
          '      the case reached into a shape one of the runtimes no longer has. That is a ' +
            'regression in the answer, not in the harness.',
        );
        continue;
      }
      const differs = bytesDiffer(expected, actual);

      if (c.ruling) {
        totals.rulings += 1;
        if (!differs) {
          failed += 1;
          console.log(`\n  ✖ ${suiteName}/${c.name} — STALE RULING: the case no longer differs`);
          console.log(`      ruling was: ${c.ruling}`);
        }
        continue;
      }
      if (differs) {
        failed += 1;
        reportMismatch(suiteName, c, expected, actual);
      }
    }
    totals.failed += failed;
    for (const n of suiteNotes) notes.push(`[${suiteName}] ${n}`);
    const kinds = cases.reduce((m, c) => ({ ...m, [c.kind]: (m[c.kind] ?? 0) + 1 }), {});
    console.log(
      `${failed === 0 ? '✔' : '✖'} ${suiteName}: ${cases.length} cases (${
        Object.entries(kinds).map(([k, v]) => `${v} ${k}`).join(', ') || 'none'
      }), ${failed} differed`,
    );
  }
  runningSuite = null;
} finally {
  // POSIX: the launcher clears the group when this process exits. Windows has no launcher.
  if (boundFired && process.platform === 'win32') killRunChildren();
  rmSync(scratch, { recursive: true, force: true });
}

for (const n of notes) console.log(`  note: ${n}`);

// #339 GUARD, read-only: the run must not have added a NAME under the operator's index or usage
// directories. Names, not bytes: a live MCP server appends to ledgers that already exist.
const leakedNames = [...operatorHomeNames()].filter((n) => !operatorNamesAtStart.has(n)).sort();
if (leakedNames.length > 0) {
  console.error(`conformance: OPERATOR HOME LEAK (#339): this run added ${leakedNames.length} name(s) under ${operatorHome}:`);
  for (const n of leakedNames.slice(0, 50)) console.error(`  ${n}`);
  process.exit(1);
}

// The --require-* flags are NON-VACUITY gates, not decoration: a suite that produced no
// case of the demanded kind fails the flag. Otherwise `--require-byte-identical` would
// pass loudest on a suite that compared nothing at all.
if (requireByteIdentical && totals.bytes === 0) {
  console.error('conformance: --require-byte-identical but no case was compared as bytes');
  process.exit(1);
}
if (requireExactStrings && totals.strings === 0) {
  console.error('conformance: --require-exact-strings but no case was compared as an exact string');
  process.exit(1);
}

summarised = true;
console.log(
  `\n${totals.failed === 0 ? 'PASS' : 'FAIL'}: ${totals.cases} cases, ${totals.bytes} byte-identical, ` +
    `${totals.strings} exact-string, ${totals.json} structural, ${totals.rulings} ruled-different, ` +
    `${totals.failed} failures`,
);
process.exit(totals.failed === 0 ? 0 : 1);

/** Key-sorted JSON, so a structural comparison is about content and not key order. */
function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${stable(value[k])}`).join(',')}}`;
  }
  return JSON.stringify(value ?? null);
}
