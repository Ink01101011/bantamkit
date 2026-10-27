"""Reference side of the `skill-miner` conformance suite (#206 Tasks 4a and 5).

Imports `bantamkit.skillmine` rather than copying it: a hand copy would be a third
implementation that agrees by construction. The Node half of the suite runs the same ops
against `runtime-ts/dist/skillmine.js`.

    {"roots": [path, ...],
     "repo_keys": [path, ...],
     "piece_sets": [[{"prompt", "tools", "paths"}, ...], ...],
     "pairs": [[signature_dict, signature_dict], ...]}
      -> {"pieces": [[piece_dict, ...] per root],
          "repo_keys": [str, ...],
          "root_signatures": [[signature_dict, ...] per root],
          "set_signatures": [[signature_dict, ...] per set],
          "similarity": [[num, den, meets], ...]}

Task 5 adds, all optional in the payload:

    {"mines": [{"pieces": [piece_dict, ...], "previous": doc | null, "now", "ms"}, ...],
     "root_mines": [{"roots": [path, ...], "previous": doc | null, "now"}, ...],
     "write": {"home": path, "doc_of": <index into mines>},
     "reads": [{"home": path}, ...]}
      -> {"mines": [doc, ...], "mine_bytes": [hex, ...], "root_mines": [doc, ...],
          "write": {"path": str, "hex": str, "read_back": doc},
          "reads": [["none"] | ["ok", doc] | ["error", message], ...]}

Task 4b adds, also optional:

    {"session_runs": [{"home", "now", "cache", "save"}, ...],
     "miner_runs": [{"home", "root", "now", "cache"}, ...]}
      -> {"session_runs": [{"pieces", "bytes_read", "cache_hex"}, ...],
          "miner_runs": [{"doc", "hex", "pieces"}, ...]}

job73 C8 adds `{"commit_subjects": [command, ...]} -> {"commit_subjects": [str | null, ...]}`.

`session_runs` mine `<home>/.claude/projects` through `select_adapter(home)` with the cache at
`cache` (loaded first; saved after when `save`). `miner_runs` run `miner_pieces` and `mine`.

`root_signatures` takes one root's shiftwork pieces as one source: its document frequencies
are counted over exactly those pieces. Every fixture is synthetic and every root is a
scratch directory the harness made; the miner only reads.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit.skillhost import select_adapter
from bantamkit.skillmine import (
    MinerCache,
    Piece,
    ProposalsError,
    Signature,
    commit_subject,
    doc_freq,
    meets,
    mine,
    miner_pieces,
    proposals_bytes,
    read_proposals,
    repo_key,
    session_pieces,
    shiftwork_pieces,
    signature,
    similarity,
    write_proposals,
)


def _signatures(pieces: list[Piece]) -> list[dict]:
    df, n = doc_freq(pieces)
    return [signature(p, df, n).as_dict() for p in pieces]


def _sig(d: dict) -> Signature:
    return Signature(frozenset(d["keywords"]), frozenset(d["ngrams"]), frozenset(d["paths"]))


def _piece(d: dict) -> Piece:
    return Piece(
        id=d["id"],
        source=d["source"],
        ts=d["ts"],
        repo=d["repo"],
        prompt=d["prompt"],
        tools=tuple(d["tools"]),
        paths=frozenset(d["paths"]),
        ok=d["ok"],
        signals=d.get("signals", {}),
        failure=d.get("failure"),
    )


def main() -> None:
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    out: dict = {"pieces": [], "root_signatures": [], "set_signatures": [], "similarity": []}
    for root in payload.get("roots", []):
        pieces = shiftwork_pieces(root)
        out["pieces"].append([p.as_dict() for p in pieces])
        out["root_signatures"].append(_signatures(pieces))
    out["repo_keys"] = [repo_key(p) for p in payload.get("repo_keys", [])]
    for pset in payload.get("piece_sets", []):
        pieces = [
            Piece(
                id=f"set/{i}",
                source="session",
                ts="",
                repo="",
                prompt=d["prompt"],
                tools=tuple(d["tools"]),
                paths=frozenset(d["paths"]),
            )
            for i, d in enumerate(pset)
        ]
        out["set_signatures"].append(_signatures(pieces))
    for a, b in payload.get("pairs", []):
        sim = similarity(_sig(a), _sig(b))
        out["similarity"].append([sim[0], sim[1], meets(sim)])
    out["mines"], out["mine_bytes"] = [], []
    for m in payload.get("mines", []):
        doc = mine([_piece(d) for d in m["pieces"]], m["previous"], m["now"], m["ms"])
        out["mines"].append(doc)
        out["mine_bytes"].append(proposals_bytes(doc).hex())
    out["root_mines"] = []
    for m in payload.get("root_mines", []):
        pieces = [p for r in m["roots"] for p in shiftwork_pieces(r)]
        out["root_mines"].append(mine(pieces, m["previous"], m["now"]))
    if "write" in payload:
        w = payload["write"]
        doc = out["mines"][w["doc_of"]]
        path = write_proposals(w["home"], doc)
        out["write"] = {
            "path": str(path),
            "hex": path.read_bytes().hex(),
            "read_back": read_proposals(w["home"]),
        }
    out["reads"] = []
    for r in payload.get("reads", []):
        try:
            got = read_proposals(r["home"])
            out["reads"].append(["none"] if got is None else ["ok", got])
        except ProposalsError as e:
            out["reads"].append(["error", str(e)])
    out["commit_subjects"] = [commit_subject(c) for c in payload.get("commit_subjects", [])]
    from bantamkit.storage.retention import parse_now

    out["session_runs"] = []
    for r in payload.get("session_runs", []):
        cache = MinerCache(r["cache"]).load()
        got = session_pieces(r["home"], select_adapter(r["home"]), parse_now(r["now"]), cache)
        hexed = cache.save().read_bytes().hex() if r["save"] else None
        out["session_runs"].append(
            {"pieces": [p.as_dict() for p in got], "bytes_read": cache.bytes_read, "cache_hex": hexed}
        )
    out["miner_runs"] = []
    for r in payload.get("miner_runs", []):
        cache = MinerCache(r["cache"]).load()
        now_ms = parse_now(r["now"])
        got = miner_pieces(r["home"], r["root"], select_adapter(r["home"]), now_ms, cache)
        doc = mine(got, None, r["now"])
        out["miner_runs"].append(
            {"doc": doc, "hex": proposals_bytes(doc).hex(), "pieces": [p.as_dict() for p in got]}
        )
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
