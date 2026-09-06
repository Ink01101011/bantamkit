"""Repo map: hand-rolled definition scan, personalised PageRank, byte-budgeted listing.

Roadmap #10. **This is a precision feature and it is not a token saving.** Row 10's own
gate — "build only after #4 shows discovery tokens dominate" — was REFUTED by measurement:
discovery is 4,266.6 k estimated tokens, 33.8 % of tool-result bytes, but **0.114 %** of
3,739,207.9 k real prompt tokens, because 97.8 % of the real bill is `cache_read`. It
ships on an explicit user ruling to build it anyway. Nothing here saves bytes; what it
buys is the right file found sooner.

**No parser, and that is a ruling rather than a shortcut.** Row 10 says "tree-sitter
defs". `runtime-ts` declares exactly one runtime dependency (`@modelcontextprotocol/sdk`)
and the standing ruling is a pure-node `npx` install, so tree-sitter cannot land there.
Landing it in Python ALONE would be strictly worse than landing none: the two runtimes
would extract different definitions from the same file and every conformance case over
this module would become a ruled divergence — the exact failure the two-runtime rule
exists to prevent. tree-sitter is a MECHANISM; row 10's property is "definitions, ranked
by graph centrality, truncated to a budget", and that is what is implemented, the same
way on both sides.

**Every number below was measured before it was chosen**, on this repository's own 235
tracked source files, against a ground truth that is NOT an input to the ranking: with
file F as the focus, where in the ranking do F's own resolved in-repo imports land?
(19 focal files, 83 import pairs; `.shiftwork/notes-job45/J45-9-repomap.md` holds the
commands.) Imports are the yardstick precisely because they are not edges.

Each decision below names the alternative it beat.

- **Edges are name references, never imports.** Import-only edges leave 232 of 235
  files at score exactly 0.0 and have not converged after 40 rounds (L1 3.00e-03);
  adding the 41 import-only edges on top of the reference graph changes no top-10,
  top-20 or top-50 membership. References carry the graph; import resolution is
  per-language module-path logic both runtimes would have to reproduce byte for byte,
  bought for a rank swap between two files already in the top ten.
- **Comments and docstrings are stripped before BOTH the definition scan and the
  reference scan.** Leaving them in: recall@10 0.361, median rank 32. Stripped: 0.578
  and 7. Prose in a docstring — "and", "of", "what", "used" — was being read as a
  reference to whatever file happened to define that name.
- **ECMAScript definitions are taken at column 0 only.** Any-indentation 0.361,
  restricted 0.410 on its own. A local `const` inside a function is not a file's
  identity: 452 of `runtime-ts/src/docread.ts`'s "definitions" were locals, and they
  made it the top-ranked file for a focus on `memory/dream.py`.
- **A name must be defined in EXACTLY ONE file to carry an edge.** Allowing 2 / 3 / 5 / 10
  / any number of definers gives recall@10 0.566 / 0.518 / 0.530 / 0.518 / 0.506 against
  0.614 for one. A name defined in 51 files (`main`) says nothing about which file you
  want. **This is deliberately NOT a named constant.** It was one, and nothing read it —
  the rule lives in `_name_index`'s ambiguity set, so a port that changed the constant
  would have changed nothing, and a number the code ignores is a lie about what is
  configurable.
- **`REFERENCE_DF_MAX_NUM / _DEN = 1/8`** — a name referenced by more than an eighth of
  the scanned files is dropped before it can make an edge. Thresholds
  none / 1/2 / 1/4 / 1/8 / 1/16 / 1/32 / 1/64 give recall@10
  0.614 / 0.614 / 0.687 / **0.735** / 0.627 / 0.554 / 0.229. This is the one knob whose
  curve TURNS rather than merely rising, so the optimum is an optimum and not the end of
  a slope. It is also what makes a hand-maintained list of language builtins unnecessary:
  the most-referenced names in this repository are `from` (224 files), `import` (224),
  `return` (215), `for` (200), `not` (184), `name` (182), `path` (168), `str` (158) — and
  before this filter, `runtime-ts/src/shiftwork.ts` ranked SECOND for a focus on
  `memory/dream.py` purely because it declares `const str` at top level and every Python
  file mentions `str`. The comparison is written as the integer
  `df * REFERENCE_DF_MAX_DEN > files * REFERENCE_DF_MAX_NUM`, so no float enters it, and
  it is floored at `REFERENCE_DF_MAX_DEN` files so that a tree smaller than the
  denominator does not reject every name it holds.
- **`MIN_REFERENCE_LENGTH = 3`.** Lengths 1 / 2 / 3 / 4 / 5 give recall@10
  0.578 / 0.590 / 0.614 / 0.627 / 0.687 — the curve keeps rising, and past 3 it is
  overfitting the yardstick, because 4 and 5 drop real API names (`run`, `key`, `page`,
  `Fact`) to score better on a ground truth built from long private helpers. Three is
  the principled line: one- and two-character names are loop variables.
- **`DAMPING = 0.20`.** 0.10 / 0.20 / 0.30 / 0.50 / 0.85 give recall@10
  0.614 / 0.614 / 0.590 / 0.566 / 0.313. 0.85 is calibrated for global web authority;
  this is a LOCAL query and 0.85 measures three times worse. 0.10 ties 0.20, so the
  larger value is taken — it keeps more of the graph.
- **`ITERATIONS = 30`, with no early stop.** The iteration is affine with linear part
  `damping * (column-stochastic)`, so successive L1 deltas contract by at most `damping`
  each round: after 30 rounds the residual is bounded by `2 * 0.2**30` = 2.1e-21, below
  one ULP of any score. Measured on this repository the vector reaches an EXACT fixed
  point at round 16 and the remaining 14 rounds change no bit. A fixed count is also one
  fewer float comparison for the port to reproduce.

**The ranking is not a dressed-up neighbour count.** Measured over the same 19 focal
files, the top 20 differs from a plain edge-weight sort on 19 of 19, and a mean of 2.0
files per top-20 are files the focus does not reference directly at all.

## Determinism — what `runtime-ts` must reproduce, and the traps that were pinned

PageRank is floating-point iteration and both runtimes must produce the same ranking from
the same tree. IEEE-754 `+`, `*` and `/` on doubles are correctly rounded and identical in
CPython and V8, so bit-identity is achievable — but only if nothing in the loop is allowed
to be clever. Four CPython/JS traps were probed rather than assumed (J45-2 and J45-3 pinned
six others in `dream`; these are numbered on from those):

- **(7) `sum()` over floats is COMPENSATED in CPython and is not in JS.** Measured on
  CPython 3.12.13: `sum([0.1, 0.2, 0.3, 1e16, -1e16])` is `0.6`, an explicit accumulation
  loop over the same list is `0.0`, and node gives `0`. Nothing in this module calls
  `sum()` on floats: every accumulation in `pagerank` is a written-out loop, and
  `test_no_float_summation_or_rounding_in_the_source` reads that function's body to keep
  it that way.
- **(8) `float` -> `str` disagrees in FORM.** `repr(1.0)` is `'1.0'` and `String(1.0)` is
  `'1'`; `1e-07` vs `1e-7`; `1e+16` vs `10000000000000000` — four of six probed values
  differ. **No raw float is ever rendered.** `RepoMap.text` carries no score at all, and
  the structured result carries `rank_units`, an integer.
- **(9) `round()` is banker's in CPython and half-up in JS.** `round(0.5)` is 0 and 2 in
  the two; `round(2.5)` is 2 and 3. Never used. `rank_units` is
  `math.floor(score * SCORE_SCALE)`, and `math.floor` and `Math.floor` agreed on every
  probed value including negatives.
- **(10) `sorted()` on `str` is code-point order; JS's default `Array.sort` is UTF-16
  code-UNIT order**, and the two disagree above the BMP. Every sort here is over paths and
  names and goes through an explicit comparator the port must copy (`_by_code_point`).

Beyond those: the accumulation ORDER is pinned (nodes in sorted order, each node's out-edges
in sorted target order), the contribution is written `score[i] * w / out[i]` and evaluated
strictly left to right, dangling mass goes to the personalisation vector, and the initial
vector IS the personalisation vector. `rank_units` is a second line of defence rather than
the first: because the arithmetic is bit-identical the scores are equal, not merely close,
and quantising then breaking ties by path means a future drift degrades to a stable order
instead of an unstable one.

## The budget is counted in UTF-8 BYTES, and that is stated rather than converted

Row 10 says "1 K-token budget". This module cannot honour that unit honestly. The
repository's exported `tokens()` (`memory/store.py`) is an ASCII-only word split returning
a SET — it is a similarity primitive, not a counter, and it is not a model tokenizer. No
tokenizer exists in either runtime and adding one is a dependency the ruling forbids. So
**the budget is stated, enforced and reported in UTF-8 bytes**, and `DEFAULT_BUDGET` is
4000 — 1 K tokens at the char/4 convention this repository already uses in
`tools/hooks/bantamkit-hook.mjs`. That convention is an ESTIMATE and **its error bar is not
measured here**, because measuring it needs a tokenizer this runtime is not allowed to
have. Bytes are what is enforced; the token figure is a note about where 4000 came from.

The omission footer is deliberately NOT charged to the budget. A budget that can suppress
the disclosure of what it dropped is the defect the footer exists to close.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "DAMPING",
    "DEFAULT_BUDGET",
    "ITERATIONS",
    "MAX_FILE_BYTES",
    "MIN_REFERENCE_LENGTH",
    "REFERENCE_DF_MAX_DEN",
    "REFERENCE_DF_MAX_NUM",
    "OMIT_BUDGET",
    "OMIT_NO_DEFINITIONS",
    "OMIT_SIZE_CAP",
    "OMIT_UNKNOWN_LANGUAGE",
    "OMIT_PER_FILE_CAP",
    "OMIT_UNREACHABLE",
    "OMIT_UNREADABLE",
    "SCORE_SCALE",
    "Definition",
    "Omission",
    "RankedFile",
    "RepoMap",
    "SKIP_DIRS",
    "MAX_DEFINITIONS_PER_FILE",
    "build_graph",
    "language_of",
    "pagerank",
    "reference_names",
    "repo_map",
    "scan_definitions",
    "select_definitions",
    "strip_noncode",
    "walk_sources",
]

# --- pinned constants -------------------------------------------------------------
# Every one of these is measured in the table above. A port that changes one changes the
# ranking, so they are named rather than inlined.
DAMPING = 0.20
ITERATIONS = 30
MIN_REFERENCE_LENGTH = 3
# A name referenced by more than NUM/DEN of the scanned files makes no edge. Compared as
# integers on both sides so the threshold cannot drift on a float.
REFERENCE_DF_MAX_NUM = 1
REFERENCE_DF_MAX_DEN = 8
# At most this many definitions of any one file reach the listing. See the module
# docstring: without it a 4000-byte map over this repository holds 6.1 files.
MAX_DEFINITIONS_PER_FILE = 4
DEFAULT_BUDGET = 4000
SCORE_SCALE = 1_000_000_000
# A source file larger than this is not scanned. 1 MiB; the largest tracked source in this
# repository is well under it, so the cap is a guard against a vendored bundle rather than
# a working limit, and a file it stops is REPORTED, never dropped.
MAX_FILE_BYTES = 1_048_576

SKIP_DIRS = (
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
)

# Suffix -> dialect. Two dialects only: `python` and `ecma`. TypeScript and JavaScript
# share a scanner because their DECLARATION forms are the same set; the extra TypeScript
# keywords (`interface`, `type`, `enum`) are simply absent from a `.js` file.
LANGUAGES = {
    ".cjs": "ecma",
    ".cts": "ecma",
    ".js": "ecma",
    ".jsx": "ecma",
    ".mjs": "ecma",
    ".mts": "ecma",
    ".py": "python",
    ".pyi": "python",
    ".ts": "ecma",
    ".tsx": "ecma",
}

OMIT_UNKNOWN_LANGUAGE = "unknown-language"
OMIT_UNREADABLE = "unreadable-bytes"
OMIT_SIZE_CAP = "size-cap"
OMIT_NO_DEFINITIONS = "no-definitions"
OMIT_UNREACHABLE = "unreachable"
OMIT_PER_FILE_CAP = "per-file-cap"
OMIT_BUDGET = "budget"

# Fixed render order for the footer, so two runs of the same map cannot disagree about the
# order of their disclosures.
OMISSION_ORDER = (
    OMIT_UNKNOWN_LANGUAGE,
    OMIT_UNREADABLE,
    OMIT_SIZE_CAP,
    OMIT_NO_DEFINITIONS,
    OMIT_UNREACHABLE,
    OMIT_PER_FILE_CAP,
    OMIT_BUDGET,
)

_ECMA_KEYWORDS = (
    "function",
    "class",
    "interface",
    "type",
    "const",
    "let",
    "var",
    "enum",
)


@dataclass(frozen=True)
class Definition:
    """One definition, at the line it was declared on. `line` is 1-based and counts lines
    of the ORIGINAL file, not of the comment-stripped view: a caller that jumps to it must
    land where the reader would."""

    path: str
    line: int
    kind: str
    name: str


@dataclass(frozen=True)
class Omission:
    """Something the tree holds that the map does not carry, as a COUNT and the fact
    behind it — `docread.Omission`'s discipline, deliberately re-stated here rather than
    imported, because these subjects are this module's and a shared vocabulary would make
    a change to one reader a change to the other.

    Never an adjective. `subject` is one of the `OMIT_*` tokens; a renderer that meets a
    token it does not know must still print the count. A silent skip is how a reader lies
    about its coverage."""

    subject: str
    count: int
    size: int = 0
    facts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class RankedFile:
    path: str
    rank_units: int
    definitions: tuple[Definition, ...]
    # The raw double. Reported for a caller that wants it; NEVER rendered, and never the
    # sort key — see trap (8).
    score: float = 0.0


@dataclass(frozen=True)
class RepoMap:
    text: str
    ranked: tuple[RankedFile, ...]
    omissions: tuple[Omission, ...]
    focus: tuple[str, ...]
    nodes: int
    edges: int
    definitions: int
    damping: float
    iterations: int
    budget: int
    per_file: int
    listing_bytes: int
    files_rendered: int = 0
    definitions_rendered: int = 0


def _by_code_point(value: str) -> tuple[int, ...]:
    """Sort key that is code-point order in BOTH runtimes — trap (10).

    CPython's `sorted()` on `str` already compares by code point; JS's default
    `Array.prototype.sort` compares UTF-16 code UNITS, so a name containing an astral
    character sorts differently there. Every sort in this module routes through this
    function so the port has one comparator to copy instead of a rule to remember."""
    return tuple(ord(ch) for ch in value)


def language_of(path: str) -> str | None:
    """The dialect for a path, or `None` when this scanner has no reader for it.

    Dispatch is on SUFFIX, and that is a deliberate departure from `docread`, which
    sniffs because a suffix is measurably a lie about a document's container. A source
    file is different: `.py` and `.ts` name a GRAMMAR, and there is no magic number for a
    grammar. A file whose suffix is unknown is reported, never guessed at."""
    dot = path.rfind(".")
    slash = max(path.rfind("/"), path.rfind("\\"))
    if dot < 0 or dot < slash:
        return None
    return LANGUAGES.get(path[dot:].lower())


def strip_noncode(text: str, language: str) -> list[str]:
    """The file's lines with comments and docstrings blanked, one output line per input
    line so line numbers survive.

    Line-oriented and stateful across lines, because both traps that matter span lines:
    a Python triple-quoted docstring and an ECMAScript `/* */` block. What is removed:

    - `python` — `'''`/`\"\"\"` blocks (the delimiter that opens is the only one that can
      close), and everything from an unquoted `#` to end of line.
    - `ecma` — `/* */` blocks, and everything from `//` to end of line.

    What is NOT removed, and is declared rather than hidden: the contents of a SINGLE-line
    string literal. Stripping those would lose the real references inside an f-string
    (`f"{store._fact_path(x)}"`), and keeping them costs a definition-shaped line inside a
    one-line string being read as a definition. Measured over this repository's 235 source
    files that costs nothing detectable; a repository that embeds source in string literals
    would see it, and would see it as extra edges rather than missing ones.

    Backslash escapes are NOT honoured: `\"\"\"` inside a string toggles the state machine.
    Both runtimes get that wrong identically, which is the requirement."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    delim = ""
    for raw in lines:
        line = raw
        if language == "python":
            if delim:
                at = line.find(delim)
                if at < 0:
                    out.append("")
                    continue
                line = line[at + 3 :]
                delim = ""
            while True:
                double = line.find('"""')
                single = line.find("'''")
                if double < 0 and single < 0:
                    break
                if double < 0:
                    at = single
                elif single < 0:
                    at = double
                else:
                    at = double if double < single else single
                opener = line[at : at + 3]
                close = line.find(opener, at + 3)
                if close < 0:
                    delim = opener
                    line = line[:at]
                    break
                line = line[:at] + " " + line[close + 3 :]
            hash_at = line.find("#")
            if hash_at >= 0:
                line = line[:hash_at]
        else:
            if delim:
                at = line.find("*/")
                if at < 0:
                    out.append("")
                    continue
                line = line[at + 2 :]
                delim = ""
            while True:
                at = line.find("/*")
                if at < 0:
                    break
                close = line.find("*/", at + 2)
                if close < 0:
                    delim = "*/"
                    line = line[:at]
                    break
                line = line[:at] + " " + line[close + 2 :]
            slash_at = line.find("//")
            if slash_at >= 0:
                line = line[:slash_at]
        out.append(line)
    return out


