import pytest
from conftest import FakeClient, assistant, call

from bantamkit.agent import Agent
from bantamkit.assets import assets_root, load_skill, load_tool
from bantamkit.memory import Memory
from bantamkit.memory.component import normalize_name
from bantamkit.memory.store import MemoryStore, MemoryValidationError


def test_assets_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    assert assets_root() == tmp_path


def test_assets_root_finds_repo_assets(monkeypatch):
    monkeypatch.delenv("BANTAMKIT_ASSETS", raising=False)
    assert (assets_root() / "tools" / "memory_save.json").exists()


def test_load_tool_and_skill():
    tool = load_tool("memory_save")
    assert tool.name == "memory_save"
    assert tool.parameters["required"] == ["type", "name", "description", "body"]
    assert "recall QUERY" in load_skill("memory")


def test_setup_registers_tools_and_skill(tmp_path):
    agent = Agent(client=FakeClient([]), system="base")
    agent.use(Memory(store=tmp_path / "mem"))
    assert [t.tool.name for t in agent.tools] == ["memory_save", "memory_recall"]
    assert "Recall first" in agent.system and agent.system.startswith("base")


def test_save_and_recall_through_agent_loop(tmp_path):
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call(
                        "memory_save",
                        {
                            "type": "project",
                            "name": "deploy-command",
                            "description": "how we deploy to prod",
                            "body": "make ship-prod",
                        },
                    )
                ]
            ),
            assistant(tool_calls=[call("memory_recall", {"query": "deploy prod"}, id="c2")]),
            assistant(content="use make ship-prod"),
        ]
    )
    agent = Agent(client=client).use(Memory(store=tmp_path / "mem"))
    result = agent.run("remember then answer how we deploy")
    save_obs = client.calls[1]["messages"][-1].content
    recall_obs = client.calls[2]["messages"][-1].content
    assert "saved 'deploy-command'" in save_obs
    assert "make ship-prod" in recall_obs
    assert result.output == "use make ship-prod"


def test_validation_error_becomes_actionable_observation(tmp_path):
    # Unit test: component handles validation error directly
    memory = Memory(store=tmp_path / "mem")
    result = memory._save(type="bogus", name="x", description="d", body="b")
    assert result.startswith("error:") and "bogus" in result

    # Integration test: loop-level error handling is not used
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call(
                        "memory_save",
                        {"type": "bogus", "name": "x", "description": "d", "body": "b"},
                    )
                ]
            ),
            assistant(content="ok"),
        ]
    )
    Agent(client=client).use(Memory(store=tmp_path / "mem")).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert obs.startswith("error:") and "bogus" in obs and "memory_save failed" not in obs


def test_budget_exceeded_becomes_an_accurate_observation(tmp_path):
    """A budget overflow is not an argument error — the loop's generic retry advice misleads."""
    # Unit test: the component handles the budget error itself
    memory = Memory(store=tmp_path / "mem", index_budget=10)
    result = memory._save(type="project", name="deploy-command", description="d", body="b")
    assert result.startswith("error:")
    assert "budget" in result and "compact" in result
    assert "fix the arguments" not in result

    # Integration test: the observation reaches the model unchanged by Agent._dispatch
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call(
                        "memory_save",
                        {
                            "type": "project",
                            "name": "deploy-command",
                            "description": "d",
                            "body": "b",
                        },
                    )
                ]
            ),
            assistant(content="ok"),
        ]
    )
    Agent(client=client).use(memory).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert "budget" in obs and "compact" in obs
    assert "memory_save failed" not in obs and "fix the arguments" not in obs


def test_duplicate_reply_guides_update(tmp_path):
    memory = Memory(store=tmp_path / "mem")
    memory.store.save("project", "deploy-command", "how we deploy to prod", "x")
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call(
                        "memory_save",
                        {
                            "type": "project",
                            "name": "deploy-steps",
                            "description": "how we deploy to the prod server",
                            "body": "y",
                        },
                    )
                ]
            ),
            assistant(content="ok"),
        ]
    )
    Agent(client=client).use(memory).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert "deploy-command" in obs and "update" in obs


