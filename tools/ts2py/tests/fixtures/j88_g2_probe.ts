// J88-2 (#316 G2): one function per construct the event log, the token ledger and the log segment
// needed, each answering a JSON-able value. tests/g2.rs compiles this with ts2py, runs it under
// Python and compares `JSON.stringify(probe())` with what `node` printed for this same file.
// Non-ASCII text is built with String.fromCodePoint so the file itself stays ASCII.

export const SHIFTED = 1 << 20;



function replacer(_key: string, value: unknown): unknown {
  if (typeof value === 'number' && !Number.isFinite(value)) throw new RangeError(`${value} is not JSON`);
  return value;
}

function stringify(): unknown[] {
  const doc = JSON.parse('{"b":1,"10":"ten","2":[1,{"x":null},[]],"a":{},"s":"\\u00e9\\u2028"}') as Record<string, unknown>;
  const out: unknown[] = [];
  out.push(JSON.stringify(doc, null, 2));
  out.push(JSON.stringify(doc, null, '--'));
  out.push(JSON.stringify([], null, 4));
  out.push(JSON.stringify({ k: [] }, null, 1));
  out.push(JSON.stringify(doc, replacer));
  try {
    JSON.stringify({ n: [1, NaN] }, replacer);
    out.push('no throw');
  } catch (e) {
    out.push(e instanceof RangeError ? 'RangeError' : 'other');
  }
  out.push(JSON.stringify({ u: undefined, v: 1 }, null, 2));
  out.push(JSON.stringify({ s: String.fromCodePoint(0x78, 0xd800, 0x79) }, null, 2));
  return out;
}

function deepParse(): unknown[] {
  const deep = `${'['.repeat(50000)}7${']'.repeat(50000)}`;
  let v: unknown = JSON.parse(deep);
  let depth = 0;
  while (Array.isArray(v)) {
    v = v[0];
    depth += 1;
  }
  let bad = 'parsed';
  try {
    JSON.parse(`${'['.repeat(50000)}${']'.repeat(49999)}`);
  } catch {
    bad = 'SyntaxError';
  }
  const deepObject = JSON.parse(`${'{"a":'.repeat(30000)}1${'}'.repeat(30000)}`) as Record<string, unknown>;
  return [depth, v, bad, typeof deepObject.a];
}

function dates(): unknown[] {
  const out: unknown[] = [];
  for (const ms of [0, -1, -1.5, 1.9, 253402300800000, -62135596800001, 8.64e15, -8.64e15, -62198755200000]) {
    out.push(new Date(ms).toISOString());
  }
  for (const ms of [8.64e15 + 1, NaN, Infinity]) {
    try {
      out.push(new Date(ms).toISOString());
    } catch (e) {
      out.push(e instanceof RangeError ? 'RangeError' : 'other');
    }
  }
  return out;
}

function strings(): unknown[] {
  return [
    `${String.fromCodePoint(0xfeff, 0xa0)} x ${String.fromCodePoint(0x3000)}\n`.trim(),
    `${String.fromCodePoint(0x1c)}x${String.fromCodePoint(0x85)}`.trim(),
    'a.jsonl'.endsWith('.jsonl'),
    'a.JSONL'.endsWith('.jsonl'),
    String.fromCodePoint(0x1f600).endsWith(String.fromCodePoint(0xde00)),
    String.fromCodePoint(0xc0, 0xc9, 0xce, 0x20, 0x130, 0x20, 0x1e9e).toLowerCase(),
    'ON'.toLowerCase(),
  ];
}

function buffers(): unknown[] {
  const a = Buffer.from(`h${String.fromCodePoint(0xe9, 0x1f600, 0xd800)}`, 'utf8');
  const b = Buffer.alloc(4);
  const view = a.subarray(1, 3);
  const joined = Buffer.concat([a, view, b.subarray(3)]);
  return [
    a.length,
    a.toString('hex'),
    joined.toString('hex'),
    view.length,
    view[1],
    a[0],
    a[99] === undefined,
    a.toString('utf8'),
    Buffer.from(String.fromCodePoint(0xff, 0xfe)).toString('utf8'),
  ];
}

function decoding(): unknown[] {
  const strict = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
  const loose = new TextDecoder('utf-8');
  const bom = Buffer.from(`${String.fromCodePoint(0xfeff)}a`, 'utf8');
  const out: unknown[] = [strict.decode(bom).length, loose.decode(bom).length];
  for (const text of ['ok', `${String.fromCodePoint(0x1f600)}`]) out.push(strict.decode(Buffer.from(text, 'utf8')));
  // A lone surrogate is written EF BF BD, which decodes back to U+FFFD under fatal.
  out.push(strict.decode(Buffer.from(String.fromCodePoint(0xd800), 'utf8')) === String.fromCodePoint(0xfffd));
  return out;
}

function trail(log: string[], step: string): string[] {
  log.push(step);
  return log;
}

function finallies(): unknown[] {
  const log: string[] = [];
  const f = (): string => {
    try {
      trail(log, 'body');
      return 'returned';
    } finally {
      trail(log, 'finally');
    }
  };
  const g = (): string => {
    try {
      try {
        throw new Error('x');
      } finally {
        trail(log, 'inner finally');
      }
    } catch {
      trail(log, 'caught');
    } finally {
      trail(log, 'outer finally');
    }
    return 'done';
  };
  return [f(), g(), log];
}

function closures(): unknown[] {
  let count = 0;
  const seen: number[] = [];
  const apply = (fn: (n: number) => void, n: number): void => {
    fn(n);
  };
  apply((n) => {
    count = count + n;
    seen.push(count);
  }, 5);
  apply((n) => {
    count = count * n;
  }, 3);
  const pick = (fn: (a?: number, b?: number) => unknown): unknown => fn();
  const row: Record<string, number> = { requests: 1 };
  const key = 'requests';
  row.requests += 2;
  row[key] -= 1;
  const doubled = [1, 2, 3].map((n) => {
    const twice = n * 2;
    return twice + 1;
  });
  return [count, seen, pick((a, b) => [a === undefined, b === undefined]), row, doubled, ['x', 'yy'].map(trimmed)];
}

function trimmed(text: string): number {
  return text.length;
}

class Clocked {
  readonly clock: () => number;
  constructor(clock: () => number) {
    this.clock = clock;
  }
  now(): number {
    return this.clock() + 1;
  }
  static make(): Clocked {
    return new Clocked(() => 41);
  }
}

class Named extends Error {}

function reflection(): unknown[] {
  const err = Object.assign(new Error('lost'), { code: 'EIO' });
  const names = [{}, [], new Named('n'), new TypeError('t'), err].map((v) => (v as { constructor: { name: string } }).constructor.name);
  let code: unknown = 'none';
  try {
    throw err;
  } catch (e) {
    code = (e as { code?: unknown }).code;
  }
  const m = new Map<string, number>([
    ['a', 1],
    ['b', 2],
  ]);
  return [Clocked.make().now(), names, code, typeof err, [...m.values()]];
}

export function probe(): unknown[] {
  return [SHIFTED, stringify(), deepParse(), dates(), strings(), buffers(), decoding(), finallies(), closures(), reflection()];
}
