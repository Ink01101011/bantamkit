/**
 * store — the whole store directory, Python against Node, after the same call.
 *
 * THE PROPERTY: given the same store on disk and the same call, the two runtimes leave the
 * directory in BYTE-IDENTICAL states and return the same string. Not "equivalent".
 * `index.md` is in the diff on purpose — its byte length is an input to the budget, so a
 * difference there changes whether the NEXT save is refused.
 *
 * HOW A SCENARIO WORKS. A fixture is materialised twice, into `py/` and `node/`, from one
 * spec, so both sides start from the same bytes. Python runs the call list through
 * `ref/store_ref.py`; Node runs the same list through `dist/memory/store.js`. Then the suite
 * walks both trees with the SAME walker and compares: the returned values as JSON, and a
 * manifest of every path, mode class and byte of content as BYTES. A scenario that writes
 * nothing still gets its tree compared — "it raised before touching disk" is a claim about
 * the directory, and this is where it is checked rather than asserted.
 *
 * The real 65-fact store is one of the fixtures, copied to scratch. It is never opened in
 * place: the defect this module reimplements destroyed that store's index once.
 */
import { execFileSync } from 'node:child_process';
import {
  chmodSync,
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  readlinkSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
} from 'node:fs';
import { EOL } from 'node:os';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'store';
export const summary = 'save/recall/index: the directory after the call, byte for byte';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'store_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

const TODAY = '2026-08-23';
const DEFAULT_INDEX_BUDGET = 24_000;

/** Null on both sides stays JSON null; see the same note in `store_ref.py`. */
const nullable = (v) => (v === null || v === undefined ? null : b64(String(v)));

/**
 * Take the fixture's own root out of every message before comparing.
 *
 * The two sides run in `py/` and `node/` under one scratch bed, and `_unreadable` and
 * `OSError` both PRINT the path — so an un-scrubbed comparison would fail on the one
 * difference the harness itself created. The path is not dropped from the check: it is
 * replaced by a marker, so a message that named the WRONG path still differs.
 */
function scrub(results, root) {
  const walk = (value) => {
    if (Array.isArray(value)) return value.map(walk);
    if (value && typeof value === 'object') {
      if (value.error) {
        return {
          error: {
            type: value.error.type,
            message: b64(unb64(value.error.message).split(root).join('<ROOT>')),
          },
        };
      }
      return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, walk(v)]));
    }
    return value;
  };
  return walk(results);
}

// ------------------------------------------------------------------------- fixtures

/** The frontmatter a Python-written fact carries, spelled out so a fixture is bytes. */
const factFile = (n, { description = `about ${n}`, type = 'project', created = '2026-08-01', last = 'null', links = '[]', body = 'b' } = {}) =>
  `---\nname: ${n}\ndescription: ${description}\ntype: ${type}\ncreated: ` +
  `${created === null ? 'null' : `'${created}'`}\nlast_recalled: ${last}\nlinks: ${links}\n---\n\n${body}\n`;

/**
 * Where the real store lives. Copied, with timestamps, so the `created`-from-mtime fallback
 * reads the same number on both sides instead of two `cp` clock samples.
 */
function realStore(ctx) {
  const explicit = ctx.options.corpus ?? process.env.BANTAMKIT_CONFORMANCE_CORPUS;
  const candidates = [];
  if (explicit) candidates.push(dirname(explicit));
  candidates.push(join(ctx.repoRoot, '.bantamkit', 'memory'));
  try {
    const commonDir = execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], {
      cwd: ctx.repoRoot,
      encoding: 'utf8',
    }).trim();
    candidates.push(join(dirname(commonDir), '.bantamkit', 'memory'));
  } catch {
    /* not a checkout; the other candidates still apply */
  }
  return candidates.find((c) => existsSync(join(c, 'facts'))) ?? null;
}

/** Materialise one fixture spec at `root`. Modes are applied last and by the caller. */
function materialise(root, spec) {
  mkdirSync(root, { recursive: true });
  if (spec.copyFrom) cpSync(spec.copyFrom, root, { recursive: true, preserveTimestamps: true });
  for (const dir of spec.dirs ?? []) mkdirSync(join(root, dir), { recursive: true });
  for (const [path, content] of Object.entries(spec.files ?? {})) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), typeof content === 'string' ? Buffer.from(content, 'utf8') : content);
  }
  for (const [link, target] of spec.symlinks ?? []) symlinkSync(target, join(root, link));
  for (const [path, when] of Object.entries(spec.mtimes ?? {})) utimesSync(join(root, path), when, when);
}

