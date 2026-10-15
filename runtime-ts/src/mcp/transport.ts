/**
 * The stdio transport, with the two things the SDK's own one cannot give this port.
 *
 * 1. THE RAW ARGUMENT BYTES. `StdioServerTransport` hands the server `JSON.parse(line)`, and
 *    N6 measured what that costs: a `5.0` that has been through `JSON.parse` is
 *    indistinguishable from `5`, so an accounting field arrives as an integer and the
 *    `.log.jsonl` line Python writes as `5.0` gets written as `5`. Nothing errors. The file
 *    just stops being diffable, silently, from the first successful clock-out.
 *
 *    The SDK exposes no hook for this — `ReadBuffer.readMessage` parses inside the buffer and
 *    the buffer is private — so the buffering is done here instead. It is thirty lines
 *    (`indexOf('\n')`, strip a trailing `\r`) and it keeps the LINE next to the parsed
 *    message, keyed PER MESSAGE (see 3). A handler then re-reads its own arguments with
 *    `pyjson.parseJson`, which tags `5.0` as a float and keeps an integer past 2^53 exact.
 *
 * 2. THE OUTGOING NUMBER LITERALS AND THE ENVELOPE ORDER. `serializeMessage` is
 *    `JSON.stringify(message) + '\n'`, which un-does the work above on the way out: the same
 *    `5.0` in a `structuredContent` leaves as `5`. So a tool handler registers the EXACT text
 *    of its result here, keyed per message, and `send` splices it in. Everything else still
 *    goes through `JSON.stringify`, which is byte-for-byte what pydantic-core writes for
 *    strings, bools, nulls and safe integers.
 *
 *    While the envelope is being built by hand anyway, its keys are written in the reference's
 *    order (`jsonrpc`, `id`, `result`) rather than the SDK's (`result`, `jsonrpc`, `id`). Key
 *    order is not observable to a conforming client, but it costs nothing here and it removes
 *    a difference from the list rather than adding a ruling to it.
 *
 * 3. ONE ENTRY PER MESSAGE, NOT PER ID (#146, #148). The side table used to be keyed by the
 *    client's id, so two requests in flight under ONE id (JSON-RPC forbids it; a client can
 *    still do it) shared one slot: the second line overwrote the first and both answers were
 *    computed from the second request's arguments. And the SDK's schema refuses an integer id
 *    past 2^53 (`JSON.parse` has already rounded it), so such a request got no answer at all.
 *    Both are fixed the same way: every request is handed to the SDK under a TOKEN of this
 *    file's own (`bantamkit-<n>`, unique per message), and the client's id is kept as the
 *    exact TEXT it arrived as, read losslessly with `pyjson.parseJson`; `send` writes that
 *    text back. The reference answers each request from its own arguments and echoes a big
 *    id exactly, so this is the port catching up, not a choice. A `notifications/cancelled`
 *    naming a client id is pointed at the newest token carrying it.
 *
 * 4. A FRAME THE SDK WOULD DROP IS ANSWERED (#148). A line that is not JSON is answered
 *    `-32700 Parse error`, and JSON that is not a JSON-RPC message (a batch array, a bare
 *    number, a message with no `jsonrpc`) `-32600 Invalid Request`, both with `id: null`
 *    as JSON-RPC 2.0 section 5.1 requires, and both in the bytes `mcpstdio.py` writes. Before,
 *    both went to `onerror` and the client waited forever. A blank line is still skipped.
 *
 * 5. A HOST THAT CLOSED ITS READ END ENDS THE SESSION QUIETLY (#181). `process.stdout` had no
 *    `error` listener, so an EPIPE mid-answer was an unhandled `error` event: exit 1 and a
 *    stack. It is now what stdin EOF already was, the host going away: the transport closes,
 *    stdin is released, and the process exits 0 with nothing on stderr. Any OTHER write error
 *    is rethrown and still crashes, because it is not that.
 *
 * NOTHING IN THIS FILE WRITES TO STDOUT EXCEPT `send`. That is the invariant the whole
 * package is under, and it is checked by `test/server.test.mjs`, which asserts that every
 * line a real session produced parses as a frame and that stdout never ends mid-line.
 */
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js';
import type { JSONRPCMessage } from '@modelcontextprotocol/sdk/types.js';
import { JSONRPCMessageSchema } from '@modelcontextprotocol/sdk/types.js';

