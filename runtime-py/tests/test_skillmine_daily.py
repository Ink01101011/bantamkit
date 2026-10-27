"""skillmine.daily (#206 Task 8): the miner in the Retention child, its status line.

Every home and repo is a tmp dir; nothing reaches the real `~/.bantamkit` or `~/.claude`. The
endpoint is a stub HTTP server on 127.0.0.1 in this process. Every fixture is synthetic.
`runtime-ts/test/skillmine-daily.test.mjs` mirrors this file.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import test_skillinstall as tsi

from bantamkit import skillfile as sf
from bantamkit import skillinstall as si
from bantamkit import skillmine as sm
from bantamkit.storage import retention

NOW = "2026-10-27T00:00:00.000Z"
DAY_S = 86_400
NAME = "fixing-lexer-crashes"
FILLERS = ["amber", "birch", "cedar", "delta", "ember", "fjord", "grove"]


def good_draft(name: str = NAME) -> str:
    return (
        f"---\nname: {name}\ndescription: Fixes lexer crashes. Use when the lexer crashes.\n---\n\n"
        "## When to use\n\nThe lexer crashes on input.\n\n## Steps\n\n1. Read the crash [j/U1].\n"
        "2. Fix the token table [j/U2].\n\n## Pitfalls\n\nNone.\n\n## Example\n\nx\n"
    )


def _age(p: Path, days: int) -> None:
    t = retention.parse_now(NOW) / 1000 - days * DAY_S
    os.utime(p, (t, t))


def _put(p: Path, text: str, days: int | None = None) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if days is not None:
        _age(p, days)


def bed(tmp_path: Path, *, trap: bool = True, units: int = 6) -> tuple[Path, Path]:
    """`(home, proj)`: a repo whose job `j` holds `units` done units of one kind (6 is twice
    the shiftwork bar) and seven unrelated ones; with `trap`, files the sweep would change."""
    home, proj = tmp_path / "home", tmp_path / "proj"
    (home / ".bantamkit").mkdir(parents=True)
    (proj / ".git").mkdir(parents=True)
    ids = [f"U{i + 1}" for i in range(units)] + [f"F{i + 1}" for i in range(len(FILLERS))]
    titles = ["fix the lexer crash"] * units + [f"{w} {w}notes" for w in FILLERS]
    ckpt = {
        "version": 1,
        "job": {"id": "j", "goal": "g", "done_definition": "d", "constraints": []},
        "plan": {
            "cursor": "U1",
            "units": [
                {
                    "id": u,
                    "title": t,
                    "brief_path": "x.md",
                    "status": "done",
                    "role": "implementer",
                    "depends_on": [],
                    "verify": "true",
                }
                for u, t in zip(ids, titles, strict=True)
            ],
        },
        "history": [],
    }
    sw = proj / ".shiftwork"
    _put(sw / "checkpoint-j.json", json.dumps(ckpt))
    ledger = "\n".join(
        json.dumps(
            {
                "unit": u,
                "role": "implementer",
                "status": "done",
                "ts": f"2026-10-0{1 + i % 9}T00:00:00Z",
            }
        )
        for i, u in enumerate(ids)
    )
    _put(sw / "checkpoint-j.json.log.jsonl", ledger + "\n")
    if trap:
        _put(home / ".bantamkit" / "hooks" / "ledger-old.json", '{"seen":{}}', 8)
        _put(
            home / ".bantamkit" / "usage" / "idle.jsonl",
            '{"ts":"2026-09-10T00:00:00Z","fact":"g","kind":"seed"}\n',
            31,
        )
    return home, proj


def snapshot(base: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for dirpath, dirs, files in os.walk(base):
        for n in dirs + files:
            p = Path(dirpath) / n
            rel = p.relative_to(base).as_posix()
            if p.is_dir() and not p.is_symlink():
                out[rel] = "dir"
            else:
                out[rel] = f"{hashlib.sha256(p.read_bytes()).hexdigest()} {p.lstat().st_mtime_ns}"
    return out


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


class Stub:
    """An OpenAI-compatible endpoint answering every request with `answer`; counts requests."""

    def __init__(self, answer: str) -> None:
        stub = self
        self.hits = 0

        class H(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - the stdlib's name
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                stub.hits += 1
                body = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": answer},
                                "finish_reason": "stop",
                            }
                        ]
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub() -> Iterator[Stub]:
    s = Stub(good_draft())
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _switches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BANTAMKIT_RETENTION", "off")
    monkeypatch.delenv("BANTAMKIT_SKILL_AUDIT", raising=False)
    monkeypatch.setenv(si.AUTO_ENV, "off")
    monkeypatch.delenv("BANTAMKIT_LLM_URL", raising=False)
    monkeypatch.delenv("BANTAMKIT_LLM_MODEL", raising=False)


def endpoint(monkeypatch: pytest.MonkeyPatch, stub: Stub) -> None:
    monkeypatch.setenv("BANTAMKIT_LLM_URL", stub.url)
    monkeypatch.setenv("BANTAMKIT_LLM_MODEL", "m")


def child(home: Path, proj: Path) -> int:
    return retention.child_main([str(proj), str(home)], now=NOW)


def bk(home: Path, name: str) -> Path:
    return home / ".bantamkit" / name


# ----------------------------------------------------------------------------- the child


def test_the_child_with_the_audit_on_writes_the_proposals_file(tmp_path: Path) -> None:
    home, proj = bed(tmp_path)
    assert child(home, proj) == 0
    doc = sm.read_proposals(home)
    assert doc is not None and doc["ts"] == NOW and doc["miner"]["error"] is None
    assert doc["miner"]["pieces"] == {"session": 0, "shiftwork": 13}
    [c] = [c for c in doc["clusters"] if c["successes"] == 6]
    assert (c["auto_eligible"], c["status"], c["level"]) == (True, "pending", "project")
    assert bk(home, sm.CACHE_NAME).is_file()
    assert not bk(home, "skill-drafts.jsonl").exists()  # no endpoint: no draft, no log line


def test_the_audit_off_writes_no_proposals_file(tmp_path: Path, monkeypatch) -> None:
    home, proj = bed(tmp_path)
    monkeypatch.setenv("BANTAMKIT_SKILL_AUDIT", "off")
    sm.daily(home, str(proj), NOW)
    monkeypatch.delenv("BANTAMKIT_RETENTION")
    assert child(home, proj) == 0
    assert retention.state_path(home).is_file()  # the child ran: the sweep claimed the day
    assert not bk(home, sm.PROPOSALS_NAME).exists()
    assert not bk(home, sm.CACHE_NAME).exists()


def test_j69_6_retention_off_changes_only_the_listed_files(
    tmp_path: Path, monkeypatch, stub: Stub
) -> None:
    """THE MOST IMPORTANT CASE: a full run (mine, draft, install, a probation removal) with the
    sweep off touches the claim, the audit record, the miner's files and skill dirs, nothing
    else — over a trap the sweep would change."""
    home, proj = bed(tmp_path)
    old = tsi.record("old-skill", ok_draft=False)
    si.install(old, tsi.draft("old-skill"), None, home, tsi.stamp_at(-31), auto=True)
    endpoint(monkeypatch, stub)
    monkeypatch.setenv(si.AUTO_ENV, "on")
    before = snapshot(tmp_path)
    assert child(home, proj) == 0
    got = changed(before, snapshot(tmp_path))
    backups = [p for p in got if p.startswith("home/.bantamkit/skill-backups/")]
    assert [p for p in got if p not in backups] == [
        "home/.bantamkit/retention.json",
        "home/.bantamkit/skill-audit.json",
        "home/.bantamkit/skill-drafts.jsonl",
        "home/.bantamkit/skill-miner-cache.json",
        "home/.bantamkit/skill-proposals.json",
        "home/.bantamkit/skills-state.json",
        "home/.bantamkit/skills/old-skill",
        "home/.bantamkit/skills/old-skill/SKILL.md",
        "home/.bantamkit/skills/old-skill/references",
        "home/.bantamkit/skills/old-skill/references/evidence.md",
        "proj/.bantamkit",
        "proj/.bantamkit/skills",
        f"proj/.bantamkit/skills/{NAME}",
        f"proj/.bantamkit/skills/{NAME}/SKILL.md",
        f"proj/.bantamkit/skills/{NAME}/references",
        f"proj/.bantamkit/skills/{NAME}/references/evidence.md",
    ]
    assert any("old-skill" in p for p in backups)
    assert stub.hits == 1
    state = sf.read_state(home)
    assert sorted(state["skills"]) == [NAME]
    assert [e["event"] for e in state["events"]] == [
        f"installed skill {NAME}",
        "removed unused skill old-skill",
    ]
    doc = sm.read_proposals(home)
    [c] = [c for c in doc["clusters"] if c["successes"] == 6]
    assert c["status"] == "installed" and c["draft"]["drafter"] == "endpoint m"
    assert sm.status_line(home).startswith("skills: mined 2026-10-27T00:00:00.000Z in ")
    assert sm.status_line(home).endswith(
        " ms; 0 pending, 1 of 5 auto-installed live, 0 promoted; drafter endpoint m"
    )


def test_with_auto_off_the_child_neither_drafts_nor_installs(
    tmp_path: Path, monkeypatch, stub: Stub
) -> None:
    home, proj = bed(tmp_path)
    endpoint(monkeypatch, stub)
    child(home, proj)
    assert stub.hits == 0
    assert not (proj / ".bantamkit").exists()
    assert sf.read_state(home)["skills"] == {}


def test_a_miner_error_is_recorded_and_no_later_step_runs(tmp_path: Path, monkeypatch) -> None:
    home, proj = bed(tmp_path)
    ready = tsi.record("ready-skill")  # auto-ready, with a passing draft
    _put(bk(home, sm.PROPOSALS_NAME), json.dumps({"version": 1, "clusters": [ready], "ts": "t"}))
    bk(home, sm.CACHE_NAME).mkdir()  # the cache cannot be saved
    monkeypatch.setenv(si.AUTO_ENV, "on")
    child(home, proj)
    doc = sm.read_proposals(home)
    assert doc["miner"]["error"] == "OSError" and doc["ts"] == NOW
    assert doc["clusters"] == [ready]  # kept as they were
    assert not (home / ".bantamkit" / "skills").exists()  # auto_step did not run
    assert sm.status_line(home) == f"skills: miner failed at {NOW}: OSError; drafter host agent"


def test_an_unreadable_proposals_file_is_left_alone(tmp_path: Path) -> None:
    home, proj = bed(tmp_path)
    _put(bk(home, sm.PROPOSALS_NAME), "{not json")
    sm.daily(home, str(proj), NOW)
    assert bk(home, sm.PROPOSALS_NAME).read_text(encoding="utf-8") == "{not json"
    assert not bk(home, sm.CACHE_NAME).exists()
    assert sm.status_line(home) == (
        "skills: miner refused: skill-proposals.json is not readable JSON; drafter host agent"
    )


# ------------------------------------------------------------------------- the status line


def test_status_never_ran_and_off(tmp_path: Path, monkeypatch) -> None:
    assert sm.status_line(tmp_path) == "skills: miner never ran; drafter host agent"
    monkeypatch.setenv("BANTAMKIT_SKILL_AUDIT", "OFF")
    assert sm.status_line(tmp_path) == "skills: off; miner never ran; drafter host agent"
    monkeypatch.setenv("BANTAMKIT_LLM_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("BANTAMKIT_LLM_MODEL", "qwen")
    assert sm.status_line(tmp_path, True) == "skills: off; miner never ran; drafter sampling"
    assert sm.status_line(tmp_path) == "skills: off; miner never ran; drafter endpoint qwen"


def test_status_mined_counts_pending_live_autos_and_promoted(tmp_path: Path) -> None:
    clusters = [{"status": s} for s in ("pending", "pending", "new", "rejected", "pending")]
    doc = {"version": 1, "clusters": clusters, "ts": NOW, "miner": {"error": None, "ms": 42}}
    _put(bk(tmp_path, sm.PROPOSALS_NAME), json.dumps(doc))
    state = {
        "version": 1,
        "skills": {
            "a": {"auto": True},
            "b": {"auto": True, "promoted": {"mode": "symlink"}},
            "c": {"auto": False, "promoted": {"mode": "copy"}},
            "d": {"auto": False, "promoted": None},
        },
    }
    _put(bk(tmp_path, sf.STATE_NAME), json.dumps(state))
    assert sm.status_line(tmp_path) == (
        f"skills: mined {NOW} in 42 ms; 3 pending, 2 of 5 auto-installed live, 2 promoted; "
        "drafter host agent"
    )
    _put(bk(tmp_path, sf.STATE_NAME), "[]")
    assert sm.status_line(tmp_path) == (
        f"skills: mined {NOW} in 42 ms; 3 pending, ? of 5 auto-installed live, ? promoted; "
        "drafter host agent"
    )


def test_status_wrong_version_is_refused(tmp_path: Path) -> None:
    _put(bk(tmp_path, sm.PROPOSALS_NAME), '{"version": 2, "clusters": []}')
    assert sm.status_line(tmp_path) == (
        "skills: miner refused: skill-proposals.json is not a version 1 proposals file; "
        "drafter host agent"
    )


# ------------------------------------------------------------------------------ the helpers


def test_draft_candidate_takes_the_most_successes_then_the_oldest() -> None:
    a = tsi.record("a", 7, ok_draft=False, ts="2026-02-01T00:00:00Z")
    b = tsi.record("b", 7, ok_draft=False, ts="2026-01-01T00:00:00Z")
    c = tsi.record("c", 8)  # already has a passing draft
    d = tsi.record("d", 6, ok_draft=False, status="installed")
    e = tsi.record("e", 5, ok_draft=False)  # below twice the bar
    got = sm.draft_candidate({"clusters": [a, b, c, d, e]})
    assert got is b
    assert sm.draft_candidate({"clusters": [c, d, e]}) is None


def test_skill_uses_counts_uses_at_or_after_the_install(tmp_path: Path) -> None:
    at = "2026-10-01T00:00:00.000Z"
    state = {"skills": {"s": {"auto": True, "at": at}, "t": {"auto": False, "at": at}}}
    rows = [
        {"ts": "2026-09-30T23:59:59Z", "fact": "s", "kind": "recall_hit"},
        {"ts": "2026-10-01T00:00:00Z", "fact": "s", "kind": "recall_hit"},
        {"ts": "2026-10-02T00:00:00Z", "fact": "s", "kind": "body_read"},
        {"ts": "2026-10-03T00:00:00Z", "fact": "s", "kind": "seed"},
        {
            "ts": "2026-10-03T00:00:00Z",
            "fact": "s",
            "kind": "folded",
            "weight": 1.0,
            "last": "2026-10-05T00:00:00Z",
        },
        {"ts": "2026-10-03T00:00:00Z", "fact": "t", "kind": "recall_hit"},
    ]
    _put(
        tmp_path / ".bantamkit" / "usage" / "abc.jsonl", "".join(json.dumps(r) + "\n" for r in rows)
    )
    _put(tmp_path / ".bantamkit" / "usage" / "notes.txt", json.dumps(rows[1]) + "\n")
    assert sm.skill_uses(tmp_path, state) == {"s": 3}
    assert sm.skill_uses(tmp_path, {"skills": {}}) == {}


def test_error_name_is_oserror_for_any_filesystem_error() -> None:
    assert sm.error_name(IsADirectoryError(21, "x")) == "OSError"
    assert sm.error_name(PermissionError(13, "x")) == "OSError"
    assert sm.error_name(sm.ProposalsError("x")) == "ProposalsError"
    assert sm.error_name(KeyError("x")) == "KeyError"