def _is_name_start(ch: str) -> bool:
    return ch == "_" or ch == "$" or ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _is_name_char(ch: str) -> bool:
    return _is_name_start(ch) or ("0" <= ch <= "9")


def _name_at(line: str, at: int) -> str:
    """The identifier starting at `at`, or `""`.

    Hand-rolled rather than a regex on purpose. `re` and `RegExp` agree on this character
    class, but a scan written out cannot pick up a dialect difference later, and the same
    twenty lines port to TypeScript unchanged. ASCII only, exactly as `tokens()` is:
    a Python identifier may hold non-ASCII and this scanner will not see it. That is a
    declared limit and not a defect to fix in one runtime."""
    if at >= len(line) or not _is_name_start(line[at]):
        return ""
    end = at + 1
    while end < len(line) and _is_name_char(line[end]):
        end += 1
    return line[at:end]


def _skip_blank(line: str, at: int) -> int:
    while at < len(line) and (line[at] == " " or line[at] == "\t"):
        at += 1
    return at


def _word_then_blank(line: str, at: int, word: str) -> int:
    """`at` advanced past `word` and the whitespace after it, or -1."""
    end = at + len(word)
    if line[at:end] != word:
        return -1
    after = _skip_blank(line, end)
    return after if after > end else -1


def scan_definitions(text: str, language: str, path: str = "") -> tuple[Definition, ...]:
    """Every definition in `text`, in source order.

    `python` — `def` and `class` at ANY indentation, so a method counts. Methods are the
    signal that made the difference in measurement: a focus on `memory/dream.py` reaches
    `memory/store.py` through `_write_fact`, `_fact_path` and `_check_index_budget`, none
    of which is top-level. Plus a bare `NAME =` or `NAME: T =` at column 0, which is how
    this repository declares its constants.

    `ecma` — `function class interface type const let var enum` at COLUMN 0 only,
    optionally behind `export` and `default` and `async`. Restricting to column 0 was the
    second-largest measured improvement in this module (recall@10 0.361 -> 0.410 on its own,
    0.578 combined with comment stripping): an indented `const` is a local, and
    `runtime-ts/src/docread.ts` was contributing 452 of them.

    The asymmetry is real and is not an oversight: an ECMAScript class member cannot be
    told from a call at the same indentation without tracking braces, and a scanner that
    guessed would invent definitions. Python's `def` keyword makes the same question free.
    """
    definitions: list[Definition] = []
    seen: set[tuple[int, str]] = set()
    for index, line in enumerate(strip_noncode(text, language)):
        number = index + 1
        if language == "python":
            at = _skip_blank(line, 0)
            head = at
            after = _word_then_blank(line, at, "async")
            if after > 0:
                at = after
            for keyword in ("def", "class"):
                after = _word_then_blank(line, at, keyword)
                if after < 0:
                    continue
                name = _name_at(line, after)
                if name and (number, name) not in seen:
                    seen.add((number, name))
                    definitions.append(Definition(path, number, keyword, name))
                break
            if head != 0:
                continue
            name = _name_at(line, 0)
            if not name:
                continue
            at = _skip_blank(line, len(name))
            if at < len(line) and line[at] == ":":
                # `NAME: T = ...` — the annotation may hold anything but `=`.
                at += 1
                while at < len(line) and line[at] != "=":
                    at += 1
            if at >= len(line) or line[at] != "=":
                continue
            if at + 1 < len(line) and line[at + 1] == "=":
                continue
            if (number, name) not in seen:
                seen.add((number, name))
                definitions.append(Definition(path, number, "const", name))
        else:
            if line[:1] in (" ", "\t"):
                continue
            at = 0
            for prefix in ("export", "default", "async"):
                after = _word_then_blank(line, at, prefix)
                if after > 0:
                    at = after
            for keyword in _ECMA_KEYWORDS:
                after = _word_then_blank(line, at, keyword)
                if after < 0:
                    continue
                name = _name_at(line, after)
                if name and (number, name) not in seen:
                    seen.add((number, name))
                    definitions.append(Definition(path, number, keyword, name))
                break
    return tuple(definitions)


