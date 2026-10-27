/**
 * An OpenAI-compatible chat client — the subset of `runtime-py/src/bantamkit/client.py` the
 * #206 drafter needs, on `node:http`/`node:https` only (no dependency; the npm install stays
 * pure Node).
 *
 * WHAT "THE SAME CLIENT" MEANS HERE. For the same base URL, model, key, seed, messages and
 * `response_format`, the request this sends is byte-for-byte the request `client.py` sends:
 * `POST <base without trailing slashes>/chat/completions`, `Authorization: Bearer <key>`,
 * `Content-Type: application/json`, and the body httpx's `json=` writes — CPython's
 * `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`, keys in `to_wire` order. The
 * retry loop is Python's: 429 and 5xx and transport failures are retried with a
 * `0.5 * 2**attempt` s wait and no wait after the last attempt; any other non-2xx is
 * `APIError` at once (redirects are not followed); one 400 on a request carrying
 * `response_format` drops the field, memoizes that, and resends without spending a retry.
 * Every sentence a caller can see is Python's, including the ones the reference does not
 * catch (`JSONDecodeError`, `TypeError`, `AttributeError`, `UnicodeEncodeError`), because a
 * drafter that logs the error logs the same line on either runtime. Compared live by
 * `tools/conformance/suites/llm-client.mjs`.
 *
 * WHAT IS NOT PORTED, BY DESIGN (`docs/porting.md`, divergence table, row `client`): tool
 * definitions and `tool_calls` parsing, the declared `context_window` and its `VOID` verdict,
 * and the `close()`/context-manager pair. #206 sends no tools and declares no window; with no
 * window Python's verdict is `UNREPORTED` or `UNCHECKED`, which this answers the same.
 *
 * ONE DETAIL THAT CANNOT BE THE SAME: the text after `chat failed after N attempts: ` when the
 * failure is the HTTP library's own (connection refused, the peer hanging up). httpx and
 * Node's `net` word those differently, and the errno inside httpx's sentence is the
 * platform's. That tail is a `ruling:` case; that BOTH refuse with `TransportError` is not.
 * A read timeout is worded `timed out` on both, so it is compared unruled.
 */
import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';

import { BantamError } from './errors.js';
import { pyRepr } from './pysem.js';
import { PyJSONDecodeError, type PyValue, dumpJson, fromJs, parseJson, reprValue, toJs } from './pyjson.js';

export { BantamError };

/** `client.BODY_SNIPPET`: how many code points of a response body a sentence quotes. */
export const BODY_SNIPPET = 200;

/** `client.TransportError`: an HTTP-level failure after bounded retries. */
export class TransportError extends BantamError {}

/** `client.APIError`: a non-retryable, non-success response. */
export class APIError extends BantamError {
  readonly statusCode: number;
  readonly body: string;

  constructor(statusCode: number, body: string) {
    const cut = cpSlice(body, BODY_SNIPPET);
    super(`API error ${statusCode}: ${pyRepr(cut)}`);
    this.statusCode = statusCode;
    this.body = cut;
  }
}

/** A Python exception the reference lets escape `chat`, named as Python names it. */
class PyEscape extends Error {
  constructor(name: string, message: string) {
    super(message);
    this.name = name;
  }
}

export const MEASURED = 'MEASURED';
export const UNREPORTED = 'UNREPORTED';
export const UNCHECKED = 'UNCHECKED';

export interface ChatMessage {
  role: string;
  content?: string | null;
}

export interface Usage {
  promptTokens: number;
  /** The endpoint's value verbatim (Python's `usage.get("completion_tokens", 0)`). */
  completionTokens: unknown;
  finishReason: unknown;
  promptTokensVerdict: string;
}

export interface Response {
  message: { role: 'assistant'; content: unknown };
  usage: Usage;
}

export interface ClientOptions {
  apiKey?: string;
  /** httpx's `timeout`, in milliseconds. */
  timeoutMs?: number;
  maxRetries?: number;
  seed?: number | null;
  /**
   * The backoff wait. A TEST SEAM, the twin of Python's tests monkeypatching `time.sleep`;
   * production leaves it unset.
   */
  sleep?: (ms: number) => Promise<void>;
}

