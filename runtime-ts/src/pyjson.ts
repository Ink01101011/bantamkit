/**
 * The CPython `json` seam: `JSONDecoder().raw_decode`, `json.dumps`, and `repr()` of what
 * the decoder returns.
 *
 * WHY THIS IS NOT `JSON.parse`. `contract.extract_json` calls `raw_decode`, and every
 * validation sentence downstream interpolates `{instance!r}` — Python's `repr` of the value
 * the decoder built. Four things separate that from `JSON.parse`:
 *
 *   1. **int is not float.** `{"n": 1.0}` gives Python a `float` whose repr is `1.0`;
 *      `JSON.parse` gives `1`, and the sentence would name a value the model never wrote.
 *   2. **int is arbitrary precision.** `12345678901234567890` survives Python exactly and
 *      rounds to `12345678901234567000` through a JS number.
 *   3. **`NaN`, `Infinity` and `-Infinity` are accepted** by CPython's decoder and rejected
 *      by `JSON.parse`; their reprs are `nan`, `inf`, `-inf`.
 *   4. **the failure text is the product.** `parse_error_message` interpolates the decoder's
 *      own exception, so `Expecting ':' delimiter: line 1 column 6 (char 5)` reaches the
 *      model verbatim, character offsets included.
 *
 * Ported against the **C** scanner (`_json.c`), which is what a stock CPython uses and whose
 * messages differ from the pure-Python fallback in `json/decoder.py`: the C scanner writes
 * `Invalid \escape` and `Invalid control character at` with NO repr of the offending
 * character, and reports the position of the backslash rather than the position after it.
 * That was measured, not read — see `tools/conformance/suites/validate.mjs`.
 *
 * POSITIONS ARE IN CODEPOINTS. Python indexes `str` by codepoint and JS indexes by UTF-16
 * unit, so `{"\u{1F600}":1,}` is `char 7` in Python and would be `char 8` from a naive
 * `.length`. Parsing runs on the JS string with UTF-16 indices — that is what the regexes
 * and `slice` want — and every index that reaches a MESSAGE is converted on the way out.
 */
import { cmpCodepoint, pyRepr as pyReprString } from './memory/pyfs.js';

// ------------------------------------------------------------------------- the value

/**
 * A JSON document as CPython's decoder builds it.
 *
 * Tagged rather than native because two of the tags are indistinguishable in JS: `int` and
 * `float` are one type there, and `1` and `1.0` must not print the same. `int` carries a
 * `bigint` because Python's does not overflow.
 */
export type PyValue =
  | { readonly t: 'null' }
  | { readonly t: 'bool'; readonly v: boolean }
  | { readonly t: 'int'; readonly v: bigint }
  | { readonly t: 'float'; readonly v: number }
  | { readonly t: 'str'; readonly v: string }
  | { readonly t: 'list'; readonly v: PyValue[] }
  | { readonly t: 'dict'; readonly v: Map<string, PyValue> };

export const PY_NONE: PyValue = { t: 'null' };

/**
 * Lift a plain JS value into the tagged form.
 *
 * RULING — the one place this port cannot recover Python's answer. A JS number carries no
 * record of whether its JSON text had a decimal point, so `1` and `1.0` arrive identical and
 * this maps every integral, safe-range number to `int`. That is exact for every schema
 * bantamkit ships (measured: the whole asset pack holds no non-integral number, and the only
 * numeric keywords in it are `minimum`/`maximum` with integer bounds). It is NOT exact for a
 * caller-supplied schema written `{"minimum": 1.0}`, where Python says
 * `is less than the minimum of 1.0` and this says `1`. `parseJson` is the exact route and
 * the MCP server should use it wherever it still holds the wire bytes; `fromJs` is the
 * fallback for a value that has already been through an SDK's parser. Carried as a ruled
 * case in `tools/conformance/suites/validate.mjs`.
 */
