//! J89-3 (#316 G3): `Float64Array` (a list of floats, indexed, written by index and measured
//! only), arithmetic on proven floats, counted loops proven once before they run, and the key sort
//! (`SUBSET.md`, *Typed arrays and counted loops*; `RULES.md`, J89-3). Every expected value is what
//! Node v26.13.0 printed for the same TypeScript (`tests/fixtures/j89_3_numeric.ts`): `probe()`'s
//! JSON, and `fuzz(20000)`'s digest of 60,000 answers.

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
        ts2py::adapters_module("._ts2py_runtime"),
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

fn compile(source: &str) -> Result<Vec<ts2py::Compiled>, Vec<String>> {
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py::Options::default()
    };
    ts2py::compile_modules(&[("m.ts", source)], &options)
}

fn code_of(source: &str) -> String {
    let modules = compile(source).unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    modules[0].code.clone()
}

fn refused(source: &str, construct: &str) {
    match compile(source) {
        Ok(modules) => panic!(
            "expected a refusal naming {construct:?}, compiled:\n{}",
            modules[0].code
        ),
        Err(lines) => assert!(
            lines.iter().any(|l| l.contains(construct)),
            "expected {construct:?} in:\n{}",
            lines.join("\n")
        ),
    }
}

/// `JSON.stringify(value)` with every code unit at or above 0x7F written `\uXXXX`.
const PRINT: &str = r#"
def node_json(m, value):
    out = m._js_json_stringify(value)
    return "".join(c if ord(c) < 0x7F else "\\u%04x" % ord(c) for c in m._js_code_units(out))
"#;

fn probe_package(dir: &Path) {
    let modules = compile(include_str!("fixtures/j89_3_numeric.ts"))
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    let code = &modules[0].code;
    // The lowerings are taken: typed arrays, the proven copies, native float arithmetic (an inline
    // zero test for a named divisor, `_js_fdiv` for any other), and the key sort.
    assert!(code.contains("a = _js_f64_new(m)"), "{code}");
    assert!(code.contains("for i in range(i, m):"), "{code}");
    assert!(code.contains("_js_doubles(xs, i, m)"), "{code}");
    assert!(code.contains("add[i] = x + y\n"), "{code}");
    assert!(code.contains("mul[i] = x * y\n"), "{code}");
    assert!(
        code.contains("div[i] = x / y if y else _js_div(x, y)\n"),
        "{code}"
    );
    assert!(code.contains("_js_fdiv(x, y - 0.5)"), "{code}");
    assert!(code.contains("_js_sort_by_f64(xs, k, True, "), "{code}");
    assert!(code.contains("_js_sort_by_f64(xs, k, False, "), "{code}");
    // A carried `let` (`best`'s `top`) is checked before the loop; `joined`'s is not carried.
    assert!(code.contains("_js_is_double(top)"), "{code}");
    assert!(!code.contains("_js_is_double(acc)"), "{code}");
    package(dir, &modules);
}

