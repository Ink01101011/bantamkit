"""The checks behind tools/release/compiled-gate.sh (#316 G4, J90-RF2), one subcommand each.

    compiled_gate.py unpack WHEEL SRC     put the wheel's extensions into SRC (a runtime-py/src)
    compiled_gate.py probe SRC            the compile set imports from extension files under SRC
    compiled_gate.py logger LOG           install the load logger in this interpreter's site
    compiled_gate.py loads LOG SRC        judge the load log written during pytest and --all

Each exits 0 when its property holds and 1 with the reason otherwise. Run them with the gate's
venv interpreter: the extension suffix that must match is that interpreter's.
`runtime-py/tests/test_compiled_gate.py` drives `unpack` and `loads` on made-up inputs, so a
check that stopped refusing would be red without a compiled build.
"""

from __future__ import annotations

import importlib
import json
import sys
import sysconfig
import zipfile
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path

# The modules hatch_build.py never compiles (`NOT_COMPILED`): the package marker and the adapters.
NOT_COMPILED = ("__init__", "_ts2py_adapters")
GENERATED = "bantamkit._generated."


def compile_set(src: Path) -> list[str]:
    """The stems mypyc compiles, from the `.py` files under `src` (what hatch_build.py compiles)."""
    gen = src / "bantamkit" / "_generated"
    return sorted(p.stem for p in gen.glob("*.py") if p.stem not in NOT_COMPILED)


def unpack(wheel: Path, src: Path) -> str:
    """Extract every extension of `wheel` into `src`; refuse a wheel that is not this build."""
    suffix = EXTENSION_SUFFIXES[0]
    want = compile_set(src)
    with zipfile.ZipFile(wheel) as z:
        exts = [n for n in z.namelist() if n.endswith(tuple(EXTENSION_SUFFIXES))]
        wrong = [n for n in exts if not n.endswith(suffix)]
        if wrong:
            raise SystemExit(f"extensions built for another interpreter (this one loads *{suffix}): {wrong[:3]}")
        groups = [n for n in exts if "/" not in n and "__mypyc." in n]
        mods = sorted(
            n.rsplit("/", 1)[1].split(".", 1)[0]
            for n in exts
            if n.startswith("bantamkit/_generated/") and n.count("/") == 2
        )
        if len(groups) != 1 or mods != want:
            raise SystemExit(
                f"not a compiled build of this tree: {len(mods)} module extensions for {len(want)} "
                f"modules, group libraries {groups}; missing {sorted(set(want) - set(mods))}, "
                f"extra {sorted(set(mods) - set(want))}"
            )
        for n in exts:
            z.extract(n, src)
    return f"unpacked {len(mods)} module extensions and {groups[0]}"


def probe(src: Path) -> str:
    """Import the compile set the way the suites do; every module must be an extension under src."""
    src = src.resolve()
    import bantamkit
    import bantamkit.mcpserver as server

    where = Path(bantamkit.__file__).resolve()
    if not where.is_relative_to(src):
        raise SystemExit(f"bantamkit imported from {where}, not from {src}")
    want = compile_set(src)
    pure = []
    for stem in want:
        f = importlib.import_module(GENERATED + stem).__file__ or ""
        if not (f.endswith(tuple(EXTENSION_SUFFIXES)) and Path(f).resolve().is_relative_to(src)):
            pure.append(f"{stem}: {f}")
    if pure:
        raise SystemExit("loaded from source, not an extension: " + "; ".join(pure))
    groups = [m.__file__ for n, m in list(sys.modules.items()) if n.endswith("__mypyc")]
    if len(groups) != 1 or Path(groups[0]).resolve().parent != src:
        raise SystemExit(f"mypyc's group library was not loaded from {src}: {groups}")
    field = server.build_identity()["compiled"]
    if field != f"mypyc ({len(want)} compiled, 1 interpreted)":
        raise SystemExit(f"build_identity's compiled field is {field!r}")
    return f"{len(want)} of {len(want)} compile-set modules from extensions; compiled = {field}"


LOGGER = '''\
# tools/release/compiled_gate.py (J90-RF2): record where bantamkit._generated modules were loaded
# from, at the exit of every process on this interpreter. Silent on any failure.
import atexit as _atexit


def _bk_compiled_gate_record():
    try:
        import json, os, sys
        mods = {n: getattr(m, "__file__", None) for n, m in list(sys.modules.items())
                if n.startswith("bantamkit._generated.")}
        if mods:
            with open(__LOG__, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"pid": os.getpid(), "modules": mods}) + "\\n")
    except Exception:
        pass


_atexit.register(_bk_compiled_gate_record)
'''


LOGGER_NAME = "_bk_compiled_gate"


def logger(log: Path) -> str:
    """A module and a `.pth` line that imports it, in the venv's site-packages.

    Not `sitecustomize.py`: only the first one on `sys.path` is imported, and Homebrew's CPython
    3.14 ships its own in the standard library directory, ahead of the venv's (measured: the
    first 3.14 gate recorded 0 processes, and failed on it). `site` runs every `import` line of
    every `.pth` file in each site directory, whatever else the interpreter ships.
    """
    site = Path(sysconfig.get_paths()["purelib"])
    module, pth = site / f"{LOGGER_NAME}.py", site / f"{LOGGER_NAME}.pth"
    for path in (module, pth):
        if path.exists():
            raise SystemExit(f"{path} already exists; the gate's venv must be its own")
    module.write_text(LOGGER.replace("__LOG__", repr(str(log)), 1), encoding="utf-8")
    pth.write_text(f"import {LOGGER_NAME}\n", encoding="utf-8")
    return f"load logger at {pth}"


def loads(log: Path, src: Path) -> str:
    """Fail on any compile-set module loaded from a `.py` under `src`, or on no compiled load."""
    src = src.resolve()
    skip = {GENERATED + stem for stem in NOT_COMPILED}
    procs = touching = compiled = 0
    pure_in_tree: list[str] = []
    elsewhere = {"compiled": 0, "pure": 0}
    for line in log.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        procs += 1
        touched = False
        for name, f in rec["modules"].items():
            if name in skip or not f:
                continue
            ext = f.endswith(tuple(EXTENSION_SUFFIXES))
            if Path(f).resolve().is_relative_to(src):
                touched = True
                if ext:
                    compiled += 1
                else:
                    pure_in_tree.append(f"pid {rec['pid']}: {name} from {f}")
            else:
                elsewhere["compiled" if ext else "pure"] += 1
        touching += touched
    summary = (
        f"{procs} processes recorded; {touching} loaded the tree's modules: {compiled} module "
        f"loads from extensions, {len(pure_in_tree)} from .py; outside the tree (a test's own "
        f"copy): {elsewhere['compiled']} compiled, {elsewhere['pure']} pure"
    )
    if pure_in_tree:
        listed = "\n   ".join(pure_in_tree[:20])
        raise SystemExit(f"{summary}\ncompile-set modules were loaded from source in the tree under test:\n   {listed}")
    if compiled == 0:
        raise SystemExit(f"{summary}\nno process loaded a compiled module from the tree; the gate measured nothing")
    return summary


def main(argv: list[str]) -> int:
    commands = {
        "unpack": lambda a: unpack(Path(a[0]), Path(a[1])),
        "probe": lambda a: probe(Path(a[0])),
        "logger": lambda a: logger(Path(a[0])),
        "loads": lambda a: loads(Path(a[0]), Path(a[1])),
    }
    if not argv or argv[0] not in commands:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        print(f"   {commands[argv[0]](argv[1:])}")
    except SystemExit as exc:
        print(f"compiled_gate.py {argv[0]}: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
