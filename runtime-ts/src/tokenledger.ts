/**
 * What a session ACTUALLY cost, read off the host's own transcripts -- on the surface.
 *
 * The port of `runtime-py/src/bantamkit/tokenledger.py`, which carries the full argument for
 * why this exists, what it deliberately leaves in `tools/ledger/token-ledger.mjs`, and the
 * correction it makes over that script's per-FILE `requestId` dedupe. What follows is what is
 * specific to THIS side.
 *
 * THREE PLACES THIS RUNTIME WOULD DIVERGE ON ITS OWN, AND WHAT IS DONE ABOUT EACH
 * ------------------------------------------------------------------------------
 * 1. **`readFileSync(p, 'utf8')` does not fail on bytes that are not UTF-8.** It substitutes
 *    U+FFFD and hands back a string, while `Path.read_text(encoding='utf-8')` raises. Left
 *    alone, a transcript holding one stray `0xFF` is an `undecodable-file` omission on the
 *    reference and a bag of replacement characters here -- silently parsed, silently counted,
 *    silently different. So the file is read as BYTES and decoded through a `TextDecoder` in
 *    `fatal` mode, which is the only decoder in this runtime that refuses the way CPython's
 *    does. The fixture corpus carries such a file for exactly this reason.
 *
 * 2. **`.sort()` is UTF-16 code-unit order.** Sessions are tie-broken by id and directory
 *    entries are ordered by name, and both must be CODE-POINT order or a non-BMP name sorts
 *    on the far side of every character above U+FFFF. `cmpCodepoint` is the same comparator
 *    `pricing.ts` uses, for the same reason and out of the same module.
 *
 * 3. **A JSON number is a `number`.** `json.loads('7.0')` is a float on the reference and
 *    `7` is indistinguishable from `7.0` here, and `true` is an `int` there and a boolean
 *    here. `isCount` holds both holes shut, and it is `pricing.ts`'s rule restated -- this
 *    module counts tokens that module later prices, so a count either would accept and the
 *    other would not is a divergence waiting for a rate to be recorded.
 *
 * The 2**53 ceiling is checked as a SUBTRACTION before each addition (`count > MAX_SAFE_INT -
 * total`), never as a comparison afterwards: a `number` past 2**53 is already rounded, so the
 * check would be reading a value this side had got wrong.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { BantamError } from './errors.js';
import {
  MAX_SAFE_INT,
  TOKEN_CLASSES,
  loadPriceTable,
  priceTokens,
  type PriceResult,
  type TokenClass,
} from './pricing.js';
import { cmpCodepoint } from './pysem.js';

/**
 * Every omission subject, in the order they are reported. Fixed here rather than derived from
 * what a run happened to see, so two corpora produce comparable documents and a subject that
 * never fires is visibly absent rather than merely unmentioned.
 */
export const OMIT_UNDECODABLE = 'undecodable-file';
export const OMIT_UNPARSED = 'unparsed-line';
export const OMIT_NOT_OBJECT = 'not-an-object';
export const OMIT_NO_SESSION = 'no-session-id';
export const OMIT_NOT_ASSISTANT = 'not-an-assistant-record';
export const OMIT_NO_USAGE = 'no-usage';
export const OMIT_MALFORMED_USAGE = 'malformed-usage';
export const OMIT_NO_REQUEST_ID = 'no-request-id';
export const OMIT_DUPLICATE_REQUEST = 'duplicate-request';

export const OMISSION_ORDER = [
  OMIT_UNDECODABLE,
  OMIT_UNPARSED,
  OMIT_NOT_OBJECT,
  OMIT_NO_SESSION,
  OMIT_NOT_ASSISTANT,
  OMIT_NO_USAGE,
  OMIT_MALFORMED_USAGE,
  OMIT_NO_REQUEST_ID,
  OMIT_DUPLICATE_REQUEST,
] as const;

/**
 * The transcript extension the host writes. Anything else under `root` is not read and is not
 * counted -- it is not a transcript, so it is not an omission either.
 */
export const TRANSCRIPT_SUFFIX = '.jsonl';

/**
 * The scan could not be run at all: the message names what was wrong with the request.
 *
 * Reserved for a failure of the SCAN, exactly as `SkillAuditError` is. A file that will not
 * decode, a line that will not parse and a record with no usage are omissions and are counted.
 */
export class TokenLedgerError extends BantamError {}

export interface Omission {
  subject: string;
  count: number;
  what: string;
}

export interface SessionRow {
  session: string;
  cwd: string;
  first: string;
  last: string;
  requests: number;
  sidechain_requests: number;
  input_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  output_tokens: number;
}

export interface Ledger {
  root: string;
  transcripts: number;
  lines: number;
  requests: number;
  totals: Record<TokenClass, number>;
  sessions: SessionRow[];
  omissions: Omission[];
  cost?: PriceResult;
}

/**
 * A non-negative integer below `2**53` both runtimes hold exactly, however JSON spelled it.
 * `pricing.ts`'s `isCount`, restated because it is this module's rule too.
 */
