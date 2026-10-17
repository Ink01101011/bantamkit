/**
 * touch-refs — path references in fact text, resolved through git (#200, E4; job70 T200-2).
 *
 * THE PROPERTY: over the same text the two runtimes extract the same raw references (a `:line`
 * or `:a-b` dropped, a `#symbol` kept, every URL blanked first), resolve each to the same
 * tracked path through the same file set and renames, and name each tracked file by the same
 * shortest unique suffix. Over one fixture git repo they read the same `ls-files`, the same
 * renames in git's order, and the same head print. A reference names a file in the graph
 * (#200 Task 4) and a suffix is what the `[via <file>]` label prints, so a disagreement here
 * is two runtimes linking a fact to different files.
 *
 * HOW. One payload to `ref/touch_ref.py` (`run_refs`), the same calls in-process against
 * `dist/touch/refs.js` and `dist/touch/repo.js`. The fixture repo is built ONCE by this
 * harness under the scratch dir (`git init`, commit, `git mv old.py new.py`, commit,
 * `git mv new.py src/new.py`, commit; then `dup.py` added and moved twice, so the newest rename
 * of one old path must win) and read by both sides.
 *
 * WHAT THE CORPUS IS AIMED AT: each row is tagged; the tags are the case names. Thai beside a
 * path matters because Python's `\w` takes Thai letters and JavaScript's does not, so a regex
 * spelled with `\w` on one side splits there.
 *
 * THE LITERALS. A change applied to both sides leaves every differential green, so three
 * answers are pinned per side: `extract_refs` of the kinds text, `shortest_suffix` of
 * `runtime-ts/src/memory/store.ts`, and the fixture repo's `resolve_ref("old.py")`.
 */
import { execFileSync } from 'node:child_process';
import { mkdirSync, realpathSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'touch-refs';
export const summary = 'touch refs: extract_refs/fact_refs, resolve_ref through renames, shortest_suffix, ls-files/renames/head print';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'touch_ref.py');

const FILES = [
  'runtime-ts/src/memory/store.ts',
  'runtime-py/src/bantamkit/memory/store.py',
  'a/store.ts',
  'b/a/store.ts',
  'docs/memory.md',
  'Makefile',
  'src/ไฟล์.py',
  'src/😀/e.ts',
  '__proto__/x.py',
];

const KINDS =
  'see runtime-ts/src/memory/store.ts:450 and store.py#recall, docs/memory.md:10-20, ' +
  'not https://github.com/x/y/blob/main/docs/memory.md nor 0.37.0 nor e.g. this';
const KINDS_LITERAL = ['runtime-ts/src/memory/store.ts', 'store.py#recall', 'docs/memory.md', 'e.g'];

/** [tag, text]: 41 rows. */
const CORPUS = [
  ['the kinds text of the unit test', KINDS],
  ['plain path', 'edit runtime-ts/src/memory/store.ts now'],
  ['path:line', 'store.py:12 broke'],
  ['path:a-b', 'docs/memory.md:10-20 says'],
  ['path#symbol', 'store.py#recall is slow'],
  ['absolute inside the toplevel', 'open /r/docs/memory.md'],
  ['absolute outside the toplevel', 'open /elsewhere/bantamkit/docs/memory.md'],
  ['absolute outside, two deeper matches (longest wins)', 'open /elsewhere/b/a/store.ts'],
  ['a missing path', 'nope/x.py is gone'],
  ['an ambiguous bare name', 'store.ts is everywhere'],
  ['a URL holding a path', 'https://github.com/x/y/blob/main/docs/memory.md'],
  ['a URL then the same path bare', 'see http://x.io/a/b.md, then a/b.md'],
  ['a URL whose query and userinfo name paths', 'https://h/blob?path=docs/memory.md&x=a.py and https://u@h/b/c.ts'],
  ['version numbers', '0.37.0 and v1.2.3 and 1.0'],
  ['Thai, spaced', 'ไฟล์ store.py แก้แล้ว'],
  ['Thai directly before a path', 'ในstore.py และในdocs/memory.md'],
  ['CRLF lines', 'a/store.ts\r\nb/a/store.ts\r\n'],
  ['a trailing slash', 'docs/ and src/dir/'],
  ['a ~/ path', '~/x/y.md and ~/.claude/settings.json'],
  ['a symbol with dots', 'x.py#Memory.recall_outcome'],
  ['abbreviations', 'e.g. this i.e. that etc.'],
  ['a sentence full stop', 'body names src/Makefile.'],
  ['bare names without an extension', 'run Makefile then README'],
  ['repeats', 'a.py a.py a.py:3 a.py#f a.py#f'],
  ['a ./ prefix', './docs/memory.md'],
  ['other URL schemes', 'file:///Users/x/a.md ssh://git@h/x.git git+https://h/y.js'],
  ['parentheses', '(see docs/memory.md)'],
  ['quotes and backticks', '`store.py` and \'a/b.ts\' and "c.rs"'],
  ['an astral emoji beside a path', '😀a.py and 😀/b.py and src/😀/e.ts'],
  ['dotfiles', '.gitignore and .shiftwork/x.json'],
  ['flags', '-v and --flag=x.py and -x.y'],
  // platform-checked: this is fact TEXT handed to a regex on both sides, never a filename; no
  // file is opened at it, so the backslash means the same on every OS.
  ['a Windows path', 'C:\\Users\\x\\a.py'],
  ['extension lengths', 'a.verylong b.abcdefgh c.abcdefghi'],
  ['digits in an extension', 'a.mp4 b.7z c.h264'],
  ['a colon without digits', 'store.py:abc'],
  ['a hash without an identifier', 'store.py#123'],
  ['a doubled slash', 'a//b.py'],
  ['a symbol on a directory', 'src/#x'],
  ['the empty text', ''],
  ['underscores', '__init__.py and _x/y_ and __proto__/x.py'],
  ['tabs and dotted words', 'a.py\tb.py foo.bar.baz a/b/c'],
];

