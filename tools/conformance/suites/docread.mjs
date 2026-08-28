/**
 * docread — the reader, Python against Node, over the same files.
 *
 * THE PROPERTY: handed the same bytes, `docread.py` and `docread.ts` identify the same
 * container, render the same rows, count the same omissions and refuse with the same
 * sentence — except for the three kinds the Node half cannot read (`pdf`, `doc`, `rtf`),
 * each of which is a `ruling` below with its reason and a companion that pins the refusal
 * bit rather than the words (docs/conformance.md, "a ruling pins the wording, not the
 * outcome").
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
  'doc.pdf': { kind: 'pdf', python: () => true },
  'sheet.xlsx.pdf': { kind: 'pdf', python: () => true },
  'named.xlsx': { kind: 'pdf', python: () => true },
  'real.doc': { kind: 'doc', python: () => true },
  'sheet.xls': { kind: 'doc', python: () => true },
  'bad.rtf': { kind: 'rtf', python: () => true },
  'note.rtf': { kind: 'rtf', python: (textutil) => !textutil },
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
  };
  for (const [file, bytes] of Object.entries(extra)) {
    writeFileSync(join(bed, file), bytes);
    paths[file] = join(bed, file);
  }
  const notes = [];
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
    { name: 'offset below zero', path: p, part: 'data', offset: -1, limit: 5 },
    { name: 'limit zero', path: p, part: 'data', offset: 0, limit: 0 },
    { name: 'one row over the byte ceiling is cut to fit', path: paths['long.xlsx'], part: 'data', offset: 0, limit: 50, max_bytes: 3072 },
    { name: 'the row after the cut one', path: paths['long.xlsx'], part: 'data', offset: 1, limit: 50, max_bytes: 3072 },
    { name: 'a window that stops on a row boundary under the ceiling', path: paths['plain.md'], part: 'document', offset: 0, limit: 50, max_bytes: 12 },
    { name: 'a markdown body, two rows', path: paths['plain.md'], part: 'document', offset: 0, limit: 2 },
    { name: 'a docx body', path: paths['d.docx'], part: 'document', offset: 1, limit: 1 },
    { name: 'an unreadable file has no page', path: paths['pic.png'], part: 'document' },
    { name: 'a missing file has no page', path: paths['missing.txt'], part: 'document' },
  ];

  // ------------------------------------------------------------------- the two sides

  const python = ctx.runPython(REF, {
    paths: names.map((n) => paths[n]),
    pages: pages.map(({ name: _n, ...spec }) => spec),
  });

  const errorOf = (e) => ({ error: { type: e?.constructor?.name ?? 'Error', message: String(e?.message ?? e) } });
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
      const expectedBits = { python: rule.python(python.textutil), node: true };
      cases.push({
        name: `extract: ${n}: the refusal bit each side is required to carry`,
        kind: 'json',
        expected: expectedBits,
        actual: { python: refused(py.extract), node: refused(nd.extract) },
      });
      if (expectedBits.python) {
        cases.push({
          name: `extract: ${n}: both refuse (the refusal bit, side to side)`,
          kind: 'json',
          expected: refused(py.extract),
          actual: refused(nd.extract),
        });
        refusedBoth += 1;
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
      `(pdf/doc/rtf); /usr/bin/textutil ${python.textutil ? 'present' : 'absent'} on this host, so the reference ` +
      `${python.textutil ? 'reads note.rtf and refuses real.doc as "plain text"' : 'refuses note.rtf and real.doc by name'}`,
  );
  const pdfRows = python.files[names.indexOf('tiny.pdf')].extract.parts?.map((x) => x.rows) ?? null;
  notes.push(`tiny.pdf on the reference: ${JSON.stringify(pdfRows)}; on the port: ${JSON.stringify(node.files[names.indexOf('tiny.pdf')].extract.error?.message)}`);
  return { cases, notes };
}
