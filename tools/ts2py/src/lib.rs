//! ts2py: compile a TypeScript module, in the subset `SUBSET.md` lists, into a Python module.
//!
//! The parser is `oxc_parser`; this crate only lowers its AST. Anything outside the subset is a
//! compile-time refusal with a source location, never a best-effort translation.

pub mod adapters;
pub mod cli;
pub mod host;
pub mod lower;
pub mod pyfmt;
pub mod types;

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use oxc_allocator::Allocator;
use oxc_parser::Parser;
use oxc_span::{SourceType, Span};
use sha2::{Digest, Sha256};

pub use host::{Host, Rebound};

/// The runtime support module, pure stdlib (`python/ts2py/runtime.py`). Inlined into the output
/// unless `runtime_module` names a module to import it from (`--emit-runtime` writes this text to
/// that module's file).
pub const RUNTIME: &str = include_str!("../python/ts2py/runtime.py");

/// J90-P2: the form of a support module `--emit-runtime` / `--emit-adapters` write (and a host
/// ships): its leading comment block and `note` (the host's `shipped_note`), then every line but
/// the full-line comments and the docstring of each function or class whose body goes on after
/// it. Nothing inside a triple-quoted string is touched, so the code is the source's statement for
/// statement (`tests/shipped.rs` holds the two to one `ast.dump`, docstrings aside), and only the
/// documentation stays behind in the source.
pub fn shipped(text: &str, note: &str) -> String {
    let lines: Vec<&str> = text.split('\n').collect();
    let mut out: Vec<&str> = Vec::new();
    let mut i = 0;
    while i < lines.len() && lines[i].starts_with('#') {
        out.push(lines[i]);
        i += 1;
    }
    out.push(note);
    let quotes = |l: &str| l.matches("\"\"\"").count();
    let indent = |l: &str| l.len() - l.trim_start().len();
    let header = |l: &str| {
        let t = l.trim_start();
        t.starts_with("def ") || t.starts_with("async def ") || t.starts_with("class ")
    };
    let mut in_string = false;
    let mut depth: Option<i64> = None;
    while i < lines.len() {
        let line = lines[i];
        let stripped = line.trim();
        if in_string {
            out.push(line);
            if quotes(line) % 2 == 1 {
                in_string = false;
            }
            i += 1;
            continue;
        }
        if depth.is_none() && header(line) {
            depth = Some(0);
        }
        if let Some(d) = depth {
            let open = line.chars().filter(|c| "([{".contains(*c)).count() as i64;
            let close = line.chars().filter(|c| ")]}".contains(*c)).count() as i64;
            let d = d + open - close;
            out.push(line);
            i += 1;
            if d == 0 && stripped.ends_with(':') {
                depth = None;
                if i < lines.len() {
                    let first = lines[i];
                    let body = first.trim_start();
                    if body.starts_with("\"\"\"") || body.starts_with("r\"\"\"") {
                        let opener = if body.starts_with('r') { 4 } else { 3 };
                        let end = if body[opener..].contains("\"\"\"") {
                            Some(i)
                        } else {
                            (i + 1..lines.len()).find(|&k| lines[k].contains("\"\"\""))
                        };
                        if let Some(end) = end {
                            let after =
                                (end + 1..lines.len()).find(|&k| !lines[k].trim().is_empty());
                            if after.is_some_and(|k| indent(lines[k]) >= indent(first)) {
                                i = end + 1;
                            }
                        }
                    }
                }
            } else {
                depth = Some(d);
            }
            continue;
        }
        if stripped.starts_with('#') {
            i += 1;
            continue;
        }
        out.push(line);
        if quotes(line) % 2 == 1 {
            in_string = true;
        }
        i += 1;
    }
    out.join("\n")
}

