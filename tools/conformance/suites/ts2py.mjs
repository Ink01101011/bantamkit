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
 *   legacy/<case>     `bantamkit.workplan` from `runtime-py/src` — the committed generated module
 *                     since #314 switched (J85-3); the arm checks what the package actually serves
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
 * `committed/<file>` then compiles EVERY generated file under `runtime-py/src/bantamkit/_generated/`
 * again with the flags it was made with (`workplan.py`; since #315 the codec's `pyyaml.py` and
 * `factfile.py`; since #316 G1 `pricing.py` and `jobbudget.py`; since G2 `logsegment.py`,
 * `eventlog.py` and `tokenledger.py`; since G3 U1 `usage.py`; `--emit-runtime`,
 * `--emit-adapters`) and compares every byte, so a hand-edited body or a compiler change that was
 * never regenerated is red, with the regenerate command (J85-R F4);
 * `committed/coverage` lists the directory, so a generated file outside the gate is red too.
 * `runtime/toLowerCase …` (J89-7, J89-7b) calls the runtime ts2py emitted this run on Greek, ǅ,
 * the 55 code points CPython's table lacks and the 307 it classifies apart for final sigma,
 * against Node's `toLowerCase()`, and pins the answers J89-7 used to refuse as literals.
 * `runtime/sort …` (J90-P2) sorts seeded arrays with NaN under four comparators with that runtime's
 * `_js_m_sort` against Node's `.sort`, the order and the comparator's calls.
 * `adapter/…` (J90-P5) lists, with the TypeScript checker, every member the compiled sources read
 * off an object an adapter builds (`lib/adaptermembers.mjs`) and asks the committed adapters what
 * each provides: a member read and not provided is red (it would read `undefined`, silently, as
 * `Stats.ino` did until J90-P4), and so is a read of an adapter type no row claims.
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
 * NO RULINGS. Every arm must match the expected answer. Until #314 switched `bantamkit.workplan` to
 * the generated module (J85-3), the hand-written planner differed from the TypeScript on 8 cases,
 * carried here as `ruling:` cases; the switch fixed all 8 on the Python side and the list was
 * deleted (`docs/porting.md`, Generated modules). A disagreement now is a red case, never a ruling.
 */
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { adapterReads } from '../lib/adaptermembers.mjs';

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
const HEADLINE = { cases: 148, graph: 21, core: 53, ts: 21, py: 13, adversarial: 40 };

function findCargo() {
  if (process.env.TS2PY_CARGO) return process.env.TS2PY_CARGO;
  const home = join(homedir(), '.cargo', 'bin', process.platform === 'win32' ? 'cargo.exe' : 'cargo');
  return existsSync(home) ? home : 'cargo';
}

/** Run the ts2py binary with `args` (from the repo root). Throws (a red suite) with cargo's own words. */
function ts2py(args, out) {
  const cargo = findCargo();
  const r = spawnSync(
    cargo,
    // #337: the compiler holds no bantamkit name; bantamkit's adapters and header names are its host file.
    ['run', '--release', '--quiet', '--manifest-path', join(repoRoot, 'tools', 'ts2py', 'Cargo.toml'), '--', ...args, '--config', join(repoRoot, 'tools', 'ts2py-bantamkit', 'ts2py.toml')],
    { cwd: repoRoot, encoding: 'utf8', timeout: 900_000, maxBuffer: 64 * 1024 * 1024 },
  );
  if (r.error) throw new Error(`ts2py: could not run ${cargo}: ${r.error.message} (set TS2PY_CARGO)`);
  if (r.status !== 0) throw new Error(`ts2py ${args.join(' ')} failed (exit ${r.status})\n${r.stderr}`);
  if (!existsSync(out)) throw new Error(`ts2py: exited 0 but wrote no ${out}`);
}

/** Compile `workplan.ts` with ts2py into `out` (the runtime inlined). */
function compile(out) {
  ts2py([SOURCE, '-o', out], out);
}

