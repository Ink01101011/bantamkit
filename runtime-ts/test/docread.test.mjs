/**
 * R3 (job43): the Node `docread` against the Python reference's OWN answers.
 *
 * Every expected value here was obtained by RUNNING `runtime-py/src/bantamkit/docread.py`
 * over the same bytes, never by reading it:
 *
 * * `docread-expected.jsonl` is one line per fixture in `docread-fixtures.mjs`, written
 *   by the Python reference (the command is in the R3 commit message). The first test
 *   below lays every fixture down, runs `extract` on each, and deep-compares the result
 *   — kind, parts, rows, omissions as `as_dict()`, `text_bytes`, or the refusal sentence
 *   — with that line. Six fixtures are the DELIBERATE divergence (pdf, doc, rtf: kinds the
 *   Node half identifies but does not read) and are asserted separately, against the Node
 *   sentence AND against the fact that the Python line differs — a ruling proves the two
 *   still differ, so the test has to hold both halves.
 * * The `page()` literals are `docread.page(...)` outputs printed by the same Python
 *   (`page_py.py` in the commit message), including the multibyte cut: 2,000 × `ä` under a
 *   3,071-byte ceiling is 1,535 characters kept and 930 bytes reported.
 *
 * The rest are the seams the reference has no fixture for but the port has to hold on its
 * own: the zip reader's deflate branch, `unescape` on the legacy no-semicolon names, the
 * UTF-8 scanner's `reason` strings, quoted-printable's soft breaks, `repr()`.
 */
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';

import { checkedInFixtures, writeFixtures, xlsxBytes, zipBytes } from './docread-fixtures.mjs';

const dist = new URL('../dist/', import.meta.url);
const docread = await import(new URL('docread.js', dist));
const {
  DEFAULT_ROW_LIMIT,
  DocumentReadError,
  HEAD_BYTES,
  PAGE_MAX_BYTES,
  PAGE_MAX_ROWS,
  TEXT_MAX_BYTES,
  ZipReader,
  a2bUu,
  bytesRepr,
  columnIndex,
  columnLetter,
  decodeCharset,
  decodeQuotedPrintable,
  decodeUu,
  extract,
  htmlRows,
  page,
  parseXml,
  pyCodecModule,
  pyRepr,
  sniff,
  unescape,
  utf8Scan,
} = docread;

const dir = mkdtempSync(join(tmpdir(), 'docread-'));
after(() => rmSync(dir, { recursive: true, force: true }));
// The 77 built fixtures plus the checked-in ones `runtime-py/tests/docread_fixtures.py`
// wrote (job43 G1): the SAME bytes the Python suite reads, addressed by file name.
const paths = { ...writeFixtures(dir), ...checkedInFixtures() };

const expected = new Map(
  readFileSync(new URL('docread-expected.jsonl', import.meta.url), 'utf8')
    .split('\n')
    .filter((line) => line)
    .map((line) => {
      const rec = JSON.parse(line);
      return [rec.fixture, rec];
    }),
);

/** The same shape `dump_py.py` prints for the reference, minus the path. */
function dump(path) {
  let doc;
  try {
    doc = extract(path);
  } catch (err) {
    if (err instanceof DocumentReadError) return { error: 'DocumentReadError', message: err.message };
    // `except (DocumentReadError, OSError)` in the reference's handler: `badcd.xlsx` is the
    // `OSError` arm, `[Errno 22] Invalid argument`, and `dump_py.py` prints it the same way.
    if (err.name === 'OSError') return { error: 'OSError', message: err.message };
    // What the reference lets ESCAPE — `zlib.error`, `BadZipFile`, `LookupError` — the port
    // lets escape too, with the same class name and the same words (`RAISED` below).
    return { error: `raised:${err.name}`, message: err.message };
  }
  return {
    kind: doc.kind,
    text_bytes: doc.textBytes,
    parts: doc.parts.map((p) => ({
      name: p.name,
      index: p.index,
      row_count: p.rowCount,
      text_bytes: p.textBytes,
      rows: [...p.rows],
      omissions: p.omissions.map((o) => o.asDict()),
    })),
    omissions: doc.omissions.map((o) => o.asDict()),
  };
}

