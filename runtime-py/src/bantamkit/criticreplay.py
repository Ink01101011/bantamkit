"""Perturbation bar: score one critic over a family of meaning-preserving prompt edits.

RB-P14. A one-cell bar cannot tell a mechanism from a perturbation — deleting a single
semantically null byte from a rubric reproduced an entire pass signature. This module
replays the critic alone, at a pinned seed, over a small declared family of
meaning-preserving edits *to the rubric template*, and reports the pass rate with its
spread, so a rubric edit has to beat the noise band it lives in.

Layer: Measurement. It reads Contract assets (rubrics) and the frozen suite read-only,
calls Transport (`client.py`) and Core (`structured()`), and adds nothing to either.

Two constraints that are not optional (spec §6.1):

- **`CritiqueGate` is bypassed.** Its verdict memo keys on exact prompt bytes, so N
  replays of one point would collapse into one model call and one repeated verdict —
  silently destroying the spread this instrument exists to measure.
- **Requests go through `structured()`.** A hand-built `response_format` request on the
  as-filed rubric scored 9 where the committed replay record has 5. Request
  construction is load-bearing, which is why the reproduction gate comes first.

Not a whole-suite sweeper: its job is validating one change's attribution on a named
cell or a small task set.

**Guard 2 has two readings and this module reports both.** §3.3's shared-token guard
forbids a word "the point adds or removes" from appearing in the cell, and the spec says
that in two sentences which do not agree about what "the point adds or removes" means.
An independent re-derivation from the spec's Test sentence produced one table; this
module's original implementation produced another; the user's ruling (2026-08-12) is
that both are computed, both are named in the artifacts, and neither is declared wrong.
`moved_words` defines them; `guard_union` is what the run acts on when they differ.

**Where the guards live on the public API.** Guards 1, 3 and 4 are properties of a
point, so they run inside `apply_point` — the one public route from a `Point` to a
template — and a consumer who never calls `run()` still gets them. `check=False` is the
documented deliberate bypass. Guard 2 is a property of a (point, CELL) pair, so it
cannot ride along there.

**Start at `guarded_family`.** It is the one call from (variants, points, cells) to
`GuardedReplay` units, each carrying the exact `Rubric` to replay, the cell, the replay
count the bar uses, and guard 2's verdict on that pair under both readings. `unit.replay
(client)` issues it and stamps that verdict onto every `Verdict` it returns, so it puts
the taint on the object the consumer serializes, rather than in a second table they must
join. `run()` is those two calls and nothing else — there is no second derivation of the
family ON THE RUN PATH. (`materialize_manifest` derives it again for the `--manifest`
audit artifact; `_check_materialization` is what keeps the two from drifting.)
`apply_point`, `guard_table` and `replay_verdicts` are the primitives they are built
from, and they stay public because an offline audit needs them; but the guarded route is
now the SHORT one — two public calls against three, from the same starting object, since
`guarded_family` takes a bare `Rubric` as well as a `RubricVariant` — which is the whole
of RB-P23's fix.

RB-P23 is a defence-in-depth hole, not a soundness bug, and this does not make it
impossible: Python has no private functions, so `apply_point` -> hand-assembled `Rubric`
-> `replay_verdicts` still reaches the wire with a tainted pair and nothing recording it.
What changed is the length comparison. That residual is measured, not claimed, by
`test_the_unguarded_route_still_reaches_the_wire_and_is_the_longer_one`, which EXECUTES
both routes from one `Rubric` and counts the module calls each one makes.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

import yaml

from bantamkit.assets import assets_root
from bantamkit.client import BantamError, Message, ModelClient, OpenAICompatible
from bantamkit.critique import Rubric
from bantamkit.evalrun import TrackingClient
from bantamkit.structured import structured

__all__ = [
    "ARTIFACT_WRITE_EXIT",
    "GUARD_DECISION_RULE",
    "GUARD_MODES",
    "GUARD_VIOLATION_EXIT",
    "IN_MEMORY_REF",
    "READINGS",
    "READING_RULES",
    "REFUSAL_EXIT",
    "RENDER_FAILURE_EXIT",
    "USAGE_EXIT",
    "Case",
    "GuardedFamily",
    "GuardedReplay",
    "Manifest",
    "PerturbationError",
    "Point",
    "ReplayRow",
    "RubricVariant",
    "RunResult",
    "Verdict",
    "apply_point",
    "cell_guard_violations",
    "exit_status",
    "guard_table",
    "guard_union",
    "guarded_family",
    "load_cases",
    "load_manifest",
    "main",
    "materialize_manifest",
    "moved_words",
    "normalize_whitespace",
    "parse_rubric_arg",
    "point_admissibility_violations",
    "render_prompt",
    "replay_scores",
    "replay_verdicts",
    "run",
    "substitution_pair_moved_words",
    "summarize",
    "whole_text_moved_words",
]

BAR = "perturbation"

# §3.3 step 3, guard 1. The schema keys, the JSON braces and the band digits are the
# rubric's contract with the wire; a point that moves one is a requirement edit.
FROZEN_LITERALS = ('"score"', '"feedback"', "9-10", "5-8", "0-4", "{{", "}}")

# §3.3 step 3, guard 3. "should not" for "do NOT" changes the force of a directive, so a
# paraphrase that moves any of these is a requirement edit wearing a paraphrase's clothes.
FROZEN_KEYWORDS = (
    "ONLY",
    "NOT",
    "never",
    "every",
    "any",
    "must",
    "should",
    "even when",
    "instead",
)

# The point classes §3 admits. `identity` is a mandatory member, not a perturbation class.
CLASSES = ("identity", "whitespace", "order", "paraphrase")

# What a run does when a point violates §3.3's shared-token guard on a cell. See
# `guard_table` for why `warn` is the default and `error` is not.
GUARD_MODES = ("warn", "error")

# ---- the exit-status contract (§6.2, RB-P24) ----
#
# Five outcomes a CI job has to tell apart. Four of them are meanings this tool
# chooses, and TWO MEANINGS MAY NOT SHARE ONE NUMBER — which is exactly what was
# wrong: a run where guard 2 fired on eight cells exited 0, indistinguishable from a
# clean one, so `--guard error` (which refuses instead of measuring) was the only
# machine-readable verdict there was.
#
#   0  measured, and guard 2 fired on nothing that ran
#   1  DID NOT COMPLETE A MEASUREMENT — every `BantamError` path, `--guard error`
#      included, and every abort in the middle of one. The perturbation-bar spec
#      §6/§11 rest on this family being non-zero. It does NOT promise that nothing
#      was written: the JSONL sink flushes per row on purpose, so a run that dies
#      mid-family (a refused connection on request 40 of 80) exits 1 with rows
#      already on disk. 1 means the run owes you no conclusion, not that it left
#      no trace. Read it as "fix the input and run it again", and treat any
#      artifact from a 1 as partial.
#   2  usage error. Not this module's to choose: it is argparse's, and it is recorded
#      here as a MEASURED number (`--not-a-flag` exits 2), pinned from a shell by
#      `test_argparses_usage_status_is_measured_not_assumed`, so that the statuses this
#      module does choose cannot silently collide with it. argparse also owns this
#      module's own `parser.error` validations (`--replays 0` exits 2, measured).
#   3  measured, WITH violations. Every artifact is written — the JSONL, the summary,
#      the printed table — and the status says the guard fired, never that the run
#      failed. A violating cell (`nav-prod-port` is one) has to stay measurable.
#   4  measured, but AN ARTIFACT COULD NOT BE WRITTEN — today, exactly: the
#      `--summary` file. The measurement completed and the table is still printed;
#      what is missing is the file a later reader would diff. It is a separate
#      number because it used to be an unhandled `OSError`, i.e. a 1, on a run that
#      had already flushed every JSONL row — the refusal status on a run that
#      measured (RB-P24 review, C1). It OUTRANKS 3: "every artifact is written" is
#      the one thing 3 promises, and here it is false. `--violations-exit-zero`
#      cannot suppress it — the hatch is an opt-out from 3 alone.
#   5  measured, but THE REPORT COULD NOT BE RENDERED: the run path's own write to
#      stdout failed for a reason that is NOT the reader going away. fd 1 on a
#      read-only fd (EBADF), fd 1 closed before the process started (`1>&-`, where
#      CPython leaves `sys.stdout` as None and `print` is a silent no-op), a full
#      device (ENOSPC). RB-P31, and it is the SAME shape as 4 one step further out:
#      the measurement completed and every file that could be written is on disk,
#      but the table a reader would have read is not anywhere. It OUTRANKS 4 for
#      4's own reason — each number here outranks the one below it because the
#      lower one's promise is false about this run, and 4's promise, in its own
#      sentence above, is "the table is still printed". `--violations-exit-zero`
#      does not suppress it either.
#      WHY NOT REUSE 4. Two meanings may not share one number (the rule this whole
#      block exists to enforce), and these are two: on a 4 the answer IS in the
#      log and the fix is a writable `--summary` path; on a 5 the answer is NOT in
#      the log and the fix is the caller's stdout. Reusing 4 would have required
#      deleting "the table is still printed" from a number CI jobs already read,
#      which is a larger break of the contract than adding one.
#      WHY NOT DOWNGRADE TO THE EARNED STATUS, the way EPIPE does. EPIPE means
#      NOBODY WAS READING, so the table's absence costs no one anything and 0 is
#      still true. Here the report was wanted and is gone; 0 would say "measured,
#      clean" about a run whose report nobody got.
#
# A CI job writes against these directly: 0 clean, 1 fix the input and re-run (any
# artifacts are partial), 2 fix the command line, 3 the run happened and the GUARD
# section and the `guard_dropped` blocks have to be read before anything is credited,
# 4 the run happened but its summary is not on disk, 5 the run happened but its table
# was never delivered — read the artifacts, not the log. Branch on 0-5; 130 is SIGINT
# and 143 is SIGTERM.
#
# ---- RB-P27, and what replaced a sentence that was wrong (v0.19.0) ----
#
# This comment used to end "a stdout that goes away mid-table is the interpreter's
# number, not one of these — a CI job should branch on this range and treat everything
# else as *did not run to completion*". The first half was true and the second was
# false about the very case the first half named: that run HAD run to completion, every
# JSONL row and the summary were on disk to prove it, and it reported 120 anyway.
#
# COVERED SINCE v0.19.0: the READER GOING AWAY (EPIPE) at the run path's own write to
# stdout — the table print, its flush, and the interpreter's shutdown flush behind them.
# If the reader of stdout is gone there, the run reports the status it EARNED (0, 3 or 4)
# and never the interpreter's number. A lost stdout may DOWNGRADE to a number the run
# already had; it may not invent one. Read from a real shell's `$?` for all three earned
# values by `test_closed_pipe_*` in test_criticreplay.py.
#
# ---- RB-P31, and the half of that sentence that was a defect ----
#
# The sentence above used to end "and this is the whole of what is covered". It was, and
# the price was measured across a 45-cell matrix on 2026-08-13
# (docs/eval-data/2026-08-13-rbp31-render-failure-matrix.md): a stdout write that failed
# for ANY OTHER reason escaped `main` on a run that had MEASURED — JSONL rows and summary
# on disk, byte-identical to the same argv with a live reader — and the shell read 120
# below fd 1's `BufferedWriter` and REFUSAL_EXIT above it, and REFUSAL_EXIT at every size
# when fd 1 was closed outright. A run that measured reporting that it refused is the
# RB-P24 defect class, one line from where RB-P24 fixed it.
#
# COVERED NOW: the run path's own write to stdout failing for a reason other than a gone
# reader reports 5 (above), not the interpreter's number and never REFUSAL_EXIT. Three
# things make that arm narrow rather than a bare `except`:
#   - `format_table(summary)` is evaluated OUTSIDE the try. A failure to BUILD the table
#     is a bug in this module and propagates with its traceback; only the WRITE is inside
#     the arm. Pinned by `test_a_non_pipe_failure_around_the_table_print_is_not_downgraded`,
#     which raises from `format_table` and requires both raisers to reach the caller.
#   - the arm catches `OSError`, not `Exception`. A non-OSError raised BY THE WRITE still
#     propagates; pinned by `test_a_non_oserror_at_the_table_write_is_not_downgraded`.
#   - the closed-fd 1 case is READ, not caught: `sys.stdout is None` is a state CPython
#     puts the interpreter in before `main` runs, and there is no exception to catch —
#     `print` to a None stdout is a silent no-op and the table is lost with no raise at
#     all. That cell is why "give the print an `except OSError` arm", RB-P31's own filed
#     attack direction, would not have closed it.
#
# The buffer is not the axis of the FIX, but it is why the defect looked like two
# defects: CPython gives `sys.stdout` a `BufferedWriter` of `os.fstat(1).st_blksize`
# bytes — 4096 for a regular file, 16384 for a pipe, 65536 for `/dev/null` — and whether
# the doomed bytes are still in that buffer when the failure surfaces decides whether the
# interpreter's finalization flush re-fails and overwrites the status with 120. Both
# sides are handled by the same arm and both are pinned, at both sizes.
#
# STILL OUTSIDE THE RANGE, measured 2026-08-13 rather than assumed, because "everything
# outside 0-4 means the run did not complete" is STILL not a true reading. This list is
# OPEN — it is what has been measured, not a proof that nothing else escapes:
#   - `--help` with no reader on stdout exits 120. argparse writes the epilog and exits
#     before `main` reaches the handler, so the handler is not on that path at all.
#   - a run that WRITES to stderr while stderr has no reader exits 120 — a refusal's
#     `error: …`, the summary-write failure, the `--violations-exit-zero` note. The
#     refusal's own 1 is erased exactly as the table's 3 used to be. A run that writes
#     nothing to stderr is unaffected (nothing to flush; measured, still 3).
# Those two are pinned by nodes that go red if a later change covers them, so they cannot
# go stale silently: `test_help_with_no_reader_on_stdout_is_still_the_interpreters_
# number` and `test_a_refusal_whose_stderr_has_no_reader_leaves_the_range`. NOTHING pins
# the list's exhaustiveness, and it is NOT exhaustive. What RB-P31's fix does NOT reach,
# stated so the next reader does not have to re-derive it:
#   - anything written to stdout OUTSIDE the run path's own table print. `--help` is the
#     measured instance; argparse writes and exits before `main` gets there.
#   - stderr. Every arm here reports on stderr, so a run whose stderr is also gone loses
#     the explanation, and the finalization flush of fd 2 takes the status with it.
#   - ENOSPC on a real full device was NOT constructed in the field (macOS has no
#     `/dev/full`); it is in the arm by class, and only simulated in-process. On Linux
#     the cell is `... > /dev/full` and it is worth one line there.
#
# So the advice is: branch on 0-5, and read anything else as "this process did not
# choose its own status" — a signal, or a stream this handler does not cover — rather
# than as "the measurement did not happen". The artifacts may still be on disk, and
# under RB-P27's case (a) and RB-P31's whole matrix they demonstrably were.
REFUSAL_EXIT = 1
USAGE_EXIT = 2
GUARD_VIOLATION_EXIT = 3
ARTIFACT_WRITE_EXIT = 4
RENDER_FAILURE_EXIT = 5

# §3.3 guard 2 has two defensible readings of "a word the point adds or removes", and
# the spec supports each in a different sentence. The user's ruling (2026-08-12) is that
# both are computed and reported side by side and neither is called wrong; `guard_union`
# is the decision rule that has to act when they disagree. See `moved_words`.
READINGS = ("whole-text", "substitution-pair")

READING_RULES = {
    "whole-text": (
        "symmetric difference of the base and perturbed TEMPLATE word sets — §3.3's "
        "operative Test sentence, and what an independent re-derivation from the spec "
        "produced"
    ),
    "substitution-pair": (
        "symmetric difference of the point's own `from`/`to` word sets — what §3.3 "
        "step 4's substitution-pair form and the manifest's P2 justification imply"
    ),
}

GUARD_DECISION_RULE = (
    "union — a (point, cell) is tainted if EITHER reading flags it, because "
    "under-detection is the direction this guard exists to prevent"
)

NO_NEWLINE = "\\ No newline at end of file"

# §3.3 guard 2's "tokenize on word boundaries". A HYPHEN IS A WORD BOUNDARY: with it
# word-internal, `requests-per-minute` was one token, so the guard could not see
# `requests` inside it and reported clean on `recall-org-quota` — a false negative,
# the direction this guard exists to prevent, and true under both readings. The four
# compounds in the frozen prompts (`requests-per-minute`, `on-call`, `billing-svc`,
# `INV-42`) hid seven words between them. Pinned by
# `test_a_hyphen_does_not_hide_the_words_inside_a_compound`.
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class PerturbationError(BantamError):
    """The instrument cannot report a number it would be able to defend."""


# ---- small helpers ----


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def normalize_whitespace(text: str) -> str:
    """§3.1's admissibility predicate, one half of it: collapse runs and strip.

    Two strings are in class W of each other iff their normalizations are
    byte-identical. Mechanical and checkable by anyone; nothing else is class W.
    """
    return " ".join(text.split())


def _diff_lines(text: str) -> list[str]:
    """Lines for a unified diff, with git's explicit missing-trailing-newline marker.

    Without the marker a trailing-newline edit — the null control, the whole reason this
    module exists — diffs as no change at all, because both sides have identical lines.
    """
    lines = text.splitlines()
    if not text.endswith("\n"):
        lines.append(NO_NEWLINE)
    return lines


def unified_diff(base: str, new: str, from_label: str = "base", to_label: str = "point") -> str:
    if base == new:
        return ""
    return "\n".join(
        difflib.unified_diff(
            _diff_lines(base),
            _diff_lines(new),
            fromfile=from_label,
            tofile=to_label,
            n=1,
            lineterm="",
        )
    )


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


# §3.3 step 3, guard 4. A sentence ends at `.`/`!`/`?` followed by whitespace OR the end
# of the string — a NEWLINE is whitespace, which is the whole point: the template is
# hard-wrapped, so the predicate this replaces (`". " in anchor` or a trailing `.`) was
# inverted on real input. It raised on an anchor that is exactly one complete sentence,
# and passed an anchor spanning two sentences joined by a newline.
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")

# §3.3 step 3, guard 3, at WORD boundaries and case-sensitively (§3.6 X3: case here does
# illocutionary work). Substring counting reported `every` as moved when `itself` became
# `everything`.
_FROZEN_KEYWORD_RE = {
    word: re.compile(rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])")
    for word in FROZEN_KEYWORDS
}


def _spans_a_sentence_boundary(text: str) -> bool:
    """True when `text` continues past a sentence terminator.

    "One sentence per instance" admits a whole sentence — an instance that IS one
    complete sentence is the easiest thing there is to check at a glance. What it
    forbids is an instance that runs past a boundary into a second sentence.
    """
    stripped = text.strip()
    return any(match.end() != len(stripped) for match in _SENTENCE_END.finditer(stripped))


def _keyword_positions(text: str) -> list[tuple[str, int]]:
    """Every frozen keyword in `text`, with its ordinal position in the word sequence.

    Counting can only see a keyword appear or vanish. `"Judge ONLY whether"` ->
    `"Judge whether ONLY"` changes what `ONLY` scopes over while leaving every count
    identical, and that is a requirement edit wearing a paraphrase's clothes — exactly
    what guard 3 is for. Comparing positions across the instance catches it, and still
    admits rewording the words a keyword governs (`"Do NOT deduct"` -> `"Do NOT
    subtract"` leaves `NOT` at index 1).
    """
    words = _WORD.findall(text)
    found: list[tuple[str, int]] = []
    for keyword in FROZEN_KEYWORDS:
        parts = keyword.split()
        for index in range(len(words) - len(parts) + 1):
            if words[index : index + len(parts)] == parts:
                found.append((keyword, index))
    return sorted(found)


# ---- the manifest (§3, §4.1) ----


@dataclass
class Point:
    id: str
    point_class: str  # `class` in the manifest and in the JSONL row; not a Python name
    rule: str
    op: str
    replace: list[dict] = field(default_factory=list)
    swap: dict | None = None
    justification: str | None = None
    variants: dict = field(default_factory=dict)


@dataclass
class Manifest:
    rubric: str
    requirement_inventory: list[str]
    points: list[Point]
    materialized_variants: dict
    sha256: str
    path: Path


def default_manifest_path(rubric_name: str) -> Path:
    """`assets/evals/perturbations/<rubric-name>.yaml`.

    Measurement *input*, not a Contract asset: no product code path loads it, and
    `test_layers.py`'s golden byte-identity guard over contract strings does not extend
    to it. It lives under `assets/evals/` because that is already where measurement
    input lives (`tasks/`, `fixtures/`), and a test asserts this module is its only
    reader.
    """
    return assets_root() / "evals" / "perturbations" / f"{rubric_name}.yaml"


def load_manifest(path: Path | None = None, rubric_name: str | None = None) -> Manifest:
    if path is None:
        if rubric_name is None:
            raise PerturbationError("load_manifest needs a path or a rubric name")
        path = default_manifest_path(rubric_name)
    path = Path(path)
    if not path.is_file():
        raise PerturbationError(f"perturbation manifest not found: {path}")
    raw = path.read_text()
    data = yaml.safe_load(raw)
    points = []
    for entry in data["points"]:
        if entry["class"] not in CLASSES:
            raise PerturbationError(f"point '{entry['id']}' has unknown class {entry['class']!r}")
        points.append(
            Point(
                id=entry["id"],
                point_class=entry["class"],
                rule=entry["rule"],
                op=entry["op"],
                replace=entry.get("replace") or [],
                swap=entry.get("swap"),
                justification=entry.get("justification"),
                variants=entry.get("variants") or {},
            )
        )
    ids = [p.id for p in points]
    if len(set(ids)) != len(ids):
        raise PerturbationError(f"duplicate point ids in {path}")
    return Manifest(
        rubric=data["rubric"],
        requirement_inventory=list(data["requirement_inventory"]),
        points=points,
        materialized_variants=data.get("materialized_variants") or {},
        sha256=sha256_text(raw),
        path=path,
    )


def apply_point(point: Point, template: str, *, check: bool = True) -> str | None:
    """Apply one declared, text-anchored transformation to one template.

    Returns the perturbed template, or `None` when the point's anchor is absent from
    this variant (§4.1: `applicable: false`, which paired dropping then handles). Never
    a silent no-op — a transformation that fires and changes nothing is an error, not a
    point, and so is an anchor that matches in more places than it claims.

    **Guards 1, 3 and 4 run here** (`check=True`, the default). They are properties of
    the POINT, not of any cell, so they ride with the transformation itself rather than
    living only inside `run()`. This is the public route from a `Point` to a template,
    so a library consumer with a hand-rolled manifest gets them without knowing they
    exist — the case `3420384` claimed to close for `--manifest` and left open here.

    Guard 2 cannot ride along: it is a property of a (point, CELL) pair and this
    function never sees a cell.

    **A PRIMITIVE, not the route to a replay.** `guarded_family` is what a consumer
    scoring a family should call — it is built from this function and returns templates
    already paired with guard 2's verdict on each cell. Reaching a request from here
    instead means assembling the `Rubric` by hand and getting no guard 2 at all, which is
    RB-P23's residual: possible, and now the longer of the two routes — three public
    calls (`apply_point`, `Rubric`, `replay_verdicts`) against the guarded route's two
    (`guarded_family`, `unit.replay`), from the same starting `Rubric`.

    `check=False` is the deliberate bypass, and it is deliberate on purpose: a guard
    nobody can turn off is a guard people route around. `_variant_family` uses it so it
    can raise a message naming the variant as well as the point.
    """
    new = _transform(point, template)
    if new is None:
        return None
    if new == template and point.op != "identity":
        raise PerturbationError(
            f"point '{point.id}' is a no-op on a variant whose anchor it matched — "
            "a transformation that changes nothing is an error, not a point"
        )
    if check:
        problems = point_admissibility_violations(point, template, new)
        if problems:
            raise PerturbationError(
                f"point '{point.id}' is inadmissible (spec §3.3 step 3): it "
                f"{'; it '.join(problems)} — a point that is not meaning-preserving "
                "measures a requirement edit, not a perturbation. Pass check=False to "
                "apply it anyway."
            )
    return new


def _transform(point: Point, template: str) -> str | None:
    if point.op == "identity":
        return template
    if point.op == "strip-trailing-newline":
        return template[:-1] if template.endswith("\n") else None
    if point.op == "append-trailing-newline":
        return template + "\n"
    if point.op == "replace":
        new = template
        for op in point.replace:
            found, new = _replace_once(point.id, new, op)
            if not found:
                return None
        return new
    if point.op == "swap":
        return _swap(point.id, template, point.swap or {})
    raise PerturbationError(f"point '{point.id}' has unknown op {point.op!r}")


def _replace_once(point_id: str, template: str, op: dict) -> tuple[bool, str]:
    anchor, replacement = op["from"], op["to"]
    count = template.count(anchor)
    if count == 0:
        return False, template
    if op.get("occurrences", 1) != "all" and count != 1:
        raise PerturbationError(
            f"point '{point_id}' anchor occurs {count} times but claims one — "
            "an ambiguous anchor silently perturbs the wrong place"
        )
    return True, template.replace(anchor, replacement)


_SENTINEL = "\x00bantamkit-swap\x00"


def _swap(point_id: str, template: str, swap: dict) -> str | None:
    a, b = swap["a"], swap["b"]
    if a not in template or b not in template:
        return None
    for side in (a, b):
        if template.count(side) != 1:
            raise PerturbationError(
                f"point '{point_id}' swap anchor occurs {template.count(side)} times but "
                "claims one"
            )
    if _SENTINEL in template:
        raise PerturbationError(f"point '{point_id}': template contains the swap sentinel")
    return template.replace(a, _SENTINEL).replace(b, a).replace(_SENTINEL, b)


def whole_text_moved_words(base: str, perturbed: str) -> list[str]:
    """Reading 1 of "the words this point moves": base vs perturbed TEMPLATE word sets.

    This is §3.3's operative Test sentence read literally — "the symmetric difference of
    the base and perturbed word sets must be disjoint from the task prompt's word set" —
    and it is what an independent reviewer, forbidden from reading this module, derived
    from the spec alone. A word the edit drops from one clause but that still occurs
    elsewhere in the template has not moved out of the critic's input, so this reading
    does not count it.
    """
    return sorted(_words(base) ^ _words(perturbed))


def substitution_pair_moved_words(point: Point) -> list[str]:
    """Reading 2: the symmetric difference of the point's own `from`/`to` strings.

    This is what §3.3 step 4 ("each P point is expressed as a literal `from` -> `to`
    substitution pair") and the manifest's own P2 justification prose imply: the
    instance is the pair, so the words the instance moves are the pair's. It is blind to
    anything that is not a `replace` op, and to a substitution landing inside a word.
    """
    changed: set[str] = set()
    for op in point.replace:
        changed |= _words(op["from"]) ^ _words(op["to"])
    return sorted(changed)


def moved_words(point: Point, base: str, perturbed: str) -> dict[str, list[str]]:
    """Both readings of §3.3 guard 2's "added or removed word", by name.

    The user's ruling (2026-08-12) after the two readings were found to disagree on
    `P2-asks-requests`: **compute both, report both, declare neither wrong.** The spec
    supports each in a different sentence and they answer different questions —
    whole-text asks what changed in the bytes the critic reads, substitution-pair asks
    what the author declared they were changing. Neither is a superset of the other in
    general: substitution-pair sees a word the edit removes from one clause that
    survives elsewhere; whole-text sees an edit that lands inside a word, and any point
    whose op is not `replace`.
    """
    return {
        "whole-text": whole_text_moved_words(base, perturbed),
        "substitution-pair": substitution_pair_moved_words(point),
    }


def guard_union(readings: dict[str, list[str]]) -> list[str]:
    """The decision rule when the readings disagree: taint if EITHER flags (§3.3 g2).

    Under-detection is the direction this guard exists to prevent — a tainted point that
    reads clean is RB-P4's mechanism scoring itself — so the union is the conservative
    choice, and the cost of a false taint is bounded: `pass_rate` still reports the full
    family, only the *attribution* claim has to survive dropping the point.
    """
    out: set[str] = set()
    for words in readings.values():
        out |= set(words)
    return sorted(out)


def shared_token_violations(
    point: Point, text: str, base: str, perturbed: str | None = None
) -> dict[str, list[str]]:
    """§3.3 step 3, guard 2, against one text — both readings, keyed by name.

    RB-P4's measured mechanism was literal matching against a token copied from the task
    prompt, so a paraphrase that changes the shared-token surface is changing the
    mechanism under test.

    The primitive. It takes one text so the offline tables over all 22 frozen task
    prompts can be pinned against it directly; `cell_guard_violations` is what the run
    path calls, because the guard the spec writes is about the whole cell.
    """
    if perturbed is None:
        perturbed = _transform(point, base)
        if perturbed is None:  # the anchor is absent: this point moves nothing here
            perturbed = base
    text_words = _words(text)
    return {
        reading: sorted(set(words) & text_words)
        for reading, words in moved_words(point, base, perturbed).items()
    }


def point_admissibility_violations(point: Point, base: str, perturbed: str) -> list[str]:
    """§3.3 step 3, guards 1, 3 and 4: what makes a point inadmissible on ANY cell.

    Unlike guard 2 these need no cell, so they cannot be drop-and-report: a point that
    moves a band digit is not meaning-preserving anywhere, and a run has nothing to
    salvage from it. `_variant_family` raises on them, before any request.

    Guard 3's keyword list has lived in this module since the bar shipped and was read
    only by an offline test over the three committed variants — the same
    defined-but-uncalled shape as guard 2. Guards 1 and 4 had no definition here at all.

    Guards 3 and 4 were both written from the spec with no measured defect behind them,
    and once they could abort a run they aborted it on legitimate input. Guard 4 was
    INVERTED on the real template: it flagged `". "` and a trailing `.`, so an anchor
    that is exactly one complete sentence raised, while an anchor spanning two sentences
    joined by a newline — which is how the hard-wrapped template joins them — passed.
    Guard 3 counted substrings, so `itself` -> `everything` "moved" the keyword `every`,
    and reordering `ONLY` inside the instance moved nothing. See `_spans_a_sentence_
    boundary` and `_keyword_positions`.
    """
    problems = []
    for literal in FROZEN_LITERALS:
        if perturbed.count(literal) != base.count(literal):
            problems.append(f"moves the frozen contract literal {literal!r}")
    if point.point_class != "paraphrase":
        return problems
    for word in FROZEN_KEYWORDS:
        pattern = _FROZEN_KEYWORD_RE[word]
        if len(pattern.findall(perturbed)) != len(pattern.findall(base)):
            problems.append(f"moves the frozen keyword {word!r}")
    if point.op != "replace" or len(point.replace) != 1:
        problems.append("is not one sentence expressed as one literal from -> to pair")
        return problems
    anchor, replacement = point.replace[0]["from"], point.replace[0]["to"]
    if _keyword_positions(anchor) != _keyword_positions(replacement):
        problems.append(
            "moves a frozen keyword within the instance it edits, changing what the "
            "directive scopes over"
        )
    for side, label in ((anchor, "from"), (replacement, "to")):
        if _spans_a_sentence_boundary(side):
            problems.append(f"spans more than one sentence (the {label} side)")
    return problems


def cell_guard_violations(
    point: Point, case: Case, base: str, perturbed: str | None = None
) -> dict[str, list[str]]:
    """The same guard against a whole cell: §3.3's `{task}` **or** `{output}`.

    Checking `{task}` alone is how this guard was under-implemented; the spec names both
    surfaces, and a run holds both. Measured on the committed M1 transcripts the
    `{output}` half adds nothing today (zero extra violations over 20 cells), which is
    the point: a guard is not allowed to be right only by luck.
    """
    task = shared_token_violations(point, case.prompt, base, perturbed)
    output = shared_token_violations(point, case.output, base, perturbed)
    return {reading: sorted(set(task[reading]) | set(output[reading])) for reading in READINGS}


def materialize_manifest(points: list[Point], templates: dict[str, str]) -> dict:
    """Per point, per variant: applicability, the resulting template sha, and a diff.

    The whole family is materialized so a reader audits the exact bytes without
    re-running anything, and so a rule change shows up as a manifest diff.
    """
    out: dict[str, dict] = {}
    for point in points:
        out[point.id] = {}
        for label, base in templates.items():
            new = apply_point(point, base)
            if new is None:
                out[point.id][label] = {"applicable": False}
            else:
                out[point.id][label] = {
                    "applicable": True,
                    "sha256": sha256_text(new),
                    "diff": unified_diff(new=new, base=base, from_label=label, to_label=point.id),
                }
    return out


# ---- rubric variants (§6.2) ----


@dataclass
class RubricVariant:
    label: str
    spec: str
    ref: str
    rubric: Rubric
    sha256: str


def parse_rubric_arg(arg: str) -> RubricVariant:
    """`LABEL=SPEC`, where SPEC is a path or `git:<ref>:<path>`.

    The git form exists because the acceptance test needs rubrics that live only in
    history. `load_rubric` is name-only and has no path hook, so the parsed `Rubric` is
    passed around as an instance.
    """
    label, sep, spec = arg.partition("=")
    if not sep or not label or not spec:
        raise PerturbationError(f"--rubric wants LABEL=SPEC, got {arg!r}")
    if spec.startswith("git:"):
        _, ref, path = spec.split(":", 2)
        raw = _git_show(ref, path)
        source = ref
    else:
        path = Path(spec)
        if not path.is_file():
            raise PerturbationError(f"rubric not found: {spec}")
        raw = path.read_text()
        source = spec
    return RubricVariant(
        label=label, spec=spec, ref=source, rubric=_parse_rubric(raw, spec), sha256=sha256_text(raw)
    )


def _git_show(ref: str, path: str) -> str:
    try:
        return subprocess.run(
            ["git", "show", f"{ref}:{path}"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise PerturbationError(f"cannot read git:{ref}:{path}: {e}") from e


def _parse_rubric(raw: str, where: str) -> Rubric:
    data = yaml.safe_load(raw)
    try:
        rubric = Rubric(
            name=data["name"],
            threshold=int(data["threshold"]),
            prompt=data["prompt"],
            schema=data["schema"],
        )
    except (KeyError, TypeError, ValueError) as e:
        raise PerturbationError(f"{where} is not a rubric: {e}") from e
    missing = [slot for slot in ("{task}", "{output}") if slot not in rubric.prompt]
    if missing:
        raise PerturbationError(f"{where} prompt missing placeholder(s): {', '.join(missing)}")
    return rubric


# ---- cells, taken byte-exact from P8 transcripts (§6.2) ----


@dataclass
class Case:
    task: str
    repeat: int
    seed: int
    prompt: str  # the frozen suite's task prompt, read-only
    output: str  # the answer, byte-exact from the transcript


def load_cases(
    transcripts_dir: Path, tasks: list[str] | None = None, tasks_dir: Path | None = None
) -> list[Case]:
    """One cell per (task, repeat), fed from P8 transcripts rather than hand-copied strings.

    That is what makes "byte-identical answer" true by construction instead of by
    assertion. The task *prompt* is loaded read-only from the frozen suite; a
    transcript that carries no answer is skipped, and two transcripts that disagree
    about one cell are a hard error rather than a coin toss.
    """
    tasks_dir = Path(tasks_dir) if tasks_dir else assets_root() / "evals" / "tasks"
    wanted = set(tasks) if tasks else None
    cells: dict[tuple[str, int], tuple[Case, str]] = {}
    for path in sorted(Path(transcripts_dir).glob("*.json")):
        data = json.loads(path.read_text())
        name = data["task"]
        if wanted is not None and name not in wanted:
            continue
        if data.get("output") is None:
            continue
        if data.get("seed") is None:
            raise PerturbationError(
                f"{path.name} records no seed; the bar reports seeded numbers only"
            )
        case = Case(
            task=name,
            repeat=int(data["repeat"]),
            seed=int(data["seed"]),
            prompt=_task_prompt(tasks_dir, name),
            output=data["output"],
        )
        key = (case.task, case.repeat)
        seen = cells.get(key)
        if seen is not None and (seen[0].prompt, seen[0].output) != (case.prompt, case.output):
            raise PerturbationError(
                f"transcripts {seen[1]} and {path.name} disagree about cell {key}: the "
                "{task}/{output} region must be identical for every variant of a cell"
            )
        if seen is None:
            cells[key] = (case, path.name)
    return [case for case, _ in cells.values()]


def _task_prompt(tasks_dir: Path, name: str) -> str:
    path = Path(tasks_dir) / f"{name}.yaml"
    if not path.is_file():
        raise PerturbationError(f"task asset not found: {path}")
    return yaml.safe_load(path.read_text())["prompt"]


def render_prompt(template: str, case: Case) -> str:
    """The critic's literal input: the template, then `{task}`/`{output}` interpolated.

    Perturbation runs on the template only and interpolation happens afterwards from
    read-only sources, which is what makes the frozen-suite invariant mechanical: a
    perturbation cannot reach `{task}` or `{output}`.
    """
    return template.format(task=case.prompt, output=case.output)


# ---- the replay primitive (§6.1, §8) ----


@dataclass
class Verdict:
    score: int
    feedback: str
    tokens_in: int
    tokens_out: int
    calls: int
    prompt_sha256: str
    payload_sha256: str
    # §3.3 guard 2's verdict for the (point, cell) this replay came from. EMPTY when the
    # replay was issued through `replay_verdicts` directly, which holds a `Rubric` and a
    # `Case` and cannot re-derive which point produced the template — blank, not clean.
    # `GuardedReplay.replay` fills them, so the taint is on the object the consumer
    # serializes, rather than in a second table they must join.
    guard_violations: list[str] = field(default_factory=list)
    guard_readings: dict[str, list[str]] = field(default_factory=dict)


def _payload_sha(model: str, seed: int | None, messages: list[Message], response_format) -> str:
    """The wire body's sha, assembled the way `OpenAICompatible.chat` assembles it.

    Recorded beside `prompt_sha256` because they answer different questions: the prompt
    sha proves which text the critic read, the payload sha proves the whole request —
    seed and `response_format` included — was the one intended. `e57f1a6` changes the
    rubric *schema*, so two variants can differ in what goes on the wire as
    `response_format` and not only in prose.
    """
    payload: dict = {"model": model, "messages": [m.to_wire() for m in messages]}
    if seed is not None:
        payload["seed"] = seed
    if response_format is not None:
        payload["response_format"] = response_format
    return sha256_text(json.dumps(payload, ensure_ascii=False))


class _PayloadSpy:
    """Captures the first request `structured()` actually sends, changing nothing.

    Reading the payload off the real call rather than rebuilding it keeps the recorded
    sha honest: a second spelling of the request would make "same request" unfalsifiable,
    which is exactly the failure §6.1 warns about.
    """

    def __init__(self, inner, model: str, seed: int | None):
        self.inner = inner
        self.model = model
        self.seed = seed
        self.payload_sha256: str | None = None

    @property
    def _response_format_unsupported(self) -> bool:
        return self.inner._response_format_unsupported

    def chat(self, messages, tools=None, response_format=None):
        if self.payload_sha256 is None:
            self.payload_sha256 = _payload_sha(self.model, self.seed, messages, response_format)
        return self.inner.chat(messages, tools, response_format=response_format)


def replay_verdicts(
    client: ModelClient, rubric: Rubric, case: Case, replays: int = 1
) -> list[Verdict]:
    """Re-issue one pinned critic request `replays` times and keep every verdict.

    `CritiqueGate` is deliberately not involved. Its memo keys on exact prompt bytes and
    would return one bought verdict N times, which is the one thing this instrument must
    never do. `structured()` is, because request construction is load-bearing.

    **A PRIMITIVE, not the route to a family.** It holds a `Rubric` and a `Case` and
    cannot re-derive which point produced the template, so guard 2 cannot live here and
    threading a `Point` in would add a parameter this function does not use. The
    `Verdict`s it returns therefore carry EMPTY `guard_violations` — blank, not clean.
    Call `GuardedReplay.replay` from `guarded_family` instead: same request, same count,
    and the pair's verdict stamped on every one of them.
    """
    if replays < 1:
        raise PerturbationError(f"replays must be >= 1, got {replays}")
    if hasattr(client, "seed"):
        client.seed = case.seed
    prompt = render_prompt(rubric.prompt, case)
    prompt_sha = sha256_text(prompt)
    model = getattr(client, "model", "")
    seed = getattr(client, "seed", None)
    verdicts = []
    for _ in range(replays):
        tracking = TrackingClient(client)
        spy = _PayloadSpy(tracking, model, seed)
        data = structured(spy, prompt, rubric.schema)
        verdicts.append(
            Verdict(
                score=int(data["score"]),
                feedback=str(data.get("feedback") or ""),
                tokens_in=tracking.usage.prompt_tokens,
                tokens_out=tracking.usage.completion_tokens,
                calls=tracking.calls,
                prompt_sha256=prompt_sha,
                payload_sha256=spy.payload_sha256 or "",
            )
        )
    return verdicts


def replay_scores(client: ModelClient, rubric: Rubric, case: Case, replays: int = 1) -> list[int]:
    """RB-P15's standing check, reduced to the number it asks for: N scores at one seed.

    The `identity` point is one call to this. Nothing extra is needed to *compute* the
    within-cell replay spread — only the plumbing around it (§8).
    """
    return [v.score for v in replay_verdicts(client, rubric, case, replays)]


# ---- the run (§6.3) ----

_ROW_KEYS = (
    "bar", "variant", "rubric_ref", "rubric_sha256", "manifest_sha256", "task", "seed",
    "repeat", "model", "point", "class", "rule", "replay", "prompt_sha256", "payload_sha256",
    "score", "threshold", "passed", "feedback", "tokens_in", "tokens_out", "calls",
    "guard_violations", "guard_readings",
)


@dataclass
class ReplayRow:
    bar: str
    variant: str
    rubric_ref: str
    rubric_sha256: str
    manifest_sha256: str
    task: str
    seed: int
    repeat: int
    model: str
    point: str
    point_class: str  # emitted as `class`, which is not a Python identifier
    rule: str
    replay: int
    prompt_sha256: str
    payload_sha256: str
    score: int
    threshold: int
    passed: bool
    feedback: str
    tokens_in: int
    tokens_out: int
    calls: int  # wire calls behind this one row: 1, or more if `structured()` retried
    # §3.3 guard 2's verdict for THIS (point, cell): the shared words, or empty. The row
    # is the artifact a later reader has; a violation that lives only in prose is how
    # this one got under-reported twice. `guard_violations` is the decision the run acts
    # on — the union of the two readings — and `guard_readings` carries each reading
    # under its own name, because the readings disagree and neither is wrong.
    guard_violations: list[str] = field(default_factory=list)
    guard_readings: dict[str, list[str]] = field(default_factory=dict)

    def row(self) -> dict:
        data = dict(vars(self))
        data["class"] = data.pop("point_class")
        return {key: data[key] for key in _ROW_KEYS}


@dataclass
class RunResult:
    rows: list[ReplayRow]
    dropped: dict[str, list[str]]
    selected: list[str]
    labels: list[str]
    threshold: int
    cells: list[Case]
    # (task, repeat) -> {point id: shared words}. Empty when every point is clean. This
    # is the UNION of the two readings: the set the decision rule acts on.
    guard: dict[tuple[str, int], dict[str, list[str]]] = field(default_factory=dict)
    # reading name -> the same table under that reading alone. Both ship, side by side.
    guard_readings: dict[str, dict[tuple[str, int], dict[str, list[str]]]] = field(
        default_factory=dict
    )
    guard_mode: str = "warn"


@dataclass
class GuardedReplay:
    """One (variant, point, cell): the exact request to replay, and guard 2's verdict on it.

    The unit `guarded_family` hands back. It carries the perturbed `Rubric` ready for
    `replay_verdicts`, the cell, the replay count the bar uses for this point's class,
    and the shared-token verdict for this pair — the union the decision rule acts on, and
    each reading under its own name.

    The verdict is on the object that carries the rubric ON PURPOSE. A shape that handed
    back templates and a separate guard table would close nothing: the consumer can
    ignore half of it and never know. Here the verdict is in hand before the rubric is.
    """

    variant: RubricVariant
    point: Point
    case: Case
    rubric: Rubric
    replays: int
    guard_violations: list[str] = field(default_factory=list)
    guard_readings: dict[str, list[str]] = field(default_factory=dict)

    @property
    def tainted(self) -> bool:
        """§3.3 guard 2 fired on this (point, cell) under at least one reading."""
        return bool(self.guard_violations)

    def replay(self, client: ModelClient) -> list[Verdict]:
        """Replay this unit the number of times the bar uses, taint already stamped on.

        `guarded_family` puts the verdict in the consumer's HAND; this puts it in their
        ARTIFACT. A consumer who calls `replay_verdicts` off the unit still has to choose
        to copy `guard_violations` into whatever they write, and a violation that lives
        anywhere except the artifact is the exact failure mode this line of work exists
        to stop. Every `Verdict` this returns carries the pair's verdict under both
        readings, so the default is recorded rather than dropped.
        """
        verdicts = replay_verdicts(client, self.rubric, self.case, self.replays)
        for verdict in verdicts:
            verdict.guard_violations = list(self.guard_violations)
            verdict.guard_readings = {
                reading: list(words) for reading, words in self.guard_readings.items()
            }
        return verdicts


@dataclass
class GuardedFamily:
    """Every replayable (variant, point, cell) of one bar, already guarded.

    `units` is the only route from here to a request. The tables beside it are the same
    verdicts aggregated for the artifacts — `summarize` reads them — not a second way to
    get a rubric.
    """

    units: list[GuardedReplay]
    dropped: dict[str, list[str]]
    selected: list[str]
    labels: list[str]
    threshold: int
    cells: list[Case]
    # (task, repeat) -> {point id: shared words}, the UNION of the two readings.
    guard: dict[tuple[str, int], dict[str, list[str]]] = field(default_factory=dict)
    guard_readings: dict[str, dict[tuple[str, int], dict[str, list[str]]]] = field(
        default_factory=dict
    )
    guard_mode: str = "warn"


IN_MEMORY_REF = "<in-memory>"


def _as_variant(entry: RubricVariant | Rubric) -> RubricVariant:
    """A bare `Rubric` is a variant with no file behind it, and the derived fields say so.

    `guarded_family` takes either. Requiring a `RubricVariant` charged the guarded route a
    construction the unguarded route never charges — five fields including a `sha256` the
    consumer computes — so from an equal starting point (a `Rubric`, a `Manifest`, a
    `Case`) the two routes were the SAME length, and the length claim was true only for a
    consumer whose rubric is a file, which is the CLI and not the hand-rolling library
    consumer RB-P23 is about.

    The derived fields are the honest ones, not invented ones:

    - `label` is the rubric's own `name`. Two variants that share a label are refused in
      `guarded_family` rather than silently collapsing into one entry of the per-label
      tables.
    - `ref` is `<in-memory>`. There is no path and no git ref to record, and naming a file
      that was never read is worse than saying there is none.
    - `sha256` is EMPTY. The populated column is the sha of a rubric FILE's bytes
      (`parse_rubric_arg`), and an object has no file; hashing the prompt instead would put
      two different meanings under one column name. Blank, not wrong — and every row still
      carries `prompt_sha256`, which pins the exact text that went on the wire.
    """
    if isinstance(entry, RubricVariant):
        return entry
    if isinstance(entry, Rubric):
        return RubricVariant(
            label=entry.name,
            spec=IN_MEMORY_REF,
            ref=IN_MEMORY_REF,
            rubric=entry,
            sha256="",
        )
    raise PerturbationError(
        f"variants must be RubricVariant or Rubric, got {type(entry).__name__}"
    )


def guarded_family(
    variants: list[RubricVariant | Rubric],
    manifest: Manifest,
    cases: list[Case],
    *,
    replays: int = 1,
    identity_replays: int = 5,
    identity_only: bool = False,
    guard: str = "warn",
) -> GuardedFamily:
    """(variants, points, cells) -> templates already paired with their guard verdicts.

    **RB-P23's fix, and it is a length claim, not an impossibility claim.** Before this
    existed, the shortest route a consumer could assemble from the public API was
    `apply_point` -> hand-built `Rubric` -> `replay_verdicts`, which touches guard 2
    nowhere; getting the guard meant knowing that a SECOND call, `guard_table`, exists
    and joining its table to the (point, cell) key by hand. The unguarded route was the
    short one. Now the guarded route is: this call, then `unit.replay(client)`. The
    unguarded route still works — a consumer can always hand-roll around any API in a
    language without private functions — and that residual is measured by a test rather
    than argued away.

    **`variants` takes `RubricVariant` OR a bare `Rubric`** (`_as_variant` normalizes,
    and documents what the derived `label`/`ref`/`sha256` mean). That is what makes the
    length claim true for the consumer RB-P23 is about rather than only for the CLI: a
    consumer holding a `Rubric` used to owe a `RubricVariant` construction the unguarded
    route never charged, which made the two routes the same length from an equal start.

    Everything a run decides before it spends anything happens here, in the order it
    happened in `run()`: the mode and threshold preconditions, then guard 2 over every
    (point, cell) — which in `error` mode refuses HERE, so no unit is ever handed out —
    then per-variant family construction, which is where the `dropped` bookkeeping and
    guards 1/3/4, the collision check and the materialization check live.

    **The materialization cost of the per-(variant, point, cell) shape.** `units` is
    cells x points x variants objects, where a templates-plus-table shape would be
    points x variants. The `Rubric` each unit carries is shared by reference across
    cells, so what is actually materialized per cell is one small dataclass holding
    references — pinned by
    `test_the_constructor_materializes_one_rubric_per_variant_point_not_per_cell`. That
    is the trade the filing asked to be chosen explicitly, and it is chosen: a consumer
    who has the rubric necessarily has the verdict.

    `identity_only` (RB-P15's standing check) is a family SELECTION, not a special case:
    the identity point moves no words, so its units come back with empty verdicts and
    replay exactly as any other unit does. Nothing here refuses to score without a point.
    """
    if guard not in GUARD_MODES:
        raise PerturbationError(f"unknown guard mode {guard!r}; expected one of {GUARD_MODES}")
    if not variants:
        raise PerturbationError("nothing to replay: no rubric variants")
    if not cases:
        raise PerturbationError("nothing to replay: no cells")
    variants = [_as_variant(entry) for entry in variants]
    labels = [v.label for v in variants]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise PerturbationError(
            f"two variants share the label {', '.join(repr(d) for d in duplicates)} — every "
            "per-label table here (templates, dropped, the rubric cache, the summary) is "
            "keyed on it, so both would be replayed with whichever rubric was built last. "
            "A bare Rubric takes its label from its name; pass RubricVariant with distinct "
            "labels to compare two rubrics of one name."
        )
    thresholds = {v.rubric.threshold for v in variants}
    if len(thresholds) != 1:
        raise PerturbationError(
            f"variants disagree on threshold ({sorted(thresholds)}); pass rates across two "
            "different decision points are not comparable"
        )
    threshold = thresholds.pop()
    points = [p for p in manifest.points if p.point_class == "identity" or not identity_only]
    full_guard = guard_table(
        points, cases, {v.label: v.rubric.prompt for v in variants}, mode=guard
    )
    union_guard = {
        cell: {pid: guard_union(hit) for pid, hit in hits.items()}
        for cell, hits in full_guard.items()
    }
    reading_guards = {
        reading: {
            cell: {pid: hit[reading] for pid, hit in hits.items() if hit[reading]}
            for cell, hits in full_guard.items()
            if any(hit[reading] for hit in hits.values())
        }
        for reading in READINGS
    }

    templates: dict[str, dict[str, str]] = {}
    dropped: dict[str, list[str]] = {}
    for variant in variants:
        templates[variant.label], dropped[variant.label] = _variant_family(
            variant, points, manifest
        )
    # One Rubric per (variant, point), shared by reference across every cell.
    rubrics = {
        (variant.label, pid): Rubric(
            name=variant.rubric.name,
            threshold=threshold,
            prompt=template,
            schema=variant.rubric.schema,
        )
        for variant in variants
        for pid, template in templates[variant.label].items()
    }

    units: list[GuardedReplay] = []
    for variant in variants:
        for case in cases:
            for point in points:
                rubric = rubrics.get((variant.label, point.id))
                if rubric is None:  # §4.1: the anchor is absent from this variant
                    continue
                cell = (case.task, case.repeat)
                units.append(
                    GuardedReplay(
                        variant=variant,
                        point=point,
                        case=case,
                        rubric=rubric,
                        replays=(
                            identity_replays if point.point_class == "identity" else replays
                        ),
                        guard_violations=list(union_guard.get(cell, {}).get(point.id, [])),
                        guard_readings={
                            reading: list(
                                full_guard.get(cell, {}).get(point.id, {}).get(reading, [])
                            )
                            for reading in READINGS
                        },
                    )
                )
    return GuardedFamily(
        units=units,
        dropped=dropped,
        selected=[p.id for p in points],
        labels=[v.label for v in variants],
        threshold=threshold,
        cells=list(cases),
        guard=union_guard,
        guard_readings=reading_guards,
        guard_mode=guard,
    )


def run(
    client: ModelClient,
    variants: list[RubricVariant | Rubric],
    manifest: Manifest,
    cases: list[Case],
    *,
    replays: int = 1,
    identity_replays: int = 5,
    identity_only: bool = False,
    model: str = "",
    guard: str = "warn",
    on_row: Callable[[ReplayRow], None] | None = None,
) -> RunResult:
    """`guarded_family` plus `unit.replay` over what it returns. Nothing else.

    ONE DERIVATION, NOT TWO THAT AGREE. The family, the guard tables and the replay
    counts are whatever the constructor said they are; this function re-derives none of
    them, so a consumer calling `guarded_family` gets the run's own answer rather than a
    parallel implementation that happens to agree with it. RB-P19's transferable finding
    is that a check inheriting the method of the thing it checks is not a check of it,
    and the same logic makes a parallel path worthless as corroboration.
    """
    family = guarded_family(
        variants,
        manifest,
        cases,
        replays=replays,
        identity_replays=identity_replays,
        identity_only=identity_only,
        guard=guard,
    )
    model = model or getattr(client, "model", "")
    rows: list[ReplayRow] = []
    for unit in family.units:
        for index, verdict in enumerate(unit.replay(client)):
            row = ReplayRow(
                bar=BAR,
                variant=unit.variant.label,
                rubric_ref=unit.variant.ref,
                rubric_sha256=unit.variant.sha256,
                manifest_sha256=manifest.sha256,
                task=unit.case.task,
                seed=unit.case.seed,
                repeat=unit.case.repeat,
                model=model,
                point=unit.point.id,
                point_class=unit.point.point_class,
                rule=unit.point.rule,
                replay=index,
                prompt_sha256=verdict.prompt_sha256,
                payload_sha256=verdict.payload_sha256,
                score=verdict.score,
                threshold=family.threshold,
                passed=verdict.score >= family.threshold,
                feedback=verdict.feedback,
                tokens_in=verdict.tokens_in,
                tokens_out=verdict.tokens_out,
                calls=verdict.calls,
                guard_violations=verdict.guard_violations,
                guard_readings=verdict.guard_readings,
            )
            rows.append(row)
            if on_row is not None:
                on_row(row)
    return RunResult(
        rows=rows,
        dropped=family.dropped,
        selected=family.selected,
        labels=family.labels,
        threshold=family.threshold,
        cells=family.cells,
        guard=family.guard,
        guard_readings=family.guard_readings,
        guard_mode=family.guard_mode,
    )


def guard_table(
    points: list[Point], cases: list[Case], templates: dict[str, str], mode: str = "warn"
) -> dict[tuple[str, int], dict[str, dict[str, list[str]]]]:
    """§3.3 guard 2 for every (point, cell), decided before a single request goes out.

    **A PRIMITIVE of `guarded_family`, and the offline audit route.** It stays public
    because a reader auditing which pairs are tainted wants the table alone, without
    materializing a family; but a consumer who is going to REPLAY should call
    `guarded_family`, which calls this and hands the verdicts back already attached to
    the rubrics they belong to. Guard 2 is a property of a (point, cell) pair, so unlike
    guards 1/3/4 it cannot ride inside `apply_point`, which never sees a cell.

    `templates` maps variant label to that variant's BASE template. The whole-text
    reading is a function of the template, so it is computed per variant and unioned:
    a word that moves on one variant under comparison is a word that moves.

    Returns `{(task, repeat): {point id: {reading: shared words}}}`, carrying only the
    (cell, point) pairs at least one reading flags. `guard_union` collapses a value to
    the decision the run acts on.

    **`warn` is the default, and a hard error is the wrong default.** Eight of the
    twenty M1-screened cells violate this guard, `nav-prod-port` — the canonical cell of
    this whole line of work — among them, and two of the twelve committed anchor cells.
    A run that aborts on a violation makes those cells unrunnable, which is a regression
    dressed as a stricter guard: the status quo at least produced measurements.

    What the status quo failed to do was make the violation impossible to miss, so that
    is what is enforced instead. The violating point still runs; every row it produces
    carries the shared words; the summary reports the family recomputed without it; and
    attribution is credited only if the separation survives dropping it (`_compare`).
    `error` is available for callers who want the strict reading, and it refuses here,
    before any spend.
    """
    if mode not in GUARD_MODES:
        raise PerturbationError(f"unknown guard mode {mode!r}; expected one of {GUARD_MODES}")
    table: dict[tuple[str, int], dict[str, dict[str, list[str]]]] = {}
    for case in cases:
        for point in points:
            readings: dict[str, set[str]] = {reading: set() for reading in READINGS}
            for base in templates.values():
                for reading, words in cell_guard_violations(point, case, base).items():
                    readings[reading] |= set(words)
            hit = {reading: sorted(words) for reading, words in readings.items()}
            if guard_union(hit):
                table.setdefault((case.task, case.repeat), {})[point.id] = hit
    if table and mode == "error":
        named = "; ".join(
            f"{task} r{repeat}: {pid} shares {guard_union(hit)} ("
            + ", ".join(f"{reading}={hit[reading]}" for reading in READINGS)
            + ")"
            for (task, repeat), hits in sorted(table.items())
            for pid, hit in sorted(hits.items())
        )
        raise PerturbationError(
            f"shared-token guard (spec §3.3 step 3, guard 2) violated on {len(table)} cell(s) "
            f"— {named}. Decision rule: {GUARD_DECISION_RULE}. Re-run with the default guard "
            "mode to measure them anyway, with every violating row and the guard-dropped "
            "family recorded."
        )
    return table


def _variant_family(
    variant: RubricVariant, points: list[Point], manifest: Manifest
) -> tuple[dict[str, str], list[str]]:
    family: dict[str, str] = {}
    dropped: list[str] = []
    seen: dict[str, str] = {}
    for point in points:
        # check=False so the message below can name the variant as well as the point;
        # the same guards run either way, and neither route can reach a request.
        template = apply_point(point, variant.rubric.prompt, check=False)
        if template is None:
            dropped.append(point.id)
            continue
        collision = seen.get(template)
        if collision is not None:
            raise PerturbationError(
                f"points '{collision}' and '{point.id}' produce the same template on variant "
                f"'{variant.label}' — a point that changed nothing measures nothing"
            )
        problems = point_admissibility_violations(point, variant.rubric.prompt, template)
        if problems:
            raise PerturbationError(
                f"point '{point.id}' is inadmissible on variant '{variant.label}' "
                f"(spec §3.3 step 3): it {'; it '.join(problems)} — a point that is not "
                "meaning-preserving measures a requirement edit, not a perturbation"
            )
        seen[template] = point.id
        family[point.id] = template
        _check_materialization(manifest, variant.label, point, template)
    return family, dropped


def _check_materialization(manifest: Manifest, label: str, point: Point, template: str) -> None:
    """Where the manifest already materialized this label, the bytes must still match.

    A manifest that has drifted from the rubric it describes would let a reader audit
    one family while the run measured another.
    """
    recorded = point.variants.get(label)
    if not recorded or not recorded.get("applicable"):
        return
    if recorded.get("sha256") != sha256_text(template):
        raise PerturbationError(
            f"point '{point.id}' on variant '{label}' does not match the manifest's "
            f"materialized sha — {manifest.path} has drifted from the rubric it describes"
        )


# ---- the decision rule (§7) ----


def summarize(result: RunResult, manifest_sha256: str) -> dict:
    threshold = result.threshold
    by_cell: dict[tuple[str, int], dict[str, dict[str, list[ReplayRow]]]] = {}
    for row in result.rows:
        cell = by_cell.setdefault((row.task, row.repeat), {})
        cell.setdefault(row.variant, {}).setdefault(row.point, []).append(row)

    cells = []
    for case in result.cells:
        key = (case.task, case.repeat)
        per_variant = by_cell.get(key, {})
        violations = result.guard.get(key, {})
        readings = {
            reading: dict(result.guard_readings.get(reading, {}).get(key, {}))
            for reading in READINGS
        }
        block = {
            "task": case.task,
            "repeat": case.repeat,
            "seed": case.seed,
            "guard_violations": dict(violations),
            "guard_readings": readings,
            "variants": {
                label: _variant_stats(
                    per_variant.get(label, {}),
                    [p for p in result.selected if p not in result.dropped[label]],
                    threshold,
                    violations,
                    readings,
                )
                for label in result.labels
            },
            "comparisons": [
                _compare(result, per_variant, a, b, threshold, key, violations)
                for a, b in combinations(result.labels, 2)
            ],
        }
        cells.append(block)

    return {
        "bar": BAR,
        "threshold": threshold,
        "manifest_sha256": manifest_sha256,
        "guard": {
            "rule": "spec §3.3 step 3, guard 2 — no word a point adds or removes may "
            "appear in the cell's {task} or {output}. 'A word a point adds or removes' "
            "has two defensible readings and the spec supports each in a different "
            "sentence; both are computed and reported here and NEITHER is wrong.",
            "readings": dict(READING_RULES),
            "decision_rule": GUARD_DECISION_RULE,
            "mode": result.guard_mode,
            "violations": [
                {
                    "task": task,
                    "repeat": repeat,
                    "point": pid,
                    "words": words,
                    "readings": {
                        reading: result.guard_readings.get(reading, {})
                        .get((task, repeat), {})
                        .get(pid, [])
                        for reading in READINGS
                    },
                }
                for (task, repeat), hits in sorted(result.guard.items())
                for pid, words in sorted(hits.items())
            ],
            "by_reading": {
                reading: [
                    {"task": task, "repeat": repeat, "point": pid, "words": words}
                    for (task, repeat), hits in sorted(
                        result.guard_readings.get(reading, {}).items()
                    )
                    for pid, words in sorted(hits.items())
                ]
                for reading in READINGS
            },
        },
        # `requests` is the row count — one row per (variant, cell, point, replay).
        # `wire_calls` is what actually went out: they differ exactly when `structured()`
        # retried, which would otherwise inflate `tokens_total` invisibly.
        "requests": len(result.rows),
        "wire_calls": sum(r.calls for r in result.rows),
        "tokens_total": sum(r.tokens_in + r.tokens_out for r in result.rows),
        "variants": [
            {
                "label": label,
                "rubric_ref": next(r.rubric_ref for r in result.rows if r.variant == label),
                "rubric_sha256": next(r.rubric_sha256 for r in result.rows if r.variant == label),
                "dropped_rules": result.dropped[label],
            }
            for label in result.labels
            if any(r.variant == label for r in result.rows)
        ],
        "cells": cells,
    }


def _variant_stats(
    point_rows: dict[str, list[ReplayRow]],
    family: list[str],
    threshold: int,
    violations: dict[str, list[str]],
    readings: dict[str, dict[str, list[str]]],
) -> dict:
    """One (variant, cell) block, plus the same statistic with tainted points removed.

    `pass_rate` stays the FULL family so a run remains comparable with every committed
    number, including the anchor set's `expect_pass_rate`. `guard_dropped` is the
    recomputation a reader would otherwise have to do by hand — and did, in prose, in
    `docs/eval.md`, because the artifacts could not carry it.

    `guard_violations` is the union decision; `guard_readings` names each reading, so a
    reader who prefers one of them can recompute `guard_dropped` for it without a run.
    """
    stats = _family_stats(point_rows, family, threshold)
    hits = {pid: words for pid, words in violations.items() if pid in family}
    stats["guard_violations"] = hits
    stats["guard_readings"] = {
        reading: {pid: words for pid, words in hit.items() if pid in family}
        for reading, hit in readings.items()
    }
    stats["guard_dropped"] = (
        _family_stats(point_rows, [pid for pid in family if pid not in hits], threshold)
        if hits
        else None
    )
    return stats


def _family_stats(
    point_rows: dict[str, list[ReplayRow]], family: list[str], threshold: int
) -> dict:
    """One (variant, cell) block. A point passes only if every one of its replays does."""
    scores = [row.score for pid in family for row in point_rows.get(pid, [])]
    passed = sum(
        1 for pid in family if point_rows.get(pid) and all(r.passed for r in point_rows[pid])
    )
    identity = [row.score for row in point_rows.get("identity", [])]
    low, high = (min(scores), max(scores)) if scores else (0, 0)
    return {
        "pass_rate": f"{passed}/{len(family)}",
        "passed": passed,
        "family_size": len(family),
        "score_min": low,
        "score_max": high,
        "spread": high - low,
        "margin_zero": sum(
            1
            for pid in family
            if any(abs(r.score - threshold) <= 1 for r in point_rows.get(pid, []))
        ),
        "identity_scores": identity,
        "identity_spread": (max(identity) - min(identity)) if identity else 0,
        # min and max straddling the threshold: the family cannot tell pass from fail.
        "fragile": bool(scores) and low < threshold <= high,
    }


def _compare(
    result: RunResult,
    per_variant: dict[str, dict[str, list[ReplayRow]]],
    a: str,
    b: str,
    threshold: int,
    cell: tuple[str, int],
    violations: dict[str, list[str]],
) -> dict:
    """Paired dropping, then the separation rule. F is post-drop and reported explicitly.

    Guard dropping is a second, cell-scoped drop on top of paired dropping, and it gates
    attribution: a separation carried by a point that shares a token with the cell is
    RB-P4's measured mechanism, not evidence about the edit. So `attributable` now
    requires the separation to survive removing the tainted points. It never removes a
    cell from the run — when everything is tainted, `guard_verdict` is `undefined` and
    nothing is credited, which is the honest answer, not an abort.
    """
    family = [
        pid
        for pid in result.selected
        if pid not in result.dropped[a] and pid not in result.dropped[b]
    ]
    dropped_rules = [
        {"rule": pid, "variant": label}
        for pid in result.selected
        if pid not in family
        for label in (a, b)
        if pid in result.dropped[label]
    ]
    rows_a, rows_b = per_variant.get(a, {}), per_variant.get(b, {})
    present_a = {pid for pid in family if rows_a.get(pid)}
    present_b = {pid for pid in family if rows_b.get(pid)}
    if present_a != present_b:
        raise PerturbationError(
            f"post-drop rule-id sets differ for '{a}' and '{b}' on cell {cell}: "
            f"{sorted(present_a ^ present_b)} — refusing to report across mismatched families"
        )
    stats_a = _family_stats(rows_a, family, threshold)
    stats_b = _family_stats(rows_b, family, threshold)
    verdict = _separation(stats_a, stats_b, len(family))
    guard_family = [pid for pid in family if pid not in violations]
    guard_verdict = _separation(
        _family_stats(rows_a, guard_family, threshold),
        _family_stats(rows_b, guard_family, threshold),
        len(guard_family),
    )
    fragile = [label for label, s in ((a, stats_a), (b, stats_b)) if s["fragile"]]
    return {
        "a": a,
        "b": b,
        "verdict": verdict,
        "family_size": len(family),
        "dropped_rules": dropped_rules,
        "a_pass_rate": stats_a["pass_rate"],
        "b_pass_rate": stats_b["pass_rate"],
        "fragile": fragile,
        "guard_verdict": guard_verdict,
        "guard_family_size": len(guard_family),
        "guard_dropped_rules": [
            {"rule": pid, "reason": "shared-token", "words": violations[pid]}
            for pid in family
            if pid in violations
        ],
        # §7 rule 2: a fragile family voids attribution on this cell even if rule 1
        # fires. RB-P19 adds the third: so does a separation that only the
        # shared-token-violating points carried.
        "attributable": (
            verdict == "distinguishable" and guard_verdict == "distinguishable" and not fragile
        ),
    }


def _separation(stats_a: dict, stats_b: dict, size: int) -> str:
    """§7 rule 1, on whichever family it is handed."""
    if size == 0:
        return "undefined"
    if (stats_a["passed"] == size and stats_b["passed"] == 0) or (
        stats_b["passed"] == size and stats_a["passed"] == 0
    ):
        return "distinguishable"
    if stats_a["passed"] == stats_b["passed"]:
        return "indistinguishable"
    return "inconclusive"


def format_table(summary: dict) -> str:
    lines = [
        "| variant | task | repeat | seed | pass | min | max | spread | margin0 "
        "| identity | fragile |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for cell in summary["cells"]:
        for label, stats in cell["variants"].items():
            lines.append(
                f"| {label} | {cell['task']} | {cell['repeat']} | {cell['seed']} | "
                f"{stats['pass_rate']} | {stats['score_min']} | {stats['score_max']} | "
                f"{stats['spread']} | {stats['margin_zero']} | "
                f"{','.join(str(s) for s in stats['identity_scores'])} | {stats['fragile']} |"
            )
    guard = summary["guard"]
    if guard["violations"]:
        lines += [
            "",
            f"GUARD VIOLATIONS ({guard['mode']} mode) — spec §3.3 step 3, guard 2, "
            f"BOTH readings; decision: {guard['decision_rule']}",
        ]
        for hit in guard["violations"]:
            per_reading = "; ".join(
                f"{reading}: {', '.join(hit['readings'][reading]) or '(none)'}"
                for reading in READINGS
            )
            lines.append(
                f"- {hit['task']} r{hit['repeat']}: {hit['point']} shares "
                f"{', '.join(hit['words'])} with the cell [{per_reading}] — dropped from the "
                "guard-clean family, attribution void unless the separation survives it"
            )
        for cell in summary["cells"]:
            for label, stats in cell["variants"].items():
                if stats["guard_dropped"]:
                    lines.append(
                        f"  {label} {cell['task']} r{cell['repeat']}: "
                        f"{stats['pass_rate']} full -> "
                        f"{stats['guard_dropped']['pass_rate']} guard-clean"
                    )
    lines += ["", "Pairwise (post-drop family):"]
    for cell in summary["cells"]:
        for comparison in cell["comparisons"]:
            dropped = ", ".join(
                f"{d['rule']} (absent from {d['variant']})" for d in comparison["dropped_rules"]
            )
            lines.append(
                f"- {cell['task']} r{cell['repeat']}: {comparison['a']} "
                f"{comparison['a_pass_rate']} vs {comparison['b']} {comparison['b_pass_rate']} "
                f"-> {comparison['verdict']} (F={comparison['family_size']}"
                + (f"; dropped {dropped}" if dropped else "")
                + ")"
                + ("" if comparison["attributable"] or comparison["verdict"] != "distinguishable"
                   else f" — attribution VOID: fragile {comparison['fragile']}")
            )
    lines += [
        "",
        f"requests: {summary['requests']}  wire calls: {summary['wire_calls']}  "
        f"tokens: {summary['tokens_total']}  manifest: {summary['manifest_sha256'][:12]}",
    ]
    return "\n".join(lines)


def exit_status(result: RunResult) -> int:
    """The status a run that MEASURED something leaves behind: 0, or `GUARD_VIOLATION_EXIT`.

    **What counts, and it is the rows.** Guard 2's union is non-empty on a (point, cell)
    pair the run ACTUALLY REPLAYED. Every row carries that pair's verdict already
    (`GuardedReplay.replay` stamps it), so this reads the run's own answer rather than
    re-deriving one beside it — RB-P19's finding is that a second derivation which
    happens to agree corroborates nothing.

    Three consequences, each deliberate:

    - **A point dropped from every variant's family does not count.** `guard_table` runs
      over every selected point, before `_variant_family` drops the ones whose anchor is
      absent, and the substitution-pair reading is a function of the point's own
      `from`/`to` pair — so `result.guard` can flag a point that reached no request and
      entered no statistic. Statusing on that table would be a verdict about a pair that
      never ran. It is still in the summary, and the drop is still in `dropped_rules`.
    - **`--identity-only` is always 0.** The identity point moves no words and cannot
      violate; RB-P15's standing check keeps the status it has always had.
    - **A violation on a variant whose rows were all dropped does not count for the
      status, but a violation on any variant that DID replay the pair does.** The union
      is across variants exactly as `guard_table` computes it.

    This is a statement about the GUARD FIRING, not about whether the conclusion survived
    dropping the point. Whether the separation holds on the guard-clean family is
    `_compare`'s `guard_verdict`/`attributable`, it is already in the summary, and it is
    not re-decided here: a run whose attribution survives its violations still fired the
    guard, and a reader who is told otherwise by an exit code learns the wrong thing.
    """
    return GUARD_VIOLATION_EXIT if any(row.guard_violations for row in result.rows) else 0


# ---- CLI (§6.2) ----

_EXIT_CONTRACT = f"""exit status (RB-P24):
  0  measured; guard 2 fired on nothing that ran
  {REFUSAL_EXIT}  did not complete a measurement (bad input, --guard error on a violating
     cell, or an abort mid-run). Artifacts from a {REFUSAL_EXIT} are PARTIAL, not absent:
     the --json sink flushes per row so a killed run keeps what it got.
  {USAGE_EXIT}  usage error (argparse's number, including this module's own validations)
  {GUARD_VIOLATION_EXIT}  measured, WITH guard-2 violations - every artifact is still written,
     and the GUARD section names each violating (point, cell)
  {ARTIFACT_WRITE_EXIT}  measured, but an artifact could not be written (the --summary file).
     The table is still printed. Outranks {GUARD_VIOLATION_EXIT}; --violations-exit-zero
     does not suppress it.
  {RENDER_FAILURE_EXIT}  measured, but THE REPORT COULD NOT BE RENDERED: the write of
     the table to stdout failed for a reason that is NOT the reader going away -
     fd 1 read-only (EBADF), fd 1 closed before the process started, a full
     device. The measurement is COMPLETE and every file that could be written is
     on disk; read those, not this run's log, because the table is not in it. The
     reason is on stderr. Outranks {ARTIFACT_WRITE_EXIT}; --violations-exit-zero
     does not suppress it.
Branch on 0-{RENDER_FAILURE_EXIT}. A stdout that fails at the table print
no longer leaves the range, and the two arms report DIFFERENT numbers on
purpose: if the reader is gone (EPIPE) nothing was owed to anyone, so the run
reports the status it EARNED (RB-P27); if the write fails for any other reason
the report was wanted and is now lost, so the run
reports {RENDER_FAILURE_EXIT} instead of claiming a clean measurement (RB-P31).
Neither arm invents a status the run did not have.
WHAT IS STILL OUTSIDE THE RANGE is the interpreter or a signal, and that list
is OPEN rather than exhaustive. Measured so far: 130 SIGINT, 143 SIGTERM, a
stderr lost while the run was writing to it, and 120 for a stdout lost OUTSIDE
the run path (--help, which argparse writes and exits before main is reached).
Read those as "this process did not choose its own status", NOT as "the
measurement did not happen": the artifacts may still be on disk. ENOSPC on a
real full device has NOT been measured in the field on this platform; it is
handled by class, not by evidence.
NOTE for in-process callers (main is exported): once either arm has fired,
this process's sys.stdout is replaced by a sink that RAISES the original
failure on any further write, and fd 1 itself is left exactly as it was found.
A caller that keeps writing after main gets an exception, never silence.
"""


class _LostStdout:
    """What `sys.stdout` becomes once the run path's write to it has failed.

    ONE recovery for both arms, and it replaces the `os.dup2(devnull, 1)` that v0.19.0
    used. The job is exactly one thing: make CPython's finalization flush succeed. That
    flush runs AFTER `main` has returned and after `SystemExit` has chosen its number, it
    calls `sys.stdout.flush()` on whatever `sys.stdout` is bound to at that moment, and
    if it raises, the interpreter throws the chosen status away and exits 120. Below fd
    1's `BufferedWriter` the doomed bytes are still in the buffer when we get here, so
    that re-failure is not hypothetical - it is what the whole 120 half of RB-P31's
    matrix is. Rebinding `sys.stdout` to this object gives the flush nothing to fail on.

    Three properties the `dup2` recipe did not have, and each is a filed defect closed:

    - **It needs no file descriptor.** `os.open(os.devnull)` inside the handler can
      itself fail, and RB-P31 filed that as its second route: the recovery raising
      `OSError` out of the arm lands the run on REFUSAL_EXIT, which is the very thing
      the arm exists to prevent. There is no `os.open` here, so the route is gone rather
      than caught. (K1 could not construct EMFILE from outside the process and said so;
      the answer to a route that cannot be measured is to remove it, not to argue it is
      rare.)
    - **It does not touch fd 1.** RB-P33: the `dup2` pointed this process's fd 1 at the
      null device permanently, so every later write - including a child process's, which
      inherits fd 1 - silently succeeded into nothing. fd 1 is left exactly as found.
    - **It raises rather than lies.** RB-P33's own words: silence is the one option not
      available. A caller that writes to `sys.stdout` after `main` returns gets the
      original failure re-raised, which is true: that stream really is broken.

    `flush` and `close` are no-ops because the bytes are already lost and re-attempting
    the write is what this exists to stop.
    """

    closed = False

    def __init__(self, cause: BaseException) -> None:
        self.cause = cause

    def write(self, _text: str) -> int:
        raise self.cause

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    def isatty(self) -> bool:
        return False


def main(argv: list[str] | None = None) -> None:
    """The CLI. Exits through the contract in `_EXIT_CONTRACT`; see the module comment.

    ONE SIDE EFFECT AN IN-PROCESS CALLER HAS TO KNOW ABOUT (RB-P33). If the write of the
    table to stdout fails - the reader gone, fd 1 read-only, a full device - this
    function rebinds `sys.stdout` to a `_LostStdout` and LEAVES it rebound, because
    CPython's finalization flush happens after this function returns and would otherwise
    re-fail on the same stream and replace the status with 120. `sys.__stdout__` and fd 1
    are untouched, and a later write to `sys.stdout` re-raises the original failure, so
    the loss stays visible to whoever writes next.
    """
    parser = argparse.ArgumentParser(
        prog="python -m bantamkit.criticreplay",
        description=(
            "Perturbation bar: replay one critic over a family of meaning-preserving\n"
            "edits to its own prompt and report the pass rate with its spread."
        ),
        epilog=_EXIT_CONTRACT,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--rubric",
        action="append",
        required=True,
        metavar="LABEL=SPEC",
        help="repeatable; SPEC is a path or git:<ref>:<path>",
    )
    parser.add_argument(
        "--manifest", type=Path, help="perturbation manifest (default: by rubric name)"
    )
    parser.add_argument(
        "--transcripts", type=Path, required=True, help="directory of P8 transcripts (the cells)"
    )
    parser.add_argument("--task", action="append", help="repeatable; restrict to these tasks")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--replays", type=int, default=1, help="replays per perturbation point")
    parser.add_argument("--identity-replays", type=int, default=5)
    parser.add_argument("--identity-only", action="store_true", help="RB-P15's standing check")
    parser.add_argument(
        "--guard",
        choices=GUARD_MODES,
        default="warn",
        help=(
            "what to do when a point shares a moved word with a cell (spec §3.3 guard 2, "
            "computed under BOTH readings and tainted if either flags): 'warn' measures it "
            "and records both readings on every row and in the summary (default); 'error' "
            "refuses before any request"
        ),
    )
    parser.add_argument("--json", type=Path, help="append one JSON line per replay to this file")
    parser.add_argument("--summary", type=Path, help="write the summary JSON here")
    parser.add_argument(
        "--violations-exit-zero",
        action="store_true",
        help=(
            f"exit 0 instead of {GUARD_VIOLATION_EXIT} when guard 2 fired on a replayed "
            "pair, for a procedure whose violations are EXPECTED and recorded (the anchor "
            "set's second pass is one). Changes nothing that is written, and prints what "
            "it suppressed on stderr"
        ),
    )
    args = parser.parse_args(argv)
    if args.replays < 1 or args.identity_replays < 1:
        parser.error("--replays and --identity-replays must be >= 1")

    jsonl = None
    try:
        variants = [parse_rubric_arg(spec) for spec in args.rubric]
        manifest = load_manifest(args.manifest, rubric_name=variants[0].rubric.name)
        cases = load_cases(args.transcripts, tasks=args.task)
        if not cases:
            raise PerturbationError(
                f"no transcripts with answers in {args.transcripts}"
                + (f" for task(s) {args.task}" if args.task else "")
            )
        client = OpenAICompatible(
            base_url=args.base_url, model=args.model, timeout=args.timeout
        )
        sink = None
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            jsonl = args.json.open("a")

            def sink(row: ReplayRow) -> None:
                jsonl.write(json.dumps(row.row()) + "\n")
                jsonl.flush()  # a killed run keeps its partials

        result = run(
            client,
            variants,
            manifest,
            cases,
            replays=args.replays,
            identity_replays=args.identity_replays,
            identity_only=args.identity_only,
            model=args.model,
            guard=args.guard,
            on_row=sink,
        )
        summary = summarize(result, manifest.sha256)
    except BantamError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    finally:
        if jsonl is not None:
            jsonl.close()

    # RB-P24 review, C1: this write is the one artifact produced AFTER the measurement,
    # and it used to sit outside every handler — so an unwritable `--summary` raised an
    # unhandled OSError and the process exited 1, the REFUSAL status, on a run that had
    # already flushed every JSONL row. A run that measured may not report that it
    # refused. The failure gets its own number and the table is still printed, because
    # the measurement happened and stdout is where it is readable.
    write_failure: OSError | None = None
    if args.summary:
        try:
            args.summary.parent.mkdir(parents=True, exist_ok=True)
            args.summary.write_text(json.dumps(summary, indent=2) + "\n")
        except OSError as e:
            write_failure = e
            print(
                f"error: measured, but the summary could not be written to "
                f"{args.summary}: {e}. The measurement itself is the table, printed "
                "after this line unless a render failure is reported too; the JSONL "
                "rows, if --json was passed, are on disk.",
                file=sys.stderr,
            )

    # RB-P31. `format_table` is OUTSIDE the try BY DESIGN. A failure to BUILD the table
    # is a bug in this module, and a bug may not be laundered into a contract status: it
    # propagates with its traceback. Only the WRITE is inside an arm. Pinned by
    # `test_a_non_pipe_failure_around_the_table_print_is_not_downgraded`, which raises
    # from `format_table` and requires both raisers to reach the caller — move this call
    # back inside the try and its OSError case goes red.
    table = format_table(summary)
    render_failure: str | None = None
    if sys.stdout is None:
        # fd 1 was not open when this process started (`prog 1>&-`). CPython leaves
        # `sys.stdout` as None in that case, `print` to a None stdout is a SILENT NO-OP,
        # and the table is lost with no exception raised anywhere — which is why this is
        # READ as a state rather than caught as an error, and why RB-P31's own filed
        # attack direction ("give the print an `except OSError` arm") would have left
        # this cell exactly where it was: at REFUSAL_EXIT, at every table size, on a run
        # with every artifact on disk. Measured 2026-08-13, 9 of 9 cells.
        render_failure = "fd 1 was not open when this process started"
    else:
        try:
            print(table)
            sys.stdout.flush()
        except BrokenPipeError as e:
            # RB-P27 lever (2). The reader of stdout is gone (`... | head -1` once `head`
            # has exited), so the table cannot be delivered — and NOBODY WAS WAITING FOR
            # IT. Its absence costs no reader anything, so the run reports the status it
            # EARNED below rather than the interpreter's 120: a lost stdout may DOWNGRADE
            # to a number the run already had; it may never invent one. This is the ONLY
            # arm that downgrades, and "nobody was reading" is the whole of the reason.
            #
            # The explicit `flush()` is load-bearing: `print` writes into a buffer, and
            # without it the EPIPE would surface at interpreter shutdown instead of here,
            # where it can be handled.
            sys.stdout = _LostStdout(e)
        except OSError as e:
            # RB-P31. The write failed and the reader was NOT gone: fd 1 is read-only
            # (EBADF), or the device is full (ENOSPC), or the fd is otherwise unusable.
            # stderr is live in every measured cell of this class, so this is a report
            # that could not be RENDERED, not a reader that walked away — the difference
            # the two arms exist to keep apart. The run measured, so it does not report
            # REFUSAL_EXIT; the report is gone, so it does not report the earned status
            # either. It reports RENDER_FAILURE_EXIT, and says why on stderr.
            #
            # `except OSError`, not `except Exception`: a non-OSError raised by the write
            # itself is a bug and still propagates, pinned by
            # `test_a_non_oserror_at_the_table_write_is_not_downgraded`.
            render_failure = str(e)
            sys.stdout = _LostStdout(e)
    if render_failure is not None:
        print(
            f"error: measured, but the report could not be rendered on stdout: "
            f"{render_failure}. The measurement is COMPLETE — the JSONL rows, if --json "
            "was passed, and the summary file, if --summary was passed and could be "
            "written, are on disk and are the same bytes a run with a live stdout would "
            f"have left. The table is not in this run's log. Exit status "
            f"{RENDER_FAILURE_EXIT}.",
            file=sys.stderr,
        )

    # RB-P24. LAST, after every artifact that could be written exists: the JSONL (whose
    # sink already flushed per row), the summary and the table. Non-zero here means
    # "measured, and the guard fired" or "measured, and a file could not be written" or
    # "measured, and the report could not be rendered" — never "nothing happened".
    # Nothing that is written depends on this.
    status = exit_status(result)
    if status and args.violations_exit_zero:
        print(
            f"note: guard 2 fired on a replayed pair; suppressing status {status} because "
            "--violations-exit-zero was passed. The violations are in the GUARD section "
            "above and in the artifacts.",
            file=sys.stderr,
        )
        status = 0
    if write_failure is not None:
        # Outranks the guard status and survives the hatch: 3 promises "every artifact
        # is written", and the hatch is an opt-out from 3 alone.
        status = ARTIFACT_WRITE_EXIT
    if render_failure is not None:
        # Outranks 4 for 4's own reason, one step further out. Each number in this ladder
        # outranks the one below because the lower one's own promise is false about this
        # run: 3 promises "every artifact is written", and 4 promises "the table is still
        # printed". Here neither is true, and the one a reader is worse off not knowing
        # is that the report never reached them. Survives the hatch for the same reason 4
        # does — the hatch is an opt-out from 3 alone.
        status = RENDER_FAILURE_EXIT
    if status:
        raise SystemExit(status)


if __name__ == "__main__":
    main()
