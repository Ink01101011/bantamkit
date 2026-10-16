"""#200 Task 5: `w_context` in the ranker and the via admission path (`touch.context`)."""

from __future__ import annotations

import math

import pytest

from bantamkit.memory import retrieval
from bantamkit.memory.retrieval import weight_of
from bantamkit.memory.store import Pool
from bantamkit.touch import context as tc

G = {
    "files": ["src/a.py", "src/b.py", "docs/x.md"],
    "strong": {"src/a.py": [["fa", None], ["fb", None]], "docs/x.md": [["fx", None]]},
    "weak": {"src/b.py": {"fw": ["2026-10-16T00:00:00Z", "2026-10-02T00:00:00Z"]}},
}


def _row(seq, path, op="edit"):
    return {"ts": "2026-10-16T00:00:00Z", "session": "s", "seq": seq, "op": op, "path": path}


def test_ctx_defaults_to_zero_and_is_clamped(monkeypatch):
    monkeypatch.setattr(retrieval, "W_CONTEXT", 0.5)
    assert weight_of("project", False, 0.0) == pytest.approx(1.1)
    assert weight_of("project", False, 0.0, 1.0) == pytest.approx(1.6)
    assert weight_of("project", False, 0.0, 7.0) == pytest.approx(1.6)
    assert weight_of("project", False, 0.0, -1.0) == pytest.approx(1.1)
    assert weight_of("project", False, 0.0, math.nan) == pytest.approx(1.1)
    assert weight_of("project", False, 0.0, 0.5) == pytest.approx(1.35)


def test_w_context_is_still_zero_until_task_8():
    assert retrieval.W_CONTEXT == 0.0
    assert tc.VIA_ON is False


def test_window_is_last_twenty_calls_most_recent_first():
    rows = [_row(1, "docs/x.md"), _row(25, "src/a.py"), _row(30, "src/b.py", "read")]
    rows.append(_row(31, "src/a.py"))
    assert tc.window(rows, 31) == ["src/a.py", "src/b.py"]  # seq 1 is outside 31-20


def test_window_boundary_uses_and_folds_are_not_touches():
    rows = [_row(11, "edge.py"), _row(10, "out.py"), {"seq": 12, "op": "use", "fact": "f"}]
    rows.append({"seq": 13, "op": "folded", "path": "folded.py"})
    assert tc.window(rows, 30) == ["edge.py"]


def test_context_weights_strong_full_weak_partial():
    w = tc.context_weights(G, ["src/a.py", "src/b.py"], "2026-10-16T00:00:00Z")
    assert w["fa"] == 1.0 and w["fb"] == 1.0
    assert w["fw"] == pytest.approx(round(0.5 * (1.0 + 0.5), 9))
    assert "fx" not in w


def test_context_weights_cap_and_strong_wins_and_bad_stamp_skipped():
    g = {
        "files": ["p"],
        "strong": {"p": [["both", None]]},
        "weak": {"p": {"both": ["2026-10-16T00:00:00Z"], "many": ["2026-10-16T00:00:00Z"] * 9,
                       "bad": ["nope", "2026-10-16T00:00:00Z"]}},
    }
    w = tc.context_weights(g, ["p"], "2026-10-16T00:00:00Z")
    assert w == {"both": 1.0, "many": 1.0, "bad": 0.5}


def test_via_strong_only_window_only_one_fact():
    weigh = {"fa": 1.1, "fb": 1.3, "fw": 9.0, "fx": 9.0}.get
    # fw is weak: never admitted.
    assert tc.via_pick(G, ["src/b.py", "src/a.py"], set(), weigh) == ("fb", "src/a.py")
    assert tc.via_pick(G, ["src/a.py"], {"fb"}, weigh) == ("fa", "src/a.py")
    assert tc.via_pick(G, [], set(), weigh) is None  # docs/x.md not in window
    assert tc.via_pick(G, ["src/a.py"], {"fa", "fb"}, weigh) is None
    assert tc.via_pick(G, ["src/a.py"], set(), {"fa": 1.0, "fb": 1.0}.get) == ("fa", "src/a.py")


def test_via_label_uses_shortest_suffix():
    assert tc.via_label("src/a.py", G) == " [via a.py]"


def test_via_switch(monkeypatch):
    monkeypatch.delenv("BANTAMKIT_VIA", raising=False)
    assert tc.via_enabled() is tc.VIA_ON
    monkeypatch.setenv("BANTAMKIT_VIA", "on")
    assert tc.via_enabled() is True
    monkeypatch.setenv("BANTAMKIT_VIA", "off")
    monkeypatch.setattr(tc, "VIA_ON", True)
    assert tc.via_enabled() is False
    monkeypatch.setenv("BANTAMKIT_VIA", "yes")
    assert tc.via_enabled() is True  # not on/off: the default


def test_pool_weights_reweigh_context_names_keeping_usage(monkeypatch):
    monkeypatch.setattr(retrieval, "W_CONTEXT", 0.5)
    p = Pool(3, 0.0, {}, names=["a", "b", "c"], types=[0, 0, 0], type_names=["project"], stale=[2])
    base = p.weights({"b": 1.0})
    got = p.weights({"b": 1.0}, {"b": 1.0, "c": 0.5, "a": 0.0, "zz": 1.0})
    assert got[0] == base[0]
    assert got[1] == pytest.approx(weight_of("project", False, 1.0, 1.0))
    assert got[2] == pytest.approx(weight_of("project", True, 0.0, 0.5))
    assert p.weights({}, None) == p.weights({})
