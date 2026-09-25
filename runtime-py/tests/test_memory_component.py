import os
from pathlib import Path

import pytest
from conftest import FakeClient, assistant, call

from bantamkit.agent import Agent
from bantamkit.assets import assets_root, load_skill, load_tool
from bantamkit.memory import Memory
from bantamkit.memory.component import normalize_name
from bantamkit.memory.layers import MEMORY_DIR_ENV
from bantamkit.memory.store import (
    RECALL_MIN_SCORE_RATIO,
    MemoryStore,
    MemoryValidationError,
)


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
    assert [t.tool.name for t in agent.tools] == ["memory_save", "memory_recall", "memory_compact"]
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
    """Point the profile memory layer at a scratch dir, on every platform.

    `Memory.layered` locates the profile store under `Path.home()`, and which
    environment variable that consults is platform-specific: POSIX
    (`posixpath.expanduser`) reads `HOME` and falls back to `pwd`; Windows
    (`ntpath.expanduser`) reads `USERPROFILE`, then `HOMEDRIVE`+`HOMEPATH`,
    and never reads `HOME` at all. Setting environment names is therefore
    correct only while that list is complete, and the list belongs to CPython,
    not to us. Replacing `Path.home` retires the question: the call site gets
    this directory whatever the platform's rule is. `HOME` is still set so an
    environment-reading consumer agrees with it where `HOME` is the rule.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
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
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n", encoding="utf-8"
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
    before = (profile_store / "facts" / "prof.md").read_text(encoding="utf-8")

    Memory.layered(start=project)._recall("deploy")
    assert (profile_store / "facts" / "prof.md").read_text(encoding="utf-8") == before


def test_layered_recall_stamps_the_project_layer_by_default_and_not_when_told_not_to(
    tmp_path, fake_home
):
    """`stamp=False` (job64, J64-1) is the hook's flag: the same walk, the same answer, and
    not one byte written. The default half is pinned in the same test because J64-0 found
    the POSITIVE ("a layered recall stamps the project layer") pinned nowhere at this level
    — only the negative for read-only layers, one test up."""
    project = tmp_path / "companyA"
    project.mkdir()
    store = project / ".bantamkit" / "memory"
    _seed(store, "deploy", "project truth")
    path = store / "facts" / "deploy.md"
    before = path.read_bytes()
    assert b"last_recalled: null" in before

    quiet = Memory.layered(start=project).recall_outcome("deploy", stamp=False)
    assert (quiet.status, quiet.returned) == ("answered", 1)
    assert path.read_bytes() == before

    loud = Memory.layered(start=project).recall_outcome("deploy")
    assert loud.reply == quiet.reply, "the flag changes what is written, never what is answered"
    assert path.read_bytes() != before
    assert b"last_recalled: '" in path.read_bytes()


# ---- the exact-name walk (job64, J64-4) -------------------------------------------------
#
# COMMON.md premise 4, measured 2026-09-25: a `memory_recall` whose query was exactly the
# name of a PROFILE fact came back with three PROJECT facts, because the project layer's
# fuzzy hits filled the budget and `recall_outcome` broke out of the loop before the profile
# layer was read. The bed below is that shape: three project facts share tokens with the name,
# and the fact itself lives one layer down.

_NPX = "feedback-bantamkit-mcp-local-install-not-npx"


def _shadowed_bed(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    store = project / ".bantamkit" / "memory"
    _seed(store, "local-dev-loop", "b", description="local install of the mcp for development")
    _seed(store, "mcp-server-notes", "b", description="notes on the bantamkit mcp server")
    _seed(store, "npx-windows-eperm", "b", description="npx install fails on windows with eperm")
    profile = fake_home / ".bantamkit" / "memory"
    _seed(profile, _NPX, "the body", description="install the mcp locally, never through npx")
    return project, store, profile


def test_a_query_that_is_a_profile_fact_name_is_answered_alone_past_a_full_project_layer(
    tmp_path, fake_home
):
    project, store, profile = _shadowed_bed(tmp_path, fake_home)
    untouched = {p: p.read_bytes() for p in (store / "facts").iterdir()}
    profile_before = (profile / "facts" / f"{_NPX}.md").read_bytes()

    out = Memory.layered(start=project).recall_outcome(_NPX)

    assert out.reply == (
        f"[profile] [{_NPX}] (project) install the mcp locally, never through npx\nthe body"
    )
    assert (out.status, out.lookup, out.returned, out.reached, out.source) == (
        "answered", "hit", 1, 2, "profile"
    )
    # The project layer WAS read (reached 2, candidates count it) and nothing in it was
    # stamped: an exact hit dates the fact named, and only in a writable layer.
    assert out.candidates == 4
    assert {p: p.read_bytes() for p in (store / "facts").iterdir()} == untouched
    assert (profile / "facts" / f"{_NPX}.md").read_bytes() == profile_before


def test_the_same_name_padded_with_whitespace_is_still_the_name(tmp_path, fake_home):
    project, _store, _profile = _shadowed_bed(tmp_path, fake_home)
    mem = Memory.layered(start=project)
    assert mem.recall_outcome(f"  {_NPX}\n").reply == mem.recall_outcome(_NPX).reply
    assert mem.recall_outcome(f"  {_NPX}\n").lookup == "hit"


def test_an_exact_hit_in_the_project_layer_stops_the_walk_and_stamps_only_that_fact(
    tmp_path, fake_home
):
    """Precedence is unchanged: when both layers hold the name, the project copy answers,
    the profile copy is never read, and `stamp=False` (the hook's flag) still writes nothing."""
    project = tmp_path / "companyA"
    project.mkdir()
    store = project / ".bantamkit" / "memory"
    _seed(store, "deploy-command", "project truth")
    _seed(store, "deploy-notes", "other", description="deploy command notes")
    profile = fake_home / ".bantamkit" / "memory"
    _seed(profile, "deploy-command", "profile stale")
    path = store / "facts" / "deploy-command.md"
    before = path.read_bytes()

    quiet = Memory.layered(start=project).recall_outcome("deploy-command", stamp=False)
    assert quiet.reply == "[project] [deploy-command] (project) a fact about deploys\nproject truth"
    assert (quiet.lookup, quiet.reached, quiet.returned) == ("hit", 1, 1)
    assert path.read_bytes() == before

    loud = Memory.layered(start=project).recall_outcome("deploy-command")
    assert loud.reply == quiet.reply
    assert b"last_recalled: '" in path.read_bytes()
    assert b"last_recalled: null" in (store / "facts" / "deploy-notes.md").read_bytes()
    assert b"last_recalled: null" in (profile / "facts" / "deploy-command.md").read_bytes()


def test_a_name_shaped_query_nobody_holds_says_so_in_one_leading_line(tmp_path, fake_home):
    """The line is followed by EXACTLY the reply the ordinary walk gives — a hit here, one of
    the empty verdicts in the test below — so the ordinary walk is pinned as a suffix."""
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "deploy", "project truth")
    mem = Memory.layered(start=project)

    ordinary = mem.recall_outcome("deploy command")  # spaced: never enters the name walk
    assert ordinary.lookup is None
    named = mem.recall_outcome("deploy-command")
    assert named.lookup == "miss"
    assert named.reply == (
        "no fact named 'deploy-command' in any layer bound here; matching by words instead:"
        "\n\n" + ordinary.reply
    )
    assert (named.status, named.returned, named.reached) == (
        ordinary.status, ordinary.returned, ordinary.reached
    )


