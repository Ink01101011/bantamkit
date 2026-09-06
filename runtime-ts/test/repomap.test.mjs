/**
 * The repo map on the Node side: what the scanner sees, what it refuses to hide, and the
 * places where a CPython freebie stops being free.
 *
 * TWO ORACLES, and the second is the one this port owes. Most nodes below are the SAME
 * nodes `runtime-py/tests/test_repomap.py` holds — same fixture, same claim, same
 * assertion — so a behaviour that moved on one side and not the other goes red here rather
 * than in a conformance run two units later. That is the fast loop.
 *
 * The slow loop is `tools/conformance/`, which compares the two live answers. What THIS
 * file adds that a differential over this repository cannot see is the `NODE-ONLY PINS`
 * section. J45-10 ran the full rendered map, the omission footer and the IEEE-754 BIT
 * PATTERN of every score through a Python/Node diff over this repository's own 278 scanned
 * files and got IDENTICAL first run — and then measured that FIVE mutants survived that
 * differential anyway, because this repository contains no directory symlink, no path above
 * the BMP, no source file over 1 MiB and no budget that lands on a block boundary. Every
 * node in that section is a rule J45-9 measured as EQUIVALENT in CPython — three of its own
 * four surviving mutants — and load-bearing here.
 *
 * A differential is also blind in a second way this file has to cover: it says the two
 * runtimes AGREE, never that either is right. Two nodes below exist because a mutant
 * survived this suite and was caught only by the differential, and the fixture was then
 * made able to tell the difference — see the three-definer comment on the ambiguity node.
 *
 * NOTHING HERE TOUCHES A REAL STORE OR A REAL CHECKOUT IT WRITES TO. Every tree is built
 * under the OS temp directory; the two nodes that read this repository read it and never
 * write to it.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  DAMPING,
  DEFAULT_BUDGET,
  ITERATIONS,
  MAX_DEFINITIONS_PER_FILE,
  MAX_FILE_BYTES,
  OMIT_BUDGET,
  OMIT_NO_DEFINITIONS,
  OMIT_PER_FILE_CAP,
  OMIT_SIZE_CAP,
  OMIT_UNKNOWN_LANGUAGE,
  OMIT_UNREACHABLE,
  OMIT_UNREADABLE,
  OMISSION_ORDER,
  SCORE_SCALE,
  buildGraph,
  languageOf,
  pagerank,
  referenceNames,
  repoMap,
  scanDefinitions,
  selectDefinitions,
  stripNoncode,
  walkSources,
} from '../dist/repomap.js';

const REPO = dirname(dirname(dirname(fileURLToPath(import.meta.url))));

const roots = [];
function tree() {
  const root = mkdtempSync(join(tmpdir(), 'bk-repomap-'));
  roots.push(root);
  return root;
}
process.on('exit', () => {
  for (const root of roots) rmSync(root, { recursive: true, force: true });
});

function w(root, rel, text) {
  const full = join(root, rel);
  mkdirSync(dirname(full), { recursive: true });
  writeFileSync(full, text, 'utf8');
}

const names = (defs) => defs.map((d) => d.name);

function omissions(result) {
  const out = {};
  for (const o of result.omissions) out[o.subject] = o.count;
  return out;
}

function facts(result, subject) {
  for (const o of result.omissions) {
    if (o.subject === subject) return Object.fromEntries(o.facts);
  }
  throw new assert.AssertionError({
    message: `no ${subject} omission in ${JSON.stringify(omissions(result))}`,
  });
}

/** Python dicts of definitions/references, as the Maps `buildGraph` takes. */
function defsOf(mapping) {
  const out = new Map();
  for (const [path, rows] of Object.entries(mapping)) {
    out.set(
      path,
      rows.map(([line, kind, name]) => ({ path, line, kind, name })),
    );
  }
  return out;
}
function refsOf(mapping) {
  const out = new Map();
  for (const [path, xs] of Object.entries(mapping)) out.set(path, new Set(xs));
  return out;
}
function plainEdges(edges) {
  const out = {};
  for (const [source, row] of edges) out[source] = Object.fromEntries(row);
  return out;
}

// ---------------------------------------------------------------------------- languageOf

test('languageOf dispatches on suffix and refuses the rest', () => {
  const table = [
    ['a.py', 'python'],
    ['a.pyi', 'python'],
    ['a.ts', 'ecma'],
    ['a.mjs', 'ecma'],
    ['a.cjs', 'ecma'],
    ['a.tsx', 'ecma'],
    ['A.PY', 'python'],
    ['a.md', null],
    ['a.json', null],
    ['Makefile', null],
    ['.gitignore', null],
    // The dot belongs to the DIRECTORY, so the file has no suffix at all.
    ['dir.py/README', null],
    ['dir.py\\README', null],
  ];
  for (const [path, expected] of table) {
    assert.equal(languageOf(path), expected, path);
  }
});

