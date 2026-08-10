import pytest
from conftest import FakeClient, assistant, call

from bantamkit.agent import Agent, ToolDef
from bantamkit.budget import TokenBudget
from bantamkit.client import BantamError, Message, Tool
from bantamkit.critique import (
    CritiqueExhausted,
    CritiqueGate,
    GroundedCritiqueGate,
    Rubric,
    load_rubric,
    render_evidence,
)


def test_load_rubric_from_assets():
    rubric = load_rubric("task-completion")
    assert rubric.name == "task-completion" and rubric.threshold == 7
    assert "{task}" in rubric.prompt and "{output}" in rubric.prompt
    assert rubric.schema["required"] == ["score", "feedback"]


def make_rubric(threshold=7):
    return Rubric(
        name="r",
        threshold=threshold,
        prompt="Task:{task} Answer:{output}",
        schema={
            "type": "object",
            "required": ["score", "feedback"],
            "properties": {"score": {"type": "integer"}, "feedback": {"type": "string"}},
        },
    )


def test_pass_first_round():
    # agent answer, then critique verdict
    client = FakeClient(
        [assistant(content="answer"), assistant(content='{"score": 9, "feedback": "fine"}')]
    )
    agent = Agent(client=client).use(CritiqueGate(make_rubric(), client=client))
    assert agent.run("t").output == "answer"


def test_below_threshold_feeds_back_then_passes():
    client = FakeClient(
        [
            assistant(content="draft"),
            assistant(content='{"score": 4, "feedback": "missing the total"}'),
            assistant(content="final with total"),
            assistant(content='{"score": 8, "feedback": "ok"}'),
        ]
    )
    agent = Agent(client=client).use(CritiqueGate(make_rubric(), client=client))
    result = agent.run("t")
    assert result.output == "final with total"
    feedback_msg = client.calls[2]["messages"][-1].content
    assert "missing the total" in feedback_msg and "4" in feedback_msg


def test_exhausted_rounds_raises():
    script = []
    for i in range(3):
        script.append(assistant(content=f"draft {i}"))
        script.append(assistant(content='{"score": 2, "feedback": "bad"}'))
    client = FakeClient(script)
    agent = Agent(client=client, max_turns=20).use(
        CritiqueGate(make_rubric(), client=client, max_rounds=3)
    )
    with pytest.raises(CritiqueExhausted, match="3 rounds"):
        agent.run("t")


def test_rounds_used_counts_the_round_that_raises():
    """RP2: an exhausted gate recorded 2 for the 3 critic calls its own error text quoted."""
    script = []
    for i in range(3):
        script.append(assistant(content=f"draft {i}"))
        script.append(assistant(content='{"score": 2, "feedback": "bad"}'))
    client = FakeClient(script)
    gate = CritiqueGate(make_rubric(), client=client, max_rounds=3)
    agent = Agent(client=client, max_turns=20).use(gate)
    with pytest.raises(CritiqueExhausted, match="3 rounds"):
        agent.run("t")
    critic_calls = sum(1 for c in client.calls if "Task:t" in c["messages"][-1].content)
    assert critic_calls == 3
    assert gate.rounds_used == 3


def test_rounds_used_counts_every_below_threshold_round_short_of_the_cap():
    """Unchanged where the gate does not exhaust: one objection, one round."""
    client = FakeClient(
        [
            assistant(content="draft"),
            assistant(content='{"score": 4, "feedback": "thin"}'),
            assistant(content="final"),
            assistant(content='{"score": 8, "feedback": "ok"}'),
        ]
    )
    gate = CritiqueGate(make_rubric(), client=client)
    assert Agent(client=client).use(gate).run("t").output == "final"
    assert gate.rounds_used == 1


def test_critique_exhausted_messages_defaults_to_empty():
    """Declares the `MaxTurnsExceeded` transcript slot, so the agent can fill it in."""
    assert CritiqueExhausted("below threshold").messages == []