def test_a_name_shaped_query_over_a_store_that_misses_leads_with_the_line_then_the_verdict(
    tmp_path, fake_home
):
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "deploy", "project truth")
    out = Memory.layered(start=project).recall_outcome("zzz-nothing-like-this")
    assert out.reply == (
        "no fact named 'zzz-nothing-like-this' in any layer bound here; matching by words "
        "instead:\n\nno memories matched. Try different words, or proceed without."
    )
    assert (out.status, out.lookup) == ("empty-no-match", "miss")


def test_a_bare_word_is_the_ordinary_walk_even_when_a_fact_is_named_by_it(tmp_path, fake_home):
    """`deploy` is `NAME_RE`-valid but carries no hyphen, so it is NOT in the name shape: a
    single word is a word anyone might search, and the layered dedupe test above
    (`test_layered_project_wins_on_duplicate_name_and_prefixes_layers`) has always pinned
    that a bare word naming a fact in two layers still returns the merged word matches.
    Here: the word search returns two facts; no exact hit, no miss line."""
    project = tmp_path / "companyA"
    project.mkdir()
    store = project / ".bantamkit" / "memory"
    _seed(store, "deploy", "project truth")
    _seed(store, "runbook", "other", description="the deploy runbook")
    out = Memory.layered(start=project).recall_outcome("deploy")
    assert out.reply == (
        "[project] [deploy] (project) a fact about deploys\nproject truth\n\n"
        "[project] [runbook] (project) the deploy runbook\nother"
    )
    assert (out.lookup, out.returned) == (None, 2)


