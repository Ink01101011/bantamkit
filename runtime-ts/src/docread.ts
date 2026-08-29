/**
 * The Node half of `runtime-py/src/bantamkit/docread.py`: deterministic text extraction,
 * addressable by part and row, dispatched on what a file IS.
 *
 * The Python module is the reference and this file COPIES it — its rows, its omission
 * records and its sentences, byte for byte, for the kinds it reads: `text`, `xlsx`,
 * `docx`, `html` and `mhtml`. Every constant, token and sentence below is the Python
 * one; where the reference reads something this half does not (`pdf` through
 * `pdfread`, `doc`/`rtf` through `/usr/bin/textutil`), `sniff` still IDENTIFIES the
 * container so the refusal names it, and `extract` refuses with a sentence that is a
 * DELIBERATE divergence recorded in `docs/porting.md`.
 *
 * No third-party dependency. The reference leans on four standard-library modules that
 * Node does not ship, and each is replaced by the smallest hand-written reader that
 * reproduces the reference's answers on the reference's own fixtures:
 *
 * - `zipfile`    -> `ZipReader`: central-directory walk, stored + deflate (`node:zlib`
 *                   `inflateRawSync`), CRC-32 checked the way `ZipFile.read` checks it.
 * - `xml.etree`  -> `parseXml`: a namespace-expanding element tree with `.text`,
 *                   `iter(tag)`, `find(tag)` and direct-child iteration — the four ET
 *                   operations `docread.py` actually calls.
 * - `html.parser` + `html.unescape` -> `HtmlText` over a line-for-line port of
 *                   `HTMLParser.goahead` (CPython 3.12.13, `convert_charrefs=True`), so
 *                   the DATA CHUNKS arrive in the same pieces — the chunking is visible in
 *                   the rows because `_HtmlText` joins chunks with a space.
 * - `email`      -> `parseMime`: multipart boundaries, header unfolding, Content-Type
 *                   parameters, quoted-printable (`binascii.a2b_qp`) and base64.
 *
 * Python string semantics that JavaScript does not share are ported explicitly rather
 * than approximated: `str.strip()`/`split()`/`splitlines()` use Python's whitespace and
 * line-boundary sets (`PY_WS`, `pySplitlines`), `repr()` of a `str` and of `bytes` is
 * `pyRepr`/`bytesRepr`, `sorted()` compares by code point (`cmpCodepoint`), and a UTF-8
 * decode error reports the same `start` offset and `reason` CPython's decoder does
 * (`utf8Scan`).
 */

import { closeSync, openSync, readFileSync, readSync, statSync } from 'node:fs';
import { posix } from 'node:path';
import { constants as zlibConstants, inflateRawSync } from 'node:zlib';

import { BantamError } from './errors.js';
import { HTML5_ENTITIES } from './htmlentities.js';
import { PyOSError, pyJoin, pyName, pySuffix as pyPathSuffix } from './memory/pyfs.js';

export const NS_S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}';
export const NS_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}';
export const NS_R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}';

// Read directly, by this module, with nothing outside the standard library — the Python
// tuple verbatim, because `_unsupported_remedy` prints it and the sentence must match.
export const SUPPORTED = ['text', 'xlsx', 'docx', 'pdf', 'html', 'mhtml'] as const;
export const TEXTUTIL_SUPPORTED = ['doc', 'rtf'] as const;
export const TEXTUTIL = '/usr/bin/textutil';
export const DEFAULT_ROW_LIMIT = 50;
export const PAGE_MAX_ROWS = 200;
export const PAGE_MAX_BYTES = 3072;
export const TEXT_MAX_BYTES = 16 * 1024 * 1024;

export const OMIT_MEDIA = 'media';
export const OMIT_BLANK_ROWS = 'blank-rows';
export const OMIT_NUMBER_FORMAT = 'number-format';
export const OMIT_UNREAD_PAGE = 'unread-page';
export const OMIT_UNMAPPED = 'unmapped-text';
export const OMIT_UNREAD_TAIL = 'unread-tail';
export const OMIT_SIZE_CAP = 'size-cap';

/** Extraction failed. The message names what was seen, never just the format's own error. */
export class DocumentReadError extends BantamError {}

// ------------------------------------------------------------------ Python string semantics

/** The characters `str.isspace()` is true for — what `strip()` and `split()` consume. */
const PY_WS =
  '\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0                　';
const PY_WS_CLASS = `[${PY_WS.replace(/[\]\\^-]/g, '\\$&')}]`;
const PY_WS_RUN = new RegExp(`${PY_WS_CLASS}+`, 'g');
const PY_STRIP = new RegExp(`^${PY_WS_CLASS}+|${PY_WS_CLASS}+$`, 'g');
const PY_LSTRIP = new RegExp(`^${PY_WS_CLASS}+`);
const PY_RSTRIP = new RegExp(`${PY_WS_CLASS}+$`);

/** `str.strip()` with no argument. */
export function pyStrip(s: string): string {
  return s.replace(PY_STRIP, '');
}

function pyRstrip(s: string): string {
  return s.replace(PY_RSTRIP, '');
}

/** `str.strip(chars)`. */
function pyStripChars(s: string, chars: string): string {
  let start = 0;
  let end = s.length;
  while (start < end && chars.includes(s[start] as string)) start += 1;
  while (end > start && chars.includes(s[end - 1] as string)) end -= 1;
  return s.slice(start, end);
}

function pyLstripChars(s: string, chars: string): string {
  let start = 0;
  while (start < s.length && chars.includes(s[start] as string)) start += 1;
  return s.slice(start);
}

/** `str.split()` with no argument: runs of whitespace, no empty fields. */
export function pySplit(s: string): string[] {
  const trimmed = s.replace(PY_LSTRIP, '');
  if (!trimmed) return [];
  return pyRstrip(trimmed).split(PY_WS_RUN);
}

/** `str.splitlines()`: Python's line boundaries, terminators dropped. */
export function pySplitlines(s: string): string[] {
  const out: string[] = [];
  let start = 0;
  let i = 0;
  while (i < s.length) {
    const ch = s[i] as string;
    let eol = 0;
    if (ch === '\r') eol = s[i + 1] === '\n' ? 2 : 1;
    else if ('\n\x0b\x0c\x1c\x1d\x1e\x85  '.includes(ch)) eol = 1;
    if (eol) {
      out.push(s.slice(start, i));
      i += eol;
      start = i;
    } else {
      i += 1;
    }
  }
  if (start < s.length) out.push(s.slice(start));
  return out;
}

/** `int(text)` for a base-10 literal; `null` where Python raises `ValueError`. */
// `int()` strips `Py_UNICODE_ISSPACE` characters, which is neither JavaScript's `\s` (that
// has U+FEFF, this does not) nor `str.isspace()` (U+001C–U+001F are ASCII-whitespace to
// `isspace` and refused by `int()`). Measured on CPython 3.12 (job43 G2), one character at a
// time: accepted U+0085, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F,
// U+3000; refused U+001C–U+001F, U+180E, U+200B, U+FEFF.
const PY_INT_SPACE = '[\\t\\n\\x0b\\x0c\\r \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]*';
const PY_INT = new RegExp(`^${PY_INT_SPACE}([+-]?)(\\p{Nd}+(?:_\\p{Nd}+)*)${PY_INT_SPACE}$`, 'u');
const IS_ND = /\p{Nd}/u;

/**
 * The value of one `Nd` character. Unicode encodes every decimal-digit set as a contiguous
 * run 0..9, so the value is the distance to the run's start — walked, because the runs abut
 * (the five mathematical sets U+1D7CE.. are fifty consecutive code points) and the walk is
 * taken modulo ten.
 */
function digitValue(ch: string): number {
  let cp = ch.codePointAt(0) as number;
  let steps = 0;
  while (IS_ND.test(String.fromCodePoint(cp - 1))) {
    cp -= 1;
    steps += 1;
  }
  return steps % 10;
}

/**
 * `int(text)`, or `null` where it raises `ValueError`.
 *
 * `int()` accepts ANY Unicode decimal digit — `<v>١٢</v>` (Arabic-Indic) indexes shared
 * string 12 on the reference (measured, job43 G1: `tests/data/docread/unicode-digit-shared-
 * string.xlsx` reads `str12`), and until G2 this port refused the cell as "indexes shared
 * string '١٢'". `_` between digit groups, a sign, and Unicode whitespace around are `int()`'s
 * too. A decimal string past 4300 digits is `ValueError` since CPython 3.11 (the cap
 * `mcpserver._ArgMetadata` documents), and is `null` here rather than `Infinity`.
 */
function pyInt(text: string): number | null {
  const m = PY_INT.exec(text);
  if (!m) return null;
  const digits = (m[2] as string).replace(/_/g, '');
  if (digits.length > 4300) return null;
  let ascii = '';
  for (const ch of digits) ascii += digitValue(ch);
  const n = Number(ascii);
  return m[1] === '-' ? -n : n;
}

/** Python list indexing: negative counts from the end, out of range is `undefined`. */
function pyIndex<T>(list: readonly T[], index: number): T | undefined {
  const i = index < 0 ? list.length + index : index;
  return i >= 0 && i < list.length ? list[i] : undefined;
}

/** `sorted()` on strings: by code point, which is not what `Array.sort` does above U+FFFF. */
export function cmpCodepoint(a: string, b: string): number {
  const ia = a[Symbol.iterator]();
  const ib = b[Symbol.iterator]();
  for (;;) {
    const x = ia.next();
    const y = ib.next();
    if (x.done && y.done) return 0;
    if (x.done) return -1;
    if (y.done) return 1;
    const cx = (x.value as string).codePointAt(0) as number;
    const cy = (y.value as string).codePointAt(0) as number;
    if (cx !== cy) return cx - cy;
  }
}

function pySorted(items: Iterable<string>): string[] {
  return [...items].sort(cmpCodepoint);
}

// `str.isprintable()` is false for these categories (space itself excepted).
const NONPRINTABLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]/u;

function quoteFor(s: string): string {
  return s.includes("'") && !s.includes('"') ? '"' : "'";
}

/** `repr(str)`. */
export function pyRepr(s: string): string {
  const quote = quoteFor(s);
  let out = quote;
  for (const ch of s) {
    const code = ch.codePointAt(0) as number;
    if (ch === quote || ch === '\\') out += '\\' + ch;
    else if (ch === '\t') out += '\\t';
    else if (ch === '\n') out += '\\n';
    else if (ch === '\r') out += '\\r';
    else if (ch !== ' ' && NONPRINTABLE.test(ch)) {
      if (code < 0x100) out += '\\x' + code.toString(16).padStart(2, '0');
      else if (code < 0x10000) out += '\\u' + code.toString(16).padStart(4, '0');
      else out += '\\U' + code.toString(16).padStart(8, '0');
    } else out += ch;
  }
  return out + quote;
}

/** `repr(bytes)`. */
export function bytesRepr(buf: Uint8Array): string {
  const text = Buffer.from(buf).toString('latin1');
  const quote = quoteFor(text);
  let out = 'b' + quote;
  for (const b of buf) {
    const ch = String.fromCharCode(b);
    if (ch === quote || ch === '\\') out += '\\' + ch;
    else if (b === 0x09) out += '\\t';
    else if (b === 0x0a) out += '\\n';
    else if (b === 0x0d) out += '\\r';
    else if (b >= 0x20 && b < 0x7f) out += ch;
    else out += '\\x' + b.toString(16).padStart(2, '0');
  }
  return out + quote;
}

/**
 * `str(Path(p))`: `//` and `.` segments collapsed, a trailing slash dropped, nothing resolved.
 *
 * This is ALSO the string every `fs` call in this module receives, because it is the string
 * the reference hands the kernel: `Path('')` is `.` (the cwd — a directory, on the
 * reference), and `Path('a/b/.')` is `a/b`, so `stat('README.md/.')` on the reference is a
 * stat of the FILE, where a raw `statSync('README.md/.')` is ENOTDIR. Measured (job43 F3):
 * `''` read as `no such file: .` here and `. is a directory, not a document` there.
 *
 * The parsing is `pyfs`'s — `PurePath`'s own, with the Windows flavour on Windows — so a
 * sentence printed under `win32` carries `C:\\docs\\a.docx` where the reference prints it,
 * and `Path('C:/docs/a.docx').name` is `a.docx` on both. Until job43 G2 this module had its
 * own POSIX-only copy of the three helpers, and every sentence on Windows would have named
 * the path with the separators the CALLER wrote.
 */
function pyPathStr(path: string): string {
  return pyJoin(path);
}

/** `Path(p).name`: the last component of the collapsed path — `''` for `''`, `.` and `/`. */
function pyPathName(path: string): string {
  return pyName(path);
}

/** `posixpath.splitext(name)[1]`. Leading dots of the basename never begin an extension. */
function posixSplitextExt(name: string): string {
  const slash = name.lastIndexOf('/');
  const dot = name.lastIndexOf('.');
  if (dot <= slash) return '';
  let first = slash + 1;
  while (first < dot && name[first] === '.') first += 1;
  return first < dot ? name.slice(dot) : '';
}

function utf8Length(s: string): number {
  return Buffer.byteLength(s, 'utf8');
}

// ------------------------------------------------------------------------ strict UTF-8

export interface Utf8Scan {
  /** Bytes `[0, end)` decode cleanly. */
  end: number;
  /** Where the first sequence no continuation could complete begins, or -1. */
  invalidAt: number;
  /** CPython's `UnicodeDecodeError.reason` for that sequence. */
  reason: string;
  /** With `final` false: the bytes past `end` are an incomplete trailing character. */
  incomplete: boolean;
}

/**
 * CPython's UTF-8 decoder, as a validator: the same `start` and `reason` its
 * `UnicodeDecodeError` carries, and the same tolerance an incremental decoder has for a
 * final character the read cut in half when `final` is false.
 */
export function utf8Scan(buf: Uint8Array, final: boolean): Utf8Scan {
  const n = buf.length;
  let i = 0;
  while (i < n) {
    const b = buf[i] as number;
    if (b < 0x80) {
      i += 1;
      continue;
    }
    let need: number;
    let lo = 0x80;
    let hi = 0xbf;
    if (b >= 0xc2 && b <= 0xdf) need = 1;
    else if (b >= 0xe0 && b <= 0xef) {
      need = 2;
      if (b === 0xe0) lo = 0xa0;
      if (b === 0xed) hi = 0x9f;
    } else if (b >= 0xf0 && b <= 0xf4) {
      need = 3;
      if (b === 0xf0) lo = 0x90;
      if (b === 0xf4) hi = 0x8f;
    } else {
      return { end: i, invalidAt: i, reason: 'invalid start byte', incomplete: false };
    }
    for (let k = 1; k <= need; k += 1) {
      if (i + k >= n) {
        if (final) {
          return { end: i, invalidAt: i, reason: 'unexpected end of data', incomplete: false };
        }
        return { end: i, invalidAt: -1, reason: '', incomplete: true };
      }
      const c = buf[i + k] as number;
      const min = k === 1 ? lo : 0x80;
      const max = k === 1 ? hi : 0xbf;
      if (c < min || c > max) {
        return { end: i, invalidAt: i, reason: 'invalid continuation byte', incomplete: false };
      }
    }
    i += need + 1;
  }
  return { end: n, invalidAt: -1, reason: '', incomplete: false };
}

