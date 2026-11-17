//! J90-3 (#316 G4: `storage/coldindex`, `storage/retention`, `storage/tiers`, `storage/index`):
//! what generating them needed — `Buffer.prototype.equals`, `buf.toString('base64')`,
//! `lstatSync(p, {bigint: true})`, `unlinkSync`, `rmdirSync`, `path.relative`, `path.sep` (a
//! namespace constant), `path.join`'s refusal of `undefined` / `null` as a JS TypeError, the
//! `nodeRealpath` adapter as Node's function (the orchestrator's ruling on J90-2's dangling-symlink
//! divergence), and a RE-EXPORT (`export { a } from './m.js'`, storage/index.ts). Every expected
//! value is what Node v26.13.0 printed for the same TypeScript (`tests/fixtures/j90_3_probe.ts`,
//! imported by Node, which strips the types, over the same bed).

use std::path::{Path, PathBuf};
use std::process::Command;

fn python() -> String {
    std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string())
}

fn run_python(script: &str, args: &[&Path]) -> String {
    let python = python();
    let run = Command::new(&python)
        .arg("-c")
        .arg(script)
        .args(args)
        .output()
        .unwrap_or_else(|err| {
            panic!("cannot run {python}: {err}; this test runs generated code under Python (set TS2PY_PYTHON)")
        });
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    String::from_utf8(run.stdout).unwrap()
}

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("ts2py-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn package(dir: &Path, modules: &[ts2py::Compiled]) {
    let package = dir.join("pkg");
    std::fs::create_dir_all(&package).unwrap();
    std::fs::write(package.join("__init__.py"), "").unwrap();
    std::fs::write(package.join("_ts2py_runtime.py"), ts2py::RUNTIME).unwrap();
    std::fs::write(
        package.join("_ts2py_adapters.py"),
        ts2py_bantamkit::adapters_module("._ts2py_runtime"),
    )
    .unwrap();
    for module in modules {
        std::fs::write(
            package.join(format!("{}.py", module.py_module)),
            &module.code,
        )
        .unwrap();
    }
}

fn options() -> ts2py::Options {
    ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py_bantamkit::options()
    }
}

fn compile_package(sources: &[(&str, &str)]) -> Vec<ts2py::Compiled> {
    ts2py::compile_modules(sources, &options())
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")))
}

fn refusals(sources: &[(&str, &str)]) -> Vec<String> {
    match ts2py::compile_modules(sources, &options()) {
        Ok(_) => panic!("expected a refusal"),
        Err(lines) => lines,
    }
}

/// `JSON.stringify(probe(bed))` and `relFuzz(20000)` as Node v26.13.0 printed them (macOS arm64).
const NODE_PROBE: &str = r#"[[true,false,true],["aMOpbGxvAPCfmIA=","","YWI=","YWJj"],[true,true,"bigint","bigint",true,false],["threw","ENOENT"],[null,false],["threw","ENOTEMPTY"],["threw","ENOTDIR"],["threw","ENOENT"],[null,false],[[true,"ERR_INVALID_ARG_TYPE","The \"path\" argument must be of type string. Received undefined"],[true,"ERR_INVALID_ARG_TYPE","The \"path\" argument must be of type string. Received null"],"/"],["real","real","dangle","dangle/sub","nothing/deeper","f.txt",""]]"#;
const NODE_REL_FUZZ: &str = "499719387";
/// `longScan(200000)`: every unit of a 200,000-character string that is not ASCII.
const NODE_LONG_SCAN: &str = "282233859";

