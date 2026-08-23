import itertools
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pytest

import bantamkit
from bantamkit.memory import (
    DEFAULT_INDEX_BUDGET,
    Memory,
    MemoryBudgetExceeded,
    MemoryStore,
    MemoryValidationError,
    SaveResult,
)
from bantamkit.memory.__main__ import main as memory_main


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
    text = fact_file.read_text(encoding="utf-8")
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
    assert "new" in (store.root / "facts" / "deploy-command.md").read_text(encoding="utf-8")


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
    assert "last_recalled: '2026-08-06'" in (store.root / "facts" / "deploy-command.md").read_text(
        encoding="utf-8"
    )


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

    on_disk = (store.root / "index.md").read_text(encoding="utf-8")
    assert on_disk == store.index_text()
    assert "kept-fact" in on_disk
    assert ("gone-fact" in on_disk) is (op != "compact")


def test_restore_of_an_unknown_or_live_name_is_a_validation_error(tmp_path):
    store = MemoryStore(tmp_path / "mem", today=lambda: "2026-08-21")
    store.save("project", "live-fact", "a subject in use", "b")
    with pytest.raises(MemoryValidationError, match="no archived fact"):
        store.restore("never-existed")
    (store.root / "archive" / "live-fact.md").write_text(
        "---\nname: live-fact\n---\n\nb\n", encoding="utf-8"
    )
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
        (store.root / "facts" / f"{name}.md").write_text(legacy, encoding="utf-8")
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
        "type: project\nlast_recalled: null\nlinks: []\n---\n\nbody\n",
        encoding="utf-8",
    )
    old = time.mktime(datetime(2025, 3, 4).timetuple())
    os.utime(store.root / "facts" / "legacy-fact.md", (old, old))

    store.recall("alpha subject")  # any write of the fact carries the derived date through

    text = (store.root / "facts" / "legacy-fact.md").read_text(encoding="utf-8")
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
    (store.root / "facts" / "drifted.md").write_text("---\n---\n\nbody\n", encoding="utf-8")
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
    before = (tmp_path / "m" / "facts" / "deploy-cmd.md").read_text(encoding="utf-8")
    hits = store.recall("deploy", stamp=False)
    assert [f.name for f in hits] == ["deploy-cmd"]
    assert (tmp_path / "m" / "facts" / "deploy-cmd.md").read_text(encoding="utf-8") == before


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
    assert "6543" in (store.root / "facts" / "db-port.md").read_text(encoding="utf-8")


def test_snapshot_stamp_never_writes_pinned_content_back(store):
    """The reverse poisoning: stamping a pinned hit must not revert the live file."""
    store.save("project", "db-port", "port the database listens on", "5432")
    with store.snapshot():
        store.save("project", "db-port", "port the database listens on", "6543")
        store.recall("database port", k=1)
    text = (store.root / "facts" / "db-port.md").read_text(encoding="utf-8")
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
    (store.root / "facts" / "broken.md").write_text("no frontmatter at all", encoding="utf-8")
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


# ---------------------------------------------------------------------------
# J37: a store that cannot be listed is not a store with nothing in it.
#
# `Path.glob` swallows the OSError its own directory scan raises and yields
# nothing, so `MemoryStore._facts` could not tell "empty" from "unreadable" —
# and `save` writes `index.md` from whatever `_facts` returned. MEASURED
# 2026-08-23 on a COPY of the live 65-fact project store (never on the store
# itself; this defect destroys indexes), with `facts/` at 0o311 — writable and
# traversable, not listable:
#
#     glob("*.md") -> []                       PermissionError swallowed
#     save(...)    -> SaveResult(status='saved')
#     BEFORE  facts: 65   index.md: 13,472 bytes / 65 lines
#     AFTER   facts: 66   index.md:      0 bytes /  0 lines
#
# The fact files survived. The index every reader loads did not. This is the
# same conflation `layers.count_facts` removed one layer out, reached from
# underneath: there, an unreadable store came back `state="empty"`.
# ---------------------------------------------------------------------------


def _three_facts(tmp_path):
    store = MemoryStore(tmp_path / "mem", today=lambda: "2026-08-06")
    for i in range(3):
        store.save("project", f"fact-{i}", f"w{i}a w{i}b w{i}c w{i}d", f"body {i}")
    return store


def test_an_unlistable_store_is_never_reported_empty_and_never_rewrites_the_index(tmp_path):
    """The measured wipe, reproduced on a store built here rather than on anyone's real one.

    NOT a `windows_cannot_construct` skipif, following the ruling already made for
    `test_a_root_that_denies_listing_is_unreadable_not_absent` in
    test_memory_store_tripwire.py: the platform question is MEASURED rather than
    asserted by a mark. The node puts the directory into the state, probes whether the
    OS actually honoured it, and reports honestly when it did not — which covers
    Windows (where `chmod` does not restrict a directory listing) and any uid that
    bypasses the mode bits, in one mechanism, without adding a fifth entry to
    `_WINDOWS_ONLY_SKIPS` in a module `_windows_only_skip_conditions()` does not scan.
    What runs on all four CI jobs instead is
    `test_a_facts_path_that_is_not_a_directory_is_unreadable_not_empty` and
    `test_a_listing_that_fails_stops_save_before_it_writes_anything` below, which reach
    the same property through shapes every platform can be put into.
    """
    store = _three_facts(tmp_path)
    index = store.root / "index.md"
    before = index.read_bytes()
    assert before.count(b"\n") == 3

    facts = store.root / "facts"
    os.chmod(facts, 0o311)
    try:
        try:
            list(facts.iterdir())
        except OSError:
            constructed = True
        else:
            constructed = False
        if constructed:
            with pytest.raises(MemoryValidationError) as e:
                store.save("project", "probe", "an entirely unrelated probe subject", "body")
            message = str(e.value)
    finally:
        os.chmod(facts, 0o755)

    if not constructed:
        pytest.skip(
            "this platform lets a 0o311 directory be listed (Windows, where chmod is a "
            "no-op on a directory, or a uid that bypasses the mode bits), so the "
            "scenario cannot be constructed and this run FAILS TO MEASURE that a save "
            "into a writable-but-unlistable store raises instead of rewriting index.md "
            "from an empty listing. The two nodes below pin the same property through "
            "shapes that are constructible everywhere."
        )

    assert str(facts) in message
    assert "ermission" in message
    assert index.read_bytes() == before, "index.md was rebuilt from a listing that had failed"
    assert not (facts / "probe.md").exists(), "save wrote a fact before it could read the store"
    assert sorted(p.name for p in facts.iterdir()) == ["fact-0.md", "fact-1.md", "fact-2.md"]