const FIELDS = [
  { description: 'store.ts first', keywords: ['docs/memory.md', 'store.ts'], body: 'body names src/Makefile.' },
  { description: '', keywords: [], body: '' },
  { description: 'x.py#f', keywords: ['x.py', 'x.py#f'], body: 'x.py:3 and https://h/x.py' },
  { description: 'ไฟล์ store.py', keywords: ['ในdocs/memory.md'], body: 'a/b\r\nc/d.ts' },
];

/** a1 -> b1 -> docs/memory.md is a chain; x.md <-> y.md is a cycle (nothing after 32 hops). */
const RENAMES = {
  'old/memory.md': 'docs/memory.md',
  'a1.py': 'b1.py',
  'b1.py': 'runtime-py/src/bantamkit/memory/store.py',
  'x.md': 'y.md',
  'y.md': 'x.md',
  'gone.py': 'also-gone.py',
  'store.ts': 'a/store.ts',
};
const EXTRA_RAW = [
  'old/memory.md',
  'a1.py',
  'x.md',
  'gone.py',
  'store.ts',
  '/r/a/store.ts#f',
  '/r/docs/',
  '/r',
  '/rx/docs/memory.md',
  './a/store.ts',
  'Makefile',
  'ไฟล์.py',
  '__proto__/x.py#constructor',
  'constructor',
  '',
];
const PROBES = ['store.ts', 'a/store.ts', 'x/b/a/store.ts', 'memory.md', 'store.py', 'e.ts', '😀/e.ts', 'Makefile', 'nothing'];

function fixtureRepo(scratch) {
  const r = join(scratch, 'touch-refs-repo');
  mkdirSync(r, { recursive: true });
  const g = (...a) =>
    execFileSync('git', ['-c', 'user.email=t@t', '-c', 'user.name=t', '-c', 'commit.gpgsign=false', '-C', r, ...a], {
      stdio: 'pipe',
      env: { ...process.env, GIT_CONFIG_NOSYSTEM: '1', LC_ALL: 'C' },
    });
  g('init', '-q');
  writeFileSync(join(r, 'old.py'), 'x\n');
  writeFileSync(join(r, 'keep.md'), 'k\n');
  g('add', '.');
  g('commit', '-qm', 'one');
  g('mv', 'old.py', 'new.py');
  g('commit', '-qm', 'two');
  mkdirSync(join(r, 'src'));
  g('mv', 'new.py', 'src/new.py');
  g('commit', '-qm', 'three');
  // one old path renamed twice: the NEWEST rename of `dup.py` is the one that counts
  writeFileSync(join(r, 'dup.py'), 'first\n');
  g('add', 'dup.py');
  g('commit', '-qm', 'four');
  g('mv', 'dup.py', 'first.py');
  g('commit', '-qm', 'five');
  writeFileSync(join(r, 'dup.py'), 'second\n');
  g('add', 'dup.py');
  g('commit', '-qm', 'six');
  g('mv', 'dup.py', 'second.py');
  g('commit', '-qm', 'seven');
  return realpathSync(r);
}

