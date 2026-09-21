"""A — the one-way export of bantamkit fact descriptions into Claude Code's OWN auto-memory
directory, PYTHON half, and the resolver that finds that directory without recomputing the
host's slug.

THE PORT IS THE POINT. `runtime-ts/test/nativeexport.test.mjs` pins these same 23 facts on
the other side (J62-6); this file is the Python half's gate, and the two are written case for
case so that a divergence is a named line rather than a file only one runtime has. CLAUDE.md's
rule is that a feature lands in BOTH runtimes or it does not land, and until this file existed
only Node exported: `_native_memory_exists` still answered the SessionStart injection question
from an incomplete slug, so the two runtimes injected different blocks for the same cwd.

WHY THIS FILE EXISTS, in two halves.

1. THE DEBT. `_native_memory_exists` answered "does the host have an auto-memory store for
   this cwd" with `re.sub(r"[\\\\/:]", "-", cwd)` — an incomplete reimplementation of the
   host's slug, on the hook path, and its own docstring said so. S0
   (`.shiftwork/notes-job62/S0-prep-probe.md`) dumped the real resolver out of `2.1.278`:
   four branches, a 200-character cap with a base36 hash suffix, and a key that is the
   CANONICALIZED GIT WORKTREE ROOT, not the cwd. Job62 runs inside a worktree, which is
   exactly the case the old rule got wrong. The fix is not a better slug — it is to stop
   computing one and read the answer back instead.

2. THE EXPORT. RULING Q1.2/Q1.3/Q1.5 of `.shiftwork/notes-job62/S1-delivery-path.md`. A
   learns the directory by OBSERVATION WITH VERIFICATION (env override, then
   `autoMemoryDirectory` from `<home>/.claude/settings.json`, then
   `dirname(transcript_path)/memory`, each of the last two accepted only when it holds a
   readable `MEMORY.md`), exports NOTHING when no branch answers, and writes a name only when
   that name is ABSENT. It never rewrites an entry, never deletes one, and never creates the
   directory or `MEMORY.md`.

THE TESTS ARE PROCESS-LEVEL, for `test_hookadapter.py`'s reason: an arm that has only ever
been READ is how the PreCompact channel defect shipped. Each case feeds
`python -m bantamkit.mcpserver --hook` a real payload on a real stdin.

NOTHING HERE TOUCHES THE REAL HOME. Every run gets a scratch HOME **and** a scratch
USERPROFILE, and `_run_hook` ASSERTS the adapter followed it — the hook log has to be under
the scratch home — before any case looks at what was written. That assertion is not a style
note: J62-5 lost the operator's real `~/.claude/settings.json` to a probe that set only
`COLUMNS`/`LINES`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


def _env(home: Path) -> dict[str, str]:
    """The child's environment, with every RESOLVER INPUT removed unless a case sets it.

    `BANTAMKIT_MEMORY_DIR` and `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` are both inputs here, and
    a case that silently read the operator's own value would be measuring this machine rather
    than the code.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.pop("BANTAMKIT_MEMORY_DIR", None)
    env.pop("CLAUDE_COWORK_MEMORY_PATH_OVERRIDE", None)
    return env


class HookResult:
    def __init__(self, proc, home: Path, cwd: Path, records: list[dict]):
        self.proc = proc
        self.home = home
        self.cwd = cwd
        self.records = records
        # THE LAST such record, not the first. A case that runs the hook twice over ONE
        # scratch home appends to one log, and reading the first record would have every
        # second-run assertion silently measuring the first run. (The Node file sidesteps
        # this by giving every call a fresh home; reading the last record is the same fact
        # stated in the test rather than in the fixture.)
        self.record = next(
            (r for r in reversed(records) if r.get("event") == "SessionStart" and "bytes" in r),
            None,
        )

    @property
    def returncode(self) -> int:
        return self.proc.returncode

    @property
    def stdout(self) -> str:
        return self.proc.stdout.decode("utf-8")


def _run_hook(
    payload: dict,
    *,
    home: Path,
    cwd: Path,
    env_extra: dict[str, str] | None = None,
) -> HookResult:
    body: dict = {"cwd": str(cwd), "session_id": "native-export-probe", **payload}
    env = _env(home)
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", "--hook"],
        capture_output=True,
        cwd=str(cwd),
        env=env,
        input=json.dumps(body).encode("utf-8"),
        timeout=120,
    )
    # THE HOME ASSERTION, and it fires before any case reads a byte the hook wrote.
    log = home / ".bantamkit" / "hooks" / "hook-log.jsonl"
    assert log.exists(), f"the adapter did not follow HOME={home}: no log at {log}"
    records = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").strip().splitlines()
        if line
    ]
    return HookResult(proc, home, cwd, records)


