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
 * of the ten manifests (`document_list`, `document_read`, `file_graph`) claim only `agent`.
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
  ListPromptsRequestSchema,
  ListResourceTemplatesRequestSchema,
  ListResourcesRequestSchema,
  ListToolsRequestSchema,
  ReadResourceRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

import { AssetNotFound, assetsRoot, loadSkill, loadToolAsset } from '../assets.js';
import { BantamError } from '../errors.js';
import { schemaError } from '../contract.js';
import { EventLog, type DetailValue } from '../eventlog.js';
import type { Memory } from '../memory/component.js';
import { pyReadText } from '../memory/pyfs.js';
import { fromJs, parseJson, reprValue, toJs, type PyValue } from '../pyjson.js';
import * as shiftwork from '../shiftwork.js';
import { buildIdentity, SERVER_NAME } from './identity.js';
import { ARG_MODELS, PyValidationFailure, validateArguments } from './pyargs.js';
import { sdkJson } from './sdkjson.js';
import type { RawStdioTransport } from './transport.js';

/** The seven, in the order `build_server` lists them — which is the order `tools/list` emits. */
export const MCP_TOOLS = [
  'memory_save',
  'memory_recall',
  'validate_json',
  'shiftwork_clock_in',
  'shiftwork_clock_out',
  'shiftwork_status',
  'build_identity',
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
 * The two return kinds are the SDK's, not this file's: `memory_save` and `memory_recall` are
 * annotated `-> str` in the reference, so `_create_wrapped_model` puts them under a `result`
 * key; the other five are `-> dict[str, Any]` and pass through as themselves. That is why
 * `structuredContent` has a `result` key for exactly two of the seven.
 *
 * EVERY RECORD BELOW COMES FROM A DECISION, NEVER FROM A REPLY. `memory_save` reads
 * `SaveOutcome.status`, `memory_recall` reads `RecallOutcome.status`, the three shiftwork
 * tools read the register's own `result` key, `validate_json` reads the `valid` bool it is
 * about to return, and `build_identity` reads the length of the `unavailable` list it
 * computed. Not one of them looks at the words. Change a reply's wording and the record must
 * be byte-identical — `test/eventlog.test.mjs` holds exactly that.
 *
 * Logging happens HERE and not in the caller's `try`, so that an argument refusal — which
 * `validateArguments` raises before this function is entered, exactly as pydantic does before
 * the reference's handler is entered — writes no record on either side.
 */
function runTool(
  name: string,
  memory: Memory,
  args: Map<string, PyValue>,
  version: string,
  log: EventLog,
): { value: PyValue; wrapped: boolean } {
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
      return { value: { t: 'str', v: outcome.reply }, wrapped: true };
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
      return { value: { t: 'str', v: outcome.reply }, wrapped: true };
    }
    case 'validate_json': {
      const error = recordRaise(log, 'validate_json', () => schemaError(asText(args.get('output')), args.get('schema')!));
      const out = new Map<string, PyValue>([['valid', { t: 'bool', v: error === null }]]);
      out.set('feedback', error === null ? { t: 'null' } : { t: 'str', v: `${error}\nReturn ONLY a JSON object matching the schema.` });
      log.record('validate_json', error === null ? 'valid' : 'invalid');
      return { value: { t: 'dict', v: out }, wrapped: false };
    }
    case 'shiftwork_clock_in':
      return { value: recordResult(log, name, () => shiftwork.clockIn(asText(args.get('checkpoint')))), wrapped: false };
    case 'shiftwork_clock_out':
      return {
        value: recordResult(log, name, () =>
          shiftwork.clockOut(
            asText(args.get('checkpoint')),
            asText(args.get('unit_id')),
            asText(args.get('status')),
            args.get('handoff_patch')!,
            args.get('history_entry')!,
            args.get('accounting') ?? { t: 'null' },
          ),
        ),
        wrapped: false,
      };
    case 'shiftwork_status':
      return { value: recordResult(log, name, () => shiftwork.status(asText(args.get('checkpoint')))), wrapped: false };
    case 'build_identity': {
      const identity = recordRaise(log, 'build_identity', () => buildIdentity(version, sdkVersion()));
      // The COUNT of underivable fields, not the fields and not the digests. A code digest is
      // by construction different in the two runtimes — they fingerprint two different trees
      // — so putting one in a record that a conformance case byte-compares would make the
      // record unportable to buy nothing the tool's own reply does not already say.
      const unavailable = identity.get('unavailable') as unknown[];
      log.record('build_identity', unavailable.length ? 'partial' : 'complete', { unavailable: unavailable.length });
      return { value: fromJs(identity), wrapped: false };
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
  server.setRequestHandler(ListPromptsRequestSchema, () => ({ prompts: [] }));
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
