/**
 * skill-miner — the experience miner (#206), Python against Node. Part 1 (Task 4a): the
 * shiftwork source, the signature and the similarity. Task 5 adds clustering and the bars.
 *
 * THE PROPERTY: over the same `.shiftwork/` trees the two runtimes find the same pieces of
 * work (ids, success bits, last clock-out, prompt, named paths, failure, repo key), compute
 * the same signature for each, and answer the same exact fraction — and the same verdict at
 * the 1/2 boundary — for every pair of signatures. A piece that one runtime counts and the
 * other does not is a skill one of them proposes and the other never would.
 *
 * HOW. The suite builds every fixture tree once, in this run's scratch; the miner only
 * reads, so both runtimes read the SAME directories and even the realpath-based repo key is
 * comparable byte for byte. `ref/skillmine_ref.py` answers for Python, `dist/skillmine.js`
 * for Node.
 *
 * WHAT THE FIXTURES ARE AIMED AT. Each rule has an input that only it decides: an archived
 * job (`.json.gz`), a live job, a plain `checkpoint.json` named by `job.id` and shadowing its
 * own archive; every clock-out status (done, blocked, dropped, in_progress); an `uncommitted`
 * marker that takes a `done` back; ledger lines `JSON.parse` and a lax `json.loads` disagree
 * on (`NaN`), a status that is a list, two records joined by U+2028 (a `splitlines` reader
 * would split them), a CRLF line; a BOM'd checkpoint and a gzip of invalid UTF-8; briefs
 * that are absolute, `../`, or a symlink out of the root; unit ids and paths whose code-point
 * order differs from their UTF-16 order (`😀` against `！`); a linked worktree that must share
 * its main checkout's repo key; and a similarity pair at exactly 1/2 whose float sum is
 * 0.49999999999999994.
 *
 * THE LITERALS. `KEYWORDS_TOP` and the boundary verdict are pinned per side, so a change
 * made to BOTH runtimes alike (top 10, a float compare in both) is still red.
 */
import { mkdirSync, symlinkSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gzipSync } from 'node:zlib';

export const name = 'skill-miner';
export const summary = 'shiftwork pieces of work, their signature and the exact weighted-Jaccard similarity';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'skillmine_ref.py');

const ckpt = (jobId, units, history = []) =>
  JSON.stringify({
    version: 1,
    job: { id: jobId, goal: 'g', done_definition: 'd', constraints: [] },
    plan: {
      cursor: units[0][0],
      units: units.map(([id, title, brief]) => ({
        id,
        title,
        brief_path: brief,
        status: 'done',
        role: 'implementer',
        depends_on: [],
        verify: 'true',
      })),
    },
    history,
  });
const line = (unit, status, ts) => JSON.stringify({ unit, role: 'implementer', status, ts });
const ev = (event, unit) => JSON.stringify({ event, unit, role: 'implementer', ts: '2026-01-01T00:00:00Z' });

function write(p, data) {
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, data);
}

