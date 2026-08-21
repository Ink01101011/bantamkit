import itertools
import os
import time
from datetime import date, datetime
from pathlib import Path

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


# ---- compaction: the remedy the budget error names ----
#
# The node this block replaces, `test_compact_archives_least_recently_recalled`, was
# the ONLY node in the whole suite that called `compact()` (1 of 1459 went red when the
# sort key was flipped). It seeded its "stale" fact as never-recalled, so it asserted
# the very conflation this block exists to break: it could not tell a fact nobody has
# wanted in months from one written seconds ago, because both were `last_recalled: None`.
# It is rewritten, not re-asserted, with the third case added.

# Three roles, three names of EQUAL length so every index line is the same size and the
# budget arithmetic below does not depend on which name drew which role. Every test that
# asks "which fact gets evicted" sweeps the assignment over all six permutations, so an
# answer the alphabetical tiebreak produced by luck cannot pass.
COMPACT_NAMES = ("aaa-fact", "mmm-fact", "zzz-fact")
ROLE_ORDER = ("hot", "old", "new")
NAME_ASSIGNMENTS = list(itertools.permutations(COMPACT_NAMES))


def _describe(name: str) -> str:
    """A description unique to `name`, same byte length for every name, pairwise below
    the duplicate threshold (jaccard 1/3 against any sibling)."""
    return f"subject {name[0] * 24}"


def _seed_three_roles(root, roles):
    """A store holding one recalled fact, one never-recalled OLD fact, one never-recalled
    BRAND-NEW fact. HOT and OLD are created on the SAME day and differ only in that HOT
    was recalled, so nothing but the recall stamp can separate them."""
    store = MemoryStore(root, index_budget=100_000, today=lambda: "2026-01-05")
    for role in ("hot", "old"):
        store.save("project", roles[role], _describe(roles[role]), role)
    store._today = lambda: "2026-08-20"
    store.recall(roles["hot"][0] * 24)  # the token unique to HOT: stamps HOT and nothing else
    store._today = lambda: "2026-08-21"
    store.save("project", roles["new"], _describe(roles["new"]), "new")
    return store


def _line_size(store, name):
    fact = next(f for f in store._facts() if f.name == name)
    return len(store._index_line(fact).encode())


@pytest.mark.parametrize("names", NAME_ASSIGNMENTS)
def test_compact_evicts_the_old_unrecalled_fact_not_the_brand_new_one(tmp_path, names):
    """P2/P4: recalled-recently, never-recalled-and-old, never-recalled-and-brand-new are
    three states, not two. One slot to free must take the OLD one."""
    roles = dict(zip(ROLE_ORDER, names, strict=True))
    store = _seed_three_roles(tmp_path / "mem", roles)
    line = _line_size(store, roles["old"])
    assert {_line_size(store, n) for n in names} == {line}, "fixture must keep lines equal"

    # Three lines of budget, one line reserved: the target is two lines, so exactly one
    # fact must go. `reserve` is passed rather than defaulted, so this node fails only on
    # the ORDER of eviction and never on the reserve policy.
    store.index_budget = 3 * line
    result = store.compact(reserve=line)

    assert result.names == [roles["old"]]
    assert (store.root / "archive" / f"{roles['old']}.md").exists()
    assert not (store.root / "facts" / f"{roles['old']}.md").exists()
    assert sorted(f.name for f in store._facts()) == sorted([roles["hot"], roles["new"]])
    store.lint()


@pytest.mark.parametrize("names", NAME_ASSIGNMENTS)
def test_compact_takes_the_brand_new_fact_last_of_all_three(tmp_path, names):
    """Two slots to free orders the whole set: OLD, then HOT, and the fact written today
    is the last thing standing. Under the old key it was the FIRST thing evicted."""
    roles = dict(zip(ROLE_ORDER, names, strict=True))
    store = _seed_three_roles(tmp_path / "mem", roles)
    line = _line_size(store, roles["old"])

    store.index_budget = 2 * line  # target of one line: two of the three must go
    result = store.compact(reserve=line)

    assert result.names == [roles["old"], roles["hot"]]
    assert [f.name for f in store._facts()] == [roles["new"]]


