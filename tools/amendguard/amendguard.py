"""Enforce the record-vs-pointer rule over an amend-only document set.

THE RULE IS IN `docs/record-vs-pointer.md`. THIS IS THE MECHANISM. They landed in one
commit, which is the whole point: a rule without a checker is another intention for the
next pin drift to step on.

  RECORD   a number, a verdict, a table, a verbatim block, a claim. AMEND ONLY. A record
           is a statement about a moment that has passed; rewriting it in place rewrites
           what was said, not what is true. Corrections are dated amendments appended at
           the end.

  POINTER  a statement about WHERE something is. It can become false without anyone
           lying, so it is CORRECTABLE IN PLACE — in its own commit, touching nothing
           else, with the correction stated in the body. The classes are a CLOSED LIST
           (`POINTER_CLASSES` below, four of them, carried as data).

  CO-MOVING COUNT
           a figure whose correct value is a function of the body of the artifact that
           carries it, AT THE SAME COMMIT. Amend-versus-edit is the wrong question for
           it, because it was never a claim about the past. It carries a machine-readable
           derivation marker and must equal that derivation recomputed over the committed
           body at every commit.

  CROSS-ARTIFACT CO-MOVING COUNT
           a count whose derivation lives OUTSIDE the document — a pytest total, a ruff
           result. NOT covered by the marker and deliberately not covered: there is no
           commit at which the number and its derivation are simultaneously true (932 at
           `5458059`, 940 at `3f52a86`, both correct), so "equal to its derivation
           recomputed over the committed body at this commit" has no referent. It falls
           back to RECORD plus a PROVENANCE STAMP of (value, commit, command). The stamp
           enforces FALSIFIABILITY, NOT CORRECTNESS: this checker never learns whether
           932 is right, only that a reader was handed the commit and the command needed
           to find out. THAT GAP IS OPEN AND IS NOT CLOSED HERE.

TWO GUARDS, AND EACH IS MACHINE-CHECKABLE RATHER THAN ASPIRATIONAL.

  1. THE CLOSED LIST MAKES `classify` TOTAL. Every changed hunk lands in exactly one
     branch and the default branch is `DEFAULT_KIND`, which is `record`. A construct
     nobody thought about is therefore amend-only, which is the safe direction. There is
     no "unclassified" output, so the checker cannot be silent about something it did not
     understand — it says `record` and blocks.
  2. `isolation` MAKES A LIE VISIBLE IN `git log --numstat`. A pointer fix must be its own
     commit touching nothing else. A commit that declares itself a pointer fix and moves
     thirty lines reads `isolation=mixed`, and the verdict is POINTER-NOT-ISOLATED. The
     numstat is the evidence; it is not this program's own word for it.

N-12, AND WHY EVERY ASSERTION HERE IS ON A FIELD AND NEVER ON PROSE. A selfcheck filed on
2026-08-19 reddened when a `void_reason` STRING branch was reverted (2 RED) and stayed
GREEN AT 0 RED when the ternary that actually ASSIGNS the classification in the live loop
was reverted. The claim named the classifier; the covered line was the formatter. This
program has the identical exposure — `classify` is a classifier and the `#` note lines are
a formatter — so:

    A MUTATION COUNTS AS PINNING A BRANCH ONLY IF IT MOVES A MACHINE-READABLE VERDICT
    FIELD. A MUTATION THAT MOVES ONLY A HUMAN-READABLE MESSAGE IS RECORDED AS
    FORMATTER-ONLY AND THE BRANCH STAYS UNPINNED.

Machine-readable output is exactly the lines beginning `VERDICT ` and `SUMMARY `. Every
other line begins `#` or is a heading, and nothing may assert on it. `MUT-NOTE-PROSE` in
`MUTATIONS` exists to demonstrate that this works: it changes a sentence, changes no
field, and is reported FORMATTER-ONLY with its branch left UNPINNED. It is not deleted to
make the coverage number look better (RB-P48).

THE TAUTOLOGY TEST, PASSED BEFORE THIS WAS TRUSTED (RB-P47). A cross-check between two
transcriptions of one rule is not a cross-check. Name an input on which `classify` and the
ledger DISAGREE: a `file:line` pin INSIDE A FENCED VERBATIM BLOCK. A pointer by syntax; a
record by context, because a verbatim block is a record class and its contents are quoted,
not cited. That input exists, the two do disagree on it, and it is fixture case
`VERBATIM-PIN`, which must come back RECORD-EDITED.

UNMEASURED IS A VERDICT (RB-P51). A ledger whose patterns matched no changed path exits 3
and prints `unmeasured=1`. It does not exit 0 and it does not print a pass.

RB-P49-SAFE BY CONSTRUCTION. Both subcommands are required and `check` has three required
positionals, so a bare invocation exits 2 from argparse. There is no `repo_root`
defaulting to `'.'`, no implicit write, and no path on which this program overwrites a
committed artifact and exits 0. `--out` is the only write and it is explicit.

CALIBRATE BEFORE YOU BELIEVE IT. `calibration.json` is not a measurement — it is the
expected verdict for every commit of a SYNTHETIC repository this program builds itself,
including one commit that MUST come back red (`RECORD-EDITED`, a number rewritten in
place) and one that MUST come back green (`POINTER-P3-SOLE`, a `file:line` pin corrected
alone), plus the pair Amendment 1 demanded: `BARE-GATE` red and `STAMPED-GATE` green. If
any of them flips, nothing this program says about any real commit may be believed.

    python tools/amendguard/amendguard.py calibrate
    python tools/amendguard/amendguard.py check . 5845698..HEAD tools/amendguard/ledger.json
    python tools/amendguard/amendguard.py check . 5845698..HEAD tools/amendguard/ledger.json --out /tmp/r.md

NOTE ON THE INVOCATION. The plan's §4.3 wrote this as three bare positionals with no verb.
A verb was added because `calibrate` needs an entry point that takes no repository at all,
and folding it into the positional form would have meant either a fourth positional nobody
uses or a flag that makes the positionals conditional — and conditional positionals are how
a program acquires a default write branch. The three positionals of `check` are exactly the
three the plan specified.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# --------------------------------------------------------------------------------------
# THE CLOSED LIST. Four classes, carried as DATA, in priority order. Widening it is a
# commit that edits this tuple, which is visible in a diff and reviewable as such. An
# unlisted construct does not get a branch here — it falls through to DEFAULT_KIND.
# --------------------------------------------------------------------------------------
POINTER_CLASSES: tuple[tuple[str, str, str], ...] = (
    ("P1", r"\[[^\]\n]*\]\([^)\n]*\)", "hyperlink or in-document anchor"),
    ("P3", r"§\d+(?:\.\d+)*:\d+(?:-\d+)?", "file:line pin, section form (§10.2:718)"),
    ("P3", r"`:\d+(?:-\d+)?`", "file:line pin, bare-backtick form (`:1288`)"),
    ("P3", r"[A-Za-z0-9_./-]+\.[A-Za-z0-9]+:\d+(?:-\d+)?", "file:line pin, path form"),
    ("P2", r"§\s?\d+(?:\.\d+)*", "section citation (bar §3.2)"),
    ("P4", r"\*\(filled\)\*|\bTODO\b|\bpending\b|\bHEAD is [0-9a-f]{7,40}\b", "stale-state marker"),
)

# THE SAFE DIRECTION, ON ONE LINE, SO A MUTATION CAN REACH IT. Everything the closed list
# did not match is a record and a record is amend-only.
DEFAULT_KIND = "record"

# A gate expectation is a CROSS-ARTIFACT co-moving count: its derivation is a run, not a
# blob, so the marker cannot reach it (see the module docstring) and a provenance stamp is
# required instead. These patterns are data for the same reason the pointer classes are.
GATE_EXPECTATION_PATTERNS: tuple[str, ...] = (
    r"\b\d+\s+passed\b",
    r"\b\d+\s+failed\b",
    r"\b\d+\s+xfailed\b",
    r"\b\d+\s+xpassed\b",
    r"\bAll checks passed\b",
)

MARKER_RE = re.compile(r"^\s*<!--\s*co-moving-count:\s*(\S+)\s*=\s*count\((.*)\)\s*-->\s*$")
STAMP_RE = re.compile(r"<!--\s*provenance:(.*?)-->")
STAMP_REQUIRED_KEYS = ("value", "commit", "command")
STAMP_WINDOW = 8  # lines above a gate expectation that a stamp may sit in

FENCE_RE = re.compile(r"^\s*(?:```|~~~)")

WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen",
    18: "eighteen", 19: "nineteen", 20: "twenty",
}

OK = "OK"
RECORD_EDITED = "RECORD-EDITED"
POINTER_NOT_ISOLATED = "POINTER-NOT-ISOLATED"
COUNT_STALE = "COUNT-STALE"
STAMP_MISSING = "STAMP-MISSING"
BROKEN = "BROKEN"

# Severity order for collapsing a path's hunks into one `classify` field, worst first.
# `amendment` sits with `insert`: both add text and destroy none, and neither is a record
# edit. It is listed BEFORE `insert` only so a mixed commit reports the in-place shape,
# which is the one a reviewer wants named.
SEVERITY = ("record", "co-moving-count", "pointer", "amendment", "insert", "append", "new-file", "deleted")

_MASK_RE = re.compile(
    "|".join(f"(?P<g{i}>{pat})" for i, (_c, pat, _d) in enumerate(POINTER_CLASSES))
)
_GATE_RE = re.compile("|".join(GATE_EXPECTATION_PATTERNS))


class Broken(RuntimeError):
    """The checker could not read what it was asked to judge. Never swallowed: a check
    that quietly passes on data it cannot see is not the same as one that reports it read
    nothing (RB-P51)."""


# --------------------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------------------
def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def git_ok(repo: Path, *args: str) -> str:
    r = git(repo, *args)
    if r.returncode:
        raise Broken(" ".join(args) + " -> rc=" + str(r.returncode) + " " + r.stderr.strip())
    return r.stdout


def commits_in(repo: Path, rev_range: str) -> list[str]:
    return [ln.strip() for ln in git_ok(repo, "rev-list", "--reverse", rev_range).splitlines() if ln.strip()]


def parents_of(repo: Path, commit: str) -> list[str]:
    line = git_ok(repo, "rev-list", "--parents", "-n", "1", commit).split()
    return line[1:]


def paths_touched(repo: Path, commit: str) -> list[str]:
    out = git_ok(repo, "diff-tree", "-r", "--root", "--no-commit-id", "--no-renames", "--name-only", commit)
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def blob(repo: Path, rev: str, path: str) -> str | None:
    """The file's content at a revision, or None when it does not exist there."""
    r = git(repo, "show", rev + ":" + path)
    if r.returncode:
        return None
    return r.stdout


