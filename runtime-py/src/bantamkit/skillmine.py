"""The experience miner (#206): pieces of work, their signature and their similarity.

Task 4a of `docs/superpowers/plans/2026-10-27-skills-from-experience.md` — the shiftwork
source (R1, R2, R6, R7) and the signature every source shares. Clustering, the X1 bars and
the proposals file come later (Task 5); the transcript source later still (Task 4b).

A **piece of work** from shiftwork is one unit's LAST clock-out line in a job's ledger
(`<checkpoint>.log.jsonl`), live under `<root>/.shiftwork/` or archived by #204's Retention
into `.shiftwork/archive/<job>.json.gz` (`{relpath: text | {"base64": ...}}`). An
`uncommitted` event for the unit takes back the clock-out it follows (shiftwork #162). A
ledger line that is not JSON, not an object, or not a clock-out (it carries an `event`, or
lacks a string `ts` or a known `status`) is skipped.

- `ok` (R2): `done` is a success, `blocked` a failure, `dropped` and `in_progress` neither.
- `prompt`: the unit's title, then `\\n` and the brief file's text when the brief is
  readable and inside the root (an archived brief is read from the bundle first). X4 lists
  shiftwork briefs as the orchestrator's words, so they may enter a piece.
- `paths`: the repo-relative paths the brief names that exist as regular files under the
  root at mining time (`_named_paths`); `.git/` and `.shiftwork/` are never named.
- `failure`: the newest history-ring entry for a unit that is not `done` (`outcome`, then
  `\\n` and `notes` when present).
- `repo` (R7): the realpath of the root's COMMON git dir — a linked worktree's `commondir`
  is followed — so the worktrees of one repository share one key; `""` outside a repo.

The **signature** is `tokenize_v2` keywords of the prompt (a term in more than half of the
source's pieces is dropped, then the `KEYWORDS_TOP` most frequent, ties in code-point
order), the tool-name n-grams for `NGRAM_SIZES`, and the touched paths. **Similarity** is a
weighted Jaccard over the three, each component whose union is empty left out of both sums,
answered as an exact reduced fraction `(num, den)`; `meets` compares on integers only, so the
two runtimes cannot disagree at the `SIM_MIN` boundary.

Read-only: nothing here writes anything. `runtime-ts/src/skillmine.ts` is the port;
`tools/conformance/suites/skill-miner.mjs` compares the two.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import re
import zlib
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bantamkit.memory.retrieval import tokenize_v2

SOURCE_SHIFTWORK = "shiftwork"
SOURCE_SESSION = "session"

KEYWORDS_TOP = 12
#: A term in more than KEYWORD_DF_MAX of a source's pieces is a corpus stop-word.
KEYWORD_DF_MAX = (1, 2)
NGRAM_SIZES = (2, 3)
SIM_WEIGHTS = (("keywords", 2), ("ngrams", 1), ("paths", 1))
SIM_MIN = (1, 2)

#: R2: the clock-out statuses and what each says about success.
_OK = {"done": True, "blocked": False, "dropped": None, "in_progress": None}
_UNCOMMITTED = "uncommitted"

_CHECKPOINT = re.compile(r"checkpoint(?:-([\s\S]+))?\.json")
_BUNDLE_CHECKPOINT = re.compile(r"\.shiftwork/(checkpoint(?:-[\s\S]+)?\.json)")
_ARCHIVE_SUFFIX = ".json.gz"
#: Separators around a path named in a brief: ASCII whitespace, quotes, brackets, punctuation.
#: Spelled out, never `\s`, whose meaning differs between Python and JavaScript.
_PATH_SPLIT = re.compile(r"[ \t\n\r\f\v`'\"()\[\]{}<>,;|*]+")
_NEVER_NAMED = (".git", ".shiftwork")


@dataclass(frozen=True)
class Piece:
    id: str
    source: str
    ts: str
    repo: str
    prompt: str
    tools: tuple[str, ...] = ()
    paths: frozenset[str] = frozenset()
    ok: bool | None = None
    signals: Mapping[str, bool] = field(default_factory=dict)
    failure: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "failure": self.failure,
            "id": self.id,
            "ok": self.ok,
            "paths": sorted(self.paths),
            "prompt": self.prompt,
            "repo": self.repo,
            "signals": {k: self.signals[k] for k in sorted(self.signals)},
            "source": self.source,
            "tools": list(self.tools),
            "ts": self.ts,
        }


@dataclass(frozen=True)
class Signature:
    keywords: frozenset[str]
    ngrams: frozenset[str]
    paths: frozenset[str]

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "keywords": sorted(self.keywords),
            "ngrams": sorted(self.ngrams),
            "paths": sorted(self.paths),
        }


# ------------------------------------------------------------------------------ reading


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def _load_json(text: str) -> Any:
    """`JSON.parse`'s rules: `NaN`/`Infinity` refused (retention's `_load_json`)."""
    return json.loads(text, parse_constant=_refuse_constant)


def _decode(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _read_text(p: str) -> str | None:
    try:
        with open(p, "rb") as fh:
            return _decode(fh.read())
    except (OSError, ValueError):
        return None


def _isfile(p: str) -> bool:
    try:
        return os.path.isfile(p)
    except (OSError, ValueError):
        return False


def _realpath(p: str) -> str | None:
    try:
        return os.path.realpath(p)
    except (OSError, ValueError):
        return None


def _inside(root_real: str, rel: str) -> str | None:
    """The realpath of `rel` under `root_real` when it is a regular file inside the root."""
    if not rel or rel.startswith("/") or "\\" in rel or ":" in rel:
        return None
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    real = _realpath(os.path.join(root_real, *parts))
    if real is None or not real.startswith(root_real + os.sep) or not _isfile(real):
        return None
    return real


def _named_paths(text: str, root_real: str) -> frozenset[str]:
    """Repo-relative paths `text` names that are regular files under the root now."""
    out: set[str] = set()
    for tok in _PATH_SPLIT.split(text):
        tok = tok.split(":", 1)[0].rstrip(".")  # `file.py:48`, a sentence's full stop
        while tok.startswith("./"):
            tok = tok[2:]
        if "/" not in tok and "." not in tok:
            continue
        if tok.split("/", 1)[0] in _NEVER_NAMED:
            continue
        if _inside(root_real, tok) is not None:
            out.add(tok)
    return frozenset(out)


def repo_key(root: str | Path) -> str:
    """R7: the realpath of `root`'s common git dir, or `""` when `root` is in no repository."""
    from bantamkit.touch.repo import find_repo

    repo = find_repo(str(root))
    if repo is None:
        return ""
    common = repo.gitdir
    raw = _read_text(os.path.join(common, "commondir"))
    if raw is not None and raw.split("\n", 1)[0].strip():
        rel = raw.split("\n", 1)[0].strip()
        common = rel if os.path.isabs(rel) else os.path.join(common, rel)
    return _realpath(common) or ""


