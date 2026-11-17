//! J89-2 (#316 G3 U1): the constructs `memory/usage.ts` needed and those J89-2 lowered for
//! `memory/retrieval.ts` (generated since J89-3, `g3_numeric.rs`) (`x++` /
//! `--x` as a loop update, `.charCodeAt`, `.match`, `.toFixed`, a module-level `let` assigned by a
//! module function, an array element write, `buf.indexOf(byte)`, `in` on a Map or Set, a parameter
//! named as a Python builtin), the `node:crypto` hash, and the six #316 modules compiled together. Every expected value is what Node v26.13.0 printed for the
//! same TypeScript (`tests/fixtures/j89_g3_probe.ts`; the fuzz generator is spelled in both
//! languages, and Node's digests are the literals).

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

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .unwrap()
        .to_path_buf()
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

fn compile_package(sources: &[(&str, &str)]) -> Vec<ts2py::Compiled> {
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py_bantamkit::options()
    };
    ts2py::compile_modules(sources, &options)
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")))
}

/// `JSON.stringify(value)` with every code unit at or above 0x7F written `\uXXXX`.
const PRINT: &str = r#"
def node_json(m, value):
    out = m._js_json_stringify(value)
    return "".join(c if ord(c) < 0x7F else "\\u%04x" % ord(c) for c in m._js_code_units(out))
"#;

