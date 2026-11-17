//! J90-P2 (#316 G4): bantamkit's adapter module ships without its comments and docstrings
//! (`ts2py::shipped`, with bantamkit's `shipped_note`), and that changes no statement: Python's
//! `ast.dump` of the shipped adapter module is the source's (the compiler's own `tests/shipped.rs`
//! holds the runtime to the same), once each function's and class's docstring (which `shipped`
//! drops when the body goes on) is set aside. A rule that cut a code line, or a line inside a
//! string, is red here.

use std::process::Command;

const SAME_CODE: &str = r#"
import ast, sys
def without_docstrings(text):
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = node.body
            if len(b) > 1 and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) and isinstance(b[0].value.value, str):
                del b[0]
    return ast.dump(tree)
source, shipped = open(sys.argv[1]).read(), open(sys.argv[2]).read()
print(without_docstrings(source) == without_docstrings(shipped), len(source), len(shipped))
"#;

#[test]
fn shipped_support_modules_are_the_source_statement_for_statement() {
    let python = std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let dir = std::env::temp_dir().join(format!("ts2py-bantamkit-shipped-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let adapters = ts2py_bantamkit::adapters_module("._ts2py_runtime");
    {
        let (name, source) = ("adapters", adapters.as_str());
        let shipped = ts2py_bantamkit::shipped(source);
        assert!(shipped.contains(&ts2py_bantamkit::shipped_note()));
        assert!(
            shipped.len() < source.len() * 3 / 4,
            "{name}: {} of {}",
            shipped.len(),
            source.len()
        );
        let (a, b) = (
            dir.join(format!("{name}.py")),
            dir.join(format!("{name}-shipped.py")),
        );
        std::fs::write(&a, source).unwrap();
        std::fs::write(&b, &shipped).unwrap();
        let run = Command::new(&python)
            .arg("-c")
            .arg(SAME_CODE)
            .arg(&a)
            .arg(&b)
            .output()
            .unwrap_or_else(|err| panic!("cannot run {python}: {err} (set TS2PY_PYTHON)"));
        assert!(
            run.status.success(),
            "{}",
            String::from_utf8_lossy(&run.stderr)
        );
        let out = String::from_utf8(run.stdout).unwrap();
        assert!(out.starts_with("True "), "{name}: {out}");
    }
    std::fs::remove_dir_all(&dir).unwrap();
}
