"""The skill installer (#206 Task 7): the auto rule, the caps, probation and undo.

A draft that passed the gate (`skilldraft.gate`) becomes a skill directory here, in the
Agent Skills shape `skillfile` writes:

    <root>/<name>/SKILL.md                 the draft, stamped (below)
    <root>/<name>/references/evidence.md   every piece of work the skill was learned from

`<root>` is `<project top>/.bantamkit/skills` for a project-level cluster (X3/X7) and
`~/.bantamkit/skills` for a user-level one; a caller may override the level.

THE STAMP. `bantamkit-generated-by: bantamkit` (#205's audit reads it), `bantamkit-evidence`
(the cluster's evidence ids joined by `,`), `bantamkit-keywords` (its keywords, at most
`KEYWORDS_MAX`, joined by `,`; the `[skill]` layer reads them, R9), `bantamkit-version: "1"`,
`bantamkit-cluster`, and last `bantamkit-sha256` (R8). `skillfile.stamp` re-renders the file,
so every installed SKILL.md is in the one X9 shape both runtimes write byte for byte.

EVIDENCE (`evidence_markdown`) is built from named fields of the proposals record only, so X4
holds by construction: ids, the time, the result, the signal names, the tools, the paths, the
commit subjects (in full: the Q8 ruling) and the user's prompt. A prompt, and the prompt a
`corrected in the next turn:` note quotes, is cut to `EVIDENCE_PROJECT_CHARS` code points in a
PROJECT-level skill (its directory may be committed to a public repo, Q8) and to
`EVIDENCE_USER_CHARS` in a user-level one.

THE AUTO RULE (`auto_step`). At most one install per run, and only when ALL hold:
`BANTAMKIT_SKILL_AUTO` is not `off` (or `0`, `false`, `no`, any case); the cluster has twice the
X1 repeats (`auto_eligible` and `successes >= auto_bar`); its stored draft passed the gate;
fewer than `AUTO_PER_DAY` automatic installs on `now`'s UTC date; fewer than `AUTO_LIVE_MAX`
live automatic installs. Candidates are tried best first (most successes, then the oldest
first piece of work, then id); one the installer refuses is marked `failed` and the next is
tried. A rejected, installed or failed cluster is never a candidate.

PROBATION (`probation_step`, automatic installs only: R13). A live automatic install whose
`probation_until` (install time + `PROBATION_DAYS`) has come with no use since it was installed
is removed when its SKILL.md still matches its hash (a backup of the directory is taken first,
so `undo` brings it back byte for byte), and is proposed for removal (never deleted) when it
does not. A skill with any use leaves probation.

EVERY WRITE is temp-then-rename (`skillfile`). An install takes an "absent" backup first, so
`undo` right after it removes the skill; if the directory write or the state write fails,
nothing is left: no directory, no state entry, no backup.

`runtime-ts/src/skillinstall.ts` is the port; `tools/conformance/suites/skill-install.mjs`
compares the two.
"""

from __future__ import annotations

import itertools
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bantamkit.skillfile import (
    HASH_KEY,
    SKILL_FILE,
    SkillFileError,
    backup_absent,
    backup_dir,
    backup_root,
    canonical_hash,
    is_edited,
    parse_skill,
    project_skills_root,
    read_state,
    skills_root,
    stamp,
    update_state,
    validate,
    write_dir_atomic,
)
from bantamkit.skillfile import (
    undo as undo_dir,
)
from bantamkit.storage.retention import parse_now

AUTO_ENV = "BANTAMKIT_SKILL_AUTO"
AUTO_PER_DAY = 1
AUTO_LIVE_MAX = 5
PROBATION_DAYS = 30
DAY_MS = 86_400_000
KEYWORDS_MAX = 16
#: Q8 (user ruling 2026-10-27): a project-level evidence file keeps the first 80 code points
#: of each prompt; a user-level one keeps up to the miner's `EVIDENCE_PROMPT_CHARS`.
EVIDENCE_PROJECT_CHARS = 80
EVIDENCE_USER_CHARS = 500
EVIDENCE_FILE = "references/evidence.md"
GENERATED_BY = "bantamkit"
LEVEL_PROJECT = "project"
LEVEL_USER = "user"
#: The statuses an automatic install may take a cluster from.
AUTO_FROM = ("new", "pending", "drafted")
#: How many automatic-install dates the state keeps (the per-day cap reads only today's).
AUTO_DATES_KEEP = 32
CORRECTED = "corrected in the next turn: "

