/**
 * Argument validation, in the reference runtime's own words.
 *
 * WHY THIS IS REPRODUCED RATHER THAN RULED. The text below is not a diagnostic in a log —
 * it is the `content[0].text` of a tool result, which means the MODEL reads it and decides
 * what to do next. `zod`'s wording is entirely different, so a port that let zod speak would
 * ship a server whose recovery behaviour differs from the reference's on every mistyped
 * argument, and that is a product difference, not a cosmetic one.
 *
 * WHAT THE URL IS. `https://errors.pydantic.dev/2.13/v/<type>` names an entry in pydantic's
 * public error catalogue. This runtime has no pydantic; the URL is part of the sentence the
 * reference emits, reproduced because the sentence is the contract. `2.13` is therefore a
 * PIN on the reference, not a claim about this process — and it is compared against the
 * live server by `tools/conformance/suites/wire.mjs`, so the day the Python side bumps to
 * 2.14 the suite goes red here instead of the two runtimes drifting apart quietly.
 *
 * EVERY RULE BELOW WAS MEASURED, not read off pydantic's documentation. The probes are in
 * `scratchpad/job38-n7/probe{4,7,8,9}.py` and each drove the real stdio server:
 *
 *   * errors come in MODEL FIELD order, not in the order the arguments arrived (probe7 id 80
 *     sends `body, name, description, type` and gets `type` before `name`);
 *   * `int` is LAX — `True`, `'2'`, `'  3  '`, `'2_0'`, `'+2'` and `3.0` all validate, while
 *     `'2.5'`, `'1e3'`, `'0x10'` and `''` are `int_parsing` and `2.5` is `int_from_float`;
 *   * a float too large for an i64 is `int_parsing_size`, with a DIFFERENT message shape
 *     (no "Input should be a valid integer," prefix);
 *   * `input_value` is truncated on the UTF-8 BYTE length of `repr(value)`: over 50 bytes it
 *     becomes head-25-bytes + `...` + tail-24-bytes, each end floored to a character
 *     boundary. Thirty Thai characters are 34 repr CHARACTERS and are still truncated.
 */
import { reprValue, type PyValue } from '../pyjson.js';

/** What a parameter accepts. `optional` is `| None = None` in the signature. */
export interface FieldSpec {
  readonly name: string;
  readonly kind: 'str' | 'int' | 'dict' | 'dictInt' | 'listStr';
  readonly optional: boolean;
  /** `Field(le=...)`: an inclusive ceiling, checked AFTER the lax int parse succeeds. */
  readonly le?: bigint;
}

export interface ArgModel {
  /** The pydantic model name, which is the FUNCTION name plus `Arguments`. */
  readonly model: string;
  readonly fields: readonly FieldSpec[];
}

const req = (name: string, kind: FieldSpec['kind']): FieldSpec => ({ name, kind, optional: false });
const opt = (name: string, kind: FieldSpec['kind'], bound: { le?: bigint } = {}): FieldSpec => ({
  name,
  kind,
  optional: true,
  ...bound,
});

/**
 * `assets/tools/bantamkit_read.json` `offset.maximum` — `Number.MAX_SAFE_INTEGER`, the
 * largest integer `JSON.parse` reads back unchanged (F1). The reference binds it as
 * `Annotated[int, Field(le=OFFSET_MAXIMUM)]`, so above it the refusal is pydantic's
 * `less_than_equal` frame and the handler never runs; this side reads the JSON with its
 * own decoder, so `9007199254740993` arrives exact and is refused with the same text.
 */
const OFFSET_MAXIMUM = 9007199254740991n;

/**
 * One model per handler, mirroring `build_server`'s closures signature for signature.
 *
 * `build_identity`'s model is `build_identity_toolArguments` and not `build_identityArguments`
 * — pydantic names it after the PYTHON FUNCTION, and the function is the closure
 * `build_identity_tool`. The same leak is already in the shipped manifest
 * (`output_schema.title` is `build_identity_toolDictOutput`), so the name is not an accident
 * this port gets to tidy: it is on the wire today, and a client that pinned it would break.
 *
 * MEASURED SURVIVOR, AND IT STAYS. A mutation changing this one string to
 * `build_identityArguments` survives both gates, because `build_identity` has no parameters
 * and a model with no fields can never fail — the name is unreachable from the wire. It is
 * still spelled correctly: the day the tool grows an argument, the sweep's kill comes for
 * free, and a name that was wrong until then would be a defect nobody planted. The leak that
 * IS observable is the manifest's `output_schema.title`, and that one is compared byte for
 * byte by the conformance suite's `advertisement: id 2` case.
 */
