"""The CLI in a REAL process, with a critic whose score actually MOVES.

RB-P16's field measurement needs a run that produces a non-degenerate band. The
existing `cli_exit_status_probe.py` always scores 9, so every point of every variant
passes, every comparison is `indistinguishable` at `F/F` vs `F/F`, and a report about
effect size would have nothing to report. That probe is right for what it pins (the
guard's status contract is not about the score) and useless here.

The ONLY thing patched is the client constructor, exactly as in that probe:
`criticreplay.OpenAICompatible` becomes a critic whose integer score is
`sha256(prompt|seed) % 11`. Argument parsing, the run loop, the guard, `summarize`,
`format_table`, the artifacts and the status decision are all the shipped `main()` on
the shipped path.

WHY A HASH AND NOT A HAND-WRITTEN SCORER. A scorer written to produce a wide gap and a
narrow one would be a rig built to agree with the claim. This one is a fixed function
of the prompt bytes and the seed, chosen before the gaps it produces were looked at, so
the band the field record reports is whatever this rubric pair and these cells give.

Not collected by pytest (the filename is deliberately not `test_*`); it is run through
`/bin/sh` by `docs/eval-data/2026-08-14-rbp16-effect-size-report.sh`, which reads `$?`.

    python rbp16_effect_probe.py --rubric A=<path> --rubric B=<path> \\
        --transcripts <dir> --base-url http://x --model fake-14b [...]
"""

from __future__ import annotations

import hashlib
import json
import sys

from bantamkit import criticreplay
from bantamkit.client import Message, Response, Usage


class _HashedCritic:
    def __init__(self, model: str = "fake-14b"):
        self.model = model
        self.seed = None
        self._response_format_unsupported = False

    def chat(self, messages, tools=None, response_format=None):
        prompt = next(m.content for m in messages if m.role == "user")
        digest = hashlib.sha256(f"{prompt}|{self.seed}".encode()).hexdigest()
        score = int(digest[:8], 16) % 11
        return Response(
            message=Message(
                role="assistant",
                content=json.dumps({"reasoning": "r", "score": score, "feedback": digest[:6]}),
            ),
            usage=Usage(100 + score, 20 + score),
        )


if __name__ == "__main__":
    criticreplay.OpenAICompatible = lambda **kw: _HashedCritic(kw.get("model", "fake-14b"))
    criticreplay.main(sys.argv[1:])
