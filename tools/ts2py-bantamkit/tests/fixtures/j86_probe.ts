// J86 semantics probe (tests/codec.rs). Every value `probe()` returns, and each error the three
// throwing functions raise, is pinned in that test as Node printed it:
//   node -e "import('./tests/fixtures/j86_probe.ts').then(m => console.log(m.probe()))"
// (Node 26 strips the types itself). The Python side is this file compiled by ts2py.
export class Boom extends Error {}

class Counter {
  private readonly items: string[] = [];
  private count = 0;
  label: string;
  constructor(label: string, start = 10) {
    this.label = label;
    this.count = start;
  }
  get size(): number {
    return this.items.length;
  }
  add(item: string, times = 1): number {
    this.items.push(item);
    this.count += times;
    this.count *= 2;
    return this.count;
  }
  push(x: string): string {
    return `own push ${x}`;
  }
  twice(): number {
    return this.count * 2;
  }
  toString(): string {
    return `${this.label}:${this.count}`;
  }
}

class Frozen {
  readonly v: number;
  constructor(v: number) {
    this.v = v;
    Object.freeze(this);
  }
}

function kind(x: unknown): string {
  switch (typeof x) {
    case 'number':
    case 'bigint':
      return 'numeric';
    case 'string': {
      const n = (x as string).length;
      return `string/${n}`;
    }
    default:
      return 'other';
  }
}

function scan(text: string): string[] {
  let i = 0;
  const out: string[] = [];
  const skip = (): void => {
    while (text[i] === ' ') i += 1;
  };
  for (;;) {
    skip();
    if (i >= text.length) break;
    const start = i;
    while (i < text.length && text[i] !== ' ') i += 1;
    out.push(text.slice(start, i));
  }
  return out;
}

export function probe(): string {
  const c = new Counter('c');
  const added = c.add('a', 3);
  const frozen = new Frozen(1);
  let froze = 'no error';
  const e = new Boom('bad thing');
  const t = new TypeError('tt');
  t.name = 'Renamed';
  const [, second, third] = ['x', 'y'];
  const { label, missing } = { label: 'L', other: 1 } as { label: string; missing?: number };
  let a = 0;
  let b = 0;
  a = b = 7;
  let p = 1;
  let q = 2;
  [p, q] = [q, p];
  const spread = { ...{ z: 1, a: 2 }, b: 3, ...(null as unknown as object) };
  const astral = 'a😀b';
  const m = /^(a)(x)?(😀)?/.exec(astral);
  const half = astral.slice(0, 2);
  const rejoin = half + astral.slice(2);
  const big = BigInt('0x1f') * 3n + BigInt(2);
  return JSON.stringify([
    added,
    c.size,
    String(c),
    `${c}`,
    c.toString(),
    c.push('p'),
    c instanceof Counter,
    froze,
    e.message,
    e.name,
    String(e),
    e instanceof Boom,
    e instanceof Error,
    t.name,
    String(t),
    second,
    third === undefined,
    label,
    missing === undefined,
    a + b,
    [p, q],
    Object.keys(spread),
    'b' in spread,
    'toString' in spread,
    'nope' in spread,
    Object.getPrototypeOf(spread) === Object.prototype,
    Object.getPrototypeOf([]) === Object.prototype,
    kind(1),
    kind(2n),
    kind('😀'),
    kind(null),
    scan('  ab  c d '),
    [7 % 3, -7 % 3, 7 % -3, 5.5 % 2],
    String(-4 % 2 === 0) + String(1 / (-4 % 2)),
    [7 / 2, 1 / 0, -1 / 0, String(0 / 0), 6 / 3],
    String(1 / -0),
    [Math.floor(-2.5), Math.abs(-3), Math.max(1, 5, 3), Math.min(), Math.max()],
    String(big),
    typeof big,
    big === 95n,
    (2n * 0n) === 0n,
    astral.length,
    astral[1] === '\ud83d',
    astral.codePointAt(1),
    astral.codePointAt(2),
    String.fromCodePoint(0x1f600, 0x61),
    String.fromCodePoint(0xd83d) + String.fromCodePoint(0xde00) === '😀',
    half.length,
    rejoin === astral,
    [...astral].length,
    astral.split('').length,
    astral.indexOf('b'),
    astral.lastIndexOf('a', -5),
    'abcabc'.lastIndexOf('c', 4),
    '7'.padStart(3, '0'),
    'ab'.padEnd(5, 'xy'),
    '-'.repeat(3),
    'a_b_c'.replace(/_/g, ''),
    'a_b_c'.replace('_', '+'),
    'x😀y'.replace(/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g, '?'),
    ('\ud83d' + 'x').replace(/[\ud800-\udbff](?![\udc00-\udfff])/g, '?'),
    m === null ? null : [m[0], m[1], m[2] === undefined, m[3]],
    new RegExp(`^[0-9]{${2}}$`).test('12'),
    new RegExp(`^[0-9]{${2}}$`).test('123'),
    parseInt('ff', 16),
    parseInt('  -12abc'),
    Number('12'),
    Number('1_0'),
    Number.isNaN(Number('x')),
    (255).toString(16).toUpperCase(),
    'ABC'.toLowerCase(),
  ]);
}

export function frozenWrite(): void {
  const f = new Frozen(1) as unknown as { v: number };
  f.v = 2;
}

export function mixBigInt(): unknown {
  return (1n as unknown as number) * 2;
}

export function throwBoom(): never {
  throw new Boom('from throw');
}

export function probe2(): string {
  const c = new Counter('q', 4);
  const xs = [3, 1, 2];
  const popped = xs.pop();
  const empty: number[] = [];
  return JSON.stringify([
    c.twice(),
    String(Infinity),
    String(-Infinity),
    String(NaN),
    Number.isNaN(NaN),
    xs.reverse(),
    popped,
    empty.pop() === undefined,
    [1, 2, 3].filter((x) => x > 1),
    Object.entries({ a: 1, b: 'two' }),
    [['k', 1], ['j', 2]].filter(([k]) => k === 'k').length,
    new Error('m').message,
    String(new Error()),
    new TypeError('t') instanceof Error,
    String(Math.floor(-0.5)),
    String(1 / Math.floor(-0)),
  ]);
}
