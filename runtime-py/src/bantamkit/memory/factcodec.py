"""The fact-file codec runtime-py reads and writes through: the GENERATED one, then PyYAML (#315).

`bantamkit._generated.factfile` and `bantamkit._generated.pyyaml` are compiled by `tools/ts2py`
from `runtime-ts/src/memory/factfile.ts` and `pyyaml.ts`, the codec the Node server uses, so
both runtimes read and write a fact file through ONE source. This module is the seam between
that code and the store, and the only place in it that still calls PyYAML for a fact file.

GENERATED FIRST, PYYAML WHEN IT REFUSES (user ruling 2026-11-15, #315 option A). The generated
codec implements the language `safe_dump` writes for a fact plus the hand-written shapes #120 and
#219 added, and refuses everything else by name. Where it refuses, the file is read or written
by real PyYAML exactly as before #315, so every file runtime-py read and wrote before it still
reads and writes byte for byte, and #120's ruling ("python reads every one") stays true. The
only answers that moved are the two the ruling names, both towards Node's:

- `yaml11-breaks`: U+0085, U+2028 and U+2029 in a scalar are KEPT, where PyYAML's YAML 1.1
  scanner folded each as a line break (so runtime-py did not read back what it had written);
- `pyyaml-refuses`: a frontmatter PyYAML refused and the codec reads (a raw non-printable
  character, a multi-line single-quoted scalar continued at column 0) is now read.

THE ADAPTER IS NOT A SECOND CODEC. The generated code holds a `PyScalar` (`pyyaml.ts`) where
PyYAML holds an `int`, `bool`, `float`, `date` or `datetime`; the store, the index and every
reply were written against PyYAML's values, so `_native` turns each one into the Python value
`safe_load` builds and `_scalar` turns a Python value back. Each conversion is CHECKED, not
trusted: a value read must print (`str()`) as the generated scalar's `text`, and a value
written must come back from `construct_plain` with PyYAML's own plain spelling as its `yaml`.
Anything that fails a check -- or that the generated codec cannot hold at all (a set, bytes,
a non-text key in a nested map, a collection appearing twice) -- goes the PyYAML way.

A READ IS NEVER GUESSED (J86-R). Where the generated structure cannot be turned into exactly
what `safe_load` builds, the read is PyYAML's: a text holding any `\r` (PyYAML breaks a line
there, the codec keeps it as text), and a mapping, at any depth, in which two raw keys become
one native key (`yes:` and `on:` are both `True`; PyYAML's last-in-file-order winner is not
recoverable from the codec's text-keyed answer).
"""

from __future__ import annotations

import math
import sys
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import yaml

from bantamkit import stdlib312 as _stdlib312
from bantamkit._generated import factfile as _gen
from bantamkit._generated import pyyaml as _genyaml

if TYPE_CHECKING:
    from .store import Fact

# libyaml when it is there (#204): J69-2 measured 0.9 s of a 1.50 s hot-index build at 5,000
# facts in the pure-Python `SafeLoader`. Both loaders resolve scalars with the same
# `SafeConstructor`; only the scanner differs, and its ERROR TEXT differs -- so any refusal
# from the C loader is re-parsed by the pure one, and the sentence a model reads is the one
# it always was.
_CSafeLoader = getattr(yaml, "CSafeLoader", None)

# The frontmatter keys a fact owns; every other key rides in `Fact.extra` (`store.OWNED_KEYS`).
_OWNED = frozenset(_gen.OWNED_KEYS)


class _Unheld(Exception):
    """A value the generated codec cannot hold, or a conversion that did not check out."""


# ------------------------------------------------------------------------------------ read


def load_frontmatter(text: str) -> Any:
    """The frontmatter `text` as `yaml.safe_load` values: the generated codec's read, else PyYAML's.

    The generated read answers when it reads the text and its answer converts back to PyYAML's
    values exactly; an EMPTY answer is not taken either (`''` and a comment-only text read as
    `{}` there and as `None` in PyYAML, and `None` is what the store's sentence is about).
    Anything else is the PyYAML read, which answers or raises exactly as it did before #315.
    """
    from .store import well_formed_frontmatter

    if "\r" in text:
        # J86-R finding 2: the generated codec reads a CR as text (`name: on\r` is `'on\r'`)
        # where PyYAML breaks the line there (`True`). The store reads with universal newlines,
        # but the promise of `safe_load` values is to every caller, so any CR is PyYAML's.
        return _pyyaml_load(text)
    held = _READ.get(text)
    if held is not None:
        return _fresh(held)
    try:
        meta = _gen.parse_frontmatter(text)
        if meta:
            # The store's own normalisation as well as the codec's (#212): idempotent, and it
            # is the one every other reader of a frontmatter in this package applies.
            value = well_formed_frontmatter(text, _native_mapping(meta))
            _remember(text, value)
            return _fresh(value)
    except Exception:  # noqa: BLE001 -- a JS throw lowers to several types; any is a refusal
        pass
    return _pyyaml_load(text)