// The rulings: what the port answers where the reference answers something else. pdf, doc
// and rtf are kinds this half identifies and refuses where the reference reads them; bzip2
// and lzma are zip members the reference decompresses through stdlib modules Node core does
// not have (job43 G2); rfc2231 is a `charset*0=`/`charset*1=` continuation the reference's
// `policy.default` header parser joins and this port's `getParam` does not (G2, left to G3
// to rule) — BOTH read the file, and the row differs by the one byte the charset decides.
const DIVERGENT = new Map([
  [
    'bzip2.docx',
    'bzip2.docx is a zip but its word/document.xml uses compression method 12 (bzip2), which the Node server cannot decompress (the Python server reads it); see docs/porting.md',
  ],
  [
    'lzma.docx',
    'lzma.docx is a zip but its word/document.xml uses compression method 14 (lzma), which the Node server cannot decompress (the Python server reads it); see docs/porting.md',
  ],
  [
    'rfc2231-charset.eml',
    {
      kind: 'mhtml',
      text_bytes: 14,
      parts: [{ name: 'document', index: 0, row_count: 1, text_bytes: 14, rows: ['caf\ufffd au lait'], omissions: [] }],
      omissions: [],
    },
  ],
  [
    'doc.pdf',
    'cannot read doc.pdf: it is a PDF document (PDF-1.7), 15 bytes on disk. pdf is not readable by the Node server yet (the Python server reads it); see docs/porting.md',
  ],
  [
    'sheet.xlsx.pdf',
    'cannot read sheet.xlsx.pdf: it is a PDF document (PDF-1.4), 10 bytes on disk. pdf is not readable by the Node server yet (the Python server reads it); see docs/porting.md',
  ],
  [
    'named.xlsx',
    'cannot read named.xlsx: it is a PDF document (PDF-1.4), 10 bytes on disk; its name says .xlsx, which its bytes do not. pdf is not readable by the Node server yet (the Python server reads it); see docs/porting.md',
  ],
  [
    'real.doc',
    'cannot read real.doc: it is an OLE2 compound file (the pre-2007 Office binary), 520 bytes on disk. doc is read through /usr/bin/textutil by the Python server and not by the Node server; see docs/porting.md',
  ],
  [
    'sheet.xls',
    'cannot read sheet.xls: it is an OLE2 compound file (the pre-2007 Office binary), 12 bytes on disk. doc is read through /usr/bin/textutil by the Python server and not by the Node server; see docs/porting.md',
  ],
  [
    'note.rtf',
    'cannot read note.rtf: it is an RTF document, 18 bytes on disk. rtf is read through /usr/bin/textutil by the Python server and not by the Node server; see docs/porting.md',
  ],
]);

// Both sides RAISE, in the same words: the reference's `_read`/`_parse` catch only what they
// word, and an XML declaration naming no codec (`LookupError`) escapes on both. A corrupt
// deflate stream (`zlib.error`) and a stream that ends early (`BadZipFile` off the CRC) were
// here until review round 3; `_read` now words both as the damaged-member sentence.
const RAISED = new Map([['bogus-encoding.docx', 'LookupError']]);

test('every fixture the reference reads or refuses gets the same bytes from the port', () => {
  assert.equal(expected.size, Object.keys(paths).length, 'one Python line per fixture');
  let compared = 0;
  for (const [name, path] of Object.entries(paths)) {
    if (DIVERGENT.has(name) || RAISED.has(name)) continue;
    const want = { ...expected.get(name) };
    delete want.fixture;
    if (want.message) want.message = want.message.replaceAll('{dir}', dir);
    assert.deepEqual(dump(path), want, name);
    compared += 1;
  }
  assert.equal(compared, expected.size - DIVERGENT.size - RAISED.size);
});