import { PY_LINESEP } from '../memory/pyfs.js';
import { parseJson } from '../pyjson.js';

type Readable = NodeJS.ReadableStream;
type Writable = NodeJS.WritableStream;

/**
 * The two frames JSON-RPC 2.0 section 5.1 prescribes for a message no id can be read from,
 * byte for byte what `mcpstdio.py` writes (`JSONRPCError(id=None, ...)` dumped by the SDK).
 */
export const PARSE_ERROR_FRAME = '{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}';
export const INVALID_REQUEST_FRAME = '{"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"Invalid Request"}}';

/** The write errors that mean the reader of stdout is gone, on POSIX and on Windows (libuv EOF). */
const HOST_GONE = new Set(['EPIPE', 'ECONNRESET', 'EOF', 'ERR_STREAM_DESTROYED']);

/** One request in flight: the client's id as it arrived, its line, and its exact result. */
interface InFlight {
  readonly idText: string;
  readonly line: string;
  exact?: string;
}

/**
 * The client's id as the exact JSON text to echo, or `undefined` when it is not one a
 * JSON-RPC id may be. A string is re-serialised (`JSON.stringify` is pydantic-core's string
 * spelling); a number is read again LOSSLESSLY, because `JSON.parse` has already rounded an
 * integer past 2^53 and cannot tell `1.0` from `1`. The reference's `RequestId` is a STRICT
 * int or a str, so a float literal is no id at all there either.
 */
function clientIdText(line: string, id: unknown): string | undefined {
  if (typeof id === 'string') return JSON.stringify(id);
  if (typeof id !== 'number') return undefined;
  try {
    const frame = parseJson(line);
    const value = frame.t === 'dict' ? frame.v.get('id') : undefined;
    return value?.t === 'int' ? value.v.toString() : undefined;
  } catch {
    return Number.isSafeInteger(id) ? String(id) : undefined;
  }
}

/** The JSON text of an id named INSIDE a message (a cancellation's `requestId`). */
const namedIdText = (id: unknown): string | undefined =>
  typeof id === 'string' ? JSON.stringify(id) : Number.isSafeInteger(id) ? String(id) : undefined;

export class RawStdioTransport implements Transport {
  onclose?: () => void;
  onerror?: (error: Error) => void;
  onmessage?: (message: JSONRPCMessage) => void;
  sessionId?: string;

  private buffer: Buffer = Buffer.alloc(0);
  private started = false;
  private outputGone = false;
  private sequence = 0;
  /** Token (the id the SDK sees) -> the request it stands for. One entry per MESSAGE. */
  private readonly inFlight = new Map<string, InFlight>();
  /** Client id text -> the newest token carrying it, for `notifications/cancelled`. */
  private readonly newest = new Map<string, string>();
  private readonly ondata = (chunk: Buffer): void => this.consume(chunk);
  private readonly onstreamerror = (error: Error): void => this.onerror?.(error);
  private readonly onoutputerror = (error: NodeJS.ErrnoException): void => {
    if (!HOST_GONE.has(error.code ?? '')) throw error;
    if (this.outputGone) return;
    this.outputGone = true;
    // The host is gone, so nothing will ever read another answer: stop reading too, or a
    // stdin the host left open would keep the process alive with nowhere to write.
    (this.input as { destroy?: () => void }).destroy?.();
    void this.close();
  };

  constructor(
    private readonly input: Readable = process.stdin,
    private readonly output: Writable = process.stdout,
  ) {}

  /** The verbatim request line this message token stands for, or `undefined` if it is gone. */
  rawLineFor(id: unknown): string | undefined {
    return typeof id === 'string' ? this.inFlight.get(id)?.line : undefined;
  }

