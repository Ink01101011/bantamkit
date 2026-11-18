//! J90-P6 (#316 G4): guarded inline expansion. Inside a loop body, `m.get(k)`, `a === b` /
//! `a !== b` and `a + b` are written as a conditional expression whose fast arm is the helper's own
//! first branch under an exact-type guard at least as strict, and whose slow arm is the unchanged
//! helper call (`lower.rs`, `hot`; RULES.md, *J90-P6 rules*).
//!
//! Pinned ANSWERING as Node does: `probe()` (every pair of an adversarial pool through `===`,
//! `!==` and `+`, a Map read by every pool value, a running Map sum through ints past 2^52) and
//! `fuzz(3000)` of `tests/fixtures/j90p6_probe.ts`, both what Node v26.13.0 printed for that file
//! with `--experimental-strip-types`.
//! Pinned EQUAL TO THE HELPER on values JS code cannot build: `expansion_equals_the_helper` calls
//! each expansion with Python values (ints past 2^53, bools, BigInts, `-0.0`, NaN, astral strings,
//! an object that is not a Map but has `_entries`) and holds it to the helper's answer, value and
//! type, or the same exception. Pinned TAKEN: the fast arms run with the helpers patched out.

use std::path::{Path, PathBuf};
use std::process::Command;

fn python() -> String {
    std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string())
}

fn run_python(script: &str, args: &[&str]) -> String {
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

fn compiled() -> Vec<ts2py::Compiled> {
    let source = include_str!("fixtures/j90p6_probe.ts");
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py_bantamkit::options()
    };
    ts2py::compile_modules(&[("runtime-ts/src/j90p6_probe.ts", source)], &options)
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")))
}

/// What Node v26.13.0 printed for `probe()`: 71 lines, as sha256 of their text, each line ended by
/// a newline (first 16 hex digits); and for `fuzz(3000)`.
const NODE_PROBE: &str = "72447cb294416689";
const NODE_FUZZ: &str = "1ed50fec2823aa9f";

