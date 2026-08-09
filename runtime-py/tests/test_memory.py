import pytest

from bantamkit.memory import (
    Memory,
    MemoryBudgetExceeded,
    MemoryStore,
    MemoryValidationError,
    SaveResult,
)


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "mem", today=lambda: "2026-08-06")


def test_save_writes_fact_file_and_index(store):
    result = store.save(
        "project", "deploy-command", "how we deploy to prod", "Deploy with `make ship-prod`."
    )
    assert result == SaveResult(status="saved", name="deploy-command")
    fact_file = store.root / "facts" / "deploy-command.md"
    assert fact_file.exists()
    text = fact_file.read_text()
    assert "type: project" in text and "make ship-prod" in text
    assert "- [[deploy-command]] (project) — how we deploy to prod" in store.index_text()


def test_save_rejects_bad_type_and_bad_name(store):
    with pytest.raises(MemoryValidationError, match="type"):
        store.save("nope", "a-name", "desc", "body")
    with pytest.raises(MemoryValidationError, match="name"):
        store.save("project", "Bad Name!", "desc", "body")
    with pytest.raises(MemoryValidationError, match="description"):
        store.save("project", "a-name", "", "body")


def test_save_detects_near_duplicate(store):
    store.save("project", "deploy-command", "how we deploy to prod", "make ship-prod")
    result = store.save("project", "deploy-steps", "how we deploy to the prod server", "x")
    assert result.status == "duplicate" and result.similar == "deploy-command"
    assert not (store.root / "facts" / "deploy-steps.md").exists()


def test_save_same_name_updates_without_duplicate_flag(store):
    store.save("project", "deploy-command", "how we deploy to prod", "old")
    result = store.save("project", "deploy-command", "how we deploy to prod", "new")
    assert result.status == "saved"
    assert "new" in (store.root / "facts" / "deploy-command.md").read_text()


def test_save_enforces_index_budget(tmp_path):
    store = MemoryStore(tmp_path / "mem", index_budget=119, today=lambda: "2026-08-06")
    store.save("project", "fact-one", "completely unrelated alpha topic", "a")
    with pytest.raises(MemoryBudgetExceeded, match="compact"):
        store.save("user", "fact-two", "different beta subject entirely", "b")
    # failed save must not leave a partial fact behind
    assert not (store.root / "facts" / "fact-two.md").exists()


def test_recall_returns_topk_and_stamps(store):
    store.save("project", "deploy-command", "how we deploy to prod", "make ship-prod")
    store.save("user", "editor-pref", "user prefers vim keybindings", "vim everywhere")
    store.save("reference", "ci-dashboard", "link to the ci dashboard", "https://ci")
    facts = store.recall("how do we deploy prod", k=1)
    assert [f.name for f in facts] == ["deploy-command"]
    assert "last_recalled: '2026-08-06'" in (store.root / "facts" / "deploy-command.md").read_text()


def test_recall_no_match_returns_empty(store):
    store.save("project", "deploy-command", "how we deploy to prod", "x")
    assert store.recall("quantum flowers") == []


def test_lint_passes_under_budget_and_fails_over(tmp_path):
    store = MemoryStore(tmp_path / "mem", index_budget=100, today=lambda: "2026-08-06")
    store.lint()  # empty store is fine
    store.save("project", "ok-fact", "short", "b")
    store.lint()
    # bypass save() to simulate drift: shrink budget after the fact
    store.index_budget = 10
    with pytest.raises(MemoryBudgetExceeded):
        store.lint()


def test_compact_archives_least_recently_recalled(tmp_path):
    store = MemoryStore(tmp_path / "mem", index_budget=100_000, today=lambda: "2026-08-06")
    store.save("project", "old-fact", "stale unrelated alpha", "a")
    store.save("project", "hot-fact", "actively used beta topic", "b")
    store.recall("actively used beta topic")  # stamps hot-fact only
    store.index_budget = len("- [[hot-fact]] (project) — actively used beta topic\n".encode()) + 5
    archived = store.compact()
    assert archived == ["old-fact"]
    assert (store.root / "archive" / "old-fact.md").exists()
    assert not (store.root / "facts" / "old-fact.md").exists()
    store.lint()


def test_lint_catches_drifted_frontmatter(tmp_path):
    store = MemoryStore(tmp_path / "mem", today=lambda: "2026-08-06")
    # Write a drifted fact file with invalid frontmatter (empty, so yaml.safe_load returns None)
    (store.root / "facts" / "drifted.md").write_text("---\n---\n\nbody\n")
    with pytest.raises(MemoryValidationError, match="frontmatter is not a mapping"):
        store.lint()


def test_recall_ignores_type_token(store):
    store.save("user", "vi-config", "text editor configuration", "vim config file")
    # Query for "user" should not match because type is not scored, only name+description
    assert store.recall("user") == []


def test_create_false_touches_nothing_and_recall_is_empty(tmp_path):
    root = tmp_path / "absent"
    store = MemoryStore(root, create=False)
    assert not root.exists()
    assert store.recall("anything") == []
    assert not root.exists()  # recall on a missing store creates nothing either


def test_save_creates_dirs_lazily_for_create_false_store(tmp_path):
    root = tmp_path / "lazy"
    store = MemoryStore(root, create=False)
    store.save("project", "deploy-cmd", "how to deploy", "make ship")
    assert (root / "facts" / "deploy-cmd.md").exists()
    assert (root / "archive").is_dir()


def test_recall_stamp_false_leaves_files_unchanged(tmp_path):
    store = MemoryStore(tmp_path / "m", today=lambda: "2026-08-07")
    store.save("project", "deploy-cmd", "how to deploy", "make ship")
    before = (tmp_path / "m" / "facts" / "deploy-cmd.md").read_text()
    hits = store.recall("deploy", stamp=False)
    assert [f.name for f in hits] == ["deploy-cmd"]
    assert (tmp_path / "m" / "facts" / "deploy-cmd.md").read_text() == before


def test_public_save_recall_round_trip(tmp_path):
    memory = Memory(store=tmp_path)
    reply = memory.save("project", "db-port", "postgres port", "The port is 5433.")
    assert reply == "saved 'db-port'"
    out = memory.recall("postgres port")
    assert "5433" in out


def test_private_aliases_delegate_to_public(tmp_path):
    memory = Memory(store=tmp_path)
    assert memory._save.__func__ is Memory.save
    assert memory._recall.__func__ is Memory.recall


def test_agent_setup_and_mcp_dispatch_honor_save_override(tmp_path):
    """setup()/mcpserver must register the public names, not the aliases."""
    calls = []

    class Probe(Memory):
        def save(self, type, name, description, body, links=None):
            calls.append(name)
            return "ok"

    probe = Probe(store=tmp_path)

    class FakeAgent:
        def __init__(self):
            self.tools = []

        def register_tool(self, tooldef):
            self.tools.append(tooldef)

        def add_system(self, text):
            pass

    agent = FakeAgent()
    probe.setup(agent)
    save_handler = next(t.handler for t in agent.tools if t.tool.name == "memory_save")
    save_handler("project", "x", "d", "b")
    assert calls == ["x"]
