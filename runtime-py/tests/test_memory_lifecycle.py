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


def test_candidates_reasons_in_order_and_feedback_done_words_do_not_count(tmp_path):
    store = _store(tmp_path)
    store.save("project", "p-done", "a thing", "b", status="done")
    store.save("project", "p-word", "the release was Shipped yesterday", "b")
    store.save("feedback", "f-word", "close issues with comment when done", "b")
    store.save("project", "p-old", "an old project note", "b")
    store.save("project", "p-both", "merged and closed", "b", status="done")
    path = store.root / "facts" / "p-old.md"
    path.write_text(path.read_text().replace("'2026-10-21'", "'2026-01-01'"))
    got = [(f.name, r) for f, r in store.candidates_done()]
    assert got == [
        ("p-both", "status: done"),
        ("p-done", "status: done"),
        ("p-word", "done-word 'shipped' in description"),
    ]
    got = [(f.name, r) for f, r in store.candidates_done(older_than_days=30, today="2026-10-21")]
    assert ("p-old", "older than 30d (created 2026-01-01)") in got
    assert all(n != "f-word" for n, _ in got)


def test_candidates_cli_is_a_dry_run_unless_apply(tmp_path, capsys):
    store = _store(tmp_path)
    store.save("project", "p-done", "a thing", "b", status="done")
    store.save("project", "p-live", "another unrelated matter entirely", "b")
    before = sorted(p.name for p in (store.root / "facts").iterdir())
    assert memory_main(["candidates", "--store", str(store.root)]) == 0
    out = capsys.readouterr().out
    assert out == (
        f"archive candidates: 1 ({store.root / 'facts'})\n"
        "p-done\tstatus: done\ta thing\n"
        "dry run; rerun with --apply to archive these 1\n"
    )
    assert sorted(p.name for p in (store.root / "facts").iterdir()) == before
    assert memory_main(["candidates", "--apply", "--store", str(store.root)]) == 0
    assert store.archived() == ["p-done"]
    assert capsys.readouterr().out.splitlines()[-1].startswith("archived 1 — index now ")


def _merge_store(tmp_path):
    store = _store(tmp_path)
    store.save("feedback", "l-one", "kappa lesson about retries", "one", outcome="error")
    store.save("feedback", "l-two", "second lesson regarding cache invalidation", "two",
               links=("l-one",))
    store.save("feedback", "l-three", "third lesson on naming of branches", "three")
    store.save("project", "pointer", "points at a lesson", "p", links=("l-two", "elsewhere"))
    return store


def test_merge_dry_run_writes_nothing_and_apply_writes_then_archives(tmp_path, capsys):
    store = _merge_store(tmp_path)
    snapshot = {p.name: p.read_bytes() for p in (store.root / "facts").iterdir()}
    argv = ["merge", "--names", "l-one", "l-two", "l-three", "--name", "kappa-pattern",
            "--type", "feedback", "--description", "the kappa pattern",
            "--body", "always kappa", "--store", str(store.root)]
    assert memory_main(argv) == 0
    out = capsys.readouterr().out
    assert out.startswith("consumes:\n  l-one\tfeedback\tkappa lesson about retries\n")
    assert "produces:\n---\nname: kappa-pattern\n" in out
    assert "Sources: l-one, l-two, l-three\n" in out
    assert "links pointing at consumed facts:\n  pointer -> l-two\n" in out
    assert out.endswith("dry run; rerun with --apply to write\n")
    assert {p.name: p.read_bytes() for p in (store.root / "facts").iterdir()} == snapshot
    assert memory_main([*argv, "--apply"]) == 0
    assert store.archived() == ["l-one", "l-three", "l-two"]
    [fact] = store.recall("kappa pattern", stamp=False)
    assert fact.body == "always kappa\n\nSources: l-one, l-two, l-three"
    # union of the consumed facts' links minus the consumed names: l-two's only link is l-one
    assert fact.links == []


@pytest.mark.parametrize(
    "names, new, sentence",
    [
        (["l-one", "nope"], "x", "merge needs at least two distinct live facts; missing: nope"),
        (["l-one", "l-one"], "x", "merge needs at least two distinct live facts; missing: none"),
        (["l-one", "l-two"], "l-one",
         "cannot merge into 'l-one': it is one of the facts being merged"),
        (["l-one", "l-two"], "pointer", "cannot merge into 'pointer': a fact of that name exists"),
    ],
)
def test_merge_refusals(tmp_path, names, new, sentence):
    store = _merge_store(tmp_path)
    with pytest.raises(MemoryValidationError) as e:
        store.merge(names, new, "feedback", "d", "b")
    assert str(e.value) == sentence


def test_merge_refuses_an_archived_target_name(tmp_path):
    store = _merge_store(tmp_path)
    store.archive("pointer")
    with pytest.raises(MemoryValidationError, match="a fact of that name exists"):
        store.merge(["l-one", "l-two"], "pointer", "feedback", "d", "b")