def _clock_outs(ledger: str) -> dict[str, dict[str, Any]]:
    """unit -> its last clock-out line that still counts (R1)."""
    stacks: dict[str, list[dict[str, Any]]] = {}
    for line in ledger.split("\n"):
        try:
            rec = _load_json(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("unit"), str):
            continue
        unit = rec["unit"]
        if "event" in rec:
            if rec["event"] == _UNCOMMITTED and stacks.get(unit):
                stacks[unit].pop()
            continue
        status = rec.get("status")
        if not isinstance(status, str) or status not in _OK or not isinstance(rec.get("ts"), str):
            continue
        stacks.setdefault(unit, []).append(rec)
    return {u: s[-1] for u, s in stacks.items() if s}


def _job_name(file_name: str, doc: Any) -> str:
    """R6: `checkpoint-job72.json` -> `job72`; a plain `checkpoint.json` -> `job.id`.

    A plain checkpoint whose `job.id` is not a non-empty string is the job `checkpoint`.
    """
    m = _CHECKPOINT.fullmatch(file_name)
    if m is not None and m.group(1):
        return m.group(1)
    job = doc.get("job") if isinstance(doc, dict) else None
    jid = job.get("id") if isinstance(job, dict) else None
    return jid if isinstance(jid, str) and jid else "checkpoint"


def _failure(history: Any, unit: str) -> str | None:
    if not isinstance(history, list):
        return None
    for entry in reversed(history):
        if (
            isinstance(entry, dict)
            and entry.get("unit") == unit
            and isinstance(entry.get("outcome"), str)
        ):
            notes = entry.get("notes")
            return entry["outcome"] + ("\n" + notes if isinstance(notes, str) and notes else "")
    return None


def _job_pieces(
    file_name: str,
    checkpoint: str,
    ledger: str,
    bundle: Mapping[str, Any],
    root_real: str,
    repo: str,
) -> tuple[str, list[Piece]] | None:
    try:
        doc = _load_json(checkpoint)
    except ValueError:
        return None
    plan = doc.get("plan") if isinstance(doc, dict) else None
    units = plan.get("units") if isinstance(plan, dict) else None
    if not isinstance(units, list):
        return None
    job = _job_name(file_name, doc)
    outs = _clock_outs(ledger)
    pieces: list[Piece] = []
    seen: set[str] = set()
    for unit in units:
        if not isinstance(unit, dict):
            continue
        uid, title = unit.get("id"), unit.get("title")
        if not isinstance(uid, str) or not isinstance(title, str) or uid in seen or uid not in outs:
            continue
        seen.add(uid)
        rec = outs[uid]
        brief = _brief_text(unit.get("brief_path"), bundle, root_real)
        prompt = title if brief is None else title + "\n" + brief
        ok = _OK[rec["status"]]
        pieces.append(
            Piece(
                id=f"{job}/{uid}",
                source=SOURCE_SHIFTWORK,
                ts=rec["ts"],
                repo=repo,
                prompt=prompt,
                paths=_named_paths(brief, root_real) if brief is not None else frozenset(),
                ok=ok,
                failure=None if rec["status"] == "done" else _failure(doc.get("history"), uid),
            )
        )
    return job, pieces


