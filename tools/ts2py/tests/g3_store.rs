//! J89-4a (#316 G3 U2): the constructs `memory/store.ts` needed — `a >> b`, `.forEach`, `.keys()`,
//! `.copyWithin`, `continue` in a C-style `for`, a module `function*` and `yield`, a hole in a
//! for-of pattern, a spread into `.splice`, `\s` / `\S`, `new Date().toISOString()`,
//! `Buffer.byteLength` — and the adapter seam it imports through (`ImportedClass`). Every expected
//! value is what Node v26.13.0 printed for the same TypeScript (`tests/fixtures/j89_4a_probe.ts`,
//! imported by Node, which strips the types); the fuzz generator is spelled once, in that file.

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

fn options() -> ts2py::Options {
    ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py::Options::default()
    }
}

fn compile_package(sources: &[(&str, &str)]) -> Vec<ts2py::Compiled> {
    ts2py::compile_modules(sources, &options())
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")))
}

fn refusals(sources: &[(&str, &str)]) -> Vec<String> {
    match ts2py::compile_modules(sources, &options()) {
        Ok(_) => panic!("expected a refusal"),
        Err(lines) => lines,
    }
}

fn assert_refused(source: &str, expected: &str) {
    let lines = refusals(&[("t.ts", source)]);
    assert!(
        lines.iter().any(|line| line == expected),
        "expected the line\n  {expected}\nin\n  {}",
        lines.join("\n  ")
    );
}

/// What Node v26.13.0 printed for `JSON.stringify(probe())` (every code unit at or above 0x7F
/// written `\uXXXX`) and for `fuzz(20000)`.
const NODE_PROBE: &str = r###"[[[0,0,0,0,0,0,0,0,0,0,0,0,0],[0,0,0,0,0,0,0,0,0,0,0,0,0],[1,0,0,0,1,0,0,0,0,1,0,1,0],[-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1],[5,2,1,0,5,2,0,2,2,5,0,5,2],[-5,-3,-2,-1,-5,-3,-1,-3,-3,-5,-1,-5,-3],[7,3,1,0,7,3,0,3,3,7,0,7,3],[-7,-4,-2,-1,-7,-4,-1,-4,-4,-7,-1,-7,-4],[2147483647,1073741823,536870911,0,2147483647,1073741823,0,1073741823,1073741823,2147483647,268435455,2147483647,1073741823],[-2147483648,-1073741824,-536870912,-1,-2147483648,-1073741824,-1,-1073741824,-1073741824,-2147483648,-268435456,-2147483648,-1073741824],[-2147483648,-1073741824,-536870912,-1,-2147483648,-1073741824,-1,-1073741824,-1073741824,-2147483648,-268435456,-2147483648,-1073741824],[2147483647,1073741823,536870911,0,2147483647,1073741823,0,1073741823,1073741823,2147483647,268435455,2147483647,1073741823],[-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1],[0,0,0,0,0,0,0,0,0,0,0,0,0],[-559939584,-279969792,-139984896,-1,-559939584,-279969792,-1,-279969792,-279969792,-559939584,-69992448,-559939584,-279969792],[559939584,279969792,139984896,0,559939584,279969792,0,279969792,279969792,559939584,69992448,559939584,279969792],[0,0,0,0,0,0,0,0,0,0,0,0,0],[0,0,0,0,0,0,0,0,0,0,0,0,0],[0,0,0,0,0,0,0,0,0,0,0,0,0],[0,0,0,0,0,0,0,0,0,0,0,0,0],[12,6,3,0,12,6,0,6,6,12,1,12,6],[-9,-5,-3,-1,-9,-5,-1,-5,-5,-9,-2,-9,-5],[16,8,4,0,16,8,0,8,8,16,2,16,8],[0,0,0,0,0,0,0,0,0,0,0,0,0],[0,0,0,0,0,0,0,0,0,0,0,0,0],[1,0,0,0,1,0,0,0,0,1,0,1,0],[0,0,0,0,0,0,0,0,0,0,0,0,0],[0,0,0,0,0,0,0,0,0,0,0,0,0],[0,0,0,0,0,0,0,0,0,0,0,0,0],[5,8,10]],[[1,0],[2,1],[3,2],[1,0],[2,1],1,[2,"a",2,"b"],[1,2,3,9],[1,2]],[["b",2,"a"],["z",1,"y"],[0,1,2],["b",2,"a"],[]],[[["d","e","c","d","e"],true],[["d","b","c","d","e"],true],[["a","a","b","c","e"],true],[["a","b","a","b","c"],true],[["a","b","c","a","b"],true],[["d","e","c","d","e"],true],[["b","c","d","d","e"],true],[["a","b","c","d","e"],true],[["a","b","c","d","e"],true],[["a","b","c","d","e"],true],[["a","b","c","d","e"],true],[["a","b","c","d","e"],true],[["a","a","b","c","e"],true],[["a","b","c","d","e"],true],[["a","b","a","d","e"],true],[["a","b","c","d","e"],true],[["a","b","c","d","e"],true],[["c","d","e","d","e"],true],[["a","b","c","b","c"],true],[["a","b","c","d","e"],true],[1,2,4,4,5]],[1,2,4,5,7,8,-8,-4,"01","02","10","12","20","21",0,4,4,4,30,50,60],[0,"#0",1,"#1",99,"end",0,1,2,[],[[0,"#0"],[1,"#1"],[2,"#2"]],1,["start"],["start"],1,2,["start","start","after 1","after 2"]],[1,2,"a","b",3,6],[[3,2,1,4,5],[1,2,3],["x","p","q","r","y"],[]],[[9,10,11,12,13,32,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288,65279],[true,true,false,true,true,true,false,false,true,true,false],[true,false,true,true,false]],[true,24],[0,3,6,3,4,3,5,4,6]]"###;
const NODE_FUZZ: &str = "302436588";