def _bed(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _seed_store(cwd: Path, facts: list[dict]) -> Path:
    """A project store under `cwd` holding `facts`, written through the store itself."""
    from bantamkit.memory.component import Memory

    root = cwd / ".bantamkit" / "memory"
    memory = Memory(store=root)
    for f in facts:
        memory.save(f["type"], f["name"], f["description"], f.get("body", "body"))
    return root


def _seed_native(directory: Path, index: str = "# Memory index\n\n## Project\n\n") -> Path:
    """A native auto-memory directory that the resolver's branches 2 and 3 will ACCEPT."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "MEMORY.md").write_bytes(index.encode("utf-8"))
    return directory


def _fact_count(root: Path) -> int:
    from bantamkit.memory.store import MemoryStore

    return len(MemoryStore(root, create=False)._facts())


def _transcript_in(directory: Path) -> str:
    return str(directory / "session.jsonl")


# --- the resolver -----------------------------------------------------------------------


def test_branch_1_env_override_is_the_directory_unverified(tmp_path):
    """RULING Q1.2(1): the override beats everything in the host too, so A takes it as given.

    This directory holds no `MEMORY.md` and is still the answer.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    native = _bed(tmp_path, "override-native")
    r = _run_hook(
        {"hook_event_name": "SessionStart", "source": "startup"},
        home=home,
        cwd=cwd,
        env_extra={"CLAUDE_COWORK_MEMORY_PATH_OVERRIDE": str(native)},
    )
    assert r.returncode == 0
    assert r.record["nativeBranch"] == "env"
    assert r.record["nativeDir"] == str(native)
    assert r.record["nativeTried"] == []


def test_branch_2_auto_memory_directory_from_user_settings(tmp_path):
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    native = _seed_native(_bed(tmp_path, "settings-native"))
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"autoMemoryDirectory": str(native)}), encoding="utf-8"
    )
    r = _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)
    assert r.record["nativeBranch"] == "settings"
    assert r.record["nativeDir"] == str(native)
    assert r.record["nativeTried"] == ["env"]


def test_branch_2_is_a_candidate_not_an_answer(tmp_path):
    """Three higher-precedence sources exist in the host that A cannot read
    (`policySettings`, `flagSettings`, the env var), so `userSettings` is never taken on its
    word: a directory with no `MEMORY.md` is REJECTED.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    bare = _bed(tmp_path, "settings-bare")  # exists, but no MEMORY.md
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"autoMemoryDirectory": str(bare)}), encoding="utf-8"
    )
    r = _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)
    assert r.record["nativeBranch"] == "unknown"
    assert r.record["nativeDir"] is None
    assert r.record["nativeTried"] == ["env", "settings", "transcript"]


def test_branch_3_dirname_transcript_path_memory(tmp_path):
    """The slug the HOST itself computed, read back rather than recomputed."""
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory")
    r = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    assert r.record["nativeBranch"] == "transcript"
    assert r.record["nativeDir"] == str(native)
    assert r.record["nativeTried"] == ["env", "settings"]


def test_branch_3_is_a_candidate_too(tmp_path):
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript-bare")
    r = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    assert r.record["nativeBranch"] == "unknown"
    assert r.record["nativeTried"] == ["env", "settings", "transcript"]


def test_unknown_exports_nothing_and_creates_nothing(tmp_path):
    """RULING Q1.3. A directory at a slug the host does not resolve to is a store nobody
    reads and nobody prunes, so the honest answer to "I do not know the path" is silence.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    r = _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)
    assert r.returncode == 0
    assert r.record["nativeBranch"] == "unknown"
    assert "nativeExported" not in r.record, "no export ran at all"
    assert not (home / ".claude" / "projects").exists()


