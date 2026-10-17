/**
 * storage-cold — `ColdIndex` and `memory_recall(include_archived)` (#204, S3; job69 J69-5),
 * Python against Node.
 *
 * THE PROPERTY: given the same docs, the two runtimes write the same cold index BYTES — every
 * segment, every one of the 16 term-hash shards, and the manifest with its wall-clock `created`
 * masked — answer the same `query` (name, owning segment, summed tf), open only the shards the
 * query's terms hash to, compact to the same answers, and refuse a corrupt index the same way.
 * Over a store, `Memory.recall_outcome(include_archived=…)` gives the same reply with the flag
 * off (today's reply) and on (archived hits after live ones, tagged `[archived]`), and leaves
 * the same cold index behind it as facts move in and out of `archive/`.
 *
 * HOW. Each side runs the same op script over its own bed (`ref/storage_ref.py`'s
 * `storage-cold` section; `runNode` below against `dist/`). File mtimes in a store bed are
 * pinned to whole seconds, so a doc's `mtime_ns` is the same on both sides; archive and
 * restore are renames and keep them.
 *
 * THE LITERALS. A change made on both sides leaves every differential green, so four answers
 * are pinned per side: the query after compaction, the shards a query opens (derived from the
 * hot index's `shardOf`, not from the cold index), the flag-on reply, and the flag-off reply
 * equal to the reply with no flag at all.
 */
import { mkdirSync, readFileSync, readdirSync, utimesSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'storage-cold';
export const summary = 'ColdIndex: segment/shard/manifest bytes, query, compact, include_archived recall';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'storage_ref.py');
const T0 = 1_700_000_000;
const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');

const doc = (name, description, keywords = [], file = `${name}.md`) => ({
  file,
  name,
  description,
  type: 'project',
  keywords,
  links: [],
  tags: [],
  refs: [],
  mtime_ns: '1700000000000000000',
  size: 42,
});
const DOCS1 = Object.fromEntries(
  [
    doc('a', 'release tag', ['ปล่อยเวอร์ชัน']),
    doc('b', 'tag only'),
    doc('__proto__', 'proto key 😀 release'),
    doc('constructor', 'constructor release tag tag'),
  ].map((d) => [d.name, d]),
);
const DOCS2 = Object.fromEntries([doc('a', 'renamed words'), doc('c', 'release notes ไทย')].map((d) => [d.name, d]));
const TERMS = ['release', 'tag', 'renamed', 'ปล', 'ไท', '😀', 'missing', 'constructor', '__proto__'];

const fact = (n, description, body = 'body', extra = '') =>
  `---\nname: ${n}\ndescription: ${description}\ntype: project\ncreated: '2026-10-01'\n` +
  `last_recalled: null\nlinks: []\n${extra}---\n\n${body}\n`;

const STORE_FILES = [
  ['facts/live-release.md', fact('live-release', 'release tag lessons', 'live')],
  ['facts/other.md', fact('other', 'unrelated words', 'x')],
  ['archive/old-release.md', fact('old-release', 'old release tag notes', 'old')],
  ['archive/old-two.md', fact('old-two', 'second archived ไทย note', 'two', 'keywords:\n- ปล่อย\n')],
  ['archive/bad.md', '---\nname: bad\ntype: project\n---\n\nno description\n'],
];

const op = (o, extra = {}) => ({ op: o, ...extra });

function scenarios(shardOf) {
  const shardFile = (t) => `shard-${String(shardOf(t)).padStart(2, '0')}.json`;
  return [
    {
      label: 'cold: add, query, shadow, compact, corrupt, reset',
      ops: [
        op('query', { terms: TERMS }),
        op('add', { docs: DOCS1 }),
        op('files'),
        op('query', { terms: TERMS }),
        op('opens', { terms: ['release', 'tag', 'missing'] }),
        op('add', { docs: DOCS2 }),
        op('query', { terms: TERMS }),
        op('docs'),
        op('files'),
        op('compact'),
        op('query', { terms: TERMS }),
        op('files'),
        op('compact'),
        op('corrupt', { file: shardFile('release'), text: '{not json' }),
        op('query', { terms: ['release'] }),
        op('query', { terms: ['words'] }),
        op('corrupt', { file: 'manifest.json', text: '{"version":2,"segments":[]}' }),
        op('query', { terms: ['words'] }),
        op('reset'),
        op('files'),
        op('query', { terms: TERMS }),
        op('add', { docs: DOCS2 }),
        op('files'),
      ],
    },
    {
      label: 'store: memory_recall include_archived over a moving archive/',
      store: true,
      ops: [
        op('mem', { query: 'release tag', flag: false }),
        op('mem', { query: 'release tag', flag: true }),
        op('memfiles'),
        op('mem', { query: 'release tag', flag: true }),
        op('mem', { query: 'old notes', flag: true }),
        op('mem', { query: 'ไทย ปล่อย', flag: true }),
        op('mem', { query: 'no description', flag: true }),
        op('mem', { query: 'old-release', flag: true }),
        op('mem', { query: 'release-tag', flag: true }),
        op('mem', { query: '', flag: true }),
        op('restore', { name: 'old-release' }),
        op('mem', { query: 'old notes', flag: true }),
        op('archive', { name: 'other' }),
        op('mem', { query: 'unrelated', flag: true }),
        op('memfiles'),
        op('write', { rel: 'archive/old-two.md', b64: b64(fact('old-two', 'rewritten archived note', 'two-b')), mtime: T0 + 50 }),
        op('mem', { query: 'rewritten', flag: true }),
        op('mem', { query: 'ไทย', flag: true }),
        op('memfiles'),
        op('mem', { query: 'release tag', flag: false }),
      ],
    },
  ];
}