# J86-5: THE READ CACHE. The generated read costs ~7x libyaml's (docs/roadmap-1.0.0.md, #315), and
# one process reads the same unchanged file many times: a SessionStart hook parses 316 frontmatters
# for ~190 files, and the MCP server re-reads every fact on every save. The answer is a function of
# the frontmatter TEXT alone, so it is keyed by the text itself -- not by path and mtime, which a
# same-size edit inside one mtime tick would fool -- and a hit is the answer a fresh parse gives.
# Every hit is a fresh copy of the lists and dicts (scalars are immutable), so no caller can change
# what the next one reads. Only the generated codec's answers are kept; a PyYAML fallback is read
# again each time, exactly as before. Bounded: emptied when full, and a long text is never kept.
# Full is EITHER bound (J86-R finding 5a): 4096 entries, or 4 MiB of key text as `sys.getsizeof`
# counts it -- the count alone allowed 4096 x 32 KiB = 128 MiB of keys. The value a key holds is
# built from that text, so the text's size is the measure of the entry.
_READ: dict[str, Any] = {}
_READ_ENTRIES = 4096
_READ_LONGEST = 1 << 15
_READ_BYTES = 4 << 20
_READ_SIZE = 0  # `sys.getsizeof` of every key in `_READ`, summed


def _remember(text: str, value: Any) -> None:
    global _READ_SIZE
    if len(text) > _READ_LONGEST:
        return
    size = sys.getsizeof(text)
    if len(_READ) >= _READ_ENTRIES or _READ_SIZE + size > _READ_BYTES:
        _READ.clear()
        _READ_SIZE = 0
    _READ[text] = _fresh(value)
    _READ_SIZE += size


def _fresh(value: Any) -> Any:
    """`value` with every list and dict rebuilt; the scalars the codec yields are immutable."""
    if isinstance(value, dict):
        return {k: _fresh(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_fresh(v) for v in value]
    return value


def _pyyaml_load(text: str) -> Any:
    """THE READ FALLBACK: `yaml.safe_load` (libyaml if present); refusals are the pure loader's."""
    from .store import well_formed_frontmatter

    if _CSafeLoader is not None:
        try:
            return well_formed_frontmatter(text, yaml.load(text, Loader=_CSafeLoader))  # noqa: S506 -- SAFE
        except Exception:  # noqa: BLE001 -- the pure loader decides what a refusal says
            pass
    return well_formed_frontmatter(text, safe_load(text))


def safe_load(text: str) -> Any:
    """`yaml.safe_load(text)`, a timestamp's `datetime` range sentence in CPython 3.12's spelling.

    PyYAML builds `date`/`datetime`/`timezone` from a plain timestamp, and the `ValueError` a bad
    one raises is CPython's own text, which 3.14 rewrote (gh-109798: `month must be in 1..12` ->
    `month must be in 1..12, not 13`). The port spells 3.12's, and the store quotes the sentence
    into `malformed fact file <path>: ...`, so it is re-spelled here (`stdlib312`).
    """
    try:
        return yaml.safe_load(text)
    except ValueError as e:
        pinned = _stdlib312.pin_datetime_error(e)
        if pinned is e:
            raise
        raise pinned from None


def _native_mapping(meta: dict) -> dict:
    out: dict = {}
    for key, value in meta.items():
        # A key YAML resolves to a non-string (`on:` is True, `null:` is None) is keyed by that
        # value, as PyYAML keys it; the codec keys it by its text.
        native_key = key if _gen.is_text_key(key) else _native(_genyaml.construct_plain(key))
        if native_key in out:
            # J86-R finding 1: two raw keys of one mapping that become ONE native key (`yes:` and
            # `on:` are both `True`). PyYAML assigns them in file order and the last wins; the
            # codec already merged each text's repeats (first place, last value), so the order
            # PyYAML needs is gone and folding here could only guess. Not a guess: PyYAML's read.
            raise _Unheld(f"keys {key!r} and an earlier one are the same {native_key!r}")
        out[native_key] = _native(value)
    return out


def _native(value: Any) -> Any:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_native(v) for v in value]
    if isinstance(value, dict):
        return _native_mapping(value)
    if isinstance(value, _genyaml.PyScalar):
        kind, text = value.pyType, value.text
        if kind == "bool":
            native: Any = text == "True"
        elif kind == "int":
            native = int(text)
        elif kind == "float":
            native = float(text)
        elif kind == "datetime.date":
            native = date.fromisoformat(text)
        elif kind == "datetime.datetime":
            native = datetime.fromisoformat(text)
        else:
            raise _Unheld(f"no Python value for a generated {kind}")
        if type(native).__name__ != kind.rpartition(".")[2] or str(native) != text:
            raise _Unheld(f"{kind} {text!r} does not convert back exactly")
        return native
    raise _Unheld(f"no Python value for a generated {type(value).__name__}")