def reference_names(text: str, language: str) -> set[str]:
    """Every identifier of at least `MIN_REFERENCE_LENGTH` characters outside a comment.

    A SET, not a count. The edge weight below is "how many DISTINCT names of B does A
    mention", so a file that repeats one name a hundred times does not out-weigh a file
    that mentions ten. That is the choice the ambiguity filter and `MIN_REFERENCE_LENGTH`
    were tuned against and it keeps every weight an exact integer."""
    names: set[str] = set()
    for line in strip_noncode(text, language):
        at = 0
        width = len(line)
        while at < width:
            if not _is_name_start(line[at]):
                at += 1
                continue
            name = _name_at(line, at)
            at += len(name)
            if len(name) >= MIN_REFERENCE_LENGTH:
                names.add(name)
    return names


def walk_sources(root: str | os.PathLike[str]) -> list[str]:
    """Every path under `root`, relative, POSIX, sorted — dialect or not.

    The language filter is NOT here, it is in `_scan_tree`, and the difference is the
    whole omission contract: a walk that filtered here would make every unknown file
    vanish instead of being counted as `unknown-language`, and a reader that silently
    drops what it cannot read is lying about its coverage. The gap is most of the tree —
    dated, because it co-moves with repo content: 2026-09-07, 1968 paths returned and 278
    with a language. Re-measure, do not quote:

        walk_sources(".") vs [p for p in walk_sources(".") if language_of(p)]

    Directory symlinks are NOT followed. Two reasons and both are measured elsewhere in
    this repository: a symlink cycle makes the walk non-terminating, and a dangling
    directory symlink is one error shape on POSIX and two on Windows
    (`reference-windows-dangling-symlink-two-shapes`), so following one is a portability
    question with no upside for a map."""
    base = Path(root)
    found: list[str] = []
    for directory, subdirs, filenames in os.walk(base, followlinks=False):
        kept = [
            d
            for d in subdirs
            if d not in SKIP_DIRS and not os.path.islink(os.path.join(directory, d))
        ]
        subdirs[:] = sorted(kept, key=_by_code_point)
        for filename in sorted(filenames, key=_by_code_point):
            full = Path(directory) / filename
            found.append(full.relative_to(base).as_posix())
    return sorted(found, key=_by_code_point)


