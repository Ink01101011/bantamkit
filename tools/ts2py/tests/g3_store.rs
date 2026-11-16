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

/// J89-5a (#316 G3 U3, `memory/queries.ts`): a class no export names keeps its method names in
/// its own module. queries.ts's `CountsView` (methods `has`, `get`, `keys`, `scan`) is handed out
/// only as a row a function returned; were its names global, every `.get` / `.has` / `.keys` of
/// every module of the call would dispatch at run time. In its module the calls dispatch and run
/// its methods; elsewhere a builtin call is the builtin's helper, which refuses an instance at run
/// time rather than answering differently. An Error subclass that names itself by a class field
/// (`override name = 'Failed'`, queries.ts's `SidecarWriteError`) is the same own property as
/// `this.name = ...` in a constructor. Node v26.13.0 printed, for the two files below,
/// `[[1,true],[null,false],[5,true],5,1,["Failed: no room","Failed","no room","Failed: no room"]]`;
/// Python answers the same but for `lookup(make(...))`, which it refuses.
#[test]
fn j89_5a_a_private_class_keeps_its_method_names_in_its_module() {
    let view = r###"class View {
  private readonly flat: readonly unknown[];
  constructor(flat: readonly unknown[]) {
    this.flat = flat;
  }
  get(k: string): unknown {
    for (let i = 0; i < this.flat.length; i += 2) if (this.flat[i] === k) return this.flat[i + 1];
    return undefined;
  }
  has(k: string): boolean {
    return this.get(k) !== undefined;
  }
}
export function make(flat: readonly unknown[]): ReadonlyMap<string, unknown> {
  return new View(flat) as unknown as ReadonlyMap<string, unknown>;
}
export function read(m: ReadonlyMap<string, unknown>, k: string): unknown[] {
  return [m.get(k) ?? null, m.has(k)];
}
export class Failed extends Error {
  override name = 'Failed';
}
export function failed(): unknown[] {
  const e = new Failed('no room');
  let caught = '';
  try {
    throw e;
  } catch (x) {
    caught = x instanceof Failed && x instanceof Error ? String(x) : 'other';
  }
  return [String(e), e.name, e.message, caught];
}
"###;
    let user = r###"export function lookup(m: ReadonlyMap<string, unknown>, k: string): unknown {
  return m.get(k) ?? null;
}
"###;
    let modules = compile_package(&[("view.ts", view), ("user.ts", user)]);
    let view_py = &modules.iter().find(|m| m.py_module == "view").unwrap().code;
    let user_py = &modules.iter().find(|m| m.py_module == "user").unwrap().code;
    assert!(
        view_py.contains("_js_dispatch(m, \"get\", _js_m_get, k)"),
        "{view_py}"
    );
    assert!(
        user_py.contains("_js_m_get(m, k)") && !user_py.contains("_js_dispatch"),
        "{user_py}"
    );
    assert!(
        view_py.contains("        self.name = \"Failed\""),
        "{view_py}"
    );
    let dir = scratch("j89-5a-private");
    package(&dir, &modules);
    let got = run_python(
        r#"import sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_runtime as rt
from pkg.view import make, read, failed
from pkg.user import lookup
out = [read(make(['a', 1, 'b', 2, 'a', 3]), 'a'), read(make(['a', 1]), 'z'), read(rt._JsMap([['a', 5]]), 'a'), lookup(rt._JsMap([['a', 5]]), 'a')]
try:
    out.append(lookup(make(['a', 1]), 'a'))
except TypeError as e:
    out.append(str(e))
out.append(failed())
print(rt._js_json_stringify(out))
"#,
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(
        got.trim(),
        r#"[[1,true],[null,false],[5,true],5,"ts2py: .get() on _View is outside the subset",["Failed: no room","Failed","no room","Failed: no room"]]"#
    );
    // An exported class's method names still reach every module (J86), so there the call
    // dispatches and runs the method, as Node does.
    let exported = view.replacen("class View {", "export class View {", 1);
    let modules = compile_package(&[("view.ts", &exported), ("user.ts", user)]);
    let user_py = &modules.iter().find(|m| m.py_module == "user").unwrap().code;
    assert!(
        user_py.contains("_js_dispatch(m, \"get\", _js_m_get, k)"),
        "{user_py}"
    );
}

