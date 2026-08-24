/**
 * Layer 2 — the model contract: every string the model reads, every parse of what it writes.
 *
 * A port of the 44 lines of `runtime-py/src/bantamkit/contract.py` that the MCP surface
 * reaches (measured by `sys.settrace` over a real stdio server; the `document_*` renderers
 * are 461 lines of the same file and NONE of them is reachable from the eight tools, so they
 * are not here). The layer rule (`docs/architecture.md`) puts the WORDING in
 * `assets/contracts/default.yaml` and the PARSE in this file, and neither half is duplicated
 * here: the sentences are read from the asset at call time, exactly as Python reads them.
 *
 * THE PROPERTY THIS FILE EXISTS FOR: for every validation failure bantamkit can produce,
 * Node emits the byte-identical string Python emits. Two of these are pinned in the Python
 * suite — `test_layers.py:592` and `test_structured.py:82` — and every one of them reaches
 * either the model's retry turn or a shift-work checkpoint's refusal reason.
 *
 * The two library seams live next door and not in here, the way `memory/pyyaml.ts` and
 * `memory/pyfs.ts` sit next to `memory/store.ts`: `pyjson.ts` is CPython's `json` decoder
 * plus `repr()`, `pyjsonschema.ts` is `jsonschema`'s Draft 2020-12 validator plus
 * `best_match`. Neither is a bantamkit layer; both are third-party behaviour this runtime
 * has to reproduce because its output is quoted verbatim into Layer 2's sentences.
 */
import { existsSync } from 'node:fs';
import { join } from 'node:path';

import { assetsRoot, AssetNotFound } from './assets.js';
import { BantamError } from './errors.js';
import { pyStrip } from './memory/factfile.js';
import { pyReadText } from './memory/pyfs.js';
import { resolveImplicitTag } from './memory/pyyaml.js';
import { fromJs, PyValueError, rawDecode, type PyValue } from './pyjson.js';
import { absolutePath, validate } from './pyjsonschema.js';

/** `contract.REQUIRED_KEYS`, in Python's order — the order the error message lists them. */
export const REQUIRED_KEYS = [
  'schema_instruction',
  'schema_retry',
  'critique_feedback',
  'parse_error',
  'validation_error',
  'json_answer_retry',
  'loop_note',
  'loop_warn',
  'evidence_line',
  'evidence_no_observation',
  'evidence_empty',
  'document_manifest_empty',
  'document_manifest_part',
  'document_manifest_header_row',
  'document_manifest_first_row',
  'document_manifest_last_row',
  'document_manifest_package_media',
  'document_manifest_omitted_media',
  'document_manifest_omitted_blank',
  'document_manifest_omitted_format',
  'document_manifest_omitted_unread_page',
  'document_manifest_unread_no_operator',
  'document_manifest_unread_unmapped',
  'document_manifest_unread_whitespace',
  'document_manifest_unread_no_character',
  'document_manifest_omitted_unmapped',
  'document_manifest_omitted_other',
  'document_page_header',
  'document_page_next',
  'document_page_end',
  'document_page_truncated',
  'document_unknown',
  'document_offset_past_end',
  'document_error',
  'document_paste_preamble',
  'document_paste_part',
  'document_paste_complete',
  'document_paste_truncated',
  'document_paste_none',
  'tool_failed',
  'tool_arguments',
  'tool_arguments_none',
  'tool_argument_types',
  'tool_argument_type',
] as const;

export class ContractParseError extends BantamError {}

// ------------------------------------------------------------------- reading the asset

