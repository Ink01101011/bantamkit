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
        AdapterKind::Function => [].iter().copied(),
    })
}
