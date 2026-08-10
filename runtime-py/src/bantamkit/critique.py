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
    """Output stayed below threshold for max_rounds critiques.

    Carries the transcript up to the raise, same payload and same reason as
    `MaxTurnsExceeded` and `StructuredOutputError`: the gate raises from inside
    the agent's post-hook chain, so without a slot every `critique-exhausted`
    run recorded `messages: []` and RP2 had to monkeypatch the runtime to read
    one. `Agent.run` fills the slot in — the gate itself is handed only the
    task and the answer.
    """

    def __init__(self, message: str, messages: list[Message] | None = None):
        super().__init__(message)
        self.messages: list[Message] = list(messages or [])


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


def _sampling_is_pinned(client: object) -> bool:
    """Whether the critic's own calls carry a pinned sampling seed, seen through wrappers.

    Exactly that and no more: a seed is *set*, which is not the same claim as sampling
    being deterministic. Whether the backend honours the pin is not visible from here —
    that half is the caller's to affirm (`CritiqueGate(deterministic_sampling=...)`).

    Duck-typed, the same spirit as `agent._supports_response_format` and as the eval
    harness's own `hasattr(client, "seed")`: `OpenAICompatible` carries a `seed` and
    the harness pins it per run, while a client that has none is free to resample.

    The walk down `.inner` is not decoration. A gate inherits `agent.client`, which in
    the eval harness is `TrackingClient` — no seed of its own and, unlike
    `_BudgetedClient`, no attribute passthrough — wrapped around the adapter that
    actually holds the seed. Reading only the outermost object would report every
    seeded eval run as unseeded.
    """
    seen: set[int] = set()
    while client is not None and id(client) not in seen:
        seen.add(id(client))
        if getattr(client, "seed", None) is not None:
            return True
        client = getattr(client, "inner", None)
    return False


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
        self,
        rubric: str | Rubric,
        client: ModelClient | None = None,
        max_rounds: int | None = None,
        deterministic_sampling: bool = False,
    ):
        """`deterministic_sampling` affirms that this critic's backend reproduces a
        sample exactly for a fixed request and a pinned seed. It is off by default and
        it is the caller's claim to make, because the library cannot check it: one
        adapter covers Ollama, vLLM, llama.cpp and OpenRouter, and on the batching ones
        a seed is best-effort. See `_verdict` for what the affirmation buys.
        """
        if isinstance(rubric, Rubric):
            _validate_rubric(rubric)
            self.rubric = rubric
        else:
            self.rubric = load_rubric(rubric)
        self.client = client
        self.deterministic_sampling = deterministic_sampling
        self.max_rounds = (
            max_rounds if max_rounds is not None else profile_default("critique", "max_rounds")
        )
        self._rounds = 0
        self.rounds_used = 0
        self.budget = None
        # Per-run: the last critic prompt and the verdict it bought. See `_verdict`.
        self._last_prompt: str | None = None
        self._last_verdict: dict | None = None

    def setup(self, agent: Agent) -> None:
        if self.client is None:
            self.client = agent.client
        self.rounds_used = 0
        self._last_prompt = None
        self._last_verdict = None
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
        verdict = self._verdict(self.rubric.prompt.format(**fields))
        if verdict["score"] >= self.rubric.threshold:
            self._rounds = 0
            return None
        self._rounds += 1
        # Counted before the exhaustion check, not after: the round that raises is a
        # round that was spent. Counting it afterwards meant every exhausted run
        # recorded one round fewer than the critic calls its own error text quoted
        # ("after 3 rounds" beside a recorded 2), and per-round token attribution
        # computed from the column came out a third too high. `rounds_used` is
        # "critique rounds that judged the answer below threshold" — a round the
        # budget denied is still not counted, because it was never spent.
        self.rounds_used += 1
        if self._rounds >= self.max_rounds:
            self._rounds = 0
            raise CritiqueExhausted(
                f"below threshold {self.rubric.threshold} after {self.max_rounds} rounds; "
                f"last feedback: {verdict['feedback']}"
            )
        return _critique_feedback(
            score=verdict["score"],
            threshold=self.rubric.threshold,
            feedback=verdict["feedback"],
        )

    def _verdict(self, prompt: str) -> dict:
        """The critic's judgement of this prompt — bought once per distinct prompt.

        Where sampling is deterministic, the critic is a deterministic function of its
        prompt, so a round that re-judges an unchanged answer is spend for a verdict
        already in hand. RP2 measured the shape: on the 14b `nav-prod-port` cell every
        round judged the identical `{"port": 9443}` and got back the identical verdict,
        and each of those rounds was a provably unwinnable one, because an unchanged
        answer guarantees an unchanged verdict guarantees exhaustion.

        Reuse, never a short cut around the loop. The reused verdict runs the same
        counting and the same exhaustion check the paid one would have, so
        `rounds_used`, the feedback bytes and the raised error come out exactly as they
        did — one model call fewer is the entire difference. Stopping the loop early
        instead would be the cheaper fix and the wrong one: the answerer sees a longer
        conversation each round and may still change its answer on the round after a
        repeat, so raising there could turn a run that would have passed into a loss.

        The key is the rendered prompt's exact bytes, which is the literal input the
        critic would have received — for `GroundedCritiqueGate` that includes the
        evidence, so a new tool observation is correctly a new question even under an
        unchanged answer. An answer that changed *textually* is likewise a new question
        and is paid for, even when it means the same thing as the last one (RP4d: the
        answerer sometimes appeases the critic by re-emitting the same value
        pretty-printed). Byte equality is the only equality this layer can prove;
        semantic equality is a judgement, and judging is the critic's job.

        Off by default, and on only when both halves of "the verdict is predictable"
        hold. That rule — this may only skip a call whose result it can predict, never
        one it merely expects — is the whole justification, and one half of it is not
        checkable from inside the library:

        - the caller affirmed `deterministic_sampling`, i.e. this backend reproduces a
          sample exactly for a fixed request and a pinned seed. Ollama does; `client.py`
          covers vLLM and OpenRouter with the same adapter, and there a seed is
          best-effort (continuous batching, upstream fingerprint drift). A seed being
          *set* proves nothing about that, so the affirmation cannot be inferred — it
          has to be stated, and stating it wrongly is the one way to lose a round;
        - and a seed is in fact pinned for this run (`_sampling_is_pinned`). Mechanical,
          so the gate checks it rather than taking it on trust: the affirmation is about
          the backend, this is about the client actually in hand.

        Without both, the same text may legitimately draw a different sample, and a
        consumer whose next round would have scored above threshold keeps that round.
        The cost of defaulting off is one re-judged verdict per repeat; the cost of
        defaulting on is a lucky would-pass turned into an exhaustion, on a backend the
        library advertises support for. Fail closed: pay for the call.
        """
        if self._last_prompt == prompt and self._last_verdict is not None:
            if self.deterministic_sampling and _sampling_is_pinned(self.client):
                return self._last_verdict
        verdict = structured(self.client, prompt, self.rubric.schema)
        self._last_prompt, self._last_verdict = prompt, verdict
        return verdict


class GroundedCritiqueGate(CritiqueGate):
    """CritiqueGate whose critic also sees the run's tool call/observation pairs."""

    wants_transcript = True

    def __init__(
        self,
        rubric: str | Rubric = "grounded-completion",
        client: ModelClient | None = None,
        max_rounds: int | None = None,
        evidence_budget: int | None = None,
        deterministic_sampling: bool = False,
    ):
        super().__init__(
            rubric,
            client=client,
            max_rounds=max_rounds,
            deterministic_sampling=deterministic_sampling,
        )
        _validate_grounded_rubric(self.rubric)
        self.evidence_budget = (
            evidence_budget
            if evidence_budget is not None
            else profile_default("critique", "evidence_budget")
        )

    def __call__(self, task: str, output: str, messages: list[Message]) -> str | None:
        evidence = render_evidence(messages, self.evidence_budget)
        return self._judge(task=task, output=output, evidence=evidence)
