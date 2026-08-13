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
    "rubric_arg_shape_problem",
    "rubric_label_collision_problem",
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
#   1  DID NOT COMPLETE A MEASUREMENT THAT WAS ATTEMPTED — every `BantamError` path
#      reached from inside `main`'s `try`, `--guard error` included, and every abort
#      in the middle of one. The perturbation-bar spec §6/§11 rest on this family
#      being non-zero. It does NOT promise that nothing was written: the JSONL sink
#      flushes per row on purpose, so a run that dies mid-family (a refused
#      connection on request 40 of 80) exits 1 with rows already on disk. 1 means the
#      run owes you no conclusion, not that it left no trace. Read it as "fix the
#      input or the environment and run it again", and treat any artifact from a 1 as
#      partial. WHAT IS NO LONGER IN HERE (RB-P32): a command line that is malformed
#      on its face. Those left for 2, because they can leave no artifact at all and
#      "treat the artifacts as partial" is not advice a typo can act on.
#   2  THE COMMAND LINE ITSELF IS WRONG, and no run was attempted. Two sources, one
#      number. The number is argparse's and is recorded here as a MEASURED one
#      (`--not-a-flag` exits 2), pinned from a shell by
#      `test_argparses_usage_status_is_measured_not_assumed`, so that the statuses this
#      module does choose cannot silently collide with it. WHICH of this module's own
#      rules report it IS this module's choice, and since RB-P32 the answer is: all of
#      the argument-SHAPE ones and only those, every one of them routed through
#      `parser.error` above `main`'s `try` (`--replays 0`, `--identity-replays 0`,
#      `--rubric` with no `LABEL=`, `--rubric a=git:HEAD`, `--rubric a=X --rubric a=Y`).
#      shape rules (exact set): --identity-replays --replays --rubric
#      THAT LINE IS CHECKED AGAINST THE CODE, not against this paragraph (K4B/I7). The
#      old check compared this block and the epilog for two substrings and joined them
#      with `and`, so renaming `parser.error` here turned it green while the epilog kept
#      a claim that was false. `test_the_usage_status_names_exactly_the_shape_rules_the_
#      code_has` now DERIVES the set — every `parser.error` reachable above `main`'s
#      `try`, and the `--flag` names its messages carry — and requires this roster and
#      the epilog's to be exactly it, with
#      `test_every_shape_rule_flag_is_the_usage_status_in_the_field` measuring each named
#      flag to 2 and each unnamed module rule to 1 from a real shell. A rename changes
#      nothing; adding a shape rule without a field case, or naming a flag here that has
#      no shape rule, is red.
#      WHERE THE LINE IS, AND WHY IT IS NOT "WHOSE RULE IS IT" (RB-P32). A 2 is an
#      argv that is malformed ON ITS FACE: `rubric_arg_shape_problem` resolves no
#      path, opens no file and runs no `git`, so the verdict is a function of the
#      typed string alone. That is what licenses the strong claim a 2 makes — this
#      command can never work on any machine, so nothing ran, nothing was written and
#      re-running it unchanged is guaranteed to fail again. A 1 is an argv that is
#      well formed and names something the world did not supply (`--rubric
#      a=/tmp/gone.yaml`, an empty `--transcripts` directory): the same argv succeeds
#      on the next run once the world changes, and there may be partial artifacts to
#      handle. The line is drawn for the CI job that has to ACT on the number: on a 2
#      a human edits the command line and there is nothing on disk to quarantine; on a
#      1 the artifacts are partial and the input or the environment is what to fix.
#      Three candidate lines were tested against the measured matrix and all three
#      failed as descriptions of the code as it stood: "2 is argparse's, 1 is ours" is
#      circular (`--replays 0` is this module's rule and was already 2); "2 before
#      parsing finishes, 1 after" is false (the `parser.error` call is after
#      `parse_args` returns); "1 needs the world, 2 does not" was false in one
#      direction (`--rubric /tmp/x.yaml` consults nothing and was 1) — and it is that
#      third one that RB-P32 made TRUE by moving the behaviour, rather than by
#      re-describing it.
#      WHAT MOVED, and it is a behaviour change a CI consumer sees. Four cases went
#      from 1 to 2: `--rubric SPEC` with no `LABEL=`, `--rubric =SPEC`, `--rubric
#      LABEL=`, and `--rubric a=git:HEAD` (which did not even reach the handler — it
#      raised an uncaught `ValueError` and gave a raw traceback with the
#      interpreter's 1). Every other case in the matrix kept its number. Measured in a
#      real shell before and after in
#      docs/eval-data/2026-08-13-rbp32-argument-validation-matrix.md and
#      -matrix-after.md.
#      A FIFTH CASE MOVED IN K4B, and the sentence above was FALSE without it (K4's C2):
#      `--rubric a=X --rubric a=Y`. Two labels that collide are decidable from the typed
#      strings alone — no path, no file, no `git` — yet the rule lived in
#      `guarded_family` inside the `try` and reported 1 on an argv the world had
#      supplied everything for. It now goes through `rubric_label_collision_problem` and
#      `parser.error`; `guarded_family` keeps its own copy for in-process callers, whose
#      labels come from a bare `Rubric`'s `name` and are world-dependent, so the two
#      checks agree on the verdict and differ on what they are entitled to look at. It
#      also stopped a measured waste: `--rubric a=git:R:P --rubric a=git:R:P` spent TWO
#      `git show` subprocesses before noticing, and now spends none. Before and after in
#      docs/eval-data/2026-08-13-k4b-c2-duplicate-rubric-label.md.
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
#      device (ENOSPC), or a stdout whose CODEC cannot represent the table
#      (`PYTHONIOENCODING=latin-1` or `=ascii`: the GUARD section always carries U+2014
#      and U+00A7, so the write raises `UnicodeEncodeError` — K4B/C1, and until it was
#      fixed that case escaped this arm and reported 1 on a run that measured, which is
#      the RB-P24 defect the PR's own headline claimed to have closed).
#      RB-P31, and it is the SAME shape as 4 one step further out:
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
#   - the arm catches `OSError` and `UnicodeEncodeError`, not `Exception`, and that pair
#     is a LINE rather than a list: they are the two things about stdout THE CALLER
#     OWNS — the descriptor, and the codec it was wrapped in. Neither is editable from
#     inside this file and on both the measurement is complete. Anything else raised BY
#     THE WRITE is a bug in this module and still propagates: pinned by
#     `test_a_non_oserror_at_the_table_write_is_not_downgraded` (a `RuntimeError`) and by
#     `test_a_non_unicode_valueerror_at_the_table_write_is_not_downgraded` (a bare
#     `ValueError`, the sibling of the class that WAS added, so the widening is pinned
#     exactly where it stops).
#     K4B/C1 IS WHY THE SECOND CLASS IS THERE, and it is worth the sentence: the first
#     version of this arm justified its narrowness on "a non-`OSError` at the write is a
#     bug in THIS MODULE". That generalisation was argued against `RuntimeError` and
#     never tested against the only realistic non-`OSError` a write can raise.
#     `UnicodeEncodeError` at the write is a property of the caller's stdout in exactly
#     the way `EBADF` is a property of the caller's fd, so it belongs on the same side of
#     the line — and with the class missing, `PYTHONIOENCODING=latin-1` was enough to
#     make a run that measured report REFUSAL_EXIT (field-measured at 3981efd: status 1,
#     320 rows and a summary byte-identical to the same argv on a live stdout that
#     earned 3, docs/eval-data/2026-08-13-k4b-c1-stdout-encoding-matrix.md).
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
#   - stderr, on BOTH of its axes. Every arm here reports on stderr, so a run whose
#     stderr is gone loses the explanation and the finalization flush of fd 2 takes the
#     status with it — and a stderr whose CODEC cannot encode what is written to it is
#     the same hole one class over. This module's own status messages are ASCII for that
#     reason (K4B/C1), which makes the 4 and 5 reports survive `PYTHONIOENCODING=ascii`;
#     a `BantamError` whose message is not ASCII, on such a stderr, still leaves by
#     traceback. It reports the number the refusal would have reported anyway, so it is a
#     DELIVERY defect and not a status one, and it is filed rather than fixed:
#     docs/eval-data/2026-08-13-k4b-c1-stdout-encoding-matrix.md.
#   - fd 1 pointing at a DIRECTORY. CPython dies in `init_sys_streams` with
#     `IsADirectoryError` before `main` exists, prints `Fatal Python error`, and the
#     shell reads 1 (measured 2026-08-13, K4B/M3). Nothing in this module runs, so
#     nothing here can choose that number; it is recorded so the next reader does not
#     re-file it as a defect of this arm. Pinned by
#     `test_fd_one_on_a_directory_never_reaches_this_module`.
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

    @property
    def template_sha256(self) -> str:
        """The sha of the RUBRIC the critic reads, as distinct from the FILE it came in.

        RB-P17, measured 2026-08-14: the two committed `B-nonewline` runs record
        `rubric_sha256` `59b0fe81ecf3…` and `29f299707fd6…` — two different values — for
        ONE rubric, whose template hashes `d1f32ad2947b…` in both. The recorded column is
        the file's bytes, so two files carrying the same `prompt` under different `name:`
        or `threshold:` framing report as two different rubrics, and the field cannot
        answer the one question provenance exists to answer: did these two runs judge
        with the same rubric? This property answers it, and it is the value the frozen
        manifest already records as `materialized_variants.<label>.base_sha256`, so a
        derived variant's row ties back to a committed manifest entry by equality.

        It is a SECOND column, not a redefinition of the first. `rubric_sha256` stays the
        file's bytes — every committed row means that, and a field that changes meaning
        under a fixed name is RB-P18's defect, which is the one being fixed here.
        """
        return sha256_text(self.rubric.prompt)


