# ts2py adapters: hand-written Python for the imports and Node globals ts2py does not compile.
# Every name here is declared in tools/ts2py/src/adapters.rs with the reason it is faithful, and
# RULES.md (Adapters) records how each was measured. Nothing else may be imported this way.
import datetime as _datetime
import os as _os

from __RUNTIME__ import _JS_UNDEFINED, _js_num, _JsError, _JsObject

# `BantamError` is provided lazily by `__getattr__` below and is not listed, so a star import does
# not build it (and import `bantamkit.client`).
__all__ = [
    "Date",
    "TextDecoder",
    "assets_root",
    "cmp_codepoint",
    "exists_sync",
    "path_join",
    "process_env",
    "py_float_repr",
    "py_repr",
    "py_strip",
    "read_file_sync",
]


def py_float_repr(x):
    """`pyFloatRepr` (runtime-ts/src/memory/pyfs.ts): CPython's `repr(float)`, which it ports."""
    return repr(float(_js_num(x)))


def py_strip(s):
    """`pyStrip` (runtime-ts/src/pysem.ts): CPython's `str.strip()` with no argument, which it
    ports."""
    return s.strip()


class TextDecoder(_JsObject):
    """`new TextDecoder('utf-8')`: WHATWG UTF-8 decode. Invalid bytes become one U+FFFD per maximal
    subpart (Python's 'replace' handler does the same) and a leading BOM is dropped."""

    _js_name = "TextDecoder"
    _js_own = frozenset({"decode"})
    _js_own_methods = frozenset({"decode"})

    def __init__(self, label="utf-8", *_):
        if str(label).strip().lower() not in ("utf-8", "utf8", "unicode-1-1-utf-8"):
            raise TypeError("ts2py: a TextDecoder for anything but UTF-8 is outside the subset")

    def decode(self, data=_JS_UNDEFINED, *_):
        if data is _JS_UNDEFINED:
            return ""
        text = bytes(data).decode("utf-8", "replace")
        return text[1:] if text.startswith("﻿") else text


class Date(_JsObject):
    """`new Date()` with no argument: the local calendar fields of the current instant."""

    _js_name = "Date"
    _js_own = frozenset({"getFullYear", "getMonth", "getDate"})
    _js_own_methods = frozenset({"getFullYear", "getMonth", "getDate"})

    def __init__(self, *args):
        if args:
            raise TypeError("ts2py: new Date(...) with an argument is outside the subset")
        object.__setattr__(self, "_js_now", _datetime.datetime.now())

    def getFullYear(self):
        return self._js_now.year

    def getMonth(self):
        return self._js_now.month - 1

    def getDate(self):
        return self._js_now.day


# ---------------------------------------------------------------- J87-3 (#316 G1): pricing


def py_repr(s):
    """`pyRepr` (runtime-ts/src/pysem.ts): CPython's `repr(str)`, which it ports."""
    if not isinstance(s, str):
        raise TypeError("ts2py: pyRepr of anything but a string is outside the subset")
    return repr(s)


def cmp_codepoint(a, b, *_):
    """`cmpCodepoint` (runtime-ts/src/pysem.ts): the order of CPython's `sorted()` on two strings,
    by code point; the same value the TypeScript returns (-1, 1, or the length difference)."""
    if not (isinstance(a, str) and isinstance(b, str)):
        raise TypeError("ts2py: cmpCodepoint of anything but two strings is outside the subset")
    for x, y in zip(a, b, strict=False):
        if x != y:
            return -1 if x < y else 1
    return len(a) - len(b)


def process_env(name):
    """`process.env[name]`: the process environment, `undefined` when unset. Each runtime reads its
    own process's environment; the hand-written module read `os.environ`."""
    if not isinstance(name, str):
        raise TypeError("ts2py: process.env read by anything but a string is outside the subset")
    return _os.environ.get(name, _JS_UNDEFINED)


def assets_root():
    """`assetsRoot` (runtime-ts/src/assets.ts): `bantamkit.assets.assets_root()`, which the
    TypeScript mirrors arm for arm (its doc comment), as the string JS holds."""
    from ..assets import assets_root as _assets_root

    return str(_assets_root())


