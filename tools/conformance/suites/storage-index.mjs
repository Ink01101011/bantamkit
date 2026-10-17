/**
 * storage-index — `HotIndex` (#204, S3/S6; job69 J69-2), Python against Node.
 *
 * THE PROPERTY: over the same source files, the two runtimes write the same index BYTES
 * (`json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`), read back
 * the same `docs`, `postings`, `df`, `avgdl` and `skipped`, and answer the same refresh
 * result at every step of a script that builds, refreshes fast, adds a file, edits one IN
 * PLACE (missed by fast, caught by full), lets `full_at` expire, removes the file that won a
 * duplicate name, and corrupts the index four ways. The index lives in `~/.bantamkit/index/`
 * and is shared between the runtimes, so a byte one side writes is a byte the other reads.
 *
 * HOW. Each scenario's bed is written twice by this harness, once per side, at two paths,
 * with every file and directory mtime pinned to whole seconds (Node's `utimes` cannot set a
 * nanosecond exactly; whole seconds it can). The script's own writes pin their mtimes the
 * same way. Each side runs the script in its own process — `ref/storage_ref.py` against
 * `bantamkit.storage`, `runNode` below against `dist/storage/index.js` — and before anything
 * is compared the bed's path becomes `<bed>` and `full_at` (wall-clock) becomes `<full_at>`.
 *
 * WHAT THE FIXTURES ARE AIMED AT. Thai and an astral emoji written raw; facts named
 * `__proto__` and `constructor`, which an object-keyed port loses; a fact whose name and
 * description are YAML integers; wiki links with padding and repeats beside frontmatter
 * links; `tags`; the store's own refusal sentences (a missing key, a `keywords` that is not
 * a list); a duplicate name; the native shape (`metadata.type`, and `links`/`tags` nested
 * under `metadata:` as INDENTED block sequences, which is how Claude Code writes them — 123 of
 * 158 real native files carry links that way), a top-level `type`, a file with neither, one
 * with no name, `MEMORY.md`, a directory named `*.md` and a `.txt`.
 *
 * THE LITERALS. A change applied to both sides leaves every differential green, so four
 * answers are pinned per side: the refresh sequence of the facts script, the `links` of the
 * wiki-link fixture, the `links`/`tags` read from under a native `metadata:`, and the native
 * directory's tree (bytes and mtimes) unchanged by a full refresh.
 *
 * WINDOWS. The lock and temp-then-rename are exercised on macOS only; the Windows run is
 * Task 8's manual step in `docs/superpowers/plans/2026-10-15-storage-layer.md`.
 */
import { createHash } from 'node:crypto';
import {
  chmodSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  statSync,
  symlinkSync,
  unlinkSync,
  utimesSync,
  writeFileSync,
} from 'node:fs';
import { basename, dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'storage-index';
export const summary = 'HotIndex: index bytes, docs/postings/df/avgdl, the refresh script, native read-only';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'storage_ref.py');

const T0 = 1_700_000_000;
const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');

const fact = (name, description, extra = '', body = 'body') =>
  `---\nname: ${name}\ndescription: ${description}\ntype: project\ncreated: '2026-10-15'\n` +
  `last_recalled: null\nlinks: []\n${extra}---\n\n${body}\n`;

/** The facts store: [rel, text]. Every mtime is pinned by `seed`. */
const FACTS = [
  ['store/facts/a.md', fact('a', 'release tag กินบริบท', 'keywords:\n- ปล่อยเวอร์ชัน\n- release\n')],
  [
    'store/facts/b.md',
    fact('b', 'links fixture', '', 'see [[release-lessons]] and [[b]] and [[c]] and [[ spaced ]] and [[b]]').replace(
      'links: []',
      "links:\n- c\n- release-lessons",
    ),
  ],
  ['store/facts/c.md', fact('c', 'tags fixture', 'tags:\n- t1\n- ไทย\n')],
  ['store/facts/constructor.md', fact('constructor', 'proto key 😀 constructor')],
  ['store/facts/__proto__.md', fact('__proto__', 'the other proto key')],
  ['store/facts/d-bad.md', '---\nname: d-bad\ntype: project\n---\n\nno description\n'],
  ['store/facts/e-kw.md', fact('e-kw', 'wrong keywords', 'keywords: notalist\n')],
  ['store/facts/num.md', '---\nname: 7\ndescription: 2026\ntype: project\nlinks: []\n---\n\nints\n'],
  ['store/facts/z-dup.md', fact('a', 'the second file named a')],
];

const NATIVE = [
  ['native/MEMORY.md', '# Memory index\n\n- [x](x.md)\n'],
  [
    'native/x.md',
    '---\nname: x\ndescription: "native fact with metadata"\nmetadata: \n  node_type: memory\n  type: feedback\n' +
      '  originSessionId: 7f42d69f-cc87-4cd9-9389-61c3255db547\n  modified: 2026-08-17T14:29:32.762Z\n---\n\nb [[y]]\n',
  ],
  [
    'native/y.md',
    '---\nname: y\ndescription: tagged ไทย\ntags:\n- t1\nlinks:\n- l1\nmetadata:\n  type: user\n---\n\n[[w]] [[l1]]\n',
  ],
  ['native/top.md', '---\nname: top\ndescription: top-level type\ntype: project\n---\n\nbody\n'],
  // Claude Code's own shape: `links` nested under `metadata:` as an INDENTED block sequence.
  [
    'native/nested.md',
    '---\nname: nested\ndescription: links under metadata\nmetadata: \n  node_type: memory\n  links: \n' +
      '    - first-link\n    - second-link\n  type: project\n  tags:\n  - nt\n---\n\nsee [[first-link]] [[third]]\n',
  ],
  // A top-level list indented under its key, beside a nested one it outranks.
  [
    'native/toplinks.md',
    '---\nname: toplinks\ndescription: top wins\nlinks:\n  - top-a\n  - top-b\nmetadata:\n  type: user\n' +
      '  links:\n  - nested-x\n---\n\nb\n',
  ],
  ['native/bad.md', '---\nname: bad\ndescription: no type anywhere\n---\n\nbody\n'],
  ['native/noname.md', '---\ndescription: no name\nmetadata:\n  type: user\n---\n\nbody\n'],
  ['native/sub.md/inner.md', '---\nname: inner\ntype: user\n---\n\nnested\n'],
  ['native/notes.txt', 'not a fact\n'],
];