  /** Register the exact JSON text to send as this message's `result`. */
  setExactResult(id: unknown, json: string): void {
    const entry = typeof id === 'string' ? this.inFlight.get(id) : undefined;
    if (entry !== undefined) entry.exact = json;
  }

  async start(): Promise<void> {
    if (this.started) throw new Error('RawStdioTransport already started');
    this.started = true;
    this.input.on('data', this.ondata);
    this.input.on('error', this.onstreamerror);
    this.output.on('error', this.onoutputerror);
  }

  async close(): Promise<void> {
    this.input.off('data', this.ondata);
    this.input.off('error', this.onstreamerror);
    if (this.input.listenerCount('data') === 0) this.input.pause();
    this.buffer = Buffer.alloc(0);
    this.inFlight.clear();
    this.newest.clear();
    this.onclose?.();
  }

  send(message: JSONRPCMessage): Promise<void> {
    return this.write(this.frame(message));
  }

  private write(text: string): Promise<void> {
    return new Promise((resolve) => {
      if (this.outputGone) {
        resolve();
        return;
      }
      // `os.linesep`, because the reference's stdout is a TEXT stream. The Python SDK writes
      // its frames through `TextIOWrapper(sys.stdout.buffer)` with the default
      // `newline=None`, so on Windows every frame CPython emits ends `\r\n`. MEASURED, run
      // 32646521489: all nine `wire/*: raw frame bytes` cases differed by exactly one byte
      // per frame and by nothing else. A client is free to strip it; a port that claims to
      // be byte-compatible on the wire does not get to decide it is decoration.
      if (this.output.write(`${text}${PY_LINESEP}`)) resolve();
      else this.output.once('drain', () => resolve());
    });
  }

  /** Answer a line no id could be read from, in order with every other frame. */
  private refuse(frame: string): void {
    void this.write(frame);
  }

  /**
   * One frame, in the reference's key order, with an exact `result` when one was registered.
   *
   * The raw line and the exact text are both dropped here rather than in the handler: the
   * handler cannot know whether the protocol will actually send its answer (a cancelled
   * request never reaches `send`), and a map that only ever grows is a leak in a process
   * that is meant to run for a session.
   */
  private frame(message: JSONRPCMessage): string {
    const framed = message as { id?: unknown; result?: unknown; error?: unknown; method?: unknown };
    if (framed.id === undefined || 'method' in framed) return JSON.stringify(message);
    const entry = typeof framed.id === 'string' ? this.inFlight.get(framed.id) : undefined;
    if (entry !== undefined) {
      this.inFlight.delete(framed.id as string);
      if (this.newest.get(entry.idText) === framed.id) this.newest.delete(entry.idText);
    }
    const id = entry?.idText ?? JSON.stringify(framed.id);
    if ('result' in framed) {
      return `{"jsonrpc":"2.0","id":${id},"result":${entry?.exact ?? JSON.stringify(framed.result)}}`;
    }
    if ('error' in framed) return `{"jsonrpc":"2.0","id":${id},"error":${JSON.stringify(framed.error)}}`;
    return JSON.stringify(message);
  }

