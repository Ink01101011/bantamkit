"""`bantamkit.stdlib312`: CPython 3.12's answers on every interpreter (J90-P8F, #316 G4).

Two halves, and each needs the other. On EVERY interpreter the pins answer the 3.12 literals
below (measured on 3.12.13), so a 3.13 or 3.14 run that loses a pin goes red here, not only in
a conformance suite. On a 3.12 (or 3.11) interpreter the pins answer what the LIVE standard
library answers over the same inputs, so a pin that drifted from 3.12 is caught where 3.12 is
the one running — the conformance references ask the live library below 3.13 and the pins
from 3.13, and this is what makes those the same reference.
"""

from __future__ import annotations

import datetime
import json
import ntpath
import os
import sys
from pathlib import Path, PurePath, PureWindowsPath

import pytest

from bantamkit import _codecs312, stdlib312

LIVE_IS_312 = sys.version_info < (3, 13)

JSON_TEXTS = [
    '{"a":1,}', "[1,]", '{"a":1 ,  }', "[1,\n ]", '{"é":1,}', '{"a":1', "[1,2", '{"a" 1}',
    '"\\u00e9', '{"a": "\\ud83d\\ude00', '"\\\\u00e9', '"\\u00e',
]
JSON_312 = [
    "Expecting property name enclosed in double quotes: line 1 column 8 (char 7)",
    "Expecting value: line 1 column 4 (char 3)",
    "Expecting property name enclosed in double quotes: line 1 column 11 (char 10)",
    "Expecting value: line 2 column 2 (char 5)",
    "Expecting property name enclosed in double quotes: line 1 column 8 (char 7)",
    "Expecting ',' delimiter: line 1 column 7 (char 6)",
    "Expecting ',' delimiter: line 1 column 5 (char 4)",
    "Expecting ':' delimiter: line 1 column 6 (char 5)",
    "Invalid \\uXXXX escape: line 1 column 3 (char 2)",
    "Invalid \\uXXXX escape: line 1 column 15 (char 14)",
    "Unterminated string starting at: line 1 column 1 (char 0)",
    "Invalid \\uXXXX escape: line 1 column 3 (char 2)",
]


def _json_errors(loads) -> list[str]:
    out = []
    for text in JSON_TEXTS:
        with pytest.raises(json.JSONDecodeError) as e:
            loads(text)
        out.append(str(e.value))
    return out


def test_json_errors_are_312s():
    assert _json_errors(stdlib312.json_loads) == JSON_312
    decoder = json.JSONDecoder()
    with pytest.raises(json.JSONDecodeError) as e:
        stdlib312.json_raw_decode(decoder, 'x {"a":1,}', 2)
    assert (e.value.msg, e.value.pos) == ("Expecting property name enclosed in double quotes", 9)
    assert stdlib312.json_loads('{"a": [1, 2]}') == {"a": [1, 2]}


@pytest.mark.skipif(not LIVE_IS_312, reason="the live json is 3.12's only below 3.13")
def test_json_pin_is_the_live_decoder_below_313():
    assert _json_errors(json.loads) == JSON_312


DATE_ARGS = [(2026, 13, 1), (2026, 2, 30), (0, 1, 1), (10000, 1, 1), (2026, 0, 1)]
DATETIME_ARGS = [(2026, 8, 23, 25), (2026, 8, 23, 10, 99), (2026, 8, 23, 10, 0, 61),
                 (2026, 8, 23, 10, 0, 0, 1000000), (2026, 8, 23, -1)]
DATETIME_312 = [
    "month must be in 1..12", "day is out of range for month", "year 0 is out of range",
    "year 10000 is out of range", "month must be in 1..12",
    "hour must be in 0..23", "minute must be in 0..59", "second must be in 0..59",
    "microsecond must be in 0..999999", "hour must be in 0..23",
    "offset must be a timedelta strictly between -timedelta(hours=24) and "
    "timedelta(hours=24), not datetime.timedelta(days=1).",
    "offset must be a timedelta strictly between -timedelta(hours=24) and "
    "timedelta(hours=24), not datetime.timedelta(days=-1).",
]


