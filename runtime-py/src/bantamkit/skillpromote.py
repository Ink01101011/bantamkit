"""Promotion and demotion of a learned skill (#206 Task 9, X8 second half).

A skill bantamkit installed lives in `.bantamkit/skills/<name>` and reaches the agent through
the `[skill]` recall layer, which costs no standing context. PROMOTION gives it a native link
the host loads every session:

    <base>/.claude/skills/<name>  ->  <base>/.bantamkit/skills/<name>

`<base>` is the directory that holds the skill's `.bantamkit` (the home for a user-level skill,
the project top for a project-level one), so the link is the RELATIVE path
`../../.bantamkit/skills/<name>`: the same bytes on every machine, and a project's link still
resolves after the checkout moves. Where the platform refuses a symlink for want of a right
(`EPERM`, `EACCES`, or Windows error 1314 without Developer Mode) the directory is COPIED
instead, built in a temp dir beside the target and renamed into place, and the copy's tree
hash is recorded so a later demotion can tell whether anyone changed it. Any other failure
(a missing parent, say) is refused, never copied.

THE ORDER OF REFUSALS (each a fixed sentence, `PromoteResult.reason`): the name is not an
installed skill; its source has no SKILL.md; the host is not Claude Code (`skillhost`'s Null
adapter: no skill directory to link into); the link path already holds something that is not
this skill's link (never overwritten); the catalogue budget. A link that is already this
skill's answers ok without writing anything.

THE BUDGET (user ruling Q4, 2026-10-27). Promotion is the only step that costs standing
context, so it alone is refused when the summed `description` bytes of every enabled skill the
host would load, with this one added, would exceed `BUDGET_DEFAULT` (8192) bytes, or the
`BANTAMKIT_SKILL_BUDGET` env value (a run of ASCII digits; anything else is the default). At
exactly the budget it passes. The sum is #205's own measure (`skillaudit.audit_roots`) over
the gatherer's roots, PLUS every symlinked skill directory directly inside the project and user
skills roots (the audit never walks into a symlinked directory, so without this a second
promotion would not see the first), PLUS the candidate. Roots are re-read at every call, so a
promotion made earlier in the same run is counted.

STATE. `skills-state.json` `skills[<name>].promoted` = `{at, link, mode}` (+ `tree_sha256`
for a copy). The `[skill]` layer reads that key live and leaves a promoted skill out; demotion
deletes it and the skill is back in the layer. `promote_step` records a refusal as
`promote_refused = {at, reason}` and does not try that skill again the same UTC day.

DEMOTION removes the link (or the copy, only while its tree hash still matches) and never
touches the source in `.bantamkit/skills`.

Promotion is automatic in the daily run (`promote_step`, Q5 default): a live skill with at
least `PROMOTE_USES` uses in the last `PROMOTE_DAYS` days; the caller counts the uses (R10).
Like the automatic installs and edits, it follows `BANTAMKIT_SKILL_AUTO`
(`skillinstall.auto_enabled`, OFF by default in 0.37.0; job73 ruling): with the switch off,
`promote_step` promotes nothing and records nothing as refused. `promote` itself (what
`skill_propose promote <name>` calls) never reads the switch, because the person asked.

`runtime-ts/src/skillpromote.ts` is the port; `tools/conformance/suites/skill-promote.mjs`
compares the two.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bantamkit.skillaudit import audit_roots
from bantamkit.skillfile import (
    SKILL_FILE,
    SkillFileError,
    read_state,
    update_state,
    write_dir_atomic,
)
from bantamkit.skillhost import HOST_CLAUDE_CODE, Gathered, select_adapter
from bantamkit.skillinstall import _int, _iso, _ms, _remove_dir, auto_enabled

PROMOTE_USES = 3
PROMOTE_DAYS = 30
BUDGET_ENV = "BANTAMKIT_SKILL_BUDGET"
BUDGET_DEFAULT = 8192
MODE_SYMLINK = "symlink"
MODE_COPY = "copy"
#: Windows `ERROR_PRIVILEGE_NOT_HELD`: a symlink without Developer Mode or admin rights.
WIN_PRIVILEGE = 1314
#: The symlink failures that mean "no right to link here": the directory is copied instead.
NO_RIGHT = (errno.EPERM, errno.EACCES)
CANDIDATE_LABEL = "candidate"

_DIGITS = re.compile(r"[0-9]{1,15}")

Symlink = Callable[[str, str], None]


class PromoteError(SkillFileError):
    """Demotion refuses; the message is the sentence."""


@dataclass(frozen=True)
class PromoteResult:
    ok: bool
    mode: str | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "ok": self.ok, "reason": self.reason}


def skill_budget() -> int:
    """`BANTAMKIT_SKILL_BUDGET` when it is a run of ASCII digits, else `BUDGET_DEFAULT`."""
    raw = os.environ.get(BUDGET_ENV, "").strip()
    return int(raw) if _DIGITS.fullmatch(raw) else BUDGET_DEFAULT


def _symlink(target: str, link: str) -> None:
    os.symlink(target, link, target_is_directory=True)


def link_path(source: Path | str) -> Path:
    """`<base>/.claude/skills/<name>` for a source at `<base>/.bantamkit/skills/<name>`."""
    source = Path(source)
    return source.parents[2] / ".claude" / "skills" / source.name


def _files(root: Path) -> dict[str, bytes]:
    """Every regular file under `root`, by `/`-joined relative path; symlinks not followed."""
    out: dict[str, bytes] = {}

    def walk(d: Path, rel: str) -> None:
        for entry in sorted(os.listdir(d)):
            p = d / entry
            r = f"{rel}{entry}"
            if p.is_symlink():
                continue
            if p.is_dir():
                walk(p, r + "/")
            elif p.is_file():
                out[r] = p.read_bytes()

    walk(root, "")
    return out


def tree_hash(root: Path | str) -> str:
    """SHA-256 over `<rel>\\0<sha256 of the bytes>\\n` per file, code-point order of `rel`."""
    files = _files(Path(root))
    lines = "".join(f"{rel}\0{hashlib.sha256(files[rel]).hexdigest()}\n" for rel in sorted(files))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _real(p: Path | str) -> str:
    return os.path.realpath(p)


def _record(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    rec = entry.get("promoted")
    return rec if isinstance(rec, dict) else None


def _is_promoted(entry: Mapping[str, Any]) -> bool:
    return "promoted" in entry and entry["promoted"] is not None and entry["promoted"] is not False


def _ours(link: Path, source: Path, entry: Mapping[str, Any]) -> bool:
    if os.path.islink(link):
        return _real(link) == _real(source)
    rec = _record(entry)
    return (
        link.is_dir()
        and rec is not None
        and rec.get("mode") == MODE_COPY
        and rec.get("link") == str(link)
    )


def _code(e: OSError) -> str:
    return errno.errorcode.get(e.errno, "EUNKNOWN") if isinstance(e.errno, int) else "EUNKNOWN"


def _no_right(e: OSError) -> bool:
    return getattr(e, "winerror", None) == WIN_PRIVILEGE or e.errno in NO_RIGHT


def _roots(gathered: Gathered, home: Path, cwd: str | None) -> list[tuple[str, str]]:
    """The gatherer's root order (`plugins, project, user`), project and user re-read now."""
    roots = [(label, p) for label, p in gathered.roots if label == "plugins"]
    user = home / ".claude" / "skills"
    if cwd is not None:
        project = Path(cwd) / ".claude" / "skills"
        if _real(project) != _real(user) and project.is_dir():
            roots.append(("project", str(project)))
    if user.is_dir():
        roots.append(("user", str(user)))
    return roots


