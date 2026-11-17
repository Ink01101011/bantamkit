//! J90-P7B (#316 G4): three shortcuts in the code ts2py writes beside the generated modules, each
//! pinned equal to what it shortcuts.
//!
//! - `_js_py_round_float9` (runtime.py; the adapters' `py_round_float9`, moved into the runtime so
//!   a compiled build compiles it) carries `pyRoundFloat9`'s own J68-5 fast path: a float `0 < x`
//!   with `x * 1e9 < 2**40` whose fraction is more than 1e-3 from one half is the nearer whole
//!   over 1e9. Pinned equal to CPython's `round(x, 9)` (value, sign and type) over 400,000 seeded
//!   values, near-ties and the values just either side of the 1e-3 band included, with the fast
//!   path TAKEN for most of them.
//! - `_posix_basename` / `_posix_dirname` (adapters.py) answer a path that does not end in `/` from
//!   its last `/`, found in C. Pinned equal to the statement-for-statement port of Node's
//!   `lib/path.js` (written out below, as it stood before) over every path of up to seven units
//!   drawn from `a`, `/`, `.` and `é`, and a list of spelled cases.
//! - `py_read_text` opens a POSIX path `PurePath` leaves as it is with `io.open`, as
//!   `Path.read_text` does, without building the `Path`; `_pure_as_is(p)` is a sufficient test of
//!   `str(PurePath(p)) == p`. Pinned: `_pure_as_is` never claims a path `PurePath` rewrites (the
//!   same exhaustive pool), and `py_read_text` answers what `Path(p).read_text(encoding='utf-8')`
//!   answers (the text, or the exception's type and message) for a file, a CRLF file, a file that
//!   is not UTF-8, a directory, a missing path, and each spelled with a doubled `/`, a `.` part and
//!   a trailing `/`.

use std::path::{Path, PathBuf};
use std::process::Command;

fn python() -> String {
    std::env::var("TS2PY_PYTHON").unwrap_or_else(|_| "python3".to_string())
}

fn run_python(dir: &Path, script: &str) -> String {
    let python = python();
    let run = Command::new(&python)
        .arg("-c")
        .arg(script)
        .current_dir(dir)
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
    std::fs::create_dir_all(dir.join("pkg")).unwrap();
    std::fs::write(dir.join("pkg").join("__init__.py"), "").unwrap();
    std::fs::write(dir.join("pkg").join("_ts2py_runtime.py"), ts2py::RUNTIME).unwrap();
    std::fs::write(
        dir.join("pkg").join("_ts2py_adapters.py"),
        ts2py_bantamkit::adapters_module("._ts2py_runtime"),
    )
    .unwrap();
    dir
}

#[test]
fn round9_fast_path_equals_cpython_round() {
    let dir = scratch("j90p7b-round");
    let out = run_python(
        &dir,
        r#"
import math, random, struct
from pkg._ts2py_runtime import _js_py_round_float9 as fast
from pkg._ts2py_adapters import py_round_float9
assert py_round_float9 is fast
random.seed(9)
pool = [0.0, -0.0, 1.0, -1.0, 0.5, 1e-9, 5e-10, 4.9999999995e-10, 1099.511627775, 1099.511627776,
        1099.511627777, float("inf"), -float("inf"), 0.1, 0.123456789500, 7, -7, 0, 2**53 + 1, 3.0]
gens = [lambda: random.random(), lambda: random.random() * 1000, lambda: random.uniform(0, 1e-6),
        lambda: random.uniform(0, 1100), lambda: -random.random() * 50,
        lambda: (random.randrange(10**12) + 0.5) / 1e9, lambda: (random.randrange(10**12) + 0.4989) / 1e9,
        lambda: (random.randrange(10**12) + 0.5011) / 1e9, lambda: (random.randrange(10**12) + 0.499) / 1e9,
        lambda: struct.unpack("d", struct.pack("Q", random.getrandbits(62)))[0]]
for g in gens:
    pool += [g() for _ in range(40000)]
bad = []
taken = 0
for x in pool:
    want = round(x if type(x) is float else float(x) if abs(x) > 2**53 else x, 9)
    got = fast(x)
    if type(x) is float and x > 0 and x * 1e9 < 2**40 and abs(x * 1e9 - math.floor(x * 1e9) - 0.5) > 1e-3:
        taken += 1
    same = type(got) is type(want) and (got == want or (got != got and want != want))
    if same and type(got) is float and got == 0:
        same = math.copysign(1, got) == math.copysign(1, want)
    if not same:
        bad.append((x, got, want))
print(len(pool), taken, bad[:5])
"#,
    );
    let parts: Vec<&str> = out.trim().splitn(3, ' ').collect();
    let total: usize = parts[0].parse().unwrap();
    let taken: usize = parts[1].parse().unwrap();
    assert_eq!(parts[2], "[]", "fast round differs from round(x, 9): {out}");
    assert!(
        total >= 400_000 && taken > total / 2,
        "fast path not taken enough: {out}"
    );
}

