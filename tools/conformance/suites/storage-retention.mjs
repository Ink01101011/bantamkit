/**
 * storage-retention — the daily Retention job (#204, S4; job69 J69-6), Python against Node.
 *
 * THE PROPERTY: over the same trap fixture, the two runtimes delete, fold, rotate, archive and
 * refuse exactly the same files, leave byte-identical trees behind (archives compared AFTER
 * decompression: the compressed bytes differ between zlib builds, as `storage-log` rules), build
 * the same job cold index, answer `shiftwork_status(search)` the same, and honour the once-a-day
 * TTL and `BANTAMKIT_RETENTION=off` the same.
 *
 * `tree` hashes every file, a `.gz` one after decompression.
 *
 * THE BAR (spec, declared before any number): zero files deleted that are not verified in an
 * archive or past their TTL. The fixture plants the traps: an OPEN job 30 days old, a closed job
 * 6 days old, a closed job whose newest file is 6 days old, a ledger exactly 7 days old, an
 * unreadable checkpoint, an empty plan, an older archive that differs, an archive directory that
 * cannot be made, a fact 400 days old. `LITERAL: files gone` pins, per side, the only files a
 * run may remove.
 *
 * THE LITERALS. A change made on both sides leaves every differential green (a 7-day window
 * moved to 6, say), so the deleted list, the refused list and the files gone are pinned per side.
 *
 * `run.mjs` sets `BANTAMKIT_RETENTION=off` for every suite; each bed here turns it back on with
 * its first op, and every bed's HOME is the bed's own `home/`.
 */
import { createHash } from 'node:crypto';
import { lstatSync, mkdirSync, readdirSync, readFileSync, symlinkSync, utimesSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gunzipSync, gzipSync } from 'node:zlib';

export const name = 'storage-retention';
export const summary = 'Retention: prune, fold, rotate, archive closed jobs, verify before delete, TTL, opt-out, search';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'storage_ref.py');
const NOW = '2026-10-16T00:00:00.000Z';
const NOW_S = Date.parse(NOW) / 1000;
const DAY = 86_400;
const B = (s) => Buffer.from(s, 'utf8');

const units = (...statuses) =>
  statuses.map((s, i) => ({
    id: `U${i + 1}`,
    title: `unit ${i + 1}`,
    brief_path: `b${i + 1}.md`,
    status: s,
    role: 'implementer',
    depends_on: [],
    verify: 'true',
  }));
const cp = (goal, ...statuses) =>
  B(
    JSON.stringify(
      {
        version: 1,
        job: { id: goal, goal, done_definition: 'd', constraints: [] },
        state: { repo: { branch: 'b', head_sha: 'h', dirty: false }, artifacts: [], external: [] },
        plan: { cursor: 'U1', units: units(...statuses) },
        handoff: { next_action: 'x', open_questions: [], do_not: [], notes: '' },
        history: [],
        retro: [],
      },
      null,
      2,
    ),
  );