def test_the_debt_a_directory_at_the_old_slug_is_not_the_answer(tmp_path):
    """The case the deleted `_native_memory_exists` got wrong, driven from the outside.

    The old-slug directory is built EXACTLY as the old code would have addressed it and given
    a real `MEMORY.md`; the resolver must still answer `unknown`, and — the observable
    consequence — SessionStart must still inject the project index, which the old code
    suppressed on the strength of that directory.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    old_slug = re.sub(r"[\\/:]", "-", str(cwd))
    _seed_native(home / ".claude" / "projects" / old_slug / "memory")
    r = _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)
    assert r.record["nativeBranch"] == "unknown"
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "[bantamkit project memory — 1 facts]" in ctx
    assert r.record["projectInjected"] == 1


# --- the export -------------------------------------------------------------------------


def test_an_absent_name_is_written_as_a_valid_auto_memory_file(tmp_path):
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory")
    _seed_store(
        cwd,
        [
            {"type": "project", "name": "alpha", "description": "the first fact"},
            {"type": "feedback", "name": "beta", "description": "the second   fact\nwrapped"},
        ],
    )
    r = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    assert r.returncode == 0
    assert r.record["nativeBranch"] == "transcript"
    assert r.record["nativeExported"] == 2
    assert r.record["nativeFiles"] == 2

    alpha = (native / "alpha.md").read_text(encoding="utf-8")
    assert alpha.startswith('---\nname: alpha\ndescription: "the first fact"\nmetadata:\n')
    assert re.search(r"^ {2}node_type: memory$", alpha, re.M)
    assert re.search(r"^ {2}type: project$", alpha, re.M)
    assert re.search(r"^ {2}source: bantamkit$", alpha, re.M)
    assert "mcp__bantamkit__memory_recall" in alpha

    # Whitespace is normalised to single spaces, so a wrapped description stays ONE YAML line.
    beta = (native / "beta.md").read_text(encoding="utf-8")
    assert re.search(r'^description: "the second fact wrapped"$', beta, re.M)
    assert re.search(r"^ {2}type: feedback$", beta, re.M)


def test_the_index_line_is_appended_under_a_section_a_owns(tmp_path):
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    seeded = "# Memory index\n\n## Project\n\n- [host-fact](host-fact.md) — the host wrote this\n"
    native = _seed_native(t / "memory", seeded)
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    r = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    index = (native / "MEMORY.md").read_text(encoding="utf-8")
    assert index.startswith(seeded), "every byte the host wrote is still there, in order"
    assert "\n## bantamkit\n" in index
    assert "\n- [alpha](alpha.md) — the first fact\n" in index
    assert r.record["nativeIndexLines"] == 1


def test_a_name_already_in_the_index_gets_no_second_line(tmp_path):
    """RULING Q1.5: write a name only when it is ABSENT, and the two halves are checked
    INDEPENDENTLY — the file's absence gates the file, the index line's absence gates the
    line — so a dream that removes one and keeps the other leaves A doing exactly one thing.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(
        t / "memory", "# Memory index\n\n- [alpha](alpha.md) — a description the host reworded\n"
    )
    sentinel = "SENTINEL — written by something that is not bantamkit\n"
    (native / "alpha.md").write_text(sentinel, encoding="utf-8")
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    r = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    assert (native / "alpha.md").read_text(encoding="utf-8") == sentinel, (
        "an entry A did not just create is never rewritten"
    )
    index = (native / "MEMORY.md").read_text(encoding="utf-8")
    assert len(re.findall(r"\]\(alpha\.md\)", index)) == 1
    assert r.record["nativeExported"] == 0
    # A name already there is a QUIET skip, not a failed write. The exclusive-create flag on
    # the write is a second guard against the race between the check and the write; this
    # assertion is what keeps the FIRST guard — `os.path.lexists` — from being quietly
    # deleted in favour of it, because without it an already-present name would end the run
    # with a `FileExistsError` instead of skipping.
    assert "nativeError" not in r.record, "a present name costs no error"


def test_a_second_run_writes_nothing_new_and_a_third_restores_what_was_removed(tmp_path):
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory")
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    payload = {
        "hook_event_name": "SessionStart",
        "source": "startup",
        "transcript_path": _transcript_in(t),
    }
    first = _run_hook(payload, home=home, cwd=cwd)
    assert first.record["nativeExported"] == 1
    after1 = (native / "MEMORY.md").read_bytes()
    second = _run_hook(payload, home=home, cwd=cwd)
    assert second.record["nativeExported"] == 0
    assert (native / "MEMORY.md").read_bytes() == after1, "the index is byte-unchanged"

    # …and when the host's dream removes both halves, the THIRD run puts them back. A is
    # correct when everything it wrote is gone, which is the property job59 measured it needs.
    (native / "alpha.md").unlink()
    (native / "MEMORY.md").write_text("# Memory index\n", encoding="utf-8")
    third = _run_hook(payload, home=home, cwd=cwd)
    assert third.record["nativeExported"] == 1
    assert (native / "alpha.md").exists()