#[test]
fn g3_constructs_answer_like_node() {
    let source = include_str!("fixtures/j89_g3_probe.ts");
    let modules = compile_package(&[("j89_g3_probe.ts", source)]);
    let code = &modules[0].code;
    // The lowerings themselves.
    assert!(code.contains("COUNTER: _JsAny = 0\n"), "{code}");
    assert!(code.contains("    global COUNTER\n"), "{code}");
    assert!(code.contains("def named(type_, len_):"), "{code}");
    assert!(
        code.contains("i = _js_num(i + 1)") || code.contains("i = _js_inc(i)"),
        "{code}"
    );
    assert!(
        code.contains("_js_m_charCodeAt(")
            && code.contains("_js_m_match(")
            && code.contains("_js_m_toFixed(")
    );
    let dir = scratch("j89-probe");
    package(&dir, &modules);
    let out = run_python(
        &format!(
            "{PRINT}\nimport sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import _ts2py_runtime as rt, j89_g3_probe as m\nprint(node_json(rt, m.probe()))\n"
        ),
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(
        out.trim_end(),
        r###"[0,[2,2.5,2.5],"t:3",[0,1,2,3,2,1,[0,1,2,1]],["NaN",97,233,55357,56832,55296,122,"NaN",97,97,233,"NaN"],[["release","lessons","0","35","9"],null,["","xx","",""],null,["x1"],["a1","a","1"],null],["0.000000000","0","0.00","0","0.000000000","0","0.00","0","1.000000000","1","1.00","1","-1.000000000","-1","-1.00","-1","0.500000000","1","0.50","1","1.500000000","2","1.50","2","2.500000000","3","2.50","3","-2.500000000","-3","-2.50","-3","1.005000000","1","1.00","1","0.000976563","0","0.00","0","0.000000000","0","0.00","0","123.456000000","123","123.46","123","100000000000000000000.000000000","100000000000000000000","100000000000000000000.00","100000000000000000000","1e+21","1e+21","1e+21","1e+21","1.5e+21","1.5e+21","1.5e+21","1.5e+21","-1e+21","-1e+21","-1e+21","-1e+21","NaN","NaN","NaN","NaN","Infinity","Infinity","Infinity","Infinity","-Infinity","-Infinity","-Infinity","-Infinity","0.300000000","0","0.30","0","0.333333333","0","0.33","0","0.000000000","0","0.00","0","4.350000000","4","4.35","4","1.450000000","1","1.45","1","8.345000000","8","8.35","8","0.50000000000000000000","102"],["RangeError","RangeError"],[[9,2,3,4],[0,0.5,1,1.5]],[1,3,5,1,1,-1,1,4,"\u00c3\u00a9\n\u00f0\u009f\u0098\u0080\n\n",3,["a\u00e9","b"]],[false,true,true,true,false,true],["e3b0c44298fc1c14","3c48591d8d098a45","28e66175821bf0ad","dcb278505dc15deb"]]"###
    );
}

/// `toFixed` (`_js_m_toFixed`) over 40,000 seeded doubles: tiny to huge, dyadic ties, raw bit
/// patterns, both signs, 0..20 digits. The digest is Node's for the same generator
/// (`x.toFixed(f)`), so one differing answer reddens it.
const FUZZ: &str = r#"import hashlib, struct, sys
sys.path.insert(0, sys.argv[1])
from pkg._ts2py_runtime import _js_m_toFixed
seed = 0x89
M = (1 << 64) - 1
def nxt():
    global seed
    seed = (seed * 6364136223846793005 + 1442695040888963407) & M
    return seed
N = 40000
fixed = []
for i in range(N):
    r = nxt(); kind = r % 4
    if kind == 0:
        x = (nxt() >> 11) / 2**53 * 10.0 ** ((nxt() % 30) - 12)
    elif kind == 1:
        x = (nxt() % 100000) / 2 ** (nxt() % 40)
    elif kind == 2:
        x = struct.unpack(">d", nxt().to_bytes(8, "big"))[0]
        if x != x or x in (float("inf"), float("-inf")): x = 0.5
    else:
        x = (nxt() % 2000000) / 1024
    if nxt() % 3 == 0: x = -x
    f = nxt() % 21
    fixed.append(_js_m_toFixed(x, f))
h = lambda a: hashlib.sha256("\n".join(a).encode()).hexdigest()
print(N, h(fixed))
"#;

#[test]
fn g3_to_fixed_fuzz_like_node() {
    let dir = scratch("j89-fuzz");
    package(&dir, &[]);
    let out = run_python(FUZZ, &[&dir]);
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(
        out.trim_end(),
        "40000 b509ff8529e26285b6926b67db67e2cf2a829ea25213e60a1b353a8bb96cd82f"
    );
}

/// The eight #316 modules in one ts2py call (G1, G2, G3's usage ledger, retrieval and, since J89-4b,
/// the store): usage imports the compiled log segment, the event log the compiled store's
/// `.bantamkit` helpers, and pysem / pyfs / node:crypto come through the seam.
#[test]
fn g3_modules_compile_together() {
    let root = repo_root();
    let paths = [
        "runtime-ts/src/pricing.ts",
        "runtime-ts/src/jobbudget.ts",
        "runtime-ts/src/storage/logsegment.ts",
        "runtime-ts/src/eventlog.ts",
        "runtime-ts/src/tokenledger.ts",
        "runtime-ts/src/memory/usage.ts",
        "runtime-ts/src/memory/retrieval.ts",
        "runtime-ts/src/memory/store.ts",
        // J90-2 (#316 G4): the store imports the compiled lock and hot index; J90-3 the cold index.
        "runtime-ts/src/storage/lock.ts",
        "runtime-ts/src/storage/hotindex.ts",
        "runtime-ts/src/storage/coldindex.ts",
    ];
    let sources: Vec<String> = paths
        .iter()
        .map(|p| std::fs::read_to_string(root.join(p)).unwrap())
        .collect();
    let pairs: Vec<(&str, &str)> = paths
        .iter()
        .zip(&sources)
        .map(|(p, s)| (*p, s.as_str()))
        .collect();
    let modules = compile_package(&pairs);
    let code = |stem: &str| -> &str { &modules.iter().find(|m| m.py_module == stem).unwrap().code };
    assert!(code("usage").contains("from .logsegment import ROTATE_BYTES, LogSegment\n"));
    // J90-P2: `createHash(..).update(.., 'utf8').digest('hex')` is one adapter call.
    assert!(code("usage").contains("hash_hex(\"sha256\", "));
    assert!(code("usage").contains("py_pow(0.5, "));
    for module in &modules {
        let committed = root
            .join("runtime-py/src/bantamkit/_generated")
            .join(format!("{}.py", module.py_module));
        assert_eq!(
            std::fs::read_to_string(&committed).unwrap(),
            module.code,
            "{} is not what this compile writes",
            committed.display()
        );
    }
}

/// J89-2: another compiled module may not import a module-level `let`: Python's
/// `from .m import X` would copy the live binding once.
#[test]
fn g3_a_module_let_is_not_importable() {
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py_bantamkit::options()
    };
    let lines = match ts2py::compile_modules(
        &[
            (
                "m.ts",
                "export let x = 1;\nexport function set(v: number): void {\n  x = v;\n}\n",
            ),
            (
                "n.ts",
                "import { x } from './m.js';\nexport function get(): number {\n  return x;\n}\n",
            ),
        ],
        &options,
    ) {
        Ok(_) => panic!("expected a refusal"),
        Err(lines) => lines,
    };
    assert!(
        lines.iter().any(|l| l == "n.ts:1:10: unsupported import of x from ./m.js, which that module does not export: x"),
        "{}",
        lines.join("\n")
    );
}