/** A clean store: nothing skipped and every name a string, so the index may answer. */
const CLEAN = [
  FACTS[0],
  FACTS[1],
  FACTS[2],
  FACTS[3],
  FACTS[4],
  ['store/facts/h.md', fact('h', 'release notes for the tag')],
  ['store/facts/m.md', fact('m', 'tag release tag')],
  ['store/facts/q.md', fact('q', 'สวัสดี only thai words')],
];
/** Two YAML-integer names: Python orders 9 before 10, their strings order '10' first. */
/** Four facts whose `release` and `tag` postings form runs: ids a=0 b=1 c=2 d=3. */
const RUNS = [
  ['store/facts/a.md', fact('a', 'release tag')],
  ['store/facts/b.md', fact('b', 'release')],
  ['store/facts/c.md', fact('c', 'tag release', 'keywords:\n- release\n')],
  ['store/facts/d.md', fact('d', 'notes')],
];
/** Two facts tied on every score whose NAMES run opposite to their FILES; TIE_BROKEN adds a
 * second file claiming `zz-tie`, which sends recall to the files (#199 D3, J68-5). */
const TIES = [
  ['store/facts/a.md', fact('zz-tie', 'tie words')],
  ['store/facts/b.md', fact('aa-tie', 'tie words')],
];
const TIE_BROKEN = [...TIES, ['store/facts/c.md', fact('zz-tie', 'other')]];
/** #200: facts and a native file whose text names paths; `refs` is what the touch graph reads. */
const REFS_FACTS = [
  [
    'store/facts/r1.md',
    fact('r1', 'touches runtime-ts/src/memory/store.ts:450', 'keywords:\n- store.py#recall\n- ไฟล์ docs/memory.md\n',
      'see https://h/x/docs/gone.md and docs/memory.md:3, then src/Makefile.\r\nในa.py too'),
  ],
  ['store/facts/r2.md', fact('r2', 'no paths here at all, 0.37.0', '', 'Makefile README e.g. this')],
];
const REFS_NATIVE = [
  ['native/MEMORY.md', '# Memory index\n'],
  [
    'native/n.md',
    '---\nname: n\ndescription: touches src/a.ts\nmetadata:\n  type: user\n---\n\nand b.py#f, src/a.ts:9 ~/x/y.md\n',
  ],
];
const REFS_LITERAL = {
  r1: ['runtime-ts/src/memory/store.ts', 'store.py#recall', 'docs/memory.md', 'src/Makefile', 'a.py'],
  r2: ['e.g'], // the plan's own kinds test: `e.g.` ends in `.<letter>`, so it is a raw reference that resolves to nothing
  n: ['src/a.ts', 'b.py#f'],
};
const RUNS_SEGMENTS = [
  ['release', [0, 2, 0, 1, 0, 2, 1, 0, 1, 1]],
  ['tag', [0, 1, 0, 1, 0, 2, 1, 0, 1, 0]],
];
const LOOSE = [
  FACTS[0],
  ['store/facts/n10.md', '---\nname: 10\ndescription: loose number\ntype: project\nlinks: []\n---\n\nb\n'],
  ['store/facts/n9.md', '---\nname: 9\ndescription: loose number\ntype: project\nlinks: []\n---\n\nb\n'],
];
/**
 * #212: a lone surrogate spelled as a YAML escape. The file is UTF-8 (the backslash is literal);
 * PyYAML decodes `\ud800` to a lone code point, which the strict UTF-8 encoder refused when
 * the hot index was written, so one such fact took down every recall on its store. The pair is
 * the other half: PyYAML hands `\ud83d\ude00` back as TWO code points, a JS string as one
 * emoji, so both sides must read it as the emoji. Reversed, the two halves are two lone ones.
 */
const SURROGATE = [
  [
    'store/facts/release-notes.md',
    fact('release-notes', '"release \\ud800 notes"', 'keywords:\n- "\\udfff kw"\ntags:\n- "t\\ud800"\n'),
  ],
  ['store/facts/pair-fact.md', fact('pair-fact', '"pair \\ud83d\\ude00 joined, reversed \\ude00\\ud83d split"')],
  ['store/facts/plain.md', fact('plain', 'plain neighbour notes')],
];
const SURROGATE_NATIVE = [
  ['native/MEMORY.md', '# Memory index\n'],
  ['native/sn.md', '---\nname: sn\ndescription: "native \\ud800 lone"\nmetadata:\n  type: user\n---\n\nb\n'],
];
/** What both sides must read those escapes as: each lone half one U+FFFD, the pair one emoji. */
const SURROGATE_LITERAL = {
  'release-notes': ['release \ufffd notes', ['\ufffd kw'], ['t\ufffd']],
  'pair-fact': ['pair \u{1F600} joined, reversed \ufffd\ufffd split', [], []],
};
const RECALLS = [
  { query: 'release tag' },
  { query: 'RELEASE, Tag!' },
  { query: 'release', k: 1 },
  { query: 'release', k: 10 },
  { query: 'release tag fixture links', k: 5 },
  { query: 'release tag notes', min_ratio: 1.0 },
  { query: 'release tag notes', min_ratio: 0.5, k: 10 },
  { query: 'proto constructor key' },
  { query: 'nothing matches here' },
  { query: '' },
  { query: 'สวัสดี' },
  { query: 'release', k: 0 },
];
const LOOKUPS = ['a', 'b', '__proto__', 'constructor', 'missing', 'A', 'saved-late'];
const QUERY_TERMS = ['release', 'ปล', 'ปล่', 'tag', 'missing', '😀', 'constructor', '__proto__'];
const QUERY_WORDS = ['release', 'tag', 'fixture', 'proto', 'nope', '__proto__', '7', '2026'];
const STALE_SHARD = '{"fingerprint":"0000000000000000","terms":{"evil":["a"],"release":["evil"]}}';

const write = (rel, text, mtime, dirMtime) => ({ op: 'write', rel, b64: b64(text), mtime, dir_mtime: dirMtime });
const op = (o, extra = {}) => ({ op: o, ...extra });
const A_IN_PLACE = FACTS[0][1].replace('release tag', 'renamed words');
const B_IN_PLACE = FACTS[1][1].replace('links fixture', 'links fixture edited in place');

