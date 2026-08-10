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
    ``inject_at`` the `loop_note` wording is prepended to the observation; at
    ``warn_at`` and beyond, `loop_warn` replaces it. Prepended, not appended:
    the agent truncates observations head-first, so an appended note would be
    eaten exactly on the oversized no-info tails it targets — prepending
    survives truncation, same as FileAccessGraph's markers. Identity stays
    keyed on the raw inner observation, never on the injected wording. Below
    the threshold the observation passes through byte-unchanged.

    A component cannot and must not stop the agent loop — never swallow a
    scorable answer — so this only ever injects words the model reads.

    Attach with `Agent.use(...)`; `setup` rewraps and resets streaks, so one
    instance is reusable across sequential runs, and setting up twice on the
    same agent unwraps first (the TokenBudget precedent) so observations are
    never counted once per layer. v1 limitations, documented: tools registered
    after `setup` are not wrapped — attach LoopGuard last. And the guard
    counts only observations produced by tool returns: repeated raising
    errors and unknown-tool observations cannot streak, because the agent
    formats those error observations after the wrapper's frame unwinds — the
    wrapper resets that tool's streak on a raise and re-raises unchanged, so
    an error between identical results can never count as a repeat the model
    never saw.
    """

    def __init__(self, inject_at: int | None = None, warn_at: int | None = None):
        self.inject_at = (
            inject_at if inject_at is not None else profile_default("loop_guard", "inject_at")
        )
        self.warn_at = warn_at if warn_at is not None else profile_default("loop_guard", "warn_at")
        if self.inject_at < 1:
            raise ValueError(f"inject_at must be >= 1, got {self.inject_at!r}")
        if self.inject_at > self.warn_at:
            raise ValueError(
                f"inject_at must be <= warn_at, got inject_at={self.inject_at!r} "
                f"warn_at={self.warn_at!r}"
            )
        self.streaks: dict[str, tuple[str, int]] = {}

    def setup(self, agent: Agent) -> None:
        self.streaks = {}
        agent.tools[:] = [self._wrap(self._unwrap(td)) for td in agent.tools]

    @staticmethod
    def _unwrap(tooldef: ToolDef) -> ToolDef:
        """Peel any prior LoopGuard wrapper so re-setup leaves exactly one layer."""
        return getattr(tooldef.handler, "_loopguard_inner", tooldef)

    def _wrap(self, tooldef: ToolDef) -> ToolDef:
        inner, tool_name = tooldef.handler, tooldef.tool.name

        def handler(**kwargs):
            try:
                result = inner(**kwargs)
            except Exception:
                # The agent formats this into an error observation after our frame
                # unwinds, so we never see those bytes: reset rather than count,
                # or an error between identical results would extend a streak the
                # model never saw two of in a row. Re-raise unchanged — the
                # agent's error-formatting contract stays byte-identical.
                self.streaks.pop(tool_name, None)
                raise
            return self._observe(tool_name, str(result))

        handler._loopguard_inner = tooldef
        return ToolDef(tool=tooldef.tool, handler=handler)

    def _observe(self, tool: str, observation: str) -> str:
        digest = hashlib.sha256(observation.encode()).hexdigest()
        prior_digest, count = self.streaks.get(tool, ("", 0))
        count = count + 1 if digest == prior_digest else 1
        self.streaks[tool] = (digest, count)
        if count >= self.warn_at:
            return f"{loop_warn()}\n{observation}"
        if count >= self.inject_at:
            return f"{loop_note(count)}\n{observation}"
        return observation
