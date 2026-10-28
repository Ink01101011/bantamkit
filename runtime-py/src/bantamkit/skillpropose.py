"""#206 Task 11: the `skill_propose` prompt and the skills SessionStart line.

THE COMMAND (spec component 5). `/mcp__bantamkit__skill_propose` in Claude Code: a PERSON's
command, served by both MCP servers as a prompt with three optional arguments, `action`
(`list` by default, `approve`, `reject`, `undo`, `promote`, `demote`), `target` (a proposal id,
or a skill name) and `level` (`project` or `user`, X3's override on approve). `render` runs the
action server-side and answers ONE user message: the outcome, never an RPC error. Claude Code
passes a prompt's arguments space-separated in this order, so the routes this module prints
read `/mcp__bantamkit__skill_propose undo <name>`; a value typed as `action=undo` is read too.

APPROVE (X5, R11). A proposal that already holds a gated draft is installed (`auto=False`, so
not on probation, R13). One without walks the server's chain: MCP sampling when the client
declared it, the endpoint when one is configured, then the host agent. A draft that fails the
gate is discarded and logged and does NOT fall through. The host agent gets the bundle, the
drafting instructions and the exact path to write one SKILL.md to (`handoff_path`, under
`~/.bantamkit`, outside every skills root, so the gate never meets the draft twice); the second
approve finds that file, gates it, stamps it and installs it, with `references/evidence.md`
written by the installer from named fields only (X4). Without a Claude Code adapter the
stamped file is printed for the person to place, and nothing is written.

THE LINE (spec component 6). `session_line` names, once, each thing the daily run did that a
person should know (an install, a probation removal or proposal, a promotion, a rollback) and
each newly pending proposal, in at most `LINE_MAX_BYTES` UTF-8 bytes, with the undo route.
What was shown is remembered in `skills-state.json` `surfaced`; nothing new is None and no
write, so SessionStart adds 0 bytes. `BANTAMKIT_SKILL_AUDIT=off` (the miner's switch, Q2)
silences it, as it silences #205's line.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

SKILL_PROPOSE_NAME = "skill_propose"
SKILL_PROPOSE_PROMPT_TITLE = "bantamkit skill proposals"
SKILL_PROPOSE_PROMPT_DESCRIPTION = (
    "List the skills bantamkit proposes from your repeated, successful work and the ones it "
    "installed, or approve, reject, undo, promote or demote one by its id or name."
)
#: `(name, description)` of the prompt's arguments, all optional, in the order Claude Code
#: fills them from a space-separated command line.
ARGUMENTS = (
    ("action", "list (the default), approve, reject, undo, promote or demote"),
    ("target", "a proposal id, or the name of an installed skill"),
    ("level", "project or user: where an approved skill is installed"),
)
ACTIONS = ("list", "approve", "reject", "undo", "promote", "demote")
COMMAND = "/mcp__bantamkit__skill_propose"
#: The `maxTokens` of the one `sampling/createMessage` request a draft sends.
SAMPLING_MAX_TOKENS = 4096
#: Where the host agent writes its draft: `~/.bantamkit/skill-handoff/<proposal id>/SKILL.md`.
HANDOFF_DIR = "skill-handoff"
LINE_MAX_BYTES = 200

EMPTY = (
    "bantamkit skill proposals: nothing is pending and no skill is installed. The daily run "
    "proposes a skill once the same work has succeeded 3 times in shiftwork units or 5 times "
    "in sessions."
)

Sampler = Callable[[str, str], str]


def _int(v: Any) -> int | None:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return v if type(v) is int and 0 <= v <= 2**53 - 1 else None


def _num(v: Any) -> str:
    n = _int(v)
    return "?" if n is None else str(n)


def _strs(v: Any) -> list[str]:
    return [s for s in v if isinstance(s, str)] if isinstance(v, list) else []


def _arg(value: Any, name: str) -> str | None:
    """An argument as typed: None or "" is absent; `name=value` is read as `value`."""
    if not isinstance(value, str) or value == "":
        return None
    prefix = f"{name}="
    if value.startswith(prefix):
        value = value[len(prefix) :]
    return value or None


def handoff_path(home: str | Path, cid: str) -> Path:
    return Path(home) / ".bantamkit" / HANDOFF_DIR / cid / "SKILL.md"


def _records(doc: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if doc is None:
        return []
    return [r for r in doc["clusters"] if isinstance(r, dict) and isinstance(r.get("id"), str)]


def _pending(doc: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The pending proposals, file order, at most `PENDING_MAX` (a hand-edited file may hold
    more; the cap is the surface's, not only the miner's)."""
    from bantamkit.skillmine import PENDING_MAX

    return [r for r in _records(doc) if r.get("status") == "pending"][:PENDING_MAX]