test('what the reference lets escape, the port lets escape: the same class name and the same words', () => {
  for (const [name, cls] of RAISED) {
    const python = expected.get(name);
    assert.ok(python.error === cls || python.error.endsWith(`.${cls}`), `${name}: the reference raised ${python.error}`);
    assert.deepEqual(dump(paths[name]), { error: `raised:${cls}`, message: python.message }, name);
  }
});

test('the rulings: sniff agrees on the kind, the port answers its own sentence, and the reference answers something else', () => {
  for (const [name, want] of DIVERGENT) {
    const kind = sniff(paths[name]).kind;
    const python = expected.get(name);
    const got = dump(paths[name]);
    if (typeof want === 'string') {
      assert.ok(['pdf', 'doc', 'rtf', 'docx'].includes(kind), `${name} sniffs as ${kind}`);
      assert.deepEqual(got, { error: 'DocumentReadError', message: want }, name);
    } else {
      // The read-both ruling: the same shape around the one row that differs.
      assert.deepEqual(got, want, name);
      assert.equal(python.kind, got.kind);
      assert.equal(python.parts.length, got.parts.length);
    }
    const { fixture: _, ...reference } = python;
    assert.notDeepEqual(reference, got, `${name}: the reference answers something else, which is what the ruling records`);
  }
});

test('the checked-in G1 fixtures are read from runtime-py/tests/data/docread, not rebuilt', () => {
  const names = Object.keys(checkedInFixtures());
  assert.deepEqual(names, [
    'bad-crc.docx',
    'charref-4301-digits.html',
    'charset-table.json',
    'compression-method-9.docx',
    'corrupt-deflate.docx',
    'encrypted-member.docx',
    'encrypted-mimetype.odt',
    'eszett-cell-ref.xlsx',
    'internal-dtd-entity.docx',
    'rfc2231-charset.eml',
    'rfc822-nested-twice.eml',
    'unicode-digit-shared-string.xlsx',
    'x-uuencode.eml',
  ]);
  // Three of them are the G2 ports, asserted here by name so a regression is named too.
  assert.deepEqual(dump(paths['unicode-digit-shared-string.xlsx']).parts[0].rows, ['str12\tstr0']);
  assert.deepEqual(dump(paths['x-uuencode.eml']).parts[0].rows, ['hello uuencoded world']);
  assert.deepEqual(dump(paths['internal-dtd-entity.docx']).parts[0].rows, ['a ENT b']);
  assert.equal(
    dump(paths['encrypted-member.docx']).message,
    'encrypted-member.docx is a zip but its word/document.xml is encrypted, so this reader cannot read it without a password',
  );
});

test('review round 3 (H2): the five checked-in reproducers answer the reference\'s own sentences', () => {
  // Each sentence is the `docread-expected.jsonl` line the Python reference wrote for the
  // same bytes (`dump_py.py`, commit message); named here so a regression is named too.
  const sentences = {
    'eszett-cell-ref.xlsx': "cell reference 'ß1' is not a column-and-row reference like B7, so this reader cannot place it",
    'compression-method-9.docx':
      'compression-method-9.docx is a zip but its word/document.xml uses compression method 9, which this reader cannot decompress',
    'encrypted-mimetype.odt':
      'encrypted-mimetype.odt is a zip but its mimetype is encrypted, so this reader cannot read it without a password',
    'bad-crc.docx':
      "bad-crc.docx is a zip but its word/document.xml is damaged (Bad CRC-32 for file 'word/document.xml'), so this reader cannot read it",
    'corrupt-deflate.docx':
      'corrupt-deflate.docx is a zip but its word/document.xml is damaged (Error -3 while decompressing data: invalid block type), so this reader cannot read it',
  };
  for (const [name, message] of Object.entries(sentences)) {
    assert.deepEqual(dump(paths[name]), { error: 'DocumentReadError', message }, name);
    assert.equal(expected.get(name).message, message, `${name}: the reference's line`);
  }
  // The encrypted `mimetype` is a refusal from `sniff` itself, not "truncated or damaged".
  assert.throws(() => sniff(paths['encrypted-mimetype.odt']), { message: sentences['encrypted-mimetype.odt'] });
});