function decodeUtf8(buf: Uint8Array): string {
  return Buffer.from(buf.buffer, buf.byteOffset, buf.length).toString('utf8');
}

/** `bytes.decode(charset, errors="replace")`, falling back to UTF-8 on `LookupError`. */
function decodeCharset(buf: Uint8Array, charset: string): string {
  const name = charset.toLowerCase().replace(/_/g, '-');
  if (['ascii', 'us-ascii', '646', 'us', 'ansi-x3.4-1968'].includes(name)) {
    let out = '';
    for (const b of buf) out += b < 0x80 ? String.fromCharCode(b) : '�';
    return out;
  }
  if (['latin-1', 'latin1', 'iso-8859-1', 'iso8859-1', 'l1', '8859', 'cp819'].includes(name)) {
    return Buffer.from(buf).toString('latin1');
  }
  try {
    return new TextDecoder(name, { fatal: false, ignoreBOM: true }).decode(buf);
  } catch {
    return new TextDecoder('utf-8', { fatal: false, ignoreBOM: true }).decode(buf);
  }
}

// ------------------------------------------------------------------------ the data model

export interface OmissionDict {
  subject: string;
  count: number;
  size: number;
  where: string[];
  what: string;
  facts: Record<string, number>;
}

/** Something the file holds that the rows do not carry, as a COUNT and the fact behind it. */
export class Omission {
  constructor(
    public readonly subject: string,
    public readonly count: number,
    public readonly size: number = 0,
    public readonly where: readonly string[] = [],
    public readonly what: string = '',
    public readonly facts: readonly (readonly [string, number])[] = [],
  ) {}

  /** The primitive form the contract layer takes, keys in the reference's order. */
  asDict(): OmissionDict {
    const facts: Record<string, number> = {};
    for (const [name, value] of this.facts) facts[name] = value;
    return {
      subject: this.subject,
      count: this.count,
      size: this.size,
      where: [...this.where],
      what: this.what,
      facts,
    };
  }
}

/** One addressable unit: a worksheet, or a `.docx` body. `rows` are rendered lines. */
export class Part {
  constructor(
    public readonly name: string,
    public readonly index: number,
    public readonly rows: readonly string[],
    public readonly omissions: readonly Omission[] = [],
  ) {}

  get rowCount(): number {
    return this.rows.length;
  }

  /** UTF-8 bytes of this part's full rendering. EXTRACTED size, not file size. */
  get textBytes(): number {
    return utf8Length(this.rows.join('\n'));
  }
}

export class Document {
  constructor(
    public readonly kind: string,
    public readonly parts: readonly Part[],
    public readonly omissions: readonly Omission[] = [],
  ) {}

  get textBytes(): number {
    return this.parts.reduce((sum, p) => sum + p.textBytes, 0);
  }

  /** Resolve by exact sheet name, else by 0-based index. Names win over numeric keys. */
  part(key: string | number): Part {
    for (const p of this.parts) {
      if (p.name === key) return p;
    }
    const numeric = typeof key === 'number' ? key : /^[0-9]+$/.test(key.replace(/^-+/, '')) ? pyInt(key) : null;
    if (numeric !== null) {
      if (numeric >= 0 && numeric < this.parts.length) return this.parts[numeric] as Part;
    }
    const names = this.parts.map((p) => pyRepr(p.name)).join(', ');
    const shown = typeof key === 'number' ? String(key) : pyRepr(key);
    throw new DocumentReadError(`no part ${shown}; this document has ${this.parts.length}: ${names}`);
  }
}

/** A row slice of one part. `nextOffset` is null exactly when the part is exhausted. */
export class Page {
  constructor(
    public readonly part: string,
    public readonly offset: number,
    public readonly rows: readonly string[],
    public readonly totalRows: number,
    public readonly nextOffset: number | null,
    public readonly truncatedBytes: number = 0,
  ) {}

  get text(): string {
    return this.rows.join('\n');
  }
}

/** One rendered row is one line: no embedded newline or tab may survive a cell value. */
function clean(text: string): string {
  return text.replace(/\t/g, ' ').replace(/\r/g, ' ').replace(/\n/g, ' ');
}

// --------------------------------------------------------------- what a file IS, from bytes

/** The container a file's own bytes declare it to be. `kind` decides; `what` explains. */
export class Container {
  constructor(
    public readonly kind: string,
    public readonly what: string,
    public readonly named: string,
  ) {}

  /** True when the name promises a container the bytes do not deliver. */
  get suffixLies(): boolean {
    const expected = lookup(SUFFIX_KINDS, this.named);
    return expected !== undefined && expected !== this.kind;
  }
}

export const SUFFIX_KINDS: Readonly<Record<string, string>> = {
  xlsx: 'xlsx',
  docx: 'docx',
  pptx: 'pptx',
  pdf: 'pdf',
  doc: 'doc',
  xls: 'doc',
  ppt: 'doc',
  rtf: 'rtf',
  htm: 'html',
  html: 'html',
  mht: 'mhtml',
  mhtml: 'mhtml',
  eml: 'mhtml',
  mov: 'isobmff',
  mp4: 'isobmff',
  m4a: 'isobmff',
  m4v: 'isobmff',
  png: 'png',
  jpg: 'jpeg',
  jpeg: 'jpeg',
  gif: 'gif',
  gz: 'gzip',
  zip: 'zip',
};

const WHAT: Readonly<Record<string, string>> = {
  doc: 'an OLE2 compound file (the pre-2007 Office binary)',
  rtf: 'an RTF document',
  woff2: 'a WOFF2 web font',
  woff: 'a WOFF web font',
  zstd: 'a zstd-compressed stream',
  xz: 'an xz-compressed stream',
  sqlite: 'a SQLite 3 database',
  wasm: 'a WebAssembly module',
};

const MAGIC: readonly (readonly [Uint8Array, string])[] = [
  [Buffer.from('%PDF-', 'latin1'), 'pdf'],
  [Buffer.from('\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', 'latin1'), 'doc'],
  [Buffer.from('{\\rtf', 'latin1'), 'rtf'],
  [Buffer.from('\x89PNG\r\n\x1a\n', 'latin1'), 'png'],
  [Buffer.from('\xff\xd8\xff', 'latin1'), 'jpeg'],
  [Buffer.from('GIF8', 'latin1'), 'gif'],
  [Buffer.from('\x1f\x8b', 'latin1'), 'gzip'],
  [Buffer.from('Rar!\x1a\x07', 'latin1'), 'rar'],
  [Buffer.from("7z\xbc\xaf'\x1c", 'latin1'), '7z'],
  [Buffer.from('%!PS', 'latin1'), 'postscript'],
  [Buffer.from('\x7fELF', 'latin1'), 'elf'],
  [Buffer.from('BZh', 'latin1'), 'bzip2'],
  [Buffer.from('SQLite format 3\x00', 'latin1'), 'sqlite'],
  [Buffer.from('\xfd7zXZ\x00', 'latin1'), 'xz'],
  [Buffer.from('wOF2\x00\x01\x00\x00', 'latin1'), 'woff2'],
  [Buffer.from('wOF2OTTO', 'latin1'), 'woff2'],
  [Buffer.from('wOFF\x00\x01\x00\x00', 'latin1'), 'woff'],
  [Buffer.from('wOFFOTTO', 'latin1'), 'woff'],
  [Buffer.from('\x28\xb5\x2f\xfd', 'latin1'), 'zstd'],
  [Buffer.from('\x00asm', 'latin1'), 'wasm'],
];

const ZIP_MEMBERS: readonly (readonly [string, string])[] = [
  ['xl/workbook.xml', 'xlsx'],
  ['word/document.xml', 'docx'],
  ['ppt/presentation.xml', 'pptx'],
];

export const HEAD_BYTES = 4096;
// Python's `\s` and `\b` are Unicode-aware in a `str` pattern; the classes below say so.
const HTML_HEAD = new RegExp(
  `<(?:!doctype${PY_WS_CLASS}+html|html(?![\\p{L}\\p{N}_])|head(?![\\p{L}\\p{N}_])|body(?![\\p{L}\\p{N}_]))`,
  'iu',
);
const MIME_HEADER = /^[A-Za-z][A-Za-z0-9-]*:[ \t]/;

// The C0 codes a plain-text document legitimately carries: tab, the newline family, and ESC.
const TEXT_CONTROLS = new Set([0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1b]);

function isBinaryControl(code: number): boolean {
  return code < 0x20 && !TEXT_CONTROLS.has(code);
}

/** The Python regex character class for the same set, over a whole string. */
const BINARY_CONTROL = new RegExp(
  '[' +
    Array.from({ length: 0x20 }, (_, c) => c)
      .filter((c) => !TEXT_CONTROLS.has(c))
      .map((c) => '\\x' + c.toString(16).padStart(2, '0'))
      .join('') +
    ']',
);

function startsWith(head: Uint8Array, magic: Uint8Array): boolean {
  if (head.length < magic.length) return false;
  for (let i = 0; i < magic.length; i += 1) if (head[i] !== magic[i]) return false;
  return true;
}

function zipKind(path: string, head: Uint8Array): Container {
  const named = pyPathSuffix(path).toLowerCase().replace(/^\.+/, '');
  let names: string[];
  let mimetype = '';
  try {
    const zf = ZipReader.open(path);
    names = zf.namelist();
    if (names.includes('mimetype')) {
      mimetype = new TextDecoder('utf-8', { ignoreBOM: true }).decode(zf.read('mimetype'));
    }
  } catch (err) {
    if (err instanceof BadZipFile || isOsError(err) || err instanceof ZipMemberUnreadable) {
      return new Container(
        'zip',
        `a truncated or damaged zip archive (it starts with ${bytesRepr(head.subarray(0, 8))})`,
        named,
      );
    }
    throw err;
  }
  const members = new Set(names);
  for (const [member, kind] of ZIP_MEMBERS) {
    if (members.has(member)) return new Container(kind, `an OOXML package holding ${member}`, named);
  }
  if (mimetype.startsWith('application/vnd.oasis.opendocument')) {
    return new Container('odf', `an OpenDocument package (${mimetype})`, named);
  }
  const sample = pySorted(members).slice(0, 5).join(', ') || '(empty archive)';
  return new Container('zip', `a zip archive that is no OOXML package; it holds: ${sample}`, named);
}

/** `dict.get(key)`: own keys only, so `constructor` is not a hit. */
function lookup<T>(rec: Readonly<Record<string, T>>, key: string): T | undefined {
  return Object.hasOwn(rec, key) ? rec[key] : undefined;
}

/**
 * `except OSError`: a rejection the FILESYSTEM produced, or the `OSError` this reader raised
 * itself. A Node `fs` error carries a numeric `errno` and the `syscall` it came from; a
 * `zlib` error carries an `errno` (-3, `Z_DATA_ERROR`) but no syscall, and Node's own
 * `ERR_INVALID_ARG_VALUE` / `ERR_STRING_TOO_LONG` carry a string `code` and nothing else.
 * Until job43 G2 any Error with a string `code` passed here, so a corrupt deflate stream in a
 * rels part was swallowed as "no relationships" where the reference lets `zlib.error` escape.
 */
function isOsError(err: unknown): err is NodeJS.ErrnoException {
  if (err instanceof PyOSError) return true;
  const e = err as NodeJS.ErrnoException;
  return err instanceof Error && typeof e.errno === 'number' && typeof e.syscall === 'string';
}

/** Decode a TRUNCATED sample, tolerating a character the sample cut in half. */
function decodeHead(head: Uint8Array): string | null {
  const scan = utf8Scan(head, head.length < HEAD_BYTES);
  if (scan.invalidAt >= 0) return null;
  return decodeUtf8(head.subarray(0, scan.end));
}

function textKind(head: Uint8Array, named: string): Container | null {
  const text = decodeHead(head);
  if (text === null) return null;
  const stripped = pyLstripChars(text, '﻿ \t\r\n');
  const lines = pySplitlines(stripped).filter((line) => pyStrip(line));
  if (lines.length && MIME_HEADER.test(lines[0] as string)) {
    const block = lines.slice(0, 20).join('\n').toLowerCase();
    if (block.includes('mime-version:') || block.includes('content-type:')) {
      return new Container('mhtml', 'a MIME message / MHTML web archive', named);
    }
  }
  if (HTML_HEAD.test(sliceChars(stripped, 2048))) {
    return new Container('html', 'an HTML document', named);
  }
  let binary = false;
  for (const ch of text) {
    if (isBinaryControl(ch.codePointAt(0) as number)) {
      binary = true;
      break;
    }
  }
  if (!binary) return new Container('text', 'plain text in no document container', named);
  return null;
}

/** `text[:n]` counts CODE POINTS, which `String.prototype.slice` does not. */
function sliceChars(text: string, n: number): string {
  let out = '';
  let count = 0;
  for (const ch of text) {
    if (count >= n) break;
    out += ch;
    count += 1;
  }
  return out;
}

interface Stat {
  exists: boolean;
  isDir: boolean;
  size: number;
}

/** `Path.is_dir()`/`exists()`/`stat().st_size`, with pathlib's tolerance for a dead link. */
function statPath(path: string): Stat {
  try {
    const st = statSync(pyPathStr(path));
    return { exists: true, isDir: st.isDirectory(), size: st.size };
  } catch (err) {
    if (isOsError(err) && ['ENOENT', 'ENOTDIR', 'EBADF', 'ELOOP'].includes(err.code ?? '')) {
      return { exists: false, isDir: false, size: 0 };
    }
    // `Path('a\x00b').exists()` is False: `os.stat` raises `ValueError("embedded null
    // byte")` and pathlib's `exists`/`is_dir` catch it. Node refuses the same string with
    // `ERR_INVALID_ARG_VALUE` before any syscall, and until job43 G2 that reached the wire as
    // a fabricated `[Errno 0] ERR_INVALID_ARG_VALUE` where the reference says `no such file`.
    if (err instanceof Error && (err as NodeJS.ErrnoException).code === 'ERR_INVALID_ARG_VALUE') {
      return { exists: false, isDir: false, size: 0 };
    }
    throw err;
  }
}

