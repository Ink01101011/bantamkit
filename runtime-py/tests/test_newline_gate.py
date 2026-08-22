"""W6: a fixture that means specific bytes writes bytes, or something turns red.

WHAT THE DEFECT IS, AND WHY W1'S SWEEP COULD NOT REACH IT. `encoding=` and `newline=` are
two different arguments. W1 gave every text open in this repository an explicit encoding,
which fixes WHICH bytes a character becomes; it does not touch line-ending translation,
which is `newline=`. A text-mode write with `newline=None` -- the default everywhere in
this repo -- translates every `\\n` to `os.linesep` on the way out. That is a no-op on
macOS and Linux and `\\r\\n` on Windows, so a string carrying a literal `\\r\\n` lands as
`\\r\\r\\n` there and the file's BYTES differ by platform.

That is invisible for ordinary prose, where a line ending is just a line ending. It is
fatal wherever the line ending is load-bearing: MIME/MHTML boundaries, HTTP-shaped headers,
`\\r\\n`-delimited protocol fixtures, and anything asserting a byte offset, a byte length or
a byte-for-byte identity.

MEASURED, the one real instance, at `106bb38`: `test_docread.py`'s MHTML fixture wrote 237
bytes of `multipart/related` through `Path.write_text`. Translated, it is 253 bytes with all
16 `\\r\\n` turned into `\\r\\r\\n`; no `--B` line matches the declared boundary; and
`extract` returns one part of 11 rows with zero omissions instead of one part of 1 row with
two. That is the windows-latest failure `assert ('mhtml' == 'mhtml' ...`.

THE INCLUSION RULE, stated once and applied mechanically: **a `str` carrying a literal
carriage return, handed to a file-writing call that did not name `newline=`.** `str` is the
whole of it -- a `str` can only reach the disk through a text-mode stream, because writing
`str` to a binary handle is a `TypeError` -- so the rule needs no mode tracking and cannot
be fooled by a handle opened three frames away.

What the rule deliberately EXCLUDES, and why each is genuinely correct:

* `write_bytes(...)` / `open(..., "wb")` -- a binary stream translates nothing, ever.
* `open(..., "w", newline="")` or `newline="\\n"` -- translation explicitly disabled.
* a `bytes` payload, including `rb"{\\rtf1..."`. The detector tests the EVALUATED constant,
  so a raw literal's `\\r` -- backslash then `r`, as in the RTF control word at
  `test_docread.py:787` -- is correctly not a carriage return.
* `zipfile.writestr(...)` -- a zip member is written as bytes; there is no text layer.
* a `write_text` of ordinary prose. On Windows it lands as CRLF and every reader in this
  repo reads it back through text mode, which normalizes CRLF to `\\n` again. MEASURED
  consequence: every committed digest in `test_criticreplay.py` is over a `read_text`
  result (`criticreplay.py:583`, `sha256_text` at `:447`), so it is translation-invariant.
  Sweeping those 224 sites would be noise.

THE POPULATION, MEASURED at `106bb38` over the 101 committed Python files: 225 write-family
calls, of which **1** carried a `str` with a literal carriage return. The class has exactly
one member, and this file is what keeps it at one.

WHAT THIS GATE CANNOT SEE, WITH THE SHAPE NAMED. It is static: a CRLF string assembled at
runtime -- read from somewhere, built by `join`, or interpolated through a non-constant
`f`-string -- is invisible to it. At `106bb38` there were none. It resolves three shapes
past a bare literal, each because a real regression would take it: adjacent and `+`
concatenation, a constant-only f-string, and `NAME.decode(...)` of a module-level bytes
constant, which is what a revert of THIS unit's fix would look like. It is also
deliberately over-broad on bare `.write(...)`: it cannot tell a file handle from an
`io.StringIO`, which translates nothing, so a future CRLF write into a StringIO would be a
false positive. There are zero today, which is why this file carries no escape hatch to
silence one -- an unused escape hatch is the more expensive of the two.

NEVER MEASURED: the Windows run itself. Every number here was taken on macOS, where the
translation is reproduced deliberately via `newline="\\r\\n"` (see
`test_docread.py::test_a_text_mode_write_is_what_breaks_the_boundary`) rather than observed.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Calls that put a payload on disk through a stream that may translate line endings.
# `writestr` is absent on purpose: a zip member is bytes. `print(file=...)` is here because
# it is a text-mode write with the same default.
_WRITE_METHODS = {"write_text", "write", "writelines"}


def _keyword(call: ast.Call, name: str) -> ast.keyword | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw
    return None


def _bytes_constants(tree: ast.AST) -> dict[str, bytes]:
    """Module-level `NAME = b"..."` bindings, so `NAME.decode(...)` can be resolved.

    Without this the gate has a hole exactly where the fix put the bait: once a CRLF fixture
    is correctly declared as a bytes constant, the cheapest way to regress it is
    `write_text(NAME.decode("utf-8"))`, whose payload is a call rather than a literal. That
    is the shape a reverting author reaches for first, so it is the shape this must see.
    """
    constants: dict[str, bytes] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, bytes):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = node.value.value
    return constants


def _str_value(node: ast.AST, constants: dict[str, bytes] | None = None) -> str | None:
    """The `str` this expression evaluates to, or None if it is not a literal `str`.

    Tests the EVALUATED value, never the source text, which is what makes `rb"{\\rtf1"` and
    `r"a\\rb"` correctly invisible: their `\\r` is two characters, not a carriage return.
    Adjacent string literals are already one `Constant` by the time the parser is done;
    explicit `+` and a constant-only f-string are the two shapes that still need walking.
    """
    constants = constants or {}
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _str_value(node.left, constants), _str_value(node.right, constants)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts = [_str_value(v, constants) for v in node.values]
        return "".join(p for p in parts if p is not None) or None
    # `NAME.decode(...)` where NAME is a module-level bytes constant: the payload is a call,
    # but its value is known, and a CR in it reaches a text-mode write all the same.
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "decode"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in constants
    ):
        return constants[node.func.value.id].decode("utf-8", errors="replace")
    return None


def _handles_that_named_newline(tree: ast.AST) -> set[str]:
    """Names bound to a stream opened with an explicit `newline=`, so `.write` on them is safe.

    `newline=` is given to `open`, but the violation would be spotted at `.write`, one
    statement later -- so without this the correct shape `with p.open("w", newline="") as h:`
    is reported forever, and a gate that cries wolf gets deleted. Both binding forms this
    repo uses are covered: a `with ... as name` item and a plain `name = open(...)`.

    Deliberately scope-naive: the name is exempt for the whole file, not for its block. That
    over-exempts a file that reuses the same handle name for a translating stream elsewhere,
    which is the safe direction for a gate (it under-reports rather than cries wolf) and is
    stated here rather than hidden. There are no such reuses at `106bb38`.
    """
    exempt: set[str] = set()

    def opener(value: ast.AST) -> bool:
        return isinstance(value, ast.Call) and _keyword(value, "newline") is not None

    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if opener(item.context_expr) and isinstance(item.optional_vars, ast.Name):
                    exempt.add(item.optional_vars.id)
        elif isinstance(node, ast.Assign) and opener(node.value):
            exempt |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return exempt


def crlf_text_writes(tree: ast.AST) -> list[tuple[int, str]]:
    """Every call handing a `str` with a literal carriage return to an untranslated write."""
    found: list[tuple[int, str]] = []
    exempt = _handles_that_named_newline(tree)
    constants = _bytes_constants(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name, attribute = func.attr, True
        elif isinstance(func, ast.Name):
            name, attribute = func.id, False
        else:
            continue
        if name == "print" and not attribute:
            if _keyword(node, "file") is None:
                continue  # stdout is not a file this repo asserts bytes about
            payloads = list(node.args)
        elif name in _WRITE_METHODS and attribute:
            if isinstance(func.value, ast.Name) and func.value.id in exempt:
                continue  # this stream named its translation when it was opened
            payloads = node.args[:1]
        else:
            continue
        if any(kw.arg is None for kw in node.keywords):
            continue  # `**kwargs` may carry `newline`; unprovable either way
        if _keyword(node, "newline") is not None:
            continue  # translation named explicitly, whatever it was named as
        for payload in payloads:
            value = _str_value(payload, constants)
            if value is not None and "\r" in value:
                found.append((node.lineno, f"{name}() with {value.count(chr(13))} CR"))
                break
    return sorted(found)


def write_family_calls(tree: ast.AST) -> int:
    """The denominator: how many write-family calls the walk actually visited.

    Without this the census node has no scale, and a `crlf_text_writes` that walked nothing
    would be indistinguishable from a repository with no violations.
    """
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _WRITE_METHODS | {"write_bytes", "writestr"}
    )


def _python_files() -> list[Path]:
    """The committed set, for the reason `test_encoding_gate.py` gives: a deleted file stays
    listed, so it is a missing path rather than a node that quietly stops being collected."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    ).stdout
    return sorted(REPO_ROOT / line for line in out.split("\0") if line)


