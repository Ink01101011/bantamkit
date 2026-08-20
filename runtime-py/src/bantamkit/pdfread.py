"""PDF text extraction with nothing but the standard library — and a reason for every refusal.

**Why this file exists at all.** J25-PREP measured this machine, 2026-08-20: `pypdf`, `PyPDF2`,
`fitz`, `pdfminer`, `pdfplumber`, `pdftotext`, `mutool` and `qpdf` are all **absent**, and
`/usr/bin/textutil`, which is present, does not do PDF. The runtime dependency list is fixed at
three packages, so a PDF reader here is written or there is none. `zlib` is standard library,
which is the whole of the compression problem; everything else a PDF needs — a tokenizer, an
object graph, a page tree, a content-stream interpreter and a character map — is arithmetic.

**The one rule this module is built around: a PDF string's bytes are not characters.** They are
indices into a font's encoding. For a composite font with `Identity-H` encoding they are glyph
indices *in that font's own subset*, and without a `/ToUnicode` map nothing in the file says
what character a glyph is. Decoding those bytes anyway produces text that reads as plausible
noise and that no caller can distinguish from content — the same failure class as
`/usr/bin/textutil` echoing Mac Roman at exit 0 (measured, J25-D1). So every character this
module emits carries a provenance, and **a character it cannot vouch for is never emitted**:

- from a `/ToUnicode` CMap in the file — the file's own statement of what the code means;
- from a simple font under `WinAnsiEncoding`, `MacRomanEncoding` or `StandardEncoding`;
- from a `/Differences` glyph name that resolves to a codepoint (`uniXXXX`, `AGL`).

Anything else is **counted, not rendered**: `PdfPage.unmapped` is how many characters were
dropped and `PdfPage.unmapped_fonts` names the fonts that produced them, so the caller can
disclose the gap instead of quoting noise. A page whose every character is unmapped yields no
rows and says why; `docread` turns that into a refusal when it is true of the whole file.

**What a "row" is here, and what it is not.** A PDF has no rows. It has glyphs at coordinates.
This module groups glyphs into rows by baseline (`_rows_from_runs`) and orders them by x, so
that `docread.page()` has a slice unit. That is a *slicing* decision, not a claim about
structure: a two-column page will interleave and a table will not come back as columns.

**Structure, without the xref.** The cross-reference table is an index, and on a real corpus it
is the part most likely to be stale, rewritten by an incremental update, or replaced by an xref
*stream* that itself needs the object graph to read. So this module does not read it: it scans
the file for `N G obj` and parses every object it finds, skipping the byte ranges that belong to
stream data (which is where a false `obj` match would come from), then expands every
`/Type/ObjStm` object stream — the PDF 1.5+ container the naive J25-PREP pass could not see
through, 13 of the user's 28 files. Later definitions of an object number win, which is what an
incremental update means. This costs one linear scan and buys immunity to a broken index.

Encryption is refused by name and never guessed at: not one file on the J25 corpus is encrypted
(`/Encrypt` absent from all 28, measured `6994f96`), so any decryption code here would be
unmeasured code, which this program does not ship.
"""

from __future__ import annotations

import base64
import re
import unicodedata
import zlib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["PdfError", "PdfPage", "PdfText", "read_pdf"]


class PdfError(Exception):
    """The PDF could not be read. The message names what was seen, never a bare traceback."""


# --------------------------------------------------------------------------- object model


class Name(str):
    """A PDF name (`/Type`). A `str` subclass so comparisons read naturally, distinct from a
    PDF *string*, which is `bytes` — the difference matters when a value may be either."""

    __slots__ = ()


@dataclass(frozen=True)
class Ref:
    num: int
    gen: int


@dataclass
class Stream:
    d: dict
    raw: bytes


class _Keyword(str):
    """A bare content-stream token: an operator, or `obj`/`endobj` in the object graph."""

    __slots__ = ()


# --------------------------------------------------------------------------------- tokenizer

_WS = b"\x00\t\n\x0c\r "
_DELIMS = b"()<>[]{}/%"
_ESCAPES = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}


def _skip_ws(data: bytes, i: int) -> int:
    n = len(data)
    while i < n:
        c = data[i]
        if c == 0x25:  # '%' comment runs to end of line
            while i < n and data[i] not in (0x0A, 0x0D):
                i += 1
        elif c in _WS:
            i += 1
        else:
            break
    return i


def _regular_run(data: bytes, i: int) -> tuple[bytes, int]:
    n, j = len(data), i
    while j < n and data[j] not in _WS and data[j] not in _DELIMS:
        j += 1
    return data[i:j], j


_HASH_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")


def _parse_name(data: bytes, i: int) -> tuple[Name, int]:
    token, j = _regular_run(data, i + 1)
    token = _HASH_ESCAPE.sub(lambda m: bytes([int(m.group(1), 16)]), token)
    return Name(token.decode("utf-8", errors="replace")), j


def _parse_literal_string(data: bytes, i: int) -> tuple[bytes, int]:
    i += 1
    depth, n = 1, len(data)
    out = bytearray()
    while i < n:
        c = data[i]
        if c == 0x5C:  # backslash
            i += 1
            if i >= n:
                break
            e = data[i]
            if e in _ESCAPES:
                out.append(_ESCAPES[e])
                i += 1
            elif 0x30 <= e <= 0x37:
                digits = bytearray()
                while i < n and len(digits) < 3 and 0x30 <= data[i] <= 0x37:
                    digits.append(data[i])
                    i += 1
                out.append(int(digits, 8) & 0xFF)
            elif e == 0x0A:
                i += 1
            elif e == 0x0D:
                i += 1
                if i < n and data[i] == 0x0A:
                    i += 1
            else:
                out.append(e)
                i += 1
        elif c == 0x28:
            depth += 1
            out.append(c)
            i += 1
        elif c == 0x29:
            depth -= 1
            i += 1
            if depth == 0:
                return bytes(out), i
            out.append(c)
        else:
            out.append(c)
            i += 1
    raise PdfError("a literal string runs off the end of the data (no closing parenthesis)")


_HEX_DIGITS = frozenset(b"0123456789abcdefABCDEF")


