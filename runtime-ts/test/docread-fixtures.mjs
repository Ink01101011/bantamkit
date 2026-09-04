/**
 * The fixtures `test/docread.test.mjs` reads, built from bytes — the same zip layout and
 * the same XML `runtime-py/tests/test_docread.py` writes with `zipfile`, so the Python
 * reference can be run over the SAME files to obtain every expected literal. Not a test
 * file (no `.test.mjs` suffix): `scripts/run-tests.mjs` does not collect it, and the
 * differential harness in the R3 commit message imports it to lay the fixtures on disk.
 *
 * The zip writer is deliberately tiny: local headers, a central directory, an EOCD,
 * CRC-32, stored or deflated entries. `zipfile.writestr` writes stored entries by
 * default, which is what the Python fixtures are; `deflate: true` exercises the other
 * branch of `ZipReader.read`.
 */
import { mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { deflateRawSync } from 'node:zlib';

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

function crc32(buf) {
  let crc = -1;
  for (const b of buf) crc = CRC_TABLE[(crc ^ b) & 0xff] ^ (crc >>> 8);
  return (crc ^ -1) >>> 0;
}

/**
 * `entries` is `[[name, string | Buffer], ...]` in write order. A payload may also be a
 * PRE-COMPRESSED member, `{ method, raw, crc, size }` — how the bzip2 and lzma rulings get
 * their bytes: Node has no compressor for either, so the member is the one CPython's
 * `zipfile` wrote (`ZipFile.writestr(..., compress_type=ZIP_BZIP2|ZIP_LZMA)`, job43 G2),
 * carried here as hex and laid into this writer's own container.
 */
export function zipBytes(entries, { deflate = false } = {}) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const [name, payload] of entries) {
    const nameBytes = Buffer.from(name, 'utf8');
    const pre = payload !== null && typeof payload === 'object' && !Buffer.isBuffer(payload);
    const data = pre ? Buffer.alloc(payload.size) : Buffer.isBuffer(payload) ? payload : Buffer.from(payload, 'utf8');
    const stored = pre ? payload.raw : deflate ? deflateRawSync(data) : data;
    const method = pre ? payload.method : deflate ? 8 : 0;
    const crc = pre ? payload.crc : crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x800, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(stored.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    locals.push(local, nameBytes, stored);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0x800, 8);
    central.writeUInt16LE(method, 10);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(stored.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, nameBytes);
    offset += 30 + nameBytes.length + stored.length;
  }
  const cd = Buffer.concat(centrals);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(cd.length, 12);
  eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, cd, eocd]);
}

export const CONTENT_TYPES =
  '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
  '<Default Extension="xml" ContentType="application/xml"/>' +
  '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/></Types>';
export const ROOT_RELS =
  '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
  '<Relationship Id="rIdWb" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
  '</Relationships>';
export const SHEET_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"';
export const REL_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"';
export const WORD_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';
export const DRAWING_RELS = (inner) =>
  `<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${inner}</Relationships>`;

/** `sheets` is `[[display name, part path, sheet XML body], ...]` in DECLARATION order. */
export function xlsxBytes(sheets, { shared = null, extra = {}, ridAttr = true, deflate = false } = {}) {
  const entries = [
    ['[Content_Types].xml', CONTENT_TYPES],
    ['_rels/.rels', ROOT_RELS],
  ];
  const decls = [];
  const rels = [];
  sheets.forEach(([name, target, body], i) => {
    const rid = `rId${i}`;
    const attr = ridAttr ? ` r:id="${rid}"` : '';
    decls.push(`<sheet name="${name}" sheetId="${i + 1}"${attr}/>`);
    rels.push(
      `<Relationship Id="${rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="${target}"/>`,
    );
    const part = target.startsWith('/') ? target.replace(/^\/+/, '') : `xl/${target}`;
    entries.push([part, `<worksheet ${SHEET_NS}><sheetData>${body}</sheetData></worksheet>`]);
  });
  entries.push(['xl/workbook.xml', `<workbook ${SHEET_NS} ${REL_NS}><sheets>${decls.join('')}</sheets></workbook>`]);
  entries.push([
    'xl/_rels/workbook.xml.rels',
    `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${rels.join('')}</Relationships>`,
  ]);
  if (shared !== null) {
    const items = shared.map((s) => `<si><t>${s}</t></si>`).join('');
    entries.push([
      'xl/sharedStrings.xml',
      `<sst ${SHEET_NS} count="${shared.length}" uniqueCount="${shared.length}">${items}</sst>`,
    ]);
  }
  for (const [name, payload] of Object.entries(extra)) entries.push([name, payload]);
  return zipBytes(entries, { deflate });
}

