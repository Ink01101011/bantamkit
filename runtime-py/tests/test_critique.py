import pytest
from conftest import FakeClient, assistant

from bantamkit.agent import Agent
from bantamkit.critique import CritiqueExhausted, CritiqueGate, Rubric, load_rubric


def test_load_rubric_from_assets():
    rubric = load_rubric("task-completion")
    assert rubric.name == "task-completion" and rubric.threshold == 7
    assert "{task}" in rubric.prompt and "{output}" in rubric.prompt
    assert rubric.schema["required"] == ["score", "feedback"]


def make_rubric(threshold=7):
    return Rubric(name="r", threshold=threshold,
                  prompt="Task:{task} Answer:{output}",
                  schema={"type": "object", "required": ["score", "feedback"],
                          "properties": {"score": {"type": "integer"},
                                         "feedback": {"type": "string"}}})


def test_pass_first_round():
    # agent answer, then critique verdict
    client = FakeClient([assistant(content="answer"),
                         assistant(content='{"score": 9, "feedback": "fine"}')])
    agent = Agent(client=client).use(CritiqueGate(make_rubric(), client=client))
    assert agent.run("t").output == "answer"


def test_below_threshold_feeds_back_then_passes():
    client = FakeClient([
        assistant(content="draft"),
        assistant(content='{"score": 4, "feedback": "missing the total"}'),
        assistant(content="final with total"),
        assistant(content='{"score": 8, "feedback": "ok"}'),
    ])
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
        CritiqueGate(make_rubric(), client=client, max_rounds=3))
    with pytest.raises(CritiqueExhausted, match="3 rounds"):
        agent.run("t")


def test_gate_defaults_to_agent_client():
    client = FakeClient([assistant(content="answer"),
                         assistant(content='{"score": 9, "feedback": "fine"}')])
    gate = CritiqueGate(make_rubric())
    Agent(client=client).use(gate).run("t")
    assert gate.client is client