/**
 * THE COMMITTED FILES, byte for byte (J85-R F4). `runtime-py/src/bantamkit/_generated/` is what the
 * wheel serves, and the header line alone cannot vouch for it: a hand-edited body keeps its
 * header, and so does a module that a changed `lower.rs` or `runtime.py` would now write
 * differently. So the suite compiles with exactly the flags the committed files were made with
 * and compares every byte; a mismatch is red and its message is the command that regenerates.
 */
const COMMITTED = 'runtime-py/src/bantamkit/_generated';
/** The fact-file codec (#315, J86-3): one ts2py call compiles both into one package. */
const CODEC_SOURCES = ['runtime-ts/src/memory/pyyaml.ts', 'runtime-ts/src/memory/factfile.ts'];
/**
 * #316 G1 (J87-3): pricing and jobbudget; G2 (J88-2): the log segment, the event log and the token
 * ledger; G3 U1 (J89-2): the usage ledger; G3 (J89-3): retrieval; G3 U2 (J89-4b): the store; G3 U3
 * (J89-5): the native layer; (J89-5a) the queries sidecar; (J89-5b) the layers; (J89-5c) the dream; G3 U4 (J89-6) the component;
 * G4 (J90-2) the lock and the hot index (which the store imports and which imports the store back:
 * an import cycle, written at the end of each module); G4 (J90-3) the cold index, retention, the
 * tiers and the storage package file (`storage/index.ts`, its re-exports). One ts2py call into the same package,
 * because the token ledger imports pricing and the event log and the usage ledger import the log
 * segment, and an import between compiled modules resolves only inside one call.
 */
const G1_SOURCES = [
  'runtime-ts/src/pricing.ts',
  'runtime-ts/src/jobbudget.ts',
  'runtime-ts/src/storage/logsegment.ts',
  'runtime-ts/src/eventlog.ts',
  'runtime-ts/src/tokenledger.ts',
  'runtime-ts/src/memory/usage.ts',
  'runtime-ts/src/memory/retrieval.ts',
  'runtime-ts/src/memory/store.ts',
  'runtime-ts/src/memory/native.ts',
  'runtime-ts/src/memory/queries.ts',
  'runtime-ts/src/memory/layers.ts',
  'runtime-ts/src/memory/dream.ts',
  'runtime-ts/src/memory/component.ts',
  'runtime-ts/src/storage/lock.ts',
  'runtime-ts/src/storage/hotindex.ts',
  'runtime-ts/src/storage/coldindex.ts',
  'runtime-ts/src/storage/retention.ts',
  'runtime-ts/src/storage/tiers.ts',
  'runtime-ts/src/storage/index.ts',
];
const CARGO_RUN = 'cargo run --release --manifest-path tools/ts2py/Cargo.toml -- --config tools/ts2py-bantamkit/ts2py.toml';
const REGENERATE =
  'regenerate from the repository root:\n' +
  `  ${CARGO_RUN} ${SOURCE} -o ${COMMITTED}/workplan.py --runtime-module ._ts2py_runtime\n` +
  `  ${CARGO_RUN} ${CODEC_SOURCES.join(' ')} --out-dir ${COMMITTED} --runtime-module ._ts2py_runtime\n` +
  `  ${CARGO_RUN} ${G1_SOURCES.join(' ')} --out-dir ${COMMITTED} --runtime-module ._ts2py_runtime\n` +
  `  ${CARGO_RUN} --emit-runtime ${COMMITTED}/_ts2py_runtime.py\n` +
  `  ${CARGO_RUN} --emit-adapters ${COMMITTED}/_ts2py_adapters.py`;

/**
 * Every `.py` under `_generated/` but `__init__.py` (hand-written, one docstring), compiled again
 * with the flags it was made with and compared byte for byte. The committed set is LISTED, not
 * named: a generated file committed without a fresh counterpart here is red, so a module added
 * later cannot ship outside this gate.
 */
