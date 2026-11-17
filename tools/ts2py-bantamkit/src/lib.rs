//! bantamkit's host input to ts2py (#337), for the tests in `tests/`: `ts2py.toml` beside this
//! crate is the file the regenerate commands pass as `--config` (docs/porting.md, *Generated
//! modules*), loaded once. The compiler itself is `../ts2py` and holds no bantamkit name.

use std::path::Path;
use std::sync::{Arc, OnceLock};

/// The host file every bantamkit compile passes as `--config`.
pub const CONFIG: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/ts2py.toml");

/// The repository root (the TypeScript paths the tests compile are relative to it).
pub fn repo_root() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("tools/ts2py-bantamkit sits two levels below the repository root")
}

/// bantamkit's host, read from `CONFIG` once.
pub fn host() -> Arc<ts2py::Host> {
    static HOST: OnceLock<Arc<ts2py::Host>> = OnceLock::new();
    HOST.get_or_init(|| {
        Arc::new(ts2py::Host::load(Path::new(CONFIG)).unwrap_or_else(|e| panic!("{e}")))
    })
    .clone()
}

/// `ts2py::Options` with bantamkit's host and nothing else set.
pub fn options() -> ts2py::Options {
    ts2py::Options {
        host: host(),
        ..ts2py::Options::default()
    }
}

/// bantamkit's adapter module importing the runtime from `runtime_module`.
pub fn adapters_module(runtime_module: &str) -> String {
    host()
        .adapters_module(runtime_module)
        .expect("ts2py.toml names an adapter_source")
}

/// `ts2py::shipped` with bantamkit's note.
pub fn shipped(text: &str) -> String {
    host().shipped(text)
}

/// The note `shipped` writes (bantamkit's `shipped_note`).
pub fn shipped_note() -> String {
    host().shipped_note.clone()
}
