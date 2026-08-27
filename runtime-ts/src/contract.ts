/**
 * Layer 2 — the model contract: every string the model reads, every parse of what it writes.
 *
 * A port of the lines of `runtime-py/src/bantamkit/contract.py` that the MCP surface
 * reaches. Measured by `sys.settrace` over a real stdio server, that was 44 lines while the
 * surface was nine tools (served-tools: dated) and none of the `document_*` renderers —
 * before `bantamkit_read` (job43)
 * put the reader on the wire, so `document_manifest`, `document_page`, `document_error`,
 * `document_offset_past_end` and the two sentences that are that tool's own are here now,
 * mirrored from `contract.py` line for line — including `_omission_line`'s subject switch
 * and its printed fallback. The layer rule (`docs/architecture.md`) puts the WORDING in
 * `assets/contracts/default.yaml` and the PARSE in this file, and neither half is duplicated
 * here: the sentences are read from the asset at call time, exactly as Python reads them.
 *
 * THE RENDERERS TAKE PRIMITIVES, as the reference's do: `contract.py` may not import
 * `docread` (`test_layers.py::test_import_direction`) and this file does not import
 * `docread.ts`. A rendered row is already a string by the time a reader has one, and an
 * omission arrives as `Omission.asDict()`'s plain object.
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

/**
 * `contract.REQUIRED_KEYS`, in Python's order — the order the error message lists them.
 *
 * `bantamkit_read_page_next` and `bantamkit_read_unknown_part` are deliberately NOT here:
 * the reference's tuple does not carry them (R1 added the sentences to the asset and not to
 * the tuple), and `missing key(s): ...` lists this tuple verbatim, so a Node list that was
 * two keys longer would refuse a thin contract with a sentence Python does not print. The
 * two renderers below fetch their key at call time and raise by name if it is absent, which
 * is the `KeyError` the reference would raise at the same moment.
 */
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

// ---------------------------------------------------- the document reader's sentences

/**
 * The primitive shape of one omission, as `docread.Omission.asDict()` hands it over. The
 * reference reads `dict` keys with `[]` and `.get`; the optional ones are optional here too.
 */
export interface OmissionRecord {
  readonly subject: string;
  readonly count: number;
  readonly size?: number;
  readonly where?: readonly string[];
  readonly what?: string;
  readonly facts?: Readonly<Record<string, number>>;
}

/** One part of a manifest, as `evalrun._document_tools` and `bantamkit_read` build it. */
export interface ManifestPart {
  readonly document: string;
  readonly kind: string;
  readonly index: number;
  readonly part: string;
  readonly row_count: number;
  readonly rows: readonly string[];
  readonly omissions?: readonly OmissionRecord[];
}

/** A document's own omissions, which the manifest prints before that document's parts. */
export interface ManifestDocument {
  readonly document: string;
  readonly omissions?: readonly OmissionRecord[];
}

/** `str(int)` for a template field — every number in these sentences is an `int`. */
const num = (n: number): string => String(n);

/** A contract key the reference reads with `contract[key]`: a `KeyError` there, a raise here. */
function sentence(contract: Record<string, string>, key: string): string {
  const template = contract[key];
  if (template === undefined) throw new BantamError(`contract missing key: ${key}`);
  return template;
}

/**
 * `_omission_line`: one omission, as one line. An unknown subject is PRINTED, never dropped.
 *
 * The branch order is `contract.py`'s, and the `unread-page` arm chooses between the four
 * reasons in the order `docread._pdf_refusal` chooses, so the page-grain sentence and the
 * document-grain refusal cannot disagree about a file.
 */
function omissionLine(
  contract: Record<string, string>,
  entry: { readonly row_count: number },
  omission: OmissionRecord,
): string {
  const subject = omission.subject;
  if (subject === 'media') {
    return pyFormat(sentence(contract, 'document_manifest_omitted_media'), {
      count: num(omission.count),
      bytes: num(omission.size ?? 0),
    });
  }
  if (subject === 'blank-rows') {
    return pyFormat(sentence(contract, 'document_manifest_omitted_blank'), {
      count: num(omission.count),
      rows: num(entry.row_count),
    });
  }
  if (subject === 'number-format') {
    return pyFormat(sentence(contract, 'document_manifest_omitted_format'), {
      where: (omission.where ?? []).join(', '),
      count: num(omission.count),
      what: omission.what ?? '',
    });
  }
  if (subject === 'unread-page') {
    const facts = omission.facts ?? {};
    const showOps = Math.trunc(facts['show_ops'] ?? 0);
    const vouched = Math.trunc(facts['vouched'] ?? 0);
    const unmapped = Math.trunc(facts['unmapped'] ?? 0);
    let why: string;
    if (showOps === 0) {
      why = sentence(contract, 'document_manifest_unread_no_operator');
    } else if (vouched === 0 && unmapped) {
      why = pyFormat(sentence(contract, 'document_manifest_unread_unmapped'), {
        show_ops: num(showOps),
        unmapped: num(unmapped),
      });
    } else if (vouched) {
      why = pyFormat(sentence(contract, 'document_manifest_unread_whitespace'), {
        show_ops: num(showOps),
        vouched: num(vouched),
      });
    } else {
      why = pyFormat(sentence(contract, 'document_manifest_unread_no_character'), {
        show_ops: num(showOps),
      });
    }
    return pyFormat(sentence(contract, 'document_manifest_omitted_unread_page'), {
      why,
      count: num(Math.trunc(facts['images'] ?? 0)),
      bytes: num(Math.trunc(facts['image_bytes'] ?? 0)),
    });
  }
  if (subject === 'unmapped-text') {
    return pyFormat(sentence(contract, 'document_manifest_omitted_unmapped'), {
      count: num(omission.count),
      what: omission.what ?? '',
    });
  }
  return pyFormat(sentence(contract, 'document_manifest_omitted_other'), {
    count: num(omission.count),
    subject,
    what: omission.what ?? '',
  });
}

