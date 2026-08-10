"""Score-and-retry gate: rubric is data, scoring is schema-enforced, rounds are bounded."""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from bantamkit.agent import Agent
from bantamkit.assets import AssetNotFound, assets_root
from bantamkit.client import BantamError, Message, ModelClient
from bantamkit.contract import critique_feedback as _critique_feedback
from bantamkit.contract import render_evidence
from bantamkit.profile import default as profile_default
from bantamkit.structured import structured

__all__ = [
    "CritiqueExhausted",
    "CritiqueGate",
    "GroundedCritiqueGate",
    "Rubric",
    "load_rubric",
    "render_evidence",
]


class CritiqueExhausted(BantamError):
    """Output stayed below threshold for max_rounds critiques."""


def _validate_rubric(rubric: Rubric) -> None:
    """Validate that rubric prompt contains required placeholders.

    Raises BantamError if {task} or {output} are missing.
    """
    missing = []
    if "{task}" not in rubric.prompt:
        missing.append("task")
    if "{output}" not in rubric.prompt:
        missing.append("output")
    if missing:
        raise BantamError(
            f"rubric '{rubric.name}' prompt missing placeholder(s): "
            f"{', '.join('{' + p + '}' for p in missing)}"
        )


def _validate_grounded_rubric(rubric: Rubric) -> None:
    _validate_rubric(rubric)
    if "{evidence}" not in rubric.prompt:
        raise BantamError(f"rubric '{rubric.name}' prompt missing placeholder(s): {{evidence}}")


@dataclass
class Rubric:
    name: str
    threshold: int
    prompt: str  # must contain {task} and {output}
    schema: dict


def load_rubric(name: str) -> Rubric:
    path = assets_root() / "rubrics" / f"{name}.yaml"
    if not path.exists():
        raise AssetNotFound(f"rubric asset not found: {path}")
    data = yaml.safe_load(path.read_text())
    rubric = Rubric(
        name=data["name"],
        threshold=int(data["threshold"]),
        prompt=data["prompt"],
        schema=data["schema"],
    )
    _validate_rubric(rubric)
    return rubric


class CritiqueGate:
    def __init__(
        self, rubric: str | Rubric, client: ModelClient | None = None, max_rounds: int | None = None
    ):
        if isinstance(rubric, Rubric):
            _validate_rubric(rubric)
            self.rubric = rubric
        else:
            self.rubric = load_rubric(rubric)
        self.client = client
        self.max_rounds = (
            max_rounds if max_rounds is not None else profile_default("critique", "max_rounds")
        )
        self._rounds = 0
        self.rounds_used = 0
        self.budget = None

    def setup(self, agent: Agent) -> None:
        if self.client is None:
            self.client = agent.client
        self.rounds_used = 0
        # Duck-typed and optional: a run with no governor keeps every round it had.
        # Attach the budget before this gate, or the handle is None for the whole
        # run — and the client captured above is the unwrapped one, so critic
        # spend never reaches the governor either. Budget first, always.
        self.budget = getattr(agent, "budget", None)
        agent.add_post_hook(self)

    def __call__(self, task: str, output: str) -> str | None:
        return self._judge(task=task, output=output)

    def _judge(self, **fields: str) -> str | None:
        # A critique round is optional work (see `TokenBudget`): it is the largest
        # per-answer cost and the run is still correct without it. Denied means
        # accept the answer, never an exception — and the round counters are left
        # alone, because a round that was never spent is not a round.
        if self.budget is not None and not self.budget.allow("optional"):
            return None
        verdict = structured(
            self.client, self.rubric.prompt.format(**fields), self.rubric.schema
        )
        if verdict["score"] >= self.rubric.threshold:
            self._rounds = 0
            return None
        self._rounds += 1
        if self._rounds >= self.max_rounds:
            self._rounds = 0
            raise CritiqueExhausted(
                f"below threshold {self.rubric.threshold} after {self.max_rounds} rounds; "
                f"last feedback: {verdict['feedback']}"
            )
        self.rounds_used += 1
        return _critique_feedback(
            score=verdict["score"],
            threshold=self.rubric.threshold,
            feedback=verdict["feedback"],
        )


class GroundedCritiqueGate(CritiqueGate):
    """CritiqueGate whose critic also sees the run's tool call/observation pairs."""

    wants_transcript = True

    def __init__(
        self,
        rubric: str | Rubric = "grounded-completion",
        client: ModelClient | None = None,
        max_rounds: int | None = None,
        evidence_budget: int | None = None,
    ):
        super().__init__(rubric, client=client, max_rounds=max_rounds)
        _validate_grounded_rubric(self.rubric)
        self.evidence_budget = (
            evidence_budget
            if evidence_budget is not None
            else profile_default("critique", "evidence_budget")
        )

    def __call__(self, task: str, output: str, messages: list[Message]) -> str | None:
        evidence = render_evidence(messages, self.evidence_budget)
        return self._judge(task=task, output=output, evidence=evidence)