/** [relative path, bytes, age in days]. The comment above each says what must happen to it. */
function trapFiles() {
  const ledger = B('{"seen":{}}');
  const hook = B(
    [
      { ts: '2026-08-01T10:00:00.000Z', ms: 1, event: 'Folded', counts: { SessionStart: 3 } },
      { ts: '2026-09-06T10:00:00.000Z', ms: 1, event: 'SessionStart' },
      { ts: '2026-09-06T11:00:00.000Z', ms: 1, event: 'SessionStart' },
      { ts: '2026-09-06T12:00:00.000Z', ms: 1, event: 'PostToolUse', tool: 'Read' },
      { ts: '2026-09-06T13:00:00.000Z', ms: 1, tool: 'Bash' },
      { ts: '2026-09-15T23:59:59.999Z', ms: 1, event: 'UserPromptSubmit' },
      { ts: '2026-09-16T00:00:00.000Z', ms: 1, event: 'Stop' },
      { ts: '2026-09-20T12:00:00.000Z', ms: 1, event: 'Stop', note: 'ไทย 😀' },
    ]
      .map((r) => `${JSON.stringify(r)}\n`)
      .join('') + 'not json\n',
  );
  const usage = B(
    '{"ts":"2026-09-01T00:00:00Z","fact":"f1","kind":"recall_hit"}\n' +
      '{"ts":"2026-09-02T00:00:00Z","fact":"f1","kind":"save","keywords":["k"]}\n' +
      '{"ts":"2026-09-03T00:00:00Z","fact":"f2","kind":"body_read"}\n' +
      '{"ts":"2026-10-10T00:00:00Z","fact":"f1","kind":"body_read"}\n',
  );
  const sw = 'a/.shiftwork';
  return [
    // deleted: past its TTL / stays / stays (not MORE than 7 days) / stays (not a ledger name)
    ['home/.bantamkit/hooks/ledger-old.json', ledger, 8],
    ['home/.bantamkit/hooks/ledger-new.json', ledger, 6],
    ['home/.bantamkit/hooks/ledger-edge.json', ledger, 7],
    ['home/.bantamkit/hooks/ledger-notes.txt', ledger, 30],
    // folded: the boundary lines at the cutoff; folded; folded then rotated; saves only: untouched
    ['home/.bantamkit/hooks/hook-log.jsonl', hook, 0],
    ['home/.bantamkit/usage/aaaa.jsonl', usage, 0],
    ['home/.bantamkit/usage/idle.jsonl', B('{"ts":"2026-09-10T00:00:00Z","fact":"g","kind":"seed"}\n'), 31],
    ['home/.bantamkit/usage/saves.jsonl', B('{"ts":"2026-09-01T00:00:00Z","fact":"s","kind":"save"}\n'), 0],
    // a fact: never archived by age
    ['home/.bantamkit/memory/facts/keep.md', B('---\nname: keep\n---\n'), 400],
    // OPEN, 30 days old: stays
    [`${sw}/checkpoint-open.json`, cp('open', 'done', 'todo'), 30],
    [`${sw}/briefs-open/U1.md`, B('open brief release notes\n'), 30],
    // closed 8 days ago: archived, then deleted (a non-UTF-8 file is bundled as base64)
    [`${sw}/checkpoint-closed8.json`, cp('closed eight release', 'done', 'dropped'), 8],
    [`${sw}/checkpoint-closed8.json.log.jsonl`, B('{"brief":"U1"}\n'), 8],
    [`${sw}/briefs-closed8/U1.md`, B('brief ไทย release notes\r\nsecond line\n'), 8],
    [`${sw}/notes-closed8/sub/U1.md`, B('note: release tag measured\nrelease notes again\n'), 9],
    [`${sw}/notes-closed8/bin.dat`, Buffer.from([0xff, 0xfe, 0x00, 0x72, 0x61, 0x77]), 8],
    [`${sw}/notes-closed8/bom.md`, Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), B('bom line\n')]), 8],
    // closed 6 days ago: stays
    [`${sw}/checkpoint-closed6.json`, cp('closed six', 'done'), 6],
    // closed, checkpoint 8 days old, but its newest file is 6 days old: stays
    [`${sw}/checkpoint-mixed.json`, cp('mixed', 'done'), 8],
    [`${sw}/notes-mixed/late.md`, B('late\n'), 6],
    // unreadable; no units; a BOM before the JSON: all stay
    [`${sw}/checkpoint-bad.json`, B('{not json'), 30],
    [`${sw}/checkpoint-empty.json`, cp('empty'), 30],
    [`${sw}/checkpoint-bom.json`, Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), cp('bom', 'done')]), 30],
    // closed 8 days ago, but an older archive of the same name differs: refused, stays
    [`${sw}/checkpoint-clash.json`, cp('clash', 'done'), 8],
    [`${sw}/archive/clash.json.gz`, gzipSync(B('{}')), 8],
    // the bare `checkpoint.json`: archived as `checkpoint`
    [`${sw}/checkpoint.json`, cp('bare', 'dropped'), 8],
    // not a job
    [`${sw}/backlog.md`, B('backlog\n'), 30],
    // closed 8 days ago, but a FILE sits where the archive directory goes: refused, stays
    ['b/.shiftwork/checkpoint-blocked.json', cp('blocked', 'done'), 8],
    ['b/.shiftwork/archive', B('a file where the archive dir goes\n'), 8],
  ];
}

const op = (o, extra = {}) => ({ op: o, ...extra });
const FILES = [
  op('file', { rel: 'home/.bantamkit/hooks/hook-log.jsonl' }),
  op('file', { rel: 'home/.bantamkit/usage/aaaa.jsonl' }),
  op('file', { rel: 'home/.bantamkit/usage/idle.jsonl' }),
  op('file', { rel: 'home/.bantamkit/usage/idle.jsonl.1.gz', gz: true }),
  op('file', { rel: 'a/.shiftwork/archive/closed8.json.gz', gz: true }),
  op('file', { rel: 'a/.shiftwork/archive/checkpoint.json.gz', gz: true }),
];

