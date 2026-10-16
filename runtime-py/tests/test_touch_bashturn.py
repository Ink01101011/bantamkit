"""bash-turn (#200, E5, Task 3): two `git status` snapshots per turn, diffed.

`runtime-ts/test/touch-bashturn.test.mjs` mirrors these; `touch-turn` compares the two.
"""

import subprocess

from bantamkit.touch.bashturn import changed, load_turn, save_turn, snapshot
from bantamkit.touch.repo import find_repo


def _repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()

    def g(*a):
        subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)

    g("init", "-q")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (r / "a.txt").write_text("1\n", encoding="utf-8")
    (r / "dirty.txt").write_text("1\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-qm", "c")
    (r / "dirty.txt").write_text("2\n", encoding="utf-8")  # dirty before the turn
    return r


def test_diff_sees_new_modified_and_redirtied(tmp_path):
    r = _repo(tmp_path)
    repo = find_repo(str(r))
    before = snapshot(repo)
    (r / "a.txt").write_text("changed by bash\n", encoding="utf-8")
    (r / "new").mkdir()
    (r / "new" / "n.txt").write_text("n\n", encoding="utf-8")
    # already dirty: only the stat moves
    (r / "dirty.txt").write_text("3, longer\n", encoding="utf-8")
    assert changed(before, snapshot(repo)) == ["a.txt", "dirty.txt", "new/n.txt"]


def test_revert_to_clean_is_a_change(tmp_path):
    r = _repo(tmp_path)
    repo = find_repo(str(r))
    before = snapshot(repo)
    (r / "dirty.txt").write_text("1\n", encoding="utf-8")
    assert changed(before, snapshot(repo)) == ["dirty.txt"]


def test_rename_keys_on_the_destination(tmp_path):
    r = _repo(tmp_path)
    repo = find_repo(str(r))
    subprocess.run(["git", "-C", str(r), "mv", "a.txt", "b.txt"], check=True)
    snap = snapshot(repo)
    assert "b.txt" in snap and "a.txt" not in snap
    assert snap["b.txt"][0] == "R "


def test_snapshot_is_none_when_git_fails(tmp_path):
    r = tmp_path / "notgit"
    (r / ".git").mkdir(parents=True)  # find_repo accepts it; git refuses it
    assert snapshot(find_repo(str(r))) is None


def test_turn_round_trip(tmp_path):
    save_turn(str(tmp_path), "s/1", {"a": ["??", "1", 2]}, 7)
    assert load_turn(str(tmp_path), "s/1") == (7, {"a": ["??", "1", 2]})
    assert (tmp_path / "ledger-s_1.turn.json").exists()
    assert (tmp_path / "ledger-s_1.turn.json").read_bytes() == (
        b'{"seq":7,"status":{"a":["??","1",2]}}'
    )


def test_load_turn_refuses_junk(tmp_path):
    assert load_turn(str(tmp_path), "none") is None
    junks = ['{"seq":', "[1]", '{"seq":"7","status":{}}', '{"seq":7,"status":[]}']
    for junk in [*junks, '{"seq":true,"status":{}}']:
        (tmp_path / "ledger-j.turn.json").write_text(junk, encoding="utf-8")
        assert load_turn(str(tmp_path), "j") is None, junk
