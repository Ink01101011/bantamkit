"""J51-1 / J51-8a: a `.bantamkit` directory ignores itself in git — but ONLY the one
bantamkit itself brings into existence.

User ruling 2026-09-15 (`.shiftwork/notes-job51/P0-probes.md`): `.bantamkit` stays out of
git by default via a self-ignoring `.bantamkit/.gitignore` (`*`), never by editing the
repository's own `.gitignore`. The property, from `.shiftwork/briefs-job51/J51-1.md`,
AS AMENDED by user ruling #2 (2026-09-15, `.shiftwork/briefs-job51/J51-8a.md`) after J51-8
measured that a deleted ignore file came back on the next save and that a store a team
already commits would silently start ignoring new fact files after an upgrade:

1. The ignore file is written IF AND ONLY IF, in this call, the `.bantamkit` directory
   did not exist immediately before the directories were made and exists afterwards.
   "Did not exist" is decided by checking the `.bantamkit` directory itself BEFORE the
   mkdir — never the `.gitignore` file, never `memory/`. (Was: written whenever the
   store's directories are brought into existence and the ignore file itself is absent,
   regardless of whether `.bantamkit` already existed — J51-8 measured this makes
   deletion not stick.)
2. A `.bantamkit` directory that already existed — made by an earlier bantamkit, by hand,
   or checked out from git; with or without a `.gitignore` — is never given one. In
   particular, an existing `.gitignore` is never rewritten (unchanged from J51-1).
3. Writing it is best-effort: an unwritable `.gitignore` never fails the write that
   triggered it.
4. A store whose parent is not named `.bantamkit` gets no `.gitignore` anywhere.
5. End-to-end: a fresh `git init` directory shows nothing under `.bantamkit` in
   `git status --porcelain --untracked-files=all` after a `memory_save`.
6. Consequence of 1: deleting the file after bantamkit created it, then saving again,
   leaves it deleted — the file's own first line ("Delete this file to commit it") is
   now true.

Also covers the bypass this audit found: `EventLog._append`'s own
`self.path.parent.mkdir(parents=True, exist_ok=True)` can bring a `.bantamkit` directory
into existence WITHOUT ever calling `MemoryStore._ensure_dirs` — e.g. when
`BANTAMKIT_EVENT_LOG=on` and the project store has never been saved to. That path must
carry the same gitignore-write (and the same "only if `.bantamkit` did not already
exist" gate), or a `.bantamkit` created that way is never ignored, or is ignored when it
should not be.
"""

import shutil
import subprocess

import pytest

from bantamkit.eventlog import EventLog, default_path
from bantamkit.memory import Memory, MemoryStore
from bantamkit.memory.store import BANTAMKIT_GITIGNORE_TEXT, ensure_bantamkit_gitignore


def test_property_1_gitignore_written_when_store_root_parent_is_dot_bantamkit(tmp_path):
    root = tmp_path / ".bantamkit" / "memory"
    MemoryStore(root)  # create=True by default; brings facts/ and archive/ into existence

    gitignore = tmp_path / ".bantamkit" / ".gitignore"
    assert gitignore.exists()
    assert gitignore.read_bytes() == BANTAMKIT_GITIGNORE_TEXT.encode("utf-8")


def test_property_1_also_fires_on_save_not_only_construction(tmp_path):
    root = tmp_path / ".bantamkit" / "memory"
    store = MemoryStore(root, create=False)
    gitignore = tmp_path / ".bantamkit" / ".gitignore"
    assert not gitignore.exists()

    store.save("project", "widget-cache", "one line", "body", ())

    assert gitignore.exists()
    assert gitignore.read_text(encoding="utf-8") == BANTAMKIT_GITIGNORE_TEXT


def test_property_2_an_existing_gitignore_is_never_rewritten(tmp_path):
    root = tmp_path / ".bantamkit" / "memory"
    bantamkit_dir = tmp_path / ".bantamkit"
    bantamkit_dir.mkdir()
    gitignore = bantamkit_dir / ".gitignore"
    gitignore.write_text("operator's own content\n", encoding="utf-8")

    store = MemoryStore(root)
    store.save("project", "widget-cache", "one line", "body", ())
    store.compact()

    assert gitignore.read_text(encoding="utf-8") == "operator's own content\n"


def test_property_3_unwritable_gitignore_is_best_effort(tmp_path, monkeypatch):
    root = tmp_path / ".bantamkit" / "memory"

    from pathlib import Path

    real_write_text = Path.write_text

    def refuse(self, *args, **kwargs):
        if self.name == ".gitignore":
            raise OSError("simulated: read-only filesystem")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", refuse)

    store = MemoryStore(root)  # must not raise
    result = store.save("project", "widget-cache", "one line", "body", ())  # must not raise

    assert result.status == "saved"
    assert not (tmp_path / ".bantamkit" / ".gitignore").exists()


