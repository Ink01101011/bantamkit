"""Reply-native (#292): think in English, reply in the user's language.

Pure functions the hook adapter calls. `runtime-ts/src/replynative.ts` is the port; every
regex here is written so it means the same thing in JS `RegExp` (no `\\w`, `\\b`, `\\s`, `$`).
Spec: docs/superpowers/specs/2026-11-07-reply-native-design.md.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from bantamkit.assets import AssetNotFound, load_lang

NATIVE_ENV = "BANTAMKIT_REPLY_NATIVE"
LANG_ENV = "BANTAMKIT_REPLY_LANG"
CORE_MAX = 600
PACK_MAX = 450
INJECT_MAX = 1050
RAW_LANG_MAX = 32
STATE_FILE = "reply-native.json"
_ON = frozenset({"on", "1", "true", "yes"})
_ISO = re.compile(r"[a-z]{2}")

_END = r"(?![\s\S])"
_STRIP = [
    re.compile(
        r"<(pasted_content|ide_[a-z_]+|system-reminder)[^>]*>[\s\S]*?(?:</\1>|" + _END + ")"
    ),
    re.compile(r"```[\s\S]*?(?:```|" + _END + ")"),
    re.compile(r"`[^`\n]*`"),
    re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^ \t\r\n]+"),
    re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|\.{1,2}\\)[^ \t\r\n\"'<>|]+"),
    re.compile(r"(?:~|\.{1,2})?/[^ \t\r\n\"'<>|]+"),
    re.compile(r"\"[^\"\n]*\"|“[^”\n]*”|'[^'\n]{2,}'|「[^」\n]*」|『[^』\n]*』"),
]
_BLANK = re.compile(r"[ \t\r\n]*")
_THAI = re.compile(r"[\u0E01-\u0E2E]")
_KANA = re.compile(r"[\u3040-\u309F\u30A0-\u30FF]")


@dataclass(frozen=True)
class Mode:
    kind: str  # off | latest | fixed
    lang: str | None = None
    raw_lang: str | None = None
    reason: str | None = None

    def as_json(self) -> dict:
        return {
            "kind": self.kind,
            "lang": self.lang,
            "rawLang": self.raw_lang,
            "reason": self.reason,
        }

    @staticmethod
    def from_json(d: Mapping) -> Mode:
        return Mode(d["kind"], d.get("lang"), d.get("rawLang"), d.get("reason"))


@dataclass(frozen=True)
class Plan:
    parts: tuple[str, ...]
    text: str
    reason: str | None = None

    def as_json(self) -> dict:
        return {"parts": list(self.parts), "text": self.text, "reason": self.reason}


def mode(env: Mapping[str, str]) -> Mode:
    if str(env.get(NATIVE_ENV) or "").strip().lower() not in _ON:
        return Mode("off")
    raw = env.get(LANG_ENV)
    if raw is None or _BLANK.fullmatch(raw):
        return Mode("latest")
    norm = raw.strip().lower()
    if _ISO.fullmatch(norm):
        return Mode("fixed", norm)
    return Mode("latest", None, raw[:RAW_LANG_MAX], "invalid-lang")


def frame(prompt: str) -> str:
    out = prompt
    for rx in _STRIP:
        out = rx.sub(" ", out)
    return prompt if _BLANK.fullmatch(out) else out


def classify(prompt: str) -> str | None:
    f = frame(prompt)
    if _THAI.search(f):
        return "th"
    if _KANA.search(f):
        return "ja"
    return None


def _pack(lang: str) -> str | None:
    try:
        return load_lang(lang)
    except AssetNotFound:
        return None


def plan(m: Mode, lang: str | None, seen: Collection[str]) -> Plan:
    if m.kind == "off" or lang is None:
        return Plan((), "")
    if m.kind == "fixed" and lang == "en":
        return Plan((), "", "english")
    try:
        core = load_lang("core-fixed" if m.kind == "fixed" else "core-latest")
    except AssetNotFound:
        return Plan((), "", "asset-missing")
    if m.kind == "fixed":
        core = core.replace("{lang}", lang)
    pack = _pack(lang)
    if m.kind == "latest" and pack is None:
        return Plan((), "", "asset-missing")
    if len(core.encode("utf-8")) > CORE_MAX or (
        pack is not None and len(pack.encode("utf-8")) > PACK_MAX
    ):
        return Plan((), "", "over-budget")
    parts: list[str] = []
    texts: list[str] = []
    if "core" not in seen:
        parts.append("core")
        texts.append(core)
    if pack is not None and lang not in seen:
        parts.append(lang)
        texts.append(pack)
    text = "\n".join(texts)
    if len(text.encode("utf-8")) > INJECT_MAX:
        return Plan((), "", "over-budget")
    return Plan(tuple(parts), text)


def status_line(home: Path | str) -> str:
    """The `reply-native:` line of `bantamkit_status`. Never raises."""
    path = Path(home) / ".bantamkit" / "hooks" / STATE_FILE
    try:
        if not os.path.lexists(path):
            return "reply-native: off"
        rec = json.loads(path.read_text(encoding="utf-8"))
        head = f"reply-native: {rec['mode']}" + (
            f" {rec['lang']}" if rec["mode"] == "fixed" else ""
        )
        parts = rec["parts"]
        what = (
            f"injected {'+'.join(parts)} ({rec['bytes']} bytes)"
            if parts
            else f"nothing injected ({rec.get('reason') or 'nothing to inject'})"
        )
        tail = (
            f"; {LANG_ENV}={rec['rawLang']} invalid, fell back to latest"
            if rec.get("rawLang") is not None
            else ""
        )
        return f"{head}; last {rec['event']} at {rec['ts']}: {what}{tail}"
    except (OSError, ValueError, KeyError, TypeError):
        return "reply-native: the last record is unreadable"
