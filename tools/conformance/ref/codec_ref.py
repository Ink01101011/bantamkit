"""Reference side of the fact-file codec conformance suite.

Runs under the repo venv and answers with what `runtime-py` would actually do. It imports
NOTHING from `bantamkit` on purpose: the expression below is copied from `_write_fact` and
`_facts`, so if someone edits the store, this file stops agreeing with it and the suite goes
red — which is the alarm you want. Importing the store instead would make the harness track
the store silently and prove only that the port matches whatever the store has become.

Protocol: a JSON request on stdin, a JSON response on stdout. Payload strings that must
survive byte-exactly travel as base64, because the point of the exercise is bytes.

    {"op": "emit",  "facts": [{name, description, type, body, links, last_recalled, created}]}
      -> {"emitted_b64": [...]}                  # exactly what `_write_fact` would write

    {"op": "parse", "texts_b64": [...]}
      -> {"parsed": [{"meta": ..., "body": ...} | {"error": "..."}]}

    {"op": "read_file", "paths": [...]}          # goes through Path.read_text, so the
      -> {"parsed": [...]}                       # universal-newline translation is real

    {"op": "today", "ts": [unix seconds]}        # date.today() is LOCAL; run me with $TZ
      -> {"dates": ["YYYY-MM-DD", ...]}
"""

from __future__ import annotations

import base64
import datetime
import json
import sys
from pathlib import Path

import yaml


def write_fact(fact: dict) -> str:
    """`store.MemoryStore._write_fact`, verbatim from the expression it writes."""
    meta = {
        "name": fact["name"],
        "description": fact["description"],
        "type": fact["type"],
        "created": fact.get("created"),
        "last_recalled": fact.get("last_recalled"),
        "links": list(fact.get("links") or []),
    }
    return (
        "---\n"
        + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + fact["body"].strip()
        + "\n"
    )


def jsonable(value):
    """Make a `safe_load` result comparable with a JSON parse from Node.

    A `datetime.date` is exactly the thing the single-quoting of `created` exists to
    prevent, so it is rendered as a TAGGED marker rather than silently as its ISO string —
    a Node parse that returned the plain string must not look equal to it.
    """
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return f"<python {type(value).__name__} {value.isoformat()}>"
    if isinstance(value, bool):
        return f"<python bool {value}>"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"<python {type(value).__name__} {value}>"
    return value


def parse_text(text: str) -> dict:
    """The frontmatter half of `_facts`, on text that has already been read."""
    try:
        _, front, body = text.split("---\n", 2)
        meta = yaml.safe_load(front)
        if not isinstance(meta, dict):
            return {"error": "frontmatter is not a mapping"}
        return {"meta": jsonable(meta), "body": body.strip()}
    except (ValueError, KeyError, yaml.YAMLError) as e:
        return {"error": f"{type(e).__name__}: {e}"}


def main() -> None:
    request = json.load(sys.stdin)
    op = request["op"]
    if op == "emit":
        out = [
            base64.b64encode(write_fact(f).encode("utf-8")).decode("ascii")
            for f in request["facts"]
        ]
        json.dump({"emitted_b64": out}, sys.stdout)
    elif op == "parse":
        texts = [base64.b64decode(b).decode("utf-8") for b in request["texts_b64"]]
        json.dump({"parsed": [parse_text(t) for t in texts]}, sys.stdout)
    elif op == "read_file":
        # `Path.read_text` opens in TEXT mode, so this arm is where universal-newline
        # translation actually happens rather than being simulated.
        json.dump(
            {"parsed": [parse_text(Path(p).read_text(encoding="utf-8")) for p in request["paths"]]},
            sys.stdout,
        )
    elif op == "today":
        # `date.today()` is `date.fromtimestamp(time.time())` — LOCAL, honouring $TZ. The
        # caller pins TZ so the two runtimes are asked the same question.
        json.dump(
            # The suppression below is deliberate: DTZ012 wants a tz-aware call, and a
            # tz-aware call would answer a DIFFERENT question. `store._today` is
            # `date.today()`, naive-local, and this file reproduces it rather than
            # improving it.
            {
                "dates": [
                    datetime.date.fromtimestamp(ts).isoformat()  # noqa: DTZ012
                    for ts in request["ts"]
                ]
            },
            sys.stdout,
        )
    else:
        raise SystemExit(f"unknown op {op!r}")


if __name__ == "__main__":
    main()
