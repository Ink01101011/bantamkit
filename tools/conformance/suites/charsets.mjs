/**
 * charsets — the port's copy of CPython's codec registry, against the registry itself.
 *
 * THE PROPERTY: `runtime-ts/src/charsets.ts` is not a second registry kept in step by hand;
 * it is CPython's, written out by `runtime-ts/scripts/charsets-table.py`, and this suite is
 * what makes that a measurement. Two comparisons, because two things drift independently:
 *
 *   1. THE FILE AGAINST THE GENERATOR. The checked-in `charsets.ts` is compared byte for byte
 *      with what the generator writes today, header line excluded — the header names the
 *      interpreter's version, which the note reports instead, so a `3.12.13` venv and a
 *      `3.12.x` CI runner compare the tables and not the banner. An edited script whose
 *      output was never regenerated fails here.
 *   2. THE TABLES AGAINST THE INTERPRETER. For every codec the port carries, all 256 bytes
 *      are decoded by the REFERENCE (`bytes([b]).decode(codec, errors="replace")`, computed
 *      in `ref/charsets_ref.py`, not read back from the generator) and compared to what the
 *      port's table says — the low half is ASCII unless the table carries a `low` (the
 *      EBCDIC pages). The alias map and the module list are compared whole. A CPython that
 *      changed a table, added an alias or dropped a module fails here even if the file and
 *      the generator still agree with each other.
 *   3. THE KEY SETS, so the comparison runs BOTH WAYS. Comparison 2 is driven by the PORT'S
 *      key list, so until review round 4 it could see a table that changed and never one that
 *      VANISHED — a lost codec lost its case and the run stayed green (M7 / I3-F7). Two cases
 *      now compare the loaded artefact's key set against the generator's, so a port that drops
 *      a table fails as surely as an interpreter that drops a module.
 *
 * Nothing in comparisons 1-3 is a ruling: the port is REQUIRED to answer for the registry it
 * was generated from, and a difference there is a stale file, never a decision.
 *
 *   4. THE TEN CJK CODECS, WHICH ARE NOT IN THAT FILE AT ALL, and where the two sides are
 *      RULED to differ. `charsets.ts` carries single-byte tables; `euc_jp`, `euc_kr`,
 *      `cp932`, `gb18030`, `gbk`, `shift_jis`, `big5`, `big5hkscs`, `cp949` and `gb2312` go
 *      through ICU's `TextDecoder` instead (`docread.ts` `MULTI_BYTE_LABELS`), and the six
 *      `iso2022_jp*` labels through ICU's `iso-2022-jp` whole (`ESCAPE_LABELS`). ICU's
 *      tables are not CPython's. Roadmap row 8 (o) has said so in prose since 2026-08-29
 *      with ten per-codec counts beside it, and until 2026-09-06 NOTHING compared them — the
 *      port could have changed in either direction and no run would have gone red.
 *      See `CJK_RULING` and `PINNED` below for the shape and for what each case holds.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'charsets';
export const summary =
  'src/charsets.ts against the live CPython codec registry: the generator\'s output, every single-byte table, and the ten CJK codecs ICU decodes instead';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'charsets_ref.py');
const CJK_REF = join(here, 'ref', 'cjk_ref.py');

const ASCII = Array.from({ length: 128 }, (_, i) => String.fromCharCode(i)).join('');
const HEADER = /^\/\/ Registry: CPython .*\n/m;

// --------------------------------------------------------------------------- the CJK half

/**
 * The ten codecs `docread.ts` decodes through ICU rather than through `charsets.ts`, in the
 * order roadmap row 8 (o) lists them. `iso2022_jp` is measured separately below, because it
 * is a STATEFUL codec and a corpus of random bytes says almost nothing about one.
 */
const CJK = ['euc_jp', 'euc_kr', 'cp932', 'gb18030', 'gbk', 'shift_jis', 'big5', 'big5hkscs', 'cp949', 'gb2312'];

