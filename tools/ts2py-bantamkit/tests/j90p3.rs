//! J90-P3 (#316 G4): proven shapes for JSON-derived arrays. A counted loop may stride
//! (`j += S`, `S` a literal or a module `const`), read `x[j + c]`, read an array only as a value
//! (bounds-checked, never number-checked, and the read proves nothing), hold `throw new
//! Error('...')`, array literals and a counted loop of its own (proven again, per entry, inside the
//! copy); the guard made once before the loop is what proves every read in range and every operand
//! a number, so a value that fails it takes the general loop, as JS would answer. `Array.isArray`
//! is its own test inline; a proven number named once is tested `x != 0 and x == x`.
//!
//! Each is pinned TAKEN (the text below is in the generated module) and ANSWERING as Node does
//! (`probe()` and `fuzz(3000)` of `tests/fixtures/j90p3_probe.ts`, both what Node v26.13.0 printed
//! for that file with `--experimental-strip-types`). The fuzz reads seeded malformed segment arrays
//! from JSON text: wrong types, `null`, `true`, out-of-range starts and runs, ints past 2^53, `-0`,
//! floats, `1e400`, NaN-like strings, lengths that are no multiple of the stride.

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

fn compile(source: &str) -> String {
    let modules = ts2py::compile_modules(&[("runtime-ts/src/m.ts", source)], &options())
        .unwrap_or_else(|lines| panic!("refused:\n{}\n{source}", lines.join("\n")));
    modules[0].code.clone()
}

/// What Node v26.13.0 printed for `JSON.stringify(probe())`.
const NODE_PROBE: &str = include_str!("fixtures/j90p3_probe.node.txt");
/// What Node v26.13.0 printed for `fuzz(3000)`.
const NODE_FUZZ: &str = "731085881";