/**
 * `handle.read(n)`: at most `n` bytes from the front of the file, never the whole file.
 *
 * The count is what `read(2)` RETURNS, never `st_size`: a device or procfs file reports
 * 0 bytes and still answers a read. Measured (job43 F3): `/dev/zero` was `an empty file
 * (0 bytes)` here while the reference read 4096 zero bytes and named `not a recognised
 * container`. The buffer grows a chunk at a time so a 12-byte file does not allocate the
 * 16 MiB `extract_text` may ask for.
 */
function readPrefix(path: string, n: number): Buffer {
  const fd = openSync(pyPathStr(path), 'r');
  try {
    const chunks: Buffer[] = [];
    let total = 0;
    while (total < n) {
      const chunk = Buffer.allocUnsafe(Math.min(n - total, 1 << 20));
      const got = readSync(fd, chunk, 0, chunk.length, total);
      if (got === 0) break;
      chunks.push(chunk.subarray(0, got));
      total += got;
    }
    return chunks.length === 1 ? chunks[0]! : Buffer.concat(chunks, total);
  } finally {
    closeSync(fd);
  }
}

/** What `path` IS. Magic bytes, then a zip's member list. The suffix is never consulted. */
export function sniff(path: string): Container {
  const st = statPath(path);
  if (st.isDir) throw new DocumentReadError(`${pyPathStr(path)} is a directory, not a document`);
  if (!st.exists) throw new DocumentReadError(`no such file: ${pyPathStr(path)}`);
  const named = pyPathSuffix(path).toLowerCase().replace(/^\.+/, '');
  const head = readPrefix(path, HEAD_BYTES);
  if (head.length === 0) return new Container('empty', 'an empty file (0 bytes)', named);
  if (head[0] === 0x50 && head[1] === 0x4b) return zipKind(path, head);
  for (const [magic, kind] of MAGIC) {
    if (startsWith(head, magic)) {
      if (kind === 'pdf') {
        const version = pyStrip(head.subarray(1, 8).toString('latin1'));
        return new Container('pdf', `a PDF document (${version})`, named);
      }
      return new Container(kind, lookup(WHAT, kind) ?? `a ${kind} file`, named);
    }
  }
  if (head.subarray(4, 8).toString('latin1') === 'ftyp') {
    const brand = pyStrip(head.subarray(8, 12).toString('latin1')) || '?';
    return new Container(
      'isobmff',
      `an ISO base-media container, brand ${pyRepr(brand)} (video/audio)`,
      named,
    );
  }
  const guessed = textKind(head, named);
  if (guessed !== null) return guessed;
  return new Container(
    'unknown',
    `not a recognised container; it starts with ${bytesRepr(head.subarray(0, 12))}`,
    named,
  );
}

/** The one refusal sentence, and it names the CONTENT before it names anything else. */
function refuse(path: string, container: Container, remedy: string): DocumentReadError {
  const size = statSync(pyPathStr(path)).size;
  let lie = '';
  if (container.suffixLies) lie = `; its name says .${container.named}, which its bytes do not`;
  return new DocumentReadError(
    `cannot read ${pyPathName(path)}: it is ${container.what}, ${size} bytes on disk${lie}. ${remedy}`,
  );
}

function unsupportedRemedy(): string {
  const direct = SUPPORTED.slice(0, -1).join(', ') + ` and ${SUPPORTED[SUPPORTED.length - 1]}`;
  const extra =
    TEXTUTIL_SUPPORTED.slice(0, -1).join(', ') +
    ` and ${TEXTUTIL_SUPPORTED[TEXTUTIL_SUPPORTED.length - 1]}`;
  return `this reader reads ${direct} directly, and ${extra} through ${TEXTUTIL}`;
}

// -------------------------------------------------------------------------------- zip

/** `zipfile.BadZipFile`. Not a `DocumentReadError`: the reference lets it through too. */
export class BadZipFile extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BadZipFile';
  }
}

interface ZipEntry {
  filename: string;
  method: number;
  flags: number;
  crc: number;
  compressedSize: number;
  fileSize: number;
  headerOffset: number;
}

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

export function crc32(buf: Uint8Array): number {
  let crc = -1;
  for (const b of buf) crc = (CRC_TABLE[(crc ^ b) & 0xff] as number) ^ (crc >>> 8);
  return (crc ^ -1) >>> 0;
}

// IBM code page 437, the name encoding a zip uses when its UTF-8 flag (bit 11) is clear.
const CP437_HIGH =
  'ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■\xa0';

function decodeZipName(raw: Uint8Array, flags: number): string {
  if (flags & 0x800) return decodeUtf8(raw);
  let out = '';
  for (const b of raw) out += b < 0x80 ? String.fromCharCode(b) : CP437_HIGH[b - 0x80];
  return out;
}

/** `zipfile.ZipFile` read-only: the central directory, and `read(name)` with a CRC check. */
export class ZipReader {
  private readonly byName = new Map<string, ZipEntry>();

  private constructor(
    private readonly data: Buffer,
    private readonly entries: readonly ZipEntry[],
    private readonly concat: number,
    /** `Path(p).name`, for the one sentence `read` composes itself (the bzip2/lzma ruling). */
    private readonly pathName: string,
  ) {
    for (const entry of entries) this.byName.set(entry.filename, entry);
  }

  static open(path: string): ZipReader {
    return ZipReader.from(readFileSync(pyPathStr(path)), pyPathName(path));
  }

  static from(data: Buffer, pathName = ''): ZipReader {
    // `_EndRecData`: the last 22 bytes are an EOCD with no comment, or the record is
    // searched for in the last 64 KiB + 22.
    const n = data.length;
    let eocd = -1;
    if (n >= 22 && data.readUInt32LE(n - 22) === 0x06054b50 && data.readUInt16LE(n - 2) === 0) {
      eocd = n - 22;
    } else {
      const start = Math.max(0, n - (1 << 16) - 22);
      for (let i = n - 22; i >= start; i -= 1) {
        if (data.readUInt32LE(i) === 0x06054b50) {
          eocd = i;
          break;
        }
      }
    }
    if (eocd < 0) throw new BadZipFile('File is not a zip file');
    let count = data.readUInt16LE(eocd + 10);
    let sizeCd = data.readUInt32LE(eocd + 12);
    let offsetCd = data.readUInt32LE(eocd + 16);
    let location = eocd;
    if (eocd >= 20 && data.readUInt32LE(eocd - 20) === 0x07064b50) {
      const zip64Offset = Number(data.readBigUInt64LE(eocd - 20 + 8));
      if (zip64Offset + 56 <= n && data.readUInt32LE(zip64Offset) === 0x06064b50) {
        count = Number(data.readBigUInt64LE(zip64Offset + 32));
        sizeCd = Number(data.readBigUInt64LE(zip64Offset + 40));
        offsetCd = Number(data.readBigUInt64LE(zip64Offset + 48));
        location = zip64Offset;
      }
    }
    const concat = location - sizeCd - offsetCd;
    const entries: ZipEntry[] = [];
    let pos = offsetCd + concat;
    // `_RealGetContents`: `if self.start_dir < 0: raise BadZipFile(...)`. Without it the
    // first `readUInt32LE` below throws a `RangeError` carrying `ERR_OUT_OF_RANGE`.
    if (pos < 0) throw new BadZipFile('Bad offset for central directory');
    for (let k = 0; k < count; k += 1) {
      if (pos + 46 > n || data.readUInt32LE(pos) !== 0x02014b50) {
        throw new BadZipFile('Bad magic number for central directory');
      }
      const flags = data.readUInt16LE(pos + 8);
      const method = data.readUInt16LE(pos + 10);
      const crc = data.readUInt32LE(pos + 16);
      let compressedSize = data.readUInt32LE(pos + 20);
      let fileSize = data.readUInt32LE(pos + 24);
      const nameLen = data.readUInt16LE(pos + 28);
      const extraLen = data.readUInt16LE(pos + 30);
      const commentLen = data.readUInt16LE(pos + 32);
      let headerOffset = data.readUInt32LE(pos + 42);
      const filename = decodeZipName(data.subarray(pos + 46, pos + 46 + nameLen), flags);
      // zip64 extra field: the 0xFFFFFFFF sentinels are replaced in this order.
      let extra = pos + 46 + nameLen;
      const extraEnd = extra + extraLen;
      while (extra + 4 <= extraEnd) {
        const id = data.readUInt16LE(extra);
        const len = data.readUInt16LE(extra + 2);
        if (id === 0x0001) {
          let at = extra + 4;
          if (fileSize === 0xffffffff && at + 8 <= extraEnd) {
            fileSize = Number(data.readBigUInt64LE(at));
            at += 8;
          }
          if (compressedSize === 0xffffffff && at + 8 <= extraEnd) {
            compressedSize = Number(data.readBigUInt64LE(at));
            at += 8;
          }
          if (headerOffset === 0xffffffff && at + 8 <= extraEnd) {
            headerOffset = Number(data.readBigUInt64LE(at));
          }
        }
        extra += 4 + len;
      }
      entries.push({ filename, method, flags, crc, compressedSize, fileSize, headerOffset });
      pos += 46 + nameLen + extraLen + commentLen;
    }
    return new ZipReader(data, entries, concat, pathName);
  }

  namelist(): string[] {
    return this.entries.map((e) => e.filename);
  }

  /** `infolist()` reduced to what `_media_index` reads: name, size, and whether it is a directory. */
  infolist(): { filename: string; fileSize: number; isDir: boolean }[] {
    return this.entries.map((e) => ({
      filename: e.filename,
      fileSize: e.fileSize,
      isDir: e.filename.endsWith('/'),
    }));
  }

  has(name: string): boolean {
    return this.byName.has(name);
  }

  /** `ZipFile.read(name)`; a missing member is a `KeyError` — here `RangeError`, see `readMember`. */
  read(name: string): Buffer {
    const entry = this.byName.get(name);
    if (entry === undefined) throw new RangeError(`There is no item named ${pyRepr(name)} in the archive`);
    const at = entry.headerOffset + this.concat;
    const data = this.data;
    // `ZipFile.open` seeks to `header_offset`, and a NEGATIVE offset — an EOCD whose
    // central-directory offset overshoots, so `concat` is a large negative number — is
    // `fp.seek(-n)`, which the C library refuses as `OSError(EINVAL)`. The reference lets
    // that reach the model as `[Errno 22] Invalid argument`, no filename (measured, job43
    // F3, EOCD offset 0x7FFFFFF0). This port read from a `Buffer`, so the same archive
    // threw `RangeError: The value of "offset" is out of range ...` and the handler printed
    // `[Errno 0] ERR_OUT_OF_RANGE`.
    if (at < 0) throw new PyOSError(22, 'EINVAL', 'Invalid argument', null);
    if (at + 30 > data.length || data.readUInt32LE(at) !== 0x04034b50) {
      throw new BadZipFile('Bad magic number for file header');
    }
    // `RuntimeError("File 'x' is encrypted, password required for extraction")`, raised
    // off the central directory's flag before the data is touched. `readMember` words it.
    if (entry.flags & 0x1) throw new ZipMemberUnreadable(name);
    const nameLen = data.readUInt16LE(at + 26);
    const extraLen = data.readUInt16LE(at + 28);
    const start = at + 30 + nameLen + extraLen;
    const raw = data.subarray(start, start + entry.compressedSize);
    let out: Buffer;
    if (entry.method === 0) out = Buffer.from(raw);
    else if (entry.method === 8) out = inflateRaw(raw);
    else if (entry.method === 12 || entry.method === 14) {
      // DELIBERATE DIVERGENCE (docs/porting.md, "bzip2 and lzma zip members on Node"): the
      // reference's `zipfile` decompresses methods 12 and 14 through the stdlib `bz2` and
      // `lzma` modules; Node core has neither, and a decompressor is not a dependency this
      // package takes. The sentence is in the pdf/doc/rtf ruling family: what the member is,
      // which server reads it, where the ruling is written down.
      throw new DocumentReadError(
        `${this.pathName} is a zip but its ${name} uses compression method ${entry.method} ` +
          `(${entry.method === 12 ? 'bzip2' : 'lzma'}), which the Node server cannot decompress ` +
          '(the Python server reads it); see docs/porting.md',
      );
    } else {
      // `NotImplementedError("That compression method is not supported")` — which IS a
      // `RuntimeError` on the reference, so `_read`'s `except RuntimeError` turns it into the
      // ENCRYPTED sentence (measured, job43 G2: a stored member relabelled method 9 reads
      // `... is encrypted, so this reader cannot read it without a password` there). Same
      // class here, so the same words.
      throw new ZipMemberUnreadable(name);
    }
    if (crc32(out) !== entry.crc) throw new BadZipFile(`Bad CRC-32 for file ${pyRepr(name)}`);
    return out;
  }
}

/**
 * `ZipFile.read`'s `RuntimeError` family: the member is encrypted, or (its subclass
 * `NotImplementedError`) compressed by a method zipfile has no decompressor for. Not a
 * `DocumentReadError` itself, because the reference's `_read` is what words it, and the
 * parts `_rel_targets`/`_date_formats`/`_zip_kind` read swallow it silently instead.
 */
export class ZipMemberUnreadable extends Error {
  constructor(readonly member: string) {
    super(`File ${pyRepr(member)} is encrypted, password required for extraction`);
    this.name = 'ZipMemberUnreadable';
  }
}

/**
 * `zlib.decompressobj(-15).decompress(raw)` as `zipfile` calls it, with CPython's errors.
 *
 * A stream zlib rejects is `zlib.error("Error -3 while decompressing data: invalid block
 * type")` — the number is zlib's return code and the phrase is zlib's own `msg`, which Node
 * exposes as `errno` and `message`, so the sentence is rebuilt rather than translated. A
 * stream that merely ENDS early is not an error to `decompressobj` — it hands back what it
 * has, and `ZipExtFile` then fails the CRC — so `Z_BUF_ERROR` is retried with a sync flush
 * for the same partial bytes, and the CRC check in `read` refuses them the way it does there.
 */
function inflateRaw(raw: Buffer): Buffer {
  try {
    return inflateRawSync(raw);
  } catch (err) {
    const e = err as NodeJS.ErrnoException;
    if (!(err instanceof Error) || typeof e.errno !== 'number') throw err;
    if (e.code === 'Z_BUF_ERROR') return inflateRawSync(raw, { finishFlush: zlibConstants.Z_SYNC_FLUSH });
    const out = new Error(`Error ${e.errno} while decompressing data: ${e.message}`);
    // `type(zlib.error).__name__` is `error` — the class is `zlib.error`, and `error` is what
    // the reference records for it (`tools/conformance/ref/docread_ref.py`, `_error`).
    out.name = 'error';
    throw out;
  }
}

