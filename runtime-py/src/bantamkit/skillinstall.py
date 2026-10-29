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
`BANTAMKIT_SKILL_AUTO` is `on` (or `1`, `true`, `yes`, any case, trimmed: it is OFF by default
in 0.37.0, and any other value, unset or empty included, leaves it off); the cluster has twice the
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

import hashlib
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
    replace_dir_atomic,
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
#: The `skills:` status line's last clause, by the switch (0.37.0: off unless opted in).
AUTO_SAID_ON = "auto on"
AUTO_SAID_OFF = f"auto off ({AUTO_ENV}=on to opt in)"
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

#: The only values that turn automatic installs and edits on (0.37.0: opt-in). Any other value,
#: `off`/`0`/`false`/`no`, an empty one, an unknown word or none at all, leaves them off — the
#: parse `BANTAMKIT_EVENT_LOG`'s in-store switch uses, so a typo never opts anyone in.
_ON = ("on", "1", "true", "yes")
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
    """True only when `BANTAMKIT_SKILL_AUTO` is `on` (or `1`, `true`, `yes`), any case, trimmed.

    The default is OFF (#206 release train: the real-use bar was not met before 0.37.0, so the
    default changed). It gates the automatic installs (`auto_step`), the daily draft for them,
    and the automatic edits of `improve_step`; the judge and its rollback do not read it.
    """
    return os.environ.get(AUTO_ENV, "").strip().lower() in _ON


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
            edited = (
                e.get("edited") is True
                or is_edited(text)
                or canonical_hash(text) != e.get("sha256")
            )
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
    restored_version = None
    if os.path.isfile(target / SKILL_FILE):
        try:
            metadata = parse_skill((target / SKILL_FILE).read_bytes().decode("utf-8")).metadata
            stored = metadata.get(HASH_KEY)
            raw_version = metadata.get("bantamkit-version")
            if isinstance(raw_version, str) and re.fullmatch(r"[1-9][0-9]*", raw_version):
                restored_version = int(raw_version)
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
            if restored_version is not None:
                entry["version"] = restored_version
        if "removed" in fresh:
            fresh["removed"] = removed

    update_state(home, change)
    return said


# ------------------------------------------------------------- self-improvement (Task 10a)
#
# VERSIONS. `entry.version` is the live version N; `entry.versions["<k>"]` holds each
# version's counters `{uses, successes, injects, false_fires}` and, from v2 on, `at` (when it
# went live), `from` (the version it was made from: the one it is judged against) and `kind`
# (`auto` or `approved`). A version is frozen the moment another one goes live: `stats_step`
# only ever counts into the live one. Every earlier SKILL.md is kept under
# `references/history/v<k>.md`.
#
# COUNTING (`stats_step`, R10). Rows are counted into the live version once, after the
# skill's watermark `counted_to` (or from the version's `at`, else the install's `at`, when
# there is none yet) and up to `now`: a `uses` row is a session's use of the skill (the touch
# log's `use` rows); `successes` are the uses whose turn of work (the session's latest piece
# at or before the use) succeeded; `injects` are the hook log's injections naming it;
# `false_fires` the injections in a session that never used it.
#
# THE JUDGE (`judge_step`). A live version N >= 2 with no verdict is judged once it has
# `JUDGE_USES` uses, against the version it was made from, on integers (cross-multiplied; a
# rate over zero injections is 0): a success rate that fell strictly, or a false-fire rate
# that rose strictly, rolls it back to that version (its history file, restamped, as
# SKILL.md; N kept as `references/history/v<N>.md`), with the event
# `rolled back <name> to v<F>`; anything else keeps it. Never on an edited skill.
#
# THE EDITED GUARD (R8). A skill whose SKILL.md no longer matches its hash was changed by
# hand: `new_version` refuses it and `judge_step` passes it over, so it only ever receives
# proposals.

JUDGE_USES = 5
VERDICT_KEPT = "kept"
VERDICT_ROLLED_BACK = "rolled back"
HISTORY_DIR = "references/history"
VERSION_KINDS = ("auto", "approved")
_COUNTERS = ("false_fires", "injects", "successes", "uses")
_TURN_ID = re.compile(r"s([\s\S]{1,8})#([0-9]{1,15})")
_VERSION_KEY = re.compile(r"[0-9]{1,15}")


def _dir_files(root: Path) -> dict[str, bytes]:
    """Every regular file under `root`, by `/`-joined relative path; symlinks not followed."""
    out: dict[str, bytes] = {}

    def walk(d: Path, rel: str) -> None:
        for entry in sorted(os.listdir(d)):
            p = d / entry
            if p.is_symlink():
                continue
            if p.is_dir():
                walk(p, f"{rel}{entry}/")
            elif p.is_file():
                out[f"{rel}{entry}"] = p.read_bytes()

    walk(root, "")
    return out


