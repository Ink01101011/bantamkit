"""The experience miner (#206): pieces of work, their signature, clusters and proposals.

Task 4a of `docs/superpowers/plans/2026-10-27-skills-from-experience.md` — the shiftwork
source (R1, R2, R6, R7) and the signature every source shares; Task 5 — clustering, the X1
bars and the proposals file; Task 4b — the transcript source (below, "sessions").

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

**Clusters** (Task 5): leader clustering per source, the X1 bars on successful members only,
twice the bar for the installer, recurring steps, pitfalls from failed members, and the X3
level from the repo keys. `proposals` turns them into the `skill-proposals.json` document,
carrying identity, status and rejection memory from the previous document; only
`write_proposals` writes, temp-then-rename under the storage lock.

**Sessions** (Task 4b): a piece is one user turn of a Claude Code transcript — a prompt (R3:
a `type: "user"` record that is not `isMeta`, not `isCompactSummary`, carries no
`toolUseResult`, is not `isSidechain` and is not under `subagents/`; its string content or its
`text` blocks, with every `CUT_TAGS` span cut out) through the record before the next prompt,
holding at least one `tool_use`. X4 is held by construction: the only facts read from a tool
result are which call it answers and its `is_error` flag; the agent's tool names, the file
arguments of Read/Edit/Write and a Bash command's text (matched, never stored) are structure.
The signals (R5): `commit`, `tests` (the LAST test run in the turn), `uncorrected` (Q1's word
list, or the interrupt marker; a last turn has none). The `MinerCache` keeps each transcript's
offset and open turn, so an unchanged file is not read and a grown one is read from where the
last run stopped. Measured shapes (job73 C6 Step 0) added `bash-*`, `task-notification` and
`local-command-caveat` to the cut list: a `!` command's output and a background task's result
arrive as non-meta user records.

`runtime-ts/src/skillmine.ts` is the port;
`tools/conformance/suites/skill-miner.mjs` compares the two.
"""

from __future__ import annotations

import gzip
import hashlib
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
    #: The subjects of the turn's successful `git commit`s, each the first line of its `-m`
    #: argument (R4: the agent's input, never the command's output). Sessions only.
    commits: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "commits": list(self.commits),
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


# ------------------------------------------------------------------ clusters (Task 5)

#: X1: successful repeats a cluster needs before it is proposed, per source.
SHIFTWORK_BAR = 3
SESSION_BAR = 5
#: The installer acts on twice the X1 repeats.
AUTO_FACTOR = 2
#: At most this many clusters are offered (`pending`) at once.
PENDING_MAX = 3
#: A rejected cluster is offered again once its successes reach this multiple of `rejected_at`.
REJECT_FACTOR = 2
#: An n-gram in at least this share of a cluster's successful members is a recurring step.
STEP_SHARE = (1, 2)

PROPOSALS_NAME = "skill-proposals.json"
PROPOSALS_VERSION = 1
LEVEL_PROJECT = "project"
LEVEL_USER = "user"
STATUSES = ("new", "pending", "drafted", "installed", "rejected", "failed")
_BARS = {SOURCE_SHIFTWORK: SHIFTWORK_BAR, SOURCE_SESSION: SESSION_BAR}
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


class ProposalsError(Exception):
    """`skill-proposals.json` exists and is not a version-1 proposals document."""


@dataclass(frozen=True)
class Cluster:
    id: str
    source: str
    members: tuple[Piece, ...]
    successes: int
    bar: int
    auto_bar: int
    keywords: tuple[str, ...]
    steps: tuple[str, ...]
    pitfalls: tuple[tuple[str, str | None], ...]
    evidence: tuple[str, ...]
    repos: tuple[str, ...]
    level: str
    top: str | None


def _utf8(text: str) -> bytes:
    """UTF-8 with a lone surrogate as U+FFFD: what Node's `Buffer.from(text)` encodes."""
    return _LONE_SURROGATE.sub("\ufffd", text).encode("utf-8")


def _sha16(text: str) -> str:
    return hashlib.sha256(_utf8(text)).hexdigest()[:16]


def _ngram_seq(tools: tuple[str, ...]) -> list[str]:
    """The tool n-grams in order of appearance: by start position, then by size."""
    out: list[str] = []
    for i in range(len(tools)):
        for k in NGRAM_SIZES:
            if i + k <= len(tools):
                out.append(">".join(tools[i : i + k]))
    return out


def _make_cluster(source: str, members: list[Piece], sigs: list[Signature]) -> Cluster:
    ok = [i for i, p in enumerate(members) if p.ok is True]
    successes = len(ok)
    bar = _BARS[source]
    kw: Counter[str] = Counter()
    share: Counter[str] = Counter()
    for i in ok:
        kw.update(sigs[i].keywords)
        share.update(sigs[i].ngrams)
    ranked = sorted(kw.items(), key=lambda kv: (-kv[1], kv[0]))
    num, den = STEP_SHARE
    steps: list[str] = []
    for i in ok:
        for g in _ngram_seq(members[i].tools):
            if g not in steps and share[g] * den >= successes * num:
                steps.append(g)
    keys = {members[i].repo for i in ok}
    level = LEVEL_PROJECT if len(keys) == 1 and "" not in keys else LEVEL_USER
    top = None
    if level == LEVEL_PROJECT:
        (key,) = keys
        if os.path.basename(key) == ".git":
            top = os.path.dirname(key)
    return Cluster(
        id=_sha16(members[0].id),
        source=source,
        members=tuple(members),
        successes=successes,
        bar=bar,
        auto_bar=AUTO_FACTOR * bar,
        keywords=tuple(t for t, _ in ranked[:KEYWORDS_TOP]),
        steps=tuple(steps),
        pitfalls=tuple((p.id, p.failure) for p in members if p.ok is False),
        evidence=tuple(p.id for p in members),
        repos=tuple(sorted(k for k in keys if k)),
        level=level,
        top=top,
    )