def _parse_hex_string(data: bytes, i: int) -> tuple[bytes, int]:
    i += 1
    digits = bytearray()
    n = len(data)
    while i < n and data[i] != 0x3E:  # '>'
        if data[i] in _HEX_DIGITS:
            digits.append(data[i])
        i += 1
    if len(digits) % 2:
        digits.append(0x30)
    return bytes.fromhex(digits.decode("ascii")), i + 1


_REF_TAIL = re.compile(rb"[\x00\t\r\n\f ]+(\d{1,5})[\x00\t\r\n\f ]+R(?![A-Za-z0-9])")


def _parse(data: bytes, i: int, depth: int = 0) -> tuple[object, int]:
    """One PDF object starting at `i`. Returns the value and the offset just past it."""
    if depth > 64:
        raise PdfError("PDF object nesting is deeper than 64 levels")
    i = _skip_ws(data, i)
    if i >= len(data):
        raise PdfError("the object data ends where an object was expected")
    c = data[i]
    if c == 0x2F:  # '/'
        return _parse_name(data, i)
    if c == 0x28:  # '('
        return _parse_literal_string(data, i)
    if c == 0x3C:  # '<'
        if data[i + 1 : i + 2] == b"<":
            return _parse_dict(data, i, depth)
        return _parse_hex_string(data, i)
    if c == 0x5B:  # '['
        i += 1
        out: list = []
        while True:
            i = _skip_ws(data, i)
            if i >= len(data):
                raise PdfError("an array runs off the end of the data")
            if data[i] == 0x5D:  # ']'
                return out, i + 1
            value, i = _parse(data, i, depth + 1)
            out.append(value)
    if c in (0x5D, 0x3E, 0x29, 0x7D):
        raise PdfError(f"unbalanced {chr(c)!r} in the object data")
    if c == 0x7B:  # '{' PostScript calculator body; not data this reader uses
        j = data.find(b"}", i)
        return [], (j + 1 if j != -1 else len(data))
    token, j = _regular_run(data, i)
    if not token:
        raise PdfError(f"byte {data[i]!r} starts no PDF object")
    if token == b"true":
        return True, j
    if token == b"false":
        return False, j
    if token == b"null":
        return None, j
    try:
        value: object = int(token)
    except ValueError:
        try:
            value = float(token.replace(b"--", b"-"))
        except ValueError:
            return _Keyword(token.decode("latin-1")), j
    else:
        if value >= 0:
            m = _REF_TAIL.match(data, j)
            if m:
                return Ref(int(token), int(m.group(1))), m.end()
    return value, j


def _parse_dict(data: bytes, i: int, depth: int = 0) -> tuple[dict, int]:
    i += 2
    out: dict = {}
    while True:
        i = _skip_ws(data, i)
        if i >= len(data):
            raise PdfError("a dictionary runs off the end of the data")
        if data[i : i + 2] == b">>":
            return out, i + 2
        if data[i] != 0x2F:
            # A malformed key. Skip one object rather than losing the whole dictionary.
            _, i = _parse(data, i, depth + 1)
            continue
        key, i = _parse_name(data, i)
        value, i = _parse(data, i, depth + 1)
        out[str(key)] = value


# ------------------------------------------------------------------------------ stream filters

# Filters whose output is an image, not text. Named so a refusal can say which one it met.
IMAGE_FILTERS = frozenset({"DCTDecode", "DCT", "JPXDecode", "JBIG2Decode", "CCITTFaxDecode", "CCF"})


class _ImageData(Exception):
    """The stream decodes to an image. Not an error — a fact the caller acts on."""

    def __init__(self, filter_name: str):
        super().__init__(filter_name)
        self.filter_name = filter_name


def _flate(data: bytes) -> bytes:
    """`zlib`, then the tolerances a real corpus needs: truncated, raw, and leading junk."""
    for attempt in (lambda: zlib.decompress(data), lambda: zlib.decompressobj().decompress(data)):
        try:
            return attempt()
        except zlib.error:
            pass
    for skip in (1, 2, 3):
        try:
            return zlib.decompressobj().decompress(data[skip:])
        except zlib.error:
            pass
    try:
        return zlib.decompressobj(-15).decompress(data)
    except zlib.error:
        raise PdfError("a FlateDecode stream is not decompressible by zlib") from None


def _ascii85(data: bytes) -> bytes:
    body = b"".join(data.split())
    if body.startswith(b"<~"):
        body = body[2:]
    end = body.find(b"~>")
    if end != -1:
        body = body[:end]
    try:
        return base64.a85decode(body)
    except ValueError:
        raise PdfError("an ASCII85Decode stream is not valid ASCII85") from None


def _asciihex(data: bytes) -> bytes:
    end = data.find(b">")
    body = data[:end] if end != -1 else data
    digits = bytes(ch for ch in body if ch in _HEX_DIGITS)
    if len(digits) % 2:
        digits += b"0"
    return bytes.fromhex(digits.decode("ascii"))


