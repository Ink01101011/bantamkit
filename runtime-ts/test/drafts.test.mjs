/**
 * The dialects and the one resource (job65, #125 and #126) — the in-runtime half.
 *
 * `tools/conformance/suites/validate.mjs` (`drafts/`, `dialect/`) compares every sentence here
 * against the CPython reference; this file says WHICH ANSWER the port gives without a Python
 * on PATH, so a regression names itself in `npm test`. Three properties:
 *
 *   - #125: a local `$ref` (`#/$defs/…`, `#/definitions/…`, `#anchor`) resolves and
 *     `unevaluatedItems`/`unevaluatedProperties` walk the evaluated keys — both verdicts, the
 *     reference's sentences. A reference OUTSIDE the one resource, an embedded `$id`, a pointer
 *     to nowhere, an unknown anchor: ANSWERED with one sentence (`schemaError` returns it,
 *     `validate` throws `PyJsonSchemaRefusal`), never `isError`.
 *   - #126: `$schema` picks the dialect — `dependencies` fires under draft 7 and is data under
 *     2019-09; draft 4's boolean `exclusiveMaximum` and draft 7's tuple `items` validate instead
 *     of raising; a draft-3 `$schema` is refused by name.
 *   - the `$schema` URI is normalised as `_utils.URIDict` normalises it.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const contract = await import(new URL('contract.js', dist));
const pyjson = await import(new URL('pyjson.js', dist));
const pyjsonschema = await import(new URL('pyjsonschema.js', dist));

const D4 = 'http://json-schema.org/draft-04/schema#';
const D7 = 'http://json-schema.org/draft-07/schema#';
const D2019 = 'https://json-schema.org/draft/2019-09/schema';
const D2020 = 'https://json-schema.org/draft/2020-12/schema';
const D3 = 'http://json-schema.org/draft-03/schema#';

/** `schemaError` over the raw JSON text of the schema, so `1.0` stays a float. */
const answer = (output, schema) => contract.schemaError(output, pyjson.parseJson(JSON.stringify(schema)));
const at = (where, detail) => `JSON does not match schema at '${where}': ${detail}`;

// ------------------------------------------------------------------------- #125, resolved

test('#125: a $ref into #/$defs and #/definitions resolves, both verdicts', () => {
  const defs = { $defs: { x: { type: 'string' } }, properties: { a: { $ref: '#/$defs/x' } } };
  assert.equal(answer('{"a": 1}', defs), at('a', "1 is not of type 'string'"));
  assert.equal(answer('{"a": "s"}', defs), null);
  const definitions = { definitions: { x: { type: 'string' } }, properties: { a: { $ref: '#/definitions/x' } } };
  assert.equal(answer('{"a": 1}', definitions), at('a', "1 is not of type 'string'"));
  assert.equal(answer('{"a": "s"}', definitions), null);
  // The issue's own first row: a root `$ref`, and the document that IS valid against it.
  const root = { $ref: '#/$defs/x', $defs: { x: { type: 'object' } } };
  assert.equal(answer('{"a": 1}', root), null);
  assert.equal(answer('[1]', root), at('root', "[1] is not of type 'object'"));
});

test('#125: the pointer is decoded as referencing decodes it — ~1, ~0, %XX, a list index, -1', () => {
  const schema = {
    $defs: { 'a/b': { type: 'string' }, 'c~d': { type: 'string' } },
    anyOf: [{ type: 'object' }, { type: 'integer' }],
    properties: {
      a: { $ref: '#/$defs/a~1b' },
      b: { $ref: '#/$defs/c~0d' },
      c: { $ref: '#/%24defs/a~1b' },
      d: { $ref: '#/anyOf/1' },
      e: { $ref: '#/anyOf/-1' },
    },
  };
  assert.equal(answer('{"a": "s", "b": "s", "c": "s", "d": 1, "e": 1}', schema), null);
  assert.equal(answer('{"a": 1}', schema), at('a', "1 is not of type 'string'"));
  assert.equal(answer('{"b": 1}', schema), at('b', "1 is not of type 'string'"));
  assert.equal(answer('{"c": 1}', schema), at('c', "1 is not of type 'string'"));
  assert.equal(answer('{"d": "s"}', schema), at('d', "'s' is not of type 'integer'"));
  assert.equal(answer('{"e": "s"}', schema), at('e', "'s' is not of type 'integer'"));
});

