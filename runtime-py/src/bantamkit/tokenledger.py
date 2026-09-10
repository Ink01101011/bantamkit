"""What a session ACTUALLY cost, read off the host's own transcripts -- on the surface.

`tools/ledger/token-ledger.mjs` has answered this question since PR 79 and it answers it well.
What it has never been is REACHABLE: it is a Node script an operator runs by hand, so the agent
that would act on the numbers cannot ask for them and `runtime-py` cannot ask at all. This
module is the half of that script that is worth serving, promoted to a function both runtimes
have (`docs/roadmap-agent-stack.md` AS-1(c)).

**Only the REAL half is promoted, and the split is the whole scope decision.** The script
reports four things: the API's `usage` block, tool calls by name, `tool_result` BYTES, and
repeated `Read`s. Only the first is measured -- the other three are bytes, and every token
figure derived from them is `bytes / 4` and labelled `est` where the script prints it. An
estimate served to a model through a tool is an estimate that will be quoted back as a fact, so
what crosses onto the surface here is the `usage` block and nothing else. The byte half stays
an operator script, where its label travels with it.

WHAT IT COUNTS, AND THE ONE CORRECTION IT MAKES OVER THE SCRIPT
--------------------------------------------------------------
The host writes one API response as SEVERAL assistant records -- a text block, a `tool_use`
block, more -- and every one of them carries the SAME `usage`. Summing records therefore
overcounts by the number of content blocks, which is why the count is per `requestId` and not
per line.

The script dedupes per FILE. That is not enough, and `tool-usage.mjs` already found out why
over the same corpus: **a resumed session rewrites earlier records verbatim into a new file**,
so one request is on disk twice under two paths and a per-file `seen` set counts it twice. Here
the dedupe is over the WHOLE walk, first occurrence wins, and every later copy is recorded as a
`duplicate-request` omission rather than dropped in silence. `requestId` is an API request id
and is unique across the corpus, which is what makes a global set the right shape.

EVERY LINE IS COUNTED OR OMITTED, AND THE TWO ADD UP
----------------------------------------------------
`skill_audit`'s discipline, applied to lines instead of files: `lines` equals `requests` plus
the sum of every omission's `count`, always. A reader can therefore tell "your transcripts hold
no usage" from "I skipped most of your transcripts", which a bare total cannot. `omissions` is
the more interesting half of a first run -- `not-an-assistant-record` dominates any real corpus,
because the host writes attachments, mode changes and titles into the same file.

An EMPTY line is not a record and is not counted anywhere. It is the trailing newline of the
file, and counting it would put a permanent off-by-one in the accounting identity above.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
**No time window.** The script has `--days N` and this has nothing. A tool whose answer depends
on the wall clock cannot be pinned by a conformance case that runs twice, and "the last 7 days"
is an operator's question about a live machine rather than a fact about a corpus. The caller
names `root`; what is under it is the answer.

**It does not know where the host keeps its transcripts.** `root` is the caller's, exactly as
`skill_audit`'s is, and for the same reason: a tool that reaches into `~/.claude` on its own
answers a different question on every machine and cannot be handed a fixture. The default lives
in the tool's description, not in this function.

THE PARITY HAZARDS, EACH PINNED
-------------------------------
- **Walk order.** `os.listdir` and `readdirSync` do not promise the same order, and the order
  decides which copy of a duplicated `requestId` is the one that counts. Every directory listing
  is sorted by name in CODE-POINT order before anything reads it.
- **Session order.** Sessions come out sorted by `first` timestamp AS A STRING, then by session
  id, both code-point. Never by parsed time: two runtimes' date parsers are two programs, and
  the host writes ISO-8601 with a `Z`, for which byte order already is time order.
- **The 2**53 ceiling.** A token total above `2**53-1` is exact in Python and rounded in
  JavaScript, so the running sum is checked BEFORE each addition -- `count > MAX_SAFE_INT -
  total`, which only ever subtracts two values the ceiling already holds -- and the scan refuses
  rather than answering a number one side got wrong. Same ruling as `pricing`'s cost ceiling.
- **`true` is not `1`.** `isinstance(True, int)` is true here and a JSON boolean is a boolean
  there, so a `usage` carrying `"output_tokens": true` would be 1 token on one side and
  malformed on the other. `_is_count` refuses it, which is `pricing._is_count`'s rule and the
  same measured hole.
- **A bare `Infinity`.** `json.loads` accepts the token and `JSON.parse` throws. The line
  decoder closes it, so a transcript carrying one is `unparsed-line` on both sides.

THE COST IS THE REFUSAL, AND THAT IS THE NORMAL ANSWER
------------------------------------------------------
`model` is optional and turns the four totals into money through `pricing`. `assets/pricing/
default.json` ships with NO rates on purpose, so for every model this answers
`{"unavailable": "no rate recorded for model ..."}` until an operator records one with its date
and its source. That is the default answer a user sees, not an error path -- it is the point of
AS-1(b), and this is the surface it was waiting for.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from bantamkit.client import BantamError
from bantamkit.pricing import (
    MAX_SAFE_INT,
    TOKEN_CLASSES,
    load_price_table,
    price_tokens,
)

#: Every omission subject, in the order they are reported. Fixed here rather than derived from
#: what a run happened to see, so two corpora produce comparable documents and a subject that
#: never fires is visibly absent rather than merely unmentioned.
OMIT_UNDECODABLE = "undecodable-file"
OMIT_UNPARSED = "unparsed-line"
OMIT_NOT_OBJECT = "not-an-object"
OMIT_NO_SESSION = "no-session-id"
OMIT_NOT_ASSISTANT = "not-an-assistant-record"
OMIT_NO_USAGE = "no-usage"
OMIT_MALFORMED_USAGE = "malformed-usage"
OMIT_NO_REQUEST_ID = "no-request-id"
OMIT_DUPLICATE_REQUEST = "duplicate-request"

OMISSION_ORDER = (
    OMIT_UNDECODABLE,
    OMIT_UNPARSED,
    OMIT_NOT_OBJECT,
    OMIT_NO_SESSION,
    OMIT_NOT_ASSISTANT,
    OMIT_NO_USAGE,
    OMIT_MALFORMED_USAGE,
    OMIT_NO_REQUEST_ID,
    OMIT_DUPLICATE_REQUEST,
)

#: The transcript extension the host writes. Anything else under `root` is not read and is not
#: counted -- it is not a transcript, so it is not an omission either.
TRANSCRIPT_SUFFIX = ".jsonl"


class TokenLedgerError(BantamError):
    """The scan could not be run at all: the message names what was wrong with the request.

    Reserved for a failure of the SCAN, exactly as `SkillAuditError` is. A file that will not
    decode, a line that will not parse and a record with no usage are omissions and are counted;
    a ledger that refused because one of eight hundred transcripts is truncated would have told
    the operator nothing about the other seven hundred and ninety-nine.
    """


def _reject_constant(name: str) -> float:
    raise ValueError(name)


def _decode_line(text: str) -> object:
    """One transcript line, decoded the way `JSON.parse` decodes it.

    `parse_constant` closes CPython's non-standard extension in the same place and for the same
    reason `pricing.decode_price_json` does: `json.loads` accepts the bare tokens `NaN`,
    `Infinity` and `-Infinity` and `JSON.parse` rejects them, so without this a transcript
    carrying one is a counted record here and an `unparsed-line` there.
    """
    return json.loads(text, parse_constant=_reject_constant)


def _is_count(value: object) -> bool:
    """A non-negative integer below `2**53` both runtimes hold exactly, however JSON spelled it.

    `pricing._is_count`'s rule, restated here because it is this module's rule too and the
    two hold the same two measured holes: `True` is an `int` in Python and a boolean in Node,
    and `json.loads('7.0')` is a float here and indistinguishable from `7` there.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= MAX_SAFE_INT
    if isinstance(value, float):
        return value.is_integer() and 0 <= value <= MAX_SAFE_INT
    return False


