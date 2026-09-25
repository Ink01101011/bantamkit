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
 * The operator's real fact store is one of the fixtures, copied to scratch. It is never opened in
 * place: the defect this module reimplements destroyed that store's index once.
 */
import {
  chmodSync,
  cpSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  readlinkSync,
  rmSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
} from 'node:fs';
import { EOL } from 'node:os';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { auditCorpus, corpusIntegrityCase } from '../lib/corpus.mjs';

export const name = 'store';
export const summary = 'save/recall/index: the directory after the call, byte for byte';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'store_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

const TODAY = '2026-08-23';
const DEFAULT_INDEX_BUDGET = 24_000;

/**
 * Take the fixture's own root out of every message before comparing.
 *
 * The two sides run in `py/` and `node/` under one scratch bed, and `_unreadable` and
 * `OSError` both PRINT the path — so an un-scrubbed comparison would fail on the one
 * difference the harness itself created. The path is not dropped from the check: it is
 * replaced by a marker, so a message that named the WRONG path still differs.
 */
/**
 * Replace the bed in one message, in BOTH spellings the message can carry it in.
 *
 * `str(OSError)` prints the path through `%r`, which escapes a backslash — so on Windows the
 * bed appears as `C:\\Users\\...` and a scrubber that only looks for `C:\Users\...` finds
 * nothing and leaves the harness's own `py/` vs `node/` split in the comparison. MEASURED,
 * run 32649940727: three cases failed on a difference the harness had created itself, and
 * the port's sentences were identical. No effect off Windows, where the two spellings are
 * the same string.
 */
function scrubPath(text, root) {
  const escaped = root.split('\\').join('\\\\');
  return text.split(root).join('<ROOT>').split(escaped).join('<ROOT>');
}