/** Slice by code points, as Python's `str[:n]` does. */
function cpSlice(s: string, n: number): string {
  const cps = [...s];
  return cps.length <= n ? s : cps.slice(0, n).join('');
}

/** A network-level failure: the twin of `httpx.TransportError`. */
class NetFailure extends Error {}

const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

/** `str.encode("utf-8")`, refusing a lone surrogate with CPython's sentence. */
function encodeUtf8(text: string): Buffer {
  const m = LONE_SURROGATE.exec(text);
  if (m) {
    const position = [...text.slice(0, m.index)].length;
    throw new PyEscape(
      'UnicodeEncodeError',
      `'utf-8' codec can't encode character ${pyRepr(m[0])} in position ${position}: surrogates not allowed`,
    );
  }
  return Buffer.from(text, 'utf8');
}

interface Raw {
  status: number;
  body: Buffer;
}

/** Python's type name for a decoded JSON value, as an exception sentence spells it. */
function typeName(v: PyValue): string {
  return { null: 'NoneType', bool: 'bool', int: 'int', float: 'float', str: 'str', list: 'list', dict: 'dict' }[v.t];
}

class PyLookup extends Error {}

/** `container[key]` over a decoded document: KeyError/IndexError are `PyLookup`. */
function subscript(container: PyValue, key: string | number): PyValue {
  if (container.t === 'dict') {
    const k = typeof key === 'number' ? null : key;
    const v = k === null ? undefined : container.v.get(k);
    if (v === undefined) throw new PyLookup();
    return v;
  }
  if (container.t === 'list' || container.t === 'str') {
    if (typeof key === 'string') {
      throw new PyEscape(
        'TypeError',
        container.t === 'list'
          ? 'list indices must be integers or slices, not str'
          : "string indices must be integers, not 'str'",
      );
    }
    const items = container.t === 'list' ? container.v : [...container.v].map((c): PyValue => ({ t: 'str', v: c }));
    const v = items[key];
    if (v === undefined) throw new PyLookup();
    return v;
  }
  throw new PyEscape('TypeError', `'${typeName(container)}' object is not subscriptable`);
}

/** `obj.get(key)` / `obj.get(key, dflt)`: an `AttributeError` on anything but a dict. */
function get(obj: PyValue, key: string, dflt: PyValue = { t: 'null' }): PyValue {
  if (obj.t !== 'dict') throw new PyEscape('AttributeError', `'${typeName(obj)}' object has no attribute 'get'`);
  return obj.v.get(key) ?? dflt;
}

export class OpenAICompatible {
  readonly baseUrl: string;
  readonly model: string;
  readonly apiKey: string;
  readonly maxRetries: number;
  readonly timeoutMs: number;
  /** Sent only when set; writable per run, as Python's `seed` is. */
  seed: number | null;
  /** Python's `_response_format_unsupported`: flipped by the first 400 on a request with it. */
  responseFormatUnsupported = false;
  private readonly sleep: (ms: number) => Promise<void>;