@dataclass(frozen=True)
class Omission:
    """A line that was read and not counted, as a COUNT and one place to go look.

    - `subject` -- one of the `OMIT_*` tokens.
    - `count` -- how many lines. Never an estimate.
    - `what` -- the FIRST site, `<relpath>:<1-based line>`, plus `and N more` when there are
      more. Bounded on purpose: a real corpus omits tens of thousands of lines as
      `not-an-assistant-record`, and a tool that listed them all would hand a model a megabyte
      of paths in place of an answer.
    """

    subject: str
    count: int
    what: str = ""

    def as_dict(self) -> dict:
        return {"subject": self.subject, "count": self.count, "what": self.what}


@dataclass(frozen=True)
class Session:
    """One session's real usage. `requests` is distinct `requestId`s, never lines."""

    session: str
    cwd: str
    first: str
    last: str
    requests: int
    sidechain_requests: int
    tokens: dict

    def as_dict(self) -> dict:
        doc = {
            "session": self.session,
            "cwd": self.cwd,
            "first": self.first,
            "last": self.last,
            "requests": self.requests,
            "sidechain_requests": self.sidechain_requests,
        }
        for cls in TOKEN_CLASSES:
            doc[cls] = self.tokens[cls]
        return doc


@dataclass(frozen=True)
class Ledger:
    """The whole answer. `lines` equals `requests` plus every omission's `count`."""

    root: str
    transcripts: int
    lines: int
    requests: int
    totals: dict
    sessions: tuple[Session, ...] = ()
    omissions: tuple[Omission, ...] = ()
    cost: dict | None = None

    def as_dict(self) -> dict:
        doc: dict = {
            "root": self.root,
            "transcripts": self.transcripts,
            "lines": self.lines,
            "requests": self.requests,
            "totals": {cls: self.totals[cls] for cls in TOKEN_CLASSES},
            "sessions": [s.as_dict() for s in self.sessions],
            "omissions": [o.as_dict() for o in self.omissions],
        }
        if self.cost is not None:
            doc["cost"] = self.cost
        return doc

    def as_json(self) -> str:
        """Two-space indent and no ASCII escaping, so `JSON.stringify(doc, null, 2)` in the
        port produces the same bytes and a conformance case can compare them."""
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False)


