"""The touch graph (#200, Task 4): file -> facts, a derived index; a git half, a touch-log half.

Mirrored by runtime-ts/test/touch-graph.test.mjs; tools/conformance/suites/touch-graph.mjs
compares the two runtimes.
"""

import json
import os
import subprocess

import pytest

from bantamkit.memory.native import NativeStore
from bantamkit.memory.store import MemoryStore
from bantamkit.storage.hotindex import HotIndex
from bantamkit.touch import graph as graph_mod
from bantamkit.touch.graph import WEAK_TS_MAX, TouchGraph, build_strong, build_weak
from bantamkit.touch.log import TouchLog
from bantamkit.touch.refs import FileSet
from bantamkit.touch.repo import find_repo

FS = FileSet(["src/a.py", "src/b.py", "docs/x.md"])


def test_strong_edges_first_layer_first_then_name():
    layers = [{"zeta": ["a.py#run"], "alpha": ["src/a.py", "missing.py"]}, {"alpha": ["docs/x.md"]}]
    assert build_strong(layers, FS, {}, "/r") == {
        "src/a.py": [["alpha", None], ["zeta", "run"]],
        "docs/x.md": [["alpha", None]],
    }


def test_strong_one_edge_per_fact_and_symbol_and_follows_renames():
    layers = [{"f": ["src/a.py", "a.py", "src/a.py#x", "old.py"]}]
    assert build_strong(layers, FS, {"old.py": "src/b.py"}, "/r") == {
        "src/a.py": [["f", None], ["f", "x"]],
        "src/b.py": [["f", None]],
    }


def _t(seq, path, session="s", **kw):
    ts = f"2026-10-16T00:00:{seq:02d}Z"
    return {"ts": ts, "session": session, "seq": seq, "op": "edit", "path": path, **kw}


def _u(seq, fact, session="s", ts=None):
    ts = ts or f"2026-10-16T00:00:{seq:02d}Z"
    row = {"ts": ts, "session": session, "seq": seq, "op": "use", "fact": fact}
    return {**row, "kind": "recall_hit"}


def test_weak_window_is_plus_minus_twenty_same_session():
    rows = [_t(1, "src/a.py"), _u(21, "f"), _u(22, "g"), _u(5, "h", session="other")]
    assert build_weak(rows) == {"src/a.py": {"f": ["2026-10-16T00:00:21Z"]}}


def test_weak_bash_turn_counts_the_turn():
    rows = [_u(3, "f"), _u(9, "g"), _t(9, "b.txt", op="write", via="bash-turn", **{"from": 3})]
    assert build_weak(rows) == {"b.txt": {"g": ["2026-10-16T00:00:09Z"]}}


def test_weak_keeps_the_newest_distinct_timestamps():
    rows = [_t(30, "p")] + [_u(30, "f", ts=f"2026-10-16T00:{i:02d}:00Z") for i in range(40)]
    rows.append(_u(31, "f", ts="2026-10-16T00:39:00Z"))  # a duplicate timestamp counts once
    got = build_weak(rows)["p"]["f"]
    assert len(got) == WEAK_TS_MAX
    assert got[0] == "2026-10-16T00:08:00Z" and got[-1] == "2026-10-16T00:39:00Z"


def test_weak_reads_an_integral_float_seq_as_json_parse_does():
    rows = [_t(1, "p"), {**_u(2, "f"), "seq": 2.0}, {**_u(3, "g"), "seq": 2.5}]
    rows.append({**_u(4, "h"), "seq": True})
    assert build_weak(rows) == {"p": {"f": ["2026-10-16T00:00:02Z"]}}


# ------------------------------------------------------------------- TouchGraph.load


def _git(top, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
         "-C", str(top), *args],
        check=True, capture_output=True, env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
    )


def _fact(store, name, desc, body="b"):
    d = store / "facts"
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{name}.tmp"
    tmp.write_text(
        f"---\nname: {name}\ndescription: {desc}\ntype: project\ncreated: '2026-10-15'\n"
        f"last_recalled: null\nlinks: []\n---\n\n{body}\n",
        encoding="utf-8",
    )
    os.replace(tmp, d / f"{name}.md")  # temp-then-rename moves the directory mtime


@pytest.fixture
def bed(tmp_path):
    top = tmp_path / "repo"
    (top / "src").mkdir(parents=True)
    (top / "src" / "a.py").write_text("x\n", encoding="utf-8")
    (top / "README.md").write_text("r\n", encoding="utf-8")
    _git(top, "init", "-q")
    _git(top, "add", ".")
    _git(top, "commit", "-qm", "one")
    store = tmp_path / "store"
    _fact(store, "names-a", "touches src/a.py")
    repo = find_repo(str(top))
    assert repo is not None
    home = tmp_path / "home"
    return {"top": top, "store": store, "repo": repo, "home": home,
            "layers": [("project", MemoryStore(store), True)]}