const applyModes = (root, spec, on) => {
  for (const [path, mode] of Object.entries(spec.modes ?? {})) {
    chmodSync(join(root, path), on ? mode : 0o755);
  }
};

/**
 * Every path under `root`, with what it is and what it holds.
 *
 * Symlink targets and directory entries are in the manifest, not just file bytes: a port
 * that answered correctly while leaving an `.md.tmp` behind, or that followed a symlink it
 * should have left alone, would pass a content-only diff.
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
      if (st.isSymbolicLink()) lines.push(`${rel}\tlink\t${readlinkSync(full)}`);
      else if (st.isDirectory()) {
        lines.push(`${rel}\tdir`);
        walk(full);
      } else {
        const bytes = readFileSync(full);
        lines.push(`${rel}\tfile\t${bytes.length}\t${bytes.toString('base64')}`);
      }
    }
  };
  walk(root);
  return `${lines.join('\n')}\n`;
}

// ------------------------------------------------------------------------ call shapes

const save = (type, name, description, body, links = []) => ({
  op: 'save',
  args: [b64(type), b64(name), b64(description), b64(body), links.map(b64)],
});
const recall = (query, k = null, stamp = true) => ({ op: 'recall', args: [b64(query), k, stamp] });
const indexText = () => ({ op: 'index_text' });

/** The Node side of one scenario, shaped exactly like `store_ref.py`'s answer. */
function runNode(store, request) {
  const results = [];
  const encode = (e) => ({ error: { type: e?.name ?? 'Error', message: b64(String(e?.message ?? e)) } });
  let s;
  try {
    s = new store.MemoryStore(request.root, {
      today: () => request.today,
      create: request.create ?? true,
      ...(request.index_budget === null ? {} : { indexBudget: request.index_budget }),
      ...(request.k === null ? {} : { k: request.k }),
    });
  } catch (e) {
    return { results: [encode(e)] };
  }
  for (const call of request.calls) {
    try {
      if (call.op === 'save') {
        const [type, name, description, body, links] = call.args;
        const r = s.save(unb64(type), unb64(name), unb64(description), unb64(body), links.map(unb64));
        results.push({ status: r.status, name: b64(r.name), similar: r.similar === null ? null : b64(r.similar) });
      } else if (call.op === 'recall') {
        const [query, k, stamp] = call.args;
        results.push(
          s.recall(unb64(query), k, stamp).map((f) => ({
            name: nullable(f.name),
            description: nullable(f.description),
            type: nullable(f.type),
            body: b64(f.body),
            links: f.links.map((l) => b64(String(l))),
            last_recalled: nullable(f.last_recalled),
            created: nullable(f.created),
          })),
        );
      } else if (call.op === 'index_text') {
        results.push({ index_text: b64(s.indexText()) });
      } else {
        throw new Error(`unknown call op ${call.op}`);
      }
    } catch (e) {
      results.push(encode(e));
    }
  }
  return { results };
}

// -------------------------------------------------------------------------- scenarios

/**
 * Each entry is one call list against one fixture. The `ruling` field marks a scenario whose
 * ANSWERS are required to differ — the trees are still required to match, because a message
 * this port has ruled on must not also move a byte on disk.
 */
