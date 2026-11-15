//! Every construct outside the subset is a compile-time refusal: `path:line:col: unsupported
//! <construct>: <snippet>`, nonzero exit, nothing written.

use std::process::Command;

fn refusals(source: &str) -> Vec<String> {
    match ts2py::compile(source, "t.ts", &ts2py::Options::default()) {
        Ok(module) => panic!("expected a refusal, got a module:\n{module}"),
        Err(lines) => lines,
    }
}

fn assert_refused(source: &str, expected: &str) {
    let lines = refusals(source);
    assert!(
        lines.iter().any(|line| line == expected),
        "expected the line\n  {expected}\nin\n  {}",
        lines.join("\n  ")
    );
}

/// J86 accepts classes (SUBSET.md, Classes); what a class may not carry is still refused.
#[test]
fn class() {
    assert_refused(
        "export class A { static x = 1; }\n",
        "t.ts:1:18: unsupported static, computed or declared class field: static x = 1;",
    );
    assert_refused(
        "export class A extends Map<string, number> {}\n",
        "t.ts:1:24: unsupported extends anything but an Error class: Map",
    );
    assert_refused(
        "export class A { set v(x: number) {} }\n",
        "t.ts:1:18: unsupported setter: set v(x: number) {}",
    );
    assert_refused(
        "export class A { m(): number { return this.y; } }\n",
        "t.ts:1:39: unsupported this.y for a member the class does not declare: this.y",
    );
    assert_refused(
        "export class E extends Error { constructor(m: string) { super(m); } }\n",
        "t.ts:1:32: unsupported constructor in a class that extends Error: constructor(m: string) { super(m); }",
    );
}

#[test]
fn generator_and_yield() {
    let source = "export const k = 1;\n\n\nfunction* h() {\n  yield 2;\n}\n";
    let lines = refusals(source);
    assert!(
        lines
            .contains(&"t.ts:4:1: unsupported generator function: function* h() { ...".to_string()),
        "{lines:?}"
    );
    assert!(
        lines.contains(&"t.ts:5:3: unsupported yield: yield 2".to_string()),
        "{lines:?}"
    );
}

#[test]
fn async_and_await() {
    let source =
        "export async function f(x: Promise<number>): Promise<number> {\n  return await x;\n}\n";
    let lines = refusals(source);
    assert!(lines.contains(&"t.ts:1:8: unsupported async function: async function f(x: Promise<number>): Promise<number> { ...".to_string()), "{lines:?}");
    assert!(
        lines.contains(&"t.ts:2:10: unsupported await: await x".to_string()),
        "{lines:?}"
    );
}

#[test]
fn this() {
    assert_refused(
        "export function f(): unknown {\n  return this;\n}\n",
        "t.ts:2:10: unsupported this outside a class: this",
    );
}

#[test]
fn labelled_break_and_continue() {
    let source = "export function f(xs: number[]): void {\n  outer: for (const x of xs) {\n    if (x) continue outer;\n    break outer;\n  }\n}\n";
    let lines = refusals(source);
    assert!(
        lines.contains(
            &"t.ts:2:3: unsupported labelled statement: outer: for (const x of xs) { ..."
                .to_string()
        ),
        "{lines:?}"
    );
    assert!(
        lines.contains(&"t.ts:3:12: unsupported labelled continue: continue outer;".to_string()),
        "{lines:?}"
    );
    assert!(
        lines.contains(&"t.ts:4:5: unsupported labelled break: break outer;".to_string()),
        "{lines:?}"
    );
}

#[test]
fn unsupported_builtin_calls() {
    // J88-2 lowered `Object.assign` and `.trim`; their neighbours stay refused.
    assert_refused(
        "export function f(x: object): object {\n  return Object.create(x);\n}\n",
        "t.ts:2:10: unsupported builtin call Object.create: Object.create(x)",
    );
    assert_refused(
        "export function f(s: string): string {\n  return s.trimEnd();\n}\n",
        "t.ts:2:10: unsupported builtin method .trimEnd: s.trimEnd()",
    );
    assert_refused(
        "export function f(): number {\n  return Math.round(1.5);\n}\n",
        "t.ts:2:10: unsupported builtin call Math.round: Math.round(1.5)",
    );
}