def test_critique_exhausted_carries_the_transcript():
    """The run RP2 had to monkeypatch the runtime to see must record itself."""
    script = []
    for i in range(3):
        script.append(assistant(content=f"draft {i}"))
        script.append(assistant(content='{"score": 2, "feedback": "bad"}'))
    client = FakeClient(script)
    agent = Agent(client=client, max_turns=20).use(
        CritiqueGate(make_rubric(), client=client, max_rounds=3)
    )
    with pytest.raises(CritiqueExhausted) as excinfo:
        agent.run("t")
    contents = [m.content for m in excinfo.value.messages if m.role == "assistant"]
    assert contents == ["draft 0", "draft 1", "draft 2"]


def test_grounded_critique_exhausted_carries_the_transcript():
    """The grounded gate inherits the payload, tool calls and all."""
    responses = [assistant(tool_calls=[call("price_lookup", {"item": "widget"})])]
    for i in range(3):
        responses.append(assistant(content=f"answer {i}"))
        responses.append(assistant(content='{"score": 2, "feedback": "contradicts evidence"}'))
    client = FakeClient(responses)
    agent = Agent(
        client=client, max_turns=20, tools=[lookup_tool(lambda item: f"{item}: 25")]
    ).use(GroundedCritiqueGate(make_grounded_rubric(), client=client))
    with pytest.raises(CritiqueExhausted) as excinfo:
        agent.run("t")
    messages = excinfo.value.messages
    assert [tc.name for m in messages for tc in m.tool_calls] == ["price_lookup"]
    assert [m.content for m in messages if m.role == "assistant" and m.content] == [
        "answer 0",
        "answer 1",
        "answer 2",
    ]


def test_gate_defaults_to_agent_client():
    client = FakeClient(
        [assistant(content="answer"), assistant(content='{"score": 9, "feedback": "fine"}')]
    )
    gate = CritiqueGate(make_rubric())
    Agent(client=client).use(gate).run("t")
    assert gate.client is client


def test_load_rubric_missing_output_placeholder():
    """Rubric prompt missing {output} should raise BantamError."""
    rubric = Rubric(
        name="bad",
        threshold=7,
        prompt="Task: {task}",
        schema={
            "type": "object",
            "required": ["score"],
            "properties": {"score": {"type": "integer"}},
        },
    )
    with pytest.raises(BantamError, match="output"):
        CritiqueGate(rubric)


def test_load_rubric_missing_task_placeholder():
    """Rubric prompt missing {task} should raise BantamError."""
    rubric = Rubric(
        name="bad",
        threshold=7,
        prompt="Answer: {output}",
        schema={
            "type": "object",
            "required": ["score"],
            "properties": {"score": {"type": "integer"}},
        },
    )
    with pytest.raises(BantamError, match="task"):
        CritiqueGate(rubric)


@pytest.mark.parametrize("rubric_name", ["task-completion", "code-quality"])
def test_shipped_rubrics_survive_format(rubric_name):
    """Shipped rubrics can be formatted and produce valid JSON schema."""
    rubric = load_rubric(rubric_name)
    formatted = rubric.prompt.format(task="t", output="o")
    assert '{"score"' in formatted


def test_shipped_grounded_rubric_survives_format():
    rubric = load_rubric("grounded-completion")
    formatted = rubric.prompt.format(task="t", output="o", evidence="e")
    assert '{"reasoning"' in formatted and '"score"' in formatted
    assert rubric.schema["required"] == ["reasoning", "score", "feedback"]


def lookup_tool(handler):
    return ToolDef(
        tool=Tool(
            name="price_lookup",
            description="look up a price",
            parameters={"type": "object", "properties": {"item": {"type": "string"}}},
        ),
        handler=handler,
    )


def make_grounded_rubric(threshold=7):
    return Rubric(
        name="g",
        threshold=threshold,
        prompt="Task:{task} Evidence:{evidence} Answer:{output}",
        schema={
            "type": "object",
            "required": ["score", "feedback"],
            "properties": {"score": {"type": "integer"}, "feedback": {"type": "string"}},
        },
    )