@dataclass
class _Scanned:
    paths: list[str] = field(default_factory=list)
    definitions: dict[str, tuple[Definition, ...]] = field(default_factory=dict)
    references: dict[str, set[str]] = field(default_factory=dict)
    omissions: list[Omission] = field(default_factory=list)


def _scan_tree(root: Path, candidates: list[str]) -> _Scanned:
    out = _Scanned()
    unknown = 0
    unknown_bytes = 0
    unreadable: list[str] = []
    unreadable_bytes = 0
    oversize = 0
    oversize_bytes = 0
    empty = 0
    for rel in candidates:
        language = language_of(rel)
        full = root / rel
        try:
            size = full.stat().st_size
        except OSError:
            size = 0
        if language is None:
            unknown += 1
            unknown_bytes += size
            continue
        if size > MAX_FILE_BYTES:
            oversize += 1
            oversize_bytes += size
            continue
        try:
            text = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            unreadable.append(rel)
            unreadable_bytes += size
            continue
        found = scan_definitions(text, language, rel)
        out.paths.append(rel)
        out.definitions[rel] = found
        out.references[rel] = reference_names(text, language)
        if not found:
            empty += 1
    if unknown:
        out.omissions.append(Omission(OMIT_UNKNOWN_LANGUAGE, unknown, unknown_bytes))
    if unreadable:
        out.omissions.append(Omission(OMIT_UNREADABLE, len(unreadable), unreadable_bytes))
    if oversize:
        out.omissions.append(
            Omission(OMIT_SIZE_CAP, oversize, oversize_bytes, (("cap_bytes", MAX_FILE_BYTES),))
        )
    if empty:
        out.omissions.append(Omission(OMIT_NO_DEFINITIONS, empty))
    return out