def rubric_arg_shape_problem(arg: str) -> str | None:
    """What is malformed about one `--rubric` value ON ITS FACE, or `None` if nothing is.

    THE WHOLE POINT IS WHAT THIS FUNCTION MAY NOT DO (RB-P32). It resolves no path,
    opens no file and runs no `git`: its answer is a function of the string the user
    typed and of nothing else. That is what makes it safe to run above `main`'s `try`
    and report through `parser.error`, i.e. as a `USAGE_EXIT` — a verdict of "this argv
    can never work on any machine", which is a claim only a check that consulted no
    machine is entitled to make. A rule that needs the filesystem (is the rubric
    there? is it a rubric?) belongs in `parse_rubric_arg` below and is a
    `REFUSAL_EXIT`, because the same argv works on the next run once the world changes.

    Split out of `parse_rubric_arg` rather than duplicated, so the CLI and an
    in-process caller cannot drift on what "malformed" means.
    """
    label, sep, spec = arg.partition("=")
    if not sep or not label or not spec:
        return f"--rubric wants LABEL=SPEC, got {arg!r}"
    if spec.startswith("git:"):
        # `git:HEAD` used to reach `spec.split(":", 2)` below and raise an UNCAUGHT
        # `ValueError` out of `main` — a raw traceback and the interpreter's 1, which
        # from CI is indistinguishable by status from a refusal that reported itself
        # (RB-P32, matrix case C4). Empty segments are the same defect one step in:
        # `git::x` and `git:HEAD:` are malformed on their face, and letting them
        # through would have spent a `git show` to say so.
        parts = spec.split(":", 2)
        if len(parts) < 3 or not parts[1] or not parts[2]:
            return f"--rubric git spec wants git:<ref>:<path>, got {spec!r}"
    if spec.startswith("derive:"):
        parts = spec.split(":", 3)
        if len(parts) < 4 or not all(parts[1:]):
            return (
                "--rubric derive spec wants "
                f"derive:<manifest-path>:<rule-id>:git:<ref>:<path>, got {spec!r}"
            )
        base = parts[3]
        if not base.startswith("git:"):
            return (
                f"--rubric derive spec wants a git: base, got {base!r} — a derived variant "
                "has no file of its own, so the only thing that makes its recorded ref "
                "resolvable is that every segment of it is immutable. A working-tree path "
                "is not, and unlike the path form there is no file left to hash as a "
                "fallback. This is also what makes a derive-of-a-derive unrepresentable, "
                "so the load order can never cycle."
            )
        base_parts = base.split(":", 2)
        if len(base_parts) < 3 or not base_parts[1] or not base_parts[2]:
            return f"--rubric derive spec wants git:<ref>:<path> as its base, got {base!r}"
    return None