# --------------------------------------------------------------------------------------
# text analysis
# --------------------------------------------------------------------------------------
def fenced_lines(text: str) -> set[int]:
    """Indices of every line inside a fenced block, fence markers included.

    Included on purpose: a verbatim block is a RECORD class, and its opening line is part
    of the record. This set is what makes `classify` and the closed list disagree on a
    `file:line` pin written inside a fence, which is the RB-P47 input that proves the two
    are not one rule transcribed twice.
    """
    inside: set[int] = set()
    open_fence = False
    for i, line in enumerate(text.splitlines()):
        if FENCE_RE.match(line):
            inside.add(i)
            open_fence = not open_fence
            continue
        if open_fence:
            inside.add(i)
    return inside


def markers_in(text: str) -> list[tuple[int, int, str, str]]:
    """(marker_line, governed_line, name, regex) for every co-moving-count marker.

    The governed line is the next non-blank line after the marker. Nothing else in the
    document is governed, so an unmarked number stays a record and this checker does
    nothing about it at all — which is the conservative default the rule names.
    """
    out = []
    lines = text.splitlines()
    fenced = fenced_lines(text)
    for i, line in enumerate(lines):
        # A MARKER INSIDE A VERBATIM BLOCK IS QUOTED, NOT DECLARED — the same reason a
        # `file:line` pin inside a fence is a record. Found by running this program over
        # its own design document, which illustrates the marker in a fenced example and
        # was consequently reported COUNT-STALE against a body that never claimed the
        # count. Fixture case MARKER-QUOTED, mutation MUT-MARKER-FENCE.
        if i in fenced:
            continue
        m = MARKER_RE.match(line)
        if not m:
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines):
            raise Broken("co-moving-count marker at line " + str(i + 1) + " governs nothing")
        out.append((i, j, m.group(1), m.group(2)))
    return out


def derivation_of(text: str) -> tuple[str, list[str]]:
    """`ok` / `stale` / `absent`, plus one note per marker that drifted."""
    marks = markers_in(text)
    if not marks:
        return "absent", []
    lines = text.splitlines()
    notes = []
    for _mi, gi, name, pattern in marks:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise Broken("co-moving-count " + name + " carries an uncompilable regex: " + str(exc)) from exc
        n = sum(1 for ln in lines if rx.search(ln))
        governed = lines[gi]
        digits = re.search(r"\b" + str(n) + r"\b", governed) is not None
        word = WORDS.get(n) is not None and WORDS.get(n, "\x00") in governed.lower()
        if not (digits or word):
            notes.append(
                name + ": the body recomputes to " + str(n)
                + " and the governed line does not say so -> " + governed.strip()
            )
    return ("ok" if not notes else "stale"), notes


