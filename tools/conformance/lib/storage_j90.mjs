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
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, symlinkSync, unlinkSync, utimesSync, writeFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
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

/** J90-3F: `[name, 'old' | 'fresh' | 'olddir']` planted in `dir`; an old one dated `T` (2023). */
function plantTemps(dir, list) {
  for (const [n, age] of list) {
    const p = join(dir, n);
    if (age === 'olddir') mkdirSync(p);
    else writeFileSync(p, 'partial');
    if (age !== 'fresh') utimesSync(p, T, T);
  }
}
const COLD_TEMPS = [
  ['shard-03.json.4242.tmp', 'old'], ['seg-000009.json.17.tmp', 'old'], ['manifest.json.4243.tmp', 'fresh'],
  ['notes.txt.4242.tmp', 'old'], ['shard-03.json.x1.tmp', 'old'], ['shard-03.json.tmp', 'old'],
  ['manifest.json.99.tmp', 'olddir'],
];

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
    // J90-P3: segments as a shard's JSON reads them, malformed ways included (the strided copy's
    // guard fails on each, and the general loop answers); the same texts in storage_ref.py.
    decode_json: DECODE_JSON.map((text) => attempt(() => h.decodeSegments(['a', 'b', 'c'], JSON.parse(text)))),
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
  // J90-3F: a persist removes its own index's temps a killed writer left, once stale, and no other
  // index's (named `<sha>` here: the hash is of each side's own path).
  [root, home] = bed('temps', 'facts', facts.slice(0, 2));
  hi = new h.HotIndex(root, 'facts', home);
  hi.refresh('fast');
  {
    const dir = dirname(hi.path);
    const head = basename(hi.path);
    const sha = head.slice(0, -5);
    plantTemps(dir, [
      [`${head}.31.tmp`, 'old'], [`${sha}.postings-00.json.32.tmp`, 'old'], [`${head}.33.tmp`, 'fresh'],
      ['0000000000000000.json.34.tmp', 'old'], [`${sha}.txt.35.tmp`, 'old'],
    ]);
    writeFileSync(join(root, 'facts', 'gamma.md'), FACT('gamma', 'gamma word'), 'utf8');
    const again = new h.HotIndex(root, 'facts', home);
    again.refresh('full');
    out.temps = {
      left: readdirSync(dir).filter((n) => n.endsWith('.tmp')).map((n) => n.split(sha).join('<sha>')).sort(),
      names: [...again.names().keys()],
    };
  }
  // J90-P7B: a write reuses the second line only when it is the text this process wrote there (a
  // full refresh that changed nothing then writes it again, undumped); one read back in another
  // spelling is dumped again, and a patch dumps the docs it changed.
  [root, home] = bed('tail', 'facts', facts.slice(0, 2));
  hi = new h.HotIndex(root, 'facts', home);
  hi.refresh('fast');
  {
    const line2 = () => readFileSync(hi.path, 'utf8').split('\n')[1];
    const canon = line2();
    const full = () => {
      const x = new h.HotIndex(root, 'facts', home);
      x.refresh('full');
      return x;
    };
    full();
    const again = line2() === canon;
    const raw = readFileSync(hi.path, 'utf8');
    const cut = raw.indexOf('\n') + 1;
    writeFileSync(hi.path, `${raw.slice(0, cut)}${raw.slice(cut).replace('"df":{', '"df": {')}`, 'utf8');
    const spaced = line2() !== canon;
    full();
    const respelled = line2() === canon;
    writeFileSync(join(root, 'facts', 'beta.md'), FACT('beta', 'beta words moved'), 'utf8');
    const moved = full();
    out.tail = { again, spaced, respelled, patched: line2() !== canon, beta: moved.doc('beta')?.description ?? null };
  }
  // J90-RF (F1): the reuse is keyed on the TEXT this process wrote, not on the path. Process A writes
  // the second line T; another process writes T2 at the same path (a fact moved); A refreshes full
  // and finds nothing moved since T2, so it writes T2 again, never its own stale T. A new reader in
  // a third process is then served T2's doc (red under "reuse whenever this path was ever written").
  [root, home] = bed('stale', 'facts', facts.slice(0, 2));
  {
    const mod = JSON.stringify(pathToFileURL(join(runtimeTs, 'dist', 'storage', 'hotindex.js')).href);
    const open = `const h = await import(${mod}); const x = new h.HotIndex(${JSON.stringify(root)}, 'facts', ${JSON.stringify(home)});`;
    const other = (body) => execFileSync(process.execPath, ['--input-type=module', '-e', `${open} ${body}`], { encoding: 'utf8' }).trim();
    new h.HotIndex(root, 'facts', home).refresh('full');
    writeFileSync(join(root, 'facts', 'beta.md'), FACT('beta', 'beta words another process wrote'), 'utf8');
    other("x.refresh('full');");
    const a = new h.HotIndex(root, 'facts', home);
    const aRefresh = a.refresh('full');
    const reader = JSON.parse(other(
      "const d = () => x.doc('beta')?.description ?? null; const before = d(); const r = x.refresh('fast'); console.log(JSON.stringify([before, r, d()]));",
    ));
    out.stale = { a_refresh: aRefresh, a_beta: a.doc('beta')?.description ?? null, reader };
  }
  // J90-RF (F3): a head whose doc holds an integer past 2^53 (a hand edit; no writer makes one) is
  // read as JSON.parse reads it (2^53, not safe) and written back by the patch as `fromJs` lifts it:
  // a float, `9007199254740992.0`. Red when the lift's safe-int guard (`_js_lift_ints_safe`) passes
  // every int: the generated Python then hands 2^53 to `json.dumps` as an int.
  [root, home] = bed('unsafe', 'facts', facts.slice(0, 2));
  {
    const first = new h.HotIndex(root, 'facts', home);
    first.refresh('fast');
    const raw = readFileSync(first.path, 'latin1');
    writeFileSync(first.path, raw.replace(/("beta":\{[^}]*?"size":)(\d+)/, '$19007199254740993'), 'latin1');
    writeFileSync(join(root, 'facts', 'gamma.md'), FACT('gamma', 'gamma word'), 'utf8');
    const x = new h.HotIndex(root, 'facts', home);
    const refresh = x.refresh('full');
    const m = readFileSync(x.path, 'utf8').split('\n')[1].match(/"beta":\{[^}]*?"size":([^,}]+)/);
    out.unsafe = { refresh, written: m ? m[1] : null, names: [...x.names().keys()] };
  }
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
  // J90-3: a path BELOW the dangling link, and the live directory spelled in another case (a
  // case-insensitive filesystem resolves it to the spelling on disk; a case-sensitive one has none).
  out.symlinks = {
    dangle: named('dangle', 'missing-target'),
    live: named('live', 'real'),
    below: named('dangle/sub', 'missing-target/sub'),
    cased: named('REAL', 'real'),
    folds: existsSync(join(d, 'links', 'REAL')),
  };
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
    ci.addDocs(new Map([['alpha', doc('alpha', 'word one')], ['beta', doc('beta', 'word two')]]));
    ci.addDocs(new Map([['alpha', doc('alpha', 'word newer')]]));
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
  // J90-RF (F5, migration entry 2): a name's tf rows summed as doubles once the sum is past 2^53:
  // a hand-edited row of 9007199254740993 (read as JSON.parse reads it, 2^53) plus a row of 1
  // scores 9007199254740992 (0.40.0's Python read the row exactly and answered ...994).
  ci = fresh('tf_big');
  for (let i = 0; i < 16; i += 1) {
    const p = ci.shardPath(i);
    const raw = readFileSync(p, 'utf8');
    if (raw.includes('"two"')) writeFileSync(p, raw.replace('"two":[["beta","000001","description",1]]', '"two":[["beta","000001","description",9007199254740993]]'));
  }
  // Each score as its exact integer in decimal: a JSON number past 2^53 would be rounded by the
  // harness's own JSON.parse of the reference's answer, and hide an exact Python int.
  out.tf_big = ci.query(['word', 'two']).map(([n, seg, score]) => [n, seg, BigInt(score).toString()]);
  out.version_true = run('version_true', (x) => sub(x.manifestPath, '"version":1', '"version":true'));
  out.id_newline = run('id_newline', (x) => sub(x.manifestPath, '"id":"000002"', '"id":"000002\\n"'));
  out.seg_invalid_utf8 = run('seg_invalid_utf8', (x) =>
    sub(x.segmentPath('000001'), '"word two"', Buffer.concat([Buffer.from('"word tw'), Buffer.from([0xff]), Buffer.from('"')])),
  );
  // J90-3: the sentence a ColdIndexError quotes for a read that failed (`coldErrorText`): a
  // manifest that is not JSON, a segment that is not UTF-8, a segment that is gone.
  ci = fresh('msg_syntax');
  writeFileSync(ci.manifestPath, '{not json');
  const syntax = attempt(() => ci.manifest());
  ci = fresh('msg_utf8');
  sub(ci.segmentPath('000001'), '"word two"', Buffer.concat([Buffer.from('"word tw'), Buffer.from([0xff]), Buffer.from('"')]));
  const utf8 = attempt(() => ci.segment('000001'));
  ci = fresh('msg_gone');
  unlinkSync(ci.segmentPath('000001'));
  const gone = attempt(() => ci.segment('000001'));
  // J90-3F: a segment and a shard that are not JSON (one sentence, no parser's wording).
  ci = fresh('msg_seg_syntax');
  writeFileSync(ci.segmentPath('000001'), '{not json');
  const segSyntax = attempt(() => ci.segment('000001'));
  ci = fresh('msg_shard_syntax');
  for (let i = 0; i < 16; i += 1) writeFileSync(ci.shardPath(i), '[1,');
  const shardSyntax = attempt(() => ci.query(['word']));
  out.messages = { syntax, utf8, gone, seg_syntax: segSyntax, shard_syntax: shardSyntax };
  // J90-3F: the temps a killed writer left (`<file>.<pid>.tmp`): a write removes its own once older
  // than the lock's stale window, and nothing else (a fresh one, another file's, no pid, a dir).
  ci = fresh('temps');
  const temps = () => readdirSync(ci.dir).filter((n) => n.endsWith('.tmp')).sort();
  plantTemps(ci.dir, COLD_TEMPS);
  const before = temps();
  ci.addDocs(new Map([['gamma', doc('gamma', 'word three')]]));
  const add = temps();
  plantTemps(ci.dir, [['seg-000001.json.18.tmp', 'old']]);
  const compacted = ci.compact();
  out.temps = { before, add, compact: temps(), compacted, query: ci.query(['word']) };
  // J90-P7B: a shard read again is parsed again unless its text is the one last parsed: a rewrite
  // of the same length (a tf of 1 made 2) is read as written, and the old bytes back as before.
  ci = fresh('reparse');
  const q1 = ci.query(['word']);
  const at = [...Array(16).keys()].map((i) => ci.shardPath(i)).find((p) => readFileSync(p, 'utf8').includes('"word"'));
  const kept = readFileSync(at);
  sub(at, '"word":[["alpha","000001","description",1],["beta","000001","description",1]', '"word":[["alpha","000001","description",1],["beta","000001","description",2]');
  const same = readFileSync(at).length === kept.length;
  const q2 = ci.query(['word']);
  writeFileSync(at, kept);
  out.reparse = { q1, same, q2, q3: ci.query(['word']) };
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
    ci.addDocs(new Map([['j', doc]]));
    ci.addDocs(new Map([['k', { ...doc, name: 'k', file: '.shiftwork/archive/k.json.gz' }]]));
    out.no_file_run = attempt(() => r.runRetention(home, [root], now));
    out.no_file_search = attempt(() => r.searchArchived(join(root, '.shiftwork', 'checkpoint.json'), 'x', home));
    // J90-RF (F4): compaction keeps a job doc while `path.join(root, file)` is a file, so an
    // ABSOLUTE `file` names a path under the root, not the absolute file; 0.40.0's Python joined
    // with `Path /` (the absolute path wins) and kept those docs. Both runtimes now drop them.
    [home, root] = bed('abs_file');
    writeFileSync(join(root, 'real.json'), '{}');
    const outside = join(d, 'abs_file', 'outside.json');
    writeFileSync(outside, '{}');
    {
      const cold = r.shiftworkCold(home, root);
      const jdoc = (name, file) => ({
        name, description: 'alpha', file, type: 'project', keywords: [], links: [], tags: [], refs: [], mtime_ns: '1', size: 1,
      });
      cold.addDocs(new Map([['a', jdoc('a', outside)], ['b', jdoc('b', 'real.json')], ['c', jdoc('c', 'gone.json')],
        ['d', jdoc('d', '../root/real.json')], ['f', jdoc('f', join(root, 'real.json'))]]));
      cold.addDocs(new Map([['e', jdoc('e', 'real.json')]]));
      const ran = attempt(() => r.runRetention(home, [root], now));
      out.abs_file = {
        compacted: ran && Array.isArray(ran.compacted) ? ran.compacted.length : ran,
        names: r.shiftworkCold(home, root).query(['alpha']).map((x) => x[0]).sort(),
      };
    }
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
    // J90-3F: a run removes the archive and state temps a killed run left, once stale, and
    // nothing else (a fresh one, a name it does not write, no pid).
    [home, root] = bed('temps');
    plantTemps(join(root, '.shiftwork', 'archive'), [
      ['old.json.gz.4242.tmp', 'old'], ['new.json.gz.4243.tmp', 'fresh'], ['notes.md.4242.tmp', 'old'], ['x.json.gz.12a.tmp', 'old'],
    ]);
    plantTemps(join(home, '.bantamkit'), [
      ['retention.json.77.tmp', 'old'], ['retention.json.78.tmp', 'fresh'], ['other.json.79.tmp', 'old'],
    ]);
    const tmpsIn = (x) => readdirSync(x).filter((n) => n.endsWith('.tmp')).sort();
    out.temps = {
      run: attempt(() => r.runRetention(home, [root], now)),
      archive: tmpsIn(join(root, '.shiftwork', 'archive')),
      state: tmpsIn(join(home, '.bantamkit')),
    };
    // J90-3: the opt-out switch read through JS `trim` (generation settles 743b54b9's Python
    // `strip`, which also strips U+001C..U+001F and U+0085 and keeps U+FEFF).
    out.env_switch = ['off\u001c', '\u0085off', '\ufeffoff', ' OFF\t', 'off\u3000'].map((v) => {
      process.env[r.RETENTION_ENV] = v;
      return r.enabled();
    });
    process.env[r.RETENTION_ENV] = 'on';
    // J90-3: the error a failed sweep records names the JS class (743b54b9's Python: `ValueError`).
    const m = await import(pathToFileURL(join(runtimeTs, 'dist', 'storage', 'retentionmain.js')).href);
    const audit = process.env[r.SKILL_AUDIT_ENV];
    process.env[r.SKILL_AUDIT_ENV] = 'off';
    [home, root] = bed('child_error');
    const code = await m.childMain([root, home], '2026-10-16T00:00:00.000Zx');
    out.child_error = [code, JSON.parse(readFileSync(r.statePath(home), 'utf8')).error ?? null];
    // J90-3F: an audit that throws something that is not an fs error: the child still exits 0 and
    // the sweep before it is recorded (the shim's `child_main` let all but an OSError out).
    process.env[r.SKILL_AUDIT_ENV] = 'on';
    [home, root] = bed('child_audit');
    const realDaily = m.childAudit.daily;
    m.childAudit.daily = () => {
      throw new TypeError('audit broke');
    };
    let audited;
    try {
      audited = await m.childMain([root, home], now);
    } catch (e) {
      audited = { raised: e?.constructor?.name ?? 'Error', msg: String(e?.message ?? e) };
    } finally {
      m.childAudit.daily = realDaily;
    }
    const st = JSON.parse(readFileSync(r.statePath(home), 'utf8'));
    out.child_audit = [audited, 'report' in st, st.error ?? null];
    process.env[r.SKILL_AUDIT_ENV] = 'off';
    if (audit === undefined) delete process.env[r.SKILL_AUDIT_ENV];
    else process.env[r.SKILL_AUDIT_ENV] = audit;
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

