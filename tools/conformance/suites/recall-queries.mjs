/**
 * recall-queries — #207 amendment 3, likely-prompt queries and the session head, Python
 * against Node over the same beds.
 *
 * THE PROPERTY (spec `docs/superpowers/specs/2026-10-18-recall-queries-design.md`, "Parity
 * and conformance"): given the same stores and the same sidecars on disk, the two runtimes
 * rank, inject, read, write, refuse and report alike. Concretely:
 *
 *   - RANKING. A mixed Thai/English pool over three layers (project, profile, native; a name
 *     shadowed between project and native), sidecars on two of them, ranks and injects the
 *     same names, and every `QueryScorer.column` call is the same column as IEEE-754 bits.
 *     A fact with no queries scores exactly its BM25F; a Thai-only query scores 0; a fact
 *     whose only hit is its queries is injected; a pool with no sidecar is B, byte for byte;
 *     the files path and the index path agree.
 *   - HEAD. `_previous_prompt` / `previousPrompt` take the same prompt out of the same
 *     transcript bytes — sidechain, meta, `<command>`, interrupted, tool_result-only, block
 *     lists, not-JSON lines, the trailing current prompt, the 256 KiB tail's cut line — and
 *     `_head_query` / `headQuery` count CODE POINTS.
 *   - WRITE PATHS. `memory_save` with `queries` over each server's stdio leaves byte-identical
 *     sidecars; a sidecar one runtime wrote ranks the same in the other; the limits and the
 *     `memory_queries` refusals are the spec's sentences (S1-S9), and a refusal leaves the
 *     sidecar byte-unchanged.
 *   - REPORTING. The `bantamkit_status` line (S10/S11) per side, and the served tool roster.
 *
 * AND WHERE A DIFFERENTIAL IS STRUCTURALLY BLIND, THERE IS A LITERAL: every shared constant,
 * the injected names, the zero of a Thai-only query, every sentence. A change made to both
 * runtimes alike leaves every differential green; only a literal sees it
 * (`differential-is-blind-to-symmetric-regression`).
 *
 * The head end to end (the hook processes) and the SessionStart nudge (S12) are in
 * `hooks.mjs`; the sentences' surfaces in `instructions.mjs`.
 *
 * NO REAL HOME IS TOUCHED. Every bed is under the harness scratch; each side's `HOME`,
 * `USERPROFILE`, `BANTAMKIT_INDEX_DIR` and `BANTAMKIT_RETENTION=off` are pinned per call, and
 * the reference refuses to run with a `HOME` outside the scratch.
 */
import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { runNode as runNodeServer } from './wire.mjs';

export const name = 'recall-queries';
export const summary = 'likely-prompt queries and the session head: ranking, sidecar, limits, memory_queries, status (#207)';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'queries_ref.py');
const WIRE_REF = join(here, 'ref', 'wire_ref.py');
const ASSETS = join(repoRoot, 'assets');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');
const bits = (x) => {
  const v = new DataView(new ArrayBuffer(8));
  v.setFloat64(0, x);
  return v.getBigUint64(0).toString(16).padStart(16, '0');
};
const cps = (s) => [...s].length;

/** The shared-constants table of the plan, typed here once: the literal both sides answer to. */
const CONSTANTS = {
  QUERY_WEIGHT: bits(1.0),
  HEAD_SHORT: 80,
  HEAD_CUT: 500,
  TAIL_BYTES: 262144,
  MAX_QUERIES: 8,
  MAX_QUERY_CHARS: 200,
  LIST_LIMIT: 10,
  BODY_EXCERPT: 600,
  SIDECAR_VERSION: 1,
  QUERIES_DIR: 'queries',
};

/** The spec's sentences, typed here (S1-S11), never read from either runtime. */
const S1 = (n) => `queries: at most 8 per fact, got ${n}`;
const S2 = (i, n) => `queries: each at most 200 characters; query ${i} has ${n}`;
const S3 = 'queries must be a list of strings';
const S4 = ' (queries not written: the sidecar could not be saved)';
const S5 = (i) => `facts[${i}] must be an object with a name and queries`;
const S6 = (i, layer, labels) => `facts[${i}]: no layer named '${layer}'; layers are ${labels}`;
const S7 = (i, n, where) => `facts[${i}]: no fact named '${n}' in ${where}`;
const S9 = 'the sidecar could not be saved';
const S10 = (n, m) => `queries: ${n} of ${m} facts`;
const S11 = 'queries: unavailable';

function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `${label} — python`, kind, expected, actual: pySide },
    { name: `${label} — node`, kind, expected, actual: nodeSide },
  ];
}

// --------------------------------------------------------------------------------- beds

/** A bantamkit fact file, as bytes: what a Python-written fact carries. */
const factFile = (n, description, type = 'project', body = 'b') =>
  `---\nname: ${n}\ndescription: ${description}\ntype: ${type}\ncreated: '2026-10-01'\n` +
  `last_recalled: null\nlinks: []\n---\n\n${body}\n`;

/** A Claude Code auto-memory fact (the native layer's format). */
const nativeFile = (n, description, type = 'project') =>
  `---\nname: ${n}\ndescription: ${description}\ntype: ${type}\n---\n\nnative body\n`;

function write(path, data) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, data);
}

/**
 * The sidecar path, derived HERE from the spec's rule (`sha16(realpath(store root))`) rather
 * than through either runtime's `sidecarPath`: a key both sides computed wrongly alike would
 * otherwise be found by both and pass.
 */
const sidecarOf = (home, root) =>
  join(home, '.bantamkit', 'queries', `${createHash('sha256').update(realpathSync.native(root), 'utf8').digest('hex').slice(0, 16)}.json`);

const sidecarDoc = (entries) =>
  JSON.stringify({ v: 1, facts: Object.fromEntries(Object.entries(entries).map(([n, qs]) => [n, { queries: qs, sha: '' }])) });

/** The mixed pool. Names and texts are synthetic; nothing here is an eval prompt. */
const PROJECT = {
  'deploy-runbook': ['how the staging deploy is rolled out', 'project'],
  'release-lessons': ['ขั้นตอนปล่อยเวอร์ชัน release checklist', 'feedback'],
  'hook-latency': ['UserPromptSubmit timing measured on Node', 'reference'],
  'shared-name': ['the shadowed fact as the project holds it', 'project'],
  'gate-rule': ['conformance gate is zero failures', 'project'],
  'script-only': ['a document written in one script', 'reference'],
};
const PROFILE = {
  'user-language': ['the user writes Thai and English mixed', 'user'],
  'windows-eperm': ['npx install fails on Windows with EPERM', 'reference'],
};
const NATIVE = {
  'shared-name': ['the shadowed copy the host exported', 'project'],
  'native-only': ['auto memory note about the budget', 'project'],
};
const PROJECT_QUERIES = {
  'deploy-runbook': ['วิธี deploy ขึ้น staging', 'how do I deploy to staging', 'rollout steps please'],
  'release-lessons': ['ปล่อยเวอร์ชันยังไง', 'how to cut a release', 'publish the npm package'],
  'hook-latency': ['ทำไม hook ช้า', 'why is the prompt hook slow', 'latency numbers'],
  'script-only': ['ภาษาไทยล้วนไม่มีอังกฤษ'],
  'gone-fact': ['an orphaned entry for a fact nobody holds'],
};
const NATIVE_QUERIES = {
  'native-only': ['token budget for memory', 'context window cost'],
  'shared-name': ['shadowed copy query deploy'],
};

