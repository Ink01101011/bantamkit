"""skillpropose (#206 Task 11): the `skill_propose` prompt, server-side sampling and the skills
SessionStart line.

Every home is a tmp dir; nothing reaches the real `~/.bantamkit`. Every LLM is a stub: the
sampling client is the test's callback, and the "endpoint" is a local HTTP server that counts
the requests it is sent. `runtime-ts/test/skillpropose.test.mjs` mirrors this file;
`tools/conformance/suites/skill-propose.mjs` compares the two runtimes.
"""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import anyio
import pytest
from test_skillinstall import NOW, draft, record
from test_skillmine import _by_word, _corpus

from bantamkit import skillfile as sf
from bantamkit import skillmine
from bantamkit import skillpropose as sp
from bantamkit.skilldraft import DRAFT_SYSTEM

C = sp.COMMAND


def _home(tmp_path: Path, claude: bool = True) -> Path:
    home = tmp_path / "home"
    (home / ".bantamkit").mkdir(parents=True)
    if claude:
        (home / ".claude").mkdir()
    return home


def _write(home: Path, *clusters: dict) -> None:
    skillmine.write_proposals(
        home,
        {
            "clusters": list(clusters),
            "miner": {"error": None, "ms": 0, "pieces": {"session": 0, "shiftwork": 6}},
            "ts": NOW,
            "version": 1,
        },
    )


def _doc(home: Path) -> dict:
    doc = skillmine.read_proposals(home)
    assert doc is not None
    return doc


def _render(home: Path, action=None, target=None, level=None, sampler=None) -> str:
    cwd = home.parent / "cwd"
    cwd.mkdir(exist_ok=True)
    return sp.render(action, target, level, home, str(cwd), NOW, sampler)


# ------------------------------------------------------------------------------ the list


def test_an_empty_home_is_the_fixed_text(tmp_path):
    assert _render(_home(tmp_path)) == sp.EMPTY


def test_list_shows_at_most_three_pending_and_never_a_rejected_one(tmp_path):
    home = _home(tmp_path)
    _write(
        home,
        record("p-a", ok_draft=False),
        record("p-b", ok_draft=False),
        record("p-c", ok_draft=False),
        record("p-d", ok_draft=False),
        record("p-e", status="rejected", ok_draft=False),
    )
    text = _render(home, "list")
    assert "Pending (3 of at most 3):" in text
    assert all(f"- c-{n}:" in text for n in ("p-a", "p-b", "p-c"))
    assert "c-p-d" not in text and "c-p-e" not in text
    assert f"approve: {C} approve c-p-a" in text
    assert "No skill is installed." in text


def test_reject_then_a_mine_below_double_is_not_listed(tmp_path):
    home = _home(tmp_path)
    first = skillmine.mine(_corpus([("bravo", 3, 0)]), None, NOW)
    skillmine.write_proposals(home, first)
    cid = first["clusters"][0]["id"]
    assert _render(home, "reject", cid) == (
        f"rejected proposal {cid}; it is offered again once it has 6 successes"
    )
    again = skillmine.mine(_corpus([("bravo", 5, 0)], fillers=8), _doc(home), NOW)
    assert _by_word(again)["bravo"]["status"] == "rejected"
    skillmine.write_proposals(home, again)
    assert cid not in _render(home)


# ----------------------------------------------------------------------------- approving


def test_approve_with_a_stored_draft_installs_it_off_probation(tmp_path):
    home = _home(tmp_path)
    _write(home, record("fixing-a"))
    text = _render(home, "approve", "c-fixing-a")
    path = sf.skills_root(home) / "fixing-a"
    assert text == f"installed skill fixing-a at {path} (user level).\nundo: {C} undo fixing-a"
    entry = sf.read_state(home)["skills"]["fixing-a"]
    assert entry["auto"] is False and "probation_until" not in entry
    assert _doc(home)["clusters"][0]["status"] == "installed"
    assert _render(home, "approve", "c-fixing-a") == "proposal c-fixing-a is already installed"


class _Endpoint:
    """A local OpenAI-compatible stub that counts the requests it is sent."""

    def __init__(self) -> None:
        self.hits = 0
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                outer.hits += 1
                self.send_response(500)
                self.end_headers()

            def log_message(self, *a) -> None:
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def close(self) -> None:
        self.server.shutdown()