/**
 * `yaml.safe_load` reduced to the document `assets/contracts/default.yaml` actually is.
 *
 * HOW default.yaml IS READ, AND WHY THAT IS SAFE WITH NO YAML ENGINE IN THE PACKAGE.
 * N4's `parseConfigDocument` reads a DIFFERENT document — a hand-written `config.yaml` whose
 * values are paths and lists — and this one has different needs, so it gets its own reader
 * rather than a widened one. Measured shape of the shipped file (86 lines, 9,194 bytes):
 * 40 whole-line comments, 1 blank line, 1 `key: <plain scalar>` (`name: default`), and 44
 * `key: "<double-quoted scalar>"` on ONE line each. No block scalars, no wraps, no nesting,
 * no sequences, no anchors, no tags, no multi-document stream. Every value is a string; the
 * only escapes present are `\n` (3) and `\"` (16).
 *
 * So this reads exactly that: comments, blanks, an optional leading `---`, and root-level
 * entries whose value is either a double-quoted scalar closing on its own line or a plain
 * scalar. The double-quoted escape table is YAML 1.1's in full, so a contract that gains a
 * `\t` or a `é` tomorrow is already read; the plain scalar goes through
 * `resolveImplicitTag`, the SAME resolver the fact-file emitter uses, so the two halves of
 * this package cannot disagree about what `null` or `2026-08-23` means.
 *
 * SAFE, in the sense the word carries for YAML, is structural: no tag handling, no anchor or
 * alias expansion, no merge key, no constructor dispatch. `yaml.safe_load` earns the name by
 * refusing `!!python/object`; this refuses every `!`, `&` and `*` by not implementing them.
 * One left-to-right pass, no backtracking, so a hostile file costs time linear in its length.
 *
 * ANYTHING OUTSIDE THAT LANGUAGE RAISES. The failure mode of guessing is a contract key
 * whose value is subtly wrong, which reaches the model as a malformed sentence nobody
 * notices; the failure mode of raising is `AssetNotFound`-shaped and loud. The gate for this
 * claim is not the reader's own opinion: `tools/conformance/suites/validate.mjs` compares
 * this parse of the SHIPPED asset against `yaml.safe_load`'s, key for key and byte for byte,
 * and `test/contract.test.mjs` refuses the constructs above by name.
 */
