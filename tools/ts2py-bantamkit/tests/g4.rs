//! J90-2 (#316 G4: `storage/lock`, `storage/hotindex`): what generating the lock and the hot index
//! needed — `Map.prototype.delete` / `Set.prototype.delete` (and a Map or Set iterated while one
//! is deleted from), an IMPORT CYCLE between two compiled modules (the hot index reads facts with
//! the store's own reader, and the store builds the hot index), and the `dumpJsValue` adapter the
//! index serialises through. Every expected value is what Node v26.13.0 printed for the same
//! TypeScript (`tests/fixtures/j90_g4_probe.ts`, `j90_cycle_a.ts`, `j90_cycle_b.ts`, imported by
//! Node, which strips the types); the fuzz generator is spelled once, in the probe.

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

/// What Node v26.13.0 printed for `JSON.stringify(probe())` (every code unit at or above 0x7F
/// written `\uXXXX`) and for `fuzz(20000)`.
const NODE_PROBE: &str = r###"[[true,false,false,["a","c","b"],3,true,true,true,false,["1"],[["x",1],["y",2],["w",40]],["y","w"],true,false,true,false,3,["a","c"]],["0","0","-0.0","-0.0","1","1","-1","-1","1.5","1.5","1e+21","1e+21","9007199254740991","9007199254740991","9007199254740992.0","9007199254740992.0","9007199254740994.0","9007199254740994.0","-9007199254740992.0","-9007199254740992.0","NaN","NaN","Infinity","Infinity","-Infinity","-Infinity","1e-07","1e-07","0.1","0.1","\"\u00e9\"","\"\\u00e9\"","\"\ud800\"","\"\\ud800\"","true","true","false","false","null","null","null","null","[1,null,null,-0.0,2.5]","[1, null, null, -0.0, 2.5]","{\"01\":\"z\",\"10\":\"y\",\"2\":\"x\",\"a\":[2,3.25],\"b\":1,\"u\":null}","{\"2\": \"x\", \"10\": \"y\", \"b\": 1, \"a\": [2, 3.25], \"01\": \"z\", \"u\": null}","{\"1\":\"n\",\"k\":{\"z\":1},\"true\":\"b\"}","{\"1\": \"n\", \"true\": \"b\", \"k\": {\"z\": 1}}","12","12","{\"avgdl\":4.0}","{\"avgdl\": 4}","{\"avgdl\":0.0}","{\"avgdl\": 0}","{\"avgdl\":-0.0}","{\"avgdl\": -0.0}","{\"avgdl\":4.5}","{\"avgdl\": 4.5}","{\"avgdl\":\"4\"}","{\"avgdl\": \"4\"}","{\"avgdl\":true}","{\"avgdl\": true}","{\"x\":{\"avgdl\":4}}","{\"x\": {\"avgdl\": 4}}","[{\"avgdl\":4}]","[{\"avgdl\": 4}]","{\"avgdl\":NaN}","{\"avgdl\": NaN}","{\"avgdl\":1e+21}","{\"avgdl\": 1e+21}","{\"avgdl\":1.152921504606847e+18}","{\"avgdl\": 1.152921504606847e+18}","{\"avgdl\":4}","{\"avgdl\": 4}"],[[true,true],[true,false],[false,false],[true,false],[true,false],[false,false],[false,false],[false,false],[false,false],[false,false],[true,false],[false,true],[false,false],[false,true],[false,false],[false,false],[false,false]],[["[0,0,1,-1,123456789012345,1234567890123456,9007199254740992,-9007199254740992,100,1,0]",[false,true,false,false,false,false,false,false,false,false,true]],["{\"a\":0,\"b\":[0],\"c\":\"-0\",\"d\":\"12345678901234567\",\"e\":100000000000000000000}",["a","b","c","d","e"],[["a",0],["b",[0]],["c","-0"],["d","12345678901234567"],["e",100000000000000000000]]],["0",true],["12345678901234568",false],["7",false],["[1,2,3]",[false,false,false]],["{\"k\":\"x:-0,1234567890123456\"}",["k"],[["k","x:-0,1234567890123456"]]],["{\"0\":10,\"2\":1,\"10\":2,\"4294967294\":5,\"01\":3,\"a\":4,\"4294967295\":6,\"-1\":7,\"1e3\":8,\"\":9}",["0","2","10","4294967294","01","a","4294967295","-1","1e3",""],[["0",10],["2",1],["10",2],["4294967294",5],["01",3],["a",4],["4294967295",6],["-1",7],["1e3",8],["",9]]]]]"###;
const NODE_FUZZ: &str = "896189796";
/// `parseFuzz(20000)`: seeded JSON texts of integer tokens, parsed and read back.
const NODE_PARSE_FUZZ: &str = "494242382";
/// `JSON.stringify([down(0), down(1), down(5), twice(4), twice(7)])` over the cycle fixture.
const NODE_CYCLE: &str = "[10,22,104,103,219]";

