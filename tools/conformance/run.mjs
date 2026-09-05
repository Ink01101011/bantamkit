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
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = dirname(dirname(here));
const suitesDir = join(here, 'suites');

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
 * Run a reference script with a JSON payload on stdin and parse its JSON on stdout.
 *
 * `env` is merged over the parent environment, so a suite can pin `TZ` and compare a
 * LOCAL-clock answer across runtimes instead of comparing two guesses about local time.
 */
function runPython(scriptPath, payload, env = {}) {
  const r = spawnSync(python, [scriptPath], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
    env: { ...process.env, ...env },
    timeout: REF_TIMEOUT_MS,
    killSignal: 'SIGKILL',
  });
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
const toBytes = (v) => (typeof v === 'string' ? enc.encode(v) : Uint8Array.from(v));

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
const ctx = { python, repoRoot, runtimeTs: join(repoRoot, 'runtime-ts'), scratch, runPython, options };

let totals = { cases: 0, bytes: 0, strings: 0, json: 0, failed: 0, rulings: 0 };
const notes = [];

try {
  for (const suiteName of selected) {
    const mod = await import(pathToFileURL(join(suitesDir, `${suiteName}.mjs`)).href);
    if (mod.name !== suiteName) {
      die(`suite ${suiteName}.mjs exports name ${JSON.stringify(mod.name)}; the two must match`);
    }
    const { cases, notes: suiteNotes = [] } = await mod.run(ctx);
    let failed = 0;
    for (const c of cases) {
      totals.cases += 1;
      if (c.kind === 'bytes') totals.bytes += 1;
      else if (c.kind === 'string') totals.strings += 1;
      else if (c.kind === 'json') totals.json += 1;
      else die(`suite ${suiteName} case ${c.name} has unknown kind ${JSON.stringify(c.kind)}`);

      const expected = c.kind === 'json' ? enc.encode(stable(c.expected)) : toBytes(c.expected);
      const actual = c.kind === 'json' ? enc.encode(stable(c.actual)) : toBytes(c.actual);
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
} finally {
  rmSync(scratch, { recursive: true, force: true });
}

for (const n of notes) console.log(`  note: ${n}`);

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