def test_a_bad_ratio_is_refused_before_the_name_walk_reads_a_file(tmp_path, fake_home):
    """An exact hit must not swallow a caller's bug: the range check runs first, with the
    store's own sentence, and the named fact is left undated."""
    project = tmp_path / "companyA"
    project.mkdir()
    store = project / ".bantamkit" / "memory"
    _seed(store, "deploy-command", "project truth")
    before = (store / "facts" / "deploy-command.md").read_bytes()
    with pytest.raises(MemoryValidationError, match="^recall min-score ratio must be between"):
        Memory.layered(start=project).recall_outcome("deploy-command", min_ratio=1.5)
    assert (store / "facts" / "deploy-command.md").read_bytes() == before


def test_layered_corrupt_grant_does_not_break_project_recall(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "deploy", "project truth")
    bad = tmp_path / "companyB" / ".bantamkit" / "memory"
    (bad / "facts").mkdir(parents=True)
    (bad / "facts" / "junk.md").write_text("no frontmatter at all", encoding="utf-8")
    (project / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n", encoding="utf-8"
    )

    out = Memory.layered(start=project)._recall("deploy")
    assert "[project] [deploy]" in out


def test_layered_dangling_grant_raises_at_construction(tmp_path, fake_home):
    project = tmp_path / "companyA"
    project.mkdir()
    (project / ".bantamkit").mkdir()
    (project / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../nope\n", encoding="utf-8"
    )
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
    (project_store / "facts" / "broken.md").write_text(
        "no frontmatter here at all", encoding="utf-8"
    )

    with pytest.raises(MemoryValidationError):
        Memory.layered(start=project)._recall("test")


def test_v1_corrupt_layer_raises_on_recall(tmp_path):
    """Corrupt layer in v1 mode also raises MemoryValidationError on recall."""
    store_path = tmp_path / "m"
    (store_path / "facts").mkdir(parents=True)
    (store_path / "facts" / "broken.md").write_text("no frontmatter here at all", encoding="utf-8")

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
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n", encoding="utf-8"
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
    (bad / "facts" / "junk.md").write_text("no frontmatter at all", encoding="utf-8")
    (project / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n", encoding="utf-8"
    )
    client = FakeClient(
        [
            assistant(tool_calls=[call("memory_recall", {"query": "deploy"})]),
            assistant(content="ok"),
        ]
    )
    Agent(client=client).use(Memory.layered(start=project)).run("t")
    assert "[project] [deploy]" in client.calls[1]["messages"][-1].content


# ---- N3: the live topology, rebuilt, and the answer it used to give ------------
#
# Read off this machine 2026-08-22 rather than assumed -- three commands, all
# rerunnable:
#
#     lsof -a -p 34377 -d cwd -Fn                     -> .../Projects/trader-platform
#     ls ~/.bantamkit/memory/facts/ | wc -l           -> 0
#     ls .../bantamkit/.bantamkit/memory/facts/*.md | wc -l   -> 65
#
# A project with no store of its own; an ancestor — the home directory — carrying
# a store that exists and holds nothing; the operator's actual facts in a SIBLING
# project the walk never visits. The walk binds the empty ancestor, and until this
# unit a recall against it returned the same sentence a populated store returns for
# a question that matches nothing.
#
# Nothing below touches any of those real paths. The shape is rebuilt under
# `tmp_path` with `fake_home`, and every count is read back off the fixture rather
# than written down: a node whose result depends on the operator's own
# `~/.bantamkit` means something different on CI, which is the exact way this repo
# has been burned before.


def _trader_platform_shape(fake_home):
    """project (no store) under a home carrying an EMPTY store, facts in a sibling."""
    ancestor = fake_home / ".bantamkit" / "memory"
    (ancestor / "facts").mkdir(parents=True)
    project = fake_home / "Projects" / "trader-platform"
    project.mkdir(parents=True)
    sibling = fake_home / "Projects" / "bantamkit" / ".bantamkit" / "memory"
    _seed(sibling, "deploy-command", "make ship-prod", description="how we deploy to prod")
    return project, ancestor, sibling


