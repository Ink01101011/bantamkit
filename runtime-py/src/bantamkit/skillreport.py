"""The skill audit as a record and a rendered report, with its disable proposals (#205).

`skillhost` gathers, `skillaudit` measures, this decides what to say and what to propose.
K2: it REPORTS and PROPOSES a `settings.json` diff; it never edits the file — nothing in this
module opens a file for writing. A plugin is proposed only when ALL of these hold (spec, "When a
diff is proposed"):

- usage is present (`None` is no measurement, never "nothing was called");
- the transcripts span at least `USAGE_DAYS` days;
- every one of the plugin's counted skills had zero calls in that span.

Skills outside a plugin (`~/.claude/skills`, `<project>/.claude/skills`) cannot be switched off
in settings, so they are reported and never proposed: the grouping takes plugin skills only,
and a proposal needs the settings file that switched its plugin on.

THE DAILY RUN (Task 4). `daily` is what the Retention child calls once a day (K1): it runs
`run_live` and writes `~/.bantamkit/skill-audit.json` as `dumps(record) + "\n"`, temp-then-rename
under `exclusive`, keeping the previous `surfaced` keys that are still findings. `status_line` is
the `skill audit:` line `bantamkit_status` prints. Its `off; ` prefix reads the AUDIT switch
(`BANTAMKIT_SKILL_AUDIT`, Amendment A3), not retention's.

`runtime-ts/src/skillreport.ts` is the port; `tools/conformance/suites/skill-host.mjs`
compares the two (ops `record`, `render`, `propose`, `daily`, `status`, `child`, `line`).

THE SESSIONSTART LINE (Task 5). `session_line` reads the record and names, in one line of at most
`LINE_MAX_BYTES` bytes, the surfaceable findings whose `surface_key` is not yet in `surfaced`,
then adds those keys, so nothing repeats; with nothing new it returns None and writes nothing.
With `BANTAMKIT_SKILL_AUDIT=off` it returns None and writes nothing, even over an older record that
still holds unseen findings: the switch silences the line too (orchestrator ruling, job73 A6).

THE PROMPT (Task 6). `skill_audit` is the second MCP prompt on both servers: `prompts/get` returns
`render_report(run_live(home, cwd, now)) + "\n\n" + SKILL_AUDIT_PROMPT_TAIL` as one user message.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from bantamkit import skillaudit
from bantamkit.skillhost import HOST_NONE, USAGE_DAYS, Gathered, select_adapter
from bantamkit.storage.hotindex import dumps
from bantamkit.storage.lock import exclusive
from bantamkit.storage.retention import audit_enabled, parse_now

STATE_NAME = "skill-audit.json"
STATE_VERSION = 1
NO_ROOTS = "no skill directory was found for this host"
GATHER_FAILED = "the gather failed"
NOT_APPLIED = "NOT applied; bantamkit never edits settings.json"

#: The `skill_audit` MCP prompt (#205 Task 6). A PERSON's command (`/mcp__bantamkit__skill_audit`
#: in Claude Code); both servers serve these bytes.
SKILL_AUDIT_NAME = "skill_audit"
SKILL_AUDIT_PROMPT_TITLE = "bantamkit skill audit"
SKILL_AUDIT_PROMPT_DESCRIPTION = (
    "Audit the skills this host loads: catalogue bytes, shared trigger phrases, malformed "
    "frontmatter and, where the host keeps transcripts, skills with no call in 30 days. Inserts "
    "the report and a proposed settings.json change that is never applied for you."
)
SKILL_AUDIT_PROMPT_TAIL = (
    "Show me this report as it stands. Do not edit settings.json yourself; if a change is "
    "proposed above, ask me before applying it."
)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _locate(file: str, plugin: str) -> tuple[int | None, str | None, str | None]:
    """The line of `file` that switches `plugin` on, and that line switched off.

    The first line AFTER the one naming `"enabledPlugins"` that is exactly
    `<ws>"<plugin>"<ws>:<ws>true<ws>[,]<ws>` (a trailing `\\r` dropped). Anything else — a
    minified file, a value on its own line, a key spelled with an escape — is "not located",
    and the report tells the reader to edit it by hand. Read-only.
    """
    try:
        text = Path(file).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None, None, None
    armed = False
    for n, raw in enumerate(text.split("\n"), 1):
        line = raw[:-1] if raw.endswith("\r") else raw
        if not armed:
            armed = '"enabledPlugins"' in line
            continue
        head, sep, tail = line.partition(":")
        if not sep or head.strip(" \t") != f'"{plugin}"':
            continue
        if tail.strip(" \t").rstrip(",").rstrip(" \t") != "true":
            continue
        at = line.rfind("true")
        return n, line, line[:at] + "false" + line[at + 4 :]
    return None, None, None


def propose(
    found: list[Any],
    usage: dict[str, int] | None,
    span_days: int,
    sources: dict[str, str],
) -> list[dict[str, Any]]:
    """The plugins to switch off, each with the settings line that would do it.

    `found` is `skillaudit.scan_roots`' answer; `sources` maps an enabled plugin id to the
    settings file its `true` won in (`Gathered.sources`).
    """
    if usage is None or span_days < USAGE_DAYS:
        return []
    plugins: dict[str, set[str]] = {}
    for s in found:
        if s.omitted is None and s.in_plugin:
            plugins.setdefault(s.plugin_id, set()).add(s.id)
    out: list[dict[str, Any]] = []
    for pid in sorted(plugins):
        ids = sorted(plugins[pid])
        if any(usage.get(i, 0) > 0 for i in ids):
            continue
        file = sources.get(pid)
        if file is None:
            continue
        line, before, after = _locate(file, pid)
        out.append(
            {
                "plugin": pid,
                "file": file,
                "line": line,
                "before": before,
                "after": after,
                "skills": ids,
            }
        )
    return out


def _error(now: str, host: str, error: str) -> dict[str, Any]:
    return {"version": STATE_VERSION, "ts": now, "host": host, "error": error, "surfaced": []}


def build_record(g: Gathered, now: str) -> dict[str, Any]:
    """The stored record (`skill-audit.json`, written by the daily run), or its error form."""
    if not g.roots:
        return _error(now, g.host, NO_ROOTS)
    roots = [(label, path) for label, path in g.roots]
    counts = None if g.usage is None else g.usage.counts
    found = skillaudit.scan_roots(roots, list(g.enabled), g.versions)
    result = skillaudit.audit_roots(
        roots, enabled=list(g.enabled), usage=counts, versions=g.versions
    )
    span = 0 if g.usage is None else g.usage.span_days
    return {
        "version": STATE_VERSION,
        "ts": now,
        "host": g.host,
        "roots": [list(r) for r in roots],
        "skills": result.skills,
        "catalogue_bytes": result.catalogue_bytes,
        "findings": [f.as_dict() for f in result.findings],
        "omissions": [o.as_dict() for o in result.omissions],
        "usage": None if g.usage is None else g.usage.summary(),
        "proposals": propose(found, counts, span, g.sources),
        "surfaced": [],
    }


def run_live(home: Path | str, cwd: str | None, now: str) -> dict[str, Any]:
    """Gather and audit now. Never raises: a failure is the error record (spec, "Gather fails")."""
    host = HOST_NONE
    try:
        adapter = select_adapter(home)
        host = adapter.host
        return build_record(adapter.gather(home, cwd, parse_now(now)), now)
    except Exception:  # noqa: BLE001 - the report says it failed; no hook or tool fails
        return _error(now, host, GATHER_FAILED)


def _diff_lines(record: dict[str, Any]) -> list[str]:
    usage = record["usage"]
    props = record["proposals"]
    if usage is None:
        return [
            "proposed change: none — this host has no usage adapter, so no skill is called "
            "never-invoked and nothing is proposed"
        ]
    if usage["span_days"] < USAGE_DAYS:
        return [
            f"proposed change: none — the transcripts span {usage['span_days']} days; "
            f"a change needs {USAGE_DAYS}"
        ]
    if not props:
        return [
            "proposed change: none — no enabled plugin has every skill at 0 calls over "
            f"{USAGE_DAYS} days"
        ]
    out = [f"proposed change — {NOT_APPLIED}:"]
    for file in sorted({p["file"] for p in props}):
        mine = [p for p in props if p["file"] == file]
        located = sorted(
            (p for p in mine if p["line"] is not None), key=lambda p: (p["line"], p["plugin"])
        )
        if located:
            out += [f"--- {file}", f"+++ {file}"]
            for p in located:
                out += [f"@@ -{p['line']} +{p['line']} @@", f"-{p['before']}", f"+{p['after']}"]
        for p in sorted((p for p in mine if p["line"] is None), key=lambda p: p["plugin"]):
            out.append(
                f'set enabledPlugins["{p["plugin"]}"] to false in {file} '
                "(the line could not be located)"
            )
    for p in sorted(props, key=lambda p: p["plugin"]):
        out.append(
            f"{p['plugin']}: every skill had 0 calls in {USAGE_DAYS} days — "
            + ", ".join(p["skills"])
        )
    out.append(
        "edit the lines yourself, or save the hunks to a file and run "
        "`git apply --unidiff-zero <file>` from `/` (the paths are absolute)"
    )
    return out


def render_report(record: dict[str, Any]) -> str:
    """The report a person reads: the prompt's body, byte-identical across runtimes."""
    if "error" in record:
        return (
            f"skill audit — could not run: {record['error']}. The `skill_audit` tool still "
            "audits any directory you name as `root`."
        )
    sev = Counter(f.get("severity") for f in record["findings"])
    lines = [
        f"skill audit — {record['host']}, {_plural(record['skills'], 'skill')}, "
        f"{record['catalogue_bytes']} catalogue bytes",
        "roots: " + "; ".join(f"{label} {path}" for label, path in record["roots"]),
    ]
    usage = record["usage"]
    if usage is None:
        lines.append("usage: none — this host has no usage adapter")
    else:
        lines.append(
            f"usage: {_plural(usage['calls'], 'skill call')} over {usage['span_days']} days in "
            f"{_plural(usage['transcripts'], 'transcript')} ({usage['unreadable']} unreadable, "
            f"{usage['skipped_lines']} lines skipped)"
        )
    lines.append(f"findings: {sev['high']} high, {sev['medium']} medium, {sev['low']} low")
    for f in record["findings"]:
        who = ", ".join(f["skills"]) if f["skills"] else "the catalogue"
        lines.append(f"- {f['severity']} {f['kind']}: {who} — {f['detail']}")
    if record["omissions"]:
        lines.append(
            "omissions: "
            + "; ".join(
                f"{o['subject']} {o['count']} ({o['size']} bytes)" for o in record["omissions"]
            )
        )
    lines += _diff_lines(record)
    return "\n".join(lines)