def _datetime_errors(pin) -> list[str]:
    out = []
    calls = [(datetime.date, a) for a in DATE_ARGS]
    calls += [(datetime.datetime, a) for a in DATETIME_ARGS]
    calls += [(lambda h: datetime.timezone(datetime.timedelta(hours=h)), (h,)) for h in (24, -24)]
    for make, args in calls:
        with pytest.raises(ValueError) as e:
            make(*args)
        out.append(str(pin(e.value)))
    return out


def test_datetime_sentences_are_312s():
    assert _datetime_errors(stdlib312.pin_datetime_error) == DATETIME_312
    other = ValueError("something else")
    assert stdlib312.pin_datetime_error(other) is other


@pytest.mark.skipif(not LIVE_IS_312, reason="the live datetime is 3.12's only below 3.13")
def test_datetime_pin_is_the_identity_below_313():
    assert _datetime_errors(lambda e: e) == DATETIME_312


WIN_RAWS = ["//a", "///a", "////a/b", "//a/b", "//a/b/c", "//a/", "//", "/a", "/a/b/c", "a",
            "C:x", "C:/x", "C:", "\\\\srv\\share\\x", "//?/C:/x", "//?/UNC/srv/share/x",
            "\\\\a/b\\c"]
WIN_ABS_312 = [False, False, True, True, True, False, False, False, False, False, False, True,
               False, True, True, True, True]
NT_ISABS_312 = [True, True, True, True, True, True, True, True, True, False, False, True, False,
                True, True, True, True]
SUFFIX_RAWS = ["/f/a.", "a..", "a.b", ".md", "x", "/f/a.b.", "a.tar.gz"]
SUFFIX_312 = ["", "", ".b", "", "", "", ".gz"]


# 3.11's `PureWindowsPath` parses `//a`, `////a/b` and `//?` with a different algorithm (the
# J63-1b note in `--suite store`, which withholds its winpaths case there), and `win_is_absolute`
# asks the interpreter's own parse for the drive and the root, so the Windows rows are 3.12+.
PARSES_LIKE_312 = sys.version_info >= (3, 12)


def test_path_algebra_is_312s():
    if PARSES_LIKE_312:
        assert [stdlib312.win_is_absolute(r) for r in WIN_RAWS] == WIN_ABS_312
    assert [stdlib312.nt_isabs(r) for r in WIN_RAWS] == NT_ISABS_312
    assert [stdlib312.path_suffix(r) for r in SUFFIX_RAWS] == SUFFIX_312


@pytest.mark.skipif(not LIVE_IS_312, reason="the live pathlib is 3.12's only below 3.13")
def test_path_algebra_pins_are_the_live_library_below_313():
    if PARSES_LIKE_312:
        assert [PureWindowsPath(r).is_absolute() for r in WIN_RAWS] == WIN_ABS_312
    # The pin's rule over the interpreter's own parse is the interpreter's answer (3.11 too).
    assert [stdlib312.win_is_absolute(r) for r in WIN_RAWS] == [
        PureWindowsPath(r).is_absolute() for r in WIN_RAWS
    ]
    assert [ntpath.isabs(r) for r in WIN_RAWS] == NT_ISABS_312
    assert [PurePath(r).suffix for r in SUFFIX_RAWS] == SUFFIX_312


@pytest.mark.skipif(os.name == "nt", reason="a POSIX symlink loop and mode bits")
def test_resolve_raises_on_a_symlink_loop_and_resolves_the_rest(tmp_path):
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    with pytest.raises(RuntimeError) as e:
        stdlib312.path_resolve(loop)
    assert str(e.value) == f"Symlink loop from {os.path.realpath(loop)!r}"
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    assert stdlib312.path_resolve(tmp_path / "link" / "nope") == (real / "nope").resolve()
    if LIVE_IS_312:
        with pytest.raises(RuntimeError) as live:
            loop.resolve()
        assert str(live.value) == str(e.value)


@pytest.mark.skipif(os.name == "nt" or getattr(os, "geteuid", lambda: 1)() == 0,
                    reason="EACCES needs POSIX mode bits and a non-root user")
