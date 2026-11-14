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

#[test]
fn class() {
    assert_refused(
        "export class A { x = 1; }\n",
        "t.ts:1:8: unsupported class: class A { x = 1; }",
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
        "t.ts:2:10: unsupported this: this",
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
    assert_refused(
        "export function f(x: object): string[] {\n  return Object.keys(x);\n}\n",
        "t.ts:2:10: unsupported builtin call Object.keys: Object.keys(x)",
    );
    assert_refused(
        "export function f(s: string): string {\n  return s.toUpperCase();\n}\n",
        "t.ts:2:10: unsupported builtin method .toUpperCase: s.toUpperCase()",
    );
    assert_refused(
        "export function f(): number {\n  return Math.max(1, 2);\n}\n",
        "t.ts:2:10: unsupported builtin call Math.max: Math.max(1, 2)",
    );
}

#[test]
fn other_refusals() {
    assert_refused(
        "export function f(a: any): boolean {\n  return a == 1;\n}\n",
        "t.ts:2:10: unsupported loose equality other than == null: a == 1",
    );
    assert_refused(
        "export function f(a: any): unknown {\n  return a?.b;\n}\n",
        "t.ts:2:10: unsupported optional chaining: a?.b",
    );
    assert_refused(
        "export function f(a: number): number {\n  return a / 2;\n}\n",
        "t.ts:2:10: unsupported operator /: a / 2",
    );
    assert_refused(
        "export function f(xs: number[]): unknown {\n  const g = (x: number) => x;\n  return xs.map(g);\n}\n",
        "t.ts:2:13: unsupported arrow function outside a callback argument: (x: number) => x",
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
    let lines = refusals("class A {}\nexport function f(): unknown {\n  return this;\n}\n");
    assert_eq!(
        lines,
        vec![
            "t.ts:1:1: unsupported class: class A {}",
            "t.ts:3:10: unsupported this: this"
        ]
    );
}

#[test]
fn cli_writes_nothing_and_exits_nonzero() {
    let dir = std::env::temp_dir().join(format!("ts2py-refusal-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let input = dir.join("bad.ts");
    let output = dir.join("bad.py");
    std::fs::write(&input, "export class A {}\n").unwrap();
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
            .ends_with(":1:8: unsupported class: class A {}"),
        "{stderr}"
    );
    std::fs::remove_dir_all(&dir).unwrap();
}