# ---- P1b: name normalization ----


@pytest.mark.parametrize(
    "given,expected",
    [
        ("deploy_command", "deploy-command"),
        ("Deploy Command", "deploy-command"),
        ("DEPLOY_COMMAND", "deploy-command"),
        ("  deploy command  ", "deploy-command"),
        ("deploy-command", "deploy-command"),  # already canonical: no-op
        ("db-port-5432", "db-port-5432"),
    ],
)
def test_normalize_name_table(given, expected):
    assert normalize_name(given) == expected


def test_normalize_name_passes_non_strings_through_to_store_validation():
    assert normalize_name(None) is None
    assert normalize_name(7) == 7


def test_save_normalizes_invented_snake_case_name(tmp_path):
    """The store's pattern does not move; the component adapts the model's spelling."""
    memory = Memory(store=tmp_path / "mem")
    result = memory.save(type="project", name="Deploy_Command", description="d", body="b")
    assert result == "saved 'deploy-command'"  # the model is told the canonical form
    assert memory.store.recall("deploy", 1)[0].name == "deploy-command"


def test_save_normalizes_links(tmp_path):
    memory = Memory(store=tmp_path / "mem")
    memory.save(
        type="project",
        name="ship_steps",
        description="how we ship",
        body="b",
        links=["Deploy_Command", "db port"],
    )
    fact = memory.store.recall("ship", 1)[0]
    assert fact.links == ["deploy-command", "db-port"]


def test_save_invalid_name_still_reaches_store_validation(tmp_path):
    """Normalization is not leniency: characters the pattern rejects still error."""
    memory = Memory(store=tmp_path / "mem")
    result = memory.save(type="project", name="deploy/command!", description="d", body="b")
    assert result.startswith("error:") and "invalid name" in result


def test_save_normalized_name_survives_the_agent_loop(tmp_path):
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call(
                        "memory_save",
                        {
                            "type": "project",
                            "name": "deploy_command",
                            "description": "how we deploy to prod",
                            "body": "make ship-prod",
                        },
                    )
                ]
            ),
            assistant(content="ok"),
        ]
    )
    Agent(client=client).use(Memory(store=tmp_path / "mem")).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert obs == "saved 'deploy-command'"


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def _seed(root, name, body, description="a fact about deploys"):
    MemoryStore(root).save("project", name, description, body)


def test_layered_project_wins_on_duplicate_name_and_prefixes_layers(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "deploy", "project truth")
    profile_store = fake_home / ".bantamkit" / "memory"
    _seed(profile_store, "deploy", "profile stale")
    _seed(profile_store, "profile-only", "profile extra", description="deploy note extra")

    mem = Memory.layered(start=project)
    out = mem._recall("deploy")
    assert "[project] [deploy]" in out
    assert "project truth" in out
    assert "profile stale" not in out  # deduped by name, project wins
    assert "[profile] [profile-only]" in out


