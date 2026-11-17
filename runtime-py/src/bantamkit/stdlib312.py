"""CPython 3.12's answers, on every interpreter this package supports (#316 G4, J90-P8F).

WHY THIS MODULE EXISTS. The Node port reproduces CPython 3.12 — `runtime-ts/src/memory/pyfs.ts`,
`runtime-ts/src/pyjson.ts` and the store were each measured against a 3.12 reference — and the
two runtimes share a memory store and answer the same model. `requires-python = ">=3.11"`
promises 3.13 and 3.14 too, and those interpreters changed some of the answers 3.12 gave. Where
the product asks the standard library one of those questions, it asks it HERE, and gets 3.12's
answer whichever interpreter it runs on, so Python gives Node's answer on every version.

Every function below is either the 3.12 code itself (copied, with the source named) or the
interpreter's own answer corrected by a rule that is exact for the one change it undoes. Each
names the CPython change it pins. On 3.12 every one of them returns what the standard library
returns; `runtime-py/tests/test_stdlib312.py` asks that of the running interpreter and pins the
3.12 literals on every interpreter.

  - `json`, again: 3.13.x/3.14.x report a `\\uXXXX` that ends the document as an unterminated
    string; 3.12 said `Invalid \\uXXXX escape` at its `u`. `pin_json_error`.
  - `re`: 3.14 lets `\\B` match the empty string (gh-124130); 3.12 never did. `re_search`.
  - `json`: 3.13 reports a trailing comma as `Illegal trailing comma before end of object` /
    `... of array` at the comma (gh-113149). 3.12 reported `Expecting property name enclosed in
    double quotes` / `Expecting value` at the first non-blank after it. `pin_json_error`.
  - `datetime`: 3.14 rewrote the range sentences of `date`/`datetime`/`timezone`
    (gh-109798, e.g. `month must be in 1..12, not 13`). `pin_datetime_error`.
  - `pathlib.Path.exists`/`is_dir`/`is_file`: 3.14 answers `False` for every `OSError`, as
    `os.path.exists` does; 3.12 re-raised all but ENOENT/ENOTDIR/EBADF/ELOOP (and three
    winerrors), so an EACCES parent RAISED. `path_exists`, `path_is_dir`, `path_is_file`.
  - `pathlib.Path.resolve`: from 3.13 a symlink loop no longer raises in non-strict mode; 3.12
    raised `RuntimeError("Symlink loop from %r")` (pathlib docs, "Changed in version 3.13").
    `path_resolve`.
  - `PurePath.suffix`: 3.14 counts a single trailing dot as a suffix (`'a.'` -> `'.'`,
    GH-82805); 3.12 answered `''`. `path_suffix`.
  - codecs: 3.13 and 3.14 added aliases to `encodings.aliases` and changed `palmos`'s 0x9B;
    the port's `charsets.ts` is 3.12.13's registry. `codec_module`, `codec_decode`.
  - `argparse`: 3.13 changed usage wrapping and the `invalid choice` sentence (3.11.15 the
    sentence too). `argparse`, 3.12.13's module on every interpreter.
  - Windows flavour: 3.13 made `PureWindowsPath.is_absolute()` `ntpath.isabs()`, and made
    `ntpath.isabs('/x')` False (gh-44626). `win_is_absolute`, `nt_isabs`.
"""

from __future__ import annotations

import errno as _errno
import json as _json
import os as _os
import pathlib as _pathlib
import re as _re
import stat as _stat
from typing import Any

# ---------------------------------------------------------------------------------- argparse

# 3.13 rewrote usage wrapping (a mutually exclusive group may break across lines, so `[-h]` no
# longer stands alone before `[--store STORE | --start START]`) and spells `invalid choice: ...
# (choose from 'a', 'b')` with reprs, and so does CPython 3.11.15; 3.14 also colours help. The
# CLIs' every `-h` and usage error is compared byte for byte against the Node CLI, which
# reproduces 3.12.13, so on EVERY interpreter the CLIs parse with 3.12.13's own module, vendored
# verbatim (`_argparse312.py`); on 3.12.13 that is the interpreter's own file, byte for byte.
# Resolved on first use (PEP 562 `__getattr__` below), so this module imports with the standard
# library alone -- the ts2py adapters load it by file outside the package.


def __getattr__(name: str) -> Any:
    if name != "argparse":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import _argparse312 as module

    globals()["argparse"] = module
    return module

# --------------------------------------------------------------------------------------- json

_TRAILING_COMMA = "Illegal trailing comma before end of "
_JSON_BLANK = " \t\n\r"