const CJK_RULING =
  'the reference decodes through CPython\'s own multi-byte codec tables and the port through ICU\'s ' +
  '(`docread.ts` MULTI_BYTE_LABELS -> TextDecoder), and the two tables are not the same table. ' +
  'Four of the ten labels are not even the same codec on the WHATWG side — `gb2312` is decoded by ' +
  'ICU\'s gbk, `big5` carries HKSCS, `euc-kr` is cp949, `shift_jis` is cp932 — so a byte pair only ' +
  'one of the two knows parts them. Lifting this means writing CPython\'s CJK tables out into ' +
  'TypeScript the way `charsets.ts` does for single-byte codecs, which is 79 tables of 256 entries ' +
  'there against tens of thousands of multi-byte mappings here, for a difference that lands on ' +
  'MALFORMED input. See `docs/porting.md`, "the ten CJK codecs on Node".';

const ISO_RULING =
  'the same cause under a stateful codec: `iso2022_jp` goes to ICU\'s `iso-2022-jp` decoder whole ' +
  '(`docread.ts` ESCAPE_LABELS), and ICU maps six JIS X 0208 code points the way Windows-31J does ' +
  'where CPython maps them the way JIS X 0208 does — the wave dash U+301C against U+FF5E being the ' +
  'one roadmap row 8 (o) names — and rejects the SO/SI controls CPython passes through. Unlike the ' +
  'ten above, this one bites on VALID text. See `docs/porting.md`, "ISO-2022-JP\'s eight characters on Node".';

/**
 * WHAT THE LITERALS BELOW ARE FOR, AND WHY A `ruling:` ALONE WOULD HAVE BEEN A LIE.
 *
 * A ruling asserts the two sides DIFFER and stops there. Ten rulings over these codecs would
 * stay green if ICU and CPython both changed in the same direction, if the port stopped
 * decoding CJK at all and answered UTF-8 mojibake (still different!), or if the corpus itself
 * silently became a different corpus. So every ruling here sits beside FOUR non-ruled cases
 * that are literals in this file:
 *
 *   `matched`      — how many of the 300 seeded inputs the two sides answer alike. This is
 *                    the number roadmap row 8 (o) quotes, and pinning it is what makes
 *                    `gb2312` moving from 141 to 150 a failure instead of a re-measurement.
 *   `reference`    — a digest of CPython's own 300 answers. Anchors the REFERENCE half: it
 *                    goes red on a CPython whose tables moved, with the ruling still green.
 *   `port`         — a digest of ICU's own 300 answers. Anchors the PORT half, and this is
 *                    the case that catches a symmetric regression: both sides drifting
 *                    together keeps `matched` and the ruling exactly as they are.
 *   `first`        — the FIRST input the two disagree on, with both answers spelled out.
 *                    A digest tells you something moved; this tells you what, on one line.
 *
 * MEASURED 2026-09-06 on CPython 3.12.13 and Node v25.2.1 (ICU 77.1). These numbers are
 * ICU-version-dependent BY CONSTRUCTION — that is the point of anchoring the port's half —
 * so a Node whose ICU differs turns them red, and the suite's note names both versions so a
 * reader can tell an ICU upgrade from a regression in one glance.
 *
 * THEY ARE NOT ROADMAP ROW 8 (o)'s NUMBERS, and that is a finding, not a discrepancy to be
 * smoothed over. That row's recipe was never checked in; ninety-odd reconstructions of its
 * sentence were tried on 2026-09-06 and none reproduces its ten counts together — its own
 * profile rules a single corpus out. `tools/conformance/ref/cjk_ref.py`'s header carries the
 * measurement and the reasoning; `docs/porting.md` carries the diff. What is pinned here is
 * what a rerun of a recipe that EXISTS measures.
 */
