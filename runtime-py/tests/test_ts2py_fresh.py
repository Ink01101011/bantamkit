"""The committed generated modules are the ones `runtime-ts/src` compiles to (#314, #315, #316).

`bantamkit/_generated/` is committed so that building or installing the package never needs
Rust. The price is that it can go stale: someone edits the TypeScript and the Python keeps
serving the old planner or the old fact-file codec. ts2py writes the sha256 of the source bytes
into line 2 of every module it emits, so this gate compares that header with the TypeScript on
disk and fails, naming the regenerate command, the moment they part.

The runtime support module and the adapter module are checked the same way against the copies
ts2py embeds (`tools/ts2py/python/ts2py/runtime.py`, which `--emit-runtime` writes out in its
shipped form — comments and docstrings left in the source, J90-P2 — and bantamkit's
`tools/ts2py-bantamkit/adapters.py`, which `--emit-adapters` writes with its runtime import filled
in). Since #337 the compiler holds no bantamkit name: the adapters, the `shipped_note` and the
generator name come from bantamkit's host file `tools/ts2py-bantamkit/ts2py.toml` (`--config`).

Every `.py` in the directory must be one of those, so a generated module committed later cannot
sit outside this gate. Behaviour, not just freshness, is gated by
`node tools/conformance/run.mjs --suite ts2py` (which also recompiles every committed file and
compares it byte for byte) and `--suite ts2py-codec`.

The header names the TypeScript, not the body: a hand-edited body keeps its header. So when cargo
is present (on PATH or at `~/.cargo/bin/cargo`) this file also compiles every module again with
the five regenerate commands, into a scratch directory, and compares each committed file with it
byte for byte, as `--suite ts2py`'s F4 compare does (J90-RF F2). Without cargo that test is skipped
and says so; the header tests above still run.
"""

import hashlib
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GENERATED = REPO / "runtime-py" / "src" / "bantamkit" / "_generated"
TS = REPO / "runtime-ts" / "src"
RUNTIME_SOURCE = REPO / "tools" / "ts2py" / "python" / "ts2py" / "runtime.py"
HOST = REPO / "tools" / "ts2py-bantamkit" / "ts2py.toml"
_HOST = tomllib.loads(HOST.read_text(encoding="utf-8"))
ADAPTERS_SOURCE = HOST.parent / _HOST["adapter_source"]

# Each generated module and the TypeScript it is compiled from.
MODULES = {
    "workplan.py": TS / "workplan.ts",
    "pyyaml.py": TS / "memory" / "pyyaml.ts",
    "factfile.py": TS / "memory" / "factfile.ts",
    # #316 G1 (J87-3).
    "pricing.py": TS / "pricing.ts",
    "jobbudget.py": TS / "jobbudget.ts",
    # #316 G2 (J88-2), compiled in the same ts2py call as G1.
    "logsegment.py": TS / "storage" / "logsegment.ts",
    "eventlog.py": TS / "eventlog.ts",
    "tokenledger.py": TS / "tokenledger.ts",
    # #316 G3 U1 (J89-2), compiled in the same ts2py call as G1 and G2.
    "usage.py": TS / "memory" / "usage.ts",
    # #316 G3 (J89-3), the same call.
    "retrieval.py": TS / "memory" / "retrieval.ts",
    # #316 G3 U2 (J89-4b), the same call.
    "store.py": TS / "memory" / "store.ts",
    # #316 G3 U3 (J89-5), the same call.
    "native.py": TS / "memory" / "native.ts",
    # #316 G3 U3 (J89-5a), the same call.
    "queries.py": TS / "memory" / "queries.ts",
    # #316 G3 U3 (J89-5b), the same call.
    "layers.py": TS / "memory" / "layers.ts",
    # #316 G3 U3 (J89-5c), the same call.
    "dream.py": TS / "memory" / "dream.ts",
    # #316 G3 U4 (J89-6), the same call.
    "component.py": TS / "memory" / "component.ts",
    # #316 G4 (J90-2), the same call: the lock and the hot index.
    "lock.py": TS / "storage" / "lock.ts",
    "hotindex.py": TS / "storage" / "hotindex.ts",
    # #316 G4 (J90-3), the same call: the cold index, retention, the tiers and the package file.
    "coldindex.py": TS / "storage" / "coldindex.ts",
    "retention.py": TS / "storage" / "retention.ts",
    "tiers.py": TS / "storage" / "tiers.ts",
    "index.py": TS / "storage" / "index.ts",
}
# The two support modules ts2py writes from copies it embeds; and the hand-written package file.
SUPPORT = {"_ts2py_runtime.py", "_ts2py_adapters.py"}
HAND_WRITTEN = {"__init__.py"}

