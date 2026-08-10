"""Layer 1 — consecutive identical-observation detection on tool calls: `LoopGuard`."""

from __future__ import annotations

import hashlib

from bantamkit.agent import Agent, ToolDef
from bantamkit.contract import loop_note, loop_warn
from bantamkit.profile import default as profile_default

__all__ = ["LoopGuard"]


class LoopGuard:
    """Detects no-info tool loops and talks the model out of them — injection only.

    Models loop by re-calling tools, never by re-stating prose: the probe's six
    looping runs each burned a 6-16 call tail of byte-identical observations,
    while max streak in every passing run was 2. Identity is keyed on
    observation bytes, NOT call arguments — the 7b flavor paraphrases its
    arguments while the observation repeats, so args-identity is blind to it.

    Per tool name, consecutive identical observations are counted as a streak;
    any different observation resets the streak to 1 (streaks, not totals — a
    legitimately repeated read later in a long run must not trip it). At
    ``inject_at`` the `loop_note` wording is appended to the observation; at
    ``warn_at`` and beyond, `loop_warn` replaces it. Below the threshold the
    observation passes through byte-unchanged.

    A component cannot and must not stop the agent loop — never swallow a
    scorable answer — so this only ever appends words the model reads.

    Attach with `Agent.use(...)`; `setup` rewraps and resets streaks, so one
    instance is reusable across sequential runs. v1 limitation, documented:
    tools registered after `setup` are not wrapped — attach LoopGuard last.
    """

    def __init__(self, inject_at: int | None = None, warn_at: int | None = None):
        self.inject_at = (
            inject_at if inject_at is not None else profile_default("loop_guard", "inject_at")
        )
        self.warn_at = warn_at if warn_at is not None else profile_default("loop_guard", "warn_at")
        self.streaks: dict[str, tuple[str, int]] = {}

    def setup(self, agent: Agent) -> None:
        self.streaks = {}
        agent.tools[:] = [self._wrap(td) for td in agent.tools]

    def _wrap(self, tooldef: ToolDef) -> ToolDef:
        inner, tool_name = tooldef.handler, tooldef.tool.name

        def handler(**kwargs):
            return self._observe(tool_name, str(inner(**kwargs)))

        return ToolDef(tool=tooldef.tool, handler=handler)

    def _observe(self, tool: str, observation: str) -> str:
        digest = hashlib.sha256(observation.encode()).hexdigest()
        prior_digest, count = self.streaks.get(tool, ("", 0))
        count = count + 1 if digest == prior_digest else 1
        self.streaks[tool] = (digest, count)
        if count >= self.warn_at:
            return f"{observation}\n{loop_warn()}"
        if count >= self.inject_at:
            return f"{observation}\n{loop_note(count)}"
        return observation
