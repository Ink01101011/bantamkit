/**
 * contract — Layer 2, the strings the model reads and the parse of what it writes.
 *
 * THE PROPERTY: for every validation failure bantamkit can produce, Node emits the
 * BYTE-IDENTICAL string Python emits. Not the same meaning, not the same field — the same
 * bytes. Two of these sentences are pinned in the Python suite
 * (`test_layers.py:592`, `test_structured.py:82`) and reach both the model's retry turn and
 * a shift-work checkpoint's refusal reason.
 *
 * The Python side of the comparison is NOT here: it is
 * `tools/conformance/suites/validate.mjs`, which runs the real `bantamkit.contract` over
 * the same corpus. This file pins what a unit test can pin without an interpreter — the
 * two sentences the Python suite itself asserts, `best_match`'s CHOICE on documents with
 * several errors, `extract_json`'s two arms, and the reader for `assets/contracts/default.yaml`.
 */
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const contract = await import(new URL('contract.js', dist));
const pyjson = await import(new URL('pyjson.js', dist));
const pyjsonschema = await import(new URL('pyjsonschema.js', dist));
const assets = await import(new URL('assets.js', dist));

const js = (v) => pyjson.fromJs(v);

// ------------------------------------------------- the two sentences Python's suite pins

test('the sentence test_layers.py:592 asserts, byte for byte', () => {
  assert.equal(
    contract.schemaError('{"a": "x"}', js({ type: 'object', properties: { a: { type: 'integer' } } })),
    "JSON does not match schema at 'a': 'x' is not of type 'integer'",
  );
});

test('the sentence test_structured.py:82 looks for', () => {
  const err = contract.schemaError('{}', js({ type: 'object', required: ['email'] }));
  assert.equal(err, "JSON does not match schema at 'root': 'email' is a required property");
  assert.ok(contract.schemaRetryFeedback(err).includes("'email' is a required property"));
  assert.equal(
    contract.schemaRetryFeedback(err),
    "JSON does not match schema at 'root': 'email' is a required property\n" +
      'Return ONLY a JSON object matching the schema.',
  );
});

// ------------------------------------------------------------- best_match, the CHOICE

test('best_match picks the SHALLOWEST error, not the first in traversal order', () => {
  // `properties` is traversed before `required` in this schema's key order, so a port that
  // reports the first error it finds says 'a/b' and a port that reproduces the heuristic
  // says 'root'. Both sentences are well formed; only one is Python's.
  const schema = js({
    properties: { a: { properties: { b: { type: 'integer' } } } },
    required: ['z'],
  });
  assert.equal(
    contract.schemaError('{"a": {"b": "x"}}', schema),
    "JSON does not match schema at 'root': 'z' is a required property",
  );
});

test('best_match breaks a same-depth tie by taking the LARGEST path, not the first', () => {
  // Two sibling errors at depth 1. `relevance` sorts on `error.path` and `max` takes the
  // largest, so the answer is 'b' even though 'a' is produced first.
  const schema = js({ properties: { a: { type: 'integer' }, b: { type: 'integer' } } });
  assert.equal(
    contract.schemaError('{"a": "x", "b": "y"}', schema),
    "JSON does not match schema at 'b': 'y' is not of type 'integer'",
  );
});

test('best_match prefers a non-weak keyword over anyOf at the same depth', () => {
  // Both errors sit on `v`. `anyOf` is a WEAK match, so the `type` error wins even though
  // the schema lists `anyOf` first and it is therefore produced first.
  const schema = js({ properties: { v: { anyOf: [{ type: 'string' }], type: 'object' } } });
  assert.equal(
    contract.schemaError('{"v": 5}', schema),
    "JSON does not match schema at 'v': 5 is not of type 'object'",
  );
});

