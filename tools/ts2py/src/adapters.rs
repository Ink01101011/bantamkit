//! The adapter seam (J86): an import (or a Node global) that ts2py does not compile resolves to
//! hand-written Python in `adapters.py`, and only through this table. An import with no compiled
//! module and no row here is a compile error naming it.
//!
//! Every row says why a hand-written function is faithful. Two kinds of reason are accepted:
//! Python IS the reference (the TypeScript function is a port of a CPython behaviour, so the
//! CPython behaviour is the definition), or the row reproduces a Node builtin and names the
//! measurement that pins it.

/// What an adapter provides.
#[derive(Clone, Copy, PartialEq)]
pub enum AdapterKind {
    /// A function, called as `name(...)`.
    Function,
    /// A class, constructed with `new Name(...)`, with these methods.
    Class(&'static [&'static str]),
    /// J87-3: an `Error` subclass a compiled class may extend (`class E extends BantamError {}`).
    ErrorClass,
    /// J88-2: a constant, read by name (`LOCK_STALE_MS`).
    Constant,
}

pub struct Adapter {
    /// The TypeScript module the name is imported from (normalised `.ts` path from the repository
    /// root), or `None` for a global.
    pub module: Option<&'static str>,
    /// The name as TypeScript spells it.
    pub name: &'static str,
    /// The name `adapters.py` defines.
    pub py_name: &'static str,
    pub kind: AdapterKind,
    /// Why the hand-written Python is the same function.
    pub why: &'static str,
}