@pytest.fixture
def endpoint(monkeypatch):
    e = _Endpoint()
    monkeypatch.setenv("BANTAMKIT_LLM_URL", e.url)
    monkeypatch.setenv("BANTAMKIT_LLM_MODEL", "stub")
    yield e
    e.close()


def test_approve_with_no_draft_drafts_through_sampling_and_never_hits_the_endpoint(
    tmp_path, endpoint
):
    home = _home(tmp_path)
    _write(home, record("fixing-a", ok_draft=False))
    asked = []

    def sampler(system: str, user: str) -> str:
        asked.append((system, user))
        return draft("fixing-a")

    text = _render(home, "approve", "c-fixing-a", sampler=sampler)
    assert text.startswith("installed skill fixing-a at ")
    assert len(asked) == 1 and asked[0][0] == DRAFT_SYSTEM
    assert endpoint.hits == 0
    assert _doc(home)["clusters"][0]["draft"]["drafter"] == "sampling"


def test_a_sampling_draft_that_fails_the_gate_does_not_fall_through(tmp_path, endpoint):
    home = _home(tmp_path)
    _write(home, record("fixing-a", ok_draft=False))
    bad = draft("fixing-a").replace("[job1/U1]", "[job9/U9]")
    text = _render(home, "approve", "c-fixing-a", sampler=lambda s, u: bad)
    assert text.startswith("The draft from sampling did not pass the gate")
    assert "step 1 cites job9/U9, which is not in the evidence" in text
    assert endpoint.hits == 0
    assert not (sf.skills_root(home) / "fixing-a").exists()


def test_the_host_agent_is_told_the_path_and_the_second_approve_installs(tmp_path):
    home = _home(tmp_path)
    _write(home, record("fixing-a", ok_draft=False))
    text = _render(home, "approve", "c-fixing-a")
    staged = sp.handoff_path(home, "c-fixing-a")
    assert f"1. Write ONE file, {staged}, with your own file tools" in text
    assert f"run {C} approve c-fixing-a again" in text
    staged.parent.mkdir(parents=True)
    staged.write_text(draft("fixing-a").replace("[job1/U1]", "[nope]"), encoding="utf-8")
    refused = _render(home, "approve", "c-fixing-a")
    assert "did not pass the gate, so nothing was installed" in refused
    assert staged.is_file() and not (sf.skills_root(home) / "fixing-a").exists()
    staged.write_text(draft("fixing-a"), encoding="utf-8")
    assert _render(home, "approve", "c-fixing-a").startswith("installed skill fixing-a at ")
    skill = (sf.skills_root(home) / "fixing-a" / "SKILL.md").read_text(encoding="utf-8")
    assert "bantamkit-sha256:" in skill and not sf.is_edited(skill)
    assert (sf.skills_root(home) / "fixing-a" / "references" / "evidence.md").is_file()
    assert not staged.parent.exists()


def test_without_an_adapter_the_file_is_printed_and_nothing_written(tmp_path):
    home = _home(tmp_path, claude=False)
    _write(home, record("fixing-a"))
    text = _render(home, "approve", "c-fixing-a")
    assert text.startswith("No Claude Code skill directory was found on this host")
    assert "bantamkit-sha256:" in text
    assert not (sf.skills_root(home)).exists()
    assert _doc(home)["clusters"][0]["status"] == "pending"


def test_undo_after_an_approve_removes_it_and_rejects_its_proposal(tmp_path):
    home = _home(tmp_path)
    _write(home, record("fixing-a"))
    _render(home, "approve", "c-fixing-a")
    said = _render(home, "undo", "fixing-a")
    assert said.endswith("; proposal c-fixing-a is marked rejected")
    assert "fixing-a" not in sf.read_state(home)["skills"]
    rec = _doc(home)["clusters"][0]
    assert rec["status"] == "rejected" and rec["rejected_at"] == 6


@pytest.mark.parametrize(
    ("args", "said"),
    [
        (
            ("bogus", "x"),
            "unknown action 'bogus'; one of list, approve, reject, undo, promote, demote",
        ),
        (("approve", None), f"action approve needs a target: {C} approve <id or name>"),
        (("approve", "c-x", "global"), "level must be project or user"),
        (("reject", "nope"), "no pending proposal or change is named 'nope'"),
        (("undo", "nope"), "no skill named 'nope' is installed"),
        (("demote", "nope"), "no skill named 'nope' is installed"),
    ],
)
def test_refusals_are_sentences_in_the_message(tmp_path, args, said):
    assert _render(_home(tmp_path), *args) == said


