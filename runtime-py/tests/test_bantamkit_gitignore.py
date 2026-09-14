"""J51-1: a `.bantamkit` directory ignores itself in git.

User ruling 2026-09-15 (`.shiftwork/notes-job51/P0-probes.md`): `.bantamkit` stays out of
git by default via a self-ignoring `.bantamkit/.gitignore` (`*`), never by editing the
repository's own `.gitignore`. The property, from `.shiftwork/briefs-job51/J51-1.md`:

1. Whenever a memory store's directories are brought into existence and the store root's
   parent directory is named `.bantamkit`, afterwards `<that .bantamkit>/.gitignore`
   exists holding exactly `BANTAMKIT_GITIGNORE_TEXT`.
2. An existing `.bantamkit/.gitignore` is never rewritten.
3. Writing it is best-effort: an unwritable `.gitignore` never fails the write that
   triggered it.
4. A store whose parent is not named `.bantamkit` gets no `.gitignore` anywhere.
5. End-to-end: a fresh `git init` directory shows nothing under `.bantamkit` in
   `git status --porcelain --untracked-files=all` after a `memory_save`.

Also covers the bypass this audit found: `EventLog._append`'s own
`self.path.parent.mkdir(parents=True, exist_ok=True)` can bring a `.bantamkit` directory
into existence WITHOUT ever calling `MemoryStore._ensure_dirs` — e.g. when
`BANTAMKIT_EVENT_LOG=on` and the project store has never been saved to. That path must
carry the same gitignore-write, or a `.bantamkit` created that way is never ignored.
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
    directory = tmp_path / "not-bantamkit"
    directory.mkdir()
    ensure_bantamkit_gitignore(directory)
    assert list(directory.iterdir()) == []


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
