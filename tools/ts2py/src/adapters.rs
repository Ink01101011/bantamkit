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
    /// J89-4a: a class with these methods whose calls dispatch (`_js_invoke` / `_js_dispatch`)
    /// only in a module that imports it, so its method names do not reach every module of the
    /// call (a `Set`'s `.add` elsewhere stays `_js_m_add`). Naming one of them as a value is not
    /// refused at compile time: on an instance the runtime refuses it (`_js_object_get`), and on
    /// anything else it is a property read (`pool.names` of a plain object), as in JS.
    ImportedClass(&'static [&'static str]),
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
        why: "Reached only by a call that compiles a module importing it WITHOUT store.ts (since J89-4b the committed event log imports the compiled store; ts2py's own G2 tests compile the event log alone): `bantamkit.memory.store.bantamkit_dir_for`, the shim over the generated function, called on `Path(p)` and answered as a string or null.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/store.ts"),
        name: "ensureBantamkitGitignore",
        py_name: "ensure_bantamkit_gitignore",
        kind: AdapterKind::Function,
        why: "Reached only by a call that compiles a module importing it WITHOUT store.ts (see `bantamkitDirFor`): `bantamkit.memory.store.ensure_bantamkit_gitignore`, the shim over the generated function.",
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
    // J89-2 (#316 G3: memory/usage, memory/retrieval). `pysem.ts` rows first: each TypeScript
    // function is a port of the CPython function named, so CPython is the definition (pysem.ts,
    // "the memory modules' float and text semantics", has the measurement).
    Adapter {
        module: Some("runtime-ts/src/pysem.ts"),
        name: "pyRoundFloat9",
        py_name: "py_round_float9",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyRoundFloat9` is CPython's `round(x, 9)` (its doc comment: `double_round`, half to even on the exact binary value). J89-2: 40,000 seeded doubles (and `recall-retrieval`'s 1,000) equal bit for bit against Node.",
    },
    Adapter {
        module: Some("runtime-ts/src/pysem.ts"),
        name: "pyLog",
        py_name: "py_log",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyLog` is CPython's `math.log` (retrieval.py's idf). Node's `Math.log` differs from it in the last bit on 549 of 30,000 doubles (J89-2, arm64), and no Python helper can reproduce V8's bits on every platform (a port of its fdlibm `log` still differs on 86 of 40,021 on arm64); every score it feeds is rounded to nine decimals.",
    },
    Adapter {
        module: Some("runtime-ts/src/pysem.ts"),
        name: "pyLog1p",
        py_name: "py_log1p",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyLog1p` is CPython's `math.log1p` (retrieval.py's usage weight); Node's `Math.log1p` differs in the last bit on 561 of 30,000 doubles (J89-2), absorbed as `pyLog`'s is.",
    },
    Adapter {
        module: Some("runtime-ts/src/pysem.ts"),
        name: "pyPow",
        py_name: "py_pow",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyPow` is CPython's `float ** float` (usage.py's `0.5 ** (age / half)`), except that where `**` overflows (CPython raises OverflowError) it answers Infinity, as `Math.pow` does (J89-3, `--suite recall-usage` `future:`); a negative base is refused (Python answers a complex). Node's `Math.pow(0.5, y)` agreed with it on 30,000 of 30,000 doubles (J89-2, arm64); ts2py refuses `Math.pow` itself (pysem.ts says why).",
    },
    Adapter {
        module: Some("runtime-ts/src/pysem.ts"),
        name: "pyNfkcLower",
        py_name: "py_nfkc_lower",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyNfkcLower` is `unicodedata.normalize('NFKC', s).lower()` (retrieval.py's tokenizer); Node's spelling differs only where its ICU has Unicode data CPython's tables do not (code points CPython leaves unassigned).",
    },
    Adapter {
        module: Some("runtime-ts/src/pysem.ts"),
        name: "pyWordchar",
        py_name: "py_wordchar",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyWordchar` is `unicodedata.category(ch)[0] in 'LNM'` (retrieval.py's `_wordchar`), with `pyNfkcLower`'s Unicode-version drift.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyRealpath",
        py_name: "py_realpath",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyRealpath` is the port of `os.path.realpath(strict=False)` (J89-1F, its doc comment), so the adapter is `os.path.realpath` of the path as the OS receives it (the G2 path policy, `_os_char`: a lone surrogate os cannot encode is U+FFFD), the hand-written `usage.os_realpath`. `--suite recall-usage` and `--suite skill-layer` pin J89-1F's dangling-symlink and surrogate cases.",
    },
    Adapter {
        module: Some("node:crypto"),
        name: "createHash",
        py_name: "create_hash",
        kind: AdapterKind::Function,
        why: "Node builtin, `'sha256'` or (J89-5a) `'sha1'`: a `Hash` (below) over `hashlib.sha256` / `hashlib.sha1`.",
    },
    Adapter {
        module: Some("node:crypto"),
        name: "Hash",
        py_name: "Hash",
        kind: AdapterKind::Class(&["update", "digest"]),
        why: "Node builtin: `hash.update(string, 'utf8')` hashes the string's UTF-8, a lone surrogate as U+FFFD (EF BF BD), as Node's encoder writes it; under the G2 path policy (its only caller hashes a path, `storeId`) a POSIX surrogateescape code point U+DC80..U+DCFF is the real byte it stands for (the ruled target-specific difference, docs/porting.md). `digest('hex')` is `hexdigest()`; a finished hash is refused, as Node throws ERR_CRYPTO_HASH_FINALIZED. J89-5a: `hash.update(buffer)` (no encoding) hashes the Buffer's bytes as they are, as Node does (queries.ts hashes a sidecar's and a fact file's bytes).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/queries.ts"),
        name: "CountsView",
        py_name: "CountsView",
        kind: AdapterKind::Class(&["scan"]),
        why: "Declared for its `scan` method only: retrieval's `bm25Rows` calls `row.scan(...)` on a row that has one (`'scan' in row`). J89-5a: queries.ts is compiled and the class with it (`_generated/queries.py`'s `_CountsView`); it is not exported, so its method names stay in its module (`scan_module`), and this row is what still names `scan` for retrieval, whose call dispatches to the compiled class (`_js_invoke`). The adapter class itself is never built: the queries shim answers dicts, which the retrieval shim hands over as Maps, and `'scan' in` a Map is false.",
    },
    // J89-4a (#316 G3 U2: memory/store). Every import of store.ts that is not compiled.
    Adapter {
        module: Some("node:os"),
        name: "homedir",
        py_name: "homedir",
        kind: AdapterKind::Function,
        why: "Python is the reference: every `homedir()` in store.ts stands where store.py passes `Path.home()` (the hot index, the cold index and the usage ledger), so the adapter is `str(Path.home())`. Node's `os.homedir()` reads the same `HOME` (`USERPROFILE` on Windows); the two differ only for a set but empty `HOME` (Node answers '', `Path.home()` '/'), where the reference's answer is taken.",
    },
    Adapter {
        module: Some("runtime-ts/src/pysem.ts"),
        name: "pySearchWord",
        py_name: "py_search_word",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pySearchWord(alternatives, text)` is `re.compile(r'\\b(' + alternatives + r')\\b', re.IGNORECASE).search(text)`'s group 1 (its doc comment; store.py's `_DONE_WORD_RE`), the regex J89-1F swept against CPython over every code point and J89-2 over every letter's case-fold set (`--suite store`). Moved out of store.ts because its pattern is assembled at run time.",
    },
    Adapter {
        module: Some("runtime-ts/src/storage/hotindex.ts"),
        name: "HotIndex",
        py_name: "HotIndex",
        kind: AdapterKind::ImportedClass(&[
            "cols",
            "exists",
            "fileOf",
            "invalidate",
            "lensTotal",
            "names",
            "parseFile",
            "refresh",
            "segments",
        ]),
        why: "Python is the reference: hotindex.ts is the port of `bantamkit.storage.hotindex.HotIndex` (#204; #316 G4 generates it later; `--suite store` and `recall-index` compare the two over the same index files). The adapter is that class with the TypeScript spelling: `names()` / `segments()` / `skipped` as read-only Maps over the dicts it holds, `lensTotal()` / `fileOf()` / `parseFile()` (a doc, or the reason string where Python answers `(None, reason)`) by the same functions, and a native `BantamError` restated as the adapter's so a compiled `catch` sees it.",
    },
    Adapter {
        module: Some("runtime-ts/src/storage/hotindex.ts"),
        name: "INDEX_DIR_ENV",
        py_name: "INDEX_DIR_ENV",
        kind: AdapterKind::Constant,
        why: "Python is the reference: `bantamkit.storage.hotindex.INDEX_DIR_ENV`, the same `BANTAMKIT_INDEX_DIR` the port declares.",
    },
    // J89-5 (#316 G3 U3: memory/native).
    Adapter {
        module: Some("runtime-ts/src/storage/hotindex.ts"),
        name: "DUPLICATE",
        py_name: "DUPLICATE",
        kind: AdapterKind::Constant,
        why: "Python is the reference: `bantamkit.storage.hotindex.DUPLICATE`, the same `duplicate name` sentence head the port declares (the native index and the native layer report a second file claiming a name with it).",
    },
    Adapter {
        module: Some("runtime-ts/src/storage/hotindex.ts"),
        name: "parseNative",
        py_name: "parse_native",
        kind: AdapterKind::Function,
        why: "Python is the reference: `parseNative` is `divergence.parse_fact` for the native shape (its doc comment), so the adapter is that function, answering the name, description, type and body it read as the object the TypeScript returns (`meta`, which no compiled caller reads, is not carried), and its `MemoryValidationError` restated as the adapter's `BantamError` with the same message, so a compiled `catch` sees it (`--suite store`, `skill-layer` and `hooks` compare the native layer over the same files).",
    },
    Adapter {
        module: Some("runtime-ts/src/storage/coldindex.ts"),
        name: "ColdIndex",
        py_name: "ColdIndex",
        kind: AdapterKind::ImportedClass(&["add", "allDocs", "doc", "query", "reset"]),
        why: "Python is the reference: coldindex.ts is the port of `bantamkit.storage.coldindex.ColdIndex` (#204; #316 G4 generates it later; `--suite store` `include_archived` cases compare the two). The adapter is that class with the TypeScript spelling; `add` takes a Map, `query` answers `[name, segment, tf]` lists, and a Python `ColdIndexError` is restated as the adapter's (below).",
    },
    Adapter {
        module: Some("runtime-ts/src/storage/coldindex.ts"),
        name: "ColdIndexError",
        py_name: "ColdIndexError",
        kind: AdapterKind::ErrorClass,
        why: "Python is the reference: `bantamkit.storage.coldindex.ColdIndexError`, raised by the `ColdIndex` adapter with that error's message as a JS Error (`name` 'ColdIndexError') so a compiled `catch` and `instanceof` see it as Node's.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyyaml.ts"),
        name: "PyScalar",
        py_name: "PyScalar",
        kind: AdapterKind::Class(&[]),
        why: "The class ts2py compiled from this same TypeScript (`_generated/pyyaml.py`, the #315 codec call), so `instanceof PyScalar` is `isinstance` of the class the codec builds; imported lazily.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/factfile.ts"),
        name: "extraOf",
        py_name: "extra_of",
        kind: AdapterKind::Function,
        why: "The function ts2py compiled from this same TypeScript (`_generated/factfile.py`, the #315 codec call, which stays a call of its own), imported lazily.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/factfile.ts"),
        name: "formatFact",
        py_name: "format_fact",
        kind: AdapterKind::Function,
        why: "The function ts2py compiled from this same TypeScript (`_generated/factfile.py`, the #315 codec call, which stays a call of its own), imported lazily. J89-4b decides the Python-side boundary (factcodec's PyYAML fallback, #315's owner ruling) when the store is generated.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/factfile.ts"),
        name: "lifecycleOf",
        py_name: "lifecycle_of",
        kind: AdapterKind::Function,
        why: "The function ts2py compiled from this same TypeScript (`_generated/factfile.py`, the #315 codec call, which stays a call of its own), imported lazily.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/factfile.ts"),
        name: "parseFrontmatter",
        py_name: "parse_frontmatter",
        kind: AdapterKind::Function,
        why: "The function ts2py compiled from this same TypeScript (`_generated/factfile.py`, the #315 codec call, which stays a call of its own), imported lazily. J89-4b decides the Python-side boundary (factcodec's PyYAML fallback, #315's owner ruling) when the store is generated.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/factfile.ts"),
        name: "pyList",
        py_name: "py_list",
        kind: AdapterKind::Function,
        why: "The function ts2py compiled from this same TypeScript (`_generated/factfile.py`, the #315 codec call, which stays a call of its own), imported lazily.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/factfile.ts"),
        name: "pySplit",
        py_name: "py_split",
        kind: AdapterKind::Function,
        why: "The function ts2py compiled from this same TypeScript (`_generated/factfile.py`, the #315 codec call, which stays a call of its own), imported lazily.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/factfile.ts"),
        name: "pyTruthy",
        py_name: "py_truthy",
        kind: AdapterKind::Function,
        why: "The function ts2py compiled from this same TypeScript (`_generated/factfile.py`, the #315 codec call, which stays a call of its own), imported lazily.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/factfile.ts"),
        name: "todayLocal",
        py_name: "today_local",
        kind: AdapterKind::Function,
        why: "The function ts2py compiled from this same TypeScript (`_generated/factfile.py`, the #315 codec call, which stays a call of its own), imported lazily.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/factfile.ts"),
        name: "pyStrip",
        py_name: "py_strip",
        kind: AdapterKind::Function,
        why: "factfile.ts re-exports pysem.ts's `pyStrip` (the row above: Python's `str.strip()`).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/factfile.ts"),
        name: "VALID_OUTCOMES",
        py_name: "VALID_OUTCOMES",
        kind: AdapterKind::Constant,
        why: "The constant ts2py compiled from this same TypeScript (`_generated/factfile.py`'s `VALID_OUTCOMES`, `['error', 'success']`), imported lazily.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "asPyOSError",
        py_name: "as_py_os_error",
        kind: AdapterKind::Function,
        why: "Python is the reference: `asPyOSError` restates a Node fs rejection as the `OSError` CPython raises; every fs adapter already raises CPython's own `OSError`, so the adapter answers an `OSError` unchanged (a missing `filename` filled from the fallback paths, as the port fills it) and re-raises anything else, which no CPython call would have raised.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "matchesMd",
        py_name: "matches_md",
        kind: AdapterKind::Function,
        why: "Python is the reference: `matchesMd` is `fnmatch.fnmatch(name, '*.md')` (its doc comment), which the adapter calls.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyLexists",
        py_name: "py_lexists",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyLexists` is `os.path.lexists` (its doc comment).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyOSErrorText",
        py_name: "py_os_error_text",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyOSErrorText` is `str(e)` of the CPython `OSError` a `PyOSError` ports (J89-4b); in Python every `PyOSError` is that `OSError`, whose text a compiled `.message` read may not ask for.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyOSErrorStrerror",
        py_name: "py_os_error_strerror",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyOSErrorStrerror` is the CPython `OSError`'s `strerror` (J89-4b), as the reference's f-string prints it.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyMkdirParents",
        py_name: "py_mkdir_parents",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyMkdirParents` is `Path.mkdir(parents=True, exist_ok=True)` (its doc comment).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyMtimeDate",
        py_name: "py_mtime_date",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyMtimeDate` is `date.fromtimestamp(path.stat().st_mtime).isoformat()` (its doc comment), local time.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyParents",
        py_name: "py_parents",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyParents` is `PurePath.parents` (its doc comment), as strings.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyReadText",
        py_name: "py_read_text",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyReadText` is `Path.read_text(encoding='utf-8')` (its doc comment: strict UTF-8 and universal newlines); a decode failure is the `PyUnicodeDecodeError` below with CPython's message.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyReplace",
        py_name: "py_replace",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyReplace` is `os.replace` (its doc comment, `Path.replace`).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyScandirNames",
        py_name: "py_scandir_names",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyScandirNames` is `os.scandir(directory)` reduced to names (its doc comment), in the directory's order.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyScandirProbe",
        py_name: "py_scandir_probe",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyScandirProbe` is `with os.scandir(directory): pass` (its doc comment).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pySuffix",
        py_name: "py_suffix",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pySuffix` is `PurePath.suffix` (its doc comment).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyUnlink",
        py_name: "py_unlink",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyUnlink` is `Path.unlink()` (its doc comment).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyWriteText",
        py_name: "py_write_text",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyWriteText` is `Path.write_text(text, encoding='utf-8')` (its doc comment, newline translation included).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyWriteTextAtomic",
        py_name: "py_write_text_atomic",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyWriteTextAtomic` is J89-1F's port of store.py's `_write_text_atomic` (a `<path>.<pid>.<8 hex>.tmp` opened `x`, written by the buffered writer, `os.replace`d onto `path`, unlinked on any failure), which the adapter carries statement for statement so it outlives store.py's logic (#316 G3 U2).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "sortedPathNames",
        py_name: "sorted_path_names",
        kind: AdapterKind::Function,
        why: "Python is the reference: `sortedPathNames` is `sorted(directory / name for name in names)` reduced to names (its doc comment): a stable sort by `os.path.normcase` of each name, by code point.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "PyUnicodeDecodeError",
        py_name: "PyUnicodeDecodeError",
        kind: AdapterKind::ErrorClass,
        why: "Python is the reference: `PyUnicodeDecodeError` is the port of CPython's `UnicodeDecodeError` (its doc comment); the `pyReadText` adapter raises it with `str()` of the one CPython raised as its message and `name` 'UnicodeDecodeError', so a compiled `catch` sees it (a `ValueError` is not something a JS `catch` could hold).",
    },
    Adapter {
        module: None,
        name: "Buffer.byteLength",
        py_name: "buffer_byte_length",
        kind: AdapterKind::Function,
        why: "Node global, `(string, 'utf8')` only: the length of the string's UTF-8, a lone surrogate counted as U+FFFD's three bytes, as `Buffer.from` writes it (tests/g3.rs).",
    },
    // J89-5a (#316 G3 U3: memory/queries). Every import of queries.ts that is not compiled.
    Adapter {
        module: Some("runtime-ts/src/pyjson.ts"),
        name: "parseJson",
        py_name: "parse_json",
        kind: AdapterKind::Function,
        why: "Python is the reference: `parseJson` is `json.loads` (its doc comment; pyjson.ts is the port of CPython's json module). The adapter is `json.loads`, its value answered as the tagged `PyValue` the TypeScript returns (`{t, v}`: an int as a BigInt, a dict as a Map in the dict's order, a repeated key at its first position with its last value, as both keep it), and a refusal is `PyJSONDecodeError` with CPython's message so a compiled `catch` sees it. The hand-written queries module read every sidecar with exactly this `json.loads` (`--suite recall-queries` reads malformed, BOM-led and non-int-`v` sidecars on both sides).",
    },
    Adapter {
        module: Some("runtime-ts/src/pyjson.ts"),
        name: "dumpJson",
        py_name: "dump_json",
        kind: AdapterKind::Function,
        why: "Python is the reference: `dumpJson` is `json.dumps` with the four options it ports (`indent`, `sort_keys`, `ensure_ascii`, `separators`), `allow_nan` and float `repr` as CPython's. The adapter is `json.dumps` of the `PyValue` untagged; the hand-written queries module wrote the sidecar with exactly `json.dumps(ensure_ascii=False, sort_keys=True, separators=(',', ':'))` (`hotindex.dumps`), which `--suite recall-queries` compares byte for byte.",
    },
    Adapter {
        module: Some("runtime-ts/src/pyjson.ts"),
        name: "encodeBasestringAscii",
        py_name: "encode_basestring_ascii",
        kind: AdapterKind::Function,
        why: "Python is the reference: `encodeBasestringAscii` is CPython's `py_encode_basestring_ascii` (its doc comment); the adapter is `json.encoder.encode_basestring_ascii`, the same function (a lone surrogate and each half of an astral character as a lowercase `\\uXXXX`). The term cache's bytes are compared by `--suite recall-queries`.",
    },
    Adapter {
        module: Some("runtime-ts/src/storage/hotindex.ts"),
        name: "sha16",
        py_name: "sha16",
        kind: AdapterKind::Function,
        why: "Python is the reference: `sha16` is the port of `bantamkit.storage.hotindex.sha16` (#204), the function the hand-written queries module keyed the sidecar and the term cache with; the adapter is that function.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyDecodeUtf8",
        py_name: "py_decode_utf8",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyDecodeUtf8` is CPython's strict `bytes.decode('utf-8')`, a leading BOM kept as U+FEFF (its doc comment, measured over 64,028,929 byte sequences). The adapter is that decode; a refusal is the `PyUnicodeDecodeError` (above) with CPython's message, so a compiled `catch` sees it.",
    },
    Adapter {
        module: Some("node:fs"),
        name: "writeFileSync",
        py_name: "write_file_sync",
        kind: AdapterKind::Function,
        why: "Node builtin, `(path, string, 'utf8')` only: opened `w` (O_TRUNC | O_CREAT | O_WRONLY, mode 0o666 under the umask, binary on Windows) and every byte of the string's UTF-8 written (Node loops until it is; a lone surrogate is U+FFFD's three bytes, as Node's encoder writes it), the path under the G2 path policy. The flags and mode are what `Path.write_text` opens with, which the hand-written queries module used for the sidecar and the term cache (tests/g3_store.rs `j89_5a_*`).",
    },
    // J89-5b (#316 G3 U3: memory/layers). Every import of layers.ts that is not compiled.
    Adapter {
        module: Some("runtime-ts/src/memory/grantconfig.ts"),
        name: "firstTokenTab",
        py_name: "first_token_tab",
        kind: AdapterKind::Function,
        why: "Python is the reference, by the orchestrator's ruling on J89-5's stop (option b: Python keeps PyYAML for the config, as #315 kept it for fact files). `firstTokenTab` is the port's search for the byte PyYAML refuses with `found character '\\t' that cannot start any token` (its doc comment); the reference reads that byte off the error, `_token_tab`: a `ScannerError` with exactly that problem and a mark. The adapter runs `yaml.safe_load` (once per text, shared with `parseConfigDocument`) and answers that mark's 1-based `[line, column]`, or null. An exception `load_grants` never caught (anything but `yaml.YAMLError`, e.g. CPython's `ValueError` from an implicit timestamp that is no date) is raised here, outside the compiled `try`, so it leaves `loadGrants` as it left `load_grants`.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/grantconfig.ts"),
        name: "parseConfigDocument",
        py_name: "parse_config_document",
        kind: AdapterKind::Function,
        why: "Python is the reference (the ruling above): `parseConfigDocument` is `yaml.safe_load` reduced to the three answers `load_grants` asks (its doc comment). The adapter is `yaml.safe_load` of the same text, its value converted to the `ConfigDocument` the compiled validator reads: `None` is `{kind: 'null'}`, a dict `{kind: 'mapping', entries}` (a Map of its `str` keys; `data.get('extra_stores')` matches no other key), anything else `{kind: 'other'}`; an entry that is a list is `{kind: 'seq', items}` with each `str` item `{kind: 'str', value}` and any other `{kind: 'other', value: null}` (`isinstance(p, str)` is the one question asked of an item), any other entry `{kind: 'other', value: null}`. A `yaml.YAMLError` is a `_JsError` whose message is `str(e)`, the text the reference interpolates (`--suite recall-strings` config battery and `RULED: config outside the reader's language`).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyIsFile",
        py_name: "py_is_file",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyIsFile` is `Path.is_file()` (its doc comment), raising for EACCES as CPython 3.12 does.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyRepr",
        py_name: "py_repr",
        kind: AdapterKind::Function,
        why: "Python is the reference: pyfs.ts re-exports pysem.ts's `pyRepr`, CPython's `repr(str)` (the J87-3 row).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyResolve",
        py_name: "py_resolve",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyResolve` is `Path.resolve()` with `strict=False` (its doc comment: `posixpath.realpath`, then pathlib's ELOOP check), so `str(Path(p).resolve())`.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyStatIsDir",
        py_name: "py_stat_is_dir",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyStatIsDir` is `stat.S_ISDIR(os.stat(p).st_mode)`, unguarded (its doc comment; `_pinned_store`'s check).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyCwd",
        py_name: "py_cwd",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyCwd` is `Path.cwd()`, `os.getcwd()` as a string (`_resolved_base`).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyExpanduser",
        py_name: "py_expanduser",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyExpanduser` is `Path(raw).expanduser()` (its doc comment), so `str(Path(raw).expanduser())`, its `RuntimeError` included; `~<another user>` is the ruled difference (`RULED: ~someone-else needs a passwd lookup`), and Python keeps its passwd lookup.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyIsAbsolute",
        py_name: "py_is_absolute",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyIsAbsolute` is `PurePath.is_absolute()` (its doc comment).",
    },
    // J89-5c (#316 G3 U3: memory/dream). dreamre.ts holds the patterns dream.ts built at run time
    // from pysem's CPython classes under the `u` flag; each is a port of a dream.py pattern.
    Adapter {
        module: Some("runtime-ts/src/memory/dreamre.ts"),
        name: "pyRelativeScan",
        py_name: "py_relative_scan",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyRelativeScan` is `dream.py`'s `_RELATIVE.finditer(body)` with `_STAMPED.match` applied after each match (its doc comment; the pattern is a port of `_RELATIVE`, `\\b(?P<simple>today|tonight|yesterday|tomorrow)\\b|...` under `re.IGNORECASE`, whose `\\s`, `\\d`, `\\b` and case folding dream.ts's header measured). The adapter runs those two CPython patterns, unchanged from the hand-written dream.py, and answers each match as `{lead, term, stamped, simple, now, digits, unit}` and the rest of the body as `tail` (no string position crosses the seam: a position is a UTF-16 unit in Node and a code point here).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/dreamre.ts"),
        name: "pyUnresolvedTerms",
        py_name: "py_unresolved_terms",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyUnresolvedTerms` is `[m.group(0) for m in _UNRESOLVED.finditer(body)]`, the port of `dream.py`'s `_UNRESOLVED` (its doc comment). The adapter runs that CPython pattern, unchanged.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/dreamre.ts"),
        name: "pySlotGroups",
        py_name: "py_slot_groups",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pySlotGroups` is `_SLOT.match(_BULLET.sub('', text))`'s `subject` and `value` groups, the port of `dream.py`'s two patterns (its doc comment; `{1,60}` counts code points under `u`, as `re` does). The adapter runs those CPython patterns, unchanged, and answers `[subject, value]` or null.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/dreamre.ts"),
        name: "pySubSpaces",
        py_name: "py_sub_spaces",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pySubSpaces` is `re.sub(r'\\s+', ' ', text)` with CPython's 29-codepoint `\\s` (`pysem.PY_WS_CLASS`), the call `dream.py`'s `collapse` makes. The adapter is that call.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/dreamre.ts"),
        name: "pyIntDigits",
        py_name: "py_int_digits",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyIntDigits` is CPython's `int(text)` of a `\\d+` run (its doc comment), the call `dream.py`'s `_resolve` makes. The adapter is `int(text)`, its `ValueError` past `sys.get_int_max_str_digits()` digits included, answered as the double a JS number is (a value past the largest double is infinity, which Node's sum overflows to; every count past 999,999,999 meets `addDays`'s cap either way). Two inputs where Node's walk-back differs from `int()` are pinned UNRULED in `--suite dream`, unchanged by generation.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/dreamre.ts"),
        name: "formatFixed3",
        py_name: "format_fixed3",
        kind: AdapterKind::Function,
        why: "Python is the reference: `formatFixed3` is `f\"{value:.3f}\"`, round half to even on the exact binary value (its doc comment), which CPython's `format` is; the one spelling it adds is no sign on a value that rounds to zero (`-0.0` is `0.000`), and `inf` / `-inf` / `nan`. dream.ts only re-exports it (component.ts prints the two similarity figures with it); the compiled dream never calls it. J89-5c fuzzed it against Node (RULES.md, Adapters).",
    },
    // J89-6 (#316 G3 U4: memory/component). The skill layer, the touch modules, the asset pack and
    // the reply-language frame are not compiled; each row reaches the hand-written module the
    // TypeScript ports.
    Adapter {
        module: Some("node:path"),
        name: "resolve",
        py_name: "path_resolve",
        kind: AdapterKind::Function,
        why: "Node builtin: `path.resolve(...paths)` (lib/path.js), ported statement for statement over `normalizeString`, the function `path_join` already ports: the paths right to left until one is absolute, then the working directory, normalised, no trailing separator. POSIX only; on win32 a path that is not drive-absolute is outside the subset. component.ts calls it in `sameDirectory`'s fallback alone (`pyRealpath` raised). J89-6 fuzzed it against Node (RULES.md, Adapters).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/pyfs.ts"),
        name: "pyHome",
        py_name: "py_home",
        kind: AdapterKind::Function,
        why: "Python is the reference: `pyHome` is `Path.home()` (its doc comment), so the adapter is `str(Path.home())`, what component.py passed in each place component.ts calls it (the profile store, the skill roots, the queries sidecar).",
    },
    Adapter {
        module: Some("runtime-ts/src/pysem.ts"),
        name: "pyLower",
        py_name: "py_lower",
        kind: AdapterKind::Function,
        why: "`pyLower` stood for `str.lower()`, the call component.py's `normalize_name` made; on CPython 3.11 to 3.13 that is not Node's `toLowerCase()` for the 55 code points CPython's table has no lowercase for (U+1C89) or a final sigma beside a code point the two tables classify apart, so the adapter is the runtime's `_js_m_toLowerCase` (J89-7b), which answers as Node does on every code point and never refuses.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/skills.ts"),
        name: "SKILL_LAYER",
        py_name: "SKILL_LAYER",
        kind: AdapterKind::Constant,
        why: "Python is the reference: `bantamkit.memory.skills.SKILL_LAYER`, the same `skill` label the port declares (`--suite skill-layer`).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/skills.ts"),
        name: "SkillStore",
        py_name: "SkillStore",
        kind: AdapterKind::ImportedClass(&[
            "archivedRecall",
            "candidates",
            "count",
            "lookup",
            "offer",
            "pool",
            "resolve",
        ]),
        why: "Python is the reference: skills.ts is the port of `bantamkit.memory.skills.SkillStore` (#206 X8; `--suite skill-layer` compares the two over the same SKILL.md trees). The adapter is that class with the TypeScript spelling of the seven methods component.ts calls and its `root` as a string; facts and pools cross as the generated store's shapes (the store shim's `_fact_in` / `_pool_in`), a `skipped` list is the caller's own, a shadow `Set` is read as the Python set it stands for, and `offer()` answers the reference's offer unchanged (only `fireOn` reads it).",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/skills.ts"),
        name: "skillRoots",
        py_name: "skill_roots",
        kind: AdapterKind::Function,
        why: "Python is the reference: `skillRoots` ports `skills.skill_roots` (`--suite skill-layer`); the adapter is that function, its `Path`s as strings.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/skills.ts"),
        name: "triggersEnabled",
        py_name: "triggers_enabled",
        kind: AdapterKind::Function,
        why: "Python is the reference: `triggersEnabled` ports `skills.triggers_enabled` (#301), read every call; the adapter is that function.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/skills.ts"),
        name: "isSkillStore",
        py_name: "is_skill_store",
        kind: AdapterKind::Function,
        why: "`store instanceof SkillStore` (its doc comment), named so the compiled component asks it of the adapter class: the adapter is `isinstance` of the `SkillStore` adapter above.",
    },
    Adapter {
        module: Some("runtime-ts/src/memory/skills.ts"),
        name: "fireOn",
        py_name: "fire_on",
        kind: AdapterKind::Function,
        why: "Python is the reference: `fireOn` is `SkillStore.fire(tokenizeLabel(frame(query)), shown, offer)` (its doc comment), the three calls component.py's `_fire` makes on `skills.SkillStore.fire`, `skillmine.tokenize_label` and `replynative.frame`. The adapter makes them, and answers the fired fact as the generated store's shape.",
    },
    Adapter {
        module: Some("runtime-ts/src/assets.ts"),
        name: "loadSkill",
        py_name: "load_skill",
        kind: AdapterKind::Function,
        why: "Python is the reference: `loadSkill` mirrors `bantamkit.assets.load_skill` (its doc comment); each runtime reads its own pack (`assetsRoot`'s row). The adapter is that function.",
    },
    Adapter {
        module: Some("runtime-ts/src/touch/context.ts"),
        name: "viaEnabled",
        py_name: "via_enabled",
        kind: AdapterKind::Function,
        why: "Python is the reference: `viaEnabled` ports `touch.context.via_enabled` (#200 E3), `BANTAMKIT_VIA` then the module's `VIA_ON`, read every call; the adapter is that function, so a test that patches `VIA_ON` is honoured.",
    },
    Adapter {
        module: Some("runtime-ts/src/touch/context.ts"),
        name: "viaPick",
        py_name: "via_pick",
        kind: AdapterKind::Function,
        why: "Python is the reference: `viaPick` ports `touch.context.via_pick` (#200 E3; `--suite hooks` compares the via admission). The adapter is that function over the graph the hook built, the window as a list, the excluded names as the Python set the `Set` stands for, and the compiled `weigh` closure called as is; its `(fact, path)` answers as a two-element array.",
    },
    Adapter {
        module: Some("runtime-ts/src/touch/context.ts"),
        name: "viaLabel",
        py_name: "via_label",
        kind: AdapterKind::Function,
        why: "Python is the reference: `viaLabel` ports `touch.context.via_label`; the adapter is that function.",
    },
    Adapter {
        module: Some("runtime-ts/src/touch/recallfile.ts"),
        name: "fileLinks",
        py_name: "file_links",
        kind: AdapterKind::Function,
        why: "Python is the reference: `fileLinks` is the repository half of component.py's `recall_file`, moved out of component.ts statement for statement (its doc comment): `current_cwd`, `find_repo`, `TouchGraph.load` over the layers, `ls_files`, `FileSet.matches`, `recallfile`'s sentences, `shortest_suffix`, `history_line` over the touch log and `linked_names`. The adapter makes those calls on the hand-written touch modules in that order; the layers cross as the Python layers they stand for (`wire.mjs`'s `memory-recall-file` session compares the two servers).",
    },
    Adapter {
        module: Some("runtime-ts/src/touch/recallfile.ts"),
        name: "QUERY_IGNORED",
        py_name: "QUERY_IGNORED",
        kind: AdapterKind::Constant,
        why: "Python is the reference: `touch.recallfile.QUERY_IGNORED`, the same sentence the port declares.",
    },
    Adapter {
        module: Some("runtime-ts/src/touch/recallfile.ts"),
        name: "RECALL_NEEDS_QUERY_OR_FILE",
        py_name: "RECALL_NEEDS_QUERY_OR_FILE",
        kind: AdapterKind::Constant,
        why: "Python is the reference: `touch.recallfile.RECALL_NEEDS_QUERY_OR_FILE`, the same sentence the port declares.",
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

/// Method names the adapter classes declare (not an `ImportedClass`'s: see there).
pub fn class_methods() -> impl Iterator<Item = &'static str> {
    ADAPTERS.iter().flat_map(|a| match a.kind {
        AdapterKind::Class(methods) => methods.iter().copied(),
        AdapterKind::Function
        | AdapterKind::ErrorClass
        | AdapterKind::Constant
        | AdapterKind::ImportedClass(_) => [].iter().copied(),
    })
}