def catalogue_bytes(
    gathered: Gathered, home: Path | str, cwd: str | None, candidate: Path | str | None
) -> int:
    """The catalogue's description bytes the way #205 measures them, with the symlinked skill
    directories of the project and user roots, and `candidate` (a skill directory), added."""
    roots = _roots(gathered, Path(home), cwd)
    links: list[tuple[str, str]] = []
    for label, root in roots:
        if label == "plugins":
            continue
        for entry in sorted(os.listdir(root)):
            p = Path(root, entry)
            if p.is_symlink() and p.is_dir() and (p / SKILL_FILE).is_file():
                links.append((f"{label}-link-{entry}", str(p)))
    every = roots + links
    if candidate is not None:
        every.append((CANDIDATE_LABEL, str(candidate)))
    if not every:
        return 0
    return audit_roots(
        every,
        enabled=list(gathered.enabled),
        check="budget",
        versions=gathered.versions,
    ).catalogue_bytes


def promote(
    name: str,
    home: Path | str,
    cwd: str | None,
    now: str,
    budget: int | None = None,
    *,
    symlink: Symlink | None = None,
    gathered: Gathered | None = None,
) -> PromoteResult:
    """A native link for one installed skill, or the sentence saying why not."""
    now_ms = _ms(now)
    home = Path(home)
    entry = read_state(home)["skills"].get(name)
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
        return PromoteResult(False, None, f"no skill named {name!r} is installed")
    source = Path(entry["path"])
    if not (source / SKILL_FILE).is_file():
        return PromoteResult(False, None, f"skill {name} has no {SKILL_FILE} at {source}")
    if gathered is None:
        gathered = select_adapter(home).gather(home, cwd, now_ms)
    if gathered.host != HOST_CLAUDE_CODE:
        return PromoteResult(
            False, None, "promotion is Claude Code only; this host has no skill directory"
        )
    link = link_path(source)
    if os.path.lexists(link):
        if _ours(link, source, entry):
            rec = _record(entry)
            mode = rec.get("mode") if rec is not None else None
            return PromoteResult(
                True, mode if mode == MODE_COPY else MODE_SYMLINK, f"{name} is already promoted"
            )
        return PromoteResult(False, None, f"{link} already exists and is not this skill's link")
    limit = skill_budget() if budget is None else budget
    total = catalogue_bytes(gathered, home, cwd, source)
    if total > limit:
        return PromoteResult(
            False,
            None,
            f"promoting {name} would take the catalogue to {total} bytes, "
            f"over the budget of {limit}",
        )
    link.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"at": now, "link": str(link)}
    try:
        (symlink or _symlink)(os.path.relpath(source, link.parent), str(link))
        record["mode"] = MODE_SYMLINK
    except OSError as e:
        if not _no_right(e):
            return PromoteResult(False, None, f"could not link {link}: {_code(e)}")
        write_dir_atomic(link, _files(source))
        record["mode"] = MODE_COPY
        record["tree_sha256"] = tree_hash(link)

    def change(state: dict[str, Any]) -> None:
        live = state["skills"].get(name)
        if isinstance(live, dict):
            live["promoted"] = record
            live.pop("promote_refused", None)

    update_state(home, change)
    return PromoteResult(True, record["mode"], f"promoted skill {name}")