def mask_pointers_indexed(line: str) -> tuple[str, list[tuple[int, str]]]:
    """Replace every closed-list construct with a per-class sentinel; report ENTRY INDICES.

    Two lines whose masks are equal differ ONLY inside pointer constructs. Two lines whose
    masks differ changed something else as well, and something else is a record.

    The index — the position in `POINTER_CLASSES` — is what is reported, not the class id,
    because THE TWO ARE NOT THE SAME COUNT. Six entries carry four distinct ids: P3 alone
    has three sub-forms. A guard that counts ids cannot tell a covered sub-form from an
    uncovered one, and this is the only function that knows which entry actually matched.
    """
    found: list[tuple[int, str]] = []

    def sub(m: re.Match) -> str:
        idx = int(m.lastgroup[1:])
        found.append((idx, m.group(0)))
        return "\x00" + POINTER_CLASSES[idx][0] + "\x00"

    return _MASK_RE.sub(sub, line), found


def mask_pointers(line: str) -> tuple[str, list[tuple[str, str]]]:
    """`mask_pointers_indexed` with the entry index resolved to its class id.

    One implementation, two views. A second masker written beside this one would be a
    transcription of the same rule, and a cross-check between two transcriptions is a
    tautology (RB-P47).
    """
    masked, found = mask_pointers_indexed(line)
    return masked, [(POINTER_CLASSES[i][0], text) for i, text in found]


def pointer_entries_changed(old: list[str], new: list[str]) -> set[int] | None:
    """The CLOSED-LIST ENTRY INDICES a change lands inside, or None when it reaches outside.

    This is `pointer_only_change`'s decision, one resolution finer. It is exported because
    coverage of the closed list has to be counted per ENTRY: the calibration's `classify`
    field says `pointer:P3` for three different sub-forms, so nothing downstream of a
    verdict line can tell which of the three a fixture case exercised.
    """
    if len(old) != len(new) or not old:
        return None
    changed: set[int] = set()
    for o, n in zip(old, new):
        if o == n:
            continue
        mo, co = mask_pointers_indexed(o)
        mn, cn = mask_pointers_indexed(n)
        if mo != mn:
            return None
        for (i1, t1), (_i2, t2) in zip(co, cn):
            if t1 != t2:
                changed.add(i1)
    if not changed:
        return None
    return changed


def pointer_only_change(old: list[str], new: list[str]) -> str | None:
    """`pointer:Pn` when every difference lies inside closed-list constructs, else None."""
    changed = pointer_entries_changed(old, new)
    if changed is None:
        return None
    return "pointer:" + "+".join(sorted({POINTER_CLASSES[i][0] for i in changed}))


def destroys_nothing(old: list[str], new: list[str]) -> bool:
    """True when the new text contains the old text ENTIRELY, with characters only added.

    WHY A CLASS EXISTS FOR THIS. The rule this file enforces is `docs/record-vs-pointer.md`'s,
    and the rule's own reasoning is that AN ADDITION DESTROYS NO RECORD. `classify_hunks`
    already honours that for a whole line (`insert`, `append`) and did not honour it for
    anything smaller — so a register row that gained a closure inside its last table cell, or
    a heading that gained `~~` around its number, arrived as a line-level `replace` and was
    called `record`, which is a rewrite. Those are this repository's two most common ways of
    closing an item.

    WHAT WAS REGISTERED AND WHAT WAS MEASURED — and they are not the same answer, which is why
    this predicate is character-level rather than the prefix test the ledger proposed.
    `tools/amendguard/ledger.json` registered candidate (1): "a `replace` hunk whose new line
    has the old line as a strict PREFIX". MEASURED 2026-09-11 over
    `6e506ca..df48b68` (40 commits, branch `feat/job46-register-and-agent-stack`) with the
    register files in `amend_only`: SEVEN hunks come back RECORD-EDITED and the prefix test
    greens ZERO of them. Not one closure on that branch was written at the end of its line —
    a table row ends in `|`, and a struck row `| 12 |` becomes `| ~~12~~ |` in the middle. The
    registered design would have shipped and changed nothing.

    The character-level test greens FIVE of the seven and leaves TWO red, and those two really
    did destroy text: `181744a86` replaced three lines of `docs/roadmap-agent-stack.md` with
    one (6 characters destroyed) and `a7f90073d` removed two backslashes from a
    `docs/porting.md` cell. Both are findings, not false positives.

    THE COMPARISON IS OVER THE WHOLE HUNK, joined by newlines, not line by line. A closure
    that both extends a row AND adds a line below it is one amendment; testing each line
    separately would call the pair a rewrite because the line counts differ.

    WHAT THIS IS NOT. It is not "the diff looks additive". `difflib` over CHARACTERS reports
    `delete` and `replace` opcodes for anything removed, and one such opcode is enough to
    refuse. Deleting a single character — the `_rows_from_runs`-style off-by-one this
    repository keeps finding — is a `delete` opcode and stays a record edit.
    """
    import difflib

    if not old or not new:
        return False
    a = "\n".join(old)
    b = "\n".join(new)
    if a == b or len(b) <= len(a):
        return False
    for tag, _i1, _i2, _j1, _j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag in ("delete", "replace"):
            return False
    return True


@dataclass
class Hunk:
    kind: str
    detail: str


def classify_hunks(old_text: str, new_text: str) -> list[Hunk]:
    """One classification per changed region. Total by construction."""
    import difflib

    old = old_text.splitlines()
    new = new_text.splitlines()
    old_fence = fenced_lines(old_text)
    new_fence = fenced_lines(new_text)
    governed = {gi for _mi, gi, _n, _p in markers_in(new_text)}
    hunks: list[Hunk] = []
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            where = "at EOF" if i1 >= len(old) else "at line " + str(j1 + 1)
            # An insertion destroys no record. Appending at the end is how an amendment is
            # written; an insertion in the body shifts every line number below it, which
            # is the hazard the `file:line` pin convention exists for, so it is named
            # separately rather than folded into `append`.
            hunks.append(Hunk("append" if i1 >= len(old) else "insert", str(j2 - j1) + " lines " + where))
            continue
        if tag == "delete":
            hunks.append(Hunk(DEFAULT_KIND, str(i2 - i1) + " lines removed at line " + str(i1 + 1)))
            continue
        # tag == "replace": committed text was rewritten. This is the branch the rule is
        # about, and the order below is the rule.
        if any(i in old_fence for i in range(i1, i2)) or any(j in new_fence for j in range(j1, j2)):
            hunks.append(Hunk(DEFAULT_KIND, "inside a fenced verbatim block at line " + str(j1 + 1)))
            continue
        if any(j in governed for j in range(j1, j2)):
            hunks.append(Hunk("co-moving-count", "a marked count at line " + str(j1 + 1)))
            continue
        pointer = pointer_only_change(old[i1:i2], new[j1:j2])
        if pointer is not None:
            hunks.append(Hunk(pointer, "corrected in place at line " + str(j1 + 1)))
            continue
        if destroys_nothing(old[i1:i2], new[j1:j2]):
            hunks.append(Hunk("amendment", "extended in place at line " + str(j1 + 1)))
            continue
        # THE CLOSED LIST IS CLOSED HERE. Nothing above matched, so this is a record and a
        # record is amend-only. There is no "unclassified" branch to fall into.
        hunks.append(Hunk(DEFAULT_KIND, "rewritten in place at line " + str(j1 + 1)))
    return hunks


