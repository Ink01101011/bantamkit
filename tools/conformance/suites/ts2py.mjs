/**
 * ts2py — the work planner three ways: TypeScript, ts2py's generated Python, and `bantamkit.workplan`.
 *
 * THE PROPERTY (#314). `runtime-ts/src/workplan.ts` compiled by `tools/ts2py` answers every case
 * in `fixtures/workplan-cases.json` exactly as the TypeScript does, and so does whatever serves
 * `bantamkit.workplan` on the Python side. Each case is compared on three arms against the ONE
 * expected answer written in that file:
 *
 *   node/<case>       `plan` from `runtime-ts/dist/workplan.js` (run `npm run build` if stale)
 *   generated/<case>  the module ts2py writes into this run's scratch, compiled FRESH every run
 *   legacy/<case>     `bantamkit.workplan` from `runtime-py/src` — hand-written today, the
 *                     generated module once #314 switches (J85-3); the arm keeps working then
 *
 * Every arm is compared as TEXT: Node's `JSON.stringify(answer)` against Python's
 * `json.dumps(answer, ensure_ascii=False, separators=(",", ":"))`, so key order (`held` last)
 * is under test and not only the values. A Python arm that raises answers
 * `RAISED <type>: <message>`, one red case naming itself.
 *
 * WHY IT COMPILES AT RUN TIME. A checked-in generated file could go stale against `workplan.ts`
 * and still pass a suite that imported it. Here `cargo run` (from `~/.cargo/bin/cargo`, or
 * `$TS2PY_CARGO`, or `cargo` on PATH) rebuilds the compiler from `tools/ts2py` and recompiles the
 * source on every run, and `generated/source-sha256` checks the module's header names the bytes
 * on disk. No Rust toolchain means this suite is red, with the reason, rather than skipped.
 *
 * WHY THE PYTHON ARMS READ THE FIXTURE THEMSELVES. `ref/ts2py_ref.py` opens the file with
 * `json.load`; the cases are not sent as a payload, because the payload goes through
 * `JSON.stringify`, which would turn `3.0` into `3` and `-0.0` into `0` before Python saw them.
 * Each side parses the same bytes with its own parser, which is what the MCP servers do with a
 * request.
 *
 * THE EXPECTED ANSWERS ARE DATA, WRITTEN ONCE (#312). `fixtures/workplan-cases.json` holds the 21
 * real graphs and the synthetic corpus of `suites/workplan.mjs` (which now reads its inputs from
 * the same file), every `plan()` input in `runtime-ts/test/workplan.test.mjs` and
 * `runtime-py/tests/test_workplan.py`, and adversarial cases where Python and JS semantics split.
 * An input that appears in several places is one case whose `source` lists them all. Every
 * `expected` is the TypeScript planner's answer, written in on 2026-11-15 after every literal those
 * three locations pin (widths, first batches, refusal sentences, `held`) was checked against it.
 *
 * KNOWN DISAGREEMENTS ARE RULINGS, AND A RULING MUST STAY TRUE. An arm that disagrees with the
 * expected answer is never fixed by editing the expected value or the legacy planner (J85-2
 * property 5). It is listed below with its reason and carried as a `ruling:` case, which the
 * harness REQUIRES to differ — so it is shown, not silenced, and the day it starts matching it
 * fails as a STALE RULING until someone deletes the entry. The generated arm carries no ruling:
 *
 *   KNOWN_LEGACY_FINDINGS  the hand-written `workplan.py` disagrees with the TypeScript. These are
 *                          shipped Python/Node parity bugs that switching to the generated module
 *                          FIXES. J85-3 deletes this list when it switches; the stale rulings
 *                          force it to. Two of them are integers beyond 2^53, which a JS double
 *                          rounds and the legacy planner's Python ints do not; ts2py lowers
 *                          numbers as doubles (`tools/ts2py/SUBSET.md`, Numbers), so the
 *                          generated arm matches.
 *
 * The missing-`id` case is one of the legacy findings: `plan([{depends_on: []}])` refuses
 * `nodes[0].id must be a string` in TypeScript and raises `KeyError: 'id'` in the legacy planner.
 * The tool surface pins the KeyError separately (`suites/workplan.mjs`, `tool/no-id`), and that
 * case is untouched.
 */
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'ts2py';
export const summary = 'workplan three ways: TypeScript, ts2py-generated Python and bantamkit.workplan against one expected file';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const FIXTURE = join(here, 'fixtures', 'workplan-cases.json');
const REF = join(here, 'ref', 'ts2py_ref.py');
const SOURCE = 'runtime-ts/src/workplan.ts';

/**
 * The case count per category, typed out. A case dropped from the fixture is red here rather
 * than a smaller suite that still passes.
 */
const HEADLINE = { cases: 147, graph: 21, core: 53, ts: 21, py: 13, adversarial: 39 };

