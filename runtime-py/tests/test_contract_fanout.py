"""RB-P95. The contract surface's wording protection, measured for FAN-OUT, not for presence.

WHAT THIS EXISTS FOR

`docs/eval-data/2026-08-20-j28-contract-mutation-catalogue.py` reports that 31 of the 32
mutable contract strings are pinned by at least one node whose NAME declares it asserts
wording. Re-derived at `9a7b886` with `--only` over the keys this module rests on, that figure
is true and it is also the wrong resolution. For `validation_error`, `loop_note`, `loop_warn`,
`document_paste_preamble` and `document_manifest_omitted_unread_page`, the ENTIRE set of nodes
that go red on a rewording is one node, and that node is a byte golden in `test_layers.py`.
Delete or edit that one file and five model-facing sentences can be reworded into anything
with a green suite.

The property, which is what this module enforces and the reason it is not more goldens:

    A contract string's meaning must be held by more than one INDEPENDENT source. A byte
    golden proves the bytes did not move; it does not prove that anything asserts what the
    string MEANS. A surface whose protection all lives in one file is one edit from
    unprotected.

More goldens cannot fix that, because a golden's file is exactly the thing that is
concentrated: `test_layers.py::test_document_manifest_bytes` alone stands under five strings.
So this gate counts FILES, and it fails when a string is stated in fewer than
`MIN_SOURCE_FILES` of them.

WHAT COUNTS AS A SOURCE, AND WHY IT IS QUOTATION AND NOT EXECUTION

A test file is a source for a contract string when the file WRITES THE WORDS OUT — when some
string literal in it quotes the sentence. That is deliberately narrower than "would go red on
a rewording", and narrower in the direction that matters:

  - A node that renders the string from the asset and compares (`loop_note(3)`,
    `load_contract()["loop_warn"]`) is NOT a source. It agrees with every rewording of the
    asset, because both sides of its comparison move together. `test_loopguard.py` was full of
    exactly that and the catalogue confirms it: mutate `loop_note` and not one loopguard node
    goes red.
  - A node that goes red for a reason its name does not declare — the LAUNDERING class of
    `RB-P89` — is not a source either. `document_paste_none` has such a node in
    `test_document_tools.py`; it reddens on a byte budget, it states nothing about the
    sentence, and crediting it would be crediting an accident.

So the measure reads the tests as an AST and collects every non-docstring string literal.
A literal is a quotation of a contract string when either

  (a) it contains, or is contained in, a placeholder-free RUN of that string of at least
      `MIN_QUOTED_CHARS` characters, and that run occurs in no other contract string; or
  (b) one of its lines is a full rendering of one of the string's lines — the line with every
      `{placeholder}` treated as a wildcard — and of no other contract string's line.

Path (b) exists because several strings share their only long run with a sibling: `tool_failed`,
`tool_arguments` and `tool_argument_types` all end `. fix the arguments and retry.`, and
`document_manifest_part` and `document_paste_part` share ` rows, numbered 0 to `. A shared run
cannot identify which string a test quoted, so it is dropped; the whole-line render can, and
does.

COVERAGE — what is NOT measured, declared rather than silent

Two strings carry no line with `MIN_QUOTED_CHARS` literal characters, so no quotation of them
can be told from a quotation of something else. They are named in `UNATTRIBUTABLE` with the
reason, the set is asserted, and a third one appearing fails the suite. This is the same
carve-out shape the catalogue makes for `document_error` under `--mode prose`, and for the same
reason: an instrument that cannot see something must say so rather than report zero.

WHY EVERY NODE BELOW HAS `wording` IN ITS NAME

Reword any contract string and this module's nodes go red, because the reworded sentence is no
longer the one the suite writes out. That is the gate working. It also means these nodes are
`RB-P89` subjects: a node that reddens on a rewording while its name promises something else is
laundering, and the J28 catalogue judges by a fixed predicate on the NAME. The first draft of
this file was measured and three of its nodes came back LAUNDERING under
`--only validation_error`, `--only loop_note`, `--only loop_warn`,
`--only document_paste_preamble` and `--only document_manifest_omitted_unread_page` at
`84cb7c2`. They were renamed rather than exempted: they do assert wording, and a name is the
only thing the catalogue can read.

`runtime-ts` is not read here. Whether the TypeScript suite states any of these sentences is
UNMEASURED by this module.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from bantamkit.contract import load_contract

TESTS = Path(__file__).resolve().parent
SELF = Path(__file__).name

# The module `docs/architecture.md` names as the byte-identity guard, and the file the J28
# catalogue found every naming pin concentrated in. Named here so the concentration is a
# declared subject of a test rather than a fact someone has to notice.
GOLDEN_FILE = "test_layers.py"

# The floor. Two, and not three or one, for a reason about EDITS rather than about coverage: a
# string stated in one file is reworded and re-asserted in the same diff, by the same person,
# in the same review — the assertion moves with the sentence and never contradicts it. Two
# files is the smallest number at which the second statement has to be found before the first
# can change. Three would buy nothing this property asks for and would fail 30 of the 38
# strings on the day it landed, which is a gate nobody keeps.
MIN_SOURCE_FILES = 2

# The shortest run of a contract sentence that counts as a quotation of it. Below this, a match
# is a collision rather than a citation (` failed: ` is 9 characters and belongs to nothing).
# The value is not a taste: the set of strings this module reports as single-sourced is
# IDENTICAL at 10, 12 and 14, and `test_the_wording_fragment_floor_sits_on_a_plateau` asserts
# that, so the measurement does not depend on which of those was picked. Above the plateau,
# real strings start falling out of measurement: at 16, `tool_argument_type`'s longest run
# (` must be type `, 14 characters) stops counting and the string becomes invisible.
MIN_QUOTED_CHARS = 12
PLATEAU = (10, 12, 14)

# Strings this instrument cannot attribute a quotation to, with the reason for each. Asserted
# exactly by `test_the_unattributable_wording_register_is_exactly_what_is_measured`: a string that
# joins this class in a later contract edit fails the suite instead of quietly reading as
# protected-by-nothing-in-particular.
UNATTRIBUTABLE = {
    "evidence_line": (
        '"{name}({arguments}) -> {observation}" is punctuation and placeholders. Its longest '
        "literal run is `) -> `, five characters, which quotes nothing. The J28 catalogue "
        "special-cases the same string for the same reason and mutates its PUNCTUATION."
    ),
    "document_error": (
        '"error: {detail}" is the machine-readable marker and a placeholder. Every other '
        "`error: ` string in the pack begins with the same seven characters, so no literal "
        "can be attributed to this one rather than to those. The catalogue EXCLUDES it under "
        "`--mode prose` for the same reason: the rewording is a no-op."
    ),
}

# The debt this gate is landing with, one entry per string still held up by a single file.
# Asserted EXACTLY — a string that leaves this class must leave this dict in the same diff, so
# the register can only be read down. `RB-P95` shipped five closures (`validation_error`,
# `loop_note`, `loop_warn`, `document_paste_preamble`,
# `document_manifest_omitted_unread_page`); these three are what it did not close.
SINGLE_SOURCED_DEBT = {
    "evidence_no_observation": (
        "stated only in `test_critique.py`, and the J28 catalogue classes it LAUNDERING: both "
        "nodes that redden on it promise a different claim in their names. It is the one "
        "string on the surface whose sole source is not the golden file, and closing it means "
        "a second consumer of `render_evidence` asserting the words — `RB-P89` work, not this."
    ),
    "document_manifest_omitted_other": (
        "the fallback line for an omission subject this layer has no template for. Its only "
        "long run, `  NOT in those rows: `, is shared with `document_manifest_omitted_media`, "
        "so only a whole-line render can attribute it, and only `test_layers.py` writes one."
    ),
    "document_paste_none": (
        "the zero-rows-shown case of the paste arm. `test_document_tools.py` DOES go red on a "
        "rewording of it, through a byte-budget assertion that states nothing about the "
        "sentence — laundering, not a source. A real second source needs a paste fixture that "
        "shows no row of a part, which the bar's corpora do not currently produce."
    ),
}

# The share of the attributable surface that may rest on one file. The PRINCIPLED value is
# 0.0: the property above says a string held in one file is one edit from unprotected, and no
# share of that is acceptable. This number is therefore not a tolerance derived from an
# argument — it is the measurement at the commit this gate landed, 3 of 38, written down so
# that raising it is a line in a diff someone has to defend. It is a ratchet: it may fall, and
# `test_the_single_sourced_wording_register_is_exactly_what_is_measured` is what makes it fall
# rather than drift.
MAX_SINGLE_SOURCED_SHARE = 3 / 38

CONTRACT = {key: value for key, value in load_contract().items() if key != "name"}
SPLIT = re.compile(r"(\{[^{}]*\})")


def _runs(line: str) -> list[str]:
    """The placeholder-free pieces of one line."""
    return [piece for index, piece in enumerate(SPLIT.split(line)) if index % 2 == 0 and piece]


def _quotable_lines(value: str, minimum: int) -> list[str]:
    return [line for line in value.split("\n") if sum(len(r) for r in _runs(line)) >= minimum]


def _line_pattern(value: str, minimum: int) -> re.Pattern[str] | None:
    """The string's lines as one regex, every `{placeholder}` a wildcard."""
    alternatives = [
        "".join(
            re.escape(piece) if index % 2 == 0 else ".+?"
            for index, piece in enumerate(SPLIT.split(line))
        )
        for line in _quotable_lines(value, minimum)
    ]
    return re.compile("|".join(f"(?:{a})" for a in alternatives)) if alternatives else None


