/**
 * A frontmatter scalar that is not a string, at every place the store renders one.
 *
 * WHY THIS FILE EXISTS. `_facts` in `runtime-py` puts `yaml.safe_load`'s answer into the
 * `Fact` dataclass with no type check, so `description: 2026` really does give the reference
 * store an `int` in a `str` field — and the reference store keeps working: it writes a
 * working `index.md` line, answers `memory_recall`, stamps the file and accepts the next
 * `memory_save`. This port used to refuse the WHOLE STORE for one such file. N8 measured 13
 * of 17 shapes doing it; N10 ported `SafeConstructor` so that they do not.
 *
 * Every expected string here was PRODUCED BY CPython 3.12 / PyYAML 6.0.3 and pasted in, not
 * derived by reading this port and agreeing with it. The live differential — 37 shapes
 * against the reference over three fact files, with the whole directory diffed — is
 * `frontmatter scalar:` in `tools/conformance/suites/store.mjs`, and 50,000 generated lists
 * for the recall tie-break are beside it. This file is the in-runtime half, so a mutation
 * that survives the pins is visible without a Python on PATH.
 */
import assert from 'node:assert/strict';
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  utimesSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import { Memory } from '../dist/memory/component.js';
import { MEMORY_DIR_ENV } from '../dist/memory/layers.js';

import { constructPlain, PyScalar, safeDumpMapping, YamlConstructError } from '../dist/memory/pyyaml.js';
import { parseFrontmatter } from '../dist/memory/factfile.js';
import {
  MemoryStore,
  MemoryValidationError,
  pyCompareLt,
  pyEqualValue,
  pyHashKey,
  pyText,
  sortScored,
} from '../dist/memory/store.js';

// -------------------------------------------------------------- what safe_load builds

/**
 * `[frontmatter spelling, str(value), safe_dump's spelling, bool(value)]`.
 *
 * `str()` and `safe_dump` are two different questions and the table proves it: they part on
 * every `bool` and on three of the floats. A port that carried one number per field would
 * have to re-derive both at each of the nine render points below.
 */
const SHAPES = [
  ['7', '7', '7', true],
  ['2026', '2026', '2026', true],
  ['0x1f', '31', '31', true],
  ['0b101', '5', '5', true],
  ['017', '15', '15', true],
  ['1_000', '1000', '1000', true],
  ['1:30', '90', '90', true],
  ['-0', '0', '0', false],
  ['0', '0', '0', false],
  ['+7', '7', '7', true],
  ['999999999999999999999999', '999999999999999999999999', '999999999999999999999999', true],
  ['1.5', '1.5', '1.5', true],
  ['1.0', '1.0', '1.0', true],
  ['1.0e+50', '1e+50', '1.0e+50', true],
  ['.inf', 'inf', '.inf', true],
  ['-.inf', '-inf', '-.inf', true],
  ['.nan', 'nan', '.nan', true],
  ['1:30.5', '90.5', '90.5', true],
  ['0.0', '0.0', '0.0', false],
  ['true', 'True', 'true', true],
  ['yes', 'True', 'true', true],
  ['On', 'True', 'true', true],
  ['no', 'False', 'false', false],
  ['off', 'False', 'false', false],
  ['2026-08-23', '2026-08-23', '2026-08-23', true],
  ['2026-08-23 10:00:00', '2026-08-23 10:00:00', '2026-08-23 10:00:00', true],
  ['2026-08-23T10:00:00Z', '2026-08-23 10:00:00+00:00', '2026-08-23 10:00:00+00:00', true],
  ['2026-08-23T10:00:00-05:30', '2026-08-23 10:00:00-05:30', '2026-08-23 10:00:00-05:30', true],
  ['2026-1-2 3:04:05', '2026-01-02 03:04:05', '2026-01-02 03:04:05', true],
  ['2026-08-23 10:00:00.1234567', '2026-08-23 10:00:00.123456', '2026-08-23 10:00:00.123456', true],
];

