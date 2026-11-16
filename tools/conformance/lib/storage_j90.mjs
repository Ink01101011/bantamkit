/**
 * J90-1 (#316 G4 prep): the Node side of `ref/storage_ref.py`'s `storage-j90` section, op for
 * op. Each owning suite (`storage-index`, `storage-cold`, `storage-retention`, `storage-lock`)
 * calls `j90(ctx, section)`, which runs the reference and this module over two scratch
 * directories and answers `{ py, nd }`; the suite decides which answers are compared and which
 * were pinned as `UNRULED DIVERGENCE` until J90-1F settled them (see `j90Cases`). Change one side,
 * change both.
 *
 * A raise is the answer `{ raised: <class>, msg: <sentence> }` on both sides.
 */
import { mkdirSync, readFileSync, readdirSync, statSync, symlinkSync, unlinkSync, utimesSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gzipSync } from 'node:zlib';

const REF = join(dirname(dirname(fileURLToPath(import.meta.url))), 'ref', 'storage_ref.py');
const T = 1_700_000_000;
const FACT = (n, d) =>
  `---\nname: ${n}\ndescription: ${d}\ntype: project\ncreated: '2026-08-01'\n` +
  `last_recalled: null\nlinks: []\n---\n\nbody [[${n}-link]] see src/${n}.py\n`;

const attempt = (f) => {
  try {
    return f();
  } catch (e) {
    return { raised: e?.constructor?.name ?? 'Error', msg: String(e?.message ?? e) };
  }
};
const byKey = (entries) => [...entries].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
const pin = (d) => {
  for (const n of readdirSync(d)) utimesSync(join(d, n), T, T);
  utimesSync(d, T, T);
};

