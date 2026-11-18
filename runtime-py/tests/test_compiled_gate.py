"""The compiled gate's own checks refuse what they exist to refuse (#316 G4, J90-RF2).

`tools/release/compiled-gate.sh` is the documented way to run pytest and `--all` against the mypyc
build. J90-PF and J90-PF2 reported a compiled `--all` green that had loaded the `.py` files, so the
gate's value is in its refusals: a wheel that is not this tree's compiled build, and a run in
which any process loaded a compile-set module from source in the tree under test (or none loaded
a compiled one at all). These nodes drive `tools/release/compiled_gate.py` on made-up wheels and
load logs, so a check that stopped refusing is red here, on the pure build, without a compiler.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SUFFIX = EXTENSION_SUFFIXES[0]


def _gate():
    path = REPO / "tools" / "release" / "compiled_gate.py"
    spec = importlib.util.spec_from_file_location("compiled_gate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gate = _gate()


@pytest.fixture
def src(tmp_path: Path) -> Path:
    """A runtime-py/src with two compiled modules, the adapters and the package marker."""
    root = tmp_path / "src"
    gen = root / "bantamkit" / "_generated"
    gen.mkdir(parents=True)
    for stem in ("__init__", "_ts2py_adapters", "_ts2py_runtime", "store"):
        (gen / f"{stem}.py").write_text("", encoding="utf-8")
    (root / "bantamkit" / "__init__.py").write_text("", encoding="utf-8")
    return root


def _wheel(tmp_path: Path, names: list[str]) -> Path:
    path = tmp_path / "bantamkit-0-cp3-cp3-any.whl"
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, b"")
        z.writestr("bantamkit/_generated/store.py", b"")
    return path


GROUP = f"0123456789abcdef0123__mypyc{SUFFIX}"
FULL = [
    GROUP,
    f"bantamkit/_generated/_ts2py_runtime{SUFFIX}",
    f"bantamkit/_generated/store{SUFFIX}",
]


def test_unpack_puts_each_extension_where_the_wheel_puts_it(
    src: Path, tmp_path: Path
) -> None:
    said = gate.unpack(_wheel(tmp_path, FULL), src)
    assert "unpacked 2 module extensions" in said
    assert (src / GROUP).is_file(), "the group library goes beside bantamkit/, as in site-packages"
    assert (src / "bantamkit" / "_generated" / f"store{SUFFIX}").is_file()


@pytest.mark.parametrize(
    "names, why",
    [
        (FULL[1:], "group libraries []"),
        ([GROUP, FULL[1]], "missing ['store']"),
        ([], "0 module extensions"),
    ],
    ids=["no-group-library", "a-module-not-compiled", "the-pure-wheel"],
)
def test_unpack_refuses_a_wheel_that_is_not_this_trees_compiled_build(
    src: Path, tmp_path: Path, names: list[str], why: str
) -> None:
    with pytest.raises(SystemExit, match=r".*") as refused:
        gate.unpack(_wheel(tmp_path, names), src)
    assert why in str(refused.value)
    assert not list(src.rglob(f"*{SUFFIX}")), "a refused wheel must leave the tree pure"


def test_unpack_refuses_extensions_for_another_interpreter(src: Path, tmp_path: Path) -> None:
    other = ".cpython-399-elsewhere.so"
    names = [n.replace(SUFFIX, other) for n in FULL]
    with pytest.raises(SystemExit) as refused:
        gate.unpack(_wheel(tmp_path, names), src)
    assert "another interpreter" in str(refused.value)


def _log(tmp_path: Path, records: list[dict[str, str]]) -> Path:
    path = tmp_path / "loads.jsonl"
    path.write_text(
        "".join(json.dumps({"pid": i, "modules": m}) + "\n" for i, m in enumerate(records)),
        encoding="utf-8",
    )
    return path


def test_loads_passes_a_run_that_loaded_extensions_only(src: Path, tmp_path: Path) -> None:
    gen = src / "bantamkit" / "_generated"
    log = _log(tmp_path, [
        {"bantamkit._generated.store": str(gen / f"store{SUFFIX}"),
         "bantamkit._generated._ts2py_adapters": str(gen / "_ts2py_adapters.py")},
        # a test's own pure copy elsewhere is counted, not failed
        {"bantamkit._generated.store": str(tmp_path / "copy" / "store.py")},
    ])
    said = gate.loads(log, src)
    assert "1 module loads from extensions, 0 from .py" in said and "0 compiled, 1 pure" in said


def test_loads_fails_a_run_that_loaded_source_from_the_tree_under_test(
    src: Path, tmp_path: Path
) -> None:
    """The J90-PF shape: a reference process imported the tree's `.py` instead of its extension."""
    gen = src / "bantamkit" / "_generated"
    log = _log(tmp_path, [
        {"bantamkit._generated.store": str(gen / f"store{SUFFIX}")},
        {"bantamkit._generated.store": str(gen / "store.py")},
    ])
    with pytest.raises(SystemExit) as refused:
        gate.loads(log, src)
    assert "loaded from source in the tree under test" in str(refused.value)
    assert "store.py" in str(refused.value)


def test_loads_fails_a_run_that_loaded_nothing_compiled(src: Path, tmp_path: Path) -> None:
    log = _log(tmp_path, [{"bantamkit._generated.store": str(tmp_path / "copy" / "store.py")}])
    with pytest.raises(SystemExit) as refused:
        gate.loads(log, src)
    assert "the gate measured nothing" in str(refused.value)


def test_the_load_logger_records_where_generated_modules_came_from(
    tmp_path: Path, monkeypatch
) -> None:
    log = tmp_path / "loads.jsonl"
    namespace: dict[str, object] = {}
    registered = []
    monkeypatch.setattr("atexit.register", registered.append)
    exec(gate.LOGGER.replace("__LOG__", repr(str(log)), 1), namespace)
    fake = type(sys)("bantamkit._generated.zz_gate_probe")
    fake.__file__ = f"/somewhere/zz_gate_probe{SUFFIX}"
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    assert registered, "the logger must register itself to run at exit"
    registered[0]()
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["modules"][fake.__name__] == fake.__file__


def test_the_logger_runs_from_a_pth_file_in_a_site_directory(tmp_path: Path, monkeypatch) -> None:
    """J90-RF2: a `.pth` line, not `sitecustomize.py`, which Homebrew's 3.14 already ships.

    The first 3.14 gate recorded 0 processes because the interpreter's own `sitecustomize` was
    imported instead. A fresh interpreter that adds the directory as a site dir must record.
    """
    site = tmp_path / "site"
    site.mkdir()
    log = tmp_path / "loads.jsonl"
    monkeypatch.setattr(gate.sysconfig, "get_paths", lambda: {"purelib": str(site)})
    gate.logger(log)
    with pytest.raises(SystemExit, match="already exists"):
        gate.logger(log)
    program = (
        "import site, sys, types\n"
        f"site.addsitedir({str(site)!r})\n"
        "m = types.ModuleType('bantamkit._generated.zz_pth_probe'); m.__file__ = '/x/zz.py'\n"
        "sys.modules[m.__name__] = m\n"
    )
    # `-I -S`: no site directory of this interpreter, so the gate's own logger (when this test
    # runs inside the compiled gate, it is already installed under the same name) is not the one
    # the `.pth` line imports.
    subprocess.run([sys.executable, "-I", "-S", "-c", program], check=True)
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["modules"] == {"bantamkit._generated.zz_pth_probe": "/x/zz.py"}
