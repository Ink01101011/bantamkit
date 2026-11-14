//! `ts2py <input.ts> -o <output.py> [--runtime-module MODULE]`
//! `ts2py --emit-runtime <runtime.py>`
//!
//! Exit 0 and a Python module on success. On an unsupported construct (or a syntax error), one
//! `<path>:<line>:<col>: unsupported <construct>: <snippet>` line per offence on stderr, exit 1,
//! and nothing written. Exit 2 on a usage or I/O error.

use std::path::{Path, PathBuf};
use std::process::ExitCode;

const USAGE: &str = "usage: ts2py <input.ts> -o <output.py> [--runtime-module MODULE]\n       ts2py --emit-runtime <runtime.py>";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut input: Option<String> = None;
    let mut output: Option<String> = None;
    let mut runtime_out: Option<String> = None;
    let mut options = ts2py::Options::default();
    let mut i = 0;
    while i < args.len() {
        let value = |i: usize| args.get(i + 1).cloned();
        match args[i].as_str() {
            "-o" | "--output" => {
                output = value(i);
                i += 1;
            }
            "--runtime-module" => {
                options.runtime_module = value(i);
                i += 1;
            }
            "--emit-runtime" => {
                runtime_out = value(i);
                i += 1;
            }
            "-h" | "--help" => {
                println!("{USAGE}");
                return ExitCode::SUCCESS;
            }
            arg if !arg.starts_with('-') && input.is_none() => input = Some(arg.to_string()),
            arg => {
                eprintln!("ts2py: unexpected argument {arg}\n{USAGE}");
                return ExitCode::from(2);
            }
        }
        i += 1;
    }

    if let Some(path) = &runtime_out
        && let Err(err) = std::fs::write(path, ts2py::RUNTIME)
    {
        eprintln!("ts2py: cannot write {path}: {err}");
        return ExitCode::from(2);
    }
    let (Some(input), Some(output)) = (input, output) else {
        if runtime_out.is_some() {
            return ExitCode::SUCCESS;
        }
        eprintln!("{USAGE}");
        return ExitCode::from(2);
    };

    let source = match std::fs::read_to_string(&input) {
        Ok(source) => source,
        Err(err) => {
            eprintln!("ts2py: cannot read {input}: {err}");
            return ExitCode::from(2);
        }
    };
    match ts2py::compile(&source, &display_path(Path::new(&input)), &options) {
        Ok(module) => {
            if let Err(err) = std::fs::write(&output, module) {
                eprintln!("ts2py: cannot write {output}: {err}");
                return ExitCode::from(2);
            }
            ExitCode::SUCCESS
        }
        Err(lines) => {
            for line in lines {
                eprintln!("{line}");
            }
            ExitCode::from(1)
        }
    }
}

/// The input path relative to the enclosing git checkout, `/`-separated, so the header is the
/// same whatever directory the compiler ran from. Outside a checkout: the path as given.
fn display_path(input: &Path) -> String {
    let fallback = input.to_string_lossy().replace('\\', "/");
    let Ok(absolute) = input.canonicalize() else {
        return fallback;
    };
    let mut root: Option<PathBuf> = None;
    for dir in absolute.ancestors().skip(1) {
        if dir.join(".git").exists() {
            root = Some(dir.to_path_buf());
            break;
        }
    }
    match root.and_then(|root| absolute.strip_prefix(&root).ok().map(Path::to_path_buf)) {
        Some(relative) => relative
            .components()
            .map(|c| c.as_os_str().to_string_lossy().into_owned())
            .collect::<Vec<_>>()
            .join("/"),
        None => fallback,
    }
}
