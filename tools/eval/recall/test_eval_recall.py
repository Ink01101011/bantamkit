import json
from pathlib import Path

import pytest
from tools.eval.recall.mine_silver import is_thai, mine_transcript
from tools.eval.recall.score import metrics


def _line(obj):
    return json.dumps(obj) + "\n"


def test_prompt_followed_by_recall_call_labels_positive(tmp_path: Path):
    t = tmp_path / "s.jsonl"
    t.write_text(
        _line({"type": "user", "message": {"content": "ช่วยดู release lessons หน่อย"}})
        + _line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "mcp__bantamkit__memory_recall",
             "input": {"query": "release-0-35-4-out-on-both-registries"}}]}}),
        encoding="utf-8",
    )
    rows = list(mine_transcript(t, known={"release-0-35-4-out-on-both-registries"}))
    assert rows == [{"prompt": "ช่วยดู release lessons หน่อย",
                     "positives": ["release-0-35-4-out-on-both-registries"],
                     "thai": True, "session": "s"}]


def test_read_of_memory_file_labels_positive(tmp_path: Path):
    t = tmp_path / "s.jsonl"
    t.write_text(
        _line({"type": "user", "message": {"content": "what did we decide on tags"}})
        + _line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read",
             "input": {"file_path": "/x/memory/merge-authorized-standing-tag-withheld.md"}}]}}),
        encoding="utf-8",
    )
    rows = list(mine_transcript(t, known={"merge-authorized-standing-tag-withheld"}))
    assert rows[0]["positives"] == ["merge-authorized-standing-tag-withheld"]
    assert rows[0]["thai"] is False


def test_is_thai():
    assert is_thai("กิน context ไหม") and not is_thai("eats context?")


def test_metrics_precision_and_recall():
    injected = {1: ["a", "b"], 2: [], 3: ["c"]}
    gold = {1: {"a"}, 2: {"d"}, 3: {"x"}}
    ranked = {1: ["a", "b", "z"], 2: ["d", "q", "r"], 3: ["c", "x", "y"]}
    m = metrics(injected, ranked, gold, thai_ids={2})
    assert m["precision_at_inject"] == 1 / 3      # a ok, b no, c no
    assert m["recall_at_3"] == 3 / 3              # a, d, x all inside top 3
    assert m["thai_recall_at_3"] == 1.0


# --- additions beyond the plan's four (J68-0): the shapes the real corpus has ---


def test_read_of_bantamkit_store_fact_labels_positive(tmp_path: Path):
    t = tmp_path / "s.jsonl"
    t.write_text(
        _line({"type": "user", "message": {"content": "tags?"}})
        + _line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read",
             "input": {"file_path": "/r/.bantamkit/memory/facts/tag-rule.md"}}]}}),
        encoding="utf-8",
    )
    assert [r["positives"] for r in mine_transcript(t, known={"tag-rule"})] == [["tag-rule"]]


def test_meta_and_sidechain_records_neither_open_nor_close_a_window(tmp_path: Path):
    t = tmp_path / "s.jsonl"
    t.write_text(
        _line({"type": "user", "message": {"content": "real prompt"}})
        + _line({"type": "user", "isMeta": True, "message": {"content": "hand-back text"}})
        + _line({"type": "user", "isSidechain": True, "message": {"content": "a brief"}})
        + _line({"type": "user", "message": {"content": "<command-name>/clear</command-name>"}})
        + _line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "mcp__bantamkit__memory_recall",
             "input": {"query": "tag-rule"}}]}}),
        encoding="utf-8",
    )
    rows = list(mine_transcript(t, known={"tag-rule"}))
    assert [r["prompt"] for r in rows] == ["real prompt"]


def test_recall_query_not_a_known_name_labels_nothing(tmp_path: Path):
    t = tmp_path / "s.jsonl"
    t.write_text(
        _line({"type": "user", "message": {"content": "p"}})
        + _line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "mcp__bantamkit__memory_recall",
             "input": {"query": "tag rule words"}}]}}),
        encoding="utf-8",
    )
    assert list(mine_transcript(t, known={"tag-rule"})) == []