test('best_match stops at the anyOf when its two best children tie', () => {
  // The descent into `context` is only taken when one child is strictly more relevant than
  // the next. Two branches that both fail on `type` tie, so the anyOf's own sentence stands
  // — a port that always descends would name the first branch and be wrong here.
  for (const branches of [
    [{ type: 'string' }, { type: 'boolean' }],
    [{ type: 'string' }, { minimum: 3 }],
  ]) {
    assert.equal(
      contract.schemaError('{"v": 1}', js({ properties: { v: { anyOf: branches } } })),
      "JSON does not match schema at 'v': 1 is not valid under any of the given schemas",
    );
  }
});

test('inside a context the preference INVERTS: the deepest child wins', () => {
  // At the top level `max(relevance)` prefers the shallowest error. The descent uses
  // `nsmallest` over the SAME key, so inside an anyOf/oneOf context it prefers the DEEPEST —
  // those keywords only have to match once, so the shallow "did not match" is the useless
  // half. A port that reused the top-level comparison here would answer 'v' and Python
  // answers 'v/q'. The path is also the proof that absolute and relative paths are kept
  // apart: 'v' comes from the parent, 'q' from the child.
  const schema = js({
    properties: { v: { anyOf: [{ type: 'string' }, { properties: { q: { type: 'integer' } } }] } },
  });
  assert.equal(
    contract.schemaError('{"v": {"q": "x"}}', schema),
    "JSON does not match schema at 'v/q': 'x' is not of type 'integer'",
  );
});

// -------------------------------------------------------------- the seven error classes

test('every error class the checkpoint schema uses has its own sentence', () => {
  const cases = [
    [{ required: ['b'] }, '{"a": 1}', "root", "'b' is a required property"],
    [{ properties: { a: { type: 'integer' } } }, '{"a": "x"}', 'a', "'x' is not of type 'integer'"],
    [
      { properties: { h: { additionalProperties: false, properties: { n: {} } } } },
      '{"h": {"n": 1, "notes": "hi"}}',
      'h',
      "Additional properties are not allowed ('notes' was unexpected)",
    ],
    [{ properties: { s: { enum: ['todo', 'done'] } } }, '{"s": "nope"}', 's',
      "'nope' is not one of ['todo', 'done']"],
    [{ properties: { i: { minLength: 1 } } }, '{"i": ""}', 'i', "'' should be non-empty"],
    [{ properties: { h: { maxItems: 5 } } }, '{"h": [1,2,3,4,5,6]}', 'h', '[1, 2, 3, 4, 5, 6] is too long'],
    [{ properties: { version: { const: 1 } } }, '{"version": 2}', 'version', '1 was expected'],
  ];
  for (const [schema, output, where, detail] of cases) {
    assert.equal(
      contract.schemaError(output, js(schema)),
      `JSON does not match schema at '${where}': ${detail}`,
      JSON.stringify(schema),
    );
  }
});

test('the real checkpoint schema refuses a real defect with the real sentence', () => {
  const schema = assets.loadSchema('shiftwork-checkpoint');
  // `URL.pathname` is NOT a filesystem path. On Windows it is `/D:/a/...`, and joining
  // that yields `\D:\a\...`, which opens nothing — MEASURED as ENOENT on both Windows
  // cells while both Ubuntu cells passed, because on POSIX the two spellings coincide.
  // `fileURLToPath` is the conversion that exists for exactly this.
  const repoRoot = fileURLToPath(new URL('../../', import.meta.url));
  const doc = JSON.parse(
    readFileSync(join(repoRoot, 'tools', 'shiftwork', 'example-codefix-checkpoint.json'), 'utf8'),
  );
  assert.equal(contract.schemaError(JSON.stringify(doc), js(schema)), null);
  doc.plan.units[0].status = 'finished';
  assert.equal(
    contract.schemaError(JSON.stringify(doc), js(schema)),
    "JSON does not match schema at 'plan/units/0/status': 'finished' is not one of " +
      "['todo', 'in_progress', 'done', 'blocked', 'dropped']",
  );
});

// ------------------------------------------------------------------------ extract_json

test('extract_json: the fence arm strips prose on both sides', () => {
  const schema = js({ type: 'object', required: ['a'] });
  assert.equal(contract.schemaError('here you go:\n```json\n{"a": 1}\n```\nhope that helps', schema), null);
  assert.equal(contract.schemaError('```\n{"a": 1}\n```', schema), null);
});