test('a cell reference is ASCII letters then ASCII digits as written, or it is refused (H2)', () => {
  // Python `_column`: `ß1`, `É1`, `A`, `1`, `A1B` refused; `B7` -> 1, `b7` -> 1, `AA1` -> 26.
  assert.equal(columnIndex('B7', 9), 1);
  assert.equal(columnIndex('b7', 9), 1);
  assert.equal(columnIndex('AA1', 9), 26);
  assert.equal(columnIndex(undefined, 9), 9);
  assert.equal(columnIndex('', 9), 9);
  for (const ref of ['ß1', 'É1', 'A', '1', 'A1B', 'A 1']) {
    assert.throws(
      () => columnIndex(ref, 0),
      { message: `cell reference ${pyRepr(ref)} is not a column-and-row reference like B7, so this reader cannot place it` },
      ref,
    );
  }
});

test('a row of 300,000 cells is one line of 300,000 fields, not a call-stack overflow (H2)', () => {
  // `Math.max(...cells.keys())` over 300k keys is `RangeError: Maximum call stack size
  // exceeded` (measured); the reference answers 1 row, 300000 fields, text_bytes 2288889.
  let cells = '';
  for (let i = 0; i < 300000; i += 1) cells += `<c r="${columnLetter(i)}1" t="inlineStr"><is><t>v${i}</t></is></c>`;
  const path = join(dir, 'wide.xlsx');
  writeFileSync(path, xlsxBytes([['Wide', 'worksheets/sheet1.xml', `<row r="1">${cells}</row>`]], { deflate: true }));
  const doc = extract(path);
  assert.equal(doc.parts[0].rowCount, 1);
  assert.equal(doc.parts[0].rows[0].split('\t').length, 300000);
  assert.equal(doc.textBytes, 2288889);
});

test('html_rows: the 4301-digit cap applies to text and attribute values, never to CDATA content (H2)', () => {
  // Every expected value: `docread.html_rows(markup)` on the reference, H1's parser.
  const big = '&#' + '1'.repeat(4301) + ';';
  assert.deepEqual(htmlRows(`<p>x</p><xmp>${big}</xmp><p>y</p>`), ['x', big, 'y']);
  assert.deepEqual(htmlRows(`<textarea>${big}</textarea>`), ['\ufffd']);
  assert.deepEqual(htmlRows(`<script>${big}</script>q`), ['q']);
  assert.deepEqual(htmlRows(`a ${big} b`), ['a \ufffd b']);
  assert.deepEqual(htmlRows(`a ${big.slice(0, -1)}b`), ['a \ufffdb']);
  assert.deepEqual(htmlRows(`<p>${big.slice(0, -1)}`), ['\ufffd']);
  assert.deepEqual(htmlRows(`x &#65; y ${big} z &#${'0'.repeat(4301)}65; w`), ['x A y \ufffd z A w']);
  assert.deepEqual(htmlRows(`<p title="${big}">t</p>`), ['t']);
  assert.deepEqual(htmlRows('&#0000000065; &#x41; &amp;'), ['A A &']);
});

test('decodeCharset answers the codec registry\'s bytes, row for row of charset-table.json (H2)', () => {
  // 40 labels x bytes `80 D0 E9 A4 FF`, `errors="replace"`, written by the registry itself
  // (`docread_fixtures.charset_table`); `LookupError` is the `_decoded_body` fallback, UTF-8.
  const table = JSON.parse(readFileSync(paths['charset-table.json'], 'utf8'));
  const bytes = new Uint8Array([0x80, 0xd0, 0xe9, 0xa4, 0xff]);
  assert.equal(Object.keys(table).length, 40);
  for (const [label, want] of Object.entries(table)) {
    const expect = want === 'LookupError' ? Buffer.from(bytes).toString('utf8') : want;
    assert.equal(decodeCharset(bytes, label), expect, label);
    assert.equal(pyCodecModule(label) === null, want === 'LookupError', `${label}: LookupError`);
  }
});