export function docxBytes(body, { extra = {}, deflate = false } = {}) {
  const entries = [
    ['[Content_Types].xml', CONTENT_TYPES],
    ['_rels/.rels', ROOT_RELS],
    ['word/document.xml', `<w:document ${WORD_NS}><w:body>${body}</w:body></w:document>`],
  ];
  for (const [name, payload] of Object.entries(extra)) entries.push([name, payload]);
  return zipBytes(entries, { deflate });
}

export const row = (cells, index = 1) => `<row r="${index}">${cells.join('')}</row>`;
export const cell = (ref, value, kind = null) => `<c r="${ref}"${kind ? ` t="${kind}"` : ''}><v>${value}</v></c>`;
export const inlineCell = (ref, value) => `<c r="${ref}" t="inlineStr"><is><t>${value}</t></is></c>`;
export const para = (...runs) => '<w:p>' + runs.map((r) => `<w:r><w:t>${r}</w:t></w:r>`).join('') + '</w:p>';

export function escapeAttr(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/** `{part path: [image name, ...]}` -> the extra members that anchor them to their sheets. */
export function mediaPack(sheetMedia) {
  const extra = {};
  Object.entries(sheetMedia)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .forEach(([target, images], i0) => {
      const i = i0 + 1;
      const drawing = `drawing${i}.xml`;
      extra[`xl/worksheets/_rels/${target.split('/').pop()}.rels`] = DRAWING_RELS(
        `<Relationship Id="rIdD" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/${drawing}"/>`,
      );
      extra[`xl/drawings/${drawing}`] = '<xdr/>';
      extra[`xl/drawings/_rels/${drawing}.rels`] = DRAWING_RELS(
        images
          .map(
            (name, j) =>
              `<Relationship Id="rIdI${j}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/${name}"/>`,
          )
          .join(''),
      );
      for (const name of images) extra[`xl/media/${name}`] ??= 'x'.repeat(100);
    });
  return extra;
}

/** `xl/styles.xml` with custom `numFmt` codes from id 164 up and the given `cellXfs`. */
export function styles(codes, xfs) {
  const fmts = codes.map((c, i) => `<numFmt numFmtId="${164 + i}" formatCode="${escapeAttr(c)}"/>`).join('');
  const cellXfs = xfs.map((i) => `<xf numFmtId="${i}"/>`).join('');
  return `<styleSheet ${SHEET_NS}><numFmts>${fmts}</numFmts><cellXfs count="${xfs.length}">${cellXfs}</cellXfs></styleSheet>`;
}

export const MHTML_DOC =
  'Date: Wed, 19 Aug 2026 04:28:21 +0000 (UTC)\n' +
  'Subject: Exported From Confluence\n' +
  'MIME-Version: 1.0\n' +
  'Content-Type: multipart/related; boundary="----=_Part_6"\n' +
  '\n' +
  '------=_Part_6\n' +
  'Content-Type: text/html; charset=UTF-8\n' +
  'Content-Transfer-Encoding: quoted-printable\n' +
  '\n' +
  '<html><head><title>API</title><style>p{color:red}</style></head><body>\n' +
  '<h1>POST /juristic/api/account-service/submission-juma-acct-s=\n' +
  'ignature</h1>\n' +
  '<p>Overview</p>\n' +
  '<table><tr><th>field</th><th>type</th></tr>\n' +
  '<tr><td>account</td><td>string</td></tr></table>\n' +
  '<script>var leaked =3D 1;</script>\n' +
  '</body></html>\n' +
  '\n' +
  '------=_Part_6\n' +
  'Content-Type: image/png\n' +
  'Content-Transfer-Encoding: base64\n' +
  '\n' +
  'iVBORw0KGgo=\n' +
  '\n' +
  '------=_Part_6--\n';

export const MHTML_CRLF = Buffer.from(
  'MIME-Version: 1.0\r\n' +
    'Content-Type: multipart/related; boundary="B"\r\n\r\n' +
    '--B\r\nContent-Type: text/html\r\n\r\n<html><body><p>hello</p></body></html>\r\n' +
    '--B\r\nContent-Type: application/octet-stream\r\n\r\nZZZZZ\r\n' +
    '--B\r\nContent-Type: image/png\r\n\r\nQQ\r\n' +
    '--B--\r\n',
  'latin1',
);

export const MHTML_TWO =
  'MIME-Version: 1.0\n' +
  'Content-Type: multipart/related; boundary="b"\n' +
  '\n--b\nContent-Type: text/html\n\n<p>first</p>\n' +
  '\n--b\nContent-Type: text/plain\n\nsecond\n' +
  '\n--b--\n';

const HEAD_BYTES = 4096;
const ARROW = Buffer.from('→', 'utf8');

/** Text whose 3-byte character has exactly `inside` of its bytes below the head boundary. */
export function straddling(inside) {
  return Buffer.concat([Buffer.alloc(HEAD_BYTES - inside, 0x61), ARROW, Buffer.alloc(64, 0x62)]);
}

/** A body longer than `_HEAD_BYTES`, so `tail` is provably past what `sniff` looked at. */
export function headThen(tail) {
  const lines = [];
  for (let i = 0; i < 200; i += 1) lines.push(`row ${String(i).padStart(4, '0')} ${'a'.repeat(40)}\n`);
  const body = Buffer.from(lines.join(''), 'latin1');
  if (body.length <= HEAD_BYTES) throw new Error('fixture must exceed the head');
  return Buffer.concat([body, tail]);
}

const PAGED_BODY = Array.from({ length: 120 }, (_, k) => {
  const i = k + 1;
  return row([inlineCell(`A${i}`, `row-${String(i).padStart(3, '0')}`)], i);
}).join('');

/**
 * Every fixture, keyed by file name. The names are the suffixes the Python tests use,
 * including the ones that LIE (`api.doc` is MHTML, `named.pdf` is a docx), because the
 * suffix disagreement is part of the sentence under test.
 */
export function fixtures() {
  const lat = (s) => Buffer.from(s, 'latin1');
  const utf = (s) => Buffer.from(s, 'utf8');
  const table = `<w:tbl><w:tr><w:tc>${para('r1c1')}</w:tc><w:tc>${para('r1c2')}</w:tc></w:tr></w:tbl>`;
  return {
    // xlsx: the three traps and the row shape
    'shared.xlsx': xlsxBytes([['data', 'worksheets/sheet1.xml', row([cell('A1', '1', 's'), cell('B1', '0', 's')])]], {
      shared: ['zero', 'one'],
    }),
    'runs.xlsx': xlsxBytes([['data', 'worksheets/sheet1.xml', row([cell('A1', '0', 's')])]], {
      extra: {
        'xl/sharedStrings.xml': `<sst ${SHEET_NS}><si><r><t>Pol</t></r><r><t>icy</t></r><rPh><t>ポリシー</t></rPh></si></sst>`,
      },
    }),
    'badindex.xlsx': xlsxBytes([['data', 'worksheets/sheet1.xml', row([cell('A1', '7', 's')])]], { shared: ['only'] }),
    'both.xlsx': xlsxBytes(
      [['data', 'worksheets/sheet1.xml', row([cell('A1', '0', 's'), inlineCell('B1', 'inline'), cell('C1', '3.50')])]],
      { shared: ['shared'] },
    ),
    'rid.xlsx': xlsxBytes([
      ['first', 'worksheets/sheet9.xml', row([inlineCell('A1', 'from sheet9')])],
      ['second', 'worksheets/sheet1.xml', row([inlineCell('A1', 'from sheet1')])],
    ]),
    'absolute.xlsx': xlsxBytes([['abs', '/xl/worksheets/odd.xml', row([inlineCell('A1', 'absolute')])]]),
    'norid.xlsx': xlsxBytes([['guess', 'worksheets/sheet1.xml', row([inlineCell('A1', 'guessed')])]], { ridAttr: false }),
    'many.xlsx': xlsxBytes(
      Array.from({ length: 37 }, (_, i) => [`S${37 - i}`, `worksheets/sheet${i + 1}.xml`, row([inlineCell('A1', `v${37 - i}`)])]),
    ),
    'gaps.xlsx': xlsxBytes([
      ['data', 'worksheets/sheet1.xml', row([inlineCell('A1', 'a'), inlineCell('D1', 'd')]) + row([inlineCell('C2', 'c')], 2)],
    ]),
    'wide.xlsx': xlsxBytes([['data', 'worksheets/sheet1.xml', row([inlineCell('AB1', 'wide')])]]),
    'empty-sheet.xlsx': xlsxBytes([
      ['blank', 'worksheets/sheet1.xml', ''],
      ['data', 'worksheets/sheet2.xml', row([inlineCell('A1', 'x')])],
    ]),
    'blankrow.xlsx': xlsxBytes([
      ['data', 'worksheets/sheet1.xml', row([inlineCell('A1', 'a')]) + row([cell('A2', '')], 2) + row([], 3)],
    ]),
    'numbers.xlsx': xlsxBytes([
      ['data', 'worksheets/sheet1.xml', row([cell('A1', '1.10'), cell('B1', '46235.0'), cell('C1', '1E+30'), cell('D1', '0.1')])],
    ]),
    'kinds.xlsx': xlsxBytes([
      [
        'data',
        'worksheets/sheet1.xml',
        row([cell('A1', '1', 'b'), cell('B1', '0', 'b'), cell('C1', '#DIV/0!', 'e'), cell('D1', 'cached', 'str')]),
      ],
    ]),
    'newline.xlsx': xlsxBytes([['data', 'worksheets/sheet1.xml', row([inlineCell('A1', 'two\nlines\tand\rtab')])]]),
    'p.xlsx': xlsxBytes([
      ['data', 'worksheets/sheet1.xml', PAGED_BODY],
      ['other', 'worksheets/sheet2.xml', ''],
    ]),
    'long.xlsx': xlsxBytes([['data', 'worksheets/sheet1.xml', row([inlineCell('A1', 'ä'.repeat(2000))]) + row([inlineCell('A2', 'next')], 2)]]),
    'deflated.xlsx': xlsxBytes([['data', 'worksheets/sheet1.xml', row([inlineCell('A1', 'inflated')])]], { deflate: true }),
    'unresolved.xlsx': xlsxBytes([['data', 'worksheets/sheet1.xml', '']], {
      extra: {
        'xl/workbook.xml': `<workbook ${SHEET_NS} ${REL_NS}><sheets><sheet name="lost" sheetId="1" r:id="rId99"/></sheets></workbook>`,
      },
    }),
    // omissions
    'clean.xlsx': xlsxBytes([['data', 'worksheets/sheet1.xml', row([inlineCell('A1', 'x')])]]),
    'shots.xlsx': xlsxBytes(
      [
        ['empty', 'worksheets/sheet1.xml', ''],
        ['data', 'worksheets/sheet2.xml', row([inlineCell('A1', 'x')])],
      ],
      { extra: mediaPack({ 'xl/worksheets/sheet1.xml': ['a.png', 'b.png', 'c.png'], 'xl/worksheets/sheet2.xml': ['d.png'] }) },
    ),
    'twice.xlsx': xlsxBytes(
      [
        ['one', 'worksheets/sheet1.xml', ''],
        ['two', 'worksheets/sheet2.xml', ''],
      ],
      { extra: mediaPack({ 'xl/worksheets/sheet1.xml': ['same.jpeg'], 'xl/worksheets/sheet2.xml': ['same.jpeg'] }) },
    ),
    'badrels.xlsx': xlsxBytes([['data', 'worksheets/sheet1.xml', '']], {
      extra: { 'xl/worksheets/_rels/sheet1.xml.rels': '<not xml', 'xl/media/image1.png': 'x'.repeat(10), 'xl/embeddings/o.bin': 'y'.repeat(5) },
    }),
    'dated.xlsx': xlsxBytes(
      [['data', 'worksheets/sheet1.xml', row([cell('A1', '46235'), cell('B1', '46235.5')]).replace('<c r="A1">', '<c r="A1" s="1">').replace('<c r="B1">', '<c r="B1" s="2">')]],
      { extra: { 'xl/styles.xml': styles(['yyyy-mm-dd', '"$"#,##0.00', '[h]:mm:ss;@'], [0, 164, 165, 166, 14, 27]) } },
    ),
    'builtin.xlsx': xlsxBytes([['data', 'worksheets/sheet1.xml', row([`<c r="A1" s="1"><v>1</v></c>`, `<c r="B1" s="2"><v>2</v></c>`])]], {
      extra: { 'xl/styles.xml': styles([], [0, 14, 27]) },
    }),
    'textdate.xlsx': xlsxBytes([['data', 'worksheets/sheet1.xml', row([`<c r="A1" s="1" t="s"><v>0</v></c>`])]], {
      shared: ['46235'],
      extra: { 'xl/styles.xml': styles(['yyyy'], [0, 164]) },
    }),
    'columns.xlsx': xlsxBytes(
      [
        [
          'data',
          'worksheets/sheet1.xml',
          row([`<c r="A1" s="1"><v>1</v></c>`, `<c r="C1" s="1"><v>2</v></c>`]) + row([`<c r="C2" s="1"><v>3</v></c>`, `<c r="AA2" s="1"><v>4</v></c>`], 2),
        ],
      ],
      { extra: { 'xl/styles.xml': styles(['d/m/yyyy'], [0, 164]) } },
    ),
    // docx
    'd.docx': docxBytes(para('Policy ', 'number 4') + '<w:p/>' + para('') + para('Second')),
    't.docx': docxBytes(para('before') + table),
    'tab.docx': docxBytes('<w:p><w:r><w:t>a</w:t><w:tab/><w:t>b</w:t><w:br/><w:t>c</w:t></w:r></w:p>'),
    'shots.docx': docxBytes('<w:p><w:r><w:t>hi</w:t></w:r></w:p>', {
      extra: {
        'word/_rels/document.xml.rels': DRAWING_RELS(
          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>',
        ),
        'word/media/image1.png': 'x'.repeat(50),
      },
    }),
    'nodoc.docx': zipBytes([['word/settings.xml', '<x/>']]),
    'named.pdf': docxBytes(para('really a docx')),
    'named.docx': xlsxBytes([['data', 'worksheets/sheet1.xml', row([inlineCell('A1', 'really a workbook')])]]),
    // zip that is no OOXML, odf, empty zip, not a zip
    'plain.zip': zipBytes([
      ['readme.txt', 'hello'],
      ['data/values.csv', 'a,b'],
    ]),
    'sheet.ods': zipBytes([
      ['mimetype', 'application/vnd.oasis.opendocument.spreadsheet'],
      ['content.xml', '<x/>'],
    ]),
    'empty.zip': zipBytes([]),
    'notzip.xlsx': lat('PK\x03\x04 but nothing behind it'),
    // html / mhtml
    'api.doc': utf(MHTML_DOC),
    'export.doc': MHTML_CRLF,
    'two.mht': utf(MHTML_TWO),
    'page.html': lat('<html><body><h1>Title &amp; more</h1><p>Body</p></body></html>'),
    'blank.html': lat('<html><head><style>p{color:red}</style></head><body></body></html>'),
    'entities.html': utf(
      '<!DOCTYPE html><html><head><title>T &copy; &amp; &notin; &#128; &#x110000;</title></head><body>' +
        '<p>a &amp b&nbsp;c &lt;3</p><div>x<!-- gone -->y</div><textarea>t<b>u</textarea><pre>  keep\n  lines  </pre>' +
        '<table><tr><td> one </td><td>two<br/>2b</td></tr><tr><th>h</th></tr></table><p>tail &foo',
    ),
    'noboundary.mht': lat('MIME-Version: 1.0\nContent-Type: multipart/related\n\n--x\nContent-Type: text/plain\n\nhello\n--x--\n'),
    'charset.eml': Buffer.concat([
      lat('MIME-Version: 1.0\nContent-Type: text/plain; charset="iso-8859-1"\nContent-Transfer-Encoding: 8bit\n\ncaf\xe9 \x80 done\n'),
    ]),
    // text
    'plain.md': utf('# Title\n\n  indented\n\tTabbed\tfields\nlast'),
    'crlf.txt': lat('one\r\ntwo\r\n\r\nfour\r\n'),
    'nofinal.txt': lat('a\nb'),
    'blanklines.txt': lat('\n\n   \n\t\n'),
    'empty.txt': Buffer.alloc(0),
    'cut1.md': straddling(1),
    'cut2.md': straddling(2),
    'nul.log': headThen(lat('tail line\x00binary\n')),
    'invalid.log': headThen(lat('tail\xffline\nmore\n')),
    'partial.log': headThen(lat('no newline after this')),
    'noline.txt': Buffer.concat([lat('x'.repeat(5000)), lat('\x00')]),
    'ansi.log': lat('\x1b[31mred\x1b[0m\n'),
    'bell.txt': lat('ding\x07\n'),
    'short.txt': lat('ab\xe2\x82'),
    'bom.txt': Buffer.concat([lat('\xef\xbb\xbf'), utf('bom line\n')]),
    'latin1.txt': lat('caf\xe9\n'),
    // magic, video, unknown, suffix lies
    'doc.pdf': lat('%PDF-1.7\n%\xe2\xe3\xcf\xd3\n'),
    'sheet.xlsx.pdf': lat('%PDF-1.4 x'),
    'named.xlsx': lat('%PDF-1.4 x'),
    'real.doc': Buffer.concat([lat('\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'), Buffer.alloc(512)]),
    'note.rtf': lat('{\\rtf1\\ansi hello}'),
    'sheet.xls': lat('\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest'),
    'clip.mov': Buffer.concat([lat('\x00\x00\x00\x14ftypqt  '), Buffer.alloc(32)]),
    'pic.png': lat('\x89PNG\r\n\x1a\nxxxx'),
    'font.woff2': lat('wOF2\x00\x01\x00\x00rest'),
    'wof2note.md': utf('wOF2 is a font container format\n'),
    'blob.bin': lat('\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d'),
    'nosuffix': lat('just words\n'),
    'zstd.txt': lat('\x28\xb5\x2f\xfdxxxx'),
    // F3 (job43): what expat refuses and this walk once accepted — a bare `&`, a reference
    // with no semicolon, `&#0;`, a surrogate, a code point past Unicode — in a cell, in the
    // shared strings, in a sheet name (so in workbook.xml), in an attribute, in a docx body.
    // `rels-amp.xlsx` is the part that is NOT routed through `_parse`: an omission, never a
    // refusal. `tab.xlsx` and `refs.xlsx` are the legal references, so the strictness cannot
    // overshoot. `badcd.xlsx` is a valid archive whose EOCD central-directory offset is
    // 0x7FFFFFF0, so every member's header offset goes negative: `[Errno 22]` there.
    'amp.xlsx': xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'a & b')])]]),
    'sst.xlsx': xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([cell('A1', '0', 's')])]], { shared: ['a & b'] }),
    'wb.xlsx': xlsxBytes([['a & b', 'worksheets/sheet1.xml', '']]),
    'amp.docx': docxBytes('<w:p><w:r><w:t>a & b</w:t></w:r></w:p>'),
    'nosemi.xlsx': xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'a &amp b')])]]),
    'nul.xlsx': xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'a &#0; b')])]]),
    'surrogate.xlsx': xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'a &#xD800; b')])]]),
    'past-unicode.xlsx': xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'a &#x110000; b')])]]),
    'attr-amp.xlsx': xlsxBytes([
      ['Sales', 'worksheets/sheet1.xml', '<row r="1" x="a & b"><c r="A1" t="inlineStr"><is><t>ok</t></is></c></row>'],
    ]),
    'rels-amp.xlsx': xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'ok')])]], {
      extra: { 'xl/worksheets/_rels/sheet1.xml.rels': '<Relationships><Relationship Id="x" Target="a & b"/></Relationships>' },
    }),
    'tab.xlsx': xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'a &#9; b &#xA; c')])]]),
    'refs.xlsx': xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'a &amp; b &#38; &#x26; &lt;')])]]),
    'badcd.xlsx': badCentralDirectoryOffset(
      xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'ok')])]]),
    ),
    // ---- job43 G2: the zip member arms
    // bzip2 / lzma: the reference reads both; the port refuses by method — the ruling.
    'bzip2.docx': docxRaw(HELLO_BZIP2),
    // Review round 4 (M1): the SAME undecompressable method, on an OPTIONAL member. The
    // reference reads the whole workbook (its `bz2` decompresses the styles); this port
    // cannot decompress them, and a member it reads TOLERANTLY must cost it that member and
    // never the document. No cell here is date-styled, so what `styles.xml` would have said
    // changes nothing and BOTH runtimes answer the same bytes — that is what makes this a
    // parity case rather than a second ruling.
    'bzip2-optional-styles.xlsx': xlsxBytes(
      [['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'ok')])]],
      { extra: { 'xl/styles.xml': STYLES_BZIP2 } },
    ),
    'lzma.docx': docxRaw(HELLO_LZMA),
    // A stored member relabelled method 9 (deflate64): `NotImplementedError` is a
    // `RuntimeError` on the reference, so BOTH sides print the encrypted sentence.
    'method9.docx': relabelMethod(docxRaw(HELLO_DOCUMENT_XML), 'word/document.xml', 9),
    'encrypted-rels.xlsx': setEncryptedFlag(
      xlsxBytes([['Sales', 'worksheets/sheet1.xml', row([inlineCell('A1', 'ok')])]], {
        extra: { 'xl/worksheets/_rels/sheet1.xml.rels': DRAWING_RELS('<Relationship Id="x" Target="../media/image1.png"/>'), 'xl/media/image1.png': 'PNG' },
      }),
      'xl/worksheets/_rels/sheet1.xml.rels',
    ),
    // Both RAISE: `zlib.error` on the reference, `Error` named `zlib.error` here.
    'corrupt-deflate.docx': corruptStream(docxRaw(HELLO_DOCUMENT_XML, { deflate: true }), 'word/document.xml'),
    // A stream that ends early is a CRC failure, `BadZipFile`, on both — raised, not worded.
    'truncated-deflate.docx': truncateStream(docxRaw(HELLO_DOCUMENT_XML, { deflate: true }), 'word/document.xml', 20),
    // ---- job43 G2: what expat refuses and accepts
    'invalid-utf8.docx': docxRaw(Buffer.from(`<w:document ${WORD_NS}><w:body>${hello('caf\xe9')}</w:body></w:document>`, 'latin1')),
    'latin1-decl.docx': docxRaw(
      Buffer.from(`<?xml version="1.0" encoding="ISO-8859-1"?><w:document ${WORD_NS}><w:body>${hello('caf\xe9')}</w:body></w:document>`, 'latin1'),
    ),
    'cp1252-decl.docx': docxRaw(
      Buffer.from(`<?xml version="1.0" encoding="windows-1252"?><w:document ${WORD_NS}><w:body>${hello('\x93quoted\x94 \x80')}</w:body></w:document>`, 'latin1'),
    ),
    'bogus-encoding.docx': docxRaw(`<?xml version="1.0" encoding="x-nope"?><w:document ${WORD_NS}><w:body>${hello('x')}</w:body></w:document>`),
    'cdata-end-in-text.docx': docxBytes(hello('x ]]> y')),
    'control-char.docx': docxBytes(hello('x \x01 y')),
    'dtd-entity-nested.docx': docxRaw(
      `<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY f "F&#38;"><!ENTITY e "x&f;y<w:t>in</w:t>"><!ENTITY % p "no">]>` +
        `<w:document ${WORD_NS}><w:body><w:p><w:r><w:t>a &e; b</w:t><w:t xml:space="&f;">z</w:t></w:r></w:p></w:body></w:document>`,
    ),
    'dtd-entity-undefined.docx': docxRaw(`<!DOCTYPE w:document [<!ENTITY e "E">]><w:document ${WORD_NS}><w:body>${hello('a &f; b')}</w:body></w:document>`),
    // ---- job43 G2: `int()` over a shared-string index
    'unicode-digit-styles.xlsx': xlsxBytes([['S', 'worksheets/sheet1.xml', row([cell('A1', '𝟙', 's'), cell('B1', ' +٠ ', 's'), cell('C1', '1_2', 's'), cell('D1', '²', 's')])]], {
      shared: ['zero', 'one', ...Array.from({ length: 11 }, (_, i) => `s${i + 2}`)],
    }),
    // ---- job43 G2: uuencode's fallback — a blank line before `end` is "Truncated input", and
    // the payload comes back undecoded.
    'uu-truncated.eml': Buffer.from('MIME-Version: 1.0\r\nContent-Type: text/plain; charset=us-ascii\r\nContent-Transfer-Encoding: x-uuencode\r\n\r\nbegin 644 f\r\n#0V%T\r\n\r\nend\r\n', 'latin1'),
    'uu-broken-line.eml': Buffer.from('MIME-Version: 1.0\r\nContent-Type: text/plain\r\nContent-Transfer-Encoding: uue\r\n\r\nbegin 644 f\r\n#0V%Tzz\r\n`\r\nend\r\n', 'latin1'),
  };
}

