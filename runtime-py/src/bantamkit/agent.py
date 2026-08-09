"""Core agentic loop: chat → tool call → observe → repeat, within budgets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from bantamkit.client import BantamError, Message, ModelClient, Tool, Usage
from bantamkit.profile import default as profile_default
from bantamkit.textutil import truncate


class MaxTurnsExceeded(BantamError):
    """The loop ended without a final answer inside the turn budget."""


@dataclass
class ToolDef:
    tool: Tool
    handler: Callable[..., str]


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

        raise MaxTurnsExceeded(f"no final answer within {self.max_turns} turns")

    def _dispatch(self, tc) -> str:
        handler = next((t.handler for t in self.tools if t.tool.name == tc.name), None)
        if handler is None:
            names = [t.tool.name for t in self.tools]
            return f"error: unknown tool '{tc.name}'. available tools: {names}"
        try:
            return str(handler(**tc.arguments))
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