test('pyCodecModule resolves a charset the way codecs.lookup does, LookupError included (H2)', () => {
  // `codecs.lookup(name).name` on CPython 3.12.13, or `LookupError`; only the verdict is
  // pinned here, the module name is the port's own key.
  const resolves = ['ISO 8859-1', 'ISO_8859-1', 'iso8859_1', ' latin1 ', 'Latin-1', 'utf8', 'UTF-8', 'utf_8', 'macroman', '437', 'ibm437', 'windows_1252', 'cp1252', 'ansi_x3.4-1968', 'iso_8859_1:1987', 'csISOLatin1', 'l1', '8859', 'utf16', 'utf-16-le', 'utf_16be', 'sjis', 'ms932', 'euc_jp', 'ks_c_5601-1987', 'tis620', 'ISO--8859--1', 'iso-8859-1;', 'u8', 'cp65001', 'utf-32', 'latin_1', 'iso8859-1'];
  const refused = ['latin.1', 'x-mac-roman', 'cp-437', 'iso-8859-12', 'gb-2312', 'x-gbk', 'big-5', 'koi8r', '', '-'];
  for (const name of resolves) assert.notEqual(pyCodecModule(name), null, name);
  for (const name of refused) assert.equal(pyCodecModule(name), null, name);
  assert.equal(pyCodecModule('ISO 8859-1'), 'latin_1');
  assert.equal(pyCodecModule('windows-1252'), 'cp1252');
});

test('under win32 every sentence names the path the way pathlib spells it there', () => {
  // `Path('C:/docs/missing.docx')` prints `C:\docs\missing.docx` on Windows; the sentence
  // is built from `str(Path(p))`. The platform is faked, the filesystem is this one: the
  // stat of `C:\docs\missing.docx` fails here as it would there.
  const platform = Object.getOwnPropertyDescriptor(process, 'platform');
  Object.defineProperty(process, 'platform', { value: 'win32', configurable: true });
  try {
    assert.throws(() => sniff('C:/docs/missing.docx'), { message: 'no such file: C:\\docs\\missing.docx' });
    assert.throws(() => extract('C:/docs/missing.docx'), { message: 'no such file: C:\\docs\\missing.docx' });
    // `Path(p).name`: a file that is literally called `docs\junk.docx` on this filesystem is
    // `junk.docx` to `PureWindowsPath`, and the refusal names it so. (`docs` is a directory
    // component there, so the path is written with no separator this platform would split.)
    const literal = join(dir, 'docs\\junk.docx');
    writeFileSync(literal, 'PK\x03\x04 not a zip at all');
    const cwd = process.cwd();
    process.chdir(dir);
    try {
      assert.throws(() => extract('docs\\junk.docx'), {
        message: /^cannot read junk\.docx: it is a truncated or damaged zip archive/,
      });
    } finally {
      process.chdir(cwd);
    }
  } finally {
    Object.defineProperty(process, 'platform', platform);
  }
  // And back on this platform the same literal name is one component.
  const cwd = process.cwd();
  process.chdir(dir);
  try {
    assert.throws(() => extract('docs\\junk.docx'), { message: /^cannot read docs\\junk\.docx: / });
  } finally {
    process.chdir(cwd);
  }
});