def test_render_evidence_pairs_calls_with_observations():
    messages = [
        Message(role="user", content="q"),
        Message(role="assistant", tool_calls=[call("price_lookup", {"item": "widget"})]),
        Message(role="tool", content="widget: 25", tool_call_id="c1"),
        Message(role="assistant", tool_calls=[call("price_lookup", {"item": "gadget"}, id="c2")]),
        Message(role="tool", content="gadget: 40", tool_call_id="c2"),
        Message(role="assistant", content="total 90"),
    ]
    evidence = render_evidence(messages)
    assert evidence == (
        'price_lookup({"item": "widget"}) -> widget: 25\n'
        'price_lookup({"item": "gadget"}) -> gadget: 40'
    )


def test_render_evidence_no_tool_calls():
    messages = [Message(role="user", content="q"), Message(role="assistant", content="a")]
    assert render_evidence(messages) == "(no tool calls were made)"


def test_render_evidence_missing_observation():
    messages = [Message(role="assistant", tool_calls=[call("f", {"x": 1})])]
    assert render_evidence(messages) == 'f({"x": 1}) -> (no observation)'


def test_render_evidence_truncates_at_budget():
    messages = [
        Message(role="assistant", tool_calls=[call("f", {})]),
        Message(role="tool", content="x" * 100, tool_call_id="c1"),
    ]
    evidence = render_evidence(messages, budget=20)
    assert "[truncated" in evidence and len(evidence.encode()) < 120


def test_grounded_gate_rejects_rubric_without_evidence_placeholder():
    with pytest.raises(BantamError, match="evidence"):
        GroundedCritiqueGate(make_rubric())


def test_grounded_gate_loads_asset_rubric_by_default():
    gate = GroundedCritiqueGate(client=FakeClient([]))
    assert gate.rubric.name == "grounded-completion" and gate.rubric.threshold == 7
    assert "{evidence}" in gate.rubric.prompt
    assert gate.wants_transcript is True


def test_grounded_gate_critic_sees_evidence_and_passes():
    client = FakeClient(
        [
            assistant(tool_calls=[call("price_lookup", {"item": "widget"})]),
            assistant(content="total is 25"),
            assistant(content='{"score": 9, "feedback": "matches evidence"}'),
        ]
    )
    agent = Agent(
        client=client,
        tools=[lookup_tool(lambda item: f"{item}: 25")],
    ).use(GroundedCritiqueGate(make_grounded_rubric(), client=client))
    result = agent.run("total?")
    assert result.output == "total is 25"
    critic_prompt = client.calls[2]["messages"][-1].content
    assert 'price_lookup({"item": "widget"}) -> widget: 25' in critic_prompt


def test_grounded_gate_feedback_and_exhaustion_match_parent_semantics():
    responses = []
    for i in range(3):
        responses.append(assistant(content=f"answer {i}"))
        responses.append(assistant(content='{"score": 2, "feedback": "contradicts evidence"}'))
    client = FakeClient(responses)
    gate = GroundedCritiqueGate(make_grounded_rubric(), client=client)
    agent = Agent(client=client, max_turns=20).use(gate)
    with pytest.raises(CritiqueExhausted, match="contradicts evidence"):
        agent.run("t")
    assert gate.rounds_used == 3  # two feedback rounds plus the round that raised
    feedback_msg = client.calls[2]["messages"][-1].content
    assert "A reviewer scored your answer 2/10" in feedback_msg


def test_grounded_gate_constructor_kwargs_reach_judge():
    client = FakeClient(
        [
            assistant(tool_calls=[call("price_lookup", {"item": "widget"})]),
            assistant(content="total is 25"),
            assistant(content='{"score": 2, "feedback": "bad"}'),
        ]
    )
    gate = GroundedCritiqueGate(
        make_grounded_rubric(), client=client, max_rounds=1, evidence_budget=20
    )
    agent = Agent(client=client, tools=[lookup_tool(lambda item: "x" * 100)]).use(gate)
    with pytest.raises(CritiqueExhausted):
        agent.run("total?")
    critic_prompt = client.calls[2]["messages"][-1].content
    assert "[truncated" in critic_prompt