#[cfg(unix)]
#[test]
fn j90_3_builtins_answer_like_node() {
    let source = include_str!("fixtures/j90_3_probe.ts");
    let modules = compile_package(&[("runtime-ts/src/j90_3_probe.ts", source)]);
    let code = &modules[0].code;
    for lowered in [
        "_js_m_equals(",
        "unlink_sync(",
        "rmdir_sync(",
        "path_relative(",
        "PATH_SEP",
        "node_realpath(",
    ] {
        assert!(code.contains(lowered), "{lowered} missing in:\n{code}");
    }
    let dir = scratch("j90-3-probe");
    package(&dir, &modules);
    let bed = dir.join("bed");
    std::fs::create_dir_all(bed.join("real")).unwrap();
    std::os::unix::fs::symlink("real", bed.join("live")).unwrap();
    std::os::unix::fs::symlink("missing-target", bed.join("dangle")).unwrap();
    let out = run_python(
        "import sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import _ts2py_runtime as rt, j90_3_probe as m\nprint(rt._js_json_stringify(m.probe(sys.argv[2])))\nprint(m.rel_fuzz(20000))\nprint(m.long_scan(200000))\n",
        &[&dir, &bed],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let mut lines = out.lines();
    assert_eq!(lines.next().unwrap(), NODE_PROBE);
    assert_eq!(lines.next().unwrap(), NODE_REL_FUZZ);
    // J90-3: quadratic before `_js_code_units` held a long string by identity (minutes; it is
    // well under a second now).
    assert_eq!(lines.next().unwrap(), NODE_LONG_SCAN);
}

/// J90-3: `export { a, type T } from './m.js'` re-exports what an import of the same names binds:
/// a compiled module's name, or an adapter row's; a type is dropped. The names are exported.
#[test]
fn j90_3_a_re_export_binds_what_an_import_would() {
    let m = "export const A = 1;\nexport type T = number;\nexport function twice(n: number): number {\n  return n * 2;\n}\n";
    let index = "export { A, twice, type T } from './m.js';\nexport { nodeRealpath } from './storage/realpath.js';\nexport type { T as U } from './m.js';\n";
    let modules = compile_package(&[
        ("runtime-ts/src/m.ts", m),
        ("runtime-ts/src/index.ts", index),
    ]);
    let code = &modules
        .iter()
        .find(|x| x.py_module == "index")
        .unwrap()
        .code;
    assert!(code.contains("from .m import A, twice\n"), "{code}");
    assert!(
        code.contains("from ._ts2py_adapters import node_realpath\n"),
        "{code}"
    );
    assert!(
        code.contains(r#"__all__ = ["A", "node_realpath", "twice"]"#),
        "{code}"
    );
    let dir = scratch("j90-3-reexport");
    package(&dir, &modules);
    let out = run_python(
        "import sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import index\nprint(index.A, index.twice(21), callable(index.node_realpath))\n",
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(out.trim(), "1 42 True");
}

/// J90-3: what a re-export may not do, refused: rename, re-export everything, name what the module
/// does not export or what neither a compiled module nor an adapter provides. A namespace member
/// that is no adapter constant stays refused.
#[test]
fn j90_3_re_export_and_namespace_refusals() {
    let m = "export const A = 1;\n";
    let lines = refusals(&[
        ("m.ts", m),
        (
            "i.ts",
            "export { A as B } from './m.js';\nexport * from './m.js';\nexport { C } from './m.js';\nexport { D } from './elsewhere.js';\n",
        ),
    ]);
    for want in [
        "i.ts:1:10: unsupported renamed re-export: A as B",
        "i.ts:2:1: unsupported export *: export * from './m.js';",
        "i.ts:3:10: unsupported re-export of C from ./m.js, which that module does not export: C",
        "i.ts:4:10: unsupported re-export of D from ./elsewhere.js: no compiled module and no declared adapter: D",
    ] {
        assert!(
            lines.iter().any(|l| l.starts_with(want)),
            "{want} not in {lines:?}"
        );
    }
    let lines = refusals(&[(
        "n.ts",
        "import * as path from 'node:path';\nexport const D = path.delimiter;\n",
    )]);
    assert!(lines.iter().any(|l| l.starts_with("n.ts:2:")), "{lines:?}");
}