@pytest.mark.parametrize("budget", [512, 1024, 2048, 4096])
@pytest.mark.parametrize("desc_len", [10, 40, 120])
def test_compact_frees_room_in_the_state_the_budget_error_leaves_behind(
    tmp_path, budget, desc_len
):
    """P1, the kill finding, swept over budget size and index-line length.

    `save` rolls its fact back before raising, so the caller reaches the remedy with the
    index already UNDER budget. Compacting to merely-fits archives nothing there and the
    retry raises identically — measured on the real 20-fact store as `compact() -> []`
    three times in a row. The property: in that exact state compaction must free
    something, and the SAME save that raised must then succeed with no second compact.
    """
    store = MemoryStore(tmp_path / "mem", index_budget=budget, today=lambda: "2026-08-21")
    filler = "y" * desc_len
    n = 0
    while True:
        name, description = f"fact-{n}", f"w{n} {filler}"
        try:
            store.save("project", name, description, "b")
        except MemoryBudgetExceeded:
            break
        n += 1
        assert n < 500, "budget never reached"
    assert n >= 2, "sweep point too small to be a compaction test"

    over_budget_save = (name, description)
    assert len(store.index_text().encode()) <= budget, "the failed save must have rolled back"

    result = store.compact()
    assert result.archived, "compaction in the post-rollback state must free something"
    assert result.index_after < budget, "merely-fitting leaves the caller in a retry loop"
    assert result.index_after <= result.target

    store.save("project", over_budget_save[0], over_budget_save[1], "b")  # must not raise
    store.lint()


@pytest.mark.parametrize("budget", [512, 1024, 2048, 4096])
def test_compact_is_idempotent(tmp_path, budget):
    """A second call must archive nothing: the reserve is recomputed from the survivors,
    so compaction cannot walk a store down to empty by being called repeatedly."""
    store = MemoryStore(tmp_path / "mem", index_budget=budget, today=lambda: "2026-08-21")
    n = 0
    while True:
        try:
            store.save("project", f"fact-{n}", f"w{n} {'y' * 40}", "b")
        except MemoryBudgetExceeded:
            break
        n += 1
    first = store.compact()
    assert first.archived
    for _ in range(3):
        again = store.compact()
        assert again.archived == []
        assert again.index_after == first.index_after


def test_compact_result_says_what_the_caller_lost(tmp_path):
    """P3: archiving stays a one-way MOVE, so the return value has to carry what left.
    `archive/` is a directory the calling model never reads."""
    store = MemoryStore(tmp_path / "mem", index_budget=100_000, today=lambda: "2026-01-05")
    store.save("project", "gone-fact", "an alpha subject nobody wants", "body one")
    store.save("user", "kept-fact", "a beta topic still in use", "body two")
    store._today = lambda: "2026-08-21"
    store.recall("beta topic still in use")
    kept = _line_size(store, "kept-fact")
    lost = _line_size(store, "gone-fact")
    store.index_budget = kept + lost + max(kept, lost) - 1

    result = store.compact(reserve=max(kept, lost))

    assert result.names == ["gone-fact"]
    (archived,) = result.archived
    assert archived.type == "project"
    assert archived.description == "an alpha subject nobody wants"
    assert archived.index_bytes == lost
    assert archived.last_recalled is None and archived.created == "2026-01-05"
    assert result.index_before - result.index_after == lost
    assert result.headroom == result.budget - result.index_after
    # one-way, but not gone: the file is readable where the result says it is
    assert (Path(result.archive_dir) / "gone-fact.md").exists()
    assert store.archived() == ["gone-fact"]


