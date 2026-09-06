/**
 * recall-gate — roadmap #6's precision gate, Python against Node, over the same store.
 *
 * THE PROPERTY: given the same store on disk and the same `min_ratio`, the two runtimes
 * return the same facts in the same order, refuse the same ratios with the same sentence,
 * and leave the directory in byte-identical states. The gate keeps a fact iff
 *
 *     score(f) >= min_ratio * max(score over the SAME recall)
 *
 * and it ships at `RECALL_MIN_SCORE_RATIO = 0.0`, where it keeps everything. The mechanism
 * landed in J45-6 (runtime-py) and J45-7 (runtime-ts); this suite is what makes the claim
 * "they agree" rerunnable instead of a thing two implementers each observed once.
 *
 * WHY THE LADDER FIXTURE IS SHAPED THE WAY IT IS. Four facts scoring 4, 3, 2 and 1 against
 * one query, so a ratio can be aimed EXACTLY at a fact rather than between two of them. The
 * two at-threshold points are the whole reason the fixture is a ladder of small integers:
 * `0.5 * 4` is 2.0 and `0.25 * 4` is 1.0, both exact in IEEE754 on both sides, so the
 * score-2 and score-1 facts sit ON the floor and are ADMITTED. Those are the only cases
 * that separate `>=` from `>`, and that distinction is live — mutant M1 reddened 7 nodes in
 * `runtime-ts` and 5 in `runtime-py`. A fixture with scores 5 and 3 would put every floor
 * strictly between two facts and could not tell the two comparisons apart at all.
 *
 * AND WHERE A DIFFERENTIAL IS STRUCTURALLY BLIND, THERE IS A LITERAL. Four of the claims
 * here — the value of the constant, the at-threshold admission, the relative-gate property
 * and the refusal sentence — are written twice, once per runtime, and a change applied to
 * BOTH halves leaves the two agreeing. No comparison between them can see that. The
 * `literalCases(...)` blocks at the end of `run()` therefore compare EACH side to a typed
 * constant, which is the only shape a symmetric regression reddens.
 *
 * THE RELATIVE-GATE CASE is the one neither implementer had written down and it is the
 * point of the whole design: a uniformly weak field — three facts all scoring 1 — at
 * `min_ratio = 1.0`, the strictest value the range permits, returns ALL THREE. The floor is
 * a fraction of the best score IN THAT RECALL, so the top hit always equals the max and
 * clears every ratio. The gate narrows an injection; it can never suppress one. A future
 * "improvement" that quietly made the cut absolute would empty that recall, and this is the
 * case that says so.
 *
 * WHAT IS DELIBERATELY NOT PINNED. Whether the filter sits before or after the top-`k`
 * slice. Mutant M7 survived on BOTH runtimes and both implementers proved it equivalent:
 * the floor is a fraction of the max, so the survivors are always a prefix of the
 * score-sorted list, and taking the first `k` of that prefix is the same list as filtering
 * the first `k`. A case claiming to separate them would be vacuous by construction, so
 * every ladder scenario asks for `k = 10` — more than the fixture holds — and the gate is
 * the only thing that can shorten the answer.
 *
 * NO REAL STORE IS OPENED. Every fixture is built in harness scratch, and the layered
 * scenarios pin `HOME` and `BANTAMKIT_MEMORY_DIR` inside each side's own bed, so the
 * profile layer is the harness's and never the operator's.
 */
import {
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  readlinkSync,
  writeFileSync,
} from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'recall-gate';
export const summary = 'the min-score ratio: which facts survive it, and which ratios it refuses';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'recall_gate_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

const TODAY = '2026-08-23';

/** The query every ladder scenario asks. Four tokens, so the ladder's scores are 4/3/2/1. */
const LADDER_QUERY = 'alpha bravo charlie delta';

/**
 * Take the side's own bed out of a message before comparing.
 *
 * `memory store is unreadable: <path>` prints the root, and the two sides run in `py/` and
 * `node/`, so an un-scrubbed comparison would fail on the one difference the harness itself
 * created. The path is not dropped: it becomes a marker, so a message naming the WRONG path
 * still differs. Both spellings, because `str(OSError)` prints through `%r` and doubles a
 * backslash on Windows.
 */