def cluster(pieces: Iterable[Piece]) -> list[Cluster]:
    """Leader clustering, per source (shiftwork, then session), pieces in `(ts, id)` order.

    A piece joins the cluster whose LEADER (first member) is the most similar to it among
    those that meet `SIM_MIN` (a tie goes to the older cluster), else it leads a new one.
    Document frequencies are counted over that source's pieces only. Failed pieces cluster
    like successful ones; only successes count toward a bar.
    """
    pieces = list(pieces)
    out: list[Cluster] = []
    for source in (SOURCE_SHIFTWORK, SOURCE_SESSION):
        group = sorted((p for p in pieces if p.source == source), key=lambda p: (p.ts, p.id))
        if not group:
            continue
        df, n = doc_freq(group)
        sigs = [signature(p, df, n) for p in group]
        leaders: list[Signature] = []
        groups: list[list[int]] = []
        for i, s in enumerate(sigs):
            best, best_sim = -1, (0, 1)
            for c, lead in enumerate(leaders):
                sim = similarity(lead, s)
                if meets(sim) and (best < 0 or sim[0] * best_sim[1] > best_sim[0] * sim[1]):
                    best, best_sim = c, sim
            if best < 0:
                leaders.append(s)
                groups.append([i])
            else:
                groups[best].append(i)
        for idxs in groups:
            out.append(_make_cluster(source, [group[i] for i in idxs], [sigs[i] for i in idxs]))
    return out


def _record_ids(rec: Mapping[str, Any]) -> set[str]:
    return {
        e["id"]
        for e in rec.get("evidence", [])
        if isinstance(e, dict) and isinstance(e.get("id"), str)
    }


def _valid_record(rec: Any) -> bool:
    return (
        isinstance(rec, dict)
        and isinstance(rec.get("id"), str)
        and isinstance(rec.get("source"), str)
        and isinstance(rec.get("evidence"), list)
    )


def match_previous(cluster: Cluster, previous: Iterable[Any]) -> dict[str, Any] | None:
    """The previous record of the same source sharing the most evidence ids (ties: lower id).

    None when no record shares one. Identity follows the evidence, so a cluster keeps its
    id, status and rejection after its leader leaves the window.
    """
    ids = set(cluster.evidence)
    best: dict[str, Any] | None = None
    best_n = 0
    for rec in previous:
        if not _valid_record(rec) or rec["source"] != cluster.source:
            continue
        n = len(ids & _record_ids(rec))
        if n > best_n or (n > 0 and n == best_n and best is not None and rec["id"] < best["id"]):
            best, best_n = rec, n
    return best


_SAFE_INT = 2**53 - 1


def _int(v: Any) -> int | None:
    """A non-negative integer a JSON reader on either side holds exactly (`3.0` counts)."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return v if type(v) is int and 0 <= v <= _SAFE_INT else None


def proposals(
    clusters: Iterable[Cluster], previous: Mapping[str, Any] | None, now: str, ms: int = 0
) -> dict[str, Any]:
    """The `skill-proposals.json` document for `clusters`, carrying state from `previous`.

    - Each cluster is matched to at most one previous record (`match_previous`), in the order
      `(-successes, id)`; a matched cluster takes the record's id, status, `rejected_at` and
      `draft`. An id already given out is re-hashed (`sha16(id)`) until it is free.
    - `rejected` stays until `successes >= REJECT_FACTOR * rejected_at`, then it is offered
      again with `rejected_at` kept. A `pending` cluster that is no longer eligible is `new`.
    - At most `PENDING_MAX` clusters are `pending`: those already pending keep their place
      first, then eligible `new` and re-offered clusters, each group in output order.
    - Written: a cluster of two or more pieces, or one whose status is not `new` (a
      single piece can never clear a bar, and a carried status must survive).
    """
    clusters = list(clusters)
    records = (
        [r for r in previous.get("clusters", []) if _valid_record(r)]
        if isinstance(previous, Mapping) and isinstance(previous.get("clusters"), list)
        else []
    )
    counts = {SOURCE_SHIFTWORK: 0, SOURCE_SESSION: 0}
    for c in clusters:
        counts[c.source] = counts.get(c.source, 0) + len(c.members)
    unclaimed = list(records)
    used: set[str] = set()
    rows: list[tuple[Cluster, str, dict[str, Any] | None]] = []
    for c in sorted(clusters, key=lambda c: (-c.successes, c.id)):
        prev = match_previous(c, unclaimed)
        if prev is not None:
            unclaimed = [r for r in unclaimed if r is not prev]
        cid = prev["id"] if prev is not None else c.id
        while cid in used:
            cid = _sha16(cid)
        used.add(cid)
        rows.append((c, cid, prev))
    rows.sort(key=lambda r: (-r[0].successes, r[1]))

    out: list[dict[str, Any]] = []
    wants: list[str] = []
    for c, cid, prev in rows:
        eligible = c.successes >= c.bar
        carried = prev.get("status") if prev is not None else "new"
        if carried not in STATUSES:
            carried = "new"
        rejected_at = _int(prev.get("rejected_at")) if prev is not None else None
        if carried == "rejected":
            again = rejected_at is not None and c.successes >= REJECT_FACTOR * rejected_at
            want = "offer" if eligible and again else "rejected"
        elif carried == "pending":
            want = "keep" if eligible else "new"
        elif carried == "new":
            want = "offer" if eligible else "new"
        else:
            want = carried
        rec: dict[str, Any] = {
            "auto_bar": c.auto_bar,
            "auto_eligible": c.successes >= c.auto_bar,
            "bar": c.bar,
            "eligible": eligible,
            "evidence": [p.as_dict() for p in c.members],
            "id": cid,
            "keywords": list(c.keywords),
            "level": c.level,
            "members": len(c.members),
            "pitfalls": [{"failure": f, "id": i} for i, f in c.pitfalls],
            "repos": list(c.repos),
            "source": c.source,
            "status": "new",
            "steps": list(c.steps),
            "successes": c.successes,
            "top": c.top,
        }
        if rejected_at is not None:
            rec["rejected_at"] = rejected_at
        if prev is not None and "draft" in prev:
            rec["draft"] = prev["draft"]
        out.append(rec)
        wants.append(want)
    pending = 0
    for rec, want in zip(out, wants, strict=True):
        if want not in ("keep", "offer"):
            rec["status"] = want
    for group in ("keep", "offer"):
        for rec, want in zip(out, wants, strict=True):
            if want == group:
                rec["status"] = "pending" if pending < PENDING_MAX else "new"
                pending += rec["status"] == "pending"
    return {
        "clusters": [r for r in out if r["members"] >= 2 or r["status"] != "new"],
        "miner": {
            "error": None,
            "ms": ms,
            "pieces": {
                SOURCE_SESSION: counts[SOURCE_SESSION],
                SOURCE_SHIFTWORK: counts[SOURCE_SHIFTWORK],
            },
        },
        "ts": now,
        "version": PROPOSALS_VERSION,
    }


def mine(
    pieces: Iterable[Piece], previous: Mapping[str, Any] | None, now: str, ms: int = 0
) -> dict[str, Any]:
    """`proposals(cluster(pieces), previous, now, ms)`."""
    return proposals(cluster(pieces), previous, now, ms)


# --------------------------------------------------------------------- the proposals file


def proposals_path(home: str | Path) -> Path:
    return Path(home) / ".bantamkit" / PROPOSALS_NAME


def proposals_bytes(doc: Mapping[str, Any]) -> bytes:
    """Indented, sorted keys, UTF-8; a lone surrogate is written as U+FFFD (as Node writes it)."""
    text = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return _LONE_SURROGATE.sub("�", text).encode("utf-8")


def read_proposals(home: str | Path) -> dict[str, Any] | None:
    """The previous proposals document, None when there is none.

    A file that exists and is not a version-1 document is REFUSED, never read as empty: an
    empty previous would forget every rejection and re-offer what the user turned down.
    """
    try:
        with open(proposals_path(home), "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return None
    try:
        doc = _load_json(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ProposalsError(f"{PROPOSALS_NAME} is not readable JSON") from e
    version = doc.get("version") if isinstance(doc, dict) else None
    if _int(version) != PROPOSALS_VERSION or not isinstance(doc.get("clusters"), list):
        raise ProposalsError(
            f"{PROPOSALS_NAME} is not a version {PROPOSALS_VERSION} proposals file"
        )
    return doc


def write_proposals(home: str | Path, doc: Mapping[str, Any]) -> Path:
    """Temp-then-rename under the storage lock; the path written."""
    from bantamkit.storage.lock import exclusive

    path = proposals_path(home)
    data = proposals_bytes(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive(path):
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return path


# ------------------------------------------------------------- sessions (Task 4b)

#: A user prompt is cut to this many code points in a piece of work (and so in every file
#: the miner writes): the plan's `EVIDENCE_PROMPT_CHARS`.
EVIDENCE_PROMPT_CHARS = 500
#: The transcript window: a transcript last written before it is not read, and a turn that
#: starts before it is not a piece. #205's `skillhost.USAGE_DAYS`, so the miner and the audit
#: look at the same month.
MINE_DAYS = 30
DAY_MS = 86_400_000
CACHE_NAME = "skill-miner-cache.json"
CACHE_VERSION = 1
#: Q1's default: a next prompt that starts with (or is) one of these corrects the turn before.
CORRECTIONS = (
    "no",
    "nope",
    "wrong",
    "stop",
    "don't",
    "do not",
    "that's not",
    "undo",
    "revert",
    "ไม่",
    "อย่า",
    "ผิด",
    "หยุด",
)
INTERRUPT = "[Request interrupted by user"
#: R3: spans the harness writes into a user record; none of them is the user's own words.
#: `bash-*` and `task-notification` are measured additions (C6 Step 0): a `!` command's
#: output and a background task's result arrive as non-meta user records.
CUT_TAGS = (
    "system-reminder",
    "command-name",
    "command-message",
    "command-args",
    "local-command-stdout",
    "local-command-stderr",
    "local-command-caveat",
    "bash-input",
    "bash-stdout",
    "bash-stderr",
    "task-notification",
)
#: R4: the tools whose input names a file the agent touched.
PATH_TOOLS = ("Read", "Edit", "MultiEdit", "Write", "NotebookEdit")
PATH_KEYS = ("file_path", "path", "notebook_path")
BASH_TOOL = "Bash"
#: R5. Word edges are spelled as ASCII classes and blanks as `[ \t]`, never `\b`/`\s`,
#: whose meaning differs between Python and JavaScript.
_COMMIT = re.compile(r"(?<![A-Za-z0-9_])git[ \t]+commit(?![A-Za-z0-9_])")
_TESTS = re.compile(
    r"(?<![A-Za-z0-9_])(?:pytest|npm[ \t]+test|npm[ \t]+run[ \t]+test|node[ \t]+--test"
    r"|go[ \t]+test|cargo[ \t]+test|jest|vitest)(?![A-Za-z0-9_])|run\.mjs"
)
_CUT = re.compile(r"<(" + "|".join(CUT_TAGS) + r")>[\s\S]*?(?:</\1>|\Z)")
_WORD_CHAR = re.compile(r"[a-z0-9]")
_QUOTES = re.compile("[‘’]")
_SUBAGENTS = "subagents"


def _well_formed(text: str) -> str:
    return _LONE_SURROGATE.sub("�", text)


def _cut(text: str, n: int = EVIDENCE_PROMPT_CHARS) -> str:
    return text[:n]


def _user_text(content: Any) -> str | None:
    """R3: the string content, or the `text` blocks joined by `\\n`; tool results never."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    texts = [
        b["text"]
        for b in content
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
    ]
    return "\n".join(texts) if texts else None


