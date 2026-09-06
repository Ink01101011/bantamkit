/**
 * repomap — the ranked definition map, Python against Node, over four purpose-built trees.
 *
 * THE PROPERTY: given the same tree on disk and the same call, the two runtimes answer the
 * same walk, the same per-file scan, the same edge map, the same IEEE-754 score for every
 * node, the same rendered listing, the same omission footer, and the same MCP reply. Six
 * comparisons per (tree, call), not one, because "it ranked the same" and "it printed the
 * same bytes" are different claims and this pass can fail either.
 *
 * WHY THIS EXISTS AT ALL. J45-10 proved the two implementations identical with a
 * differential it ran BY HAND, twice, on two corpora. That is a measurement, not a gate: it
 * says the port was right on 2026-09-07 and nothing reruns it. This file is the same
 * comparison wired into `node tools/conformance/run.mjs --all`.
 *
 * THE CORPUS IS BUILT, NEVER THE REPOSITORY, AND THAT IS THE HARDEST-WON RULE IN THIS JOB.
 * J45-10 measured THREE wrong answers from using this checkout as a repo-map corpus while
 * the unit was writing into it: adding one test file produced 40 phantom edge rows; adding
 * one note moved `unknown-language` 1689 -> 1690 and scored four EQUIVALENT mutants as
 * KILLED; editing a header shifted four `Definition.line` values. A stale reference does
 * not fail loudly — it fails as a plausible-looking divergence, which is worse. Every tree
 * below is built in harness scratch from bytes spelled here.
 *
 * AND WHERE A DIFFERENTIAL IS STRUCTURALLY BLIND, THERE IS A LITERAL. J45-8 applied four
 * mutants to BOTH runtimes at once and reddened ZERO differential cases: a rule written
 * twice and asserted nowhere is invisible to a comparison between the two. The
 * `literalCases(...)` blocks at the end of `run()` pin the constants, the tie-break, the
 * omission vocabulary and the tool's fixed tail as TYPED literals against EACH side
 * separately, which is the only shape a symmetric regression cannot stay green through.
 *
 * THE ASTRAL CASE IS THE DEBT THIS SUITE WAS BUILT TO PAY. `_by_code_point` /
 * `cmpCodepoint` is the one rule in `repomap` that NO Python test can make non-vacuous
 * (J45-9 §7, mutant 26: CPython's `str` comparison IS code-point comparison, so no CPython
 * fixture can distinguish the comparator from the identity). J45-10 killed it on the Node
 * side alone. Only a case can prove the two AGREE, and `tree3` is that case: two files
 * whose names differ solely above the BMP, whose scores tie to the last bit, so the
 * comparator is the only thing that decides the order.
 */
import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'repomap';
export const summary = 'the ranked definition map: the walk, the scan, the graph, the score bits, the listing and the tool reply';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'repomap_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

/** SHA-256 of one canonical string. A set has no order on the wire; the caller canonicalises. */
const sha256 = (text) => createHash('sha256').update(Buffer.from(text, 'utf8')).digest('hex');

/**
 * Bound in `run()` from the port's own modules, because the suite is loaded before the
 * harness has told it where `runtime-ts` is. Spelling them here rather than re-implementing
 * them is the point: `pyReadText` is the strict decode and `cmpCodepoint` is the comparator
 * the whole port sorts through, and a probe with its own copy of either would be a third
 * implementation the gate does not cover.
 */
let pyReadText;
let cmpCodepoint;

/** A double as its exact IEEE-754 big-endian bytes. The ONLY way a float travels here. */
function bits(value) {
  const buf = Buffer.alloc(8);
  buf.writeDoubleBE(value);
  return buf.toString('hex');
}

// ---------------------------------------------------------------------- the corpus

/**
 * `tree1` — the ordinary shape, engineered so a plausible-but-wrong port is VISIBLE.
 *
 * Not symmetric anywhere, on purpose (`tests-that-pick-the-input-that-cannot-fail`):
 *
 * - `store.py` defines `Store`, `save`, `load` and a column-0 `CONST_A`; `store.ts` defines
 *   `Store` and `CONST_A` TOO, so both are ambiguous and neither can carry an edge. That is
 *   J45-9's `MAX_DEFINERS = 1` rule with a fixture that can see it — a port that kept the
 *   first definer gains two edges here.
 * - `dream.py` references `Store`, `save`, `load` and `helper`; only `helper` survives the
 *   ambiguity filter, so there is exactly ONE edge out of it and its target is not the file
 *   a naive reader would guess.
 * - `helpers.py` carries a docstring and a `#` comment that both NAME `Store`. A port that
 *   did not strip them reads two extra references and the edge map changes.
 * - `deep/nested.ts` puts a `const` at column 4 inside a function: it must NOT be a
 *   definition (J45-9 §2.3's asymmetry), and it mentions `helper` at an indent, which must
 *   still count as a reference.
 * - `README` and `notes.rst` have no dialect -> `unknown-language=2`.
 * - `empty.py` scans clean and holds nothing -> `no-definitions`.
 */
