"""The touch log, the per-session counter and the repo finder (#200, Task 1).

`runtime-ts/test/touch-log.test.mjs` mirrors every test here; `touch-log` compares the two.
"""

import json
import subprocess
import sys
from pathlib import Path

from bantamkit.touch.log import (
    TOUCH_LOG_CAP_BYTES,
    TOUCH_LOG_FOLD_TARGET_BYTES,
    TOUCH_TAIL_BYTES,
    TouchLog,
    bound_body,
    current_seq,
    fold_cutoff,
    next_seq,
    touch_reducer,
    use_names,
)
from bantamkit.touch.repo import find_repo, git_on_path, relpath


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / "src" / "a.py").write_text("x\n", encoding="utf-8")
    return r


def test_find_repo_walks_up_and_ids_the_realpath(tmp_path):
    r = _repo(tmp_path)
    found = find_repo(str(r / "src"))
    assert found is not None and Path(found.top) == r.resolve() and len(found.id) == 16
    assert find_repo(str(tmp_path)) is None


def test_find_repo_reads_a_gitdir_file(tmp_path):
    wt = tmp_path / "wt"
    (wt / "deep").mkdir(parents=True)
    (tmp_path / "real-gitdir").mkdir()
    (wt / ".git").write_text("gitdir: ../real-gitdir\n", encoding="utf-8")
    found = find_repo(str(wt / "deep"))
    assert found is not None and Path(found.top) == wt.resolve()
    assert Path(found.gitdir) == (tmp_path / "real-gitdir").resolve()


def test_relpath_is_slash_separated_and_none_outside(tmp_path):
    r = _repo(tmp_path)
    repo = find_repo(str(r))
    assert relpath(repo, str(r / "src" / "a.py")) == "src/a.py"
    assert relpath(repo, str(tmp_path / "elsewhere.py")) is None
    assert relpath(repo, str(r)) is None


def test_touch_line_bytes(tmp_path):
    log = TouchLog(tmp_path / "home", "0123456789abcdef")
    assert log.append_touch("s1", 3, "edit", "src/a.py", ts="2026-10-16T00:00:00Z")
    assert log.append_touch(
        "s1", 9, "write", "b.txt", via="bash-turn", frm=4, ts="2026-10-16T00:00:01Z"
    )
    assert log.append_use("s1", 10, "fact-a", "recall_hit", ts="2026-10-16T00:00:02Z")
    assert log.path.read_text(encoding="utf-8").splitlines() == [
        '{"ts":"2026-10-16T00:00:00Z","session":"s1","seq":3,"op":"edit","path":"src/a.py"}',
        '{"ts":"2026-10-16T00:00:01Z","session":"s1","seq":9,"op":"write","path":"b.txt",'
        '"via":"bash-turn","from":4}',
        '{"ts":"2026-10-16T00:00:02Z","session":"s1","seq":10,"op":"use","fact":"fact-a",'
        '"kind":"recall_hit"}',
    ]


def test_tail_is_this_session_after_seq(tmp_path):
    log = TouchLog(tmp_path / "home", "0123456789abcdef")
    for seq, session in [(1, "s1"), (2, "s2"), (5, "s1"), (6, "s1")]:
        log.append_touch(session, seq, "read", f"f{seq}", ts="2026-10-16T00:00:00Z")
    assert [r["seq"] for r in log.tail("s1", 1)] == [5, 6]


def test_tail_drops_the_line_the_seek_cut(tmp_path):
    log = TouchLog(tmp_path / "home", "0123456789abcdef")
    n = 0
    while not log.path.exists() or log.path.stat().st_size <= TOUCH_TAIL_BYTES:
        n += 1
        log.append_touch("s1", n, "read", "p" * 40, ts="2026-10-16T00:00:00Z")
    rows = log.tail("s1", 0)
    assert log.skipped == 0 and rows[-1]["seq"] == n and rows[0]["seq"] > 1


def test_corrupt_line_is_skipped_and_counted(tmp_path):
    log = TouchLog(tmp_path / "home", "0123456789abcdef")
    log.append_touch("s1", 1, "read", "a", ts="2026-10-16T00:00:00Z")
    with log.path.open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    assert len(log.read()) == 1 and log.skipped == 1