function scrubPath(text, root) {
  const escaped = root.split('\\').join('\\\\');
  return text.split(root).join('<ROOT>').split(escaped).join('<ROOT>');
}

function scrub(results, root) {
  const walk = (value) => {
    if (Array.isArray(value)) return value.map(walk);
    if (value && typeof value === 'object') {
      if (value.error) {
        return {
          error: { type: value.error.type, message: b64(scrubPath(unb64(value.error.message), root)) },
        };
      }
      return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, walk(v)]));
    }
    return value;
  };
  return walk(results);
}

// -------------------------------------------------------------------------- fixtures

/** The frontmatter a Python-written fact carries, spelled out so a fixture is bytes. */
const factFile = (n, description) =>
  `---\nname: ${n}\ndescription: ${description}\ntype: project\ncreated: '2026-08-01'\n` +
  `last_recalled: null\nlinks: []\n---\n\nb\n`;

/** A store at `path`, as bytes rather than as a call into the code under test. */
function storeSpec(path, facts = {}) {
  const spec = { dirs: [`${path}/facts`, `${path}/archive`], files: {} };
  for (const [n, description] of Object.entries(facts)) {
    spec.files[`${path}/facts/${n}.md`] = factFile(n, description);
  }
  return spec;
}

function merge(...parts) {
  const out = { dirs: [], files: {} };
  for (const part of parts) {
    out.dirs.push(...(part.dirs ?? []));
    Object.assign(out.files, part.files ?? {});
  }
  return out;
}

/**
 * The 4/3/2/1 ladder. `score = |tokens(name + " " + description) INTERSECT tokens(query)|`,
 * and `_tokens` is `[a-z0-9]+` over the lowercased text — so the NAME is scored too, and
 * none of these names shares a token with the query.
 */
const LADDER = storeSpec('store', {
  four: 'alpha bravo charlie delta',
  three: 'alpha bravo charlie zulu',
  two: 'alpha bravo yankee zulu',
  one: 'alpha xray yankee zulu',
});

/**
 * A uniformly weak field: three facts, each sharing exactly ONE token with the query.
 *
 * Every score is 1, so the best score is 1 and the floor at `min_ratio = 1.0` is 1. All
 * three clear it. This is the shape that distinguishes a RELATIVE gate from an absolute
 * one, and an absolute cut of anything above 1 would return nothing at all.
 */
const UNIFORM = storeSpec('store', {
  'weak-a': 'alpha zulu yankee xray',
  'weak-b': 'alpha zulu yankee xray',
  'weak-c': 'alpha zulu yankee xray',
});

/** Materialise one spec at `root`. */
function materialise(root, spec) {
  mkdirSync(root, { recursive: true });
  for (const dir of spec.dirs ?? []) mkdirSync(join(root, dir), { recursive: true });
  for (const [path, content] of Object.entries(spec.files ?? {})) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), Buffer.from(content, 'utf8'));
  }
}

/**
 * Every path under `root`, with what it is and what it holds.
 *
 * The tree is in the comparison because a recall STAMPS what it returns: at
 * `min_ratio = 0.5` the score-1 fact is gated out and its `last_recalled` must stay `null`,
 * and at every refused ratio nothing at all may be written. "It answered correctly" and "it
 * touched the right files" are separate claims and this is where the second one is checked.
 */
function manifest(root) {
  const lines = [];
  const walk = (dir) => {
    let entries;
    try {
      entries = readdirSync(dir);
    } catch (e) {
      lines.push(`${relative(root, dir) || '.'}\tUNREADABLE\t${e.code}`);
      return;
    }
    for (const entry of entries.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))) {
      const full = join(dir, entry);
      const rel = relative(root, full);
      const st = lstatSync(full);
      if (st.isSymbolicLink()) lines.push(`${rel}\tlink\t${scrubPath(readlinkSync(full), root)}`);
      else if (st.isDirectory()) {
        lines.push(`${rel}\tdir`);
        walk(full);
      } else {
        const bytes = readFileSync(full);
        lines.push(`${rel}\tfile\t${bytes.length}\t${scrubPath(bytes.toString('utf8'), root)}`);
      }
    }
  };
  walk(root);
  return `${lines.join('\n')}\n`;
}