const TREE1 = {
  'pkg/store.py':
    '"""Store: the docstring names Store, save and load, so the strip is load-bearing."""\n' +
    '\n' +
    'class Store:\n' +
    '    def save(self, fact):\n' +
    '        # save writes the fact; this comment names save and must not be a reference\n' +
    '        return fact\n' +
    '\n' +
    '    def load(self, key):\n' +
    '        return key\n' +
    '\n' +
    'CONST_A = 1\n' +
    'CONST_B: int = 2\n' +
    'NOT_A_DEF == 3\n',
  'pkg/store.ts':
    '/* Store: the block comment names Store and helper and must be stripped. */\n' +
    'export class Store {\n' +
    '  save(fact) {\n' +
    '    const local = fact; // a column-4 const is NOT a definition\n' +
    '    return local;\n' +
    '  }\n' +
    '}\n' +
    'export const CONST_A = 1;\n' +
    'export default async function boot() { return new Store(); }\n',
  'pkg/dream.py':
    'from pkg.store import Store\n' +
    'from pkg.helpers import helper\n' +
    '\n' +
    'def dream(store):\n' +
    '    s = Store()\n' +
    '    s.save(1)\n' +
    '    s.load(2)\n' +
    '    return helper(s)\n',
  'pkg/helpers.py':
    '"""helper: this docstring names Store on purpose."""\n' +
    '# and so does this comment: Store\n' +
    'def helper(store):\n' +
    '    return store\n' +
    '\n' +
    'def unused_helper():\n' +
    '    return None\n' +
    '\n' +
    'def third_helper():\n' +
    '    return None\n' +
    '\n' +
    'def fourth_helper():\n' +
    '    return None\n' +
    '\n' +
    'def fifth_helper():\n' +
    '    return None\n',
  'deep/nested.ts':
    'export interface Shape { readonly n: number }\n' +
    'export type Alias = Shape;\n' +
    'export enum Colour { Red, Blue }\n' +
    'function inner() {\n' +
    '  const helper = 1;\n' +
    '  let other = 2;\n' +
    '  var third = 3;\n' +
    '  return helper + other + third;\n' +
    '}\n' +
    'export let exported = inner;\n',
  'empty.py': '# nothing but a comment\n',
  README: 'not source\n',
  'notes.rst': 'also not source\n',
};

/**
 * `tree2` — the boundary tree. Every omission subject that a built tree can produce.
 *
 * - `binary.py` holds a byte that is not valid UTF-8 -> `unreadable-bytes`. J45-10 §3.4
 *   measured that `readFileSync(p,'utf8')` SUBSTITUTES U+FFFD and returns a string, so a
 *   naive port scans it clean and reports nothing; only `pyReadText`'s strict decode is the
 *   reference's `Path.read_text(encoding="utf-8")`.
 * - `huge.py` is over `MAX_FILE_BYTES` (1 MiB) -> `size-cap`. Neither the repository nor
 *   J45-10's own fixture had one until it was built for this.
 * - `skipped/` is not in `SKIP_DIRS`, but `node_modules/` and `.git/` are, and both hold a
 *   file that would otherwise be scanned and would change the denominator.
 * - `many.py` holds eight definitions against `MAX_DEFINITIONS_PER_FILE = 4` ->
 *   `per-file-cap`, with a `class`, a `def` and a `const` so the KIND ordering inside the
 *   block is exercised rather than only the count.
 */