def _brief_text(brief_path: Any, bundle: Mapping[str, Any], root_real: str) -> str | None:
    if not isinstance(brief_path, str):
        return None
    rel = brief_path
    while rel.startswith("./"):
        rel = rel[2:]
    held = bundle.get(rel)
    if isinstance(held, str):
        return held
    real = _inside(root_real, rel)
    return None if real is None else _read_text(real)


def _listdir(d: str) -> list[str]:
    try:
        return sorted(os.listdir(d))
    except (OSError, ValueError):
        return []


def shiftwork_pieces(root: str | Path) -> list[Piece]:
    """Every shiftwork piece of work under `<root>/.shiftwork/`, live and archived (R1).

    Sorted by `(ts, id)` in code-point order. A live job wins over an archive of the same
    job name; an unreadable checkpoint, ledger or archive yields nothing and never raises.
    """
    root_real = _realpath(str(root))
    if root_real is None:
        return []
    sw = os.path.join(root_real, ".shiftwork")
    repo = repo_key(root_real)
    by_job: dict[str, list[Piece]] = {}
    for name in _listdir(sw):
        if _CHECKPOINT.fullmatch(name) is None or not _isfile(os.path.join(sw, name)):
            continue
        checkpoint = _read_text(os.path.join(sw, name))
        ledger = _read_text(os.path.join(sw, name + ".log.jsonl"))
        if checkpoint is None or ledger is None:
            continue
        got = _job_pieces(name, checkpoint, ledger, {}, root_real, repo)
        if got is not None and got[0] not in by_job:
            by_job[got[0]] = got[1]
    archive = os.path.join(sw, "archive")
    for name in _listdir(archive):
        if not name.endswith(_ARCHIVE_SUFFIX) or not _isfile(os.path.join(archive, name)):
            continue
        bundle = _read_bundle(os.path.join(archive, name))
        if bundle is None:
            continue
        for rel in sorted(bundle):
            m = _BUNDLE_CHECKPOINT.fullmatch(rel)
            checkpoint, ledger = bundle[rel], bundle.get(rel + ".log.jsonl")
            if m is None or not isinstance(checkpoint, str) or not isinstance(ledger, str):
                continue
            got = _job_pieces(m.group(1), checkpoint, ledger, bundle, root_real, repo)
            if got is not None and got[0] not in by_job:
                by_job[got[0]] = got[1]
    pieces = [p for job in by_job.values() for p in job]
    pieces.sort(key=lambda p: (p.ts, p.id))
    return pieces


def _read_bundle(p: str) -> dict[str, Any] | None:
    try:
        with open(p, "rb") as fh:
            data = gzip.decompress(fh.read())
    except (OSError, EOFError, zlib.error, ValueError):
        return None
    text = _decode(data)
    if text is None:
        return None
    try:
        bundle = _load_json(text)
    except ValueError:
        return None
    return bundle if isinstance(bundle, dict) else None


# ---------------------------------------------------------------------------- signature


def doc_freq(pieces: Iterable[Piece]) -> tuple[Counter[str], int]:
    """Document frequency of every `tokenize_v2` term over one source's pieces, and their count."""
    df: Counter[str] = Counter()
    n = 0
    for p in pieces:
        n += 1
        df.update(set(tokenize_v2(p.prompt)))
    return df, n


def ngrams(tools: Iterable[str]) -> frozenset[str]:
    seq = list(tools)
    return frozenset(">".join(seq[i : i + k]) for k in NGRAM_SIZES for i in range(len(seq) - k + 1))


def signature(piece: Piece, df: Mapping[str, int], n: int) -> Signature:
    num, den = KEYWORD_DF_MAX
    counts = Counter(t for t in tokenize_v2(piece.prompt) if df.get(t, 0) * den <= n * num)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return Signature(
        keywords=frozenset(t for t, _ in ranked[:KEYWORDS_TOP]),
        ngrams=ngrams(piece.tools),
        paths=frozenset(piece.paths),
    )


def similarity(a: Signature, b: Signature) -> tuple[int, int]:
    """Weighted Jaccard as a reduced fraction; empty-union components count in neither sum."""
    num, den = 0, 1
    weight = 0
    for comp, w in SIM_WEIGHTS:
        x, y = getattr(a, comp), getattr(b, comp)
        union = len(x | y)
        if union == 0:
            continue
        weight += w
        # num/den + w*inter/union
        num, den = num * union + den * w * len(x & y), den * union
        g = math.gcd(num, den)
        num, den = num // g, den // g
    if weight == 0:
        return 0, 1
    den *= weight
    g = math.gcd(num, den)
    return num // g, den // g


def meets(sim: tuple[int, int]) -> bool:
    """`sim >= SIM_MIN`, cross-multiplied: integers only."""
    num, den = sim
    return den > 0 and num * SIM_MIN[1] >= den * SIM_MIN[0]
