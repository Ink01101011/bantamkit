//! J91-1 (#341): the type facts J91-1 added (RULES.md, *J91-1 rules*): a receiver bound to
//! `new Map(...)` is a `_JsMap` (`map`), a counted loop's variable is an index in its body, a length
//! is an index, `+` / `-` of two indices is exact, and a guarded expansion leaves out each test its
//! operands' facts answer.
//!
//! Pinned ANSWERING as Node does: `probe()` and `fuzz(3000)` of `tests/fixtures/j91_probe.ts`, both
//! what Node v26.13.0 printed for that file (types stripped; `fixtures/j91_probe.node.txt`), with
//! each rule present in the compiled text where its fact holds and absent where it does not (a
//! Map another function can reach, loops that are not counted, a safe int that is not an index).
//! Pinned EQUAL TO THE GUARDED PATH: every fast form has a twin in the fixture whose operands are
//! laundered through `opaque` (or counted by a `while`), so it keeps every guard; `fuzz` counts the
//! seeded cases where the twins differ (0 in both runtimes), and in Python both twins are run over
//! seeded lists of values JS code cannot build (ints past 2**53, bools, `1.0`, `-0.0`, NaN, lone
//! surrogates, BigInts) and held to the same answer, or the same exception.

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
    let source = include_str!("fixtures/j91_probe.ts");
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py_bantamkit::options()
    };
    ts2py::compile_modules(&[("runtime-ts/src/j91_probe.ts", source)], &options)
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")))
}

/// The text of the Python function `name` (its `def` line to the next top-level line).
fn function<'c>(code: &'c str, name: &str) -> &'c str {
    let start = code
        .find(&format!("\ndef {name}("))
        .unwrap_or_else(|| panic!("no def {name}"));
    let rest = &code[start + 1..];
    let end = rest[1..].find("\ndef ").map_or(rest.len(), |at| at + 1);
    &rest[..end]
}

const KEY: &str =
    "(type(k) is str or type(k) is int and -9007199254740992 <= k <= 9007199254740992)";