const CORPUS_DIGEST = '369de783e62618e2';
const PINNED = {
  euc_jp: {
    matched: 295,
    reference: '7289cdfec3e912e5',
    port: '9f6331b2f12ec61e',
    first: { index: 11, input: 'd654af4dfad7', reference: '\uFFFDT\uFFFDM\uFFFD\uFFFD', port: '\uFFFDT\uFFFDM\u6A7E' },
  },
  euc_kr: {
    matched: 298,
    reference: '978b7b1da534813c',
    port: 'ca9ed18124709b68',
    first: { index: 7, input: '1e69fedaa0ee', reference: '\u001Ei\uFFFD\uFFFD\uFFFD\uFFFD', port: '\u001Ei\uE097\uFFFD\uFFFD' },
  },
  cp932: {
    matched: 285,
    reference: '875dda57133db1db',
    port: 'fdc8c99597f7326f',
    first: { index: 8, input: 'e8b9997f5c7c', reference: '\u96F9\uFFFD\u007F\\|', port: '\u96F9\uFFFD\u001A\\|' },
  },
  gb18030: {
    matched: 293,
    reference: '33e4579b6744ffa4',
    port: '3782257c09f83754',
    first: { index: 6, input: '5c3460be3120', reference: '\\4`\uFFFD', port: '\\4`\uFFFD1 ' },
  },
  gbk: {
    matched: 277,
    reference: '003ef6a4ae74990d',
    port: '7d0fc728ce734f23',
    first: { index: 7, input: '1e69fedaa0ee', reference: '\u001Ei\uFFFD\u8DD4\uFFFD', port: '\u001Ei\uE4A1\u72C0' },
  },
  shift_jis: {
    matched: 247,
    reference: '42b377a0bd9e135f',
    port: 'ed65853b27708249',
    first: { index: 8, input: 'e8b9997f5c7c', reference: '\u96F9\uFFFD\u007F\\|', port: '\u96F9\uFFFD\u001A\\|' },
  },
  big5: {
    matched: 210,
    reference: 'bd0b21f9e13d241d',
    port: 'f4be57355366b6f8',
    first: { index: 5, input: '4494d6493c9d', reference: 'D\uFFFD\u710D<\uFFFD', port: 'D\uE733I<\uFFFD' },
  },
  big5hkscs: {
    matched: 211,
    reference: '31c933aa6e444f4f',
    // NOT A COPY-PASTE OF `big5`'s: `big5` and `big5hkscs` are ONE decoder on the port, ICU's
    // `big5`, which carries HKSCS. The reference has two. The two `port` digests being equal
    // and the two `reference` digests differing IS the divergence, spelled as data.
    port: 'f4be57355366b6f8',
    first: { index: 5, input: '4494d6493c9d', reference: 'D\u{20D4C}I<\uFFFD', port: 'D\uE733I<\uFFFD' },
  },
  cp949: {
    matched: 205,
    reference: 'b9ce92c20bc1f46d',
    port: 'ca9ed18124709b68', // likewise: `euc_kr` and `cp949` are both ICU's `euc-kr`.
    first: { index: 5, input: '4494d6493c9d', reference: 'D\uBDA7I<\uFFFD', port: 'D\uFFFD\uFFFDI<\uFFFD' },
  },
  gb2312: {
    matched: 141,
    reference: '9ef56d61450232a1',
    port: '7d0fc728ce734f23', // likewise: `gb2312` and `gbk` are both ICU's `gbk`.
    first: { index: 5, input: '4494d6493c9d', reference: 'D\uFFFD\uFFFDI<\uFFFD', port: 'D\u65A8I<\uFFFD' },
  },
};

