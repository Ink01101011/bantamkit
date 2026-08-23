import os
import sys

import pytest

from bantamkit.memory.layers import (
    MEMORY_DIR_ENV,
    discover_project_store,
    load_grants,
    resolve_project_store,
)
from bantamkit.memory.store import MemoryValidationError


def _mkstore(base):
    store = base / ".bantamkit" / "memory"
    store.mkdir(parents=True)
    return store


def test_discover_finds_nearest_ancestor_store(tmp_path):
    top = _mkstore(tmp_path / "companyA")
    nested = tmp_path / "companyA" / "src" / "deep"
    nested.mkdir(parents=True)
    assert discover_project_store(nested) == top


def test_discover_prefers_closer_store_over_ancestor(tmp_path):
    _mkstore(tmp_path / "companyA")
    inner = _mkstore(tmp_path / "companyA" / "subproj")
    start = tmp_path / "companyA" / "subproj" / "lib"
    start.mkdir()
    assert discover_project_store(start) == inner


def test_discover_miss_designates_under_start_without_creating(tmp_path):
    start = tmp_path / "fresh"
    start.mkdir()
    designated = discover_project_store(start)
    assert designated == start.resolve() / ".bantamkit" / "memory"
    assert not designated.exists()


def test_load_grants_missing_config_is_empty(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    assert load_grants(store) == []


def test_load_grants_empty_config_is_empty(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text("", encoding="utf-8")
    assert load_grants(store) == []


def test_load_grants_resolves_relative_to_config(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    other = _mkstore(tmp_path / "companyB")
    (store.parent / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n", encoding="utf-8"
    )
    assert load_grants(store) == [other.resolve()]


def test_load_grants_malformed_yaml_raises(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text("extra_stores: [unclosed\n", encoding="utf-8")
    with pytest.raises(MemoryValidationError):
        load_grants(store)


def test_load_grants_non_mapping_config_raises(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text("just a string\n", encoding="utf-8")
    with pytest.raises(MemoryValidationError):
        load_grants(store)


def test_load_grants_dangling_path_raises(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text(
        "extra_stores:\n  - ../../nope/memory\n", encoding="utf-8"
    )
    with pytest.raises(MemoryValidationError):
        load_grants(store)


def test_discover_with_start_as_store_directory(tmp_path):
    _mkstore(tmp_path)
    own_store = _mkstore(tmp_path / "companyA")
    result = discover_project_store(tmp_path / "companyA")
    assert result == own_store


def test_discover_skips_file_named_store(tmp_path):
    real_store = _mkstore(tmp_path)
    ancestor = tmp_path / "ancestor"
    ancestor.mkdir()
    (ancestor / ".bantamkit").mkdir()
    (ancestor / ".bantamkit" / "memory").write_text("not a directory", encoding="utf-8")

    start = ancestor / "src"
    start.mkdir()
    assert discover_project_store(start) == real_store


def test_discover_symlinked_start_resolves(tmp_path):
    real_proj = _mkstore(tmp_path / "companyA")
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "companyA")

    result = discover_project_store(link / "src")
    assert result == real_proj


def test_load_grants_config_as_directory_raises(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").mkdir()
    with pytest.raises(MemoryValidationError):
        load_grants(store)


def test_load_grants_no_extra_stores_key_is_empty(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text("some_other_key: value\n", encoding="utf-8")
    assert load_grants(store) == []


def test_discover_miss_path_under_resolved_ancestor(tmp_path):
    real_proj = tmp_path / "companyA"
    real_proj.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real_proj)

    result = discover_project_store(link / "fresh_sub")
    expected = real_proj.resolve() / "fresh_sub" / ".bantamkit" / "memory"
    assert result == expected
    assert not result.exists()


def test_load_grants_symlinked_store_reads_adjacent_config(tmp_path):
    real_store = _mkstore(tmp_path / "realstore")
    proj = tmp_path / "proj"
    proj.mkdir()
    symlink_store = proj / ".bantamkit" / "memory"
    symlink_store.parent.mkdir(parents=True)
    symlink_store.symlink_to(real_store)

    other_store = _mkstore(tmp_path / "other")
    (proj / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../other/.bantamkit/memory\n", encoding="utf-8"
    )

    result = load_grants(discover_project_store(proj))
    assert result == [other_store.resolve()]


def test_resolve_names_a_populated_store(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store / "facts").mkdir()
    (store / "facts" / "a-fact.md").write_text("x", encoding="utf-8")
    nested = tmp_path / "companyA" / "src"
    nested.mkdir()

    binding = resolve_project_store(nested)
    assert binding.path == store
    assert binding.state == "populated"
    assert binding.fact_count == 1
    assert binding.searched_from == nested.resolve()


def test_resolve_empty_ancestor_store_is_not_populated(tmp_path):
    # The measured shape: the project itself has no store, the walk climbs past it
    # and binds to an ancestor store that exists and holds nothing.
    ancestor = _mkstore(tmp_path / "home")
    (ancestor / "facts").mkdir()
    project = tmp_path / "home" / "Projects" / "trader-platform"
    project.mkdir(parents=True)

    binding = resolve_project_store(project)
    assert binding.path == ancestor
    assert binding.state == "empty"
    assert binding.fact_count == 0


def test_resolve_designated_is_a_third_state(tmp_path):
    start = tmp_path / "fresh"
    start.mkdir()

    binding = resolve_project_store(start)
    assert binding.state == "designated"
    assert binding.path == start.resolve() / ".bantamkit" / "memory"
    assert binding.fact_count == 0


def test_resolve_three_states_are_three_values(tmp_path):
    populated = _mkstore(tmp_path / "full")
    (populated / "facts").mkdir()
    (populated / "facts" / "f.md").write_text("x", encoding="utf-8")
    empty = _mkstore(tmp_path / "hollow")
    fresh = tmp_path / "fresh"
    fresh.mkdir()

    states = {
        resolve_project_store(tmp_path / "full").state,
        resolve_project_store(tmp_path / "hollow").state,
        resolve_project_store(fresh).state,
    }
    assert states == {"populated", "empty", "designated"}
    assert empty.exists()


def test_resolve_creates_nothing(tmp_path):
    start = tmp_path / "fresh"
    start.mkdir()
    hollow = _mkstore(tmp_path / "hollow")

    resolve_project_store(start)
    resolve_project_store(tmp_path / "hollow")

    assert list(start.iterdir()) == []
    assert list(hollow.iterdir()) == []


def test_resolve_missing_facts_dir_is_empty_not_designated(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store / "archive").mkdir()

    binding = resolve_project_store(tmp_path / "companyA")
    assert binding.state == "empty"
    assert binding.path == store


def test_resolve_counts_only_the_files_the_store_reads(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store / "facts").mkdir()
    (store / "facts" / "real.md").write_text("x", encoding="utf-8")
    (store / "facts" / "notes.txt").write_text("x", encoding="utf-8")
    (store / "index.md").write_text("x", encoding="utf-8")

    assert resolve_project_store(tmp_path / "companyA").fact_count == 1


def test_resolve_path_never_disagrees_with_discover(tmp_path):
    populated = _mkstore(tmp_path / "full")
    (populated / "facts").mkdir()
    (populated / "facts" / "f.md").write_text("x", encoding="utf-8")
    _mkstore(tmp_path / "hollow")
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    deep = tmp_path / "full" / "src" / "deep"
    deep.mkdir(parents=True)

    for start in (tmp_path / "full", tmp_path / "hollow", fresh, deep):
        assert resolve_project_store(start).path == discover_project_store(start)


# --- the explicit pin -------------------------------------------------------
#
# The MCP server's cwd is chosen by the HOST, not the operator, so every rule
# derived from cwd is a rule the operator cannot control. `BANTAMKIT_MEMORY_DIR`
# is the one surface every host exposes. These nodes fix what it outranks and
# how loudly it fails; the name itself is imported, never spelled, so the
# resolver and its tests cannot drift onto two different variables.


@pytest.fixture(autouse=True)
def _no_ambient_pin(monkeypatch):
    """Every node above this point asserts walk behaviour; a pin in the real
    environment would silently answer for all of them."""
    monkeypatch.delenv(MEMORY_DIR_ENV, raising=False)


def test_pin_outranks_an_ancestor_store(tmp_path, monkeypatch):
    _mkstore(tmp_path / "companyA")
    pinned = _mkstore(tmp_path / "elsewhere")
    nested = tmp_path / "companyA" / "src"
    nested.mkdir()
    monkeypatch.setenv(MEMORY_DIR_ENV, str(pinned))

    assert discover_project_store(nested) == pinned


def test_pin_outranks_a_store_in_the_start_directory_itself(tmp_path, monkeypatch):
    own = _mkstore(tmp_path / "companyA")
    pinned = _mkstore(tmp_path / "elsewhere")
    monkeypatch.setenv(MEMORY_DIR_ENV, str(pinned))

    assert discover_project_store(tmp_path / "companyA") == pinned
    assert own.is_dir()  # the store it beat is still there, untouched


def test_pin_names_the_state_of_the_store_it_points_at(tmp_path, monkeypatch):
    pinned = _mkstore(tmp_path / "elsewhere")
    (pinned / "facts").mkdir()
    (pinned / "facts" / "f.md").write_text("x", encoding="utf-8")
    start = tmp_path / "fresh"
    start.mkdir()
    monkeypatch.setenv(MEMORY_DIR_ENV, str(pinned))

    binding = resolve_project_store(start)
    assert binding.path == pinned
    assert binding.state == "populated"
    assert binding.fact_count == 1


def test_pin_at_a_real_but_empty_store_is_not_an_error(tmp_path, monkeypatch):
    # A legitimate first run. N1 made this a nameable state precisely so it
    # would not have to be an error here.
    pinned = _mkstore(tmp_path / "elsewhere")
    monkeypatch.setenv(MEMORY_DIR_ENV, str(pinned))

    binding = resolve_project_store(tmp_path)
    assert binding.state == "empty"
    assert binding.fact_count == 0


def test_pin_at_nothing_raises_instead_of_designating(tmp_path, monkeypatch):
    missing = tmp_path / "typo" / "memory"
    monkeypatch.setenv(MEMORY_DIR_ENV, str(missing))

    with pytest.raises(MemoryValidationError) as e:
        discover_project_store(tmp_path)
    assert str(missing) in str(e.value)
    assert MEMORY_DIR_ENV in str(e.value)


def test_pin_at_nothing_is_loud_from_resolve_too(tmp_path, monkeypatch):
    monkeypatch.setenv(MEMORY_DIR_ENV, str(tmp_path / "typo"))
    with pytest.raises(MemoryValidationError):
        resolve_project_store(tmp_path)


def test_pin_at_nothing_creates_nothing(tmp_path, monkeypatch):
    missing = tmp_path / "typo"
    monkeypatch.setenv(MEMORY_DIR_ENV, str(missing))

    for call in (discover_project_store, resolve_project_store):
        with pytest.raises(MemoryValidationError):
            call(tmp_path)
    assert not missing.exists()
    assert list(tmp_path.iterdir()) == []


def test_pin_at_a_file_raises(tmp_path, monkeypatch):
    f = tmp_path / "memory"
    f.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv(MEMORY_DIR_ENV, str(f))

    with pytest.raises(MemoryValidationError):
        discover_project_store(tmp_path)


def test_pin_says_it_was_pinned_and_the_walk_says_it_walked(tmp_path, monkeypatch):
    pinned = _mkstore(tmp_path / "elsewhere")
    _mkstore(tmp_path / "companyA")

    assert resolve_project_store(tmp_path / "companyA").origin == "walk"
    monkeypatch.setenv(MEMORY_DIR_ENV, str(pinned))
    assert resolve_project_store(tmp_path / "companyA").origin == "pin"


def test_pinned_binding_does_not_claim_a_walk_it_never_ran(tmp_path, monkeypatch):
    pinned = _mkstore(tmp_path / "elsewhere")
    start = tmp_path / "companyA"
    start.mkdir()
    monkeypatch.setenv(MEMORY_DIR_ENV, str(pinned))

    binding = resolve_project_store(start)
    assert binding.searched_from is None


def test_pin_and_walk_never_disagree_under_a_pin(tmp_path, monkeypatch):
    pinned = _mkstore(tmp_path / "elsewhere")
    _mkstore(tmp_path / "companyA")
    monkeypatch.setenv(MEMORY_DIR_ENV, str(pinned))

    for start in (tmp_path, tmp_path / "companyA", tmp_path / "elsewhere"):
        assert resolve_project_store(start).path == discover_project_store(start)


def test_unset_pin_is_the_walk_untouched(tmp_path, monkeypatch):
    top = _mkstore(tmp_path / "companyA")
    nested = tmp_path / "companyA" / "src"
    nested.mkdir()
    monkeypatch.delenv(MEMORY_DIR_ENV, raising=False)

    assert discover_project_store(nested) == top
    assert resolve_project_store(nested).origin == "walk"


@pytest.mark.parametrize("blank", ["", " ", "\t\n"])
def test_a_blank_pin_is_not_a_pin(tmp_path, monkeypatch, blank):
    # A host that writes `"env": {"BANTAMKIT_MEMORY_DIR": ""}` has named no store.
    # Raising there would break the walk for someone who pinned nothing.
    top = _mkstore(tmp_path / "companyA")
    monkeypatch.setenv(MEMORY_DIR_ENV, blank)

    assert discover_project_store(tmp_path / "companyA") == top
    assert resolve_project_store(tmp_path / "companyA").origin == "walk"


def test_a_relative_pin_raises_even_when_it_would_have_resolved(tmp_path, monkeypatch):
    # A pin resolved against cwd is a pin whose meaning depends on the exact
    # thing the pin exists to escape. cwd is moved so the relative path DOES
    # name the store: a resolver that quietly resolved it would succeed here,
    # and the node would pass on the raise it never earned.
    store = _mkstore(tmp_path / "companyA")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(MEMORY_DIR_ENV, "companyA/.bantamkit/memory")
    assert store.is_dir()

    with pytest.raises(MemoryValidationError) as e:
        discover_project_store(tmp_path)
    assert "absolute" in str(e.value)
    assert MEMORY_DIR_ENV in str(e.value)


def test_pin_expands_the_home_shorthand(tmp_path, monkeypatch):
    # MCP hosts pass `env` verbatim: no shell runs, so `~` arrives literally.
    store = _mkstore(tmp_path / "home")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv(MEMORY_DIR_ENV, "~/.bantamkit/memory")

    assert discover_project_store(tmp_path) == store


def test_pin_to_a_symlinked_store_keeps_its_config_beside_the_symlink(tmp_path, monkeypatch):
    # Matches the walk's existing stance (test_load_grants_symlinked_store_reads
    # _adjacent_config): the store path is not symlink-resolved, so grants are
    # read next to the link the operator pinned.
    real_store = _mkstore(tmp_path / "realstore")
    proj = tmp_path / "proj"
    (proj / ".bantamkit").mkdir(parents=True)
    link = proj / ".bantamkit" / "memory"
    link.symlink_to(real_store)
    other = _mkstore(tmp_path / "other")
    (proj / ".bantamkit" / "config.yaml").write_text(
        "extra_stores:\n  - ../../other/.bantamkit/memory\n", encoding="utf-8"
    )
    monkeypatch.setenv(MEMORY_DIR_ENV, str(link))

    found = discover_project_store(tmp_path)
    assert found == link
    assert load_grants(found) == [other.resolve()]


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores mode bits")
def test_an_unreadable_pin_is_loud_and_says_why(tmp_path, monkeypatch):
    # Path.is_dir() swallows PermissionError and answers False. On the walk that
    # is pre-existing; on a pin it would report the operator's own store as a
    # typo. The pin is new surface, so it gets the accurate answer.
    parent = tmp_path / "locked"
    store = parent / "memory"
    store.mkdir(parents=True)
    parent.chmod(0o000)
    monkeypatch.setenv(MEMORY_DIR_ENV, str(store))
    try:
        with pytest.raises(MemoryValidationError) as e:
            discover_project_store(tmp_path)
        message = str(e.value)
    finally:
        parent.chmod(0o755)
    assert "ermission" in message
    assert str(store) in message


# --- F1: an unreadable store is not an empty one ------------------------------
#
# `resolve_project_store`'s docstring has asserted this raise since the function
# was written, and the raise never happened: `Path.glob` suppresses the OSError
# from its directory scan and yields nothing, so a store holding a fact at mode
# 0o000 came back `state="empty", fact_count=0`. The only `chmod(0o000)` in this
# file before now locks a PIN's parent, which exercises `os.stat` -- the
# unreadability that was handled. This is the one that was documented and not.


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores mode bits")
def test_a_store_whose_facts_cannot_be_read_is_never_called_empty(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    facts = store / "facts"
    facts.mkdir()
    (facts / "a-fact.md").write_text("x", encoding="utf-8")
    facts.chmod(0o000)
    try:
        with pytest.raises(MemoryValidationError) as e:
            resolve_project_store(tmp_path / "companyA")
        message = str(e.value)
    finally:
        facts.chmod(0o755)
    assert str(facts) in message
    assert "ermission" in message


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores mode bits")
def test_an_unreadable_pinned_store_is_loud_too(tmp_path, monkeypatch):
    """A pin skips the walk, so it reaches the count by its own route."""
    store = tmp_path / "pinned"
    facts = store / "facts"
    facts.mkdir(parents=True)
    (facts / "a-fact.md").write_text("x", encoding="utf-8")
    facts.chmod(0o000)
    monkeypatch.setenv(MEMORY_DIR_ENV, str(store))
    try:
        with pytest.raises(MemoryValidationError):
            resolve_project_store(tmp_path)
    finally:
        facts.chmod(0o755)


def test_a_readable_store_is_still_counted_exactly_as_before(tmp_path):
    """The raise must not be bought by changing what a countable store counts."""
    store = _mkstore(tmp_path / "companyA")
    facts = store / "facts"
    facts.mkdir()
    for name in ("real.md", ".hidden.md", "notes.txt"):
        (facts / name).write_text("x", encoding="utf-8")
    (facts / "dir.md").mkdir()

    binding = resolve_project_store(tmp_path / "companyA")
    assert binding.fact_count == len(list(facts.glob("*.md")))
    assert binding.state == "populated"


# --- F6: the guard in conftest, which had no node -----------------------------
#
# `conftest._no_ambient_memory_pin` deletes BANTAMKIT_MEMORY_DIR for every node in
# the suite. Deleting its body left CI green, because CI has no ambient pin: the
# fixture that protects every other node was the one change in this job with
# nothing watching it. These two nodes watch it, and neither can be satisfied by
# an environment that happens to be clean.


def test_the_ambient_pin_guard_reaches_this_node_without_being_asked(request):
    """autouse, not opt-in: a node that has to remember to ask is not a guard."""
    assert "_no_ambient_memory_pin" in request.fixturenames
    assert MEMORY_DIR_ENV not in os.environ


def test_the_ambient_pin_guard_puts_back_the_store_a_pin_had_taken(tmp_path, monkeypatch, request):
    """The hazard and the guard in one node, so the guard cannot be emptied quietly.

    The fixture's own function is called here rather than re-implemented: a copy of
    the body would keep passing after the body it copies is deleted, which is
    exactly the failure this node exists to catch.

    THIS NODE'S OWN `request` is handed over, not a stub. The fixture grew a
    `realpair` exemption on a sibling branch, and passing a real unmarked request
    is what proves an ordinary node is not exempt -- a stub would have been written
    to whatever the fixture happened to read that day. Calling it with `monkeypatch`
    alone stopped working the moment the exemption landed, which is how the two
    branches discovered they disagreed.
    """
    import conftest  # noqa: PLC0415

    own = _mkstore(tmp_path / "companyA")
    (own / "facts").mkdir()
    elsewhere = _mkstore(tmp_path / "elsewhere")
    (elsewhere / "facts").mkdir()

    monkeypatch.setenv(MEMORY_DIR_ENV, str(elsewhere))
    assert resolve_project_store(tmp_path / "companyA").path == elsewhere, (
        "an ambient pin outranks the walk -- this is what the guard is for"
    )

    conftest._no_ambient_memory_pin.__wrapped__(request, monkeypatch)

    assert MEMORY_DIR_ENV not in os.environ
    assert resolve_project_store(tmp_path / "companyA").path == own


# ---------------------------------------------------------------------------
# J37/W2 DEFERRED: the one shape on which the binding layer and the store layer
# still give different answers. Marked, not silently skipped.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFERRED to a follow-up on the BINDING layer. `count_facts` maps every "
        "FileNotFoundError to 0, so a `facts/` that is a dangling symlink counts as an "
        "empty store, while `MemoryStore._fact_paths` (J37/W1) raises on the same shape "
        "because it keys 'first run' on os.path.lexists rather than on the errno. J37 "
        "was chartered on the store layer and this fix belongs in memory/layers.py with "
        "its own argument for changing count_facts' documented 'absent facts/ is 0 and "
        "not an error' contract. strict=True so the day it is fixed this node fails as "
        "XPASS and the mark has to come off, rather than the deferral outliving the defect."
    ),
)
def test_a_dangling_facts_symlink_is_unreadable_to_both_layers(tmp_path):
    """The two layers must not disagree about whether a store can be read.

    MEASURED 2026-08-23, and it reaches a person: with this shape on a read-only GRANT
    layer, `Memory.recall` skips the layer and `_nothing_to_report` then says "no
    memories to search: nothing is saved in any layer bound here." The same grant at
    0o311 correctly says "... could not be read." One unreadable store, two sentences,
    and the wrong one is the one that tells the operator to stop looking.

    Not a `windows_cannot_construct` mark: the symlink is attempted and the node reports
    honestly when the platform declines it, the ruling W1 already made for
    `test_a_root_that_denies_listing_is_unreadable_not_absent`.
    """
    store = _mkstore(tmp_path / "companyA")
    try:
        (store / "facts").symlink_to(tmp_path / "nowhere-at-all")
    except (OSError, NotImplementedError):  # pragma: no cover - Windows without privilege
        pytest.skip(
            "this platform cannot create a symlink without privilege (Windows without "
            "developer mode), so the dangling-`facts/` shape cannot be constructed and "
            "this run FAILS TO MEASURE whether the binding layer and the store layer "
            "agree that such a store is unreadable."
        )

    with pytest.raises(MemoryValidationError) as e:
        resolve_project_store(tmp_path / "companyA")
    assert str(store / "facts") in str(e.value)


def test_w5_diagnostic_dangling_facts_symlink_observations(tmp_path):
    """TEMPORARY W5 INSTRUMENT -- deliberately red so CI prints what it observed."""
    from bantamkit.memory.layers import count_facts

    store = _mkstore(tmp_path / "companyA")
    obs = {"platform": os.name, "sys": sys.platform}
    try:
        (store / "facts").symlink_to(tmp_path / "nowhere-at-all")
        obs["symlink_to"] = "created"
    except (OSError, NotImplementedError) as e:
        obs["symlink_to"] = f"REFUSED {type(e).__name__} {e}"
    facts = store / "facts"
    obs["lexists"] = os.path.lexists(facts)
    obs["exists"] = os.path.exists(facts)
    obs["islink"] = os.path.islink(facts)
    obs["is_dir"] = facts.is_dir()
    try:
        with os.scandir(facts) as entries:
            obs["scandir"] = f"OK {len(list(entries))} entries"
    except OSError as e:
        obs["scandir"] = (
            f"{type(e).__name__} errno={e.errno} winerror={getattr(e, 'winerror', None)} "
            f"strerror={e.strerror}"
        )
    try:
        obs["count_facts"] = count_facts(store)
    except OSError as e:
        obs["count_facts"] = (
            f"raised {type(e).__name__} errno={e.errno} winerror={getattr(e, 'winerror', None)}"
        )
    try:
        obs["resolve"] = repr(resolve_project_store(tmp_path / "companyA"))
    except Exception as e:  # noqa: BLE001
        obs["resolve"] = f"raised {type(e).__name__}: {e}"
    raise AssertionError("W5-DIAGNOSTIC " + repr(obs))