function scenarios() {
  return [
    {
      label: 'facts: the refresh script',
      files: FACTS,
      dirs: ['store/facts'],
      source: 'store',
      kind: 'facts',
      ops: [
        op('refresh', { mode: 'fast' }),
        op('bytes'),
        op('docs'),
        op('postings'),
        op('df'),
        op('avgdl'),
        op('skipped'),
        op('refresh', { mode: 'fast' }),
        write('store/facts/h.md', fact('h', 'added by rename'), T0 + 200, T0 + 201),
        op('refresh', { mode: 'fast' }),
        op('docs'),
        // in place: the directory mtime is put back, so a fast refresh cannot see it
        write('store/facts/a.md', A_IN_PLACE, T0 + 300, T0 + 201),
        op('refresh', { mode: 'fast' }),
        op('postings'),
        op('refresh', { mode: 'full' }),
        op('postings'),
        op('bytes'),
        op('refresh', { mode: 'full' }),
        write('store/facts/b.md', B_IN_PLACE, T0 + 400, T0 + 201),
        op('set', { key: 'full_at', value: '2000-01-01T00:00:00Z' }),
        op('refresh', { mode: 'fast' }),
        op('docs'),
        { op: 'unlink', rel: 'store/facts/a.md', dir_mtime: T0 + 500 },
        op('refresh', { mode: 'fast' }),
        op('docs'),
        op('skipped'),
        op('bytes'),
        op('corrupt', { text: '{not json' }),
        op('refresh', { mode: 'fast' }),
        op('bytes'),
        // version 1 is the single-file layout before the head and its shards: never read as a head
        op('set', { key: 'version', value: 1 }),
        op('refresh', { mode: 'fast' }),
        op('set', { key: 'source', value: '/elsewhere' }),
        op('refresh', { mode: 'fast' }),
        op('set', { key: 'kind', value: 'native' }),
        op('refresh', { mode: 'fast' }),
        op('set', { key: 'files', value: { 'x.md': 5 } }),
        op('refresh', { mode: 'fast' }),
        op('bytes'),
        // a doc of the wrong shape: the fresh path reads no doc, `docs()` reads them all and rebuilds
        op('set', { key: 'docs', value: { a: 5, b: { file: 'b.md' } } }),
        op('refresh', { mode: 'fast' }),
        op('docs'),
        op('bytes'),
        op('shardbytes'),
        op('query', { terms: QUERY_TERMS }),
        op('query_words', { words: QUERY_WORDS }),
        op('loose'),
        // a shard the head does not vouch for: its terms are never trusted, the index rebuilds
        op('corrupt_shard', { family: 'words', i: 'release', text: STALE_SHARD }),
        op('reopen'),
        op('query_words', { words: ['release', 'evil'] }),
        op('shardbytes'),
        op('rm_shard', { family: 'postings', i: 'ปล' }),
        op('reopen'),
        op('postings'),
        op('shardbytes'),
        op('corrupt_shard', { family: 'postings', i: 'tag', text: '{not json' }),
        op('reopen'),
        op('query', { terms: ['tag'] }),
        op('shardbytes'),
      ],
    },
    {
      label: 'store: recall and lookup answer from the index what the files answer',
      wallclock: true,
      files: CLEAN,
      dirs: ['store/facts'],
      source: 'store',
      kind: 'facts',
      ops: [
        ...RECALLS.map((r) => op('recall', r)),
        ...LOOKUPS.map((name) => op('lookup', { name })),
        op('refresh', { mode: 'fast' }),
        op('save', { name: 'saved-late', description: 'release lessons written late', keywords: ['ปล่อย'] }),
        op('refresh', { mode: 'fast' }),
        op('recall', { query: 'release lessons late' }),
        op('lookup', { name: 'saved-late' }),
        op('query', { terms: ['ปล', 'late'] }),
        op('stamp_lookup', { name: 'a' }),
        op('refresh', { mode: 'fast' }),
        op('recall', { query: 'release tag' }),
        op('save', { name: 'zz-release-tag', description: 'release tag' }),
        op('bytes'),
        op('shardbytes'),
        op('envindex', { query: 'release' }),
      ],
    },
    {
      label: 'store: the files answer when the index cannot vouch',
      files: FACTS,
      dirs: ['store/facts'],
      source: 'store',
      kind: 'facts',
      ops: [...RECALLS.map((r) => op('recall', r)), op('lookup', { name: 'a' }), op('lookup', { name: 'b' }), op('skipped')],
    },
    // POSIX modes, and root lists anything: the case runs where the modes mean something.
    ...(process.platform === 'win32' || process.getuid?.() === 0
      ? []
      : [
          {
            label: 'store: a fresh index never answers for a store nobody can list',
            files: CLEAN.slice(0, 2),
            dirs: ['store/facts'],
            source: 'store',
            kind: 'facts',
            ops: [
              op('recall', { query: 'release' }),
              // chmod moves no mtime: the index alone would answer `fresh`
              op('chmod', { rel: 'store/facts', mode: 0o311 }),
              op('recall', { query: 'release' }),
              op('lookup', { name: 'a' }),
              op('chmod', { rel: 'store/facts', mode: 0o755 }),
              op('recall', { query: 'release' }),
            ],
          },
        ]),
    {
      label: 'store: a name that is not a string sends recall to the files',
      files: LOOSE,
      dirs: ['store/facts'],
      source: 'store',
      kind: 'facts',
      ops: [
        op('loose'),
        op('recall', { query: 'loose number' }),
        op('recall', { query: 'release' }),
        op('lookup', { name: '9' }),
        op('lookup', { name: 'a' }),
      ],
    },
    {
      label: 'native: read-only, the native shape and its refusals',
      files: NATIVE,
      dirs: ['native/sub.md', 'native'],
      source: 'native',
      kind: 'native',
      ops: [
        op('tree'),
        op('refresh', { mode: 'full' }),
        op('bytes'),
        op('docs'),
        op('postings'),
        op('skipped'),
        op('refresh', { mode: 'fast' }),
        op('tree'),
      ],
    },
    {
      label: 'unwritable: the index dir is a file, so the answer stays in memory',
      files: [FACTS[0], FACTS[1]],
      dirs: ['store/facts'],
      source: 'store',
      kind: 'facts',
      unwritable: true,
      ops: [op('refresh', { mode: 'fast' }), op('persisted'), op('docs'), op('bytes'), op('refresh', { mode: 'fast' })],
    },
    {
      label: 'missing: a store with no facts directory yet',
      files: [],
      dirs: ['store'],
      source: 'store',
      kind: 'facts',
      ops: [
        op('refresh', { mode: 'fast' }),
        op('bytes'),
        op('docs'),
        op('avgdl'),
        op('refresh', { mode: 'fast' }),
        write('store/facts/a.md', fact('a', 'first fact'), T0 + 10, T0 + 11),
        op('refresh', { mode: 'fast' }),
        op('docs'),
        op('avgdl'),
      ],
    },
    {
      label: 'ties: the index breaks a tie on the name, not the file',
      files: TIES,
      dirs: ['store/facts'],
      source: 'store',
      kind: 'facts',
      ops: [op('recall', { query: 'tie words' })],
    },
    {
      label: 'ties: the files break a tie on the name, not the file',
      files: TIE_BROKEN,
      dirs: ['store/facts'],
      source: 'store',
      kind: 'facts',
      ops: [op('recall', { query: 'tie words' })],
    },
    {
      // #199, J68-5 (index v4): postings are run-length segments over doc ids, and the head is
      // one object in two lines, of which a recall parses the first. A second line nobody can
      // parse is found only by a read that needs it, and that read rebuilds.
      label: 'v4: segments, and a recall that reads the head\'s first line only',
      wallclock: true,
      files: RUNS,
      dirs: ['store/facts'],
      source: 'store',
      kind: 'facts',
      ops: [
        op('recall', { query: 'release tag' }),
        op('segments', { terms: ['release', 'tag', 'ปล', 'missing'] }),
        op('query', { terms: ['release', 'tag'] }),
        op('bytes'),
        op('corrupt_tail', { text: 'not json at all' }),
        op('reopen'),
        op('recall', { query: 'release tag' }),
        op('bytes'),
        op('refresh', { mode: 'fast' }),
        op('docs'),
        op('bytes'),
      ],
    },
    {
      // #200 (index v5): docs carry the path references of their text in `refs`.
      label: 'v5 #200 refs: a fact\'s path references',
      files: REFS_FACTS,
      dirs: ['store/facts'],
      source: 'store',
      kind: 'facts',
      ops: [op('refresh', { mode: 'fast' }), op('docs'), op('bytes')],
    },
    {
      label: 'v5 #200 refs: a native file\'s path references',
      files: REFS_NATIVE,
      dirs: ['native'],
      source: 'native',
      kind: 'native',
      ops: [op('refresh', { mode: 'full' }), op('docs'), op('bytes')],
    },
    {
      label: 'store #212: a lone surrogate in a frontmatter escape is read as U+FFFD',
      files: SURROGATE,
      dirs: ['store/facts'],
      source: 'store',
      kind: 'facts',
      ops: [
        op('refresh', { mode: 'fast' }),
        op('bytes'),
        op('shardbytes'),
        op('docs'),
        op('recall', { query: 'release notes' }),
        op('recall', { query: 'pair joined' }),
        op('lookup', { name: 'release-notes' }),
        op('refresh', { mode: 'fast' }),
      ],
    },
    {
      label: 'native #212: a lone surrogate in a native frontmatter escape is read as U+FFFD',
      files: SURROGATE_NATIVE,
      dirs: ['native'],
      source: 'native',
      kind: 'native',
      ops: [op('refresh', { mode: 'full' }), op('bytes'), op('docs')],
    },
  ];
}