/// J89-2's numeric fast paths (`_js_add` / `_js_mul` / `_js_div` / `_js_mod` on floats and exact
/// ints, `_js_floor`, `_js_number` of a digit string, two-operand `_js_max` / `_js_min`,
/// `_js_typeof`, `_js_double_out`) against the general path they shortcut. A subclass of
/// `float` / `int` / `str` / `dict` skips every fast path (each tests `type(x) is ...`) and is the
/// same JS value, so the helper called on it IS the general path; the two answers must be the same
/// value, the same Python type and the same sign of a zero, over 40,000 random operand pairs (an
/// int past 2**53 is passed as it is: both calls take the general path for it).
const FAST_PATHS: &str = r#"
import math, random, sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_runtime as rt

class F(float): pass
class I(int): pass
class S(str): pass
class D(dict): pass

def slow(v):
    if type(v) is float: return F(v)
    # An int past 2**53 takes the general path either way; `_js_num` rounds only a plain `int`, so
    # wrapping one would not be the general path's own answer.
    if type(v) is int and -(2**53) <= v <= 2**53: return I(v)
    if type(v) is str: return S(v)
    if type(v) is dict: return D(v)
    return v

def key(v):
    if isinstance(v, float):
        return ("float", "nan" if v != v else repr(float(v)), math.copysign(1.0, v) if v == 0 else 0)
    if isinstance(v, bool) or v is None or v is rt._JS_UNDEFINED:
        return (repr(v),)
    if isinstance(v, int):
        return ("int", int(v))
    return (type(v).__name__, repr(v))

def answer(f, *args):
    try:
        return key(f(*args))
    except Exception as e:
        return ("raised", type(e).__name__)

rnd = random.Random(892)
def value():
    k = rnd.randrange(12)
    if k == 0: return rnd.randint(-50, 50)
    if k == 1: return rnd.choice([0, 1, -1, 2**53, -(2**53), 2**53 + 1, 2**60, 400, 4, 100])
    if k == 2: return rnd.uniform(-1e3, 1e3)
    if k == 3: return float(rnd.randint(-40, 40))
    if k == 4: return rnd.choice([0.0, -0.0, math.inf, -math.inf, math.nan, 0.5, -0.5, 1e300, 5e-324, 2.0**53, 2.0**54])
    if k == 5: return rnd.choice(["12", "0", "007", "123456789012345", "1234567890123456", "1e3", " 4", "", "x", "-3"])
    if k == 6: return rnd.choice([True, False, None, rt._JS_UNDEFINED])
    if k == 7: return rnd.uniform(-1, 1) * 10.0 ** rnd.randint(-20, 20)
    if k == 8: return rnd.choice([{}, {"a": 1}])
    return rnd.randint(-10**6, 10**6)

calls = diffs = 0
shown = []
for _ in range(40000):
    a, b = value(), value()
    for name, f, args, sargs in [
        ("add", rt._js_add, (a, b), (slow(a), slow(b))),
        ("mul", rt._js_mul, (a, b), (slow(a), slow(b))),
        ("div", rt._js_div, (a, b), (slow(a), slow(b))),
        ("mod", rt._js_mod, (a, b), (slow(a), slow(b))),
        ("floor", rt._js_floor, (a,), (slow(a),)),
        ("number", rt._js_number, (a,), (slow(a),)),
        ("max", rt._js_max, (a, b), (slow(a), slow(b))),
        ("min", rt._js_min, (a, b), (slow(a), slow(b))),
        ("typeof", rt._js_typeof, (a,), (slow(a),)),
    ]:
        calls += 1
        if answer(f, *args) != answer(f, *sargs):
            diffs += 1
            if len(shown) < 5:
                shown.append((name, args, answer(f, *args), answer(f, *sargs)))
    if isinstance(a, float):
        calls += 1
        if key(rt._js_double_out(a)) != key(rt._js_double_out(F(a))):
            diffs += 1
print("calls", calls, "diffs", diffs, shown)
"#;

#[test]
fn g3_numeric_fast_paths_answer_as_the_general_path() {
    let dir = scratch("j89-fast");
    package(&dir, &[]);
    let out = run_python(FAST_PATHS, &[&dir]);
    std::fs::remove_dir_all(&dir).unwrap();
    let out = out.trim_end();
    assert!(
        out.starts_with("calls ") && out.ends_with(" diffs 0 []"),
        "{out}"
    );
}