function openZip(path: string): ZipReader {
  if (!statPath(path).exists) throw new DocumentReadError(`no such file: ${pyPathStr(path)}`);
  try {
    return ZipReader.open(path);
  } catch (err) {
    if (!(err instanceof BadZipFile)) throw err;
    const head = readPrefix(path, 8);
    throw new DocumentReadError(
      `${pyPathName(path)} is not a zip archive, so it is not an OOXML document; ` +
        `it starts with ${bytesRepr(head)} (${statSync(pyPathStr(path)).size} bytes on disk)`,
    );
  }
}

/**
 * `_parse`: one part this reader cannot do without, or the refusal in the reader's words.
 *
 * The sentence carries NO line, column or parser phrase, on purpose: the reference's expat
 * and this hand-written walk would never agree on one, and the sentence is what the model
 * reads. `relTargets` and `dateFormats` are not routed through here, as `_rel_targets` and
 * `_date_formats` are not: a broken rels or styles part costs an omission or a date format,
 * never the rows.
 */
function parsePart(data: Uint8Array, member: string, path: string): XmlElement {
  try {
    return parseXml(data);
  } catch (err) {
    if (!(err instanceof XmlParseError)) throw err;
    throw new DocumentReadError(
      `${pyPathName(path)} is a zip but its ${member} is not well-formed XML, so this reader cannot parse it`,
    );
  }
}

function readMember(zf: ZipReader, name: string, path: string): Buffer {
  if (!zf.has(name)) {
    const sample = pySorted(zf.namelist()).slice(0, 8).join(', ') || '(empty archive)';
    throw new DocumentReadError(`${pyPathName(path)} is a zip but has no ${name}; it contains: ${sample}`);
  }
  try {
    return zf.read(name);
  } catch (err) {
    if (!(err instanceof ZipMemberUnreadable)) throw err;
    // `_read`'s `except RuntimeError`: the member and the fact, nothing zipfile said. Until
    // job43 G1/G2 zipfile's own sentence crossed the wire as an `isError` frame on both sides.
    throw new DocumentReadError(
      `${pyPathName(path)} is a zip but its ${name} is encrypted, so this reader cannot read it without a password`,
    );
  }
}

// -------------------------------------------------------------------------------- xml

/** `xml.etree.ElementTree.ParseError`. Not a `DocumentReadError`: the reference lets it through. */
export class XmlParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'XmlParseError';
  }
}

/** An element the way ET exposes one: expanded `{ns}tag`, attributes, `.text`, children. */
export class XmlElement {
  text = '';
  readonly children: XmlElement[] = [];
  constructor(
    public readonly tag: string,
    public readonly attrs: Map<string, string>,
  ) {}

  get(name: string): string | undefined {
    return this.attrs.get(name);
  }

  /** `Element.find(tag)`: the first DIRECT child with that tag. */
  find(tag: string): XmlElement | undefined {
    return this.children.find((c) => c.tag === tag);
  }

  /** `Element.iter(tag)`: this element and every descendant, document order. */
  *iter(tag?: string): IterableIterator<XmlElement> {
    if (tag === undefined || this.tag === tag) yield this;
    for (const child of this.children) yield* child.iter(tag);
  }
}

const XML_NS = 'http://www.w3.org/XML/1998/namespace';
const XML_NAME = /[:A-Za-z_\p{L}\p{Nl}][-.:A-Za-z0-9_\u00b7\p{L}\p{Nl}\p{Mn}\p{Mc}\p{Nd}\p{Pc}]*/uy;

const XML_ENTITIES = new Map([
  ['amp', '&'],
  ['lt', '<'],
  ['gt', '>'],
  ['quot', '"'],
  ['apos', "'"],
]);

/** XML 1.0 `Char`: what a character reference may name. `&#0;` and a surrogate may not. */
function isXmlChar(cp: number): boolean {
  return (
    cp === 0x9 ||
    cp === 0xa ||
    cp === 0xd ||
    (cp >= 0x20 && cp <= 0xd7ff) ||
    (cp >= 0xe000 && cp <= 0xfffd) ||
    (cp >= 0x10000 && cp <= 0x10ffff)
  );
}

/**
 * A declared encoding expat has no decoder for. `LookupError("unknown encoding: x")` on the
 * reference — NOT an `ET.ParseError`, so `_parse` does not word it and it escapes to the
 * wire as a raised exception; the same class of thing here, deliberately not `XmlParseError`.
 */
export class XmlEncodingError extends Error {
  constructor(encoding: string) {
    super(`unknown encoding: ${encoding}`);
    this.name = 'LookupError';
  }
}

// `cp1252` bytes 0x80–0x9F, 0 where the codec has no character (0x81, 0x8D, 0x8F, 0x90, 0x9D).
const CP1252_HIGH = [
  0x20ac, 0, 0x201a, 0x0192, 0x201e, 0x2026, 0x2020, 0x2021, 0x02c6, 0x2030, 0x0160, 0x2039, 0x0152, 0, 0x017d, 0,
  0, 0x2018, 0x2019, 0x201c, 0x201d, 0x2022, 0x2013, 0x2014, 0x02dc, 0x2122, 0x0161, 0x203a, 0x0153, 0, 0x017e, 0x0178,
];

// `<?xml version="1.0" encoding="..." standalone="..."?>` — the three in that order, or
// expat's "XML declaration not well-formed".
const XML_DECL =
  /^<\?xml[ \t\r\n]+version[ \t\r\n]*=[ \t\r\n]*(["'])1\.[0-9]+\1(?:[ \t\r\n]+encoding[ \t\r\n]*=[ \t\r\n]*(["'])([A-Za-z][A-Za-z0-9._-]*)\2)?(?:[ \t\r\n]+standalone[ \t\r\n]*=[ \t\r\n]*(["'])(?:yes|no)\4)?[ \t\r\n]*\?>/;

/**
 * The bytes of an XML part as the characters expat hands ET.
 *
 * A byte-order mark decides first (UTF-8's is dropped, UTF-16's picks the byte order); then
 * the declaration's `encoding`; then UTF-8. The property, measured against `ET.fromstring`
 * (job43 G2): UTF-8 is STRICT — `<a>caf\xe9</a>` with no declaration is "not well-formed
 * (invalid token)", where until G2 this port decoded it lossily to `caf�` and read a
 * row the reference refuses; `encoding="ISO-8859-1"` over the same byte reads `café`, and
 * over `\xc3\xa9` reads `Ã©`, because a declaration is obeyed and not sniffed past;
 * `US-ASCII` refuses any byte over 0x7f; a name no codec answers to is `LookupError`.
 * Every other name goes to `TextDecoder`, which has the single-byte codecs CPython has
 * (windows-125x, iso-8859-x, koi8) but not utf-7 — the docs/porting.md utf-7 row.
 */
function decodeXmlSource(data: Uint8Array): string {
  let bytes = data;
  if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) bytes = bytes.subarray(3);
  // A UTF-16 byte-order mark, or expat's BOM-less detection off the first `<`: `3C 00` is
  // little-endian, `00 3C` big-endian.
  const bom = (bytes[0] === 0xff && bytes[1] === 0xfe) || (bytes[0] === 0xfe && bytes[1] === 0xff);
  const bare16 = (bytes[0] === 0x3c && bytes[1] === 0x00) || (bytes[0] === 0x00 && bytes[1] === 0x3c);
  if (bom || bare16) {
    const order = bytes[0] === 0xff || bytes[0] === 0x3c ? 'utf-16le' : 'utf-16be';
    try {
      return new TextDecoder(order, { fatal: true, ignoreBOM: !bom }).decode(bytes);
    } catch {
      throw new XmlParseError('not well-formed (invalid token)');
    }
  }
  const head = Buffer.from(bytes.buffer, bytes.byteOffset, Math.min(bytes.length, 1024)).toString('latin1');
  let encoding: string | null = null;
  if (/^<\?xml[ \t\r\n?]/.test(head)) {
    const m = XML_DECL.exec(head);
    if (!m) throw new XmlParseError('XML declaration not well-formed');
    encoding = m[3] === undefined ? null : m[3].toLowerCase();
  }
  const name = (encoding ?? 'utf-8').replace(/_/g, '-');
  if (['utf-8', 'utf8'].includes(name)) {
    const scan = utf8Scan(bytes, true);
    if (scan.invalidAt >= 0) throw new XmlParseError('not well-formed (invalid token)');
    return decodeUtf8(bytes);
  }
  if (['iso-8859-1', 'iso8859-1', 'latin-1', 'latin1', 'l1', '8859', 'cp819'].includes(name)) {
    return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.length).toString('latin1');
  }
  if (['us-ascii', 'ascii', 'us', '646', 'ansi-x3.4-1968'].includes(name)) {
    for (const b of bytes) if (b >= 0x80) throw new XmlParseError('not well-formed (invalid token)');
    return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.length).toString('latin1');
  }
  if (['utf-16', 'utf16'].includes(name)) {
    // No BOM: expat assumes the little-endian order (measured on the reference).
    return new TextDecoder('utf-16le', { fatal: true, ignoreBOM: true }).decode(bytes);
  }
  if (['windows-1252', 'cp1252', '1252'].includes(name)) {
    // Node's `TextDecoder('windows-1252')` takes a latin1 fast path and answers U+0093 for
    // 0x93 (measured, job43 G2); CPython's `cp1252` answers U+201C, and expat sees the codec's
    // answer. The 0x80–0x9F row is spelled out; a byte the codec has no character for is
    // what expat refuses (measured: 0x81, 0x8D, 0x8F, 0x90, 0x9D are "not well-formed").
    let out = '';
    for (const b of bytes) {
      if (b < 0x80 || b >= 0xa0) out += String.fromCharCode(b);
      else {
        const ch = CP1252_HIGH[b - 0x80] as number;
        if (ch === 0) throw new XmlParseError('not well-formed (invalid token)');
        out += String.fromCharCode(ch);
      }
    }
    return out;
  }
  let decoder: { decode(input: Uint8Array): string };
  try {
    decoder = new TextDecoder(name, { fatal: true, ignoreBOM: true });
  } catch {
    throw new XmlEncodingError(encoding as string);
  }
  try {
    return decoder.decode(bytes);
  } catch {
    throw new XmlParseError('not well-formed (invalid token)');
  }
}

// Every character of the decoded document must be an XML 1.0 `Char`: `\x01`, `\x0c` and
// NUL in text, in an attribute, anywhere, are "not well-formed (invalid token)" to expat
// (measured, job43 G2); `\x7f` and the C1 range are allowed. A lone surrogate cannot come
// out of the decoders above, so the class is the BMP's non-characters and C0.
// eslint-disable-next-line no-control-regex
const NOT_XML_CHAR = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/;

/** The `<!ENTITY name "replacement">` declarations of a document's internal subset. */
type EntityMap = Map<string, string>;

/**
 * A reference's body — `#123`, `#x1F`, `lt`, or a declared name — resolved through the
 * predefined five and `entities`, or `XmlParseError`; `resolve` is how the caller expands a
 * declared entity in ITS context (an attribute value cannot hold markup, a text run can).
 */