def clean_prompt(text: str) -> str:
    """The user's own words: every `CUT_TAGS` span cut out (an unclosed one to the end),
    then stripped."""
    return _CUT.sub("", text).strip()


def is_correction(prompt: str) -> bool:
    """Q1: NFKC, lower-cased, curly apostrophes made straight, leading blanks dropped; a
    correction word is the whole prompt or is followed by anything but `[a-z0-9]`."""
    import unicodedata

    s = _QUOTES.sub("'", unicodedata.normalize("NFKC", prompt).lower()).lstrip()
    if s.startswith(INTERRUPT.lower()):
        return True
    for word in CORRECTIONS:
        if s.startswith(word) and (
            len(s) == len(word) or _WORD_CHAR.fullmatch(s[len(word)]) is None
        ):
            return True
    return False


def _ts_ms(value: Any) -> int | None:
    from bantamkit.storage.retention import parse_now

    try:
        return parse_now(value)
    except ValueError:
        return None


# ---- commit subjects (R4): the first line of a `git commit`'s `-m` argument, read off the
# command the agent wrote. A small shell-word reader, the same in both runtimes: blanks are
# space and tab (a backslash-newline is one too), `'...'` is literal, `"..."` drops a backslash
# before a double quote, a backslash, `$`, a backtick or a newline, a bare backslash escapes
# the next character, and an unquoted one of
# `;&|()<>` or a newline ends the command. The value of the FIRST `-m <w>`, `-m<w>`,
# `-<flags>m <w>`, `--message <w>` or `--message=<w>` after `git commit` is the message; a
# value that opens `$(cat <<EOF` (the delimiter bare or quoted, `<<-` too) is the heredoc's
# lines up to the delimiter line. The subject is the first line that is not blank, stripped.

_SHELL_STOP = frozenset(";&|()<>\n")
_DQ_ESCAPES = frozenset('"\\$`\n')
#: Short options whose value follows them: a cluster reaching one of these holds no `-m`.
_VALUE_FLAGS = frozenset("FCct")
_HEREDOC = re.compile(r"\"?\$\(cat[ \t]*<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[ \t]*\n")


