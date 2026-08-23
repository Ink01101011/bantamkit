/**
 * The `jsonschema` seam: `Draft202012Validator.iter_errors` + `exceptions.best_match`.
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
 * WHAT IS IMPLEMENTED. Draft 2020-12, which is the checkpoint schema's dialect and also
 * jsonschema's default for a schema with no `$schema` — the shape `validate_json` receives.
 * 30 of the 36 keywords in `Draft202012Validator.VALIDATORS`. The other six RAISE rather
 * than answer plausibly: `$ref` and `$dynamicRef` need a reference resolver,
 * `unevaluatedItems`/`unevaluatedProperties` need annotation collection, and neither appears
 * anywhere in the asset pack (measured: `assets/**\/*.json`). `format` is implemented as the
 * no-op it is — `jsonschema.validate` passes no `format_checker`, so the keyword can never
 * produce an error on this path.
 *
 * WHAT IS NOT IMPLEMENTED, AND WHY THAT IS A RULING AND NOT A GAP.
 * `jsonschema.validate` calls `cls.check_schema(schema)` FIRST, so an invalid schema raises
 * `SchemaError` before any instance is looked at — and `contract.schema_error` catches only
 * `ValidationError`, so that exception escapes `validate_json` to the caller. Reproducing it
 * means shipping the 2020-12 metaschema and validating against it. This port instead raises
 * `PyJsonSchemaUnsupported` at the point it meets a construct it cannot honour. Both
 * runtimes refuse; the sentence differs. Registered as a ruled case, and registered as a
 * runtime-py defect: `validate_json` lets an exception out on caller input.
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
 * `jsonschema.exceptions.ValidationError`, narrowed to the fields the relevance heuristic
 * and `schema_error` read.
 *
 * `path` is the RELATIVE path, which is what `relevance` sorts on, and `parent` is set only
 * for the context errors an `anyOf`/`oneOf` carries. `absolutePath` walks the chain, which
 * is what `schema_error` interpolates. Keeping the two apart is not pedantry: `best_match`
 * ranks context errors by their relative paths and then `schema_error` prints an absolute
 * one, and a port that conflated them would name the wrong field inside every `anyOf`.
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
 * `draft202012_type_checker`.
 *
 * Two Python-isms carry: `bool` is not an `int`, so `true` is neither `integer` nor
 * `number`; and draft 6 onward redefines `integer` to accept a float with no fractional
 * part, so `1.0` IS an integer.
 */