/**
 * The checked-in fixtures `runtime-py/tests/docread_fixtures.py` wrote (job43 G1) —
 * `{name: absolute path}` under `runtime-py/tests/data/docread/`. The SAME bytes both
 * suites read, by that module's own rule, so nothing here rebuilds them.
 */
export function checkedInFixtures() {
  const dir = fileURLToPath(new URL('../../runtime-py/tests/data/docread/', import.meta.url));
  const out = {};
  for (const name of readdirSync(dir).sort()) out[name] = join(dir, name);
  return out;
}

/**
 * Patch one member's headers in place — the local file header (`PK\x03\x04`) and the
 * central directory entry (`PK\x01\x02`) — the way `runtime-py/tests/docread_fixtures.py`'s
 * `set_encrypted_flag` does. `patch(buf, localAt, centralAt)` edits both.
 */
function patchMember(bytes, name, patch) {
  const out = Buffer.from(bytes);
  const want = Buffer.from(name, 'utf8');
  const find = (sig, nameAt, nameLenAt) => {
    let at = out.indexOf(sig);
    while (at >= 0) {
      const len = out.readUInt16LE(at + nameLenAt);
      if (out.subarray(at + nameAt, at + nameAt + len).equals(want)) return at;
      at = out.indexOf(sig, at + 4);
    }
    throw new Error(`no member ${name}`);
  };
  patch(out, find(Buffer.from('PK\x03\x04', 'latin1'), 30, 26), find(Buffer.from('PK\x01\x02', 'latin1'), 46, 28));
  return out;
}

