//! J90-PF (#316 G4): the pure build's speed rules (RULES.md, *J90-PF rules*).
//!
//! Pinned ANSWERING as Node does: `probe()` and `fuzz(3000)` of `tests/fixtures/j90pf_probe.ts`,
//! both what Node v26.13.0 printed for that file (types stripped, beside `runtime-ts/dist`), with
//! every rule the probe exercises present in the compiled text.
//! Pinned EQUAL TO THE HELPER on values JS code cannot build: each expansion is called with Python
//! values (ints past 2^53, bools, BigInts, `-0.0`, NaN, lone surrogates, a Map with kept keys, a Map
//! waiting to be settled, a Set, a subclass, objects with `_entries` / `_items`, dicts, `None`) and
//! held to the helper's answer, value and type, or the same exception; the fast arms TAKEN with the
//! helpers patched to raise.
//! Pinned EQUAL TO THE GENERAL PATH: each runtime fast path J90-PF added over seeded inputs, and the
//! three stat adapters against `BigIntStats` over real files, a directory, symlinks and missing
//! paths, and the `parseNative` adapter's `front` against the text it was split from.

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
    let source = include_str!("fixtures/j90pf_probe.ts");
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py_bantamkit::options()
    };
    ts2py::compile_modules(&[("runtime-ts/src/j90pf_probe.ts", source)], &options)
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")))
}

/// What Node v26.13.0 printed for `probe()`: 58 lines, as sha256 of their text, each line ended by
/// a newline (first 16 hex digits); and for `fuzz(3000)`.
const NODE_PROBE: &str = "ffd4a1ed41ff4cae";
const NODE_FUZZ: &str = "4b3efff7cb5432a4";