test('a plain scalar builds what SafeConstructor builds, and carries BOTH spellings', () => {
  for (const [text, str, dumped, truthy] of SHAPES) {
    const value = constructPlain(text);
    assert.ok(value instanceof PyScalar, `${text} should not stay a string`);
    assert.equal(pyText(value), str, `str() of ${text}`);
    assert.equal(safeDumpMapping([['k', value]]), `k: ${dumped}\n`, `safe_dump of ${text}`);
    assert.equal(value.truthy, truthy, `bool() of ${text}`);
  }
});

test('str and null are unchanged, and the tags with no constructor raise', () => {
  assert.equal(constructPlain('a fact name'), 'a fact name');
  assert.equal(constructPlain('1e+17'), '1e+17'); // no `.` before the exponent: a str, not a float
  assert.equal(constructPlain('00:00'), '00:00'); // leading zero: not sexagesimal
  assert.equal(constructPlain('y'), 'y'); // one letter is not a bool; only `yes`/`no`/… are
  assert.equal(constructPlain(''), null);
  assert.equal(constructPlain('~'), null);
  assert.equal(constructPlain('null'), null);
  for (const [text, tag] of [['<<', 'merge'], ['=', 'value'], ['!', 'yaml'], ['&', 'yaml'], ['*', 'yaml']]) {
    assert.throws(
      () => constructPlain(text),
      (e) =>
        e instanceof YamlConstructError &&
        e.message === `could not determine a constructor for the tag 'tag:yaml.org,2002:${tag}'`,
      `${text} should have no constructor`,
    );
  }
});

test("a timestamp the resolver accepts and datetime refuses carries CPython's own ValueError", () => {
  const cases = [
    ['2026-13-45', 'month must be in 1..12'],
    ['2026-02-30', 'day is out of range for month'],
    ['2026-02-29', 'day is out of range for month'], // 2026 is not a leap year
    ['0000-01-01', 'year 0 is out of range'],
    ['2026-08-23 25:00:00', 'hour must be in 0..23'],
    ['2026-08-23 10:99:00', 'minute must be in 0..59'],
    ['2026-08-23 10:00:99', 'second must be in 0..59'],
    [
      '2026-08-23T10:00:00+24:00',
      'offset must be a timedelta strictly between -timedelta(hours=24) and ' +
        'timedelta(hours=24), not datetime.timedelta(days=1).',
    ],
    [
      '2026-08-23T10:00:00-99:59',
      'offset must be a timedelta strictly between -timedelta(hours=24) and ' +
        'timedelta(hours=24), not datetime.timedelta(days=-5, seconds=72060).',
    ],
  ];
  for (const [text, message] of cases) {
    assert.throws(() => constructPlain(text), (e) => e.message === message, `${text}: ${message}`);
  }
  // 2024 IS a leap year, so the same day-of-month is fine there.
  assert.equal(pyText(constructPlain('2024-02-29')), '2024-02-29');
});

test('a sequence item resolves like a mapping value, and a bare dash is a null item', () => {
  assert.deepEqual(
    parseFrontmatter('links:\n- 12\n- a\n-\n- 2026-08-23\n').links.map(pyText),
    ['12', 'a', 'None', '2026-08-23'],
  );
  assert.equal(
    safeDumpMapping([['links', parseFrontmatter('links:\n- 12\n-\n').links]]),
    'links:\n- 12\n- null\n',
  );
});

// -------------------------------------------------------- `<` and `==`, and the sort

