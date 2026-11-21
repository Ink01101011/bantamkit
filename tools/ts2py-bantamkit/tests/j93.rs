//! J91-3 (#341): element and return facts (RULES.md, *J91-3 rules*). A local `const` bound to an
//! `own` list, Map or Set whose every read is a sealed use keeps what was put into it (`elem`); what
//! a function returns is what every return of it proved, across the compiled modules too
//! (`ModuleExports::rets`, rounds of the whole compile; here through an import cycle); the `str`
//! contract of an adapter row; a `g` match's `str`s; `a ?? b`; a for-of `const` narrowed by a guard
//! (and a narrowing never outliving an assignment to the binding, which a `const` and a `let` of
//! one name in one function share); and the JSON integer scan over bytes.
//!
//! Pinned ANSWERING as Node does: `probe()` and `fuzz(3000)` of `tests/fixtures/j93_probe.ts` (with
//! `j93_lib.ts`), both what Node v26.13.0 printed for those files (types stripped;
//! `fixtures/j93_probe.node.txt`), with each fact taken in the compiled text where it holds (a
//! key's test left out, a `str` slice, a list's `len`) and not where a counter-example breaks it.
//! Pinned EQUAL TO THE GENERAL PATH: every fast form has a twin in the fixture whose container is
//! laundered through `opaque`; `fuzz` counts the seeded cases where the twins differ (0 in both
//! runtimes), and in Python the twins run over values JS code cannot build (`str` subclasses with
//! their own `lower`, tuples, bytes, dicts, floats, `None`), with the same answer or exception.

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
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py_bantamkit::options()
    };
    ts2py::compile_modules(
        &[
            (
                "runtime-ts/src/j93_probe.ts",
                include_str!("fixtures/j93_probe.ts"),
            ),
            (
                "runtime-ts/src/j93_lib.ts",
                include_str!("fixtures/j93_lib.ts"),
            ),
        ],
        &options,
    )
    .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")))
}

/// The text of the Python function `name`'s typed body if it has one, else of `name` (its `def`
/// line to the next top-level line).
fn function<'c>(code: &'c str, name: &str) -> &'c str {
    let start = code
        .find(&format!("\ndef _{name}__typed("))
        .or_else(|| code.find(&format!("\ndef {name}(")))
        .unwrap_or_else(|| panic!("no def {name}"));
    let rest = &code[start + 1..];
    let end = rest[1..].find("\ndef ").map_or(rest.len(), |at| at + 1);
    &rest[..end]
}

/// The key test a `Map.get` keeps for a key not proven its own `_js_key`.
fn key_test(k: &str) -> String {
    format!(
        "(type({k}) is str or type({k}) is int and -9007199254740992 <= {k} <= 9007199254740992)"
    )
}