/** J90-P3: segment texts for `decodeSegments` (storage_ref.py holds the same list). */
const DECODE_JSON = ['[-0,1,1,0,0]', '[0,1,2.0,0,0]', '[0,1,1.5,0,0]', '[9007199254740993,1,1,0,0]', '[0,"1",1,0,0]', '[0,1,null,0,0]', '[0,1,1,0]', '[0,4,1,0,0]', '[1e400,1,1,0,0]', '[0,1,1,0,0,1,1,0,0,2]', '[0,1,true,0,0]', '[-1,1,1,0,0]', '[0,0,1,0,0]', '[0,3,1,-1,2,1,2,0,0,5]', '"x"', '{}', '[]'];
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

/** J90-3F: the shard `word` hashes to, and the cold `temps` probe's answer. */
const COLD_WORD_SHARD = '14';
const COLD_TEMPS_AFTER = {
  before: ['manifest.json.4243.tmp', 'manifest.json.99.tmp', 'notes.txt.4242.tmp', 'seg-000009.json.17.tmp', 'shard-03.json.4242.tmp', 'shard-03.json.tmp', 'shard-03.json.x1.tmp'],
  add: ['manifest.json.4243.tmp', 'manifest.json.99.tmp', 'notes.txt.4242.tmp', 'shard-03.json.tmp', 'shard-03.json.x1.tmp'],
  compact: ['manifest.json.4243.tmp', 'manifest.json.99.tmp', 'notes.txt.4242.tmp', 'shard-03.json.tmp', 'shard-03.json.x1.tmp'],
  compacted: '000004',
  query: [['alpha', '000004', 1], ['beta', '000004', 1], ['gamma', '000004', 1]],
};

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
    same('decodeSegments of JSON-read segments, malformed ones too (J90-P3: each answer, the bit and the sentence)', py.units.decode_json.map((v) => [bit(v), msgOf(v)]), nd.units.decode_json.map((v) => [bit(v), msgOf(v)]));
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
    // J90-2 found, J90-3 settled (the orchestrator's ruling: Node's answer): through a dangling
    // symlink the reference's `os.path.realpath` followed the link to its missing target where
    // `nodeRealpath` keeps the link as spelled. The `nodeRealpath` adapter is now Node's function
    // (`realpath(3)`, the parent on a throw), so both name the source's index (`sha16`) and its
    // head's `source` by the link; was `ruling: UNRULED DIVERGENCE (J90-2)` with python
    // `['missing-target', true]`.
    same('J90-3 a source through a dangling symlink keeps the link as spelled (realpath and sha16)', py.symlinks.dangle, nd.symlinks.dangle);
    lit('J90-3 a source through a dangling symlink keeps the link as spelled', ['dangle', false], py.symlinks.dangle, nd.symlinks.dangle);
    same('J90-3 a source below a dangling symlink keeps the path as spelled', py.symlinks.below, nd.symlinks.below);
    lit('J90-3 a source below a dangling symlink', ['sub', false], py.symlinks.below, nd.symlinks.below);
    same('J90-3 a source spelled in another case is named as the filesystem spells it', py.symlinks.cased, nd.symlinks.cased);
    lit('J90-3 a source spelled in another case', nd.symlinks.folds ? ['real', true] : ['REAL', false], py.symlinks.cased, nd.symlinks.cased);
    // J90-3F: a persist removes its own index's stale temps, no other index's (red on 2cca2564).
    same('J90-3F a hot index persist removes its own stale temps and nothing else', py.temps, nd.temps);
    lit('J90-3F a hot index persist removes its own stale temps and nothing else', {
      left: ['0000000000000000.json.34.tmp', '<sha>.json.33.tmp', '<sha>.txt.35.tmp'], names: ['alpha', 'beta', 'gamma'],
    }, py.temps, nd.temps);
    same('J90-P7B a write reuses the second line only when this process wrote that text', py.tail, nd.tail);
    lit('J90-P7B a write reuses the second line only when this process wrote that text', {
      again: true, spaced: true, respelled: true, patched: true, beta: 'beta words moved',
    }, py.tail, nd.tail);
    // J90-RF (F1): red on both sides when `completeTail` reuses whatever this process last wrote at
    // the path (`WROTE_TAIL.has`) instead of only the text it wrote: A writes its stale line back and
    // a new reader in a third process is served the old doc with a fresh head.
    const STALE = 'beta words another process wrote';
    same('J90-RF a full refresh after another process wrote the index writes that process\'s line, never its own older one', py.stale, nd.stale);
    lit('J90-RF a full refresh after another process wrote the index: a new reader is served the newer doc', {
      a_refresh: 'fresh', a_beta: STALE, reader: [STALE, 'fresh', STALE],
    }, py.stale, nd.stale);
    same('J90-RF a head doc holding an integer past 2^53 is written back as fromJs lifts it (a float)', py.unsafe, nd.unsafe);
    lit('J90-RF a head doc holding an integer past 2^53 is written back as a float', {
      refresh: 'patched', written: '9007199254740992.0', names: ['alpha', 'beta', 'gamma'],
    }, py.unsafe, nd.unsafe);
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
    same('J90-RF a cold query summing tf rows past 2^53 adds them as doubles (migration entry 2)', py.tf_big, nd.tf_big);
    lit('J90-RF a cold query summing tf rows past 2^53', [['beta', '000001', '9007199254740992'], ['alpha', '000002', '1']], py.tf_big, nd.tf_big);
    // J90-3: the sentence a ColdIndexError quotes for a failed read (`coldErrorText`, an adapter).
    // A gone segment and a segment that is not UTF-8 are worded alike (CPython's OSError and
    // decoder wording, a PyOSError / PyUnicodeDecodeError on node); the class is compared too.
    const M = py.messages;
    const N = nd.messages;
    const cls = (v) => (bit(v) ? v.raised.replace(/^_/, '') : null);
    same('J90-3 a ColdIndexError for a failed read — the class, per failure', [cls(M.syntax), cls(M.utf8), cls(M.gone)], [cls(N.syntax), cls(N.utf8), cls(N.gone)]);
    same('J90-3 a ColdIndexError for a segment that is gone — the sentence', unpath(msgOf(M.gone), dirs.py), unpath(msgOf(N.gone), dirs.nd));
    lit('J90-3 a ColdIndexError for a segment that is gone', "cold index segment 000001 unreadable: [Errno 2] No such file or directory: '<dir>/msg_gone/.bantamkit/cold/t/seg-000001.json'", unpath(msgOf(M.gone), dirs.py), unpath(msgOf(N.gone), dirs.nd));
    same('J90-3 a ColdIndexError for a segment that is not UTF-8 — the sentence', msgOf(M.utf8), msgOf(N.utf8));
    lit('J90-3 a ColdIndexError for a segment that is not UTF-8', "cold index segment 000001 unreadable: 'utf-8' codec can't decode byte 0xff in position 197: invalid start byte", msgOf(M.utf8), msgOf(N.utf8));
    // J90-3 found, J90-3F settled (the orchestrator: one shared sentence, no parser's wording): a
    // manifest, segment or shard that is not JSON quoted each runtime's own JSON parser (CPython's
    // `json` on the reference, V8 on the port), pinned `ruling: UNRULED DIVERGENCE (J90-3)` with
    // python `... unreadable: Expecting property name enclosed in double quotes: line 1 column 2
    // (char 1)` and node `... unreadable: Expected property name or '}' in JSON at position 1 (line 1
    // column 2)`. `coldindex.ts` now throws its own `COLD_NOT_JSON`.
    const notJson = (what) => `cold index ${what} unreadable: the file is not JSON`;
    const syn = (X) => [X.syntax, X.seg_syntax, X.shard_syntax].map((v) => [cls(v), msgOf(v)]);
    same('J90-3F a ColdIndexError for a manifest, segment or shard that is not JSON — one sentence, no parser wording', syn(M), syn(N));
    lit('J90-3F a ColdIndexError for a manifest, segment or shard that is not JSON', [
      ['ColdIndexError', notJson('manifest')], ['ColdIndexError', notJson('segment 000001')], ['ColdIndexError', notJson(`shard ${COLD_WORD_SHARD}`)],
    ], syn(M), syn(N));
    // J90-3F: a killed writer's `<file>.<pid>.tmp` is removed by the next write once older than the
    // lock's stale window; a fresh temp, another file's, one with no pid and a directory are kept
    // (both runtimes kept every one before: red on 2cca2564 on both sides).
    same('J90-3F a cold write removes its own stale temps and nothing else', py.temps, nd.temps);
    lit('J90-3F a cold write removes its own stale temps and nothing else', COLD_TEMPS_AFTER, py.temps, nd.temps);
    // J90-P7B: a shard is parsed again whenever its text is not the one last parsed.
    same('J90-P7B a cold shard rewritten to the same length is read as written', py.reparse, nd.reparse);
    lit('J90-P7B a cold shard rewritten to the same length is read as written', {
      q1: [['alpha', '000002', 1], ['beta', '000001', 1]], same: true,
      q2: [['beta', '000001', 2], ['alpha', '000002', 1]], q3: [['alpha', '000002', 1], ['beta', '000001', 1]],
    }, py.reparse, nd.reparse);
  } else if (section === 'retention') {
    const L = LITERALS.retention;
    same('retention constants', py.constants, nd.constants);
    lit('retention constants', L.constants, py.constants, nd.constants);
    same('parseNow — the value or the refusal bit, per input', py.parse_now.map((v) => (bit(v) ? 'refused' : v)), nd.parse_now.map((v) => (bit(v) ? 'refused' : v)));
    lit('parseNow values', L.parse_now_values, py.parse_now.slice(0, 4), nd.parse_now.slice(0, 4));
    // J90-3: found while generating retention (a difference 743b54b9 had, NOT in any case before):
    // the hand-written Python read the opt-out switch with `str.strip()`, which strips U+001C..U+001F
    // and U+0085 and keeps U+FEFF, where Node's `trim()` keeps the first five and strips U+FEFF.
    // Generation runs Node's `trim` on both sides; these pin that answer per side (743b54b9's
    // Python answered [false, false, true, false, false]).
    // J90-3F: retention removes the archive and `retention.json` temps a killed run left, once
    // stale, and reports them deleted (red on 2cca2564 on both sides: every temp stayed).
    same('J90-3F a run removes the stale archive and state temps it owns, and nothing else', P(py.temps), N(nd.temps));
    lit('J90-3F a run removes the stale archive and state temps it owns, and nothing else', {
      run: { ...EMPTY_REPORT, deleted: ['<dir>/temps/home/.bantamkit/retention.json.77.tmp', '<dir>/temps/root/.shiftwork/archive/old.json.gz.4242.tmp'] },
      archive: ['new.json.gz.4243.tmp', 'notes.md.4242.tmp', 'x.json.gz.12a.tmp'],
      state: ['other.json.79.tmp', 'retention.json.78.tmp'],
    }, P(py.temps), N(nd.temps));
    // J90-3F: an audit that raises what is not an OSError costs neither the child's exit nor the
    // sweep's record (the shim's `child_main` caught only OSError: red on 2cca2564's Python).
    same('J90-3F an audit that throws a TypeError: the child exits 0 and the sweep is recorded', py.child_audit, nd.child_audit);
    lit('J90-3F an audit that throws a TypeError', [0, true, null], py.child_audit, nd.child_audit);
    same('J90-3 a failed sweep records the error by its JS class', py.child_error, nd.child_error);
    lit('J90-3 a failed sweep records the error by its JS class', [0, 'Error'], py.child_error, nd.child_error);
    same('J90-3 the BANTAMKIT_RETENTION switch is read through JS trim', py.env_switch, nd.env_switch);
    lit('J90-3 the BANTAMKIT_RETENTION switch is read through JS trim', [true, true, false, false, false], py.env_switch, nd.env_switch);
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
    // J90-RF (F4): Node's answer (docs/porting.md, the J90-3 section); 0.40.0's Python kept a and f.
    same('J90-RF compaction drops a job doc whose file is absolute (joined under the root, as path.join joins)', py.abs_file, nd.abs_file);
    lit('J90-RF compaction drops a job doc whose file is absolute', { compacted: 1, names: ['b', 'd', 'e'] }, py.abs_file, nd.abs_file);
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