export const ARG_MODELS: Readonly<Record<string, ArgModel>> = {
  memory_save: {
    model: 'memory_saveArguments',
    fields: [req('type', 'str'), req('name', 'str'), req('description', 'str'), req('body', 'str'), opt('links', 'listStr')],
  },
  memory_recall: { model: 'memory_recallArguments', fields: [req('query', 'str'), opt('k', 'int')] },
  validate_json: { model: 'validate_jsonArguments', fields: [req('output', 'str'), req('schema', 'dict')] },
  shiftwork_clock_in: { model: 'shiftwork_clock_inArguments', fields: [req('checkpoint', 'str')] },
  shiftwork_clock_out: {
    model: 'shiftwork_clock_outArguments',
    fields: [
      req('checkpoint', 'str'),
      req('unit_id', 'str'),
      req('status', 'str'),
      req('handoff_patch', 'dict'),
      req('history_entry', 'dict'),
      opt('accounting', 'dict'),
    ],
  },
  shiftwork_status: { model: 'shiftwork_statusArguments', fields: [req('checkpoint', 'str')] },
  build_identity: { model: 'build_identity_toolArguments', fields: [] },
  // `bantamkit_statusArguments`, not `bantamkit_status_toolArguments`: the model name is
  // pydantic's, derived from the reference's CLOSURE name, and the status handler is called
  // `bantamkit_status` there where the identity one is called `build_identity_tool`. It is
  // the title `assets/tools/bantamkit_status.json` already advertises.
  bantamkit_status: { model: 'bantamkit_statusArguments', fields: [] },
  // `reserve: int | None = None` on the reference, so it is the same lax `int` as `k`:
  // `'2'`, `True` and `3.0` validate, `'2.5'` is `int_parsing`, `2.5` is `int_from_float`,
  // and an explicit `null` is the default. The manifest's `minimum: 0` is advisory to the
  // client; nothing here floors it — a negative value reaches `MemoryStore.compact`, whose
  // `max(0, min(reserve, budget // 2))` is the only clamp on either side (6b966e5).
  memory_compact: { model: 'memory_compactArguments', fields: [opt('reserve', 'int')] },
  // `bantamkit_read(path: str, part: str | None = None, offset: int | None = None,
  // limit: int | None = None)` on the reference (job43). `path` and `part` are the strict
  // `str` every other string field is — `123` is `string_type`, measured for `memory_save`
  // and the same validator. `offset` and `limit` are the lax `int` that `k` and `reserve`
  // are: `'2'`, `True` and `3.0` validate, `'2.5'` is `int_parsing`, `2.5` is
  // `int_from_float`, and an explicit `null` is the default. The manifest's `minimum` and
  // `maximum` are advisory to the client for `limit` and for `offset`'s floor; the handler
  // clamps `limit` to `[1, 200]` and `offset` to `>= 0` itself, the way `memory_recall`
  // clamps `k`. `offset`'s CEILING is bound in the model, as it is on the reference (F2).
  bantamkit_read: {
    model: 'bantamkit_readArguments',
    fields: [req('path', 'str'), opt('part', 'str'), opt('offset', 'int', { le: OFFSET_MAXIMUM }), opt('limit', 'int')],
  },
  // `skill_audit(root: str, enabled: list[str] | None = None, usage: dict[str, int] | None =
  // None, check: str | None = None, budget: int | None = None)` on the reference (job44).
  // `usage` is the only `dict[str, int]` on the surface and the reason `dictInt` exists:
  // pydantic validates a typed dict's VALUES, so `{'a': 'x'}` is `usage.a` / `int_parsing`
  // where `handoff_patch`'s `dict[str, Any]` takes anything. `budget` carries no `le`,
  // because the reference binds none — the manifest's `maximum` is advisory to the client,
  // and the handler's own refusal is the negative one.
  skill_audit: {
    model: 'skill_auditArguments',
    fields: [
      req('root', 'str'),
      opt('enabled', 'listStr'),
      opt('usage', 'dictInt'),
      opt('check', 'str'),
      opt('budget', 'int'),
    ],
  },
};

