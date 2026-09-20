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
 * of the seventeen manifests (`document_list`, `document_read`, `file_graph`) claim only
 * `agent`, while two (`bantamkit_read`, `repo_map`) claim NO surface at all since job50 I5
 * (2026-09-12). `fromManifest` REFUSES those by name rather than filtering them out, because
 * a filter is indistinguishable from a typo: a manifest renamed or a surface dropped would
 * silently shrink the served set, and the field would be a comment. `MCP_TOOLS` below is the
 * SAME literal list the reference's `build_server` holds, in the same order, and the asset is
 * the gate on every name in it — not the source of the names, because the served ORDER is
 * part of the wire and no asset carries it.
 */
import { existsSync, readFileSync, realpathSync, statSync } from 'node:fs';
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
import * as repomap from '../repomap.js';
import * as skillaudit from '../skillaudit.js';
import { PriceTableError } from '../pricing.js';
import * as tokenledger from '../tokenledger.js';
import { EventLog, type DetailValue } from '../eventlog.js';
import type { Memory } from '../memory/component.js';
import { PyOSError, asPyOSError, pyReadText } from '../memory/pyfs.js';
import { fromJs, parseJson, reprValue, toJs, type PyValue } from '../pyjson.js';
import * as shiftwork from '../shiftwork.js';
import { plan, type PlanNode } from '../workplan.js';
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
 * The fourteen, in the order `build_server` lists them — which is the order `tools/list` emits.
 *
 * `bantamkit_status` went LAST rather than first, `memory_compact` after it rather than
 * beside `memory_save` where a reader would look for it, `skill_audit` after that,
 * `memory_dream` after that, `token_ledger` after that and `work_plan` then `shiftwork_plan`
 * after that, for the same reason the reference appends: registration order IS the served
 * order, and appending is the only edit that leaves the others where every existing
 * declaration says they are.
 *
 * `work_plan` BEFORE `shiftwork_plan` is the reference's order (`mcpserver.py`'s `tools`
 * list), and it is load-bearing rather than alphabetical: `runtime-py/tests/data/
 * served-tool-surface.json` pins the served order as a golden and `wire.mjs` compares the
 * two `tools/list` answers frame by frame, so registering them the other way round is a
 * red in three places and a wire change nobody asked for.
 *
 * `bantamkit_read` (tenth) and `repo_map` (thirteenth) LEFT this list on the user's ruling
 * of 2026-09-12 (job50, I5), the same ruling that took them out of the reference's
 * `tools = [...]`: measured over the transcript corpus, neither was called — auto-mode routes
 * discovery and reading through Bash — and every request re-sent their descriptions. Their
 * assets claim NO surface now (`"surfaces": []`), so putting either name back here without
 * also restoring `"mcp"` to its asset is refused by `fromManifest` at startup; and a name
 * that is not here is `Unknown tool:` on `tools/call` even though `ARG_MODELS` still holds
 * its argument model. The handlers below are DORMANT, not gone: a roster decision, not a
 * deletion of working code.
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
  'skill_audit',
  'memory_dream',
  'token_ledger',
  'work_plan',
  'shiftwork_plan',
] as const;

/** The served set, for the call path: a name outside it is unknown, whatever `ARG_MODELS` says. */
const SERVED: ReadonlySet<string> = new Set<string>(MCP_TOOLS);


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

/**
 * `work_plan`'s `nodes` as `workplan.plan` takes them.
 *
 * The reference's model is `list[dict[str, Any]]`, so pydantic guarantees a list of dicts
 * and NOTHING about what is inside one; `workplan.plan` then reads `node["id"]`,
 * `node.get("depends_on") or []` and `node.get("priority", 0)` off raw Python objects. This
 * reproduces those three reads and their defaults.
 *
 * A NODE WITH NO `id` RAISES, and raising is the port: `node["id"]` is a `KeyError` on the
 * reference, whose `str()` is the key in single quotes, so the SDK's envelope reads
 * `Error executing tool work_plan: 'id'`. Defaulting it here would answer a plan over a
 * node the reference refused to look at.
 *
 * WHERE THE DYNAMIC HALF STOPS, said rather than hidden. Python keeps an id's own type and
 * this side stringifies it with `str()`'s spelling (`reprValue` for every non-`str`), so a
 * document mixing `5` and `"5"` is two nodes there and one here, and a non-numeric
 * `priority` is a `TypeError` there and a 0 here. Both need a node whose types contradict
 * `assets/tools/work_plan.json`, which nothing in the shift-work corpus produces; they are
 * named here because an unwritten difference is the one that is found later.
 */