export function fromJs(value: unknown): PyValue {
  if (value === null || value === undefined) return PY_NONE;
  if (typeof value === 'boolean') return { t: 'bool', v: value };
  if (typeof value === 'bigint') return { t: 'int', v: value };
  if (typeof value === 'number') {
    return Number.isSafeInteger(value) && !Object.is(value, -0)
      ? { t: 'int', v: BigInt(value) }
      : { t: 'float', v: value };
  }
  if (typeof value === 'string') return { t: 'str', v: value };
  if (Array.isArray(value)) return { t: 'list', v: value.map(fromJs) };
  if (value instanceof Map) {
    const out = new Map<string, PyValue>();
    for (const [k, v] of value) out.set(String(k), fromJs(v));
    return { t: 'dict', v: out };
  }
  if (typeof value === 'object') {
    const out = new Map<string, PyValue>();
    for (const [k, v] of Object.entries(value)) out.set(k, fromJs(v));
    return { t: 'dict', v: out };
  }
  throw new TypeError(`cannot lift ${typeof value} into a PyValue`);
}

/** Back to plain JS, for a caller that only wants the data. Precision may be lost. */
export function toJs(value: PyValue): unknown {
  switch (value.t) {
    case 'null':
      return null;
    case 'bool':
    case 'float':
    case 'str':
      return value.v;
    case 'int':
      return Number(value.v);
    case 'list':
      return value.v.map(toJs);
    case 'dict': {
      const out: Record<string, unknown> = {};
      for (const [k, v] of value.v) out[k] = toJs(v);
      return out;
    }
  }
}

// -------------------------------------------------------------------------------- repr

/**
 * `repr(float)`.
 *
 * CPython formats with `PyOS_double_to_string(v, 'r', 0, Py_DTSF_ADD_DOT_0)`: the shortest
 * decimal that round-trips, rendered in scientific notation when the decimal point falls at
 * or left of position -4 or right of position 16, and with a forced `.0` otherwise. JS
 * agrees on the DIGITS (`toExponential()` with no argument is also shortest-round-trip) and
 * on nothing else: it switches to scientific at 1e21 and 1e-7, writes `10000000000000000`
 * where Python writes `1e+16`, and never pads the exponent to two digits.
 */
export function pyFloatRepr(x: number): string {
  if (Number.isNaN(x)) return 'nan';
  if (x === Infinity) return 'inf';
  if (x === -Infinity) return '-inf';
  const negative = x < 0 || Object.is(x, -0);
  const [mantissa, exponent] = Math.abs(x).toExponential().split('e') as [string, string];
  const digits = mantissa.replace('.', '');
  const decpt = Number(exponent) + 1; // digits[0] sits just left of position `decpt`
  const sign = negative ? '-' : '';
  if (decpt <= -4 || decpt > 16) {
    const head = digits.slice(0, 1);
    const tail = digits.slice(1).replace(/0+$/, '');
    const e = decpt - 1;
    const eSign = e < 0 ? '-' : '+';
    return `${sign}${head}${tail ? `.${tail}` : ''}e${eSign}${String(Math.abs(e)).padStart(2, '0')}`;
  }
  if (decpt <= 0) return `${sign}0.${'0'.repeat(-decpt)}${digits}`;
  if (decpt >= digits.length) return `${sign}${digits}${'0'.repeat(decpt - digits.length)}.0`;
  return `${sign}${digits.slice(0, decpt)}.${digits.slice(decpt)}`;
}

/** `repr()` of a decoded JSON document, exactly as an error sentence interpolates it. */
export function reprValue(value: PyValue): string {
  switch (value.t) {
    case 'null':
      return 'None';
    case 'bool':
      return value.v ? 'True' : 'False';
    case 'int':
      return value.v.toString();
    case 'float':
      return pyFloatRepr(value.v);
    case 'str':
      return pyReprString(value.v);
    case 'list':
      return `[${value.v.map(reprValue).join(', ')}]`;
    case 'dict':
      return `{${[...value.v].map(([k, v]) => `${pyReprString(k)}: ${reprValue(v)}`).join(', ')}}`;
  }
}

// ------------------------------------------------------------------------- the encoder