#[test]
fn j90_2_constructs_answer_like_node() {
    let source = include_str!("fixtures/j90_g4_probe.ts");
    // Compiled as a module of runtime-ts/src, so `./pyjson.js` is the `dumpJsValue` adapter row.
    let modules = compile_package(&[("runtime-ts/src/j90_g4_probe.ts", source)]);
    let code = &modules[0].code;
    for lowered in [
        "_js_m_delete(",
        "dump_js_value(",
        "_js_every_integer(",
        "_js_every_string(",
    ] {
        assert!(code.contains(lowered), "{lowered} missing in:\n{code}");
    }
    let dir = scratch("j90-2-probe");
    package(&dir, &modules);
    let out = run_python(
        "import sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import _ts2py_runtime as rt, j90_g4_probe as m\nout = rt._js_json_stringify(m.probe())\nprint(''.join(c if ord(c) < 0x7F else '\\\\u%04x' % ord(c) for c in rt._js_code_units(out)))\nprint(m.fuzz(20000))\nprint(m.parse_fuzz(20000))\n",
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let mut lines = out.lines();
    assert_eq!(lines.next().unwrap(), NODE_PROBE);
    assert_eq!(lines.next().unwrap(), NODE_FUZZ);
    assert_eq!(lines.next().unwrap(), NODE_PARSE_FUZZ);
}

/// J90-2: two compiled modules that import each other (as `storage/hotindex.ts` and
/// `memory/store.ts` do) compile; each imports the other's names at its END, so Python imports
/// the cycle from either side, and the answers are Node's.
#[test]
fn j90_2_an_import_cycle_imports_from_either_side() {
    let a = include_str!("fixtures/j90_cycle_a.ts");
    let b = include_str!("fixtures/j90_cycle_b.ts");
    let modules = compile_package(&[("j90_cycle_a.ts", a), ("j90_cycle_b.ts", b)]);
    let code = |stem: &str| -> &str { &modules.iter().find(|m| m.py_module == stem).unwrap().code };
    assert!(
        code("j90_cycle_a").ends_with(
            "# Imported last: these modules import this one back (an import cycle).\nfrom .j90_cycle_b import twice  # noqa: E402\n"
        ),
        "{}",
        code("j90_cycle_a")
    );
    assert!(
        code("j90_cycle_b")
            .ends_with("from .j90_cycle_a import BASE, Counter, down  # noqa: E402\n"),
        "{}",
        code("j90_cycle_b")
    );
    // Neither names the other at its top, where the cycle could find it half-built.
    assert!(!code("j90_cycle_a").contains("\nfrom .j90_cycle_b import twice\n"));
    let dir = scratch("j90-2-cycle");
    package(&dir, &modules);
    for first in ["j90_cycle_a", "j90_cycle_b"] {
        let script = format!(
            "import json, sys\nsys.path.insert(0, sys.argv[1])\nimport pkg.{first}\nfrom pkg import j90_cycle_a as a, j90_cycle_b as b\nprint(json.dumps([a.down(0), a.down(1), a.down(5), b.twice(4), b.twice(7)], separators=(',', ':')))\n"
        );
        let out = run_python(&script, &[&dir]);
        assert_eq!(out.trim(), NODE_CYCLE, "importing {first} first");
    }
    std::fs::remove_dir_all(&dir).unwrap();
}

/// J90-2: what an import cycle may not do, refused at compile time: read a name of the cycle while
/// the module itself is executed (a module-level initializer), when the other module may not have
/// bound it yet. A base class is read then too, but a compiled class imported from another module is
/// never one (`extends` takes `Error` and the Error classes declared here or by an adapter), so that
/// stays the refusal it was. A module outside the cycle importing it is untouched.
#[test]
fn j90_2_an_import_cycle_refuses_a_name_read_at_import() {
    let a = "import { twice } from './b.js';\nexport const BASE = 10;\nexport function down(n: number): number {\n  return twice(n);\n}\n";
    let b_eager = "import { BASE, down } from './a.js';\nexport const LIMIT = BASE + 1;\nexport function twice(n: number): number {\n  return n > 0 ? down(n - 1) : LIMIT;\n}\n";
    let lines = refusals(&[("a.ts", a), ("b.ts", b_eager)]);
    assert!(
        lines.contains(
            &"b.ts:2:14: unsupported module-level use of BASE, imported in an import cycle: LIMIT = BASE + 1"
                .to_string()
        ),
        "{lines:?}"
    );
    let a_err = "import { twice } from './b.js';\nexport class Bad extends Error {}\nexport function down(n: number): number {\n  return twice(n);\n}\n";
    let b_extends = "import { Bad, down } from './a.js';\nexport class Worse extends Bad {}\nexport function twice(n: number): number {\n  return n > 0 ? down(n - 1) : 0;\n}\n";
    let lines = refusals(&[("a.ts", a_err), ("b.ts", b_extends)]);
    assert!(
        lines.contains(
            &"b.ts:2:28: unsupported extends anything but an Error class: Bad".to_string()
        ),
        "{lines:?}"
    );
    // The same reads from a module the cycle does not reach are ordinary top imports.
    let b_lazy = "import { BASE, down } from './a.js';\nexport function twice(n: number): number {\n  return n > 0 ? down(n - 1) : BASE;\n}\n";
    let outside = "import { BASE } from './a.js';\nexport const TOP = BASE + 1;\n";
    let modules = compile_package(&[("a.ts", a), ("b.ts", b_lazy), ("c.ts", outside)]);
    let c = &modules.iter().find(|m| m.py_module == "c").unwrap().code;
    assert!(
        c.contains("\nfrom .a import BASE\n") && !c.contains("E402"),
        "{c}"
    );
}

/// J90-2: `delete` is a method name, so reading it as a value stays refused (J86-R finding 3), and
/// called on anything but a Map or a Set it raises at run time (`_js_outside`).
#[test]
fn j90_2_delete_is_a_map_or_set_method_only() {
    let lines = refusals(&[(
        "t.ts",
        "export function f(m: Map<string, number>): unknown {\n  return m.delete;\n}\n",
    )]);
    assert!(
        lines.contains(&"t.ts:2:10: unsupported method .delete read as a value (a method may only be called directly): m.delete".to_string()),
        "{lines:?}"
    );
    let modules = compile_package(&[(
        "t.ts",
        "export function f(m: unknown): unknown {\n  return (m as Map<string, number>).delete('a');\n}\n",
    )]);
    let dir = scratch("j90-2-delete");
    package(&dir, &modules);
    let out = run_python(
        "import sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import t\ntry:\n    t.f({'a': 1})\nexcept TypeError as e:\n    print(e)\n",
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(out.trim(), "ts2py: .delete() on dict is outside the subset");
}
