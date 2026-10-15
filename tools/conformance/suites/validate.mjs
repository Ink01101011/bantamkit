/**
 * validate — the validator, Python against Node, sentence by sentence.
 *
 * THE PROPERTY: for every validation failure bantamkit can produce, Node emits the
 * BYTE-IDENTICAL string Python emits. Both libraries agree on WHETHER a document is valid;
 * they disagree on what they say about it, and what they say is what reaches the model's
 * retry turn and the checkpoint's refusal reason.
 *
 * WHAT IS COMPARED
 *   1. `schema_error(output, schema)` over a corpus built here — one case per error class,
 *      each of those at four depths, a battery of documents with SEVERAL errors (where
 *      `best_match`'s choice is the whole answer), and the REAL checkpoint schema against
 *      mutations of two real checkpoints.
 *   2. `raw_decode` over a systematically damaged corpus: every truncation and a sweep of
 *      single-character mutations of eight valid documents. This is the CPython decoder's
 *      own error text, which `parse_error_message` quotes verbatim, offsets included.
 *   3. `extract_json`'s two arms — fenced and bare — including prose on both sides.
 *   4. `repr(float)`, because every numeric sentence interpolates it and Python and JS
 *      disagree about when to use scientific notation and how wide an exponent is.
 *   5. `load_contract` against `yaml.safe_load` of the SHIPPED `assets/contracts/default.yaml`,
 *      key for key. That is the gate on reading a YAML file with no YAML engine.
 *
 * The schemas travel as raw JSON TEXT and each side runs its own decoder over the same
 * bytes. Handing over a parsed object would erase the int/float distinction that
 * `{instance!r}` prints, which is one of the things under test.
 */
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'validate';
export const summary = 'the validator: every sentence a schema failure can produce';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'validate_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

/** One Python answer, rendered as the one string a comparison can point at. */
/**
 * The NODE side, rendered exactly as `answer` renders Python's.
 *
 * N8 found two ruled cases comparing `answer(null)` -> `'(valid)'` against `String(null)` ->
 * `'null'`: both runtimes agreed the document was VALID and the case "differed" only because
 * the two sides went through different stringifiers. A ruling whose case can never stop
 * differing documents nothing. Every ruled case below renders both sides through the same
 * two functions, so making the port match really does turn the case red.
 */
const nodeAnswer = (value) => (value === null ? '(valid)' : String(value));

const answer = (value) => {
  if (value === null) return '(valid)';
  if (typeof value === 'string') return unb64(value);
  if (value && value.error) return `${value.error.type}: ${unb64(value.error.message)}`;
  return JSON.stringify(value);
};

// --------------------------------------------------------------------------- the corpus

/** One (schema, instance) pair per error class, then the same class at four depths. */
const CLASSES = [
  ['type-string', { type: 'string' }, 5],
  ['type-integer', { type: 'integer' }, 'x'],
  ['type-number', { type: 'number' }, 'x'],
  ['type-boolean', { type: 'boolean' }, 1],
  ['type-array', { type: 'array' }, {}],
  ['type-object', { type: 'object' }, []],
  ['type-null', { type: 'null' }, 0],
  ['type-union', { type: ['string', 'integer'] }, []],
  ['type-int-vs-float', { type: 'integer' }, 1.5],
  ['type-bool-is-not-number', { type: 'number' }, true],
  ['type-float-int-is-integer', { type: 'string' }, 1.0],
  ['required-1', { required: ['a'] }, {}],
  ['required-2', { required: ['a', 'b'] }, { b: 1 }],
  ['required-quote', { required: ["it's"] }, {}],
  ['required-unicode', { required: ['ชื่อ'] }, {}],
  ['addprops-1', { additionalProperties: false, properties: { a: {} } }, { a: 1, b: 2 }],
  ['addprops-2', { additionalProperties: false, properties: { a: {} } }, { b: 2, c: 3 }],
  ['addprops-3', { additionalProperties: false, properties: { a: {} } }, { d: 4, c: 3, b: 2 }],
  ['addprops-schema', { additionalProperties: { type: 'string' }, properties: { a: {} } }, { a: 1, b: 2 }],
  ['addprops-patterns', { additionalProperties: false, patternProperties: { '^a': {} } }, { zz: 1 }],
  ['enum-str', { enum: ['todo', 'done'] }, 'nope'],
  ['enum-mixed', { enum: [1, 'a', null, true] }, 'b'],
  ['enum-empty', { enum: [] }, 'b'],
  ['const-int', { const: 1 }, 2],
  ['const-str', { const: 'x' }, 'y'],
  ['const-obj', { const: { a: 1 } }, { a: 2 }],
  ['const-true-is-not-1', { const: true }, 1],
  ['minLength-1', { minLength: 1 }, ''],
  ['minLength-3', { minLength: 3 }, 'ab'],
  ['minLength-astral', { minLength: 3 }, '😀😀'],
  ['maxLength-0', { maxLength: 0 }, 'a'],
  ['maxLength-2', { maxLength: 2 }, 'abc'],
  ['maxItems-0', { maxItems: 0 }, [1]],
  ['maxItems-5', { maxItems: 5 }, [1, 2, 3, 4, 5, 6]],
  ['minItems-1', { minItems: 1 }, []],
  ['minItems-2', { minItems: 2 }, [1]],
  ['minimum', { minimum: 1 }, 0],
  ['minimum-float', { minimum: 1.5 }, 1],
  ['maximum', { maximum: 5 }, 6],
  ['exclusiveMinimum', { exclusiveMinimum: 1 }, 1],
  ['exclusiveMaximum', { exclusiveMaximum: 1 }, 1],
  ['multipleOf-int', { multipleOf: 2 }, 3],
  ['multipleOf-float', { multipleOf: 0.5 }, 0.3],
  ['pattern', { pattern: '^[a-z]+$' }, 'A1'],
  ['uniqueItems', { uniqueItems: true }, [1, 1]],
  ['uniqueItems-deep', { uniqueItems: true }, [{ a: [1] }, { a: [1] }]],
  ['uniqueItems-bool-int', { uniqueItems: true }, [true, 1]],
  ['minProperties-1', { minProperties: 1 }, {}],
  ['minProperties-2', { minProperties: 2 }, { a: 1 }],
  ['maxProperties-0', { maxProperties: 0 }, { a: 1 }],
  ['maxProperties-1', { maxProperties: 1 }, { a: 1, b: 2 }],
  ['false-schema', false, 1],
  ['true-schema', true, 1],
  ['anyOf', { anyOf: [{ type: 'string' }, { type: 'integer' }] }, []],
  ['anyOf-deep-child', { anyOf: [{ type: 'string' }, { properties: { q: { type: 'integer' } } }] }, { q: 'x' }],
  ['oneOf-none', { oneOf: [{ type: 'string' }, { type: 'integer' }] }, []],
  ['oneOf-many', { oneOf: [{ type: 'integer' }, { minimum: 0 }] }, 1],
  ['allOf', { allOf: [{ type: 'integer' }, { minimum: 5 }] }, 1],
  ['not', { not: { type: 'integer' } }, 1],
  ['contains-none', { contains: { type: 'integer' } }, ['a']],
  ['contains-too-few', { contains: { type: 'integer' }, minContains: 2 }, [1, 'a']],
  ['contains-too-many', { contains: { type: 'integer' }, maxContains: 1 }, [1, 2]],
  ['propertyNames', { propertyNames: { maxLength: 1 } }, { ab: 1 }],
  ['dependentRequired', { dependentRequired: { a: ['b'] } }, { a: 1 }],
  ['dependentSchemas', { dependentSchemas: { a: { required: ['b'] } } }, { a: 1 }],
  ['prefixItems', { prefixItems: [{ type: 'integer' }] }, ['x']],
  ['prefixItems-and-items', { prefixItems: [{ type: 'integer' }], items: false }, [1, 2]],
  ['prefixItems-and-items-1', { prefixItems: [{}], items: false }, [1, 2, 3]],
  ['items-false', { items: false }, [1]],
  ['patternProperties', { patternProperties: { '^a': { type: 'integer' } } }, { ab: 'x' }],
  ['items-schema', { items: { type: 'integer' } }, [1, 'x', 3]],
  ['if-then', { if: { type: 'integer' }, then: { minimum: 5 } }, 1],
  ['if-else', { if: { type: 'integer' }, else: { minLength: 5 } }, 'ab'],
  ['format-is-a-noop', { format: 'email' }, 'not-an-email'],
];

/** Documents with SEVERAL errors — the only place `best_match`'s choice is observable. */
const MULTI = [
  ['two-siblings', { properties: { a: { type: 'integer' }, b: { type: 'integer' } } }, { a: 'x', b: 'y' }],
  ['three-siblings', { properties: { a: { type: 'integer' }, b: { type: 'integer' }, c: { type: 'integer' } } },
    { a: 'x', b: 'y', c: 'z' }],
  ['reverse-declared-order', { properties: { b: { type: 'integer' }, a: { type: 'integer' } } }, { b: 'x', a: 'y' }],
  ['root-vs-deep', { required: ['z'], properties: { a: { properties: { b: { type: 'integer' } } } } },
    { a: { b: 'x' } }],
  ['deep-vs-root', { properties: { a: { required: ['q'] } }, required: ['a'] }, { a: {} }],
  ['array-two', { items: { type: 'integer' } }, ['x', 'y']],
  ['array-second-only', { items: { type: 'integer' } }, [1, 'y']],
  ['array-vs-object', { properties: { a: { items: { type: 'integer' } }, b: { type: 'string' } } },
    { a: ['x'], b: 1 }],
  ['weak-vs-strong', { anyOf: [{ type: 'string' }], type: 'object' }, 5],
  ['strong-then-weak', { type: 'object', anyOf: [{ type: 'string' }] }, 5],
  ['anyOf-context-tie', { anyOf: [{ type: 'string' }, { type: 'boolean' }] }, 1],
  ['anyOf-context-no-tie', { anyOf: [{ type: 'string' }, { properties: { q: { type: 'integer' } } }] }, { q: 'x' }],
  ['anyOf-context-three', { anyOf: [{ type: 'string' }, { minimum: 3 }, { maxLength: 1 }] }, 1],
  ['oneOf-context', { properties: { a: { oneOf: [{ type: 'string' }, { type: 'boolean' }] } } }, { a: 1 }],
  ['nested-anyOf', { anyOf: [{ anyOf: [{ type: 'string' }] }, { type: 'boolean' }] }, 1],
  ['mixed-keywords', { type: 'object', required: ['x'], additionalProperties: false, properties: { y: { type: 'integer' } } },
    { y: 's', z: 1 }],
  ['required-and-type', { type: 'object', required: ['a'], properties: { b: { type: 'integer' } } }, { b: 'x' }],
  ['three-levels', { properties: { a: { properties: { b: { properties: { c: { type: 'integer' } } } } } }, required: ['zz'] },
    { a: { b: { c: 'x' } } }],
  ['matches-type-tiebreak', { properties: { a: { type: 'object', minProperties: 2 } } }, { a: { q: 1 } }],
  ['same-path-two-keywords', { properties: { a: { type: 'string', minimum: 3 } } }, { a: 1 }],
  ['array-index-order', { items: { properties: { k: { type: 'integer' } } } }, [{ k: 'a' }, { k: 'b' }]],
  // Two errors at one path, both non-weak: the tie falls to relevance's last slot,
  // `not _matches_type()`. The `type` error's subschema does NOT describe the instance and
  // the `minimum` error's does, so the `type` error wins.
  ['matches-type-allOf', { properties: { v: { allOf: [{ type: 'string' }, { type: 'integer', minimum: 5 }] } } },
    { v: 1 }],
  ['matches-type-allOf-flipped', { properties: { v: { allOf: [{ type: 'integer', minimum: 5 }, { type: 'string' }] } } },
    { v: 1 }],
];

