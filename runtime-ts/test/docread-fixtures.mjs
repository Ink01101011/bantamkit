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
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
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

/** `entries` is `[[name, string | Buffer], ...]` in write order. */
export function zipBytes(entries, { deflate = false } = {}) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const [name, payload] of entries) {
    const nameBytes = Buffer.from(name, 'utf8');
    const data = Buffer.isBuffer(payload) ? payload : Buffer.from(payload, 'utf8');
    const stored = deflate ? deflateRawSync(data) : data;
    const method = deflate ? 8 : 0;
    const crc = crc32(data);
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
  };
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