test('Python < over the four families, refusals included', () => {
  const v = (t) => constructPlain(t);
  assert.equal(pyCompareLt(v('7'), v('7.5')), true); // one numeric family
  assert.equal(pyCompareLt(v('true'), v('7')), true); // bool IS an int
  assert.equal(pyCompareLt(v('2026-08-23'), v('2026-08-24')), true);
  assert.equal(pyCompareLt(v('2026-08-23 10:00:00'), v('2026-08-23 11:00:00')), true);
  assert.equal(pyCompareLt('a', 'b'), true);
  assert.equal(pyCompareLt(v('.nan'), v('.nan')), false); // nan orders with nothing, silently
  for (const [a, b, message] of [
    [v('7'), 'a', "'<' not supported between instances of 'int' and 'str'"],
    ['a', v('7'), "'<' not supported between instances of 'str' and 'int'"],
    [null, 'a', "'<' not supported between instances of 'NoneType' and 'str'"],
    [null, null, "'<' not supported between instances of 'NoneType' and 'NoneType'"],
    [v('1.5'), v('2026-08-23'), "'<' not supported between instances of 'float' and 'datetime.date'"],
    // Both directions name `datetime` first — CPython's wording, not the operand order.
    [v('2026-08-23'), v('2026-08-23 00:00:00'), "can't compare datetime.datetime to datetime.date"],
    [v('2026-08-23 00:00:00'), v('2026-08-23'), "can't compare datetime.datetime to datetime.date"],
    [v('2026-08-23 00:00:00'), v('2026-08-23T00:00:00Z'), "can't compare offset-naive and offset-aware datetimes"],
  ]) {
    assert.throws(() => pyCompareLt(a, b), (e) => e.name === 'TypeError' && e.message === message, message);
  }
});

test('Python == never raises, and it is what keeps the sort from raising on two None names', () => {
  const v = (t) => constructPlain(t);
  assert.equal(pyEqualValue(null, null), true);
  assert.equal(pyEqualValue(v('7'), v('7.0')), true);
  assert.equal(pyEqualValue(v('true'), v('1')), true);
  assert.equal(pyEqualValue(v('.nan'), v('.nan')), false); // nan == nan is False
  assert.equal(pyEqualValue(v('7'), 'a'), false); // across types: False, never a raise
  assert.equal(pyEqualValue(v('2026-08-23'), v('2026-08-23 00:00:00')), false);
  assert.equal(pyEqualValue(v('2026-08-23 00:00:00'), v('2026-08-23T00:00:00Z')), false);
  // `sorted` walks the key tuple with `==` first, so two facts named `None` never reach `<`.
  assert.deepEqual(
    sortScored([{ score: 1, name: null, i: 0 }, { score: 1, name: null, i: 1 }]).map((x) => x.i),
    [0, 1],
  );
});

test('the sort names the types CPython names, in CPython\'s order', () => {
  const v = (t) => constructPlain(t);
  const run = (pairs) => {
    try {
      return sortScored(pairs.map(([score, name], i) => ({ score, name, i }))).map((x) => x.i).join(',');
    } catch (e) {
      return e.message;
    }
  };
  // The later element is on the LEFT of the `<` CPython performs, so the message names its
  // type first. Both orders are pinned because a port that got them backwards would still
  // raise, and still raise a plausible sentence.
  assert.equal(run([[3, v('7')], [3, 'in-meta']]), "'<' not supported between instances of 'str' and 'int'");
  assert.equal(run([[3, 'in-meta'], [3, v('7')]]), "'<' not supported between instances of 'int' and 'str'");
  // Different scores never compare the names at all.
  assert.equal(run([[3, v('7')], [2, 'a']]), '0,1');
  assert.equal(run([[2, v('7')], [3, 'a']]), '1,0');
  // One numeric family sorts; `True` is 1.
  assert.equal(run([[1, v('7')], [1, v('1.5')], [1, v('true')]]), '2,1,0');
});

// ---------------------------------------------------------------- the nine render points

const factFile = (over = {}) => {
  const f = { name: 'n', description: 'd', type: 'project', created: "'2026-08-01'", last: 'null', links: '[]', ...over };
  return (
    `---\nname: ${f.name}\ndescription: ${f.description}\ntype: ${f.type}\n` +
    `created: ${f.created}\nlast_recalled: ${f.last}\nlinks: ${f.links}\n---\n\nb\n`
  );
};

function bed(files, mtime = 1755990000) {
  // `realpathSync`: `os.tmpdir()` is not canonical — a `/var` symlink on macOS, the 8.3
  // short name on Windows CI. See the note in test/store.test.mjs.
  const root = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-scalars-')));
  mkdirSync(join(root, 'facts'), { recursive: true });
  mkdirSync(join(root, 'archive'), { recursive: true });
  for (const [name, text] of Object.entries(files)) {
    writeFileSync(join(root, 'facts', name), text, 'utf8');
    utimesSync(join(root, 'facts', name), mtime, mtime);
  }
  return root;
}