def test_an_empty_ancestor_store_no_longer_answers_like_a_query_that_missed(
    tmp_path, fake_home
):
    project, ancestor, sibling = _trader_platform_shape(fake_home)
    assert list((ancestor / "facts").glob("*.md")) == []
    assert len(list((sibling / "facts").glob("*.md"))) == 1

    out = Memory.layered(start=project)._recall("deploy prod")

    # The pre-N1 answer, in full: "no memories matched. Try different words, or
    # proceed without." Every clause of it was wrong here.
    assert "Try different words" not in out
    assert str(ancestor) in out, "the answer must name the cabinet it opened"
    assert str(project) in out, "and why that cabinet and not another"
    assert MEMORY_DIR_ENV in out, "and the one lever the operator actually holds"


def test_the_pin_the_message_names_is_the_one_that_reaches_the_facts(
    tmp_path, fake_home, monkeypatch
):
    """The remedy in the message is not advice; this runs it."""
    project, _ancestor, sibling = _trader_platform_shape(fake_home)
    assert MEMORY_DIR_ENV in Memory.layered(start=project)._recall("deploy prod")

    monkeypatch.setenv(MEMORY_DIR_ENV, str(sibling))
    assert "make ship-prod" in Memory.layered(start=project)._recall("deploy prod")


def test_a_populated_store_that_genuinely_misses_keeps_its_exact_wording(tmp_path, fake_home):
    """The case that already worked, pinned byte for byte."""
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "deploy", "make ship-prod")

    out = Memory.layered(start=project)._recall("zzz nothing like this")
    assert out == "no memories matched. Try different words, or proceed without."


def test_a_designated_store_says_none_existed_rather_than_none_matched(tmp_path, fake_home):
    """Third state: the walk found no store anywhere, so one was created empty."""
    project = tmp_path / "fresh"
    project.mkdir()

    out = Memory.layered(start=project)._recall("deploy prod")
    assert "No memory store existed at or above" in out
    assert str(project.resolve()) in out
    assert "walking up from" not in out  # that is the OTHER state's sentence


def test_a_pinned_empty_store_blames_the_pin_and_not_the_query(tmp_path, fake_home, monkeypatch):
    pinned = tmp_path / "elsewhere" / ".bantamkit" / "memory"
    (pinned / "facts").mkdir(parents=True)
    monkeypatch.setenv(MEMORY_DIR_ENV, str(pinned))

    out = Memory.layered(start=tmp_path)._recall("deploy prod")
    assert f"{MEMORY_DIR_ENV} pinned it" in out
    assert "walking up from" not in out  # no walk ran, so none may be claimed


def test_the_three_states_are_three_different_sentences(tmp_path, fake_home):
    """N1 named three states; a message that collapses two of them is the defect."""
    populated = tmp_path / "full"
    populated.mkdir()
    _seed(populated / ".bantamkit" / "memory", "deploy", "make ship-prod")
    hollow = tmp_path / "hollow"
    (hollow / ".bantamkit" / "memory" / "facts").mkdir(parents=True)
    fresh = tmp_path / "fresh"
    fresh.mkdir()

    answers = {
        Memory.layered(start=start)._recall("zzz nothing like this")
        for start in (populated, hollow, fresh)
    }
    assert len(answers) == 3


def test_the_diagnosis_stops_once_the_store_it_named_holds_a_fact(tmp_path, fake_home):
    """A store that was empty at construction and has been saved to since can answer,
    and must not keep being described from a binding taken before the save."""
    project, _ancestor, _sibling = _trader_platform_shape(fake_home)
    mem = Memory.layered(start=project)
    assert MEMORY_DIR_ENV in mem._recall("deploy prod")

    mem.save("project", "deploy-command", "how we deploy to prod", "make ship-prod")

    assert (
        mem._recall("zzz nothing like this")
        == "no memories matched. Try different words, or proceed without."
    )


