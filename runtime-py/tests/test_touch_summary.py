"""The B summaries (#200, E1-B, Task 6): the last session's edits and commits, and this session's
edits after a compaction, in at most 600 bytes.

`runtime-ts/test/touch-summary.test.mjs` mirrors these; `touch-summary` compares the two.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from bantamkit.touch.log import TouchLog
from bantamkit.touch.repo import find_repo
from bantamkit.touch.summary import (
    SUMMARY_MAX,
    age_text,
    cap_bytes,
    compact_line,
    last_session_line,
    previous_session,
    shift_ts,
    uncommitted_count,
)

SRC = Path(__file__).resolve().parents[1] / "src"


def _r(seq, path, op="edit", session="old", ts=None, **kw):
    return {
        "ts": ts or f"2026-10-15T10:00:{seq:02d}Z",
        "session": session,
        "seq": seq,
        "op": op,
        "path": path,
        **kw,
    }


ROWS = [
    _r(1, "src/store.ts"),
    _r(2, "src/retrieval.ts", "read"),
    _r(3, "src/retrieval.ts"),
    _r(4, "src/factfile.ts", "write"),
    _r(5, "x.txt", "write", via="bash-turn", **{"from": 4}),
    _r(6, "y.txt"),
    _r(7, "now.py", session="current", ts="2026-10-15T13:00:00Z"),
]


def test_age_text():
    assert [age_text(s) for s in (5, 120, 3 * 3600, 3 * 86400)] == [
        "just now",
        "2 min ago",
        "3 h ago",
        "3 d ago",
    ]


def test_age_text_boundaries():
    got = [age_text(s) for s in (59, 60, 3599, 3600, 172799, 172800, -5)]
    assert got == [
        "just now",
        "1 min ago",
        "59 min ago",
        "1 h ago",
        "47 h ago",
        "2 d ago",
        "just now",
    ]


def test_previous_session_skips_current_and_folded():
    rows = ROWS + [
        {"ts": "2026-10-16T00:00:00Z", "session": "", "seq": 0, "op": "folded", "path": "p", "n": 3}
    ]
    sid, mine = previous_session(rows, "current")
    assert sid == "old" and len(mine) == 6


def test_previous_session_tie_goes_to_the_smaller_id():
    rows = [_r(1, "a", session="b"), _r(1, "a", session="a"), _r(1, "a", session="c")]
    assert previous_session(rows, "x")[0] == "a"
    assert previous_session([_r(1, "a", session="s")], "s") is None


def test_line_shape_and_silence():
    _, mine = previous_session(ROWS, "current")
    line = last_session_line(
        mine,
        "2026-10-15T13:00:06Z",
        lambda p: p.split("/")[-1],
        ["feat: one (#199)", "fix: two"],
        4,
    )
    assert line == (
        "[bantamkit touch] last session here (2026-10-15, 3 h ago): edited 5 files — "
        "y.txt, x.txt, factfile.ts (+2); commits: feat: one (#199); fix: two; uncommitted: 4 files"
    )
    reads_only = [_r(1, "a", "read")]
    assert last_session_line(reads_only, "2026-10-15T13:00:00Z", str, [], 9) == ""


def test_zero_edits_with_commits_and_singulars():
    line = last_session_line(
        [_r(1, "a", "read")], "2026-10-15T10:00:01Z", str, ["a", "b", "c", "d", "e"], 1
    )
    assert line == (
        "[bantamkit touch] last session here (2026-10-15, just now): edited no files; "
        "commits: a; b; c (+2); uncommitted: 1 file"
    )
    one = last_session_line([_r(1, "a")], "2026-10-15T10:00:01Z", str, [], 0)
    assert one == "[bantamkit touch] last session here (2026-10-15, just now): edited 1 file — a"


def test_cap_is_600_bytes_in_bytes():
    _, mine = previous_session(ROWS, "current")
    line = last_session_line(
        mine, "2026-10-15T13:00:06Z", lambda p: "ไทย" * 40 + p, ["ก" * 300] * 3, 1
    )
    assert len(line.encode("utf-8")) <= 600
    line.encode("utf-8").decode("utf-8")  # never split inside a character


def test_cap_bytes_keeps_600_and_cuts_601():
    s600 = "a" * 597 + "ก"  # 597 + 3 = 600 bytes
    assert cap_bytes(s600, SUMMARY_MAX) == s600
    s601 = "a" * 598 + "ก"  # 601 bytes: the Thai character is dropped whole
    assert cap_bytes(s601, SUMMARY_MAX) == "a" * 598
    assert cap_bytes("a" * 599 + "😀", SUMMARY_MAX) == "a" * 599


def test_subject_is_cut_at_60_bytes():
    line = last_session_line([_r(1, "a")], "2026-10-15T10:00:01Z", str, ["ก" * 30], 0)
    assert line.endswith("; commits: " + "ก" * 20)


def test_compact_lists_edits_only():
    rows = [
        _r(1, "a.py", session="s"),
        _r(2, "b.py", "read", session="s"),
        _r(3, "c.py", "write", session="s"),
    ]
    assert (
        compact_line(rows, "s", str)
        == "[bantamkit touch] edited in this session before compaction: c.py, a.py"
    )
    assert compact_line([_r(1, "a.py", "read", session="s")], "s", str) == ""


def test_compact_caps_at_ten_names():
    rows = [_r(i, f"f{i:02d}.py", session="s") for i in range(1, 13)]
    assert compact_line(rows, "s", str) == (
        "[bantamkit touch] edited in this session before compaction: "
        + ", ".join(f"f{i:02d}.py" for i in range(12, 2, -1))
        + " (+2)"
    )


def test_shift_ts():
    assert shift_ts("2026-10-15T23:50:00Z", 1800) == "2026-10-16T00:20:00Z"


def test_uncommitted_count_skips_a_rename_source():
    # `R  new\0old\0` is ONE entry; a source path whose third character is a space is still skipped
    assert uncommitted_count("R  b.txt\0ab c.txt\0 M d.txt\0?? e.txt\0") == 3
    assert uncommitted_count("") == 0


# ------------------------------------------------------------------- the hook, as a process


def _git(r, *a, date=None):
    env = {**os.environ}
    if date:
        env.update(GIT_COMMITTER_DATE=date, GIT_AUTHOR_DATE=date)
    subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True, env=env)


def _bed(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "src").mkdir()
    for f in ("src/store.ts", "src/retrieval.ts", "lib/store.ts", "a.txt", "b.txt"):
        (r / f).parent.mkdir(exist_ok=True)
        (r / f).write_text("1\n", encoding="utf-8")
    _git(r, "add", ".")
    _git(r, "commit", "-qm", "before the session", date="2026-10-15T09:00:00Z")
    (r / "a.txt").write_text("2\n", encoding="utf-8")
    _git(r, "commit", "-qam", "J68-3 keywords (#199)", date="2026-10-15T10:20:00Z")
    (r / "b.txt").write_text("3\n", encoding="utf-8")  # uncommitted
    _git(r, "mv", "a.txt", "c.txt")  # a rename: one uncommitted entry, not two
    repo = find_repo(str(r))
    log = TouchLog(home, repo.id)
    log.append_touch("old", 1, "edit", "src/store.ts", ts="2026-10-15T10:00:01Z")
    log.append_touch("old", 2, "read", "src/retrieval.ts", ts="2026-10-15T10:00:02Z")
    log.append_touch("old", 3, "write", "b.txt", ts="2026-10-15T10:00:03Z")
    log.append_touch("now", 1, "edit", "src/retrieval.ts", ts="2026-10-17T10:00:00Z")
    return home, r


def _session_start(home, cwd, source, tz="Asia/Bangkok"):
    env = dict(os.environ, PYTHONPATH=str(SRC), HOME=str(home), USERPROFILE=str(home), TZ=tz)
    env.pop("BANTAMKIT_MEMORY_DIR", None)
    payload = {
        "hook_event_name": "SessionStart",
        "source": source,
        "session_id": "now",
        "cwd": str(cwd),
    }
    done = subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", "--hook"],
        capture_output=True,
        cwd=str(cwd),
        env=env,
        input=json.dumps(payload).encode(),
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    ctx = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
    log = (
        (home / ".bantamkit" / "hooks" / "hook-log.jsonl").read_text(encoding="utf-8").splitlines()
    )
    return ctx, [json.loads(x) for x in log if '"SessionStart"' in x][-1]


def test_hook_startup_appends_the_line_before_the_toolbox_part(tmp_path):
    home, r = _bed(tmp_path)
    ctx, rec = _session_start(home, r, "startup")
    parts = ctx.split("\n\n")
    line = next(p for p in parts if p.startswith("[bantamkit touch]"))
    assert parts[parts.index(line) + 1].startswith("[bantamkit] Toolbox is live")
    # git read `--since=...Z` as UTC under TZ=Asia/Bangkok: the 09:00Z commit is outside the window
    assert re.sub(r"\d+ (min|h|d) ago|just now", "<age>", line) == (
        "[bantamkit touch] last session here (2026-10-15, <age>): "
        "edited 2 files — b.txt, src/store.ts; commits: J68-3 keywords (#199); uncommitted: 2 files"
    )
    assert rec["touchBytes"] == len(line.encode("utf-8"))


def test_hook_compact_lists_this_sessions_edits(tmp_path):
    home, r = _bed(tmp_path)
    ctx, rec = _session_start(home, r, "compact")
    line = "[bantamkit touch] edited in this session before compaction: retrieval.ts"
    assert line in ctx.split("\n\n")
    assert rec["touchBytes"] == len(line.encode("utf-8"))


def test_hook_outside_a_repo_says_nothing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "plain"
    cwd.mkdir()
    ctx, rec = _session_start(home, cwd, "startup")
    assert "[bantamkit touch]" not in ctx
    assert rec["touchBytes"] == 0
