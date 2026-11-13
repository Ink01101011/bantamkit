"""Count parsed log records per fixed-length time window."""


def count_by_window(records, minutes: int) -> dict[str, int]:
    """Return {window start: count}, windows aligned to midnight, in time order."""
    if minutes <= 0 or 1440 % minutes != 0:
        raise ValueError(f"minutes must divide a day, got {minutes}")
    counts: dict[str, int] = {}
    for record in sorted(records, key=lambda r: r["ts"]):
        ts = record["ts"]
        minute_of_day = ts.hour * 60 + ts.minute
        start = minute_of_day - minute_of_day % minutes
        window = ts.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
        key = window.strftime("%Y-%m-%dT%H:%MZ")
        counts[key] = counts.get(key, 0) + 1
    return counts