function isCount(value: unknown): boolean {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= MAX_SAFE_INT;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * One transcript line, decoded the way `json.loads(..., parse_constant=raise)` decodes it.
 *
 * `JSON.parse` is already the strict side -- it rejects the bare `NaN` / `Infinity` /
 * `-Infinity` tokens CPython accepts -- so this is a plain parse, and the reference is what
 * had to move. It exists as a named arm anyway, because a rule living in one of two runtimes
 * is a rule the conformance harness cannot reach.
 */
function decodeLine(text: string): unknown {
  return JSON.parse(text) as unknown;
}

/**
 * Every `*.jsonl` under `base`, in one deterministic order.
 *
 * Sorted by entry NAME in code-point order at every level, directories and files in the same
 * listing, so the sequence is a property of the tree and not of the filesystem. It has to be:
 * the walk order decides which copy of a duplicated `requestId` is the one that counts.
 */
export function walk(base: string): Array<[string, string]> {
  const found: Array<[string, string]> = [];
  const visit = (directory: string, prefix: string): void => {
    let names: string[];
    try {
      names = readdirSync(directory).sort(cmpCodepoint);
    } catch {
      return;
    }
    for (const name of names) {
      const child = join(directory, name);
      const rel = `${prefix}${name}`;
      let isDirectory = false;
      try {
        isDirectory = statSync(child).isDirectory();
      } catch {
        // A dangling symlink is not a directory. `Path.is_dir()` answers False for one too,
        // so it falls through to the suffix test and is read (and fails to be read) here
        // exactly as it is there.
        isDirectory = false;
      }
      if (isDirectory) visit(child, `${rel}/`);
      else if (name.endsWith(TRANSCRIPT_SUFFIX)) found.push([child, rel]);
    }
  };
  visit(base, '');
  return found;
}

/**
 * The strict UTF-8 decode. `readFileSync(p, 'utf8')` substitutes U+FFFD where the reference
 * raises, which would make an unreadable transcript a counted one on this side alone.
 */
function readUtf8Strict(path: string): string {
  const decoder = new TextDecoder('utf-8', { fatal: true });
  return decoder.decode(readFileSync(path));
}

function usageOf(record: Record<string, unknown>): unknown {
  const message = record.message;
  if (!isPlainObject(message)) return undefined;
  return message.usage;
}

/** `<relpath>:<line>` for the first site, plus `and N more` when there are more. */
function whatOf(count: number, site: string): string {
  if (count <= 1) return site;
  return `${site} and ${count - 1} more`;
}

/**
 * Walk `root` and answer the ledger.
 *
 * An empty `root` is refused rather than resolved -- `statSync('')` throws here and
 * `Path('')` is `Path('.')` on the reference, so the two would answer a refusal and a
 * CWD-relative ledger for one input. `model` omitted is not `model` empty: an absent model
 * asks for no cost and gets no `cost` key, and an empty string is refused rather than looked
 * up and reported as "no rate recorded for model ''".
 */
export function read(
  root: string,
  options: { model?: string | null; prices?: string | null } = {},
): Ledger {
  const model = options.model ?? null;
  const prices = options.prices ?? null;
  if (root === '') {
    throw new TokenLedgerError('root must not be empty; name the directory of transcripts to read');
  }
  if (model !== null && model === '') {
    throw new TokenLedgerError('model must not be empty; name the model to price, or omit it');
  }
  if (!existsSync(root)) throw new TokenLedgerError(`no such directory: ${root}`);
  if (!statSync(root).isDirectory()) {
    throw new TokenLedgerError(`${root} is a file, not a directory of transcripts`);
  }

  const files = walk(root);
  const sessions = new Map<string, SessionRow>();
  const counts = new Map<string, number>();
  const sites = new Map<string, string>();
  // Spelled out rather than built in a loop: `noUncheckedIndexedAccess` makes an index into a
  // `Record<string, number>` a `number | undefined`, and the ceiling arithmetic below must not
  // be reading a `?? 0` that would silently restart a total.
  const totals: Record<TokenClass, number> = {
    input_tokens: 0,
    cache_creation_input_tokens: 0,
    cache_read_input_tokens: 0,
    output_tokens: 0,
  };
  const seenRequests = new Set<string>();
  let lines = 0;

  const omit = (subject: string, site: string): void => {
    const seen = counts.get(subject) ?? 0;
    if (seen === 0) sites.set(subject, site);
    counts.set(subject, seen + 1);
  };

  for (const [path, relpath] of files) {
    let text: string;
    try {
      text = readUtf8Strict(path);
    } catch {
      // The file exists and is a transcript by name; it is one line of nothing anyone can
      // read. Counted as ONE omission and not as N, because N is not knowable.
      lines += 1;
      omit(OMIT_UNDECODABLE, `${relpath}:1`);
      continue;
    }
    const rows = text.split('\n');
    for (const [index, line] of rows.entries()) {
      // Not a record. The last one is the file's trailing newline; counting it would put a
      // permanent off-by-one in `lines == requests + sum(counts)`.
      if (line === '') continue;
      lines += 1;
      const site = `${relpath}:${index + 1}`;
      let record: unknown;
      try {
        record = decodeLine(line);
      } catch {
        omit(OMIT_UNPARSED, site);
        continue;
      }
      if (!isPlainObject(record)) {
        omit(OMIT_NOT_OBJECT, site);
        continue;
      }
      const sessionId = record.sessionId;
      if (typeof sessionId !== 'string' || sessionId === '') {
        omit(OMIT_NO_SESSION, site);
        continue;
      }
      if (record.type !== 'assistant') {
        omit(OMIT_NOT_ASSISTANT, site);
        continue;
      }
      const usage = usageOf(record);
      if (usage === undefined || usage === null) {
        omit(OMIT_NO_USAGE, site);
        continue;
      }
      if (!isPlainObject(usage) || !TOKEN_CLASSES.every((cls) => isCount(usage[cls]))) {
        // A real `usage` also carries `service_tier`, `iterations` and friends. Those are the
        // host's and are ignored; what is required is that all FOUR classes this ledger
        // reports are present and are counts. A class silently defaulted to zero is a token
        // silently invented.
        omit(OMIT_MALFORMED_USAGE, site);
        continue;
      }
      const requestId = record.requestId;
      if (typeof requestId !== 'string' || requestId === '') {
        omit(OMIT_NO_REQUEST_ID, site);
        continue;
      }
      if (seenRequests.has(requestId)) {
        omit(OMIT_DUPLICATE_REQUEST, site);
        continue;
      }
      seenRequests.add(requestId);

      let row = sessions.get(sessionId);
      if (row === undefined) {
        row = {
          session: sessionId,
          cwd: '',
          first: '',
          last: '',
          requests: 0,
          sidechain_requests: 0,
          input_tokens: 0,
          cache_creation_input_tokens: 0,
          cache_read_input_tokens: 0,
          output_tokens: 0,
        };
        sessions.set(sessionId, row);
      }
      const cwd = record.cwd;
      if (row.cwd === '' && typeof cwd === 'string') row.cwd = cwd;
      const stamp = record.timestamp;
      if (typeof stamp === 'string' && stamp !== '') {
        if (row.first === '' || cmpCodepoint(stamp, row.first) < 0) row.first = stamp;
        if (cmpCodepoint(stamp, row.last) > 0) row.last = stamp;
      }
      row.requests += 1;
      if (record.isSidechain === true) row.sidechain_requests += 1;
      for (const cls of TOKEN_CLASSES) {
        const count = usage[cls] as number;
        if (count > MAX_SAFE_INT - totals[cls]) {
          throw new TokenLedgerError(
            `${cls} total exceeds 2**53-1, which is the largest integer both runtimes ` +
              'represent exactly',
          );
        }
        row[cls] += count;
        totals[cls] += count;
      }
    }
  }

  const ordered = [...sessions.values()].sort(
    (a, b) => cmpCodepoint(a.first, b.first) || cmpCodepoint(a.session, b.session),
  );
  const omissions: Omission[] = [];
  for (const subject of OMISSION_ORDER) {
    const count = counts.get(subject) ?? 0;
    if (count > 0) omissions.push({ subject, count, what: whatOf(count, sites.get(subject) ?? '') });
  }

  const ledger: Ledger = {
    root,
    transcripts: files.length,
    lines,
    requests: seenRequests.size,
    totals,
    sessions: ordered,
    omissions,
  };
  if (model !== null) {
    ledger.cost = priceTokens(loadPriceTable(prices ?? undefined), model, { ...totals });
  }
  return ledger;
}

/**
 * The document, in the reference's key order.
 *
 * Built explicitly rather than by serialising `Ledger`, because the interface's declaration
 * order is a type and not a runtime fact, and `sessions[]` interleaves the four token classes
 * after `sidechain_requests` -- an order a structural copy would not reproduce.
 */
export function asDict(ledger: Ledger): Record<string, unknown> {
  const totals: Record<string, number> = {};
  for (const cls of TOKEN_CLASSES) totals[cls] = ledger.totals[cls];
  const doc: Record<string, unknown> = {
    root: ledger.root,
    transcripts: ledger.transcripts,
    lines: ledger.lines,
    requests: ledger.requests,
    totals,
    sessions: ledger.sessions.map((s) => {
      const row: Record<string, unknown> = {
        session: s.session,
        cwd: s.cwd,
        first: s.first,
        last: s.last,
        requests: s.requests,
        sidechain_requests: s.sidechain_requests,
      };
      for (const cls of TOKEN_CLASSES) row[cls] = s[cls];
      return row;
    }),
    omissions: ledger.omissions.map((o) => ({
      subject: o.subject,
      count: o.count,
      what: o.what,
    })),
  };
  if (ledger.cost !== undefined) doc.cost = ledger.cost;
  return doc;
}

/**
 * Two-space indent and no ASCII escaping, so this and `Ledger.as_json()` on the reference are
 * the same bytes and a conformance case can compare them.
 */
export function asJson(ledger: Ledger): string {
  return JSON.stringify(asDict(ledger), null, 2);
}