// ------------------------------------------------------------------------ call shapes

/**
 * One recall, with the ratio carried as a SPEC and not as a number.
 *
 * `'nan'`, `'inf'` and `'-inf'` have no JSON literal — sent as data they would arrive as
 * `null` and test a different refusal — so each side constructs the value itself.
 * `'default'` means "pass no fourth argument", which is how the shipped default is measured
 * without this file restating what it is.
 */
const call = (ratio, { query = LADDER_QUERY, k = 10, stamp = true } = {}) => ({
  query: b64(query),
  ratio,
  k,
  stamp,
});

// ------------------------------------------------------------------------ node side

/** The Node side of one `store` request, shaped exactly like `recall_gate_ref.py`'s answer. */
function runNodeStore(store, request) {
  const encode = (e) => ({
    error: { type: e?.name ?? 'Error', message: b64(String(e?.message ?? e)) },
  });
  let s;
  try {
    s = new store.MemoryStore(request.root, {
      today: () => request.today,
      create: request.create ?? true,
      ...(request.k === null ? {} : { k: request.k }),
    });
  } catch (e) {
    return { results: [encode(e)] };
  }
  const results = [];
  for (const c of request.calls) {
    try {
      const query = unb64(c.query);
      // The three-argument form is the DEFAULT arm and it must stay three arguments:
      // passing `RECALL_MIN_SCORE_RATIO` explicitly here would compare the constant to
      // itself and say nothing about what `recall` does when nobody names a ratio.
      const facts =
        c.ratio === 'default'
          ? s.recall(query, c.k, c.stamp)
          : s.recall(query, c.k, c.stamp, ratioOf(c.ratio));
      results.push(facts.map((f) => b64(store.pyText(f.name))));
    } catch (e) {
      results.push(encode(e));
    }
  }
  return { results };
}

/** The spec, as the number it names — built HERE, because JSON cannot carry these three. */
function ratioOf(spec) {
  if (typeof spec !== 'string') return spec;
  if (spec === 'nan') return Number.NaN;
  if (spec === 'inf') return Number.POSITIVE_INFINITY;
  if (spec === '-inf') return Number.NEGATIVE_INFINITY;
  throw new Error(`unknown ratio spec ${JSON.stringify(spec)}`);
}

