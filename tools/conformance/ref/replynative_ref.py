"""Reference side of the `reply-native` conformance suite (#292).

Imports `bantamkit.replynative` and lets the real code answer.

    {"calls": [call, ...], "assets": str | null} -> {"results": [json, ...]}

    {"fn": "mode", "env": {...}}                       mode(env).as_json()
    {"fn": "frame", "prompt": str}                     frame(prompt)
    {"fn": "classify", "prompt": str}                  classify(prompt)
    {"fn": "plan", "mode": {...}, "lang": str|null, "seen": [str]}   plan(...).as_json()

stdin is decoded as UTF-8 explicitly (#249: Windows reads a pipe in the console code page);
stdout is ASCII JSON.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import replynative as rn


def _call(c: dict):
    fn = c["fn"]
    if fn == "mode":
        return rn.mode(c["env"]).as_json()
    if fn == "frame":
        return rn.frame(c["prompt"])
    if fn == "classify":
        return rn.classify(c["prompt"])
    if fn == "plan":
        return rn.plan(rn.Mode.from_json(c["mode"]), c["lang"], c["seen"]).as_json()
    raise ValueError(f"unknown fn {fn}")


def main() -> None:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    if req.get("assets"):
        os.environ["BANTAMKIT_ASSETS"] = req["assets"]
    else:
        os.environ.pop("BANTAMKIT_ASSETS", None)
    sys.stdout.write(json.dumps({"results": [_call(c) for c in req["calls"]]}))


if __name__ == "__main__":
    main()