test('uuencode decodes like binascii.a2b_uu and email._decode_uu', () => {
  // Every literal is `binascii.a2b_uu(...)` / `Message.get_payload(decode=True)` on CPython 3.12.
  assert.equal(a2bUu(Buffer.from('#0V%T')).toString('latin1'), 'Cat');
  assert.equal(a2bUu(Buffer.from('#0V%')).toString('latin1'), 'Ca@');
  assert.deepEqual([...a2bUu(Buffer.from(''))], new Array(32).fill(0));
  assert.deepEqual([...a2bUu(Buffer.from(' '))], []);
  assert.throws(() => a2bUu(Buffer.from('#0V%Tzz')), { message: 'Trailing garbage' });
  assert.throws(() => a2bUu(Buffer.from('!A\x7f')), { message: 'Illegal char' });
  assert.equal(decodeUu(Buffer.from('begin 644 f\n#0V%T\n`\nend\n')).toString('latin1'), 'Cat');
  assert.equal(decodeUu(Buffer.from('begin 644 f\r\n#0V%Tzz\r\nend\r\n')).toString('latin1'), 'Cat');
  assert.equal(decodeUu(Buffer.from('begin 644 f\n#0V%T\nEND\n')).length, 3 + 37); // `END` is data: 'E' - 32 = 37 bytes
  assert.throws(() => decodeUu(Buffer.from('begin 644 f\n#0V%T\n\nend\n')), { message: 'Truncated input' });
  assert.throws(() => decodeUu(Buffer.from('begin xyz f\n#0V%T\nend\n')), { message: '`begin` line not found' });
  assert.throws(() => decodeUu(Buffer.from('  begin 644 f\n#0V%T\nend\n')), { message: '`begin` line not found' });
});

test('the page ceilings are the numbers the reference hoisted', () => {
  assert.deepEqual([DEFAULT_ROW_LIMIT, PAGE_MAX_ROWS, PAGE_MAX_BYTES, TEXT_MAX_BYTES, HEAD_BYTES], [50, 200, 3072, 16777216, 4096]);
});

const rowsFrom = (a, b) => Array.from({ length: b - a + 1 }, (_, k) => `row-${String(a + k).padStart(3, '0')}`);

function pageDict(doc, ...args) {
  try {
    const p = page(doc, ...args);
    return {
      part: p.part,
      offset: p.offset,
      rows: [...p.rows],
      total_rows: p.totalRows,
      next_offset: p.nextOffset,
      truncated_bytes: p.truncatedBytes,
    };
  } catch (err) {
    if (err instanceof DocumentReadError) return { error: err.message };
    throw err;
  }
}

test('page() slices the way the reference slices', () => {
  const doc = extract(paths['p.xlsx']);
  const data = (offset, rows, next, truncated = 0) => ({
    part: 'data',
    offset,
    rows,
    total_rows: 120,
    next_offset: next,
    truncated_bytes: truncated,
  });
  assert.deepEqual(pageDict(doc), data(0, rowsFrom(1, 50), 50));
  assert.deepEqual(pageDict(doc, 'data', 0, 50), data(0, rowsFrom(1, 50), 50));
  assert.deepEqual(pageDict(doc, 'data', 100, 50), data(100, rowsFrom(101, 120), null));
  assert.deepEqual(pageDict(doc, 'data', 119, 5), data(119, ['row-120'], null));
  assert.deepEqual(pageDict(doc, 'data', 120, 5), data(120, [], null));
  assert.deepEqual(pageDict(doc, 'data', 500, 5), data(500, [], null));
  assert.deepEqual(pageDict(doc, 'data', 0, 200, PAGE_MAX_BYTES), data(0, rowsFrom(1, 120), null));
  assert.deepEqual(pageDict(doc, 'data', 0, 50, 20), data(0, ['row-001', 'row-002'], 2));
  assert.deepEqual(pageDict(doc, 'data', 3, 50, 7), data(3, ['row-004'], 4));
  const other = { part: 'other', offset: 0, rows: [], total_rows: 0, next_offset: null, truncated_bytes: 0 };
  assert.deepEqual(pageDict(doc, 1), other);
  assert.deepEqual(pageDict(doc, '1'), other);
  assert.deepEqual(pageDict(doc, '-1'), { error: "no part '-1'; this document has 2: 'data', 'other'" });
  assert.deepEqual(pageDict(doc, 'nope'), { error: "no part 'nope'; this document has 2: 'data', 'other'" });
  assert.deepEqual(pageDict(doc, 7), { error: "no part 7; this document has 2: 'data', 'other'" });
  assert.deepEqual(pageDict(doc, 0, -1, 5), { error: 'offset must be >= 0 and limit >= 1, got -1 and 5' });
  assert.deepEqual(pageDict(doc, 0, 0, 0), { error: 'offset must be >= 0 and limit >= 1, got 0 and 0' });
});

