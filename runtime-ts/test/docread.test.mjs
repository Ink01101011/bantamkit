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
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';

import { writeFixtures, zipBytes } from './docread-fixtures.mjs';

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
  bytesRepr,
  decodeQuotedPrintable,
  extract,
  page,
  pyRepr,
  sniff,
  unescape,
  utf8Scan,
} = docread;

const dir = mkdtempSync(join(tmpdir(), 'docread-'));
after(() => rmSync(dir, { recursive: true, force: true }));
const paths = writeFixtures(dir);

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
    throw err;
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

// The kinds this half identifies and refuses where the reference reads them.
const DIVERGENT = new Map([
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

test('every fixture the reference reads or refuses gets the same bytes from the port', () => {
  assert.equal(expected.size, Object.keys(paths).length, 'one Python line per fixture');
  let compared = 0;
  for (const [name, path] of Object.entries(paths)) {
    if (DIVERGENT.has(name)) continue;
    const want = { ...expected.get(name) };
    delete want.fixture;
    if (want.message) want.message = want.message.replaceAll('{dir}', dir);
    assert.deepEqual(dump(path), want, name);
    compared += 1;
  }
  assert.equal(compared, expected.size - DIVERGENT.size);
});

test('pdf, doc and rtf are identified by sniff and refused by the Node sentence, which differs from the reference', () => {
  for (const [name, sentence] of DIVERGENT) {
    const kind = sniff(paths[name]).kind;
    assert.ok(['pdf', 'doc', 'rtf'].includes(kind), `${name} sniffs as ${kind}`);
    const got = dump(paths[name]);
    assert.deepEqual(got, { error: 'DocumentReadError', message: sentence }, name);
    const python = expected.get(name);
    assert.notDeepEqual(
      { error: python.error, message: python.message },
      got,
      `${name}: the reference answers something else, which is what the ruling records`,
    );
  }
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