def _checked_path(path, what):
    if not isinstance(path, str):
        raise TypeError(f"ts2py: {what} of anything but a string path is outside the subset")
    if "\0" in path or any(0xD800 <= ord(c) <= 0xDFFF for c in path):
        # Node refuses a NUL with its own TypeError and encodes a lone surrogate as U+FFFD; CPython
        # refuses the one and maps some of the other to bytes. Neither is modelled.
        raise TypeError(
            f"ts2py: {what} of a path holding NUL or a lone surrogate is outside the subset"
        )
    return path


def exists_sync(path, *_):
    """`fs.existsSync(path)`: true when the path can be stat'ed (symlinks followed), false on any
    error, never a raise; a non-string argument (null, a number) is false, as Node answers it."""
    if path is None or path is _JS_UNDEFINED or isinstance(path, (bool, int, float)):
        return False
    return _os.path.exists(_checked_path(path, "fs.existsSync"))


def read_file_sync(path, encoding=_JS_UNDEFINED, *_):
    """`fs.readFileSync(path, 'utf8')`: the file's bytes decoded as Node decodes UTF-8, one U+FFFD
    per maximal invalid subpart and a BOM kept. A failure is the `OSError` CPython's `open()` raises
    for the same path (class, errno, strerror, filename), which a generated `catch` sees as Node's
    fs Error and which reaches a Python caller unchanged otherwise."""
    if encoding not in ("utf8", "utf-8"):
        raise TypeError("ts2py: fs.readFileSync without the 'utf8' encoding is outside the subset")
    with open(_checked_path(path, "fs.readFileSync"), "rb") as handle:
        data = handle.read()
    return data.decode("utf-8", "replace")


def _normalize_string(path, allow_above_root, separator, is_separator):
    """Node's `normalizeString` (lib/path.js), statement for statement."""
    res = ""
    last_segment_length = 0
    last_slash = -1
    dots = 0
    code = ""
    i = 0
    while i <= len(path):
        if i < len(path):
            code = path[i]
        elif is_separator(code):
            break
        else:
            code = "/"
        if is_separator(code):
            if last_slash == i - 1 or dots == 1:
                pass
            elif dots == 2:
                if len(res) < 2 or last_segment_length != 2 or res[-1] != "." or res[-2] != ".":
                    if len(res) > 2:
                        last_slash_index = res.rfind(separator)
                        if last_slash_index == -1:
                            res = ""
                            last_segment_length = 0
                        else:
                            res = res[:last_slash_index]
                            last_segment_length = len(res) - 1 - res.rfind(separator)
                        last_slash = i
                        dots = 0
                        i += 1
                        continue
                    elif len(res) != 0:
                        res = ""
                        last_segment_length = 0
                        last_slash = i
                        dots = 0
                        i += 1
                        continue
                if allow_above_root:
                    res += separator + ".." if len(res) > 0 else ".."
                    last_segment_length = 2
            else:
                if len(res) > 0:
                    res += separator + path[last_slash + 1 : i]
                else:
                    res = path[last_slash + 1 : i]
                last_segment_length = i - last_slash - 1
            last_slash = i
            dots = 0
        elif code == "." and dots != -1:
            dots += 1
        else:
            dots = -1
        i += 1
    return res


def _posix_join(parts):
    """`path.posix.join` (lib/path.js): the non-empty parts joined by `/`, then normalised."""
    joined = "/".join(part for part in parts if part)
    if not joined:
        return "."
    absolute = joined[0] == "/"
    trailing = joined[-1] == "/"
    joined = _normalize_string(joined, not absolute, "/", lambda c: c == "/")
    if not joined:
        return "/" if absolute else ("./" if trailing else ".")
    if trailing:
        joined += "/"
    return "/" + joined if absolute else joined


_WIN32_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"{kind}{n}" for kind in ("COM", "LPT") for n in "0123456789\u00b9\u00b2\u00b3"]
)


def _win32_separator(c):
    return c in ("/", "\\")