test('one hand-edited fact does not take the store down, and the index line is Python\'s', () => {
  const root = bed({
    'good-one.md': factFile({ name: 'good-one', description: 'a real description' }),
    'bad-one.md': factFile({ name: 'bad-one', description: '2026' }),
    'good-two.md': factFile({ name: 'good-two', description: 'another real description' }),
  });
  try {
    const store = new MemoryStore(root, { today: () => '2026-08-23', create: false });
    // THE DEFECT, in one line: this used to raise `MemoryValidationError` naming `bad-one.md`
    // while the Python server on the same directory answered.
    assert.equal(
      store.indexText(),
      '- [[bad-one]] (project) — 2026\n' +
        '- [[good-one]] (project) — a real description\n' +
        '- [[good-two]] (project) — another real description\n',
    );
    assert.deepEqual(store.recall('real description', 3, false).map((f) => f.name), ['good-one', 'good-two']);
    assert.equal(store.save('project', 'a-third', 'wholly unrelated words here', 'b').status, 'saved');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a non-string name reaches the FILE PATH, and _stamp writes there', () => {
  const root = bed({ 'in-name.md': factFile({ name: '2026-08-23', description: 'shared probe token' }) });
  try {
    const store = new MemoryStore(root, { today: () => '2026-08-23', create: false });
    assert.equal(store.indexText(), '- [[2026-08-23]] (project) — shared probe token\n');
    store.recall('shared probe token', 3, true);
    // `_write_fact` uses `f"{fact.name}.md"`, so the stamp lands on a NEW file named after
    // the date, and the original is left where it was.
    assert.deepEqual(readdirSync(join(root, 'facts')).sort(), ['2026-08-23.md', 'in-name.md']);
    // …and `created` goes back through `safe_dump` as the quoted string it came in as,
    // while a `date` in that field would go back unquoted. Both are pinned below.
    assert.match(readFileSync(join(root, 'facts', '2026-08-23.md'), 'utf8'), /^name: 2026-08-23\n/m);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a date in created round-trips through _stamp unquoted, and a falsy value falls back', () => {
  const root = bed({
    'dated.md': factFile({ name: 'dated', description: 'shared probe token', created: '2026-08-23' }),
    'zeroed.md': factFile({ name: 'zeroed', description: 'shared probe token', created: '0' }),
  });
  try {
    const store = new MemoryStore(root, { today: () => '2026-08-23', create: false });
    const hits = store.recall('shared probe token', 3, false);
    assert.equal(pyText(hits.find((f) => f.name === 'dated').created), '2026-08-23');
    // `created or _mtime_date(path)`: `0` is FALSY in Python, so the mtime wins. 1755990000
    // is 2025-08-24 in this machine's zone or the day either side of it; what is pinned is
    // that it is NOT `0`.
    assert.notEqual(pyText(hits.find((f) => f.name === 'zeroed').created), '0');
    assert.match(pyText(hits.find((f) => f.name === 'zeroed').created), /^\d{4}-\d{2}-\d{2}$/);
    store.recall('shared probe token', 3, true);
    assert.match(readFileSync(join(root, 'facts', 'dated.md'), 'utf8'), /^created: 2026-08-23$/m);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('links: a falsy scalar is [], and a truthy one is list()\'s TypeError, uncaught', () => {
  for (const [links, expected] of [['0', []], ['false', []], ['null', []], ['abc', ['a', 'b', 'c']]]) {
    const root = bed({ 'l.md': factFile({ name: 'l', links }) });
    try {
      const store = new MemoryStore(root, { today: () => '2026-08-23', create: false });
      assert.deepEqual(store.recall('d', 3, false)[0].links.map(pyText), expected, `links: ${links}`);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  }
  const root = bed({ 'l.md': factFile({ name: 'l', links: '12' }) });
  try {
    const store = new MemoryStore(root, { today: () => '2026-08-23', create: false });
    // `except (ValueError, KeyError, yaml.YAMLError)` in `_facts` does NOT catch `TypeError`,
    // so this escapes as itself and never becomes `malformed fact file …`.
    assert.throws(
      () => store.indexText(),
      (e) => e.name === 'TypeError' && e.message === "'int' object is not iterable" &&
        !(e instanceof MemoryValidationError),
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('the layered dedupe set is hash/==, not str', () => {
  // Python's `seen` is a `set`, so `7`, `7.0` and `True` are ONE key and `'7'` is another.
  const v = (t) => constructPlain(t);
  assert.equal(pyHashKey(v('7')), pyHashKey(v('7.0')));
  assert.equal(pyHashKey(v('1')), pyHashKey(v('true')));
  assert.notEqual(pyHashKey(v('7')), pyHashKey('7'));
  assert.notEqual(pyHashKey(v('2026-08-23')), pyHashKey('2026-08-23'));
  assert.equal(pyHashKey(null), 'None');
});

test('a numeric name and its string spelling are TWO facts across layers, not one', () => {
  // `Memory.recall` dedupes across layers with `if fact.name in seen` over a Python `set`,
  // which is `hash`/`==`. `7` and `'7'` are different keys there and `pyText` would collapse
  // them into one, dropping a fact the reference reports; `7`, `7.0` and `True` are the SAME
  // key, and a key built from the JS type would report a fact the reference drops. Both
  // directions are exercised here, through the real layered surface.
  const bed = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-scalar-layers-')));
  const home = join(bed, 'home');
  const project = join(bed, 'p');
  const grant = join(bed, 'granted');
  // Every description scores DIFFERENTLY inside its own store, so what this test measures
  // is the dedupe and not the tie-break (which has its own cases above).
  const store = (root, files) => {
    mkdirSync(join(root, 'facts'), { recursive: true });
    mkdirSync(join(root, 'archive'), { recursive: true });
    for (const [file, [name, description]] of Object.entries(files)) {
      writeFileSync(
        join(root, 'facts', `${file}.md`),
        `---\nname: ${name}\ndescription: ${description}\ntype: project\n` +
          `created: '2026-08-01'\nlast_recalled: null\nlinks: []\n---\n\nb\n`,
      );
    }
  };
  store(join(home, '.bantamkit', 'memory'), {});
  store(join(project, '.bantamkit', 'memory'), {
    seven: ['7', 'shared probe token'],
    trueish: ['true', 'shared probe'],
  });
  store(grant, {
    sevenstr: ["'7'", 'shared probe token'],
    sevenfloat: ['7.0', 'shared probe'],
    one: ['1', 'shared'],
  });
  writeFileSync(join(project, '.bantamkit', 'config.yaml'), `extra_stores:\n- ${grant}\n`);

  const saved = { [MEMORY_DIR_ENV]: process.env[MEMORY_DIR_ENV], HOME: process.env.HOME };
  delete process.env[MEMORY_DIR_ENV];
  process.env.HOME = home;
  try {
    const out = Memory.layered(project, { today: () => '2026-08-23', k: 9 }).recall('shared probe token');
    const lines = out.split('\n\n').map((block) => block.split('\n')[0]);
    // The project layer contributes `7` and `True`. In the grant, `'7'` is a DIFFERENT key
    // and survives; `7.0` equals `7` and `1` equals `True`, so both are dropped.
    assert.deepEqual(lines, [
      '[project] [7] (project) shared probe token',
      '[project] [True] (project) shared probe',
      '[extra:granted] [7] (project) shared probe token',
    ]);
  } finally {
    if (saved[MEMORY_DIR_ENV] === undefined) delete process.env[MEMORY_DIR_ENV];
    else process.env[MEMORY_DIR_ENV] = saved[MEMORY_DIR_ENV];
    process.env.HOME = saved.HOME;
    rmSync(bed, { recursive: true, force: true });
  }
});