/**
 * ISO-2022-JP, PINNED BY CHARACTER AND NOT BY COUNT.
 *
 * Roadmap row 8 (o) says the residual is "12 of 900 valid-text inputs, and every one of the
 * 12 is the WAVE DASH". A count of 12 that stays 12 while the differing characters change is
 * a gate that missed something, so `characters` is the case that matters: a CENSUS of every
 * one of the 7,008 characters CPython's `iso2022_jp` round-trips, decoded one at a time
 * through both sides, keyed by `U+xxxx -> U+xxxx`.
 *
 * IT REFUTES THE "EVERY ONE" HALF. EIGHT characters differ, not one:
 *
 *   U+00A2 -> U+FFE0   CENT SIGN            -> FULLWIDTH CENT SIGN
 *   U+00A3 -> U+FFE1   POUND SIGN           -> FULLWIDTH POUND SIGN
 *   U+00AC -> U+FFE2   NOT SIGN             -> FULLWIDTH NOT SIGN
 *   U+2016 -> U+2225   DOUBLE VERTICAL LINE -> PARALLEL TO
 *   U+2212 -> U+FF0D   MINUS SIGN           -> FULLWIDTH HYPHEN-MINUS
 *   U+301C -> U+FF5E   WAVE DASH            -> FULLWIDTH TILDE      <- the one the row names
 *   U+000E -> U+FFFD   SHIFT OUT   } CPython passes the SO/SI controls through; ICU refuses
 *   U+000F -> U+FFFD   SHIFT IN    } them, so these two are a REFUSAL and not a remapping.
 *
 * The first six are the well-known JIS X 0208 against Windows-31J disagreement; the wave dash
 * is simply its most-cited member, and the register generalised from a sample that happened
 * to contain only it. `textCharacters` is the SAMPLE shape re-run (900 seeded strings) and it
 * finds 7 differing inputs against the row's 12, over five of the eight characters — which is
 * the same point from the other side: a sample cannot settle a claim about which characters.
 */
const ISO = {
  module: 'iso2022_jp',
  census: 7008,
  censusReference: 'd44d3ac621d7e088',
  censusPort: '5fbb6ca70bd6fa7a',
  characters: {
    'U+000E -> U+FFFD': 1,
    'U+000F -> U+FFFD': 1,
    'U+00A2 -> U+FFE0': 1,
    'U+00A3 -> U+FFE1': 1,
    'U+00AC -> U+FFE2': 1,
    'U+2016 -> U+2225': 1,
    'U+2212 -> U+FF0D': 1,
    'U+301C -> U+FF5E': 1,
  },
  textInputs: 900,
  textDiffering: 7,
  textReference: '128027bf5203f722',
  textPort: 'ccef63f05206ada8',
  textCharacters: {
    'U+000E -> U+FFFD': 1,
    'U+000F -> U+FFFD': 2,
    'U+00A2 -> U+FFE0': 1,
    'U+2016 -> U+2225': 1,
    'U+301C -> U+FF5E': 2,
  },
};

/**
 * The unit separator, and never a newline or a comma: it cannot occur in a decoded answer
 * here (no CJK codec produces U+001F from a byte that is not 0x1F, and 0x1F alone decodes to
 * U+001F on both sides), so joining on it cannot make two different answer LISTS hash alike.
 */
const SEP = String.fromCharCode(31);

/** 64 bits of SHA-256 over the joined list — enough that a changed answer cannot collide. */
const digest = (parts) => createHash('sha256').update(parts.join(SEP), 'utf8').digest('hex').slice(0, 16);

const codepoint = (c) => `U+${c.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}`;

/** `U+xxxx -> U+xxxx` counted, so the KEY names the characters and the value names how many. */
function characterDiff(reference, port) {
  const map = {};
  for (let i = 0; i < reference.length; i += 1) {
    const a = [...reference[i]];
    const b = [...port[i]];
    for (let k = 0; k < Math.max(a.length, b.length); k += 1) {
      if (a[k] === b[k]) continue;
      const key = `${a[k] === undefined ? '<end>' : codepoint(a[k])} -> ${b[k] === undefined ? '<end>' : codepoint(b[k])}`;
      map[key] = (map[key] ?? 0) + 1;
    }
  }
  return map;
}