#[test]
fn j89_4a_constructs_answer_like_node() {
    let source = include_str!("fixtures/j89_4a_probe.ts");
    let modules = compile_package(&[("j89_4a_probe.ts", source)]);
    let code = &modules[0].code;
    for lowered in [
        "_js_sar(",
        "_js_m_forEach(",
        "_js_m_keys(",
        "_js_m_copyWithin(",
        "_js_first",
        "    yield ",
        "_js_date_to_iso(_js_now())",
        "buffer_byte_length(",
        "_js_m_splice(a, 0, 3, *",
    ] {
        assert!(code.contains(lowered), "{lowered} missing in:\n{code}");
    }
    // A generator with no `yield` is still one.
    assert!(
        code.contains("def _nothing():\n    return\n    yield"),
        "{code}"
    );
    let dir = scratch("j89-4a-probe");
    package(&dir, &modules);
    let out = run_python(
        "import sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import _ts2py_runtime as rt, j89_4a_probe as m\nout = rt._js_json_stringify(m.probe())\nprint(''.join(c if ord(c) < 0x7F else '\\\\u%04x' % ord(c) for c in rt._js_code_units(out)))\nprint(m.fuzz(20000))\n",
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let mut lines = out.lines();
    assert_eq!(lines.next().unwrap(), NODE_PROBE);
    assert_eq!(lines.next().unwrap(), NODE_FUZZ);
}

/// J89-4a: what the new lowerings must not take, each refused at compile time.
#[test]
fn j89_4a_refusals() {
    let g = "function* g(): Generator<number> {\n  yield 1;\n}\n";
    // A generator's object may not be held: a JS `break` closes it, a Python one does not.
    assert_refused(
        &format!("{g}export function f(): unknown {{\n  const it = g();\n  return it;\n}}\n"),
        "t.ts:5:14: unsupported generator function called anywhere but as a for-of's iterable or an array spread: g()",
    );
    assert_refused(
        &format!("{g}export function f(): unknown {{\n  return [1].map(g);\n}}\n"),
        "t.ts:5:18: unsupported callback that is not an inline arrow function: g",
    );
    assert_refused(
        "export function* g(): Generator<number> {\n  yield* [1];\n}\n",
        "t.ts:2:3: unsupported yield: yield* [1]",
    );
    assert_refused(
        "export function* g(): Generator<number> {\n  const v = yield 1;\n  return;\n}\n",
        "t.ts:2:13: unsupported yield: yield 1",
    );
    assert_refused(
        "export function* g(): Generator<number, number> {\n  yield 1;\n  return 2;\n}\n",
        "t.ts:3:3: unsupported return with a value in a generator function: return 2;",
    );
    assert_refused(
        "export function* g(): Generator<number> {\n  try {\n    yield 1;\n  } finally {\n    g;\n  }\n}\n",
        "t.ts:3:5: unsupported yield: yield 1",
    );
    assert_refused(
        "export class A {\n  *m(): Generator<number> {\n    yield 1;\n  }\n}\n",
        "t.ts:2:3: unsupported generator or async method: *m(): Generator<number> { ...",
    );
    // `forEach` takes no `thisArg`; `keys` no argument; `>>>` stays refused.
    assert_refused(
        "export function f(xs: number[]): void {\n  xs.forEach((x) => x, 1);\n}\n",
        "t.ts:2:3: unsupported argument count for .forEach: xs.forEach((x) => x, 1)",
    );
    assert_refused(
        "export function f(m: Map<string, number>): unknown {\n  return m.keys(1);\n}\n",
        "t.ts:2:10: unsupported argument count for .keys: m.keys(1)",
    );
    assert_refused(
        "export function f(a: number): number {\n  return a >>> 1;\n}\n",
        "t.ts:2:10: unsupported operator >>>: a >>> 1",
    );
    // `copyWithin` needs a target and a start; a hole may not sit beside a rest element.
    assert_refused(
        "export function f(a: number[]): unknown {\n  return a.copyWithin(1);\n}\n",
        "t.ts:2:10: unsupported argument count for .copyWithin: a.copyWithin(1)",
    );
    assert_refused(
        "export function f(xs: number[][]): void {\n  for (const [, ...r] of xs) r;\n}\n",
        "t.ts:2:14: unsupported destructuring rest element: [, ...r]",
    );
    // A spread into `.splice` must be an array proven a list.
    assert_refused(
        "export function f(a: number[], s: string): unknown {\n  return a.splice(0, 1, ...s);\n}\n",
        "t.ts:2:25: unsupported spread of a value not proven an array: ...s",
    );
    // `\s` inside a class stays refused (only the escape outside one is spelled out).
    assert_refused(
        "const R = /[\\s]/;\nexport function f(s: string): boolean {\n  return R.test(s);\n}\n",
        "t.ts:1:11: unsupported regex syntax: /[\\s]/",
    );
    // A `g` regex's `lastIndex` is not modelled, so writing it is refused where it is written.
    assert_refused(
        "const R = /a/g;\nexport function f(): void {\n  R.lastIndex = 0;\n}\n",
        "t.ts:3:3: unsupported assignment to lastIndex: R.lastIndex = 0",
    );
}

/// J89-4a, the orchestrator's method-name clash ruling: `message.usage` in tokenledger.ts was
/// refused because `MemoryStore` declared a method `usage`, and ts2py has no receiver type to tell
/// the two apart (a fact never comes from a TypeScript type alone). store.ts renamed its private
/// `usage()` to `usageLedger()` (Node's answers unchanged); a clash is still refused.
#[test]
fn j89_4a_a_method_name_still_refuses_a_property_read_of_that_name() {
    let reader = "export function usageOf(record: Record<string, unknown>): unknown {\n  const message = record.message as Record<string, unknown>;\n  return message.usage;\n}\n";
    let clashing = "export class Store {\n  private usage(): number {\n    return 1;\n  }\n}\n";
    let lines = refusals(&[("reader.ts", reader), ("store.ts", clashing)]);
    assert!(
        lines.contains(&"reader.ts:3:10: unsupported method .usage read as a value (a method may only be called directly): message.usage".to_string()),
        "{lines:?}"
    );
    let renamed =
        "export class Store {\n  private usageLedger(): number {\n    return 1;\n  }\n}\n";
    compile_package(&[("reader.ts", reader), ("store.ts", renamed)]);
}

/// J89-4a: an `ImportedClass` adapter's methods dispatch only in a module that imports it, and a
/// property of the same name on anything else still reads.
#[test]
fn j89_4a_imported_class_methods_stay_in_their_module() {
    let importer = "import { ColdIndex } from './storage/coldindex.js';\nimport { HotIndex } from './storage/hotindex.js';\nexport function f(c: ColdIndex, h: HotIndex, seen: Set<string>, pool: { names: string[] }): unknown {\n  seen.add('x');\n  c.add(new Map());\n  return [pool.names, h.names()];\n}\n";
    let other = "export function g(seen: Set<string>): unknown {\n  return seen.add('x');\n}\n";
    let modules = compile_package(&[
        ("runtime-ts/src/importer.ts", importer),
        ("runtime-ts/src/other.ts", other),
    ]);
    let code = |stem: &str| -> &str { &modules.iter().find(|m| m.py_module == stem).unwrap().code };
    assert!(
        code("importer").contains("_js_dispatch(seen, \"add\", _js_m_add, \"x\")"),
        "{}",
        code("importer")
    );
    assert!(
        code("importer").contains("_js_get(pool, \"names\")")
            && code("importer").contains("_js_invoke(h, \"names\")"),
        "{}",
        code("importer")
    );
    assert!(
        code("other").contains("_js_m_add(seen, \"x\")"),
        "{}",
        code("other")
    );
}

/// J89-4a, the unit's proof: `memory/store.ts` compiles together with every module the G1/G2/G3
/// call compiles, with no refusal (J89-4 counted 86). Generating it is J89-4b's.
#[test]
fn j89_4a_store_compiles_with_the_committed_modules() {
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
    let store = &modules
        .iter()
        .find(|m| m.py_module == "store")
        .unwrap()
        .code;
    assert!(store.contains("def pooled_ranking("), "{store}");
    assert!(store.contains("from ._ts2py_adapters import "), "{store}");
}

/// J89-4a: `Buffer.byteLength(s, 'utf8')` over 20,000 seeded strings of ASCII, two- three- and
/// four-byte characters and lone surrogates: the length `Buffer.from(s, 'utf8')` has (Node writes
/// U+FFFD's three bytes for a lone surrogate, and so does `buffer_from`).
#[test]
fn j89_4a_byte_length_is_buffer_from_s_length() {
    let dir = scratch("j89-4a-bytes");
    package(&dir, &[]);
    let out = run_python(
        r#"import random, sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_adapters as a
r = random.Random(4004)
pool = ["a", "~", "é", "߿", "ࠀ", "€", "￿", "\U0001f600", "\U0010ffff", "\ud800", "\udbff", "\udc00", "\udfff"]
bad = 0
for _ in range(20000):
    s = "".join(r.choice(pool) for _ in range(r.randint(0, 12)))
    bad += a.buffer_byte_length(s, "utf8") != len(a.buffer_from(s, "utf8"))
print(bad)
"#,
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(out.trim(), "0");
}

/// J89-4b: the store's OS seam as the generated store reaches it. `pyOSErrorText` /
/// `pyOSErrorStrerror` over three CPython errors, `_store_path`'s NUL (the OSError `asPyOSError`
/// makes of Node's ERR_INVALID_ARG_VALUE, the inspected path cut at 128 code units) and lone
/// surrogate (written at U+FFFD), and `pyLexists` of a NUL (false). Every expected line is what
/// Node v26.13.0 printed for the same calls of `runtime-ts/src/memory/pyfs.ts`, run in an empty
/// directory with the same relative paths (macOS; the errno numbers are the platform's).
#[test]
fn j89_4b_store_os_seam_answers_like_node() {
    let dir = scratch("j89-4b-seam");
    package(&dir, &[]);
    let bed = dir.join("bed");
    std::fs::create_dir_all(&bed).unwrap();
    let out = run_python(
        r#"import json, os, sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_adapters as a
os.chdir(sys.argv[2])
open("file.md", "w").write("x")
out = []
def attempt(f):
    try:
        f()
        out.append(None)
    except OSError as e:
        out.append([type(e).__name__, a.py_os_error_text(e), a.py_os_error_strerror(e)])
attempt(lambda: a.py_scandir_names("missing"))
attempt(lambda: a.py_scandir_names("file.md"))
attempt(lambda: a.py_read_text("."))
attempt(lambda: a.py_mkdir_parents("it's\x00\n"))
attempt(lambda: a.py_mkdir_parents("x" * 130 + "\x00"))
a.py_write_text_atomic("s\ud800x.md", "hi")
out.append(a.py_lexists("a\x00b"))
out.append(sorted(os.fsencode(n).hex() for n in os.listdir(".")))
print(json.dumps(out, separators=(",", ":")))
"#,
        &[&dir, &bed],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let long = format!("'{}...", "x".repeat(127));
    let nul = "ERR_INVALID_ARG_VALUE: The argument 'path' must be a string, Uint8Array, or URL without null bytes. Received ";
    let expected = format!(
        concat!(
            r#"[["FileNotFoundError","[Errno 2] No such file or directory: 'missing'","No such file or directory"],"#,
            r#"["NotADirectoryError","[Errno 20] Not a directory: 'file.md'","Not a directory"],"#,
            r#"["IsADirectoryError","[Errno 21] Is a directory: '.'","Is a directory"],"#,
            r#"["OSError","[Errno 0] {nul}\"it's\\x00\\n\": \"it's\\x00\\n\"","{nul}\"it's\\x00\\n\""],"#,
            r#"["OSError","[Errno 0] {nul}{long}: '{x}\\x00'","{nul}{long}"],"#,
            r#"false,["66696c652e6d64","73efbfbd782e6d64"]]"#
        ),
        nul = nul,
        long = long,
        x = "x".repeat(130),
    );
    assert_eq!(out.trim(), expected);
}

/// J89-5 (#316 G3 U3, `memory/native.ts`): a type imported from a compiled module of the call
/// declares its data fields where it is imported, as it does where it is declared. `pool.facts` in
/// native.ts names the `facts` field of store.ts's `Pool`; `MemoryStore` declares a method
/// `facts()`, so without the imported type the read is still refused (J89-4a's clash ruling
/// stands: the declared type decides, never the name alone). The answer is the property, as Node
/// prints it (`[[1,2],null]` for the two pools below).
#[test]
fn j89_5_an_imported_type_declares_its_data_fields() {
    let store = "export interface Pool {\n  facts: number[] | null;\n}\nexport class Store {\n  facts(): number[] {\n    return [];\n  }\n}\n";
    let typed = "import { type Pool } from './store.js';\nexport function rows(pool: Pool): unknown {\n  return pool.facts;\n}\n";
    let whole = "import type { Pool } from './store.js';\nexport function rows(pool: Pool): unknown {\n  return pool.facts;\n}\n";
    let bare = "export function rows(pool: { names: string[] }): unknown {\n  const p = pool as unknown as Record<string, unknown>;\n  return p.facts;\n}\n";
    for reader in [typed, whole] {
        let modules = compile_package(&[("store.ts", store), ("reader.ts", reader)]);
        let dir = scratch("j89-5-typed");
        package(&dir, &modules);
        let got = run_python(
            "import json, sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg.reader import rows\nprint(json.dumps([rows({'facts': [1, 2]}), rows({'facts': None})], separators=(',', ':')))\n",
            &[&dir],
        );
        assert_eq!(got.trim(), "[[1,2],null]");
    }
    let lines = refusals(&[("store.ts", store), ("reader.ts", bare)]);
    assert!(
        lines.contains(&"reader.ts:3:10: unsupported method .facts read as a value (a method may only be called directly): p.facts".to_string()),
        "{lines:?}"
    );
}

/// J89-5: an annotated callback parameter declares its data fields, as a function parameter does
/// (`(o: Omission) => o.count` in tokenledger.ts, once native.ts's `NativeStore.count()` joined
/// the call). Unannotated, the same read is refused. Node prints `[2,5]`.
#[test]
fn j89_5_an_annotated_callback_parameter_declares_its_fields() {
    let layer = "export class Layer {\n  count(): number {\n    return 0;\n  }\n}\n";
    let typed = "interface Omission {\n  count: number;\n}\nexport function counts(xs: Omission[]): number[] {\n  return xs.map((o: Omission) => o.count);\n}\n";
    let bare = "interface Omission {\n  count: number;\n}\nexport function counts(xs: Omission[]): number[] {\n  return xs.map((o) => o.count);\n}\n";
    let modules = compile_package(&[("layer.ts", layer), ("ledger.ts", typed)]);
    let dir = scratch("j89-5-callback");
    package(&dir, &modules);
    let got = run_python(
        "import json, sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg.ledger import counts\nprint(json.dumps(counts([{'count': 2}, {'count': 5}]), separators=(',', ':')))\n",
        &[&dir],
    );
    assert_eq!(got.trim(), "[2,5]");
    let lines = refusals(&[("layer.ts", layer), ("ledger.ts", bare)]);
    assert!(
        lines.contains(&"ledger.ts:5:24: unsupported method .count read as a value (a method may only be called directly): o.count".to_string()),
        "{lines:?}"
    );
}

/// J89-5: two adapter-side speedups the native layer's listing needed, each held to the path it
/// replaces over 20,000 seeded inputs (strings drawn from ASCII, `/`, `.`, U+00E9, a lone
/// surrogate and an astral character): `_js_m_sort` with `cmpCodepoint` sorts strings by Python's
/// own `str` order, which must equal the comparator path (Node-equal since J87-3), and `py_join`'s
/// memo must answer `str(PurePath(*parts))`.
#[test]
fn j89_5_codepoint_sort_and_join_memo_answer_as_the_paths_they_replace() {
    let dir = scratch("j89-5-fast");
    package(&dir, &[]);
    let got = run_python(
        r#"import random, sys, pathlib
sys.path.insert(0, sys.argv[1])
from pkg._ts2py_runtime import _js_m_sort
from pkg._ts2py_adapters import cmp_codepoint, py_join
rng = random.Random(895)
alphabet = ["a", "b", "Z", "0", "/", ".", "é", "\ud800", "\U0001f600", "-"]
word = lambda: "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 6)))
bad_sort = bad_join = 0
for _ in range(20000):
    xs = [word() for _ in range(rng.randrange(0, 9))]
    fast = _js_m_sort(list(xs), cmp_codepoint)
    slow = _js_m_sort(list(xs), lambda a, b, *_: cmp_codepoint(a, b))
    bad_sort += fast != slow
    parts = [word() for _ in range(rng.randrange(1, 4))]
    bad_join += py_join(*parts) != str(pathlib.PurePath(*parts))
print(bad_sort, bad_join)
"#,
        &[&dir],
    );
    assert_eq!(got.trim(), "0 0");
}