def pin_json_error(error: _json.JSONDecodeError) -> _json.JSONDecodeError:
    """`error` as CPython 3.12's decoder (C scanner and pure Python alike) would have raised it.

    3.13 added one check to both scanners: after a `,` and any blanks, a `}` or `]` raises
    `Illegal trailing comma before end of object|array` AT THE COMMA (gh-113149). Without it,
    3.12 went on: an object asked for a key at that first non-blank and raised `Expecting
    property name enclosed in double quotes` there; an array scanned a value there and raised
    `Expecting value` there. So the rewrite is exact: the same document, the position moved
    past the comma and its blanks, and 3.12's sentence. Any other error is returned unchanged.
    """
    msg = error.msg
    doc = error.doc
    if msg == "Unterminated string starting at" and _ends_in_u_escape(doc):
        # 3.12's C `scanstring` tested `next + 4 >= len` for a `\uXXXX`, so an escape whose four
        # digits end the document exactly was `Invalid \uXXXX escape` at its `u`; 3.13.x/3.14.x
        # read the four digits and then report the string unterminated at its opening quote.
        return _json.JSONDecodeError("Invalid \\uXXXX escape", doc, len(doc) - 5)
    if not msg.startswith(_TRAILING_COMMA):
        return error
    pos = error.pos + 1
    while pos < len(doc) and doc[pos] in _JSON_BLANK:
        pos += 1
    if msg.endswith("object"):
        return _json.JSONDecodeError("Expecting property name enclosed in double quotes", doc, pos)
    return _json.JSONDecodeError("Expecting value", doc, pos)


def _ends_in_u_escape(doc: str) -> bool:
    """Does `doc` end in `\\u` + four characters, the backslash itself unescaped?"""
    if len(doc) < 6 or doc[-6] != "\\" or doc[-5] != "u":
        return False
    run = 0
    i = len(doc) - 6
    while i >= 0 and doc[i] == "\\":
        run += 1
        i -= 1
    return run % 2 == 1


def json_loads(text: str | bytes | bytearray, **kwargs: Any) -> Any:
    """`json.loads`, raising 3.12's `JSONDecodeError` (`pin_json_error`)."""
    try:
        return _json.loads(text, **kwargs)
    except _json.JSONDecodeError as e:
        pinned = pin_json_error(e)
        if pinned is e:
            raise
        raise pinned from None


def json_raw_decode(decoder: _json.JSONDecoder, text: str, idx: int = 0) -> tuple[Any, int]:
    """`decoder.raw_decode(text, idx)`, raising 3.12's `JSONDecodeError` (`pin_json_error`)."""
    try:
        return decoder.raw_decode(text, idx)
    except _json.JSONDecodeError as e:
        pinned = pin_json_error(e)
        if pinned is e:
            raise
        raise pinned from None


# ----------------------------------------------------------------------------------- datetime

# gh-109798 (3.14): each sentence on the left is the 3.14 spelling of the 3.12 one on the right,
# measured on 3.12.13 and 3.14.10 (`tests/test_stdlib312.py`). `day` loses its numbers in 3.12.
_DATETIME_3_14 = (
    (_re.compile(r"year must be in 1\.\.9999, not (-?\d+)"),
     lambda m: f"year {m.group(1)} is out of range"),
    (_re.compile(r"day -?\d+ must be in range 1\.\.\d+ for month \d+ in year -?\d+"),
     lambda m: "day is out of range for month"),
    (_re.compile(r"(month|hour|minute|second|microsecond) must be in (\d+\.\.\d+), not -?\d+"),
     lambda m: f"{m.group(1)} must be in {m.group(2)}"),
    # 3.12 ended this one with a full stop after the repr; 3.14 does not.
    (_re.compile(r"(offset must be a timedelta strictly between -timedelta\(hours=24\) and "
                 r"timedelta\(hours=24\), not .*[^.])"), lambda m: f"{m.group(1)}."),
)


def pin_datetime_text(text: str) -> str:
    """A `date`/`datetime`/`timezone` range sentence in 3.12's spelling; anything else unchanged."""
    for pattern, spell in _DATETIME_3_14:
        m = pattern.fullmatch(text)
        if m is not None:
            return spell(m)
    return text


def pin_datetime_error(error: ValueError) -> ValueError:
    """`error`, re-spelled by `pin_datetime_text` when it is one of gh-109798's sentences.

    The SAME object is returned when nothing changes, so a caller re-raising it keeps its
    traceback; a changed one is a new `ValueError` of the same type carrying 3.12's text.
    """
    if type(error) is not ValueError or len(error.args) != 1 or not isinstance(error.args[0], str):
        return error
    pinned = pin_datetime_text(error.args[0])
    return error if pinned == error.args[0] else ValueError(pinned)


# ----------------------------------------------------------------------------------- pathlib

