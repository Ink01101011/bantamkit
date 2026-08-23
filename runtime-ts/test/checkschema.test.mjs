/**
 * `check_schema` — the caller schema that is not a schema, and the two decoders that were
 * one question with two answers.
 *
 * WHY THIS FILE EXISTS. `jsonschema.validate` runs `cls.check_schema(schema)` BEFORE it
 * looks at the instance. This port did not, and the consequence was not a different sentence
 * but a WRONG ANSWER: the keywords in `pyjsonschema.ts` are written to SKIP a schema value
 * they do not recognise, which is correct inside `iter_errors` and is `{"valid": true}` at a
 * tool boundary. N8 measured five on the wire; the fix is `checkSchema`, and 53 shapes are
 * compared against the reference in `tools/conformance/suites/validate.mjs`. This file is
 * the in-runtime half — it says WHICH ANSWER changed, without a Python on PATH.
 *
 * The UTF-8 BOM cases are here for the same reason one directory over: `pyDecodeUtf8`'s own
 * validator accepted `EF BB BF` as three ordinary bytes while the `TextDecoder` behind it
 * silently dropped them, so the module checked one string and returned another.
 */
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const contract = await import(new URL('contract.js', dist));
const pyjson = await import(new URL('pyjson.js', dist));
const pyjsonschema = await import(new URL('pyjsonschema.js', dist));
const pyfs = await import(new URL('memory/pyfs.js', dist));
const assets = await import(new URL('assets.js', dist));

/** The five N8 measured on the wire, each with the answer this port used to give. */
const N8_FIVE = [
  ['{"required": "a"}', '{"valid": true}'],
  ['{"required": 3}', '{"valid": true}'],
  ['{"properties": ["a"]}', '{"valid": true}'],
  ['{"additionalProperties": [1]}', '{"valid": true}'],
  ['{"type": 3}', '{"valid": false, "feedback": "… is not of type 3"}'],
];

test('the five N8 measured now REFUSE instead of answering', () => {
  for (const [schema, was] of N8_FIVE) {
    assert.throws(
      () => contract.schemaError('{"a": 1}', pyjson.parseJson(schema)),
      (e) => e instanceof pyjsonschema.PyJsonSchemaUnsupported,
      `${schema} used to answer ${was}`,
    );
  }
});

test('the shape table, one refusal per keyword family', () => {
  const bad = [
    '{"required": [3]}',
    '{"required": ["a", "a"]}',
    '{"properties": {"a": 3}}',
    '{"additionalProperties": 1}',
    '{"type": "nosuch"}',
    '{"type": ["string", 3]}',
    '{"type": ["string", "string"]}',
    '{"type": []}',
    '{"enum": "a"}',
    '{"multipleOf": "a"}',
    '{"multipleOf": 0}',
    '{"multipleOf": -1}',
    '{"minimum": "a"}',
    '{"maxLength": "a"}',
    '{"maxLength": -1}',
    '{"maxLength": 1.5}',
    '{"uniqueItems": "yes"}',
    '{"pattern": 3}',
    '{"pattern": "("}',
    '{"format": 3}',
    '{"allOf": {"a": 1}}',
    '{"allOf": []}',
    '{"allOf": [3]}',
    '{"anyOf": {}}',
    '{"oneOf": "x"}',
    '{"prefixItems": {}}',
    '{"items": 3}',
    '{"contains": 3}',
    '{"not": 3}',
    '{"if": 3}',
    '{"propertyNames": 3}',
    '{"patternProperties": []}',
    '{"patternProperties": {"^a": 3}}',
    '{"dependentRequired": "a"}',
    '{"dependentRequired": {"a": "b"}}',
    '{"dependentSchemas": []}',
    '{"dependentSchemas": {"a": 3}}',
    '{"minContains": "a"}',
    '[1]',
    '3',
    '"x"',
    // Recursive, and the last one is the loudest: `$defs` is never descended into by any
    // keyword this port implements, and the reference refuses it all the same.
    '{"properties": {"a": {"required": "b"}}}',
    '{"items": {"type": 3}}',
    '{"anyOf": [{"properties": {"a": {"maxLength": "x"}}}]}',
    '{"$defs": {"x": {"type": 3}}}',
  ];
  for (const schema of bad) {
    assert.throws(
      () => contract.schemaError('{"a": 1}', pyjson.parseJson(schema)),
      (e) => e instanceof pyjsonschema.PyJsonSchemaUnsupported,
      schema,
    );
  }
});

test('a schema that IS a schema still answers, and the answer is unchanged', () => {
  // The shapes next door to a refusal, so the check cannot be passing by refusing everything.
  assert.equal(contract.schemaError('{"a": 1}', pyjson.parseJson('{"required": ["a"]}')), null);
  assert.equal(contract.schemaError('{"a": 1}', pyjson.parseJson('{"type": ["object", "array"]}')), null);
  assert.equal(contract.schemaError('{"a": 1}', pyjson.parseJson('{"enum": []}')) !== null, true);
  assert.equal(contract.schemaError('{"a": 1}', pyjson.parseJson('{"maxLength": 2.0}')), null);
  assert.equal(contract.schemaError('{"a": 1}', pyjson.parseJson('{"multipleOf": 0.5}')), null);
  assert.equal(contract.schemaError('{"a": 1}', pyjson.parseJson('{"additionalProperties": false}')) !== null, true);
  assert.equal(
    contract.schemaError('{"a": "x"}', pyjson.parseJson('{"properties": {"a": {"type": "integer"}}}')),
    "JSON does not match schema at 'a': 'x' is not of type 'integer'",
  );
  // Every tool asset ships its own parameter block through this path on every call.
  for (const tool of ['memory_save', 'memory_recall', 'shiftwork_clock_out', 'validate_json']) {
    const parameters = assets.loadToolAsset(tool)['parameters'];
    assert.doesNotThrow(() => pyjsonschema.checkSchema(pyjson.fromJs(parameters)));
  }
});