def test_unwritable_log_answers_false(tmp_path):
    (tmp_path / "home" / ".bantamkit").mkdir(parents=True)
    (tmp_path / "home" / ".bantamkit" / "touch").write_text("a file, not a dir", encoding="utf-8")
    log = TouchLog(tmp_path / "home", "0123456789abcdef")
    assert log.append_touch("s", 1, "read", "a") is False
    assert log.append_use("s", 1, "f", "save") is False


def test_seq_counts_up_per_session(tmp_path):
    state = str(tmp_path / "state")
    assert current_seq(state, "s1") == 0
    assert [next_seq(state, "s1") for _ in range(3)] == [1, 2, 3]
    assert next_seq(state, "s2") == 1 and current_seq(state, "s1") == 3
    assert (tmp_path / "state" / "ledger-s1.seq.json").read_bytes() == b'{"seq":3}'
    assert next_seq(state, "a/b.c") == 1 and (tmp_path / "state" / "ledger-a_b_c.seq.json").exists()


def test_use_names_from_recall_reply_and_save():
    reply = (
        "[project] [fact-a] (project) d\nbody\n\n[profile] [fact-b] (feedback) e\nbody [x] (y) z"
    )
    blocks = [{"type": "text", "text": reply}]
    assert use_names("mcp__bantamkit__memory_recall", {"query": "q"}, blocks) == [
        ("fact-a", "recall_hit"),
        ("fact-b", "recall_hit"),
    ]
    assert use_names("mcp__bantamkit__memory_recall", {}, {"content": blocks})[0] == (
        "fact-a",
        "recall_hit",
    )
    assert use_names("mcp__bantamkit__memory_recall", {}, "[solo] (user) one-layer header\nb") == [
        ("solo", "recall_hit")
    ]
    assert use_names("mcp__bantamkit__memory_save", {"name": "n1"}, "saved") == [("n1", "save")]
    assert use_names("Bash", {"command": "ls"}, "x") == []


def test_use_names_starts_a_line_after_newline_only():
    # JavaScript's multiline `^` also starts after \r, U+2028 and U+2029; neither side may.
    for sep in ("\r", " ", " "):
        reply = f"x{sep}[f] (user) d"
        assert use_names("mcp__bantamkit__memory_recall", {}, reply) == []


def test_reducer_keeps_last_touch_per_path_and_drops_uses():
    rows = [
        {"ts": "2026-09-01T00:00:00Z", "session": "a", "seq": 1, "op": "read", "path": "p"},
        {"ts": "2026-09-02T00:00:00Z", "session": "a", "seq": 2, "op": "edit", "path": "p"},
        {"ts": "2026-09-03T00:00:00Z", "session": "a", "seq": 3, "op": "use", "fact": "f",
         "kind": "save"},
    ]
    assert touch_reducer(rows) == [
        {"ts": "2026-09-02T00:00:00Z", "session": "", "seq": 0, "op": "folded", "path": "p", "n": 2}
    ]


def test_reducer_of_a_fold_is_the_same_fold():
    rows = [
        {"ts": "2026-09-01T00:00:00Z", "session": "a", "seq": 1, "op": "read", "path": "b"},
        {"ts": "2026-09-02T00:00:00Z", "session": "a", "seq": 2, "op": "edit", "path": "a"},
        {"ts": "2026-09-03T00:00:00Z", "session": "a", "seq": 3, "op": "edit", "path": "a"},
    ]
    once = touch_reducer(rows)
    assert [(r["path"], r["n"]) for r in once] == [("a", 2), ("b", 1)]
    assert touch_reducer(once) == once


# --- T200-10: git on PATH by stats, the log bounded on append ----------------------------


def test_git_on_path_is_a_stat_walk(tmp_path):
    exe, plain, win = tmp_path / "exe", tmp_path / "plain", tmp_path / "win"
    for d in (exe, plain, win):
        d.mkdir()
    (exe / "git").write_text("#!/bin/sh\n", encoding="utf-8")
    (exe / "git").chmod(0o755)
    (plain / "git").write_text("x", encoding="utf-8")
    (plain / "git").chmod(0o644)
    (win / "git.exe").write_text("x", encoding="utf-8")
    assert git_on_path(str(exe), "", False) is True
    assert git_on_path(str(plain), "", False) is False  # no execute bit
    assert git_on_path(f"::{plain}:{exe}", "", False) is True
    assert git_on_path("", "", False) is False
    assert git_on_path(str(win), "", True) is True  # PATHEXT unset: .COM;.EXE;.BAT;.CMD
    assert git_on_path(str(win), ".COM;.BAT", True) is False
    assert git_on_path(str(exe), "", True) is False  # Windows wants an extension