// --------------------------------------------------------------------- the Node half

function tree(root) {
  const rows = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir).sort()) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else {
        rows.push([
          relative(root, p).split(sep).join('/'),
          createHash('sha256').update(readFileSync(p)).digest('hex'),
          statSync(p, { bigint: true }).mtimeNs.toString(),
        ]);
      }
    }
  };
  walk(root);
  return rows.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
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
const pairs = (m) => [...m.keys()].sort(cmpCp).map((k) => [k, m.get(k)]);

/** `call(store)` as shipped, then with the index refused (the files), and the eligibility. */
function both(store, call) {
  const seen = [];
  const shipped = store.indexed;
  const run = () => {
    try {
      return call(store);
    } catch (e) {
      return { error: `${e.name === 'TypeError' ? 'TypeError' : e.constructor.name}: ${e.message}` };
    }
  };
  store.indexed = function spy() {
    const got = shipped.call(store);
    seen.push(got !== null);
    return got;
  };
  const fast = run();
  store.indexed = () => null;
  const slow = run();
  delete store.indexed;
  return { fast, slow, indexed: seen.length > 0 && seen[0] };
}

function runNode(storage, pyjson, memory, bed) {
  let hi = new storage.HotIndex(bed.source, bed.kind, bed.home);
  let store = null;
  if (bed.kind === 'facts') {
    store = new memory.MemoryStore(bed.source, { create: false, today: () => '2026-10-15' });
    store.hot = hi;
  }
  const names = (facts) => facts.map((f) => memory.pyText(f.name));
  const nameOr = (f) => (f === null ? null : memory.pyText(f.name));
  const utime = (p, t) => {
    if (t !== undefined && t !== null) utimesSync(p, t, t);
  };
  const out = [];
  for (const o of bed.ops) {
    switch (o.op) {
      case 'write': {
        const p = join(bed.root, o.rel);
        mkdirSync(dirname(p), { recursive: true });
        writeFileSync(p, Buffer.from(o.b64, 'base64'));
        utime(p, o.mtime);
        utime(dirname(p), o.dir_mtime);
        out.push(null);
        break;
      }
      case 'unlink': {
        const p = join(bed.root, o.rel);
        unlinkSync(p);
        utime(dirname(p), o.dir_mtime);
        out.push(null);
        break;
      }
      case 'refresh':
        out.push(hi.refresh(o.mode));
        break;
      case 'docs':
        out.push(pairs(hi.docs()));
        break;
      case 'postings':
        out.push(pairs(hi.postings()));
        break;
      case 'df':
        out.push(pairs(hi.df()));
        break;
      case 'skipped':
        out.push(pairs(hi.skipped));
        break;
      case 'avgdl':
        out.push(pyjson.pyFloatRepr(hi.avgdl()));
        break;
      case 'persisted':
        out.push(hi.persisted);
        break;
      case 'bytes':
        try {
          out.push(readFileSync(hi.path).toString('base64'));
        } catch {
          out.push(null);
        }
        break;
      case 'set': {
        const data = JSON.parse(readFileSync(hi.path, 'utf8'));
        data[o.key] = o.value;
        writeFileSync(hi.path, storage.dumpIndex(data), 'utf8');
        out.push(null);
        break;
      }
      case 'corrupt':
        writeFileSync(hi.path, o.text, 'utf8');
        out.push(null);
        break;
      case 'tree':
        out.push(tree(bed.root));
        break;
      case 'shardbytes': {
        const rows = [];
        const stem = basename(hi.path, '.json');
        for (const family of storage.FAMILIES) {
          for (let i = 0; i < storage.SHARDS; i += 1) {
            const sp = hi.shardPath(family, i);
            let text = null;
            try {
              text = readFileSync(sp, 'utf8');
            } catch {
              /* absent */
            }
            rows.push([basename(sp).slice(stem.length), text]);
          }
        }
        out.push(rows);
        break;
      }
      case 'query':
        out.push(pairs(hi.query(o.terms)));
        break;
      case 'segments':
        out.push(pairs(hi.segments(o.terms)));
        break;
      case 'corrupt_tail': {
        // the head's first line kept, its second replaced: what a torn or hand-mangled tail is
        const raw = readFileSync(hi.path);
        const cut = raw.indexOf(0x0a);
        writeFileSync(hi.path, Buffer.concat([raw.subarray(0, cut + 1), Buffer.from(o.text, 'utf8')]));
        out.push(null);
        break;
      }
      case 'query_words':
        out.push(pairs(hi.queryWords(o.words)));
        break;
      case 'loose':
        out.push(hi.loose);
        break;
      case 'chmod':
        // platform-checked: the one scenario with a chmod op is built only off process.platform
        // 'win32' and only for a non-root uid (`scenarios()`), where a 0o311 directory refuses a listing.
        chmodSync(join(bed.root, o.rel), o.mode);
        out.push(null);
        break;
      case 'reopen':
        // a new process: nothing held in memory, every shard read from the disk
        hi = new storage.HotIndex(bed.source, bed.kind, bed.home);
        if (store !== null) store.hot = hi;
        out.push(null);
        break;
      case 'corrupt_shard':
        writeFileSync(hi.shardPath(o.family, o.i), o.text, 'utf8');
        out.push(null);
        break;
      case 'rm_shard':
        unlinkSync(hi.shardPath(o.family, o.i));
        out.push(null);
        break;
      case 'recall':
        out.push(both(store, (st) => names(st.recall(o.query, o.k ?? null, false, o.min_ratio ?? 0.0))));
        break;
      case 'lookup':
        out.push(both(store, (st) => nameOr(st.lookup(o.name, false))));
        break;
      case 'save':
        out.push(store.save('project', o.name, o.description, 'body', [], o.keywords ?? []).status);
        break;
      case 'stamp_lookup':
        out.push(nameOr(store.lookup(o.name)));
        break;
      case 'envindex': {
        const envDir = join(bed.home, 'envidx');
        const previous = process.env[storage.INDEX_DIR_ENV];
        process.env[storage.INDEX_DIR_ENV] = envDir;
        try {
          new memory.MemoryStore(bed.source, { create: false }).recall(o.query, null, false);
        } finally {
          if (previous === undefined) delete process.env[storage.INDEX_DIR_ENV];
          else process.env[storage.INDEX_DIR_ENV] = previous;
        }
        let dir = null;
        try {
          dir = readdirSync(envDir);
        } catch {
          /* absent */
        }
        out.push(dir === null ? null : { files: dir.length, heads: dir.filter((n) => /^[0-9a-f]{16}\.json$/.test(n)).length });
        break;
      }
      default:
        throw new Error(`storage-index: unknown op ${o.op}`);
    }
  }
  return out;
}