function planNodes(value: PyValue | undefined): PlanNode[] {
  const pyText = (v: PyValue): string => (v.t === 'str' ? v.v : reprValue(v));
  const items = value !== undefined && value.t === 'list' ? value.v : [];
  return items.map((item) => {
    const node = item.t === 'dict' ? item.v : new Map<string, PyValue>();
    const id = node.get('id');
    if (id === undefined) throw new BantamError("'id'");
    const declared = node.get('depends_on');
    const priority = node.get('priority');
    return {
      id: pyText(id),
      // `list(node.get("depends_on") or [])`: missing, `null` and `[]` are one case.
      depends_on: declared !== undefined && declared.t === 'list' ? declared.v.map(pyText) : [],
      priority: priority !== undefined && (priority.t === 'int' || priority.t === 'float') ? Number(priority.v) : 0,
    };
  });
}

/** `int | None` after validation: the tagged int, or `null` for the default. */
function asInt(value: PyValue | undefined): number | null {
  return value && value.t === 'int' ? Number(value.v) : null;
}

/**
 * The errno family `Path.exists()` and `Path.is_dir()` answer `False` for instead of
 * raising — CPython `pathlib`'s `_IGNORED_ERRNOS`, spelled as Node's `code` strings.
 *
 * Not a guess and not a superset: anything OUTSIDE this set makes both predicates raise on
 * the reference, so it must reach `recordRaise` here too. A `statSync` wrapped in a bare
 * `catch { }` would turn a permission failure into "no such directory", which is a
 * different sentence about a different problem.
 */
const EXISTS_IGNORED = new Set(['ENOENT', 'ENOTDIR', 'EBADF', 'ELOOP']);

/**
 * The last paragraph of every `repo_map` reply, refusal excepted. FIXED AND MANDATORY, and
 * byte-identical to the reference's `REPO_MAP_TAIL`.
 *
 * DORMANT — `repo_map` left the roster (job50 I5, 2026-09-12). The tail, `REPO_MAP_EMPTY`
 * and `repoMapReply` below stay with the handler: a roster decision, not a deletion of
 * working code.
 *
 * Roadmap row 10's build gate was "build only after #4 shows discovery tokens dominate",
 * and #4 REFUTED it: discovery is 0.114 % of real prompt tokens because 97.8 % of the bill
 * is `cache_read`. The feature ships on an explicit ruling to build it anyway, as a
 * PRECISION feature. A surface that let a caller believe the map is a token saving would
 * say the one thing the measurement forbids, so the refutation travels with every answer
 * rather than living only in a doc nobody reads at call time.
 *
 * The second sentence is the budget's unit, for the same reason: `DEFAULT_BUDGET = 4000` is
 * "1 K tokens" only at the char/4 convention, whose error bar is unmeasured because
 * measuring it needs the tokenizer the pure-node ruling forbids.
 */
export const REPO_MAP_TAIL =
  'This is a precision pass, not a token saving: this feature\'s build gate was REFUTED ' +
  'by measurement — discovery is 0.114% of real prompt tokens, because 97.8% of the ' +
  'bill is cache_read — so a map does not make a session cheaper. What it buys is the ' +
  'right file found sooner.\n' +
  'The budget above is UTF-8 BYTES of listing, not tokens: neither runtime carries a ' +
  'model tokenizer and this tool will not pretend to one.';

/** What a listing says when there is nothing to list. The reference's `REPO_MAP_EMPTY`. */
export const REPO_MAP_EMPTY = '(nothing listed: no file under this root scanned into a definition)';

/**
 * The `repo_map` tool's prose, byte for byte, from the structured result.
 *
 * Split out of the handler for the same reason the reference splits `repo_map_reply` out of
 * its own: one shape to reproduce rather than a format string buried in a `case`, and the
 * `repomap` conformance suite compares the rendered reply without standing up a server. No
 * float is ever rendered here — `repomap`'s trap (8); every number on the header line is an
 * integer, and `String(1.0)` is `'1'` where `repr(1.0)` is `'1.0'`.
 */
