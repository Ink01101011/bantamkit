// J90-P7 (#316 G4) probe (tests/j90p7.rs): the forms ts2py writes so that mypyc compiles the
// generated modules as they stand. `probe()` is pinned as Node printed it:
//   node -e "import('./tests/fixtures/j90p7_probe.ts').then(m => console.log(JSON.stringify(m.probe())))"
export class Oops extends Error {}

export class Bag {
  private readonly items: number[] = [];
  private seed: number;
  constructor(seed: number) {
    this.seed = seed;
  }
  get size(): number {
    return this.items.length;
  }
  add(n: number): number {
    this.items.push(n);
    return this.items.length;
  }
  // A method holding a closure that captures `this` and a local: written as a module function.
  scaled(k: number): number[] {
    const offset = this.seed + 1;
    return [...this.items].sort((a, b) => (b - a) * k).map((x) => x * k + offset);
  }
  // A nested function that throws, caught by the method that holds it.
  checked(limit: number): string {
    const fail = (why: string): never => {
      throw new Oops(`${why} past ${limit}`);
    };
    try {
      if (this.items.length > limit) fail('size');
      return 'ok';
    } catch (e) {
      return e instanceof Oops ? e.message : 'other';
    }
  }
}

// A module-level `let` whose value changes type (int, then a fraction): JS allows it.
export let ratio = 3;

export function halve(): number {
  ratio = ratio / 2;
  return ratio;
}

export function probe(): unknown[] {
  const bag = new Bag(10);
  bag.add(1);
  bag.add(2);
  const out: unknown[] = [bag.size, bag.scaled(3), bag.checked(5), bag.checked(1)];
  out.push(halve(), halve());
  out.push(new Oops('x') instanceof Error, bag instanceof Bag, new Oops('y') instanceof Bag);
  return out;
}

// Called from Python with an instance of a Python subclass: compiled, `instanceof` and a property
// read must still see it (an inline `isinstance` of a non-native class tests the exact type).
export function isBag(x: unknown): boolean {
  return x instanceof Bag;
}

export function readV(o: { v: unknown }): unknown {
  return o.v;
}