const HUGE = `${'# padding to pass the one-mebibyte size cap\n'.repeat(27000)}def never_seen():\n    return 1\n`;
const TREE2 = {
  'good.py': 'class Kept:\n    def method(self):\n        return capped_one\n',
  'many.py':
    'ZED_CONST = 1\n' +
    'class Alpha:\n' +
    '    def capped_one(self):\n' +
    '        return 1\n' +
    '\n' +
    'class Beta:\n' +
    '    def capped_two(self):\n' +
    '        return 2\n' +
    '\n' +
    'def top_level():\n' +
    '    return 3\n' +
    '\n' +
    'AAA_CONST = 4\n',
  'huge.py': HUGE,
  'node_modules/vendored.py': 'class NeverScanned:\n    pass\n',
  '.git/hook.py': 'class AlsoNeverScanned:\n    pass\n',
  'skipped/kept.ts': 'export class NotSkipped {}\n',
};

/**
 * `tree3` — THE ASTRAL CASE, and the reason this suite exists in the shape it does.
 *
 * Two files whose names differ ONLY above the BMP: `\u{1F414}widget.py` (U+1F414, astral)
 * and `！widget.py` (U+FF01, BMP fullwidth). Their contents are structurally identical,
 * so their scores tie to the last bit and the ONLY thing that decides the rendered order is
 * the comparator.
 *
 * CPython `sorted()` puts U+FF01 (65281) BEFORE U+1F414 (128020). JS's default
 * `Array.prototype.sort` compares UTF-16 code UNITS, and U+1F414's high surrogate is
 * 0xD83D = 55357, which is LESS than 0xFF01 — so a port that used the default comparator
 * emits them the other way round. J45-10 measured exactly this (§1, trap 10) and killed the
 * mutant on the Node side; nothing until now compared the two.
 *
 * The tree also carries an astral IDENTIFIER inside a name-shaped position, which is a
 * SECOND claim and a smaller one: `repomap`'s scanner is ASCII-only by declaration, so
 * `def \u{1F414}fn()` must be invisible to BOTH runtimes. A port whose `isNameStart` used a
 * Unicode property class would scan a definition the reference does not.
 */
const CHICKEN = '\u{1F414}';
const FULLWIDTH = '！';
const TWIN = (marker) =>
  `class Twin${marker === CHICKEN ? 'A' : 'B'}:\n` +
  '    def shared_method(self):\n' +
  '        return anchor_name\n';
const TREE3 = {
  [`${CHICKEN}widget.py`]: TWIN(CHICKEN),
  [`${FULLWIDTH}widget.py`]: TWIN(FULLWIDTH),
  'anchor.py':
    'def anchor_name():\n' +
    '    return 1\n' +
    '\n' +
    `def ${CHICKEN}fn():\n` +
    '    return 2\n' +
    '\n' +
    `class ${CHICKEN}Class:\n` +
    '    pass\n',
  [`dir${CHICKEN}/inside.py`]: 'def inside_fn():\n    return anchor_name\n',
};

/** `tree4` — one file and nothing else, so the degenerate denominators are compared too. */
const TREE4 = { 'only.py': 'class Only:\n    def solo(self):\n        return 1\n' };

/**
 * `tree5` — THE DOCUMENT-FREQUENCY TREE, and it exists because this suite's own mutation
 * register measured that nothing else here could see the filter.
 *
 * MEASURED, not designed in: mutant `P5-df-filter` (`REFERENCE_DF_MAX_DEN` raised until the
 * filter can never fire) reddened exactly TWO cases across the four trees above — the
 * constants case and its literal — and not one map, listing or edge row. The reason is the
 * FLOOR: `_name_index` skips a name that fewer than `REFERENCE_DF_MAX_DEN` files mention,
 * so on a tree of eight files or fewer the 1/8 threshold cannot reject anything at all.
 * Every tree above is smaller than the floor, so the whole rule was pinned by a number and
 * by no behaviour. This is J45-8's finding in a new place: a case that cannot go red is
 * worse than no case, because it looks like a gate.
 *
 * So: SIXTEEN scanned files. `common.py` defines `widely_named`, which twelve of them
 * mention — thirteen files in all, past the floor of 8 and past `13 * 8 > 16 * 1` — so it
 * is dropped and `common.py` collects NO edge. `rare.py` defines `rare_name`, mentioned by
 * three, which the floor keeps — so `rare.py` collects edges and `common.py` does not, and
 * a port with no DF filter gives `common.py` twelve edges and inverts the ranking.
 */
