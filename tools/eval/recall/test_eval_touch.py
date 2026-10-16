"""#200 Task 8: the touch silver miner, the touch scorer, the tuner's choice, the pass-2 builder."""
import json
import random
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]


def _line(obj):
    return json.dumps(obj) + "\n"


def _fact(root: Path, name: str, desc: str, body: str = "body") -> None:
    (root / "facts").mkdir(parents=True, exist_ok=True)
    (root / "facts" / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\ntype: project\n---\n{body}\n", encoding="utf-8")


def _git_repo(top: Path) -> Path:
    (top / "src").mkdir(parents=True)
    (top / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (top / "src" / "b.py").write_text("y = 2\n", encoding="utf-8")
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "PATH": "/usr/bin:/bin"}
    for args in (["init", "-q"], ["add", "src"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c"]):
        subprocess.run(["git", "-C", str(top), *args], check=True, env=env)
    return top.resolve()


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("BANTAMKIT_INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.setenv("BANTAMKIT_RETENTION", "off")
    monkeypatch.delenv("BANTAMKIT_VIA", raising=False)
    return tmp_path


def _tool(name, inp, tid="t", ts="2026-10-01T10:00:05.000Z"):
    return {"type": "assistant", "timestamp": ts,
            "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def _prompt(text, ts):
    return {"type": "user", "timestamp": ts, "message": {"content": text}}


def _transcript(top: Path, path: Path) -> None:
    recs = [{"type": "system", "cwd": str(top)},
            _prompt("first prompt", "2026-10-01T10:00:00.000Z"),
            _tool("Bash", {"command": "cat src/b.py"}, "b1"),
            _tool("Edit", {"file_path": str(top / "src" / "a.py")}, "e1"),
            _prompt("second prompt about the parser", "2026-10-01T10:01:00.000Z"),
            _tool("mcp__bantamkit__memory_recall", {"query": "fa"}, "r1", "2026-10-01T10:01:05.000Z"),
            {"type": "user", "timestamp": "2026-10-01T10:01:10.000Z", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "r1",
                 "content": "[project] [fa] (project) the a.py parser\nbody"}]}}]
    recs += [_tool("Bash", {"command": f"echo {i}"}, f"x{i}", f"2026-10-01T10:02:{i:02d}.000Z")
             for i in range(21)]
    recs.append(_prompt("third prompt", "2026-10-01T10:05:00.000Z"))
    path.write_text("".join(_line(r) for r in recs), encoding="utf-8")


def _stores(scratch: Path) -> tuple[Path, Path]:
    proj, prof = scratch / "project", scratch / "profile"
    _fact(proj, "fa", "the parser in src/a.py")
    _fact(proj, "fz", "deploy only on tuesdays")
    (prof / "facts").mkdir(parents=True)
    return proj, prof


def test_miner_window_positives_and_bash_counts_without_a_path(scratch: Path):
    from tools.eval.recall.mine_touch_silver import mine

    top = _git_repo(scratch / "repo")
    proj, prof = _stores(scratch)
    projects = scratch / "projects" / "slug"
    projects.mkdir(parents=True)
    _transcript(top, projects / "s1.jsonl")
    silver, rows = mine(projects.parent, top, proj, prof, None, scratch / "home")
    assert [r["prompt"] for r in silver] == ["first prompt", "second prompt about the parser",
                                             "third prompt"]
    assert silver[0]["window"] == [] and silver[0]["positives"] == []
    assert silver[1]["window"] == ["src/a.py"]  # the Bash call took seq 1 and added no path
    assert silver[1]["positives"] == ["fa"]  # recalled after prompt 2, and it names src/a.py
    assert silver[2]["window"] == []  # 21 Bash calls later the Edit has left the window
    assert silver[1]["seq"] == 2 and silver[2]["seq"] == 24
    ops = [(r["op"], r.get("path") or r.get("fact"), r["seq"]) for r in rows]
    assert ops == [("edit", "src/a.py", 2), ("use", "fa", 3)]
    assert all(r["session"] == "s1" and r["ts"].endswith("Z") and "." not in r["ts"] for r in rows)


def test_miner_positive_needs_a_use_and_a_strong_edge_to_the_window(scratch: Path):
    from tools.eval.recall.mine_touch_silver import mine

    top = _git_repo(scratch / "repo")
    proj, prof = _stores(scratch)
    projects = scratch / "projects" / "slug"
    projects.mkdir(parents=True)
    _transcript(top, projects / "s1.jsonl")
    t = projects / "s1.jsonl"
    t.write_text(t.read_text(encoding="utf-8").replace('"query": "fa"', '"query": "fz"')
                 .replace("[fa] (project) the a.py parser", "[fz] (project) tuesdays"),
                 encoding="utf-8")
    silver, _rows = mine(projects.parent, top, proj, prof, None, scratch / "home")
    # fz was used after prompt 2 too, but its text names no file in the window
    assert silver[1]["window"] == ["src/a.py"] and silver[1]["positives"] == []


def test_miner_skips_a_session_whose_cwd_is_another_directory(scratch: Path):
    from tools.eval.recall.mine_touch_silver import mine

    top = _git_repo(scratch / "repo")
    proj, prof = _stores(scratch)
    projects = scratch / "projects" / "slug"
    projects.mkdir(parents=True)
    _transcript(scratch, projects / "s1.jsonl")  # cwd is the parent, not the repo
    silver, rows = mine(projects.parent, top, proj, prof, None, scratch / "home")
    assert silver == [] and rows == []


def test_score_touch_via_on_admits_the_strong_edge_fact(scratch: Path):
    from tools.eval.recall.mine_touch_silver import mine
    from tools.eval.recall.score_touch import Scorer

    top = _git_repo(scratch / "repo")
    proj, prof = _stores(scratch)
    projects = scratch / "projects" / "slug"
    projects.mkdir(parents=True)
    _transcript(top, projects / "s1.jsonl")
    silver, rows = mine(projects.parent, top, proj, prof, None, scratch / "home")
    # a prompt whose words match no fact: the gate picks nothing, so only the via path can admit
    labels = [{**r, "prompt": "what next", "positives": ["fa"]} for r in silver if r["window"]]
    sc = Scorer(proj, prof, None, top, rows, scratch / "home")
    off = sc.score(labels, w_context=0.0, weak_share=0.5, via=False)
    assert off["via_n"] == 0
    on = sc.score(labels, w_context=0.0, weak_share=0.5, via=True)
    assert on["via_n"] == 1 and on["via_precision"] == 1.0 and on["n"] == 1
    assert on["precision_at_inject"] == 1.0  # fa is the only injection, and it is positive


def test_score_touch_keeps_edges_from_the_future_out(scratch: Path):
    from tools.eval.recall.score_touch import graph_at

    base = {"files": ["src/a.py"], "strong": {}, "weak": {}}
    rows = [{"ts": "2026-10-01T10:00:00Z", "session": "s", "seq": 1, "op": "read", "path": "src/a.py"},
            {"ts": "2026-10-01T10:00:30Z", "session": "s", "seq": 2, "op": "use", "fact": "fw",
             "kind": "recall_hit"}]
    assert graph_at(base, rows, "2026-10-01T10:00:10Z")["weak"] == {}
    assert graph_at(base, rows, "2026-10-01T10:01:00Z")["weak"] == {
        "src/a.py": {"fw": ["2026-10-01T10:00:30Z"]}}


def test_score_touch_overrides_are_restored(scratch: Path):
    from bantamkit.memory import retrieval
    from bantamkit.touch import context
    from tools.eval.recall.score_touch import overrides

    saved = (retrieval.W_CONTEXT, context.CONTEXT_WEAK_SHARE, context.VIA_ON)
    with overrides(0.8, 0.25, True):
        assert (retrieval.W_CONTEXT, context.CONTEXT_WEAK_SHARE, context.via_enabled()) == (
            0.8, 0.25, True)
    assert (retrieval.W_CONTEXT, context.CONTEXT_WEAK_SHARE, context.VIA_ON) == saved


def _pt(w, s, p, r):
    return {"W_CONTEXT": w, "CONTEXT_WEAK_SHARE": s, "precision_at_inject": p, "recall_at_3": r}


def test_tune_choice_max_recall_not_below_baseline_precision():
    from tools.eval.recall.tune_context import choose

    pts = [_pt(0.0, 0.0, 0.30, 0.10), _pt(0.0, 0.5, 0.30, 0.10), _pt(0.2, 0.5, 0.31, 0.20),
           _pt(0.4, 0.5, 0.29, 0.40), _pt(0.8, 1.0, 0.31, 0.20)]
    c = choose(pts)
    assert (c["W_CONTEXT"], c["CONTEXT_WEAK_SHARE"]) == (0.2, 0.5)  # 0.4 costs precision
    # ties on recall and precision: the smaller W_CONTEXT, then the share nearest today's 0.5
    pts2 = [_pt(0.0, 0.5, 0.3, 0.1), _pt(0.4, 1.0, 0.3, 0.2), _pt(0.4, 0.25, 0.3, 0.2),
            _pt(0.2, 1.0, 0.3, 0.2)]
    c2 = choose(pts2)
    assert (c2["W_CONTEXT"], c2["CONTEXT_WEAK_SHARE"]) == (0.2, 1.0)
    # nothing beats the baseline: the baseline is kept, at today's share
    c3 = choose([_pt(0.0, 0.0, 0.3, 0.1), _pt(0.0, 0.5, 0.3, 0.1), _pt(0.1, 0.5, 0.2, 0.5)])
    assert (c3["W_CONTEXT"], c3["CONTEXT_WEAK_SHARE"]) == (0.0, 0.5)


def test_via_gold_rows_pool_every_view_and_name_no_view():
    from tools.eval.recall.build_via_gold import pass2_rows

    picked = [{"id": 1, "prompt": "fix it", "window": ["src/a.py", "src/b.py"], "thai": False,
               "via": ("fa", "a.py"), "views": {"ctx0": ["fz"], "ctx": ["fa", "fz"],
                                                 "ctx_via": ["fz", "fa"], "via": ["fa"]}}]
    copies = {"fa": [{"description": "d", "body": "b"}], "fz": [{"description": "e", "body": "c"}]}
    cands, judge, inj, pool = pass2_rows(picked, lambda n: copies[n], lambda p: p.split("/")[-1],
                                         random.Random(200))
    assert cands == [{"id": 1, "prompt": "fix it — touched: a.py, b.py; via a.py",
                      "candidates": ["fa"], "thai": False}]
    assert judge[0]["prompt"] == cands[0]["prompt"]
    assert sorted(c["name"] for c in judge[0]["candidates"]) == ["fa", "fz"]
    assert set(judge[0]) == {"id", "prompt", "candidates"}
    assert all(set(c) == {"name", "copies"} for c in judge[0]["candidates"])
    text = json.dumps(judge)
    assert not any(v in text for v in ('"ctx0"', '"ctx"', '"ctx_via"', '"via"'))
    assert inj == {"1": picked[0]["views"]}
    assert pool[0]["candidates"] == [c["name"] for c in judge[0]["candidates"]]


def test_miner_counts_a_subagents_tool_calls_into_the_session(scratch: Path):
    from tools.eval.recall.mine_touch_silver import mine

    top = _git_repo(scratch / "repo")
    proj, prof = _stores(scratch)
    projects = scratch / "projects" / "slug"
    (projects / "s1" / "subagents").mkdir(parents=True)
    _transcript(top, projects / "s1.jsonl")
    t = projects / "s1.jsonl"  # the main thread recalls fz, never fa
    t.write_text(t.read_text(encoding="utf-8").replace('"query": "fa"', '"query": "fz"')
                 .replace("[fa] (project) the a.py parser", "[fz] (project) tuesdays"),
                 encoding="utf-8")
    sub = [{"isSidechain": True, "type": "user", "timestamp": "2026-10-01T10:00:06.000Z",
            "message": {"content": "a brief, never a prompt"}},
           {**_tool("Read", {"file_path": str(top / "src" / "b.py")}, "s1"), "isSidechain": True,
            "timestamp": "2026-10-01T10:00:07.000Z"},
           {**_tool("mcp__bantamkit__memory_recall", {"query": "fa"}, "s2"), "isSidechain": True,
            "timestamp": "2026-10-01T10:01:20.000Z"}]
    (projects / "s1" / "subagents" / "agent-x.jsonl").write_text(
        "".join(_line(r) for r in sub), encoding="utf-8")
    silver, rows = mine(projects.parent, top, proj, prof, None, scratch / "home")
    assert [r["prompt"] for r in silver] == ["first prompt", "second prompt about the parser",
                                             "third prompt"]
    assert silver[1]["seq"] == 3 and silver[1]["window"] == ["src/b.py", "src/a.py"]
    # the subagent's recall of fa follows prompt 2 and fa names src/a.py, but only the main
    # thread's own use labels a positive (the mine_silver rule)
    assert silver[1]["positives"] == []
    assert ("read", "src/b.py", 3) in [(r["op"], r.get("path"), r["seq"]) for r in rows]


def test_via_gold_pool_always_holds_the_via_fact():
    from tools.eval.recall.build_via_gold import pass2_rows

    picked = [{"id": 1, "prompt": "p", "window": ["src/a.py"], "thai": True, "via": ("fa", "a.py"),
               "views": {"ctx0": ["fz"]}}]
    _c, judge, _i, pool = pass2_rows(picked, lambda n: [], lambda p: p, random.Random(1))
    assert sorted(pool[0]["candidates"]) == ["fa", "fz"]