function scrub(results, root) {
  const walk = (value) => {
    if (Array.isArray(value)) return value.map(walk);
    if (value && typeof value === 'object') {
      if (value.error) {
        return {
          error: {
            type: value.error.type,
            message: b64(scrubPath(unb64(value.error.message), root)),
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
 *
 * The finder itself is `lib/corpus.mjs`, shared with `codec.mjs`. It used to live here, and
 * the rule it enforces — a store is `facts/` AND `index.md`, never `facts/` alone — was
 * learned here (run 32644269451, an empty `facts/` at a runner's repository root killed
 * this suite on an uncaught ENOENT). `codec.mjs` kept its own copy of the finder without
 * that rule and lost 288 cases to it (I3-F1). One finder now, so there is nothing to drift.
 */
function realStore(ctx) {
  return auditCorpus(ctx);
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

/**
 * Apply one fixture spec's modes to a bed, or put them back.
 *
 * platform-checked: BOTH BEDS GET THE SAME CALL FROM THE SAME SPEC — `applyModes` is invoked
 * once per side (`for (const side of ['py', 'node'])`) with one `spec`, so a platform that
 * ignores the mode removes the restriction from the reference's tree and the port's tree
 * identically. That is the property this suite's comparison rests on, and it holds on every
 * platform because it is a property of the harness rather than of the filesystem.
 *
 * WHAT IS NOT CLAIMED, and it is not claimed because it is not measured: whether the
 * resulting comparison still has teeth on Windows. It does not — an unrestricted bed answers
 * a question nobody asked — and this repository has no Windows run to show it with, because
 * Actions is off on this account. `recall-strings.mjs` shows the shape that would measure it:
 * a probe that tries the denied operation, and a `notes.push('NOT MEASURED: ...')` when the
 * mode was not honoured. Registered rather than written here, because a sentence asserting
 * Windows behaviour nobody has run is the thing this gate's own docstring warns about.
 */
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
const lookup = (name, stamp = true) => ({ op: 'lookup', args: [b64(name), stamp] });
const indexText = () => ({ op: 'index_text' });

/** The Node side of one scenario, shaped exactly like `store_ref.py`'s answer. */
function runNode(store, request) {
  /** `str(value)` as the PORT spells it — the same function the index line goes through. */
  const nullable = (v) => (v === null || v === undefined ? null : b64(store.pyText(v)));
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
        results.push({ status: r.status, name: b64(r.name), similar: nullable(r.similar) });
      } else if (call.op === 'recall') {
        const [query, k, stamp] = call.args;
        results.push(
          s.recall(unb64(query), k, stamp).map((f) => ({
            name: nullable(f.name),
            description: nullable(f.description),
            type: nullable(f.type),
            body: b64(f.body),
            // `str(link)`, not `String(link)`: a null item spells `None` in Python and
            // `null` in JS, and the port's `pyText` is the one place that decision lives.
            links: f.links.map((l) => b64(store.pyText(l))),
            last_recalled: nullable(f.last_recalled),
            created: nullable(f.created),
          })),
        );
      } else if (call.op === 'lookup') {
        // `lookup` (job64, J64-4) answers ONE fact or nothing; the same fact JSON as a
        // recall hit, so a port that found the right fact but rendered it differently
        // still differs. `null` is the miss, on both sides.
        const [name_, stamp] = call.args;
        const f = s.lookup(unb64(name_), stamp);
        results.push(
          f === null
            ? null
            : {
                name: nullable(f.name),
                description: nullable(f.description),
                type: nullable(f.type),
                body: b64(f.body),
                links: f.links.map((l) => b64(store.pyText(l))),
                last_recalled: nullable(f.last_recalled),
                created: nullable(f.created),
              },
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

// ---------------------------------------------------------- frontmatter scalar corpus

/**
 * THE SHAPES A HAND-EDITED FRONTMATTER CAN RESOLVE TO, and the nine places the store
 * renders one.
 *
 * WHY THIS CORPUS EXISTS. `_facts` puts `yaml.safe_load`'s answer into the `Fact` dataclass
 * with no type check, so `description: 2026` gives the reference an `int` in a `str` field
 * — and the reference then keeps working, while this port used to raise
 * `MemoryValidationError` and refuse `recall`, `save` AND the index rebuild for the whole
 * store. N8 measured that on 13 of 17 shapes; N10 fixed it, and this is the measurement
 * that says the fix is Python's answer and not a second guess.
 *
 * EACH SCENARIO PUTS ONE SHAPE IN THREE PLACES AT ONCE and then makes the store do
 * everything it can do with them:
 *
 *   `in-name.md`  — the shape is the fact's NAME. Reaches the index line, the token text,
 *                   the recall tie-break, `SaveResult.similar`, and the FILE PATH: `_stamp`
 *                   writes to `facts/{name}.md`, so a `name: 7` grows a `facts/7.md` and
 *                   the tree diff is what proves the two runtimes spell it the same.
 *   `in-desc.md`  — the shape is the DESCRIPTION. Index line and token text again, plus the
 *                   duplicate gate, which is scored on `f"{name} {description}"`.
 *   `in-meta.md`  — the shape is `type`, `created`, `last_recalled` AND the single `links`
 *                   item. Reaches the index line's `({type})`, both TRUTHINESS tests
 *                   (`created or _mtime_date(path)`, `links or []`), and `list()` over the
 *                   links value.
 *
 * The call list then reads the index (before any write), recalls with `stamp=true` (which
 * sends every one of those values back through `yaml.safe_dump` into a file on disk), reads
 * the index again, and saves over `in-desc` (an UPDATE, so `existing.created` — possibly a
 * `datetime.date` — is carried into the new Fact and re-emitted). Answers are compared as
 * JSON and the whole tree byte for byte, so a shape that renders right in the index and
 * wrong in the file is still a failure.
 */
const SCALAR_SHAPES = [
  // int: every base the constructor branches on, plus the two falsy ones and a value no
  // JS number can hold.
  ['int decimal', '7'],
  ['int four digits', '2026'],
  ['int hex', '0x1f'],
  ['int binary', '0b101'],
  ['int octal by leading zero', '017'],
  ['int with underscores', '1_000'],
  ['int sexagesimal', '1:30'],
  ['int negative zero', '-0'],
  ['int zero is falsy', '0'],
  ['int past 2^53', '999999999999999999999999'],
  // float: `str()` and `safe_dump` DISAGREE on three of these, which is why a Fact field
  // carries both spellings instead of one number.
  ['float', '1.5'],
  ['float integral', '1.0'],
  ['float exponent', '1.0e+50'],
  ['float inf', '.inf'],
  ['float -inf', '-.inf'],
  ['float nan', '.nan'],
  ['float sexagesimal', '1:30.5'],
  ['float zero is falsy', '0.0'],
  // bool: `True` in a sentence, `true` on disk.
  ['bool true', 'true'],
  ['bool no is falsy', 'no'],
  ['bool off is falsy', 'off'],
  // timestamp: the shape that made this a job — `created:` unquoted is a `datetime.date`
  // and it round-trips through `_stamp`.
  ['date', '2026-08-23'],
  ['datetime', '2026-08-23 10:00:00'],
  ['datetime Z', '2026-08-23T10:00:00Z'],
  ['datetime offset', '2026-08-23T10:00:00-05:30'],
  ['datetime single-digit fields', '2026-1-2 3:04:05'],
  ['datetime fraction past microseconds', '2026-08-23 10:00:00.1234567'],
  ['null tilde', '~'],
  // A timestamp the RESOLVER accepts and the `datetime` CONSTRUCTOR refuses. CPython raises
  // `ValueError`, `_facts` catches it, and the text reaches a model inside
  // `malformed fact file <name>: <text>`. Matched exactly, not ruled.
  ['date month out of range', '2026-13-45'],
  ['date day out of range', '2026-02-30'],
  ['date year zero', '0000-01-01'],
  ['datetime hour out of range', '2026-08-23 25:00:00'],
  ['datetime minute out of range', '2026-08-23 10:99:00'],
  ['datetime tz past 24 hours', '2026-08-23T10:00:00+24:00'],
];

const scalarFixture = (shape) => ({
  dirs: ['facts', 'archive'],
  files: {
    'facts/in-name.md':
      `---\nname: ${shape}\ndescription: shared probe token\ntype: project\n` +
      `created: '2026-08-01'\nlast_recalled: null\nlinks: []\n---\n\nb\n`,
    'facts/in-desc.md':
      `---\nname: in-desc\ndescription: ${shape}\ntype: project\n` +
      `created: '2026-08-01'\nlast_recalled: null\nlinks: []\n---\n\nb\n`,
    'facts/in-meta.md':
      `---\nname: in-meta\ndescription: shared probe token\ntype: ${shape}\n` +
      `created: ${shape}\nlast_recalled: ${shape}\nlinks:\n- ${shape}\n---\n\nb\n`,
  },
  mtimes: {
    'facts/in-name.md': 1755990000,
    'facts/in-desc.md': 1755990000,
    'facts/in-meta.md': 1755990000,
  },
});

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
    // `lookup` (job64, J64-4): the name, not a score. `fact-1` shares every token of its name
    // with `fact-0` and `fact-2` as a QUERY would score them, and the tree says only
    // `fact-1.md` was dated; the second call is the miss that must write nothing, and the
    // third is `stamp: false` over a hit — found, undated.
    ['lookup answers the named fact alone and stamps only it', three, {}, [lookup('fact-1', true)]],
    ['lookup misses write nothing, and a name is not a query', three, {}, [
      lookup('fact', true), lookup('fact 1', true), lookup('fact-1', false), indexText(),
    ]],
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

  for (const [label, shape] of SCALAR_SHAPES) {
    list.push([
      `frontmatter scalar: ${label} (${shape})`,
      scalarFixture(shape),
      { create: false },
      [
        indexText(),
        recall('shared probe token', 5, true),
        indexText(),
        save('project', 'in-desc', 'shared probe token', 'rewritten'),
      ],
    ]);
  }

  // `links` holding a SCALAR rather than a sequence. `list(12)` is a `TypeError` and the
  // `except (ValueError, KeyError, yaml.YAMLError)` in `_facts` does not catch it, so it
  // escapes the store as a bare `TypeError` instead of a `malformed fact file` sentence.
  // The escape route is half the case: a caller catching `MemoryValidationError` sees one
  // and not the other.
  list.push([
    'frontmatter scalar: links is an int, and list() refuses it',
    {
      dirs: ['facts', 'archive'],
      files: {
        'facts/scalarlinks.md':
          '---\nname: scalarlinks\ndescription: d\ntype: project\nlinks: 12\n---\n\nb\n',
      },
      mtimes: { 'facts/scalarlinks.md': 1755990000 },
    },
    { create: false },
    [indexText()],
  ]);

  // A null item in `links`: `- ` with nothing after it. `list()` keeps the `None` and
  // `represent_none` writes it back as `- null`, so the STAMP is where this shows.
  list.push([
    'frontmatter scalar: a null links item survives the round trip',
    {
      dirs: ['facts', 'archive'],
      files: {
        'facts/nulllink.md':
          '---\nname: nulllink\ndescription: shared probe token\ntype: project\nlinks:\n-\n- a\n---\n\nb\n',
      },
      mtimes: { 'facts/nulllink.md': 1755990000 },
    },
    { create: false },
    [recall('shared probe token', 5, true)],
  ]);

  // THE TIE-BREAK. `sorted(key=lambda p: (-p[0], p[1].name))` compares the NAMES only when
  // the scores are equal, and Python has no order between an `int` and a `str`. Two facts,
  // one token each, identical score: whatever Python does here — answer or raise — is what
  // this port has to do.
  list.push([
    'frontmatter scalar: an int name and a str name tie on score',
    {
      dirs: ['facts', 'archive'],
      files: {
        'facts/num.md':
          "---\nname: 7\ndescription: shared probe token\ntype: project\ncreated: '2026-08-01'\nlinks: []\n---\n\nb\n",
        'facts/str.md':
          "---\nname: seven\ndescription: shared probe token\ntype: project\ncreated: '2026-08-01'\nlinks: []\n---\n\nb\n",
      },
      mtimes: { 'facts/num.md': 1755990000, 'facts/str.md': 1755990000 },
    },
    { create: false },
    [recall('shared probe token', 5, false)],
  ]);

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
        'here rather than discovered later. THE RULING COVERS THE COLLECTION SHAPES ONLY: a ' +
        'list, and (measured) a MAP, where Python says `{\'a\': 1}` and JS says `{a: 1}`. ' +
        'The plain non-string SCALARS were once here too, as a defect awaiting a unit; they ' +
        'are NOT a divergence any more. N10 ported `SafeConstructor`, and the 37 ' +
        '`frontmatter scalar:` scenarios above compare `name: 7`, `description: 2026`, ' +
        '`type: true`, `created: 2026-08-23` and 33 more at every place the store renders ' +
        'one — index line, file path, token text, tie-break, both truthiness tests, and the ' +
        'bytes `_stamp` writes back — with the whole tree diffed and nothing ruled.',
    ],
  ];

  // The three tags whose ANSWER differs, at the width it was measured and no wider. Each is
  // one fact file holding one plain scalar; the tree still has to match, so none of these
  // can hide a byte moving on disk.
  for (const [label, shape, why] of [
    [
      'the merge tag',
      '<<',
      'PyYAML has no constructor for `tag:yaml.org,2002:merge` outside a mapping key, and ' +
        'says so with a `ConstructorError` carrying the source marks and a rendered snippet ' +
        '— `in "<unicode string>", line 1, column 4:` and a caret under the scalar. Both ' +
        'runtimes REFUSE and the prefix `malformed fact file <name>: ` is identical; only ' +
        'the marks differ, and reproducing them is the PyYAML-diagnostics surface this ' +
        'module already declined for `ScannerError`.',
    ],
    [
      'the value tag',
      '=',
      'Same shape as `<<` for `tag:yaml.org,2002:value`, and measured separately rather ' +
        'than assumed from it — the previous ruling in this file asserted a general case ' +
        'from one example and N8 found four counter-examples inside it.',
    ],
    [
      'a bare tag indicator, where CPython ANSWERS and this port refuses',
      '!',
      'THE ONE WHERE THE ANSWERS GENUINELY PART. `k: !` is not a plain scalar to PyYAML: ' +
        'the SCANNER reads `!` as a tag property on an empty node, and the empty node ' +
        'resolves to null — CPython returns `None` and the store keeps working. This codec ' +
        'has no scanner; `parseFrontmatter` accepts the emitter\'s language and sees a plain ' +
        'scalar that resolves to `tag:yaml.org,2002:yaml`, so it refuses. Filed on its own ' +
        'rather than with `&` and `*` because those two also refuse in CPython (an anchor ' +
        'and an alias, both `ScannerError`) and this one does not. Fixing it means a YAML ' +
        'SCANNER, which is the surface this module exists to avoid; the cost of the ' +
        'divergence is one hand-edited file refused where Python read it as an empty value.',
    ],
    [
      'an anchor indicator',
      '&',
      '`&` starts an anchor name to PyYAML\'s scanner and the scanner fails on the empty ' +
        'one: `while scanning an anchor … expected alphabetic or numeric character`. Both ' +
        'runtimes refuse; only the words differ.',
    ],
    [
      'an alias indicator',
      '*',
      '`*` starts an alias, and the same scanner failure. Measured, not inferred from `&`.',
    ],
  ]) {
    ruled.push([
      `frontmatter scalar: ${label} (${shape})`,
      {
        dirs: ['facts', 'archive'],
        files: {
          'facts/tagged.md': `---\nname: tagged\ndescription: ${shape}\ntype: project\nlinks: []\n---\n\nb\n`,
        },
        mtimes: { 'facts/tagged.md': 1755990000 },
      },
      { create: false },
      [indexText()],
      why,
    ]);
  }

  return { list, ruled };
}

// ------------------------------------------------------------------------------- run

export async function run(ctx) {
  const store = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'store.js')).href);
  const pyfs = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'pyfs.js')).href);
  const pyyaml = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'pyyaml.js')).href);
  const cases = [];
  const notes = [];

  const audit = realStore(ctx);
  const real = audit.root;
  notes.push(real ? `real corpus: ${real}` : 'real corpus: NOT FOUND — the synthetic fixtures ran alone');
  // Same gate as `codec.mjs`: a resolved store that has quietly shrunk, or a real store
  // turned away for want of an `index.md`, is a failure and not a smaller run.
  cases.push(corpusIntegrityCase(audit));

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

  // The five tag rulings above pin their WORDING, and a `ruling` case fails only when the
  // two sides MATCH — so a port that stopped refusing `<<` altogether would still "differ"
  // from PyYAML's ConstructorError and stay green. This is the other half and it is NOT
  // ruled: did each side refuse at all, over the four where the answer is that both do. `!`
  // is left out because its bits genuinely disagree, and the ruled scenario above is already
  // what fails if this port ever starts answering `None` there.
  {
    const shapes = ['<<', '=', '&', '*'];
    const bed = join(ctx.scratch, 'tagbits');
    const py = [];
    const nd = [];
    shapes.forEach((shape, i) => {
      const spec = {
        dirs: ['facts', 'archive'],
        files: {
          'facts/tagged.md': `---\nname: tagged\ndescription: ${shape}\ntype: project\nlinks: []\n---\n\nb\n`,
        },
        mtimes: { 'facts/tagged.md': 1755990000 },
      };
      const roots = {};
      for (const side of ['py', 'node']) {
        roots[side] = join(bed, `s${i}`, side);
        materialise(roots[side], spec);
      }
      const request = (root) => ({ op: 'run', root, today: TODAY, index_budget: null, k: null, create: false, calls: [indexText()] });
      py.push(ctx.runPython(REF, request(roots.py)).results[0].error !== undefined);
      nd.push(runNode(store, request(roots.node)).results[0].error !== undefined);
    });
    cases.push({
      name: 'the four constructor-less tags that both refuse: WHO refuses, not what they say',
      kind: 'json',
      expected: py,
      actual: nd,
    });
    notes.push(`constructor-less tags: python refuses ${py.filter(Boolean).length}/4, node ${nd.filter(Boolean).length}/4 (the fifth, \`!\`, is the ruled one where python answers)`);
  }

  // ------------------------------------------------ the self-ignoring .bantamkit/.gitignore
  //
  // THE PROPERTY (user ruling 2026-09-15, J51-1/J51-2, narrowed by user ruling #2 the same
  // day, J51-8a/J51-8b): the first save that brings a `.bantamkit` directory into existence
  // leaves `.bantamkit/.gitignore` holding exactly GITIGNORE_LITERAL; a `.gitignore` already
  // there is never rewritten; a store whose parent is not named `.bantamkit` gets none. And
  // the ignore file is written ONLY when bantamkit itself creates `.bantamkit`: a `.bantamkit`
  // that already exists without one never gets one (scenario 4), and deleting the file sticks
  // across a later save (scenario 5). Those two are the ruling; J51-3's first three are
  // unchanged by it.
  //
  // SCENARIO 5 READS THE FILE BEFORE IT DELETES IT. Absence after the second save proves
  // nothing if the first save never wrote the file, so each side also gets a case pinning
  // the first save's bytes to the literal — the delete is a real delete, not a no-op.
  //
  // PROVEN NON-VACUOUS IN J51-8c: reverting the rule to J51-1/J51-2's "write whenever the
  // file is absent" — Python only, Node only, and both — turns scenarios 4 and 5 red; in the
  // both-sides run only the against-the-literal arms can see it, which is why they exist.
  //
  // WHY EVERY SIDE IS ALSO COMPARED TO A LITERAL. A Python-vs-Node comparison alone stays
  // green when both runtimes regress the same way — both stop writing the file and they
  // "agree" on its absence (see `differential-is-blind-to-symmetric-regression`). So each
  // scenario yields eight cases: per side, the save succeeded, the file's bytes against the
  // literal, and the `.gitignore` files under the bed against the expected list; then python
  // against node, for the file's bytes and for the whole tree. The literal is typed HERE, not
  // imported from either runtime, so a change to both runtimes' constant turns this red
  // instead of moving the goalposts. Proven non-vacuous in J51-3: removing the write, the
  // exists-guard, or the name-guard — in Python only, Node only, or both — turns it red.
  //
  // A missing file reads as the sentinel `<ABSENT>` rather than throwing, so a runtime that
  // stopped writing is one red case naming itself, not a suite that could not build.
  {
    const GITIGNORE_LITERAL =
      '# Created by bantamkit: this directory is local state. Delete this file to commit it.\n' +
      '*\n';
    const OPERATOR_GITIGNORE = '# mine: an operator edited this one\n!memory/\n';
    const ABSENT = '<ABSENT>';
    const readOr = (path) => {
      try {
        return readFileSync(path);
      } catch (e) {
        if (e.code === 'ENOENT') return ABSENT;
        throw e;
      }
    };
    /** Every `.gitignore` under `root`, as `/`-joined relative paths, sorted. */
    const gitignoresUnder = (root) => {
      const found = [];
      const walk = (dir) => {
        for (const entry of readdirSync(dir).sort()) {
          const full = join(dir, entry);
          if (lstatSync(full).isDirectory()) walk(full);
          else if (entry === '.gitignore') found.push(relative(root, full).split('\\').join('/'));
        }
      };
      walk(root);
      return found;
    };
    const gitignoreScenarios = [
      {
        label: 'a fresh .bantamkit store',
        store: ['proj', '.bantamkit', 'memory'],
        files: {},
        file: ['proj', '.bantamkit', '.gitignore'],
        literal: GITIGNORE_LITERAL,
      },
      {
        label: 'a pre-existing .bantamkit/.gitignore',
        store: ['proj', '.bantamkit', 'memory'],
        files: { 'proj/.bantamkit/.gitignore': OPERATOR_GITIGNORE },
        file: ['proj', '.bantamkit', '.gitignore'],
        literal: OPERATOR_GITIGNORE,
      },
      {
        label: 'a store whose parent is not .bantamkit',
        store: ['proj', 'state', 'memory'],
        files: {},
        file: ['proj', 'state', '.gitignore'],
        literal: ABSENT,
      },
      {
        // Ruling #2: `.bantamkit` predates bantamkit's first save — made by hand, by an
        // earlier bantamkit, or checked out from git — so bantamkit did not create it.
        label: 'an existing .bantamkit with no ignore file',
        store: ['proj', '.bantamkit', 'memory'],
        dirs: ['proj/.bantamkit/memory'],
        files: {},
        file: ['proj', '.bantamkit', '.gitignore'],
        literal: ABSENT,
      },
      {
        // Ruling #2: the operator deleted the file bantamkit wrote; the next save leaves it gone.
        label: 'an ignore file deleted after creation',
        store: ['proj', '.bantamkit', 'memory'],
        files: {},
        file: ['proj', '.bantamkit', '.gitignore'],
        literal: ABSENT,
        deleteThenSaveAgain: true,
      },
      // ---- J54-3: THE SHAPES OF ROOT THE FIRST FIVE NEVER ASKED ABOUT. Every scenario above
      // roots the store at `<x>/.bantamkit/memory`, where the `.bantamkit` directory happens
      // to be the root's PARENT — and both runtimes decided about the parent and nothing else.
      // A root that IS the `.bantamkit` directory, or one nested deeper under it, is created
      // by the same `mkdir(parents=True)` and had its decision taken about the wrong
      // directory, which is no decision at all. MEASURED, not hypothetical: `~/.bantamkit` on
      // the machine this was found on holds an empty `facts/` and `archive/` beside `memory/`
      // — left by a store once rooted at it — and no `.gitignore`. Both of the first two were
      // RED on both sides before the fix; the third is the guard that it does not over-fire.
      {
        label: 'a store rooted AT the .bantamkit directory itself',
        store: ['proj', '.bantamkit'],
        files: {},
        file: ['proj', '.bantamkit', '.gitignore'],
        literal: GITIGNORE_LITERAL,
      },
      {
        label: 'a store nested deeper under .bantamkit',
        store: ['proj', '.bantamkit', 'memory', 'extra'],
        files: {},
        file: ['proj', '.bantamkit', '.gitignore'],
        literal: GITIGNORE_LITERAL,
      },
      {
        // Ruling #2 again, at the new shape: the directory predates the call, so it stays
        // visible to git whichever component of the root happens to be named `.bantamkit`.
        label: 'an existing .bantamkit the store is rooted AT',
        store: ['proj', '.bantamkit'],
        dirs: ['proj/.bantamkit'],
        files: {},
        file: ['proj', '.bantamkit', '.gitignore'],
        literal: ABSENT,
      },
    ];
    gitignoreScenarios.forEach((sc, i) => {
      const bed = join(ctx.scratch, 'gitignore', `g${i}`);
      const got = {};
      const answers = {};
      const beds = {};
      const beforeDelete = {};
      const probes = [save('project', 'gitignore-probe', 'the first save into this store', 'b')];
      if (sc.deleteThenSaveAgain) {
        probes.push(save('project', 'after-the-delete', 'a later process writes again once the operator removed it', 'c'));
      }
      for (const side of ['py', 'node']) {
        beds[side] = join(bed, side);
        materialise(beds[side], { dirs: ['proj', ...(sc.dirs ?? [])], files: sc.files });
        answers[side] = [];
        probes.forEach((call, n) => {
          if (n > 0) {
            // Each save is its own request — a separate MemoryStore, as a later process would
            // be — and the file is deleted between them, after its bytes are recorded.
            beforeDelete[side] = readOr(join(beds[side], ...sc.file));
            rmSync(join(beds[side], ...sc.file), { force: true });
          }
          const request = {
            op: 'run',
            root: join(beds[side], ...sc.store),
            today: TODAY,
            index_budget: null,
            k: null,
            create: true,
            calls: [call],
          };
          const r = side === 'py' ? ctx.runPython(REF, request) : runNode(store, request);
          answers[side].push(...scrub(r.results, beds[side]));
        });
        got[side] = { file: readOr(join(beds[side], ...sc.file)), all: gitignoresUnder(beds[side]) };
      }
      const name = (what) => `.bantamkit/.gitignore: ${sc.label} — ${what}`;
      const expectedAll = sc.literal === ABSENT ? [] : [sc.file.join('/')];
      const expectedSaves = [{ status: 'saved', name: b64('gitignore-probe'), similar: null }];
      if (sc.deleteThenSaveAgain) {
        expectedSaves.push({ status: 'saved', name: b64('after-the-delete'), similar: null });
      }
      // The save itself must have SUCCEEDED on both sides; a refused save writes no ignore
      // file and would make the absence scenario pass for the wrong reason.
      for (const side of ['py', 'node']) {
        cases.push({
          name: name(`${side === 'py' ? 'python' : 'node'} saved`),
          kind: 'json',
          expected: expectedSaves,
          actual: answers[side],
        });
        if (sc.deleteThenSaveAgain) {
          cases.push({
            name: name(`${side === 'py' ? 'python' : 'node'} first save wrote the literal before the delete`),
            kind: 'bytes',
            expected: GITIGNORE_LITERAL,
            actual: beforeDelete[side],
          });
        }
        cases.push({
          name: name(`${side === 'py' ? 'python' : 'node'} bytes against the literal`),
          kind: 'bytes',
          expected: sc.literal,
          actual: got[side].file,
        });
        cases.push({
          name: name(`${side === 'py' ? 'python' : 'node'} .gitignore files under the bed`),
          kind: 'json',
          expected: expectedAll,
          actual: got[side].all,
        });
      }
      cases.push({
        name: name('python against node, bytes'),
        kind: 'bytes',
        expected: got.py.file,
        actual: got.node.file,
      });
      cases.push({
        name: name('python against node, whole tree'),
        kind: 'bytes',
        expected: manifest(beds.py),
        actual: manifest(beds.node),
      });
    });
    notes.push(`.bantamkit/.gitignore: ${gitignoreScenarios.length} scenarios, each side against a literal and against the other`);
  }

  // ---------------------------------------------------- the recall tie-break, 50 000 times
  //
  // `recall` sorts on `(-score, fact.name)`, and once a name can be something other than a
  // `str` that sort can RAISE — with a sentence whose two type names depend on which pair
  // CPython's `listsort` happened to compare first. `Array.prototype.sort`'s comparison
  // order is unspecified, so the port spells out `count_run` + `binarysort` instead; this is
  // the case that says the spelling is CPython's and not a plausible-looking one.
  //
  // The lists are generated by a seeded LCG so both runtimes see the SAME 50,000 inputs, and
  // the names travel as frontmatter TEXT so each side constructs its own value the way it
  // constructs one off disk. Two earlier models are in the ruling at `store.sortScored`;
  // this case is what refuted them and it re-runs on every conformance run.
  {
    const NAMES = [
      '1', '2', '7.0', 'true', 'a', 'zz', '~', '2026-08-23',
      '2026-08-23 10:00:00', '2026-08-23T10:00:00Z',
    ];
    let seed = 20260823;
    const next = () => (seed = (seed * 1103515245 + 12345) % 2147483648);
    const pick = (n) => next() % n;
    const lists = [];
    // 30,000 short lists, then 20,000 across the length bands the ruling names — 64 is where
    // CPython stops sorting one run and starts merging them.
    const bands = [[2, 14, 30000], [2, 14, 4000], [15, 63, 4000], [64, 64, 4000], [65, 120, 4000], [121, 300, 4000]];
    for (const [lo, hi, count] of bands) {
      for (let i = 0; i < count; i += 1) {
        const n = lo + pick(hi - lo + 1);
        const spec = [];
        for (let j = 0; j < n; j += 1) spec.push([pick(3), NAMES[pick(NAMES.length)]]);
        lists.push(spec);
      }
    }
    const py = ctx.runPython(REF, { op: 'sortnames', lists });
    const nodeAnswers = lists.map((spec) => {
      const scored = spec.map(([score, text], i) => ({ score, name: pyyaml.constructPlain(text), i }));
      try {
        return { order: store.sortScored(scored).map((x) => x.i) };
      } catch (e) {
        return { error: String(e.message) };
      }
    });
    const raised = py.lists.filter((r) => r.error !== undefined).length;
    cases.push({
      name: `the recall tie-break over ${lists.length} generated lists (${raised} of them raise)`,
      kind: 'json',
      expected: py.lists,
      actual: nodeAnswers,
    });
    notes.push(
      `tie-break: ${lists.length} generated (score, name) lists, n from 2 to 300; ` +
        `CPython's sorted raises TypeError on ${raised} of them and the port reproduces the ` +
        'order or the sentence for every one',
    );
  }

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
      `budget vs disk: this note said "the port writes LF, so the two agree on every ` +
        'platform" and THAT PREMISE IS DEAD. It described N2\'s original ruling, which ' +
        'codec.mjs REVERSED after run 32646521489 measured it as 83 of the 132 Windows ' +
        'conformance failures. What the port does today is `pyfs.pyWriteText` -> ' +
        '`pyNewlineOut`, which is CRLF on win32 and a no-op elsewhere — CPython\'s ' +
        '`write_text(newline=None)` translation, deliberately reproduced. So the two ' +
        'runtimes agree byte for byte on disk on EVERY platform, and they agree for the ' +
        'opposite reason to the one this note used to give. codec.mjs pins both halves ' +
        'unruled and decidably here: `toCrlf` against CPython\'s own translation, and ' +
        '`Path.write_text` on whatever platform the run is standing on.',
    );
    notes.push(
      `budget vs disk, the part that IS still true and is NOT a defect: both runtimes ` +
        `measure the budget on the LF text — CPython ` +
        '`len(index_text().encode())`, the port ' +
        `\`Buffer.byteLength(indexText(), 'utf8')\` — and neither ever stats index.md. ` +
        `Here that is ${Buffer.byteLength(rebuilt, 'utf8')} bytes counted against ` +
        `${live.length} on disk (os.linesep=${JSON.stringify(EOL)}); on Windows the same ` +
        `${lines}-line index would sit at ${Buffer.byteLength(rebuilt, 'utf8') + lines} ` +
        'bytes on disk and still be counted at ' +
        `${Buffer.byteLength(rebuilt, 'utf8')}. That is the DESIGN, not drift: the budget ` +
        'governs how much index a model has to read, and both digests stay on the LF text ' +
        'for the same reason, so one store is judged the same number on every machine that ' +
        'opens it. Counting the disk instead would make a store over budget on Windows and ' +
        'under it on macOS with not one byte of content changed. Every budget case in this ' +
        'suite compares computed sizes and none reads the file, which is what holds it.',
    );
    notes.push(
      'the one-byte-per-line rule itself stays measured, from the same run 32645443625 over ' +
        'the SYNTHETIC fixtures where both runtimes write side by side and the tree manifest ' +
        'carries the counts: a 1-line index.md 42 bytes against 41, a 10-line fact file 134 ' +
        'against 124, a 93-line checkpoint 2609 against 2516. Those pairs were CPython ' +
        'against the port BEFORE the reversal; today both sides would write the CRLF number. ' +
        'The live store is arithmetic on that rule, never a second measurement — it ' +
        'is not on a runner and must never be put on one.',
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
          pyfs.pyStrerror(k),
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
  // THE BOM. `EF BB BF` is a well-formed three-byte sequence and CPython's utf-8 codec
  // decodes it to one U+FEFF — `utf-8-sig` is the codec that strips it. `TextDecoder`
  // defaults `ignoreBOM` to FALSE, meaning it DROPS it, so this port's own hand-rolled
  // validator accepted the bytes while the decoder behind it returned a different string.
  // Measured end to end by N8: CPython REFUSES a BOM'd checkpoint (`json.loads` answers
  // `Unexpected UTF-8 BOM (decode using utf-8-sig)`) and this port parsed it and WROTE.
  // An ok/not-ok comparison could never see it, which is why this case compares the TEXT.
  for (const s of [[0xef, 0xbb, 0xbf], [0xef, 0xbb, 0xbf, 0x61], [0x61, 0xef, 0xbb, 0xbf],
    [0xef, 0xbb, 0xbf, 0xef, 0xbb, 0xbf], [0xef, 0xbb, 0xbf, 0x7b, 0x7d]]) seqs.push(s);
  const pyDecoded = ctx.runPython(REF, { op: 'decode', seqs }).decoded;
  cases.push({
    name: `utf-8 strict decode over ${seqs.length} sequences, the decoded text included`,
    kind: 'json',
    expected: pyDecoded,
    actual: seqs.map((s) => {
      try {
        return { ok: true, text: b64(pyfs.pyDecodeUtf8(Uint8Array.from(s))) };
      } catch (e) {
        return { ok: false, message: e.message };
      }
    }),
  });

  // `%r` IN THE TWO SENTENCES THAT CARRY A PATH. `OSError.__str__` is `[Errno %S] %S: %R`
  // and pathlib's symlink-loop check is `RuntimeError("Symlink loop from %r")`. Both were
  // spelled with a hand-written pair of apostrophes, which is the same text for an ordinary
  // path and a DIFFERENT one for a path holding `'`, a newline or a tab — `pyRepr` switches
  // to double quotes for the first and escapes the other two. `component.Memory` and
  // shiftwork's clock-out quote that sentence straight into what a model reads, and `pyRepr`
  // was already in `pyfs.ts` with no caller. Both sides run real syscalls over the SAME
  // directory, so the path inside the message is NOT scrubbed here: a message that named the
  // wrong path would still fail.
  {
    const bed = join(ctx.scratch, 'oserror');
    mkdirSync(bed, { recursive: true });
    const nasty = ["it's-here.md", 'two\nlines.md', 'a\tb.md', 'plain.md', 'quote"and\'both.md',
      'back\\slash.md', 'ret\rurn.md', 'thai-ความจำ.md'];
    const loop = join(bed, "loop's-link");
    symlinkSync(loop, loop);
    const specs = [];
    for (const n of nasty) {
      specs.push(['unlink', join(bed, n), '']);
      specs.push(['read', join(bed, n), '']);
      specs.push(['mkdir', join(bed, 'missing', n), '']);
      specs.push(['replace', join(bed, n), join(bed, 'missing', n)]);
    }
    specs.push(['resolve', loop, '']);
    const pyMessages = ctx.runPython(REF, {
      op: 'oserror',
      cases: specs.map(([k, a, b]) => [k, b64(a), b64(b)]),
    }).messages;
    cases.push({
      name: `str(OSError) and the symlink-loop RuntimeError use %r, over ${specs.length} awkward paths`,
      kind: 'json',
      expected: pyMessages,
      actual: specs.map(([kind, a, b]) => {
        try {
          if (kind === 'unlink') pyfs.pyUnlink(a);
          else if (kind === 'read') pyfs.pyReadText(a);
          // `os.mkdir`, not `pyMkdirParents`: the reference's is non-recursive and this
          // case is about `str(OSError)`, so it goes through `asPyOSError` directly.
          else if (kind === 'mkdir') mkdirSync(a);
          else if (kind === 'replace') pyfs.pyReplace(a, b);
          else if (kind === 'resolve') pyfs.pyResolve(a);
          return { ok: true };
        } catch (e) {
          const err = e instanceof pyfs.PyOSError || e.name === 'RuntimeError' ? e : pyfs.asPyOSError(e, a);
          return { type: err.name, message: b64(err.message) };
        }
      }),
    });
  }

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

  // ------------------------------------------ the pressure line, as integer arithmetic
  //
  // `undegraded_index_ceiling(b)` is `(INDEX_PRESSURE_PERCENT * b - 1) // 100` on the
  // reference and `Math.floor((INDEX_PRESSURE_PERCENT * b - 1) / 100)` on the port. It is new
  // in job46 and it is the number `MemoryStore.compact`'s default `reserve` is now measured
  // from, so a one-byte disagreement here is a different set of facts archived on the two
  // sides of a store they share on disk. `//` against `Math.floor` is exactly the class of
  // expression that drifts between CPython and V8, so it is compared here rather than
  // reasoned about — and NOT by re-deriving the same expression in the harness, which would
  // only prove the harness agrees with itself.
  //
  // WHY THE CORPUS IS NOT A LIST OF ROUND NUMBERS, and why a case over 24000 alone would
  // prove nothing. Two distinct things can go wrong and each has its own class of budget:
  //
  //   * `PCT * b` NOT divisible by 100 — every budget that is not a multiple of 10. Here the
  //     floor truncates something, and an implementation that divided in floating point and
  //     rounded would land one byte out.
  //   * `PCT * b` divisible by 100 — every budget that IS a multiple of 10. Here and ONLY
  //     here does subtracting 1 change the answer, so this is the class that says whether the
  //     `- 1` survived the port. The default budget, 24000, is in it.
  //   * a NEGATIVE budget, where CPython's `//` floors toward -infinity and `Math.trunc`
  //     rounds toward zero. Unreachable through either CLI (both refuse a budget below 1) and
  //     compared anyway, because the function's signature does not refuse one and a helper
  //     that is right only on the inputs today's callers pass is a helper that breaks the
  //     first time a caller changes.
  //
  // The membership case below counts each class and pins the counts, so a later edit that
  // quietly trimmed the corpus to round numbers fails instead of going quietly green.
  //
  // THE BOOLEAN RIDES WITH THE NUMBER, and it is what makes the ceiling mean anything: the
  // condition both servers actually write is the cross-multiplied `size * 100 >= PCT * b`,
  // and the ceiling's whole contract is that `size > ceiling(b)` is the same predicate. Each
  // budget is therefore probed at `ceiling - 1`, `ceiling` and `ceiling + 1` — taken from the
  // PORT's ceiling — and the reference answers the comparison for those three sizes. A port
  // whose ceiling is one byte out probes three shifted sizes and the reference's answer stops
  // being `[false, false, true]`, so one case catches a wrong ceiling AND a wrong comparison.
  const ceilingBudgets = [
    // Every residue mod 10 and mod 100 across a full two hundred, so both classes above are
    // swept densely rather than sampled.
    ...Array.from({ length: 200 }, (_, i) => i + 1),
    // The budgets the product itself names or has been driven at.
    4096, 19200, 24000, 320, 1101, 995, 900,
    // Bigger, and each a different shape: a round thousand, one under, one over, a prime.
    1000, 999, 1001, 100000, 999999, 1000003,
    // 90 * (2**31 - 1) is 1.93e11 — exactly representable as a double, so this is a size
    // comparison and not a precision ruling in disguise.
    2 ** 31 - 1, 2 ** 31,
    // Zero and the negatives, where floor and trunc part company.
    0, -1, -2, -3, -5, -9, -10, -11, -99, -100, -101, -1000,
  ];
  const nodeCeiling = ceilingBudgets.map((b) => store.undegradedIndexCeiling(b));
  const ceilingSizes = nodeCeiling.map((c) => [c - 1, c, c + 1]);
  const ceilingRef = ctx.runPython(REF, { op: 'index_ceiling', budgets: ceilingBudgets, sizes: ceilingSizes });
  cases.push({
    name: 'undegraded_index_ceiling: the floor-divided pressure line, over both divisibility classes and both signs',
    kind: 'json',
    expected: { percent: ceilingRef.percent, ceiling: ceilingRef.ceiling },
    actual: { percent: store.INDEX_PRESSURE_PERCENT, ceiling: nodeCeiling },
  });
  cases.push({
    name: 'undegraded_index_ceiling: `size > ceiling(b)` is the cross-multiplied comparison the servers write',
    kind: 'json',
    // The reference answers `size * 100 >= PCT * b` for the three sizes straddling the PORT's
    // ceiling; the port answers its own `>` against its own ceiling. Both must be the same
    // triple, and that triple must be the straddle — a helper that answered a constant would
    // match itself and is caught by the literal.
    expected: { degraded: ceilingRef.degraded, straddles: ceilingBudgets.length },
    actual: {
      degraded: ceilingSizes.map((sizes, i) => sizes.map((size) => size > nodeCeiling[i])),
      straddles: ceilingSizes.filter((sizes, i) => {
        const said = sizes.map((size) => size > nodeCeiling[i]).join(',');
        return said === 'false,false,true';
      }).length,
    },
  });
  // The corpus's own teeth, per side and as a literal: a later edit that dropped the
  // multiples of ten would take the `- 1` out of the comparison without failing anything
  // above, because every remaining budget agrees whether or not the `- 1` is there.
  // 90 SPELLED OUT, and deliberately not read from either runtime: this is the harness's own
  // copy of the constant, the way `codec.mjs` keeps its own copy of `_write_fact`. If the
  // product ever moves the percent, these counts change and this case goes red — which is the
  // alarm wanted, because a corpus chosen for one percent is not swept for another.
  const HARNESS_PRESSURE_PERCENT = 90;
  const roundBudgets = ceilingBudgets.filter((b) => (HARNESS_PRESSURE_PERCENT * b) % 100 === 0);
  const floorNotTrunc = ceilingBudgets.filter(
    (b) =>
      Math.floor((HARNESS_PRESSURE_PERCENT * b - 1) / 100) !==
      Math.trunc((HARNESS_PRESSURE_PERCENT * b - 1) / 100),
  );
  cases.push({
    name: 'undegraded_index_ceiling: the corpus contains both divisibility classes and the budgets where floor and trunc differ',
    kind: 'json',
    expected: {
      budgets: 227,
      distinct: 227,
      whereTheMinusOneBites: 30,
      whereFloorBeatsTrunc: 12,
      holdsTheDefaultBudget: true,
      percentIsStillNinety: true,
    },
    actual: {
      budgets: ceilingBudgets.length,
      distinct: new Set(ceilingBudgets).size,
      whereTheMinusOneBites: roundBudgets.length,
      whereFloorBeatsTrunc: floorNotTrunc.length,
      holdsTheDefaultBudget: ceilingBudgets.includes(DEFAULT_INDEX_BUDGET),
      percentIsStillNinety: ceilingRef.percent === HARNESS_PRESSURE_PERCENT,
    },
  });

  // -------------------------------------------------------- the Windows path algebra
  //
  // THIS ONE RUNS ON EVERY PLATFORM AND THAT IS THE POINT. `ntpath` and `PureWindowsPath`
  // compute the same answers on Linux and macOS as they do on Windows, so the port's Windows
  // parsing can be measured against the reference on the laptop that writes it instead of
  // costing a CI cycle per correction. The case that made this necessary: `//a/b` is a UNC
  // share whose whole text is the drive, `PureWindowsPath('//a/b').parents` is `[]`, and this
  // port answered a two-element walk over directories that cannot exist (run 32646521489).
  //
  // The port's own `pyJoin`/`pyParents`/`pyWithSuffix` cannot be called here off Windows —
  // they read `process.platform` and would answer in POSIX — so what is compared is the
  // FLAVOUR-EXPLICIT layer underneath them, `ntSplitRoot` / `parseWindowsPath` / `ntJoin`,
  // which the Windows arms are a two-line wrapper over.
  const winRaws = ['//a', '///a', '////a/b', '//a/b', '//a/b/c', '//a/', '//', '/a', '/a/b/c',
    'a', 'a/b', '', '.', '/', '/a/b/../c', 'C:x', 'C:/x', 'C:', '\\\\srv\\share\\x',
    '//?/C:/x', '//?/UNC/srv/share/x', 'a.md', '/f/.md', '/f/a.', 'x/y.md', '\\\\a/b\\c'];
  const winJoins = [...joins, [String.raw`C:\a`, 'facts'], ['//srv/share', 'facts'],
    ['a', 'C:x'], ['C:/a', 'D:/b'], ['C:/a', 'C:b'], ['/a', '/b'], ['a', ''], ['', 'a']];
  // J63-1b (roadmap row (ddd)): the port follows CPython 3.12's `PureWindowsPath`, rewritten
  // in 3.12 over `os.path.splitroot`; 3.11's is a different algorithm that nobody chose (`//a`,
  // `////a/b`, `//?` and `PureWindowsPath('C:/a', 'C:b')` parse differently there, measured in
  // the J63-1 note), and `ntpath.splitroot` itself does not exist below 3.12. So the case is
  // asked ONLY of a 3.12+ reference. Below that it is WITHHELD — not sent to either side, and
  // named and counted in a note in the shape the win32 skips above use — rather than left as
  // a permanent red or hidden behind a `ruling:`, which is for a difference somebody chose.
  // Seen red before it was trusted: with the floor test mutated to `< 99` the 3.11 reference
  // reddened this one case with its old first-difference line (J63-1b note).
  const ref = ctx.runPython(REF, { op: 'version' });
  const [refMajor, refMinor] = ref.version_info;
  let winpathsArmed = false; // J63-5: the arming decision, pinned against a literal below
  if (refMajor < 3 || (refMajor === 3 && refMinor < 12)) {
    notes.push(
      `1 case withheld below Python 3.12 (the reference is ${ref.version}): ` +
        '`ntpath.splitroot and PureWindowsPath parsing, on every platform` — the port follows ' +
        "3.12's PureWindowsPath, and 3.11's is a different algorithm nobody chose; " +
        'run the reference on 3.12+ to arm it',
    );
  } else {
    winpathsArmed = true;
    const win = ctx.runPython(REF, {
      op: 'winpaths',
      raws: winRaws.map(b64),
      joins: winJoins.map((parts) => parts.map(b64)),
      suffixes: suffixes.map(([p, sfx]) => [b64(p), b64(sfx)]),
    });
    cases.push({
      name: 'ntpath.splitroot and PureWindowsPath parsing, on every platform',
      kind: 'json',
      expected: {
        splitroot: win.splitroot.map((row) => row.map(unb64)),
        parsed: win.parsed.map(([d, r, t]) => [unb64(d), unb64(r), t.map(unb64)]),
        str: win.str.map(unb64),
        parents: win.parents.map((row) => row.map(unb64)),
        absolute: win.absolute,
        ntisabs: win.ntisabs,
        ntsplit: win.ntsplit.map((row) => row.map(unb64)),
        name: win.name.map(unb64),
        suffix: win.suffix.map(unb64),
        ntjoined: win.ntjoined.map(unb64),
        joined: win.joined.map(unb64),
        suffixed: win.suffixed.map(unb64),
      },
      actual: {
        splitroot: winRaws.map((r) => [...pyfs.ntSplitRoot(r)]),
        parsed: winRaws.map((r) => {
          const { drive, root, tail } = pyfs.parseWindowsPath(r);
          return [drive, root, tail];
        }),
        str: winRaws.map((r) => pyfs.winStr(r)),
        parents: winRaws.map((r) => pyfs.winParents(r)),
        absolute: winRaws.map((r) => pyfs.winIsAbsolute(r)),
        ntisabs: winRaws.map((r) => pyfs.ntIsAbs(r)),
        ntsplit: winRaws.map((r) => [...pyfs.ntSplit(r)]),
        name: winRaws.map((r) => pyfs.winName(r)),
        suffix: winRaws.map((r) => {
          const nm = pyfs.winName(r);
          const dot = nm.lastIndexOf('.');
          return dot > 0 && dot < nm.length - 1 ? nm.slice(dot) : '';
        }),
        ntjoined: winJoins.map((parts) => pyfs.ntJoin(...parts)),
        joined: winJoins.map((parts) => pyfs.winStr(pyfs.ntJoin(...parts))),
        suffixed: suffixes.map(([pth, sfx]) => pyfs.winWithSuffix(pth, sfx)),
      },
    });
  }
  // J63-5: the floor test's OTHER direction — mutated to `< 99` the host was 254/0 with a self-contradicting note; this is what reddens (1 case).
  cases.push({
    name: 'winpaths is armed exactly when the reference is 3.12+, against a literal',
    kind: 'json',
    expected: { armed: refMajor > 3 || (refMajor === 3 && refMinor >= 12) },
    actual: { armed: winpathsArmed },
  });

  // The Win32 message table, asked of the running Windows. Off Windows `ctypes.FormatError`
  // has nothing to answer, so the case does not exist there and SAYS SO in a note rather
  // than reporting a pass it did not earn.
  if (process.platform === 'win32') {
    const winmsg = ctx.runPython(REF, { op: 'winerror', numbers: [...pyfs.WINERROR_NUMBERS] });
    cases.push({
      name: 'FormatMessage for every winerror the port claims to render',
      kind: 'json',
      expected: Object.fromEntries(Object.entries(winmsg.messages).map(([k, v]) => [k, unb64(v)])),
      actual: Object.fromEntries(pyfs.WINERROR_NUMBERS.map((n) => [String(n), pyfs.pyWinStrerror(n)])),
    });
  } else {
    notes.push(
      `winerror table: NOT MEASURED HERE — ${pyfs.WINERROR_NUMBERS.length} Win32 wordings are ` +
      'asked of ctypes.FormatError, which only exists on Windows. All fifteen ARE measured on ' +
      'the Windows cells of this repository\'s matrix and have passed there since run ' +
      '32649940727; what this platform cannot tell you is whether one has since drifted.',
    );
  }

  return { cases, notes };
}