/**
 * The KEY SET the generator writes for one of its two tables, read out of the generator's own
 * stdout — which is the only place the reference's answer to "which codecs belong here" exists.
 *
 * WHY THIS FUNCTION EXISTS (review round 4, M7 / I3-F7). Every per-codec case below is driven
 * by `Object.keys(charsets.SINGLE_BYTE_TABLES)` — the PORT'S OWN key list. That direction
 * catches a table whose contents drifted; it cannot catch a table that is GONE, because a
 * codec the port has lost simply generates no case. Measured on the shipped artefact
 * `runtime-ts/dist/charsets.js`, the file the port executes and `package.json` `files:`
 * ships: change one codepoint of `cp437` and the suite goes red (93 cases, 1 failure), but
 * DELETE the whole `cp437` entry and it stays green at 92 cases and 0 failures. The header
 * three lines up claims "a CPython that … dropped a module fails here", and that is true; the
 * converse was not, and the only signal was a case count nobody asserts.
 *
 * The `src/charsets.ts` byte comparison does not close it either: that case compares SOURCE
 * against the generator, and the mutation above is in `dist`. Nothing compared what the port
 * actually loads against what the reference says should be there.
 *
 * `json.dumps(..., indent=2)` writes valid JSON, so the object is parsed rather than scraped:
 * find the assignment, take the object between the first `{` after `=` and the `};` that
 * closes it at column 0.
 */
function generatedKeys(generated, constName) {
  const at = generated.indexOf(`export const ${constName}`);
  if (at < 0) return `<the generator wrote no ${constName}>`;
  const open = generated.indexOf('{', generated.indexOf('=', at));
  const close = generated.indexOf('\n};', open);
  if (open < 0 || close < 0) return `<could not read ${constName} out of the generator's output>`;
  try {
    return Object.keys(JSON.parse(generated.slice(open, close + 2))).sort();
  } catch (e) {
    return `<${constName} did not parse: ${e.message}>`;
  }
}

