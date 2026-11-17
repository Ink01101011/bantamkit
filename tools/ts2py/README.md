# ts2py (working name)

A compiler from a **subset of TypeScript** to **Python with JavaScript semantics**. One
TypeScript module becomes one Python module that answers every input the way Node answers it:
the same values, the same bytes, the same exceptions. It is written in Rust on
[`oxc_parser`](https://oxc.rs) (exact-pinned); this crate only lowers oxc's AST.

It was built inside bantamkit (#314–#316) so that one TypeScript source could serve both of
bantamkit's runtimes, and it is packaged here as a unit of its own (#337) so that it can leave
for its own repository and registries after bantamkit 1.0.0 with this directory unchanged. The
name is not decided: `ts2py` is taken on PyPI and npm and `ts2python` on PyPI.

## The subset, and the refusal rule

[`SUBSET.md`](SUBSET.md) is the contract: every accepted construct and the Python it becomes.
Anything not listed there is **refused at compile time**, never translated on a best guess:

```
<path>:<line>:<col>: unsupported <construct>: <snippet>
```

one line per offence on stderr, exit status 1, nothing written. A construct whose JavaScript and
Python behaviour differ is lowered only through a runtime helper that reproduces JavaScript
(`python/ts2py/runtime.py`); where no such helper exists, the construct is refused.
[`RULES.md`](RULES.md) is the ledger of every lowering rule and the measurement behind it.

## The host file

The compiler knows no project. What one project must supply comes in one TOML file, `--config`
([`src/host.rs`](src/host.rs) documents every key):

- `[[adapter]]` rows: an import (or a Node global) the compiler does not compile resolves to
  hand-written Python, and only through a row; each row names the module, the name, the Python
  name, its kind, and **why** the hand-written Python is the same function (a row with no reason
  is refused). An import with no compiled module and no row is a compile error.
- `adapter_source`: the hand-written adapter module the rows point into (`--emit-adapters`).
- `[[rebound]]` rows: module-level names hand-written Python rebinds, read at call time under
  mypyc too.
- `generator`, `shipped_note`: the words the generated headers and shipped support modules print.

Without `--config` the host is empty. `tests/fixtures/host/` is a complete small host;
bantamkit's is `tools/ts2py-bantamkit/` in its repository.

## Use

```bash
cargo build --release
target/release/ts2py src/app.ts -o app.py --config ts2py.toml            # runtime inlined
target/release/ts2py src/a.ts src/b.ts --out-dir pkg --runtime-module ._ts2py_runtime --config ts2py.toml
target/release/ts2py --emit-runtime pkg/_ts2py_runtime.py
target/release/ts2py --emit-adapters pkg/_ts2py_adapters.py --config ts2py.toml
```

Output is deterministic: the same inputs give the same bytes, from any working directory (the
header prints the input's path relative to its git checkout), and line 2 of every module is the
sha256 of its TypeScript, so a host can gate staleness without Rust.

## Tests: Node is the oracle

```bash
cargo test --release          # from this directory; needs python3 (TS2PY_PYTHON picks another)
cargo clippy --release --all-targets -- -D warnings
cargo fmt --check
```

The method: a probe is a TypeScript file; its expected output is what **Node printed** for it
(the version is named in the test, e.g. `tests/j90p7.rs`: Node v26.13.0), committed with it.
The test compiles the probe, runs the Python under CPython, and compares byte for byte. With
`TS2PY_MYPYC` naming a `mypyc` (whose Python is `TS2PY_PYTHON`'s), `tests/j90p7.rs` also
compiles the generated module with mypyc and holds the compiled answer to the same Node output.
`tests/boundary.rs` is red if anything in this directory but documentation names a host or
reaches outside the directory; `tests/host.rs` covers the host file.

## Layout, and why

```
Cargo.toml  Cargo.lock      one crate: [lib] (the compiler, src/lib.rs) + [[bin]] ts2py (src/main.rs)
src/                        lower.rs, types.rs, pyfmt.rs (the compiler), host.rs, adapters.rs, cli.rs
python/ts2py/runtime.py     the runtime support module (pure stdlib), embedded by include_str!
tests/                      the compiler's own tests and fixtures, runnable from here alone
SUBSET.md  RULES.md         the contract and the ledger
```

Prior art for shipping a Rust command line to Python and JavaScript users:

- **maturin's `bin` bindings** (https://www.maturin.rs/bindings): "Maturin also supports
  distributing binary applications written in Rust as Python packages using the `bin`
  bindings. Binaries are packaged into the wheel as "scripts" and are available on the user's
  `PATH`." A mixed project keeps its Python under `python-source`.
- **ruff** (`pyproject.toml`, github.com/astral-sh/ruff): `build-backend = "maturin"`,
  `[tool.maturin] bindings = "bin"`, `manifest-path = "crates/ruff/Cargo.toml"`,
  `python-source = "python"`; `python/ruff/__main__.py` finds the binary and `execvp`s it.
- **uv** (`pyproject.toml`, github.com/astral-sh/uv): the same shape, `bindings = "bin"`,
  `manifest-path = "crates/uv/Cargo.toml"`, `python-source = "python"`.
- **biome** (`packages/@biomejs/biome/package.json`, github.com/biomejs/biome): one npm package
  with `"bin": {"biome": "bin/biome"}` and one `optionalDependencies` entry per platform
  (`@biomejs/cli-darwin-arm64`, `@biomejs/cli-linux-x64-musl`, ...), each holding one prebuilt
  binary; npm installs only the one that matches.

So the layout is the maturin mixed layout ruff and uv use, at its smallest: one crate whose
manifest is the root `Cargo.toml` (no workspace needed), and a `python/` source tree for what
ships as Python. Here that Python is the runtime the generated modules import, so a wheel built
this way would carry both the `ts2py` command and an importable `ts2py.runtime`
(`--runtime-module ts2py.runtime`) instead of a vendored copy. An npm distribution would follow
biome's per-platform optional packages. No build or publish step for either is added here: the
name, the registries and the release belong to the split after 1.0.0 (#337).