test('the suffix fold cannot reach a dialect key on one side and not the other', () => {
  // `languageOf` lowercases the suffix, and `str.lower()` is not `String.toLowerCase()`.
  // MEASURED over all 1,114,112 codepoints ($S/lower_py.txt against $S/lower_ts.txt):
  // CPython 3.12.13 and node v25.2.1 disagree on exactly 27, and every one is a codepoint
  // this Node's ICU lowercases and CPython's UCD 15.0 leaves alone — the same Unicode-16
  // class `dream.ts` records for `\d` and `\w`.
  //
  // The disagreement is UNREACHABLE here, and this node is what says so rather than hoping:
  // not one of the 27 folds to anything ASCII, so a suffix holding one misses all ten keys
  // of `LANGUAGES` on BOTH sides and both answer null. If a future ICU ever folds one of
  // these to an ASCII letter, this goes red instead of the two runtimes quietly splitting.
  const disagree = [
    0x1c89, 0xa7cb, 0xa7cc, 0xa7da, 0xa7dc,
    ...Array.from({ length: 22 }, (_, i) => 0x10d50 + i),
  ];
  for (const cp of disagree) {
    const ch = String.fromCodePoint(cp);
    assert.ok(
      ![...ch.toLowerCase()].some((c) => c.codePointAt(0) < 128),
      `U+${cp.toString(16).toUpperCase()} now folds into ASCII — the two suffix folds can diverge`,
    );
    assert.equal(languageOf(`a.${ch}py`), null);
  }
});

// -------------------------------------------------------------------------- stripNoncode

test('a python docstring is stripped and the line numbers survive', () => {
  const source = '"""\ndef not_a_def():\n    pass\n"""\ndef real():\n    pass\n';
  const stripped = stripNoncode(source, 'python');
  assert.equal(stripped.length, source.split('\n').length);
  assert.ok(!stripped.join('').includes('not_a_def'));
  const found = scanDefinitions(source, 'python', 'a.py');
  assert.deepEqual(names(found), ['real']);
  assert.equal(found[0].line, 5);
});

test('a one-line python docstring does not swallow the rest of the file', () => {
  const source = 'x = 1\n"""one liner"""\ndef after():\n    pass\n';
  assert.deepEqual(names(scanDefinitions(source, 'python', 'a.py')), ['x', 'after']);
});

test('the opening python delimiter is the only one that closes it', () => {
  const source = "'''\n\"\"\"\ndef hidden():\n    pass\n'''\ndef seen():\n    pass\n";
  assert.deepEqual(names(scanDefinitions(source, 'python', 'a.py')), ['seen']);
});

test('a python hash comment hides a definition-shaped line', () => {
  const source = '# def commented():\nCONST = 1\n';
  assert.deepEqual(names(scanDefinitions(source, 'python', 'a.py')), ['CONST']);
});

test('an ecma block comment is stripped across lines', () => {
  const source = '/*\nfunction hidden() {}\n*/\nfunction seen() {}\n';
  const found = scanDefinitions(source, 'ecma', 'a.ts');
  assert.deepEqual(names(found), ['seen']);
  assert.equal(found[0].line, 4);
});

test('an ecma line comment hides a definition-shaped line', () => {
  const found = scanDefinitions('// function hidden() {}\nclass Seen {}\n', 'ecma', 'a.ts');
  assert.deepEqual(names(found), ['Seen']);
});

test('carriage returns do not change the scan', () => {
  const unix = 'def a():\n    pass\ndef b():\n    pass\n';
  assert.deepEqual(
    scanDefinitions(unix.replaceAll('\n', '\r\n'), 'python', 'a.py'),
    scanDefinitions(unix, 'python', 'a.py'),
  );
  assert.deepEqual(
    scanDefinitions(unix.replaceAll('\n', '\r'), 'python', 'a.py'),
    scanDefinitions(unix, 'python', 'a.py'),
  );
});

// ------------------------------------------------------------------------ scanDefinitions

test('python definitions are taken at any indentation', () => {
  const source =
    'class Outer:\n    def method(self):\n        pass\n' +
    '\n    async def coro(self):\n        pass\n';
  const found = scanDefinitions(source, 'python', 'a.py');
  assert.deepEqual(
    found.map((d) => [d.kind, d.name, d.line]),
    [
      ['class', 'Outer', 1],
      ['def', 'method', 2],
      ['def', 'coro', 5],
    ],
  );
});

test('a python constant counts only at column zero', () => {
  const source = 'TOP = 1\nANNOTATED: int = 2\nclass C:\n    inner = 3\n';
  assert.deepEqual(names(scanDefinitions(source, 'python', 'a.py')), ['TOP', 'ANNOTATED', 'C']);
});

