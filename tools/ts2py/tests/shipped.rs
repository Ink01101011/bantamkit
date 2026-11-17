//! J90-P2 (#316 G4): the support modules ship without their comments and docstrings
//! (`ts2py::shipped`), and that changes no statement: Python's `ast.dump` of the shipped runtime
//! is the source's (a host's adapter module is held to the same in the host's own tests), once each function's and class's docstring (which `shipped`
//! drops when the body goes on) is set aside. A rule that cut a code line, or a line inside a
//! string, is red here.

use std::process::Command;

const NOTE: &str = ts2py::host::DEFAULT_SHIPPED_NOTE;

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
    let dir = std::env::temp_dir().join(format!("ts2py-shipped-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    {
        let (name, source) = ("runtime", ts2py::RUNTIME);
        let shipped = ts2py::shipped(source, NOTE);
        assert!(shipped.contains(NOTE));
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

/// The rule itself: a comment line goes, a comment-like line inside a string stays, a docstring
/// goes only where the body goes on after it.
#[test]
fn shipped_keeps_strings_and_lone_docstrings() {
    let source = "# head\n# more\nimport os\n# gone\nX = \"\"\"\n# kept: in a string\n\"\"\"\n\n\ndef f(\n    a,\n):\n    \"\"\"Gone.\n\n    # still gone\n    \"\"\"\n    return a  # trailing kept\n\n\ndef g():\n    \"\"\"Kept: the only statement.\"\"\"\n\n\nclass C:\n    r\"\"\"Gone.\"\"\"\n\n    x = 1\n";
    let want = format!(
        "# head\n# more\n{}\nimport os\nX = \"\"\"\n# kept: in a string\n\"\"\"\n\n\ndef f(\n    a,\n):\n    return a  # trailing kept\n\n\ndef g():\n    \"\"\"Kept: the only statement.\"\"\"\n\n\nclass C:\n\n    x = 1\n",
        NOTE
    );
    assert_eq!(ts2py::shipped(source, NOTE), want);
}
