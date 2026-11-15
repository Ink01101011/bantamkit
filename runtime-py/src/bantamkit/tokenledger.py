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
- **A leading UTF-8 BOM** (#150). `read_text(encoding="utf-8")` keeps U+FEFF and `json.loads`
  refuses it, while a default `TextDecoder` strips it from the FIRST line only. The port decodes
  with `ignoreBOM: true`, so a BOM is `unparsed-line` on both sides, on any line. Tolerating it
  instead was the other choice and was not taken: the host never writes one, RFC 8259 forbids
  adding one, and a line that is not what the host writes is exactly what an omission names.
- **Directory symlinks** (#151). `Path.is_dir()` and `statSync` both FOLLOW a link, so a link
  to an ancestor was walked until the OS refused it (ELOOP, ~32 levels on macOS) and the one
  transcript beneath it was counted once per level. A symlinked directory is now neither
  descended into nor read, on both sides -- `skill_audit`'s rule (`os.walk`'s
  `followlinks=False`). A symlink to a FILE is still read: it cannot loop.

THE COST IS THE REFUSAL, AND THAT IS THE NORMAL ANSWER
------------------------------------------------------
`model` is optional and turns the four totals into money through `pricing`. `assets/pricing/
default.json` ships with NO rates on purpose, so for every model this answers
`{"unavailable": "no rate recorded for model ..."}` until an operator records one with its date
and its source. That is the default answer a user sees, not an error path -- it is the point of
AS-1(b), and this is the surface it was waiting for.

**Generated, not hand-written (#316 G2, J88-2).** The walk, every omission rule and the ceiling
are `bantamkit/_generated/tokenledger.py`, compiled from `runtime-ts/src/tokenledger.ts` by
`tools/ts2py` (`docs/porting.md`, *Generated modules*; do not edit it, regenerate it), so both
runtimes run one source and `tools/conformance/suites/tokenledger.mjs` compares them. This
module keeps the public surface the hand-written one had (shim conveniences, listed in
`docs/porting.md`): `read(root, model=None, prices=None)` answers the frozen `Ledger` /
`Session` / `Omission` dataclasses (a `Path` root or prices path is used as `str()`), the
`OMIT_*` constants, `OMISSION_ORDER` and `TOKEN_CLASSES` as tuples, `TokenLedgerError` (the
generated class, a `bantamkit.client.BantamError`), and `_walk(base)` as `(Path, relpath)` pairs.
`Ledger.as_json()` is the TypeScript's `asJson` (`JSON.stringify(doc, null, 2)`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bantamkit._generated import tokenledger as _generated
from bantamkit._generated._ts2py_runtime import _js_py_value
from bantamkit._generated.tokenledger import (
    OMIT_DUPLICATE_REQUEST,
    OMIT_MALFORMED_USAGE,
    OMIT_NO_REQUEST_ID,
    OMIT_NO_SESSION,
    OMIT_NO_USAGE,
    OMIT_NOT_ASSISTANT,
    OMIT_NOT_OBJECT,
    OMIT_UNDECODABLE,
    OMIT_UNPARSED,
    TRANSCRIPT_SUFFIX,
    TokenLedgerError,
)
from bantamkit.pricing import MAX_SAFE_INT, TOKEN_CLASSES

__all__ = [
    "MAX_SAFE_INT",
    "OMISSION_ORDER",
    "OMIT_DUPLICATE_REQUEST",
    "OMIT_MALFORMED_USAGE",
    "OMIT_NOT_ASSISTANT",
    "OMIT_NOT_OBJECT",
    "OMIT_NO_REQUEST_ID",
    "OMIT_NO_SESSION",
    "OMIT_NO_USAGE",
    "OMIT_UNDECODABLE",
    "OMIT_UNPARSED",
    "TOKEN_CLASSES",
    "TRANSCRIPT_SUFFIX",
    "Ledger",
    "Omission",
    "Session",
    "TokenLedgerError",
    "read",
]

OMISSION_ORDER = tuple(_generated.OMISSION_ORDER)


@dataclass(frozen=True)
class Omission:
    """A line that was read and not counted, as a COUNT and one place to go look."""

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
        """`asJson`: `JSON.stringify(doc, null, 2)`, the bytes the port prints. `as_dict()` is a
        ledger-shaped document itself, so the generated `asDict` reads it back unchanged."""
        return _generated.as_json(self.as_dict())


def _walk(base: Path | str) -> list[tuple[Path, str]]:
    """Every `*.jsonl` under `base`, in one deterministic order, each with its relative name."""
    return [(Path(path), rel) for path, rel in _generated.walk(str(base))]


def read(
    root: str | Path,
    model: str | None = None,
    prices: str | Path | None = None,
) -> Ledger:
    """Walk `root` and answer the ledger (`runtime-ts/src/tokenledger.ts`'s `read`)."""
    js = _generated.read(
        str(root), {"model": model, "prices": None if prices is None else str(prices)}
    )
    sessions = tuple(
        Session(
            session=s["session"],
            cwd=s["cwd"],
            first=s["first"],
            last=s["last"],
            requests=s["requests"],
            sidechain_requests=s["sidechain_requests"],
            tokens={cls: s[cls] for cls in TOKEN_CLASSES},
        )
        for s in js["sessions"]
    )
    omissions = tuple(Omission(o["subject"], o["count"], o["what"]) for o in js["omissions"])
    cost = js.get("cost")
    return Ledger(
        root=js["root"],
        transcripts=js["transcripts"],
        lines=js["lines"],
        requests=js["requests"],
        totals=dict(js["totals"]),
        sessions=sessions,
        omissions=omissions,
        cost=None if cost is None else _js_py_value(cost),
    )
