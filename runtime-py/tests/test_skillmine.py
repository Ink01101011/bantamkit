"""skillmine (#206 Task 4a): shiftwork pieces of work, their signature and similarity.

`runtime-ts/test/skillmine.test.mjs` mirrors each test; `skill-miner` compares the runtimes.
Every fixture is synthetic.
"""

from __future__ import annotations

import gzip
import json
import os
from collections import Counter
from pathlib import Path

import pytest

from bantamkit import skillmine
from bantamkit.skillmine import Piece, Signature, doc_freq, meets, signature, similarity


def _ckpt(job_id: str, units: list[tuple[str, str, str]], history: list[dict] | None = None) -> str:
    return json.dumps(
        {
            "version": 1,
            "job": {"id": job_id, "goal": "g", "done_definition": "d", "constraints": []},
            "plan": {
                "cursor": units[0][0],
                "units": [
                    {
                        "id": uid,
                        "title": title,
                        "brief_path": brief,
                        "status": "done",
                        "role": "implementer",
                        "depends_on": [],
                        "verify": "true",
                    }
                    for uid, title, brief in units
                ],
            },
            "history": history or [],
        }
    )


def _line(unit: str, status: str, ts: str, **extra) -> str:
    return json.dumps({"unit": unit, "role": "implementer", "status": status, "ts": ts, **extra})


