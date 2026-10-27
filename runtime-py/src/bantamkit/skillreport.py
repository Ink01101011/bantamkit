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

`runtime-ts/src/skillreport.ts` is the port; `tools/conformance/suites/skill-host.mjs`
compares the two (ops `record`, `render`, `propose`).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from bantamkit import skillaudit
from bantamkit.skillhost import HOST_NONE, USAGE_DAYS, Gathered, select_adapter
from bantamkit.storage.retention import parse_now

STATE_NAME = "skill-audit.json"
STATE_VERSION = 1
NO_ROOTS = "no skill directory was found for this host"
GATHER_FAILED = "the gather failed"
NOT_APPLIED = "NOT applied; bantamkit never edits settings.json"


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