def test_a_never_deletes_a_file_it_did_not_write(tmp_path):
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory")
    (native / "someone-elses.md").write_text("not ours\n", encoding="utf-8")
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    assert (native / "someone-elses.md").read_text(encoding="utf-8") == "not ours\n"


def test_a_never_creates_memory_md(tmp_path):
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    native = _bed(tmp_path, "override-native")  # exists, no MEMORY.md — branch 1 takes it
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    r = _run_hook(
        {"hook_event_name": "SessionStart", "source": "startup"},
        home=home,
        cwd=cwd,
        env_extra={"CLAUDE_COWORK_MEMORY_PATH_OVERRIDE": str(native)},
    )
    assert (native / "alpha.md").exists()
    assert not (native / "MEMORY.md").exists(), "A does not write the host index into existence"
    assert r.record["nativeIndexLines"] == 0
    assert r.record["nativeIndex"] == "absent"


def test_a_never_mkdirs(tmp_path):
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    missing = tmp_path / "not-created-by-a"
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    r = _run_hook(
        {"hook_event_name": "SessionStart", "source": "startup"},
        home=home,
        cwd=cwd,
        env_extra={"CLAUDE_COWORK_MEMORY_PATH_OVERRIDE": str(missing)},
    )
    assert r.returncode == 0
    assert not missing.exists(), "the directory is still not there"
    assert r.record["nativeExported"] == 0
    assert r.record["nativeError"], "the failure is logged rather than thrown"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="chmod cannot make a directory unwritable on Windows; the refusal path needs its "
    "own fixture there",
)
def test_a_directory_that_is_not_writable_costs_one_log_line(tmp_path):
    """WINDOWS CANNOT CONSTRUCT THIS, and saying so is the point of the guard rather than a
    convenience. `chmod` on `sys.platform == "win32"` honours only the read-only bit, which
    does not stop a write INTO a directory, so `0o500` there would leave the export
    succeeding and this case would assert the opposite of what it means.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    native = _seed_native(_bed(tmp_path, "ro-native"))
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    os.chmod(native, 0o500)
    try:
        r = _run_hook(
            {"hook_event_name": "SessionStart", "source": "startup"},
            home=home,
            cwd=cwd,
            env_extra={"CLAUDE_COWORK_MEMORY_PATH_OVERRIDE": str(native)},
        )
    finally:
        os.chmod(native, 0o700)
    assert r.returncode == 0
    assert r.stdout.startswith("{"), "the arm still emits its one JSON object"
    assert r.record["nativeExported"] == 0
    assert r.record["nativeError"], f"expected a logged error, got {r.record}"
    assert not (native / "alpha.md").exists()


def test_the_export_is_bounded_at_2000_index_bytes(tmp_path):
    """The index bytes are the ones that mean something — they are what the host injects.

    Six facts with 400-character descriptions make each line 427 B, so four fit (1708 B) and
    the fifth would pass 2000; the run stops there and the rest go on a later session.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory")
    facts = []
    for i in range(6):
        # EVERY WORD DISTINCT PER FACT, and that is not decoration: `MemoryStore.save`
        # refuses a near-duplicate by token overlap, so six facts sharing a description save
        # as ONE and the case would measure the dedupe rather than the budget. Exactly 400
        # ASCII characters.
        words = " ".join(f"q{i}z{k}" for k in range(20))
        facts.append(
            {"type": "project", "name": f"fact-{i}", "description": words.ljust(400, "x")[:400]}
        )
    root = _seed_store(cwd, facts)
    assert _fact_count(root) == 6
    r = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    assert r.record["nativeIndexLines"] == 4
    assert r.record["nativeIndexBytes"] == 4 * 427
    assert r.record["nativeIndexBytes"] <= 2000
    index = (native / "MEMORY.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^- \[fact-\d\]", index, re.M)) == 4


def test_the_export_is_bounded_at_10_names(tmp_path):
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    _seed_native(t / "memory")
    facts = []
    for i in range(14):
        # Distinct words again, for the dedupe reason the index-bytes case above gives.
        facts.append(
            {
                "type": "project",
                "name": f"fact-{i:02d}",
                "description": " ".join(f"t{i}w{k}" for k in range(4)),
            }
        )
    root = _seed_store(cwd, facts)
    # 14 really are on disk — otherwise a cap of 10 would be met by a store that held 10.
    assert _fact_count(root) == 14
    r = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    assert r.record["nativeExported"] == 10
    assert r.record["nativeFiles"] == 10