_CARGO = (
    "cargo run --release --manifest-path tools/ts2py/Cargo.toml -- "
    "--config tools/ts2py-bantamkit/ts2py.toml"
)
REGENERATE = (
    "regenerate with:\n"
    f"  {_CARGO} runtime-ts/src/workplan.ts -o runtime-py/src/bantamkit/_generated/workplan.py "
    "--runtime-module ._ts2py_runtime\n"
    f"  {_CARGO} runtime-ts/src/memory/pyyaml.ts runtime-ts/src/memory/factfile.ts "
    "--out-dir runtime-py/src/bantamkit/_generated --runtime-module ._ts2py_runtime\n"
    f"  {_CARGO} runtime-ts/src/pricing.ts runtime-ts/src/jobbudget.ts "
    "runtime-ts/src/storage/logsegment.ts runtime-ts/src/eventlog.ts runtime-ts/src/tokenledger.ts "
    "runtime-ts/src/memory/usage.ts runtime-ts/src/memory/retrieval.ts "
    "runtime-ts/src/memory/store.ts runtime-ts/src/memory/native.ts "
    "runtime-ts/src/memory/queries.ts runtime-ts/src/memory/layers.ts "
    "runtime-ts/src/memory/dream.ts runtime-ts/src/memory/component.ts "
    "runtime-ts/src/storage/lock.ts runtime-ts/src/storage/hotindex.ts "
    "runtime-ts/src/storage/coldindex.ts runtime-ts/src/storage/retention.ts "
    "runtime-ts/src/storage/tiers.ts runtime-ts/src/storage/index.ts "
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


# bantamkit's `shipped_note` (`tools/ts2py-bantamkit/ts2py.toml`), which `shipped` writes.
SHIPPED_NOTE = _HOST["shipped_note"]


def shipped(text: str) -> str:
    """`shipped` in tools/ts2py/src/lib.rs, line for line (J90-P2): the leading comment block and
    `SHIPPED_NOTE` (the host's note), then every line but the full-line comments and the docstring
    of each function or class whose body goes on after it; nothing inside a triple-quoted string is
    touched."""
    lines = text.split("\n")
    out = []

    def indent(line: str) -> int:
        return len(line) - len(line.lstrip())

    i = 0
    while i < len(lines) and lines[i].startswith("#"):
        out.append(lines[i])
        i += 1
    out.append(SHIPPED_NOTE)
    in_string = False
    depth = None
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if in_string:
            out.append(line)
            in_string = line.count('"""') % 2 == 0
            i += 1
            continue
        if depth is None and line.lstrip().startswith(("def ", "async def ", "class ")):
            depth = 0
        if depth is not None:
            depth += sum(line.count(c) for c in "([{") - sum(line.count(c) for c in ")]}")
            out.append(line)
            i += 1
            if depth == 0 and stripped.endswith(":"):
                depth = None
                body = lines[i].lstrip() if i < len(lines) else ""
                if body.startswith(('"""', 'r"""')):
                    opener = 4 if body.startswith("r") else 3
                    if '"""' in body[opener:]:
                        end = i
                    else:
                        end = next((k for k in range(i + 1, len(lines)) if '"""' in lines[k]), None)
                    if end is not None:
                        rest = (k for k in range(end + 1, len(lines)) if lines[k].strip())
                        after = next(rest, None)
                        width = len(lines[i]) - len(body)
                        if after is not None and indent(lines[after]) >= width:
                            i = end + 1
            continue
        if stripped.startswith("#"):
            i += 1
            continue
        out.append(line)
        in_string = line.count('"""') % 2 == 1
        i += 1
    return "\n".join(out)


def expected_runtime() -> bytes:
    # `--emit-runtime`: the embedded copy, in its shipped form.
    return shipped(RUNTIME_SOURCE.read_text(encoding="utf-8")).encode("utf-8")


def expected_adapters() -> bytes:
    # `Host::adapters_module` in tools/ts2py/src/host.rs: the host's adapter_source, runtime
    # import filled in, in its shipped form.
    text = ADAPTERS_SOURCE.read_text(encoding="utf-8").replace("__RUNTIME__", "._ts2py_runtime")
    return shipped(text).encode("utf-8")


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
    assert committed == expected_runtime(), (
        "bantamkit/_generated/_ts2py_runtime.py differs from tools/ts2py/python/ts2py/runtime.py; "
        + REGENERATE
    )


def test_generated_adapters_are_the_ones_ts2py_emits():
    committed = (GENERATED / "_ts2py_adapters.py").read_bytes()
    assert committed == expected_adapters(), (
        "bantamkit/_generated/_ts2py_adapters.py differs from tools/ts2py-bantamkit/adapters.py; "
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


# ------------------------------------------------------------ J90-RF F2: the body, byte for byte

# The sources of each ts2py call, as the regenerate commands above (and `--suite ts2py`) give them.
_CODEC = ["runtime-ts/src/memory/pyyaml.ts", "runtime-ts/src/memory/factfile.ts"]
_G1_G4 = [
    f"runtime-ts/src/{m}.ts"
    for m in (
        "pricing", "jobbudget", "storage/logsegment", "eventlog", "tokenledger", "memory/usage",
        "memory/retrieval", "memory/store", "memory/native", "memory/queries", "memory/layers",
        "memory/dream", "memory/component", "storage/lock", "storage/hotindex", "storage/coldindex",
        "storage/retention", "storage/tiers", "storage/index",
    )
]


def _cargo() -> str | None:
    found = shutil.which("cargo")
    if found:
        return found
    home = Path(os.path.expanduser("~")) / ".cargo" / "bin" / "cargo"
    return str(home) if home.is_file() else None


def _ts2py(cargo: str, *args: str) -> None:
    cmd = [cargo, "run", "-q", "--release", "--manifest-path", "tools/ts2py/Cargo.toml", "--",
           "--config", "tools/ts2py-bantamkit/ts2py.toml", *args]
    got = subprocess.run(cmd, cwd=REPO, capture_output=True, encoding="utf-8", errors="replace")
    assert got.returncode == 0, f"ts2py failed ({' '.join(args[:3])} ...):\n{got.stderr[-4000:]}"


@pytest.fixture(scope="module")
def fresh_emit(tmp_path_factory) -> Path:
    """Every generated module compiled again now, with the flags the committed ones were made by."""
    cargo = _cargo()
    if cargo is None:
        pytest.skip("cargo not found (PATH, ~/.cargo/bin): the body compare needs ts2py; the "
                    "source-sha256 header tests still ran")
    out = tmp_path_factory.mktemp("ts2py-fresh")
    rt = ["--runtime-module", "._ts2py_runtime"]
    _ts2py(cargo, "runtime-ts/src/workplan.ts", "-o", str(out / "workplan.py"), *rt)
    _ts2py(cargo, *_CODEC, "--out-dir", str(out), *rt)
    _ts2py(cargo, *_G1_G4, "--out-dir", str(out), *rt)
    _ts2py(cargo, "--emit-runtime", str(out / "_ts2py_runtime.py"))
    _ts2py(cargo, "--emit-adapters", str(out / "_ts2py_adapters.py"))
    return out


def test_fresh_emit_covers_every_generated_file(fresh_emit):
    made = {p.name for p in fresh_emit.glob("*.py")}
    assert made == set(MODULES) | SUPPORT, (
        f"ts2py wrote {sorted(made)}; the committed set is {sorted(set(MODULES) | SUPPORT)}"
    )


def _body_differs(committed: Path, fresh: Path) -> str | None:
    have, want = committed.read_bytes(), fresh.read_bytes()
    if have == want:
        return None
    a, b = have.split(b"\n"), want.split(b"\n")
    pairs = enumerate(zip(a, b, strict=False))
    line = next((i for i, (x, y) in pairs if x != y), min(len(a), len(b)))
    return (f"{committed.name} differs from what ts2py writes now at line {line + 1} "
            f"({len(have)} bytes committed, {len(want)} fresh)")


@pytest.mark.parametrize("module", sorted(set(MODULES) | SUPPORT))
def test_generated_body_is_what_ts2py_writes(module, fresh_emit):
    # A hand-edited body keeps its source-sha256 header, so the header test above cannot see it.
    differs = _body_differs(GENERATED / module, fresh_emit / module)
    assert differs is None, f"bantamkit/_generated/{differs}; {REGENERATE}"


def test_the_body_compare_goes_red_on_a_hand_edit(fresh_emit, tmp_path):
    # The comparison itself, proved able to fail: the committed retention module with one line of
    # its body changed (its header untouched) differs from the fresh emit.
    edited = tmp_path / "retention.py"
    text = (GENERATED / "retention.py").read_text(encoding="utf-8")
    assert "return " in text
    edited.write_text(text.replace("return ", "return  ", 1), encoding="utf-8", newline="")
    carried, wanted = source_header(edited, MODULES["retention.py"])
    assert carried == wanted
    assert _body_differs(edited, fresh_emit / "retention.py") is not None
