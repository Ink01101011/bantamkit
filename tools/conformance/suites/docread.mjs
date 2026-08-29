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
    // 0xA4 is `§`) and iso-8859-9 (Turkish, 0xD0 is `Ğ`). Sent 8bit so the bytes reach the
    // decoder as bytes; the `charsets` suite pins the whole table, this pins the seam.
    ...Object.fromEntries(
      ['cp437', 'mac_roman', 'iso-8859-9'].map((label) => [
        `charset-${label}.eml`,
        Buffer.concat([
          Buffer.from(`MIME-Version: 1.0\nContent-Type: text/plain; charset="${label}"\nContent-Transfer-Encoding: 8bit\n\nx `, 'latin1'),
          Buffer.from([0x80, 0xd0, 0xe9, 0xa4, 0xff]),
          Buffer.from(' y\n', 'latin1'),
        ]),
      ]),
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
  // A CHECKED-IN FIXTURE WINS over a built one of the same name: the built
  // `corrupt-deflate.docx` above and the checked-in one are both a corrupt deflate stream
  // over `word/document.xml`, and the checked-in bytes are what both unit suites read, so
  // the built copy is dropped here and the note names it — a throw (which is what this loop
  // did until H3) stopped the whole suite from starting over a name collision.
  const notes = [];
  for (const [file, path] of Object.entries(fixtures.checkedInFixtures())) {
    if (paths[file] !== undefined) notes.push(`checked-in fixture ${file} shadows the built one of the same name; the checked-in bytes are compared`);
    paths[file] = path;
  }
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
  const node = {
    files: names.map((n) => ({
      sniff: attempt(() => container(docread.sniff(paths[n]))),
      extract: attempt(() => document(docread.extract(paths[n]))),
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

  const cases = [];
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
      `(pdf/doc/rtf; bzip2/lzma where the reference READS; utf-7, rfc2231 and attlist where both READ); /usr/bin/textutil ${python.textutil ? 'present' : 'absent'} on this host, so the reference ` +
      `${python.textutil ? 'reads note.rtf and refuses real.doc as "plain text"' : 'refuses note.rtf and real.doc by name'}`,
  );
  const pdfRows = python.files[names.indexOf('tiny.pdf')].extract.parts?.map((x) => x.rows) ?? null;
  notes.push(`tiny.pdf on the reference: ${JSON.stringify(pdfRows)}; on the port: ${JSON.stringify(node.files[names.indexOf('tiny.pdf')].extract.error?.message)}`);
  return { cases, notes };
}