test('#125: $anchor, $dynamicRef and $recursiveRef resolve inside the one resource', () => {
  const anchor = { $defs: { x: { $anchor: 'foo', type: 'string' } }, properties: { a: { $ref: '#foo' } } };
  assert.equal(answer('{"a": 1}', anchor), at('a', "1 is not of type 'string'"));
  assert.equal(answer('{"a": "s"}', anchor), null);
  const dyn = { $defs: { x: { $dynamicAnchor: 'foo', type: 'string' } }, properties: { a: { $dynamicRef: '#foo' } } };
  assert.equal(answer('{"a": 1}', dyn), at('a', "1 is not of type 'string'"));
  // `$recursiveRef` is a 2019-09 keyword; under 2020-12 (the default) it is data.
  const rec = { $schema: D2019, type: 'object', properties: { a: { $recursiveRef: '#' } } };
  assert.equal(answer('{"a": 1}', rec), at('a', "1 is not of type 'object'"));
  assert.equal(answer('{"a": {}}', rec), null);
  assert.equal(answer('{"a": 1}', { ...rec, $schema: D2020 }), null);
});

test('#125: unevaluatedProperties and unevaluatedItems, both verdicts, both walkers', () => {
  assert.equal(
    answer('{"a": 1, "b": 2}', { properties: { a: {} }, unevaluatedProperties: false }),
    at('root', "Unevaluated properties are not allowed ('b' was unexpected)"),
  );
  assert.equal(answer('{"a": 1}', { properties: { a: {} }, unevaluatedProperties: false }), null);
  assert.equal(
    answer('{"a": 1, "b": "x"}', { properties: { a: {} }, unevaluatedProperties: { type: 'integer' } }),
    at('root', "Unevaluated properties are not valid under the given schema ('b' was unevaluated and invalid)"),
  );
  // Through a `$ref` — the walker follows the reference, as `find_evaluated_property_keys_by_schema` does.
  const viaRef = { $ref: '#/$defs/x', $defs: { x: { properties: { a: {} } } }, unevaluatedProperties: false };
  assert.equal(answer('{"a": 1, "b": 2}', viaRef), at('root', "Unevaluated properties are not allowed ('b' was unexpected)"));
  assert.equal(answer('{"a": 1}', viaRef), null);
  assert.equal(answer('[1, 2]', { prefixItems: [{}], unevaluatedItems: false }), at('root', 'Unevaluated items are not allowed (2 was unexpected)'));
  assert.equal(answer('[1]', { prefixItems: [{}], unevaluatedItems: false }), null);
  // The 2019-09 walker reads a tuple `items`, which 2020-12 refuses as a schema shape.
  const tuple2019 = { $schema: D2019, items: [{}], unevaluatedItems: false };
  assert.equal(answer('[1, 2]', tuple2019), at('root', 'Unevaluated items are not allowed (2 was unexpected)'));
  assert.equal(answer('[1]', tuple2019), null);
});

// ------------------------------------------------------------------------- #125, refused

/** Each refusal: the sentence `schemaError` ANSWERS, and the class `validate` throws. */
const REFUSALS = [
  [
    'a reference with a host',
    { properties: { a: { $ref: 'https://example.com/x.json' } } },
    'the reference "https://example.com/x.json" cannot be resolved: only references into this schema ("#", "#/..." and "#name") are supported',
  ],
  [
    'a relative reference',
    { properties: { a: { $ref: 'other.json#/x' } } },
    'the reference "other.json#/x" cannot be resolved: only references into this schema ("#", "#/..." and "#name") are supported',
  ],
  [
    'a non-local reference in a branch the instance never reaches is refused EAGERLY',
    { properties: { zz: { $ref: 'https://example.com/x.json' } } },
    'the reference "https://example.com/x.json" cannot be resolved: only references into this schema ("#", "#/..." and "#name") are supported',
  ],
  [
    'an embedded $id beside a reference',
    { $defs: { x: { $id: 'https://example.com/x', type: 'string' } }, properties: { a: { $ref: '#/$defs/x' } } },
    'the schema declares "$id" at $defs/x; references are only resolved in a schema with a single resource',
  ],
  [
    'an embedded id under draft 4',
    { $schema: D4, definitions: { x: { id: 'https://example.com/x', type: 'string' } }, properties: { a: { $ref: '#/definitions/x' } } },
    'the schema declares "id" at definitions/x; references are only resolved in a schema with a single resource',
  ],
  [
    'a pointer to nowhere',
    { properties: { a: { $ref: '#/$defs/nope' } } },
    'the reference "#/$defs/nope" points at nothing in this schema',
  ],
  [
    'an unknown anchor',
    { properties: { a: { $ref: '#nope' } } },
    'the reference "#nope" names no anchor in this schema',
  ],
  [
    'an $anchor under draft 7, where the keyword does not exist',
    { $schema: D7, definitions: { x: { $anchor: 'foo', type: 'string' } }, properties: { a: { $ref: '#foo' } } },
    'the reference "#foo" names no anchor in this schema',
  ],
  [
    'a draft-3 $schema at the root',
    { $schema: D3, type: 'string' },
    `the schema's $schema "${D3}" names draft 3, which this validator does not support (draft-04, draft-06, draft-07, 2019-09 and 2020-12 are)`,
  ],
  [
    'a draft-3 $schema in a subschema',
    { properties: { a: { $schema: D3, type: 'string' } } },
    `the schema's $schema "${D3}" names draft 3, which this validator does not support (draft-04, draft-06, draft-07, 2019-09 and 2020-12 are)`,
  ],
];

