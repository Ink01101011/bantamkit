/**
 * The fact-file codec, against `runtime-py/src/bantamkit/memory/store.py`.
 *
 * Every expected string in this file was PRODUCED BY PyYAML 6.0.3 and pasted in, not
 * derived by reading the emitter and agreeing with it. The live differential — Python and
 * Node emitting the same 65 real facts plus the adversarial set and comparing sha256 —
 * lives in `tools/conformance/suites/codec.mjs`, because it needs a Python interpreter and
 * `npm test` must not. This file is the in-runtime half: it pins the shapes so a mutation
 * that survives the pins is visible without a Python on PATH.
 *
 * The risk this unit exists for is that a wrong emitter RAISES NOTHING — the file still
 * round-trips to the same string, the store just silently stops being byte-comparable with
 * the Python one. So the assertions here are on BYTES, never on parsed values.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const dist = join(dirname(dirname(fileURLToPath(import.meta.url))), 'dist');
const { formatFact, parseFactText, decodeFactBytes, pyStrip, todayLocal, FactParseError } =
  await import(pathToFileURL(join(dist, 'memory', 'factfile.js')).href);
const pyfs = await import(pathToFileURL(join(dist, 'memory', 'pyfs.js')).href);

/** A Fact with every field defaulted, so a case names only what it is about. */
function fact(over = {}) {
  return {
    name: 'n',
    description: 'd',
    type: 'project',
    body: 'b',
    links: [],
    last_recalled: null,
    created: null,
    ...over,
  };
}

/** The frontmatter only — the part `yaml.safe_dump` produces. */
function front(f) {
  const text = formatFact(f);
  return text.slice('---\n'.length, text.indexOf('---\n\n'));
}

// ------------------------------------------------------------------ shape and order

test('the six keys emit in the fixed order sort_keys=False froze', () => {
  assert.equal(
    front(fact()),
    'name: n\ndescription: d\ntype: project\ncreated: null\nlast_recalled: null\nlinks: []\n',
  );
});

test('the whole file is frontmatter, a blank line, the stripped body, one newline', () => {
  assert.equal(
    formatFact(fact({ body: '\n\nhello\n\n\n' })),
    '---\nname: n\ndescription: d\ntype: project\ncreated: null\n' +
      'last_recalled: null\nlinks: []\n---\n\nhello\n',
  );
});

test('a date emits SINGLE-QUOTED — bare 2026-08-23 would parse back as a date object', () => {
  assert.equal(
    front(fact({ created: '2026-08-23', last_recalled: '2026-08-22' })),
    "name: n\ndescription: d\ntype: project\ncreated: '2026-08-23'\n" +
      "last_recalled: '2026-08-22'\nlinks: []\n",
  );
});

test('links: [] is flow, one and three links are a block sequence at column 0', () => {
  assert.match(front(fact({ links: [] })), /\nlinks: \[\]\n$/);
  assert.match(front(fact({ links: ['a'] })), /\nlinks:\n- a\n$/);
  assert.match(front(fact({ links: ['a', 'b', 'c'] })), /\nlinks:\n- a\n- b\n- c\n$/);
});

// ------------------------------------------------------------------ the 80-column wrap

// PyYAML breaks a plain scalar at a SINGLE space, and only once the column is already
// PAST 80 — the check runs after the word before the space has been written. Continuation
// lines are indented by 2. `description: ` costs 13 columns.

const WRAP_HEAD =
  'name: n\ndescription: aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa\n';
const WRAP_TAIL = '\ntype: project\ncreated: null\nlast_recalled: null\nlinks: []\n';
/** 30 four-letter words; slicing it hits the boundary from both sides. */
const RULER = Array(30).fill('aaaa').join(' ');

test('the wrap boundary from both sides: 78, 79, 81, 82 characters', () => {
  assert.equal(front(fact({ description: RULER.slice(0, 78) })), WRAP_HEAD + '  aaaa aaa' + WRAP_TAIL);
  assert.equal(front(fact({ description: RULER.slice(0, 79) })), WRAP_HEAD + '  aaaa aaaa' + WRAP_TAIL);
  assert.equal(front(fact({ description: RULER.slice(0, 81) })), WRAP_HEAD + '  aaaa aaaa a' + WRAP_TAIL);
  assert.equal(front(fact({ description: RULER.slice(0, 82) })), WRAP_HEAD + '  aaaa aaaa aa' + WRAP_TAIL);
});

