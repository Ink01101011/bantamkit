/**
 * ts2py-codec — the fact-file codec three ways: Node, runtime-py's PyYAML codec, and the Python
 * ts2py compiles from `factfile.ts` + `pyyaml.ts` (#315, J86-2).
 *
 * THE ARMS
 *   node     `runtime-ts/dist/memory/factfile.js` (run `npm run build` if stale): `decodeFactBytes`,
 *            `parseFactText`, `formatFact`; and for the store-level round trip, the store's own
 *            `readFact` followed by `formatFact`, which is what a recall stamp writes.
 *   py       runtime-py as it ships, real PyYAML: `load_frontmatter` for a parse, `_fact_text`
 *            for a format, `_fact_text(_read_fact(path))` for a round trip (`ref/ts2py_codec_ref.py`).
 *   gen      the modules `tools/ts2py` writes into this run's scratch, COMPILED FRESH every run
 *            (as `--suite ts2py` does), so the suite cannot pass on a stale generated file;
 *            `generated/<module>/source-sha256` checks each header names the bytes on disk.
 *
 * WHAT IS COMPARED, per input
 *   parse    the decoded fact: every meta key in order, each value with its Python type, `str()`,
 *            `safe_dump` spelling and truthiness (a `PyScalar`'s four observables), and the body.
 *   format   the exact text written for a fact built from the same values.
 *   rt       format(parse(x)): node and gen compared at the CODEC (`formatFact(parseFactText)`);
 *            py against node at the STORE (`_fact_text(_read_fact)` / `formatFact(readFact)`),
 *            because runtime-py has no codec-only round trip — `_read_fact` is where it lives.
 *
 * THE RULES
 *   gen = node   always, byte for byte, refusals included with their name and message. The
 *                generated module is compiled from node's source; any difference is a ts2py bug.
 *   py = node    the existing two-runtime contract. A refusal is compared as a bit (the two
 *                refusal TEXTS differ by the registered #120 ruling in `factfile.ts`). Every
 *                disagreement must fall in one of the five classes in `KNOWN` below, which this
 *                suite FOUND on its first run and which are pre-existing, not deliberate: on the
 *                fuzz each class is a `ruling:` case that must keep occurring, on the real stores
 *                each is counted in a note, and a disagreement outside them is red everywhere.
 *                The previous-release files show none at all.
 *   three-way    where py and node agree, gen agrees — implied by the two above, and counted in
 *                the notes, together with every input where they do not.
 *
 * THE INPUTS
 *   (a) real    every fact file in the stores on THIS machine: `<repo>/.bantamkit/memory`,
 *               `~/.bantamkit/memory` (facts/ and archive/), and the Claude Code native memory
 *               dirs `~/.claude/projects/<p>/memory/*.md` that open with `---`. They are COPIED
 *               into the run's scratch first and only the copies are read. Their contents never
 *               appear in a case: ids are `<source>#<n>`, counts go to the notes, and the cases
 *               are aggregates, so the case count does not move with the stores. Absent dirs
 *               (CI, another checkout) skip the class with a note saying so.
 *   (b) fuzz    seeded (`FUZZ_SEED`): facts built from the hard YAML values (number, bool, null
 *               and date look-alikes, quotes, colons, `#`, indicators, multi-line, control and
 *               non-ASCII characters, empties, lists, typed scalars past 2^53, 1e21, -0.0, nan,
 *               inf) formatted by all three and read back; and hand-written frontmatters
 *               (block scalars, flow and block sequences, nested `metadata:` maps, comments,
 *               escapes, CRLF) parsed and round-tripped by all three. The generator is below;
 *               its output is never committed.
 *   (c) release fact files written by released bantamkit versions from PyPI through their own
 *               `MemoryStore.save` and `recall` (`fixtures/factfile-cases/<version>/`, with
 *               `written.json` and `write_fixtures.py`). `EXPECTED.json` there pins what the
 *               current codec reads and writes back for each, so a change to either is red here.
 */
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, utimesSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'ts2py-codec';
export const summary =
  'fact-file codec three ways: Node, runtime-py (PyYAML) and the ts2py-generated codec, on real stores, a seeded fuzz and previous-release files';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'ts2py_codec_ref.py');
const RELEASES = join(here, 'fixtures', 'factfile-cases');
const SOURCES = ['runtime-ts/src/memory/pyyaml.ts', 'runtime-ts/src/memory/factfile.ts'];
const PACKAGE = 'ts2py_codec_gen';