def test_restore_brings_an_archived_fact_back_into_recall(tmp_path):
    store = MemoryStore(tmp_path / "mem", index_budget=100_000, today=lambda: "2026-01-05")
    store.save("project", "gone-fact", "an alpha subject nobody wants", "the body")
    store.save("user", "kept-fact", "a beta topic still in use", "b")
    store._today = lambda: "2026-08-21"
    store.recall("beta topic still in use")
    gone = _line_size(store, "gone-fact")
    store.index_budget = _line_size(store, "kept-fact") + gone - 1
    assert store.compact(reserve=gone).names == ["gone-fact"]
    assert store.recall("alpha subject nobody wants") == []

    store.index_budget = 100_000
    store.restore("gone-fact")

    assert store.archived() == []
    assert [f.body for f in store.recall("alpha subject nobody wants")] == ["the body"]


def test_restore_refuses_over_budget_and_leaves_the_store_untouched(tmp_path):
    store = MemoryStore(tmp_path / "mem", index_budget=100_000, today=lambda: "2026-01-05")
    store.save("project", "gone-fact", "an alpha subject nobody wants", "a")
    store.save("user", "kept-fact", "a beta topic still in use", "b")
    store._today = lambda: "2026-08-21"
    store.recall("beta topic still in use")
    gone = _line_size(store, "gone-fact")
    store.index_budget = _line_size(store, "kept-fact") + gone - 1
    assert store.compact(reserve=gone).names == ["gone-fact"]
    before = store.index_text()

    with pytest.raises(MemoryBudgetExceeded):
        store.restore("gone-fact")

    assert store.index_text() == before
    assert store.archived() == ["gone-fact"]
    assert not (store.root / "facts" / "gone-fact.md").exists()


@pytest.mark.parametrize("op", ["save", "compact", "restore"])
def test_the_index_file_on_disk_tracks_the_facts(tmp_path, op):
    """FOUND BY MUTATION, not by design: deleting `_rebuild_index()` from `compact()` left
    the whole suite green.

    Nothing in the runtime reads `index.md` back — `index_text()` recomputes it from
    `facts/` every time — so every other node checks the recomputation and none checks the
    file. `docs/memory.md` promises the file is "regenerated on every write", and a stale
    `index.md` is what a human or a model tailing the store actually reads. All three
    writers are swept: `save` had the hole too, and so did `restore`.
    """
    store = MemoryStore(tmp_path / "mem", index_budget=100_000, today=lambda: "2026-01-05")
    store.save("project", "gone-fact", "an alpha subject nobody wants", "a")
    store.save("user", "kept-fact", "a beta topic still in use", "b")
    store._today = lambda: "2026-08-21"
    store.recall("beta topic still in use")
    if op != "save":
        gone = _line_size(store, "gone-fact")
        store.index_budget = _line_size(store, "kept-fact") + gone - 1
        assert store.compact(reserve=gone).names == ["gone-fact"]
    if op == "restore":
        store.index_budget = 100_000
        store.restore("gone-fact")

    on_disk = (store.root / "index.md").read_text()
    assert on_disk == store.index_text()
    assert "kept-fact" in on_disk
    assert ("gone-fact" in on_disk) is (op != "compact")


def test_restore_of_an_unknown_or_live_name_is_a_validation_error(tmp_path):
    store = MemoryStore(tmp_path / "mem", today=lambda: "2026-08-21")
    store.save("project", "live-fact", "a subject in use", "b")
    with pytest.raises(MemoryValidationError, match="no archived fact"):
        store.restore("never-existed")
    (store.root / "archive" / "live-fact.md").write_text("---\nname: live-fact\n---\n\nb\n")
    with pytest.raises(MemoryValidationError, match="already live"):
        store.restore("live-fact")


# ---- `created`: the field that did not exist, and the stores already on disk ----