def _blank(s: str, i: int) -> int:
    while i < len(s):
        if s[i] in " \t":
            i += 1
        elif s.startswith("\\\n", i):
            i += 2
        else:
            break
    return i


def _shell_word(s: str, i: int) -> tuple[str, int]:
    out: list[str] = []
    n = len(s)
    while i < n:
        c = s[i]
        if c in " \t" or c in _SHELL_STOP:
            break
        if c == "'":
            j = s.find("'", i + 1)
            j = n if j == -1 else j
            out.append(s[i + 1 : j])
            i = j + 1
        elif c == '"':
            i += 1
            while i < n and s[i] != '"':
                if s[i] == "\\" and i + 1 < n and s[i + 1] in _DQ_ESCAPES:
                    if s[i + 1] != "\n":
                        out.append(s[i + 1])
                    i += 2
                else:
                    out.append(s[i])
                    i += 1
            i += 1
        elif c == "\\" and i + 1 < n:
            if s[i + 1] != "\n":
                out.append(s[i + 1])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out), min(i, n)


def _message_at(s: str, i: int) -> str | None:
    """The message whose value starts at raw offset `i`: a heredoc's lines, else one word."""
    m = _HEREDOC.match(s, i)
    if m is not None:
        lines = []
        for line in s[m.end() :].split("\n"):
            if line.strip(" \t") == m.group(2):
                break
            lines.append(line)
        return "\n".join(lines)
    if i >= len(s) or s[i] in _SHELL_STOP:
        return None
    return _shell_word(s, i)[0]


def _option_value(s: str, start: int, word: str, end: int) -> tuple[bool, str | None]:
    """`(is a message option, its message)` for the word `s[start:end]` read as `word`."""
    if word in ("-m", "--message"):
        return True, _message_at(s, _blank(s, end))
    if word.startswith("--message="):
        if s.startswith("--message=", start):
            return True, _message_at(s, start + len("--message="))
        return True, word[len("--message=") :]
    if len(word) < 2 or word[0] != "-" or word[1] == "-":
        return False, None
    for k in range(1, len(word)):
        c = word[k]
        if c == "m":
            if k + 1 == len(word):
                return True, _message_at(s, _blank(s, end))
            if s.startswith(word[: k + 1], start):
                return True, _message_at(s, start + k + 1)
            return True, word[k + 1 :]
        if c in _VALUE_FLAGS or not ("a" <= c <= "z" or "A" <= c <= "Z"):
            return False, None
    return False, None


def commit_subject(command: str) -> str | None:
    """The subject of the first `git commit` in `command`, or None when it names no message."""
    m = _COMMIT.search(command)
    if m is None:
        return None
    i = m.end()
    while True:
        i = _blank(command, i)
        if i >= len(command) or command[i] in _SHELL_STOP:
            return None
        start = i
        word, i = _shell_word(command, i)
        found, message = _option_value(command, start, word, i)
        if found:
            if message is None:
                return None
            for line in message.split("\n"):
                if line.strip():
                    return _well_formed(line.strip())
            return None


def _new_turn(rec: Mapping[str, Any], sid: str, n: int, prompt: str) -> dict[str, Any]:
    cwd = rec.get("cwd")
    ts = rec.get("timestamp")
    return {
        "commits": [],
        "cwd": cwd if isinstance(cwd, str) else "",
        "id": f"s{sid[:8]}#{n}",
        "inpaths": [],
        "prompt": prompt,
        "results": {},
        "session": sid,
        "subjects": {},
        "test": None,
        "tools": [],
        "ts": ts if isinstance(ts, str) else "",
    }


class _Context:
    """Per-run lookups shared by every transcript: repo keys by cwd, touch rows by repo."""

    def __init__(self, home: str) -> None:
        self.home = home
        self._repos: dict[str, tuple[str, Any]] = {}
        self._rows: dict[str, list[dict[str, Any]]] = {}

    def repo(self, cwd: str) -> tuple[str, Any]:
        if cwd not in self._repos:
            from bantamkit.touch.repo import find_repo

            self._repos[cwd] = (repo_key(cwd), find_repo(cwd)) if cwd else ("", None)
        return self._repos[cwd]

    def rows(self, repo_id: str) -> list[dict[str, Any]]:
        if repo_id not in self._rows:
            from bantamkit.touch.log import TouchLog

            self._rows[repo_id] = TouchLog(self.home, repo_id).read()
        return self._rows[repo_id]


def _turn_paths(
    turn: Mapping[str, Any], repo: Any, next_ms: int | None, ctx: _Context
) -> frozenset[str]:
    """R4: the touch log's rows of the session in `[start, next prompt)` (the start floored to
    the second the log writes), or, when the log holds no row of the session at all, the
    file arguments of the turn's Read/Edit/Write calls. Repo-relative; nothing outside a repo."""
    if repo is None:
        return frozenset()
    from bantamkit.touch.repo import relpath

    start = _ts_ms(turn["ts"])
    rows = [
        r
        for r in ctx.rows(repo.id)
        if r.get("session") == turn["session"]
        and r.get("op") not in ("use", "folded")
        and isinstance(r.get("path"), str)
        and r["path"]
    ]
    if rows:
        out: set[str] = set()
        if start is None:
            return frozenset()
        floor = start // 1000 * 1000
        for r in rows:
            t = _ts_ms(r.get("ts"))
            if t is not None and t >= floor and (next_ms is None or t < next_ms):
                out.add(r["path"])
        return frozenset(out)
    out = set()
    for p in turn["inpaths"]:
        full = p if os.path.isabs(p) else os.path.join(turn["cwd"], p)
        rel = relpath(repo, full)
        if rel is not None:
            out.add(rel)
    return frozenset(out)