def _name_index(
    definitions: dict[str, tuple[Definition, ...]],
    references: dict[str, set[str]],
) -> tuple[dict[str, str], dict[str, int]]:
    """`(definer, frequency)` over the names that are allowed to carry file identity.

    A name survives two filters and they catch different failures. The AMBIGUITY filter
    drops a name defined in more than one file — `main` is defined in 51 of this
    repository's files and `__init__` in 39, and letting those through costs recall@10
    0.614 -> 0.506. The document-frequency filter drops a name REFERENCED by more than an
    eighth of the files, which is what stops a top-level `const str` in one file from
    collecting an edge from every Python file in the tree.

    The second return is the RAW reference count for every name, unfiltered, because it
    answers a different question and the two answers must not be conflated. The edge
    question is "which file does this name IDENTIFY?" and both filters serve it. The
    RENDERING question is "what is this file best known BY?", and there a widely-referenced
    name is exactly the one worth the bytes. Running the filters over both was measured on
    this repository and it is wrong for the second: `class MemoryStore` is referenced by 34
    of 275 files and defined in two of them (`memory/store.py` and its port
    `memory/store.ts`), so BOTH filters reject it — and `memory/store.py`'s block came out
    as `headroom`, `lint`, `archived`, `archive`, with the class the file exists for
    nowhere in the map."""
    files = len(references)
    frequency: dict[str, int] = {}
    for path in sorted(references, key=_by_code_point):
        for name in references[path]:
            frequency[name] = frequency.get(name, 0) + 1
    definer: dict[str, str] = {}
    ambiguous: set[str] = set()
    for path in sorted(definitions, key=_by_code_point):
        for definition in definitions[path]:
            name = definition.name
            if name in ambiguous:
                continue
            held = definer.get(name)
            if held is None:
                definer[name] = path
            elif held != path:
                ambiguous.add(name)
                del definer[name]
    for name in sorted(definer, key=_by_code_point):
        seen = frequency.get(name, 0)
        # A FLOOR ON THE THRESHOLD, and it was found by the tests rather than reasoned
        # about. A fraction of a tree smaller than the denominator is less than one file,
        # so on a three-file project the eighth rejected every name that was mentioned at
        # all and the map came back completely empty. A name fewer than
        # `REFERENCE_DF_MAX_DEN` files mention is never "too common", whatever the
        # fraction says. On this repository the threshold is 34 of 275 files and the floor
        # is 8, so the floor is INERT here and changes no measured number in the docstring
        # above — it only rescues trees too small for a fraction to mean anything.
        if seen <= REFERENCE_DF_MAX_DEN:
            continue
        if seen * REFERENCE_DF_MAX_DEN > files * REFERENCE_DF_MAX_NUM:
            del definer[name]
    return definer, frequency


