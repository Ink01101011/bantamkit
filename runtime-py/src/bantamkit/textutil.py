"""Byte-budget truncation shared by the core loop and contract rendering."""

from __future__ import annotations


def truncate_counted(text: str, budget: int) -> tuple[str, int]:
    """`truncate`, plus the number of bytes it dropped. Zero when nothing was cut.

    C-6, 2026-08-19. The cut was already announced, but IN BAND — inside the string
    handed to the model, as `[truncated N bytes]`. The number was known here and thrown
    away, so nothing outside the model's own context could tell a run whose observations
    were cut from one whose were not. RB-P51's shape: a run that silently proceeded is
    not the same run as one that reported what it dropped.

    The second return value is what makes it a column. It is deliberately NOT parsed back
    out of the marker by a caller: that would be a second transcription of one rule and a
    check over the two would be a tautology (RB-P47).
    """
    raw = text.encode()
    if len(raw) <= budget:
        return text, 0
    dropped = len(raw) - budget
    kept = raw[:budget].decode(errors="ignore")
    return f"{kept}\n[truncated {dropped} bytes]", dropped


def truncate(text: str, budget: int) -> str:
    """Byte-identical to what it always returned. Callers that want the count call
    `truncate_counted`; `contract.py` and `filegraph.py` do not and are unchanged."""
    return truncate_counted(text, budget)[0]