def test_predicates_raise_on_eacces_and_answer_false_on_the_ignored_errnos(tmp_path):
    shut = tmp_path / "shut"
    shut.mkdir()
    (shut / "a.md").write_text("x", encoding="utf-8")
    shut.chmod(0o444)
    try:
        for ask in (stdlib312.path_exists, stdlib312.path_is_file, stdlib312.path_is_dir):
            with pytest.raises(PermissionError):
                ask(shut / "a.md")
        if LIVE_IS_312:
            for ask in (Path.exists, Path.is_file, Path.is_dir):
                with pytest.raises(PermissionError):
                    ask(shut / "a.md")
    finally:
        shut.chmod(0o755)
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    assert stdlib312.path_exists(tmp_path / "nope") is False
    assert stdlib312.path_exists(afile / "sub") is False  # ENOTDIR
    assert stdlib312.path_exists("bad\0name") is False  # ValueError
    assert stdlib312.path_is_dir(tmp_path) is True
    assert stdlib312.path_is_file(afile) is True
    assert stdlib312.path_is_dir(afile) is False


def test_codecs_resolve_through_the_312_registry():
    for later in ("cp00858", "windows-31j", "ISO_8859-8-I", "cseuckr", "ms874", "ibm01140"):
        assert stdlib312.codec_module(later) is None, later
        with pytest.raises(LookupError):
            stdlib312.codec_decode(b"abc", later)
    assert stdlib312.codec_module("UTF-8") == "utf_8"
    assert stdlib312.codec_module("Latin-1") == "latin_1"
    assert stdlib312.codec_module("Shift_JIS") == "shift_jis"
    assert stdlib312.codec_decode(bytes([0x9B]), "palmos") == "\x9b"
    assert stdlib312.codec_decode("héllo".encode("cp1252"), "windows-1252") == "héllo"


@pytest.mark.skipif(sys.version_info[:2] != (3, 12), reason="the frozen registry is 3.12's")
def test_the_frozen_registry_is_the_live_312_one():
    import encodings
    import encodings.aliases
    import pkgutil

    assert _codecs312.CODEC_ALIASES_312 == encodings.aliases.aliases
    live_modules = {m.name for m in pkgutil.iter_modules(encodings.__path__)}
    assert live_modules == _codecs312.CODEC_MODULES_312
    import codecs

    labels = set(encodings.aliases.aliases) | set(encodings.aliases.aliases.values())
    for label in sorted(labels | {"UTF-8", "ISO-8859-1", "utf 8", "nope", "x-mac-roman"}):
        try:
            live = codecs.lookup(label).name
        except LookupError:
            live = None
        module = stdlib312.codec_module(label)
        assert (None if module is None else codecs.lookup(module).name) == live, label


def test_argparse_is_312_13s_verbatim_everywhere(capsys):
    assert stdlib312.argparse.__name__ == "bantamkit._argparse312"
    source = Path(stdlib312.__file__).with_name("_argparse312.py").read_text(encoding="utf-8")
    body = source.split("\n\n", 1)[1]
    assert body.startswith("# Author: Steven J. Bethard")
    if sys.version_info[:3] == (3, 12, 13):
        import argparse

        assert body == Path(argparse.__file__).read_text(encoding="utf-8")
    parser = stdlib312.argparse.ArgumentParser(prog="p")
    parser.add_argument("--x", choices=["a", "b"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--x", "c"])
    err = capsys.readouterr().err
    assert "invalid choice: 'c' (choose from a, b)" in err, err


RE_PATTERNS = [r"\B", r"\A\B", r"$\B", r"a\B", r"\Bb", r"\b", r"^$", r"\B|x", r"\\B", r"[\]\B]",
               r"(?=\B)"]
RE_STRINGS = ["", "a", "ab", " ", "a b", "-", "--"]
RE_312 = [
    "0011011", "0001011", "0001011", "0010000", "0010000", "0110100", "1000000", "0011011",
    "0000000", "error", "0011011",
]


def _re_rows(search) -> list[str]:
    import re

    rows = []
    for pattern in RE_PATTERNS:
        try:
            rows.append("".join("1" if search(pattern, s) else "0" for s in RE_STRINGS))
        except re.error as e:
            assert stdlib312.pattern_error_kind(e) == "error"
            rows.append("error")
    return rows


def test_re_nonboundary_never_matches_the_empty_string_as_in_312():
    assert _re_rows(stdlib312.re_search) == RE_312


@pytest.mark.skipif(sys.version_info >= (3, 14), reason="3.14 lets \\B match an empty string")
def test_re_pin_is_the_live_search_below_314():
    import re

    assert _re_rows(re.search) == RE_312
