"""Reference side of the `skill-draft` conformance suite (#206 Task 6).

Imports `bantamkit.skilldraft` rather than copying it. The Node half runs the same ops
against `runtime-ts/dist/skilldraft.js`. Every drafter is a stub: sampling is a function
here, the endpoint is the suite's stub server in its own process. Every fixture is synthetic.

Protocol: one JSON request on stdin, one JSON response on stdout.

    {"bundles": [record, ...],
     "unfence": [str, ...],
     "gates": [{"text", "record", "home", "cwd"}, ...],
     "env": [{"url": str | null, "model": str | null, "sampling": bool}, ...],
     "drafts": [{"record", "home", "cwd", "now",
                 "chain": [{"kind": "sampling", "answer": str | null, "fail": bool,
                            "absent": bool}
                           | {"kind": "endpoint", "url": str}
                           | {"kind": "host"}]}, ...]}
      -> {"bundles": [{"json", "system", "user", "sha"}, ...],
          "unfence": [str, ...],
          "gates": [{"ok", "reasons", "name"}, ...],
          "env": [{"active", "chain"}, ...],
          "drafts": [{"outcome", "sampling", "log"}, ...]}

`log` is the drafts log's bytes as base64 (absent: null).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime-py" / "src"))

from bantamkit import skilldraft as sd


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def run_bundle(record: dict) -> dict:
    b = sd.bundle(record)
    system, user = sd.prompt(b)
    return {
        "json": sd.bundle_json(b),
        "system": system,
        "user": user,
        "sha": sd.prompt_sha256(b),
    }


def run_gate(case: dict) -> dict:
    g = sd.gate(case["text"], sd.bundle(case["record"]), case["home"], case["cwd"])
    return {"ok": g.ok, "reasons": g.reasons, "name": None if g.doc is None else g.doc.name}


def run_env(case: dict) -> dict:
    saved = {k: os.environ.get(k) for k in (sd.LLM_URL_ENV, sd.LLM_MODEL_ENV)}
    try:
        for key, value in ((sd.LLM_URL_ENV, case["url"]), (sd.LLM_MODEL_ENV, case["model"])):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        send = (lambda s, u: "x") if case["sampling"] else None
        return {
            "active": sd.active_drafter(case["sampling"]),
            "chain": [d.label for d in sd.default_chain(send)],
        }
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_draft(case: dict) -> dict:
    calls: list[str] = []
    chain = []
    for link in case["chain"]:
        if link["kind"] == "sampling":
            if link.get("absent"):
                chain.append(sd.SamplingDrafter(None))
                continue

            def send(system: str, user: str, link: dict = link) -> str:
                calls.append(hashlib.sha256(f"{system}\0{user}".encode()).hexdigest())
                if link.get("fail"):
                    raise RuntimeError("sampling refused")
                return link.get("answer")  # type: ignore[return-value]

            chain.append(sd.SamplingDrafter(send))
        elif link["kind"] == "endpoint":
            chain.append(sd.EndpointDrafter(link["url"], "m1", max_retries=1))
        else:
            chain.append(sd.HostAgentDrafter())
    out = sd.draft(case["record"], chain, case["home"], case["cwd"], case["now"])
    handoff = None
    if out.handoff is not None:
        handoff = {
            "bundle": sd.bundle_json(out.handoff["bundle"]),
            "instructions": out.handoff["instructions"],
            "target": out.handoff["target"],
        }
    log = sd.drafts_log(case["home"])
    return {
        "outcome": {
            "drafter": out.drafter,
            "ok": out.ok,
            "text": out.text,
            "reasons": out.reasons,
            "unreachable": out.unreachable,
            "handoff": handoff,
        },
        "sampling": calls,
        "log": b64(log.read_bytes()) if log.exists() else None,
    }


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    json.dump(
        {
            "bundles": [run_bundle(r) for r in request.get("bundles", [])],
            "unfence": [sd.unfence(t) for t in request.get("unfence", [])],
            "gates": [run_gate(c) for c in request.get("gates", [])],
            "env": [run_env(c) for c in request.get("env", [])],
            "drafts": [run_draft(c) for c in request.get("drafts", [])],
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
