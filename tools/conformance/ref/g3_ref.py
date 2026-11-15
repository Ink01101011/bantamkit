"""Reference side of the #316 G3 coverage cases (J89-1): the memory modules' public constants and
pure functions, and the store-level inputs the hand-written runtimes disagree on.

Imports `bantamkit.memory.*` rather than copying it (`recall_gate_ref.py` gives the reason: a hand
copy would be a third implementation that agrees by construction). The Node half is
`tools/conformance/lib/g3pure.mjs`, which owns the inputs; each owning suite (`recall-usage`,
`recall-retrieval`, `store`, `recall-strings`, `recall-queries`, `dream`, `skill-layer`) pushes its
module's cases from there.

    {"op": "constants", "module": m}               -> {"out": {NAME: json, ...}}
    {"op": "pure", "cases": [[fn, [args]], ...]}   -> {"out": [{"ok": v} | {"err": "Type: msg"}]}
    {"op": "store_root", "roots": [path, ...]}     -> {"out": [answer, ...]}
    {"op": "candidates_done", "root": path, "older_than"?: n}  -> {"out": [[name, why], ...]}
    {"op": "listing", "base": path}                -> {"out": [hex name, ...]}
    {"op": "store_id", "paths": [path, ...]}       -> {"out": [{"ok": id} | {"err": type}]}
    {"op": "word_class"}                           -> {"out": {"w": ranges, "cn": ranges, "ucd": v}}

Strings travel as JSON: `json.loads` reads a `\\udXXX` escape as the lone surrogate Node sent,
and `json.dumps` (ASCII) escapes one back, so no base64 is needed. Every store bed is under the
harness scratch directory and `HOME` is the harness's own.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

_M = {
    m: importlib.import_module(f"bantamkit.memory.{m}")
    for m in ("usage", "retrieval", "store", "dream", "layers", "skills", "queries")
}
usage, retrieval, store, dream, layers, skills, queries = (
    _M[m] for m in ("usage", "retrieval", "store", "dream", "layers", "skills", "queries")
)

# The constants compared, per module: every UPPER_CASE name the two modules both export, minus
# the three that are not data (`retrieval.BM25F` is a scorer object, `WORDCHAR` is a regex on
# Node and a function `_wordchar` here) and `layers.PROJECT_STORE`, which is a `Path` here and a
# list of parts on Node and is compared as its parts. Spelled out, so a constant added on one
# side is a red case (the name list differs) rather than a silently wider comparison.
CONSTANTS = {
    "usage": ["USAGE_HALF_LIFE_DAYS", "LEDGER_FOLD_LINES", "LOCK_WAIT_MS", "LOCK_STALE_MS",
              "LOCK_POLL_MS", "WEIGHT_MAX"],
    "retrieval": ["BM25_K1", "BM25_B", "FIELD_BOOST", "SCORE_ROUND", "QUERY_WEIGHT", "GATE_FLOOR",
                  "GATE_RATIO", "W_TYPE", "W_TYPE_OTHER", "W_FRESH_DEMOTE", "W_USAGE", "W_CONTEXT",
                  "W_FLOOR", "STALE_WORDS"],
    "store": ["BANTAMKIT_GITIGNORE_TEXT", "VALID_TYPES", "VALID_OUTCOMES", "VALID_STATUSES",
              "OUTCOME_TYPES", "DONE_WORDS", "DURABLE_TYPES", "NAME_MAX_CHARS", "DUPLICATE_JACCARD",
              "RECALL_MIN_SCORE_RATIO", "MIN_RATIO_RANGE", "DEFAULT_INDEX_BUDGET",
              "INDEX_PRESSURE_PERCENT"],
    "layers": ["PROJECT_STORE", "CONFIG_NAME", "MEMORY_DIR_ENV"],
    "queries": ["SIDECAR_VERSION", "MAX_QUERIES", "MAX_QUERY_CHARS", "LIST_LIMIT", "BODY_EXCERPT",
                "QUERIES_DIR", "WRITE_FAILED", "TERMS_VERSION", "TERMS_SUFFIX"],
    "native": ["NATIVE_LAYER", "NATIVE_INDEX"],
    "dream": ["PROJECT_LAYER", "PROFILE_LAYER", "SUPERSEDED_HEADING"],
    "skills": ["SKILL_LAYER", "SKILL_TYPE", "KEYWORDS_KEY", "TRIGGERS_DEFAULT"],
}


def _json(value):
    if isinstance(value, Path):
        return list(value.parts)
    if isinstance(value, (set, frozenset)):
        return sorted(_json(x) for x in value)
    if isinstance(value, (list, tuple)):
        return [_json(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    return value


def constants(module: str) -> dict:
    mod = importlib.import_module(f"bantamkit.memory.{module}")
    return {name: _json(getattr(mod, name)) for name in CONSTANTS[module]}


def _parse_ms(ts):
    """`parseTs`'s contract on this side: milliseconds, or `None` where `_parse` raises."""
    try:
        return usage._parse(ts) * 1000
    except ValueError:
        return None