test('a python comparison is not a definition', () => {
  assert.deepEqual(scanDefinitions('value == other\n', 'python', 'a.py'), []);
});

test('the ecma top-level declaration forms', () => {
  const table = [
    ['function plain() {}', ['function', 'plain']],
    ['export function exported() {}', ['function', 'exported']],
    ['export default async function both() {}', ['function', 'both']],
    ['class Shape {}', ['class', 'Shape']],
    ['export interface Wire {}', ['interface', 'Wire']],
    ['export type Alias = string;', ['type', 'Alias']],
    ['const NAME = 1;', ['const', 'NAME']],
    ['let mutable = 1;', ['let', 'mutable']],
    ['var old = 1;', ['var', 'old']],
    ['export enum Colour {}', ['enum', 'Colour']],
    ['const $dollar = 1;', ['const', '$dollar']],
  ];
  for (const [line, expected] of table) {
    const found = scanDefinitions(line + '\n', 'ecma', 'a.ts');
    assert.deepEqual(
      found.map((d) => [d.kind, d.name]),
      [expected],
      line,
    );
  }
});

test('an indented ecma declaration is a local and is not a definition', () => {
  const source = 'function outer() {\n  const local = 1;\n  class Inner {}\n}\n';
  assert.deepEqual(names(scanDefinitions(source, 'ecma', 'a.ts')), ['outer']);
});

test('a non-ascii identifier is invisible to the scanner', () => {
  // Declared, not accidental: `tokens()` is ASCII-only for the same reason, and a port that
  // "fixed" this on one side would diverge on every file that used one.
  assert.deepEqual(scanDefinitions('def \u00e9t\u00e9():\n    pass\n', 'python', 'a.py'), []);
});

// ------------------------------------------------------------------------- referenceNames

test('references skip short names and comment text', () => {
  const found = referenceNames('# unlikelycommentword\nab = cd + longname\n', 'python');
  assert.ok(found.has('longname'));
  assert.ok(!found.has('unlikelycommentword'));
  assert.ok(!found.has('ab') && !found.has('cd'));
});

// ----------------------------------------------------------------------------- buildGraph

test('a uniquely defined name makes an edge and a shared one does not', () => {
  // THREE definers of `shared`, not two, and the third one is the whole point. With two,
  // dropping the ambiguity SET and keeping only the delete gives the same answer — the
  // second definer deletes the entry and nothing puts it back — so a two-file fixture
  // cannot tell the rule from its side effect. J45-10 measured exactly that: the mutant
  // replacing `ambiguous.add(name)` with a no-op SURVIVED this node in its two-definer
  // form and was killed only by the repository differential. With a third definer the
  // no-op re-adds `shared` under `c2.py` and an edge appears that must not.
  const definitions = defsOf({
    'a.py': [[1, 'def', 'onlyhere']],
    'b.py': [[1, 'def', 'shared']],
    'c.py': [[1, 'def', 'shared']],
    'c2.py': [[1, 'def', 'shared']],
    'd.py': [],
  });
  const references = refsOf({
    'a.py': [],
    'b.py': [],
    'c.py': [],
    'c2.py': [],
    'd.py': ['onlyhere', 'shared'],
  });
  assert.deepEqual(plainEdges(buildGraph(definitions, references)), { 'd.py': { 'a.py': 1 } });
});

test('a file never makes an edge to itself', () => {
  const definitions = defsOf({ 'a.py': [[1, 'def', 'selfname']], 'b.py': [] });
  const references = refsOf({ 'a.py': ['selfname'], 'b.py': [] });
  assert.deepEqual(plainEdges(buildGraph(definitions, references)), {});
});

test('the weight counts distinct names, not mentions', () => {
  const definitions = defsOf({
    'a.py': [
      [1, 'def', 'alpha'],
      [2, 'def', 'beta'],
    ],
    'b.py': [],
  });
  const references = refsOf({ 'a.py': [], 'b.py': ['alpha', 'beta'] });
  assert.deepEqual(plainEdges(buildGraph(definitions, references)), { 'b.py': { 'a.py': 2 } });
});

test('a name referenced by more than an eighth of the files makes no edge', () => {
  // Twenty files. `popular` is mentioned by nine of them: 9 > 8 clears the floor and
  // 9 * 8 > 20 * 1 clears the fraction, so it makes no edge. `rarename` is mentioned by one
  // and keeps its edge.
  const definitions = defsOf({
    'a.py': [
      [1, 'const', 'popular'],
      [2, 'const', 'rarename'],
    ],
  });
  const references = refsOf({ 'a.py': [] });
  for (let i = 0; i < 20; i += 1) {
    if (!definitions.has(`f${i}.py`)) definitions.set(`f${i}.py`, []);
    references.set(`f${i}.py`, new Set(i < 9 ? ['popular'] : []));
  }
  references.set('f0.py', new Set(['popular', 'rarename']));
  assert.deepEqual(plainEdges(buildGraph(definitions, references)), { 'f0.py': { 'a.py': 1 } });
});