const TREE5 = (() => {
  const files = {
    'common.py': 'def widely_named():\n    return 1\n',
    'rare.py': 'def rare_name():\n    return 2\n',
  };
  for (let i = 1; i <= 12; i += 1) {
    const n = String(i).padStart(2, '0');
    files[`user${n}.py`] =
      `def caller_${n}():\n` +
      '    return widely_named()\n' +
      // Three of the twelve also reach the rare name, so it stays under the floor while the
      // common one goes over it. Any more and BOTH would be dropped and the tree would be
      // back to proving nothing.
      (i <= 3 ? `\n\ndef also_${n}():\n    return rare_name()\n` : '');
  }
  return files;
})();

const TREES = [
  ['ordinary', TREE1],
  ['boundary', TREE2],
  ['astral', TREE3],
  ['single', TREE4],
  ['document-frequency', TREE5],
];

function materialise(root, files) {
  mkdirSync(root, { recursive: true });
  for (const [rel, content] of Object.entries(files)) {
    const full = join(root, rel);
    mkdirSync(dirname(full), { recursive: true });
    writeFileSync(full, Buffer.from(content, 'utf8'));
  }
}

/**
 * The one file whose bytes cannot be written from a JS string: a lone 0x80 continuation
 * byte, which is invalid UTF-8 and is what `unreadable-bytes` counts.
 */
function writeInvalidUtf8(root) {
  writeFileSync(join(root, 'binary.py'), Buffer.from([0x64, 0x65, 0x66, 0x20, 0x80, 0x0a]));
}

/**
 * The calls made against every tree.
 *
 * The budgets are NOT a round sweep. J45-9 measured that its own first budget sweep stepped
 * by 7 and stepped over every block boundary, so the interesting values are the ones AT a
 * boundary: 0 (nothing fits), 1 (not even a header), and a set of small values that land
 * inside, on and just past a file block.
 */
const CALLS = [
  { label: 'no focus, default budget', focus: [] },
  { label: 'no focus, budget 0', focus: [], budget: 0 },
  { label: 'no focus, budget 1', focus: [], budget: 1 },
  { label: 'no focus, budget 12', focus: [], budget: 12 },
  { label: 'no focus, budget 13', focus: [], budget: 13 },
  { label: 'no focus, budget 40', focus: [], budget: 40 },
  { label: 'no focus, budget 41', focus: [], budget: 41 },
  { label: 'no focus, budget 200', focus: [], budget: 200 },
];

/** Per-tree focus calls: a real focus, two foci, and a focus that is not a node at all. */
const FOCI = {
  ordinary: [['pkg/dream.py'], ['pkg/dream.py', 'deep/nested.ts'], ['not/a/file.py']],
  boundary: [['good.py'], ['huge.py'], []],
  astral: [[`${CHICKEN}widget.py`], [`${FULLWIDTH}widget.py`], [`dir${CHICKEN}/inside.py`]],
  single: [['only.py'], ['nowhere.py']],
  'document-frequency': [['user01.py'], ['common.py'], ['rare.py']],
};

// ------------------------------------------------------------------ the Node side

/** `map_json` as `repomap_ref.py` spells it. */
function nodeMap(result) {
  return {
    text: b64(result.text),
    ranked: result.ranked.map((entry) => ({
      path: b64(entry.path),
      rank_units: entry.rankUnits,
      score_bits: bits(entry.score),
      definitions: entry.definitions.map((d) => [b64(d.path), d.line, b64(d.kind), b64(d.name)]),
    })),
    omissions: result.omissions.map((o) => ({
      subject: b64(o.subject),
      count: o.count,
      size: o.size,
      facts: o.facts.map(([k, v]) => [b64(k), v]),
    })),
    focus: result.focus.map(b64),
    nodes: result.nodes,
    edges: result.edges,
    definitions: result.definitions,
    damping_bits: bits(result.damping),
    iterations: result.iterations,
    budget: result.budget,
    per_file: result.perFile,
    listing_bytes: result.listingBytes,
    files_rendered: result.filesRendered,
    definitions_rendered: result.definitionsRendered,
  };
}

/**
 * The two rules a differential is structurally blind to, pinned as literals against EACH
 * side separately.
 *
 * MEASURED, J45-8: four mutants applied to both runtimes at once reddened ZERO differential
 * cases and were caught only by literals. So these do not compare the runtimes to each
 * other — each side is compared to a typed constant.
 */
function literalCases(pySide, nodeSide, label, expected) {
  return [
    { name: `${label} — python`, kind: 'json', expected, actual: pySide },
    { name: `${label} — node`, kind: 'json', expected, actual: nodeSide },
  ];
}

