//! J90-P2 (#316 G4): `.sort` with ANY comparator answers V8's order and makes V8's comparator
//! calls (`_js_m_sort` runs `_js_v8_timsort`, not CPython's `list.sort`, which since 3.13 orders
//! an inconsistent comparator otherwise and always calls the comparator on other pairs); the chain
//! key sort (`k1(a) - k1(b) || cmpCodepoint(k2(a), k2(b)) || ...`); `createHash(..).update(..,
//! 'utf8').digest('hex')` as one adapter call; `every` / `some` / `map` / `filter` with an inline
//! arrow as a comprehension; and one body for a function whose guarded entry is its typed body.
//! Each is pinned TAKEN (the text below is in the generated module) and ANSWERING as Node does
//! (`probe()` and `fuzz(3000)` of `tests/fixtures/j90p2_probe.ts`, both what Node v26.13.0 printed
//! for that file, run beside `runtime-ts/dist/pysem.js`, which strips the types). The runtime
//! fast paths are held to the general paths they shortcut by a seeded fuzz (`FAST_PATH_FUZZ`).

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

/// What Node v26.13.0 printed for `JSON.stringify(probe())` (every code unit at or above 0x7F
/// written `\uXXXX`).
const NODE_PROBE: &str = include_str!("fixtures/j90p2_probe.node.txt");
/// What Node v26.13.0 printed for `fuzz(3000)`.
const NODE_FUZZ: &str = "64113070";