def test_fold_cutoff_names_the_line_past_the_byte_midpoint():
    def row(s: int) -> bytes:
        return b'{"ts":"2026-10-17T00:00:0%dZ","op":"read","path":"p"}\n' % s

    assert fold_cutoff(b"") is None
    assert fold_cutoff(row(1) + row(2) + row(3) + row(4)) == "2026-10-17T00:00:03Z~"
    assert fold_cutoff(row(1) + b"z" * 400 + b"\n") is None


def test_an_append_over_the_cap_folds_the_older_half(tmp_path):
    log = TouchLog(tmp_path, "0123456789abcdef")
    log.path.parent.mkdir(parents=True)
    rows = []
    i = 0
    while sum(map(len, rows)) <= TOUCH_LOG_CAP_BYTES:
        rows.append(
            b'{"ts":"2026-10-%02dT00:00:00Z","session":"s","seq":%d,"op":"read","path":"f%d"}\n'
            % (1 + i // 1000, i + 1, i % 30)
        )
        i += 1
    log.path.write_bytes(b"".join(rows))
    assert log.append_touch("now", 1, "read", "new.py", ts="2026-10-17T00:00:00Z")
    lines = log.path.read_bytes().decode("utf-8").splitlines()
    assert log.path.stat().st_size <= TOUCH_LOG_CAP_BYTES
    assert '"op":"folded"' in lines[0] and lines[-1].endswith('"path":"new.py"}')
    tail = rows[-(len(rows) // 3):]
    assert all(r.decode("utf-8").rstrip("\n") in lines for r in tail), "the newer half is kept"


# --- T200-11: the cap holds, no thrash, no fold without the lock -------------------------


def _stuck(n: int) -> bytes:
    """The re-review's stuck log: `n` folded rows (one per distinct path), then live lines past
    the cap. With n=6000 the folded block alone is over half the cap."""
    out = [
        json.dumps(
            {"ts": f"2026-09-{1 + i * 7919 % 28:02d}T00:00:00Z", "session": "", "seq": 0,
             "op": "folded", "path": f"src/module_{i:06d}/component_file.py", "n": 1},
            separators=(",", ":"),
        ).encode() + b"\n"
        for i in range(n)
    ]
    i = 0
    while sum(map(len, out)) <= TOUCH_LOG_CAP_BYTES:
        live = b'{"ts":"2026-10-02T00:00:%02dZ","session":"s",' % (i % 60)
        live += b'"seq":%d,"op":"read",' % (i + 1)
        out.append(live + b'"path":"src/x%d.py"}\n' % i)
        i += 1
    return b"".join(out)


def test_a_folded_block_over_half_the_cap_is_bounded_then_left_alone(tmp_path):
    log = TouchLog(tmp_path, "0123456789abcdef")
    log.path.parent.mkdir(parents=True)
    log.path.write_bytes(_stuck(6000))
    assert log.append_touch("now", 1, "read", "new.py", ts="2026-10-17T00:00:00Z")
    first = log.path.read_bytes()
    assert len(first) <= TOUCH_LOG_FOLD_TARGET_BYTES
    assert first.endswith(b'"path":"new.py"}\n')
    rows = [json.loads(x) for x in first.splitlines()]
    kept = [r for r in rows if r["op"] == "folded"]
    dropped_max = max(
        (r["ts"], r["path"]) for r in map(json.loads, _stuck(6000).splitlines())
        if r["op"] == "folded" and r["path"] not in {k["path"] for k in kept}
    )
    assert min((r["ts"], r["path"]) for r in kept) > dropped_max, "oldest (ts, path) aged out first"
    ino = log.path.stat().st_ino
    for k in range(2, 10):  # the slack under the target is under one folded line
        assert log.append_touch("now", k, "read", f"new{k}.py", ts="2026-10-17T00:00:01Z")
    after = log.path.read_bytes()
    assert len(after) > TOUCH_LOG_FOLD_TARGET_BYTES
    assert after.startswith(first) and log.path.stat().st_ino == ino, "no rewrite under the cap"


def test_bound_body_is_under_the_target_for_any_log():
    no_ts = b"".join(b'{"op":"read","path":"p%d"}\n' % (i % 9000) for i in range(60000))
    late = b'{"ts":"2026-10-09T00:00:00Z","session":"s","seq":1,"op":"read","path":"late%d"}\n'
    early = b'{"ts":"2026-10-01T00:00:00Z","session":"s","seq":1,"op":"edit","path":"early%d"}\n'
    out_of_order = b"".join(late % (i % 4000) for i in range(7000))
    out_of_order += b"".join(early % (i % 4000) for i in range(7000))
    for data in (_stuck(6000), _stuck(12000), no_ts, out_of_order, b"", b"junk\n" * 300000):
        assert len(bound_body(data)) <= TOUCH_LOG_FOLD_TARGET_BYTES


def test_a_held_lock_skips_the_fold(tmp_path):
    log = TouchLog(tmp_path, "0123456789abcdef")
    log.path.parent.mkdir(parents=True)
    data = _stuck(6000)
    log.path.write_bytes(data)
    Path(f"{log.path}.lock").write_bytes(b"")  # a live holder: the 2 s wait runs out
    assert log.bound() is False
    assert log.path.read_bytes() == data, "never rewritten unlocked"


def test_bound_never_raises(tmp_path):
    log = TouchLog(tmp_path, "0123456789abcdef")
    log.path.mkdir(parents=True)  # a directory where the log should be
    assert log.bound() is False


def test_parallel_appenders_on_a_stuck_log_lose_nothing(tmp_path):
    log = TouchLog(tmp_path, "0123456789abcdef")
    log.path.parent.mkdir(parents=True)
    log.path.write_bytes(_stuck(6000))
    code = (
        "import sys; from bantamkit.touch.log import TouchLog\n"
        "l = TouchLog(sys.argv[1], '0123456789abcdef')\n"
        "for k in range(10): l.append_touch('race', int(sys.argv[2]) * 100 + k, 'read', "
        "f'r{sys.argv[2]}_{k}.py', ts='2026-10-03T00:00:00Z')\n"
    )
    argv = [sys.executable, "-c", code, str(tmp_path)]
    procs = [subprocess.Popen([*argv, str(j)]) for j in range(12)]
    for pr in procs:
        assert pr.wait(timeout=120) == 0
    rows = [json.loads(x) for x in log.path.read_bytes().splitlines()]
    race = {r["path"] for r in rows if r.get("session") == "race"}
    assert len(race) == 120, f"{120 - len(race)} appends lost"
    assert log.path.stat().st_size <= TOUCH_LOG_CAP_BYTES
    assert list(log.path.parent.glob("*.tmp")) == [] and not Path(f"{log.path}.lock").exists()


def test_bound_carries_an_inflight_unlocked_line_read_to_eof(tmp_path):
    # 208 items 2-3: an expired-wait appender that opened the log before the bound's rename and
    # writes after it (two writes, the second past 64 KiB) loses nothing; the growth is read to EOF.
    import os
    import threading
    import time

    log = TouchLog(tmp_path, "0123456789abcdef")
    log.path.parent.mkdir(parents=True)
    data = _stuck(6000)
    log.path.write_bytes(data)
    mark = Path(f"{log.path}.1.ab.writing")
    mark.write_bytes(b"")
    late = [
        b'{"ts":"2026-10-17T00:00:09Z","session":"late","seq":1,"op":"read","path":"a.py"}\n',
        b'{"ts":"2026-10-17T00:00:09Z","session":"late","seq":2,"op":"read","path":"%s"}\n'
        % (b"b" * 70000),
    ]

    def appender():
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            keeps = [n for n in os.listdir(log.path.parent) if n.endswith(".keep")]
            try:
                keep = log.path.parent / keeps[0]
                if os.stat(keep).st_ino != os.stat(log.path).st_ino:
                    with open(keep, "ab") as f:
                        for chunk in late:
                            f.write(chunk)
                            f.flush()
                    break
            except (IndexError, OSError):
                pass
            time.sleep(0.001)
        mark.unlink()

    t = threading.Thread(target=appender)
    t.start()
    assert log.bound() is True
    t.join()
    assert log.path.read_bytes() == bound_body(data) + b"".join(late)
    assert sorted(os.listdir(log.path.parent)) == ["0123456789abcdef.jsonl"]
