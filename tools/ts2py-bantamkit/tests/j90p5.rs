//! J90-P5 (#316 G4): the per-call shape guard of `dumpJsValue`'s `_lifted` (adapters.py). A list,
//! a plain dict or a plain Map whose every value is its own lifted form (strings, booleans, nulls,
//! safe ints, lists of those, dicts of those whose keys are strings with no all-digit one) is handed
//! to `json.dumps` unconverted, checked once per call at C speed; any other value takes the
//! value-by-value path, which is what Node's `fromJs` reads.
//!
//! Pinned ANSWERING as Node does: `probe()` and `fuzz(3000)` of `tests/fixtures/j90p5_probe.ts`, both
//! what Node v26.13.0 printed for that file with `--experimental-strip-types` beside
//! `runtime-ts/dist/pyjson.js`: canonical-index keys of a plain object ('1', '0', '10',
//! '4294967294') ahead of the others, '01' / '-1' / '4294967295' / '٣' not, an own `__proto__`
//! key, a Map's insertion order (a number key and its string colliding), a Map made from an
//! object's entries, `-0`, `2^53` and past it, NaN, `1e21`, undefined, and the `avgdl` float key.
//! Pinned TAKEN and equal to the general path: `fast_path_is_taken_and_equals_the_general_path`
//! runs the adapter's `_lifted` against the value-by-value algorithm it shortcuts (the J90-P4
//! function, written out in the test) over 20,000 seeded Python values, and checks the fast path
//! hands back the very object for the shapes it is for.

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

fn options() -> ts2py::Options {
    ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py_bantamkit::options()
    }
}

/// What Node v26.13.0 printed for `probe()`, one dump per line.
const NODE_PROBE: &[&str] = &[
    r#"{"0": {"2": 2, "z": 1}, "1": 2, "b": 1, "a": [3, "x"]}"#,
    r#"{"0": {"2": 2, "z": 1}, "1": 2, "b": 1, "a": [3, "x"]}"#,
    r#"{"b": [1, 2], "a": ["x", "y"], "1": [9007199254740992.0]}"#,
    r#"{"k": [1, "mixed"], "j": [[1, 2], [3]]}"#,
    r#"{"1": "string one", "true": "t"}"#,
    r#"[[1, 2], [3, 9007199254740994.0], ["a", null]]"#,
    r#"{"d": {"7": 2, "x": 1}, "e": {"y": [-0.0]}}"#,
    r#"{"__proto__": {"a": 1}, "q": [true, false, null]}"#,
    r#"{"n": {"b": 1, "a": {"c": [1, 2]}}, "m": {"\u0663": 0.5}}"#,
];
/// What Node v26.13.0 printed for `fuzz(3000)`.
const NODE_FUZZ: &str = "712c3bd5207c57e8";