def _close(
    turn: Mapping[str, Any], nxt: str | None, interrupted: bool, next_ts: Any, ctx: _Context
) -> Piece | None:
    """The piece a turn makes once the record after it is known (`nxt` the next prompt,
    `interrupted` the harness's marker, neither: the session's last turn). None without a
    tool call (R1) or without a readable start time."""
    if not turn["tools"] or _ts_ms(turn["ts"]) is None:
        return None
    results = turn["results"]
    signals = {
        "commit": any(results.get(t) is False for t in turn["commits"]),
        "tests": turn["test"] is not None and results.get(turn["test"]) is False,
    }
    failure = None
    if interrupted:
        signals["uncorrected"] = False
        failure = "interrupted by the user"
    elif nxt is not None:
        corrected = is_correction(nxt)
        signals["uncorrected"] = not corrected
        if corrected:
            failure = "corrected in the next turn: " + _cut(nxt)
    ok: bool | None = True if any(signals.values()) else (False if failure else None)
    subjects = turn.get("subjects")
    subjects = subjects if isinstance(subjects, dict) else {}
    commits: list[str] = []
    for t in turn["commits"]:
        subject = subjects.get(t)
        if results.get(t) is False and isinstance(subject, str) and subject not in commits:
            commits.append(subject)
    key, repo = ctx.repo(turn["cwd"])
    next_ms = None if nxt is None and not interrupted else _ts_ms(next_ts)
    return Piece(
        id=turn["id"],
        source=SOURCE_SESSION,
        ts=turn["ts"],
        repo=key,
        prompt=turn["prompt"],
        tools=tuple(turn["tools"]),
        paths=_turn_paths(turn, repo, next_ms, ctx),
        ok=ok,
        signals=signals,
        failure=failure if ok is False else None,
        commits=tuple(commits),
    )


def _feed(
    rec: Any, state: dict[str, Any], sid_default: str, ctx: _Context, out: list[Piece]
) -> None:
    """One transcript record into the parse state; a closed turn's piece into `out`."""
    if not isinstance(rec, dict) or rec.get("isSidechain") is True:
        return
    kind = rec.get("type")
    turn = state["turn"]
    message = rec.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if kind == "assistant":
        if turn is None or not isinstance(content, list):
            return
        for b in content:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            name = b.get("name")
            if not isinstance(name, str):
                continue
            turn["tools"].append(name)
            given = b.get("input") if isinstance(b.get("input"), dict) else {}
            if name in PATH_TOOLS:
                for k in PATH_KEYS:
                    if isinstance(given.get(k), str) and given[k]:
                        turn["inpaths"].append(given[k])
            bid = b.get("id")
            command = given.get("command")
            if name == BASH_TOOL and isinstance(bid, str) and isinstance(command, str):
                if _COMMIT.search(command):
                    turn["commits"].append(bid)
                    subject = commit_subject(command)
                    if subject is not None:
                        turn.setdefault("subjects", {})[bid] = subject
                if _TESTS.search(command):
                    turn["test"] = bid
        return
    if kind != "user":
        return
    # Only the two booleans of a tool result are read (X4): which call it answers, and
    # whether it is an error. Never its content.
    if turn is not None and isinstance(content, list):
        wanted = set(turn["commits"]) | ({turn["test"]} if turn["test"] else set())
        for b in content:
            if not isinstance(b, dict) or b.get("type") != "tool_result":
                continue
            tid = b.get("tool_use_id")
            if isinstance(tid, str) and tid in wanted:
                turn["results"][tid] = b.get("is_error") is True
    if rec.get("isMeta") is True or rec.get("isCompactSummary") is True or "toolUseResult" in rec:
        return
    text = _user_text(content)
    if text is None:
        return
    prompt = clean_prompt(_well_formed(text))
    if not prompt:
        return
    if prompt.startswith(INTERRUPT):
        if turn is not None:
            piece = _close(turn, None, True, rec.get("timestamp"), ctx)
            if piece is not None:
                out.append(piece)
            state["turn"] = None
        return
    if turn is not None:
        piece = _close(turn, prompt, False, rec.get("timestamp"), ctx)
        if piece is not None:
            out.append(piece)
    sid = rec.get("sessionId")
    if not (isinstance(sid, str) and sid):
        sid = sid_default
    n = state["ordinals"].get(sid, 0) + 1
    state["ordinals"][sid] = n
    state["turn"] = _new_turn(rec, sid, n, _cut(prompt))
    cwd = state["turn"]["cwd"]
    ts = _ts_ms(state["turn"]["ts"])
    if cwd and ts is not None and ts > state["cwds"].get(cwd, -1):
        state["cwds"][cwd] = ts


def _fresh_state() -> dict[str, Any]:
    return {"cwds": {}, "ordinals": {}, "turn": None}


def _piece_from(d: Any) -> Piece | None:
    """A cached piece back, or None when the entry is not one the miner wrote."""
    try:
        signals = d["signals"]
        ok = d["ok"]
        if not (
            isinstance(signals, dict)
            and all(isinstance(v, bool) for v in signals.values())
            and (ok is None or isinstance(ok, bool))
            and all(isinstance(d[k], str) for k in ("id", "source", "ts", "repo", "prompt"))
            and isinstance(d["tools"], list)
            and isinstance(d["paths"], list)
            and all(isinstance(t, str) for t in d["tools"])
            and all(isinstance(t, str) for t in d["paths"])
            and (d["failure"] is None or isinstance(d["failure"], str))
            and isinstance(d.get("commits", []), list)
            and all(isinstance(t, str) for t in d.get("commits", []))
        ):
            return None
        return Piece(
            id=d["id"],
            source=d["source"],
            ts=d["ts"],
            repo=d["repo"],
            prompt=d["prompt"],
            tools=tuple(d["tools"]),
            paths=frozenset(d["paths"]),
            ok=ok,
            signals=dict(signals),
            failure=d["failure"],
            commits=tuple(d.get("commits", [])),
        )
    except (KeyError, TypeError):
        return None


class MinerCache:
    """`<home>/.bantamkit/skill-miner-cache.json`: per transcript `{size, mtime_ms, offset,
    open_turn, pieces}`. It holds only what a `Piece` holds (X4-clean: the open turn's state
    is the prompt, tool names, file arguments, call ids and two booleans per call), so it is
    evidence too. An unreadable cache is an empty one: it only saves work.

    `bytes_read` counts the transcript bytes the last runs read (the test seam)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.entries: dict[str, dict[str, Any]] = {}
        self.bytes_read = 0

    @classmethod
    def for_home(cls, home: str | Path) -> MinerCache:
        return cls(Path(home) / ".bantamkit" / CACHE_NAME)

    def load(self) -> MinerCache:
        try:
            with open(self.path, "rb") as fh:
                doc = _load_json(fh.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return self
        entries = doc.get("transcripts") if isinstance(doc, dict) else None
        if _int(doc.get("version") if isinstance(doc, dict) else None) != CACHE_VERSION:
            return self
        if isinstance(entries, dict):
            self.entries = {k: v for k, v in entries.items() if isinstance(v, dict)}
        return self

    def doc(self) -> dict[str, Any]:
        return {
            "transcripts": {k: self.entries[k] for k in sorted(self.entries)},
            "version": CACHE_VERSION,
        }

    def save(self) -> Path:
        """Temp-then-rename under the storage lock."""
        from bantamkit.storage.lock import exclusive

        data = proposals_bytes(self.doc())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive(self.path):
            tmp = f"{self.path}.{os.getpid()}.tmp"
            try:
                with open(tmp, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        return self.path


def _transcripts(projects: str) -> list[str]:
    """#205's walk (sorted, never through a symlinked directory); `subagents/` skipped (R3)."""
    from bantamkit.skillhost import _jsonl_files

    out = []
    for p in _jsonl_files(Path(projects)):
        rel = os.path.relpath(str(p), projects).replace(os.sep, "/").split("/")
        if _SUBAGENTS not in rel[:-1]:
            out.append(str(p))
    return out