function isType(instance: PyValue, type: string): boolean {
  switch (type) {
    case 'array':
      return instance.t === 'list';
    case 'boolean':
      return instance.t === 'bool';
    case 'integer':
      return instance.t === 'int' || (instance.t === 'float' && Number.isInteger(instance.v));
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

type Emit = (
  message: string,
  extra?: { validator?: string; context?: PyValidationError[] },
) => PyValidationError;

/** One keyword's implementation, transcribed from `jsonschema/_keywords.py`. */
type Keyword = (
  value: PyValue,
  instance: PyValue,
  schema: PyValue | boolean,
  emit: Emit,
  descend: Descend,
) => PyValidationError[];

type Descend = (
  instance: PyValue,
  schema: PyValue | undefined,
  path?: string | number,
) => PyValidationError[];

function iterErrors(instance: PyValue, schema: PyValue | boolean): PyValidationError[] {
  if (schema === true) return [];
  if (schema === false) {
    return [
      {
        message: `False schema does not allow ${reprValue(instance)}`,
        validator: null,
        instance,
        schema,
        path: [],
        context: [],
        parent: null,
      },
    ];
  }
  if (schema.t === 'bool') return iterErrors(instance, schema.v);
  if (schema.t !== 'dict') {
    throw new PyJsonSchemaUnsupported(`a schema must be an object or a boolean, got ${schema.t}`);
  }

  const out: PyValidationError[] = [];
  // `applicable_validators` for draft 2020-12 is `methodcaller("items")` — plain dict order,
  // which for a JSON-parsed schema is DOCUMENT order. That order decides which error comes
  // first, and `best_match` breaks ties by taking the first maximum, so it is load-bearing.
  for (const [keyword, value] of schema.v) {
    const fn = KEYWORDS[keyword];
    if (fn === undefined) {
      if (UNSUPPORTED.has(keyword)) {
        throw new PyJsonSchemaUnsupported(`${keyword} is not implemented by this port`);
      }
      continue; // an annotation (`title`, `$comment`, `description`, …) — jsonschema skips it too
    }
    const emit: Emit = (message, extra = {}) => ({
      message,
      validator: extra.validator ?? keyword,
      instance,
      schema,
      path: [],
      context: extra.context ?? [],
      parent: null,
    });
    const descend: Descend = (childInstance, childSchema, path) => {
      if (childSchema === undefined) return [];
      // `Validator.descend` handles a boolean subschema and RETURNS, before the loop that
      // prepends `path`. So `{"properties": {"k": false}}` reports at `root` and not at `k`.
      // Measured against Python; a port that prepended here would name a field Python does
      // not name.
      if (childSchema.t === 'bool') return iterErrors(childInstance, childSchema.v);
      const errors = iterErrors(childInstance, childSchema);
      if (path !== undefined) for (const e of errors) e.path.unshift(path);
      return errors;
    };
    out.push(...fn(value, instance, schema, emit, descend));
  }
  return out;
}

const isValid = (instance: PyValue, schema: PyValue): boolean =>
  iterErrors(instance, schema).length === 0;

const UNSUPPORTED = new Set([
  '$ref',
  '$dynamicRef',
  '$recursiveRef',
  'unevaluatedItems',
  'unevaluatedProperties',
]);

/** `extras_msg`: `"'a', 'b'", "were"`. */
function extrasMsg(extras: string[]): [string, string] {
  return [extras.map((e) => reprValue({ t: 'str', v: e })).join(', '), extras.length === 1 ? 'was' : 'were'];
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

const KEYWORDS: Record<string, Keyword> = {
  type(value, instance, _schema, emit) {
    // `ensure_list`: a bare string becomes a one-element list, anything else passes through.
    const types = value.t === 'str' ? [value] : value.t === 'list' ? value.v : [value];
    if (types.some((t) => t.t === 'str' && isType(instance, t.v))) return [];
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

  contains(value, instance, schema, emit) {
    if (instance.t !== 'list') return [];
    const minRaw = get(schema, 'minContains');
    const maxRaw = get(schema, 'maxContains');
    const minContains = minRaw === undefined ? 1 : asNumber(minRaw);
    const maxContains = maxRaw === undefined ? instance.v.length : asNumber(maxRaw);
    let matches = 0;
    for (const each of instance.v) {
      if (isValid(each, value)) {
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

  anyOf(value, instance, _schema, emit) {
    if (value.t !== 'list') return [];
    const allErrors: PyValidationError[] = [];
    for (const subschema of value.v) {
      const errs = iterErrors(instance, subschema);
      if (errs.length === 0) return [];
      allErrors.push(...errs);
    }
    const error = emit(`${reprValue(instance)} is not valid under any of the given schemas`, {
      context: allErrors,
    });
    for (const child of allErrors) child.parent = error;
    return [error];
  },

  oneOf(value, instance, _schema, emit) {
    if (value.t !== 'list') return [];
    const out: PyValidationError[] = [];
    const allErrors: PyValidationError[] = [];
    let firstValid: PyValue | null = null;
    let index = 0;
    for (; index < value.v.length; index += 1) {
      const errs = iterErrors(instance, value.v[index]!);
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
    const moreValid = value.v.slice(index + 1).filter((each) => isValid(instance, each));
    if (moreValid.length > 0) {
      const reprs = [...moreValid, firstValid!].map(reprValue).join(', ');
      out.push(emit(`${reprValue(instance)} is valid under each of ${reprs}`));
    }
    return out;
  },

  not(value, instance, _schema, emit) {
    if (!isValid(instance, value)) return [];
    return [emit(`${reprValue(instance)} should not be valid under ${reprValue(value)}`)];
  },

  if(value, instance, schema, _emit, descend) {
    if (isValid(instance, value)) {
      const then = get(schema, 'then');
      return then === undefined ? [] : descend(instance, then);
    }
    const otherwise = get(schema, 'else');
    return otherwise === undefined ? [] : descend(instance, otherwise);
  },
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
  if (expected.t === 'str') return isType(error.instance, expected.v);
  if (expected.t === 'list') {
    return expected.v.some((t) => isType(error.instance, (t as { v: string }).v));
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

/**
 * `jsonschema.validate(instance, schema)` reduced to what `contract.schema_error` needs:
 * the single error `best_match` chooses, or `null`.
 *
 * `check_schema` is NOT run — see the module header for the ruling.
 */
export function validate(instance: PyValue, schema: PyValue): PyValidationError | null {
  return bestMatch(iterErrors(instance, schema));
}

export { iterErrors };
