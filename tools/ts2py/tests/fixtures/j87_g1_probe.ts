// J87-3 (#316 G1): every construct G1 added, each with the case where Python and JS part.
const BIG = 2 ** 53;
const MAX = Number.MAX_SAFE_INTEGER;
function opt(o: any, k: string): unknown {
  return o?.[k] ?? 'nullish';
}
function optStatic(o: any): unknown {
  return o?.size ?? 'nullish';
}
function tryRead(o: any): string {
  try {
    return String(o.k);
  } catch {
    return 'caught';
  }
}
function tryThrow(n: number): string {
  try {
    if (n > 0) throw new TypeError('positive');
    return 'none';
  } catch (e) {
    if (n > 1) throw e;
    return 'swallowed';
  }
}
function rethrown(n: number): string {
  try {
    return tryThrow(n);
  } catch {
    return 'rethrown';
  }
}
function countDown(n: number): number[] {
  const out: number[] = [];
  for (let i = n - 1; i >= 0; i -= 1) {
    if (i === 2) break;
    out.push(i);
  }
  return out;
}
function splices(): unknown[] {
  const a = [1, 2, 3, 4, 5];
  const removed = a.splice(1, 2);
  const b = [1, 2, 3];
  const tail = b.splice(-1);
  const c = [1, 2, 3];
  const none = c.splice(5, 1);
  const d = [1, 2, 3];
  const all = d.splice(0);
  return [a, removed, b, tail, c, none, d, all];
}
function reduces(xs: number[]): unknown[] {
  let empty = 'none';
  try {
    [].reduce((a: number, b: number) => a + b);
  } catch {
    empty = 'TypeError';
  }
  return [xs.reduce((a, b) => a + b, 0), xs.reduce((a, b) => a * b), [5].reduce((a, b) => a - b), empty];
}
function finite(): unknown[] {
  return [Number.isFinite(1), Number.isFinite(1.5), Number.isFinite(Infinity), Number.isFinite(NaN), Number.isFinite('1' as any), Number.isFinite(true as any), Number.isFinite(null as any)];
}
function truncs(): unknown[] {
  return [Math.trunc(1.9), Math.trunc(-1.9), String(1 / Math.trunc(-0.5)), String(1 / Math.trunc(0.5)), String(Math.trunc(NaN)), String(Math.trunc(-Infinity)), Math.trunc('7.9' as any), Math.trunc(1e300) === 1e300];
}
function extremes(xs: number[]): unknown[] {
  const fits: number[] = [];
  fits.push(3, 1, 2);
  return [Math.min(...fits), Math.max(0, ...xs), Math.min(...xs, -1)];
}
function parses(): unknown[] {
  const out: unknown[] = [];
  for (const text of ['3000000.0', '9007199254740993', '1e400', '-0', '{"a":1,"b":2,"a":3}', '{"__proto__":{"x":1}}', '[1,"x",null,true]', ' {"k": [] } ']) {
    out.push(JSON.stringify(JSON.parse(text)));
  }
  for (const bad of ['NaN', 'Infinity', '{', '01', '﻿{}', '{"a":1,}', '"\u0001"']) {
    try {
      JSON.parse(bad);
      out.push('parsed');
    } catch {
      out.push('thrown');
    }
  }
  const neg = JSON.parse('-0') as number;
  out.push(String(1 / neg));
  return out;
}
export function probe(input: unknown): unknown[] {
  return [
    BIG, MAX, 2 ** 0, 10 ** 15,
    opt(null, 'a'), opt(undefined, 'a'), opt({ a: 1 }, 'a'), opt({}, 'a'), optStatic(new Map([[1, 2]])), optStatic(null),
    tryRead(null), tryRead({ k: 5 }), tryThrow(0), tryThrow(1), rethrown(2),
    countDown(6), countDown(2), splices(), reduces([1, 2, 3, 4]), finite(), truncs(), extremes([4, 9]), parses(),
  ];
}
