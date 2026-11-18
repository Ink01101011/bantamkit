# ts2py adapters: hand-written Python for the imports and Node globals ts2py does not compile.
# Every name here is declared in tools/ts2py-bantamkit/ts2py.toml with the reason it is faithful,
# and RULES.md (Adapters) records how each was measured. Nothing else may be imported this way.
import datetime as _datetime
import errno as _errno
import fnmatch as _fnmatch
import functools as _functools
import gzip as _gzip
import hashlib as _hashlib
import io as _io
import json as _json
import math as _math
import os as _os
import pathlib as _pathlib
import re as _re
import secrets as _secrets
import stat as _stat
import time as _time
import typing as _typing
import unicodedata as _unicodedata
import zlib as _zlib

from __RUNTIME__ import (
    _JS_UNDEFINED,
    _js_lifted,
    _js_m_toLowerCase,
    _js_num,
    _js_py_round_float9,
    _js_truthy,
    _JsBigInt,
    _JsError,
    _JsMap,
    _JsObject,
    _JsRangeError,
    _JsTypeError,
)

# J90-P8F: the CPython 3.12 answers the Node port reproduces, on 3.13 and 3.14 too
# (`bantamkit/stdlib312.py` names each change). Looked up on first use, as the other bantamkit
# names here are. Inside the package it is always there. A module compiled OUTSIDE it (the host
# crate's tests, `--suite ts2py-codec`) loads the file from wherever `bantamkit` is on the path,
# without importing the package; with no bantamkit anywhere it gets `_LiveLibrary`, the
# interpreter's own answers, which is what every adapter asked before J90-P8F.
_STDLIB312 = None


class _LiveLibrary:
    """The standard library's own answers, under the names `stdlib312` gives its 3.12 pins."""

    path_exists = staticmethod(lambda path: _pathlib.Path(path).exists())
    path_is_dir = staticmethod(lambda path: _pathlib.Path(path).is_dir())
    path_is_file = staticmethod(lambda path: _pathlib.Path(path).is_file())
    path_resolve = staticmethod(lambda path, strict=False: _pathlib.Path(path).resolve(strict))
    path_suffix = staticmethod(lambda path: _pathlib.PurePath(path).suffix)
    win_is_absolute = staticmethod(lambda path: _pathlib.PureWindowsPath(path).is_absolute())
    json_loads = staticmethod(_json.loads)
    pin_datetime_error = staticmethod(lambda error: error)


def _stdlib312_by_path():
    """`bantamkit/stdlib312.py` from wherever `bantamkit` would be imported from, loaded as a module
    of its own: the package's `__init__` (and its dependencies) never runs. `None` if not found."""
    import importlib.machinery
    import importlib.util

    spec = importlib.machinery.PathFinder.find_spec("bantamkit")
    for directory in (spec.submodule_search_locations or []) if spec is not None else []:
        source = _os.path.join(directory, "stdlib312.py")
        if _os.path.isfile(source):
            found = importlib.util.spec_from_file_location("_bantamkit_stdlib312", source)
            module = importlib.util.module_from_spec(found)
            found.loader.exec_module(module)
            return module
    return None


def _stdlib312():
    global _STDLIB312
    if _STDLIB312 is None:
        try:
            from .. import stdlib312 as module
        except ImportError:
            module = _stdlib312_by_path() or _LiveLibrary
        _STDLIB312 = module
    return _STDLIB312

# J90-P7 (#316 G4): mypyc reads this module (it is never compiled) to know the base of a compiled
# `class E extends BantamError`. A base it cannot see is `Any`, and mypyc then builds the class on
# `object` alone, silently; this declaration, which only a type checker reads, names the class
# `__getattr__` builds.
if _typing.TYPE_CHECKING:

    class BantamError(_JsError):
        pass


# `BantamError` (and J89-4a's `PyScalar`, `VALID_OUTCOMES`; J90-2 retired the lock's and the hot
# index's constants, now compiled)
# are provided lazily by `__getattr__` below and are not listed, so a star import does not build
# them (and import `bantamkit.client` / `storage.lock` / the codec / the hot index).
__all__ = [
    "BigIntStats",
    "CountsView",
    "Date",
    "Hash",
    "PyOSError",
    "PyUnicodeDecodeError",
    "Stats",
    "TextDecoder",
    "append_file_sync",
    "as_py_os_error",
    "assets_root",
    "bantamkit_dir_for",
    "buffer_alloc",
    "buffer_byte_length",
    "buffer_concat",
    "buffer_from",
    "close_sync",
    "coldFs",
    "cold_error_text",
    "dump_js_value",
    "dump_json",
    "encode_basestring_ascii",
    "extract_refs",
    "cmp_codepoint",
    "create_hash",
    "ensure_bantamkit_gitignore",
    "exists_sync",
    "extra_of",
    "fact_refs",
    "format_fact",
    "fstat_sync",
    "gunzip_sync",
    "gzip_sync",
    "hash_hex",
    "homedir",
    "lifecycle_of",
    "link_sync",
    "lstat_sync",
    "matches_md",
    "node_realpath",
    "mkdir_sync",
    "open_sync",
    "os_error_class_name",
    "parse_frontmatter",
    "parse_json",
    "parse_native",
    "path_basename",
    "path_dirname",
    "path_join",
    "performance_now",
    "process_env",
    "process_env_all",
    "process_pid",
    "py_decode_utf8",
    "py_exists",
    "py_float_repr",
    "py_is_dir",
    "py_join",
    "py_lexists",
    "py_list",
    "py_log",
    "py_log1p",
    "py_mkdir_parents",
    "py_mtime_date",
    "py_name",
    "py_nfkc_lower",
    "py_os_error_strerror",
    "py_os_error_text",
    "py_parent",
    "py_parents",
    "py_pow",
    "py_read_text",
    "py_realpath",
    "py_replace",
    "py_repr",
    "py_round_float9",
    "py_scandir_names",
    "py_scandir_probe",
    "py_search_word",
    "py_split",
    "py_strip",
    "py_suffix",
    "py_truthy",
    "py_unlink",
    "py_wordchar",
    "py_write_text",
    "py_write_text_atomic",
    "random_bytes",
    "read_file_bytes",
    "read_file_sync",
    "read_sync",
    "readdir_sync",
    "rename_sync",
    "rm_sync",
    "rmdir_sync",
    "retentionFs",
    "spawn_retention_child",
    "touch_reducer",
    "native_memory_dir",
    "has_bantamkit_hooks",
    "process_cwd",
    "unlink_sync",
    "path_relative",
    "PATH_SEP",
    "sorted_path_names",
    "stat_sync",
    "today_local",
    "write_file_sync",
    "write_sync",
    "first_token_tab",
    "parse_config_document",
    "py_cwd",
    "py_expanduser",
    "py_is_absolute",
    "py_is_file",
    "py_resolve",
    "py_stat_is_dir",
    "format_fixed3",
    "py_int_digits",
    "py_relative_scan",
    "py_slot_groups",
    "py_sub_spaces",
    "py_unresolved_terms",
    "SkillStore",
    "file_links",
    "fire_on",
    "is_skill_store",
    "load_skill",
    "path_resolve",
    "py_home",
    "py_lower",
    "skill_roots",
    "triggers_enabled",
    "via_enabled",
    "via_label",
    "via_pick",
]


def py_float_repr(x):
    """`pyFloatRepr` (runtime-ts/src/memory/pyfs.ts): CPython's `repr(float)`, which it ports."""
    return repr(float(_js_num(x)))


def py_strip(s):
    """`pyStrip` (runtime-ts/src/pysem.ts): CPython's `str.strip()` with no argument, which it
    ports."""
    return s.strip()


class TextDecoder(_JsObject):
    """`new TextDecoder('utf-8', {fatal?, ignoreBOM?})`: WHATWG UTF-8 decode. Invalid bytes become
    one U+FFFD per maximal subpart (Python's 'replace' handler does the same); with `fatal: true`
    they are refused instead, as the TypeError Node throws (code
    `ERR_ENCODING_INVALID_ENCODED_DATA`), exactly where CPython's strict decoder refuses (J88-2
    measured the two acceptance sets equal). A
    leading BOM is dropped unless `ignoreBOM: true` keeps it. Nothing else is touched: no newline
    translation."""

    _js_name = "TextDecoder"
    _js_own = frozenset({"decode"})
    _js_own_methods = frozenset({"decode"})

    def __init__(self, label="utf-8", options=_JS_UNDEFINED, *_):
        if str(label).strip().lower() not in ("utf-8", "utf8", "unicode-1-1-utf-8"):
            raise TypeError("ts2py: a TextDecoder for anything but UTF-8 is outside the subset")
        fatal = ignore_bom = False
        if options is not _JS_UNDEFINED and options is not None:
            if not isinstance(options, dict) or set(options) - {"fatal", "ignoreBOM"}:
                raise TypeError(
                    "ts2py: TextDecoder options other than fatal/ignoreBOM are outside the subset"
                )
            fatal = _js_truthy(options.get("fatal", _JS_UNDEFINED))
            ignore_bom = _js_truthy(options.get("ignoreBOM", _JS_UNDEFINED))
        object.__setattr__(self, "_js_fatal", fatal)
        object.__setattr__(self, "_js_ignore_bom", ignore_bom)

    def decode(self, data=_JS_UNDEFINED, *_):
        if data is _JS_UNDEFINED:
            return ""
        if self._js_fatal:
            try:
                text = bytes(data).decode("utf-8")
            except UnicodeDecodeError:
                error = _JsTypeError("The encoded data was not valid for encoding utf-8")
                error.code = "ERR_ENCODING_INVALID_ENCODED_DATA"
                raise error from None
        else:
            text = bytes(data).decode("utf-8", "replace")
        if self._js_ignore_bom:
            return text
        return text[1:] if text.startswith("\ufeff") else text


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


# J89-5: `_js_m_sort` sorts a list of strings by this comparator with Python's own `str` order,
# which is code-point order (the fast path is pinned against this function by `g3_store.rs`).
cmp_codepoint._js_codepoint_order = True


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
    if isinstance(path, str) and "\0" in path:
        # J88-2: Node validates the path inside its try and answers false for a NUL.
        return False
    return _os.path.exists(_node_path(path, "fs.existsSync"))


def read_file_sync(path, encoding=_JS_UNDEFINED, *_):
    """`fs.readFileSync(path, 'utf8')` (J88-2: or no encoding, the bytes): the file's bytes decoded
    as Node decodes UTF-8, one U+FFFD
    per maximal invalid subpart and a BOM kept. A failure is the `OSError` CPython's `open()` raises
    for the same path (class, errno, strerror, filename), which a generated `catch` sees as Node's
    fs Error and which reaches a Python caller unchanged otherwise."""
    if encoding is _JS_UNDEFINED:
        # J88-2: no encoding is the file's bytes, a Buffer.
        return read_file_bytes(path)
    if encoding not in ("utf8", "utf-8"):
        raise TypeError("ts2py: fs.readFileSync with an encoding but 'utf8' is outside the subset")
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


def _posix_normalized(path, allow_above_root):
    """`normalizeString(path, allowAboveRoot, '/', isPosixPathSeparator)`. J90-P: a path with no
    `.` or `..` segment is its non-empty segments joined by one `/` (`normalizeString` skips an
    empty segment and keeps every other one as it is; only `.` and `..` do anything else), in C;
    any other path through the port."""
    segments = path.split("/")
    if "." not in segments and ".." not in segments:
        return "/".join(filter(None, segments))
    return _normalize_string(path, allow_above_root, "/", lambda c: c == "/")


def _posix_join(parts):
    """`path.posix.join` (lib/path.js): the non-empty parts joined by `/`, then normalised."""
    joined = "/".join(part for part in parts if part)
    if not joined:
        return "."
    absolute = joined[0] == "/"
    trailing = joined[-1] == "/"
    joined = _posix_normalized(joined, not absolute)
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
            if part is _JS_UNDEFINED or part is None:
                # J90-3: Node's `validateString` refusal, a TypeError a compiled `catch` sees
                # (`retention.ts` joins a cold-index doc's `file`, which may be missing).
                error = _JsTypeError(
                    'The "path" argument must be of type string. Received '
                    + ("undefined" if part is _JS_UNDEFINED else "null")
                )
                error.code = "ERR_INVALID_ARG_TYPE"
                raise error
            raise TypeError("ts2py: path.join of anything but strings is outside the subset")
    if _os.name == "nt":
        return _win32_join(list(parts))
    return _posix_join(list(parts))


# ---------------------------------------------------------------- J88-2 (#316 G2): event log,
# token ledger, log segment


def _os_char(c):
    """One code point of a path as the OS receives it: kept when Python's own `os` functions can
    encode it (`os.fsencode`), else the U+FFFD Node's UTF-8 encoding writes for it. Windows has
    no surrogateescape names (its `fsencode` passes every lone surrogate through), so there every
    lone surrogate is Node's U+FFFD, and the lone-surrogate beds agree on NTFS too."""
    if _os.name == "nt" and 0xD800 <= ord(c) <= 0xDFFF:
        return "�"
    try:
        _os.fsencode(c)
    except UnicodeEncodeError:
        return "\ufffd"
    return c