# ------------------------------------------------------------------------- the daily run


def state_path(home: Path | str) -> Path:
    return Path(home) / ".bantamkit" / STATE_NAME


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")  # `JSON.parse` refuses NaN/Infinity; so does this


_SAFE = 2**53 - 1


def _js_float(text: str) -> float | int:
    """`1.0` is the number 1 to `JSON.parse`; so it is here, or the two runtimes would print
    one record differently. A float that is not a whole number stays a float."""
    f = float(text)
    return int(f) if f.is_integer() and abs(f) <= _SAFE else f


def _is_int(v: Any) -> bool:
    """`Number.isSafeInteger`: a whole number a JS number holds exactly (bool is not one)."""
    return type(v) is int and abs(v) <= _SAFE


def read_state(home: Path | str) -> dict[str, Any] | None:
    """The stored record, or None: missing, unreadable, not JSON, `version != 1`, or a shape
    the status line cannot print. A None is recomputed by the next day's run."""
    try:
        doc = json.loads(
            state_path(home).read_bytes().decode("utf-8"),
            parse_constant=_refuse_constant,
            parse_float=_js_float,
        )
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(doc, dict) or not _is_int(doc.get("version")):
        return None
    if doc["version"] != STATE_VERSION:
        return None
    if not isinstance(doc.get("ts"), str) or not isinstance(doc.get("host"), str):
        return None
    surfaced = doc.get("surfaced")
    if not isinstance(surfaced, list) or not all(isinstance(s, str) for s in surfaced):
        return None
    if "error" in doc:
        return doc if isinstance(doc["error"], str) else None
    findings = doc.get("findings")
    usage = doc.get("usage")
    ok = (
        _is_int(doc.get("skills"))
        and _is_int(doc.get("catalogue_bytes"))
        and isinstance(findings, list)
        and all(isinstance(f, dict) for f in findings)
        and isinstance(doc.get("proposals"), list)
        and isinstance(doc.get("roots"), list)
        and isinstance(doc.get("omissions"), list)
        and (usage is None or (isinstance(usage, dict) and _is_int(usage.get("span_days"))))
    )
    return doc if ok else None