/** The main root: one archived job, one live job, a plain checkpoint, refusals. */
function mainRoot(base) {
  const root = join(base, 'main');
  mkdirSync(join(root, '.git'), { recursive: true });
  write(join(root, '.git', 'config'), '[core]\n');
  for (const f of ['src/parse.py', 'src/lex.ts', 'docs/คู่มือ.md', 'docs/😀.md', 'docs/！.md', 'README.md', 'docs/u3.md']) {
    write(join(root, f), 'x\n');
  }
  write(join(base, 'outside.md'), 'outside src/parse.py\n');
  const sw = join(root, '.shiftwork');

  // job71, archived: its briefs live only in the bundle, except U3's, which is a repo file.
  const bundle = {
    '.shiftwork/checkpoint-job71.json': ckpt(
      'job71',
      [
        ['U1', 'fix the parser', '.shiftwork/briefs-job71/U1.md'],
        ['U2', 'port the parser', '.shiftwork/briefs-job71/U2.md'],
        ['U3', 'document the parser', 'docs/u3.md'],
      ],
      [{ unit: 'U2', outcome: 'escalated', notes: 'the parity case was red' }],
    ),
    '.shiftwork/checkpoint-job71.json.log.jsonl':
      [
        ev('brief', 'U1'),
        line('U1', 'done', '2026-01-02T00:00:00Z'),
        line('U2', 'blocked', '2026-01-03T00:00:00Z'),
        line('U3', 'done', '2026-01-04T00:00:00Z'),
      ].join('\n') + '\n',
    '.shiftwork/briefs-job71/U1.md': 'Edit src/parse.py, then run `pytest`. See README.md.\n',
    '.shiftwork/briefs-job71/U2.md': 'Port src/parse.py to src/lex.ts; docs/คู่มือ.md explains it.\n',
  };
  write(join(sw, 'archive', 'job71.json.gz'), gzipSync(Buffer.from(JSON.stringify(bundle))));
  write(join(sw, 'archive', 'broken.json.gz'), 'not gzip at all');
  write(join(sw, 'archive', 'notutf8.json.gz'), gzipSync(Buffer.from([0x7b, 0xff, 0x7d])));
  // The plain job's archive: shadowed by the live checkpoint below.
  write(
    join(sw, 'archive', 'plainjob.json.gz'),
    gzipSync(
      Buffer.from(
        JSON.stringify({
          '.shiftwork/checkpoint-plainjob.json': ckpt('plainjob', [['P1', 'archived title', 'x.md']]),
          '.shiftwork/checkpoint-plainjob.json.log.jsonl': line('P1', 'done', '2026-01-05T00:00:00Z'),
        }),
      ),
    ),
  );

  // job72, live: every status, the uncommitted marker, junk lines, outside briefs.
  write(
    join(sw, 'checkpoint-job72.json'),
    ckpt(
      'job72',
      [
        ['U1', 'fix the lexer', '.shiftwork/briefs-job72/U1.md'],
        ['U2', 'drop this', '.shiftwork/briefs-job72/U2.md'],
        ['U3', 'still going', '.shiftwork/briefs-job72/U2.md'],
        ['U4', 'taken back', '.shiftwork/briefs-job72/U2.md'],
        ['U5', 'never clocked out', '.shiftwork/briefs-job72/U2.md'],
        ['😀', 'astral unit', './.shiftwork/briefs-job72/astral.md'],
        ['！', 'fullwidth unit', '.shiftwork/briefs-job72/astral.md'],
        ['U6', 'absolute brief', join(base, 'outside.md')],
        ['U7', 'dotdot brief', '../outside.md'],
        ['U8', 'symlinked brief', '.shiftwork/out.md'],
      ],
      [
        { unit: 'U4', outcome: 'first try failed' },
        { unit: 'U4', outcome: 'second try failed', notes: '' },
      ],
    ),
  );
  write(join(sw, 'briefs-job72', 'U1.md'), 'Fix ./src/lex.ts:12 and src/lex.ts. Not .git/config, not .shiftwork/briefs-job72/U1.md, not src/missing.py.\n');
  write(join(sw, 'briefs-job72', 'U2.md'), 'nothing to see\n');
  write(join(sw, 'briefs-job72', 'astral.md'), 'Paths docs/😀.md and docs/！.md.\n');
  symlinkSync(join(base, 'outside.md'), join(sw, 'out.md'));
  write(
    join(sw, 'checkpoint-job72.json.log.jsonl'),
    [
      line('U1', 'in_progress', '2026-02-01T00:00:00Z'),
      line('U1', 'done', '2026-02-02T00:00:00Z'),
      '{"unit":"U1","role":"implementer","status":"blocked","ts":"2026-02-09T00:00:00Z","x":NaN}',
      '{"unit":"U1","status":["done"],"ts":"2026-02-09T00:00:00Z"}',
      line('U2', 'dropped', '2026-02-03T00:00:00Z'),
      line('U3', 'in_progress', '2026-02-03T00:00:00Z') + '\r',
      line('U4', 'blocked', '2026-02-04T00:00:00Z'),
      line('U4', 'done', '2026-02-05T00:00:00Z'),
      ev('uncommitted', 'U4'),
      line('U2', 'done', '2026-02-09T00:00:00Z') + ' ' + line('U3', 'done', '2026-02-09T00:00:00Z'),
      '﻿' + line('U3', 'done', '2026-02-09T00:00:00Z'),
      line('😀', 'done', '2026-02-06T00:00:00Z'),
      line('！', 'done', '2026-02-06T00:00:00Z'),
      line('U6', 'done', '2026-02-07T00:00:00Z'),
      line('U7', 'done', '2026-02-07T00:00:00Z'),
      line('U8', 'done', '2026-02-07T00:00:00Z'),
      '{not json',
      '[1, 2]',
      '',
    ].join('\n'),
  );

  // A plain checkpoint named by job.id, shadowing its archive.
  write(join(sw, 'checkpoint.json'), ckpt('plainjob', [['P1', 'live title', 'README.md']]));
  write(join(sw, 'checkpoint.json.log.jsonl'), line('P1', 'done', '2026-01-05T00:00:00Z') + '\n');
  // Refused: a BOM'd checkpoint; a checkpoint with no ledger.
  write(join(sw, 'checkpoint-bom.json'), '﻿' + ckpt('bom', [['B1', 'bom', 'x.md']]));
  write(join(sw, 'checkpoint-bom.json.log.jsonl'), line('B1', 'done', '2026-01-01T00:00:00Z') + '\n');
  write(join(sw, 'checkpoint-noledger.json'), ckpt('noledger', [['N1', 'n', 'x.md']]));
  return root;
}