#[test]
fn rules_answer_like_node() {
    let modules = compiled();
    let code = &modules[0].code;
    // Each rule is what the probe exercised.
    for form in [
        // `m.get(k)` / `m.has(k)` with a key that is its own tag: a string or a safe int.
        "._entries.get(k, _JS_UNDEFINED) if type(m) is _JsMap and (type(k) is str or type(k) is int and -9007199254740992 <= k <= 9007199254740992) else _js_m_get(m, k))",
        "(k in m._entries if type(m) is _JsMap and (type(k) is str or type(k) is int and -9007199254740992 <= k <= 9007199254740992) else k in m._items if type(m) is _JsSet and (type(k) is str or type(k) is int and -9007199254740992 <= k <= 9007199254740992) else _js_m_has(m, k))",
        // `m.set(k, v)` as a statement, of a name and of a list display.
        "if type(m) is _JsMap and (type(k) is str or type(k) is int and -9007199254740992 <= k <= 9007199254740992) and m._keys is None:\n            m._entries[k] = v\n        else:\n            _js_m_set(m, k, v)",
        "by_shard._entries[i] = [t]",
        // `xs.push(x)` as a statement and as a value; several items on a proven list.
        "if type(xs) is list:\n            xs.append(x)\n        else:\n            _js_m_push(xs, x)",
        "(xs.append(x) or len(xs) if type(xs) is list else _js_m_push(xs, x))",
        "several.extend((i, _js_neg(0), \"q\",))",
        // `xs[k] = v` and reads by a counted and a literal index.
        "if type(xs) is list and type(k) is int and 0 <= k < len(xs):\n            xs[k] = v\n        else:\n            _js_put(xs, k, v)",
        "(xs[k] if type(xs) is list and type(k) is int and 0 <= k < len(xs) else _js_get(xs, k))",
        "(xs[0] if type(xs) is list and 0 < len(xs) else _js_get(xs, 0))",
        // `===` / `!==` of two safe ints.
        "(a == b if type(a) is type(b) is str or type(a) is type(b) is int and -9007199254740992 <= a <= 9007199254740992 and -9007199254740992 <= b <= 9007199254740992 else _js_strict_eq(a, b))",
        "(a != b if type(a) is type(b) is str or type(a) is type(b) is int and -9007199254740992 <= a <= 9007199254740992 and -9007199254740992 <= b <= 9007199254740992 else not _js_strict_eq(a, b))",
        // The sorts and the ASCII-literal string tests.
        "_js_sort_unique(xs, cmp_codepoint)",
        "_js_sort_num(xs, False, ",
        "(s.endswith(\".md\") if type(s) is str else _js_m_endsWith(s, \".md\"))",
        "(s.startswith(\"a\") if type(s) is str else _js_m_startsWith(s, \"a\"))",
    ] {
        assert!(code.contains(form), "missing {form}\nin:\n{code}");
    }
    // A needle that is not ASCII is a code-unit test: the helper, never `endswith`.
    assert!(code.contains("_js_m_endsWith(") && !code.contains(".endswith(\"\\ude00\")"));
    let dir = scratch("j90pf-probe");
    package(&dir, &modules);
    let out = run_python(
        "import hashlib, sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import j90pf_probe as m\ntext = ''.join(line + '\\n' for line in m.probe())\nprint(text.count('\\n'), hashlib.sha256(text.encode('utf-8', 'surrogatepass')).hexdigest()[:16])\nprint(m.fuzz(3000))\n",
        &[dir.to_str().unwrap()],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let lines: Vec<&str> = out.lines().collect();
    assert_eq!(lines[0], format!("58 {NODE_PROBE}"));
    assert_eq!(lines[1], NODE_FUZZ);
}

const REFERENCE: &str = r#"
import copy, itertools, math, sys
sys.path.insert(0, sys.argv[1])
from pkg import j90pf_probe as P
from pkg import _ts2py_runtime as R
from pkg import _ts2py_adapters as A

class NotAMap:
    _keys = None
    def __init__(self):
        self._entries = {"a": "not a Map"}
        self._items = {"a": "not a Set"}

class SubMap(R._JsMap):
    pass

class SubList(list):
    pass

POOL = [
    "a", "1", "", "\U0001F600", "\ud83d", "x.md", "a.md", "\U0001F600.md", "\ud800.md",
    0, 1, -1, 7, 15, -0.0, 0.0, 1.0, 0.5, float("nan"), float("inf"),
    True, False, None, R._JS_UNDEFINED, R._JsBigInt(5), R._JsBigInt(2**70),
    2**52, 2**53 - 1, 2**53, 2**53 + 1, -(2**53), -(2**53) - 1, 2**60, 10**30, 2.0**53, 1e21,
]

def norm(value, seen=None):
    if isinstance(value, float) and value != value:
        return ("nan",)
    if isinstance(value, float):
        return (float, value, math.copysign(1.0, value))
    if isinstance(value, (list, tuple)):
        return (type(value), [norm(v) for v in value])
    if isinstance(value, R._JsMap):
        return (type(value), [norm(e) for e in list(value)], sorted(map(repr, (value._keys or {}).items())) if isinstance(value._keys, dict) else repr(value._keys is None))
    if isinstance(value, R._JsSet):
        return (type(value), [norm(v) for v in list(value)])
    if isinstance(value, dict):
        return (dict, sorted((repr(k), repr(norm(v))) for k, v in value.items()))
    return (type(value), repr(value))

def answer(fn, *args):
    try:
        value = fn(*args)
    except Exception as err:
        return ("raise", type(err).__name__, str(err))
    return norm(value)

def maps():
    out = []
    plain = R._JsMap()
    for key in POOL:
        plain.set(key, repr(key))
    out.append(plain)
    strs = R._JsMap()
    for i, key in enumerate(["a", "b", 1, 2, 2**53]):
        strs.set(key, i)
    out.append(strs)
    out.append(R._js_map_entries({"2": "two", "1": "one", "a": "A"}))
    s = R._JsSet()
    for key in POOL:
        s.add(key)
    out.append(s)
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
        if bad < 8:
            print("DIFF", label, got, want)

for a, b in itertools.product(POOL, POOL):
    check(("eq", a, b), answer(P.eq_in, a, b), answer(R._js_strict_eq, a, b))
    check(("ne", a, b), answer(P.ne_in, a, b), answer(lambda x, y: not R._js_strict_eq(x, y), a, b))
for k in POOL + ["missing", 3, 2**53 + 3]:
    for i, m in enumerate(maps()):
        check(("get", i, k), answer(P.get_in, m, k), answer(R._js_m_get, m, k))
    for i, m in enumerate(maps()):
        check(("has", i, k), answer(P.has_in, m, k), answer(R._js_m_has, m, k))
    for i, (m1, m2) in enumerate(zip(maps(), maps())):
        for v in [1, None, [k]]:
            check(("set", i, k, repr(v)), answer(P.set_in, m1, k, v), answer(lambda: (R._js_m_set(m2, k, v), m2)[1]))
for x in POOL:
    for xs1, xs2 in [([1, 2], [1, 2]), ([], []), (SubList([1]), SubList([1])), ("ab", "ab"), (None, None), (R._JsMap(), R._JsMap())]:
        check(("push", repr(xs1), x), answer(P.push_in, xs1, x), answer(lambda: (R._js_m_push(xs2, x), xs2)[1]))
    for xs1, xs2 in [([1, 2], [1, 2]), ([], []), (SubList([1]), SubList([1])), (None, None)]:
        check(("pushv", repr(xs1), x), answer(P.push_value_in, xs1, x), answer(R._js_m_push, xs2, x))
for k in POOL + [2, 3, 4, -2, "0", "2"]:
    for v in [9, "v"]:
        for make in [lambda: [0, 0, 0], lambda: SubList([0, 0]), lambda: {"0": 1}, lambda: "abc", lambda: None, lambda: R._JsMap()]:
            xs1, xs2 = make(), make()
            check(("put", repr(xs1), k, v), answer(P.put_in, xs1, k, v), answer(lambda: (R._js_put(xs2, k, v), xs2)[1]))
for xs in [[1, 2, 3], SubList([1, 2]), "a\U0001F600b", {"0": "z", "1": "o"}, {}, None, R._JsMap(), (1, 2), b"ab"]:
    check(("read", repr(xs)), answer(P.read_in, xs, 4), answer(lambda: [R._js_get(xs, k) for k in range(4)]))
    check(("readlit", repr(xs)), answer(P.read_literal_in, xs), answer(lambda: [R._js_get(xs, 0), R._js_get(xs, 1)]))
for s in POOL + [["a"], {"a": 1}]:
    check(("ends", repr(s)), answer(P.ends_in, s), answer(R._js_m_endsWith, s, ".md"))
    check(("starts", repr(s)), answer(P.starts_in, s), answer(R._js_m_startsWith, s, "a"))
for xs_make in [lambda: ["b", "a", "b", "\ud800", "\U0001F600", "\uffff"], lambda: [], lambda: ["a", 1], lambda: [1, "a"], lambda: R._JsSet(["b", "a"]), lambda: ("b", "a"), lambda: ["a", R._JS_UNDEFINED], lambda: None]:
    check(("unique", repr(xs_make())), answer(P.unique_in, xs_make()), answer(lambda: R._js_m_sort([*R._JsSet(xs_make())], A.cmp_codepoint)))
for xs_make in [lambda: [3, 1, 2, 1], lambda: [2**53 + 1, 2**53, 1], lambda: [-0.0, 0, 0.0], lambda: [2, float("nan"), 1], lambda: [1.5, 1, True], lambda: [], lambda: [1], lambda: [None, 1], lambda: [R._JS_UNDEFINED, 1, 0], lambda: [10**30, 1]]:
    check(("num", repr(xs_make())), answer(P.num_in, xs_make()), answer(lambda: R._js_sort_keyed(xs_make(), lambda a, *_: a, False, lambda a, b, *_: R._js_num(R._js_num(a) - R._js_num(b)))))
print("checked", checked, "bad", bad)

# TAKEN: with every helper patched to fail, the fast arms answer for the values they are for.
def boom(*_):
    raise AssertionError("helper called")
for name in ("_js_m_get", "_js_m_has", "_js_m_set", "_js_m_push", "_js_put", "_js_get", "_js_strict_eq", "_js_m_endsWith", "_js_m_startsWith"):
    setattr(P, name, boom)
m = R._JsMap()
P.set_in(m, "k", 1)
P.set_in(m, 2**53, 2)
assert P.get_in(m, "k") == 1 and P.get_in(m, 2**53) == 2 and P.has_in(m, 2**53) is True
assert P.has_in(R._JsSet([3]), 3) is True
assert P.push_in([1], 2) == [1, 2] and P.push_value_in([1], 2) == 2
assert P.put_in([0, 0], 1, 5) == [0, 5]
assert P.read_in([4, 5], 2) == [4, 5] and P.read_literal_in([6, 7]) == [6, 7]
assert P.eq_in(2**53, 2**53) is True and P.ne_in(1, 2) is True and P.eq_in("x", "x") is True
assert P.ends_in("a.md") is True and P.starts_in("ab") is True
print("taken")
"#;

#[test]
fn expansions_equal_the_helpers() {
    let dir = scratch("j90pf-reference");
    package(&dir, &compiled());
    let out = run_python(REFERENCE, &[dir.to_str().unwrap()]);
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(out.contains(" bad 0\n"), "{out}");
    assert!(out.ends_with("taken\n"), "{out}");
}

const RUNTIME_FUZZ: &str = r#"
import json, math, random, sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_runtime as R
from pkg import _ts2py_adapters as A

r = random.Random(90316)
STRS = ["", "a", "b", "Z", "é", "\uffff", "\U0001F600", "\ud800", "\udc00", "a\"b", "c\\d", "\b\f\n\r\t", "\x01\x1f\x7f", "\u2028", "x-0", "-0", "1"]
def a_str():
    return "".join(r.choice(STRS) for _ in range(r.randrange(3)))
INTS = [0, 1, -1, 7, 2**31, 2**52, 2**53 - 1, 2**53, 2**53 + 1, -(2**53), -(2**53) - 1, 2**60, 10**30]

def norm(value):
    if isinstance(value, float) and value != value:
        return ("nan",)
    if isinstance(value, float):
        return (float, value, math.copysign(1.0, value))
    if isinstance(value, (list, tuple)):
        return (type(value), [norm(v) for v in value])
    if isinstance(value, dict):
        return (dict, [(k, norm(v)) for k, v in value.items()])
    return (type(value), value)

def answer(fn, *args):
    try:
        return norm(fn(*args))
    except Exception as err:
        return ("raise", type(err).__name__, str(err))

bad = 0
def check(label, got, want):
    global bad
    if got != want:
        bad += 1
        if bad < 8:
            print("DIFF", label, got, want)

def general_sort_unique(items, compare):
    return R._js_m_sort([*R._JsSet(items)], compare)
for _ in range(4000):
    kind = r.randrange(4)
    if kind == 0:
        xs = [a_str() for _ in range(r.randrange(8))]
    elif kind == 1:
        xs = [r.choice([a_str(), 1, None, R._JS_UNDEFINED]) for _ in range(r.randrange(5))]
    elif kind == 2:
        xs = R._JsSet([a_str() for _ in range(r.randrange(5))])
    else:
        xs = tuple(a_str() for _ in range(r.randrange(4)))
    check(("unique", xs), answer(R._js_sort_unique, xs if not isinstance(xs, list) else list(xs), A.cmp_codepoint), answer(general_sort_unique, xs if not isinstance(xs, list) else list(xs), A.cmp_codepoint))

sub = lambda a, b, *_: R._js_num(R._js_num(a) - R._js_num(b))
for _ in range(4000):
    pick = r.randrange(3)
    pool = INTS if pick == 0 else INTS + [0.5, -0.0, 0.0, float("nan"), float("inf"), True] if pick == 1 else INTS + [None, R._JS_UNDEFINED]
    xs = [r.choice(pool) for _ in range(r.randrange(7))]
    desc = r.random() < 0.5
    check(("num", xs, desc), answer(R._js_sort_num, list(xs), desc, sub), answer(R._js_sort_keyed, list(xs), lambda a, *_: a, desc, sub))

def build(keys, reorder):
    if reorder:
        return R._js_map_entries({"2": 1, "1": 2, "x": 3})
    m = R._JsMap()
    for i, k in enumerate(keys):
        m.set(k, i)
    return m
def walk(rows, drop):
    out = []
    for a, b in rows:
        out.append([a, b])
        R._js_m_delete(M[0], drop)
    return out
M = [None]
for _ in range(2000):
    keys = [r.choice(["a", "b", "c", 1, 2, 2**53 + 1, True, float("nan")]) for _ in range(r.randrange(6))]
    reorder = r.random() < 0.2
    drop = r.choice(keys + ["zz", "1"]) if keys else "zz"
    M[0] = build(keys, reorder)
    got = answer(walk, R._js_rows(M[0], 2, (0, 1)), drop)
    M[0] = build(keys, reorder)
    want = answer(walk, ([R._js_get(item, 0), R._js_get(item, 1)] for item in M[0]), drop)
    check(("rows", keys, reorder, drop), got, want)

for v in INTS + [-(2**53) + 1, 3, -7]:
    check(("str", v), answer(R._js_str, v), answer(R._js_num_str, v))

for _ in range(3000):
    keys = [r.choice(["a", 1, 2**53, 2**53 + 1, -0.0, 0, 1.0, True, float("nan"), None]) for _ in range(r.randrange(5))]
    m1, m2 = R._JsMap(), R._JsMap()
    for k in keys:
        R._js_m_set(m1, k, repr(k))
        m2.set(k, repr(k))
    k = r.choice(keys + ["zz", 3])
    check(("mget", keys, k), answer(R._js_m_get, m1, k), answer(m2.get, k))
    check(("mhas", keys, k), answer(R._js_m_has, m1, k), answer(m2.has, k))
    check(("mstate", keys), norm([[a, b] for a, b in m1]) + (m1._keys is None,), norm([[a, b] for a, b in m2]) + (m2._keys is None,))
    s1 = R._JsSet(keys)
    check(("shas", keys, k), answer(R._js_m_has, s1, k), answer(s1.has, k))

def plain_value(depth=0):
    roll = r.randrange(10)
    if roll < 3 or depth > 3:
        return a_str()
    if roll == 3:
        return r.choice(INTS)
    if roll == 4:
        return r.choice([True, False, None])
    if roll == 5:
        return r.choice([0.5, -0.0, 1e21])
    if roll == 6:
        return {a_str(): plain_value(depth + 1)}
    return [plain_value(depth + 1) for _ in range(r.randrange(4))]
for _ in range(6000):
    v = [plain_value() for _ in range(r.randrange(5))]
    if r.random() < 0.1:
        v.append(v[0] if v else [])
    check(("json", v), answer(R._js_json_stringify, v), answer(lambda x: R._js_json(x), v))
a = []; a.append(a); a.append(a)
check(("json cyclic",), answer(R._js_json_plain, [a]), norm(False))

TOKENS = ["-0", "0", "-1", "1e-0", "-0.0", "12345678901234567", "-12345678901234567", "123", "\"x-0\"", "\"a,-0\"", "\"12345678901234567\"", "\"-0\"", "true", "null"]
for _ in range(6000):
    parts = [r.choice(TOKENS) for _ in range(r.randrange(1, r.choice([40, 400])))]
    sep = r.choice([",", ", ", " ,\n"])
    text = "[" + sep.join(parts) + "]" if r.random() < 0.7 else "{" + sep.join(f'"k{i}":{p}' for i, p in enumerate(parts)) + "}"
    text = r.choice(["", " ", "\n"]) + text
    if R._js_json_ints_exact(text):
        check(("ints", text), answer(R._JS_JSON_DECODER_INTS.decode, text), answer(R._JS_JSON_DECODER.decode, text))
    check(("parse", text), answer(R._js_json_parse, text), answer(R._JS_JSON_DECODER.decode, text))
print("bad", bad)
"#;

#[test]
fn runtime_fast_paths_equal_the_general_path() {
    let dir = scratch("j90pf-runtime");
    package(&dir, &compiled());
    let out = run_python(RUNTIME_FUZZ, &[dir.to_str().unwrap()]);
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(out.ends_with("bad 0\n"), "{out}");
}

const STATS: &str = r#"
import os, sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_adapters as A
from pkg import _ts2py_runtime as R

base = sys.argv[2]
f = os.path.join(base, "f.txt")
open(f, "w").write("x" * 1234)
os.mkdir(os.path.join(base, "d"))
os.symlink(f, os.path.join(base, "l.txt"))
os.symlink(os.path.join(base, "gone"), os.path.join(base, "dangling"))
paths = [f, os.path.join(base, "d"), os.path.join(base, "l.txt"), os.path.join(base, "dangling"), os.path.join(base, "missing"), os.path.join(base, "f.txt", "x"), "", "a\0b", 7]

def answer(fn, *args):
    try:
        return ("ok", fn(*args))
    except Exception as err:
        return ("raise", type(err).__name__, getattr(err, "errno", None), R._js_get(err, "code") if isinstance(err, OSError) else None)

def stamp(p):
    st = A.stat_sync(p, {"bigint": True})
    return R._js_str(R._js_get(st, "mtimeNs")) + ":" + R._js_str(R._js_size(st)) + ":" + R._js_str(R._js_get(st, "ino"))
def mtime(p):
    return R._js_m_toString(R._js_get(A.stat_sync(p, {"bigint": True}), "mtimeNs"))
def row(p):
    st = A.stat_sync(p, {"bigint": True})
    return [R._js_m_toString(R._js_get(st, "mtimeNs")), R._js_number(R._js_size(st)), R._js_invoke(st, "isFile")]
bad = 0
for p in paths:
    for got, want in [(answer(A.stat_stamp, p), answer(stamp, p)), (answer(A.stat_mtime_ns, p), answer(mtime, p)), (answer(A.stat_file, p), answer(row, p))]:
        if got != want:
            bad += 1
            print("DIFF", repr(p), got, want)
print("bad", bad)
"#;

#[test]
fn stat_adapters_equal_the_bigint_stats() {
    let dir = scratch("j90pf-stats");
    package(&dir, &[]);
    let files = dir.join("files");
    std::fs::create_dir_all(&files).unwrap();
    let out = run_python(STATS, &[dir.to_str().unwrap(), files.to_str().unwrap()]);
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(out.ends_with("bad 0\n"), "{out}");
}

const FRONT: &str = r#"
import os, sys
sys.path.insert(0, sys.argv[1])
from bantamkit._generated import _ts2py_adapters as A

base = sys.argv[2]
cases = {
    "plain.md": "---\nname: plain\ndescription: d\ntype: project\n---\nbody\n",
    "links.md": "---\nname: links\ndescription: d\ntype: project\nlinks: [a, b]\ntags:\n  - t\n---\nbody [[c]]\n",
    "nested.md": "---\nname: nested\ndescription: d\nmetadata:\n  type: user\n  links: [x]\n---\n---\nmore\n",
    "crlf.md": "---\r\nname: crlf\r\ndescription: d\r\ntype: project\r\n---\r\nbody\r\n",
    "flow.md": "---\nname: flow\ndescription: d\nmetadata: {type: user, links: [z]}\n---\nbody\n",
}
bad = 0
for name, text in cases.items():
    p = os.path.join(base, name)
    with open(p, "w", newline="") as fh:
        fh.write(text)
    got = A.parse_native(p)
    with open(p, encoding="utf-8") as fh:
        parts = fh.read().split("---\n", 2)
    want = parts[1] if len(parts) == 3 else ""
    if got["front"] != want:
        bad += 1
        print("DIFF", name, repr(got["front"]), repr(want))
print("bad", bad)
"#;

#[test]
fn parse_native_front_is_the_text_it_split() {
    // The bantamkit package itself: the adapter reads through `divergence.parse_fact`.
    let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../runtime-py/src");
    let dir = scratch("j90pf-front");
    let out = run_python(FRONT, &[src.to_str().unwrap(), dir.to_str().unwrap()]);
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(out.ends_with("bad 0\n"), "{out}");
}