# `pathlib._IGNORED_ERRNOS` / `_IGNORED_WINERRORS` / `_ignore_error`, CPython 3.12 Lib/pathlib.py.
_IGNORED_ERRNOS = (_errno.ENOENT, _errno.ENOTDIR, _errno.EBADF, _errno.ELOOP)
_IGNORED_WINERRORS = (21, 123, 1921)  # NOT_READY, INVALID_NAME, CANT_RESOLVE_FILENAME
_WINERROR_CANT_RESOLVE_FILENAME = 1921


def _ignore_error(exception: BaseException) -> bool:
    return (getattr(exception, "errno", None) in _IGNORED_ERRNOS
            or getattr(exception, "winerror", None) in _IGNORED_WINERRORS)


def _mode(path: Any) -> int | None:
    """`stat().st_mode`, or `None` where 3.12's predicates answered `False`; else it raises."""
    try:
        return _os.stat(path).st_mode
    except OSError as e:
        if not _ignore_error(e):
            raise
        return None
    except ValueError:
        # Non-encodable path
        return None


def _is_pathlib(path: Any) -> bool:
    # A `str` or a `pathlib` path. Anything else (`os.DirEntry`, `zipfile.Path`, an
    # `importlib.resources` traversable that is not a `Path`) answers with its own method.
    return isinstance(path, (str, _pathlib.PurePath))


def path_exists(path: Any) -> bool:
    """`Path.exists()` as 3.12 answered it: EACCES and every other unignored error RAISE.

    An object that is not a `pathlib` path (a `zipfile.Path`, an `importlib.resources`
    traversable) is asked its own `exists()`: its answer never came from `pathlib`.
    """
    if not _is_pathlib(path):
        return path.exists()
    return _mode(path) is not None


def path_is_dir(path: Any) -> bool:
    """`Path.is_dir()` as 3.12 answered it (`path_exists`)."""
    if not _is_pathlib(path):
        return path.is_dir()
    mode = _mode(path)
    return mode is not None and _stat.S_ISDIR(mode)


def path_is_file(path: Any) -> bool:
    """`Path.is_file()` as 3.12 answered it (`path_exists`)."""
    if not _is_pathlib(path):
        return path.is_file()
    mode = _mode(path)
    return mode is not None and _stat.S_ISREG(mode)


def path_resolve(path: Any, strict: bool = False) -> _pathlib.Path:
    """`Path(path).resolve(strict)` with 3.12's symlink-loop check (CPython 3.12 `Path.resolve`).

    3.12 promoted ELOOP — from `realpath` or, in non-strict mode, from a `stat()` of its answer
    — to `RuntimeError("Symlink loop from %r" % e.filename)`; 3.13 dropped both (a loop is an
    `OSError` in strict mode and nothing at all otherwise). `realpath` itself answers the same
    text on 3.12, 3.13 and 3.14 for a loop, so 3.12's check over today's answer is 3.12's answer.
    """
    p = _pathlib.Path(path)

    def check_eloop(e: OSError) -> None:
        winerror = getattr(e, "winerror", 0)
        if e.errno == _errno.ELOOP or winerror == _WINERROR_CANT_RESOLVE_FILENAME:
            raise RuntimeError(f"Symlink loop from {e.filename!r}")

    try:
        s = _os.path.realpath(p, strict=strict)
    except OSError as e:
        check_eloop(e)
        raise
    resolved = type(p)(s)
    if not strict:
        try:
            resolved.stat()
        except OSError as e:
            check_eloop(e)
    return resolved


def path_suffix(path: Any) -> str:
    """`PurePath(path).suffix` as 3.12 answered it (CPython 3.12 `PurePath.suffix`)."""
    name = _pathlib.PurePath(path).name
    i = name.rfind(".")
    if 0 < i < len(name) - 1:
        return name[i:]
    return ""


def win_is_absolute(path: Any) -> bool:
    """`PureWindowsPath(path).is_absolute()` as 3.12 answered it: a drive AND a root."""
    w = _pathlib.PureWindowsPath(path)
    return bool(w.drive and w.root)


def nt_isabs(s: Any) -> bool:
    """`ntpath.isabs(s)` as 3.12 answered it (CPython 3.12 Lib/ntpath.py, legacy bug included)."""
    s = _os.fspath(s)
    if isinstance(s, bytes):
        sep, altsep, colon_sep = b"\\", b"/", b":\\"
    else:
        sep, altsep, colon_sep = "\\", "/", ":\\"
    s = s[:3].replace(altsep, sep)
    # Absolute: UNC, device, and paths with a drive and root.
    # LEGACY BUG: isabs("/x") should be false since the path has no drive.
    return bool(s.startswith(sep) or s.startswith(colon_sep, 1))


# ---------------------------------------------------------------------------------------- re