def test_a_facts_path_that_is_not_a_directory_is_unreadable_not_empty(tmp_path):
    """The same property through a shape all four CI jobs can construct.

    `save` never reaches the listing here — `_ensure_dirs` raises FileExistsError on
    the `mkdir` first — so this goes in through the readers, which is where a wrong
    "empty" is quietest: `recall` answered `[]` and `index_text` answered `""`.

    The errno differs by platform (POSIX reports ENOTDIR; a Windows directory scan of
    a non-directory reports the path as not found), which is exactly why `_fact_paths`
    keys "first run" on whether anything is at the path rather than on the errno.
    """
    root = tmp_path / "mem"
    root.mkdir()
    (root / "facts").write_text("this is not a facts directory\n", encoding="utf-8")
    store = MemoryStore(root, create=False)

    for call in (lambda: store.recall("anything"), store.index_text, store.lint):
        with pytest.raises(MemoryValidationError) as e:
            call()
        assert str(root / "facts") in str(e.value)


def test_a_listing_that_fails_stops_save_before_it_writes_anything(tmp_path, monkeypatch):
    """The ordering claim, run rather than assumed, and run on every platform.

    `save` reads the store in its duplicate check BEFORE it writes. With the listing
    blind that check passed vacuously; with the listing honest the whole operation
    fails before it touches disk, so there is no half-written state to roll back.

    Fault injection stands in for the real 0o311 construction only because that
    construction is POSIX-only — `PermissionError` from `os.scandir` is precisely what
    the kernel raises there, and the node above runs the real thing wherever the OS
    honours the mode bits.
    """
    store = _three_facts(tmp_path)
    facts = store.root / "facts"
    index = store.root / "index.md"
    before = index.read_bytes()
    real_scandir = os.scandir

    def denied(path, *args, **kwargs):
        if Path(path) == facts:
            raise PermissionError(13, "Permission denied")
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", denied)
    with pytest.raises(MemoryValidationError) as e:
        store.save("project", "fact-0", "w0a w0b w0c w0d", "a rewrite of an existing fact")
    monkeypatch.undo()

    assert "Permission denied" in str(e.value)
    assert index.read_bytes() == before
    assert sorted(p.name for p in facts.iterdir()) == ["fact-0.md", "fact-1.md", "fact-2.md"]
    assert "a rewrite of an existing fact" not in (facts / "fact-0.md").read_text(
        encoding="utf-8"
    )


def test_a_missing_facts_directory_is_a_first_run_and_not_an_error(tmp_path):
    """The other half: "no such file" and "permission denied" are not one sentence.

    `_ensure_dirs`, the designate path and `create=False` all depend on this staying
    an empty answer, so the raise above must not have been bought by making a first
    run loud.
    """
    store = MemoryStore(tmp_path / "never-made", create=False)
    assert store._fact_paths() == []
    assert store.recall("anything") == []
    assert store.index_text() == ""
    assert not (tmp_path / "never-made").exists()


def _write_shapes(directory, names):
    """Create every name the filesystem will accept, and hand back both lists.

    `*.md` is in the shape list on purpose — it is the name most likely to make two
    implementations of "which files are facts" disagree — and `*` is reserved in a
    DOS/Win32 filename, so `open()` refuses it there. Measured 2026-08-23 on this
    machine against a filesystem that enforces that rule (a FAT32 image: `dd`,
    `mkfs.vfat`, `mount -o loop`, in a Linux container): `Path("*.md").write_text("x")`
    raised `OSError [Errno 22] Invalid argument`, while `real.md`, `adir.md`,
    `spaced name.md` and `UPPER.MD` were all created. `ci.yml` runs this suite on
    `windows-latest` for py3.11 and py3.12, where that same rule is enforced by the
    Win32 layer for every filesystem — so a hardcoded population count here is a red
    matrix, and a shape list built with no record of what was refused is a claim about
    seventeen shapes silently made about fifteen.
    """
    made, refused = [], []
    for name in names:
        try:
            (directory / name).write_text("x", encoding="utf-8")
        except (OSError, ValueError):
            refused.append(name)
        else:
            made.append(name)
    return made, refused


_GLOB_SHAPES = (
    "real.md",
    ".hidden.md",
    ".md",
    "UPPER.MD",
    "*.md",
    "notes.txt",
    "no-extension",
    "spaced name.md",
    "unicode-ñ.md",
    "fact-0.md.tmp",
)
# Nothing else in the list uses a character Win32 reserves, so `*.md` is the one shape
# allowed to go missing — and it has to go missing NAMED. A node that quietly tests one
# shape fewer on half the CI matrix still carries the full claim in its docstring.
_WIN32_CANNOT_SPELL = {"*.md"}


def _assert_only_win32_dropped_a_shape(refused):
    assert set(refused) <= _WIN32_CANNOT_SPELL, f"a shape went missing unnamed: {refused}"
    assert refused == [] or os.name == "nt", (
        f"only a DOS/Win32 name rule refuses these, and this is {os.name}: {refused}"
    )