function scenarios(ctx, real) {
  const three = {
    dirs: ['facts', 'archive'],
    files: {
      'facts/fact-0.md': factFile('fact-0', { description: 'w0a w0b w0c w0d' }),
      'facts/fact-1.md': factFile('fact-1', { description: 'w1a w1b w1c w1d' }),
      'facts/fact-2.md': factFile('fact-2', { description: 'w2a w2b w2c w2d' }),
      'index.md':
        '- [[fact-0]] (project) — w0a w0b w0c w0d\n' +
        '- [[fact-1]] (project) — w1a w1b w1c w1d\n' +
        '- [[fact-2]] (project) — w2a w2b w2c w2d\n',
    },
  };
  const empty = { dirs: ['facts', 'archive'] };
  const malformed = (body) => ({ dirs: ['facts', 'archive'], files: { 'facts/broken.md': body } });

  const list = [
    ['save into an empty store', empty, {}, [save('project', 'a-fact', 'a description', 'the body')]],
    ['three saves in a row', empty, {}, [
      save('reference', 'zulu', 'about zulu', 'b'),
      save('reference', 'alpha', 'about alpha', 'b'),
      save('reference', 'mike', 'about mike', 'b'),
    ]],
    ['save refused as a duplicate', three, {}, [save('project', 'probe', 'w0a w0b w0c w0d', 'b')]],
    ['save as an update keeps created', three, {}, [
      save('feedback', 'fact-0', 'w0a w0b w0c w0d', 'rewritten'),
    ]],
    ['save with links, unicode and an em dash', empty, {}, [
      save('user', 'thai-fact', 'ภาษาไทย — a description long enough to reach the eighty column wrap',
        'body\n\nwith blanks\n\n', ['a', "it's", 'x'.repeat(100)]),
    ]],
    ['every validation refusal', empty, {}, [
      save('notes', 'a', 'd', 'b'),
      save('project', 'Bad Name', 'd', 'b'),
      save('project', '', 'd', 'b'),
      save('project', 'a', '   \n', 'b'),
      // Python's `$` matches before a trailing newline and JS's does not, so this SAVES.
      save('project', 'a\n', 'd', 'b'),
      save('project', 'a\n\n', 'unrelated words entirely', 'b'),
    ]],
    ['budget refuses a new fact and rolls it back', three, { index_budget: 130 }, [
      save('project', 'probe', 'an entirely unrelated probe subject line', 'b'),
      indexText(),
    ]],
    ['budget refuses an update and puts the bytes back', three, { index_budget: 130 }, [
      save('project', 'fact-0', `w0a w0b w0c w0d${' padding'.repeat(6)}`, 'b'),
      indexText(),
    ]],
    ['recall hits, ordered and stamped', three, {}, [recall('w0a w1a w2a fact', 3, true)]],
    ['recall misses and writes nothing', three, {}, [recall('nothing-shares-this', 3, true)]],
    ['recall without stamping', three, {}, [recall('w0a', 3, false)]],
    ['recall k=1', three, {}, [recall('w0a w1a w2a fact', 1, true)]],
    // Astral names: JS sorts by UTF-16 code unit and Python by codepoint, and they disagree.
    ['the astral name boundary, in the index and the tie-break', {
      dirs: ['facts', 'archive'],
      files: {
        'facts/\u{1f414}.md': factFile('"\u{1f414}"', { description: 'shared token' }),
        'facts/！.md': factFile('"！"', { description: 'shared token' }),
        'facts/zz.md': factFile('zz', { description: 'shared token' }),
      },
    }, {}, [indexText(), recall('shared', 3, false)]],
    ['a first run: no facts directory at all', { dirs: [] }, { create: false }, [
      indexText(), recall('anything', 3, true),
    ]],
    ['facts is a regular file', { files: { facts: 'this is not a facts directory\n' } }, { create: false }, [
      indexText(), recall('anything', 3, true),
    ]],
    ['facts is a regular file and save runs mkdir first', { files: { facts: 'not a directory\n' } }, {}, [
      save('project', 'a', 'd', 'b'),
    ]],
    ['facts is a dangling symlink', { symlinks: [['facts', './nowhere']] }, { create: false }, [
      indexText(), recall('anything', 3, true),
    ]],
    ['facts is unlistable at 0o311', { ...three, modes: { facts: 0o311 } }, {}, [
      save('project', 'probe', 'an entirely unrelated probe', 'body'), indexText(),
    ]],
    ['facts is unreadable at 0o000', { ...three, modes: { facts: 0o000 } }, { create: false }, [
      indexText(),
    ]],
    ['the counted set: dotfiles in, .txt and .md.tmp out, a directory named x.md in', {
      dirs: ['facts', 'archive', 'facts/adir.md'],
      files: {
        'facts/plain.md': factFile('plain'),
        'facts/.hidden.md': factFile('hidden'),
        'facts/notes.txt': 'ignored\n',
        'facts/plain.md.tmp': 'ignored\n',
      },
    }, { create: false }, [indexText()]],
    ['malformed: one part', malformed('no frontmatter at all\n'), { create: false }, [indexText()]],
    ['malformed: two parts', malformed('---\nname: broken\n'), { create: false }, [indexText()]],
    ['malformed: empty frontmatter', malformed('---\n---\n\nbody\n'), { create: false }, [indexText()]],
    ['malformed: frontmatter is a scalar', malformed('---\njust a scalar\n---\n\nbody\n'), { create: false }, [indexText()]],
    ['malformed: frontmatter is a sequence', malformed('---\n- a\n- b\n---\n\nbody\n'), { create: false }, [indexText()]],
    ['malformed: no name key', malformed('---\ndescription: d\ntype: project\n---\n\nbody\n'), { create: false }, [indexText()]],
    ['malformed: no type key', malformed('---\nname: b\ndescription: d\n---\n\nbody\n'), { create: false }, [indexText()]],
    ['a fact file that is not utf-8', {
      dirs: ['facts', 'archive'],
      files: { 'facts/bad.md': Buffer.from([0x2d, 0x2d, 0x2d, 0x0a, 0x61, 0xff, 0x62, 0x0a]) },
    }, { create: false }, [indexText()]],
    ['created falls back to the file mtime', {
      dirs: ['facts', 'archive'],
      files: { 'facts/old.md': '---\nname: old\ndescription: d\ntype: project\nlinks: []\n---\n\nb\n' },
      mtimes: { 'facts/old.md': 1755990000 },
    }, { create: false }, [recall('d', 3, false)]],
    ['a null name interpolates as Python\'s None, on disk and in the index', {
      dirs: ['facts', 'archive'],
      files: { 'facts/nameless.md': '---\nname:\ndescription: d\ntype: project\nlinks: []\n---\n\nb\n' },
      mtimes: { 'facts/nameless.md': 1755990000 },
    }, { create: false }, [indexText(), recall('d', 3, true)]],
    ['links given as a string are iterated into characters', {
      dirs: ['facts', 'archive'],
      files: { 'facts/strlinks.md': factFile('strlinks', { links: 'abc' }) },
    }, { create: false }, [recall('about strlinks', 3, true)]],
    ['two facts with no ascii tokens never collide', empty, {}, [
      save('project', 'aa', 'ความจำ', 'b'), save('project', 'bb', 'ความจำ', 'b'),
    ]],
    // The index of `three` is exactly 129 bytes, so this is the `>` boundary from both
    // sides. Without the equal case, `size >= budget` survives every other scenario.
    ['an index exactly at the budget is allowed', three, { index_budget: 129 }, [
      save('project', 'fact-0', 'w0a w0b w0c w0d', 'rewritten'), indexText(),
    ]],
    ['an index one byte over the budget is refused', three, { index_budget: 128 }, [
      save('project', 'fact-0', 'w0a w0b w0c w0d', 'rewritten'), indexText(),
    ]],
    // The rollback REBUILDS the index, and that is only observable when the index on disk
    // was wrong to begin with — which is exactly the state the original defect left behind.
    ['a budget rollback rebuilds an index that was already stale',
      { ...three, files: { ...three.files, 'index.md': 'stale\n' } }, { index_budget: 130 }, [
        save('project', 'probe', 'an entirely unrelated probe subject line', 'b'),
      ]],
    // `_write_fact` writes `<name>.md.tmp` and renames. With `facts/` read-only the write
    // is what fails, and the path in the message is the only place the tmp step shows.
    ['a read-only facts directory fails on the tmp write, and says so',
      { ...three, modes: { facts: 0o555 } }, {}, [
        save('project', 'fact-0', 'w0a w0b w0c w0d', 'rewritten'),
      ]],
    // Readable but not traversable: the listing succeeds and the STAT does not, which is
    // the one arm where `Path.exists()` re-raises instead of answering False.
    ['facts is readable but not traversable', { ...empty, modes: { facts: 0o644 } }, {}, [
      save('project', 'a', 'a description', 'b'),
    ]],
    ['the fact path is a directory', {
      dirs: ['facts', 'archive', 'facts/x.md'],
    }, {}, [save('project', 'x', 'a description', 'b')]],
    ['created as an empty string still falls back to the mtime', {
      dirs: ['facts', 'archive'],
      files: { 'facts/e.md': "---\nname: e\ndescription: d\ntype: project\ncreated: ''\nlinks: []\n---\n\nb\n" },
      mtimes: { 'facts/e.md': 1755990000 },
    }, { create: false }, [recall('d', 3, false)]],
    // `str.strip()` is not `String.trim()`: they disagree on six codepoints, and the
    // description is stripped before it is written.
    ['a description stripped at the six codepoints the two runtimes disagree on', empty, {}, [
      save('project', 'ws', '\u001c a description \u0085', 'b'),
      save('project', 'ws2', '\ufeff another description entirely \ufeff', 'b'),
    ]],
  ];

  if (real) {
    list.push(
      ['the real store: index_text and the budget', { copyFrom: real }, { create: false }, [indexText()]],
      ['the real store: recall stamps three python-written files', { copyFrom: real }, {}, [
        recall('memory store budget index', 3, true),
      ]],
      ['the real store: a save lands beside 65 python-written facts', { copyFrom: real }, {}, [
        save('project', 'job38-conformance-probe', 'a probe subject nothing else here shares', 'b'),
      ]],
    );
  }

  const ruled = [
    [
      'malformed: outside the codec grammar',
      malformed('---\nname: [unclosed\n---\n\nbody\n'),
      { create: false },
      [indexText()],
      "PyYAML answers a document outside the emitter's grammar with a ScannerError carrying " +
        'its marks and a rendered snippet; this port answers with parseFrontmatter\'s own ' +
        'reason. Matching would mean porting PyYAML\'s scanner diagnostics — a surface larger ' +
        'than the store — for strings no runtime-py test pins. The prefix "malformed fact ' +
        'file <name>: ", which is what names the file, IS identical and is pinned by the ' +
        'malformed cases above; only the reason after it differs, and the TREE still has to ' +
        'match, so the ruling cannot hide a byte moving on disk.',
    ],
    [
      'a sequence where a name should be',
      {
        dirs: ['facts', 'archive'],
        files: { 'facts/seq.md': '---\nname:\n- a\n- b\ndescription: d\ntype: project\nlinks: []\n---\n\nb\n' },
        mtimes: { 'facts/seq.md': 1755990000 },
      },
      { create: false },
      [indexText()],
      'A `name` that resolved to a LIST is interpolated by Python as `[\'a\', \'b\']` and by ' +
        'JS as `a,b`. `pyText` reproduces `None` because a null name is a plausible ' +
        'hand-edit; a list is not, and reproducing `list.__repr__` means reproducing ' +
        '`str.__repr__`, which means the Unicode printability table. Both runtimes produce ' +
        'garbage for this file — the ruling is about WHICH garbage, and it is written down ' +
        'here rather than discovered later.',
    ],
  ];

  return { list, ruled };
}