@pytest.mark.parametrize(
    "stale_name,fresh_name", [("aaa-fact", "zzz-fact"), ("zzz-fact", "aaa-fact")]
)
def test_a_fact_saved_before_created_existed_is_dated_by_its_file_not_evicted_first(
    tmp_path, stale_name, fresh_name
):
    """Migration: every store already on disk was written without `created`. Defaulting
    those to the empty string would make the entire pre-existing store maximally stale
    and evict it first, which is the same conflation in a new costume. The file's own
    mtime is the date it was last written, so it is the fallback — no migration pass over
    anybody's store, and the next write persists the value into the frontmatter.

    Swept over which name sorts first so the alphabetical tiebreak cannot supply the answer.
    """
    store = MemoryStore(tmp_path / "mem", index_budget=100_000, today=lambda: "2026-08-21")
    for name in (stale_name, fresh_name):
        legacy = (
            f"---\nname: {name}\ndescription: {_describe(name)}\n"
            f"type: project\nlast_recalled: null\nlinks: []\n---\n\nbody\n"
        )
        (store.root / "facts" / f"{name}.md").write_text(legacy)
        assert "created" not in legacy
    old = time.mktime(datetime(2025, 3, 4).timetuple())
    os.utime(store.root / "facts" / f"{stale_name}.md", (old, old))

    facts = {f.name: f for f in store._facts()}
    assert facts[stale_name].created == "2025-03-04"
    assert facts[fresh_name].created == date.today().isoformat()

    store.index_budget = 2 * _line_size(store, stale_name)
    assert store.compact(reserve=_line_size(store, stale_name)).names == [stale_name]


def test_created_is_persisted_on_the_next_write_of_a_legacy_fact(tmp_path):
    store = MemoryStore(tmp_path / "mem", today=lambda: "2026-08-21")
    (store.root / "facts" / "legacy-fact.md").write_text(
        "---\nname: legacy-fact\ndescription: an alpha subject\n"
        "type: project\nlast_recalled: null\nlinks: []\n---\n\nbody\n"
    )
    old = time.mktime(datetime(2025, 3, 4).timetuple())
    os.utime(store.root / "facts" / "legacy-fact.md", (old, old))

    store.recall("alpha subject")  # any write of the fact carries the derived date through

    text = (store.root / "facts" / "legacy-fact.md").read_text()
    assert "created: '2025-03-04'" in text
    # and it survives an mtime the migration would now read differently
    os.utime(store.root / "facts" / "legacy-fact.md", None)
    assert next(iter(store._facts())).created == "2025-03-04"


def test_updating_a_fact_under_the_same_name_does_not_reset_created(tmp_path):
    """A re-save must not launder a stale fact into a fresh one."""
    store = MemoryStore(tmp_path / "mem", today=lambda: "2026-01-05")
    store.save("project", "db-port", "port the database listens on", "5432")
    store._today = lambda: "2026-08-21"
    store.save("project", "db-port", "port the database listens on", "6543")
    assert next(iter(store._facts())).created == "2026-01-05"


def test_compact_never_surrenders_more_than_half_the_budget_to_headroom(tmp_path):
    """The reserve is data-driven, so one enormous description must not let it eat the
    store. Swept implicitly by the ratio: one line far longer than half the budget."""
    store = MemoryStore(tmp_path / "mem", index_budget=100_000, today=lambda: "2026-08-21")
    store.save("project", "huge-fact", "alpha " + "h" * 400, "a")
    store.save("project", "tiny-fact", "beta topic", "b")
    huge = _line_size(store, "huge-fact")
    store.index_budget = huge + 20  # a full reserve would be `huge`, i.e. a negative target
    result = store.compact()
    assert result.reserve == store.index_budget // 2
    assert result.target == store.index_budget - store.index_budget // 2 > 0


def test_memory_component_compact_reports_the_names_and_the_arithmetic(tmp_path):
    """P3 at the surface a caller actually holds: `Memory`, not `Memory.store`."""
    memory = Memory(store=tmp_path, index_budget=100_000)
    memory.store._today = lambda: "2026-01-05"
    memory.save("project", "gone-fact", "an alpha subject nobody wants", "a")
    memory.save("user", "kept-fact", "a beta topic still in use", "b")
    memory.store._today = lambda: "2026-08-21"
    memory.recall("beta topic still in use")
    kept = _line_size(memory.store, "kept-fact")
    gone = _line_size(memory.store, "gone-fact")
    memory.store.index_budget = kept + gone + max(kept, gone) - 1

    reply = memory.compact(reserve=max(kept, gone))

    assert "gone-fact" in reply and "an alpha subject nobody wants" in reply
    assert "kept-fact" not in reply
    assert "NOT deleted" in reply and str(memory.store.root / "archive") in reply
    assert memory.compact().startswith("nothing archived")


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
            self.scopes = []

        def register_tool(self, tooldef):
            self.tools.append(tooldef)

        def add_batch_scope(self, scope):
            self.scopes.append(scope)

        def add_system(self, text):
            pass

    agent = FakeAgent()
    probe.setup(agent)
    save_handler = next(t.handler for t in agent.tools if t.tool.name == "memory_save")
    save_handler("project", "x", "d", "b")
    assert calls == ["x"]