test('at 80 the slice ends in a space, which forces quotes — and the QUOTED form wraps too', () => {
  // trailing_space -> plain forbidden -> single quoted. The single-quoted writer has its
  // own wrap with two extra guards the plain writer does not have
  // (`start != 0 and end != len(text)`), which is why the trailing space SURVIVES the
  // wrap here instead of being eaten by the break.
  assert.equal(
    front(fact({ description: RULER.slice(0, 80) })),
    "name: n\ndescription: 'aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa\n" +
      "  aaaa aaaa '\ntype: project\ncreated: null\nlast_recalled: null\nlinks: []\n",
  );
});

test('the wrap fires at column > 80, NOT >= 80 — a word ending exactly at 80', () => {
  // Found by mutation: `bestWidth = 79` and `column >= bestWidth` both SURVIVED the whole
  // 126-fact corpus, because four-letter words never end a line at column 80. Three-letter
  // words do: `description: ` is 13 columns, so word 17 ends at exactly 80 and the space
  // after it must NOT break. The break comes one word later, at 84.
  assert.equal(
    front(fact({ description: Array(19).fill('aaa').join(' ') })),
    'name: n\ndescription: aaa aaa aaa aaa aaa aaa aaa aaa aaa aaa aaa aaa aaa aaa aaa aaa aaa aaa\n' +
      '  aaa\ntype: project\ncreated: null\nlast_recalled: null\nlinks: []\n',
  );
});

test('a trailing space past column 80 survives inside single quotes', () => {
  // Found by mutation: dropping `start !== 0 && end !== chars.length` from the
  // single-quoted writer SURVIVED the corpus. Those guards are the reason a trailing space
  // is written literally instead of being swallowed by a wrap — but only when the column
  // is already past 80 when the trailing space arrives, which needs a long unbreakable
  // word. (`start !== 0`, the leading-space half, is unreachable at these key lengths:
  // the column at the start of a value is at most 15.)
  assert.equal(
    front(fact({ description: 'a: ' + 'w'.repeat(90) + ' ' })),
    `name: n\ndescription: 'a: ${'w'.repeat(90)} '\ntype: project\ncreated: null\nlast_recalled: null\nlinks: []\n`,
  );
});

test('a description that wraps twice', () => {
  const d = Array(45).fill('aaaa').join(' ');
  assert.equal(
    front(fact({ description: d })),
    'name: n\ndescription: aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa\n' +
      '  aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa\n' +
      '  aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa\n' +
      'type: project\ncreated: null\nlast_recalled: null\nlinks: []\n',
  );
});

test('a single long word never wraps — there is no space to break at', () => {
  assert.equal(
    front(fact({ description: 'w'.repeat(120) })),
    `name: n\ndescription: ${'w'.repeat(120)}\ntype: project\ncreated: null\nlast_recalled: null\nlinks: []\n`,
  );
});

test('the wrap column counts CODEPOINTS, not UTF-16 units — two emoji move the break', () => {
  // Python charges `len(str)` = codepoints; `String.length` charges 2 per astral emoji and
  // would break a word early. FOUND BY MUTATION: an earlier version of this test used a
  // description where both countings happened to agree, and `column += data.length`
  // survived the whole unit suite. This one does not agree — with UTF-16 columns the last
  // `aaaa` on line 1 moves down to line 2.
  assert.equal(
    front(fact({ description: `🐔🐔 ${Array(15).fill('aaaa').join(' ')}` })),
    'name: n\ndescription: 🐔🐔 aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa\n' +
      '  aaaa\ntype: project\ncreated: null\nlast_recalled: null\nlinks: []\n',
  );
});

test('em dash, Thai and emoji stay raw — allow_unicode=True, nothing is escaped', () => {
  const d = 'an em dash — ภาษาไทย และ emoji 🐔 that pushes the column past the eighty mark ok';
  assert.equal(
    front(fact({ description: d })),
    'name: n\ndescription: an em dash — ภาษาไทย และ emoji 🐔 that pushes the column past the eighty\n' +
      '  mark ok\ntype: project\ncreated: null\nlast_recalled: null\nlinks: []\n',
  );
});