def test_render_evidence_duplicate_ids_pair_in_order():
    messages = [
        Message(role="assistant", tool_calls=[call("f", {"n": 1})]),
        Message(role="tool", content="first", tool_call_id="c1"),
        Message(role="assistant", tool_calls=[call("f", {"n": 2})]),
        Message(role="tool", content="second", tool_call_id="c1"),
    ]
    assert render_evidence(messages) == 'f({"n": 1}) -> first\nf({"n": 2}) -> second'


def test_render_evidence_observation_before_call_does_not_pair():
    messages = [
        Message(role="tool", content="stray", tool_call_id="c1"),
        Message(role="assistant", tool_calls=[call("f", {})]),
    ]
    assert render_evidence(messages) == 'f({}) -> (no observation)'


def test_render_evidence_duplicate_ids_in_one_assistant_message():
    """Two calls sharing an id in ONE assistant message must consume observations in order."""
    messages = [
        Message(role="assistant", tool_calls=[call("f", {"n": 1}), call("f", {"n": 2})]),
        Message(role="tool", content="first", tool_call_id="c1"),
        Message(role="tool", content="second", tool_call_id="c1"),
    ]
    assert render_evidence(messages) == 'f({"n": 1}) -> first\nf({"n": 2}) -> second'


# ---- P3: critique rounds are optional work and must ask the budget ----


def test_critique_round_is_skipped_when_the_budget_denies_optional_work():
    """Denied means accept the answer: no critic call, no exception, no round spent."""
    client = FakeClient([assistant(content="answer")])  # no verdict is scripted
    gate = CritiqueGate(make_rubric(), client=client)
    budget = TokenBudget(ceiling=20, optional_cutoff=0.5)  # cutoff = 10, one answer = 15
    agent = Agent(client=client).use(budget, gate)
    result = agent.run("t")
    assert result.output == "answer"
    assert len(client.calls) == 1  # the critic was never called
    assert gate.rounds_used == 0
    assert budget.exhausted is False  # the cutoff band is degradation, not exhaustion


def test_critique_round_still_runs_under_the_cutoff():
    client = FakeClient(
        [assistant(content="answer"), assistant(content='{"score": 9, "feedback": "fine"}')]
    )
    gate = CritiqueGate(make_rubric(), client=client)
    agent = Agent(client=client).use(TokenBudget(ceiling=6000), gate)
    assert agent.run("t").output == "answer"
    assert len(client.calls) == 2


def test_rounds_used_stays_honest_when_a_later_round_is_denied():
    """Round one is spent and counted; round two is denied and must not be counted."""
    client = FakeClient(
        [
            assistant(content="answer one", prompt_tokens=30),
            assistant(content='{"score": 2, "feedback": "thin"}', prompt_tokens=30),
            assistant(content="answer two", prompt_tokens=30),
        ]
    )
    gate = CritiqueGate(make_rubric(), client=client)
    # 35 tokens per agent turn; cutoff = 50, ceiling = 100. The gate holds an
    # explicit unwrapped client, so its critic calls bypass the governor's wrapper
    # and only turns move `spent` — which is what this denial arithmetic needs.
    budget = TokenBudget(ceiling=100, optional_cutoff=0.5)
    agent = Agent(client=client).use(budget, gate)
    result = agent.run("t")
    assert result.output == "answer two"
    assert gate.rounds_used == 1
    assert budget.spent == 70 and budget.exhausted is False


def test_grounded_gate_inherits_the_budget_check():
    client = FakeClient([assistant(content="total is 25")])  # no verdict is scripted
    gate = GroundedCritiqueGate(make_grounded_rubric(), client=client)
    agent = Agent(client=client).use(TokenBudget(ceiling=20, optional_cutoff=0.5), gate)
    assert agent.run("total?").output == "total is 25"
    assert len(client.calls) == 1 and gate.rounds_used == 0


def test_gate_without_a_budget_keeps_every_round():
    gate = CritiqueGate(make_rubric(), client=FakeClient([]))
    gate.setup(Agent(client=FakeClient([])))
    assert gate.budget is None