def unstamped_gate_lines(old_text: str, new_text: str) -> list[str]:
    """Gate expectations this commit ADDED or CHANGED that carry no provenance stamp."""
    import difflib

    old = old_text.splitlines()
    new = new_text.splitlines()
    governed = {gi for _mi, gi, _n, _p in markers_in(new_text)}
    touched: list[int] = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            touched.extend(range(j1, j2))
    bad = []
    for j in touched:
        line = new[j]
        if not _GATE_RE.search(line):
            continue
        if j in governed:
            continue
        if _stamped(new, j):
            continue
        bad.append("line " + str(j + 1) + ": " + line.strip())
    return bad


def _stamped(lines: list[str], j: int) -> bool:
    for k in range(max(0, j - STAMP_WINDOW), j + 1):
        m = STAMP_RE.search(lines[k])
        if m and all(key + "=" in m.group(1) for key in STAMP_REQUIRED_KEYS):
            return True
    return False


# --------------------------------------------------------------------------------------
# the sweep
# --------------------------------------------------------------------------------------
@dataclass
class Row:
    commit: str
    path: str
    classify: str
    isolation: str
    derivation: str
    verdict: str
    notes: list[str]

    def line(self) -> str:
        return (
            "VERDICT commit=" + self.commit[:9]
            + " path=" + self.path
            + " classify=" + self.classify
            + " isolation=" + self.isolation
            + " derivation=" + self.derivation
            + " verdict=" + self.verdict
        )


def severity_key(kind: str) -> int:
    base = kind.split(":")[0]
    return SEVERITY.index(base) if base in SEVERITY else 0


def load_ledger(p: Path) -> list[str]:
    raw = json.loads(p.read_text(encoding="utf-8"))
    pats = raw.get("amend_only")
    if not pats or not all(isinstance(x, str) and x.strip() for x in pats):
        raise ValueError(str(p) + ": `amend_only` must list at least one path pattern")
    return list(pats)


def in_ledger(path: str, patterns: list[str]) -> bool:
    pp = PurePosixPath(path)
    return any(pp.match(pat) for pat in patterns)


def rows_for_commit(repo: Path, commit: str, patterns: list[str]) -> tuple[list[Row], list[str]]:
    """Every (commit, path) row this commit produces, plus notes about what was skipped."""
    parents = parents_of(repo, commit)
    if len(parents) > 1:
        return [], [
            "merge commit " + commit[:9] + " with " + str(len(parents)) + " parents — no row "
            "emitted. A combined diff is not a hunk this rule can read, and saying so is the "
            "point: a check that is silent about what it could not see is RB-P51's defect."
        ]
    parent = parents[0] if parents else None
    touched = paths_touched(repo, commit)
    subject = git_ok(repo, "log", "-1", "--format=%s", commit).strip()
    rows: list[Row] = []
    for path in sorted(touched):
        if not in_ledger(path, patterns):
            continue
        pre = blob(repo, parent, path) if parent else None
        post = blob(repo, commit, path)
        try:
            if post is None:
                rows.append(Row(commit, path, "deleted", "mixed", "absent", RECORD_EDITED,
                                ["subject: " + subject, "the whole record was removed"]))
                continue
            hunks = classify_hunks(pre or "", post)
            derivation, dnotes = derivation_of(post)
            gate_notes = unstamped_gate_lines(pre or "", post)
            if pre is None:
                classify = "new-file"
            elif not hunks:
                classify = "append"
            else:
                classify = max((h.kind for h in hunks), key=lambda k: -severity_key(k))
            pointer_only = bool(hunks) and all(h.kind.startswith("pointer:") for h in hunks)
            isolation = "sole" if (pointer_only and len(touched) == 1) else "mixed"
            verdict = _verdict(classify, isolation, derivation, gate_notes)
            notes = ["subject: " + subject]
            notes += [h.kind + " — " + h.detail for h in hunks]
            notes += dnotes
            notes += ["unstamped gate expectation, " + g for g in gate_notes]
            rows.append(Row(commit, path, classify, isolation, derivation, verdict, notes))
        except Broken as exc:
            rows.append(Row(commit, path, "unreadable", "mixed", "absent", BROKEN,
                            ["subject: " + subject, str(exc)]))
    return rows, []


def _verdict(classify: str, isolation: str, derivation: str, gate_notes: list[str]) -> str:
    """The gate, in precedence order. Each fixture case triggers exactly one of these, so
    no branch is hidden behind another's precedence."""
    if derivation == "stale":
        return COUNT_STALE
    if gate_notes:
        return STAMP_MISSING
    if classify == DEFAULT_KIND or classify == "deleted":
        return RECORD_EDITED
    if classify.startswith("pointer:") and isolation != "sole":
        return POINTER_NOT_ISOLATED
    return OK


def check_range(repo: Path, rev_range: str, patterns: list[str]) -> tuple[list[Row], list[str]]:
    rows: list[Row] = []
    notes: list[str] = []
    for commit in commits_in(repo, rev_range):
        r, n = rows_for_commit(repo, commit, patterns)
        rows.extend(r)
        notes.extend(n)
    return rows, notes


def render(rows: list[Row], notes: list[str], repo: Path, rev_range: str, patterns: list[str]) -> tuple[str, int]:
    red = [r for r in rows if r.verdict != OK]
    broken = [r for r in rows if r.verdict == BROKEN]
    unmeasured = 1 if not rows else 0
    lines = [
        "# amendguard — the record-vs-pointer rule over " + rev_range,
        "",
        "repo: " + str(repo),
        "amend-only patterns: " + ", ".join(patterns),
        "",
        "Machine-readable output is exactly the `VERDICT` and `SUMMARY` lines. Everything",
        "else is prose and no assertion may rest on it (N-12: the claim named the",
        "classifier and the covered line was the formatter).",
        "",
    ]
    for r in rows:
        lines.append(r.line())
        for n in r.notes:
            lines.append("#   " + n)
    for n in notes:
        lines.append("# " + n)
    if unmeasured:
        lines += [
            "",
            "# UNMEASURED. The ledger's amend-only patterns matched no path changed in this",
            "# range. That is not a pass and this program does not report it as one (RB-P51).",
        ]
    lines += [
        "",
        "SUMMARY rows=" + str(len(rows)) + " ok=" + str(len(rows) - len(red))
        + " red=" + str(len(red)) + " broken=" + str(len(broken))
        + " merges=" + str(len(notes)) + " unmeasured=" + str(unmeasured),
    ]
    if unmeasured:
        return "\n".join(lines) + "\n", 3
    return "\n".join(lines) + "\n", (1 if red else 0)


