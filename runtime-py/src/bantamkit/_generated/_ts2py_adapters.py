# ts2py adapters: hand-written Python for the imports and Node globals ts2py does not compile.
# Every name here is declared in tools/ts2py-bantamkit/ts2py.toml with the reason it is faithful,
# and RULES.md (Adapters) records how each was measured. Nothing else may be imported this way.
# Shipped form (J90-P2): comments are in tools/ts2py/python/ts2py/ and tools/ts2py-bantamkit/.
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

from ._ts2py_runtime import (
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

_STDLIB312 = None


class _LiveLibrary:

    path_exists = staticmethod(lambda path: _pathlib.Path(path).exists())
    path_is_dir = staticmethod(lambda path: _pathlib.Path(path).is_dir())
    path_is_file = staticmethod(lambda path: _pathlib.Path(path).is_file())
    path_resolve = staticmethod(lambda path, strict=False: _pathlib.Path(path).resolve(strict))
    path_suffix = staticmethod(lambda path: _pathlib.PurePath(path).suffix)
    win_is_absolute = staticmethod(lambda path: _pathlib.PureWindowsPath(path).is_absolute())
    json_loads = staticmethod(_json.loads)
    pin_datetime_error = staticmethod(lambda error: error)


def _stdlib312_by_path():
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

if _typing.TYPE_CHECKING:

    class BantamError(_JsError):
        pass


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
    return repr(float(_js_num(x)))


def py_strip(s):
    return s.strip()


class TextDecoder(_JsObject):

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




def py_repr(s):
    if not isinstance(s, str):
        raise TypeError("ts2py: pyRepr of anything but a string is outside the subset")
    return repr(s)


def cmp_codepoint(a, b, *_):
    if not (isinstance(a, str) and isinstance(b, str)):
        raise TypeError("ts2py: cmpCodepoint of anything but two strings is outside the subset")
    for x, y in zip(a, b, strict=False):
        if x != y:
            return -1 if x < y else 1
    return len(a) - len(b)


cmp_codepoint._js_codepoint_order = True


def process_env(name):
    if not isinstance(name, str):
        raise TypeError("ts2py: process.env read by anything but a string is outside the subset")
    return _os.environ.get(name, _JS_UNDEFINED)


def assets_root():
    from ..assets import assets_root as _assets_root

    return str(_assets_root())


def _checked_path(path, what):
    if not isinstance(path, str):
        raise TypeError(f"ts2py: {what} of anything but a string path is outside the subset")
    if "\0" in path or any(0xD800 <= ord(c) <= 0xDFFF for c in path):
        raise TypeError(
            f"ts2py: {what} of a path holding NUL or a lone surrogate is outside the subset"
        )
    return path


def exists_sync(path, *_):
    if path is None or path is _JS_UNDEFINED or isinstance(path, (bool, int, float)):
        return False
    if isinstance(path, str) and "\0" in path:
        return False
    return _os.path.exists(_node_path(path, "fs.existsSync"))


def read_file_sync(path, encoding=_JS_UNDEFINED, *_):
    if encoding is _JS_UNDEFINED:
        return read_file_bytes(path)
    if encoding not in ("utf8", "utf-8"):
        raise TypeError("ts2py: fs.readFileSync with an encoding but 'utf8' is outside the subset")
    with open(_checked_path(path, "fs.readFileSync"), "rb") as handle:
        data = handle.read()
    return data.decode("utf-8", "replace")


def _normalize_string(path, allow_above_root, separator, is_separator):
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
    segments = path.split("/")
    if "." not in segments and ".." not in segments:
        return "/".join(filter(None, segments))
    return _normalize_string(path, allow_above_root, "/", lambda c: c == "/")


def _posix_join(parts):
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
    for part in parts:
        if not isinstance(part, str):
            if part is _JS_UNDEFINED or part is None:
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




def _os_char(c):
    if _os.name == "nt" and 0xD800 <= ord(c) <= 0xDFFF:
        return "�"
    try:
        _os.fsencode(c)
    except UnicodeEncodeError:
        return "\ufffd"
    return c


def _node_path(path, what):
    if not isinstance(path, str):
        raise TypeError(f"ts2py: {what} of anything but a string path is outside the subset")
    if "\0" in path:
        error = _JsTypeError("The argument 'path' must be a string without null bytes")
        error.code = "ERR_INVALID_ARG_VALUE"
        raise error
    return _os_text(path)


class Stats(_JsObject):

    _js_name = "Stats"
    _js_own = frozenset({"size", "mtimeMs", "ino", "isDirectory", "isFile", "isSymbolicLink"})
    _js_own_methods = frozenset({"isDirectory", "isFile", "isSymbolicLink"})

    def __init__(self, st, *_):
        ns = st.st_mtime_ns
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

    _js_name = "BigIntStats"
    _js_own = frozenset(
        {"size", "mtimeMs", "mtimeNs", "ino", "isDirectory", "isFile", "isSymbolicLink"}
    )

    def __init__(self, st, *_):
        ns = st.st_mtime_ns
        fields = self.__dict__
        fields["_js_st"] = st
        fields["size"] = _JsBigInt(st.st_size)
        fields["mtimeNs"] = _JsBigInt(ns)
        fields["mtimeMs"] = _JsBigInt(ns // 1_000_000)
        fields["ino"] = _JsBigInt(st.st_ino)


def stat_sync(path, *rest):
    bigint = False
    if rest:
        options = rest[0]
        only = len(rest) == 1 and isinstance(options, dict) and len(options) == 1
        if not (only and "bigint" in options):
            raise TypeError("ts2py: fs.statSync options other than bigint are outside the subset")
        bigint = _js_truthy(options["bigint"])
    st = _os.stat(_node_path(path, "fs.statSync"))
    return BigIntStats(st) if bigint else Stats(st)


def lstat_sync(path, *rest):
    bigint = False
    if rest:
        options = rest[0]
        only = len(rest) == 1 and isinstance(options, dict) and len(options) == 1
        if not (only and "bigint" in options):
            raise TypeError("ts2py: fs.lstatSync options other than bigint are outside the subset")
        bigint = _js_truthy(options["bigint"])
    st = _os.lstat(_node_path(path, "fs.lstatSync"))
    return BigIntStats(st) if bigint else Stats(st)


def stat_stamp(path, *_):
    st = _os.stat(_node_path(path, "fs.statSync"))
    return f"{st.st_mtime_ns}:{st.st_size}:{st.st_ino}"


def stat_mtime_ns(path, *_):
    return str(_os.stat(_node_path(path, "fs.statSync")).st_mtime_ns)


def stat_file(path, *_):
    st = _os.stat(_node_path(path, "fs.statSync"))
    return [str(st.st_mtime_ns), _js_num(st.st_size), _stat.S_ISREG(st.st_mode)]


def fstat_sync(fd, *rest):
    if rest or isinstance(fd, bool) or not isinstance(fd, int):
        raise TypeError("ts2py: fs.fstatSync of anything but a descriptor is outside the subset")
    return Stats(_os.fstat(fd))


def readdir_sync(path, *rest):
    if rest:
        raise TypeError("ts2py: fs.readdirSync options are outside the subset")
    path = _node_path(path, "fs.readdirSync")
    names = _os.listdir(path)
    if "".join(names).isascii():
        return names
    if _os.name == "nt":
        return [
            "".join("\ufffd" if 0xD800 <= ord(c) <= 0xDFFF else c for c in name)
            for name in _os.listdir(path)
        ]
    return [name.decode("utf-8", "replace") for name in _os.listdir(_os.fsencode(path))]


def mkdir_sync(path, options=_JS_UNDEFINED, *_):
    recursive = isinstance(options, dict) and set(options) == {"recursive"}
    if not (recursive and options["recursive"] is True):
        raise TypeError("ts2py: fs.mkdirSync without {recursive: true} is outside the subset")
    _os.makedirs(_node_path(path, "fs.mkdirSync"), exist_ok=True)
    return _JS_UNDEFINED


def rename_sync(old, new, *_):
    _os.replace(_node_path(old, "fs.renameSync"), _node_path(new, "fs.renameSync"))
    return _JS_UNDEFINED


def rm_sync(path, options=_JS_UNDEFINED, *_):
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
_BINARY = getattr(_os, "O_BINARY", 0)


def open_sync(path, flags="r", *rest):
    if rest or flags not in _OPEN_FLAGS:
        raise TypeError(f"ts2py: fs.openSync with flags {flags!r} or a mode is outside the subset")
    return _os.open(_node_path(path, "fs.openSync"), _OPEN_FLAGS[flags] | _BINARY, 0o666)


def close_sync(fd, *_):
    if isinstance(fd, bool) or not isinstance(fd, int):
        raise TypeError("ts2py: fs.closeSync of anything but a descriptor is outside the subset")
    _os.close(fd)
    return _JS_UNDEFINED


def write_sync(fd, data, *rest):
    if rest or not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("ts2py: fs.writeSync of anything but (fd, buffer) is outside the subset")
    return _os.write(fd, data)


def read_sync(fd, buffer, offset, length, position, *_):
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
    with open(_node_path(path, "fs.readFileSync"), "rb") as handle:
        return handle.read()


def _posix_dirname(path):
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
    if not isinstance(path, str):
        raise TypeError("ts2py: path.dirname of anything but a string is outside the subset")
    return _win32_dirname(path) if _os.name == "nt" else _posix_dirname(path)


def path_basename(path, *rest):
    if rest or not isinstance(path, str):
        raise TypeError("ts2py: path.basename of anything but one string is outside the subset")
    return _win32_basename(path) if _os.name == "nt" else _posix_basename(path)


def _zlib_error(message, code):
    error = _JsError(message)
    error.code = code
    return error


def gzip_sync(data, *rest):
    if rest or not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("ts2py: zlib.gzipSync of anything but a buffer is outside the subset")
    return _gzip.compress(bytes(data), mtime=0)


def gunzip_sync(data, *rest):
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
    if rest or isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise TypeError("ts2py: crypto.randomBytes of anything but a count is outside the subset")
    return _os.urandom(size)


def buffer_from(value, encoding=_JS_UNDEFINED, *_):
    if not isinstance(value, str) or encoding not in (_JS_UNDEFINED, "utf8", "utf-8"):
        raise TypeError("ts2py: Buffer.from of anything but a string as utf8 is outside the subset")
    if not value.isascii() and any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        value = "".join("\ufffd" if 0xD800 <= ord(c) <= 0xDFFF else c for c in value)
    return value.encode("utf-8")


def buffer_concat(items, *rest):
    buffers = isinstance(items, list) and all(
        isinstance(b, (bytes, bytearray, memoryview)) for b in items
    )
    if rest or not buffers:
        raise TypeError(
            "ts2py: Buffer.concat of anything but a list of buffers is outside the subset"
        )
    return b"".join(items)


def buffer_alloc(size, *rest):
    if rest or isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise TypeError("ts2py: Buffer.alloc of anything but a count is outside the subset")
    return bytearray(size)


def process_env_all():
    return dict(_os.environ)


def process_pid():
    return _os.getpid()




def py_exists(path):
    return _stdlib312().path_exists(_pathlib.Path(path))


def py_is_dir(path):
    return _stdlib312().path_is_dir(_pathlib.Path(path))


@_functools.lru_cache(maxsize=8192)
def _pure_join(parts):
    return str(_pathlib.PurePath(*parts))


def py_join(*parts):
    if all(type(p) is str for p in parts):
        return _pure_join(parts)
    return str(_pathlib.PurePath(*parts))


def py_parent(path):
    return str(_pathlib.PurePath(path).parent)


def py_name(path):
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
    return _OSERROR_SUBCLASS.get(code, "OSError") if isinstance(code, str) else "OSError"


PyOSError = OSError


def bantamkit_dir_for(path):
    from ..memory.store import bantamkit_dir_for as _for

    found = _for(_pathlib.Path(path))
    return None if found is None else str(found)


def ensure_bantamkit_gitignore(directory, created, *_):
    from ..memory.store import ensure_bantamkit_gitignore as _ensure

    _ensure(_pathlib.Path(directory), created=bool(created))
    return _JS_UNDEFINED




py_round_float9 = _js_py_round_float9


def py_log(x, *_):
    return _math.log(_js_num(x))


def py_log1p(x, *_):
    return _math.log1p(_js_num(x))


def py_pow(x, y, *_):
    base = float(_js_num(x))
    if base < 0:
        raise TypeError("ts2py: pyPow of a negative base is outside the subset")
    try:
        return base ** float(_js_num(y))
    except OverflowError:
        return _math.inf


def py_nfkc_lower(text, *_):
    return _unicodedata.normalize("NFKC", text).lower()


def py_wordchar(ch, *_):
    return _unicodedata.category(ch)[0] in "LNM"


def _os_text(text):
    if text.isascii():
        return text
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "".join(_os_char(c) if 0xD800 <= ord(c) <= 0xDFFF else c for c in text)
    return text


def py_realpath(path, *_):
    if not isinstance(path, str):
        raise TypeError("ts2py: pyRealpath of anything but a string path is outside the subset")
    return _os.path.realpath(_os_text(path))


_HASHES = {"sha256": _hashlib.sha256, "sha1": _hashlib.sha1}


class Hash(_JsObject):

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
            self._live().update(data)
            return self
        if not isinstance(data, str) or encoding not in ("utf8", "utf-8"):
            raise TypeError(
                "ts2py: hash.update of anything but a 'utf8' string or a Buffer is outside the"
                " subset"
            )
        self._live().update(_hash_bytes(data))
        return self

    def digest(self, encoding=_JS_UNDEFINED, *_):
        if encoding != "hex":
            raise TypeError("ts2py: hash.digest of anything but 'hex' is outside the subset")
        out = self._live().hexdigest()
        object.__setattr__(self, "_js_hash", None)
        return out


def _hash_bytes(text):
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        return _os_text(text).encode("utf-8", "surrogateescape")


def hash_hex(algorithm, data):
    if type(data) is str:
        return _HASHES[algorithm](_hash_bytes(data)).hexdigest()
    return Hash(algorithm).update(data, "utf8").digest("hex")


def create_hash(algorithm, *_):
    return Hash(algorithm)


def _lazy_bantam_error():
    try:
        from ..client import BantamError as python_base
    except ImportError:
        bases = (_JsError,)
    else:
        bases = (_JsError, python_base)

    def __init__(self, message=_JS_UNDEFINED, *_):
        _JsError.__init__(self, message)
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
    if name == "BantamError":
        cls = _lazy_bantam_error()
        globals()["BantamError"] = cls
        return cls
    if name == "PyScalar":
        from .pyyaml import PyScalar as value
    elif name == "VALID_OUTCOMES":
        from .factfile import VALID_OUTCOMES as value
    elif name == "SKILL_LAYER":
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

    _js_name = "CountsView"
    _js_own = frozenset({"scan"})
    _js_own_methods = frozenset({"scan"})

    def __init__(self, *_):
        raise TypeError("ts2py: a CountsView is never built in Python")

    def scan(self, *_):  # pragma: no cover - never constructed
        raise TypeError("ts2py: a CountsView is never built in Python")


# ---------------------------------------------------------------- J89-4a (#316 G3 U2): store


def homedir(*_):
    return str(_pathlib.Path.home())


_WORD_SEARCH = {}


def py_search_word(alternatives, text, *_):
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
    if not isinstance(value, str) or encoding not in (_JS_UNDEFINED, "utf8", "utf-8"):
        raise TypeError(
            "ts2py: Buffer.byteLength of anything but a string as utf8 is outside the subset"
        )
    if value.isascii():
        return len(value)
    return len(value.encode("utf-8", "surrogatepass"))


class _JsReadMap(_JsMap):

    __slots__ = ()

    def __init__(self, data):
        object.__setattr__(self, "_entries", data)
        object.__setattr__(self, "_keys", None)

    def set(self, key, value):
        raise TypeError("ts2py: writing a Map an index adapter answered is outside the subset")

    def delete(self, key):
        raise TypeError("ts2py: writing a Map an index adapter answered is outside the subset")


def _native_bantam_error(error):
    cls = globals().get("BantamError") or __getattr__("BantamError")
    if isinstance(error, cls):
        return error
    return cls(str(error))


def _native_meta(front):
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


_NATIVE_EXTRA_LINE = _re.compile("(?:^|[\n\r\u2028\u2029])[ \t]*(?:tags|links):")


def parse_native(path, *_):
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
    if not _FACTFILE:
        from . import factfile as _ff

        _FACTFILE.append(_ff)
    return getattr(_FACTFILE[0], name)


def extra_of(meta, *_):
    return _factfile("extra_of")(meta)


def _factcodec():
    try:
        from ..memory import factcodec as codec
    except ImportError:
        return None
    return codec


def format_fact(fact, *_):
    codec = _factcodec()
    if codec is None:
        return _factfile("format_fact")(fact)
    return codec.held_fact_text(fact)


def lifecycle_of(meta, *_):
    return _factfile("lifecycle_of")(meta)


def parse_frontmatter(front, *_):
    codec = _factcodec()
    if codec is None:
        return _factfile("parse_frontmatter")(front)
    return codec.held_frontmatter(front)


def py_list(value, *_):
    return _factfile("py_list")(value)


def py_split(text, sep, maxsplit, *_):
    return _factfile("py_split")(text, sep, maxsplit)


def py_truthy(value=_JS_UNDEFINED, *_):
    return _factfile("py_truthy")(value)


def today_local(*args):
    return _factfile("today_local")(*args[:1])


def as_py_os_error(error, fallback_path=_JS_UNDEFINED, fallback_dest=_JS_UNDEFINED, *_):
    if not isinstance(error, OSError):
        raise error
    if error.filename is None and isinstance(fallback_path, str):
        error.filename = fallback_path
        if error.filename2 is None and isinstance(fallback_dest, str):
            error.filename2 = fallback_dest
    return error


def matches_md(name, *_):
    return _fnmatch.fnmatch(name, "*.md")


def _js_inspect_str(text):
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
    inspected = _js_inspect_str(value)
    units = inspected.encode("utf-16-le", "surrogatepass")
    if len(units) > 256:
        return units[:256].decode("utf-16-le", "surrogatepass") + "..."
    return inspected


def _store_path(path, what):
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
    if not isinstance(path, str):
        raise TypeError("ts2py: pyLexists of anything but a string path is outside the subset")
    return None if "\0" in path else _os_text(path)


def py_lexists(path, *_):
    path = _lexists_path(path)
    return False if path is None else _os.path.lexists(path)


def py_mkdir_parents(path, *_):
    _pathlib.Path(_store_path(path, "pyMkdirParents")).mkdir(parents=True, exist_ok=True)
    return _JS_UNDEFINED


def py_mtime_date(path, *_):
    mtime = _pathlib.Path(_store_path(path, "pyMtimeDate")).stat().st_mtime
    return _datetime.date.fromtimestamp(mtime).isoformat()  # noqa: DTZ012


def py_parents(path, *_):
    return [str(p) for p in _pathlib.PurePath(path).parents]


class PyUnicodeDecodeError(_JsError):

    _js_name = "PyUnicodeDecodeError"
    name = "UnicodeDecodeError"


def py_read_text(path, *_):
    try:
        path = _store_path(path, "pyReadText")
        if _pure_as_is(path):
            with _io.open(path, encoding="utf-8") as handle:  # noqa: UP020
                return handle.read()
        return _pathlib.Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise PyUnicodeDecodeError(str(error)) from None


def _pure_as_is(path):
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
    _os.replace(_store_path(source, "pyReplace"), _store_path(target, "pyReplace"))
    return _JS_UNDEFINED


def py_scandir_names(directory, *_):
    with _os.scandir(_store_path(directory, "pyScandirNames")) as entries:
        return [entry.name for entry in entries]


def py_scandir_probe(directory, *_):
    with _os.scandir(_store_path(directory, "pyScandirProbe")):
        pass
    return _JS_UNDEFINED


def py_suffix(path, *_):
    return _stdlib312().path_suffix(path)


def py_unlink(path, *_):
    _pathlib.Path(_store_path(path, "pyUnlink")).unlink()
    return _JS_UNDEFINED


def py_write_text(path, text, *_):
    _pathlib.Path(_store_path(path, "pyWriteText")).write_text(text, encoding="utf-8")
    return _JS_UNDEFINED


def py_write_text_atomic(path, text, *_):
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
    if not isinstance(error, OSError):
        raise TypeError("ts2py: pyOSErrorText of anything but an OSError is outside the subset")
    return str(error)


def py_os_error_strerror(error, *_):
    if not isinstance(error, OSError):
        raise TypeError("ts2py: pyOSErrorStrerror of anything but an OSError is outside the subset")
    return str(error.strerror)


def sorted_path_names(names, *_):
    return sorted(names, key=_os.path.normcase)




class PyJSONDecodeError(_JsError):

    _js_name = "PyJSONDecodeError"
    name = "PyJSONDecodeError"


class _TaggedDict:
    pass


def _tagged_close(into, at):
    keys, values = into[at]
    held = _JsMap()
    held._entries = dict(zip(keys, values, strict=True))
    into[at] = {"t": "dict", "v": held}


def _tagged(value):
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


_PARSE_JSON_DEPTH = 512

_JSON_NESTING = _re.compile(r'"(?:[^"\\]+|\\.)*"?|[\[\]{}]', _re.DOTALL)


def _json_too_deep(text):
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
    try:
        _stdlib312().json_loads(text[:cut])
    except _json.JSONDecodeError as error:
        return error.msg == "Expecting value" and error.pos == cut
    except RecursionError:
        return True
    return False


def parse_json(text, *_):
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
    if not isinstance(text, str):
        raise TypeError(
            "ts2py: encodeBasestringAscii of anything but a string is outside the subset"
        )
    return _json.encoder.encode_basestring_ascii(text)


def py_decode_utf8(data, *_):
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("ts2py: pyDecodeUtf8 of anything but a Buffer is outside the subset")
    try:
        return bytes(data).decode("utf-8")
    except UnicodeDecodeError as error:
        raise PyUnicodeDecodeError(str(error)) from None


def _node_utf8(text):
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        pass
    units = text.encode("utf-16-le", "surrogatepass")
    return units.decode("utf-16-le", "replace").encode("utf-8")


def write_file_sync(path, data, options=_JS_UNDEFINED, *rest):
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



_TAB_PROBLEM = "found character '\\t' that cannot start any token"

_GRANT_CONFIG = []

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
        error = _GrantConfigUnreadable(_GRANT_TOO_DEEP)
    except ValueError as e:
        error = _GrantConfigUnreadable(str(_stdlib312().pin_datetime_error(e)))
    _GRANT_CONFIG[:] = [(text, value, error)]
    return value, error


def first_token_tab(text, *_):
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
    if isinstance(item, str) and "\0" not in item:
        return {"kind": "str", "value": item}
    return {"kind": "other", "value": None}


def parse_config_document(text, *_):
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
    return _stdlib312().path_is_file(_pathlib.Path(path))


def py_resolve(path, *_):
    return str(_stdlib312().path_resolve(path))


def py_stat_is_dir(path, *_):
    return _stat.S_ISDIR(_os.stat(_pathlib.Path(path)).st_mode)


def py_cwd(*_):
    return str(_pathlib.Path.cwd())


def py_expanduser(path, *_):
    return str(_pathlib.Path(path).expanduser())


def py_is_absolute(path, *_):
    if _os.name == "nt":
        return _stdlib312().win_is_absolute(path)
    return _pathlib.PurePath(path).is_absolute()


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
    body = _dream_text("pyUnresolvedTerms", body)
    return [m.group(0) for m in _DREAM_UNRESOLVED.finditer(body)]


def py_slot_groups(text, *_):
    text = _dream_text("pySlotGroups", text)
    m = _DREAM_SLOT.match(_DREAM_BULLET.sub("", text))
    return None if m is None else [m.group("subject"), m.group("value")]


def py_sub_spaces(text, *_):
    return _DREAM_SPACES.sub(" ", _dream_text("pySubSpaces", text))


def py_int_digits(text, *_):
    text = _dream_text("pyIntDigits", text)
    try:
        n = int(text)
    except ValueError:
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




def _posix_resolve(paths):
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
    return str(_pathlib.Path.home())


def py_lower(text, *_):
    if not isinstance(text, str):
        raise TypeError("ts2py: pyLower of anything but a string is outside the subset")
    return _js_m_toLowerCase(text)


def _store_shim():
    from ..memory import store as shim

    return shim


def _python_set(values):
    return frozenset() if values is _JS_UNDEFINED or values is None else frozenset(values)


def _skipped_list(skipped):
    return None if skipped is _JS_UNDEFINED else skipped


class SkillStore(_JsObject):

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
    return isinstance(store, SkillStore)


def skill_roots(project_store, home, *_):
    from ..memory.skills import skill_roots as _roots

    return [str(p) for p in _roots(project_store, home)]


def triggers_enabled(*_):
    from ..memory.skills import triggers_enabled as _enabled

    return _enabled()


def fire_on(query, shown, offer, *_):
    from ..memory.skills import SkillStore as _Skills
    from ..replynative import frame
    from ..skillmine import tokenize_label

    fact = _Skills.fire(tokenize_label(frame(query)), set(shown), offer)
    return None if fact is None else _store_shim()._fact_in(fact)


def load_skill(name, *_):
    from ..assets import load_skill as _load

    return _load(name)


def via_enabled(*_):
    from ..touch import context as _context

    return _context.via_enabled()


def via_pick(graph, paths, exclude, weigh, *_):
    from ..touch import context as _context

    got = _context.via_pick(graph, list(paths), set(exclude), weigh)
    return None if got is None else [got[0], got[1]]


def via_label(path, graph, *_):
    from ..touch import context as _context

    return _context.via_label(path, graph)


def file_links(file, layers, *_):
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




def performance_now(*_):
    return _time.monotonic() * 1000


def _libc_realpath():
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


_lifted = _js_lifted


def dump_js_value(value, options=_JS_UNDEFINED, float_key=_JS_UNDEFINED, *_):
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
    from ..touch.refs import extract_refs as reference

    return reference(text)


def fact_refs(description, keywords, body, *_):
    from ..touch.refs import fact_refs as reference

    return reference(description, list(keywords), body)




def unlink_sync(path, *_):
    _os.unlink(_node_path(path, "fs.unlinkSync"))
    return _JS_UNDEFINED


def rmdir_sync(path, *rest):
    if rest:
        raise TypeError("ts2py: fs.rmdirSync options are outside the subset")
    _os.rmdir(_node_path(path, "fs.rmdirSync"))
    return _JS_UNDEFINED


PATH_SEP = "\\" if _os.name == "nt" else "/"


def _posix_relative(source, target):
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
    if not isinstance(source, str) or not isinstance(target, str):
        raise TypeError("ts2py: path.relative of anything but strings is outside the subset")
    if _os.name == "nt":
        return _os.path.relpath(target, source)
    return _posix_relative(source, target)


class _ColdFs(_JsObject):

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
    return str(error)


def _fsync_dir(directory):
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
    from ..touch.log import touch_reducer as _reducer

    return _reducer(rows)


def native_memory_dir(home, *_):
    from ..hookadapter import native_memory_dir as _resolve

    return _resolve(home)


def has_bantamkit_hooks(path, *_):
    from ..hostinstall import has_bantamkit_hooks as _probe

    return bool(_probe(_pathlib.Path(path)))


def process_cwd(*_):
    return _os.getcwd()