/**
 * `json.dumps`, which is the OTHER half of this seam and the one that writes files.
 *
 * `JSON.stringify` differs from it in four ways, every one of which silently corrupts a
 * shift-work checkpoint rather than failing:
 *
 *   1. **`ensure_ascii=True`.** Python escapes every codepoint outside ` `..`~` as
 *      `\uXXXX`, astral ones as a surrogate PAIR. `JSON.stringify` emits them raw. The
 *      document still round-trips to the same string, so nothing errors — the file just
 *      stops being byte-comparable with the one Python writes, and the whole 29 KB of a
 *      real checkpoint gets rewritten on the first successful clock-out.
 *   2. **separators.** `(', ', ': ')` with no indent, `(',', ': ')` with one.
 *      `JSON.stringify` uses neither.
 *   3. **`sort_keys` is a codepoint sort.** JS `Array.sort` on strings is UTF-16 order,
 *      which puts every astral key before U+E000 instead of after it.
 *   4. **`5.0` is a float.** `JSON.stringify({n: 5.0})` is `{"n":5}`. Python keeps the
 *      decimal point because it kept the type, which is why this module carries a tagged
 *      value model at all.
 *
 * Also faithful: `allow_nan=True` emits the bare words `NaN`, `Infinity` and `-Infinity`
 * that no JSON parser accepts, and `/` is NOT escaped.
 */
export interface DumpOptions {
  /** Spaces per level. `null`/omitted is Python's `indent=None` — everything on one line. */
  indent?: number | null;
  /** Python's `sort_keys`. The comparison is by CODEPOINT, not by UTF-16 unit. */
  sortKeys?: boolean;
}

/**
 * `json/encoder.py`'s `ESCAPE_DCT`: the seven short escapes, then `\u00xx` for the rest of
 * C0. Everything from ` ` (0x20) through `~` (0x7e) that is not `"` or `\` is literal, and
 * everything else — DEL included — is `\uXXXX`.
 */
const ESCAPE_DCT: Record<string, string> = {
  '\\': '\\\\',
  '"': '\\"',
  '\b': '\\b',
  '\f': '\\f',
  '\n': '\\n',
  '\r': '\\r',
  '\t': '\\t',
};

/**
 * `py_encode_basestring_ascii`.
 *
 * The loop walks UTF-16 units on purpose: a lone surrogate half is exactly what Python
 * emits for an astral character under `ensure_ascii`, so iterating by codepoint would only
 * have to split every pair back apart.
 */
function encodeBasestringAscii(s: string): string {
  let out = '"';
  for (let i = 0; i < s.length; i += 1) {
    const ch = s[i]!;
    const short = ESCAPE_DCT[ch];
    if (short !== undefined) {
      out += short;
      continue;
    }
    const unit = s.charCodeAt(i);
    out += unit >= 0x20 && unit <= 0x7e ? ch : `\\u${unit.toString(16).padStart(4, '0')}`;
  }
  return `${out}"`;
}

/** `floatstr` under `allow_nan=True`: `repr` for the finite ones, bare words for the rest. */
function encodeFloat(x: number): string {
  if (Number.isNaN(x)) return 'NaN';
  if (x === Infinity) return 'Infinity';
  if (x === -Infinity) return '-Infinity';
  return pyFloatRepr(x);
}

export function dumpJson(value: PyValue, options: DumpOptions = {}): string {
  const indent = options.indent ?? null;
  const sortKeys = options.sortKeys ?? false;
  const pad = indent === null ? '' : ' '.repeat(indent);
  // `indent is not None` changes the ITEM separator and leaves the key separator alone.
  const itemSep = indent === null ? ', ' : ',';
  const keySep = ': ';

  const encode = (v: PyValue, level: number): string => {
    switch (v.t) {
      case 'null':
        return 'null';
      case 'bool':
        return v.v ? 'true' : 'false';
      case 'int':
        return v.v.toString();
      case 'float':
        return encodeFloat(v.v);
      case 'str':
        return encodeBasestringAscii(v.v);
      case 'list': {
        if (v.v.length === 0) return '[]';
        const parts = v.v.map((item) => encode(item, level + 1));
        if (indent === null) return `[${parts.join(itemSep)}]`;
        const nl = `\n${pad.repeat(level + 1)}`;
        return `[${nl}${parts.join(itemSep + nl)}\n${pad.repeat(level)}]`;
      }
      case 'dict': {
        if (v.v.size === 0) return '{}';
        const entries = [...v.v];
        // `sorted(dct.items())` — keys are unique, so the value never enters the compare.
        if (sortKeys) entries.sort((a, b) => cmpCodepoint(a[0], b[0]));
        const parts = entries.map(
          ([k, item]) => `${encodeBasestringAscii(k)}${keySep}${encode(item, level + 1)}`,
        );
        if (indent === null) return `{${parts.join(itemSep)}}`;
        const nl = `\n${pad.repeat(level + 1)}`;
        return `{${nl}${parts.join(itemSep + nl)}\n${pad.repeat(level)}}`;
      }
    }
  };

  return encode(value, 0);
}