#[test]
fn expansions_answer_like_node() {
    let modules = compiled();
    let code = &modules[0].code;
    // The three expansions are what the probe exercised (J90-PF widened the key test to a safe
    // int and `===` to two safe ints: tests/j90pf.rs).
    for form in [
        "._entries.get(k, _JS_UNDEFINED) if type(m) is _JsMap and (type(k) is str or type(k) is int and -9007199254740992 <= k <= 9007199254740992) else _js_m_get(m, k))",
        "(a == b if type(a) is type(b) is str or type(a) is type(b) is int and -9007199254740992 <= a <= 9007199254740992 and -9007199254740992 <= b <= 9007199254740992 else _js_strict_eq(a, b))",
        "(a != b if type(a) is type(b) is str or type(a) is type(b) is int and -9007199254740992 <= a <= 9007199254740992 and -9007199254740992 <= b <= 9007199254740992 else not _js_strict_eq(a, b))",
        "(x + y if type(x) is int and type(y) is int and -4503599627370496 <= y <= 4503599627370496 and -4503599627370496 <= x <= 4503599627370496 else _js_add(x, y))",
        "(s + 1 if type(s) is int and -4503599627370496 <= s <= 4503599627370496 else _js_add(s, 1))",
    ] {
        assert!(code.contains(form), "missing expansion {form}");
    }
    let dir = scratch("j90p6-probe");
    package(&dir, &modules);
    let out = run_python(
        "import hashlib, sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import j90p6_probe as m\ntext = ''.join(line + '\\n' for line in m.probe())\nprint(len(text.splitlines()), hashlib.sha256(text.encode()).hexdigest()[:16])\nprint(m.fuzz(3000))\n",
        &[dir.to_str().unwrap()],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let lines: Vec<&str> = out.lines().collect();
    assert_eq!(lines[0], format!("71 {NODE_PROBE}"));
    assert_eq!(lines[1], NODE_FUZZ);
}

const REFERENCE: &str = r#"
import itertools, math, sys
sys.path.insert(0, sys.argv[1])
from pkg import j90p6_probe as P
from pkg import _ts2py_runtime as R

class NotAMap:
    _keys = None
    def __init__(self):
        self._entries = {"a": "not a Map"}

class SubMap(R._JsMap):
    pass

POOL = [
    "a", "1", "", "\U0001F600", "\ud83d", 0, 1, -1, 7, -0.0, 0.0, 0.5, 1.5, float("nan"), float("inf"),
    True, False, None, R._JS_UNDEFINED, R._JsBigInt(5), R._JsBigInt(2**70),
    2**52 - 1, 2**52, 2**52 + 1, -(2**52), -(2**52) - 1, 2**53 - 1, 2**53, 2**53 + 1, -(2**53) - 1,
    2**60, 10**30, 2.0**53, 1e21, [], {},
]

def answer(fn, *args):
    try:
        value = fn(*args)
    except Exception as err:
        return ("raise", type(err).__name__, str(err))
    if isinstance(value, float) and value != value:
        return ("nan",)
    if isinstance(value, float):
        return (float, value, math.copysign(1.0, value))
    return (type(value), value) if not isinstance(value, (list, dict)) else (type(value), id(value))

def maps():
    out = []
    plain = R._JsMap()
    for key in POOL:
        if not isinstance(key, (list, dict)):
            plain.set(key, key)
    plain.set("a", 2**53)
    plain.set("b", 2**52 + 1)
    plain.set("c", "\ud83d")
    plain.set("d", 2**53 + 1)
    out.append(plain)
    sub = SubMap()
    sub.set("a", 1)
    out.append(sub)
    out.append(NotAMap())
    out.append({"a": 1})
    out.append(None)
    return out

bad = 0
checked = 0
def check(label, got, want):
    global bad, checked
    checked += 1
    if got != want:
        bad += 1
        if bad < 6:
            print("DIFF", label, got, want)

for a, b in itertools.product(POOL, POOL):
    check(("add", a, b), answer(P.add_in, a, b), answer(R._js_add, a, b))
    check(("eq", a, b), answer(P.eq_in, a, b), answer(R._js_strict_eq, a, b))
    check(("ne", a, b), answer(P.ne_in, a, b), answer(lambda x, y: not R._js_strict_eq(x, y), a, b))
for a in POOL:
    check(("add1", a), answer(P.add_one_in, a), answer(R._js_add, a, 1))
for m in maps():
    for k in POOL + ["b", "c", "d", "missing"]:
        if isinstance(k, (list, dict)):
            continue
        check(("get", k), answer(P.get_in, m, k), answer(R._js_m_get, m, k))
        for b in POOL:
            check(("geteq", k, b), answer(P.get_eq_in, m, k, b), answer(lambda: R._js_strict_eq(R._js_m_get(m, k), b)))
            check(("getadd", k, b), answer(P.get_add_in, m, k, b), answer(lambda: R._js_add(R._js_m_get(m, k), b)))
print("checked", checked, "bad", bad)

m = R._JsMap()
m.set("k", 1)
assert P.map_in(m, "k", 1, [1, 2]) == [2, 3] and P.map_in(m, "j", 1, [1, 2]) == []

# TAKEN: with every helper patched to fail, the fast arms still answer for the values they are for.
def boom(*_):
    raise AssertionError("helper called")
for name in ("_js_add", "_js_strict_eq", "_js_m_get"):
    setattr(P, name, boom)
m = R._JsMap()
m.set("k", 2**52)
assert P.get_in(m, "k") == 2**52
m.set("s", "v")
assert P.get_eq_in(m, "s", "v") is True
assert P.get_add_in(m, "k", 2**52) == 2**53
assert P.eq_in("x", "x") is True and P.ne_in("x", "y") is True
print("taken")
"#;

#[test]
fn expansion_equals_the_helper() {
    let dir = scratch("j90p6-reference");
    package(&dir, &compiled());
    let out = run_python(REFERENCE, &[dir.to_str().unwrap()]);
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(out.contains("bad 0\n"), "{out}");
    assert!(out.ends_with("taken\n"), "{out}");
}
