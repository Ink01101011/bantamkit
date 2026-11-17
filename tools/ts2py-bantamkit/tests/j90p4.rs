//! J90-P4 (#316 G4): the `fs.Stats` adapter's `ino`, which the hot index's held-head check reads
//! (`statHead`: `${st.mtimeNs}:${st.size}:${st.ino}`). Until J90-P4 neither `Stats` nor
//! `BigIntStats` carried it, so the generated Python read `undefined` where Node reads libuv's
//! `st_ino`: a head replaced by a file of the same mtime and size (a rename over it) was a
//! held head to Python and a new head to Node, which reloads. Node's answer, per libuv: the
//! BigInt form is `st_ino` exactly; the number form is that integer as a double.

use std::path::{Path, PathBuf};
use std::process::Command;

fn python() -> String {
    std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string())
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

const PROBE: &str = "import * as fs from 'node:fs';
export function ino(p: string): string {
  const a = fs.statSync(p, { bigint: true });
  const b = fs.statSync(p);
  const c = fs.lstatSync(p, { bigint: true });
  const d = fs.lstatSync(p);
  return `${a.ino}:${b.ino}:${c.ino}:${d.ino}`;
}
";

#[test]
fn stats_carry_node_s_ino() {
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py_bantamkit::options()
    };
    let modules = ts2py::compile_modules(&[("runtime-ts/src/inoprobe.ts", PROBE)], &options)
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    let dir = scratch("j90p4-ino");
    package(&dir, &modules);
    let file = dir.join("f.txt");
    std::fs::write(&file, "x").unwrap();
    let link = dir.join("l.txt");
    #[cfg(unix)]
    std::os::unix::fs::symlink(&file, &link).unwrap();
    #[cfg(not(unix))]
    std::fs::copy(&file, &link).unwrap();
    // Node's number `ino` is the integer as a double, printed as JS prints it; the BigInt is exact.
    let script = "import os, sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import inoprobe\nfrom pkg._ts2py_runtime import _js_num_str, _js_num\np = sys.argv[2]\ns, l = os.stat(p).st_ino, os.lstat(p).st_ino\nwant = f'{s}:{_js_num_str(_js_num(s))}:{l}:{_js_num_str(_js_num(l))}'\ngot = inoprobe.ino(p)\nprint(got == want, got, want)\n";
    let run = Command::new(python())
        .arg("-c")
        .arg(script)
        .arg(&dir)
        .arg(&link)
        .output()
        .expect("python");
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    let out = String::from_utf8(run.stdout).unwrap();
    assert!(out.starts_with("True "), "{out}");
    assert!(!out.contains("undefined"), "{out}");
}
