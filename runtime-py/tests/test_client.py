from bantamkit.client import Message, Response, Tool, ToolCall, Usage


def test_user_message_wire_format():
    assert Message(role="user", content="hi").to_wire() == {"role": "user", "content": "hi"}


def test_assistant_tool_call_wire_format():
    msg = Message(role="assistant", content=None,
                  tool_calls=[ToolCall(id="c1", name="lookup", arguments={"item": "widget"})])
    wire = msg.to_wire()
    assert wire["tool_calls"] == [{
        "id": "c1", "type": "function",
        "function": {"name": "lookup", "arguments": '{"item": "widget"}'},
    }]


def test_tool_result_wire_format():
    wire = Message(role="tool", content="42", tool_call_id="c1").to_wire()
    assert wire == {"role": "tool", "content": "42", "tool_call_id": "c1"}


def test_tool_wire_format():
    tool = Tool(name="lookup", description="d", parameters={"type": "object"})
    assert tool.to_wire() == {"type": "function", "function": {
        "name": "lookup", "description": "d", "parameters": {"type": "object"}}}


def test_usage_addition():
    total = Usage(10, 5) + Usage(3, 2)
    assert (total.prompt_tokens, total.completion_tokens) == (13, 7)


def test_response_holds_message_and_usage():
    r = Response(message=Message(role="assistant", content="ok"), usage=Usage())
    assert r.message.content == "ok" and r.usage.prompt_tokens == 0