/** A linked worktree of `main`, with a job of its own. */
function worktreeRoot(base, main) {
  const gd = join(main, '.git', 'worktrees', 'wt');
  write(join(gd, 'commondir'), '../..\n');
  const root = join(base, 'wt');
  write(join(root, '.git'), `gitdir: ${gd}\n`);
  write(join(root, 'src', 'parse.py'), 'x\n');
  write(join(root, '.shiftwork', 'checkpoint-job80.json'), ckpt('job80', [['W1', 'fix the parser again', 'brief.md']]));
  write(join(root, 'brief.md'), 'Edit src/parse.py.\n');
  write(join(root, '.shiftwork', 'checkpoint-job80.json.log.jsonl'), line('W1', 'done', '2026-04-01T00:00:00Z') + '\n');
  return root;
}

function noRepoRoot(base) {
  const root = join(base, 'norepo');
  write(join(root, '.shiftwork', 'checkpoint-job90.json'), ckpt('job90', [['X1', 'outside any repo', 'x.md']]));
  write(join(root, '.shiftwork', 'checkpoint-job90.json.log.jsonl'), line('X1', 'blocked', '2026-05-01T00:00:00Z') + '\n');
  return root;
}

const WORDS = Array.from({ length: 20 }, (_, i) => `term${String.fromCharCode(97 + i)}`);
const PIECE_SETS = [
  // df and KEYWORDS_TOP: `common` is in 3 of 4 (dropped), `beta` in 2 of 4 (kept).
  [
    { prompt: `${WORDS.join(' ')} termt terms common`, tools: [], paths: [] },
    { prompt: 'common beta', tools: [], paths: [] },
    { prompt: 'common gamma ไทยภาษา', tools: [], paths: [] },
    { prompt: 'beta delta', tools: [], paths: [] },
  ],
  // n-grams of the tool sequence; a single tool has none.
  [
    { prompt: 'run the tests', tools: ['Read', 'Edit', 'Bash', 'Edit'], paths: ['a.py'] },
    { prompt: 'one tool', tools: ['Read'], paths: [] },
    { prompt: '', tools: [], paths: [] },
  ],
];

const sig = (k, g, p) => ({ keywords: k, ngrams: g, paths: p });
const BOUNDARY = [sig(['k1', 'k2'], ['g1', 'g2', 'g3'], ['p1', 'p2']), sig(['k1'], ['g1', 'g2'], ['p2', 'p3'])];
const PAIRS = [
  BOUNDARY,
  [sig(['k1', 'k2'], ['g1', 'g2', 'g3'], ['p1', 'p2']), sig(['k1'], ['g1'], ['p2', 'p3'])],
  [sig(['k1', 'k2'], [], ['p1']), sig(['k1', 'k2'], [], ['p1'])],
  [sig(['k1'], [], []), sig(['k1', 'k2'], [], [])],
  [sig([], [], []), sig([], [], [])],
  [sig(['ไทย', 'ภาษา'], ['Read>Edit'], []), sig(['ไทย'], ['Read>Edit', 'Edit>Bash'], [])],
  [sig(['a', 'b', 'c'], [], ['x']), sig(['d'], [], ['y'])],
];

function runNode(sm, payload) {
  const sigs = (pieces) => {
    const [df, n] = sm.docFreq(pieces);
    return pieces.map((p) => sm.signatureDict(sm.signature(p, df, n)));
  };
  const out = { pieces: [], root_signatures: [], set_signatures: [], similarity: [] };
  for (const root of payload.roots) {
    const pieces = sm.shiftworkPieces(root);
    out.pieces.push(pieces.map(sm.pieceDict));
    out.root_signatures.push(sigs(pieces));
  }
  out.repo_keys = payload.repo_keys.map((p) => sm.repoKey(p));
  for (const set of payload.piece_sets) {
    out.set_signatures.push(
      sigs(
        set.map((d, i) => ({
          id: `set/${i}`,
          source: 'session',
          ts: '',
          repo: '',
          prompt: d.prompt,
          tools: d.tools,
          paths: new Set(d.paths),
          ok: null,
          signals: {},
          failure: null,
        })),
      ),
    );
  }
  const toSig = (d) => ({ keywords: new Set(d.keywords), ngrams: new Set(d.ngrams), paths: new Set(d.paths) });
  for (const [a, b] of payload.pairs) {
    const s = sm.similarity(toSig(a), toSig(b));
    out.similarity.push([s[0], s[1], sm.meets(s)]);
  }
  return out;
}

