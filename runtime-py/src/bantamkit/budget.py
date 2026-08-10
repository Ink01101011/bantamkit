"""Layer 1 — a global spend governor for one agent run: `TokenBudget`."""

from __future__ import annotations

from bantamkit.client import Usage
from bantamkit.profile import default as profile_default
from bantamkit.profile import default_float as profile_default_float

__all__ = ["TokenBudget"]


class _BudgetedClient:
    """The recording point: every chat through the agent's client books its usage.

    A proxy rather than a subclass, because the thing being wrapped is whatever
    the caller handed the agent (a raw adapter, the eval harness's tracking
    client, a fake). `__getattr__` passes everything else through, so the
    duck-typed contracts callers test for — `seed`, `model`,
    `_response_format_unsupported` — read the inner client unchanged.
    """

    def __init__(self, inner, budget: TokenBudget):
        self.inner = inner
        self.budget = budget

    def chat(self, *args, **kwargs):
        resp = self.inner.chat(*args, **kwargs)
        self.budget.record(resp.usage)
        return resp

    def __getattr__(self, name: str):
        return getattr(self.inner, name)


class TokenBudget:
    """A governor, not an odometer: it decides what a run may still spend.

    Every gate already caps its own retries; composition multiplies those caps
    and nothing bounded the total (3b `full`: 214,698 tokens for 15/66). This
    component bounds the run and degrades it in two steps instead of one:

    - past ``ceiling * optional_cutoff`` spent, ``allow("optional")`` is denied,
      so optional work is skipped and a `full` run degrades toward `lean`/`bare`;
    - past ``ceiling``, everything is denied and `Agent.run` stops at the top of
      the next turn, returning the last assistant content as a best-effort result.

    The gap between the cutoff and the ceiling **is** the reserve: the final
    answer emission always fits.

    Priority classification (v1, deliberately coarse — no cost estimation, which
    would be guesswork until a measured need exists):

    - ``"optional"`` — critique rounds, blind and grounded. Denied means "accept
      the answer", never an exception.
    - ``"required"`` — the agent's own turns and the schema / json-answer retries.
      Cheap, high-value, and denied only past the hard ceiling.

    Spend is booked at the client boundary: `setup` wraps `agent.client` in a
    `_BudgetedClient`, so every call made through the agent's client moves
    `spent` — the agent's own turns *and* the critic calls the gates issue
    through `structured()` on that same client. That is the point: the critique
    rounds are the dominant optional spend the cutoff exists to govern, and
    while `Agent.run` was the only recording point they were invisible to the
    governor.

    `structured()` is still not budgeted as a *loop*: it never asks `allow()`
    between its own retries, which stay bounded by `max_retries`. What changed
    is visibility, not control.

    Attach with `Agent.use(...)`; `setup` resets per-run state, so one instance
    may not measure two runs at once but can be reused across sequential ones.
    """

    def __init__(self, ceiling: int | None = None, optional_cutoff: float | None = None):
        self.ceiling = (
            ceiling if ceiling is not None else profile_default("token_budget", "ceiling")
        )
        self.optional_cutoff = (
            optional_cutoff
            if optional_cutoff is not None
            else profile_default_float("token_budget", "optional_cutoff")
        )
        self.spent = 0
        self.exhausted = False

    def setup(self, agent) -> None:
        self.spent = 0
        self.exhausted = False
        # Unwrap first: setting up twice on the same agent (or reusing an agent
        # across budgets) must leave exactly one wrapper, or every call would be
        # booked once per layer.
        inner = agent.client
        if isinstance(inner, _BudgetedClient):
            inner = inner.inner
        agent.client = _BudgetedClient(inner, self)
        agent.budget = self

    def record(self, usage: Usage) -> None:
        """Book one chat response against the budget. Called by `_BudgetedClient`."""
        self.spent += usage.total

    def allow(self, priority: str) -> bool:
        """Ask before spending. `priority` is ``"required"`` or ``"optional"``."""
        if priority not in ("required", "optional"):
            raise ValueError(f"unknown budget priority {priority!r}")
        if self.spent >= self.ceiling:
            # Latched for the run: the hard ceiling denied work, which is what
            # `budget-exhausted` reports. Cutoff-band denials are degradation,
            # not exhaustion, and deliberately do not set this.
            self.exhausted = True
            return False
        if priority == "optional":
            return self.spent < self.ceiling * self.optional_cutoff
        return True
