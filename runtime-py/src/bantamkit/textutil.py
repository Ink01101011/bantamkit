"""Byte-budget truncation shared by the core loop and contract rendering."""

from __future__ import annotations


def truncate(text: str, budget: int) -> str:
    raw = text.encode()
    if len(raw) <= budget:
        return text
    kept = raw[:budget].decode(errors="ignore")
    return f"{kept}\n[truncated {len(raw) - budget} bytes]"
