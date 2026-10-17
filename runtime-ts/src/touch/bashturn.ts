/**
 * Writes made by Bash, once per turn (#200, E5): `git status` at UserPromptSubmit against `git
 * status` at Stop. A path already dirty before the turn is caught by its stat moving. Port of
 * `runtime-py/src/bantamkit/touch/bashturn.py`; `touch-turn` compares the two.
 *
 * `snapshot` reads `git status --porcelain=v1 -z -uall` into `path -> [xy, mtime_ns, size]`
 * (`mtime_ns` the exact bigint as a decimal string, Python's `st_mtime_ns`; `"-"` and `-1`
 * when the path cannot be statted). A rename or copy entry keys on the destination. `changed`
 * sorts in code-point order, never UTF-16 order. The turn file's keys are written sorted, so
 * its bytes are the reference's `sort_keys=True` output. Maps, so a path named `__proto__` is
 * a key like any other.
 */
import fs from 'node:fs';
import path from 'node:path';

import { git, type Repo } from './repo.js';

export type Entry = [string, string, number];
export type Snapshot = Map<string, Entry>;

const UNSAFE = /[^A-Za-z0-9_-]/g; // the ledger file-name rule, `ledgerPath` in hookadapter

export function snapshot(repo: Repo): Snapshot | null {
  const out = git(repo, ['status', '--porcelain=v1', '-z', '-uall']);
  if (out === null) return null;
  const fields = out.split('\0');
  const snap: Snapshot = new Map();
  let i = 0;
  while (i < fields.length) {
    const entry = fields[i]!;
    i += 1;
    if ([...entry].length < 4) continue;
    const xy = entry.slice(0, 2);
    const p = entry.slice(3);
    if (xy[0] === 'R' || xy[0] === 'C') i += 1; // the source path follows; key on the destination
    try {
      const st = fs.statSync(path.join(repo.top, ...p.split('/')), { bigint: true });
      snap.set(p, [xy, st.mtimeNs.toString(), Number(st.size)]);
    } catch {
      snap.set(p, [xy, '-', -1]);
    }
  }
  return snap;
}

function codePointCmp(a: string, b: string): number {
  const x = [...a];
  const y = [...b];
  const n = Math.min(x.length, y.length);
  for (let k = 0; k < n; k++) {
    const d = x[k]!.codePointAt(0)! - y[k]!.codePointAt(0)!;
    if (d !== 0) return d;
  }
  return x.length - y.length;
}

/** Python's `!=` over the entries: a loaded turn holds whatever JSON the file held. */
function same(a: unknown, b: unknown): boolean {
  if (a === undefined || b === undefined) return a === b;
  return JSON.stringify(a) === JSON.stringify(b);
}

export function changed(before: Snapshot, after: Snapshot): string[] {
  const all = new Set([...before.keys(), ...after.keys()]);
  return [...all].filter((p) => !same(before.get(p), after.get(p))).sort(codePointCmp);
}

function turnPath(stateDir: string, session: string): string {
  return path.join(stateDir, `ledger-${(session || 'nosession').replace(UNSAFE, '_')}.turn.json`);
}

/** `{"seq", "status"}`, keys sorted, temp then rename. Throws when unwritable. */
export function saveTurn(stateDir: string, session: string, snap: Snapshot, seq: number): void {
  const p = turnPath(stateDir, session);
  fs.mkdirSync(stateDir, { recursive: true });
  const status: Record<string, Entry> = Object.create(null) as Record<string, Entry>;
  for (const k of [...snap.keys()].sort(codePointCmp)) status[k] = snap.get(k)!;
  const tmp = `${p}.${process.pid}.${Math.random().toString(16).slice(2, 10)}.tmp`;
  try {
    fs.writeFileSync(tmp, JSON.stringify({ seq, status }));
    fs.renameSync(tmp, p);
  } catch (e) {
    try {
      fs.unlinkSync(tmp);
    } catch {
      /* never written */
    }
    throw e;
  }
}

export function loadTurn(stateDir: string, session: string): [number, Snapshot] | null {
  let d: unknown;
  try {
    d = JSON.parse(fs.readFileSync(turnPath(stateDir, session)).toString('utf8'));
  } catch {
    return null;
  }
  if (typeof d !== 'object' || d === null || Array.isArray(d)) return null;
  const seq = (d as Record<string, unknown>)['seq'];
  const status = (d as Record<string, unknown>)['status'];
  if (typeof seq !== 'number' || !Number.isInteger(seq)) return null;
  if (typeof status !== 'object' || status === null || Array.isArray(status)) return null;
  return [seq, new Map(Object.entries(status as Record<string, Entry>))];
}
