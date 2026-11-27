// Plain JavaScript syntax also lets Node 20 run this TypeScript fixture as an ES module.
export function propertyProbe() {
  const values = [null, undefined, {}, 'hello', [1, 2], 1, true];
  const keys = ['length', 'missing', '', 0];
  const out = [];
  for (const value of values) {
    try {
      out.push(['read', value.length]);
    } catch (e) {
      out.push([e instanceof TypeError, e instanceof Error, e.name, e.message]);
    }
    for (const key of keys) {
      try {
        out.push(['read', value[key]]);
      } catch (e) {
        out.push([e instanceof TypeError, e instanceof Error, e.name, e.message]);
      }
    }
  }
  return JSON.stringify(out);
}

export function argumentsProbe() {
  let effects = 0;
  const tick = (n) => { effects += 1; return n; };
  const empty = () => 'ok';
  const one = (a) => a;
  const pair = (a, b) => { return a + b; };
  const fallback = (a = 7) => a;
  const underscore = (_) => _;
  let loose = (a) => a;
  const alias = one;
  let state = 345;
  const out = [];
  for (let i = 0; i < 128; i++) {
    state = (state * 16807) % 2147483647;
    const n = state % 1000;
    try {
      out.push([
        empty(tick(n)), one(n, tick(1)), pair(n, 2, tick(3), tick(4)),
        fallback(undefined, tick(n)), underscore(n, tick(5)),
        loose(n, tick(6)), alias(n, tick(7)), effects,
      ]);
    } catch (e) {
      out.push(['threw', e instanceof TypeError]);
    }
  }
  return JSON.stringify(out);
}