/** Spelled, not counted: a release fixture that loses a file is red, not a smaller suite. */
const RELEASE_HEADLINE = { '0.27.0': 10, '0.35.9': 10, '0.36.2': 10, '0.39.3': 10 };
const FUZZ_SEED = 315;
const FUZZ_FACTS = 1200;
const FUZZ_TEXTS = 1500;
/** A fixed mtime for every copied file, so `_mtime_date` / `pyMtimeDate` agree in any $TZ. */
const PINNED_MTIME = new Date('2026-01-15T12:00:00Z');

// --------------------------------------------------------------------------------- compile

function findCargo() {
  if (process.env.TS2PY_CARGO) return process.env.TS2PY_CARGO;
  const home = join(homedir(), '.cargo', 'bin', process.platform === 'win32' ? 'cargo.exe' : 'cargo');
  return existsSync(home) ? home : 'cargo';
}

function ts2py(args, out) {
  const cargo = findCargo();
  const r = spawnSync(
    cargo,
    ['run', '--release', '--quiet', '--manifest-path', join(repoRoot, 'tools', 'ts2py', 'Cargo.toml'), '--', ...args],
    { cwd: repoRoot, encoding: 'utf8', timeout: 900_000, maxBuffer: 64 * 1024 * 1024 },
  );
  if (r.error) throw new Error(`ts2py: could not run ${cargo}: ${r.error.message} (set TS2PY_CARGO)`);
  if (r.status !== 0) throw new Error(`ts2py ${args.join(' ')} failed (exit ${r.status})\n${r.stderr}`);
  if (!existsSync(out)) throw new Error(`ts2py: exited 0 but wrote no ${out}`);
}

/** The codec package, compiled now: pyyaml.py, factfile.py, the runtime and the adapters. */
function compileCodec(root) {
  const pkg = join(root, PACKAGE);
  mkdirSync(pkg, { recursive: true });
  writeFileSync(join(pkg, '__init__.py'), '');
  ts2py([...SOURCES, '--out-dir', pkg, '--runtime-module', '._ts2py_runtime'], join(pkg, 'factfile.py'));
  ts2py(['--emit-runtime', join(pkg, '_ts2py_runtime.py')], join(pkg, '_ts2py_runtime.py'));
  ts2py(['--emit-adapters', join(pkg, '_ts2py_adapters.py')], join(pkg, '_ts2py_adapters.py'));
  return pkg;
}

// ----------------------------------------------------------------------------- node arms

function nodeArms(ff, yaml, store) {
  const canon = (v) => {
    if (v === null || typeof v === 'string') return v;
    if (Array.isArray(v)) return v.map(canon);
    if (v instanceof yaml.PyScalar) return { t: v.pyType, s: v.text, y: v.yaml, b: v.truthy };
    if (typeof v === 'object') return { map: Object.entries(v).map(([k, x]) => [k, canon(x)]) };
    throw new Error(`no canonical form for ${typeof v}`);
  };
  const err = (e) => ({ error: `${e && e.name}: ${e && e.message}` });
  const value = (v) =>
    v !== null && typeof v === 'object' && !Array.isArray(v) && 'plain' in v
      ? yaml.constructPlain(v.plain)
      : Array.isArray(v)
        ? v.map(value)
        : v;
  return {
    parse(bytes) {
      try {
        const p = ff.parseFactText(ff.decodeFactBytes(bytes));
        return { meta: Object.entries(p.meta).map(([k, v]) => [k, canon(v)]), body: p.body };
      } catch (e) {
        return err(e);
      }
    },
    rt(bytes) {
      try {
        return ff.formatFact(ff.parseFactText(ff.decodeFactBytes(bytes)));
      } catch (e) {
        return err(e);
      }
    },
    rtStore(path) {
      try {
        // `readFact` is the store's private read: no instance state, so any receiver serves.
        return ff.formatFact(store.MemoryStore.prototype.readFact.call({}, path));
      } catch (e) {
        return err(e);
      }
    },
    format(fact) {
      try {
        const built = {};
        for (const [k, v] of Object.entries(fact)) {
          if (k === 'extra') built.extra = v.map(([key, x]) => [key, value(x)]);
          else if (k === 'body' || k === 'keywords') built[k] = v;
          else built[k] = value(v);
        }
        return ff.formatFact(built);
      } catch (e) {
        return err(e);
      }
    },
  };
}

// ---------------------------------------------------------------------------- comparison

