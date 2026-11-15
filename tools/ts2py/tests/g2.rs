//! J88-2 (#316 G2): the constructs `eventlog.ts`, `tokenledger.ts` and `storage/logsegment.ts`
//! needed (`<<`, `JSON.stringify` with a replacer and a space, `JSON.parse` past the recursion
//! limit, `new Date(ms).toISOString()`, `trim`, `endsWith`, non-ASCII `toLowerCase`, Buffers,
//! `TextDecoder` with `fatal`/`ignoreBOM`, `finally`, an arrow used as a value, compound property
//! assignment, a function-valued field called as `this.f()`, a static method, `Object.assign`,
//! `.constructor.name`, a catch binding read, `Map.values()`), the `node:fs` / `node:path` /
//! `node:zlib` adapters against a real directory, and the five G1+G2 modules compiled together.
//! Every expected value is what Node v26.13.0 printed for the same TypeScript.

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

fn compile_package(sources: &[(&str, &str)]) -> Vec<ts2py::Compiled> {
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py::Options::default()
    };
    ts2py::compile_modules(sources, &options)
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")))
}

/// `JSON.stringify(value)` with every code unit at or above 0x7F written `\uXXXX`, so a literal
/// below can hold Node's line in ASCII.
const PRINT: &str = r#"
def node_json(m, value):
    out = m._js_json_stringify(value)
    return "".join(c if ord(c) < 0x7F else "\\u%04x" % ord(c) for c in m._js_code_units(out))
"#;