def demote(name: str, home: Path | str) -> str:
    """Remove the native link (a copy only while unchanged); the source is never touched."""
    entry = read_state(home)["skills"].get(name)
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
        raise PromoteError(f"no skill named {name!r} is installed")
    if not _is_promoted(entry):
        raise PromoteError(f"skill {name} is not promoted")
    source = Path(entry["path"])
    rec = _record(entry) or {}
    link = Path(rec["link"]) if isinstance(rec.get("link"), str) else link_path(source)
    changed = f"{link} was changed after promotion; remove it yourself or keep it"
    if os.path.islink(link):
        if _real(link) != _real(source):
            raise PromoteError(changed)
        os.unlink(link)
    elif os.path.lexists(link):
        if (
            rec.get("mode") != MODE_COPY
            or not link.is_dir()
            or tree_hash(link) != rec.get("tree_sha256")
        ):
            raise PromoteError(changed)
        _remove_dir(link)

    def change(state: dict[str, Any]) -> None:
        live = state["skills"].get(name)
        if isinstance(live, dict):
            live.pop("promoted", None)
            live.pop("promote_refused", None)

    update_state(home, change)
    return f"demoted skill {name}"


def _refused_today(entry: Mapping[str, Any], today: str) -> bool:
    r = entry.get("promote_refused")
    if not isinstance(r, dict) or not isinstance(r.get("at"), str):
        return False
    try:
        return _iso(_ms(r["at"]))[:10] == today
    except SkillFileError:
        return False


def promote_step(
    state: dict[str, Any],
    uses: Mapping[str, int],
    home: Path | str,
    cwd: str | None,
    now: str,
    budget: int | None = None,
    *,
    symlink: Symlink | None = None,
    gathered: Gathered | None = None,
) -> list[str]:
    """Promote every live skill with `PROMOTE_USES` uses in the last `PROMOTE_DAYS`; events.

    `uses[name]` is the caller's count over that window (R10). A refusal is recorded on the
    skill (`promote_refused`) and that skill is not tried again the same UTC day. `state` is
    read for the decisions and replaced in place by the state written. With
    `BANTAMKIT_SKILL_AUTO` off (the 0.37.0 default) it does nothing at all: no promotion, no
    refusal recorded, no gather.
    """
    now_ms = _ms(now)
    if not auto_enabled():
        return []
    today = _iso(now_ms)[:10]
    skills = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    due = [
        n
        for n in sorted(skills)
        if isinstance(skills[n], dict)
        and not _is_promoted(skills[n])
        and (_int(uses.get(n)) or 0) >= PROMOTE_USES
        and not _refused_today(skills[n], today)
    ]
    if not due:
        return []
    if gathered is None:
        gathered = select_adapter(home).gather(home, cwd, now_ms)
    events: list[str] = []
    for name in due:
        got = promote(name, home, cwd, now, budget, symlink=symlink, gathered=gathered)
        if got.ok:
            events.append(got.reason)
            continue

        def refuse(fresh: dict[str, Any], name: str = name, reason: str = got.reason) -> None:
            live = fresh["skills"].get(name)
            if isinstance(live, dict):
                live["promote_refused"] = {"at": now, "reason": reason}

        update_state(home, refuse)
    fresh = read_state(home)
    state.clear()
    state.update(fresh)
    return events