test('the frequency floor keeps a small tree from rejecting every name', () => {
  // Below `REFERENCE_DF_MAX_DEN` files an eighth of the tree is less than one file. The
  // floor is what stops that from emptying the map; without it a three-file project
  // produced no edges at all.
  const definitions = defsOf({ 'core.py': [[1, 'class', 'Engine']], 'caller.py': [] });
  const references = refsOf({ 'core.py': ['Engine'], 'caller.py': ['Engine'] });
  assert.deepEqual(plainEdges(buildGraph(definitions, references)), {
    'caller.py': { 'core.py': 1 },
  });
});

// ------------------------------------------------------------------------------- pagerank

/**
 * Deliberately a loop and not `reduce()`: CPython 3.12 compensates float `sum()` and JS
 * does not, so a total taken the tidy way here would be comparing against a number the
 * reference cannot produce. `runtime-py/tests/test_repomap.py::_total` is the same loop for
 * the same reason.
 */
function total(values) {
  let out = 0.0;
  for (const v of values) out += v;
  return out;
}

const edgeMap = (mapping) => {
  const out = new Map();
  for (const [k, row] of Object.entries(mapping)) out.set(k, new Map(Object.entries(row)));
  return out;
};

test('with no edges the score is the personalisation vector', () => {
  assert.deepEqual(pagerank(['a.py', 'b.py', 'c.py'], new Map(), ['b.py']), [0.0, 1.0, 0.0]);
});

test('with no focus and no edges the score is uniform', () => {
  assert.deepEqual(
    pagerank(['a.py', 'b.py', 'c.py', 'd.py'], new Map(), []),
    [0.25, 0.25, 0.25, 0.25],
  );
});

test('mass is conserved', () => {
  const nodes = ['a.py', 'b.py', 'c.py', 'd.py'];
  const edges = edgeMap({
    'a.py': { 'b.py': 2, 'c.py': 1 },
    'b.py': { 'c.py': 1 },
    'c.py': { 'a.py': 3 },
  });
  assert.ok(Math.abs(total(pagerank(nodes, edges, ['a.py'])) - 1.0) < 1e-12);
});

test('the focus reaches what it references', () => {
  const scores = pagerank(['a.py', 'b.py', 'c.py'], edgeMap({ 'a.py': { 'b.py': 1 } }), ['a.py']);
  assert.ok(scores[1] > 0.0, 'b is referenced by the focus');
  assert.equal(scores[2], 0.0, 'c is unreachable from the focus');
});

test('a focus that is not a node falls back to uniform', () => {
  assert.deepEqual(pagerank(['a.py', 'b.py'], new Map(), ['absent.py']), [0.5, 0.5]);
});

test('the iteration has reached its fixed point by the pinned count', () => {
  // The 60 is a LITERAL on purpose. Comparing `ITERATIONS` against `ITERATIONS + 20` passes
  // for any value of `ITERATIONS`, so it would prove nothing about the pinned one — J45-9
  // measured a mutant setting `ITERATIONS = 3` surviving that version of this test.
  const nodes = Array.from({ length: 12 }, (_, i) => `f${i}.py`);
  const rows = {};
  for (let i = 0; i < 12; i += 1) {
    rows[nodes[i]] = { [nodes[(i + 1) % 12]]: 1, [nodes[(i + 5) % 12]]: 2 };
  }
  const edges = edgeMap(rows);
  assert.equal(ITERATIONS, 30, 'the port contract pins this number, not merely its use');
  assert.deepEqual(
    pagerank(nodes, edges, [nodes[0]], DAMPING, ITERATIONS),
    pagerank(nodes, edges, [nodes[0]], DAMPING, 60),
  );
});

test('the pinned damping is what orders a two-hop node against a weak neighbour', () => {
  // A hub the focus leans on (weight 10), a weak direct neighbour (weight 5), and a node
  // reachable only THROUGH the hub. At the pinned 0.20 the weak neighbour outranks the
  // two-hop node; at the canonical 0.85 they swap. Without this the tuned constant is
  // pinned by nothing at all and a mutant restoring 0.85 survives the whole suite.
  const nodes = ['a_hub.py', 'b_deep.py', 'c_weak.py', 'f_focus.py'];
  const edges = edgeMap({
    'f_focus.py': { 'a_hub.py': 10, 'c_weak.py': 5 },
    'a_hub.py': { 'b_deep.py': 1 },
  });
  const scores = pagerank(nodes, edges, ['f_focus.py']);
  assert.ok(scores[2] > scores[1], 'at DAMPING=0.20 the direct neighbour wins');
  const loose = pagerank(nodes, edges, ['f_focus.py'], 0.85);
  assert.ok(loose[1] > loose[2], 'and at 0.85 it does not — the constant is load-bearing');
});

