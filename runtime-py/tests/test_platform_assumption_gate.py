"""Every test that assumes POSIX must say so, in both runtimes' suites.

WHAT THIS EXISTS FOR, and it is a list of things that actually happened rather than a
list of things that could. On 2026-09-05 CI ran on Windows for the first time in weeks
and reported twenty-four failures. Nine of them were one mistake wearing four costumes:

  * a fixture wrote `#!/bin/sh` into a file and then EXECUTED it. Windows answers
    `OSError: [WinError 193] %1 is not a valid Win32 application`, and it answers it from
    the test's own liveness check, before the property under test is ever reached.
  * a fixture called `chmod(0)` or `chmod(0o500)` to build an unreadable file or an
    unwritable directory. Windows honours neither: the read succeeds, the write succeeds,
    and the assertion gets the opposite of what it asked for.
  * a watcher wrote its verdict from a `SIGTERM` handler. `child.kill('SIGTERM')` on
    Windows is `TerminateProcess`; the handler never runs, and the test failed with
    `ENOENT ... verdict.json` while saying nothing about the thing it was watching.
  * a fixture wrote a file literally named `docs\\junk.docx`. On POSIX that is one file
    whose name contains a backslash — the point of the case. On Windows it names a file
    inside a directory that does not exist.

None of these is a defect in the product. Every one of them is a test describing a
machine it was not running on, and every one was invisible for as long as nobody ran the
suite on Windows.

THE RULE. A test that uses one of these constructs must, somewhere inside its own body,
either name the platform (`sys.platform`, `os.name`, `process.platform`, a `skipif`, a
`windows_cannot_construct`, a `skip:`) or carry the marker `platform-checked:` with a
sentence saying why it is portable. Four words either way, and the next person to write
one of these gets the question asked at the moment they are best placed to answer it.

WHAT THIS DELIBERATELY DOES NOT DO. It does not try to decide whether the guard is
CORRECT — that is what CI is for, and CI is the thing that found all of this. It only
refuses the silent case: a POSIX assumption with nothing anywhere near it that has
considered another platform.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PY_TESTS = REPO / "runtime-py" / "tests"
TS_TESTS = REPO / "runtime-ts" / "test"

# The marker a writer adds when the construct IS portable and the reason is not obvious.
MARKER = "platform-checked:"

# Anything here means the enclosing test has thought about more than one platform.
GUARDS = (
    "sys.platform",
    "os.name",
    "process.platform",
    "skipif",
    "windows_cannot_construct",
    "posix_only",
    "windows_only",
    "skip:",
    "winOnly",
    "PATHEXT",
    MARKER,
)

# Each entry is (name, pattern, what Windows does instead). The names are the sentences a
# failure prints, so they say what to fix rather than what was matched.
ASSUMPTIONS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "a #!/bin/sh fixture is executed",
        re.compile(r"#!/bin/sh"),
        "Windows cannot execute a file with a shebang and no extension: WinError 193",
    ),
    (
        "chmod removes a permission",
        re.compile(r"chmod(?:Sync)?\s*\(\s*[^,)]*,?\s*0o?[0-7]{0,3}\s*\)"),
        "Windows honours only the read-only bit; a 0 or 0o500 mode changes nothing a "
        "read or a write has to obey",
    ),
    (
        "a child is controlled with a signal",
        re.compile(r"SIGTERM|SIGINT|SIGKILL"),
        "there are no POSIX signals on Windows; kill() is TerminateProcess and no handler runs",
    ),
    (
        "a filename literal contains a backslash",
        re.compile(r"""['"][^'"\n]*\\\\[a-zA-Z0-9_.-]+\.(?:docx|txt|json|jsonl|md|yaml|py|mjs)['"]"""),
        "a backslash is a path separator on Windows, so the literal names a file in a "
        "directory rather than a file whose name contains one",
    ),
)


def _blocks(text: str, opener: re.Pattern[str]) -> list[tuple[int, str]]:
    """Split a test file into (start line, body) at each test declaration.

    Line-based and crude on purpose. A construct's guard is what sits in the same test, and
    the enclosing test is what a reader looks at; anything cleverer would need a parser per
    language for no more accuracy than this.

    THE BLOCK STARTS AT THE DECORATOR, NOT AT `def`. `@windows_cannot_construct(...)` spans
    several lines, and a block beginning at `def test_` leaves the guard in the PREVIOUS
    block — which made the first version of this gate report as unguarded the very tests
    written to be guarded. The walk back over contiguous non-blank lines fixes that whatever
    shape the decorator takes.
    """
    lines = text.split("\n")
    starts = []
    for i, line in enumerate(lines):
        if not opener.match(line):
            continue
        j = i
        while j > 0 and lines[j - 1].strip():
            j -= 1
        starts.append(j)
    if not starts:
        return [(1, text)]
    bounds = [0, *starts, len(lines)]
    seen = sorted(set(bounds))
    return [
        (seen[k] + 1, "\n".join(lines[seen[k] : seen[k + 1]]))
        for k in range(len(seen) - 1)
    ]


# `async def` AND INDENTED `test(`, both found by review and both silent holes.
#
# `^def test_` never matched an `async def test_`, so an async test was not a block boundary
# at all: its body joined the block above it and INHERITED that block's guard. Thirteen of
# `test_eventlog.py`'s tests are async, and an offence inside one of them was being reported
# at the previous test's line number. `^test\(` had the same hole for the eighteen indented
# `test(` calls in the Node suite.
#
# A gate whose scanner cannot see a construct reports zero offences and looks like a pass.
# That is the "silent case" this module's own docstring says it refuses, and it was refusing
# it for some tests and not others.
#
# Python matches at column ZERO deliberately: a nested `def test_helper` inside a test is not
# a boundary, and treating it as one would split a guard away from the body it guards.
# JavaScript matches with leading whitespace because a `test(` inside a `describe(` IS the
# declaration.
PY_OPENER = re.compile(r"^(?:async )?def test_", re.MULTILINE)
TS_OPENER = re.compile(r"^\s*test\(", re.MULTILINE)


def _offences(path: Path, opener: re.Pattern[str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    found = []
    for line_no, body in _blocks(text, opener):
        if any(guard in body for guard in GUARDS):
            continue
        for name, pattern, consequence in ASSUMPTIONS:
            if pattern.search(body):
                rel = path.relative_to(REPO)
                found.append(f"{rel}:~{line_no}: {name} — {consequence}")
    return found


def _files() -> list[tuple[Path, re.Pattern[str]]]:
    here = Path(__file__).name
    out = [(p, PY_OPENER) for p in sorted(PY_TESTS.glob("test_*.py")) if p.name != here]
    out += [(p, TS_OPENER) for p in sorted(TS_TESTS.glob("*.test.mjs"))]
    return out


BASELINE_PATH = PY_TESTS / "data" / "platform-assumption-baseline.json"


def _baseline() -> dict[str, list[str]]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _names(path: Path, opener: re.Pattern[str]) -> set[str]:
    """The construct NAMES this file trips today, without the explanatory tail."""
    text = path.read_text(encoding="utf-8")
    names = set()
    for _, body in _blocks(text, opener):
        if any(guard in body for guard in GUARDS):
            continue
        for name, pattern, _consequence in ASSUMPTIONS:
            if pattern.search(body):
                names.add(name)
    return names


@pytest.mark.parametrize(("path", "opener"), _files(), ids=lambda v: getattr(v, "name", ""))
def test_a_posix_assumption_names_the_platform_or_says_why_it_does_not_have_to(path, opener):
    """A RATCHET, and the difference from a rug is the test below this one.

    Thirteen files trip this gate today. Deciding all thirteen in one sitting would produce
    thirteen hurried sentences about platforms, which is worse than none: this repository has
    already been bitten twice this week by a comment that asserted its own correctness. So
    what exists is recorded, nothing new may join it, and the record is required to shrink —
    `test_the_baseline_holds_nothing_that_is_already_fixed` fails the moment an entry stops
    being true, which is what stops the list from becoming furniture.
    """
    # `as_posix()` AND NOT `str()`. The baseline is a tracked file with `/` in its keys, and
    # `str(PurePath)` gives `\` on Windows — so every lookup missed there and this gate, whose
    # whole subject is platform assumptions, failed on every file for a platform assumption of
    # its own. Measured on CI 2026-09-05, the first Windows run after it landed.
    rel = path.relative_to(REPO).as_posix()
    allowed = set(_baseline().get(rel, []))
    offences = [
        o
        for o in _offences(path, opener)
        if o.split(": ", 1)[1].rsplit(" — ", 1)[0] not in allowed
    ]
    assert not offences, (
        "a test uses a POSIX-only construct with nothing in it that has considered another "
        "platform:\n  "
        + "\n  ".join(offences)
        + "\n\nAdd a platform guard (skipif / process.platform / windows_cannot_construct), or "
        f"the marker `{MARKER}` with a sentence saying why it is portable."
    )


def test_the_baseline_holds_nothing_that_is_already_fixed():
    """The ratchet's pawl. Without it the baseline is a list nobody ever shortens.

    An entry that no longer trips has been fixed, and leaving it behind would let the same
    construct come back into that file unnoticed — the allowance outliving the thing it was
    allowing.
    """
    by_path = {p.relative_to(REPO).as_posix(): (p, opener) for p, opener in _files()}
    stale = []
    for rel, names in sorted(_baseline().items()):
        if rel not in by_path:
            stale.append(f"{rel}: the file is gone; drop the entry")
            continue
        path, opener = by_path[rel]
        live = _names(path, opener)
        for name in names:
            if name not in live:
                stale.append(f"{rel}: `{name}` no longer trips — remove it from the baseline")
    assert not stale, "the baseline has entries that are no longer true:\n  " + "\n  ".join(stale)


def test_the_gate_can_see_each_construct_it_claims_to_see():
    """The gate's own red proof, because a scanner that matches nothing passes everything.

    Each pattern is run against a sample that must match and a sample that must not. Without
    this the whole file could be a regex typo and every parametrised case above would be
    green — which is the vacuity this repository keeps finding in its own gates.
    """
    samples = {
        "a #!/bin/sh fixture is executed": (
            "stub.write_text('#!/bin/sh\\nexit 0\\n')",
            "write_text('hello')",
        ),
        "chmod removes a permission": ("locked.chmod(0)", "shutil.copy2(a, b)"),
        "a child is controlled with a signal": ("watcher.kill('SIGTERM')", "watcher.kill()"),
        "a filename literal contains a backslash": (
            r"""join(dir, 'docs\\junk.docx')""",
            "join(dir, 'docs', 'junk.docx')",
        ),
    }
    for name, pattern, _ in ASSUMPTIONS:
        hit, miss = samples[name]
        assert pattern.search(hit), f"{name}: the pattern no longer matches {hit!r}"
        assert not pattern.search(miss), f"{name}: the pattern matches {miss!r}, which is fine"


def test_the_gate_reads_both_suites_and_neither_is_empty():
    """A path that stopped resolving would make this file pass by scanning nothing."""
    py = [p for p, _ in _files() if p.suffix == ".py"]
    ts = [p for p, _ in _files() if p.suffix == ".mjs"]
    assert len(py) > 20, f"only {len(py)} Python test files found under {PY_TESTS}"
    assert len(ts) > 15, f"only {len(ts)} Node test files found under {TS_TESTS}"
