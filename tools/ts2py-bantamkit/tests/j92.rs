//! J91-2 (#341): the lowerings J91-2 added (RULES.md, *J91-2 rules*): `parseInt(<hash chain>
//! .slice(0, N), 16)` is `hash_hex_int(alg, x, N)` for N in `[1, 13]` (an index), and a
//! destructuring for-of over a proven list unpacks each item in the loop (`_js_row` for an item that
//! is not a list of exactly the pattern's length) instead of through `_js_rows`' generator. The third
//! rule (a fact drops a range or sign test, never a type test, so mypyc keeps narrowing) is pinned
//! in tests/j91.rs, where the J91-1 forms are asserted.
//!
//! Pinned ANSWERING as Node does: `probe()` and `fuzz(3000)` of `tests/fixtures/j92_probe.ts`, both
//! what Node v26.13.0 printed for that file (types stripped; `fixtures/j92_probe.node.txt`), with
//! each rule present in the compiled text where it applies and absent where it does not (14 digits,
//! a slice not from 0, another radix, no radix, a slice of a string that is not a digest; a for-of
//! over a value not proven a list). Pinned EQUAL TO THE GENERAL PATH: every fast form has a twin in
//! the fixture whose operand is laundered through `opaque`, so it keeps the general lowering; `fuzz`
//! counts the seeded cases where the twins differ (0 in both runtimes), and in Python
//! `hash_hex_int` and `_js_row` are held to the general lowering over values JS code cannot build
//! (non-`str` data, `str` subclasses, surrogate-escaped bytes, tuples, dicts, Maps, `None`), with
//! the same answer or the same exception.

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
    let source = include_str!("fixtures/j92_probe.ts");
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py_bantamkit::options()
    };
    ts2py::compile_modules(&[("runtime-ts/src/j92_probe.ts", source)], &options)
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

