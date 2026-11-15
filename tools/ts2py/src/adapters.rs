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
              on a byte corpus (RULES.md, Adapters).",
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
        AdapterKind::Function | AdapterKind::ErrorClass => [].iter().copied(),
    })
}