// --------------------------------------------------------------------- the Node half

function filesOf(d) {
  let names;
  try {
    names = readdirSync(d)
      .filter((n) => !n.endsWith('.lock'))
      .sort();
  } catch {
    return [];
  }
  return names.map((n) => [n, readFileSync(join(d, n)).toString('base64')]);
}

function runNode(storage, memory, component, bed) {
  const before = process.env.BANTAMKIT_INDEX_DIR;
  process.env.BANTAMKIT_INDEX_DIR = bed.index_dir;
  try {
    const cold = new storage.ColdIndex('t', bed.home);
    const out = [];
    for (const o of bed.ops) {
      switch (o.op) {
        case 'add':
          out.push(cold.add(new Map(Object.entries(o.docs))));
          break;
        case 'query':
          try {
            out.push(cold.query(o.terms));
          } catch (e) {
            if (!(e instanceof storage.ColdIndexError)) throw e;
            out.push({ error: 'ColdIndexError' });
          }
          break;
        case 'opens': {
          const opened = [];
          const real = storage.coldFs.readFileSync;
          storage.coldFs.readFileSync = (p) => {
            const n = p.split(/[/\\]/).pop();
            if (n.startsWith('shard-')) opened.push(n);
            return real(p);
          };
          try {
            cold.query(o.terms);
          } finally {
            storage.coldFs.readFileSync = real;
          }
          out.push(opened);
          break;
        }
        case 'docs': {
          const d = cold.docs();
          out.push([...d.keys()].sort(cmpCp).map((k) => [k, d.get(k)]));
          break;
        }
        case 'compact':
          out.push(cold.compact());
          break;
        case 'reset':
          cold.reset();
          out.push(null);
          break;
        case 'files':
          out.push(filesOf(cold.dir));
          break;
        case 'corrupt':
          writeFileSync(join(cold.dir, o.file), o.text, 'utf8');
          out.push(null);
          break;
        case 'write': {
          const p = join(bed.root, o.rel);
          mkdirSync(dirname(p), { recursive: true });
          writeFileSync(p, Buffer.from(o.b64, 'base64'));
          utimesSync(p, o.mtime, o.mtime);
          out.push(null);
          break;
        }
        case 'archive':
        case 'restore': {
          const store = new memory.MemoryStore(bed.root, { create: false, today: () => '2026-10-15' });
          try {
            store[o.op](o.name);
            out.push(null);
          } catch (e) {
            out.push({ error: e.constructor.name });
          }
          break;
        }
        case 'mem': {
          const m = new component.Memory(bed.root);
          const r = m.recallOutcome(o.query, o.k ?? null, undefined, false, o.flag);
          out.push({ reply: r.reply, status: r.status, returned: r.returned });
          break;
        }
        case 'memfiles':
          out.push(filesOf(new memory.MemoryStore(bed.root, { create: false }).cold().dir));
          break;
        default:
          throw new Error(`unknown op: ${o.op}`);
      }
    }
    return out;
  } finally {
    if (before === undefined) delete process.env.BANTAMKIT_INDEX_DIR;
    else process.env.BANTAMKIT_INDEX_DIR = before;
  }
}

const cmpCp = (a, b) => {
  const x = [...a];
  const y = [...b];
  for (let i = 0; i < Math.min(x.length, y.length); i += 1) {
    const d = x[i].codePointAt(0) - y[i].codePointAt(0);
    if (d) return d;
  }
  return x.length - y.length;
};

