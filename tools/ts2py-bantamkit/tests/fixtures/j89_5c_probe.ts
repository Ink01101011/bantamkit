// J89-5c (#316 G3 U3): `s.split(re)`, the construct `memory/dream.ts`'s `splitBlocks` needed
// (`normalised.split(BLOCK_SPLIT)`). `probe()` answers one JSON-able array and `fuzz(n)` one
// digest; tests/g3_store.rs holds both to what Node v26.13.0 printed for this file (imported by
// Node, which strips the types).

const SPLITTERS: RegExp[] = [
  /\n[ \t]*\n+/,
  /x*/,
  /(-)|(\+)/,
  /^a/,
  /a$/,
  /(?<=b)c/,
  /\b/,
  /,/,
  /[\uD800-\uDBFF]/,
  /\uDE00/,
  /(?:)/,
  /(a)?b/,
  /\n[ \t]*\n+/g,
];
const SUBJECTS: string[] = [
  '',
  'a',
  'abc',
  'a\n\nb\n \n\nc',
  '\n\n',
  'x-y+z',
  'axbxxc',
  'bcbc',
  'a\u{1F600}b',
  '\u{1F600}\u{1F600}',
  'aa',
  'cab',
  'a,b,,c,',
  ',',
  'b',
  'ab',
  'word boundary',
  '\uD800x\uDC00',
];

export function probe(): unknown[] {
  return SPLITTERS.map((re) => SUBJECTS.map((s) => s.split(re)));
}

const ALPHABET: string[] = ['a', 'b', 'c', 'x', '-', '+', '\n', ' ', '\t', ',', '\u{1F600}', '\uD800', '\uDE00'];

export function fuzz(n: number): number {
  let seed = 5089;
  let acc = 0;
  for (let i = 0; i < n; i += 1) {
    seed = (seed * 48271) % 2147483647;
    const size = seed % 13;
    let s = '';
    for (let k = 0; k < size; k += 1) {
      seed = (seed * 48271) % 2147483647;
      s += ALPHABET[seed % ALPHABET.length]!;
    }
    seed = (seed * 48271) % 2147483647;
    const parts = s.split(SPLITTERS[seed % SPLITTERS.length]!);
    acc = (acc * 31 + parts.length) % 1000000007;
    for (const part of parts) {
      acc = (acc * 31 + (part === undefined ? 1 : part.length + 2)) % 1000000007;
    }
  }
  return acc;
}