function refValue(body: string, entities: EntityMap, resolve: (name: string) => string): string {
  let cp: number;
  if (/^#x[0-9a-fA-F]+$/.test(body)) cp = parseInt(body.slice(2), 16);
  else if (/^#[0-9]+$/.test(body)) cp = parseInt(body.slice(1), 10);
  else {
    const known = XML_ENTITIES.get(body);
    if (known !== undefined) return known;
    if (!/^[A-Za-z_:][-.:A-Za-z0-9_]*$/.test(body)) throw new XmlParseError('not well-formed (invalid token)');
    if (!entities.has(body)) throw new XmlParseError(`undefined entity: &${body};`);
    return resolve(body);
  }
  if (!isXmlChar(cp)) throw new XmlParseError('reference to invalid character number');
  return String.fromCodePoint(cp);
}

/**
 * Text and attribute values with their references expanded, or `XmlParseError`.
 *
 * Every `&` MUST begin a well-formed reference — expat says `not well-formed (invalid
 * token)` for a bare one, `&amp b` without its semicolon, `&#0;`, `&#xD800;` (a surrogate)
 * and `&#x110000;` (past Unicode). Until job43 F3 this port accepted all of them: `a & b`
 * came back as a row where the reference refused the whole part, and `&#x110000;` threw a
 * `RangeError` out of `String.fromCodePoint`. The five predefined names are the only named
 * entities an OOXML part may use without a DTD; a name the internal subset declared is
 * expanded through `resolve` (job43 G2), and any other name is "undefined entity".
 */
function xmlUnescape(text: string, entities: EntityMap = NO_ENTITIES, resolve: (name: string) => string = undefinedEntity): string {
  if (!text.includes('&')) return text;
  let out = '';
  let i = 0;
  for (;;) {
    const amp = text.indexOf('&', i);
    if (amp < 0) return out + text.slice(i);
    out += text.slice(i, amp);
    const semi = text.indexOf(';', amp + 1);
    if (semi < 0) throw new XmlParseError('not well-formed (invalid token)');
    out += refValue(text.slice(amp + 1, semi), entities, resolve);
    i = semi + 1;
  }
}

const NO_ENTITIES: EntityMap = new Map();
function undefinedEntity(name: string): string {
  throw new XmlParseError(`undefined entity: &${name};`);
}

/**
 * The internal subset of a `<!DOCTYPE ... [ ... ]>`: its `<!ENTITY name "value">`
 * declarations, and where the declaration ends.
 *
 * What expat does with the subset, reduced to what an OOXML part could carry: a general
 * entity with a literal value is declared (the first declaration of a name wins; a
 * character reference in the value is expanded at declaration time, a general-entity
 * reference is kept for use time, a bare `&` is refused); a parameter entity (`%`), an
 * external entity (`SYSTEM`/`PUBLIC`) and every other declaration (`ELEMENT`, `ATTLIST`,
 * `NOTATION`) are skipped over their quoted strings; comments and processing instructions
 * inside the subset are skipped, so an `<!ENTITY>` inside a comment declares nothing.
 * Measured against `ET.fromstring` on fourteen subset shapes (job43 G2).
 */
function parseDoctype(src: string, at: number): { end: number; entities: EntityMap } {
  const entities: EntityMap = new Map();
  const n = src.length;
  let i = at + 2;
  const skipQuoted = (): void => {
    const q = src[i] as string;
    const close = src.indexOf(q, i + 1);
    if (close < 0) throw new XmlParseError('unterminated declaration');
    i = close + 1;
  };
  // The prolog of the declaration: up to `[` or `>`, honouring quoted external identifiers.
  for (; i < n; i += 1) {
    const ch = src[i];
    if (ch === '"' || ch === "'") {
      skipQuoted();
      i -= 1;
    } else if (ch === '[' || ch === '>') break;
  }
  if (i >= n) throw new XmlParseError('unterminated declaration');
  if (src[i] === '>') return { end: i + 1, entities };
  i += 1;
  for (;;) {
    while (i < n && ' \t\n'.includes(src[i] as string)) i += 1;
    if (i >= n) throw new XmlParseError('unterminated declaration');
    if (src[i] === ']') break;
    if (src.startsWith('<!--', i)) {
      const j = src.indexOf('-->', i + 4);
      if (j < 0) throw new XmlParseError('unterminated comment');
      i = j + 3;
      continue;
    }
    if (src.startsWith('<?', i)) {
      const j = src.indexOf('?>', i + 2);
      if (j < 0) throw new XmlParseError('unterminated processing instruction');
      i = j + 2;
      continue;
    }
    if (src[i] === '%') {
      // A parameter-entity reference in the subset: `%name;` — nothing to expand here.
      const j = src.indexOf(';', i + 1);
      if (j < 0) throw new XmlParseError('not well-formed (invalid token)');
      i = j + 1;
      continue;
    }
    if (!src.startsWith('<!', i)) throw new XmlParseError('not well-formed (invalid token)');
    const isEntity = src.startsWith('<!ENTITY', i) && ' \t\n'.includes(src[i + 8] ?? '');
    i += 2;
    let name: string | null = null;
    let value: string | null = null;
    if (isEntity) {
      i += 6;
      while (i < n && ' \t\n'.includes(src[i] as string)) i += 1;
      let parameter = false;
      if (src[i] === '%') {
        parameter = true;
        i += 1;
        while (i < n && ' \t\n'.includes(src[i] as string)) i += 1;
      }
      XML_NAME.lastIndex = i;
      const m = XML_NAME.exec(src);
      if (!m || m.index !== i) throw new XmlParseError('not well-formed (invalid token)');
      i += m[0].length;
      while (i < n && ' \t\n'.includes(src[i] as string)) i += 1;
      if (src[i] === '"' || src[i] === "'") {
        const q = src[i] as string;
        const close = src.indexOf(q, i + 1);
        if (close < 0) throw new XmlParseError('unterminated declaration');
        if (!parameter) {
          name = m[0];
          value = src.slice(i + 1, close);
        }
        i = close + 1;
      }
    }
    // The rest of this declaration, to its `>`, over any quoted string.
    for (; i < n; i += 1) {
      const ch = src[i];
      if (ch === '"' || ch === "'") {
        skipQuoted();
        i -= 1;
      } else if (ch === '>') break;
    }
    if (i >= n) throw new XmlParseError('unterminated declaration');
    i += 1;
    if (name !== null && value !== null && !entities.has(name)) {
      // Character references are expanded now; `&name;` stays for use time; `&` bare or
      // `%` in a literal are refused as expat refuses them.
      let text = '';
      let k = 0;
      for (;;) {
        const amp = value.indexOf('&', k);
        if (amp < 0) {
          text += value.slice(k);
          break;
        }
        text += value.slice(k, amp);
        const semi = value.indexOf(';', amp + 1);
        if (semi < 0) throw new XmlParseError('not well-formed (invalid token)');
        const body = value.slice(amp + 1, semi);
        if (body.startsWith('#')) text += refValue(body, NO_ENTITIES, undefinedEntity);
        else if (/^[A-Za-z_:][-.:A-Za-z0-9_]*$/.test(body)) text += `&${body};`;
        else throw new XmlParseError('not well-formed (invalid token)');
        k = semi + 1;
      }
      if (text.includes('%')) throw new XmlParseError('not well-formed (invalid token)');
      entities.set(name, text);
    }
  }
  i += 1;
  while (i < n && ' \t\n'.includes(src[i] as string)) i += 1;
  if (src[i] !== '>') throw new XmlParseError('not well-formed (invalid token)');
  return { end: i + 1, entities };
}

/**
 * A strict-enough XML reader: one root, matched tags, declared prefixes, the five
 * predefined entities and the internal subset's own, comments and PIs dropped, CDATA kept,
 * line ends normalised, and attribute values whitespace-normalised — what expat gives ET
 * for an OOXML part.
 *
 * A declared entity is expanded the way expat expands it: in a text run its replacement
 * text is PARSED in place, so `<!ENTITY e "<x>in</x>y">` yields an element, and a
 * replacement that opens what it does not close is "asynchronous entity"; in an attribute
 * value it is expanded as text and may not contain `<`; a reference to the entity being
 * expanded is "recursive entity reference". Measured against `ET.fromstring` (job43 G2).
 */
export function parseXml(data: Uint8Array): XmlElement {
  const src = decodeXmlSource(data).replace(/\r\n?/g, '\n');
  if (NOT_XML_CHAR.test(src)) throw new XmlParseError('not well-formed (invalid token)');
  const stack: { el: XmlElement; ns: Map<string, string> }[] = [];
  let root: XmlElement | undefined;
  let entities: EntityMap = NO_ENTITIES;
  let doctypeSeen = false;
  const expanding = new Set<string>();
  const appendText = (text: string): void => {
    const top = stack[stack.length - 1];
    if (top === undefined) {
      if (pyStrip(text)) throw new XmlParseError('text outside the root element');
      return;
    }
    if (top.el.children.length === 0) top.el.text += text;
  };
  /** A declared entity in an attribute value: text only, no markup, no cycles. */
  const attrEntity = (name: string): string => {
    if (expanding.has(name)) throw new XmlParseError('recursive entity reference');
    const replacement = entities.get(name) as string;
    if (replacement.includes('<')) throw new XmlParseError('not well-formed (invalid token)');
    expanding.add(name);
    try {
      // Attribute-value normalisation reaches into the replacement text: a literal tab or
      // newline there (a character reference's included) becomes a space.
      return xmlUnescape(replacement.replace(/[\t\n]/g, ' '), entities, attrEntity);
    } finally {
      expanding.delete(name);
    }
  };
  /** A declared entity in a text run: its replacement text parsed here, at this depth. */
  const textEntity = (name: string): void => {
    if (expanding.has(name)) throw new XmlParseError('recursive entity reference');
    const depth = stack.length;
    expanding.add(name);
    try {
      scan(entities.get(name) as string, true);
    } finally {
      expanding.delete(name);
    }
    if (stack.length !== depth) throw new XmlParseError('asynchronous entity');
  };
  /** A run of character data: references expanded, declared entities parsed in place. */
  const emitText = (run: string): void => {
    if (run.includes(']]>')) throw new XmlParseError('not well-formed (invalid token)');
    let i = 0;
    for (;;) {
      const amp = run.indexOf('&', i);
      if (amp < 0) {
        appendText(xmlUnescape(run.slice(i)));
        return;
      }
      const semi = run.indexOf(';', amp + 1);
      if (semi < 0) throw new XmlParseError('not well-formed (invalid token)');
      const body = run.slice(amp + 1, semi);
      if (body.startsWith('#') || !entities.has(body)) {
        appendText(xmlUnescape(run.slice(i, semi + 1), entities, undefinedEntity));
      } else {
        appendText(xmlUnescape(run.slice(i, amp)));
        textEntity(body);
      }
      i = semi + 1;
    }
  };
  const scan = (text: string, inEntity: boolean): void => {
    let i = 0;
    const n = text.length;
    const fail: (what: string) => never = (what) => {
      throw new XmlParseError(`${what} at offset ${i}`);
    };
    const expand = (qname: string, ns: Map<string, string>, isAttr: boolean): string => {
      const colon = qname.indexOf(':');
      if (colon < 0) {
        if (isAttr) return qname;
        const def = ns.get('');
        return def ? `{${def}}${qname}` : qname;
      }
      const prefix = qname.slice(0, colon);
      const local = qname.slice(colon + 1);
      if (prefix === 'xml') return `{${XML_NS}}${local}`;
      const uri = ns.get(prefix);
      if (uri === undefined) return fail(`unbound prefix ${prefix}`);
      return `{${uri}}${local}`;
    };
    while (i < n) {
      if (text[i] !== '<') {
        const j = text.indexOf('<', i);
        const end = j < 0 ? n : j;
        emitText(text.slice(i, end));
        i = end;
        continue;
      }
      if (text.startsWith('<!--', i)) {
        const j = text.indexOf('-->', i + 4);
        if (j < 0) fail('unterminated comment');
        i = j + 3;
        continue;
      }
      if (text.startsWith('<![CDATA[', i)) {
        const j = text.indexOf(']]>', i + 9);
        if (j < 0) fail('unterminated CDATA section');
        appendText(text.slice(i + 9, j));
        i = j + 3;
        continue;
      }
      if (text.startsWith('<?', i)) {
        const j = text.indexOf('?>', i + 2);
        if (j < 0) fail('unterminated processing instruction');
        // `<?xml ...?>` anywhere but the very start is "XML or text declaration not at
        // start of entity"; at the start it was read by `decodeXmlSource` already.
        if (i !== 0 && /^<\?xml(?![-.:A-Za-z0-9_])/i.test(text.slice(i, i + 6))) {
          fail('XML or text declaration not at start of entity');
        }
        i = j + 2;
        continue;
      }
      if (text.startsWith('<!', i)) {
        if (!text.startsWith('<!DOCTYPE', i) || inEntity || root !== undefined || stack.length || doctypeSeen) {
          fail('not well-formed (invalid token)');
        }
        doctypeSeen = true;
        const doctype = parseDoctype(text, i);
        entities = doctype.entities;
        i = doctype.end;
        continue;
      }
      if (text.startsWith('</', i)) {
        XML_NAME.lastIndex = i + 2;
        const m = XML_NAME.exec(text);
        if (!m) return fail('malformed end tag');
        let j = i + 2 + m[0].length;
        while (j < n && ' \t\n'.includes(text[j] as string)) j += 1;
        if (text[j] !== '>') return fail('malformed end tag');
        const top = stack.pop();
        if (top === undefined) return fail('end tag with no open element');
        const expected = expand(m[0], top.ns, false);
        if (expected !== top.el.tag) fail('mismatched tag');
        i = j + 1;
        continue;
      }
      // A start tag.
      XML_NAME.lastIndex = i + 1;
      const m = XML_NAME.exec(text);
      if (!m) return fail('not well-formed');
      const qname = m[0];
      let j = i + 1 + qname.length;
      const rawAttrs: [string, string][] = [];
      let selfClosing = false;
      for (;;) {
        while (j < n && ' \t\n'.includes(text[j] as string)) j += 1;
        if (j >= n) fail('unterminated start tag');
        if (text[j] === '>') {
          j += 1;
          break;
        }
        if (text[j] === '/' && text[j + 1] === '>') {
          selfClosing = true;
          j += 2;
          break;
        }
        XML_NAME.lastIndex = j;
        const am = XML_NAME.exec(text);
        if (!am) return fail('malformed attribute');
        j += am[0].length;
        while (j < n && ' \t\n'.includes(text[j] as string)) j += 1;
        if (text[j] !== '=') fail('attribute without value');
        j += 1;
        while (j < n && ' \t\n'.includes(text[j] as string)) j += 1;
        const quote = text[j];
        if (quote !== '"' && quote !== "'") return fail('unquoted attribute value');
        const close = text.indexOf(quote, j + 1);
        if (close < 0) fail('unterminated attribute value');
        const value = text.slice(j + 1, close);
        if (value.includes('<')) fail("'<' in attribute value");
        rawAttrs.push([am[0], xmlUnescape(value.replace(/[\t\n]/g, ' '), entities, attrEntity)]);
        j = close + 1;
      }
      const parentNs = stack[stack.length - 1]?.ns ?? new Map<string, string>();
      let ns = parentNs;
      for (const [name, value] of rawAttrs) {
        if (name === 'xmlns' || name.startsWith('xmlns:')) {
          if (ns === parentNs) ns = new Map(parentNs);
          ns.set(name === 'xmlns' ? '' : name.slice(6), value);
        }
      }
      const attrs = new Map<string, string>();
      for (const [name, value] of rawAttrs) {
        if (name === 'xmlns' || name.startsWith('xmlns:')) continue;
        const key = expand(name, ns, true);
        if (attrs.has(key)) fail('duplicate attribute');
        attrs.set(key, value);
      }
      const el = new XmlElement(expand(qname, ns, false), attrs);
      const parent = stack[stack.length - 1];
      if (parent === undefined) {
        if (root !== undefined) fail('junk after document element');
        root = el;
      } else {
        parent.el.children.push(el);
      }
      if (!selfClosing) stack.push({ el, ns });
      i = j;
    }
  };
  scan(src, false);
  if (stack.length) throw new XmlParseError('unclosed element');
  if (root === undefined) throw new XmlParseError('no element found');
  return root;
}

// ------------------------------------------- what an OOXML package holds that no row carries

const MEDIA_MEMBER = /(?:^|\/)(?:media|embeddings)\/[^/]+$/;

function mediaIndex(zf: ZipReader): Map<string, number> {
  const out = new Map<string, number>();
  for (const info of zf.infolist()) {
    if (!info.isDir && MEDIA_MEMBER.test(info.filename)) out.set(info.filename, info.fileSize);
  }
  return out;
}

function relTargets(zf: ZipReader, member: string, members: Set<string>): string[] {
  const rels = posix.join(posix.dirname(member), '_rels', posix.basename(member) + '.rels');
  if (!members.has(rels)) return [];
  let tree: XmlElement;
  try {
    tree = parseXml(zf.read(rels));
  } catch (err) {
    if (err instanceof XmlParseError || err instanceof RangeError || isOsError(err) || err instanceof ZipMemberUnreadable) {
      return [];
    }
    throw err;
  }
  const out: string[] = [];
  for (const rel of tree.children) {
    const target = rel.get('Target') ?? '';
    if (!target || rel.get('TargetMode') === 'External' || target.includes('://')) continue;
    if (target.startsWith('/')) out.push(target.replace(/^\/+/, ''));
    else out.push(posix.normalize(posix.join(posix.dirname(member), target)));
  }
  return out;
}

function anchoredMedia(zf: ZipReader, member: string, media: Map<string, number>): Map<string, number> {
  const members = new Set(zf.namelist());
  const reached = new Map<string, number>();
  for (const first of relTargets(zf, member, members)) {
    const direct = media.get(first);
    if (direct !== undefined) {
      reached.set(first, direct);
      continue;
    }
    for (const second of relTargets(zf, first, members)) {
      const size = media.get(second);
      if (size !== undefined) reached.set(second, size);
    }
  }
  return reached;
}

const BUILTIN_DATE_FORMATS: Readonly<Record<number, string>> = {
  14: 'mm-dd-yy',
  15: 'd-mmm-yy',
  16: 'd-mmm',
  17: 'mmm-yy',
  18: 'h:mm AM/PM',
  19: 'h:mm:ss AM/PM',
  20: 'h:mm',
  21: 'h:mm:ss',
  22: 'm/d/yy h:mm',
  45: 'mm:ss',
  46: '[h]:mm:ss',
  47: 'mmss.0',
};

function isLocaleDateId(id: number): boolean {
  return (id >= 27 && id <= 36) || (id >= 50 && id <= 58);
}

const FORMAT_LITERAL = /\[[^\]]*\]|"[^"]*"|\\[^\n]/g;