def build_graph(
    definitions: dict[str, tuple[Definition, ...]],
    references: dict[str, set[str]],
) -> dict[str, dict[str, int]]:
    """`source -> {target: weight}`, weight being the number of surviving names the source
    mentions that ONLY the target defines.

    Weights are exact integers, so `out[i]` in `pagerank` is an exact integer too and the
    only inexact step in the whole pass is the one division."""
    definer, _ = _name_index(definitions, references)
    edges: dict[str, dict[str, int]] = {}
    for path in sorted(references, key=_by_code_point):
        weights: dict[str, int] = {}
        for name in sorted(references[path], key=_by_code_point):
            target = definer.get(name)
            if target is None or target == path:
                continue
            weights[target] = weights.get(target, 0) + 1
        if weights:
            edges[path] = weights
    return edges


# A definition's kind decides what it is worth saying about a file, before any count does.
# A type names the file's subject; a callable is its verb; a binding is a detail.
_KIND_RANK = {
    "class": 0,
    "interface": 0,
    "enum": 0,
    "type": 0,
    "def": 1,
    "function": 1,
    "const": 2,
    "let": 2,
    "var": 2,
}


def select_definitions(
    definitions: tuple[Definition, ...], references: dict[str, int], limit: int
) -> tuple[Definition, ...]:
    """At most `limit` of a file's definitions, chosen by kind then reach, returned in
    SOURCE order.

    The key is `(kind rank, -reference count, line, name)`, and every part of it is an
    integer or a code-point tuple, so the choice is total and the port has nothing to
    interpret. `references` is the RAW count from `_name_index` — see that function for why
    it is not the filtered one.

    **This ordering is argued, not measured, and the difference matters.** Every other
    constant in this module beat a named alternative on a yardstick. This one cannot: the
    yardstick is "does the focus file's own import appear in the rendered map", which is a
    question about which FILES are listed, and selection only decides which lines appear
    UNDER a file already listed. Measured, it moves that number by zero. So it rests on a
    stated principle instead — name the file's subject before its details — and a later
    unit with a definition-level yardstick is entitled to overturn it. What it is NOT is
    source order, which put `VALID_TYPES`, `DURABLE_TYPES`, `NAME_RE` and
    `DUPLICATE_JACCARD` at the head of `memory/store.py`'s block.

    The selected definitions are re-sorted into SOURCE order for rendering: a block whose
    line numbers ran backwards would be harder to read for no gain, and the order a block
    is chosen in is not the order it is read in."""
    if limit <= 0 or len(definitions) <= limit:
        return definitions
    ordered = sorted(
        definitions,
        key=lambda d: (
            _KIND_RANK.get(d.kind, len(_KIND_RANK)),
            -references.get(d.name, 0),
            d.line,
            _by_code_point(d.name),
        ),
    )
    chosen = ordered[:limit]
    return tuple(sorted(chosen, key=lambda d: (d.line, _by_code_point(d.name))))