// ------------------------------------------------------------------------------- run

export async function run(ctx) {
  const store = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'store.js')).href);
  const pyfs = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'pyfs.js')).href);
  const cases = [];
  const notes = [];

  const real = realStore(ctx);
  notes.push(real ? `real corpus: ${real}` : 'real corpus: NOT FOUND — the synthetic fixtures ran alone');

  const { list, ruled } = scenarios(ctx, real);
  let n = 0;
  for (const [label, spec, options, calls, ruling] of [...list, ...ruled.map((r) => [...r])]) {
    n += 1;
    const bed = join(ctx.scratch, `s${String(n).padStart(2, '0')}`);
    const roots = {};
    for (const side of ['py', 'node']) {
      roots[side] = join(bed, side);
      materialise(roots[side], spec);
      applyModes(roots[side], spec, true);
    }
    const request = (root) => ({
      op: 'run',
      root,
      today: TODAY,
      index_budget: options.index_budget ?? null,
      k: options.k ?? null,
      create: options.create ?? true,
      calls,
    });
    const py = ctx.runPython(REF, request(roots.py));
    const nd = runNode(store, request(roots.node));
    for (const side of ['py', 'node']) applyModes(roots[side], spec, false);

    cases.push({
      name: `${label} — answer`,
      kind: 'json',
      expected: scrub(py.results, roots.py),
      actual: scrub(nd.results, roots.node),
      ...(ruling ? { ruling } : {}),
    });
    cases.push({
      name: `${label} — tree`,
      kind: 'bytes',
      expected: manifest(roots.py),
      actual: manifest(roots.node),
    });
  }
  notes.push(`${list.length} scenarios compared, ${ruled.length} ruled to differ in their answer`);

  // ------------------------------------------------ the live index, rebuilt from scratch
  // The strongest single statement this suite can make: take the index.md that the PYTHON
  // store has been maintaining for months, and rebuild it from the fact files with the Node
  // port. If those bytes match, the budget the port measures is the budget the live store
  // has, and the two are the same number rather than two numbers that happen to be close.
  if (real) {
    const bed = join(ctx.scratch, 'live-index');
    materialise(bed, { copyFrom: real });
    const live = readFileSync(join(bed, 'index.md'));
    const rebuilt = new store.MemoryStore(bed, { today: () => TODAY, create: false }).indexText();
    cases.push({
      name: 'the live index.md, rebuilt from the fact files by the port',
      kind: 'bytes',
      expected: [...live],
      actual: rebuilt,
    });
    const lines = rebuilt.split('\n').length - 1;
    notes.push(
      `live index: ${live.length} bytes on disk, ${Buffer.byteLength(rebuilt, 'utf8')} bytes ` +
        `rebuilt, ${lines} lines, ${DEFAULT_INDEX_BUDGET - Buffer.byteLength(rebuilt, 'utf8')} ` +
        'bytes of headroom under the 24000 default',
    );
    notes.push(
      `budget vs disk: the port writes LF, so the two agree at ${Buffer.byteLength(rebuilt, 'utf8')} ` +
        `on every platform. runtime-py agrees here (os.linesep=${JSON.stringify(EOL)}) ` +
        `but on Windows write_text turns each of the ${lines} lines into CRLF while ` +
        `_check_index_budget still counts this LF text — ${Buffer.byteLength(rebuilt, 'utf8') + lines} ` +
        `bytes on disk against ${Buffer.byteLength(rebuilt, 'utf8')} checked. NOT MEASURED HERE: ` +
        'CPython gates write-translation on #ifdef MS_WINDOWS, so this platform cannot ' +
        'construct it. A Windows runner settles it with ' +
        'python -c "import pathlib,os;p=pathlib.Path(r);print(len(s.index_text().encode()), p.joinpath(\'index.md\').stat().st_size)".',
    );
  }

  // ---------------------------------------------------------------- the primitives
  // Each of these is a table or a rule the store depends on. They are compared separately
  // because a scenario that happens not to reach one would let it rot unnoticed.

  const strerror = ctx.runPython(REF, { op: 'strerror', names: [...pyfs.STRERROR_NAMES] });
  cases.push({
    name: 'os.strerror for every errno the port claims to render',
    kind: 'json',
    expected: { strerror: strerror.strerror, missing: strerror.missing },
    actual: {
      strerror: Object.fromEntries(
        pyfs.STRERROR_NAMES.filter((k) => !strerror.missing.includes(k)).map((k) => [
          k,
          pyfs.asPyOSError({ code: k, errno: -1 }).strerror,
        ]),
      ),
      missing: strerror.missing,
    },
  });

  // The utf-8 decoder's message, over the corpus its rules were derived from.
  const seqs = [];
  for (const b of [0x80, 0xbf, 0xc0, 0xc1, 0xf5, 0xfe, 0xff]) seqs.push([0x61, b, 0x62]);
  for (const s of [[0xc2], [0xc2, 0x61], [0xe0], [0xe0, 0xa0], [0xe0, 0xa0, 0x61], [0xe0, 0x80, 0x80],
    [0xed, 0xa0, 0x80], [0xf0, 0x80, 0x80, 0x80], [0xf0, 0x9f, 0x90], [0xf0, 0x9f, 0x90, 0x61],
    [0xf4, 0x90, 0x80, 0x80], [0x61, 0xe2, 0x82], [0x61, 0xe2, 0x82, 0x61], [0xf0, 0x9f, 0x90, 0x94]]) seqs.push(s);
  let seed = 7;
  const rnd = (n) => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n; };
  for (let i = 0; i < 200; i += 1) seqs.push(Array.from({ length: 1 + rnd(8) }, () => rnd(256)));
  const pyDecoded = ctx.runPython(REF, { op: 'decode', seqs }).decoded;
  cases.push({
    name: `utf-8 strict decode over ${seqs.length} sequences`,
    kind: 'json',
    expected: pyDecoded,
    actual: seqs.map((s) => {
      try {
        pyfs.pyDecodeUtf8(Uint8Array.from(s));
        return { ok: true };
      } catch (e) {
        return { ok: false, message: e.message };
      }
    }),
  });

  const texts = ['ABC def 123', 'İstanbul', 'ẞ straße', 'K elvin', 'ΣοφοΣ', 'ı dotless', 'ＡＢＣ',
    'Ångström A123', 'ǅ titlecase', 'ᾼ iota', '🐔 emoji A1', 'АБВ abc', 'tab\tsep', '--- dashes ---',
    '2026-08-23', 'a_b_c', '① circled one', 'Ṡ̇ dot', 'ความจำ', ''];
  cases.push({
    name: '_tokens over the lowercasing cases',
    kind: 'json',
    expected: ctx.runPython(REF, { op: 'tokens', texts_b64: texts.map(b64) }).tokens,
    actual: texts.map((t) => [...store.tokens(t)].sort()),
  });

  // `_jaccard` direct. The both-empty arm is UNREACHABLE from `save` — `NAME_RE` forces at
  // least one ASCII token into the new fact's side — so the guard has no scenario that can
  // exercise it, and comparing the function itself is the only honest way to pin its value.
  const pairs = [[[], []], [[], ['a']], [['a'], []], [['a'], ['a']], [['a', 'b'], ['b', 'c']],
    [['a', 'b', 'c', 'd'], ['a', 'b', 'c', 'd', 'e']], [['a', 'b'], ['a', 'b', 'c', 'd']]];
  cases.push({
    name: '_jaccard, including the empty sets save cannot reach',
    kind: 'json',
    expected: ctx.runPython(REF, { op: 'jaccard', pairs }).jaccard,
    actual: pairs.map(([a, b]) => store.jaccard(new Set(a), new Set(b))),
  });

  const names = ['a.md', 'A.md', 'z.md', '！.md', '\u{1f414}.md', '.md', '￿.md', '0-.md',
    '0.md', 'a-b.md', 'ab.md', 'Z.md', 'á.md'];
  cases.push({
    name: 'sorted(Path) over the astral and case boundary',
    kind: 'json',
    expected: ctx.runPython(REF, { op: 'sortpaths', dir: '/s/facts', names: names.map(b64) }).sorted.map(unb64),
    actual: pyfs.sortedPathNames(names),
  });

  const joins = [['/a/b', 'facts'], ['/a/b/', 'facts'], ['/a//b', 'facts'], ['/a/./b', 'facts'],
    ['/a/b/..', 'facts'], ['a/b', 'facts', 'x.md'], ['.', 'facts'], ['/', 'facts'], ['//a', 'facts'],
    ['///a', 'facts'], ['~/mem', 'facts']];
  const suffixes = [['/f/a.md', '.md.tmp'], ['/f/a.b.md', '.md.tmp'], ['/f/.md', '.md.tmp'],
    ['/f/a..md', '.md.tmp'], ['/f/a.', '.md.tmp'], ['/f/None.md', '.md.tmp'], ['/f/a\n.md', '.md.tmp']];
  const paths = ctx.runPython(REF, {
    op: 'paths',
    joins: joins.map((parts) => parts.map(b64)),
    suffixes: suffixes.map(([p, s]) => [b64(p), b64(s)]),
  });
  cases.push({
    name: 'PurePath / and with_suffix',
    kind: 'json',
    expected: { joined: paths.joined.map(unb64), suffixed: paths.suffixed.map(unb64) },
    actual: {
      joined: joins.map((parts) => pyfs.pyJoin(...parts)),
      suffixed: suffixes.map(([p, s]) => pyfs.pyWithSuffix(p, s)),
    },
  });

  return { cases, notes };
}