/**
 * The py/node disagreements this suite found on its first run (J86-2, 2026-11-15), by class.
 * NONE IS A DELIBERATE DIVERGENCE: none has a row in `docs/porting.md`. They are pre-existing
 * findings in the two-runtime contract, registered here so this suite can hold the generated
 * codec to Node without going red on them, and so each one is still SEEN: on the fuzz every
 * class is a `ruling:` case that must keep occurring (fix one and its case goes stale and
 * red, and this list is edited), and anything outside these classes is red everywhere.
 */
const KNOWN = {
  'node-refuses':
    "node refuses a frontmatter PyYAML reads (#120's registered ruling: outside the language `parseFrontmatter` claims, node raises rather than guesses): a quoted key such as `'True':`, which BOTH emitters write for a Fact.extra key YAML would not read as text, and a block sequence inside a nested `metadata:` mapping, which Claude Code native memory files carry",
  'non-text-key':
    'a key YAML resolves to a non-string (`on:` is True, `null:` is None, `True:`): PyYAML keys the mapping by that value, node by the text; both stores drop such a key (`isTextKey` in factfile.ts, `isinstance(k, str)` in `_read_fact`), so it never reaches a Fact or a write',
  'nested-map-rewrite':
    "a nested mapping value (`metadata:` blocks, as Claude Code's native memory files carry) is read alike by both, but the store's read-then-write differs: runtime-py's `_fact_text` dumps it back as a block mapping, node's `formatFact` throws `cannot emit object for key metadata` (`safeDumpMapping` emits scalars and lists only)",
  'yaml11-breaks':
    "U+0085, U+2028 or U+2029 inside a quoted or plain scalar: PyYAML reads each as a YAML 1.1 line break and folds it (so runtime-py does not read back what its own `safe_dump` wrote), node keeps the character; both write the same bytes",
  'pyyaml-refuses':
    'PyYAML refuses a hand-written frontmatter node reads: a raw non-printable character (`unacceptable character #x0001`) or a multi-line single-quoted scalar whose continuation sits at column 0 (`ScannerError`)',
};

const refused = (x) => x !== null && typeof x === 'object' && 'error' in x;
const asBit = (x) => (refused(x) ? { refused: true } : x);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** The first meta key whose value differs, or `body`, or the refusal — never a value. */
function where(a, b) {
  if (refused(a) || refused(b)) return `refused py=${refused(a)} node=${refused(b)}`;
  if (typeof a === 'string' || typeof b === 'string') {
    const [ca, cb] = [[...String(a)], [...String(b)]];
    const n = ca.findIndex((ch, i) => ch !== cb[i]);
    return `text differs at char ${n === -1 ? Math.min(ca.length, cb.length) : n}`;
  }
  const ka = a.meta.map(([k]) => (typeof k === 'string' ? k : JSON.stringify(k)));
  const kb = b.meta.map(([k]) => k);
  if (!same(ka, kb)) return `keys differ: ${JSON.stringify(ka)} vs ${JSON.stringify(kb)}`;
  for (let i = 0; i < a.meta.length; i += 1) {
    if (!same(a.meta[i][1], b.meta[i][1])) return `value of '${ka[i]}' differs`;
  }
  return a.body === b.body ? 'identical' : 'body differs';
}

/** Which KNOWN class explains a py/node parse disagreement, or null when none does. */
function parseClass(text, py, node, isTextKey) {
  if (refused(node) && !refused(py)) return 'node-refuses';
  if (refused(py) && !refused(node)) return 'pyyaml-refuses';
  const textKeys = (m, keep) => m.filter(([k]) => keep(k));
  if (
    same(
      { meta: textKeys(py.meta, (k) => typeof k === 'string'), body: py.body },
      { meta: textKeys(node.meta, (k) => isTextKey(k)), body: node.body },
    )
  ) {
    return 'non-text-key';
  }
  if (/[\x85\u2028\u2029]/.test(text)) return 'yaml11-breaks';
  return null;
}