def test_a_readable_store_lists_exactly_what_glob_listed(tmp_path):
    """The counted set does not change. Seventeen shapes, over the binding layer's sixteen.

    A raise bought by quietly changing which files count as facts would be a worse
    defect than the one it fixes, so this compares the new listing against `glob("*.md")`
    itself rather than against a hand-written expectation — including the shapes that
    make the two implementations differ if they are going to: a bare `.md`, an uppercase
    `.MD` (pathlib and `fnmatch.fnmatch` are both case-sensitive off Windows and both
    case-insensitive on it), a file literally named `*.md`, a directory named `*.md`,
    and three symlink flavours.

    Sixteen of the seventeen are constructible everywhere. The seventeenth, the file
    literally named `*.md`, is not: see `_write_shapes`. On Windows this node therefore
    tests sixteen, and `_assert_only_win32_dropped_a_shape` is what keeps that a
    measured platform difference rather than a silently weaker test — the equality
    against `glob("*.md")` is self-adjusting and is asserted unchanged on both.
    """
    facts = tmp_path / "mem" / "facts"
    facts.mkdir(parents=True)
    made, refused = _write_shapes(facts, _GLOB_SHAPES)
    (facts / "adir.md").mkdir()
    (facts / "sub").mkdir()
    (facts / "sub" / "nested.md").write_text("x", encoding="utf-8")

    symlinks = 0
    for link, target in (
        ("link-to-file.md", facts / "real.md"),
        ("link-to-txt.md", facts / "notes.txt"),
        ("link-to-dir.md", facts / "sub"),
        ("dangling.md", facts / "gone.md"),
    ):
        try:
            (facts / link).symlink_to(target)
        except (OSError, NotImplementedError):  # pragma: no cover - Windows without privilege
            break
        symlinks += 1

    store = MemoryStore(tmp_path / "mem", create=False)
    assert store._fact_paths() == sorted(facts.glob("*.md"))
    # The population is pinned so a later edit cannot buy agreement by dropping shapes:
    # every name the filesystem accepted, plus `adir.md` and `sub/`, plus whatever
    # symlinks this platform allowed. Measured on macOS/APFS: nothing refused, so 12
    # top-level entries and 4 symlinks, of which 11 of the 17 match `*.md` — `UPPER.MD`
    # matches under neither implementation, so the case rule agrees as well as the name
    # rule. On Windows the arithmetic drops by one and the named-shape floor below is
    # what stops that from being a test that quietly checks less.
    _assert_only_win32_dropped_a_shape(refused)
    assert len(list(facts.iterdir())) == len(made) + 2 + symlinks
    assert {"real.md", "spaced name.md", "unicode-ñ.md", "adir.md"} <= {
        p.name for p in store._fact_paths()
    }, "the shapes did not survive the filesystem"
    assert symlinks == 4 or os.name == "nt", "symlinks are constructible off Windows"


# ---------------------------------------------------------------------------
# J37/W2: the audit of who was being lied to.
#
# W1 made the FACT listing honest. This block is the enumeration of every caller
# that reached it, what each one now does, and the two callers the audit found
# still reading a directory the old way.
#
# The list was derived from `store.py` itself, and the two the brief's list did
# not name are the two that needed code, not prose:
#   * `archived()` had a second `glob("*.md")` of its own, on `archive/`.
#   * `restore()` reaches the listing through `_check_index_budget` AFTER it has
#     already moved a file, and the rollback beside it catches
#     `MemoryBudgetExceeded` only.
# ---------------------------------------------------------------------------


def _deny_scandir(monkeypatch, directory):
    """Make `os.scandir` fail for exactly one directory, on every platform.

    Fault injection rather than `chmod(0o311)` because the mode bits are a no-op on a
    Windows directory and a no-op for a uid that bypasses them. W1's
    `test_an_unlistable_store_is_never_reported_empty_and_never_rewrites_the_index`
    runs the real construction and reports honestly when the OS declines it; these
    nodes are the half that has to RUN on all four CI jobs, and `PermissionError` from
    `os.scandir` is precisely what the kernel raises for the real thing.
    """
    real_scandir = os.scandir

    def denied(path, *args, **kwargs):
        if Path(path) == Path(directory):
            raise PermissionError(13, "Permission denied")
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", denied)


def test_every_op_that_reads_the_store_refuses_to_answer_a_listing_that_failed(
    tmp_path, monkeypatch
):
    """The enumerated caller audit, as one node, so a NEW caller cannot slip past it.

    Every row reaches `_fact_paths`, directly or through `index_text`. WAS, for every
    one of them, an empty listing and a confident answer: `recall` -> `[]`, `lint` ->
    ok, `compact` -> "nothing to archive", `index_text` -> `""`, `_rebuild_index` -> a
    zero-byte `index.md` over a full one, `save` -> `status='saved'`. NOW: one sentence
    that names the path, the OS reason, and the consequence — from all nine.

    `snapshot()+recall` is in the table because the scope swallows the error at ENTRY
    on purpose; that must not become a scope in which reads answer `[]`.
    """
    store = _three_facts(tmp_path)
    facts = store.root / "facts"
    (store.root / "archive" / "put-away.md").write_text(
        "---\nname: put-away\ndescription: an archived fact\ntype: project\n---\n\nbody\n",
        encoding="utf-8",
    )
    index_before = (store.root / "index.md").read_bytes()

    def recall_inside_a_scope():
        with store.snapshot():
            return store.recall("w0a")

    ops = {
        "save": lambda: store.save("project", "probe", "an unrelated probe subject", "b"),
        "recall": lambda: store.recall("w0a"),
        "lint": store.lint,
        "compact": store.compact,
        "index_text": store.index_text,
        "restore": lambda: store.restore("put-away"),
        "_rebuild_index": store._rebuild_index,
        "_check_index_budget": store._check_index_budget,
        "snapshot()+recall": recall_inside_a_scope,
    }
    _deny_scandir(monkeypatch, facts)
    for label, op in ops.items():
        with pytest.raises(MemoryValidationError) as e:
            op()
        assert str(facts) in str(e.value), label
        assert "Permission denied" in str(e.value), label
        assert "not a store with no facts" in str(e.value), label

    # Negative controls. Breaking `facts/` must not break the other directory, and
    # nothing in the table may have written, moved or deleted anything.
    assert store.archived() == ["put-away"]
    assert (store.root / "index.md").read_bytes() == index_before
    monkeypatch.undo()
    assert sorted(p.name for p in facts.iterdir()) == ["fact-0.md", "fact-1.md", "fact-2.md"]
    assert sorted(p.name for p in (store.root / "archive").iterdir()) == ["put-away.md"]


