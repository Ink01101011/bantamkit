import pytest

from bantamkit.memory.layers import (
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