function packageMediaLine(
  contract: Record<string, string>,
  document: string,
  omission: OmissionRecord,
): string {
  return pyFormat(sentence(contract, 'document_manifest_package_media'), {
    document,
    count: num(omission.count),
    what: omission.what ?? '',
    bytes: num(omission.size ?? 0),
  });
}

/**
 * `document_manifest`: the answer to "what exists", as one observation — per part, the row
 * count, the numbering, the header, the first and the last data row, and every omission the
 * rendering made. A document's own omissions print before its first part; one whose
 * omissions matched no part is still said, after every part, because `pop` makes that
 * reachable on the reference and dropping the line would put the silence back one level up.
 */
export function documentManifest(
  parts: readonly ManifestPart[],
  documents: readonly ManifestDocument[] | null = null,
): string {
  const contract = loadContract();
  if (parts.length === 0) return sentence(contract, 'document_manifest_empty');
  // `{entry["document"]: entry.get("omissions") or []}` — a later duplicate wins, as in a dict.
  const pkg = new Map<string, readonly OmissionRecord[]>();
  for (const entry of documents ?? []) pkg.set(entry.document, entry.omissions ?? []);
  const lines: string[] = [];
  for (const entry of parts) {
    const rows = entry.rows;
    const last = entry.row_count - 1;
    const pending = pkg.get(entry.document) ?? [];
    pkg.delete(entry.document);
    for (const omission of pending) {
      lines.push(
        omission.subject === 'media'
          ? packageMediaLine(contract, entry.document, omission)
          : omissionLine(contract, entry, omission),
      );
    }
    lines.push(
      pyFormat(sentence(contract, 'document_manifest_part'), {
        document: entry.document,
        kind: entry.kind,
        index: num(entry.index),
        part: entry.part,
        rows: num(entry.row_count),
        last: num(last),
      }),
    );
    if (rows.length > 0) {
      lines.push(pyFormat(sentence(contract, 'document_manifest_header_row'), { row: rows[0]! }));
    }
    if (rows.length > 1) {
      lines.push(pyFormat(sentence(contract, 'document_manifest_first_row'), { row: rows[1]! }));
    }
    if (rows.length > 2) {
      lines.push(
        pyFormat(sentence(contract, 'document_manifest_last_row'), {
          index: num(last),
          row: rows[rows.length - 1]!,
        }),
      );
    }
    for (const omission of entry.omissions ?? []) lines.push(omissionLine(contract, entry, omission));
  }
  for (const [document, omissions] of pkg) {
    for (const omission of omissions) {
      lines.push(
        omission.subject === 'media'
          ? packageMediaLine(contract, document, omission)
          : omissionLine(contract, { row_count: 0 }, omission),
      );
    }
  }
  return lines.join('\n');
}

/**
 * `document_page`: one page, with its own coordinates and its continuation, both in band.
 *
 * `nextKey` names the contract sentence for the continuation, because that sentence names
 * the TOOL to call again: `document_read` for the eval pair, `bantamkit_read` for the MCP
 * reader. Every other line of a page is the same bytes on both.
 */
export function documentPage(
  document: string,
  part: string,
  offset: number,
  rows: readonly string[],
  rowCount: number,
  nextOffset: number | null,
  truncatedBytes = 0,
  nextKey = 'document_page_next',
): string {
  const contract = loadContract();
  const end = rows.length > 0 ? offset + rows.length - 1 : offset;
  const lines = [
    pyFormat(sentence(contract, 'document_page_header'), {
      document,
      part,
      start: num(offset),
      end: num(end),
      rows: num(rowCount),
    }),
  ];
  rows.forEach((row, i) => lines.push(`${offset + i}\t${row}`));
  if (truncatedBytes) {
    lines.push(
      pyFormat(sentence(contract, 'document_page_truncated'), {
        index: num(end),
        dropped: num(truncatedBytes),
      }),
    );
  }
  if (nextOffset === null) {
    lines.push(pyFormat(sentence(contract, 'document_page_end'), { part }));
  } else {
    lines.push(pyFormat(sentence(contract, nextKey), { next_offset: num(nextOffset) }));
  }
  return lines.join('\n');
}

export function documentUnknown(name: string, available: readonly string[]): string {
  return pyFormat(sentence(loadContract(), 'document_unknown'), { name, available: available.join(', ') });
}

export function documentOffsetPastEnd(part: string, offset: number, rowCount: number): string {
  return pyFormat(sentence(loadContract(), 'document_offset_past_end'), {
    part,
    offset: num(offset),
    rows: num(rowCount),
    last: num(rowCount - 1),
  });
}

/**
 * `bantamkit_read_unknown_part`: a part the file does not have — a fact about the FILE
 * ("in {path}; it has: ...") and not about "this task", which is why it is not
 * `document_unknown`'s sentence.
 */
export function bantamkitReadUnknownPart(part: string, path: string, available: readonly string[]): string {
  return pyFormat(sentence(loadContract(), 'bantamkit_read_unknown_part'), {
    part,
    path,
    available: available.join(', '),
  });
}

/**
 * `document_error`: a reader failure, kept in the reader's own words, with the `error:`
 * prefix every other tool observation in the harness uses. `str(detail)` on the reference;
 * an `Error`'s `message` is that string here (`DocumentReadError` and `PyOSError` both put
 * the whole sentence there).
 */
export function documentError(detail: unknown): string {
  const text = detail instanceof Error ? detail.message : String(detail);
  return pyFormat(sentence(loadContract(), 'document_error'), { detail: text });
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
