# ts2py adapters: hand-written Python for the imports and Node globals ts2py does not compile.
# Every name here is declared in tools/ts2py/src/adapters.rs with the reason it is faithful, and
# RULES.md (Adapters) records how each was measured. Nothing else may be imported this way.
import datetime as _datetime
import errno as _errno
import gzip as _gzip
import os as _os
import pathlib as _pathlib
import stat as _stat
import zlib as _zlib

from ._ts2py_runtime import (
    _JS_UNDEFINED,
    _js_num,
    _js_truthy,
    _JsError,
    _JsObject,
    _JsTypeError,
)

# `BantamError` (and J88-2's `LOCK_*_MS`) are provided lazily by `__getattr__` below and are not
# listed, so a star import does not build them (and import `bantamkit.client` / `storage.lock`).
__all__ = [
    "Date",
    "PyOSError",
    "Stats",
    "TextDecoder",
    "append_file_sync",
    "assets_root",
    "bantamkit_dir_for",
    "buffer_alloc",
    "buffer_concat",
    "buffer_from",
    "close_sync",
    "cmp_codepoint",
    "ensure_bantamkit_gitignore",
    "exclusive",
    "exists_sync",
    "fstat_sync",
    "gunzip_sync",
    "gzip_sync",
    "link_sync",
    "lstat_sync",
    "mkdir_sync",
    "open_sync",
    "os_error_class_name",
    "path_basename",
    "path_dirname",
    "path_join",
    "process_env",
    "process_env_all",
    "process_pid",
    "py_exists",
    "py_float_repr",
    "py_is_dir",
    "py_join",
    "py_name",
    "py_parent",
    "py_repr",
    "py_strip",
    "random_bytes",
    "read_file_bytes",
    "read_file_sync",
    "read_sync",
    "readdir_sync",
    "rename_sync",
    "rm_sync",
    "stat_sync",
    "write_sync",
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
    if not path.isascii() and any(0xD800 <= ord(c) <= 0xDFFF for c in path):
        path = "".join(_os_char(c) if 0xD800 <= ord(c) <= 0xDFFF else c for c in path)
    return path


class Stats(_JsObject):
    """`fs.Stats` from `statSync`/`lstatSync`/`fstatSync`: `size`, `mtimeMs` (libuv's seconds and
    nanoseconds as Node combines them, `sec * 1e3 + nsec / 1e6`), and the type tests. On Windows a
    junction is a symbolic link to `lstat`, as libuv reports one."""

    _js_name = "Stats"
    _js_own = frozenset({"size", "mtimeMs", "isDirectory", "isFile", "isSymbolicLink"})
    _js_own_methods = frozenset({"isDirectory", "isFile", "isSymbolicLink"})

    def __init__(self, st, *_):
        object.__setattr__(self, "_js_st", st)
        self.size = st.st_size
        ns = st.st_mtime_ns
        self.mtimeMs = (ns // 1_000_000_000) * 1e3 + (ns % 1_000_000_000) / 1e6

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


def stat_sync(path, *rest):
    """`fs.statSync(path)`: `os.stat` (symlinks followed); a failure is CPython's OSError."""
    if rest:
        raise TypeError("ts2py: fs.statSync options are outside the subset")
    return Stats(_os.stat(_node_path(path, "fs.statSync")))


def lstat_sync(path, *rest):
    """`fs.lstatSync(path)`: `os.lstat`; a failure is CPython's OSError."""
    if rest:
        raise TypeError("ts2py: fs.lstatSync options are outside the subset")
    return Stats(_os.lstat(_node_path(path, "fs.lstatSync")))


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
    """`path.posix.dirname` (lib/path.js), statement for statement."""
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
    """`path.posix.basename` (lib/path.js) with no suffix argument."""
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
    """`pyExists` (runtime-ts/src/memory/pyfs.ts): `Path.exists()`, which it ports."""
    return _pathlib.Path(path).exists()


def py_is_dir(path):
    """`pyIsDir` (runtime-ts/src/memory/pyfs.ts): `Path.is_dir()`, which it ports."""
    return _pathlib.Path(path).is_dir()


def py_join(*parts):
    """`pyJoin` (runtime-ts/src/memory/pyfs.ts): `str(PurePath(*parts))`, which it ports."""
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
    """`bantamkitDirFor` (runtime-ts/src/memory/store.ts):
    `bantamkit.memory.store.bantamkit_dir_for`, the hand-written Python it ports (#316 G3 is not
    generated yet), as a string or `null`."""
    from ..memory.store import bantamkit_dir_for as _for

    found = _for(_pathlib.Path(path))
    return None if found is None else str(found)


def ensure_bantamkit_gitignore(directory, created, *_):
    """`ensureBantamkitGitignore` (runtime-ts/src/memory/store.ts): the hand-written Python it
    ports (`bantamkit.memory.store.ensure_bantamkit_gitignore`, #316 G3 not generated yet)."""
    from ..memory.store import ensure_bantamkit_gitignore as _ensure

    _ensure(_pathlib.Path(directory), created=bool(created))
    return _JS_UNDEFINED


def _lock_constant(name):
    from ..storage import lock as _lock

    return getattr(_lock, name)


def exclusive(target, body, options=_JS_UNDEFINED, *_):
    """`exclusive(target, body, options)` (runtime-ts/src/storage/lock.ts): the hand-written Python
    lock it ports (`bantamkit.storage.lock.exclusive`, #316 G4 not generated yet; `--suite
    storage-lock` compares the two), with `body(held)` run inside it and its answer returned. An
    option left out takes the lock's default, as `?? LOCK_*_MS` does."""
    from ..storage.lock import exclusive as _exclusive

    kwargs = {}
    if options is not _JS_UNDEFINED and options is not None:
        if not isinstance(options, dict) or set(options) - {"waitMs", "staleMs", "pollMs"}:
            raise TypeError(
                "ts2py: lock options other than waitMs/staleMs/pollMs are outside the subset"
            )
        for js, py in (("waitMs", "wait_ms"), ("staleMs", "stale_ms"), ("pollMs", "poll_ms")):
            value = options.get(js, _JS_UNDEFINED)
            if value is not _JS_UNDEFINED and value is not None:
                kwargs[py] = value
    # J88-RF F4a: the lock file is named from the path every fs adapter hands the OS.
    with _exclusive(_node_path(target, "exclusive"), **kwargs) as held:
        return body(held)


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
    # J88-2: `storage/lock.ts`'s constants, read from the hand-written lock on first import.
    if name in ("LOCK_POLL_MS", "LOCK_STALE_MS", "LOCK_WAIT_MS"):
        value = _lock_constant(name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