#[test]
fn j90p2_lowerings_are_taken_and_answer_like_node() {
    let source = include_str!("fixtures/j90p2_probe.ts");
    // Compiled where it would sit in runtime-ts/src, so `./pysem.js` is the `cmpCodepoint` adapter.
    let modules = ts2py::compile_modules(&[("runtime-ts/src/j90p2_probe.ts", source)], &options())
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    let code = &modules[0].code;
    for taken in [
        // The chain key sorts: two differences, a difference then a code point, a code point alone.
        "_js_sort_lex(rows, ((lambda p, *_: _js_get(p, \"k\"), True, False), (lambda p, *_: _js_get(p, \"j\"), False, False),), ",
        "_js_sort_lex(rows, ((lambda p, *_: _js_get(p, \"k\"), False, False), (lambda p, *_: _js_get(p, \"s\"), False, True),), ",
        "_js_sort_lex(rows, ((lambda p, *_: _js_get(p, \"s\"), False, True),), ",
        // Any other comparator: the general sort (V8's).
        "_js_m_sort(xs, lambda a, b, *_: 1 if _js_gt(a, b) else 0)",
        // The hash chain.
        "hash_hex(\"sha1\", x) if sha1 else hash_hex(\"sha256\", x)",
        // The callbacks, inline.
        "all(isinstance(r, list) and len(r) == 2 and isinstance(r[0], str) for r in rows)",
        "any(_js_is_number(r) and _js_gt(r, 1) for r in rows)",
        "[len(r) if isinstance(r, list) else _js_typeof(r) for r in rows]",
        "[r for r in rows if _js_truthy(r)]",
        // One body, two names; and two bodies where they differ.
        "_twice__typed = twice",
        "def _size__typed(xs):",
        // `r.length === 2` narrows `r` where nothing can change its length, not past a call.
        "_js_m_pop(r) is not None, lambda: _js_list_at(r, 1))",
    ] {
        assert!(code.contains(taken), "`{taken}` missing in:\n{code}");
    }
    assert!(!code.contains("def _twice__typed("), "{code}");
    let dir = scratch("j90p2-probe");
    package(&dir, &modules);
    let out = run_python(
        "import sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import _ts2py_runtime as rt, j90p2_probe as m\nout = rt._js_json_stringify(m.probe())\nprint(''.join(c if ord(c) < 0x7F else '\\\\u%04x' % ord(c) for c in rt._js_code_units(out)))\nprint(m.fuzz(3000))\n",
        &[dir.to_str().unwrap()],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let mut lines = out.lines();
    assert_eq!(lines.next().unwrap(), NODE_PROBE.trim_end());
    assert_eq!(lines.next().unwrap(), NODE_FUZZ);
}

/// A chain is a key sort only when every part is a key difference or `cmpCodepoint` of one pure
/// key of each parameter, and `cmpCodepoint` is the adapter (not a local): anything else is the
/// general `.sort`.
#[test]
fn j90p2_only_a_chain_of_pure_keys_is_a_chain_key_sort() {
    let head = "import { cmpCodepoint } from './pysem.js';\nexport function f(xs: Array<{ k: number; s: string }>, m: Map<string, number>): unknown {\n  return xs.sort(";
    for cmp in [
        "(a, b) => a.k - b.k || 1",
        "(a, b) => a.k - b.k || cmpCodepoint(a.s, a.s)",
        "(a, b) => a.k - b.k || cmpCodepoint(a.s, b.s) * 2",
        "(a, b) => a.k - b.k && cmpCodepoint(a.s, b.s)",
        "(a, b) => a.k - b.k || f([a], m).length - f([b], m).length",
        "(a, b) => a.k - b.k || cmpCodepoint(a.s, b.k as unknown as string, 1 as unknown as string)",
        "(a, b) => a.k + b.k || cmpCodepoint(a.s, b.s)",
    ] {
        let source = format!("{head}{cmp});\n}}\n");
        let modules = ts2py::compile_modules(&[("runtime-ts/src/m.ts", &source)], &options())
            .unwrap_or_else(|lines| panic!("{cmp} refused:\n{}", lines.join("\n")));
        let code = &modules[0].code;
        assert!(
            code.contains("_js_m_sort(xs, ") && !code.contains("_js_sort_lex("),
            "{cmp}:\n{code}"
        );
    }
    // A local named `cmpCodepoint` is not the adapter.
    let source = "export function f(xs: Array<{ k: number; s: string }>): unknown {\n  const cmpCodepoint = (x: string, y: string): number => x.length - y.length;\n  return xs.sort((a, b) => cmpCodepoint(a.s, b.s));\n}\n";
    let modules = ts2py::compile_modules(&[("runtime-ts/src/m.ts", source)], &options())
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    assert!(
        !modules[0].code.contains("_js_sort_lex("),
        "{}",
        modules[0].code
    );
    // J90-P's own list: a difference then a second difference is now this sort.
    let source =
        format!("{head}(a, b) => (m.get(b.s)! - m.get(a.s)!) || a.s.length - b.s.length);\n}}\n");
    let modules = ts2py::compile_modules(&[("runtime-ts/src/m.ts", &source)], &options())
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    assert!(
        modules[0].code.contains(
            "_js_sort_lex(xs, ((lambda a, *_: _js_m_get(m, _js_get(a, \"s\")), True, False), "
        ),
        "{}",
        modules[0].code
    );
}

/// A callback is inline only with one plain parameter and no function in its body; the hash
/// chain only with the adapter, a literal algorithm and the literal encodings.
#[test]
fn j90p2_callbacks_and_hashes_inline_only_as_written() {
    let general = [
        (
            "export function f(xs: number[]): unknown {\n  return xs.map((x, i) => x + i);\n}\n",
            "_js_m_map(xs, ",
        ),
        (
            "export function f(xs: number[], ys: number[]): unknown {\n  return xs.map((x) => ys.map((y) => x + y));\n}\n",
            "_js_m_map(xs, ",
        ),
        (
            "export function f(xs: number[][]): unknown {\n  return xs.every(([x]) => x);\n}\n",
            "_js_m_every(xs, ",
        ),
        (
            "import { createHash } from 'node:crypto';\nexport function f(x: string, a: string): unknown {\n  return createHash(a).update(x, 'utf8').digest('hex');\n}\n",
            "_js_invoke(create_hash(a), \"update\", x, \"utf8\")",
        ),
        (
            "import { createHash } from 'node:crypto';\nexport function f(x: string): unknown {\n  return createHash('sha256').update(x).digest('hex');\n}\n",
            "_js_invoke(create_hash(\"sha256\"), \"update\", x)",
        ),
    ];
    for (source, want) in general {
        let modules = ts2py::compile_modules(&[("runtime-ts/src/m.ts", source)], &options())
            .unwrap_or_else(|lines| panic!("{source} refused:\n{}", lines.join("\n")));
        let code = &modules[0].code;
        assert!(code.contains(want), "`{want}` missing in:\n{code}");
        assert!(
            !code.contains(" for x in ") && !code.contains("hash_hex("),
            "{code}"
        );
    }
}

#[test]
fn j90p2_runtime_fast_paths_answer_as_the_general_paths() {
    let dir = scratch("j90p2-fuzz");
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

const FAST_PATH_FUZZ: &str = r###""""J90-P2: each runtime fast path against the general path it shortcuts, over seeded inputs."""
import math, random, sys
sys.path.insert(0, sys.argv[1])
import rt as R
import ad as A
N = int(sys.argv[2])
r = random.Random(9092)
diffs = 0
def same(label, a, b):
    global diffs
    if repr(a) != repr(b) or type(a) is not type(b):
        diffs += 1
        if diffs < 10:
            print(label, repr(a)[:300], repr(b)[:300])
def call(f, *a):
    try:
        return ("ok", f(*a))
    except Exception as e:
        return ("err", type(e).__name__, str(e))
# 1. `_js_sort_lex`: against the general sort (V8's) with the chain comparator, with keys that
#    are numbers (NaN, infinities, -0, ints past 2^53), strings, and values neither takes.
NUMS = [0, -0.0, 1, -1, 2.5, math.inf, -math.inf, math.nan, 3, 3, 2**53, 2**53 + 1, -(2**53), "7", None, True]
STRS = ["", "a", "b", "ab", "é", "\U0001f600", "a\U0001f600", "Z", "\ud800", 7]
def cmp_of(parts):
    def cmp(a, b, *_):
        for key, desc, cp in parts:
            x, y = (key(b), key(a)) if desc else (key(a), key(b))
            v = A.cmp_codepoint(x, y) if cp else R._js_num(R._js_num(x) - R._js_num(y)) if R._js_is_number(x) and R._js_is_number(y) else math.nan
            if R._js_truthy(v):
                return v
        return v
    return cmp
for _ in range(N):
    n = r.randint(0, 40)
    rows = [{"k": r.choice(NUMS[:12] if r.random() < 0.6 else NUMS), "j": j, "s": r.choice(STRS[:9] if r.random() < 0.7 else STRS)} for j in range(n)]
    parts = []
    for _ in range(r.randint(1, 3)):
        f = r.choice(["k", "j", "s"])
        cp = f == "s"
        parts.append(((lambda f: lambda o, *_: o[f])(f), r.random() < 0.5, cp))
    parts = tuple(parts)
    cmp = cmp_of(parts)
    same("lex", call(lambda: [o["j"] for o in R._js_sort_lex(list(rows), parts, cmp)]), call(lambda: [o["j"] for o in R._js_m_sort(list(rows), cmp)]))
# 2. `_js_m_sort` with a comparator IS V8's sort: against `_js_v8_sort`, with the calls it makes.
for _ in range(N):
    xs = [r.choice([math.nan, r.randint(0, 9), R._JS_UNDEFINED]) for _ in range(r.randint(0, 30))]
    calls_a, calls_b = [], []
    def ca(x, y, *_):
        calls_a.append((repr(x), repr(y)))
        return x - y
    def cb(x, y, *_):
        calls_b.append((repr(x), repr(y)))
        return x - y
    same("sort", repr(R._js_m_sort(list(xs), ca)), repr(R._js_v8_sort(list(xs), cb)))
    same("calls", calls_a, calls_b)
# 3. `hash_hex`: against the three calls, for strings of every kind and what they refuse.
CH = ["a", "Z", "0", "é", "\U0001f600", "\ud800", "\udc80", " ", "ก"]
for _ in range(N):
    t = "".join(r.choice(CH) for _ in range(r.randint(0, 9)))
    alg = r.choice(["sha256", "sha1"])
    data = t if r.random() < 0.95 else r.choice([None, 7, b"x"])
    same("hash", call(A.hash_hex, alg, data), call(lambda: A.create_hash(alg).update(data, "utf8").digest("hex")))
# 4. `_js_number_is_integer`'s plain-int answer: against the general path it shortcuts (the
#    value as the double JS holds, then finite and integral), at and past 2^53 and the double range.
def is_integer_general(v):
    if not R._js_is_number(v):
        return False
    v = R._js_num(v)
    return True if isinstance(v, int) else math.isfinite(v) and v.is_integer()
EDGE = [0, 1, -1, 2**53, 2**53 + 1, -(2**53) - 1, 2**1023, 2**1024, -(2**1024), 10**400, True, 1.5, 2.0, math.nan, math.inf, "3", None]
for _ in range(N):
    v = r.choice(EDGE + [r.randint(-(2**60), 2**60), r.randint(-9, 9)])
    same("isInteger", R._js_number_is_integer(v), is_integer_general(v))
print("diffs", diffs)
"###;
