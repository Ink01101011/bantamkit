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

  cases.push({
    name: 'ruling: an invalid SCHEMA raises a different sentence',
    kind: 'string',
    expected: answer(
      ctx.runPython(REF, {
        op: 'schema_error',
        cases: [{ schema: b64('{"type": "nosuch"}'), output: b64('{"a": 1}') }],
      }).results[0],
    ),
    actual: (() => {
      try {
        contract.schemaError('{"a": 1}', pyjson.parseJson('{"type": "nosuch"}'));
        return '(no exception)';
      } catch (e) {
        return `${e.name}: ${e.message}`;
      }
    })(),
    ruling:
      "`jsonschema.validate` runs `cls.check_schema(schema)` before it looks at the instance, " +
      'so an invalid caller schema raises `SchemaError` with the METASCHEMA\'s own sentence — ' +
      'and `schema_error` catches only `ValidationError`, so it escapes `validate_json` to the ' +
      'caller. Reproducing that means shipping and running the 2020-12 metaschema. This port ' +
      'raises `PyJsonSchemaUnsupported` at the construct instead. BOTH RUNTIMES REFUSE and ' +
      'neither returns a wrong answer; only the words differ. Registered against runtime-py as ' +
      'a defect in its own right: a tool that takes a schema from the model should not let an ' +
      'exception out of the tool call.',
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
    expected: answer(
      ctx.runPython(REF, {
        op: 'schema_error',
        cases: [{ schema: b64('{"minimum": 1.0}'), output: b64('[0]') }],
      }).results[0],
    ),
    actual: String(contract.schemaError('[0]', { minimum: 1.0 })),
    ruling:
      'A JS number carries no record of the decimal point its JSON text had, so a schema that ' +
      'has already been through an SDK parser reaches this port with `1.0` indistinguishable ' +
      'from `1`, and the sentence says `the minimum of 1` where Python says `1.0`. The exact ' +
      'route exists and is used everywhere the raw bytes are still in hand — `pyjson.parseJson`, ' +
      'which is what every non-ruled case above goes through. The loss is confined to ' +
      '`fromJs`, and measured over the whole asset pack it is unreachable there: no shipped ' +
      'schema holds a non-integral number.',
  });

  const pyRegex = ctx.runPython(REF, {
    op: 'schema_error',
    cases: [{ schema: b64('{"pattern": "^\\\\d+$"}'), output: b64('["\\u0e51\\u0e52\\u0e53"]') }],
  }).results[0];
  cases.push({
    name: 'ruling: python re and JS RegExp are different languages',
    kind: 'string',
    expected: answer(pyRegex),
    actual: String(contract.schemaError('["๑๒๓"]', pyjson.parseJson('{"pattern": "^\\\\d+$"}'))),
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