PYTHON_FILES = _python_files()


def test_the_scan_has_something_to_scan():
    """`_python_files()` returning nothing would make the census below vacuously green."""
    assert len(PYTHON_FILES) >= 80, f"only {len(PYTHON_FILES)} Python files found"


def test_no_str_carrying_a_carriage_return_is_written_through_text_mode():
    """The census. MEASURED at `106bb38`: 1 violation in 225 write-family calls; now 0."""
    violations: list[str] = []
    denominator = 0
    for path in PYTHON_FILES:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        denominator += write_family_calls(tree)
        relative = path.relative_to(REPO_ROOT)
        violations += [f"{relative}:{line} {kind}" for line, kind in crlf_text_writes(tree)]
    assert denominator >= 150, f"only {denominator} write-family calls seen; the walk is short"
    assert violations == [], (
        f"{len(violations)} of {denominator} write-family calls hand a CRLF string to a "
        "translating text-mode write. Use write_bytes, or name newline=:\n  "
        + "\n  ".join(violations)
    )


def test_the_detector_finds_the_violation_it_is_shown():
    """The detector's red demonstration: it is not a function that returns [].

    Line 4 is the exact shape `test_docread.py:1163` had before this unit, adjacent-literal
    concatenation and all, so a rewrite that stops matching it is red HERE rather than
    silently turning the census node into a green that measures nothing.
    """
    source = (
        "from pathlib import Path\n"
        "def f(p, handle, out):\n"
        "    Path(p).write_text('MIME-Version: 1.0\\r\\n'\n"
        "                       'Content-Type: multipart/related\\r\\n\\r\\n')\n"
        "    handle.write('GET / HTTP/1.1\\r\\n')\n"
        "    handle.writelines('a\\r\\n')\n"
        "    handle.write('one' + '\\r\\n' + 'two')\n"
        "    print('X-Header: v\\r\\n', file=out)\n"
    )
    found = crlf_text_writes(ast.parse(source))
    assert [line for line, _ in found] == [3, 5, 6, 7, 8], found
    assert found[0][1] == "write_text() with 3 CR"