function threeWay(inputs, ans, isTextKey) {
  const out = { parseGen: [], rtGen: [], unclassified: [], known: {}, readAlike: 0, refusedAlike: 0, codecRtAgree: 0, storeLayer: 0 };
  for (const k of Object.keys(KNOWN)) out.known[k] = [];
  inputs.forEach((input, i) => {
    const { node, py, gen } = ans[i];
    if (!same(gen.parse, node.parse)) out.parseGen.push({ id: input.id, at: where(gen.parse, node.parse) });
    if (!same(gen.rt, node.rt)) out.rtGen.push({ id: input.id, at: where(gen.rt, node.rt) });

    const parseAgrees = same(asBit(py.parse), asBit(node.parse));
    const rtAgrees = same(asBit(py.rt), asBit(node.rtStore));
    let cls = null;
    if (!parseAgrees) cls = parseClass(input.text, py.parse, node.parse, isTextKey);
    else if (!rtAgrees && !refused(py.rt) && refused(node.rtStore) && /cannot emit object for key/.test(node.rtStore.error)) {
      cls = 'nested-map-rewrite';
    }
    if (!parseAgrees || !rtAgrees) {
      if (cls === null) {
        out.unclassified.push({ id: input.id, parse: parseAgrees ? 'agrees' : where(py.parse, node.parse), rtStore: rtAgrees ? 'agrees' : where(py.rt, node.rtStore) });
      } else {
        out.known[cls].push(input.id);
      }
    }
    if (!refused(py.parse) && same(py.parse, node.parse)) out.readAlike += 1;
    if (refused(py.parse) && refused(node.parse)) out.refusedAlike += 1;
    // The three-way: where runtime-py's stamp and node's codec write the same bytes, gen does too
    // (it equals node's codec, checked above); where they differ it is the store layer's read.
    if (!refused(py.rt) && py.rt === node.rt) out.codecRtAgree += 1;
    else if (!refused(py.rt) && !refused(node.rt) && rtAgrees) out.storeLayer += 1;
  });
  return out;
}

function aggregateCases(prefix, r, label, { rulings }) {
  const show = (xs) => xs.slice(0, 40);
  const cases = [
    { name: `${prefix}/parse/gen=node`, kind: 'json', expected: [], actual: show(r.parseGen) },
    { name: `${prefix}/rt/gen=node`, kind: 'json', expected: [], actual: show(r.rtGen) },
    { name: `${prefix}/py=node/unclassified`, kind: 'json', expected: [], actual: show(r.unclassified) },
    {
      name: `${prefix}/not-vacuous`,
      kind: 'string',
      expected: `${label}: some inputs are read alike by all three`,
      actual: r.readAlike > 0 ? `${label}: some inputs are read alike by all three` : `${label}: none read alike`,
    },
  ];
  if (rulings) {
    for (const [cls, why] of Object.entries(KNOWN)) {
      cases.push({
        name: `${prefix}/py=node/known:${cls}`,
        kind: 'json',
        expected: { [cls]: 0 },
        actual: { [cls]: r.known[cls].length },
        ruling: `pre-existing py/node finding (J86-2), not a deliberate divergence: ${why}`,
      });
    }
  }
  return cases;
}

function summarise(label, n, r) {
  const known = Object.entries(r.known)
    .filter(([, ids]) => ids.length > 0)
    .map(([k, ids]) => `${k} ${ids.length}`)
    .join(', ');
  return (
    `${label}: ${n} inputs; read alike by all three ${r.readAlike}, refused by all three ${r.refusedAlike}; ` +
    `gen!=node parse ${r.parseGen.length} rt ${r.rtGen.length}; py!=node by known class: ${known || 'none'}; ` +
    `unclassified ${r.unclassified.length}; round trip where runtime-py's stamp = node's codec = gen ${r.codecRtAgree}, ` +
    `where the stamp differs from the codec-only round trip but py = node at the store ${r.storeLayer} ` +
    `(the store's read: created from mtime, an unquoted timestamp as text, a description made one line)`
  );
}

// --------------------------------------------------------------------------------- inputs

function copyPinned(src, dest) {
  copyFileSync(src, dest);
  utimesSync(dest, PINNED_MTIME, PINNED_MTIME);
}

