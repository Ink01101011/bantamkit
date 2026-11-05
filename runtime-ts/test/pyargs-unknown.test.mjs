/**
 * An unknown top-level argument is refused by name on every served tool (#133).
 *
 * User ruling 2026-10-15 (job67, J67-1). `validateArguments` refuses a key the tool's model
 * does not name, after the lone-surrogate check and before anything else, with the sentence
 * the reference's `_ArgMetadata.validate_arguments` says: `unknown argument '<key>'; known:
 * <fields in schema order>`. These nodes tie the model's field order to the asset's
 * `parameters.properties` order (the `known:` list is read off the model) and pin that every
 * served asset closes its top level. `tools/conformance/suites/wire.mjs` pins the wire.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const repoRoot = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const { ARG_MODELS, unknownArgument, validateArguments } = await import('../dist/mcp/pyargs.js');
const { MCP_TOOLS } = await import('../dist/mcp/server.js');
const { fromJs } = await import('../dist/pyjson.js');

const asset = (name) => JSON.parse(readFileSync(join(repoRoot, 'assets', 'tools', `${name}.json`), 'utf8'));
const known = (name) => {
  const keys = Object.keys(asset(name).parameters.properties);
  return keys.length === 0 ? '(none)' : keys.join(', ');
};

test('every served asset advertises additionalProperties false at the top level', () => {
  assert.equal(MCP_TOOLS.length, 16); // + memory_queries (#207 amendment 3), shiftwork_draft (#226)
  for (const name of MCP_TOOLS) assert.equal(asset(name).parameters.additionalProperties, false, name);
});

test('every served model lists its fields in the asset order', () => {
  for (const name of MCP_TOOLS) {
    assert.deepEqual(
      ARG_MODELS[name].fields.map((f) => f.name),
      Object.keys(asset(name).parameters.properties),
      name,
    );
  }
});

test('every served tool refuses an unknown key by name', () => {
  for (const name of MCP_TOOLS) {
    assert.throws(
      () => validateArguments(ARG_MODELS[name], fromJs({ bogus: 1 })),
      { message: `unknown argument 'bogus'; known: ${known(name)}` },
      name,
    );
  }
});

test('the first unknown key in arrival order is named, ahead of a type error', () => {
  const model = ARG_MODELS.memory_recall;
  assert.equal(unknownArgument(model, fromJs({ query: 'a', zz: 1, aa: 2 })), "unknown argument 'zz'; known: query, k, include_archived, file, outcome");
  assert.throws(() => validateArguments(model, fromJs({ query: 123, bogus: 1 })), {
    message: "unknown argument 'bogus'; known: query, k, include_archived, file, outcome",
  });
  assert.equal(unknownArgument(model, fromJs({ query: 'a', constructor: 1 })), "unknown argument 'constructor'; known: query, k, include_archived, file, outcome");
});

test('known keys alone still validate', () => {
  const bound = validateArguments(ARG_MODELS.memory_recall, fromJs({ query: 'a', k: 2 }));
  assert.equal(bound.get('query').v, 'a');
  assert.equal(unknownArgument(ARG_MODELS.build_identity, fromJs({})), null);
});

test('job78: bantamkit_status takes `detail: bool = False` — absent binds the default, null is bool_type', () => {
  // Frames measured on pydantic 2.13 with `create_model(..., detail=(bool, False))`: NOT
  // `bool | None`, so an explicit `null` is refused rather than read as the default.
  const model = ARG_MODELS.bantamkit_status;
  const refusal = (args) => {
    try {
      return validateArguments(model, fromJs(args));
    } catch (error) {
      return error.detail;
    }
  };
  assert.deepEqual(refusal({ detail: 'yes' }).get('detail'), { t: 'bool', v: true });
  assert.deepEqual(refusal({}).get('detail'), { t: 'null' });
  assert.equal(
    refusal({ detail: null }),
    '1 validation error for bantamkit_statusArguments\ndetail\n' +
      '  Input should be a valid boolean [type=bool_type, input_value=None, input_type=NoneType]',
  );
  assert.equal(unknownArgument(model, fromJs({ verbose: true })), "unknown argument 'verbose'; known: detail");
});