def _absolutise(body, basis):
    text, hits, unresolved = dream.absolutise(body, basis, "n", "project")
    return [text, [vars(h) for h in hits], [vars(h) for h in unresolved]]


PURE = {
    "parseTs": _parse_ms,
    "seedTs": usage.seed_ts,
    "stripNospace": retrieval.strip_nospace,
    "tokenizeV2": retrieval.tokenize_v2,
    "queryTerms": retrieval.query_terms,
    "stale": retrieval.stale,
    "weightOf": retrieval.weight_of,
    "loneSurrogate": store.lone_surrogate,
    "tokens": store.tokens,
    "jaccard": lambda a, b: store._jaccard(set(a), set(b)),
    "collapse": dream.collapse,
    "blockKey": dream.block_key,
    "splitBlocks": dream.split_blocks,
    "claimSlot": dream.claim_slot,
    "unionKeywords": dream.union_keywords,
    "mergeLinks": dream.merge_links,
    "mergeDescriptions": dream.merge_descriptions,
    "absolutise": _absolutise,
    "tabSentence": layers.tab_sentence,
    "keywordsOf": skills.keywords_of,
    "triggersOf": skills.triggers_of,
    "checkQueries": queries.check_queries,
    "qdoc": queries.qdoc,
    "queriesStatusLine": queries.status_line,
}


def pure(cases: list) -> list:
    out = []
    for fn, args in cases:
        try:
            out.append({"ok": _json(PURE[fn](*args))})
        except Exception as e:  # noqa: BLE001 -- a raise is an answer
            out.append({"err": f"{type(e).__name__}: {e}"})
    return out


def store_root(roots: list) -> list:
    """One save and one recall at each root: what the caller is told, and nothing else."""
    out = []
    for root in roots:
        try:
            s = store.MemoryStore(
                root, today=lambda: "2026-08-23", now=lambda: "2026-08-23T00:00:00Z"
            )
            saved = s.save("project", "x-fact", "desc words here", "body")
            hits = s.recall("desc words", 3, True)
            out.append({"ok": [saved.status, len(hits)]})
        except BaseException as e:  # noqa: BLE001 -- the refusal is the answer
            out.append({"err": [type(e).__name__, str(e)]})
    return out


def candidates_done(root: str, older_than: int | None = None) -> list:
    s = store.MemoryStore(root, today=lambda: "2026-08-23", create=False)
    return [[str(f.name), why] for f, why in s.candidates_done(older_than_days=older_than)]


def listing(base: str) -> list:
    """The entry names under `base` as bytes (hex), so a U+FFFD and a raw byte are told apart."""
    return sorted(name.hex() for name in os.listdir(os.fsencode(base)))


def store_ids(paths: list) -> list:
    out = []
    for p in paths:
        try:
            out.append({"ok": usage.store_id(p)})
        except Exception as e:  # noqa: BLE001 -- a raise is an answer
            out.append({"err": type(e).__name__})
    return out


def _ranges(pred) -> list:
    """[[lo, hi], ...] inclusive, of every code point 0..0x10FFFF for which `pred` holds."""
    out: list = []
    for cp in range(0x110000):
        if pred(cp):
            if out and out[-1][1] == cp - 1:
                out[-1][1] = cp
            else:
                out.append([cp, cp])
    return out


def word_class() -> dict:
    """J89-1F: CPython's `\\w` over every code point, and the code points its UCD leaves unassigned."""
    import re
    import unicodedata

    w = re.compile(r"\w")
    return {
        "w": _ranges(lambda cp: w.match(chr(cp)) is not None),
        "cn": _ranges(lambda cp: unicodedata.category(chr(cp)) == "Cn"),
        "ucd": unicodedata.unidata_version,
    }


def main() -> None:
    req = json.load(sys.stdin)
    op = req["op"]
    if op == "constants":
        out = constants(req["module"])
    elif op == "pure":
        out = pure(req["cases"])
    elif op == "store_root":
        out = store_root(req["roots"])
    elif op == "candidates_done":
        out = candidates_done(req["root"], req.get("older_than"))
    elif op == "listing":
        out = listing(req["base"])
    elif op == "store_id":
        out = store_ids(req["paths"])
    elif op == "word_class":
        out = word_class()
    else:
        raise ValueError(f"unknown op {op!r}")
    sys.stdout.write(json.dumps({"out": out}, ensure_ascii=True))


if __name__ == "__main__":
    main()