def _entry_ok(e: Mapping[str, Any]) -> bool:
    st = e.get("open_turn")
    return (
        all(_int(e.get(k)) is not None for k in ("size", "mtime_ms", "offset"))
        and isinstance(e.get("pieces"), list)
        and isinstance(st, dict)
        and isinstance(st.get("ordinals"), dict)
        and isinstance(st.get("cwds"), dict)
        and (st.get("turn") is None or isinstance(st.get("turn"), dict))
    )


def _mine_file(
    path: str, size: int, mtime_ms: int, cache: MinerCache, ctx: _Context
) -> dict[str, Any]:
    entry = cache.entries.get(path)
    if entry is not None and not _entry_ok(entry):
        entry = None
    if entry is not None and entry["size"] == size and entry["mtime_ms"] == mtime_ms:
        return entry
    if entry is not None and size > entry["size"] and entry["offset"] <= size:
        offset = entry["offset"]
        state = json.loads(json.dumps(entry["open_turn"]))
        pieces = list(entry["pieces"])
    else:  # new, shrunk or replaced: read whole
        offset, state, pieces = 0, _fresh_state(), []
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except OSError:
        # Unreadable now: an entry that never matches, so the next run tries again.
        return {"mtime_ms": -1, "offset": 0, "open_turn": _fresh_state(), "pieces": [], "size": -1}
    cache.bytes_read += len(data)
    end = data.rfind(b"\n") + 1  # a line still being written waits for the next run
    sid_default = os.path.basename(path)[: -len(".jsonl")]
    new: list[Piece] = []
    for line in data[:end].split(b"\n"):
        try:
            rec = _load_json(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        _feed(rec, state, sid_default, ctx, new)
    pieces += [p.as_dict() for p in new]
    return {
        "mtime_ms": mtime_ms,
        "offset": offset + end,
        "open_turn": state,
        "pieces": pieces,
        "size": size,
    }


def session_pieces(home: str | Path, adapter: Any, now_ms: int, cache: MinerCache) -> list[Piece]:
    """Every session piece of work in the window (R1-R7), sorted by `(ts, id)`.

    With `NullAdapter` there is no transcript source: `[]` (shiftwork is the only one). With
    `ClaudeCodeAdapter`, `<home>/.claude/projects` is walked as #205 walks it, `subagents/`
    skipped. A transcript unchanged since `cache` saw it is not read; one that grew is read
    from the cached offset (transcripts are append-only); one that shrank or was replaced is
    read whole. `cache.entries` is updated in place (the caller saves it); a transcript that
    left the window or the disk leaves the cache. An id seen twice keeps its first piece.
    """
    from bantamkit.skillhost import HOST_CLAUDE_CODE

    if getattr(adapter, "host", None) != HOST_CLAUDE_CODE:
        return []
    home = str(home)
    projects = os.path.join(home, ".claude", "projects")
    cutoff = now_ms - MINE_DAYS * DAY_MS
    ctx = _Context(home)
    kept: dict[str, dict[str, Any]] = {}
    for path in _transcripts(projects):
        try:
            st = os.stat(path)
        except OSError:
            continue
        mtime_ms = st.st_mtime_ns // 1_000_000
        if mtime_ms < cutoff:
            continue
        kept[path] = _mine_file(path, st.st_size, mtime_ms, cache, ctx)
    cache.entries = kept
    out: list[Piece] = []
    seen: set[str] = set()
    for entry in kept.values():
        found = [q for q in (_piece_from(d) for d in entry["pieces"]) if q is not None]
        turn = entry["open_turn"]["turn"]
        if turn is not None:
            last = _close(turn, None, False, None, ctx)
            if last is not None:
                found.append(last)
        for p in found:
            t = _ts_ms(p.ts)
            if p.id in seen or t is None or t < cutoff:
                continue
            seen.add(p.id)
            out.append(p)
    out.sort(key=lambda p: (p.ts, p.id))
    return out


def session_tops(cache: MinerCache, now_ms: int) -> list[str]:
    """The distinct repository tops the window's prompts ran in (each worktree its own),
    code-point order: where a `.shiftwork/` may live besides the miner's own root."""
    from bantamkit.touch.repo import find_repo

    cutoff = now_ms - MINE_DAYS * DAY_MS
    tops: set[str] = set()
    for entry in cache.entries.values():
        cwds = entry.get("open_turn", {}).get("cwds", {})
        for cwd, ts in cwds.items():
            if isinstance(ts, int) and ts >= cutoff:
                repo = find_repo(cwd)
                if repo is not None:
                    tops.add(repo.top)
    return sorted(tops)


def miner_pieces(
    home: str | Path, root: str | Path, adapter: Any, now_ms: int, cache: MinerCache
) -> list[Piece]:
    """Both sources: the session pieces, then the shiftwork pieces of the miner's root and of
    every repository top the window's transcripts name, each root once (realpath). A shiftwork
    id two roots share keeps the first root's piece."""
    sessions = session_pieces(home, adapter, now_ms, cache)
    roots: list[str] = []
    for r in [str(root), *session_tops(cache, now_ms)]:
        real = _realpath(r)
        if real is not None and real not in roots:
            roots.append(real)
    seen: set[str] = set()
    work: list[Piece] = []
    for r in roots:
        for p in shiftwork_pieces(r):
            if p.id not in seen:
                seen.add(p.id)
                work.append(p)
    work.sort(key=lambda p: (p.ts, p.id))
    return work + sessions


# ------------------------------------------------------------- the daily run (Task 8)

#: The `skills-state.json` events the SessionStart line reads (C12): the newest kept.
EVENTS_KEEP = 32
#: The usage-ledger kinds that count as a use of a skill (R10).
USE_KINDS = ("recall_hit", "body_read")
_LEDGER_NAME = re.compile(r"[\s\S]+\.jsonl")


def error_name(e: BaseException) -> str:
    """The word `miner.error` holds: `OSError` for any filesystem error (Node's errors carry an
    errno `code` and a `syscall`, never Python's subclass names), else the class name."""
    return "OSError" if isinstance(e, OSError) else type(e).__name__


def _failed_doc(previous: Mapping[str, Any] | None, now: str, ms: int, error: str) -> dict:
    """The proposals file after a miner error: the previous clusters kept as they were (their
    statuses and rejections must survive a failed day), `miner.error` set."""
    clusters = previous.get("clusters") if isinstance(previous, Mapping) else None
    return {
        "clusters": list(clusters) if isinstance(clusters, list) else [],
        "miner": {"error": error, "ms": ms, "pieces": {SOURCE_SESSION: 0, SOURCE_SHIFTWORK: 0}},
        "ts": now,
        "version": PROPOSALS_VERSION,
    }


def draft_candidate(doc: Mapping[str, Any]) -> dict[str, Any] | None:
    """R12: the one record the daily child drafts — auto-eligible, still installable, with no
    passing draft yet; most successes, then the oldest first member, then the id."""
    from bantamkit.skillinstall import AUTO_FROM, _draft_text, _first_ts

    clusters = doc.get("clusters") if isinstance(doc.get("clusters"), list) else []
    ready = [
        r
        for r in clusters
        if isinstance(r, dict)
        and r.get("auto_eligible") is True
        and r.get("status") in AUTO_FROM
        and isinstance(r.get("id"), str)
        and _int(r.get("successes")) is not None
        and _draft_text(r) is None
    ]
    ready.sort(key=lambda r: (-_int(r["successes"]), _first_ts(r), r["id"]))  # type: ignore[operator]
    return ready[0] if ready else None


def use_counts(home: str | Path, since: Mapping[str, int]) -> dict[str, int]:
    """R10: per name in `since`, the `recall_hit`/`body_read` rows of any store's usage ledger
    (`~/.bantamkit/usage/*.jsonl`, rotated segments too) that name it at or after
    `since[name]` (ms). A folded line counts once when its `last` use is at or after it."""
    from bantamkit.memory.usage import _parse
    from bantamkit.storage.logsegment import LogSegment

    if not since:
        return {}
    d = os.path.join(str(home), ".bantamkit", "usage")
    uses = dict.fromkeys(since, 0)
    for n in sorted(_listdir(d)):
        p = os.path.join(d, n)
        if _LEDGER_NAME.fullmatch(n) is None or not _isfile(p):
            continue
        for row in LogSegment(Path(p)).read():
            fact = row.get("fact")
            if not isinstance(fact, str) or fact not in since:
                continue
            kind = row.get("kind")
            ts = (
                row.get("ts")
                if kind in USE_KINDS
                else row.get("last")
                if kind == "folded"
                else None
            )
            if not isinstance(ts, str):
                continue
            try:
                at = int(_parse(ts)) * 1000
            except ValueError:
                continue
            if at >= since[fact]:
                uses[fact] += 1
    return uses


def _installed_at(state: Mapping[str, Any], auto_only: bool) -> dict[str, int]:
    from bantamkit.storage.retention import parse_now

    skills = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    out: dict[str, int] = {}
    for name, e in skills.items():
        if not isinstance(e, dict) or not isinstance(e.get("at"), str):
            continue
        if auto_only and e.get("auto") is not True:
            continue
        try:
            out[name] = parse_now(e["at"])
        except ValueError:
            continue
    return out


def skill_uses(home: str | Path, state: Mapping[str, Any]) -> dict[str, int]:
    """R10 for probation: per live automatic install, its uses since it was installed."""
    return use_counts(home, _installed_at(state, auto_only=True))


def promote_uses(home: str | Path, state: Mapping[str, Any], now_ms: int) -> dict[str, int]:
    """R10 for promotion: per live skill, its uses in the last `PROMOTE_DAYS` days (and since
    it was installed)."""
    from bantamkit.skillpromote import PROMOTE_DAYS

    floor = now_ms - PROMOTE_DAYS * DAY_MS
    return use_counts(
        home, {n: max(at, floor) for n, at in _installed_at(state, auto_only=False).items()}
    )


#: The hook log the injections are read from (`hookadapter`'s UserPromptSubmit `inject` rows).
HOOK_LOG = ("hooks", "hook-log.jsonl")


def improve_sources(
    home: str | Path, pieces: Iterable[Piece], state: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """What `skillinstall.stats_step` counts, read off disk (R10's per-session attribution):

    - `uses`: the touch logs' (`~/.bantamkit/touch/*.jsonl`) `use` rows of a use kind, as
      `{ts, session, fact}`;
    - `injects`: the hook log's UserPromptSubmit `inject` rows with a session, as
      `{ts, session, names}` (the injected names);
    - `turns`: the session pieces of this run, as `{id, ts, ok, failure, tools}` (Task 10b's
      Pitfalls and different-steps signals read the last two).

    Nothing is read when no skill is installed. Paths and names only (X4)."""
    from bantamkit.storage.logsegment import LogSegment

    skills = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    out: dict[str, list[dict[str, Any]]] = {"injects": [], "turns": [], "uses": []}
    if not skills:
        return out
    d = os.path.join(str(home), ".bantamkit", "touch")
    for n in sorted(_listdir(d)):
        p = os.path.join(d, n)
        if _LEDGER_NAME.fullmatch(n) is None or not _isfile(p):
            continue
        for row in LogSegment(Path(p)).read():
            if row.get("op") == "use" and row.get("kind") in USE_KINDS:
                out["uses"].append(
                    {"fact": row.get("fact"), "session": row.get("session"), "ts": row.get("ts")}
                )
    log = os.path.join(str(home), ".bantamkit", *HOOK_LOG)
    if _isfile(log):
        for row in LogSegment(Path(log)).read():
            injected = row.get("injected")
            if (
                row.get("event") != "UserPromptSubmit"
                or row.get("action") != "inject"
                or not isinstance(injected, list)
            ):
                continue
            names = [x["name"] for x in injected if isinstance(x, dict) and "name" in x]
            out["injects"].append(
                {"names": names, "session": row.get("session"), "ts": row.get("ts")}
            )
    for piece in pieces:
        if piece.source == SOURCE_SESSION:
            out["turns"].append(
                {
                    "failure": piece.failure,
                    "id": piece.id,
                    "ok": piece.ok,
                    "tools": list(piece.tools),
                    "ts": piece.ts,
                }
            )
    return out


def _record_events(home: str | Path, events: list[str], now: str) -> None:
    from bantamkit.skillfile import update_state

    if not events:
        return

    def change(state: dict[str, Any]) -> None:
        old = state.get("events") if isinstance(state.get("events"), list) else []
        state["events"] = [*old, *({"at": now, "event": e} for e in events)][-EVENTS_KEEP:]

    update_state(home, change)


def daily(home: str | Path, cwd: str | None, now: str) -> None:
    """The miner's once-a-day run, in the Retention child after #205's audit under the same
    claimed day. Silent; never raises.

    Runs only when `BANTAMKIT_SKILL_AUDIT` is not off (Q2). Mines both sources into
    `skill-proposals.json` (and saves the miner cache); then, with an endpoint configured and
    `BANTAMKIT_SKILL_AUTO` on, drafts the ONE best auto-eligible record through the endpoint
    alone (R11, R12); then `auto_step` and `probation_step`; then (Task 10a) `stats_step` off
    `improve_sources`, `promote_step` off `promote_uses`, (Task 10b) `improve_step` with the
    endpoint as its only drafter, and `judge_step`, each on its own so
    one that fails cannot lose the events before it; the events go to `skills-state.json`'s
    `events` for the SessionStart line. A miner error writes `miner.error`
    over the previous clusters and NOTHING later runs. A proposals file that exists and cannot
    be read is refused: left as it is, and nothing runs.
    """
    import time

    from bantamkit.storage.retention import audit_enabled

    if not audit_enabled():
        return
    try:
        _daily(home, cwd, now, time.monotonic_ns)
    except Exception:  # noqa: BLE001 - the next day's run tries again; no hook or tool fails
        pass


def _daily(home: str | Path, cwd: str | None, now: str, clock: Any) -> None:
    from bantamkit.skilldraft import default_chain, draft, endpoint_config
    from bantamkit.skillfile import read_state
    from bantamkit.skillhost import select_adapter
    from bantamkit.skillinstall import (
        auto_enabled,
        auto_step,
        draft_entry,
        improve_step,
        judge_step,
        probation_step,
        stats_step,
    )
    from bantamkit.skillpromote import promote_step
    from bantamkit.storage.retention import parse_now
    from bantamkit.touch.repo import find_repo

    t0 = clock()
    try:
        previous = read_proposals(home)
    except ProposalsError:
        return
    try:
        now_ms = parse_now(now)
        repo = find_repo(cwd) if cwd else None
        root = repo.top if repo is not None else (cwd or "")
        cache = MinerCache.for_home(home).load()
        pieces = miner_pieces(home, root, select_adapter(home), now_ms, cache)
        doc = mine(pieces, previous, now, 0)
        cache.save()
    except Exception as e:  # noqa: BLE001 - recorded, and the later steps do not run
        ms = (clock() - t0) // 1_000_000
        write_proposals(home, _failed_doc(previous, now, ms, error_name(e)))
        return
    doc["miner"]["ms"] = (clock() - t0) // 1_000_000
    write_proposals(home, doc)
    written = proposals_bytes(doc)
    if endpoint_config() is not None and auto_enabled():
        rec = draft_candidate(doc)
        if rec is not None:
            out = draft(rec, default_chain(None, host_agent=False), home, cwd, now)
            if out.ok:
                rec["draft"] = draft_entry(out.drafter, out.text, now)
    state = read_state(home)
    events = auto_step(doc, state, home, now)
    if proposals_bytes(doc) != written:
        write_proposals(home, doc)
    events += probation_step(state, skill_uses(home, state), home, now)
    # Task 10a: count, promote, judge. Each step is on its own: one that fails leaves the
    # events already made to be recorded, and the next day's run tries it again.
    sources: dict[str, Any] = {}
    try:
        sources = improve_sources(home, pieces, state)
        stats_step(state, sources, home, now)
    except Exception:  # noqa: BLE001
        pass
    try:
        events += promote_step(state, promote_uses(home, state, now_ms), home, cwd, now)
    except Exception:  # noqa: BLE001
        pass
    # Task 10b: the improvement signals, before the judge, so a version made today is never
    # judged on the day it is made.
    try:
        chain = default_chain(None, host_agent=False)
        events += improve_step(state, sources, doc, home, cwd, now, chain)
    except Exception:  # noqa: BLE001
        pass
    try:
        events += judge_step(state, home, now)
    except Exception:  # noqa: BLE001
        pass
    _record_events(home, events, now)


def status_line(home: str | Path, sampling: bool = False) -> str:
    """The `skills:` line of `bantamkit_status`, after the `skill audit:` line. Never raises.

    `<p>` is `off; ` when the miner's switch (`BANTAMKIT_SKILL_AUDIT`) is off; the drafter is
    the one a draft made now would reach first (`sampling` when the client declared it); the
    last clause says whether automatic installs and edits are on (`BANTAMKIT_SKILL_AUTO`, off
    by default) and, when off, how to opt in.
    """
    from bantamkit.skilldraft import active_drafter
    from bantamkit.skillfile import read_state
    from bantamkit.skillinstall import (
        AUTO_LIVE_MAX,
        AUTO_SAID_OFF,
        AUTO_SAID_ON,
        auto_enabled,
        live_auto,
    )
    from bantamkit.storage.retention import audit_enabled

    p = "" if audit_enabled() else "off; "
    said = AUTO_SAID_ON if auto_enabled() else AUTO_SAID_OFF
    tail = f"; drafter {active_drafter(sampling)}; {said}"
    try:
        doc = read_proposals(home)
    except ProposalsError as e:
        return f"skills: {p}miner refused: {e}{tail}"
    except Exception:  # noqa: BLE001 - a status line never fails the report
        return f"skills: {p}miner refused: {PROPOSALS_NAME} is not readable{tail}"
    if doc is None:
        return f"skills: {p}miner never ran{tail}"
    miner = doc.get("miner") if isinstance(doc.get("miner"), dict) else {}
    ts = doc["ts"] if isinstance(doc.get("ts"), str) else "?"
    error = miner.get("error")
    if error is not None:
        return f"skills: {p}miner failed at {ts}: {error if isinstance(error, str) else '?'}{tail}"
    pending = sum(
        1 for r in doc["clusters"] if isinstance(r, dict) and r.get("status") == "pending"
    )
    try:
        state = read_state(home)
        live = str(len(live_auto(state)))
        promoted = str(
            sum(
                1
                for e in state["skills"].values()
                if isinstance(e, dict) and e.get("promoted") not in (None, False)
            )
        )
    except Exception:  # noqa: BLE001 - an unreadable state is said, never guessed
        live = promoted = "?"
    ms = _int(miner.get("ms"))
    return (
        f"skills: {p}mined {ts} in {'?' if ms is None else ms} ms; {pending} pending, "
        f"{live} of {AUTO_LIVE_MAX} auto-installed live, {promoted} promoted{tail}"
    )