/** `type(value).__name__`, for the `input_type=` half of the sentence. */
function pyTypeName(value: PyValue): string {
  switch (value.t) {
    case 'null':
      return 'NoneType';
    case 'bool':
      return 'bool';
    case 'int':
      return 'int';
    case 'float':
      return 'float';
    case 'str':
      return 'str';
    case 'list':
      return 'list';
    case 'dict':
      return 'dict';
  }
}

const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8');

/**
 * pydantic-core's `truncate_input_value`: 50 UTF-8 bytes, then `head[..25] + "..." + tail[24..]`
 * with both cuts moved off a multi-byte character rather than splitting one.
 *
 * The floor at each end is what makes 30 Thai characters render as 7 + `...` + 7 instead of
 * 8 + `...` + 8 — measured, probe8 case 104.
 */
function truncateRepr(text: string): string {
  const bytes = encoder.encode(text);
  if (bytes.length <= 50) return text;
  let head = 25;
  while (head > 0 && (bytes[head]! & 0xc0) === 0x80) head -= 1;
  let tail = bytes.length - 24;
  while (tail < bytes.length && (bytes[tail]! & 0xc0) === 0x80) tail += 1;
  return `${decoder.decode(bytes.slice(0, head))}...${decoder.decode(bytes.slice(tail))}`;
}

interface RawError {
  readonly loc: string;
  readonly type: string;
  readonly msg: string;
  readonly input: PyValue;
}

/** i64, which is the width pydantic parses an int into before it complains about size. */
const I64_MAX = 9223372036854775807n;
const I64_MIN = -9223372036854775808n;

/** `int(text)` as Python accepts it: optional sign, underscores between digits. */
const PY_INT_TEXT = /^[+-]?\d+(?:_\d+)*$/;
/** …and pydantic additionally accepts a trailing `.0`-style fraction that is all zeros. */
const PY_INT_DECIMAL_TEXT = /^([+-]?\d+(?:_\d+)*)\.0+$/;

/**
 * Validate one field, returning either the coerced value or the error pydantic reports.
 *
 * Lax mode, which is pydantic's default and therefore the reference's: `bool` IS an `int`
 * here, and a string that spells an integer IS one. Only `str` is strict, because pydantic
 * refuses every non-`str` for a `str` field even in lax mode (measured: `123` -> string_type).
 */
function checkField(spec: FieldSpec, value: PyValue): { value: PyValue } | RawError[] {
  if (spec.optional && value.t === 'null') return { value };
  switch (spec.kind) {
    case 'str':
      if (value.t === 'str') return { value };
      return [{ loc: spec.name, type: 'string_type', msg: 'Input should be a valid string', input: value }];
    case 'dict':
      if (value.t === 'dict') return { value };
      return [{ loc: spec.name, type: 'dict_type', msg: 'Input should be a valid dictionary', input: value }];
    case 'dictInt': {
      // `dict[str, int]`. pydantic validates the VALUES too, one error per bad entry and in
      // the dict's own order, with the KEY in the location — `usage.a`, never `usage.0`. The
      // coerced value is what the handler gets, so `{'a': '0'}` reaches `skillaudit` as `0`
      // and is a `never-invoked` finding exactly as `{'a': 0}` is.
      if (value.t !== 'dict') {
        return [{ loc: spec.name, type: 'dict_type', msg: 'Input should be a valid dictionary', input: value }];
      }
      const bad: RawError[] = [];
      const coerced = new Map<string, PyValue>();
      for (const [key, item] of value.v) {
        const checked = checkInt(`${spec.name}.${key}`, item);
        if ('value' in checked) coerced.set(key, checked.value);
        else bad.push(checked);
      }
      return bad.length > 0 ? bad : { value: { t: 'dict', v: coerced } };
    }
    case 'listStr': {
      if (value.t !== 'list') {
        return [{ loc: spec.name, type: 'list_type', msg: 'Input should be a valid list', input: value }];
      }
      // EVERY bad item, not the first: pydantic validates the whole list and reports one
      // error per element, so `links: [1, 'ok', None]` is TWO errors, `links.0` and `links.2`.
      const bad: RawError[] = [];
      for (let i = 0; i < value.v.length; i += 1) {
        const item = value.v[i]!;
        if (item.t !== 'str') {
          bad.push({ loc: `${spec.name}.${i}`, type: 'string_type', msg: 'Input should be a valid string', input: item });
        }
      }
      return bad.length > 0 ? bad : { value };
    }
    case 'int': {
      const checked = checkInt(spec.name, value);
      if (!('value' in checked)) return [checked];
      // `less_than_equal` names the ORIGINAL input, as every constraint error does.
      if (spec.le !== undefined && checked.value.t === 'int' && checked.value.v > spec.le) {
        return [
          {
            loc: spec.name,
            type: 'less_than_equal',
            msg: `Input should be less than or equal to ${spec.le}`,
            input: value,
          },
        ];
      }
      return checked;
    }
  }
}

