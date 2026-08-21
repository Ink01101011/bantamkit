"""RB-P18's one request, issued in a REAL process so no `pytest` is in `sys.modules`.

RB-P28's residual, closed for this acceptance. `test_a_fresh_run_reproduces_both_frozen
_payload_recipes_from_one_request` runs the shipped `replay_verdicts` IN-PROCESS under
pytest, so a patch reading `"pytest" in sys.modules` reaches it and every other node in
the file at once — measured (L5, reproduced by the orchestrator): a fix-nothing patch
keeps the whole suite green while the field reverts. A probe cannot be reached that way:
it is a separate interpreter started by `/bin/sh` with no `PYTEST_*` key in its
environment and no pytest anywhere on its import path.

The ONLY thing patched is the client, exactly as in `cli_exit_status_probe.py` and
`rbp16_effect_probe.py`: a scripted critic that always scores 5, so no request leaves the
machine. Request CONSTRUCTION — which is the whole of RB-P18 — is the shipped
`replay_verdicts` on the shipped `structured()` path, and both payload columns are read
off the `Verdict` the shipped code produced.

Prints one JSON object on stdout and nothing else, so a caller reads a value rather than
scraping a log:

    {"prompt_sha256": ..., "payload_sha256": ..., "payload_canonical_sha256": ...}

Not collected by pytest (the filename is deliberately not `test_*`).

    python rbp18_payload_probe.py <repo> <sa3-replay.json> <git-ref> <repeat> <seed>
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bantamkit import criticreplay
from bantamkit.client import Message, Response, Usage


class _ScriptedCritic:
    """Always scores 5 — the score is not what RB-P18 is about; the request is."""

    def __init__(self, model: str):
        self.model = model
        self.seed = None
        self._response_format_unsupported = False

    def chat(self, messages, tools=None, response_format=None):
        return Response(
            message=Message(
                role="assistant",
                content=json.dumps({"reasoning": "r", "score": 5, "feedback": "f"}),
            ),
            usage=Usage(100, 20),
        )


if __name__ == "__main__":
    repo, sa3_path, ref, repeat, seed = sys.argv[1:6]
    sa3 = json.loads(Path(sa3_path).read_text(encoding="utf-8"))
    raw = subprocess.run(
        ["git", "-C", repo, "show", f"{ref}:assets/rubrics/task-completion.yaml"],
        capture_output=True,
        text=True,
        check=True, encoding="utf-8",
    ).stdout
    rubric = criticreplay._parse_rubric(raw, f"git:{ref}")
    case = criticreplay.Case(
        task=sa3["task"],
        repeat=int(repeat),
        seed=int(seed),
        prompt=sa3["task_prompt"],
        output=sa3["answer_replayed"],
    )
    (verdict,) = criticreplay.replay_verdicts(
        _ScriptedCritic(sa3["model"]), rubric, case
    )
    print(
        json.dumps(
            {
                "prompt_sha256": verdict.prompt_sha256,
                "payload_sha256": verdict.payload_sha256,
                "payload_canonical_sha256": verdict.payload_canonical_sha256,
            }
        )
    )