def _index(contract: dict[str, str], minimum: int):
    """Per key: the runs that identify it alone, and the pattern its rendered lines match."""
    fragments, patterns = {}, {}
    for key, value in contract.items():
        own = {
            run
            for line in _quotable_lines(value, minimum)
            for run in _runs(line)
            if len(run) >= minimum
        }
        fragments[key] = {
            run
            for run in own
            if not any(run in other for name, other in contract.items() if name != key)
        }
        patterns[key] = _line_pattern(value, minimum)
    return fragments, patterns


def _quoted_by(literal: str, fragments, patterns) -> set[str]:
    """Every contract key this one string literal quotes."""
    found = {
        key
        for key, runs in fragments.items()
        if any(run in literal or (len(literal) >= MIN_QUOTED_CHARS and literal in run)
               for run in runs)
    }
    for line in literal.split("\n"):
        rendered = {key for key, p in patterns.items() if p is not None and p.fullmatch(line)}
        if len(rendered) == 1:
            found |= rendered
    return found


def _literals(path: Path) -> list[str]:
    """Every string literal in the file that is not a docstring."""
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = node.body
            first = body[0] if body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def read_suite() -> dict[str, list[str]]:
    """The whole test tree as {file name: its string literals}. This file is excluded: a gate
    that counted its own docstring's quotations would be its own second source."""
    return {p.name: _literals(p) for p in sorted(TESTS.glob("*.py")) if p.name != SELF}