#[test]
fn g2_constructs_answer_like_node() {
    let source = include_str!("fixtures/j88_g2_probe.ts");
    let modules = compile_package(&[("j88_g2_probe.ts", source)]);
    let code = &modules[0].code;
    // The lowerings themselves.
    assert!(code.contains("SHIFTED = 1048576\n"), "{code}");
    assert!(code.contains("_js_json_stringify_with(doc, None, 2)"));
    assert!(code.contains("_js_date_to_iso(ms)"));
    assert!(code.contains("    finally:\n"));
    assert!(code.contains("@staticmethod"));
    assert!(code.contains("nonlocal count"));
    let dir = scratch("j88-probe");
    package(&dir, &modules);
    let out = run_python(
        &format!(
            "{PRINT}\nimport sys\nsys.path.insert(0, sys.argv[1])\nfrom pkg import _ts2py_runtime as rt, j88_g2_probe as m\nprint(node_json(rt, m.probe()))\n"
        ),
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(
        out.trim_end(),
        r###"[1048576,["{\n  \"2\": [\n    1,\n    {\n      \"x\": null\n    },\n    []\n  ],\n  \"10\": \"ten\",\n  \"b\": 1,\n  \"a\": {},\n  \"s\": \"\u00e9\u2028\"\n}","{\n--\"2\": [\n----1,\n----{\n------\"x\": null\n----},\n----[]\n--],\n--\"10\": \"ten\",\n--\"b\": 1,\n--\"a\": {},\n--\"s\": \"\u00e9\u2028\"\n}","[]","{\n \"k\": []\n}","{\"2\":[1,{\"x\":null},[]],\"10\":\"ten\",\"b\":1,\"a\":{},\"s\":\"\u00e9\u2028\"}","RangeError","{\n  \"v\": 1\n}","{\n  \"s\": \"x\\ud800y\"\n}"],[50000,7,"SyntaxError","object"],["1970-01-01T00:00:00.000Z","1969-12-31T23:59:59.999Z","1969-12-31T23:59:59.999Z","1970-01-01T00:00:00.001Z","+010000-01-01T00:00:00.000Z","0000-12-31T23:59:59.999Z","+275760-09-13T00:00:00.000Z","-271821-04-20T00:00:00.000Z","-000001-01-01T00:00:00.000Z","RangeError","RangeError","RangeError"],["x","\u001cx\u0085",true,false,true,"\u00e0\u00e9\u00ee i\u0307 \u00df","on"],[10,"68c3a9f09f9880efbfbd","68c3a9f09f9880efbfbdc3a900",2,169,104,true,"h\u00e9\ud83d\ude00\ufffd","\u00ff\u00fe"],[2,1,"ok","\ud83d\ude00",true],["returned","done",["body","finally","inner finally","caught","outer finally"]],[15,[5],[true,true],{"requests":2},[3,5,7],[1,2]],[42,["Object","Array","Named","TypeError","Error"],"EIO","object",[1,2]]]"###
    );
}

/// The `node:fs`, `node:path` and `node:zlib` adapters and the strict TextDecoder on a real
/// directory (a file, a directory, a symlink to one, invalid UTF-8), against Node's answers for the
/// same calls; and an uncaught fs error reaching Python as the OSError CPython's `os.stat` raises.
const FS_PROBE: &str = r#"import * as fs from 'node:fs';
import * as path from 'node:path';
import * as zlib from 'node:zlib';
import { lstatSync, readdirSync, statSync } from 'node:fs';

function code(fn: () => unknown): unknown {
  try {
    const v = fn();
    return v === undefined ? 'ok' : v;
  } catch (e) {
    return (e as { code?: unknown }).code ?? 'no code';
  }
}

export function probe(root: string): unknown[] {
  const at = (name: string): string => path.join(root, name);
  const out: unknown[] = [];
  fs.mkdirSync(at('d/e'), { recursive: true });
  out.push(code(() => fs.mkdirSync(at('d/e'), { recursive: true })));
  const fd = fs.openSync(at('f.bin'), 'wx');
  out.push(fs.writeSync(fd, Buffer.from('hello\n', 'utf8')));
  fs.closeSync(fd);
  out.push(code(() => fs.openSync(at('f.bin'), 'wx')));
  out.push(code(() => fs.mkdirSync(at('f.bin/x'), { recursive: true })));
  out.push(code(() => fs.mkdirSync(at('f.bin'), { recursive: true })));
  fs.appendFileSync(at('f.bin'), Buffer.from('more', 'utf8'));
  const st = statSync(at('f.bin'));
  out.push([st.size, st.isDirectory(), st.isFile(), typeof st.mtimeMs, statSync(at('d')).isDirectory()]);
  const rfd = fs.openSync(at('f.bin'), 'a+');
  const one = Buffer.alloc(1);
  out.push([fs.fstatSync(rfd).size, fs.readSync(rfd, one, 0, 1, 4), one[0], fs.readSync(rfd, Buffer.alloc(4), 0, 4, 99)]);
  fs.closeSync(rfd);
  out.push(fs.readFileSync(at('f.bin')).toString('hex'));
  fs.linkSync(at('f.bin'), at('g.bin'));
  out.push(code(() => fs.linkSync(at('f.bin'), at('g.bin'))));
  fs.renameSync(at('g.bin'), at('h.bin'));
  out.push(readdirSync(root).sort());
  out.push(code(() => fs.rmSync(at('missing'), { force: true })));
  out.push(code(() => fs.rmSync(at('d'), { force: true })) !== 'ok');
  fs.rmSync(at('h.bin'), { force: true });
  out.push([fs.existsSync(at('h.bin')), fs.existsSync(at('f.bin')), fs.existsSync(`${root}\0x`)]);
  out.push([code(() => statSync(at('missing'))), code(() => statSync(at('f.bin/x'))), code(() => readdirSync(at('f.bin')))]);
  out.push(code(() => fs.readFileSync(at('d'))));
  out.push(code(() => statSync(`${root}\0x`)));
  out.push(lstatSync(at('lnk')).isSymbolicLink());
  out.push(statSync(at('lnk')).isDirectory());
  out.push(lstatSync(at('d')).isSymbolicLink());
  const gz = zlib.gzipSync(Buffer.from('a line\n', 'utf8'));
  out.push([zlib.gunzipSync(gz).toString('utf8'), code(() => zlib.gunzipSync(Buffer.alloc(0))), code(() => zlib.gunzipSync(Buffer.from('plain', 'utf8')))]);
  const strict = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
  out.push(code(() => strict.decode(fs.readFileSync(at('bad.txt')))));
  out.push(new TextDecoder('utf-8').decode(fs.readFileSync(at('bad.txt'))).length);
  return out;
}

export function names(): unknown[] {
  const samples = ['', '/', '//', '///', 'a', 'a/', '/a', '/a/', 'a/b', 'a//b//', '/a/b/c', '.', '..', './a', 'a/./b', '//a', 'C:\\x\\y'];
  return samples.map((p) => [path.dirname(p), path.basename(p)]);
}

export function uncaught(p: string): unknown {
  return statSync(p).size;
}
"#;

#[cfg(unix)]
#[test]
fn g2_fs_adapters_answer_like_node() {
    let modules = compile_package(&[("fsprobe.ts", FS_PROBE)]);
    let dir = scratch("j88-fs");
    package(&dir, &modules);
    let root = dir.join("root");
    std::fs::create_dir_all(root.join("target")).unwrap();
    std::fs::write(root.join("bad.txt"), b"ok\xff\xfe\n").unwrap();
    std::os::unix::fs::symlink("target", root.join("lnk")).unwrap();
    let out = run_python(
        &format!(
            r#"{PRINT}
import os, sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_runtime as rt, fsprobe as f
print(node_json(rt, [f.probe(sys.argv[2]), f.names()]))
missing = os.path.join(sys.argv[2], "missing")
try:
    os.stat(missing)
except OSError as e:
    cpython = (type(e), e.errno, e.strerror, e.filename, e.args, str(e))
try:
    f.uncaught(missing)
except OSError as e:
    print((type(e), e.errno, e.strerror, e.filename, e.args, str(e)) == cpython, type(e).__name__)
"#
        ),
        &[&dir, &root],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(
        out,
        concat!(
            r###"[["ok",6,"EEXIST","ENOTDIR","EEXIST",[10,false,true,"number",true],[10,1,111,0],"68656c6c6f0a6d6f7265","EEXIST",["bad.txt","d","f.bin","h.bin","lnk","target"],"ok",true,[false,true,false],["ENOENT","ENOTDIR","ENOTDIR"],"EISDIR","ERR_INVALID_ARG_VALUE",true,true,false,["a line\n","Z_BUF_ERROR","Z_DATA_ERROR"],"ERR_ENCODING_INVALID_ENCODED_DATA",5],[[".",""],["/",""],["/",""],["/",""],[".","a"],[".","a"],["/","a"],["/","a"],["a","b"],["a/","b"],["/a/b","c"],[".","."],[".",".."],[".","a"],["a/.","b"],["//","a"],[".","C:\\x\\y"]]]"###,
            "\nTrue FileNotFoundError\n"
        )
    );
}

/// The five #316 modules in one ts2py call (G1's pricing and jobbudget, G2's log segment, event
/// log and token ledger), every import resolved: the compiled modules import each other, and every
/// other name comes through the adapter seam. Their behaviour is the conformance suites' (`eventlog`,
/// `tokenledger`, `storage-log`, `pricing`, `jobbudget`), which run them inside `bantamkit`.
#[test]
fn g2_modules_compile_together() {
    let root = repo_root();
    let paths = [
        "runtime-ts/src/pricing.ts",
        "runtime-ts/src/jobbudget.ts",
        "runtime-ts/src/storage/logsegment.ts",
        "runtime-ts/src/eventlog.ts",
        "runtime-ts/src/tokenledger.ts",
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
    let code = |stem: &str| -> &str { &modules.iter().find(|m| m.py_module == stem).unwrap().code };
    assert!(code("eventlog").contains("from .logsegment import LogSegment\n"));
    assert!(code("tokenledger").contains("from .pricing import "));
    assert!(code("logsegment").contains("exclusive(self.path, _js_fn"));
    assert!(code("tokenledger").contains("class TokenLedgerError(BantamError):\n"));
}
