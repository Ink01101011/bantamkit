"""Core agentic loop: chat → tool call → observe → repeat, within budgets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from bantamkit.client import BantamError, Message, ModelClient, Tool, Usage
from bantamkit.profile import default as profile_default
from bantamkit.textutil import truncate


class MaxTurnsExceeded(BantamError):
    """The loop ended without a final answer inside the turn budget.

    Carries the transcript up to the raise. Without it, the runs most worth
    diagnosing are the ones that record nothing: v0.8.1's probes wrote
    `messages: []` for every turns-exhausted run.
    """

    def __init__(self, message: str, messages: list[Message] | None = None):
        super().__init__(message)
        self.messages: list[Message] = list(messages or [])


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


@dataclass
class Agent:
    client: ModelClient
    tools: list[ToolDef] = field(default_factory=list)
    system: str | None = None
    max_turns: int | None = None
    observation_budget: int | None = None
    _post_hooks: list[Callable[..., str | None]] = field(default_factory=list)

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

    def run(self, prompt: str) -> AgentResult:
        messages: list[Message] = []
        if self.system:
            messages.append(Message(role="system", content=self.system))
        messages.append(Message(role="user", content=prompt))
        usage = Usage()

        for _ in range(self.max_turns):
            resp = self.client.chat(messages, tools=[t.tool for t in self.tools] or None)
            usage = usage + resp.usage
            messages.append(resp.message)

            if resp.message.tool_calls:
                for tc in resp.message.tool_calls:
                    observation = truncate(self._dispatch(tc), self.observation_budget)
                    messages.append(Message(role="tool", content=observation, tool_call_id=tc.id))
                continue

            output = resp.message.content or ""
            feedback = self._first_feedback(prompt, output, messages)
            if feedback is None:
                return AgentResult(output=output, messages=messages, usage=usage)
            messages.append(Message(role="user", content=feedback))

        raise MaxTurnsExceeded(f"no final answer within {self.max_turns} turns", messages)

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
