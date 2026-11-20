//! J87 (#316): type-directed lowering (SUBSET.md, *Types*). Every fast path is checked both ways:
//! TAKEN where the compiler can prove its precondition, NOT taken where the proof fails (the J85
//! lesson: a fast path that trusts the wrong fact answers wrongly and silently). Each probe then
//! runs under Python, and what it prints is what Node prints for the same source, pinned below
//! (Node v26.13.0, `JSON.stringify` with every code unit at or above U+007F written `\uXXXX`).

use std::process::Command;

fn compile(source: &str, name: &str) -> String {
    ts2py::compile(source, name, &ts2py::Options::default())
        .unwrap_or_else(|lines| panic!("{name} refused:\n{}", lines.join("\n")))
}

/// The text of one top-level `def` in a generated module.
fn def_of<'m>(module: &'m str, name: &str) -> &'m str {
    let head = format!("\ndef {name}(");
    let start = module
        .find(&head)
        .unwrap_or_else(|| panic!("no def {name} in:\n{module}"))
        + 1;
    let rest = &module[start..];
    let end = rest[1..].find("\n\n\n").map_or(rest.len(), |at| at + 1);
    &rest[..end]
}

fn has(body: &str, needle: &str) {
    assert!(body.contains(needle), "expected `{needle}` in:\n{body}");
}

fn lacks(body: &str, needle: &str) {
    assert!(
        !body.contains(needle),
        "did not expect `{needle}` in:\n{body}"
    );
}

/// Run `probe(<arg>)` of the module under Python and print it as Node's `JSON.stringify` would,
/// every code unit at or above U+007F escaped.
fn run(module: &str, arg: &str) -> String {
    // J90-P7: one directory per call. Keyed by the module's length alone, two tests running at
    // once could write one `probe.py` and read each other's answer.
    static CALLS: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
    let call = CALLS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "ts2py-types-{}-{call}-{:x}",
        std::process::id(),
        module.len() ^ arg.len() << 20
    ));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("probe.py");
    std::fs::write(&path, module).unwrap();
    let driver = r#"
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("p", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
out = m._js_json_stringify(m.probe(json.loads(sys.argv[2])))
print("".join(c if ord(c) < 0x7F else "\\u%04x" % ord(c) for c in m._js_code_units(out)))
"#;
    let python = std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let run = Command::new(&python)
        .arg("-c")
        .arg(driver)
        .arg(&path)
        .arg(arg)
        .output()
        .unwrap_or_else(|err| {
            panic!("cannot run {python}: {err}; set TS2PY_PYTHON to an interpreter")
        });
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    String::from_utf8(run.stdout)
        .unwrap()
        .trim_end()
        .to_string()
}

const GUARD: &str = r###"// An exported function is entered from Python with any value: its guard admits a `string` into
// the typed body and sends anything else to the untyped one, which answers as JS does.
export function probe(s: string): unknown[] {
  return [s.length, s[0], s.slice(1), s.includes('c')];
}
"###;

