//! ts2py: compile a TypeScript module, in the subset `SUBSET.md` lists, into a Python module.
//!
//! The parser is `oxc_parser`; this crate only lowers its AST. Anything outside the subset is a
//! compile-time refusal with a source location, never a best-effort translation.

pub mod adapters;
pub mod lower;
pub mod pyfmt;
pub mod types;

use oxc_allocator::Allocator;
use oxc_parser::Parser;
use oxc_span::{SourceType, Span};
use sha2::{Digest, Sha256};

/// The runtime support module, pure stdlib. Inlined into the output unless `runtime_module` names
/// a module to import it from (`--emit-runtime` writes this text to that module's file).
pub const RUNTIME: &str = include_str!("runtime.py");

/// The hand-written adapters (J86, `adapters.rs`). `__RUNTIME__` stands for the runtime module.
pub const ADAPTERS: &str = include_str!("adapters.py");

/// The adapter module's text, importing the runtime from `runtime_module`.
pub fn adapters_module(runtime_module: &str) -> String {
    ADAPTERS.replace("__RUNTIME__", runtime_module)
}

#[derive(Default)]
pub struct Options {
    /// Import the runtime helpers from this module (e.g. `._ts2py_runtime`) instead of inlining them.
    pub runtime_module: Option<String>,
    /// J86: import adapters from this module (default `._ts2py_adapters`).
    pub adapter_module: Option<String>,
}

/// One compiled module (J86).
pub struct Compiled {
    /// The TypeScript path, as printed.
    pub path: String,
    /// The Python module name (the file's stem): `<py_module>.py`.
    pub py_module: String,
    pub code: String,
}

/// Compile `source` (whose path, as printed in the header and in diagnostics, is `display_path`).
///
/// `Ok` is the whole Python module. `Err` is one line per offence:
/// `<path>:<line>:<col>: unsupported <construct>: <snippet>` (or `syntax error` for a parse error).
/// J87: rounds of the type-fact fixpoint before a module is refused as not settling.
const MAX_ROUNDS: usize = 64;

pub fn compile(source: &str, display_path: &str, options: &Options) -> Result<String, Vec<String>> {
    compile_modules(&[(display_path, source)], options).map(|mut modules| modules.remove(0).code)
}

/// Compile several modules together (J86): each TypeScript module becomes one Python module, and an
/// import of one of them from another is a relative import of the generated module. An import of
/// anything else goes through the adapter seam (`adapters.rs`) or is refused.
pub fn compile_modules(
    sources: &[(&str, &str)],
    options: &Options,
) -> Result<Vec<Compiled>, Vec<String>> {
    let allocators: Vec<Allocator> = sources.iter().map(|_| Allocator::default()).collect();
    let mut errors = Vec::new();
    let mut programs = Vec::new();
    for ((display_path, source), allocator) in sources.iter().zip(&allocators) {
        let parsed = Parser::new(allocator, source, SourceType::ts()).parse();
        if parsed.fatal_error || !parsed.diagnostics.is_empty() {
            let before = errors.len();
            for diagnostic in parsed.diagnostics.iter() {
                let offset = diagnostic.labels.first().map_or(0, |label| label.offset());
                let (line, col) = line_col(source, offset);
                errors.push(format!(
                    "{display_path}:{line}:{col}: syntax error: {}",
                    diagnostic.message
                ));
            }
            if errors.len() == before {
                errors.push(format!(
                    "{display_path}:1:1: syntax error: the parser gave up"
                ));
            }
        }
        programs.push(parsed.program);
    }
    if !errors.is_empty() {
        return Err(errors);
    }

    // What each module exports, before anything is lowered, so imports between them resolve.
    let mut ctx = lower::ModuleCtx {
        adapter_module: options
            .adapter_module
            .clone()
            .unwrap_or_else(|| "._ts2py_adapters".to_string()),
        ..lower::ModuleCtx::default()
    };
    ctx.class_methods
        .extend(adapters::class_methods().map(str::to_string));
    let mut stems = Vec::new();
    for ((display_path, _), program) in sources.iter().zip(&programs) {
        let stem = py_module_name(display_path);
        if !is_identifier(&stem) || stems.contains(&stem) {
            errors.push(format!(
                "{display_path}:1:1: unsupported module name: {stem} is not a distinct Python identifier"
            ));
        }
        stems.push(stem.clone());
        let (names, methods) = lower::scan_module(program);
        ctx.class_methods.extend(methods);
        ctx.modules.insert(
            display_path.to_string(),
            lower::ModuleExports {
                py_module: stem,
                names,
            },
        );
    }
    if !errors.is_empty() {
        return Err(errors);
    }

    let mut out = Vec::new();
    for (((display_path, source), program), stem) in sources.iter().zip(&programs).zip(stems) {
        let module_ctx = lower::ModuleCtx {
            path: display_path.to_string(),
            ..ctx.clone()
        };
        // J87: rounds of the type-fact fixpoint (`types.rs`): each lowers the whole module under
        // the facts the last one left standing, until a round observes exactly what it assumed.
        // Every fact only shrinks and every wrapper or escape only grows, so this ends.
        let mut assume = types::Assume::default();
        let mut rounds = 0;
        let (mut lowerer, body) = loop {
            let mut lowerer =
                lower::Lowerer::with_assume(source, module_ctx.clone(), assume.clone());
            let body = lowerer.program(program);
            let next = lowerer.next_assume();
            rounds += 1;
            if next == *lowerer.assumed() || rounds >= MAX_ROUNDS {
                break (lowerer, body);
            }
            assume = next;
        };
        if rounds >= MAX_ROUNDS && lowerer.next_assume() != *lowerer.assumed() {
            errors.push(format!(
                "{display_path}:1:1: unsupported module: type facts did not settle in {MAX_ROUNDS} rounds"
            ));
            continue;
        }
        if !lowerer.refusals.is_empty() {
            let mut refusals = std::mem::take(&mut lowerer.refusals);
            // A function with a typed body is lowered twice (J87): one offence, one line.
            let mut seen = std::collections::HashSet::new();
            refusals.retain(|r| seen.insert((r.span.start, r.span.end, r.construct.clone())));
            refusals.sort_by_key(|r| (r.span.start, r.span.end));
            errors.extend(refusals.iter().map(|r| {
                let (line, col) = line_col(source, r.span.start);
                format!(
                    "{display_path}:{line}:{col}: unsupported {}: {}",
                    r.construct,
                    snippet(source, r.span)
                )
            }));
            continue;
        }
        let code = emit(source, display_path, options, &lowerer, &body);
        out.push(Compiled {
            path: display_path.to_string(),
            py_module: stem,
            code,
        });
    }
    if !errors.is_empty() {
        return Err(errors);
    }
    Ok(out)
}