def without_nonboundary(pattern: str) -> str:
    """`pattern` with every `\\B` outside a character class made `(?!)`, which never matches."""
    out: list[str] = []
    i = 0
    in_class = False
    class_start = False
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            out.append("(?!)" if pattern[i + 1] == "B" and not in_class else pattern[i : i + 2])
            i += 2
            class_start = False
            continue
        if in_class:
            if c == "]" and not class_start:
                in_class = False
            class_start = class_start and c == "^"
        elif c == "[":
            in_class = True
            class_start = True
        out.append(c)
        i += 1
    return "".join(out)


def re_search(pattern: Any, string: Any, flags: int = 0) -> Any:
    """`re.search` as CPython 3.12 answered it: `\\B` never matches in an EMPTY string.

    3.14 changed `\\B` to match the empty string (gh-124130); 3.12's `SRE_AT_NON_BOUNDARY`
    answered no whenever the whole string was empty, and on every other string the two agree.
    The pattern is compiled as given first, so a bad one raises exactly what `re.search`
    raises; only then, for an empty string, is each `\\B` replaced by a never-match.
    """
    compiled = _re.compile(pattern, flags)
    if string == "" and isinstance(pattern, str) and "\\B" in pattern:
        compiled = _re.compile(without_nonboundary(pattern), flags)
    return compiled.search(string)


def pattern_error_kind(error: BaseException) -> str:
    """The name the pattern child reports for an exception: `re.error` is `error` on every CPython
    (3.13 renamed the class `PatternError`, keeping `error` as an alias)."""
    return "error" if isinstance(error, _re.error) else type(error).__name__


# ------------------------------------------------------------------------------------ codecs

# The one single-byte table 3.13 changed (`encodings/palmos.py`: 0x9B was `<control>` U+009B and
# is now U+203A SINGLE RIGHT-POINTING ANGLE QUOTATION MARK). `charsets.ts` holds 3.12's.
_PALMOS_3_12_AT_9B = "\x9b"


_ASCII_LOWER = {c: c + 32 for c in range(ord("A"), ord("Z") + 1)} | {ord(" "): "_", ord("-"): "_"}


def codec_module(label: str) -> str | None:
    """The `encodings` module CPython 3.12's `encodings.search_function` resolved `label` to.

    `None` is 3.12's `LookupError`. The registry is the frozen 3.12.13 one (`_codecs312`), so a
    label 3.13/3.14 learned (`cp00858`, `windows_31j`, `iso_8859_8_i`) resolves to nothing here,
    as it does in the port's `charsets.ts`. The steps are 3.12's: `codecs.lookup` lower-cases,
    `normalize_encoding` folds the rest, the alias table is asked with and without `.`, and the
    alias is tried before the name itself. `mbcs`/`oem` import only on Windows.
    """
    import encodings

    from ._codecs312 import CODEC_ALIASES_312, CODEC_MODULES_312

    # `codecs.lookup`'s C `normalizestring` lowers ASCII only, and spaces and hyphens become `_`.
    norm = encodings.normalize_encoding(label.translate(_ASCII_LOWER))
    aliased = CODEC_ALIASES_312.get(norm) or CODEC_ALIASES_312.get(norm.replace(".", "_"))
    for modname in ([aliased, norm] if aliased is not None else [norm]):
        if not modname or "." in modname or modname not in CODEC_MODULES_312:
            continue
        if modname in ("mbcs", "oem") and _os.name != "nt":
            continue
        return modname
    return None


def codec_decode(data: bytes, label: str, errors: str = "strict") -> str:
    """`data.decode(label, errors)` as CPython 3.12 answered it (`codec_module`, 3.12's palmos).

    Raises `LookupError` for a label 3.12 could not resolve, and otherwise decodes through the
    module 3.12 resolved it to, which every later interpreter still ships under that name.
    """
    import codecs

    modname = codec_module(label)
    if modname is None:
        raise LookupError(f"unknown encoding: {label}")
    if modname == "palmos":
        from encodings import palmos

        table = palmos.decoding_table
        table = table[:0x9B] + _PALMOS_3_12_AT_9B + table[0x9C:]
        return codecs.charmap_decode(data, errors, table)[0]
    return data.decode(modname, errors)


# `argparse` is served by `__getattr__` above and is not star-exported.
__all__ = [
    "pattern_error_kind",
    "re_search",
    "without_nonboundary",
    "codec_decode",
    "codec_module",
    "json_loads",
    "json_raw_decode",
    "nt_isabs",
    "path_exists",
    "path_is_dir",
    "path_is_file",
    "path_resolve",
    "path_suffix",
    "pin_datetime_error",
    "pin_datetime_text",
    "pin_json_error",
    "win_is_absolute",
]