/**
 * Cases whose OUTPUT TEXT cannot survive `JSON.stringify`, so they are written as bytes.
 *
 * `JSON.stringify(1.0)` is `"1"` and a duplicate key cannot be expressed by an object
 * literal at all, so the two Python-isms that only exist in the TEXT — float-vs-int and
 * dict insertion order under a repeated key — are unreachable from the corpus above.
 */
const RAW = [
  ['float-integer-is-integer', { properties: { v: { type: 'integer' } } }, '{"v": 1.0}'],
  ['float-nonintegral-is-not', { properties: { v: { type: 'integer' } } }, '{"v": 1.5}'],
  ['float-reprs-as-float', { properties: { v: { type: 'string' } } }, '{"v": 1.0}'],
  ['float-in-a-bound', { properties: { v: { minimum: 1.0 } } }, '{"v": 0}'],
  ['float-exponent', { properties: { v: { type: 'string' } } }, '{"v": 1e16}'],
  ['float-small', { properties: { v: { type: 'string' } } }, '{"v": 1e-5}'],
  ['bigint-exact', { properties: { v: { type: 'string' } } }, '{"v": 12345678901234567890}'],
  ['bigint-bound', { properties: { v: { minimum: 99999999999999999999 } } }, '{"v": 1}'],
  ['nan-reprs', { properties: { v: { type: 'string' } } }, '{"v": NaN}'],
  ['inf-reprs', { properties: { v: { type: 'string' } } }, '{"v": -Infinity}'],
  ['dup-key-keeps-first-position', { type: 'string' }, '{"a": 1, "b": 2, "a": 3}'],
  ['dup-key-three', { type: 'string' }, '{"z": 0, "a": 1, "z": 9, "m": 2}'],
  ['enum-true-is-not-1', { properties: { v: { enum: [1] } } }, '{"v": true}'],
  ['enum-1-is-not-true', { properties: { v: { enum: [true] } } }, '{"v": 1}'],
  ['const-true-vs-1', { properties: { v: { const: true } } }, '{"v": 1}'],
  ['const-1-vs-true', { properties: { v: { const: 1 } } }, '{"v": true}'],
  ['unique-true-and-1', { properties: { v: { uniqueItems: true } } }, '{"v": [true, 1]}'],
  ['unique-1-and-1.0', { properties: { v: { uniqueItems: true } } }, '{"v": [1, 1.0]}'],
  ['unique-0-and-false', { properties: { v: { uniqueItems: true } } }, '{"v": [0, false]}'],
  ['multipleOf-float-schema', { properties: { v: { multipleOf: 0.5 } } }, '{"v": 0.3}'],
];

/** Mutations of a real checkpoint, validated against the REAL shipped schema. */
const MUTATIONS = {
  'version-const': (d) => { d.version = 2; },
  'version-type': (d) => { d.version = '1'; },
  'drop-job': (d) => { delete d.job; },
  'drop-handoff': (d) => { delete d.handoff; },
  'extra-root': (d) => { d.notes = 'hi'; },
  'two-extra-root': (d) => { d.notes = 'hi'; d.owner = 'me'; },
  'job-id-empty': (d) => { d.job.id = ''; },
  'job-goal-type': (d) => { d.job.goal = 5; },
  'job-extra': (d) => { d.job.owner = 'me'; },
  'constraint-empty': (d) => { d.job.constraints.push(''); },
  'constraint-type': (d) => { d.job.constraints.push(3); },
  'cursor-empty': (d) => { d.plan.cursor = ''; },
  'unit-status-enum': (d) => { d.plan.units[0].status = 'finished'; },
  'unit-role-enum': (d) => { d.plan.units[0].role = 'worker'; },
  'unit-drop-verify': (d) => { delete d.plan.units[0].verify; },
  'unit-extra': (d) => { d.plan.units[0].model = 'opus'; },
  'unit-title-empty': (d) => { d.plan.units[0].title = ''; },
  'unit-2-status': (d) => { d.plan.units[1].status = 'nope'; },
  'two-units-bad': (d) => { d.plan.units[0].status = 'nope'; d.plan.units[1].role = 'nope'; },
  'history-overflow': (d) => { d.history = [...d.history, ...Array(9).fill({ unit: 'x', outcome: 'y' })].slice(0, 9); },
  'history-item-drop': (d) => { if (d.history[0]) delete d.history[0].outcome; },
  'repo-dirty-type': (d) => { d.state.repo.dirty = 'no'; },
  'repo-drop-branch': (d) => { delete d.state.repo.branch; },
  'external-kind': (d) => { d.state.external.push({ kind: 'email', ref: 'r', status: 's' }); },
  'artifact-extra': (d) => { if (d.state.artifacts[0]) d.state.artifacts[0].why = 'z'; },
  'handoff-next-empty': (d) => { d.handoff.next_action = ''; },
  'handoff-dropq': (d) => { delete d.handoff.open_questions; },
  'donot-type': (d) => { d.handoff.do_not.push(7); },
  'plan-units-type': (d) => { d.plan.units = {}; },
  // `job.roles`, the optional v1 addition of job46/AS-2. It is the FIRST use of
  // `propertyNames` anywhere in this schema, so these are the only cases that carry that
  // keyword from the reference through the port at all — everything else in the checkpoint
  // closes an object with `additionalProperties: false`, which `roles` cannot use because it
  // is a map keyed by role rather than a record read by fixed field name.
  'job-roles-valid': (d) => { d.job.roles = { implementer: ['claude-opus-5', 'claude-sonnet-5'], reviewer: ['claude-opus-5'] }; },
  'job-roles-empty-map': (d) => { d.job.roles = {}; },
  'job-roles-bad-key': (d) => { d.job.roles = { auditor: ['claude-opus-5'] }; },
  'job-roles-empty-list': (d) => { d.job.roles = { implementer: [] }; },
  'job-roles-string-value': (d) => { d.job.roles = { implementer: 'claude-opus-5' }; },
  'job-roles-empty-name': (d) => { d.job.roles = { reviewer: [''] }; },
  'job-roles-not-object': (d) => { d.job.roles = ['implementer']; },
  // `handoff.notes`, the optional v1 addition of job50/F8. The example checkpoint already
  // carries one, so `real/example/valid` exercises the accept path; these four overwrite
  // it, empty it, mis-type it, and stand a one-letter typo beside it.
  'handoff-notes-valid': (d) => { d.handoff.notes = 'gate baseline — 3989 cases, 0 failures'; },
  'handoff-notes-empty': (d) => { d.handoff.notes = ''; },
  'handoff-notes-type': (d) => { d.handoff.notes = 5; },
  'handoff-extra-key': (d) => { d.handoff.note = 'typo'; },
  'everything': (d) => {
    d.version = 9;
    d.job.id = '';
    d.plan.units[0].status = 'x';
    d.handoff.next_action = '';
  },
};

/** Eight valid documents, damaged systematically — the decoder's own message is the answer. */
const DECODER_SEEDS = [
  '{"a": 1}',
  '{"a": [1, 2], "b": {"c": null}}',
  '[1, 2.5, true, false, null, "x"]',
  '{"a": "b\\nc", "d": "\\u00e9"}',
  '{ "a" : 1 , "b" : 2 }',
  '{"😀": "🎉"}',
  '[[[1]]]',
  '{"n": -1.5e-3}',
];
const MUTANT_CHARS = ['', ' ', ',', ':', '"', '{', '}', '[', ']', '\\', '\n', '\t', '0', 'x', "'", ''];

function decoderCorpus() {
  const texts = new Set();
  for (const seed of DECODER_SEEDS) {
    // By CODEPOINT, not by UTF-16 unit: slicing an astral character in half would put a lone
    // surrogate in the corpus, and the base64 transport between the two sides would replace
    // it with U+FFFD on one side only — a harness artifact masquerading as a port defect.
    const chars = [...seed];
    for (let cut = 0; cut <= chars.length; cut += 1) texts.add(chars.slice(0, cut).join(''));
    for (let at = 0; at < chars.length; at += 1) {
      for (const ch of MUTANT_CHARS) {
        texts.add(chars.slice(0, at).join('') + ch + chars.slice(at + 1).join(''));
      }
    }
  }
  for (const t of [
    '', '   ', 'no json', 'NaN', 'Infinity', '-Infinity', '01', '1.', '.5', '+1', '--1',
    'tru', 'nul', '"abc', '"a\\q"', '"a\\u12"', '"a\\uZZZZ"', '"\\ud800"', '"\\ud800\\udc00"',
    '"\\ud800A"', '﻿{}', '{}{}', '{"a":1}garbage', '[1] [2]', '{"a": 1}\n{"b": 2}',
    '12345678901234567890', '{"n": 12345678901234567890}', '{"n": 1.0}', '{"n": -0.0}',
    '{"a": 1, "a": 2}', '{"a":undefined}', '{"a":01}', '{"a":1 "b":2}', '[,]', '[1,2,]',
    '{"a": 1}', '{"😀":1,}', '[1,😀]', '"😀x', '{"a": "\\ud83d\\ude00"}',
  ]) {
    texts.add(t);
  }
  return [...texts];
}

/** `extract_json`'s own arms: fences, prose, and the no-JSON refusal. */
const EXTRACT_TEXTS = [
  '{"a": 1}',
  '  {"a": 1}  ',
  'here you go:\n```json\n{"a": 1}\n```\nhope that helps',
  '```\n{"a": 1}\n```',
  '```json{"a":1}```',
  '```json\n{"a": 1}\n```\n```json\n{"b": 2}\n```',
  'prose ``` {"a": 1} ``` more',
  // A brace BEFORE the fence: with the fence arm the answer is {'a': 1}, without it the
  // first brace wins and the answer is {}. Nothing else in this list can tell them apart.
  'use {} then\n```json\n{"a": 1}\n```',
  'the list [] first, then\n```json\n{"a": 1}\n```',
  'set {"b": 9} aside;\n```\n[1, 2]\n```',
  '```json\nnot json at all\n```',
  '```json\n```',
  'sure! {"a": 1} — anything else?',
  '{"a": 1}{"b": 2}',
  'the array is [1, 2, 3] ok',
  'a { then [1]',
  'a [1] then {',
  'I could not do that.',
  '',
  '   \n  ',
  'the brace is inside a string: "{" and that is all',
  '```json\n[{"a": 1}]\n```',
  '5',
  'null',
  '"just a string"',
  'text with } closing first then {"a": 1}',
];

const FLOAT_TEXTS = [
  '0.0', '-0.0', '1.0', '1.5', '0.1', '0.0001', '1e-05', '1e-04', '0.00001', '1e15', '1e16',
  '1e17', '1e21', '1e300', '1e-300', '2.5', '3.141592653589793', '1234567890123456.0',
  '12345678901234567.0', '5e-324', '1.7976931348623157e308', '-1.5e-3', '100.0', '1e100',
];