/** The prompts. Thai and English, short and long; a query-only hit; a Thai-only query. */
const PROMPTS = [
  { prompt: 'how do I deploy', head: null },
  { prompt: 'why so slow', head: null }, // no BM25F term: only hook-latency's queries hit
  { prompt: 'ปล่อยเวอร์ชันยังไง release', head: null },
  { prompt: 'context window cost', head: null },
  { prompt: 'ภาษาไทยล้วนไม่มีอังกฤษ', head: null }, // only script-only's Thai query holds it
  { prompt: 'and then?', head: 'and then?\nhow the staging deploy is rolled out' },
  { prompt: 'Windows EPERM npm publish release', head: null },
];

/** The beds: one root per scenario, both sides reading the same store paths. */
function mixedBed(root, { sidecars = true, broken = false, orphanOnly = false } = {}) {
  rmSync(root, { recursive: true, force: true });
  const project = join(root, 'project');
  const profile = join(root, 'profile');
  const native = join(root, 'native');
  for (const [n, [d, t]] of Object.entries(PROJECT)) write(join(project, 'facts', `${n}.md`), factFile(n, d, t));
  for (const [n, [d, t]] of Object.entries(PROFILE)) write(join(profile, 'facts', `${n}.md`), factFile(n, d, t));
  for (const [n, [d, t]] of Object.entries(NATIVE)) write(join(native, `${n}.md`), nativeFile(n, d, t));
  write(join(native, 'MEMORY.md'), '# memory\n');
  mkdirSync(join(project, 'archive'), { recursive: true });
  mkdirSync(join(profile, 'archive'), { recursive: true });
  if (broken) {
    // An unparseable fact file in each bantamkit store: the index cannot vouch for that store,
    // so both runtimes answer from the FILES (`_indexed` / `indexed` return null).
    write(join(project, 'facts', 'zz-broken.md'), 'not a fact at all\n');
    write(join(profile, 'facts', 'zz-broken.md'), 'not a fact at all\n');
  }
  const homes = {};
  for (const side of ['py', 'node']) {
    const home = join(root, `home-${side}`);
    mkdirSync(home, { recursive: true });
    if (sidecars) {
      write(sidecarOf(home, project), sidecarDoc(orphanOnly ? { 'gone-fact': ['an orphaned entry'] } : PROJECT_QUERIES));
      if (!orphanOnly) write(sidecarOf(home, native), sidecarDoc(NATIVE_QUERIES));
    }
    homes[side] = home;
  }
  return { root, project, profile, native, homes };
}

// --------------------------------------------------------------------------- the sides

function sideEnv(root, side, home) {
  return {
    HOME: home,
    USERPROFILE: home,
    BANTAMKIT_INDEX_DIR: join(root, `idx-${side}`),
    BANTAMKIT_RETENTION: 'off',
    BANTAMKIT_MEMORY_DIR: undefined,
  };
}