test('an empty node list ranks nothing', () => {
  assert.deepEqual(pagerank([], new Map(), []), []);
});

// ---------------------------------------------------------------------- selectDefinitions

const def = (line, kind, name) => ({ path: 'a.py', line, kind, name });

test('selection prefers a type, then reach, then the earlier line', () => {
  const definitions = [
    def(1, 'const', 'EARLY'),
    def(2, 'def', 'helper'),
    def(3, 'class', 'Subject'),
    def(4, 'def', 'popular'),
  ];
  const references = new Map([
    ['EARLY', 99],
    ['helper', 1],
    ['Subject', 1],
    ['popular', 50],
  ]);
  const chosen = selectDefinitions(definitions, references, 2);
  assert.deepEqual(names(chosen), ['Subject', 'popular'], 'the class and the reached callable');
  assert.deepEqual(
    chosen.map((d) => d.line),
    [3, 4],
    'and rendered in source order',
  );
});

test('the chosen block is rendered in source order, not choice order', () => {
  // The choice puts the class first; the render puts line 1 first. A fixture where those two
  // agree cannot tell them apart, and J45-9's first one did not.
  const definitions = [def(1, 'def', 'early_callable'), def(9, 'class', 'LateType'), def(20, 'const', 'TAIL')];
  const chosen = selectDefinitions(definitions, new Map(), 2);
  assert.deepEqual(names(chosen), ['early_callable', 'LateType']);
  assert.deepEqual(
    chosen.map((d) => d.line),
    [1, 9],
  );
});

test('selection returns everything when it fits or when unlimited', () => {
  const definitions = [def(1, 'def', 'one'), def(2, 'def', 'two')];
  assert.deepEqual(selectDefinitions(definitions, new Map(), 5), definitions);
  assert.deepEqual(selectDefinitions(definitions, new Map(), 0), definitions);
});

// -------------------------------------------------------------- repoMap over a built tree

function buildTree(root) {
  w(
    root,
    'pkg/core.py',
    '"""Docstring mentioning nothing."""\n\nclass CoreEngine:\n    def churn(self):\n' +
      '        return 1\n\n    def _private_helper(self):\n        return 2\n',
  );
  w(
    root,
    'pkg/caller.py',
    'from pkg.core import CoreEngine\n\n\ndef drive():\n' +
      '    engine = CoreEngine()\n    return engine.churn()\n',
  );
  w(root, 'pkg/stranger.py', 'def unrelatedthing():\n    return 0\n');
  w(root, 'notes.md', '# not source\n');
  w(root, 'data.json', '{}\n');
  return root;
}

test('the map ranks what the focus reaches and names the rest', () => {
  const root = buildTree(tree());
  const result = repoMap(root, { focus: ['pkg/caller.py'] });
  assert.equal(result.nodes, 3);
  assert.deepEqual(
    result.ranked.map((e) => e.path),
    ['pkg/core.py'],
  );
  assert.ok(!result.text.includes('pkg/caller.py'), 'the focus file is not spent on itself');
  assert.ok(result.text.includes('CoreEngine'));
  const counts = omissions(result);
  assert.equal(counts[OMIT_UNKNOWN_LANGUAGE], 2, 'notes.md and data.json are named, not dropped');
  assert.equal(counts[OMIT_UNREACHABLE], 1, 'stranger.py is unreachable from the focus');
});

test('an empty focus ranks the whole tree', () => {
  const root = buildTree(tree());
  const result = repoMap(root, { focus: [] });
  assert.deepEqual(new Set(result.ranked.map((e) => e.path)), new Set([
    'pkg/core.py',
    'pkg/caller.py',
    'pkg/stranger.py',
  ]));
  assert.deepEqual(result.focus, []);
});

test('a file that is not utf-8 is counted and does not raise', () => {
  const root = tree();
  w(root, 'good.py', 'def fine():\n    pass\n');
  writeFileSync(join(root, 'bad.py'), Buffer.from('6465662062726f6b656e28293a0a2020202078203d2027fffe270a', 'hex'));
  const result = repoMap(root);
  assert.equal(omissions(result)[OMIT_UNREADABLE], 1);
  assert.ok(!result.text.includes('bad.py'));
  assert.equal(result.nodes, 1);
});

test('a file over the size cap is counted and not scanned', () => {
  const root = tree();
  w(root, 'small.py', 'def fine():\n    pass\n');
  w(root, 'huge.py', 'x = 1\n' + '# pad\n'.repeat(Math.floor(MAX_FILE_BYTES / 6)));
  const result = repoMap(root);
  assert.equal(omissions(result)[OMIT_SIZE_CAP], 1);
  assert.equal(facts(result, OMIT_SIZE_CAP).cap_bytes, MAX_FILE_BYTES);
  assert.equal(result.nodes, 1);
});

