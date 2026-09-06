/**
 * docread — the reader, Python against Node, over the same files.
 *
 * THE PROPERTY: handed the same bytes, `docread.py` and `docread.ts` identify the same
 * container, render the same rows, count the same omissions and refuse with the same
 * sentence — except for the three kinds the Node half cannot read (`pdf`, `doc`, `rtf`),
 * each of which is a `ruling` below with its reason and a companion that pins the refusal
 * bit rather than the words (docs/conformance.md, "a ruling pins the wording, not the
 * outcome") — and except one codec, utf-7, which CPython has and WHATWG does not: that
 * ruling is over two READS, and its companion pins that neither side refuses. Job43 G3
 * added three more: two zip compression methods `node:zlib` has not got (bzip2, lzma —
 * the reference reads both, the port refuses by method and number, and the companions pin
 * the reference's row and the port's sentence as literals), and RFC 2231 charset
 * continuations, a second both-READ ruling over the one decoded row. H3 added the fourth
 * both-READ ruling, `<!ATTLIST>` defaults (`attlist.xlsx`, built below: the reference's expat
 * applies the default and reads `SHARED`, the port's subset walk skips it and reads `0`).
 * Job44's U17 added the fifth both-READ ruling and the first whose divergence is an OMISSION
 * rather than a row: a bzip2 `xl/styles.xml` that CARRIES a date format (`bzip2-date-styles
 * .xlsx`), where both sides read `46235\tok` and only the reference can say that `46235` is
 * `yyyy-mm-dd`. It is the one ruling with a CONTROL — `deflate-date-styles.xlsx`, the same
 * styles bytes behind method 8, on which both sides disclose — pinned as a literal below,
 * because a ruling over a missing omission goes quietly green if the input stops producing
 * one at all.
 *
 * THE THIRTEEN CHECKED-IN FIXTURES under `runtime-py/tests/data/docread/` (job43 G1 wrote
 * seven, round 3's H1 six more) are read from where they lie, unruled but for `rfc2231-charset.eml`; and the path `a\x00b` — a NUL
 * inside a file name — is handed to both as typed. Both sides answer `no such file: a\x00b`
 * on macOS, where this job measured it; the case is not skipped on win32, so a Windows run
 * measures it itself — and the note says which platform the numbers in hand came from.
 *
 * THE FIXTURES ARE R3's. `runtime-ts/test/docread-fixtures.mjs` lays down the 77 files
 * `runtime-py/tests/test_docread.py` builds with `zipfile` — the xlsx traps (shared strings,
 * rich-text runs, number formats, blank rows, unresolved rels), the docx shapes, HTML and
 * MHTML, the UTF-8 head boundary, the suffix lies — and this suite adds what the brief asks
 * for on top: a `.py` source, a copy of the host's own `ls` binary, a PDF that carries text
 * (so the pdf ruling is "the reference READS it and the port refuses", not two refusals), an
 * RTF `textutil` cannot convert, and the missing path. Both sides read the SAME directory:
 * nothing here writes, so there is no `py/` vs `node/` split and no path to scrub.
 *
 * `page()` is driven separately from `extract()`, because the row window is where the two
 * ceilings live (50 rows default, 200 max, 3072 bytes) and where the reference's
 * `Document.part` once leaked `int()`'s `ValueError` for a part named `--1` — the case that
 * found it is below, unruled, and the reference was the side that changed.
 */
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'docread';
export const summary = 'the reader: sniff, rows, omissions and refusals over the same files, and the pdf/doc/rtf rulings';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'docread_ref.py');

/**
 * A one-page PDF with one text run, built the way `pdfread` reads it: a catalog, a page
 * tree, a page, a content stream with `BT … (text) Tj ET`, a Type1 font, an xref table with
 * byte-exact offsets. Small enough to write by hand and enough for the reference to render
 * one row from — measured: `docread.extract` answers `[('page 1', ['Hello conformance'])]`.
 */