def _node_path(path, what):
    """A path as the OS receives it: a string, handed over the way Python's own `os` functions
    encode it, so a POSIX surrogateescape path (U+DC80..U+DCFF standing for the undecodable bytes
    of a real name, as `os.getcwd` / `os.listdir` return it) is that real name, as on main and in
    the hand-written store and lock (J88-RF F4b: target-specific I/O, docs/porting.md). A lone
    surrogate Python cannot encode at all is the U+FFFD that Node's UTF-8 encoding of the string
    writes. A NUL is the TypeError Node throws (code `ERR_INVALID_ARG_VALUE`)."""
    if not isinstance(path, str):
        raise TypeError(f"ts2py: {what} of anything but a string path is outside the subset")
    if "\0" in path:
        error = _JsTypeError("The argument 'path' must be a string without null bytes")
        error.code = "ERR_INVALID_ARG_VALUE"
        raise error
    return _os_text(path)


class Stats(_JsObject):
    """`fs.Stats` from `statSync`/`lstatSync`/`fstatSync`: `size`, `mtimeMs` (libuv's seconds and
    nanoseconds as Node combines them, `sec * 1e3 + nsec / 1e6`), `ino` (J90-P4: libuv's `st_ino`
    as a double, which the hot index's held-head check reads), and the type tests. On Windows a
    junction is a symbolic link to `lstat`, as libuv reports one."""

    _js_name = "Stats"
    _js_own = frozenset({"size", "mtimeMs", "ino", "isDirectory", "isFile", "isSymbolicLink"})
    _js_own_methods = frozenset({"isDirectory", "isFile", "isSymbolicLink"})

    def __init__(self, st, *_):
        ns = st.st_mtime_ns
        # J90-P4: the fields set at once (the instance is not frozen yet, so `__setattr__`'s test
        # has nothing to refuse).
        self.__dict__.update(
            _js_st=st,
            size=st.st_size,
            mtimeMs=(ns // 1_000_000_000) * 1e3 + (ns % 1_000_000_000) / 1e6,
            ino=_js_num(st.st_ino),
        )

    def isDirectory(self, *_):
        return _stat.S_ISDIR(self._js_st.st_mode)

    def isFile(self, *_):
        return _stat.S_ISREG(self._js_st.st_mode)

    def isSymbolicLink(self, *_):
        st = self._js_st
        if _stat.S_ISLNK(st.st_mode):
            return True
        tag = getattr(st, "st_reparse_tag", 0)
        return tag in (
            getattr(_stat, "IO_REPARSE_TAG_SYMLINK", -1),
            getattr(_stat, "IO_REPARSE_TAG_MOUNT_POINT", -1),
        )


class BigIntStats(Stats):
    """`fs.Stats` from `statSync(path, {bigint: true})` (J89-4a): `size`, `mtimeMs` and `mtimeNs`
    as BigInts (`mtimeNs` is libuv's `sec * 1e9 + nsec` exactly, which `st_mtime_ns` is;
    `mtimeMs` that floored to milliseconds; J90-P4: `ino`, `st_ino` exactly), and the same type
    tests."""

    _js_name = "BigIntStats"
    _js_own = frozenset(
        {"size", "mtimeMs", "mtimeNs", "ino", "isDirectory", "isFile", "isSymbolicLink"}
    )

    def __init__(self, st, *_):
        # J90-P7B: the five fields stored one by one (no keyword dict built per stat).
        ns = st.st_mtime_ns
        fields = self.__dict__
        fields["_js_st"] = st
        fields["size"] = _JsBigInt(st.st_size)
        fields["mtimeNs"] = _JsBigInt(ns)
        fields["mtimeMs"] = _JsBigInt(ns // 1_000_000)
        fields["ino"] = _JsBigInt(st.st_ino)


def stat_sync(path, *rest):
    """`fs.statSync(path)`: `os.stat` (symlinks followed); a failure is CPython's OSError. J89-4a:
    `{bigint: true}` (or `false`) as the one option, the BigInt fields (`BigIntStats`)."""
    bigint = False
    if rest:
        options = rest[0]
        # J90-P7B: "exactly the key `bigint`" without a set built per call.
        only = len(rest) == 1 and isinstance(options, dict) and len(options) == 1
        if not (only and "bigint" in options):
            raise TypeError("ts2py: fs.statSync options other than bigint are outside the subset")
        bigint = _js_truthy(options["bigint"])
    st = _os.stat(_node_path(path, "fs.statSync"))
    return BigIntStats(st) if bigint else Stats(st)


def lstat_sync(path, *rest):
    """`fs.lstatSync(path)`: `os.lstat`; a failure is CPython's OSError. J90-3: `{bigint: true}`
    (or `false`) as the one option, the BigInt fields (`BigIntStats`), as `statSync` takes it."""
    bigint = False
    if rest:
        options = rest[0]
        # J90-P7B: "exactly the key `bigint`" without a set built per call.
        only = len(rest) == 1 and isinstance(options, dict) and len(options) == 1
        if not (only and "bigint" in options):
            raise TypeError("ts2py: fs.lstatSync options other than bigint are outside the subset")
        bigint = _js_truthy(options["bigint"])
    st = _os.lstat(_node_path(path, "fs.lstatSync"))
    return BigIntStats(st) if bigint else Stats(st)


def stat_stamp(path, *_):
    """`statStamp` (runtime-ts/src/storage/statstamp.ts, J90-PF): `${mtimeNs}:${size}:${ino}` of
    `statSync(path, {bigint: true})`, the decimals of the three integers `BigIntStats` holds, from
    the same `os.stat` without building it. The path and the failure are `stat_sync`'s."""
    st = _os.stat(_node_path(path, "fs.statSync"))
    return f"{st.st_mtime_ns}:{st.st_size}:{st.st_ino}"


def stat_mtime_ns(path, *_):
    """`statMtimeNs` (runtime-ts/src/storage/statstamp.ts, J90-PF): `statSync(path, {bigint:
    true}).mtimeNs.toString()`, the decimal of `st_mtime_ns`. The path and the failure are
    `stat_sync`'s."""
    return str(_os.stat(_node_path(path, "fs.statSync")).st_mtime_ns)


def stat_file(path, *_):
    """`statFile` (runtime-ts/src/storage/statstamp.ts, J90-PF): `[mtimeNs.toString(),
    Number(size), isFile()]` of `statSync(path, {bigint: true})`: the decimal of `st_mtime_ns`, the
    size as the number `Number` makes of its BigInt (`_js_num`: an int up to 2^53, else the nearest
    double) and `BigIntStats.isFile`'s answer. The path and the failure are `stat_sync`'s."""
    st = _os.stat(_node_path(path, "fs.statSync"))
    return [str(st.st_mtime_ns), _js_num(st.st_size), _stat.S_ISREG(st.st_mode)]


def fstat_sync(fd, *rest):
    """`fs.fstatSync(fd)`: `os.fstat`."""
    if rest or isinstance(fd, bool) or not isinstance(fd, int):
        raise TypeError("ts2py: fs.fstatSync of anything but a descriptor is outside the subset")
    return Stats(_os.fstat(fd))


def readdir_sync(path, *rest):
    """`fs.readdirSync(path)`: the entry names in the order the directory gives them (`.` and `..`
    left out), each decoded from its bytes as Node decodes them (UTF-8, one U+FFFD per invalid
    subpart); on Windows the UTF-16 names with any lone surrogate as U+FFFD."""
    if rest:
        raise TypeError("ts2py: fs.readdirSync options are outside the subset")
    path = _node_path(path, "fs.readdirSync")
    # J90-P4: a listing of ASCII names only is the same list whichever way it is decoded (an
    # ASCII byte is itself under UTF-8 with "replace" and under the filesystem encoding), so it is
    # returned as `os.listdir` gives it; any other is listed again and decoded below.
    names = _os.listdir(path)
    if "".join(names).isascii():
        return names
    if _os.name == "nt":
        # A NAME comes back as Node reports it: every lone surrogate U+FFFD (only a path handed
        # IN keeps what Python's `os` can encode, J88-RF F4b).
        return [
            "".join("\ufffd" if 0xD800 <= ord(c) <= 0xDFFF else c for c in name)
            for name in _os.listdir(path)
        ]
    return [name.decode("utf-8", "replace") for name in _os.listdir(_os.fsencode(path))]


def mkdir_sync(path, options=_JS_UNDEFINED, *_):
    """`fs.mkdirSync(path, {recursive: true})`: every missing directory made (mode 0o777 under the
    umask), an existing directory accepted; an existing file is EEXIST, a file on the way ENOTDIR,
    as `os.makedirs(exist_ok=True)` raises them. Without `recursive` it is outside the subset."""
    recursive = isinstance(options, dict) and set(options) == {"recursive"}
    if not (recursive and options["recursive"] is True):
        raise TypeError("ts2py: fs.mkdirSync without {recursive: true} is outside the subset")
    _os.makedirs(_node_path(path, "fs.mkdirSync"), exist_ok=True)
    return _JS_UNDEFINED


def rename_sync(old, new, *_):
    """`fs.renameSync(old, new)`: rename(2), replacing `new` (`os.replace`, which is MoveFileEx's
    replace on Windows, as libuv's rename is)."""
    _os.replace(_node_path(old, "fs.renameSync"), _node_path(new, "fs.renameSync"))
    return _JS_UNDEFINED


def rm_sync(path, options=_JS_UNDEFINED, *_):
    """`fs.rmSync(path, {force: true})`: a file or symlink unlinked, a missing path ignored; a
    directory is refused (Node's ERR_FS_EISDIR, here CPython's IsADirectoryError, both an error with
    a string `code`). `recursive` is outside the subset."""
    if not (isinstance(options, dict) and set(options) == {"force"} and options["force"] is True):
        raise TypeError("ts2py: fs.rmSync without exactly {force: true} is outside the subset")
    path = _node_path(path, "fs.rmSync")
    try:
        st = _os.lstat(path)
    except FileNotFoundError:
        return _JS_UNDEFINED
    if _stat.S_ISDIR(st.st_mode):
        raise IsADirectoryError(_errno.EISDIR, _os.strerror(_errno.EISDIR), path)
    try:
        _os.unlink(path)
    except FileNotFoundError:
        pass
    return _JS_UNDEFINED


def link_sync(existing, new, *_):
    """`fs.linkSync(existing, new)`: link(2), as `os.link` calls it."""
    _os.link(_node_path(existing, "fs.linkSync"), _node_path(new, "fs.linkSync"))
    return _JS_UNDEFINED


_OPEN_FLAGS = {
    "r": _os.O_RDONLY,
    "r+": _os.O_RDWR,
    "w": _os.O_TRUNC | _os.O_CREAT | _os.O_WRONLY,
    "wx": _os.O_TRUNC | _os.O_CREAT | _os.O_WRONLY | _os.O_EXCL,
    "w+": _os.O_TRUNC | _os.O_CREAT | _os.O_RDWR,
    "a": _os.O_APPEND | _os.O_CREAT | _os.O_WRONLY,
    "ax": _os.O_APPEND | _os.O_CREAT | _os.O_WRONLY | _os.O_EXCL,
    "a+": _os.O_APPEND | _os.O_CREAT | _os.O_RDWR,
}
# libuv opens every file in binary mode on Windows; the C runtime's default there is text.
_BINARY = getattr(_os, "O_BINARY", 0)


def open_sync(path, flags="r", *rest):
    """`fs.openSync(path, flags)`: Node's `stringToFlags` for the flags listed above, mode 0o666
    (Node's default, under the umask), binary on Windows; the descriptor is an int."""
    if rest or flags not in _OPEN_FLAGS:
        raise TypeError(f"ts2py: fs.openSync with flags {flags!r} or a mode is outside the subset")
    return _os.open(_node_path(path, "fs.openSync"), _OPEN_FLAGS[flags] | _BINARY, 0o666)


def close_sync(fd, *_):
    """`fs.closeSync(fd)`: `os.close`."""
    if isinstance(fd, bool) or not isinstance(fd, int):
        raise TypeError("ts2py: fs.closeSync of anything but a descriptor is outside the subset")
    _os.close(fd)
    return _JS_UNDEFINED


def write_sync(fd, data, *rest):
    """`fs.writeSync(fd, buffer)`: ONE write(2) of the whole buffer at the descriptor's position,
    answering the count written, as Node's single `writeBuffer` call does (neither loops)."""
    if rest or not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("ts2py: fs.writeSync of anything but (fd, buffer) is outside the subset")
    return _os.write(fd, data)


def read_sync(fd, buffer, offset, length, position, *_):
    """`fs.readSync(fd, buffer, offset, length, position)`: one read of up to `length` bytes into
    `buffer[offset:]`, at `position` (pread) when it is a number, answering the count read."""
    if not isinstance(buffer, bytearray) or not all(
        isinstance(v, int) and not isinstance(v, bool) for v in (offset, length)
    ):
        raise TypeError(
            "ts2py: fs.readSync of anything but (fd, Buffer.alloc, int, int, pos)"
            " is outside the subset"
        )
    if offset < 0 or length < 0 or offset + length > len(buffer):
        raise TypeError("ts2py: fs.readSync out of the buffer's bounds is outside the subset")
    if isinstance(position, (int, float)) and not isinstance(position, bool) and position >= 0:
        pos = int(position)
        if hasattr(_os, "pread"):
            data = _os.pread(fd, length, pos)
        else:  # Windows: libuv reads at the offset and restores the file pointer
            here = _os.lseek(fd, 0, _os.SEEK_CUR)
            try:
                _os.lseek(fd, pos, _os.SEEK_SET)
                data = _os.read(fd, length)
            finally:
                _os.lseek(fd, here, _os.SEEK_SET)
    elif position is None or position is _JS_UNDEFINED:
        data = _os.read(fd, length)
    else:
        raise TypeError("ts2py: fs.readSync at that position is outside the subset")
    buffer[offset : offset + len(data)] = data
    return len(data)


def append_file_sync(path, data, *rest):
    """`fs.appendFileSync(path, buffer)`: opened `a` (mode 0o666, binary), the whole buffer written
    (Node loops until it is), closed."""
    if rest or not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(
            "ts2py: fs.appendFileSync of anything but (path, buffer) is outside the subset"
        )
    fd = _os.open(_node_path(path, "fs.appendFileSync"), _OPEN_FLAGS["a"] | _BINARY, 0o666)
    try:
        view = memoryview(data)
        while len(view):
            view = view[_os.write(fd, view) :]
    finally:
        _os.close(fd)
    return _JS_UNDEFINED


def read_file_bytes(path):
    """`fs.readFileSync(path)` with no encoding: every byte; a failure is CPython's OSError."""
    with open(_node_path(path, "fs.readFileSync"), "rb") as handle:
        return handle.read()


def _posix_dirname(path):
    """`path.posix.dirname` (lib/path.js), statement for statement. J90-P7B: a path that does not
    end in `/` and whose last `/` is past its second unit is everything before that `/` (the loop
    stops there, at its first slash after a non-slash), found in C."""
    if path and path[-1] != "/":
        cut = path.rfind("/")
        if cut > 1:
            return path[:cut]
    if not path:
        return "."
    has_root = path[0] == "/"
    end = -1
    matched_slash = True
    for i in range(len(path) - 1, 0, -1):
        if path[i] == "/":
            if not matched_slash:
                end = i
                break
        else:
            matched_slash = False
    if end == -1:
        return "/" if has_root else "."
    if has_root and end == 1:
        return "//"
    return path[:end]


def _posix_basename(path):
    """`path.posix.basename` (lib/path.js) with no suffix argument. J90-P7B: a path that does not
    end in `/` is everything after its last `/` (the loop's `end` is its length, `start` one past
    that slash), found in C."""
    if path and path[-1] != "/":
        return path[path.rfind("/") + 1 :]
    start = 0
    end = -1
    matched_slash = True
    for i in range(len(path) - 1, -1, -1):
        if path[i] == "/":
            if not matched_slash:
                start = i + 1
                break
        elif end == -1:
            matched_slash = False
            end = i + 1
    if end == -1:
        return ""
    return path[start:end]


def _win32_dirname(path):
    """`path.win32.dirname` (lib/path.js), statement for statement."""
    length = len(path)
    if length == 0:
        return "."
    root_end = -1
    offset = 0
    code = path[0]
    if length == 1:
        return path if _win32_separator(code) else "."
    if _win32_separator(code):
        root_end = offset = 1
        if _win32_separator(path[1]):
            j = 2
            last = j
            while j < length and not _win32_separator(path[j]):
                j += 1
            if j < length and j != last:
                last = j
                while j < length and _win32_separator(path[j]):
                    j += 1
                if j < length and j != last:
                    last = j
                    while j < length and not _win32_separator(path[j]):
                        j += 1
                    if j == length:
                        return path
                    if j != last:
                        root_end = offset = j + 1
    elif code.isascii() and code.isalpha() and path[1] == ":":
        root_end = 3 if length > 2 and _win32_separator(path[2]) else 2
        offset = root_end
    end = -1
    matched_slash = True
    for i in range(length - 1, offset - 1, -1):
        if _win32_separator(path[i]):
            if not matched_slash:
                end = i
                break
        else:
            matched_slash = False
    if end == -1:
        if root_end == -1:
            return "."
        end = root_end
    return path[:end]


def _win32_basename(path):
    """`path.win32.basename` (lib/path.js) with no suffix argument."""
    start = 0
    end = -1
    matched_slash = True
    if len(path) >= 2 and path[0].isascii() and path[0].isalpha() and path[1] == ":":
        start = 2
    for i in range(len(path) - 1, start - 1, -1):
        if _win32_separator(path[i]):
            if not matched_slash:
                start = i + 1
                break
        elif end == -1:
            matched_slash = False
            end = i + 1
    if end == -1:
        return ""
    return path[start:end]


def path_dirname(path, *_):
    """`path.dirname(path)` (Node's lib/path.js, ported): posix on POSIX, win32 on Windows."""
    if not isinstance(path, str):
        raise TypeError("ts2py: path.dirname of anything but a string is outside the subset")
    return _win32_dirname(path) if _os.name == "nt" else _posix_dirname(path)


def path_basename(path, *rest):
    """`path.basename(path)` (Node's lib/path.js, ported, no suffix)."""
    if rest or not isinstance(path, str):
        raise TypeError("ts2py: path.basename of anything but one string is outside the subset")
    return _win32_basename(path) if _os.name == "nt" else _posix_basename(path)


def _zlib_error(message, code):
    error = _JsError(message)
    error.code = code
    return error


def gzip_sync(data, *rest):
    """`zlib.gzipSync(buffer)`: a gzip member with mtime 0 (`gzip.compress(mtime=0)`). Node's zlib
    (Chromium's) writes a different deflate stream for the same input, which no Python library
    reproduces: only the DECOMPRESSED bytes are compared, a ruled difference (`storage-log`)."""
    if rest or not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("ts2py: zlib.gzipSync of anything but a buffer is outside the subset")
    return _gzip.compress(bytes(data), mtime=0)


def gunzip_sync(data, *rest):
    """`zlib.gunzipSync(buffer)`: every member decompressed and joined, trailing zero padding
    ignored (`gzip.decompress`). Where Node refuses, this refuses with Node's error code: empty or
    truncated input is `Z_BUF_ERROR` (CPython returns b"" for the empty one), a bad header, CRC or
    trailing garbage `Z_DATA_ERROR`. NOT exact on two hand-crafted shapes neither runtime writes
    (J88-RF F5, docs/porting.md): Node ends the input at a zero byte after a member, so a member,
    a zero, then a non-zero byte reads as that member (this refuses it), and a member, a zero, a
    second member reads as the first alone (this reads both)."""
    if rest or not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("ts2py: zlib.gunzipSync of anything but a buffer is outside the subset")
    data = bytes(data)
    if not data:
        raise _zlib_error("unexpected end of file", "Z_BUF_ERROR")
    try:
        return _gzip.decompress(data)
    except EOFError:
        raise _zlib_error("unexpected end of file", "Z_BUF_ERROR") from None
    except (OSError, _zlib.error):
        raise _zlib_error("incorrect header check", "Z_DATA_ERROR") from None


def random_bytes(size, *rest):
    """`crypto.randomBytes(size)`: `os.urandom` (both read the OS CSPRNG)."""
    if rest or isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise TypeError("ts2py: crypto.randomBytes of anything but a count is outside the subset")
    return _os.urandom(size)


def buffer_from(value, encoding=_JS_UNDEFINED, *_):
    """`Buffer.from(string, 'utf8')`: the string's UTF-8, a lone surrogate written as U+FFFD's three
    bytes (EF BF BD), as Node's encoder writes it."""
    if not isinstance(value, str) or encoding not in (_JS_UNDEFINED, "utf8", "utf-8"):
        raise TypeError("ts2py: Buffer.from of anything but a string as utf8 is outside the subset")
    if not value.isascii() and any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        value = "".join("\ufffd" if 0xD800 <= ord(c) <= 0xDFFF else c for c in value)
    return value.encode("utf-8")


def buffer_concat(items, *rest):
    """`Buffer.concat(list)`: one new buffer holding each in order."""
    buffers = isinstance(items, list) and all(
        isinstance(b, (bytes, bytearray, memoryview)) for b in items
    )
    if rest or not buffers:
        raise TypeError(
            "ts2py: Buffer.concat of anything but a list of buffers is outside the subset"
        )
    return b"".join(items)


def buffer_alloc(size, *rest):
    """`Buffer.alloc(size)`: `size` zero bytes, writable in place (`bytearray`)."""
    if rest or isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise TypeError("ts2py: Buffer.alloc of anything but a count is outside the subset")
    return bytearray(size)


def process_env_all():
    """`process.env` as a value (only read): this process's environment as a plain object."""
    return dict(_os.environ)


def process_pid():
    """`process.pid`: this process's id (`os.getpid()`), each runtime its own."""
    return _os.getpid()


# pyfs.ts is the CPython OS seam: each of these is the CPython call it ports (its doc comment).


def py_exists(path):
    """`pyExists` (runtime-ts/src/memory/pyfs.ts): `Path.exists()`, which it ports — 3.12's, whose
    EACCES raises (3.14 answers `False`; `stdlib312.path_exists`)."""
    return _stdlib312().path_exists(_pathlib.Path(path))


def py_is_dir(path):
    """`pyIsDir` (runtime-ts/src/memory/pyfs.ts): `Path.is_dir()`, which it ports — 3.12's
    (`stdlib312.path_is_dir`)."""
    return _stdlib312().path_is_dir(_pathlib.Path(path))


@_functools.lru_cache(maxsize=8192)
def _pure_join(parts):
    return str(_pathlib.PurePath(*parts))


def py_join(*parts):
    """`pyJoin` (runtime-ts/src/memory/pyfs.ts): `str(PurePath(*parts))`, which it ports.

    J89-5: memoised for string parts. `PurePath` is pure (no filesystem access, the same string
    for the same parts on one OS), so the cache answers exactly what it computes; a layer's
    listing joins the same directory and names on every recall (`native.ts`'s `listing`)."""
    if all(type(p) is str for p in parts):
        return _pure_join(parts)
    return str(_pathlib.PurePath(*parts))


def py_parent(path):
    """`pyParent` (runtime-ts/src/memory/pyfs.ts): `str(PurePath(path).parent)`."""
    return str(_pathlib.PurePath(path).parent)


def py_name(path):
    """`pyName` (runtime-ts/src/memory/pyfs.ts): `PurePath(path).name`."""
    return _pathlib.PurePath(path).name


_OSERROR_SUBCLASS = {
    "EACCES": "PermissionError",
    "EAGAIN": "BlockingIOError",
    "ECHILD": "ChildProcessError",
    "EEXIST": "FileExistsError",
    "EINTR": "InterruptedError",
    "EISDIR": "IsADirectoryError",
    "ENOENT": "FileNotFoundError",
    "ENOTDIR": "NotADirectoryError",
    "EPERM": "PermissionError",
    "EPIPE": "BrokenPipeError",
    "ESRCH": "ProcessLookupError",
}


def os_error_class_name(code, *_):
    """`osErrorClassName` (runtime-ts/src/memory/pyfs.ts): the class CPython's `OSError.__new__`
    picks for an errno name, from the same table, `OSError` for any other."""
    return _OSERROR_SUBCLASS.get(code, "OSError") if isinstance(code, str) else "OSError"


# `PyOSError` (pyfs.ts) is the port of CPython's OSError, so `x instanceof PyOSError` is
# `isinstance(x, OSError)`.
PyOSError = OSError


def bantamkit_dir_for(path):
    """`bantamkitDirFor` (runtime-ts/src/memory/store.ts), for a call that compiles its importer
    without store.ts (ts2py's G2 tests; since J89-4b the committed event log imports the compiled
    store): `bantamkit.memory.store.bantamkit_dir_for`, the shim over the generated function, as a
    string or `null`."""
    from ..memory.store import bantamkit_dir_for as _for

    found = _for(_pathlib.Path(path))
    return None if found is None else str(found)


def ensure_bantamkit_gitignore(directory, created, *_):
    """`ensureBantamkitGitignore` (runtime-ts/src/memory/store.ts), for a call that compiles its
    importer without store.ts (see `bantamkit_dir_for`): the shim over the generated function."""
    from ..memory.store import ensure_bantamkit_gitignore as _ensure

    _ensure(_pathlib.Path(directory), created=bool(created))
    return _JS_UNDEFINED


# ---------------------------------------------------------------- J89-2 (#316 G3): usage, retrieval


# `pyRoundFloat9` (runtime-ts/src/pysem.ts), CPython's `round(x, 9)`: moved to the runtime as
# `_js_py_round_float9`, unchanged (#316 G4, J90-P7B), so a compiled build compiles it (a recall
# rounds every score: 10,000 calls at 5,000 facts, each a call into this interpreted module).
py_round_float9 = _js_py_round_float9


def py_log(x, *_):
    """`pyLog` (pysem.ts): CPython's `math.log`, which it ports."""
    return _math.log(_js_num(x))


def py_log1p(x, *_):
    """`pyLog1p` (pysem.ts): CPython's `math.log1p`, which it ports."""
    return _math.log1p(_js_num(x))


def py_pow(x, y, *_):
    """`pyPow` (pysem.ts): CPython's `float ** float`, which it ports, except where `**` overflows:
    there CPython raises OverflowError and Node's `Math.pow` answers Infinity, and since J89-3 this
    answers Infinity too (the base is not negative, so an overflow is +Infinity). Every other
    result, a ZeroDivisionError included, is CPython's. A negative base is refused: Python's answer
    there is a complex number."""
    base = float(_js_num(x))
    if base < 0:
        raise TypeError("ts2py: pyPow of a negative base is outside the subset")
    try:
        return base ** float(_js_num(y))
    except OverflowError:
        return _math.inf


def py_nfkc_lower(text, *_):
    """`pyNfkcLower` (pysem.ts): `unicodedata.normalize('NFKC', text).lower()`, which it ports."""
    return _unicodedata.normalize("NFKC", text).lower()


def py_wordchar(ch, *_):
    """`pyWordchar` (pysem.ts): `unicodedata.category(ch)[0] in 'LNM'` for one code point."""
    return _unicodedata.category(ch)[0] in "LNM"


def _os_text(text):
    """`text` with each lone surrogate as the OS receives it (`_os_char`). J90-P5: a text the strict
    UTF-8 codec encodes holds no surrogate code point (it refuses exactly those), so it is its own
    answer, found at C speed."""
    if text.isascii():
        return text
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "".join(_os_char(c) if 0xD800 <= ord(c) <= 0xDFFF else c for c in text)
    return text


def py_realpath(path, *_):
    """`pyRealpath` (runtime-ts/src/memory/pyfs.ts): `os.path.realpath(path)` (strict=False), which
    it ports (J89-1F), of the path as the OS receives it (the G2 path policy, `_os_char`)."""
    if not isinstance(path, str):
        raise TypeError("ts2py: pyRealpath of anything but a string path is outside the subset")
    return _os.path.realpath(_os_text(path))


_HASHES = {"sha256": _hashlib.sha256, "sha1": _hashlib.sha1}


class Hash(_JsObject):
    """`crypto.createHash('sha256' | 'sha1')`: `update(string, 'utf8')` or `update(buffer)`, then
    `digest('hex')` once."""

    _js_name = "Hash"
    _js_own = frozenset({"update", "digest"})
    _js_own_methods = frozenset({"update", "digest"})

    def __init__(self, algorithm, *_):
        if algorithm not in _HASHES:
            raise TypeError(
                "ts2py: createHash of anything but 'sha256' or 'sha1' is outside the subset"
            )
        object.__setattr__(self, "_js_hash", _HASHES[algorithm]())

    def _live(self):
        if self._js_hash is None:
            raise TypeError("ts2py: a Hash used after digest() is outside the subset")
        return self._js_hash

    def update(self, data, encoding=_JS_UNDEFINED, *_):
        if isinstance(data, (bytes, bytearray, memoryview)) and encoding is _JS_UNDEFINED:
            # J89-5a: a Buffer is hashed as its bytes (queries.ts: a sidecar, a fact file).
            self._live().update(data)
            return self
        if not isinstance(data, str) or encoding not in ("utf8", "utf-8"):
            raise TypeError(
                "ts2py: hash.update of anything but a 'utf8' string or a Buffer is outside the"
                " subset"
            )
        # Node's UTF-8, a lone surrogate as U+FFFD, under the G2 path policy (`_os_char`): a POSIX
        # surrogateescape code point is the real byte it stands for.
        self._live().update(_hash_bytes(data))
        return self

    def digest(self, encoding=_JS_UNDEFINED, *_):
        if encoding != "hex":
            raise TypeError("ts2py: hash.digest of anything but 'hex' is outside the subset")
        out = self._live().hexdigest()
        object.__setattr__(self, "_js_hash", None)
        return out


def _hash_bytes(text):
    """The bytes `Hash.update(text, 'utf8')` hashes: `_os_text(text)` as UTF-8 with
    surrogateescape. J90-P5: a string with no surrogate code point is its own `_os_text` (only a
    surrogate is changed there), and its strict UTF-8 is what surrogateescape writes, so strict
    `encode()` answers it at C speed; the strict codec refuses exactly the surrogates, which take
    the per-character path."""
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        return _os_text(text).encode("utf-8", "surrogateescape")


def hash_hex(algorithm, data):
    """J90-P2: `createHash(algorithm).update(data, 'utf8').digest('hex')` in one call (ts2py
    lowers that chain, `algorithm` a literal `'sha256'` or `'sha1'`, to it): a `str` is hashed as
    its bytes at once (J90-P5: any `str`, through `_hash_bytes`, not only an ASCII one); anything
    else is the three calls, with their refusals."""
    if type(data) is str:
        return _HASHES[algorithm](_hash_bytes(data)).hexdigest()
    return Hash(algorithm).update(data, "utf8").digest("hex")


def create_hash(algorithm, *_):
    """`crypto.createHash(algorithm)`: a `Hash`, `'sha256'` or `'sha1'`."""
    return Hash(algorithm)


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
    # J89-4a: the compiled codec's class and constant, and the hot index's constant.
    if name == "PyScalar":
        from .pyyaml import PyScalar as value
    elif name == "VALID_OUTCOMES":
        from .factfile import VALID_OUTCOMES as value
    elif name == "SKILL_LAYER":
        # J89-6: the skill layer's label, and the two recall-file sentences component.ts says.
        from ..memory.skills import SKILL_LAYER as value
    elif name in ("QUERY_IGNORED", "RECALL_NEEDS_QUERY_OR_FILE"):
        from ..touch import recallfile as _recallfile

        value = getattr(_recallfile, name)
    else:
        value = None
    if value is not None:
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class CountsView(_JsObject):
    """queries.ts's cached row view, declared for its `scan` method only (retrieval's `bm25Rows`).
    J89-5a compiles the class itself (`_generated/queries.py`); this stub is never built: the
    queries shim answers dicts, which the retrieval shim hands over as Maps."""

    _js_name = "CountsView"
    _js_own = frozenset({"scan"})
    _js_own_methods = frozenset({"scan"})

    def __init__(self, *_):
        raise TypeError("ts2py: a CountsView is never built in Python")

    def scan(self, *_):  # pragma: no cover - never constructed
        raise TypeError("ts2py: a CountsView is never built in Python")


# ---------------------------------------------------------------- J89-4a (#316 G3 U2): store


def homedir(*_):
    """`os.homedir()` where store.ts calls it: `str(Path.home())`, what store.py passes in each of
    those places (the hot index, the cold index, the usage ledger)."""
    return str(_pathlib.Path.home())


_WORD_SEARCH = {}


def py_search_word(alternatives, text, *_):
    """`pySearchWord` (runtime-ts/src/pysem.ts): group 1 of
    `re.compile(r'\\b(' + alternatives + r')\\b', re.IGNORECASE).search(text)`, or `null`, which it
    ports (store.py's `_DONE_WORD_RE`). `alternatives` is what `pyCaseless` accepts."""
    pattern = _WORD_SEARCH.get(alternatives)
    if pattern is None:
        if not isinstance(alternatives, str) or not _re.fullmatch(r"[A-Za-z|?]*", alternatives):
            raise _JsError(
                'pyCaseless: only ASCII letters, "|" and "?" are supported: '
                + _json.dumps(alternatives, ensure_ascii=False)
            )
        pattern = _re.compile(r"\b(" + alternatives + r")\b", _re.IGNORECASE)
        _WORD_SEARCH[alternatives] = pattern
    if not isinstance(text, str):
        raise TypeError("ts2py: pySearchWord of anything but a string is outside the subset")
    m = pattern.search(text)
    return None if m is None else m.group(1)


def buffer_byte_length(value, encoding=_JS_UNDEFINED, *_):
    """`Buffer.byteLength(string, 'utf8')`: the length `Buffer.from(string, 'utf8')` has, a lone
    surrogate counted as U+FFFD's three bytes (as `surrogatepass` counts it too)."""
    if not isinstance(value, str) or encoding not in (_JS_UNDEFINED, "utf8", "utf-8"):
        raise TypeError(
            "ts2py: Buffer.byteLength of anything but a string as utf8 is outside the subset"
        )
    if value.isascii():
        return len(value)
    return len(value.encode("utf-8", "surrogatepass"))


class _JsReadMap(_JsMap):
    """A read-only `Map` over a Python dict with string keys, without copying it: what the index
    adapters answer where the TypeScript answers a Map the index holds (`names()`, `segments()`,
    `skipped`). Writing to it is outside the subset."""

    __slots__ = ()

    def __init__(self, data):
        # J90-P: a dict with string keys is already a Map's entries (each key its own tag).
        object.__setattr__(self, "_entries", data)
        object.__setattr__(self, "_keys", None)

    def set(self, key, value):
        raise TypeError("ts2py: writing a Map an index adapter answered is outside the subset")

    def delete(self, key):
        raise TypeError("ts2py: writing a Map an index adapter answered is outside the subset")


def _native_bantam_error(error):
    """A `bantamkit.client.BantamError` the hand-written index raised, as the adapter's
    `BantamError` (a JS Error a compiled `catch` holds) with the same message."""
    # J89-5: the class already built when there is one. `__getattr__` builds a NEW class on every
    # direct call, so a module that imported `BantamError` before the first restatement held a
    # different class, and its `instanceof BantamError` was false for the restated error.
    cls = globals().get("BantamError") or __getattr__("BantamError")
    if isinstance(error, cls):
        return error
    return cls(str(error))


def _native_meta(front):
    """J90-2: the reference's `hotindex._secondary` read of a native frontmatter
    (`load_frontmatter`, `{}` where it refuses or reads no mapping), as values the compiled index
    reads the way the reference read the Python ones: a mapping a dict (its text keys), a list a
    list, a string or None itself, and any other scalar opaque (`factcodec._Opaque`: not a
    string to `strList`, its `str()` to `pyText`, as `[str(x) for x in links]` and `_str_list`
    read them)."""
    import yaml

    from ..memory.factcodec import _Opaque, load_frontmatter

    def held(value):
        if value is None or type(value) is str:
            return value
        if type(value) is list:
            return [held(item) for item in value]
        if type(value) is dict:
            return {key: held(item) for key, item in value.items() if type(key) is str}
        return _Opaque(value)

    try:
        meta = load_frontmatter(front)
    except (ValueError, yaml.YAMLError):
        return {}
    return held(meta) if isinstance(meta, dict) else {}


# J90-2: `hotindex.ts`'s NATIVE_EXTRA_LINE, the `m` flag spelled out (JS's four line terminators).
_NATIVE_EXTRA_LINE = _re.compile("(?:^|[\n\r\u2028\u2029])[ \t]*(?:tags|links):")


def parse_native(path, *_):
    """`parseNative` (runtime-ts/src/storage/nativefact.ts): `divergence.parse_fact`, which it ports
    for the native shape (J89-5; kept by the #228 ruling). The name, description, type and body it
    read, as the object the TypeScript returns; its `MemoryValidationError` (a
    `bantamkit.client.BantamError`) restated as the adapter's `BantamError` with the same message.

    J90-2: and `meta`, which the generated hot index reads a native file's `links` / `tags` from
    when the frontmatter names one of them (`NATIVE_EXTRA_LINE`): what the reference's index read
    them with (`hotindex._secondary`: `load_frontmatter` of the same frontmatter, `_native_meta`),
    `{}` where that refuses. A frontmatter naming neither key is not read twice: its `meta` is
    `{}`, which nothing reads.

    J90-PF: and `front`, the frontmatter's text (the second of `split("---\\n", 2)`'s three parts
    of the file read as `pyReadText` reads it, `""` without them), which the hot index tests for
    `NATIVE_EXTRA_LINE` instead of reading the file a third time; the TypeScript returns the text
    it parsed."""
    from ..client import BantamError as _Native
    from ..memory.divergence import parse_fact

    if not isinstance(path, str):
        raise TypeError("ts2py: parseNative of anything but a string path is outside the subset")
    try:
        stored = parse_fact(path)
    except _Native as error:
        raise _native_bantam_error(error) from None
    meta = {}
    try:
        parts = _pathlib.Path(path).read_text(encoding="utf-8").split("---\n", 2)
    except (OSError, ValueError):
        parts = []
    front = parts[1] if len(parts) == 3 else ""
    if _NATIVE_EXTRA_LINE.search(front):
        meta = _native_meta(front)
    return {
        "name": stored.name,
        "description": stored.description,
        "type": stored.type,
        "body": stored.body,
        "meta": meta,
        "front": front,
    }


_FACTFILE = []


def _factfile(name):
    # The compiled codec, imported on first use and held (J89-4b: the store reads every fact through
    # these, and an import statement per call was a measurable share of a listing).
    if not _FACTFILE:
        from . import factfile as _ff

        _FACTFILE.append(_ff)
    return getattr(_FACTFILE[0], name)


def extra_of(meta, *_):
    """`extraOf` (memory/factfile.ts): `_generated/factfile.py`'s, compiled from it."""
    return _factfile("extra_of")(meta)


def _factcodec():
    # J89-4b: inside the bantamkit package the store reads and writes through
    # `bantamkit.memory.factcodec` (#315's owner ruling: generated + PyYAML fallback); outside it
    # (ts2py's own tests) the compiled codec alone. Imported late: factcodec imports the store.
    try:
        from ..memory import factcodec as codec
    except ImportError:
        return None
    return codec


def format_fact(fact, *_):
    """`formatFact` (factfile.ts): in bantamkit, `factcodec.held_fact_text` -- the compiled
    `format_fact`, then `yaml.safe_dump` where it refuses, over the Python values the fact stands
    for (an opaque value's own object), so the bytes are `fact_text`'s (J89-4b); elsewhere
    `_generated/factfile.py`'s, compiled from it."""
    codec = _factcodec()
    if codec is None:
        return _factfile("format_fact")(fact)
    return codec.held_fact_text(fact)


def lifecycle_of(meta, *_):
    """`lifecycleOf` (factfile.ts): `_generated/factfile.py`'s, compiled from it."""
    return _factfile("lifecycle_of")(meta)


def parse_frontmatter(front, *_):
    """`parseFrontmatter` (factfile.ts): in bantamkit, `factcodec.held_frontmatter` -- what
    `load_frontmatter` reads (the compiled codec, then PyYAML where it refuses), in the codec's
    shape, a PyYAML refusal a JS Error with PyYAML's text (J89-4b); elsewhere
    `_generated/factfile.py`'s, compiled from it."""
    codec = _factcodec()
    if codec is None:
        return _factfile("parse_frontmatter")(front)
    return codec.held_frontmatter(front)


def py_list(value, *_):
    """`pyList` (factfile.ts): `_generated/factfile.py`'s, compiled from it."""
    return _factfile("py_list")(value)


def py_split(text, sep, maxsplit, *_):
    """`pySplit` (factfile.ts): `_generated/factfile.py`'s, compiled from it."""
    return _factfile("py_split")(text, sep, maxsplit)


def py_truthy(value=_JS_UNDEFINED, *_):
    """`pyTruthy` (factfile.ts): `_generated/factfile.py`'s, compiled from it."""
    return _factfile("py_truthy")(value)


def today_local(*args):
    """`todayLocal` (factfile.ts): `_generated/factfile.py`'s, compiled from it."""
    return _factfile("today_local")(*args[:1])


def as_py_os_error(error, fallback_path=_JS_UNDEFINED, fallback_dest=_JS_UNDEFINED, *_):
    """`asPyOSError` (runtime-ts/src/memory/pyfs.ts): what CPython would have raised. Every fs
    adapter raises CPython's own `OSError`, which is answered as it is (a `filename` it lacks taken
    from the fallback, as the port takes it); anything else is re-raised."""
    if not isinstance(error, OSError):
        raise error
    if error.filename is None and isinstance(fallback_path, str):
        error.filename = fallback_path
        if error.filename2 is None and isinstance(fallback_dest, str):
            error.filename2 = fallback_dest
    return error


def matches_md(name, *_):
    """`matchesMd` (pyfs.ts): `fnmatch.fnmatch(name, '*.md')`, which it ports."""
    return _fnmatch.fnmatch(name, "*.md")


def _js_inspect_str(text):
    # `util.inspect` of a string, as Node's ERR_INVALID_ARG_VALUE message quotes the path: single
    # quotes, double when the text holds a `'` and no `"`, a backtick when it holds both and no
    # backtick; the quote, the backslash and C0 controls / DEL escaped (`\n`, `\x00`).
    quote = "'"
    if "'" in text:
        if '"' not in text:
            quote = '"'
        elif "`" not in text and "${" not in text:
            quote = "`"
    named = {"\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r", "\\": "\\\\"}
    out = []
    for c in text:
        if c == quote:
            out.append("\\" + c)
        elif c in named:
            out.append(named[c])
        elif ord(c) < 0x20 or ord(c) == 0x7F:
            out.append(f"\\x{ord(c):02X}")
        else:
            out.append(c)
    return quote + "".join(out) + quote


def _js_received(value):
    # Node's `ERR_INVALID_ARG_VALUE` (lib/internal/errors.js): the inspected value, cut to its
    # first 128 UTF-16 code units and `...` when it is longer.
    inspected = _js_inspect_str(value)
    units = inspected.encode("utf-16-le", "surrogatepass")
    if len(units) > 256:
        return units[:256].decode("utf-16-le", "surrogatepass") + "..."
    return inspected


def _store_path(path, what):
    """J89-4b: a path as `pyfs.ts` hands it to Node's fs, for the store's file calls. The G2 path
    policy (`_node_path`): a lone surrogate CPython cannot encode is the U+FFFD Node's UTF-8
    encoding writes, and a POSIX surrogateescape code point is the real byte it stands for. A NUL
    is what `asPyOSError` makes of Node's `ERR_INVALID_ARG_VALUE` TypeError: an `OSError` with
    errno 0 and strerror `ERR_INVALID_ARG_VALUE: <Node's message>` (its `code` reads as
    undefined, which no store decision tests for), naming the path."""
    if not isinstance(path, str):
        raise TypeError(f"ts2py: {what} of anything but a string path is outside the subset")
    if "\0" in path:
        raise OSError(
            0,
            "ERR_INVALID_ARG_VALUE: The argument 'path' must be a string, Uint8Array, or URL "
            "without null bytes. Received " + _js_received(path),
            path,
        )
    return _os_text(path)


def _lexists_path(path):
    # `pyLexists` swallows every failure (`lstatSync` in a bare try), a NUL included.
    if not isinstance(path, str):
        raise TypeError("ts2py: pyLexists of anything but a string path is outside the subset")
    return None if "\0" in path else _os_text(path)


def py_lexists(path, *_):
    """`pyLexists` (pyfs.ts): `os.path.lexists`, which it ports, of the path as Node's fs receives
    it (`_store_path`); a NUL answers false, as the port's bare catch does."""
    path = _lexists_path(path)
    return False if path is None else _os.path.lexists(path)


def py_mkdir_parents(path, *_):
    """`pyMkdirParents` (pyfs.ts): `Path.mkdir(parents=True, exist_ok=True)` (`_store_path`)."""
    _pathlib.Path(_store_path(path, "pyMkdirParents")).mkdir(parents=True, exist_ok=True)
    return _JS_UNDEFINED


def py_mtime_date(path, *_):
    """`pyMtimeDate` (pyfs.ts): `date.fromtimestamp(Path(path).stat().st_mtime).isoformat()`."""
    # Local time, as the reference's `date.fromtimestamp` (and `date.today()`) is.
    mtime = _pathlib.Path(_store_path(path, "pyMtimeDate")).stat().st_mtime
    return _datetime.date.fromtimestamp(mtime).isoformat()  # noqa: DTZ012


def py_parents(path, *_):
    """`pyParents` (pyfs.ts): `PurePath.parents`, as strings."""
    return [str(p) for p in _pathlib.PurePath(path).parents]


class PyUnicodeDecodeError(_JsError):
    """`PyUnicodeDecodeError` (pyfs.ts): CPython's `UnicodeDecodeError` as a JS Error, its message
    `str()` of the one CPython raised."""

    _js_name = "PyUnicodeDecodeError"
    name = "UnicodeDecodeError"


def py_read_text(path, *_):
    """`pyReadText` (pyfs.ts): `Path.read_text(encoding='utf-8')`, which it ports; a decode failure
    is `PyUnicodeDecodeError` with CPython's message. J90-P7B: a POSIX path `PurePath` leaves as it
    is (`_pure_as_is`) is opened as `read_text` opens it, `io.open(path, encoding='utf-8')`, without
    building the `Path`."""
    try:
        path = _store_path(path, "pyReadText")
        if _pure_as_is(path):
            # `io.open`, as `Path.open` calls it: a spy on `builtins.open` sees no more than before.
            with _io.open(path, encoding="utf-8") as handle:  # noqa: UP020
                return handle.read()
        return _pathlib.Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise PyUnicodeDecodeError(str(error)) from None


def _pure_as_is(path):
    """`str(PurePath(path)) == path`, by a sufficient test (J90-P7B): POSIX, not empty, and no part
    `PurePosixPath` rewrites (a doubled `/`, a `.` part, a trailing `/`). Any other path is False,
    and goes through `Path`."""
    return (
        _os.name != "nt"
        and path != ""
        and path != "."
        and path[-1] != "/"
        and "//" not in path
        and "/./" not in path
        and not path.startswith("./")
        and not path.endswith("/.")
    )


def py_replace(source, target, *_):
    """`pyReplace` (pyfs.ts): `os.replace`, which it ports."""
    _os.replace(_store_path(source, "pyReplace"), _store_path(target, "pyReplace"))
    return _JS_UNDEFINED


def py_scandir_names(directory, *_):
    """`pyScandirNames` (pyfs.ts): `os.scandir(directory)` reduced to names, in its order."""
    with _os.scandir(_store_path(directory, "pyScandirNames")) as entries:
        return [entry.name for entry in entries]


def py_scandir_probe(directory, *_):
    """`pyScandirProbe` (pyfs.ts): `with os.scandir(directory): pass`."""
    with _os.scandir(_store_path(directory, "pyScandirProbe")):
        pass
    return _JS_UNDEFINED


def py_suffix(path, *_):
    """`pySuffix` (pyfs.ts): `PurePath.suffix` — 3.12's, where `'a.'` has none
    (`stdlib312.path_suffix`)."""
    return _stdlib312().path_suffix(path)


def py_unlink(path, *_):
    """`pyUnlink` (pyfs.ts): `Path.unlink()`."""
    _pathlib.Path(_store_path(path, "pyUnlink")).unlink()
    return _JS_UNDEFINED


def py_write_text(path, text, *_):
    """`pyWriteText` (pyfs.ts): `Path.write_text(text, encoding='utf-8')`."""
    _pathlib.Path(_store_path(path, "pyWriteText")).write_text(text, encoding="utf-8")
    return _JS_UNDEFINED


def py_write_text_atomic(path, text, *_):
    """`pyWriteTextAtomic` (pyfs.ts), the port of store.py's `_write_text_atomic` (J89-1F), carried
    here statement for statement: `<path>.<pid>.<8 hex>.tmp` opened `x`, the buffered writer writes
    every byte, `os.replace` onto `path`; on any failure the temp is unlinked and the error goes on
    up, so `path` holds the old bytes or the new ones, never a prefix."""
    path = _store_path(path, "pyWriteTextAtomic")
    tmp = _pathlib.Path(f"{path}.{_os.getpid()}.{_secrets.token_hex(4)}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as fh:
            fh.write(text)
        tmp.replace(path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return _JS_UNDEFINED


def py_os_error_text(error, *_):
    """`pyOSErrorText` (pyfs.ts, J89-4b): `str(e)` of the CPython `OSError`, which `PyOSError` ports
    and whose `message` the port's constructor builds as `OSError.__str__` does."""
    if not isinstance(error, OSError):
        raise TypeError("ts2py: pyOSErrorText of anything but an OSError is outside the subset")
    return str(error)


def py_os_error_strerror(error, *_):
    """`pyOSErrorStrerror` (pyfs.ts, J89-4b): the CPython `OSError`'s `strerror`, as the reference's
    f-string prints it (an `OSError` built without one prints `None`; a port's always has one)."""
    if not isinstance(error, OSError):
        raise TypeError("ts2py: pyOSErrorStrerror of anything but an OSError is outside the subset")
    return str(error.strerror)


def sorted_path_names(names, *_):
    """`sortedPathNames` (pyfs.ts): `sorted(directory / name for name in names)` reduced to the
    names: stable, by `os.path.normcase` of each, by code point."""
    return sorted(names, key=_os.path.normcase)


# ---------------------------------------------------------------- J89-5a (#316 G3 U3): queries


class PyJSONDecodeError(_JsError):
    """`PyJSONDecodeError` (runtime-ts/src/pyjson.ts): CPython's `json.JSONDecodeError` as a JS
    Error, its message `str()` of the one CPython raised."""

    _js_name = "PyJSONDecodeError"
    name = "PyJSONDecodeError"


class _TaggedDict:
    # The marker that closes a dict in `_tagged`: its values are converted (they were pushed after
    # it), so the Map is built from them.
    pass


def _tagged_close(into, at):
    keys, values = into[at]
    held = _JsMap()
    held._entries = dict(zip(keys, values, strict=True))
    into[at] = {"t": "dict", "v": held}


def _tagged(value):
    # A `json.loads` value as the TypeScript's `PyValue`: `{t, v}`, ints as BigInts (the int/float
    # kind is what the tag keeps), dicts as Maps in the dict's order. Iterative, so a document
    # `json.loads` read is converted at any depth it reached.
    out = [None]
    work = [(value, out, 0)]
    while work:
        item, into, at = work.pop()
        if item is _TaggedDict:
            _tagged_close(into, at)
            continue
        if item is None:
            into[at] = {"t": "null"}
        elif item is True or item is False:
            into[at] = {"t": "bool", "v": item}
        elif type(item) is int:
            into[at] = {"t": "int", "v": _JsBigInt(item)}
        elif type(item) is float:
            into[at] = {"t": "float", "v": item}
        elif type(item) is str:
            into[at] = {"t": "str", "v": item}
        elif type(item) is list:
            items = [None] * len(item)
            into[at] = {"t": "list", "v": items}
            work.extend((x, items, i) for i, x in enumerate(item))
        else:
            keys = list(item)
            values = [None] * len(keys)
            into[at] = (keys, values)
            work.append((_TaggedDict, into, at))
            work.extend((item[k], values, i) for i, k in enumerate(keys))
    return out[0]


#: J89-5e: the deepest nesting `parse_json` reads, counted as `JSON.parse` nests (each array or
#: object one level, the outermost included: `[]` is 1, `[[]]` is 2). CPython's own limit is not
#: one number: 3.11's C scanner is bounded by `sys.getrecursionlimit()` less the caller's frames
#: (991 at the top level, 978 on the MCP and hook paths, measured), 3.12 and 3.13 read to ~9,994
#: and 3.14 has no fixed limit. A fixed depth below all of them keeps Python's answer off the
#: CPython version and its recursion limit (ruled: docs/porting.md, the J89-5d/J89-5e row).
_PARSE_JSON_DEPTH = 512

# A JSON string (an unterminated one runs to the end, as `json.loads` would refuse it there) or
# one bracket: what `_json_too_deep` steps over to count nesting.
_JSON_NESTING = _re.compile(r'"(?:[^"\\]+|\\.)*"?|[\[\]{}]', _re.DOTALL)


def _json_too_deep(text):
    """True when `json.loads(text)`, reading without a depth limit, would open an array or object
    `_PARSE_JSON_DEPTH + 1` deep: the text is well-formed up to that opener, which is where a
    recursive descent with `_PARSE_JSON_DEPTH` levels of stack stops. A text that is malformed
    before it is not too deep; `json.loads` refuses it with its own message. Never recurses."""
    if text.count("[") + text.count("{") <= _PARSE_JSON_DEPTH:
        return False
    depth = 0
    for match in _JSON_NESTING.finditer(text):
        token = match.group()
        if token[0] == '"':
            continue
        if token in "[{":
            depth += 1
            if depth > _PARSE_JSON_DEPTH:
                cut = match.start()
                break
        else:
            depth -= 1
            if depth < 0:
                return False
    else:
        return False
    # The opener at `cut` is reached exactly when the text before it is a well-formed prefix that
    # wants a value there: `json.loads` of that prefix stops at its end with `Expecting value`.
    try:
        _stdlib312().json_loads(text[:cut])
    except _json.JSONDecodeError as error:
        return error.msg == "Expecting value" and error.pos == cut
    except RecursionError:
        # Not reached on a supported CPython (the prefix is at most 512 deep); were it, the whole
        # text would not read either.
        return True
    return False


def parse_json(text, *_):
    """`parseJson` (runtime-ts/src/pyjson.ts): `json.loads(text)`, which it ports, answered as the
    tagged `PyValue` the TypeScript returns; a malformed text is `PyJSONDecodeError` with CPython's
    message, so a compiled `catch` sees it.

    A text nested past `_PARSE_JSON_DEPTH` (512) is the RangeError `Maximum call stack size
    exceeded`, which is what `parseJson`, a recursive descent, throws past its stack: a compiled
    `catch` sees it as it sees Node's (J89-5d, ruled: a crash is a bug; J89-5e, ruled: the depth is
    Python's own, so the answer does not move with the CPython version or its recursion limit).
    Between 512 and Node's stack (1,562 cold) the two differ, by ruling: docs/porting.md, the
    J89-5d/J89-5e row. `RecursionError` stays mapped the same way, as the backstop."""
    if not isinstance(text, str):
        raise TypeError("ts2py: parseJson of anything but a string is outside the subset")
    if _json_too_deep(text):
        raise _JsRangeError("Maximum call stack size exceeded")
    try:
        value = _stdlib312().json_loads(text)
    except RecursionError:
        raise _JsRangeError("Maximum call stack size exceeded") from None
    except ValueError as error:
        raise PyJSONDecodeError(str(error)) from None
    return _tagged(value)


def _untagged(value):
    # A `PyValue` as the Python value `json.dumps` is handed (iterative, as `_tagged`).
    out = [None]
    work = [(value, out, 0)]
    while work:
        item, into, at = work.pop()
        if item is _TaggedDict:
            keys, values = into[at]
            into[at] = dict(zip(keys, values, strict=True))
            continue
        tag = item["t"]
        if tag == "null":
            into[at] = None
        elif tag in ("bool", "float", "str"):
            into[at] = item["v"]
        elif tag == "int":
            into[at] = item["v"].value
        elif tag == "list":
            items = [None] * len(item["v"])
            into[at] = items
            work.extend((x, items, i) for i, x in enumerate(item["v"]))
        elif tag == "dict":
            pairs = list(item["v"])
            keys = [k for k, _ in pairs]
            values = [None] * len(pairs)
            into[at] = (keys, values)
            work.append((_TaggedDict, into, at))
            work.extend((v, values, i) for i, (_, v) in enumerate(pairs))
        else:
            raise TypeError("ts2py: dumpJson of anything but a PyValue is outside the subset")
    return out[0]


_DUMP_OPTIONS = frozenset({"indent", "sortKeys", "ensureAscii", "separators"})


def dump_json(value, options=_JS_UNDEFINED, *_):
    """`dumpJson` (runtime-ts/src/pyjson.ts): `json.dumps` with the options it ports (`indent`,
    `sort_keys`, `ensure_ascii`, `separators`; `allow_nan` and float `repr` as CPython's)."""
    if options is _JS_UNDEFINED:
        options = {}
    if not isinstance(options, dict) or not set(options) <= _DUMP_OPTIONS:
        raise TypeError("ts2py: dumpJson with those options is outside the subset")

    def opt(name, default):
        got = options.get(name, _JS_UNDEFINED)
        return default if got is _JS_UNDEFINED or got is None else got

    separators = opt("separators", None)
    return _json.dumps(
        _untagged(value),
        indent=opt("indent", None),
        sort_keys=opt("sortKeys", False) is True,
        ensure_ascii=opt("ensureAscii", True) is not False,
        separators=None if separators is None else (separators[0], separators[1]),
    )


def encode_basestring_ascii(text, *_):
    """`encodeBasestringAscii` (runtime-ts/src/pyjson.ts): CPython's
    `json.encoder.encode_basestring_ascii`, which it ports."""
    if not isinstance(text, str):
        raise TypeError(
            "ts2py: encodeBasestringAscii of anything but a string is outside the subset"
        )
    return _json.encoder.encode_basestring_ascii(text)


def py_decode_utf8(data, *_):
    """`pyDecodeUtf8` (runtime-ts/src/memory/pyfs.ts): `bytes.decode('utf-8')`, strict, a leading
    BOM kept, which it ports; a refusal is `PyUnicodeDecodeError` with CPython's message."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("ts2py: pyDecodeUtf8 of anything but a Buffer is outside the subset")
    try:
        return bytes(data).decode("utf-8")
    except UnicodeDecodeError as error:
        raise PyUnicodeDecodeError(str(error)) from None


def _node_utf8(text):
    # Node's UTF-8 encoding of a JS string: a surrogate pair is its character, a lone surrogate
    # the U+FFFD (EF BF BD) the encoder writes for it.
    try:
        # Strict UTF-8 refuses exactly the surrogate code points; anything else is Node's bytes.
        return text.encode("utf-8")
    except UnicodeEncodeError:
        pass
    units = text.encode("utf-16-le", "surrogatepass")
    return units.decode("utf-16-le", "replace").encode("utf-8")


def write_file_sync(path, data, options=_JS_UNDEFINED, *rest):
    """`fs.writeFileSync(path, string, 'utf8')`: opened `w` (O_TRUNC | O_CREAT | O_WRONLY, mode
    0o666 under the umask, binary), every byte of the string's UTF-8 written (Node loops until it
    is), closed. A Buffer, another encoding or an options object is outside the subset."""
    if rest or not isinstance(data, str) or options not in ("utf8", "utf-8"):
        raise TypeError(
            "ts2py: fs.writeFileSync of anything but (path, string, 'utf8') is outside the subset"
        )
    payload = _node_utf8(data)
    fd = _os.open(_node_path(path, "fs.writeFileSync"), _OPEN_FLAGS["w"] | _BINARY, 0o666)
    try:
        view = memoryview(payload)
        while len(view):
            view = view[_os.write(fd, view) :]
    finally:
        _os.close(fd)
    return _JS_UNDEFINED


# ------------------------------------------------------------ J89-5b (#316 G3 U3): layers
#
# The grants config is read by PyYAML, as `load_grants` always read it: the orchestrator's ruling
# on J89-5's stop (option b), following the owner's #315 ruling for fact files. `firstTokenTab`
# and `parseConfigDocument` (runtime-ts/src/memory/grantconfig.ts) are the port's reduction of
# `yaml.safe_load`; here they are `yaml.safe_load` itself.

#: PyYAML's own wording for a tab where a token would start (job65/#158), matched exactly as the
#: reference's `_TAB_PROBLEM` is, so a PyYAML that rewords it falls back to the generic sentence.
_TAB_PROBLEM = "found character '\\t' that cannot start any token"

# One text's `yaml.safe_load` outcome, `(text, value, error)`: `loadGrants` asks `firstTokenTab`
# and then `parseConfigDocument` of the same text, and the reference loads it once.
_GRANT_CONFIG = []

#: J89-5d: the reason `load_grants` gives for a config nested past CPython's recursion limit.
_GRANT_TOO_DEEP = "the document is nested too deeply to read"


class _GrantConfigUnreadable(Exception):
    """A config `yaml.safe_load` raised on with something other than a `yaml.YAMLError` (J89-5d):
    refused through the same `invalid memory config <path>: <reason>` sentence."""


def _grant_config_load(text):
    if _GRANT_CONFIG and _GRANT_CONFIG[0][0] == text:
        return _GRANT_CONFIG[0][1], _GRANT_CONFIG[0][2]
    import yaml

    value, error = None, None
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as e:
        error = e
    except RecursionError:
        # J89-5d (ruled: a crash is a bug): a document nested past CPython's limit is refused by
        # name, as every other config refusal is, instead of leaving `load_grants` raw.
        error = _GrantConfigUnreadable(_GRANT_TOO_DEEP)
    except ValueError as e:
        # J89-5d: a scalar PyYAML resolves but cannot construct (an implicit timestamp such as
        # `2001-02-30` or `25:00:00`, an int past CPython's 4,300-digit limit) is refused with
        # CPython's own reason, as a `yaml.YAMLError` is -- 3.12's, which the port spells (J90-P8F:
        # 3.14 rewrote the timestamp sentences, gh-109798; `stdlib312.pin_datetime_error`).
        error = _GrantConfigUnreadable(str(_stdlib312().pin_datetime_error(e)))
    _GRANT_CONFIG[:] = [(text, value, error)]
    return value, error


def first_token_tab(text, *_):
    """`firstTokenTab` (grantconfig.ts): the 1-based `[line, column]` of the tab PyYAML refused,
    read off its `ScannerError`'s mark as the reference's `_token_tab` reads it, or null. An
    exception that is not a `yaml.YAMLError` (the reference never caught one) is raised here, out
    of `loadGrants`, as it left `load_grants`."""
    if not isinstance(text, str):
        raise TypeError("ts2py: firstTokenTab of anything but a string is outside the subset")
    import yaml.scanner

    try:
        _, error = _grant_config_load(text)
    except BaseException:
        _GRANT_CONFIG.clear()
        raise
    if not isinstance(error, yaml.scanner.ScannerError) or error.problem != _TAB_PROBLEM:
        return None
    mark = error.problem_mark
    if mark is None:
        return None
    return [mark.line + 1, mark.column + 1]


def _config_item(item):
    # J89-5d: a string holding NUL (PyYAML decodes `"\0"`) names no path, so it is not one: the
    # validator refuses the list (`extra_stores must be a list of paths`) where `Path.resolve`
    # raised a raw `ValueError` out of `load_grants`.
    if isinstance(item, str) and "\0" not in item:
        return {"kind": "str", "value": item}
    return {"kind": "other", "value": None}


def parse_config_document(text, *_):
    """`parseConfigDocument` (grantconfig.ts): `yaml.safe_load(text)` as the `ConfigDocument` the
    compiled validator reads (the adapter row says how each shape converts); a `yaml.YAMLError` is
    a `_JsError` whose message is `str(e)`, the text `load_grants` interpolates."""
    if not isinstance(text, str):
        raise TypeError("ts2py: parseConfigDocument of anything but a string is outside the subset")
    value, error = _grant_config_load(text)
    _GRANT_CONFIG.clear()
    if error is not None:
        raise _JsError(str(error))
    if value is None:
        return {"kind": "null"}
    if not isinstance(value, dict):
        return {"kind": "other"}
    entries = _JsMap()
    for key, entry in value.items():
        if type(key) is not str:
            continue
        if isinstance(entry, list):
            entries.set(key, {"kind": "seq", "items": [_config_item(i) for i in entry]})
        else:
            entries.set(key, {"kind": "other", "value": None})
    return {"kind": "mapping", "entries": entries}


def py_is_file(path, *_):
    """`pyIsFile` (pyfs.ts): `Path.is_file()`, which it ports — 3.12's (`stdlib312.path_is_file`)."""
    return _stdlib312().path_is_file(_pathlib.Path(path))


def py_resolve(path, *_):
    """`pyResolve` (pyfs.ts): `str(Path(path).resolve())`, which it ports (`strict=False`) — 3.12's,
    whose symlink loop raises `RuntimeError` (`stdlib312.path_resolve`)."""
    return str(_stdlib312().path_resolve(path))


def py_stat_is_dir(path, *_):
    """`pyStatIsDir` (pyfs.ts): `stat.S_ISDIR(os.stat(path).st_mode)`, unguarded."""
    return _stat.S_ISDIR(_os.stat(_pathlib.Path(path)).st_mode)


def py_cwd(*_):
    """`pyCwd` (pyfs.ts): `str(Path.cwd())`."""
    return str(_pathlib.Path.cwd())


def py_expanduser(path, *_):
    """`pyExpanduser` (pyfs.ts): `str(Path(path).expanduser())`, its `RuntimeError` included."""
    return str(_pathlib.Path(path).expanduser())


def py_is_absolute(path, *_):
    """`pyIsAbsolute` (pyfs.ts): `PurePath(path).is_absolute()` — 3.12's, where a Windows path is
    absolute only with a drive AND a root (`stdlib312.win_is_absolute`)."""
    if _os.name == "nt":
        return _stdlib312().win_is_absolute(path)
    return _pathlib.PurePath(path).is_absolute()


# J89-5c (#316 G3 U3: memory/dream). `dreamre.ts`'s patterns are ports of `dream.py`'s, so these are
# `dream.py`'s own CPython patterns, unchanged.
_DREAM_RELATIVE = _re.compile(
    r"\b(?P<simple>today|tonight|yesterday|tomorrow)\b"
    r"|\b(?P<now>right\s+now|just\s+now)\b"
    r"|\b(?P<count>\d+)\s+(?P<unit>days?|weeks?)\s+ago\b",
    _re.IGNORECASE,
)
_DREAM_UNRESOLVED = _re.compile(
    r"\brecently\b"
    r"|\b(?:last|this|next)\s+(?:week|month|year|quarter|night|session|time)\b"
    r"|\b\d+\s+(?:months?|years?)\s+ago\b",
    _re.IGNORECASE,
)
_DREAM_STAMPED = _re.compile(r"\s*\(\d{4}-\d{2}-\d{2}\)")
_DREAM_BULLET = _re.compile(r"^(?:[-*+]\s+|#+\s+)")
_DREAM_SLOT = _re.compile(r"^(?P<subject>[^:\n]{1,60}?)\s*:\s*(?P<value>\S.*)$")
_DREAM_SPACES = _re.compile(r"\s+")


def _dream_text(name, text):
    if not isinstance(text, str):
        raise TypeError(f"ts2py: {name} of anything but a string is outside the subset")
    return text


def py_relative_scan(body, *_):
    """`pyRelativeScan` (dreamre.ts): `_RELATIVE.finditer(body)`, each match with the body from the
    previous match's end to its own (`lead`), whether `_STAMPED.match(body[end:])` holds, and its
    groups; the body after the last match is `tail`."""
    body = _dream_text("pyRelativeScan", body)
    matches = []
    position = 0
    for m in _DREAM_RELATIVE.finditer(body):
        end = m.end()
        matches.append(
            {
                "lead": body[position:end],
                "term": m.group(0),
                "stamped": _DREAM_STAMPED.match(body, end) is not None,
                "simple": m.group("simple"),
                "now": m.group("now") is not None,
                "digits": m.group("count"),
                "unit": m.group("unit"),
            }
        )
        position = end
    return {"matches": matches, "tail": body[position:]}


def py_unresolved_terms(body, *_):
    """`pyUnresolvedTerms` (dreamre.ts): every `_UNRESOLVED` match's text, in order."""
    body = _dream_text("pyUnresolvedTerms", body)
    return [m.group(0) for m in _DREAM_UNRESOLVED.finditer(body)]


def py_slot_groups(text, *_):
    """`pySlotGroups` (dreamre.ts): `_SLOT.match(_BULLET.sub('', text))` as `[subject, value]`, or
    `null`."""
    text = _dream_text("pySlotGroups", text)
    m = _DREAM_SLOT.match(_DREAM_BULLET.sub("", text))
    return None if m is None else [m.group("subject"), m.group("value")]


def py_sub_spaces(text, *_):
    """`pySubSpaces` (dreamre.ts): `re.sub(r"\\s+", " ", text)`."""
    return _DREAM_SPACES.sub(" ", _dream_text("pySubSpaces", text))


def py_int_digits(text, *_):
    """`pyIntDigits` (dreamre.ts): CPython's `int(text)` (its `ValueError` included, but for a run
    of digits past the int-string limit), as a double; past the largest double, infinity."""
    text = _dream_text("pyIntDigits", text)
    try:
        n = int(text)
    except ValueError:
        # J89-5d (ruled: a crash is a bug): a run of digits past CPython's int-string limit
        # (`sys.get_int_max_str_digits()`, 4,300) is read as `pyIntDigits` reads it, the limit
        # left where it is: its leading zeros dropped, its value past the largest double infinity.
        if not text.isdecimal():
            raise
        digits = "".join(str(_unicodedata.decimal(ch)) for ch in text).lstrip("0")
        if len(digits) > 400:
            return _math.inf
        n = int(digits or "0")
    try:
        return float(n)
    except OverflowError:
        return _math.inf


def format_fixed3(value, *_):
    """`formatFixed3` (dreamre.ts): `f"{value:.3f}"`, no sign on a value that rounds to zero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("ts2py: formatFixed3 of anything but a number is outside the subset")
    x = float(value)
    if x != x:
        return "nan"
    if x in (_math.inf, -_math.inf):
        return "inf" if x > 0 else "-inf"
    text = format(x, ".3f")
    if text.startswith("-") and not text.strip("-0."):
        text = text[1:]
    return text


# ---------------------------------------------------------------- J89-6 (#316 G3 U4): component


def _posix_resolve(paths):
    """`path.posix.resolve` (lib/path.js), statement for statement."""
    resolved = ""
    absolute = False
    i = len(paths) - 1
    while i >= -1 and not absolute:
        path = paths[i] if i >= 0 else _os.getcwd()
        i -= 1
        if not path:
            continue
        resolved = f"{path}/{resolved}"
        absolute = path[0] == "/"
    resolved = _posix_normalized(resolved, not absolute)
    if absolute:
        return "/" + resolved
    return resolved if resolved else "."


def path_resolve(*paths):
    """`path.resolve(...paths)` (Node's `lib/path.js`): `path.posix.resolve`, ported statement for
    statement; on Windows, a drive-absolute last path normalised without its trailing separator, and
    anything else outside the subset."""
    for path in paths:
        if not isinstance(path, str):
            raise TypeError("ts2py: path.resolve of anything but strings is outside the subset")
    if _os.name != "nt":
        return _posix_resolve(list(paths))
    last = paths[-1] if paths else ""
    if len(last) < 3 or last[1] != ":" or not _win32_separator(last[2]):
        raise TypeError(
            "ts2py: path.resolve on win32 of a path not drive-absolute is outside the subset"
        )
    out = _win32_normalize(last)
    return out[:-1] if len(out) > 3 and _win32_separator(out[-1]) else out


def py_home(*_):
    """`pyHome` (pyfs.ts): `Path.home()`, as a string."""
    return str(_pathlib.Path.home())


def py_lower(text, *_):
    """`pyLower` (pysem.ts): `toLowerCase()`, the runtime's own (J89-7b). `str.lower()` was the
    reference's call, but CPython 3.11 to 3.13 have no lowercase for the 55 code points the
    runtime maps first (`'\u1c89x'.lower()` keeps U+1C89; Node lowers it to U+1C8A), and a final
    sigma beside a code point their table classifies apart from Node's; the runtime answers as
    Node does on every one, so `normalize_name` does too."""
    if not isinstance(text, str):
        raise TypeError("ts2py: pyLower of anything but a string is outside the subset")
    return _js_m_toLowerCase(text)


def _store_shim():
    # The store shim's conversions (a `Fact` / `Pool` as the generated store holds one), imported
    # on first use: the shim imports this module.
    from ..memory import store as shim

    return shim


def _python_set(values):
    """A compiled `Set` (or any iterable of names) as the Python set the reference takes."""
    return frozenset() if values is _JS_UNDEFINED or values is None else frozenset(values)


def _skipped_list(skipped):
    return None if skipped is _JS_UNDEFINED else skipped


class SkillStore(_JsObject):
    """`SkillStore` (runtime-ts/src/memory/skills.ts): `bantamkit.memory.skills.SkillStore`, which
    it ports (#206 X8), with the TypeScript spelling of the methods component.ts calls; facts and
    pools as the generated store's shapes, `root` as a string."""

    _js_name = "SkillStore"
    _js_own = frozenset(
        {"archivedRecall", "candidates", "count", "lookup", "offer", "pool", "resolve", "root"}
    )
    _js_own_methods = frozenset(
        {"archivedRecall", "candidates", "count", "lookup", "offer", "pool", "resolve"}
    )

    def __init__(self, roots, home=None, *_):
        from ..memory.skills import SkillStore as _Skills

        if home is _JS_UNDEFINED:
            home = None
        self._bind(_Skills(list(roots), home))

    def _bind(self, skills):
        object.__setattr__(self, "_js_skill", skills)
        object.__setattr__(self, "root", str(skills.root))

    @classmethod
    def _of(cls, skills):
        """This adapter over a hand-written `SkillStore` already built (a caller's own layer)."""
        adapter = cls.__new__(cls)
        adapter._bind(skills)
        return adapter

    def _call(self, method, *args):
        from ..client import BantamError as _Native

        try:
            return getattr(self._js_skill, method)(*args)
        except _Native as error:
            raise _native_bantam_error(error) from None

    def candidates(self, skipped=_JS_UNDEFINED, shadow=_JS_UNDEFINED, *_):
        got = self._call("candidates", _skipped_list(skipped), _python_set(shadow))
        fact_in = _store_shim()._fact_in
        return [fact_in(f) for f in got]

    def offer(self, *_):
        # Opaque to the compiled component, which only hands it back to `fireOn`.
        return self._call("offer")

    def count(self, *_):
        return self._call("count")

    def pool(self, q, skipped=_JS_UNDEFINED, shadow=_JS_UNDEFINED, every_row=False, *_):
        if every_row is _JS_UNDEFINED:
            every_row = False
        got = self._call(
            "pool", list(q), _skipped_list(skipped), _python_set(shadow), bool(every_row)
        )
        return _store_shim()._pool_in(got)

    def resolve(self, pool, row, *_):
        return pool["facts"][row]

    def lookup(self, name, stamp=False, skipped=_JS_UNDEFINED, *_):
        if stamp is _JS_UNDEFINED:
            stamp = False
        got = self._call("lookup", name, stamp, _skipped_list(skipped))
        return None if got is None else _store_shim()._fact_in(got)

    def archivedRecall(self, query, k, exclude=_JS_UNDEFINED, *_):
        got = self._call("archived_recall", query, k, [] if exclude is _JS_UNDEFINED else exclude)
        fact_in = _store_shim()._fact_in
        return [fact_in(f) for f in got]


def is_skill_store(store, *_):
    """`isSkillStore` (skills.ts): `store instanceof SkillStore`, of the adapter class above."""
    return isinstance(store, SkillStore)


def skill_roots(project_store, home, *_):
    """`skillRoots` (skills.ts): `skills.skill_roots`, its paths as strings."""
    from ..memory.skills import skill_roots as _roots

    return [str(p) for p in _roots(project_store, home)]


def triggers_enabled(*_):
    """`triggersEnabled` (skills.ts): `skills.triggers_enabled`, read every call."""
    from ..memory.skills import triggers_enabled as _enabled

    return _enabled()


def fire_on(query, shown, offer, *_):
    """`fireOn` (skills.ts): `SkillStore.fire(tokenize_label(frame(query)), shown, offer)`, the
    fired fact as the generated store's shape."""
    from ..memory.skills import SkillStore as _Skills
    from ..replynative import frame
    from ..skillmine import tokenize_label

    fact = _Skills.fire(tokenize_label(frame(query)), set(shown), offer)
    return None if fact is None else _store_shim()._fact_in(fact)


def load_skill(name, *_):
    """`loadSkill` (assets.ts): `bantamkit.assets.load_skill`."""
    from ..assets import load_skill as _load

    return _load(name)


def via_enabled(*_):
    """`viaEnabled` (touch/context.ts): `touch.context.via_enabled`, read every call."""
    from ..touch import context as _context

    return _context.via_enabled()


def via_pick(graph, paths, exclude, weigh, *_):
    """`viaPick` (touch/context.ts): `touch.context.via_pick`; `(fact, path)` as an array."""
    from ..touch import context as _context

    got = _context.via_pick(graph, list(paths), set(exclude), weigh)
    return None if got is None else [got[0], got[1]]


def via_label(path, graph, *_):
    """`viaLabel` (touch/context.ts): `touch.context.via_label`."""
    from ..touch import context as _context

    return _context.via_label(path, graph)


def file_links(file, layers, *_):
    """`fileLinks` (touch/recallfile.ts): the repository half of the reference's `recall_file`,
    its calls in its order, on the hand-written touch modules; the layers as the Python layers."""
    from ..memory.component import _python_layers
    from ..memory.store import utc_now
    from ..storage.tiers import current_cwd
    from ..touch import recallfile as rf
    from ..touch.graph import TouchGraph
    from ..touch.log import TouchLog
    from ..touch.refs import FileSet, shortest_suffix
    from ..touch.repo import find_repo, ls_files

    def ended(said):
        return {"said": said, "history": "", "names": [], "none": ""}

    cwd = current_cwd()
    repo = None if cwd is None else find_repo(cwd)
    if repo is None:
        return ended(rf.FILE_NOT_IN_REPO)
    home = _pathlib.Path.home()
    graph = TouchGraph(home, repo).load(_python_layers(layers))
    if graph is None:
        graph = {"files": ls_files(repo) or [], "strong": {}, "weak": {}}
    fs = FileSet([f for f in graph["files"] if isinstance(f, str)])
    want = rf.normalize_file(file)
    found = fs.matches(want)
    if not found:
        return ended(rf.FILE_UNKNOWN.format(file=want))
    if len(found) > 1:
        return ended(rf.ambiguous(want, found, fs))
    path = found[0]
    suffix = shortest_suffix(path, fs)
    history = rf.history_line(repo, path, TouchLog(home, repo.id).read(), suffix)
    names = rf.linked_names(graph, path, utc_now())
    none = f"{history}\n\n{rf.FILE_NO_FACTS.format(suffix=suffix)}"
    return {"said": None, "history": history, "names": list(names), "none": none}


# ---------------------------------------------------------------- J90-2 (#316 G4): lock, hotindex


def performance_now(*_):
    """`performance.now()`: a monotonic clock in milliseconds, `time.monotonic()` (the clock the
    reference's lock read), only ever compared with another reading of itself."""
    return _time.monotonic() * 1000


def _libc_realpath():
    """libc's `realpath(3)` through ctypes (POSIX); None where ctypes or the symbol is missing."""
    global _LIBC_REALPATH
    if _LIBC_REALPATH is None:
        found = False
        try:
            import ctypes

            libc = ctypes.CDLL(None, use_errno=True)
            realpath = libc.realpath
            realpath.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            realpath.restype = ctypes.c_void_p
            free = libc.free
            free.argtypes = [ctypes.c_void_p]
            free.restype = None
            found = (ctypes, realpath, free)
        except (ImportError, OSError, AttributeError):
            found = False
        _LIBC_REALPATH = found
    return _LIBC_REALPATH or None


_LIBC_REALPATH = None


def _realpath_native(abs_path):
    """`fs.realpathSync.native(abs_path)`: libuv's `uv_fs_realpath`, which is `realpath(3)` on
    POSIX (the path encoded as `_node_path` hands it to the OS, the answer decoded as Node decodes
    a name, one U+FFFD per invalid subpart) and `GetFinalPathNameByHandleW` on Windows (CPython's
    strict `ntpath.realpath` calls the same); any failure an OSError."""
    if _os.name == "nt":
        return _os.path.realpath(abs_path, strict=True)
    native = _libc_realpath()
    raw = _os.fsencode(abs_path)
    if native is None:
        resolved = _os.path.realpath(raw, strict=True)
    else:
        ctypes, realpath, free = native
        if b"\0" in raw:
            raise OSError(_errno.EINVAL, "realpath")
        out = realpath(raw, None)
        if not out:
            err = ctypes.get_errno()
            raise OSError(err, _os.strerror(err))
        try:
            resolved = ctypes.string_at(out)
        finally:
            free(out)
    return resolved.decode("utf-8", "replace")


def node_realpath(path, *_):
    """`nodeRealpath` (runtime-ts/src/storage/realpath.ts), statement for statement: `path.resolve`
    (`path_resolve`), then `fs.realpathSync.native` (`_realpath_native`), and where that throws the
    parent resolved the same way joined with the name as spelled. J90-3 (#316 G4, the
    orchestrator's ruling on J90-2's divergence): Node's answer, so a path through a DANGLING
    symlink keeps the link as spelled (it was `os.path.realpath`, which follows it to its missing
    target), and a name the filesystem folds is spelled as the filesystem spells it."""
    if not isinstance(path, str):
        raise TypeError("ts2py: nodeRealpath of anything but a string path is outside the subset")
    if _os.name == "nt":
        absolute = _os.path.abspath(_os_text(path))
    else:
        absolute = path_resolve(_os_text(path))
    return _node_realpath_abs(absolute)


def _node_realpath_abs(absolute):
    try:
        return _realpath_native(absolute)
    except (OSError, ValueError):
        parent = path_dirname(absolute)
        if parent == absolute:
            return absolute
        return path_join(_node_realpath_abs(parent), path_basename(absolute))


# J90-P7 (#316 G4): `fromJs` (`_lifted`) moved to the runtime as `_js_lifted`, unchanged, so a
# mypyc build compiles it (this module is never compiled).
_lifted = _js_lifted


def dump_js_value(value, options=_JS_UNDEFINED, float_key=_JS_UNDEFINED, *_):
    """`dumpJsValue` (runtime-ts/src/pyjson.ts): `dump_json` of `fromJs(value)` (`_lifted`), with
    `float_key` of a top-level plain object holding a number written as a float (`4.0`)."""
    if options is _JS_UNDEFINED:
        options = {}
    if not isinstance(options, dict) or not set(options) <= _DUMP_OPTIONS:
        raise TypeError("ts2py: dumpJsValue with those options is outside the subset")

    def opt(name, default):
        got = options.get(name, _JS_UNDEFINED)
        return default if got is _JS_UNDEFINED or got is None else got

    lifted = _lifted(value)
    if (
        float_key is not _JS_UNDEFINED
        and type(value) is dict
        and float_key in value
        and type(value[float_key]) in (int, float)
    ):
        lifted = dict(lifted)
        lifted[float_key] = float(value[float_key])
    separators = opt("separators", None)
    return _json.dumps(
        lifted,
        indent=opt("indent", None),
        sort_keys=opt("sortKeys", False) is True,
        ensure_ascii=opt("ensureAscii", True) is not False,
        separators=None if separators is None else (separators[0], separators[1]),
    )


def extract_refs(text, *_):
    """`extractRefs` (runtime-ts/src/touch/refs.ts): `bantamkit.touch.refs.extract_refs`, which it
    ports (#200)."""
    from ..touch.refs import extract_refs as reference

    return reference(text)


def fact_refs(description, keywords, body, *_):
    """`factRefs` (runtime-ts/src/touch/refs.ts): `bantamkit.touch.refs.fact_refs`, which it ports
    (#200), the keywords as a list."""
    from ..touch.refs import fact_refs as reference

    return reference(description, list(keywords), body)


# ---------------------------------------------------------------- J90-3 (#316 G4): coldindex,
# retention, tiers


def unlink_sync(path, *_):
    """`fs.unlinkSync(path)`: unlink(2), which `os.unlink` calls (a directory refused by the OS:
    EPERM on macOS, EISDIR on Linux, as Node's binding gets it); a failure is CPython's OSError."""
    _os.unlink(_node_path(path, "fs.unlinkSync"))
    return _JS_UNDEFINED


def rmdir_sync(path, *rest):
    """`fs.rmdirSync(path)`: rmdir(2), which `os.rmdir` calls (ENOTEMPTY / ENOTDIR / ENOENT as the
    OS answers); options (`recursive`) are outside the subset."""
    if rest:
        raise TypeError("ts2py: fs.rmdirSync options are outside the subset")
    _os.rmdir(_node_path(path, "fs.rmdirSync"))
    return _JS_UNDEFINED


# `path.sep`: the platform's separator, as `path` is `path.posix` or `path.win32`.
PATH_SEP = "\\" if _os.name == "nt" else "/"


def _posix_relative(source, target):
    """`path.posix.relative` (lib/path.js), statement for statement."""
    if source == target:
        return ""
    source = _posix_resolve([source])
    target = _posix_resolve([target])
    if source == target:
        return ""
    from_start = 1
    from_end = len(source)
    from_len = from_end - from_start
    to_start = 1
    to_len = len(target) - to_start
    length = from_len if from_len < to_len else to_len
    last_common_sep = -1
    i = 0
    while i < length:
        from_code = source[from_start + i]
        if from_code != target[to_start + i]:
            break
        if from_code == "/":
            last_common_sep = i
        i += 1
    if i == length:
        if to_len > length:
            if target[to_start + i] == "/":
                return target[to_start + i + 1 :]
            if i == 0:
                return target[to_start + i :]
        elif from_len > length:
            if source[from_start + i] == "/":
                last_common_sep = i
            elif i == 0:
                last_common_sep = 0
    out = ""
    i = from_start + last_common_sep + 1
    while i <= from_end:
        if i == from_end or source[i] == "/":
            out += ".." if len(out) == 0 else "/.."
        i += 1
    return f"{out}{target[to_start + last_common_sep :]}"


def path_relative(source, target, *_):
    """`path.relative(from, to)`: `path.posix.relative` ported statement for statement (code points
    for UTF-16 units: only `/` is compared by position, and a pair differing in either unit differs
    as a code point, so every cut lands on the same character); on Windows CPython's
    `ntpath.relpath`, which answers `path.win32.relative`'s path for a `to` under `from` (the one
    shape compiled code passes, `retention.ts`'s `rel`; unmeasured on Windows)."""
    if not isinstance(source, str) or not isinstance(target, str):
        raise TypeError("ts2py: path.relative of anything but strings is outside the subset")
    if _os.name == "nt":
        return _os.path.relpath(target, source)
    return _posix_relative(source, target)


class _ColdFs(_JsObject):
    """`coldFs` (runtime-ts/src/storage/coldfs.ts): the reads `coldindex.ts` makes, one object a
    test swaps a method on. `readFileSync(p)` is the builtin `open(p, encoding="utf-8")` read
    whole, the reference's `_read_json` (`bantamkit.storage.coldindex` on 743b54b9), which
    `pyReadText` ports (strict UTF-8, universal newlines, `_store_path`'s path policy); `open` is
    looked up when called, so the Python test's `builtins.open` spy still sees every read."""

    _js_name = "Object"
    _js_own = frozenset({"readFileSync"})
    _js_own_methods = frozenset({"readFileSync"})

    def readFileSync(self, path, *_):
        try:
            with open(_store_path(path, "pyReadText"), encoding="utf-8") as handle:
                return handle.read()
        except UnicodeDecodeError as error:
            raise PyUnicodeDecodeError(str(error)) from None


coldFs = _ColdFs()


def cold_error_text(error, *_):
    """`coldErrorText` (runtime-ts/src/storage/coldfs.ts): the text a `ColdIndexError` quotes,
    `str(e)` as the reference quoted it (`f"... unreadable: {e}"`): an OSError CPython's `str(e)`
    (which a `PyOSError`'s message is in Node), a `PyUnicodeDecodeError` CPython's decoder message
    (both runtimes). A text that is not JSON never reaches it since J90-3F: `coldindex.ts` throws
    its own `COLD_NOT_JSON` sentence, so neither parser's wording is quoted
    (`--suite storage-cold`)."""
    return str(error)


def _fsync_dir(directory):
    """`retentionfs.ts`'s `fsyncDir`: the reference's `_fsync_dir`. POSIX only."""
    if _os.name == "nt":
        return
    try:
        fd = _os.open(directory, _os.O_RDONLY)
    except OSError:
        return
    try:
        _os.fsync(fd)
        retentionFs.syncs += 1
    except OSError:
        pass
    finally:
        _os.close(fd)


class _RetentionFs(_JsObject):
    """`retentionFs` (runtime-ts/src/storage/retentionfs.ts): the archive's one write, temp then
    rename, fsynced (the file, then its directory on POSIX), the reference's `_write_archive`
    statement for statement (J69-8); the gzip is `gzip_sync`'s (the `gzipSync` row: the compressed
    bytes are RULED, the data they hold the same). `syncs` counts the syncs made. `os.fsync`,
    `os.replace` and `os.unlink` are looked up when called, so a test that patches `os` sees
    them; a test swaps `writeArchive` to make the write fail, as Node's test does."""

    _js_name = "Object"
    _js_own = frozenset({"syncs", "writeArchive"})
    _js_own_methods = frozenset({"writeArchive"})

    def __init__(self):
        self.syncs = 0

    def writeArchive(self, target, data, *_):
        target = _node_path(target, "retentionFs.writeArchive")
        directory = _os.path.dirname(target)
        _pathlib.Path(directory).mkdir(parents=True, exist_ok=True)
        tmp = _os.path.join(directory, f"{_os.path.basename(target)}.{_os.getpid()}.tmp")
        # compressed before the temp is opened (J90-3F), as Node's: a live writer's temp is never
        # idle, so the stale-temp sweep (`removeStaleTemps`) never meets one
        gz = gzip_sync(data)
        try:
            with open(tmp, "wb") as handle:
                handle.write(gz)
                handle.flush()
                _os.fsync(handle.fileno())
                self.syncs += 1
            _os.replace(tmp, target)
            _fsync_dir(directory)
        except OSError:
            try:
                _os.unlink(tmp)
            except OSError:
                pass
            raise
        return _JS_UNDEFINED


retentionFs = _RetentionFs()


def spawn_retention_child(cwd, home, *_):
    """`spawnRetentionChild` (runtime-ts/src/storage/retentionspawn.ts): the reference's spawn
    (`maybe_spawn`): `python -m bantamkit.storage.retention <cwd> <home>`, detached and silent
    (stdin, stdout, stderr to the null device; a new session on POSIX, a detached process group on
    Windows), never waited for. True once started; False when the spawn fails in any way (the
    reference answered `failed` for any exception, as `maybeSpawn` answers for a missing child
    script or a spawn that throws)."""
    import subprocess
    import sys

    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if _os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(
            [sys.executable, "-m", "bantamkit.storage.retention", cwd, home], **kwargs
        )
    except Exception:  # noqa: BLE001 - a spawn this cannot make is never a failed session
        return False
    return True


def touch_reducer(rows, *_):
    """`touchReducer` (runtime-ts/src/touch/log.ts): `bantamkit.touch.log.touch_reducer`, which it
    ports (#200; `--suite touch-log` compares the two); the reference's retention folded with it."""
    from ..touch.log import touch_reducer as _reducer

    return _reducer(rows)


def native_memory_dir(home, *_):
    """`nativeMemoryDir` (runtime-ts/src/hookadapter.ts): `bantamkit.hookadapter.native_memory_dir`,
    which it ports (RULING Q1.2 without the transcript branch, J69-7)."""
    from ..hookadapter import native_memory_dir as _resolve

    return _resolve(home)


def has_bantamkit_hooks(path, *_):
    """`hasBantamkitHooks` (runtime-ts/src/hostinstall.ts): `bantamkit.hostinstall.
    has_bantamkit_hooks` of the path, which it ports (#204, S2)."""
    from ..hostinstall import has_bantamkit_hooks as _probe

    return bool(_probe(_pathlib.Path(path)))


def process_cwd(*_):
    """`process.cwd()`: `os.getcwd()`, the reference's `current_cwd`; a deleted directory raises
    CPython's FileNotFoundError, which a compiled `catch` sees as Node's ENOENT."""
    return _os.getcwd()
