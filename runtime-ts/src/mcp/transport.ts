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
 *    message, keyed by JSON-RPC id. A handler then re-reads its own arguments with
 *    `pyjson.parseJson`, which tags `5.0` as a float and keeps an integer past 2^53 exact.
 *
 * 2. THE OUTGOING NUMBER LITERALS AND THE ENVELOPE ORDER. `serializeMessage` is
 *    `JSON.stringify(message) + '\n'`, which un-does the work above on the way out: the same
 *    `5.0` in a `structuredContent` leaves as `5`. So a tool handler registers the EXACT text
 *    of its result here, keyed by request id, and `send` splices it in. Everything else still
 *    goes through `JSON.stringify`, which is byte-for-byte what pydantic-core writes for
 *    strings, bools, nulls and safe integers.
 *
 *    While the envelope is being built by hand anyway, its keys are written in the reference's
 *    order (`jsonrpc`, `id`, `result`) rather than the SDK's (`result`, `jsonrpc`, `id`). Key
 *    order is not observable to a conforming client, but it costs nothing here and it removes
 *    a difference from the list rather than adding a ruling to it.
 *
 * NOTHING IN THIS FILE WRITES TO STDOUT EXCEPT `send`. That is the invariant the whole
 * package is under, and it is checked by `test/server.test.mjs`, which asserts that every
 * line a real session produced parses as a frame and that stdout never ends mid-line.
 */
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js';
import type { JSONRPCMessage } from '@modelcontextprotocol/sdk/types.js';
import { JSONRPCMessageSchema } from '@modelcontextprotocol/sdk/types.js';

import { PY_LINESEP } from '../memory/pyfs.js';

type Readable = NodeJS.ReadableStream;
type Writable = NodeJS.WritableStream;

/** A JSON-RPC id is a string or a number; the map key is its JSON text, which is total. */
const idKey = (id: unknown): string => JSON.stringify(id ?? null);

export class RawStdioTransport implements Transport {
  onclose?: () => void;
  onerror?: (error: Error) => void;
  onmessage?: (message: JSONRPCMessage) => void;
  sessionId?: string;

  private buffer: Buffer = Buffer.alloc(0);
  private started = false;
  private readonly rawLines = new Map<string, string>();
  private readonly exactResults = new Map<string, string>();
  private readonly ondata = (chunk: Buffer): void => this.consume(chunk);
  private readonly onstreamerror = (error: Error): void => this.onerror?.(error);

  constructor(
    private readonly input: Readable = process.stdin,
    private readonly output: Writable = process.stdout,
  ) {}

  /** The verbatim request line that carried this id, or `undefined` if it is gone. */
  rawLineFor(id: unknown): string | undefined {
    return this.rawLines.get(idKey(id));
  }

  /** Register the exact JSON text to send as this request's `result`. */
  setExactResult(id: unknown, json: string): void {
    this.exactResults.set(idKey(id), json);
  }

  async start(): Promise<void> {
    if (this.started) throw new Error('RawStdioTransport already started');
    this.started = true;
    this.input.on('data', this.ondata);
    this.input.on('error', this.onstreamerror);
  }

  async close(): Promise<void> {
    this.input.off('data', this.ondata);
    this.input.off('error', this.onstreamerror);
    if (this.input.listenerCount('data') === 0) this.input.pause();
    this.buffer = Buffer.alloc(0);
    this.rawLines.clear();
    this.exactResults.clear();
    this.onclose?.();
  }

  send(message: JSONRPCMessage): Promise<void> {
    return new Promise((resolve) => {
      const text = this.frame(message);
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

  /**
   * One frame, in the reference's key order, with an exact `result` when one was registered.
   *
   * The raw line and the exact text are both dropped here rather than in the handler: the
   * handler cannot know whether the protocol will actually send its answer (a cancelled
   * request never reaches `send`), and a map that only ever grows is a leak in a process
   * that is meant to run for a session.
   */
  private frame(message: JSONRPCMessage): string {
    const framed = message as { id?: unknown; result?: unknown; error?: unknown };
    if (framed.id === undefined) return JSON.stringify(message);
    const key = idKey(framed.id);
    this.rawLines.delete(key);
    const id = JSON.stringify(framed.id);
    if ('result' in framed) {
      const exact = this.exactResults.get(key);
      this.exactResults.delete(key);
      return `{"jsonrpc":"2.0","id":${id},"result":${exact ?? JSON.stringify(framed.result)}}`;
    }
    this.exactResults.delete(key);
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
      let message: JSONRPCMessage;
      try {
        message = JSONRPCMessageSchema.parse(JSON.parse(line));
      } catch (error) {
        this.onerror?.(error as Error);
        continue;
      }
      const id = (message as { id?: unknown }).id;
      if (id !== undefined) this.rawLines.set(idKey(id), line);
      this.onmessage?.(message);
    }
  }
}