def test_first_load_writes_and_an_unchanged_second_does_not(bed):
    g = TouchGraph(bed["home"], bed["repo"])
    data = g.load(bed["layers"])
    assert data is not None and data["strong"] == {"src/a.py": [["names-a", None]]}
    assert data["files"] == ["README.md", "src/a.py"] and data["weak"] == {}
    before = os.stat(g.path).st_mtime_ns
    raw = g.path.read_bytes()
    assert json.loads(raw) == data and raw.endswith(b"\n")
    assert g.load(bed["layers"]) == data
    assert os.stat(g.path).st_mtime_ns == before and g.path.read_bytes() == raw


def test_a_touch_line_rebuilds_weak_only(bed, monkeypatch):
    g = TouchGraph(bed["home"], bed["repo"])
    first = g.load(bed["layers"])
    assert first is not None

    def boom(_repo):
        raise AssertionError("ls_files called on a weak-only change")

    monkeypatch.setattr(graph_mod, "ls_files", boom)
    log = TouchLog(bed["home"], bed["repo"].id)
    log.append_touch("s", 1, "edit", "src/a.py", ts="2026-10-16T00:00:01Z")
    log.append_use("s", 2, "names-a", "recall_hit", ts="2026-10-16T00:00:02Z")
    got = g.load(bed["layers"])
    assert got is not None
    assert got["weak"] == {"src/a.py": {"names-a": ["2026-10-16T00:00:02Z"]}}
    assert got["strong_print"] == first["strong_print"] and got["weak_print"] != first["weak_print"]


def test_a_commit_moves_strong_print(bed):
    g = TouchGraph(bed["home"], bed["repo"])
    first = g.load(bed["layers"])
    (bed["top"] / "src" / "b.py").write_text("y\n", encoding="utf-8")
    _git(bed["top"], "add", ".")
    _git(bed["top"], "commit", "-qm", "two")
    got = g.load(bed["layers"])
    assert got is not None and first is not None
    assert got["strong_print"] != first["strong_print"] and "src/b.py" in got["files"]


def test_a_fact_write_moves_strong(bed):
    g = TouchGraph(bed["home"], bed["repo"])
    g.load(bed["layers"])
    _fact(bed["store"], "body-only", "nothing here", body="the body names README.md")
    got = g.load(bed["layers"])
    assert got is not None and got["strong"]["README.md"] == [["body-only", None]]


def test_a_corrupt_graph_file_is_rebuilt(bed):
    g = TouchGraph(bed["home"], bed["repo"])
    good = g.load(bed["layers"])
    for junk in (b"{not json", b'{"version": true}', b"[]"):
        g.path.write_bytes(junk)
        assert g.load(bed["layers"]) == good
    shaped = dict(good or {}, strong=[])
    g.path.write_text(json.dumps(shaped), encoding="utf-8")
    assert g.load(bed["layers"]) == good


class _Raising:
    def __init__(self, inner):
        self.inner = inner

    def index(self):
        idx = self.inner.index()

        class _I:
            dir = idx.dir

            def refresh(self, mode):
                return idx.refresh(mode)

            def head_print(self):
                return idx.head_print()

            def docs(self):
                raise OSError("unreadable")

        return _I()


def test_a_writable_store_that_raises_makes_load_none(bed):
    layers = [("project", _Raising(MemoryStore(bed["store"])), True)]
    assert TouchGraph(bed["home"], bed["repo"]).load(layers) is None


def test_a_read_only_layer_that_raises_contributes_nothing(bed):
    layers = bed["layers"] + [("extra", _Raising(MemoryStore(bed["store"])), False)]
    got = TouchGraph(bed["home"], bed["repo"]).load(layers)
    assert got is not None and got["strong"] == {"src/a.py": [["names-a", None]]}


def test_a_missing_layer_directory_contributes_nothing_and_writes_no_index(bed, tmp_path):
    gone = NativeStore(tmp_path / "nowhere")  # a MemoryStore makes its root; a native one never
    got = TouchGraph(bed["home"], bed["repo"]).load(bed["layers"] + [("extra", gone, False)])
    assert got is not None and got["strong"] == {"src/a.py": [["names-a", None]]}
    assert not gone.index().path.exists()


def test_no_git_history_makes_load_none(tmp_path):
    top = tmp_path / "fresh"
    top.mkdir()
    _git(top, "init", "-q")  # no commit: `renames` fails
    repo = find_repo(str(top))
    assert repo is not None
    assert TouchGraph(tmp_path / "home", repo).load([]) is None


def test_index_head_print_moves_on_a_body_only_write(tmp_path):
    store = tmp_path / "s"
    _fact(store, "f", "same description", body="one")
    idx = HotIndex(store, "facts", tmp_path / "home", index_dir=tmp_path / "idx")
    idx.refresh("fast")
    first, shards = idx.head_print(), idx._loaded()["shards"]
    _fact(store, "f", "same description", body="two names src/a.py")
    idx.refresh("fast")
    assert idx._loaded()["shards"] == shards  # the body is in no posting...
    assert idx.head_print() != first  # ...and the print moves all the same