#[test]
fn j90p3_lowerings_are_taken_and_answer_like_node() {
    let source = include_str!("fixtures/j90p3_probe.ts");
    let modules = ts2py::compile_modules(&[("runtime-ts/src/j90p3_probe.ts", source)], &options())
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    let code = &modules[0].code;
    for taken in [
        // The strided copy of `decode`: the stride from a module `const`, every read in range for
        // the last group, the elements checked numbers once; `names` only bounds-checked.
        "if type(j) is int and 0 <= j and type(m) is int and type(seg) is list and (m <= j or j + (m - 1 - j) // 5 * 5 + 4 < len(seg)) and _js_doubles(seg, j, len(seg)) and type(names) is list and _js_is_double(n):",
        "        for j in range(j, m, 5):  # noqa: B020",
        "            tf2 = seg[j + 4]",
        "            if count < 1 or start < 0 or _js_num(start + count) > n:",
        // The run, a counted loop proven again inside the copy, its names read as they are.
        "            if type(i) is int and 0 <= i and type(end) is int and type(names) is list and end <= len(names):",
        "                for i in range(i, end):  # noqa: B020\n                    name = names[i]\n                    if tf0 != 0 and tf0 == tf0:",
        "                        out.append([name, \"a\", tf0])",
        // A literal stride; one array read only as a value (no `_js_doubles`), one compared.
        "type(keys) is list and (m <= j or j + (m - 1 - j) // 2 * 2 < len(keys)) and type(vals) is list and (m <= j or j + (m - 1 - j) // 2 * 2 + 1 < len(vals)):",
        "and (m <= j or j + (m - 1 - j) // 3 * 3 + 2 < len(xs)) and _js_doubles(xs, j, len(xs)):",
        "            out.append([a < b, c])",
        // An element compared through a `const` is checked a number.
        "m <= len(xs) and _js_doubles(xs, j, m)",
        "            if v < cap:",
        // A `let` a nested copy gives a string is not carried by the outer copy.
        "            s = _js_add(s, xs[i])\n            k = 0\n",
        // `Number.isInteger` of a name and of an element read, inline.
        "out.append((type(x) is int and -2**53 <= x <= 2**53 or _js_number_is_integer(x)))",
        "(type(_js_list_at(xs, 1)) is int and -2**53 <= _js_list_at(xs, 1) <= 2**53 or _js_number_is_integer(_js_list_at(xs, 1)))",
        // `Array.isArray` inline.
        "isinstance(_js_re_exec(_JS_RE_0, s), list)",
    ] {
        assert!(code.contains(taken), "`{taken}` missing in:\n{code}");
    }
    assert!(
        !code.contains("_js_doubles(keys") && !code.contains("_js_doubles(vals"),
        "{code}"
    );
    assert!(!code.contains("_js_is_array("), "{code}");
    // The general loop of a copy (what a failed guard runs) holds no copy of its own: one proven
    // run loop and one general run loop in the copy, one general run loop in the general loop.
    let decode =
        &code[code.find("def decode(").unwrap()..code.find("def _triples__typed(").unwrap()];
    assert_eq!(
        decode.matches("for i in range(i, end):").count(),
        1,
        "{decode}"
    );
    assert_eq!(decode.matches("while i < end:").count(), 1, "{decode}");
    assert_eq!(
        decode.matches("while _js_lt(i, end):").count(),
        1,
        "{decode}"
    );
    let dir = scratch("j90p3-probe");
    package(&dir, &modules);
    let out = run_python(
        "import sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import _ts2py_runtime as rt, j90p3_probe as m\nout = rt._js_json_stringify(m.probe())\nprint(''.join(c if ord(c) < 0x7F else '\\\\u%04x' % ord(c) for c in rt._js_code_units(out)))\nprint(m.fuzz(3000))\n",
        &[dir.to_str().unwrap()],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let mut lines = out.lines();
    assert_eq!(lines.next().unwrap(), NODE_PROBE.trim_end());
    assert_eq!(lines.next().unwrap(), NODE_FUZZ);
}

/// A loop is copied only when its stride, its offsets and its body are all of the proven shape;
/// anything else is the general loop alone.
#[test]
fn j90p3_only_the_proven_shape_is_copied() {
    let head = "const S = 2;\nlet L = 2;\nfunction g(x: number): number {\n  return x;\n}\nexport function f(xs: number[], k: number, out: unknown[]): unknown {\n  const m = xs.length;\n  const acc: unknown[] = [];\n  for (let j = 0; j < m; ";
    for (update, body) in [
        // A stride that is a parameter, a module `let`, a fraction, zero.
        ("j += k", "acc.push([xs[j]! + 1]);"),
        ("j += L", "acc.push([xs[j]! + 1]);"),
        ("j += 1.5", "acc.push([xs[j]! + 1]);"),
        ("j += 0", "acc.push([xs[j]! + 1]);"),
        // A read before the variable, or at an offset that is not a constant.
        ("j += S", "acc.push([xs[j - 1]! + 1]);"),
        ("j += S", "acc.push([xs[j + k]! + 1]);"),
        // A call of compiled code, a throw of a computed message, a spread, a push onto a
        // parameter, a nested loop that is not counted.
        ("j += S", "acc.push([g(xs[j]!)]);"),
        ("j += S", "if (xs[j]! < 0) throw new Error(String(j));"),
        ("j += S", "acc.push([...xs]);"),
        ("j += S", "out.push(xs[j]);"),
        ("j += S", "for (const x of xs) acc.push([x + xs[j]!]);"),
    ] {
        let source = format!("{head}{update}) {{\n    {body}\n  }}\n  return acc;\n}}\n");
        let code = compile(&source);
        assert!(!code.contains(" in range("), "{update} / {body}:\n{code}");
    }
    // An element that reaches an operand through a `let`, or is returned, is checked a number.
    for body in [
        "let v = xs[j]; v = v + 1; acc.push([v]);",
        "return xs[j];",
        "const v = xs[j]; const w = v; acc.push([w]);",
    ] {
        let source = format!("{head}j += S) {{\n    {body}\n  }}\n  return acc;\n}}\n");
        let code = compile(&source);
        assert!(
            code.contains(" in range(j, m, 2):") && code.contains("_js_doubles(xs, j, len(xs))"),
            "{body}:\n{code}"
        );
    }
    // Read only as a value: bounds alone.
    let source = format!(
        "{head}j += S) {{\n    const v = xs[j + 1]; if (v) acc.push([v]);\n  }}\n  return acc;\n}}\n"
    );
    let code = compile(&source);
    assert!(
        code.contains("(m <= j or j + (m - 1 - j) // 2 * 2 + 1 < len(xs)):")
            && !code.contains("_js_doubles("),
        "{code}"
    );
}

/// One body serves both names when the typed body and the guarded entry's differ only in the
/// numbers of the compiler's own temporaries (`_js_caught3` / `_js_caught9`); two bodies when
/// anything else differs. The one body answers as Node does for an argument of either kind.
#[test]
fn j90p3_one_body_up_to_temporaries() {
    let source = "export function f(s: string): unknown {\n  try {\n    return JSON.parse(s);\n  } catch {\n    return ['threw', s];\n  }\n}\nexport function g(s: string): unknown {\n  try {\n    return s.length;\n  } catch {\n    return 0;\n  }\n}\n";
    let modules = ts2py::compile_modules(&[("runtime-ts/src/m.ts", source)], &options())
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    let code = &modules[0].code;
    assert!(code.contains("_f__typed = f\n"), "{code}");
    assert!(!code.contains("def _f__typed("), "{code}");
    assert!(
        code.contains("def _g__typed(") && code.contains("def g("),
        "{code}"
    );
    let dir = scratch("j90p3-temps");
    package(&dir, &modules);
    let out = run_python(
        "import sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import _ts2py_runtime as rt, m\nprint(rt._js_json_stringify([m.f('[1,2]'), m.f('x'), m._f__typed('{}'), m.g('abc'), m.g([1])]))\n",
        &[dir.to_str().unwrap()],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    // Node v26.13.0: `[f('[1,2]'), f('x'), f('{}'), g('abc'), g([1])]`.
    assert_eq!(out.trim_end(), r#"[[1,2],["threw","x"],{},3,1]"#);
}