/// J89-5a: the adapters queries.ts imports (`parseJson`, `dumpJson`, `encodeBasestringAscii`,
/// `pyDecodeUtf8`; `createHash('sha1')` over a Buffer; `fs.writeFileSync(path, string, 'utf8')`),
/// held to what Node v26.13.0 printed through runtime-ts's own `pyjson.ts` / `pyfs.ts` / `node:fs`
/// for the same inputs (a repeated key, a code-point key order, an int past 2^64, `-0`, `1e400`,
/// NaN, a lone surrogate, a BOM, malformed texts, a lone surrogate written to a file). A seeded
/// fuzz of 20,000 texts against Node agreed (RULES.md, J89-5a).
#[test]
fn j89_5a_queries_adapters_answer_like_node() {
    let dir = scratch("j89-5a-adapters");
    package(&dir, &[]);
    let written = dir.join("w.txt");
    let got = run_python(
        r#"import sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_runtime as rt, _ts2py_adapters as A
texts = ['{"a":1,"b":2,"a":3}', '{"\\u00e9":1,"z":2,"\\ud83d\\ude00":3,"\\uffff":4}', '{"b":1,"a":[1.0,true,null,"\\u00e9\\ud83d\\ude00\\udc80",-0,1e400,12345678901234567890],"a":{"z":2.5,"y":[]}}', '[NaN,-Infinity,"\\u007f\\u0000"]', '{"v": 1, "facts": {}}  ', '﻿{}', '{"a":1,}', '[1,2']
opts = [{"sortKeys": True, "ensureAscii": False, "separators": [",", ":"]}, rt._JS_UNDEFINED, {"sortKeys": True, "ensureAscii": True, "separators": [",", ":"]}, {"indent": 2}]
out = []
for t in texts:
    try:
        v = A.parse_json(t)
        out.append([A.dump_json(v, o) for o in opts])
    except rt._JsError as e:
        out.append(["error", e.message])
out.append([A.encode_basestring_ascii(s) for s in ['x', '"q\\', 'é\U0001f600', '\ud800', '\x7f\x1f']])
for b in [bytes([0x61, 0xff]), bytes([0xef, 0xbb, 0xbf, 0x61]), bytes([0xed, 0xa0, 0x80])]:
    try:
        out.append(A.py_decode_utf8(b))
    except rt._JsError as e:
        out.append(["error", e.message])
out.append(A.create_hash("sha1").update(bytes([0, 1, 2, 255])).digest("hex"))
A.write_file_sync(sys.argv[2], "a\ud800b\U0001f600\udc80", "utf8")
out.append(open(sys.argv[2], "rb").read().hex())
t = rt._js_json_stringify(out)
print("".join(c if ord(c) < 0x7F else "\\u%04x" % ord(c) for c in rt._js_code_units(t)))
refused = []
for call in (lambda: A.write_file_sync(sys.argv[2], "x", {"encoding": "utf8"}), lambda: A.write_file_sync(sys.argv[2], b"x", "utf8"), lambda: A.create_hash("md5"), lambda: A.dump_json({"t": "null"}, {"allowNan": False}), lambda: A.parse_json(b"{}"), lambda: A.py_decode_utf8("x")):
    try:
        call()
        refused.append("answered")
    except TypeError as e:
        refused.append(str(e).startswith("ts2py: ") and "outside the subset" in str(e))
print(refused)
"#,
        &[&dir, &written],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let mut lines = got.lines();
    assert_eq!(
        lines.next().unwrap(),
        r###"[["{\"a\":3,\"b\":2}","{\"a\": 3, \"b\": 2}","{\"a\":3,\"b\":2}","{\n  \"a\": 3,\n  \"b\": 2\n}"],["{\"z\":2,\"\u00e9\":1,\"\uffff\":4,\"\ud83d\ude00\":3}","{\"\\u00e9\": 1, \"z\": 2, \"\\ud83d\\ude00\": 3, \"\\uffff\": 4}","{\"z\":2,\"\\u00e9\":1,\"\\uffff\":4,\"\\ud83d\\ude00\":3}","{\n  \"\\u00e9\": 1,\n  \"z\": 2,\n  \"\\ud83d\\ude00\": 3,\n  \"\\uffff\": 4\n}"],["{\"a\":{\"y\":[],\"z\":2.5},\"b\":1}","{\"b\": 1, \"a\": {\"z\": 2.5, \"y\": []}}","{\"a\":{\"y\":[],\"z\":2.5},\"b\":1}","{\n  \"b\": 1,\n  \"a\": {\n    \"z\": 2.5,\n    \"y\": []\n  }\n}"],["[NaN,-Infinity,\"\u007f\\u0000\"]","[NaN, -Infinity, \"\\u007f\\u0000\"]","[NaN,-Infinity,\"\\u007f\\u0000\"]","[\n  NaN,\n  -Infinity,\n  \"\\u007f\\u0000\"\n]"],["{\"facts\":{},\"v\":1}","{\"v\": 1, \"facts\": {}}","{\"facts\":{},\"v\":1}","{\n  \"v\": 1,\n  \"facts\": {}\n}"],["error","Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0)"],["error","Expecting property name enclosed in double quotes: line 1 column 8 (char 7)"],["error","Expecting ',' delimiter: line 1 column 5 (char 4)"],["\"x\"","\"\\\"q\\\\\"","\"\\u00e9\\ud83d\\ude00\"","\"\\ud800\"","\"\\u007f\\u001f\""],["error","'utf-8' codec can't decode byte 0xff in position 1: invalid start byte"],"\ufeffa",["error","'utf-8' codec can't decode byte 0xed in position 0: invalid continuation byte"],"c62c27924f4c967f5eddb1850c091d54c7a2ab58","61efbfbd62f09f9880efbfbd"]"###
    );
    assert_eq!(
        lines.next().unwrap(),
        "[True, True, True, True, True, True]"
    );
}

/// J89-5e: `parse_json` reads at most 512 deep (arrays and objects alike, the outermost counted),
/// whatever the CPython version and its recursion limit, and past that is the RangeError the
/// recursive `parseJson` throws past its stack. A text malformed before the 513th opener keeps
/// `json.loads`'s own refusal; brackets inside strings do not count. The recursion limit is
/// lowered under the call to show the answer does not move with it (3.11's C scanner counts
/// against it; 3.12 and later do not).
#[test]
fn j89_5e_parse_json_reads_a_fixed_depth() {
    let dir = scratch("j89-5e-depth");
    package(&dir, &[]);
    let got = run_python(
        r#"import sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_runtime as rt, _ts2py_adapters as A
def arr(n, inner=""):
    return "[" * n + inner + "]" * n
def obj(n):
    return '{"k":' * (n - 1) + "{}" + "}" * (n - 1)
texts = [
    arr(512), arr(513), obj(512), obj(513), arr(100000),
    '["[[[[", ' + arr(511) + "]", '["[[[[", ' + arr(512) + "]",
    '["\\"[", ' + arr(511) + "]", '["\\\\", ' + arr(512) + "]",
    "[1 " + arr(600), "{" + arr(600) + "}", "[1, " + arr(600) + "]",
    arr(512, "x"), arr(200) + "]",
]
out = []
for limit in (1000, 600):
    sys.setrecursionlimit(limit)
    row = []
    for t in texts:
        try:
            v = A.parse_json(t)
            row.append("read")
        except rt._JsError as e:
            row.append(e.name + ": " + e.message)
    out.append(row)
sys.setrecursionlimit(1000)
print(A._PARSE_JSON_DEPTH)
print(out[0] == out[1])
for r in out[0]:
    print(r)
"#,
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let range = "RangeError: Maximum call stack size exceeded";
    let expected = [
        "512",
        "True",
        "read",
        range,
        "read",
        range,
        range,
        "read",
        range,
        "read",
        range,
        "PyJSONDecodeError: Expecting ',' delimiter: line 1 column 4 (char 3)",
        "PyJSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
        range,
        "PyJSONDecodeError: Expecting value: line 1 column 513 (char 512)",
        "PyJSONDecodeError: Extra data: line 1 column 401 (char 400)",
    ];
    assert_eq!(got.lines().collect::<Vec<_>>(), expected);
}

/// J89-5b (#316 G3 U3, `memory/layers.ts`): the adapters layers.ts imports. `firstTokenTab` and
/// `parseConfigDocument` (grantconfig.ts) are `yaml.safe_load` by the orchestrator's ruling
/// (Python keeps PyYAML for the config): the tab positions are held to what Node v26.13.0's
/// `firstTokenTab` printed for job65's #158 battery (the two agree there; `--suite store` pins the
/// sentences), the document shapes to what the compiled validator reads, a YAMLError to `str(e)`,
/// and (J89-5d, ruled: a crash is a bug) an error `load_grants` never caught (`ValueError` from an
/// impossible implicit timestamp, `RecursionError` from nesting) held by `firstTokenTab` and
/// refused by `parseConfigDocument` as a JS Error, so the compiled `catch` names it, and a decoded
/// NUL item `other` (it names no path). Until J89-5d the first was raised out of `firstTokenTab`,
/// outside the compiled `try`. The pyfs rows are held to Node's
/// `pyfs.ts` over the same bed (`HOME` the bed; `link` -> `real`).
#[test]
fn j89_5b_layers_adapters_answer_like_the_reference() {
    let dir = scratch("j89-5b-adapters");
    package(&dir, &[]);
    let bed = dir.join("bed");
    std::fs::create_dir_all(bed.join("real").join("sub")).unwrap();
    std::fs::write(bed.join("afile"), "x\n").unwrap();
    #[cfg(unix)]
    std::os::unix::fs::symlink(bed.join("real"), bed.join("link")).unwrap();
    let got = run_python(
        r###"import os, sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_runtime as rt, _ts2py_adapters as A
bed = os.path.realpath(sys.argv[2])
os.environ["HOME"] = bed
docs = ['extra_stores:\n\t- ../../other\n', 'extra_stores:\t[../../other]\n', 'extra_stores:\n  -\t../../other\n', 'extra_stores:\n  \t- ../../other\n', 'extra_stores: []\n\tother: 1\n', 'extra_stores: []\t# none\n', 'extra_stores: []\n\t\n', '# a\tcomment\nextra_stores:\n  - ../../other\n', "extra_stores:\n  - '../../other'\n  - \"../../other\"\n", 'a: 1\n']
print(rt._js_json_stringify([A.first_token_tab(d) for d in docs]))
def shape(text):
    try:
        A.first_token_tab(text)
        doc = A.parse_config_document(text)
    except rt._JsError as e:
        return ["error", e.message.splitlines()[0]]
    if doc["kind"] != "mapping":
        return doc
    return {"kind": "mapping", "entries": [[k, v] for k, v in doc["entries"]]}
texts = ["", "# only\n", "- a\n", "just a scalar\n", "a: 1\n", "extra_stores: [a, 3, null, [b], 'c']\n", "extra_stores: x\n", "extra_stores:\n", "1: [a]\nnull: [b]\nextra_stores: &x [g]\nalias: *x\n", "extra_stores: [unclosed\n", "a: 1\na: 2\n"]
print(rt._js_json_stringify([shape(t) for t in texts]))
held = []
for text in ("k: 2001-02-30\n", "extra_stores: " + "[" * 1000 + "]" * 1000 + "\n", 'extra_stores: ["a\\0b", g]\n'):
    try:
        held.append(A.first_token_tab(text))
        held.append(shape(text))
    except BaseException as e:
        held.append(type(e).__name__)
print(rt._js_json_stringify(held))
print(rt._js_json_stringify([A.py_is_absolute("/a"), A.py_is_absolute("a"), A.py_is_absolute(""), A.py_expanduser("~/x") == bed + "/x", A.py_expanduser("a//b/"), A.py_resolve(bed + "/link/sub/..").replace(bed, "<B>"), A.py_resolve(bed + "/nope/x").replace(bed, "<B>"), A.py_stat_is_dir(bed + "/real"), A.py_stat_is_dir(bed + "/afile"), A.py_is_file(bed + "/afile"), A.py_is_file(bed + "/real"), A.py_is_file(bed + "/missing"), A.py_cwd() == os.getcwd()]))
refused = []
for call in (lambda: A.first_token_tab(b"a: 1"), lambda: A.parse_config_document(None)):
    try:
        call()
        refused.append("answered")
    except TypeError as e:
        refused.append(str(e).startswith("ts2py: ") and "outside the subset" in str(e))
print(refused)
"###,
        &[&dir, &bed],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let mut lines = got.lines();
    // Node: `[[2,1],[1,14],[2,4],[2,3],[2,1],[1,17],[2,1],null,null,null]`.
    assert_eq!(
        lines.next().unwrap(),
        "[[2,1],[1,14],[2,4],[2,3],[2,1],[1,17],[2,1],null,null,null]"
    );
    assert_eq!(
        lines.next().unwrap(),
        r###"[{"kind":"null"},{"kind":"null"},{"kind":"other"},{"kind":"other"},{"kind":"mapping","entries":[["a",{"kind":"other","value":null}]]},{"kind":"mapping","entries":[["extra_stores",{"kind":"seq","items":[{"kind":"str","value":"a"},{"kind":"other","value":null},{"kind":"other","value":null},{"kind":"other","value":null},{"kind":"str","value":"c"}]}]]},{"kind":"mapping","entries":[["extra_stores",{"kind":"other","value":null}]]},{"kind":"mapping","entries":[["extra_stores",{"kind":"other","value":null}]]},{"kind":"mapping","entries":[["extra_stores",{"kind":"seq","items":[{"kind":"str","value":"g"}]}],["alias",{"kind":"seq","items":[{"kind":"str","value":"g"}]}]]},["error","while parsing a flow sequence"],{"kind":"mapping","entries":[["a",{"kind":"other","value":null}]]}]"###
    );
    assert_eq!(
        lines.next().unwrap(),
        r###"[null,["error","day is out of range for month"],null,["error","the document is nested too deeply to read"],null,{"kind":"mapping","entries":[["extra_stores",{"kind":"seq","items":[{"kind":"other","value":null},{"kind":"str","value":"g"}]}]]}]"###
    );
    // Node's pyfs.ts over the same bed: `[true,false,false,"<HOME>/x","a/b","<B>/real",
    // "<B>/nope/x",true,false,true,false,false]` (the last, `pyCwd`, is `process.cwd()`).
    assert_eq!(
        lines.next().unwrap(),
        r###"[true,false,false,true,"a/b","<B>/real","<B>/nope/x",true,false,true,false,false,true]"###
    );
    assert_eq!(lines.next().unwrap(), "[True, True]");
}

/// J89-5c (#316 G3 U3, `memory/dream.ts`): `s.split(re)`, ECMA-262's `RegExp.prototype[@@split]`
/// with no limit over UTF-16 code units (`_js_split_regex`): an empty match where the last piece
/// ended moves on one unit, capture groups join the result (`undefined` when they took no part),
/// `''` is `[]` when the splitter matches it, a `g` flag changes nothing. Every expected value is
/// what Node v26.13.0 printed for `tests/fixtures/j89_5c_probe.ts` (imported by Node, which strips
/// the types): `JSON.stringify(probe())` with every code unit at or above 0x7F written `\uXXXX`,
/// and `fuzz(20000)` (20,000 seeded strings over 13 characters incl. an astral one and both lone
/// halves, split by the 13 splitters).
const NODE_SPLIT_PROBE: &str = r###"[[[""],["a"],["abc"],["a","b","c"],["",""],["x-y+z"],["axbxxc"],["bcbc"],["a\ud83d\ude00b"],["\ud83d\ude00\ud83d\ude00"],["aa"],["cab"],["a,b,,c,"],[","],["b"],["ab"],["word boundary"],["\ud800x\udc00"]],[[],["a"],["a","b","c"],["a","\n","\n","b","\n"," ","\n","\n","c"],["\n","\n"],["","-","y","+","z"],["a","b","c"],["b","c","b","c"],["a","\ud83d","\ude00","b"],["\ud83d","\ude00","\ud83d","\ude00"],["a","a"],["c","a","b"],["a",",","b",",",",","c",","],[","],["b"],["a","b"],["w","o","r","d"," ","b","o","u","n","d","a","r","y"],["\ud800","\udc00"]],[[""],["a"],["abc"],["a\n\nb\n \n\nc"],["\n\n"],["x","-",null,"y",null,"+","z"],["axbxxc"],["bcbc"],["a\ud83d\ude00b"],["\ud83d\ude00\ud83d\ude00"],["aa"],["cab"],["a,b,,c,"],[","],["b"],["ab"],["word boundary"],["\ud800x\udc00"]],[[""],["",""],["","bc"],["","\n\nb\n \n\nc"],["\n\n"],["x-y+z"],["","xbxxc"],["bcbc"],["","\ud83d\ude00b"],["\ud83d\ude00\ud83d\ude00"],["","a"],["cab"],["",",b,,c,"],[","],["b"],["","b"],["word boundary"],["\ud800x\udc00"]],[[""],["",""],["abc"],["a\n\nb\n \n\nc"],["\n\n"],["x-y+z"],["axbxxc"],["bcbc"],["a\ud83d\ude00b"],["\ud83d\ude00\ud83d\ude00"],["a",""],["cab"],["a,b,,c,"],[","],["b"],["ab"],["word boundary"],["\ud800x\udc00"]],[[""],["a"],["ab",""],["a\n\nb\n \n\nc"],["\n\n"],["x-y+z"],["axbxxc"],["b","b",""],["a\ud83d\ude00b"],["\ud83d\ude00\ud83d\ude00"],["aa"],["cab"],["a,b,,c,"],[","],["b"],["ab"],["word boundary"],["\ud800x\udc00"]],[[""],["a"],["abc"],["a","\n\n","b","\n \n\n","c"],["\n\n"],["x","-","y","+","z"],["axbxxc"],["bcbc"],["a","\ud83d\ude00","b"],["\ud83d\ude00\ud83d\ude00"],["aa"],["cab"],["a",",","b",",,","c",","],[","],["b"],["ab"],["word"," ","boundary"],["\ud800","x","\udc00"]],[[""],["a"],["abc"],["a\n\nb\n \n\nc"],["\n\n"],["x-y+z"],["axbxxc"],["bcbc"],["a\ud83d\ude00b"],["\ud83d\ude00\ud83d\ude00"],["aa"],["cab"],["a","b","","c",""],["",""],["b"],["ab"],["word boundary"],["\ud800x\udc00"]],[[""],["a"],["abc"],["a\n\nb\n \n\nc"],["\n\n"],["x-y+z"],["axbxxc"],["bcbc"],["a","\ude00b"],["","\ude00","\ude00"],["aa"],["cab"],["a,b,,c,"],[","],["b"],["ab"],["word boundary"],["","x\udc00"]],[[""],["a"],["abc"],["a\n\nb\n \n\nc"],["\n\n"],["x-y+z"],["axbxxc"],["bcbc"],["a\ud83d","b"],["\ud83d","\ud83d",""],["aa"],["cab"],["a,b,,c,"],[","],["b"],["ab"],["word boundary"],["\ud800x\udc00"]],[[],["a"],["a","b","c"],["a","\n","\n","b","\n"," ","\n","\n","c"],["\n","\n"],["x","-","y","+","z"],["a","x","b","x","x","c"],["b","c","b","c"],["a","\ud83d","\ude00","b"],["\ud83d","\ude00","\ud83d","\ude00"],["a","a"],["c","a","b"],["a",",","b",",",",","c",","],[","],["b"],["a","b"],["w","o","r","d"," ","b","o","u","n","d","a","r","y"],["\ud800","x","\udc00"]],[[""],["a"],["","a","c"],["a\n\n",null,"\n \n\nc"],["\n\n"],["x-y+z"],["ax",null,"xxc"],["",null,"c",null,"c"],["a\ud83d\ude00",null,""],["\ud83d\ude00\ud83d\ude00"],["aa"],["c","a",""],["a,",null,",,c,"],[","],["",null,""],["","a",""],["word ",null,"oundary"],["\ud800x\udc00"]],[[""],["a"],["abc"],["a","b","c"],["",""],["x-y+z"],["axbxxc"],["bcbc"],["a\ud83d\ude00b"],["\ud83d\ude00\ud83d\ude00"],["aa"],["cab"],["a,b,,c,"],[","],["b"],["ab"],["word boundary"],["\ud800x\udc00"]]]"###;
const NODE_SPLIT_FUZZ: &str = "545608662";

#[test]
fn j89_5c_split_by_a_regex_answers_like_node() {
    let source = include_str!("fixtures/j89_5c_probe.ts");
    let modules = compile_package(&[("j89_5c_probe.ts", source)]);
    assert!(
        modules[0].code.contains("_js_m_split("),
        "{}",
        modules[0].code
    );
    let dir = scratch("j89-5c-split");
    package(&dir, &modules);
    let out = run_python(
        r#"import sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_runtime as rt, j89_5c_probe as m
out = rt._js_json_stringify(m.probe())
print("".join(c if ord(c) < 0x7F else "\\u%04x" % ord(c) for c in rt._js_code_units(out)))
print(m.fuzz(20000))
try:
    rt._js_m_split(7, rt._js_re.compile("x"))
    print("answered")
except TypeError as e:
    print(str(e).startswith("ts2py: ") and "outside the subset" in str(e))
"#,
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let mut lines = out.lines();
    assert_eq!(lines.next().unwrap(), NODE_SPLIT_PROBE);
    assert_eq!(lines.next().unwrap(), NODE_SPLIT_FUZZ);
    // A receiver that is not a string is refused at run time, not split.
    assert_eq!(lines.next().unwrap(), "True");
}

/// J89-5c: a limit is still refused at compile time (`.split` takes one argument in the subset).
#[test]
fn j89_5c_split_with_a_limit_is_refused() {
    assert_refused(
        "export function f(s: string): string[] {\n  return s.split(/,/, 2);\n}\n",
        "t.ts:2:10: unsupported argument count for .split: s.split(/,/, 2)",
    );
}

/// J89-6 (#316 G3 U4, `memory/component.ts`): the component compiles together with every module
/// of the G1/G2/G3 call, with no refusal (J89-6's census counted 82), and reaches the hand-written
/// modules it calls only through adapter rows.
#[test]
fn j89_6_component_compiles_with_the_g3_call() {
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
        "runtime-ts/src/memory/native.ts",
        "runtime-ts/src/memory/queries.ts",
        "runtime-ts/src/memory/layers.ts",
        "runtime-ts/src/memory/dream.ts",
        "runtime-ts/src/memory/component.ts",
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
    let component = &modules
        .iter()
        .find(|m| m.py_module == "component")
        .unwrap()
        .code;
    assert!(
        component.contains("class Memory(_JsObject):"),
        "{component}"
    );
    for adapter in [
        "file_links",
        "fire_on",
        "is_skill_store",
        "SkillStore",
        "py_lower",
        "path_resolve",
    ] {
        assert!(
            component.contains(adapter),
            "{adapter} missing in:\n{component}"
        );
    }
}

/// J89-6: the two adapter rows that reproduce something Node answers rather than a reference call.
/// `path_resolve` is `path.posix.resolve`: every expected value is what Node v26.13.0 printed for
/// `path.resolve(...args)` with its working directory written `<C>` (the bed's 20,000-path fuzz,
/// RULES.md, is the wider proof). `py_lower` is `str.lower()`, which component.ts's `pyLower` is
/// on Node: Final_Sigma included (`toLowerCase()` printed the same five strings).
#[test]
fn j89_6_component_adapters_answer_like_node() {
    let dir = scratch("j89-6-adapters");
    package(&dir, &[]);
    let got = run_python(
        r###"import os, sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_runtime as rt, _ts2py_adapters as A
os.chdir(os.path.realpath(sys.argv[1]))
cwd = os.getcwd()
P = [["/a/b"], ["/a/b/"], ["/a//b/./c/.."], ["a/b"], [""], ["."], ["/"], ["//"], ["//a"], ["///a/b"], ["/a", "b"], ["/a", "/b"], ["/a/b/../../.."], ["/.bantamkit/memory"], ["/x/./"], ["/a/b", "", ""], ["/a/..b/c"], ["/a/...", "d"], ["/é/\U0001F600/.."]]
out = rt._js_json_stringify([A.path_resolve(*args).replace(cwd, "<C>") for args in P])
print("".join(c if ord(c) < 0x7F else "\\u%04x" % ord(c) for c in rt._js_code_units(out)))
out = rt._js_json_stringify([A.py_lower(s) for s in ["ΣΟΦΟΣ", "ΑΣ", "Σ", "AΣB", "İ"]])
print("".join(c if ord(c) < 0x7F else "\\u%04x" % ord(c) for c in rt._js_code_units(out)))
refused = []
for call in (lambda: A.path_resolve("/a", 7), lambda: A.py_lower(None)):
    try:
        call()
        refused.append("answered")
    except TypeError as e:
        refused.append(str(e).startswith("ts2py: ") and "outside the subset" in str(e))
print(refused)
"###,
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let mut lines = got.lines();
    assert_eq!(
        lines.next().unwrap(),
        r###"["/a/b","/a/b","/a/b","<C>/a/b","<C>","<C>","/","/","/a","/a/b","/a/b","/b","/","/.bantamkit/memory","/x","/a/b","/a/..b/c","/a/.../d","/\u00e9"]"###
    );
    assert_eq!(
        lines.next().unwrap(),
        r###"["\u03c3\u03bf\u03c6\u03bf\u03c2","\u03b1\u03c2","\u03c3","a\u03c3b","i\u0307"]"###
    );
    assert_eq!(lines.next().unwrap(), "[True, True]");
}
