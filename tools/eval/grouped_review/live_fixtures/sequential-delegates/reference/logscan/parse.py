"""Parse one structured log line."""

from datetime import UTC, datetime

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")


def parse_line(line: str) -> dict | None:
    """Return the line's fields, or None when the line is not well formed."""
    parts = line.strip().split(" ", 2)
    if len(parts) != 3:
        return None
    stamp, level, rest = parts
    level = level.upper()
    if level not in LEVELS:
        return None
    component, sep, message = rest.partition(": ")
    if not sep or not component or " " in component:
        return None
    try:
        ts = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return {"ts": ts, "level": level, "component": component, "message": message.strip()}