// ------------------------------------------------------------------------------- the run

export async function run(ctx) {
  const cases = [];
  const notes = [];
  const nodeUrl = (m) => pathToFileURL(join(ctx.runtimeTs, 'dist', `${m}.js`)).href;
  const contract = await import(nodeUrl('contract'));
  const pyjson = await import(nodeUrl('pyjson'));

  const repoRoot = ctx.repoRoot;
  const checkpointSchema = readFileSync(
    join(repoRoot, 'assets', 'schemas', 'shiftwork-checkpoint.json'),
    'utf8',
  );
  // The tracked template is always in; the live job checkpoint joins it only when the
  // checkout happens to have one. `.shiftwork/` is gitignored, so on a runner it never
  // does, and an unconditional read here threw ENOENT and took this suite plus `wire` down
  // with it. It is kept as an OPTIONAL extra rather than dropped because a 29 KB document
  // with Thai and sixteen escaped em dashes is a better instrument than a 2 KB one — but
  // it can only ever be a bonus, never the thing the suite rests on.
  const liveCheckpoint = join(repoRoot, '.shiftwork', 'job38-npx-public-install', 'checkpoint.json');
  const realCheckpoints = {
    example: join(repoRoot, 'tools', 'shiftwork', 'example-codefix-checkpoint.json'),
    ...(existsSync(liveCheckpoint) ? { live: liveCheckpoint } : {}),
  };

  // ------------------------------------------------------- 1. schema_error, the sentences

  const specs = [];
  const add = (caseName, schema, outputText) =>
    specs.push({ name: caseName, schema: JSON.stringify(schema), output: outputText });

  for (const [nm, schema, instance] of CLASSES) {
    const text = JSON.stringify(instance);
    add(`class/${nm}`, schema, text);
    add(`nested/${nm}`, { type: 'object', properties: { k: schema } }, `{"k": ${text}}`);
    add(`array/${nm}`, { type: 'array', items: schema }, `[${text}]`);
    add(
      `deep/${nm}`,
      { properties: { a: { properties: { b: { items: schema } } } } },
      `{"a": {"b": [${text}]}}`,
    );
  }
  for (const [nm, schema, instance] of MULTI) add(`multi/${nm}`, schema, JSON.stringify(instance));
  for (const [nm, schema, text] of RAW) add(`raw/${nm}`, schema, text);

  for (const [base, path] of Object.entries(realCheckpoints)) {
    const original = readFileSync(path, 'utf8');
    add(`real/${base}/valid`, JSON.parse(checkpointSchema), original);
    for (const [mname, mutate] of Object.entries(MUTATIONS)) {
      const doc = JSON.parse(original);
      try {
        mutate(doc);
      } catch {
        continue; // the checkpoint has no such field; the other one does
      }
      specs.push({
        name: `real/${base}/${mname}`,
        schema: checkpointSchema,
        output: JSON.stringify(doc),
      });
    }
  }

  // A schema an eval-run caller would send: the tool manifests' own parameter blocks, whose
  // keyword vocabulary is `minimum`/`maximum`/`pattern`/`enum`/`anyOf` and NOT the
  // checkpoint's.
  for (const tool of ['memory_save', 'memory_recall', 'document_read', 'shiftwork_clock_out']) {
    const manifest = JSON.parse(readFileSync(join(repoRoot, 'assets', 'tools', `${tool}.json`), 'utf8'));
    for (const [nm, args] of [
      ['empty', {}],
      ['wrong-types', { type: 5, name: [], k: 'x', offset: -1, document: 1, status: 3 }],
      ['bad-enum', { type: 'nope', name: 'x', description: 'y', body: 'z' }],
      ['bad-pattern', { type: 'project', name: 'NOT A SLUG', description: 'y', body: 'z' }],
      ['out-of-range', { query: 'q', k: 99, offset: -3 }],
    ]) {
      add(`manifest/${tool}/${nm}`, manifest['parameters'], JSON.stringify(args));
    }
  }

  // ------------------------------------------------ the dialects and the one resource (job65)
  //
  // #126: `$schema` picks the dialect, as `validator_for` picks it — each draft gets its own
  // keyword table, and a keyword another dialect owns is DATA (`dependencies` under 2019-09,
  // `dependentRequired` under draft 7). #125: a local `$ref` (`#/$defs`, `#/definitions`,
  // `#anchor`, a pointer with `~1`/`~0`/`%XX`/a list index) resolves inside the one resource a
  // caller schema is, and `unevaluated*` walks the evaluated keys with the walker of the draft.
  // What the one resource cannot hold — a reference with a scheme or path, an embedded `$id`
  // beside any reference, a draft-3 `$schema` — is ANSWERED with one sentence on both sides,
  // and a pointer to nowhere or an unknown anchor is answered lazily where `referencing` finds
  // it. Every row is run under every dialect in which it is a VALID schema for the reference's
  // `check_schema` (the fourth column); the combinations it refuses are measured once more
  // below as the gated bit, so that no (dialect, row) pair is silently skipped.
  //
  // The outputs are TEXT, not values: `{"a": 1.0}` has to stay a float to tell draft 4's
  // `integer` from draft 6's.
  const D = {
    'draft-04': 'http://json-schema.org/draft-04/schema#',
    'draft-06': 'http://json-schema.org/draft-06/schema#',
    'draft-07': 'http://json-schema.org/draft-07/schema#',
    '2019-09': 'https://json-schema.org/draft/2019-09/schema',
    '2020-12': 'https://json-schema.org/draft/2020-12/schema',
    // Not a key of `_META_SCHEMAS`: the reference warns and validates under the latest draft.
    unknown: 'https://example.com/not-a-draft',
    none: null,
  };
  const D3 = 'http://json-schema.org/draft-03/schema#';
  const EVERY = Object.keys(D);
  const MODERN = ['2019-09', '2020-12', 'unknown', 'none'];
  const SINCE6 = ['draft-06', 'draft-07', ...MODERN];
  const TUPLE_ITEMS = ['draft-04', 'draft-06', 'draft-07', '2019-09'];
  const DRAFT_ROWS = [
    // ---- #126: the keyword table moves with the dialect
    ['dependencies-list', { dependencies: { a: ['b'] } }, ['{"a": 1}', '{"a": 1, "b": 2}'], EVERY],
    ['dependencies-schema', { dependencies: { a: { required: ['b'] } } }, ['{"a": 1}', '{"a": 1, "b": 2}'], EVERY],
    ['dependentRequired', { dependentRequired: { a: ['b'] } }, ['{"a": 1}', '{"a": 1, "b": 2}'], EVERY],
    ['dependentSchemas', { dependentSchemas: { a: { required: ['b'] } } }, ['{"a": 1}', '{"a": 1, "b": 2}'], EVERY],
    ['exclusiveMaximum-bool', { properties: { a: { maximum: 1, exclusiveMaximum: true } } }, ['{"a": 1}', '{"a": 0}'], ['draft-04']],
    ['exclusiveMinimum-bool', { properties: { a: { minimum: 1, exclusiveMinimum: true } } }, ['{"a": 1}', '{"a": 2}'], ['draft-04']],
    ['exclusiveMaximum-number', { properties: { a: { exclusiveMaximum: 1 } } }, ['{"a": 1}', '{"a": 0}'], SINCE6],
    ['items-tuple', { properties: { a: { items: [{ type: 'integer' }, { type: 'integer' }] } } }, ['{"a": [1, "x"]}', '{"a": [1, 2, "x"]}'], TUPLE_ITEMS],
    ['additionalItems-false', { properties: { a: { items: [{}], additionalItems: false } } }, ['{"a": [1, 2]}', '{"a": [1]}'], TUPLE_ITEMS],
    ['additionalItems-schema', { properties: { a: { items: [{}], additionalItems: { type: 'integer' } } } }, ['{"a": [1, "x"]}', '{"a": ["x", 1]}'], TUPLE_ITEMS],
    ['prefixItems-and-items-false', { prefixItems: [{ type: 'integer' }], items: false }, ['[1, 2]', '[1]'], SINCE6],
    ['contains', { contains: { type: 'integer' } }, ['["a"]', '[1]'], EVERY],
    ['minContains', { contains: { type: 'integer' }, minContains: 2 }, ['[1, "a"]', '[1, 2]'], EVERY],
    ['if-then', { properties: { a: { if: { type: 'integer' }, then: { minimum: 5 } } } }, ['{"a": 1}', '{"a": 7}'], EVERY],
    ['const', { properties: { a: { const: 1 } } }, ['{"a": 2}', '{"a": 1}'], EVERY],
    ['propertyNames', { propertyNames: { maxLength: 1 } }, ['{"ab": 1}', '{"a": 1}'], EVERY],
    ['integer-1.0', { properties: { a: { type: 'integer' } } }, ['{"a": 1.0}', '{"a": 1}'], EVERY],
    ['ref-siblings', { $defs: { x: { type: 'integer' } }, properties: { a: { $ref: '#/$defs/x', type: 'string' } } }, ['{"a": "s"}', '{"a": 1}'], EVERY],
    ['nested-$schema-redispatch', { properties: { a: { $schema: D['draft-07'], dependencies: { b: ['c'] } } } }, ['{"a": {"b": 1}}', '{"a": {"b": 1, "c": 2}}'], EVERY],
    ['nested-$schema-draft4-bool-exclusive', { properties: { a: { $schema: D['draft-04'], maximum: 1, exclusiveMaximum: true } } }, ['{"a": 1}', '{"a": 0}'], ['draft-04']],
    // ---- #125: references into the one resource
    ['defs-ref', { $defs: { x: { type: 'string' } }, properties: { a: { $ref: '#/$defs/x' } } }, ['{"a": 1}', '{"a": "s"}'], EVERY],
    ['definitions-ref', { definitions: { x: { type: 'string' } }, properties: { a: { $ref: '#/definitions/x' } } }, ['{"a": 1}', '{"a": "s"}'], EVERY],
    ['root-ref', { $ref: '#/$defs/x', $defs: { x: { type: 'string' } } }, ['{"a": 1}', '["s"]'], EVERY],
    ['ref-to-root', { type: 'object', properties: { a: { $ref: '#' } } }, ['{"a": 1}', '{"a": {}}'], EVERY],
    ['pointer-escapes', { $defs: { 'a/b': { type: 'string' }, 'c~d': { type: 'string' } }, properties: { a: { $ref: '#/$defs/a~1b' }, b: { $ref: '#/$defs/c~0d' }, c: { $ref: '#/%24defs/a~1b' } } }, ['{"a": 1, "b": 2, "c": 3}', '{"a": "s", "b": "s", "c": "s"}'], EVERY],
    ['pointer-into-a-list', { allOf: [{ type: 'object' }, { type: 'string' }], properties: { a: { $ref: '#/allOf/1' } } }, ['{"a": 1}'], EVERY],
    ['pointer-into-a-list-from-the-end', { anyOf: [{ type: 'object' }, { type: 'string' }], properties: { a: { $ref: '#/anyOf/-1' } } }, ['{"a": 1}', '{"a": "s"}'], EVERY],
    ['anchor', { $defs: { x: { $anchor: 'foo', type: 'string' } }, properties: { a: { $ref: '#foo' } } }, ['{"a": 1}', '{"a": "s"}'], EVERY],
    ['dynamicRef', { $defs: { x: { $dynamicAnchor: 'foo', type: 'string' } }, properties: { a: { $dynamicRef: '#foo' } } }, ['{"a": 1}', '{"a": "s"}'], EVERY],
    ['recursiveRef', { type: 'object', properties: { a: { $recursiveRef: '#' } } }, ['{"a": 1}', '{"a": {}}'], EVERY],
    ['property-named-$ref', { properties: { $ref: { type: 'string' } } }, ['{"$ref": 1}', '{"$ref": "https://x"}'], EVERY],
    ['root-$id-with-ref', { $id: 'https://example.com/root', $defs: { x: { type: 'string' } }, properties: { a: { $ref: '#/$defs/x' } } }, ['{"a": 1}', '{"a": "s"}'], EVERY],
    ['embedded-$id-no-ref', { $defs: { x: { $id: 'https://example.com/x', type: 'string' } }, properties: { a: { type: 'string' } } }, ['{"a": 1}', '{"a": "s"}'], EVERY],
    // ---- #125: unevaluated*, with each draft's walker
    ['unevaluatedProperties-false', { properties: { a: {} }, unevaluatedProperties: false }, ['{"a": 1, "b": 2}', '{"a": 1}'], EVERY],
    ['unevaluatedProperties-schema', { properties: { a: {} }, unevaluatedProperties: { type: 'integer' } }, ['{"a": 1, "b": "x"}', '{"a": 1, "b": 2}'], EVERY],
    ['unevaluatedProperties-allOf', { allOf: [{ properties: { a: {} } }], unevaluatedProperties: false }, ['{"a": 1, "b": 2}', '{"a": 1}'], EVERY],
    ['unevaluatedProperties-ref', { $ref: '#/$defs/x', $defs: { x: { properties: { a: {} } } }, unevaluatedProperties: false }, ['{"a": 1, "b": 2}', '{"a": 1}'], EVERY],
    ['unevaluatedProperties-if', { if: { required: ['a'] }, then: { properties: { b: {} } }, unevaluatedProperties: false }, ['{"a": 1, "b": 2}', '{"b": 2}'], EVERY],
    // The 2019-09 walker reads the KEYS of an object `additionalProperties` as property names.
    ['unevaluatedProperties-additionalProperties-object', { additionalProperties: { type: 'integer' }, unevaluatedProperties: false }, ['{"type": 1, "b": "x"}', '{"b": 2}'], EVERY],
    ['unevaluatedItems-false', { prefixItems: [{}], unevaluatedItems: false }, ['[1, 2]', '[1]'], EVERY],
    ['unevaluatedItems-tuple-items', { items: [{}], unevaluatedItems: false }, ['[1, 2]', '[1]'], TUPLE_ITEMS],
    ['unevaluatedItems-allOf', { allOf: [{ prefixItems: [{}] }], unevaluatedItems: false }, ['[1, 2]', '[1]'], EVERY],
    ['unevaluatedItems-contains', { contains: { type: 'integer' }, unevaluatedItems: false }, ['[1, "x"]', '[1, 2]'], EVERY],
    // ---- #125: what the one resource cannot hold, and what is found lazily
    ['remote-ref', { properties: { a: { $ref: 'https://example.com/x.json' } } }, ['{"a": 1}'], EVERY],
    ['relative-ref', { properties: { a: { $ref: 'other.json#/x' } } }, ['{"a": 1}'], EVERY],
    ['remote-ref-unreached', { properties: { zz: { $ref: 'https://example.com/x.json' } } }, ['{"a": 1}'], EVERY],
    ['pointer-to-nowhere', { properties: { a: { $ref: '#/$defs/nope' } } }, ['{"a": 1}'], EVERY],
    ['pointer-to-nowhere-unreached', { properties: { zz: { $ref: '#/$defs/nope' } } }, ['{"a": 1}'], EVERY],
    ['anchor-nowhere', { properties: { a: { $ref: '#nope' } } }, ['{"a": 1}'], EVERY],
    ['embedded-$id', { $defs: { x: { $id: 'https://example.com/x', type: 'string' } }, properties: { a: { $ref: '#/$defs/x' } } }, ['{"a": 1}'], EVERY],
    ['embedded-id-draft4-key', { definitions: { x: { id: 'https://example.com/x', type: 'string' } }, properties: { a: { $ref: '#/definitions/x' } } }, ['{"a": 1}'], EVERY],
    ['nested-$schema-draft3', { properties: { a: { $schema: D3, type: 'string' } } }, ['{"a": 1}'], EVERY],
  ];
  const withDialect = (name, schema) => (D[name] === null ? schema : { $schema: D[name], ...schema });
  let draftSpecs = 0;
  for (const [nm, schema, outputs, drafts] of DRAFT_ROWS) {
    for (const draft of drafts) {
      outputs.forEach((text, i) => {
        add(`drafts/${draft}/${nm}/${i}`, withDialect(draft, schema), text);
        draftSpecs += 1;
      });
    }
  }
  // Draft 3 at the root, once per row kind: refused before any keyword runs.
  add('drafts/draft-03/root', { $schema: D3, type: 'string' }, '{"a": 1}');
  add('drafts/draft-03/root-with-ref', { $schema: D3, $ref: '#/definitions/x', definitions: { x: { type: 'string' } } }, '{"a": 1}');
  draftSpecs += 2;

  // The `$schema` URI, normalised as `_utils.URIDict` normalises it: with and without the
  // empty fragment, an upper-case scheme, a leading space and an empty query are ONE key;
  // `https` for a pre-2019 draft, a trailing slash, a non-empty fragment and an unknown URI are
  // not, and fall back to the latest draft, where `dependencies` is data.
  const DIALECT_URIS = [
    'http://json-schema.org/draft-07/schema#',
    'http://json-schema.org/draft-07/schema',
    'HTTP://json-schema.org/draft-07/schema#',
    'http://json-schema.org/draft-07/schema?',
    '  http://json-schema.org/draft-07/schema#',
    'https://json-schema.org/draft-07/schema#',
    'http://json-schema.org/draft-07/schema/',
    'http://json-schema.org/draft-07/schema#frag',
    'https://JSON-schema.org/draft/2020-12/schema',
    'https://json-schema.org/draft/2019-09/schema#',
    'http://json-schema.org/schema#',
    'https://example.com/not-a-draft',
    '',
  ];
  for (const uri of DIALECT_URIS) add(`dialect/${JSON.stringify(uri)}`, { $schema: uri, dependencies: { a: ['b'] } }, '{"a": 1}');

  const pySchemaErrors = ctx.runPython(REF, {
    op: 'schema_error',
    cases: specs.map((s) => ({ schema: b64(s.schema), output: b64(s.output) })),
  }).results;

  let raised = 0;
  /** Both sides' rendered answer, by spec name — so a literal can be pinned without a re-run. */
  const rendered = new Map();
  for (let i = 0; i < specs.length; i += 1) {
    const spec = specs[i];
    let actual;
    try {
      actual = contract.schemaError(spec.output, pyjson.parseJson(spec.schema));
    } catch (e) {
      actual = { error: { type: e.constructor.name, message: b64(e.message) } };
    }
    const expected = pySchemaErrors[i];
    if (typeof expected === 'object' && expected !== null) raised += 1;
    const pyText = answer(expected);
    const nodeText =
      typeof actual === 'string' || actual === null ? answer(actual === null ? null : b64(actual)) : answer(actual);
    rendered.set(spec.name, { python: pyText, node: nodeText });
    cases.push({
      name: `schema_error/${spec.name}`,
      kind: 'string',
      expected: pyText,
      actual: nodeText,
    });
  }
  notes.push(`${specs.length} schema_error cases; ${raised} of them are an EXCEPTION on both sides`);
  notes.push(`${draftSpecs} of them are the drafts/ matrix (job65, #125/#126) and ${DIALECT_URIS.length} the dialect/ URIs`);

  /**
   * THE PROPERTIES OF #125 AND #126 ARE ABSOLUTE, so they are pinned per side. The differential
   * above is green whether both sides answer `(valid)` for a draft-7 `dependencies` violation
   * or both say the sentence — and "both say `(valid)`" is exactly the wrong verdict #126
   * reports. Likewise a `$ref` that both sides skipped would compare equal. Each literal below
   * is the sentence the CPython reference printed on 2026-10-14 (`.shiftwork/notes-job65/J65-3.md`
   * carries the probe), and a port or a reference that stops printing it fails on its own line.
   */
  const DRAFT_LITERALS = {
    // #126: never `(valid)` for a keyword the dialect owns.
    'drafts/draft-07/dependencies-list/0': "JSON does not match schema at 'root': 'b' is a dependency of 'a'",
    'drafts/draft-07/dependencies-list/1': '(valid)',
    'drafts/2019-09/dependencies-list/0': '(valid)',
    'drafts/2019-09/dependentRequired/0': "JSON does not match schema at 'root': 'b' is a dependency of 'a'",
    'drafts/draft-07/dependentRequired/0': '(valid)',
    'drafts/draft-04/exclusiveMaximum-bool/0': "JSON does not match schema at 'a': 1 is greater than or equal to the maximum of 1",
    'drafts/draft-04/exclusiveMaximum-bool/1': '(valid)',
    'drafts/draft-07/items-tuple/0': "JSON does not match schema at 'a/1': 'x' is not of type 'integer'",
    'drafts/draft-07/items-tuple/1': '(valid)',
    // `$ref` silences its siblings through draft 7 (`ignore_ref_siblings`); from 2019-09 on both apply.
    'drafts/draft-07/ref-siblings/1': '(valid)',
    'drafts/2019-09/ref-siblings/1': "JSON does not match schema at 'a': 1 is not of type 'string'",
    'drafts/draft-04/integer-1.0/0': "JSON does not match schema at 'a': 1.0 is not of type 'integer'",
    'drafts/draft-06/integer-1.0/0': '(valid)',
    'drafts/2020-12/nested-$schema-redispatch/0': "JSON does not match schema at 'a': 'c' is a dependency of 'b'",
    // #125: resolved, both verdicts.
    'drafts/none/defs-ref/0': "JSON does not match schema at 'a': 1 is not of type 'string'",
    'drafts/none/defs-ref/1': '(valid)',
    'drafts/none/definitions-ref/0': "JSON does not match schema at 'a': 1 is not of type 'string'",
    'drafts/none/root-ref/0': "JSON does not match schema at 'root': {'a': 1} is not of type 'string'",
    'drafts/2020-12/anchor/0': "JSON does not match schema at 'a': 1 is not of type 'string'",
    'drafts/draft-07/anchor/0': 'the reference "#foo" names no anchor in this schema',
    'drafts/2019-09/recursiveRef/0': "JSON does not match schema at 'a': 1 is not of type 'object'",
    'drafts/2020-12/recursiveRef/0': '(valid)',
    'drafts/none/unevaluatedProperties-false/0': "JSON does not match schema at 'root': Unevaluated properties are not allowed ('b' was unexpected)",
    'drafts/none/unevaluatedProperties-false/1': '(valid)',
    'drafts/none/unevaluatedItems-false/0': "JSON does not match schema at 'root': Unevaluated items are not allowed (2 was unexpected)",
    'drafts/none/unevaluatedItems-false/1': '(valid)',
    'drafts/2019-09/unevaluatedItems-tuple-items/0': "JSON does not match schema at 'root': Unevaluated items are not allowed (2 was unexpected)",
    'drafts/2019-09/unevaluatedProperties-additionalProperties-object/0': "JSON does not match schema at 'root': Unevaluated properties are not allowed ('b' was unexpected)",
    'drafts/2020-12/unevaluatedProperties-additionalProperties-object/0': "JSON does not match schema at 'root': Unevaluated properties are not allowed ('b' was unexpected)",
    // #125: refused with one sentence — ANSWERED, so a model can act on it.
    'drafts/none/remote-ref/0': 'the reference "https://example.com/x.json" cannot be resolved: only references into this schema ("#", "#/..." and "#name") are supported',
    'drafts/none/remote-ref-unreached/0': 'the reference "https://example.com/x.json" cannot be resolved: only references into this schema ("#", "#/..." and "#name") are supported',
    'drafts/none/relative-ref/0': 'the reference "other.json#/x" cannot be resolved: only references into this schema ("#", "#/..." and "#name") are supported',
    'drafts/none/pointer-to-nowhere/0': 'the reference "#/$defs/nope" points at nothing in this schema',
    'drafts/none/pointer-to-nowhere-unreached/0': '(valid)',
    'drafts/none/anchor-nowhere/0': 'the reference "#nope" names no anchor in this schema',
    'drafts/none/embedded-$id/0': 'the schema declares "$id" at $defs/x; references are only resolved in a schema with a single resource',
    'drafts/draft-04/embedded-id-draft4-key/0': 'the schema declares "id" at definitions/x; references are only resolved in a schema with a single resource',
    'drafts/draft-07/embedded-id-draft4-key/0': "JSON does not match schema at 'a': 1 is not of type 'string'",
    'drafts/none/embedded-$id-no-ref/0': "JSON does not match schema at 'a': 1 is not of type 'string'",
    'drafts/none/nested-$schema-draft3/0': `the schema's $schema "${D3}" names draft 3, which this validator does not support (draft-04, draft-06, draft-07, 2019-09 and 2020-12 are)`,
    'drafts/draft-03/root': `the schema's $schema "${D3}" names draft 3, which this validator does not support (draft-04, draft-06, draft-07, 2019-09 and 2020-12 are)`,
    // the URI
    'dialect/"http://json-schema.org/draft-07/schema"': "JSON does not match schema at 'root': 'b' is a dependency of 'a'",
    'dialect/"https://json-schema.org/draft-07/schema#"': '(valid)',
  };
  for (const [specName, sentence] of Object.entries(DRAFT_LITERALS)) {
    const got = rendered.get(specName) ?? { python: null, node: null };
    cases.push({
      name: `schema_error/${specName}: the sentence, as a literal on each side`,
      kind: 'json',
      expected: { python: sentence, node: sentence },
      actual: { python: got.python, node: got.node },
    });
  }
  notes.push(`drafts: ${Object.keys(DRAFT_LITERALS).length} sentences pinned as a literal on each side`);

  // ------------------------------------------- `job.roles`, as a literal on each side

  /**
   * WHY LITERALS AND NOT ONLY THE DIFFERENTIAL ABOVE. `job.roles` is a change to a SHARED
   * asset — both runtimes read `assets/schemas/shiftwork-checkpoint.json`, the Node package
   * by vendoring a copy of it — so deleting `propertyNames` from the schema turns
   * `job-roles-bad-key` from a refusal into `(valid)` on BOTH sides at once, and every
   * differential case above stays green through it. J46-6 measured that blindness on a
   * shared default and the answer is the same here: pin the sentence itself, per side. The
   * two `(valid)` rows are the other half of the property — the field is OPTIONAL and an
   * empty map constrains nothing, so a schema that started refusing them would be wrong in
   * the direction that stops a live job.
   */
  const ROLES_LITERALS = {
    'job-roles-valid': '(valid)',
    'job-roles-empty-map': '(valid)',
    'job-roles-bad-key':
      "JSON does not match schema at 'job/roles': 'auditor' is not one of ['planner', 'implementer', 'reviewer']",
    'job-roles-empty-list': "JSON does not match schema at 'job/roles/implementer': [] should be non-empty",
    'job-roles-string-value':
      "JSON does not match schema at 'job/roles/implementer': 'claude-opus-5' is not of type 'array'",
    'job-roles-empty-name': "JSON does not match schema at 'job/roles/reviewer/0': '' should be non-empty",
    'job-roles-not-object':
      "JSON does not match schema at 'job/roles': ['implementer'] is not of type 'object'",
  };
  for (const [mname, sentence] of Object.entries(ROLES_LITERALS)) {
    const got = rendered.get(`real/example/${mname}`) ?? { python: null, node: null };
    cases.push({
      name: `schema_error/real/example/${mname}: the sentence, as a literal on each side`,
      kind: 'json',
      expected: { python: sentence, node: sentence },
      actual: { python: got.python, node: got.node },
    });
  }
  notes.push(
    `job.roles: ${Object.keys(ROLES_LITERALS).length} sentences pinned as a literal on each side — ` +
      'a shared-asset change is invisible to the differential half of this suite',
  );

  /**
   * job50/F8, the same instrument for a LOOSENING. `handoff.notes` was added to the shared
   * schema; the differential above is green whether `handoff` is closed or wide open,
   * because both sides read the same text. What must not drift: the two `(valid)` rows say
   * the key exists and may be empty, and the two refusals say the object is STILL closed —
   * a typo one letter off the new key is refused, and so is the right key with the wrong
   * shape. Note this suite hands the schema text to both sides itself, so it cannot see a
   * stale vendored copy under `runtime-ts/assets/`; the `shiftwork` suite's `handoff/`
   * block, which goes through `clockOut` and each runtime's own loader, is what can.
   */
  const HANDOFF_LITERALS = {
    'handoff-notes-valid': '(valid)',
    'handoff-notes-empty': '(valid)',
    'handoff-notes-type': "JSON does not match schema at 'handoff/notes': 5 is not of type 'string'",
    'handoff-extra-key':
      "JSON does not match schema at 'handoff': Additional properties are not allowed ('note' was unexpected)",
  };
  for (const [mname, sentence] of Object.entries(HANDOFF_LITERALS)) {
    const got = rendered.get(`real/example/${mname}`) ?? { python: null, node: null };
    cases.push({
      name: `schema_error/real/example/${mname}: the sentence, as a literal on each side`,
      kind: 'json',
      expected: { python: sentence, node: sentence },
      actual: { python: got.python, node: got.node },
    });
  }
  notes.push(
    `handoff.notes: ${Object.keys(HANDOFF_LITERALS).length} sentences pinned as a literal on each side — ` +
      'two accept, two refuse, so neither a closed nor an open `handoff` can satisfy all four',
  );

  // ------------------------------------------------------- 2. the CPython decoder's text

  const damaged = decoderCorpus();
  const pyDecoded = ctx.runPython(REF, { op: 'raw_decode', texts: damaged.map(b64) }).results;
  for (let i = 0; i < damaged.length; i += 1) {
    let actual;
    try {
      const [value, end] = pyjson.rawDecode(damaged[i]);
      actual = `${pyjson.reprValue(value)} @${end}`;
    } catch (e) {
      actual = `${e.name === 'PyJSONDecodeError' ? 'JSONDecodeError' : e.name}: ${e.message}`;
    }
    const py = pyDecoded[i];
    const expected = py.error
      ? `${py.error.type}: ${unb64(py.error.message)}`
      : `${unb64(py.repr)} @${py.end}`;
    cases.push({ name: `raw_decode/${JSON.stringify(damaged[i])}`, kind: 'string', expected, actual });
  }
  notes.push(`${damaged.length} raw_decode cases, from truncations and single-char mutations`);

  // ------------------------------------------------------------- 3. extract_json's arms

  const pyExtracted = ctx.runPython(REF, { op: 'extract_json', texts: EXTRACT_TEXTS.map(b64) }).results;
  for (let i = 0; i < EXTRACT_TEXTS.length; i += 1) {
    let actual;
    try {
      actual = pyjson.reprValue(contract.extractJson(EXTRACT_TEXTS[i]));
    } catch (e) {
      const type = e.name === 'PyJSONDecodeError' ? 'JSONDecodeError' : 'ValueError';
      actual = `${type}: ${e.message}`;
    }
    const py = pyExtracted[i];
    const expected = py.error ? `${py.error.type}: ${unb64(py.error.message)}` : unb64(py.repr);
    cases.push({ name: `extract_json/${JSON.stringify(EXTRACT_TEXTS[i])}`, kind: 'string', expected, actual });
  }

  // ------------------------------------------------------------------------ 4. repr(float)

  const pyFloats = ctx.runPython(REF, { op: 'float_repr', texts: FLOAT_TEXTS }).reprs;
  for (let i = 0; i < FLOAT_TEXTS.length; i += 1) {
    cases.push({
      name: `float_repr/${FLOAT_TEXTS[i]}`,
      kind: 'string',
      expected: pyFloats[i],
      actual: pyjson.pyFloatRepr(Number(FLOAT_TEXTS[i])),
    });
  }

  // ---------------------------------------------- 5. the contract asset, key for key

  const pyContract = ctx.runPython(REF, { op: 'contract', name: 'default' }).data;
  const nodeContract = contract.loadContract();
  cases.push({
    name: 'load_contract/key-set',
    kind: 'string',
    expected: Object.keys(pyContract).join('\n'),
    actual: Object.keys(nodeContract).join('\n'),
  });
  for (const [key, value] of Object.entries(pyContract)) {
    cases.push({
      name: `load_contract/${key}`,
      kind: 'bytes',
      expected: unb64(value),
      actual: nodeContract[key] ?? '(absent)',
    });
  }

  // --------------------------------------------------------------------------- rulings

  // ---------------------------------------------- the caller schema that is not a schema
  //
  // `jsonschema.validate` runs `check_schema` BEFORE it looks at the instance, so an invalid
  // caller schema raises `SchemaError` — and `contract.schema_error` catches only
  // `ValidationError`, so it escapes `validate_json` to the caller. (That escape is a
  // registered `runtime-py` defect: a tool handed a schema by a model should not let an
  // exception out. NOT fixed here — invariant 8.)
  //
  // WAS: this port ran the keywords anyway, and the keywords SKIP a schema value they do not
  // recognise, which is right inside `iter_errors` and a wrong ANSWER at the tool boundary.
  // N8 measured five on the wire — four `{"valid": true}` and one invented sentence about a
  // schema that is not one. The previous ruling here covered `{"type": "nosuch"}` and
  // asserted the general case from it; N8's correction is now a fix, and this is the
  // measurement at the width it was measured.
  //
  // NOW both runtimes REFUSE all 50 of these and only the WORDS differ: Python quotes the
  // metaschema (`'a' is not of type 'array'`, plus the failing metaschema path), this port
  // names the keyword and the shape it wanted. Each is a ruled case, so a shape that ever
  // stops differing — because someone made the port answer again — fails the run.
  const BAD_SCHEMAS = [
    ['required is a string', '{"required": "a"}'],
    ['required is an int', '{"required": 3}'],
    ['required item is an int', '{"required": [3]}'],
    ['required has a duplicate', '{"required": ["a", "a"]}'],
    ['properties is a list', '{"properties": ["a"]}'],
    ['properties value is an int', '{"properties": {"a": 3}}'],
    ['additionalProperties is a list', '{"additionalProperties": [1]}'],
    ['additionalProperties is an int', '{"additionalProperties": 1}'],
    ['type is an int', '{"type": 3}'],
    ['type is an unknown name', '{"type": "nosuch"}'],
    ['type list holds an int', '{"type": ["string", 3]}'],
    ['type list has a duplicate', '{"type": ["string", "string"]}'],
    ['type is an empty list', '{"type": []}'],
    ['enum is a string', '{"enum": "a"}'],
    ['multipleOf is a string', '{"multipleOf": "a"}'],
    ['multipleOf is zero', '{"multipleOf": 0}'],
    ['multipleOf is negative', '{"multipleOf": -1}'],
    ['minimum is a string', '{"minimum": "a"}'],
    ['maxLength is a string', '{"maxLength": "a"}'],
    ['maxLength is negative', '{"maxLength": -1}'],
    ['maxLength is fractional', '{"maxLength": 1.5}'],
    ['uniqueItems is a string', '{"uniqueItems": "yes"}'],
    ['pattern is an int', '{"pattern": 3}'],
    ['pattern does not compile', '{"pattern": "("}'],
    ['format is an int', '{"format": 3}'],
    ['allOf is an object', '{"allOf": {"a": 1}}'],
    ['allOf is empty', '{"allOf": []}'],
    ['allOf item is an int', '{"allOf": [3]}'],
    ['anyOf is an object', '{"anyOf": {}}'],
    ['oneOf is a string', '{"oneOf": "x"}'],
    ['prefixItems is an object', '{"prefixItems": {}}'],
    ['items is an int', '{"items": 3}'],
    ['contains is an int', '{"contains": 3}'],
    ['not is an int', '{"not": 3}'],
    ['if is an int', '{"if": 3}'],
    ['propertyNames is an int', '{"propertyNames": 3}'],
    ['patternProperties is a list', '{"patternProperties": []}'],
    ['patternProperties value is an int', '{"patternProperties": {"^a": 3}}'],
    ['dependentRequired is a string', '{"dependentRequired": "a"}'],
    ['dependentRequired value is a string', '{"dependentRequired": {"a": "b"}}'],
    ['dependentSchemas is a list', '{"dependentSchemas": []}'],
    ['dependentSchemas value is an int', '{"dependentSchemas": {"a": 3}}'],
    ['minContains is a string', '{"minContains": "a"}'],
    ['the schema is a list', '[1]'],
    ['the schema is an int', '3'],
    ['the schema is a string', '"x"'],
    // The check is RECURSIVE, and the last of these is the one that says so loudest: `$defs`
    // is never descended into by any keyword this port implements, and Python still refuses.
    ['bad shape under properties', '{"properties": {"a": {"required": "b"}}}'],
    ['bad shape under items', '{"items": {"type": 3}}'],
    ['bad shape under an unused $defs', '{"$defs": {"x": {"type": 3}}}'],
    ['bad shape two levels down an anyOf', '{"anyOf": [{"properties": {"a": {"maxLength": "x"}}}]}'],
  ];
  const BAD_OUTPUT = '{"a": 1}';
  const pyBad = ctx.runPython(REF, {
    op: 'schema_error',
    cases: BAD_SCHEMAS.map(([, schema]) => ({ schema: b64(schema), output: b64(BAD_OUTPUT) })),
  }).results;
  for (let i = 0; i < BAD_SCHEMAS.length; i += 1) {
    const [nm, schema] = BAD_SCHEMAS[i];
    cases.push({
      name: `ruling: check_schema/${nm}`,
      kind: 'string',
      expected: answer(pyBad[i]),
      actual: (() => {
        try {
          return nodeAnswer(contract.schemaError(BAD_OUTPUT, pyjson.parseJson(schema)));
        } catch (e) {
          return `${e.name}: ${e.message}`;
        }
      })(),
      ruling:
        'BOTH RUNTIMES REFUSE this schema and the exception escapes `validate_json` in both. ' +
        "Python's `check_schema` quotes the 2020-12 metaschema and the path inside it; this " +
        'port names the keyword and the shape the metaschema demands. Running the real ' +
        'metaschema is not available here — it is eight documents wired with `$ref` and ' +
        '`$dynamicRef`, the vocabulary this validator refuses to implement, so `check_schema` ' +
        'would have to be more capable than `validate`. The RULING IS THAT BOTH REFUSE, ' +
        'measured over 50 shapes and not generalised from one: the previous wording here ' +
        'asserted the general case from `{"type": "nosuch"}` and N8 found five ' +
        'counter-examples inside it.',
    });
  }
  // THE RULED CASES ABOVE PIN THE WORDING, NOT THE REFUSAL, and that distinction is the
  // trap N8 found in this file: a `ruling` case fails only when the two sides MATCH, so a
  // port that went back to answering `{"valid": true}` would still "differ" from Python's
  // SchemaError and every one of those 50 would stay green. This case is the other half and
  // it is NOT ruled: one bit per schema, did you refuse, and the two arrays must be equal.
  cases.push({
    name: `check_schema: all ${BAD_SCHEMAS.length} refuse on both sides — the bit, not the words`,
    kind: 'json',
    expected: pyBad.map((r) => typeof r === 'object' && r !== null && r.error !== undefined),
    actual: BAD_SCHEMAS.map(([, schema]) => {
      try {
        contract.schemaError(BAD_OUTPUT, pyjson.parseJson(schema));
        return false;
      } catch {
        return true;
      }
    }),
  });

  // THE SAME CHECK, GATED BY DIALECT (job65, #126). A keyword the dialect does not know is DATA
  // to its metaschema, so the same value is a `SchemaError` under one `$schema` and a valid
  // schema under another. Each row below is the pair: the dialect that REFUSES it (both sides,
  // the bit; the words are the already-ruled `refuse()` divergence above) and the dialect under
  // which it is data (both sides ANSWER, compared as strings through `schemaError`).
  const GATED = [
    ['if is an int', '{"if": 3}', 'draft-07', 'draft-04'],
    ['contains is an int', '{"contains": 3}', 'draft-06', 'draft-04'],
    ['propertyNames is an int', '{"propertyNames": 3}', 'draft-06', 'draft-04'],
    ['dependentRequired value is a string', '{"dependentRequired": {"a": "b"}}', '2019-09', 'draft-07'],
    ['dependentSchemas value is an int', '{"dependentSchemas": {"a": 3}}', '2019-09', 'draft-07'],
    // `dependencies` is no longer a KEYWORD from 2019-09 on and still a SHAPE in every
    // metaschema (deprecated, kept for compatibility), so there is no dialect that answers it.
    ['dependencies value is an int', '{"dependencies": {"a": 3}}', 'draft-07', null],
    ['dependencies value is an int, under 2019-09', '{"dependencies": {"a": 3}}', '2019-09', null],
    ['dependencies value is an int, under 2020-12', '{"dependencies": {"a": 3}}', '2020-12', null],
    ['dependencies list is empty', '{"dependencies": {"a": []}}', 'draft-04', 'draft-06'],
    ['dependencies list is empty, 2020-12 answers too', '{"dependencies": {"a": []}}', 'draft-04', '2020-12'],
    ['unevaluatedProperties is an int', '{"unevaluatedProperties": 3}', '2019-09', 'draft-07'],
    ['$defs value is an int', '{"$defs": {"x": 3}}', '2019-09', 'draft-07'],
    // `definitions` is the same shape: in every metaschema, a keyword in none from 2019-09.
    ['definitions value is an int', '{"definitions": {"x": 3}}', 'draft-04', null],
    ['definitions value is an int, under 2020-12', '{"definitions": {"x": 3}}', '2020-12', null],
    ['exclusiveMaximum is a number', '{"exclusiveMaximum": 1}', 'draft-04', 'draft-06'],
    ['exclusiveMaximum is a boolean', '{"maximum": 1, "exclusiveMaximum": true}', 'draft-06', 'draft-04'],
    ['exclusiveMaximum without maximum', '{"exclusiveMaximum": true}', 'draft-04', null],
    ['a boolean subschema', '{"properties": {"a": true}}', 'draft-04', 'draft-06'],
    ['required is empty', '{"required": []}', 'draft-04', 'draft-06'],
    ['enum is empty', '{"enum": []}', 'draft-04', 'draft-06'],
    ['items is a tuple', '{"items": [{}]}', '2020-12', '2019-09'],
    ['items tuple is empty', '{"items": []}', 'draft-07', null],
    ['prefixItems is an object', '{"prefixItems": {}}', '2020-12', '2019-09'],
    ['maxContains is a string', '{"maxContains": "a"}', '2019-09', 'draft-07'],
    ['maxLength is 2.0', '{"maxLength": 2.0}', 'draft-04', 'draft-06'],
    ['$anchor is malformed', '{"$anchor": "#x"}', '2019-09', 'draft-07'],
    ['$anchor starts with an underscore', '{"$anchor": "_x"}', '2019-09', '2020-12'],
    ['$dynamicAnchor is an int', '{"$dynamicAnchor": 3}', '2020-12', '2019-09'],
    ['$id carries a fragment', '{"$id": "https://example.com/x#frag"}', '2020-12', 'draft-07'],
    // Draft 4's metaschema has no `$ref` property, and the reference still raises — lazily,
    // from the lookup (`AttributeError`) — so no dialect ANSWERS this one either.
    ['$ref is an int', '{"$ref": 3}', '2020-12', null],
    ['$ref is an int, under draft 4', '{"$ref": 3}', 'draft-04', null],
    ['$recursiveRef is an int', '{"$recursiveRef": 3}', '2019-09', 'draft-07'],
    ['$schema is an int', '{"$schema": 3}', null, null],
  ];
  // Spliced into the TEXT, not through `JSON.parse`: `{"maxLength": 2.0}` has to reach both
  // decoders as a float, which a round trip through a JS number would erase.
  const gatedSchema = (draft, text) => {
    if (draft === null) return text;
    return text.replace(/^\{/, `{"$schema": ${JSON.stringify(D[draft])}, `);
  };
  const GATED_OUTPUT = '{"a": [1]}';
  const pyGated = ctx.runPython(REF, {
    op: 'schema_error',
    cases: GATED.flatMap(([, text, refuses, answers]) => [
      { schema: b64(gatedSchema(refuses, text)), output: b64(GATED_OUTPUT) },
      ...(answers === null ? [] : [{ schema: b64(gatedSchema(answers, text)), output: b64(GATED_OUTPUT) }]),
    ]),
  }).results;
  const nodeGated = (text) => {
    try {
      return nodeAnswer(contract.schemaError(GATED_OUTPUT, pyjson.parseJson(text)));
    } catch (e) {
      return { error: `${e.name}: ${e.message}` };
    }
  };
  let gi = 0;
  const gatedBits = { python: [], node: [] };
  for (const [nm, text, refuses, answers] of GATED) {
    const py = pyGated[gi++];
    const node = nodeGated(gatedSchema(refuses, text));
    gatedBits.python.push(typeof py === 'object' && py !== null && py.error !== undefined);
    gatedBits.node.push(typeof node === 'object');
    if (answers === null) continue;
    const pyA = pyGated[gi++];
    const nodeA = nodeGated(gatedSchema(answers, text));
    cases.push({
      name: `check_schema/gated: ${nm} is DATA under ${answers}`,
      kind: 'string',
      expected: answer(pyA),
      actual: typeof nodeA === 'object' ? nodeA.error : nodeA,
    });
  }
  cases.push({
    name: `check_schema/gated: all ${GATED.length} shapes refuse on both sides under the dialect that knows them — the bit, not the words`,
    kind: 'json',
    expected: GATED.map(() => true),
    actual: gatedBits.python,
  });
  cases.push({
    name: `check_schema/gated: the port's ${GATED.length} refusal bits equal the reference's`,
    kind: 'json',
    expected: gatedBits.python,
    actual: gatedBits.node,
  });

  // AMENDED (job65 J65-7, #131). Until this job this was `ruling: a Python-only regex in a
  // branch that never fires`: `checkSchema` compiled `pattern` as a JS RegExp, so `(?P<x>a)` —
  // valid `re` — raised here while Python answered `(valid)`. The issue, filed against the
  // released contract, outranks the pin: the port now parses `re`'s grammar, so the two MATCH
  // and the ruling went `STALE RULING`. The old ruling's text, for the record: "THE PRICE OF
  // CHECKING `pattern` EAGERLY, stated rather than hidden. `check_schema` compiles every
  // `pattern` (the metaschema's `"format": "regex"`), which is how `{"pattern": "("}` became a
  // refusal on both sides instead of `{"valid": true}` here. The same eagerness makes this
  // port refuse `(?P<x>…)` — valid `re`, invalid `RegExp` — even though the instance has no
  // `s` and the keyword would never have fired. Python answers `(valid)`. … Porting
  // `sre_compile` is what would close it."
  cases.push({
    name: 'a Python-only regex in a branch that never fires answers on both sides (#131; was a ruling until job65)',
    kind: 'string',
    expected: answer(
      ctx.runPython(REF, {
        op: 'schema_error',
        cases: [{ schema: b64('{"properties": {"s": {"pattern": "(?P<x>a)"}}}'), output: b64('{"n": 1}') }],
      }).results[0],
    ),
    actual: (() => {
      try {
        return nodeAnswer(
          contract.schemaError('{"n": 1}', pyjson.parseJson('{"properties": {"s": {"pattern": "(?P<x>a)"}}}')),
        );
      } catch (e) {
        return `${e.name}: ${e.message}`;
      }
    })(),
  });

  // AMENDED (job65, #125). Until this job the case here was `ruling: $ref is not resolved`: the
  // port raised `jsonschema seam: $ref is not implemented by this port` and the ruling pinned the
  // WORDS of that refusal against Python's sentence. The issue, filed against the released
  // contract, outranks the pin: the port now resolves a local `$ref` inside the one resource a
  // caller schema is, so the two sides MATCH and the ruling would have gone `STALE RULING` — which
  // is the design (docs/conformance.md), not a regression. Kept as the non-ruled case it has become,
  // and the whole surface is measured below under `drafts/`. The old ruling's text, for the record:
  // "`$ref` needs a reference resolver and a registry. Measured over the whole asset pack
  // (`assets/**\/*.json`): zero occurrences of `$ref`, `$dynamicRef`, `unevaluatedItems` and
  // `unevaluatedProperties`, so nothing bantamkit ships reaches this. A caller-supplied schema can,
  // and this port refuses by name rather than validating a document against half a schema and
  // reporting it valid — which is what silently skipping the keyword would do."
  const REF_SCHEMA = '{"$defs": {"x": {"type": "integer"}}, "properties": {"a": {"$ref": "#/$defs/x"}}}';
  cases.push({
    name: '$ref into #/$defs resolves on both sides (#125; was `ruling: $ref is not resolved` until job65)',
    kind: 'string',
    expected: answer(
      ctx.runPython(REF, { op: 'schema_error', cases: [{ schema: b64(REF_SCHEMA), output: b64('{"a": "s"}') }] }).results[0],
    ),
    actual: (() => {
      try {
        return nodeAnswer(contract.schemaError('{"a": "s"}', pyjson.parseJson(REF_SCHEMA)));
      } catch (e) {
        return `${e.name}: ${e.message}`;
      }
    })(),
  });

  cases.push({
    name: 'ruling: fromJs cannot tell 1 from 1.0 in a caller schema',
    kind: 'string',
    // `minimum` constrains NUMBERS. The instance has to BE a number for the keyword to fire:
    // with `[0]` — an array — jsonschema skips `minimum` entirely and both runtimes answer
    // "valid", which is what made this case toothless before N8 rewrote it.
    expected: answer(
      ctx.runPython(REF, {
        op: 'schema_error',
        cases: [{ schema: b64('{"properties": {"n": {"minimum": 1.0}}}'), output: b64('{"n": 0}') }],
      }).results[0],
    ),
    actual: nodeAnswer(contract.schemaError('{"n": 0}', { properties: { n: { minimum: 1.0 } } })),
    ruling:
      'A JS number carries no record of the decimal point its JSON text had, so a schema that ' +
      'has already been through an SDK parser reaches this port with `1.0` indistinguishable ' +
      'from `1`, and the sentence says `the minimum of 1` where Python says `1.0` — measured, both sides now report the SAME instance as invalid and disagree only on how they spell the bound. The exact ' +
      'route exists and is used everywhere the raw bytes are still in hand — `pyjson.parseJson`, ' +
      'which is what every non-ruled case above goes through. The loss is confined to ' +
      '`fromJs`, and measured over the whole asset pack it is unreachable there: no shipped ' +
      'schema holds a non-integral number.',
  });

  // `pattern` constrains STRINGS, so the Thai digits have to be a string the keyword applies
  // to. `["๑๒๓"]` is an array: jsonschema skips `pattern` and BOTH runtimes answer "valid".
  // Measured over the wire, this schema and instance is one of 11 divergences in 15 regex
  // shapes; the array form was zero of them.
  const REGEX_SCHEMA = '{"properties": {"s": {"pattern": "^\\\\d+$"}}}';
  const REGEX_OUTPUT = '{"s": "\\u0e51\\u0e52\\u0e53"}';
  const pyRegex = ctx.runPython(REF, {
    op: 'schema_error',
    cases: [{ schema: b64(REGEX_SCHEMA), output: b64(REGEX_OUTPUT) }],
  }).results[0];
  // AMENDED (job65 J65-7, #131). Until this job this was `ruling: python re and JS RegExp are
  // different languages`, pinning that the port's `\d` was ASCII. The issue outranks the pin:
  // the port translates `re`'s classes, the two MATCH, and the ruling went `STALE RULING`. The
  // old ruling's text, for the record: "Python's `\d` matches every Unicode decimal digit and
  // JS's matches [0-9], so Thai digits satisfy the pattern in Python and fail it here. `$`
  // before a trailing newline, `(?P<name>…)`, `\A` and `\Z` diverge too. … Fixing this means
  // porting `sre_compile`, which is a larger surface than the whole validator." The whole
  // dialect is now measured below under `pattern/`.
  cases.push({
    name: 'python re digits are Unicode on both sides (#131; was `ruling: python re and JS RegExp are different languages` until job65)',
    kind: 'string',
    expected: answer(pyRegex),
    actual: nodeAnswer(contract.schemaError(REGEX_OUTPUT.replace('\\u0e51\\u0e52\\u0e53', '๑๒๓'), pyjson.parseJson(REGEX_SCHEMA))),
  });

  // ======================================================= job65 J65-7: #131 #132 #152 #153
  //
  // THE PROPERTIES. (#131) the `pattern` dialect is Python's `re` on both sides: the port
  // parses `re`'s grammar and translates it, and a construct it cannot translate faithfully is
  // refused with ONE sentence by both, never answered differently. (#132) a document's patterns
  // run against a shared 500 ms budget and a pattern past it is refused with one sentence. (#152)
  // a top-level scalar is a JSON document. (#153) feedback quotes at most 200 codepoints of an
  // offending value and at most 1000 of the sentence, with a `…(N more)` tail.
  const pyjsonschema = await import(nodeUrl('pyjsonschema'));

  // ---- the dialect itself: a seeded corpus of patterns, per pattern a row of search bits ---
  const DIALECT_TOKENS = [
    'a', 'b', 'c', '\n', 'ไ', '๑', '_', '-', ' ', 'Z', '.', '^', '$', '|', '(', ')', '(?:', '(?P<n>', '(?P<m>',
    '(?P=n)', '(?=', '(?!', '(?<=', '(?<!', '(?#c)', '(?i)', '(?u)', '(?a)', '(?x)', '(?i:', '(?-i:', '(?>',
    '(?(1)', '(?(n)', '(?P', '(?<n>', '(?L)', '(?au)', '[', ']', '[^', '[]', '*', '+', '?', '{', '}', '{2}',
    '{1,3}', '{,2}', '{3,1}', '{1,}', ',', '\\d', '\\D', '\\w', '\\W', '\\s', '\\S', '\\b', '\\B', '\\A', '\\Z',
    '\\1', '\\0', '\\12', '\\101', '\\400', '\\8', '\\x41', '\\x4', '\\u0e51', '\\U0001F600', '\\U00110000',
    '\\N{DIGIT ONE}', '\\q', '\\-', '\\.', '\\]', '\\\\', '\\', '*+', '++', '??', '#', '\\a', '\\v', '\\t',
    '&&', '--', '/', '😀', '{0}', '(a)', '(?:b|c)', '[a-c]', '[^\\d]', '[\\w-]', '[\\s\\S]', '[ไ-๑]', '(ab|)',
    '[]a]', '[a-]', '[\\b]',
  ];
  const DIALECT_STRINGS = [
    '', 'a', 'ab', 'aab', 'abc', 'a\n', '\n', 'ไทย', '๑๒๓', '123', 'a b', 'A', 'a_b-c', '😀', '\x1c',
    '﻿', '\r', '{', 'abcZ', 'b', 'aa', ' ', '\x08', '\x07', '-', 'c\n', 'Z', '}', ',', '\\', '#', '&&',
  ];
  let seed = 0x6a3507; // mulberry32: the corpus is the same on every run, so a red is rerunnable
  const rand = () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const dialectPatterns = [];
  const seenPatterns = new Set();
  while (dialectPatterns.length < 4000) {
    let p = '';
    const n = 1 + Math.floor(rand() * 7);
    for (let i = 0; i < n; i += 1) p += DIALECT_TOKENS[Math.floor(rand() * DIALECT_TOKENS.length)];
    if (seenPatterns.has(p)) continue;
    seenPatterns.add(p);
    dialectPatterns.push(p);
  }
  const pyDialect = ctx.runPython(REF, {
    op: 'pattern_dialect',
    patterns: dialectPatterns.map(b64),
    strings: DIALECT_STRINGS.map(b64),
  }).results;
  const dialectCount = { error: 0, unsupported: 0, searched: 0 };
  dialectPatterns.forEach((p, i) => {
    let node;
    try {
      const t = pyjsonschema.translatePyPattern(p);
      if (t.source === null) node = 'unsupported';
      else {
        const re = new RegExp(t.source, 'v');
        node = DIALECT_STRINGS.map((x) => (re.test(x) ? '1' : '0')).join('');
      }
    } catch (e) {
      node = e.name === 'PyReError' || e.name === 'PyJsonSchemaUnsupported' ? 'error' : `${e.name}: ${e.message}`;
    }
    const py = pyDialect[i];
    dialectCount[py === 'error' || py === 'unsupported' ? py : 'searched'] += 1;
    cases.push({ name: `pattern/dialect/${i} ${JSON.stringify(p)}`, kind: 'string', expected: py, actual: node });
  });
  notes.push(
    `pattern dialect: ${dialectPatterns.length} seeded patterns x ${DIALECT_STRINGS.length} strings — ` +
      `${dialectCount.searched} searched, ${dialectCount.error} refused by re, ${dialectCount.unsupported} outside the shared dialect`,
  );

  // ---- end to end through schema_error -------------------------------------------------------
  const j7 = [];
  const j7add = (name, schema, output) => j7.push({ name, schema: JSON.stringify(schema), output });
  const sOf = (pattern) => ({ properties: { s: { pattern } } });
  // #131's own five probes.
  const ISSUE_131 = [
    ['^\\d+$', '๑๒๓'],
    ['^\\w+$', 'ไทย'],
    ['^a$', 'a\n'],
    ['c\\Z', 'abcZ'],
    ['(?P<x>a)', 'a'],
  ];
  ISSUE_131.forEach(([p, x], i) => j7add(`issue131/${i}`, sOf(p), JSON.stringify({ s: x })));
  // Every construct outside the shared dialect, in a branch the instance never reaches: the
  // refusal is eager, like `check_schema`'s compile.
  const UNSUPPORTED = [
    '(?i)a', '(?i:a)', '(?-i:a)', '(?s).', '(?x) a', '(?a)\\w', '(?<=a)b', '(?<!a)b', '(a)\\1', '(?P<n>a)(?P=n)',
    '(?>a)', 'a*+', 'a++', 'a?+', 'a{1,2}+', '(a)?(?(1)b|c)', '\\N{DIGIT ONE}', '\\N{NO SUCH NAME}', '[\\N{DIGIT ONE}]',
  ];
  UNSUPPORTED.forEach((p, i) => j7add(`unsupported/${i}`, sOf(p), '{"n": 1}'));
  j7add('unsupported/patternProperties-key', { patternProperties: { '(?i)^a': {} } }, '{"n": 1}');
  j7add('unsupported/global-u-is-the-default', sOf('(?u)^a$'), '{"s": "b"}');
  // `patternProperties` keys are `"format": "regex"` from draft 6: a key `re` cannot compile
  // is a SchemaError there even when no property meets it — the bit, compared below.
  const PP_DRAFTS = [
    'http://json-schema.org/draft-04/schema#',
    'http://json-schema.org/draft-06/schema#',
    'http://json-schema.org/draft-07/schema#',
    'https://json-schema.org/draft/2019-09/schema',
    'https://json-schema.org/draft/2020-12/schema',
  ];
  PP_DRAFTS.forEach((d, i) => j7add(`pp-key-compiles/${i}`, { $schema: d, patternProperties: { '(': {} } }, '{}'));
  // #132: the budget, on the issue's pattern, through `pattern` and through `additionalProperties`.
  const BOOM = 'a'.repeat(40) + '!';
  j7add('budget/pattern', sOf('^(a+)+$'), JSON.stringify({ s: BOOM }));
  j7add(
    'budget/additionalProperties',
    { patternProperties: { '^(a+)+$': {} }, additionalProperties: false },
    JSON.stringify({ [BOOM]: 1 }),
  );
  const MANY = Object.fromEntries(Array.from({ length: 300 }, (_, i) => [`k${i}`, `v${i}`]));
  j7add('budget/many-fast-searches', { patternProperties: { '^k\\d+$': { pattern: '^v\\d+$' } } }, JSON.stringify(MANY));
  // #152: a top-level scalar is a JSON document.
  j7add('scalar/string', { type: 'string' }, '"just a string"');
  j7add('scalar/float', { type: 'number' }, '1.0');
  j7add('scalar/null', { type: 'null' }, 'null');
  j7add('scalar/true', { type: 'boolean' }, 'true');
  j7add('scalar/wrong-type', { type: 'integer' }, '"x"');
  j7add('scalar/fenced', { type: 'string' }, 'here:\n```json\n"x"\n```');
  j7add('scalar/prose-is-still-not-json', {}, '42 is the answer');
  j7add('scalar/string-holding-braces', { type: 'object' }, '"see {\\"a\\": 1}"');
  // #153: the offending value, clipped.
  j7add('clip/maxLength', { properties: { x: { maxLength: 10 } } }, JSON.stringify({ x: 'y'.repeat(100000) }));
  j7add('clip/maxItems', { maxItems: 3 }, JSON.stringify(Array.from({ length: 5000 }, () => 1)));
  j7add('clip/unexpected-key', { additionalProperties: false }, JSON.stringify({ ['k'.repeat(5000)]: 1 }));
  j7add('clip/where', { additionalProperties: { type: 'string' } }, JSON.stringify({ ['w'.repeat(300)]: 1 }));
  j7add('clip/short-is-untouched', { properties: { x: { maxLength: 1 } } }, JSON.stringify({ x: 'y'.repeat(150) }));

  const pyJ7 = ctx.runPython(REF, {
    op: 'schema_error',
    cases: j7.map((c) => ({ schema: b64(c.schema), output: b64(c.output) })),
  }).results;
  // A raise renders as `RAISES` on both sides: the two libraries' exception WORDS are ruled
  // elsewhere (`check_schema`); here the bit is the property.
  const j7py = new Map();
  const j7node = new Map();
  j7.forEach((spec, i) => {
    const py = pyJ7[i];
    j7py.set(spec.name, typeof py === 'object' && py !== null ? 'RAISES' : answer(py));
    let node;
    try {
      node = nodeAnswer(contract.schemaError(spec.output, pyjson.parseJson(spec.schema)));
    } catch {
      node = 'RAISES';
    }
    j7node.set(spec.name, node);
    cases.push({ name: `pattern/schema_error/${spec.name}`, kind: 'string', expected: j7py.get(spec.name), actual: node });
  });

  // ---- the absolute half: literals on each side ----------------------------------------------
  // A differential is blind to a regression that lands in BOTH runtimes (dropping the scalar
  // arm, the clip, or the refusal from both is green above). These pin what the answer IS.
  const refusal = (p) =>
    `the pattern ${p} is not supported: this validator refuses inline flags, look-behind, ` +
    'backreferences, atomic groups, possessive quantifiers, conditional groups and \\N{...} escapes';
  const budget = (p) =>
    `the pattern ${p} did not finish within the 500 ms this validator allows a document's patterns; ` +
    'rewrite it so it cannot backtrack catastrophically, as (a+)+$ does';
  const clipped = (text, limit) => {
    const cps = [...text];
    return cps.length <= limit ? text : `${cps.slice(0, limit).join('')}…(${cps.length - limit} more)`;
  };
  const J7_LITERALS = {
    'issue131/0': '(valid)',
    'issue131/1': '(valid)',
    'issue131/2': '(valid)',
    'issue131/3': "JSON does not match schema at 's': 'abcZ' does not match 'c\\\\Z'",
    'issue131/4': '(valid)',
    'unsupported/0': refusal("'(?i)a'"),
    'unsupported/6': refusal("'(?<=a)b'"),
    'unsupported/8': refusal("'(a)\\\\1'"),
    'unsupported/10': refusal("'(?>a)'"),
    'unsupported/11': refusal("'a*+'"),
    'unsupported/15': refusal("'(a)?(?(1)b|c)'"),
    'unsupported/17': refusal("'\\\\N{NO SUCH NAME}'"),
    'unsupported/patternProperties-key': refusal("'(?i)^a'"),
    'unsupported/global-u-is-the-default': "JSON does not match schema at 's': 'b' does not match '(?u)^a$'",
    'budget/pattern': budget("'^(a+)+$'"),
    'budget/additionalProperties': budget("'^(a+)+$'"),
    'budget/many-fast-searches': '(valid)',
    'scalar/string': '(valid)',
    'scalar/float': '(valid)',
    'scalar/null': '(valid)',
    'scalar/true': '(valid)',
    'scalar/wrong-type': "JSON does not match schema at 'root': 'x' is not of type 'integer'",
    'scalar/fenced': '(valid)',
    'scalar/prose-is-still-not-json': 'output was not parseable JSON: no JSON object found in output',
    'scalar/string-holding-braces': `JSON does not match schema at 'root': 'see {"a": 1}' is not of type 'object'`,
    'clip/maxLength': `JSON does not match schema at 'x': ${clipped(`'${'y'.repeat(100000)}'`, 200)} is too long`,
    'clip/maxItems': `JSON does not match schema at 'root': ${clipped(`[${Array(5000).fill('1').join(', ')}]`, 200)} is too long`,
    'clip/unexpected-key': `JSON does not match schema at 'root': ${clipped(`Additional properties are not allowed ('${'k'.repeat(5000)}' was unexpected)`, 1000)}`,
    'clip/where': `JSON does not match schema at '${clipped('w'.repeat(300), 200)}': 1 is not of type 'string'`,
    'clip/short-is-untouched': `JSON does not match schema at 'x': '${'y'.repeat(150)}' is too long`,
  };
  for (const [specName, sentence] of Object.entries(J7_LITERALS)) {
    cases.push({
      name: `pattern/schema_error/${specName}: the sentence, as a literal on each side`,
      kind: 'json',
      expected: { python: sentence, node: sentence },
      actual: { python: j7py.get(specName) ?? null, node: j7node.get(specName) ?? null },
    });
  }
  // Every refused construct answers the sentence — not a raise, not a verdict — on each side.
  cases.push({
    name: `pattern/unsupported: all ${UNSUPPORTED.length} constructs answer the one sentence on each side`,
    kind: 'json',
    expected: { python: UNSUPPORTED.map(() => true), node: UNSUPPORTED.map(() => true) },
    actual: {
      python: UNSUPPORTED.map((_, i) => (j7py.get(`unsupported/${i}`) ?? '').startsWith('the pattern ')),
      node: UNSUPPORTED.map((_, i) => (j7node.get(`unsupported/${i}`) ?? '').startsWith('the pattern ')),
    },
  });
  // The refusal bit for an uncompilable `patternProperties` key, per draft: data under draft 4.
  cases.push({
    name: 'pattern/pp-key-compiles: an uncompilable patternProperties key raises from draft 6, on each side',
    kind: 'json',
    expected: { python: [false, true, true, true, true], node: [false, true, true, true, true] },
    actual: {
      python: PP_DRAFTS.map((_, i) => j7py.get(`pp-key-compiles/${i}`) === 'RAISES'),
      node: PP_DRAFTS.map((_, i) => j7node.get(`pp-key-compiles/${i}`) === 'RAISES'),
    },
  });
  notes.push(`#131 #132 #152 #153: ${j7.length} schema_error cases, ${Object.keys(J7_LITERALS).length + 2} pinned as literals on each side`);

  return { cases, notes };
}