@dataclass
class _Accumulator:
    """One session while the walk is still running."""

    session: str
    cwd: str = ""
    first: str = ""
    last: str = ""
    requests: int = 0
    sidechain_requests: int = 0
    tokens: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.tokens is None:
            self.tokens = {cls: 0 for cls in TOKEN_CLASSES}


def _walk(base: Path) -> list[tuple[Path, str]]:
    """Every `*.jsonl` under `base`, in one deterministic order, each with the name it is called by.

    Sorted by entry NAME in code-point order at every level, directories and files in the same
    listing, so the sequence is a property of the tree and not of the filesystem. It has to be:
    the walk order decides which copy of a duplicated `requestId` is the one that counts, so an
    unsorted walk would make the ANSWER depend on inode order.

    The relative name is BUILT during the descent -- `'/'.join(names)` -- rather than derived
    afterwards from the two paths. `Path('./x')` normalises to `x` here and `path.join('a//b',
    'c')` normalises in the port, and neither normalisation is the other's; carrying the name
    down means the string a caller reads in `omissions[].what` never passed through either.
    """
    found: list[tuple[Path, str]] = []

    def visit(directory: Path, prefix: str) -> None:
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            return
        for name in names:
            child = directory / name
            rel = f"{prefix}{name}"
            if child.is_dir():
                visit(child, f"{rel}/")
            elif name.endswith(TRANSCRIPT_SUFFIX):
                found.append((child, rel))

    visit(base, "")
    return found


def _usage_of(record: dict) -> object:
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    return message.get("usage")