// ------------------------------------------------------------------------- the decoder

/** `json.JSONDecodeError`. `message` is what `str(e)` gives, which is what the model reads. */
export class PyJSONDecodeError extends Error {
  readonly msg: string;
  readonly pos: number;
  readonly lineno: number;
  readonly colno: number;

  constructor(msg: string, doc: string, utf16Pos: number) {
    const head = [...doc.slice(0, utf16Pos)];
    const pos = head.length;
    let lastNewline = -1;
    let lines = 1;
    for (let i = 0; i < head.length; i += 1) {
      if (head[i] === '\n') {
        lastNewline = i;
        lines += 1;
      }
    }
    super(`${msg}: line ${lines} column ${pos - lastNewline} (char ${pos})`);
    this.name = 'PyJSONDecodeError';
    this.msg = msg;
    this.pos = pos;
    this.lineno = lines;
    this.colno = pos - lastNewline;
  }
}

/** `ValueError`, the base `extract_json` raises and `schema_error` catches. */
export class PyValueError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PyValueError';
  }
}

const WS = ' \t\n\r';
/**
 * `nextchar in _ws` where `nextchar` came from `s[end:end+1]`.
 *
 * Past the end that slice is `''`, and `'' in ' \t\n\r'` is TRUE in Python — the empty
 * string is a substring of everything. Two of the decoder's branches depend on it.
 */
const isWs = (ch: string): boolean => ch === '' || WS.includes(ch);

const skipWs = (s: string, i: number): number => {
  let at = i;
  while (at < s.length && WS.includes(s[at]!)) at += 1;
  return at;
};

const BACKSLASH: Record<string, string> = {
  '"': '"',
  '\\': '\\',
  '/': '/',
  b: '\b',
  f: '\f',
  n: '\n',
  r: '\r',
  t: '\t',
};

/** `c_scanstring`, entered just past the opening quote. Returns [value, end]. */
function scanString(s: string, start: number): [string, number] {
  const begin = start - 1;
  let end = start;
  let out = '';
  for (;;) {
    let next = end;
    let terminator = '';
    while (next < s.length) {
      const c = s[next]!;
      if (c === '"' || c === '\\') {
        terminator = c;
        break;
      }
      if (c <= '\u001f') throw new PyJSONDecodeError('Invalid control character at', s, next);
      next += 1;
    }
    if (terminator === '') throw new PyJSONDecodeError('Unterminated string starting at', s, begin);
    if (next !== end) out += s.slice(end, next);
    next += 1;
    if (terminator === '"') return [out, next];
    if (next === s.length) throw new PyJSONDecodeError('Unterminated string starting at', s, begin);
    const esc = s[next]!;
    if (esc !== 'u') {
      const ch = BACKSLASH[esc];
      // The C scanner reports the BACKSLASH, not the chunk start and not the escape letter.
      // Measured: `"a\\q"` is char 2 and `"\\q"` is char 1.
      if (ch === undefined) throw new PyJSONDecodeError('Invalid \\escape', s, next - 1);
      out += ch;
      end = next + 1;
      continue;
    }
    let uni = decodeUXXXX(s, next);
    let after = next + 5;
    if (uni >= 0xd800 && uni <= 0xdbff && s.slice(after, after + 2) === '\\u') {
      const uni2 = decodeUXXXX(s, after + 1);
      if (uni2 >= 0xdc00 && uni2 <= 0xdfff) {
        uni = 0x10000 + (((uni - 0xd800) << 10) | (uni2 - 0xdc00));
        after += 6;
      }
    }
    // A lone surrogate is a legal Python `str` character and a legal JS one; `chr(uni)` and
    // `String.fromCodePoint` agree on every value the branch above can produce.
    out += String.fromCodePoint(uni);
    end = after;
  }
}