test('a single row over the ceiling is cut on a character boundary and the loss reported', () => {
  const doc = extract(paths['long.xlsx']);
  const odd = pageDict(doc, 0, 0, 50, 3071);
  assert.deepEqual({ ...odd, rows: [odd.rows[0].length, new Set(odd.rows[0]).size] }, {
    part: 'data',
    offset: 0,
    rows: [1535, 1],
    total_rows: 2,
    next_offset: 1,
    truncated_bytes: 930,
  });
  const even = pageDict(doc, 0, 0, 50, 3072);
  assert.deepEqual([even.rows[0].length, even.truncated_bytes, even.next_offset], [1536, 928, 1]);
  assert.deepEqual(pageDict(doc, 0, 1, 50, 3072), {
    part: 'data',
    offset: 1,
    rows: ['next'],
    total_rows: 2,
    next_offset: null,
    truncated_bytes: 0,
  });
});

test('the zip reader inflates a deflated member and checks its CRC', () => {
  const zf = ZipReader.from(zipBytes([['a/b.txt', 'hello '.repeat(200)]], { deflate: true }));
  assert.equal(zf.read('a/b.txt').toString(), 'hello '.repeat(200));
  const bytes = zipBytes([['x', 'payload']]);
  bytes[30 + 1] ^= 0xff; // one byte of the stored data
  assert.throws(() => ZipReader.from(bytes).read('x'), /Bad CRC-32/);
  assert.throws(() => ZipReader.from(Buffer.from('PK\x03\x04 nothing')), /not a zip file/);
});

test('the zip reader refuses a negative member offset the way a seek(-n) does, with no filename', () => {
  // The fixture with the EOCD central-directory offset overwritten as 0x7FFFFFF0: the central
  // directory itself is still found (`start_dir = location - size_cd`), but every header offset
  // is `header_offset + concat` with `concat` hugely negative. The reference: `[Errno 22]
  // Invalid argument` (measured, the F3 commit message); before F3 this port threw
  // `RangeError [ERR_OUT_OF_RANGE]` out of `readUInt32LE`.
  const zf = ZipReader.open(paths['badcd.xlsx']);
  assert.deepEqual(zf.namelist().slice(0, 2), ['[Content_Types].xml', '_rels/.rels']);
  assert.throws(
    () => zf.read('xl/workbook.xml'),
    (err) => err.name === 'OSError' && err.errno === 22 && err.message === '[Errno 22] Invalid argument',
  );
  // A central directory that starts before byte 0 is `BadZipFile`, which `openZip` turns
  // into the not-a-zip sentence — the reference's `_RealGetContents` check, not a `RangeError`.
  const bytes = zipBytes([['x', 'payload']]);
  bytes.writeUInt32LE(0xffffffff, bytes.length - 22 + 12); // size_cd > location
  assert.throws(() => ZipReader.from(bytes), /Bad offset for central directory/);
});

test('the XML walk refuses every reference expat refuses, and expands every one it accepts', () => {
  const doc = (text) => parseXml(Buffer.from(`<a>${text}</a>`)).text;
  assert.equal(doc('a &amp; b &#38; &#x26; &lt; &gt; &quot; &apos; &#9;'), 'a & b & & < > " \' \t');
  assert.equal(doc('&#x1F600;'), '\u{1F600}');
  for (const bad of ['a & b', 'a &amp b', '&#0;', '&#xD800;', '&#xDFFF;', '&#x110000;', '&#xFFFE;', '&nbsp;', '&;', '& amp;']) {
    assert.throws(() => doc(bad), (err) => err.name === 'XmlParseError', bad);
  }
  // In an attribute value too, which is where expat found `attr-amp.xlsx`'s.
  assert.throws(() => parseXml(Buffer.from('<a x="1 & 2"/>')), (err) => err.name === 'XmlParseError');
  assert.equal(parseXml(Buffer.from('<a x="1 &amp; 2"/>')).get('x'), '1 & 2');
});

