"""Reference side of the `dream` conformance suite — the cross-layer consolidation pass.

WHY THIS IMPORTS `bantamkit` RATHER THAN COPYING THE ALGORITHM. Same trade `store_ref.py`
makes and for the same reason: `dream.py` is seven hundred lines of stateful filesystem
behaviour, and a hand copy here would be a THIRD implementation needing its own review. The
drift alarm moves rather than disappearing — this suite runs the same call against two
copies of one pair of stores and diffs both whole trees, so any change to `dream.py` that
moves a byte reddens the port immediately.

WHAT THE COMPARISON IS. `dream()` answers a `DreamResult` and it WRITES: a survivor into the
project store, the profile copy into the profile store's `archive/`, and an index rebuild in
each store that already had one. So a scenario is compared on three things and not one — the
result, the project tree, and the profile tree — because "it returned the right plan" and
"it left the right bytes on disk" are different claims and this pass can fail either.

Protocol: one JSON request on stdin, one JSON response on stdout. Every string that must
survive byte-exactly travels as base64.

    {"op": "run", "project": <path>, "profile": <path>, "dry_run": bool,
     "index_budget": int|null, "profile_index_budget": int|null, "create": bool,
     "passes": int}
      -> {"results": [<result>|{"error": {...}}, ...]}   one entry per pass

    {"op": "absolutise", "cases": [[body_b64, basis, name_b64, layer], ...]}
      -> {"out": [{"body": b64, "hits": [...], "unresolved": [...]}, ...]}
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit.memory.dream import absolutise, dream
from bantamkit.memory.store import MemoryStore


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8", "surrogatepass")).decode("ascii")


def unb64(text: str) -> str:
    return base64.b64decode(text).decode("utf-8", "surrogatepass")


def text(value: object) -> str:
    """`str(value)` — the frontmatter may have resolved to an int, a date or None."""
    return b64(str(value))


def hit_json(hit) -> dict:
    return {
        "name": text(hit.name),
        "layer": b64(hit.layer),
        "term": b64(hit.term),
        "resolved": b64(hit.resolved),
        "basis": b64(hit.basis),
    }


def superseded_json(record) -> dict:
    return {
        "subject": b64(record.subject),
        "kept": b64(record.kept),
        "kept_layer": b64(record.kept_layer),
        "kept_date": b64(record.kept_date),
        "lost": b64(record.lost),
        "lost_layer": b64(record.lost_layer),
        "lost_date": b64(record.lost_date),
    }


def merge_json(merge) -> dict:
    return {
        "name": text(merge.name),
        "kind": merge.kind,
        "jaccard": merge.jaccard,
        "survivor_layer": b64(merge.survivor_layer),
        "consumed_layer": b64(merge.consumed_layer),
        "body_before": merge.body_before,
        "body_after": merge.body_after,
        "blocks_added": merge.blocks_added,
        "superseded": [superseded_json(r) for r in merge.superseded],
    }


def result_json(result, project_root: str, profile_root: str) -> dict:
    """The whole `DreamResult`, with the two bed roots replaced by markers.

    The roots differ between the `py/` and `node/` halves of one scenario — the harness
    created that difference — so they are SUBSTITUTED rather than dropped: a message naming
    the wrong root still differs, and `archive_dir` still proves which store was written to.
    """

    def scrub(value: str) -> str:
        return value.replace(project_root, "<PROJECT>").replace(profile_root, "<PROFILE>")

    return {
        "applied": result.applied,
        "dry_run": result.dry_run,
        "merged": [merge_json(m) for m in result.merged],
        "refused": [[text(name), b64(scrub(why))] for name, why in result.refused],
        "absolutised": [hit_json(h) for h in result.absolutised],
        "unresolved": [hit_json(h) for h in result.unresolved],
        "similar_unmerged": [
            {"project_name": text(p.project_name), "profile_name": text(p.profile_name),
             "jaccard": p.jaccard}
            for p in result.similar_unmerged
        ],
        "consumed": [text(n) for n in result.consumed],
        "rewritten": [text(n) for n in result.rewritten],
        "archive_dir": b64(scrub(result.archive_dir)),
        "index_before": result.index_before,
        "index_after": result.index_after,
        "budget": result.budget,
        "profile_index_before": result.profile_index_before,
        "profile_index_after": result.profile_index_after,
        "fact_bytes_before": result.fact_bytes_before,
        "fact_bytes_after": result.fact_bytes_after,
        "project_root": b64(scrub(result.project_root)),
        "profile_root": b64(scrub(result.profile_root)),
        "over_budget": result.over_budget,
        "changes": result.changes,
        "superseded": [superseded_json(r) for r in result.superseded],
    }


def error_json(e: BaseException, project_root: str, profile_root: str) -> dict:
    message = str(e).replace(project_root, "<PROJECT>").replace(profile_root, "<PROFILE>")
    return {"error": {"type": type(e).__name__, "message": b64(message)}}


def run_dream(request: dict) -> dict:
    project_root = request["project"]
    profile_root = request["profile"]
    create = request.get("create", True)
    results = []
    for _ in range(request.get("passes", 1)):
        try:
            kwargs = {}
            if request.get("index_budget") is not None:
                kwargs["index_budget"] = request["index_budget"]
            project = MemoryStore(project_root, create=create, **kwargs)
            profile_kwargs = {}
            if request.get("profile_index_budget") is not None:
                profile_kwargs["index_budget"] = request["profile_index_budget"]
            profile = MemoryStore(profile_root, create=create, **profile_kwargs)
            outcome = dream(project, profile, request.get("dry_run", True))
            results.append(result_json(outcome, project_root, profile_root))
        except BaseException as e:  # noqa: BLE001 — every failure is part of the comparison
            results.append(error_json(e, project_root, profile_root))
    return {"results": results}


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    op = request["op"]
    if op == "run":
        out = run_dream(request)
    elif op == "absolutise":
        rows = []
        for body, basis, name, layer in request["cases"]:
            try:
                new_body, hits, unresolved = absolutise(unb64(body), basis, unb64(name), layer)
                rows.append({
                    "body": b64(new_body),
                    "hits": [hit_json(h) for h in hits],
                    "unresolved": [hit_json(h) for h in unresolved],
                })
            except BaseException as e:  # noqa: BLE001 — a raise here is the whole finding
                rows.append({"error": {"type": type(e).__name__, "message": b64(str(e))}})
        out = {"out": rows}
    else:
        raise SystemExit(f"unknown op {op!r}")
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