const SCENARIOS = [
  {
    label: 'trap: one run over the fixture, then a second run',
    ops: [
      op('env', { off: false }),
      op('tree'),
      op('run', { now: NOW }),
      op('tree'),
      ...FILES,
      op('cold'),
      op('search', { rel: 'a/.shiftwork/checkpoint-open.json', q: 'release notes' }),
      op('search', { rel: 'a/.shiftwork/checkpoint-open.json', q: 'ไทย' }),
      op('search', { rel: 'a/.shiftwork/checkpoint-open.json', q: 'release' }),
      op('search', { rel: 'a/.shiftwork/checkpoint-open.json', q: '' }),
      op('search', { rel: 'a/.shiftwork/checkpoint-open.json', q: 'absent words' }),
      op('search', { rel: 'a/.shiftwork/checkpoint-missing.json', q: 'release' }),
      op('run', { now: NOW }),
      op('tree'),
      op('ghost'),
      op('run', { now: NOW }),
      op('cold'),
      op('tree'),
    ],
  },
  {
    label: 'ttl: the child claims the day once',
    ops: [
      op('env', { off: false }),
      op('due', { now: NOW }),
      op('child', { now: NOW }),
      op('tree'),
      op('due', { now: '2026-10-16T23:59:59.999Z' }),
      op('due', { now: '2026-10-17T00:00:00.000Z' }),
      op('due', { now: '2026-10-15T23:59:59.999Z' }),
      op('due', { now: 'not a time' }),
      op('child', { now: '2026-10-16T12:00:00.000Z' }),
      op('tree'),
      op('child', { now: '2026-10-25T00:00:00.000Z' }),
      op('tree'),
    ],
  },
  {
    label: 'opt-out: BANTAMKIT_RETENTION=off changes nothing',
    ops: [
      op('env', { off: true }),
      op('tree'),
      op('run', { now: NOW }),
      op('child', { now: NOW }),
      op('tree'),
    ],
  },
  {
    label: 'reducer: the hook-log fold rows',
    ops: [
      op('env', { off: false }),
      op('reducer', {
        rows: [
          { ts: '2026-09-02T01:00:00.000Z', event: 'B' },
          { ts: '2026-09-01T01:00:00.000Z', event: 'A', tool: 'T' },
          { ts: '2026-09-01T02:00:00.000Z', event: 'Folded', counts: { A: 2, Z: 1, bad: 'x' } },
          { ts: 5, event: 'A' },
          { event: 'A' },
          { ts: '2026-09-01T03:00:00.000Z', event: 7 },
          { ts: '2026-09-01T04:00:00.000Z', event: 'Folded', counts: 'nope' },
          { ts: 'ไทย-short', event: 'A' },
        ],
      }),
      op('reducer', { rows: [] }),
    ],
  },
  {
    // J69-8: a job directory that is a LINK is never walked. Closed 8 days ago, `notes-linked`
    // points at `<bed>/outside/`; before the fix both sides bundled `outside/keep.md` and then
    // deleted it THROUGH the link (a symmetric bug, so only the literals below can see it).
    label: 'link: a job directory that is a link to elsewhere is never walked',
    extra: [
      ['outside/keep.md', B('outside .shiftwork, must survive\n'), 30],
      ['a/.shiftwork/checkpoint-linked.json', cp('linked', 'done'), 8],
      ['a/.shiftwork/briefs-linked/U1.md', B('linked brief\n'), 8],
    ],
    links: [['a/.shiftwork/notes-linked', 'outside']],
    ops: [
      op('env', { off: false }),
      op('tree'),
      op('run', { now: NOW }),
      op('tree'),
      op('file', { rel: 'a/.shiftwork/archive/linked.json.gz', gz: true }),
    ],
  },
];

// --------------------------------------------------------------------- the Node half