#[test]
fn facts_answer_like_node() {
    let modules = compiled();
    let code = &modules[0].code;
    let map_fast = function(code, "_map_fast__typed");
    // A `new Map()` receiver: `has` has no Set arm; a JSON key keeps its key test; a counted index
    // needs none (`m.get(i)` is the receiver test alone). J91-2 (#341): the receiver test
    // `type(m) is _JsMap` stays, the test mypyc narrows the receiver by.
    for form in [
        format!("got = (m._entries.get(k, _JS_UNDEFINED) if type(m) is _JsMap and {KEY} else _js_m_get(m, k))"),
        format!("(k in m._entries if type(m) is _JsMap and {KEY} else _js_m_has(m, k))"),
        format!("if type(m) is _JsMap and {KEY} and m._keys is None:\n            m._entries[k] = shown"),
        "if type(m) is _JsMap and m._keys is None:\n            m._entries[i] = label".to_string(),
        "got = (m._entries.get(i, _JS_UNDEFINED) if type(m) is _JsMap else _js_m_get(m, i))".to_string(),
        // A key proven a number but not a safe int (NaN here) keeps its key test.
        "(m._entries.get(nan, _JS_UNDEFINED) if type(m) is _JsMap and (type(nan) is str or type(nan) is int and -9007199254740992 <= nan <= 9007199254740992) else _js_m_get(m, nan))".to_string(),
        // `new Set()` is never proven a Map: `has` keeps both arms' receiver tests.
        format!("(k in s._entries if type(s) is _JsMap and {KEY} else k in s._items if type(s) is _JsSet and {KEY} else _js_m_has(s, k))"),
        // The counted variable: an index in the body (no sign test; J91-2: `type(i) is int`
        // stays, mypyc's narrowing), an int `+` after it.
        "k = (vals[i] if type(i) is int and i < len(vals) else _js_list_at(vals, i))".to_string(),
        "i = i + 1".to_string(),
    ] {
        assert!(map_fast.contains(&form), "missing {form}\nin:\n{map_fast}");
    }
    assert!(!map_fast.contains("m._items"), "{map_fast}");
    // The guarded twin and a parameter: never proven a Map.
    for name in ["_map_guarded__typed", "map_param"] {
        let body = function(code, name);
        assert!(body.contains("if type(m) is _JsMap and"), "{name}:\n{body}");
    }
    let counted = function(code, "_counted_fast__typed");
    for form in [
        // `i + 1` and `i - 1` of an index are ints (safe; one may be -1): no `_js_num`. A read
        // by an index needs no sign test; J91-2 (#341): every read and store keeps its type tests
        // (`type(i) is int`, a receiver's `type(ys) is list`), the tests mypyc narrows by, and a
        // safe int that is not an index keeps its sign test too.
        "k = i + 1",
        "j = i - 1",
        "here = (xs[i] if type(i) is int and i < len(xs) else _js_list_at(xs, i))",
        "after = (ys[k] if type(k) is int and 0 <= k < len(ys) else _js_list_at(ys, k))",
        "before = (xs[j] if type(j) is int and 0 <= j < len(xs) else _js_list_at(xs, j))",
        "if type(ys) is list and type(k) is int and 0 <= k < len(ys):\n            ys[k] = here",
        // A stride, a literal bound, `ys.length - i`, `++i`.
        "i = i + 2",
        "n = len(ys) - i",
        "(ys[n] if type(n) is int and 0 <= n < len(ys) else _js_list_at(ys, n))",
    ] {
        assert!(counted.contains(form), "missing {form}\nin:\n{counted}");
    }
    // Not counted: the body assigns `i`, the start is negative, the bound or the start is a value
    // passed in, the stride is a name. Every read keeps `type(i) is int and 0 <= i`.
    let not_counted = function(code, "_not_counted__typed");
    assert_eq!(
        not_counted
            .matches("(xs[i] if type(i) is int and 0 <= i < len(xs) else _js_list_at(xs, i))")
            .count(),
        5,
        "{not_counted}"
    );
    // Only the counted store loop (`obj[i] = i`) steps by Python's int `+`.
    assert_eq!(not_counted.matches("i = i + 1").count(), 1, "{not_counted}");
    for form in [
        // `.length` of a value not proven a list or a string proves nothing.
        "(x[n] if type(n) is int and 0 <= n < len(x) else _js_list_at(x, n))",
        // A store into a value not proven a list keeps its list test.
        "if type(obj) is list and type(i) is int and i < len(obj):\n            obj[i] = i",
    ] {
        assert!(
            not_counted.contains(form),
            "missing {form}\nin:\n{not_counted}"
        );
    }
    let arithmetic = function(code, "_arithmetic__typed");
    for form in [
        // Two indices: plain int arithmetic; a safe int that is not an index: `_js_num` as before.
        "s = a + i",
        "d = i - a",
        "_js_str(half + half)",
        "_js_str(half + i)",
        "_js_str(_js_num(big + 2))",
        "_js_str(_js_num(big + i))",
        // `v + i`, `i` an index: `v`'s own test and `i`'s type test (J91-2: mypyc's narrowing);
        // `v + big`, `big` not an index: both tests.
        "w = (v + i if type(v) is int and type(i) is int and -4503599627370496 <= v <= 4503599627370496 else _js_add(v, i))",
        "wb = (v + big if type(v) is int and type(big) is int and -4503599627370496 <= big <= 4503599627370496 and -4503599627370496 <= v <= 4503599627370496 else _js_add(v, big))",
        // `===` with one side a proven number: the int arm alone; an index needs no range test
        // (J91-2: its `type(x) is int` stays, mypyc's narrowing).
        "(a == v if type(a) is int and type(v) is int and -9007199254740992 <= v <= 9007199254740992 else _js_strict_eq(a, v))",
        "(top == v if type(top) is int and -9007199254740992 <= top <= 9007199254740992 and type(v) is int and -9007199254740992 <= v <= 9007199254740992 else _js_strict_eq(top, v))",
        "(v != i if type(v) is int and -9007199254740992 <= v <= 9007199254740992 and type(i) is int else not _js_strict_eq(v, i))",
    ] {
        assert!(
            arithmetic.contains(form),
            "missing {form}\nin:\n{arithmetic}"
        );
    }
    let dir = scratch("j91-probe");
    package(&dir, &modules);
    let out = run_python(
        "import json, sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import j91_probe as m\nwant = json.loads(sys.argv[2])\nassert m.probe() == want['probe'], [(a, b) for a, b in zip(m.probe(), want['probe']) if a != b][:1]\ngot = m.fuzz(3000)\nassert got == want['fuzz'], (got, want['fuzz'])\nprint(len(want['probe']), got)\n",
        &[
            dir.to_str().unwrap(),
            include_str!("fixtures/j91_probe.node.txt").trim(),
        ],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    // 10 probe lines; no fuzz case where the fast and the guarded twin differ.
    assert!(out.trim().starts_with("10 0:"), "{out}");
}

const TWINS: &str = r#"
import math, random, sys
sys.path.insert(0, sys.argv[1])
from pkg import j91_probe as P
from pkg import _ts2py_runtime as R

# Values JS code cannot build next to ones it can: an int past 2**53 is its own Map key in no JS
# program, `True` is not `1`, `1.0` is `1`, `-0.0` is `0`, NaN is itself; a BigInt.
POOL = [
    "a", "1", "", "\ud800", "\udc00x", "\U0001F600", 0, 1, -1, 2, 3, 7, 1.0, -0.0, 0.5, 1.5,
    float("nan"), float("inf"), True, False, None, R._JS_UNDEFINED, R._JsBigInt(3),
    2**52, 2**52 + 1, 2**53 - 1, 2**53, 2**53 + 1, -(2**53) - 1, 2**60, 10**30, 2.0**53,
]

def norm(v):
    if isinstance(v, float) and v != v:
        return ("nan",)
    if isinstance(v, float):
        return (float, v, math.copysign(1.0, v))
    return (type(v), v)

def answer(fn, *args):
    try:
        return ("ok", norm(fn(*args)))
    except Exception as err:
        return ("raise", type(err).__name__, str(err))

rng = random.Random(91)
bad = checked = 0
pairs = [
    (P.map_fast, P.map_guarded, lambda xs: (xs,)),
    (P.counted_fast, P.counted_guarded, lambda xs: (xs,)),
    (P.arithmetic, P.arithmetic_guarded, lambda xs: (xs[:2], [v for v in xs if type(v) in (str, int, float)])),
]
for case in range(3000):
    xs = [rng.choice(POOL) for _ in range(rng.randrange(9))]
    for fast, guarded, args in pairs:
        checked += 1
        a, b = answer(fast, *args(xs)), answer(guarded, *args(xs))
        if a != b:
            bad += 1
            if bad < 6:
                print("DIFF", fast.__name__, xs, a, b)
# A Map another function can reach: a subclass, a dict, a Set and `None` take the helper's path.
class SubMap(R._JsMap):
    pass
def reference(m, keys):
    out = ""
    for k in keys:
        if R._js_m_has(m, k):
            out += P._show(k) + ":" + R._js_str(R._js_m_get(m, k)) + ";"
        else:
            out += P._show(k) + ":none;"
        R._js_m_set(m, k, 1)
    return out
for make in (R._JsMap, SubMap, dict, R._JsSet, lambda: None):
    for keys in ([True, 1, 1.0, -0.0, 0, 2**60, float("nan")], ["\ud800", "a"]):
        checked += 1
        got, want = answer(P.map_param, make(), keys), answer(reference, make(), keys)
        if got != want:
            bad += 1
            print("DIFF param", make, keys, got, want)
print("checked", checked, "bad", bad)
"#;

#[test]
fn fast_twins_equal_the_guarded_ones_on_python_values() {
    let dir = scratch("j91-twins");
    package(&dir, &compiled());
    let out = run_python(TWINS, &[dir.to_str().unwrap()]);
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(out.trim().ends_with("bad 0"), "{out}");
    assert!(out.contains("checked 9010 bad 0"), "{out}");
}