#[test]
fn posix_basename_and_dirname_equal_the_port() {
    let dir = scratch("j90p7b-path");
    let out = run_python(
        &dir,
        r#"
import itertools
from pkg import _ts2py_adapters as A

def basename(path):
    start = 0
    end = -1
    matched_slash = True
    for i in range(len(path) - 1, -1, -1):
        if path[i] == "/":
            if not matched_slash:
                start = i + 1
                break
        elif end == -1:
            matched_slash = False
            end = i + 1
    if end == -1:
        return ""
    return path[start:end]

def dirname(path):
    if not path:
        return "."
    has_root = path[0] == "/"
    end = -1
    matched_slash = True
    for i in range(len(path) - 1, 0, -1):
        if path[i] == "/":
            if not matched_slash:
                end = i
                break
        else:
            matched_slash = False
    if end == -1:
        return "/" if has_root else "."
    if has_root and end == 1:
        return "//"
    return path[:end]

pool = ["", "/", "//", "///", "a", "a/", "/a", "//a", "///a", "a//b", "/a/b/", "a/b/c.md", ".",
        "..", "x/./y", "/Users/k/.bantamkit/index/0123456789abcdef.json", "é/ü.md", "\\a\\b", "a/\ud800"]
for n in range(1, 8):
    pool += ["".join(p) for p in itertools.product("a/.é", repeat=n)]
bad = [p for p in pool if A._posix_basename(p) != basename(p) or A._posix_dirname(p) != dirname(p)]
print(len(pool), bad[:5])
"#,
    );
    assert!(out.trim().ends_with(" []"), "path fast paths differ: {out}");
}

#[test]
fn py_read_text_equals_path_read_text() {
    let dir = scratch("j90p7b-read");
    let out = run_python(
        &dir,
        r#"
import itertools, os, pathlib
from pkg import _ts2py_adapters as A

pool = []
for n in range(1, 8):
    pool += ["".join(p) for p in itertools.product("a/.é", repeat=n)]
claimed = [p for p in pool if A._pure_as_is(p) and str(pathlib.PurePath(p)) != p]

base = os.path.abspath("files")
os.makedirs(base + "/sub")
open(base + "/plain.txt", "w", encoding="utf-8").write("one ไทย\ntwo")
open(base + "/crlf.txt", "wb").write(b"a\r\nb\rc\n")
open(base + "/latin.txt", "wb").write(b"caf\xe9")
cases = []
for name in ("plain.txt", "crlf.txt", "latin.txt", "sub", "gone.txt"):
    for spelled in (f"{base}/{name}", f"{base}//{name}", f"{base}/./{name}", f"{base}/{name}/", f"{base}/sub/../{name}"):
        cases.append(spelled)
cases += ["", ".", "files/plain.txt", "./files/plain.txt", "files/plain.txt/."]

def answer(f, p):
    try:
        return ("ok", f(p))
    except Exception as e:
        return (type(e).__name__, str(e))

def reference(p):
    try:
        return pathlib.Path(p).read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise A.PyUnicodeDecodeError(str(error)) from None

bad = [p for p in cases if answer(A.py_read_text, p) != answer(reference, p)]
taken = sum(1 for p in cases if A._pure_as_is(p))
print(len(claimed), len(cases), taken, bad[:5])
"#,
    );
    let parts: Vec<&str> = out.trim().splitn(4, ' ').collect();
    assert_eq!(
        parts[0], "0",
        "_pure_as_is claims a path PurePath rewrites: {out}"
    );
    assert_eq!(
        parts[3], "[]",
        "py_read_text differs from Path.read_text: {out}"
    );
    let taken: usize = parts[2].parse().unwrap();
    assert!(taken >= 5, "the io.open path is never taken: {out}");
}
