"""Tests for `charsets-table.py`'s POSIX/Windows discrepancy over `mbcs` and `oem`.

Run directly, not through `npm test` (which must not need a Python interpreter — see
`runtime-ts/test/codec.test.mjs`) and not through `runtime-py/tests` (this script is
`runtime-ts` build tooling, not part of the `runtime-py` package):

    .venv/bin/python -m pytest runtime-ts/scripts/test_charsets_table.py -q

Two things are checked, and neither is "verified on Windows" — there is no Windows
machine on this job and GitHub Actions is off for this account, so CI cannot settle it
either:

  1. THE MEASURED POSIX FACT the fix is a response to: `mbcs.py` and `oem.py` exist as
     files under `encodings.__path__` on this interpreter (so `pkgutil.iter_modules`
     lists them), but `codecs.lookup` raises `LookupError` for both names here — the
     module set the OLD generator built for `SINGLE_BYTE_TABLES` depended on that
     `LookupError`, not on any property of the codecs themselves.
  2. A SIMULATION of the other side of that discrepancy: `codecs.register` can add a
     search function that makes `codecs.lookup('mbcs')` and `codecs.lookup('oem')`
     genuinely succeed on THIS POSIX interpreter, resolving to real, working codecs
     (`cp1252` / `cp437` — the pair the generator's own comment names as the common
     Windows alias targets). That is an honest stand-in for what CPython's Windows
     build does natively; it is still a simulation, and nothing below claims otherwise.
     Run the generator under that simulation and confirm `mbcs`/`oem` do NOT appear in
     `SINGLE_BYTE_TABLES` — i.e. the named exclusion (`PLATFORM_VARIANT_CODECS`) holds
     regardless of whether the lookup guard would have let them through.

Test-first record: run against the generator BEFORE the `PLATFORM_VARIANT_CODECS` fix,
`test_platform_variant_codecs_survive_a_successful_lookup` fails — the simulated run
puts real `mbcs`/`oem` tables (aliased to `cp1252`/`cp437`, both genuine stateless
single-byte codecs) into `SINGLE_BYTE_TABLES`, because the old guard's only gate was
`codecs.lookup`, and the simulation makes that gate pass. After the fix it passes,
because the module-name exclusion does not care whether the lookup would have
succeeded.
"""

from __future__ import annotations

import codecs
import encodings
import json
import pkgutil
import subprocess
import sys
from pathlib import Path

GENERATOR = Path(__file__).resolve().parent / "charsets-table.py"


def _run_generator(*, simulate_windows: bool) -> str:
    """The generator's stdout, optionally under a simulated Windows codec registry."""
    if not simulate_windows:
        return subprocess.run(
            [sys.executable, str(GENERATOR)], capture_output=True, text=True, encoding="utf-8", check=True
        ).stdout
    wrapper = f"""
import codecs, runpy

# SIMULATION — see module docstring. This registers REAL, WORKING codecs under the
# names "mbcs" and "oem" on this POSIX interpreter, the way CPython's own Windows
# build resolves them natively (to the machine's ANSI / OEM codepage). It is not a
# claim that this IS Windows.
def _search(name):
    if name == "mbcs":
        return codecs.lookup("cp1252")
    if name == "oem":
        return codecs.lookup("cp437")
    return None

codecs.register(_search)
assert codecs.lookup("mbcs").name == "cp1252", "simulation setup failed for mbcs"
assert codecs.lookup("oem").name == "cp437", "simulation setup failed for oem"

runpy.run_path({str(GENERATOR)!r}, run_name="__main__")
"""
    return subprocess.run(
        [sys.executable, "-c", wrapper], capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


def _json_after(text: str, marker: str, open_char: str) -> object:
    """Decode the JSON value that starts at the first `open_char` after `marker`."""
    at = text.index(marker)
    start = text.index(open_char, at)
    value, _ = json.JSONDecoder().raw_decode(text, start)
    return value


def _codec_modules(generated: str) -> list[str]:
    return _json_after(generated, "new Set(", "[")


def _single_byte_table_keys(generated: str) -> list[str]:
    at = generated.index("export const SINGLE_BYTE_TABLES")
    eq = generated.index("=", at)
    return sorted(_json_after(generated[eq:], "=", "{").keys())


# --------------------------------------------------------------- 1. the measured POSIX fact


def test_mbcs_and_oem_files_exist_but_do_not_register_on_this_interpreter():
    """The defect's premise, measured here rather than assumed.

    `pkgutil` lists both `mbcs` and `oem` as modules under `encodings` on THIS (POSIX)
    interpreter — the .py files ship on every platform — while `codecs.lookup` raises
    `LookupError` for both names here. The old generator used exactly that `LookupError`
    as its inclusion test, which is why its module set was POSIX-vs-Windows dependent.
    """
    modules = {m.name for m in pkgutil.iter_modules(encodings.__path__)}
    assert {"mbcs", "oem"} <= modules, f"expected both listed by pkgutil, got {sorted(modules)}"

    for name in ("mbcs", "oem"):
        try:
            codecs.lookup(name)
        except LookupError:
            continue
        raise AssertionError(
            f"codecs.lookup({name!r}) unexpectedly succeeded on this interpreter "
            f"({sys.version}) — the POSIX premise this fix responds to no longer holds here"
        )


# --------------------------------------------------------- 2. the fix, proved with a simulation


def test_platform_variant_codecs_survive_a_successful_lookup():
    """SIMULATION (see module docstring): even when `codecs.lookup` succeeds for `mbcs`/
    `oem`, the generator's `SINGLE_BYTE_TABLES` must not carry them — the exclusion is by
    name (`PLATFORM_VARIANT_CODECS`), not by whether this interpreter's registry happens
    to answer for them.
    """
    generated = _run_generator(simulate_windows=True)
    table_keys = _single_byte_table_keys(generated)
    assert "mbcs" not in table_keys, "mbcs leaked into SINGLE_BYTE_TABLES under the simulated lookup"
    assert "oem" not in table_keys, "oem leaked into SINGLE_BYTE_TABLES under the simulated lookup"


def test_codec_modules_list_is_unaffected_by_the_simulation():
    """`CODEC_MODULES` is the raw `pkgutil` listing (never filtered by `codecs.lookup`), so
    it already carried `mbcs`/`oem` before this fix and must go on doing so — this fix is
    about `SINGLE_BYTE_TABLES` only, and must not narrow `CODEC_MODULES`.
    """
    real = _run_generator(simulate_windows=False)
    simulated = _run_generator(simulate_windows=True)
    real_modules = _codec_modules(real)
    simulated_modules = _codec_modules(simulated)
    assert real_modules == simulated_modules
    assert {"mbcs", "oem"} <= set(real_modules)