/** `files` with each manifest's wall-clock `created` masked, decoded for a readable diff. */
const maskFiles = (rows) =>
  rows.map(([n, data]) => [n, Buffer.from(data, 'base64').toString('utf8').replace(/"created":"[^"]*"/g, '"created":"<created>"')]);

const literalCases = (pySide, nodeSide, label, expected) => [
  { name: `${label} — python`, kind: 'json', expected, actual: pySide },
  { name: `${label} — node`, kind: 'json', expected, actual: nodeSide },
];

// constructor: name 1 + `constructor release tag tag` 1+1+2; c: release + ไท; the rest one term
// each, tied and so in code-point order (`_` before `a`). `a` scores `renamed`, its NEWEST text.
const AFTER_COMPACT = [
  ['constructor', 5],
  ['c', 2],
  ['__proto__', 1],
  ['a', 1],
  ['b', 1],
];
const FLAG_ON =
  '[live-release] (project) release tag lessons\nlive\n\n[archived] [old-release] (project) old release tag notes\nold';

// ------------------------------------------------------------------------------- run

/**
 * HOME is this suite's own scratch home for the whole run (#199, J68-5): a stamping `lookup` or
 * `recall` appends to the usage ledger under `~/.bantamkit/usage/`, and the harness does not move
 * HOME. The reference children inherit it (`runPython` spreads `process.env`).
 */
export async function run(ctx) {
  const was = [process.env.HOME, process.env.USERPROFILE];
  const home = join(ctx.scratch, 'storage-cold-home');
  mkdirSync(home, { recursive: true });
  process.env.HOME = home;
  process.env.USERPROFILE = home;
  try {
    return await runIn(ctx);
  } finally {
    for (const [k, v] of [['HOME', was[0]], ['USERPROFILE', was[1]]]) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

async function runIn(ctx) {
  const storage = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'storage', 'index.js')).href);
  const memory = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'store.js')).href);
  const component = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'component.js')).href);
  const cases = [];
  const all = scenarios(storage.shardOf);
  const beds = { py: [], node: [] };
  all.forEach((s, i) => {
    for (const side of ['py', 'node']) {
      const base = join(ctx.scratch, `storage-cold-${String(i + 1).padStart(2, '0')}`, side);
      const root = join(base, 'store');
      mkdirSync(join(base, 'home'), { recursive: true });
      mkdirSync(join(root, 'facts'), { recursive: true });
      mkdirSync(join(root, 'archive'), { recursive: true });
      if (s.store) {
        STORE_FILES.forEach(([rel, text], k) => {
          const p = join(root, rel);
          writeFileSync(p, text, 'utf8');
          utimesSync(p, T0 + k, T0 + k);
        });
      }
      beds[side].push({ home: join(base, 'home'), root, index_dir: join(base, 'idx'), ops: s.ops });
    }
  });
  const py = ctx.runPython(REF, { suite: 'storage-cold', beds: beds.py });
  const nd = { beds: beds.node.map((bed) => runNode(storage, memory, component, bed)) };

  const norm = (o, v) => (o.op === 'files' || o.op === 'memfiles' ? maskFiles(v) : v);
  all.forEach((s, i) => {
    s.ops.forEach((o, j) => {
      const what = `${o.op}${o.query !== undefined ? ` ${JSON.stringify(o.query)}${o.flag ? ' +archived' : ''}` : ''}${o.name ? ` ${o.name}` : ''}${o.file ? ` ${o.file}` : ''}`;
      cases.push({
        name: `${s.label} — #${String(j).padStart(2, '0')} ${what}`,
        kind: 'json',
        expected: norm(o, py.beds[i][j]),
        actual: norm(o, nd.beds[i][j]),
      });
    });
  });

  // ------------------------------------------------------------------- the literals
  const sideOf = (side) => (side === 'py' ? py : nd);
  const at = (i, pred, nth = 0) => all[i].ops.map((o, j) => [o, j]).filter(([o]) => pred(o))[nth][1];
  const afterCompact = at(0, (o) => o.op === 'query', 3);
  const strip = (rows) => (Array.isArray(rows) ? rows.map(([n, , tf]) => [n, tf]) : rows);
  cases.push(
    ...literalCases(
      strip(py.beds[0][afterCompact]),
      strip(nd.beds[0][afterCompact]),
      'LITERAL: the query after compaction (shadowed `a` scores its newest version)',
      AFTER_COMPACT,
    ),
  );
  const opensAt = at(0, (o) => o.op === 'opens');
  const wantOpens = [...new Set(['release', 'tag', 'missing'].map((t) => storage.shardOf(t)))]
    .sort((a, b) => a - b)
    .map((n) => `shard-${String(n).padStart(2, '0')}.json`);
  cases.push(
    ...literalCases(py.beds[0][opensAt], nd.beds[0][opensAt], 'LITERAL: a query opens exactly the shards its terms hash to, in order', wantOpens),
  );
  const flagOn = at(1, (o) => o.op === 'mem' && o.flag);
  const flagOff = at(1, (o) => o.op === 'mem' && !o.flag);
  for (const side of ['py', 'node']) {
    const label = side === 'py' ? 'python' : 'node';
    cases.push({
      name: `LITERAL: include_archived puts the archived hit after the live one, tagged — ${label}`,
      kind: 'json',
      expected: { reply: FLAG_ON, status: 'answered', returned: 2 },
      actual: sideOf(side).beds[1][flagOn],
    });
    cases.push({
      name: `LITERAL: without the flag no archived fact is read — ${label}`,
      kind: 'json',
      expected: { reply: '[live-release] (project) release tag lessons\nlive', status: 'answered', returned: 1 },
      actual: sideOf(side).beds[1][flagOff],
    });
  }
  return { cases, notes: [`${all.length} scripted scenarios, ${all.reduce((n, s) => n + s.ops.length, 0)} ops per side`] };
}