def measure(
    contract: dict[str, str], suite: dict[str, list[str]], minimum: int = MIN_QUOTED_CHARS
) -> dict[str, set[str]]:
    """Per contract key, the set of test FILES that write its words out."""
    fragments, patterns = _index(contract, minimum)
    sources: dict[str, set[str]] = {key: set() for key in contract}
    for name, literals in suite.items():
        for literal in literals:
            for key in _quoted_by(literal, fragments, patterns):
                sources[key].add(name)
    return sources


def unattributable(contract: dict[str, str], minimum: int = MIN_QUOTED_CHARS) -> set[str]:
    fragments, patterns = _index(contract, minimum)
    return {key for key in contract if not fragments[key] and patterns[key] is None}


SUITE = read_suite()
SOURCES = measure(CONTRACT, SUITE)
MEASURED = sorted(set(CONTRACT) - unattributable(CONTRACT))
BELOW_FLOOR = {key for key in MEASURED if len(SOURCES[key]) < MIN_SOURCE_FILES}


@pytest.mark.parametrize("key", MEASURED)
def test_a_contract_strings_wording_is_written_out_in_at_least_two_test_files(key):
    """The gate. One file is one edit from unprotected, so one file is not protection."""
    if len(SOURCES[key]) >= MIN_SOURCE_FILES:
        return
    assert key in SINGLE_SOURCED_DEBT, (
        f"`{key}` is written out in {sorted(SOURCES[key]) or 'no test file at all'} and "
        f"nowhere else, so one edit to that file leaves the sentence the model reads free to "
        f"become anything. Give it a second source that asserts what the sentence MEANS in "
        f"the situation it describes — not a second byte golden — or add it to "
        f"SINGLE_SOURCED_DEBT with the reason it is still there."
    )


