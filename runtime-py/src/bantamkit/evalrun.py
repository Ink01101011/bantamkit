"""Eval harness: bare vs +toolkit on the same suite, with token accounting (spec §4.6)."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import tempfile
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

import yaml

from bantamkit.agent import Agent, MaxTurnsExceeded, ToolDef, response_format_for
from bantamkit.assets import assets_root, load_tool
from bantamkit.budget import TokenBudget
from bantamkit.client import BantamError, Message, ModelClient, OpenAICompatible, Tool, Usage
from bantamkit.contract import (
    document_error,
    document_manifest,
    document_offset_past_end,
    document_page,
    document_paste,
    document_unknown,
    schema_error,
    schema_instruction,
    schema_retry_feedback,
)
from bantamkit.critique import CritiqueExhausted, CritiqueGate, GroundedCritiqueGate
from bantamkit.docread import Document, DocumentReadError, extract, page
from bantamkit.filegraph import FileAccessGraph, ReadAccounting
from bantamkit.loopguard import LoopGuard
from bantamkit.memory import Memory, MemoryStore
from bantamkit.profile import default as profile_default
from bantamkit.profile import load_profile
from bantamkit.structured import (
    JsonAnswerGate,
    StructuredOutputError,
    extract_json,
    structured,
)

CONFIGS = ["bare", "structured", "critique", "grounded", "graph", "memory", "lean", "full"]


# ---- deterministic eval fixture tools (fixture data lives in assets) ----


def _catalog() -> dict:
    return json.loads((assets_root() / "evals" / "fixtures" / "catalog.json").read_text())


def _lookup(field: str):
    def handler(item: str) -> str:
        entry = _catalog().get(item.lower())
        if entry is None:
            return f"error: unknown item '{item}'. known items: {sorted(_catalog())}"
        return f"{item.lower()} {field}: {entry[field]}"

    return handler


_ITEM_SCHEMA = {
    "type": "object",
    "required": ["item"],
    "properties": {"item": {"type": "string"}},
}

_PRICE_TOOL = ToolDef(
    tool=Tool(
        name="price_lookup",
        description="Get the unit price of an item",
        parameters=_ITEM_SCHEMA,
    ),
    handler=_lookup("price"),
)
_STOCK_TOOL = ToolDef(
    tool=Tool(
        name="stock_lookup",
        description="Get the stock count of an item",
        parameters=_ITEM_SCHEMA,
    ),
    handler=_lookup("stock"),
)

BUILTIN_TOOLS = {
    "price_lookup": _PRICE_TOOL,
    "stock_lookup": _STOCK_TOOL,
}

WORKSPACE_TOOLS = ("read_file", "list_files")

_PATH_SCHEMA = {
    "type": "object",
    "required": ["path"],
    "properties": {"path": {"type": "string"}},
}


def _workspace_tools(workspace: dict) -> dict[str, ToolDef]:
    """Per-task file tools over the task's `workspace:` mapping (path -> content)."""

    def read_file(path: str) -> str:
        content = workspace.get(path)
        if content is None:
            return f"error: unknown file '{path}'. available: {sorted(workspace)}"
        return content

    def list_files() -> str:
        return "\n".join(sorted(workspace))

    return {
        "read_file": ToolDef(
            tool=Tool(
                name="read_file",
                description="Read the full content of one file by its exact path",
                parameters=_PATH_SCHEMA,
            ),
            handler=read_file,
        ),
        "list_files": ToolDef(
            tool=Tool(
                name="list_files",
                description="List all file paths in the workspace",
                parameters={"type": "object", "properties": {}},
            ),
            handler=list_files,
        ),
    }


GRAPH_CONFIGS = {
    "graph": {"annotate": True, "cache": True, "query": True},
    "graph-annotate": {"annotate": True, "cache": False, "query": False},
    "graph-cache": {"annotate": True, "cache": True, "query": False},
    # Rung zero WITH the ledger. `bare` is already a clean rung zero for the
    # ladder's token deltas — `graph-annotate`'s `effective` resolves to itself and
    # picks up no other component, so `bare -> graph-annotate -> graph-cache ->
    # graph` isolates one flag per step. What `bare` cannot do is COUNT: it attaches
    # no FileAccessGraph, so nothing records how many reads a run made or how many
    # of them were repeats. All three flags off records the ledger and changes
    # nothing the model sees — the wrapped reader returns the observation unchanged on
    # every path when `cache` and `annotate` are both False (`filegraph.py:133-195`,
    # the three returns at `143`, `153` and `195`), and `setup` registers no tool and
    # adds no skill when `query` is False (`filegraph.py:118-122`). Both pins were
    # re-read at HEAD, not shifted by arithmetic: the previous `83-92` / `51-53` were
    # written against a pre-`d522e93` file and named 1 of the 3 return paths (bar
    # §9/A3, re-pinned in §9/A4). That is what makes it the meaning-preserving null
    # control: a mechanism-off arm that removes no information, and the only arm
    # that can tell "the collapse did not help" from "the collapse never fired".
    # Pinned by test_evalrun.py::test_graph_off_observations_are_identical_to_bare.
    "graph-off": {"annotate": False, "cache": False, "query": False},
}

# Calibration-only too (same precedent as GRAPH_CONFIGS): each name maps to the headline
# config it mirrors exactly, plus a TokenBudget. `budgeted` is `full` under a ceiling —
# it earns a place in CONFIGS only once the calibration bars say the ceiling holds.
BUDGET_CONFIGS = {"budgeted": "full"}

# Same precedent once more: each guarded name mirrors its headline config exactly, plus
# a LoopGuard — attached last in run_task so it wraps every tool (v1 wraps only what is
# registered at setup). Calibration-only until the conversion bars say otherwise.
GUARD_CONFIGS = {"graph-guarded": "graph", "memory-guarded": "memory"}

# Same precedent a fourth time. `reader` mirrors `bare` exactly, plus the document tool pair
# — and `bare` is the right thing to mirror, because it is the only arm that says what an
# over-window corpus costs with NO reader at all. Resolving `effective` to `bare` means the
# arm picks up no schema gate, no critic, no graph and no memory, so `bare -> reader`
# isolates one component per step exactly as `bare -> graph-annotate` does.
#
# Calibration-only, in CONFIG_CHOICES and NOT in CONFIGS, for the reason the other three are:
# a component earns a place in the permanent matrix when a bar says it did, and this job's
# bar has not been run yet. Keeping it out also means the default suite is byte-identical to
# the one before this commit for every task that declares no `document_setup:`.
READER_CONFIGS = {"reader": "bare"}

# Same precedent a fifth time, and this one is the reader's REAL comparison rather than its
# floor. `paste` mirrors `bare` exactly — no schema gate, no critic, no graph, no memory and
# NO reader tools — plus one system message carrying as much of the corpus as fits. It is what
# a practitioner with no reader does, and J4 died for assuming that paste was always available:
# `inventory.xlsx` extracts to 258,129 B, which is 7.88x the 8,192-token window the declared
# tiers are actually served at, so the paste J4 imagined is unconstructible and the arm that
# replaces it is incomplete BY CONSTRUCTION on the large corpus and complete on the small one.
# Pre-registered at `docs/eval-data/2026-08-20-document-read-bar.md` §10.2 before any arm ran;
# this is a transcription of that contract, and the constant below is one of its five clauses.
PASTE_CONFIGS = {"paste": "bare"}

# ONE constant over BOTH corpora, and it is not tuned per corpus. Measured at this commit: the
# large corpus keeps rendered rows 0-570 (571 of 12,001 = 4.7579%, 12,277 B) and row 571 is the
# first one outside; the small corpus needs 8,621 B and so is kept WHOLE, which is what makes
# the small cell a level-ground comparison the reader has to win rather than a handicap match.
# Sized in the bar's §10.2 to fit the served window with margin; §7.10 states in advance that a
# larger window would give a larger paste and a smaller effect. Shrinking it is an AMENDMENT to
# the bar with its own date (§6 V-1), never a silent adjustment.
PASTE_MAX_BYTES = 12288

