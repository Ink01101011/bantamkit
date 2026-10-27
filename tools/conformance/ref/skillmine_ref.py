"""Reference side of the `skill-miner` conformance suite (#206 Task 4a).

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

`root_signatures` takes one root's shiftwork pieces as one source: its document frequencies
are counted over exactly those pieces. Every fixture is synthetic and every root is a
scratch directory the harness made; the miner only reads.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit.skillmine import (
    Piece,
    Signature,
    doc_freq,
    meets,
    repo_key,
    shiftwork_pieces,
    signature,
    similarity,
)


def _signatures(pieces: list[Piece]) -> list[dict]:
    df, n = doc_freq(pieces)
    return [signature(p, df, n).as_dict() for p in pieces]


def _sig(d: dict) -> Signature:
    return Signature(frozenset(d["keywords"]), frozenset(d["ngrams"]), frozenset(d["paths"]))


def main() -> None:
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    out: dict = {"pieces": [], "root_signatures": [], "set_signatures": [], "similarity": []}
    for root in payload["roots"]:
        pieces = shiftwork_pieces(root)
        out["pieces"].append([p.as_dict() for p in pieces])
        out["root_signatures"].append(_signatures(pieces))
    out["repo_keys"] = [repo_key(p) for p in payload["repo_keys"]]
    for pset in payload["piece_sets"]:
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
    for a, b in payload["pairs"]:
        sim = similarity(_sig(a), _sig(b))
        out["similarity"].append([sim[0], sim[1], meets(sim)])
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
