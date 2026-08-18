"""Core agentic loop: chat → tool call → observe → repeat, within budgets."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass, field

from bantamkit.client import BantamError, Message, ModelClient, Tool, Usage
from bantamkit.profile import default as profile_default
from bantamkit.textutil import truncate_counted


def response_format_for(schema: dict) -> dict:
    """The wire shape of the constrained-decoding tier, in one place.

    Lives here rather than in `structured.py` so both core callers — the one-shot
    `structured()` loop and the agent loop — send byte-identical bodies; a second
    spelling would make "same tier" unfalsifiable across the two paths.
    """
    return {"type": "json_schema", "json_schema": {"name": "output", "schema": schema}}


def _supports_response_format(client: ModelClient) -> bool:
    """Duck-typed capability check, same spirit as `seed`.

    A client that understands the kwarg exposes the memo (`OpenAICompatible`
    initializes it `False`); one that has met a 400 has flipped it to `True`.
    Fake clients and adapters that never heard of the kwarg lack the attribute
    entirely and are never sent it.
    """
    return hasattr(client, "_response_format_unsupported") and not (
        client._response_format_unsupported
    )


class MaxTurnsExceeded(BantamError):
    """The loop ended without a final answer inside the turn budget.

    Carries the transcript up to the raise. Without it, the runs most worth
    diagnosing are the ones that record nothing: v0.8.1's probes wrote
    `messages: []` for every turns-exhausted run.
    """

    def __init__(self, message: str, messages: list[Message] | None = None):
        super().__init__(message)
        self.messages: list[Message] = list(messages or [])


def _attach_transcript(error: BantamError, messages: list[Message]) -> None:
    """Fill in a gate-raised error's transcript slot from the agent's own messages.

    A post hook raises from inside `_first_feedback`, where the agent is the last
    holder of the transcript — the hook was never handed one, and `run_task`'s own
    `messages` list is still empty. Without this, every `schema-exhausted` and
    `critique-exhausted` run recorded `messages: []`.

    Opt-in by declaration, and fill-once: only an error that already carries a
    `messages` list (the `MaxTurnsExceeded` shape) is filled, and only while that
    list is empty. An error that declares no slot is left exactly as raised — a
    transport failure is not a gate giving up, and measurement must not invent a
    payload for it.
    """
    existing = getattr(error, "messages", None)
    if isinstance(existing, list) and not existing:
        error.messages = list(messages)


@dataclass
class ToolDef:
    tool: Tool
    handler: Callable[..., str]


_STRING_COERCIONS: dict[str, Callable[[str], object]] = {
    "integer": int,
    "number": float,
    "boolean": lambda v: {"true": True, "false": False}[v.strip().lower()],
}


def coerce_arguments(arguments: dict, parameters: dict) -> dict:
    """Adapt string-spelled scalars to the tool's declared parameter schema.

    Small models send `k` as the JSON string `"10"` and the handler dies
    comparing int to str — 17 of the 18 tool-argument failures in the 3b probe.
    Only strings under an `integer`/`number`/`boolean` property are touched,
    top level only; a conversion that fails passes the original value through
    so today's error observation fires unchanged. Well-typed calls are no-ops.
    """
    properties = parameters.get("properties") if isinstance(parameters, dict) else None
    if not isinstance(properties, dict):
        return arguments
    coerced = dict(arguments)
    for key, value in arguments.items():
        schema = properties.get(key)
        if not isinstance(value, str) or not isinstance(schema, dict):
            continue
        declared = schema.get("type")
        convert = _STRING_COERCIONS.get(declared) if isinstance(declared, str) else None
        if convert is None:
            continue
        try:
            coerced[key] = convert(value)
        except (ValueError, KeyError):
            pass  # unconvertible: hand the handler what the model actually sent
    return coerced


@dataclass
class AgentResult:
    output: str
    messages: list[Message]
    usage: Usage
    #: C-6, 2026-08-19. How many tool observations this run had cut to fit
    #: `observation_budget`, and how many bytes went with them. The cut was always
    #: announced IN BAND — `[truncated N bytes]` inside the string the model reads — and
    #: nowhere else, so a run whose evidence was cut and one whose was not were the same
    #: object to every caller, every scorer and every artifact. RB-P51: a run that
    #: silently proceeded is not the same run as one that reported what it dropped.
    #:
    #: Zero on an uncut run, which is what keeps the column from being always-on. It is a
    #: DISCLOSURE and not a verdict: the loop still proceeds, exactly as it did before,
    #: and nothing here decides whether a cut run is scorable.
    observations_truncated: int = 0
    observation_bytes_dropped: int = 0


@dataclass
class Agent:
    client: ModelClient
    tools: list[ToolDef] = field(default_factory=list)
    system: str | None = None
    max_turns: int | None = None
    observation_budget: int | None = None
    # Optional spend governor (`bantamkit.budget.TokenBudget`), attached by `use(...)`.
    # Typed loosely and duck-typed at the call sites on purpose: core must not depend
    # on the component, and an agent without one is byte-identical to before.
    budget: object | None = None
    # Optional constrained-decoding request for the loop's own model call
    # (`response_format_for(schema)`). Unset by default and forwarded only to a client
    # that understands the kwarg, so every existing caller stays byte-identical.
    # It has to live on the loop, not on a gate: a gate only ever sees a violation that
    # already happened, and the decode worth constraining is the first one.
    response_format: dict | None = None
    _post_hooks: list[Callable[..., str | None]] = field(default_factory=list)
    # Component state that must be scoped to one assistant turn's tool calls rather
    # than to the whole run — see `add_batch_scope`. An agent that registers none
    # behaves exactly as it did before the hook existed.
    _batch_scopes: list[Callable[[], AbstractContextManager]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.tools = list(self.tools or [])
        if self.max_turns is None:
            self.max_turns = profile_default("agent", "max_turns")
        if self.observation_budget is None:
            self.observation_budget = profile_default("agent", "observation_budget")

    def use(self, *components) -> Agent:
        for component in components:
            component.setup(self)
        return self

    def register_tool(self, tooldef: ToolDef) -> None:
        self.tools.append(tooldef)

    def add_system(self, text: str) -> None:
        self.system = f"{self.system}\n\n{text}" if self.system else text

    def add_post_hook(self, hook: Callable[..., str | None]) -> None:
        self._post_hooks.append(hook)

    def add_batch_scope(self, scope: Callable[[], AbstractContextManager]) -> None:
        """Register a context-manager factory entered around each tool-call batch.

        The model emits a whole batch of tool calls from one view of the world, and
        this loop then dispatches them one after another — so a write early in the
        batch is visible to a read later in the same batch, which the model has no
        way to anticipate. A component whose state must not move under its own feet
        mid-turn registers the boundary here; only the component knows what "not
        moving" means for it, and only the loop knows where the turn ends.
        """
        self._batch_scopes.append(scope)

    def run(self, prompt: str) -> AgentResult:
        messages: list[Message] = []
        if self.system:
            messages.append(Message(role="system", content=self.system))
        messages.append(Message(role="user", content=prompt))
        usage = Usage()
        last_content = ""
        observations_truncated = 0
        observation_bytes_dropped = 0

        for _ in range(self.max_turns):
            if self.budget is not None and not self.budget.allow("required"):
                # Past the hard ceiling. Stop iterating and hand back what the run
                # already produced: a truncated answer is still scorable, and an
                # exception here would convert a scorable answer into a loss.
                return AgentResult(
                    output=last_content,
                    messages=messages,
                    usage=usage,
                    observations_truncated=observations_truncated,
                    observation_bytes_dropped=observation_bytes_dropped,
                )
            resp = self._chat(messages)
            usage = usage + resp.usage
            messages.append(resp.message)
            if resp.message.content:
                last_content = resp.message.content

            if resp.message.tool_calls:
                with ExitStack() as stack:
                    for scope in self._batch_scopes:
                        stack.enter_context(scope())
                    for tc in resp.message.tool_calls:
                        observation, dropped = truncate_counted(
                            self._dispatch(tc), self.observation_budget
                        )
                        if dropped:
                            observations_truncated += 1
                            observation_bytes_dropped += dropped
                        messages.append(
                            Message(role="tool", content=observation, tool_call_id=tc.id)
                        )
                continue

            output = resp.message.content or ""
            try:
                feedback = self._first_feedback(prompt, output, messages)
            except BantamError as e:
                # Recording only. The exception propagates unchanged — same type,
                # same message, same traceback — so no verdict can move.
                _attach_transcript(e, messages)
                raise
            if feedback is None:
                return AgentResult(
                    output=output,
                    messages=messages,
                    usage=usage,
                    observations_truncated=observations_truncated,
                    observation_bytes_dropped=observation_bytes_dropped,
                )
            messages.append(Message(role="user", content=feedback))

        raise MaxTurnsExceeded(f"no final answer within {self.max_turns} turns", messages)

    def _chat(self, messages: list[Message]):
        """One model call, with the constrained-decoding tier when it is available.

        Re-checked per turn, as `structured()` does: a 400 on turn 1 flips the client's
        memo and silently drops the tier from there on.
        """
        tools = [t.tool for t in self.tools] or None
        if self.response_format is not None and _supports_response_format(self.client):
            return self.client.chat(messages, tools=tools, response_format=self.response_format)
        return self.client.chat(messages, tools=tools)

    def _dispatch(self, tc) -> str:
        tooldef = next((t for t in self.tools if t.tool.name == tc.name), None)
        if tooldef is None:
            names = [t.tool.name for t in self.tools]
            return f"error: unknown tool '{tc.name}'. available tools: {names}"
        try:
            arguments = coerce_arguments(tc.arguments, tooldef.tool.parameters)
            return str(tooldef.handler(**arguments))
        except Exception as e:
            return f"error: {tc.name} failed: {e}. fix the arguments and retry."

    def _first_feedback(
        self, task: str, output: str, messages: list[Message]
    ) -> str | None:
        for hook in self._post_hooks:
            if getattr(hook, "wants_transcript", False):
                feedback = hook(task, output, messages)
            else:
                feedback = hook(task, output)
            if feedback is not None:
                return feedback
        return None