test('pyDecodeUtf8 KEEPS a BOM, because bytes.decode("utf-8") does', () => {
  const dec = (bytes) => pyfs.pyDecodeUtf8(Uint8Array.from(bytes));
  assert.equal(dec([0xef, 0xbb, 0xbf]), '﻿');
  assert.equal(dec([0xef, 0xbb, 0xbf, 0x61]), '﻿a');
  assert.equal(dec([0xef, 0xbb, 0xbf, 0xef, 0xbb, 0xbf]), '﻿﻿');
  assert.equal(dec([0x61, 0xef, 0xbb, 0xbf]), 'a﻿');
});

test('json.loads refuses a BOM and raw_decode does not — the check lives in loads', () => {
  assert.throws(
    () => pyjson.parseJson('﻿{"a": 1}'),
    (e) => String(e.message) === 'Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0)',
  );
  // `contract.extract_json` goes through `raw_decode`, which has no BOM test at all: it just
  // fails to find a value there.
  assert.throws(
    () => pyjson.rawDecode('﻿{"a": 1}'),
    (e) => String(e.message) === 'Expecting value: line 1 column 1 (char 0)',
  );
});

test('OSError and the symlink-loop RuntimeError print the path with %r', () => {
  const err = (filename, filename2 = null) =>
    new pyfs.PyOSError(2, 'ENOENT', 'No such file or directory', filename, filename2).message;
  assert.equal(err('/a/plain.md'), "[Errno 2] No such file or directory: '/a/plain.md'");
  // An apostrophe flips the quote, exactly as `repr` does; the old spelling emitted
  // `: '/a/it's.md'`, which is not a string CPython ever prints.
  assert.equal(err("/a/it's.md"), `[Errno 2] No such file or directory: "/a/it's.md"`);
  assert.equal(err('/a/two\nlines.md'), "[Errno 2] No such file or directory: '/a/two\\nlines.md'");
  assert.equal(err('/a/tab\there.md'), "[Errno 2] No such file or directory: '/a/tab\\there.md'");
  assert.equal(
    err("/a/x'.md", '/b/y\n.md'),
    `[Errno 2] No such file or directory: "/a/x'.md" -> '/b/y\\n.md'`,
  );
});

test("pathlib's symlink-loop RuntimeError uses %r too", () => {
  // `realpathSync`: `os.tmpdir()` is not canonical — a `/var` symlink on macOS, the 8.3
  // short name on Windows CI. See the note in test/store.test.mjs.
  const bed = realpathSync(mkdtempSync(join(tmpdir(), 'bk-loop-')));
  try {
    const link = join(bed, "loop's-link");
    symlinkSync(link, link);
    // The path in the message is the RESOLVED one (`/var` is a symlink to `/private/var`
    // here), so what is pinned is the quoting: `%r` picks `"` because the name holds a `'`.
    assert.throws(
      () => pyfs.pyResolve(link),
      (e) => /^Symlink loop from "\/.*\/loop's-link"$/.test(e.message),
    );
  } finally {
    rmSync(bed, { recursive: true, force: true });
  }
});

test('an asset that is not UTF-8 raises CPython\'s decode message, not U+FFFD', () => {
  // `assets.ts` used to carry its OWN decoder — `readFileSync(p, "utf8")`, which substitutes
  // U+FFFD for a bad byte and hands a model a description with a replacement character in
  // it. `Path.read_text(encoding="utf-8")` raises. One decoder for the package means this
  // arm inherits `pyDecodeUtf8`'s strictness along with its BOM handling.
  const bed = realpathSync(mkdtempSync(join(tmpdir(), 'bk-assets-')));
  const saved = process.env.BANTAMKIT_ASSETS;
  try {
    mkdirSync(join(bed, 'skills'), { recursive: true });
    writeFileSync(join(bed, 'skills', 'broken.md'), Buffer.from([0x61, 0xff, 0x62]));
    writeFileSync(join(bed, 'skills', 'bommed.md'), Buffer.from([0xef, 0xbb, 0xbf, 0x61]));
    process.env.BANTAMKIT_ASSETS = bed;
    assert.throws(
      () => assets.loadSkill('broken'),
      (e) =>
        e.name === 'UnicodeDecodeError' &&
        e.message === "'utf-8' codec can't decode byte 0xff in position 1: invalid start byte",
    );
    // …and the BOM is content, here as everywhere else.
    assert.equal(assets.loadSkill('bommed'), '\ufeffa');
  } finally {
    if (saved === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = saved;
    rmSync(bed, { recursive: true, force: true });
  }
});