def test_an_unlistable_archive_is_not_an_empty_archive(tmp_path, monkeypatch):
    """(a) from W1's handoff: the same defect one directory over, and the worse of the two.

    `compact()` MOVES the operator's facts into `archive/`, so `archived()` is the only
    thing in the system that says where they went. WAS, measured 2026-08-23 on a store
    that had just compacted `fact-0` out, with `archive/` at 0o311:

        archived()                          -> []
        python -m bantamkit.memory status   -> "archived: 0"      exit 0
        python -m bantamkit.memory archived -> "archived facts: 0" exit 0
        on disk                             -> archive/fact-0.md

    An operator reading that has been told their memory was deleted. NOW: a raise that
    names `archive/` and says the facts are still under it.

    The CLI half is asserted here too and it is NOT yet pretty: `_cmd_archived` and
    `_cmd_status` do not wrap `MemoryValidationError` the way `_cmd_lint` and
    `_cmd_restore` do, so the operator gets a traceback where they used to get a lie.
    That is the same state `status` and `compact` have been in since W1 and it is
    registered as a follow-up on the operator entry point; it is pinned here so the
    trade is visible rather than discovered.
    """
    store = MemoryStore(tmp_path / "mem", today=lambda: "2026-08-06")
    store.save("project", "put-away", "a fact that was compacted out", "body")
    archive = store.root / "archive"
    (store.root / "facts" / "put-away.md").rename(archive / "put-away.md")
    store._rebuild_index()
    assert store.archived() == ["put-away"]

    _deny_scandir(monkeypatch, archive)
    with pytest.raises(MemoryValidationError) as e:
        store.archived()
    assert str(archive) in str(e.value)
    assert "not an empty archive" in str(e.value)
    assert "still on disk" in str(e.value)
    assert "index.md" not in str(e.value), (
        "the facts/ consequence is not true of archive/; a wrong consequence sends "
        "the reader to the wrong file"
    )

    with pytest.raises(MemoryValidationError):
        memory_main(["archived", "--store", str(store.root)])

    # Breaking `archive/` must not break the store: a recall is still answerable.
    assert store.recall("compacted", stamp=False) == []
    assert store.index_text() == ""
    monkeypatch.undo()
    assert sorted(p.name for p in archive.iterdir()) == ["put-away.md"]


def test_an_archive_path_that_is_not_a_directory_is_unreadable_not_empty(tmp_path):
    """The same property through a shape all four CI jobs can construct.

    The errno differs by platform exactly as it does for `facts/` — POSIX ENOTDIR, a
    Windows directory scan of a non-directory reports the path as not found — which is
    why the listing keys "first run" on whether anything is AT the path.
    """
    root = tmp_path / "mem"
    (root / "facts").mkdir(parents=True)
    (root / "archive").write_text("this is not an archive directory\n", encoding="utf-8")
    store = MemoryStore(root, create=False)

    with pytest.raises(MemoryValidationError) as e:
        store.archived()
    assert str(root / "archive") in str(e.value)
    assert "not an empty archive" in str(e.value)


def test_an_absent_archive_is_an_empty_archive_and_not_an_error(tmp_path):
    """The other half, for the second directory: the raise must not be bought with noise.

    A `create=False` store makes neither directory, and a store that has never compacted
    has no `archive/` at all — `archived()` has always answered `[]` there and callers
    (`_cmd_status`, `_cmd_archived`) print that count unconditionally.
    """
    store = MemoryStore(tmp_path / "never-made", create=False)
    assert store.archived() == []
    assert not (tmp_path / "never-made").exists()


def test_a_readable_archive_lists_exactly_what_glob_listed(tmp_path):
    """The counted set of the SECOND directory does not change either.

    Same guard W1 put on `facts/`, aimed at `archive/`, because `archived()` returns
    STEMS rather than paths and a re-implementation is exactly where an off-by-one in
    the name rule hides. Compared against `glob("*.md")` itself over the shapes that
    make two implementations differ if they are going to.

    Built defensively for the same reason as the `facts/` node above: `*.md` is not a
    filename Win32 can spell, and this suite runs on `windows-latest`. What the
    platform refused is named rather than absent.
    """
    root = tmp_path / "mem"
    (root / "facts").mkdir(parents=True)
    archive = root / "archive"
    archive.mkdir()
    made, refused = _write_shapes(archive, _GLOB_SHAPES)
    (archive / "adir.md").mkdir()

    store = MemoryStore(root, create=False)
    assert store.archived() == sorted(p.stem for p in archive.glob("*.md"))
    _assert_only_win32_dropped_a_shape(refused)
    assert len(list(archive.iterdir())) == len(made) + 1, (
        "the shapes did not survive the filesystem"
    )
    assert {"real", "spaced name", "unicode-ñ", "adir"} <= set(store.archived())


def test_restore_moves_nothing_when_the_store_cannot_be_listed(tmp_path, monkeypatch):
    """`restore` is the one op that could half-complete, and this is why it lists first.

    Everything after the `rename` reaches the listing through `_check_index_budget`,
    whose raise since W1 is a `MemoryValidationError` — and the rollback beside it
    catches `MemoryBudgetExceeded` ONLY. Measured 2026-08-23 with `facts/` at 0o311
    before this node existed: `restore('put-away')` moved the file out of `archive/`,
    left it in `facts/`, raised "unreadable", never rebuilt `index.md`, and the
    docstring above it went on promising "a failed restore leaves the store exactly as
    it found it".

    `save` is immune to the same shape only by luck of ordering — its duplicate check
    lists before `_write_fact`. This asserts the OUTCOME (nothing moved), not the
    ordering statement, so a later refactor that keeps the property by another
    mechanism still passes.
    """
    store = _three_facts(tmp_path)
    facts = store.root / "facts"
    archive = store.root / "archive"
    (archive / "put-away.md").write_text(
        "---\nname: put-away\ndescription: an archived fact\ntype: project\n---\n\nbody\n",
        encoding="utf-8",
    )
    index_before = (store.root / "index.md").read_bytes()

    _deny_scandir(monkeypatch, facts)
    with pytest.raises(MemoryValidationError) as e:
        store.restore("put-away")
    monkeypatch.undo()

    assert str(facts) in str(e.value)
    assert sorted(p.name for p in archive.iterdir()) == ["put-away.md"], (
        "the fact left the archive on the strength of a listing that had failed"
    )
    assert sorted(p.name for p in facts.iterdir()) == ["fact-0.md", "fact-1.md", "fact-2.md"]
    assert (store.root / "index.md").read_bytes() == index_before

    # And the door back still opens when the store IS readable: the raise was not
    # bought by making `restore` refuse in general.
    store.restore("put-away")
    assert store.archived() == []
    assert "put-away" in store.index_text()


