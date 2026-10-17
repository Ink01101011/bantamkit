"""Retention: the daily, detached, verify-before-delete job (#204, S4; job69 J69-6).

`run_retention(home, roots, now)` does five things, in this order, and answers what it did:

1. **Ledgers.** `home/.bantamkit/hooks/ledger-*.json` whose mtime is MORE than 7 days before
   `now` are deleted. They are per-session read ledgers, past their TTL; nothing archives them.
2. **Logs.** Lines older than 30 days are folded through each log's reducer: the hook log
   (`hooks/hook-log.jsonl`) into one `{"event": "Folded"}` row per day counting `event` (and
   `event/tool`); every usage ledger (`usage/*.jsonl`) through J68-4's own reducer, at the
   cutoff, so the weights it keeps are unchanged and nothing is made to look recently used;
   every touch log (`touch/*.jsonl`, #200) into one `{"op": "folded"}` row per path keeping
   its last touch and count, its old `use` lines dropped.
3. **Segments.** A log whose live file was last written more than 30 days ago is gzipped into
   its next `.N.gz` segment (`LogSegment.rotate(0)`). Rotated segments are never rewritten.
4. **Jobs.** In each root's `.shiftwork/`, a job (`checkpoint[-<job>].json`, its
   `.log.jsonl`, `briefs-<job>/`, `notes-<job>/`) whose units are ALL done or dropped and
   whose newest file is more than 7 days old is bundled into `.shiftwork/archive/<job>.json.gz`
   (`{relative path: utf-8 text | {"base64": bytes}}`), the archive is re-read and its hash
   checked, every original is re-read and checked against what was bundled, and only then
   are the originals deleted. Any failure deletes nothing and is listed under `refused`. An
   open job, an unreadable checkpoint and an empty plan are never touched.
5. **Cold indexes.** Archived jobs are added to `ColdIndex("shiftwork-<repo_id>")`; every cold
   index is compacted, dropping names whose archive file is gone (a restored fact, a removed
   job archive).

Facts are NEVER archived by age (S4). The event log is not folded here: it is opt-in, bounded
by its own documented two-file rotation (docs/eventlog.md), and its readers would count a fold
row as unreadable (J69-6 deviation, `.shiftwork/notes-job69/J69-6.md`).

THE TRIGGER. `maybe_spawn` starts `python -m bantamkit.storage.retention <cwd>` detached and
silent, at most once per 24 h (`home/.bantamkit/retention.json` `{"ran_at"}`); the SessionStart
hook calls it, and the MCP server calls it with `server=True`, which stands down when a hook
wrote `hooks/hook-log.jsonl` within the TTL. `BANTAMKIT_RETENTION=off` makes every entry here a
no-op. `runtime-ts/src/storage/retention.ts` is the port; `storage-retention` compares them.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import zlib
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .coldindex import ColdIndex, ColdIndexError
from .hotindex import INDEX_DIR_ENV, dumps
from .lock import exclusive
from .logsegment import LogSegment

RETENTION_ENV = "BANTAMKIT_RETENTION"
TTL_S = 86_400
LEDGER_DAYS = 7
LOG_DAYS = 30
JOB_DAYS = 7
STATE_NAME = "retention.json"
SEARCH_MAX = 50

_OFF = frozenset({"off", "0", "false", "no"})
_NOW = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{3}))?Z"
)
# `[\s\S]`, not `.`: JavaScript's `.` also refuses `\r`, U+2028 and U+2029.
_LEDGER = re.compile(r"ledger-[\s\S]*\.json")
_CHECKPOINT = re.compile(r"checkpoint(?:-([\s\S]+))?\.json")
_TOP_CHECKPOINT = re.compile(r"\.shiftwork/checkpoint(?:-[\s\S]+)?\.json")
_CLOSED = frozenset({"done", "dropped"})
_DAY_NS = 86_400 * 1_000_000_000


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def _load_json(data: bytes) -> Any:
    """Strict UTF-8 (a BOM is not stripped), and `NaN`/`Infinity` refused: `JSON.parse`'s rules."""
    return json.loads(data.decode("utf-8"), parse_constant=_refuse_constant)


def enabled() -> bool:
    """False when `BANTAMKIT_RETENTION` is `off` (or `0`, `false`, `no`), any case."""
    return os.environ.get(RETENTION_ENV, "").strip().lower() not in _OFF


