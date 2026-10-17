"""`memory_recall({file})` (#200, Task 7): the facts linked to a tracked file, and its last touch.

Mirrored by runtime-ts/test/touch-recall-file.test.mjs; tools/conformance/suites/wire.mjs's
`memory-recall-file` session compares the two servers.
"""

from __future__ import annotations

import asyncio
import os
import subprocess

import pytest

from bantamkit.memory import Memory
from bantamkit.memory.store import MemoryValidationError
from bantamkit.touch import recallfile as rf
from bantamkit.touch.log import TouchLog
from bantamkit.touch.refs import FileSet
from bantamkit.touch.repo import find_repo


def _git(top, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
         "-C", str(top), *args],
        check=True, capture_output=True, env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
    )


@pytest.fixture
def bed(tmp_path, monkeypatch):
    top = tmp_path / "repo"
    for rel in ("src/memory/store.ts", "other/store.ts", "docs/x.md"):
        (top / rel).parent.mkdir(parents=True, exist_ok=True)
        (top / rel).write_text("x\n", encoding="utf-8")
    _git(top, "init", "-q")
    _git(top, "add", ".")
    _git(top, "commit", "-qm", "the first commit")
    m = Memory(store=tmp_path / "store")
    m.save("project", "fa", "about memory/store.ts", "fa body")
    m.save("project", "fb", "unrelated words here", "fb body")
    monkeypatch.chdir(top)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return {"top": top, "m": m, "home": home}


def test_a_suffix_lists_the_linked_fact_and_never_touched(bed):
    out = bed["m"].recall_file("memory/store.ts")
    first = out.reply.split("\n")[0]
    assert first.startswith("[file] memory/store.ts — last touched never; last commit ")
    assert first.endswith(" the first commit")
    assert "[fa] (project) about memory/store.ts\nfa body" in out.reply
    assert "[fb]" not in out.reply
    assert out.status == "answered" and out.returned == 1 and out.headers


def test_an_ambiguous_suffix_names_both_by_shortest_suffix(bed):
    out = bed["m"].recall_file("store.ts")
    assert out.reply == (
        '"store.ts" matches 2 tracked files: memory/store.ts, other/store.ts. Pass a longer suffix.'
    )
    assert out.status == "none"


def test_an_unknown_file(bed):
    assert bed["m"].recall_file("nope.py").reply == (
        'No tracked file in this repository matches "nope.py".'
    )


def test_a_file_no_fact_names(bed):
    out = bed["m"].recall_file("docs/x.md")
    assert out.reply.split("\n")[0].startswith("[file] x.md — last touched never")
    assert out.reply.endswith("\n\nNo memory is linked to x.md.")
    assert out.status == "none"


def test_outside_a_repo(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    m = Memory(store=tmp_path / "store")
    assert m.recall_file("x.py").reply == rf.FILE_NOT_IN_REPO


def test_with_a_query_line_two_says_it_was_ignored(bed):
    lines = bed["m"].recall_file("memory/store.ts", None, "x").reply.split("\n")
    assert lines[1] == "(query ignored: file was given)" and lines[2] == ""
    assert bed["m"].recall_file("store.ts", None, "x").reply.split("\n")[1] == rf.QUERY_IGNORED


def test_a_windows_separator_and_an_absolute_path_resolve(bed):
    assert bed["m"].recall_file("memory\\store.ts").reply.startswith("[file] memory/store.ts")
    absolute = str(bed["top"] / "src" / "memory" / "store.ts")
    assert bed["m"].recall_file(absolute).reply.startswith("[file] memory/store.ts")


def test_a_touch_line_dates_the_history(bed):
    repo = find_repo(str(bed["top"]))
    TouchLog(bed["home"], repo.id).append_touch(
        "s", 1, "edit", "src/memory/store.ts", ts="2026-10-16T10:00:00Z"
    )
    TouchLog(bed["home"], repo.id).append_touch(
        "s", 2, "read", "other/store.ts", ts="2026-10-17T10:00:00Z"
    )
    first = bed["m"].recall_file("memory/store.ts").reply.split("\n")[0]
    assert first.startswith("[file] memory/store.ts — last touched 2026-10-16 (edit); last commit ")


def test_nothing_is_stamped(bed):
    before = bed["m"].store.lookup("fa", stamp=False)
    bed["m"].recall_file("memory/store.ts")
    assert bed["m"].store.lookup("fa", stamp=False) == before


def test_ambiguous_shows_five_and_counts_the_rest():
    files = [f"d{i}/s.py" for i in range(7)]
    fs = FileSet(files)
    assert rf.ambiguous("s.py", fs.matches("s.py"), fs) == (
        '"s.py" matches 7 tracked files: d0/s.py, d1/s.py, d2/s.py, d3/s.py, d4/s.py (+2). '
        "Pass a longer suffix."
    )


def test_linked_names_strong_first_then_weak_by_weight_then_name():
    graph = {
        "strong": {"p": [["s2", None], ["s1", "x"], ["s2", "y"]]},
        "weak": {"p": {
            "s1": ["2026-10-16T00:00:00Z"],
            "w-old": ["2026-09-01T00:00:00Z"],
            "w-b": ["2026-10-16T00:00:00Z"],
            "w-a": ["2026-10-16T00:00:00Z"],
            "w-bad": ["not a stamp"],
        }},
    }
    assert rf.linked_names(graph, "p", "2026-10-17T00:00:00Z") == [
        "s2", "s1", "w-a", "w-b", "w-old", "w-bad",
    ]


def test_last_touch_keeps_the_newest_and_the_later_of_a_tie():
    rows = [
        {"ts": "2026-10-16T00:00:00Z", "op": "read", "path": "p"},
        {"ts": "2026-10-16T00:00:00Z", "op": "edit", "path": "p"},
        {"ts": "2026-10-15T00:00:00Z", "op": "write", "path": "p"},
        {"ts": "2026-10-18T00:00:00Z", "op": "use", "path": "p"},
    ]
    assert rf.last_touch(rows, "p") == ("2026-10-16T00:00:00Z", "edit")


# ------------------------------------------------------------------------- the handler

mcp = pytest.importorskip("mcp")


def _call(m, args):
    from mcp import Client

    from bantamkit.mcpserver import build_server

    async def scenario():
        async with Client(build_server(m)) as c:
            answer = await c.call_tool("memory_recall", args)
            return answer.is_error, answer.content[0].text

    return asyncio.run(scenario())


def test_the_handler_refuses_neither_argument(bed):
    assert _call(bed["m"], {}) == (
        True, "Error executing tool memory_recall: memory_recall needs a query or a file."
    )
    assert _call(bed["m"], {"query": None, "file": None})[0] is True


def test_the_handler_serves_file_and_ignores_the_query(bed):
    err, text = _call(bed["m"], {"file": "memory/store.ts", "query": "x"})
    assert err is False and text.split("\n")[1] == rf.QUERY_IGNORED


def test_the_component_recall_takes_file_for_the_agent_surface(bed):
    assert bed["m"].recall(file="nope.py") == rf.FILE_UNKNOWN.format(file="nope.py")
    with pytest.raises(MemoryValidationError, match="needs a query or a file"):
        bed["m"].recall()