# ---------------------------------------------------------------------------
# J37/W4: the promise `restore` made that its code did not keep, and an OS error
# escaping a documented op.
#
# `restore` is the only op here that can half-complete, and W1 moved a read ahead
# of its `rename` to stop that. A LISTING is not enough. The read that fails after
# the move is `_check_index_budget` -> `index_text` -> `_facts`, which PARSES;
# `_fact_paths` only lists. Measured on throwaway stores, byte-identical at
# `533229c` and at `b973c32`:
#
#   facts/broken.md malformed     -> restore('put-away') took the fact OUT of
#                                    archive/, left it in facts/, raised, and never
#                                    rebuilt index.md
#   archive/put-away.md malformed -> the same, and no pre-read can see this one at
#                                    all: the file is not in facts/ yet
#
# The first is closed by widening the pre-read to `_facts()`. That refuses no
# restore that would otherwise have succeeded, because every parse the pre-read can
# fail on is one `_check_index_budget` re-runs three lines later — it converts a
# half-complete failure into a refusal, it does not create one. The second is
# reachable only after the move, so the rollback beside it had to widen too.
#
# Third: `restore` opens one named path instead of listing, deliberately, so an
# unlistable-but-traversable `archive/` still restores. But `Path.exists()` does not
# swallow EACCES, so `archive/` at 0o000 gave a raw `PermissionError` traceback out
# of `python -m bantamkit.memory restore` — measured, exit 1 with a stack trace where
# `_cmd_restore` has a sentence ready. The same hole was open on the `facts/` side
# and nobody had named it: `destination.exists()` runs BEFORE the pre-read, so the
# error W1 wrote for exactly this case never got a chance to be the one raised.
# ---------------------------------------------------------------------------


_ARCHIVED_FACT = "---\nname: put-away\ndescription: an archived fact\ntype: project\n---\n\nbody\n"


def _deny_stat(monkeypatch, path):
    """Make `os.stat` fail for exactly one path, on every platform.

    Fault injection for the same reason `_deny_scandir` above uses it: `chmod(0o000)`
    is a no-op on a Windows directory and a no-op for a uid that bypasses it, and these
    nodes have to RUN on all four CI jobs rather than skip on two. `PermissionError`
    from `os.stat` is precisely what the kernel raises for the real thing — measured
    2026-08-23 on a throwaway store with `archive/` at 0o000:
    `PermissionError: [Errno 13] Permission denied: '.../mem/archive/put-away.md'`,
    out of `Path.exists()`, three lines before any `rename`.
    """
    real_stat = os.stat

    def denied(target, *args, **kwargs):
        if isinstance(target, (str, os.PathLike)) and Path(target) == Path(path):
            raise PermissionError(13, "Permission denied")
        return real_stat(target, *args, **kwargs)

    monkeypatch.setattr(os, "stat", denied)


def test_restore_moves_nothing_when_a_fact_already_in_the_store_is_malformed(tmp_path):
    """The half-complete restore W1's listing did not close, and the reason it did not.

    `_fact_paths()` lists; it does not parse. One malformed file in `facts/` therefore
    passed the pre-read, and the raise landed on `_check_index_budget` AFTER the
    `rename` — a `MemoryValidationError`, which the rollback beside it did not catch.

    This is not a restore that used to work and now refuses: with `broken.md` on disk
    the restore fails either way, because `_check_index_budget` parses the same file.
    All that changes is whether it fails before the move or after it.
    """
    store = _three_facts(tmp_path)
    facts, archive = store.root / "facts", store.root / "archive"
    (archive / "put-away.md").write_text(_ARCHIVED_FACT, encoding="utf-8")
    (facts / "broken.md").write_text("not frontmatter at all\n", encoding="utf-8")
    index_before = (store.root / "index.md").read_bytes()

    with pytest.raises(MemoryValidationError) as e:
        store.restore("put-away")

    assert "broken.md" in str(e.value)
    assert sorted(p.name for p in archive.iterdir()) == ["put-away.md"], (
        "the fact left the archive on the strength of a read that had not parsed it"
    )
    assert not (facts / "put-away.md").exists()
    assert (store.root / "index.md").read_bytes() == index_before

    # And the door back still opens once the malformed file is gone: the refusal was
    # not bought by making `restore` refuse in general.
    (facts / "broken.md").unlink()
    store.restore("put-away")
    assert store.archived() == []
    assert "put-away" in store.index_text()


def test_restore_puts_the_archived_fact_back_when_that_fact_is_itself_malformed(tmp_path):
    """The half of the class no pre-read can reach, so the rollback has to.

    The file being restored is in `archive/` when the pre-read runs, so widening that
    read to `_facts()` cannot see it. It becomes a fact only after the `rename`, and
    the parse that rejects it is the one inside `_check_index_budget`. Measured before
    this node existed: the malformed file ended up in `facts/`, out of the archive,
    with `index.md` never rebuilt — the store left in a state the operator did not ask
    for and the docstring above `restore` said could not happen.
    """
    store = _three_facts(tmp_path)
    facts, archive = store.root / "facts", store.root / "archive"
    (archive / "put-away.md").write_text("no frontmatter here\n", encoding="utf-8")
    index_before = (store.root / "index.md").read_bytes()

    with pytest.raises(MemoryValidationError) as e:
        store.restore("put-away")

    assert "put-away.md" in str(e.value)
    assert sorted(p.name for p in archive.iterdir()) == ["put-away.md"], (
        "a restore that failed left the fact somewhere the operator did not put it"
    )
    assert sorted(p.name for p in facts.iterdir()) == ["fact-0.md", "fact-1.md", "fact-2.md"]
    assert (store.root / "index.md").read_bytes() == index_before

    # The rollback rebuilt the index from the store it restored, not from the store it
    # briefly made: a second attempt behaves identically rather than compounding.
    with pytest.raises(MemoryValidationError):
        store.restore("put-away")
    assert (store.root / "index.md").read_bytes() == index_before