#[test]
fn guarded_entry_admits_only_what_the_annotation_says() {
    let module = compile(GUARD, "guard.ts");
    // Exported, so Python may call it with anything: a typed body, and a guarded entry under the
    // function's own name that runs it only for a `str`.
    let typed = def_of(&module, "_probe__typed");
    has(typed, "_jsu_s = _js_code_units(s)");
    has(typed, "len(_jsu_s)");
    has(typed, "_js_units_slice(_jsu_s, 1)");
    has(typed, "_js_str_includes(s, \"c\")");
    let entry = def_of(&module, "probe");
    has(
        entry,
        "    if type(s) is str:\n        return _probe__typed(s)\n",
    );
    has(
        entry,
        "[_js_len(s), _js_get(s, 0), _js_m_slice(s, 1), _js_m_includes(s, \"c\")]",
    );
    assert_eq!(
        run(&module, r#""a\ud83d\ude00c""#),
        r###"[4,"a","\ud83d\ude00c",true]"###
    );
    // An array is not a string: the guard sends it to the untyped body, which answers as JS does.
    assert_eq!(run(&module, r#"["x","c"]"#), r###"[2,"x",["c"],true]"###);
}

const STRS: &str = r###"// Proven: `s` is a guarded `string` parameter. Unproven: `u` is `unknown`, `c` came through `as`.
function views(s: string): unknown[] {
  return [s.length, s[1], s.slice(1), s.slice(-2, 9), s.indexOf('b'), s.indexOf('b', 2), s.includes('😀'), s.startsWith('a'), s ? 'yes' : 'no', !s];
}
function loose(u: unknown): unknown[] {
  const c = u as string;
  return [c.length, c[1], c.slice(1), c.includes('😀'), c ? 'yes' : 'no'];
}
export function probe(input: unknown): unknown[] {
  return [views('abcb'), views('a😀b'), views(''), loose('a😀b'), loose(['x', '😀']), loose([])];
}
"###;

#[test]
fn string_fast_paths_taken_only_on_a_proven_str() {
    let module = compile(STRS, "strs.ts");
    // Called only with string literals, so `s` is proven and no guarded entry is needed.
    let views = def_of(&module, "_views");
    for fast in [
        "len(_jsu_s)",
        "_js_units_slice(_jsu_s, -2, 9)",
        "_js_units_index_of(_jsu_s, \"b\", 2)",
        "_js_str_includes(s, ",
        // J90-PF: an ASCII literal needle is Python's own `startswith` on the proven `str`.
        "s.startswith(\"a\")",
        "\"yes\" if s != \"\" else \"no\"",
        "not s != \"\"",
    ] {
        has(views, fast);
    }
    lacks(&module, "def _views__typed");
    // `u as string` proves nothing: every read takes the general helper.
    let loose = def_of(&module, "_loose");
    for general in [
        "_js_len(c)",
        "_js_get(c, 1)",
        "_js_m_slice(c, 1)",
        "_js_m_includes(c, ",
        "_js_truthy(c)",
    ] {
        has(loose, general);
    }
    assert_eq!(
        run(&module, "null"),
        r###"[[4,"b","bcb","cb",1,3,false,true,"yes",false],[4,"\ud83d","\ud83d\ude00b","\ude00b",3,3,true,true,"yes",false],[0,null,"","",-1,-1,false,false,"no",true],[4,"\ud83d","\ud83d\ude00b",true,"yes"],[2,"\ud83d\ude00",["\ud83d\ude00"],true,"yes"],[0,null,[],false,"yes"]]"###
    );
}

const LISTS: &str = r###"// Proven: `out` is bound once, to an array literal. Unproven: `xs` is reassigned from `unknown`.
export function probe(input: unknown): unknown[] {
  const out: string[] = [];
  out.push('a');
  out.push('😀');
  const n = out.push('b');
  let xs: unknown = [];
  xs = input;
  const ys = xs as string[];
  return [out.length, out[1], out[7], out.includes('b'), out.includes('z'), n, ys.length, ys[0], ys.includes('b')];
}
"###;

#[test]
fn list_fast_paths_taken_only_on_a_proven_list() {
    let module = compile(LISTS, "lists.ts");
    let body = def_of(&module, "probe");
    // `out` is bound once, to an array literal: a list for as long as it lives.
    for fast in [
        "out.append(\"a\")",
        "n = _js_m_push(out, \"b\")",
        "len(out)",
        "_js_list_at(out, 1)",
        "\"b\" in out",
        "\"z\" in out",
    ] {
        has(body, fast);
    }
    // `ys` is `xs`, which was reassigned from the input: nothing is proven of it.
    for general in ["_js_len(ys)", "_js_get(ys, 0)", "_js_m_includes(ys, \"b\")"] {
        has(body, general);
    }
    assert_eq!(
        run(&module, r#"["q","b"]"#),
        r###"[3,"\ud83d\ude00",null,true,false,3,2,"q",true]"###
    );
}

const NUMS: &str = r###"// Proven: `i` only ever holds sums of numbers. Unproven: `j` also takes `step`, which is `unknown`.
function count(n: number, step: unknown): unknown[] {
  let i = 0;
  let j = 0;
  while (i < n) {
    i += 1;
    j = j + (step as number);
  }
  return [i, i === n, j, j < n];
}
export function probe(input: unknown): unknown[] {
  return [count(3, 1), count(2, '1'), count(0.5, 2)];
}
"###;

#[test]
fn number_ops_plain_only_on_proven_numbers() {
    let module = compile(NUMS, "nums.ts");
    let count = def_of(&module, "_count");
    // `i` only ever holds sums of numbers, and `n` is a guarded `number` parameter.
    has(count, "while i < n:");
    has(count, "i = _js_num(i + 1)");
    has(count, "i == n");
    // `j` also takes `step` (`unknown`, cast with `as`): JS's `+` and `<`, through the runtime.
    // J90-P6: in a loop the `+` is the guarded expansion, whose plain `+` runs only for two ints
    // within 2^52 and whose other arm is the same runtime call.
    has(
        count,
        "j = (j + step if type(j) is int and type(step) is int and -4503599627370496 <= step <= 4503599627370496 and -4503599627370496 <= j <= 4503599627370496 else _js_add(j, step))",
    );
    has(count, "_js_lt(j, n)");
    // `count(2, '1')` concatenates, as JS does: the cast proved nothing.
    assert_eq!(
        run(&module, "null"),
        r###"[[3,true,3,false],[2,true,"011",false],[1,false,2,false]]"###
    );
}

const TUPLES: &str = r###"// Proven: `pair` returns a fresh [string, number] on every path. Unproven: `held` returns a
// binding, which any caller could have mutated.
function pair(s: string, n: number): [string, number] {
  if (n > 1) return [s, 2];
  return [s + '!', n + 1];
}
const SAVED: unknown[] = ['kept', 1];
function held(): unknown[] {
  return SAVED;
}
export function probe(input: unknown): unknown[] {
  const [a, b] = pair('x', 0);
  const [c, d] = held();
  return [a, b, b + 1, c, d];
}
"###;

#[test]
fn fresh_tuples_unpack_directly_and_bindings_do_not() {
    let module = compile(TUPLES, "tuples.ts");
    let body = def_of(&module, "probe");
    // Every return of `pair` is a fresh two-item array: a plain unpack, and `b` is a number.
    has(body, "a, b = _pair(\"x\", 0)");
    has(body, "_js_num(b + 1)");
    // `held` returns a binding, whose array any caller could have changed: through the iterator.
    has(body, "c, d = _js_destructure(_held(), 2)");
    assert_eq!(run(&module, "null"), r###"["x!",1,2,"kept",1]"###);
}

const FROZEN: &str = r###"// Proven: TABLE is only ever destructured by for-of. Unproven: SHARED is also pushed to.
const TABLE: Array<[string, RegExp, string[]]> = [
  ['digit', /^[0-9]+$/, ['0', '1', '2']],
  ['word', /^[a-z]+$/, ['a', 'b']],
];
const SHARED: Array<[string, RegExp, string[]]> = [['any', /./, ['x']]];
function classify(value: string): string {
  const first = value.slice(0, 1);
  for (const [tag, pattern, firsts] of TABLE) {
    if (firsts.includes(first) && pattern.test(value)) return tag;
  }
  return 'none';
}
function loose(value: string): string {
  for (const [tag, pattern, firsts] of SHARED) {
    if (firsts.includes(value[0]!) && pattern.test(value)) return tag;
  }
  return 'none';
}
export function probe(input: unknown): unknown[] {
  SHARED.push(['late', /x/, ['y']]);
  return [classify('12'), classify('ab'), classify('a1'), classify(''), loose('x'), loose('yx'), loose('q')];
}
"###;

#[test]
fn frozen_module_array_unpacks_and_an_escaped_one_does_not() {
    let module = compile(FROZEN, "frozen.ts");
    // TABLE is only ever destructured by `for-of`: its rows unpack directly, `firsts` is a list
    // and `pattern` a regex literal.
    let classify = def_of(&module, "_classify");
    has(classify, "for tag, pattern, firsts in _TABLE:");
    has(classify, "first in firsts");
    has(
        classify,
        "pattern.search(_js_code_units(value)) is not None",
    );
    // SHARED is also pushed to, so its rows prove nothing: each is read the general way (J90-P:
    // `_js_get` of each name's index unless the row is a list that long). J91-2 (#341): SHARED
    // itself is a list, so the loop is Python's over it and each row is unpacked there, through
    // `_js_row` unless it is a list of exactly three.
    let loose = def_of(&module, "_loose");
    has(loose, "in _SHARED:");
    has(
        loose,
        "tag, pattern, firsts = _js_r1 if type(_js_r1) is list and len(_js_r1) == 3 else _js_row(_js_r1, 3, (0, 1, 2))",
    );
    lacks(loose, "for tag, pattern, firsts in _SHARED:");
    has(loose, "_js_m_includes(firsts, ");
    has(loose, "_js_m_test(pattern, value)");
    assert_eq!(
        run(&module, "null"),
        r###"["digit","word","none","none","any","late","none"]"###
    );
}

const NARROW: &str = r###"// Proven after a guard: `w` is a number once `w === undefined` has exited; `ch` is a string inside
// `ch === "'" || ch === '"'`. Unproven: `v` is computed before the guard; `ch2` is never tested.
const W: Record<string, number> = { x: 2, u: 4 };
function width(code: string): number {
  const w = W[code];
  if (w === undefined) throw new Error('no width');
  return w + 1;
}
function late(code: string): unknown {
  const w = W[code];
  const v = w + 1;
  if (w === undefined) return 'none';
  return v;
}
function twice(q: string): string {
  return q + q;
}
function quoteOf(s: string, i: number): string {
  const ch = s[i];
  if (ch === "'" || ch === '"') return twice(ch);
  return 'plain';
}
function anyOf(s: string, i: number): string {
  const ch2 = s[i];
  return twice(ch2 as string);
}
export function probe(input: unknown): unknown[] {
  return [width('x'), width('u'), late('x'), late('u'), quoteOf("a'b", 1), quoteOf('ab', 0), anyOf('ab', 0), anyOf('ab', 1)];
}
"###;

#[test]
fn narrowing_after_a_guard_and_not_before_it() {
    let module = compile(NARROW, "narrow.ts");
    // After `if (w === undefined) throw`, `w` (a property of a frozen object of numbers) is a
    // number; before the guard it is not. J91-1 (#341): the object's numbers are whole literals in
    // `[0, 2**52]`, so `w` is an index and `w + 1` is Python's exact int `+` (no `_js_num`).
    has(def_of(&module, "_width"), "return w + 1");
    has(def_of(&module, "_late"), "v = _js_add(w, 1)");
    // Inside `ch === "'" || ch === '"'`, `ch` is a string: the typed body of `twice` is called.
    has(def_of(&module, "_quote_of"), "return _twice__typed(ch)");
    // `ch2` is never tested (`as string` proves nothing): the guarded entry.
    has(def_of(&module, "_any_of"), "return _twice(ch2)");
    has(def_of(&module, "_twice"), "if type(q) is str:");
    assert_eq!(
        run(&module, "null"),
        r###"[3,5,3,5,"''","plain","aa","bb"]"###
    );
}

const HOIST: &str = r###"// Proven: `s` is a string parameter never assigned again, so its UTF-16 view is computed once.
// Unproven: `t` is reassigned, so every read goes through the string helpers.
function count(s: string, c: string): number {
  let n = 0;
  let i = 0;
  while (i < s.length) {
    if (s[i] === c) n += 1;
    i += 1;
  }
  return n;
}
function trimmed(t: string): string {
  while (t.length > 0 && t[0] === ' ') t = t.slice(1);
  return t;
}
export function probe(input: unknown): unknown[] {
  return [count('a😀a😀', 'a'), count('a😀a😀', '\ud83d'), count('', 'a'), trimmed('  x😀'), trimmed('')];
}
"###;

#[test]
fn utf16_view_hoisted_only_for_a_binding_never_reassigned() {
    let module = compile(HOIST, "hoist.ts");
    let count = def_of(&module, "_count");
    has(count, "    _jsu_s = _js_code_units(s)\n");
    has(count, "while i < len(_jsu_s):");
    has(
        count,
        "_jsu_s[i] if type(i) is int and 0 <= i < len(_jsu_s) else _js_str_at(s, i)",
    );
    // `t` is reassigned, so no view of it can be kept.
    let trimmed = def_of(&module, "_trimmed");
    lacks(trimmed, "_jsu_t");
    has(trimmed, "_js_str_len(t) > 0 and _js_str_at(t, 0) == \" \"");
    // Positions count UTF-16 units: half of a surrogate pair is found inside one.
    assert_eq!(run(&module, "null"), r###"[2,2,0,"x\ud83d\ude00",""]"###);
}

const RECUR: &str = r###"// Mutual recursion: the greatest fixpoint proves both return numbers.
function down(n: number): number {
  return n > 0 ? up(n - 1) : 0;
}
function up(n: number): number {
  return down(n) + 1;
}
export function probe(input: unknown): unknown[] {
  return [down(3), up(0), down(-1)];
}
"###;

#[test]
fn mutual_recursion_settles_on_the_greatest_fixpoint() {
    let module = compile(RECUR, "recur.ts");
    has(
        def_of(&module, "_down"),
        "_up(_js_num(n - 1)) if n > 0 else 0",
    );
    has(def_of(&module, "_up"), "return _js_num(_down(n) + 1)");
    assert_eq!(run(&module, "null"), r###"[3,1,0]"###);
}

const FIELDS: &str = r###"// A data field whose name is a builtin method's: read as data where the declared type says so.
interface Opts {
  map: string;
  size?: number;
}
type Box = { get: number; link: string[] };
export function probe(input: unknown): unknown[] {
  const o: { get: number } = { get: 5 };
  const opts: Opts = { map: 'm' };
  const box: Box = { get: 7, link: ['l'] };
  return [o.get, o['get'], opts.map, box.get, box.link, readMap(opts)];
}
function readMap(x: Opts): string {
  return x.map;
}
"###;

#[test]
fn data_field_named_like_a_method_reads_as_data_where_declared() {
    let module = compile(FIELDS, "fields.ts");
    let body = def_of(&module, "probe");
    has(body, "_js_get(o, \"get\")");
    has(body, "_js_get(opts, \"map\")");
    has(body, "_js_get(box, \"link\")");
    has(def_of(&module, "_read_map"), "return _js_get(x, \"map\")");
    assert_eq!(run(&module, "null"), r###"[5,5,"m",7,["l"],"m"]"###);
}

/// Without a declared type that makes the member data, the name still decides (J86-R finding 3).
#[test]
fn a_method_name_without_a_declared_data_field_stays_refused() {
    let cases = [
        (
            "const o = { get: 5 };\n  return o.get;",
            "method .get read as a value",
        ),
        (
            "const o: any = { get: 5 };\n  return o.get;",
            "method .get read as a value",
        ),
        (
            "const o: { get(): number } = { get: 5 } as any;\n  return o.get;",
            "method .get read as a value",
        ),
        (
            "const o: { get: () => number } = { get: () => 5 };\n  return o.get;",
            "method .get read as a value",
        ),
        (
            "const o: unknown = { map: 'm' };\n  return (o as { map: string }).map;",
            "method .map read as a value",
        ),
    ];
    for (body, construct) in cases {
        let source = format!("export function probe(input: unknown): unknown {{\n  {body}\n}}\n");
        let lines = ts2py::compile(&source, "refused.ts", &ts2py::Options::default())
            .err()
            .unwrap_or_else(|| panic!("accepted:\n{source}"));
        assert!(
            lines.iter().any(|l| l.contains(construct)),
            "{source}\n{}",
            lines.join("\n")
        );
    }
}

/// A function with a typed body is lowered twice; each offence is still reported once.
#[test]
fn a_refusal_in_a_typed_function_is_reported_once() {
    // J89-2 lowered `.charCodeAt`; `.trimEnd()` is still refused.
    let source = "export function f(s: string): string {\n  return s.trimEnd();\n}\n";
    let lines = ts2py::compile(source, "once.ts", &ts2py::Options::default()).unwrap_err();
    assert_eq!(
        lines,
        vec!["once.ts:2:10: unsupported builtin method .trimEnd: s.trimEnd()".to_string()]
    );
}

/// Each J87 helper for a proven receiver against the general helper it shortcuts, over random
/// receivers of the proven type and ANY argument: the helpers must take the general path for an
/// argument their own fast case does not cover. (A mutant that skips `_js_from_units` in
/// `_js_list_join`, or indexes code points in `_js_str_at`, turns this red.)
#[test]
fn proven_receiver_helpers_answer_as_the_general_helpers() {
    let dir = std::env::temp_dir().join(format!("ts2py-helpers-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let runtime = dir.join("rt.py");
    std::fs::write(&runtime, ts2py::RUNTIME).unwrap();
    let python = std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let run = Command::new(&python)
        .arg("-c")
        .arg(HELPER_FUZZ)
        .arg(&runtime)
        .arg("1500")
        .output()
        .unwrap_or_else(|err| panic!("cannot run {python}: {err}"));
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    let stdout = String::from_utf8(run.stdout).unwrap();
    assert_eq!(stdout.trim_end(), "calls 30000 diffs 0", "{stdout}");
}

const HELPER_FUZZ: &str = r###""""J87: each proven-receiver helper against the general helper it shortcuts, over random inputs of
the proven receiver type and ANY argument (the helpers must take the general path for an argument
their own fast case does not cover)."""
import importlib.util, random, re, sys
spec = importlib.util.spec_from_file_location("rt", sys.argv[1]); R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
ROUNDS = int(sys.argv[2])
r = random.Random(87)
INTS = [0, 1, -1, 2, 3, -3, 5, 100, -100, 2**53, 2**53 + 1, -2**53 - 1, 2**60, 7]
NUMS = INTS + [0.0, -0.0, 1.0, 1.5, -1.5, float("nan"), float("inf"), float("-inf"), 2.0]
STRS = ["", "a", "abc", "ab ab", "é", "😀", "a😀b", "\ud800", "\udc00x", "ไทย", "\U0001F600x", "x\ny", "  a", "#", " #", "aé😀\ud800z"]
ANY = NUMS + STRS + [True, False, None, R._JS_UNDEFINED, [], ["a"], [1], {"a": 1}, "length", "0", "1", "01"]
LISTS = [[], ["a"], ["a", "b", "é"], ["😀", 1, None], [R._JsBigInt(1), 1.0, float("nan"), "x"], [[], {}, "a"], ["\ud800", "\udc00"]]
def call(f, *a):
    try: return ("ok", repr(f(*a)))
    except Exception as e: return ("err", type(e).__name__, str(e))
pairs = [
    ("_js_str_len", lambda s: R._js_str_len(s), lambda s: R._js_len(s), lambda: (r.choice(STRS),)),
    ("_js_str_at", R._js_str_at, R._js_get, lambda: (r.choice(STRS), r.choice(ANY))),
    ("_js_units_at", lambda s, k: R._js_units_at(R._js_code_units(s), s, k), R._js_get, lambda: (r.choice(STRS), r.choice(ANY))),
    ("inline units", lambda s, k: (lambda u: u[k] if type(k) is int and 0 <= k < len(u) else R._js_str_at(s, k))(R._js_code_units(s)), R._js_get, lambda: (r.choice(STRS), r.choice(ANY))),
    ("_js_list_at", R._js_list_at, R._js_get, lambda: (list(r.choice(LISTS)), r.choice(ANY))),
    ("len(list)", lambda xs: len(xs), R._js_len, lambda: (list(r.choice(LISTS)),)),
    ("_js_str_includes", R._js_str_includes, R._js_m_includes, lambda: (r.choice(STRS), r.choice(STRS))),
    ("str in list", lambda xs, s: s in xs, R._js_m_includes, lambda: (list(r.choice(LISTS)), r.choice(STRS + ["a", "x"]))),
    ("_js_str_starts_with", R._js_str_starts_with, R._js_m_startsWith, lambda: (r.choice(STRS), r.choice(STRS))),
    ("_js_str_index_of", R._js_str_index_of, R._js_m_indexOf, lambda: (r.choice(STRS), r.choice(STRS), *([r.choice(NUMS)] if r.random() < 0.7 else []))),
    ("_js_str_slice", R._js_str_slice, R._js_m_slice, lambda: (r.choice(STRS), *[r.choice(NUMS) for _ in range(r.randint(0, 2))])),
    ("regex test", lambda p, s: p.search(R._js_code_units(s)) is not None, R._js_m_test, lambda: (r.choice(PATS), r.choice(STRS))),
    ("str truthy", lambda s: s != "", R._js_truthy, lambda: (r.choice(STRS),)),
    ("_js_is_double", R._js_is_double, lambda v: R._js_is_number(v) and R._js_num(v) is v, lambda: (r.choice(ANY),)),
    ("_js_units_index_of", lambda s, t, *p: R._js_units_index_of(R._js_code_units(s), t, *p), R._js_m_indexOf, lambda: (r.choice(STRS), r.choice(["\n", " #", "a", "", "b", " "]), *([r.choice(NUMS)] if r.random() < 0.7 else []))),
    ("_js_units_slice", lambda s, *a: R._js_units_slice(R._js_code_units(s), *a), R._js_m_slice, lambda: (r.choice(STRS), *[r.choice(NUMS + [R._JS_UNDEFINED]) for _ in range(r.randint(0, 2))])),
    ("_js_list_join", R._js_list_join, R._js_m_join, lambda: (list(r.choice(LISTS + [["a", "\ud83d"], ["\ude00", "x"], ["a", None, "b"], [R._JS_UNDEFINED]])), r.choice(["", ",", " ", "\ud83d", "é"]))),
    ("_js_re_exec", lambda p, s: (lambda m: None if m is None else (list(m), m.index, m.input))(R._js_re_exec(p, s)), lambda p, s: (lambda m: None if m is None else (list(m), m.index, m.input))(R._js_m_exec(p, s)), lambda: (r.choice(PATS + GPATS), r.choice(STRS))),
    ("_js_re_replace", R._js_re_replace, R._js_m_replace, lambda: (r.choice(STRS), r.choice(PATS + GPATS), r.choice(["", "x", "é", "😀", " "]))),
    ("_js_m_push list", lambda xs, v: (R._js_m_push(xs, v), xs), lambda xs, v: (R._js_dispatch(xs, "push", R._js_m_push, v), xs), lambda: (list(r.choice(LISTS)), r.choice(ANY))),
]
PATS = [re.compile(p, re.ASCII) for p in ["a", "^a", "\\ud83d", "[^\\n\\r\\u2028\\u2029]{2}", "b\\Z", "^$"]]
GPATS = [re.compile(p, re.ASCII) for p in ["^( *)(a)?", "(?:#[^\\n]*)?$", "[ \\t]+\\Z", "^[ \\t]+", "(x)|(a)"]]
n = diffs = 0
for name, fast, general, gen in pairs:
    for _ in range(ROUNDS):
        a = gen()
        b = tuple(list(x) if isinstance(x, list) else x for x in a)
        n += 1
        x, y = call(fast, *a), call(general, *b)
        if x != y:
            diffs += 1
            if diffs < 20: print("DIFF", name, a, x, y)
print("calls", n, "diffs", diffs)
"###;

const BOOL_ANNOTATION: &str = r###"// J87-3 (item 6): a `: boolean` return annotation is not proof. `isIt` hands back whatever it is
// given, so a call of it is tested with JS truthiness, never Python's (`[]` is truthy, NaN falsy).
function isIt(x: any): boolean {
  return x;
}
// Every return proven a bool: the call is a known bool, from the body, not the annotation.
function isX(s: string): boolean {
  return s === 'x';
}
export function probe(input: unknown): unknown[] {
  const empty: unknown[] = [];
  return [
    isIt(empty) ? 'yes' : 'no',
    isIt(NaN) ? 'yes' : 'no',
    !isIt(empty),
    isIt(empty) && 'and',
    isIt(0) || 'or',
    isX('x') && isX('y'),
    isX(String(input)) ? 1 : 2,
  ];
}
"###;

#[test]
fn a_boolean_return_annotation_is_not_proof() {
    let module = compile(BOOL_ANNOTATION, "boolann.ts");
    let probe = def_of(&module, "probe");
    // The J85 rule (`bool_fns`) lowered these with Python truthiness, `[]` falsy and NaN truthy.
    has(probe, "\"yes\" if _js_truthy(_is_it(empty)) else \"no\"");
    has(probe, "\"yes\" if _js_truthy(_is_it(_JS_NAN)) else \"no\"");
    has(probe, "not _js_truthy(_is_it(empty))");
    has(probe, "_js_and_value(_is_it(empty), \"and\")");
    has(probe, "_js_or_value(_is_it(0), \"or\")");
    // Proven from the body: every return of `isX` is a comparison.
    has(probe, "_is_x(\"x\") and _is_x(\"y\")");
    has(probe, "1 if _is_x(_js_str(input)) else 2");
    // Node v26.13.0 prints this for the same source.
    assert_eq!(
        run(&module, r#""x""#),
        r###"["yes","no",false,"and","or",false,1]"###
    );
}