# --------------------------------------------------------------------------------------
# THE SYNTHETIC FIXTURE. Every expectation this program makes about itself is an
# expectation about THIS repository, built here, from these bytes — never about the
# repository it is run on (RB-P14 Gate 2; RB-P28: the suite is not evidence).
# --------------------------------------------------------------------------------------
DOC_A = """# Doc A

A measurement: the floor is 0.001472.

See [Eval](eval.md#cross-model-results) and bar §3.2.

The consumer sits at field-measurement.py:1288.

The same consumer, cited by section: §10.2:718.

The same consumer, cited bare: `:1288`.

Status: TODO
"""

DOC_B = """# Doc B

Nothing filed yet.
"""

FIXTURE_COMMITS: tuple[dict, ...] = (
    {"label": "BASE", "ops": [{"path": "doc-a.md", "write": DOC_A},
                              {"path": "doc-b.md", "write": DOC_B}]},
    {"label": "APPEND-OK", "ops": [{"path": "doc-a.md", "append":
        "\n## Amendment 1 — 2026-01-02\n\nThe floor above is superseded; the corrected value is 0.002000.\n"}]},
    {"label": "RECORD-EDITED", "ops": [{"path": "doc-a.md", "sub": ["0.001472", "0.002000"]}]},
    {"label": "POINTER-P3-SOLE", "ops": [{"path": "doc-a.md",
        "sub": ["field-measurement.py:1288", "field-measurement.py:1567"]}]},
    {"label": "POINTER-P3-MIXED", "ops": [
        {"path": "doc-a.md", "sub": ["field-measurement.py:1567", "field-measurement.py:1570"]},
        {"path": "doc-c.md", "write": "# Doc C\n\nA second file in the same commit.\n"}]},
    {"label": "POINTER-P1", "ops": [{"path": "doc-a.md",
        "sub": ["(eval.md#cross-model-results)", "(eval.md#cross-model-results-2026)"]}]},
    {"label": "POINTER-P2", "ops": [{"path": "doc-a.md", "sub": ["bar §3.2", "bar §3.3"]}]},
    {"label": "POINTER-P4", "ops": [{"path": "doc-a.md", "sub": ["Status: TODO", "Status: pending"]}]},
    # THE OTHER TWO P3 SUB-FORMS. `classify` reports the CLASS, so these two read
    # `pointer:P3` exactly as the path form does — which is precisely why a coverage guard
    # counting classes could not see that neither had a case. One case per closed-list
    # ENTRY; `test_every_closed_list_entry_has_a_fixture_case` is what makes that hold.
    {"label": "POINTER-P3-SECTION", "ops": [{"path": "doc-a.md",
        "sub": ["§10.2:718", "§10.2:742"]}]},
    {"label": "POINTER-P3-BACKTICK", "ops": [{"path": "doc-a.md",
        "sub": ["`:1288`", "`:1600`"]}]},
    {"label": "ADD-FENCE", "ops": [{"path": "doc-a.md", "append":
        "\n## Transcript\n\n```\ngrep -n floor docs/x.md:403\n```\n"}]},
    {"label": "VERBATIM-PIN", "ops": [{"path": "doc-a.md", "sub": ["docs/x.md:403", "docs/x.md:404"]}]},
    {"label": "COUNT-INTRODUCED", "ops": [{"path": "doc-b.md", "append":
        "\n<!-- co-moving-count: findings = count(^### F-\\d+$) -->\n**Two findings filed.**\n\n### F-1\n\n### F-2\n"}]},
    {"label": "COUNT-BUMPED", "ops": [{"path": "doc-b.md", "append": "\n### F-3\n"},
                                      {"path": "doc-b.md", "sub": ["**Two findings filed.**", "**Three findings filed.**"]}]},
    {"label": "COUNT-STALE", "ops": [{"path": "doc-b.md", "append": "\n### F-4\n"}]},
    {"label": "COUNT-REPAIRED", "ops": [{"path": "doc-b.md",
        "sub": ["**Three findings filed.**", "**Four findings filed.**"]}]},
    {"label": "BARE-GATE", "ops": [{"path": "doc-a.md", "append":
        "\n## Gates\n\n932 passed, 2 xfailed\n"}]},
    {"label": "STAMPED-GATE", "ops": [{"path": "doc-b.md", "append":
        "\n## Gates\n\n<!-- provenance: value=932 passed, 2 xfailed; commit=5458059;"
        " command=.venv/bin/python -m pytest runtime-py/tests -q -->\n932 passed, 2 xfailed\n"}]},
    # A STAMP THAT IS PRESENT AND INCOMPLETE, in its own file so that no earlier stamp is
    # inside `STAMP_WINDOW` and able to satisfy this line by accident. Invariant 5 makes
    # the `(value, commit, command)` TRIPLE the whole fallback for a cross-artifact
    # co-moving count; before this case `STAMP_REQUIRED_KEYS = ()` passed with flips=0, so
    # the triple was the least-pinned assertion in the program. The code was correct and
    # untested, and under this job's own standard that is a separate verdict.
    {"label": "PARTIAL-STAMP", "ops": [{"path": "doc-d.md", "write":
        "# Doc D\n\n## Gates\n\n"
        "<!-- provenance: value=932 passed, 2 xfailed; commit=5458059 -->\n"
        "932 passed, 2 xfailed\n"}]},
    # A marker SHOWN in a fenced example, in a file that has no live marker at all. If the
    # fence is ignored the derivation recomputes to 0 against a governed line that says
    # eleven, and the whole file reads COUNT-STALE for a count nobody declared.
    {"label": "MARKER-QUOTED", "ops": [{"path": "doc-c.md", "append":
        "\n## How the marker is written\n\n```\n"
        "<!-- co-moving-count: findings = count(^### F-\\d+$) -->\n"
        "**Eleven findings filed.**\n```\n"}]},
    # THE PAIR THE `amendment` CLASS IS CALIBRATED BY, and they differ by one character.
    #
    # A register row here is one LINE — `| 12 | ... |` — so a closure written into its last
    # cell, or a `~~` struck around its number, is a line-level `replace` even though it
    # destroys nothing. `AMEND-IN-PLACE` is that shape and must be GREEN. `AMEND-BUT-DELETES`
    # extends the same line by far more text and removes ONE character while doing it, and
    # must be RED — because the test is "was anything destroyed", never "did it get longer".
    # Without the second row the first would be satisfied by a predicate that only compared
    # lengths.
    {"label": "AMEND-BASE", "ops": [{"path": "doc-e.md", "write":
        "# Doc E\n\n| 12 | the row this document is about | open |\n"}]},
    {"label": "AMEND-IN-PLACE", "ops": [{"path": "doc-e.md", "write":
        "# Doc E\n\n| ~~12~~ | the row this document is about | open — CLOSED 2026-01-01, "
        "nothing above was rewritten |\n"}]},
    {"label": "AMEND-BUT-DELETES", "ops": [{"path": "doc-e.md", "write":
        "# Doc E\n\n| ~~12~~ | the row this document is abut | open — CLOSED 2026-01-01, "
        "nothing above was rewritten. And here is a great deal of additional text, so that "
        "the line is very much longer than it was and a length test would call this an "
        "amendment. One character of the word `about` is gone. |\n"}]},
)

