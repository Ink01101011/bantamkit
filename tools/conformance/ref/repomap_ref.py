"""Reference side of the `repomap` conformance suite — the ranked definition map.

WHY THIS IMPORTS `bantamkit` RATHER THAN COPYING THE ALGORITHM. Same trade `dream_ref.py`
and `store_ref.py` make: `repomap.py` is a thousand lines of scanner, graph and
floating-point iteration, and a hand copy here would be a THIRD implementation needing its
own review. The drift alarm moves rather than disappearing — this suite runs the same calls
against the same fixture trees and compares every stage, so any change to `repomap.py` that
moves a byte reddens the port immediately.

EVERY FLOAT LEAVES AS ITS IEEE-754 BIG-ENDIAN BIT PATTERN IN HEX, NEVER AS A DECIMAL
STRING. J45-7 lost time to `json.dumps(0.0)` = `'0.0'` against `JSON.stringify(0)` = `'0'`
and nearly recorded a `docs/porting.md` divergence row over a serialiser artefact;
`repomap.py`'s trap (8) is the same fact — four of six probed float renderings differ. A
differential that compares `String(x)` measures the serialiser rather than the number.

EVERY STRING THAT MUST SURVIVE BYTE-EXACTLY TRAVELS AS BASE64, for the same reason the
`dream` reference does it: the corpus deliberately holds astral-plane paths and identifiers
(the ONE rule no Python test can make non-vacuous — `_by_code_point` — see J45-9 §7 mutant
26), and a path that went through a JSON string escape on one side and not the other would
compare the escapers.

Protocol: one JSON request on stdin, one JSON response on stdout.

    {"op": "map", "root": <path>, "cases": [{"focus": [...], "budget": int}, ...]}
      -> {"out": [<map>, ...]}            one entry per case

    {"op": "stages", "root": <path>}
      -> {"walk": [...], "scan": {...}, "edges": {...}}

    {"op": "reply", "root": <path>, "cases": [...]}
      -> {"out": [b64, ...]}              the MCP tool's rendered prose

    {"op": "constants"} -> the pinned numbers, floats as bits
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import repomap
from bantamkit.mcpserver import (
    REPO_MAP_EMPTY,
    REPO_MAP_TAIL,
    repo_map_reply,
)


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8", "surrogatepass")).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text).decode("utf-8", "surrogatepass")


def bits(value: float) -> str:
    """A double as its exact IEEE-754 big-endian bytes. The ONLY way a float travels here."""
    return struct.pack(">d", value).hex()


def digest(values) -> str:
    """SHA-256 over a code-point-sorted, NUL-joined set. A set has no order on the wire."""
    joined = "\x00".join(sorted(values, key=repomap._by_code_point))
    return hashlib.sha256(joined.encode("utf-8", "surrogatepass")).hexdigest()


def definition_json(d: repomap.Definition) -> list:
    return [b64(d.path), d.line, b64(d.kind), b64(d.name)]


def omission_json(o: repomap.Omission) -> dict:
    return {
        "subject": b64(o.subject),
        "count": o.count,
        "size": o.size,
        "facts": [[b64(k), v] for k, v in o.facts],
    }


def map_json(result: repomap.RepoMap) -> dict:
    """Every field of `RepoMap`, with `score` as BITS and `text` as base64.

    `rank_units` travels as an int and `score` as bits, and BOTH are compared: the integer
    is the ranking the product uses, the bits are what says the two runtimes agree before
    the quantisation rather than because of it. J45-9 §3.1's point — the floor is a second
    line of defence, not the first — is only checkable if both are on the wire.
    """
    return {
        "text": b64(result.text),
        "ranked": [
            {
                "path": b64(entry.path),
                "rank_units": entry.rank_units,
                "score_bits": bits(entry.score),
                "definitions": [definition_json(d) for d in entry.definitions],
            }
            for entry in result.ranked
        ],
        "omissions": [omission_json(o) for o in result.omissions],
        "focus": [b64(f) for f in result.focus],
        "nodes": result.nodes,
        "edges": result.edges,
        "definitions": result.definitions,
        "damping_bits": bits(result.damping),
        "iterations": result.iterations,
        "budget": result.budget,
        "per_file": result.per_file,
        "listing_bytes": result.listing_bytes,
        "files_rendered": result.files_rendered,
        "definitions_rendered": result.definitions_rendered,
    }


def run_map(request: dict) -> dict:
    root = request["root"]
    out = []
    for case in request["cases"]:
        result = repomap.repo_map(
            root,
            focus=[unb64(f) for f in case.get("focus", [])],
            budget=case.get("budget", repomap.DEFAULT_BUDGET),
        )
        out.append(map_json(result))
    return {"out": out}


def run_stages(request: dict) -> dict:
    """The walk, the per-file scan and the whole edge map — the three stages BEFORE the rank.

    A map comparison alone cannot say WHERE a port diverged: a scanner that missed a
    definition and a graph that dropped an edge both show up as a different listing. These
    three make the first differing stage nameable.
    """
    root = Path(request["root"])
    walked = repomap.walk_sources(root)
    scan: dict[str, dict] = {}
    definitions: dict[str, tuple[repomap.Definition, ...]] = {}
    references: dict[str, set[str]] = {}
    for rel in walked:
        language = repomap.language_of(rel)
        entry: dict = {"language": None if language is None else b64(language)}
        if language is None:
            scan[b64(rel)] = entry
            continue
        path = root / rel
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # The PROBE reports that the read failed, never which class was raised:
            # `pyfs.ts` raises CPython's shapes under names prefixed `Py`, and J45-10 §2
            # measured that recording the class name manufactures two false divergences out
            # of a difference nothing `repomap` returns can observe.
            entry["unreadable"] = True
            scan[b64(rel)] = entry
            continue
        stripped = repomap.strip_noncode(raw, language)
        defs = repomap.scan_definitions(raw, language, rel)
        refs = repomap.reference_names(raw, language)
        entry["stripped_sha256"] = hashlib.sha256(
            "\n".join(stripped).encode("utf-8", "surrogatepass")
        ).hexdigest()
        entry["lines"] = len(stripped)
        entry["definitions"] = [definition_json(d) for d in defs]
        entry["references_sha256"] = digest(refs)
        entry["references"] = len(refs)
        scan[b64(rel)] = entry
        definitions[rel] = defs
        references[rel] = refs
    edges = repomap.build_graph(definitions, references)
    return {
        "walk": [b64(p) for p in walked],
        "scan": scan,
        "edges": {
            b64(source): {b64(t): w for t, w in sorted(targets.items(), key=lambda kv: repomap._by_code_point(kv[0]))}
            for source, targets in sorted(edges.items(), key=lambda kv: repomap._by_code_point(kv[0]))
        },
    }


def run_reply(request: dict) -> dict:
    """The MCP tool's rendered prose, which is the surface J45-11 added.

    Compared as its own case rather than folded into the map: `repo_map_reply` is a THIRD
    thing to keep in step (the header line, the empty-listing sentence and the fixed tail),
    and a suite that only compared `RepoMap` would be green while the two servers printed
    different bytes for the same tree.
    """
    root = request["root"]
    out = []
    for case in request["cases"]:
        result = repomap.repo_map(
            root,
            focus=[unb64(f) for f in case.get("focus", [])],
            budget=case.get("budget", repomap.DEFAULT_BUDGET),
        )
        out.append(b64(repo_map_reply(result)))
    return {"out": out}


def run_constants() -> dict:
    return {
        "DAMPING_bits": bits(repomap.DAMPING),
        "ITERATIONS": repomap.ITERATIONS,
        "MIN_REFERENCE_LENGTH": repomap.MIN_REFERENCE_LENGTH,
        "REFERENCE_DF_MAX_NUM": repomap.REFERENCE_DF_MAX_NUM,
        "REFERENCE_DF_MAX_DEN": repomap.REFERENCE_DF_MAX_DEN,
        "MAX_DEFINITIONS_PER_FILE": repomap.MAX_DEFINITIONS_PER_FILE,
        "DEFAULT_BUDGET": repomap.DEFAULT_BUDGET,
        "SCORE_SCALE": repomap.SCORE_SCALE,
        "MAX_FILE_BYTES": repomap.MAX_FILE_BYTES,
        "SKIP_DIRS": [b64(d) for d in repomap.SKIP_DIRS],
        "LANGUAGES": {b64(k): b64(v) for k, v in repomap.LANGUAGES.items()},
        "OMISSION_ORDER": [b64(s) for s in repomap.OMISSION_ORDER],
        "REPO_MAP_TAIL": b64(REPO_MAP_TAIL),
        "REPO_MAP_EMPTY": b64(REPO_MAP_EMPTY),
    }


def run_pagerank(request: dict) -> dict:
    """`pagerank` on a hand-built graph, so the iteration is compared without a filesystem.

    The nodes and weights are the case's, not a tree's, which is what lets a scenario put a
    dangling node, a self-referencing pair and a focus that is not a node into one call.
    """
    out = []
    for case in request["cases"]:
        nodes = [unb64(n) for n in case["nodes"]]
        edges = {
            unb64(source): {unb64(t): w for t, w in targets.items()}
            for source, targets in case["edges"].items()
        }
        scores = repomap.pagerank(
            nodes,
            edges,
            [unb64(f) for f in case["personal"]],
            case.get("damping", repomap.DAMPING),
            case.get("iterations", repomap.ITERATIONS),
        )
        out.append(
            {
                "bits": [bits(s) for s in scores],
                "rank_units": [math.floor(s * repomap.SCORE_SCALE) for s in scores],
            }
        )
    return {"out": out}


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    op = request["op"]
    if op == "map":
        out = run_map(request)
    elif op == "stages":
        out = run_stages(request)
    elif op == "reply":
        out = run_reply(request)
    elif op == "constants":
        out = run_constants()
    elif op == "pagerank":
        out = run_pagerank(request)
    else:
        raise SystemExit(f"unknown op {op!r}")
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