function mangle(raw, mode) {
  const s = raw.toString('latin1');
  if (mode === 'lens_total_float') return Buffer.from(s.replace(/"lens_total":\[(\d+)/, '"lens_total":[$1.0'), 'latin1');
  if (mode === 'full_at_lower') {
    return Buffer.from(s.replace(/"full_at":"([0-9-]{10})T([0-9:]{8})Z"/, '"full_at":"$1t$2z"'), 'latin1');
  }
  if (mode === 'shard_invalid_utf8') return Buffer.from(s.replace('"alpha":', '"alph\xff":'), 'latin1');
  if (mode === 'shard_seg_float') return Buffer.from(s.replace(/"alpha":\[(\d+),1,/, '"alpha":[$1,1.0,'), 'latin1');
  if (mode === 'head_invalid_utf8') return Buffer.from(s.replace('"beta"', '"bet\xff"'), 'latin1');
  if (mode === 'tail_invalid_utf8') return Buffer.from(s.replace('"beta alpha words', '"bet\xff alpha words'), 'latin1');
  throw new Error(mode);
}

async function index(runtimeTs, d) {
  const h = await import(pathToFileURL(join(runtimeTs, 'dist', 'storage', 'hotindex.js')).href);
  const out = {};
  const bed = (name, kind, files) => {
    const root = join(d, name);
    const src = kind === 'facts' ? join(root, 'facts') : root;
    mkdirSync(src, { recursive: true });
    for (const [rel, text] of files) writeFileSync(join(src, rel), text, 'utf8');
    pin(src);
    return [root, join(d, `${name}-home`)];
  };
  const facts = [
    ['alpha.md', FACT('alpha', 'alpha word')],
    ['beta.md', FACT('beta', 'beta alpha words, stale? no')],
    ['other-file.md', FACT('gamma', 'gamma in another file')],
    ['loose.md', '---\nname: 7\ndescription: loose\ntype: project\n---\n\nb\n'],
  ];
  let [root, home] = bed('reads', 'facts', facts);
  let hi = new h.HotIndex(root, 'facts', home);
  hi.refresh('fast');
  const pf = (file) => {
    const got = hi.parseFile(join(root, 'facts', file), '5', 9);
    return typeof got === 'string' ? [null, got] : [got, ''];
  };
  out.reads = {
    names: [...hi.names().keys()],
    doc: hi.doc('alpha'),
    doc_missing: hi.doc('nope'),
    cols: hi.cols(),
    file_of: ['alpha', 'gamma', 'nope'].map((n) => hi.fileOf(n)),
    lens: ['alpha', 'beta', 'nope'].map((n) => hi.lens(n)),
    lens_total: hi.lensTotal(),
    size: hi.docCount(),
    exists: hi.exists(),
    head_print: JSON.parse(hi.headPrint()).shards,
    unchecked: [...hi.docsUnchecked().keys()].sort(),
    parse_file: pf('beta.md'),
    parse_file_loose: pf('loose.md'),
    parse_file_gone: pf('gone.md'),
  };
  hi.invalidate();
  out.reads.after_invalidate = [hi.exists(), hi.docCount()];
  const all = [...h.HEAD_KEYS, ...h.TAIL_KEYS];
  out.units = {
    decode: h.decodeSegments(['a', 'b', 'c'], [0, 2, 1, 0, 3, 2, 1, 0, 0, 1]),
    decode_bad: attempt(() => h.decodeSegments(['a'], [0, 2, 1, 0, 0])),
    encode: h.encodeSegments([[0, 1, 0, 0], [1, 1, 0, 0], [2, 0, 2, 0], [4, 0, 2, 0]]),
    head_text: h.headText(Object.fromEntries(all.map((k) => [k, k]))),
    constants: [h.INDEX_VERSION, h.FULL_REFRESH_EVERY_S, h.SHARDS, [...h.FAMILIES], [...h.HEAD_KEYS], [...h.TAIL_KEYS], h.SEG, h.DUPLICATE, h.INDEX_DIR_ENV],
  };
  for (const mode of ['lens_total_float', 'full_at_lower', 'shard_invalid_utf8', 'shard_seg_float', 'head_invalid_utf8', 'tail_invalid_utf8']) {
    [root, home] = bed(mode, 'facts', facts.slice(0, 2));
    hi = new h.HotIndex(root, 'facts', home);
    hi.refresh('fast');
    const p = mode.startsWith('shard') ? hi.shardPath('postings', h.shardOf('alpha')) : hi.path;
    writeFileSync(p, mangle(readFileSync(p), mode));
    const fresh = new h.HotIndex(root, 'facts', home);
    const res = {
      refresh: attempt(() => fresh.refresh('fast')),
      query: attempt(() => byKey(fresh.query(['alpha']))),
      names: attempt(() => [...fresh.names().keys()]),
      beta: attempt(() => fresh.doc('beta')?.description ?? null),
    };
    const first = readFileSync(fresh.path, 'utf8').split('\n', 1)[0];
    res.full_at_sep = JSON.parse(`${first.slice(0, -1)}}`).full_at.slice(10, 11);
    out[mode] = res;
  }
  [root, home] = bed('native', 'native', [
    ['flow.md', '---\nname: flow\ndescription: flow meta\nmetadata: {type: user}\n---\n\nb\n'],
    ['plain.md', '---\nname: plain\ndescription: ok\nmetadata:\n  type: reference\n---\n\nb\n'],
  ]);
  hi = new h.HotIndex(root, 'native', home);
  hi.refresh('fast');
  out.native_flow = { docs: [...hi.docs().keys()].sort(), skipped: [...hi.skipped.keys()].sort() };
  // J90-2: a source through a symlink whose target is missing (`dangle`), and one through a live
  // symlink (`live` -> `real`). What the index names it by: its realpath's last part, and whether
  // `sha16` hashes the target's path.
  mkdirSync(join(d, 'links', 'real'), { recursive: true });
  symlinkSync('missing-target', join(d, 'links', 'dangle'));
  symlinkSync('real', join(d, 'links', 'live'));
  const named = (link, target) => {
    const p = join(d, 'links', link);
    const real = new h.HotIndex(p, 'facts', join(d, 'links-home')).real;
    return [real.slice(real.lastIndexOf('/') + 1), h.sha16(p) === h.sha16(join(d, 'links', target))];
  };
  out.symlinks = { dangle: named('dangle', 'missing-target'), live: named('live', 'real') };
  return out;
}

async function cold(runtimeTs, d) {
  const c = await import(pathToFileURL(join(runtimeTs, 'dist', 'storage', 'coldindex.js')).href);
  const out = {};
  const doc = (name, desc, file = null) => ({
    file: file ?? `${name}.md`, name, description: desc, type: 'project',
    keywords: ['kw'], links: [], tags: [], refs: [], mtime_ns: '1', size: 1,
  });
  const fresh = (name) => {
    const ci = new c.ColdIndex('t', join(d, name));
    ci.add(new Map([['alpha', doc('alpha', 'word one')], ['beta', doc('beta', 'word two')]]));
    ci.add(new Map([['alpha', doc('alpha', 'word newer')]]));
    return ci;
  };
  let ci = fresh('reads');
  out.reads = {
    owners: byKey(ci.owners()),
    all_docs: ci.allDocs().map((x) => x.description),
    docs: byKey([...ci.docs()].map(([k, v]) => [k, v.description])),
    doc: ci.doc('alpha'),
    doc_missing: ci.doc('nope'),
    manifest_ids: ci.manifest().segments.map((s) => s.id),
    constants: [c.COLD_VERSION],
  };
  out.bad_name = ['a/b', '..', ''].map((n) => attempt(() => new c.ColdIndex(n, d)));
  const sub = (p, a, b) => {
    const raw = readFileSync(p);
    const i = raw.indexOf(a);
    writeFileSync(p, Buffer.concat([raw.subarray(0, i), Buffer.from(b), raw.subarray(i + Buffer.from(a).length)]));
  };
  const run = (name, mutate) => {
    ci = fresh(name);
    mutate(ci);
    const guard = (f) => {
      try {
        return f();
      } catch (e) {
        if (e instanceof c.ColdIndexError) return { ColdIndexError: true };
        throw e;
      }
    };
    return { query: guard(() => ci.query(['word'])), doc: guard(() => ci.doc('beta')) };
  };
  out.tf_float = run('tf_float', (x) => {
    for (let i = 0; i < 16; i += 1) {
      const p = x.shardPath(i);
      if (readFileSync(p, 'utf8').includes('"word"')) sub(p, '"description",1]', '"description",1.0]');
    }
  });
  out.version_true = run('version_true', (x) => sub(x.manifestPath, '"version":1', '"version":true'));
  out.id_newline = run('id_newline', (x) => sub(x.manifestPath, '"id":"000002"', '"id":"000002\\n"'));
  out.seg_invalid_utf8 = run('seg_invalid_utf8', (x) =>
    sub(x.segmentPath('000001'), '"word two"', Buffer.concat([Buffer.from('"word tw'), Buffer.from([0xff]), Buffer.from('"')])),
  );
  return out;
}

async function retention(runtimeTs, d) {
  const r = await import(pathToFileURL(join(runtimeTs, 'dist', 'storage', 'retention.js')).href);
  const out = {};
  const keys = [r.RETENTION_ENV, 'BANTAMKIT_INDEX_DIR'];
  const saved = keys.map((k) => process.env[k]);
  process.env[r.RETENTION_ENV] = 'on';
  process.env.BANTAMKIT_INDEX_DIR = '';
  try {
    const bed = (name) => {
      const home = join(d, name, 'home');
      const root = join(d, name, 'root');
      mkdirSync(join(home, '.bantamkit'), { recursive: true });
      mkdirSync(join(root, '.shiftwork', 'archive'), { recursive: true });
      return [home, root];
    };
    const now = '2026-10-16T00:00:00.000Z';
    let [home, root] = bed('list_status');
    const sw = join(root, '.shiftwork');
    writeFileSync(join(sw, 'checkpoint-a.json'), JSON.stringify({ plan: { units: [{ status: [] }] } }));
    writeFileSync(join(sw, 'checkpoint-b.json'), JSON.stringify({ plan: { units: [{ status: 'done' }] } }));
    pin(sw);
    out.list_status = { run: attempt(() => r.runRetention(home, [root], now)), left: readdirSync(sw).sort() };
    [home, root] = bed('no_file');
    const ci = r.shiftworkCold(home, root);
    const doc = { name: 'j', description: '', type: 'shiftwork', keywords: ['x'], links: [], tags: [], refs: [], mtime_ns: '0', size: 1 };
    ci.add(new Map([['j', doc]]));
    ci.add(new Map([['k', { ...doc, name: 'k', file: '.shiftwork/archive/k.json.gz' }]]));
    out.no_file_run = attempt(() => r.runRetention(home, [root], now));
    out.no_file_search = attempt(() => r.searchArchived(join(root, '.shiftwork', 'checkpoint.json'), 'x', home));
    // J90-1F: an OSError in searchArchived's RETRY, as the reference builds it.
    [home, root] = bed('retry_oserror');
    writeFileSync(join(root, '.shiftwork', 'archive', 'j.json.gz'), gzipSync(JSON.stringify({ '.shiftwork/checkpoint-j.json': 'alpha word' })));
    const cp = join(root, '.shiftwork', 'checkpoint.json');
    const first = attempt(() => r.searchArchived(cp, 'alpha', home));
    const c = r.shiftworkCold(home, root).dir;
    const seg = JSON.parse(readFileSync(join(c, 'seg-000001.json'), 'utf8'));
    seg.id = '000002';
    writeFileSync(join(c, 'seg-000002.json'), JSON.stringify(seg));
    unlinkSync(join(c, 'seg-000001.json'));
    const man = JSON.parse(readFileSync(join(c, 'manifest.json'), 'utf8'));
    man.segments[0].id = '000002';
    writeFileSync(join(c, 'manifest.json'), JSON.stringify(man));
    for (let i = 0; i < 16; i += 1) writeFileSync(join(c, `shard-${String(i).padStart(2, '0')}.json`), '{');
    mkdirSync(join(c, 'seg-000001.json'));
    out.retry_oserror = { first, retry: attempt(() => r.searchArchived(cp, 'alpha', home)) };
    [home] = bed('due');
    writeFileSync(r.statePath(home), Buffer.concat([Buffer.from('{"ran_at":"2026-10-16T00:00:00.000Z","note":"'), Buffer.from([0xff]), Buffer.from('"}')]));
    out.due_invalid_utf8 = r.due(home, '2026-10-16T01:00:00.000Z');
    out.parse_now = [
      '2026-10-16T00:00:00Z', '2026-10-16T00:00:00.123Z', '0001-01-01T00:00:00Z',
      '2024-02-29T23:59:59.999Z', '2023-02-29T00:00:00Z', '0000-01-01T00:00:00Z',
      '2026-10-16T24:00:00Z', '2026-10-16T00:00:60Z', '2026-10-16 00:00:00Z',
      '2026-10-16T00:00:00', 'x', '',
    ].map((s) => attempt(() => r.parseNow(s)));
    out.parse_now_nonstr = attempt(() => r.parseNow(5));
    out.constants = [r.RETENTION_ENV, r.SKILL_AUDIT_ENV, r.TTL_S, r.LEDGER_DAYS, r.LOG_DAYS, r.JOB_DAYS, r.STATE_NAME, r.SEARCH_MAX];
  } finally {
    keys.forEach((k, i) => {
      if (saved[i] === undefined) delete process.env[k];
      else process.env[k] = saved[i];
    });
  }
  return out;
}

async function lock(runtimeTs, d) {
  const l = await import(pathToFileURL(join(runtimeTs, 'dist', 'storage', 'lock.js')).href);
  const t = join(d, 'target');
  const was = process.umask(0o022); // as the reference sets it
  try {
    const mode = l.exclusive(t, (held) => [held, `0o${(statSync(`${t}.lock`).mode & 0o777).toString(8)}`]);
    // J90-1F: the wait with the WALL clock stepped back 1 s (or on 5 s), as the reference does it.
    const real = Date.now;
    const clock = [];
    for (const jump of [-1000, 5000]) {
      writeFileSync(`${t}.lock`, '');
      let calls = 0;
      Date.now = () => real() + (calls++ > 0 ? jump : 0);
      const t0 = performance.now();
      let got;
      try {
        got = l.exclusive(t, (h) => h, { waitMs: 200, staleMs: 60_000 });
      } finally {
        Date.now = real;
      }
      const waited = performance.now() - t0;
      clock.push([got, waited < 1000, waited >= 150]);
    }
    unlinkSync(`${t}.lock`);
    return { mode, clock, constants: [l.LOCK_WAIT_MS, l.LOCK_STALE_MS, l.LOCK_POLL_MS] };
  } finally {
    process.umask(was);
  }
}

const SECTIONS = { index, cold, retention, lock };

/** `{ py, nd }` for one section, each side in its own scratch directory. */
export async function j90(ctx, section) {
  const base = join(ctx.scratch, `j90-${section}`);
  const dirs = { py: join(base, 'py'), nd: join(base, 'node') };
  for (const p of Object.values(dirs)) mkdirSync(p, { recursive: true });
  const py = ctx.runPython(REF, { suite: 'storage-j90', section, dir: dirs.py });
  const nd = await SECTIONS[section](ctx.runtimeTs, dirs.nd);
  return { py, nd, dirs };
}

/** `text` with each side's scratch directory written `<dir>`, so a sentence that names a path compares. */
export function unpath(value, dir) {
  return JSON.parse(JSON.stringify(value ?? null).split(dir).join('<dir>'));
}

// --------------------------------------------------------------------------------- the cases

const bit = (v) => v !== null && typeof v === 'object' && !Array.isArray(v) && 'raised' in v;
const msgOf = (v) => (bit(v) ? v.msg : v);

/*
 * J90-1F settled the sixteen inputs J90-1 pinned `UNRULED DIVERGENCE` (and three more it found):
 * fifteen now AGREE — each compared side to side and pinned per side below, so a change made on
 * both sides at once still fails — and one, the native flow mapping, is RULED under #228
 * (docs/porting.md), with its outcome bit pinned per side and the half it does not license compared.
 */
const Q_ALPHA = [['alpha', [['alpha', 'name', 1], ['alpha', 'description', 1], ['beta', 'description', 1]]]];
const SETTLED_INDEX = {
  query: Q_ALPHA, names: ['alpha', 'beta'], beta: 'beta alpha words, stale? no', full_at_sep: 'T',
};
const CIE = { ColdIndexError: true };
const BETA_DOC = {
  description: 'word two', file: 'beta.md', keywords: ['kw'], links: [], mtime_ns: '1', name: 'beta',
  refs: [], size: 1, tags: [], type: 'project',
};
const EMPTY_REPORT = { archived: [], compacted: [], deleted: [], folded: [], refused: [], rotated: [] };
const RULING_228_HOT =
  '#228 (docs/porting.md, the hot index row): a native fact whose frontmatter only PyYAML reads (here a flow ' +
  'mapping, `metadata: {type: user}`) is indexed by the reference, which reads native files with ' +
  '`divergence.parse_fact` (`yaml.safe_load`), and skipped by the port, whose codec refuses the shape by name ' +
  "(#120). Each side's hot index holds what that side's native mirror and recall read for the same file.";

const UNRULED_J90_2 =
  'UNRULED DIVERGENCE (J90-2): not ruled in docs/porting.md and not fixed; found while generating the hot index ' +
  '(#316 G4) and left as it stood on 9c6bc181 for the orchestrator: os.path.realpath follows a dangling symlink, ' +
  "Node's realpathSync refuses it and the port keeps the link as spelled.";

/** Per-side literals: a change made on both sides leaves the differential green, these do not. */
const LITERALS = {
  index: {
    names: ['7', 'alpha', 'beta', 'gamma'],
    file_of: ['alpha.md', 'other-file.md', null],
    size: 4,
    encode: [0, 2, 1, 0, 0, 2, 1, 0, 2, 0, 4, 1, 0, 2, 0],
    constants: [5, 600, 16, ['postings', 'words'],
      ['avgdl', 'boost', 'cols', 'dir_mtime_ns', 'fingerprint', 'full_at', 'kind', 'lens_total', 'loose', 'shards', 'skipped', 'source', 'version'],
      ['df', 'docs', 'files', 'lens'], 5, 'duplicate name', 'BANTAMKIT_INDEX_DIR'],
  },
  cold: { owners: [['alpha', '000002'], ['beta', '000001']], all_docs: ['word one', 'word two', 'word newer'] },
  retention: {
    constants: ['BANTAMKIT_RETENTION', 'BANTAMKIT_SKILL_AUDIT', 86400, 7, 30, 7, 'retention.json', 50],
    parse_now_values: [1792108800000, 1792108800123, -62135596800000, 1709251199999],
  },
  lock: { constants: [2000, 10000, 5] },
};

/** The cases one section contributes to its owning suite. */
export function j90Cases(section, { py, nd, dirs }) {
  const P = (v) => unpath(v, dirs.py);
  const N = (v) => unpath(v, dirs.nd);
  const cases = [];
  const same = (name, a, b, kind = 'json') => cases.push({ name: `J90-1 ${name}`, kind, expected: a, actual: b });
  const lit = (name, expected, a, b) => {
    cases.push({ name: `LITERAL: J90-1 ${name} — python`, kind: 'json', expected, actual: a });
    cases.push({ name: `LITERAL: J90-1 ${name} — node`, kind: 'json', expected, actual: b });
  };
  if (section === 'index') {
    const L = LITERALS.index;
    same('HotIndex public reads (names, doc, cols, fileOf, lens, lensTotal, size, exists, headPrint, docsUnchecked, parseFile, invalidate)', P(py.reads), N(nd.reads));
    lit('HotIndex names / fileOf / size', [L.names, L.file_of, L.size], [py.reads.names, py.reads.file_of, py.reads.size], [nd.reads.names, nd.reads.file_of, nd.reads.size]);
    same('decodeSegments / encodeSegments / headText', [py.units.decode, py.units.encode, py.units.head_text], [nd.units.decode, nd.units.encode, nd.units.head_text]);
    same('decodeSegments refuses a run past the names (the bit and the sentence)', [bit(py.units.decode_bad), msgOf(py.units.decode_bad)], [bit(nd.units.decode_bad), msgOf(nd.units.decode_bad)]);
    same('hotindex constants', py.units.constants, nd.units.constants);
    lit('hotindex encodeSegments and constants', [L.encode, L.constants], [py.units.encode, py.units.constants], [nd.units.encode, nd.units.constants]);
    // #1 #2 #4 settled to node's answer, #3 (and the head and tail J90-1F found alike) to python's.
    const modes = ['lens_total_float', 'full_at_lower', 'shard_invalid_utf8', 'shard_seg_float', 'head_invalid_utf8', 'tail_invalid_utf8'];
    const why = {
      lens_total_float: 'a head whose lens_total holds 1.0 is read as 1 and trusted (was: python rebuilt)',
      full_at_lower: 'a head whose full_at is spelled with a lowercase t and z is unreadable: a full refresh rewrites it (was: python kept it)',
      shard_invalid_utf8: 'a postings shard with an invalid UTF-8 byte in a term is refused and rebuilt, the term found (was: node lost it)',
      shard_seg_float: 'a postings shard whose run length is 1.0 reads as 1 and answers (was: python raised malformed postings)',
      head_invalid_utf8: 'a head whose first line holds an invalid UTF-8 byte is refused and rebuilt (was: node trusted a U+FFFD name)',
      tail_invalid_utf8: 'a head whose second line holds an invalid UTF-8 byte is refused and rebuilt (was: node served a U+FFFD description)',
    };
    for (const m of modes) {
      const pick = (r) => ({ refresh: r.refresh, query: r.query, names: r.names, beta: r.beta, full_at_sep: r.full_at_sep });
      same(`${why[m]} — refresh, query, names, doc, stamp`, py[m], nd[m]);
      // Only a refused FIRST line is seen by the fast refresh (it rebuilds); a bad second line,
      // shard or stamp is met later (`_complete`, `_shard`, the full-refresh test).
      const refresh = m === 'head_invalid_utf8' ? 'rebuilt' : 'fresh';
      lit(`${why[m]}`, { refresh, ...SETTLED_INDEX }, pick(py[m]), pick(nd[m]));
    }
    // #5: ruled under #228. The outcome bit DIFFERS, so it is pinned per side; the fact beside it
    // (block-mapping `metadata:`) is read alike, and that half is compared.
    cases.push({ name: 'ruling: #228 the hot index over a native fact only PyYAML reads (flow mapping) — docs and skips', kind: 'json', expected: py.native_flow, actual: nd.native_flow, ruling: RULING_228_HOT });
    cases.push({ name: 'LITERAL: J90-1F #228 per side: the hot index over a native flow mapping — python indexes it', kind: 'json', expected: { docs: ['flow', 'plain'], skipped: [] }, actual: py.native_flow });
    cases.push({ name: 'LITERAL: J90-1F #228 per side: the hot index over a native flow mapping — node skips it by file', kind: 'json', expected: { docs: ['plain'], skipped: ['flow.md'] }, actual: nd.native_flow });
    same('#228 the native fact beside it (block-mapping metadata) is indexed on both sides', py.native_flow.docs.includes('plain'), nd.native_flow.docs.includes('plain'));
    // J90-2: found while generating the index, NOT ruled and NOT fixed (left to the orchestrator):
    // through a dangling symlink the reference's `os.path.realpath` follows the link to its
    // missing target, Node's `realpathSync` refuses it and `nodeRealpath` keeps the link as
    // spelled, so the two name the source's index (`sha16`) and its head's `source` differently.
    // The generated Python keeps the reference's answer (the `nodeRealpath` adapter), so this is
    // the divergence as it stood on 9c6bc181. A live symlink is resolved alike, compared.
    cases.push({
      name: 'ruling: UNRULED DIVERGENCE (J90-2) the hot index of a source through a dangling symlink — realpath and sha16',
      kind: 'json',
      expected: py.symlinks.dangle,
      actual: nd.symlinks.dangle,
      ruling: UNRULED_J90_2,
    });
    cases.push({ name: 'LITERAL: J90-2 a source through a dangling symlink — python follows the link', kind: 'json', expected: ['missing-target', true], actual: py.symlinks.dangle });
    cases.push({ name: 'LITERAL: J90-2 a source through a dangling symlink — node keeps the link', kind: 'json', expected: ['dangle', false], actual: nd.symlinks.dangle });
    same('J90-2 a source through a live symlink is named by its target on both sides', py.symlinks.live, nd.symlinks.live);
    lit('a source through a live symlink', ['real', true], py.symlinks.live, nd.symlinks.live);
  } else if (section === 'cold') {
    same('ColdIndex public reads (owners, allDocs, docs, doc, manifest)', py.reads, nd.reads);
    lit('ColdIndex owners / allDocs', [LITERALS.cold.owners, LITERALS.cold.all_docs], [py.reads.owners, py.reads.all_docs], [nd.reads.owners, nd.reads.all_docs]);
    same('ColdIndex refuses a name with a separator, `..` or empty (the refusal bit)', py.bad_name.map(bit), nd.bad_name.map(bit));
    // #6 #7 #8 #9 settled to node's answer, #10 to python's.
    const names = ['unknown cold index name: "a/b"', 'unknown cold index name: ".."', 'unknown cold index name: ""'];
    same('the ColdIndex bad-name sentence (JSON quotes)', py.bad_name.map(msgOf), nd.bad_name.map(msgOf));
    lit('the ColdIndex bad-name sentence', names, py.bad_name.map(msgOf), nd.bad_name.map(msgOf));
    const settled = [
      ['tf_float', 'a cold shard row whose tf is 1.0 reads as 1 (was: python refused the shard)', { query: [['alpha', '000002', 1], ['beta', '000001', 1]], doc: BETA_DOC }],
      ['version_true', 'a cold manifest whose version is true is refused (was: python accepted True == 1)', { query: CIE, doc: CIE }],
      ['id_newline', 'a cold manifest segment id with a trailing newline is refused (was: python matched before the newline)', { query: CIE, doc: CIE }],
      ['seg_invalid_utf8', 'a cold segment with an invalid UTF-8 byte is refused (was: node served U+FFFD)', { query: [['alpha', '000002', 1], ['beta', '000001', 1]], doc: CIE }],
    ];
    for (const [k, w, want] of settled) {
      same(w, py[k], nd[k]);
      lit(w, want, py[k], nd[k]);
    }
  } else if (section === 'retention') {
    const L = LITERALS.retention;
    same('retention constants', py.constants, nd.constants);
    lit('retention constants', L.constants, py.constants, nd.constants);
    same('parseNow — the value or the refusal bit, per input', py.parse_now.map((v) => (bit(v) ? 'refused' : v)), nd.parse_now.map((v) => (bit(v) ? 'refused' : v)));
    lit('parseNow values', L.parse_now_values, py.parse_now.slice(0, 4), nd.parse_now.slice(0, 4));
    same('parseNow refuses a number (the sentence)', msgOf(py.parse_now_nonstr), msgOf(nd.parse_now_nonstr));
    // #11 #12 #13 #14 settled to node's answer, #15 to python's; the retry OSError (J90-1F) to node's.
    const q = (x) => `not a retention timestamp: ${JSON.stringify(x)}`;
    const refusals = ['2023-02-29T00:00:00Z', '0000-01-01T00:00:00Z', '2026-10-16T24:00:00Z', '2026-10-16T00:00:60Z',
      '2026-10-16 00:00:00Z', '2026-10-16T00:00:00', 'x', ''].map(q);
    same('parseNow — the refusal sentence, one sentence with JSON quotes', py.parse_now.filter(bit).map(msgOf), nd.parse_now.filter(bit).map(msgOf));
    lit('parseNow — the refusal sentence', refusals, py.parse_now.filter(bit).map(msgOf), nd.parse_now.filter(bit).map(msgOf));
    const listStatus = { run: { ...EMPTY_REPORT, archived: ['<dir>/list_status/root/.shiftwork/archive/b.json.gz'] }, left: ['archive', 'checkpoint-a.json'] };
    same('Retention over a checkpoint whose unit status is a list skips it and archives the closed job beside it', P(py.list_status), N(nd.list_status));
    lit('Retention over a list unit status', listStatus, P(py.list_status), N(nd.list_status));
    same('Retention compacting a job cold index holding a doc with no file: the sweep goes on', py.no_file_run, nd.no_file_run);
    lit('Retention over a doc with no file', EMPTY_REPORT, py.no_file_run, nd.no_file_run);
    same('searchArchived over a job cold index holding a doc with no file raises (the refusal bit)', bit(py.no_file_search), bit(nd.no_file_search));
    same('searchArchived over a doc with no file — the class raised', py.no_file_search.raised, nd.no_file_search.raised);
    lit('searchArchived over a doc with no file — the class raised', 'TypeError', py.no_file_search.raised, nd.no_file_search.raised);
    same('retention.json with a non-UTF-8 byte outside ran_at: the run is due', py.due_invalid_utf8, nd.due_invalid_utf8);
    lit('retention.json with a non-UTF-8 byte: due', true, py.due_invalid_utf8, nd.due_invalid_utf8);
    const retry = { first: [{ job: 'j', file: '.shiftwork/checkpoint-j.json', line: 1 }], retry: [] };
    same('searchArchived: an OSError in the retry after a ColdIndexError answers []', py.retry_oserror, nd.retry_oserror);
    lit('searchArchived: an OSError in the retry', retry, py.retry_oserror, nd.retry_oserror);
  } else if (section === 'lock') {
    same('lock constants', py.constants, nd.constants);
    lit('lock constants', LITERALS.lock.constants, py.constants, nd.constants);
    // #16 settled to node's answer. POSIX permission bits: Windows has no mode to compare.
    if (process.platform !== 'win32') {
      same('the permission bits of a held lock file (umask 022): 0o644, not executable', py.mode, nd.mode);
      lit('the permission bits of a held lock file (umask 022)', [true, '0o644'], py.mode, nd.mode);
    }
    // J90-1F: the wait is measured on a monotonic clock, so a stepped wall clock moves neither end.
    same('a lock wait with the wall clock stepped back 1 s / on 5 s: [held, under 1 s, at least 150 ms]', py.clock, nd.clock);
    lit('a lock wait under a stepped wall clock', [[false, true, true], [false, true, true]], py.clock, nd.clock);
  }
  return cases;
}