def test_layered_k_budget_is_total_across_layers(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    store = project / ".bantamkit" / "memory"
    descriptions = [
        "deploy to main branch immediately",
        "deploy to staging environment first",
        "deploy procedure includes rollback",
    ]
    for i in range(3):
        _seed(store, f"proj-{i}", "x", description=descriptions[i])
    profile_store = fake_home / ".bantamkit" / "memory"
    _seed(profile_store, "prof", "y", description="deploy to production at night")

    out = Memory.layered(start=project, k=3)._recall("deploy")
    assert out.count("[project] [") == 3
    assert "[profile]" not in out  # budget spent before profile


def test_layered_save_writes_project_layer_only(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    other = tmp_path / "companyB" / ".bantamkit" / "memory"
    _seed(other, "b-fact", "b body", description="grant fact")
    (project / ".bantamkit").mkdir()
    (project / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n"
    )
    grant_before = sorted(p.name for p in (other / "facts").glob("*.md"))

    mem = Memory.layered(start=project)
    assert mem._save("project", "a-fact", "saved from A", "body") == "saved 'a-fact'"
    assert (project / ".bantamkit" / "memory" / "facts" / "a-fact.md").exists()
    assert sorted(p.name for p in (other / "facts").glob("*.md")) == grant_before
    assert not (fake_home / ".bantamkit" / "memory" / "facts").exists()


def test_layered_recall_does_not_stamp_readonly_layers(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    profile_store = fake_home / ".bantamkit" / "memory"
    _seed(profile_store, "prof", "profile body", description="deploy fact")
    before = (profile_store / "facts" / "prof.md").read_text()

    Memory.layered(start=project)._recall("deploy")
    assert (profile_store / "facts" / "prof.md").read_text() == before


def test_layered_corrupt_grant_does_not_break_project_recall(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "deploy", "project truth")
    bad = tmp_path / "companyB" / ".bantamkit" / "memory"
    (bad / "facts").mkdir(parents=True)
    (bad / "facts" / "junk.md").write_text("no frontmatter at all")
    (project / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n"
    )

    out = Memory.layered(start=project)._recall("deploy")
    assert "[project] [deploy]" in out


def test_layered_dangling_grant_raises_at_construction(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    (project / ".bantamkit").mkdir()
    (project / ".bantamkit" / "config.yaml").write_text("extra_stores:\n  - ../../nope\n")
    with pytest.raises(MemoryValidationError):
        Memory.layered(start=project)


def test_v1_single_store_output_has_no_layer_prefixes(tmp_path):
    mem = Memory(store=tmp_path / "m")
    mem._save("project", "deploy", "how to deploy", "make ship")
    out = mem._recall("deploy")
    assert "[deploy]" in out
    assert "[project]" not in out


def test_layered_budget_allows_later_layers_to_contribute_on_overlap(tmp_path, fake_home):
    """Regression test for budget parameter (not remaining): layers fetch full budget,
    deduplication handles overlaps, allowing later layers to fill gaps."""
    project = tmp_path / "companyA"
    project.mkdir()
    store = project / ".bantamkit" / "memory"
    _seed(store, "alpha", "x", description="alpha fact description context")
    _seed(store, "beta", "x", description="beta fact specific info here")
    profile_store = fake_home / ".bantamkit" / "memory"
    _seed(
        profile_store,
        "alpha",
        "y",
        description="alpha fact entry from profile differs",
    )
    _seed(profile_store, "gamma", "y", description="gamma fact only in profile")
    _seed(profile_store, "delta", "y", description="delta fact another profile entry")

    out = Memory.layered(start=project, k=4)._recall("fact")
    # Should return 4 facts: alpha (project), beta (project), gamma (profile), delta (profile)
    # Project layer returns alpha+beta (2 facts matching "fact")
    # Profile layer returns alpha (skip, seen), gamma, delta (2 new facts)
    # Total: 4 facts within budget
    assert out.count("\n\n") == 3  # 4 facts separated by 3 newline pairs
    assert "[project] [alpha]" in out
    assert "[project] [beta]" in out
    assert "[profile] [gamma]" in out
    assert "[profile] [delta]" in out


def test_corrupt_project_layer_raises_on_recall(tmp_path, fake_home):
    """Corrupt project layer (malformed facts) raises MemoryValidationError on recall."""
    project = tmp_path / "companyA"
    project.mkdir()
    project_store = project / ".bantamkit" / "memory"
    (project_store / "facts").mkdir(parents=True)
    # Write a corrupted fact file with no frontmatter
    (project_store / "facts" / "broken.md").write_text("no frontmatter here at all")

    with pytest.raises(MemoryValidationError):
        Memory.layered(start=project)._recall("test")


def test_v1_corrupt_layer_raises_on_recall(tmp_path):
    """Corrupt layer in v1 mode also raises MemoryValidationError on recall."""
    store_path = tmp_path / "m"
    (store_path / "facts").mkdir(parents=True)
    (store_path / "facts" / "broken.md").write_text("no frontmatter here at all")

    mem = Memory(store=store_path)
    with pytest.raises(MemoryValidationError):
        mem._recall("test")


def test_layered_short_circuits_and_does_not_query_profile_when_budget_filled(
    tmp_path, fake_home, monkeypatch
):
    """Profile store recall should not be called when k budget is filled by project layer."""
    project = tmp_path / "companyA"
    project.mkdir()
    store = project / ".bantamkit" / "memory"
    descriptions = [
        "fact: deploy to main branch",
        "fact: stage in test environment",
        "fact: rollback strategy procedure",
        "fact: monitoring after release",
    ]
    for i in range(4):
        _seed(store, f"proj-{i}", "x", description=descriptions[i])

    profile_store = fake_home / ".bantamkit" / "memory"
    _seed(profile_store, "prof", "y", description="fact from profile")

    mem = Memory.layered(start=project, k=4)
    # Spy on profile store recall by tracking calls
    profile_layer_store = mem._layers[-1][1]  # Get the profile store
    original_recall = profile_layer_store.recall
    recall_called = []

    def spy_recall(*args, **kwargs):
        recall_called.append((args, kwargs))
        return original_recall(*args, **kwargs)

    profile_layer_store.recall = spy_recall

    out = mem._recall("fact")
    # Should get 4 project facts, filling budget
    assert out.count("[project] [") == 4
    # Profile recall should NOT have been called (budget exhausted before reaching it)
    assert not recall_called, "Profile store recall should not be called when k budget is filled"


def test_layered_readonly_layer_with_invalid_utf8_does_not_break_recall(tmp_path, fake_home):
    """Regression test: a non-UTF-8 file in a granted read-only store must not crash recall.

    A bad external layer (e.g., corrupted file with invalid bytes) raises UnicodeDecodeError
    during store.recall() -> _facts() -> path.read_text(). The component's _recall method
    must catch this (as well as BantamError) and skip the corrupt layer, allowing the
    project layer to still return facts.
    """
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "deploy", "project truth")

    bad = tmp_path / "companyB" / ".bantamkit" / "memory"
    (bad / "facts").mkdir(parents=True)
    # Write a file with invalid UTF-8 bytes to trigger UnicodeDecodeError
    (bad / "facts" / "corrupted.md").write_bytes(b"\xff\xfe")

    (project / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n"
    )

    # Verify the project fact is returned despite the corrupt grant layer
    out = Memory.layered(start=project)._recall("deploy")
    assert "[project] [deploy]" in out
    assert "project truth" in out


# ---- RB-P1 P-A: the model-supplied k is floored at the component default ----


def test_recall_floors_a_model_supplied_k_at_the_component_default(tmp_path):
    """Measured: 57 of 60 `memory_recall` calls across 12 seeded 14b runs sent `k: 1`."""
    mem = Memory(store=tmp_path / "mem", k=3)
    mem.store.save("project", "gateway-user-quota", "per-user rate limit on the api gateway", "40")
    mem.store.save("project", "org-seat-count", "how many seats one org licence includes", "5")
    out = mem.recall("api gateway quota per user seats org licence", k=1)
    assert "[gateway-user-quota]" in out and "[org-seat-count]" in out


def test_recall_leaves_a_k_above_the_default_alone(tmp_path):
    mem = Memory(store=tmp_path / "mem", k=1)
    for i, description in enumerate(["alpha fact one", "alpha fact two", "alpha fact three"]):
        mem.store.save("project", f"f-{i}", description, "b")
    assert mem.recall("alpha fact", k=3).count("[f-") == 3


def test_recall_without_k_is_unchanged(tmp_path):
    mem = Memory(store=tmp_path / "mem", k=2)
    for i, description in enumerate(["alpha fact one", "alpha fact two", "alpha fact three"]):
        mem.store.save("project", f"f-{i}", description, "b")
    assert mem.recall("alpha fact").count("[f-") == 2


def test_component_floor_does_not_reach_into_the_store(tmp_path):
    """The store stays honest about doing what it was told; only the agent-facing layer bends."""
    store = MemoryStore(tmp_path / "mem")
    store.save("project", "alpha", "alpha fact one", "b")
    store.save("project", "beta", "alpha fact two", "b")
    assert len(store.recall("alpha fact", k=1)) == 1


def test_recall_floor_survives_the_agent_loop(tmp_path):
    client = FakeClient(
        [
            assistant(tool_calls=[call("memory_recall", {"query": "quota seats org", "k": 1})]),
            assistant(content="200"),
        ]
    )
    mem = Memory(store=tmp_path / "mem")
    mem.store.save("project", "gateway-user-quota", "per-user quota on the api gateway", "40")
    mem.store.save("project", "org-seat-count", "seats one org licence includes", "5")
    Agent(client=client).use(mem).run("t")
    obs = client.calls[1]["messages"][-1].content
    assert "[gateway-user-quota]" in obs and "[org-seat-count]" in obs


def test_malformed_k_still_becomes_an_error_observation(tmp_path):
    """Flooring must not swallow a nonsense argument — the error path is unchanged."""
    client = FakeClient(
        [
            assistant(tool_calls=[call("memory_recall", {"query": "x", "k": "lots"})]),
            assistant(content="ok"),
        ]
    )
    Agent(client=client).use(Memory(store=tmp_path / "mem")).run("t")
    assert client.calls[1]["messages"][-1].content.startswith("error:")


# ---- RB-P1 P-B: a save is not visible to a recall in the same tool-call batch ----


def test_same_batch_save_does_not_poison_a_later_recall(tmp_path):
    """Measured on seed 2418578173: recall / save / recall in one assistant turn, and the
    speculative save overwrote the ground-truth fact between the two reads."""
    mem = Memory(store=tmp_path / "mem")
    mem.store.save("project", "payments-api-owner", "which team owns the payments api", "Atlas")
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call("memory_recall", {"query": "owns payments api"}, id="c1"),
                    call(
                        "memory_save",
                        {
                            "type": "project",
                            "name": "payments-api-owner",
                            "description": "which team owns the payments api",
                            "body": "finance-team",
                        },
                        id="c2",
                    ),
                    call("memory_recall", {"query": "owns payments api"}, id="c3"),
                ]
            ),
            assistant(content="Atlas"),
        ]
    )
    Agent(client=client).use(mem).run("t")
    observations = [m.content for m in client.calls[1]["messages"] if m.role == "tool"]
    assert "Atlas" in observations[0]
    assert observations[2] == observations[0], "the second read saw the same-turn write"
    assert "finance-team" not in observations[2]