#[test]
fn facts_answer_like_node() {
    let modules = compiled();
    let probe = &modules[0].code;
    let lib = &modules[1].code;
    // Taken: a key proven a `str` is its own tag, so `m.get(t)` keeps only the receiver's test.
    for (name, keys) in [
        ("list_fast", &["t"][..]),
        ("map_fast", &["k"][..]),
        ("set_fast", &["t"][..]),
        ("returns_fast", &["t"][..]),
    ] {
        let body = function(probe, name);
        for k in keys {
            let fast = format!(
                "m._entries.get({k}, _JS_UNDEFINED) if type(m) is _JsMap else _js_m_get(m, {k})"
            );
            assert!(body.contains(&fast), "{name}: no fast get of {k}\n{body}");
            assert!(!body.contains(&key_test(k)), "{name}: {k} tested\n{body}");
        }
    }
    // A sealed Map's for-of still walks it with `_js_rows` (no pair is made); its `get` answers a
    // list or `undefined`, narrowed to the list.
    let map = function(probe, "map_fast");
    assert!(
        map.contains("for k, row in _js_rows(counts, 2, (0, 1)):"),
        "{map}"
    );
    assert!(map.contains("row.append(1)"), "{map}");
    // Another module's returns, through the import cycle: the call's answer is a list.
    let returns = function(probe, "returns_fast");
    for form in [
        "for t in words(text):",
        "for t in matched(text):",
        "for t in run_set(text, [\"b\", \"1\"]):",
        "held = words(text)",
        "for t in held:",
    ] {
        assert!(returns.contains(form), "missing {form}\n{returns}");
    }
    // Not taken: each counter-example keeps the key's test.
    for (code, name, k) in [
        (probe, "list_guarded", "t"),
        (probe, "list_alias", "t"),
        (probe, "closure_return", "t"),
        (probe, "list_splice", "t"),
        (probe, "list_pairs", "k"),
        (probe, "list_any", "t"),
        (probe, "list_stored", "t"),
        (probe, "map_guarded", "k"),
        (probe, "map_bool_key", "k"),
        (probe, "set_guarded", "t"),
        (probe, "set_num", "t"),
        (probe, "returns_guarded", "t"),
        (probe, "returns_untyped", "t"),
        (probe, "match_no_g", "t"),
        (lib, "captured", "t"),
        (lib, "call_later", "t"),
    ] {
        let body = function(code, name);
        assert!(
            body.contains(&key_test(k)),
            "{name}: {k} not tested\n{body}"
        );
    }
    let shared = function(probe, "returns_shared");
    assert!(shared.contains(&key_test("e")), "{shared}");
    assert!(shared.contains(&key_test("s")), "{shared}");
    let set_num = function(probe, "set_num");
    assert!(set_num.contains(&key_test("u")), "{set_num}");
    assert!(set_num.contains(&key_test("w")), "{set_num}");
    let miss = function(probe, "map_miss");
    assert!(miss.contains("_js_truthy(name)"), "{miss}");
    // A Map made from entries holds them (J91-R F1): its `get` may answer the `5` put in, so
    // `r` (`get ?? []`) is not proven a list and `.length` stays `_js_len`, as in its twin.
    for name in ["map_made", "map_made_guarded"] {
        let body = function(probe, name);
        assert!(body.contains("_show(_js_len(r))"), "{name}\n{body}");
        assert!(!body.contains("_show(len(r))"), "{name}\n{body}");
    }
    // The `str` contract: `pyNfkcLower`'s answer is a `str` (its UTF-16 view hoisted, sliced as
    // one); `pyStrip`'s row has no contract.
    let adapter = function(probe, "adapter_fast");
    assert!(
        adapter.contains("_js_units_slice(_jsu_a, 0, 2)"),
        "{adapter}"
    );
    assert!(adapter.contains("_js_m_slice(b, 0, 2)"), "{adapter}");
    // `a ?? b`: a list where `a` is defined, met with `b`.
    let coalesce = function(probe, "coalesce");
    assert!(coalesce.contains("_js_len(v)"), "{coalesce}");
    assert!(coalesce.contains("len(w)"), "{coalesce}");
    // A for-of `const` narrowed by `Array.isArray`; not where a `let` of its name is assigned.
    let narrowed = function(probe, "narrowed_const");
    assert!(
        narrowed.contains("if isinstance(v, list) and len(v) == 2:"),
        "{narrowed}"
    );
    let not_narrowed = function(probe, "narrowed");
    assert!(!not_narrowed.contains("_show(len(v))"), "{not_narrowed}");
    assert!(not_narrowed.contains("_show(_js_len(v))"), "{not_narrowed}");
    assert!(
        not_narrowed.contains("_js_strict_eq(_js_len(v), 2)"),
        "{not_narrowed}"
    );

    let dir = scratch("j93-probe");
    package(&dir, &modules);
    let out = run_python(
        "import json, sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import j93_probe as m\nwant = json.loads(sys.argv[2])\ngot = m.probe()\nassert got == want['probe'], [(a, b) for a, b in zip(got, want['probe']) if a != b][:1]\nfz = m.fuzz(3000)\nassert fz == want['fuzz'], (fz, want['fuzz'])\nprint(len(want['probe']), fz)\n",
        &[
            dir.to_str().unwrap(),
            include_str!("fixtures/j93_probe.node.txt").trim(),
        ],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    // 80 probe lines; no fuzz case where the fast and the general twin differ.
    assert!(out.trim().starts_with("80 0:"), "{out}");
}

const TWINS: &str = r#"
import random, sys
sys.path.insert(0, sys.argv[1])
from pkg import j93_probe as P
from pkg import j93_lib as L
from pkg import _ts2py_runtime as R
from pkg import _ts2py_adapters as A

def answer(fn, *args):
    try:
        got = fn(*args)
        return ("ok", type(got), got)
    except Exception as err:
        return ("raise", type(err).__name__, str(err))

class Loud(str):
    # A `str` subclass whose own `lower` and `__str__` answer something else.
    def lower(self):
        return 42
    def __str__(self):
        return "loud"

class Plain(str):
    pass

rng = random.Random(93)
VALUES = ["a", "b", "1", "a b", Plain("a"), Plain("a b"), Loud("a"), Loud("A B"), 1, True, False, None,
          R._JS_UNDEFINED, 1.5, -0.0, float("nan"), 2 ** 60, (1, 2), [1], {"a": 1}, b"a", R._JsMap(),
          R._JsBigInt(3)]
TEXTS = ["a b", "A b 1", "", "ab12 cd", Plain("a b"), Loud("x y"), Plain("\ud800 z"), 5, None, [1]]
bad = checked = 0
for case in range(3000):
    xs = [rng.choice(VALUES) for _ in range(rng.randrange(6))]
    t = rng.choice(TEXTS)
    for fast, guarded, args in ((P.list_fast, P.list_guarded, (xs,)), (P.map_fast, P.map_guarded, (xs,)),
                                (P.set_fast, P.set_guarded, (t, xs)), (P.returns_fast, P.returns_guarded, (t,))):
        checked += 1
        a, b = answer(fast, *args), answer(guarded, *args)
        if a != b:
            bad += 1
            if bad < 6:
                print("DIFF", fast.__name__, repr(args), a, b)
# The `str` contract: `py_nfkc_lower` answers an exact `str` for any `str` (a subclass with its own
# `lower` included) and refuses anything else, as `unicodedata.normalize` does.
import unicodedata
for v in VALUES + TEXTS:
    checked += 1
    got = answer(A.py_nfkc_lower, v)
    if isinstance(v, str):
        want = ("ok", str, str.lower(unicodedata.normalize("NFKC", v)))
    else:
        want = ("raise", "TypeError", None)
    if got[:2] != want[:2] or (want[0] == "ok" and got[2] != want[2]):
        bad += 1
        print("DIFF nfkc", repr(v), got, want)
print("checked", checked, "bad", bad)
"#;

#[test]
fn fast_forms_equal_the_general_ones_on_python_values() {
    let dir = scratch("j93-twins");
    package(&dir, &compiled());
    let out = run_python(TWINS, &[dir.to_str().unwrap()]);
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(out.trim().ends_with("bad 0"), "{out}");
    assert!(out.contains("checked 12033 bad 0"), "{out}");
}

const JSON_SCAN: &str = r#"
import random, re, sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_runtime as R

# `_js_json_ints_exact` as J90-PF wrote it (the scan over the `str`), the answer J91-3 must keep.
NEG = re.compile(r"-0(?![.eE0-9])")
DIGITS = bytes.maketrans(b"123456789", b"000000000")
RUN = re.compile(b"0+")
def old(text):
    for match in NEG.finditer(text):
        before = match.start() - 1
        while before >= 0 and text[before] in " \t\n\r":
            before -= 1
        if before < 0 or text[before] in "[,:":
            return False
    data = text.encode("utf-8", "surrogatepass")
    zeros = data.translate(DIGITS)
    at = zeros.find(b"0" * 16)
    while at != -1:
        before = at - 1
        if before >= 0 and data[before] == 0x2D:
            before -= 1
        while before >= 0 and data[before] in b" \t\n\r":
            before -= 1
        if before < 0 or data[before] in b"[,:":
            return False
        at = zeros.find(b"0" * 16, RUN.match(zeros, at).end())
    return True

rng = random.Random(341)
ATOMS = ["-0", "0", "-", "1234567890123456", "12345678901234567890", "9", " ", "\t", "\n", "\r", "[", "]",
         ",", ":", '"', "e", "E", ".", "a", "x-0-y", "é", "\ud800", "\U0001F600", "{", "}", "-00", "-0.5",
         "1e-0", "0" * 16, "-" + "9" * 17, "a" + "1" * 16, '"' + "7" * 19 + '"', "-" + "0" * 16]
checked = bad = 0
for case in range(60000):
    text = "".join(rng.choice(ATOMS) for _ in range(rng.randrange(14)))
    checked += 1
    if R._js_json_ints_exact(text) != old(text):
        bad += 1
        if bad < 6:
            print("DIFF", repr(text))
# And what `JSON.parse` answers is the slow decoder's, whichever decoder the scan picks.
for case in range(3000):
    items = [rng.choice(["-0", "0", "1", "-12", "1234567890123456", "-98765432109876543", "1.5", "-0.0",
                         '"x-0"', '"' + "7" * 19 + '"', "[1,-0]", "true", "null"]) for _ in range(rng.randrange(400))]
    text = "[" + ",".join(items) + "]"
    checked += 1
    got = R._js_json_parse(text)
    want = R._JS_JSON_DECODER.decode(text)
    if repr(got) != repr(want) or [type(x) for x in got] != [type(x) for x in want]:
        bad += 1
        print("DIFF parse", text[:80])
print("checked", checked, "bad", bad)
"#;

#[test]
fn json_scan_answers_as_before() {
    let dir = scratch("j93-json");
    package(&dir, &[]);
    let out = run_python(JSON_SCAN, &[dir.to_str().unwrap()]);
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(out.contains("checked 63000 bad 0"), "{out}");
}