# The four MIRROR families above each map a calibration name to the headline config it copies,
# and every one of them exists to make a ladder step isolate ONE component. Resolving that here
# rather than inline in `run_task` is what makes the mapping checkable: the property that every
# mirrored name lands on a real config in CONFIGS is the whole reason `bare -> reader` and
# `bare -> paste` are one-component steps, and an arm that quietly resolved to itself would
# still behave identically today and stop being a mirror the moment a component keyed off a new
# name. GRAPH_CONFIGS is deliberately absent: its names resolve to THEMSELVES because the flag
# dict is looked up by the resolved name (`effective in GRAPH_CONFIGS`), which is a different
# mechanism wearing the same variable.
MIRROR_CONFIGS = (GUARD_CONFIGS, BUDGET_CONFIGS, READER_CONFIGS, PASTE_CONFIGS)


def effective_config(config: str) -> str:
    """The headline config a calibration-only name mirrors, or the name itself."""
    for family in MIRROR_CONFIGS:
        if config in family:
            return family[config]
    return config


# Every config name run_task accepts: the permanent matrix plus calibration-only ablations.
CONFIG_CHOICES = CONFIGS + sorted(
    (
        set(GRAPH_CONFIGS)
        | set(BUDGET_CONFIGS)
        | set(GUARD_CONFIGS)
        | set(READER_CONFIGS)
        | set(PASTE_CONFIGS)
    )
    - set(CONFIGS)
)


# ---- suite ----


@dataclass
class TaskResult:
    task: str
    config: str
    family: str
    passed: bool
    tokens: int
    outcome: str
    model_calls: int
    tool_calls: int
    schema_retries: int
    critique_rounds: int
    error: str | None
    # Trailing field: new JSONL columns are additive, old rows simply lack them.
    # None means no seed was applied (a client that has no `seed` attribute to pin).
    seed: int | None = None
    # Bar §8's accounting grain, added by M3.5 under the same trailing-field
    # convention: additive, defaulted, and nothing above is renumbered, reordered or
    # repurposed. `tokens` still means exactly what it meant.
    #
    # Columns 1-6 are read off `FileAccessGraph.accounting` — the ledger the harness
    # used to discard (bar §7.2) — and read 0 on every config that attaches no graph,
    # which is what "no graph was attached" looks like rather than a measurement.
    # Column 7 is counted in `TrackingClient.chat` below.
    #
    # `unrecorded_reader_calls` is NOT one of bar §8's seven. It is the carve-out that
    # makes column 1 honest: reads that returned the harness's `error:` convention are
    # counted as attempts and named here rather than silently missing from the
    # denominator (null-control §7.3). Ledger-sourced rates use
    # `reader_calls - unrecorded_reader_calls`. Recorded per bar §9/A4.
    reader_calls: int = 0
    unrecorded_reader_calls: int = 0
    repeat_reader_calls: int = 0
    collapsed_calls: int = 0
    collapsed_bytes: int = 0
    annotate_marker_bytes: int = 0
    query_bytes: int = 0
    context_bytes_sent: int = 0
    # RB-P38's fix, under the same trailing-field convention as `seed` above and the
    # eight accounting columns: additive, defaulted, nothing above renumbered. The
    # committed rows that predate it simply lack the key — backfilling them would be a
    # retro-edit of evidence.
    #
    # The value is read off the client the harness already holds, by duck typing and not
    # by signature, exactly as `seed` is. `None` means the client carries no model name,
    # which is what a fake or an in-process stub looks like; recording the CLI's
    # `--model` string instead would attribute a row to a model that never answered it.
    model: str | None = None
    # The repeat index, under the same trailing-field convention as `seed` above, the
    # eight accounting columns and RB-P38's `model`: additive, defaulted, nothing above
    # renumbered, reordered or repurposed. Rows that predate it simply lack the key —
    # backfilling them would be a retro-edit of evidence.
    #
    # `repeat` is the finest grain a row can be matched on across arms, and until now it
    # was only *recoverable*: `run_seed` is injective over the (task, repeat) domain, so
    # an analyst could invert the seed by brute force, which is exactly what
    # `docs/eval-data/2026-08-17-devteam-ladder-field-measurement.py`'s
    # `slots_are_repeat_indexed` does. That recovery costs the reader the model string and
    # a 66-hash loop, and it stops working the moment anything about the seed changes.
    # `run_task` is handed the number already; this records it instead of re-deriving it.
    # `run_seed` is untouched — the seed a row carries still means exactly what it meant,
    # and the recorded `repeat` is a witness that can be checked against it.
    repeat: int = 0


def request_wire_bytes(messages: list[Message], tools: list[Tool] | None) -> int:
    """Bytes of the transcript-and-roster half of one request, as the adapter serializes it.

    Mirrors `OpenAICompatible.chat`'s payload construction (`client.py:155-157`) key for
    key, minus the two fields a wrapper cannot see: `model` and `seed` live on the inner
    client and are per-run constants, so excluding them keeps this a function of the
    transcript — which is the quantity bar §8 column 7 exists to be a denominator for.
    """
    payload: dict = {"messages": [m.to_wire() for m in messages]}
    if tools:
        payload["tools"] = [t.to_wire() for t in tools]
    return len(json.dumps(payload).encode())


class TrackingClient:
    """Wraps any ModelClient and accumulates token usage and call count across all calls."""

    def __init__(self, inner: ModelClient):
        self.inner = inner
        self.usage = Usage()
        self.calls = 0
        # Bar §8 column 7. Accumulated here rather than at the adapter because the
        # transcript is re-sent whole on every call, so a byte that entered the context
        # once is paid for on every later request — and that re-send weighting is the
        # only thing that converts a byte share into a token share.
        self.context_bytes_sent = 0

    @property
    def _response_format_unsupported(self) -> bool:
        """Mirror the inner client's capability memo, live.

        Callers duck-type on this attribute, and they see the wrapper, not the
        wrapped client. Raising AttributeError when the inner has no memo is the
        point: `hasattr` then reads False and the wrapper is as transparent to the
        constrained-decoding tier as it already is to `seed`.
        """
        return self.inner._response_format_unsupported

    def chat(self, messages, tools=None, response_format=None):
        # Before the call, so a request that raises still counts the bytes it sent.
        self.context_bytes_sent += request_wire_bytes(messages, tools)
        # Forwarded only when asked for AND understood: fake clients whose chat()
        # takes two arguments must keep working, and they never carry the memo.
        if response_format is not None and hasattr(self.inner, "_response_format_unsupported"):
            resp = self.inner.chat(messages, tools, response_format=response_format)
        else:
            resp = self.inner.chat(messages, tools)
        self.usage = self.usage + resp.usage
        self.calls += 1
        return resp


def load_tasks(tasks_dir: Path | None = None) -> list[dict]:
    tasks_dir = tasks_dir or assets_root() / "evals" / "tasks"
    files = sorted(Path(tasks_dir).glob("*.yaml"))
    if not files:
        raise EvalConfigError(f"no task files found in {tasks_dir}")
    return [yaml.safe_load(f.read_text()) for f in files]


def contains_term(output: str, term: str) -> bool:
    """Case-insensitive match on word boundaries.

    A plain substring test scores wrong answers as passes: `100` is inside `1000`, `atlas`
    is inside `atlassian`. The guards are "no word character either side" rather than `\\b`,
    so terms that start or end with punctuation still anchor the way you would expect.
    Digit-comma adjacency is also blocked, so `200` does not match inside `1,200`.
    """
    pattern = rf"(?<!\d,)(?<!\w){re.escape(term)}(?!\w)(?!,\d)"
    return re.search(pattern, output, re.IGNORECASE) is not None