test('a source file holding no definition is counted', () => {
  const root = tree();
  w(root, 'a.py', 'def real():\n    pass\n');
  w(root, 'empty.py', '# nothing but a comment\n');
  assert.equal(omissions(repoMap(root))[OMIT_NO_DEFINITIONS], 1);
});

test('the per-file cap is counted with the limit that caused it', () => {
  const root = tree();
  let body = '';
  for (let i = 0; i < MAX_DEFINITIONS_PER_FILE + 3; i += 1) body += `def name${i}():\n    pass\n`;
  w(root, 'wide.py', body);
  const result = repoMap(root);
  assert.equal(omissions(result)[OMIT_PER_FILE_CAP], 3);
  assert.equal(facts(result, OMIT_PER_FILE_CAP).per_file, MAX_DEFINITIONS_PER_FILE);
});

test('a budget too small reports what it could not carry', () => {
  const root = buildTree(tree());
  const result = repoMap(root, { budget: 0 });
  assert.equal(result.listingBytes, 0);
  assert.equal(result.filesRendered, 0);
  assert.equal(facts(result, OMIT_BUDGET).budget_bytes, 0);
  assert.equal(omissions(result)[OMIT_BUDGET], result.ranked.length);
  assert.ok(result.text.startsWith('# omitted:'));
});

test('the listing never exceeds the budget', () => {
  const root = buildTree(tree());
  // EVERY budget, not every seventh: an off-by-one in the fill only shows at a byte where a
  // line lands exactly on the boundary, and J45-9 measured a step of 7 stepping over all of
  // them — a mutant loosening the comparison to `> budget + 1` survived the sparser sweep.
  for (let budget = 0; budget < 300; budget += 1) {
    assert.ok(repoMap(root, { budget }).listingBytes <= budget, String(budget));
  }
});

test('the omission footer is not charged to the budget', () => {
  // The rule this pins: a budget that could suppress the disclosure of what it dropped
  // would be the defect the footer exists to close.
  const root = buildTree(tree());
  const result = repoMap(root, { budget: 40 });
  assert.ok(result.listingBytes <= 40);
  assert.ok(Buffer.byteLength(result.text, 'utf8') > 40);
  assert.ok(result.text.split('\n').at(-1).startsWith('# omitted:'));
});

test('the footer names every subject in the pinned order', () => {
  const root = buildTree(tree());
  w(root, 'empty.py', '# nothing\n');
  const result = repoMap(root, { focus: ['pkg/caller.py'], budget: 30 });
  const line = result.text.split('\n').at(-1);
  const subjects = line.slice('# omitted: '.length).split(' ').map((f) => f.split('=')[0]);
  assert.ok(subjects.length > 1, 'a one-subject footer cannot test an order');
  assert.deepEqual(
    subjects,
    [...subjects].sort((a, b) => OMISSION_ORDER.indexOf(a) - OMISSION_ORDER.indexOf(b)),
  );
});

test('a clean tree has no footer at all', () => {
  const root = tree();
  w(root, 'a.py', 'def alpha():\n    pass\n');
  w(root, 'b.py', 'def beta():\n    return alpha\n');
  const result = repoMap(root, { budget: DEFAULT_BUDGET });
  assert.ok(!result.text.includes('# omitted'));
  assert.deepEqual(result.omissions, []);
});

// ---------------------------------------------------------- determinism — the port contract

test('a tie in the rank is broken by path', () => {
  // Three files identical but for their names, all referenced once by the focus: the scores
  // are equal to the last bit, so ONLY the by-path tie-break decides the order.
  const root = tree();
  w(root, 'zulu.py', 'def zuluthing():\n    pass\n');
  w(root, 'alpha.py', 'def alphathing():\n    pass\n');
  w(root, 'mike.py', 'def mikething():\n    pass\n');
  w(root, 'focus.py', 'def go():\n    return zuluthing, alphathing, mikething\n');
  const result = repoMap(root, { focus: ['focus.py'] });
  const units = new Set(result.ranked.map((e) => e.rankUnits));
  assert.equal(units.size, 1, 'the three scores must actually tie for this to test anything');
  assert.deepEqual(
    result.ranked.map((e) => e.path),
    ['alpha.py', 'mike.py', 'zulu.py'],
  );
});

test('the rendered map carries no raw float', () => {
  // Trap (8): `repr(1.0)` is '1.0' in CPython and String(1.0) is '1'; `1e-07` vs `1e-7`. A
  // score in the text would make the two runtimes disagree byte for byte on a right answer.
  const root = buildTree(tree());
  const result = repoMap(root, { focus: ['pkg/caller.py'] });
  for (const line of result.text.split('\n')) {
    const bare = line.replaceAll('.py', '').replaceAll('.md', '').replaceAll('.json', '');
    assert.ok(!bare.includes('.'), line);
  }
  assert.ok(result.ranked.every((e) => Number.isInteger(e.rankUnits)));
});

