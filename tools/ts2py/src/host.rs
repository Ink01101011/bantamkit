//! What the project being compiled supplies (#337): everything the compiler would otherwise have
//! to know about one particular host. The compiler holds no host's names: no module path, no
//! adapter row, no output location. A host hands them over in one TOML file (`--config`):
//!
//! ```toml
//! generator = "ts2py"                 # the name the generated headers print
//! shipped_note = "# Shipped form ..." # the line `shipped` writes after a support module's header
//! adapter_source = "adapters.py"      # the hand-written adapter module, relative to this file
//!
//! [[rebound]]                          # a module-level name hand-written Python rebinds
//! module = "src/app.ts"
//! name = "Store"
//! why = "app.py rebinds `_g.Store`."
//!
//! [[adapter]]                          # one name the adapter module provides
//! module = "node:fs"                   # omitted for a global
//! name = "existsSync"
//! py_name = "exists_sync"
//! kind = "function"                    # function | class | error-class | constant | imported-class
//! # methods = ["decode"]               # class and imported-class only
//! # contract = "compare-codepoints"    # optional, see `adapters::Contract` ("str" too)
//! why = "Node builtin: ... measured on ..."
//! ```
//!
//! Without a file the host is empty: no adapter, so every import of a module that is not compiled
//! in the same call is refused.

use std::collections::HashSet;
use std::path::Path;

use serde::Deserialize;

use crate::adapters::{Adapter, AdapterKind, AdapterTable, Contract};

/// The generator name the headers print when the host names none.
pub const DEFAULT_GENERATOR: &str = "ts2py";

/// The line `shipped` writes when the host names none.
pub const DEFAULT_SHIPPED_NOTE: &str =
    "# Shipped form: its comments and docstrings are in the ts2py sources.";

/// J90-P7: a module-level name of a generated module that hand-written Python rebinds
/// (`_g.Store = _Core`) or a test patches. Interpreted, every global is read at call time;
/// mypyc binds a module's own functions and the functions and classes it imports to their
/// definitions, so a rebinding would not reach compiled code. Each row is read at call time there
/// too: a function the module defines is decorated (`@_js_late`, the identity: mypyc calls a
/// decorated function through the module's globals), an imported one becomes an `Any` variable.
/// Constants need no row: mypyc reads a module-level variable that is not `Final` from the globals.
#[derive(Clone, Debug, PartialEq)]
pub struct Rebound {
    /// The end of the module's display path (`memory/app.ts`).
    pub module: String,
    pub name: String,
    pub why: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Host {
    pub generator: String,
    pub shipped_note: String,
    /// The adapter module's text; `__RUNTIME__` stands for the runtime module.
    pub adapter_source: Option<String>,
    pub adapters: AdapterTable,
    pub rebound: Vec<Rebound>,
}

impl Default for Host {
    fn default() -> Self {
        Host {
            generator: DEFAULT_GENERATOR.to_string(),
            shipped_note: DEFAULT_SHIPPED_NOTE.to_string(),
            adapter_source: None,
            adapters: AdapterTable::default(),
            rebound: Vec::new(),
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FileHost {
    generator: Option<String>,
    shipped_note: Option<String>,
    adapter_source: Option<String>,
    #[serde(default)]
    rebound: Vec<FileRebound>,
    #[serde(default)]
    adapter: Vec<FileAdapter>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FileRebound {
    module: String,
    name: String,
    why: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FileAdapter {
    module: Option<String>,
    name: String,
    py_name: String,
    kind: String,
    methods: Option<Vec<String>>,
    contract: Option<String>,
    why: String,
}

impl Host {
    /// Read a host file. Relative paths in it are relative to the file's directory.
    pub fn load(path: &Path) -> Result<Host, String> {
        let shown = path.display();
        let text =
            std::fs::read_to_string(path).map_err(|e| format!("cannot read {shown}: {e}"))?;
        let base = path.parent().unwrap_or(Path::new("."));
        Host::parse(&text, base).map_err(|e| format!("{shown}: {e}"))
    }

    /// Parse a host file's text; `base` is the directory its relative paths start from.
    pub fn parse(text: &str, base: &Path) -> Result<Host, String> {
        let file: FileHost = toml::from_str(text).map_err(|e| e.to_string().trim().to_string())?;
        let mut host = Host::default();
        if let Some(generator) = file.generator {
            host.generator = generator;
        }
        if let Some(note) = file.shipped_note {
            if !note.starts_with('#') || note.contains('\n') {
                return Err("shipped_note must be one comment line (starting with #)".to_string());
            }
            host.shipped_note = note;
        }
        if let Some(source) = &file.adapter_source {
            let at = base.join(source);
            host.adapter_source = Some(
                std::fs::read_to_string(&at)
                    .map_err(|e| format!("cannot read adapter_source {}: {e}", at.display()))?,
            );
        }
        for r in file.rebound {
            if r.why.trim().is_empty() {
                return Err(format!("rebound {} of {}: no why", r.name, r.module));
            }
            host.rebound.push(Rebound {
                module: r.module,
                name: r.name,
                why: r.why,
            });
        }
        let mut seen: HashSet<(Option<String>, String)> = HashSet::new();
        for a in file.adapter {
            let label = match &a.module {
                Some(m) => format!("adapter {} of {m}", a.name),
                None => format!("adapter {} (a global)", a.name),
            };
            if a.why.trim().is_empty() {
                return Err(format!(
                    "{label}: no why; every row says why it is faithful"
                ));
            }
            if !seen.insert((a.module.clone(), a.name.clone())) {
                return Err(format!("{label}: declared twice"));
            }
            let methods = a.methods;
            let kind = match (a.kind.as_str(), methods) {
                ("function", None) => AdapterKind::Function,
                ("error-class", None) => AdapterKind::ErrorClass,
                ("constant", None) => AdapterKind::Constant,
                ("class", Some(m)) => AdapterKind::Class(m),
                ("imported-class", Some(m)) => AdapterKind::ImportedClass(m),
                ("class" | "imported-class", None) => {
                    return Err(format!("{label}: kind {} needs methods", a.kind));
                }
                ("function" | "error-class" | "constant", Some(_)) => {
                    return Err(format!("{label}: kind {} takes no methods", a.kind));
                }
                (other, _) => return Err(format!("{label}: unknown kind {other}")),
            };
            let contract = match a.contract.as_deref() {
                None => None,
                Some("compare-codepoints") if kind == AdapterKind::Function => {
                    Some(Contract::CompareCodepoints)
                }
                Some("str") if kind == AdapterKind::Function => Some(Contract::Str),
                Some(other) => return Err(format!("{label}: unknown contract {other}")),
            };
            host.adapters.rows.push(Adapter {
                module: a.module,
                name: a.name,
                py_name: a.py_name,
                kind,
                contract,
                why: a.why,
            });
        }
        if !host.adapters.rows.is_empty() && host.adapter_source.is_none() {
            return Err("adapter rows need an adapter_source".to_string());
        }
        Ok(host)
    }

    /// The adapter module's text, importing the runtime from `runtime_module`.
    pub fn adapters_module(&self, runtime_module: &str) -> Option<String> {
        self.adapter_source
            .as_ref()
            .map(|text| text.replace("__RUNTIME__", runtime_module))
    }

    /// `crate::shipped` with this host's note.
    pub fn shipped(&self, text: &str) -> String {
        crate::shipped(text, &self.shipped_note)
    }
}