def _brief(unit: str) -> str:
    return json.dumps(
        {"event": "brief", "unit": unit, "role": "implementer", "ts": "2026-01-01T00:00:00Z"}
    )


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "fix.py").write_text("x\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("y\n", encoding="utf-8")
    return root


def _three_jobs(root: Path) -> None:
    sw = root / ".shiftwork"
    (sw / "briefs-job72").mkdir(parents=True)
    (sw / "briefs-job73").mkdir()
    # job71: archived by Retention, its briefs only inside the bundle.
    bundle = {
        ".shiftwork/checkpoint-job71.json": _ckpt(
            "job71",
            [
                ("U1", "fix the parser", ".shiftwork/briefs-job71/U1.md"),
                ("U2", "write the release note", ".shiftwork/briefs-job71/U2.md"),
            ],
        ),
        ".shiftwork/checkpoint-job71.json.log.jsonl": "\n".join(
            [
                _brief("U1"),
                _line("U1", "done", "2026-01-02T00:00:00Z"),
                _line("U2", "done", "2026-01-03T00:00:00Z"),
            ]
        )
        + "\n",
        ".shiftwork/briefs-job71/U1.md": "Edit src/fix.py and run the tests.\n",
        ".shiftwork/briefs-job71/U2.md": "Update `docs/guide.md`, then docs/missing.md.\n",
    }
    (sw / "archive").mkdir()
    (sw / "archive" / "job71.json.gz").write_bytes(
        gzip.compress(json.dumps(bundle).encode(), mtime=0)
    )
    # job72: live, one done, one dropped.
    (sw / "checkpoint-job72.json").write_text(
        _ckpt(
            "job72",
            [
                ("U1", "fix the lexer", ".shiftwork/briefs-job72/U1.md"),
                ("U2", "dropped work", ".shiftwork/briefs-job72/U2.md"),
            ],
        ),
        encoding="utf-8",
    )
    (sw / "checkpoint-job72.json.log.jsonl").write_text(
        "\n".join(
            [
                _line("U1", "in_progress", "2026-02-01T00:00:00Z"),
                _line("U1", "done", "2026-02-02T00:00:00Z"),
                _line("U2", "dropped", "2026-02-03T00:00:00Z"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (sw / "briefs-job72" / "U1.md").write_text(
        "See ./src/fix.py:12 and .shiftwork/briefs-job72/U1.md.\n", encoding="utf-8"
    )
    (sw / "briefs-job72" / "U2.md").write_text("nothing\n", encoding="utf-8")
    # job73: live, one blocked unit with a history entry.
    (sw / "checkpoint-job73.json").write_text(
        _ckpt(
            "job73",
            [("U1", "port the lexer", ".shiftwork/briefs-job73/U1.md")],
            history=[{"unit": "U1", "outcome": "blocked", "notes": "the gate was red"}],
        ),
        encoding="utf-8",
    )
    (sw / "checkpoint-job73.json.log.jsonl").write_text(
        _line("U1", "blocked", "2026-03-01T00:00:00Z") + "\n", encoding="utf-8"
    )
    (sw / "briefs-job73" / "U1.md").write_text("Port it.\n", encoding="utf-8")


def test_three_jobs_yield_pieces_per_r1_and_r2(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _three_jobs(root)
    pieces = skillmine.shiftwork_pieces(root)
    assert [p.id for p in pieces] == ["job71/U1", "job71/U2", "job72/U1", "job72/U2", "job73/U1"]
    by = {p.id: p for p in pieces}
    assert [by[i].ok for i in ("job71/U1", "job71/U2", "job72/U1", "job72/U2", "job73/U1")] == [
        True,
        True,
        True,
        None,
        False,
    ]
    assert by["job72/U1"].ts == "2026-02-02T00:00:00Z"  # the LAST clock-out
    assert by["job71/U1"].prompt == "fix the parser\nEdit src/fix.py and run the tests.\n"
    assert by["job71/U1"].paths == frozenset({"src/fix.py"})
    assert by["job71/U2"].paths == frozenset({"docs/guide.md"})  # missing.md does not exist
    assert by["job72/U1"].paths == frozenset({"src/fix.py"})  # `./`, `:12`; .shiftwork never named
    assert by["job73/U1"].failure == "blocked\nthe gate was red"
    assert by["job72/U2"].failure is None  # no history entry
    assert by["job72/U1"].failure is None
    real = os.path.realpath(root)
    assert all(p.repo == os.path.join(real, ".git") for p in pieces)
    assert all(p.source == "shiftwork" and p.tools == () and dict(p.signals) == {} for p in pieces)
    d = by["job71/U1"].as_dict()
    assert list(d) == sorted(d)
    assert d["paths"] == ["src/fix.py"] and d["tools"] == []


def test_dropped_and_in_progress_are_neither(tmp_path: Path) -> None:
    root = _root(tmp_path)
    sw = root / ".shiftwork"
    sw.mkdir()
    (sw / "checkpoint-j.json").write_text(
        _ckpt("j", [("A", "a", "x.md"), ("B", "b", "x.md")]), encoding="utf-8"
    )
    (sw / "checkpoint-j.json.log.jsonl").write_text(
        _line("A", "in_progress", "2026-01-01T00:00:00Z")
        + "\n"
        + _line("B", "dropped", "2026-01-01T00:00:00Z")
        + "\n",
        encoding="utf-8",
    )
    assert [p.ok for p in skillmine.shiftwork_pieces(root)] == [None, None]


def test_uncommitted_takes_back_the_clock_out_it_follows(tmp_path: Path) -> None:
    root = _root(tmp_path)
    sw = root / ".shiftwork"
    sw.mkdir()
    (sw / "checkpoint-j.json").write_text(
        _ckpt("j", [("A", "a", "x.md"), ("B", "b", "x.md")]), encoding="utf-8"
    )
    (sw / "checkpoint-j.json.log.jsonl").write_text(
        "\n".join(
            [
                _line("A", "blocked", "2026-01-01T00:00:00Z"),
                _line("A", "done", "2026-01-02T00:00:00Z"),
                json.dumps({"event": "uncommitted", "unit": "A", "role": "implementer", "ts": "x"}),
                _line("B", "done", "2026-01-03T00:00:00Z"),
                json.dumps({"event": "uncommitted", "unit": "B", "role": "implementer", "ts": "x"}),
                "{not json",
                "[1]",
                json.dumps({"unit": "A", "status": "weird", "ts": "t"}),
                json.dumps({"unit": "A", "status": "done"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    pieces = skillmine.shiftwork_pieces(root)
    assert [(p.id, p.ok, p.ts) for p in pieces] == [("j/A", False, "2026-01-01T00:00:00Z")]


def test_brief_outside_the_repo_is_ignored(tmp_path: Path) -> None:
    root = _root(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret src/fix.py\n", encoding="utf-8")
    sw = root / ".shiftwork"
    sw.mkdir()
    (sw / "link.md").symlink_to(outside)
    (sw / "checkpoint-j.json").write_text(
        _ckpt(
            "j",
            [
                ("A", "abs", str(outside)),
                ("B", "dotdot", "../outside.md"),
                ("C", "link", ".shiftwork/link.md"),
            ],
        ),
        encoding="utf-8",
    )
    (sw / "checkpoint-j.json.log.jsonl").write_text(
        "\n".join(_line(u, "done", "2026-01-01T00:00:00Z") for u in "ABC") + "\n", encoding="utf-8"
    )
    pieces = skillmine.shiftwork_pieces(root)
    assert [(p.prompt, p.paths) for p in pieces] == [
        ("abs", frozenset()),
        ("dotdot", frozenset()),
        ("link", frozenset()),
    ]


def test_plain_checkpoint_takes_job_id_and_live_wins_over_archive(tmp_path: Path) -> None:
    root = _root(tmp_path)
    sw = root / ".shiftwork"
    (sw / "archive").mkdir(parents=True)
    (sw / "checkpoint.json").write_text(_ckpt("myjob", [("A", "live", "x.md")]), encoding="utf-8")
    (sw / "checkpoint.json.log.jsonl").write_text(
        _line("A", "done", "2026-01-01T00:00:00Z") + "\n", encoding="utf-8"
    )
    bundle = {
        ".shiftwork/checkpoint-myjob.json": _ckpt("myjob", [("A", "archived", "x.md")]),
        ".shiftwork/checkpoint-myjob.json.log.jsonl": _line("A", "done", "2026-01-01T00:00:00Z"),
    }
    (sw / "archive" / "myjob.json.gz").write_bytes(gzip.compress(json.dumps(bundle).encode()))
    (sw / "archive" / "broken.json.gz").write_bytes(b"not gzip")
    pieces = skillmine.shiftwork_pieces(root)
    assert [(p.id, p.prompt) for p in pieces] == [("myjob/A", "live")]


def test_worktrees_of_one_repo_share_the_repo_key(tmp_path: Path) -> None:
    main = _root(tmp_path)
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (main / ".git" / "worktrees" / "wt" / "commondir").write_text("../..\n", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n", encoding="utf-8")
    assert (
        skillmine.repo_key(wt)
        == skillmine.repo_key(main)
        == os.path.join(os.path.realpath(main), ".git")
    )
    assert skillmine.repo_key(tmp_path) == ""


def _p(prompt: str, tools: tuple[str, ...] = (), paths: frozenset[str] = frozenset()) -> Piece:
    return Piece(
        id="j/x", source="shiftwork", ts="t", repo="", prompt=prompt, tools=tools, paths=paths
    )


def test_df_filter_drops_a_term_in_more_than_half_the_pieces() -> None:
    pieces = [_p("common alpha"), _p("common beta"), _p("common gamma"), _p("beta delta")]
    df, n = doc_freq(pieces)
    assert n == 4 and df["common"] == 3 and df["beta"] == 2
    sig = signature(pieces[1], df, n)
    assert sig.keywords == frozenset({"beta"})  # 2 of 4 is not MORE than half


def test_keywords_top_ties_in_code_point_order() -> None:
    words = [f"w{i:02d}" for i in range(20)]
    prompt = " ".join(words + ["w19", "w18"])  # w18, w19 twice
    piece = _p(prompt)
    sig = signature(piece, Counter(), 100)
    assert len(sig.keywords) == skillmine.KEYWORDS_TOP == 12
    assert sig.keywords == frozenset(["w18", "w19"] + words[:10])


def test_ngrams_of_the_tool_sequence() -> None:
    sig = signature(_p("", tools=("Read", "Edit", "Bash", "Edit")), Counter(), 1)
    assert sig.ngrams == frozenset(
        {"Read>Edit", "Edit>Bash", "Bash>Edit", "Read>Edit>Bash", "Edit>Bash>Edit"}
    )
    assert signature(_p("", tools=("Read",)), Counter(), 1).ngrams == frozenset()


def _sig(k: set[str], g: set[str], p: set[str]) -> Signature:
    return Signature(frozenset(k), frozenset(g), frozenset(p))


def test_similarity_at_exactly_one_half_meets_and_one_less_does_not() -> None:
    # keywords 1/2 (w2), ngrams 2/3, paths 1/3: (1 + 2/3 + 1/3) / 4 = 1/2 exactly; a float
    # sum of the same terms is 0.49999999999999994.
    a = _sig({"k1", "k2"}, {"g1", "g2", "g3"}, {"p1", "p2"})
    b = _sig({"k1"}, {"g1", "g2"}, {"p2", "p3"})
    assert similarity(a, b) == (1, 2) and meets(similarity(a, b))
    c = _sig({"k1"}, {"g1"}, {"p2", "p3"})
    assert similarity(a, c) == (5, 12) and not meets(similarity(a, c))


def test_an_empty_ngram_set_is_not_a_mismatch() -> None:
    a = _sig({"k1", "k2"}, set(), {"p1"})
    b = _sig({"k1", "k2"}, set(), {"p1"})
    assert similarity(a, b) == (1, 1)
    c = _sig({"k1"}, set(), set())
    d = _sig({"k1", "k2"}, set(), set())
    assert similarity(c, d) == (1, 2) and meets(similarity(c, d))
    assert similarity(_sig(set(), set(), set()), _sig(set(), set(), set())) == (0, 1)
    assert not meets((0, 1))


@pytest.mark.parametrize(
    "name", ["KEYWORDS_TOP", "NGRAM_SIZES", "SIM_WEIGHTS", "SIM_MIN", "KEYWORD_DF_MAX"]
)
def test_plan_constants(name: str) -> None:
    expected = {
        "KEYWORDS_TOP": 12,
        "NGRAM_SIZES": (2, 3),
        "SIM_WEIGHTS": (("keywords", 2), ("ngrams", 1), ("paths", 1)),
        "SIM_MIN": (1, 2),
        "KEYWORD_DF_MAX": (1, 2),
    }
    assert getattr(skillmine, name) == expected[name]


# ------------------------------------------------------------------ clusters (Task 5)

NOW = "2026-10-27T00:00:00.000Z"
REPO_A = "/r/a/.git"


def _wp(
    pid: str,
    prompt: str,
    ok: bool | None = True,
    *,
    ts: str = "",
    source: str = "shiftwork",
    repo: str = REPO_A,
    tools: tuple[str, ...] = (),
    failure: str | None = None,
) -> Piece:
    return Piece(
        id=pid,
        source=source,
        ts=ts or pid,
        repo=repo,
        prompt=prompt,
        tools=tools,
        ok=ok,
        failure=failure,
    )


def _corpus(
    groups: list[tuple[str, int, int]], source: str = "shiftwork", fillers: int = 6
) -> list[Piece]:
    """`(word, successes, failures)` groups, each one cluster, plus unrelated filler pieces."""
    out: list[Piece] = []
    n = 0
    for word, ok, failed in groups:
        for i in range(ok + failed):
            n += 1
            out.append(
                _wp(
                    f"{word}/{i:02d}",
                    f"{word} lexer{word} crash{word}",
                    i < ok,
                    ts=f"2026-01-01T00:00:{n:02d}Z",
                    source=source,
                    failure=None if i < ok else f"{word} attempt {i} failed",
                )
            )
    for i in range(fillers):
        n += 1
        out.append(
            _wp(f"zz/{i:02d}", f"filler{i} odd{i}", ts=f"2026-01-01T00:00:{n:02d}Z", source=source)
        )
    return out


def _by_word(doc: dict) -> dict[str, dict]:
    return {c["evidence"][0]["id"].split("/")[0]: c for c in doc["clusters"]}


def test_shiftwork_bar_at_two_and_three() -> None:
    got = _by_word(skillmine.mine(_corpus([("alpha", 2, 0), ("bravo", 3, 0)]), None, NOW))
    assert not got["alpha"]["eligible"] and got["alpha"]["status"] == "new"
    assert got["bravo"]["eligible"] and got["bravo"]["status"] == "pending"
    assert got["bravo"]["bar"] == 3 and got["bravo"]["auto_bar"] == 6


def test_failed_members_are_pitfalls_and_do_not_count() -> None:
    got = _by_word(skillmine.mine(_corpus([("bravo", 3, 2)]), None, NOW))["bravo"]
    assert (got["successes"], got["members"], got["eligible"]) == (3, 5, True)
    assert got["pitfalls"] == [
        {"failure": "bravo attempt 3 failed", "id": "bravo/03"},
        {"failure": "bravo attempt 4 failed", "id": "bravo/04"},
    ]
    two = _by_word(skillmine.mine(_corpus([("bravo", 2, 3)]), None, NOW))["bravo"]
    assert (two["successes"], two["eligible"]) == (2, False)


def test_session_bar_at_four_and_five() -> None:
    got = _by_word(
        skillmine.mine(_corpus([("alpha", 4, 0), ("bravo", 5, 0)], "session", 10), None, NOW)
    )
    assert not got["alpha"]["eligible"] and got["bravo"]["eligible"]
    assert got["bravo"]["bar"] == 5 and not got["bravo"]["auto_eligible"]


def test_auto_bar_is_twice_the_bar() -> None:
    sw = _by_word(skillmine.mine(_corpus([("alpha", 5, 0), ("bravo", 6, 0)], fillers=8), None, NOW))
    assert not sw["alpha"]["auto_eligible"] and sw["bravo"]["auto_eligible"]
    se = _by_word(
        skillmine.mine(_corpus([("alpha", 9, 0), ("bravo", 10, 0)], "session", 4), None, NOW)
    )
    assert not se["alpha"]["auto_eligible"] and se["bravo"]["auto_eligible"]


def _rejected(doc: dict, word: str, at: int) -> dict:
    rec = dict(_by_word(doc)[word])
    rec["status"] = "rejected"
    rec["rejected_at"] = at
    return {**doc, "clusters": [rec]}


def test_a_rejected_cluster_waits_until_it_has_doubled() -> None:
    first = skillmine.mine(_corpus([("bravo", 3, 0)]), None, NOW)
    prev = _rejected(first, "bravo", 3)
    five = _by_word(skillmine.mine(_corpus([("bravo", 5, 0)], fillers=8), prev, NOW))["bravo"]
    assert five["status"] == "rejected" and five["rejected_at"] == 3
    six = _by_word(skillmine.mine(_corpus([("bravo", 6, 0)], fillers=8), prev, NOW))["bravo"]
    assert six["status"] == "pending" and six["rejected_at"] == 3
    assert six["id"] == five["id"] == first["clusters"][0]["id"]


def test_pending_cap_keeps_the_fourth_new() -> None:
    doc = skillmine.mine(
        _corpus([("alpha", 6, 0), ("bravo", 5, 0), ("charlie", 4, 0), ("delta", 3, 0)]), None, NOW
    )
    got = _by_word(doc)
    assert [got[w]["status"] for w in ("alpha", "bravo", "charlie", "delta")] == [
        "pending",
        "pending",
        "pending",
        "new",
    ]
    # One leaves `pending` (approved and drafted): the fourth is offered on the next run.
    prev = {
        **doc,
        "clusters": [
            {**c, "status": "drafted"} if c is got["alpha"] else c for c in doc["clusters"]
        ],
    }
    again = _by_word(
        skillmine.mine(
            _corpus([("alpha", 6, 0), ("bravo", 5, 0), ("charlie", 4, 0), ("delta", 3, 0)]),
            prev,
            NOW,
        )
    )
    assert [again[w]["status"] for w in ("alpha", "bravo", "charlie", "delta")] == [
        "drafted",
        "pending",
        "pending",
        "pending",
    ]


def test_level_from_the_repo_keys() -> None:
    one = [_wp(f"a/{i}", "alpha lexer crash", repo=REPO_A) for i in range(3)]
    fill = [_wp(f"z/{i}", f"filler{i}") for i in range(4)]
    got = skillmine.mine(one + fill, None, NOW)["clusters"][0]
    assert (got["level"], got["repos"], got["top"]) == ("project", [REPO_A], "/r/a")
    two = [
        _wp(f"a/{i}", "alpha lexer crash", repo=["/r/a/.git", "/r/b/.git"][i % 2]) for i in range(3)
    ]
    got = skillmine.mine(two + fill, None, NOW)["clusters"][0]
    assert (got["level"], got["repos"], got["top"]) == ("user", ["/r/a/.git", "/r/b/.git"], None)
    none = [_wp(f"a/{i}", "alpha lexer crash", repo="") for i in range(3)]
    got = skillmine.mine(none + fill, None, NOW)["clusters"][0]
    assert (got["level"], got["repos"]) == ("user", [])


def test_two_worktrees_of_one_repo_are_project_level(tmp_path: Path) -> None:
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (main / ".git" / "worktrees" / "wt" / "commondir").write_text("../..\n", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n", encoding="utf-8")
    for root, units in ((main, ["M1", "M2", "F1", "F2"]), (wt, ["W1", "F3", "F4"])):
        sw = root / ".shiftwork"
        sw.mkdir()
        (sw / "checkpoint-j.json").write_text(
            _ckpt(
                f"j{root.name}",
                [
                    (u, "fix the lexer crash" if u[0] != "F" else f"filler {u} odd{u}", "x.md")
                    for u in units
                ],
            ),
            encoding="utf-8",
        )
        (sw / "checkpoint-j.json.log.jsonl").write_text(
            "\n".join(_line(u, "done", f"2026-01-0{i + 1}T00:00:00Z") for i, u in enumerate(units)),
            encoding="utf-8",
        )
    pieces = skillmine.shiftwork_pieces(main) + skillmine.shiftwork_pieces(wt)
    got = [c for c in skillmine.mine(pieces, None, NOW)["clusters"] if c["successes"] == 3]
    assert len(got) == 1
    assert got[0]["level"] == "project"
    assert got[0]["top"] == os.path.realpath(main)


def test_identity_survives_the_leader_leaving() -> None:
    doc = skillmine.mine(_corpus([("bravo", 4, 0)]), None, NOW)
    old = doc["clusters"][0]
    later = [p for p in _corpus([("bravo", 4, 0)]) if p.id != "bravo/00"]
    got = skillmine.mine(later, doc, NOW)["clusters"][0]
    assert got["id"] == old["id"] != skillmine._sha16("bravo/01")


def test_match_previous_ties_go_to_the_lower_id() -> None:
    fill = [_wp(f"z/{i}", f"filler{i}") for i in range(3)]
    c = skillmine.cluster([_wp("a/1", "x y"), _wp("a/2", "x y"), *fill])[0]
    assert c.evidence == ("a/1", "a/2")
    recs = [
        {"id": "b", "source": "shiftwork", "evidence": [{"id": "a/1"}]},
        {"id": "a", "source": "shiftwork", "evidence": [{"id": "a/2"}]},
        {"id": "0", "source": "session", "evidence": [{"id": "a/1"}, {"id": "a/2"}]},
    ]
    assert skillmine.match_previous(c, recs)["id"] == "a"
    assert skillmine.match_previous(c, recs[2:]) is None


def test_steps_are_ngrams_in_half_the_successes_in_order() -> None:
    seq = ("Read", "Edit", "Bash")
    pieces = [
        _wp("s/1", "alpha lexer", source="session", tools=seq),
        _wp("s/2", "alpha lexer", source="session", tools=("Grep",) + seq),
        _wp("s/3", "alpha lexer", source="session", tools=("Read", "Edit")),
        _wp("s/4", "alpha lexer", source="session", tools=("Read", "Edit", "Write")),
        _wp("s/5", "alpha lexer", False, source="session", tools=("Read", "Edit", "Write")),
    ] + [_wp(f"z/{i}", f"filler{i}", source="session") for i in range(6)]
    c = [c for c in skillmine.cluster(pieces) if len(c.members) == 5][0]
    assert c.steps == ("Read>Edit", "Read>Edit>Bash", "Edit>Bash")


def test_leader_ties_go_to_the_older_cluster() -> None:
    a = _wp("1", "alpha bravo", tools=())
    b = _wp("2", "charlie delta", tools=())
    c = _wp("3", "alpha bravo charlie delta", tools=())
    fill = [_wp(f"z/{i}", f"filler{i}") for i in range(6)]
    got = skillmine.cluster([a, b, c, *fill])
    assert [m.id for m in got[0].members] == ["1", "3"]


def test_singletons_are_not_written_but_a_carried_status_is() -> None:
    doc = skillmine.mine([_wp("a/1", "alpha"), _wp("b/1", "bravo")], None, NOW)
    assert doc["clusters"] == []
    assert doc["miner"] == {"error": None, "ms": 0, "pieces": {"session": 0, "shiftwork": 2}}
    prev = {
        "version": 1,
        "clusters": [
            {
                "id": "x",
                "source": "shiftwork",
                "status": "rejected",
                "rejected_at": 3,
                "evidence": [{"id": "a/1"}],
            }
        ],
    }
    doc = skillmine.mine([_wp("a/1", "alpha"), _wp("b/1", "bravo")], prev, NOW)
    assert [(c["id"], c["status"]) for c in doc["clusters"]] == [("x", "rejected")]


def test_proposals_file_round_trip_and_refusal(tmp_path: Path) -> None:
    assert skillmine.read_proposals(tmp_path) is None
    doc = skillmine.mine(_corpus([("bravo", 3, 0)]), None, NOW)
    path = skillmine.write_proposals(tmp_path, doc)
    assert path == tmp_path / ".bantamkit" / "skill-proposals.json"
    assert path.read_bytes() == skillmine.proposals_bytes(doc)
    assert path.read_bytes().endswith(b"}\n")
    assert skillmine.read_proposals(tmp_path) == doc
    assert not list(path.parent.glob("*.tmp")) and not list(path.parent.glob("*.lock"))
    path.write_text('{"version": 2, "clusters": []}', encoding="utf-8")
    with pytest.raises(skillmine.ProposalsError, match="is not a version 1 proposals file"):
        skillmine.read_proposals(tmp_path)
    path.write_bytes(b"\xef\xbb\xbf{}")
    with pytest.raises(skillmine.ProposalsError, match="is not readable JSON"):
        skillmine.read_proposals(tmp_path)


def test_a_lone_surrogate_is_written_as_replacement_character() -> None:
    doc = skillmine.mine(
        [_wp("a\ud800", "alpha"), _wp("b", "alpha")]
        + [_wp(f"z{i}", f"filler{i}") for i in range(3)],
        None,
        NOW,
    )
    data = skillmine.proposals_bytes(doc)
    assert "a�".encode() in data
    assert doc["clusters"][0]["id"] == skillmine._sha16("a�")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SHIFTWORK_BAR", 3),
        ("SESSION_BAR", 5),
        ("AUTO_FACTOR", 2),
        ("PENDING_MAX", 3),
        ("REJECT_FACTOR", 2),
        ("STEP_SHARE", (1, 2)),
    ],
)
def test_task5_constants(name: str, value: object) -> None:
    assert getattr(skillmine, name) == value
