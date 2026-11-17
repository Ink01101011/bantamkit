//! J87-3 (#316 G1): the constructs `pricing.ts` and `jobbudget.ts` needed (`**` of literals,
//! `Number.MAX_SAFE_INTEGER`, one optional member read, `try` / `catch`, a C-style `for`,
//! `splice`, `reduce`, `Number.isFinite`, `Math.trunc`, `Math.min(...xs)`, `JSON.parse`), the fs
//! adapters' error shape, and the two real modules compiled together through the adapter seam.
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

/// A package holding the runtime, the adapters and `modules`, importable as `pkg`.
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

fn compile_package(sources: &[(&str, &str)]) -> Vec<ts2py::Compiled> {
    let options = ts2py::Options {
        runtime_module: Some("._ts2py_runtime".to_string()),
        ..ts2py_bantamkit::options()
    };
    ts2py::compile_modules(sources, &options)
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")))
}

const PRINT: &str = r#"
def node_json(m, value):
    out = m._js_json_stringify(value)
    return "".join(c if ord(c) < 0x7F else "\\u%04x" % ord(c) for c in m._js_code_units(out))
"#;

#[test]
fn g1_constructs_answer_like_node() {
    let source = include_str!("fixtures/j87_g1_probe.ts");
    let module = ts2py::compile(source, "j87_g1_probe.ts", &ts2py_bantamkit::options())
        .unwrap_or_else(|lines| panic!("probe refused:\n{}", lines.join("\n")));
    // The lowerings themselves: a folded power, the constant, the optional read, the catch.
    assert!(
        module.contains("BIG: _JsAny = 9007199254740992\n"),
        "{module}"
    );
    assert!(module.contains("MAX: _JsAny = 9007199254740991\n"));
    assert!(module.contains("_js_opt_get(o, k)"));
    assert!(module.contains("except Exception as _js_error"));
    assert!(module.contains("= _js_catch(_js_error"));
    let dir = scratch("j87-probe");
    let path = dir.join("probe.py");
    std::fs::write(&path, module).unwrap();
    let out = run_python(
        &format!(
            "{PRINT}\nimport importlib.util, sys\nspec = importlib.util.spec_from_file_location('p', sys.argv[1])\nm = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\nprint(node_json(m, m.probe(None)))\n"
        ),
        &[&path],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(
        out.trim_end(),
        r###"[9007199254740992,9007199254740991,1,1000000000000000,"nullish","nullish",1,"nullish",1,"nullish","caught","5","none","swallowed","rethrown",[5,4,3],[1,0],[[1,4,5],[2,3],[1,2],[3],[1,2,3],[],[],[1,2,3]],[10,24,5,"TypeError"],[true,true,false,false,false,false,false],[1,-1,"-Infinity","Infinity","NaN","-Infinity",7,true],[1,9,-1],["3000000","9007199254740992","null","0","{\"a\":3,\"b\":2}","{\"__proto__\":{\"x\":1}}","[1,\"x\",null,true]","{\"k\":[]}","thrown","thrown","thrown","thrown","thrown","thrown","thrown","-Infinity"]]"###
    );
}

const FS_ERRORS: &str = r#"import { readFileSync } from 'node:fs';
export function caught(path: string): string {
  try {
    return readFileSync(path, 'utf8');
  } catch (e) {
    throw e;
  }
}
export function uncaught(path: string): string {
  return readFileSync(path, 'utf8');
}
export function converted(path: string): string {
  try {
    return readFileSync(path, 'utf8');
  } catch {
    return 'caught';
  }
}
export function refusedInside(path: string): string {
  try {
    return readFileSync(path, 'latin1');
  } catch {
    return 'caught';
  }
}
"#;

/// The #315 unknown, "the error shape across the pyfs seam": an fs error raised under a generated
/// `catch` and rethrown, or not caught at all, reaches the Python caller as the very exception
/// CPython's `open()` raises for that path (class, errno, strerror, filename, args, `str`); a
/// `catch` that swallows it answers as Node's does (`converted`, Node: 'caught' for both paths);
/// and a subset refusal raised inside a `try` is not swallowed (Node would have read latin1).
#[test]
fn fs_errors_reach_python_as_cpython_raises_them() {
    let modules = compile_package(&[("runtime-ts/src/fserrors.ts", FS_ERRORS)]);
    let dir = scratch("j87-fs");
    package(&dir, &modules);
    std::fs::create_dir_all(dir.join("a-directory")).unwrap();
    let out = run_python(
        r#"
import sys
sys.path.insert(0, sys.argv[1])
from pkg import fserrors as f
def shape(e):
    return (type(e), e.errno, e.strerror, e.filename, e.args, str(e))
for path in [sys.argv[1] + "/missing.json", sys.argv[1] + "/a-directory"]:
    try:
        open(path, "rb")
    except OSError as e:
        cpython = shape(e)
    for fn in (f.caught, f.uncaught):
        try:
            fn(path)
            print("returned")
        except OSError as e:
            print(type(e).__name__, shape(e) == cpython)
    print(f.converted(path))
try:
    f.refused_inside(sys.argv[1] + "/missing.json")
    print("returned")
except TypeError as e:
    print(str(e))
"#,
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let directory = if cfg!(windows) {
        "PermissionError"
    } else {
        "IsADirectoryError"
    };
    assert_eq!(
        out,
        format!(
            "FileNotFoundError True\nFileNotFoundError True\ncaught\n{directory} True\n{directory} True\ncaught\nts2py: fs.readFileSync with an encoding but 'utf8' is outside the subset\n"
        )
    );
}

/// `runtime-ts/src/pricing.ts` and `jobbudget.ts` compiled together (`pyRepr`, `cmpCodepoint`,
/// `assetsRoot`, `BantamError`, `existsSync`, `readFileSync`, `path.join` and `process.env`
/// through the adapter seam): a budget view and its refusals, a validated table, two prices, three
/// table faults (one where `.sort()` and code-point order name different offenders), two amounts and
/// a missing table. The expected line is Node's `JSON.stringify` of the same calls.
#[test]
fn g1_modules_compile_and_answer_like_node() {
    let root = repo_root();
    let paths = ["runtime-ts/src/pricing.ts", "runtime-ts/src/jobbudget.ts"];
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
    assert!(modules[0].code.contains(
        "from ._ts2py_adapters import assets_root, BantamError, cmp_codepoint, exists_sync, path_join, process_env, py_repr, read_file_sync\n"
    ));
    assert!(
        modules[0]
            .code
            .contains("class PriceTableError(BantamError):\n")
    );
    let dir = scratch("j87-g1");
    package(&dir, &modules);
    let out = run_python(
        &format!(
            r#"{PRINT}
import sys
sys.path.insert(0, sys.argv[1])
from pkg import _ts2py_runtime as rt, jobbudget as jb, pricing as pr
out = []
lines = [{{"unit": "U1", "tokens": 5}}, {{"unit": "U2", "tokens": 9, "duration_ms": 100}}, {{"event": "uncommitted", "unit": "U2"}}, {{"unit": "U3", "tokens": 1e20}}]
view = jb.budget(lines, {{"tokens": 20, "units": 3}}, 1)
out += [view, jb.refusal(view), jb.refusal(jb.budget([], {{"units": 1}}, 1))]
good = '{{"schema_version": 1, "currency": "USD", "unit": "micro_usd_per_million_tokens", "rates": {{"m": {{"recorded": "2026-09-11", "source": "s", "input_tokens": 3000000.0, "output_tokens": 15000000}}}}}}'
t = pr.validate_price_table(pr.decode_price_json(good))
out += [t, pr.price_tokens(t, "m", {{"input_tokens": 1234, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 7}})]
out.append(pr.price_tokens(t, "m", {{"input_tokens": 1, "cache_creation_input_tokens": 2, "cache_read_input_tokens": 0, "output_tokens": 0}}))
for bad in ['{{"schema_version": 1, "currency": "USD", "unit": "micro_usd_per_million_tokens", "rates": {{"\U0001F414": {{"recorded": "2026-09-11", "source": "s"}}, "！": {{"recorded": "x", "source": "s", "input_tokens": 1}}}}}}', '[]', '{{"zeta": 1, "alpha": 2}}']:
    try:
        pr.validate_price_table(pr.decode_price_json(bad))
        out.append("ok")
    except pr.PriceTableError as e:
        out.append(e.name + ": " + str(e))
out += [pr.format_micros(1234567), pr.format_micros(9007199254740991)]
try:
    pr.load_price_table("/nonexistent/prices.json")
except pr.PriceTableError as e:
    out.append(e.name + ": " + str(e))
print(node_json(rt, out))
"#
        ),
        &[&dir],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(
        out.trim_end(),
        r###"[{"limit":{"tokens":20,"units":3},"spent":{"tokens":100000000000000000000,"units":2,"wallclock_ms":0},"in_flight":1,"remaining":{"tokens":-100000000000000000000,"units":0},"per_unit":5,"affordable":0},"budget tokens spent: 100000000000000000000 of 20; raise job.budget or stop the job","budget units spent: 1 of 1; raise job.budget or stop the job",{"schema_version":1,"currency":"USD","unit":"micro_usd_per_million_tokens","rates":{"m":{"recorded":"2026-09-11","source":"s","input_tokens":3000000,"output_tokens":15000000}}},{"model":"m","currency":"USD","micros":3807,"amount":"0.003807","breakdown":{"input_tokens":3702,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":105},"rate":{"recorded":"2026-09-11","source":"s","input_tokens":3000000,"output_tokens":15000000}},{"unavailable":"rate for model 'm' does not price 'cache_creation_input_tokens', and 2 such tokens were used -- a missing rate is not a zero"},"PriceTableError: price table rate '\uff01' has a 'recorded' that is not a YYYY-MM-DD date","PriceTableError: price table must be a JSON object","PriceTableError: price table has unknown key 'alpha'","1.234567","9007199254.740991","PriceTableError: price table not found: /nonexistent/prices.json"]"###
    );
}

/// J87-3F: `Object.hasOwn` and `Object.fromEntries`, the own-key primitives `pricing.ts` looks a
/// model up and builds its rates with. A `__proto__` key is own and inherited names are not.
const OWN_KEYS: &str = r#"export function probe(input: unknown): unknown[] {
  const proto = JSON.parse('{"__proto__":{"x":1},"a":2}') as Record<string, unknown>;
  const owns = ['__proto__', 'a', 'x', 'toString', 'constructor', 'hasOwnProperty', 'valueOf'].map((k) => Object.hasOwn(proto, k));
  const arr = [Object.hasOwn([5, 6], '0'), Object.hasOwn([5, 6], '2'), Object.hasOwn([5, 6], 'length'), Object.hasOwn([5, 6], 'map'), Object.hasOwn('ab', '1'), Object.hasOwn('ab', 'length'), Object.hasOwn(7 as any, 'toFixed'), Object.hasOwn(JSON.parse('{"1":"x"}'), 1 as any)];
  let thrown = 'none';
  try {
    Object.hasOwn(null as any, 'a');
  } catch {
    thrown = 'thrown';
  }
  const built = Object.fromEntries([['b', 1], ['__proto__', 2], ['10', 3], ['b', 4], ['c']] as unknown[][]);
  const made = [JSON.stringify(built), Object.keys(built).join(','), Object.hasOwn(built, '__proto__'), Object.getPrototypeOf(built) === Object.prototype, built['c'] === undefined, Object.hasOwn(built, 'c')];
  return [owns, arr, thrown, made, JSON.stringify(Object.fromEntries([]))];
}
"#;

#[test]
fn own_key_builtins_answer_like_node() {
    let module = ts2py::compile(OWN_KEYS, "own_keys.ts", &ts2py_bantamkit::options())
        .unwrap_or_else(|lines| panic!("probe refused:\n{}", lines.join("\n")));
    assert!(module.contains("_js_object_has_own(proto, k)"), "{module}");
    assert!(module.contains("_js_object_from_entries("), "{module}");
    let dir = scratch("j87-own-keys");
    let path = dir.join("probe.py");
    std::fs::write(&path, module).unwrap();
    let out = run_python(
        &format!(
            "{PRINT}\nimport importlib.util, sys\nspec = importlib.util.spec_from_file_location('p', sys.argv[1])\nm = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\nprint(node_json(m, m.probe(None)))\n"
        ),
        &[&path],
    );
    std::fs::remove_dir_all(&dir).unwrap();
    // What Node v26 printed for the same TypeScript.
    assert_eq!(
        out.trim_end(),
        r###"[[true,true,false,false,false,false,false],[true,false,true,false,true,true,false,true],"thrown",["{\"10\":3,\"b\":4,\"__proto__\":2}","10,b,__proto__,c",true,true,true,true],"{}"]"###
    );
}
