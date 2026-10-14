/**
 * The `jsonschema` seam: `validator_for(schema)(schema).iter_errors` + `exceptions.best_match`.
 *
 * WHY THIS IS NOT AJV — measured, not assumed. Over the 288-case corpus in
 * `tools/conformance/suites/validate.mjs`, ajv 8.20.0 and jsonschema 4.26.0 agree on
 * WHETHER a document is valid in 288/288 cases, and on WHAT TO SAY ABOUT IT in **0 of 281**
 * invalid ones. Not one message matches; ajv's own error list does not even CONTAIN
 * Python's sentence anywhere in 281/281. Beyond the wording, ajv's error count differs in
 * 28/281 (`additionalProperties` fires once per extra key where jsonschema fires once and
 * names them all), its first error points at a different instance path in 11/281 and at a
 * different KEYWORD in 19/281 (`anyOf`, `oneOf` and `contains` become `type`). The one bit
 * ajv would contribute — valid or not — is the one bit that is not the product, and it is
 * a bit this file has to compute anyway on the way to the sentence. So ajv buys nothing and
 * costs a runtime dependency; the whole keyword vocabulary is 286 lines of Python
 * (`jsonschema/_keywords.py`), which is smaller than the translation layer would be.
 *
 * WHAT IS IMPLEMENTED (job65, #125/#126; before it this file was 2020-12 only and RAISED on
 * `$ref`, `$dynamicRef`, `$recursiveRef`, `unevaluatedItems` and `unevaluatedProperties`).
 *
 * THE DIALECT IS READ FROM `$schema`, as `jsonschema.validators.validator_for` reads it:
 * the URI is normalised the way `_META_SCHEMAS` normalises its keys —
 * `urlsplit(uri).geturl()`, which lowercases the scheme and drops an EMPTY fragment or
 * query, so `…/draft-07/schema#` and `…/draft-07/schema` are one key and `https://…/draft-07`
 * or a trailing slash are not — and an unknown URI, or no `$schema`, is draft 2020-12 (the
 * reference warns and uses the latest draft). Drafts 4, 6, 7, 2019-09 and 2020-12 each get
 * their own keyword table and type checker (`1.0` is an `integer` from draft 6 on, not in 4),
 * and from draft 7 back `$ref` silences its siblings (`_legacy_keywords.ignore_ref_siblings`).
 * Every subschema re-dispatches on its OWN `$schema` with the enclosing dialect as the
 * default, because `Validator.evolve` does. Draft 3 is the one dialect the two runtimes
 * REFUSE, with one shared sentence (`contract.py`'s pre-scan says the same words).
 *
 * `$ref` RESOLVES INSIDE THE ONE RESOURCE A CALLER SCHEMA IS. `#`, a JSON pointer `#/…`
 * (percent-decoded as a whole, then `~1`/`~0` per segment, `int()` for a list index — the
 * order `referencing`'s `Resource.pointer` uses) and a plain-name `#anchor` (`$anchor`,
 * plus `$dynamicAnchor` under 2020-12) all resolve against the root document. `$dynamicRef`
 * is the same lookup because `_keywords.dynamicRef` IS `_validate_reference(ref)` in 4.26,
 * and `$recursiveRef` is the root because `lookup_recursive_ref` can only land on the root
 * when there is one resource. What is NOT here is a second resource: a reference with a
 * scheme, host, path or query, or a schema that embeds a `$id` (`id` under draft 4) below
 * its root, is refused BEFORE validation with one sentence both runtimes print — a
 * `PyJsonSchemaRefusal`, which `contract.schemaError` turns into the `{valid: false,
 * feedback}` answer rather than an exception, because a model handed that sentence can act
 * on it and a model handed `isError` cannot. A pointer to nowhere or an unknown anchor is
 * the same refusal, found lazily where Python's `PointerToNowhere`/`NoSuchAnchor` find it.
 *
 * `unevaluatedItems`/`unevaluatedProperties` carry BOTH walkers: `_utils.find_evaluated_*`
 * for 2020-12 and `_legacy_keywords.find_evaluated_*` for 2019-09, which differ in more than
 * `prefixItems` — the 2019 property walker reads the KEYS of an `additionalProperties`
 * subschema as property names, and this port reproduces that because the sentence does.
 * `format` is implemented as the no-op it is — `jsonschema.validate` passes no
 * `format_checker`, so the keyword can never produce an error on this path.
 *
 * THE CALLER SCHEMA IS CHECKED FIRST, as it is in the reference. `jsonschema.validate` calls
 * `cls.check_schema(schema)` before it looks at the instance, so an invalid schema raises
 * `SchemaError` — and `contract.schema_error` catches only `ValidationError`, so that
 * exception escapes `validate_json` to the caller. This port used NOT to run it, and the
 * consequence was not a different sentence but a WRONG ANSWER: the keywords below are
 * written to skip a schema value they do not recognise, which is correct inside
 * `iter_errors` and is `{"valid": true}` at a tool boundary. Measured by N8 on the wire,
 * `{"required": "a"}`, `{"required": 3}`, `{"properties": ["a"]}` and
 * `{"additionalProperties": [1]}` all answered `{"valid": true}`, and `{"type": 3}` answered
 * `{"valid": false}` with a sentence about a schema that is not a schema.
 *
 * `checkSchema` below is the fix and it is NOT the metaschema — the metaschemas are several
 * documents wired together with `$ref`/`$dynamicRef` across resources, which is the second
 * resource this file does not implement. It is the keyword SHAPE table, applied recursively
 * and gated per dialect, because a keyword the dialect does not know is DATA to its
 * metaschema: `{"if": 3}` is a `SchemaError` under draft 7 and a valid schema under draft 4.
 * Measured over 50 malformed shapes under 2020-12 and 121 shapes under each of the five
 * dialects: the refusal bit matches the reference on every row the suite carries, and only
 * the WORDS differ. Registered and NOT fixed here: `validate_json` letting an exception out
 * on caller input is a `runtime-py` defect (invariant 8).
 */
import { cmpCodepoint } from './memory/pyfs.js';
import { reprValue, type PyValue } from './pyjson.js';

export class PyJsonSchemaUnsupported extends Error {
  constructor(message: string) {
    super(`jsonschema seam: ${message}`);
    this.name = 'PyJsonSchemaUnsupported';
  }
}

/**
 * A schema the validator will not resolve, answered — not raised. `contract.schemaError`
 * returns the message as the feedback sentence, so `validate_json` says `{"valid": false,
 * "feedback": …}` where it used to say `isError` (#125). The Python side prints the same
 * sentence from `contract._unsupported_schema` and from the `referencing` exceptions.
 */
export class PyJsonSchemaRefusal extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PyJsonSchemaRefusal';
  }
}

// ------------------------------------------------------------------------ the dialect

/** The drafts this port validates. Draft 3 is looked up so it can be refused by name. */
export type Draft = 4 | 6 | 7 | 2019 | 2020;

const DRAFT_BY_URI: ReadonlyMap<string, Draft | 3> = new Map<string, Draft | 3>([
  ['http://json-schema.org/draft-03/schema', 3],
  ['http://json-schema.org/draft-04/schema', 4],
  ['http://json-schema.org/draft-06/schema', 6],
  ['http://json-schema.org/draft-07/schema', 7],
  ['https://json-schema.org/draft/2019-09/schema', 2019],
  ['https://json-schema.org/draft/2020-12/schema', 2020],
]);

/** `urllib.parse.uses_netloc`, which decides whether `urlunsplit` re-inserts `//`. */
const USES_NETLOC = new Set([
  '', 'ftp', 'http', 'gopher', 'nntp', 'telnet', 'imap', 'wais', 'file', 'mms', 'https', 'shttp',
  'snews', 'prospero', 'rtsp', 'rtsps', 'rtspu', 'rsync', 'svn', 'svn+ssh', 'sftp', 'nfs', 'git',
  'git+ssh', 'ws', 'wss', 'itms-services',
]);

/**
 * `urllib.parse.urlsplit(uri).geturl()` — `_utils.URIDict.normalize`, the function every
 * `$schema` goes through before `_META_SCHEMAS` is consulted. 3.12 strips leading C0/space,
 * removes every tab/CR/LF, lowercases the scheme, and `urlunsplit` drops an empty query and
 * an empty fragment. Measured in `tools/conformance/suites/validate.mjs` (`dialect/…`).
 */
