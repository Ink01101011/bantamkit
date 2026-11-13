"""Rank components by how many records they logged at one level."""


def top_components(records, level: str, limit: int = 3) -> list[tuple[str, int]]:
    """Return up to ``limit`` (component, count) pairs, busiest first, ties by name."""
    wanted = level.upper()
    counts: dict[str, int] = {}
    for record in records:
        if record["level"] == wanted:
            counts[record["component"]] = counts.get(record["component"], 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:limit]