export function isDateFormat(code: string): boolean {
  const bare = (code.replace(FORMAT_LITERAL, '').split(';')[0] as string).toLowerCase();
  return [...'ymdhs'].some((ch) => bare.includes(ch));
}

function dateFormats(zf: ZipReader): string[] {
  if (!zf.has('xl/styles.xml')) return [];
  let root: XmlElement;
  try {
    root = parseXml(zf.read('xl/styles.xml'));
  } catch (err) {
    if (err instanceof XmlParseError || err instanceof RangeError || isOsError(err) || err instanceof ZipMemberUnreadable) {
      return [];
    }
    throw err;
  }
  const custom = new Map<number, string>();
  for (const node of root.iter(NS_S + 'numFmt')) {
    const id = pyInt(node.get('numFmtId') || '-1');
    if (id === null) continue;
    custom.set(id, node.get('formatCode') || '');
  }
  const cellXfs = root.find(NS_S + 'cellXfs');
  const out: string[] = [];
  for (const xf of cellXfs ? cellXfs.children : []) {
    const fmtId = pyInt(xf.get('numFmtId') || '0');
    if (fmtId === null) {
      out.push('');
      continue;
    }
    const code = custom.get(fmtId);
    if (code !== undefined) out.push(isDateFormat(code) ? code : '');
    else if (BUILTIN_DATE_FORMATS[fmtId] !== undefined) out.push(BUILTIN_DATE_FORMATS[fmtId] as string);
    else if (isLocaleDateId(fmtId)) out.push(`built-in numFmtId ${fmtId} (locale-dependent date)`);
    else out.push('');
  }
  return out;
}

/** 0 -> `A`. */
export function columnLetter(index: number): string {
  let letters = '';
  let i = index + 1;
  while (i) {
    const rem = (i - 1) % 26;
    i = Math.floor((i - 1) / 26);
    letters = String.fromCharCode(65 + rem) + letters;
  }
  return letters;
}

/** `B7` -> 1. The cell's own reference decides its column; XML order is only a fallback. */
export function columnIndex(ref: string | undefined, fallback: number): number {
  if (!ref) return fallback;
  let index = 0;
  for (const ch of ref) {
    if (!/\p{L}/u.test(ch)) break;
    index = index * 26 + ((ch.toUpperCase().codePointAt(0) as number) - 64);
  }
  return index ? index - 1 : fallback;
}

function sharedStrings(zf: ZipReader, path: string): string[] {
  if (!zf.has('xl/sharedStrings.xml')) return [];
  const out: string[] = [];
  for (const si of parsePart(zf.read('xl/sharedStrings.xml'), 'xl/sharedStrings.xml', path).children) {
    const runs: string[] = [];
    for (const child of si.children) {
      if (child.tag === NS_S + 't') runs.push(child.text);
      else if (child.tag === NS_S + 'r') {
        for (const sub of child.children) if (sub.tag === NS_S + 't') runs.push(sub.text);
      }
    }
    out.push(runs.join(''));
  }
  return out;
}

function cellText(cell: XmlElement, shared: readonly string[]): string {
  const kind = cell.get('t');
  if (kind === 'inlineStr') {
    const node = cell.find(NS_S + 'is');
    if (node === undefined) return '';
    let out = '';
    for (const t of node.iter(NS_S + 't')) out += t.text;
    return out;
  }
  const value = cell.find(NS_S + 'v');
  const raw = value === undefined ? '' : value.text;
  if (kind === 's') {
    const index = pyInt(raw);
    const hit = index === null ? undefined : pyIndex(shared, index);
    if (hit === undefined) {
      throw new DocumentReadError(
        `cell ${cell.get('r') ?? 'None'} indexes shared string ${pyRepr(raw)}, ` +
          `but the table has ${shared.length} entries`,
      );
    }
    return hit;
  }
  if (kind === 'b') return raw === '1' ? 'TRUE' : 'FALSE';
  return raw;
}

function sheetRows(
  root: XmlElement,
  shared: readonly string[],
  dateStyles: readonly string[] = [],
): [string[], Omission[]] {
  const rows: string[] = [];
  let blank = 0;
  const dated = new Map<string, Map<number, number>>();
  for (const row of root.iter(NS_S + 'row')) {
    const cells = new Map<number, string>();
    let position = 0;
    for (const cell of row.iter(NS_S + 'c')) {
      const text = clean(cellText(cell, shared));
      const at = position;
      position += 1;
      if (!text) continue;
      const column = columnIndex(cell.get('r'), at);
      cells.set(column, text);
      const t = cell.get('t');
      if (t === undefined || t === 'n') {
        const style = pyInt(cell.get('s') || '0');
        const code = style === null ? '' : (pyIndex(dateStyles, style) ?? '');
        if (code) {
          let columns = dated.get(code);
          if (columns === undefined) {
            columns = new Map();
            dated.set(code, columns);
          }
          columns.set(column, (columns.get(column) ?? 0) + 1);
        }
      }
    }
    const width = cells.size ? Math.max(...cells.keys()) + 1 : 0;
    const fields: string[] = [];
    for (let k = 0; k < width; k += 1) fields.push(cells.get(k) ?? '');
    const line = fields.join('\t');
    if (!line) blank += 1;
    rows.push(line);
  }
  const omissions: Omission[] = [];
  if (blank) omissions.push(new Omission(OMIT_BLANK_ROWS, blank));
  for (const code of pySorted(dated.keys())) {
    const columns = dated.get(code) as Map<number, number>;
    const sortedColumns = [...columns.keys()].sort((a, b) => a - b);
    omissions.push(
      new Omission(
        OMIT_NUMBER_FORMAT,
        [...columns.values()].reduce((a, b) => a + b, 0),
        0,
        sortedColumns.map(columnLetter),
        code,
      ),
    );
  }
  return [rows, omissions];
}

function worksheetTargets(zf: ZipReader, path: string): [string, string | undefined][] {
  const workbook = parsePart(readMember(zf, 'xl/workbook.xml', path), 'xl/workbook.xml', path);
  const rels = new Map<string | undefined, string>();
  const member = 'xl/_rels/workbook.xml.rels';
  for (const rel of parsePart(readMember(zf, member, path), member, path).children) {
    const target = rel.get('Target') ?? '';
    if (target.startsWith('/')) rels.set(rel.get('Id'), target.replace(/^\/+/, ''));
    else rels.set(rel.get('Id'), posix.normalize(posix.join('xl', target)));
  }
  const out: [string, string | undefined][] = [];
  let order = 0;
  for (const sheet of workbook.iter(NS_S + 'sheet')) {
    const rid = sheet.get(NS_R + 'id');
    const target = rid ? rels.get(rid) : `xl/worksheets/sheet${order + 1}.xml`;
    out.push([sheet.get('name') || `sheet${order + 1}`, target]);
    order += 1;
  }
  return out;
}

function mediaOmission(media: Map<string, number>): Omission[] {
  if (media.size === 0) return [];
  const kinds = new Set<string>();
  for (const name of media.keys()) {
    kinds.add(posixSplitextExt(name).replace(/^\.+/, '').toLowerCase() || '?');
  }
  let size = 0;
  for (const bytes of media.values()) size += bytes;
  return [new Omission(OMIT_MEDIA, media.size, size, [], pySorted(kinds).join(', '))];
}

export function extractXlsx(path: string): Document {
  const zf = openZip(path);
  const shared = sharedStrings(zf, path);
  const dateStyles = dateFormats(zf);
  const media = mediaIndex(zf);
  const parts: Part[] = [];
  let index = 0;
  for (const [name, target] of worksheetTargets(zf, path)) {
    if (target === undefined) {
      throw new DocumentReadError(`sheet ${pyRepr(name)} has no resolvable worksheet part`);
    }
    const sheet = parsePart(readMember(zf, target, path), target, path);
    const [rows, sheetOmissions] = sheetRows(sheet, shared, dateStyles);
    const omissions = [...mediaOmission(anchoredMedia(zf, target, media)), ...sheetOmissions];
    parts.push(new Part(name, index, rows, omissions));
    index += 1;
  }
  return new Document('xlsx', parts, mediaOmission(media));
}

export function extractDocx(path: string): Document {
  const zf = openZip(path);
  const root = parsePart(readMember(zf, 'word/document.xml', path), 'word/document.xml', path);
  const media = mediaIndex(zf);
  const anchored = mediaOmission(anchoredMedia(zf, 'word/document.xml', media));
  const rows: string[] = [];
  for (const para of root.iter(NS_W + 'p')) {
    const runs: string[] = [];
    for (const node of para.iter()) {
      if (node.tag === NS_W + 't') runs.push(node.text);
      else if (node.tag === NS_W + 'tab' || node.tag === NS_W + 'br' || node.tag === NS_W + 'cr') runs.push(' ');
    }
    const text = pyStrip(clean(runs.join('')));
    if (text) rows.push(text);
  }
  const body = new Part('document', 0, rows, anchored);
  return new Document('docx', [body], mediaOmission(media));
}

// ------------------------------------------------------------------- HTML (html.parser)

const BLOCK_TAGS = new Set(
  'p div br hr li tr h1 h2 h3 h4 h5 h6 table tbody thead blockquote pre section article header footer nav aside figure figcaption dt dd ul ol form fieldset title'.split(
    ' ',
  ),
);
const FIELD_TAGS = new Set(['td', 'th']);
const SILENT_TAGS = new Set(['script', 'style', 'template', 'noscript']);

const INVALID_CHARREFS: Readonly<Record<number, string>> = {
  0x00: '�',
  0x0d: '\r',
  0x80: '€',
  0x81: '\x81',
  0x82: '‚',
  0x83: 'ƒ',
  0x84: '„',
  0x85: '…',
  0x86: '†',
  0x87: '‡',
  0x88: 'ˆ',
  0x89: '‰',
  0x8a: 'Š',
  0x8b: '‹',
  0x8c: 'Œ',
  0x8d: '\x8d',
  0x8e: 'Ž',
  0x8f: '\x8f',
  0x90: '\x90',
  0x91: '‘',
  0x92: '’',
  0x93: '“',
  0x94: '”',
  0x95: '•',
  0x96: '–',
  0x97: '—',
  0x98: '˜',
  0x99: '™',
  0x9a: 'š',
  0x9b: '›',
  0x9c: 'œ',
  0x9d: '\x9d',
  0x9e: 'ž',
  0x9f: 'Ÿ',
};

function isInvalidCodepoint(num: number): boolean {
  if ((num >= 0x1 && num <= 0x8) || (num >= 0xe && num <= 0x1f) || (num >= 0x7f && num <= 0x9f)) return true;
  if (num >= 0xfdd0 && num <= 0xfdef) return true;
  if (num === 0xb) return true;
  return (num & 0xfffe) === 0xfffe && num <= 0x10ffff;
}

const CHARREF = /&(#[0-9]+;?|#[xX][0-9a-fA-F]+;?|[^\t\n\f <&#;]{1,32};?)/g;

function replaceCharref(s: string): string {
  if (s[0] === '#') {
    const num = s[1] === 'x' || s[1] === 'X' ? parseInt(s.slice(2).replace(/;$/, ''), 16) : parseInt(s.slice(1).replace(/;$/, ''), 10);
    const invalid = INVALID_CHARREFS[num];
    if (invalid !== undefined) return invalid;
    if ((num >= 0xd800 && num <= 0xdfff) || num > 0x10ffff) return '�';
    if (isInvalidCodepoint(num)) return '';
    return String.fromCodePoint(num);
  }
  const whole = HTML5_ENTITIES.get(s);
  if (whole !== undefined) return whole;
  for (let x = s.length - 1; x > 1; x -= 1) {
    const hit = HTML5_ENTITIES.get(s.slice(0, x));
    if (hit !== undefined) return hit + s.slice(x);
  }
  return '&' + s;
}

/** `html.unescape`. */
export function unescape(s: string): string {
  if (!s.includes('&')) return s;
  return s.replace(CHARREF, (_, body: string) => replaceCharref(body));
}

const TAGFIND_TOLERANT = /([a-zA-Z][^\t\n\r\f />]*)(?:[\t\n\r\f ]|\/(?!>))*/y;
const ATTRFIND_TOLERANT =
  /((?<=['"\t\n\r\f /])[^\t\n\r\f />][^\t\n\r\f /=>]*)([\t\n\r\f ]*=[\t\n\r\f ]*('[^']*'|"[^"]*"|(?!['"])[^>\t\n\r\f ]*))?(?:[\t\n\r\f ]|\/(?!>))*/y;
const LOCATETAGEND =
  /[a-zA-Z][^\t\n\r\f />]*[\t\n\r\f /]*(?:(?<=['"\t\n\r\f /])[^\t\n\r\f />][^\t\n\r\f /=>]*(?:[\t\n\r\f ]*=[\t\n\r\f ]*(?:'[^']*'|"[^"]*"|(?!['"])[^>\t\n\r\f ]*))?[\t\n\r\f /]*)*>?/y;
