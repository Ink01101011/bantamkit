//! J90-P (#316 G4): the lowerings and runtime fast paths that made the generated storage Python
//! no slower than the hand-written modules it replaced. Each lowering is pinned twice: TAKEN in the
//! probe (the text below is in the generated module) and ANSWERING as Node does (`probe()` and
//! `fuzz(30000)` of `tests/fixtures/j90p_probe.ts`, both what Node v26.13.0 printed for that file,
//! imported by Node, which strips the types). Each runtime fast path is held to the general path
//! it shortcuts by a seeded fuzz over random inputs (`FAST_PATH_FUZZ`).

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

/// What Node v26.13.0 printed for `JSON.stringify(probe())` (every code unit at or above 0x7F
/// written `\uXXXX`).
const NODE_PROBE: &str = include_str!("fixtures/j90p_probe.node.txt");
/// What Node v26.13.0 printed for `fuzz(30000)`.
const NODE_FUZZ: &str = "10072591";

#[test]
fn j90p_lowerings_are_taken_and_answer_like_node() {
    let source = include_str!("fixtures/j90p_probe.ts");
    let modules = ts2py::compile_modules(
        &[("j90p_probe.ts", source)],
        &ts2py::Options {
            runtime_module: Some("._ts2py_runtime".to_string()),
            ..ts2py_bantamkit::options()
        },
    )
    .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    let code = &modules[0].code;
    for taken in [
        // `new Map(Object.entries(x))`, direct and through `const entries = (v) => ...`.
        "m = _js_map_entries(obj)",
        "n = _js_map_entries(obj)",
        // A key sort (`k(b) - k(a)` and `a - b`), not for a Float64Array.
        "_js_sort_keyed([*names], lambda x, *_: _js_m_get(w, x), True, ",
        // J90-PF: `(a, b) => a - b`, the item its own key: `_js_sort_num`.
        "_js_sort_num([3, 1, 2, 10, -1], False, ",
        // Destructuring rows, and one name with its trailing comma.
        "for name, n, _js_hole, d in _js_rows(rows, 4, (0, 1, 3)):",
        "for first, in _js_rows(rows, 1, (0,)):",
        // `typeof x === '...'` as the one type test.
        "isinstance(v, str)",
        "_js_is_number(v)",
        "v is not _JS_UNDEFINED",
        // `Array.isArray(v) && v.length` / `?:` / after an exiting `if`: a list.
        "isinstance(v, list) and len(v) > 1",
        "len(v) if isinstance(v, list) else",
        // A counted loop reading another array's `.length`: checked a list, `len()` in the copy.
        "and type(types) is list:",
        "t >= len(types)",
    ] {
        assert!(code.contains(taken), "`{taken}` missing in:\n{code}");
    }
    let dir = scratch("j90p-probe");
    package(&dir, &modules);
    let out = run_python(
        "import sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import _ts2py_runtime as rt, j90p_probe as m\nout = rt._js_json_stringify(m.probe())\nprint(''.join(c if ord(c) < 0x7F else '\\\\u%04x' % ord(c) for c in rt._js_code_units(out)))\nprint(m.fuzz(30000))\n",
        &[dir.to_str().unwrap()],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let mut lines = out.lines();
    assert_eq!(lines.next().unwrap(), NODE_PROBE.trim_end());
    assert_eq!(lines.next().unwrap(), NODE_FUZZ);
}

/// The key sort only for a comparator that is exactly `k(a) - k(b)` or `k(b) - k(a)` of one pure
/// key: anything else is the general `.sort`.
#[test]
fn j90p_only_a_pure_key_difference_is_a_key_sort() {
    let head = "export function f(xs: string[], m: Map<string, number>, o: Record<string, number>): string[] {\n  return xs.sort(";
    for cmp in [
        "(a, b) => m.get(a)! - m.get(a)!",
        "(a, b) => m.get(b)! + m.get(a)!",
        "(a, b) => m.get(b)! - o[a]!",
        "(a, b) => f([b], m, o).length - f([a], m, o).length",
        "(a, b) => m.get(b)! - m.get(a)! - 1",
    ] {
        let code = ts2py::compile(
            &format!("{head}{cmp});\n}}\n"),
            "m.ts",
            &ts2py_bantamkit::options(),
        )
        .unwrap_or_else(|lines| panic!("{cmp} refused:\n{}", lines.join("\n")));
        assert!(
            code.contains("_js_m_sort(xs, ") && !code.contains("_js_sort_keyed(xs"),
            "{cmp}:\n{code}"
        );
    }
    let code = ts2py::compile(
        &format!("{head}(a, b) => o[b]! - o[a]!);\n}}\n"),
        "m.ts",
        &ts2py_bantamkit::options(),
    )
    .unwrap();
    assert!(
        code.contains("_js_sort_keyed(xs, lambda a, *_: _js_get(o, a), True, "),
        "{code}"
    );
}

#[test]
fn j90p_runtime_fast_paths_answer_as_the_general_paths() {
    let dir = scratch("j90p-fuzz");
    std::fs::write(dir.join("rt.py"), ts2py::RUNTIME).unwrap();
    std::fs::write(
        dir.join("ad.py"),
        ts2py_bantamkit::adapters_module("rt").replace("from .rt import", "from rt import"),
    )
    .unwrap();
    let out = run_python(FAST_PATH_FUZZ, &[dir.to_str().unwrap(), "3000"]);
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(out.trim_end(), "diffs 0", "{out}");
}

const FAST_PATH_FUZZ: &str = r###""""J90-P: each runtime fast path against the general path it shortcuts (reached by an argument of
another type that the general path reads as the same JS value, or by the code the fast path
replaced, spelled here), over seeded random inputs."""
import json, math, random, sys
sys.path.insert(0, sys.argv[1])
import rt as R
import ad as A
N = int(sys.argv[2])
r = random.Random(9090)
diffs = 0
def same(label, a, b):
    global diffs
    if repr(a) != repr(b) or type(a) is not type(b):
        diffs += 1
        if diffs < 10:
            print(label, repr(a)[:200], repr(b)[:200])
def call(f, *a):
    try:
        return ("ok", f(*a))
    except Exception as e:
        return ("err", type(e).__name__, str(e))
CH = ["a", "Z", "0", "9", "é", "😀", "\ud800", "\udc00", "/", ".", "-", " ", '"', "x", "f", "F", "\U0010ffff", "ไ"]
def text(k):
    return "".join(r.choice(CH) for _ in range(r.randint(0, k)))
# 1. `_js_m_slice` / `_js_m_charCodeAt` / `_js_parse_int`: int arguments (fast) against the same
#    numbers as floats (the general path).
for _ in range(N):
    s = text(9)
    a, b = r.randint(-12, 12), r.randint(-12, 12)
    same("slice", call(R._js_m_slice, s, a, b), call(R._js_m_slice, s, float(a), float(b)))
    same("slice1", call(R._js_m_slice, s, a), call(R._js_m_slice, s, float(a)))
    same("charCodeAt", call(R._js_m_charCodeAt, s, a), call(R._js_m_charCodeAt, s, float(a)))
    h = "".join(r.choice("0123456789abcdefABCDEFxg -+") for _ in range(r.randint(0, 17)))
    same("parseInt", call(R._js_parse_int, h, 16), call(R._js_parse_int, h, 16.0))
# 2. `_js_code_units_of`: the width test against splitting every astral character by hand.
def units(t):
    out = []
    for c in t:
        code = ord(c)
        if code < 0x10000:
            out.append(c)
        else:
            code -= 0x10000
            out.append(chr(0xD800 + (code >> 10)) + chr(0xDC00 + (code & 0x3FF)))
    return "".join(out)
for _ in range(N):
    t = text(12)
    same("units", R._js_code_units_of(t), units(t))
# 3. `_js_own_keys` / `_js_object_entries` / `_js_map_entries`: against the J90-2 algorithm.
def own_keys(obj):
    keys = list(obj)
    idx = sorted((k for k in keys if k.isdigit() and k.isascii() and (k[0] != "0" or k == "0") and int(k) < 2**32 - 1), key=int)
    chosen = set(idx)
    return idx + [k for k in keys if k not in chosen]
KEYS = ["0", "1", "01", "10", "2", "a", "b", "4294967294", "4294967295", "", "-1", "1e3", "٣", "99999999999", "7"]
for _ in range(N):
    obj = {}
    for j in range(r.randint(0, 8)):
        obj[r.choice(KEYS)] = j
    same("ownKeys", R._js_own_keys(obj), own_keys(obj))
    same("entries", R._js_object_entries(obj), [[k, obj[k]] for k in own_keys(obj)])
    m = R._js_map_entries(obj)
    same("mapEntries", list(m), [[k, obj[k]] for k in own_keys(obj)])
# 4. `_JsMap` (tag -> value, `_keys` beside): random operations against a model that keeps
#    `(first key, value)` per SameValueZero tag, as the J90-2 Map did.
OBJ = [[1], {"o": 1}]
VALS = ["a", "1", 1, 1.0, -0.0, 0, True, False, None, R._JS_UNDEFINED, float("nan"), 2**60, float(2**60), OBJ[0], OBJ[1]]
def tag(k):
    if isinstance(k, bool):
        return ("b", k)
    if isinstance(k, float) and k != k:
        return ("nan",)
    if isinstance(k, (list, dict)):
        return ("id", id(k))
    if isinstance(k, int) and not -(2**53) <= k <= 2**53:
        return float(k)
    return k
def stored(k):
    # J90-RF2: a Map stores +0 for a -0 key (ECMA-262 Map.prototype.set), so the model does too.
    return 0 if isinstance(k, float) and k == 0 and math.copysign(1.0, k) < 0 else k
for _ in range(N):
    m = R._JsMap([[r.choice(["a", "b", "1"]), j] for j in range(r.randint(0, 3))] if r.random() < 0.5 else None)
    if r.random() < 0.3:
        m = R._js_map_entries({r.choice(KEYS): j for j in range(r.randint(0, 5))})
    model = {}
    for k, v in list(m):
        model.setdefault(tag(k), [k, v])[1] = v
    for _ in range(r.randint(0, 10)):
        op = r.randint(0, 4)
        k = r.choice(VALS + KEYS)
        if op == 0:
            v = r.randint(0, 9)
            got = R._js_m_set(m, k, v) if r.random() < 0.5 else m.set(k, v)
            same("set", got is m, True)
            if tag(k) in model:
                model[tag(k)][1] = v
            else:
                model[tag(k)] = [stored(k), v]
        elif op == 1:
            same("delete", R._js_m_delete(m, k), model.pop(tag(k), None) is not None)
        elif op == 2:
            same("get", R._js_m_get(m, k), model[tag(k)][1] if tag(k) in model else R._JS_UNDEFINED)
        elif op == 3:
            same("has", R._js_m_has(m, k), tag(k) in model)
        else:
            same("size", len(m), len(model))
    same("iter", [[repr(a), repr(b)] for a, b in m], [[repr(a), repr(b)] for a, b in model.values()])
# 5. `_js_get`, `_js_truthy`, `_js_len`, `_js_key`, `_js_m_add`: the reordered tests answer as before.
ANY = VALS + KEYS + [[], ["x"], {}, {"a": 1, "constructor": 2}, "length", "constructor", "toString", 3, -1, 2.0]
def key_old(k):
    if isinstance(k, float) and k == 0 and math.copysign(1.0, k) < 0:
        return 0  # J90-RF2: -0 is the key 0
    if isinstance(k, bool):
        return (R._JsMap, k)
    if isinstance(k, float) and k != k:
        return (R._JsMap, "NaN")
    if isinstance(k, int):
        return R._js_num(k)
    if isinstance(k, (list, dict)):
        return (R._JsSet, id(k))
    return k
def truthy_old(v):
    if v is None or v is R._JS_UNDEFINED:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True
class D(dict):
    pass
for _ in range(N):
    o, k = r.choice(ANY + [{"a": 1, "1": 2}]), r.choice(ANY)
    # A dict subclass takes the general path's dict branch, the answer the fast path shortcuts.
    same("get", call(R._js_get, o, k), call(R._js_get, D(o) if type(o) is dict else o, k))
    same("truthy", R._js_truthy(o), truthy_old(o))
    same("key", repr(R._js_key(k)), repr(key_old(k)))
    s = R._JsSet()
    same("add", (R._js_m_add(s, k) is s, R._js_m_has(s, k), len(s)), (True, True, 1))
# 6. `_js_json_parse`: one reused decoder, ints by `int()` where the text proves them exact,
#    against `json.loads` with the per-token hook on every number.
def ref_parse(t):
    try:
        return ("ok", json.loads(t, parse_int=R._js_json_number, parse_float=R._js_json_number, parse_constant=R._js_json_reject_constant))
    except ValueError as e:
        return ("err", str(e))
def tok():
    k = r.randint(0, 7)
    if k == 0:
        return "-0"
    if k == 1:
        return str(r.randint(0, 999))
    if k == 2:
        return str(r.randint(10**14, 10**22)) * r.randint(1, 2)
    if k == 3:
        return '"' + text(6).replace('"', "q").replace("\\", "") + str(r.randint(0, 10**18)) + '"'
    if k == 4:
        return "-" + str(r.randint(0, 10**17))
    if k == 5:
        return r.choice(["1.5", "-0.0", "1e3", "-0e1", "0", "[]", "{}", "9007199254740993", "-9007199254740993", "9999999999999999", "999999999999999"])
    if k == 6:
        return '{"k":' + str(r.randint(-5, 5)) + "}"
    return '"2026-0' + str(r.randint(1, 9)) + '-11"'
for _ in range(N):
    body = ",".join(tok() for _ in range(r.randint(0, 6)))
    pad = " " * (2100 if r.random() < 0.5 else 0)
    t = r.choice(["[" + pad + body + "]", pad + "[" + body + "]", "\ufeff[" + body + "]", "[" + body + pad + "]"])
    got = call(R._js_json_parse, t)
    want = ref_parse(t)
    same("json", (got[0], repr(got[1]) if got[0] == "ok" else got[2]), (want[0], repr(want[1]) if want[0] == "ok" else want[1]))
# 7. `_js_rows`: against `_js_get` of each named index.
for _ in range(N):
    items = [r.choice([[1, 2, 3, 4, 5], [1], [], "ab", ["x", None, "y"], [7, 8, 9, 10]]) for _ in range(r.randint(0, 4))]
    n = r.randint(1, 4)
    wanted = tuple(i for i in range(n) if r.random() < 0.8) or (0,)
    got = [[row[i] for i in wanted] for row in R._js_rows(items, n, wanted)]
    same("rows", got, [[R._js_get(item, i) for i in wanted] for item in items])
# 8. `_js_sort_keyed`: against the general sort with the same comparator, for numeric keys
#    without NaN (with NaN it IS the general sort), and keys that raise.
NUMS = [0, -0.0, 1, -1, 2.5, math.inf, -math.inf, 3, 3, 2**53, -(2**53)]
for _ in range(N):
    keys = [r.choice(NUMS) for _ in range(r.randint(0, 7))]
    items = list(range(len(keys)))
    desc = r.random() < 0.5
    key = lambda i, *_: keys[i]
    cmp = (lambda a, b, *_: R._js_num(R._js_num(keys[b]) - R._js_num(keys[a]))) if desc else (lambda a, b, *_: R._js_num(R._js_num(keys[a]) - R._js_num(keys[b])))
    same("sortKeyed", R._js_sort_keyed(list(items), key, desc, cmp), R._js_m_sort(list(items), cmp))
# 9. Adapters: `_lifted` keeps a safe-int container as it is; `_posix_normalized` is the port's.
def lifted_old(v):
    if type(v) is list:
        return [lifted_old(x) for x in v]
    if type(v) is dict:
        return {k: lifted_old(v[k]) for k in R._js_own_keys(v)}
    return A._lifted(v) if type(v) in (int, float) else v
SEGS = ["a", "b", ".", "..", "...", "", "x.y", ".a"]
for _ in range(N):
    v = [r.choice([1, 2**53 - 1, 2**53, -(2**53) + 1, 2.0, True, None, "s"]) for _ in range(r.randint(0, 5))]
    same("lifted", A._lifted(v), lifted_old(v))
    d = {str(j): x for j, x in enumerate(v)}
    same("liftedDict", A._lifted(d), lifted_old(d))
    p = "/".join(r.choice(SEGS) for _ in range(r.randint(1, 6)))
    if r.random() < 0.3:
        p = "/" + p
    above = r.random() < 0.5
    same("normalize", A._posix_normalized(p, above), A._normalize_string(p, above, "/", lambda c: c == "/"))
# 10. `_js_class_names` (memoised per class AND attribute) through `_js_invoke` and `_js_get`.
class P1(R._JsObject):
    _js_own = frozenset({"x"})
    _js_own_methods = frozenset({"m"})
    def m(self):
        return "p1"
class P2(P1):
    _js_own = frozenset({"y"})
    _js_own_methods = frozenset({"n"})
    def n(self):
        return "p2"
class Q(R._JsObject):
    _js_own_methods = frozenset({"q"})
    def q(self):
        return "q"
for _ in range(N // 10):
    o = r.choice([P1(), P2(), Q()])
    name = r.choice(["m", "n", "q", "x", "y"])
    want = name in {P1: {"m"}, P2: {"m", "n"}, Q: {"q"}}[type(o)]
    same("invoke", call(R._js_invoke, o, name)[0] == "ok", want)
print("diffs", diffs)
"###;
