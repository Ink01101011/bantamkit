import pytest

from bantamkit.memory.__main__ import main as memory_main
from bantamkit.memory.store import MemoryStore, MemoryValidationError


def _store(tmp_path):
    return MemoryStore(tmp_path / "mem", index_budget=100_000, today=lambda: "2026-10-21")


def test_outcome_and_status_round_trip_and_are_written_after_links(tmp_path):
    store = _store(tmp_path)
    store.save(
        "feedback", "lesson-a", "a lesson about alpha", "body", outcome="error", status="done"
    )
    text = (store.root / "facts" / "lesson-a.md").read_text(encoding="utf-8")
    keys = ("links: []\n", "outcome: error\n", "status: done\n")
    links, outcome, status = (text.index(k) for k in keys)
    assert links < outcome < status
    [fact] = store.recall("lesson alpha")
    assert (fact.outcome, fact.status) == ("error", "done")


def test_a_fact_saved_without_the_new_fields_is_byte_identical_to_before(tmp_path):
    store = _store(tmp_path)
    store.save("project", "plain-fact", "a plain description", "body")
    text = (store.root / "facts" / "plain-fact.md").read_text(encoding="utf-8")
    assert "outcome" not in text and "status" not in text
    assert text == (
        "---\nname: plain-fact\ndescription: a plain description\ntype: project\n"
        "created: '2026-10-21'\nlast_recalled: null\nlinks: []\n---\n\nbody\n"
    )


def test_status_active_is_never_written(tmp_path):
    store = _store(tmp_path)
    store.save("project", "p", "a description", "b", status="active")
    assert "status" not in (store.root / "facts" / "p.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "kwargs, sentence",
    [
        ({"outcome": "meh"}, "invalid outcome 'meh'; must be one of ['error', 'success']"),
        ({"status": "gone"}, "invalid status 'gone'; must be one of ['active', 'done']"),
    ],
)
def test_unknown_outcome_or_status_is_refused_with_the_sentence(tmp_path, kwargs, sentence):
    store = _store(tmp_path)
    with pytest.raises(MemoryValidationError) as e:
        store.save("project", "p", "a description", "b", **kwargs)
    assert str(e.value) == sentence
    assert not (store.root / "facts" / "p.md").exists()


def test_outcome_is_refused_on_user_and_reference_facts(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(MemoryValidationError) as e:
        store.save("reference", "r", "a description", "b", outcome="success")
    assert str(e.value) == (
        "invalid outcome 'success' for type 'reference'; "
        "outcome is only for feedback and project facts"
    )


def test_memory_keeper_metadata_is_read_as_an_alias_and_not_rewritten(tmp_path):
    store = _store(tmp_path)
    store._ensure_dirs()
    raw = (
        "---\nname: old-lesson\ndescription: an old lesson about gamma\n"
        "metadata:\n  type: feedback\n  loop: error\n  status: done\n---\n\nbody\n"
    )
    (store.root / "facts" / "old-lesson.md").write_text(raw, encoding="utf-8")
    [fact] = store.recall("old lesson gamma", stamp=False)
    assert (fact.type, fact.outcome, fact.status) == ("feedback", "error", "done")
    assert (store.root / "facts" / "old-lesson.md").read_text(encoding="utf-8") == raw


def test_alias_values_outside_the_enums_read_as_absent(tmp_path):
    store = _store(tmp_path)
    store._ensure_dirs()
    (store.root / "facts" / "r.md").write_text(
        "---\nname: r\ndescription: a reflexion pattern about delta\ntype: feedback\n"
        "metadata:\n  loop: reflexion\n  status: archived\n---\n\nbody\n",
        encoding="utf-8",
    )
    [fact] = store.recall("reflexion pattern delta", stamp=False)
    assert fact.outcome is None
    assert fact.status == "done"  # `archived` reads as done, per spec §1


def test_recall_with_outcome_keeps_only_matching_hits(tmp_path):
    store = _store(tmp_path)
    store.save("feedback", "bad-one", "lesson zeta pipeline crashed", "b", outcome="error")
    store.save("feedback", "good-one", "lesson zeta rollout shipped", "b", outcome="success")
    store.save("feedback", "plain-one", "lesson zeta weekly sync agenda", "b")
    assert [f.name for f in store.recall("lesson zeta", k=5, outcome="error")] == ["bad-one"]
    assert [f.name for f in store.recall("lesson zeta", k=5, outcome="success")] == ["good-one"]
    assert len(store.recall("lesson zeta", k=5)) == 3


def test_list_facts_filters_and_sorts_by_name(tmp_path):
    store = _store(tmp_path)
    store.save("feedback", "b-err", "about b", "b", outcome="error")
    store.save("feedback", "a-ok", "about a", "b", outcome="success")
    store.save("project", "c-done", "about c", "b", status="done")
    assert [f.name for f in store.list_facts()] == ["a-ok", "b-err", "c-done"]
    assert [f.name for f in store.list_facts(outcome="error")] == ["b-err"]
    assert [f.name for f in store.list_facts(type="project", status="done")] == ["c-done"]
    assert [f.name for f in store.list_facts(status="active")] == ["a-ok", "b-err"]


def test_list_cli_prints_one_line_per_fact(tmp_path, capsys):
    store = _store(tmp_path)
    store.save("feedback", "b-err", "about b", "b", outcome="error")
    store.save("project", "c-done", "about c", "b", status="done")
    assert memory_main(["list", "--store", str(store.root)]) == 0
    assert capsys.readouterr().out == (
        f"facts: 2 ({store.root / 'facts'})\n"
        "b-err\tfeedback\terror\tactive\tabout b\n"
        "c-done\tproject\t-\tdone\tabout c\n"
    )
    assert memory_main(["list", "--outcome", "error", "--store", str(store.root)]) == 0
    assert (
        capsys.readouterr().out
        == f"facts: 1 ({store.root / 'facts'})\nb-err\tfeedback\terror\tactive\tabout b\n"
    )


def test_list_cli_refuses_an_unknown_filter_value_as_usage(tmp_path):
    with pytest.raises(SystemExit) as e:
        memory_main(["list", "--outcome", "meh", "--store", str(tmp_path)])
    assert e.value.code == 2