def test_a_fact_name_that_is_not_a_safe_filename_is_skipped(tmp_path):
    """`MemoryStore.save` enforces `^[a-z0-9][a-z0-9-]*$`, but `_facts()` does NOT revalidate
    on READ — measured: a hand-written `facts/*.md` whose frontmatter says `name: ../escape`
    parses and is handed out with that name. So the guard is reachable, and this drives it.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory")
    root = _seed_store(
        cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}]
    )
    (root / "facts" / "weird.md").write_text(
        "---\nname: ../escape\ndescription: traversal probe\ntype: project\n"
        "created: '2026-09-20'\n---\n\nbody\n",
        encoding="utf-8",
    )
    r = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    assert r.returncode == 0
    assert r.record["nativeSkipped"] == ["../escape"]
    assert r.record["nativeExported"] == 1, "alpha still went, the traversal name did not"
    assert not (native.parent / "escape.md").exists(), "nothing escaped the directory"


def test_the_export_replaces_the_project_index(tmp_path):
    """The old `_native_memory_exists` suppressed the project block whenever the host had a
    store for this cwd. That behaviour is KEPT, now keyed on the resolver: the export IS the
    delivery, so injecting the same facts again would be paying twice.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    _seed_native(t / "memory")
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    r = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "bantamkit project memory" not in ctx, "no project block when the export ran"
    assert "projectInjected" not in r.record


def test_only_the_project_layer_is_exported(tmp_path):
    """The native directory is keyed on the host's project root, so a cross-project fact in
    it would be copied into every project's store; and the profile index is injected on every
    session anyway, so exporting it buys nothing. Named here so a later unit cannot widen it
    by accident.
    """
    from bantamkit.memory.component import Memory

    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory")
    Memory(store=home / ".bantamkit" / "memory").save(
        "user", "profile-only", "a cross-project fact", "body"
    )
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    r = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    assert (native / "alpha.md").exists()
    assert not (native / "profile-only.md").exists(), "the profile layer is not exported"
    assert r.record["nativeExported"] == 1


def test_the_export_runs_on_sessionstart_and_on_no_other_event(tmp_path):
    """One resolution per session, at the one event that carries `transcript_path` and
    already had to resolve the directory for the injection decision.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory")
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    r = _run_hook(
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "a prompt long enough to be scored",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    assert r.returncode == 0
    assert not (native / "alpha.md").exists(), "UserPromptSubmit exports nothing"
    stop = _run_hook(
        {"hook_event_name": "Stop", "transcript_path": _transcript_in(t)}, home=home, cwd=cwd
    )
    assert stop.returncode == 0
    assert not (native / "alpha.md").exists(), "Stop exports nothing either"


# --- appending, at the end of the file ---------------------------------------------------


def test_the_bantamkit_heading_is_written_once(tmp_path):
    from bantamkit.memory.component import Memory

    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory")
    _seed_store(
        cwd,
        [
            {"type": "project", "name": "alpha", "description": "the first fact"},
            {"type": "project", "name": "gamma", "description": "the third fact"},
        ],
    )
    payload = {
        "hook_event_name": "SessionStart",
        "source": "startup",
        "transcript_path": _transcript_in(t),
    }
    _run_hook(payload, home=home, cwd=cwd)
    # a new fact appears in bantamkit between the two sessions
    Memory(store=cwd / ".bantamkit" / "memory").save(
        "project", "delta", "the fourth fact", "body"
    )
    _run_hook(payload, home=home, cwd=cwd)
    index = (native / "MEMORY.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^## bantamkit$", index, re.M)) == 1
    assert "\n- [delta](delta.md) — the fourth fact\n" in index


def test_an_index_that_does_not_end_in_a_newline_still_gets_a_well_formed_line(tmp_path):
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory", "# Memory index")  # no trailing newline
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    index = (native / "MEMORY.md").read_text(encoding="utf-8")
    assert index.startswith("# Memory index\n"), "a newline was inserted, not glued on"
    assert index.endswith("\n- [alpha](alpha.md) — the first fact\n")


# --- the traps the 23 mirrored cases cannot reach ----------------------------------------
#
# The three below have NO counterpart in `runtime-ts/test/nativeexport.test.mjs`, and that is
# the point: each one pins a place where a natural Python spelling would quietly answer
# differently from the Node original. `\\s`, `str.strip()`, `ensure_ascii`, `$` and
# `os.path.exists` are all defaults a later editor would reach for, and every one of them is a
# divergence in a shared on-disk store rather than a style difference. Each was measured as a
# mutation before being written down; see `.shiftwork/notes-job62/U7-python-native-export.md`.


def _write_raw_fact(root: Path, filename: str, frontmatter: str) -> None:
    """A fact file written BY HAND, past `save`'s validation, the way a foreign writer would.

    `MemoryStore._facts()` does not revalidate on read, so this is how a name or a description
    the writer would have refused reaches the export.
    """
    (root / "facts" / filename).write_text(
        f"---\n{frontmatter}---\n\nbody\n", encoding="utf-8", newline="\n"
    )


def test_a_description_is_exported_the_way_the_other_runtime_spells_it(tmp_path):
    r"""THREE PARITY TRAPS IN ONE FILE, asserted as exact bytes rather than as a match.

    * `\s` is not the same set in the two languages — Python's matches U+00A0, JavaScript's
      `[ \t\n\r\f\v]` does not, so a `\s` here would collapse the NBSP the other side keeps.
    * `str.strip()` is not `trim()` — `trim()` strips U+FEFF and `str.strip()` does not, so a
      plain `.strip()` here would leave the two BOMs the other side removes.
    * `ensure_ascii=True` (the `json.dumps` default) would escape every non-ASCII character
      that `JSON.stringify` leaves as itself.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory")
    root = _seed_store(cwd, [{"type": "project", "name": "keep", "description": "a kept fact"}])
    _write_raw_fact(
        root,
        "tricky.md",
        'name: tricky\ndescription: "\\uFEFFcaf\\xE9 \\u4E2D\\u6587\\u00A0nbsp  x\\uFEFF"\n'
        "type: project\ncreated: '2026-09-20'\n",
    )
    _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    expected = 'description: "café 中文 nbsp x"'
    written = (native / "tricky.md").read_text(encoding="utf-8")
    assert expected in written, f"got {written.splitlines()[2]!r}"
    index = (native / "MEMORY.md").read_text(encoding="utf-8")
    assert "- [tricky](tricky.md) — café 中文 nbsp x\n" in index