def rubric_label_collision_problem(specs: list[str]) -> str | None:
    """What is malformed about a SET of `--rubric` values on its face, or `None`.

    THE SAME RULE `guarded_family` ENFORCES, DECIDED ONE LAYER EARLIER AND FROM LESS
    (K4's C2). Two `--rubric` values that share a LABEL collide on every machine: a
    label is the text left of the first `=` in the string the user typed, so the
    collision is a function of the argv and of nothing else — no path resolved, no file
    opened, no `git` run. That makes it an argument-SHAPE rule under RB-P32's own
    definition, and until K4B it was the one shape rule that did not behave like one:
    it was refused by `guarded_family` INSIDE `main`'s `try` and reported
    `REFUSAL_EXIT`, which falsified, verbatim, the `#   2` block's "all of the
    argument-SHAPE ones and only those" and its "a `1` is an argv that names something
    the world did not supply" — here the world supplied everything. Measured at 3981efd
    from a real shell: status 1, 0 bytes on stdout
    (docs/eval-data/2026-08-13-k4b-c2-duplicate-rubric-label.md).

    WHY THE `guarded_family` CHECK STAYS WHERE IT IS, rather than moving here. It is not
    this check on this input. An in-process caller may pass a bare `Rubric`, whose label
    is its `name` and therefore comes from a file on disk — world-dependent, undecidable
    from any argv, and a `PerturbationError` inside the run is the right answer for it.
    This one is decidable from the typed strings, so the CLI answers it before it spends
    anything, and the two checks agree on the verdict while disagreeing on what they are
    allowed to look at.

    IT ALSO STOPS THE MODULE PAYING TO LEARN IT. `--rubric a=git:R:P --rubric a=git:R:P`
    spent TWO `git show` subprocesses in `parse_rubric_arg` before `guarded_family`
    noticed the duplicate (measured, same artifact; zero after). That is exactly the
    cost the `git:` shape check above exists to avoid, and it was being paid one flag
    over.
    """
    labels = [spec.partition("=")[0] for spec in specs]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if not duplicates:
        return None
    return (
        f"--rubric label {', '.join(repr(d) for d in duplicates)} given more than once; "
        "every per-label table (templates, dropped, the rubric cache, the summary) is "
        "keyed on the label, so two --rubric values sharing one would both be replayed "
        "with whichever rubric was built last. Give each --rubric a distinct LABEL=."
    )


def parse_rubric_arg(arg: str) -> RubricVariant:
    """`LABEL=SPEC`, where SPEC is a path, `git:<ref>:<path>`, or a `derive:` rule.

    The git form exists because the acceptance test needs rubrics that live only in
    history. `load_rubric` is name-only and has no path hook, so the parsed `Rubric` is
    passed around as an instance.

    THE RECORDED REF IS THE WHOLE SPEC, NOT A PIECE OF IT (RB-P17, 2026-08-14). The git
    branch used to record `source = ref`, so a row said `d2f78b7` — a commit and not a
    file. Two rubrics in one commit were indistinguishable in the record, and
    `rubric_sha256` could not be re-derived from the row without knowing which path to
    ask `git show` for. `RubricVariant.spec` held the answer and never reached a row.
    Every branch now records the string a second reader can hand back to this function.

    THE `derive:` FORM: `derive:<manifest-path>:<rule-id>:git:<ref>:<path>`.

    A perturbed variant is a rule applied to a committed ref, and until now it was not
    expressible as one. `B-nonewline` — the null control the whole RB-P14 finding turns
    on — is `A-asfiled`'s template minus its single trailing newline, which is exactly
    the frozen manifest's `W1-trailing-newline` point; with no way to say that, it was
    materialized to a scratch file and two committed summaries record an absolute
    `/private/tmp` path as its provenance. Written in this form the null control is::

        --rubric B-nonewline=derive:assets/evals/perturbations/task-completion.yaml\
:W1-trailing-newline:git:d2f78b7:assets/rubrics/task-completion.yaml

    WHY THE MANIFEST IS IN THE STRING, and not left implicit. The filing proposed
    `derive:<label>:<rule-id>` — `derive:A-asfiled:W1-trailing-newline`. That resolves
    only from the argv that also defined `A-asfiled`, and it names the manifest nowhere,
    so a row carrying it is a pointer into a process that has exited: the same failure as
    a pointer into a directory that has been cleaned, one indirection along. Every
    segment here is repo-relative or a git ref, so a reader who has ONLY this repository
    and one row can recover the exact bytes the critic read — read the manifest at that
    path, take the point with that id, `git show` that ref and path, apply. No argv, no
    machine, no `/private/tmp`. `manifest_sha256` is already on every row, so the reader
    can also tell whether the manifest they just read is the one the run used.

    Ordering is manifest, then rule, then base, because the base is the only segment that
    contains a `:` — three splits and the remainder is the base spec, with no escaping.

    NO SILENT NO-OP, AND NO CYCLE. A rule whose anchor is absent from the base raises
    rather than returning the base unchanged: `W1-trailing-newline` on a template that
    has no trailing newline (`B-nonewline` itself — it is the rule's fixed point) names
    no variant, and a variant that is silently its own base is RB-P17's defect one level
    in. The base must be a `git:` spec, which makes a derive-of-a-derive unrepresentable
    on its face, so no load order can cycle and no resolution can recurse.

    The CLI has already rejected a malformed `arg` through `parser.error` before this
    runs (RB-P32); the same check is re-raised here as a `PerturbationError` for
    in-process callers, so that every malformed `--rubric` raises ONE kind of error
    rather than some of them escaping as `ValueError`.
    """
    problem = rubric_arg_shape_problem(arg)
    if problem is not None:
        raise PerturbationError(problem)
    label, _, spec = arg.partition("=")
    if spec.startswith("derive:"):
        return RubricVariant(
            label=label, spec=spec, ref=spec, rubric=_derive_rubric(spec), sha256=""
        )
    if spec.startswith("git:"):
        _, ref, path = spec.split(":", 2)
        raw = _git_show(ref, path)
    else:
        file = Path(spec)
        if not file.is_file():
            raise PerturbationError(f"rubric not found: {spec}")
        raw = file.read_text()
    return RubricVariant(
        label=label, spec=spec, ref=spec, rubric=_parse_rubric(raw, spec), sha256=sha256_text(raw)
    )


