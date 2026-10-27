"""Self-improvement, part 1 (#206 Task 10a): versions, the counts, the 5-use judge, rollback,
the edited guard, the gate's own-skill variant and the daily wiring.

Every home is a tmp dir; nothing reaches the real `~/.bantamkit`. Every fixture is synthetic.
`runtime-ts/test/skillimprove.test.mjs` mirrors this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bantamkit import skilldraft as sd
from bantamkit import skillfile as sf
from bantamkit import skillinstall as si
from bantamkit import skillmine as sm

NOW = "2026-10-27T12:00:00.000Z"
LATER = "2026-10-28T12:00:00.000Z"


def draft(name: str, words: str = "Does {n}. Use when {n} is asked.", step: str = "Do it") -> str:
    return (
        f"---\nname: {name}\ndescription: {words.format(n=name)}\n---\n\n"
        f"## When to use\n\nWhen asked.\n\n## Steps\n\n1. {step} [job1/U1].\n\n"
        "## Pitfalls\n\nNone.\n\n## Example\n\nx\n"
    )


def cluster(name: str) -> dict:
    return {
        "evidence": [{"id": "job1/U1", "ok": True, "ts": "2026-01-01T00:00:00Z"}],
        "id": f"c-{name}",
        "keywords": ["k1"],
        "level": "user",
        "members": 3,
        "source": "shiftwork",
        "status": "pending",
        "successes": 3,
        "top": None,
    }


def installed(home: Path, name: str = "sk-one", auto: bool = False) -> Path:
    si.install(cluster(name), draft(name), None, home, NOW, auto)
    return sf.skills_root(home) / name


def set_stats(home: Path, name: str, version: str, stats: dict) -> None:
    def change(state: dict) -> None:
        state["skills"][name]["versions"].setdefault(version, {}).update(stats)

    sf.update_state(home, change)


def v2(home: Path, name: str = "sk-one") -> Path:
    d = installed(home, name)
    si.new_version(name, draft(name, step="Do it better"), home, NOW, "auto")
    return d


def test_constants():
    assert (si.JUDGE_USES, si.VERDICT_KEPT, si.VERDICT_ROLLED_BACK, si.HISTORY_DIR) == (
        5,
        "kept",
        "rolled back",
        "references/history",
    )


# ------------------------------------------------------------------------- new_version


def test_new_version_keeps_the_old_one_in_history(tmp_path):
    d = installed(tmp_path)
    v1 = (d / "SKILL.md").read_bytes()
    said = si.new_version("sk-one", draft("sk-one", step="Do it better"), tmp_path, NOW, "auto")
    assert said == "updated skill sk-one to v2"
    assert (d / "references/history/v1.md").read_bytes() == v1
    assert (d / "references/evidence.md").is_file()
    text = (d / "SKILL.md").read_text(encoding="utf-8")
    doc = sf.parse_skill(text)
    assert doc.metadata["bantamkit-version"] == "2"
    assert doc.metadata["bantamkit-generated-by"] == "bantamkit"
    assert doc.metadata["bantamkit-cluster"] == "c-sk-one"
    assert "Do it better" in doc.body
    assert not sf.is_edited(text)
    e = sf.read_state(tmp_path)["skills"]["sk-one"]
    assert e["version"] == 2
    assert e["sha256"] == sf.canonical_hash(text)
    assert e["counted_to"] == NOW
    assert e["versions"]["2"] == {
        "at": NOW,
        "false_fires": 0,
        "from": 1,
        "injects": 0,
        "kind": "auto",
        "successes": 0,
        "uses": 0,
    }
    assert e["versions"]["1"] == {"false_fires": 0, "injects": 0, "successes": 0, "uses": 0}


def test_new_version_refusals(tmp_path):
    d = installed(tmp_path)
    with pytest.raises(si.InstallError, match="^kind must be auto or approved$"):
        si.new_version("sk-one", draft("sk-one"), tmp_path, NOW, "manual")
    with pytest.raises(si.InstallError, match="^no skill named 'nope' is installed$"):
        si.new_version("nope", draft("nope"), tmp_path, NOW, "auto")
    with pytest.raises(si.InstallError, match="^the new version is named 'sk-two', not 'sk-one'$"):
        si.new_version("sk-one", draft("sk-two"), tmp_path, NOW, "auto")
    with pytest.raises(si.InstallError, match="^## Steps is missing or empty$"):
        si.new_version(
            "sk-one", draft("sk-one").replace("## Steps", "## Stops"), tmp_path, NOW, "auto"
        )
    assert not (d / "references/history").exists()


def test_an_edited_skill_is_never_versioned(tmp_path):
    d = installed(tmp_path)
    p = d / "SKILL.md"
    p.write_bytes(p.read_bytes() + b"my own line\n")
    before = p.read_bytes()
    with pytest.raises(
        si.InstallError, match="^sk-one was edited by hand; it only receives proposed changes$"
    ):
        si.new_version("sk-one", draft("sk-one", step="Do it better"), tmp_path, NOW, "auto")
    assert p.read_bytes() == before
    assert sf.read_state(tmp_path)["skills"]["sk-one"]["version"] == 1
    assert si.edited_by_hand(sf.read_state(tmp_path)["skills"]["sk-one"]) is True


def test_a_failed_swap_leaves_the_live_version(tmp_path, monkeypatch):
    d = installed(tmp_path)
    v1 = (d / "SKILL.md").read_bytes()
    before = sf.state_bytes(sf.read_state(tmp_path))
    real = sf._rename
    calls = [0]

    def rename(src, dst):
        calls[0] += 1
        if calls[0] == 3:  # 1 backup in, 2 live aside, 3 the new dir in
            raise OSError("injected")
        real(src, dst)

    monkeypatch.setattr(sf, "_rename", rename)
    with pytest.raises(OSError):
        si.new_version("sk-one", draft("sk-one", step="Do it better"), tmp_path, NOW, "auto")
    assert (d / "SKILL.md").read_bytes() == v1
    assert not (d / "references/history").exists()
    assert sf.state_bytes(sf.read_state(tmp_path)) == before
    assert sorted(p.name for p in d.parent.iterdir()) == ["sk-one"]


def test_the_next_number_skips_a_rolled_back_one(tmp_path):
    d = v2(tmp_path)
    set_stats(tmp_path, "sk-one", "1", {"successes": 4, "uses": 5})
    set_stats(tmp_path, "sk-one", "2", {"successes": 1, "uses": 5})
    state = sf.read_state(tmp_path)
    assert si.judge_step(state, tmp_path, NOW) == ["rolled back sk-one to v1"]
    said = si.new_version(
        "sk-one", draft("sk-one", step="Do it a third way"), tmp_path, LATER, "approved"
    )
    assert said == "updated skill sk-one to v3"
    e = sf.read_state(tmp_path)["skills"]["sk-one"]
    assert (e["version"], e["versions"]["3"]["from"], e["versions"]["3"]["kind"]) == (
        3,
        1,
        "approved",
    )
    assert sorted(p.name for p in (d / "references/history").iterdir()) == ["v1.md", "v2.md"]


# -------------------------------------------------------------------------- stats_step


def sources(name: str) -> dict:
    return {
        "injects": [
            {"names": [name], "session": "aaaaaaaa-1", "ts": "2026-10-27T12:00:01.000Z"},
            {"names": [name, "other"], "session": "bbbbbbbb-2", "ts": "2026-10-27T12:00:02.000Z"},
            {"names": [name], "session": "cccccccc-3", "ts": "2026-10-27T12:00:03.000Z"},
            {"names": ["other"], "session": "aaaaaaaa-1", "ts": "2026-10-27T12:00:04.000Z"},
            {"names": [name], "session": "", "ts": "2026-10-27T12:00:05.000Z"},
            {"names": [name], "session": "dddddddd-4", "ts": "2026-10-26T12:00:00.000Z"},
            {"names": [name], "session": "eeeeeeee-5", "ts": "2026-10-29T12:00:00.000Z"},
        ],
        "turns": [
            {"id": "saaaaaaaa#1", "ok": True, "ts": "2026-10-27T12:00:00.000Z"},
            {"id": "sbbbbbbbb#1", "ok": True, "ts": "2026-10-27T11:00:00.000Z"},
            {"id": "sbbbbbbbb#2", "ok": False, "ts": "2026-10-27T12:00:00.000Z"},
        ],
        "uses": [
            {"fact": name, "session": "aaaaaaaa-1", "ts": "2026-10-27T12:00:10.000Z"},
            {"fact": name, "session": "bbbbbbbb-2", "ts": "2026-10-27T12:00:10.000Z"},
            {"fact": name, "session": "zzzzzzzz-9", "ts": "2026-10-27T12:00:10.000Z"},
            {"fact": "other", "session": "cccccccc-3", "ts": "2026-10-27T12:00:10.000Z"},
            {"fact": name, "session": "aaaaaaaa-1", "ts": "2026-10-26T00:00:00.000Z"},
        ],
    }


def test_stats_count_once_into_the_live_version(tmp_path):
    installed(tmp_path)
    state = sf.read_state(tmp_path)
    si.stats_step(state, sources("sk-one"), tmp_path, LATER)
    e = state["skills"]["sk-one"]
    # uses: a, b, z (the 10-26 one is before the install); successes: a (its turn ok), not b
    # (its latest turn failed), not z (no turn); injects: a, b, c (no session, too early, too
    # late are out); false fires: c (never used it)
    assert e["versions"]["1"] == {"false_fires": 1, "injects": 3, "successes": 1, "uses": 3}
    assert e["counted_to"] == LATER
    si.stats_step(state, sources("sk-one"), tmp_path, LATER)
    assert state["skills"]["sk-one"]["versions"]["1"]["uses"] == 3
    assert sf.read_state(tmp_path) == state


def test_stats_after_a_new_version_go_to_it_and_freeze_the_old(tmp_path):
    v2(tmp_path)
    state = sf.read_state(tmp_path)
    si.stats_step(state, sources("sk-one"), tmp_path, LATER)
    e = state["skills"]["sk-one"]
    assert e["versions"]["1"] == {"false_fires": 0, "injects": 0, "successes": 0, "uses": 0}
    # counted after the new version's watermark (NOW), strictly
    assert e["versions"]["2"]["uses"] == 3
    assert e["versions"]["2"]["injects"] == 3


# ------------------------------------------------------------------------- judge_step


@pytest.mark.parametrize(
    ("v1", "v2s", "verdict"),
    [
        ({"successes": 4, "uses": 5}, {"successes": 3, "uses": 5}, "rolled back"),
        ({"successes": 4, "uses": 5}, {"successes": 4, "uses": 5}, "kept"),
        ({"successes": 4, "uses": 5}, {"successes": 8, "uses": 10}, "kept"),
        ({"successes": 4, "uses": 5}, {"successes": 7, "uses": 9}, "rolled back"),
        (
            {"false_fires": 2, "injects": 5, "uses": 5},
            {"false_fires": 3, "injects": 5, "uses": 5},
            "rolled back",
        ),
        (
            {"false_fires": 2, "injects": 5, "uses": 5},
            {"false_fires": 2, "injects": 5, "uses": 5},
            "kept",
        ),
        ({"injects": 0, "uses": 5}, {"false_fires": 1, "injects": 1, "uses": 5}, "rolled back"),
        ({"false_fires": 1, "injects": 1, "uses": 5}, {"injects": 0, "uses": 5}, "kept"),
        ({"uses": 0}, {"successes": 0, "uses": 5}, "kept"),
    ],
)
def test_judge_rates(tmp_path, v1, v2s, verdict):
    v2(tmp_path)
    set_stats(tmp_path, "sk-one", "1", v1)
    set_stats(tmp_path, "sk-one", "2", v2s)
    state = sf.read_state(tmp_path)
    events = si.judge_step(state, tmp_path, NOW)
    assert state["skills"]["sk-one"]["versions"]["2"]["verdict"] == verdict
    assert events == (["rolled back sk-one to v1"] if verdict == "rolled back" else [])


def test_four_uses_are_never_judged_five_are(tmp_path):
    v2(tmp_path)
    set_stats(tmp_path, "sk-one", "1", {"successes": 4, "uses": 5})
    set_stats(tmp_path, "sk-one", "2", {"successes": 0, "uses": 4})
    state = sf.read_state(tmp_path)
    assert si.judge_step(state, tmp_path, NOW) == []
    assert "verdict" not in state["skills"]["sk-one"]["versions"]["2"]
    set_stats(tmp_path, "sk-one", "2", {"uses": 5})
    state = sf.read_state(tmp_path)
    assert si.judge_step(state, tmp_path, NOW) == ["rolled back sk-one to v1"]


def test_rollback_restores_v1_bytes_and_keeps_v2_in_history(tmp_path):
    d = installed(tmp_path)
    v1 = (d / "SKILL.md").read_bytes()
    si.new_version("sk-one", draft("sk-one", step="Do it better"), tmp_path, NOW, "auto")
    v2_bytes = (d / "SKILL.md").read_bytes()
    set_stats(tmp_path, "sk-one", "1", {"successes": 4, "uses": 5})
    set_stats(tmp_path, "sk-one", "2", {"successes": 3, "uses": 5})
    state = sf.read_state(tmp_path)
    assert si.judge_step(state, tmp_path, LATER) == ["rolled back sk-one to v1"]
    assert (d / "SKILL.md").read_bytes() == v1
    assert (d / "references/history/v2.md").read_bytes() == v2_bytes
    assert (d / "references/history/v1.md").read_bytes() == v1
    e = sf.read_state(tmp_path)["skills"]["sk-one"]
    assert (e["version"], e["rolled_back"], e["counted_to"]) == (1, 2, LATER)
    assert e["sha256"] == sf.canonical_hash(v1.decode("utf-8"))
    assert si.edited_by_hand(e) is False
    # judged once: the next run leaves it
    assert si.judge_step(sf.read_state(tmp_path), tmp_path, LATER) == []


def test_an_edited_skill_is_never_judged(tmp_path):
    d = v2(tmp_path)
    set_stats(tmp_path, "sk-one", "1", {"successes": 4, "uses": 5})
    set_stats(tmp_path, "sk-one", "2", {"successes": 0, "uses": 9})
    p = d / "SKILL.md"
    p.write_bytes(p.read_bytes() + b"mine\n")
    before = sf.state_bytes(sf.read_state(tmp_path))
    edited = p.read_bytes()
    state = sf.read_state(tmp_path)
    assert si.judge_step(state, tmp_path, NOW) == []
    assert p.read_bytes() == edited
    assert sf.state_bytes(sf.read_state(tmp_path)) == before


def test_a_failed_rollback_leaves_v2_intact_and_unjudged(tmp_path, monkeypatch):
    d = v2(tmp_path)
    set_stats(tmp_path, "sk-one", "1", {"successes": 4, "uses": 5})
    set_stats(tmp_path, "sk-one", "2", {"successes": 3, "uses": 5})
    tree = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    real = sf._rename
    calls = [0]

    def rename(src, dst):
        calls[0] += 1
        if calls[0] == 3:
            raise OSError("injected")
        real(src, dst)

    monkeypatch.setattr(sf, "_rename", rename)
    state = sf.read_state(tmp_path)
    assert si.judge_step(state, tmp_path, NOW) == []
    assert {p: p.read_bytes() for p in d.rglob("*") if p.is_file()} == tree
    assert "verdict" not in sf.read_state(tmp_path)["skills"]["sk-one"]["versions"]["2"]


# ------------------------------------------------------------------------------ the gate


def test_the_gate_lets_a_skill_be_improved_only_as_itself(tmp_path):
    words = 'Does {n}. Use when asked to "ship the thing".'
    si.install(cluster("sk-one"), draft("sk-one", words=words), None, tmp_path, NOW, False)
    d = sf.skills_root(tmp_path) / "sk-one"
    b = sd.bundle(cluster("sk-one"))
    text = draft("sk-one", words=words, step="Do it better")
    plain = sd.gate(text, b, tmp_path, None)
    assert not plain.ok
    assert any("already exists at" in r for r in plain.reasons)
    assert any("is shared with sk-one" in r for r in plain.reasons)
    assert sd.gate(text, b, tmp_path, None, own=d).reasons == []
    # another skill still collides and shares
    si.install(cluster("sk-two"), draft("sk-two", words=words), None, tmp_path, NOW, False)
    got = sd.gate(text, b, tmp_path, None, own=d)
    assert any("is shared with sk-two" in r for r in got.reasons)


# ------------------------------------------------------------------------------ daily


def _jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_daily_counts_promotes_and_judges(tmp_path, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_AUDIT", "on")
    monkeypatch.setenv("BANTAMKIT_SKILL_AUTO", "off")
    (tmp_path / ".claude").mkdir()
    d = installed(tmp_path)
    set_stats(tmp_path, "sk-one", "1", {"successes": 4, "uses": 5})
    si.new_version("sk-one", draft("sk-one", step="Do it better"), tmp_path, NOW, "auto")
    set_stats(tmp_path, "sk-one", "2", {"successes": 0, "uses": 4})
    usage = [{"fact": "sk-one", "kind": "recall_hit", "ts": "2026-10-27T13:00:00Z"}] * 3
    _jsonl(tmp_path / ".bantamkit/usage/store.jsonl", usage)
    touch = [
        {
            "ts": "2026-10-27T13:00:00Z",
            "session": "s-1",
            "seq": 1,
            "op": "use",
            "fact": "sk-one",
            "kind": "recall_hit",
        },
        {
            "ts": "2026-10-27T13:00:00Z",
            "session": "s-1",
            "seq": 2,
            "op": "use",
            "fact": "sk-one",
            "kind": "save",
        },
    ]
    _jsonl(tmp_path / ".bantamkit/touch/repo.jsonl", touch)
    hooks = [
        {
            "ts": "2026-10-27T13:00:00.000Z",
            "event": "UserPromptSubmit",
            "action": "inject",
            "session": "s-2",
            "injected": [{"name": "sk-one"}],
        },
        {
            "ts": "2026-10-27T13:00:00.000Z",
            "event": "UserPromptSubmit",
            "action": "skip",
            "session": "s-2",
            "injected": [{"name": "sk-one"}],
        },
    ]
    _jsonl(tmp_path / ".bantamkit/hooks/hook-log.jsonl", hooks)
    sm.daily(tmp_path, None, LATER)
    state = sf.read_state(tmp_path)
    e = state["skills"]["sk-one"]
    assert e["versions"]["2"] == {
        "at": NOW, "false_fires": 1, "from": 1, "injects": 1, "kind": "auto",
        "successes": 0, "uses": 5, "verdict": "rolled back",
    }  # fmt: skip
    assert e["version"] == 1
    assert e["promoted"]["mode"] == "symlink"
    assert [x["event"] for x in state["events"]] == [
        "promoted skill sk-one",
        "rolled back sk-one to v1",
    ]
    assert (tmp_path / ".claude/skills/sk-one").is_symlink()
    assert (d / "references/history/v2.md").is_file()