function runNode(refs, repoMod, req) {
  const fs = new refs.FileSet(req.files);
  const res = (r) => (r === null ? null : [r[0], r[1]]);
  const out = {
    extract: req.texts.map((t) => refs.extractRefs(t)),
    fact_refs: req.fields.map((f) => refs.factRefs(f.description, f.keywords, f.body)),
    resolve: req.resolve.map((r) => res(refs.resolveRef(r, fs, req.renames, req.top))),
    suffix: req.files.map((f) => [refs.shortestSuffix(f, fs), fs.matches(refs.shortestSuffix(f, fs))]),
    matches: req.probes.map((p) => fs.matches(p)),
    repo: null,
  };
  if (req.repo) {
    const repo = repoMod.findRepo(req.repo);
    if (repo !== null) {
      const files = repoMod.lsFiles(repo);
      const moved = repoMod.renames(repo);
      const rfs = new refs.FileSet(files ?? []);
      out.repo = {
        ls_files: files,
        renames: moved === null ? null : [...moved],
        resolve: req.repo_resolve.map((r) => res(refs.resolveRef(r, rfs, moved ?? new Map(), repo.top))),
        head_print: repoMod.headPrint(repo),
      };
    }
  }
  return out;
}

function literalCases(pySide, nodeSide, label, expected) {
  return [
    { name: `${label} — python`, kind: 'json', expected, actual: pySide },
    { name: `${label} — node`, kind: 'json', expected, actual: nodeSide },
  ];
}

export async function run(ctx) {
  const refs = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'touch', 'refs.js')).href);
  const repoMod = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'touch', 'repo.js')).href);
  const cases = [];
  const notes = [];

  const texts = CORPUS.map(([, t]) => t);
  // Every raw reference either side extracted, then the hand-picked ones, deduped in order.
  const seed = new Set([...texts.flatMap((t) => refs.extractRefs(t)), ...EXTRA_RAW]);
  const repo = fixtureRepo(ctx.scratch);
  const req = {
    suite: 'touch-refs',
    texts,
    fields: FIELDS,
    files: FILES,
    renames: RENAMES,
    top: '/r',
    resolve: [...seed],
    probes: PROBES,
    repo,
    repo_resolve: ['old.py', 'new.py', 'src/new.py', 'keep.md', `${repo}/old.py`, 'missing.py', 'dup.py'],
  };
  const py = ctx.runPython(REF, req);
  const nd = runNode(refs, repoMod, req);

  // The resolve list is seeded from the Node extraction; a Python-only raw would be missing
  // from it, but then the extract case below is already red.
  CORPUS.forEach(([tag], i) =>
    cases.push({ name: `extract_refs — ${tag}`, kind: 'json', expected: py.extract[i], actual: nd.extract[i] }),
  );
  FIELDS.forEach((f, i) =>
    cases.push({ name: `fact_refs — fields #${i}`, kind: 'json', expected: py.fact_refs[i], actual: nd.fact_refs[i] }),
  );
  req.resolve.forEach((raw, i) =>
    cases.push({ name: `resolve_ref — ${JSON.stringify(raw)}`, kind: 'json', expected: py.resolve[i], actual: nd.resolve[i] }),
  );
  FILES.forEach((f, i) =>
    cases.push({ name: `shortest_suffix and its round trip — ${f}`, kind: 'json', expected: py.suffix[i], actual: nd.suffix[i] }),
  );
  PROBES.forEach((p, i) =>
    cases.push({ name: `FileSet.matches — ${p}`, kind: 'json', expected: py.matches[i], actual: nd.matches[i] }),
  );
  for (const key of ['ls_files', 'renames', 'resolve', 'head_print']) {
    cases.push({
      name: `fixture repo (old.py -> new.py -> src/new.py; dup.py moved twice) — ${key}`,
      kind: 'json',
      expected: py.repo?.[key] ?? '<no repo>',
      actual: nd.repo?.[key] ?? '<no repo>',
    });
  }
  // The round trip holds on each side by itself, not only equally.
  for (const [side, got] of [['python', py], ['node', nd]]) {
    cases.push({
      name: `matches(shortest_suffix(f)) == [f] for every fixture file — ${side}`,
      kind: 'json',
      expected: FILES.map((f) => [f]),
      actual: got.suffix.map(([, m]) => m),
    });
  }

  cases.push(...literalCases(py.extract[0], nd.extract[0], 'LITERAL: extract_refs of the kinds text', KINDS_LITERAL));
  const at = FILES.indexOf('runtime-ts/src/memory/store.ts');
  cases.push(
    ...literalCases(py.suffix[at][0], nd.suffix[at][0], 'LITERAL: shortest_suffix("runtime-ts/src/memory/store.ts")', 'memory/store.ts'),
  );
  cases.push(
    ...literalCases(py.repo?.resolve[0] ?? null, nd.repo?.resolve[0] ?? null, 'LITERAL: resolve_ref("old.py") follows two git mv to src/new.py', [
      'src/new.py',
      null,
    ]),
  );
  notes.push(`${CORPUS.length} texts, ${req.resolve.length} raw references resolved, fixture repo at <scratch>/touch-refs-repo`);
  return { cases, notes };
}
