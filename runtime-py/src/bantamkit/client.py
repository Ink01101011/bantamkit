"""Core types + ModelClient protocol + OpenAI-compatible adapter."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol


class BantamError(Exception):
    """Base for all bantamkit errors."""


class TransportError(BantamError):
    """HTTP-level failure after bounded retries."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None

    def to_wire(self) -> dict:
        wire: dict = {"role": self.role, "content": self.content}
        if self.tool_calls:
            wire["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in self.tool_calls
            ]
        if self.tool_call_id is not None:
            wire["tool_call_id"] = self.tool_call_id
        return wire


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema

    def to_wire(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.prompt_tokens + other.prompt_tokens,
                     self.completion_tokens + other.completion_tokens)

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class Response:
    message: Message
    usage: Usage


class ModelClient(Protocol):
    def chat(self, messages: list[Message], tools: list[Tool] | None = None) -> Response: ...