// ------------------------------------------------------------------------- literals

function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `${label} — python`, kind, expected, actual: pySide },
    { name: `${label} — node`, kind, expected, actual: nodeSide },
  ];
}

const REFRESH_LITERAL = [
  'rebuilt', // build
  'fresh', // nothing moved
  'patched', // a new file moved the directory
  'fresh', // an in-place edit: fast cannot see it
  'patched', // full can
  'fresh', // full, nothing changed
  'patched', // full_at expired: fast behaved as full
  'patched', // the duplicate's winner removed
  'rebuilt', // corrupt
  'rebuilt', // version
  'rebuilt', // source
  'rebuilt', // kind
  'rebuilt', // a files entry of the wrong shape
  'fresh', // a doc of the wrong shape: nothing on the fresh path reads one
];
const LINKS_LITERAL = ['c', 'release-lessons', 'b', 'spaced'];
const SHARD_TERMS = ['release', 'ปล', '😀', '', 'a', 'tag', 'loose'];
const YAML_REFUSED = [
  ['y1.md', '---\nname: y1\ndescription: b: c\ntype: project\n---\n\nb\n'],
  ['y2.md', '---\nname: y2\ndescription: [1\ntype: project\n---\n\nb\n'],
];
const YAML_REASONS_PY = [
  'malformed fact file y1.md: mapping values are not allowed here\n  in "<unicode string>", line 2, column 15:\n' +
    '    description: b: c\n                  ^',
  'malformed fact file y2.md: while parsing a flow sequence\n  in "<unicode string>", line 2, column 14:\n' +
    '    description: [1\n                 ^\nexpected \',\' or \']\', but got \':\'\n  in "<unicode string>", ' +
    'line 3, column 5:\n    type: project\n        ^',
];
const YAML_REASONS_NODE = [
  'malformed fact file y1.md: a plain scalar containing ": " is not readable YAML — PyYAML rejects it too: "b: c"',
  'malformed fact file y2.md: a flow sequence that continues past its line is outside this codec\'s language: "[1"',
];
const SHARD_LITERAL = [12, 0, 4, 2, 2, 6, 6];

// ------------------------------------------------------------------------------- run

/**
 * HOME is this suite's own scratch home for the whole run (#199, J68-5): a stamping `lookup` or
 * `recall` appends to the usage ledger under `~/.bantamkit/usage/`, and the harness does not move
 * HOME. The reference children inherit it (`runPython` spreads `process.env`).
 */