#[test]
fn dump_js_value_answers_like_node() {
    let source = include_str!("fixtures/j90p5_probe.ts");
    // Compiled where it would sit in runtime-ts/src, so `./pyjson.js` is the `dumpJsValue` adapter.
    let modules = ts2py::compile_modules(&[("runtime-ts/src/j90p5_probe.ts", source)], &options())
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    let dir = scratch("j90p5-probe");
    package(&dir, &modules);
    let out = run_python(
        "import sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import j90p5_probe as m\nfor line in m.probe():\n    print(line)\nprint(m.fuzz(3000))\n",
        &[dir.to_str().unwrap()],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let lines: Vec<&str> = out.lines().collect();
    assert_eq!(&lines[..NODE_PROBE.len()], NODE_PROBE);
    assert_eq!(lines[NODE_PROBE.len()], NODE_FUZZ);
}

/// The value-by-value `_lifted` (as J90-P4 shipped it) and a seeded generator of the values the
/// generated modules hand `dumpJsValue`: Maps (plain, waiting to be settled, with keys that are not
/// their own tags), plain dicts with index-like keys, lists of rows, every scalar kind.
const REFERENCE: &str = r#"
import math, random, sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_adapters as A
from pkg import _ts2py_runtime as R

SAFE = 2**53 - 1
SAME = frozenset({str, bool, type(None)})

def general(value):
    kind = type(value)
    if kind in SAME:
        return value
    if kind is int:
        return value if -SAFE <= value <= SAFE else float(value)
    if kind is float:
        if value.is_integer() and -SAFE <= value <= SAFE and not (value == 0 and math.copysign(1.0, value) < 0):
            return int(value)
        return value
    if kind is list:
        return [general(item) for item in value]
    if kind is dict:
        return {key: general(value[key]) for key in R._js_own_keys(value)}
    if value is R._JS_UNDEFINED:
        return None
    if isinstance(value, R._JsMap):
        return {R._js_str(key): general(item) for key, item in value}
    if kind is R._JsBigInt:
        return value.value
    raise TypeError(kind)

KEYS = ["b", "a", "1", "0", "01", "10", "-1", "4294967294", "4294967295", "٣", "", "__proto__", "x7", "é"]
rng = random.Random(int(sys.argv[2]))

def scalar():
    return rng.choice([
        "s", "☃", True, False, None, rng.randrange(-1000, 1000), 0, -0.0, 0.5, 1.0, 2.0**53,
        2**53, 2**53 - 1, -(2**53) + 1, 2**53 + 1, 2**60, 10**30, float("nan"), float("inf"), 1e21,
        R._JS_UNDEFINED, R._JsBigInt(2**70),
    ])

def value(depth):
    if depth <= 0:
        return scalar()
    k = rng.randrange(9)
    if k == 0:
        return scalar()
    if k == 1:
        return [rng.choice(["p", "q"]) for _ in range(rng.randrange(5))]
    if k == 2:
        return [rng.randrange(-5, 5) if rng.randrange(20) else rng.choice([2**53, 2**53 + 2, True, 1.5]) for _ in range(rng.randrange(5))]
    if k == 3:
        return [value(depth - 1) for _ in range(rng.randrange(4))]
    if k in (4, 5):
        return {rng.choice(KEYS): value(depth - 1) for _ in range(rng.randrange(5))}
    m = R._JsMap()
    for _ in range(rng.randrange(5)):
        r = rng.randrange(12)
        key = rng.randrange(3) if r == 0 else True if r == 1 else 2**60 if r == 2 else rng.choice(KEYS)
        m.set(key, value(depth - 1))
    if k == 7:
        m = R._js_map_entries({rng.choice(KEYS): value(depth - 1) for _ in range(rng.randrange(5))})
    return m

def same(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        return (a != a and b != b) or (a == b and math.copysign(1, a) == math.copysign(1, b))
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    return a == b

bad = 0
for i in range(int(sys.argv[3])):
    v = value(1 + i % 4)
    try:
        want = general(v)
    except TypeError:
        continue
    got = A._lifted(v)
    if not same(got, want):
        bad += 1
        if bad < 4:
            print("DIFF", repr(v)[:300], repr(got)[:300], repr(want)[:300])
print("bad", bad)

# TAKEN: the shapes the guard is for come back as the very object (a list, a dict), or as the
# Map's own entries dict.
rows = [[1, 2, 3], ["a", "b"], [], [True, None]]
assert A._lifted(rows) is rows
docs = {"a": {"name": "a", "keywords": ["x"], "size": 3}, "b": {"name": "b", "keywords": [], "size": 1}}
assert A._lifted(docs) is docs
m = R._JsMap()
m.set("t", [1, 2, 3])
m.set("u", ["n"])
assert A._lifted(m) == m._entries and A._lifted(m) is not m._entries
print("taken")

# `hash_hex` / `Hash.update` of any `str`: the bytes the J90-P4 path hashed (`_os_text`, then
# UTF-8 with surrogateescape), for strings of every kind: ASCII, Latin, Thai, astral, and lone
# surrogates (the high and low halves, and the surrogateescape bytes U+DC80..U+DCFF).
import hashlib
CH = ["a", "0", " ", "\u00e9", "\u0e01", "\U0001f600", "\ud800", "\udbff", "\udc80", "\udcff", "\udfff", "\u2028"]
hdiff = 0
for _ in range(int(sys.argv[3])):
    t = "".join(rng.choice(CH) for _ in range(rng.randrange(12)))
    for alg in ("sha256", "sha1"):
        want = getattr(hashlib, alg)(A._os_text(t).encode("utf-8", "surrogateescape")).hexdigest()
        if A.hash_hex(alg, t) != want or A.create_hash(alg).update(t, "utf8").digest("hex") != want:
            hdiff += 1
    # `_os_text` (and `_node_path`, through it): each lone surrogate as `_os_char` gives it.
    os_want = "".join(A._os_char(c) if 0xD800 <= ord(c) <= 0xDFFF else c for c in t)
    if A._os_text(t) != os_want or A._node_path(t, "probe") != os_want:
        hdiff += 1
print("hash diffs", hdiff)
"#;

#[test]
fn fast_path_is_taken_and_equals_the_general_path() {
    let dir = scratch("j90p5-lift");
    package(&dir, &[]);
    let out = run_python(REFERENCE, &[dir.to_str().unwrap(), "90905", "20000"]);
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(out.contains("bad 0\n"), "{out}");
    assert!(out.contains("taken\n"), "{out}");
    assert!(out.contains("hash diffs 0\n"), "{out}");
}
