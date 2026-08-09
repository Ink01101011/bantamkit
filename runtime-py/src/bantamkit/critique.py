"""Score-and-retry gate: rubric is data, scoring is schema-enforced, rounds are bounded."""

from __future__ import annotations

import json
from dataclasses import dataclass

import yaml

from bantamkit.agent import Agent, truncate
from bantamkit.assets import AssetNotFound, assets_root
from bantamkit.client import BantamError, Message, ModelClient
from bantamkit.structured import structured


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


def render_evidence(messages: list[Message], budget: int = 4096) -> str:
    """Tool call/observation pairs from a run's transcript, as critic-readable lines."""
    observations = {m.tool_call_id: m.content for m in messages if m.role == "tool"}
    lines = []
    for message in messages:
        for tc in message.tool_calls:
            observation = observations.get(tc.id, "(no observation)")
            lines.append(f"{tc.name}({json.dumps(tc.arguments)}) -> {observation}")
    if not lines:
        return "(no tool calls were made)"
    return truncate("\n".join(lines), budget)


class CritiqueGate:
    def __init__(
        self, rubric: str | Rubric, client: ModelClient | None = None, max_rounds: int = 3
    ):
        if isinstance(rubric, Rubric):
            _validate_rubric(rubric)
            self.rubric = rubric
        else:
            self.rubric = load_rubric(rubric)
        self.client = client
        self.max_rounds = max_rounds
        self._rounds = 0
        self.rounds_used = 0

    def setup(self, agent: Agent) -> None:
        if self.client is None:
            self.client = agent.client
        self.rounds_used = 0
        agent.add_post_hook(self)

    def __call__(self, task: str, output: str) -> str | None:
        return self._judge(task=task, output=output)

    def _judge(self, **fields: str) -> str | None:
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
        return (
            f"A reviewer scored your answer {verdict['score']}/10 "
            f"(needs >= {self.rubric.threshold}). Feedback: {verdict['feedback']}\n"
            f"Revise and answer again."
        )


class GroundedCritiqueGate(CritiqueGate):
    """CritiqueGate whose critic also sees the run's tool call/observation pairs."""

    wants_transcript = True

    def __init__(
        self,
        rubric: str | Rubric = "grounded-completion",
        client: ModelClient | None = None,
        max_rounds: int = 3,
        evidence_budget: int = 4096,
    ):
        super().__init__(rubric, client=client, max_rounds=max_rounds)
        _validate_grounded_rubric(self.rubric)
        self.evidence_budget = evidence_budget

    def __call__(self, task: str, output: str, messages: list[Message]) -> str | None:
        evidence = render_evidence(messages, self.evidence_budget)
        return self._judge(task=task, output=output, evidence=evidence)