#[test]
fn j89_3_numeric_lowerings_answer_like_node() {
    let dir = scratch("j89-3-probe");
    probe_package(&dir);
    let out = run_python(
        &format!(
            "{PRINT}\nimport sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import _ts2py_runtime as rt, m\nprint(node_json(rt, m.probe()))\n"
        ),
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(
        out.trim_end(),
        r###"[["0","3","2","0","0","2","3","RangeError: Invalid typed array length: -1.50","0","0","1","RangeError: Invalid typed array length: -1","RangeError: Invalid typed array length: Infinity","RangeError: Invalid typed array length: 9007199254740992","TypeError: Cannot convert a BigInt value to a number"],["1.5","-0","3","undefined:undefined","undefined:undefined","undefined:undefined","1.5","-0","undefined:undefined","3","undefined:undefined","undefined:undefined","undefined:undefined"],["0,5,0","0,0,0","7,0,0","0,0,2.5","0,0,0","1,0,0","0,0,0","NaN,0,0","12,0,0","NaN,0,0","0,1152921504606847000,0","TypeError: Cannot convert a BigInt value to a number","TypeError: Cannot convert a BigInt value to a number"],["0 0 0 NaN NaN 0","0 0 -0 NaN -Infinity 0","1 -1 0 0 3 0","-1 1 -0 -0 -1.5 0","0.5 -0.5 0 0 10 NaN","-2.5 2.5 -0 -0 0.5 0","3 -3 0 0 5 0","1e+300 -1e+300 0 0 3.5 0","-1e+300 1e+300 -0 -0 4 0","5e-324 -5e-324 0 0 Infinity 0","9007199254740992 -9007199254740992 0 0 5.000000000000001 0","Infinity -Infinity NaN 0 5.5 0","-Infinity Infinity NaN -0 6 0","NaN NaN NaN NaN NaN NaN","0 -0 -0 NaN Infinity 0","-0 0 0 NaN -Infinity 0","1 -1 -0 -0 24 -0","-1 1 0 0 -8.5 0","0.5 -0.5 -0 -0 45 NaN","-2.5 2.5 0 0 1.9000000000000004 0","3 -3 -0 -0 16.666666666666668 -0","1e+300 -1e+300 -0 -0 10.5 -0","-1e+300 1e+300 0 0 11 0","5e-324 -5e-324 -0 -0 Infinity 0","9007199254740992 -9007199254740992 -0 -0 12.000000000000004 -0","Infinity -Infinity NaN -0 12.5 -0","-Infinity Infinity NaN 0 13 0","NaN NaN NaN NaN NaN NaN","1 1 0 Infinity Infinity -2","1 1 -0 -Infinity -Infinity -2","2 0 1 1 44.5 2","0 2 -1 -1 -16 -0.6666666666666666","1.5 0.5 0.5 2 79.5 Infinity","-1.5 3.5 -2.5 -0.4 2.8000000000000007 -0.3333333333333333","4 -2 3 0.3333333333333333 27.833333333333336 0.4","1e+300 -1e+300 1e+300 1e-300 17 1e-300","-1e+300 1e+300 -1e+300 -1e-300 17.5 -1e-300","1 1 5e-324 Infinity Infinity -2","9007199254740992 -9007199254740991 9007199254740992 1.1102230246251565e-16 18.500000000000004 1.1102230246251565e-16","Infinity -Infinity Infinity 0 19 0","-Infinity Infinity -Infinity -0 19.5 0","NaN NaN NaN NaN NaN NaN","-1 -1 -0 -Infinity Infinity 2","-1 -1 0 Infinity -Infinity 2","0 -2 -1 -1 66.5 -2","-2 0 1 1 -22 0.6666666666666666","-0.5 -1.5 -0.5 -2 115.5 -Infinity","-3.5 1.5 2.5 0.4 5.199999999999999 0.3333333333333333","2 -4 -3 -0.3333333333333333 40.5 -0.4","1e+300 -1e+300 -1e+300 -1e-300 25 -1e-300","-1e+300 1e+300 1e+300 1e-300 25.5 1e-300","-1 -1 -5e-324 -Infinity Infinity 2","9007199254740991 -9007199254740992 -9007199254740992 -1.1102230246251565e-16 26.500000000000007 -1.1102230246251565e-16","Infinity -Infinity -Infinity -0 27 -0","-Infinity Infinity Infinity 0 27.5 0","NaN NaN NaN NaN NaN NaN","0.5 0.5 0 Infinity Infinity -1","0.5 0.5 -0 -Infinity -Infinity -1","1.5 -0.5 0.5 0.5 86.75 1","-0.5 1.5 -0.5 -0.5 -29.75 -0.3333333333333333","1 0 0.25 1 149.75 Infinity","-2 3 -1.25 -0.2 5.850000000000001 -0.16666666666666666","3.5 -2.5 1.5 0.16666666666666666 51.41666666666667 0.2","1e+300 -1e+300 5e+299 5e-301 31.25 5e-301","-1e+300 1e+300 -5e+299 -5e-301 31.75 -5e-301","0.5 0.5 0 Infinity Infinity -1","9007199254740992 -9007199254740992 4503599627370496 5.551115123125783e-17 32.75000000000001 5.551115123125783e-17","Infinity -Infinity Infinity 0 33.25 0","-Infinity Infinity -Infinity -0 33.75 0","NaN NaN NaN NaN NaN NaN","-2.5 -2.5 -0 -Infinity Infinity 5","-2.5 -2.5 0 Infinity -Infinity 5","-1.5 -3.5 -2.5 -2.5 109.25 -5","-3.5 -1.5 2.5 2.5 -35.25 1.6666666666666667","-2 -3 -1.25 -5 186.25 -Infinity","-5 0 6.25 1 8.75 0.8333333333333334","0.5 -5.5 -7.5 -0.8333333333333334 64.58333333333333 -1","1e+300 -1e+300 -2.5e+300 -2.5e-300 39.75 -2.5e-300","-1e+300 1e+300 2.5e+300 2.5e-300 40.25 2.5e-300","-2.5 -2.5 -1e-323 -Infinity Infinity 5","9007199254740990 -9007199254740994 -22517998136852480 -2.7755575615628914e-16 41.25000000000001 -2.7755575615628914e-16","Infinity -Infinity -Infinity -0 41.75 -0","-Infinity Infinity Infinity 0 42.25 0","NaN NaN NaN NaN NaN NaN","3 3 0 Infinity Infinity -6","3 3 -0 -Infinity -Infinity -6","4 2 3 3 127.5 6","2 4 -3 -3 -45 -2","3.5 2.5 1.5 6 218.5 Infinity","0.5 5.5 -7.5 -1.2 7.399999999999999 -1","6 0 9 1 73.5 1.2","1e+300 -1e+300 3e+300 2.9999999999999996e-300 44 2.9999999999999996e-300","-1e+300 1e+300 -3e+300 -2.9999999999999996e-300 44.5 -2.9999999999999996e-300","3 3 1.5e-323 Infinity Infinity -6","9007199254740996 -9007199254740989 27021597764222976 3.3306690738754696e-16 45.50000000000001 3.3306690738754696e-16","Infinity -Infinity Infinity 0 46 0","-Infinity Infinity -Infinity -0 46.5 0","NaN NaN NaN NaN NaN NaN","1e+300 1e+300 0 Infinity Infinity -2e+300","1e+300 1e+300 -0 -Infinity -Infinity -2e+300","1e+300 1e+300 1e+300 1e+300 -5e+299 2e+300","1e+300 1e+300 -1e+300 -1e+300 -5e+299 -6.666666666666667e+299","1e+300 1e+300 5e+299 2e+300 -5e+299 Infinity","1e+300 1e+300 -2.5e+300 -4e+299 -5e+299 -3.3333333333333335e+299","1e+300 1e+300 3e+300 3.3333333333333335e+299 -5e+299 4e+299","2e+300 0 Infinity 1 -5e+299 1","0 2e+300 -Infinity -1 -5e+299 -1","1e+300 1e+300 4.940656458412466e-24 Infinity Infinity -2e+300","1e+300 1e+300 Infinity 1.1102230246251566e+284 -5e+299 1.1102230246251566e+284","Infinity -Infinity Infinity 0 -5e+299 0","-Infinity Infinity -Infinity -0 -5e+299 0","NaN NaN NaN NaN NaN NaN","-1e+300 -1e+300 -0 -Infinity Infinity 2e+300","-1e+300 -1e+300 0 Infinity -Infinity 2e+300","-1e+300 -1e+300 -1e+300 -1e+300 5e+299 -2e+300","-1e+300 -1e+300 1e+300 1e+300 5e+299 6.666666666666667e+299","-1e+300 -1e+300 -5e+299 -2e+300 5e+299 -Infinity","-1e+300 -1e+300 2.5e+300 4e+299 5e+299 3.3333333333333335e+299","-1e+300 -1e+300 -3e+300 -3.3333333333333335e+299 5e+299 -4e+299","0 -2e+300 -Infinity -1 5e+299 -1","-2e+300 0 Infinity 1 5e+299 1","-1e+300 -1e+300 -4.940656458412466e-24 -Infinity Infinity 2e+300","-1e+300 -1e+300 -Infinity -1.1102230246251566e+284 5e+299 -1.1102230246251566e+284","Infinity -Infinity -Infinity -0 5e+299 -0","-Infinity Infinity Infinity 0 5e+299 0","NaN NaN NaN NaN NaN NaN","5e-324 5e-324 0 Infinity Infinity -1e-323","5e-324 5e-324 -0 -Infinity -Infinity -1e-323","1 -1 5e-324 5e-324 192 1e-323","-1 1 -5e-324 -5e-324 -64.5 -5e-324","0.5 -0.5 0 1e-323 325 Infinity","-2.5 2.5 -1e-323 -0 13.100000000000001 0","3 -3 1.5e-323 0 110 0","1e+300 -1e+300 4.940656458412466e-24 0 66.5 0","-1e+300 1e+300 -4.940656458412466e-24 -0 67 0","1e-323 0 0 1 Infinity -1e-323","9007199254740992 -9007199254740992 4.450147717014403e-308 0 68.00000000000001 0","Infinity -Infinity Infinity 0 68.5 0","-Infinity Infinity -Infinity -0 69 0","NaN NaN NaN NaN NaN NaN","9007199254740992 9007199254740992 0 Infinity Infinity -18014398509481984","9007199254740992 9007199254740992 -0 -Infinity -Infinity -18014398509481984","9007199254740992 9007199254740991 9007199254740992 9007199254740992 -4503599627370283 18014398509481984","9007199254740991 9007199254740992 -9007199254740992 -9007199254740992 -4503599627370568 -6004799503160661","9007199254740992 9007199254740992 4503599627370496 18014398509481984 -4503599627370136 Infinity","9007199254740990 9007199254740994 -22517998136852480 -3602879701896397 -4503599627370481.5 -3002399751580330.5","9007199254740996 9007199254740989 27021597764222976 3002399751580330.5 -4503599627370374.5 3602879701896397","1e+300 -1e+300 Infinity 9.007199254740992e-285 -4503599627370422.5 9.007199254740992e-285","-1e+300 1e+300 -Infinity -9.007199254740992e-285 -4503599627370422 -9.007199254740992e-285","9007199254740992 9007199254740992 4.450147717014403e-308 Infinity Infinity -18014398509481984","18014398509481984 0 8.112963841460668e+31 1 -4503599627370421 1","Infinity -Infinity Infinity 0 -4503599627370420.5 0","-Infinity Infinity -Infinity -0 -4503599627370420 0","NaN NaN NaN NaN NaN NaN","Infinity Infinity NaN Infinity NaN NaN","Infinity Infinity NaN -Infinity -Infinity NaN","Infinity Infinity Infinity Infinity -Infinity NaN","Infinity Infinity -Infinity -Infinity -Infinity NaN","Infinity Infinity Infinity Infinity -Infinity NaN","Infinity Infinity -Infinity -Infinity -Infinity NaN","Infinity Infinity Infinity Infinity -Infinity NaN","Infinity Infinity Infinity Infinity -Infinity NaN","Infinity Infinity -Infinity -Infinity -Infinity NaN","Infinity Infinity Infinity Infinity NaN NaN","Infinity Infinity Infinity Infinity -Infinity NaN","Infinity NaN Infinity NaN -Infinity NaN","NaN Infinity -Infinity NaN -Infinity NaN","NaN NaN NaN NaN NaN NaN","-Infinity -Infinity NaN -Infinity Infinity NaN","-Infinity -Infinity NaN Infinity NaN NaN","-Infinity -Infinity -Infinity -Infinity Infinity NaN","-Infinity -Infinity Infinity Infinity Infinity NaN","-Infinity -Infinity -Infinity -Infinity Infinity NaN","-Infinity -Infinity Infinity Infinity Infinity NaN","-Infinity -Infinity -Infinity -Infinity Infinity NaN","-Infinity -Infinity -Infinity -Infinity Infinity NaN","-Infinity -Infinity Infinity Infinity Infinity NaN","-Infinity -Infinity -Infinity -Infinity Infinity NaN","-Infinity -Infinity -Infinity -Infinity Infinity NaN","NaN -Infinity -Infinity NaN Infinity NaN","-Infinity NaN Infinity NaN Infinity NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN","NaN NaN NaN NaN NaN NaN"],["1.5,2,2.5,3","0,1.25,1.75,0","1.5,2,2.5,3","1.5,2,NaN,NaN","1.5,2,0,0","0,2,2.5,0","0.51,11,1.51,21","1.5,2,2.5,3","0,0,-1e+300,-1e+300","0,0,0,0","1.5,1,1.5,3","9","-1","NaN","string:9","0","0.75","string:0.5|0.25"],[[0,2,1],[1,2,0],[0,1,1,2],[0,1,2],[0,1,2],[3,4,0,6,7,1,2,5],[1,4,5,0,7,8,2,3,6],[0,1,6,2,3,8,7,4,5],[]]]"###
    );
}

/// 20,000 rounds: a key sort (both ways) of a shuffled, sometimes duplicated index list whose keys
/// hold NaN, signed zeros, infinities and ties (up to 2,000 items, so V8's merges and gallops run on
/// an inconsistent comparator), the float arithmetic over random pairs, and the proven / general
/// counted loops over arrays some of whose elements are strings. Node's digest.
#[test]
fn j89_3_numeric_fuzz_like_node() {
    let dir = scratch("j89-3-fuzz");
    probe_package(&dir);
    let out = run_python(
        &format!(
            "{PRINT}\nimport sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import _ts2py_runtime as rt, m\nprint(node_json(rt, m.fuzz(20000)))\n"
        ),
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(
        out.trim_end(),
        r###"["60000","48109af1957ba4679ae56e12bd2350ba5f9f5f5c6e3d8c3ef08ae39b9a86f024"]"###
    );
}

/// `_js_doubles`, the guard of a proven copy: a float, or an int a double holds exactly; never a
/// bool, an int past 2**53, a subclass, or anything else; only over the range asked.
#[test]
fn j89_3_the_element_guard_admits_only_proven_numbers() {
    let dir = scratch("j89-3-guard");
    package(&dir, &[]);
    let out = run_python(
        r#"import sys
sys.path.insert(0, sys.argv[1])
from pkg._ts2py_runtime import _js_doubles
class F(float): pass
cases = [
    ([], 0, 0), ([1, 2.5, -0.0, float("nan"), float("inf")], 0, 5), ([2**53, -(2**53)], 0, 2),
    ([2**53 + 1], 0, 1), ([True], 0, 1), ([F(1.0)], 0, 1), (["1"], 0, 1), ([None], 0, 1),
    ([1.5, "x", 2.5], 2, 3), ([1.5, "x", 2.5], 0, 3), ([1, 2**60, 3.5], 0, 2), ([1, 2**60, 3.5], 0, 3),
]
print([_js_doubles(*c) for c in cases])
"#,
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(
        out.trim_end(),
        "[True, True, True, False, False, False, False, False, True, False, False, False]"
    );
}

#[test]
fn j89_3_a_float64array_that_escapes_is_refused() {
    let used = "a Float64Array used as a value";
    refused(
        "export function f(): unknown {\n  const t = new Float64Array(2);\n  return t;\n}\n",
        used,
    );
    refused(
        "function g(x: unknown): void {}\nexport function f(): void {\n  const t = new Float64Array(2);\n  g(t);\n}\n",
        used,
    );
    refused(
        "export function f(): unknown {\n  const t = new Float64Array(2);\n  const u = t;\n  return u[0];\n}\n",
        used,
    );
    refused(
        "export function f(): unknown {\n  const t = new Float64Array(2);\n  for (const x of t) return x;\n  return 0;\n}\n",
        used,
    );
    refused(
        "export function f(): unknown {\n  const t = new Float64Array(2);\n  return t.map((x) => x);\n}\n",
        used,
    );
    refused(
        "export function f(): unknown {\n  const t = new Float64Array(2);\n  return t.byteLength;\n}\n",
        "a Float64Array's .byteLength",
    );
    refused(
        "export function f(): void {\n  let t = new Float64Array(2);\n  t[0] = 1;\n}\n",
        "a Float64Array bound by anything but a const",
    );
    refused(
        "export function f(): unknown {\n  return [new Float64Array(2)];\n}\n",
        "new Float64Array anywhere but a const's initializer",
    );
    refused(
        "export function f(): void {\n  const t = new Float64Array(2);\n  t[0] += 1;\n}\n",
        "compound assignment to a Float64Array element",
    );
}

/// A comparator that is not exactly `t[b] - t[a] || a - b` (or `t[a] - t[b] || a - b`) over a
/// Float64Array is the general `.sort`.
#[test]
fn j89_3_only_the_exact_key_comparator_is_a_key_sort() {
    let head = "export function f(xs: number[], ks: number[]): number[] {\n  const t = new Float64Array(3);\n  return xs.sort(";
    for cmp in [
        "(a, b) => t[b]! - t[a]!",
        "(a, b) => t[b]! - t[a]! || b - a",
        "(a, b) => t[b]! * t[a]! || a - b",
        "(a, b) => t[b]! - t[b]! || a - b",
        "(a, b) => ks[b]! - ks[a]! || a - b",
        "(a, b) => t[b]! - t[a]! && a - b",
        "(a, b) => (t[b]! - t[a]!) * 2 || a - b",
    ] {
        let code = code_of(&format!("{head}{cmp});\n}}\n"));
        assert!(
            code.contains("_js_m_sort(") && !code.contains("_js_sort_by_f64("),
            "{cmp}:\n{code}"
        );
    }
    let code = code_of(&format!(
        "{head}(a, b) => (t[a]! - t[b]!) || (a - b));\n}}\n"
    ));
    assert!(code.contains("_js_sort_by_f64(xs, t, False, "), "{code}");
}

/// A counted loop gets no proven copy when anything in its body could change what the guard
/// checked, or when it is not `for (let i = a; i < b; i += 1)` indexing by `i` itself.
#[test]
fn j89_3_a_loop_that_could_break_its_guard_has_no_proven_copy() {
    let open = "function g(): void {}\nexport function f(xs: number[], ys: number[], n: number): number {\n  const t = new Float64Array(n);\n  const out: number[] = [];\n  let s = 0;\n";
    for body in [
        "for (let i = 0; i < n; i += 1) { t[i] = xs[i]!; g(); }",
        "for (let i = 0; i < n; i += 1) { t[i] = xs[i]!; ys[i] = 1; }",
        "for (let i = 0; i < n; i += 1) { t[i] = xs[i]!; xs.push(1); }",
        "for (let i = 0; i < n; i += 1) { t[i] = xs[i + 1]!; }",
        "for (let i = 0; i < n; i += 2) { t[i] = xs[i]!; }",
        "for (let i = 0; i <= n; i += 1) { t[i] = xs[i]!; }",
        "for (let i = 0; i < n; i += 1) { t[i] = xs[i]!; i = n; }",
        "for (let i = 0; i < n; i += 1) { t[i] = xs[i]!; n = 0; }",
        "for (let i = 0; i < n; i += 1) { for (let j = 0; j < n; j += 1) s = s + 1; }",
        "for (let i = 0; i < n; i += 1) { s = s + xs.length; }",
        "for (let i = 0; i < n; i += 1) { t[i] = `${xs[i]!}`.length; }",
    ] {
        let code = code_of(&format!("{open}  {body}\n  return s + out.length;\n}}\n"));
        assert!(!code.contains("range("), "{body}:\n{code}");
    }
    // The same loop with nothing that could break it: proven.
    let code = code_of(&format!(
        "{open}  for (let i = 0; i < n; i += 1) {{ t[i] = xs[i]! * 0.5; out.push(i); }}\n  return s + out.length;\n}}\n"
    ));
    assert!(code.contains("for i in range(i, n):"), "{code}");
}