export function parseContractDocument(text: string): Map<string, string> {
  const lines = text.split('\n');
  if (lines[lines.length - 1] === '') lines.pop();
  const entries = new Map<string, string>();
  let i = 0;
  const blank = (line: string): boolean => pyStrip(line) === '' || /^\s*#/.test(line);
  while (i < lines.length && blank(lines[i]!)) i += 1;
  if (i < lines.length && lines[i]!.trimEnd() === '---') i += 1;

  for (; i < lines.length; i += 1) {
    const line = lines[i]!;
    if (blank(line)) continue;
    if (/^\s*(?:[!&*]|<<|---|\.\.\.)/.test(line)) {
      throw new ContractParseError(
        `line ${i + 1} uses a tag, an anchor, an alias or a second document, which is ` +
          'outside this reader',
      );
    }
    const head = /^([^\s#:'"[\]{}&*!][^:]*):(?:[ \t]+|$)/.exec(line);
    if (head === null || line.startsWith(' ') || line.startsWith('\t')) {
      throw new ContractParseError(
        `line ${i + 1} is not a root "key: value" entry, which is outside this reader`,
      );
    }
    const key = pyStrip(head[1]!);
    const rest = line.slice(head[0].length);
    entries.set(key, readScalar(rest, i + 1));
  }
  return entries;
}

/** One value, on one line: a double-quoted scalar or a plain one. */
function readScalar(rest: string, lineNumber: number): string {
  const body = rest.trimEnd();
  if (body === '' || body.startsWith('|') || body.startsWith('>')) {
    throw new ContractParseError(
      `line ${lineNumber} opens a block scalar or an empty value, which is outside this reader`,
    );
  }
  if (/^['[{!&*]|^\?\s|^:\s/.test(body)) {
    throw new ContractParseError(
      `line ${lineNumber} opens the value with a single quote, a flow collection, a tag, an ` +
        'anchor or an alias, which is outside this reader',
    );
  }
  if (!body.startsWith('"')) {
    // A plain scalar ends at ` #`. `resolveImplicitTag` decides whether it is a string.
    const cut = body.indexOf(' #');
    const plain = pyStrip(cut === -1 ? body : body.slice(0, cut));
    const tag = resolveImplicitTag(plain);
    if (tag !== 'tag:yaml.org,2002:str') {
      throw new ContractParseError(
        `line ${lineNumber} is a plain scalar resolving to ${tag}, and every contract value ` +
          'is a string; that is outside this reader',
      );
    }
    return plain;
  }
  const [value, end] = readDoubleQuoted(body, lineNumber);
  const tail = pyStrip(body.slice(end));
  if (tail !== '' && !tail.startsWith('#')) {
    throw new ContractParseError(
      `line ${lineNumber} has content after the closing quote, which is outside this reader`,
    );
  }
  return value;
}

/** YAML 1.1's double-quoted escape table, which is a superset of JSON's. */
const YAML_ESCAPES: Record<string, string> = {
  '0': '\0',
  a: '\x07',
  b: '\b',
  t: '\t',
  '\t': '\t',
  n: '\n',
  v: '\v',
  f: '\f',
  r: '\r',
  e: '\x1b',
  ' ': ' ',
  '"': '"',
  '/': '/',
  '\\': '\\',
  N: '\x85',
  _: '\xa0',
  L: ' ',
  P: ' ',
};
const YAML_HEX: Record<string, number> = { x: 2, u: 4, U: 8 };

function readDoubleQuoted(body: string, lineNumber: number): [string, number] {
  let out = '';
  let i = 1;
  while (i < body.length) {
    const ch = body[i]!;
    if (ch === '"') return [out, i + 1];
    if (ch !== '\\') {
      out += ch;
      i += 1;
      continue;
    }
    const esc = body[i + 1];
    if (esc === undefined) break; // a line-continuation fold: multi-line, outside this reader
    const width = YAML_HEX[esc];
    if (width !== undefined) {
      const digits = body.slice(i + 2, i + 2 + width);
      if (digits.length !== width || !/^[0-9a-fA-F]+$/.test(digits)) {
        throw new ContractParseError(
          `line ${lineNumber} has a malformed \\${esc} escape, which is outside this reader`,
        );
      }
      out += String.fromCodePoint(Number.parseInt(digits, 16));
      i += 2 + width;
      continue;
    }
    const mapped = YAML_ESCAPES[esc];
    if (mapped === undefined) {
      throw new ContractParseError(
        `line ${lineNumber} has an unknown escape \\${esc}, which is outside this reader`,
      );
    }
    out += mapped;
    i += 2;
  }
  throw new ContractParseError(
    `line ${lineNumber} has a double-quoted scalar that does not close on its own line, ` +
      'which is outside this reader',
  );
}

/**
 * `load_contract`. Reads the asset EVERY call, as Python does — the prep probe measured that
 * `contracts/default.yaml` is touched only on a validation failure, so a cache would buy
 * nothing and would make a hot-edited contract silently stale.
 */
export function loadContract(name = 'default'): Record<string, string> {
  const path = join(assetsRoot(), 'contracts', `${name}.yaml`);
  if (!existsSync(path)) throw new AssetNotFound(`contract asset not found: ${path}`);
  const data = parseContractDocument(pyReadText(path));
  const missing = REQUIRED_KEYS.filter((k) => !data.has(k));
  if (missing.length > 0) {
    throw new BantamError(`contract '${name}' missing key(s): ${missing.join(', ')}`);
  }
  return Object.fromEntries(data);
}

// --------------------------------------------------------------------------- the strings

/**
 * `str.format(**fields)`, and it is here rather than as a `String.replace` for one measured
 * reason: JS gives `$` a meaning in the REPLACEMENT string. `'{detail}'.replace('{detail}',
 * "'A1' does not match '^[a-z]+$'")` drops the `$'` and emits
 * `'A1' does not match '^[a-z]+`, because `$'` means "everything after the match". Every
 * `pattern` sentence and every regex a model writes back would arrive truncated. Caught by
 * the differential, not by review.
 *
 * `{{` and `}}` are Python's literal braces; a field the caller did not supply is a
 * `KeyError` there and a thrown `BantamError` here, rather than a brace left in the text.
 */
function pyFormat(template: string, fields: Record<string, string>): string {
  let out = '';
  for (let i = 0; i < template.length; i += 1) {
    const ch = template[i]!;
    if (ch === '{' && template[i + 1] === '{') {
      out += '{';
      i += 1;
    } else if (ch === '}' && template[i + 1] === '}') {
      out += '}';
      i += 1;
    } else if (ch === '{') {
      const close = template.indexOf('}', i + 1);
      if (close === -1) throw new BantamError(`unmatched '{' in contract template`);
      const key = template.slice(i + 1, close);
      const value = fields[key];
      if (value === undefined) throw new BantamError(`contract template wants field '${key}'`);
      out += value;
      i = close;
    } else {
      out += ch;
    }
  }
  return out;
}

export function schemaRetryFeedback(error: string): string {
  return pyFormat(loadContract()['schema_retry']!, { error });
}

export function parseErrorMessage(detail: unknown): string {
  const text = detail instanceof Error ? detail.message : String(detail);
  return pyFormat(loadContract()['parse_error']!, { detail: text });
}

export function validationErrorMessage(where: string, detail: string): string {
  return pyFormat(loadContract()['validation_error']!, { where, detail });
}

// ------------------------------------------------------------------------- extract_json

/**
 * `extract_json`: a fenced block if there is one, otherwise the first `{`/`[` onward.
 *
 * Both arms are here because both reach the model. The fence is `re.search` with `DOTALL`
 * and a non-greedy body, so it takes the FIRST fence and prose on either side is discarded;
 * with no fence, `find` takes the earliest brace or bracket — including one inside a string
 * of prose, which is faithful and occasionally wrong in exactly Python's way. `raw_decode`
 * then stops at the end of that one value, which is why `{"a": 1} — anything else?` parses.
 */
export function extractJson(text: string): PyValue {
  let body = pyStrip(text);
  // `re.DOTALL` — JS needs `[\s\S]`, and `\s*` after the opening fence is Python's `\s*`.
  const fence = /```(?:json)?[\s\S]*?```/.exec(body);
  if (fence !== null) {
    const inner = /```(?:json)?\s*([\s\S]*?)```/.exec(body);
    body = pyStrip(inner![1]!);
  }
  const startBrace = body.indexOf('{');
  const startBracket = body.indexOf('[');
  let start: number;
  if (startBrace === -1 && startBracket === -1) {
    throw new PyValueError('no JSON object found in output');
  } else if (startBrace === -1) {
    start = startBracket;
  } else if (startBracket === -1) {
    start = startBrace;
  } else {
    start = Math.min(startBrace, startBracket);
  }
  return rawDecode(body.slice(start))[0];
}

// -------------------------------------------------------------------------- schema_error

/**
 * `schema_error`: a pointed validation error for `output`, or `null` if it satisfies
 * `schema`.
 *
 * `where` is `"/".join(e.absolute_path)` with `"root"` standing in for the empty path, and
 * `detail` is `ValidationError.message` VERBATIM. The error is the one `best_match` chose,
 * not the first one found — see `pyjsonschema.bestMatch`.
 *
 * The schema may be a `PyValue` (exact — use `pyjson.parseJson` when the raw text is still
 * in hand) or a plain JS value, which is lifted with `pyjson.fromJs` and its one documented
 * loss.
 */
export function schemaError(output: string, schema: PyValue | unknown): string | null {
  let data: PyValue;
  try {
    data = extractJson(output);
  } catch (e) {
    // `except ValueError` — and `json.JSONDecodeError` IS a `ValueError`, which is how
    // CPython's decoder text reaches the model.
    if (e instanceof Error && (e.name === 'PyValueError' || e.name === 'PyJSONDecodeError')) {
      return parseErrorMessage(e);
    }
    throw e;
  }
  const asPy = isPyValue(schema) ? schema : fromJs(schema);
  const error = validate(data, asPy);
  if (error === null) return null;
  const where = absolutePath(error).map(String).join('/') || 'root';
  return validationErrorMessage(where, error.message);
}

function isPyValue(value: unknown): value is PyValue {
  return (
    typeof value === 'object' &&
    value !== null &&
    't' in value &&
    typeof (value as { t: unknown }).t === 'string' &&
    ['null', 'bool', 'int', 'float', 'str', 'list', 'dict'].includes((value as { t: string }).t)
  );
}