#[derive(Clone, Default)]
pub struct Options {
    /// Import the runtime helpers from this module (e.g. `._ts2py_runtime`) instead of inlining them.
    pub runtime_module: Option<String>,
    /// J86: import adapters from this module (default `._ts2py_adapters`).
    pub adapter_module: Option<String>,
    /// #337: what the project being compiled supplies (`host.rs`); empty by default.
    pub host: Arc<Host>,
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
/// anything else goes through the host's adapter seam (`adapters.rs`, `host.rs`) or is refused.
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
        adapters: Arc::new(options.host.adapters.clone()),
        ..lower::ModuleCtx::default()
    };
    ctx.class_methods
        .extend(options.host.adapters.class_methods().map(str::to_string));
    let mut stems = Vec::new();
    // J89-5a: each module's own non-exported classes' method names (`scan_module`).
    let mut private_methods: HashMap<String, HashSet<String>> = HashMap::new();
    for ((display_path, _), program) in sources.iter().zip(&programs) {
        let stem = py_module_name(display_path);
        if !is_identifier(&stem) || stems.contains(&stem) {
            errors.push(format!(
                "{display_path}:1:1: unsupported module name: {stem} is not a distinct Python identifier"
            ));
        }
        stems.push(stem.clone());
        let (names, methods, private) = lower::scan_module(program);
        ctx.class_methods.extend(methods);
        private_methods.insert(display_path.to_string(), private);
        ctx.modules.insert(
            display_path.to_string(),
            lower::ModuleExports {
                py_module: stem,
                names,
                generators: lower::generator_names(program),
                type_fields: types::TypeDecls::read(program).fields,
            },
        );
    }
    if !errors.is_empty() {
        return Err(errors);
    }

    // J90-2: the import graph between the compiled modules of this call, and each module's
    // imports that lead back to it (a cycle): those are written after its body.
    let mut edges: HashMap<String, HashSet<String>> = HashMap::new();
    for ((display_path, _), program) in sources.iter().zip(&programs) {
        edges.insert(
            display_path.to_string(),
            lower::compiled_imports(program, display_path, &ctx.modules),
        );
    }
    let reaches = |from: &str, to: &str| -> bool {
        let mut seen: HashSet<&str> = HashSet::new();
        let mut stack = vec![from];
        while let Some(at) = stack.pop() {
            if at == to {
                return true;
            }
            if !seen.insert(at) {
                continue;
            }
            if let Some(next) = edges.get(at) {
                stack.extend(next.iter().map(String::as_str));
            }
        }
        false
    };

    let mut out = Vec::new();
    for (((display_path, source), program), stem) in sources.iter().zip(&programs).zip(stems) {
        let cyclic_imports: HashSet<String> = edges
            .get(*display_path)
            .map(|targets| {
                targets
                    .iter()
                    .filter(|t| reaches(t, display_path))
                    .cloned()
                    .collect()
            })
            .unwrap_or_default();
        let mut module_ctx = lower::ModuleCtx {
            path: display_path.to_string(),
            cyclic_imports,
            ..ctx.clone()
        };
        if let Some(private) = private_methods.get(*display_path) {
            module_ctx.class_methods.extend(private.iter().cloned());
        }
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

    // J90-P7: a name a hand-written shim rebinds is read at call time under mypyc too.
    let rebound: Vec<&str> = options
        .host
        .rebound
        .iter()
        .filter(|r| display_path.ends_with(r.module.as_str()))
        .map(|r| r.name.as_str())
        .collect();
    let mut late_defs = String::new();
    for name in &rebound {
        let def = format!("\ndef {name}(");
        if body.starts_with(&def[1..]) || body.contains(&def) {
            late_defs.push_str(name);
        }
    }
    let body_owned: String;
    let body: &str = if late_defs.is_empty() {
        body
    } else {
        let mut text = format!("\n{body}");
        for name in &rebound {
            let def = format!("\ndef {name}(");
            text = text.replacen(&def, &format!("\n@_js_late\ndef {name}("), 1);
        }
        body_owned = text[1..].to_string();
        &body_owned
    };
    // J90-P7: every module-level variable is `_JsAny`. mypy gives an unannotated one the type of
    // its first value, and mypyc then refuses (TypeError) any later value of another type, which
    // JS allows: a shim forwarding `GATE_FLOOR = 1.5` over `1`, or the module's own `let`.
    let annotated: String;
    let body: &str = {
        let mut seen: HashSet<&str> = HashSet::new();
        let mut lines: Vec<String> = Vec::new();
        let mut changed = false;
        for line in body.split('\n') {
            let name_end = line
                .find(|c: char| !(c.is_ascii_alphanumeric() || c == '_'))
                .unwrap_or(line.len());
            let name = &line[..name_end];
            let is_assign = name_end > 0
                && !name.starts_with(|c: char| c.is_ascii_digit())
                && line[name_end..].starts_with(" = ")
                && name != "__all__"
                // A typed body's second name (`_f__typed = f`) is a function, never rebound.
                && !name.ends_with("__typed");
            if is_assign && seen.insert(name) {
                // A `_JS_` name is ts2py's own (a hoisted regex), never rebound: `Final`.
                let kind = if name.starts_with("_JS_") {
                    "_Final"
                } else {
                    "_JsAny"
                };
                lines.push(format!("{name}: {kind}{}", &line[name_end..]));
                changed = true;
            } else {
                lines.push(line.to_string());
            }
        }
        if changed {
            annotated = lines.join("\n");
            &annotated
        } else {
            body
        }
    };
    let mut bound_imports: Vec<&str> = Vec::new();

    let mut out = String::new();
    let generator = &options.host.generator;
    out.push_str(&format!(
        "# Generated by {generator} from {display_path}. DO NOT EDIT: change the TypeScript and regenerate.\n"
    ));
    out.push_str(&format!("# source-sha256: {hex}\n"));
    // Generated lines are not wrapped; and every lambda is a callback a helper calls before the
    // enclosing statement ends (SUBSET.md), so a loop variable it reads is never stale.
    // J88-2: and a TypeScript name like `l` is kept as spelled (E741).
    // J90-P6: a guarded inline expansion is always parenthesized, also as a call's sole argument
    // (UP034).
    out.push_str("# ruff: noqa: E501, B023, E741, UP034\n");
    out.push_str(&format!(
        "\"\"\"Generated from `{display_path}` by {generator}; the TypeScript source is the documentation.\"\"\"\n\n"
    ));
    match &options.runtime_module {
        None => out.push_str(RUNTIME),
        Some(module) => {
            let imported_rebound = lowerer
                .imports
                .values()
                .flatten()
                .any(|n| rebound.contains(&n.as_str()));
            let used: Vec<&str> = runtime_names()
                .into_iter()
                .filter(|n| uses(body, n) || (*n == "_JsAny" && imported_rebound))
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
        let names: Vec<String> = names
            .into_iter()
            .map(|n| {
                if rebound.contains(&n) {
                    bound_imports.push(n);
                    format!("{n} as _js_bound_{n}")
                } else {
                    n.to_string()
                }
            })
            .collect();
        out.push_str(&format!("from {module} import {}\n", names.join(", ")));
    }
    // J90-P7: an imported class or function a shim rebinds is an `Any` variable, which mypyc reads
    // from the module's globals at each use (it binds an imported name to its definition).
    for name in &bound_imports {
        out.push_str(&format!("{name}: _JsAny = _js_bound_{name}\n"));
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
    // J90-2: the imports of an import cycle, after every name of this module is bound (so the
    // cycle imports in either order); the body reads them only when a function runs.
    if !lowerer.late_imports.is_empty() {
        out.push_str(
            "\n\n# Imported last: these modules import this one back (an import cycle).\n",
        );
        for (module, names) in &lowerer.late_imports {
            let mut names: Vec<&str> = names.iter().map(String::as_str).collect();
            names.sort_by_key(|n| (n.to_uppercase() != *n, n.to_lowercase(), n.to_string()));
            out.push_str(&format!(
                "from {module} import {}  # noqa: E402\n",
                names.join(", ")
            ));
        }
    }
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
            // J90-P7: `_JS_UNITS: dict = {}` binds `_JS_UNITS`.
            line.split(" = ").next().and_then(|n| n.split(':').next())
        } else if let Some(rest) = line.strip_prefix("from typing import ") {
            rest.split(" as ")
                .nth(1)
                .and_then(|n| n.split_whitespace().next())
        } else {
            None
        };
        if let Some(name) = name {
            names.push(name.trim());
        }
    }
    // J90-P7: the decorator only mypyc reads, bound in an `if TYPE_CHECKING:` block.
    if RUNTIME.contains("\n    _mypyc_attr = _js_no_mypyc_attr") {
        names.push("_mypyc_attr");
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