/** The Node side of one `layered` request, with the same env levers the reference gets. */
function runNodeLayered(component, request, env) {
  const before = new Map(Object.keys(env).map((k) => [k, process.env[k]]));
  for (const [k, v] of Object.entries(env)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  const encode = (e) => ({
    error: { type: e?.name ?? 'Error', message: b64(String(e?.message ?? e)) },
  });
  try {
    let mem;
    try {
      mem = component.Memory.layered(request.start, {
        today: () => request.today,
        ...(request.k === null ? {} : { k: request.k }),
      });
    } catch (e) {
      return { results: [encode(e)] };
    }
    const results = [];
    for (const c of request.calls) {
      try {
        const query = unb64(c.query);
        results.push(
          b64(c.ratio === 'default' ? mem.recall(query, c.k) : mem.recall(query, c.k, ratioOf(c.ratio))),
        );
      } catch (e) {
        results.push(encode(e));
      }
    }
    return { results };
  } finally {
    for (const [k, v] of before) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

// ------------------------------------------------------------------------- scenarios

/**
 * Each entry is one call list against one fixture.
 *
 * `create: false` throughout: the fixture is already on disk as bytes, and a `create: true`
 * store would make directories the fixture did not describe — the same trap J45-7 named for
 * the Node constructor.
 */
function storeScenarios() {
  return [
    ['the shipped default gates nothing — and it is not named here', LADDER, {}, [call('default')]],
    ['0.0 keeps every fact the ungated recall would have returned', LADDER, {}, [call(0.0)]],
    [
      'AT THRESHOLD 0.25: 0.25*4 is exactly 1.0 and the score-1 fact is ADMITTED',
      LADDER,
      {},
      [call(0.25)],
    ],
    ['0.4 lands between the score-2 and score-1 facts', LADDER, {}, [call(0.4)]],
    [
      'AT THRESHOLD 0.5: 0.5*4 is exactly 2.0 and the score-2 fact is ADMITTED',
      LADDER,
      {},
      [call(0.5)],
    ],
    ['0.6 lands between the score-3 and score-2 facts', LADDER, {}, [call(0.6)]],
    ['1.0 keeps only the top hit', LADDER, {}, [call(1.0)]],
    [
      'THE RELATIVE GATE: a uniformly weak field at 1.0 returns ALL of it',
      UNIFORM,
      {},
      [call(1.0, { query: 'alpha' })],
    ],
    [
      'the six ratios outside [0.0, 1.0] — three of which JSON cannot spell',
      LADDER,
      {},
      [call(-0.1), call(1.1), call(2.0), call('nan'), call('inf'), call('-inf')],
    ],
    // Several ratios in ONE call list, so the gate is exercised against a store whose facts
    // have already been stamped by an earlier call in the same process. A port that filtered
    // on a cached score, or that let `_stamp` change what the next recall scores, differs
    // here and nowhere else in this suite.
    //
    // AND NOT ONE OF THEM ADMITS THE WHOLE LADDER, which is the difference between a tree
    // case that means something and one that cannot fail. `0.0` or `0.25` anywhere in this
    // list would stamp all four facts, and the end state would then be the same whatever the
    // later calls did — the first draft had exactly that and its tree case survived every
    // mutant in the register. Descending 1.0 -> 0.6 -> 0.5 leaves the score-1 fact
    // `last_recalled: null`, so the tree still carries a claim: `>` instead of `>=` loses
    // `two`'s stamp, and an absolute floor gains `one`'s.
    [
      'three ratios walked in one process, none of them admitting the whole ladder',
      LADDER,
      {},
      [call(1.0), call(0.6), call(0.5)],
    ],
  ];
}

/**
 * THE RANGE CHECK RUNS BEFORE ANY FILE IS READ, and this is the fixture that can tell.
 *
 * `facts` is a FILE, not a directory, so listing it raises on both platforms and both
 * runtimes — `memory store is unreadable: <root>`. The scenario asks TWICE: once with a
 * ratio outside the range, which must answer the RANGE sentence, and once with a legal
 * ratio, which must answer the UNREADABLE one. The second call is what stops the first from
 * being vacuous: without it, "it said the range is wrong" would be consistent with a store
 * that was perfectly readable.
 *
 * THIS SCENARIO GETS NO TREE CASE, and that is a deletion rather than an omission. Both
 * calls pass `stamp: false` and the store cannot be listed at all, so nothing this suite can
 * mutate could make either runtime write a byte here — the tree case was in the first draft,
 * survived all twenty-two mutants in the register, and a case that cannot fail is worse than
 * no case. The "it refused before touching disk" claim is not lost: the six-ratio scenario
 * above makes it over a READABLE store, where deleting the range check DOES let a negative
 * ratio through to stamp all four facts (mutant py-M4, tree red).
 */
const UNREADABLE = {
  dirs: ['store/archive'],
  files: { 'store/facts': 'this is a file where a directory belongs\n' },
};

// ------------------------------------------------------------------------- literals

/**
 * Compare EACH side to a typed constant, rather than to the other side.
 *
 * The constant's value, the at-threshold admission, the relative-gate property and the
 * refusal sentence are each written twice — once per runtime — so a change applied to both
 * halves leaves the two runtimes agreeing and every differential above green. A literal is
 * the only shape that reddens for a symmetric regression, and `docs/conformance.md` records
 * why this suite carries four of them.
 */
function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `${label} — python`, kind, expected, actual: pySide },
    { name: `${label} — node`, kind, expected, actual: nodeSide },
  ];
}