def parse_now(now: str) -> int:
    """Milliseconds since the epoch for `YYYY-MM-DDTHH:MM:SS[.mmm]Z`; ValueError otherwise."""
    m = _NOW.fullmatch(now) if isinstance(now, str) else None
    if m is None:
        raise ValueError(f"not a retention timestamp: {now!r}")
    y, mo, d, h, mi, s = (int(g) for g in m.groups()[:6])
    ms = int(m.group(7) or 0)
    t = datetime(y, mo, d, h, mi, s, tzinfo=UTC)
    return int(t.timestamp()) * 1000 + ms


def _iso_ms(ms: int) -> str:
    t = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)
    return f"{t.strftime('%Y-%m-%dT%H:%M:%S')}.{t.microsecond // 1000:03d}Z"


def _iso_s(ms: int) -> str:
    t = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_stamp() -> str:
    """The wall clock as `toISOString()` writes it."""
    return _iso_ms(int(datetime.now(UTC).timestamp() * 1000))


def _cold_base(home: Path) -> Path:
    override = os.environ.get(INDEX_DIR_ENV) or None
    return Path(override) / "cold" if override else Path(home) / ".bantamkit" / "cold"


def _store_id(p: Path) -> str:
    from bantamkit.memory.usage import store_id

    return store_id(p)


def _empty_report() -> dict[str, list[Any]]:
    return {
        "archived": [],
        "compacted": [],
        "deleted": [],
        "folded": [],
        "refused": [],
        "rotated": [],
    }


def _regular(p: Path) -> os.stat_result | None:
    try:
        st = os.lstat(p)
    except OSError:
        return None
    return st if stat.S_ISREG(st.st_mode) else None


def _listdir(d: Path) -> list[str]:
    try:
        return sorted(os.listdir(d))
    except OSError:
        return []


# ------------------------------------------------------------------------------ ledgers


def _prune_ledgers(home: Path, now_ns: int, report: dict[str, list[Any]]) -> None:
    hooks = Path(home) / ".bantamkit" / "hooks"
    cutoff = now_ns - LEDGER_DAYS * _DAY_NS
    for name in _listdir(hooks):
        if not _LEDGER.fullmatch(name):
            continue
        p = hooks / name
        st = _regular(p)
        if st is None or st.st_mtime_ns >= cutoff:
            continue
        try:
            os.unlink(p)
            report["deleted"].append(str(p))
        except OSError:
            report["refused"].append({"path": str(p), "reason": "delete failed"})


# --------------------------------------------------------------------------------- logs