/**
 * `\uXXXX`, reported at the position of the `u`.
 *
 * The C scanner needs FIVE characters after the `u`, not four: `"\u0041` is
 * `Invalid \uXXXX escape` while `"\u0041 ` gets past the escape and fails as an
 * unterminated string. Measured on both sides of the boundary — the pure-Python
 * `_decode_uXXXX` needs only four, so a port written from `json/decoder.py` is wrong here.
 */
function decodeUXXXX(s: string, uAt: number): number {
  if (uAt + 5 >= s.length) throw new PyJSONDecodeError('Invalid \\uXXXX escape', s, uAt);
  const esc = s.slice(uAt + 1, uAt + 5);
  if (esc[1] !== 'x' && esc[1] !== 'X' && /^[0-9a-fA-F]{4}$/.test(esc)) {
    return Number.parseInt(esc, 16);
  }
  throw new PyJSONDecodeError('Invalid \\uXXXX escape', s, uAt);
}

const NUMBER_RE = /(-?(?:0|[1-9]\d*))(\.\d+)?([eE][-+]?\d+)?/y;

/** A `StopIteration(idx)` out of `scan_once`, which `raw_decode` turns into a message. */
class StopScan {
  constructor(readonly at: number) {}
}

function scanOnce(s: string, idx: number): [PyValue, number] {
  if (idx >= s.length) throw new StopScan(idx);
  const nextchar = s[idx]!;
  if (nextchar === '"') {
    const [value, end] = scanString(s, idx + 1);
    return [{ t: 'str', v: value }, end];
  }
  if (nextchar === '{') return scanObject(s, idx + 1);
  if (nextchar === '[') return scanArray(s, idx + 1);
  if (nextchar === 'n' && s.slice(idx, idx + 4) === 'null') return [PY_NONE, idx + 4];
  if (nextchar === 't' && s.slice(idx, idx + 4) === 'true') return [{ t: 'bool', v: true }, idx + 4];
  if (nextchar === 'f' && s.slice(idx, idx + 5) === 'false') return [{ t: 'bool', v: false }, idx + 5];

  NUMBER_RE.lastIndex = idx;
  const m = NUMBER_RE.exec(s);
  if (m) {
    const integer = m[1]!;
    const frac = m[2];
    const exp = m[3];
    if (frac || exp) {
      return [{ t: 'float', v: Number(`${integer}${frac ?? ''}${exp ?? ''}`) }, NUMBER_RE.lastIndex];
    }
    return [{ t: 'int', v: BigInt(integer) }, NUMBER_RE.lastIndex];
  }
  if (nextchar === 'N' && s.slice(idx, idx + 3) === 'NaN') return [{ t: 'float', v: NaN }, idx + 3];
  if (nextchar === 'I' && s.slice(idx, idx + 8) === 'Infinity') {
    return [{ t: 'float', v: Infinity }, idx + 8];
  }
  if (nextchar === '-' && s.slice(idx, idx + 9) === '-Infinity') {
    return [{ t: 'float', v: -Infinity }, idx + 9];
  }
  throw new StopScan(idx);
}

/** `scan_once` with `StopIteration` already turned into the decoder's own message. */
function scanValue(s: string, idx: number): [PyValue, number] {
  try {
    return scanOnce(s, idx);
  } catch (e) {
    if (e instanceof StopScan) throw new PyJSONDecodeError('Expecting value', s, e.at);
    throw e;
  }
}