# ----------------------------------------------------------------------------------- write


def fact_text(fact: Fact) -> str:
    """The bytes `_write_fact` writes for `fact`: the generated `format_fact`, else PyYAML's."""
    try:
        seen: set[int] = set()
        held = {
            "name": _scalar(fact.name, seen),
            "description": _scalar(fact.description, seen),
            "type": _scalar(fact.type, seen),
            "created": _scalar(fact.created, seen),
            "last_recalled": _scalar(fact.last_recalled, seen),
            "links": _scalar(fact.links, seen),
            "keywords": _scalar(fact.keywords, seen),
            "outcome": _scalar(fact.outcome, seen),
            "status": _scalar(fact.status, seen),
            "extra": [[_key(k), _scalar(v, seen)] for k, v in fact.extra.items()
                      if k not in _OWNED],
            "body": fact.body,
        }
        return _gen.format_fact(held)
    except Exception:  # noqa: BLE001 -- a JS throw lowers to several types; any is a refusal
        pass
    return _pyyaml_fact_text(fact)


def _pyyaml_fact_text(fact: Fact) -> str:
    """THE WRITE FALLBACK: `_fact_text` as it was before #315, through `yaml.safe_dump`."""
    meta = {
        "name": fact.name,
        "description": fact.description,
        "type": fact.type,
        "created": fact.created,
        "last_recalled": fact.last_recalled,
        "links": fact.links,
    }
    # Only when non-empty (#199): a fact that never had keywords keeps its bytes.
    if fact.keywords:
        meta["keywords"] = fact.keywords
    # #219 / #221 (0.36.2): after `keywords`, before the hand-written keys.
    if fact.outcome is not None:
        meta["outcome"] = fact.outcome
    if fact.status is not None and fact.status != "active":
        meta["status"] = fact.status
    # After the owned keys, in the order the file had them (#199 Task 6).
    for key, value in fact.extra.items():
        if key not in _OWNED:
            meta[key] = value
    return (
        "---\n"
        + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + fact.body.strip()
        + "\n"
    )


def _scalar(value: Any, seen: set[int]) -> Any:
    """`value` as the generated codec holds it, or `_Unheld`. `seen` is every collection so far.

    Types are matched EXACTLY, as `SafeRepresenter` matches them: a subclass of `str` or `int`
    has no representer there and `safe_dump` raises, so it goes the PyYAML way and raises still.
    """
    if value is None or type(value) is str:
        return value
    if isinstance(value, (list, dict)):
        # PyYAML writes a collection met twice as an anchor and an alias; the generated codec
        # refuses it. Refused here first, by identity, as PyYAML's representer tests it.
        if id(value) in seen:
            raise _Unheld("a collection appears twice")
        seen.add(id(value))
        if isinstance(value, list) and type(value) is list:
            return [_scalar(v, seen) for v in value]
        if type(value) is dict and all(type(k) is str for k in value):
            return {k: _scalar(v, seen) for k, v in value.items()}
        raise _Unheld(f"cannot hold a {type(value).__name__}")
    if isinstance(value, date):
        # Not on `SafeRepresenter.ignore_aliases`' list (None, (), str, bytes, bool, int, float),
        # so PyYAML anchors a `date` or `datetime` OBJECT met twice (`&id001 2026-08-23`) too.
        if id(value) in seen:
            raise _Unheld("a date object appears twice")
        seen.add(id(value))
    spelling = _plain_spelling(value)
    held = _genyaml.construct_plain(spelling)
    if not isinstance(held, _genyaml.PyScalar) or held.yaml != spelling:
        raise _Unheld(f"{spelling!r} does not re-emit as PyYAML writes it")
    return held