# --------------------------------------------------------------------------------- the line


def _events(home: Path, *events: str) -> None:
    sf.write_state(
        home,
        {
            "skills": {},
            "events": [
                {"at": f"2026-10-27T00:00:0{i}.000Z", "event": e} for i, e in enumerate(events)
            ],
        },
    )


@pytest.fixture
def audit_on(monkeypatch):
    monkeypatch.delenv("BANTAMKIT_SKILL_AUDIT", raising=False)


def test_nothing_new_is_none_and_writes_nothing(tmp_path, audit_on):
    home = _home(tmp_path)
    assert sp.session_line(home) is None
    assert not sf.state_path(home).exists()


def test_one_install_is_one_line_never_repeated(tmp_path, audit_on):
    home = _home(tmp_path)
    _events(home, "installed skill fixing-a")
    line = sp.session_line(home)
    assert line == (
        f"[bantamkit] skills: installed fixing-a on probation (undo: {C} undo fixing-a) — "
        f"{C} lists them."
    )
    assert len(line.encode("utf-8")) <= sp.LINE_MAX_BYTES
    assert sp.session_line(home) is None


def test_four_events_are_cut_on_an_item_boundary(tmp_path, audit_on):
    home = _home(tmp_path)
    _events(
        home,
        "installed skill fixing-a",
        "removed unused skill old-b",
        "promoted skill used-c",
        "rolled back used-c to v1",
    )
    line = sp.session_line(home)
    assert line is not None and len(line.encode("utf-8")) <= sp.LINE_MAX_BYTES
    assert line == (
        f"[bantamkit] skills: installed fixing-a on probation (undo: {C} undo fixing-a); +3 more "
        f"— {C} lists them."
    )
    assert sp.session_line(home) is None


def test_the_audit_switch_off_silences_the_line(tmp_path, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_AUDIT", "off")
    home = _home(tmp_path)
    _events(home, "installed skill fixing-a")
    before = sf.state_path(home).read_bytes()
    assert sp.session_line(home) is None
    assert sf.state_path(home).read_bytes() == before


# ------------------------------------------------------------------------------ the server


def test_the_server_lists_three_prompts_and_drafts_through_the_clients_sampling(
    tmp_path, monkeypatch, endpoint
):
    """Over the in-memory client in the handshake protocol (the one Claude Code speaks): the
    prompt's three optional arguments, then an approve whose draft is asked of the client's
    sampling callback, once, with `SAMPLING_MAX_TOKENS` -- and the endpoint never."""
    from mcp import types
    from mcp.client import Client
    from test_status_surface import make_memory

    from bantamkit.mcpserver import build_server

    home = _home(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(home.parent)
    _write(home, record("fixing-a", ok_draft=False))
    asked = []

    async def sampling(context, params):
        asked.append(params)
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text=draft("fixing-a")),
            model="stub",
        )

    async def scenario():
        server = build_server(make_memory(tmp_path))
        async with Client(server, sampling_callback=sampling, mode="legacy") as c:
            listed = (await c.list_prompts()).prompts
            got = await c.get_prompt(
                sp.SKILL_PROPOSE_NAME, {"action": "approve", "target": "c-fixing-a"}
            )
            status = await c.call_tool("bantamkit_status", {})
        return listed, got, status

    listed, got, status = anyio.run(scenario)
    prompt = listed[2]
    assert prompt.name == sp.SKILL_PROPOSE_NAME and prompt.title == sp.SKILL_PROPOSE_PROMPT_TITLE
    assert [(a.name, a.description, a.required) for a in prompt.arguments] == [
        (n, d, False) for n, d in sp.ARGUMENTS
    ]
    assert got.messages[0].content.text.startswith("installed skill fixing-a at ")
    assert len(asked) == 1
    assert asked[0].max_tokens == sp.SAMPLING_MAX_TOKENS
    assert asked[0].system_prompt == DRAFT_SYSTEM
    assert endpoint.hits == 0
    assert status.content[0].text.split("\n")[-1].endswith(
        "; drafter sampling; auto off (BANTAMKIT_SKILL_AUTO=on to opt in)"
    )
    assert json.loads(sf.state_path(home).read_text(encoding="utf-8"))["skills"]["fixing-a"]