/** General-purpose flag bit 0 (encrypted) set on `name`, in both headers. */
export function setEncryptedFlag(bytes, name) {
  return patchMember(bytes, name, (out, local, central) => {
    out.writeUInt16LE(out.readUInt16LE(local + 6) | 1, local + 6);
    out.writeUInt16LE(out.readUInt16LE(central + 8) | 1, central + 8);
  });
}

/** The compression method field of `name` overwritten as `method`, in both headers. */
export function relabelMethod(bytes, name, method) {
  return patchMember(bytes, name, (out, local, central) => {
    out.writeUInt16LE(method, local + 8);
    out.writeUInt16LE(method, central + 10);
  });
}

/** The first eight bytes of `name`'s (deflated) stream overwritten with 0xFF. */
export function corruptStream(bytes, name) {
  return patchMember(bytes, name, (out, local) => {
    const start = local + 30 + out.readUInt16LE(local + 26) + out.readUInt16LE(local + 28);
    out.fill(0xff, start, start + 8);
  });
}

/**
 * `name`'s deflated stream cut to its first `keep` bytes IN PLACE (the compressed size in
 * both headers lowered to match; the rest of the stream zeroed, not removed, so every
 * later offset still holds): an incomplete stream, not a corrupt one.
 */
export function truncateStream(bytes, name, keep) {
  return patchMember(bytes, name, (out, local, central) => {
    const size = out.readUInt32LE(local + 18);
    const start = local + 30 + out.readUInt16LE(local + 26) + out.readUInt16LE(local + 28);
    out.fill(0, start + keep, start + size);
    out.writeUInt32LE(keep, local + 18);
    out.writeUInt32LE(keep, central + 20);
  });
}