def test_property_4_store_not_under_dot_bantamkit_gets_no_gitignore(tmp_path):
    root = tmp_path / "somewhere" / "mem"
    MemoryStore(root)

    assert not (tmp_path / "somewhere" / ".gitignore").exists()
    assert not (tmp_path / ".gitignore").exists()


def test_ensure_bantamkit_gitignore_is_a_noop_off_a_non_bantamkit_directory(tmp_path):
    """API change for J51-8a: `created` is now a required keyword — the caller must say
    whether ITS OWN mkdir is what brought `directory` into existence. Passed `True` here
    on purpose: the name check must refuse even when the caller claims a fresh creation.
    """
    directory = tmp_path / "not-bantamkit"
    directory.mkdir()
    ensure_bantamkit_gitignore(directory, created=True)
    assert list(directory.iterdir()) == []


def test_property_1_amended_existing_bantamkit_without_gitignore_gets_none_on_save(tmp_path):
    """J51-8a (a): a `.bantamkit` that already existed — with no `.gitignore` in it —
    never gets one, even though the ignore file itself is absent. FAILS on the
    pre-J51-8a source, which writes whenever the file is absent.
    """
    bantamkit_dir = tmp_path / ".bantamkit"
    bantamkit_dir.mkdir()
    gitignore = bantamkit_dir / ".gitignore"
    assert not gitignore.exists()

    root = bantamkit_dir / "memory"
    store = MemoryStore(root)
    store.save("project", "widget-cache", "one line", "body", ())

    assert not gitignore.exists()


def test_property_1_amended_deleting_the_gitignore_after_creation_stays_deleted(tmp_path):
    """J51-8a (b): bantamkit creates `.bantamkit` itself, so the ignore file is written —
    delete it, save again, and it must stay deleted. FAILS on the pre-J51-8a source,
    which rewrites it on the next save because the file is absent.
    """
    root = tmp_path / ".bantamkit" / "memory"
    gitignore = tmp_path / ".bantamkit" / ".gitignore"

    store = MemoryStore(root)
    assert gitignore.exists()

    gitignore.unlink()
    store.save("project", "widget-cache", "one line", "body", ())

    assert not gitignore.exists()


def test_eventlog_amended_existing_bantamkit_without_gitignore_gets_none(tmp_path):
    """J51-8a (c), condition (a): the event-log creator follows the same rule — a
    `.bantamkit` that already existed, with no `.gitignore`, is left alone.
    """
    bantamkit_dir = tmp_path / ".bantamkit"
    bantamkit_dir.mkdir()
    gitignore = bantamkit_dir / ".gitignore"
    assert not gitignore.exists()

    store_root = bantamkit_dir / "memory"
    log = EventLog(default_path(store_root))
    log.record("memory_save", "saved", {"budget": 1, "index_bytes": 1})

    assert log.write_failed is False
    assert not gitignore.exists()


def test_eventlog_amended_deleting_the_gitignore_after_creation_stays_deleted(tmp_path):
    """J51-8a (c), condition (b): the event-log creator brought `.bantamkit` into
    existence itself, so deleting the ignore file it wrote must stick on the next append.
    """
    store_root = tmp_path / ".bantamkit" / "memory"
    gitignore = tmp_path / ".bantamkit" / ".gitignore"

    log = EventLog(default_path(store_root))
    log.record("memory_save", "saved", {"budget": 1, "index_bytes": 1})
    assert gitignore.exists()

    gitignore.unlink()
    log.record("memory_save", "saved", {"budget": 1, "index_bytes": 1})

    assert not gitignore.exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")
def test_property_5_end_to_end_git_status_is_clean_under_dot_bantamkit(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)

    memory = Memory(tmp_path / ".bantamkit" / "memory")
    outcome = memory.save_outcome("project", "widget-cache", "one line", "body", ())
    assert outcome.status == "saved"

    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    bantamkit_lines = [line for line in result.stdout.splitlines() if ".bantamkit" in line]
    assert bantamkit_lines == []


def test_eventlog_mkdir_bypass_still_gets_the_gitignore(tmp_path):
    """The finding: `EventLog._append` mkdir's a `.bantamkit` tree on its own when the
    project store was never saved to. That must not skip the gitignore write.
    """
    store_root = tmp_path / ".bantamkit" / "memory"
    assert not (tmp_path / ".bantamkit").exists()

    log = EventLog(default_path(store_root))
    log.record("memory_save", "saved", {"budget": 1, "index_bytes": 1})

    assert log.write_failed is False
    gitignore = tmp_path / ".bantamkit" / ".gitignore"
    assert gitignore.exists()
    assert gitignore.read_text(encoding="utf-8") == BANTAMKIT_GITIGNORE_TEXT


def test_eventlog_path_unrelated_to_dot_bantamkit_writes_no_gitignore(tmp_path):
    log = EventLog(tmp_path / "custom" / "log.jsonl")
    log.record("memory_save", "saved", {"budget": 1, "index_bytes": 1})

    assert log.write_failed is False
    assert not list(tmp_path.glob("**/.gitignore"))