#[test]
fn other_refusals() {
    assert_refused(
        "export function f(a: any): boolean {\n  return a == 1;\n}\n",
        "t.ts:2:10: unsupported loose equality other than == null: a == 1",
    );
    assert_refused(
        // J87-3: one optional member read is accepted (`a?.b`); a link after it, an optional call
        // and two optional links are not.
        "export function f(a: any): unknown {\n  return a?.b.c;\n}\n",
        "t.ts:2:10: unsupported optional chaining other than one member read: a?.b.c",
    );
    assert_refused(
        "export function f(a: any): unknown {\n  return a?.b?.c;\n}\n",
        "t.ts:2:10: unsupported optional chaining other than one member read: a?.b?.c",
    );
    assert_refused(
        "export function f(a: any): unknown {\n  return a?.();\n}\n",
        "t.ts:2:10: unsupported optional chaining other than one member read: a?.()",
    );
    assert_refused(
        "export function f(a: number): number {\n  return a ** 2;\n}\n",
        "t.ts:2:10: unsupported operator ** other than of two integer literals with an exact result: a ** 2",
    );
    // J87-3: `2 ** 53` folds to its exact value; one past 2^53 or a fraction does not.
    assert_refused(
        "export const X = 2 ** 54;\n",
        "t.ts:1:18: unsupported operator ** other than of two integer literals with an exact result: 2 ** 54",
    );
    assert_refused(
        "export const X = 4 ** 0.5;\n",
        "t.ts:1:18: unsupported operator ** other than of two integer literals with an exact result: 4 ** 0.5",
    );
    assert_refused(
        "export function f(xs: number[]): unknown {\n  const g = (x: number) => x;\n  return xs.map(g);\n}\n",
        "t.ts:3:17: unsupported callback that is not an inline arrow function: g",
    );
    // J88-2: an arrow used as a value is a nested `def`, but not inside a callback lambda (the
    // `def` would be hoisted out of reach of the lambda's parameters).
    assert_refused(
        "export function f(xs: number[]): unknown {\n  return xs.map((x) => () => x);\n}\n",
        "t.ts:2:24: unsupported arrow function outside a callback argument: () => x",
    );
    assert_refused(
        "export function f(x: number): number {\n  if (x) {\n    const x = 2;\n  }\n  return x;\n}\n",
        "t.ts:3:11: unsupported shadowed binding: x",
    );
    assert_refused(
        "export function f(): unknown {\n  return /\\s+/;\n}\n",
        "t.ts:2:10: unsupported regex syntax: /\\s+/",
    );
    assert_refused(
        "export function f(): unknown {\n  return window;\n}\n",
        "t.ts:2:10: unsupported global window: window",
    );
    assert_refused(
        "export function f(): void {\n  let i = 0;\n  i++;\n}\n",
        "t.ts:3:3: unsupported update expression (++/--): i++",
    );
    assert_refused(
        "export function f(): number {\n  const _js_x = 1;\n  return _js_x;\n}\n",
        "t.ts:2:9: unsupported identifier with the reserved _js prefix: _js_x",
    );
}

#[test]
fn every_offence_is_reported_in_source_order() {
    let lines = refusals("enum E { A }\nexport function f(): unknown {\n  return this;\n}\n");
    assert_eq!(
        lines,
        vec![
            "t.ts:1:1: unsupported enum: enum E { A }",
            "t.ts:3:10: unsupported this outside a class: this"
        ]
    );
}