fn emit(
    source: &str,
    display_path: &str,
    options: &Options,
    lowerer: &lower::Lowerer<'_>,
    body: &str,
) -> String {
    let mut exports = lowerer.exports.clone();
    exports.sort();
    let digest = Sha256::digest(source.as_bytes());
    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();

    let mut out = String::new();
    out.push_str(&format!(
        "# Generated by tools/ts2py from {display_path}. DO NOT EDIT: change the TypeScript and regenerate.\n"
    ));
    out.push_str(&format!("# source-sha256: {hex}\n"));
    // Generated lines are not wrapped; and every lambda is a callback a helper calls before the
    // enclosing statement ends (SUBSET.md), so a loop variable it reads is never stale.
    out.push_str("# ruff: noqa: E501, B023\n");
    out.push_str(&format!(
        "\"\"\"Generated from `{display_path}` by tools/ts2py; the TypeScript source is the documentation.\"\"\"\n\n"
    ));
    match &options.runtime_module {
        None => out.push_str(RUNTIME),
        Some(module) => {
            let used: Vec<&str> = runtime_names()
                .into_iter()
                .filter(|n| uses(body, n))
                .collect();
            if !used.is_empty() {
                out.push_str(&format!("from {module} import (  # noqa: F401\n"));
                for name in used {
                    out.push_str(&format!("    {name},\n"));
                }
                out.push_str(")\n");
            }
        }
    }
    // J86: imports from the other compiled modules and from the adapter module.
    for (module, names) in &lowerer.imports {
        let mut names: Vec<&str> = names.iter().map(String::as_str).collect();
        names.sort_by_key(|n| (n.to_uppercase() != *n, n.to_lowercase(), n.to_string()));
        out.push_str(&format!("from {module} import {}\n", names.join(", ")));
    }
    match &options.runtime_module {
        None => out.push_str("\n\n"),
        Some(_) => out.push('\n'),
    }
    out.push_str("__all__ = [");
    out.push_str(
        &exports
            .iter()
            .map(|e| pyfmt::py_str(e))
            .collect::<Vec<_>>()
            .join(", "),
    );
    out.push_str("]\n\n\n");
    out.push_str(body);
    out
}

/// The Python module a TypeScript path compiles to: its file stem.
pub fn py_module_name(display_path: &str) -> String {
    let file = display_path.rsplit('/').next().unwrap_or(display_path);
    file.split('.').next().unwrap_or(file).to_string()
}

fn is_identifier(name: &str) -> bool {
    let mut chars = name.chars();
    chars
        .next()
        .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '_')
        && !pyfmt::is_py_keyword(name)
}

/// Every module-level name the runtime defines, sorted.
pub fn runtime_names() -> Vec<&'static str> {
    let mut names = Vec::new();
    for line in RUNTIME.lines() {
        let name = if let Some(rest) = line.strip_prefix("def ") {
            rest.split('(').next()
        } else if let Some(rest) = line.strip_prefix("class ") {
            rest.split([':', '(']).next()
        } else if let Some(rest) = line.strip_prefix("import ") {
            rest.split(" as ").nth(1)
        } else if line.starts_with("_JS") {
            line.split(" = ").next()
        } else {
            None
        };
        if let Some(name) = name {
            names.push(name.trim());
        }
    }
    // isort's order, as ruff applies it: constants first, then the rest case-insensitively.
    names.sort_by_key(|n| (n.to_uppercase() != *n, n.to_lowercase(), n.to_string()));
    names.dedup();
    names
}

/// `name` appears in `code` as a whole identifier.
fn uses(code: &str, name: &str) -> bool {
    let ident = |c: char| c.is_ascii_alphanumeric() || c == '_';
    code.match_indices(name).any(|(at, _)| {
        let before = code[..at].chars().next_back();
        let after = code[at + name.len()..].chars().next();
        !before.is_some_and(ident) && !after.is_some_and(ident)
    })
}

/// 1-based line and column (in characters) of a byte offset.
pub fn line_col(source: &str, offset: u32) -> (usize, usize) {
    let offset = (offset as usize).min(source.len());
    let before = &source[..offset];
    let line = before.matches('\n').count() + 1;
    let start = before.rfind('\n').map_or(0, |i| i + 1);
    (line, source[start..offset].chars().count() + 1)
}

/// The offending source, first line only, at most 80 characters.
fn snippet(source: &str, span: Span) -> String {
    let text = &source[span.start as usize..span.end as usize];
    let first = text.lines().next().unwrap_or("").trim_end();
    let mut out: String = first.chars().take(80).collect();
    if first.chars().count() > 80 || text.contains('\n') {
        out.push_str(" ...");
    }
    out
}