def surface_key(finding: dict[str, Any]) -> str:
    """`kind<TAB>skills,joined<TAB>detail`: what `surfaced` remembers was already shown."""
    skills = finding.get("skills")
    joined = ",".join(skills) if isinstance(skills, list) else ""
    return f"{finding.get('kind')}\t{joined}\t{finding.get('detail')}"


def _write(path: Path, record: dict[str, Any]) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(dumps(record) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def daily(home: Path | str, cwd: str | None, now: str) -> None:
    """The once-a-day run the Retention child makes (K1). Silent; never raises."""
    try:
        record = run_live(home, cwd, now)
        path = state_path(home)
        with exclusive(path) as held:
            if not held:
                return
            prev = read_state(home)
            if prev is not None and "findings" in record:
                keys = {surface_key(f) for f in record["findings"]}
                record["surfaced"] = sorted(k for k in prev["surfaced"] if k in keys)
            _write(path, record)
    except Exception:  # noqa: BLE001 - recomputed at the next day's run
        pass


def status_line(home: Path | str) -> str:
    """The `skill audit:` line of `bantamkit_status`. Never raises."""
    prefix = "" if audit_enabled() else "off; "
    unreadable = f"skill audit: {prefix}the last record is unreadable; the next run recomputes it"
    try:
        if not os.path.lexists(state_path(home)):
            return f"skill audit: {prefix}never ran; usage adapter {select_adapter(home).host}"
        record = read_state(home)
        if record is None:
            return unreadable
        if "error" in record:
            return f"skill audit: {prefix}last ran {record['ts']}; no report — {record['error']}"
        sev = Counter(f.get("severity") for f in record["findings"])
        usage = record["usage"]
        if usage is None:
            clause = (
                f"usage: none — {record['host']} has no usage adapter, "
                "so nothing is called never-invoked"
            )
        elif usage["span_days"] < USAGE_DAYS:
            clause = f"usage over {usage['span_days']} days (a proposed change needs {USAGE_DAYS})"
        else:
            clause = (
                f"usage over {USAGE_DAYS} days; "
                f"{_plural(len(record['proposals']), 'change')} proposed"
            )
        return (
            f"skill audit: {prefix}last ran {record['ts']} on {record['host']}; "
            f"{_plural(record['skills'], 'skill')}, {record['catalogue_bytes']} catalogue bytes; "
            f"findings {sev['high']} high, {sev['medium']} medium, {sev['low']} low; {clause}"
        )
    except Exception:  # noqa: BLE001 - a status line never fails the report
        return unreadable


# --------------------------------------------------------------------- the SessionStart line

LINE_MAX_BYTES = 200
COMMAND = "/mcp__bantamkit__skill_audit"
_TAIL = f" — {COMMAND} has the report."
_ELLIPSIS = "…"


def _b(text: str) -> int:
    return len(text.encode("utf-8"))


def _clip(text: str, room: int) -> str:
    """The longest prefix of whole code points that fits `room` bytes with the ellipsis."""
    out = ""
    for ch in text:  # code points, as Node's `for (const ch of text)`
        if _b(out + ch) + _b(_ELLIPSIS) > room:
            break
        out += ch
    return out + _ELLIPSIS


def _well_formed(f: dict[str, Any]) -> bool:
    """A finding the line can name and `surfaced` can key: `read_state` checks only that each
    finding is an object, so a hand-edited one is skipped here, the same way on both sides."""
    skills = f.get("skills")
    return (
        isinstance(f.get("kind"), str)
        and isinstance(f.get("detail"), str)
        and isinstance(skills, list)
        and all(isinstance(s, str) for s in skills)
    )


def surfaceable(record: dict[str, Any]) -> list[dict[str, Any]]:
    """The findings worth a SessionStart line (spec K1): every `high` one, and `never-invoked`
    only once the transcripts span `USAGE_DAYS` days. Record order."""
    usage = record.get("usage")
    long_enough = isinstance(usage, dict) and usage.get("span_days", 0) >= USAGE_DAYS
    return [
        f
        for f in record.get("findings", [])
        if _well_formed(f)
        and (f.get("severity") == "high" or (f.get("kind") == "never-invoked" and long_enough))
    ]


def _item(f: dict[str, Any]) -> str:
    if f["kind"] == "never-invoked" and f["skills"]:
        return f"{f['skills'][0]} {USAGE_DAYS} days without a call"
    return f"{f['kind']}: {', '.join(f['skills']) if f['skills'] else f['detail']}"


def render_line(items: list[str]) -> str:
    """`[bantamkit] skill audit: N new — a; b; +k more — <command> has the report.`, at most
    `LINE_MAX_BYTES` UTF-8 bytes. Whole items while they fit; a first item that cannot fit is
    clipped on a code point."""
    head = f"[bantamkit] skill audit: {len(items)} new — "
    room = LINE_MAX_BYTES - _b(head) - _b(_TAIL)
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
    return head + body + _TAIL


def session_line(home: Path | str) -> str | None:
    """One line for SessionStart, only for what `surfaced` has not seen (K1). None — and no
    write — when nothing is new, so SessionStart adds 0 bytes. Otherwise the shown keys join
    `surfaced` under the lock, if the record is still the one read (same `ts`). Never raises.
    `BANTAMKIT_SKILL_AUDIT=off` silences it: None, nothing written, whatever the record holds."""
    try:
        if not audit_enabled():
            return None
        record = read_state(home)
        if record is None or "error" in record:
            return None
        shown = set(record["surfaced"])
        new = [f for f in surfaceable(record) if surface_key(f) not in shown]
        if not new:
            return None
        line = render_line([_item(f) for f in new])
        path = state_path(home)
        with exclusive(path) as held:
            if held:
                again = read_state(home)
                if again is not None and "error" not in again and again["ts"] == record["ts"]:
                    keys = set(again["surfaced"]) | {surface_key(f) for f in new}
                    again["surfaced"] = sorted(keys)
                    _write(path, again)
        return line
    except Exception:  # noqa: BLE001 - a line this cannot make is no line, never a dead session
        return None
