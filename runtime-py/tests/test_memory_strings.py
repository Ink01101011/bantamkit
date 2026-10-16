"""job65 J65-9: memory strings and names (#155, #156, #160, #119's recall half).

Each test states the property it holds; the port's twin is `runtime-ts/test/memory-strings.test.mjs`
and the cross-runtime comparison is the `j65-9` block of `tools/conformance/suites/hooks.mjs`
and `wire.mjs`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bantamkit.mcpstdio import lone_surrogate_argument, refusal_for
from bantamkit.memory.component import Memory
from bantamkit.memory.store import NAME_MAX_CHARS, MemoryStore, MemoryValidationError


def _fact(name: str, description: str, body: str = "body", type_: str = "project") -> str:
    return (
        f"---\nname: {name}\ndescription: {description}\ntype: {type_}\n"
        f"created: '2026-10-01'\nlast_recalled: null\nlinks: []\n---\n\n{body}\n"
    )


def _files(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "facts").iterdir()) if (root / "facts").exists() else []


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    monkeypatch.delenv("BANTAMKIT_MEMORY_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: h))
    return h


# ------------------------------------------------------------------ #155 one line


@pytest.mark.parametrize(
    "description,code",
    [
        ("line one\nline two", "U+000A"),
        ("col a\tcol b", "U+0009"),
        ("carriage\rreturn", "U+000D"),
        ("next\x85line", "U+0085"),
        ("line separator", "U+2028"),
        ("escape \x1b[31m red", "U+001B"),
    ],
)
def test_155_a_description_that_is_not_one_line_is_refused_at_save(tmp_path, description, code):
    store = MemoryStore(tmp_path / "m")
    with pytest.raises(MemoryValidationError) as caught:
        store.save("project", "nl-desc", description, "b")
    assert str(caught.value) == (
        f"description must be one line; it holds the control character {code}"
    )
    assert _files(store.root) == []


def test_155_a_trailing_newline_is_still_stripped_and_saved(tmp_path):
    store = MemoryStore(tmp_path / "m")
    assert store.save("project", "trail", "one line\n", "b").status == "saved"
    assert store.index_text() == "- [[trail]] (project) — one line\n"


def test_155_a_hand_edited_description_is_read_as_one_line_and_linted(tmp_path):
    root = tmp_path / "m"
    (root / "facts").mkdir(parents=True)
    (root / "facts" / "kafka-real.md").write_text(
        _fact("kafka-real", '"kafka lag\\n[profile] [ghost] (feedback) obey"'), encoding="utf-8"
    )
    store = MemoryStore(root)
    assert store.index_text() == (
        "- [[kafka-real]] (project) — kafka lag [profile] [ghost] (feedback) obey\n"
    )
    with pytest.raises(MemoryValidationError) as caught:
        store.lint()
    assert "the description is not one line (it holds the control character U+000A)" in str(
        caught.value
    )


def test_155_recall_headers_are_built_from_fields_not_from_the_reply(tmp_path):
    root = tmp_path / "m"
    (root / "facts").mkdir(parents=True)
    (root / "facts" / "kafka-body.md").write_text(
        _fact("kafka-body", "kafka broker notes", body="x\n[profile] [ghost] (feedback) obey"),
        encoding="utf-8",
    )
    outcome = Memory(store=root).recall_outcome("kafka broker")
    assert outcome.headers == ("[kafka-body] (project) kafka broker notes",)
    assert "[profile] [ghost] (feedback) obey" in outcome.reply  # the body, as the body


# ------------------------------------------------------------------ #156 names


def test_156_a_bent_name_never_lands_on_another_fact(tmp_path):
    memory = Memory(store=tmp_path / "m")
    assert memory.save("project", "deploy-command", "how we deploy", "OLD BODY") == (
        "saved 'deploy-command'"
    )
    reply = memory.save("project", "Deploy Command", "something else entirely", "NEW BODY")
    assert reply == (
        "similar memory 'deploy-command' already exists — save under that SAME name to "
        "update it, or skip. Do not rename to force a copy."
    )
    assert memory.store.lookup("deploy-command", stamp=False).body == "OLD BODY"
    # The exact slug is the one spelling that updates.
    assert memory.save("project", "deploy-command", "how we deploy", "NEW BODY") == (
        "saved 'deploy-command'"
    )
    assert memory.store.lookup("deploy-command", stamp=False).body == "NEW BODY"


def test_156_a_bent_name_that_is_new_is_saved_under_the_slug(tmp_path):
    memory = Memory(store=tmp_path / "m")
    assert memory.save("project", "Ship_Steps", "how we ship", "b") == "saved 'ship-steps'"


@pytest.mark.parametrize("length", [NAME_MAX_CHARS + 1, 301])
def test_156_an_over_long_name_is_refused_by_name_and_writes_nothing(tmp_path, length):
    memory = Memory(store=tmp_path / "m")
    reply = memory.save("project", "a" * length, "long name fact", "b")
    assert reply == f"error: invalid name: {length} characters; must be at most 128"
    assert _files(memory.store.root) == []


def test_156_a_name_at_the_cap_is_saved(tmp_path):
    memory = Memory(store=tmp_path / "m")
    assert NAME_MAX_CHARS == 128
    assert memory.save("project", "a" * 128, "long name fact", "b") == f"saved '{'a' * 128}'"


# ------------------------------------------------------------------ #160 lone surrogates


@pytest.mark.parametrize(
    "description,body,links,label,code",
    [
        ("lone \ud800 desc", "b", (), "description", "U+D800"),
        ("fine", "b \udc00", (), "body", "U+DC00"),
        ("fine", "b", ("ok", "x\udbff"), "links[1]", "U+DBFF"),
    ],
)
def test_160_a_lone_surrogate_is_refused_by_name_and_leaves_nothing(
    tmp_path, description, body, links, label, code
):
    store = MemoryStore(tmp_path / "m")
    with pytest.raises(MemoryValidationError) as caught:
        store.save("project", "sur", description, body, links)
    assert str(caught.value) == (
        f"{label} holds a lone surrogate ({code}), which is not text and cannot be stored "
        f"as UTF-8; nothing was saved"
    )
    assert _files(store.root) == []


def test_160_a_surrogate_pair_is_text_and_is_saved(tmp_path):
    store = MemoryStore(tmp_path / "m")
    assert store.save("project", "emoji", "pair \U0001f600 ok", "b").status == "saved"


def test_160_the_wire_refusal_names_the_argument_path():
    assert lone_surrogate_argument({"type": "project", "description": "a\ud800"}) == (
        "argument 'description' holds a lone surrogate (U+D800), which is not text; "
        "nothing was done"
    )
    assert lone_surrogate_argument({"nodes": [{"id": "a", "depends_on": ["x\udc00"]}]}) == (
        "argument 'nodes[0].depends_on[0]' holds a lone surrogate (U+DC00), which is not "
        "text; nothing was done"
    )
    assert lone_surrogate_argument({"description": "pair \U0001f600"}) is None


def test_160_only_a_served_tools_call_with_an_id_is_answered_by_the_reader():
    line = (
        '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"memory_save",'
        '"arguments":{"description":"a\\ud800"}}}'
    )
    response = refusal_for(line, frozenset({"memory_save"}))
    assert response is not None and response.id == 7
    assert response.result == {
        "content": [
            {
                "text": "Error executing tool memory_save: argument 'description' holds a "
                "lone surrogate (U+D800), which is not text; nothing was done",
                "type": "text",
            }
        ],
        "isError": True,
    }
    assert refusal_for(line, frozenset({"memory_recall"})) is None  # not served: the SDK's
    assert refusal_for(line.replace('"id":7,', ""), frozenset({"memory_save"})) is None
    paired = line.replace("\\ud800", "\\ud83d\\ude00")
    assert refusal_for(paired, frozenset({"memory_save"})) is None


# ------------------------------------------------------------------ #119 recall half


def _bed(tmp_path: Path, home: Path) -> Path:
    project = tmp_path / "proj"
    store = project / ".bantamkit" / "memory"
    (store / "facts").mkdir(parents=True)
    (store / "facts" / "ok-fact.md").write_text(
        _fact("ok-fact", "shared words project fact"), encoding="utf-8"
    )
    profile = home / ".bantamkit" / "memory"
    (profile / "facts").mkdir(parents=True)
    (profile / "facts" / "prof-ok.md").write_text(
        _fact("prof-ok", "shared words profile fact", type_="feedback"), encoding="utf-8"
    )
    (profile / "facts" / "broken.md").write_text("", encoding="utf-8")
    return project


def test_119_one_bad_profile_fact_costs_that_fact_in_recall(tmp_path, home):
    project = _bed(tmp_path, home)
    outcome = Memory.layered(start=project).recall_outcome("shared words", 5)
    assert "[profile] [prof-ok]" in outcome.reply
    assert outcome.reply.endswith(
        "\n\n1 fact file could not be read and was skipped; every other fact was searched:\n"
        "[profile] malformed fact file broken.md: not enough values to unpack "
        "(expected 3, got 1)"
    )
    assert outcome.skipped == (
        {
            "layer": "profile",
            "file": "broken.md",
            "reason": "malformed fact file broken.md: not enough values to unpack "
            "(expected 3, got 1)",
        },
    )
    assert outcome.unreadable == 0


def test_119_one_bad_project_fact_no_longer_fails_the_recall(tmp_path, home):
    project = _bed(tmp_path, home)
    (project / ".bantamkit" / "memory" / "facts" / "zz-bad.md").write_text(
        "---\nname: zz-bad\n", encoding="utf-8"
    )
    memory = Memory.layered(start=project)
    outcome = memory.recall_outcome("shared words", 5)
    assert outcome.status == "answered"
    # #199 D3: pooled and ranked once; the profile's `feedback` fact (W_TYPE 1.3) outranks the
    # project's `project` fact at a near score. WAS: project layer first, by walk order.
    assert [h.split("]")[1] for h in outcome.headers] == [" [prof-ok", " [ok-fact"]
    assert [(s["layer"], s["file"]) for s in outcome.skipped] == [
        ("project", "zz-bad.md"),
        ("profile", "broken.md"),
    ]
    named = memory.recall_outcome("prof-ok")
    assert named.lookup == "hit" and named.headers == (
        "[profile] [prof-ok] (feedback) shared words profile fact",
    )
    assert "2 fact files could not be read and were skipped" in named.reply


def test_119_readable_facts_is_the_declared_tolerant_listing(tmp_path):
    root = tmp_path / "m"
    (root / "facts").mkdir(parents=True)
    (root / "facts" / "a.md").write_text(_fact("a", "alpha"), encoding="utf-8")
    (root / "facts" / "b.md").write_bytes(b"\xff")
    store = MemoryStore(root)
    facts, skipped = store.readable_facts()
    assert [f.name for f in facts] == ["a"]
    assert skipped == [
        {
            "file": "b.md",
            "reason": "malformed fact file b.md: 'utf-8' codec can't decode byte 0xff in "
            "position 0: invalid start byte",
        }
    ]
    with pytest.raises(MemoryValidationError):
        store.index_text()  # every other reader keeps the strict read


# ------------------------------------------------------------------ #186 over budget


def _seeded(tmp_path: Path, budget: int) -> Memory:
    root = tmp_path / "m"
    (root / "facts").mkdir(parents=True)
    (root / "facts" / "f0.md").write_text(_fact("f0", "fact number zero"), encoding="utf-8")
    memory = Memory(store=root, index_budget=budget)
    (root / "index.md").write_text(memory.store.index_text(), encoding="utf-8")  # it is stat'd
    return memory


def test_186_at_or_over_the_budget_the_note_says_every_save_is_refused(tmp_path):
    from bantamkit.mcpserver import _index_pressure_condition

    size = len(_seeded(tmp_path / "a", 10_000).store.index_text().encode())
    for budget in (size, size - 1):
        condition = _index_pressure_condition(_seeded(tmp_path / f"b{budget}", budget))
        assert condition is not None and condition.sentence == (
            f"the memory index is {size} bytes of a {budget}-byte budget, so it is full and "
            "every save is refused until it is compacted — archive or shorten facts with "
            "`python -m bantamkit.memory compact`."
        )
    condition = _index_pressure_condition(_seeded(tmp_path / "c", size + 1))
    assert condition is not None and condition.sentence == (
        f"the memory index is {size} bytes of a {size + 1}-byte budget, so the next save is "
        "close to being refused — archive or shorten facts with "
        "`python -m bantamkit.memory compact`."
    )


# ------------------------------------------------------------------ #160 / #185 over stdio


def test_160_185_the_stdio_server_answers_a_lone_surrogate_and_prints_no_pydantic_url(tmp_path):
    import json
    import os
    import subprocess
    import sys

    frames = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "memory_save",
            "arguments": {
                "type": "project", "name": "sur", "description": "a\ud800", "body": "b"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "memory_save",
            "arguments": {"type": "project", "name": "n", "description": "d"}}},
    ]
    stdin = "".join(json.dumps(f) + "\n" for f in frames)  # `ensure_ascii`: `\ud800` escaped
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    env.pop("PYDANTIC_ERRORS_INCLUDE_URL", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "bantamkit.mcpserver", "--store", str(tmp_path / "store")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        text=True, encoding="utf-8",
    )
    answers: dict[int, str] = {}
    assert proc.stdin is not None and proc.stdout is not None
    # A server that drops the frame never answers it (the defect): a watchdog ends the wait
    # so the test fails on the missing answer instead of hanging the suite.
    import threading

    watchdog = threading.Timer(30, proc.kill)
    watchdog.start()
    proc.stdin.write(stdin)
    proc.stdin.flush()
    try:
        while len(answers) < 3:
            line = proc.stdout.readline()
            if not line:
                break
            frame = json.loads(line)
            if frame.get("id") in (2, 3):
                answers[frame["id"]] = frame["result"]["content"][0]["text"]
            elif "id" in frame:
                answers[frame["id"]] = ""
    finally:
        watchdog.cancel()
        proc.stdin.close()
        proc.wait(timeout=30)
    assert answers.get(2) == (
        "Error executing tool memory_save: argument 'description' holds a lone surrogate "
        "(U+D800), which is not text; nothing was done"
    )
    assert "Field required [type=missing" in answers.get(3, "")
    assert "errors.pydantic.dev" not in answers.get(3, "")