def _runlength(data: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        length = data[i]
        i += 1
        if length == 128:
            break
        if length < 128:
            out += data[i : i + length + 1]
            i += length + 1
        else:
            if i >= n:
                break
            out += bytes([data[i]]) * (257 - length)
            i += 1
    return bytes(out)


def _lzw(data: bytes, early: int = 1) -> bytes:
    out = bytearray()
    table = [bytes([k]) for k in range(256)] + [b"", b""]
    bits, buf, nbits = 9, 0, 0
    previous: bytes | None = None
    for byte in data:
        buf = (buf << 8) | byte
        nbits += 8
        while nbits >= bits:
            code = (buf >> (nbits - bits)) & ((1 << bits) - 1)
            nbits -= bits
            if code == 256:
                table = [bytes([k]) for k in range(256)] + [b"", b""]
                bits, previous = 9, None
                continue
            if code == 257:
                return bytes(out)
            if previous is None:
                if code >= len(table):
                    raise PdfError("an LZWDecode stream starts with an undefined code")
                entry = table[code]
            elif code < len(table):
                entry = table[code]
                table.append(previous + entry[:1])
            else:
                entry = previous + previous[:1]
                table.append(entry)
            out += entry
            previous = entry
            if len(table) + early >= (1 << bits) and bits < 12:
                bits += 1
    return bytes(out)


def _png_predictor(data: bytes, colors: int, bpc: int, columns: int) -> bytes:
    bpp = max(1, (colors * bpc + 7) // 8)
    rowlen = (columns * colors * bpc + 7) // 8
    out = bytearray()
    previous = bytearray(rowlen)
    i, n = 0, len(data)
    while i + 1 <= n - 1:
        tag = data[i]
        row = bytearray(data[i + 1 : i + 1 + rowlen])
        if len(row) < rowlen:
            row += bytes(rowlen - len(row))
        i += 1 + rowlen
        if tag == 1:
            for k in range(bpp, rowlen):
                row[k] = (row[k] + row[k - bpp]) & 0xFF
        elif tag == 2:
            for k in range(rowlen):
                row[k] = (row[k] + previous[k]) & 0xFF
        elif tag == 3:
            for k in range(rowlen):
                left = row[k - bpp] if k >= bpp else 0
                row[k] = (row[k] + ((left + previous[k]) >> 1)) & 0xFF
        elif tag == 4:
            for k in range(rowlen):
                a = row[k - bpp] if k >= bpp else 0
                b = previous[k]
                c = previous[k - bpp] if k >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                best = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[k] = (row[k] + best) & 0xFF
        out += row
        previous = row
    return bytes(out)


def _tiff_predictor(data: bytes, colors: int, bpc: int, columns: int) -> bytes:
    if bpc != 8:
        return data
    rowlen = columns * colors
    out = bytearray(data)
    for start in range(0, len(out) - rowlen + 1, rowlen):
        for k in range(colors, rowlen):
            out[start + k] = (out[start + k] + out[start + k - colors]) & 0xFF
    return bytes(out)


# --------------------------------------------------------------------------- the object graph

_OBJ_RE = re.compile(rb"(?<![0-9])(\d{1,10})[\x00\t\r\n\f ]+(\d{1,5})[\x00\t\r\n\f ]+obj\b")
_TRAILER_RE = re.compile(rb"trailer[\x00\t\r\n\f ]*(?=<<)")
_HEADER_RE = re.compile(rb"%PDF-(\d+\.\d+)")


class PdfDocument:
    """Every object in the file, found by scanning rather than by trusting the xref index."""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.objects: dict[int, object] = {}
        self._decoded: dict[int, bytes] = {}
        self._scan()
        self._expand_object_streams()

    # -- loading ---------------------------------------------------------------------------

    def _scan(self) -> None:
        raw = self.raw
        guard = 0
        for m in _OBJ_RE.finditer(raw):
            if m.start() < guard:
                continue  # inside a stream's data: a false `obj` match, not an object
            num = int(m.group(1))
            try:
                value, j = _parse(raw, m.end())
            except PdfError:
                continue
            head = _skip_ws(raw, j)
            if isinstance(value, dict) and raw[head : head + 6] == b"stream":
                k = head + 6
                if raw[k : k + 2] == b"\r\n":
                    k += 2
                elif raw[k : k + 1] in (b"\n", b"\r"):
                    k += 1
                end = self._stream_end(value, k)
                value = Stream(value, raw[k:end])
                after = raw.find(b"endstream", end)
                guard = (after + 9) if after != -1 else end
            self.objects[num] = value

    def _stream_end(self, d: dict, start: int) -> int:
        """Where the stream data stops. `/Length` when it is honest, `endstream` when it is not.

        A `/Length` that is an indirect reference cannot be resolved yet — the object it points
        at may not be scanned — so the search is the fallback, and it is also the fallback for a
        `/Length` that simply lies, which real generators do.
        """
        raw = self.raw
        length = d.get("Length")
        if isinstance(length, int) and 0 <= length <= len(raw) - start:
            candidate = start + length
            if re.match(rb"[\x00\t\r\n\f ]*endstream", raw[candidate : candidate + 20]):
                return candidate
        found = raw.find(b"endstream", start)
        end = found if found != -1 else len(raw)
        while end > start and raw[end - 1] in (0x0A, 0x0D):
            end -= 1
        return end

    def _expand_object_streams(self) -> None:
        for num, obj in list(self.objects.items()):
            if not (isinstance(obj, Stream) and obj.d.get("Type") == "ObjStm"):
                continue
            try:
                data = self.stream_data(num, obj)
            except (PdfError, _ImageData):
                continue
            count = self.resolve(obj.d.get("N")) or 0
            first = self.resolve(obj.d.get("First")) or 0
            if not isinstance(count, int) or not isinstance(first, int):
                continue
            fields = data[:first].split()
            for k in range(0, min(len(fields) - 1, 2 * count), 2):
                try:
                    inner, offset = int(fields[k]), int(fields[k + 1])
                except ValueError:
                    continue
                if inner in self.objects:
                    continue  # a direct definition is the newer one; it wins
                try:
                    value, _ = _parse(data, first + offset)
                except PdfError:
                    continue
                self.objects[inner] = value

    # -- access ----------------------------------------------------------------------------

    def resolve(self, obj: object, depth: int = 0) -> object:
        while isinstance(obj, Ref) and depth < 32:
            obj = self.objects.get(obj.num)
            depth += 1
        return obj

    def as_dict(self, obj: object) -> dict | None:
        obj = self.resolve(obj)
        if isinstance(obj, Stream):
            return obj.d
        return obj if isinstance(obj, dict) else None

    def stream_data(self, key: object, stream: Stream) -> bytes:
        """Decoded bytes of a stream. Raises `_ImageData` when the filter chain is an image."""
        cache_key = key if isinstance(key, int) else None
        if cache_key is not None and cache_key in self._decoded:
            return self._decoded[cache_key]
        data = stream.raw
        filters = self.resolve(stream.d.get("Filter", stream.d.get("F")))
        if filters is None:
            filters = []
        elif not isinstance(filters, list):
            filters = [filters]
        parms = self.resolve(stream.d.get("DecodeParms", stream.d.get("DP")))
        if not isinstance(parms, list):
            parms = [parms] * len(filters)
        for index, raw_filter in enumerate(filters):
            name = str(self.resolve(raw_filter) or "")
            if name in IMAGE_FILTERS:
                raise _ImageData(name)
            parm = self.as_dict(parms[index]) if index < len(parms) else None
            if name in ("FlateDecode", "Fl"):
                data = _flate(data)
            elif name in ("LZWDecode", "LZW"):
                early = self.resolve((parm or {}).get("EarlyChange", 1))
                data = _lzw(data, 1 if early is None else int(early))
            elif name in ("ASCII85Decode", "A85"):
                data = _ascii85(data)
            elif name in ("ASCIIHexDecode", "AHx"):
                data = _asciihex(data)
            elif name in ("RunLengthDecode", "RL"):
                data = _runlength(data)
            elif name in ("Crypt", ""):
                continue
            else:
                raise PdfError(f"stream filter /{name} is one this reader does not implement")
            if parm:
                predictor = self.resolve(parm.get("Predictor", 1)) or 1
                if isinstance(predictor, int) and predictor > 1:
                    colors = int(self.resolve(parm.get("Colors", 1)) or 1)
                    bpc = int(self.resolve(parm.get("BitsPerComponent", 8)) or 8)
                    columns = int(self.resolve(parm.get("Columns", 1)) or 1)
                    if predictor == 2:
                        data = _tiff_predictor(data, colors, bpc, columns)
                    else:
                        data = _png_predictor(data, colors, bpc, columns)
        if cache_key is not None:
            self._decoded[cache_key] = data
        return data

    def data_of(self, obj: object) -> bytes:
        key = obj.num if isinstance(obj, Ref) else None
        resolved = self.resolve(obj)
        if not isinstance(resolved, Stream):
            raise PdfError("expected a stream and found none")
        return self.stream_data(key, resolved)

    # -- structure -------------------------------------------------------------------------

    def trailers(self) -> list[dict]:
        out = []
        for m in _TRAILER_RE.finditer(self.raw):
            try:
                d, _ = _parse_dict(self.raw, m.end())
            except PdfError:
                continue
            out.append(d)
        for obj in self.objects.values():
            if isinstance(obj, Stream) and obj.d.get("Type") == "XRef":
                out.append(obj.d)
        return out

    def encryption(self) -> dict | None:
        for trailer in self.trailers():
            if "Encrypt" in trailer:
                return self.as_dict(trailer["Encrypt"]) or {}
        return None

    def catalog(self) -> dict | None:
        for trailer in reversed(self.trailers()):
            root = self.as_dict(trailer.get("Root"))
            if root is not None and "Pages" in root:
                return root
        for num in sorted(self.objects, reverse=True):
            d = self.as_dict(self.objects[num])
            if isinstance(d, dict) and d.get("Type") == "Catalog":
                return d
        return None

    _INHERITED = ("Resources", "MediaBox", "CropBox", "Rotate")

    def pages(self) -> list[tuple[dict, dict]]:
        """Every page, in document order, paired with its inherited attributes."""
        out: list[tuple[dict, dict]] = []
        catalog = self.catalog()
        if catalog is not None:
            self._walk(catalog.get("Pages"), {}, out, set(), 0)
        if out:
            return out
        # No usable page tree. Every `/Type/Page` object, in object-number order: not the
        # document's order, and said so by the caller rather than passed off as it.
        for num in sorted(self.objects):
            d = self.as_dict(self.objects[num])
            if isinstance(d, dict) and d.get("Type") == "Page":
                out.append((d, dict(d)))
        return out

    def _walk(
        self, node: object, inherited: dict, out: list, seen: set, depth: int
    ) -> None:
        if depth > 64 or len(out) > 20000:
            return
        if isinstance(node, Ref):
            if (node.num, node.gen) in seen:
                return
            seen.add((node.num, node.gen))
        d = self.as_dict(node)
        if d is None:
            return
        inherited = {**inherited, **{k: d[k] for k in self._INHERITED if k in d}}
        kids = self.resolve(d.get("Kids"))
        if d.get("Type") == "Page" or (not isinstance(kids, list) and "Contents" in d):
            out.append((d, inherited))
            return
        if isinstance(kids, list):
            for kid in kids:
                self._walk(kid, inherited, out, seen, depth + 1)


# ------------------------------------------------------------------- characters, and vouching

# The Adobe Glyph List, restricted to what a Latin document actually uses. A glyph name this
# table does not hold and that is not a `uniXXXX` form is NOT guessed at — it is unmapped.
_AGL = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$",
    "percent": "%", "ampersand": "&", "quotesingle": "'", "quoteright": "’",
    "quoteleft": "‘", "parenleft": "(", "parenright": ")", "asterisk": "*",
    "plus": "+", "comma": ",", "hyphen": "-", "period": ".", "slash": "/", "zero": "0",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "colon": ":", "semicolon": ";", "less": "<",
    "equal": "=", "greater": ">", "question": "?", "at": "@", "bracketleft": "[",
    "backslash": "\\", "bracketright": "]", "asciicircum": "^", "underscore": "_",
    "grave": "`", "braceleft": "{", "bar": "|", "braceright": "}", "asciitilde": "~",
    "quotedblleft": "“", "quotedblright": "”", "endash": "–",
    "emdash": "—", "bullet": "•", "ellipsis": "…", "fi": "fi", "fl": "fl",
    "ff": "ff", "ffi": "ffi", "ffl": "ffl", "dagger": "†", "daggerdbl": "‡",
    "trademark": "™", "copyright": "©", "registered": "®",
    "degree": "°", "plusminus": "±", "middot": "·", "sterling": "£",
    "yen": "¥", "euro": "€", "cent": "¢", "section": "§",
    "paragraph": "¶", "guillemotleft": "«", "guillemotright": "»",
    "quotesinglbase": "‚", "quotedblbase": "„", "perthousand": "‰",
    "nbspace": " ", "minus": "−", "divide": "÷", "multiply": "×",
}
for _letter in "abcdefghijklmnopqrstuvwxyz":
    _AGL[_letter] = _letter
    _AGL[_letter.upper()] = _letter.upper()

_UNI_NAME = re.compile(r"^uni([0-9A-Fa-f]{4,6})$")
_U_NAME = re.compile(r"^u([0-9A-Fa-f]{4,6})$")


def glyph_to_unicode(name: str) -> str | None:
    """A `/Differences` glyph name as a character, or None when nothing in the file says.

    `g23`, `index7`, `cid100` and a subset font's private names all return None **on purpose**:
    the name is an index into a font, and the file has not said what character it draws.
    """
    if name in _AGL:
        return _AGL[name]
    m = _UNI_NAME.match(name) or _U_NAME.match(name)
    if m:
        try:
            return chr(int(m.group(1), 16))
        except (ValueError, OverflowError):
            return None
    base = name.split(".")[0]
    if base != name and base in _AGL:
        return _AGL[base]
    return None


def _vouchable(text: str) -> bool:
    """Is this character one a caller can be handed? Control, private-use and unassigned are
    exactly the shapes glyph-index noise takes, so they are dropped even when a map produced
    them."""
    for ch in text:
        if ch in "\t\n\r ":
            continue
        if ch == "�":
            return False
        if unicodedata.category(ch) in ("Cc", "Cf", "Cn", "Co", "Cs"):
            return False
    return True


_STANDARD_CODECS = {
    "WinAnsiEncoding": "cp1252",
    "MacRomanEncoding": "mac_roman",
    "PDFDocEncoding": "cp1252",
}


def _base_encoding_map(name: str) -> dict[int, str]:
    """Codes 0-255 under a named base encoding, ASCII-only when the file names none.

    A font with no `/Encoding` uses its own built-in one, which the file does not state. ASCII
    is where every Latin text encoding agrees, so ASCII is trusted and the high half is not.
    """
    out: dict[int, str] = {}
    codec = _STANDARD_CODECS.get(name)
    if codec:
        for code in range(32, 256):
            try:
                ch = bytes([code]).decode(codec)
            except UnicodeDecodeError:
                continue
            if _vouchable(ch):
                out[code] = ch
        return out
    for code in range(32, 127):
        out[code] = chr(code)
    return out


def parse_cmap(data: bytes) -> tuple[dict[int, str], set[int]]:
    """A `/ToUnicode` CMap as code -> text, plus the code byte-lengths it declares."""
    mapping: dict[int, str] = {}
    lengths: set[int] = set()

    def utf16(hexbytes: bytes) -> str:
        raw = hexbytes.decode("ascii")
        if len(raw) % 2:
            raw += "0"
        try:
            return bytes.fromhex(raw).decode("utf-16-be", errors="replace")
        except ValueError:
            return ""

    for block in re.findall(rb"begincodespacerange(.*?)endcodespacerange", data, re.S):
        for src, _dst in re.findall(rb"<([0-9A-Fa-f]*)>\s*<([0-9A-Fa-f]*)>", block):
            if src:
                lengths.add(max(1, len(src) // 2))
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            lengths.add(max(1, len(src) // 2))
            mapping[int(src, 16)] = utf16(dst)
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        pattern = rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(?:<([0-9A-Fa-f]*)>|\[(.*?)\])"
        for m in re.finditer(pattern, block, re.S):
            lo, hi = int(m.group(1), 16), int(m.group(2), 16)
            lengths.add(max(1, len(m.group(1)) // 2))
            if hi < lo or hi - lo > 65535:
                continue
            if m.group(3) is not None:
                base = m.group(3)
                prefix, tail = base[:-4], base[-4:] if len(base) >= 4 else base
                try:
                    start = int(tail, 16) if tail else 0
                except ValueError:
                    continue
                for k in range(hi - lo + 1):
                    mapping[lo + k] = utf16(prefix + f"{start + k:04X}".encode())
            else:
                for k, item in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", m.group(4) or b"")):
                    if lo + k <= hi:
                        mapping[lo + k] = utf16(item)
    return mapping, lengths


@dataclass
class _Font:
    """One font resource, and everything needed to turn its codes into vouched characters."""

    name: str
    basefont: str
    two_byte: bool
    to_unicode: dict[int, str]
    encoding: dict[int, str]
    widths: dict[int, float]
    default_width: float

    def codes(self, raw: bytes) -> list[int]:
        if self.two_byte:
            if len(raw) % 2:
                raw += b"\x00"
            return [(raw[i] << 8) | raw[i + 1] for i in range(0, len(raw), 2)]
        return list(raw)

    def char(self, code: int, permissive: bool = False) -> str | None:
        """The character this code means, or None when nothing in the file says.

        `permissive=True` is the audit path and only the audit path: it decodes an unmapped
        code as `chr(code)`, which is precisely the assumption that turns a subset font's
        glyph indices into mojibake. `read_pdf(vouch=False)` is its only caller.
        """
        text = self.to_unicode.get(code)
        if text is None:
            text = self.encoding.get(code)
        if text is None or not _vouchable(text):
            if not permissive:
                return None
            try:
                return text if text is not None else chr(code)
            except ValueError:
                return "\ufffd"
        return text

    def width(self, code: int) -> float:
        return self.widths.get(code, self.default_width)


def _build_font(doc: PdfDocument, name: str, node: object) -> _Font:
    d = doc.as_dict(node) or {}
    subtype = str(doc.resolve(d.get("Subtype")) or "")
    basefont = str(doc.resolve(d.get("BaseFont")) or "?")
    to_unicode: dict[int, str] = {}
    lengths: set[int] = set()
    tu = doc.resolve(d.get("ToUnicode"))
    if isinstance(tu, Stream):
        try:
            to_unicode, lengths = parse_cmap(doc.data_of(d.get("ToUnicode")))
        except (PdfError, _ImageData):
            to_unicode, lengths = {}, set()
    if subtype == "Type0":
        encoding_name = str(doc.resolve(d.get("Encoding")) or "")
        # Composite-font codes are two bytes unless the ToUnicode CMap declares otherwise:
        # Identity-H, and every predefined CJK CMap this corpus carries, are two-byte.
        two_byte = lengths != {1}
        del encoding_name
        widths, default_width = _cid_widths(doc, d)
        return _Font(
            name=name,
            basefont=basefont,
            two_byte=two_byte,
            to_unicode=to_unicode,
            encoding={},
            widths=widths,
            # A composite font says nothing about characters without a ToUnicode map: its
            # codes are CIDs, and for Identity-H they are glyph indices in a subset font.
            # `encoding` is therefore left EMPTY, which is what makes `char()` return None
            # for every code — the trust decision is that emptiness and nothing else.
            default_width=default_width,
        )
    encoding_obj = doc.resolve(d.get("Encoding"))
    base_name, differences = "", []
    if isinstance(encoding_obj, Name):
        base_name = str(encoding_obj)
    elif isinstance(encoding_obj, dict):
        base_name = str(doc.resolve(encoding_obj.get("BaseEncoding")) or "")
        differences = doc.resolve(encoding_obj.get("Differences")) or []
    encoding = _base_encoding_map(base_name)
    code = 0
    for item in differences if isinstance(differences, list) else []:
        item = doc.resolve(item)
        if isinstance(item, (int, float)):
            code = int(item)
        elif isinstance(item, Name):
            ch = glyph_to_unicode(str(item))
            if ch is None:
                encoding.pop(code, None)  # the file named a glyph, not a character
            else:
                encoding[code] = ch
            code += 1
    widths, default_width = _simple_widths(doc, d)
    return _Font(
        name=name,
        basefont=basefont,
        two_byte=False,
        to_unicode=to_unicode,
        encoding=encoding,
        widths=widths,
        default_width=default_width,
    )


def _simple_widths(doc: PdfDocument, d: dict) -> tuple[dict[int, float], float]:
    widths: dict[int, float] = {}
    first = doc.resolve(d.get("FirstChar"))
    table = doc.resolve(d.get("Widths"))
    if isinstance(first, int) and isinstance(table, list):
        for k, w in enumerate(table):
            w = doc.resolve(w)
            if isinstance(w, (int, float)):
                widths[first + k] = float(w)
    descriptor = doc.as_dict(d.get("FontDescriptor")) or {}
    missing = doc.resolve(descriptor.get("MissingWidth", 500))
    return widths, float(missing) if isinstance(missing, (int, float)) else 500.0


def _cid_widths(doc: PdfDocument, d: dict) -> tuple[dict[int, float], float]:
    descendants = doc.resolve(d.get("DescendantFonts")) or []
    child = doc.as_dict(descendants[0]) if isinstance(descendants, list) and descendants else {}
    child = child or {}
    default = doc.resolve(child.get("DW", 1000))
    widths: dict[int, float] = {}
    table = doc.resolve(child.get("W")) or []
    index = 0
    while isinstance(table, list) and index < len(table):
        start = doc.resolve(table[index])
        following = doc.resolve(table[index + 1]) if index + 1 < len(table) else None
        if isinstance(following, list):
            for k, w in enumerate(following):
                w = doc.resolve(w)
                if isinstance(start, int) and isinstance(w, (int, float)):
                    widths[start + k] = float(w)
            index += 2
        elif isinstance(following, int) and index + 2 < len(table):
            w = doc.resolve(table[index + 2])
            if isinstance(start, int) and isinstance(w, (int, float)) and following - start < 65536:
                for cid in range(start, following + 1):
                    widths[cid] = float(w)
            index += 3
        else:
            break
    return widths, float(default) if isinstance(default, (int, float)) else 1000.0


# ------------------------------------------------------------- the content-stream interpreter


def _mul(m: tuple, n: tuple) -> tuple:
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass
class _Run:
    y: float
    x: float
    end_x: float
    size: float
    text: str


@dataclass
class _PageState:
    runs: list[_Run] = field(default_factory=list)
    show_ops: int = 0
    vouched: int = 0
    unmapped: int = 0
    unmapped_fonts: set = field(default_factory=set)
    images: int = 0
    image_bytes: int = 0
    image_kinds: set = field(default_factory=set)
    permissive: bool = False


_INLINE_IMAGE = re.compile(rb"\bID[\x00\t\r\n\f ]")


def _tokenize_content(data: bytes) -> list:
    """Content-stream tokens. Inline images (`BI … ID … EI`) are skipped as the binary they are."""
    out: list = []
    i, n = 0, len(data)
    while True:
        i = _skip_ws(data, i)
        if i >= n:
            return out
        try:
            value, j = _parse(data, i)
        except PdfError:
            # A byte that starts no object. Step over it — and STEPPING is the point: a
            # `continue` that left `i` where it was hung this reader forever on a real file
            # (`Defect_Apr 2026 RELEASE_SIT_AP1827-38933.pdf`, measured 2026-08-20).
            i += 1
            continue
        if j <= i:
            j = i + 1
        if isinstance(value, _Keyword) and value == "BI":
            m = _INLINE_IMAGE.search(data, j)
            end = data.find(b"EI", m.end() if m else j)
            out.append(_Keyword("INLINE_IMAGE"))
            i = (end + 2) if end != -1 else n
            continue
        out.append(value)
        i = j


def _run_content(
    doc: PdfDocument,
    data: bytes,
    resources: dict,
    state: _PageState,
    ctm: tuple,
    depth: int,
    seen: set,
) -> None:
    fonts: dict[str, _Font] = {}
    font_dict = doc.as_dict(resources.get("Font")) or {}
    xobjects = doc.as_dict(resources.get("XObject")) or {}

    def font_for(key: str) -> _Font:
        if key not in fonts:
            if key in font_dict:
                fonts[key] = _build_font(doc, key, font_dict[key])
            else:
                # A font the page never declared. Its codes mean nothing this file states.
                fonts[key] = _Font(key, "?", False, {}, {}, {}, 500.0)
        return fonts[key]

    stack: list[tuple] = []
    tm = tlm = _IDENTITY
    font: _Font | None = None
    fsize = 0.0
    tc = tw = 0.0
    th = 1.0
    tl = 0.0
    rise = 0.0
    operands: list = []

    def show(raw: bytes) -> None:
        nonlocal tm
        if font is None:
            return
        state.show_ops += 1
        placement = _mul(tm, ctm)
        trm = _mul((fsize * th, 0.0, 0.0, fsize, 0.0, rise), placement)
        scale = abs(trm[3]) or abs(fsize) or 1.0
        # The displacement below is computed in TEXT space; the run's extent on the page is
        # that displacement through the text and current transformation matrices. Using the
        # CTM alone under-measures every run a `Tm` scales, which shows up as spurious spaces
        # inside words ("Cus t omer") when the gap rule below compares extents.
        stretch = abs(placement[0]) or 1.0
        pieces: list[str] = []
        advance = 0.0
        for code in font.codes(raw):
            ch = font.char(code, state.permissive)
            if ch is None:
                state.unmapped += 1
                state.unmapped_fonts.add(font.basefont or font.name)
            else:
                state.vouched += 1
                pieces.append(ch)
            step = font.width(code) / 1000.0 * fsize + tc
            if code == 32 and not font.two_byte:
                step += tw
            advance += step * th
        text = "".join(pieces)
        if text.strip():
            x0, y0 = trm[4], trm[5]
            state.runs.append(
                _Run(y=y0, x=x0, end_x=x0 + advance * stretch, size=scale, text=text)
            )
        tm = _mul((1.0, 0.0, 0.0, 1.0, advance, 0.0), tm)

    def adjust(amount: float) -> None:
        nonlocal tm
        tm = _mul((1.0, 0.0, 0.0, 1.0, -amount / 1000.0 * fsize * th, 0.0), tm)

    def numbers(count: int) -> list[float]:
        got = [v for v in operands[-count:] if isinstance(v, (int, float))]
        return [float(v) for v in got] if len(got) == count else []

    for token in _tokenize_content(data):
        if not isinstance(token, _Keyword):
            operands.append(token)
            if len(operands) > 64:
                del operands[:-32]
            continue
        op = str(token)
        if op == "q":
            stack.append(ctm)
        elif op == "Q":
            if stack:
                ctm = stack.pop()
        elif op == "cm":
            got = numbers(6)
            if got:
                ctm = _mul(tuple(got), ctm)
        elif op == "BT":
            tm = tlm = _IDENTITY
        elif op == "ET":
            tm = tlm = _IDENTITY
        elif op == "Tf":
            got = [v for v in operands if isinstance(v, Name)]
            size = numbers(1)
            if got:
                font = font_for(str(got[-1]))
            if size:
                fsize = size[0]
        elif op == "Td":
            got = numbers(2)
            if got:
                tlm = _mul((1.0, 0.0, 0.0, 1.0, got[0], got[1]), tlm)
                tm = tlm
        elif op == "TD":
            got = numbers(2)
            if got:
                tl = -got[1]
                tlm = _mul((1.0, 0.0, 0.0, 1.0, got[0], got[1]), tlm)
                tm = tlm
        elif op == "Tm":
            got = numbers(6)
            if got:
                tm = tlm = tuple(got)
        elif op == "T*":
            tlm = _mul((1.0, 0.0, 0.0, 1.0, 0.0, -tl), tlm)
            tm = tlm
        elif op == "TL":
            got = numbers(1)
            if got:
                tl = got[0]
        elif op == "Tc":
            got = numbers(1)
            if got:
                tc = got[0]
        elif op == "Tw":
            got = numbers(1)
            if got:
                tw = got[0]
        elif op == "Tz":
            got = numbers(1)
            if got:
                th = got[0] / 100.0
        elif op == "Ts":
            got = numbers(1)
            if got:
                rise = got[0]
        elif op == "Tj":
            if operands and isinstance(operands[-1], bytes):
                show(operands[-1])
        elif op == "'":
            tlm = _mul((1.0, 0.0, 0.0, 1.0, 0.0, -tl), tlm)
            tm = tlm
            if operands and isinstance(operands[-1], bytes):
                show(operands[-1])
        elif op == '"':
            got = [v for v in operands[-3:-1] if isinstance(v, (int, float))]
            if len(got) == 2:
                tw, tc = float(got[0]), float(got[1])
            tlm = _mul((1.0, 0.0, 0.0, 1.0, 0.0, -tl), tlm)
            tm = tlm
            if operands and isinstance(operands[-1], bytes):
                show(operands[-1])
        elif op == "TJ":
            array = operands[-1] if operands and isinstance(operands[-1], list) else []
            for item in array:
                if isinstance(item, bytes):
                    show(item)
                elif isinstance(item, (int, float)):
                    adjust(float(item))
        elif op == "INLINE_IMAGE":
            state.images += 1
            state.image_kinds.add("inline")
        elif op == "Do":
            got = [v for v in operands if isinstance(v, Name)]
            if got:
                _do_xobject(doc, str(got[-1]), xobjects, state, ctm, depth, seen)
        operands = []


def _do_xobject(
    doc: PdfDocument, key: str, xobjects: dict, state: _PageState, ctm: tuple, depth: int, seen: set
) -> None:
    node = xobjects.get(key)
    resolved = doc.resolve(node)
    if not isinstance(resolved, Stream):
        return
    subtype = str(doc.resolve(resolved.d.get("Subtype")) or "")
    if subtype == "Image":
        state.images += 1
        size = doc.resolve(resolved.d.get("Length"))
        state.image_bytes += int(size) if isinstance(size, int) else len(resolved.raw)
        filters = doc.resolve(resolved.d.get("Filter"))
        for name in filters if isinstance(filters, list) else [filters]:
            state.image_kinds.add(str(doc.resolve(name) or "raw"))
        return
    if subtype != "Form" or depth >= 8:
        return
    marker = (node.num, node.gen) if isinstance(node, Ref) else id(resolved)
    if marker in seen:
        return
    seen.add(marker)
    try:
        data = doc.data_of(node)
    except _ImageData as image:
        state.images += 1
        state.image_kinds.add(image.filter_name)
        return
    except PdfError:
        return
    inner = doc.as_dict(resolved.d.get("Resources")) or {}
    matrix = doc.resolve(resolved.d.get("Matrix"))
    local = ctm
    if isinstance(matrix, list) and len(matrix) == 6:
        try:
            local = _mul(tuple(float(doc.resolve(v)) for v in matrix), ctm)
        except (TypeError, ValueError):
            local = ctm
    _run_content(doc, data, inner, state, local, depth + 1, seen)
    seen.discard(marker)


def _rows_from_runs(runs: list[_Run], rotate: int) -> tuple[str, ...]:
    """Glyph runs, grouped into rows by baseline and ordered by x. A slicing unit, not layout."""
    if not runs:
        return ()
    if rotate % 360 in (90, 270):
        runs = [_Run(y=r.x, x=-r.y, end_x=-r.y + (r.end_x - r.x), size=r.size, text=r.text)
                for r in runs]
    runs.sort(key=lambda r: (-r.y, r.x))
    rows: list[list[_Run]] = []
    current: list[_Run] = []
    baseline = 0.0
    for run in runs:
        tolerance = max(1.5, 0.35 * run.size)
        if current and abs(run.y - baseline) <= tolerance:
            current.append(run)
        else:
            if current:
                rows.append(current)
            current = [run]
            baseline = run.y
    if current:
        rows.append(current)
    out: list[str] = []
    for row in rows:
        row.sort(key=lambda r: r.x)
        pieces: list[str] = []
        previous_end: float | None = None
        for run in row:
            if previous_end is not None and run.x - previous_end > 0.22 * max(run.size, 1.0):
                pieces.append(" ")
            pieces.append(run.text)
            previous_end = max(run.end_x, run.x)
        line = "".join(pieces).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
        if line:
            out.append(line)
    return tuple(out)


# ------------------------------------------------------------------------------- the API


@dataclass(frozen=True)
class PdfPage:
    """One page: its rows, and the counts behind everything the rows do not carry."""

    number: int
    rows: tuple[str, ...]
    show_ops: int
    vouched: int
    unmapped: int
    unmapped_fonts: tuple[str, ...]
    images: int
    image_bytes: int
    image_kinds: tuple[str, ...]

    @property
    def characters(self) -> int:
        return sum(len(row.strip()) for row in self.rows)


@dataclass(frozen=True)
class PdfText:
    version: str
    pages: tuple[PdfPage, ...]

    @property
    def vouched(self) -> int:
        return sum(page.vouched for page in self.pages)

    @property
    def unmapped(self) -> int:
        return sum(page.unmapped for page in self.pages)

    @property
    def show_ops(self) -> int:
        return sum(page.show_ops for page in self.pages)

    @property
    def images(self) -> int:
        return sum(page.images for page in self.pages)

    @property
    def unmapped_fonts(self) -> tuple[str, ...]:
        out: set[str] = set()
        for page in self.pages:
            out.update(page.unmapped_fonts)
        return tuple(sorted(out))


def read_pdf(path: str | Path, vouch: bool = True) -> PdfText:
    """Every page of `path`, as rows this reader can vouch for.

    `vouch=False` renders the characters it CANNOT vouch for as well, mapping an unmapped code
    to the character its raw value would suggest. That output is mojibake by construction and
    is never what `docread` asks for — it exists so the audit in
    `.shiftwork/probes/J25-D3-pdf-coverage.py` can *demonstrate* what the guard is suppressing
    rather than assert it. Nothing in the runtime calls it with `vouch=False`.
    """
    path = Path(path)
    raw = path.read_bytes()
    header = _HEADER_RE.match(raw[:1024]) or _HEADER_RE.search(raw[:1024])
    if header is None:
        raise PdfError("it does not begin with a %PDF- header, so it is not a PDF")
    version = header.group(1).decode("ascii")
    doc = PdfDocument(raw)
    encryption = doc.encryption()
    if encryption is not None:
        handler = encryption.get("Filter", "?")
        raise PdfError(
            f"it is an ENCRYPTED PDF (/Encrypt, security handler /{handler}) and this reader "
            "decrypts nothing — no file on the corpus it was measured against was encrypted, "
            "so decryption here would be unmeasured code"
        )
    page_nodes = doc.pages()
    if not page_nodes:
        raise PdfError(
            f"its structure yielded no page at all: {len(doc.objects)} objects were parsed and "
            "none of them is a page tree or a /Type/Page"
        )
    pages: list[PdfPage] = []
    for index, (node, inherited) in enumerate(page_nodes):
        state = _PageState()
        resources = doc.as_dict(inherited.get("Resources", node.get("Resources"))) or {}
        for chunk in _content_chunks(doc, node):
            try:
                _run_content(doc, chunk, resources, state, _IDENTITY, 0, set())
            except PdfError:
                continue
            except RecursionError:
                continue
        rotate = doc.resolve(inherited.get("Rotate", node.get("Rotate", 0)))
        rows = _rows_from_runs(state.runs, int(rotate) if isinstance(rotate, int) else 0)
        if not vouch:
            rows = _unvouched_rows(doc, node, resources)
        pages.append(
            PdfPage(
                number=index + 1,
                rows=rows,
                show_ops=state.show_ops,
                vouched=state.vouched,
                unmapped=state.unmapped,
                unmapped_fonts=tuple(sorted(state.unmapped_fonts)),
                images=state.images,
                image_bytes=state.image_bytes,
                image_kinds=tuple(sorted(state.image_kinds)),
            )
        )
    return PdfText(version=version, pages=tuple(pages))


def _content_chunks(doc: PdfDocument, node: dict) -> list[bytes]:
    contents = node.get("Contents")
    targets = contents if isinstance(doc.resolve(contents), list) else [contents]
    if isinstance(doc.resolve(contents), list):
        targets = doc.resolve(contents)
    out: list[bytes] = []
    for target in targets:
        try:
            out.append(doc.data_of(target))
        except (PdfError, _ImageData):
            continue
    return out


def _unvouched_rows(doc: PdfDocument, node: dict, resources: dict) -> tuple[str, ...]:
    """What the page WOULD render if every code were decoded regardless of provenance.

    Audit-only, and deliberately crude: an unmapped code becomes `chr(code)`, which is exactly
    the assumption a reader makes when it decodes a subset font's glyph indices as if they were
    characters. `read_pdf(vouch=False)` is the only caller, and nothing in the runtime calls
    that. It exists so the mojibake guard can be DEMONSTRATED rather than asserted.
    """
    audit = _PageState(permissive=True)
    for chunk in _content_chunks(doc, node):
        try:
            _run_content(doc, chunk, resources, audit, _IDENTITY, 0, set())
        except (PdfError, RecursionError):
            continue
    rotate = doc.resolve(node.get("Rotate", 0))
    return _rows_from_runs(audit.runs, int(rotate) if isinstance(rotate, int) else 0)