def score_output(task: dict, output: str, messages: list[Message]) -> bool:
    kind = task["scoring"]["kind"]
    expected = task["scoring"]["expected"]
    if kind == "json_equal":
        try:
            return extract_json(output) == expected
        except ValueError:
            return False
    if kind == "contains":
        return all(contains_term(output, str(s)) for s in expected)
    if kind == "tool_trace":
        trace = [tc.name for m in messages for tc in m.tool_calls]
        it = iter(trace)
        return all(name in it for name in expected)  # ordered subsequence
    raise ValueError(f"unknown scoring kind '{kind}'")


class EvalConfigError(BantamError):
    """A task and a config combine into something the harness cannot score."""


# ---- generated document fixtures (`document_setup:`) ----------------------------------
#
# `memory_setup:` is the precedent: a task declares facts, and `run_task` materialises them
# into a real per-run `workdir` before the agent starts. A document works the same way and
# for the same reason. It cannot use `workspace:` — that mapping holds `path -> str` and its
# `read_file` returns the string; an `.xlsx` is a zip archive, so it has no representation in
# that mapping and no reader can open it from there. Widening `workspace:` to carry bytes
# would give every file-nav task a second, silently different storage mode; putting the
# document on the filesystem where a reader expects it does not.
#
# The task declares a GENERATOR, not a file. The repository therefore gains no binary blob,
# and a corpus larger than the worker context window costs nothing to ship. The price is that
# a reader of the task YAML sees the SHAPE (how many rows, which columns, what value range,
# which cell holds the answer) but not the VALUES: those come out of the seed. That trade is
# taken deliberately — the alternative is a committed blob whose contents no diff can review
# either, plus a hand-written expected answer that drifts from it the first time the blob is
# regenerated. Here the expected answer is resolved by extracting the file that was just
# built, so the answer cannot disagree with the document by construction.


class DocumentSetupError(EvalConfigError):
    """A `document_setup:` declaration the harness cannot build.

    Raised at setup, BEFORE the agent runs, and left to ESCAPE `run_task` rather than caught
    into the `config-error` outcome that a missing `family` produces. A run that starts with no
    document and scores `wrong-answer` measures nothing at all and reports a defect in the
    declaration as a defect in the model; a `config-error` row is only marginally better,
    because `main()` prints its report and returns whatever the outcomes were — no outcome
    class moves the process exit status, so a suite whose corpus never got built still exits 0.
    A typo here is a hard failure, never a recorded non-measurement.
    """


DOCUMENT_SUFFIXES = ("xlsx", "docx")
DOCUMENT_COLUMN_KINDS = ("key", "choice", "int")

_ENTRY_KEYS = frozenset({"path", "seed", "sheets", "rows", "columns", "answers"})
_SHEET_KEYS = frozenset({"name", "rows", "columns"})
_COLUMN_KEYS = frozenset({"name", "kind", "prefix", "width", "values", "low", "high"})

# Every archive member is written with this timestamp and no compression. Both are
# byte-determinism requirements, not cosmetics. A zip member records an mtime, so the default
# `writestr(str, ...)` stamps *now* and the same declaration hashes differently on every run;
# `ZipInfo.create_system` additionally defaults to 3 on POSIX and 0 on Windows, which moves a
# byte across machines. Compression is left off because DEFLATE output is a function of the
# linked zlib, so a compressed fixture's hash would be pinned to a build of a C library rather
# than to the declaration. STORED costs disk in a temp dir and buys a hash that is a function
# of the declaration alone.
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

_CONTENT_TYPES = (
    '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
    'content-types"><Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
    'relationships+xml"/></Types>'
)
_ROOT_RELS_XLSX = (
    '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
    '2006/relationships"><Relationship Id="rIdWb" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    "</Relationships>"
)
_ROOT_RELS_DOCX = (
    '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
    '2006/relationships"><Relationship Id="rIdDoc" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)
_SHEET_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_REL_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
_WORD_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


@dataclass(frozen=True)
class DocumentFixture:
    """One materialised document. Sizes are MEASURED off the file that was just written."""

    name: str
    path: Path
    file_bytes: int
    sha256: str
    text_bytes: int
    row_counts: tuple[int, ...]
    answers: dict[str, str]

    @property
    def est_tokens(self) -> int:
        """Extracted bytes / 4, the estimator every other measurement in this repo uses.

        Off the EXTRACTED text, never `file_bytes`: `docread` measured the ratio between the
        two spanning 1660x across real files, so a budget taken from the file size is wrong
        by up to three orders of magnitude.
        """
        return self.text_bytes // 4


def _doc_field(seed: int, part: str, column: dict, index: int) -> str:
    """One cell, as a pure function of (seed, part, column, 1-based data row).

    SHA-256 rather than `random.Random`: the Mersenne stream is a CPython implementation
    detail, while the digest of a byte string is specified. A fixture whose values could move
    under an interpreter upgrade is not a fixture.
    """
    kind = column["kind"]
    if kind == "key":
        return f"{column.get('prefix', '')}{index:0{int(column.get('width', 6))}d}"
    digest = hashlib.sha256(f"{seed}|{part}|{column['name']}|{index}".encode()).digest()
    draw = int.from_bytes(digest[:8], "big")
    if kind == "choice":
        return str(column["values"][draw % len(column["values"])])
    return str(int(column["low"]) + draw % (int(column["high"]) - int(column["low"]) + 1))


def _xml_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _sheet_xml(seed: int, name: str, columns: list[dict], rows: int) -> str:
    """Row 1 is the header, so declared data row `i` is spreadsheet row `i + 1`.

    Every row from 1 to `rows + 1` is declared, with no gaps. That matters because `docread`
    does not materialise undeclared rows: only because this generator leaves none does a
    spreadsheet row number equal its rendered index + 1, which is what makes the `sheet!C4138`
    answer addresses below mean what a reader of the YAML assumes they mean.
    """
    out = []
    header = "".join(
        f'<c r="{_column_letter(c)}1" t="inlineStr"><is><t>{_xml_text(str(col["name"]))}'
        "</t></is></c>"
        for c, col in enumerate(columns)
    )
    out.append(f'<row r="1">{header}</row>')
    for i in range(1, rows + 1):
        r = i + 1
        cells = []
        for c, col in enumerate(columns):
            ref = f"{_column_letter(c)}{r}"
            value = _doc_field(seed, name, col, i)
            if col["kind"] == "int":
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                # inlineStr, not a shared-string table: a shared table would make every cell's
                # bytes depend on a global dedup ORDER, so byte-determinism would rest on the
                # stability of that ordering as well as on the seed. Inline keeps a row's bytes
                # a function of that row. `docread` reads both spellings (its trap 1 and 2).
                cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>{_xml_text(value)}</t></is></c>'
                )
        out.append(f'<row r="{r}">{"".join(cells)}</row>')
    return "".join(out)


def _xlsx_members(entry: dict) -> list[tuple[str, str]]:
    seed = int(entry["seed"])
    members = [("[Content_Types].xml", _CONTENT_TYPES), ("_rels/.rels", _ROOT_RELS_XLSX)]
    decls, rels = [], []
    for i, sheet in enumerate(entry["sheets"]):
        rid = f"rId{i + 1}"
        decls.append(f'<sheet name="{_xml_text(sheet["name"])}" sheetId="{i + 1}" r:id="{rid}"/>')
        rels.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
        )
        body = _sheet_xml(seed, sheet["name"], sheet["columns"], int(sheet["rows"]))
        members.append(
            (
                f"xl/worksheets/sheet{i + 1}.xml",
                f"<worksheet {_SHEET_NS}><sheetData>{body}</sheetData></worksheet>",
            )
        )
    members.append(
        (
            "xl/workbook.xml",
            f"<workbook {_SHEET_NS} {_REL_NS}><sheets>{''.join(decls)}</sheets></workbook>",
        )
    )
    members.append(
        (
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            f"relationships\">{''.join(rels)}</Relationships>",
        )
    )
    return members