test('rankUnits is a floor of the scaled score', () => {
  // Trap (9): CPython's `round` is banker's and JS's `Math.round` is half-up, so the
  // quantisation has to be a floor. A three-file fixture could not tell the two apart —
  // every score there happened to round down — so this runs over the repository's own
  // package, where hundreds of scores make the distinction certain, and ASSERTS that it is
  // certain rather than assuming it.
  const result = repoMap(join(REPO, 'runtime-py', 'src', 'bantamkit'), {
    focus: ['memory/dream.py'],
  });
  const scaled = result.ranked.map((e) => e.score * SCORE_SCALE);
  assert.ok(
    scaled.some((v) => Math.floor(v) !== Math.round(v)),
    'this fixture cannot distinguish floor from round and so cannot test it',
  );
  result.ranked.forEach((entry, i) => assert.equal(entry.rankUnits, Math.floor(scaled[i])));
});

test('no float summation or rounding in the pagerank source', () => {
  // The mirror of `test_no_float_summation_or_rounding_in_the_source`, and it is a guard
  // rather than a proof. `sum()` over floats is COMPENSATED in CPython 3.12 and nothing in
  // JS is — measured on node v25.2.1, `[0.1, 0.2, 0.3, 1e16, -1e16]` totals 0.6 through
  // CPython's `sum()`, 0.0 through a CPython loop, and 0 through both a JS loop and
  // `Array.reduce`. So the risk on THIS side is the reverse of the Python side's: a
  // `reduce` here is not wrong on its own, it is wrong the moment the reference is allowed
  // to keep using `sum()`, and neither difference shows up in any output an ASCII corpus
  // can compare.
  const source = readFileSync(new URL('../src/repomap.ts', import.meta.url), 'utf8');
  const start = source.indexOf('export function pagerank(');
  assert.ok(start > 0, 'pagerank must still be a named export for this guard to find it');
  const end = source.indexOf('\ninterface Rendered', start);
  assert.ok(end > start, 'the slice terminator moved — this guard would otherwise read nothing');
  const body = source
    .slice(start, end)
    .split('\n')
    .filter((line) => !line.trimStart().startsWith('//'))
    .join('\n');
  assert.ok(body.length > 800, `the slice is ${body.length} bytes and cannot be the function`);
  assert.ok(!body.includes('.reduce('), 'float accumulation must be a written-out loop');
  assert.ok(!body.includes('Math.round('), 'Math.round is half-up and CPython round() is not');
  assert.ok(!body.includes('**'), 'no exponentiation: CPython and JS disagree on its edge cases');
});

test('the map is byte-stable across runs', () => {
  const root = buildTree(tree());
  const first = repoMap(root, { focus: ['pkg/caller.py'] });
  const second = repoMap(root, { focus: ['pkg/caller.py'] });
  assert.equal(first.text, second.text);
  assert.deepEqual(
    first.ranked.map((e) => e.rankUnits),
    second.ranked.map((e) => e.rankUnits),
  );
});

// ---------------------------------------------------------------------------- walkSources

test('the walk skips the named directories', () => {
  const root = tree();
  w(root, 'src/keep.py', 'x = 1\n');
  for (const skipped of ['node_modules', '.venv', '__pycache__', '.git']) {
    w(root, `${skipped}/drop.py`, 'x = 1\n');
  }
  assert.deepEqual(walkSources(root), ['src/keep.py']);
});

// ----------------------------------------------------------------- NODE-ONLY PINS
//
// Four mutants survived a Python/Node differential over this whole repository — the full
// rendered map, the omission footer and the IEEE-754 bits of every score — because this
// repository holds no directory symlink, no astral path, no source over 1 MiB and no budget
// that lands on a block boundary. The size cap and the budget sweep are covered above. The
// two below are the ones J45-9 could not kill from Python AT ALL, and named as this port's
// work rather than its translation.

const symlinks = { skip: process.platform === 'win32' ? 'a directory symlink needs a privilege this host may not grant' : false };

test('the walk does not follow a directory symlink', symlinks, () => {
  const root = tree();
  w(root, 'real/a.py', 'x = 1\n');
  symlinkSync(join(root, 'real'), join(root, 'loop'));
  assert.deepEqual(walkSources(root), ['real/a.py']);
});