def _derive_rubric(spec: str) -> Rubric:
    """Resolve `derive:<manifest-path>:<rule-id>:git:<ref>:<path>` to the perturbed rubric.

    `sha256` is BLANK on the variant this builds, following the `IN_MEMORY_REF` precedent
    exactly: the populated `rubric_sha256` column is the sha of a rubric FILE's bytes, a
    derived variant has no file, and hashing something else into that column would put two
    meanings under one name. `rubric_template_sha256` is the populated one here, and it is
    the value the manifest already records for this (point, variant) cell — so the row and
    the frozen manifest tie together by equality rather than by prose.
    """
    _, manifest_spec, rule_id, base_spec = spec.split(":", 3)
    manifest = load_manifest(Path(manifest_spec))
    points = [point for point in manifest.points if point.id == rule_id]
    if not points:
        raise PerturbationError(
            f"rule {rule_id!r} is not a point in {manifest_spec}: "
            f"have {', '.join(point.id for point in manifest.points)}"
        )
    _, ref, path = base_spec.split(":", 2)
    base = _parse_rubric(_git_show(ref, path), base_spec)
    perturbed = apply_point(points[0], base.prompt)
    if perturbed is None:
        raise PerturbationError(
            f"rule {rule_id!r} is inapplicable to {base_spec}: its anchor is absent from that "
            "template, so this spec names no variant. A rule that cannot fire would return "
            "the base rubric unchanged, and a variant silently equal to its own base is "
            "RB-P17's defect one level in — the record would name a perturbation that never "
            "happened. (This is what `W1-trailing-newline` does against a base that already "
            "has no trailing newline: it is that rule's fixed point.)"
        )
    return Rubric(
        name=base.name, threshold=base.threshold, prompt=perturbed, schema=base.schema
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
        # K4B/M2, and it is RB-P32's `git:HEAD` shape one directory over: a `.json` in
        # here that is not a transcript used to raise an uncaught `KeyError: 'task'` (or
        # a `JSONDecodeError`) straight out of `main`, so the user got a raw traceback
        # and the interpreter's 1 where the refusal path would have given them
        # `error: ...` and the same 1. The NUMBER was never wrong - this directory is
        # world, so a 1 is right - only the delivery was, and "reported by traceback" is
        # not a way this module reports anything. Refusing rather than skipping is
        # deliberate: a silently skipped file is a cell missing from the run.
        try:
            data = json.loads(path.read_text())
        except ValueError as e:
            raise PerturbationError(f"{path.name} is not readable as JSON: {e}") from e
        if not isinstance(data, dict) or "task" not in data or "repeat" not in data:
            raise PerturbationError(
                f"{path.name} is in {transcripts_dir} but is not a transcript: a "
                "transcript is a JSON object recording at least `task` and `repeat`. "
                "Point --transcripts at a directory of P8 transcripts, or move this "
                "file out of it."
            )
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
    # The same wire body key-sorted (RB-P18). Defaulted here and NOT on `ReplayRow`: a
    # `Verdict` is also built by callers that never went through `_PayloadSpy`, whereas a
    # row a run writes must state the column or fail to construct.
    payload_canonical_sha256: str = ""
    # §3.3 guard 2's verdict for the (point, cell) this replay came from. EMPTY when the
    # replay was issued through `replay_verdicts` directly, which holds a `Rubric` and a
    # `Case` and cannot re-derive which point produced the template — blank, not clean.
    # `GuardedReplay.replay` fills them, so the taint is on the object the consumer
    # serializes, rather than in a second table they must join.
    guard_violations: list[str] = field(default_factory=list)
    guard_readings: dict[str, list[str]] = field(default_factory=dict)


# ---- what a payload sha NAMES, published beside the field (RB-P18) ----

#: The exact call behind each recorded payload column. Emitted into every summary a run
#: writes, so the recipe travels with the artifact instead of living in a docstring the
#: reader of a JSONL row will never open.
PAYLOAD_SHA_RECIPES = {
    "payload_sha256": "sha256(json.dumps(payload, ensure_ascii=False))",
    "payload_canonical_sha256": (
        "sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True))"
    ),
}

#: WHERE A READER LOOKS. Emitted into every summary beside the recipes above.
PAYLOAD_SHA_NOTE = (
    "`prompt_sha256` is the CROSS-RECORD IDENTITY: it hashes the rendered critic prompt "
    "and depends on no serialization choice, so two records that agree on it put the same "
    "text in front of the critic, whoever wrote them. The payload columns hash the whole "
    "wire body, which is strictly more than the prompt (model, seed, response_format) and "
    "therefore also strictly more fragile. `payload_sha256` is that body under THIS "
    "writer's key insertion order and is the value every committed row before 2026-08-14 "
    "carries; `payload_canonical_sha256` is the same bytes key-sorted, is independent of "
    "insertion order, and is the column two records may be compared on. Measured "
    "2026-08-14 on all six committed (variant, seed) cells: the canonical recipe "
    "reproduces the payload shas in "
    "docs/eval-data/2026-08-11-sa3-14b-nav-prod-port-critic-replay.json exactly, and the "
    "insertion-order recipe reproduces the perturbation-bar JSONL rows exactly, so the "
    "two frozen record families differ by the one keyword argument `sort_keys=True` and "
    "by nothing else. To interpret a row written before 2026-08-14, which carries only "
    "`payload_sha256` and names no recipe: re-run its cell and see which of the two "
    "columns the frozen value lands in."
)


def payload_shas_recorded(value: str | list[str]) -> tuple[str, ...]:
    """The payload shas a record's `payload_sha256` field states, whatever SHAPE it is in.

    ONE NAME, TWO ARITIES — MEASURED 2026-08-14 over the whole committed record, not
    asserted. 1280 occurrences across 12 artifacts carry a `str`; 30 occurrences in
    `2026-08-11-sa3-14b-nav-prod-port-critic-replay.json` carry a `list`. A reader diffing
    the two families with `==` gets `False` from the TYPE before the hash is ever compared,
    which is RB-P18's own defect one level below the recipe.

    THE LIST IS NOT A TYPO, AND FLATTENING IT WOULD DESTROY EVIDENCE. The two writers
    record different UNITS. A bar row is one replay, so its field is one sha. An SA3 entry
    is one CELL, and its field is the SET of distinct shas observed across that cell's
    processes — the cardinality is itself the claim, stated in that file's own
    `how_to_reproduce`: "every cell here shows exactly one payload sha across its
    processes, so any score spread is the server's, not the prompt's". Measured: all 30
    lists have length 1, so all 30 cells make that claim and none of them fails it. A
    reader who took `[0]` would silently discard a claim that a two-element list would
    have falsified.

    So this returns a TUPLE and preserves cardinality: comparison between records is
    between sets of shas, never between a `str` and a `list`. What it does NOT do is
    rewrite anything — the committed bytes keep their shapes; this is the reader supplying
    a defined reading, exactly as `_rows_as_replay_rows` supplies an absent column.
    """
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise PerturbationError(
        f"a `payload_sha256` field is a sha string or a list of sha strings, got {value!r}"
    )


def _payload_shas(
    model: str, seed: int | None, messages: list[Message], response_format
) -> tuple[str, str]:
    """The wire body's shas, assembled the way `OpenAICompatible.chat` assembles it.

    Returns `(payload_sha256, payload_canonical_sha256)` — ONE dict, TWO serializations,
    and the pair is the whole of RB-P18's fix.

    Recorded beside `prompt_sha256` because they answer different questions: the prompt
    sha proves which text the critic read, the payload shas prove the whole request —
    seed and `response_format` included — was the one intended. `e57f1a6` changes the
    rubric *schema*, so two variants can differ in what goes on the wire as
    `response_format` and not only in prose.

    WHY `sort_keys` AND NOT SOME OTHER CANONICALISATION. RB-P18 was filed saying two
    recipes "serialize different dicts" under one field name. Re-measured on all six
    committed (variant, seed) cells: they do not. They serialize the IDENTICAL dict, and
    the entire cross-record incomparability is that the scratchpad writer passed
    `sort_keys=True` and this one did not. `sort_keys` is therefore not a canonicalisation
    chosen for taste — it is the one that (1) removes the measured difference, being the
    only key-order-independent form of the same call, and (2) is ALREADY A COMMITTED VALUE:
    the second column reproduces SA3's frozen `payload_sha256` bit for bit, so the fix
    reaches BACKWARD into the frozen record rather than only forward. Any other order-
    independent recipe (`ensure_ascii=True`, different `separators`) would be equally
    order-free and would match nothing that is already written down, leaving SA3's 30 rows
    exactly as uninterpretable as they are today.

    WHY THE FIRST COLUMN IS UNTOUCHED, in name, recipe and value. 1280 committed
    occurrences mean the insertion-order recipe, and a field that changes meaning under a
    fixed name is RB-P18's own defect — the same argument that made
    `rubric_template_sha256` a second column beside `rubric_sha256` rather than a
    redefinition of it. This is also why the fix is NOT the one RB-P18 filed: "version the
    field name so two recipes cannot share one" would make permanent, in the schema, a
    difference that canonicalisation removes.
    """
    payload: dict = {"model": model, "messages": [m.to_wire() for m in messages]}
    if seed is not None:
        payload["seed"] = seed
    if response_format is not None:
        payload["response_format"] = response_format
    return (
        sha256_text(json.dumps(payload, ensure_ascii=False)),
        sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
    )


def _payload_sha(model: str, seed: int | None, messages: list[Message], response_format) -> str:
    """The recorded `payload_sha256`, unchanged in name, in recipe and in value.

    Kept as its own entry point because it is the recipe 1280 committed rows were written
    under and because `docs/eval-data/2026-08-13-rbp16-rbp17-rbp18-survey.py`, which is
    committed evidence and therefore never edited, imports it by this name.
    """
    return _payload_shas(model, seed, messages, response_format)[0]


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
        self.payload_canonical_sha256: str | None = None

    @property
    def _response_format_unsupported(self) -> bool:
        return self.inner._response_format_unsupported

    def chat(self, messages, tools=None, response_format=None):
        if self.payload_sha256 is None:
            # Both columns come off ONE observation of the request. Computing the
            # canonical form from a second reconstruction would make "same request"
            # unfalsifiable in exactly the way this class exists to prevent.
            self.payload_sha256, self.payload_canonical_sha256 = _payload_shas(
                self.model, self.seed, messages, response_format
            )
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
                payload_canonical_sha256=spy.payload_canonical_sha256 or "",
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
    "bar", "variant", "rubric_ref", "rubric_sha256", "rubric_template_sha256",
    "manifest_sha256", "task", "seed",
    "repeat", "model", "point", "class", "rule", "replay", "prompt_sha256", "payload_sha256",
    "payload_canonical_sha256",
    "score", "threshold", "passed", "feedback", "tokens_in", "tokens_out", "calls",
    "guard_violations", "guard_readings",
)