// ------------------------------------------------------- what forces a quote, and which

test('the characters that force PyYAML out of plain style', () => {
  const q = (d) => front(fact({ description: d })).split('\n')[1];
  assert.equal(q('a: b'), "description: 'a: b'"); // ': ' -> block indicator
  assert.equal(q('a #b'), "description: 'a #b'"); // ' #' -> comment start
  assert.equal(q('- a'), "description: '- a'"); //   leading '-' + space
  assert.equal(q('a '), "description: 'a '"); //     trailing space
  assert.equal(q(''), "description: ''"); //         empty resolves to null
  assert.equal(q('null'), "description: 'null'"); // resolves to null
  assert.equal(q('yes'), "description: 'yes'"); //   resolves to bool
  assert.equal(q('2026-08-23'), "description: '2026-08-23'"); // resolves to timestamp
  assert.equal(q('12'), "description: '12'"); //     resolves to int
  assert.equal(q('#a'), "description: '#a'"); //     leading '#'
  assert.equal(q('a:b'), 'description: a:b'); //     ':' NOT followed by space is fine
  assert.equal(q('a-b'), 'description: a-b');
  assert.equal(q('a#b'), 'description: a#b'); //     '#' not preceded by space is fine
});

test("a lone ' is doubled inside single quotes, but only quotes when it leads", () => {
  const q = (d) => front(fact({ description: d })).split('\n')[1];
  // MEASURED REFUTATION of the brief's case list: a non-leading apostrophe is not an
  // indicator anywhere in analyze_scalar, so PyYAML leaves it PLAIN.
  assert.equal(q("it's"), "description: it's");
  assert.equal(q("'lead"), "description: '''lead'");
  assert.equal(q("a: it's"), "description: 'a: it''s'");
});

test('a control character forces DOUBLE quotes and escaping', () => {
  const q = (d) => front(fact({ description: d })).split('\n')[1];
  assert.equal(q('a\x01b'), 'description: "a\\x01b"');
  assert.equal(q('a\tb'), 'description: "a\\tb"');
});

test('a line break does NOT force double quotes — it emits a folded blank line', () => {
  // MEASURED REFUTATION of the obvious guess. `line_breaks` clears only
  // `allow_block_plain`; `allow_single_quoted` survives, so PyYAML emits a MULTI-LINE
  // single-quoted scalar. `write_single_quoted`'s `breaks` arm writes one extra break so
  // that the reader's fold (n breaks -> n-1 newlines) gives the `\n` back.
  assert.equal(
    front(fact({ description: 'a\nb' })),
    "name: n\ndescription: 'a\n\n  b'\ntype: project\ncreated: null\nlast_recalled: null\nlinks: []\n",
  );
  assert.equal(parseFactText(formatFact(fact({ description: 'a\nb' }))).meta.description, 'a\nb');
  assert.equal(parseFactText(formatFact(fact({ description: 'a\n\nb' }))).meta.description, 'a\n\nb');
});

test('a name at both ends of ^[a-z0-9][a-z0-9-]*$ stays plain', () => {
  assert.match(front(fact({ name: 'a' })), /^name: a\n/);
  assert.match(front(fact({ name: '0-' })), /^name: 0-\n/);
  assert.match(front(fact({ name: 'a'.repeat(100) })), /^name: a{100}\n/);
  // ...except the ones the resolver claims. Both of these pass `^[a-z0-9][a-z0-9-]*$`,
  // so a store CAN hold them, and both come out QUOTED: `0` is an int and `on` is a bool.
  assert.match(front(fact({ name: '0' })), /^name: '0'\n/);
  assert.match(front(fact({ name: 'on' })), /^name: 'on'\n/);
});

// ------------------------------------------------------------------ the body, and strip