def _key(key: Any) -> str:
    if type(key) is not str:
        raise _Unheld(f"cannot hold a {type(key).__name__} key")
    return key


def _plain_spelling(value: Any) -> str:
    """`SafeRepresenter`'s scalar for a bool, int, float, date or datetime (PyYAML 6.0.3)."""
    kind = type(value)
    if kind is bool:
        return "true" if value else "false"
    if kind is int:
        return str(value)
    if kind is float:
        if math.isnan(value):
            return ".nan"
        if math.isinf(value):
            return ".inf" if value > 0 else "-.inf"
        text = repr(value).lower()
        return text.replace("e", ".0e", 1) if "." not in text and "e" in text else text
    if kind is datetime:
        return value.isoformat(" ")
    if kind is date:
        return value.isoformat()
    raise _Unheld(f"cannot hold a {kind.__name__}")


# ------------------------------------------------------------- the generated store's seam (J89-4b)
#
# #316 G3 U2: `memory/store` is generated from `store.ts`, which reads a frontmatter with
# `parseFrontmatter` and writes a fact with `formatFact`. In Python both reach the store through the
# two functions below (the `parse_frontmatter` / `format_fact` adapters), so the generated store
# reads and writes through THIS codec -- generated first, PyYAML where it refuses (#315, the owner's
# ruling "generated + PyYAML fallback") -- and reads exactly what `load_frontmatter` reads and
# writes exactly the bytes `fact_text` writes. The store holds the codec's shape (`PyScalar`, plain
# lists and dicts); a value that shape cannot hold the way Python holds it is carried OPAQUELY
# (`_Opaque`): a set, bytes, a tuple, a collection met twice (PyYAML writes it back as an anchor and
# an alias), a dict with a non-text key, a scalar that does not re-emit as PyYAML writes it, and a
# list or dict where the store interpolates the value as text (`name`, `description`, `type`, the
# stamps, the lifecycle fields, a `links` item, a `metadata` value), so `str()` of it is still
# Python's. An opaque value prints, compares (never equal, `<` a TypeError naming its type) and
# tests truthy as Python's value does, and the write hands the original object back to `fact_text`.

_TEXT_FIELDS = frozenset(
    {"name", "description", "type", "created", "last_recalled", "outcome", "status"}
)


class _Opaque(_genyaml.PyScalar):
    """A value the codec's shape cannot hold, carried for the write (`native`)."""

    def __init__(self, native: Any) -> None:
        object.__setattr__(self, "_bk_native", native)
        super().__init__(
            "tag:bantamkit:opaque",
            type(native).__name__,
            str(native),
            None,
            bool(native),
            {"kind": "opaque"},
        )


def _shared_ids(value: Any) -> set[int]:
    """Ids of the collections (and date objects) met more than once under `value`."""
    seen: set[int] = set()
    twice: set[int] = set()
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, (list, dict, date)):
            if id(v) in seen:
                twice.add(id(v))
                continue
            seen.add(id(v))
            if isinstance(v, list):
                stack.extend(v)
            elif isinstance(v, dict):
                stack.extend(v.keys())
                stack.extend(v.values())
    return twice


def _held(value: Any, shared: set[int], text: bool = False) -> Any:
    """`value` in the codec's shape, or `_Unheld`. `text`: a list or dict here is opaque."""
    if value is None or type(value) is str:
        return value
    kind = type(value)
    if kind is list or kind is dict:
        if text or id(value) in shared:
            raise _Unheld("a collection where text is read, or met twice")
        if kind is list:
            return [_held(v, shared) for v in value]
        if not all(type(k) is str for k in value):
            raise _Unheld("a non-text key")
        return {k: _held(v, shared) for k, v in value.items()}
    if kind in (bool, int, float, date, datetime):
        if kind in (date, datetime) and id(value) in shared:
            raise _Unheld("a date object met twice")
        spelling = _plain_spelling(value)
        held = _genyaml.construct_plain(spelling)
        if not isinstance(held, _genyaml.PyScalar) or held.yaml != spelling:
            raise _Unheld(f"{spelling!r} does not re-emit as PyYAML writes it")
        back = _native(held)
        if type(back) is not kind or str(back) != str(value):
            raise _Unheld(f"{spelling!r} does not read back as the same value")
        return held
    raise _Unheld(f"cannot hold a {kind.__name__}")


