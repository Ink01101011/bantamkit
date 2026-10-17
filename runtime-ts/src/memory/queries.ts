/**
 * Likely-prompt queries (#207 amendment 3): the per-store sidecar, its limits, and the qdoc a
 * recall scores. Port of runtime-py/src/bantamkit/memory/queries.py; byte-identical, and the
 * `recall-queries` conformance suite pins both.
 *
 * `<home>/.bantamkit/queries/<sha16(realpath(store root))>.json`, the hot index's key
 * (`hotindex.sha16`), holding `{"v": 1, "facts": {<name>: {"queries": [...], "sha": <sha1 of the
 * fact file when written>}}}`. Derived from nothing and owned by nobody's facts: deleting it
 * loses recall quality only. `BANTAMKIT_INDEX_DIR` does not move it, because it is not an index.
 *
 * Read with `parseJson` (Python's `json.loads`: `1.0` and `true` are not the int 1) over a
 * FATAL UTF-8 decode (Python's strict decode). Written with Python's `dumps` options
 * (sorted keys by code point, `ensure_ascii=False`, compact) under the storage lock, through a
 * `<name>.<pid>.tmp` file and a rename. A text Python's UTF-8 encoder would refuse (a lone
 * surrogate) is refused here too rather than written as U+FFFD.
 */
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

import { dumpJson, parseJson, type PyValue } from '../pyjson.js';
import { sha16 } from '../storage/hotindex.js';
import { exclusive } from '../storage/lock.js';
import { stripNospace } from './retrieval.js';
import { loneSurrogate, MemoryValidationError } from './store.js';

export const SIDECAR_VERSION = 1;
export const MAX_QUERIES = 8;
export const MAX_QUERY_CHARS = 200;
export const LIST_LIMIT = 10;
export const BODY_EXCERPT = 600;
export const QUERIES_DIR = 'queries';
export const WRITE_FAILED = 'the sidecar could not be saved';

/** Any failure to write a sidecar: the reference's `OSError` / `UnicodeError` there. */
export class SidecarWriteError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SidecarWriteError';
  }
}

export function sidecarPath(home: string, root: string): string {
  return path.join(home, '.bantamkit', QUERIES_DIR, `${sha16(root)}.json`);
}

type Dict = Map<string, PyValue>;

function docOf(p: string): Dict | null {
  let doc: PyValue;
  try {
    const text = new TextDecoder('utf-8', { fatal: true }).decode(fs.readFileSync(p));
    doc = parseJson(text);
  } catch {
    return null;
  }
  if (doc.t !== 'dict') return null;
  const v = doc.v.get('v');
  if (v === undefined || v.t !== 'int') return null;
  if (v.v !== BigInt(SIDECAR_VERSION)) return null;
  const facts = doc.v.get('facts');
  if (facts === undefined || facts.t !== 'dict') return null;
  return doc.v;
}

/**
 * `{name: queries}` for every well-formed, non-empty entry; empty for a sidecar that is absent
 * or malformed. Never throws.
 */
export function readSidecar(p: string): Map<string, string[]> {
  const out = new Map<string, string[]>();
  const doc = docOf(p);
  if (doc === null) return out;
  const facts = doc.get('facts') as { t: 'dict'; v: Dict };
  for (const [name, entry] of facts.v) {
    if (entry.t !== 'dict') continue;
    const qs = entry.v.get('queries');
    if (qs !== undefined && qs.t === 'list' && qs.v.length > 0 && qs.v.every((x) => x.t === 'str')) {
      out.set(
        name,
        qs.v.map((x) => (x as { t: 'str'; v: string }).v),
      );
    }
  }
  return out;
}

/** Q2: the queries joined with "\n", every no-space code point blanked (before NFKC). */
export function qdoc(queries: readonly string[]): string {
  return stripNospace(queries.join('\n'));
}

const cps = (s: string): number => {
  let n = 0;
  for (const _ of s) n += 1;
  return n;
};

/** Q5's limits, in the spec's sentences (S1, S2, S3). Lengths are code points. */
export function checkQueries(queries: unknown): string[] {
  if (!Array.isArray(queries) || !queries.every((x) => typeof x === 'string')) {
    throw new MemoryValidationError('queries must be a list of strings');
  }
  if (queries.length > MAX_QUERIES) {
    throw new MemoryValidationError(`queries: at most ${MAX_QUERIES} per fact, got ${queries.length}`);
  }
  queries.forEach((x: string, i) => {
    const n = cps(x);
    if (n > MAX_QUERY_CHARS) {
      throw new MemoryValidationError(
        `queries: each at most ${MAX_QUERY_CHARS} characters; query ${i + 1} has ${n}`,
      );
    }
  });
  return queries as string[];
}

/** sha1 of the fact file's bytes; `''` when there is no file or it cannot be read. */
export function factSha(p: string | null | undefined): string {
  if (p === null || p === undefined) return '';
  try {
    return createHash('sha1').update(fs.readFileSync(p)).digest('hex');
  } catch {
    return '';
  }
}

/**
 * Merge `entries` into the sidecar under its lock; `null` removes a name. A malformed sidecar
 * is replaced. Throws `SidecarWriteError` when the sidecar cannot be written, and leaves no tmp
 * file behind.
 */
export function writeEntries(p: string, entries: ReadonlyMap<string, readonly [readonly string[], string] | null>): void {
  try {
    fs.mkdirSync(path.dirname(p), { recursive: true });
  } catch (e) {
    throw new SidecarWriteError(String((e as Error).message));
  }
  exclusive(p, () => {
    const doc: Dict = docOf(p) ?? new Map<string, PyValue>([
      ['v', { t: 'int', v: BigInt(SIDECAR_VERSION) }],
      ['facts', { t: 'dict', v: new Map() }],
    ]);
    const facts = (doc.get('facts') as { t: 'dict'; v: Dict }).v;
    for (const [name, entry] of entries) {
      if (entry === null) {
        facts.delete(name);
      } else {
        facts.set(name, {
          t: 'dict',
          v: new Map<string, PyValue>([
            ['queries', { t: 'list', v: entry[0].map((x): PyValue => ({ t: 'str', v: x })) }],
            ['sha', { t: 'str', v: entry[1] }],
          ]),
        });
      }
    }
    const tmp = path.join(path.dirname(p), `${path.basename(p)}.${process.pid}.tmp`);
    try {
      const text = dumpJson({ t: 'dict', v: doc }, { sortKeys: true, ensureAscii: false, separators: [',', ':'] });
      // Python's `write_text(encoding="utf-8")` raises on a lone surrogate; Buffer would write U+FFFD.
      const bad = loneSurrogate(text);
      if (bad !== null) throw new SidecarWriteError(`'utf-8' codec can't encode character ${bad}`);
      fs.writeFileSync(tmp, text, 'utf8');
      fs.renameSync(tmp, p);
    } catch (e) {
      try {
        fs.rmSync(tmp, { force: true });
      } catch {
        /* nothing more to remove */
      }
      if (e instanceof SidecarWriteError) throw e;
      throw new SidecarWriteError(String((e as Error).message));
    }
  });
}

/** S10, the `bantamkit_status` line. */
export function statusLine(n: number, m: number): string {
  return `queries: ${n} of ${m} facts`;
}