def test_restore_puts_back_an_archived_name_that_turns_out_not_to_be_a_readable_file(tmp_path):
    """The same failure arriving as an OS error instead of a validation error.

    `archive/put-away.md` is a DIRECTORY here. Nothing before the `rename` can tell:
    `exists()` says yes, and the pre-read parses `facts/`, which this is not part of
    yet. The parse that rejects it is `_check_index_budget` -> `_facts` ->
    `Path.read_text`, and that raises `IsADirectoryError` on POSIX and
    `PermissionError` on Windows — an `OSError`, not a `Memory*` error.

    So the rollback is keyed on "the op after the move failed", not on a list of
    exception types: a promise that the store is left as it was found is not a promise
    about which exception was raised. Measured before this node existed, with the
    rollback catching `(MemoryBudgetExceeded, MemoryValidationError)`: the directory
    was moved into `facts/` and left there.
    """
    store = _three_facts(tmp_path)
    facts, archive = store.root / "facts", store.root / "archive"
    (archive / "put-away.md").mkdir()
    index_before = (store.root / "index.md").read_bytes()

    with pytest.raises(OSError):
        store.restore("put-away")

    assert sorted(p.name for p in archive.iterdir()) == ["put-away.md"]
    assert (archive / "put-away.md").is_dir()
    assert sorted(p.name for p in facts.iterdir()) == ["fact-0.md", "fact-1.md", "fact-2.md"]
    assert (store.root / "index.md").read_bytes() == index_before


def test_restore_names_the_directory_it_could_not_read_rather_than_the_fact_it_could_not_find(
    tmp_path, monkeypatch
):
    """"Not allowed to look" is not "not there" — the same invariant, one stat down.

    Two `exists()` probes run before anything moves, and neither of them swallows
    EACCES. WAS: a raw `PermissionError` out of both, so `restore` answered an
    operating-system question with an operating-system traceback. NOW: the module's
    one sentence, naming the directory and the consequence, which `_cmd_restore`
    already knows how to print.

    Note which sentence each side gets. Answering "no archived fact 'put-away'" for an
    archive that could not be read would be the module's own defect in its smallest
    form: the fact IS there.
    """
    store = _three_facts(tmp_path)
    facts, archive = store.root / "facts", store.root / "archive"
    (archive / "put-away.md").write_text(_ARCHIVED_FACT, encoding="utf-8")
    index_before = (store.root / "index.md").read_bytes()

    _deny_stat(monkeypatch, archive / "put-away.md")
    with pytest.raises(MemoryValidationError) as e:
        store.restore("put-away")
    monkeypatch.undo()
    assert str(archive) in str(e.value)
    assert "Permission denied" in str(e.value)
    assert "unreadable" in str(e.value)
    assert "no archived fact 'put-away'" not in str(e.value), (
        "the fact is on disk; saying it is not there is the wrong answer for EACCES"
    )

    # The destination probe is the same hole on the other side, and it runs BEFORE the
    # pre-read, so W1's raise never got a chance to be the one the operator saw.
    _deny_stat(monkeypatch, facts / "put-away.md")
    with pytest.raises(MemoryValidationError) as e:
        store.restore("put-away")
    monkeypatch.undo()
    assert str(facts) in str(e.value)
    assert "Permission denied" in str(e.value)
    assert "already live" not in str(e.value), (
        "a stat that was refused is not a name that is taken"
    )

    # Neither refusal moved anything, and the door back still opens.
    assert sorted(p.name for p in archive.iterdir()) == ["put-away.md"]
    assert (store.root / "index.md").read_bytes() == index_before
    store.restore("put-away")
    assert store.archived() == []


def test_the_cli_restore_prints_a_sentence_where_it_used_to_print_a_traceback(
    tmp_path, monkeypatch, capsys
):
    """The third unwrapped operator surface, closed at the store rather than at the CLI.

    `_cmd_restore` already catches `MemoryValidationError` and prints "restore failed:
    ...". It never saw one for this shape, because the error escaping was a
    `PermissionError` from `Path.exists()`. Measured at HEAD on a throwaway store with
    `archive/` at 0o000: `python -m bantamkit.memory restore put-away --store ...`
    exited 1 with a stack trace ending in `PermissionError: [Errno 13] Permission
    denied`. The exit code was right by accident — Python exits 1 on an unhandled
    exception — and everything the operator could act on was missing.

    Fixed in `store.py` and not in `__main__.py` on purpose. `_cmd_restore` is the only
    caller of `restore()` in the tree today (checked, not assumed: nothing else in
    `runtime-py/src` calls it), but "not allowed to look" versus "not there" is the
    STORE's invariant — the same one `_listing` holds one syscall up — and a
    `try/except PermissionError` in one CLI command would hold it for one caller.
    """
    store = _three_facts(tmp_path)
    archive = store.root / "archive"
    (archive / "put-away.md").write_text(_ARCHIVED_FACT, encoding="utf-8")

    _deny_stat(monkeypatch, archive / "put-away.md")
    rc = memory_main(["restore", "put-away", "--store", str(store.root)])
    monkeypatch.undo()

    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("restore failed: ")
    assert "unreadable" in err and str(archive) in err
    assert "Traceback" not in err
    assert sorted(p.name for p in archive.iterdir()) == ["put-away.md"]