const STARTTAGOPEN = /<[a-zA-Z]/y;
const ENDTAGOPEN = /<\/[a-zA-Z]/y;
const COMMENTCLOSE = /--!?>/g;
const COMMENTABRUPTCLOSE = /-?>/y;
const CHARREF_TOKEN = /&#(?:[0-9]+|[xX][0-9a-fA-F]+)[^0-9a-fA-F]/y;
const ENTITYREF_TOKEN = /&([a-zA-Z][-.a-zA-Z0-9]*)[^a-zA-Z0-9]/y;
const INCOMPLETE_TOKEN = /&[a-zA-Z#]/y;
const CDATA_CONTENT_ELEMENTS = new Set(['script', 'style', 'xmp', 'iframe', 'noembed', 'noframes']);
const RCDATA_CONTENT_ELEMENTS = new Set(['textarea', 'title']);

function stickyMatch(re: RegExp, s: string, at: number): RegExpExecArray | null {
  re.lastIndex = at;
  return re.exec(s);
}

/**
 * `html.parser.HTMLParser`, `convert_charrefs=True`, ported statement for statement from
 * CPython 3.12.13 — including the RAWTEXT handling of `<script>`/`<style>` and the RCDATA
 * handling of `<title>`/`<textarea>` that release carries. Only the three handlers
 * `_HtmlText` overrides do anything; comments, declarations and PIs are consumed and
 * dropped exactly where the reference drops them.
 */
abstract class HtmlParserBase {
  private rawdata = '';
  private cdataElem: string | null = null;
  private escapable = true;
  private interesting: RegExp | null = null;

  abstract handleStarttag(tag: string): void;
  abstract handleEndtag(tag: string): void;
  abstract handleData(data: string): void;

  feed(data: string): void {
    this.rawdata += data;
    this.goahead(false);
  }

  close(): void {
    this.goahead(true);
  }

  private setCdataMode(elem: string, escapable: boolean): void {
    this.cdataElem = elem.toLowerCase();
    this.escapable = escapable;
    if (this.cdataElem === 'plaintext') this.interesting = /$(?![\s\S])/g;
    else this.interesting = new RegExp(`</${this.cdataElem}(?=[\\t\\n\\r\\f />])`, 'ig');
  }

  private clearCdataMode(): void {
    this.interesting = null;
    this.cdataElem = null;
    this.escapable = true;
  }

  private goahead(end: boolean): void {
    const rawdata = this.rawdata;
    let i = 0;
    const n = rawdata.length;
    while (i < n) {
      let j: number;
      if (!this.cdataElem) {
        j = rawdata.indexOf('<', i);
        if (j < 0) {
          const amppos = rawdata.lastIndexOf('&', n - 1);
          const from = Math.max(i, n - 34);
          const amp = amppos >= from ? amppos : -1;
          if (amp >= 0 && !/[\t\n\r\f ;]/.test(rawdata.slice(amp))) break;
          j = n;
        }
      } else {
        const re = this.interesting as RegExp;
        re.lastIndex = i;
        const match = re.exec(rawdata);
        if (match) j = match.index;
        else break;
      }
      if (i < j) {
        if (this.escapable) this.handleData(unescape(rawdata.slice(i, j)));
        else this.handleData(rawdata.slice(i, j));
      }
      i = j;
      if (i === n) break;
      if (rawdata.startsWith('<', i)) {
        let k: number;
        if (stickyMatch(STARTTAGOPEN, rawdata, i)) k = this.parseStarttag(i);
        else if (rawdata.startsWith('</', i)) k = this.parseEndtag(i);
        else if (rawdata.startsWith('<!--', i)) k = this.parseComment(i);
        else if (rawdata.startsWith('<?', i)) k = this.parsePi(i);
        else if (rawdata.startsWith('<!', i)) k = this.parseHtmlDeclaration(i);
        else if (i + 1 < n || end) {
          this.handleData('<');
          k = i + 1;
        } else break;
        if (k < 0) {
          if (!end) break;
          if (rawdata.startsWith('</', i) && i + 2 === n) this.handleData('</');
          k = n;
        }
        i = k;
      } else if (rawdata.startsWith('&#', i)) {
        // Unreachable with convert_charrefs=True outside cdata mode; kept for shape.
        const match = stickyMatch(CHARREF_TOKEN, rawdata, i);
        if (match) {
          let k = i + match[0].length;
          if (rawdata[k - 1] !== ';') k -= 1;
          i = k;
          continue;
        }
        if (rawdata.slice(i).includes(';')) {
          this.handleData(rawdata.slice(i, i + 2));
          i += 2;
        }
        break;
      } else if (rawdata.startsWith('&', i)) {
        const match = stickyMatch(ENTITYREF_TOKEN, rawdata, i);
        if (match) {
          let k = i + match[0].length;
          if (rawdata[k - 1] !== ';') k -= 1;
          i = k;
          continue;
        }
        if (stickyMatch(INCOMPLETE_TOKEN, rawdata, i)) break;
        if (i + 1 < n) {
          this.handleData('&');
          i += 1;
        } else break;
      } else {
        throw new Error('interesting.search() lied');
      }
    }
    if (end && i < n) {
      if (this.escapable) this.handleData(unescape(rawdata.slice(i, n)));
      else this.handleData(rawdata.slice(i, n));
      i = n;
    }
    this.rawdata = rawdata.slice(i);
  }

  private parseHtmlDeclaration(i: number): number {
    const rawdata = this.rawdata;
    if (rawdata.startsWith('<!--', i)) return this.parseComment(i);
    if (rawdata.startsWith('<![CDATA[', i)) {
      const j = rawdata.indexOf(']]>', i + 9);
      return j < 0 ? -1 : j + 3;
    }
    if (rawdata.slice(i, i + 9).toLowerCase() === '<!doctype') {
      const gtpos = rawdata.indexOf('>', i + 9);
      return gtpos === -1 ? -1 : gtpos + 1;
    }
    if (rawdata.startsWith('<![', i)) {
      const j = rawdata.indexOf('>', i + 3);
      return j < 0 ? -1 : j + 1;
    }
    return this.parseBogusComment(i);
  }

  private parseComment(i: number): number {
    const rawdata = this.rawdata;
    COMMENTCLOSE.lastIndex = i + 4;
    let match: RegExpExecArray | null = COMMENTCLOSE.exec(rawdata);
    if (!match) {
      match = stickyMatch(COMMENTABRUPTCLOSE, rawdata, i + 4);
      if (!match) return -1;
    }
    return match.index + match[0].length;
  }

  private parseBogusComment(i: number): number {
    const pos = this.rawdata.indexOf('>', i + 2);
    return pos === -1 ? -1 : pos + 1;
  }

  private parsePi(i: number): number {
    const pos = this.rawdata.indexOf('>', i + 2);
    return pos === -1 ? -1 : pos + 1;
  }

  private parseStarttag(i: number): number {
    const rawdata = this.rawdata;
    const endpos = this.checkForWholeStartTag(i);
    if (endpos < 0) return endpos;
    const match = stickyMatch(TAGFIND_TOLERANT, rawdata, i + 1) as RegExpExecArray;
    let k = i + 1 + match[0].length;
    const tag = (match[1] as string).toLowerCase();
    while (k < endpos) {
      const m = stickyMatch(ATTRFIND_TOLERANT, rawdata, k);
      if (!m || m[0].length === 0) break;
      k += m[0].length;
    }
    const endText = pyStrip(rawdata.slice(k, endpos));
    if (endText !== '>' && endText !== '/>') {
      this.handleData(rawdata.slice(i, endpos));
      return endpos;
    }
    if (endText.endsWith('/>')) {
      this.handleStarttag(tag);
      this.handleEndtag(tag);
    } else {
      this.handleStarttag(tag);
      if (CDATA_CONTENT_ELEMENTS.has(tag) || tag === 'plaintext') this.setCdataMode(tag, false);
      else if (RCDATA_CONTENT_ELEMENTS.has(tag)) this.setCdataMode(tag, true);
    }
    return endpos;
  }

  private checkForWholeStartTag(i: number): number {
    const match = stickyMatch(LOCATETAGEND, this.rawdata, i + 1) as RegExpExecArray;
    const j = i + 1 + match[0].length;
    return this.rawdata[j - 1] !== '>' ? -1 : j;
  }

  private parseEndtag(i: number): number {
    const rawdata = this.rawdata;
    if (rawdata.indexOf('>', i + 2) < 0) return -1;
    if (!stickyMatch(ENDTAGOPEN, rawdata, i)) {
      if (rawdata[i + 2] === '>') return i + 3;
      return this.parseBogusComment(i);
    }
    const match = stickyMatch(LOCATETAGEND, rawdata, i + 2) as RegExpExecArray;
    const j = i + 2 + match[0].length;
    if (rawdata[j - 1] !== '>') return -1;
    const name = stickyMatch(TAGFIND_TOLERANT, rawdata, i + 2) as RegExpExecArray;
    this.handleEndtag((name[1] as string).toLowerCase());
    this.clearCdataMode();
    return j;
  }
}

/** HTML to rows. Block markup ends a row, `<td>`/`<th>` separate fields with a tab. */
class HtmlText extends HtmlParserBase {
  readonly rows: string[] = [];
  private fields: string[] = [];
  private silent = 0;

  handleStarttag(tag: string): void {
    if (SILENT_TAGS.has(tag)) this.silent += 1;
    else if (FIELD_TAGS.has(tag)) this.fields.push('');
    else if (BLOCK_TAGS.has(tag)) this.flush();
  }

  handleEndtag(tag: string): void {
    if (SILENT_TAGS.has(tag)) this.silent = Math.max(0, this.silent - 1);
    else if (BLOCK_TAGS.has(tag)) this.flush();
  }

  handleData(data: string): void {
    if (this.silent) return;
    const text = pySplit(data).join(' ');
    if (!text) return;
    if (this.fields.length) {
      const last = this.fields.length - 1;
      this.fields[last] = pyStrip(`${this.fields[last]} ${text}`);
    } else {
      this.fields.push(text);
    }
  }

  private flush(): void {
    const line = pyStrip(pyStripChars(this.fields.map((field) => pyStrip(clean(field))).join('\t'), '\t'));
    this.fields = [];
    if (line) this.rows.push(line);
  }

  override close(): void {
    super.close();
    this.flush();
  }
}

/** Rendered rows of one HTML fragment. A pure function of the string: no I/O, no host. */
export function htmlRows(markup: string): string[] {
  const parser = new HtmlText();
  parser.feed(markup);
  parser.close();
  return parser.rows;
}

// ------------------------------------------------------------------------ MIME (email)

interface MimePart {
  headers: [string, string][];
  /** The body bytes, as a latin1 string (one char per byte), when this part is a leaf. */
  body: string | null;
  children: MimePart[];
  defaultType: string;
}

/** `Message.get(name)`: the first header of that name, unfolded the way the policy does. */
function header(part: MimePart, name: string): string | undefined {
  const want = name.toLowerCase();
  for (const [key, value] of part.headers) {
    if (key.toLowerCase() === want) return value.replace(/[\r\n]/g, '');
  }
  return undefined;
}

/** `email.message._parseparam`. */
function parseParam(s: string): string[] {
  s = ';' + s;
  const plist: string[] = [];
  while (s.startsWith(';')) {
    s = s.slice(1);
    let end = s.indexOf(';');
    const count = (text: string, needle: string): number => text.split(needle).length - 1;
    while (end > 0 && (count(s.slice(0, end), '"') - count(s.slice(0, end), '\\"')) % 2) {
      end = s.indexOf(';', end + 1);
    }
    if (end < 0) end = s.length;
    let f = s.slice(0, end);
    if (f.includes('=')) {
      const i = f.indexOf('=');
      f = pyStrip(f.slice(0, i)).toLowerCase() + '=' + pyStrip(f.slice(i + 1));
    }
    plist.push(pyStrip(f));
    s = s.slice(end);
  }
  return plist;
}

function unquoteValue(value: string): string {
  if (value.length > 1) {
    if (value.startsWith('"') && value.endsWith('"')) {
      return value.slice(1, -1).replace(/\\\\/g, '\\').replace(/\\"/g, '"');
    }
    if (value.startsWith('<') && value.endsWith('>')) return value.slice(1, -1);
  }
  return value;
}

function getParam(part: MimePart, name: string): string | undefined {
  const value = header(part, 'content-type');
  if (value === undefined) return undefined;
  for (const p of parseParam(value)) {
    let key: string;
    let val: string;
    const eq = p.indexOf('=');
    if (eq >= 0) {
      key = pyStrip(p.slice(0, eq));
      val = pyStrip(p.slice(eq + 1));
    } else {
      key = pyStrip(p);
      val = '';
    }
    if (key.toLowerCase() === name.toLowerCase()) return unquoteValue(val);
  }
  return undefined;
}

function contentType(part: MimePart): string {
  const value = header(part, 'content-type');
  if (value === undefined) return part.defaultType;
  const ctype = pyStrip(value.split(';')[0] as string).toLowerCase();
  if (ctype.split('/').length - 1 !== 1) return 'text/plain';
  return ctype;
}

function contentMaintype(part: MimePart): string {
  return contentType(part).split('/')[0] as string;
}

function contentSubtype(part: MimePart): string {
  return contentType(part).split('/')[1] as string;
}

function contentCharset(part: MimePart): string | undefined {
  const charset = getParam(part, 'charset');
  if (charset === undefined) return undefined;
  // eslint-disable-next-line no-control-regex
  if (/[^\x00-\x7f]/.test(charset)) return undefined;
  return charset.toLowerCase();
}

/** `binascii.a2b_qp(data, header=False)`, i.e. `quopri.decodestring`. */
export function decodeQuotedPrintable(data: Uint8Array): Buffer {
  const out: number[] = [];
  const n = data.length;
  let i = 0;
  const isHex = (b: number) => (b >= 0x30 && b <= 0x39) || (b >= 0x41 && b <= 0x46) || (b >= 0x61 && b <= 0x66);
  while (i < n) {
    const b = data[i] as number;
    if (b === 0x3d) {
      i += 1;
      if (i >= n) break;
      const c = data[i] as number;
      if (c === 0x0a || c === 0x0d) {
        if (c !== 0x0a) while (i < n && data[i] !== 0x0a) i += 1;
        if (i < n) i += 1;
      } else if (c === 0x3d) {
        out.push(0x3d);
        i += 1;
      } else if (i + 1 < n && isHex(c) && isHex(data[i + 1] as number)) {
        out.push(parseInt(String.fromCharCode(c, data[i + 1] as number), 16));
        i += 2;
      } else {
        out.push(0x3d);
      }
    } else {
      out.push(b);
      i += 1;
    }
  }
  return Buffer.from(out);
}

/** `binascii.Error`, which is a `ValueError`. */
class BinasciiError extends Error {}

/**
 * `binascii.a2b_uu(line)`: one uuencoded line to its bytes, in the C module's own steps.
 *
 * The first character is the byte count; each following character carries six bits, a line
 * end or a line that ran out counts as zero ("some spaces got eaten at end-of-line"); a
 * character outside `' '..'\x60'` is "Illegal char"; and whatever is left after the count
 * is satisfied must be space, backtick or a line end, or it is "Trailing garbage".
 */
export function a2bUu(line: Uint8Array): Buffer {
  // An empty line is 32 zero bytes on the reference (measured: `a2b_uu(b'')`), the count a
  // missing first character implies — the same answer as a NUL first character.
  let binLen = line.length === 0 ? 32 : ((line[0] as number) - 0x20) & 0x3f;
  const out: number[] = [];
  let i = 1;
  let leftchar = 0;
  let leftbits = 0;
  for (; binLen > 0; i += 1) {
    let ch: number;
    if (i >= line.length) ch = 0;
    else {
      ch = line[i] as number;
      if (ch === 0x0a || ch === 0x0d) ch = 0;
      else {
        if (ch < 0x20 || ch > 0x20 + 64) throw new BinasciiError('Illegal char');
        ch = (ch - 0x20) & 0x3f;
      }
    }
    leftchar = (leftchar << 6) | ch;
    leftbits += 6;
    if (leftbits >= 8) {
      leftbits -= 8;
      out.push((leftchar >> leftbits) & 0xff);
      leftchar &= (1 << leftbits) - 1;
      binLen -= 1;
    }
  }
  for (; i < line.length; i += 1) {
    const ch = line[i] as number;
    if (ch !== 0x20 && ch !== 0x20 + 64 && ch !== 0x0a && ch !== 0x0d) throw new BinasciiError('Trailing garbage');
  }
  return Buffer.from(out);
}

/** `bytes.splitlines()`: `\n`, `\r` and `\r\n` split, no trailing empty line. */
function bytesSplitlines(data: Buffer): Buffer[] {
  const out: Buffer[] = [];
  let start = 0;
  for (let i = 0; i < data.length; i += 1) {
    const b = data[i];
    if (b === 0x0a || b === 0x0d) {
      out.push(data.subarray(start, i));
      if (b === 0x0d && data[i + 1] === 0x0a) i += 1;
      start = i + 1;
    }
  }
  if (start < data.length) out.push(data.subarray(start));
  return out;
}

/**
 * `email.message._decode_uu`: the lines between `begin <octal mode> ...` and `end`, or
 * `ValueError` — which `get_payload` answers with the payload UNDECODED.
 *
 * `begin` must start the line and its mode must parse in base 8; a blank line before `end`
 * is "Truncated input"; `end` is recognised stripped of ` \t\r\n\f`; and a line
 * `a2b_uu` rejects is retried cut to the length its count character implies (the workaround
 * for broken encoders that the stdlib carries by name). Measured against the reference
 * (job43 G2) on seventeen payload shapes, including the Truncated and no-`begin` ones.
 */
export function decodeUu(encoded: Buffer): Buffer {
  const lines = bytesSplitlines(encoded);
  let at = 0;
  for (;;) {
    if (at >= lines.length) throw new BinasciiError('`begin` line not found');
    const line = lines[at] as Buffer;
    at += 1;
    if (line.subarray(0, 6).toString('latin1') === 'begin ') {
      const mode = line.subarray(6).toString('latin1').split(' ')[0] as string;
      // `int(mode, base=8)`: a sign, optional `0o`, octal digits with single underscores.
      if (/^[ \t\n\x0b\x0c\r]*[+-]?(?:0[oO]_?)?[0-7]+(?:_[0-7]+)*[ \t\n\x0b\x0c\r]*$/.test(mode)) break;
    }
  }
  const out: Buffer[] = [];
  for (; at < lines.length; at += 1) {
    const line = lines[at] as Buffer;
    if (line.length === 0) throw new BinasciiError('Truncated input');
    if (line.toString('latin1').replace(/^[ \t\r\n\f]+|[ \t\r\n\f]+$/g, '') === 'end') break;
    try {
      out.push(a2bUu(line));
    } catch (err) {
      if (!(err instanceof BinasciiError)) throw err;
      const nbytes = Math.floor(((((line[0] as number) - 32) & 63) * 4 + 5) / 3);
      out.push(a2bUu(line.subarray(0, nbytes)));
    }
  }
  return Buffer.concat(out);
}

/** `Message.get_payload(decode=True)` for a leaf; `null` for a multipart the way it is there. */
function decodedPayload(part: MimePart): Buffer | null {
  if (part.body === null) return null;
  const raw = Buffer.from(part.body, 'latin1');
  const cte = (header(part, 'content-transfer-encoding') ?? '').toLowerCase();
  if (cte === 'quoted-printable') return decodeQuotedPrintable(raw);
  if (['x-uuencode', 'uuencode', 'uue', 'x-uue'].includes(cte)) {
    // `except ValueError: return bpayload` — a payload that will not decode is handed back
    // as it is, `begin` line and all, and read as text.
    try {
      return decodeUu(raw);
    } catch (err) {
      if (err instanceof BinasciiError) return raw;
      throw err;
    }
  }
  if (cte === 'base64') {
    const joined = part.body.replace(/\r\n|\r|\n/g, '');
    const pad = joined.length % 4;
    return Buffer.from(pad ? joined + '='.repeat(4 - pad) : joined, 'base64');
  }
  return raw;
}

const HEADER_LINE = /^(From |[\x21-\x39\x3b-\x7e]*:|[\t ])/;

function splitLines(text: string): string[] {
  // `NLCRE_crack`: every line keeps its own terminator.
  const out: string[] = [];
  let start = 0;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === '\n') {
      out.push(text.slice(start, i + 1));
      start = i + 1;
    } else if (ch === '\r') {
      const end = text[i + 1] === '\n' ? i + 2 : i + 1;
      out.push(text.slice(start, end));
      start = end;
      i = end - 1;
    }
  }
  if (start < text.length) out.push(text.slice(start));
  return out;
}