test('the stat target and the displayed name are Path(p) and Path(p).name', () => {
  // `Path('')` is `.`, the cwd — a directory; `statSync('')` is ENOENT. Measured (F3):
  // `. is a directory, not a document` there, `no such file: .` here.
  assert.throws(() => extract(''), { message: '. is a directory, not a document' });
  // A trailing `.` component is dropped by pathlib, so `nosuffix/.` is the FILE; a raw stat
  // of `file/.` is ENOTDIR. `a/b/.` names `b`, not `.`.
  assert.deepEqual(dump(paths['nosuffix'] + '/.'), dump(paths['nosuffix']));
  assert.throws(() => extract(join(dir, 'missing', 'b', '.')), { message: `no such file: ${join(dir, 'missing', 'b')}` });
  assert.throws(() => extract(paths['sheet.xls'] + '/.'), {
    message: /^cannot read sheet\.xls: it is an OLE2 compound file/,
  });
});

test('a device file is sniffed by what read() returns, not by st_size', { skip: !existsSync('/dev/zero') }, () => {
  // The reference reads 4096 zero bytes off `/dev/zero`; `st_size` is 0. Measured (F3): the
  // port said `an empty file (0 bytes)` and the reference said what follows.
  assert.throws(() => extract('/dev/zero'), {
    message:
      "cannot read zero: it is not a recognised container; it starts with b'\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00', 0 bytes on disk. this reader reads text, xlsx, docx, pdf, html and mhtml directly, and doc and rtf through /usr/bin/textutil",
  });
});

test('unescape follows html.unescape, legacy names and invalid code points included', () => {
  // Python: html.unescape("a &amp b &notin; &#128; &#x110000; &#0; &lt") == 'a & b ∉ € � � <'
  assert.equal(unescape('a &amp b &notin; &#128; &#x110000; &#0; &lt'), 'a & b ∉ € � � <');
  assert.equal(unescape('&nosuch; &ampx'), '&nosuch; &x');
  assert.equal(unescape('&#1; &#xB; &#xFDD0;'), '  ');
});

test('the UTF-8 scanner reports the offset and reason CPython reports', () => {
  assert.deepEqual(utf8Scan(Buffer.from('ab\xe2\x82', 'latin1'), true), {
    end: 2,
    invalidAt: 2,
    reason: 'unexpected end of data',
    incomplete: false,
  });
  assert.deepEqual(utf8Scan(Buffer.from('ab\xe2\x82', 'latin1'), false), {
    end: 2,
    invalidAt: -1,
    reason: '',
    incomplete: true,
  });
  assert.equal(utf8Scan(Buffer.from('a\xffb', 'latin1'), true).reason, 'invalid start byte');
  assert.equal(utf8Scan(Buffer.from('\xe0\x80\x80', 'latin1'), true).reason, 'invalid continuation byte');
  assert.equal(utf8Scan(Buffer.from('\xed\xa0\x80', 'latin1'), true).reason, 'invalid continuation byte');
  assert.deepEqual(utf8Scan(Buffer.from('→ok', 'utf8'), true), { end: 5, invalidAt: -1, reason: '', incomplete: false });
});

test('quoted-printable decodes like binascii.a2b_qp', () => {
  // Python: quopri.decodestring(b"a  \nb =\r\nc=41=4a=zz \t\r\nd") == b'a  \nb cAJ=zz \t\r\nd'
  assert.equal(
    decodeQuotedPrintable(Buffer.from('a  \nb =\r\nc=41=4a=zz \t\r\nd', 'latin1')).toString('latin1'),
    'a  \nb cAJ=zz \t\r\nd',
  );
});

test('repr() of a str and of bytes, as the refusal sentences print them', () => {
  assert.equal(pyRepr("it's"), '"it\'s"');
  assert.equal(pyRepr('tab\there​'), "'tab\\there\\u200b'");
  assert.equal(bytesRepr(Buffer.from('PK\x03\x04\n\xff\'"', 'latin1')), "b'PK\\x03\\x04\\n\\xff\\'\"'");
});