def test_a_recall_pinned_before_the_store_broke_answers_but_never_dates_it(
    tmp_path, monkeypatch
):
    """`snapshot()`'s non-obvious case, worked out and pinned rather than left to be found.

    Three moments a store can become unreadable around a scope, and only the middle one
    is surprising:

    - BROKE INSIDE THE SCOPE. The pin holds, so `recall(..., stamp=False)` still answers
      from the facts as of entry — that is what the pin is FOR. The default
      `stamp=True` raises out of `_stamp`, which lists the live store, and it does so
      AFTER the hits were computed, so the answer is thrown away. WAS: `_stamp` got an
      empty listing, found no live copy, and silently skipped the stamp.
    - ALREADY UNREADABLE AT ENTRY. Nothing is pinned and `recall` raises on its own.
    - REPAIRED INSIDE THE SCOPE. Entry pinned nothing, so reads go live and see the
      repair.

    The stamp raise is kept rather than swallowed: a store that stops being readable
    mid-turn is news. What is asserted is that it costs nothing — no fact is left
    half-dated, because `_stamp` lists before it writes and raises on the first hit.
    """
    store = _three_facts(tmp_path)
    facts = store.root / "facts"
    on_disk = {p.name: p.read_bytes() for p in facts.iterdir()}

    with store.snapshot():
        assert store._snapshot is not None and len(store._snapshot) == 3
        _deny_scandir(monkeypatch, facts)
        assert [f.name for f in store.recall("w0a", stamp=False)] == ["fact-0"]
        with pytest.raises(MemoryValidationError) as e:
            store.recall("w0a")
        assert str(facts) in str(e.value)
        monkeypatch.undo()
    assert {p.name: p.read_bytes() for p in facts.iterdir()} == on_disk, (
        "a recall that raised while stamping still dated a fact"
    )

    _deny_scandir(monkeypatch, facts)
    with store.snapshot():
        assert store._snapshot is None, "an unreadable store is not pinned"
        with pytest.raises(MemoryValidationError):
            store.recall("w0a")
    monkeypatch.undo()

    _deny_scandir(monkeypatch, facts)
    with store.snapshot():
        monkeypatch.undo()
        assert [f.name for f in store.recall("w0a", stamp=False)] == ["fact-0"]


# ---------------------------------------------------------------------------
# The operator entry point (`python -m bantamkit.memory`).
#
# `docs/memory.md` holds a deliberate position: `lint`, `compact`, `archived`
# and `restore` are NOT agent tools, because lifecycle is an operator decision.
# Measured 2026-08-21, the operator had no way to make that decision — the
# budget was not on any argument parser and the four ops were reachable only
# from Python. These nodes are the other half of that position: they assert on
# what an operator actually SEES on stdout, so the report cannot become a
# write-only artifact the way `archive/` and `index.md` both did.
# ---------------------------------------------------------------------------


