"""`docs/conformance.md`'s suite table against the suites that actually run.

WHAT THE DEFECT WAS, AND WHY IT NEEDED A GATE RATHER THAN A FIX. The page's heading
said "The fourteen suites" over fourteen table rows while
`node tools/conformance/run.mjs --list` answered FIFTEEN: `skillaudit` had run in
`--all` since job44 and was never added. J45-11 found it by hand while editing the page
for another reason, added the row, and corrected the heading — and that closed the
INSTANCE while leaving the SHAPE wide open, because nothing in this tree compared the
page against the directory. The next suite would have gone unlisted exactly the same way.

This is the same class as `test_served_tool_count_records.py`'s: a number that lives only
in prose, next to a number a program can answer, with nothing joining them. That gate was
built after "seven tools" survived in three layers; this one is built after "fourteen
suites" survived over fifteen.

WHAT IT KEYS ON, AND WHY NOT `--list`. `tools/conformance/run.mjs` builds its suite list
by reading `tools/conformance/suites/*.mjs` — "Drop a module in `suites/` and it runs",
as the page itself says. So the directory IS the authority, and reading it directly keeps
this gate node-free and fast. A copy of the list kept here would be a third place for the
number to go stale, in the direction that hides the defect, so there is none.

BOTH DIRECTIONS, deliberately. A suite with no row is the defect that already happened; a
row naming a suite that no longer exists is the same staleness pointing the other way, and
a gate that checked only one of them would pass through a rename.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SUITES_DIR = REPO / "tools" / "conformance" / "suites"
PAGE = REPO / "docs" / "conformance.md"

#: The words the heading may spell, as far as anyone is likely to take this table.
#: Ends deliberately past today's count — and `test_the_heading_number_is_spellable`
#: makes the ending LOUD rather than silent, which is the lesson J45-12 carried over
#: from `test_served_tool_count_records.py`'s word table topping out at the surface.
WORDS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "twenty-one": 21, "twenty-two": 22,
    "twenty-three": 23, "twenty-four": 24, "twenty-five": 25,
}

_HEADING = re.compile(r"^## The ([a-z-]+) suites\s*$", re.MULTILINE)
_ROW = re.compile(r"^\| `([a-z0-9-]+)` \|", re.MULTILINE)


def _suites() -> list[str]:
    return sorted(p.stem for p in SUITES_DIR.glob("*.mjs"))


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_the_scan_finds_something_to_check() -> None:
    """A gate that passes by finding nothing is the defect wearing a green tick."""
    suites = _suites()
    assert len(suites) >= 10, f"only {len(suites)} suite modules found under {SUITES_DIR}"
    rows = _ROW.findall(_page())
    assert len(rows) >= 10, (
        f"only {len(rows)} table rows matched in {PAGE.name} — the row pattern has "
        "probably stopped matching, which is a defect in this gate and not a pass"
    )
    assert _HEADING.search(_page()) is not None, (
        f"no `## The <word> suites` heading in {PAGE.name}; the heading pattern is stale"
    )


def test_every_suite_that_runs_has_a_row_on_the_page() -> None:
    """The direction the real incident took: a suite runs in `--all` and is undocumented."""
    rows = set(_ROW.findall(_page()))
    missing = [s for s in _suites() if s not in rows]
    assert not missing, (
        "these suites run in `node tools/conformance/run.mjs --all` and have no row in "
        f"docs/conformance.md's table: {missing}\n"
        "  `skillaudit` went unlisted this way from job44 until 2026-09-07."
    )


def test_no_row_names_a_suite_that_no_longer_runs() -> None:
    """The other direction, so a rename cannot pass through by leaving the old row."""
    suites = set(_suites())
    stale = [r for r in _ROW.findall(_page()) if r not in suites]
    assert not stale, (
        "docs/conformance.md's table names suites that no module in "
        f"tools/conformance/suites/ provides: {stale}"
    )


def test_the_heading_counts_the_rows_it_stands_over() -> None:
    """"The fourteen suites" over fifteen suites is the sentence this node exists for."""
    word = _HEADING.search(_page()).group(1)
    stated = WORDS.get(word)
    assert stated is not None, (
        f"the heading spells {word!r}, which is not in this gate's word table — add it, "
        "and see `test_the_heading_number_is_spellable` for why the table ends at all"
    )
    served = len(_suites())
    assert stated == served, (
        f"docs/conformance.md's heading says {word} ({stated}) suites and "
        f"tools/conformance/suites/ holds {served}"
    )


def test_the_heading_number_is_spellable() -> None:
    """The word table must reach today's count, or this gate goes QUIET as it grows.

    Kept separate from the node above so the two failures read differently: one says the
    page is stale, this one says THIS GATE is. Without it, a seventeenth suite would make
    the heading unreadable to `WORDS` and the assertion above would fail with a message
    about a word rather than about the page — or, had the lookup been written to skip an
    unknown word, would have passed silently. That is exactly how
    `test_served_tool_count_records.py`'s table came to top out at the served surface.
    """
    served = len(_suites())
    spelled = {value: word for word, value in WORDS.items()}
    assert served in spelled, (
        f"{served} suites run and this gate's `WORDS` cannot spell it (table ends at "
        f"{max(WORDS.values())}). Add the word; the heading check reads it."
    )
