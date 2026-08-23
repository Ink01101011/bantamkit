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
import { readFileSync } from 'node:fs';
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
  const realCheckpoints = {
    live: join(repoRoot, '.shiftwork', 'job38-npx-public-install', 'checkpoint.json'),
    example: join(repoRoot, 'tools', 'shiftwork', 'example-codefix-checkpoint.json'),
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

  const pySchemaErrors = ctx.runPython(REF, {
    op: 'schema_error',
    cases: specs.map((s) => ({ schema: b64(s.schema), output: b64(s.output) })),
  }).results;

  let raised = 0;
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
    cases.push({
      name: `schema_error/${spec.name}`,
      kind: 'string',
      expected: answer(expected),
      actual: typeof actual === 'string' || actual === null ? answer(actual === null ? null : b64(actual)) : answer(actual),
    });
  }
  notes.push(`${specs.length} schema_error cases; ${raised} of them are an EXCEPTION on both sides`);

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
  // NOW both runtimes REFUSE all 53 of these and only the WORDS differ: Python quotes the
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
        'measured over 53 shapes and not generalised from one: the previous wording here ' +
        'asserted the general case from `{"type": "nosuch"}` and N8 found five ' +
        'counter-examples inside it.',
    });
  }
  // THE RULED CASES ABOVE PIN THE WORDING, NOT THE REFUSAL, and that distinction is the
  // trap N8 found in this file: a `ruling` case fails only when the two sides MATCH, so a
  // port that went back to answering `{"valid": true}` would still "differ" from Python's
  // SchemaError and every one of those 53 would stay green. This case is the other half and
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

  cases.push({
    name: 'ruling: a Python-only regex in a branch that never fires',
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
    ruling:
      'THE PRICE OF CHECKING `pattern` EAGERLY, stated rather than hidden. `check_schema` ' +
      "compiles every `pattern` (the metaschema's `\"format\": \"regex\"`), which is how " +
      '`{"pattern": "("}` became a refusal on both sides instead of `{"valid": true}` here. ' +
      "The same eagerness makes this port refuse `(?P<x>…)` — valid `re`, invalid `RegExp` — " +
      'even though the instance has no `s` and the keyword would never have fired. Python ' +
      'answers `(valid)`. This is the SAME divergence as the `python re and JS RegExp` ruling ' +
      'below, moved earlier; the trade taken is that a refusal in an unreached branch beats ' +
      'answering `{"valid": true}` for a pattern that is not one. Porting `sre_compile` is ' +
      'what would close it.',
  });

  cases.push({
    name: 'ruling: $ref is not resolved',
    kind: 'string',
    expected: answer(
      ctx.runPython(REF, {
        op: 'schema_error',
        cases: [{
          schema: b64('{"$defs": {"x": {"type": "integer"}}, "properties": {"a": {"$ref": "#/$defs/x"}}}'),
          output: b64('{"a": "s"}'),
        }],
      }).results[0],
    ),
    actual: (() => {
      try {
        return String(contract.schemaError(
          '{"a": "s"}',
          pyjson.parseJson('{"$defs": {"x": {"type": "integer"}}, "properties": {"a": {"$ref": "#/$defs/x"}}}'),
        ));
      } catch (e) {
        return `${e.name}: ${e.message}`;
      }
    })(),
    ruling:
      '`$ref` needs a reference resolver and a registry. Measured over the whole asset pack ' +
      '(`assets/**/*.json`): zero occurrences of `$ref`, `$dynamicRef`, `unevaluatedItems` and ' +
      '`unevaluatedProperties`, so nothing bantamkit ships reaches this. A caller-supplied ' +
      'schema can, and this port refuses by name rather than validating a document against ' +
      'half a schema and reporting it valid — which is what silently skipping the keyword ' +
      'would do.',
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
  cases.push({
    name: 'ruling: python re and JS RegExp are different languages',
    kind: 'string',
    expected: answer(pyRegex),
    actual: nodeAnswer(contract.schemaError(REGEX_OUTPUT.replace('\\u0e51\\u0e52\\u0e53', '๑๒๓'), pyjson.parseJson(REGEX_SCHEMA))),
    ruling:
      "Python's `\\d` matches every Unicode decimal digit and JS's matches [0-9], so Thai " +
      'digits satisfy the pattern in Python and fail it here. `$` before a trailing newline, ' +
      '`(?P<name>…)`, `\\A` and `\\Z` diverge too. The asset pack holds exactly ONE `pattern` ' +
      '(`assets/tools/memory_save.json`) and it is inside the common core; a caller-supplied ' +
      'pattern is not guaranteed to be. Fixing this means porting `sre_compile`, which is a ' +
      'larger surface than the whole validator.',
  });

  return { cases, notes };
}