export async function run(ctx) {
  const charsets = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'charsets.js')).href);
  const source = readFileSync(join(ctx.runtimeTs, 'src', 'charsets.ts'), 'utf8');
  const codecs = Object.keys(charsets.SINGLE_BYTE_TABLES).sort();
  const multi = Object.keys(charsets.MULTI_BYTE_SINGLES).sort();
  const python = ctx.runPython(REF, { codecs, multi });

  const cases = [];
  const notes = [];

  const fileVersion = source.match(HEADER)?.[0].match(/CPython (\S+)/)?.[1] ?? null;
  // A GENERATOR THAT DID NOT RUN IS A FAILING CASE, NOT A CRASH. Reading `.replace` off a
  // null took the whole run down on Windows with a `TypeError` that named neither the
  // generator nor the platform, so the suite had never completed there and nothing said so.
  // The reference now reports the outcome and this turns it into one legible failure.
  if (typeof python.generated !== 'string') {
    const g = python.generator ?? {};
    cases.push({
      name: 'scripts/charsets-table.py runs at all',
      kind: 'json',
      expected: { ran: true, returncode: 0 },
      actual: { ran: typeof python.generated === 'string', returncode: g.returncode ?? null },
    });
    notes.push(
      `charsets: the generator did not produce a table. path=${g.path} exists=${g.exists} ` +
        `returncode=${g.returncode} stdout_bytes=${g.stdout_bytes}` +
        (g.stderr ? `\n--- generator stderr ---\n${g.stderr}` : ''),
    );
    return { cases, notes };
  }
  cases.push({
    name: 'src/charsets.ts is what scripts/charsets-table.py writes for the live registry (header line excluded)',
    kind: 'bytes',
    expected: python.generated.replace(HEADER, ''),
    actual: source.replace(HEADER, ''),
  });
  cases.push({
    name: 'src/charsets.ts carries the generator\'s header',
    kind: 'json',
    expected: true,
    actual: HEADER.test(source) && source.startsWith('// GENERATED by scripts/charsets-table.py'),
  });
  cases.push({ name: 'CODEC_MODULES is what pkgutil finds under encodings', kind: 'json', expected: python.modules, actual: [...charsets.CODEC_MODULES].sort() });
  cases.push({ name: 'CODEC_ALIASES is encodings.aliases.aliases', kind: 'json', expected: python.aliases, actual: charsets.CODEC_ALIASES });
  // THE SET, not just the contents. Everything below iterates the port's own keys, so a table
  // the port LOSES generates no case at all; these two compare the key set the loaded artefact
  // carries against the key set the generator writes, so a shrinking table set is a failure
  // and not a smaller number. See `generatedKeys` above for the measurement that motivated it.
  cases.push({
    name: 'SINGLE_BYTE_TABLES holds exactly the codecs the generator writes — a table the port LOST is a failure, not one fewer case',
    kind: 'json',
    expected: generatedKeys(python.generated, 'SINGLE_BYTE_TABLES'),
    actual: codecs,
  });
  cases.push({
    name: 'MULTI_BYTE_SINGLES holds exactly the codecs the generator writes — a table the port LOST is a failure, not one fewer case',
    kind: 'json',
    expected: generatedKeys(python.generated, 'MULTI_BYTE_SINGLES'),
    actual: multi,
  });
  for (const codec of codecs) {
    const table = charsets.SINGLE_BYTE_TABLES[codec];
    cases.push({
      name: `single-byte ${codec}: all 256 bytes decode as CPython decodes them (errors="replace")`,
      kind: 'bytes',
      expected: python.tables[codec] ?? `<no such codec on the reference: ${codec}>`,
      actual: `${table.low ?? ASCII}${table.high}`,
    });
  }
  for (const codec of multi) {
    cases.push({
      name: `multi-byte ${codec}: which of 0x80..0xFF is a character on its own to CPython`,
      kind: 'bytes',
      expected: python.multi_singles[codec] ?? `<no such codec on the reference: ${codec}>`,
      actual: charsets.MULTI_BYTE_SINGLES[codec],
    });
  }
  notes.push(
    `${codecs.length} single-byte codecs, ${multi.length} multi-byte codecs' single bytes, ${Object.keys(charsets.CODEC_ALIASES).length} aliases, ` +
      `${charsets.CODEC_MODULES.size} modules; src/charsets.ts was generated by CPython ${fileVersion}, the reference here is CPython ${python.version}`,
  );

  // ------------------------------------------------------------------ the ten CJK codecs
  //
  // `decodeCharset` comes from `dist/`, the artefact `package.json` `files:` ships and the
  // one the MCP server executes — same reason comparison 3 above reads `dist/charsets.js`
  // rather than the source. A port that decodes correctly in TypeScript and ships a stale
  // bundle is a port that is wrong for every user of it.
  const docread = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'docread.js')).href);
  const cjk = ctx.runPython(CJK_REF, { codecs: CJK });

  cases.push({
    name: 'cjk: the seeded corpus is the same 300 inputs the counts below were measured over',
    kind: 'json',
    expected: { digest: CORPUS_DIGEST, count: 300 },
    actual: { digest: digest(cjk.inputs), count: cjk.inputs.length },
  });

  for (const codec of CJK) {
    const reference = cjk.answers[codec];
    if (!Array.isArray(reference)) {
      cases.push({
        name: `cjk ${codec}: the reference has this codec at all`,
        kind: 'json',
        expected: true,
        actual: false,
      });
      continue;
    }
    const port = cjk.inputs.map((hex) => docread.decodeCharset(Buffer.from(hex, 'hex'), codec));
    let matched = 0;
    let firstIndex = -1;
    for (let i = 0; i < reference.length; i += 1) {
      if (reference[i] === port[i]) matched += 1;
      else if (firstIndex < 0) firstIndex = i;
    }
    const pin = PINNED[codec];

    // THE RULING. It is the only case here allowed to differ, and it goes red BY ITSELF if
    // the two sides ever agree on all 300 — which is what would happen if someone wrote
    // CPython's tables into the port and forgot to delete the divergence row.
    cases.push({
      name: `ruling: cjk ${codec}: ICU's table against CPython's over 300 seeded byte strings`,
      kind: 'string',
      expected: reference.join(SEP),
      actual: port.join(SEP),
      ruling: CJK_RULING,
    });
    // THE FOUR COMPANIONS. Every one compares a LITERAL in this file against a measurement,
    // so none of them can be satisfied by the two runtimes moving together.
    cases.push({
      name: `cjk ${codec}: how many of the 300 the two sides answer alike`,
      kind: 'json',
      expected: pin.matched,
      actual: matched,
    });
    cases.push({
      name: `cjk ${codec}: the reference's own 300 answers, anchored (a ruling cannot see CPython move)`,
      kind: 'string',
      expected: pin.reference,
      actual: digest(reference),
    });
    cases.push({
      name: `cjk ${codec}: the port's own 300 answers, anchored (a ruling cannot see ICU move)`,
      kind: 'string',
      expected: pin.port,
      actual: digest(port),
    });
    cases.push({
      name: `cjk ${codec}: the first input the two sides answer differently, both answers spelled out`,
      kind: 'json',
      expected: pin.first,
      actual: {
        index: firstIndex,
        input: cjk.inputs[firstIndex] ?? '<the two sides agreed on all 300>',
        reference: reference[firstIndex] ?? '',
        port: port[firstIndex] ?? '',
      },
    });
  }

  // ---------------------------------------------------- iso-2022-jp, by character not count
  const isoChars = cjk.iso.chars;
  const isoCensus = cjk.iso.hex.map((hex) => docread.decodeCharset(Buffer.from(hex, 'hex'), cjk.iso.module));
  const isoText = cjk.iso.text;
  const isoTextPort = cjk.iso.text_hex.map((hex) => docread.decodeCharset(Buffer.from(hex, 'hex'), cjk.iso.module));

  cases.push({
    name: `ruling: cjk ${ISO.module}: ICU's JIS X 0208 mapping against CPython's, over every character CPython round-trips`,
    kind: 'string',
    expected: isoChars.join(SEP),
    actual: isoCensus.join(SEP),
    ruling: ISO_RULING,
  });
  cases.push({
    name: `cjk ${ISO.module}: WHICH characters the port answers differently, by code point — the case a count cannot be`,
    kind: 'json',
    expected: ISO.characters,
    actual: characterDiff(isoChars, isoCensus),
  });
  cases.push({
    name: `cjk ${ISO.module}: how many characters the reference round-trips at all`,
    kind: 'json',
    expected: ISO.census,
    actual: isoChars.length,
  });
  cases.push({
    name: `cjk ${ISO.module}: the reference's own census answers, anchored`,
    kind: 'string',
    expected: ISO.censusReference,
    actual: digest(isoChars),
  });
  cases.push({
    name: `cjk ${ISO.module}: the port's own census answers, anchored`,
    kind: 'string',
    expected: ISO.censusPort,
    actual: digest(isoCensus),
  });
  cases.push({
    name: `ruling: cjk ${ISO.module}: the same difference in the shape roadmap row 8 (o) sampled — 900 seeded strings of valid text`,
    kind: 'string',
    expected: isoText.join(SEP),
    actual: isoTextPort.join(SEP),
    ruling: ISO_RULING,
  });
  cases.push({
    name: `cjk ${ISO.module}: how many of the 900 valid-text inputs differ, and over which characters`,
    kind: 'json',
    expected: { inputs: ISO.textInputs, differing: ISO.textDiffering, characters: ISO.textCharacters },
    actual: {
      inputs: isoText.length,
      differing: isoText.reduce((n, s, i) => n + (s === isoTextPort[i] ? 0 : 1), 0),
      characters: characterDiff(isoText, isoTextPort),
    },
  });
  cases.push({
    name: `cjk ${ISO.module}: the reference's own 900 answers, anchored`,
    kind: 'string',
    expected: ISO.textReference,
    actual: digest(isoText),
  });
  cases.push({
    name: `cjk ${ISO.module}: the port's own 900 answers, anchored`,
    kind: 'string',
    expected: ISO.textPort,
    actual: digest(isoTextPort),
  });

  notes.push(
    `cjk: ${CJK.length} codecs x 300 seeded byte strings and ${ISO.census} iso2022_jp characters + ${ISO.textInputs} strings, ` +
      `reference CPython ${cjk.version} against Node ${process.version} (ICU ${process.versions.icu}). ` +
      'The pinned counts and digests move with EITHER version — the note names both so a red run can be read.',
  );
  return { cases, notes };
}