function committedCases(bed) {
  const fresh = join(bed, 'committed');
  mkdirSync(fresh, { recursive: true });
  ts2py([SOURCE, '-o', join(fresh, 'workplan.py'), '--runtime-module', '._ts2py_runtime'], join(fresh, 'workplan.py'));
  ts2py([...CODEC_SOURCES, '--out-dir', fresh, '--runtime-module', '._ts2py_runtime'], join(fresh, 'factfile.py'));
  ts2py([...G1_SOURCES, '--out-dir', fresh, '--runtime-module', '._ts2py_runtime'], join(fresh, 'pricing.py'));
  ts2py(['--emit-runtime', join(fresh, '_ts2py_runtime.py')], join(fresh, '_ts2py_runtime.py'));
  ts2py(['--emit-adapters', join(fresh, '_ts2py_adapters.py')], join(fresh, '_ts2py_adapters.py'));
  const made = readdirSync(fresh).filter((f) => f.endsWith('.py')).sort();
  const committedFiles = readdirSync(join(repoRoot, COMMITTED))
    .filter((f) => f.endsWith('.py') && f !== '__init__.py')
    .sort();
  const cases = [
    {
      name: 'committed/coverage',
      kind: 'json',
      expected: { committedWithoutAFreshCompile: [], freshButNotCommitted: [] },
      actual: {
        committedWithoutAFreshCompile: committedFiles.filter((f) => !made.includes(f)),
        freshButNotCommitted: made.filter((f) => !committedFiles.includes(f)),
      },
    },
  ];
  for (const file of made) {
    const committed = join(repoRoot, COMMITTED, file);
    const want = readFileSync(join(fresh, file));
    const have = existsSync(committed) ? readFileSync(committed) : Buffer.alloc(0);
    cases.push({
      name: `committed/${file}`,
      kind: 'string',
      expected: `${COMMITTED}/${file} is byte-identical to ts2py's output`,
      actual: want.equals(have)
        ? `${COMMITTED}/${file} is byte-identical to ts2py's output`
        : `${COMMITTED}/${file} differs from what ts2py writes now (${have.length} bytes committed, ${want.length} fresh); ${REGENERATE}`,
    });
  }
  return cases;
}