@dataclass
class ReplayRow:
    bar: str
    variant: str
    rubric_ref: str
    rubric_sha256: str  # the FILE's bytes, blank when the variant has no file
    rubric_template_sha256: str  # the RUBRIC the critic read; see RubricVariant
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
    payload_sha256: str  # this writer's key INSERTION order; see PAYLOAD_SHA_RECIPES
    payload_canonical_sha256: str  # the same body key-SORTED; the comparable column
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
        # K4B/C2. This is the WORLD-DEPENDENT half of the rule and it stays here: a bare
        # `Rubric` takes its label from its `name`, which came off a file on disk, so
        # whether two of them collide cannot be decided from any command line. The half
        # that CAN be — two `--rubric LABEL=SPEC` strings sharing the text left of the
        # first `=` — is `rubric_label_collision_problem`, checked above `main`'s `try`
        # and reported as `USAGE_EXIT`, so the CLI never reaches this raise and never
        # spends a `git show` to arrive at it. Same verdict, two entitlements.
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
                rubric_template_sha256=unit.variant.template_sha256,
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
                payload_canonical_sha256=verdict.payload_canonical_sha256,
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
        # RB-P16's third missing piece: a statement ACROSS cells. Report only — see
        # `_directional`, which records that the rule RB-P16 proposes has no instance in
        # the committed record and is therefore reported rather than enforced.
        "directional": _directional(cells),
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
        # THE RECIPE TRAVELS WITH THE ARTIFACT (RB-P18). A reader holding this file and a
        # row file can say which serialization produced each payload column without
        # opening this repository, which is what "the recipe is published" has to mean for
        # evidence that outlives the tree it was written in. `cross_record_identity` is
        # here and not only in a commit message because it is the field a reader should be
        # diffing on in the first place.
        "payload_sha256_recipes": {
            "recipes": dict(PAYLOAD_SHA_RECIPES),
            "payload": "{model, messages, seed?, response_format?}, in that insertion order",
            "cross_record_identity": "prompt_sha256",
            "comparable_column": "payload_canonical_sha256",
            "note": PAYLOAD_SHA_NOTE,
        },
        "variants": [
            {
                "label": label,
                "rubric_ref": next(r.rubric_ref for r in result.rows if r.variant == label),
                "rubric_sha256": next(r.rubric_sha256 for r in result.rows if r.variant == label),
                "rubric_template_sha256": next(
                    r.rubric_template_sha256 for r in result.rows if r.variant == label
                ),
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


def _passing_points(
    point_rows: dict[str, list[ReplayRow]], family: list[str]
) -> list[str]:
    """The family points this variant passed. A point passes only if every replay does.

    THE ONE DEFINITION. `_family_stats` counts this list and `_effect` intersects two of
    them, so the pass rate a cell reports and the point-level disagreement it reports
    cannot drift apart. RB-P19's transferable finding is that a second derivation which
    happens to agree corroborates nothing — so there is not a second one.
    """
    return [
        pid for pid in family if point_rows.get(pid) and all(r.passed for r in point_rows[pid])
    ]


def _family_stats(
    point_rows: dict[str, list[ReplayRow]], family: list[str], threshold: int
) -> dict:
    """One (variant, cell) block. A point passes only if every one of its replays does."""
    scores = [row.score for pid in family for row in point_rows.get(pid, [])]
    passed = len(_passing_points(point_rows, family))
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
        # RB-P16: the verdict is one of four words for a two-dimensional fact, so it
        # travels with its size, its direction and its point-level disagreement. Read
        # `_effect`'s docstring for why these fields and not a banding vocabulary.
        # It decides nothing — `attributable` below is untouched by it.
        "effect": _effect(a, b, rows_a, rows_b, family),
        "family_size": len(family),
        "dropped_rules": dropped_rules,
        "a_pass_rate": stats_a["pass_rate"],
        "b_pass_rate": stats_b["pass_rate"],
        "fragile": fragile,
        "guard_verdict": guard_verdict,
        "guard_effect": _effect(a, b, rows_a, rows_b, guard_family),
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
    """§7 rule 1, on whichever family it is handed.

    **Read the word beside its `effect` block, never alone.** This function returns four
    words for a two-dimensional fact and RB-P16 is the measured consequence:

    - `inconclusive` covers everything that is neither `F/F`-versus-`0/F` nor a tie. Over
      the whole committed §7 record (12 comparisons, 2 runs, measured 2026-08-13) eleven
      cells wear it, spanning |Δ| 3/11 = 0.2727 to 5/6 = 0.8333 — a factor of 3.06.
    - `indistinguishable` is **equal pass COUNTS, not agreement.** The one committed cell
      that carries it (`B-nonewline` 7/11 vs `C-attempted` 7/11, r1) is a cell on which
      the two variants disagree on **2 of 11 points**: `B` passes `P2-asks-requests`,
      `C` passes `W2-double-trailing`. The word claims an identity the measurement does
      not support, and it is the only cell in that record where the disagreement is
      two-sided — on the other eleven the pass sets are nested, so Δ alone recovers it.
      A fresh run measured 2026-08-14 puts a second instance on the record: the shipped
      rubric versus its trailing-newline variant reads `indistinguishable` at 2/11 vs
      2/11 on `nav-prod-port` r0 while the two disagree on **4 of 11 points**.

    Neither word is renamed here. The defect is not the spelling: a rename would make the
    committed record incomparable while still asserting nothing about agreement. What
    fixes it is that `_compare` now ships `_effect` beside every verdict, so a reader gets
    the size, the direction and the point-level disagreement without re-deriving them.
    """
    if size == 0:
        return "undefined"
    if (stats_a["passed"] == size and stats_b["passed"] == 0) or (
        stats_b["passed"] == size and stats_a["passed"] == 0
    ):
        return "distinguishable"
    if stats_a["passed"] == stats_b["passed"]:
        return "indistinguishable"
    return "inconclusive"


def _effect(
    a: str,
    b: str,
    rows_a: dict[str, list[ReplayRow]],
    rows_b: dict[str, list[ReplayRow]],
    family: list[str],
) -> dict:
    """The effect size that travels with the verdict (RB-P16). It DECIDES NOTHING.

    ## Why this shape, argued against the measured band

    The band this has to render is not hypothetical. Every §7 comparison this project has
    ever committed — 12, over 2 runs, surveyed 2026-08-13 in
    `docs/eval-data/2026-08-13-rbp16-rbp17-rbp18-survey.md` and re-derived from the rows
    again on 2026-08-14 — is:

        |Δrate|  0.2727 0.2727 0.3333 0.3636 0.3636 0.4545 0.4545 0.6364 0.6364 0.6667 0.8333
        |Δn|          3      3      4      4      4      5      5      7      7      8     10

    plus one exact tie. Eleven of the twelve read `inconclusive`. The worst — `A-asfiled`
    1/12 vs `C-attempted` 11/12, ten of twelve points flipped, **one point short of
    `0/F` versus `F/F` on each side** — wears the same word as the mildest, 7/11 vs 10/11.
    So the requirement is exact: 0.2727 and 0.8333 must be tellable **at a glance**.

    Four fields, each earning its place against that band:

    - **`delta_passed` / `delta_rate`, signed `a - b`.** The sign convention is the
      committed survey's, so its signed columns and this block are directly comparable.
      `delta_rate` is the at-a-glance number: no two DISTINCT values in the band above
      collide at the 3 decimals `format_table` prints (0.273 / 0.333 / 0.364 / 0.455 /
      0.636 / 0.667 / 0.833). `format_table` additionally renders |`delta_rate`| as a
      10-cell bar, because the eye compares LENGTHS faster than it compares decimals and
      the whole complaint is that a reader could not tell these apart while skimming.
    - **`points_from_separation` = `F - |Δn|`.** Distance to the only thing §7 rule 1
      credits. This is derived from the rule itself and invents no threshold —
      deliberately: a banding vocabulary (`large`/`small`) would be a new grade with new
      cut points, and an instrument that grades evidence may not quietly re-grade its
      own. The worst committed cell reads 2; the mildest reads 8.
    - **`disagreeing_points` with `a_only` / `b_only`.** This is what makes the tie word
      honest and is the field `delta_*` cannot supply. At Δn = 0 the difference is 0 and
      the two families can still disagree — measured on the one committed
      `indistinguishable` cell, they disagree on 2 of 11 points. Reported by NAME so the
      claim is checkable point by point rather than re-derived by the reader.

    ## What this deliberately does not do

    It does not touch `attributable`, and no field of it is read by any decision. §7's
    rules 1-3 decide exactly what they decided before this function existed; moving
    attribution would move a committed finding by moving the ruler and needs its own
    argued case. Rule 1 has decided all 12 committed cells, so rules 2 and 3 have never
    been reached — a reporting change is the only lever here that touches every cell.
    """
    size = len(family)
    passed_a = set(_passing_points(rows_a, family))
    passed_b = set(_passing_points(rows_b, family))
    delta = len(passed_a) - len(passed_b)
    a_only = [pid for pid in family if pid in passed_a and pid not in passed_b]
    b_only = [pid for pid in family if pid in passed_b and pid not in passed_a]
    return {
        "delta_passed": delta,
        "delta_rate": round(delta / size, 4) if size else 0.0,
        "sign": (delta > 0) - (delta < 0),
        "leads": (a if delta > 0 else b) if delta else None,
        "points_from_separation": size - abs(delta) if size else 0,
        "disagreeing_points": len(a_only) + len(b_only),
        "a_only": a_only,
        "b_only": b_only,
    }


def _directional(cells: list[dict]) -> list[dict]:
    """The cross-cell statement §7 never made: does one pair point one way on every cell?

    **REPORT ONLY. Nothing here is read by `attributable` or by any verdict.** That is not
    caution, it is the measurement: RB-P16's filing proposes requiring the sign to agree
    across cells before an `inconclusive` may be called directional, and **no committed
    cell exercises that rule.** Surveyed over the entire committed §7 record on
    2026-08-13 and re-derived here: every `inconclusive` cell has sign −1, there is no run
    in which two cells of one pair point in opposite directions, and the only non-negative
    sign anywhere is the exact tie that already reads `indistinguishable`. Shipping it as
    a gate would be shipping a rule with zero instances behind it, which would change
    nothing on any cell while looking like it had been tested. So it is shipped as a
    sentence a reader can check, and `conflicting` is the field that would go true first.

    A tie ABSTAINS rather than breaking agreement: sign 0 is "this cell says nothing about
    direction", which is exactly what an equal pass count means. `directional` therefore
    requires agreement AND at least one cell that actually pointed.
    """
    by_pair: dict[tuple[str, str], list[dict]] = {}
    for cell in cells:
        for comparison in cell["comparisons"]:
            by_pair.setdefault((comparison["a"], comparison["b"]), []).append(
                {
                    "task": cell["task"],
                    "repeat": cell["repeat"],
                    "verdict": comparison["verdict"],
                    **{
                        key: comparison["effect"][key]
                        for key in ("sign", "delta_rate", "leads")
                    },
                }
            )
    out = []
    for (a, b), seen in by_pair.items():
        signs = [c["sign"] for c in seen]
        nonzero = {s for s in signs if s}
        rates = [abs(c["delta_rate"]) for c in seen]
        out.append(
            {
                "a": a,
                "b": b,
                "cells": seen,
                "signs": signs,
                "ties": signs.count(0),
                "conflicting": len(nonzero) > 1,
                "directional": len(nonzero) == 1,
                "leads": (a if nonzero == {1} else b) if len(nonzero) == 1 else None,
                "abs_delta_rate_min": min(rates) if rates else 0.0,
                "abs_delta_rate_max": max(rates) if rates else 0.0,
            }
        )
    return out


def _format_effect(effect: dict, size: int) -> str:
    """One line a skimming reader can rank without subtracting two fractions.

    The bar is ten ASCII cells of |Δrate|, `#` filled. Against the committed band that
    is `[########--]` for the worst cell (0.8333) and `[###-------]` for the mildest
    (0.2727) — the difference RB-P16 says a reader cannot currently see. ASCII on
    purpose: RB-P31/K4B measured what this module does when stdout cannot encode a
    character, and a report line is not the place to find out again.
    """
    delta, rate = effect["delta_passed"], effect["delta_rate"]
    filled = round(abs(rate) * 10)
    bar = "#" * filled + "-" * (10 - filled)
    lead = f"leads {effect['leads']}" if effect["leads"] else "neither leads"
    # A tie renders " 0", never "+0": the column width is kept but no direction is
    # implied, because an equal pass count is exactly the absence of one.
    dtxt = f"{delta:+d}" if delta else " 0"
    rtxt = f"{rate:+.3f}" if delta else " 0.000"
    return (
        f"    effect: d={dtxt}/{size} ({rtxt}) [{bar}] {lead}; "
        f"{effect['points_from_separation']} from separation; "
        f"{effect['disagreeing_points']}/{size} points disagree"
    )


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
            # RB-P16. A SECOND line rather than a longer first one: the verdict line's
            # bytes are what every committed table and every downstream reader already
            # parses, and the effect is an addition to the report, not a reflow of it.
            lines.append(_format_effect(comparison["effect"], comparison["family_size"]))
    if summary.get("directional"):
        lines += [
            "",
            "Directional consistency (one pair across its cells) — REPORT ONLY, it decides "
            "nothing; §7 has no cross-cell rule and no committed cell exercises one:",
        ]
        for pair in summary["directional"]:
            signs = ",".join("+" if s > 0 else "-" if s < 0 else "0" for s in pair["signs"])
            if pair["conflicting"]:
                verdict = "CONFLICTING — cells of this pair point opposite ways"
            elif pair["directional"]:
                verdict = f"consistent toward {pair['leads']}"
            else:
                verdict = "no direction (every cell ties)"
            lines.append(
                f"- {pair['a']} vs {pair['b']}: signs {signs} -> {verdict}"
                + (f" ({pair['ties']} tie)" if pair["ties"] == 1 else "")
                + (f" ({pair['ties']} ties)" if pair["ties"] > 1 else "")
                + f"; |d| {pair['abs_delta_rate_min']:.3f}..{pair['abs_delta_rate_max']:.3f}"
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
  {REFUSAL_EXIT}  did not complete a measurement that was ATTEMPTED: the command line was
     well formed and something it named could not be used (a rubric that is not
     on disk, a directory with no answered transcripts), or --guard error fired
     on a violating cell, or the run aborted mid-family. Artifacts from a
     {REFUSAL_EXIT} are PARTIAL, not absent: the --json sink flushes per row so a killed
     run keeps what it got. The SAME argv can succeed on the next run - what it
     depends on lives outside the command line.
  {USAGE_EXIT}  the command line itself is wrong and no run was attempted. Two sources,
     one number: argparse's own parsing (unknown flag, missing required,
     type=/choices=), and every argument-SHAPE validation this module makes -
     --replays 0, --identity-replays 0, --rubric with no LABEL=, --rubric
     a=git:HEAD, two --rubric values sharing one LABEL, a --rubric derive: spec
     whose base is not a git: spec (RB-P17 - which is also how a derive OF a
     derive is refused, so the load order is acyclic rather than checked) -
     each of them reported through parser.error before any file is opened. A
     derive: whose rule id the manifest does not have is NOT here: that needs
     the manifest read, so it is a {REFUSAL_EXIT}. Malformed ON ITS FACE means
     it can never work on any machine: nothing ran, nothing was written, and
     re-running the same argv is guaranteed to fail again, so a human edits the
     command.
     shape rules (exact set): --identity-replays --replays --rubric
     That roster is checked against the CODE - every parser.error reachable
     above main's try and the flags its messages name - and every flag on it is
     field-measured to {USAGE_EXIT} from a real shell, so it cannot drift from what this
     tool does. A rule that needs the WORLD is not on it and is a {REFUSAL_EXIT}:
     --rubric a=<a path that is not there> is the one to keep in mind, because
     the flag is on the roster and that case still is not.
     CHANGED IN RB-P32, and a CI job that branches on these sees it: the four
     malformed --rubric shapes used to report {REFUSAL_EXIT}, the status that also means
     "a measurement died halfway and its artifacts are partial". A fifth case
     followed it in K4B - two --rubric values sharing a LABEL, which collide on
     every machine and were nonetheless refused from inside the run. Measured
     before and after in docs/eval-data/2026-08-13-rbp32-argument-validation-*.md
     and docs/eval-data/2026-08-13-k4b-c2-duplicate-rubric-label.md.
     RB-P17 adds the derive: shapes above. 3 cases change number, measured in
     docs/eval-data/2026-08-14-rbp17-provenance-resolution.md: a derive of a
     derive moves 1 -> 2 (it is now wrong on its face, not a path that is not
     there), and the two runs that use the form at all move 1 -> 3 because
     before it there was no form and the argv could not run.
  {GUARD_VIOLATION_EXIT}  measured, WITH guard-2 violations - every artifact is still written,
     and the GUARD section names each violating (point, cell)
  {ARTIFACT_WRITE_EXIT}  measured, but an artifact could not be written (the --summary file).
     The table is still printed - unless the READER of stdout had already gone,
     in which case it went nowhere and nobody was owed it (a stdout that FAILED
     is {RENDER_FAILURE_EXIT}, below, never this). Outranks {GUARD_VIOLATION_EXIT};
     --violations-exit-zero does not suppress it.
  {RENDER_FAILURE_EXIT}  measured, but THE REPORT COULD NOT BE RENDERED: the write of
     the table to stdout failed for a reason that is NOT the reader going away -
     fd 1 read-only (EBADF), fd 1 closed before the process started, a full
     device, or a stdout whose CODEC cannot represent the table
     (PYTHONIOENCODING=latin-1 or =ascii, where the GUARD section's U+2014 raises
     UnicodeEncodeError). The measurement is COMPLETE and every file that could
     be written is on disk, BYTE-IDENTICAL to what the same argv leaves with a
     live stdout; read those, not this run's log, because the table is not in it.
     The reason is on stderr and is ASCII, so it arrives as written on a
     stderr wrapped in the codec that just failed - stderr's own error handler
     is backslashreplace, so the status would survive a non-ASCII byte there
     but the sentence would not. Outranks
     {ARTIFACT_WRITE_EXIT}; --violations-exit-zero does not suppress it.
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
handled by class, not by evidence. fd 1 pointing at a DIRECTORY is outside the
range in the other direction: CPython dies in init_sys_streams before main
exists and the shell reads 1, so nothing here chose that number either.
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
        help=(
            "repeatable; SPEC is a path, git:<ref>:<path>, or "
            "derive:<manifest-path>:<rule-id>:git:<ref>:<path>"
        ),
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
    # EVERY ARGUMENT-SHAPE VALIDATION THIS MODULE MAKES, IN ONE PLACE, ABOVE THE `try`
    # (RB-P32). What belongs here is a rule that can be decided from the argv alone —
    # no path resolved, no file opened, no `git` run. Those exit through `parser.error`,
    # so a command line that is malformed on its face is always `USAGE_EXIT`: it can
    # never work on any machine, nothing ran, nothing was written, and a CI job's only
    # move is to edit the command. A rule that needs the world stays inside the `try`
    # below and is a `REFUSAL_EXIT`, because the same argv works once the world changes
    # and the artifacts of a half-finished run may be on disk.
    #
    # BEFORE RB-P32 the line was not this one: it was whichever function the author had
    # reached for. `--replays 0` was `parser.error` and therefore 2, while `--rubric`
    # with no `LABEL=` raised `PerturbationError` one statement lower and was 1 — the
    # same 1 a run that died on request 40 of 80 with 39 rows on disk reports. Four
    # cases moved from 1 to 2 and the module comment records them.
    if args.replays < 1 or args.identity_replays < 1:
        parser.error("--replays and --identity-replays must be >= 1")
    for spec in args.rubric:
        problem = rubric_arg_shape_problem(spec)
        if problem is not None:
            parser.error(problem)
    collision = rubric_label_collision_problem(args.rubric)
    if collision is not None:
        parser.error(collision)

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
                f"{args.summary}: {e}. The measurement itself went to stdout IF STDOUT "
                "TOOK IT, which this line cannot promise: a stdout that failed is "
                f"reported on its own line below and the status becomes "
                f"{RENDER_FAILURE_EXIT}, and a stdout whose reader was already gone is "
                "not reported at all - the table went nowhere and nobody was waiting "
                "for it. The JSONL rows, if --json was passed, are on disk either way.",
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
        except (OSError, UnicodeEncodeError) as e:
            # RB-P31, and the line K4B had to draw again because the first one was one
            # class too narrow. The write failed and the reader was NOT gone: fd 1 is
            # read-only (EBADF), or the device is full (ENOSPC), or the fd is otherwise
            # unusable — or stdout's CODEC cannot represent the table
            # (`PYTHONIOENCODING=latin-1` or `=ascii`, where the GUARD section's U+2014
            # and U+00A7 raise `UnicodeEncodeError`). stderr is live in every measured
            # cell of this class, so this is a report that could not be RENDERED, not a
            # reader that walked away — the difference the two arms exist to keep apart.
            # The run measured, so it does not report REFUSAL_EXIT; the report is gone,
            # so it does not report the earned status either. It reports
            # RENDER_FAILURE_EXIT, and says why on stderr.
            #
            # WHERE THE LINE IS NOW, AND WHY IT IS NOT `except Exception`. The two
            # classes here are the two things about stdout that THE CALLER OWNS and this
            # module cannot fix: the descriptor (`OSError`) and the codec that
            # descriptor was wrapped in (`UnicodeEncodeError`). The shell chose fd 1; the
            # environment and the locale chose the encoding; neither is editable from
            # inside this file, and on both the measurement is complete and only the
            # delivery is lost. Everything else a write can raise is still a bug in this
            # module and still propagates with its traceback — a `RuntimeError`, a
            # `TypeError`, an `AttributeError`, and any `ValueError` that is not a
            # `UnicodeEncodeError` (`I/O operation on closed file` is the realistic one,
            # and it is reachable only from an in-process caller who closed
            # `sys.stdout`: a shell cannot hand a fresh process a stdout that is closed
            # at the Python-object level — `1>&-` gives `sys.stdout is None`, which is
            # the branch above). Pinned on that side by
            # `test_a_non_oserror_at_the_table_write_is_not_downgraded`, which raises a
            # `RuntimeError` from the write, and by
            # `test_a_non_unicode_valueerror_at_the_table_write_is_not_downgraded`,
            # which raises a bare `ValueError` — the sibling class of the one now
            # caught, so the widening is pinned exactly where it stops.
            #
            # WHAT THIS DOES NOT REACH: an encoding failure on STDERR. Every arm here
            # reports on stderr, so the messages this module writes there are ASCII on
            # purpose (below); a `BantamError` whose own message is not, on a stderr
            # that cannot encode it, still leaves by traceback with the same number the
            # refusal would have had. Measured in
            # docs/eval-data/2026-08-13-k4b-c1-stdout-encoding-matrix.md.
            render_failure = str(e)
            sys.stdout = _LostStdout(e)
    if render_failure is not None:
        # ASCII ONLY, and the reason is NOT the one it looks like (K4B, and this is a
        # claim K4B made, measured, and had to correct). One of the failures this line
        # reports is stdout's CODEC refusing the table, and stderr is wrapped in the SAME
        # codec — so the obvious story is that an em dash here would fail to encode and
        # turn a reported 5 back into an unreported traceback. IT WOULD NOT: CPython
        # gives `sys.stderr` the `backslashreplace` error handler and keeps it there even
        # under `PYTHONIOENCODING=ascii:strict` (measured 2026-08-13, both codecs), so a
        # non-ASCII character here is ESCAPED, never raised. The status survives.
        # What does not survive is the SENTENCE: it arrives as `COMPLETE — the`,
        # i.e. mangled in the one report whose whole job is to tell a reader where the
        # measurement went. So this is a legibility rule, not a survival one, and it is
        # pinned that way — the encoding nodes compare the delivered text against this
        # literal rather than merely checking that the bytes are ASCII, because
        # `backslashreplace` output IS ASCII and would pass that check.
        print(
            f"error: measured, but the report could not be rendered on stdout: "
            f"{render_failure}. The measurement is COMPLETE: the JSONL rows, if --json "
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