export function repoMapReply(result: repomap.RepoMap): string {
  const focus =
    result.focus.length > 0
      ? result.focus.join(', ')
      : '(none) — plain centrality over the whole tree';
  const head =
    `repo map: ${result.nodes} files scanned, ${result.definitions} definitions, ` +
    `${result.edges} edges.\n` +
    `focus: ${focus}\n` +
    `budget: ${result.budget} UTF-8 bytes; listing ${result.listingBytes} bytes; ` +
    `rendered ${result.filesRendered} files, ` +
    `${result.definitionsRendered} definitions.`;
  const body = result.text !== '' ? result.text : REPO_MAP_EMPTY;
  return `${head}\n\n${body}\n\n${REPO_MAP_TAIL}`;
}

/** `bool | None` after validation: the tagged bool, or `null` for the default. */
function asBool(value: PyValue | undefined): boolean | null {
  return value && value.t === 'bool' ? value.v : null;
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
 * The last `docread.extract` result this server produced, and what it was OF.
 *
 * DORMANT — its one user, `bantamkit_read`, left the roster (job50 I5, 2026-09-12); kept
 * with the handler so the roster line can come back without re-deriving the cache.
 *
 * The port of `mcpserver._DocumentCache` (register entry (i), `docs/roadmap-toolbox.md` row
 * 8). `bantamkit_read` re-parsed the whole document on EVERY call, so a caller paging a
 * 12,001-row sheet in 200-row pages parsed the workbook once per page — paging was O(N^2) in
 * the row window. MEASURED on this machine over a 1,553,944-byte 12,001-row xlsx driven
 * through a real client with `docread.extract` counted by a loader hook: 68 tool calls, **68**
 * parses, 4.128 s for the walk. After, over the same fixture and the same counter: **1**
 * parse, 0.104 s (0.103 / 0.108 on two repeats). The committed, rerunnable form of the same
 * count is `test/document-cache-and-bounds.test.mjs`, at 7 calls rather than 68.
 *
 * ONE entry, deliberately, and for the reference's reason. A single entry evicts whenever two
 * callers alternate between two documents, and that case then costs exactly one parse per
 * call — which is what the code this replaces cost for EVERY case, so the cache cannot make
 * any caller slower than it was (`test/document-cache-and-bounds.test.mjs` counts the
 * alternating walk and pins the number). What more entries would cost is resident memory: a
 * `Document` holds its whole rendering as strings, bounded per document by
 * `docread.TEXT_MAX_BYTES` and `docread.XLSX_MAX_TEXT_BYTES` (16 MiB each), and every extra
 * entry multiplies that ceiling by one.
 *
 * **The key is (realpath, size, mtimeNs), and it has one hole — stated, not implied.** A
 * rewrite that lands inside a single filesystem timestamp tick AND leaves the byte count
 * unchanged is indistinguishable from no rewrite at all, and would be served from the stale
 * parse. `mtimeNs` is nanosecond-SHAPED and not nanosecond-GRAINED: what it reports is
 * whatever the filesystem stored, which on HFS+ is one second and on APFS/ext4 is finer but
 * not unbounded. The alternative — hashing the bytes — would re-read the file this cache
 * exists to avoid re-reading, which is the whole cost on the large documents that motivate
 * it. So the hole stays, and the test that proves the key works changes the SIZE rather than
 * racing the clock, because a test that raced it would be measuring the filesystem.
 *
 * THE CACHED VALUE IS THE RESULT, NEVER A READER. `docread.extract` hands its own `ZipReader`
 * down to `extractXlsx`/`extractDocx` so an archive is read from disk once instead of twice,
 * and that reader's lifetime ends with the `extract` call that opened it. This sits one layer
 * above and holds a finished `Document`; no file handle outlives a call because of it.
 */
class DocumentCache {
  private key: string | null = null;
  private doc: docread.Document | null = null;

  /** The cached document for `key`, or `null` — a `null` key never matches. */
  get(key: string | null): docread.Document | null {
    if (key === null || key !== this.key) {
      return null;
    }
    return this.doc;
  }

  put(key: string | null, doc: docread.Document): void {
    if (key === null) {
      return;
    }
    this.key = key;
    this.doc = doc;
  }
}

/**
 * What identifies the bytes at `path` — or `null`, which means "do not cache".
 *
 * `statSync` FOLLOWS symlinks, which is the same file the reader is about to open, and
 * `{bigint: true}` is not decoration: `Stats.mtimeMs` is a float and has already lost the
 * sub-millisecond digits the reference's `st_mtime_ns` keeps, so a key built from it would
 * have a coarser hole than the one documented above. `size` and `mtimeNs` are read from the
 * bigint view for the same reason.
 *
 * Any error here returns `null` rather than refusing: this is a cache key, and the refusal a
 * caller reads must be the one `docread.extract` raises in the reader's own words, not one
 * this function invented from a different syscall's errno. That covers the one shape the
 * reference does not have — `os.path.realpath` is non-strict in CPython and answers even for
 * a path that does not resolve, while `realpathSync` throws. A path that stats but will not
 * resolve is therefore uncached here and cached there; nothing a client can observe moves,
 * because the reply is the reader's either way.
 */
function documentKey(path: string): string | null {
  try {
    const stat = statSync(path, { bigint: true });
    // NUL cannot occur in a path on either platform, so the join is unambiguous.
    return `${realpathSync(path)}\0${stat.size}\0${stat.mtimeNs}`;
  } catch {
    return null;
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
  documents: DocumentCache,
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
    case 'shiftwork_clock_in': {
      // J60: optional `unit_id`. Read the way `bantamkit_read` reads its optional `part` —
      // a value that is not a string is the DEFAULT, which is the cursor unit, so a host
      // sending `null` gets exactly the call it got before the field existed.
      const unitArg = args.get('unit_id');
      const unit = unitArg !== undefined && unitArg.t === 'str' ? unitArg.v : null;
      return {
        value: notedDict(recordResult(log, name, () => shiftwork.clockIn(asText(args.get('checkpoint')), unit))),
        wrapped: false,
      };
    }
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
    case 'memory_dream': {
      // Consolidate what the project layer and the machine-wide profile layer both hold
      // under one name (job45, roadmap row 5). `dryRun` DEFAULTS TO TRUE and the default
      // lives HERE rather than in the component, exactly as the reference's handler carries
      // it: a client that omits the argument sends nothing, `asBool` answers `null`, and
      // turning that into the SAFE answer is this handler's job. It is the only tool on
      // this surface that writes into the user's home directory, and the only one whose
      // effect is machine-wide — a fact archived out of the profile store stops answering
      // for every other project on this machine with no store of its own.
      //
      // THE RECORD IS A DECISION. `DreamOutcome.status` is read off `DreamResult.applied`,
      // `.overBudget` and `.changes` — never off the reply, whose prose is allowed to
      // improve without moving a single byte of the event log.
      const dryRun = asBool(args.get('dry_run'));
      const outcome = recordRaise(log, 'memory_dream', () =>
        memory.dreamOutcome(dryRun === null ? true : dryRun),
      );
      log.record('memory_dream', outcome.status, {
        absolutised: outcome.absolutised,
        consumed: outcome.consumed,
        dry_run: outcome.dryRun,
        merged: outcome.merged,
      });
      return { value: { t: 'str', v: noted(outcome.reply) }, wrapped: true };
    }
    case 'bantamkit_read': {
      // DORMANT — NOT ON THE ROSTER since job50 I5 (user ruling, 2026-09-12): `bantamkit_read`
      // left `MCP_TOOLS` because the transcript corpus showed it was never called. The reader
      // (`docread`, `contract`) and its tests are untouched; this arm, `DocumentCache` and
      // `OFFSET_MAXIMUM` are kept, unreachable from the wire (`SERVED` gates the call path),
      // so the roster line can return without a rewrite.
      //
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
        // (i): the parse is cached on (realpath, size, mtimeNs), so a paging walk over one
        // unchanged document parses it once. `documentKey` answering `null` means "do not
        // cache" and leaves this arm exactly as it was.
        const key = documentKey(path);
        let doc: docread.Document | null = documents.get(key);
        if (doc === null) {
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
          // A refusal is NOT cached: the entry holds a parse, and a path that has no parse
          // must reach the reader again next call so the reply stays the reader's own.
          documents.put(key, doc);
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
    case 'repo_map': {
      // DORMANT — NOT ON THE ROSTER since job50 I5 (user ruling, 2026-09-12): `repo_map` left
      // `MCP_TOOLS` because the transcript corpus showed it was never called. The engine
      // (`repomap.ts`) and its tests are untouched; this arm is kept, unreachable from the
      // wire (`SERVED` gates the call path), so the roster line can return without a rewrite.
      //
      // The ranked definition map on the MCP surface (job45 row 10): `repomap` measures,
      // this serves it. Byte for byte the reference's `repo_map` handler.
      //
      // THE THREE REFUSALS LIVE HERE AND NOT IN `repomap.ts`, and that is deliberate.
      // `repoMap()` over a root that does not exist answers an EMPTY map on both runtimes
      // — `os.walk` yields nothing for a missing directory and `walkSources`' `readdirSync`
      // catch does the same — which is the right answer for a library and the wrong one for
      // a tool: a caller who typed the path wrong would be told the tree holds no source.
      // So the argument checks are the SURFACE's, and the engine J45-9/J45-10 proved
      // byte-identical is not touched.
      //
      // THE `statSync` ARM IS `Path.exists()` / `Path.is_dir()`, NOT A SHORTCUT FOR THEM.
      // Both pathlib predicates SWALLOW the not-here errno family and re-raise anything
      // else, so `EXISTS_IGNORED` below is that family spelled out: a dangling symlink and
      // `a-file.py/sub` are "no such directory" on both runtimes, while a permission
      // failure flies to `recordRaise` rather than being dressed up as a missing tree.
      //
      // THE RECORD IS A DECISION AND HOLDS NO PATH. `root` is what the operator typed and
      // `focus` is the name of the file they are editing; neither is a decision this
      // handler made, so neither is written down. The counts are.
      const root = asText(args.get('root'));
      const focusArg = args.get('focus');
      const focus =
        focusArg !== undefined && focusArg.t === 'list'
          ? focusArg.v.map((item) => (item.t === 'str' ? item.v : ''))
          : [];
      const budgetArg = args.get('budget');
      const budget = budgetArg !== undefined && budgetArg.t === 'int' ? Number(budgetArg.v) : repomap.DEFAULT_BUDGET;
      return recordRaise(log, 'repo_map', () => {
        const refuse = (detail: string) => {
          log.record('repo_map', 'refused');
          return { value: { t: 'str' as const, v: noted(toolFailed('repo_map', detail)) }, wrapped: true };
        };
        if (root === '') return refuse('root must not be empty; name the directory to map');
        if (budget < 0) return refuse(`budget must not be negative; got ${budget}`);
        let stat = null;
        try {
          stat = statSync(root);
        } catch (e) {
          const code = (e as NodeJS.ErrnoException)?.code;
          if (!EXISTS_IGNORED.has(String(code))) throw asPyOSError(e, root);
        }
        if (stat === null) return refuse(`no such directory: ${root}`);
        if (!stat.isDirectory()) return refuse(`${root} is a file, not a directory to map`);
        const result = repomap.repoMap(root, { focus, budget });
        log.record('repo_map', 'mapped', {
          definitions: result.definitions,
          edges: result.edges,
          files_rendered: result.filesRendered,
          listing_bytes: result.listingBytes,
          nodes: result.nodes,
        });
        return { value: { t: 'str', v: noted(repoMapReply(result)) }, wrapped: true };
      });
    }
    case 'token_ledger': {
      // The transcript ledger on the MCP surface (job46, AS-1(c)): `tokenledger` measures,
      // this serves it. Byte for byte the reference's `token_ledger` handler.
      //
      // THE REPLY IS A JSON DOCUMENT AND NOT PROSE, the same shape and for the same reason as
      // `skill_audit` above: a caller comparing `totals` before and after a change, or
      // deciding whether `omissions` explain a total that looks too small, has to read
      // numbers rather than parse a sentence back out of English. `asJson` is the reply
      // verbatim and the only string this layer authors is the refusal.
      //
      // THE FOUR REFUSALS ARE ARGUMENT FAILURES — an empty `root`, a `root` that is missing,
      // a `root` that is a file, an empty `model` — so they go through `toolFailed`, and
      // unlike `repo_map` above they live in the MODULE rather than here: `read()` over a
      // missing root does not answer an empty ledger that a caller could mistake for a real
      // one, it refuses, so there is nothing for this layer to add.
      //
      // `PriceTableError` is caught BESIDE `TokenLedgerError` and is not the same kind of
      // thing: it is an operator configuration fault reached only when `model` names a price
      // table that will not load. It is still an argument failure from the CALLER's side —
      // it names the path they passed — so it is refused rather than crashing the request.
      //
      // THE RECORD IS A DECISION, NEVER A REPLY. `read` carries the four counts the host
      // cannot see and `refused` carries nothing at all, and no token count is recorded
      // either: the event log is a record of what this server DID, and the numbers are the
      // reply.
      const root = asText(args.get('root'));
      const modelArg = args.get('model');
      const model = modelArg !== undefined && modelArg.t === 'str' ? modelArg.v : null;
      const pricesArg = args.get('prices');
      const prices = pricesArg !== undefined && pricesArg.t === 'str' ? pricesArg.v : null;
      return recordRaise(log, 'token_ledger', () => {
        let result: tokenledger.Ledger;
        try {
          result = tokenledger.read(root, { model, prices });
        } catch (e) {
          // `except (tokenledger.TokenLedgerError, PriceTableError, OSError)`. Both classes
          // extend `BantamError` and both already carry the reference's own sentence.
          if (!(e instanceof tokenledger.TokenLedgerError) && !(e instanceof PriceTableError)) {
            throw e;
          }
          log.record('token_ledger', 'refused');
          return { value: { t: 'str', v: noted(toolFailed('token_ledger', e)) }, wrapped: true };
        }
        log.record('token_ledger', 'read', {
          transcripts: result.transcripts,
          lines: result.lines,
          requests: result.requests,
          sessions: result.sessions.length,
        });
        return { value: { t: 'str', v: noted(tokenledger.asJson(result)) }, wrapped: true };
      });
    }
    case 'work_plan':
      // `depends_on` turned into the batches that may run in parallel, over any task list
      // the caller hands over. No path, no file, no clock: `workplan.plan` is Layer 1 and
      // this is the seam that serves it.
      //
      // `result` is added HERE and not in `workplan.plan`, which answers the COMPUTATION
      // (`batches`, `sequence`, `width`) rather than a wire shape. The wire shape is the
      // tool asset's, so the verdict key goes on at the seam that serves it — the same
      // division `shiftwork.planBatches` uses one layer down. A refusal already carries its
      // own `result` and passes through untouched, because `recordResult` reads that key to
      // write the register's verdict to the log.
      //
      // THE MAPPING IS INSIDE THE CLOSURE, not above it, so that a node the core cannot
      // read raises where the reference raises: within `_record_result`, which records the
      // exception and re-raises it into the `Error executing tool work_plan:` envelope.
      return {
        value: notedDict(
          recordResult(log, name, () => {
            const answer = plan(planNodes(args.get('nodes')));
            if ('result' in answer) return { t: 'dict', v: new Map<string, PyValue>([['result', { t: 'str', v: 'error' }], ['reason', { t: 'str', v: answer.reason }]]) };
            return {
              t: 'dict',
              v: new Map<string, PyValue>([
                ['result', { t: 'str', v: 'plan' }],
                ['batches', { t: 'list', v: answer.batches.map((batch) => ({ t: 'list', v: batch.map((id) => ({ t: 'str', v: id })) })) }],
                ['sequence', { t: 'list', v: answer.sequence.map((id) => ({ t: 'str', v: id })) }],
                ['width', { t: 'int', v: BigInt(answer.width) }],
              ]),
            };
          }),
        ),
        wrapped: false,
      };
    case 'shiftwork_plan':
      // The read-only batch view of a checkpoint. Registered beside `shiftwork_status`
      // because it is the same kind of thing: a path in, an answer out, and not one byte
      // written — `test/shiftwork.test.mjs` hashes the checkpoint AND its `.log.jsonl`
      // before and after to hold that, rather than commenting it.
      return {
        value: notedDict(recordResult(log, name, () => shiftwork.planBatches(asText(args.get('checkpoint'))))),
        wrapped: false,
      };
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

  // Per SERVER, not per process: two servers in one interpreter (the tests build several)
  // must not answer each other's files, and the entry dies with the server rather than
  // outliving it in a module global. The reference does the same, inside `build_server`.
  const documents = new DocumentCache();

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
      // The roster decides what exists, not the argument table: `ARG_MODELS` still carries
      // the DORMANT `bantamkit_read` and `repo_map` models (job50 I5), and the reference
      // answers `Unknown tool:` for a handler it never registered.
      const model = SERVED.has(name) ? ARG_MODELS[name] : undefined;
      if (model === undefined) throw new BantamError(`Unknown tool: ${name}`);
      const bound = validateArguments(model, args);
      const { value, wrapped } = runTool(name, memory, bound, version, log, documents);
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