test("the body is stripped with PYTHON's whitespace set, not JS trim()", () => {
  // Measured over all 0x110000 codepoints: Python str.strip() also strips
  // U+001C..U+001F and U+0085; JS trim() also strips U+FEFF. Six codepoints of
  // difference, and each one silently changes a byte the store then hashes.
  assert.equal(pyStrip(' x '), 'x');
  assert.equal(pyStrip('\ufeffx\ufeff'), '﻿x﻿');
  assert.equal('\ufeffx\ufeff'.trim(), 'x', 'JS trim would have eaten the BOM');
  assert.equal(pyStrip('\x1cx\x85'), 'x');
  assert.equal('\x1cx\x85'.trim(), '\x1cx\x85', 'JS trim strips neither U+001C nor U+0085');
  assert.equal(pyStrip(' x　'), 'x');
});

test('an empty body still ends the file with exactly one newline', () => {
  assert.ok(formatFact(fact({ body: '' })).endsWith('links: []\n---\n\n\n'));
  assert.ok(formatFact(fact({ body: '   \n  ' })).endsWith('links: []\n---\n\n\n'));
});

test('a body containing ---\\n in the middle survives emit unchanged', () => {
  const text = formatFact(fact({ body: 'one\n---\ntwo' }));
  assert.ok(text.endsWith('---\n\none\n---\ntwo\n'));
  // ...and parses back, because the split is bounded to 2 like Python's.
  assert.equal(parseFactText(text).body, 'one\n---\ntwo');
});

// ------------------------------------------------------------------ the parse direction

test('every emitted form parses back to the record it came from', () => {
  const cases = [
    fact(),
    fact({ description: 'a: b # c', links: ['x', 'y'], created: '2026-08-23' }),
    fact({ description: Array(45).fill('aaaa').join(' ') }),
    fact({
      description:
        'aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa aaaa'.slice(
          0,
          80,
        ),
    }),
    fact({
      description: 'an em dash — ภาษาไทย และ emoji 🐔 that pushes the column past the eighty mark ok',
    }),
    fact({ description: 'a\x01b\tc' }),
    fact({ description: "it's a '" }),
    fact({ description: '' }),
    fact({ last_recalled: '2026-08-22', created: '2026-08-01', links: ['a'] }),
    fact({ body: 'line one\nline two\n' }),
  ];
  for (const f of cases) {
    const { meta, body } = parseFactText(formatFact(f));
    assert.deepEqual(
      meta,
      {
        name: f.name,
        description: f.description,
        type: f.type,
        created: f.created,
        last_recalled: f.last_recalled,
        links: f.links,
      },
      `round trip lost something for ${JSON.stringify(f.description)}`,
    );
    assert.equal(body, pyStrip(f.body));
  }
});

test('the parser undoubles \'\' and folds a wrapped quoted scalar', () => {
  // FOUND BY MUTATION: dropping the `''` un-doubling survived `npm test` and was caught
  // only by the conformance differential. A parser that reads its own emitter's output
  // wrongly is silent — the value just quietly loses a character.
  const p = (front) => parseFactText(`---\n${front}---\n\nb\n`).meta.description;
  assert.equal(p("name: n\ndescription: '''lead'\ntype: project\n"), "'lead");
  assert.equal(p("name: n\ndescription: 'a: it''s'\ntype: project\n"), "a: it's");
  assert.equal(p("name: n\ndescription: 'one two'\ntype: project\n"), 'one two');
  // a wrapped single-quoted scalar folds the break back to one space...
  assert.equal(p("name: n\ndescription: 'a: one\n  two'\ntype: project\n"), 'a: one two');
  // ...and a blank line folds to one newline, which is how a `\n` survives on disk.
  assert.equal(p("name: n\ndescription: 'a\n\n  b'\ntype: project\n"), 'a\nb');
  // double-quoted: escapes, and a trailing backslash means "no space here"
  assert.equal(p('name: n\ndescription: "a\\tb"\ntype: project\n'), 'a\tb');
  assert.equal(p('name: n\ndescription: "a\\x01b"\ntype: project\n'), 'a\x01b');
  assert.equal(p('name: n\ndescription: "one\\\n  two"\ntype: project\n'), 'onetwo');
});

test("the split is bounded to 2 the way Python's split('---\\n', 2) is", () => {
  assert.throws(() => parseFactText('no frontmatter here\n'), FactParseError);
  assert.throws(() => parseFactText('---\nname: n\n'), FactParseError);
});