  private consume(chunk: Buffer): void {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    for (;;) {
      const at = this.buffer.indexOf(0x0a);
      if (at === -1) return;
      const line = this.buffer.toString('utf8', 0, at).replace(/\r$/, '');
      this.buffer = this.buffer.subarray(at + 1);
      if (line.trim() === '') continue;
      let parsed: unknown;
      try {
        parsed = JSON.parse(line);
      } catch {
        this.refuse(PARSE_ERROR_FRAME);
        continue;
      }
      // A LONE SURROGATE is text `JSON.parse` keeps and pydantic's parser refuses, so the
      // reference's SDK cannot read such a frame at all; `mcpstdio.py` answers it `-32600`
      // (the standard library CAN read it). The one exception is job65/#160's: a `tools/call`
      // carrying one in its arguments is refused BY NAME, which the server does here too.
      if (LONE_ESCAPE.test(line) && holdsLoneSurrogate(parsed) && !refusedByName(line, parsed)) {
        this.refuse(INVALID_REQUEST_FRAME);
        continue;
      }
      // The reference's adapter is pydantic, which IGNORES a member it has no field for and
      // takes `params: null` as no params; the TS SDK's schemas are strict and refuse both.
      // Measured on both SDKs (J66-3 note): normalised here, so a frame the reference answers
      // is not one the port calls an Invalid Request.
      if (isObject(parsed)) {
        for (const key of Object.keys(parsed)) if (!MESSAGE_KEYS.has(key)) delete parsed[key];
        if (parsed['params'] === null) delete parsed['params'];
      }
      // A REQUEST (an object with an id and a method) travels under a token of this file's
      // own; its client id is kept as text. Anything else goes to the SDK's schema unchanged.
      let token: string | undefined;
      let idText: string | undefined;
      if (isObject(parsed) && 'id' in parsed && 'method' in parsed) {
        idText = clientIdText(line, parsed['id']);
        if (idText === undefined) {
          // Not a str and not an int (`null`, `1.0`, `true`): the reference's `RequestId`
          // refuses it, and its union then reads the frame as a NOTIFICATION with the id
          // ignored, so nothing is answered. Measured; the port does the same.
          delete parsed['id'];
        } else {
          token = `bantamkit-${++this.sequence}`;
          parsed['id'] = token;
        }
      }
      let message: JSONRPCMessage;
      try {
        message = JSONRPCMessageSchema.parse(parsed);
      } catch {
        this.refuse(INVALID_REQUEST_FRAME);
        continue;
      }
      if (token !== undefined && idText !== undefined) {
        this.inFlight.set(token, { idText, line });
        this.newest.set(idText, token);
      } else {
        this.retarget(message);
      }
      this.onmessage?.(message);
    }
  }

  /** Point a `notifications/cancelled` at the token now standing for the id it names. */
  private retarget(message: JSONRPCMessage): void {
    const note = message as { method?: unknown; params?: { requestId?: unknown } };
    if (note.method !== 'notifications/cancelled' || note.params === undefined) return;
    const named = namedIdText(note.params.requestId);
    const token = named === undefined ? undefined : this.newest.get(named);
    if (token !== undefined) note.params.requestId = token;
  }
}

/** Only a line spelling a surrogate escape can hold a lone surrogate (`mcpstdio._ESCAPE`). */
const LONE_ESCAPE = /\\u[dD][89a-fA-F][0-9a-fA-F]{2}/;
const LONE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

/** Whether any string in the value, member names included, holds a lone surrogate. */
function holdsLoneSurrogate(value: unknown): boolean {
  if (typeof value === 'string') return LONE.test(value);
  if (Array.isArray(value)) return value.some(holdsLoneSurrogate);
  if (isObject(value)) return Object.entries(value).some(([key, item]) => LONE.test(key) || holdsLoneSurrogate(item));
  return false;
}

/**
 * `mcpstdio.refusal_for`'s test, less the roster: a `tools/call` with a str or int id whose
 * `arguments` object holds a lone surrogate goes on to the server, which refuses it by name
 * (`pyargs.loneSurrogateArgument`). The reference also requires the tool to be one it
 * serves; for an unserved name it answers `-32600` where the port answers `Unknown tool:`.
 */
function refusedByName(line: string, parsed: unknown): boolean {
  if (!isObject(parsed) || parsed['method'] !== 'tools/call' || !('id' in parsed)) return false;
  if (clientIdText(line, parsed['id']) === undefined) return false;
  const params = parsed['params'];
  return isObject(params) && typeof params['name'] === 'string' && isObject(params['arguments']) && holdsLoneSurrogate(params['arguments']);
}

/** The members a JSON-RPC 2.0 message may carry; any other is dropped as pydantic drops it. */
const MESSAGE_KEYS = new Set(['jsonrpc', 'id', 'method', 'params', 'result', 'error']);

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