def _skills(state: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if state is None:
        return {}
    return {n: e for n, e in state["skills"].items() if isinstance(e, dict)}


def _waiting(state: Mapping[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    """Needs-user items: a skill whose `proposal` is still pending, by name."""
    out = []
    for name in sorted(_skills(state)):
        p = _skills(state)[name].get("proposal")
        if isinstance(p, dict) and p.get("status") == "pending" and isinstance(p.get("kind"), str):
            out.append((name, p))
    return out


# --------------------------------------------------------------------------------- list


def _proposal_lines(r: Mapping[str, Any]) -> list[str]:
    pitfalls = []
    for p in r.get("pitfalls") if isinstance(r.get("pitfalls"), list) else []:
        if isinstance(p, dict) and isinstance(p.get("id"), str):
            f = p.get("failure")
            pitfalls.append(f"{p['id']} ({f})" if isinstance(f, str) and f else p["id"])
    ids = [
        e["id"]
        for e in r.get("evidence") or []
        if isinstance(e, dict) and isinstance(e.get("id"), str)
    ]
    source = r["source"] if isinstance(r.get("source"), str) else "?"
    level = r["level"] if isinstance(r.get("level"), str) else "?"
    return [
        f"- {r['id']}: {source}, {_num(r.get('successes'))} of {_num(r.get('bar'))} successes, "
        f"{level} level",
        f"  keywords: {', '.join(_strs(r.get('keywords'))) or '-'}",
        f"  steps: {'; '.join(_strs(r.get('steps'))) or '-'}",
        f"  pitfalls: {'; '.join(pitfalls) or '-'}",
        f"  evidence: {', '.join(ids) or '-'}",
        f"  approve: {COMMAND} approve {r['id']}   reject: {COMMAND} reject {r['id']}",
    ]


def _waiting_lines(name: str, p: Mapping[str, Any]) -> list[str]:
    if p["kind"] == "remove":
        what = "remove it (unused through probation, but edited by hand, so never removed for you)"
    else:
        what = f"a proposed {p['kind']} change"
    out = [f"- {name}: {what}"]
    diff = p.get("diff")
    if isinstance(diff, str) and diff:
        out += ["  ```diff", *(f"  {line}" for line in diff.split("\n")), "  ```"]
    out.append(f"  approve: {COMMAND} approve {name}   reject: {COMMAND} reject {name}")
    return out


def _skill_line(name: str, e: Mapping[str, Any]) -> str:
    parts = [
        f"- {name} v{_num(e.get('version'))}",
        "auto" if e.get("auto") is True else "approved",
        f"{e['level'] if isinstance(e.get('level'), str) else '?'} level",
    ]
    until = e.get("probation_until")
    if isinstance(until, str):
        parts.append(f"on probation until {until[:10]}")
    promoted = e.get("promoted")
    if isinstance(promoted, dict):
        mode = promoted.get("mode")
        parts.append(f"promoted ({mode if isinstance(mode, str) else '?'})")
    refused = e.get("promote_refused")
    if isinstance(refused, dict) and isinstance(refused.get("reason"), str):
        parts.append(f"promotion refused: {refused['reason']}")
    return ", ".join(parts)


def render_list(home: str | Path) -> str:
    from bantamkit.skillfile import SkillFileError, read_state
    from bantamkit.skillmine import PENDING_MAX, ProposalsError, read_proposals

    out: list[str] = []
    try:
        doc = read_proposals(home)
    except ProposalsError as e:
        doc = None
        out.append(f"The proposals could not be read: {e}.")
    try:
        state = read_state(home)
    except SkillFileError as e:
        state = None
        out.append(f"The installed skills could not be read: {e}.")
    pending = _pending(doc)
    waiting = _waiting(state)
    skills = _skills(state)
    if not out and not pending and not waiting and not skills:
        return EMPTY
    lines = ["bantamkit skill proposals", ""]
    lines += out + ([""] if out else [])
    if pending:
        lines.append(f"Pending ({len(pending)} of at most {PENDING_MAX}):")
        for r in pending:
            lines += _proposal_lines(r)
    else:
        lines.append("No proposal is pending.")
    if waiting:
        lines += ["", "Waiting on you:"]
        for name, p in waiting:
            lines += _waiting_lines(name, p)
    lines.append("")
    if skills:
        lines.append("Installed:")
        lines += [_skill_line(n, skills[n]) for n in sorted(skills)]
        lines.append(
            f"  undo: {COMMAND} undo <name>   promote: {COMMAND} promote <name>   "
            f"demote: {COMMAND} demote <name>"
        )
    else:
        lines.append("No skill is installed.")
    return "\n".join(lines)


# ------------------------------------------------------------------------------ approve


def _handoff_text(rec: Mapping[str, Any], handoff: Mapping[str, Any], home: str | Path) -> str:
    from bantamkit.skilldraft import bundle_json

    path = handoff_path(home, rec["id"])
    return (
        f"No sampling client or endpoint drafted proposal {rec['id']}, so you draft it.\n\n"
        f"1. Write ONE file, {path}, with your own file tools, following these instructions:\n\n"
        f"{handoff['instructions']}\n\n"
        f"The evidence bundle:\n\n```json\n{bundle_json(handoff['bundle'])}\n```\n\n"
        f"2. Then run {COMMAND} approve {rec['id']} again. bantamkit gates the file, adds its "
        f"metadata and installs it under {handoff['target']}, with references/evidence.md written "
        "from the evidence. Write nothing else."
    )


def _gate_failed(where: str, reasons: list[str], tail: str) -> str:
    return "\n".join(
        [f"{where} did not pass the gate, so nothing was installed:"]
        + [f"- {r}" for r in reasons]
        + [tail]
    )


def _install(
    rec: dict[str, Any],
    doc: dict[str, Any],
    text: str,
    level: str | None,
    home: str | Path,
    now: str,
) -> str:
    from bantamkit.skillfile import SkillFileError
    from bantamkit.skillhost import HOST_CLAUDE_CODE, select_adapter
    from bantamkit.skillinstall import install, install_root, skill_text
    from bantamkit.skillmine import write_proposals

    if select_adapter(home).host != HOST_CLAUDE_CODE:
        try:
            _, root = install_root(rec, level, home)
            stamped = skill_text(rec, text)
        except SkillFileError as e:
            return f"could not prepare proposal {rec['id']}: {e}"
        return (
            "No Claude Code skill directory was found on this host, so nothing was written. "
            f"Place this file yourself, as {root}/<name>/SKILL.md where <name> is its name:\n\n"
            f"```markdown\n{stamped}```"
        )
    try:
        got = install(rec, text, level, home, now, auto=False)
    except SkillFileError as e:
        return f"could not install proposal {rec['id']}: {e}"
    write_proposals(home, doc)
    shutil.rmtree(handoff_path(home, rec["id"]).parent, ignore_errors=True)
    return (
        f"installed skill {got.name} at {got.path} ({got.level} level).\n"
        f"undo: {COMMAND} undo {got.name}"
    )


def _approve_proposal(
    rec: dict[str, Any],
    doc: dict[str, Any],
    level: str | None,
    home: str | Path,
    cwd: str | None,
    now: str,
    sampler: Sampler | None,
) -> str:
    from bantamkit.skilldraft import (
        DRAFTER_HOST,
        DraftOutcome,
        bundle,
        default_chain,
        draft,
        drafts_log,
        gate,
    )
    from bantamkit.skillinstall import _draft_text, draft_entry
    from bantamkit.skillmine import write_proposals
    from bantamkit.storage.logsegment import LogSegment

    cid = rec["id"]
    if rec.get("status") == "installed":
        return f"proposal {cid} is already installed"
    if rec.get("eligible") is not True:
        return (
            f"proposal {cid} has not cleared its bar: {_num(rec.get('successes'))} of "
            f"{_num(rec.get('bar'))} successes"
        )
    text = _draft_text(rec)
    if text is not None:
        return _install(rec, doc, text, level, home, now)
    staged = handoff_path(home, cid)
    if staged.is_file():
        try:
            text = staged.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            return f"{staged} is not UTF-8 text; nothing was installed"
        g = gate(text, bundle(rec), home, cwd)
        outcome = DraftOutcome(DRAFTER_HOST, g.ok, text if g.ok else None, g.reasons, [])
        LogSegment(drafts_log(home)).append(outcome.log_line(now, cid))
        if not g.ok:
            return _gate_failed(
                f"The SKILL.md at {staged}",
                g.reasons,
                f"Fix it and run {COMMAND} approve {cid} again.",
            )
        return _install(rec, doc, text, level, home, now)
    out = draft(rec, default_chain(sampler, host_agent=True), home, cwd, now)
    if out.handoff is not None:
        return _handoff_text(rec, out.handoff, home)
    if not out.ok or out.text is None:
        return _gate_failed(
            f"The draft from {out.drafter}",
            out.reasons,
            f"It was discarded and logged; proposal {cid} stays as it is.",
        )
    rec["draft"] = draft_entry(out.drafter, out.text, now)
    write_proposals(home, doc)
    return _install(rec, doc, out.text, level, home, now)


def _approve_item(name: str, p: Mapping[str, Any], home: str | Path, now: str) -> str:
    """A needs-user item: `remove` takes the skill away (with a backup, so undo restores it);
    any item carrying a `text` becomes the skill's next version, `approved`."""
    from bantamkit.skillfile import SkillFileError, backup_dir, backup_root, update_state
    from bantamkit.skillinstall import _remove_dir, new_version
    from bantamkit.skillpromote import demote

    if p["kind"] == "remove":
        state_entry = _skills(_state(home)).get(name, {})
        if isinstance(state_entry.get("promoted"), dict):
            try:
                demote(name, home)
            except SkillFileError as e:
                return f"could not remove skill {name}: {e}"
        target = Path(state_entry["path"]) if isinstance(state_entry.get("path"), str) else None
        if target is not None and target.is_dir():
            backup_dir(backup_root(home), target, now)
            _remove_dir(target)

        def change(fresh: dict[str, Any]) -> None:
            entry = fresh["skills"].pop(name, None)
            if isinstance(entry, dict):
                entry.pop("proposal", None)
                if not isinstance(fresh.get("removed"), dict):
                    fresh["removed"] = {}
                fresh["removed"][name] = entry

        update_state(home, change)
        return f"removed skill {name}.\nundo: {COMMAND} undo {name}"
    text = p.get("text")
    if not isinstance(text, str):
        return f"the proposed {p['kind']} change to {name} carries no text to apply"
    try:
        said = new_version(name, text, home, now, "approved")
    except SkillFileError as e:
        return f"could not apply the proposed change to {name}: {e}"
    _drop_proposal(home, name)
    return said


def _drop_proposal(home: str | Path, name: str, status: str | None = None) -> None:
    from bantamkit.skillfile import update_state

    def change(fresh: dict[str, Any]) -> None:
        entry = fresh["skills"].get(name)
        if isinstance(entry, dict) and isinstance(entry.get("proposal"), dict):
            if status is None:
                entry.pop("proposal")
            else:
                entry["proposal"]["status"] = status

    update_state(home, change)


def _state(home: str | Path) -> dict[str, Any] | None:
    from bantamkit.skillfile import SkillFileError, read_state

    try:
        return read_state(home)
    except SkillFileError:
        return None


# ------------------------------------------------------------------------------- render


def render(
    action: str | None,
    target: str | None,
    level: str | None,
    home: str | Path,
    cwd: str | None,
    now: str,
    sampler: Sampler | None = None,
) -> str:
    """The text of the one user message `prompts/get skill_propose` answers. Never raises for
    anything a person typed: every refusal is a sentence in the message."""
    from bantamkit.skillfile import SkillFileError
    from bantamkit.skillinstall import undo
    from bantamkit.skillmine import ProposalsError, read_proposals, write_proposals
    from bantamkit.skillpromote import demote, promote

    action = _arg(action, "action") or "list"
    target = _arg(target, "target")
    level = _arg(level, "level")
    if action not in ACTIONS:
        return f"unknown action '{action}'; one of {', '.join(ACTIONS)}"
    if action == "list":
        return render_list(home)
    if target is None:
        return f"action {action} needs a target: {COMMAND} {action} <id or name>"
    if level is not None and level not in ("project", "user"):
        return "level must be project or user"
    if action in ("approve", "reject"):
        try:
            doc = read_proposals(home)
        except ProposalsError as e:
            return f"could not {action} {target}: {e}"
        rec = next((r for r in _records(doc) if r["id"] == target), None)
        if rec is not None and doc is not None:
            if action == "approve":
                return _approve_proposal(rec, doc, level, home, cwd, now, sampler)
            if rec.get("status") == "installed":
                return f"proposal {target} is installed; {COMMAND} undo <name> removes its skill"
            successes = _int(rec.get("successes")) or 0
            rec["status"] = "rejected"
            rec["rejected_at"] = successes
            write_proposals(home, doc)
            return (
                f"rejected proposal {target}; it is offered again once it has "
                f"{2 * successes} successes"
            )
        item = dict(_waiting(_state(home))).get(target)
        if item is None:
            return f"no pending proposal or change is named '{target}'"
        if action == "approve":
            return _approve_item(target, item, home, now)
        _drop_proposal(home, target, "rejected")
        return f"kept skill {target}; the proposed {item['kind']} change is dropped"
    if action == "promote":
        try:
            return promote(target, home, cwd, now).reason
        except SkillFileError as e:
            return str(e)
    if action == "demote":
        try:
            return demote(target, home)
        except SkillFileError as e:
            return str(e)
    # undo: a promoted skill is demoted first (its link would dangle otherwise); else the
    # newest backup is put back. An install undone marks its proposal rejected, so the daily
    # run does not install it again.
    entry = _skills(_state(home)).get(target)
    try:
        if entry is not None and isinstance(entry.get("promoted"), dict):
            return demote(target, home)
        said = undo(target, home)
    except SkillFileError as e:
        return str(e)
    if entry is not None and target not in _skills(_state(home)):
        cid = entry.get("cluster")
        try:
            doc = read_proposals(home)
        except ProposalsError:
            doc = None
        rec = next((r for r in _records(doc) if r["id"] == cid), None)
        if rec is not None and doc is not None and rec.get("status") == "installed":
            rec["status"] = "rejected"
            rec["rejected_at"] = _int(rec.get("successes")) or 0
            write_proposals(home, doc)
            said += f"; proposal {cid} is marked rejected"
    return said


# --------------------------------------------------------------------- the SessionStart line

_ELLIPSIS = "…"
_HEAD = "[bantamkit] skills: "
_TAIL = f" — {COMMAND} lists them."


def _b(text: str) -> int:
    return len(text.encode("utf-8"))


def _clip(text: str, room: int) -> str:
    out = ""
    for ch in text:
        if _b(out + ch) + _b(_ELLIPSIS) > room:
            break
        out += ch
    return out + _ELLIPSIS


def event_item(event: str) -> str:
    """The line's words for one daily event (the strings `skillinstall`/`skillpromote` make)."""
    for prefix, fmt in (
        ("installed skill ", "installed {} on probation (undo: " + COMMAND + " undo {})"),
        ("removed unused skill ", "removed unused {} (undo: " + COMMAND + " undo {})"),
        ("proposed removing edited skill ", "{} unused but edited: removal waits on you"),
        ("promoted skill ", "promoted {} (undo: " + COMMAND + " demote {})"),
    ):
        if event.startswith(prefix):
            name = event[len(prefix) :]
            return fmt.format(name, name)
    return event


def render_line(items: list[str]) -> str:
    """`[bantamkit] skills: a; b; +k more — <command> lists them.`, at most `LINE_MAX_BYTES`
    UTF-8 bytes: whole items while they fit; a first item that cannot fit is clipped on a code
    point."""
    room = LINE_MAX_BYTES - _b(_HEAD) - _b(_TAIL)
    body = ""
    for i, item in enumerate(items):
        left = len(items) - i - 1
        more = f"; +{left} more" if left else ""
        cand = item if not body else f"{body}; {item}"
        if _b(cand + more) <= room:
            body = cand
            continue
        body = f"{body}; +{len(items) - i} more" if body else _clip(item, room - _b(more)) + more
        break
    return _HEAD + body + _TAIL


def _line_items(home: str | Path) -> list[tuple[str, str]]:
    """`(surface key, words)` for every event and pending proposal, oldest event first."""
    from bantamkit.skillfile import read_state
    from bantamkit.skillmine import ProposalsError, read_proposals

    state = read_state(home)
    out: list[tuple[str, str]] = []
    events = state.get("events") if isinstance(state.get("events"), list) else []
    for e in events:
        if isinstance(e, dict) and isinstance(e.get("at"), str) and isinstance(e.get("event"), str):
            out.append((f"event\t{e['at']}\t{e['event']}", event_item(e["event"])))
    try:
        doc = read_proposals(home)
    except ProposalsError:
        doc = None
    for r in _pending(doc):
        out.append((f"pending\t{r['id']}", f"new proposal {r['id']}"))
    return out


def session_line(home: str | Path) -> str | None:
    """One SessionStart line for what `surfaced` has not seen; None, with no write, when nothing
    is new (the 0-byte bar). Never raises."""
    from bantamkit.skillfile import update_state
    from bantamkit.storage.retention import audit_enabled

    try:
        if not audit_enabled():
            return None
        from bantamkit.skillfile import read_state

        state = read_state(home)
        shown = set(_strs(state.get("surfaced")))
        items = _line_items(home)
        new = [(k, w) for k, w in items if k not in shown]
        if not new:
            return None
        line = render_line([w for _, w in new])
        current = {k for k, _ in items}

        def change(fresh: dict[str, Any]) -> None:
            kept = {k for k in _strs(fresh.get("surfaced")) if k in current}
            fresh["surfaced"] = sorted(kept | {k for k, _ in new})

        update_state(home, change)
        return line
    except Exception:  # noqa: BLE001 - a line this cannot make is no line, never a dead session
        return None


__all__ = [
    "ACTIONS",
    "ARGUMENTS",
    "COMMAND",
    "EMPTY",
    "HANDOFF_DIR",
    "LINE_MAX_BYTES",
    "SAMPLING_MAX_TOKENS",
    "SKILL_PROPOSE_NAME",
    "SKILL_PROPOSE_PROMPT_DESCRIPTION",
    "SKILL_PROPOSE_PROMPT_TITLE",
    "event_item",
    "handoff_path",
    "render",
    "render_line",
    "render_list",
    "session_line",
]