const KNOWN_LEGACY_FINDINGS = new Map([
  [
    'ts/shape-no-id',
    "legacy plan() reads node['id'] before checking it and raises KeyError 'id'; TypeScript refuses `nodes[0].id must be a string`",
  ],
  [
    'adversarial/touches/1e21',
    "legacy _json prints a float with Python's repr, 1000000000000000000000; JSON.stringify prints 1e+21",
  ],
  ['adversarial/touches/1e-7', "legacy _json prints Python's repr 1e-07; JSON.stringify prints 1e-7"],
  [
    'adversarial/touches/object-nested-floats-and-keys',
    'legacy _json folds only a TOP-LEVEL integral float (nested 3.0 stays 3.0) and keeps dict insertion order; JSON.stringify writes 3 and puts the array-index key "1" first',
  ],
  [
    'adversarial/touches/object-array-index-keys',
    'legacy _json keeps dict insertion order; JSON.stringify puts array-index keys first, ascending ("2", "10", then "b")',
  ],
  [
    'adversarial/touches/object-in-list',
    'legacy _json does not fold the nested integral float 1.0; JSON.stringify writes 1',
  ],
  [
    'adversarial/priority/2^53-plus-one-ties-in-js',
    'legacy plan() subtracts exact Python ints, so 9007199254740993 outranks 9007199254740992; as JS doubles they tie and insertion order holds',
  ],
  [
    'adversarial/touches/int-beyond-2^53',
    'legacy _json prints the exact int 12345678901234567890; JSON.stringify prints the rounded double 12345678901234567000',
  ],
]);

function findCargo() {
  if (process.env.TS2PY_CARGO) return process.env.TS2PY_CARGO;
  const home = join(homedir(), '.cargo', 'bin', process.platform === 'win32' ? 'cargo.exe' : 'cargo');
  return existsSync(home) ? home : 'cargo';
}

/** Compile `workplan.ts` with ts2py into `out`. Throws (a red suite) with cargo's own words. */
function compile(out) {
  const cargo = findCargo();
  const r = spawnSync(
    cargo,
    ['run', '--release', '--quiet', '--manifest-path', join(repoRoot, 'tools', 'ts2py', 'Cargo.toml'), '--', SOURCE, '-o', out],
    { cwd: repoRoot, encoding: 'utf8', timeout: 900_000, maxBuffer: 64 * 1024 * 1024 },
  );
  if (r.error) throw new Error(`ts2py: could not run ${cargo}: ${r.error.message} (set TS2PY_CARGO)`);
  if (r.status !== 0) throw new Error(`ts2py: compiling ${SOURCE} failed (exit ${r.status})\n${r.stderr}`);
  if (!existsSync(out)) throw new Error(`ts2py: exited 0 but wrote no ${out}`);
}

export async function run(ctx) {
  const fixture = JSON.parse(readFileSync(FIXTURE, 'utf8'));
  const { plan } = await import(new URL('workplan.js', pathToFileURL(join(ctx.runtimeTs, 'dist', '/'))));

  const bed = join(ctx.scratch, 'ts2py');
  mkdirSync(bed, { recursive: true });
  const generatedPath = join(bed, 'workplan_generated.py');
  compile(generatedPath);

  const cases = [];
  const notes = [];

  // The module is what the source on disk compiles to NOW: its header names those bytes.
  const sha = createHash('sha256').update(readFileSync(join(repoRoot, SOURCE))).digest('hex');
  cases.push({
    name: 'generated/source-sha256',
    kind: 'string',
    expected: `# source-sha256: ${sha}`,
    actual: readFileSync(generatedPath, 'utf8').split('\n')[1] ?? '(no second line)',
  });

  const counts = { cases: fixture.length };
  for (const c of fixture) {
    const category = c.name.split('/')[0];
    counts[category] = (counts[category] ?? 0) + 1;
  }
  cases.push({ name: 'fixture/headline', kind: 'json', expected: HEADLINE, actual: counts });

  // Every ruling must name a case that exists, or a renamed case would carry its ruling nowhere.
  const names = new Set(fixture.map((c) => c.name));
  for (const listed of KNOWN_LEGACY_FINDINGS.keys()) {
    cases.push({ name: `ruling-names-a-case/${listed}`, kind: 'json', expected: true, actual: names.has(listed) });
  }

  const python = ctx.runPython(REF, { fixture: FIXTURE, generated: generatedPath });

  fixture.forEach((c, i) => {
    const expected = JSON.stringify(c.expected);
    let node;
    try {
      node = JSON.stringify(plan(c.input));
    } catch (e) {
      node = `RAISED ${e && e.name}: ${e && e.message}`;
    }
    cases.push({ name: `node/${c.name}`, kind: 'string', expected, actual: node });

    const legacyFinding = KNOWN_LEGACY_FINDINGS.get(c.name);
    const legacy = python.legacy[i];
    cases.push({ name: `generated/${c.name}`, kind: 'string', expected, actual: python.generated[i] });
    cases.push({ name: `legacy/${c.name}`, kind: 'string', expected, actual: legacy, ...(legacyFinding ? { ruling: legacyFinding } : {}) });
    if (legacyFinding && legacy !== expected) {
      notes.push(`known legacy finding, legacy/${c.name}: expected ${expected}, got ${legacy}`);
    }
  });

  notes.push(
    `compiled ${SOURCE} with ts2py this run (sha256 ${sha.slice(0, 12)}); ${fixture.length} cases x 3 arms against fixtures/workplan-cases.json`,
  );
  return { cases, notes };
}
