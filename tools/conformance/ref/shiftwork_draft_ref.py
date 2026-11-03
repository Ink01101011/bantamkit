"""Reference side of the `shiftwork-draft` conformance suite (#226).

Same stance as the other refs: this IMPORTS `bantamkit.shiftwork` and lets the real code
answer. One request runs a list of steps in order over one bed directory, which the suite
rebuilds at the same path before each side, so every path in every sentence is the same
string on both sides.

    {"bed": str, "steps": [step, ...]} -> {"results": [b64_text, ...]}

    {"do": "draft", "args": {...}}          json.dumps(shiftwork.draft(**args))
    {"do": "list"}                          json.dumps([[relpath, b64(bytes)], ...]) under bed,
                                            sorted, `*.log.jsonl` and `*.lock` left out
    {"do": "plan", "checkpoint": str}       json.dumps(shiftwork.plan_batches(checkpoint))
    {"do": "clock_in", "checkpoint": str}   json.dumps(shiftwork.clock_in(checkpoint))

`args` travels as ordinary JSON and is handed over exactly as `json.loads` produced it,
which is what the MCP server does with the arguments off the wire.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import shiftwork


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _listing(bed: Path) -> list[list[str]]:
    out = []
    for path in sorted(bed.rglob("*")):
        if not path.is_file() or path.name.endswith((".log.jsonl", ".lock")):
            continue
        out.append([path.relative_to(bed).as_posix(), _b64(path.read_bytes())])
    return out


def _step(bed: Path, step: dict) -> object:
    if step["do"] == "draft":
        return shiftwork.draft(**step["args"])
    if step["do"] == "list":
        return _listing(bed)
    if step["do"] == "plan":
        return shiftwork.plan_batches(step["checkpoint"])
    if step["do"] == "clock_in":
        return shiftwork.clock_in(step["checkpoint"])
    raise ValueError(f"unknown step {step['do']!r}")


def main() -> None:
    # stdin is a byte protocol: decode it as utf-8, not through the ANSI code page.
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    bed = Path(request["bed"])
    results = [
        _b64(json.dumps(_step(bed, step)).encode("utf-8")) for step in request["steps"]
    ]
    json.dump({"results": results}, sys.stdout)


if __name__ == "__main__":
    main()