def hook_log_reducer(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One `{"ts": <day>T00:00:00.000Z, "event": "Folded", "counts": {...}}` row per day.

    A key is the row's `event`, or `event/tool` when the row names a string `tool`; a row with
    no string `event` counts as `?`. An earlier fold row's counts are merged, so a fold of a
    fold is the same fold.
    """
    days: dict[str, Counter[str]] = {}
    for row in rows:
        ts = row.get("ts")
        day = ts[:10] if isinstance(ts, str) else "?"
        c = days.setdefault(day, Counter())
        counts = row.get("counts")
        if row.get("event") == "Folded" and isinstance(counts, dict):
            for k, v in counts.items():
                if isinstance(v, int) and not isinstance(v, bool):
                    c[str(k)] += v
            continue
        event = row.get("event")
        key = event if isinstance(event, str) else "?"
        tool = row.get("tool")
        if isinstance(tool, str):
            key = f"{key}/{tool}"
        c[key] += 1
    return [
        {
            "ts": f"{day}T00:00:00.000Z",
            "event": "Folded",
            "counts": {k: days[day][k] for k in sorted(days[day])},
        }
        for day in sorted(days)
    ]


def _bytes(p: Path) -> bytes | None:
    try:
        return p.read_bytes()
    except OSError:
        return None


def _old_use(path: Path, cutoff: str) -> bool:
    """Does the live usage ledger hold a line older than `cutoff` that is not a `save`?

    The usage reducer keeps each fact's latest `save` line as read and writes it FIRST, so
    a ledger whose only old lines are saves would be reordered by every fold and never
    settle. Folding only when a use or an earlier fold is old makes a second pass a no-op.
    """
    data = _bytes(path)
    if data is None:
        return False
    for line in data.decode("utf-8", errors="replace").split("\n"):
        try:
            row = json.loads(line, parse_constant=_refuse_constant)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        ts = row.get("ts")
        if isinstance(ts, str) and ts < cutoff and row.get("kind") != "save":
            return True
    return False


def _old_touch(path: Path, cutoff: str) -> bool:
    """Does the live touch log hold a line older than `cutoff` that is not a `folded` row?

    A folded row keeps its path's last `ts`, so it is old forever; folding only when a live
    line is old makes a second pass a no-op and lets an idle log reach its rotate (#200).
    """
    data = _bytes(path)
    if data is None:
        return False
    for line in data.decode("utf-8", errors="replace").split("\n"):
        try:
            row = json.loads(line, parse_constant=_refuse_constant)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        ts = row.get("ts")
        if isinstance(ts, str) and ts < cutoff and row.get("op") != "folded":
            return True
    return False


def _fold_logs(home: Path, now_ms: int, report: dict[str, list[Any]]) -> None:
    from bantamkit.memory.usage import reduce_usage
    from bantamkit.touch.log import touch_reducer

    base = Path(home) / ".bantamkit"
    cutoff_ms = now_ms - LOG_DAYS * 86_400_000
    idle_ns = cutoff_ms * 1_000_000
    logs: list[tuple[Path, Callable[[LogSegment], None]]] = []
    hook_cutoff = _iso_ms(cutoff_ms)
    logs.append(
        (base / "hooks" / "hook-log.jsonl", lambda seg: seg.fold(hook_cutoff, hook_log_reducer))
    )
    usage_cutoff = _iso_s(cutoff_ms)
    for name in _listdir(base / "usage"):
        if name.endswith(".jsonl") and _old_use(base / "usage" / name, usage_cutoff):
            logs.append(
                (
                    base / "usage" / name,
                    lambda seg: seg.fold_lines(
                        usage_cutoff, lambda pairs: reduce_usage(pairs, usage_cutoff)
                    ),
                )
            )
    # #200: every touch log, folded at the usage cutoff (its lines carry seconds, as usage's
    # do) into one row per path when a live line is old, and rotated once idle.
    for name in _listdir(base / "touch"):
        if not name.endswith(".jsonl"):
            continue
        p = base / "touch" / name
        if _old_touch(p, usage_cutoff):
            logs.append((p, lambda seg: seg.fold(usage_cutoff, touch_reducer)))
        else:
            logs.append((p, lambda seg: None))
    for path, fold in logs:
        st = _regular(path)
        if st is None:
            continue
        idle = st.st_mtime_ns < idle_ns
        seg = LogSegment(path)
        before = _bytes(path)
        fold(seg)
        if _bytes(path) != before:
            report["folded"].append(str(path))
        if idle and seg.rotate(0):
            report["rotated"].append(str(path))


# --------------------------------------------------------------------------------- jobs


def _closed(data: Any) -> bool:
    plan = data.get("plan") if isinstance(data, dict) else None
    units = plan.get("units") if isinstance(plan, dict) else None
    if not isinstance(units, list) or not units:
        return False
    return all(isinstance(u, dict) and u.get("status") in _CLOSED for u in units)


def _walk(d: Path) -> list[Path]:
    """Every regular file under `d`, sorted; a symlink is neither followed nor listed.

    That holds for `d` itself (J69-8): a `briefs-<job>` or `notes-<job>` that is a link to a
    directory elsewhere is not walked, so archiving a job never deletes a file outside
    `.shiftwork/` through it. The link is left where it is.
    """
    try:
        if not stat.S_ISDIR(os.lstat(d).st_mode):
            return []
    except OSError:
        return []
    out: list[Path] = []
    for name in _listdir(d):
        p = d / name
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            out += _walk(p)
        elif stat.S_ISREG(st.st_mode):
            out.append(p)
    return out


def _job_files(sw: Path, name: str, job: str) -> list[Path]:
    files = [sw / name]
    log = sw / f"{name}.log.jsonl"
    if _regular(log) is not None:
        files.append(log)
    if job != "checkpoint":
        files += _walk(sw / f"briefs-{job}") + _walk(sw / f"notes-{job}")
    return files


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def bundle_bytes(bundle: dict[str, Any]) -> bytes:
    return dumps(bundle).encode("utf-8")


def _entry(data: bytes) -> Any:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(data).decode("ascii")}


def _gunzip(p: Path) -> bytes | None:
    try:
        return gzip.decompress(p.read_bytes())
    except (OSError, EOFError, zlib.error):
        return None


def _fsync_dir(d: Path) -> None:
    """Make a rename in `d` durable. POSIX only: Windows cannot open a directory for fsync."""
    if os.name == "nt":
        return
    try:
        fd = os.open(d, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_archive(target: Path, data: bytes) -> None:
    """Hook for tests: the archive's one write, temp then rename, flushed to the disk.

    The originals are deleted only after this archive is read back, and a read-back is served
    from the page cache: without the fsync a power cut after the unlinks could leave neither
    the archive nor the files it held (J69-8).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(gzip.compress(data, mtime=0))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        _fsync_dir(target.parent)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _remove_empty_dirs(d: Path) -> None:
    for name in _listdir(d):
        p = d / name
        if p.is_dir() and not p.is_symlink():
            _remove_empty_dirs(p)
    try:
        os.rmdir(d)
    except OSError:
        pass


def job_doc(job: str, rel_archive: str, data: bytes, bundle: dict[str, Any]) -> dict[str, Any]:
    """The cold-index doc of one archived job: every token of every text file, as keywords."""
    from bantamkit.memory.retrieval import tokenize_v2

    goal = ""
    terms: set[str] = set()
    for rel in sorted(bundle):
        terms.update(tokenize_v2(rel))
        value = bundle[rel]
        if isinstance(value, str):
            terms.update(tokenize_v2(value))
    for rel in sorted(bundle):
        value = bundle[rel]
        if isinstance(value, str) and _TOP_CHECKPOINT.fullmatch(rel):
            try:
                doc = _load_json(value.encode("utf-8"))
            except ValueError:
                continue
            job_obj = doc.get("job") if isinstance(doc, dict) else None
            if isinstance(job_obj, dict) and isinstance(job_obj.get("goal"), str):
                goal = job_obj["goal"]
    return {
        "file": rel_archive,
        "name": job,
        "description": goal,
        "type": "shiftwork",
        "keywords": sorted(terms),
        "links": [],
        "tags": [],
        "refs": [],
        "mtime_ns": "0",
        "size": len(data),
    }


def _archive_jobs(
    root: Path, now_ns: int, report: dict[str, list[Any]]
) -> dict[str, dict[str, Any]]:
    sw = root / ".shiftwork"
    added: dict[str, dict[str, Any]] = {}
    if not sw.is_dir() or sw.is_symlink():
        return added
    cutoff = now_ns - JOB_DAYS * _DAY_NS
    for name in _listdir(sw):
        m = _CHECKPOINT.fullmatch(name)
        if m is None or _regular(sw / name) is None:
            continue
        job = m.group(1) or "checkpoint"
        try:
            data = _load_json((sw / name).read_bytes())
        except (OSError, ValueError):
            continue  # unreadable: never touched
        if not _closed(data):
            continue  # an open job is never archived, at any age
        files = _job_files(sw, name, job)
        stats = [_regular(p) for p in files]
        if any(s is None for s in stats):
            continue
        if max(s.st_mtime_ns for s in stats if s is not None) >= cutoff:
            continue
        archive = sw / "archive" / f"{job}.json.gz"
        try:
            raw = {_rel(root, p): p.read_bytes() for p in files}
        except OSError:
            report["refused"].append({"path": str(sw / name), "reason": "unreadable"})
            continue
        bundle = {rel: _entry(raw[rel]) for rel in raw}
        data_out = bundle_bytes(bundle)
        if archive.exists() or archive.is_symlink():
            if _gunzip(archive) != data_out:
                report["refused"].append(
                    {"path": str(archive), "reason": "archive exists and differs"}
                )
                continue
            wrote = False
        else:
            try:
                _write_archive(archive, data_out)
            except OSError:
                report["refused"].append({"path": str(sw / name), "reason": "archive write failed"})
                continue
            wrote = True
        # VERIFY, THEN DELETE. The archive is read back and hashed; every original is read
        # back and must still be the bytes that were bundled (a live session may have
        # written one since), and the checkpoint must still be closed.
        back = _gunzip(archive)
        if back is None or _sha(back) != _sha(data_out):
            report["refused"].append({"path": str(archive), "reason": "archive did not verify"})
            continue
        changed = False
        for p in files:
            now_bytes = _bytes(p)
            if now_bytes is None or _sha(now_bytes) != _sha(raw[_rel(root, p)]):
                changed = True
                break
        if changed or not _closed(_load_json(raw[_rel(root, sw / name)])):
            if wrote:
                try:
                    archive.unlink()
                except OSError:
                    pass
            report["refused"].append({"path": str(sw / name), "reason": "changed since bundled"})
            continue
        failed = False
        for p in files:
            try:
                os.unlink(p)
            except OSError:
                failed = True
                report["refused"].append({"path": str(p), "reason": "delete failed"})
        if job != "checkpoint":
            for d in (sw / f"briefs-{job}", sw / f"notes-{job}"):
                if d.is_dir() and not d.is_symlink():
                    _remove_empty_dirs(d)
        if not failed:
            report["archived"].append(str(archive))
        added[job] = job_doc(job, _rel(root, archive), data_out, bundle)
    return added


def shiftwork_cold(home: Path, root: Path) -> ColdIndex:
    return ColdIndex(f"shiftwork-{_store_id(root)}", home, cold_dir=_cold_base(home))


def sync_jobs(home: Path, root: Path) -> ColdIndex:
    """The root's job cold index, with every `.shiftwork/archive/*.json.gz` not yet in it added."""
    cold = shiftwork_cold(home, root)
    try:
        held = {d["file"] for d in cold.all_docs()}
    except ColdIndexError:
        cold.reset()
        held = set()
    adds: dict[str, dict[str, Any]] = {}
    arch = root / ".shiftwork" / "archive"
    for name in _listdir(arch):
        if not name.endswith(".json.gz") or _regular(arch / name) is None:
            continue
        rel = _rel(root, arch / name)
        if rel in held:
            continue
        data = _gunzip(arch / name)
        if data is None:
            continue
        try:
            bundle = _load_json(data)
        except ValueError:
            continue
        if not isinstance(bundle, dict):
            continue
        job = name[: -len(".json.gz")]
        adds[job] = job_doc(job, rel, data, bundle)
    if adds:
        cold.add(adds)
    return cold


# --------------------------------------------------------------------------------- cold


def _compact_cold(home: Path, roots: list[Path], report: dict[str, list[Any]]) -> None:
    keeps: dict[str, Callable[[dict[str, Any]], bool]] = {}
    for root in roots:
        keeps[f"shiftwork-{_store_id(root)}"] = lambda d, r=root: (r / d["file"]).is_file()
    stores = [Path(home) / ".bantamkit" / "memory"] + [r / ".bantamkit" / "memory" for r in roots]
    for store in stores:
        if store.is_dir():
            keeps[f"facts-archive-{_store_id(store)}"] = lambda d, s=store: (
                s / "archive" / d["file"]
            ).is_file()
    base = _cold_base(home)
    for name in _listdir(base):
        if not (base / name / "manifest.json").is_file():
            continue
        cold = ColdIndex(name, home, cold_dir=base)
        keep = keeps.get(name)
        try:
            if cold.compact(keep) is not None:
                report["compacted"].append(name)
        except ColdIndexError:
            cold.reset()  # derived: the next search re-adds its sources
        except OSError:
            pass


# ---------------------------------------------------------------------------------- run


def run_retention(home: Path | str, roots: list[Path | str], now: str) -> dict[str, list[Any]]:
    """One retention pass over `home` and the `.shiftwork/` of each root, at `now`."""
    report = _empty_report()
    if not enabled():
        return report
    home = Path(home)
    now_ms = parse_now(now)
    now_ns = now_ms * 1_000_000
    _prune_ledgers(home, now_ns, report)
    _fold_logs(home, now_ms, report)
    root_paths = [Path(r) for r in roots]
    for root in root_paths:
        added = _archive_jobs(root, now_ns, report)
        if added:
            try:
                sync_jobs(home, root)
            except (OSError, ColdIndexError):
                pass  # derived: the next search syncs it
    _compact_cold(home, root_paths, report)
    return report


# ------------------------------------------------------------------------------ trigger


def state_path(home: Path | str) -> Path:
    return Path(home) / ".bantamkit" / STATE_NAME


def due(home: Path | str, now: str) -> bool:
    """True unless `retention.json` holds a `ran_at` within the last 24 h (and not ahead)."""
    try:
        data = json.loads(state_path(home).read_text(encoding="utf-8"))
        age = parse_now(now) - parse_now(data["ran_at"])
    except (OSError, ValueError, TypeError, KeyError):
        return True
    return not 0 <= age < TTL_S * 1000


def _hooked(home: Path, now: str) -> bool:
    try:
        mtime_ms = (
            os.stat(home / ".bantamkit" / "hooks" / "hook-log.jsonl").st_mtime_ns // 1_000_000
        )
    except OSError:
        return False
    return 0 <= parse_now(now) - mtime_ms < TTL_S * 1000


def maybe_spawn(home: Path | str, cwd: str, *, server: bool = False) -> str:
    """Start the detached child when due. The word says why it did or did not.

    `off` (opted out), `nohome` (no `~/.bantamkit`: an install makes it, not this), `hooked`
    (the server, when a hook ran within the TTL), `fresh` (ran within 24 h), `spawned`,
    `failed`. Never raises.
    """
    try:
        if not enabled():
            return "off"
        home = Path(home)
        if not (home / ".bantamkit").is_dir():
            return "nohome"
        now = now_stamp()
        if server and _hooked(home, now):
            return "hooked"
        if not due(home, now):
            return "fresh"
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            kwargs["start_new_session"] = True
        # THE HOME GOES ON THE COMMAND LINE. The child must act on the home this function
        # judged the TTL on, never re-derive one: J69-6's first draft let the child read `~`,
        # and a test that passed a scratch home here ran the child on the operator's real one.
        subprocess.Popen(
            [sys.executable, "-m", "bantamkit.storage.retention", cwd, str(home)], **kwargs
        )
        return "spawned"
    except Exception:  # noqa: BLE001 - a spawn this cannot make is never a failed session
        return "failed"


def _write_state(home: Path, obj: dict[str, Any]) -> None:
    p = state_path(home)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(dumps(obj) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, p)


def child_main(argv: list[str], now: str | None = None) -> int:
    """The detached child, `<cwd> <home>`: claim the day under the lock, run, record.

    Silent; exit 0. Both arguments are required: without a home named by the spawner the
    child does nothing rather than guess one.
    """
    if not enabled() or len(argv) < 2:
        return 0
    home = Path(argv[1])
    if not (home / ".bantamkit").is_dir():
        return 0
    stamp = now if now is not None else now_stamp()
    try:
        with exclusive(state_path(home)) as held:
            if not held or not due(home, stamp):
                return 0
            _write_state(home, {"ran_at": stamp})
        roots = [Path(a) for a in argv[:1]]
        try:
            report = run_retention(home, roots, stamp)
            _write_state(home, {"ran_at": stamp, "report": report})
        except Exception as e:  # noqa: BLE001 - recorded, retried at the next day's TTL
            _write_state(home, {"ran_at": stamp, "error": type(e).__name__})
    except OSError:
        pass
    return 0


# ------------------------------------------------------------------------------- search


def search_archived(
    checkpoint: Path | str, search: str, home: Path | str | None = None
) -> list[dict[str, Any]]:
    """`{job, file, line}` for every line of an archived job that holds every query term.

    Jobs come from the root's cold index (synced from `.shiftwork/archive/` first), best first;
    within a job, files in code-point order, lines in order. At most `SEARCH_MAX` hits.
    """
    from bantamkit.memory.retrieval import tokenize_v2

    terms = tokenize_v2(search)
    if not terms:
        return []
    want = set(terms)
    home = Path(home) if home is not None else Path(os.path.expanduser("~"))
    root = Path(checkpoint).parent.parent
    try:
        cold = sync_jobs(home, root)
        rows = cold.query(terms)
    except ColdIndexError:
        shiftwork_cold(home, root).reset()
        cold = sync_jobs(home, root)
        rows = cold.query(terms)
    except OSError:
        return []
    hits: list[dict[str, Any]] = []
    for job, _seg, _tf in rows:
        doc = cold.doc(job)
        if doc is None:
            continue
        data = _gunzip(root / doc["file"])
        if data is None:
            continue
        try:
            bundle = _load_json(data)
        except ValueError:
            continue
        if not isinstance(bundle, dict):
            continue
        for rel in sorted(bundle):
            value = bundle[rel]
            if not isinstance(value, str):
                continue
            for i, line in enumerate(value.split("\n"), 1):
                if want.issubset(tokenize_v2(line)):
                    hits.append({"job": job, "file": rel, "line": i})
                    if len(hits) >= SEARCH_MAX:
                        return hits
    return hits


if __name__ == "__main__":
    sys.exit(child_main(sys.argv[1:]))