// ------------------------------------------------------------------------------- run

export async function run(ctx) {
  const rm = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'repomap.js')).href);
  const server = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'mcp', 'server.js')).href);
  ({ pyReadText } = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'pyfs.js')).href));
  ({ cmpCodepoint } = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'pysem.js')).href));
  const cases = [];
  const notes = [];

  const roots = {};
  for (const [label, files] of TREES) {
    const root = join(ctx.scratch, `rm-${label}`);
    materialise(root, files);
    if (label === 'boundary') writeInvalidUtf8(root);
    roots[label] = root;
  }

  // ------------------------------------------------ stage 1-3: the walk, scan and graph
  //
  // Compared SEPARATELY from the map, so the first differing stage is nameable: a scanner
  // that missed a definition and a graph that dropped an edge both surface as a different
  // listing, and a suite that only compared listings would send the reader to the renderer.
  for (const [label] of TREES) {
    const root = roots[label];
    const py = ctx.runPython(REF, { op: 'stages', root });
    const nd = nodeStages(rm, root);
    cases.push({ name: `${label} — the walk`, kind: 'json', expected: py.walk, actual: nd.walk });
    cases.push({ name: `${label} — the per-file scan`, kind: 'json', expected: py.scan, actual: nd.scan });
    cases.push({ name: `${label} — the edge map`, kind: 'json', expected: py.edges, actual: nd.edges });
  }

  // ---------------------------------------------------- stage 4-6: the map and the reply
  for (const [label] of TREES) {
    const root = roots[label];
    const calls = [
      ...CALLS,
      ...FOCI[label].map((focus, i) => ({ label: `focus set ${i + 1}`, focus })),
    ];
    const request = {
      op: 'map',
      root,
      cases: calls.map((c) => ({
        focus: c.focus.map(b64),
        budget: c.budget === undefined ? rm.DEFAULT_BUDGET : c.budget,
      })),
    };
    const py = ctx.runPython(REF, request).out;
    const nd = request.cases.map((c) =>
      nodeMap(rm.repoMap(root, { focus: c.focus.map(unb64), budget: c.budget })),
    );
    calls.forEach((call, i) => {
      cases.push({ name: `${label} / ${call.label} — the map`, kind: 'json', expected: py[i], actual: nd[i] });
      // The rendered listing is compared AS BYTES as well as inside the map, because bytes
      // is the comparison a reader can act on: `run.mjs` prints the first differing byte
      // and a hex window, where a JSON diff prints two base64 blobs.
      cases.push({
        name: `${label} / ${call.label} — the listing bytes`,
        kind: 'bytes',
        expected: unb64(py[i].text),
        actual: unb64(nd[i].text),
      });
    });

    const pyReply = ctx.runPython(REF, { ...request, op: 'reply' }).out;
    const ndReply = request.cases.map((c) =>
      server.repoMapReply(rm.repoMap(root, { focus: c.focus.map(unb64), budget: c.budget })),
    );
    calls.forEach((call, i) => {
      cases.push({
        name: `${label} / ${call.label} — the tool reply`,
        kind: 'bytes',
        expected: unb64(pyReply[i]),
        actual: ndReply[i],
      });
    });
  }

  // --------------------------------------------------------- the iteration, without a tree
  //
  // `pagerank` on hand-built graphs, so the arithmetic is compared where a filesystem
  // cannot reach: a node with no out-edges (the dangling mass), a two-cycle, a focus that
  // is not a node, an empty personalisation, and a graph with one node and no edges.
  const PAGERANK = [
    { label: 'a dangling node redistributes its mass', nodes: ['a', 'b', 'c'], edges: { a: { b: 1 } }, personal: ['a'] },
    { label: 'a two-cycle at the uniform vector', nodes: ['a', 'b'], edges: { a: { b: 1 }, b: { a: 1 } }, personal: [] },
    { label: 'a focus that is not a node', nodes: ['a', 'b'], edges: { a: { b: 2 } }, personal: ['zzz'] },
    { label: 'weights that are not one', nodes: ['a', 'b', 'c'], edges: { a: { b: 3, c: 1 }, b: { c: 7 } }, personal: ['a'] },
    { label: 'one node, no edges', nodes: ['a'], edges: {}, personal: [] },
    { label: 'no nodes at all', nodes: [], edges: {}, personal: [] },
    { label: 'astral node names decide the index order', nodes: [`${CHICKEN}a`, `${FULLWIDTH}a`], edges: { [`${CHICKEN}a`]: { [`${FULLWIDTH}a`]: 1 } }, personal: [`${CHICKEN}a`] },
  ];
  const pyRank = ctx.runPython(REF, {
    op: 'pagerank',
    cases: PAGERANK.map((c) => ({
      nodes: c.nodes.map(b64),
      edges: Object.fromEntries(Object.entries(c.edges).map(([s, t]) => [b64(s), Object.fromEntries(Object.entries(t).map(([k, v]) => [b64(k), v]))])),
      personal: c.personal.map(b64),
    })),
  }).out;
  PAGERANK.forEach((c, i) => {
    // `pagerank` takes a Map of Maps here and a dict of dicts on the reference; the plain
    // object above is the CASE spelling, converted once so the two calls carry the same
    // graph rather than two graphs that happen to look alike in the source.
    const graph = new Map(
      Object.entries(c.edges).map(([source, targets]) => [source, new Map(Object.entries(targets))]),
    );
    const scores = rm.pagerank(c.nodes, graph, c.personal, rm.DAMPING, rm.ITERATIONS);
    cases.push({
      name: `pagerank: ${c.label}`,
      kind: 'json',
      expected: pyRank[i],
      actual: { bits: scores.map(bits), rank_units: scores.map((s) => Math.floor(s * rm.SCORE_SCALE)) },
    });
  });

  // ------------------------------------------------------------------ the constants
  const pyConst = ctx.runPython(REF, { op: 'constants' });
  const ndConst = {
    DAMPING_bits: bits(rm.DAMPING),
    ITERATIONS: rm.ITERATIONS,
    MIN_REFERENCE_LENGTH: rm.MIN_REFERENCE_LENGTH,
    REFERENCE_DF_MAX_NUM: rm.REFERENCE_DF_MAX_NUM,
    REFERENCE_DF_MAX_DEN: rm.REFERENCE_DF_MAX_DEN,
    MAX_DEFINITIONS_PER_FILE: rm.MAX_DEFINITIONS_PER_FILE,
    DEFAULT_BUDGET: rm.DEFAULT_BUDGET,
    SCORE_SCALE: rm.SCORE_SCALE,
    MAX_FILE_BYTES: rm.MAX_FILE_BYTES,
    SKIP_DIRS: rm.SKIP_DIRS.map(b64),
    LANGUAGES: Object.fromEntries(Object.entries(rm.LANGUAGES).map(([k, v]) => [b64(k), b64(v)])),
    OMISSION_ORDER: rm.OMISSION_ORDER.map(b64),
    REPO_MAP_TAIL: b64(server.REPO_MAP_TAIL),
    REPO_MAP_EMPTY: b64(server.REPO_MAP_EMPTY),
  };
  cases.push({ name: 'the pinned constants', kind: 'json', expected: pyConst, actual: ndConst });

  notes.push(
    `${TREES.length} trees x ${CALLS.length} budget calls plus per-tree foci; ` +
      `${PAGERANK.length} pagerank scenarios; every float as IEEE-754 bits, never a decimal`,
  );

  // ============================================================== LITERALS, per side
  //
  // Everything above is a differential. Everything below is not: each side is compared to a
  // typed constant, because a rule changed on BOTH sides at once keeps every differential
  // green (J45-8 measured 4 such mutants and 0 differential cases red).

  // --- literal 1: the constants themselves, as bits and integers.
  cases.push(
    ...literalCases(
      {
        DAMPING_bits: pyConst.DAMPING_bits,
        ITERATIONS: pyConst.ITERATIONS,
        MIN_REFERENCE_LENGTH: pyConst.MIN_REFERENCE_LENGTH,
        df: [pyConst.REFERENCE_DF_MAX_NUM, pyConst.REFERENCE_DF_MAX_DEN],
        per_file: pyConst.MAX_DEFINITIONS_PER_FILE,
        budget: pyConst.DEFAULT_BUDGET,
        scale: pyConst.SCORE_SCALE,
        cap: pyConst.MAX_FILE_BYTES,
      },
      {
        DAMPING_bits: ndConst.DAMPING_bits,
        ITERATIONS: ndConst.ITERATIONS,
        MIN_REFERENCE_LENGTH: ndConst.MIN_REFERENCE_LENGTH,
        df: [ndConst.REFERENCE_DF_MAX_NUM, ndConst.REFERENCE_DF_MAX_DEN],
        per_file: ndConst.MAX_DEFINITIONS_PER_FILE,
        budget: ndConst.DEFAULT_BUDGET,
        scale: ndConst.SCORE_SCALE,
        cap: ndConst.MAX_FILE_BYTES,
      },
      'the measured constants are the measured values',
      {
        // 0.20 is `3fc999999999999a`. A decimal comparison here would have compared two
        // serialisers; J45-9's DAMPING mutant (0.20 -> 0.85) moves this string.
        DAMPING_bits: '3fc999999999999a',
        ITERATIONS: 30,
        MIN_REFERENCE_LENGTH: 3,
        df: [1, 8],
        per_file: 4,
        budget: 4000,
        scale: 1000000000,
        cap: 1048576,
      },
    ),
  );

  // --- literal 2: THE ASTRAL TIE-BREAK. The debt J45-9 named and J45-10 could only half pay.
  //
  // Both files score identically (their content is structurally the same and each is
  // referenced by nothing), so `rank_units` ties and ONLY the comparator orders them. The
  // expected order is CODE POINT order: U+FF01 (65281) before U+1F414 (128020). A port on
  // `Array.prototype.sort`'s default emits the astral one first, because its high surrogate
  // 0xD83D (55357) sorts below 0xFF01.
  //
  // The case also asserts the TIE, not only the order: if a future change made the two
  // scores differ, the ordering would be decided by the score and this case would pass for
  // the wrong reason. That is the vacuity J45-8 found in its own `0.0` ladder scenario.
  {
    const astralRoot = roots.astral;
    const pyTie = ctx.runPython(REF, {
      op: 'map',
      root: astralRoot,
      cases: [{ focus: [], budget: 4000 }],
    }).out[0];
    const ndTie = nodeMap(rm.repoMap(astralRoot, { focus: [], budget: 4000 }));
    const twins = (m) =>
      m.ranked
        .map((e) => ({ path: unb64(e.path), rank_units: e.rank_units }))
        .filter((e) => e.path.endsWith('widget.py'));
    cases.push(
      ...literalCases(
        twins(pyTie),
        twins(ndTie),
        'an astral path and a BMP one tie, and the tie resolves by CODE POINT',
        [
          // The two rank_units are EQUAL and that is half the claim: if a future change
          // made the scores differ, the score would decide the order and this case would
          // pass for the wrong reason — the vacuity J45-8 found in its own `0.0` ladder.
          { path: `${FULLWIDTH}widget.py`, rank_units: 217391304 },
          { path: `${CHICKEN}widget.py`, rank_units: 217391304 },
        ],
      ),
    );
    notes.push(
      `astral tie-break: U+FF01 (${FULLWIDTH.codePointAt(0)}) sorts before U+1F414 ` +
        `(${CHICKEN.codePointAt(0)}) by code point; by UTF-16 code unit the high surrogate ` +
        `${CHICKEN.charCodeAt(0)} would sort first, which is the order this case forbids`,
    );

    // --- literal 3: an astral IDENTIFIER is invisible to the scanner, on both sides.
    // `repomap`'s name characters are ASCII by declaration, so `def 🐔fn()` and
    // `class 🐔Class` are NOT definitions. A port whose `isNameStart` reached for a Unicode
    // property class would scan two the reference never sees.
    const pyStages = ctx.runPython(REF, { op: 'stages', root: astralRoot });
    const ndStages = nodeStages(rm, astralRoot);
    const namesIn = (stages) =>
      (stages.scan[b64('anchor.py')].definitions ?? []).map((d) => unb64(d[3]));
    cases.push(
      ...literalCases(
        namesIn(pyStages),
        namesIn(ndStages),
        'an astral identifier is not a definition on either side',
        ['anchor_name'],
      ),
    );
  }

  // --- literal 4: the omission vocabulary is a CLOSED set and the boundary tree hits it.
  // J45-9 mutants 19/20/28/29/30 each make one of these vanish; a differential sees a
  // vanished omission only while the two sides disagree about it.
  {
    const boundary = roots.boundary;
    const pyBoundary = ctx.runPython(REF, {
      op: 'map',
      root: boundary,
      cases: [{ focus: [], budget: 60 }],
    }).out[0];
    const ndBoundary = nodeMap(rm.repoMap(boundary, { focus: [], budget: 60 }));
    const subjects = (m) =>
      Object.fromEntries(m.omissions.map((o) => [unb64(o.subject), o.count]));
    cases.push(
      ...literalCases(
        subjects(pyBoundary),
        subjects(ndBoundary),
        'the boundary tree names every omission it earns',
        {
          // `binary.py`'s lone 0x80; `huge.py` over 1 MiB; `many.py`'s seven definitions
          // against a cap of four; and the two files a 60-byte budget cannot carry.
          'unreadable-bytes': 1,
          'size-cap': 1,
          'per-file-cap': 3,
          budget: 2,
        },
      ),
    );
  }

  // --- literal 5: the tool's fixed tail, which is the sentence the measurement forbids
  // changing. Row 10's build gate was REFUTED (discovery is 0.114 % of real prompt tokens),
  // so the reply says so on every call. A differential would stay green if someone softened
  // it on both sides at once.
  cases.push(
    ...literalCases(
      { tail: unb64(pyConst.REPO_MAP_TAIL), empty: unb64(pyConst.REPO_MAP_EMPTY) },
      { tail: server.REPO_MAP_TAIL, empty: server.REPO_MAP_EMPTY },
      'the reply tail records the refuted gate and the byte unit',
      {
        tail:
          "This is a precision pass, not a token saving: this feature's build gate was " +
          'REFUTED by measurement — discovery is 0.114% of real prompt tokens, because ' +
          '97.8% of the bill is cache_read — so a map does not make a session cheaper. ' +
          'What it buys is the right file found sooner.\n' +
          'The budget above is UTF-8 BYTES of listing, not tokens: neither runtime ' +
          'carries a model tokenizer and this tool will not pretend to one.',
        empty: '(nothing listed: no file under this root scanned into a definition)',
      },
    ),
  );

  return { cases, notes };
}