function checkInt(loc: string, value: PyValue): { value: PyValue } | RawError {
  const tooBig = (): RawError => ({
    loc,
    type: 'int_parsing_size',
    msg: 'Unable to parse input string as an integer, exceeded maximum size',
    input: value,
  });
  if (value.t === 'int') {
    return value.v > I64_MAX || value.v < I64_MIN ? tooBig() : { value };
  }
  if (value.t === 'bool') return { value: { t: 'int', v: value.v ? 1n : 0n } };
  if (value.t === 'float') {
    if (!Number.isInteger(value.v)) {
      return {
        loc,
        type: 'int_from_float',
        msg: 'Input should be a valid integer, got a number with a fractional part',
        input: value,
      };
    }
    if (!(Math.abs(value.v) <= 9223372036854775807)) return tooBig();
    return { value: { t: 'int', v: BigInt(value.v) } };
  }
  if (value.t === 'str') {
    const text = value.v.trim();
    const decimal = PY_INT_DECIMAL_TEXT.exec(text);
    const digits = PY_INT_TEXT.test(text) ? text : decimal?.[1];
    if (digits === undefined) {
      return {
        loc,
        type: 'int_parsing',
        msg: 'Input should be a valid integer, unable to parse string as an integer',
        input: value,
      };
    }
    const parsed = BigInt(digits.replace(/_/g, ''));
    return parsed > I64_MAX || parsed < I64_MIN ? tooBig() : { value: { t: 'int', v: parsed } };
  }
  return { loc, type: 'int_type', msg: 'Input should be a valid integer', input: value };
}

/**
 * The pydantic `ValidationError` text, WITHOUT the `Error executing tool <name>: ` prefix.
 *
 * The prefix is the SDK's, added by `Tool.run`'s `except Exception` for every failure a tool
 * can have — not just an argument one — so it belongs at the one place that catches them all.
 */
export class PyValidationFailure extends Error {
  constructor(readonly detail: string) {
    super(detail);
    this.name = 'PyValidationFailure';
  }
}

/**
 * `model.model_validate(arguments)` for one tool, or the exact `ValidationError` text.
 *
 * Unknown keys are IGNORED, because pydantic's default `model_config` ignores them and the
 * measured server accepts `{"query": "a", "extra": 1}` without complaint. The absent-key case
 * and the explicit-`null` case are different: `{}` is `missing`, `{"handoff_patch": null}` is
 * `dict_type`, and only an OPTIONAL field treats `null` as its default.
 */
export function validateArguments(model: ArgModel, args: PyValue): Map<string, PyValue> {
  const supplied = args.t === 'dict' ? args.v : new Map<string, PyValue>();
  const errors: RawError[] = [];
  const bound = new Map<string, PyValue>();
  for (const spec of model.fields) {
    if (!supplied.has(spec.name)) {
      if (spec.optional) {
        bound.set(spec.name, { t: 'null' });
        continue;
      }
      errors.push({ loc: spec.name, type: 'missing', msg: 'Field required', input: args });
      continue;
    }
    const checked = checkField(spec, supplied.get(spec.name)!);
    if (Array.isArray(checked)) errors.push(...checked);
    else bound.set(spec.name, checked.value);
  }
  if (errors.length === 0) return bound;

  const count = errors.length;
  const head = `${count} validation error${count === 1 ? '' : 's'} for ${model.model}`;
  const body = errors
    .map(
      (e) =>
        `${e.loc}\n  ${e.msg} [type=${e.type}, input_value=${truncateRepr(reprValue(e.input))}, ` +
        `input_type=${pyTypeName(e.input)}]\n    For further information visit ` +
        `https://errors.pydantic.dev/2.13/v/${e.type}`,
    )
    .join('\n');
  throw new PyValidationFailure(`${head}\n${body}`);
}