test('extract_json: the raw_decode arm takes the first brace and ignores the tail', () => {
  const schema = js({ type: 'object', required: ['a'] });
  assert.equal(contract.schemaError('sure! {"a": 1} — anything else?', schema), null);
  assert.equal(contract.schemaError('{"a": 1}{"b": 2}', schema), null);
});

test('extract_json: no JSON at all is a PARSE error, not a validation error', () => {
  assert.equal(
    contract.schemaError('I could not do that.', js({})),
    'output was not parseable JSON: no JSON object found in output',
  );
});

test('extract_json: malformed JSON carries CPython json decoder text verbatim', () => {
  assert.equal(
    contract.schemaError('{"a": ', js({})),
    'output was not parseable JSON: Expecting value: line 1 column 6 (char 5)',
  );
  assert.equal(
    contract.schemaError('{"a" 1}', js({})),
    "output was not parseable JSON: Expecting ':' delimiter: line 1 column 6 (char 5)",
  );
  assert.equal(
    contract.schemaError('{\n  "a": 1,\n}', js({})),
    'output was not parseable JSON: Expecting property name enclosed in double quotes: ' +
      'line 3 column 1 (char 12)',
  );
});

test('extract_json: a Python int is not a JS number', () => {
  // 12345678901234567890 survives raw_decode exactly; JSON.parse rounds it to
  // 12345678901234567000 and the sentence would name a number the model never wrote.
  assert.equal(
    contract.schemaError('{"n": 12345678901234567890}', js({ properties: { n: { type: 'string' } } })),
    "JSON does not match schema at 'n': 12345678901234567890 is not of type 'string'",
  );
});

test('extract_json: CPython accepts NaN and Infinity and repr()s them Python-style', () => {
  assert.equal(
    contract.schemaError('{"n": NaN}', js({ properties: { n: { type: 'string' } } })),
    "JSON does not match schema at 'n': nan is not of type 'string'",
  );
  assert.equal(
    contract.schemaError('{"n": -Infinity}', js({ properties: { n: { type: 'string' } } })),
    "JSON does not match schema at 'n': -inf is not of type 'string'",
  );
});

test('the text is the only record of float-vs-int and of a repeated key', () => {
  // `JSON.stringify` cannot express either, so both are unreachable from a JS literal.
  // 1.0 IS an integer under draft 6+, and a repeated key keeps its FIRST position with its
  // LAST value.
  assert.equal(contract.schemaError('{"v": 1.0}', js({ properties: { v: { type: 'integer' } } })), null);
  assert.equal(
    contract.schemaError('{"v": 1.5}', js({ properties: { v: { type: 'integer' } } })),
    "JSON does not match schema at 'v': 1.5 is not of type 'integer'",
  );
  assert.equal(
    contract.schemaError('{"a": 1, "b": 2, "a": 3}', js({ type: 'string' })),
    'JSON does not match schema at \'root\': ' + "{'a': 3, 'b': 2} is not of type 'string'",
  );
});

test('True is not 1, in enum, in const and in uniqueItems', () => {
  assert.equal(
    contract.schemaError('{"v": true}', js({ properties: { v: { enum: [1] } } })),
    "JSON does not match schema at 'v': True is not one of [1]",
  );
  assert.equal(
    contract.schemaError('{"v": 1}', js({ properties: { v: { const: true } } })),
    "JSON does not match schema at 'v': True was expected",
  );
  assert.equal(contract.schemaError('{"v": [true, 1]}', js({ properties: { v: { uniqueItems: true } } })), null);
  assert.equal(
    contract.schemaError('{"v": [1, 1.0]}', js({ properties: { v: { uniqueItems: true } } })),
    "JSON does not match schema at 'v': [1, 1.0] has non-unique elements",
  );
});