test('frontmatter that is not a mapping is refused, not guessed at', () => {
  assert.throws(() => parseFactText('---\n- a\n- b\n---\n\nbody\n'), FactParseError);
});

// ------------------------------------------------------------------ newline translation

test('CRLF on disk decodes to LF, the way Python text mode does', () => {
  // MEASURED in the prep probe: a CRLF fact file splits into 3 parts in Python and 1 in
  // Node without this. The bug is not that the parse is wrong, it is that the parse
  // SUCCEEDS with one part and the store reports the file malformed.
  const crlf = Buffer.from(
    '---\r\nname: n\r\ndescription: d\r\ntype: project\r\n---\r\n\r\nbody\r\n',
    'utf8',
  );
  const text = decodeFactBytes(crlf);
  assert.equal(text.split('---\n').length, 3);
  const { meta, body } = parseFactText(text);
  assert.equal(meta.name, 'n');
  assert.equal(body, 'body');
  assert.equal(decodeFactBytes(Buffer.from('a\rb\r\nc\n', 'utf8')), 'a\nb\nc\n');
});

test('the EMITTER builds LF text; the WRITER is what translates it', () => {
  // The emitter's half never moves: `index_text`, the index budget and both digests are
  // computed on this string, exactly as the reference computes them on its own LF string.
  assert.ok(!formatFact(fact({ body: 'a\nb' })).includes('\r'));
  // The writer's half is where `newline=None` lives, and it is CPython's rule rather than
  // this port's. N2 ruled the port would write LF everywhere; run 32646521489 measured what
  // that ruling cost — 83 of 132 Windows conformance failures, one byte per line, in files
  // the Python server and this one both write into the SAME store on the SAME machine.
  // Reversed. `toCrlf` is the translation, and it is the platform gate in `pyNewlineOut`
  // that decides whether it runs, so both halves have a node that can fail here.
  assert.equal(pyfs.toCrlf('a\nb\n'), 'a\r\nb\r\n');
  // Including the `\n` of a CRLF that was already in the string: `TextIOWrapper` translates
  // the LF it finds and does not look at what precedes it, so CPython emits `\r\r\n`.
  assert.equal(pyfs.toCrlf('a\r\nb'), 'a\r\r\nb');
  assert.equal(pyfs.toCrlf('a\rb'), 'a\rb');
  assert.equal(pyfs.PY_LINESEP, process.platform === 'win32' ? '\r\n' : '\n');
  assert.equal(pyfs.pyNewlineOut('a\nb'), process.platform === 'win32' ? 'a\r\nb' : 'a\nb');
  // And what actually reaches the disk is the writer's answer, not the emitter's.
  const bed = mkdtempSync(join(tmpdir(), 'bk-linesep-'));
  try {
    const path = join(bed, 'x.md');
    pyfs.pyWriteText(path, 'a\nb\n');
    assert.deepEqual([...readFileSync(path)], [...Buffer.from(pyfs.pyNewlineOut('a\nb\n'), 'utf8')]);
    // Read is universal-newline on both platforms, so the round trip is LF either way.
    assert.equal(pyfs.pyReadText(path), 'a\nb\n');
  } finally {
    rmSync(bed, { recursive: true, force: true });
  }
});

// ------------------------------------------------------------------ the clock

test('todayLocal is LOCAL, and toISOString().slice(0,10) is not the same thing', () => {
  // `date.today()` is local. Measured against CPython under four zones: the local getters
  // agree everywhere, the UTC slice disagrees for 4 of 12 sampled instants.
  const instant = new Date(1755990000 * 1000); // 2025-08-23T21:40Z = 2025-08-24 in UTC+7
  const local = todayLocal(instant);
  const p = (n) => String(n).padStart(2, '0');
  assert.equal(
    local,
    `${instant.getFullYear()}-${p(instant.getMonth() + 1)}-${p(instant.getDate())}`,
  );
  assert.match(local, /^\d{4}-\d{2}-\d{2}$/);
  if (instant.getTimezoneOffset() !== 0) {
    assert.notEqual(local, instant.toISOString().slice(0, 10));
  }
  // A year before 1000 must still be four digits: Python's isoformat zero-pads.
  assert.equal(todayLocal(new Date(Date.UTC(7, 0, 2, 12))).length, 10);
});