export async function run(ctx) {
  const sm = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'skillmine.js')).href);
  const base = join(ctx.scratch, 'skill-miner');
  const home = join(base, 'home');
  mkdirSync(home, { recursive: true });
  const main = mainRoot(base);
  const wt = worktreeRoot(base, main);
  const norepo = noRepoRoot(base);
  const payload = {
    roots: [main, wt, norepo, join(base, 'does-not-exist')],
    repo_keys: [main, wt, norepo, join(main, 'src')],
    piece_sets: PIECE_SETS,
    pairs: PAIRS,
  };
  const py = ctx.runPython(REF, payload, { HOME: home, USERPROFILE: home });
  const nd = runNode(sm, payload);
  const cases = [];
  const rootNames = ['main (archived + live + plain)', 'linked worktree', 'no repository', 'missing root'];

  rootNames.forEach((label, i) => {
    cases.push({ name: `shiftwork_pieces — ${label}`, kind: 'json', expected: py.pieces[i], actual: nd.pieces[i] });
    cases.push({
      name: `shiftwork_pieces — ${label} — bytes`,
      kind: 'string',
      expected: JSON.stringify(py.pieces[i]),
      actual: JSON.stringify(nd.pieces[i]),
    });
    cases.push({
      name: `signature — ${label} as one source`,
      kind: 'json',
      expected: py.root_signatures[i],
      actual: nd.root_signatures[i],
    });
  });
  ['main', 'linked worktree', 'no repository', 'a subdirectory of main'].forEach((label, i) => {
    cases.push({ name: `repo_key — ${label}`, kind: 'string', expected: py.repo_keys[i], actual: nd.repo_keys[i] });
  });
  cases.push({
    name: 'repo_key — the worktree shares main\'s key (per side)',
    kind: 'json',
    expected: [true, true],
    actual: [py.repo_keys[1] === py.repo_keys[0] && py.repo_keys[0] !== '', nd.repo_keys[1] === nd.repo_keys[0] && nd.repo_keys[0] !== ''],
  });
  PIECE_SETS.forEach((_, i) => {
    cases.push({
      name: `signature — piece set ${i + 1}`,
      kind: 'json',
      expected: py.set_signatures[i],
      actual: nd.set_signatures[i],
    });
  });
  PAIRS.forEach((_, i) => {
    cases.push({ name: `similarity — pair ${i + 1}`, kind: 'json', expected: py.similarity[i], actual: nd.similarity[i] });
  });

  // ---------------------------------------------------------------------- the literals
  for (const [side, ans] of [
    ['python', py],
    ['node', nd],
  ]) {
    cases.push({
      name: `LITERAL: KEYWORDS_TOP keeps 12 keywords of a 20-term prompt — ${side}`,
      kind: 'json',
      expected: 12,
      actual: ans.set_signatures[0][0].keywords.length,
    });
    cases.push({
      name: `LITERAL: the 1/2 boundary pair is exactly [1, 2] and meets — ${side}`,
      kind: 'json',
      expected: [1, 2, true],
      actual: ans.similarity[0],
    });
    cases.push({
      name: `LITERAL: main root success bits by id — ${side}`,
      kind: 'json',
      expected: [
        ['job71/U1', true],
        ['job71/U2', false],
        ['job71/U3', true],
        ['plainjob/P1', true],
        ['job72/U1', true],
        ['job72/U2', null],
        ['job72/U3', null],
        ['job72/U4', false],
        ['job72/！', true],
        ['job72/😀', true],
        ['job72/U6', true],
        ['job72/U7', true],
        ['job72/U8', true],
      ],
      actual: ans.pieces[0].map((p) => [p.id, p.ok]),
    });
  }
  const n = py.pieces[0].length;
  return { cases, notes: [`${n} shiftwork pieces in the main fixture, ${PAIRS.length} similarity pairs`] };
}