def test_striking_the_golden_file_leaves_only_declared_debt_unstated():
    """RB-P95's own finding, as a check. At `9a7b886` this set had seven members and every one
    of them was held up by a single `*_bytes` node in one file."""
    bare = {key for key in MEASURED if not (SOURCES[key] - {GOLDEN_FILE})}
    assert bare <= set(SINGLE_SOURCED_DEBT), (
        f"delete `{GOLDEN_FILE}` and {sorted(bare - set(SINGLE_SOURCED_DEBT))} would be stated "
        f"by nothing in the suite"
    )


def test_the_single_sourced_wording_register_is_exactly_what_is_measured():
    """Both directions. A string that falls to one source must be written down in the same
    diff; a string that gained a second source must be struck from the register in the same
    diff, or the register stops being a count of anything."""
    assert BELOW_FLOOR == set(SINGLE_SOURCED_DEBT), (
        f"measured single-sourced: {sorted(BELOW_FLOOR)}; declared: "
        f"{sorted(SINGLE_SOURCED_DEBT)}"
    )


def test_the_single_sourced_wording_share_is_within_the_declared_ceiling():
    share = len(BELOW_FLOOR) / len(MEASURED)
    assert share <= MAX_SINGLE_SOURCED_SHARE, (
        f"{len(BELOW_FLOOR)} of {len(MEASURED)} contract strings rest on one file "
        f"({share:.1%}), above the declared {MAX_SINGLE_SOURCED_SHARE:.1%}"
    )


def test_the_unattributable_wording_register_is_exactly_what_is_measured():
    """The instrument's own blind spot, asserted rather than reported. A string that stops
    being quotable — because a sibling grew wording it shares — fails here instead of reading
    as zero sources, which is the silent zero this register exists to catch."""
    assert unattributable(CONTRACT) == set(UNATTRIBUTABLE)


def test_every_contract_wording_is_either_measured_or_declared_unattributable():
    assert set(MEASURED) | set(UNATTRIBUTABLE) == set(CONTRACT)
    assert not set(UNATTRIBUTABLE) & set(SINGLE_SOURCED_DEBT)


def test_the_measure_is_not_stuck_on():
    """CAL-GREEN, in-suite. An instrument that reports every string sourced cannot be told
    from one that reports every string sourced BECAUSE IT IS STUCK ON — the control the
    2026-08-14 pinning harness lost. A sentence no test writes out must measure zero."""
    absent = "no test in this repository writes this particular sentence out anywhere"
    # CAL-GREEN, contract side: a sentence nothing quotes measures zero against the real suite.
    assert measure(dict(CONTRACT) | {"cal_green": absent}, SUITE)["cal_green"] == set()
    # CAL-GREEN and CAL-RED, suite side: ONE key against two suites that differ in exactly one
    # thing — whether its sentence is written out. A detector stuck on fails the first; a
    # detector stuck off fails the second; only a working one passes both.
    key = "document_manifest_empty"
    assert measure(CONTRACT, {"test_cal.py": [absent]})[key] == set()
    assert measure(CONTRACT, {"test_cal.py": [CONTRACT[key]]})[key] == {"test_cal.py"}


def test_a_test_that_renders_the_string_from_the_asset_is_not_a_source():
    """Why this counts quotation and not redness. `assert dispatch(...) == f"{loop_note(3)}\\n
    alpha"` compares the asset against itself: reword the asset and both sides move. All such
    a node leaves in the AST is the glue around the call, and glue is not a statement about
    what the sentence says."""
    glue = {"test_glue_only.py": ["\nalpha", "lookup", "out"]}
    assert measure(CONTRACT, glue)["loop_note"] == set()
    assert measure(CONTRACT, glue)["loop_warn"] == set()


@pytest.mark.parametrize("minimum", PLATEAU)
def test_the_wording_fragment_floor_sits_on_a_plateau(minimum):
    """MIN_QUOTED_CHARS is data with an argument, and this is the argument: the answer does
    not move across the plateau, so no result in this module rests on which value was picked."""
    assert {key for key in MEASURED if len(measure(CONTRACT, SUITE, minimum)[key]) < 2} == (
        BELOW_FLOOR
    )
    assert unattributable(CONTRACT, minimum) == set(UNATTRIBUTABLE)
