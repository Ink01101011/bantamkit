/**
 * J90-3 (#316 G4: storage/coldindex, retention, tiers): the constructs and Node builtins generating
 * them needed, run by Node (which strips the types) and by the generated Python over the same
 * scratch directory; `tests/g4b.rs` holds Node's printed answers. Compiled as a module of
 * `runtime-ts/src`, so `./storage/realpath.js` is the `nodeRealpath` adapter row.
 *
 * The directory holds `real/` (a directory), `live` -> `real`, `dangle` -> `missing-target`,
 * made by the caller before either runtime runs.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';

import { nodeRealpath } from './storage/realpath.js';

function code(f: () => unknown): unknown {
  try {
    return f();
  } catch (e) {
    const c = (e as NodeJS.ErrnoException).code;
    return ['threw', typeof c === 'string' ? c : null];
  }
}

function joined(part: unknown): unknown {
  try {
    return path.join('/a', part as string);
  } catch (e) {
    const err = e as NodeJS.ErrnoException;
    return [err instanceof TypeError, err.code ?? null, err.message];
  }
}

export function probe(dir: string): unknown[] {
  const out: unknown[] = [];
  const a = Buffer.from('héllo', 'utf8');
  out.push([a.equals(Buffer.from('héllo', 'utf8')), a.equals(Buffer.from('hello', 'utf8')), Buffer.from('', 'utf8').equals(Buffer.from('', 'utf8'))]);
  out.push([
    Buffer.from('héllo\u0000\u{1F600}', 'utf8').toString('base64'),
    Buffer.from('', 'utf8').toString('base64'),
    Buffer.from('ab', 'utf8').toString('base64'),
    Buffer.from('abc', 'utf8').toString('base64'),
  ]);
  const f = path.join(dir, 'f.txt');
  fs.writeFileSync(f, 'x', 'utf8');
  const l = fs.lstatSync(f, { bigint: true });
  const s = fs.statSync(f, { bigint: true });
  const ln = fs.lstatSync(path.join(dir, 'live'), { bigint: true });
  out.push([l.mtimeNs === s.mtimeNs, l.isFile(), typeof l.mtimeNs, typeof l.size, ln.isSymbolicLink(), ln.isDirectory()]);
  out.push(code(() => fs.unlinkSync(path.join(dir, 'missing'))));
  out.push([code(() => fs.unlinkSync(f)), fs.existsSync(f)]);
  fs.mkdirSync(path.join(dir, 'full', 'sub'), { recursive: true });
  out.push(code(() => fs.rmdirSync(path.join(dir, 'full'))));
  fs.writeFileSync(f, 'x', 'utf8');
  out.push(code(() => fs.rmdirSync(f)));
  out.push(code(() => fs.rmdirSync(path.join(dir, 'gone'))));
  out.push([code(() => fs.rmdirSync(path.join(dir, 'full', 'sub'))), fs.existsSync(path.join(dir, 'full', 'sub'))]);
  out.push([joined(undefined), joined(null), path.sep]);
  const base = nodeRealpath(dir);
  const rel = (p: string): string => path.relative(base, nodeRealpath(path.join(dir, p)));
  out.push([rel('real'), rel('live'), rel('dangle'), rel('dangle/sub'), rel('nothing/deeper'), rel('live/../f.txt'), rel('.')]);
  return out;
}

const PARTS = ['a', 'b', 'c', '..', '.', '', 'é', '\u{1F600}', 'aé', 'x y'];

/** A digest of `n` seeded `path.relative(from, to)` answers over absolute POSIX paths. */
export function relFuzz(n: number): number {
  let seed = 90003;
  const next = (): number => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return Math.floor(seed / 65536);
  };
  const one = (): string => {
    const len = next() % 6;
    let p = '';
    for (let i = 0; i < len; i += 1) p += `/${PARTS[next() % PARTS.length]!}`;
    return p === '' ? '/' : next() % 5 === 0 ? `${p}/` : p;
  };
  let h = 0;
  for (let i = 0; i < n; i += 1) {
    const from = one();
    const to = next() % 4 === 0 ? `${from}/${PARTS[next() % PARTS.length]!}` : one();
    const text = `${path.relative(from, to)}|`;
    for (let j = 0; j < text.length; j += 1) h = (h * 31 + text.charCodeAt(j)) % 1000000007;
  }
  return h;
}

/**
 * A digest of every code unit of a long string that is not ASCII (`n` characters past the 65,536
 * the runtime memoises by value: an astral character, then `é` and ASCII), read by `charCodeAt`
 * and by one-unit `slice`s, as the tokenizer reads an archived job's text.
 */
export function longScan(n: number): number {
  let s = '\u{1F600}';
  while (s.length < n) s += `é${'abcdefgh'.repeat(7)} `;
  let h = 0;
  for (let i = 0; i < s.length; i += 1) {
    h = (h * 31 + s.charCodeAt(i)) % 1000000007;
    if (i % 97 === 0) h = (h * 31 + s.slice(i, i + 1).charCodeAt(0)) % 1000000007;
  }
  return h;
}
