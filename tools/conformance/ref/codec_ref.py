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

    {"op": "windows_write", "facts": [...]}      # the SAME facts, written the way `newline=
      -> {"written_b64": [...]}                  # None` writes them where os.linesep is CRLF
"""

from __future__ import annotations

import base64
import datetime
import json
import sys
import tempfile
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
    # STDIN IS A BYTE PROTOCOL, SO DECODE IT AS ONE.
    #
    # `json.load(sys.stdin)` decodes through the text wrapper, whose encoding is
    # `locale.getpreferredencoding(False)` -- utf-8 on Linux and macOS, and the ANSI
    # CODE PAGE on Windows. MEASURED on windows-latest, run 32643739343: 26 of the codec
    # suite's 206 cases differed, every one of them mojibake, `an em dash \u00e2\u20ac\u201d`
    # for `an em dash \u2014` and whole Thai descriptions turned into Latin-1 rubble with
    # lone surrogates in them. Nothing was wrong with either runtime; the HARNESS's own
    # transport had re-decoded the question before either side saw it.
    #
    # This is not the masking that `ci.yml` refuses. `PYTHONUTF8` and `-X utf8` are barred
    # there because they change how the CODE UNDER TEST opens files, hiding the very
    # encoding defects the gate exists to find. This line changes nothing about the code
    # under test: it names the encoding of a pipe this harness owns at both ends, and the
    # Node side has always written utf-8 into it.
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
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
    elif op == "windows_write":
        # THE CRLF RULING'S REFERENCE SIDE, produced by CPython rather than simulated in JS.
        #
        # `Path.write_text(..., encoding="utf-8")` passes `newline=None`, which translates
        # every "\n" to `os.linesep` on the way out — CRLF on Windows, a no-op here. CPython
        # gates that on `#ifdef MS_WINDOWS`, so this platform cannot construct it directly;
        # `newline="\r\n"` asks the SAME TextIOWrapper for the SAME translation with the
        # target explicitly named, which is as close as a macOS runner gets to the Windows
        # write without pretending. It matters that this goes through the io stack and not
        # through `str.replace`: if CPython's translation ever changed, this moves and the
        # ruling that depends on it is re-read instead of trusted.
        written = []
        with tempfile.TemporaryDirectory() as tmp:
            for i, fact in enumerate(request["facts"]):
                path = Path(tmp) / f"{i}.md"
                with path.open("w", encoding="utf-8", newline="\r\n") as handle:
                    handle.write(write_fact(fact))
                written.append(base64.b64encode(path.read_bytes()).decode("ascii"))
        json.dump({"written_b64": written}, sys.stdout)
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