export async function run(ctx) {
  const was = [process.env.HOME, process.env.USERPROFILE];
  const home = join(ctx.scratch, 'storage-index-home');
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
  const pyjson = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'pyjson.js')).href);
  const memory = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'store.js')).href);
  const cases = [];
  const notes = [];

  // A shard op names its shard by a term; the harness resolves it once, for both sides.
  const all = scenarios().map((s) => ({
    ...s,
    ops: s.ops.map((o) => (typeof o.i === 'string' ? { ...o, i: storage.shardOf(o.i), term: o.i } : o)),
  }));
  const beds = { py: [], node: [] };
  const roots = { py: [], node: [] };
  all.forEach((s, i) => {
    for (const side of ['py', 'node']) {
      const base = join(ctx.scratch, `storage-index-${String(i + 1).padStart(2, '0')}`, side);
      const root = join(base, 'bed');
      const home = join(base, 'home');
      mkdirSync(root, { recursive: true });
      mkdirSync(home, { recursive: true });
      s.files.forEach(([rel, text], k) => {
        const p = join(root, rel);
        mkdirSync(dirname(p), { recursive: true });
        writeFileSync(p, text, 'utf8');
        utimesSync(p, T0 + k, T0 + k);
      });
      for (const d of s.dirs) {
        mkdirSync(join(root, d), { recursive: true });
        utimesSync(join(root, d), T0 + 100, T0 + 100);
      }
      if (s.unwritable) {
        mkdirSync(join(home, '.bantamkit'));
        writeFileSync(join(home, '.bantamkit', 'index'), 'a file, not a dir');
      }
      const real = realpathSync(root);
      roots[side].push([real, root]);
      beds[side].push({ root: real, source: join(real, s.source), kind: s.kind, home, ops: s.ops });
    }
  });

  // sha16 over the same absolute paths on both sides, so the index FILE NAME is comparable.
  const shaRoot = join(ctx.scratch, 'storage-index-sha', 'real');
  mkdirSync(shaRoot, { recursive: true });
  const shaLink = join(ctx.scratch, 'storage-index-sha', 'link');
  symlinkSync(shaRoot, shaLink, 'dir');
  const shaPaths = [shaRoot, shaLink, join(shaLink, 'not-yet', 'made'), join(ctx.scratch, 'storage-index-sha', 'ความจำ')];

  // Two frontmatters PyYAML refuses. Python reads facts through libyaml now (J69-3) and
  // re-parses any refusal with the pure loader, so the sentence is the pure loader's.
  const yamlRoots = {};
  for (const side of ['py', 'node']) {
    yamlRoots[side] = join(ctx.scratch, 'storage-index-yaml', side);
    mkdirSync(join(yamlRoots[side], 'facts'), { recursive: true });
    for (const [file, text] of YAML_REFUSED) writeFileSync(join(yamlRoots[side], 'facts', file), text, 'utf8');
  }
  const py = ctx.runPython(REF, {
    suite: 'storage-index',
    beds: beds.py,
    sha16: shaPaths,
    shard_of: SHARD_TERMS,
    yaml_skipped: [yamlRoots.py],
  });
  const nd = {
    beds: beds.node.map((bed) => runNode(storage, pyjson, memory, bed)),
    sha16: shaPaths.map((p) => storage.sha16(p)),
    shard_of: SHARD_TERMS.map((t) => storage.shardOf(t)),
    yaml_skipped: [yamlRoots.node].map((root) => {
      const out = [];
      new memory.MemoryStore(root, { create: false }).recall('x', null, false, 0.0, out);
      return out;
    }),
  };
  const [pyYaml] = py.yaml_skipped;
  const [ndYaml] = nd.yaml_skipped;
  cases.push({
    name: 'a frontmatter PyYAML refuses is skipped by both runtimes (the refusal bit)',
    kind: 'json',
    expected: pyYaml.map((r) => r.file),
    actual: ndYaml.map((r) => r.file),
  });
  cases.push({
    name: 'ruling: the YAML refusal sentence is PyYAML\'s on one side and the codec\'s on the other',
    kind: 'json',
    expected: pyYaml,
    actual: ndYaml,
    ruling:
      'store.mjs already rules this text (Node does not port PyYAML\'s scanner diagnostics); ' +
      'it is re-pinned here because libyaml words every one of these differently, and the ' +
      'python literal below is what proves the pure loader still writes them',
  });
  cases.push({
    name: "LITERAL: the YAML refusal sentence is the pure SafeLoader's, never libyaml's — python",
    kind: 'json',
    expected: YAML_REASONS_PY,
    actual: pyYaml.map((r) => r.reason),
  });
  cases.push({
    name: "LITERAL: the YAML refusal sentence is the codec's — node",
    kind: 'json',
    expected: YAML_REASONS_NODE,
    actual: ndYaml.map((r) => r.reason),
  });
  cases.push({ name: 'shard_of over the pinned terms', kind: 'json', expected: py.shard_of, actual: nd.shard_of });
  cases.push(...literalCases(py.shard_of, nd.shard_of, 'LITERAL: shard_of is sha256[:8] mod 16', SHARD_LITERAL));

  shaPaths.forEach((p, i) => {
    cases.push({
      name: `sha16 — ${['the source', 'a symlink to it', 'a path below the link that does not exist', 'a Thai name that does not exist'][i]}`,
      kind: 'string',
      expected: py.sha16[i],
      actual: nd.sha16[i],
    });
  });

  // `<bed>` for the side's own bed path, `<full_at>` for the wall-clock stamp.
  const mark = (side, i, text) => {
    let t = text.replace(/"full_at":"[^"]*"/g, '"full_at":"<full_at>"');
    for (const r of roots[side][i]) t = t.split(r).join('<bed>');
    // A `MemoryStore` write lands at wall-clock time: its mtimes are markers, its sizes are not.
    if (all[i].wallclock) {
      t = t
        .replace(/"(dir_)?mtime_ns":"\d+"/g, '"$1mtime_ns":"<mtime>"')
        .replace(/\["\d+",(\d+)\]/g, '["<mtime>",$1]');
    }
    return t;
  };
  const markJson = (side, i, v) => (v === null || v === undefined ? v : JSON.parse(mark(side, i, JSON.stringify(v))));
  const markBytes = (side, i, v) =>
    v === null ? Buffer.from('<no index file>') : Buffer.from(mark(side, i, Buffer.from(v, 'base64').toString('utf8')), 'utf8');

  all.forEach((s, i) => {
    s.ops.forEach((o, j) => {
      const what = `${o.op}${o.mode ? ` ${o.mode}` : ''}${o.key ? ` ${o.key}` : ''}${o.rel ? ` ${o.rel}` : ''}`;
      const isBytes = o.op === 'bytes';
      cases.push({
        name: `${s.label} — #${String(j).padStart(2, '0')} ${what}`,
        kind: isBytes ? 'bytes' : 'json',
        expected: isBytes ? markBytes('py', i, py.beds[i][j]) : markJson('py', i, py.beds[i][j]),
        actual: isBytes ? markBytes('node', i, nd.beds[i][j]) : markJson('node', i, nd.beds[i][j]),
      });
    });
  });
  notes.push(`${all.length} scripted scenarios, ${all.reduce((n, s) => n + s.ops.length, 0)} ops per side`);

  // ------------------------------------------------------------------- the literals
  const refreshes = (side) =>
    all[0].ops.map((o, j) => (o.op === 'refresh' ? (side === 'py' ? py : nd).beds[0][j] : undefined)).filter((x) => x !== undefined);
  cases.push(...literalCases(refreshes('py'), refreshes('node'), 'LITERAL: the facts script\'s refresh sequence', REFRESH_LITERAL));

  const docsAt = all[0].ops.findIndex((o) => o.op === 'docs');
  const linksOf = (side) => {
    const row = (side === 'py' ? py : nd).beds[0][docsAt].find(([n]) => n === 'b');
    return row ? row[1].links : null;
  };
  cases.push(...literalCases(linksOf('py'), linksOf('node'), 'LITERAL: links are frontmatter links, then [[wiki]] links, deduped', LINKS_LITERAL));

  const nat = all.findIndex((s) => s.kind === 'native');
  const natDocs = all[nat].ops.findIndex((o) => o.op === 'docs');
  const nestedOf = (side) => {
    const row = (side === 'py' ? py : nd).beds[nat][natDocs].find(([n]) => n === 'nested');
    return row ? [row[1].links, row[1].tags] : null;
  };
  cases.push(
    ...literalCases(nestedOf('py'), nestedOf('node'), 'LITERAL: native links and tags nested under metadata: are read', [
      ['first-link', 'second-link', 'third'],
      ['nt'],
    ]),
  );
  const treeAt = (side, which) => {
    const idx = which === 'first' ? all[nat].ops.findIndex((o) => o.op === 'tree') : all[nat].ops.findLastIndex((o) => o.op === 'tree');
    return (side === 'py' ? py : nd).beds[nat][idx];
  };
  for (const side of ['py', 'node']) {
    cases.push({
      name: `LITERAL: a native refresh leaves the native directory's bytes and mtimes unchanged — ${side === 'py' ? 'python' : 'node'}`,
      kind: 'json',
      expected: treeAt(side, 'first'),
      actual: treeAt(side, 'last'),
    });
  }

  // --------------------------------------------- the index answers what the files answer
  const sideOf = (side) => (side === 'py' ? py : nd);
  const label = (side) => (side === 'py' ? 'python' : 'node');
  const byLabel = (prefix) => all.findIndex((s) => s.label.startsWith(prefix));
  const opsOf = (i, kind) => all[i].ops.map((o, j) => [o, j]).filter(([o]) => kind.includes(o.op));
  const verdicts = (side, i) =>
    opsOf(i, ['recall', 'lookup']).map(([o, j]) => {
      const r = sideOf(side).beds[i][j];
      return [o.op, o.query ?? o.name, JSON.stringify(r.fast) === JSON.stringify(r.slow), r.indexed];
    });
  const expectAll = (i, indexed) => opsOf(i, ['recall', 'lookup']).map(([o]) => [o.op, o.query ?? o.name, true, indexed]);
  const clean = byLabel('store: recall and lookup');
  const dirty = byLabel('store: the files answer');
  const loose = byLabel('store: a name that is not');
  const unlisted = byLabel('store: a fresh index never answers');
  for (const side of ['py', 'node']) {
    cases.push({
      name: `LITERAL: on a clean store every recall and lookup is answered by the index, and equals the files' answer — ${label(side)}`,
      kind: 'json',
      expected: expectAll(clean, true),
      actual: verdicts(side, clean),
    });
    cases.push({
      name: `LITERAL: a skipped file sends every read to the files, and the answer is the files' — ${label(side)}`,
      kind: 'json',
      expected: expectAll(dirty, false),
      actual: verdicts(side, dirty),
    });
    cases.push({
      name: `LITERAL: a name that is not a string sends every read to the files, and the answer is the files' — ${label(side)}`,
      kind: 'json',
      expected: expectAll(loose, false),
      actual: verdicts(side, loose),
    });
    if (unlisted !== -1) {
      const rows = opsOf(unlisted, ['recall', 'lookup']).map(([, j]) => sideOf(side).beds[unlisted][j]);
      const refused = (r) =>
        JSON.stringify(r.fast) === JSON.stringify(r.slow) &&
        r.indexed === false &&
        typeof r.fast?.error === 'string' &&
        r.fast.error.startsWith('MemoryValidationError: memory store is unreadable: ');
      cases.push({
        name: `LITERAL: a store nobody can list is refused with the store's sentence, index or no index — ${label(side)}`,
        kind: 'json',
        expected: [true, true, true, true],
        actual: [rows[0].indexed && JSON.stringify(rows[0].fast) === JSON.stringify(rows[0].slow), refused(rows[1]), refused(rows[2]), rows[3].indexed],
      });
    }
    // #212 PER SIDE: a differential stays green if both sides keep the surrogate, or both drop
    // the fact; these pin WHAT both read, and that the fact is still found by the index.
    const sur = byLabel('store #212');
    const surDocs = sideOf(side).beds[sur][all[sur].ops.findIndex((o) => o.op === 'docs')];
    cases.push({
      name: `LITERAL: #212 each lone surrogate is U+FFFD and a split pair is one emoji, in the index's docs — ${label(side)}`,
      kind: 'json',
      expected: SURROGATE_LITERAL,
      actual: Object.fromEntries(
        surDocs.filter(([n]) => n in SURROGATE_LITERAL).map(([n, d]) => [n, [d.description, d.keywords, d.tags]]),
      ),
    });
    cases.push({
      name: `LITERAL: #212 the surrogate fact is recalled, by the index, and the build did not throw — ${label(side)}`,
      kind: 'json',
      expected: [
        'rebuilt',
        { fast: ['release-notes', 'plain'], slow: ['release-notes', 'plain'], indexed: true },
        ['recall', 'pair joined', true, true],
        'fresh',
      ],
      actual: [
        sideOf(side).beds[sur][0],
        sideOf(side).beds[sur][4],
        verdicts(side, sur)[1],
        sideOf(side).beds[sur][7],
      ],
    });
    const nsur = byLabel('native #212');
    const nsurDocs = sideOf(side).beds[nsur][2];
    cases.push({
      name: `LITERAL: #212 a native lone surrogate is U+FFFD — ${label(side)}`,
      kind: 'json',
      expected: ['rebuilt', 'native \ufffd lone'],
      actual: [sideOf(side).beds[nsur][0], (nsurDocs.find(([n]) => n === 'sn') ?? [null, {}])[1].description],
    });
    const looseAt = all[loose].ops.findIndex((o) => o.op === 'recall');
    // #199 D3 (J68-5): tied facts break on the name as a STRING — the ranker's `Candidate.name`
    // is `str`, compared by code point — so '10' sorts before '9' on both runtimes, fast path
    // or slow. WAS `LITERAL: integer names keep Python's order (9 before 10)`.
    cases.push({
      name: `LITERAL: integer names tie-break as strings, by code point ('10' before '9') — ${label(side)}`,
      kind: 'json',
      expected: { fast: ['10', '9'], slow: ['10', '9'], indexed: false },
      actual: sideOf(side).beds[loose][looseAt],
    });
    cases.push({
      name: `LITERAL: write-through — after a build, a save and a stamped lookup, a fast refresh is fresh — ${label(side)}`,
      kind: 'json',
      expected: ['fresh', 'fresh', 'fresh'],
      actual: opsOf(clean, ['refresh']).map(([, j]) => sideOf(side).beds[clean][j]),
    });
    const env = all[clean].ops.findIndex((o) => o.op === 'envindex');
    const got = sideOf(side).beds[clean][env];
    cases.push({
      name: `LITERAL: INDEX_DIR_ENV moves the head and its 32 shards there — ${label(side)}`,
      kind: 'json',
      expected: { files: 33, heads: 1 },
      actual: got,
    });
    const shardRows = opsOf(0, ['shardbytes']).map(([, j]) => JSON.stringify(sideOf(side).beds[0][j]));
    cases.push({
      name: `LITERAL: a stale, missing or corrupt shard is rebuilt to the same bytes — ${label(side)}`,
      kind: 'json',
      expected: [true, true, true, 32],
      actual: [
        shardRows[1] === shardRows[0],
        shardRows[2] === shardRows[0],
        shardRows[3] === shardRows[0],
        JSON.parse(shardRows[0]).filter(([, t]) => t !== null).length,
      ],
    });
    const staleAt = all[0].ops.findIndex((o, j) => o.op === 'query_words' && j > all[0].ops.findIndex((x) => x.op === 'corrupt_shard'));
    const stale = sideOf(side).beds[0][staleAt];
    cases.push({
      name: `LITERAL: a shard's terms are never trusted past its fingerprint — ${label(side)}`,
      kind: 'json',
      expected: [false, false],
      actual: [stale.some(([t]) => t === 'evil'), stale.some(([, names]) => names.includes('evil'))],
    });
  }

  // ---------------------------------------- ties break on the name, index or files
  // the files' answer also holds c.md's second `zz-tie`, matched on its name only: last
  for (const [prefix, indexed, want] of [
    ['ties: the index', true, ['aa-tie', 'zz-tie']],
    ['ties: the files', false, ['aa-tie', 'zz-tie', 'zz-tie']],
  ]) {
    const i = byLabel(prefix);
    for (const side of ['py', 'node']) {
      cases.push({
        name: `LITERAL: ${prefix.slice(6)} breaks a tie on the name (aa-tie in b.md before zz-tie in a.md) — ${label(side)}`,
        kind: 'json',
        expected: { fast: want, slow: want, indexed },
        actual: sideOf(side).beds[i][0],
      });
    }
  }

  // ------------------------------------------------ v4: segments and the two-line head
  const v4 = byLabel('v4: segments');
  const at = (op, nth = 0) => all[v4].ops.map((o, j) => [o, j]).filter(([o]) => o.op === op)[nth][1];
  for (const side of ['py', 'node']) {
    const got = sideOf(side).beds[v4];
    cases.push({
      name: `LITERAL: postings are run-length segments over doc ids, [start, count, tf per field] — ${label(side)}`,
      kind: 'json',
      expected: RUNS_SEGMENTS,
      actual: got[at('segments')],
    });
    const head = (j) => mark(side, v4, Buffer.from(got[j], 'base64').toString('utf8'));
    const first = head(at('bytes', 0));
    cases.push({
      name: `LITERAL: the head is one object in two lines; a recall needs only the first, a docs read rebuilds the second — ${label(side)}`,
      kind: 'json',
      expected: [true, true, true, true, true, 'fresh', true],
      actual: [
        first.split('\n').length === 2 && first.startsWith('{"avgdl":') && JSON.parse(first) !== null,
        first.split('\n')[0].includes('"cols":{') && !first.split('\n')[0].includes('"docs":'),
        JSON.stringify(got[at('recall', 1)]) === JSON.stringify(got[at('recall', 0)]) && got[at('recall', 1)].indexed,
        JSON.stringify(got[at('recall', 1)].fast) === JSON.stringify(got[at('recall', 1)].slow) && got[at('recall', 1)].fast.length === 3,
        head(at('bytes', 1)).endsWith('\nnot json at all'),
        got[at('refresh')],
        head(at('bytes', 2)) === first,
      ],
    });
  }

  // ------------------------------------------------ v5 (#200): refs, and the version that says so
  for (const side of ['py', 'node']) {
    const refsOf = {};
    let version = null;
    for (const prefix of ['v5 #200 refs: a fact', 'v5 #200 refs: a native']) {
      const i = byLabel(prefix);
      const got = sideOf(side).beds[i];
      const docsAt5 = all[i].ops.findIndex((o) => o.op === 'docs');
      for (const [n, doc] of got[docsAt5]) refsOf[n] = doc.refs;
      const bytesAt = all[i].ops.findIndex((o) => o.op === 'bytes');
      version = JSON.parse(Buffer.from(got[bytesAt], 'base64').toString('utf8')).version;
    }
    cases.push({
      name: `LITERAL: #200 refs — docs carry their path references, and the head is version 5 — ${label(side)}`,
      kind: 'json',
      expected: { refs: REFS_LITERAL, version: 5 },
      actual: { refs: refsOf, version },
    });
  }

  return { cases, notes };
}