#[test]
fn cli_writes_nothing_and_exits_nonzero() {
    let dir = std::env::temp_dir().join(format!("ts2py-refusal-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let input = dir.join("bad.ts");
    let output = dir.join("bad.py");
    std::fs::write(&input, "export enum E { A }\n").unwrap();
    let _ = std::fs::remove_file(&output);
    let run = Command::new(env!("CARGO_BIN_EXE_ts2py"))
        .arg(&input)
        .arg("-o")
        .arg(&output)
        .output()
        .unwrap();
    assert_eq!(run.status.code(), Some(1));
    assert!(!output.exists(), "no output may be written on a refusal");
    let stderr = String::from_utf8(run.stderr).unwrap();
    assert!(
        stderr
            .trim_end()
            .ends_with(":1:8: unsupported enum: enum E { A }"),
        "{stderr}"
    );
    std::fs::remove_dir_all(&dir).unwrap();
}

/// J85-R2 L3: a range out of order in UTF-16 code units is a SyntaxError in JS (without the `u`
/// flag `[😀-😂]` is `[😀-😂]`, whose middle range runs backwards). It used
/// to compile into a module that raised `re.error` on import; it is refused here, with the reason.
#[test]
fn regex_range_out_of_order() {
    assert_refused(
        "export const R = /^[😀-😂]$/;\n",
        "t.ts:1:18: unsupported regex range out of order in UTF-16 code units (\\ude00-\\ud83d), a SyntaxError in JS: /^[😀-😂]$/",
    );
    assert_refused(
        "export const R = /[z-a]/;\n",
        "t.ts:1:18: unsupported regex range out of order in UTF-16 code units (\\u007a-\\u0061), a SyntaxError in JS: /[z-a]/",
    );
}

/// J85-R2 L3, the general case: patterns `re` cannot compile (or that mean something else there)
/// are refused at compile time, each with its reason.
#[test]
fn regex_python_cannot_compile() {
    for (pattern, why) in [
        (
            "a{3,2}",
            "regex repeat {3,2} with min above max, a SyntaxError in JS",
        ),
        ("a**", "regex quantifier `*` with nothing to repeat"),
        ("(?=a)*", "regex quantifier `*` with nothing to repeat"),
        (
            "(a",
            "regex `(` without a matching `)`, a SyntaxError in JS",
        ),
        ("[a-\\d]", "regex class escape as a range endpoint"),
        ("a{99999}", "regex repeat count above 65535"),
        ("a{,2}", "regex syntax"),
        ("{", "regex quantifier `{` with nothing to repeat"),
        ("]", "regex syntax"),
        (
            "a\\B",
            "regex \\B, which Python's re does not match in an empty string",
        ),
    ] {
        let source = format!("export const R = /{pattern}/;\n");
        assert_refused(
            &source,
            &format!("t.ts:1:18: unsupported {why}: /{pattern}/"),
        );
    }
}

/// J86-R finding 3: a method read as a value. `const f = a.get; f()` throws in Node (`this` is
/// lost) and returned a value in Python; `a.get === a.get` is true in Node and false in Python (a
/// fresh bound method per read). So a member whose target is callable may be named only as the
/// callee of a direct call. ts2py has no type checker, so "callable" is decided by the NAME: a
/// builtin method of String, Array, Map, Set, RegExp, Number, Function or Object.prototype, or a
/// method any compiled or adapter class declares. Any other name reads as data, as before.
#[test]
fn method_read_as_a_value() {
    for (source, expected) in [
        (
            "export function f(a: Map<string, number>): unknown {\n  const g = a.get;\n  return g;\n}\n",
            "t.ts:2:13: unsupported method .get read as a value (a method may only be called directly): a.get",
        ),
        (
            "export function f(a: Map<string, number>): boolean {\n  return a.get === a.get;\n}\n",
            "t.ts:2:10: unsupported method .get read as a value (a method may only be called directly): a.get",
        ),
        (
            "export function f(s: string): unknown {\n  return s.slice;\n}\n",
            "t.ts:2:10: unsupported method .slice read as a value (a method may only be called directly): s.slice",
        ),
        (
            "export function f(xs: number[]): unknown {\n  return [xs.push];\n}\n",
            "t.ts:2:11: unsupported method .push read as a value (a method may only be called directly): xs.push",
        ),
        // Not in the subset's call table, still a builtin method: refused, not read as undefined.
        (
            "export function f(s: string): unknown {\n  return s.trim;\n}\n",
            "t.ts:2:10: unsupported method .trim read as a value (a method may only be called directly): s.trim",
        ),
        (
            "export function f(xs: number[]): unknown {\n  return xs['map'];\n}\n",
            "t.ts:2:10: unsupported method .map read as a value (a method may only be called directly): xs['map']",
        ),
        // A class method, on another receiver and on `this`.
        (
            "export class A {\n  m(): number {\n    return 1;\n  }\n}\nexport function f(a: A): unknown {\n  return a.m;\n}\n",
            "t.ts:7:10: unsupported method .m read as a value (a method may only be called directly): a.m",
        ),
        (
            "export class A {\n  m(): number {\n    return 1;\n  }\n  n(): unknown {\n    return this.m;\n  }\n}\n",
            "t.ts:6:12: unsupported method .m read as a value (a method may only be called directly): this.m",
        ),
        // Passing one along is reading it as a value too.
        (
            "function g(x: unknown): unknown {\n  return x;\n}\nexport function f(s: string): unknown {\n  return g(s.startsWith);\n}\n",
            "t.ts:5:12: unsupported method .startsWith read as a value (a method may only be called directly): s.startsWith",
        ),
    ] {
        assert_refused(source, expected);
    }
}

/// The other side of the same rule: calling a method, and reading data, still compile.
#[test]
fn method_called_directly_still_compiles() {
    for source in [
        "export function f(a: Map<string, number>): unknown {\n  return a.get('k');\n}\n",
        "export function f(s: string): number {\n  return s.slice(1).length;\n}\n",
        "export class A {\n  x = 1;\n  m(): number {\n    return this.x;\n  }\n  n(): number {\n    return this.m();\n  }\n}\n",
        "export function f(o: { name: string }): string {\n  return o.name;\n}\n",
    ] {
        if let Err(lines) = ts2py::compile(source, "t.ts", &ts2py::Options::default()) {
            panic!(
                "expected a module for\n{source}\ngot\n  {}",
                lines.join("\n  ")
            );
        }
    }
}

/// J87-3 (#316 G1): what the G1 constructs still refuse, each where JS and Python would part.
#[test]
fn g1_refusals() {
    // J88-2 lowered `finally` and reading a catch binding (the runtime answers only what JS
    // would read of a Python exception, `code`, and refuses the rest; tests/g2.rs).
    // A `continue` in a C-style loop would skip the update in Python.
    assert_refused(
        "export function f(n: number): number {\n  let s = 0;\n  for (let i = 0; i < n; i += 1) {\n    if (i === 2) continue;\n    s += i;\n  }\n  return s;\n}\n",
        "t.ts:3:3: unsupported continue in a C-style for loop: for (let i = 0; i < n; i += 1) { ...",
    );
    assert_refused(
        "export function f(n: number): number {\n  let i = 0;\n  for (i = 1; i < n; i += 1) {}\n  return i;\n}\n",
        "t.ts:3:8: unsupported C-style for loop init other than a let declaration: i = 1",
    );
    // `Math.max(...x)` over anything not proven an array (a Python `*` of a dict is its keys).
    assert_refused(
        "export function f(x: any): number {\n  return Math.max(...x);\n}\n",
        "t.ts:2:19: unsupported spread of a value not proven an array: ...x",
    );
    assert_refused(
        "export class A {}\nexport class B extends A {}\n",
        "t.ts:2:24: unsupported extends anything but an Error class: A",
    );
    assert_refused(
        "export function f(): unknown {\n  return process.argv;\n}\n",
        "t.ts:2:10: unsupported global process: process",
    );
}

/// J88-2 (#316 G2): what the G2 constructs still refuse.
#[test]
fn g2_refusals() {
    // A Node module's function with no adapter row, through a namespace import.
    assert_refused(
        "import * as fs from 'node:fs';\nexport function f(p: string): void {\n  fs.watch(p);\n}\n",
        "t.ts:3:3: unsupported node:fs function watch: no declared adapter: fs.watch(p)",
    );
    // A namespace import of anything but a Node builtin.
    assert_refused(
        "import * as m from './m.js';\nexport const x = 1;\n",
        "t.ts:1:8: unsupported default or namespace import: * as m",
    );
    // `Atomics.wait` on anything but a fresh buffer: a notify could end it early.
    assert_refused(
        "export function f(a: Int32Array): void {\n  Atomics.wait(a, 0, 0, 5);\n}\n",
        "t.ts:2:3: unsupported Atomics.wait other than a sleep on a fresh buffer: Atomics.wait(a, 0, 0, 5)",
    );
    // A compound assignment through anything but a local object.
    assert_refused(
        "export function f(o: { a: { n: number } }): void {\n  o.a.n += 1;\n}\n",
        "t.ts:2:3: unsupported compound assignment to a property of anything but a local: o.a.n += 1",
    );
    // `<<` is lowered; `>>` and `>>>` are not.
    assert_refused(
        "export function f(a: number): number {\n  return a >> 1;\n}\n",
        "t.ts:2:10: unsupported operator >>: a >> 1",
    );
}