/**
 * `run_stages` as `repomap_ref.py` spells it, off the port's own exports.
 *
 * `pyReadText` and not `readFileSync(p,'utf8')`: J45-10 §3.4 measured that Node's decoder
 * SUBSTITUTES U+FFFD for a bad byte and returns a string, so a probe using it would scan the
 * boundary tree's `binary.py` clean and report a definition CPython never sees — the probe
 * itself would manufacture a divergence. `cmpCodepoint` and not `.sort()`, for trap (10).
 */
function nodeStages(rm, root) {
  const walked = rm.walkSources(root);
  const scan = {};
  const definitions = new Map();
  const references = new Map();
  for (const rel of walked) {
    const language = rm.languageOf(rel);
    const entry = { language: language === null ? null : b64(language) };
    if (language === null) {
      scan[b64(rel)] = entry;
      continue;
    }
    let raw;
    try {
      raw = pyReadText(join(root, rel));
    } catch {
      // The probe reports THAT the read failed, never which class was raised: `pyfs.ts`
      // raises CPython's shapes under names prefixed `Py`, and J45-10 §2 measured that
      // recording the class name manufactures two false divergences out of a difference
      // nothing `repomap` returns can observe.
      entry.unreadable = true;
      scan[b64(rel)] = entry;
      continue;
    }
    const stripped = rm.stripNoncode(raw, language);
    const defs = rm.scanDefinitions(raw, language, rel);
    const refs = rm.referenceNames(raw, language);
    entry.stripped_sha256 = sha256(stripped.join('\n'));
    entry.lines = stripped.length;
    entry.definitions = defs.map((d) => [b64(d.path), d.line, b64(d.kind), b64(d.name)]);
    // A set has no order on the wire, so both sides hash the SAME canonical form: code-point
    // sorted, NUL joined. A space would collide with nothing here, but NUL cannot appear in
    // an identifier at all, which is the property that makes the join unambiguous.
    entry.references_sha256 = sha256([...refs].sort(cmpCodepoint).join('\u0000'));
    entry.references = refs.size;
    scan[b64(rel)] = entry;
    definitions.set(rel, defs);
    references.set(rel, refs);
  }
  const edges = rm.buildGraph(definitions, references);
  const out = {};
  for (const source of [...edges.keys()].sort(cmpCodepoint)) {
    const targets = edges.get(source);
    const inner = {};
    for (const target of [...targets.keys()].sort(cmpCodepoint)) inner[b64(target)] = targets.get(target);
    out[b64(source)] = inner;
  }
  return { walk: walked.map(b64), scan, edges: out };
}