function treeOf(base) {
  const rows = [];
  const walk = (d) => {
    for (const n of readdirSync(d)) {
      const p = join(d, n);
      const st = lstatSync(p);
      if (st.isSymbolicLink()) rows.push([relative(base, p).split(sep).join('/'), '<link>']);
      else if (st.isDirectory()) walk(p);
      else {
        const r = relative(base, p).split(sep).join('/');
        if (r.startsWith('idx/') || n.endsWith('.lock')) continue;
        let data = readFileSync(p);
        if (n.endsWith('.gz')) {
          // compared AFTER decompression: zlib builds differ (storage-log's ruling)
          try {
            data = gunzipSync(data);
          } catch {
            /* hashed as on disk */
          }
        }
        // retention.json prints this bed's paths: its content is the `child` op's
        rows.push([r, r.endsWith('/retention.json') ? '<state>' : createHash('sha256').update(data).digest('hex')]);
      }
    }
  };
  walk(base);
  return rows.sort((a, b) => cmpCp(a[0], b[0]));
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

function readOrNull(p) {
  try {
    return readFileSync(p);
  } catch {
    return null;
  }
}

function runNode(mods, bed) {
  const { retention, shiftwork, toJs } = mods;
  const saved = { r: process.env.BANTAMKIT_RETENTION, i: process.env.BANTAMKIT_INDEX_DIR };
  process.env.BANTAMKIT_INDEX_DIR = bed.index_dir;
  try {
    const out = [];
    for (const o of bed.ops) {
      switch (o.op) {
        case 'env':
          if (o.off) process.env.BANTAMKIT_RETENTION = 'off';
          else delete process.env.BANTAMKIT_RETENTION;
          out.push(null);
          break;
        case 'run':
          out.push(retention.runRetention(bed.home, bed.roots, o.now));
          break;
        case 'tree':
          out.push(treeOf(bed.base));
          break;
        case 'file': {
          let data = readOrNull(join(bed.base, o.rel));
          if (data !== null && o.gz) data = gunzipSync(data);
          out.push(data === null ? null : data.toString('base64'));
          break;
        }
        case 'cold': {
          const d = retention.shiftworkCold(bed.home, bed.roots[0]).dir;
          let names = [];
          try {
            names = readdirSync(d)
              .filter((n) => !n.endsWith('.lock'))
              .sort(cmpCp);
          } catch {
            names = [];
          }
          out.push(names.map((n) => [n, readFileSync(join(d, n), 'utf8')]));
          break;
        }
        case 'search':
          out.push(toJs(shiftwork.status(join(bed.base, o.rel), o.q)));
          break;
        case 'child': {
          retention.childMain([bed.roots[0], bed.home], o.now);
          const data = readOrNull(retention.statePath(bed.home));
          out.push(data === null ? null : JSON.parse(data.toString('utf8')));
          break;
        }
        case 'due':
          out.push(retention.due(bed.home, o.now));
          break;
        case 'ghost': {
          const cold = retention.shiftworkCold(bed.home, bed.roots[0]);
          const doc = {
            file: '.shiftwork/archive/ghost.json.gz',
            name: 'ghost',
            description: 'gone',
            type: 'shiftwork',
            keywords: ['ghost'],
            links: [],
            tags: [],
            refs: [],
            mtime_ns: '0',
            size: 1,
          };
          cold.add(new Map([['ghost', doc]]));
          out.push(null);
          break;
        }
        case 'reducer':
          out.push(retention.hookLogReducer(o.rows));
          break;
        default:
          throw new Error(`unknown op: ${o.op}`);
      }
    }
    return out;
  } finally {
    const put = (k, v) => (v === undefined ? delete process.env[k] : (process.env[k] = v));
    put('BANTAMKIT_RETENTION', saved.r);
    put('BANTAMKIT_INDEX_DIR', saved.i);
  }
}

// ------------------------------------------------------------------------- masking

/** Every printed path relative to its bed, `/`-separated; the cold dir's store id masked. */
function mask(value, base) {
  const text = JSON.stringify(value);
  if (text === undefined) return value;
  const esc = JSON.stringify(base).slice(1, -1);
  const sepEsc = JSON.stringify(sep).slice(1, -1);
  return JSON.parse(
    text
      .split(esc)
      .join('<BED>')
      .split(`<BED>${sepEsc}`)
      .join('<BED>/')
      .replace(/<BED>\/[^"]*/g, (m) => m.split(sepEsc).join('/'))
      .replace(/shiftwork-[0-9a-f]{16}/g, 'shiftwork-<id>')
      .replace(/"created":"[^"]*"/g, '"created":"<created>"')
      .replace(/\\"created\\":\\"[^"\\]*\\"/g, '\\"created\\":\\"<created>\\"')
      .replace(/"ran_at":"(?!2026-)[^"]*"/g, '"ran_at":"<now>"'),
  );
}

// ------------------------------------------------------------------------------- run

export async function run(ctx) {
  const dist = (p) => pathToFileURL(join(ctx.runtimeTs, 'dist', ...p.split('/'))).href;
  const mods = {
    retention: await import(dist('storage/retention.js')),
    shiftwork: await import(dist('shiftwork.js')),
    toJs: (await import(dist('pyjson.js'))).toJs,
  };
  const beds = { py: [], node: [] };
  SCENARIOS.forEach((s, i) => {
    for (const side of ['py', 'node']) {
      const base = join(ctx.scratch, `storage-retention-${String(i + 1).padStart(2, '0')}`, side);
      for (const [rel, data, age] of [...trapFiles(), ...(s.extra ?? [])]) {
        const p = join(base, rel);
        mkdirSync(dirname(p), { recursive: true });
        writeFileSync(p, data);
        const when = NOW_S - Math.trunc(age * DAY);
        utimesSync(p, when, when);
      }
      // platform-checked: a 'junction' needs no privilege on Windows and is a plain directory
      // symlink on POSIX (the type argument is ignored there); the target is absolute, as a
      // junction requires.
      for (const [rel, target] of s.links ?? []) symlinkSync(join(base, target), join(base, rel), 'junction');
      beds[side].push({
        base,
        home: join(base, 'home'),
        roots: [join(base, 'a'), join(base, 'b')],
        index_dir: join(base, 'idx'),
        ops: s.ops,
      });
    }
  });
  const py = ctx.runPython(REF, { suite: 'storage-retention', beds: beds.py }, { HOME: join(ctx.scratch, 'retention-py-home') });
  const nd = { beds: beds.node.map((bed) => runNode(mods, bed)) };
  const P = (i, j) => mask(py.beds[i][j], beds.py[i].base);
  const N = (i, j) => mask(nd.beds[i][j], beds.node[i].base);

  const cases = [];
  SCENARIOS.forEach((s, i) => {
    s.ops.forEach((o, j) => {
      const what = `${o.op}${o.rel ? ` ${o.rel}` : ''}${o.q !== undefined ? ` ${JSON.stringify(o.q)}` : ''}${o.now ? ` ${o.now}` : ''}`;
      cases.push({ name: `${s.label} — #${String(j).padStart(2, '0')} ${what}`, kind: 'json', expected: P(i, j), actual: N(i, j) });
    });
  });

  // ------------------------------------------------------------------- the literals
  const at = (i, pred, nth = 0) => SCENARIOS[i].ops.map((o, j) => [o, j]).filter(([o]) => pred(o))[nth][1];
  const firstRun = at(0, (o) => o.op === 'run');
  const [treeBefore, treeAfter] = [at(0, (o) => o.op === 'tree', 0), at(0, (o) => o.op === 'tree', 1)];
  const gone = (get) => {
    const after = new Set(get(0, treeAfter).map(([r]) => r));
    return get(0, treeBefore)
      .map(([r]) => r)
      .filter((r) => !after.has(r));
  };
  const literal = (label, expected, pySide, nodeSide) => [
    { name: `${label} — python`, kind: 'json', expected, actual: pySide },
    { name: `${label} — node`, kind: 'json', expected, actual: nodeSide },
  ];
  cases.push(
    ...literal(
      'LITERAL: files gone after one run — only the past-TTL ledger and the verified-archived job files',
      [
        'a/.shiftwork/briefs-closed8/U1.md',
        'a/.shiftwork/checkpoint-closed8.json',
        'a/.shiftwork/checkpoint-closed8.json.log.jsonl',
        'a/.shiftwork/checkpoint.json',
        'a/.shiftwork/notes-closed8/bin.dat',
        'a/.shiftwork/notes-closed8/bom.md',
        'a/.shiftwork/notes-closed8/sub/U1.md',
        'home/.bantamkit/hooks/ledger-old.json',
      ],
      gone(P),
      gone(N),
    ),
    ...literal('LITERAL: the deleted list', ['<BED>/home/.bantamkit/hooks/ledger-old.json'], P(0, firstRun).deleted, N(0, firstRun).deleted),
    ...literal(
      'LITERAL: the refused list',
      [
        { path: '<BED>/a/.shiftwork/archive/clash.json.gz', reason: 'archive exists and differs' },
        { path: '<BED>/b/.shiftwork/checkpoint-blocked.json', reason: 'archive write failed' },
      ],
      P(0, firstRun).refused,
      N(0, firstRun).refused,
    ),
    ...literal(
      'LITERAL: the archived list',
      ['<BED>/a/.shiftwork/archive/closed8.json.gz', '<BED>/a/.shiftwork/archive/checkpoint.json.gz'],
      P(0, firstRun).archived,
      N(0, firstRun).archived,
    ),
  );
  const optRun = at(2, (o) => o.op === 'run');
  const empty = { archived: [], compacted: [], deleted: [], folded: [], refused: [], rotated: [] };
  cases.push(...literal('LITERAL: opt-out answers an empty report', empty, P(2, optRun), N(2, optRun)));
  const search = at(0, (o) => o.op === 'search');
  const hits = (v) => (v && typeof v === 'object' ? v.search : v);
  cases.push(
    ...literal(
      'LITERAL: search finds every line holding all the words, archived jobs only',
      [
        { job: 'closed8', file: '.shiftwork/briefs-closed8/U1.md', line: 1 },
        { job: 'closed8', file: '.shiftwork/notes-closed8/sub/U1.md', line: 2 },
      ],
      hits(P(0, search)),
      hits(N(0, search)),
    ),
  );
  // A fold that ran is non-vacuous only if the boundary rows went the right way; spelled out.
  const hookLog = at(0, (o) => o.op === 'file', 0);
  const lines = (b64) => (b64 === null ? null : Buffer.from(b64, 'base64').toString('utf8').split('\n'));
  cases.push(
    ...literal(
      'LITERAL: the hook log after the fold (a row AT the cutoff is kept; a bad line is dropped)',
      [
        '{"ts":"2026-08-01T00:00:00.000Z","event":"Folded","counts":{"SessionStart":3}}',
        '{"ts":"2026-09-06T00:00:00.000Z","event":"Folded","counts":{"?/Bash":1,"PostToolUse/Read":1,"SessionStart":2}}',
        '{"ts":"2026-09-15T00:00:00.000Z","event":"Folded","counts":{"UserPromptSubmit":1}}',
        '{"ts":"2026-09-16T00:00:00.000Z","ms":1,"event":"Stop"}',
        '{"ts":"2026-09-20T12:00:00.000Z","ms":1,"event":"Stop","note":"ไทย 😀"}',
        '',
      ],
      lines(py.beds[0][hookLog]),
      lines(nd.beds[0][hookLog]),
    ),
  );
  // J69-8: a job directory that is a link. What lives behind the link survives, the link is
  // left, and the archive bundles only the job's own files. Both sides once deleted
  // `outside/keep.md` through the link, which every differential passes; these cannot.
  const linkIdx = SCENARIOS.findIndex((s) => s.label.startsWith('link:'));
  const linkTree = at(linkIdx, (o) => o.op === 'tree', 1);
  const behind = (rows) => (Array.isArray(rows) ? rows.filter(([r]) => r.startsWith('outside/') || r === 'a/.shiftwork/notes-linked') : rows);
  const keys = (b64) => (typeof b64 === 'string' ? Object.keys(JSON.parse(Buffer.from(b64, 'base64').toString('utf8'))).sort() : b64);
  const linkFile = at(linkIdx, (o) => o.op === 'file');
  cases.push(
    ...literal(
      'LITERAL: a linked job directory is not walked — the file behind it survives, the link stays',
      [
        ['a/.shiftwork/notes-linked', '<link>'],
        ['outside/keep.md', createHash('sha256').update(B('outside .shiftwork, must survive\n')).digest('hex')],
      ],
      behind(P(linkIdx, linkTree)),
      behind(N(linkIdx, linkTree)),
    ),
    ...literal(
      'LITERAL: the archive of the linked job holds only its own files',
      ['.shiftwork/briefs-linked/U1.md', '.shiftwork/checkpoint-linked.json'],
      keys(py.beds[linkIdx][linkFile]),
      keys(nd.beds[linkIdx][linkFile]),
    ),
  );
  return { cases, notes: [`${SCENARIOS.length} scripted scenarios, ${SCENARIOS.reduce((n, s) => n + s.ops.length, 0)} ops per side`] };
}