def _docx_members(entry: dict) -> list[tuple[str, str]]:
    """One paragraph per row, fields joined by ", ".

    `docread` renders a `.docx` paragraph as a single field, so a `.docx` answer address can
    only be column A and resolves to the whole line. That is stated rather than worked around:
    a Word document has no columns and pretending otherwise would invent structure the reader
    cannot see.
    """
    seed = int(entry["seed"])
    columns = entry["columns"]
    lines = [", ".join(str(col["name"]) for col in columns)]
    for i in range(1, int(entry["rows"]) + 1):
        lines.append(", ".join(_doc_field(seed, "document", col, i) for col in columns))
    body = "".join(f"<w:p><w:r><w:t>{_xml_text(line)}</w:t></w:r></w:p>" for line in lines)
    return [
        ("[Content_Types].xml", _CONTENT_TYPES),
        ("_rels/.rels", _ROOT_RELS_DOCX),
        ("word/document.xml", f"<w:document {_WORD_NS}><w:body>{body}</w:body></w:document>"),
    ]


def build_document(entry: dict) -> bytes:
    """The file's bytes, as a pure function of the (already validated) declaration."""
    members = (
        _xlsx_members(entry) if str(entry["path"]).endswith(".xlsx") else _docx_members(entry)
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as archive:
        for name, payload in members:
            info = zipfile.ZipInfo(name, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, payload)
    return buf.getvalue()


def _fail(entry: object, message: str) -> None:
    where = entry.get("path", "<no path>") if isinstance(entry, dict) else entry
    raise DocumentSetupError(f"document_setup entry {where!r}: {message}")


def _check_column(entry: dict, where: str, column: object) -> None:
    if not isinstance(column, dict):
        _fail(entry, f"{where} column must be a mapping, got {type(column).__name__}")
    unknown = sorted(set(column) - _COLUMN_KEYS)
    if unknown:
        _fail(entry, f"{where} column has unknown keys {unknown}; known: {sorted(_COLUMN_KEYS)}")
    if not isinstance(column.get("name"), str) or not column["name"]:
        _fail(entry, f"{where} column needs a non-empty string 'name'")
    kind = column.get("kind")
    if kind not in DOCUMENT_COLUMN_KINDS:
        _fail(entry, f"{where} column {column['name']!r} has kind {kind!r}, "
              f"supported are {', '.join(DOCUMENT_COLUMN_KINDS)}")
    if kind == "choice":
        values = column.get("values")
        if not isinstance(values, list) or not values:
            _fail(
                entry,
                f"{where} column {column['name']!r} kind 'choice' needs a non-empty 'values'",
            )
    if kind == "int":
        try:
            low, high = int(column["low"]), int(column["high"])
        except (KeyError, TypeError, ValueError):
            _fail(entry, f"{where} column {column['name']!r} kind 'int' needs integer low/high")
        if low > high:
            _fail(entry, f"{where} column {column['name']!r} has low {low} > high {high}")


def _check_rows_and_columns(entry: dict, where: str, holder: dict) -> None:
    rows = holder.get("rows")
    if not isinstance(rows, int) or isinstance(rows, bool) or rows < 1:
        _fail(entry, f"{where} needs an integer 'rows' >= 1, got {rows!r}")
    columns = holder.get("columns")
    if not isinstance(columns, list) or not columns:
        _fail(entry, f"{where} needs a non-empty 'columns' list")
    for column in columns:
        _check_column(entry, where, column)


def validate_document_entry(entry: object) -> None:
    """Reject a declaration the generator cannot build, naming the key that is wrong.

    Unknown keys are an error rather than an ignored extra. A silently ignored `row:` for
    `rows:` builds a document of the wrong size and the run still scores, which is the exact
    failure mode this program has already been bitten by: a measurement that skipped what it
    was measuring and exited 0.
    """
    if not isinstance(entry, dict):
        _fail(entry, f"must be a mapping, got {type(entry).__name__}")
    unknown = sorted(set(entry) - _ENTRY_KEYS)
    if unknown:
        _fail(entry, f"unknown keys {unknown}; known: {sorted(_ENTRY_KEYS)}")
    path = entry.get("path")
    if not isinstance(path, str) or not path:
        _fail(entry, "needs a non-empty string 'path'")
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        _fail(entry, "'path' must be relative and must not escape the workdir")
    suffix = pure.suffix.lower().lstrip(".")
    if suffix not in DOCUMENT_SUFFIXES:
        _fail(entry, f"suffix {suffix or 'none'!r} is not readable; "
              f"supported are {', '.join(DOCUMENT_SUFFIXES)}")
    seed = entry.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        _fail(entry, f"needs an integer 'seed', got {seed!r}")
    if suffix == "xlsx":
        if "rows" in entry or "columns" in entry:
            _fail(entry, "an .xlsx declares 'sheets:', not top-level 'rows'/'columns'")
        sheets = entry.get("sheets")
        if not isinstance(sheets, list) or not sheets:
            _fail(entry, "needs a non-empty 'sheets' list")
        seen = set()
        for sheet in sheets:
            if not isinstance(sheet, dict):
                _fail(entry, f"sheet must be a mapping, got {type(sheet).__name__}")
            extra = sorted(set(sheet) - _SHEET_KEYS)
            if extra:
                _fail(entry, f"sheet has unknown keys {extra}; known: {sorted(_SHEET_KEYS)}")
            name = sheet.get("name")
            if not isinstance(name, str) or not name:
                _fail(entry, "every sheet needs a non-empty string 'name'")
            if name in seen:
                _fail(entry, f"duplicate sheet name {name!r}; `Document.part` resolves by name")
            seen.add(name)
            _check_rows_and_columns(entry, f"sheet {name!r}", sheet)
    else:
        if "sheets" in entry:
            _fail(entry, "a .docx declares top-level 'rows'/'columns', not 'sheets:'")
        _check_rows_and_columns(entry, "document", entry)
    answers = entry.get("answers") or {}
    if not isinstance(answers, dict):
        _fail(entry, f"'answers' must be a mapping of label -> 'part!CELL', got {answers!r}")
    for label, address in answers.items():
        if not isinstance(address, str) or "!" not in address:
            _fail(entry, f"answer {label!r} must be 'part!CELL', got {address!r}")


def _resolve_answer(doc: Document, entry: dict, label: str, address: str) -> str:
    """Read the answer OUT OF the document that was just built, never off the declaration.

    This is what stops the expected value and the corpus drifting apart: they cannot disagree,
    because one is a slice of the other. It also means an answer address that points past the
    end of the sheet is a setup failure rather than a silent empty string.
    """
    part_key, _, cell = address.partition("!")
    letters = "".join(c for c in cell if c.isalpha())
    digits = "".join(c for c in cell if c.isdigit())
    if not letters or not digits:
        _fail(entry, f"answer {label!r} address {address!r} is not a cell reference")
    try:
        part = doc.part(part_key)
    except DocumentReadError as exc:
        _fail(entry, f"answer {label!r}: {exc}")
    index = int(digits) - 1
    if not 0 <= index < part.row_count:
        _fail(entry, f"answer {label!r} names row {digits} but part {part.name!r} "
              f"renders {part.row_count} rows")
    column = 0
    for char in letters:
        column = column * 26 + (ord(char.upper()) - 64)
    fields = part.rows[index].split("\t")
    if not 0 < column <= len(fields):
        _fail(entry, f"answer {label!r} names column {letters} but row {digits} of "
              f"{part.name!r} has {len(fields)} fields")
    return fields[column - 1]


def document_dir(workdir: Path, task: dict, config: str) -> Path:
    """Per-task, per-config, under the run's `workdir` — the `memory_setup:` convention.

    Per config and not shared, for the same reason the memory store is per config: an arm that
    let the agent write to the document would otherwise hand the next arm a different corpus,
    and the comparison would stop being between configs. Nothing is deleted afterwards; the
    caller owns `workdir` (`run_suite` mkdtemps one), and a failed run whose document was
    cleaned up cannot be diagnosed.
    """
    return workdir / f"{task['name']}-{config}-docs"


def materialise_documents(task: dict, workdir: Path, config: str) -> list[DocumentFixture]:
    """Validate, build and write every `document_setup:` entry. Raises before the agent runs."""
    entries = task.get("document_setup") or []
    if not isinstance(entries, list):
        raise DocumentSetupError(
            f"task {task.get('name')!r}: document_setup must be a list, "
            f"got {type(entries).__name__}"
        )
    target = document_dir(workdir, task, config)
    fixtures = []
    for entry in entries:
        validate_document_entry(entry)
        path = target / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = build_document(entry)
        path.write_bytes(payload)
        doc = extract(path)
        fixtures.append(
            DocumentFixture(
                name=entry["path"],
                path=path,
                file_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                text_bytes=doc.text_bytes,
                row_counts=tuple(p.row_count for p in doc.parts),
                answers={
                    label: _resolve_answer(doc, entry, label, address)
                    for label, address in (entry.get("answers") or {}).items()
                },
            )
        )
    return fixtures


# ---- the reader pair the model actually sees (`document_list`, `document_read`) ---------
#
# TWO polymorphic tools, not five typed ones. Both `.xlsx` and `.docx` reduce to the same
# shape upstream — a `Document` of named `Part`s of rendered rows — so a `sheet_*` roster and
# a `docx_*` roster would be two spellings of one mechanism, and every request would carry
# both whichever kind the task actually holds. The roster is re-sent on every request, so
# that duplication is not paid once; `test_document_tools.py` prices the pair against a
# five-tool typed roster written out in full and asserts the gap in bytes.
#
# The pair is a DESCRIBER and a PAGER, and the split is what makes an over-window corpus
# readable at all. `document_list` answers "what exists" once — part names, row counts, row
# numbering, and the header / first / last row of each part. `document_read` answers "what is
# at offset N". Neither searches: no argument names a value to look for. That is deliberate
# and it is the boundary of what this job measures — a `find`-shaped argument is a FINDER
# primitive, a different axis, and adding one would make the result unable to say whether the
# reader bought anything. See `contract.document_manifest` for why the three sample rows are
# the load-bearing part.

DOCUMENT_PAGE_ROW_LIMIT = 50
DOCUMENT_PAGE_MAX_ROWS = 200
# Under `Agent.observation_budget` (4096 by default) with room for the header line, the
# continuation line and the per-row number prefixes this module adds after `page()` has
# sliced. The ceiling has to be the READER's, not the loop's: the loop cuts an over-budget
# observation IN BAND and the model then reads a page that lies about where it stopped,
# whereas `page()` stops on a row boundary and reports the shortfall out of band.
DOCUMENT_PAGE_MAX_BYTES = 3072


def _document_int(value: object, fallback: int) -> int:
    """A model's spelling of a number, bent to the argument the reader takes.

    `Agent.coerce_arguments` already turns `"50"` into `50` for a declared integer; what it
    cannot do is decide what an omitted or null argument means. Anything unconvertible is
    passed through as-is so the reader's own validation is what speaks.
    """
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return value  # type: ignore[return-value]


def _document_tools(fixtures: list[DocumentFixture]) -> list[ToolDef]:
    """The pair, bound to the documents this run materialised.

    Extraction happens once here rather than per call: `page()` slices an already-rendered
    `Document`, so a per-call `extract()` would re-parse 12,000 rows of XML on every read and
    price the tool by the corpus size. It re-extracts rather than reusing what
    `materialise_documents` parsed because `DocumentFixture` is a MEASUREMENT record — sizes
    and hashes of what was written — and hanging a live handle off it would make a row's
    provenance depend on whether a reader was attached.
    """
    docs: dict[str, Document] = {f.name: extract(f.path) for f in fixtures}
    default_document = next(iter(docs), "")

    def list_documents() -> str:
        return document_manifest(
            [
                {
                    "document": name,
                    "kind": doc.kind,
                    "index": part.index,
                    "part": part.name,
                    "row_count": part.row_count,
                    "rows": part.rows,
                }
                for name, doc in docs.items()
                for part in doc.parts
            ]
        )

    def read_document(
        document: str | None = None,
        part: str | None = None,
        offset: object = 0,
        limit: object = DOCUMENT_PAGE_ROW_LIMIT,
    ) -> str:
        name = document or default_document
        doc = docs.get(name)
        if doc is None:
            return document_unknown(name, sorted(docs))
        key: str | int = part if part else 0
        try:
            target = doc.part(key)
        except DocumentReadError as e:
            return document_error(e)  # names every part it does have
        start = _document_int(offset, 0)
        rows = _document_int(limit, DOCUMENT_PAGE_ROW_LIMIT)
        if isinstance(start, int) and start >= target.row_count:
            # `page()` would return an empty page with `next_offset=None`, which reads as
            # "the part ended here" — a dead end the model cannot tell from a real one.
            return document_offset_past_end(target.name, start, target.row_count)
        if isinstance(rows, int):
            rows = min(rows, DOCUMENT_PAGE_MAX_ROWS)
        try:
            got = page(doc, key, start, rows, DOCUMENT_PAGE_MAX_BYTES)
        except (DocumentReadError, TypeError) as e:
            return document_error(e)
        return document_page(
            document=name,
            part=got.part,
            offset=got.offset,
            rows=list(got.rows),
            row_count=got.total_rows,
            next_offset=got.next_offset,
            truncated_bytes=got.truncated_bytes,
        )

    return [
        ToolDef(tool=load_tool("document_list"), handler=list_documents),
        ToolDef(tool=load_tool("document_read"), handler=read_document),
    ]


def _paste_head(fixtures: list[DocumentFixture]) -> str:
    """The `paste` arm's system message: the head of the corpus, cut on a row boundary.

    The bar's §10.2, clause by clause. (1) The fixtures are the ones `run_task` materialised
    unconditionally, so this arm reads the same bytes every other arm does. (2) Each part is
    re-extracted and rendered as `docread` renders it — `Part.rows` is already header-then-rows
    and nothing here reformats a row. (3) Whole rows are added in declaration order while the
    running total, counting each row PLUS its newline, stays <= PASTE_MAX_BYTES; a row that
    would cross the ceiling stops the fill rather than being cut, because half a row is a value
    the model can misread as a whole one. (4) `document_paste` states the part name, the total
    and the shown count. (5) The caller registers no tools on this arm.

    The budget is one running total across every part in order, not a fresh ceiling per part,
    because PASTE_MAX_BYTES is a ceiling on what the SYSTEM PROMPT carries and a per-part
    ceiling would make a two-part task quietly pay twice. Every task in this bar's set declares
    one part, so the two readings agree on the committed corpus; the global one is the reading
    that stays honest if a later task does not. A part reached with the budget already spent is
    still announced with its true row count and zero rows shown — the model is told the part
    exists and is unreadable, which is the same honesty clause 4 asks for.
    """
    remaining = PASTE_MAX_BYTES
    entries = []
    for fixture in fixtures:
        doc = extract(fixture.path)
        for part in doc.parts:
            kept: list[str] = []
            for row in part.rows:
                cost = len(row.encode()) + 1
                if cost > remaining:
                    break
                remaining -= cost
                kept.append(row)
            entries.append(
                {
                    "document": fixture.name,
                    "kind": doc.kind,
                    "index": part.index,
                    "part": part.name,
                    "row_count": part.row_count,
                    "rows": kept,
                }
            )
    return document_paste(entries)


class SchemaGate:
    """Enforce a task schema on the agent's final answer, on structured()'s retry budget.

    Mirrors structured(): a violation is fed back as a pointed revision message rather than
    scored as a loss, so `full` and `structured` get the same number of shots at schema
    compliance and the config comparison measures the components, not the retry budget.
    """

    def __init__(self, schema: dict, max_attempts: int | None = None):
        self.schema = schema
        self.max_attempts = (
            max_attempts
            if max_attempts is not None
            else profile_default("schema_gate", "max_attempts")
        )
        self.retries_used = 0
        self._attempts = 0

    def setup(self, agent: Agent) -> None:
        self.retries_used = 0
        agent.add_post_hook(self)

    def __call__(self, task: str, output: str) -> str | None:
        error = schema_error(output, self.schema)
        if error is None:
            self._attempts = 0
            return None
        self._attempts += 1
        if self._attempts >= self.max_attempts:
            self._attempts = 0
            raise StructuredOutputError(
                f"no valid output after {self.max_attempts} attempts; last error: {error}"
            )
        self.retries_used += 1
        return schema_retry_feedback(error)


OUTCOMES = [
    "pass",
    "wrong-answer",
    "malformed-output",
    "schema-exhausted",
    "critique-exhausted",
    "turns-exhausted",
    "budget-exhausted",
    "config-error",
    "transport-error",
]


def classify_outcome(
    task: dict,
    passed: bool,
    output: str | None,
    error: BantamError | None,
    budget: TokenBudget | None = None,
) -> str:
    """One deterministic failure class per run (suite-hardening spec §3.2).

    Splits "failed" into content-wrong vs format-broken vs gate-gave-up vs
    infrastructure — each has a different remedy.
    """
    if passed:
        return "pass"
    if isinstance(error, EvalConfigError):
        return "config-error"
    if isinstance(error, StructuredOutputError):
        return "schema-exhausted"
    if isinstance(error, CritiqueExhausted):
        return "critique-exhausted"
    if isinstance(error, MaxTurnsExceeded):
        # Agent behaviour, not infrastructure. Before the generic branch below, which
        # would otherwise file turn exhaustion under `transport-error` and point the
        # diagnosis at the server (P7 — all 10 of the 3b sweep's "transport errors").
        return "turns-exhausted"
    if error is not None:
        return "transport-error"
    if budget is not None and budget.exhausted:
        # Reached only on a failed run, because `passed` is decided above by scoring the
        # answer the ceiling left behind — a budget-truncated but correct answer counts
        # `pass` (the P7 lesson: nothing swallows a scorable answer). Below the raised
        # classes on purpose: an exception explains itself better than the ceiling does.
        return "budget-exhausted"
    if task["scoring"]["kind"] == "json_equal":
        try:
            extract_json(output or "")
        except ValueError:
            return "malformed-output"
    return "wrong-answer"


def run_seed(model: str, task_name: str, repeat: int) -> int:
    """One deterministic sampling seed per (model, task, repeat).

    SHA-256 rather than Python's `hash()`, which is salted per process — a seed that
    changes between sweeps records nothing. Truncated to 32 bits, which every server
    accepts.

    **Config is deliberately excluded**: every config of a (task, repeat) shares one
    seed, so `bare` vs `graph` off-family is exact-equality-falsifiable again instead
    of paying a sampling-noise tax on the first call of each run (P9).
    """
    digest = hashlib.sha256(f"{model}\x1f{task_name}\x1f{repeat}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def _message_dict(message: Message) -> dict:
    """Exactly the `Message` fields, JSON-ready — the transcript is a post-hoc read, not a wire."""
    return {
        "role": message.role,
        "content": message.content,
        "tool_calls": [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in message.tool_calls
        ],
        "tool_call_id": message.tool_call_id,
    }


def _write_transcript(
    transcripts_dir: Path,
    result: TaskResult,
    repeat: int,
    output: str | None,
    messages: list[Message],
) -> None:
    """Dump one run's messages beside its scoring verdict.

    One file per run, `<config>--<task>--r<repeat>.json`, written on pass and on
    failure alike (the `structured` path has no agent transcript, so `messages` is
    `[]` there — the file still appears). Any write failure warns and returns:
    measurement must never change what it measures.
    """
    path = transcripts_dir / f"{result.config}--{result.task}--r{repeat}.json"
    payload = {
        "task": result.task,
        "config": result.config,
        "repeat": repeat,
        "passed": result.passed,
        "outcome": result.outcome,
        "seed": result.seed,
        # RB-P38 again: the transcript is the other thing a run writes, and its filename
        # is `<config>--<task>--r<repeat>.json` with no model in it, so two models writing
        # into one --transcripts directory collide. Carrying the key makes the file it
        # wrote self-describing; the collision itself is reported, not papered over.
        "model": result.model,
        "output": output,
        "messages": [_message_dict(m) for m in messages],
    }
    try:
        path.write_text(json.dumps(payload, indent=2))
    except (OSError, TypeError, ValueError) as e:
        print(f"warning: could not write transcript {path}: {e}", file=sys.stderr)


def run_task(
    client: ModelClient,
    task: dict,
    config: str,
    workdir: Path,
    transcripts_dir: Path | None = None,
    repeat: int = 0,
    profile: dict | None = None,
) -> TaskResult:
    # Applied by duck typing, not by signature: a client that carries a `seed` attribute
    # (OpenAICompatible does) gets this run's pinned seed; anything else is left alone and
    # records `seed: None`, because a seed the client ignored would be provenance fiction.
    # chat() is untouched either way.
    applied_seed: int | None = None
    if hasattr(client, "seed"):
        applied_seed = run_seed(getattr(client, "model", ""), task["name"], repeat)
        client.seed = applied_seed
    # RB-P38. Read, never written: the harness already holds the client that will answer,
    # so no call site gains an argument. Read here rather than at the row so it is the
    # model in force when the run started, and a client mutated mid-run cannot relabel it.
    answering_model: str | None = getattr(client, "model", None)

    def policy(section: str, key: str):
        """Explicit-wins profile threading (P6).

        `None` keeps every component resolving the `default` profile itself, so a run
        without `--eval-profile` is byte-identical to the one before the flag existed.
        """
        return None if profile is None else profile[section][key]

    # Calibration-only configs mirror a headline config exactly, plus one component.
    # Resolving the name here keeps every membership test below reading as it did;
    # `config` itself stays the label the TaskResult records.
    effective = effective_config(config)

    # Before the agent exists, and unconditional on `config`: a document is the task's
    # corpus, not a component under test, so every arm reads the same bytes — which the
    # generator makes literally true. A malformed declaration raises here rather than
    # letting the run start with no document and record a `wrong-answer` row, which would
    # report a defect in the task file as a defect in the model.
    document_fixtures = materialise_documents(task, workdir, config)
    tracking = TrackingClient(client)
    workspace_tools = _workspace_tools(task.get("workspace") or {})
    tools = [
        workspace_tools[name] if name in workspace_tools else BUILTIN_TOOLS[name]
        for name in task.get("tools", [])
    ]
    agent = Agent(
        client=tracking,
        tools=tools,
        max_turns=policy("agent", "max_turns"),
        observation_budget=policy("agent", "observation_budget"),
    )

    schema_gate: SchemaGate | None = None
    critique_gate: CritiqueGate | None = None
    budget: TokenBudget | None = None
    if config in BUDGET_CONFIGS:
        # Before every gate: `CritiqueGate.setup` reads `agent.budget` and `agent.client`
        # once, so a budget attached after it would be a governor nothing ever asks —
        # and would leave the gate holding the unwrapped client, invisible again.
        budget = TokenBudget(
            ceiling=policy("token_budget", "ceiling"),
            optional_cutoff=policy("token_budget", "optional_cutoff"),
        )
        agent.use(budget)
    memory_attached = False
    if effective in ("memory", "lean", "full") and task.get("memory_setup"):
        store_dir = workdir / f"{task['name']}-{config}-mem"
        store = MemoryStore(store_dir)
        for fact in task["memory_setup"]:
            store.save(fact["type"], fact["name"], fact["description"], fact["body"])
        agent.use(Memory(store=store_dir))
        memory_attached = True
    # `memory_setup:` gates the memory tools; `document_setup:` gates these, for the same
    # reason — a task with no corpus handed a reader would put two tools on the wire that
    # can only answer "no documents are attached to this task". The config side follows the
    # memory recipe too: the component's own arm, plus the two composed configs. `bare` gets
    # nothing and stays the floor.
    if document_fixtures and (config in READER_CONFIGS or effective in ("lean", "full")):
        for tooldef in _document_tools(document_fixtures):
            agent.register_tool(tooldef)
    # The `paste` arm, gated on `document_setup:` for the same reason: a paste of no corpus is
    # a system message that says nothing. It registers NO tool — the branch above cannot fire
    # for it, because `paste` is not in READER_CONFIGS and its `effective` is `bare` — so the
    # only difference between a `bare` row and a `paste` row is these bytes in the system
    # prompt, which is exactly the comparison the bar's §5 asks for.
    if document_fixtures and config in PASTE_CONFIGS:
        agent.add_system(_paste_head(document_fixtures))
    if effective in ("lean", "full") and "schema" in task:
        # The agent owns the loop here, so it needs the same instruction structured() gives.
        # Gate registered before the critique gate: a malformed answer is fixed for free
        # rather than spending a critique call on it.
        agent.add_system(schema_instruction(task["schema"]))
        # Tier 1 on the loop's own call, the same tier `structured` has always had.
        # It belongs here and not inside `SchemaGate`: a gate only ever sees a violation
        # that already happened, so a gate-owned decision could never constrain the first
        # decode — and on 3b that first decode is where the run was lost (RP1 wire capture:
        # all three POSTs of a schema-exhausted cell carried only `{model, messages, seed}`).
        agent.response_format = response_format_for(task["schema"])
        schema_gate = SchemaGate(task["schema"], max_attempts=policy("schema_gate", "max_attempts"))
        agent.use(schema_gate)
    if effective in ("memory", "lean", "full") and task["scoring"]["kind"] == "json_equal":
        # Registered after the schema gate on purpose: where a task has a schema, the
        # schema-aware error is strictly more informative, so this is the fallback for
        # json_equal tasks that carry no schema (every memory-recall task). `bare` does
        # not get it — it stays the floor.
        agent.use(JsonAnswerGate(max_attempts=policy("json_answer", "max_attempts")))
    # The gates take no explicit client: `CritiqueGate.setup` inherits `agent.client`,
    # which is the tracking client — wrapped by the budget in the `budgeted` config,
    # bare tracking everywhere else (identical to the `client=tracking` they used to be
    # handed). Inheriting is what puts critic spend in front of the governor.
    # `deterministic_sampling=True` on both gates below is this harness affirming what
    # the library will not assume for a consumer: that the endpoint reproduces a
    # verdict's *decision* — its score — for a fixed request under the seed pinned
    # above. Narrowed to the score and no wider, because that is what is measured
    # (RB-P15): the verdict text moved at an identical request payload sha, the score
    # never did. It is the harness's claim to make and it costs nothing new — every bar
    # here is already stated as a seeded number, and a run against a backend that
    # resamples has an unreproducible bar with or without the critic memo. A consumer
    # whose backend batches gets the safe default instead (RP5b;
    # `CritiqueGate._verdict`).
    if effective == "critique":
        critique_gate = CritiqueGate(
            "task-completion",
            max_rounds=policy("critique", "max_rounds"),
            deterministic_sampling=True,
        )
        agent.use(critique_gate)
    # RB-P8. A `memory_setup` task keeps its answer in a store; a config that attaches
    # no store hands the agent a question whose only source it withheld. That is the
    # deliberate control arm — `bare`, `critique` and `grounded` all run those tasks
    # storeless, which is how the memory component's uplift gets measured. What is not
    # deliberate is then asking a critic that verifies answers *against sources* to
    # bless one, because there is no source for it to check and refusing is the only
    # honest verdict it can reach. On 4b `grounded` that spent ten `critique-exhausted`
    # runs, three rounds each, on answers no round could ever have fixed.
    #
    # Composition, not library: `GroundedCritiqueGate` is behaving correctly, and a
    # library-side degrade ("pass when the evidence set is empty") would make every
    # consumer's grounded gate defeatable by calling no tools — the one thing it is
    # attached to prevent. The defect is that this recipe pairs a source-checking
    # critic with a task whose source it removed, so the recipe is what changes.
    #
    # Scoped to the measured cell on purpose. Toolless `structured-extraction` tasks
    # also reach the critic with an empty evidence set, but their source is the task
    # prompt itself, they burn no exhausted runs, and there is no finding to act on —
    # so they keep the gate. `full` never trips this, because a `memory_setup` task
    # under `full` always gets its store.
    source_withheld = bool(task.get("memory_setup")) and not memory_attached
    if effective in ("grounded", "full") and not source_withheld:
        critique_gate = GroundedCritiqueGate(
            max_rounds=policy("critique", "max_rounds"),
            evidence_budget=policy("critique", "evidence_budget"),
            deterministic_sampling=True,
        )
        agent.use(critique_gate)
    graph: FileAccessGraph | None = None
    if effective in GRAPH_CONFIGS and any(n in WORKSPACE_TOOLS for n in task.get("tools", [])):
        # `effective`, not `config`: `graph-guarded` gets exactly the headline graph.
        # Held in a local now: `run_task` used to construct the graph inside the `use(...)`
        # call and drop the only reference to it, which is why the realised repeat-read
        # count could not reach a JSONL row (bar §7.2) and a field program had to
        # monkey-patch the constructor to see it at all.
        graph = FileAccessGraph(readers={"read_file": "path"}, **GRAPH_CONFIGS[effective])
        agent.use(graph)
    if config in GUARD_CONFIGS:
        # Attached LAST on purpose: LoopGuard wraps only the tools registered by the
        # time its setup runs, and last means all of them — the memory tools, the
        # graph-wrapped readers, and the file_graph query tool alike.
        agent.use(
            LoopGuard(
                inject_at=policy("loop_guard", "inject_at"),
                warn_at=policy("loop_guard", "warn_at"),
            )
        )

    output: str | None = None
    messages: list[Message] = []
    caught: BantamError | None = None
    try:
        if "family" not in task:
            raise EvalConfigError(f"task '{task['name']}' is missing required key 'family'")
        if effective == "structured" and "schema" in task:
            # structured() drives its own loop, so no agent transcript exists to score against.
            if task["scoring"]["kind"] == "tool_trace":
                raise EvalConfigError(
                    f"task '{task['name']}' uses schema + tool_trace scoring, which the "
                    "structured config cannot score: it has no agent transcript"
                )
            data = structured(
                tracking,
                task["prompt"],
                task["schema"],
                max_retries=policy("structured", "max_retries"),
            )
            output = json.dumps(data)
        else:
            result = agent.run(task["prompt"])
            output, messages = result.output, result.messages
        passed = score_output(task, output, messages)
    except BantamError as e:
        passed, caught = False, e

    if effective == "structured" and "schema" in task:
        # No gate object on this path; structured() makes exactly one call per attempt.
        schema_retries = max(0, tracking.calls - 1)
    else:
        schema_retries = schema_gate.retries_used if schema_gate else 0
    # An all-zero accounting stands in for "no graph was attached", which is what a
    # `bare`/`lean`/`full` row means. It is not a measured zero and the bar's §5 R3 test
    # is only readable on a row whose config is in GRAPH_CONFIGS.
    accounting = graph.accounting if graph is not None else ReadAccounting()
    result = TaskResult(
        task=task["name"],
        config=config,
        family=task.get("family", "unknown"),
        passed=passed,
        tokens=tracking.usage.total,
        outcome=classify_outcome(task, passed, output, caught, budget),
        model_calls=tracking.calls,
        # messages stays [] when agent.run raises, so tool_calls reads 0 on gate-exhausted runs.
        tool_calls=sum(len(m.tool_calls) for m in messages),
        schema_retries=schema_retries,
        critique_rounds=critique_gate.rounds_used if critique_gate else 0,
        error=f"{type(caught).__name__}: {caught}" if caught else None,
        seed=applied_seed,
        reader_calls=accounting.reader_calls,
        unrecorded_reader_calls=accounting.unrecorded_reader_calls,
        repeat_reader_calls=accounting.repeat_reader_calls,
        collapsed_calls=accounting.collapsed_calls,
        collapsed_bytes=accounting.collapsed_bytes,
        annotate_marker_bytes=accounting.annotate_marker_bytes,
        query_bytes=accounting.query_bytes,
        context_bytes_sent=tracking.context_bytes_sent,
        model=answering_model,
        repeat=repeat,
    )
    if transcripts_dir is not None:
        # The run most worth reading used to record nothing: `agent.run` raising left
        # `messages` empty, so every turns-exhausted transcript was `messages: []`.
        # TaskResult.tool_calls above still reads the loop's own list, so the JSONL
        # columns keep their documented semantics this cycle — only the dump improves.
        _write_transcript(
            transcripts_dir, result, repeat, output, messages or getattr(caught, "messages", [])
        )
    return result


def run_suite(
    client: ModelClient,
    configs: list[str] | None = None,
    workdir: Path | None = None,
    tasks_dir: Path | None = None,
    repeats: int = 1,
    on_result: Callable[[TaskResult], None] | None = None,
    transcripts_dir: Path | None = None,
    profile: dict | None = None,
) -> list[TaskResult]:
    configs = configs or CONFIGS
    workdir = workdir or Path(tempfile.mkdtemp(prefix="bantamkit-eval-"))
    tasks = load_tasks(tasks_dir)
    results: list[TaskResult] = []
    for config in configs:
        for task in tasks:
            for i in range(repeats):
                # Fresh subdir per repeat: memory stores must not leak between repeats.
                result = run_task(
                    client,
                    task,
                    config,
                    workdir / f"repeat-{i}",
                    transcripts_dir=transcripts_dir,
                    repeat=i,
                    profile=profile,
                )
                results.append(result)
                if on_result is not None:
                    on_result(result)
    return results


def _score_cell(rows: list[TaskResult]) -> str:
    return f"{sum(r.passed for r in rows)}/{len(rows)}"


def format_report(results: list[TaskResult]) -> str:
    seen = {r.config for r in results}
    configs = [c for c in CONFIG_CHOICES if c in seen]
    configs += sorted(seen - set(CONFIG_CHOICES))  # never silently drop a result row
    lines = ["| config | score | tokens | score/1k tok |", "|---|---|---|---|"]
    for config in configs:
        rows = [r for r in results if r.config == config]
        passed, tokens = sum(r.passed for r in rows), sum(r.tokens for r in rows)
        per_1k = passed / (tokens / 1000) if tokens else 0.0
        lines.append(f"| {config} | {_score_cell(rows)} | {tokens} | {per_1k:.2f} |")

    families = sorted({r.family for r in results})
    if len(families) > 1:
        lines += [
            "",
            "Per family (score · tokens):",
            "| config | " + " | ".join(families) + " |",
            "|---" * (len(families) + 1) + "|",
        ]
        for config in configs:
            cells = []
            for family in families:
                rows = [r for r in results if r.config == config and r.family == family]
                cells.append(f"{_score_cell(rows)} · {sum(r.tokens for r in rows)} tok")
            lines.append(f"| {config} | " + " | ".join(cells) + " |")

    failed = [r for r in results if not r.passed]
    if failed:
        lines += ["", "Failure outcomes:"]
        for config in configs:
            counts = Counter(r.outcome for r in failed if r.config == config)
            if counts:
                summary = ", ".join(f"{o} ×{n}" for o, n in sorted(counts.items()))
                lines.append(f"- {config}: {summary}")

    if len(configs) > 1:
        lines += _rescue_matrix(results, configs)

    errors = [r for r in results if r.error]
    if errors:
        lines += ["", "Explicit failures:"]
        lines.extend(f"- {r.config}/{r.task}: {r.error}" for r in errors)
    return "\n".join(lines)


def _rescue_matrix(results: list[TaskResult], configs: list[str]) -> list[str]:
    """Pass-fraction grid over tasks some run failed.

    "Discriminating" = fully passed under at least one config AND fully failed
    under at least one — the tasks that actually separate configs. The count is
    the suite-quality headline the hardening cycle exists to move.
    """
    task_names = list(dict.fromkeys(r.task for r in results))
    grid: dict[str, dict[str, tuple[int, int]]] = {}
    for name in task_names:
        per_config = {}
        for config in configs:
            rows = [r for r in results if r.task == name and r.config == config]
            per_config[config] = (sum(r.passed for r in rows), len(rows))
        if any(p < n for p, n in per_config.values()):
            grid[name] = per_config
    if not grid:
        return ["", f"Discriminating tasks: 0/{len(task_names)}"]
    discriminating = sum(
        1
        for per_config in grid.values()
        if any(n > 0 and p == n for p, n in per_config.values())
        and any(n > 0 and p == 0 for p, n in per_config.values())
    )
    lines = [
        "",
        f"Discriminating tasks: {discriminating}/{len(task_names)}",
        "| task | " + " | ".join(configs) + " |",
        "|---" * (len(configs) + 1) + "|",
    ]
    for name, per_config in grid.items():
        cells = [f"{p}/{n}" for p, n in (per_config[c] for c in configs)]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the bantamkit eval suite.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--config", action="append", choices=CONFIG_CHOICES, help="repeatable; default: all configs"
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="per-request timeout in seconds (default 60)"
    )
    parser.add_argument("--repeats", type=int, default=1, help="runs per (config, task); default 1")
    parser.add_argument(
        "--tasks", type=Path, help="load tasks from this directory instead of the builtin suite"
    )
    parser.add_argument(
        "--json", type=Path, help="append one JSON line per finished run to this file"
    )
    parser.add_argument(
        "--transcripts",
        type=Path,
        help="dump one JSON transcript per finished run into this directory",
    )
    parser.add_argument(
        "--eval-profile",
        help="run under this named profile asset instead of `default` (e.g. `patient`)",
    )
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be >= 1")
    client = OpenAICompatible(base_url=args.base_url, model=args.model, timeout=args.timeout)

    sink: Callable[[TaskResult], None] | None = None
    jsonl = None
    if args.json:
        jsonl = args.json.open("a")

        def sink(result: TaskResult) -> None:
            jsonl.write(json.dumps(asdict(result)) + "\n")
            jsonl.flush()

    # Passed only when the flag is given, so callers (and fakes) that predate it keep working.
    suite_kwargs: dict = {}
    if args.transcripts:
        args.transcripts.mkdir(parents=True, exist_ok=True)
        suite_kwargs["transcripts_dir"] = args.transcripts
    if args.eval_profile:
        # Loaded (and validated) once here, then passed down as explicit constructor
        # args: profile *selection* is the harness's business, never global state that
        # the library reads. Core keeps resolving `default` for everyone else.
        suite_kwargs["profile"] = load_profile(args.eval_profile)

    try:
        results = run_suite(
            client,
            configs=args.config,
            tasks_dir=args.tasks,
            repeats=args.repeats,
            on_result=sink,
            **suite_kwargs,
        )
    finally:
        if jsonl is not None:
            jsonl.close()
    print(format_report(results))


if __name__ == "__main__":
    main()