export function pyUrlNormalize(uri: string): string {
  let url = uri.replace(/^[\u0000- ]+/, '').replace(/[\t\r\n]/g, '');
  let scheme = '';
  const colon = url.indexOf(':');
  if (colon > 0 && /^[A-Za-z][A-Za-z0-9+.-]*$/.test(url.slice(0, colon))) {
    scheme = url.slice(0, colon).toLowerCase();
    url = url.slice(colon + 1);
  }
  let netloc = '';
  if (url.startsWith('//')) {
    const rel = url.slice(2).search(/[/?#]/);
    const stop = rel === -1 ? url.length : 2 + rel;
    netloc = url.slice(2, stop);
    url = url.slice(stop);
  }
  let fragment = '';
  const hash = url.indexOf('#');
  if (hash !== -1) {
    fragment = url.slice(hash + 1);
    url = url.slice(0, hash);
  }
  let query = '';
  const q = url.indexOf('?');
  if (q !== -1) {
    query = url.slice(q + 1);
    url = url.slice(0, q);
  }
  if (netloc || (scheme && USES_NETLOC.has(scheme) && !url.startsWith('//'))) {
    if (url && !url.startsWith('/')) url = `/${url}`;
    url = `//${netloc}${url}`;
  }
  if (scheme) url = `${scheme}:${url}`;
  if (query) url += `?${query}`;
  if (fragment) url += `#${fragment}`;
  return url;
}

const draft3Sentence = (uri: string): string =>
  `the schema's $schema ${JSON.stringify(uri)} names draft 3, which this validator does not ` +
  'support (draft-04, draft-06, draft-07, 2019-09 and 2020-12 are)';

/**
 * `validator_for(schema, default=fallback)`: the dialect a (sub)schema is validated under.
 * The root falls back to 2020-12 (`_LATEST_VERSION`); a subschema falls back to the
 * enclosing dialect, which is what `Validator.evolve` passes as `default`.
 */
function dialectOf(schema: PyValue | boolean, fallback: Draft): Draft {
  const v = get(schema, '$schema');
  if (v === undefined) return fallback;
  // `schema["$schema"] not in _META_SCHEMAS` → `urlsplit(3)` → AttributeError. Both raise.
  if (v.t !== 'str') throw new PyJsonSchemaUnsupported(`$schema must be a string, got ${v.t}`);
  const found = DRAFT_BY_URI.get(pyUrlNormalize(v.v));
  if (found === 3) throw new PyJsonSchemaRefusal(draft3Sentence(v.v));
  return found ?? fallback;
}

/**
 * `jsonschema.exceptions.ValidationError`, narrowed to the fields the relevance heuristic
 * and `schema_error` read.
 *
 * `path` is the RELATIVE path, which is what `relevance` sorts on, and `parent` is set only
 * for the context errors an `anyOf`/`oneOf` carries. `absolutePath` walks the chain, which
 * is what `schema_error` interpolates. Keeping the two apart is not pedantry: `best_match`
 * ranks context errors by their relative paths and then `schema_error` prints an absolute
 * one, and a port that conflated them would name the wrong field inside every `anyOf`.
 *
 * `draft` is the dialect the keyword ran under — `error._type_checker`, which
 * `_matches_type` consults, and the one place the dialect reaches `best_match`.
 */
export interface PyValidationError {
  message: string;
  validator: string | null;
  instance: PyValue;
  /** The (sub)schema the keyword lives in. `null` stands for a `false` schema. */
  schema: PyValue | boolean;
  path: (string | number)[];
  context: PyValidationError[];
  parent: PyValidationError | null;
  draft: Draft;
}

export function absolutePath(error: PyValidationError): (string | number)[] {
  return error.parent === null ? error.path : [...absolutePath(error.parent), ...error.path];
}

// ---------------------------------------------------------------------------- py helpers

const isDict = (v: PyValue | boolean): v is { t: 'dict'; v: Map<string, PyValue> } =>
  typeof v !== 'boolean' && v.t === 'dict';

const get = (schema: PyValue | boolean, key: string): PyValue | undefined =>
  isDict(schema) ? schema.v.get(key) : undefined;

const cpLength = (s: string): number => [...s].length;

const asNumber = (v: PyValue): number => (v.t === 'int' ? Number(v.v) : (v as { v: number }).v);

/** `jsonschema._utils.equal`: JSON equality that refuses `True == 1`. */
export function pyEqual(a: PyValue, b: PyValue): boolean {
  if (a.t === 'str' || b.t === 'str') return a.t === 'str' && b.t === 'str' && a.v === b.v;
  if (a.t === 'list' && b.t === 'list') {
    return a.v.length === b.v.length && a.v.every((x, i) => pyEqual(x, b.v[i]!));
  }
  if (a.t === 'dict' && b.t === 'dict') {
    if (a.v.size !== b.v.size) return false;
    for (const [k, v] of a.v) {
      const other = b.v.get(k);
      if (other === undefined || !pyEqual(v, other)) return false;
    }
    return true;
  }
  // `unbool`: True and False become unique sentinels, so they equal nothing but themselves.
  if (a.t === 'bool' || b.t === 'bool') return a.t === 'bool' && b.t === 'bool' && a.v === b.v;
  if (a.t === 'null' || b.t === 'null') return a.t === 'null' && b.t === 'null';
  if (a.t === 'int' && b.t === 'int') return a.v === b.v;
  if ((a.t === 'int' || a.t === 'float') && (b.t === 'int' || b.t === 'float')) {
    return asNumber(a) === asNumber(b);
  }
  return false;
}

/**
 * The draft type checkers.
 *
 * Two Python-isms carry: `bool` is not an `int`, so `true` is neither `integer` nor
 * `number`; and draft 6 onward redefines `integer` to accept a float with no fractional
 * part, so `1.0` IS an integer — under draft 6+ only. `draft4_type_checker` is
 * `is_integer` alone, and `{"type": "integer"}` refuses `1.0` there.
 */
function isType(instance: PyValue, type: string, draft: Draft = 2020): boolean {
  switch (type) {
    case 'array':
      return instance.t === 'list';
    case 'boolean':
      return instance.t === 'bool';
    case 'integer':
      if (instance.t === 'int') return true;
      return draft !== 4 && instance.t === 'float' && Number.isInteger(instance.v);
    case 'null':
      return instance.t === 'null';
    case 'number':
      return instance.t === 'int' || instance.t === 'float';
    case 'object':
      return instance.t === 'dict';
    case 'string':
      return instance.t === 'str';
    default:
      // Python never reaches this: `check_schema` rejects the schema first. See the module
      // header — both runtimes refuse, with different words.
      throw new PyJsonSchemaUnsupported(`undefined type check ${JSON.stringify(type)}`);
  }
}

// --------------------------------------------------------------------------- the engine

/** What a keyword needs beyond its own value: the root resource and the dialect in force. */
interface Ctx {
  root: PyValue;
  draft: Draft;
  /** The ROOT's dialect — anchors are found by the resource's specification, not the leaf's. */
  rootDraft: Draft;
}

type Emit = (
  message: string,
  extra?: { validator?: string; context?: PyValidationError[] },
) => PyValidationError;

/** One keyword's implementation, transcribed from `jsonschema/_keywords.py` and `_legacy_keywords.py`. */
type Keyword = (
  value: PyValue,
  instance: PyValue,
  schema: PyValue | boolean,
  emit: Emit,
  descend: Descend,
  ctx: Ctx,
) => PyValidationError[];

type Descend = (
  instance: PyValue,
  schema: PyValue | undefined,
  path?: string | number,
) => PyValidationError[];

const falseSchemaError = (instance: PyValue, draft: Draft): PyValidationError => ({
  message: `False schema does not allow ${reprValue(instance)}`,
  validator: null,
  instance,
  schema: false,
  path: [],
  context: [],
  parent: null,
  draft,
});

/**
 * `applicable_validators`: for 2019-09 and 2020-12 it is `methodcaller("items")` — plain
 * dict order, which for a JSON-parsed schema is DOCUMENT order; from draft 7 back it is
 * `_legacy_keywords.ignore_ref_siblings`, which returns `$ref` ALONE when the schema has
 * one. That order decides which error comes first, and `best_match` breaks ties by taking
 * the first maximum, so it is load-bearing.
 */
function applicable(schema: Map<string, PyValue>, draft: Draft): Iterable<[string, PyValue]> {
  if (draft === 4 || draft === 6 || draft === 7) {
    const ref = schema.get('$ref');
    // `schema.get("$ref") is not None` — a JSON null counts as absent.
    if (ref !== undefined && ref.t !== 'null') return [['$ref', ref]];
  }
  return schema;
}

function iterErrors(instance: PyValue, schema: PyValue | boolean, ctx?: Ctx): PyValidationError[] {
  const c = ctx ?? rootCtx(schema);
  if (schema === true) return [];
  if (schema === false) return [falseSchemaError(instance, c.draft)];
  if (schema.t === 'bool') return iterErrors(instance, schema.v, c);
  if (schema.t !== 'dict') {
    throw new PyJsonSchemaUnsupported(`a schema must be an object or a boolean, got ${schema.t}`);
  }
  // `Validator.evolve` re-dispatches on the subschema's own `$schema`, defaulting to the
  // enclosing class.
  const draft = dialectOf(schema, c.draft);
  const here: Ctx = draft === c.draft ? c : { ...c, draft };
  const table = KEYWORDS_BY_DRAFT[draft];

  const out: PyValidationError[] = [];
  for (const [keyword, value] of applicable(schema.v, draft)) {
    const fn = table[keyword];
    if (fn === undefined) continue; // an annotation, or a keyword of another dialect — jsonschema skips it too
    const emit: Emit = (message, extra = {}) => ({
      message,
      validator: extra.validator ?? keyword,
      instance,
      schema,
      path: [],
      context: extra.context ?? [],
      parent: null,
      draft,
    });
    const descend: Descend = (childInstance, childSchema, path) => {
      if (childSchema === undefined) return [];
      // `Validator.descend` handles a boolean subschema and RETURNS, before the loop that
      // prepends `path`. So `{"properties": {"k": false}}` reports at `root` and not at `k`.
      // Measured against Python; a port that prepended here would name a field Python does
      // not name.
      if (childSchema.t === 'bool') return iterErrors(childInstance, childSchema.v, here);
      const errors = iterErrors(childInstance, childSchema, here);
      if (path !== undefined) for (const e of errors) e.path.unshift(path);
      return errors;
    };
    out.push(...fn(value, instance, schema, emit, descend, here));
  }
  return out;
}

const isValid = (instance: PyValue, schema: PyValue | boolean, ctx: Ctx): boolean =>
  iterErrors(instance, schema, ctx).length === 0;

/** The context a bare `iterErrors(instance, schema)` call runs under: the schema is the root. */
function rootCtx(schema: PyValue | boolean): Ctx {
  const draft = dialectOf(schema, 2020);
  const root: PyValue = typeof schema === 'boolean' ? { t: 'bool', v: schema } : schema;
  return { root, draft, rootDraft: draft };
}

/** `extras_msg`: `"'a', 'b'", "were"`. */
function extrasMsg(extras: string[]): [string, string] {
  return extrasMsgValues(extras.map((e) => ({ t: 'str', v: e })));
}

function extrasMsgValues(extras: PyValue[]): [string, string] {
  return [extras.map(reprValue).join(', '), extras.length === 1 ? 'was' : 'were'];
}

/** `find_additional_properties`, in instance order. */
function findAdditionalProperties(instance: Map<string, PyValue>, schema: PyValue | boolean): string[] {
  const properties = get(schema, 'properties');
  const known = properties && properties.t === 'dict' ? properties.v : new Map<string, PyValue>();
  const pp = get(schema, 'patternProperties');
  const patterns = pp && pp.t === 'dict' ? [...pp.v.keys()].join('|') : '';
  const out: string[] = [];
  for (const property of instance.keys()) {
    if (known.has(property)) continue;
    if (patterns && reSearch(patterns, property)) continue;
    out.push(property);
  }
  return out;
}

/**
 * `re.search(pattern, string)`.
 *
 * RULING. Python's `re` and JS's `RegExp` are different languages past the common core:
 * `\d` is Unicode-wide in Python and ASCII-only in JS, `$` matches before a trailing newline
 * in Python and not in JS, and `(?P<x>…)`/`\Z`/`\A` are Python-only syntax. The asset pack
 * holds exactly one `pattern` (`assets/tools/memory_save.json`), which is inside the common
 * core; a caller-supplied schema is not guaranteed to be. Carried as a ruled case rather
 * than fixed, because fixing it means porting `sre_compile`.
 */
function reSearch(pattern: string, text: string): boolean {
  let re: RegExp;
  try {
    re = new RegExp(pattern, 'u');
  } catch {
    try {
      re = new RegExp(pattern);
    } catch (e) {
      throw new PyJsonSchemaUnsupported(
        `pattern ${JSON.stringify(pattern)} is not a JS regular expression: ${(e as Error).message}`,
      );
    }
  }
  return re.test(text);
}

const sortedByStr = (names: string[]): string[] => [...names].sort(cmpCodepoint);

/** Python truthiness for a decoded JSON value: `not aP`, `if uI`. */
function pyTruthy(value: PyValue): boolean {
  switch (value.t) {
    case 'null':
      return false;
    case 'bool':
      return value.v;
    case 'int':
      return value.v !== 0n;
    case 'float':
      return value.v !== 0;
    case 'str':
      return value.v !== '';
    case 'list':
      return value.v.length > 0;
    case 'dict':
      return value.v.size > 0;
  }
}

// ------------------------------------------------------------------- the one resource

const REF_KEYWORDS = ['$ref', '$dynamicRef', '$recursiveRef'];

/** The keywords whose value is a schema, in ANY dialect — the walk the pre-scan takes. */
const WALK_SUBSCHEMA = new Set([
  'additionalItems', 'additionalProperties', 'contains', 'else', 'if', 'items', 'not',
  'propertyNames', 'then', 'unevaluatedItems', 'unevaluatedProperties',
]);
/** …whose value is an object whose VALUES are schemas (or, for `dependencies`, string lists). */
const WALK_MAP = new Set(['$defs', 'definitions', 'dependencies', 'dependentSchemas', 'patternProperties', 'properties']);
/** …whose value is an array of schemas. */
const WALK_LIST = new Set(['allOf', 'anyOf', 'oneOf', 'prefixItems']);

/**
 * Every subschema of `schema`, root first, in document order, with its path in the form
 * the refusal sentence prints. Structural, not blind: a PROPERTY named `$ref` is not a
 * reference, and this walk never mistakes it for one. `contract.py`'s `_subschemas` is the
 * same walk in the same order, which is what makes the two sentences name the same place.
 */
function* subschemas(schema: PyValue, path = ''): Generator<[string, Map<string, PyValue>]> {
  if (schema.t !== 'dict') return;
  yield [path, schema.v];
  for (const [k, v] of schema.v) {
    const at = path === '' ? k : `${path}/${k}`;
    if (k === 'items' && v.t === 'list') {
      for (let i = 0; i < v.v.length; i += 1) yield* subschemas(v.v[i]!, `${at}/${i}`);
    } else if (WALK_SUBSCHEMA.has(k)) {
      yield* subschemas(v, at);
    } else if (WALK_MAP.has(k) && v.t === 'dict') {
      for (const [n, x] of v.v) yield* subschemas(x, `${at}/${n}`);
    } else if (WALK_LIST.has(k) && v.t === 'list') {
      for (let i = 0; i < v.v.length; i += 1) yield* subschemas(v.v[i]!, `${at}/${i}`);
    }
  }
}

/**
 * The eager half of the one-resource rule (#125), run BEFORE `checkSchema` as the Python
 * pre-scan runs before `check_schema`. Three refusals, in document order, each one sentence
 * that `contract._unsupported_schema` prints byte for byte:
 *
 *   - a subschema whose `$schema` names draft 3;
 *   - a `$ref`/`$dynamicRef` that is not fragment-only (`$recursiveRef`'s value is never
 *     read by the reference, so it is never judged here either);
 *   - a `$id` (`id` under draft 4) below the root while the document holds any reference.
 *
 * Eager rather than on first use, deliberately: the reference resolves a `$ref` only when
 * validation reaches it, but it resolves it against a base URI this port does not model,
 * and the Python side cannot be made lazy about an absolute reference it CAN resolve.
 * Both runtimes refusing the same document is the property; refusing a branch the
 * instance never reached is the price, and it is the same trade `pattern` already takes.
 */
function refuseUnsupportedReferences(schema: PyValue, draft: Draft): void {
  const idKey = draft === 4 ? 'id' : '$id';
  const refs: [string, string][] = [];
  const ids: string[] = [];
  for (const [path, sub] of subschemas(schema)) {
    if (path !== '') {
      const nested = sub.get('$schema');
      if (nested !== undefined && nested.t === 'str' && DRAFT_BY_URI.get(pyUrlNormalize(nested.v)) === 3) {
        throw new PyJsonSchemaRefusal(draft3Sentence(nested.v));
      }
      const id = sub.get(idKey);
      if (id !== undefined && id.t === 'str') ids.push(path);
    }
    for (const k of REF_KEYWORDS) {
      const v = sub.get(k);
      if (v !== undefined && v.t === 'str') refs.push([k, v.v]);
    }
  }
  for (const [k, v] of refs) {
    if (k !== '$recursiveRef' && v !== '' && !v.startsWith('#')) {
      throw new PyJsonSchemaRefusal(
        `the reference ${JSON.stringify(v)} cannot be resolved: only references into this ` +
          'schema ("#", "#/..." and "#name") are supported',
      );
    }
  }
  if (refs.length > 0 && ids.length > 0) {
    throw new PyJsonSchemaRefusal(
      `the schema declares "${idKey}" at ${ids[0]}; references are only resolved in a schema ` +
        'with a single resource',
    );
  }
}

/** `urllib.parse.unquote(s)`: `%XX` runs decoded as UTF-8 with replacement, a lone `%` kept. */
function pyUnquote(text: string): string {
  return text.replace(/(?:%[0-9A-Fa-f]{2})+/g, (run) => {
    const bytes = Uint8Array.from(run.split('%').slice(1), (h) => parseInt(h, 16));
    return new TextDecoder('utf-8').decode(bytes);
  });
}

/** `int(segment)` for a list index: sign, digits, underscores between them, surrounding whitespace. */
function pyInt(segment: string): number {
  const m = /^\s*([+-]?)(\d+(?:_\d+)*)\s*$/.exec(segment);
  if (m === null) {
    throw new PyJsonSchemaUnsupported(`invalid literal for int() with base 10: ${JSON.stringify(segment)}`);
  }
  const n = Number(m[2]!.replace(/_/g, ''));
  return m[1] === '-' ? -n : n;
}

const nowhere = (pointer: string): PyJsonSchemaRefusal =>
  new PyJsonSchemaRefusal(`the reference ${JSON.stringify(`#${pointer}`)} points at nothing in this schema`);

/**
 * `referencing.Resource.pointer`: the fragment is percent-decoded AS A WHOLE and then split
 * on `/`; a segment into a sequence goes through `int()` (so `-1` is the last element and
 * `a` is a `ValueError`, which escapes), a segment into an object has `~1` then `~0`
 * unescaped. A `str` is a `Sequence` in Python, so a pointer can index into one.
 */
function resolvePointer(pointer: string, root: PyValue): PyValue {
  let contents = root;
  for (const raw of pyUnquote(pointer.slice(1)).split('/')) {
    if (contents.t === 'list' || contents.t === 'str') {
      const seq: PyValue[] = contents.t === 'list' ? contents.v : [...contents.v].map((ch) => ({ t: 'str', v: ch }));
      const index = pyInt(raw);
      const i = index < 0 ? seq.length + index : index;
      if (i < 0 || i >= seq.length) throw nowhere(pointer);
      contents = seq[i]!;
    } else if (contents.t === 'dict') {
      const next = contents.v.get(raw.replace(/~1/g, '/').replace(/~0/g, '~'));
      if (next === undefined) throw nowhere(pointer);
      contents = next;
    } else {
      // `3["x"]` — a TypeError in Python, not a LookupError, so not a PointerToNowhere.
      throw new PyJsonSchemaUnsupported(`${contents.t} object is not subscriptable`);
    }
  }
  return contents;
}

/** `Resource.anchor(name)`: the subschema carrying `$anchor` (or, under 2020-12, `$dynamicAnchor`) `name`. */
function resolveAnchor(name: string, ctx: Ctx): PyValue {
  const keys = ctx.rootDraft === 2020 ? ['$anchor', '$dynamicAnchor'] : ctx.rootDraft === 2019 ? ['$anchor'] : [];
  // Under draft 7 and earlier an anchor is a fragment-only `$id` below the root, which the
  // eager scan refused with the document; nothing is left here to match.
  for (const [, sub] of subschemas(ctx.root)) {
    for (const k of keys) {
      const v = sub.get(k);
      if (v !== undefined && v.t === 'str' && v.v === name) return { t: 'dict', v: sub };
    }
  }
  throw new PyJsonSchemaRefusal(`the reference ${JSON.stringify(`#${name}`)} names no anchor in this schema`);
}

/** `Resolver.lookup(ref)` inside the one resource: `""` and `"#"` are the root. */
function resolveRef(ref: string, ctx: Ctx): PyValue {
  if (ref === '' || ref === '#') return ctx.root;
  const fragment = ref.slice(1);
  if (fragment.startsWith('/')) return resolvePointer(fragment, ctx.root);
  return resolveAnchor(fragment, ctx);
}

const refValue = (keyword: string, value: PyValue): string => {
  // `lookup(3)` → `urljoin("", 3)` → TypeError. Both raise.
  if (value.t !== 'str') throw new PyJsonSchemaUnsupported(`${keyword} must be a string, got ${value.t}`);
  return value.v;
};

// --------------------------------------------------------------- unevaluated*, two ways

/**
 * `_utils.find_evaluated_property_keys_by_schema` (2020-12). A list, not a set, because the
 * reference's is — membership is all it is used for, so the duplicates do not matter.
 */
function evaluatedKeys2020(instance: Map<string, PyValue>, schema: PyValue | boolean, ctx: Ctx): string[] {
  if (typeof schema === 'boolean' || schema.t === 'bool') return [];
  const keys: string[] = [];
  const sub = (child: PyValue | boolean): string[] => evaluatedKeys2020(instance, child, ctx);
  for (const k of ['$ref', '$dynamicRef']) {
    const ref = get(schema, k);
    if (ref !== undefined && ref.t !== 'null') keys.push(...sub(resolveRef(refValue(k, ref), ctx)));
  }
  const properties = get(schema, 'properties');
  if (properties !== undefined && properties.t === 'dict') {
    for (const name of properties.v.keys()) if (instance.has(name)) keys.push(name);
  }
  for (const k of ['additionalProperties', 'unevaluatedProperties']) {
    const child = get(schema, k);
    if (child === undefined || child.t === 'null') continue;
    for (const [name, value] of instance) if (isValid(value, child, ctx)) keys.push(name);
  }
  const pp = get(schema, 'patternProperties');
  if (pp !== undefined && pp.t === 'dict') {
    for (const name of instance.keys()) for (const pattern of pp.v.keys()) if (reSearch(pattern, name)) keys.push(name);
  }
  const ds = get(schema, 'dependentSchemas');
  if (ds !== undefined && ds.t === 'dict') {
    for (const [name, child] of ds.v) if (instance.has(name)) keys.push(...sub(child));
  }
  for (const k of ['allOf', 'oneOf', 'anyOf']) {
    const list = get(schema, k);
    if (list === undefined || list.t !== 'list') continue;
    for (const child of list.v) if (isValid({ t: 'dict', v: instance }, child, ctx)) keys.push(...sub(child));
  }
  keys.push(...evaluatedByIf(schema, { t: 'dict', v: instance }, ctx, sub));
  return keys;
}

/** The `if`/`then`/`else` arm all four walkers share. */
function evaluatedByIf<T>(
  schema: PyValue,
  instance: PyValue,
  ctx: Ctx,
  walk: (child: PyValue | boolean) => T[],
): T[] {
  const cond = get(schema, 'if');
  if (cond === undefined) return [];
  if (isValid(instance, cond, ctx)) {
    const then = get(schema, 'then');
    return [...walk(cond), ...(then === undefined ? [] : walk(then))];
  }
  const otherwise = get(schema, 'else');
  return otherwise === undefined ? [] : walk(otherwise);
}

/**
 * `_legacy_keywords.find_evaluated_property_keys_by_schema` (2019-09). Note the second
 * loop: for an OBJECT `additionalProperties`/`unevaluatedProperties` it reads the
 * subschema's KEYS (`type`, `minLength`, …) as property names. Reproduced, not corrected —
 * the sentence that comes out of it is the reference's sentence.
 */
function evaluatedKeys2019(instance: Map<string, PyValue>, schema: PyValue | boolean, ctx: Ctx): string[] {
  if (typeof schema === 'boolean' || schema.t === 'bool') return [];
  const keys: string[] = [];
  const sub = (child: PyValue | boolean): string[] => evaluatedKeys2019(instance, child, ctx);
  const ref = get(schema, '$ref');
  if (ref !== undefined && ref.t !== 'null') keys.push(...sub(resolveRef(refValue('$ref', ref), ctx)));
  if (get(schema, '$recursiveRef') !== undefined) keys.push(...sub(ctx.root));
  for (const k of ['properties', 'additionalProperties', 'unevaluatedProperties']) {
    const value = get(schema, k);
    if (value === undefined) continue;
    if (value.t === 'bool' && value.v) keys.push(...instance.keys());
    else if (value.t === 'dict') for (const name of value.v.keys()) if (instance.has(name)) keys.push(name);
  }
  const pp = get(schema, 'patternProperties');
  if (pp !== undefined && pp.t === 'dict') {
    for (const name of instance.keys()) for (const pattern of pp.v.keys()) if (reSearch(pattern, name)) keys.push(name);
  }
  const ds = get(schema, 'dependentSchemas');
  if (ds !== undefined && ds.t === 'dict') {
    for (const [name, child] of ds.v) if (instance.has(name)) keys.push(...sub(child));
  }
  for (const k of ['allOf', 'oneOf', 'anyOf']) {
    const list = get(schema, k);
    if (list === undefined || list.t !== 'list') continue;
    for (const child of list.v) if (isValid({ t: 'dict', v: instance }, child, ctx)) keys.push(...sub(child));
  }
  keys.push(...evaluatedByIf(schema, { t: 'dict', v: instance }, ctx, sub));
  return keys;
}

const range = (n: number): number[] => Array.from({ length: n }, (_, i) => i);

/** `_utils.find_evaluated_item_indexes_by_schema` (2020-12). */
function evaluatedIndexes2020(instance: PyValue[], schema: PyValue | boolean, ctx: Ctx): number[] {
  if (typeof schema === 'boolean' || schema.t === 'bool') return [];
  if (get(schema, 'items') !== undefined) return range(instance.length);
  const idx: number[] = [];
  const sub = (child: PyValue | boolean): number[] => evaluatedIndexes2020(instance, child, ctx);
  for (const k of ['$ref', '$dynamicRef']) {
    const ref = get(schema, k);
    if (ref !== undefined && ref.t !== 'null') idx.push(...sub(resolveRef(refValue(k, ref), ctx)));
  }
  const prefix = get(schema, 'prefixItems');
  if (prefix !== undefined) idx.push(...range(pyLen(prefix)));
  const list: PyValue = { t: 'list', v: instance };
  idx.push(...evaluatedByIf(schema, list, ctx, sub));
  for (const k of ['contains', 'unevaluatedItems']) {
    const child = get(schema, k);
    if (child === undefined) continue;
    instance.forEach((v, i) => {
      if (isValid(v, child, ctx)) idx.push(i);
    });
  }
  for (const k of ['allOf', 'oneOf', 'anyOf']) {
    const children = get(schema, k);
    if (children === undefined || children.t !== 'list') continue;
    for (const child of children.v) if (isValid(list, child, ctx)) idx.push(...sub(child));
  }
  return idx;
}

/** `_legacy_keywords.find_evaluated_item_indexes_by_schema` (2019-09). */
function evaluatedIndexes2019(instance: PyValue[], schema: PyValue | boolean, ctx: Ctx): number[] {
  if (typeof schema === 'boolean' || schema.t === 'bool') return [];
  const idx: number[] = [];
  const sub = (child: PyValue | boolean): number[] => evaluatedIndexes2019(instance, child, ctx);
  const ref = get(schema, '$ref');
  if (ref !== undefined && ref.t !== 'null') idx.push(...sub(resolveRef(refValue('$ref', ref), ctx)));
  if (get(schema, '$recursiveRef') !== undefined) idx.push(...sub(ctx.root));
  const items = get(schema, 'items');
  if (items !== undefined) {
    if (get(schema, 'additionalItems') !== undefined) return range(instance.length);
    if (items.t === 'dict') return range(instance.length);
    idx.push(...range(pyLen(items)));
  }
  const list: PyValue = { t: 'list', v: instance };
  idx.push(...evaluatedByIf(schema, list, ctx, sub));
  for (const k of ['contains', 'unevaluatedItems']) {
    const child = get(schema, k);
    if (child === undefined) continue;
    instance.forEach((v, i) => {
      if (isValid(v, child, ctx)) idx.push(i);
    });
  }
  for (const k of ['allOf', 'oneOf', 'anyOf']) {
    const children = get(schema, k);
    if (children === undefined || children.t !== 'list') continue;
    for (const child of children.v) if (isValid(list, child, ctx)) idx.push(...sub(child));
  }
  return idx;
}

/** `len(value)` where the reference calls it on a schema value: a list, a dict, a string — never a bool. */
function pyLen(value: PyValue): number {
  if (value.t === 'list') return value.v.length;
  if (value.t === 'dict') return value.v.size;
  if (value.t === 'str') return cpLength(value.v);
  throw new PyJsonSchemaUnsupported(`object of type '${value.t}' has no len()`);
}

function unevaluatedItemsWith(walker: (instance: PyValue[], schema: PyValue | boolean, ctx: Ctx) => number[]): Keyword {
  return (_value, instance, schema, emit, _descend, ctx) => {
    if (instance.t !== 'list') return [];
    const evaluated = new Set(walker(instance.v, schema, ctx));
    const unevaluated = instance.v.filter((_, i) => !evaluated.has(i));
    if (unevaluated.length === 0) return [];
    const [joined, verb] = extrasMsgValues(unevaluated);
    return [emit(`Unevaluated items are not allowed (${joined} ${verb} unexpected)`)];
  };
}

function unevaluatedPropertiesWith(walker: (instance: Map<string, PyValue>, schema: PyValue | boolean, ctx: Ctx) => string[]): Keyword {
  return (value, instance, schema, emit, _descend, ctx) => {
    if (instance.t !== 'dict') return [];
    const evaluated = new Set(walker(instance.v, schema, ctx));
    const unevaluated: string[] = [];
    for (const [name, v] of instance.v) {
      if (evaluated.has(name)) continue;
      // `for _ in validator.descend(...)`: appended ONCE PER ERROR, so a subschema that
      // fails a property twice names it twice. Reproduced.
      for (const _ of iterErrors(v, value, ctx)) unevaluated.push(name);
    }
    if (unevaluated.length === 0) return [];
    if (value.t === 'bool' && !value.v) {
      const [joined, verb] = extrasMsg(sortedByStr(unevaluated));
      return [emit(`Unevaluated properties are not allowed (${joined} ${verb} unexpected)`)];
    }
    const [joined, verb] = extrasMsg(unevaluated);
    return [
      emit(`Unevaluated properties are not valid under the given schema (${joined} ${verb} unevaluated and invalid)`),
    ];
  };
}

// ------------------------------------------------------------------------- the keywords

const KEYWORDS: Record<string, Keyword> = {
  type(value, instance, _schema, emit, _descend, ctx) {
    // `ensure_list`: a bare string becomes a one-element list, anything else passes through.
    const types = value.t === 'str' ? [value] : value.t === 'list' ? value.v : [value];
    if (types.some((t) => t.t === 'str' && isType(instance, t.v, ctx.draft))) return [];
    const reprs = types.map(reprValue).join(', ');
    return [emit(`${reprValue(instance)} is not of type ${reprs}`)];
  },

  properties(value, instance, _schema, _emit, descend) {
    if (instance.t !== 'dict' || value.t !== 'dict') return [];
    const out: PyValidationError[] = [];
    for (const [property, subschema] of value.v) {
      const child = instance.v.get(property);
      if (instance.v.has(property)) out.push(...descend(child!, subschema, property));
    }
    return out;
  },

  required(value, instance, _schema, emit) {
    if (instance.t !== 'dict' || value.t !== 'list') return [];
    const out: PyValidationError[] = [];
    for (const property of value.v) {
      const name = (property as { v: string }).v;
      if (!instance.v.has(name)) {
        out.push(emit(`${reprValue(property)} is a required property`));
      }
    }
    return out;
  },

  additionalProperties(value, instance, schema, emit, descend) {
    if (instance.t !== 'dict') return [];
    const extras = findAdditionalProperties(instance.v, schema);
    if (value.t === 'dict') {
      const out: PyValidationError[] = [];
      // `set(...)` in Python — iteration order is a hash order this port cannot reproduce.
      // Every error here descends into a subschema and carries its own `path`, so the ORDER
      // is the only thing that differs and `best_match` sorts on `path` before order. Sorted
      // for determinism; see the ruled case.
      for (const extra of sortedByStr(extras)) out.push(...descend(instance.v.get(extra)!, value, extra));
      return out;
    }
    if (!pyTruthy(value) && extras.length > 0) {
      const pp = get(schema, 'patternProperties');
      if (pp !== undefined) {
        const verb = extras.length === 1 ? 'does' : 'do';
        const joined = sortedByStr(extras).map((e) => reprValue({ t: 'str', v: e })).join(', ');
        const patterns = sortedByStr(pp.t === 'dict' ? [...pp.v.keys()] : [])
          .map((e) => reprValue({ t: 'str', v: e }))
          .join(', ');
        return [emit(`${joined} ${verb} not match any of the regexes: ${patterns}`)];
      }
      const [joined, verb] = extrasMsg(sortedByStr(extras));
      return [emit(`Additional properties are not allowed (${joined} ${verb} unexpected)`)];
    }
    return [];
  },

  patternProperties(value, instance, _schema, _emit, descend) {
    if (instance.t !== 'dict' || value.t !== 'dict') return [];
    const out: PyValidationError[] = [];
    for (const [pattern, subschema] of value.v) {
      for (const [k, v] of instance.v) {
        if (reSearch(pattern, k)) out.push(...descend(v, subschema, k));
      }
    }
    return out;
  },

  propertyNames(value, instance, _schema, _emit, descend) {
    if (instance.t !== 'dict') return [];
    const out: PyValidationError[] = [];
    // No `path`: jsonschema descends on the KEY with no path component, so the error points
    // at the object and not at a property that does not exist.
    for (const property of instance.v.keys()) out.push(...descend({ t: 'str', v: property }, value));
    return out;
  },

  prefixItems(value, instance, _schema, _emit, descend) {
    if (instance.t !== 'list' || value.t !== 'list') return [];
    const out: PyValidationError[] = [];
    const n = Math.min(instance.v.length, value.v.length);
    for (let i = 0; i < n; i += 1) out.push(...descend(instance.v[i]!, value.v[i]!, i));
    return out;
  },

  /** `_keywords.items` (2020-12): everything past `prefixItems`. */
  items(value, instance, schema, emit, descend) {
    if (instance.t !== 'list') return [];
    const pi = get(schema, 'prefixItems');
    const prefix = pi && pi.t === 'list' ? pi.v.length : 0;
    const total = instance.v.length;
    const extra = total - prefix;
    if (extra <= 0) return [];
    if (value.t === 'bool' && value.v === false) {
      const rest = extra !== 1 ? { t: 'list' as const, v: instance.v.slice(prefix) } : instance.v[prefix]!;
      const item = prefix !== 1 ? 'items' : 'item';
      return [emit(`Expected at most ${prefix} ${item} but found ${extra} extra: ${reprValue(rest)}`)];
    }
    const out: PyValidationError[] = [];
    for (let i = prefix; i < total; i += 1) out.push(...descend(instance.v[i]!, value, i));
    return out;
  },

  /** `_keywords.contains` (2019-09 and 2020-12): with `minContains`/`maxContains`. */
  contains(value, instance, schema, emit, _descend, ctx) {
    if (instance.t !== 'list') return [];
    const minRaw = get(schema, 'minContains');
    const maxRaw = get(schema, 'maxContains');
    const minContains = minRaw === undefined ? 1 : asNumber(minRaw);
    const maxContains = maxRaw === undefined ? instance.v.length : asNumber(maxRaw);
    let matches = 0;
    for (const each of instance.v) {
      if (isValid(each, value, ctx)) {
        matches += 1;
        if (matches > maxContains) {
          return [
            emit(`Too many items match the given schema (expected at most ${maxContains})`, {
              validator: 'maxContains',
            }),
          ];
        }
      }
    }
    if (matches < minContains) {
      if (matches === 0) {
        return [emit(`${reprValue(instance)} does not contain items matching the given schema`)];
      }
      return [
        emit(
          `Too few items match the given schema (expected at least ${minContains} but only ` +
            `${matches} matched)`,
          { validator: 'minContains' },
        ),
      ];
    }
    return [];
  },

  const(value, instance, _schema, emit) {
    return pyEqual(instance, value) ? [] : [emit(`${reprValue(value)} was expected`)];
  },

  enum(value, instance, _schema, emit) {
    if (value.t !== 'list') return [];
    if (value.v.some((each) => pyEqual(each, instance))) return [];
    return [emit(`${reprValue(instance)} is not one of ${reprValue(value)}`)];
  },

  minimum(value, instance, _schema, emit) {
    if (!isType(instance, 'number')) return [];
    if (numLess(instance, value)) {
      return [emit(`${reprValue(instance)} is less than the minimum of ${reprValue(value)}`)];
    }
    return [];
  },

  maximum(value, instance, _schema, emit) {
    if (!isType(instance, 'number')) return [];
    if (numLess(value, instance)) {
      return [emit(`${reprValue(instance)} is greater than the maximum of ${reprValue(value)}`)];
    }
    return [];
  },

  exclusiveMinimum(value, instance, _schema, emit) {
    if (!isType(instance, 'number')) return [];
    if (!numLess(value, instance)) {
      return [
        emit(`${reprValue(instance)} is less than or equal to the minimum of ${reprValue(value)}`),
      ];
    }
    return [];
  },

  exclusiveMaximum(value, instance, _schema, emit) {
    if (!isType(instance, 'number')) return [];
    if (!numLess(instance, value)) {
      return [
        emit(`${reprValue(instance)} is greater than or equal to the maximum of ${reprValue(value)}`),
      ];
    }
    return [];
  },

  multipleOf(value, instance, _schema, emit) {
    if (!isType(instance, 'number')) return [];
    let failed: boolean;
    if (value.t === 'float') {
      const quotient = asNumber(instance) / value.v;
      if (!Number.isFinite(quotient)) {
        // `int(quotient)` raises OverflowError in Python and it falls back to exact Fraction
        // arithmetic. Reached only for an enormous instance over a tiny divisor.
        throw new PyJsonSchemaUnsupported('multipleOf overflowed; the Fraction fallback is not ported');
      }
      failed = Math.trunc(quotient) !== quotient;
    } else if (value.t === 'int') {
      if (value.v === 0n) throw new PyJsonSchemaUnsupported('multipleOf 0 divides by zero');
      failed =
        instance.t === 'int'
          ? instance.v % value.v !== 0n
          : asNumber(instance) % Number(value.v) !== 0;
    } else {
      throw new PyJsonSchemaUnsupported(`multipleOf must be a number, got ${value.t}`);
    }
    // `{dB}` is str(), not repr(): an int prints the same either way and a float does too
    // for every value `str` and `repr` share, which since 3.1 is all of them.
    return failed ? [emit(`${reprValue(instance)} is not a multiple of ${reprValue(value)}`)] : [];
  },

  minItems(value, instance, _schema, emit) {
    if (instance.t !== 'list' || instance.v.length >= asNumber(value)) return [];
    const message = asNumber(value) === 1 ? 'should be non-empty' : 'is too short';
    return [emit(`${reprValue(instance)} ${message}`)];
  },

  maxItems(value, instance, _schema, emit) {
    if (instance.t !== 'list' || instance.v.length <= asNumber(value)) return [];
    const message = asNumber(value) === 0 ? 'is expected to be empty' : 'is too long';
    return [emit(`${reprValue(instance)} ${message}`)];
  },

  minLength(value, instance, _schema, emit) {
    if (instance.t !== 'str' || cpLength(instance.v) >= asNumber(value)) return [];
    const message = asNumber(value) === 1 ? 'should be non-empty' : 'is too short';
    return [emit(`${reprValue(instance)} ${message}`)];
  },

  maxLength(value, instance, _schema, emit) {
    if (instance.t !== 'str' || cpLength(instance.v) <= asNumber(value)) return [];
    const message = asNumber(value) === 0 ? 'is expected to be empty' : 'is too long';
    return [emit(`${reprValue(instance)} ${message}`)];
  },

  minProperties(value, instance, _schema, emit) {
    if (instance.t !== 'dict' || instance.v.size >= asNumber(value)) return [];
    const message = asNumber(value) === 1 ? 'should be non-empty' : 'does not have enough properties';
    return [emit(`${reprValue(instance)} ${message}`)];
  },

  maxProperties(value, instance, _schema, emit) {
    if (instance.t !== 'dict' || instance.v.size <= asNumber(value)) return [];
    const message = asNumber(value) === 0 ? 'is expected to be empty' : 'has too many properties';
    return [emit(`${reprValue(instance)} ${message}`)];
  },

  uniqueItems(value, instance, _schema, emit) {
    if (!pyTruthy(value) || instance.t !== 'list') return [];
    const seen: PyValue[] = [];
    for (const each of instance.v) {
      if (seen.some((i) => pyEqual(i, each))) {
        return [emit(`${reprValue(instance)} has non-unique elements`)];
      }
      seen.push(each);
    }
    return [];
  },

  pattern(value, instance, _schema, emit) {
    if (instance.t !== 'str' || value.t !== 'str') return [];
    if (reSearch(value.v, instance.v)) return [];
    return [emit(`${reprValue(instance)} does not match ${reprValue(value)}`)];
  },

  /** `jsonschema.validate` passes no `format_checker`, so this keyword cannot ever fire. */
  format() {
    return [];
  },

  dependentRequired(value, instance, _schema, emit) {
    if (instance.t !== 'dict' || value.t !== 'dict') return [];
    const out: PyValidationError[] = [];
    for (const [property, dependency] of value.v) {
      if (!instance.v.has(property)) continue;
      if (dependency.t !== 'list') continue;
      for (const each of dependency.v) {
        const name = (each as { v: string }).v;
        if (!instance.v.has(name)) {
          out.push(emit(`${reprValue(each)} is a dependency of ${reprValue({ t: 'str', v: property })}`));
        }
      }
    }
    return out;
  },

  dependentSchemas(value, instance, _schema, _emit, descend) {
    if (instance.t !== 'dict' || value.t !== 'dict') return [];
    const out: PyValidationError[] = [];
    for (const [property, dependency] of value.v) {
      if (!instance.v.has(property)) continue;
      out.push(...descend(instance, dependency));
    }
    return out;
  },

  allOf(value, instance, _schema, _emit, descend) {
    if (value.t !== 'list') return [];
    const out: PyValidationError[] = [];
    for (const subschema of value.v) out.push(...descend(instance, subschema));
    return out;
  },

  anyOf(value, instance, _schema, emit, _descend, ctx) {
    if (value.t !== 'list') return [];
    const allErrors: PyValidationError[] = [];
    for (const subschema of value.v) {
      const errs = iterErrors(instance, subschema, ctx);
      if (errs.length === 0) return [];
      allErrors.push(...errs);
    }
    const error = emit(`${reprValue(instance)} is not valid under any of the given schemas`, {
      context: allErrors,
    });
    for (const child of allErrors) child.parent = error;
    return [error];
  },

  oneOf(value, instance, _schema, emit, _descend, ctx) {
    if (value.t !== 'list') return [];
    const out: PyValidationError[] = [];
    const allErrors: PyValidationError[] = [];
    let firstValid: PyValue | null = null;
    let index = 0;
    for (; index < value.v.length; index += 1) {
      const errs = iterErrors(instance, value.v[index]!, ctx);
      if (errs.length === 0) {
        firstValid = value.v[index]!;
        break;
      }
      allErrors.push(...errs);
    }
    if (firstValid === null) {
      const error = emit(`${reprValue(instance)} is not valid under any of the given schemas`, {
        context: allErrors,
      });
      for (const child of allErrors) child.parent = error;
      out.push(error);
    }
    // `subschemas` is one shared iterator in Python: the comprehension below resumes where
    // the loop above broke, so the schemas already tried are never re-checked.
    const moreValid = value.v.slice(index + 1).filter((each) => isValid(instance, each, ctx));
    if (moreValid.length > 0) {
      const reprs = [...moreValid, firstValid!].map(reprValue).join(', ');
      out.push(emit(`${reprValue(instance)} is valid under each of ${reprs}`));
    }
    return out;
  },

  not(value, instance, _schema, emit, _descend, ctx) {
    if (!isValid(instance, value, ctx)) return [];
    return [emit(`${reprValue(instance)} should not be valid under ${reprValue(value)}`)];
  },

  if(value, instance, schema, _emit, descend, ctx) {
    if (isValid(instance, value, ctx)) {
      const then = get(schema, 'then');
      return then === undefined ? [] : descend(instance, then);
    }
    const otherwise = get(schema, 'else');
    return otherwise === undefined ? [] : descend(instance, otherwise);
  },

  /** `_keywords.ref`: `descend(instance, resolved.contents)` — no path, no `$ref` in the schema path. */
  $ref(value, instance, _schema, _emit, descend, ctx) {
    return descend(instance, resolveRef(refValue('$ref', value), ctx));
  },

  /** `_keywords.dynamicRef` is `_validate_reference(ref=dynamicRef)` — the same lookup. */
  $dynamicRef(value, instance, _schema, _emit, descend, ctx) {
    return descend(instance, resolveRef(refValue('$dynamicRef', value), ctx));
  },

  /** `_legacy_keywords.recursiveRef` never reads its value; in one resource it is the root. */
  $recursiveRef(_value, instance, _schema, _emit, descend, ctx) {
    return descend(instance, ctx.root);
  },

  unevaluatedItems: unevaluatedItemsWith(evaluatedIndexes2020),
  unevaluatedProperties: unevaluatedPropertiesWith(evaluatedKeys2020),
};

/** `_legacy_keywords`: the keywords whose shape or sentence is older than 2020-12. */
const LEGACY: Record<string, Keyword> = {
  /** `items_draft3_draft4`: an object applies to every item, anything else is zipped. */
  itemsDraft4(value, instance, _schema, _emit, descend) {
    if (instance.t !== 'list') return [];
    const out: PyValidationError[] = [];
    if (value.t === 'dict') {
      instance.v.forEach((item, i) => out.push(...descend(item, value, i)));
    } else if (value.t === 'list') {
      const n = Math.min(instance.v.length, value.v.length);
      for (let i = 0; i < n; i += 1) out.push(...descend(instance.v[i]!, value.v[i]!, i));
    }
    return out;
  },

  /** `items_draft6_draft7_draft201909`: an array is zipped, anything else applies to every item. */
  itemsDraft6(value, instance, _schema, _emit, descend) {
    if (instance.t !== 'list') return [];
    const out: PyValidationError[] = [];
    if (value.t === 'list') {
      const n = Math.min(instance.v.length, value.v.length);
      for (let i = 0; i < n; i += 1) out.push(...descend(instance.v[i]!, value.v[i]!, i));
    } else {
      instance.v.forEach((item, i) => out.push(...descend(item, value, i)));
    }
    return out;
  },

  additionalItems(value, instance, schema, emit, descend) {
    if (instance.t !== 'list') return [];
    // `schema.get("items", {})` is an object when absent, so the keyword applies only
    // beside a LIST `items`; `len(True)` beside a boolean one is a TypeError that escapes.
    const items = get(schema, 'items');
    if (items === undefined || items.t === 'dict') return [];
    const lenItems = pyLen(items);
    if (value.t === 'dict') {
      const out: PyValidationError[] = [];
      for (let i = lenItems; i < instance.v.length; i += 1) out.push(...descend(instance.v[i]!, value, i));
      return out;
    }
    if (!pyTruthy(value) && instance.v.length > lenItems) {
      const [joined, verb] = extrasMsgValues(instance.v.slice(lenItems));
      return [emit(`Additional items are not allowed (${joined} ${verb} unexpected)`)];
    }
    return [];
  },

  /** `dependencies_draft4_draft6_draft7`: a list is `dependentRequired`, anything else a schema. */
  dependencies(value, instance, _schema, emit, descend) {
    if (instance.t !== 'dict' || value.t !== 'dict') return [];
    const out: PyValidationError[] = [];
    for (const [property, dependency] of value.v) {
      if (!instance.v.has(property)) continue;
      if (dependency.t === 'list') {
        for (const each of dependency.v) {
          const name = (each as { v: string }).v;
          if (!instance.v.has(name)) {
            out.push(emit(`${reprValue(each)} is a dependency of ${reprValue({ t: 'str', v: property })}`));
          }
        }
      } else {
        out.push(...descend(instance, dependency));
      }
    }
    return out;
  },

  /** `maximum_draft3_draft4`: a truthy `exclusiveMaximum` sibling makes the bound exclusive. */
  maximumDraft4(value, instance, schema, emit) {
    if (!isType(instance, 'number')) return [];
    const exclusive = get(schema, 'exclusiveMaximum');
    if (exclusive !== undefined && pyTruthy(exclusive)) {
      if (!numLess(instance, value)) {
        return [emit(`${reprValue(instance)} is greater than or equal to the maximum of ${reprValue(value)}`)];
      }
      return [];
    }
    if (numLess(value, instance)) {
      return [emit(`${reprValue(instance)} is greater than the maximum of ${reprValue(value)}`)];
    }
    return [];
  },

  minimumDraft4(value, instance, schema, emit) {
    if (!isType(instance, 'number')) return [];
    const exclusive = get(schema, 'exclusiveMinimum');
    if (exclusive !== undefined && pyTruthy(exclusive)) {
      if (!numLess(value, instance)) {
        return [emit(`${reprValue(instance)} is less than or equal to the minimum of ${reprValue(value)}`)];
      }
      return [];
    }
    if (numLess(instance, value)) {
      return [emit(`${reprValue(instance)} is less than the minimum of ${reprValue(value)}`)];
    }
    return [];
  },

  /** `contains_draft6_draft7`: no `minContains`, and a different sentence. */
  containsDraft6(value, instance, _schema, emit, _descend, ctx) {
    if (instance.t !== 'list') return [];
    if (instance.v.some((element) => isValid(element, value, ctx))) return [];
    return [emit(`None of ${reprValue(instance)} are valid under the given schema`)];
  },

  unevaluatedItems2019: unevaluatedItemsWith(evaluatedIndexes2019),
  unevaluatedProperties2019: unevaluatedPropertiesWith(evaluatedKeys2019),
};

const pick = (names: string[]): Record<string, Keyword> =>
  Object.fromEntries(names.map((n) => [n, KEYWORDS[n]!]));

/** `Draft4Validator.VALIDATORS` … `Draft202012Validator.VALIDATORS`, name for name. */
const KEYWORDS_BY_DRAFT: Record<Draft, Record<string, Keyword>> = {
  4: {
    ...pick([
      '$ref', 'additionalProperties', 'allOf', 'anyOf', 'enum', 'format', 'maxItems', 'maxLength',
      'maxProperties', 'minItems', 'minLength', 'minProperties', 'multipleOf', 'not', 'oneOf',
      'pattern', 'patternProperties', 'properties', 'required', 'type', 'uniqueItems',
    ]),
    additionalItems: LEGACY['additionalItems']!,
    dependencies: LEGACY['dependencies']!,
    items: LEGACY['itemsDraft4']!,
    maximum: LEGACY['maximumDraft4']!,
    minimum: LEGACY['minimumDraft4']!,
  },
  6: {
    ...pick([
      '$ref', 'additionalProperties', 'allOf', 'anyOf', 'const', 'enum', 'exclusiveMaximum',
      'exclusiveMinimum', 'format', 'maxItems', 'maxLength', 'maxProperties', 'maximum', 'minItems',
      'minLength', 'minProperties', 'minimum', 'multipleOf', 'not', 'oneOf', 'pattern',
      'patternProperties', 'properties', 'propertyNames', 'required', 'type', 'uniqueItems',
    ]),
    additionalItems: LEGACY['additionalItems']!,
    contains: LEGACY['containsDraft6']!,
    dependencies: LEGACY['dependencies']!,
    items: LEGACY['itemsDraft6']!,
  },
  7: {
    ...pick([
      '$ref', 'additionalProperties', 'allOf', 'anyOf', 'const', 'enum', 'exclusiveMaximum',
      'exclusiveMinimum', 'format', 'if', 'maxItems', 'maxLength', 'maxProperties', 'maximum',
      'minItems', 'minLength', 'minProperties', 'minimum', 'multipleOf', 'not', 'oneOf', 'pattern',
      'patternProperties', 'properties', 'propertyNames', 'required', 'type', 'uniqueItems',
    ]),
    additionalItems: LEGACY['additionalItems']!,
    contains: LEGACY['containsDraft6']!,
    dependencies: LEGACY['dependencies']!,
    items: LEGACY['itemsDraft6']!,
  },
  2019: {
    ...pick([
      '$recursiveRef', '$ref', 'additionalProperties', 'allOf', 'anyOf', 'const', 'contains',
      'dependentRequired', 'dependentSchemas', 'enum', 'exclusiveMaximum', 'exclusiveMinimum',
      'format', 'if', 'maxItems', 'maxLength', 'maxProperties', 'maximum', 'minItems', 'minLength',
      'minProperties', 'minimum', 'multipleOf', 'not', 'oneOf', 'pattern', 'patternProperties',
      'properties', 'propertyNames', 'required', 'type', 'uniqueItems',
    ]),
    additionalItems: LEGACY['additionalItems']!,
    items: LEGACY['itemsDraft6']!,
    unevaluatedItems: LEGACY['unevaluatedItems2019']!,
    unevaluatedProperties: LEGACY['unevaluatedProperties2019']!,
  },
  2020: pick([
    '$dynamicRef', '$ref', 'additionalProperties', 'allOf', 'anyOf', 'const', 'contains',
    'dependentRequired', 'dependentSchemas', 'enum', 'exclusiveMaximum', 'exclusiveMinimum',
    'format', 'if', 'items', 'maxItems', 'maxLength', 'maxProperties', 'maximum', 'minItems',
    'minLength', 'minProperties', 'minimum', 'multipleOf', 'not', 'oneOf', 'pattern',
    'patternProperties', 'prefixItems', 'properties', 'propertyNames', 'required', 'type',
    'unevaluatedItems', 'unevaluatedProperties', 'uniqueItems',
  ]),
};

/** `a < b` over Python numbers, exact for two ints of any size. */
function numLess(a: PyValue, b: PyValue): boolean {
  if (a.t === 'int' && b.t === 'int') return a.v < b.v;
  return asNumber(a) < asNumber(b);
}

// ------------------------------------------------------------------------- the heuristic

const WEAK_MATCHES = new Set(['anyOf', 'oneOf']);
// `STRONG_MATCHES` is `frozenset()` in 4.26 — the third tuple slot is always False. Kept
// visible rather than folded away, so a jsonschema release that fills it is a one-line edit.
const STRONG_MATCHES = new Set<string>();

/** `error._matches_type()`. A `false` schema has no `["type"]`, so it answers False. */
function matchesType(error: PyValidationError): boolean {
  const expected = get(error.schema, 'type');
  if (expected === undefined) return false;
  if (expected.t === 'str') return isType(error.instance, expected.v, error.draft);
  if (expected.t === 'list') {
    return expected.v.some((t) => isType(error.instance, (t as { v: string }).v, error.draft));
  }
  return false;
}

type Relevance = [number, (string | number)[], boolean, boolean, boolean];

/** `jsonschema.exceptions.relevance`, the default key of `by_relevance()`. */
function relevance(error: PyValidationError): Relevance {
  const validator = error.validator;
  return [
    -error.path.length,
    error.path,
    validator === null || !WEAK_MATCHES.has(validator),
    validator !== null && STRONG_MATCHES.has(validator),
    !matchesType(error),
  ];
}

/** Python tuple comparison, with `deque` lexicographic ordering for the path slot. */
function cmpRelevance(a: Relevance, b: Relevance): number {
  if (a[0] !== b[0]) return a[0] < b[0] ? -1 : 1;
  const p = cmpPath(a[1], b[1]);
  if (p !== 0) return p;
  for (const i of [2, 3, 4] as const) {
    if (a[i] !== b[i]) return a[i] ? 1 : -1; // False < True
  }
  return 0;
}

function cmpPath(a: (string | number)[], b: (string | number)[]): number {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i += 1) {
    const x = a[i]!;
    const y = b[i]!;
    if (typeof x === 'number' && typeof y === 'number') {
      if (x !== y) return x < y ? -1 : 1;
      continue;
    }
    if (typeof x === 'string' && typeof y === 'string') {
      const c = cmpCodepoint(x, y);
      if (c !== 0) return c;
      continue;
    }
    // Python raises TypeError comparing str with int. It cannot happen for errors from one
    // instance — at each position the container is fixed by the shared prefix — and if it
    // ever does, refusing beats inventing an order.
    throw new PyJsonSchemaUnsupported(`cannot order path components ${String(x)} and ${String(y)}`);
  }
  return a.length === b.length ? 0 : a.length < b.length ? -1 : 1;
}

/**
 * `jsonschema.exceptions.best_match`.
 *
 * THE CHOICE IS THE PRODUCT, not just the formatting. One invalid document usually produces
 * several errors and Python raises exactly one of them, so a port that reports the first
 * error it finds emits a correct-looking sentence about the wrong field. Two rules do the
 * work: `max` prefers the SHALLOWEST error (`-len(path)`) and returns the FIRST maximum on a
 * tie; and once a winner is found, the loop descends into its `context` — the sub-errors an
 * `anyOf`/`oneOf` carries — unless the two most relevant children tie, in which case the
 * parent stands.
 */
export function bestMatch(errors: PyValidationError[]): PyValidationError | null {
  if (errors.length === 0) return null;
  let best = errors[0]!;
  let bestKey = relevance(best);
  for (let i = 1; i < errors.length; i += 1) {
    const key = relevance(errors[i]!);
    if (cmpRelevance(key, bestKey) > 0) {
      best = errors[i]!;
      bestKey = key;
    }
  }
  while (best.context.length > 0) {
    // `heapq.nsmallest(2, ..., key)` is documented as `sorted(iterable, key=key)[:2]`, and
    // its decoration by index makes it stable, so ties keep the earlier child.
    const ordered = best.context
      .map((e, i) => ({ e, i, k: relevance(e) }))
      .sort((x, y) => cmpRelevance(x.k, y.k) || x.i - y.i);
    const smallest = ordered.slice(0, 2);
    if (smallest.length === 2 && cmpRelevance(smallest[0]!.k, smallest[1]!.k) === 0) return best;
    best = smallest[0]!.e;
  }
  return best;
}

// ------------------------------------------------------------------ the schema, checked

/**
 * `cls.check_schema(schema)`, reduced to the SHAPE of each keyword's value, per dialect.
 *
 * WHY THIS EXISTS, and why it is not the metaschema. `jsonschema.validate` runs
 * `check_schema` BEFORE it looks at the instance, so a caller schema the metaschema
 * refuses never reaches a keyword. Without it, this port ran the keywords anyway and the
 * keywords are written to SKIP a value they do not recognise — which is correct behaviour
 * inside `iter_errors` and a wrong ANSWER at the tool boundary. N8 measured it on the wire:
 *
 *     {"required": "a"}              python: SchemaError   port: {"valid": true}
 *     {"required": 3}                python: SchemaError   port: {"valid": true}
 *     {"properties": ["a"]}          python: SchemaError   port: {"valid": true}
 *     {"additionalProperties": [1]}  python: SchemaError   port: {"valid": true}
 *     {"type": 3}                    python: SchemaError   port: {"valid": false, …}
 *
 * The last one is the worst of the five: a sentence about a schema that is not a schema.
 *
 * WHAT IS CHECKED, AND THE RULING ON WHAT IS NOT. Running the real metaschemas is not
 * available to this port — each is several documents wired together across resources with
 * `$ref`/`$dynamicRef`, and one resource is all this file resolves. What is here instead
 * is the SHAPE TABLE: for every keyword this port implements, the type the dialect's
 * metaschema demands of its value, applied recursively through the keywords whose values
 * hold subschemas, and GATED BY DIALECT — the metaschema of draft 4 knows no `if`, so
 * `{"if": 3}` is data there and a `SchemaError` from draft 7 on; draft 4 allows no boolean
 * subschema, requires `maximum` beside `exclusiveMaximum: true`, refuses an empty
 * `required`/`enum` and reads `2.0` as a non-integer. That is narrower than the metaschema
 * — it does not check `title`, `description`, `$comment` or `examples`, nor
 * `dependentRequired`'s uniqueness — and every gap is a schema Python refuses and this port
 * answers on. Each keyword listed below is MEASURED against the reference in
 * `tools/conformance/suites/validate.mjs`, under every dialect; the gaps are listed there
 * too, as rows deliberately absent from the grid rather than quietly ruled.
 *
 * BOTH RUNTIMES REFUSE, AND THE SENTENCE DIFFERS. Python raises `SchemaError` with the
 * metaschema's own wording and it ESCAPES `validate_json` to the caller (a registered
 * `runtime-py` defect — a tool should not let an exception out on caller input; not fixed
 * here, invariant 8). This raises `PyJsonSchemaUnsupported`, which escapes the same way,
 * because agreeing that the tool raises is the behaviour and inventing an answer is not.
 */
const SIMPLE_TYPES = new Set(['array', 'boolean', 'integer', 'null', 'number', 'object', 'string']);

/** Keywords whose value is itself a schema, and the first dialect that knows them. */
const SUBSCHEMA: Record<string, Draft> = {
  additionalProperties: 4,
  contains: 6,
  else: 7,
  if: 7,
  not: 4,
  propertyNames: 6,
  then: 7,
  unevaluatedItems: 2019,
  unevaluatedProperties: 2019,
};
/** Keywords whose value is an object whose VALUES are schemas. */
const SUBSCHEMA_MAP: Record<string, Draft> = { $defs: 2019, definitions: 4, dependentSchemas: 2019, patternProperties: 4, properties: 4 };
/** Keywords whose value is a non-empty array of schemas. */
const SUBSCHEMA_LIST: Record<string, Draft> = { allOf: 4, anyOf: 4, oneOf: 4 };
/** Keywords whose value is any JSON number. */
const NUMBER_KEYWORDS = ['maximum', 'minimum'];
/** Keywords whose value is a non-negative integer, and the first dialect that knows them. */
const COUNT_KEYWORDS: Record<string, Draft> = {
  maxContains: 2019,
  maxItems: 4,
  maxLength: 4,
  maxProperties: 4,
  minContains: 2019,
  minItems: 4,
  minLength: 4,
  minProperties: 4,
};
/** `$anchor`'s pattern changed between the two dialects that have it. */
const ANCHOR_PATTERN: Record<2019 | 2020, RegExp> = {
  2019: /^[A-Za-z][-A-Za-z0-9.:_]*$/,
  2020: /^[A-Za-z_][-A-Za-z0-9._]*$/,
};

const knows = (draft: Draft, since: Draft): boolean => draft >= since;

function refuse(where: string, expected: string, got: PyValue | boolean): never {
  const kind = typeof got === 'boolean' ? 'boolean' : got.t;
  throw new PyJsonSchemaUnsupported(`${where} must be ${expected}, got ${kind}`);
}

/** Draft 4's metaschema says `"type": "object"` for every subschema; draft 6 added the booleans. */
const isSchemaValue = (v: PyValue, draft: Draft): boolean => v.t === 'dict' || (v.t === 'bool' && draft !== 4);

const schemaWord = (draft: Draft): string => (draft === 4 ? 'an object' : 'an object or a boolean');

export function checkSchema(schema: PyValue | boolean, where = 'the schema', draft?: Draft): void {
  if (typeof schema === 'boolean' || schema.t === 'bool') return;
  const d = draft ?? dialectOf(schema, 2020);
  if (schema.t !== 'dict') refuse(where, 'an object or a boolean', schema);
  const subschema = (v: PyValue, at: string, boolOk = false): void => {
    if (!(boolOk && v.t === 'bool') && !isSchemaValue(v, d)) refuse(at, schemaWord(d), v);
    checkSchema(v, at, d);
  };
  const schemaList = (value: PyValue, at: string, nonEmpty: boolean): void => {
    if (value.t !== 'list') refuse(at, 'an array', value);
    if (nonEmpty && value.v.length === 0) throw new PyJsonSchemaUnsupported(`${at} must be a non-empty array`);
    value.v.forEach((v, i) => subschema(v, `${at}/${i}`));
  };
  const stringList = (value: PyValue, at: string, nonEmpty: boolean): void => {
    if (value.t !== 'list') refuse(at, 'an array', value);
    if (nonEmpty && value.v.length === 0) throw new PyJsonSchemaUnsupported(`${at} must be a non-empty array`);
    const seen = new Set<string>();
    value.v.forEach((v, i) => {
      if (v.t !== 'str') refuse(`${at}/${i}`, 'a string', v);
      if (seen.has(v.v)) {
        throw new PyJsonSchemaUnsupported(`${at} must have unique items, got ${reprValue(v)} twice`);
      }
      seen.add(v.v);
    });
  };
  const string = (value: PyValue, at: string): string => {
    if (value.t !== 'str') refuse(at, 'a string', value);
    return value.v;
  };
  const anchor = (value: PyValue, at: string): void => {
    const pattern = ANCHOR_PATTERN[d === 2019 ? 2019 : 2020];
    if (!pattern.test(string(value, at))) {
      throw new PyJsonSchemaUnsupported(`${at} must match ${pattern.source}, got ${reprValue(value)}`);
    }
  };
  for (const [keyword, value] of schema.v) {
    const at = `${where}: ${keyword}`;
    if (keyword in SUBSCHEMA_LIST) {
      // `allOf`/`anyOf`/`oneOf` carry `"minItems": 1` in every dialect's metaschema.
      schemaList(value, at, true);
    } else if (keyword === 'prefixItems') {
      if (d === 2020) schemaList(value, at, false);
    } else if (keyword === 'items') {
      if (value.t === 'list') {
        // A tuple `items` is `schemaArray` (non-empty) through 2019-09 and not a schema at all in 2020-12.
        if (d === 2020) refuse(at, 'an object or a boolean', value);
        schemaList(value, at, true);
      } else subschema(value, at);
    } else if (keyword === 'additionalItems') {
      // Draft 4 allows no boolean subschema EXCEPT here and on `additionalProperties`, whose
      // metaschema entries are `anyOf: [{type: boolean}, {$ref: "#"}]`.
      if (d !== 2020) subschema(value, at, true);
    } else if (keyword === 'additionalProperties') {
      subschema(value, at, true);
    } else if (keyword in SUBSCHEMA) {
      if (knows(d, SUBSCHEMA[keyword]!)) subschema(value, at);
    } else if (keyword in SUBSCHEMA_MAP) {
      if (!knows(d, SUBSCHEMA_MAP[keyword]!)) continue;
      if (value.t !== 'dict') refuse(at, 'an object', value);
      for (const [k, v] of value.v) subschema(v, `${at}/${k}`);
    } else if (keyword === 'dependencies') {
      // Each value is a schema or a `stringArray` (non-empty under draft 4). Still a SHAPE in
      // the 2019-09 and 2020-12 metaschemas — deprecated there, but `{"dependencies": {"a": 3}}`
      // is a `SchemaError` under every dialect — even though it is no longer a keyword either
      // validator runs. Measured: `check_schema/gated` in `tools/conformance/suites/validate.mjs`.
      if (value.t !== 'dict') refuse(at, 'an object', value);
      for (const [k, v] of value.v) {
        if (v.t === 'list') stringList(v, `${at}/${k}`, d === 4);
        else subschema(v, `${at}/${k}`);
      }
    } else if (keyword === 'type') {
      const each = (v: PyValue, place: string): void => {
        if (v.t !== 'str') refuse(place, 'a simple type name', v);
        if (!SIMPLE_TYPES.has(v.v)) {
          throw new PyJsonSchemaUnsupported(`${place} must be a simple type name, got ${reprValue(v)}`);
        }
      };
      if (value.t === 'list') {
        // `{"type": [...]}` is `"minItems": 1, "uniqueItems": true` in the validation
        // vocabulary, and both are reachable: `{"type": []}` and `{"type": ["string",
        // "string"]}` are schemas the reference refuses and this port used to answer on.
        if (value.v.length === 0) throw new PyJsonSchemaUnsupported(`${at} must be a non-empty array`);
        const seen = new Set<string>();
        value.v.forEach((v, i) => {
          each(v, `${at}/${i}`);
          const name = (v as { v: string }).v;
          if (seen.has(name)) {
            throw new PyJsonSchemaUnsupported(`${at} must have unique items, got ${reprValue(v)} twice`);
          }
          seen.add(name);
        });
      } else each(value, at);
    } else if (keyword === 'required') {
      // Draft 4's `stringArray` carries `"minItems": 1`; later drafts default it to `[]`.
      stringList(value, at, d === 4);
    } else if (keyword === 'dependentRequired') {
      if (d < 2019) continue;
      if (value.t !== 'dict') refuse(at, 'an object', value);
      for (const [k, v] of value.v) {
        if (v.t !== 'list') refuse(`${at}/${k}`, 'an array', v);
        v.v.forEach((x, i) => {
          if (x.t !== 'str') refuse(`${at}/${k}/${i}`, 'a string', x);
        });
      }
    } else if (keyword === 'enum') {
      if (value.t !== 'list') refuse(at, 'an array', value);
      if (d === 4) {
        // Draft 4: `"minItems": 1, "uniqueItems": true`; draft 6 on, any array.
        if (value.v.length === 0) throw new PyJsonSchemaUnsupported(`${at} must be a non-empty array`);
        value.v.forEach((v, i) => {
          if (value.v.slice(0, i).some((seen) => pyEqual(seen, v))) {
            throw new PyJsonSchemaUnsupported(`${at} must have unique items, got ${reprValue(v)} twice`);
          }
        });
      }
    } else if (keyword === 'uniqueItems') {
      if (value.t !== 'bool') refuse(at, 'a boolean', value);
    } else if (keyword === 'pattern' || keyword === 'format') {
      if (value.t !== 'str') refuse(at, 'a string', value);
      // `"format": "regex"` on `pattern` in the metaschema, and jsonschema's own format
      // checker compiles it — `{"pattern": "("}` is a SchemaError there, and was
      // `{"valid": true}` here. `reSearch` already refuses a pattern it cannot compile;
      // this only moves the refusal to where Python's is, which is before the instance.
      //
      // THE PRICE, measured and accepted: `re` accepts patterns `RegExp` does not
      // (`(?P<x>…)`, `\A`, `\Z`), so a schema carrying one now refuses HERE even when the
      // keyword would never have fired. Before, it refused only when it fired, and answered
      // otherwise. Both are the same ruled divergence — see the `python re and JS RegExp`
      // ruling — and a refusal in an unreached branch is a smaller error than `{"valid":
      // true}` for a pattern that is not a pattern. Both directions are pinned as ruled
      // cases in `tools/conformance/suites/validate.mjs`.
      if (keyword === 'pattern') reSearch(value.v, '');
    } else if (keyword === 'multipleOf') {
      if (value.t !== 'int' && value.t !== 'float') refuse(at, 'a number', value);
      if (value.t === 'int' ? value.v <= 0n : value.v <= 0) {
        throw new PyJsonSchemaUnsupported(`${at} must be a number greater than 0, got ${reprValue(value)}`);
      }
    } else if (NUMBER_KEYWORDS.includes(keyword)) {
      if (value.t !== 'int' && value.t !== 'float') refuse(at, 'a number', value);
    } else if (keyword === 'exclusiveMaximum' || keyword === 'exclusiveMinimum') {
      if (d === 4) {
        // Draft 4: a boolean modifier, and the metaschema's `dependencies` demand the bound.
        if (value.t !== 'bool') refuse(at, 'a boolean', value);
        const bound = keyword === 'exclusiveMaximum' ? 'maximum' : 'minimum';
        if (!schema.v.has(bound)) {
          throw new PyJsonSchemaUnsupported(`${where}: '${bound}' is a dependency of '${keyword}'`);
        }
      } else if (value.t !== 'int' && value.t !== 'float') refuse(at, 'a number', value);
    } else if (keyword in COUNT_KEYWORDS) {
      if (!knows(d, COUNT_KEYWORDS[keyword]!)) continue;
      // `draft4_type_checker` has no float-with-no-fraction clause: `2.0` is not an integer there.
      const integral = value.t === 'int' || (d !== 4 && value.t === 'float' && Number.isInteger(value.v));
      if (!integral) refuse(at, 'a non-negative integer', value);
      if (value.t === 'int' ? value.v < 0n : (value as { v: number }).v < 0) {
        throw new PyJsonSchemaUnsupported(
          `${at} must be a non-negative integer, got ${reprValue(value)}`,
        );
      }
    } else if (keyword === '$schema') {
      string(value, at);
    } else if (keyword === '$ref') {
      // Draft 4's metaschema has no `$ref` property; the lookup refuses a non-string lazily.
      if (d !== 4) string(value, at);
    } else if (keyword === '$dynamicRef') {
      if (d === 2020) string(value, at);
    } else if (keyword === '$recursiveRef') {
      if (d >= 2019) string(value, at);
    } else if (keyword === '$id') {
      if (d === 4) continue;
      const id = string(value, at);
      // 2019-09 and 2020-12: `"pattern": "^[^#]*#?$"` — an empty fragment at most.
      if (d >= 2019 && !/^[^#]*#?$/.test(id)) {
        throw new PyJsonSchemaUnsupported(`${at} must match ^[^#]*#?$, got ${reprValue(value)}`);
      }
    } else if (keyword === 'id') {
      if (d === 4) string(value, at);
    } else if (keyword === '$anchor') {
      if (d >= 2019) anchor(value, at);
    } else if (keyword === '$dynamicAnchor') {
      if (d === 2020) anchor(value, at);
    }
  }
}

/**
 * `jsonschema.validate(instance, schema)` reduced to what `contract.schema_error` needs:
 * the single error `best_match` chooses, or `null`.
 *
 * In the reference's order: `validator_for` (the dialect, which raises on a non-string
 * `$schema`), then the one-resource pre-scan `contract.py` runs before `validate`, then
 * `check_schema`, then the instance. A `PyJsonSchemaRefusal` out of here is an ANSWER —
 * `contract.schemaError` returns its sentence — and a `PyJsonSchemaUnsupported` is a raise.
 */
export function validate(instance: PyValue, schema: PyValue): PyValidationError | null {
  const draft = dialectOf(schema, 2020);
  if (schema.t === 'dict') refuseUnsupportedReferences(schema, draft);
  checkSchema(schema, 'the schema', draft);
  return bestMatch(iterErrors(instance, schema, { root: schema, draft, rootDraft: draft }));
}

export { iterErrors };