test('#125: what the one resource cannot hold is ANSWERED with one sentence, not raised', () => {
  for (const [why, schema, sentence] of REFUSALS) {
    assert.equal(answer('{"a": 1}', schema), sentence, why);
    assert.throws(
      () => pyjsonschema.validate(pyjson.parseJson('{"a": 1}'), pyjson.parseJson(JSON.stringify(schema))),
      (e) => e instanceof pyjsonschema.PyJsonSchemaRefusal && e.message === sentence,
      why,
    );
  }
});

test('#125: the rule is structural — an embedded $id with no reference, a root $id, a property named $ref', () => {
  assert.equal(
    answer('{"a": 1}', { $defs: { x: { $id: 'https://example.com/x' } }, properties: { a: { type: 'string' } } }),
    at('a', "1 is not of type 'string'"),
  );
  const rootId = { $id: 'https://example.com/root', $defs: { x: { type: 'string' } }, properties: { a: { $ref: '#/$defs/x' } } };
  assert.equal(answer('{"a": 1}', rootId), at('a', "1 is not of type 'string'"));
  assert.equal(answer('{"a": "s"}', rootId), null);
  const named = { properties: { $ref: { type: 'string' } } };
  assert.equal(answer('{"$ref": 1}', named), at('$ref', "1 is not of type 'string'"));
  assert.equal(answer('{"$ref": "https://x"}', named), null);
  // A pointer to nowhere in an UNREACHED branch is found lazily — valid, as the reference answers.
  assert.equal(answer('{"a": 1}', { properties: { zz: { $ref: '#/$defs/nope' } } }), null);
});

// ------------------------------------------------------------------------- #126, dispatched

test('#126: $schema picks the dialect — dependencies fires under draft 7 and is data under 2019-09', () => {
  const dep = { dependencies: { a: ['b'] } };
  assert.equal(answer('{"a": 1}', { $schema: D7, ...dep }), at('root', "'b' is a dependency of 'a'"));
  assert.equal(answer('{"a": 1, "b": 2}', { $schema: D7, ...dep }), null);
  assert.equal(answer('{"a": 1}', { $schema: D4, dependencies: { a: { required: ['b'] } } }), at('root', "'b' is a required property"));
  assert.equal(answer('{"a": 1}', { $schema: D2019, ...dep }), null);
  assert.equal(answer('{"a": 1}', dep), null);
  // `dependentRequired` is the other way round.
  assert.equal(answer('{"a": 1}', { $schema: D7, dependentRequired: { a: ['b'] } }), null);
  assert.equal(answer('{"a": 1}', { $schema: D2019, dependentRequired: { a: ['b'] } }), at('root', "'b' is a dependency of 'a'"));
});

test("#126: the issue's other two rows — draft 4's boolean exclusiveMaximum and draft 7's tuple items", () => {
  const d4 = { $schema: D4, properties: { a: { maximum: 1, exclusiveMaximum: true } } };
  assert.equal(answer('{"a": 2}', d4), at('a', '2 is greater than or equal to the maximum of 1'));
  assert.equal(answer('{"a": 1}', d4), at('a', '1 is greater than or equal to the maximum of 1'));
  assert.equal(answer('{"a": 0}', d4), null);
  const tuple = { $schema: D7, properties: { a: { items: [{ type: 'integer' }, { type: 'integer' }] } } };
  assert.equal(answer('{"a": [1, "x"]}', tuple), at('a/1', "'x' is not of type 'integer'"));
  assert.equal(answer('{"a": [1, 2, "x"]}', tuple), null);
  assert.equal(
    answer('{"a": [1, 2]}', { $schema: D7, properties: { a: { items: [{}], additionalItems: false } } }),
    at('a', 'Additional items are not allowed (2 was unexpected)'),
  );
});