function withEnv(env, fn) {
  const before = new Map(Object.keys(env).map((k) => [k, process.env[k]]));
  for (const [k, v] of Object.entries(env)) {
    if (v === undefined || v === null) delete process.env[k];
    else process.env[k] = v;
  }
  try {
    return fn();
  } finally {
    for (const [k, v] of before) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

/** The reference, under `env` (merged over the harness's own; no op here discovers a store). */
function py(ctx, env, payload) {
  const e = Object.fromEntries(Object.entries(env).filter(([, v]) => v !== undefined));
  return ctx.runPython(REF, { scratch: ctx.scratch, ...payload }, e);
}

export async function run(ctx) {
  const dist = (p) => pathToFileURL(join(ctx.runtimeTs, 'dist', p)).href;
  const component = await import(dist('memory/component.js'));
  const retrieval = await import(dist('memory/retrieval.js'));
  const queries = await import(dist('memory/queries.js'));
  const hook = await import(dist('hookadapter.js'));
  const { pyText } = await import(dist('memory/store.js'));

  // The Node half of the ref's `QueryScorer.column` hook: the same three columns, recorded.
  const TRACE = [];
  const column = retrieval.QueryScorer.prototype.column;
  retrieval.QueryScorer.prototype.column = function traced(cols, vecs) {
    const col = column.call(this, cols, vecs);
    if (vecs !== null && col !== null) {
      const a = retrieval.bm25Segments(cols.q, cols.n, cols.total, cols.df, cols.lengths, cols.segs);
      TRACE.push({ vecs: vecs.map((v) => b64(v)), a: a.map(bits), col: col.map(bits) });
    }
    return col;
  };

  const nodeRank = (env, req) =>
    withEnv(env, () => {
      const mem = component.Memory.layeredForEval(req.project, req.profile, 'v2', req.native ?? null);
      return {
        results: req.calls.map((c) => {
          const prompt = unb64(c.prompt);
          const head = c.head === null ? null : unb64(c.head);
          TRACE.length = 0;
          const inject = mem.injectCandidates(prompt, head);
          const ranked = mem.rankAll(prompt, req.depth ?? 10, head);
          const o = mem.recallOutcome(prompt, 3, retrieval.GATE_RATIO, false, false, null, head);
          return {
            inject: inject.map((f) => b64(pyText(f.name))),
            rank: ranked.map((f) => b64(pyText(f.name))),
            reply: b64(o.reply),
            status: o.status,
            trace: [...TRACE],
          };
        }),
      };
    });
  const nodeQueries = (env, req) =>
    withEnv(env, () => {
      const mem = component.Memory.layeredForEval(req.project, req.profile, 'v2', req.native ?? null);
      return {
        out: req.calls.map((c) => {
          if (c.do === 'missing') return mem.queriesMissing();
          if (c.do === 'coverage') return mem.queriesCoverage();
          return mem.queriesWrite(c.facts);
        }),
      };
    });
  const nodeSave = (env, req) =>
    withEnv(env, () => {
      const mem = new component.Memory(req.store);
      return {
        out: req.calls.map((c) => {
          const o = mem.saveOutcome(c.type, c.name, c.description, c.body, null, null, c.queries === null ? null : c.queries.map(unb64));
          return { reply: b64(o.reply), status: o.status };
        }),
      };
    });
  const nodeRead = (paths) => ({ maps: paths.map((p) => [...queries.readSidecar(p)].map(([k, v]) => [b64(k), v.map(b64)])) });

  const cases = [];
  const notes = [];
  const root = join(ctx.scratch, 'recall-queries');
  mkdirSync(root, { recursive: true });
  const calls = PROMPTS.map((p) => ({ prompt: b64(p.prompt), head: p.head === null ? null : b64(p.head) }));
  const names = (list) => list.map(unb64);

  /** Both sides over one bed: the ref under its home, the port in-process under its own. */
  const rankBoth = (bed, extra = {}) => {
    const req = { op: 'rank', project: bed.project, profile: bed.profile, native: bed.native, depth: 10, calls, ...extra };
    const p = py(ctx, sideEnv(bed.root, 'py', bed.homes.py), req);
    const n = nodeRank(sideEnv(bed.root, 'node', bed.homes.node), req);
    return { p, n };
  };

  // ======================================================================= constants (21)
  {
    const p = py(ctx, sideEnv(root, 'py', join(root, 'home-const')), { op: 'constants' });
    const n = {
      QUERY_WEIGHT: bits(retrieval.QUERY_WEIGHT),
      HEAD_SHORT: hook.HEAD_SHORT,
      HEAD_CUT: hook.HEAD_CUT,
      TAIL_BYTES: hook.TAIL_BYTES,
      MAX_QUERIES: queries.MAX_QUERIES,
      MAX_QUERY_CHARS: queries.MAX_QUERY_CHARS,
      LIST_LIMIT: queries.LIST_LIMIT,
      BODY_EXCERPT: queries.BODY_EXCERPT,
      SIDECAR_VERSION: queries.SIDECAR_VERSION,
      QUERIES_DIR: queries.QUERIES_DIR,
    };
    for (const key of Object.keys(CONSTANTS)) {
      cases.push(...literalCases(p[key], n[key], `constants: ${key} is the plan's number`, CONSTANTS[key]));
    }
  }

  // ===================================================================== ranking (1-6)
  const mixed = mixedBed(join(root, 'mixed'));
  const { p: mp, n: mn } = rankBoth(mixed);
  // 1. rank/mixed: the whole answer per prompt, columns included, Python against Node.
  PROMPTS.forEach((pr, i) => {
    const view = (r) => ({ inject: names(r.inject), rank: names(r.rank), reply: unb64(r.reply), status: r.status, trace: r.trace });
    cases.push({
      name: `rank/mixed: ${JSON.stringify(pr.prompt)}${pr.head ? ' (with a head)' : ''} — inject, rankAll(10), recall reply and every QueryScorer column`,
      kind: 'json',
      expected: view(mp.results[i]),
      actual: view(mn.results[i]),
    });
  });
  // The names, typed (measured on the reference at the Task 1 + 2 tree): a symmetric change
  // to the ranker reddens these and no differential.
  const MIXED_INJECT = [
    ['deploy-runbook', 'release-lessons'], // "how" is in release-lessons' queries
    ['hook-latency'],
    ['release-lessons'],
    ['native-only'],
    [],
    ['deploy-runbook', 'user-language', 'gate-rule'], // the head's "the"/"is" reach two more
    ['release-lessons', 'windows-eperm'],
  ];
  PROMPTS.forEach((pr, i) => {
    cases.push(
      ...literalCases(names(mp.results[i].inject), names(mn.results[i].inject), `rank/mixed: LITERAL inject for ${JSON.stringify(pr.prompt)}`, MIXED_INJECT[i]),
    );
  });

  // 2. rank/no-queries-fact: a row with no entry (an empty qdoc) scores exactly its BM25F.
  const emptyRows = (r) => {
    let rows = 0;
    let exact = 0;
    for (const t of r.trace) {
      t.vecs.forEach((v, j) => {
        if (unb64(v) !== '') return;
        rows += 1;
        if (t.col[j] === t.a[j]) exact += 1;
      });
    }
    return { rows, exact };
  };
  const sumRows = (side) =>
    side.results.reduce((acc, r) => {
      const e = emptyRows(r);
      return { rows: acc.rows + e.rows, exact: acc.exact + e.exact };
    }, { rows: 0, exact: 0 });
  {
    const pe = sumRows(mp);
    const ne = sumRows(mn);
    cases.push({ name: 'rank/no-queries-fact: rows with no entry, and how many score exactly their BM25F', kind: 'json', expected: pe, actual: ne });
    // Every one of them, and there are some: a trace that saw no empty row would pass vacuously.
    cases.push(...literalCases(pe.rows > 0 && pe.exact === pe.rows, ne.rows > 0 && ne.exact === ne.rows, 'rank/no-queries-fact: LITERAL every empty-qdoc row is BM25F to the bit (and there is at least one)', true));
  }

  // 3. rank/thai-only-query: a qdoc made only of Thai is blank, and scores 0.
  {
    const THAI = ['ภาษาไทยล้วนไม่มีอังกฤษ'];
    const pq = py(ctx, sideEnv(root, 'py', join(root, 'home-const')), { op: 'qdoc', lists: [THAI.map(b64), ['ok ไทย 日本語 カナ'].map(b64)] });
    const nq = { qdocs: [queries.qdoc(THAI), queries.qdoc(['ok ไทย 日本語 カナ'])].map(b64) };
    cases.push(...literalCases(unb64(pq.qdocs[0]), unb64(nq.qdocs[0]), 'rank/thai-only-query: LITERAL qdoc of a Thai-only query is all spaces', ' '.repeat(cps(THAI[0]))));
    cases.push(...literalCases(unb64(pq.qdocs[1]), unb64(nq.qdocs[1]), 'rank/thai-only-query: LITERAL only the spaced-script tokens survive', `ok${' '.repeat(cps('ok ไทย 日本語 カナ') - 2)}`));
    const prompt = THAI[0];
    const pb = py(ctx, sideEnv(root, 'py', join(root, 'home-const')), { op: 'bm25', prompt: b64(prompt), docs: [pq.qdocs[0]] });
    const nb = retrieval.bm25Scores(prompt, [{ name: '', description: queries.qdoc(THAI), keywords: [] }]).map(bits);
    cases.push(...literalCases(pb.bits, nb, 'rank/thai-only-query: LITERAL its queries score 0.0 against the same Thai prompt', [bits(0)]));
    // And end to end: the Thai prompt (PROMPTS[4]) reaches script-only through nothing else.
    cases.push(...literalCases(names(mp.results[4].inject), names(mn.results[4].inject), 'rank/thai-only-query: LITERAL the Thai-only query injects nothing', []));
  }

  // 4. rank/query-only-hit, and 6. rank/files-equals-index: index path, files path.
  const broken = mixedBed(join(root, 'files'), { broken: true });
  const { p: fp, n: fn } = rankBoth(broken);
  const sp = py(ctx, sideEnv(mixed.root, 'py', mixed.homes.py), { op: 'rank', project: mixed.project, profile: mixed.profile, native: mixed.native, depth: 10, calls, mode: 'snapshot' });
  {
    const QUERY_ONLY = 1; // 'why so slow'
    for (const [label, p, n] of [['index', mp, mn], ['files', fp, fn]]) {
      cases.push(...literalCases(names(p.results[QUERY_ONLY].inject), names(n.results[QUERY_ONLY].inject), `rank/query-only-hit (${label} path): LITERAL a prompt with no BM25F term injects the fact its queries hold`, ['hook-latency']));
    }
    cases.push(...literalCases(names(sp.results[QUERY_ONLY].inject), names(mn.results[QUERY_ONLY].inject), 'rank/query-only-hit (python snapshot, node index): LITERAL', ['hook-latency']));
    PROMPTS.forEach((pr, i) => {
      const v = (r) => ({ inject: names(r.inject), rank: names(r.rank) });
      const four = { 'py-index': v(mp.results[i]), 'py-snapshot': v(sp.results[i]), 'py-files': v(fp.results[i]), 'node-files': v(fn.results[i]) };
      cases.push({
        name: `rank/files-equals-index: ${JSON.stringify(pr.prompt)} — the files path (snapshot, unparseable file) ranks what node's index path ranks`,
        kind: 'json',
        expected: { 'py-index': v(mn.results[i]), 'py-snapshot': v(mn.results[i]), 'py-files': v(mn.results[i]), 'node-files': v(mn.results[i]) },
        actual: four,
      });
    });
  }

  // 5. rank/no-sidecar-is-b: no sidecar at all is B, byte for byte, on each side.
  {
    const bare = mixedBed(join(root, 'bare'), { sidecars: false });
    const { p: bp, n: bn } = rankBoth(bare);
    const off = py(ctx, sideEnv(bare.root, 'py', bare.homes.py), { op: 'rank', project: bare.project, profile: bare.profile, native: bare.native, depth: 10, calls, force_off: true });
    const orphan = mixedBed(join(root, 'orphan'), { orphanOnly: true });
    const { p: op, n: on } = rankBoth(orphan);
    const view = (r) => ({ inject: names(r.inject), rank: names(r.rank), reply: unb64(r.reply), status: r.status });
    PROMPTS.forEach((pr, i) => {
      cases.push({ name: `rank/no-sidecar-is-b: ${JSON.stringify(pr.prompt)} — python with no sidecar against python with the read forced off`, kind: 'json', expected: view(off.results[i]), actual: view(bp.results[i]) });
      cases.push({ name: `rank/no-sidecar-is-b: ${JSON.stringify(pr.prompt)} — no sidecar, python against node`, kind: 'json', expected: view(bp.results[i]), actual: view(bn.results[i]) });
      cases.push({
        name: `rank/no-sidecar-is-b: ${JSON.stringify(pr.prompt)} — a sidecar holding only an orphan is still B, per side`,
        kind: 'json',
        expected: { py: view(bp.results[i]), node: view(bn.results[i]) },
        actual: { py: view(op.results[i]), node: view(on.results[i]) },
      });
    });
    cases.push(...literalCases(bp.results.every((r) => r.trace.length === 0), bn.results.every((r) => r.trace.length === 0), 'rank/no-sidecar-is-b: LITERAL no sidecar never builds a QueryScorer', true));
  }

  // ===================================================================== sidecar (7)
  {
    const dir = join(root, 'sidecar');
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });
    const WHOLE = [
      '',
      'not json',
      '[]',
      '{"v":2,"facts":{}}',
      '{"v":1.0,"facts":{"a":{"queries":["x"]}}}',
      '{"v":true,"facts":{"a":{"queries":["x"]}}}',
      '{"v":1,"facts":[]}',
      '{"facts":{"a":{"queries":["x"]}}}',
      '{"v":"1","facts":{"a":{"queries":["x"]}}}',
    ];
    const paths = WHOLE.map((t, i) => {
      const p = join(dir, `whole-${i}.json`);
      writeFileSync(p, t, 'utf8');
      return p;
    });
    const ff = join(dir, 'ff.json');
    writeFileSync(ff, Buffer.concat([Buffer.from('{"v":1,"facts":{"a":{"queries":["'), Buffer.from([0xff]), Buffer.from('"]}}}')]));
    paths.push(ff, join(dir, 'missing.json'), dir);
    const ENTRIES = join(dir, 'entries.json');
    writeFileSync(
      ENTRIES,
      '{"v":1,"facts":{"a":{"queries":["x",1]},"b":{"queries":[]},"c":"x","d":{"queries":["ok"]},' +
        '"e":{"queries":"str"},"f":{},"ไทย":{"queries":["วิธี deploy","how"],"sha":3},"g":null}}',
      'utf8',
    );
    const pr = py(ctx, sideEnv(dir, 'py', join(root, 'home-const')), { op: 'read_sidecar', paths: [...paths, ENTRIES] });
    const nr = nodeRead([...paths, ENTRIES]);
    cases.push({ name: 'sidecar/malformed: every malformed sidecar and entry reads the same', kind: 'json', expected: pr.maps, actual: nr.maps });
    paths.forEach((p, i) => {
      const what = i < WHOLE.length ? JSON.stringify(WHOLE[i]) : ['a \\xff byte', 'a missing file', 'a directory'][i - WHOLE.length];
      cases.push(...literalCases(pr.maps[i], nr.maps[i], `sidecar/malformed: LITERAL ${what} reads as no sidecar`, []));
    });
    const view = (m) => m.map(([k, v]) => [unb64(k), v.map(unb64)]);
    cases.push(...literalCases(view(pr.maps.at(-1)), view(nr.maps.at(-1)), 'sidecar/malformed: LITERAL a bad entry is skipped one by one', [['d', ['ok']], ['ไทย', ['วิธี deploy', 'how']]]));
  }

  // ======================================================================= head (8-11)
  {
    const dir = join(root, 'head');
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });
    const TAIL = CONSTANTS.TAIL_BYTES;
    const TEXT = (text) => ({ type: 'text', text });
    const rec = (text, { content, ...kw } = {}) => JSON.stringify({ type: 'user', message: { content: content ?? text }, ...kw });
    const file = (n, data) => {
      const p = join(dir, n);
      writeFileSync(p, data);
      return p;
    };
    const rules = file(
      'rules.jsonl',
      [
        rec('first prompt'),
        rec('side', { isSidechain: true }),
        rec('meta', { isMeta: true }),
        rec('also meta', { isMeta: 1 }),
        rec('not side', { isSidechain: 0 }),
        rec('<command-name>/clear</command-name>'),
        rec('  <local-command-stdout>x</local-command-stdout>'),
        rec('[Request interrupted by user]'),
        rec(null, { content: [{ type: 'tool_result', content: 'x' }] }),
        JSON.stringify({ type: 'assistant', message: { content: 'hi' } }),
        rec(null, { content: [TEXT('  second '), TEXT('part')] }),
        'not json',
        '{"type": "user", "message": "a string message"}',
        rec('current'),
      ].join('\n') + '\n',
    );
    // The excluded record LAST before the current prompt: only there does skipping it decide
    // the answer (the rules file above has a main-chain prompt after each of them).
    const sideLast = file('side-last.jsonl', [rec('main prompt'), rec('a sidechain prompt', { isSidechain: true }), rec('current')].join('\n') + '\n');
    const metaLast = file('meta-last.jsonl', [rec('main prompt'), rec('a meta prompt', { isMeta: true }), rec('current')].join('\n') + '\n');
    const falsyLast = file('falsy-last.jsonl', [rec('main prompt'), rec('kept: falsy flags', { isSidechain: 0, isMeta: false }), rec('current')].join('\n') + '\n');
    const repeat = file('repeat.jsonl', [rec('before'), rec('now'), rec(' now ')].join('\n') + '\n');
    const notYet = file('not-yet.jsonl', [rec('now'), rec('before')].join('\n') + '\n');
    const badUtf8 = file('bad-utf8.jsonl', Buffer.concat([Buffer.from([0xff, 0xfe, 0x0a]), Buffer.from(rec('ok') + '\n')]));
    const astral = file('astral.jsonl', rec('🐔 hen prompt ไทย') + '\n');
    // 9. the boundary: a line straddling the tail's first byte; a ghost record that parses
    // after the cut; a file of exactly TAIL_BYTES; one byte over.
    const straddle = rec('x'.repeat(TAIL + 10));
    const cutKept = file('cut-kept.jsonl', `${straddle}\n${rec('kept')}\n`);
    const cutOnly = file('cut-only.jsonl', `${straddle}\n`);
    const ghost = rec('g'.repeat(TAIL - 1 - Buffer.byteLength(rec(''))));
    if (Buffer.byteLength(ghost) !== TAIL - 1) throw new Error('recall-queries: the ghost record is not TAIL_BYTES - 1 long');
    const ghostFile = file('ghost.jsonl', `junk${ghost}\n`);
    const exactLine = rec('e'.repeat(TAIL - 1 - Buffer.byteLength(rec(''))));
    const exact = file('exact.jsonl', `${exactLine}\n`); // exactly TAIL_BYTES: read whole, start 0
    const over = file('over.jsonl', `x${exactLine}\n`); // one byte over: the first line is cut
    const before = file('before.jsonl', `${rec('y'.repeat(100))}\n${'z'.repeat(TAIL - 10)}\n`);
    if (readFileSync(exact).length !== TAIL || readFileSync(over).length !== TAIL + 1) throw new Error('recall-queries: the boundary fixtures are mis-sized');
    const PP = [
      [rules, 'current', 'second \npart'],
      [rules, '  current ', 'second \npart'],
      [rules, 'other', 'current'],
      [sideLast, 'current', 'main prompt'],
      [metaLast, 'current', 'main prompt'],
      [falsyLast, 'current', 'kept: falsy flags'],
      [repeat, 'now', 'before'],
      [notYet, 'now', 'before'],
      [badUtf8, 'x', 'ok'],
      [astral, 'x', '🐔 hen prompt ไทย'],
      [cutKept, 'now', 'kept'],
      [cutOnly, 'now', ''],
      [ghostFile, 'now', ''],
      [exact, 'now', 'e'.repeat(TAIL - 1 - Buffer.byteLength(rec('')))],
      [over, 'now', ''],
      [before, 'now', ''],
      [join(dir, 'missing.jsonl'), 'x', ''],
      [dir, 'x', ''],
      ['', 'x', ''],
    ];
    const LABEL = ['rules', 'rules, current spaced', 'rules, other current', 'a sidechain record last', 'a meta record last', 'falsy isSidechain/isMeta last', 'trailing copies', 'current not yet written', 'bad utf-8', 'astral', 'cut line, kept', 'cut line only', 'ghost after the cut', 'exactly TAIL_BYTES', 'one byte over', 'prompt before the tail', 'missing file', 'a directory', 'empty path'];
    const pp = py(ctx, sideEnv(dir, 'py', join(root, 'home-const')), { op: 'previous_prompt', calls: PP.map(([p, c]) => ({ path: b64(p), current: b64(c) })) });
    const np = PP.map(([p, c]) => hook.previousPrompt(p, c));
    PP.forEach(([, , want], i) => {
      const tag = i < 10 ? 'head/rules' : i < 16 ? 'head/boundary' : 'head/missing';
      cases.push({ name: `${tag}: ${LABEL[i]} — previous prompt, python against node`, kind: 'string', expected: unb64(pp.out[i]), actual: np[i] });
      cases.push(...literalCases(unb64(pp.out[i]), np[i], `${tag}: LITERAL ${LABEL[i]}`, want, 'string'));
    });
    // 11. head/short-limit: 79, 80, 81 code points, and an astral 79 (158 UTF-16 units).
    const long = file('long.jsonl', rec('p'.repeat(600)) + '\n');
    const HQ = [
      ['ok?', long, `ok?\n${'p'.repeat(500)}`],
      ['x'.repeat(79), long, `${'x'.repeat(79)}\n${'p'.repeat(500)}`],
      ['x'.repeat(80), long, null],
      ['x'.repeat(81), long, null],
      ['🐔'.repeat(79), long, `${'🐔'.repeat(79)}\n${'p'.repeat(500)}`],
      ['🐔'.repeat(80), long, null],
      ['ok?', join(dir, 'none.jsonl'), null],
      ['ok?', '', null],
      ['ok?', astral, 'ok?\n🐔 hen prompt ไทย'],
    ];
    const ph = py(ctx, sideEnv(dir, 'py', join(root, 'home-const')), { op: 'head_query', calls: HQ.map(([p, t]) => ({ prompt: b64(p), path: b64(t) })) });
    const nh = HQ.map(([p, t]) => hook.headQuery(p, t));
    HQ.forEach(([p, t, want], i) => {
      const label = `${cps(p)} code points${p.startsWith('🐔') ? ' (astral)' : ''}${t === '' ? ', no transcript' : t.endsWith('none.jsonl') ? ', missing transcript' : ''}`;
      const pv = ph.out[i] === null ? null : unb64(ph.out[i]);
      cases.push({ name: `head/short-limit: ${label} — python against node`, kind: 'json', expected: pv, actual: nh[i] });
      cases.push(...literalCases(pv, nh[i], `head/short-limit: LITERAL ${label}`, want));
    });
  }

  // ============================================================ write paths (13-18)
  //
  // 13/14/19 run both SERVERS over stdio on one bed path, rebuilt before each side, so every
  // path either side prints or keys on is the same.
  const INIT = JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'conformance', version: '0' } },
  });
  const INITIALIZED = JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' });
  const rpc = (id, method, params) => JSON.stringify({ jsonrpc: '2.0', id, method, params });
  const callTool = (id, tool, args) => rpc(id, 'tools/call', { name: tool, arguments: args });
  const srv = join(root, 'server');
  const srvHome = join(srv, 'home');
  const srvStore = join(srv, 'project', 'store');
  const serverEnv = (extra = {}) => ({
    HOME: srvHome,
    USERPROFILE: srvHome,
    BANTAMKIT_ASSETS: ASSETS,
    BANTAMKIT_MEMORY_DIR: null,
    BANTAMKIT_INDEX_DIR: join(srv, 'idx'),
    BANTAMKIT_RETENTION: 'off',
    CLAUDE_COWORK_MEMORY_PATH_OVERRIDE: null,
    BANTAMKIT_EVENT_LOG: null,
    ...extra,
  });
  const serve = async (spec, setup) => {
    const wire = { name: spec.name, argv: ['--store', srvStore], env: serverEnv(spec.env), cwd: join(srv, 'project'), lines: spec.lines };
    const after = {};
    const one = async (side) => {
      rmSync(srv, { recursive: true, force: true });
      mkdirSync(srvHome, { recursive: true });
      mkdirSync(join(srv, 'project'), { recursive: true });
      setup?.();
      let frames;
      if (side === 'py') {
        const [s] = ctx.runPython(WIRE_REF, { sessions: [{ ...wire, lines: wire.lines.map(b64) }] }).sessions;
        frames = s.frames.map(unb64);
      } else {
        frames = (await runNodeServer(wire)).frames;
      }
      const byId = new Map();
      for (const line of frames) {
        try {
          const f = JSON.parse(line);
          if (f && f.id !== undefined) byId.set(f.id, f);
        } catch {
          /* a non-frame line fails the frame comparison */
        }
      }
      const side_ = { frames, byId };
      const sc = existsSync(join(srvStore)) ? sidecarOf(srvHome, srvStore) : null;
      side_.sidecar = sc !== null && existsSync(sc) ? readFileSync(sc, 'utf8') : null;
      // A copy of the bed as this side left it, for the cross-read (14).
      const keep = join(root, `server-${spec.name}-${side}`);
      rmSync(keep, { recursive: true, force: true });
      cpSync(srv, keep, { recursive: true });
      side_.kept = keep;
      after[side] = side_;
    };
    await one('py');
    await one('node');
    return after;
  };
  const text = (side, id) => side.byId.get(id)?.result?.content?.[0]?.text ?? JSON.stringify(side.byId.get(id) ?? null);
  const structured = (side, id) => side.byId.get(id)?.result?.structuredContent ?? null;

  // 13. save/sidecar-bytes, over stdio: names saved out of order, a Thai name, an update to
  // [], and a fact saved with no queries at all.
  {
    const SAVES = [
      ['zeta-fact', 'the zeta deploy path', ['วิธี deploy zeta', 'how to deploy zeta', 'zeta?']],
      ['alpha-fact', 'the alpha release notes', ['ปล่อย alpha', 'cut the alpha release']],
      ['thai-fact', 'ข้อเท็จจริงภาษาไทย', ['คำถามภาษาไทย', 'thai fact question', '🐔 astral']],
      ['beta-fact', 'the beta fact with none', null],
      ['mid-fact', 'saved with queries then cleared', ['to be removed']],
      ['mid-fact', 'saved with queries then cleared', []],
    ];
    const lines = [INIT, INITIALIZED];
    SAVES.forEach(([n, d, q], i) => {
      const args = { type: 'project', name: n, description: d, body: `body of ${n}` };
      if (q !== null) args.queries = q;
      lines.push(callTool(2 + i, 'memory_save', args));
    });
    const RECALL_ID = 2 + SAVES.length;
    lines.push(callTool(RECALL_ID, 'memory_recall', { query: 'zeta?' }));
    const r = await serve({ name: 'save', lines });
    SAVES.forEach(([n], i) => {
      cases.push({ name: `save/sidecar-bytes: memory_save ${n} reply`, kind: 'string', expected: text(r.py, 2 + i), actual: text(r.node, 2 + i) });
    });
    cases.push({ name: 'save/sidecar-bytes: the sidecar each server left is byte-identical', kind: 'string', expected: r.py.sidecar ?? '<no sidecar>', actual: r.node.sidecar ?? '<no sidecar>' });
    const shape = (s) => {
      if (s === null) return null;
      const doc = JSON.parse(s);
      return { v: doc.v, names: Object.keys(doc.facts), queries: Object.fromEntries(Object.entries(doc.facts).map(([k, e]) => [k, e.queries])), shaLen: [...new Set(Object.values(doc.facts).map((e) => e.sha.length))] };
    };
    const WANT = {
      v: 1,
      names: ['alpha-fact', 'thai-fact', 'zeta-fact'],
      queries: { 'alpha-fact': SAVES[1][2], 'thai-fact': SAVES[2][2], 'zeta-fact': SAVES[0][2] },
      shaLen: [40],
    };
    cases.push(...literalCases(shape(r.py.sidecar), shape(r.node.sidecar), 'save/sidecar-bytes: LITERAL keys sorted, [] removed, an omitted queries writes nothing, sha1 recorded', WANT));
    cases.push({ name: 'save/sidecar-bytes: a recall by the queries reads the same', kind: 'string', expected: text(r.py, RECALL_ID), actual: text(r.node, RECALL_ID) });

    // 14. save/cross-read: each side's bed ranked by the other runtime.
    const crossCalls = ['how to deploy zeta', 'cut alpha', 'คำถามภาษาไทย', 'zeta?'].map((p) => ({ prompt: b64(p), head: null }));
    const crossReq = (kept) => ({
      op: 'rank',
      project: join(kept, 'project', 'store'),
      profile: join(kept, 'no-profile'),
      native: null,
      depth: 10,
      calls: crossCalls,
    });
    const home = (kept) => join(kept, 'home');
    // The sidecar is keyed on the store's path, which was `srvStore`: put the kept bed's copy
    // where that key now points (the kept store's own path).
    for (const side of ['py', 'node']) {
      const kept = r[side].kept;
      const keptStore = join(kept, 'project', 'store');
      if (r[side].sidecar !== null) write(sidecarOf(home(kept), keptStore), r[side].sidecar);
    }
    const v = (res) => res.results.map((x) => ({ inject: names(x.inject), rank: names(x.rank), trace: x.trace }));
    const pyOnPy = v(py(ctx, sideEnv(r.py.kept, 'py', home(r.py.kept)), crossReq(r.py.kept)));
    const nodeOnPy = v(nodeRank(sideEnv(r.py.kept, 'node', home(r.py.kept)), crossReq(r.py.kept)));
    const pyOnNode = v(py(ctx, sideEnv(r.node.kept, 'py', home(r.node.kept)), crossReq(r.node.kept)));
    const nodeOnNode = v(nodeRank(sideEnv(r.node.kept, 'node', home(r.node.kept)), crossReq(r.node.kept)));
    cases.push({ name: 'save/cross-read: a Python-written sidecar ranks the same in Node', kind: 'json', expected: pyOnPy, actual: nodeOnPy });
    cases.push({ name: 'save/cross-read: a Node-written sidecar ranks the same in Python', kind: 'json', expected: nodeOnNode, actual: pyOnNode });
    cases.push(...literalCases(pyOnPy.map((x) => x.inject), nodeOnNode.map((x) => x.inject), 'save/cross-read: LITERAL the queries reach their facts', [['zeta-fact'], ['alpha-fact'], ['thai-fact'], ['zeta-fact']]));
  }

  // 15. save/limits and 16. save/write-fails, through the component API.
  {
    const dir = join(root, 'limits');
    rmSync(dir, { recursive: true, force: true });
    const store = join(dir, 'store');
    mkdirSync(join(store, 'facts'), { recursive: true });
    mkdirSync(join(store, 'archive'), { recursive: true });
    const LIMITS = [
      ['nine', Array.from({ length: 9 }, (_, i) => `q${i}`), S1(9)],
      ['long', ['ok', 'y'.repeat(201)], S2(2, 201)],
      ['astral-200', ['🐔'.repeat(200)], null],
      ['astral-201', ['🐔'.repeat(201)], S2(1, 201)],
      ['eight', Array.from({ length: 8 }, (_, i) => `q${i}`), null],
      ['not-a-string', ['ok', 3], S3],
      ['not-a-list', 'ok', S3],
    ];
    const pc = py(ctx, sideEnv(dir, 'py', join(dir, 'home-py')), { op: 'check_queries', values: LIMITS.map(([, v]) => v) });
    const nc = LIMITS.map(([, v]) => {
      try {
        return { ok: queries.checkQueries(v).map(b64) };
      } catch (e) {
        return { error: b64(e.message) };
      }
    });
    const view = (o) => (o.error !== undefined ? { error: unb64(o.error) } : { ok: o.ok.length });
    LIMITS.forEach(([label, v, want], i) => {
      cases.push({ name: `save/limits: check_queries ${label} — python against node`, kind: 'json', expected: view(pc.out[i]), actual: view(nc[i]) });
      cases.push(...literalCases(view(pc.out[i]), view(nc[i]), `save/limits: LITERAL check_queries ${label}`, want === null ? { ok: v.length } : { error: want }));
    });
    // Through save: a refused save writes neither the fact nor the sidecar.
    const SAVE = [
      { type: 'project', name: 'limit-nine', description: 'nine queries refused', body: 'b', queries: Array.from({ length: 9 }, (_, i) => b64(`q${i}`)) },
      { type: 'project', name: 'limit-long', description: 'a long query refused', body: 'b', queries: [b64('y'.repeat(201))] },
      { type: 'project', name: 'limit-astral', description: 'two hundred astral code points', body: 'b', queries: [b64('🐔'.repeat(200))] },
    ];
    const ps = py(ctx, sideEnv(dir, 'py', join(dir, 'home-py')), { op: 'save', store, calls: SAVE });
    const facts = () => (existsSync(join(store, 'facts')) ? readdirNames(join(store, 'facts')) : []);
    const pyFacts = facts();
    rmSync(join(store, 'facts'), { recursive: true, force: true });
    mkdirSync(join(store, 'facts'), { recursive: true });
    const ns = nodeSave(sideEnv(dir, 'node', join(dir, 'home-node')), { store, calls: SAVE.map((c) => ({ ...c })) });
    const nodeFacts = facts();
    const sv = (o) => ({ reply: unb64(o.reply), status: o.status });
    SAVE.forEach((c, i) => {
      cases.push({ name: `save/limits: memory_save ${c.name} — python against node`, kind: 'json', expected: sv(ps.out[i]), actual: sv(ns.out[i]) });
    });
    cases.push(...literalCases(ps.out.map((o) => o.status), ns.out.map((o) => o.status), 'save/limits: LITERAL a limit refuses the whole save; 200 astral code points are accepted', ['refused-validation', 'refused-validation', 'saved']));
    cases.push(...literalCases(sv(ps.out[0]).reply.includes(S1(9)), sv(ns.out[0]).reply.includes(S1(9)), 'save/limits: LITERAL the refusal carries S1', true));
    cases.push(...literalCases(pyFacts, nodeFacts, 'save/limits: LITERAL only the accepted fact was written', ['limit-astral.md']));
    const scPy = sidecarOf(join(dir, 'home-py'), store);
    const scNode = sidecarOf(join(dir, 'home-node'), store);
    cases.push({ name: 'save/limits: the accepted save leaves the same sidecar on both sides', kind: 'string', expected: existsSync(scPy) ? readFileSync(scPy, 'utf8') : '<none>', actual: existsSync(scNode) ? readFileSync(scNode, 'utf8') : '<none>' });

    // 16. save/write-fails: a FILE where the queries directory belongs.
    const WF = [{ type: 'project', name: 'write-fails', description: 'the sidecar cannot be written', body: 'b', queries: [b64('how')] }];
    for (const side of ['py', 'node']) write(join(dir, `wf-home-${side}`, '.bantamkit', 'queries'), 'a file where the queries directory goes');
    const wstore = join(dir, 'wstore');
    mkdirSync(join(wstore, 'facts'), { recursive: true });
    const pw = py(ctx, sideEnv(dir, 'py', join(dir, 'wf-home-py')), { op: 'save', store: wstore, calls: WF });
    const pwFacts = readdirNames(join(wstore, 'facts'));
    rmSync(join(wstore, 'facts'), { recursive: true, force: true });
    mkdirSync(join(wstore, 'facts'), { recursive: true });
    const nw = nodeSave(sideEnv(dir, 'node', join(dir, 'wf-home-node')), { store: wstore, calls: WF });
    const nwFacts = readdirNames(join(wstore, 'facts'));
    cases.push({ name: 'save/write-fails: reply and status — python against node', kind: 'json', expected: sv(pw.out[0]), actual: sv(nw.out[0]) });
    cases.push(...literalCases(sv(pw.out[0]).reply.endsWith(S4) && pw.out[0].status === 'saved', sv(nw.out[0]).reply.endsWith(S4) && nw.out[0].status === 'saved', 'save/write-fails: LITERAL the reply ends with S4 and the save stands', true));
    cases.push(...literalCases(pwFacts, nwFacts, 'save/write-fails: LITERAL the fact is on disk', ['write-fails.md']));
  }

  // 17. memory_queries/list and 18. memory_queries/write + refusals, through the component.
  {
    const bed = mixedBed(join(root, 'mq'), { sidecars: false });
    // A body past the 600-code-point cut, astral included, so the cut is counted in code points.
    write(join(bed.project, 'facts', 'long-body.md'), factFile('long-body', 'a fact with a long body', 'project', `${'🐔'.repeat(300)}${'b'.repeat(400)}`));
    const LABELS = 'project, profile, native';
    const good = { name: 'deploy-runbook', queries: ['how do I deploy', 'วิธี deploy'] };
    const CALLS = [
      { do: 'coverage' },
      { do: 'missing' },
      { do: 'write', facts: [good, { name: 'native-only', layer: 'native', queries: ['budget?'] }, { name: 'windows-eperm', queries: ['npx EPERM'] }] },
      { do: 'coverage' },
      { do: 'missing' },
      // refusals, each after a good item: nothing of the call may be written
      { do: 'write', facts: [good, 'x'] },
      { do: 'write', facts: [good, { name: '', queries: [] }] },
      { do: 'write', facts: [good, { name: 'deploy-runbook' }] },
      { do: 'write', facts: [good, { name: 'deploy-runbook', queries: [], layer: 3 }] },
      { do: 'write', facts: [good, { name: 'deploy-runbook', layer: 'nope', queries: ['x'] }] },
      { do: 'write', facts: [good, { name: 'no-such-fact', queries: ['x'] }] },
      { do: 'write', facts: [good, { name: 'gate-rule', layer: 'profile', queries: ['x'] }] },
      { do: 'write', facts: [good, { name: 'gate-rule', queries: Array.from({ length: 9 }, () => 'q') }] },
      { do: 'write', facts: [good, { name: 'gate-rule', queries: ['y'.repeat(201)] }] },
      { do: 'write', facts: [good, { name: 'gate-rule', queries: [1] }] },
      // [] removes an entry
      { do: 'write', facts: [{ name: 'windows-eperm', queries: [] }] },
      { do: 'coverage' },
    ];
    const REFUSALS = [
      S5(1),
      S5(1),
      S5(1),
      S5(1),
      S6(1, 'nope', LABELS),
      S7(1, 'no-such-fact', 'any layer'),
      S7(1, 'gate-rule', "layer 'profile'"),
      `facts[1]: ${S1(9)}`,
      `facts[1]: ${S2(1, 201)}`,
      `facts[1]: ${S3}`,
    ];
    const req = { op: 'queries', project: bed.project, profile: bed.profile, native: bed.native };
    const sidecars = (home) => [bed.project, bed.profile, bed.native].map((r) => {
      const p = sidecarOf(home, r);
      return existsSync(p) ? readFileSync(p, 'utf8') : null;
    });
    // One call at a time, so the sidecars can be read between calls on each side.
    const stepPy = [];
    const stepNode = [];
    for (const c of CALLS) {
      const p = py(ctx, sideEnv(bed.root, 'py', bed.homes.py), { ...req, calls: [c] }).out[0];
      stepPy.push({ out: p, sidecars: sidecars(bed.homes.py) });
      const n = nodeQueries(sideEnv(bed.root, 'node', bed.homes.node), { ...req, calls: [c] }).out[0];
      stepNode.push({ out: n, sidecars: sidecars(bed.homes.node) });
    }
    CALLS.forEach((c, i) => {
      const label = c.do === 'write' ? `write ${JSON.stringify(c.facts.at(-1)).slice(0, 80)}` : c.do;
      cases.push({ name: `memory_queries/${c.do === 'missing' ? 'list' : c.do}: step ${i} ${label} — answer and the sidecars after it, python against node`, kind: 'json', expected: stepPy[i], actual: stepNode[i] });
    });
    const at = (steps, i) => steps[i].out;
    cases.push(...literalCases(at(stepPy, 0), at(stepNode, 0), 'memory_queries/coverage: LITERAL before any write (the shadowed native copy counts once)', [0, 10]));
    const listView = (o) => ({ result: o.result, remaining: o.remaining, facts: o.facts.map((f) => [f.layer, f.name, cps(f.body)]), instructions: o.instructions.startsWith('# Likely-prompt queries') && o.instructions.includes('memory_queries') });
    cases.push(
      ...literalCases(listView(at(stepPy, 1)), listView(at(stepNode, 1)), 'memory_queries/list: LITERAL the missing list (precedence then name), the 600-code-point cut, the instructions', {
        result: 'missing',
        remaining: 10,
        facts: [
          ['project', 'deploy-runbook', 1],
          ['project', 'gate-rule', 1],
          ['project', 'hook-latency', 1],
          ['project', 'long-body', 600],
          ['project', 'release-lessons', 1],
          ['project', 'script-only', 1],
          ['project', 'shared-name', 1],
          ['profile', 'user-language', 1],
          ['profile', 'windows-eperm', 1],
          ['native', 'native-only', 11],
        ],
        instructions: true,
      }),
    );
    cases.push(...literalCases(at(stepPy, 2), at(stepNode, 2), 'memory_queries/write: LITERAL three written, seven left', { result: 'written', written: 3, remaining: 7 }));
    cases.push(...literalCases(at(stepPy, 3), at(stepNode, 3), 'memory_queries/coverage: LITERAL after the write', [3, 10]));
    REFUSALS.forEach((want, j) => {
      const i = 5 + j;
      cases.push(...literalCases(at(stepPy, i), at(stepNode, i), `memory_queries/refusals: LITERAL ${want}`, { result: 'error', reason: want }));
      cases.push(...literalCases(
        JSON.stringify(stepPy[i].sidecars) === JSON.stringify(stepPy[4].sidecars),
        JSON.stringify(stepNode[i].sidecars) === JSON.stringify(stepNode[4].sidecars),
        `memory_queries/refusals: LITERAL the sidecars are byte-unchanged after ${JSON.stringify(want)}`,
        true,
      ));
    });
    cases.push(...literalCases(at(stepPy, CALLS.length - 1), at(stepNode, CALLS.length - 1), 'memory_queries/write: LITERAL queries [] removes the entry', [2, 10]));

    // S9: the write itself fails (a FILE where the queries directory goes).
    const s9 = mixedBed(join(root, 'mq-s9'), { sidecars: false });
    for (const side of ['py', 'node']) write(join(s9.homes[side], '.bantamkit', 'queries'), 'in the way');
    const s9req = { op: 'queries', project: s9.project, profile: s9.profile, native: s9.native, calls: [{ do: 'write', facts: [good] }] };
    const p9 = py(ctx, sideEnv(s9.root, 'py', s9.homes.py), s9req).out[0];
    const n9 = nodeQueries(sideEnv(s9.root, 'node', s9.homes.node), s9req).out[0];
    cases.push(...literalCases(p9, n9, 'memory_queries/refusals: LITERAL S9 when the sidecar cannot be written', { result: 'error', reason: S9 }));
  }

  // ===================================================================== reporting (19, 22)
  {
    const fact = (n, d) => write(join(srvStore, 'facts', `${n}.md`), factFile(n, d));
    const base = () => {
      mkdirSync(join(srvStore, 'facts'), { recursive: true });
      mkdirSync(join(srvStore, 'archive'), { recursive: true });
    };
    const two = () => {
      base();
      fact('one-fact', 'the first fact');
      fact('two-fact', 'the second fact');
    };
    const sc = (entries) => write(sidecarOf(srvHome, srvStore), sidecarDoc(entries));
    const SCENARIOS = [
      ['0 of 0', base, S10(0, 0)],
      ['1 of 2', () => (two(), sc({ 'one-fact': ['how one'] })), S10(1, 2)],
      ['2 of 2', () => (two(), sc({ 'one-fact': ['how one'], 'two-fact': ['how two'] })), S10(2, 2)],
      ['an orphan entry counts nothing', () => (two(), sc({ 'gone-fact': ['x'] })), S10(0, 2)],
      // An unreadable project store: `facts` is a FILE, on POSIX and Windows alike.
      ['unreadable', () => (mkdirSync(srvStore, { recursive: true }), write(join(srvStore, 'facts'), 'not a directory')), S11],
    ];
    const statusLines = [];
    for (const [label, setup, want] of SCENARIOS) {
      const lines = [INIT, INITIALIZED, rpc(2, 'tools/list', {}), callTool(3, 'bantamkit_status', {})];
      const r = await serve({ name: `status-${label.replace(/\W+/g, '-')}`, lines }, setup);
      const report = (side) => text(side, 3);
      const line = (side) => report(side).split('\n').find((l) => l.startsWith('queries:')) ?? '<no queries line>';
      cases.push(...literalCases(line(r.py), line(r.node), `status/queries-line: LITERAL ${label}`, want, 'string'));
      const minusBuild = (s) => s.split('\n').filter((l) => !/build sha256:|\bversion \d/.test(l)).join('\n');
      cases.push({ name: `status/queries-line: ${label} — the whole report minus the build line, python against node`, kind: 'string', expected: minusBuild(report(r.py)), actual: minusBuild(report(r.node)) });
      statusLines.push(`${label}: ${line(r.py)}`);
      if (label === '1 of 2') {
        // 22. the roster: both servers serve memory_queries with the same schema.
        const tools = (side) => side.byId.get(2)?.result?.tools ?? [];
        const named = (side) => tools(side).find((t) => t.name === 'memory_queries') ?? null;
        cases.push(...literalCases(tools(r.py).length, tools(r.node).length, 'tools/list: LITERAL fifteen tools', 15));
        cases.push(...literalCases(named(r.py) !== null, named(r.node) !== null, 'tools/list: LITERAL memory_queries is served', true));
        cases.push({ name: 'tools/list: memory_queries is served with the same schema', kind: 'json', expected: named(r.py), actual: named(r.node) });
        const saveQ = (side) => tools(side).find((t) => t.name === 'memory_save')?.inputSchema?.properties?.queries ?? null;
        cases.push({ name: 'tools/list: memory_save serves the same queries parameter', kind: 'json', expected: saveQ(r.py), actual: saveQ(r.node) });
        cases.push(...literalCases(saveQ(r.py) !== null, saveQ(r.node) !== null, 'tools/list: LITERAL memory_save takes queries', true));
      }
    }
    notes.push(`status lines (python): ${statusLines.join('; ')}`);
  }

  notes.push(`beds under ${root}; every side ran with its own HOME, BANTAMKIT_INDEX_DIR and BANTAMKIT_RETENTION=off`);
  return { cases, notes };
}

/** The `.md` names in `dir`, sorted; `[]` when it cannot be listed. */
function readdirNames(dir) {
  try {
    return readdirSync(dir).filter((n) => n.endsWith('.md')).sort();
  } catch {
    return [];
  }
}