def test_a_populated_profile_layer_still_names_the_empty_project_binding(tmp_path, fake_home):
    """Something really was searched, so the verdict is a true miss — but the store
    that saves land in is still the wrong one, and the miss must not hide that."""
    project = tmp_path / "companyA"
    (project / ".bantamkit" / "memory" / "facts").mkdir(parents=True)
    _seed(
        fake_home / ".bantamkit" / "memory",
        "profile-note",
        "a profile body",
        description="an unrelated topic",
    )

    out = Memory.layered(start=project)._recall("deploy prod")
    assert out.startswith("no memories matched.")
    assert str(project / ".bantamkit" / "memory") in out
    assert MEMORY_DIR_ENV in out
    # This node was emitting the F2 sentence and asserting nothing about it: the
    # walk here terminates at step zero, so `no store of its own` was false.
    assert "which has no store of its own" not in out


def test_a_caller_named_store_reports_no_walk_it_never_ran(tmp_path):
    """`Memory(store=...)` resolved nothing, so it may not narrate a resolution."""
    out = Memory(store=tmp_path / "mem")._recall("deploy prod")
    assert str(tmp_path / "mem") in out
    assert "walking up from" not in out
    assert "No memory store existed" not in out


# ---- N5: the three sentences the message was getting wrong ---------------------


def test_a_project_whose_own_store_is_merely_empty_is_not_told_it_has_none(
    tmp_path, fake_home
):
    """F2: the walk clause described an ascent that did not happen.

    The walk terminates at step zero here -- the project's OWN `.bantamkit/memory`
    is the store it binds -- and the message still said `which has no store of its
    own`. That sentence sends an operator hunting a binding bug that is not there.
    """
    project = tmp_path / "companyA"
    (project / ".bantamkit" / "memory" / "facts").mkdir(parents=True)

    out = Memory.layered(start=project)._recall("deploy prod")

    assert "which has no store of its own" not in out
    assert "walking up from" not in out
    assert str(project / ".bantamkit" / "memory") in out
    assert MEMORY_DIR_ENV in out


def test_a_walk_that_really_ascended_still_narrates_the_ascent(tmp_path, fake_home):
    """The other half of F2: the clause is not deleted, it is made conditional."""
    project, ancestor, _sibling = _trader_platform_shape(fake_home)

    out = Memory.layered(start=project)._recall("deploy prod")

    assert "walking up from" in out
    assert "which has no store of its own" in out
    assert str(project) in out and str(ancestor) in out


def test_the_remedy_never_tells_you_to_seed_the_shared_profile_store(tmp_path, fake_home):
    """F3: `save a memory to start this one` is harmful when `this one` is shared.

    `Memory.layered` locates the profile layer at `~/.bantamkit/memory`, and the
    project walk binds that SAME directory whenever a project has no store of its
    own. Following the old advice there writes a fact that then answers for every
    unrelated project on the machine.
    """
    project, ancestor, _sibling = _trader_platform_shape(fake_home)
    assert ancestor == fake_home / ".bantamkit" / "memory", "the bound store IS the profile layer"

    out = Memory.layered(start=project)._recall("deploy prod")

    assert "save a memory to start this one" not in out
    assert "profile layer" in out
    assert "every project" in out


def test_a_store_that_is_this_project_s_alone_still_says_to_start_it(tmp_path, fake_home):
    """The advice is withdrawn only where it is harmful, never everywhere."""
    project = tmp_path / "companyA"
    (project / ".bantamkit" / "memory" / "facts").mkdir(parents=True)

    out = Memory.layered(start=project)._recall("deploy prod")

    assert "save a memory to start this one" in out
    assert "profile layer" not in out


def test_a_save_into_the_bound_store_answers_for_an_unrelated_project(tmp_path, fake_home):
    """Why F3 is a defect and not a wording quibble: the leak, run rather than argued.

    This is also the tripwire on the deeper defect N4 named and this job does not
    fix -- the project walk and the profile layer can bind the SAME directory. The
    day they cannot, this node fails, and the advice withdrawn above can come back.
    """
    project_a, ancestor, _sibling = _trader_platform_shape(fake_home)
    project_b = fake_home / "Projects" / "unrelated"
    project_b.mkdir(parents=True)

    Memory.layered(start=project_a).save(
        "project", "leaked-fact", "how we deploy to prod", "make ship-prod"
    )

    assert (ancestor / "facts" / "leaked-fact.md").exists(), "project A's save landed in $HOME"
    assert "make ship-prod" in Memory.layered(start=project_b)._recall("deploy prod")


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores mode bits")
def test_a_layer_that_could_not_be_read_is_not_evidence_that_nothing_is_saved(
    tmp_path, fake_home
):
    """F1 at the message: `_fact_count`'s `except OSError` was unreachable.

    `Path.glob` swallowed the error, so an unreadable profile layer counted as zero
    facts and the recall announced that nothing is saved in any layer bound here --
    while a fact sat in the layer it could not open.
    """
    project = tmp_path / "companyA"
    (project / ".bantamkit" / "memory" / "facts").mkdir(parents=True)
    profile_facts = fake_home / ".bantamkit" / "memory" / "facts"
    profile_facts.mkdir(parents=True)
    (profile_facts / "a-fact.md").write_text("x", encoding="utf-8")
    profile_facts.chmod(0o000)
    try:
        out = Memory.layered(start=project)._recall("deploy prod")
    finally:
        profile_facts.chmod(0o755)

    assert "nothing is saved in any layer bound here" not in out
    assert "could not be read" in out
    assert str(profile_facts.parent) in out


