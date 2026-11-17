//! The ts2py command line, built in this crate so its tests can run it (`CARGO_BIN_EXE_*` names
//! only a package's own binaries). It is `ts2py::cli::run`, the same function `ts2py` runs.

fn main() -> std::process::ExitCode {
    ts2py::cli::run(std::env::args().skip(1).collect())
}
