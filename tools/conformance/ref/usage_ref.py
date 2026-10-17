"""Reference side of the `recall-usage` conformance suite — the usage ledger (#199, D5).

Imports `bantamkit.memory.usage` rather than copying it, for the reason `recall_gate_ref.py`
gives: a hand copy would be a third implementation that agrees by construction.

The suite sends each bed's event script; this file runs it against `UsageLedger` and
answers one result per op. The Node half of the suite runs the SAME script against the
port's `UsageLedger` with an interpreter written to the same table:

    {"op": "append", "fact", "kind", "ts", "keywords"?}  -> bool
    {"op": "raw", "b64"}                                 -> null   (bytes appended verbatim)
    {"op": "weights", "now"}                             -> [[fact, "%.9f"], ...] in map order
    {"op": "last_used", "fact"}                          -> str | null
    {"op": "keywords_copy", "fact"}                      -> [str] | null
    {"op": "skipped"}                                    -> int    (after the previous read)
    {"op": "fold", "now"}                                -> null
    {"op": "bytes"}                                      -> b64 | null (the ledger file)
    {"op": "gz", "n"}                                    -> b64 | null (segment n, DECOMPRESSED)
    {"op": "listdir"}                                    -> sorted names in the usage dir
    {"op": "path"}                                       -> the ledger path relative to home

    {"beds": [{"home", "store", "fold_lines": int|null, "rotate_bytes": int|null, "ops": [...]}, ...],
     "store_ids": [path, ...]}
      -> {"beds": [[result, ...], ...], "store_ids": [str, ...]}

Weights travel as nine-decimal TEXT: a float through two serialisers is a comparison of the
serialisers (`1.0` against `1`), and nine places is what the fold itself writes.
`HOME` is the bed's own, set by the harness; the ledger takes `home` explicitly anyway, and
no real `~/.bantamkit` is ever opened.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit.memory.usage import UsageLedger, store_id


def run_bed(bed: dict) -> list:
    home = Path(bed["home"])
    led = UsageLedger(
        home,
        Path(bed["store"]),
        fold_lines=bed.get("fold_lines"),
        rotate_bytes=bed.get("rotate_bytes"),
    )
    out: list = []
    for op in bed["ops"]:
        kind = op["op"]
        if kind == "append":
            out.append(led.append(op["fact"], op["kind"], op["ts"], op.get("keywords")))
        elif kind == "raw":
            led.path.parent.mkdir(parents=True, exist_ok=True)
            with led.path.open("ab") as f:
                f.write(base64.b64decode(op["b64"]))
            out.append(None)
        elif kind == "weights":
            out.append([[k, f"{v:.9f}"] for k, v in led.weights(op["now"]).items()])
        elif kind == "last_used":
            out.append(led.last_used(op["fact"]))
        elif kind == "keywords_copy":
            out.append(led.keywords_copy(op["fact"]))
        elif kind == "skipped":
            out.append(led.skipped)
        elif kind == "fold":
            led.fold(op["now"])
            out.append(None)
        elif kind == "bytes":
            try:
                out.append(base64.b64encode(led.path.read_bytes()).decode("ascii"))
            except OSError:
                out.append(None)
        elif kind == "gz":
            try:
                raw = Path(f"{led.path}.{op['n']}.gz").read_bytes()
                out.append(base64.b64encode(gzip.decompress(raw)).decode("ascii"))
            except OSError:
                out.append(None)
        elif kind == "listdir":
            try:
                out.append(sorted(os.listdir(led.path.parent)))
            except OSError:
                out.append(None)
        elif kind == "path":
            out.append(led.path.relative_to(home).as_posix())
        else:
            raise SystemExit(f"usage_ref: unknown op {kind!r}")
    return out


def main() -> None:
    req = json.loads(sys.stdin.read())
    json.dump(
        {
            "beds": [run_bed(b) for b in req.get("beds", [])],
            "store_ids": [store_id(Path(p)) for p in req.get("store_ids", [])],
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