#[test]
fn lowerings_answer_like_node() {
    let modules = compiled();
    let code = &modules[0].code;
    // Every N in [1, 13], both algorithms: one call each, and the index it answers added plainly.
    let fast = function(code, "hash_fast");
    for form in [
        "hash_hex_int(\"sha256\", t, 1)",
        "hash_hex_int(\"sha256\", t, 2)",
        "hash_hex_int(\"sha256\", t, 7)",
        "hash_hex_int(\"sha256\", t, 8)",
        "hash_hex_int(\"sha256\", t, 12)",
        "hash_hex_int(\"sha256\", t, 13)",
        "hash_hex_int(\"sha1\", t, 3)",
        "hash_hex_int(\"sha1\", t, 8)",
        "hash_hex_int(\"sha1\", t, 13)",
        "h = hash_hex_int(\"sha256\", t, 8)",
        "h + 1,",
    ] {
        assert!(fast.contains(form), "missing {form}\nin:\n{fast}");
    }
    assert!(!fast.contains("_js_parse_int"), "{fast}");
    // Not taken: 14 digits, a slice from 1, radix 10, no radix, a slice of the input itself; and
    // the laundered twin.
    let not_taken = function(code, "_hash_not_taken__typed");
    assert!(!not_taken.contains("hash_hex_int"), "{not_taken}");
    for form in [
        "_js_parse_int(_js_str_slice(hash_hex(\"sha256\", t), 0, 14), 16)",
        "_js_parse_int(_js_str_slice(hash_hex(\"sha256\", t), 1, 8), 16)",
        "_js_parse_int(_js_str_slice(hash_hex(\"sha256\", t), 0, 8), 10)",
        "_js_parse_int(_js_str_slice(hash_hex(\"sha256\", t), 0, 8))",
    ] {
        assert!(not_taken.contains(form), "missing {form}\nin:\n{not_taken}");
    }
    let guarded = function(code, "hash_guarded");
    assert!(!guarded.contains("hash_hex_int"), "{guarded}");
    // A proven list's rows: Python's own list iterator, each item unpacked in the loop; four
    // names, a hole, one name (its trailing comma), and a list pushed to while it is walked.
    let rows = function(code, "_rows_fast__typed");
    for form in [
        "for _js_r1 in rows:\n        a, b, c, d = _js_r1 if type(_js_r1) is list and len(_js_r1) == 4 else _js_row(_js_r1, 4, (0, 1, 2, 3))",
        "for _js_r2 in rows:\n        _js_hole, b = _js_r2 if type(_js_r2) is list and len(_js_r2) == 2 else _js_row(_js_r2, 2, (1,))",
        "for _js_r3 in rows:\n        a, = _js_r3 if type(_js_r3) is list and len(_js_r3) == 1 else _js_row(_js_r3, 1, (0,))",
        "in copy:\n        a, b = ",
    ] {
        assert!(rows.contains(form), "missing {form}\nin:\n{rows}");
    }
    assert!(!rows.contains("_js_rows("), "{rows}");
    // Not a proven list: `_js_rows` as before (the laundered twin, and the untyped entry's body).
    for name in ["rows_guarded", "rows_fast"] {
        let body = function(code, name);
        assert!(
            body.contains("for a, b, c, d in _js_rows("),
            "{name}:\n{body}"
        );
    }
    let dir = scratch("j92-probe");
    package(&dir, &modules);
    let out = run_python(
        "import json, sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import j92_probe as m\nwant = json.loads(sys.argv[2])\nassert m.probe() == want['probe'], [(a, b) for a, b in zip(m.probe(), want['probe']) if a != b][:1]\ngot = m.fuzz(3000)\nassert got == want['fuzz'], (got, want['fuzz'])\nprint(len(want['probe']), got)\n",
        &[
            dir.to_str().unwrap(),
            include_str!("fixtures/j92_probe.node.txt").trim(),
        ],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    // 51 probe lines; no fuzz case where the fast and the general twin differ.
    assert!(out.trim().starts_with("51 0:"), "{out}");
}

const TWINS: &str = r#"
import random, sys
sys.path.insert(0, sys.argv[1])
from pkg import j92_probe as P
from pkg import _ts2py_runtime as R
from pkg import _ts2py_adapters as A

def answer(fn, *args):
    try:
        got = fn(*args)
        return ("ok", type(got), got)
    except Exception as err:
        return ("raise", type(err).__name__, str(err))

def general(alg, data, digits):
    # The lowering `hash_hex_int` replaces, as J90-P2 wrote it.
    return R._js_parse_int(R._js_str_slice(A.hash_hex(alg, data), 0, digits), 16)

class Sub(str):
    pass

rng = random.Random(92)
UNITS = ["a", "Z", "0", "é", "中", "\U0001F600", "\ud800", "\udbff", "\udc00", "\udfff",
         "\udc80", "\udcff", "�", "\x00", "\n", " "]
bad = checked = 0
for case in range(3000):
    text = "".join(rng.choice(UNITS) for _ in range(rng.randrange(7)))
    for alg in ("sha256", "sha1"):
        for digits in range(1, 14):
            checked += 1
            a, b = answer(A.hash_hex_int, alg, text, digits), answer(general, alg, text, digits)
            if a != b:
                bad += 1
                if bad < 6:
                    print("DIFF hash", alg, repr(text), digits, a, b)
# Not a `str`: the general lowering's answer or refusal, value by value.
for data in [None, 1, 1.5, True, b"ab", bytearray(b"ab"), memoryview(b"ab"), [1], {}, R._JS_UNDEFINED,
             R._JsBigInt(3), R._JsMap(), Sub("ab"), Sub("\ud800")]:
    for alg in ("sha256", "sha1"):
        for digits in (1, 8, 13):
            checked += 1
            a, b = answer(A.hash_hex_int, alg, data, digits), answer(general, alg, data, digits)
            if a != b:
                bad += 1
                print("DIFF data", alg, repr(data), digits, a, b)
# `_js_row` is `_js_rows`' answer for one item; the inline unpack and `_js_rows` agree on a whole
# list of items JS code cannot build, item by item, answer or exception.
m = R._JsMap(); m.set(0, "zero")
ITEMS = [[], [1], [1, 2], [1, 2, 3], [1, 2, 3, 4], [1, 2, 3, 4, 5], (1, 2, 3, 4), "abcd", "\U0001F600x",
         {"0": "a", "1": "b"}, m, None, R._JS_UNDEFINED, 7, [None, R._JS_UNDEFINED, -0.0, float("nan")]]
for item in ITEMS:
    for n, wanted in ((4, (0, 1, 2, 3)), (2, (1,)), (1, (0,)), (3, (0, 2))):
        checked += 1
        a = answer(lambda: R._js_row(item, n, wanted))
        b = answer(lambda: next(R._js_rows([item], n, wanted)))
        if a != b:
            bad += 1
            print("DIFF row", repr(item), n, wanted, a, b)
for case in range(3000):
    rows = [rng.choice(ITEMS) for _ in range(rng.randrange(6))]
    checked += 1
    a, b = answer(P.rows_fast, rows), answer(P.rows_guarded, rows)
    if a != b:
        bad += 1
        if bad < 12:
            print("DIFF rows", rows, a, b)
print("checked", checked, "bad", bad)
"#;

#[test]
fn fast_forms_equal_the_general_ones_on_python_values() {
    let dir = scratch("j92-twins");
    package(&dir, &compiled());
    let out = run_python(TWINS, &[dir.to_str().unwrap()]);
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(out.trim().ends_with("bad 0"), "{out}");
    assert!(out.contains("checked 81144 bad 0"), "{out}");
}