function stripEol(line: string): string {
  return line.replace(/\r\n$|\r$|\n$/, '');
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** `email.feedparser` for what `extract_mhtml` walks: headers, multipart, message/*. */
function parseMessage(lines: string[], defaultType: string): MimePart {
  const part: MimePart = { headers: [], body: null, children: [], defaultType };
  // `_parse_headers`: up to the first line that is not a header; a blank line is consumed.
  let at = 0;
  const raw: string[][] = [];
  while (at < lines.length) {
    const line = lines[at] as string;
    if (!HEADER_LINE.test(line)) {
      if (/^(\r\n|\r|\n)$/.test(line)) at += 1;
      break;
    }
    if (/^[ \t]/.test(line) && raw.length) (raw[raw.length - 1] as string[]).push(line);
    else raw.push([line]);
    at += 1;
  }
  for (const source of raw) {
    const first = source[0] as string;
    if (first.startsWith('From ')) continue;
    const colon = first.indexOf(':');
    if (colon < 0) continue;
    const name = first.slice(0, colon);
    const value = (first.slice(colon + 1).replace(/^[ \t]+/, '') + source.slice(1).join('')).replace(/[\r\n]+$/, '');
    part.headers.push([name, value]);
  }
  const body = lines.slice(at);
  const maintype = contentMaintype(part);
  if (maintype === 'message') {
    part.children.push(parseMessage(body, 'text/plain'));
    return part;
  }
  if (maintype === 'multipart') {
    const boundary = getParam(part, 'boundary');
    if (boundary === undefined) {
      part.body = body.join('');
      return part;
    }
    const childDefault = contentType(part) === 'multipart/digest' ? 'message/rfc822' : 'text/plain';
    const boundaryRe = new RegExp(`^(--${escapeRegex(pyRstrip(boundary))})(--)?([ \\t]*)(\\r\\n|\\r|\\n)?$`);
    let k = 0;
    let sawBoundary = false;
    while (k < body.length) {
      const line = body[k] as string;
      const mo = boundaryRe.exec(line);
      k += 1;
      if (!mo) continue;
      if (mo[2]) break;
      // Consume any multiple boundary lines that may be following.
      while (k < body.length && boundaryRe.test(body[k] as string)) k += 1;
      const sub: string[] = [];
      while (k < body.length && !boundaryRe.test(body[k] as string)) {
        sub.push(body[k] as string);
        k += 1;
      }
      const child = parseMessage(sub, childDefault);
      // The newline preceding the boundary belongs to the boundary, not to the part — and
      // the reference strips it after every subpart, closing boundary seen or not.
      if (child.body !== null) child.body = stripEol(child.body);
      part.children.push(child);
      sawBoundary = true;
    }
    if (!sawBoundary) part.body = body.join('');
    return part;
  }
  part.body = body.join('');
  return part;
}

function* walk(part: MimePart): IterableIterator<MimePart> {
  yield part;
  for (const child of part.children) yield* walk(child);
}

function decodedBody(part: MimePart): string {
  const payload = decodedPayload(part);
  if (payload === null) return '';
  return decodeCharset(payload, contentCharset(part) ?? 'utf-8');
}

export function extractMhtml(path: string): Document {
  const message = parseMessage(splitLines(readFileSync(pyPathStr(path)).toString('latin1')), 'text/plain');
  const bodies: [string, string][] = [];
  const skipped = new Map<string, number>();
  let skippedBytes = 0;
  for (const part of walk(message)) {
    if (contentMaintype(part) === 'multipart') continue;
    const subtype = contentSubtype(part);
    if (contentMaintype(part) !== 'text' || (subtype !== 'html' && subtype !== 'plain')) {
      const payload = decodedPayload(part);
      const type = contentType(part);
      skipped.set(type, (skipped.get(type) ?? 0) + 1);
      skippedBytes += payload ? payload.length : 0;
      continue;
    }
    const body = decodedBody(part);
    if (pyStrip(body)) bodies.push([subtype, body]);
  }
  const parts: Part[] = [];
  bodies.forEach(([subtype, body], index) => {
    const rows = subtype === 'html' ? htmlRows(body) : plainRows(body);
    const name = bodies.length === 1 ? 'document' : `part${index}`;
    parts.push(new Part(name, index, rows));
  });
  let omissions: Omission[] = [];
  if (skipped.size) {
    let count = 0;
    for (const c of skipped.values()) count += c;
    omissions = [new Omission(OMIT_MEDIA, count, skippedBytes, [], pySorted(skipped.keys()).join(', '))];
  }
  return nonempty(new Document('mhtml', parts, omissions), path, 'no text/html or text/plain part carried any text');
}

export function extractHtml(path: string): Document {
  const raw = readFileSync(pyPathStr(path));
  const markup = new TextDecoder('utf-8', { fatal: false, ignoreBOM: true }).decode(raw);
  const doc = new Document('html', [new Part('document', 0, htmlRows(markup))]);
  return nonempty(doc, path, 'its markup carried no text outside script and style');
}

function plainRows(text: string): string[] {
  return pySplitlines(text)
    .map((raw) => pyStrip(clean(raw)))
    .filter((line) => line);
}

function nonempty(doc: Document, path: string, why: string): Document {
  if (doc.parts.some((part) => part.rows.length)) return doc;
  throw new DocumentReadError(
    `cannot read ${pyPathName(path)}: it is a ${doc.kind} container but ${why}, so this reader has ` +
      'no text for it — it is not an empty document',
  );
}

// --------------------------------------------------------------- plain text, in no container

function textRows(text: string): string[] {
  if (!text) return [];
  if (text.endsWith('\n')) text = text.slice(0, -1);
  return text.split('\n').map((line) => (line.endsWith('\r') ? line.slice(0, -1) : line));
}

export function extractText(path: string): Document {
  const size = statSync(pyPathStr(path)).size;
  let raw = readPrefix(path, TEXT_MAX_BYTES + 1);
  const capped = raw.length > TEXT_MAX_BYTES;
  if (capped) raw = raw.subarray(0, TEXT_MAX_BYTES);
  const scan = utf8Scan(raw, !capped);
  let why = '';
  let text: string;
  if (scan.invalidAt >= 0) {
    text = decodeUtf8(raw.subarray(0, scan.invalidAt));
    why = `byte ${scan.invalidAt} begins a sequence that is not UTF-8 (${scan.reason})`;
  } else {
    text = decodeUtf8(raw.subarray(0, scan.end));
  }
  const control = BINARY_CONTROL.exec(text);
  if (control !== null) {
    const at = utf8Length(text.slice(0, control.index));
    why = `byte ${at} is control code 0x${control[0].charCodeAt(0).toString(16).padStart(2, '0')}, which is binary framing`;
    text = text.slice(0, control.index);
  }
  if (why || capped) text = text.slice(0, text.lastIndexOf('\n') + 1);
  const dropped = size - utf8Length(text);
  let omissions: Omission[] = [];
  if (dropped > 0) {
    const subject = why ? OMIT_UNREAD_TAIL : OMIT_SIZE_CAP;
    const what = why || `${size} bytes on disk; this reader reads ${TEXT_MAX_BYTES}`;
    omissions = [new Omission(subject, dropped, dropped, [], what)];
  }
  const doc = new Document('text', [new Part('document', 0, textRows(text))], omissions);
  if (doc.parts.some((part) => part.rows.some((row) => pyStrip(row)))) return doc;
  throw refuse(path, sniff(path), why || 'no line in it carries a character, so this reader has no text for it');
}

// ------------------------------------------------------- pdf, doc, rtf: identified, refused

/**
 * DELIBERATE DIVERGENCE (docs/porting.md). The reference reads a PDF through `pdfread`
 * and `.doc`/`.rtf` through `/usr/bin/textutil`; this half has neither, so the three
 * kinds are identified by `sniff` and refused by name. Same `_refuse` shape as every
 * other refusal — container, size on disk, the suffix disagreement — with a remedy that
 * says which server can read it.
 */
function nodeRefusal(kind: string): string {
  if (kind === 'pdf') return 'pdf is not readable by the Node server yet (the Python server reads it); see docs/porting.md';
  return `${kind} is read through ${TEXTUTIL} by the Python server and not by the Node server; see docs/porting.md`;
}

const EXTRACTORS: Readonly<Record<string, (path: string) => Document>> = {
  text: extractText,
  xlsx: extractXlsx,
  docx: extractDocx,
  mhtml: extractMhtml,
  html: extractHtml,
};

const NODE_REFUSED = new Set(['pdf', 'doc', 'rtf']);

/** Dispatch on what the file IS. Anything unreadable raises, naming the container. */
export function extract(path: string): Document {
  const container = sniff(path);
  const reader = lookup(EXTRACTORS, container.kind);
  if (reader !== undefined) return reader(path);
  if (NODE_REFUSED.has(container.kind)) throw refuse(path, container, nodeRefusal(container.kind));
  throw refuse(path, container, unsupportedRemedy());
}

/** Slice `limit` rows from `part` starting at `offset`, optionally under a byte ceiling. */
export function page(
  doc: Document,
  part: string | number = 0,
  offset = 0,
  limit: number = DEFAULT_ROW_LIMIT,
  maxBytes: number | null = null,
): Page {
  const target = doc.part(part);
  if (offset < 0 || limit < 1) {
    throw new DocumentReadError(`offset must be >= 0 and limit >= 1, got ${offset} and ${limit}`);
  }
  const rows: string[] = [];
  let used = 0;
  let dropped = 0;
  for (const row of target.rows.slice(offset, offset + limit)) {
    const bytes = utf8Length(row);
    const size = bytes + (rows.length ? 1 : 0);
    if (maxBytes !== null && rows.length && used + size > maxBytes) break;
    if (maxBytes !== null && !rows.length && size > maxBytes) {
      const encoded = Buffer.from(row, 'utf8').subarray(0, maxBytes);
      const scan = utf8Scan(encoded, false);
      const cut = decodeUtf8(encoded.subarray(0, scan.end));
      dropped = bytes - utf8Length(cut);
      rows.push(cut);
      used = utf8Length(cut);
      break;
    }
    rows.push(row);
    used += size;
  }
  const nxt = offset + rows.length;
  return new Page(target.name, offset, rows, target.rowCount, nxt < target.rowCount ? nxt : null, dropped);
}
