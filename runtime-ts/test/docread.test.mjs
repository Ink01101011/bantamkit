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
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, sep } from 'node:path';
import { after, test } from 'node:test';
import { execFileSync } from 'node:child_process';

import { checkedInFixtures, docxBytes, writeFixtures, xlsxBytes, zipBytes } from './docread-fixtures.mjs';

const dist = new URL('../dist/', import.meta.url);
const docread = await import(new URL('docread.js', dist));
const contract = await import(new URL('contract.js', dist));
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
  // job44 U17. The bzip2 member M1 left unfixtured, now carrying a DATE format. Neither side
  // refuses and both read the same row — the divergence is the DISCLOSURE: the reference
  // decompresses `xl/styles.xml` through `bz2`, sees `yyyy-mm-dd` at the style A1 uses, and
  // emits the `number-format` omission; `dateFormats` here catches the method-12 refusal as an
  // unreadable OPTIONAL member and answers no formats, so the omission list is empty. The
  // sibling `deflate-date-styles.xlsx` is the control and is NOT in this map: the same styles
  // behind method 8 make both sides emit the omission, which is what says the fixture can show
  // a difference at all.
  [
    'bzip2-date-styles.xlsx',
    {
      kind: 'xlsx',
      text_bytes: 8,
      parts: [{ name: 'Sales', index: 0, row_count: 1, text_bytes: 8, rows: ['46235\tok'], omissions: [] }],
      omissions: [],
    },
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
    // `{dir}/` AND NOT `{dir}`, because the separator in the template belongs to the platform
    // the expectations were RECORDED on. Substituting a Windows temp directory into `{dir}/x`
    // yields `C:\...\docread-xxx/x` — a mixed path no runtime produces — while the port spells
    // it the way the OS does. Measured on CI 2026-09-05: expected `...docread-xjwmDz/a-directory`
    // against actual `...docread-xjwmDz\a-directory`, one character apart.
    //
    // Only the separator that follows the placeholder is rewritten. Every `/` in these messages
    // is a path separator today — checked, zero of the recorded messages contain one for any
    // other purpose — but a blanket replace would silently corrupt the first message that
    // carried a mime type, so this stays narrow.
    if (want.message) want.message = want.message.replaceAll('{dir}/', dir + sep).replaceAll('{dir}', dir);
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

test('review round 3 (H2): the four checked-in reproducers answer the reference\'s own sentences', () => {
  // Each sentence is the `docread-expected.jsonl` line the Python reference wrote for the
  // same bytes (`dump_py.py`, commit message); named here so a regression is named too.
  //
  // AMENDED at review round 4 (M2). This list held FIVE, and the fifth was
  // `eszett-cell-ref.xlsx`: "cell reference 'ß1' is not a column-and-row reference like B7,
  // so this reader cannot place it". That sentence no longer exists on either runtime — one
  // cell the reader cannot place must not cost the caller the whole workbook — so the
  // fixture moved out of the refusal list and into "one unplaceable cell does not cost the
  // caller the other sheet", which pins what it answers INSTEAD. Mirrors `runtime-py`
  // `a1acfa7`; the reference's own new line for it is `docread-expected.jsonl:114`.
  const sentences = {
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

test('a cell reference is ASCII letters then ASCII digits as written, or it is not placed (H2)', () => {
  // Python `_column`: `B7` -> 1, `b7` -> 1, `AA1` -> 26; `ß1`, `É1`, `A`, `1`, `A1B` are not
  // placed. AMENDED at review round 4 (M2): the shapes this reader cannot place are an
  // ANSWER now and not a throw — `[fallback, reason]`. What round 3 measured still holds and
  // is what this case is for: no `TypeError` on `ß1`, and `ß1` is still NOT read as `SS1`
  // (column 486), because the match is on the reference as written. The full shape list and
  // the ceiling are pinned below, under M2/M5.
  assert.deepEqual(columnIndex('B7', 9), [1, '']);
  assert.deepEqual(columnIndex('b7', 9), [1, '']);
  assert.deepEqual(columnIndex('AA1', 9), [26, '']);
  assert.deepEqual(columnIndex(undefined, 9), [9, '']);
  assert.deepEqual(columnIndex('', 9), [9, '']);
  for (const ref of ['ß1', 'É1', 'A', '1', 'A1B', 'A 1']) {
    assert.deepEqual(columnIndex(ref, 0), [0, docread.UNPLACED_SHAPE], ref);
    assert.notEqual(columnIndex(ref, 0)[0], 485, `${ref} must not be read through toUpperCase`);
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
  const realPlatform = process.platform;
  const platform = Object.getOwnPropertyDescriptor(process, 'platform');
  Object.defineProperty(process, 'platform', { value: 'win32', configurable: true });
  try {
    assert.throws(() => sniff('C:/docs/missing.docx'), { message: 'no such file: C:\\docs\\missing.docx' });
    assert.throws(() => extract('C:/docs/missing.docx'), { message: 'no such file: C:\\docs\\missing.docx' });
    // `Path(p).name`: whatever `docs\junk.docx` denotes, the refusal names `junk.docx` and
    // not the whole path. WHAT IT DENOTES IS NOT THE SAME EVERYWHERE and the fixture has to
    // follow: on POSIX a backslash is an ordinary character, so this is ONE file whose name
    // contains it; on a real Windows filesystem it is `junk.docx` inside a `docs` directory.
    // Writing the POSIX shape there fails at `writeFileSync` with `ENOENT ... docs\junk.docx`
    // because the directory does not exist — measured on CI 2026-09-05.
    //
    // `process.platform` IS FAKED ABOVE, so the real platform is asked for separately. The
    // fake decides what the code under test SPELLS; the filesystem decides what can be
    // written, and only the second one is a question about this machine.
    if (realPlatform === 'win32') {
      mkdirSync(join(dir, 'docs'), { recursive: true });
      writeFileSync(join(dir, 'docs', 'junk.docx'), 'PK\x03\x04 not a zip at all');
    } else {
      writeFileSync(join(dir, 'docs\\junk.docx'), 'PK\x03\x04 not a zip at all');
    }
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
  // And back on this platform, where the same literal is read by THIS platform's rules: one
  // component on POSIX, two on Windows. The sentence names the last component either way,
  // which is the property — `Path(p).name` — and the expectation follows the reading rather
  // than pinning one of them. Measured on CI 2026-09-05: `cannot read junk.docx` there
  // against `cannot read docs\junk.docx` here, from one unchanged line of code.
  const named = process.platform === 'win32' ? /^cannot read junk\.docx: / : /^cannot read docs\\junk\.docx: /;
  const cwd = process.cwd();
  process.chdir(dir);
  try {
    assert.throws(() => extract('docs\\junk.docx'), { message: named });
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

// ---- M2 / M5: a cell this reader cannot place costs that cell's COLUMN, nothing more ----
//
// Mirrors `runtime-py` `a1acfa7`. Round 3 made `columnIndex` strict about the SHAPE of a
// cell reference — right — and spelled the answer as a `DocumentReadError` out of a
// function `sheetRows` does not catch, so ONE cell refused the whole workbook. Round 3 also
// left the resulting index unbounded, so a reference of five letters built a row wide enough
// to hold it. Both are `columnIndex`, and they have one answer: it ANSWERS `[column, reason]`
// and the column the cell did not get is disclosed through the omission channel.

const sheet = (body) => xlsxBytes([['S', 'worksheets/sheet1.xml', body]]);
const inline = (ref, value) => `<c r="${ref}" t="inlineStr"><is><t>${value}</t></is></c>`;
const oneRow = (...cells) => `<row r="1">${cells.join('')}</row>`;
/** `[(o.subject, o.count, o.where, o.what) for o in part.omissions]`, as the reference prints it. */
const omitted = (part) => part.omissions.map((o) => [o.subject, o.count, [...o.where], o.what]);

function xlsx(name, body) {
  const path = join(dir, name);
  writeFileSync(path, sheet(body));
  return path;
}

test('one unplaceable cell does not cost the caller the other sheet (M2)', () => {
  // MEASURED before the fix, on this exact fixture: `DocumentReadError: cell reference '1'
  // is not a column-and-row reference like B7, so this reader cannot place it` — no
  // manifest, no parts, and the CLEAN sheet unreachable. The cell keeps its text and takes
  // its XML position, which is where it sat before round 3 and is the same position on both
  // runtimes; what it loses is its stated column, and that loss is DISCLOSED.
  const path = join(dir, 'two-sheets.xlsx');
  writeFileSync(
    path,
    xlsxBytes([
      ['Good', 'worksheets/sheet1.xml', oneRow(inline('A1', 'clean'))],
      ['Bad', 'worksheets/sheet2.xml', oneRow(inline('1', 'oops'))],
    ]),
  );
  const doc = extract(path);
  assert.deepEqual(doc.parts.map((p) => [p.name, [...p.rows]]), [['Good', ['clean']], ['Bad', ['oops']]]);
  assert.deepEqual(omitted(doc.parts[0]), []);
  assert.deepEqual(omitted(doc.parts[1]), [['unplaced-cell', 1, ['A'], docread.UNPLACED_SHAPE]]);
});

test('every reference shape this reader cannot place is reported, not raised (M2)', () => {
  // The shapes round 3 refused, each one now an answer instead of an exception. `ß1` is the
  // one round 3 was written for and it still does NOT become column 486: the match is on
  // the reference AS WRITTEN and never on its uppercase, so the cell falls back to its XML
  // position and both runtimes place it in the same place.
  for (const ref of ['1', 'A', 'A1B', 'É1', 'a-1', 'A 1', 'B7 ', 'ß1']) {
    assert.deepEqual(columnIndex(ref, 3), [3, docread.UNPLACED_SHAPE], ref);
  }
  assert.deepEqual(columnIndex('ab7', 0), [27, '']);
  assert.deepEqual(columnIndex('AB7', 0), [27, '']);
  assert.deepEqual(columnIndex(undefined, 3), [3, '']);
  assert.deepEqual(columnIndex('', 3), [3, '']);
});

test('a reference past the format\'s last column is not placed there (M5)', () => {
  // MEASURED on the reference before the fix: 1,755 bytes of xlsx whose single cell is
  // `r="ZZZZZ1"` produced a 12,356,630-byte row — 7,041x amplification, from a column index
  // with no ceiling at all. The bound is the FORMAT's: ECMA-376 gives a worksheet 16,384
  // columns, the last of them `XFD`.
  const doc = extract(xlsx('zzzzz.xlsx', oneRow(inline('ZZZZZ1', 'x'))));
  assert.deepEqual([...doc.parts[0].rows], ['x']);
  assert.equal(Buffer.byteLength(doc.parts[0].rows[0], 'utf8'), 1);
  assert.deepEqual(omitted(doc.parts[0]), [['unplaced-cell', 1, ['A'], docread.UNPLACED_RANGE]]);
});

test('the last column the format has is still read (M5)', () => {
  // Off-by-one-proof from both sides: `XFD` is column 16,384 and reads; `XFE` is the first
  // that does not exist and falls back. A ceiling that ate the last real column would be a
  // second defect wearing the first one's fix.
  assert.deepEqual(columnIndex('XFD1', 0), [16383, '']);
  assert.equal(docread.XLSX_MAX_COLUMNS, 16384);
  assert.equal(columnLetter(16383), 'XFD');
  assert.deepEqual(columnIndex('XFE1', 0), [0, docread.UNPLACED_RANGE]);
  assert.deepEqual(columnIndex('ZZZ1', 0), [0, docread.UNPLACED_RANGE]); // 18278, three letters
  const doc = extract(xlsx('xfd.xlsx', oneRow(inline('XFD1', 'end'))));
  assert.deepEqual([...doc.parts[0].rows], ['\t'.repeat(16383) + 'end']);
  assert.deepEqual(omitted(doc.parts[0]), []);
});

test('a million-letter reference is answered without building the integer (M5)', () => {
  // A reference of a million letters is a valid `[A-Za-z]+[0-9]+` and would otherwise be
  // turned into a base-26 number of a million digits before anything looked at its size.
  const start = process.hrtime.bigint();
  assert.deepEqual(columnIndex('A'.repeat(1_000_000) + '1', 7), [7, docread.UNPLACED_RANGE]);
  assert.ok(Number(process.hrtime.bigint() - start) / 1e9 < 1.0);
});

test('unplaced cells of one reason are counted together and the reasons apart (M2/M5)', () => {
  // One omission per reason, columns in column order — the shape `number-format` already
  // uses, so a caller that renders one renders the other. The reasons sort by CODEPOINT,
  // which puts `past XFD` before `not letters then digits`.
  //
  // The DUPLICATE line is job44 (v)-(w)'s doing and was always true of this fixture: `B7 ` is
  // unplaceable, so it falls back to its XML position — column 2, which is `C1`'s column, and
  // `C1` overwrote it. This assertion said the sheet lost two things when it had lost three,
  // and the third one is precisely the silence entry (w) registers.
  const doc = extract(
    xlsx('mixed.xlsx', oneRow(inline('1', 'a'), inline('ZZZZZ1', 'b'), inline('B7 ', 'c'), inline('C1', 'd'))),
  );
  assert.deepEqual([...doc.parts[0].rows], ['a\tb\td']); // `c` is gone, and now it is gone OUT LOUD
  assert.deepEqual(omitted(doc.parts[0]), [
    ['unplaced-cell', 1, ['B'], docread.UNPLACED_RANGE],
    ['unplaced-cell', 2, ['A', 'C'], docread.UNPLACED_SHAPE],
    ['duplicate-cell', 1, ['C'], docread.DUPLICATE_CELL],
  ]);
});

test('an unplaced cell renders through the contract layer\'s unknown-subject line', () => {
  // `omissionLine` has no branch for this subject and does not need one: the generic line
  // prints an unknown subject's count rather than dropping it, which is the whole reason
  // that fallback exists. Pinning it here keeps the two layers honest about the lag.
  const doc = extract(xlsx('unplaced-one.xlsx', oneRow(inline('1', 'a'))));
  const lines = contract.documentManifest([
    {
      document: 'unplaced-one.xlsx',
      kind: 'xlsx',
      index: 1,
      part: 'S',
      row_count: 1,
      rows: [...doc.parts[0].rows],
      omissions: doc.parts[0].omissions.map((o) => o.asDict()),
    },
  ]).split('\n');
  assert.ok(
    lines.includes(
      '  NOT in those rows: 1 unplaced-cell (the column of a cell whose reference is not letters then digits)',
    ),
    lines.join('\n'),
  );
});

// ---- H1: a STATEFUL codec is not a byte table, and must never be given one ---------------
//
// THE FAMILY. `charsets-table.py` writes `SINGLE_BYTE_TABLES` for every module it judges a
// stateless single-byte codec. Its judgement was a 2-byte probe from SIX hand-picked lead
// bytes (0x41, 0x80, 0xA4, 0xD0, 0xE9, 0xFF), and neither ESC (0x1B) nor `~` (0x7E) is among
// them — so the codecs whose decoder carries STATE set by earlier bytes walked straight
// through it. MEASURED: seven modules held a 256-character table they cannot have —
// `hz` and the six `iso2022_jp*` — and `decodeSingleByte` then decoded them ONE BYTE AT A
// TIME, which is what destroyed the escape sequences.
//
// MEASURED before the fix, on `'こんにちは'.encode('iso2022_jp')`:
//   reference  'こんにちは'
//   port       "�$B$3$s$K$A$O�(B"    (the ESCs mapped to U+FFFD by the table)
// This was a REGRESSION: before round 3 the port called `TextDecoder(charset)` and ICU has
// a real `iso-2022-jp` decoder.
//
// WHICH DECODER, decided by measurement and not by taste. Three arms over 8,829 inputs
// (every character CPython's `iso2022_jp` can encode, in slices of 8, plus 7,920 random and
// ESC-biased byte strings), scored against CPython's own answer:
//
//   arm                    all         valid iso-2022-jp text   random bytes
//   byte table (before)    5021/8829   73/900                   4940/7920
//   utf-8 fallback         4339/8829   45/900                   4288/7920
//   ICU iso-2022-jp        5664/8829   888/900                  4768/7920
//
// and over the shared JIS X 0208 range each `iso2022_jp*` variant scores 99.5–99.7 % through
// ICU against 1.4 % through UTF-8. `hz`, `iso2022_kr` and `utf_7` score 0 % through ICU —
// WHATWG maps those three to the "replacement" encoding — so they keep the no-decoder path
// `decodeCharset` already documents. That is where this family's boundary is, and it is a
// number, not a preference.

test('a stateful codec never holds a single-byte table (H1)', async () => {
  // The property the generator must hold: a codec whose meaning depends on decoder STATE
  // cannot be a byte-to-character map, so it must not be in the map table at all. Named
  // individually so a regression names the module.
  const charsets = await import(new URL('charsets.js', dist));
  const stateful = [
    'hz',
    'utf_7',
    'iso2022_jp',
    'iso2022_jp_1',
    'iso2022_jp_2',
    'iso2022_jp_2004',
    'iso2022_jp_3',
    'iso2022_jp_ext',
    'iso2022_kr',
  ];
  for (const module of stateful) {
    assert.ok(charsets.CODEC_MODULES.has(module), `${module} is a module the registry has`);
    assert.equal(
      Object.prototype.hasOwnProperty.call(charsets.SINGLE_BYTE_TABLES, module),
      false,
      `${module} is stateful and must not have a single-byte table`,
    );
  }
});

test('iso-2022-jp and its variants decode through the escape-aware decoder (H1)', () => {
  // `'こんにちは'.encode('iso2022_jp')`. The reference answers 'こんにちは' for every one of
  // the six `iso2022_jp*` modules; the port answered "�$B$3$s$K$A$O�(B".
  const buf = Buffer.from('1b244224332473244b2441244f1b2842', 'hex');
  for (const label of [
    'iso-2022-jp',
    'iso2022_jp',
    'iso2022_jp_1',
    'iso2022_jp_2',
    'iso2022_jp_2004',
    'iso2022_jp_3',
    'iso2022_jp_ext',
  ]) {
    assert.equal(decodeCharset(buf, label), 'こんにちは', label);
  }
  // ASCII outside the escapes is still ASCII, and the shift back to ASCII is honoured.
  assert.equal(
    decodeCharset(Buffer.from('68690a1b24422422242424261b284277', 'hex'), 'iso-2022-jp'),
    'hi\nあいうw',
  );
});

test('the stateful codecs ICU has no decoder for keep the no-decoder path (H1)', () => {
  // `hz`, `iso2022_kr` and `utf_7` are the WHATWG "replacement" encoding — ICU answers a
  // single U+FFFD for any non-empty input, which is neither CPython's answer nor a useful
  // one — so they stay on the UTF-8 fallback `decodeCharset` documents for a module this
  // port has no decoder for. MEASURED: on these bytes CPython's own `hz` and `utf_7` answer
  // the ASCII passthrough, so the port is byte-identical to the reference for both.
  const buf = Buffer.from('1b244224332473244b2441244f1b2842', 'hex');
  const passthrough = '\x1b$B$3$s$K$A$O\x1b(B';
  assert.equal(decodeCharset(buf, 'hz'), passthrough);
  assert.equal(decodeCharset(buf, 'utf-7'), passthrough);
  assert.equal(decodeCharset(buf, 'iso-2022-kr'), passthrough);
});

// ---- M1: a member read TOLERANTLY costs that member, never the document -----------------

test('an optional member this port cannot decompress does not refuse the document (M1)', () => {
  // Found independently by I1 (from the reference) and I2 (from here). `ZipReader.read`
  // answers methods 12 and 14 with a `DocumentReadError` — the ruled bzip2/lzma sentence —
  // and `isUnreadableOptional` did not name that class, so the refusal escaped the tolerant
  // read of `xl/styles.xml` and refused the WHOLE workbook. MEASURED before the fix, on
  // this fixture: `DocumentReadError: bzip2-optional-styles.xlsx is a zip but its
  // xl/styles.xml uses compression method 12 (bzip2), which the Node server cannot
  // decompress (the Python server reads it); see docs/porting.md` — no manifest, no parts.
  //
  // The reference reads the whole workbook here: its `zipfile` decompresses the styles
  // through the stdlib `bz2`. What `docs/porting.md`'s bzip2 row rules is a REQUIRED member,
  // where the two runtimes genuinely answer different things; it has no optional-member
  // fixture, so this divergence was unruled AND unpinned. No cell in this fixture is
  // date-styled, so what `styles.xml` would have said changes nothing and the two runtimes
  // answer the same bytes — the docread suite compares them live.
  const doc = extract(paths['bzip2-optional-styles.xlsx']);
  assert.equal(doc.kind, 'xlsx');
  assert.deepEqual(doc.parts.map((p) => [p.name, [...p.rows]]), [['Sales', ['ok']]]);
  assert.deepEqual(omitted(doc.parts[0]), []);
  // The SAME method on a REQUIRED member is still the ruling, word for word.
  assert.throws(() => extract(paths['bzip2.docx']), {
    name: 'DocumentReadError',
    message:
      'bzip2.docx is a zip but its word/document.xml uses compression method 12 (bzip2), ' +
      'which the Node server cannot decompress (the Python server reads it); see docs/porting.md',
  });
});


// ---- job44 U2: the ceilings a bounded file could otherwise blow past ---------------------
//
// The mirror of `runtime-py/tests/test_docread_ceilings.py` (U1), entries (v), (k) and (w) of
// `docs/roadmap-toolbox.md` row 8, plus the port-only (a)/(j). Every SENTENCE and every
// subject below is the reference's, byte for byte — `tools/conformance` compares them, so a
// wording change here that is not also made there is a divergence and not a preference.
//
// Where the Python tests vary `TEXT_MAX_BYTES` with a monkeypatch, these use files that
// actually cross the shipped ceiling: an ESM `const` export cannot be reassigned, and a
// ceiling only a patched constant has ever met is a ceiling nobody measured.

test('a workbook cannot materialise unbounded text out of a bounded file (v)', () => {
  // MEASURED on both runtimes before the fix (register row 8, item (v)): 20,000 rows each
  // holding ONE `XFD1` cell deflate to 53,967 B and materialise 327,680,000 B in ~9 s —
  // 6,072x. `XLSX_MAX_COLUMNS` bounds how wide one ROW may get and nothing bounded the
  // document, so the amplification was bought a row at a time.
  //
  // 2,000 rows rather than the register's 20,000: the ceiling bites at the SAME row either
  // way (a row is 16,383 tabs + one character = 16,384 B, and 16,777,216 / 16,384 is 1,024),
  // and a fixture that costs 32 MB before the fix says what one costing 327 MB says.
  const rows = [];
  for (let i = 1; i <= 2000; i += 1) rows.push(`<row r="${i}">${inline(`XFD${i}`, 'x')}</row>`);
  const path = join(dir, 'wide-document.xlsx');
  writeFileSync(path, xlsxBytes([['S', 'worksheets/sheet1.xml', rows.join('')]], { deflate: true }));
  assert.ok(readFileSync(path).length < 100_000); // a bounded file in
  const doc = extract(path);
  assert.ok(doc.textBytes <= docread.XLSX_MAX_TEXT_BYTES + 16_384, String(doc.textBytes));
  assert.equal(doc.parts[0].rowCount, 1024); // 16 MiB / 16,384 bytes a row, exactly
  assert.deepEqual(
    doc.omissions.map((o) => [o.subject, o.count, o.size, [...o.where], o.what]),
    [['size-cap', 976, 0, [], '2000 rows in this workbook; this reader renders 16777216 bytes of cell text']],
  );
});

test('the workbook budget is the DOCUMENT\'s and not one sheet\'s (v)', () => {
  // A per-sheet budget would let an N-sheet workbook materialise N budgets. The count is the
  // document's too: every row no sheet rendered is in the one omission, so a caller reads one
  // number for "what this workbook did not give me" rather than summing across parts.
  const wide = (n) => {
    const out = [];
    for (let i = 1; i <= n; i += 1) out.push(`<row r="${i}">${inline(`XFD${i}`, 'x')}</row>`);
    return out.join('');
  };
  const path = join(dir, 'wide-two-sheets.xlsx');
  writeFileSync(
    path,
    xlsxBytes([['First', 'worksheets/sheet1.xml', wide(700)], ['Second', 'worksheets/sheet2.xml', wide(700)]], {
      deflate: true,
    }),
  );
  const doc = extract(path);
  assert.deepEqual(doc.parts.map((p) => [p.name, p.rowCount]), [['First', 700], ['Second', 324]]);
  assert.deepEqual(
    doc.omissions.map((o) => [o.subject, o.count, o.what]),
    [['size-cap', 376, '1400 rows in this workbook; this reader renders 16777216 bytes of cell text']],
  );
});

test('a workbook under the budget says nothing about it (v)', () => {
  // The ceiling must be invisible to every real workbook. MEASURED 2026-09-06 over the goal's
  // roots: 15 `.xlsx`, largest 8,664,227 B on disk, largest RENDERING 754,520 B — 22x under.
  // An omission on any of them would be a false disclosure, the same defect wearing the other
  // sign. The one-row `XFD1` fixture is the widest row this reader will build.
  const doc = extract(xlsx('xfd-budget.xlsx', oneRow(inline('XFD1', 'end'))));
  assert.deepEqual([...doc.parts[0].rows], ['\t'.repeat(16383) + 'end']);
  assert.deepEqual(doc.omissions, []);
  assert.deepEqual(doc.parts[0].omissions, []);
});

test('the workbook budget has its own name and can move alone (v)', () => {
  // Named, not inlined, and NOT an alias of `TEXT_MAX_BYTES` — the two bound different things
  // (bytes read off a disk, bytes rendered out of a container), and a bar that varies one must
  // not silently be varying the other.
  assert.equal(docread.XLSX_MAX_TEXT_BYTES, 16 * 1024 * 1024);
  const source = readFileSync(new URL('../src/docread.ts', import.meta.url), 'utf8');
  assert.ok(source.includes('export const XLSX_MAX_TEXT_BYTES = 16 * 1024 * 1024;'));
  assert.ok(!source.includes('XLSX_MAX_TEXT_BYTES = TEXT_MAX_BYTES'));
});

test('an html file is read to the ceiling and says how much it left (k)', () => {
  // `extractHtml` did `readFileSync(path)`: a 1 GB `.html` was held whole, where a 1 GB `.txt`
  // stops at `TEXT_MAX_BYTES` six lines below and counts the rest. Same ceiling and the SAME
  // SENTENCE — this reader states one number for "how much of a file I read", not one per
  // container.
  const path = join(dir, 'huge.html');
  // One giant text run rather than two million elements: the ceiling is what is under test,
  // and a 17 MiB fixture that also costs 17 MiB of parsing costs the suite for nothing.
  const chunks = ['<html><body><p>first</p><p>', 'a'.repeat(17 * 1024 * 1024), '</p><p>last</p></body></html>'];
  writeFileSync(path, chunks.join(''));
  const size = readFileSync(path).length;
  assert.ok(size > TEXT_MAX_BYTES);
  const doc = extract(path);
  assert.equal(doc.kind, 'html');
  assert.equal(doc.parts[0].rows[0], 'first');
  assert.ok(!doc.parts[0].rows.includes('last'));
  assert.deepEqual(
    doc.omissions.map((o) => [o.subject, o.count, o.size, [...o.where], o.what]),
    [['size-cap', size - TEXT_MAX_BYTES, size - TEXT_MAX_BYTES, [], `${size} bytes on disk; this reader reads ${TEXT_MAX_BYTES}`]],
  );
});

test('an html file under the ceiling is unchanged and discloses nothing (k)', () => {
  const path = join(dir, 'small.html');
  writeFileSync(path, '<html><body><p>one</p><p>two</p></body></html>');
  const doc = extract(path);
  assert.deepEqual([...doc.parts[0].rows], ['one', 'two']);
  assert.deepEqual(doc.omissions, []);
});

test('an mhtml archive is read to the ceiling and says how much it left (k)', () => {
  // `readFileSync(path).toString('latin1')` fed the WHOLE file to the MIME parser. The
  // register named the reference's line off a grep and did not read the mhtml half line by
  // line; read line by line, both halves were unbounded, each in its own spelling.
  const path = join(dir, 'huge.mhtml');
  const chunks = [
    'MIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nfirst\r\n',
    'a'.repeat(17 * 1024 * 1024),
    '\r\nlast\r\n',
  ];
  writeFileSync(path, chunks.join(''));
  const size = readFileSync(path).length;
  assert.ok(size > TEXT_MAX_BYTES);
  const doc = extract(path);
  assert.equal(doc.kind, 'mhtml');
  assert.equal(doc.parts[0].rows[0], 'first');
  assert.ok(!doc.parts[0].rows.includes('last'));
  assert.deepEqual(
    doc.omissions.map((o) => [o.subject, o.count, o.size, [...o.where], o.what]),
    [['size-cap', size - TEXT_MAX_BYTES, size - TEXT_MAX_BYTES, [], `${size} bytes on disk; this reader reads ${TEXT_MAX_BYTES}`]],
  );
});

test('a duplicate cell reference is disclosed instead of dropped in silence (w)', () => {
  // MEASURED before the fix, on this exact fixture: `('second',)` and ZERO omissions, on both
  // runtimes. Last-wins is KEPT — it is what both do and what a writer's own later cell means.
  // The silence is the defect: every other cell this reader cannot place is disclosed, and a
  // cell it placed another cell on top of is a cell the rows do not carry.
  const doc = extract(xlsx('dup-ref.xlsx', oneRow(inline('A1', 'first'), inline('A1', 'second'))));
  assert.deepEqual([...doc.parts[0].rows], ['second']);
  assert.deepEqual(omitted(doc.parts[0]), [['duplicate-cell', 1, ['A'], docread.DUPLICATE_CELL]]);
  assert.equal(docread.DUPLICATE_CELL, 'the text of a cell a later cell in the same row and column replaced');
  assert.equal(docread.OMIT_DUPLICATE_CELL, 'duplicate-cell');
});

test('the duplicate omission never echoes the file\'s own reference (w)', () => {
  // `UNPLACED_SHAPE`'s rule, one omission over: `r` is whatever the file says, and an omission
  // that echoed it would carry the file's bytes into the manifest with no bound at all. The
  // column LETTER is derived and bounded; the reference is not.
  const ref = 'AAAA1'; // past XFD, so it falls back to its XML position — column A twice
  const doc = extract(xlsx('dup-echo.xlsx', oneRow(inline('A1', 'first'), inline(ref, 'second'))));
  const rendered = doc.parts[0].omissions.map((o) => o.what).join(' ');
  assert.ok(!rendered.includes('AAAA'));
});

test('duplicates are counted across the sheet with their columns in order (w)', () => {
  // One omission for the sheet, columns in column order — the shape `number-format` and
  // `unplaced-cell` already use, so a caller that renders one renders this one. It is rendered
  // AFTER the unplaced reasons, which is the reference's tuple order.
  const body =
    oneRow(inline('C1', 'a'), inline('C1', 'b'), inline('C1', 'c')) +
    `<row r="2">${inline('A2', 'd')}${inline('A2', 'e')}</row>` +
    `<row r="3">${inline('B3', 'f')}</row>`;
  const doc = extract(xlsx('dups.xlsx', body));
  assert.deepEqual([...doc.parts[0].rows], ['\t\tc', 'e', '\tf']);
  assert.deepEqual(omitted(doc.parts[0]), [['duplicate-cell', 3, ['A', 'C'], docread.DUPLICATE_CELL]]);
});

test('an empty cell on top of a full one is not a duplicate (w)', () => {
  // A cell with no text was never going to be in the rows, so it replaced nothing. Counting it
  // would inflate the disclosure with cells nobody lost.
  const doc = extract(
    xlsx('dup-blank.xlsx', oneRow(inline('A1', 'kept'), '<c r="A1" t="inlineStr"><is><t></t></is></c>')),
  );
  assert.deepEqual([...doc.parts[0].rows], ['kept']);
  assert.deepEqual(doc.parts[0].omissions, []);
});

test('a duplicate renders through the contract layer\'s generic omission line (w)', () => {
  // `omissionLine` has no branch for this subject and does not need one: the generic line
  // prints an unknown subject's count rather than dropping it. Pinned here so the lag between
  // the two layers stays a slightly generic sentence and never a lost count.
  const doc = extract(xlsx('dup-line.xlsx', oneRow(inline('A1', 'first'), inline('A1', 'second'))));
  const lines = contract.documentManifest([
    {
      document: 'dup-line.xlsx',
      kind: 'xlsx',
      index: 1,
      part: 'S',
      row_count: 1,
      rows: [...doc.parts[0].rows],
      omissions: doc.parts[0].omissions.map((o) => o.asDict()),
    },
  ]).split('\n');
  assert.ok(
    lines.includes(
      '  NOT in those rows: 1 duplicate-cell (the text of a cell a later cell in the same row and column replaced)',
    ),
    lines.join('\n'),
  );
});

test('one extract reads the archive from disk ONCE, measured and not read off the source (a)(j)', () => {
  // `sniff` opened the archive to list its members and the extractor opened it again: two
  // whole-file `readFileSync` per call, MEASURED at 2 before the fix. A code reading is not
  // the gate — the count is taken in a child process whose `node:fs` is wrapped BEFORE any
  // ESM facade for `node:fs` exists, so the wrapper IS the binding `docread.js` resolved.
  const preload = join(dir, 'count-fs.cjs');
  writeFileSync(
    preload,
    "const fs = require('fs');\n" +
      'const counts = Object.create(null);\n' +
      'globalThis.__fsByPath = counts;\n' +
      'const real = fs.readFileSync;\n' +
      'fs.readFileSync = function (p, ...rest) {\n' +
      '  counts[String(p)] = (counts[String(p)] || 0) + 1;\n' +
      '  return real.call(this, p, ...rest);\n' +
      '};\n',
  );
  const driver = join(dir, 'count-fs.mjs');
  writeFileSync(
    driver,
    `const d = await import(${JSON.stringify(new URL('docread.js', dist).href)});\n` +
      'const p = process.argv[2];\n' +
      'const before = globalThis.__fsByPath[p] || 0;\n' +
      'const doc = d.extract(p);\n' +
      'const after = globalThis.__fsByPath[p] || 0;\n' +
      'process.stdout.write(JSON.stringify({ reads: after - before, rows: doc.parts[0].rows.length }));\n',
  );
  const reads = (path) =>
    JSON.parse(execFileSync(process.execPath, ['--require', preload, driver, path], { encoding: 'utf8' }));
  const book = join(dir, 'read-once.xlsx');
  writeFileSync(book, xlsxBytes([['S', 'worksheets/sheet1.xml', oneRow(inline('A1', 'x'))]], { deflate: true }));
  assert.deepEqual(reads(book), { reads: 1, rows: 1 });
  // The other OOXML container goes through the same `openZip`, so it is the same defect.
  const word = join(dir, 'read-once.docx');
  writeFileSync(word, docxBytes('<w:p><w:r><w:t>x</w:t></w:r></w:p>', { deflate: true }));
  assert.deepEqual(reads(word), { reads: 1, rows: 1 });
});

test('the sniffed reader does not outlive the call that made it (a)(j)', () => {
  // The correctness trap the efficiency fix opens, and the reason the reader is a local and
  // never a field: a reader held across calls answers from bytes no longer on disk. Rewriting
  // the file between two extracts must change the answer — the same property the single-entry
  // document cache one layer up (entry (i), U5) is keyed on.
  const path = join(dir, 'rewritten.xlsx');
  writeFileSync(path, sheet(oneRow(inline('A1', 'before'))));
  assert.deepEqual([...extract(path).parts[0].rows], ['before']);
  writeFileSync(path, sheet(oneRow(inline('A1', 'after'))));
  assert.deepEqual([...extract(path).parts[0].rows], ['after']);
});

test('the CPython semantics ported twice are now one module, and answer identically (n)', async () => {
  // Entry (n): `pyStrip`, `cmpCodepoint` and `pyRepr` were each written twice. The gate before
  // unifying was a DIFF, not a reading — see the U2 handoff for the numbers. This pins the
  // outcome: the exported names still exist where they always did, and they are the same
  // function object, so the two spellings cannot drift apart again.
  const pysem = await import(new URL('pysem.js', dist));
  const factfile = await import(new URL('memory/factfile.js', dist));
  const pyfs = await import(new URL('memory/pyfs.js', dist));
  assert.equal(docread.pyStrip, pysem.pyStrip);
  assert.equal(factfile.pyStrip, pysem.pyStrip);
  assert.equal(docread.cmpCodepoint, pysem.cmpCodepoint);
  assert.equal(pyfs.cmpCodepoint, pysem.cmpCodepoint);
  assert.equal(docread.pyRepr, pysem.pyRepr);
  assert.equal(pyfs.pyRepr, pysem.pyRepr);
  // The six codepoints `String.prototype.trim` and `str.strip()` disagree on, and the astral
  // ordering `Array.sort` gets wrong — the reasons each copy existed, held by the one left.
  assert.equal(pysem.pyStrip('\x1cx\x85'), 'x');
  assert.equal(pysem.pyStrip('﻿x﻿'), '﻿x﻿');
  assert.ok(pysem.cmpCodepoint('\u{1F414}', '！') > 0);
  assert.equal(pysem.pyRepr("it's"), '"it\'s"');
});

// ---- job44 F2: review round 5, the three HIGH findings against U1/U2's own work -----------
//
// The mirror of `runtime-py/tests/test_docread_ceilings.py`'s round-2 block. Every sentence is
// the reference's, byte for byte, and was CONFIRMED by running `runtime-py/src/bantamkit/
// docread.py` over the same bytes rather than by reading it.
//
// One thing here is NOT a copy, and it is why the shape differs from the reference's. F1's
// gate refuses on the size the central directory DECLARES, and it needed no second ceiling
// because `zipfile.ZipExtFile` clamps its own output to `ZipInfo.file_size`. This half's
// `ZipReader` is hand-written and MEASURED not to clamp: before `ZipReader.read` took a
// `maxOutputLength`, a member declaring 10 bytes over a 19,600,112-byte deflate stream
// inflated all 19,600,112, passed the CRC, and rendered 400,000 rows. The mechanism is
// therefore two ceilings where the reference has one; the ANSWERS are identical on both sides
// of the lie, which is what the last test in this block pins.

/** The reviewer's own input: `count` rows each holding one inline-string cell of one `x`. */
const inlineRows = (count) => '<row><c t="inlineStr"><is><t>x</t></is></c></row>'.repeat(count);

test('a bounded zip cannot make this reader parse unbounded xml (v round 2)', () => {
  // MEASURED before this fix, on THIS runtime, at the shipped constants, peak RSS from
  // `process.resourceUsage().maxRSS`:
  //
  // | rows      | file on disk | member declares | RSS during `extract` | omissions |
  // |-----------|--------------|-----------------|----------------------|-----------|
  // |   400,000 |     58,378 B |    19,600,112 B | 102.2 -> 1,039.3 MB  | `[]`      |
  // | 1,000,000 |    143,939 B |    49,000,112 B | 158.6 -> 2,290.8 MB  | `[]`      |
  //
  // Linear and unbounded, and `XLSX_MAX_TEXT_BYTES` never sees it: `readMember` decompresses
  // the member whole and `parsePart` builds a tree from it, both before the first row is
  // rendered. The tree is where the memory goes — 19.2 MB of member XML became a gigabyte of
  // `XmlElement`. After: 2 ms and no growth at all, because nothing is inflated.
  const path = join(dir, 'rows.xlsx');
  writeFileSync(path, xlsxBytes([['S', 'worksheets/sheet1.xml', inlineRows(400_000)]], { deflate: true }));
  assert.ok(readFileSync(path).length < 100_000); // a file small enough to mail
  const declared = ZipReader.open(path).declaredSize('xl/worksheets/sheet1.xml');
  assert.ok(declared > docread.ZIP_MEMBER_MAX_BYTES);
  assert.throws(() => extract(path), {
    name: 'DocumentReadError',
    message:
      `rows.xlsx is a zip but its xl/worksheets/sheet1.xml declares ${declared} bytes uncompressed, ` +
      `past the ${docread.ZIP_MEMBER_MAX_BYTES} bytes this reader parses, so this reader cannot parse it`,
  });
});

test('the shared string table is the same door one call earlier (v round 2)', () => {
  // `sharedStrings` reached the archive before any sheet did, so a gate only on the worksheet
  // would have left the workbook's biggest part wide open — and it went through `zf.read`
  // rather than `readMember`, so it had neither this ceiling nor the reader's own sentences
  // for a damaged or encrypted table. One gate in `readMember` covers every member this
  // reader cannot do without: the two here, `xl/workbook.xml`, its rels, `word/document.xml`
  // and an ODF `mimetype`.
  const path = join(dir, 'shared.xlsx');
  writeFileSync(
    path,
    xlsxBytes([['S', 'worksheets/sheet1.xml', '<row r="1"><c r="A1" t="s"><v>0</v></c></row>']], {
      shared: ['x'.repeat(17 * 1024 * 1024)],
      deflate: true,
    }),
  );
  const declared = ZipReader.open(path).declaredSize('xl/sharedStrings.xml');
  assert.ok(declared > docread.ZIP_MEMBER_MAX_BYTES);
  assert.throws(() => extract(path), {
    name: 'DocumentReadError',
    message:
      `shared.xlsx is a zip but its xl/sharedStrings.xml declares ${declared} bytes uncompressed, ` +
      `past the ${docread.ZIP_MEMBER_MAX_BYTES} bytes this reader parses, so this reader cannot parse it`,
  });
});

test('a word document part is bounded by the same member ceiling (k round 2)', () => {
  // `.docx` had no ceiling of any kind — the (k) principle claimed one number for "how much of
  // a file this reader reads" while `extractDocx` rendered every `<w:t>` with no budget and no
  // omission. MEASURED before this fix on this runtime, on 100 runs of 400,000 `y`: a
  // 41,254-byte `.docx` rendered 40,000,099 bytes of text in 306 ms — 2.38x `TEXT_MAX_BYTES`
  // — with `doc.omissions` and `part.omissions` both empty. After: refused in 0 ms.
  //
  // The ceiling lands on the member rather than on the rendering because that is where the
  // memory is spent, and because the rendering of an OOXML part can never exceed the bytes of
  // the part: 40 MB of text needs 40 MB of `<w:t>` to come out of.
  const path = join(dir, 'big.docx');
  writeFileSync(path, docxBytes(`<w:p><w:r><w:t>${'y'.repeat(17 * 1024 * 1024)}</w:t></w:r></w:p>`, { deflate: true }));
  const declared = ZipReader.open(path).declaredSize('word/document.xml');
  assert.ok(declared > docread.ZIP_MEMBER_MAX_BYTES);
  assert.throws(() => extract(path), {
    name: 'DocumentReadError',
    message:
      `big.docx is a zip but its word/document.xml declares ${declared} bytes uncompressed, ` +
      `past the ${docread.ZIP_MEMBER_MAX_BYTES} bytes this reader parses, so this reader cannot parse it`,
  });
});

test('the member ceiling has its own name and the workbook budget no longer overclaims (v)', () => {
  // Two claims, both of them source facts and both of them shipped: the ceiling is a named
  // constant a bar can vary, and the sentence beside `XLSX_MAX_TEXT_BYTES` that said the file
  // was already bounded is gone. That sentence was false for the whole life of the (v)
  // closure and it is the reason the parse was never looked at.
  assert.equal(docread.ZIP_MEMBER_MAX_BYTES, 16 * 1024 * 1024);
  const source = readFileSync(new URL('../src/docread.ts', import.meta.url), 'utf8');
  assert.ok(source.includes('export const ZIP_MEMBER_MAX_BYTES = 16 * 1024 * 1024;'));
  // The false clause is gone as a CLAIM. It survives only inside the correction that names it
  // false, which is the record of why (v) shipped half-closed and is worth keeping.
  assert.ok(!source.includes('because the file is already bounded and the'));
  assert.ok(source.includes('"because the file is already bounded", and that was FALSE'));
});

test('an ordinary workbook is far under the member ceiling and invents no refusal (v)', () => {
  // A ceiling no real file meets, stated as a measurement rather than a hope. The reference
  // measured the corpus: 25 OOXML/ODF packages under the goal's roots, the largest single XML
  // member 4,283,286 B — 3.9x under this — and the largest `word/document.xml` 159,976 B.
  // Held on a fixture rather than on the corpus, because the corpus is this machine's.
  const path = xlsx('ordinary-member.xlsx', oneRow(inline('A1', 'first')) + `<row r="2">${inline('A2', 'second')}</row>`);
  const zf = ZipReader.open(path);
  assert.ok(Math.max(...zf.infolist().map((i) => i.fileSize)) * 4000 < docread.ZIP_MEMBER_MAX_BYTES);
  const doc = extract(path);
  assert.deepEqual([...doc.parts[0].rows], ['first', 'second']);
  assert.deepEqual(doc.omissions, []);
});

test('a member that declares less than it holds cannot slip past the gate (v round 2)', () => {
  // THE ONE THING THAT IS NOT A COPY. The gate reads the central directory, which is the
  // ATTACKER's bytes, so this asks what a lying declaration BUYS rather than asserting from
  // the source that it buys nothing.
  //
  // MEASURED on the reference: `ZipExtFile` clamps its output to `ZipInfo.file_size` and CRCs
  // what it produced, so a member declaring 10 bytes while holding 19,600,112 yields 10 bytes
  // and `Bad CRC-32`. MEASURED here BEFORE this fix, on the identical bytes: `ZipReader.read`
  // returned all 19,600,112, the CRC passed (it covers the real content), and `extract`
  // rendered 400,000 rows with no omission — the declared-size gate walked past by one 4-byte
  // edit. `maxOutputLength` is that clamp with a hard stop instead of a truncation, and the
  // sentence is the CRC check's own, which is what the reference prints for this file.
  const path = join(dir, 'lie.xlsx');
  const raw = xlsxBytes([['S', 'worksheets/sheet1.xml', inlineRows(400_000)]], { deflate: true });
  const member = Buffer.from('xl/worksheets/sheet1.xml', 'utf8');
  let central = raw.lastIndexOf('PK\x01\x02', raw.length, 'latin1');
  while (!raw.subarray(central + 46, central + 46 + member.length).equals(member)) {
    central = raw.lastIndexOf('PK\x01\x02', central - 1, 'latin1');
    assert.notEqual(central, -1);
  }
  raw.writeUInt32LE(10, central + 24); // the DECLARED uncompressed size, and nothing else
  writeFileSync(path, raw);
  const zf = ZipReader.open(path);
  assert.equal(zf.declaredSize('xl/worksheets/sheet1.xml'), 10);
  assert.ok(10 < docread.ZIP_MEMBER_MAX_BYTES); // the declared-size gate lets this through
  assert.throws(() => zf.read('xl/worksheets/sheet1.xml'), {
    name: 'BadZipFile',
    message: "Bad CRC-32 for file 'xl/worksheets/sheet1.xml'",
  });
  assert.throws(() => extract(path), {
    name: 'DocumentReadError',
    message:
      "lie.xlsx is a zip but its xl/worksheets/sheet1.xml is damaged (Bad CRC-32 for file " +
      "'xl/worksheets/sheet1.xml'), so this reader cannot read it",
  });
});

test('an html refusal reached under the cap says the reader stopped early (w round 2)', () => {
  // MEASURED before this fix, on the reviewer's own input — a 16 MiB comment inside `<script>`
  // followed by one visible sentence:
  //
  //     cannot read big2.html: it is a html container but its markup carried no text outside
  //     script and style, so this reader has no text for it — it is not an empty document
  //
  // The document DOES carry text. `extractHtml` built the `Document` with the `size-cap`
  // omission in it and handed it to `nonempty`, which raises — and the refusal carried the
  // reader's verdict about the content while the cap that produced that verdict was discarded.
  // This is the finding most likely to reach a real user: a caller reading that sentence
  // concludes the file is empty and stops.
  const path = join(dir, 'big2.html');
  writeFileSync(
    path,
    `<html><script>/*${'a'.repeat(TEXT_MAX_BYTES)}*/</script><p>the only sentence in this document</p></html>`,
  );
  const size = readFileSync(path).length;
  assert.ok(size > TEXT_MAX_BYTES);
  assert.throws(() => extract(path), {
    name: 'DocumentReadError',
    message:
      'cannot read big2.html: it is a html container but its markup carried no text outside ' +
      `script and style in the part this reader read (${size} bytes on disk; this reader reads ` +
      `${TEXT_MAX_BYTES}) — the ${size - TEXT_MAX_BYTES} bytes it did not read may carry text`,
  });
});

test('an mhtml refusal under the cap keeps the media tally too (w round 2)', () => {
  // The reviewer's second input: a base64 `image/png` part and then a `text/plain` part past
  // the ceiling. Both the `size-cap` AND the media tally were lost — the answer was the bare
  // `no text/html or text/plain part carried any text`.
  //
  // The media clause is not decoration. It is the difference between "this file holds nothing
  // I can read" and "this file holds one embedded object and I stopped before the text".
  const path = join(dir, 'big.mht');
  writeFileSync(
    path,
    'MIME-Version: 1.0\r\nContent-Type: multipart/related; boundary="B"\r\n\r\n--B\r\n' +
      'Content-Type: image/png\r\nContent-Transfer-Encoding: base64\r\n\r\n' +
      'iVBORw0KGgo='.repeat(TEXT_MAX_BYTES / 12) +
      '\r\n\r\n--B\r\nContent-Type: text/plain\r\n\r\nthe only sentence in this document\r\n--B--\r\n',
  );
  const size = readFileSync(path).length;
  assert.ok(size > TEXT_MAX_BYTES);
  assert.throws(() => extract(path), {
    name: 'DocumentReadError',
    message:
      'cannot read big.mht: it is a mhtml container but no text/html or text/plain part ' +
      `carried any text in the part this reader read (${size} bytes on disk; this reader reads ` +
      `${TEXT_MAX_BYTES}) — the ${size - TEXT_MAX_BYTES} bytes it did not read may carry text, ` +
      'and it holds 1 embedded part(s) (image/png) this reader renders no text for',
  });
});

test('a refusal with media behind it names the media it could not render (w round 2)', () => {
  // No cap here, so the verdict about the text IS true — and the file is still not empty.
  // `nonempty` threw every omission away, media included, on every path out of it.
  const path = join(dir, 'picture.mht');
  writeFileSync(
    path,
    'MIME-Version: 1.0\n' +
      'Content-Type: multipart/related; boundary="B"\n\n' +
      '--B\nContent-Type: image/png\nContent-Transfer-Encoding: base64\n\niVBORw0KGgo=\n\n--B--\n',
  );
  assert.throws(() => extract(path), {
    name: 'DocumentReadError',
    message:
      'cannot read picture.mht: it is a mhtml container but no text/html or text/plain part ' +
      'carried any text, so this reader has no text for it — it is not an empty document, ' +
      'and it holds 1 embedded part(s) (image/png) this reader renders no text for',
  });
});

test('a refusal with nothing behind it is the sentence it always was (w round 2)', () => {
  // The common case does not move. An empty `.html` with no cap and no media still refuses in
  // the words `docs/porting.md` pins, `docread-expected.jsonl` records and
  // `tools/conformance` compares.
  const path = join(dir, 'empty-round2.html');
  writeFileSync(path, '<html><body><script>var x = 1;</script></body></html>');
  assert.throws(() => extract(path), {
    name: 'DocumentReadError',
    message:
      'cannot read empty-round2.html: it is a html container but its markup carried no text ' +
      'outside script and style, so this reader has no text for it — it is not an empty document',
  });
  // And the two fixtures the reference's own answers are recorded for take the same branch —
  // `blank.html` and `noboundary.mht` in `docread-expected.jsonl`, unchanged by this round.
  for (const fixture of ['blank.html', 'noboundary.mht']) {
    assert.equal(dump(paths[fixture]).message, expected.get(fixture).message);
  }
});
