/**
 * J90-1 (#316 G4 prep): the Node side of `ref/storage_ref.py`'s `storage-j90` section, op for
 * op. Each owning suite (`storage-index`, `storage-cold`, `storage-retention`, `storage-lock`)
 * calls `j90(ctx, section)`, which runs the reference and this module over two scratch
 * directories and answers `{ py, nd }`; the suite decides which answers are compared and which
 * are pinned as `UNRULED DIVERGENCE`. Change one side, change both.
 *
 * A raise is the answer `{ raised: <class>, msg: <sentence> }` on both sides.
 */
import { mkdirSync, readFileSync, readdirSync, statSync, utimesSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

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
    size: hi.size(),
    exists: hi.exists(),
    head_print: JSON.parse(hi.headPrint()).shards,
    unchecked: [...hi.docsUnchecked().keys()].sort(),
    parse_file: pf('beta.md'),
    parse_file_loose: pf('loose.md'),
    parse_file_gone: pf('gone.md'),
  };
  hi.invalidate();
  out.reads.after_invalidate = [hi.exists(), hi.size()];
  const all = [...h.HEAD_KEYS, ...h.TAIL_KEYS];
  out.units = {
    decode: h.decodeSegments(['a', 'b', 'c'], [0, 2, 1, 0, 3, 2, 1, 0, 0, 1]),
    decode_bad: attempt(() => h.decodeSegments(['a'], [0, 2, 1, 0, 0])),
    encode: h.encodeSegments([[0, 1, 0, 0], [1, 1, 0, 0], [2, 0, 2, 0], [4, 0, 2, 0]]),
    head_text: h.headText(Object.fromEntries(all.map((k) => [k, k]))),
    constants: [h.INDEX_VERSION, h.FULL_REFRESH_EVERY_S, h.SHARDS, [...h.FAMILIES], [...h.HEAD_KEYS], [...h.TAIL_KEYS], h.SEG, h.DUPLICATE, h.INDEX_DIR_ENV],
  };
  for (const mode of ['lens_total_float', 'full_at_lower', 'shard_invalid_utf8', 'shard_seg_float']) {
    [root, home] = bed(mode, 'facts', facts.slice(0, 2));
    hi = new h.HotIndex(root, 'facts', home);
    hi.refresh('fast');
    const p = mode.startsWith('shard') ? hi.shardPath('postings', h.shardOf('alpha')) : hi.path;
    writeFileSync(p, mangle(readFileSync(p), mode));
    const fresh = new h.HotIndex(root, 'facts', home);
    const res = {
      refresh: attempt(() => fresh.refresh('fast')),
      query: attempt(() => byKey(fresh.query(['alpha']))),
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
    return { mode, constants: [l.LOCK_WAIT_MS, l.LOCK_STALE_MS, l.LOCK_POLL_MS] };
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

const UNRULED = 'UNRULED DIVERGENCE (J90-1): not ruled in docs/porting.md and not fixed; ';
const bit = (v) => v !== null && typeof v === 'object' && !Array.isArray(v) && 'raised' in v;
const msgOf = (v) => (bit(v) ? v.msg : v);

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
  const unruled = (name, a, b, why) =>
    cases.push({ name: `ruling: UNRULED DIVERGENCE ${name}`, kind: 'json', expected: a, actual: b, ruling: UNRULED + why });
  if (section === 'index') {
    const L = LITERALS.index;
    same('HotIndex public reads (names, doc, cols, fileOf, lens, lensTotal, size, exists, headPrint, docsUnchecked, parseFile, invalidate)', P(py.reads), N(nd.reads));
    lit('HotIndex names / fileOf / size', [L.names, L.file_of, L.size], [py.reads.names, py.reads.file_of, py.reads.size], [nd.reads.names, nd.reads.file_of, nd.reads.size]);
    same('decodeSegments / encodeSegments / headText', [py.units.decode, py.units.encode, py.units.head_text], [nd.units.decode, nd.units.encode, nd.units.head_text]);
    same('decodeSegments refuses a run past the names (the bit and the sentence)', [bit(py.units.decode_bad), msgOf(py.units.decode_bad)], [bit(nd.units.decode_bad), msgOf(nd.units.decode_bad)]);
    same('hotindex constants', py.units.constants, nd.units.constants);
    lit('hotindex encodeSegments and constants', [L.encode, L.constants], [py.units.encode, py.units.constants], [nd.units.encode, nd.units.constants]);
    unruled('a head whose lens_total holds 1.0 (a float the JSON spells as an integer)', py.lens_total_float, nd.lens_total_float,
      'python rebuilds (`_is_lens` wants `int`), node reads the head as fresh (`JSON.parse` folds 1.0 to 1)');
    unruled('a head whose full_at is spelled with a lowercase t and z', py.full_at_lower, nd.full_at_lower,
      'python strptime is case-insensitive and keeps the stamp; node ISO regex refuses it, refreshes in full and rewrites the stamp');
    unruled('a postings shard with an invalid UTF-8 byte inside a term, fingerprint intact', py.shard_invalid_utf8, nd.shard_invalid_utf8,
      'python strict-decodes, refuses the shard and rebuilds (the term is found); node decodes it lossily, trusts it, and the term is LOST (python is safer)');
    unruled('a postings shard whose run length is 1.0', py.shard_seg_float, nd.shard_seg_float,
      'python `query` raises ValueError("malformed postings") out to the caller; node reads 1.0 as 1 and answers');
    unruled('a native fact whose metadata is a flow mapping ({type: user})', py.native_flow, nd.native_flow,
      'python reads native frontmatter with PyYAML and indexes it; the codec refuses a flow mapping and skips the file (#228 rules the same boundary for the native mirror, not for the hot index)');
  } else if (section === 'cold') {
    same('ColdIndex public reads (owners, allDocs, docs, doc, manifest)', py.reads, nd.reads);
    lit('ColdIndex owners / allDocs', [LITERALS.cold.owners, LITERALS.cold.all_docs], [py.reads.owners, py.reads.all_docs], [nd.reads.owners, nd.reads.all_docs]);
    same('ColdIndex refuses a name with a separator, `..` or empty (the refusal bit)', py.bad_name.map(bit), nd.bad_name.map(bit));
    unruled('the ColdIndex bad-name sentence', py.bad_name.map(msgOf), nd.bad_name.map(msgOf),
      "python quotes with repr ('a/b'), node with JSON.stringify (\"a/b\"); no caller passes a user's name today");
    unruled('a cold shard row whose tf is 1.0', py.tf_float, nd.tf_float, 'python refuses the shard (ColdIndexError), node reads 1.0 as 1 and answers');
    unruled('a cold manifest whose version is true', py.version_true, nd.version_true, 'python accepts it (True == 1), node refuses it (true !== 1)');
    unruled('a cold manifest segment id with a trailing newline', py.id_newline, nd.id_newline,
      "python's `^[0-9]{6}$` matches before a final newline and the segment's rows go unread; node refuses the manifest");
    unruled('a cold segment with an invalid UTF-8 byte', py.seg_invalid_utf8, nd.seg_invalid_utf8,
      'python refuses the segment (ColdIndexError), node decodes it lossily and returns U+FFFD in the doc');
  } else if (section === 'retention') {
    const L = LITERALS.retention;
    same('retention constants', py.constants, nd.constants);
    lit('retention constants', L.constants, py.constants, nd.constants);
    same('parseNow — the value or the refusal bit, per input', py.parse_now.map((v) => (bit(v) ? 'refused' : v)), nd.parse_now.map((v) => (bit(v) ? 'refused' : v)));
    lit('parseNow values', L.parse_now_values, py.parse_now.slice(0, 4), nd.parse_now.slice(0, 4));
    same('parseNow refuses a number (the sentence)', msgOf(py.parse_now_nonstr), msgOf(nd.parse_now_nonstr));
    unruled('parseNow — the refusal sentence', py.parse_now.filter(bit).map(msgOf), nd.parse_now.filter(bit).map(msgOf),
      "python quotes with repr and lets datetime word an impossible date ('day is out of range for month'), node writes one sentence with JSON quotes");
    unruled('Retention over a checkpoint whose unit status is a list, beside a closed job', P(py.list_status), N(nd.list_status),
      "python `_closed` raises TypeError (unhashable list) and the WHOLE sweep dies, so the closed job beside it is not archived; node skips the job and archives the other");
    unruled('Retention compacting a job cold index holding a doc with no file', py.no_file_run, nd.no_file_run,
      'python `d["file"]` raises KeyError out of run_retention (the child records an error); node swallows it inside compact');
    same('searchArchived over a job cold index holding a doc with no file raises (the refusal bit)', bit(py.no_file_search), bit(nd.no_file_search));
    unruled('searchArchived over a doc with no file — the class raised', py.no_file_search.raised, nd.no_file_search.raised, 'python KeyError, node TypeError');
    unruled('retention.json with a non-UTF-8 byte outside ran_at', py.due_invalid_utf8, nd.due_invalid_utf8,
      'python strict-decodes, fails and calls the run due; node `due` decodes lossily and calls it fresh (node `retentionLine` already decodes strictly)');
  } else if (section === 'lock') {
    same('lock constants', py.constants, nd.constants);
    lit('lock constants', LITERALS.lock.constants, py.constants, nd.constants);
    // POSIX permission bits: Windows has no mode to compare, so the pin is POSIX-only.
    if (process.platform !== 'win32') unruled('the permission bits of a held lock file (umask 022)', py.mode, nd.mode,
      "python `os.open` defaults to mode 0o777 (0o755 after the umask), node `'wx'` to 0o666 (0o644)");
  }
  return cases;
}
