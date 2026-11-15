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
    `${input.f}|${input.n}|${input.flag}|${input.nil}|${0.1}|${input.bigN}|${input.tiny}`,
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
data = {"flag": True, "n": 3.0, "f": 3.0, "nil": None, "bigN": 1e21, "tiny": 1e-7,
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
    input.bigN,
    `${input.bigN}|${input.hi}|${input.smallN - 1}|${-input.smallN}`,
    [input.smallN, input.smallN - 1, -input.smallN, input.smallN + 2, input.smallN + 0.5],
    input.huge,
    input.huge > input.bigN,
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
data = json.loads('{"lo": 9007199254740992, "hi": 9007199254740993, "bigN": 12345678901234567890, "smallN": 3, "huge": 1' + '0' * 400 + '}')
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

/// J86-5: the runtime's fast paths. Each one answers for exactly the operand types it tests for at
/// run time (`type(x) is int` inside +-2^53, `type(x) is str`, a list) and hands every other pair
/// to the general path, so the answers must not move at the edges: an int one past 2^53 (`hi`,
/// which JS reads as 2^53), sums past 2^53, a bool against 1, a float 1.0 position, NaN, an astral
/// string indexed and measured by code unit, SameValueZero over a mixed array, `fromCodePoint` at
/// and past U+10FFFF, and the code-unit memo past both of its bounds (600 distinct strings, one of
/// 70,001 characters). The JSON line is what Node prints for the same source on the same input;
/// the second line is Node's `RangeError: Invalid code point 1114112` under the runtime's class.
const FAST_PATHS: &str = r#"
export function fast(input: any): string {
  const xs: any[] = [];
  const pushed = xs.push(input.smallN, input.lo);
  let total = 0;
  let k = 0;
  while (k < 600) {
    total = total + (input.e + k + input.grin).length;
    k = k + 1;
  }
  const long = input.e.repeat(70000) + input.grin;
  return JSON.stringify([
    input.lo === input.hi, input.lo === input.lo, input.smallN === input.smallN, input.smallN === input.three,
    input.t === input.one, input.one === input.onef, input.onestr === input.one, input.s === input.s2,
    input.nan === input.nan, input.neg === input.neg,
    input.lo + input.one, input.hi + input.hi, input.smallN + input.smallN, input.lo + input.lo,
    input.neg + input.smallN, input.smallN + input.onef, (input.lo + input.one) - input.lo, (input.hi + input.smallN) - input.hi, (input.hi + input.one) - input.lo,
    input.hi > input.lo, input.hi >= input.lo, input.hi < input.lo, input.hi <= input.lo,
    input.neg < input.smallN, input.smallN > input.neg, input.smallN <= input.smallN, input.smallN >= input.three,
    input.t >= input.one, input.nan < input.one, input.nan >= input.one, input.bigN > input.lo,
    input.astral[1], input.astral[2], input.astral[0], input.thai[2], input.s[99] === undefined,
    input.list[1], input.list[5] === undefined, input.list[input.neg] === undefined, input.thai[input.neg] === undefined,
    input.astral.length, input.thai.length, input.s.length,
    input.mixed.includes(input.onestr), input.mixed.includes(input.one), input.mixed.includes(input.t),
    input.nums.includes(input.onestr), input.mixed.includes(input.nan), input.strs.includes(input.thai),
    input.grin.codePointAt(input.zero), input.grin.codePointAt(input.one), input.grin.codePointAt(input.hi),
    input.grin.codePointAt(input.neg) === undefined, input.grin.codePointAt(input.onef),
    String.fromCodePoint(input.cp), String.fromCodePoint(input.maxcp).length, String.fromCodePoint(input.zero).length,
    pushed, xs.length, total, long.length, long[70000] === input.grin[0], long.length,
  ]);
}

export function over(input: any): string {
  return String.fromCodePoint(input.over);
}
"#;

#[test]
fn fast_paths_answer_exactly_as_the_general_paths_and_js_do() {
    let module = ts2py::compile(FAST_PATHS, "fast.ts", &ts2py::Options::default())
        .unwrap_or_else(|lines| panic!("fast-path probe refused:\n{}", lines.join("\n")));
    for helper in [
        "_js_strict_eq(",
        "_js_add(",
        "_js_lt(",
        "_js_gt(",
        "_js_le(",
        "_js_ge(",
        "_js_get(_js_get(input, \"astral\"), 1)",
        "_js_len(",
        "_js_m_includes(",
        "_js_m_codePointAt(",
        "_js_from_code_point(",
    ] {
        assert!(
            module.contains(helper),
            "the probe no longer reaches {helper}"
        );
    }
    let dir = std::env::temp_dir().join(format!("ts2py-fast-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("fast.py");
    std::fs::write(&path, module).unwrap();
    let driver = r#"
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("f", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
data = json.loads('{"lo": 9007199254740992, "hi": 9007199254740993, "bigN": 12345678901234567890, "smallN": 3, "three": 3, "neg": -1, "zero": 0, "one": 1, "onestr": "1", "t": true, "s": "abc", "s2": "abc", "astral": "a\\ud835\\udd18b", "thai": "\\u0e17\\u0e14\\u0e2a\\u0e2d\\u0e1a", "grin": "\\ud83d\\ude00", "e": "\\u00e9", "list": [10, 20, 30], "mixed": [true, 1, "1", null], "nums": [1, 2], "strs": ["x", "\\u0e17\\u0e14\\u0e2a\\u0e2d\\u0e1a"], "cp": 128512, "maxcp": 1114111, "over": 1114112}')
data["nan"] = float("nan")
data["onef"] = 1.0
sys.stdout.reconfigure(encoding="utf-8")
print(m.fast(data))
try:
    m.over(data)
except Exception as e:
    print(f"{type(e).__name__}: {e}")
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
        r#"[true,true,true,true,false,true,false,true,false,true,9007199254740992,18014398509481984,"#,
        r#"6,18014398509481984,2,4,0,4,0,false,true,false,true,true,true,true,true,true,false,false,"#,
        r#"true,"\ud835","\udd18","a","ส",true,20,true,true,true,4,5,3,true,true,true,false,false,"#,
        r#"true,128512,56832,null,true,56832,"😀",2,1,2,2,3490,70002,true,70002]"#,
        "\n_JsRangeError: Invalid code point 1114112",
    );
    assert_eq!(String::from_utf8(run.stdout).unwrap().trim_end(), expected);
}

/// J86-R finding 3, the run-time half: a COMPUTED key the compiler cannot see that names a method
/// of the receiver's JS type (`xs[k]`, `k === 'push'`) is a function in Node; the generated code
/// raises instead of answering `undefined`. Data keys, and method names on a plain object (which
/// has no such method), still read as Node reads them.
#[test]
fn a_computed_key_naming_a_method_raises() {
    let source = "export class A {\n  m(): number {\n    return 1;\n  }\n}\nexport function read(o: any, k: string): unknown {\n  return o[k];\n}\nexport function make(): A {\n  return new A();\n}\n";
    let module = ts2py::compile(source, "read.ts", &ts2py::Options::default())
        .unwrap_or_else(|lines| panic!("refused:\n{}", lines.join("\n")));
    let dir = std::env::temp_dir().join(format!("ts2py-meth-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("read.py");
    std::fs::write(&path, module).unwrap();
    let driver = r#"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("r", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
rt = vars(m)
out = []
for obj, key in [([1], "push"), ("s", "slice"), (rt["_JsMap"](), "get"), (rt["_JsSet"](), "add"),
                 (1.5, "toFixed"), (m.make(), "m"), ([1], "0"), ("s", "0"), ({"push": 2}, "push"),
                 ({}, "slice"), (True, "toFixed")]:
    try:
        got = m.read(obj, key)
        out.append(repr(got if got is not rt["_JS_UNDEFINED"] else "undefined"))
    except TypeError as e:
        out.append("raise")
print(",".join(out))
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
    assert_eq!(
        String::from_utf8_lossy(&run.stdout).trim(),
        "raise,raise,raise,raise,raise,raise,1,'s',2,'undefined','undefined'"
    );
}