def _win32_join(parts):
    """`path.win32.join` (lib/path.js) on the paths its reserved-device-name and colon rules leave
    alone: a colon only as a drive's (`C:`), and no path whose last character dropped leaves a
    reserved device name (`normalize` tests that slice). Anything else is outside the subset."""
    parts = [part for part in parts if part]
    if not parts:
        return "."
    first = parts[0]
    joined = "\\".join(parts)
    colons = [i for i, c in enumerate(joined) if c == ":"]
    if colons and (colons != [1] or not joined[0].isascii() or not joined[0].isalpha()):
        raise TypeError(
            "ts2py: path.join on win32 of a path with a colon past a drive is outside the subset"
        )
    needs_replace = True
    slash_count = 0
    if _win32_separator(first[0]):
        slash_count += 1
        if len(first) > 1 and _win32_separator(first[1]):
            slash_count += 1
            if len(first) > 2:
                if _win32_separator(first[2]):
                    slash_count += 1
                else:
                    needs_replace = False
    if needs_replace:
        while slash_count < len(joined) and _win32_separator(joined[slash_count]):
            slash_count += 1
        if slash_count >= 2:
            joined = "\\" + joined[slash_count:]
    if not colons and joined[:-1].upper() in _WIN32_RESERVED:
        raise TypeError("ts2py: path.join on win32 of a reserved device name is outside the subset")
    return _win32_normalize(joined)


def _win32_normalize(path):
    """`path.win32.normalize` (lib/path.js) on the domain `_win32_join` admits."""
    length = len(path)
    if length == 1:
        return "\\" if path == "/" else path
    root_end = 0
    device = None
    absolute = False
    code = path[0]
    if _win32_separator(code):
        absolute = True
        if _win32_separator(path[1]):
            j = 2
            last = j
            while j < length and not _win32_separator(path[j]):
                j += 1
            if j < length and j != last:
                first = path[last:j]
                last = j
                while j < length and _win32_separator(path[j]):
                    j += 1
                if j < length and j != last:
                    last = j
                    while j < length and not _win32_separator(path[j]):
                        j += 1
                    if j == length or j != last:
                        if first in (".", "?"):
                            raise TypeError(
                                "ts2py: path.join on win32 of a device root is outside the subset"
                            )
                        if j == length:
                            return "\\\\" + first + "\\" + path[last:] + "\\"
                        device = "\\\\" + first + "\\" + path[last:j]
                        root_end = j
        else:
            root_end = 1
    elif path.find(":") == 1:
        device = path[:2]
        root_end = 2
        if length > 2 and _win32_separator(path[2]):
            absolute = True
            root_end = 3
    tail = (
        _normalize_string(path[root_end:], not absolute, "\\", _win32_separator)
        if root_end < length
        else ""
    )
    if not tail and not absolute:
        tail = "."
    if tail and _win32_separator(path[-1]):
        tail += "\\"
    if device is None:
        return "\\" + tail if absolute else tail
    return device + "\\" + tail if absolute else device + tail


def path_join(*parts):
    """`path.join(...parts)` (Node's `lib/path.js`, ported statement for statement): `path.posix`
    on POSIX, `path.win32` on Windows (where it raises outside the colon and device-name subset)."""
    for part in parts:
        if not isinstance(part, str):
            raise TypeError("ts2py: path.join of anything but strings is outside the subset")
    if _os.name == "nt":
        return _win32_join(list(parts))
    return _posix_join(list(parts))


def _lazy_bantam_error():
    # `bantamkit.client.BantamError` is the reference; it is imported only when a generated module
    # first asks for this name, so modules that never use it do not pay for `bantamkit.client`.
    try:
        from ..client import BantamError as python_base
    except ImportError:
        # Outside the bantamkit package (ts2py's own tests): the JS face alone.
        bases = (_JsError,)
    else:
        bases = (_JsError, python_base)

    def __init__(self, message=_JS_UNDEFINED, *_):
        _JsError.__init__(self, message)
        # `this.name = new.target.name`: the constructing class's own JS name, as an own property.
        self.name = type(self)._js_name

    return type(
        "BantamError",
        bases,
        {
            "__doc__": "`BantamError` (runtime-ts/src/errors.ts): bantamkit.client.BantamError, "
            "the base it mirrors, with JS's Error face; `name` is the constructing class's name.",
            "__module__": __name__,
            "_js_name": "BantamError",
            "_js_own": frozenset(),
            "_js_own_methods": frozenset(),
            "__init__": __init__,
        },
    )


def __getattr__(name):
    # PEP 562: `BantamError` is built on first import (`from ._ts2py_adapters import BantamError`).
    if name == "BantamError":
        cls = _lazy_bantam_error()
        globals()["BantamError"] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
