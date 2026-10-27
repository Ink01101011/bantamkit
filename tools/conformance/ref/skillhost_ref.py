"""Reference side of `tools/conformance/suites/skill-host.mjs` (#205 Task 2): the product's own
`bantamkit.skillhost`, one answer per op, each the product's serialisation in base64.

    {"op": "usage", "projects", "now", "known": [..] | null}  -> b64(dumps(UsageScan.summary()))
    {"op": "gather", "home", "cwd": str | null, "now"}         -> b64(dumps(Gathered.as_dict()))

`dumps` is `storage.hotindex.dumps`, which `hotindex.ts` `dumpIndex` mirrors byte for byte.
"""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import skillhost
from bantamkit.storage.hotindex import dumps
from bantamkit.storage.retention import parse_now


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _one(op: dict) -> str:
    now = parse_now(op["now"])
    if op["op"] == "usage":
        known = None if op.get("known") is None else frozenset(op["known"])
        return _b64(
            dumps(skillhost.count_skill_usage(Path(op["projects"]), now, known=known).summary())
        )
    if op["op"] == "gather":
        adapter = skillhost.select_adapter(op["home"])
        return _b64(dumps(adapter.gather(op["home"], op["cwd"], now).as_dict()))
    raise ValueError(f"unknown op {op['op']!r}")


def main() -> None:
    req = json.loads(sys.stdin.read())
    json.dump({"answers": [_one(op) for op in req["ops"]]}, sys.stdout)


if __name__ == "__main__":
    main()