# ---- RB-P1 P-B: batch-scoped read isolation ----


def test_snapshot_pins_the_read_set_for_the_scope(store):
    store.save("project", "payments-api-owner", "which team owns the payments api", "team Atlas")
    with store.snapshot():
        before = store.recall("who owns the payments api", k=1)
        store.save("project", "payments-api-owner", "which team owns the payments api", "finance")
        after = store.recall("who owns the payments api", k=1)
    assert before[0].body == "team Atlas"
    assert after[0].body == "team Atlas", "a write inside the scope must not be read back in it"


def test_snapshot_does_not_hide_the_write_from_the_next_scope(store):
    store.save("project", "payments-api-owner", "which team owns the payments api", "team Atlas")
    with store.snapshot():
        store.save("project", "payments-api-owner", "which team owns the payments api", "finance")
    assert store.recall("who owns the payments api", k=1)[0].body == "finance"


def test_snapshot_leaves_save_semantics_untouched(store):
    """Same-name-is-update still holds inside the scope: one file, latest content."""
    store.save("project", "db-port", "port the database listens on", "5432")
    with store.snapshot():
        result = store.save("project", "db-port", "port the database listens on", "6543")
    assert result.status == "saved"
    assert sorted(p.name for p in (store.root / "facts").glob("*.md")) == ["db-port.md"]
    assert "6543" in (store.root / "facts" / "db-port.md").read_text()


def test_snapshot_stamp_never_writes_pinned_content_back(store):
    """The reverse poisoning: stamping a pinned hit must not revert the live file."""
    store.save("project", "db-port", "port the database listens on", "5432")
    with store.snapshot():
        store.save("project", "db-port", "port the database listens on", "6543")
        store.recall("database port", k=1)
    text = (store.root / "facts" / "db-port.md").read_text()
    assert "6543" in text and "5432" not in text
    assert "last_recalled: '2026-08-06'" in text


def test_snapshot_skips_stamping_a_fact_the_scope_deleted(store):
    store.save("project", "db-port", "port the database listens on", "5432")
    with store.snapshot():
        (store.root / "facts" / "db-port.md").unlink()
        assert store.recall("database port", k=1)[0].body == "5432"
    assert not (store.root / "facts" / "db-port.md").exists()


def test_snapshot_restores_live_reads_on_exit_even_after_an_error(store):
    store.save("project", "db-port", "port the database listens on", "5432")
    with pytest.raises(RuntimeError):
        with store.snapshot():
            raise RuntimeError("boom")
    store.save("project", "db-port", "port the database listens on", "6543")
    assert store.recall("database port", k=1)[0].body == "6543"


def test_snapshot_of_an_unreadable_store_falls_back_to_live_reads(tmp_path):
    """Pinning is an isolation nicety; a corrupt store must still raise where it always did."""
    store = MemoryStore(tmp_path / "mem")
    (store.root / "facts" / "broken.md").write_text("no frontmatter at all")
    with store.snapshot():
        with pytest.raises(MemoryValidationError):
            store.recall("anything")


def test_nested_snapshot_keeps_the_outermost_pin(store):
    store.save("project", "db-port", "port the database listens on", "5432")
    with store.snapshot():
        store.save("project", "db-port", "port the database listens on", "6543")
        with store.snapshot():
            assert store.recall("database port", k=1)[0].body == "5432"
        assert store.recall("database port", k=1)[0].body == "5432"