def _fact(root: Path, name: str, desc: str) -> None:
    (root / "facts").mkdir(parents=True, exist_ok=True)
    (root / "facts" / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\ntype: project\n---\nbody\n", encoding="utf-8")


_REPO = Path(__file__).resolve().parents[3]

# The original v1 test's body, run in a child whose import path is the pre-#199 source: since
# Task 5 the v1 engine exists only there (J68-7), so that is where its property is checked.
_V1_CHILD = """
import sys
from pathlib import Path
import bantamkit
from tools.eval.recall.score import _engine
tmp = Path(sys.argv[1])
proj, prof = tmp / "project", tmp / "profile"
before = {p: p.read_bytes() for p in tmp.rglob("*") if p.is_file()}
inject, rank = _engine("v1", proj, prof)
assert set(rank("deploy service tuesdays")) == {"deploy-command", "deploy-window"}
assert inject("nothing matches zzz") == []
after = {p: p.read_bytes() for p in tmp.rglob("*") if p.is_file()}
assert after == before
print(bantamkit.__file__)
"""


def test_v1_engine_reads_only_the_copies_and_writes_nothing(tmp_path: Path):
    import os
    import subprocess
    import sys

    from tools.eval.recall.score import V1_SOURCE

    v1 = tmp_path / "v1"
    v1.mkdir()
    arch = subprocess.run(["git", "-C", str(_REPO), "archive", V1_SOURCE, "runtime-py/src"],
                          capture_output=True, check=False)
    if arch.returncode != 0:
        pytest.skip(f"no {V1_SOURCE} in this clone: {arch.stderr.decode('utf-8', 'replace')}")
    subprocess.run(["tar", "-x", "-C", str(v1)], input=arch.stdout, check=True)
    data = tmp_path / "data"
    _fact(data / "project", "deploy-command", "how to deploy the service")
    _fact(data / "profile", "deploy-window", "deploy only on tuesdays")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(v1 / "runtime-py" / "src"), str(_REPO)])}
    out = subprocess.run([sys.executable, "-c", _V1_CHILD, str(data)], cwd=_REPO, env=env,
                         capture_output=True, encoding="utf-8", check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().startswith(str(v1)), out.stdout  # the v1 source answered


def test_v1_engine_refuses_on_a_tree_whose_recall_is_v2(tmp_path: Path):
    from tools.eval.recall.score import _engine

    proj, prof = tmp_path / "project", tmp_path / "profile"
    _fact(proj, "deploy-command", "how to deploy the service")
    _fact(prof, "deploy-window", "deploy only on tuesdays")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(SystemExit) as e:
        _engine("v1", proj, prof)
    msg = str(e.value)
    assert msg.startswith("--engine v1 refused: the bantamkit on the import path (")
    assert "git archive 4bab744 runtime-py/src | tar -x -C <dir>" in msg
    assert msg.endswith("PYTHONPATH=<dir>/runtime-py/src")
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_build_gold_picks_thai_first_and_caps_candidates():
    import random

    from tools.eval.recall.build_gold import candidates_for, pick_rows

    rows = [{"prompt": f"p{i}", "positives": ["a"], "thai": i < 3, "session": f"s{i % 4}"}
            for i in range(30)]
    rows.append(dict(rows[0]))  # a duplicate prompt is picked once
    picked = pick_rows(rows, 10, 5, random.Random(199))
    assert len(picked) == 10 and len({r["prompt"] for r in picked}) == 10
    assert sum(r["thai"] for r in picked) == 3  # all three Thai rows, fewer than the minimum
    c = candidates_for({"prompt": "x", "positives": ["a", "b"]}, lambda p: ["b", "c"],
                       ["a", "d", "e", "f", "g", "h"], 5, random.Random(1))
    assert len(c) == 5 and len(set(c)) == 5 and {"a", "b", "c"} <= set(c)


def _gold_fixture():
    cand = {1: {"id": 1, "prompt": "p1", "candidates": ["a", "b", "c", "d"], "thai": True},
            2: {"id": 2, "prompt": "p2", "candidates": ["e", "f", "g", "h"], "thai": False}}
    judge = {1: {"id": 1, "positives": ["a"]}, 2: {"id": 2, "positives": ["e", "f"]}}
    return cand, judge


def test_gold_agreement_is_raw_and_kappa_over_user_prompts_only():
    from tools.eval.recall.gold_merge import agreement
    cand, judge = _gold_fixture()
    # the user agrees on 3 of 4 candidates of prompt 1; prompt 2 is not in the spot-check
    res = agreement(cand, judge, {1: {"id": 1, "positives": ["a", "b"]}})
    assert res["n"] == 4 and res["agreement"] == 0.75
    # po 0.75, pj 0.25, pu 0.5, pe 0.5 -> kappa 0.5
    assert res["kappa"] == 0.5


def test_gold_merge_user_rows_replace_the_judge():
    from tools.eval.recall.gold_merge import merge
    cand, judge = _gold_fixture()
    out = merge(cand, judge, {1: {"id": 1, "positives": ["b"]}})
    assert out == [{"id": 1, "prompt": "p1", "positives": ["b"], "thai": True},
                   {"id": 2, "prompt": "p2", "positives": ["e", "f"], "thai": False}]


def _run_gold_merge(tmp_path: Path, judge_pos: list[str], user_pos: list[str]):
    import subprocess
    import sys
    names = list("abcdefghij")
    c, j, u, out = (tmp_path / n for n in ("c.jsonl", "j.jsonl", "u.jsonl", "gold.jsonl"))
    c.write_text(_line({"id": 1, "prompt": "p", "candidates": names, "thai": False}), encoding="utf-8")
    j.write_text(_line({"id": 1, "positives": judge_pos}), encoding="utf-8")
    u.write_text(_line({"id": 1, "positives": user_pos}), encoding="utf-8")
    script = Path(__file__).with_name("gold_merge.py")
    r = subprocess.run([sys.executable, str(script), "--candidates", str(c), "--judge", str(j),
                        "--user", str(u), "--out", str(out)], capture_output=True, text=True, encoding="utf-8",
                       check=False)
    return r, out


@pytest.mark.parametrize(("judge_pos", "user_pos", "failing"), [
    # agreement 0.9 clears 0.9, kappa 0.0 misses 0.6: guards the kappa clause
    ([], ["a"], "kappa"),
    # kappa 0.6 clears 0.6, agreement 0.8 misses 0.9: guards the agreement clause
    (list("abcde"), list("abcdf"), "agreement"),
])
def test_gold_merge_refuses_when_either_clause_misses(tmp_path: Path, judge_pos, user_pos, failing):
    r, out = _run_gold_merge(tmp_path, judge_pos, user_pos)
    assert r.returncode == 1 and not out.exists(), (failing, r.stdout, r.stderr)
    assert json.loads(r.stdout)["pass"] is False


def test_gold_merge_writes_gold_when_both_clauses_clear(tmp_path: Path):
    r, out = _run_gold_merge(tmp_path, ["a", "b"], ["a", "b"])
    assert r.returncode == 0, r.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["positives"] == ["a", "b"]


# --- tune.py (J68-7): silver only, overrides that take effect and are undone, the rule ---


def test_tune_refuses_a_label_set_without_sessions(tmp_path: Path):
    from tools.eval.recall.tune import read_silver

    gold = tmp_path / "gold-labels.jsonl"
    gold.write_text(_line({"id": 1, "prompt": "p", "positives": ["a"], "thai": False}),
                    encoding="utf-8")
    with pytest.raises(SystemExit, match="has no session; tune.py reads silver only"):
        read_silver(gold)


def test_tune_overrides_reach_the_scoring_walk_and_are_restored(tmp_path: Path, monkeypatch):
    from bantamkit.memory import component, retrieval
    from bantamkit.memory.component import Memory
    from tools.eval.recall.tune import overrides

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("BANTAMKIT_INDEX_DIR", str(tmp_path / "index"))
    proj, prof = tmp_path / "project", tmp_path / "profile"
    _fact(proj, "deploy-command", "how to deploy the service")
    _fact(prof, "deploy-window", "deploy only on tuesdays")
    m = Memory.layered_for_eval(project=proj, profile=prof)
    before = [f.name for f in m.inject_candidates("deploy service")]
    saved = (retrieval.GATE_FLOOR, retrieval.W_USAGE, dict(retrieval.W_TYPE),
             component.RECALL_MIN_SCORE_RATIO)
    assert before
    point = {"GATE_FLOOR": 1e9, "GATE_RATIO": 0.0, "W_USAGE": 0.0, "W_TYPE.feedback": 1.0}
    with overrides(point):
        assert m.inject_candidates("deploy service") == []
        assert m.rank_all("deploy service") == []
    with overrides({**point, "GATE_FLOOR": 0.0, "GATE_RATIO": 1.0}):
        assert [f.name for f in m.inject_candidates("deploy service")] == before[:1]
    assert (retrieval.GATE_FLOOR, retrieval.W_USAGE, dict(retrieval.W_TYPE),
            component.RECALL_MIN_SCORE_RATIO) == saved
    assert [f.name for f in m.inject_candidates("deploy service")] == before


def _pt(floor, ratio, usage, fb, p, r, thai=0.1, injected=50):
    return {"constants": {"GATE_FLOOR": floor, "GATE_RATIO": ratio, "W_USAGE": usage,
                          "W_TYPE.feedback": fb},
            "B": {"precision_at_inject": p, "recall_at_3": r, "thai_recall_at_3": thai,
                  "injected": injected}}


def test_tune_choose_feasible_then_fallback_then_nearest_current():
    from tools.eval.recall.tune import choose

    pts = [_pt(0, 0, 0.2, 1.3, 0.9, 0.2), _pt(1, 0, 0.2, 1.3, 0.86, 0.3),
           _pt(2, 0, 0.2, 1.3, 0.5, 0.9)]
    assert choose(pts, 0.05, 0.85, 10)[0] is pts[1]          # clause 1: best recall, feasible
    pts = [_pt(0, 0, 0.2, 1.3, 0.1, 0.2), _pt(1, 0, 0.2, 1.3, 0.4, 0.06),
           _pt(2, 0, 0.2, 1.3, 0.6, 0.01), _pt(3, 0, 0.2, 1.3, 0.7, 0.3, injected=3)]
    best, clause = choose(pts, 0.05, 0.85, 10)
    assert best is pts[1] and clause.startswith("2")           # under v1 and under 10 fall out
    pts = [_pt(0, 0, 0.0, 1.3, 0.4, 0.2), _pt(0, 0, 0.2, 1.3, 0.4, 0.2),
           _pt(0, 0, 0.4, 1.6, 0.4, 0.2)]
    assert choose(pts, 0.05, 0.85, 10)[0] is pts[1]           # a tie keeps today's W_USAGE


# --- score_pooled.py (J68-17): gold positives plus pool positives, and no unlabelled fact ---


def _pooled_fixture(tmp_path: Path, injected_extra: str | None = None):
    # prompt 1: gold judged a, b, c (a positive); the pool judged d, e (d positive)
    # prompt 2: gold judged x, y (none positive); nothing was pooled for it
    files = {
        "gold.jsonl": [{"id": 1, "prompt": "p1", "positives": ["a"], "thai": True},
                       {"id": 2, "prompt": "p2", "positives": [], "thai": False}],
        "cand.jsonl": [{"id": 1, "candidates": ["a", "b", "c"]}, {"id": 2, "candidates": ["x", "y"]}],
        "targets.jsonl": [{"id": 1, "prompt": "p1", "candidates": [
            {"name": "d", "copies": []}, {"name": "e", "copies": []}]}],
        "labels.jsonl": [{"id": 1, "positives": ["d"]}],
    }
    for name, rows in files.items():
        (tmp_path / name).write_text("".join(_line(r) for r in rows), encoding="utf-8")
    inj = {"1": {"v1": ["a", "b"], "B": ["d", "a", "e"]}, "2": {"v1": ["x"], "B": []}}
    if injected_extra:
        inj["2"]["B"].append(injected_extra)
    (tmp_path / "inj.json").write_text(json.dumps(inj), encoding="utf-8")
    return ["--gold", "gold.jsonl", "--candidates", "cand.jsonl", "--pool-targets", "targets.jsonl",
            "--pool-labels", "labels.jsonl", "--injections", "inj.json"]


def _run_pooled(tmp_path: Path, args: list[str]):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[3]
    return subprocess.run([sys.executable, "-m", "tools.eval.recall.score_pooled",
                           *[str(tmp_path / x) if x.endswith((".jsonl", ".json")) else x for x in args]],
                          capture_output=True, text=True, encoding="utf-8", check=False, cwd=root)


def test_score_pooled_relevant_is_gold_positives_union_pool_positives(tmp_path: Path):
    r = _run_pooled(tmp_path, _pooled_fixture(tmp_path))
    assert r.returncode == 0, r.stderr
    out = {row["view"]: row for row in map(json.loads, r.stdout.splitlines())}
    assert list(out) == ["B", "v1"]
    # B injects d (pool positive), a (gold positive), e (pool negative): 2 of 3 right, both relevant in its top 3
    assert out["B"]["precision_at_inject"] == 2 / 3 and out["B"]["recall_at_3"] == 1.0
    assert out["B"]["thai_recall_at_3"] == 1.0 and out["B"]["injected"] == 3
    # v1 injects a, b, x: 1 of 3 right; it misses the pool positive d, so recall@3 over {a, d} is 0.5
    assert out["v1"]["precision_at_inject"] == 1 / 3 and out["v1"]["recall_at_3"] == 0.5


def test_score_pooled_refuses_a_fact_nobody_labelled(tmp_path: Path):
    r = _run_pooled(tmp_path, _pooled_fixture(tmp_path, injected_extra="z"))
    assert r.returncode != 0 and r.stdout == ""
    assert "prompt 2: injected fact z (B) was never labelled" in r.stderr