def test_a_fact_name_with_a_trailing_newline_is_skipped(tmp_path):
    r"""`\Z` and not `$`.

    Python's `$` matches just BEFORE a final newline as well as at the end, so a name of
    `escape\n` passes `^[A-Za-z0-9][A-Za-z0-9._-]*$` here and fails the same pattern in
    JavaScript. One runtime would then join a newline into a path the other refused.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory")
    root = _seed_store(cwd, [{"type": "project", "name": "keep", "description": "a kept fact"}])
    _write_raw_fact(
        root,
        "newline-name.md",
        'name: "escape\\n"\ndescription: a name with a newline in it\n'
        "type: project\ncreated: '2026-09-20'\n",
    )
    r = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    assert r.record["nativeSkipped"] == ["escape\n"]
    assert sorted(p.name for p in native.iterdir()) == ["MEMORY.md", "keep.md"]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="creating a symlink on Windows needs Developer Mode or an elevated process, so "
    "this fixture is not constructible there; the dangling-link path needs its own fixture",
)
def test_a_dangling_symlink_is_an_entry_a_did_not_create(tmp_path):
    """`os.path.lexists` and not `os.path.exists`.

    `exists` follows the link, so a dangling one reads as ABSENT and the export would write
    THROUGH it into whatever it points at — creating a file outside the directory A was given.
    A dangling link is an entry A did not create, and "absent" is the only condition under
    which A writes.
    """
    home, cwd = _bed(tmp_path, "home"), _bed(tmp_path, "cwd")
    t = _bed(tmp_path, "transcript")
    native = _seed_native(t / "memory")
    elsewhere = _bed(tmp_path, "elsewhere") / "not-ours.md"
    (native / "alpha.md").symlink_to(elsewhere)
    _seed_store(cwd, [{"type": "project", "name": "alpha", "description": "the first fact"}])
    r = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "transcript_path": _transcript_in(t),
        },
        home=home,
        cwd=cwd,
    )
    assert not elsewhere.exists(), "A wrote through a dangling symlink"
    assert r.record["nativeFiles"] == 0, "the file half was skipped; only the index line went"
    assert r.record["nativeIndexLines"] == 1
    assert "nativeError" not in r.record