test('the Dirent that looks like the answer is the wrong one', symlinks, () => {
  // THE PROBE THAT MAKES THE NODE ABOVE NON-VACUOUS. `os.walk(followlinks=False)` gives
  // CPython the whole rule for free, so J45-9's mutation 24 — delete the explicit `islink`
  // filter — SURVIVED on that side. Here it is real logic, and the reason is measured
  // rather than asserted: `readdirSync(..., {withFileTypes: true})` reports from LSTAT, so
  // a symlink to a directory answers `isDirectory() === false` and a walk that trusted the
  // Dirent would file it as a SOURCE FILE, not as a directory it declines to enter.
  const root = tree();
  w(root, 'real/a.py', 'x = 1\n');
  w(root, 'plain.py', 'y = 2\n');
  symlinkSync(join(root, 'real'), join(root, 'linkdir'));
  symlinkSync(join(root, 'plain.py'), join(root, 'linkfile.py'));
  symlinkSync(join(root, 'nowhere-at-all'), join(root, 'dangling.py'));

  const byName = Object.fromEntries(
    readdirSync(root, { withFileTypes: true }).map((d) => [d.name, d]),
  );
  assert.equal(byName['linkdir'].isDirectory(), false, 'the Dirent does NOT follow the link');
  assert.equal(byName['linkdir'].isSymbolicLink(), true);
  assert.equal(byName['real'].isDirectory(), true, 'and a real directory still answers true');

  // What CPython's walk yields, reproduced: the directory link is gone entirely, the file
  // link is a file, and the dangling link is a file that will be counted unreadable.
  assert.deepEqual(walkSources(root), ['dangling.py', 'linkfile.py', 'plain.py', 'real/a.py']);
  assert.equal(omissions(repoMap(root))[OMIT_UNREADABLE], 1, 'the dangling link is counted');
});

test('a tie between an astral path and a BMP one resolves by code point, not code unit', () => {
  // THE ONE RULE NO PYTHON FIXTURE CAN MAKE NON-VACUOUS. CPython's `str` comparison IS
  // code-point comparison, so J45-9's mutant turning `_by_code_point` into the identity was
  // UNKILLABLE there. Here the default `Array.prototype.sort` compares UTF-16 code UNITS:
  // U+1F414's lead surrogate is 0xD83D and sorts BELOW U+FF01, while its code point 0x1F414
  // sorts ABOVE. The two files below are structurally identical, so their scores tie to the
  // last bit and only the comparator decides.
  const root = tree();
  const astral = '\u{1F414}widget.py';
  const fullwidth = '\uFF01widget.py';
  w(root, astral, 'def astral_widget():\n    return SharedThing\n');
  w(root, fullwidth, 'def fullwidth_widget():\n    return SharedThing\n');
  w(root, 'shared.py', 'class SharedThing:\n    pass\n');

  assert.deepEqual(
    [astral, fullwidth].sort(),
    [astral, fullwidth],
    'the JS default sort puts the astral path FIRST — if this flips, the trap is gone',
  );

  const result = repoMap(root, { focus: [] });
  const listed = result.ranked.map((e) => e.path).filter((p) => p.endsWith('widget.py'));
  const units = new Set(
    result.ranked.filter((e) => e.path.endsWith('widget.py')).map((e) => e.rankUnits),
  );
  assert.equal(units.size, 1, 'the two scores must actually tie for this to test anything');
  assert.deepEqual(listed, [fullwidth, astral], 'code point, not code unit');
  assert.deepEqual(walkSources(root).slice(-2), [fullwidth, astral]);
});

test('the budget is UTF-8 bytes, not characters', () => {
  // `Buffer.byteLength(s, 'utf8')` is `len(s.encode('utf-8'))`. A `.length` would count two
  // UTF-16 units for an astral character and CPython would count one — and neither is the
  // number of bytes either side is spending.
  const root = tree();
  const wide = '\u{1F414}\u{1F414}\u{1F414}.py'; // 15 UTF-8 bytes, 9 UTF-16 units, 7 code points
  w(root, wide, 'def widecall():\n    pass\n');
  const result = repoMap(root, { budget: 40 });
  assert.equal(result.listingBytes, Buffer.byteLength(result.text.split('\n# omitted')[0], 'utf8'));
  assert.ok(
    Buffer.byteLength(wide, 'utf8') > wide.length,
    'the fixture must actually be multi-byte',
  );
});

// -------------------------------------------------------- the repository's own sources

test("the map over this repository's python package finds its own modules", () => {
  const root = join(REPO, 'runtime-py', 'src', 'bantamkit');
  const result = repoMap(root, { focus: ['memory/dream.py'], budget: DEFAULT_BUDGET });
  assert.ok(result.nodes > 20);
  assert.ok(result.edges > 0);
  const listed = result.ranked.map((e) => e.path);
  assert.ok(listed.slice(0, 3).includes('memory/store.py'), JSON.stringify(listed.slice(0, 5)));
  assert.ok(!listed.includes('memory/dream.py'));
  assert.ok(result.listingBytes <= DEFAULT_BUDGET);
  assert.ok(result.damping > 0.0 && result.iterations === ITERATIONS);
});