  constructor(baseUrl: string, model: string, options: ClientOptions = {}) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.model = model;
    this.apiKey = options.apiKey ?? 'none';
    this.timeoutMs = options.timeoutMs ?? 60_000;
    this.maxRetries = options.maxRetries ?? 3;
    this.seed = options.seed ?? null;
    this.sleep = options.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
  }

  private post(payload: Map<string, PyValue>): Promise<Raw> {
    const body = encodeUtf8(dumpJson({ t: 'dict', v: payload }, { ensureAscii: false, separators: [',', ':'] }));
    const url = new URL(`${this.baseUrl}/chat/completions`);
    const send = url.protocol === 'https:' ? httpsRequest : httpRequest;
    return new Promise((resolve, reject) => {
      const req = send(
        url,
        {
          method: 'POST',
          agent: false,
          headers: {
            Authorization: `Bearer ${this.apiKey}`,
            'Content-Type': 'application/json',
            'Content-Length': String(body.length),
          },
        },
        (res) => {
          const chunks: Buffer[] = [];
          res.on('data', (c: Buffer) => chunks.push(c));
          res.on('end', () => resolve({ status: res.statusCode ?? 0, body: Buffer.concat(chunks) }));
          res.on('error', (e) => reject(new NetFailure(e.message)));
        },
      );
      req.setTimeout(this.timeoutMs, () => req.destroy(new NetFailure('timed out')));
      req.on('error', (e) => reject(e instanceof NetFailure ? e : new NetFailure(e.message)));
      req.end(body);
    });
  }

  async chat(messages: ChatMessage[], options: { responseFormat?: unknown } = {}): Promise<Response> {
    const payload = new Map<string, PyValue>([
      ['model', { t: 'str', v: this.model }],
      [
        'messages',
        {
          t: 'list',
          v: messages.map(
            (m): PyValue => ({
              t: 'dict',
              v: new Map<string, PyValue>([
                ['role', { t: 'str', v: m.role }],
                ['content', m.content == null ? { t: 'null' } : { t: 'str', v: m.content }],
              ]),
            }),
          ),
        },
      ],
    ]);
    if (this.seed !== null) payload.set('seed', fromJs(this.seed));
    if (options.responseFormat !== undefined && options.responseFormat !== null) {
      payload.set('response_format', fromJs(options.responseFormat));
    }
    let lastErr: Error | null = null;
    for (let attempt = 0; attempt < this.maxRetries; attempt += 1) {
      try {
        let r = await this.post(payload);
        if (r.status === 400 && payload.has('response_format')) {
          // The single 400 IS the capability detection (client.py): drop, remember, resend.
          this.responseFormatUnsupported = true;
          payload.delete('response_format');
          r = await this.post(payload);
        }
        const text = r.body.toString('utf8');
        if (r.status === 429 || r.status >= 500) {
          throw new TransportError(`server error ${r.status}: ${cpSlice(text, BODY_SNIPPET)}`);
        }
        if (r.status < 200 || r.status >= 300) throw new APIError(r.status, text);
        return parseResponse(r.body);
      } catch (e) {
        if (!(e instanceof NetFailure || e instanceof TransportError)) throw e;
        lastErr = e;
        if (attempt < this.maxRetries - 1) await this.sleep(500 * 2 ** attempt);
      }
    }
    throw new TransportError(`chat failed after ${this.maxRetries} attempts: ${lastErr === null ? 'None' : lastErr.message}`);
  }
}

/** `r.json()` then `_parse`, over CPython's decoder so `5.0` stays a float. */
function parseResponse(raw: Buffer): Response {
  // `json.loads(bytes)` detects a UTF-8 BOM and decodes with `utf-8-sig`.
  const hasBom = raw.length >= 3 && raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf;
  const text = (hasBom ? raw.subarray(3) : raw).toString('utf8');
  let data: PyValue;
  try {
    data = parseJson(text);
  } catch (e) {
    if (e instanceof PyJSONDecodeError) throw new PyEscape('JSONDecodeError', e.message);
    throw e;
  }
  let rawChoice: PyValue;
  let choice: PyValue;
  try {
    rawChoice = subscript(subscript(data, 'choices'), 0);
    choice = subscript(rawChoice, 'message');
  } catch (e) {
    if (e instanceof PyLookup) {
      throw new BantamError(`malformed chat response: ${cpSlice(reprValue(data), 200)}`);
    }
    throw e;
  }
  // Python reads `choice.get("tool_calls")` first; this port parses no tool calls (see the
  // header), but the `.get` on a non-dict raises before anything else either way.
  get(choice, 'tool_calls');
  const rawUsage = get(data, 'usage');
  const usage: PyValue = rawUsage.t === 'dict' ? rawUsage : { t: 'dict', v: new Map() };
  const reported = get(usage, 'prompt_tokens');
  const usable = reported.t === 'int';
  return {
    message: { role: 'assistant', content: toJs(get(choice, 'content')) },
    usage: {
      promptTokens: usable ? Number(reported.v) : 0,
      completionTokens: toJs(get(usage, 'completion_tokens', { t: 'int', v: 0n })),
      finishReason: toJs(get(rawChoice, 'finish_reason')),
      promptTokensVerdict: usable ? UNCHECKED : UNREPORTED,
    },
  };
}
