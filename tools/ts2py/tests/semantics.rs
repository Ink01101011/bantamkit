//! The JS semantics SUBSET.md promises, checked by running generated code under Python.
//! Each expected value is what Node prints for the same expression.

use std::process::Command;

/// J85-R2 L2: these tests are the gate, so an interpreter that cannot be started is a failure,
/// never a silent pass. `TS2PY_PYTHON` picks the interpreter; default `python3`.
fn python_missing(python: &str, err: &std::io::Error) -> String {
    format!(
        "cannot run {python}: {err}; this test runs the generated module under Python and fails without one (set TS2PY_PYTHON to an interpreter)"
    )
}

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
    let run = Command::new(&python)
        .arg("-c")
        .arg(driver)
        .arg(&path)
        .output()
        .unwrap_or_else(|err| panic!("{}", python_missing(&python, &err)));
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

/// Numbers are JS doubles (SUBSET.md, Numbers): an int beyond 2^53 from the input rounds the way
/// `JSON.parse` would round it, in arithmetic, comparison, a sort comparator and stringify; a small
/// int still prints without `.0`. The expected line is Node's output for the same function and
/// the same JSON text.
const NUMBERS: &str = r#"
export function numbers(input: any): string {
  const rows = [{ id: 'a', p: input.lo }, { id: 'b', p: input.hi }];
  rows.sort((x, y) => y.p - x.p);
  return JSON.stringify([
    rows.map((r) => r.id).join(','),
    input.hi - input.lo,
    input.hi === input.lo,
    input.hi > input.lo,
    input.hi <= input.lo,
    -input.hi,
    input.lo + 1,
    input.lo + 1 === input.lo,
    input.big,
    `${input.big}|${input.hi}|${input.small - 1}|${-input.small}`,
    [input.small, input.small - 1, -input.small, input.small + 2, input.small + 0.5],
    input.huge,
    input.huge > input.big,
  ]);
}
"#;