FIXTURE_LEDGER = {"amend_only": ["*.md"]}

FIXTURE_ENV = {
    "GIT_AUTHOR_NAME": "amendguard fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "amendguard fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def build_fixture(dest: Path) -> dict[str, str]:
    """Build the synthetic repository. Returns {label: sha}.

    Every `sub` asserts its anchor is present EXACTLY ONCE before it is applied. A
    `.replace()` that matched nothing looks exactly like an edit that worked, and a
    fixture whose commits silently did not happen calibrates nothing.
    """
    import os

    dest.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(FIXTURE_ENV)

    def g(*args: str) -> None:
        r = subprocess.run(["git", "-C", str(dest), *args], capture_output=True, text=True,
                           env=env, check=False, encoding="utf-8")
        if r.returncode:
            raise Broken("fixture: git " + " ".join(args) + " -> " + r.stderr.strip())

    g("init", "-q")
    g("symbolic-ref", "HEAD", "refs/heads/main")
    labels: dict[str, str] = {}
    for spec in FIXTURE_COMMITS:
        for op in spec["ops"]:
            f = dest / op["path"]
            if "write" in op:
                f.write_text(op["write"], encoding="utf-8")
            elif "append" in op:
                f.write_text(f.read_text(encoding="utf-8") + op["append"], encoding="utf-8")
            else:
                anchor, replacement = op["sub"]
                text = f.read_text(encoding="utf-8")
                n = text.count(anchor)
                if n != 1:
                    raise Broken("fixture " + spec["label"] + ": anchor appears " + str(n)
                                 + "x in " + op["path"] + " — the fixture is stale")
                f.write_text(text.replace(anchor, replacement), encoding="utf-8")
            g("add", "--", op["path"])
        g("commit", "-q", "-m", spec["label"])
        labels[spec["label"]] = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True,
            env=env, check=True, encoding="utf-8").stdout.strip()
    return labels


def fixture_ledger_path(dest: Path) -> Path:
    p = dest.parent / "fixture-ledger.json"
    p.write_text(json.dumps(FIXTURE_LEDGER, indent=2) + "\n", encoding="utf-8")
    return p


# --------------------------------------------------------------------------------------
# THE MUTATION CATALOGUE, KEYED BY DECISION BRANCH AND NOT BY CHECK NAME.
#
# `pins` names the pytest node entitled to pin the branch, exactly as `pinned.py` does:
# "a mutation turned SOMETHING red" is not "this branch is pinned". Coverage is counted
# from the CHECKER'S PRINTED VERDICT FIELDS, never from a grep over this source — RB-P48
# measured a source-side grep under-counting its own defect 5 against 11 of 14.
# --------------------------------------------------------------------------------------
MUTATION_CATALOGUE_MARKER = "MUTATIONS: tuple[dict" + ", ...] = ("