/** `JSONObject`, entered just past the `{`. */
function scanObject(s: string, start: number): [PyValue, number] {
  const pairs = new Map<string, PyValue>();
  let end = start;
  let nextchar = s.slice(end, end + 1);
  if (nextchar !== '"') {
    if (isWs(nextchar)) {
      end = skipWs(s, end);
      nextchar = s.slice(end, end + 1);
    }
    if (nextchar === '}') return [{ t: 'dict', v: pairs }, end + 1];
    if (nextchar !== '"') {
      throw new PyJSONDecodeError('Expecting property name enclosed in double quotes', s, end);
    }
  }
  end += 1;
  for (;;) {
    const [key, afterKey] = scanString(s, end);
    end = afterKey;
    if (s.slice(end, end + 1) !== ':') {
      end = skipWs(s, end);
      if (s.slice(end, end + 1) !== ':') {
        throw new PyJSONDecodeError("Expecting ':' delimiter", s, end);
      }
    }
    end += 1;
    end = skipWs(s, end);
    const [value, afterValue] = scanValue(s, end);
    end = afterValue;
    // `dict(pairs)`: a repeated key keeps its FIRST position and its LAST value, which is
    // what `Map.set` does too.
    pairs.set(key, value);
    let sep = end < s.length ? s[end]! : '';
    if (isWs(sep)) {
      end = skipWs(s, end + 1);
      sep = end < s.length ? s[end]! : '';
    }
    end += 1;
    if (sep === '}') break;
    if (sep !== ',') throw new PyJSONDecodeError("Expecting ',' delimiter", s, end - 1);
    end = skipWs(s, end);
    const quote = s.slice(end, end + 1);
    end += 1;
    if (quote !== '"') {
      throw new PyJSONDecodeError('Expecting property name enclosed in double quotes', s, end - 1);
    }
  }
  return [{ t: 'dict', v: pairs }, end];
}

/** `JSONArray`, entered just past the `[`. */
function scanArray(s: string, start: number): [PyValue, number] {
  const values: PyValue[] = [];
  let end = start;
  let nextchar = s.slice(end, end + 1);
  if (isWs(nextchar)) {
    end = skipWs(s, end + 1);
    nextchar = s.slice(end, end + 1);
  }
  if (nextchar === ']') return [{ t: 'list', v: values }, end + 1];
  for (;;) {
    const [value, afterValue] = scanValue(s, end);
    end = afterValue;
    values.push(value);
    let sep = s.slice(end, end + 1);
    if (isWs(sep)) {
      end = skipWs(s, end + 1);
      sep = s.slice(end, end + 1);
    }
    end += 1;
    if (sep === ']') break;
    if (sep !== ',') throw new PyJSONDecodeError("Expecting ',' delimiter", s, end - 1);
    end = skipWs(s, end);
  }
  return [{ t: 'list', v: values }, end];
}

/**
 * `JSONDecoder().raw_decode(s, idx)` — decode ONE value and return it with the offset just
 * past it. Trailing text is not an error here; that is the whole reason `extract_json` uses
 * this and not `json.loads`. Note there is no leading-whitespace skip: `raw_decode` has
 * none either, and `extract_json` always enters on a `{` or a `[`.
 */
export function rawDecode(s: string, idx = 0): [PyValue, number] {
  try {
    const [value, end] = scanOnce(s, idx);
    // Python's `end` counts CODEPOINTS. Converting here rather than threading a codepoint
    // index through the scanner keeps the hot path on UTF-16 slices, which is what the
    // regexes want, and pays one linear pass only on success.
    return [value, [...s.slice(0, end)].length];
  } catch (e) {
    if (e instanceof StopScan) throw new PyJSONDecodeError('Expecting value', s, e.at);
    throw e;
  }
}

/** `json.loads`, for the places that want the whole document and nothing after it. */
export function parseJson(s: string): PyValue {
  const start = skipWs(s, 0);
  const [value, end] = scanValueTop(s, start);
  const rest = skipWs(s, end);
  if (rest !== s.length) throw new PyJSONDecodeError('Extra data', s, rest);
  return value;
}

/** `raw_decode` without the codepoint conversion, for callers that slice with the offset. */
function scanValueTop(s: string, idx: number): [PyValue, number] {
  return scanValue(s, idx);
}
