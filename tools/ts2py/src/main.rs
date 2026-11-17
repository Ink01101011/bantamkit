//! The `ts2py` command; everything it does is `ts2py::cli::run` (`src/cli.rs`).

fn main() -> std::process::ExitCode {
    ts2py::cli::run(std::env::args().skip(1).collect())
}