// `word/document.xml` of `<w:document ...><w:body><w:p><w:r><w:t>hello</w:t></w:r></w:p></w:body></w:document>`
// as CPython's `zipfile` compressed it (job43 G2; the bytes and CRC read back off the
// local header of the zip `ZipFile.writestr(info, xml, compress_type=ZIP_BZIP2 | ZIP_LZMA)` wrote).
const HELLO_DOCUMENT_XML =
  '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>hello</w:t></w:r></w:p></w:body></w:document>';
const HELLO_BZIP2 = {
  method: 12,
  crc: 0x7a6d9799,
  size: 151,
  raw: Buffer.from(
    '425a68393141592653599f7be89700001299805001d1173fe7dee0200064254d4c9a4f21a8f43537aa3d4f141aa7e94c1190321e90057bd6a6bded1dd85252727db0c2330aa306bb169f28d739b664c8450c8cf23f199a7ce5f493b75da05521c36372983068f623ee5cbaa615457a04b168d59eb95b025aeaa8876082492e47fd80fc5dc914e142427defa25c',
    'hex',
  ),
};
/**
 * `xl/styles.xml` — a styleSheet with no custom formats — as CPython's `zipfile` compressed
 * it with `compress_type=ZIP_BZIP2`. Review round 4 (M1) needs a bzip2 member that is
 * OPTIONAL rather than required, and the ruled `bzip2.docx` puts its member at
 * `word/document.xml`, which is neither.
 */
