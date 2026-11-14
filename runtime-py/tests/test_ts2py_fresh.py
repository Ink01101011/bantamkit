"""The committed generated planner is the one `runtime-ts/src/workplan.ts` compiles to (#314).

`bantamkit/_generated/workplan.py` is committed so that building or installing the
package never needs Rust. The price is that it can go stale: someone edits the
TypeScript and the Python keeps serving the old planner. ts2py writes the sha256 of the
source bytes into line 2 of every module it emits, so this gate compares that header with
the TypeScript on disk and fails, naming the regenerate command, the moment they part.

The runtime support module is checked the same way against the copy ts2py embeds
(`tools/ts2py/src/runtime.py`, which `--emit-runtime` writes out byte for byte).

Behaviour, not just freshness, is gated by `node tools/conformance/run.mjs --suite ts2py`,
which recompiles the TypeScript from scratch every run.
"""

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GENERATED = REPO / "runtime-py" / "src" / "bantamkit" / "_generated"
SOURCE = REPO / "runtime-ts" / "src" / "workplan.ts"
RUNTIME_SOURCE = REPO / "tools" / "ts2py" / "src" / "runtime.py"

REGENERATE = (
    "regenerate with:\n"
    "  cargo run --release --manifest-path tools/ts2py/Cargo.toml -- "
    "runtime-ts/src/workplan.ts -o runtime-py/src/bantamkit/_generated/workplan.py "
    "--runtime-module ._ts2py_runtime\n"
    "  cargo run --release --manifest-path tools/ts2py/Cargo.toml -- "
    "--emit-runtime runtime-py/src/bantamkit/_generated/_ts2py_runtime.py\n"
    "(cargo lives at ~/.cargo/bin/cargo if it is not on PATH; see docs/porting.md, "
    "Generated modules)"
)


def source_header(generated: Path, source: Path) -> tuple[str, str]:
    """(the header line the module carries, the header line the source on disk calls for)."""
    lines = generated.read_text(encoding="utf-8").splitlines()
    carried = lines[1] if len(lines) > 1 else "(no second line)"
    wanted = "# source-sha256: " + hashlib.sha256(source.read_bytes()).hexdigest()
    return carried, wanted


def test_generated_workplan_names_the_typescript_on_disk():
    carried, wanted = source_header(GENERATED / "workplan.py", SOURCE)
    assert carried == wanted, (
        f"bantamkit/_generated/workplan.py is stale against {SOURCE.relative_to(REPO)}: "
        f"it carries {carried!r}, the source needs {wanted!r}; {REGENERATE}"
    )


def test_generated_runtime_is_the_one_ts2py_emits():
    committed = (GENERATED / "_ts2py_runtime.py").read_bytes()
    assert committed == RUNTIME_SOURCE.read_bytes(), (
        "bantamkit/_generated/_ts2py_runtime.py differs from tools/ts2py/src/runtime.py; "
        + REGENERATE
    )


def test_the_gate_goes_red_on_a_changed_source(tmp_path):
    # The comparison itself, proved able to fail: one byte appended to a copy of the
    # TypeScript moves the hash the committed header is held to.
    changed = tmp_path / "workplan.ts"
    changed.write_bytes(SOURCE.read_bytes() + b"\n")
    carried, wanted = source_header(GENERATED / "workplan.py", changed)
    assert carried != wanted