export function tinyPdf(text) {
  const objs = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    null,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];
  const stream = `BT /F1 12 Tf 72 700 Td (${text}) Tj ET`;
  objs[3] = `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`;
  let out = '%PDF-1.4\n';
  const offsets = [];
  objs.forEach((o, i) => {
    offsets.push(out.length);
    out += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
  for (const off of offsets) out += `${String(off).padStart(10, '0')} 00000 n \n`;
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}

/**
 * `0 -> "A"`, `25 -> "Z"`, `26 -> "AA"`: a zero-based column index as ECMA-376 spells it.
 *
 * The same walk `runtime-ts/test/docread.test.mjs` uses to build its 300,000-cell row, kept
 * here because the row is now a conformance fixture too (register entry (p)) and neither
 * runtime's reader exports the inverse of `_letter`.
 */
export function columnLetter(index) {
  let n = index + 1;
  let out = '';
  while (n > 0) {
    const remainder = (n - 1) % 26;
    out = String.fromCharCode(65 + remainder) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

/**
 * The three kinds the Node half refuses by name, and what each side is EXPECTED to do with
 * each ruled fixture. `python` is a function of whether the host has `/usr/bin/textutil`,
 * which the reference reports rather than the suite assuming; `node` is always a refusal.
 *
 *   tiny.pdf   carries text: the reference reads it, the port refuses. The sharpest ruling.
 *   doc.pdf, sheet.xlsx.pdf, named.xlsx   a `%PDF-` header and nothing behind it: the
 *              reference refuses on the structure, the port refuses on the kind. BOTH refuse.
 *   real.doc, sheet.xls   an OLE2 signature over zeros / over `rest`: without textutil the reference refuses "not on
 *              this host"; with it, textutil reports `Type: plain text` and the reference
 *              refuses THAT. BOTH refuse, on every host.
 *   bad.rtf    an `{\rtf` signature over bytes textutil cannot convert: refused without
 *              textutil, and with it converts to no text, which `_nonempty` refuses. BOTH.
 *   note.rtf   a real RTF: read where textutil is, refused where it is not; the port refuses.
 */
const RULED = {
  'tiny.pdf': { kind: 'pdf', python: () => false },
  // Two compression methods `node:zlib` has not got. The reference reads both to one row
  // (`zipfile` links bz2 and lzma); the port names the member, the method NUMBER and its
  // name in the refusal. `reads` and `sentence` are the two literals the companions pin —
  // both were generated from a measured run (`.venv/bin/python` over the fixture, and the
  // port's `extract` over the same bytes), never written by hand.
  'bzip2.docx': {
    kind: 'bzip2',
    python: () => false,
    reads: ['hello'],
    sentence: 'DocumentReadError: bzip2.docx is a zip but its word/document.xml uses compression method 12 (bzip2), which the Node server cannot decompress (the Python server reads it); see docs/porting.md',
  },
  'lzma.docx': {
    kind: 'lzma',
    python: () => false,
    reads: ['hello'],
    sentence: 'DocumentReadError: lzma.docx is a zip but its word/document.xml uses compression method 14 (lzma), which the Node server cannot decompress (the Python server reads it); see docs/porting.md',
  },
  // job44 U17. The same undecompressable method on an OPTIONAL member, now CARRYING a date
  // format. Both sides READ (`node: false`), both answer the same row, and the divergence is
  // the DISCLOSURE — so `discloses` is the literal the reference must emit and the port must
  // not, measured from each side's own run. Its control, `deflate-date-styles.xlsx`, is not
  // ruled and is pinned below.
  'bzip2-date-styles.xlsx': {
    kind: 'bzip2Styles',
    python: () => false,
    node: false,
    discloses: [{ subject: 'number-format', count: 1, size: 0, where: ['A'], what: 'yyyy-mm-dd', facts: {} }],
  },
  // RFC 2231: both READ, one row apart — the utf-7 shape (`node: false` below).
  'rfc2231-charset.eml': { kind: 'rfc2231', python: () => false, node: false },
  'doc.pdf': { kind: 'pdf', python: () => true },
  'sheet.xlsx.pdf': { kind: 'pdf', python: () => true },
  'named.xlsx': { kind: 'pdf', python: () => true },
  'real.doc': { kind: 'doc', python: () => true },
  'sheet.xls': { kind: 'doc', python: () => true },
  'bad.rtf': { kind: 'rtf', python: () => true },
  'note.rtf': { kind: 'rtf', python: (textutil) => !textutil },
  // The one ruling where NEITHER side refuses: both read the file to one row, and the row
  // differs by one codepoint. `node: false` is what makes the companion below "both read".
  'utf7.eml': { kind: 'utf7', python: () => false, node: false },
  // Review round 4 (H1's residual): the same divergence as `utf7.eml` under two more names.
  // `decodeCharset`'s docstring already said so; it had no ruling row and no case, and per
  // CLAUDE.md a deliberate difference costs three things. Both READ, so `node: false` again
  // and the two non-ruled companions come with it — and it is the COMPANION, not the ruling,
  // that catches one of these sides starting to refuse.
  'hz.eml': { kind: 'statefulCjk', python: () => false, node: false },
  'iso2022kr.eml': { kind: 'statefulCjk', python: () => false, node: false },
  // `<!ATTLIST>` defaults (H3): both READ, the row differs by one cell (`SHARED` / `0`).
  'attlist.xlsx': { kind: 'attlist', python: () => false, node: false },
};

const RULING_REASON = {
  pdf:
    'the reference reads PDF through `bantamkit.pdfread` and the port has no PDF reader yet ' +
    '(job44 ports it); `docread.ts` identifies the kind by `sniff` and refuses with "pdf is not ' +
    'readable by the Node server yet (the Python server reads it); see docs/porting.md". ' +
    'docs/porting.md, "pdf, doc and rtf on Node".',
  doc:
    'the reference reads a real OLE2 `.doc` through `/usr/bin/textutil`, a macOS built-in it ' +
    'probes at every call; the port shells out to nothing and refuses with "doc is read through ' +
    '/usr/bin/textutil by the Python server and not by the Node server; see docs/porting.md". ' +
    'The reference\'s own sentence differs by host (absent textutil / textutil says plain text), ' +
    'and the port\'s matches neither. docs/porting.md, "pdf, doc and rtf on Node".',
  rtf:
    'the reference reads RTF through `/usr/bin/textutil` where the host has it and refuses by ' +
    'name where it does not; the port always refuses with "rtf is read through /usr/bin/textutil ' +
    'by the Python server and not by the Node server; see docs/porting.md". ' +
    'docs/porting.md, "pdf, doc and rtf on Node".',
  utf7:
    'a MIME text part declaring `charset=utf-7` is decoded by the reference through CPython\'s ' +
    'codec registry, which has utf-7, so `+AOk-` becomes `é`; the port decodes through the WHATWG ' +
    'Encoding Standard\'s `TextDecoder`, whose registry deliberately has no utf-7, so the label ' +
    'is not recognised and the bytes are read as UTF-8: `+AOk-` stays `+AOk-`. Both sides READ ' +
    'the file to one row; the row differs by that one token. The port DOES carry CPython\'s ' +
    'single-byte tables since H2 (`runtime-ts/src/charsets.ts`, generated by ' +
    '`runtime-ts/scripts/charsets-table.py` and pinned against the live registry by the ' +
    '`charsets` suite), but utf-7 is a stateful modified-base64 transform, not a byte table, ' +
    'and no decoder for it is written; the label still falls to UTF-8. ' +
    'docs/porting.md, "utf-7 on Node".',
  statefulCjk:
    'a MIME text part declaring `charset=hz` or `charset=iso-2022-kr` is decoded by the ' +
    'reference through CPython\'s codec registry, which has both; the port decodes through ' +
    'the WHATWG Encoding Standard\'s `TextDecoder`, whose registry has neither label, so the ' +
    'bytes are read as UTF-8 and the escape machinery comes back as literal text. MEASURED ' +
    'on these two fixtures: `~{:O::~}` reads `合汉` on the reference and `~{:O::~}` here; ' +
    '`ESC $ ) C SO = " SI` reads `숱` there and `\\x1b$)C\\x0e="\\x0f` here. These are the ' +
    'same divergence as "utf-7 on Node" under two more names, and the same cause as the ' +
    'third: each is a STATEFUL escape transform, not a byte table, so ' +
    '`runtime-ts/src/charsets.ts` cannot carry it — H1 (`666f14f`) removed the seven tables ' +
    'the generator had written for exactly these codecs, when its statelessness probe was six ' +
    'hand-picked lead bytes containing neither ESC nor `~`. The decoder was chosen by ' +
    'measurement over 8,829 inputs against CPython (ICU 5,664 correct, byte table 5,021, ' +
    'utf-8 4,339); `hz`, `iso2022_kr` and `utf_7` score 0% through WHATWG, which is why six ' +
    'labels route to ICU and not nine. Writing three modified-escape decoders by hand is over ' +
    'the port budget, and no third-party dependency is allowed into runtime-ts. Both sides ' +
    'READ the file to one row; the row is the divergence. ' +
    'docs/porting.md, "hz and iso-2022-kr on Node".',
  attlist:
    'an internal DTD that declares a DEFAULT attribute value — `<!ATTLIST c t CDATA "s">` — ' +
    'is applied by the reference\'s expat, so a `<c>` written without `t` is a shared-string ' +
    'cell and `<v>0</v>` reads as `SHARED`; the port\'s hand-written internal-subset walk ' +
    '(`docread.ts` `parseDoctype`) reads `<!ENTITY>` declarations and skips `<!ATTLIST>` over ' +
    'its quoted strings, so the same cell is a number and reads `0`. Both sides READ the file ' +
    'to one row of one part; the row differs by that one cell. No OOXML writer emits an ' +
    'internal DTD, and applying defaults means carrying expat\'s attribute-declaration model ' +
    '(per-element, per-attribute, `#IMPLIED`/`#REQUIRED`/`#FIXED`) into a walk that exists ' +
    'to read four element names. docs/porting.md, "`<!ATTLIST>` defaults on Node".',
  bzip2:
    'a zip member stored with compression method 12 (bzip2) is read by the reference because ' +
    'CPython\'s `zipfile` decompresses it through the `bz2` module; the port decompresses ' +
    'through `node:zlib`, which has deflate and nothing else the zip format names, and no ' +
    'third-party dependency is allowed into runtime-ts (package.json has one runtime dep). The ' +
    'port names the member, the method number and its name: "<name> is a zip but its <member> ' +
    'uses compression method 12 (bzip2), which the Node server cannot decompress (the Python ' +
    'server reads it); see docs/porting.md". docs/porting.md, "bzip2 and lzma zip members on Node".',
  lzma:
    'a zip member stored with compression method 14 (lzma) is read by the reference because ' +
    'CPython\'s `zipfile` decompresses it through the `lzma` module; the port decompresses ' +
    'through `node:zlib`, which has no lzma, and no third-party dependency is allowed into ' +
    'runtime-ts. The port names the member, the method number and its name: "<name> is a zip ' +
    'but its <member> uses compression method 14 (lzma), which the Node server cannot decompress ' +
    '(the Python server reads it); see docs/porting.md". docs/porting.md, "bzip2 and lzma zip ' +
    'members on Node".',
  bzip2Styles:
    'an OPTIONAL zip member stored with compression method 12 (bzip2) costs BOTH runtimes only ' +
    'that member since review round 4 (M1) — but the two do not lose the same amount, because ' +
    'the member CARRIES something. `xl/styles.xml` here declares `yyyy-mm-dd` at the `cellXfs` ' +
    'index cell A1 uses; the reference decompresses it through `bz2`, resolves the style, and ' +
    'discloses the format as `number-format` (count 1, column A, `yyyy-mm-dd`), while ' +
    '`docread.ts` `dateFormats` catches the method-12 refusal as an unreadable optional member ' +
    'and answers no formats at all, so the omission list is empty. NEITHER side refuses and ' +
    'both read the same row `46235\\tok`: the divergence is entirely in what the caller is TOLD ' +
    'about that number, which in an `.xlsx` is the only thing separating a serial date from a ' +
    'plain one. Same cause as "bzip2 and lzma zip members on Node" — `node:zlib` has deflate ' +
    'and nothing else the zip format names, and runtime-ts may carry no new runtime dependency ' +
    '— and lifting it means the same bzip2 decoder that row waits on. Measured, not predicted: ' +
    '`deflate-date-styles.xlsx` is the SAME workbook with the SAME `xl/styles.xml` content (same ' +
    'CRC, same uncompressed size) behind method 8, and on it both runtimes emit the omission. ' +
    'docs/porting.md, "a bzip2 xl/styles.xml that carries date formats".',
  rfc2231:
    'a MIME text part whose charset arrives as RFC 2231 continuations (`charset*0=utf-8; ' +
    'charset*1=…`, or a `charset*=utf-8\'\'…` encoded value) is reassembled by the reference ' +
    'through `email.policy.default`\'s header parser, whose semantics are its own — `charset*1=x; ' +
    'charset*0=y` joins to `yx`, and a plain duplicate `charset=utf-8` LOSES to the continuation — ' +
    'so the part decodes as UTF-8 and reads `café au lait`; the port reads the plain `charset=` ' +
    'parameter only, sees no usable label, and decodes the same bytes as latin-1-through-UTF-8: ' +
    '`caf� au lait`. Both sides READ the file to one row. Porting `email`\'s parameter ' +
    'reassembly — with its ordering, its duplicate rule and its language tag — is far over the ' +
    'port budget for one row on one shape. docs/porting.md, "RFC 2231 charset continuations on Node".',
};

export async function run(ctx) {
  const fixtures = await import(pathToFileURL(join(repoRoot, 'runtime-ts', 'test', 'docread-fixtures.mjs')).href);
  const docread = await import(pathToFileURL(join(repoRoot, 'runtime-ts', 'dist', 'docread.js')).href);

  // ------------------------------------------------------------------------ the files

  const bed = join(ctx.scratch, 'docread');
  mkdirSync(bed, { recursive: true });
  const paths = fixtures.writeFixtures(bed);
  const extra = {
    'script.py': Buffer.from('#!/usr/bin/env python3\n"""A module."""\n\nimport sys\n\n\ndef main() -> int:\n    return len(sys.argv)\n', 'utf8'),
    'tiny.pdf': tinyPdf('Hello conformance'),
    'bad.rtf': Buffer.from('{\\rtf1\x00\x00\xff\xfe garbage', 'latin1'),
    'boundary.txt': fixtures.straddling(2),
    // A MIME text part that names a codec CPython has and WHATWG does not — the utf-7 ruling.
    'utf7.eml': Buffer.from('MIME-Version: 1.0\nContent-Type: text/plain; charset="utf-7"\nContent-Transfer-Encoding: 7bit\n\ncaf+AOk- done\n', 'latin1'),
    // THE `<!ATTLIST>` RULING (H3). An internal DTD that declares a DEFAULT for `c`'s `t`
    // attribute: `<!ATTLIST c t CDATA "s">`. The reference's expat applies the default, so a
    // `<c>` with no `t` is read as a shared-string cell and `<v>0</v>` resolves to `SHARED`;
    // the port's internal-subset walk skips `<!ATTLIST>`, so the same cell is a number and
    // reads `0`. Both sides READ the file to one row of one part — the utf-7 shape. No OOXML
    // writer emits an internal DTD, which is why this was a "gap" until a fixture showed it.
    'attlist.xlsx': fixtures.zipBytes([
      ['[Content_Types].xml', fixtures.CONTENT_TYPES],
      ['_rels/.rels', fixtures.ROOT_RELS],
      [
        'xl/worksheets/sheet1.xml',
        `<!DOCTYPE worksheet [<!ATTLIST c t CDATA "s">]><worksheet ${fixtures.SHEET_NS}><sheetData><row r="1"><c r="A1"><v>0</v></c><c r="B1" t="inlineStr"><is><t>plain</t></is></c></row></sheetData></worksheet>`,
      ],
      ['xl/workbook.xml', `<workbook ${fixtures.SHEET_NS} ${fixtures.REL_NS}><sheets><sheet name="Sales" sheetId="1" r:id="rId0"/></sheets></workbook>`],
      [
        'xl/_rels/workbook.xml.rels',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId0" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
      ],
      ['xl/sharedStrings.xml', `<sst ${fixtures.SHEET_NS} count="1" uniqueCount="1"><si><t>SHARED</t></si></sst>`],
    ]),
    // `<xmp>` holds raw text, and a 4301-digit character reference inside it — one over
    // CPython's `int()` digit limit — is kept as typed on both sides (H1 fixed the reference,
    // whose cap once rewrote the whole markup; the checked-in `charref-4301-digits.html` is
    // the `<p>` shape, where both sides cap to U+FFFD). Unruled.
    'xmp-charref-4301.html': Buffer.from(`<html><body><p>x</p><xmp>&#${'1'.repeat(4301)};</xmp><p>y</p></body></html>\n`, 'latin1'),
    // THE CHARSET TABLE, on a MIME part (H3, unruled). Three single-byte codecs the port now
    // decodes through `src/charsets.ts` — CPython's own tables, generated by
    // `runtime-ts/scripts/charsets-table.py` — over the five bytes `charset-table.json`
    // pins (80 D0 E9 A4 FF): cp437 (an IBM page, 0x80 is `Ç`), mac_roman (0x80 is `Ä`,
    // 0xA4 is `§`) and iso-8859-9 (Turkish, 0xD0 is `Ğ`). The `charsets` suite pins the whole
    // table; this pins the seam.
    //
    // QUOTED-PRINTABLE AND NOT `8bit`, WHICH IS A FIX (review round 4, I6). Sent `8bit`, the
    // five bytes sit RAW in the file, and `_text_kind` decodes the head through an incremental
    // UTF-8 decoder before it looks for a MIME header: `0x80 0xD0 0xE9 0xA4 0xFF` is not
    // valid UTF-8, `_decode_head` answers None, the container sniffs `unknown`, and BOTH
    // sides refuse the file with `it is not a recognised container; it starts with
    // b'MIME-Version'`. MEASURED, at `19a28fb`, on the fixture's own bytes:
    //
    //     sniff  -> Container(kind='unknown', what="not a recognised container; …")
    //     extract-> DocumentReadError, on the reference AND on the port
    //
    // So the two answers matched, the case was green, and no charset decoder was ever
    // reached — these fixtures pinned a refusal while claiming to pin a codec table. The same
    // bytes as `quoted-printable` leave the file ASCII, the head decodes, the part is found,
    // and the decoder gets the bytes: `x Ç╨Θñ  y` on both sides. That is the seam H3
    // meant to measure.
    ...Object.fromEntries(
      ['cp437', 'mac_roman', 'iso-8859-9'].map((label) => [
        `charset-${label}.eml`,
        Buffer.from(
          `MIME-Version: 1.0\nContent-Type: text/plain; charset="${label}"\n` +
            'Content-Transfer-Encoding: quoted-printable\n\nx =80=D0=E9=A4=FF y\n',
          'latin1',
        ),
      ]),
    ),
    // ---- review round 4, the fixes this round landed in BOTH runtimes, each pinned here
    //
    // M2 + M5 (`a1acfa7` Python, `4e56836` Node), one fixture because one answer. `ZZZZZ1`
    // is a syntactically valid cell reference whose column is 12,356,630 — over ECMA-376's
    // XFD (16,384). Before the round it materialised a 12,356,631-byte row from 1,393 bytes
    // of zip, an 8,870x amplification with no ceiling; before THAT it refused the whole
    // workbook. Now the clean cell keeps its column, the unplaceable one keeps its text and
    // loses only its column, and the loss is an OMISSION. Everything about that is compared
    // side to side by the generic loop below — the row, the row count, the omission list.
    'max-column.xlsx': fixtures.xlsxBytes([
      ['Sheet', 'worksheets/sheet1.xml', fixtures.row([fixtures.inlineCell('A1', 'ok'), fixtures.inlineCell('ZZZZZ1', 'over')])],
    ]),
    // The other side of the same ceiling: XFD is column 16,384 exactly, the last one the
    // format has, and it must still READ. A ceiling case without this one pins a refusal and
    // not a boundary.
    'xfd-column.xlsx': fixtures.xlsxBytes([
      ['Sheet', 'worksheets/sheet1.xml', fixtures.row([fixtures.inlineCell('A1', 'ok'), fixtures.inlineCell('XFD1', 'last')])],
    ]),
    // M4 (`15c7e04`): three charset labels whose CPython codec EXISTS and RAISES. `idna` and
    // `punycode` raise `UnicodeError` on these bytes and `undefined` raises on everything —
    // `_decoded_body` caught `LookupError` only, so the exception escaped the reader. Swept
    // over all 357 aliases in `encodings.aliases`: 22 raise `LookupError`, 3 raise
    // `UnicodeError`, the rest decode, so `UnicodeError` is the CLASS and not three names.
    // The port has no decoder for any of them and falls to UTF-8; the reference now answers
    // the same replacement characters, so this is PARITY and not a ruling — which is exactly
    // why it needs a case: nothing else would notice one side starting to raise again.
    // Quoted-printable for the reason spelled out at `charset-<label>.eml` above: sent
    // `8bit` the raw bytes make the HEAD undecodable, the file sniffs `unknown`, and both
    // sides refuse before any codec is consulted — a green case that measures nothing.
    ...Object.fromEntries(
      ['idna', 'punycode', 'undefined'].map((label) => [
        `charset-raises-${label}.eml`,
        Buffer.from(
          `MIME-Version: 1.0\nContent-Type: text/plain; charset="${label}"\n` +
            'Content-Transfer-Encoding: quoted-printable\n\nx =80=D0=E9=A4=FF y\n',
          'latin1',
        ),
      ]),
    ),
    // H1 (`666f14f`): `iso-2022-jp` is a STATEFUL codec, and the generator used to hand the
    // port a 256-character byte table for it because its statelessness probe was six
    // hand-picked lead bytes containing neither ESC (0x1B) nor `~`. The port then decoded
    // one byte at a time and answered `�$B$3$s$K$A$O�(B` where the reference
    // answers こんにちは. The generator now sweeps all 65,536 ordered pairs, the table is
    // gone, and the label reaches ICU's decoder. Both sides must read the same row.
    'iso2022jp.eml': Buffer.concat([
      Buffer.from('MIME-Version: 1.0\nContent-Type: text/plain; charset="iso-2022-jp"\nContent-Transfer-Encoding: 8bit\n\n', 'latin1'),
      Buffer.from([0x1b, 0x24, 0x42, 0x24, 0x33, 0x24, 0x73, 0x24, 0x4b, 0x24, 0x41, 0x24, 0x4f, 0x1b, 0x28, 0x42]),
      Buffer.from('\n', 'latin1'),
    ]),
    // The three labels H1 measured at 0% through the WHATWG registry, so the port reads them
    // as UTF-8 where the reference has a real codec. `utf_7` is already ruled on its own
    // fixture (`utf7.eml`); these two are the same divergence under different names and are
    // ruled below. `hz` marks its GB2312 run with `~{`…`~}`; `iso2022_kr` announces its
    // charset once with ESC $ ) C and then shifts in with SO (0x0E).
    'hz.eml': Buffer.concat([
      Buffer.from('MIME-Version: 1.0\nContent-Type: text/plain; charset="hz"\nContent-Transfer-Encoding: 8bit\n\n', 'latin1'),
      Buffer.from([0x7e, 0x7b, 0x3a, 0x4f, 0x3a, 0x3a, 0x7e, 0x7d]),
      Buffer.from('\n', 'latin1'),
    ]),
    'iso2022kr.eml': Buffer.concat([
      Buffer.from('MIME-Version: 1.0\nContent-Type: text/plain; charset="iso-2022-kr"\nContent-Transfer-Encoding: 8bit\n\n', 'latin1'),
      Buffer.from([0x1b, 0x24, 0x29, 0x43, 0x0e, 0x3d, 0x22, 0x0f]),
      Buffer.from('\n', 'latin1'),
    ]),
    // ---- job44 U1/U2, entry (w): a duplicate cell reference is DISCLOSED, last-wins kept
    //
    // `<c r="A1">…</c>` twice in one row used to yield the second silently, with ZERO
    // omissions on both runtimes — `docs/roadmap-toolbox.md` row 8 (w). Last-wins is what a
    // writer's own second cell means and is unchanged; the SILENCE is what was fixed.
    //
    // THE SHEET IS BUILT TO PIN THE ORDER AND NOT ONLY THE SENTENCE. A part's omissions are
    // emitted blank rows, then number formats by code, then unplaced cells by reason, then
    // duplicates — and "duplicates last" is a choice a differential cannot see, because both
    // runtimes make it together. So one sheet carries ALL FOUR at once:
    //
    //   row 1  `<c r="A1" s="1"><v>46235</v></c>` — a NUMBER FORMAT (`yyyy-mm-dd`, column A)
    //          `<c r="B1">bee</c>`                — an ordinary cell
    //          `<c r="A1">second</c>`             — the DUPLICATE, column A again
    //          `<c r="1">nowhere</c>`             — an UNPLACED cell (`1` is not letters+digits),
    //                                               which takes XML position 3, column D
    //   row 2  no cells at all                    — a BLANK ROW
    //   row 3  `A3` twice                         — a second duplicate, so `count` is 2 and not 1
    //
    // MEASURED on both runtimes 2026-09-06, and the literal below is that measurement: rows
    // `second\tbee\t\tnowhere`, ``, `y`, and four omissions in that order. The second duplicate
    // in row 3 is why `count` is 2: a count of 1 would be indistinguishable from a reader that
    // disclosed only the first duplicate it ever met.
    'duplicate-cell.xlsx': fixtures.xlsxBytes(
      [
        [
          'Dupes',
          'worksheets/sheet1.xml',
          fixtures.row(['<c r="A1" s="1"><v>46235</v></c>', fixtures.inlineCell('B1', 'bee'), fixtures.inlineCell('A1', 'second'), fixtures.inlineCell('1', 'nowhere')], 1) +
            fixtures.row([], 2) +
            fixtures.row([fixtures.inlineCell('A3', 'x'), fixtures.inlineCell('A3', 'y')], 3),
        ],
      ],
      { extra: { 'xl/styles.xml': fixtures.styles(['yyyy-mm-dd'], [0, 164]) } },
    ),
  };
  for (const [file, bytes] of Object.entries(extra)) {
    writeFileSync(join(bed, file), bytes);
    paths[file] = join(bed, file);
  }
  // The checked-in fixtures, read from where `runtime-py/tests/data/docread/` keeps them —
  // the same bytes both unit suites read, so nothing is rebuilt: `unicode-digit-shared-
  // string.xlsx` (an index `str.isdigit()` accepts and `int()` does not), `x-uuencode.eml`,
  // `rfc2231-charset.eml` (RULED), `rfc822-nested-twice.eml`, `internal-dtd-entity.docx`,
  // `charref-4301-digits.html`, `encrypted-member.docx`.
  // Round 3 (H1) added six more — `eszett-cell-ref.xlsx`, `compression-method-9.docx`,
  // `encrypted-mimetype.odt`, `bad-crc.docx`, `corrupt-deflate.docx`, `charset-table.json`.
  // A CHECKED-IN FIXTURE WINS over a built one of the same name, and WHICH NAMES IT MAY WIN
  // IS DECLARED, not discovered (review round 4, M8 / I3-F8).
  //
  // H3 turned a `throw` here into a `notes.push`, which was right — a throw stopped the whole
  // suite from starting over a name collision — but a note is not a gate. Any future
  // collision (someone checks in a `boundary.txt`, an `attlist.xlsx`, a `utf7.eml`) would
  // silently replace built bytes that exist to exercise a specific edge or back a specific
  // ruling, the run would stay green, and the note would scroll past: the same shrinking-gate
  // class as I3-F1 and I3-F7.
  //
  // So the shadow list is written down and COMPARED. The built duplicate cannot simply be
  // deleted from here: it is built by `runtime-ts/test/docread-fixtures.mjs`, which is the
  // runtime-ts layer and whose own unit tests read it. One name is declared today —
  // `corrupt-deflate.docx`, where the built copy and the checked-in one are both a corrupt
  // deflate stream over `word/document.xml` and the checked-in bytes are what both unit
  // suites read. The case below fails BOTH ways: an undeclared collision appears, or a
  // declared one stops happening and the declaration goes stale.
  const DECLARED_SHADOWS = ['corrupt-deflate.docx'];
  const notes = [];
  const shadowed = [];
  for (const [file, path] of Object.entries(fixtures.checkedInFixtures())) {
    if (paths[file] !== undefined) shadowed.push(file);
    paths[file] = path;
  }
  shadowed.sort();
  const shadowCase = {
    name: 'fixtures: exactly the declared checked-in fixtures shadow a built one of the same name',
    kind: 'json',
    expected: DECLARED_SHADOWS,
    actual: shadowed,
  };
  notes.push(
    `checked-in fixtures shadowing a built one: ${shadowed.length ? shadowed.join(', ') : '(none)'}; ` +
      `declared: ${DECLARED_SHADOWS.join(', ')}. the checked-in bytes are what is compared, and the ` +
      'list is a case, not a note — an undeclared collision fails the suite',
  );
  // A NUL inside the file name: `a\x00b`. The reference's `Path.stat` raises `ValueError`
  // ("embedded null byte"), which `docread` answers as `no such file: a\x00b`; the port's
  // `fs.statSync` raises `ERR_INVALID_ARG_VALUE`, answered with the same sentence. Job43 G3
  // measured it on macOS only; the case is NOT skipped on win32 (where CPython raises the
  // same `ValueError`), so a Windows run measures it itself, and the note names the platform.
  paths['nul-in-name'] = 'a\x00b';
  notes.push(`a NUL inside a file name (a\\x00b) measured on ${process.platform}; win32 name functions cannot run on a POSIX host, so a Windows answer is only known from a Windows run`);
  // THE PATHS THAT ARE NOT FILES, handed to both readers as the caller typed them. `''` is
  // `Path('')`, which is `.`, the harness's cwd, a directory; `a/b/.` is `Path('a/b/.')`, which
  // `pathlib` collapses to `a/b` BEFORE the file is looked for, so the sentence names `a/b`
  // and not what was typed — both resolve against the same cwd because `run.mjs` spawns the
  // reference in its own. `/dev/zero` is a character device that reads as endless NULs and
  // stats as 0 bytes: the sniff must name the first twelve bytes and stop there rather than
  // read to an end that never comes. It has no Windows counterpart, so it is skipped there.
  paths['empty-path'] = '';
  paths['dot-tail'] = 'a/b/.';
  if (process.platform === 'win32') {
    notes.push('/dev/zero has no Windows counterpart; the character-device sniff is NOT MEASURED HERE');
  } else {
    paths['dev-zero'] = '/dev/zero';
  }
  // The host's own `ls`: a Mach-O on macOS, an ELF on Linux, a PE on Windows CI where it
  // is `C:\Program Files\Git\usr\bin\ls.exe` or absent. Whatever it is, it is a real binary
  // neither side should mistake for text, and both must name the same first twelve bytes.
  const lsCandidates = ['/bin/ls', '/usr/bin/ls', 'C:\\Program Files\\Git\\usr\\bin\\ls.exe'];
  const ls = lsCandidates.find((p) => existsSync(p));
  if (ls !== undefined) {
    copyFileSync(ls, join(bed, 'ls.bin'));
    paths['ls.bin'] = join(bed, 'ls.bin');
  } else {
    notes.push('no `ls` binary found on this host; the Mach-O/ELF fixture is NOT MEASURED HERE');
  }

  const names = Object.keys(paths).sort();

  // ------------------------------------------- the fixtures that STRADDLE A CEILING
  //
  // Six files built HERE, in harness scratch, and deleted with it. They are not in `paths`
  // and are not checked in, for two different reasons that both come to the same place.
  //
  // WHY THEY ARE GENERATED AND NOT COMMITTED — and this is what closes register entry (p).
  // `docs/porting.md` records that the 300,000-cell row "has no conformance fixture: the
  // smallest deflated xlsx that shows it is 1,501,739 bytes, over the 1 MB ceiling". That
  // ceiling is a rule about what is CHECKED IN — it appears nowhere in a gate, a hook or a
  // `.gitattributes`; it is a convention `docs/porting.md` states in prose, and the largest
  // file under `runtime-py/tests/data/docread/` is 4,342 bytes. Nothing forbids a suite from
  // BUILDING a large fixture, and this repository already does: `runtime-ts/test/docread.
  // test.mjs:304` writes exactly this workbook into a temp dir on every run. So the entry was
  // never blocked on the reader — it was blocked on the git tree, and building the same bytes
  // in `ctx.scratch` costs the run 0.7 s and the repository nothing. Measured here: the file
  // is 1,501,741 bytes, two bytes off the number the register recorded (the sheet name).
  //
  // WHY A CEILING CANNOT BE STRADDLED BY A SMALL FILE. `TEXT_MAX_BYTES` and
  // `XLSX_MAX_TEXT_BYTES` are both 16 MiB, so a fixture that shows either one biting has to
  // be over 16 MiB of file or 16 MiB of rendering. There is no smaller input; that is what a
  // ceiling means.
  //
  // THEY GO THROUGH `summaries` AND NOT `paths`. The reference's `summaries` route replaces
  // each part's rows with their SHA-256, their count and the first 120 characters of the
  // first and last row, so the comparison still covers every rendered byte and every omission
  // verbatim without pushing 16 MiB across the pipe twice. See `ref/docread_ref.py`.
  const SUMMARISED = {};
  const summarise = (file, bytes) => {
    writeFileSync(join(bed, file), bytes);
    SUMMARISED[file] = join(bed, file);
  };
  // The workbook budget's rows, `XFD` and all: one `A<n>` cell of `ok` and one `XFD<n>` cell
  // of `v0000`, which is 16,384 fields — 2 + 16,383 tabs + 5 = 16,390 bytes — the SAME width
  // for every row, so what the budget does is arithmetic and not a transcript. 16,777,216 /
  // 16,390 = 1023.6, and a row is rendered whole or not at all, so 1,024 rows render and the
  // 1,025th is the first to be dropped.
  const budgetRows = (n) => {
    let out = '';
    for (let i = 1; i <= n; i += 1) {
      out += fixtures.row([fixtures.inlineCell(`A${i}`, 'ok'), fixtures.inlineCell(`XFD${i}`, `v${String(i).padStart(4, '0')}`)], i);
    }
    return out;
  };
  // (v) The document-level materialisation budget, over it by 73 rows AND carrying media, so
  // the ORDER of the two document omissions is pinned as well as the sentence: the cap is
  // stated BEFORE the media tally, because the media a reader met is a count of what it met
  // underneath the cap. 1,097 is deliberately not a round number and not a multiple of
  // anything the reader computes.
  summarise(
    'xlsx-over-budget.xlsx',
    fixtures.xlsxBytes([['Wide', 'worksheets/sheet1.xml', budgetRows(1097)]], {
      deflate: true,
      extra: fixtures.mediaPack({ 'worksheets/sheet1.xml': ['shot.png', 'logo.gif'] }),
    }),
  );
  // (v)'s BOUNDARY, both sides of it, one row apart. Without these the cap case pins a
  // refusal and not a ceiling: a reader that had stopped rendering rows at all, or one whose
  // threshold had moved by a row, would keep the case above green. 1,024 rows must render
  // WHOLE with no omission; 1,025 must drop exactly one.
  summarise('xlsx-at-budget.xlsx', fixtures.xlsxBytes([['Wide', 'worksheets/sheet1.xml', budgetRows(1024)]], { deflate: true }));
  summarise('xlsx-one-over-budget.xlsx', fixtures.xlsxBytes([['Wide', 'worksheets/sheet1.xml', budgetRows(1025)]], { deflate: true }));
  // (k) html and mhtml read to `TEXT_MAX_BYTES` and count the rest, the way plain text has
  // since J10. Both were `read_bytes()` / `readFileSync` — a 1 GB `.html` held whole.
  //
  // The padding is one unbroken run of a single byte INSIDE `<pre>` (html) or inside the one
  // text part's body (mhtml), so the truncation lands in the middle of that run on both
  // runtimes and neither has to agree with the other about half a tag. The two overshoots are
  // different numbers on purpose — 4,321 and 2,749 — because the sentence interpolates the
  // file's size and a shared constant would let one side's arithmetic hide inside the other's.
  const TEXT_MAX_BYTES = 16 * 1024 * 1024;
  const HTML_HEAD = '<html><body><p>alpha</p><pre>';
  const MHT_HEAD = 'MIME-Version: 1.0\nContent-Type: text/plain; charset="utf-8"\nContent-Transfer-Encoding: 8bit\n\nalpha\n';
  const padded = (head, over, byte) =>
    Buffer.concat([Buffer.from(head, 'latin1'), Buffer.alloc(TEXT_MAX_BYTES - head.length + over, byte)]);
  summarise('html-over-ceiling.html', padded(HTML_HEAD, 4321, 0x78));
  summarise('mhtml-over-ceiling.mht', padded(MHT_HEAD, 2749, 0x79));
  // (k)'s BOUNDARY: a file of EXACTLY `TEXT_MAX_BYTES` is read whole and says nothing. A cap
  // that fired here would be a reader that truncates every file and admits it, which is not
  // the behaviour (k) asked for.
  summarise('html-at-ceiling.html', padded(HTML_HEAD, 0, 0x78));
  // (p) The 300,000-cell row. `Math.max(...cells.keys())` over 300k keys is a `RangeError:
  // Maximum call stack size exceeded`, fixed in round 3 (H2) and held since by
  // `runtime-ts/test/docread.test.mjs:304` alone — one runtime's unit test, comparing nothing.
  // Every reference past `XFD` is unplaceable and keeps its XML position, so the row is
  // 300,000 fields wide and 283,616 of them are disclosed as `unplaced-cell`.
  {
    let cells = '';
    for (let i = 0; i < 300000; i += 1) cells += `<c r="${columnLetter(i)}1" t="inlineStr"><is><t>v${i}</t></is></c>`;
    summarise('wide-row.xlsx', fixtures.xlsxBytes([['Wide', 'worksheets/sheet1.xml', `<row r="1">${cells}</row>`]], { deflate: true }));
  }
  const summaryNames = Object.keys(SUMMARISED).sort();

  // ------------------------------------------------------------------------ the pages

  const p = paths['p.xlsx'];
  const pages = [
    { name: 'first window, defaults', path: p, part: 'data' },
    { name: 'second window', path: p, part: 'data', offset: 50, limit: 50 },
    { name: 'last window, next_offset null', path: p, part: 'data', offset: 100, limit: 50 },
    { name: 'the 200-row ceiling', path: p, part: 'data', offset: 0, limit: 200 },
    { name: 'limit above the ceiling is the caller\'s to clamp', path: p, part: 'data', offset: 0, limit: 900 },
    { name: 'offset past the end is an empty window, not a refusal', path: p, part: 'data', offset: 500, limit: 10 },
    { name: 'part by index string', path: p, part: '0', offset: 118, limit: 5 },
    { name: 'part by index number', path: p, part: 1 },
    { name: 'an empty part', path: p, part: 'other' },
    { name: 'a name that is not a part', path: p, part: 'Nope' },
    { name: 'an index that is not a part', path: p, part: '2' },
    { name: 'a negative index', path: p, part: '-1' },
    { name: 'a doubly-negative index — the reference leaked int()\'s ValueError here', path: p, part: '--1' },
    { name: 'a signed index', path: p, part: '+1' },
    { name: 'an index with spaces', path: p, part: ' 1 ' },
    { name: 'an index with an underscore', path: p, part: '1_0' },
    { name: 'a non-ASCII digit is a name, not an index', path: p, part: '\u0661' },
    { name: 'a superscript digit — isdigit() said yes and int() said no', path: p, part: '\u00b2' },
    // JSON spellings handed as part NAMES: the library sees the string, never unwraps it,
    // and answers the unknown-part sentence on both sides. The same three on the wire are
    // the `read-round2` session in wire.mjs.
    { name: 'the string "null" is a name that is not a part', path: p, part: 'null' },
    { name: 'the string "[1]" is a name that is not a part, not an index', path: p, part: '[1]' },
    { name: 'the string "{}" is a name that is not a part', path: p, part: '{}' },
    { name: 'offset below zero', path: p, part: 'data', offset: -1, limit: 5 },
    { name: 'limit zero', path: p, part: 'data', offset: 0, limit: 0 },
    { name: 'one row over the byte ceiling is cut to fit', path: paths['long.xlsx'], part: 'data', offset: 0, limit: 50, max_bytes: 3072 },
    { name: 'the row after the cut one', path: paths['long.xlsx'], part: 'data', offset: 1, limit: 50, max_bytes: 3072 },
    { name: 'a window that stops on a row boundary under the ceiling', path: paths['plain.md'], part: 'document', offset: 0, limit: 50, max_bytes: 12 },
    { name: 'a markdown body, two rows', path: paths['plain.md'], part: 'document', offset: 0, limit: 2 },
    { name: 'a docx body', path: paths['d.docx'], part: 'document', offset: 1, limit: 1 },
    { name: 'an unreadable file has no page', path: paths['pic.png'], part: 'document' },
    { name: 'a missing file has no page', path: paths['missing.txt'], part: 'document' },
    // 4301 digits is one over CPython's default `int()` conversion limit (sys.int_info.
    // str_digits_check_threshold, 4300): the reference once let that `ValueError` escape as
    // a different sentence from `--1`'s. Now it is a name that is not a part, on both sides.
    { name: 'a 4301-digit key is a name that is not a part, not an int() limit error', path: p, part: '1'.repeat(4301) },
    // 2**53 is the largest offset the wire schema admits (`maximum: 9007199254740991` is
    // 2**53 - 1; the value here is one past it, so the LIBRARY is what is being asked). The
    // library answers an empty window and `next_offset: null` on both sides; the schema
    // refusal for the same number on the wire is the `read-edges` session in wire.mjs.
    { name: 'offset 2**53 at the library is an empty window on both sides, not a refusal', path: p, part: 'data', offset: 2 ** 53, limit: 50 },
  ];

  // ------------------------------------------------------------------- the two sides

  const python = ctx.runPython(REF, {
    paths: names.map((n) => paths[n]),
    summaries: summaryNames.map((n) => SUMMARISED[n]),
    pages: pages.map(({ name: _n, ...spec }) => spec),
  });

  // `e.name` before the constructor: the port's `PyOSError` carries CPython's class name
  // (`OSError`, `NotADirectoryError`, …) in `name`, and `badcd.xlsx` — an EOCD whose central
  // directory offset points past the file — is refused as `OSError` on both sides. Measured
  // before this line: 2 of 633 differed on the constructor's name alone.
  const errorOf = (e) => ({ error: { type: e?.name ?? e?.constructor?.name ?? 'Error', message: String(e?.message ?? e) } });
  const container = (c) => ({ kind: c.kind, what: c.what, named: c.named, suffix_lies: c.suffixLies });
  const document = (doc) => ({
    kind: doc.kind,
    text_bytes: doc.textBytes,
    parts: doc.parts.map((part) => ({
      name: part.name,
      index: part.index,
      row_count: part.rowCount,
      text_bytes: part.textBytes,
      rows: [...part.rows],
      omissions: part.omissions.map((o) => o.asDict()),
    })),
    omissions: doc.omissions.map((o) => o.asDict()),
  });
  const pageOf = (pg) => ({
    part: pg.part,
    offset: pg.offset,
    rows: [...pg.rows],
    total_rows: pg.totalRows,
    next_offset: pg.nextOffset,
    truncated_bytes: pg.truncatedBytes,
  });
  const attempt = (fn) => {
    try {
      return fn();
    } catch (e) {
      return errorOf(e);
    }
  };
  /**
   * `document()` with each part's rows replaced by their digest, count and edges.
   *
   * The port's half of `ref/docread_ref.py`'s `_summary`, field for field and in the same
   * spelling, so the two are compared as one JSON object. `head`/`tail` slice by CODE POINT
   * (`[...row]`) and not by UTF-16 unit, because CPython's `row[:120]` counts code points and
   * a `slice(0, 120)` here would cut a surrogate pair in half on one side only.
   */
  const summary = (doc) => ({
    kind: doc.kind,
    text_bytes: doc.textBytes,
    parts: doc.parts.map((part) => {
      const joined = [...part.rows].join('\n');
      return {
        name: part.name,
        index: part.index,
        row_count: part.rowCount,
        text_bytes: part.textBytes,
        rows: part.rows.length,
        rows_bytes: Buffer.byteLength(joined, 'utf8'),
        rows_sha256: createHash('sha256').update(joined, 'utf8').digest('hex'),
        head: part.rows.length ? [...part.rows[0]].slice(0, 120).join('') : null,
        tail: part.rows.length ? [...part.rows[part.rows.length - 1]].slice(0, 120).join('') : null,
        omissions: part.omissions.map((o) => o.asDict()),
      };
    }),
    omissions: doc.omissions.map((o) => o.asDict()),
  });
  const node = {
    files: names.map((n) => ({
      sniff: attempt(() => container(docread.sniff(paths[n]))),
      extract: attempt(() => document(docread.extract(paths[n]))),
    })),
    summaries: summaryNames.map((n) => ({
      sniff: attempt(() => container(docread.sniff(SUMMARISED[n]))),
      extract: attempt(() => summary(docread.extract(SUMMARISED[n]))),
    })),
    pages: pages.map((spec) =>
      attempt(() => ({
        page: pageOf(
          docread.page(
            docread.extract(spec.path),
            spec.part ?? 0,
            spec.offset ?? 0,
            spec.limit ?? docread.DEFAULT_ROW_LIMIT,
            spec.max_bytes ?? null,
          ),
        ),
      })),
    ),
  };

  // ------------------------------------------------------------------------- the cases

  const cases = [shadowCase];
  const refused = (answer) => Boolean(answer.error);
  let ruled = 0;
  let readBoth = 0;
  let refusedBoth = 0;

  names.forEach((n, i) => {
    const py = python.files[i];
    const nd = node.files[i];
    // `sniff` agrees on every file, the ruled ones included: identifying a PDF is not
    // reading one, and the ruling below is about what happens AFTER the kind is known.
    cases.push({ name: `sniff: ${n}: kind`, kind: 'bytes', expected: py.sniff.kind ?? py.sniff.error?.message, actual: nd.sniff.kind ?? nd.sniff.error?.message });
    cases.push({ name: `sniff: ${n}`, kind: 'json', expected: py.sniff, actual: nd.sniff });

    const rule = RULED[n];
    if (rule !== undefined) {
      ruled += 1;
      cases.push({
        name: `extract: ${n}: ${rule.kind} is RULED`,
        kind: 'json',
        expected: py.extract,
        actual: nd.extract,
        ruling: RULING_REASON[rule.kind],
      });
      // THE COMPANIONS. A ruling only proves the two answers differ; these say what each
      // answer IS. First the bit each side is required to have, as a literal from the table
      // above — the case that says which side is RIGHT and would fail if the port started
      // reading a PDF by accident or the reference stopped. Then, where both refuse, the
      // bare bit compared side to side, the non-ruled companion CLAUDE.md requires.
      const expectedBits = { python: rule.python(python.textutil), node: rule.node ?? true };
      cases.push({
        name: `extract: ${n}: the refusal bit each side is required to carry`,
        kind: 'json',
        expected: expectedBits,
        actual: { python: refused(py.extract), node: refused(nd.extract) },
      });
      if (expectedBits.python && expectedBits.node) {
        cases.push({
          name: `extract: ${n}: both refuse (the refusal bit, side to side)`,
          kind: 'json',
          expected: refused(py.extract),
          actual: refused(nd.extract),
        });
        refusedBoth += 1;
      } else if (!expectedBits.python && expectedBits.node && rule.reads !== undefined) {
        // The bzip2/lzma shape: the reference READS, the port refuses. The literal above
        // says which side must do which; these two say WHAT each side must answer, so a
        // reference that stopped reading to `hello` or a port whose sentence lost the
        // method number would fail on its own line rather than behind "they still differ".
        cases.push({
          name: `extract: ${n}: the reference reads the row as measured (\`${rule.reads.join('\\n')}\`)`,
          kind: 'bytes',
          expected: rule.reads.join('\n'),
          actual: (py.extract.parts ?? []).flatMap((x) => x.rows).join('\n'),
        });
        cases.push({
          name: `extract: ${n}: the port refuses in the sentence the ruling quotes`,
          kind: 'bytes',
          expected: rule.sentence,
          actual: `${nd.extract.error?.type}: ${nd.extract.error?.message}`,
        });
      } else if (!expectedBits.python && !expectedBits.node) {
        // The utf-7 shape: a ruling over two READS. The companion pins that neither side
        // refuses, side to side, and that they agree on everything but the decoded row —
        // the part count, the row count, the kind — so a port that started refusing the
        // label, or reading a second part, fails here and not behind the ruling.
        cases.push({
          name: `extract: ${n}: both read (the refusal bit, side to side)`,
          kind: 'json',
          expected: refused(py.extract),
          actual: refused(nd.extract),
        });
        cases.push({
          name: `extract: ${n}: the same shape around the ruled row (kind, parts, row counts, omissions)`,
          kind: 'json',
          expected: { kind: py.extract.kind, parts: (py.extract.parts ?? []).map((x) => [x.name, x.index, x.row_count, x.rows?.length]), omissions: py.extract.omissions },
          actual: { kind: nd.extract.kind, parts: (nd.extract.parts ?? []).map((x) => [x.name, x.index, x.row_count, x.rows?.length]), omissions: nd.extract.omissions },
        });
        // A ruling whose divergence is an OMISSION and not a row needs the same treatment
        // `reads`/`sentence` give the bzip2/lzma pair: the refusal bit says neither side
        // refuses, and the shape case above compares only DOCUMENT omissions, so without
        // these two the whole divergence would live inside the ruling — where a passing
        // comparison is reported as stale rather than as a side that changed. Each of these
        // is NON-RULED: one names what the reference must disclose, one names that the port
        // discloses nothing, and a port that grew a bzip2 decoder reddens the second.
        if (rule.discloses !== undefined) {
          cases.push({
            name: `extract: ${n}: the reference discloses what the unreachable member carries, as measured`,
            kind: 'json',
            expected: rule.discloses,
            actual: (py.extract.parts ?? []).flatMap((x) => x.omissions),
          });
          cases.push({
            name: `extract: ${n}: the port discloses nothing, because the member holding it is method 12`,
            kind: 'json',
            expected: [],
            actual: (nd.extract.parts ?? []).flatMap((x) => x.omissions),
          });
        }
        readBoth += 1;
      }
      // The port's refusal still names the container, the size and the suffix disagreement
      // the way `_refuse` does: everything before the remedy is the reference's sentence.
      const head = (text) => (text ?? '').split('. ')[0];
      if (refused(py.extract) && refused(nd.extract) && py.extract.error.type === 'DocumentReadError' && py.extract.error.message.startsWith('cannot read ') && !py.extract.error.message.includes('textutil')) {
        cases.push({
          name: `extract: ${n}: the refusal names the same container, size and suffix before the remedy`,
          kind: 'bytes',
          expected: head(py.extract.error.message),
          actual: head(nd.extract.error.message),
        });
      }
      return;
    }

    cases.push({ name: `extract: ${n}`, kind: 'json', expected: py.extract, actual: nd.extract });
    // The refusal BIT, on its own, beside the bytes: the whole-answer case above fails on a
    // word, this one fails only when one side reads what the other refuses — the difference
    // that matters to a caller, kept visible as its own line in the report.
    cases.push({ name: `extract: ${n}: the refusal bit (side to side)`, kind: 'json', expected: refused(py.extract), actual: refused(nd.extract) });
    if (refused(py.extract) || refused(nd.extract)) {
      cases.push({
        name: `extract: ${n}: the refusal sentence`,
        kind: 'bytes',
        expected: `${py.extract.error?.type}: ${py.extract.error?.message}`,
        actual: `${nd.extract.error?.type}: ${nd.extract.error?.message}`,
      });
      if (refused(py.extract) && refused(nd.extract)) refusedBoth += 1;
      return;
    }
    readBoth += 1;
    (py.extract.parts ?? []).forEach((part, k) => {
      const other = nd.extract.parts?.[k];
      cases.push({
        name: `extract: ${n}: part ${JSON.stringify(part.name)} rows`,
        kind: 'bytes',
        expected: part.rows.join('\n'),
        actual: (other?.rows ?? ['<no such part on the node side>']).join('\n'),
      });
      cases.push({
        name: `extract: ${n}: part ${JSON.stringify(part.name)} omissions`,
        kind: 'json',
        expected: part.omissions,
        actual: other?.omissions ?? null,
      });
    });
    cases.push({
      name: `extract: ${n}: document omissions`,
      kind: 'json',
      expected: py.extract.omissions,
      actual: nd.extract.omissions,
    });
  });

  // ------------------------------ the bzip2-styles ruling's CONTROL, as a LITERAL (U17)
  //
  // `bzip2-date-styles.xlsx` is ruled above because the reference discloses a `number-format`
  // the port cannot reach. That ruling is only worth something while the INPUT can still show
  // the difference — and a differential cannot check that on its own, because a reader that
  // stopped resolving date styles altogether would leave both sides silent, the ruled
  // comparison would start MATCHING (reported as a stale ruling, i.e. as good news), and the
  // two non-ruled companions would both read `[]`. That is the shape three parity bugs already
  // survived in this repo: the example chosen was the one where both sides agree.
  //
  // So the control is pinned as a literal on BOTH sides. `deflate-date-styles.xlsx` is the same
  // workbook, the same sheet, and the same `xl/styles.xml` CONTENT — same CRC 0x7e197e5f, same
  // 225 uncompressed bytes — behind method 8 instead of 12. One field of one header is the only
  // difference between the two files, so if this case is green and the ruled one differs, the
  // method is the only thing the difference can be.
  {
    const control = names.indexOf('deflate-date-styles.xlsx');
    const disclosed = [{ subject: 'number-format', count: 1, size: 0, where: ['A'], what: 'yyyy-mm-dd', facts: {} }];
    const omissionsOf = (answer) => (answer.extract.parts ?? []).flatMap((part) => part.omissions);
    cases.push({
      name: 'the bzip2-styles ruling has a control: the same styles behind method 8 make BOTH sides disclose',
      kind: 'json',
      expected: { python: disclosed, node: disclosed },
      actual: {
        python: omissionsOf(python.files[control]),
        node: omissionsOf(node.files[control]),
      },
    });
  }
  notes.push(
    'the bzip2 `xl/styles.xml` ruling is controlled: `deflate-date-styles.xlsx` carries the same ' +
      'styles bytes (CRC 0x7e197e5f, 225 B) behind method 8 and both sides disclose `yyyy-mm-dd` ' +
      'on it, so the ruled file\'s silence on the port is the method and not the input',
  );

  // ------------------------------------------------- the column ceiling, as a LITERAL
  //
  // M2 + M5 landed in BOTH runtimes in the same job (`a1acfa7` Python, `4e56836` Node), and
  // that is exactly what a differential cannot see: reverting both halves to `952586e` leaves
  // the two sides AGREEING that the workbook is unreadable, and every case above stays green.
  // MEASURED — a copy of this tree with both `docread` files reverted to `952586e` reddened
  // `bzip2-optional-styles.xlsx`, `charset-raises-*.eml` and `iso2022jp.eml`, and did NOT
  // redden `max-column.xlsx`, because a joint regression is a match.
  //
  // So the answer is pinned as a LITERAL on each side, the way `wire.mjs` pins its sentences
  // and `memorycli.mjs` now pins its eviction order. Three facts in one case, all three of
  // them the fix: the workbook READS, the unplaceable cell keeps its TEXT at its XML position
  // (`ok\tover`, column B — round 3 refused the document for it, and before round 3 it was
  // placed at column 12,356,630 and materialised a 12,356,631-byte row from 1,393 bytes of
  // zip), and the loss of its column is DISCLOSED. The reason string is fixed text and never
  // interpolates `r`, which is attacker-controlled.
  {
    const at = (side, file) => side.files[names.indexOf(file)]?.extract ?? null;
    const shapeOf = (answer) => ({
      refused: Boolean(answer?.error),
      rows: (answer?.parts ?? []).flatMap((p) => p.rows),
      omissions: (answer?.parts ?? []).flatMap((p) => p.omissions),
    });
    const overXfd = {
      refused: false,
      rows: ['ok\tover'],
      omissions: [
        {
          subject: 'unplaced-cell',
          count: 1,
          size: 0,
          where: ['B'],
          what: 'the column of a cell past XFD, the last column the format has',
          // `{}` and not `[]`: an omission's `facts` is a MAPPING on both sides, and it is
          // empty here because the reason string carries no interpolated value — `r` is
          // attacker-controlled and the pre-round-4 error interpolated it unbounded.
          facts: {},
        },
      ],
    };
    cases.push({
      name: 'extract: max-column.xlsx: a cell past XFD costs its column and not the workbook, as a literal on each side',
      kind: 'json',
      expected: { python: overXfd, node: overXfd },
      actual: { python: shapeOf(at(python, 'max-column.xlsx')), node: shapeOf(at(node, 'max-column.xlsx')) },
    });
    // The boundary itself, as a literal: XFD is column 16,384, the LAST one ECMA-376 has, and
    // it must still be placed. A ceiling case without this one pins a refusal and not a
    // boundary — a port that clamped one column too low would keep every case above green.
    // The row is measured by its cell COUNT rather than spelled out, because spelling it out
    // means 16,383 tab characters in a source file.
    const lastColumn = { refused: false, cells: 16384, first: 'ok', last: 'last', omissions: [] };
    const boundaryOf = (answer) => {
      const rows = (answer?.parts ?? []).flatMap((p) => p.rows);
      const cells = rows.length === 1 ? rows[0].split('\t') : null;
      return {
        refused: Boolean(answer?.error),
        cells: cells?.length ?? null,
        first: cells?.[0] ?? null,
        last: cells?.[cells.length - 1] ?? null,
        omissions: (answer?.parts ?? []).flatMap((p) => p.omissions),
      };
    };
    cases.push({
      name: 'extract: xfd-column.xlsx: XFD is column 16,384 and still places, as a literal on each side',
      kind: 'json',
      expected: { python: lastColumn, node: lastColumn },
      actual: { python: boundaryOf(at(python, 'xfd-column.xlsx')), node: boundaryOf(at(node, 'xfd-column.xlsx')) },
    });
  }

  // ------------------------------ the three ceilings, side to side AND as literals (U3)
  //
  // Register entries (v), (k) and (p), plus (w) below. Every one of them landed in BOTH
  // runtimes in this job, which is precisely the shape a differential cannot see: revert both
  // halves and the two sides agree that there is no ceiling, and every case in this section
  // that only compared Python to Node would stay green. So each fixture gets TWO kinds of
  // case — the side-to-side comparison, which catches one runtime drifting, and a LITERAL
  // pinned on each side, which catches both drifting together.
  {
    summaryNames.forEach((n, i) => {
      const py = python.summaries[i];
      const nd = node.summaries[i];
      cases.push({ name: `summary: ${n}: sniff`, kind: 'json', expected: py.sniff, actual: nd.sniff });
      cases.push({ name: `summary: ${n}: extract (rows by digest, omissions verbatim)`, kind: 'json', expected: py.extract, actual: nd.extract });
    });
    const at = (name_) => {
      const i = summaryNames.indexOf(name_);
      return { python: python.summaries[i]?.extract ?? null, node: node.summaries[i]?.extract ?? null };
    };
    /** `{refused, rows, docOmissions}` — what a ceiling case is actually about. */
    const capShape = (answer) => ({
      refused: Boolean(answer?.error),
      rows: (answer?.parts ?? []).map((p) => p.row_count),
      docOmissions: answer?.omissions ?? null,
    });
    const bothSides = (name_, expected, pick = capShape) => {
      const sides = at(name_);
      cases.push({
        name: `extract: ${name_}: ${expected.label}`,
        kind: 'json',
        expected: { python: expected.value, node: expected.value },
        actual: { python: pick(sides.python), node: pick(sides.node) },
      });
    };

    // (v) The workbook budget, well over it, WITH media — so the cap's own sentence and the
    // ORDER of the two document omissions are both pinned. `count` is the rows no sheet
    // rendered (73) and `what` names what they are a fraction OF (1,097). MEASURED 2026-09-06
    // on both runtimes; the arithmetic that predicts it is at `budgetRows` above.
    const MEDIA = { subject: 'media', count: 2, size: 200, where: [], what: 'gif, png', facts: {} };
    bothSides('xlsx-over-budget.xlsx', {
      label: 'the workbook budget bites, the shortfall is 73 of 1,097 rows, and the cap is stated BEFORE the media',
      value: {
        refused: false,
        rows: [1024],
        docOmissions: [
          {
            subject: 'size-cap',
            count: 73,
            size: 0,
            where: [],
            what: '1097 rows in this workbook; this reader renders 16777216 bytes of cell text',
            facts: {},
          },
          MEDIA,
        ],
      },
    });
    // The boundary, one row apart. 1,024 rows of 16,390 bytes is 16,783,360 — already past
    // 16,777,216 — and still renders WHOLE, because a row is rendered or dropped and never
    // cut; the 1,025th is the first the budget refuses.
    bothSides('xlsx-at-budget.xlsx', {
      label: '1,024 rows is the last workbook that renders whole and says nothing',
      value: { refused: false, rows: [1024], docOmissions: [] },
    });
    bothSides('xlsx-one-over-budget.xlsx', {
      label: '1,025 rows drops exactly one, and the count is the row and not the byte',
      value: {
        refused: false,
        rows: [1024],
        docOmissions: [
          {
            subject: 'size-cap',
            count: 1,
            size: 0,
            where: [],
            what: '1025 rows in this workbook; this reader renders 16777216 bytes of cell text',
            facts: {},
          },
        ],
      },
    });
    // (k) html and mhtml now stop where plain text stops, and say how much they did not read.
    // The two files are different sizes on purpose: the sentence interpolates the size, so a
    // shared number would let one side's arithmetic hide inside the other's.
    bothSides('html-over-ceiling.html', {
      label: 'markup is read to TEXT_MAX_BYTES and the 4,321 bytes past it are disclosed',
      value: {
        refused: false,
        rows: [2],
        docOmissions: [
          { subject: 'size-cap', count: 4321, size: 4321, where: [], what: '16781537 bytes on disk; this reader reads 16777216', facts: {} },
        ],
      },
    });
    bothSides('mhtml-over-ceiling.mht', {
      label: 'a MIME archive is read to the same ceiling, in the same sentence, over 2,749 bytes',
      value: {
        refused: false,
        rows: [2],
        docOmissions: [
          { subject: 'size-cap', count: 2749, size: 2749, where: [], what: '16779965 bytes on disk; this reader reads 16777216', facts: {} },
        ],
      },
    });
    bothSides('html-at-ceiling.html', {
      label: 'a file of exactly TEXT_MAX_BYTES is read whole and says nothing',
      value: { refused: false, rows: [2], docOmissions: [] },
    });
    // (p) The 300,000-cell row, as a literal on each side. Three independent numbers, none of
    // them round: one row, 300,000 fields, 2,288,889 bytes of text, and 283,616 references
    // past XFD that kept their XML position and lost their column. `Math.max(...keys)` over
    // 300k keys overflows the call stack, which is the defect this closes on the port; the
    // reference has never had it, so a side-to-side case alone would say nothing about
    // whether the fix is still there.
    {
      const sides = at('wide-row.xlsx');
      const wideShape = (answer) => {
        const part = answer?.parts?.[0];
        return {
          refused: Boolean(answer?.error),
          parts: answer?.parts?.length ?? null,
          row_count: part?.row_count ?? null,
          text_bytes: answer?.text_bytes ?? null,
          fields: part?.head === undefined ? null : (part?.rows_bytes ?? null),
          unplaced: (part?.omissions ?? []).filter((o) => o.subject === 'unplaced-cell').map((o) => [o.count, o.what, o.where.length]),
        };
      };
      const wide = {
        refused: false,
        parts: 1,
        row_count: 1,
        text_bytes: 2288889,
        fields: 2288889,
        unplaced: [[283616, 'the column of a cell past XFD, the last column the format has', 283616]],
      };
      cases.push({
        name: 'extract: wide-row.xlsx: a 300,000-cell row is one row of 2,288,889 bytes with 283,616 columns disclosed, as a literal on each side',
        kind: 'json',
        expected: { python: wide, node: wide },
        actual: { python: wideShape(sides.python), node: wideShape(sides.node) },
      });
    }
    notes.push(
      'the ceiling fixtures are BUILT in harness scratch and deleted with it — xlsx-over-budget 1,097 rows, ' +
        'xlsx-at-budget 1,024, xlsx-one-over-budget 1,025, html-over-ceiling 16,781,537 B, html-at-ceiling ' +
        '16,777,216 B, mhtml-over-ceiling 16,779,965 B, wide-row 1,501,741 B / 300,000 cells. the 1 MB rule ' +
        'is about what is CHECKED IN (docs/porting.md) and is enforced by no gate; generating closes (p)',
    );
  }

  // ---------------------------- (w) a duplicate cell is DISCLOSED, and disclosed LAST (U3)
  //
  // Small enough to travel through `paths`, so the generic loop above already compares its
  // rows and its omissions side to side. What that cannot see is both runtimes losing the
  // disclosure together — which is exactly how (w) got registered: `('second',)` and ZERO
  // omissions, on both. So the whole part is pinned as a literal on each side, and the pin is
  // the ORDER as much as the sentence: blank rows, then the number format, then the unplaced
  // cell, then the duplicates. A reader that emitted duplicates FIRST would keep every
  // side-to-side case in this file green.
  {
    const at = (side) => side.files[names.indexOf('duplicate-cell.xlsx')]?.extract ?? null;
    const shapeOf = (answer) => ({
      refused: Boolean(answer?.error),
      rows: (answer?.parts ?? []).flatMap((p) => p.rows),
      omissions: (answer?.parts ?? []).flatMap((p) => p.omissions.map((o) => [o.subject, o.count, o.where, o.what])),
    });
    const disclosed = {
      refused: false,
      // `second` and not `first`: last-wins is UNCHANGED, and this row is what says so.
      rows: ['second\tbee\t\tnowhere', '', 'y'],
      omissions: [
        ['blank-rows', 1, [], ''],
        ['number-format', 1, ['A'], 'yyyy-mm-dd'],
        ['unplaced-cell', 1, ['D'], 'the column of a cell whose reference is not letters then digits'],
        ['duplicate-cell', 2, ['A'], 'the text of a cell a later cell in the same row and column replaced'],
      ],
    };
    cases.push({
      name: 'extract: duplicate-cell.xlsx: last-wins is kept and the replaced cell is disclosed LAST, as a literal on each side',
      kind: 'json',
      expected: { python: disclosed, node: disclosed },
      actual: { python: shapeOf(at(python)), node: shapeOf(at(node)) },
    });
  }

  pages.forEach((spec, i) => {
    const py = python.pages[i];
    const nd = node.pages[i];
    cases.push({ name: `page: ${spec.name}`, kind: 'json', expected: py, actual: nd });
    cases.push({ name: `page: ${spec.name}: the refusal bit (side to side)`, kind: 'json', expected: Boolean(py.error), actual: Boolean(nd.error) });
    if (py.error || nd.error) {
      cases.push({
        name: `page: ${spec.name}: the refusal sentence`,
        kind: 'bytes',
        expected: `${py.error?.type}: ${py.error?.message}`,
        actual: `${nd.error?.type}: ${nd.error?.message}`,
      });
    } else {
      cases.push({ name: `page: ${spec.name}: rows`, kind: 'bytes', expected: py.page.rows.join('\n'), actual: nd.page.rows.join('\n') });
    }
  });

  notes.push(
    `${names.length} files: ${readBoth} read on both sides, ${refusedBoth} refused on both, ${ruled} ruled ` +
      `(pdf/doc/rtf; bzip2/lzma where the reference READS; utf-7, rfc2231, attlist and the bzip2 ` +
      `date styles where both READ); /usr/bin/textutil ${python.textutil ? 'present' : 'absent'} on this host, so the reference ` +
      `${python.textutil ? 'reads note.rtf and refuses real.doc as "plain text"' : 'refuses note.rtf and real.doc by name'}`,
  );
  const pdfRows = python.files[names.indexOf('tiny.pdf')].extract.parts?.map((x) => x.rows) ?? null;
  notes.push(`tiny.pdf on the reference: ${JSON.stringify(pdfRows)}; on the port: ${JSON.stringify(node.files[names.indexOf('tiny.pdf')].extract.error?.message)}`);
  return { cases, notes };
}
