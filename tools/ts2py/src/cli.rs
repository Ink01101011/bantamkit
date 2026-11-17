//! `ts2py <input.ts> -o <output.py> [--runtime-module MODULE] [--config ts2py.toml]`
//! `ts2py <a.ts> <b.ts> ... --out-dir <dir> --runtime-module MODULE [--adapter-module MODULE]`
//! `ts2py --emit-runtime <runtime.py>` / `ts2py --emit-adapters <adapters.py> [--runtime-module M]`
//!
//! `--config` names the host file (`host.rs`): the adapter rows, the adapter module, the names the
//! headers print. Without it the host is empty and `--emit-adapters` has nothing to write.
//!
//! Exit 0 and a Python module (one per input with `--out-dir`, named after the input's stem) on
//! success. On an unsupported construct (or a syntax error), one
//! `<path>:<line>:<col>: unsupported <construct>: <snippet>` line per offence on stderr, exit 1,
//! and nothing written. Exit 2 on a usage or I/O error.

use std::path::{Path, PathBuf};
use std::process::ExitCode;

pub const USAGE: &str = "usage: ts2py <input.ts> -o <output.py> [--runtime-module MODULE] [--config FILE]\n       ts2py <input.ts>... --out-dir <dir> [--runtime-module MODULE] [--adapter-module MODULE] [--config FILE]\n       ts2py --emit-runtime <runtime.py> [--config FILE]\n       ts2py --emit-adapters <adapters.py> [--runtime-module MODULE] --config FILE";

/// The command line, given its arguments (without the program name).
pub fn run(args: Vec<String>) -> ExitCode {
    let mut inputs: Vec<String> = Vec::new();
    let mut output: Option<String> = None;
    let mut out_dir: Option<String> = None;
    let mut runtime_out: Option<String> = None;
    let mut adapters_out: Option<String> = None;
    let mut config: Option<String> = None;
    let mut options = crate::Options::default();
    let mut i = 0;
    while i < args.len() {
        let value = |i: usize| args.get(i + 1).cloned();
        match args[i].as_str() {
            "-o" | "--output" => {
                output = value(i);
                i += 1;
            }
            "--out-dir" => {
                out_dir = value(i);
                i += 1;
            }
            "--runtime-module" => {
                options.runtime_module = value(i);
                i += 1;
            }
            "--adapter-module" => {
                options.adapter_module = value(i);
                i += 1;
            }
            "--config" => {
                config = value(i);
                i += 1;
            }
            "--emit-runtime" => {
                runtime_out = value(i);
                i += 1;
            }
            "--emit-adapters" => {
                adapters_out = value(i);
                i += 1;
            }
            "-h" | "--help" => {
                println!("{USAGE}");
                return ExitCode::SUCCESS;
            }
            arg if !arg.starts_with('-') => inputs.push(arg.to_string()),
            arg => {
                eprintln!("ts2py: unexpected argument {arg}\n{USAGE}");
                return ExitCode::from(2);
            }
        }
        i += 1;
    }

    if let Some(path) = &config {
        match crate::Host::load(Path::new(path)) {
            Ok(host) => options.host = std::sync::Arc::new(host),
            Err(err) => {
                eprintln!("ts2py: {err}");
                return ExitCode::from(2);
            }
        }
    }
    if let Some(path) = &runtime_out
        && let Err(err) = std::fs::write(path, options.host.shipped(crate::RUNTIME))
    {
        eprintln!("ts2py: cannot write {path}: {err}");
        return ExitCode::from(2);
    }
    if let Some(path) = &adapters_out {
        let runtime = options
            .runtime_module
            .as_deref()
            .unwrap_or("._ts2py_runtime");
        let Some(text) = options.host.adapters_module(runtime) else {
            eprintln!("ts2py: --emit-adapters needs --config naming an adapter_source");
            return ExitCode::from(2);
        };
        if let Err(err) = std::fs::write(path, options.host.shipped(&text)) {
            eprintln!("ts2py: cannot write {path}: {err}");
            return ExitCode::from(2);
        }
    }
    let usable = match (&output, &out_dir) {
        (Some(_), None) => inputs.len() == 1,
        (None, Some(_)) => !inputs.is_empty(),
        _ => false,
    };
    if !usable {
        if (runtime_out.is_some() || adapters_out.is_some())
            && inputs.is_empty()
            && output.is_none()
            && out_dir.is_none()
        {
            return ExitCode::SUCCESS;
        }
        eprintln!("{USAGE}");
        return ExitCode::from(2);
    }

    let mut sources = Vec::new();
    for input in &inputs {
        match std::fs::read_to_string(input) {
            Ok(source) => sources.push((display_path(Path::new(input)), source)),
            Err(err) => {
                eprintln!("ts2py: cannot read {input}: {err}");
                return ExitCode::from(2);
            }
        }
    }
    let pairs: Vec<(&str, &str)> = sources
        .iter()
        .map(|(path, source)| (path.as_str(), source.as_str()))
        .collect();
    match crate::compile_modules(&pairs, &options) {
        Ok(modules) => {
            for module in modules {
                let target = match (&output, &out_dir) {
                    (Some(path), _) => PathBuf::from(path),
                    (None, Some(dir)) => Path::new(dir).join(format!("{}.py", module.py_module)),
                    (None, None) => unreachable!("checked above"),
                };
                if let Err(err) = std::fs::write(&target, module.code) {
                    eprintln!("ts2py: cannot write {}: {err}", target.display());
                    return ExitCode::from(2);
                }
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