MUTATIONS: tuple[dict, ...] = (
    {"id": "MUT-RECORD-DEFAULT", "expect": "pinned", "branch": "record-default",
     "anchor": 'DEFAULT_KIND = "record"', "replacement": 'DEFAULT_KIND = "pointer:P3"',
     "pins": "test_an_unlisted_construct_falls_through_to_record",
     "why": "the closed list stops being closed: everything unmatched becomes a pointer"},
    {"id": "MUT-P1", "expect": "pinned", "branch": "P1",
     "anchor": r'("P1", r"\[[^\]\n]*\]\([^)\n]*\)"', "replacement": '("P1", r"(?!x)x"',
     "pins": "test_a_hyperlink_corrected_alone_is_a_pointer",
     "why": "P1 leaves the closed list"},
    {"id": "MUT-P2", "expect": "pinned", "branch": "P2",
     "anchor": r'("P2", r"§\s?\d+(?:\.\d+)*"', "replacement": '("P2", r"(?!x)x"',
     "pins": "test_a_section_citation_corrected_alone_is_a_pointer",
     "why": "P2 leaves the closed list"},
    {"id": "MUT-P3", "expect": "pinned", "branch": "P3",
     "anchor": r'("P3", r"[A-Za-z0-9_./-]+\.[A-Za-z0-9]+:\d+(?:-\d+)?"',
     "replacement": '("P3", r"(?!x)x"',
     "pins": "test_a_lone_file_line_pin_correction_is_ok",
     "why": "the path form of the file:line pin leaves the closed list"},
    {"id": "MUT-P4", "expect": "pinned", "branch": "P4",
     "anchor": r'("P4", r"\*\(filled\)\*|\bTODO\b|\bpending\b|\bHEAD is [0-9a-f]{7,40}\b"',
     "replacement": '("P4", r"(?!x)x"',
     "pins": "test_a_stale_state_marker_corrected_alone_is_a_pointer",
     "why": "P4 leaves the closed list"},
    # ONE MUTATION PER SUB-FORM, because the mask is per sub-form and the class id is not
    # the branch. MUT-P3 above deletes the PATH form only; before these two existed either
    # of the other sub-forms could be deleted from the closed list with nothing red.
    {"id": "MUT-P3-SECTION", "expect": "pinned", "branch": "P3-section-form",
     "anchor": r'("P3", r"§\d+(?:\.\d+)*:\d+(?:-\d+)?"',
     "replacement": '("P3", r"(?!x)x"',
     "pins": "test_a_section_form_file_line_pin_correction_is_ok",
     "why": "the section form of the file:line pin leaves the closed list"},
    {"id": "MUT-P3-BACKTICK", "expect": "pinned", "branch": "P3-backtick-form",
     "anchor": r'("P3", r"`:\d+(?:-\d+)?`"',
     "replacement": '("P3", r"(?!x)x"',
     "pins": "test_a_bare_backtick_file_line_pin_correction_is_ok",
     "why": "the bare-backtick form of the file:line pin leaves the closed list"},
    {"id": "MUT-VERBATIM", "expect": "pinned", "branch": "verbatim",
     "anchor": "if any(i in old_fence for i in range(i1, i2)) or any(j in new_fence for j in range(j1, j2)):",
     "replacement": "if False:",
     "pins": "test_a_pin_inside_a_verbatim_block_is_a_record",
     "why": "a fenced verbatim block stops being a record and its pins read as pointers"},
    {"id": "MUT-ISOLATION", "expect": "pinned", "branch": "isolation",
     "anchor": 'isolation = "sole" if (pointer_only and len(touched) == 1) else "mixed"',
     "replacement": 'isolation = "sole"',
     "pins": "test_a_pointer_fix_bundled_with_anything_else_is_pointer_not_isolated",
     "why": "the its-own-commit rule stops being enforced"},
    {"id": "MUT-DERIVATION", "expect": "pinned", "branch": "derivation",
     "anchor": 'return ("ok" if not notes else "stale"), notes',
     "replacement": 'return "ok", notes',
     "pins": "test_a_co_moving_count_that_drifts_is_count_stale",
     "why": "a drifted co-moving count stops being detected"},
    {"id": "MUT-MARKER-FENCE", "expect": "pinned", "branch": "marker-fence",
     "anchor": "        if i in fenced:\n            continue",
     "replacement": "        if False:\n            continue",
     "pins": "test_a_marker_inside_a_verbatim_block_is_quoted_not_declared",
     "why": "an illustrated marker starts governing a body that never claimed its count"},
    {"id": "MUT-STAMP", "expect": "pinned", "branch": "stamp",
     "anchor": "        if _stamped(new, j):\n            continue",
     "replacement": "        if True:\n            continue",
     "pins": "test_a_gate_expectation_without_a_provenance_stamp_is_red",
     "why": "a bare cross-artifact count stops needing its (value, commit, command)"},
    {"id": "MUT-STAMP-KEYS", "expect": "pinned", "branch": "stamp-required-keys",
     "anchor": 'STAMP_REQUIRED_KEYS = ("value", "commit", "command")',
     "replacement": "STAMP_REQUIRED_KEYS = ()",
     "pins": "test_a_gate_expectation_whose_stamp_is_missing_a_key_is_red",
     "why": "any comment saying `provenance:` starts counting as a full stamp"},
    # DECLARED UNPINNED AND KEPT (RB-P48; invariant 6). No fixture case places a stamp
    # further than `STAMP_WINDOW` above the number it governs, so widening the window
    # changes nothing and this branch is NOT covered. Deleting the mutation would close it
    # by hiding it; the honest close is a fixture case whose stamp sits out of range, and
    # that case is not written here. This is also the sweep's control for the `UNPINNED`
    # arm itself, which was unreachable until the baseline path was resolved.
    {"id": "MUT-STAMP-WINDOW", "expect": "unpinned", "branch": "stamp-window",
     "anchor": "STAMP_WINDOW = 8", "replacement": "STAMP_WINDOW = 100000",
     "pins": "(none — no fixture case places a stamp outside the window)",
     "why": "the distance a stamp may sit from its number stops being bounded"},
    {"id": "MUT-AMENDMENT", "expect": "pinned", "branch": "amendment",
     "anchor": 'if destroys_nothing(old[i1:i2], new[j1:j2]):',
     "replacement": 'if False and destroys_nothing(old[i1:i2], new[j1:j2]):',
     "pins": "test_a_record_extended_in_place_without_destroying_anything_is_ok",
     "why": "an in-place extension goes back to reading as a rewrite, which is the state "
            "this branch was added to end"},
    {"id": "MUT-AMENDMENT-LENGTH-ONLY", "expect": "pinned", "branch": "amendment",
     "anchor": 'if tag in ("delete", "replace"):',
     "replacement": 'if tag in ("delete",) and False:',
     "pins": "test_an_in_place_extension_that_destroys_one_character_is_still_red",
     "why": "the predicate stops asking whether anything was destroyed and starts asking "
            "only whether the line got longer — the false positive the second fixture row "
            "exists to catch"},
    {"id": "MUT-APPEND", "expect": "pinned", "branch": "append",
     "anchor": 'Hunk("append" if i1 >= len(old) else "insert"',
     "replacement": 'Hunk("record" if i1 >= len(old) else "insert"',
     "pins": "test_an_appended_amendment_is_ok",
     "why": "appending an amendment starts reading as rewriting a record"},
    # THE DEMONSTRATION, AND IT IS NOT DELETED TO IMPROVE THE COVERAGE NUMBER (RB-P48).
    # This mutation breaks a MESSAGE. Under N-12's rule it pins nothing, and the sweep
    # must say so out loud rather than counting it.
    {"id": "MUT-NOTE-PROSE", "expect": "formatter-only", "branch": "note-prose",
     "anchor": '"rewritten in place at line "', "replacement": '"CLOBBERED IN PLACE at line "',
     "pins": "(none — this branch is prose)",
     "why": "a human-readable note changes and no verdict field moves"},
)


def _fields(text: str) -> list[str]:
    """Exactly the machine-readable lines. Prose is invisible to the sweep, by design."""
    return [ln for ln in text.splitlines() if ln.startswith(("VERDICT ", "SUMMARY "))]


