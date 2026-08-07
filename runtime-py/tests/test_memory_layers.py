import pytest

from bantamkit.memory.layers import discover_project_store, load_grants
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
    (store.parent / "config.yaml").write_text("")
    assert load_grants(store) == []


def test_load_grants_resolves_relative_to_config(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    other = _mkstore(tmp_path / "companyB")
    (store.parent / "config.yaml").write_text(
        "extra_stores:\n  - ../../companyB/.bantamkit/memory\n"
    )
    assert load_grants(store) == [other.resolve()]


def test_load_grants_malformed_yaml_raises(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text("extra_stores: [unclosed\n")
    with pytest.raises(MemoryValidationError):
        load_grants(store)


def test_load_grants_non_mapping_config_raises(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text("just a string\n")
    with pytest.raises(MemoryValidationError):
        load_grants(store)


def test_load_grants_dangling_path_raises(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text("extra_stores:\n  - ../../nope/memory\n")
    with pytest.raises(MemoryValidationError):
        load_grants(store)


def test_discover_with_start_as_store_directory(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    result = discover_project_store(tmp_path / "companyA")
    assert result == store


def test_discover_skips_file_named_store(tmp_path):
    real_store = _mkstore(tmp_path)
    ancestor = tmp_path / "ancestor"
    ancestor.mkdir()
    (ancestor / ".bantamkit").mkdir()
    (ancestor / ".bantamkit" / "memory").write_text("not a directory")

    start = ancestor / "src"
    start.mkdir()
    assert discover_project_store(start) == real_store


def test_discover_symlinked_start_resolves(tmp_path):
    real_proj = _mkstore(tmp_path / "companyA")
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "companyA")

    result = discover_project_store(link / "src")
    assert result == real_proj
    assert result == real_proj.resolve()


def test_load_grants_config_as_directory_raises(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").mkdir()
    with pytest.raises(MemoryValidationError):
        load_grants(store)


def test_load_grants_no_extra_stores_key_is_empty(tmp_path):
    store = _mkstore(tmp_path / "companyA")
    (store.parent / "config.yaml").write_text("some_other_key: value\n")
    assert load_grants(store) == []