pub const ADAPTERS: &[Adapter] = &[
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyFloatRepr",
        py_name: "py_float_repr",
        kind: AdapterKind::Function,
        why: "Python is the reference: the TypeScript is a port of CPython's `repr(float)` \
              (its doc comment says so), so `repr(float(x))` is the definition it ports. pyfs.ts is \
              the 1,687-line CPython OS seam and is not compiled.",
    },
    Adapter {
        module: Some("runtime-ts/src/pysem.ts"),
        name: "pyStrip",
        py_name: "py_strip",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyStrip` is CPython's `str.strip()` with no argument (pysem.ts \
              measured its 29-character set against `str.isspace()` over every codepoint). It is \
              built from a regex assembled at run time with a `$&` replacement, which ts2py refuses \
              to compile; J86 re-measured it against `str.strip()` (RULES.md, Adapters).",
    },
    Adapter {
        module: None,
        name: "TextDecoder",
        py_name: "TextDecoder",
        kind: AdapterKind::Class(&["decode"]),
        why: "Node builtin: `new TextDecoder('utf-8').decode(bytes)` is WHATWG UTF-8 decode (one \
              U+FFFD per maximal invalid subpart, a leading BOM dropped). Python's `bytes.decode(\
              'utf-8', 'replace')` substitutes the same maximal subparts; J86 measured the two equal \
              on a byte corpus (RULES.md, Adapters). J88-2: `{fatal: true}` refuses exactly where \
              `bytes.decode('utf-8')` (strict) raises, as Node's TypeError \
              ERR_ENCODING_INVALID_ENCODED_DATA, and `{ignoreBOM: true}` keeps the BOM; 40,000 \
              random byte strings equal against Node 26.13 (RULES.md, Adapters).",
    },
    Adapter {
        module: None,
        name: "Date",
        py_name: "Date",
        kind: AdapterKind::Class(&["getFullYear", "getMonth", "getDate"]),
        why: "Python is the reference: the only use is `todayLocal`, whose doc comment defines it as \
              `date.today().isoformat()` (local). The adapter is `new Date()` (no argument) with \
              the three local calendar getters, read from `datetime.datetime.now()`.",
    },
    // J87-3 (#316 G1, `pricing.ts`).
    Adapter {
        module: Some("runtime-ts/src/pysem.ts"),
        name: "pyRepr",
        py_name: "py_repr",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyRepr` is CPython's `repr(str)` (its doc comment says so, \
              and names the one drift: a codepoint whose Unicode category moved between CPython's \
              tables and Node's ICU). The hand-written pricing module quoted with `!r`.",
    },
    Adapter {
        module: Some("runtime-ts/src/pysem.ts"),
        name: "cmpCodepoint",
        py_name: "cmp_codepoint",
        kind: AdapterKind::Function,
        why: "Python is the reference: `cmpCodepoint` exists to order strings as CPython's \
              `sorted()` does, by code point (its doc comment). The adapter is the same function \
              over Python's code points (-1, 1, or the length difference).",
    },
    Adapter {
        module: Some("runtime-ts/src/assets.ts"),
        name: "assetsRoot",
        py_name: "assets_root",
        kind: AdapterKind::Function,
        why: "Python is the reference: `assetsRoot` mirrors `bantamkit.assets.assets_root()` arm for \
              arm (its doc comment); each runtime resolves its own pack. The adapter returns that \
              path as a string.",
    },
    Adapter {
        module: Some("runtime-ts/src/errors.ts"),
        name: "BantamError",
        py_name: "BantamError",
        kind: AdapterKind::ErrorClass,
        why: "Python is the reference: errors.ts says its `BantamError` is the base the Python \
              runtime exposes as `bantamkit.client.BantamError`. The adapter is that class with JS's \
              Error face (`message`, and an own `name` that is the constructing class's name, as \
              `this.name = new.target.name` sets it), built lazily so modules that never use it do \
              not import `bantamkit.client`.",
    },
    Adapter {
        module: Some("node:fs"),
        name: "existsSync",
        py_name: "exists_sync",
        kind: AdapterKind::Function,
        why: "Node builtin: true when the path can be stat'ed (symlinks followed), false on any \
              error and for a non-string argument. `os.path.exists` answers the same; J87-3 measured \
              18 path shapes (file, directory, trailing slash on a file, dangling symlink, symlink \
              loop, unsearchable parent, empty) equal (RULES.md, Adapters).",
    },
    Adapter {
        module: Some("node:fs"),
        name: "readFileSync",
        py_name: "read_file_sync",
        kind: AdapterKind::Function,
        why: "Node builtin, with the 'utf8' encoding only: the bytes decoded with one U+FFFD per \
              maximal invalid subpart and a BOM kept, which `bytes.decode('utf-8', 'replace')` \
              gives (J87-3: 30,000 random byte strings and 2,000 files read back, 0 \
              disagreements). A failure is the OSError CPython's `open()` raises.",
    },
    Adapter {
        module: Some("node:path"),
        name: "join",
        py_name: "path_join",
        kind: AdapterKind::Function,
        why: "Node builtin: lib/path.js's `posix.join` and `normalizeString` ported statement for \
              statement (`win32.join` on Windows, outside its colon and reserved-device-name rules \
              refused). J87-3: 60,000 random joins equal on posix, 41,055 equal on win32 (18,945 \
              refused) against Node 26.13's `path.posix.join` / `path.win32.join`.",
    },
    Adapter {
        module: None,
        name: "process.env",
        py_name: "process_env",
        kind: AdapterKind::Function,
        why: "Node global, read only (`process.env[name]`): each runtime reads its own process \
              environment, `undefined` when unset; `os.environ.get` is what the hand-written \
              Python read.",
    },
    // J88-2 (#316 G2: eventlog, tokenledger, storage/logsegment). Node builtins first; every one
    // is pinned against Node 26.13 by tests/g2.rs or the J88-2 measurement in RULES.md.
    Adapter {
        module: Some("node:fs"),
        name: "statSync",
        py_name: "stat_sync",
        kind: AdapterKind::Function,
        why: "Node builtin: `os.stat` (symlinks followed) as an `fs.Stats` (`Stats` below); a failure is the OSError CPython raises, whose `code` is the errno name libuv reports (tests/g2.rs: ENOENT, ENOTDIR, EACCES, ELOOP).",
    },
    Adapter {
        module: Some("node:fs"),
        name: "lstatSync",
        py_name: "lstat_sync",
        kind: AdapterKind::Function,
        why: "Node builtin: `os.lstat` as an `fs.Stats`; on Windows a junction is a symbolic link, as libuv reports one.",
    },
    Adapter {
        module: Some("node:fs"),
        name: "fstatSync",
        py_name: "fstat_sync",
        kind: AdapterKind::Function,
        why: "Node builtin: `os.fstat(fd)` as an `fs.Stats`.",
    },
    Adapter {
        module: Some("node:fs"),
        name: "Stats",
        py_name: "Stats",
        kind: AdapterKind::Class(&["isDirectory", "isFile", "isSymbolicLink"]),
        why: "Node builtin: `fs.Stats`, with `size`, `mtimeMs` (`sec * 1e3 + nsec / 1e6`, as Node combines libuv's two fields) and the three type tests, each the `stat` module's S_IS* test of `st_mode`.",
    },
    Adapter {
        module: Some("node:fs"),
        name: "readdirSync",
        py_name: "readdir_sync",
        kind: AdapterKind::Function,
        why: "Node builtin: the names `os.listdir` gives, in the directory's own order, `.`/`..` left out, decoded from bytes as Node decodes them (UTF-8 with U+FFFD).",
    },
    Adapter {
        module: Some("node:fs"),
        name: "mkdirSync",
        py_name: "mkdir_sync",
        kind: AdapterKind::Function,
        why: "Node builtin, `{recursive: true}` only: `os.makedirs(exist_ok=True)` (EEXIST for a file in the way, ENOTDIR for a file on the path, as libuv's recursive mkdir); tests/g2.rs.",
    },
    Adapter {
        module: Some("node:fs"),
        name: "renameSync",
        py_name: "rename_sync",
        kind: AdapterKind::Function,
        why: "Node builtin: rename(2), replacing the target (`os.replace`, MoveFileEx with replace on Windows, as libuv).",
    },
    Adapter {
        module: Some("node:fs"),
        name: "rmSync",
        py_name: "rm_sync",
        kind: AdapterKind::Function,
        why: "Node builtin, `{force: true}` only: unlink, a missing path ignored, a directory refused with an error carrying a string `code` (Node ERR_FS_EISDIR, here CPython's IsADirectoryError).",
    },
    Adapter {
        module: Some("node:fs"),
        name: "linkSync",
        py_name: "link_sync",
        kind: AdapterKind::Function,
        why: "Node builtin: link(2), which `os.link` calls.",
    },
    Adapter {
        module: Some("node:fs"),
        name: "openSync",
        py_name: "open_sync",
        kind: AdapterKind::Function,
        why: "Node builtin: `stringToFlags` for r, r+, w, wx, w+, a, ax, a+ (lib/internal/fs/utils.js), mode 0o666, O_BINARY on Windows (libuv never translates newlines); the descriptor is the int `os.open` returns.",
    },
    Adapter {
        module: Some("node:fs"),
        name: "closeSync",
        py_name: "close_sync",
        kind: AdapterKind::Function,
        why: "Node builtin: close(2) (`os.close`).",
    },
    Adapter {
        module: Some("node:fs"),
        name: "writeSync",
        py_name: "write_sync",
        kind: AdapterKind::Function,
        why: "Node builtin, `(fd, buffer)` only: one write(2) of the whole buffer answering the count, as Node's single `writeBuffer` (neither loops).",
    },
    Adapter {
        module: Some("node:fs"),
        name: "readSync",
        py_name: "read_sync",
        kind: AdapterKind::Function,
        why: "Node builtin, `(fd, buffer, offset, length, position)`: one pread(2) into the buffer (lseek/read/lseek back on Windows, as libuv restores the pointer), answering the count.",
    },
    Adapter {
        module: Some("node:fs"),
        name: "appendFileSync",
        py_name: "append_file_sync",
        kind: AdapterKind::Function,
        why: "Node builtin, `(path, buffer)`: opened `a` with mode 0o666 and written to the end (Node loops until every byte is written; so does this).",
    },
    Adapter {
        module: Some("node:path"),
        name: "dirname",
        py_name: "path_dirname",
        kind: AdapterKind::Function,
        why: "Node builtin: lib/path.js `posix.dirname` / `win32.dirname` ported statement for statement; J88-2: 60,000 random paths equal on each (tests/g2.rs pins the edge shapes).",
    },
    Adapter {
        module: Some("node:path"),
        name: "basename",
        py_name: "path_basename",
        kind: AdapterKind::Function,
        why: "Node builtin, no suffix: lib/path.js `posix.basename` / `win32.basename` ported; J88-2: 60,000 random paths equal on each.",
    },
    Adapter {
        module: Some("node:zlib"),
        name: "gzipSync",
        py_name: "gzip_sync",
        kind: AdapterKind::Function,
        why: "Node builtin, RULED: Node's bundled (Chromium) zlib writes a different deflate stream, which no Python library reproduces (J88-2: 300 of 300 inputs differ against zlib.compressobj(6, 8, 31) too), so the member is `gzip.compress(mtime=0)`, the reference's bytes, and only the DECOMPRESSED bytes are compared (the `storage-log` ruling: case).",
    },
    Adapter {
        module: Some("node:zlib"),
        name: "gunzipSync",
        py_name: "gunzip_sync",
        kind: AdapterKind::Function,
        why: "Node builtin: `gzip.decompress` (members joined, zero padding ignored); where Node refuses, an Error with Node's code (empty or truncated Z_BUF_ERROR, bad header/CRC/trailing garbage Z_DATA_ERROR). J88-2 measured nine shapes; CPython answering empty bytes for an empty input is the one it had to refuse.",
    },
    Adapter {
        module: Some("node:crypto"),
        name: "randomBytes",
        py_name: "random_bytes",
        kind: AdapterKind::Function,
        why: "Node builtin: `os.urandom` (both the OS CSPRNG); the bytes are random either side, only their count and use are compared.",
    },
    Adapter {
        module: None,
        name: "Buffer.from",
        py_name: "buffer_from",
        kind: AdapterKind::Function,
        why: "Node global, `(string, 'utf8')` only: UTF-8, a lone surrogate written EF BF BD as Node's encoder writes it (tests/g2.rs).",
    },
    Adapter {
        module: None,
        name: "Buffer.concat",
        py_name: "buffer_concat",
        kind: AdapterKind::Function,
        why: "Node global: the buffers joined into a new one (a bytes join).",
    },
    Adapter {
        module: None,
        name: "Buffer.alloc",
        py_name: "buffer_alloc",
        kind: AdapterKind::Function,
        why: "Node global: `size` zero bytes, writable in place (a `bytearray`).",
    },
    Adapter {
        module: None,
        name: "process.env.all",
        py_name: "process_env_all",
        kind: AdapterKind::Function,
        why: "Node global, `process.env` read as a value and only read: a snapshot of this process's environment as a plain object (`dict(os.environ)`), taken where JS reads the live object. Each runtime reads its own environment.",
    },
    Adapter {
        module: None,
        name: "process.pid",
        py_name: "process_pid",
        kind: AdapterKind::Function,
        why: "Node global: this process's id (`os.getpid()`), each runtime its own.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "cmpCodepoint",
        py_name: "cmp_codepoint",
        kind: AdapterKind::Function,
        why: "Python is the reference: pyfs.ts re-exports pysem.ts's `cmpCodepoint` (the row above).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyExists",
        py_name: "py_exists",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyExists` is `Path.exists()` (its doc comment: it swallows exactly pathlib's ignored errnos and raises the rest), so `Path(p).exists()` is the definition.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyIsDir",
        py_name: "py_is_dir",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyIsDir` is `Path.is_dir()` (its doc comment), raising for EACCES as CPython 3.12 does.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyJoin",
        py_name: "py_join",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyJoin` is `PurePath(*parts)` (its doc comment), so `str(PurePath(*parts))`.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyParent",
        py_name: "py_parent",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyParent` is `PurePath.parent` (its doc comment).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyName",
        py_name: "py_name",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyName` is `PurePath.name` (its doc comment).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "osErrorClassName",
        py_name: "os_error_class_name",
        kind: AdapterKind::Function,
        why: "Python is the reference: CPython's `OSError.__new__` errnomap for the errnos pyfs raises; the adapter holds the same eleven-row table and its `OSError` default.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "PyOSError",
        py_name: "PyOSError",
        kind: AdapterKind::Class(&[]),
        why: "Python is the reference: `PyOSError` is the port of CPython's `OSError` (its doc comment), so `instanceof PyOSError` is `isinstance(x, OSError)`; it is never constructed by compiled code.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/store.ts"),
        name: "bantamkitDirFor",
        py_name: "bantamkit_dir_for",
        kind: AdapterKind::Function,
        why: "Python is the reference: store.ts ports `bantamkit.memory.store.bantamkit_dir_for` (#316 G3, not generated yet; `--suite store` compares them), called on `Path(p)` and answered as a string or null.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/store.ts"),
        name: "ensureBantamkitGitignore",
        py_name: "ensure_bantamkit_gitignore",
        kind: AdapterKind::Function,
        why: "Python is the reference: store.ts ports `bantamkit.memory.store.ensure_bantamkit_gitignore` (#316 G3, not generated yet; `--suite store` compares them).",
    },
    Adapter {
        module: Some("runtime-ts/src/storage/lock.ts"),
        name: "exclusive",
        py_name: "exclusive",
        kind: AdapterKind::Function,
        why: "Python is the reference: lock.ts is the port of `bantamkit.storage.lock.exclusive` (#316 G4, not generated yet; `--suite storage-lock` compares the two), entered as a context manager around `body(held)`, `waitMs`/`staleMs`/`pollMs` passed as its keyword arguments.",
    },
    Adapter {
        module: Some("runtime-ts/src/storage/lock.ts"),
        name: "LOCK_STALE_MS",
        py_name: "LOCK_STALE_MS",
        kind: AdapterKind::Constant,
        why: "Python is the reference: `bantamkit.storage.lock.LOCK_STALE_MS`, the same 10,000 the port declares (`--suite storage-lock`).",
    },
    Adapter {
        module: Some("runtime-ts/src/storage/lock.ts"),
        name: "LOCK_POLL_MS",
        py_name: "LOCK_POLL_MS",
        kind: AdapterKind::Constant,
        why: "Python is the reference: `bantamkit.storage.lock.LOCK_POLL_MS`, the same 5 the port declares (`--suite storage-lock`).",
    },
];

/// The adapter for `name` imported from `module` (a normalised `.ts` path), if one is declared.
pub fn import(module: &str, name: &str) -> Option<&'static Adapter> {
    ADAPTERS
        .iter()
        .find(|a| a.module == Some(module) && a.name == name)
}

/// The adapter for the global `name`, if one is declared.
pub fn global(name: &str) -> Option<&'static Adapter> {
    ADAPTERS
        .iter()
        .find(|a| a.module.is_none() && a.name == name)
}

/// Method names the adapter classes declare.
pub fn class_methods() -> impl Iterator<Item = &'static str> {
    ADAPTERS.iter().flat_map(|a| match a.kind {
        AdapterKind::Class(methods) => methods.iter().copied(),
        AdapterKind::Function | AdapterKind::ErrorClass | AdapterKind::Constant => {
            [].iter().copied()
        }
    })
}