def read(
    root: str | Path,
    model: str | None = None,
    prices: str | None = None,
) -> Ledger:
    """Walk `root` and answer the ledger.

    An empty `root` is refused rather than resolved, the same refusal `skill_audit` makes and
    for the same measured reason: `Path("")` is `Path(".")` here and `statSync('')` throws in
    the port, so the two runtimes would answer a CWD-relative ledger and a refusal for one
    input.

    `model` omitted is not `model` empty. An absent model asks for no cost and gets no `cost`
    key at all; an empty string names no model and is refused, because it would otherwise be
    looked up in the rate table and reported as "no rate recorded for model ''", which reads
    like a missing price rather than a missing argument.
    """
    if str(root) == "":
        raise TokenLedgerError(
            "root must not be empty; name the directory of transcripts to read"
        )
    if model is not None and model == "":
        raise TokenLedgerError("model must not be empty; name the model to price, or omit it")
    base = Path(root)
    if not base.exists():
        raise TokenLedgerError(f"no such directory: {root}")
    if not base.is_dir():
        raise TokenLedgerError(f"{root} is a file, not a directory of transcripts")

    files = _walk(base)
    sessions: dict[str, _Accumulator] = {}
    omissions: dict[str, list] = {subject: [0, ""] for subject in OMISSION_ORDER}
    totals = {cls: 0 for cls in TOKEN_CLASSES}
    seen_requests: set[str] = set()
    lines = 0

    def omit(subject: str, site: str) -> None:
        entry = omissions[subject]
        if entry[0] == 0:
            entry[1] = site
        entry[0] += 1

    for path, relpath in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # The file exists and is a transcript by name; it is one line of nothing anyone can
            # read. Counted as ONE omission and not as N, because N is not knowable.
            lines += 1
            omit(OMIT_UNDECODABLE, f"{relpath}:1")
            continue
        for index, line in enumerate(text.split("\n")):
            if line == "":
                # Not a record. The last one is the file's trailing newline; counting it would
                # put a permanent off-by-one in `lines == requests + sum(counts)`.
                continue
            lines += 1
            site = f"{relpath}:{index + 1}"
            try:
                record = _decode_line(line)
            except ValueError:
                omit(OMIT_UNPARSED, site)
                continue
            if not isinstance(record, dict):
                omit(OMIT_NOT_OBJECT, site)
                continue
            session_id = record.get("sessionId")
            if not isinstance(session_id, str) or session_id == "":
                omit(OMIT_NO_SESSION, site)
                continue
            if record.get("type") != "assistant":
                omit(OMIT_NOT_ASSISTANT, site)
                continue
            usage = _usage_of(record)
            if usage is None:
                omit(OMIT_NO_USAGE, site)
                continue
            if not isinstance(usage, dict) or not all(
                _is_count(usage.get(cls)) for cls in TOKEN_CLASSES
            ):
                # A real `usage` also carries `service_tier`, `iterations` and friends. Those
                # are the host's and are ignored; what is required is that all FOUR classes
                # this ledger reports are present and are counts. A class silently defaulted
                # to zero is a token silently invented, which is `pricing`'s rule about money
                # applied one layer earlier.
                omit(OMIT_MALFORMED_USAGE, site)
                continue
            request_id = record.get("requestId")
            if not isinstance(request_id, str) or request_id == "":
                omit(OMIT_NO_REQUEST_ID, site)
                continue
            if request_id in seen_requests:
                omit(OMIT_DUPLICATE_REQUEST, site)
                continue
            seen_requests.add(request_id)

            acc = sessions.get(session_id)
            if acc is None:
                acc = _Accumulator(session_id)
                sessions[session_id] = acc
            cwd = record.get("cwd")
            if acc.cwd == "" and isinstance(cwd, str):
                acc.cwd = cwd
            stamp = record.get("timestamp")
            if isinstance(stamp, str) and stamp != "":
                if acc.first == "" or stamp < acc.first:
                    acc.first = stamp
                if stamp > acc.last:
                    acc.last = stamp
            acc.requests += 1
            if record.get("isSidechain") is True:
                acc.sidechain_requests += 1
            for cls in TOKEN_CLASSES:
                count = int(usage[cls])
                # BEFORE the addition, and phrased as a subtraction of two values the ceiling
                # already holds -- `total + count` above 2**53 is rounded by a JS `number`, so
                # a check written after the fact would be comparing a number one side already
                # got wrong.
                if count > MAX_SAFE_INT - totals[cls]:
                    raise TokenLedgerError(
                        f"{cls} total exceeds 2**53-1, which is the largest integer both "
                        f"runtimes represent exactly"
                    )
                acc.tokens[cls] += count
                totals[cls] += count

    ordered = sorted(sessions.values(), key=lambda a: (a.first, a.session))
    records = tuple(
        Omission(subject, omissions[subject][0], _what(omissions[subject]))
        for subject in OMISSION_ORDER
        if omissions[subject][0] > 0
    )

    cost = None
    if model is not None:
        cost = price_tokens(load_price_table(prices), model, dict(totals))

    return Ledger(
        root=str(root),
        transcripts=len(files),
        lines=lines,
        requests=len(seen_requests),
        totals=totals,
        sessions=tuple(
            Session(
                session=a.session,
                cwd=a.cwd,
                first=a.first,
                last=a.last,
                requests=a.requests,
                sidechain_requests=a.sidechain_requests,
                tokens=a.tokens,
            )
            for a in ordered
        ),
        omissions=records,
        cost=cost,
    )


def _what(entry: list) -> str:
    """`<relpath>:<line>` for the first site, plus `and N more` when there are more."""
    count, site = entry[0], entry[1]
    if count <= 1:
        return site
    return f"{site} and {count - 1} more"
