/**
 * The SDK's serializer — which is NOT `json.dumps`, and that is the whole reason this file
 * exists next to `pyjson.ts`.
 *
 * Two different writers reach the wire from the Python server and only one of them is
 * CPython's:
 *
 *   * every FILE bantamkit writes (`checkpoint.json`, `.log.jsonl`) goes through
 *     `json.dumps` — `ensure_ascii=True`, `", "`/`": "` separators, codepoint `sort_keys`.
 *     That is `pyjson.dumpJson`, N6's, and nothing here replaces it.
 *   * every JSON-RPC FRAME, and the `content[0].text` inside a tool result, goes through
 *     `pydantic_core.to_json` — Rust `serde_json`, which escapes nothing outside the JSON
 *     minimum, emits raw UTF-8, and formats floats with ryu.
 *
 * Measured, `mcp` 2.0.0 / pydantic-core 2.x (`scratchpad/job38-n7/tj.py`):
 *
 *     to_json({'x': 'em — dash'})            -> {"x":"em — dash"}      (NOT —)
 *     to_json({'k': '\x7f\x01'})             -> {"k":"?"}  -> DEL RAW,  escaped
 *     to_json(1e-6)  -> 1e-6     while repr(1e-6)  is '1e-06'
 *     to_json(1e-5)  -> 0.00001  while repr(1e-5)  is '1e-05'
 *     to_json(1.0)   -> 1.0      while String(1.0) is '1'
 *
 * The first two are what `JSON.stringify` already does, so strings ride on it. The last two
 * are not, and are why numbers are formatted by hand: a `5.0` that arrived on the wire and
 * left as `5` is exactly the defect N6 measured on the file side, relocated to the frame.
 */
import type { PyValue } from '../pyjson.js';

/**
 * ryu's presentation rule, as `serde_json` uses it, derived by sweeping 99 values against
 * the running `pydantic_core` (`scratchpad/job38-n7/tf2.py`).
 *
 * It agrees with CPython's `repr` everywhere except the exponent, in two ways:
 *   1. the exponent is NOT zero-padded — `1e-6`, not `1e-06`;
 *   2. the decimal/scientific boundary on the small side is one decade lower — `1e-5`
 *      prints as `0.00001` where `repr` gives `1e-05`.
 * The large side agrees: both switch to scientific at 1e16.
 *
 * `-0.0` keeps its sign in both. NaN and the infinities cannot occur: they are not JSON,
 * every value here arrived by parsing a JSON document, and `pyjson.parseJson` rejects
 * Python's `NaN`/`Infinity` extension the way a strict reader must.
 */
export function serdeFloat(x: number): string {
  if (!Number.isFinite(x)) {
    // `to_json` writes `null` for a non-finite float; unreachable from parsed JSON, kept so
    // the function is total rather than silently emitting invalid JSON.
    return 'null';
  }
  const sign = Object.is(x, -0) || x < 0 ? '-' : '';
  const abs = Math.abs(x);
  if (abs === 0) return `${sign}0.0`;
  // `toExponential()` with no argument gives the SHORTEST round-tripping digits, which is
  // the same digit string ryu produces; only the presentation is ours.
  const [mantissa, exponentText] = abs.toExponential().split('e') as [string, string];
  const exponent = Number(exponentText);
  const digits = mantissa.replace('.', '');
  if (exponent >= -5 && exponent < 16) {
    if (exponent >= 0) {
      const whole = digits.padEnd(exponent + 1, '0').slice(0, exponent + 1);
      const fraction = digits.slice(exponent + 1);
      return `${sign}${whole}.${fraction === '' ? '0' : fraction}`;
    }
    return `${sign}0.${'0'.repeat(-exponent - 1)}${digits}`;
  }
  const head = digits.length === 1 ? digits : `${digits[0]}.${digits.slice(1)}`;
  return `${sign}${head}e${exponent < 0 ? '-' : '+'}${Math.abs(exponent)}`;
}

/**
 * `pydantic_core.to_json(value, indent=<indent>)`.
 *
 * `indent = null` is the compact form the JSON-RPC frame uses — `,` and `:` with NO spaces,
 * which is serde's default and NOT `json.dumps`' default. `indent = 2` is the form
 * `_convert_to_content` uses for the text block of every dict-returning tool.
 *
 * Strings go through `JSON.stringify`, which was checked against serde over the escape
 * boundary: both emit the short escapes for `\b \t \n \f \r " \\`, `\u00XX` for the other
 * C0 controls, and raw bytes for everything else including DEL and `/`. They part company
 * only on a LONE SURROGATE, which JS escapes and pydantic-core refuses to encode at all —
 * unreachable here, because a lone surrogate cannot survive UTF-8 decoding of the wire.
 */
export function sdkJson(value: PyValue, indent: number | null = null): string {
  const pad = indent === null ? '' : ' '.repeat(indent);
  const itemSep = indent === null ? ',' : ',';
  const keySep = indent === null ? ':' : ': ';

  const encode = (v: PyValue, level: number): string => {
    switch (v.t) {
      case 'null':
        return 'null';
      case 'bool':
        return v.v ? 'true' : 'false';
      case 'int':
        return v.v.toString();
      case 'float':
        return serdeFloat(v.v);
      case 'str':
        return JSON.stringify(v.v);
      case 'list': {
        if (v.v.length === 0) return '[]';
        const parts = v.v.map((item) => encode(item, level + 1));
        if (indent === null) return `[${parts.join(itemSep)}]`;
        const nl = `\n${pad.repeat(level + 1)}`;
        return `[${nl}${parts.join(itemSep + nl)}\n${pad.repeat(level)}]`;
      }
      case 'dict': {
        if (v.v.size === 0) return '{}';
        const parts = [...v.v].map(([k, item]) => `${JSON.stringify(k)}${keySep}${encode(item, level + 1)}`);
        if (indent === null) return `{${parts.join(itemSep)}}`;
        const nl = `\n${pad.repeat(level + 1)}`;
        return `{${nl}${parts.join(itemSep + nl)}\n${pad.repeat(level)}}`;
      }
    }
  };
  return encode(value, 0);
}