def pagerank(
    nodes: list[str],
    edges: dict[str, dict[str, int]],
    personal: list[str],
    damping: float = DAMPING,
    iterations: int = ITERATIONS,
) -> list[float]:
    """Personalised PageRank, bit-identical to the port by construction.

    The port contract, in the order the loop performs it:

    1. `nodes` is already sorted; index by position in it.
    2. `out[i]` is the exact integer sum of node i's out-weights.
    3. Each node's out-edges are visited in sorted TARGET order.
    4. The personalisation vector is `1/len(personal)` on each focus node and 0 elsewhere;
       with no focus it is `1/n` on every node. The INITIAL vector is that same vector.
    5. Per round: zero `next`; walk sources in node order; a node with no out-edges adds
       its whole score to `dangling`; otherwise each out-edge adds
       `score[i] * weight / out[i]`, evaluated strictly left to right.
    6. `tele = damping * dangling + (1.0 - damping)`, then
       `next[i] = next[i] * damping + tele * personal[i]`.
    7. Exactly `iterations` rounds. No early stop, no convergence test — see trap (7)'s
       neighbour: a branch on a float is one more thing for a port to get wrong, and the
       contraction bound makes the test unnecessary.

    There is no `sum()` here and there must not be one in the port either: CPython 3.12
    compensates float `sum()` and JS does not (trap 7)."""
    count = len(nodes)
    if count == 0:
        return []
    index = {path: i for i, path in enumerate(nodes)}
    out = [0] * count
    adjacency: list[list[tuple[int, int]]] = [[] for _ in range(count)]
    for path in nodes:
        source = index[path]
        for target in sorted(edges.get(path, {}), key=_by_code_point):
            weight = edges[path][target]
            if target not in index:
                continue
            adjacency[source].append((index[target], weight))
            out[source] += weight
    focus = [p for p in personal if p in index]
    vector = [0.0] * count
    if focus:
        share = 1.0 / len(focus)
        for path in focus:
            vector[index[path]] = share
    else:
        share = 1.0 / count
        for i in range(count):
            vector[i] = share
    score = list(vector)
    for _ in range(iterations):
        nxt = [0.0] * count
        dangling = 0.0
        for i in range(count):
            if out[i] == 0:
                dangling += score[i]
                continue
            for target, weight in adjacency[i]:
                nxt[target] += score[i] * weight / out[i]
        tele = damping * dangling + (1.0 - damping)
        for i in range(count):
            nxt[i] = nxt[i] * damping + tele * vector[i]
        score = nxt
    return score


def _render(ranked: list[RankedFile], budget: int) -> tuple[str, int, int, int, int, int, int]:
    """The listing, greedily filled in rank order, plus what it could not carry.

    A file block is its path on one line, then one indented line per definition in source
    order. A block that does not fit whole is included as far as it fits — the header plus
    the definitions that fit — because dropping a whole high-rank file for one line's
    overflow would hand back an empty map for a repository whose top file is large. A
    header with no definition under it is never emitted: it would spend bytes to say
    nothing."""
    parts: list[str] = []
    used = 0
    files_rendered = 0
    definitions_rendered = 0
    files_dropped = 0
    definitions_dropped = 0
    files_partial = 0
    stopped = False
    for entry in ranked:
        if stopped:
            files_dropped += 1
            definitions_dropped += len(entry.definitions)
            continue
        header = entry.path
        block: list[str] = []
        cost = len(header.encode("utf-8")) + (1 if parts else 0)
        dropped_here = 0
        for definition in entry.definitions:
            line = f"  {definition.line} {definition.kind} {definition.name}"
            line_cost = len(line.encode("utf-8")) + 1
            if used + cost + line_cost > budget:
                dropped_here += 1
                continue
            block.append(line)
            cost += line_cost
        if not block:
            stopped = True
            files_dropped += 1
            definitions_dropped += len(entry.definitions)
            continue
        if parts:
            parts.append("")
        parts.append(header)
        parts.extend(block)
        used += cost
        files_rendered += 1
        definitions_rendered += len(block)
        if dropped_here:
            files_partial += 1
            definitions_dropped += dropped_here
            stopped = True
    return (
        "\n".join(parts),
        used,
        files_rendered,
        definitions_rendered,
        files_dropped,
        definitions_dropped,
        files_partial,
    )


