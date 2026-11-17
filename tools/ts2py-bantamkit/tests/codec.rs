//! J86: the constructs the fact-file codec needs (classes, Error subclasses, throw, switch, BigInt,
//! JS `%` and `/`, UTF-16 string positions, regex `g` and lookbehind, closures, destructuring),
//! multi-module compilation and the adapter seam. Every expected value below is what Node printed
//! for the same TypeScript.

use std::path::{Path, PathBuf};
use std::process::Command;

/// The interpreter the generated code runs under. A missing interpreter fails the test (J85-R2 L2).
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
            panic!(
                "cannot run {python}: {err}; this test runs generated code under Python and fails without one (set TS2PY_PYTHON)"
            )
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

/// Every J86 lowering rule against Node: `probe()`'s 70 values and `probe2()`'s 16, and the three error paths (a write
/// to a frozen instance, a BigInt mixed with a number, `throw` of an Error subclass) by `name` and
/// `message`.
#[test]
fn j86_semantics_match_node() {
    let source = include_str!("fixtures/j86_probe.ts");
    let module = ts2py::compile(source, "j86_probe.ts", &ts2py_bantamkit::options())
        .unwrap_or_else(|lines| panic!("probe refused:\n{}", lines.join("\n")));
    let dir = scratch("j86-probe");
    let path = dir.join("probe.py");
    std::fs::write(&path, module).unwrap();
    let out = run_python(
        r#"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("p", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.probe())
print(m.probe2())
for f in ["frozen_write", "mix_big_int", "throw_boom"]:
    try:
        getattr(m, f)()
        print(f, "returned")
    except Exception as e:
        print(f, e.name, str(e), isinstance(e, TypeError))
"#,
        &[&path],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let expected = concat!(
        r#"[26,1,"c:26","c:26","c:26","own push p",true,"no error","bad thing","Error","Error: bad thing",true,true,"#,
        r#""Renamed","Renamed: tt","y",true,"L",true,14,[2,1],["z","a","b"],true,true,false,true,false,"numeric","#,
        r#""numeric","string/2","other",["ab","c","d"],[1,-1,1,1.5],"true-Infinity",[3.5,null,null,"NaN",2],"#,
        r#""-Infinity",[-3,3,5,null,null],"95","bigint",true,true,4,true,128512,56832,"😀a",true,2,true,3,4,3,0,2,"#,
        r#""007","abxyx","---","abc","a+b_c","x😀y","?x",["a😀","a",true,"😀"],true,false,255,-12,12,null,true,"#,
        r#""FF","abc"]"#,
        "\n",
        r#"[8,"Infinity","-Infinity","NaN",true,[1,3],2,true,[2,3],[["a",1],["b","two"]],1,"m","Error",true,"-1","-Infinity"]"#,
        "\n",
        "frozen_write TypeError Cannot assign to read only property 'v' of object '#<Frozen>' True\n",
        "mix_big_int TypeError Cannot mix BigInt and other types, use explicit conversions True\n",
        "throw_boom Error from throw False\n",
    );
    assert_eq!(out, expected);
}

/// The fact-file codec itself: `runtime-ts/src/memory/pyyaml.ts` and `factfile.ts` compiled
/// together (factfile imports pyyaml; `pyFloatRepr`, `pyStrip`, `TextDecoder` and `Date` come
/// through the adapter seam), then a synthetic fact file (CRLF, a wrapped description, an astral
/// character, a timestamp and an int that resolve to `PyScalar`, a flow sequence, `\u` escapes
/// including a lone surrogate, a block scalar, a body ending in U+0085) decoded, parsed and
/// formatted, plus four inputs the codec refuses. Each expected line is Node's.
#[test]
fn codec_compiles_and_round_trips_like_node() {
    let root = repo_root();
    let paths = [
        "runtime-ts/src/memory/pyyaml.ts",
        "runtime-ts/src/memory/factfile.ts",
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
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py_bantamkit::options()
    };
    let modules = ts2py::compile_modules(&pairs, &options)
        .unwrap_or_else(|lines| panic!("codec refused:\n{}", lines.join("\n")));
    let dir = scratch("j86-codec");
    let package = dir.join("codec");
    std::fs::create_dir_all(&package).unwrap();
    std::fs::write(package.join("__init__.py"), "").unwrap();
    std::fs::write(package.join("_ts2py_runtime.py"), ts2py::RUNTIME).unwrap();
    std::fs::write(
        package.join("_ts2py_adapters.py"),
        ts2py_bantamkit::adapters_module("._ts2py_runtime"),
    )
    .unwrap();
    for module in &modules {
        std::fs::write(
            package.join(format!("{}.py", module.py_module)),
            &module.code,
        )
        .unwrap();
    }
    assert!(
        modules[1]
            .code
            .contains("from .pyyaml import construct_plain, PyScalar, safe_dump_mapping\n")
    );
    assert!(
        modules[1]
            .code
            .contains("from ._ts2py_adapters import Date, py_strip, TextDecoder\n")
    );
    assert!(
        modules[0]
            .code
            .contains("from ._ts2py_adapters import py_float_repr\n")
    );
    let out = run_python(
        r#"
import json, sys
sys.path.insert(0, sys.argv[1])
from codec import factfile as ff
text = "---\r\nname: synthetic-fact\r\ndescription: a description long enough that PyYAML wraps it at the eightieth column, with é and 😀 inside\r\ntype: project\r\ncreated: 2026-08-23\r\nlast_recalled: '2026-11-15'\r\nlinks:\r\n- other-fact\r\n- 12\r\nkeywords: [alpha, 'beta gamma']\r\npriority: \"high\\u00e9 \\ud83d\\ude00 \\ud800\"\r\nnote: |\r\n  line one\r\n  line two\r\n---\r\n\r\n  Body text.\x85\r\n"
parsed = ff.parse_fact_text(ff.decode_fact_bytes(text.encode("utf-8")))
print(json.dumps(ff.format_fact(parsed), ensure_ascii=False))
# J86-4: a nested `metadata:` mapping is written, as PyYAML writes it (it used to refuse).
print(json.dumps(ff.format_fact(ff.parse_fact_text("---\nname: n\ndescription: d\ntype: t\nmetadata:\n  loop: success\n---\n")), ensure_ascii=False))
for bad in ["---\nname: [a, [b]]\n---\n", "no frontmatter", "---\nname: x\ndescription: \"\\q\"\n---\n"]:
    try:
        ff.format_fact(ff.parse_fact_text(bad))
        print("ok")
    except Exception as e:
        print(json.dumps(f"{e.name}|{e}", ensure_ascii=False))
"#,
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let expected = concat!(
        r#""---\nname: synthetic-fact\ndescription: a description long enough that PyYAML wraps it at the eightieth column,\n  with é and 😀 inside\ntype: project\ncreated: 2026-08-23\nlast_recalled: '2026-11-15'\nlinks:\n- other-fact\n- 12\nkeywords:\n- alpha\n- beta gamma\npriority: highé 😀 �\nnote: 'line one\n\n  line two\n\n  '\n---\n\nBody text.\n""#,
        "\n",
        r#""---\nname: n\ndescription: d\ntype: t\ncreated: null\nlast_recalled: null\nlinks: []\noutcome: success\nmetadata:\n  loop: success\n---\n\n\n""#,
        "\n",
        r#""Error|a flow sequence holding a nested collection is outside this codec's language: \"[a, [b]]\"""#,
        "\n",
        r#""Error|expected 3 parts from split('---\\n', 2), got 1""#,
        "\n",
        r#""Error|unknown escape \\q""#,
        "\n",
    );
    assert_eq!(out, expected);
}

/// The adapter seam: an import resolves to a compiled module, or to a row of `adapters.rs`, or it
/// is a compile error that names it.
#[test]
fn imports_resolve_through_compiled_modules_or_adapters_only() {
    let a = "import { helper } from './b.js';\nimport { pyFloatRepr } from './pyfs.js';\nexport function f(x: number): string {\n  return helper(pyFloatRepr(x));\n}\n";
    let b = "export function helper(s: string): string {\n  return s;\n}\n";
    let modules = ts2py::compile_modules(
        &[
            ("runtime-ts/src/memory/a.ts", a),
            ("runtime-ts/src/memory/b.ts", b),
        ],
        &ts2py::Options {
            runtime_module: Some("._ts2py_runtime".to_string()),
            ..ts2py_bantamkit::options()
        },
    )
    .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    assert_eq!(modules[0].py_module, "a");
    assert!(
        modules[0]
            .code
            .contains("from ._ts2py_adapters import py_float_repr\n")
    );
    assert!(modules[0].code.contains("from .b import helper\n"));

    let lines = ts2py::compile(
        "import { PyRuntimeError } from './pyfs.js';\nimport { x } from 'node:fs';\nexport const y = PyRuntimeError;\n",
        "runtime-ts/src/memory/c.ts",
        &ts2py_bantamkit::options(),
    )
    .unwrap_err();
    assert_eq!(
        lines,
        vec![
            // J89-5b declared pyfs.ts's `pyRepr` (layers.ts imports it); `PyRuntimeError` is not.
            "runtime-ts/src/memory/c.ts:1:10: unsupported import of PyRuntimeError from ./pyfs.js: no compiled module and no declared adapter: PyRuntimeError",
            "runtime-ts/src/memory/c.ts:2:10: unsupported import of x from node:fs: no compiled module and no declared adapter: x",
        ]
    );
}

/// What J86 chose to refuse rather than approximate, each with its reason.
#[test]
fn j86_refusals() {
    let cases: &[(&str, &str)] = &[
        // A closure per iteration in JS, one shared binding in Python.
        (
            "export function f(xs: number[]): number {\n  let n = 0;\n  for (const x of xs) {\n    const g = (): number => x;\n    n = g();\n  }\n  return n;\n}\n",
            "t.ts:4:15: unsupported function defined inside a loop: (): number => x",
        ),
        // Fallthrough between non-empty cases.
        (
            "export function f(x: number): number {\n  let n = 0;\n  switch (x) {\n    case 1:\n      n = 1;\n    case 2:\n      return 2;\n  }\n  return n;\n}\n",
            "t.ts:4:5: unsupported switch case that falls through: case 1: ...",
        ),
        // A `break` that leaves the switch from the middle of a case.
        (
            "export function f(x: number): number {\n  switch (x) {\n    case 1:\n      if (x) break;\n      return 1;\n  }\n  return 0;\n}\n",
            "t.ts:4:14: unsupported break that does not end its switch case: break;",
        ),
        // A default in the middle reorders the if-chain.
        (
            "export function f(x: number): number {\n  switch (x) {\n    default:\n      return 0;\n    case 1:\n      return 1;\n  }\n}\n",
            "t.ts:3:5: unsupported default that is not the last, separate switch case: default: ...",
        ),
        // Flags other than `g` (case folding and `u` differ between the engines).
        (
            "export const R = /a/i;\n",
            "t.ts:1:18: unsupported regex flags other than g: /a/i",
        ),
        // A substitution that is not a whole repeat count would build a pattern at run time.
        (
            "export function f(s: string): boolean {\n  return new RegExp(`^${s}$`).test('x');\n}\n",
            "t.ts:2:10: unsupported RegExp substitution anywhere but a whole {n} repeat count: new RegExp(`^${s}$`)",
        ),
        // A lookbehind whose width is not fixed (Python's re requires a fixed width).
        (
            "export const R = /(?<=a+)b/;\n",
            "t.ts:1:18: unsupported regex quantifier `+` inside a lookbehind: /(?<=a+)b/",
        ),
        // Defaults inside a destructuring pattern.
        (
            "export function f(xs: number[]): number {\n  const [a = 1] = xs;\n  return a;\n}\n",
            "t.ts:2:10: unsupported nested or defaulted destructuring: a = 1",
        ),
        // Assigning a module-level binding (a const or an import in JS).
        (
            "const K = 1;\nexport function f(): void {\n  K = 2;\n}\n",
            "t.ts:3:3: unsupported assignment to a module-level name: K",
        ),
    ];
    for (source, expected) in cases {
        let lines = ts2py::compile(source, "t.ts", &ts2py_bantamkit::options())
            .err()
            .unwrap_or_else(|| panic!("expected a refusal for:\n{source}"));
        assert!(
            lines.iter().any(|line| line == expected),
            "expected the line\n  {expected}\nin\n  {}",
            lines.join("\n  ")
        );
    }
}

/// The J85 lowering of `-` marks its result a known number, so two BigInt differences meet plain
/// Python `+` and `<`; `_JsBigInt` implements those as JS does. Expected line: Node's `big(5n, 2n)`.
#[test]
fn bigint_differences_compose_like_node() {
    let source = "export function big(a: bigint, b: bigint): string {\n  const d = a - b;\n  const e = b - a;\n  return JSON.stringify([String(d + e), d < e, d > e, d <= e, (a - b) >= 3, (a - b) === 3, String(-(a - b))]);\n}\n";
    let module = ts2py::compile(source, "big.ts", &ts2py_bantamkit::options())
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    let dir = scratch("j86-big");
    let path = dir.join("big.py");
    std::fs::write(&path, module).unwrap();
    let out = run_python(
        "import importlib.util, sys\nspec = importlib.util.spec_from_file_location('b', sys.argv[1])\nm = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\nprint(m.big(m._JsBigInt(5), m._JsBigInt(2)))\n",
        &[&path],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(out, "[\"0\",false,true,false,true,false,\"-3\"]\n");
}
