//! J90-P7 (#316 G4): the generated Python compiles with mypyc as it stands (RULES.md, *J90-P7
//! rules*). Each form ts2py writes for that is pinned here, in pure Python against what Node
//! v26.13.0 printed for `tests/fixtures/j90p7_probe.ts`, and, when `TS2PY_MYPYC` names a `mypyc`,
//! compiled: the probe module and the runtime are built with it and must answer the same, including
//! for instances of Python subclasses passed into compiled code.
//!
//! Each case is one fault seen when the generated modules were first compiled: a method of a
//! non-native class holding a capturing closure did not compile (mypyc/mypyc#1205); a compiled
//! `isinstance` of a non-native class missed a Python subclass, so `_js_get` read `undefined`; a
//! module-level variable typed by its first value refused a later value of another type.

use std::path::{Path, PathBuf};
use std::process::Command;

/// `JSON.stringify(probe())` as Node v26.13.0 printed it.
const NODE_PROBE: &str = r#"[2,[17,14],"ok","size past 1",1.5,0.75,true,true,false]"#;

fn python() -> String {
    std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string())
}

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("ts2py-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn compiled() -> ts2py::Compiled {
    let source = include_str!("fixtures/j90p7_probe.ts");
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py::Options::default()
    };
    ts2py::compile_modules(&[("src/j90p7_probe.ts", source)], &options)
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")))
        .remove(0)
}

fn package(dir: &Path, module: &ts2py::Compiled) {
    let package = dir.join("pkg");
    std::fs::create_dir_all(&package).unwrap();
    std::fs::write(package.join("__init__.py"), "").unwrap();
    std::fs::write(
        package.join("_ts2py_runtime.py"),
        ts2py::shipped(ts2py::RUNTIME, ts2py::host::DEFAULT_SHIPPED_NOTE),
    )
    .unwrap();
    std::fs::write(package.join("j90p7_probe.py"), &module.code).unwrap();
}

/// The probe's answer, then the two Python-subclass checks, from the package in `dir`.
const DRIVER: &str = r#"
import sys
sys.path.insert(0, sys.argv[1])
from pkg import j90p7_probe as m, _ts2py_runtime as r
print(r._js_json_stringify(m.probe()))
class SubBag(m.Bag):
    pass
class Held(r._JsObject):
    def __init__(self):
        self.v = "seen"
print(m.is_bag(SubBag(1)), m.read_v(Held()), m.__file__.endswith(".py"))
"#;

fn run(dir: &Path) -> String {
    let out = Command::new(python())
        .arg("-c")
        .arg(DRIVER)
        .arg(dir)
        .current_dir(dir)
        .output()
        .expect("python");
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap()
}

#[test]
fn j90p7_forms_are_written() {
    let code = compiled().code;
    for taken in [
        // Every class is an ordinary Python class under mypyc too; its lists are class attributes.
        "@_mypyc_attr(native_class=False)\nclass Bag(_JsObject):\n",
        "@_mypyc_attr(native_class=False)\nclass Oops(_JsError):\n",
        "    _js_own_methods: _ClassVar[frozenset[str]] = frozenset({",
        // A property has a return annotation.
        "    def size(self) -> object:\n",
        // A method holding a closure forwards to a module function with its body.
        "    def scaled(self, k):\n        return _js_method_Bag_scaled(self, k)\n",
        "\ndef _js_method_Bag_scaled(self, k):\n",
        "    def checked(self, limit):\n        return _js_method_Bag_checked(self, limit)\n",
        // `instanceof` through the helper mypyc compiles as the builtin.
        "_js_instanceof(bag, Bag)",
        // A module-level variable is `Any`, whatever its first value.
        "\nratio: _JsAny = 3\n",
    ] {
        assert!(code.contains(taken), "`{taken}` missing in:\n{code}");
    }
    // A method with no closure stays where it is.
    assert!(
        code.contains("    def add(self, n):\n        _js_m_push("),
        "{code}"
    );
    assert!(!code.contains("isinstance(bag, Bag)"), "{code}");
}

#[test]
fn j90p7_probe_answers_like_node_interpreted() {
    let dir = scratch("j90p7-py");
    package(&dir, &compiled());
    assert_eq!(run(&dir), format!("{NODE_PROBE}\nTrue seen True\n"));
}

/// With `TS2PY_MYPYC` set (a `mypyc` whose Python is `TS2PY_PYTHON`'s version), the same package
/// compiled: the probe module and the runtime are extension modules, and answer as interpreted.
#[test]
fn j90p7_probe_answers_like_node_compiled() {
    let Ok(mypyc) = std::env::var("TS2PY_MYPYC") else {
        eprintln!("TS2PY_MYPYC not set: the compiled leg is skipped");
        return;
    };
    let dir = scratch("j90p7-mypyc");
    package(&dir, &compiled());
    std::fs::write(
        dir.join("mypy.ini"),
        "[mypy]\nignore_missing_imports = True\nfollow_imports = silent\n",
    )
    .unwrap();
    let build = Command::new(&mypyc)
        .args(["pkg/_ts2py_runtime.py", "pkg/j90p7_probe.py"])
        .current_dir(&dir)
        .output()
        .expect("mypyc");
    assert!(
        build.status.success(),
        "mypyc failed:\n{}{}",
        String::from_utf8_lossy(&build.stdout),
        String::from_utf8_lossy(&build.stderr)
    );
    assert_eq!(run(&dir), format!("{NODE_PROBE}\nTrue seen False\n"));
}