def test_the_detector_leaves_the_correct_shapes_alone():
    """Every way of writing CRLF that is right on Windows, and the two that only look wrong.

    `rb"{\\rtf1"` is the live one: `test_docread.py:787` writes that RTF control word, and a
    detector matching source text rather than evaluated values would flag it forever.
    """
    source = (
        "from pathlib import Path\n"
        "import zipfile\n"
        "def f(p, z, handle):\n"
        "    Path(p).write_bytes(b'MIME-Version: 1.0\\r\\n')\n"
        "    Path(p).write_bytes(rb'{\\rtf1\\ansi Policy\\par}')\n"
        "    Path(p).write_text('a\\r\\nb', newline='')\n"
        "    Path(p).write_text('ordinary prose\\nsecond line\\n')\n"
        "    handle.write(r'a literal backslash r\\r here')\n"
        "    z.writestr('m.txt', 'a\\r\\nb')\n"
        "    with open(p, 'w', newline='\\r\\n') as g:\n"
        "        g.write('a\\r\\nb')\n"
    )
    assert crlf_text_writes(ast.parse(source)) == []


def test_the_decoded_bytes_constant_is_seen_through():
    """The regression shape the fix itself creates, and the one a literal-only gate misses.

    Once the MHTML fixture is a bytes constant, `write_text(NAME.decode("utf-8"))` is the
    cheapest way back to the defect and its payload is a call, not a literal. MEASURED: with
    `_bytes_constants` removed, the mutation below runs 113 nodes green on this machine.
    Only a constant carrying a CR counts -- the prose constant here must stay unflagged.
    """
    source = (
        "from pathlib import Path\n"
        'CRLF = b"MIME-Version: 1.0\\r\\n--B--\\r\\n"\n'
        'PROSE = b"ordinary\\nlines\\n"\n'
        "def f(p, q):\n"
        '    Path(p).write_text(CRLF.decode("utf-8"), encoding="utf-8")\n'
        '    Path(q).write_text(PROSE.decode("utf-8"), encoding="utf-8")\n'
    )
    tree = ast.parse(source)
    assert set(_bytes_constants(tree)) == {"CRLF", "PROSE"}
    assert crlf_text_writes(tree) == [(5, "write_text() with 2 CR")]


def test_the_handle_exemption_is_narrow():
    """The exemption is the one way this gate could go vacuously green, so it is pinned.

    `_handles_that_named_newline` that returned every name -- or that keyed on `open` rather
    than on `newline=` being present -- would silence the census while leaving five green
    nodes above it. Both handles here are opened by the same call in the same shape; only the
    one that named its translation may be exempt.
    """
    source = (
        "from pathlib import Path\n"
        "def f(p, q):\n"
        "    with Path(p).open('w', encoding='utf-8', newline='') as named:\n"
        "        named.write('a\\r\\nb')\n"
        "    with Path(q).open('w', encoding='utf-8') as silent:\n"
        "        silent.write('a\\r\\nb')\n"
        "    loose = open(p, 'w', encoding='utf-8')\n"
        "    loose.write('a\\r\\nb')\n"
    )
    tree = ast.parse(source)
    assert _handles_that_named_newline(tree) == {"named"}
    assert crlf_text_writes(tree) == [(6, "write() with 1 CR"), (8, "write() with 1 CR")]


def test_the_denominator_counts_the_writes_it_walks_past():
    """A census with no denominator cannot tell 'none found' from 'nothing looked at'."""
    source = (
        "from pathlib import Path\n"
        "def f(p, z, handle):\n"
        "    Path(p).write_text('a')\n"
        "    Path(p).write_bytes(b'a')\n"
        "    handle.write('a')\n"
        "    handle.writelines(['a'])\n"
        "    z.writestr('m', 'a')\n"
        "    return len('not a write')\n"
    )
    assert write_family_calls(ast.parse(source)) == 5