const STYLES_BZIP2 = {
  method: 12,
  crc: 0xb4212c1d,
  size: 157,
  raw: Buffer.from(
    '425a683931415926535992411f740000101f805001f117012008402fe7de602000750d240da8f446468032320d3494f6a27ea9fa4d234d0f534c8c9b67f6ea0f8eac29a3d6a70b2f2c6166bb7644b634629748ea8ba0c019242d70dfa31ec4a214e614ee905c832f7a38c5054815427d69a623e29e070cddf71bf58e32f0a2794f8322fecc1863dcb5f21680c9d39ad6f1fc5dc914e1424249047dd0',
    'hex',
  ),
};
const HELLO_LZMA = {
  method: 14,
  crc: 0x7a6d9799,
  size: 151,
  raw: Buffer.from(
    '090405005d00008000001e1dc346566be5546829ba715d85cc79bb6cc86644d3a8233305d232bd42b359ed37b27b21d4f593615f2f1651d86ac7374fe7fba3b3d4a21909728426921d921cd3149c3c870d435eaae16a0b0f2ad5257d90a26f60b26fb06824bb9efb8a7e7e1179178d448f407106c0829fa3e4a769c81ffddeed20',
    'hex',
  ),
};

/** A docx whose `word/document.xml` is the given bytes or pre-compressed member, verbatim. */
function docxRaw(member, { deflate = false } = {}) {
  return zipBytes(
    [
      ['[Content_Types].xml', CONTENT_TYPES],
      ['_rels/.rels', ROOT_RELS],
      ['word/document.xml', member],
    ],
    { deflate },
  );
}

const hello = (t) => `<w:p><w:r><w:t>${t}</w:t></w:r></w:p>`;

/** The archive with its EOCD's central-directory offset overwritten as 0x7FFFFFF0. */
export function badCentralDirectoryOffset(bytes) {
  const out = Buffer.from(bytes);
  out.writeUInt32LE(0x7ffffff0, out.length - 22 + 16);
  return out;
}

/** Lay every fixture down under `dir`; returns `{name: absolute path}`. */
export function writeFixtures(dir) {
  mkdirSync(dir, { recursive: true });
  const out = {};
  for (const [name, bytes] of Object.entries(fixtures())) {
    const path = join(dir, name);
    writeFileSync(path, bytes);
    out[name] = path;
  }
  mkdirSync(join(dir, 'a-directory'), { recursive: true });
  out['a-directory'] = join(dir, 'a-directory');
  out['missing.txt'] = join(dir, 'missing.txt');
  return out;
}
