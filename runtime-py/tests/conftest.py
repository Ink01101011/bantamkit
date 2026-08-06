from bantamkit.client import Message, Response, ToolCall, Usage


class FakeClient:
    """Scripted ModelClient: returns queued responses, records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": list(tools or [])})
        return self.responses.pop(0)


def assistant(content=None, tool_calls=None, prompt_tokens=10, completion_tokens=5):
    return Response(
        message=Message(role="assistant", content=content, tool_calls=tool_calls or []),
        usage=Usage(prompt_tokens, completion_tokens),
    )


def call(name, arguments, id="c1"):
    return ToolCall(id=id, name=name, arguments=arguments)