test('#126: the dialect reaches the keyword semantics, not only the table', () => {
  // `$ref` silences its siblings through draft 7; from 2019-09 on both apply.
  const sib = { $defs: { x: { type: 'integer' } }, properties: { a: { $ref: '#/$defs/x', type: 'string' } } };
  assert.equal(answer('{"a": 1}', { $schema: D7, ...sib }), null);
  assert.equal(answer('{"a": 1}', { $schema: D2019, ...sib }), at('a', "1 is not of type 'string'"));
  // `1.0` is an integer from draft 6 on and not in draft 4.
  const int = { properties: { a: { type: 'integer' } } };
  assert.equal(answer('{"a": 1.0}', { $schema: D4, ...int }), at('a', "1.0 is not of type 'integer'"));
  assert.equal(answer('{"a": 1.0}', { $schema: D7, ...int }), null);
  // `contains` has no `minContains` before 2019-09, and a different sentence.
  assert.equal(answer('["a"]', { $schema: D7, contains: { type: 'integer' } }), at('root', "None of ['a'] are valid under the given schema"));
  assert.equal(answer('["a"]', { contains: { type: 'integer' } }), at('root', "['a'] does not contain items matching the given schema"));
  // A SUBSCHEMA re-dispatches on its own `$schema`, as `Validator.evolve` does.
  const nested = { $schema: D2020, properties: { a: { $schema: D7, dependencies: { b: ['c'] } } } };
  assert.equal(answer('{"a": {"b": 1}}', nested), at('a', "'c' is a dependency of 'b'"));
});

test('#126: a keyword the dialect does not know is DATA to its metaschema, and a shape it does know is checked', () => {
  assert.equal(answer('{"a": 1}', { $schema: D4, properties: { a: { if: 3 } } }), null);
  assert.throws(() => answer('{"a": 1}', { $schema: D7, properties: { a: { if: 3 } } }), /jsonschema seam/);
  assert.throws(() => answer('{"a": 1}', { $schema: D4, properties: { a: { exclusiveMaximum: 1 } } }), /must be a boolean/);
  assert.throws(() => answer('{"a": 1}', { $schema: D7, properties: { a: { exclusiveMaximum: true } } }), /must be a number/);
  assert.throws(() => answer('[1]', { $schema: D2020, items: [{}] }), /must be an object or a boolean/);
  assert.throws(() => answer('{"a": 1}', { $schema: 3 }), /\$schema must be a string/);
});

// --------------------------------------------------------------------------- the URI

test('the $schema URI is normalised as _utils.URIDict normalises it', () => {
  const n = pyjsonschema.pyUrlNormalize;
  assert.equal(n('http://json-schema.org/draft-07/schema#'), 'http://json-schema.org/draft-07/schema');
  assert.equal(n('HTTP://json-schema.org/draft-07/schema'), 'http://json-schema.org/draft-07/schema');
  assert.equal(n('http://json-schema.org/draft-07/schema?'), 'http://json-schema.org/draft-07/schema');
  assert.equal(n('  http://json-schema.org/draft-07/schema#'), 'http://json-schema.org/draft-07/schema');
  assert.equal(n('http://json-schema.org/draft-07/schema#frag'), 'http://json-schema.org/draft-07/schema#frag');
  assert.equal(n('http://json-schema.org/draft-07/schema/'), 'http://json-schema.org/draft-07/schema/');
  assert.equal(n('https://JSON-schema.org/draft/2020-12/schema'), 'https://JSON-schema.org/draft/2020-12/schema');
  const dep = { dependencies: { a: ['b'] } };
  const fires = at('root', "'b' is a dependency of 'a'");
  // One key: with and without the empty fragment, upper-case scheme, leading space.
  for (const uri of [D7, 'http://json-schema.org/draft-07/schema', 'HTTP://json-schema.org/draft-07/schema#', '  http://json-schema.org/draft-07/schema#']) {
    assert.equal(answer('{"a": 1}', { $schema: uri, ...dep }), fires, uri);
  }
  // Not a key: the reference warns and falls back to the latest draft, where `dependencies` is data.
  for (const uri of ['https://json-schema.org/draft-07/schema#', 'http://json-schema.org/draft-07/schema/', 'http://json-schema.org/draft-07/schema#frag', 'https://example.com/not-a-draft', '']) {
    assert.equal(answer('{"a": 1}', { $schema: uri, ...dep }), null, uri);
  }
});