_OFF = ("off", "0", "false", "no")
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")
_SAFE_INT = 2**53 - 1


class InstallError(SkillFileError):
    """The installer refuses; the message is the sentence."""


@dataclass(frozen=True)
class Installed:
    name: str
    level: str
    path: str
    event: str
    entry: dict[str, Any] = field(default_factory=dict)


def auto_enabled() -> bool:
    """False when `BANTAMKIT_SKILL_AUTO` is `off` (or `0`, `false`, `no`), any case."""
    return os.environ.get(AUTO_ENV, "").strip().lower() not in _OFF


def _clean(s: str) -> str:
    return _LONE_SURROGATE.sub("�", s)


def _int(v: Any) -> int | None:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return v if type(v) is int and 0 <= v <= _SAFE_INT else None


def _iso(ms: int) -> str:
    """`toISOString()`'s form: `YYYY-MM-DDTHH:MM:SS.mmmZ`."""
    t = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)
    return f"{t.strftime('%Y-%m-%dT%H:%M:%S')}.{t.microsecond // 1000:03d}Z"


def _ms(now: str) -> int:
    try:
        return parse_now(now)
    except ValueError as e:
        raise InstallError(f"not a timestamp: {now!r}") from e


def _strs(v: Any) -> list[str]:
    return [_clean(x) for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _cut(s: str, n: int) -> str:
    return s[:n]


# ------------------------------------------------------------------------------- evidence


def evidence_ids(cluster: Mapping[str, Any]) -> list[str]:
    """The record's evidence ids, in record order, each once."""
    out: list[str] = []
    for e in cluster.get("evidence") or []:
        if isinstance(e, dict) and isinstance(e.get("id"), str) and e["id"]:
            i = _clean(e["id"])
            if i not in out:
                out.append(i)
    return out


def _quote(text: str) -> list[str]:
    return ["  > " + line if line else "  >" for line in text.split("\n")]


def _failure_note(failure: str, n: int) -> str:
    if failure.startswith(CORRECTED):
        return CORRECTED + _cut(failure[len(CORRECTED) :], n)
    return _cut(failure, n)


def evidence_markdown(cluster: Mapping[str, Any], name: str, level: str) -> str:
    """`references/evidence.md` for one proposals record: named fields only (X4)."""
    n = EVIDENCE_PROJECT_CHARS if level == LEVEL_PROJECT else EVIDENCE_USER_CHARS
    cid = _clean(cluster["id"]) if isinstance(cluster.get("id"), str) else ""
    source = _clean(cluster["source"]) if isinstance(cluster.get("source"), str) else ""
    successes = _int(cluster.get("successes"))
    members = _int(cluster.get("members"))
    lines = [
        f"# Evidence: {_clean(name)}",
        "",
        f"Cluster `{cid}` ({source}): {successes if successes is not None else 0} successful "
        f"of {members if members is not None else 0} pieces of work, {level} level.",
        f"Every step in SKILL.md cites one of the ids below. Prompts are cut to {n} characters.",
    ]
    for e in cluster.get("evidence") or []:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not e["id"]:
            continue
        ok = e.get("ok")
        result = "success" if ok is True else "failure" if ok is False else "not known"
        signals = e.get("signals") if isinstance(e.get("signals"), dict) else {}
        on = [_clean(k) for k in sorted(signals) if isinstance(k, str) and signals[k] is True]
        tools = _strs(e.get("tools"))
        paths = _strs(e.get("paths"))
        commits = _strs(e.get("commits"))
        ts = _clean(e["ts"]) if isinstance(e.get("ts"), str) else ""
        lines += [
            "",
            f"## {_clean(e['id'])}",
            "",
            f"- Result: {result}",
            f"- Time: {ts or 'not known'}",
            f"- Signals: {', '.join(on) if on else 'none'}",
            f"- Tools: {', '.join(tools) if tools else 'none'}",
            f"- Paths: {', '.join(f'`{p}`' for p in paths) if paths else 'none'}",
        ]
        if commits:
            lines.append("- Commits:")
            lines += [f"  - {c}" for c in commits]
        if isinstance(e.get("failure"), str) and e["failure"]:
            lines.append(f"- Failure: {_failure_note(_clean(e['failure']), n)}")
        prompt = _cut(_clean(e["prompt"]), n) if isinstance(e.get("prompt"), str) else ""
        if prompt:
            lines.append("- Prompt:")
            lines.append("")
            lines += _quote(prompt)
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------------------- install


def install_root(
    cluster: Mapping[str, Any], level_override: str | None, home: str | Path
) -> tuple[str, Path]:
    """`(level, skills root)`: the override, else the record's level (project only with a top)."""
    if level_override not in (None, LEVEL_PROJECT, LEVEL_USER):
        raise InstallError("level must be project or user")
    level = level_override or (
        LEVEL_PROJECT if cluster.get("level") == LEVEL_PROJECT else LEVEL_USER
    )
    if level == LEVEL_USER:
        return level, skills_root(home)
    top = cluster.get("top")
    if not isinstance(top, str) or not top:
        cid = cluster.get("id") if isinstance(cluster.get("id"), str) else ""
        raise InstallError(f"cluster {cid} names no project to install into")
    return level, project_skills_root(top)


def skill_text(cluster: Mapping[str, Any], text: str) -> str:
    """The draft stamped with bantamkit's metadata and, last, its hash."""
    keywords = _strs(cluster.get("keywords"))[:KEYWORDS_MAX]
    return stamp(
        _clean(text),
        {
            "bantamkit-cluster": _clean(cluster["id"]),
            "bantamkit-evidence": ",".join(evidence_ids(cluster)),
            "bantamkit-generated-by": GENERATED_BY,
            "bantamkit-keywords": ",".join(keywords),
            "bantamkit-version": "1",
        },
    )


_counter = itertools.count(1)


def _remove_dir(target: Path) -> None:
    """Out of the way in one rename (a name the `[skill]` layer passes over), then deleted."""
    aside = f"{target}.old-{os.getpid()}-{next(_counter)}"
    os.rename(target, aside)
    shutil.rmtree(aside, ignore_errors=True)


def _drop_backup(backup: Path) -> None:
    """The backup an install took, and its name's directory when that leaves it empty."""
    shutil.rmtree(backup, ignore_errors=True)
    try:
        os.rmdir(backup.parent)
    except OSError:
        pass


def install(
    cluster: dict[str, Any],
    text: str,
    level_override: str | None,
    home: str | Path,
    now: str,
    auto: bool,
) -> Installed:
    """One skill installed from a gated draft, or nothing at all (InstallError / the failure).

    The record is marked `installed` in place; the caller writes the proposals file.
    """
    cid = cluster.get("id")
    if not isinstance(cid, str) or not cid:
        raise InstallError("the cluster has no id")
    now_ms = _ms(now)
    level, root = install_root(cluster, level_override, home)
    try:
        doc = parse_skill(_clean(text))
    except SkillFileError as e:
        raise InstallError(str(e)) from e
    reasons = validate(doc)
    if reasons:
        raise InstallError(reasons[0])
    name = doc.name
    if name in read_state(home)["skills"]:
        raise InstallError(f"a skill named {name!r} is already installed")
    target = root / name
    if os.path.lexists(target):
        raise InstallError(f"a skill already exists at {target}")
    try:
        skill = skill_text(cluster, text)
    except SkillFileError as e:
        raise InstallError(str(e)) from e
    files = {
        SKILL_FILE: skill.encode("utf-8"),
        EVIDENCE_FILE: evidence_markdown(cluster, name, level).encode("utf-8"),
    }
    entry: dict[str, Any] = {
        "at": now,
        "auto": auto,
        "cluster": _clean(cid),
        "level": level,
        "name": name,
        "path": str(target),
        "sha256": canonical_hash(skill),
        "version": 1,
        "versions": {"1": {"false_fires": 0, "injects": 0, "successes": 0, "uses": 0}},
    }
    if auto:
        entry["probation_until"] = _iso(now_ms + PROBATION_DAYS * DAY_MS)
    backup = backup_absent(backup_root(home), name, now)
    try:
        write_dir_atomic(target, files)
    except BaseException:
        _drop_backup(backup)
        raise

    def add(state: dict[str, Any]) -> None:
        if name in state["skills"]:
            raise InstallError(f"a skill named {name!r} is already installed")
        state["skills"][name] = entry
        if auto:
            dates = [d for d in state.get("auto_dates", []) if isinstance(d, str)]
            state["auto_dates"] = [*dates, _iso(now_ms)[:10]][-AUTO_DATES_KEEP:]

    try:
        update_state(home, add)
    except BaseException:
        _remove_dir(target)
        _drop_backup(backup)
        raise
    cluster["status"] = "installed"
    return Installed(name, level, str(target), f"installed skill {name}", entry)


# ------------------------------------------------------------------------------ auto step


def draft_entry(drafter: str | None, text: str | None, now: str) -> dict[str, Any] | None:
    """What a proposals record's `draft` holds once a draft passed the gate; None otherwise."""
    if not isinstance(text, str):
        return None
    return {"drafter": drafter, "ok": True, "text": text, "ts": now}


def _draft_text(rec: Mapping[str, Any]) -> str | None:
    d = rec.get("draft")
    if isinstance(d, dict) and d.get("ok") is True and isinstance(d.get("text"), str):
        return d["text"]
    return None


def _auto_ready(rec: Any) -> bool:
    if not isinstance(rec, dict) or rec.get("auto_eligible") is not True:
        return False
    successes, auto_bar = _int(rec.get("successes")), _int(rec.get("auto_bar"))
    return (
        successes is not None
        and auto_bar is not None
        and successes >= auto_bar
        and rec.get("status") in AUTO_FROM
        and isinstance(rec.get("id"), str)
        and _draft_text(rec) is not None
    )


def _first_ts(rec: Mapping[str, Any]) -> str:
    ts = [
        e["ts"]
        for e in rec.get("evidence") or []
        if isinstance(e, dict) and isinstance(e.get("ts"), str)
    ]
    return min(ts) if ts else ""


def live_auto(state: Mapping[str, Any]) -> list[str]:
    """The names of the live automatic installs, code-point order."""
    skills = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    return sorted(n for n, e in skills.items() if isinstance(e, dict) and e.get("auto") is True)


def auto_step(
    proposals: dict[str, Any], state: dict[str, Any], home: str | Path, now: str
) -> list[str]:
    """At most one automatic install; the events for the SessionStart line.

    `state` is the skills state the decision reads (the caller's fresh read); it is replaced in
    place by the state written. Records are changed in place (`installed`, or `failed`).
    """
    if not auto_enabled():
        return []
    today = _iso(_ms(now))[:10]
    dates = state.get("auto_dates") if isinstance(state.get("auto_dates"), list) else []
    if sum(1 for d in dates if d == today) >= AUTO_PER_DAY:
        return []
    if len(live_auto(state)) >= AUTO_LIVE_MAX:
        return []
    clusters = proposals.get("clusters") if isinstance(proposals.get("clusters"), list) else []
    ready = [r for r in clusters if _auto_ready(r)]
    ready.sort(key=lambda r: (-_int(r["successes"]), _first_ts(r), r["id"]))  # type: ignore[operator]
    for rec in ready:
        try:
            got = install(rec, _draft_text(rec), None, home, now, auto=True)  # type: ignore[arg-type]
        except InstallError:
            rec["status"] = "failed"
            continue
        fresh = read_state(home)
        state.clear()
        state.update(fresh)
        return [got.event]
    return []


# ------------------------------------------------------------------------------ probation


def probation_step(
    state: dict[str, Any], uses: Mapping[str, int], home: str | Path, now: str
) -> list[str]:
    """Probation for every live automatic install; the events.

    `uses[name]` counts the skill's uses since it was installed (R10). `state` is read for the
    decisions and replaced in place by the state written.
    """
    now_ms = _ms(now)
    skills = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    used: list[str] = []
    removed: list[str] = []
    proposed: list[str] = []
    gone: list[str] = []
    events: list[str] = []
    for name in sorted(skills):
        e = skills[name]
        if not isinstance(e, dict) or e.get("auto") is not True:
            continue
        until = e.get("probation_until")
        if not isinstance(until, str):
            continue
        if (_int(uses.get(name)) or 0) > 0:
            used.append(name)
            continue
        try:
            if parse_now(until) > now_ms:
                continue
        except ValueError:
            continue
        target = Path(e["path"]) if isinstance(e.get("path"), str) else None
        if target is None or not (target / SKILL_FILE).is_file():
            gone.append(name)
            continue
        raw = (target / SKILL_FILE).read_bytes()
        try:
            text = raw.decode("utf-8")
            edited = is_edited(text) or canonical_hash(text) != e.get("sha256")
        except UnicodeDecodeError:
            edited = True
        if edited:
            proposed.append(name)
            events.append(f"proposed removing edited skill {name}")
            continue
        backup_dir(backup_root(home), target, now)
        _remove_dir(target)
        removed.append(name)
        events.append(f"removed unused skill {name}")
    if not (used or removed or proposed or gone):
        return events

    def change(fresh: dict[str, Any]) -> None:
        live = fresh["skills"]
        for name in used:
            if isinstance(live.get(name), dict):
                live[name].pop("probation_until", None)
        for name in proposed:
            if isinstance(live.get(name), dict):
                live[name].pop("probation_until", None)
                live[name]["proposal"] = {"at": now, "kind": "remove", "status": "pending"}
        for name in removed:
            if name in live:
                gone_entry = live.pop(name)
                if not isinstance(fresh.get("removed"), dict):
                    fresh["removed"] = {}
                fresh["removed"][name] = gone_entry
        for name in gone:
            live.pop(name, None)

    written = update_state(home, change)
    state.clear()
    state.update(written)
    return events


# ----------------------------------------------------------------------------------- undo


def undo(name: str, home: str | Path) -> str:
    """Put back the newest backup of `name` (`skillfile.undo`) and the state with it; one sentence.

    The backup an install takes is "absent", so undo right after an install removes the skill
    and its state entry. The backup probation takes is the directory, so undo after a removal
    brings the skill back byte for byte, with its state entry, off probation.
    """
    state = read_state(home)
    live = state["skills"].get(name)
    gone = state.get("removed", {}).get(name) if isinstance(state.get("removed"), dict) else None
    src = live if isinstance(live, dict) else gone if isinstance(gone, dict) else None
    if src is None or not isinstance(src.get("path"), str):
        raise InstallError(f"no skill named {name!r} is installed")
    target = Path(src["path"])
    said = undo_dir(backup_root(home), name, target)
    restored = None
    if os.path.isfile(target / SKILL_FILE):
        try:
            stored = parse_skill((target / SKILL_FILE).read_bytes().decode("utf-8")).metadata.get(
                HASH_KEY
            )
            restored = stored if isinstance(stored, str) else None
        except (SkillFileError, UnicodeDecodeError):
            restored = None

    def change(fresh: dict[str, Any]) -> None:
        removed = fresh.get("removed") if isinstance(fresh.get("removed"), dict) else {}
        if not os.path.lexists(target):
            fresh["skills"].pop(name, None)
            removed.pop(name, None)
        else:
            entry = fresh["skills"].get(name)
            if not isinstance(entry, dict):
                entry = removed.pop(name, None)
                if not isinstance(entry, dict):
                    return
                entry.pop("probation_until", None)
                entry.pop("proposal", None)
                fresh["skills"][name] = entry
            if restored is not None:
                entry["sha256"] = restored
        if "removed" in fresh:
            fresh["removed"] = removed

    update_state(home, change)
    return said
