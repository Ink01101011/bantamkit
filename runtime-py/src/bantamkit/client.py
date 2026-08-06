"""Core types + ModelClient protocol + OpenAI-compatible adapter."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx


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
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
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
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
        )

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class Response:
    message: Message
    usage: Usage


class ModelClient(Protocol):
    def chat(self, messages: list[Message], tools: list[Tool] | None = None) -> Response: ...


class OpenAICompatible:
    """One adapter covers Ollama / vLLM / LM Studio / llama.cpp server / OpenRouter."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "none",
        timeout: float = 60.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_retries = max_retries
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def chat(self, messages: list[Message], tools: list[Tool] | None = None) -> Response:
        payload: dict = {"model": self.model, "messages": [m.to_wire() for m in messages]}
        if tools:
            payload["tools"] = [t.to_wire() for t in tools]
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = self._http.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                if r.status_code >= 500:
                    raise TransportError(f"server error {r.status_code}: {r.text[:200]}")
                r.raise_for_status()
                return self._parse(r.json())
            except (httpx.TransportError, TransportError) as e:
                last_err = e
                time.sleep(0.5 * (2**attempt))
        raise TransportError(f"chat failed after {self.max_retries} attempts: {last_err}")

    @staticmethod
    def _parse(data: dict) -> Response:
        choice = data["choices"][0]["message"]
        tool_calls = [
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=json.loads(tc["function"]["arguments"]),
            )
            for tc in (choice.get("tool_calls") or [])
        ]
        usage = data.get("usage") or {}
        return Response(
            message=Message(role="assistant", content=choice.get("content"), tool_calls=tool_calls),
            usage=Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
        )