def test_the_save_still_lands_and_is_visible_on_the_next_turn(tmp_path):
    mem = Memory(store=tmp_path / "mem")
    client = FakeClient(
        [
            assistant(
                tool_calls=[
                    call(
                        "memory_save",
                        {
                            "type": "project",
                            "name": "deploy-command",
                            "description": "how we deploy to prod",
                            "body": "make ship-prod",
                        },
                        id="c1",
                    ),
                    call("memory_recall", {"query": "deploy prod"}, id="c2"),
                ]
            ),
            assistant(tool_calls=[call("memory_recall", {"query": "deploy prod"}, id="c3")]),
            assistant(content="ok"),
        ]
    )
    Agent(client=client).use(mem).run("t")
    first_turn = [m.content for m in client.calls[1]["messages"] if m.role == "tool"]
    second_turn = [m.content for m in client.calls[2]["messages"] if m.role == "tool"]
    assert "saved 'deploy-command'" in first_turn[0]
    assert "no memories matched" in first_turn[1]
    assert "make ship-prod" in second_turn[-1]


def test_batch_isolation_does_not_snapshot_read_only_layers(tmp_path, fake_home):
    """A corrupt grant must still be skipped, not raised at batch entry."""
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "deploy", "project truth")
    bad = tmp_path / "companyB" / ".bantamkit" / "memory"
    (bad / "facts").mkdir(parents=True)
    (bad / "facts" / "junk.md").write_text("no frontmatter at all")
    (project / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n"
    )
    client = FakeClient(
        [
            assistant(tool_calls=[call("memory_recall", {"query": "deploy"})]),
            assistant(content="ok"),
        ]
    )
    Agent(client=client).use(Memory.layered(start=project)).run("t")
    assert "[project] [deploy]" in client.calls[1]["messages"][-1].content
