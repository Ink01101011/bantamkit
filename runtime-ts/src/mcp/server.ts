/**
 * bantamkit as an MCP server: memory + validation over stdio, one instance per person.
 *
 * A port of `runtime-py/src/bantamkit/mcpserver.py`'s `build_server`, across two unrelated
 * SDK lineages — Python runs `mcp` 2.0.0 (`from mcp.server import MCPServer`), this runs
 * `@modelcontextprotocol/sdk` 1.30.0. Where the two SDKs make a difference unavoidable it is
 * a `ruling` case in `tools/conformance/suites/wire.mjs`, carrying its reason and required to
 * KEEP differing — a ruling whose case quietly started matching fails the suite too. Where
 * they do not, this file takes the reference's answer even when the SDK offers an easier one.
 *
 * THE LOW-LEVEL `Server` AND NOT `McpServer`, and the reason is the whole property. The
 * high-level class derives an advertisement from a zod schema and decides its own
 * capabilities; both would have been the TS SDK's answers rather than the reference's. Every
 * payload below is built by hand, out of the asset pack, in the reference's key order, so
 * that `tools/list`, `resources/templates/list` and every tool result are the SAME BYTES the
 * Python server emits. What the SDK is used for is the part that is genuinely protocol —
 * framing, request routing, the initialize handshake, cancellation, error codes.
 *
 * THE `surfaces` GATE IS LOAD-BEARING. `assets/tools/` serves the eval agent too, and three
 * of the thirteen manifests (`document_list`, `document_read`, `file_graph`) claim only `agent`.
 * `fromManifest` REFUSES those by name rather than filtering them out, because a filter is
 * indistinguishable from a typo: a manifest renamed or a surface dropped would silently
 * shrink the served set, and the field would be a comment.
 */
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import {
  CallToolRequestSchema,
  ErrorCode,
  GetPromptRequestSchema,
  ListPromptsRequestSchema,
  ListResourceTemplatesRequestSchema,
  ListResourcesRequestSchema,
  ListToolsRequestSchema,
  ReadResourceRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

import { AssetNotFound, assetsRoot, loadSkill, loadToolAsset } from '../assets.js';
import { BantamError } from '../errors.js';
import {
  bantamkitReadUnknownPart,
  documentError,
  documentManifest,
  documentOffsetPastEnd,
  documentPage,
  schemaError,
  toolFailed,
} from '../contract.js';
import * as docread from '../docread.js';
import * as skillaudit from '../skillaudit.js';
import { EventLog, type DetailValue } from '../eventlog.js';
import type { Memory } from '../memory/component.js';
import { PyOSError, asPyOSError, pyReadText } from '../memory/pyfs.js';
import { fromJs, parseJson, reprValue, toJs, type PyValue } from '../pyjson.js';
import * as shiftwork from '../shiftwork.js';
import { buildIdentity, SERVER_NAME } from './identity.js';
import { ARG_MODELS, PyValidationFailure, validateArguments } from './pyargs.js';
import { sdkJson } from './sdkjson.js';
import {
  degradedConditions,
  degradedNotice,
  SERVED_PROMPTS,
  SERVED_RESOURCE_TEMPLATES,
  statusReport,
  STATUS_NAME,
  STATUS_PROMPT_DESCRIPTION,
  STATUS_PROMPT_TAIL,
  STATUS_PROMPT_TITLE,
} from './status.js';
import type { RawStdioTransport } from './transport.js';

/**
 * The eleven, in the order `build_server` lists them — which is the order `tools/list` emits.
 *
 * `bantamkit_status` went LAST rather than first, `memory_compact` after it rather than
 * beside `memory_save` where a reader would look for it, `bantamkit_read` after that and
 * `skill_audit` after that, for the same reason the reference appends all four: registration
 * order IS the served order, and appending is the only edit that leaves the other ten where
 * every existing declaration says they are.
 */
export const MCP_TOOLS = [
  'memory_save',
  'memory_recall',
  'validate_json',
  'shiftwork_clock_in',
  'shiftwork_clock_out',
  'shiftwork_status',
  'build_identity',
  'bantamkit_status',
  'memory_compact',
  'bantamkit_read',
  'skill_audit',
] as const;


/**
 * The advertisement for one tool, out of its manifest, with the surface checked.
 *
 * Key order is `description, inputSchema, name, outputSchema` because that is the order the
 * reference's pydantic `Tool` model dumps in, and the nested schemas keep the manifest's own
 * key order because both runtimes preserve insertion order in a JSON object.
 *
 * `output_schema` is advertised VERBATIM and is not derived from anything this file knows.
 * That includes `build_identity.json`'s `"title": "build_identity_toolDictOutput"`, which
 * leaks the Python closure name `build_identity_tool` into a Node server's advertisement.
 * IT IS REPRODUCED, NOT FIXED. The manifest is an asset, `build_identity` hashes every asset
 * byte, and changing it would move `assets_digest` — the one field that is supposed to be
 * comparable across the two runtimes. A cosmetic title is not worth breaking the instrument
 * that detects drift. Registered here, not fixed here; `runtime-py` is the reference.
 */
export function fromManifest(name: string): Record<string, unknown> {
  const asset = loadToolAsset(name);
  const surfaces = (asset['surfaces'] ?? []) as string[];
  if (!surfaces.includes('mcp')) {
    throw new BantamError(
      `tool asset '${name}' does not claim the mcp surface: [${surfaces.map((s) => `'${s}'`).join(', ')}]`,
    );
  }
  return {
    description: asset['description'],
    inputSchema: asset['parameters'],
    name: asset['name'],
    outputSchema: asset['output_schema'],
  };
}

/**
 * `metadata.version("mcp")`'s analogue: the SDK's own manifest, found by walking UP.
 *
 * NOT `import.meta.resolve('@modelcontextprotocol/sdk/package.json')`. That resolves through
 * the SDK's `exports` map, whose `"./*"` arm points into `dist/esm/`, so it returns
 * `dist/esm/package.json` — the two-key `{"type": "module"}` marker file, with no `version`
 * at all. Measured: that route reported `mcp_sdk_version: null` from BOTH a dev checkout and
 * an installed tarball, which is exactly the sentinel `RB-P51` forbids — a field typed as a
 * version holding a value that reads as one. Found by driving the packaged install, not by
 * the suite, which is why there is now a case for it.
 *
 * So: resolve a real module, then walk parents until a `package.json` names the SDK AND
 * carries a version. Anything short of that is the unavailable object, never a sentinel.
 */
function sdkVersion(): string | { unavailable: string } {
  const unavailable = {
    unavailable:
      'no package.json naming @modelcontextprotocol/sdk with a version was found above the ' +
      'resolved SDK module, so the SDK version is not knowable here',
  };
  try {
    let dir = dirname(fileURLToPath(import.meta.resolve('@modelcontextprotocol/sdk/server/index.js')));
    for (let up = 0; up < 8; up += 1) {
      const candidate = join(dir, 'package.json');
      if (existsSync(candidate)) {
        const parsed = JSON.parse(readFileSync(candidate, 'utf8')) as { name?: string; version?: string };
        if (parsed.name === '@modelcontextprotocol/sdk' && typeof parsed.version === 'string') return parsed.version;
      }
      const parent = dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  } catch {
    return unavailable;
  }
  return unavailable;
}

/**
 * A JSON-RPC error, and NOT `McpError`.
 *
 * `new McpError(code, message)` sets `.message` to `MCP error <code>: <message>`, and
 * `Protocol` copies `.message` straight onto the wire — so the SDK's own error class would
 * put a prefix in a field the reference fills with the bare sentence. The protocol reads
 * `code`, `message` and `data` off whatever is thrown, so a plain `Error` carrying the three
 * is both simpler and exact.
 */
function rpcError(code: number, message: string, data: unknown): Error {
  return Object.assign(new Error(message), { code, data });
}

const asDict = (value: PyValue): Map<string, PyValue> => (value.t === 'dict' ? value.v : new Map());
const asText = (value: PyValue | undefined): string => (value && value.t === 'str' ? value.v : '');

/** `int | None` after validation: the tagged int, or `null` for the default. */
function asInt(value: PyValue | undefined): number | null {
  return value && value.t === 'int' ? Number(value.v) : null;
}

/**
 * Run `body` and, if it throws, record the exception's TYPE before letting it fly on.
 *
 * The host already logs that a tool failed and how long it took; what it cannot say is which
 * exception the component threw — and the one place it tried, it leaked an argument value
 * doing it (`eventlog.ts`'s comment, measured). So the constructor name and nothing else, via
 * `EventLog.raised`, which has no other input available to it.
 *
 * The rethrow is unconditional: nothing here decides whether the tool fails, only whether the
 * failure was written down. `EventLog.record` swallows its own system errors, so this cannot
 * mask the original.
 */
/** A rejection the filesystem produced: libuv's numeric `errno` and the `syscall` it names. */
function isFsError(e: unknown): e is NodeJS.ErrnoException {
  const err = e as NodeJS.ErrnoException;
  return e instanceof Error && typeof err.errno === 'number' && typeof err.syscall === 'string';
}

function recordRaise<T>(log: EventLog, tool: string, body: () => T): T {
  try {
    return body();
  } catch (e) {
    log.raised(tool, e);
    throw e;
  }
}

/**
 * Run a shiftwork handler and record its `result` — the register's OWN verdict.
 *
 * Every `shiftwork` entry point answers a dict whose `result` key is the decision it made:
 * `brief`, `escalate`, `success`, `ok`, `status`, `error`. `clockIn` returning `escalate` is
 * the sharp case — the register's whole stop-and-ask contract, invisible in the host's log
 * because the tool call succeeded. Reading the key is reading the decision; nothing here
 * inspects a `reason` string, which is prose and can carry a checkpoint path.
 *
 * `raised` is the outcome for an ESCAPING exception and is spelled differently from `error`
 * on purpose: `result: "error"` is a refusal the register composed and returned normally, and
 * collapsing the two would lose the only distinction between a checkpoint that was rejected
 * and a handler that fell over.
 */
function recordResult(log: EventLog, tool: string, call: () => PyValue): PyValue {
  const answer = recordRaise(log, tool, call);
  const result = asDict(answer).get('result');
  // `str(answer.get("result", "unknown"))`. `str` of a `str` is the string itself; `str` of
  // anything else is its `repr`, which is what `reprValue` writes. Every exit answers a
  // string today, so the second arm is a shape change being recorded rather than hidden.
  log.record(tool, result === undefined ? 'unknown' : result.t === 'str' ? result.v : reprValue(result));
  return answer;
}

/**
 * Run one tool and return its Python-shaped answer.
 *
 * The two return kinds are the SDK's, not this file's: `memory_save`, `memory_recall`,
 * `bantamkit_status`, `memory_compact` and `bantamkit_read` are annotated `-> str` in the
 * reference, so `_create_wrapped_model` puts them under a `result` key; the other five are
 * `-> dict[str, Any]` and pass through as themselves. That is why `structuredContent` is
 * exactly `{ result }` for those five of the ten, and carries the handler's own keys for
 * the other five.
 *
 * DO NOT READ THAT AS "FIVE TOOLS HAVE A `result` KEY". Driven over stdio, eight of the ten
 * answer with a `result` somewhere in `structuredContent`: the three shiftwork tools carry
 * one of their own, and it is the register's verdict, not this wrapper. `wrapped` below is
 * the bit that actually decides, and it is `true` exactly five times.
 *
 * EVERY RECORD BELOW COMES FROM A DECISION, NEVER FROM A REPLY. `memory_save` reads
 * `SaveOutcome.status`, `memory_recall` reads `RecallOutcome.status`, `memory_compact`
 * reads `CompactOutcome.status` (the store's own `archived` list, empty or not), the three shiftwork
 * tools read the register's own `result` key, `validate_json` reads the `valid` bool it is
 * about to return, `build_identity` reads the length of the `unavailable` list it
 * computed, and `bantamkit_read` records the BRANCH it took. Not one of them looks at the
 * words. Change a reply's wording and the record must be byte-identical —
 * `test/eventlog.test.mjs` holds exactly that.
 *
 * Logging happens HERE and not in the caller's `try`, so that an argument refusal — which
 * `validateArguments` raises before this function is entered, exactly as pydantic does before
 * the reference's handler is entered — writes no record on either side.
 *
 * THE DEGRADED FOOTER IS APPLIED AFTER THE RECORD, EVERY TIME. A footer is a rendering
 * decision about somebody else's answer; the record is the decision the component made.
 * Folding one into the other would put a filesystem observation into a line a conformance case
 * byte-compares, and would make the log move when nothing the tool did moved. `noted` and
 * `notedDict` below therefore run last, on the way out.
 */
function runTool(
  name: string,
  memory: Memory,
  args: Map<string, PyValue>,
  version: string,
  log: EventLog,
): { value: PyValue; wrapped: boolean } {
  /**
   * The footer for right now — recomputed per call, never cached.
   *
   * A cache would be the one thing that could make this lie: a condition that cleared (or
   * arrived) between two calls has to be visible on the next one, and the whole probe is a
   * handful of `stat`s. It is also what keeps two servers over one store from disagreeing
   * about the state of it.
   */
  const notice = (): string => degradedNotice(degradedConditions(memory, log));

  /** A prose reply, plus the footer if there is one. Byte-identical when healthy. */
  const noted = (reply: string): string => {
    const line = notice();
    return line === '' ? reply : `${reply}\n\n${line}`;
  };

  /**
   * A structured reply, plus the footer if there is one, under one reserved key.
   *
   * A JSON result has no margin to write in: the rendered text of these tools IS the
   * serialised object, so a sentence appended to it would stop being parseable. The footer
   * therefore arrives as `bantamkit_degraded`, LAST in the key order and only when it exists —
   * every one of these tools advertises `additionalProperties: true`, so a key that comes and
   * goes is inside the contract it already declares. A healthy call is byte-identical to what
   * it was before this surface existed, which is the same guarantee `noted` gives for prose.
   */
  const notedDict = (answer: PyValue): PyValue => {
    const line = notice();
    if (line === '' || answer.t !== 'dict') return answer;
    // A fresh Map preserves the answer's own key order and appends: the reserved key is not
    // one of these tools' fields, so `set` puts it at the end and nothing else moves.
    const out = new Map(answer.v);
    out.set('bantamkit_degraded', { t: 'str', v: line });
    return { t: 'dict', v: out };
  };

  switch (name) {
    case 'memory_save': {
      const links = args.get('links');
      const asStrings = links && links.t === 'list' ? links.v.map((v) => asText(v)) : null;
      const outcome = recordRaise(log, 'memory_save', () =>
        memory.saveOutcome(asText(args.get('type')), asText(args.get('name')), asText(args.get('description')), asText(args.get('body')), asStrings),
      );
      if (log.enabled) {
        // Only when a log is actually on: `indexAccounting` re-parses `facts/`, and a
        // diagnostic must not put that on the path of an operator who did not ask for one.
        // Headroom is left to the reader rather than stored — it is `budget - index_bytes`,
        // and a derived field is a second thing to keep true.
        const [indexBytes, budget] = memory.indexAccounting();
        const detail: Record<string, DetailValue> = { budget };
        if (indexBytes !== null) detail['index_bytes'] = indexBytes;
        log.record('memory_save', outcome.status, detail);
      }
      return { value: { t: 'str', v: noted(outcome.reply) }, wrapped: true };
    }
    case 'memory_recall': {
      let k = asInt(args.get('k'));
      // The advertised schema's bounds; clients may ignore it, so the server does not.
      if (k !== null) k = Math.max(1, Math.min(k, 5));
      const outcome = recordRaise(log, 'memory_recall', () => memory.recallOutcome(asText(args.get('query')), k));
      const detail: Record<string, DetailValue> = {
        budget: outcome.budget,
        candidates: outcome.candidates,
        layers: outcome.layers,
        reached: outcome.reached,
        returned: outcome.returned,
        unreadable: outcome.unreadable,
      };
      if (outcome.source !== null) detail['source'] = outcome.source;
      log.record('memory_recall', outcome.status, detail);
      return { value: { t: 'str', v: noted(outcome.reply) }, wrapped: true };
    }
    case 'validate_json': {
      const error = recordRaise(log, 'validate_json', () => schemaError(asText(args.get('output')), args.get('schema')!));
      const out = new Map<string, PyValue>([['valid', { t: 'bool', v: error === null }]]);
      out.set('feedback', error === null ? { t: 'null' } : { t: 'str', v: `${error}\nReturn ONLY a JSON object matching the schema.` });
      log.record('validate_json', error === null ? 'valid' : 'invalid');
      return { value: notedDict({ t: 'dict', v: out }), wrapped: false };
    }
    case 'shiftwork_clock_in':
      return {
        value: notedDict(recordResult(log, name, () => shiftwork.clockIn(asText(args.get('checkpoint'))))),
        wrapped: false,
      };
    case 'shiftwork_clock_out':
      return {
        value: notedDict(
          recordResult(log, name, () =>
            shiftwork.clockOut(
              asText(args.get('checkpoint')),
              asText(args.get('unit_id')),
              asText(args.get('status')),
              args.get('handoff_patch')!,
              args.get('history_entry')!,
              args.get('accounting') ?? { t: 'null' },
            ),
          ),
        ),
        wrapped: false,
      };
    case 'shiftwork_status':
      return {
        value: notedDict(recordResult(log, name, () => shiftwork.status(asText(args.get('checkpoint'))))),
        wrapped: false,
      };
    case 'build_identity': {
      const identity = recordRaise(log, 'build_identity', () => buildIdentity(version, sdkVersion()));
      // The COUNT of underivable fields, not the fields and not the digests. A code digest is
      // by construction different in the two runtimes — they fingerprint two different trees
      // — so putting one in a record that a conformance case byte-compares would make the
      // record unportable to buy nothing the tool's own reply does not already say.
      const unavailable = identity.get('unavailable') as unknown[];
      log.record('build_identity', unavailable.length ? 'partial' : 'complete', { unavailable: unavailable.length });
      return { value: notedDict(fromJs(identity)), wrapped: false };
    }
    case 'bantamkit_status': {
      // NO FOOTER ON THIS ONE, and the omission is the design rather than an oversight: the
      // report already carries every condition in full, and a footer would repeat the worst of
      // them three lines below itself.
      //
      // NOTHING IS RECORDED IN THE EVENT LOG EITHER. Every other handler records the decision
      // its component made; this one makes no decision — it observes. A record would be a
      // second, worse copy of a state the log's own reader can see, and its `outcome` would
      // have to be the health verdict, which moves with the filesystem rather than with
      // anything the call did. `recordRaise` still wraps the body, so a handler that FALLS
      // OVER is still written down.
      const report = recordRaise(log, 'bantamkit_status', () =>
        statusReport(
          memory,
          log,
          degradedConditions(memory, log),
          buildIdentity(version, sdkVersion()),
          MCP_TOOLS.length,
          SERVED_PROMPTS,
          SERVED_RESOURCE_TEMPLATES,
        ),
      );
      return { value: { t: 'str', v: report }, wrapped: true };
    }
    case 'memory_compact': {
      // The model's half of compaction; the hook (`docs/hooks.md`) is the automatic half.
      // `memory_save`'s refused-budget reply names this tool, so it acts on exactly the store
      // that refused: `compactOutcome` reaches `memory.store` — the writable project layer —
      // and never a grant or the profile layer. The status is the store's own decision
      // (`archived` when the archive list is non-empty, `nothing-archived` otherwise), never
      // a match on the reply.
      const reserve = asInt(args.get('reserve'));
      // No floor here: `MemoryStore.compact` clamps `reserve` to `[0, budget/2]` itself, as
      // the reference's does, so a negative value is handled where the arithmetic lives.
      const outcome = recordRaise(log, 'memory_compact', () => memory.compactOutcome(reserve));
      log.record('memory_compact', outcome.status, {
        archived: outcome.archived,
        budget: outcome.budget,
        index_after: outcome.indexAfter,
        index_before: outcome.indexBefore,
      });
      return { value: { t: 'str', v: noted(outcome.reply) }, wrapped: true };
    }
    case 'bantamkit_read': {
      // The reader on the MCP surface (job43): `docread` digests, `contract` words it. The
      // handler makes the SAME `contract` calls the reference's `bantamkit_read` makes,
      // with the path standing in for the document name, so the two servers print the
      // same bytes for the same file. Three sentences are this tool's own — the continuation
      // line names `bantamkit_read`, an unknown part is a fact about the file, and so is a
      // part with no rows (`document_error` over `"{part}" in {path} has no rows`).
      //
      // THE RECORD IS A DECISION, NEVER A REPLY. `manifest` and `page` are the branch
      // taken; `refused-unreadable` is `extract` raising (a missing file, a directory, a
      // container this reader has no extractor for, an `OSError` the filesystem threw —
      // all of them reach the model as a `document_error` sentence in the reader's own
      // words, never as an exception on the wire); `refused-unknown-part` and
      // `refused-offset` are the two argument refusals — the latter also when the part has
      // no rows at all, where NO offset can be in range and the sentence says so instead of
      // "numbered 0 to -1" (review round 3). `detail` carries the container
      // kind (a token from `docread`'s closed set), the part count, and the rows and UTF-8
      // bytes the reply carries — never the path, never a part name, never a row.
      //
      // `limit` is clamped to the advertised `[1, 200]` and `offset` to `>= 0` the way
      // `memory_recall` clamps `k`: the schema says so, and a client may ignore it.
      const path = asText(args.get('path'));
      const partArg = args.get('part');
      const part = partArg !== undefined && partArg.t === 'str' ? partArg.v : null;
      const offsetArg = asInt(args.get('offset'));
      const start = offsetArg === null ? 0 : Math.max(0, offsetArg);
      const limitArg = asInt(args.get('limit'));
      const rows = limitArg === null ? docread.DEFAULT_ROW_LIMIT : Math.max(1, Math.min(limitArg, docread.PAGE_MAX_ROWS));
      // `with _record_raise(log, "bantamkit_read")` wraps the reference's WHOLE handler, the
      // `extract` call included, so an exception the reader lets escape (`LookupError` from
      // an XML declaration naming no codec) is recorded `raised` and then reaches the wire
      // as an `isError` frame. A corrupt deflate stream or a lying CRC no longer does: since
      // review round 3 `_read`/`readMember` word both as the damaged-member sentence, a
      // `document_error` like the encrypted one. Until job43 G2 this arm ran `extract`
      // outside `recordRaise` with a hand-copied catch.
      return recordRaise(log, 'bantamkit_read', () => {
        let doc: docread.Document;
        try {
          doc = docread.extract(path);
        } catch (e) {
          // `except (docread.DocumentReadError, OSError)`. A Node fs error is CPython's
          // `OSError` with the sentence rebuilt by `asPyOSError` — `[Errno 13] Permission
          // denied: '<path>'` for a file this process may not open — through the CRT arm,
          // because `open()` is the call the reference makes. A `BadZipFile` never reaches
          // this arm on either side: `docread.ts`'s `zipKind`/`openZip` catch it exactly
          // where `docread.py`'s `_zip_kind`/`_open` do, and what leaves them is the
          // sentence naming what the reader saw, never the zip module's.
          // A `PyOSError` the reader raised itself is already the reference's sentence —
          // `[Errno 22] Invalid argument` from a zip whose member offset is negative, with
          // NO filename, because the `seek` that fails there has none. Re-wrapping it would
          // append `: '<path>'`.
          // ONLY a filesystem rejection is an `OSError`: numeric `errno` AND the `syscall`
          // it came from. A string `code` alone is not one — `Z_DATA_ERROR`,
          // `ERR_INVALID_ARG_VALUE` and `ERR_STRING_TOO_LONG` all carry one, and until job43
          // G2 each was printed as a fabricated `[Errno 0] …` sentence where the reference
          // raises (the corrupt stream) or says `no such file` (the NUL byte, which
          // `docread.statPath` now answers before this arm is reached).
          const refusal =
            e instanceof docread.DocumentReadError || e instanceof PyOSError
              ? e
              : isFsError(e)
                ? asPyOSError(e, path, undefined, 'crt')
                : null;
          if (refusal === null) throw e;
          log.record('bantamkit_read', 'refused-unreadable');
          return { value: { t: 'str', v: noted(documentError(refusal)) }, wrapped: true };
        }
        const detail: Record<string, DetailValue> = { kind: doc.kind, parts: doc.parts.length };
        if (part === null) {
          const reply = documentManifest(
            doc.parts.map((p) => ({
              document: path,
              kind: doc.kind,
              index: p.index,
              part: p.name,
              row_count: p.rowCount,
              rows: p.rows,
              omissions: p.omissions.map((o) => o.asDict()),
            })),
            doc.omissions.length ? [{ document: path, omissions: doc.omissions.map((o) => o.asDict()) }] : [],
          );
          detail['rows'] = doc.parts.reduce((sum, p) => sum + p.rowCount, 0);
          detail['bytes'] = doc.textBytes;
          log.record('bantamkit_read', 'manifest', detail);
          return { value: { t: 'str', v: noted(reply) }, wrapped: true };
        }
        let target: docread.Part;
        try {
          target = doc.part(part);
        } catch (e) {
          if (!(e instanceof docread.DocumentReadError)) throw e;
          log.record('bantamkit_read', 'refused-unknown-part', detail);
          const reply = bantamkitReadUnknownPart(part, path, doc.parts.map((p) => p.name));
          return { value: { t: 'str', v: noted(reply) }, wrapped: true };
        }
        if (target.rowCount === 0) {
          log.record('bantamkit_read', 'refused-offset', detail);
          const reply = documentError(`"${target.name}" in ${path} has no rows`);
          return { value: { t: 'str', v: noted(reply) }, wrapped: true };
        }
        if (start >= target.rowCount) {
          log.record('bantamkit_read', 'refused-offset', detail);
          const reply = documentOffsetPastEnd(target.name, start, target.rowCount);
          return { value: { t: 'str', v: noted(reply) }, wrapped: true };
        }
        const got = docread.page(doc, part, start, rows, docread.PAGE_MAX_BYTES);
        detail['rows'] = got.rows.length;
        detail['bytes'] = Buffer.byteLength(got.text, 'utf8');
        log.record('bantamkit_read', 'page', detail);
        const reply = documentPage(
          path,
          got.part,
          got.offset,
          got.rows,
          got.totalRows,
          got.nextOffset,
          got.truncatedBytes,
          'bantamkit_read_page_next',
        );
        return { value: { t: 'str', v: noted(reply) }, wrapped: true };
      });
    }
    case 'skill_audit': {
      // The catalogue auditor on the MCP surface (job44): `skillaudit` measures, this serves
      // it.
      //
      // THE REPLY IS A JSON DOCUMENT AND NOT PROSE, which is the one thing that makes this
      // handler shaped differently from `bantamkit_read` above. The reader answers a person
      // reading a transcript, so `contract` words it; this answers a caller that has to
      // compare `catalogue_bytes` against a budget it set and act on the ids in
      // `findings[].skills`. A sentence would have to be parsed back. So `Audit.asJson` is
      // the reply verbatim, and the only string this layer authors is the refusal.
      //
      // THE REFUSALS ARE ARGUMENT FAILURES, ALL THREE OF THEM, so they go through
      // `toolFailed` — an unknown `check`, a negative `budget`, a `root` that is not a
      // directory. Nothing about the CONTENT of the tree refuses: a file that will not
      // decode, a block that will not parse and a plugin that is switched off are recorded as
      // omissions and counted.
      //
      // `check` defaults HERE rather than in the module's signature so that the one spelling
      // of the default lives in `skillaudit.audit`, and `null` and an absent argument reach
      // it as the same thing. `enabled` and `usage` do the same: an absent map is no
      // measurement, an empty one is a measurement of nothing, and the two answer differently.
      // `versions` is the third caller-supplied host fact: the version directory the host
      // actually serves, per `<plugin>@<marketplace>`, passed straight through, with an absent
      // map meaning the byte-order fallback for every plugin.
      //
      // THE RECORD IS A DECISION, NEVER A REPLY, and it holds no free text: `audited` carries
      // the four counts the host cannot see and `refused` carries nothing at all. `root` is a
      // path the operator typed and `findings[].skills` are the names of their skills;
      // neither is a decision this handler made, so neither is written down.
      const root = asText(args.get('root'));
      const enabledArg = args.get('enabled');
      const enabled =
        enabledArg !== undefined && enabledArg.t === 'list'
          ? enabledArg.v.map((item) => (item.t === 'str' ? item.v : ''))
          : null;
      const usageArg = args.get('usage');
      let usage: Map<string, bigint> | null = null;
      if (usageArg !== undefined && usageArg.t === 'dict') {
        usage = new Map();
        for (const [key, value] of usageArg.v) usage.set(key, value.t === 'int' ? value.v : 0n);
      }
      const checkArg = args.get('check');
      const check = checkArg !== undefined && checkArg.t === 'str' ? checkArg.v : 'all';
      const budgetArg = args.get('budget');
      const budget = budgetArg !== undefined && budgetArg.t === 'int' ? budgetArg.v : null;
      const versionsArg = args.get('versions');
      let versions: Map<string, string> | null = null;
      if (versionsArg !== undefined && versionsArg.t === 'dict') {
        versions = new Map();
        for (const [key, value] of versionsArg.v) versions.set(key, value.t === 'str' ? value.v : '');
      }
      return recordRaise(log, 'skill_audit', () => {
        let result: skillaudit.Audit;
        try {
          result = skillaudit.audit(root, { enabled, usage, check, budget, versions });
        } catch (e) {
          // `except (skillaudit.SkillAuditError, OSError)`. The module answers `no such
          // directory` for a root it cannot stat, so a filesystem rejection is already inside
          // its own sentence and nothing else here catches one.
          if (!(e instanceof skillaudit.SkillAuditError)) throw e;
          log.record('skill_audit', 'refused');
          return { value: { t: 'str', v: noted(toolFailed('skill_audit', e)) }, wrapped: true };
        }
        log.record('skill_audit', 'audited', {
          skills: result.skills,
          bytes: result.catalogueBytes,
          findings: result.findings.length,
          omissions: result.omissions.length,
        });
        return { value: { t: 'str', v: noted(result.asJson()) }, wrapped: true };
      });
    }
    default:
      // `tool_manager.call_tool` raises `ToolError(f"Unknown tool: {name}")`, which the
      // handler turns into an isError result rather than a JSON-RPC error.
      throw new BantamError(`Unknown tool: ${name}`);
  }
}

/**
 * Assemble the MCP server around one Memory instance (the per-person state).
 *
 * `wire` is the transport, and it is a parameter rather than something this function creates
 * because the handlers need it twice: to read the RAW request line (so `5.0` is still a float
 * when it reaches `shiftwork.clockOut`) and to register the EXACT result text (so it is still
 * a float on the way back out).
 *
 * `log` is the event-log sink (`docs/eventlog.md`), resolved from `BANTAMKIT_EVENT_LOG` when
 * the caller does not supply one and DISABLED unless that variable asks for it. It is a
 * parameter and not only an environment read so that a test can inject a fixed clock and a
 * scratch path without setting a process-wide variable — the same seam `runtime-py`'s
 * `build_server(memory, log=None)` offers.
 */
export function buildServer(
  memory: Memory,
  wire: RawStdioTransport,
  version: string,
  log: EventLog = EventLog.fromEnv(memory.store.root),
): Server {
  const server = new Server(
    { name: SERVER_NAME, version },
    {
      // The reference's advertisement, verbatim. The TS SDK's own default would be
      // `{tools:{listChanged:true},resources:{listChanged:true}}` with no `prompts` and no
      // `experimental` — a client that switched on any of those four would behave
      // differently against the two servers, which is the difference this exists to remove.
      capabilities: {
        experimental: {},
        prompts: { listChanged: false },
        resources: { listChanged: false, subscribe: false },
        tools: { listChanged: false },
      },
      instructions: loadSkill('memory'),
    },
  );

  // Startup, not call time: a tool without a manifest, or with the wrong surface, must stop
  // the process before a client ever sees a `tools/list`. The reference gets this from
  // `MCPServer(..., tools=[...])`; here it is one eager pass.
  const advertised = MCP_TOOLS.map((name) => fromManifest(name));

  server.setRequestHandler(ListToolsRequestSchema, () => ({ tools: advertised }));
  server.setRequestHandler(ListResourcesRequestSchema, () => ({ resources: [] }));

  // THE PROMPT, AND WHY IT IS NOT A DUPLICATE OF THE TOOL ABOVE.
  //
  // `prompts/list` was EMPTY on both runtimes while both advertised `prompts: {listChanged:
  // false}`, so this is a new surface rather than an addition to one. A tool is what the MODEL
  // can call; a prompt is what a PERSON invokes — in Claude Code it is a slash command in the
  // operator's own menu. The person wanting to know whether their server is alive is the
  // operator, and until now the only way for them to ask was to talk a model into asking.
  //
  // Key order is `arguments, description, name, title` and `description, messages` because
  // that is the order `mcp` 2.0.0's pydantic `Prompt` and `GetPromptResult` models dump in —
  // measured against the running reference, not guessed. Both are compared as RAW BYTES by
  // `wire`, so the order is part of the answer.
  server.setRequestHandler(ListPromptsRequestSchema, () => ({
    prompts: [
      {
        // `arguments: []` is emitted, not omitted: the reference's model has a default of
        // `[]` for a prompt function with no parameters, and a client comparing two
        // advertisements would see a key appear and disappear.
        arguments: [],
        description: STATUS_PROMPT_DESCRIPTION,
        name: STATUS_NAME,
        title: STATUS_PROMPT_TITLE,
      },
    ],
  }));

  // IT CARRIES THE ANSWER, not an instruction to go and get it. `prompts/get` runs
  // server-side, so the report is already in the message the host inserts: the operator sees
  // it with no tool round trip, and it is true as of the moment they asked.
  server.setRequestHandler(GetPromptRequestSchema, (request) => {
    // The reference's `PromptManager` raises for an unregistered name, which the SDK turns
    // into a JSON-RPC error; the TS SDK does the same for a handler that throws. One name is
    // registered, so anything else is unknown.
    if (request.params.name !== STATUS_NAME) {
      throw rpcError(ErrorCode.InvalidParams, `Unknown prompt: ${request.params.name}`, null);
    }
    const conditions = degradedConditions(memory, log);
    const report = statusReport(
      memory,
      log,
      conditions,
      buildIdentity(version, sdkVersion()),
      MCP_TOOLS.length,
      SERVED_PROMPTS,
      SERVED_RESOURCE_TEMPLATES,
    );
    return {
      description: STATUS_PROMPT_DESCRIPTION,
      messages: [{ content: { text: `${report}\n\n${STATUS_PROMPT_TAIL}`, type: 'text' as const }, role: 'user' as const }],
    };
  });

  server.setRequestHandler(ListResourceTemplatesRequestSchema, () => ({
    // `description: ""` is emitted, not omitted: the reference's pydantic model has a
    // default of `""` for a resource function with no docstring, and a client that compared
    // two advertisements would see a key appear and disappear. `name` is the PYTHON FUNCTION
    // NAME, which is why these read `skill_resource` and `rubric_resource`.
    resourceTemplates: [
      { description: '', mimeType: 'text/plain', name: 'skill_resource', uriTemplate: 'bantamkit://skills/{name}' },
      { description: '', mimeType: 'text/plain', name: 'rubric_resource', uriTemplate: 'bantamkit://rubrics/{name}' },
    ],
  }));

  server.setRequestHandler(ReadResourceRequestSchema, (request) => {
    const uri = request.params.uri;
    const skill = /^bantamkit:\/\/skills\/([^/]*)$/.exec(uri);
    if (skill) {
      let text: string;
      try {
        text = loadSkill(skill[1]!);
      } catch (e) {
        if (!(e instanceof AssetNotFound)) throw e;
        throw rpcError(ErrorCode.InternalError, `unknown skill asset: ${skill[1]}`, { uri });
      }
      return { contents: [{ mimeType: 'text/plain', text, uri }] };
    }
    const rubric = /^bantamkit:\/\/rubrics\/([^/]*)$/.exec(uri);
    if (rubric) {
      const path = join(assetsRoot(), 'rubrics', `${rubric[1]}.yaml`);
      let text: string;
      try {
        text = pyReadText(path);
      } catch {
        throw rpcError(ErrorCode.InternalError, `unknown rubric asset: ${rubric[1]}`, { uri });
      }
      return { contents: [{ mimeType: 'text/plain', text, uri }] };
    }
    // The template variable matches ONE segment and MAY BE EMPTY — measured: the reference
    // answers `bantamkit://skills/` with -32603 `unknown skill asset: `, not with "unknown
    // resource", so `[^/]*` and not `[^/]+`. A traversal is still not a match at all,
    // because `bantamkit://skills/../../etc/passwd` has separators in it, and the reference
    // answers that one -32602.
    throw rpcError(ErrorCode.InvalidParams, `Unknown resource: ${uri}`, { uri });
  });

  server.setRequestHandler(CallToolRequestSchema, (request, extra) => {
    const name = request.params.name;
    const raw = wire.rawLineFor(extra.requestId);
    // The whole reason the transport keeps the line: `JSON.parse` has already destroyed the
    // int/float distinction by the time `request.params` exists, and `5.0` in an accounting
    // record has to reach the `.log.jsonl` as `5.0`.
    const args = raw !== undefined ? argumentsFrom(raw) : fromJs(request.params.arguments ?? {});

    let text: string;
    let structured: string | null;
    let structuredValue: PyValue | null = null;
    let isError: boolean;
    try {
      const model = ARG_MODELS[name];
      if (model === undefined) throw new BantamError(`Unknown tool: ${name}`);
      const bound = validateArguments(model, args);
      const { value, wrapped } = runTool(name, memory, bound, version, log);
      // `_convert_to_content` runs BEFORE the `{"result": ...}` wrap, so a str tool's text
      // block is the RAW STRING and a dict tool's is `to_json(..., indent=2)`.
      text = value.t === 'str' ? value.v : sdkJson(value, 2);
      structuredValue = wrapped ? { t: 'dict', v: new Map([['result', value]]) } : value;
      structured = sdkJson(structuredValue);
      isError = false;
    } catch (e) {
      // Every exception out of a tool becomes `ToolError(f"Error executing tool {name}: {e}")`
      // in the reference and reaches the client as an isError RESULT, never a JSON-RPC error.
      // `Unknown tool:` is the one that is already a full sentence and is not prefixed.
      const message = e instanceof PyValidationFailure ? e.detail : (e as Error).message;
      text = message.startsWith('Unknown tool: ') ? message : `Error executing tool ${name}: ${message}`;
      structured = null;
      structuredValue = null;
      isError = true;
    }

    wire.setExactResult(
      extra.requestId,
      `{"content":[{"text":${JSON.stringify(text)},"type":"text"}],"isError":${isError}` +
        `${structured === null ? '' : `,"structuredContent":${structured}`}}`,
    );
    return {
      content: [{ type: 'text' as const, text }],
      isError,
      ...(structuredValue === null ? {} : { structuredContent: toJs(structuredValue) as Record<string, unknown> }),
    };
  });

  return server;
}

/** `params.arguments` out of the raw request line, with every number literal intact. */
function argumentsFrom(line: string): PyValue {
  try {
    const params = asDict(parseJson(line)).get('params');
    const args = params === undefined ? undefined : asDict(params).get('arguments');
    return args ?? { t: 'dict', v: new Map() };
  } catch {
    // Unreachable over a line the SDK already parsed; a re-parse failure must not be the
    // thing that decides a tool call, so it falls back to the parsed view.
    return { t: 'dict', v: new Map() };
  }
}