// ------------------------------------------------------------------------------- run

export async function run(ctx) {
  const store = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'store.js')).href);
  const component = await import(
    pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'component.js')).href
  );
  const cases = [];
  const notes = [];

  // ------------------------------------------------- the constant, as bits and as a sentence
  //
  // NOT through a serialiser. `json.dumps(0.0)` writes `0.0` and `JSON.stringify(0)` writes
  // `0`; that is a difference between two serialisers, not between two products, and a
  // `ruling:` row here would pin a serialiser artefact into `docs/porting.md` as though it
  // were a deliberate divergence. J45-7's first cross-runtime probe failed on exactly this.
  // 16 hex characters of IEEE754 is the same number or a real difference.
  const pyConst = ctx.runPython(REF, { op: 'constant' });
  const ndBits = (() => {
    const buf = Buffer.alloc(8);
    buf.writeDoubleBE(store.RECALL_MIN_SCORE_RATIO);
    return buf.toString('hex');
  })();
  const ndSentence = (() => {
    // Read out of the exception the PRODUCT raises, not out of a constant this file names,
    // so a port that kept the constant right while raising something else still differs.
    const probe = new store.MemoryStore(join(ctx.scratch, 'sentence-probe'), { create: true });
    try {
      probe.recall('q', 3, false, 2.0);
    } catch (e) {
      return String(e?.message ?? e);
    }
    return '<no refusal>';
  })();
  cases.push({
    name: 'RECALL_MIN_SCORE_RATIO — the IEEE754 bits, never the rendered decimal',
    kind: 'string',
    expected: pyConst.bits,
    actual: ndBits,
  });
  cases.push({
    name: 'the refusal sentence, as the product raises it',
    kind: 'string',
    expected: unb64(pyConst.sentence),
    actual: ndSentence,
  });
  notes.push(`RECALL_MIN_SCORE_RATIO bits: python ${pyConst.bits} / node ${ndBits}`);

  // ------------------------------------------------------------------ the store scenarios
  let n = 0;
  const answers = {};
  for (const [label, spec, options, calls] of [
    ...storeScenarios(),
    [
      'the range check runs BEFORE any file is read: an unreadable store still says "ratio"',
      UNREADABLE,
      { noTree: true },
      [call(2.0, { stamp: false }), call(0.0, { stamp: false })],
    ],
  ]) {
    n += 1;
    const bed = join(ctx.scratch, `g${String(n).padStart(2, '0')}`);
    const roots = {};
    for (const side of ['py', 'node']) {
      roots[side] = join(bed, side);
      materialise(roots[side], spec);
    }
    const request = (root) => ({
      op: 'store',
      root: join(root, 'store'),
      today: TODAY,
      k: options.k ?? null,
      create: false,
      calls,
    });
    const py = ctx.runPython(REF, request(roots.py));
    const nd = runNodeStore(store, request(roots.node));
    answers[label] = { py: scrub(py.results, roots.py), node: scrub(nd.results, roots.node) };

    cases.push({
      name: `${label} — answer`,
      kind: 'json',
      expected: answers[label].py,
      actual: answers[label].node,
    });
    // `noTree` is not a shortcut: it marks the one scenario whose directory NO mutation of
    // this rule can change — see the comment on `UNREADABLE`.
    if (!options.noTree) {
      cases.push({
        name: `${label} — tree`,
        kind: 'bytes',
        expected: manifest(roots.py),
        actual: manifest(roots.node),
      });
    }
  }
  notes.push(`${n} store scenarios compared, answer and — for all but the unreadable one — whole tree`);

  // ---------------------------------------------------------------- the layered scenarios
  //
  // `Memory.layered` is the registration production runs, and it is the ONLY place the
  // per-layer property exists: the ratio rides down to every layer unchanged, so each store
  // is gated against ITS OWN top hit and never against another layer's. The fixture is
  // asymmetric on purpose — the project layer holds a score-4 fact AND a score-1 fact, the
  // profile layer holds only a score-1 fact — so at `min_ratio = 1.0` the project's weak
  // fact is gated out while the profile's identical-scoring one survives. A gate applied
  // across layers, or a component that stopped forwarding the ratio, differs here.
  const layeredScenarios = [
    [
      'layered: the gate is applied per layer, against each layer\'s own top hit',
      [call(1.0, { query: LADDER_QUERY, k: 5 })],
    ],
    ['layered: the default still gates nothing across three layers', [call('default', { k: 5 })]],
    [
      'layered: a ratio outside the range surfaces out of the writable project layer',
      [call('nan', { k: 5 })],
    ],
  ];
  const layeredSpec = merge(
    storeSpec('project/.bantamkit/memory', {
      'top-fact': 'alpha bravo charlie delta',
      'weak-project': 'alpha zulu yankee xray',
    }),
    storeSpec('home/.bantamkit/memory', { 'weak-profile': 'alpha zulu yankee xray' }),
  );
  let m = 0;
  const layeredAnswers = {};
  for (const [label, calls] of layeredScenarios) {
    m += 1;
    const bed = join(ctx.scratch, `l${String(m).padStart(2, '0')}`);
    const roots = {};
    for (const side of ['py', 'node']) {
      roots[side] = join(bed, side);
      materialise(roots[side], layeredSpec);
    }
    const envFor = (root) => ({
      HOME: join(root, 'home'),
      USERPROFILE: join(root, 'home'),
      BANTAMKIT_MEMORY_DIR: join(root, 'project', '.bantamkit', 'memory'),
    });
    const request = (root) => ({
      op: 'layered',
      start: join(root, 'project'),
      today: TODAY,
      k: null,
      calls,
    });
    const py = ctx.runPython(REF, request(roots.py), envFor(roots.py));
    const nd = runNodeLayered(component, request(roots.node), envFor(roots.node));
    const answer = (side, results) =>
      results.map((r) =>
        r && typeof r === 'object' && r.error
          ? `${r.error.type}: ${scrubPath(unb64(r.error.message), roots[side])}`
          : scrubPath(unb64(r), roots[side]),
      );
    layeredAnswers[label] = { py: answer('py', py.results), node: answer('node', nd.results) };
    cases.push({
      name: `${label} — reply`,
      kind: 'string',
      expected: layeredAnswers[label].py.join('\n----\n'),
      actual: layeredAnswers[label].node.join('\n----\n'),
    });
    cases.push({
      name: `${label} — trees`,
      kind: 'bytes',
      expected: manifest(roots.py),
      actual: manifest(roots.node),
    });
  }
  notes.push(`${m} layered scenarios compared through Memory.layered, reply and whole tree`);

  // ------------------------------------------------------------------------- the literals
  const names = (side, label, i = 0) => answers[label][side][i].map(unb64);

  cases.push(
    ...literalCases(pyConst.bits, ndBits, 'LITERAL: the shipped ratio is 0.0', '0000000000000000', 'string'),
  );
  cases.push(
    ...literalCases(
      unb64(pyConst.sentence),
      ndSentence,
      'LITERAL: the refusal sentence, with no value interpolated',
      'recall min-score ratio must be between 0.0 and 1.0',
      'string',
    ),
  );
  cases.push(
    ...literalCases(
      names('py', 'AT THRESHOLD 0.5: 0.5*4 is exactly 2.0 and the score-2 fact is ADMITTED'),
      names('node', 'AT THRESHOLD 0.5: 0.5*4 is exactly 2.0 and the score-2 fact is ADMITTED'),
      'LITERAL: at 0.5 the score-2 fact is admitted (>= and not >)',
      ['four', 'three', 'two'],
    ),
  );
  cases.push(
    ...literalCases(
      names('py', 'THE RELATIVE GATE: a uniformly weak field at 1.0 returns ALL of it'),
      names('node', 'THE RELATIVE GATE: a uniformly weak field at 1.0 returns ALL of it'),
      'LITERAL: the gate is relative, so 1.0 over a uniform field suppresses nothing',
      ['weak-a', 'weak-b', 'weak-c'],
    ),
  );

  return { cases, notes };
}