test('the fence arm wins over a brace that appears before it', () => {
  // Without the fence arm the first `{` is the empty object in the prose, and the answer is
  // a correct-looking sentence about a document the model never sent.
  assert.equal(
    contract.schemaError('use {} then\n```json\n{"a": 1}\n```', js({ required: ['a'] })),
    null,
  );
  assert.equal(
    contract.schemaError('use {} then {"a": 1}', js({ required: ['a'] })),
    "JSON does not match schema at 'root': 'a' is a required property",
  );
});

test('a float that happens to be integral still reprs as a float', () => {
  assert.equal(
    contract.schemaError('{"n": 1.0}', js({ properties: { n: { type: 'string' } } })),
    "JSON does not match schema at 'n': 1.0 is not of type 'string'",
  );
});

// ------------------------------------------------------------------- the contract asset

test('load_contract reads every required key out of the shipped default.yaml', () => {
  const data = contract.loadContract();
  for (const key of contract.REQUIRED_KEYS) {
    assert.ok(key in data, `missing ${key}`);
    assert.equal(typeof data[key], 'string');
  }
  assert.equal(data['validation_error'], "JSON does not match schema at '{where}': {detail}");
  assert.equal(data['name'], 'default');
});

test('load_contract names the missing keys the way Python does', () => {
  const dir = process.env.BANTAMKIT_ASSETS;
  try {
    // `realpathSync`: `os.tmpdir()` is not canonical — a `/var` symlink on macOS, the 8.3
    // short name on Windows CI. See the note in test/store.test.mjs.
    const root = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-n5-contract-')));
    mkdirSync(join(root, 'contracts'), { recursive: true });
    writeFileSync(join(root, 'contracts', 'thin.yaml'), 'name: thin\nschema_instruction: "x"\n');
    process.env.BANTAMKIT_ASSETS = root;
    assert.throws(() => contract.loadContract('thin'), (e) => {
      assert.match(e.message, /^contract 'thin' missing key\(s\): schema_retry, critique_feedback, /);
      return true;
    });
    assert.throws(() => contract.loadContract('nope'), /contract asset not found: /);
    rmSync(root, { recursive: true, force: true });
  } finally {
    if (dir === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = dir;
  }
});

test('the contract reader refuses a document outside the language it reads', () => {
  assert.throws(() => contract.parseContractDocument('a: !!python/object:os.system {}\n'), /outside this reader/);
  assert.throws(() => contract.parseContractDocument('a: &x 1\nb: *x\n'), /outside this reader/);
  assert.throws(() => contract.parseContractDocument('a: "unterminated\n'), /outside this reader/);
  assert.throws(() => contract.parseContractDocument('a: |\n  block\n'), /outside this reader/);
  assert.throws(() => contract.parseContractDocument('a:\n  b: 1\n'), /outside this reader/);
});

test('the shipped default.yaml is inside the language, every line of it', () => {
  const text = readFileSync(join(assets.assetsRoot(), 'contracts', 'default.yaml'), 'utf8');
  const parsed = contract.parseContractDocument(text);
  assert.equal(parsed.size, 47); // 45 + `bantamkit_read_page_next` + `bantamkit_read_unknown_part` (job43 R1)
  assert.equal(
    parsed.get('schema_instruction'),
    'Return ONLY a JSON object matching this JSON Schema. No prose.\n',
  );
  assert.ok(parsed.get('document_manifest_part').includes('part {index} "{part}"'));
});

// ------------------------------------------------------- the document reader's sentences

/**
 * The renderers `bantamkit_read` reaches, over primitives, against the bytes `contract.py`
 * prints for the same input. The omission switch is exercised on every subject it names AND
 * on one it does not, because the printed fallback is the whole point of the mechanism.
 */
const part = (over = {}) => ({
  document: 'a.xlsx',
  kind: 'xlsx',
  index: 0,
  part: 'Sales',
  row_count: 3,
  rows: ['name\tqty', 'apple\t3', 'pear\t5'],
  ...over,
});
const omit = (subject, count, over = {}) => ({ subject, count, size: 0, where: [], what: '', facts: {}, ...over });

test('document_manifest prints the count, the numbering and three rows per part', () => {
  assert.equal(contract.documentManifest([]), contract.loadContract()['document_manifest_empty']);
  assert.equal(
    contract.documentManifest([part(), part({ index: 1, part: 'Empty', row_count: 0, rows: [] })]),
    [
      'a.xlsx (xlsx) part 0 "Sales": 3 rows, numbered 0 to 2',
      '  row 0 is the header: name\tqty',
      '  row 1 is the first data row: apple\t3',
      '  row 2 is the last data row: pear\t5',
      'a.xlsx (xlsx) part 1 "Empty": 0 rows, numbered 0 to -1',
    ].join('\n'),
  );
  // One row prints only the header; two print no "last".
  assert.equal(
    contract.documentManifest([part({ row_count: 2, rows: ['h', 'x'] })]).split('\n').length,
    3,
  );
});

test('document_manifest says every omission, including a subject it has no sentence for', () => {
  const data = contract.loadContract();
  const entry = part({
    omissions: [
      omit('media', 2, { size: 4096 }),
      omit('blank-rows', 5),
      omit('number-format', 1, { where: ['B2', 'C3'], what: 'dates' }),
      omit('unmapped-text', 7, { what: 'Symbol' }),
      omit('unread-page', 1, { facts: { show_ops: 0, images: 1, image_bytes: 99 } }),
      omit('unread-page', 1, { facts: { show_ops: 4, unmapped: 2 } }),
      omit('unread-page', 1, { facts: { show_ops: 4, vouched: 3 } }),
      omit('unread-page', 1, { facts: { show_ops: 4 } }),
      omit('from-the-future', 3, { what: 'a subject contract.ts has never heard of' }),
    ],
  });
  const lines = contract.documentManifest([entry]).split('\n');
  assert.equal(lines.length, 4 + 9);
  const sentence = (key, fields) =>
    Object.entries(fields).reduce((s, [k, v]) => s.split(`{${k}}`).join(String(v)), data[key]);
  assert.equal(lines[4], sentence('document_manifest_omitted_media', { count: 2, bytes: 4096 }));
  assert.equal(lines[5], sentence('document_manifest_omitted_blank', { count: 5, rows: 3 }));
  assert.equal(lines[6], sentence('document_manifest_omitted_format', { where: 'B2, C3', count: 1, what: 'dates' }));
  assert.equal(lines[7], sentence('document_manifest_omitted_unmapped', { count: 7, what: 'Symbol' }));
  const unread = (why, count, bytes) => sentence('document_manifest_omitted_unread_page', { why, count, bytes });
  assert.equal(lines[8], unread(data['document_manifest_unread_no_operator'], 1, 99));
  assert.equal(lines[9], unread(sentence('document_manifest_unread_unmapped', { show_ops: 4, unmapped: 2 }), 0, 0));
  assert.equal(lines[10], unread(sentence('document_manifest_unread_whitespace', { show_ops: 4, vouched: 3 }), 0, 0));
  assert.equal(lines[11], unread(sentence('document_manifest_unread_no_character', { show_ops: 4 }), 0, 0));
  assert.equal(lines[12], '  NOT in those rows: 3 from-the-future (a subject contract.ts has never heard of)');
});

test('document_manifest prints a package omission before its parts, and an orphan after them', () => {
  const data = contract.loadContract();
  const media = omit('media', 3, { size: 1234, what: 'png' });
  const lines = contract
    .documentManifest([part()], [{ document: 'a.xlsx', omissions: [media] }, { document: 'b.xlsx', omissions: [media, omit('blank-rows', 1)] }])
    .split('\n');
  const pkg = (document) =>
    ['document', 'count', 'what', 'bytes'].reduce(
      (s, k) => s.split(`{${k}}`).join(String({ document, count: 3, what: 'png', bytes: 1234 }[k])),
      data['document_manifest_package_media'],
    );
  assert.equal(lines[0], pkg('a.xlsx'));
  assert.equal(lines[1], 'a.xlsx (xlsx) part 0 "Sales": 3 rows, numbered 0 to 2');
  assert.equal(lines[5], pkg('b.xlsx'));
  // The orphan's non-media omission is rendered against `row_count: 0`.
  assert.equal(lines[6], data['document_manifest_omitted_blank'].replace('{count}', '1').replace('{rows}', '0'));
  assert.equal(lines.length, 7);
});

test('document_page numbers its rows and spells the continuation as the call to make', () => {
  assert.equal(
    contract.documentPage('n.md', 'document', 0, ['# T', ''], 84, 2),
    'n.md "document" rows 0-1 of 84; each line below begins with its own row number\n0\t# T\n1\t\nmore rows follow: call document_read again with offset=2',
  );
  assert.equal(
    contract.documentPage('n.md', 'document', 0, ['# T', ''], 84, 2, 0, 'bantamkit_read_page_next'),
    'n.md "document" rows 0-1 of 84; each line below begins with its own row number\n0\t# T\n1\t\nmore rows follow: call bantamkit_read again with offset=2',
  );
  assert.equal(
    contract.documentPage('n.md', 'document', 82, ['a', 'b'], 84, null),
    'n.md "document" rows 82-83 of 84; each line below begins with its own row number\n82\ta\n83\tb\nthat was the last row of "document"',
  );
  assert.equal(
    contract.documentPage('w.txt', 'document', 1, ['yyy'], 3, 2, 1928),
    'w.txt "document" rows 1-1 of 3; each line below begins with its own row number\n1\tyyy\nrow 1 was too long for one page and was cut: 1928 bytes dropped\nmore rows follow: call document_read again with offset=2',
  );
  // No rows: `end` is `offset`, as the reference computes it.
  assert.ok(contract.documentPage('n.md', 'document', 5, [], 5, null).startsWith('n.md "document" rows 5-5 of 5;'));
});

test('the refusals and the error keep the reference\'s words, with `$` in a row left alone', () => {
  assert.equal(contract.documentUnknown('x', ['a', 'b']), 'error: no document named x; this task has: a, b');
  assert.equal(
    contract.documentOffsetPastEnd('document', 84, 84),
    'error: offset 84 is past the end of "document", which has 84 rows numbered 0 to 83',
  );
  assert.equal(
    contract.bantamkitReadUnknownPart('Nope', '/tmp/book.xlsx', ['Sales', 'Empty']),
    'error: no part named "Nope" in /tmp/book.xlsx; it has: Sales, Empty',
  );
  assert.equal(contract.documentError(new Error('no such file: /x')), 'error: no such file: /x');
  assert.equal(contract.documentError("cost $' and $1"), "error: cost $' and $1");
  assert.equal(contract.documentPage('d', 'p', 0, ["$'"], 1, null).split('\n')[1], "0\t$'");
});

// -------------------------------------------------------------------- python value repr

test('pyRepr renders JSON values the way Python does', () => {
  const r = (v) => pyjson.reprValue(pyjson.parseJson(v));
  assert.equal(r('null'), 'None');
  assert.equal(r('true'), 'True');
  assert.equal(r('[1, 2.5, "a", null, true, {}]'), "[1, 2.5, 'a', None, True, {}]");
  assert.equal(r('{"a": {"b": [1]}}'), "{'a': {'b': [1]}}");
  assert.equal(r('"it\'s"'), '"it\'s"');
  assert.equal(r('1e16'), '1e+16');
  assert.equal(r('1e15'), '1000000000000000.0');
  assert.equal(r('1e-5'), '1e-05');
  assert.equal(r('0.0001'), '0.0001');
  assert.equal(r('-0.0'), '-0.0');
});

// ------------------------------------------------------------------ the raised divergence

test('an unresolvable construct raises rather than answering plausibly', () => {
  assert.throws(() => contract.schemaError('{}', js({ $ref: '#/$defs/x' })), /jsonschema seam/);
  assert.throws(
    () => contract.schemaError('{}', js({ unevaluatedProperties: false })),
    /jsonschema seam/,
  );
  assert.throws(() => contract.schemaError('{}', js({ type: 'nosuch' })), /jsonschema seam/);
});

test('bestMatch on an empty error list is null, as best_match returns None', () => {
  assert.equal(pyjsonschema.bestMatch([]), null);
});