/** Class (a): copies of the real stores. Returns [] and a reason when there is nothing to read. */
function realInputs(bed) {
  const home = homedir();
  const sources = [];
  for (const [label, root] of [
    ['repo-store', join(repoRoot, '.bantamkit', 'memory')],
    ['home-store', join(home, '.bantamkit', 'memory')],
  ]) {
    for (const sub of ['facts', 'archive']) {
      const dir = join(root, sub);
      if (existsSync(dir)) sources.push({ label: `${label}/${sub}`, dir, test: () => true });
    }
  }
  const projects = join(home, '.claude', 'projects');
  if (existsSync(projects)) {
    for (const p of readdirSync(projects).sort()) {
      const dir = join(projects, p, 'memory');
      if (existsSync(dir) && statSync(dir).isDirectory()) {
        sources.push({
          label: 'claude-native',
          dir,
          // a bantamkit-format file opens with a frontmatter fence; MEMORY.md is an index
          test: (f, path) => f !== 'MEMORY.md' && readFileSync(path).subarray(0, 4).toString('latin1').startsWith('---'),
        });
      }
    }
  }
  const out = [];
  const perSource = {};
  mkdirSync(bed, { recursive: true });
  for (const s of sources) {
    for (const f of readdirSync(s.dir).sort()) {
      const path = join(s.dir, f);
      if (!f.endsWith('.md') || !statSync(path).isFile() || !s.test(f, path)) continue;
      perSource[s.label] = (perSource[s.label] ?? 0) + 1;
      const id = `${s.label}#${perSource[s.label]}`;
      const dest = join(bed, `real-${out.length}.md`);
      copyPinned(path, dest);
      out.push({ id, path: dest });
    }
  }
  return { inputs: out, perSource, looked: sources.length };
}

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** The hard values: every one is here because PyYAML resolves, quotes or folds it specially. */
const HARD = [
  '', ' ', 'null', 'Null', 'NULL', '~', 'yes', 'No', 'ON', 'off', 'true', 'False', 'y', 'n',
  '12', '-7', '+3', '0', '0x1F', '017', '0o17', '0b101', '1_000', '190:20:30', '1.5', '-0.0', '0.0',
  '1e21', '1.0e+21', '6.02e+23', '.nan', '.NaN', '.inf', '-.Inf', '+.inf', '9007199254740993',
  '123456789012345678901234', '2026-08-23', '2026-8-3', '2026-08-23 10:00:00', '2026-08-23T10:00:00Z',
  '2026-08-23t10:00:00.5+07:00', '2026-02-30', '<<', '=', ' lead', 'trail ', ' both ', "it's", "'quoted'",
  '"dq"', 'a: b', 'a:b', 'a #b', 'a#b', '#x', '- x', '-x', '? x', '?x', '[x]', '{x}', '&a', '*a', '!t',
  '|', '>', '%', '@', '`', '---', '...', '--- x', 'a\nb', 'a\n\nb', 'a \nb', 'a\n b', '\n', 'a\tb', '\t',
  'a\x01b', '\x7f', 'a\x85b', '\u2028', 'a\ufeffb', 'a\u00a0b', 'ภาษาไทย', 'em — dash', '🐔', '👨‍👩‍👧‍👦',
  'a\\b', 'a "quote"', ',', 'a, b', 'x'.repeat(120), Array(30).fill('wrap').join(' '),
];
const TYPED = [
  'null', '~', 'yes', 'No', 'true', 'off', '0', '12', '-7', '0x1F', '017', '0b101', '1_000', '190:20:30',
  '1.5', '-0.0', '0.0', '1.0e+21', '6.02e+23', '.nan', '.inf', '-.Inf', '9007199254740993',
  '123456789012345678901234', '2026-08-23', '2026-08-23 10:00:00', '2026-08-23T10:00:00Z',
  '2026-08-23t10:00:00.5+07:00', 'plainword', '1e21',
];
const KEYS = ['priority', 'source', 'note', 'x_y', 'metadata', 'on', 'null', 'True', 'zz-last', 'origin'];

function fuzzFacts(n) {
  const rnd = mulberry32(FUZZ_SEED);
  const pick = (xs) => xs[Math.floor(rnd() * xs.length)];
  const str = () => {
    const parts = 1 + Math.floor(rnd() * 3);
    let s = '';
    for (let i = 0; i < parts; i += 1) s += rnd() < 0.6 ? pick(HARD) : ` ${pick(['word', 'fact', 'ok', 'α', 'deploy'])} `;
    if (rnd() < 0.03) s += '\ud800'; // a lone surrogate, which only a YAML escape can carry
    return s;
  };
  const val = () => (rnd() < 0.25 ? { plain: pick(TYPED) } : rnd() < 0.05 ? null : str());
  const facts = [];
  for (let i = 0; i < n; i += 1) {
    const fact = {
      name: rnd() < 0.85 ? `fact-${i}` : val(),
      description: val(),
      type: rnd() < 0.8 ? pick(['user', 'feedback', 'project', 'reference']) : val(),
      created: rnd() < 0.6 ? pick(['2026-01-02', '2025-12-31']) : val(),
      last_recalled: rnd() < 0.6 ? null : val(),
      links: Array.from({ length: Math.floor(rnd() * 4) }, val),
      body: rnd() < 0.2 ? pick(HARD) : `${str()}\n\n${str()}${rnd() < 0.3 ? '\n---\nmore' : ''}${rnd() < 0.3 ? '  \n\n' : ''}`,
    };
    if (rnd() < 0.3) fact.keywords = Array.from({ length: 1 + Math.floor(rnd() * 3) }, str);
    if (rnd() < 0.2) fact.outcome = rnd() < 0.7 ? pick(['error', 'success']) : val();
    if (rnd() < 0.2) fact.status = rnd() < 0.7 ? pick(['active', 'done']) : val();
    if (rnd() < 0.35) {
      const keys = [...new Set(Array.from({ length: 1 + Math.floor(rnd() * 3) }, () => pick(KEYS)))];
      fact.extra = keys.map((k) => [k, rnd() < 0.25 ? Array.from({ length: Math.floor(rnd() * 3) }, val) : val()]);
    }
    facts.push(fact);
  }
  return facts;
}