def _fill(store, n, *, width=60, prefix="fact"):
    """`n` distinct facts whose descriptions cannot collide under the dedupe check."""
    for i in range(n):
        store.save(
            "project",
            f"{prefix}-{i:03d}",
            " ".join(f"w{i:03d}q{j}" for j in range(width // 8)),
            f"body {i}",
        )


def _run(argv, capsys):
    code = memory_main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_store_and_component_index_budget_defaults_cannot_drift(tmp_path):
    """Three declarations of one number; a change to any one of them alone is a defect."""
    assert MemoryStore(tmp_path / "a").index_budget == DEFAULT_INDEX_BUDGET
    assert Memory(store=tmp_path / "b").store.index_budget == DEFAULT_INDEX_BUDGET
    assert Memory.layered(start=tmp_path / "c").store.index_budget == DEFAULT_INDEX_BUDGET


def test_the_default_budget_holds_the_real_stores_shape_without_evicting(tmp_path):
    """The live project store measured 3943 bytes over 20 facts on 2026-08-21.

    At the old default of 4096 that store had 153 bytes of headroom and 19 of its
    20 index lines were individually larger than that, so the very next save
    evicted a fact — a store permanently on a compaction treadmill. This node
    pins the property that made the default move: a store the size of the real
    one still has room to grow at the default budget.
    """
    store = MemoryStore(tmp_path / "mem")
    _fill(store, 20, width=190)
    lived = len(store.index_text().encode())
    assert lived > 3000, lived  # a store genuinely the shape of the real one
    assert store.index_budget - lived > lived, (
        "the default budget must leave a real store more headroom than it has used"
    )


@pytest.mark.parametrize("budget", [256, 512, 1024, 4096, 24_000, 100_000])
def test_operator_sets_the_budget_on_the_command_line(tmp_path, capsys, budget):
    """P5, swept: every one of these is reachable without editing a line of source."""
    store = MemoryStore(tmp_path / "mem")
    _fill(store, 2)
    code, out, err = _run(["status", "--store", str(store.root), "--budget", str(budget)], capsys)
    assert code == 0, err
    assert f"budget: {budget}" in out
    assert f"index: {len(store.index_text().encode())} bytes" in out
    assert f"facts: {len(store._facts())}" in out


@pytest.mark.parametrize("n_facts", [1, 2, 5, 9])
def test_lint_exit_code_flips_exactly_at_the_budget_not_near_it(tmp_path, capsys, n_facts):
    """RB-P99 on the budget dimension: the boundary is SWEPT, both sides, per store size.

    A single hardcoded budget would pass against an off-by-one comparison. Each
    store here is linted at exactly its own index size and at one byte under it.
    """
    store = MemoryStore(tmp_path / "mem")
    _fill(store, n_facts)
    size = len(store.index_text().encode())
    root = str(store.root)

    code, out, _ = _run(["lint", "--store", root, "--budget", str(size)], capsys)
    assert code == 0, f"{size} bytes must lint clean against a budget of exactly {size}"
    assert f"{size}/{size} bytes" in out

    code, _, err = _run(["lint", "--store", root, "--budget", str(size - 1)], capsys)
    assert code == 1, f"{size} bytes must fail a budget of {size - 1}"
    assert f"index is {size} bytes" in err and f"budget is {size - 1}" in err
    assert "compact" in err, "a FAIL must name the operator's remedy, not just the number"


def test_lint_names_the_malformed_fact_rather_than_the_budget(tmp_path, capsys):
    store = MemoryStore(tmp_path / "mem")
    _fill(store, 1)
    (store.root / "facts" / "broken.md").write_text(
        "no frontmatter at all", encoding="utf-8"
    )
    code, _, err = _run(["lint", "--store", str(store.root)], capsys)
    assert code == 1
    assert "budget" not in err.lower(), err


@pytest.mark.parametrize("n_facts,budget_lines", [(4, 1), (4, 2), (6, 3), (9, 4), (3, 3)])
def test_compact_prints_the_arithmetic_an_operator_can_check(
    tmp_path, capsys, n_facts, budget_lines
):
    """P7 swept over how much has to leave, including the case where nothing does.

    Every number on stdout is re-derived from the store afterwards, so a report
    that drifts from what actually happened reddens this.
    """
    store = MemoryStore(tmp_path / "mem")
    _fill(store, n_facts)
    line = len(store.index_text().encode()) // n_facts
    budget = budget_lines * line
    before = len(store.index_text().encode())

    code, out, err = _run(
        ["compact", "--store", str(store.root), "--budget", str(budget)], capsys
    )
    assert code == 0, err

    after = MemoryStore(store.root, index_budget=budget)
    gone = after.archived()
    assert f"compacted {len(gone)} fact(s)" in out
    assert f"index: {before} -> {len(after.index_text().encode())} bytes" in out
    assert f"budget {budget}" in out
    for name in gone:
        assert name in out, f"{name} left the index and the operator was not told"
    for fact in after._facts():
        assert fact.name not in out, f"{fact.name} is still live and must not be reported as gone"


def test_compact_that_archives_nothing_says_so_instead_of_printing_an_empty_list(
    tmp_path, capsys
):
    store = MemoryStore(tmp_path / "mem")
    _fill(store, 3)
    code, out, _ = _run(["compact", "--store", str(store.root), "--budget", "100000"], capsys)
    assert code == 0
    assert "compacted 0 fact(s)" in out
    assert "nothing to archive" in out


@pytest.mark.parametrize("n_archived", [1, 2, 4])
def test_archived_lists_every_name_compaction_moved_out(tmp_path, capsys, n_archived):
    store = MemoryStore(tmp_path / "mem")
    _fill(store, n_archived + 2)
    line = len(store.index_text().encode()) // (n_archived + 2)
    _run(["compact", "--store", str(store.root), "--budget", str(2 * line)], capsys)

    names = MemoryStore(store.root).archived()
    code, out, _ = _run(["archived", "--store", str(store.root)], capsys)
    assert code == 0
    assert f"archived facts: {len(names)}" in out
    for name in names:
        assert name in out


def test_restore_brings_a_fact_back_and_reports_the_new_index(tmp_path, capsys):
    store = MemoryStore(tmp_path / "mem")
    _fill(store, 4)
    line = len(store.index_text().encode()) // 4
    _run(["compact", "--store", str(store.root), "--budget", str(2 * line)], capsys)
    gone = MemoryStore(store.root).archived()
    assert gone, "the fixture must actually archive something"

    code, out, err = _run(
        ["restore", gone[0], "--store", str(store.root), "--budget", "100000"], capsys
    )
    assert code == 0, err
    assert f"restored '{gone[0]}'" in out
    back = MemoryStore(store.root)
    assert gone[0] in {f.name for f in back._facts()}
    assert gone[0] not in back.archived()
    assert f"{len(back.index_text().encode())}" in out


def test_restore_over_budget_fails_loudly_and_changes_nothing(tmp_path, capsys):
    store = MemoryStore(tmp_path / "mem")
    _fill(store, 4)
    line = len(store.index_text().encode()) // 4
    _run(["compact", "--store", str(store.root), "--budget", str(2 * line)], capsys)
    gone = MemoryStore(store.root).archived()
    before_live = sorted(f.name for f in MemoryStore(store.root)._facts())
    before_archive = MemoryStore(store.root).archived()

    code, _, err = _run(
        ["restore", gone[0], "--store", str(store.root), "--budget", str(line)], capsys
    )
    assert code == 1
    assert gone[0] in err
    assert sorted(f.name for f in MemoryStore(store.root)._facts()) == before_live
    assert MemoryStore(store.root).archived() == before_archive


def test_restore_of_an_unknown_name_is_an_error_not_a_traceback(tmp_path, capsys):
    store = MemoryStore(tmp_path / "mem")
    _fill(store, 1)
    code, _, err = _run(["restore", "no-such-fact", "--store", str(store.root)], capsys)
    assert code == 1
    assert "no-such-fact" in err


def test_start_discovers_the_project_store_and_never_the_profile(tmp_path, capsys):
    """`compact` touches only the writable project layer; the CLI must not widen that."""
    project = tmp_path / "repo" / ".bantamkit" / "memory"
    store = MemoryStore(project)
    _fill(store, 2)
    nested = tmp_path / "repo" / "pkg" / "deep"
    nested.mkdir(parents=True)
    code, out, err = _run(["status", "--start", str(nested)], capsys)
    assert code == 0, err
    assert f"store: {project}" in out
    assert str(Path.home() / ".bantamkit") not in out


def test_store_and_start_are_mutually_exclusive(tmp_path, capsys):
    with pytest.raises(SystemExit):
        memory_main(["status", "--store", str(tmp_path), "--start", str(tmp_path)])


@pytest.mark.parametrize("budget", ["0", "-1", "notanint"])
def test_a_nonsense_budget_is_refused_rather_than_silently_applied(tmp_path, capsys, budget):
    with pytest.raises(SystemExit):
        memory_main(["status", "--store", str(tmp_path / "mem"), "--budget", budget])


def test_the_entry_point_runs_as_a_real_subprocess(tmp_path):
    """P6 proven by invocation, not by import: `python -m bantamkit.memory` must work.

    Imported-and-called is not the claim; the claim is that an operator with a
    shell can reach this. `mcp.client.stdio` strips PYTHONPATH (RB-P97), so the
    path is passed explicitly and derived from the module actually under test.
    """
    store = MemoryStore(tmp_path / "mem")
    _fill(store, 3)
    src = Path(bantamkit.__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-m", "bantamkit.memory", "status", "--store", str(store.root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONPATH": str(src)},
    )
    assert proc.returncode == 0, proc.stderr
    assert f"facts: {len(store._facts())}" in proc.stdout
    assert f"budget: {DEFAULT_INDEX_BUDGET}" in proc.stdout