#[test]
fn numbers_beyond_2_pow_53_behave_as_js_doubles() {
    let module = ts2py::compile(NUMBERS, "numbers.ts", &ts2py::Options::default())
        .unwrap_or_else(|lines| panic!("numbers probe refused:\n{}", lines.join("\n")));
    let dir = std::env::temp_dir().join(format!("ts2py-num-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("numbers.py");
    std::fs::write(&path, module).unwrap();
    let driver = r#"
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("n", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
data = json.loads('{"lo": 9007199254740992, "hi": 9007199254740993, "big": 12345678901234567890, "small": 3, "huge": 1' + '0' * 400 + '}')
print(m.numbers(data))
"#;
    let python = std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let run = Command::new(&python)
        .arg("-c")
        .arg(driver)
        .arg(&path)
        .output()
        .unwrap_or_else(|err| panic!("{}", python_missing(&python, &err)));
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    let expected = concat!(
        r#"["a,b",0,true,false,true,-9007199254740992,9007199254740992,true,12345678901234567000,"#,
        r#""12345678901234567000|9007199254740992|2|-3",[3,2,-3,5,3.5],null,true]"#,
    );
    assert_eq!(String::from_utf8(run.stdout).unwrap().trim_end(), expected);
}

/// J85-R F1, F2 and F3: the three places where the generated code used to answer differently from
/// JS without a word. Relational operators on strings compare UTF-16 code units, not code points
/// (`'\uffff' < '😀'` is false in JS), and on anything but two numbers go through ToPrimitive and
/// ToNumber; a regex without the `u` flag matches one code unit per `.`; and an int past the
/// double range is not `Number.isInteger`. The expected line is what Node prints for the same
/// function on the same input (`huge` is `JSON.parse('1' + '0'.repeat(400))`, i.e. Infinity).
const UNITS: &str = r#"
function lt(a: any, b: any): boolean {
  return a < b;
}
export function units(input: any): string {
  const xs = ['😀', '\uffff', 'a'];
  xs.sort((x, y) => (x < y ? -1 : x > y ? 1 : 0));
  return JSON.stringify([
    lt('\uffff', '😀'),
    '\uffff' < '😀', '\uffff' <= '😀', '\uffff' > '😀', '\uffff' >= '😀',
    xs.join(','),
    input.s < input.t, input.s > input.t,
    '10' < 9, '10' < '9', null < 1, undefined < 1, undefined <= 1, undefined >= 1,
    'a' < 1, 'a' >= 1, [2] > 1, ' 12 ' > 11, '0x10' > 15, true > 0, '' < 1, 'Infinity' > 1e300,
    input.n <= input.n, input.nil >= 0, input.obj < 'b', input.list > '1,1',
    Number.isInteger(input.huge), Number.isInteger(input.n),
    /^a.b$/.test('a😀b'), /^a..b$/.test('a😀b'), /^[^x]$/.test('😀'), /^😀$/.test('😀'),
    /^[😀]$/.test('😀'), /^[😀]+$/.test('😀'), /^a.b$/.test(input.astral), /^.$/.test('\uffff'),
  ]);
}
"#;

#[test]
fn strings_and_regexes_compare_utf16_code_units_as_js_does() {
    let module = ts2py::compile(UNITS, "units.ts", &ts2py::Options::default())
        .unwrap_or_else(|lines| panic!("units probe refused:\n{}", lines.join("\n")));
    let dir = std::env::temp_dir().join(format!("ts2py-units-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("units.py");
    std::fs::write(&path, module).unwrap();
    let driver = r#"
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("u", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
data = json.loads('{"s": "\\uffff", "t": "\\ud83d\\ude00", "n": 3, "nil": null, "obj": {}, "list": [1, 2], "astral": "a\\ud835\\udd18b", "huge": 1' + '0' * 400 + '}')
sys.stdout.reconfigure(encoding="utf-8")
print(m.units(data))
"#;
    let python = std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let run = Command::new(&python)
        .arg("-c")
        .arg(driver)
        .arg(&path)
        .output()
        .unwrap_or_else(|err| panic!("{}", python_missing(&python, &err)));
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    let expected = concat!(
        r#"[false,false,false,true,true,"a,😀,"#,
        "\u{ffff}",
        r#"",false,true,false,true,true,false,false,false,"#,
        r#"false,false,true,true,true,true,true,true,true,true,true,true,false,true,"#,
        r#"false,true,false,true,false,true,false,true]"#,
    );
    assert_eq!(String::from_utf8(run.stdout).unwrap().trim_end(), expected);
}

/// J85-R2 L1: `.length` and `.size` are known numbers only on a receiver known to be a string.
/// On anything else the property is whatever the object holds, so a plain object whose `length`
/// is a string, or `true`, compares, adds and equals as JS does instead of as Python's `<`, `+`
/// and `==` would (`'￿' < '😀'` by code unit, `true !== 1`, `'2' + 1`). The expected line is
/// what Node prints for the same function on the same input.
const LENGTHS: &str = r#"
export function lengths(input: any): string {
  const a = input.a;
  const b = input.b;
  return JSON.stringify([
    a.length < b.length, a.length <= b.length, a.length > b.length, a.length >= b.length,
    input.t.length === 1, input.t.length !== 1, input.a.length + 1,
    input.s.size < 10, input.s.size === 2, input.s.size + 1,
    input.xs.length < input.str.length, input.xs.length === 3, 'ab'.length < input.str.length,
    input.str.length - 1,
  ]);
}
"#;

#[test]
fn length_of_a_plain_object_is_not_assumed_numeric() {
    let module = ts2py::compile(LENGTHS, "lengths.ts", &ts2py::Options::default())
        .unwrap_or_else(|lines| panic!("lengths probe refused:\n{}", lines.join("\n")));
    // A string's length is still a known number, so it keeps the plain operator.
    let fast = ts2py::compile(
        "export function k(): boolean {\n  return 'ab'.length < 3;\n}\n",
        "k.ts",
        &ts2py::Options::default(),
    )
    .unwrap_or_else(|lines| panic!("{}", lines.join("\n")));
    assert!(
        fast.contains("return _js_len(\"ab\") < 3\n"),
        "the string-receiver fast path is gone:\n{fast}"
    );
    let dir = std::env::temp_dir().join(format!("ts2py-lengths-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("lengths.py");
    std::fs::write(&path, module).unwrap();
    let driver = r#"
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("l", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
data = json.loads('{"a": {"length": "\\uffff"}, "b": {"length": "\\ud83d\\ude00"}, "t": {"length": true}, "s": {"size": "2"}, "xs": [1, 2, 3], "str": "\\ud83d\\ude00"}')
sys.stdout.reconfigure(encoding="utf-8")
print(m.lengths(data))
"#;
    let python = std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let run = Command::new(&python)
        .arg("-c")
        .arg(driver)
        .arg(&path)
        .output()
        .unwrap_or_else(|err| panic!("{}", python_missing(&python, &err)));
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    let expected = concat!(
        r#"[false,false,true,true,false,true,""#,
        "\u{ffff}",
        r#"1",true,false,"21",false,true,false,1]"#,
    );
    assert_eq!(String::from_utf8(run.stdout).unwrap().trim_end(), expected);
}

/// J85-R2 L3: every pattern ts2py accepts compiles under Python's `re`, so a regex can fail only
/// at compile time, never at import. Checked on hand-picked edge cases plus a deterministic
/// random sweep over the characters the grammar treats specially; the accepted translations are
/// compiled in one Python run. `TS2PY_REGEX_DUMP=<file>` also writes each pattern and whether it
/// its translation (null when refused), one JSON pair per line, for checking against JS by hand.
#[test]
fn every_accepted_regex_compiles_under_python() {
    let mut patterns: Vec<String> = [
        "^[A-Za-z]:",
        "a$",
        "\\d+",
        "^a.b$",
        "😀",
        "[😀]",
        "[^😀]+",
        "[a-z😀]+",
        "(😀|b)+",
        "^a😀?$",
        "[😀-😂]",
        "[z-a]",
        "[a-c-e]",
        "[a-c-]",
        "[-a]",
        "[a-]",
        "[\\b-\\n]",
        "[\\--\\/]",
        "a{2}",
        "a{2,}",
        "a{2,3}?",
        "a{3,2}",
        "(?:a|b)*",
        "(?=a)b",
        "(?!a)*",
        "()*",
        "(|a)+",
        "a|",
        "|",
        "[\\]]",
        "[[]",
        "\\[",
        "a{",
        "}",
        "a**",
        "a*?",
        "a??",
        "^*",
        "\\b+",
        "[\\d-z]",
        "[a-\\d]",
        "[]",
        "[^]",
        "\\s",
        "(?<n>a)",
        "(?<=a)",
        "\\1",
        "\\u0041",
        "\\x41",
        "\\cA",
        "[a&&b]",
        "[a--b]",
        "#",
        " ",
        "(((((a)))))",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    let alphabet: Vec<char> = "ab()[]{}*+?|^$.-\\dwbB2,:=!😀😂z".chars().collect();
    let mut seed: u64 = 0x2545_f491_4f6c_dd1d;
    for _ in 0..20_000 {
        seed = seed.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
        let len = (seed >> 60) as usize + 1;
        let mut p = String::new();
        for _ in 0..len {
            seed = seed.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
            p.push(alphabet[(seed >> 33) as usize % alphabet.len()]);
        }
        patterns.push(p);
    }
    let mut accepted = Vec::new();
    let mut dump = String::new();
    for p in &patterns {
        let result = ts2py::lower::translate_regex(p);
        let shown = match &result {
            Ok(t) => format!("{t:?}"),
            Err(_) => "null".to_string(),
        };
        dump.push_str(&format!("[{p:?}, {shown}]\n"));
        if let Ok(t) = result {
            accepted.push(t);
        }
    }
    if let Ok(file) = std::env::var("TS2PY_REGEX_DUMP") {
        std::fs::write(file, &dump).unwrap();
    }
    assert!(
        accepted.len() > 1000,
        "the sweep accepted only {}",
        accepted.len()
    );
    let dir = std::env::temp_dir().join(format!("ts2py-regex-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("patterns.txt");
    // One translation per line; a translation never holds a raw newline.
    std::fs::write(&path, accepted.join("\n")).unwrap();
    let driver = r#"
import re, sys
bad = []
for p in open(sys.argv[1], encoding="utf-8").read().split("\n"):
    try:
        re.compile(p, re.ASCII)
    except Exception as e:
        bad.append(f"{p!r}: {type(e).__name__}: {e}")
print(len(bad))
print("\n".join(bad[:20]))
"#;
    let python = std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let run = Command::new(&python)
        .arg("-c")
        .arg(driver)
        .arg(&path)
        .output()
        .unwrap_or_else(|err| panic!("{}", python_missing(&python, &err)));
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    let stdout = String::from_utf8(run.stdout).unwrap();
    assert!(
        stdout.starts_with("0\n"),
        "accepted patterns that re cannot compile:\n{stdout}"
    );
}
