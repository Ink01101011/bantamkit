"""The committed generated modules are the ones `runtime-ts/src` compiles to (#314, #315, #316).

`bantamkit/_generated/` is committed so that building or installing the package never needs
Rust. The price is that it can go stale: someone edits the TypeScript and the Python keeps
serving the old planner or the old fact-file codec. ts2py writes the sha256 of the source bytes
into line 2 of every module it emits, so this gate compares that header with the TypeScript on
disk and fails, naming the regenerate command, the moment they part.

The runtime support module and the adapter module are checked the same way against the copies
ts2py embeds (`tools/ts2py/src/runtime.py`, which `--emit-runtime` writes out byte for byte, and
`tools/ts2py/src/adapters.py`, which `--emit-adapters` writes with its runtime import filled in).

Every `.py` in the directory must be one of those, so a generated module committed later cannot
sit outside this gate. Behaviour, not just freshness, is gated by
`node tools/conformance/run.mjs --suite ts2py` (which also recompiles every committed file and
compares it byte for byte) and `--suite ts2py-codec`.
"""

import hashlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GENERATED = REPO / "runtime-py" / "src" / "bantamkit" / "_generated"
TS = REPO / "runtime-ts" / "src"
RUNTIME_SOURCE = REPO / "tools" / "ts2py" / "src" / "runtime.py"
ADAPTERS_SOURCE = REPO / "tools" / "ts2py" / "src" / "adapters.py"

# Each generated module and the TypeScript it is compiled from.
MODULES = {
    "workplan.py": TS / "workplan.ts",
    "pyyaml.py": TS / "memory" / "pyyaml.ts",
    "factfile.py": TS / "memory" / "factfile.ts",
    # #316 G1 (J87-3).
    "pricing.py": TS / "pricing.ts",
    "jobbudget.py": TS / "jobbudget.ts",
}
# The two support modules ts2py writes from copies it embeds; and the hand-written package file.
SUPPORT = {"_ts2py_runtime.py", "_ts2py_adapters.py"}
HAND_WRITTEN = {"__init__.py"}

_CARGO = "cargo run --release --manifest-path tools/ts2py/Cargo.toml --"
REGENERATE = (
    "regenerate with:\n"
    f"  {_CARGO} runtime-ts/src/workplan.ts -o runtime-py/src/bantamkit/_generated/workplan.py "
    "--runtime-module ._ts2py_runtime\n"
    f"  {_CARGO} runtime-ts/src/memory/pyyaml.ts runtime-ts/src/memory/factfile.ts "
    "--out-dir runtime-py/src/bantamkit/_generated --runtime-module ._ts2py_runtime\n"
    f"  {_CARGO} runtime-ts/src/pricing.ts runtime-ts/src/jobbudget.ts "
    "--out-dir runtime-py/src/bantamkit/_generated --runtime-module ._ts2py_runtime\n"
    f"  {_CARGO} --emit-runtime runtime-py/src/bantamkit/_generated/_ts2py_runtime.py\n"
    f"  {_CARGO} --emit-adapters runtime-py/src/bantamkit/_generated/_ts2py_adapters.py\n"
    "(cargo lives at ~/.cargo/bin/cargo if it is not on PATH; see docs/porting.md, "
    "Generated modules)"
)


def source_header(generated: Path, source: Path) -> tuple[str, str]:
    """(the header line the module carries, the header line the source on disk calls for)."""
    lines = generated.read_text(encoding="utf-8").splitlines()
    carried = lines[1] if len(lines) > 1 else "(no second line)"
    wanted = "# source-sha256: " + hashlib.sha256(source.read_bytes()).hexdigest()
    return carried, wanted


def expected_adapters() -> bytes:
    # `adapters_module` in tools/ts2py/src/lib.rs: the embedded copy, runtime import filled in.
    return ADAPTERS_SOURCE.read_bytes().replace(b"__RUNTIME__", b"._ts2py_runtime")


def test_every_file_in_generated_is_gated():
    present = {p.name for p in GENERATED.glob("*.py")}
    assert present == set(MODULES) | SUPPORT | HAND_WRITTEN, (
        f"bantamkit/_generated holds {sorted(present)}; every generated module must be named "
        "in MODULES (with its TypeScript) or SUPPORT in this file"
    )


@pytest.mark.parametrize("module", sorted(MODULES))
def test_generated_module_names_the_typescript_on_disk(module):
    source = MODULES[module]
    carried, wanted = source_header(GENERATED / module, source)
    assert carried == wanted, (
        f"bantamkit/_generated/{module} is stale against {source.relative_to(REPO)}: "
        f"it carries {carried!r}, the source needs {wanted!r}; {REGENERATE}"
    )


def test_generated_runtime_is_the_one_ts2py_emits():
    committed = (GENERATED / "_ts2py_runtime.py").read_bytes()
    assert committed == RUNTIME_SOURCE.read_bytes(), (
        "bantamkit/_generated/_ts2py_runtime.py differs from tools/ts2py/src/runtime.py; "
        + REGENERATE
    )


def test_generated_adapters_are_the_ones_ts2py_emits():
    committed = (GENERATED / "_ts2py_adapters.py").read_bytes()
    assert committed == expected_adapters(), (
        "bantamkit/_generated/_ts2py_adapters.py differs from tools/ts2py/src/adapters.py; "
        + REGENERATE
    )


@pytest.mark.parametrize("module", sorted(MODULES))
def test_the_gate_goes_red_on_a_changed_source(module, tmp_path):
    # The comparison itself, proved able to fail for each module: one byte appended to a copy
    # of its TypeScript moves the hash the committed header is held to.
    source = MODULES[module]
    changed = tmp_path / source.name
    changed.write_bytes(source.read_bytes() + b"\n")
    carried, wanted = source_header(GENERATED / module, changed)
    assert carried != wanted