def _footer(omissions: list[Omission]) -> str:
    """`# omitted: subject=count ...` — counts, never adjectives, in `OMISSION_ORDER`.

    NOT charged to the budget, deliberately. A budget that could suppress the disclosure of
    what it dropped is the failure this line exists to close, and a footer that fits only
    when there is nothing to say would do exactly that. A subject with a zero count is not
    printed; a subject this module does not know cannot occur here, but a RENDERER that
    meets one must still print its count."""
    by_subject = {o.subject: o for o in omissions}
    fields = [
        f"{subject}={by_subject[subject].count}"
        for subject in OMISSION_ORDER
        if subject in by_subject and by_subject[subject].count
    ]
    extra = sorted(
        (o for o in omissions if o.subject not in OMISSION_ORDER and o.count),
        key=lambda o: _by_code_point(o.subject),
    )
    fields.extend(f"{o.subject}={o.count}" for o in extra)
    return "# omitted: " + " ".join(fields) if fields else ""


def repo_map(
    root: str | os.PathLike[str],
    focus: list[str] | tuple[str, ...] = (),
    budget: int = DEFAULT_BUDGET,
    files: list[str] | None = None,
    damping: float = DAMPING,
    iterations: int = ITERATIONS,
    per_file: int = MAX_DEFINITIONS_PER_FILE,
) -> RepoMap:
    """Scan `root`, rank its files against `focus`, and render a listing within `budget`.

    `focus` is the current unit's files, relative to `root` and POSIX-separated; a focus
    entry that is not a scanned source is ignored for the personalisation vector but is
    still excluded from the listing, because a caller naming a file has it open already.
    An empty focus gives the uniform vector — plain centrality over the whole tree.

    `budget` is UTF-8 BYTES of the listing. See the module docstring: this runtime has no
    model tokenizer and will not pretend to one."""
    base = Path(root)
    candidates = list(files) if files is not None else walk_sources(base)
    candidates = sorted(candidates, key=_by_code_point)
    scanned = _scan_tree(base, candidates)
    nodes = scanned.paths
    _, references = _name_index(scanned.definitions, scanned.references)
    edges = build_graph(scanned.definitions, scanned.references)
    focus_paths = sorted({str(f) for f in focus}, key=_by_code_point)
    scores = pagerank(nodes, edges, focus_paths, damping, iterations)
    focus_set = set(focus_paths)

    ranked: list[RankedFile] = []
    unreachable = 0
    capped = 0
    for i, path in enumerate(nodes):
        if path in focus_set:
            continue
        score = scores[i]
        if score <= 0.0:
            unreachable += 1
            continue
        definitions = scanned.definitions[path]
        if not definitions:
            continue
        shown = select_definitions(definitions, references, per_file)
        capped += len(definitions) - len(shown)
        ranked.append(RankedFile(path, math.floor(score * SCORE_SCALE), shown, score))
    # The ONLY sort of the score vector, and it is over an integer with an explicit
    # by-path tie-break — traps (8) and (10).
    ranked.sort(key=lambda entry: (-entry.rank_units, _by_code_point(entry.path)))

    (
        listing,
        listing_bytes,
        files_rendered,
        definitions_rendered,
        files_dropped,
        definitions_dropped,
        files_partial,
    ) = _render(ranked, budget)

    omissions = list(scanned.omissions)
    if unreachable:
        omissions.append(Omission(OMIT_UNREACHABLE, unreachable))
    if capped:
        omissions.append(Omission(OMIT_PER_FILE_CAP, capped, 0, (("per_file", per_file),)))
    if files_dropped or definitions_dropped:
        omissions.append(
            Omission(
                OMIT_BUDGET,
                files_dropped,
                0,
                (
                    ("definitions", definitions_dropped),
                    ("files_partial", files_partial),
                    ("budget_bytes", budget),
                    ("listing_bytes", listing_bytes),
                ),
            )
        )
    footer = _footer(omissions)
    text = listing
    if footer:
        text = f"{listing}\n{footer}" if listing else footer
    return RepoMap(
        text=text,
        ranked=tuple(ranked),
        omissions=tuple(omissions),
        focus=tuple(focus_paths),
        nodes=len(nodes),
        edges=sum(len(v) for v in edges.values()),
        definitions=sum(len(v) for v in scanned.definitions.values()),
        damping=damping,
        iterations=iterations,
        budget=budget,
        per_file=per_file,
        listing_bytes=listing_bytes,
        files_rendered=files_rendered,
        definitions_rendered=definitions_rendered,
    )
