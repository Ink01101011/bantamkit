//! #345: catchable JS errors and ignored extra arguments must agree with Node.
use std::process::Command;

fn compare(probe: &str) {
    let source = include_str!("fixtures/try_semantics.ts");
    let module = ts2py::compile(source, "try_semantics.ts", &ts2py::Options::default())
        .unwrap_or_else(|lines| panic!("probe refused:\n{}", lines.join("\n")));
    let dir = std::env::temp_dir().join(format!("ts2py-{probe}-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let ts = dir.join("probe.mjs");
    let py = dir.join("probe.py");
    std::fs::write(&ts, source).unwrap();
    std::fs::write(&py, module).unwrap();
    let node = Command::new("node")
        .args(["--input-type=module", "-e"])
        .arg("import {pathToFileURL} from 'node:url'; const m = await import(pathToFileURL(process.argv[1])); console.log(m[process.argv[2]]());")
        .arg(&ts)
        .arg(probe)
        .output()
        .expect("Node is required to check JS semantics");
    let python = std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let run = Command::new(python)
        .arg("-c")
        .arg("import importlib.util, sys; spec = importlib.util.spec_from_file_location('p', sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(getattr(m, sys.argv[2])())")
        .arg(&py)
        .arg(if probe == "propertyProbe" { "property_probe" } else { "arguments_probe" })
        .output()
        .expect("TS2PY_PYTHON must name a working Python interpreter");
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(
        node.status.success(),
        "{}",
        String::from_utf8_lossy(&node.stderr)
    );
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    assert_eq!(
        String::from_utf8(run.stdout).unwrap().trim(),
        String::from_utf8(node.stdout).unwrap().trim(),
        "{probe} differs from Node"
    );
}

#[test]
fn nullish_property_reads_raise_js_type_errors() {
    compare("propertyProbe");
}

#[test]
fn extra_arrow_arguments_are_evaluated_and_ignored() {
    compare("argumentsProbe");
}
