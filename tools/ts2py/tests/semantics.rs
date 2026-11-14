//! The JS semantics SUBSET.md promises, checked by running generated code under Python.
//! Each expected value is what Node prints for the same expression.

use std::process::Command;

const PROBE: &str = r#"
export function probe(input: any): unknown[] {
  const m = new Map<unknown, string>();
  m.set(1, 'one');
  m.set(true, 'true');
  m.set('b', 'b');
  m.set(1, 'uno');
  const s = new Set<unknown>(['z', 'a', 'z']);
  const rows = [{ k: 1, v: 'a' }, { k: 0, v: 'b' }, { k: 1, v: 'c' }, { k: 0, v: 'd' }];
  rows.sort((x, y) => x.k - y.k);
  return [
    typeof input.flag === 'number',
    typeof input.n === 'number',
    Number.isInteger(input.f),
    Number.isInteger(input.flag),
    input.flag === 1,
    input.missing == null,
    input.nil == null,
    input.missing === null,
    input.missing === undefined,
    input['missing'] ?? 'dflt',
    [1, 2].find((x) => x > 5) === undefined,
    [...m].map((e) => e[1]).join(','),
    [...s].join(','),
    rows.map((r) => r.v).join(''),
    `${input.f}|${input.n}|${input.flag}|${input.nil}|${0.1}|${input.big}|${input.tiny}`,
    JSON.stringify(input.obj),
    !input.emptyList,
    input.zero || 'fallback',
    'a' + 1,
    [3, 1, 10, 2].sort().join(','),
  ];
}
"#;

#[test]
fn js_semantics_hold_under_python() {
    let module = ts2py::compile(PROBE, "probe.ts", &ts2py::Options::default())
        .unwrap_or_else(|lines| panic!("probe refused:\n{}", lines.join("\n")));
    let dir = std::env::temp_dir().join(format!("ts2py-sem-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("probe.py");
    std::fs::write(&path, module).unwrap();
    let driver = r#"
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("p", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
data = {"flag": True, "n": 3.0, "f": 3.0, "nil": None, "big": 1e21, "tiny": 1e-7,
        "obj": {"b": [1, 2.5, "é"], "1": None, "a": {"x": 3.0}}, "emptyList": [], "zero": 0}
print(json.dumps(m.probe(data), ensure_ascii=False, separators=(",", ":")))
"#;
    let python = std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let run = match Command::new(&python)
        .arg("-c")
        .arg(driver)
        .arg(&path)
        .output()
    {
        Ok(run) => run,
        Err(err) => {
            eprintln!("skipping: cannot run {python}: {err}");
            return;
        }
    };
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    let expected = concat!(
        r#"[false,true,true,false,false,true,true,false,true,"dflt",true,"uno,true,b","z,a","bdac","#,
        r#""3|3|true|null|0.1|1e+21|1e-7","{\"1\":null,\"b\":[1,2.5,\"é\"],\"a\":{\"x\":3}}",false,"fallback","a1","1,10,2,3"]"#,
    );
    assert_eq!(String::from_utf8(run.stdout).unwrap().trim_end(), expected);
}

#[test]
fn type_only_syntax_is_erased() {
    let source = r#"
export interface Box<T> { readonly value: T; }
type Pair = readonly [string, number];
export function first<T>(xs: readonly T[], fallback?: T): T | undefined {
  const head = xs[0] as T | undefined;
  const conf = { k: 1 } satisfies Record<string, number>;
  return (head ?? fallback)! ?? (conf as unknown as T);
}
"#;
    let module = ts2py::compile(source, "erase.ts", &ts2py::Options::default())
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    let body = module.split("__all__").nth(1).unwrap();
    assert_eq!(
        body,
        concat!(
            " = [\"first\"]\n\n\n",
            "def first(xs, fallback=_JS_UNDEFINED):\n",
            "    head = _js_get(xs, 0)\n",
            "    conf = {\"k\": 1}\n",
            "    return _js_coalesce_value(_js_coalesce_value(head, fallback), conf)\n",
        )
    );
}

#[test]
fn emit_runtime_writes_the_support_module() {
    let path = std::env::temp_dir().join(format!("ts2py-rt-{}.py", std::process::id()));
    let status = Command::new(env!("CARGO_BIN_EXE_ts2py"))
        .arg("--emit-runtime")
        .arg(&path)
        .status()
        .unwrap();
    assert!(status.success());
    assert_eq!(std::fs::read_to_string(&path).unwrap(), ts2py::RUNTIME);
    std::fs::remove_file(&path).unwrap();
}