export async function run(ctx) {
  const fixture = JSON.parse(readFileSync(FIXTURE, 'utf8'));
  const { plan } = await import(new URL('workplan.js', pathToFileURL(join(ctx.runtimeTs, 'dist', '/'))));

  const bed = join(ctx.scratch, 'ts2py');
  mkdirSync(bed, { recursive: true });
  const generatedPath = join(bed, 'workplan_generated.py');
  compile(generatedPath);

  const cases = [...committedCases(bed)];
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

    cases.push({ name: `generated/${c.name}`, kind: 'string', expected, actual: python.generated[i] });
    cases.push({ name: `legacy/${c.name}`, kind: 'string', expected, actual: python.legacy[i] });
  });

  notes.push(
    `compiled ${SOURCE} with ts2py this run (sha256 ${sha.slice(0, 12)}); ${fixture.length} cases x 3 arms against fixtures/workplan-cases.json`,
  );

  // J89-7 / J89-7b (J89-R F1, J89-R2 F1): the runtime's `.toLowerCase()`, from the runtime ts2py
  // emitted this run. Each answer is Node's `toLowerCase()` of the same string, on every CPython
  // 3.11-3.14: final sigma in ordinary Greek, ǅ, İ, the 55 code points CPython's table has no
  // mapping for, and (J89-7b) every U+03A3 J89-7 refused: one whose walk reaches a code point the
  // two tables classify apart (a `Cn` one to CPython, U+0295, U+1171E), now answered from Node's
  // class for those 307. `table` puts each of the 307 on both sides of a U+03A3 behind a cased
  // letter, one word apiece, so a wrong class in the runtime's table is a wrong sigma here. The
  // inputs J89-7 pinned as refusals no longer refuse, and nothing does, so each is now pinned
  // against Node's answer typed into this file as well (`LITERAL answers`).
  {
    const lowerNode = (cp) => String.fromCodePoint(cp);
    const fiftyFive = [0x1c89, 0xa7cb, 0xa7cc, 0xa7ce, 0xa7d2, 0xa7d4, 0xa7da, 0xa7dc]
      .concat(Array.from({ length: 22 }, (_, i) => 0x10d50 + i), Array.from({ length: 25 }, (_, i) => 0x16ea0 + i))
      .map(lowerNode);
    const span = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);
    const table = [
      0x0295, 0x0897, 0x0ece, ...span(0x1acf, 0x1add), ...span(0x1ae0, 0x1aeb), ...span(0x1c89, 0x1c8a),
      ...span(0xa7cb, 0xa7cf), 0xa7d2, 0xa7d4, ...span(0xa7da, 0xa7dc), 0xa7f1, 0x10d4e, ...span(0x10d50, 0x10d65),
      ...span(0x10d69, 0x10d6d), ...span(0x10d6f, 0x10d85), 0x10ec5, ...span(0x10efa, 0x10eff), 0x11241,
      ...span(0x113bb, 0x113c0), 0x113ce, 0x113d0, 0x113d2, ...span(0x113e1, 0x113e2), 0x1171e, 0x11b60,
      ...span(0x11b62, 0x11b64), 0x11b66, 0x11dd9, ...span(0x11f00, 0x11f01), ...span(0x11f36, 0x11f3a), 0x11f40,
      0x11f42, 0x11f5a, ...span(0x13439, 0x13440), ...span(0x13447, 0x13455), ...span(0x1611e, 0x16129),
      ...span(0x1612d, 0x1612f), ...span(0x16d40, 0x16d42), ...span(0x16d6b, 0x16d6c), ...span(0x16ea0, 0x16eb8),
      ...span(0x16ebb, 0x16ed3), ...span(0x16ff2, 0x16ff3), ...span(0x1df25, 0x1df2a), ...span(0x1e030, 0x1e06d),
      0x1e08f, ...span(0x1e4eb, 0x1e4ef), ...span(0x1e5ee, 0x1e5ef), 0x1e6e3, 0x1e6e6, ...span(0x1e6ee, 0x1e6ef),
      0x1e6f5, 0x1e6ff,
    ].map(lowerNode);
    const agree = [
      'ΣΟΦΟΣ ΛΟΓΟΣ.', 'ΑΣ', 'Σ', 'AΣB', 'Η ΟΔΟΣ ΤΟΥ ΣΟΦΟΥ ΣΑΣ', 'Α­Σ', 'ΑΣ­', 'ΟΔΟΣ ͸',
      '͸ ΣΑ', 'ǅemal ΣΑΣ', 'İstanbul', 'Ᲊ tje', fiftyFive.join(' '), `ΑΣ ${fiftyFive.join('')}`,
      table.map((x) => `A${x}Σ`).join(' '), table.map((x) => `AΣ${x}`).join(' '),
      table.map((x) => `${x}Σ`).join(' '), table.map((x) => `Á${x}́Σ́${x}`).join(' '),
    ];
    // J89-7's six refusals and J89-R2's two, with Node 26.13's answer typed in.
    const answered = [
      ['Α͸Σ', 'α͸σ'], ['ΑΣ͸', 'ας͸'], ['ΑΣ­͸', 'ας­͸'],
      ['ʕΣ', 'ʕσ'], ['ΑΣʕ', 'αςʕ'], ['ΑΣ\u{1171e}', 'ας\u{1171e}'],
      ['ΑΣ\u{1FAE9}', 'ας\u{1FAE9}'], ['\u{16ea0}Σ', '\u{16ebb}ς'],
      ['ΓΕΙΑ ΣΑΣ\u{1FAE9} ΚΑΙ ΕΣΥ.', 'γεια σας\u{1FAE9} και εσυ.'], ['ΟΔΟΣ\u{1FAE8}', 'οδος\u{1FAE8}'],
    ];
    const runtime = join(bed, 'committed', '_ts2py_runtime.py');
    const inputs = [...agree, ...answered.map(([text]) => text)];
    const got = ctx.runPython(REF, { lower: { runtime, inputs } }).lower;
    cases.push({ name: 'runtime/toLowerCase: 55 code points in the Node table', kind: 'json', expected: 55, actual: fiftyFive.length });
    cases.push({ name: 'runtime/toLowerCase: 307 code points in the sigma table', kind: 'json', expected: 307, actual: table.length });
    inputs.forEach((text, i) => {
      cases.push({ name: `runtime/toLowerCase agrees with node: ${JSON.stringify(text).slice(0, 60)}`, kind: 'string', expected: text.toLowerCase(), actual: got[i] });
    });
    answered.forEach(([text, lowered], i) => {
      cases.push({ name: `runtime/toLowerCase LITERAL answers: ${JSON.stringify(text)}`, kind: 'string', expected: lowered, actual: got[agree.length + i] });
    });
    notes.push(`runtime toLowerCase: ${inputs.length} inputs against node, ${answered.length} pinned as literals`);
  }

  // J90-P2: the runtime's `.sort(compare)`, from the runtime ts2py emitted this run, against Node's
  // on seeded arrays with NaN (an inconsistent comparator) and lengths past V8's insertion bound and
  // its min run: each order, and the calls the first comparator was made, pair for pair. Until
  // J90-P2 `_js_m_sort` was CPython's `list.sort`: other calls on every CPython, and on 3.13+
  // another order for an inconsistent comparator.
  {
    const SORTS = [
      (a, b) => a - b,
      (a, b) => b - a,
      (a, b) => (a > b ? 1 : 0),
      (a, b) => ((a * 7 + b * 3) % 5) - 2,
    ];
    let seed = 90902;
    const next = () => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return Math.floor(seed / 65536);
    };
    const arrays = [];
    for (let k = 0; k < 120; k += 1) {
      const n = k < 10 ? k : next() % 90;
      arrays.push(Array.from({ length: n }, () => (next() % 7 === 0 ? 'NaN' : next() % 40)));
    }
    const runtime = join(bed, 'committed', '_ts2py_runtime.py');
    const got = ctx.runPython(REF, { sort: { runtime, arrays } }).sort;
    arrays.forEach((items, i) => {
      const values = items.map((x) => (x === 'NaN' ? NaN : x));
      const calls = [];
      const logged = (a, b) => {
        calls.push(`${String(a)}<${String(b)}`);
        return a - b;
      };
      const expected = [logged, ...SORTS.slice(1)].map((cmp) => [...values].sort(cmp).map(String).join(','));
      expected.push(calls.join(' '));
      cases.push({ name: `runtime/sort agrees with node: ${items.length} items #${i}`, kind: 'json', expected, actual: got[i] });
    });
    notes.push(`runtime sort: ${arrays.length} arrays x ${SORTS.length} comparators against node, with the calls`);
  }

  // J90-P5: every member the compiled modules read off an adapter's object is one it provides.
  {
    const audit = adapterReads(repoRoot, [SOURCE, ...CODEC_SOURCES, ...G1_SOURCES]);
    const classes = Object.keys(audit.classes).sort();
    const got = ctx.runPython(REF, { adapters: { classes, scratch: join(bed, 'adapters') } }).adapters;
    cases.push({ name: 'adapter/every read of an adapter type has a row', kind: 'json', expected: [], actual: audit.unclassified });
    for (const cls of classes) {
      const read = audit.classes[cls];
      cases.push({
        name: `adapter/${cls} provides every member compiled code reads (${read.join(', ')})`,
        kind: 'json',
        expected: [],
        actual: read.filter((m) => !got.classes[cls].includes(m)),
      });
    }
    for (const [provider, rows] of Object.entries(audit.dicts).sort()) {
      const samples = got.dicts[provider] ?? [];
      for (const row of rows) {
        const shaped = samples.filter((d) => Object.entries(row.literals).every(([k, v]) => d[k] === v));
        const best = shaped.length === 0 ? row.members : shaped
          .map((d) => row.members.filter((m) => !Object.hasOwn(d, m)))
          .reduce((a, b) => (b.length < a.length ? b : a));
        cases.push({
          name: `adapter/${provider} ${JSON.stringify(row.literals)} provides ${row.members.join(', ')}`,
          kind: 'json',
          expected: [],
          actual: best,
        });
      }
    }
    notes.push(`adapter members: ${audit.count} reads of members declared outside the compiled sources, ${classes.length} adapter classes and ${Object.keys(audit.dicts).length} dict producers checked`);
  }
  return { cases, notes };
}