def _held_or_opaque(value: Any, shared: set[int], text: bool = False) -> Any:
    try:
        return _held(value, shared, text)
    except _Unheld:
        return _Opaque(value)


def held_meta(meta: dict, read: bool = True) -> dict:
    """A frontmatter, or a fact's fields, in the codec's shape (see above). A key that is not text
    is left out: the store reads its keys by name and carries text keys only (`extraOf`).

    `read`: the frontmatter `safe_load` built, so `links` is a NEW list of its items (the reference
    reads it as `list(meta["links"])`, which never aliases another value). Otherwise these are a
    `Fact`'s own fields on their way to a write, and a `links` list another value shares is carried
    opaque, so PyYAML still writes the anchor and the alias (`fact_text`)."""
    shared = _shared_ids(meta)
    out: dict = {}
    for key, value in meta.items():
        if type(key) is not str:
            continue
        if key == "links" and type(value) is list and (read or id(value) not in shared):
            out[key] = [_held_or_opaque(v, shared, text=True) for v in value]
        elif key == "metadata" and type(value) is dict and id(value) not in shared and all(
            type(k) is str for k in value
        ):
            out[key] = {k: _held_or_opaque(v, shared, text=True) for k, v in value.items()}
        else:
            out[key] = _held_or_opaque(value, shared, text=key in _TEXT_FIELDS)
    return out


def held_values(values: list) -> list:
    """Several values in the codec's shape, a collection two of them share opaque; a list or dict
    is opaque too (each is a value the store reads as text: a name)."""
    shared = _shared_ids(values)
    return [_held_or_opaque(v, shared, text=True) for v in values]


def native_value(value: Any) -> Any:
    """The Python value the codec's `value` stands for (an opaque value's original object)."""
    if value is None or type(value) is str:
        return value
    if isinstance(value, _Opaque):
        return value._bk_native
    if isinstance(value, list):
        return [native_value(v) for v in value]
    if isinstance(value, dict):
        return {k: native_value(v) for k, v in value.items()}
    return _native(value)


def held_frontmatter(text: str) -> Any:
    """THE `parseFrontmatter` ADAPTER: `load_frontmatter(text)` in the codec's shape. A refusal is a
    JS Error carrying the reference's `str(e)`, as `_read_fact`'s `except` printed it; an answer
    that is not a mapping is `frontmatter is not a mapping`, the reference's own sentence."""
    from bantamkit._generated._ts2py_runtime import _JsError

    try:
        meta = load_frontmatter(text)
    except (ValueError, KeyError, yaml.YAMLError) as e:
        raise _JsError(str(e)) from None
    if not isinstance(meta, dict):
        raise _JsError("frontmatter is not a mapping")
    return held_meta(meta)


def held_fact_text(fact: Any) -> str:
    """THE `formatFact` ADAPTER: `fact_text` of the fact the generated store holds (`fact` is a
    dict in the codec's shape), so the bytes are the ones `fact_text` writes for the same values."""
    from types import SimpleNamespace

    from bantamkit._generated._ts2py_runtime import _JS_UNDEFINED

    def get(key: str, default: Any = None) -> Any:
        value = fact.get(key, default)
        return default if value is _JS_UNDEFINED else value

    extra = get("extra") or []
    return fact_text(
        SimpleNamespace(
            name=native_value(get("name")),
            description=native_value(get("description")),
            type=native_value(get("type")),
            body=get("body", ""),
            links=native_value(get("links", [])),
            last_recalled=native_value(get("last_recalled")),
            created=native_value(get("created")),
            outcome=native_value(get("outcome")),
            status=native_value(get("status")),
            keywords=list(get("keywords") or []),
            extra={k: native_value(v) for k, v in extra},
        )
    )