def _live_text(entry: Mapping[str, Any]) -> tuple[Path, bytes] | None:
    """`(skill dir, SKILL.md bytes)` of an entry, or None when there is no SKILL.md."""
    if not isinstance(entry.get("path"), str):
        return None
    target = Path(entry["path"])
    try:
        return target, (target / SKILL_FILE).read_bytes()
    except OSError:
        return None


def _edited_bytes(raw: bytes, entry: Mapping[str, Any]) -> bool:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return is_edited(text) or canonical_hash(text) != entry.get("sha256")


def _edited(raw: bytes, entry: Mapping[str, Any]) -> bool:
    """Edited by hand now (R8), or ever (`edited`, kept once a person's change was approved
    over a hand-edited skill: X10's "never changed automatically again")."""
    return entry.get("edited") is True or _edited_bytes(raw, entry)


def edited_by_hand(entry: Mapping[str, Any]) -> bool | None:
    """True when the skill's SKILL.md no longer matches its hash (R8), or once was (`edited`);
    None without a SKILL.md."""
    live = _live_text(entry)
    return None if live is None else _edited(live[1], entry)


def _ts(v: Any) -> int | None:
    try:
        return parse_now(v)
    except ValueError:
        return None


def _rows(sources: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    v = sources.get(key) if isinstance(sources, Mapping) else None
    return [r for r in v if isinstance(r, dict)] if isinstance(v, list) else []


def _turns(sources: Mapping[str, Any]) -> dict[str, list[tuple[int, int, bool]]]:
    """Per session prefix (`s<8>`): `(ts ms, ordinal, ok)` of each turn, sorted."""
    out: dict[str, list[tuple[int, int, bool]]] = {}
    for t in _rows(sources, "turns"):
        m = _TURN_ID.fullmatch(t["id"]) if isinstance(t.get("id"), str) else None
        at = _ts(t.get("ts"))
        if m is None or at is None:
            continue
        out.setdefault(m.group(1), []).append((at, int(m.group(2)), t.get("ok") is True))
    for v in out.values():
        v.sort()
    return out


def _turn_ok(turns: Mapping[str, list[tuple[int, int, bool]]], session: str, at: int) -> bool:
    """Did the session's latest turn at or before `at` succeed?"""
    best = None
    for t in turns.get(session[:8], []):
        if t[0] <= at:
            best = t
    return best is not None and best[2]


def stats_step(
    state: dict[str, Any], sources: Mapping[str, Any], home: str | Path, now: str
) -> None:
    """Count the new rows of `sources` into each live skill's live version (see above).

    `sources` is `{"uses": [{ts, session, fact}], "injects": [{ts, session, names}],
    "turns": [{id, ts, ok}]}` (`skillmine.improve_sources` reads them off disk). `state` is
    read for the decisions and replaced in place by the state written.
    """
    now_ms = _ms(now)
    uses = [
        (u["fact"], u["session"], at)
        for u in _rows(sources, "uses")
        if isinstance(u.get("fact"), str)
        and isinstance(u.get("session"), str)
        and u["session"]
        and (at := _ts(u.get("ts"))) is not None
    ]
    injects = [
        (frozenset(n for n in i["names"] if isinstance(n, str)), i["session"], at)
        for i in _rows(sources, "injects")
        if isinstance(i.get("names"), list)
        and isinstance(i.get("session"), str)
        and i["session"]
        and (at := _ts(i.get("ts"))) is not None
    ]
    turns = _turns(sources)
    skills = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    counts: dict[str, tuple[int, dict[str, int]]] = {}
    for name in sorted(skills):
        e = skills[name]
        n = _int(e.get("version")) if isinstance(e, dict) else None
        if n is None or n < 1:
            continue
        versions = e.get("versions") if isinstance(e.get("versions"), dict) else {}
        v = versions.get(str(n)) if isinstance(versions.get(str(n)), dict) else {}
        mark = _ts(e.get("counted_to"))
        start = _ts(v.get("at")) if isinstance(v.get("at"), str) else _ts(e.get("at"))
        if mark is None and start is None:
            continue

        def inside(at: int, mark: int | None = mark, start: int | None = start) -> bool:
            if at > now_ms:
                return False
            return at > mark if mark is not None else at >= start  # type: ignore[operator]

        mine = [(s, at) for f, s, at in uses if f == name and inside(at)]
        used_in = {s for f, s, _ in uses if f == name}
        fired = [s for names, s, at in injects if name in names and inside(at)]
        counts[name] = (
            n,
            {
                "false_fires": sum(1 for s in fired if s not in used_in),
                "injects": len(fired),
                "successes": sum(1 for s, at in mine if _turn_ok(turns, s, at)),
                "uses": len(mine),
            },
        )
    if not counts:
        return

    def change(fresh: dict[str, Any]) -> None:
        for name, (n, add) in counts.items():
            e = fresh["skills"].get(name)
            if not isinstance(e, dict) or _int(e.get("version")) != n:
                continue
            if not isinstance(e.get("versions"), dict):
                e["versions"] = {}
            v = e["versions"].get(str(n))
            if not isinstance(v, dict):
                v = e["versions"][str(n)] = {}
            for k in _COUNTERS:
                v[k] = (_int(v.get(k)) or 0) + add[k]
            e["counted_to"] = now

    written = update_state(home, change)
    state.clear()
    state.update(written)


def _carried(old_text: str, doc_metadata: Mapping[str, Any]) -> dict[str, str]:
    """bantamkit's own keys of the live version, kept across a new one; the new text may
    bring its own keywords and evidence ids."""
    try:
        old = parse_skill(old_text).metadata
    except SkillFileError:
        old = {}
    out = {
        k: v
        for k, v in old.items()
        if k.startswith("bantamkit-") and k != HASH_KEY and isinstance(v, str)
    }
    for k in ("bantamkit-evidence", "bantamkit-keywords"):
        if isinstance(doc_metadata.get(k), str):
            out[k] = doc_metadata[k]
    return out


def new_version(
    name: str, text: str, home: str | Path, now: str, kind: str, base: str | None = None
) -> str:
    """The live skill `name` replaced by `text` as its next version; one sentence.

    Refused (InstallError) when `kind` is not `auto` or `approved`, the skill is not
    installed or has no SKILL.md, it was edited by hand (R8), `text` is not a valid skill or
    names another one, or its history already holds a different copy of the live version.
    The live SKILL.md goes to `references/history/v<N>.md` and the new one in, in ONE
    directory swap (a backup is taken first); a failure leaves the skill as it was.
    """
    if kind not in VERSION_KINDS:
        raise InstallError("kind must be auto or approved")
    _ms(now)
    entry = read_state(home)["skills"].get(name)
    if not isinstance(entry, dict):
        raise InstallError(f"no skill named {name!r} is installed")
    live = _live_text(entry)
    if live is None:
        raise InstallError(f"skill {name} has no SKILL.md at {entry.get('path')}")
    target, raw = live
    if base is not None and hashlib.sha256(raw).hexdigest() != base:
        raise InstallError(
            f"{name} changed after this change was proposed; reject it and wait for a new one"
        )
    was_edited = _edited(raw, entry)
    if was_edited and not (kind == "approved" and base is not None):
        raise InstallError(f"{name} was edited by hand; it only receives proposed changes")
    try:
        doc = parse_skill(_clean(text))
    except SkillFileError as e:
        raise InstallError(str(e)) from e
    reasons = validate(doc)
    if reasons:
        raise InstallError(reasons[0])
    if doc.name != name:
        raise InstallError(f"the new version is named {doc.name!r}, not {name!r}")
    n = _int(entry.get("version")) or 1
    versions = entry.get("versions") if isinstance(entry.get("versions"), dict) else {}
    known = [int(k) for k in versions if isinstance(k, str) and _VERSION_KEY.fullmatch(k)]
    m = max([n, *known]) + 1
    updates = _carried(raw.decode("utf-8"), doc.metadata)
    updates["bantamkit-version"] = str(m)
    try:
        new_text = stamp(_clean(text), updates)
    except SkillFileError as e:
        raise InstallError(str(e)) from e
    files = _dir_files(target)
    hist = f"{HISTORY_DIR}/v{n}.md"
    if hist in files and files[hist] != raw:
        raise InstallError(f"history already holds v{n} of {name}")
    files[hist] = raw
    files[SKILL_FILE] = new_text.encode("utf-8")
    replace_dir_atomic(target, files, backup_root(home), now)

    def change(fresh: dict[str, Any]) -> None:
        e = fresh["skills"].get(name)
        if not isinstance(e, dict):
            raise InstallError(f"no skill named {name!r} is installed")
        if not isinstance(e.get("versions"), dict):
            e["versions"] = {}
        e["versions"][str(m)] = {
            "at": now,
            "false_fires": 0,
            "from": n,
            "injects": 0,
            "kind": kind,
            "successes": 0,
            "uses": 0,
        }
        e["version"] = m
        e["sha256"] = canonical_hash(new_text)
        e["counted_to"] = now
        if was_edited:
            e["edited"] = True

    try:
        update_state(home, change)
    except BaseException:
        undo_dir(backup_root(home), name, target)
        raise
    return f"updated skill {name} to v{m}"


def _fell(s_n: int, u_n: int, s_f: int, u_f: int) -> bool:
    """`s_n/u_n < s_f/u_f` on integers; a rate over no uses is 0."""
    if u_n == 0:
        return False
    if u_f == 0:
        return False
    return s_n * u_f < s_f * u_n


def _rose(f_n: int, i_n: int, f_f: int, i_f: int) -> bool:
    """`f_n/i_n > f_f/i_f` on integers; a rate over no injections is 0."""
    if i_n == 0:
        return False
    if i_f == 0:
        return f_n > 0
    return f_n * i_f > f_f * i_n


def _tally(v: Mapping[str, Any], k: str) -> int:
    return _int(v.get(k)) or 0


def judge_step(state: dict[str, Any], home: str | Path, now: str) -> list[str]:
    """Judge every live version that has reached `JUDGE_USES` uses (see above); the events.

    `state` is read for the decisions and replaced in place by the state written. A rollback
    whose directory swap fails leaves the skill as it was, unjudged, for the next run.
    """
    _ms(now)
    skills = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    verdicts: dict[str, tuple[int, str, int, str | None]] = {}
    events: list[str] = []
    for name in sorted(skills):
        e = skills[name]
        if not isinstance(e, dict):
            continue
        n = _int(e.get("version"))
        versions = e.get("versions") if isinstance(e.get("versions"), dict) else {}
        v = versions.get(str(n)) if n is not None else None
        if n is None or n < 2 or not isinstance(v, dict) or "verdict" in v:
            continue
        f = _int(v.get("from"))
        f = n - 1 if f is None else f
        base = versions.get(str(f))
        if not isinstance(base, dict) or _tally(v, "uses") < JUDGE_USES:
            continue
        live = _live_text(e)
        if live is None or _edited(live[1], e):
            continue
        worse = _fell(
            _tally(v, "successes"), _tally(v, "uses"),
            _tally(base, "successes"), _tally(base, "uses"),
        ) or _rose(
            _tally(v, "false_fires"), _tally(v, "injects"),
            _tally(base, "false_fires"), _tally(base, "injects"),
        )  # fmt: skip
        if not worse:
            verdicts[name] = (n, VERDICT_KEPT, n, None)
            continue
        target, raw = live
        try:
            old = (target / HISTORY_DIR / f"v{f}.md").read_bytes().decode("utf-8")
            restored = stamp(old, {})
            files = _dir_files(target)
            files[f"{HISTORY_DIR}/v{n}.md"] = raw
            files[SKILL_FILE] = restored.encode("utf-8")
            replace_dir_atomic(target, files, backup_root(home), now)
        except (OSError, UnicodeDecodeError, SkillFileError):
            continue
        verdicts[name] = (n, VERDICT_ROLLED_BACK, f, canonical_hash(restored))
        events.append(f"rolled back {name} to v{f}")
    if not verdicts:
        return events

    def change(fresh: dict[str, Any]) -> None:
        for name, (n, verdict, f, sha) in verdicts.items():
            e = fresh["skills"].get(name)
            if not isinstance(e, dict) or _int(e.get("version")) != n:
                continue
            v = e.get("versions", {}).get(str(n)) if isinstance(e.get("versions"), dict) else None
            if not isinstance(v, dict):
                continue
            v["verdict"] = verdict
            if verdict == VERDICT_ROLLED_BACK:
                e["version"] = f
                e["sha256"] = sha
                e["rolled_back"] = n
                e["counted_to"] = now

    written = update_state(home, change)
    state.clear()
    state.update(written)
    return events


# ------------------------------------------------------------- self-improvement (Task 10b)
#
# THE SIGNALS (`improve_step`, spec X10's table), each read once: rows after the skill's
# `improved_to` watermark (else from the live version's `at`, else the install's) and up to `now`.
#   - FALSE FIRE: the live version has `injects >= TUNE_MIN_INJECTS` and
#     `false_fires / injects > FALSE_FIRE_TUNE` (integers) -> NARROW its description.
#   - MISS: a session piece of the skill's cluster (the proposals record `entry.cluster`) in whose
#     session the skill was neither injected nor used; the live version's `misses` reach
#     `MISS_TUNE` -> WIDEN: the record's keywords that occur in the missed prompts join
#     `bantamkit-keywords` (at most `KEYWORDS_MAX`), and the description is widened.
#   - USED, THEN CORRECTED: a use whose turn (the session's latest piece at or before it) failed
#     -> one `## Pitfalls` line `- [<id>] <the correcting prompt's first line, or the failure>`
#     cut to `PITFALL_CHARS` code points, AND a proposed `## Steps` change.
#   - USED AND SUCCEEDED THROUGH DIFFERENT STEPS: the turn's tool n-grams share less than
#     `STEP_SHARE` with the record's recurring steps -> a proposed `## Steps` change.
#   - FIRE TOGETHER: two live skills injected together in at least `TOGETHER_SESSIONS` sessions,
#     that being at least half of each one's injecting sessions -> a proposed merge.
# THE SPLIT BY RISK. The keyword widening and the Pitfalls line are deterministic and apply in
# the run; the description tunes need a drafter (`skilldraft.improve`, description only). With
# none that answers, the tune waits as `entry.tune = {at, kinds}` for the command to draft with
# the host agent and apply without asking. Everything a run applies to one skill is ONE new
# version (`auto`), gated first (`own` = the skill); a draft that fails the gate is logged and
# dropped, and the deterministic part is then gated and applied alone. A `## Steps` change and a
# merge NEED THE USER: `entry.proposal = {at, kind, status: "pending", ...}` (one slot per
# skill; a pending one is never replaced). A text proposal carries `text`, a unified `diff` and
# `base` (SHA-256 of the SKILL.md bytes it was built on): approving it applies it as an
# `approved` version only while the file is still those bytes.
# THE EDITED GUARD. On a skill edited by hand (`_edited`) nothing applies: the would-be version
# becomes an `improve` proposal, and an approved change keeps `edited` on the entry for good.
# THE SWITCH (0.37.0). Automatic edits follow `BANTAMKIT_SKILL_AUTO` (`auto_enabled`, OFF by
# default): with it off, nothing applies either — the run's would-be version becomes an
# `improve` proposal, a `## Steps` line due in the same run rides in that one proposal, and a
# tune with no drafter still waits as `entry.tune`. The judge and its rollback still run.

TUNE_MIN_INJECTS = 5
FALSE_FIRE_TUNE = (1, 2)
MISS_TUNE = 2
PITFALL_CHARS = 200
TOGETHER_SESSIONS = 5
TOGETHER_SHARE = (1, 2)
#: The needs-user item kinds `entry.proposal` may hold.
ITEM_KINDS = ("improve", "merge", "remove", "steps")
PITFALLS = "## Pitfalls"
STEPS = "## Steps"
_HEADING = re.compile(r"#{1,2}(?:[ \t]|$)")
_NUMBERED = re.compile(r"[ \t]{0,3}[0-9]{1,9}[.)](?:[ \t]|$)")
_EDGE = re.compile(r"^[ \t]+|[ \t]+$")


def pitfall_line(evidence_id: str, failure: str) -> str:
    """`- [<id>] <note>`: the correcting prompt's first line (or the failure's), cut."""
    note = failure[len(CORRECTED) :] if failure.startswith(CORRECTED) else failure
    note = _EDGE.sub("", _clean(note).split("\n")[0])
    return f"- [{_clean(evidence_id)}] {_cut(note, PITFALL_CHARS)}"


def append_to_section(body: str, heading: str, lines: list[str]) -> str:
    """`lines` after the last non-blank line of the `heading` section (a section of only
    `None.` has it replaced), or a new section at the end of the body."""
    ls = body.split("\n")
    idx = next((i for i, line in enumerate(ls) if line.rstrip(" \t") == heading), None)
    if idx is None:
        return (body.rstrip("\n") + "\n\n" if body else "") + heading + "\n\n" + "\n".join(lines)
    end = idx + 1
    while end < len(ls) and _HEADING.match(ls[end]) is None:
        end += 1
    content = [k for k in range(idx + 1, end) if ls[k].strip(" \t")]
    if len(content) == 1 and ls[content[0]].strip(" \t") == "None.":
        ls[content[0] : content[0] + 1] = lines
        return "\n".join(ls)
    at = content[-1] + 1 if content else idx + 1
    ins = list(lines) if content else ["", *lines]
    if at < len(ls) and ls[at].strip(" \t"):
        ins.append("")
    ls[at:at] = ins
    return "\n".join(ls)


def next_step_number(body: str) -> int:
    ls = body.split("\n")
    idx = next((i for i, line in enumerate(ls) if line.rstrip(" \t") == STEPS), None)
    if idx is None:
        return 1
    n = 0
    for line in ls[idx + 1 :]:
        if _HEADING.match(line):
            break
        n += _NUMBERED.match(line) is not None
    return n + 1


def _plain(text: str) -> list[str]:
    """The lines a diff compares: name, description and body, without the metadata bantamkit
    restamps on every write."""
    from bantamkit.skillfile import SkillDoc, render

    try:
        doc = parse_skill(text)
        text = render(SkillDoc(doc.name, doc.description, {}, doc.body))
    except SkillFileError:
        pass
    ls = text.split("\n")
    if ls and ls[-1] == "":
        ls.pop()
    return ls


def skill_diff(old: str, new: str) -> str:
    """One unified hunk (3 lines of context) from the first to the last differing line."""
    a, b = _plain(old), _plain(new)
    if a == b:
        return ""
    p = 0
    while p < len(a) and p < len(b) and a[p] == b[p]:
        p += 1
    s = 0
    while s < len(a) - p and s < len(b) - p and a[len(a) - 1 - s] == b[len(b) - 1 - s]:
        s += 1
    lo = max(0, p - 3)
    hi_a = min(len(a), len(a) - s + 3)
    hi_b = len(b) - s + (hi_a - (len(a) - s))
    out = ["--- a/SKILL.md", "+++ b/SKILL.md", f"@@ -{lo + 1},{hi_a - lo} +{lo + 1},{hi_b - lo} @@"]
    out += [" " + x for x in a[lo:p]]
    out += ["-" + x for x in a[p : len(a) - s]]
    out += ["+" + x for x in b[p : len(b) - s]]
    out += [" " + x for x in a[len(a) - s : hi_a]]
    return "\n".join(out)


def _csv(v: Any) -> list[str]:
    return [x for x in v.split(",") if x] if isinstance(v, str) else []


def _with(text: str, body: str | None, metadata: Mapping[str, str]) -> str:
    from bantamkit.skillfile import SkillDoc, render

    doc = parse_skill(text)
    return render(
        SkillDoc(
            doc.name,
            doc.description,
            {**doc.metadata, **metadata},
            doc.body if body is None else body,
        )
    )


def _with_step(text: str, tid: str, step: str) -> str:
    """`text` with `step` added as the next numbered line of `## Steps`, `tid` in its evidence."""
    doc = parse_skill(text)
    line = f"{next_step_number(doc.body)}. {step}"
    ids = _csv(doc.metadata.get("bantamkit-evidence"))
    if tid not in ids:
        ids.append(tid)
    body = append_to_section(doc.body, STEPS, [line])
    return _with(text, body, {"bantamkit-evidence": ",".join(ids)})


def _proposal(kind: str, raw: bytes, old: str, text: str, now: str) -> dict[str, Any]:
    return {
        "at": now,
        "base": hashlib.sha256(raw).hexdigest(),
        "diff": skill_diff(old, text),
        "kind": kind,
        "status": "pending",
        "text": text,
    }


def _slot_free(e: Mapping[str, Any]) -> bool:
    p = e.get("proposal")
    return not (isinstance(p, dict) and p.get("status") == "pending")


def _session_turns(
    sources: Mapping[str, Any],
) -> dict[str, list[tuple[int, int, Any, str, Any, list[str]]]]:
    """Per session prefix: `(ts ms, ordinal, ok, id, failure, tools)` of each turn, sorted."""
    out: dict[str, list[tuple[int, int, Any, str, Any, list[str]]]] = {}
    for t in _rows(sources, "turns"):
        m = _TURN_ID.fullmatch(t["id"]) if isinstance(t.get("id"), str) else None
        at = _ts(t.get("ts"))
        if m is None or at is None:
            continue
        out.setdefault(m.group(1), []).append(
            (at, int(m.group(2)), t.get("ok"), t["id"], t.get("failure"), _strs(t.get("tools")))
        )
    for v in out.values():
        v.sort(key=lambda r: (r[0], r[1]))
    return out


def apply_text(
    name: str,
    text: str,
    home: str | Path,
    cwd: str | None,
    now: str,
    b: Mapping[str, Any],
    auto: bool = True,
) -> tuple[str | None, list[str]]:
    """A low-risk change: gated (`own` = the skill), then the next `auto` version, or, on a
    skill edited by hand or with `auto` false (automatic edits off), an `improve` proposal.
    `(event, reasons)`; a gate failure is logged."""
    from bantamkit.skilldraft import DraftOutcome, drafts_log, gate
    from bantamkit.storage.logsegment import LogSegment

    entry = read_state(home)["skills"].get(name)
    live = _live_text(entry) if isinstance(entry, dict) else None
    if live is None:
        return None, [f"no skill named {name!r} is installed"]
    target, raw = live
    g = gate(text, b, home, cwd, own=target)
    if not g.ok:
        LogSegment(drafts_log(home)).append(
            DraftOutcome(None, False, None, g.reasons, []).log_line(now, b["cluster"])
        )
        return None, g.reasons
    if not auto or _edited(raw, entry):  # type: ignore[arg-type]
        if not _slot_free(entry):  # type: ignore[arg-type]
            return None, [f"a change to {name} already waits on you"]
        prop = _proposal("improve", raw, raw.decode("utf-8", "replace"), text, now)

        def put(fresh: dict[str, Any]) -> None:
            e = fresh["skills"].get(name)
            if isinstance(e, dict) and _slot_free(e):
                e["proposal"] = prop

        update_state(home, put)
        return f"proposed a change to {name}", []
    try:
        said = new_version(name, text, home, now, "auto")
    except InstallError as err:
        return None, [str(err)]
    return "improved skill " + said[len("updated skill ") :], []


def improve_step(
    state: dict[str, Any],
    sources: Mapping[str, Any],
    doc: Mapping[str, Any] | None,
    home: str | Path,
    cwd: str | None,
    now: str,
    chain: list[Any],
) -> list[str]:
    """The X10 signals for every live skill (see above); the events. `chain` holds the drafters
    that may answer in this process (the daily child: the endpoint, when configured). `state`
    is read for the decisions and replaced in place by the state written."""
    from bantamkit.memory.retrieval import tokenize_v2
    from bantamkit.skilldraft import TUNE_KINDS, TUNE_NARROW, TUNE_WIDEN, improve, improve_bundle
    from bantamkit.skillmine import STEP_SHARE, ngrams

    now_ms = _ms(now)
    auto = auto_enabled()
    skills = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    records: dict[str, dict[str, Any]] = {}
    clusters = doc.get("clusters") if isinstance(doc, Mapping) else None
    for r in clusters if isinstance(clusters, list) else []:
        if isinstance(r, dict) and isinstance(r.get("id"), str):
            records.setdefault(r["id"], r)
    uses = [
        (u["fact"], u["session"], at)
        for u in _rows(sources, "uses")
        if isinstance(u.get("fact"), str)
        and isinstance(u.get("session"), str)
        and u["session"]
        and (at := _ts(u.get("ts"))) is not None
        and at <= now_ms
    ]
    injects = [
        ({n for n in i["names"] if isinstance(n, str)}, i["session"], at)
        for i in _rows(sources, "injects")
        if isinstance(i.get("names"), list)
        and isinstance(i.get("session"), str)
        and i["session"]
        and (at := _ts(i.get("ts"))) is not None
        and at <= now_ms
    ]
    turns = _session_turns(sources)
    events: list[str] = []
    marks: dict[str, tuple[int, int, list[str], dict[str, Any] | None, dict[str, Any] | None]] = {}
    for name in sorted(skills):
        e = skills[name]
        n = _int(e.get("version")) if isinstance(e, dict) else None
        live = _live_text(e) if n is not None and n >= 1 else None
        if live is None:
            continue
        target, raw = live
        try:
            text = raw.decode("utf-8")
            sdoc = parse_skill(text)
        except (UnicodeDecodeError, SkillFileError):
            continue
        versions = e.get("versions") if isinstance(e.get("versions"), dict) else {}
        v = versions.get(str(n)) if isinstance(versions.get(str(n)), dict) else {}
        mark = _ts(e.get("improved_to"))
        start = _ts(v.get("at")) if isinstance(v.get("at"), str) else _ts(e.get("at"))
        if mark is None and start is None:
            continue

        def inside(at: int, mark: int | None = mark, start: int | None = start) -> bool:
            return at > mark if mark is not None else at >= start  # type: ignore[operator]

        rec = records.get(e["cluster"]) if isinstance(e.get("cluster"), str) else None
        seen = {s[:8] for f, s, _ in uses if f == name}
        seen |= {s[:8] for names, s, _ in injects if name in names}
        missed: list[dict[str, Any]] = []
        for ev in (rec.get("evidence") or []) if rec is not None else []:
            if not isinstance(ev, dict) or not isinstance(ev.get("id"), str):
                continue
            m = _TURN_ID.fullmatch(ev["id"])
            at = _ts(ev.get("ts"))
            if m is None or at is None or at > now_ms or not inside(at) or m.group(1) in seen:
                continue
            missed.append(ev)
        misses = _tally(v, "misses") + len(missed)
        tried = set(_strs(v.get("tried")))
        inj, ff = _tally(v, "injects"), _tally(v, "false_fires")
        tunes = []
        if inj >= TUNE_MIN_INJECTS and ff * FALSE_FIRE_TUNE[1] > inj * FALSE_FIRE_TUNE[0]:
            tunes.append(TUNE_NARROW)
        if misses >= MISS_TUNE:
            tunes.append(TUNE_WIDEN)
        tunes = [t for t in tunes if t not in tried]
        pits: list[tuple[str, str]] = []
        steps_from: tuple[int, str, str] | None = None
        recurring = set(_strs(rec.get("steps"))) if rec is not None else set()
        done: set[str] = set()
        for _f, s, at in sorted(
            (u for u in uses if u[0] == name and inside(u[2])), key=lambda u: (u[2], u[1])
        ):
            turn = None
            for t in turns.get(s[:8], []):
                if t[0] <= at:
                    turn = t
            if turn is None or turn[3] in done:
                continue
            done.add(turn[3])
            tid = turn[3]
            if turn[2] is False and isinstance(turn[4], str) and turn[4]:
                if f"[{tid}]" not in text:
                    pits.append((tid, turn[4]))
                    if steps_from is None:
                        note = pitfall_line(tid, turn[4]).split("] ", 1)[1]
                        steps_from = (
                            turn[0],
                            tid,
                            f"Before you finish, check for what [{tid}] was corrected for: {note}",
                        )
            elif turn[2] is True and recurring:
                grams = ngrams(turn[5])
                num, den = STEP_SHARE
                if grams and len(grams & recurring) * den < len(grams) * num and steps_from is None:
                    steps_from = (turn[0], tid, f"It also worked as {' > '.join(turn[5])} [{tid}].")
        kw = _csv(sdoc.metadata.get("bantamkit-keywords"))
        new_kw = list(kw)
        if TUNE_WIDEN in tunes and rec is not None:
            words = {
                t
                for ev in missed
                if isinstance(ev.get("prompt"), str)
                for t in tokenize_v2(ev["prompt"])
            }
            for k in _strs(rec.get("keywords")):
                if len(new_kw) >= KEYWORDS_MAX:
                    break
                if k in words and k not in new_kw and "," not in k:
                    new_kw.append(k)
        ids = _csv(sdoc.metadata.get("bantamkit-evidence"))
        new_ids = ids + [i for i, _ in pits if i not in ids]
        b = improve_bundle(
            rec, e.get("cluster") if isinstance(e.get("cluster"), str) else "", new_ids
        )
        changed = new_kw != kw or bool(pits)
        det = text
        if changed:
            body = (
                append_to_section(sdoc.body, PITFALLS, [pitfall_line(i, f) for i, f in pits])
                if pits
                else None
            )
            det = _with(
                text,
                body,
                {"bantamkit-evidence": ",".join(new_ids), "bantamkit-keywords": ",".join(new_kw)},
            )
        final = det if changed else None
        wait: list[str] = []
        if tunes:
            counts = {"false_fires": ff, "injects": inj, "misses": misses}
            out = improve(tunes, det, b, counts, chain, home, cwd, now, target) if chain else None
            if out is None or out.drafter is None:
                wait = [k for k in TUNE_KINDS if k in tunes]
            elif out.ok and out.text is not None:
                final = out.text
        if final is not None:
            drafted = final is not det
            folded = False
            if not auto and steps_from is not None:
                # automatic edits off: this change becomes the skill's ONE proposal, so the
                # steps line rides in it rather than being dropped for want of a free slot
                try:
                    final_s = _with_step(final, steps_from[1], steps_from[2])
                    det_s = _with_step(det, steps_from[1], steps_from[2]) if drafted else final_s
                except (UnicodeDecodeError, SkillFileError):
                    pass
                else:
                    final, det, folded = final_s, det_s, True
            event, _ = apply_text(name, final, home, cwd, now, b, auto)
            if event is None and drafted and changed:
                event, _ = apply_text(name, det, home, cwd, now, b, auto)
            if event is not None:
                events.append(event)
                if folded:
                    steps_from = None
        if wait:
            old = e.get("tune") if isinstance(e.get("tune"), dict) else {}
            kinds = [k for k in TUNE_KINDS if k in wait or k in _strs(old.get("kinds"))]
            if kinds != [k for k in TUNE_KINDS if k in _strs(old.get("kinds"))]:
                events.append(f"waiting on a drafter to tune {name}")
            tune = {"at": old["at"] if isinstance(old.get("at"), str) else now, "kinds": kinds}
        else:
            tune = None
        prop = None
        if steps_from is not None:
            fresh = read_state(home)["skills"].get(name)
            now_live = _live_text(fresh) if isinstance(fresh, dict) else None
            if now_live is not None and _slot_free(fresh):  # type: ignore[arg-type]
                try:
                    cur = now_live[1].decode("utf-8")
                    ptext = _with_step(cur, steps_from[1], steps_from[2])
                    prop = _proposal("steps", now_live[1], cur, ptext, now)
                    events.append(f"proposed a change to {name}")
                except (UnicodeDecodeError, SkillFileError):
                    prop = None
        marks[name] = (n, misses, sorted(tried | set(tunes)), tune, prop)

    # two skills that fire together: a proposed merge, on the first name
    fired: dict[str, set[str]] = {}
    for names, s, _ in injects:
        for nm in names:
            if nm in skills:
                fired.setdefault(nm, set()).add(s)
    merges: dict[str, str] = {}
    num, den = TOGETHER_SHARE
    for a in sorted(fired):
        for b2 in sorted(fired):
            if b2 <= a or a in merges:
                continue
            co = len(fired[a] & fired[b2])
            if (
                co < TOGETHER_SESSIONS
                or co * den < len(fired[a]) * num
                or co * den < len(fired[b2]) * num
            ):
                continue
            ea = skills.get(a)
            if (
                not isinstance(ea, dict)
                or not _slot_free(ea)
                or (marks.get(a) and marks[a][4] is not None)
            ):
                continue
            pa = ea.get("proposal")
            if isinstance(pa, dict) and pa.get("kind") == "merge" and pa.get("with") == b2:
                continue
            merges[a] = b2
            events.append(f"proposed merging {a} with {b2}")
    if not marks and not merges:
        return events

    def change(fresh: dict[str, Any]) -> None:
        for name, (n, misses, tried, tune, prop) in marks.items():
            e = fresh["skills"].get(name)
            if not isinstance(e, dict):
                continue
            e["improved_to"] = now
            if not isinstance(e.get("versions"), dict):
                e["versions"] = {}
            v = e["versions"].get(str(n))
            if not isinstance(v, dict):
                v = e["versions"][str(n)] = {}
            if misses:
                v["misses"] = misses
            if tried:
                v["tried"] = tried
            if tune is not None:
                e["tune"] = tune
            if prop is not None and _slot_free(e):
                e["proposal"] = prop
        for a, b2 in merges.items():
            e = fresh["skills"].get(a)
            if isinstance(e, dict) and _slot_free(e):
                e["proposal"] = {"at": now, "kind": "merge", "status": "pending", "with": b2}

    written = update_state(home, change)
    state.clear()
    state.update(written)
    return events