def calibrate(keep: Path | None = None) -> int:
    here = Path(__file__).resolve()
    calibration = here.parent / "calibration.json"
    expectations = json.loads(calibration.read_text(encoding="utf-8"))["expect"]
    # RESOLVED, AND THE SWEEP'S OWN VACUITY DETECTOR DEPENDS ON IT. Every mutant runs
    # through `main()`, which does `args.repo.resolve()`; the baseline below is built
    # in-process from this path as given. On macOS `tempfile.mkdtemp()` returns
    # `/var/folders/…` and resolves to `/private/var/folders/…`, so the rendered `repo:`
    # line differed between baseline and EVERY mutant — which made `r.stdout !=
    # baseline_text` unconditionally true and the `UNPINNED` arm UNREACHABLE. A branch
    # with zero coverage was therefore labelled `FORMATTER-ONLY`, the innocent label,
    # destroying the exact distinction RB-P48 leans on. The detector was itself vacuous.
    tmp = (Path(keep) if keep else Path(tempfile.mkdtemp(prefix="amendguard-cal-"))).resolve()
    fixture = tmp / "repo"
    labels = build_fixture(fixture)
    ledger = fixture_ledger_path(fixture)
    patterns = load_ledger(ledger)

    rows, notes = check_range(fixture, "HEAD", patterns)
    baseline_text, _rc = render(rows, notes, fixture, "HEAD", patterns)
    by_key = {(r.commit, r.path): r for r in rows}

    print("# amendguard calibration — a synthetic repository, " + str(len(FIXTURE_COMMITS))
          + " commits, built by this program")
    print("# fixture: " + str(fixture))
    print()
    flips = []
    for e in expectations:
        sha = labels.get(e["label"])
        if sha is None:
            flips.append(e["label"] + ": no such fixture commit")
            continue
        row = by_key.get((sha, e["path"]))
        if row is None:
            flips.append(e["label"] + "/" + e["path"] + ": no row emitted")
            continue
        got = {"classify": row.classify, "isolation": row.isolation,
               "derivation": row.derivation, "verdict": row.verdict}
        want = {k: e[k] for k in got}
        mark = "ok " if got == want else "FLIP"
        print(mark + " " + e["label"].ljust(18) + " " + e["path"].ljust(10)
              + " expected " + e["verdict"].ljust(21) + " measured " + row.verdict)
        if got != want:
            flips.append(e["label"] + "/" + e["path"] + ": expected " + json.dumps(want)
                         + " measured " + json.dumps(got))
    reds = [e["label"] + "/" + e["path"] for e in expectations if e["verdict"] != OK]
    greens = [e["label"] + "/" + e["path"] for e in expectations if e["verdict"] == OK]
    print()
    print("# must-be-red: " + ", ".join(reds))
    print("# must-be-green: " + ", ".join(greens))

    print()
    print("# mutation sweep — one mutation per DECISION BRANCH, effect measured on the")
    print("# checker's printed VERDICT/SUMMARY fields and on nothing else.")
    print()
    source = here.read_text(encoding="utf-8")
    # THE CATALOGUE QUOTES ITS OWN ANCHORS. Counting over the whole file finds every
    # anchor twice — once in the code it is meant to reach and once in the MUTATIONS
    # literal below — and a mutation applied to both edits the catalogue rather than the
    # classifier. So the source is split at the catalogue and only the half above it is
    # mutated. Measured, not assumed: before this split every branch but one reported
    # STALE at "anchor appears 2x in the source".
    code, marker, catalogue = source.partition(MUTATION_CATALOGUE_MARKER)
    if not marker:
        raise Broken("the mutation-catalogue marker is gone; the sweep cannot bound itself")
    coverage = []
    for mut in MUTATIONS:
        n = code.count(mut["anchor"])
        if n != 1:
            coverage.append((mut, "STALE", "anchor appears " + str(n) + "x above the catalogue"))
            continue
        mutated = tmp / ("mutant-" + mut["id"] + ".py")
        mutated.write_text(
            code.replace(mut["anchor"], mut["replacement"]) + marker + catalogue,
            encoding="utf-8",
        )
        r = subprocess.run([sys.executable, str(mutated), "check", str(fixture), "HEAD", str(ledger)],
                           capture_output=True, text=True, check=False, encoding="utf-8")
        if r.returncode not in (0, 1, 3):
            coverage.append((mut, "BROKEN", "the mutant did not run: " + r.stderr.strip()[-200:]))
            continue
        before, after = _fields(baseline_text), _fields(r.stdout)
        moved = [b for b, a in zip(before, after) if b != a] if len(before) == len(after) else before
        if moved:
            coverage.append((mut, "PINNED", str(len(moved)) + " verdict fields moved"))
        elif r.stdout != baseline_text:
            coverage.append((mut, "FORMATTER-ONLY", "output changed, not one verdict field moved"))
        else:
            coverage.append((mut, "UNPINNED", "nothing changed at all"))
    for mut, status, detail in coverage:
        agree = status.lower() == mut["expect"]
        print(("ok   " if agree else "FLIP ") + status.ljust(15) + " branch="
              + mut["branch"].ljust(16) + " " + mut["id"].ljust(20) + " " + detail)
        if not agree:
            flips.append(mut["id"] + ": declared " + mut["expect"] + ", measured " + status)
    print()
    for mut, status, detail in coverage:
        if status == "PINNED":
            continue
        # NOT DELETED TO IMPROVE THE NUMBER (RB-P48). A branch with no mutation that moves
        # a verdict field is printed here with the branch named and stays UNPINNED.
        print("# BRANCH " + mut["branch"] + " IS " + status + " — " + mut["why"]
              + ". Named node: " + mut["pins"] + ".")
    pinned = sum(1 for _m, s, _d in coverage if s == "PINNED")
    print()
    # THE SCOPE OF THE NEXT LINE, SAID ON THE LINE ITSELF. `branches=` read as an
    # inventory OF THIS PROGRAM and was an inventory OF THIS CATALOGUE: every decision
    # branch with no entry above was absent from the denominator rather than reported
    # UNPINNED, so the ratio flattered itself by omission. The field is renamed to say
    # what it counts, and the branches outside the catalogue are declared UNMEASURED
    # rather than given a number — no definition of "decision branch" is committed
    # anywhere in this repository, so any total here would be a count of whatever the
    # author's definition happened to be (the pin census's defect, one artifact over).
    print("# SCOPE. `catalogued-branches` counts the entries in MUTATIONS and nothing")
    print("# else. It is NOT the number of decision branches in this program, and the")
    print("# pinned share below is a share of the catalogue, not of the classifier.")
    print()
    print("SUMMARY expectations=" + str(len(expectations)) + " flips=" + str(len(flips))
          + " catalogued-branches=" + str(len(coverage)) + " pinned=" + str(pinned)
          + " unpinned=" + str(len(coverage) - pinned)
          + " uncatalogued-branches=UNMEASURED")
    if flips:
        print()
        print("# CALIBRATION FAILED. Nothing this program says about any real commit may be")
        print("# believed until these agree:")
        for f in flips:
            print("#   " + f)
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Enforce the record-vs-pointer rule.")
    sub = ap.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("check", help="judge a rev-range against an amend-only ledger")
    c.add_argument("repo", type=Path)
    c.add_argument("rev_range")
    c.add_argument("ledger", type=Path)
    c.add_argument("--out", type=Path, help="the ONLY write this program performs")
    k = sub.add_parser("calibrate", help="build the synthetic fixture and sweep the branches")
    k.add_argument("--keep", type=Path, help="keep the fixture at this path")
    args = ap.parse_args()

    if args.mode == "calibrate":
        return calibrate(args.keep)

    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        print("not a git repository: " + str(repo), file=sys.stderr)
        return 2
    try:
        patterns = load_ledger(args.ledger)
        rows, notes = check_range(repo, args.rev_range, patterns)
    except (Broken, ValueError, json.JSONDecodeError) as exc:
        print("BROKEN: " + str(exc), file=sys.stderr)
        return 2
    text, rc = render(rows, notes, repo, args.rev_range, patterns)
    print(text, end="")
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print("# wrote " + str(args.out))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
