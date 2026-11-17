//! The adapter seam (J86): an import (or a Node global) that ts2py does not compile resolves to
//! hand-written Python in the host's adapter module, and only through a row of the host's adapter
//! table (`host.rs`, the `[[adapter]]` rows of its `ts2py.toml`). An import with no compiled module
//! and no row is a compile error naming it. The compiler declares no row of its own.
//!
//! Every row says why a hand-written function is faithful. Two kinds of reason are accepted:
//! Python IS the reference (the TypeScript function is a port of a CPython behaviour, so the
//! CPython behaviour is the definition), or the row reproduces a Node builtin and names the
//! measurement that pins it. A row with no reason is refused when the table is read.

/// What an adapter provides.
#[derive(Clone, Debug, PartialEq)]
pub enum AdapterKind {
    /// A function, called as `name(...)`.
    Function,
    /// A class, constructed with `new Name(...)`, with these methods.
    Class(Vec<String>),
    /// J87-3: an `Error` subclass a compiled class may extend (`class E extends AppError {}`).
    ErrorClass,
    /// J88-2: a constant, read by name (`LOCK_STALE_MS`).
    Constant,
    /// J89-4a: a class with these methods whose calls dispatch (`_js_invoke` / `_js_dispatch`)
    /// only in a module that imports it, so its method names do not reach every module of the
    /// call (a `Set`'s `.add` elsewhere stays `_js_m_add`). Naming one of them as a value is not
    /// refused at compile time: on an instance the runtime refuses it (`_js_object_get`), and on
    /// anything else it is a property read (`pool.names` of a plain object), as in JS.
    ImportedClass(Vec<String>),
}

/// A promise a row makes about its function beyond "faithful", which lets the compiler lower a
/// call to it to something faster than the call.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Contract {
    /// J90-P2: `f(x, y)` orders two strings by code point (-1, 0 or 1 as `x` sorts before, with
    /// or after `y`; CPython's `sorted()` order), so a comparator chain of it is a key sort.
    CompareCodepoints,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Adapter {
    /// The TypeScript module the name is imported from (normalised `.ts` path, as the compiled
    /// modules' display paths spell it, or a bare specifier such as `node:fs`), or `None` for a
    /// global.
    pub module: Option<String>,
    /// The name as TypeScript spells it.
    pub name: String,
    /// The name the adapter module defines.
    pub py_name: String,
    pub kind: AdapterKind,
    pub contract: Option<Contract>,
    /// Why the hand-written Python is the same function.
    pub why: String,
}

impl Adapter {
    /// `module`'s `name` (a bare specifier's export, or a relative module's).
    pub fn is(&self, module: Option<&str>, name: &str) -> bool {
        self.module.as_deref() == module && self.name == name
    }
}

/// The rows a host declares, in its order.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct AdapterTable {
    pub rows: Vec<Adapter>,
}

impl AdapterTable {
    /// The adapter for `name` imported from `module` (a normalised `.ts` path), if one is declared.
    pub fn import(&self, module: &str, name: &str) -> Option<Adapter> {
        self.rows.iter().find(|a| a.is(Some(module), name)).cloned()
    }

    /// The adapter for the global `name`, if one is declared.
    pub fn global(&self, name: &str) -> Option<Adapter> {
        self.rows.iter().find(|a| a.is(None, name)).cloned()
    }

    /// Method names the adapter classes declare (not an `ImportedClass`'s: see there).
    pub fn class_methods(&self) -> impl Iterator<Item = &str> {
        self.rows.iter().flat_map(|a| match &a.kind {
            AdapterKind::Class(methods) => methods.iter().map(String::as_str).collect::<Vec<_>>(),
            AdapterKind::Function
            | AdapterKind::ErrorClass
            | AdapterKind::Constant
            | AdapterKind::ImportedClass(_) => Vec::new(),
        })
    }
}