/** Hand-written frontmatters: the shapes a human types and the emitter never does. */
function fuzzTexts(n) {
  const rnd = mulberry32(FUZZ_SEED + 1);
  const pick = (xs) => xs[Math.floor(rnd() * xs.length)];
  const sq = (s) => `'${s.replace(/'/g, "''")}'`;
  const dq = (s) =>
    `"${[...s]
      .map((c) => {
        const cp = c.codePointAt(0);
        if (c === '\\' || c === '"') return `\\${c}`;
        if (c === '\n') return '\\n';
        if (c === '\t') return pick(['\\t', '\t']);
        if (cp < 0x20 || cp === 0x7f) return `\\x${cp.toString(16).padStart(2, '0')}`;
        if (cp > 0xffff && rnd() < 0.5) return `\\U${cp.toString(16).padStart(8, '0')}`;
        if (cp > 0x7f && rnd() < 0.3) return `\\u${cp.toString(16).padStart(4, '0')}`;
        return c;
      })
      .join('')}"`;
  const scalar = () => {
    const r = rnd();
    if (r < 0.3) return pick(TYPED);
    if (r < 0.5) return sq(pick(HARD));
    if (r < 0.7) return dq(pick(HARD));
    if (r < 0.75) return pick(['"\\ud800"', '"\\ud83d\\ude00"', '"\\x41\\u00e9\\U0001F414"', "''", '""']);
    return pick(['plain words here', 'a plain: value', 'trailing #not-a-comment', 'x # a comment', pick(HARD)]);
  };
  const block = () =>
    `${pick(['|', '>', '|-', '>-', '|+', '>+', '|2', '>1-'])}\n${Array.from(
      { length: 1 + Math.floor(rnd() * 3) },
      () => `  ${pick(['line one', 'line  two', '', '  indented more', 'ภาษาไทย', 'a: b', '# not a comment'])}`,
    ).join('\n')}`;
  const flow = () => `[${Array.from({ length: Math.floor(rnd() * 4) }, scalar).join(pick([', ', ',']))}]`;
  const seq = () =>
    `\n${Array.from({ length: 1 + Math.floor(rnd() * 3) }, () => `${rnd() < 0.15 ? '\n' : ''}- ${scalar()}`).join('\n')}`;
  const nested = () =>
    `\n${Array.from(
      { length: 1 + Math.floor(rnd() * 3) },
      () => `  ${pick(['type', 'loop', 'status', 'source', 'n'])}: ${pick(['project', 'error', 'done', 'archived', '7', "'x'"])}`,
    )
      .filter((l, i, a) => a.findIndex((m) => m.split(':')[0] === l.split(':')[0]) === i)
      .join('\n')}`;
  const value = (key) => {
    const r = rnd();
    if (key === 'links' || key === 'keywords') return r < 0.4 ? seq() : r < 0.7 ? ` ${flow()}` : r < 0.85 ? ' []' : ` ${scalar()}`;
    if (key === 'metadata') return r < 0.8 ? nested() : ` ${scalar()}`;
    if (r < 0.12) return ` ${block()}`;
    if (r < 0.16) return '';
    return ` ${scalar()}${rnd() < 0.1 ? ' # trailing comment' : ''}`;
  };
  const texts = [];
  for (let i = 0; i < n; i += 1) {
    const keys = ['name', 'description', 'type'];
    for (const k of ['created', 'last_recalled', 'links', 'keywords', 'outcome', 'status', 'metadata', pick(KEYS)]) {
      if (rnd() < 0.45 && !keys.includes(k)) keys.push(k);
    }
    if (rnd() < 0.1) keys.splice(Math.floor(rnd() * 3), 1); // a required key missing
    if (rnd() < 0.3) keys.sort(() => rnd() - 0.5);
    const lines = keys.map((k) => `${k}:${k === 'name' && rnd() < 0.8 ? ` fuzz-${i}` : value(k)}`);
    if (rnd() < 0.15) lines.splice(Math.floor(rnd() * lines.length), 0, pick(['', '# a comment line', '   ']));
    let text = `---\n${lines.join('\n')}\n---\n\n${pick(['body', 'body\n---\nstill body', '  spaced  \n\n', '', pick(HARD)])}\n`;
    if (rnd() < 0.08) text = text.replace(/\n/g, '\r\n');
    texts.push(text);
  }
  return texts;
}