# --------------------------------------------------------------------------- #
# roadmap #6 — the precision gate, seen from the layered component.
# --------------------------------------------------------------------------- #


def test_the_gate_default_changes_no_layered_recall(tmp_path, fake_home):
    """The no-op proof at the surface every caller actually uses."""
    assert RECALL_MIN_SCORE_RATIO == 0.0
    project = tmp_path / "companyA"
    project.mkdir()
    store = project / ".bantamkit" / "memory"
    _seed(store, "alpha", "x", description="alpha bravo charlie delta")
    _seed(store, "weak", "x", description="alpha xray yankee zulu")
    _seed(fake_home / ".bantamkit" / "memory", "gamma", "y", description="alpha oscar papa quebec")

    mem = Memory.layered(start=project, k=9)
    plain = mem.recall_outcome("alpha bravo charlie delta")
    assert plain.returned == 3
    assert mem.recall_outcome("alpha bravo charlie delta", min_ratio=0.0).reply == plain.reply
    assert (
        mem.recall_outcome("alpha bravo charlie delta", min_ratio=RECALL_MIN_SCORE_RATIO).reply
        == plain.reply
    )


def test_the_gate_is_measured_per_layer_and_never_across_layers(tmp_path, fake_home):
    """A profile fact does not have to out-score the project store's top hit.

    Project scores 4 and 1; profile scores 1. At `min_ratio=1.0` the project layer
    keeps only its own best — so `weak` goes — while `gamma` survives, because 1 is
    the best score in the store that holds it. A gate applied to the merged list
    would have dropped `gamma` too, and this is the assertion that tells them apart.
    """
    project = tmp_path / "companyA"
    project.mkdir()
    store = project / ".bantamkit" / "memory"
    _seed(store, "alpha", "x", description="alpha bravo charlie delta")
    _seed(store, "weak", "x", description="alpha xray yankee zulu")
    _seed(fake_home / ".bantamkit" / "memory", "gamma", "y", description="alpha oscar papa quebec")

    out = Memory.layered(start=project, k=9).recall_outcome(
        "alpha bravo charlie delta", min_ratio=1.0
    )
    assert out.returned == 2
    assert "[alpha]" in out.reply and "[gamma]" in out.reply
    assert "[weak]" not in out.reply


def test_a_bad_ratio_surfaces_as_the_error_it_is_not_as_an_unreadable_layer(tmp_path, fake_home):
    """The writable project layer is reached first, so the range check re-raises."""
    project = tmp_path / "companyA"
    project.mkdir()
    _seed(project / ".bantamkit" / "memory", "alpha", "x", description="alpha bravo")
    with pytest.raises(MemoryValidationError) as excinfo:
        Memory.layered(start=project).recall_outcome("alpha", min_ratio=1.5)
    assert str(excinfo.value) == "recall min-score ratio must be between 0.0 and 1.0"


def test_memory_recall_passes_the_ratio_through_to_the_outcome(tmp_path):
    """`Memory.recall` is the string half of `recall_outcome`; the gate must reach it."""
    mem = Memory(store=tmp_path / "m", k=9)
    mem._save("project", "alpha", "alpha bravo charlie delta", "x")
    mem._save("project", "weak", "alpha xray yankee zulu", "x")
    assert "[weak]" in mem.recall("alpha bravo charlie delta")
    assert "[weak]" not in mem.recall("alpha bravo charlie delta", min_ratio=1.0)