// ------------------------------------------------------------------------------------ run

export async function run(ctx) {
  const dist = pathToFileURL(join(ctx.runtimeTs, 'dist', '/'));
  const ff = await import(new URL('memory/factfile.js', dist));
  const yaml = await import(new URL('memory/pyyaml.js', dist));
  const store = await import(new URL('memory/store.js', dist));
  const node = nodeArms(ff, yaml, store);

  const bed = join(ctx.scratch, 'ts2py-codec');
  mkdirSync(bed, { recursive: true });
  const pkg = compileCodec(join(bed, 'gen'));
  const cases = [];
  const notes = [];

  for (const src of SOURCES) {
    const sha = createHash('sha256').update(readFileSync(join(repoRoot, src))).digest('hex');
    const stem = src.split('/').pop().replace(/\.ts$/, '');
    cases.push({
      name: `generated/${stem}/source-sha256`,
      kind: 'string',
      expected: `# source-sha256: ${sha}`,
      actual: readFileSync(join(pkg, `${stem}.py`), 'utf8').split('\n')[1] ?? '(no second line)',
    });
  }

  // (b) the fact fuzz first: its formatted text becomes file inputs below.
  const facts = fuzzFacts(FUZZ_FACTS);
  const formatted = ctx.runPython(REF, { generated: join(bed, 'gen'), package: PACKAGE, files: [], facts });
  const fmtGen = [];
  const fmtPy = [];
  const fuzzFiles = [];
  facts.forEach((fact, i) => {
    const id = `fuzz/fact/${i}`;
    const n = node.format(fact);
    const g = formatted.gen.facts[i];
    const p = formatted.py.facts[i];
    if (!same(g, n)) fmtGen.push({ id, node: n, gen: g });
    if (!same(asBit(p), asBit(n))) fmtPy.push({ id, py: p, node: n, fact });
    const text = typeof p === 'string' ? p : typeof n === 'string' ? n : null;
    if (text !== null) fuzzFiles.push({ id, text });
  });
  cases.push(
    { name: 'fuzz/format/gen=node', kind: 'json', expected: [], actual: fmtGen.slice(0, 20) },
    { name: 'fuzz/format/py=node', kind: 'json', expected: [], actual: fmtPy.slice(0, 20) },
  );
  const fmtRefused = facts.filter((_, i) => refused(formatted.py.facts[i]) && refused(node.format(facts[i]))).length;

  fuzzTexts(FUZZ_TEXTS).forEach((text, i) => fuzzFiles.push({ id: `fuzz/text/${i}`, text }));
  const fuzzInputs = fuzzFiles.map((f, i) => {
    const path = join(bed, `fuzz-${i}.md`);
    writeFileSync(path, f.text, 'utf8');
    utimesSync(path, PINNED_MTIME, PINNED_MTIME);
    return { id: f.id, path };
  });
  cases.push({
    name: 'fuzz/headline',
    kind: 'json',
    expected: { seed: 315, facts: 1200, texts: 1500 },
    actual: { seed: FUZZ_SEED, facts: facts.length, texts: fuzzFiles.filter((f) => f.id.startsWith('fuzz/text/')).length },
  });

  // (c) previous releases
  const releaseInputs = [];
  const headline = {};
  for (const version of readdirSync(RELEASES).filter((d) => /^\d+\.\d+\.\d+$/.test(d)).sort()) {
    for (const f of readdirSync(join(RELEASES, version)).filter((f) => f.endsWith('.md')).sort()) {
      headline[version] = (headline[version] ?? 0) + 1;
      const dest = join(bed, `release-${version}-${f}`);
      copyPinned(join(RELEASES, version, f), dest);
      releaseInputs.push({ id: `${version}/${f}`, path: dest });
    }
  }
  cases.push({ name: 'release/headline', kind: 'json', expected: RELEASE_HEADLINE, actual: headline });

  // (a) the real stores on this machine
  const real = realInputs(join(bed, 'real'));

  const all = [...fuzzInputs, ...releaseInputs, ...real.inputs];
  const py = ctx.runPython(REF, { generated: join(bed, 'gen'), package: PACKAGE, files: all.map((x) => x.path), facts: [] });
  const answers = all.map((x, i) => {
    const bytes = readFileSync(x.path);
    x.text = bytes.toString('utf8');
    return {
      node: { parse: node.parse(bytes), rt: node.rt(bytes), rtStore: node.rtStore(x.path) },
      py: py.py.files[i],
      gen: py.gen.files[i],
    };
  });
  const slice = (from, n) => answers.slice(from, from + n);
  // `--dump=<file>`: every input's id and the three arms' answers, for reading a disagreement.
  // Real-store answers carry those files' contents, so point it into scratch, never the repo.
  if (ctx.options.dump) {
    writeFileSync(ctx.options.dump, all.map((x, i) => JSON.stringify({ id: x.id, ...answers[i] })).join('\n'));
  }

  const fuzz = threeWay(fuzzInputs, slice(0, fuzzInputs.length), ff.isTextKey);
  cases.push(...aggregateCases('fuzz', fuzz, 'fuzz', { rulings: true }));
  notes.push(
    `fuzz (seed ${FUZZ_SEED}): ${facts.length} facts formatted by all three, gen!=node ${fmtGen.length}, ` +
      `py!=node ${fmtPy.length}, refused by both ${fmtRefused}; ${fuzzFiles.length - FUZZ_TEXTS} of their texts ` +
      `and ${FUZZ_TEXTS} hand-written frontmatters read back`,
    summarise('fuzz', fuzzInputs.length, fuzz),
  );

  // (c) per file: the three-way, and what EXPECTED.json pins
  const expected = JSON.parse(readFileSync(join(RELEASES, 'EXPECTED.json'), 'utf8'));
  const relAns = slice(fuzzInputs.length, releaseInputs.length);
  releaseInputs.forEach((input, i) => {
    const { node: n, py: p, gen: g } = relAns[i];
    const at = `release/${input.id}`;
    cases.push(
      { name: `${at}/parse/gen=node`, kind: 'string', expected: JSON.stringify(n.parse), actual: JSON.stringify(g.parse) },
      { name: `${at}/rt/gen=node`, kind: 'string', expected: JSON.stringify(n.rt), actual: JSON.stringify(g.rt) },
      { name: `${at}/parse/py=node`, kind: 'json', expected: p.parse, actual: n.parse },
      { name: `${at}/rt-store/py=node`, kind: 'string', expected: JSON.stringify(p.rt), actual: JSON.stringify(n.rtStore) },
      {
        name: `${at}/expected`,
        kind: 'json',
        expected: expected[input.id] ?? '(no entry in EXPECTED.json)',
        actual: { parse: g.parse, rt: g.rt, rtStore: p.rt },
      },
    );
  });
  const rel = threeWay(releaseInputs, relAns, ff.isTextKey);
  notes.push(summarise('previous releases', releaseInputs.length, rel));
  if (ctx.options['write-expected'] === 'factfile-cases') {
    const fresh = {};
    releaseInputs.forEach((input, i) => {
      fresh[input.id] = { parse: relAns[i].gen.parse, rt: relAns[i].gen.rt, rtStore: relAns[i].py.rt };
    });
    writeFileSync(join(RELEASES, 'EXPECTED.json'), `${JSON.stringify(fresh, null, 2)}\n`);
    notes.push('wrote fixtures/factfile-cases/EXPECTED.json from the generated and runtime-py answers');
  }

  if (real.inputs.length === 0) {
    notes.push(
      `real stores SKIPPED: none of <repo>/.bantamkit/memory, ~/.bantamkit/memory, ~/.claude/projects/*/memory ` +
        `holds a fact file on this machine (${real.looked} directories looked at); class (a) runs only where they exist`,
    );
  } else {
    const r = threeWay(real.inputs, slice(fuzzInputs.length + releaseInputs.length, real.inputs.length), ff.isTextKey);
    // No rulings here: the stores change under the suite, so a class may come and go; it is
    // counted in the note, and anything outside the known classes is still red.
    cases.push(...aggregateCases('real', r, 'real stores', { rulings: false }));
    notes.push(
      `real stores (copied to scratch, read there): ${Object.entries(real.perSource)
        .map(([k, v]) => `${k} ${v}`)
        .join(', ')}`,
      summarise('real stores', real.inputs.length, r),
    );
  }
  return { cases, notes };
}
