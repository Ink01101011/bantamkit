"""Claude Code's auto-memory as the read-only `[native]` recall layer (#199 J68-11, ruling A+B)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bantamkit.memory import Memory
from bantamkit.memory.native import NativeStore
from bantamkit.memory.retrieval import query_terms
from bantamkit.memory.store import MemoryStore, pool_of, pool_without
from bantamkit.memory.usage import UsageLedger

SRC = Path(__file__).resolve().parents[1] / "src"


def _native(directory: Path, name: str, description: str, type_: str = "project", body: str = "nb"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.md").write_text(
        f'---\nname: {name}\ndescription: "{description}"\nmetadata:\n  node_type: memory\n'
        f"  type: {type_}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def _store(root: Path) -> MemoryStore:
    return MemoryStore(root / ".bantamkit" / "memory")


def _state(directory: Path) -> dict[str, tuple[bytes, int]]:
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(directory.iterdir())}


@pytest.fixture
def bed(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("BANTAMKIT_INDEX_DIR", str(tmp_path / "index"))
    project = tmp_path / "companyA"
    project.mkdir()
    native = tmp_path / "host" / "memory"
    native.mkdir(parents=True)
    index = "# Memory index\n\n- [kafka](kafka.md) — kafka\n"
    (native / "MEMORY.md").write_text(index, encoding="utf-8")
    return project, native


def test_the_native_layer_is_last_and_its_hits_are_tagged(bed):
    project, native = bed
    _store(project).save("project", "kafka-notes", "kafka notes", "b")
    _native(native, "kafka-lag", "kafka consumer lag runbook", "reference")
    mem = Memory.layered(start=project, native=native)
    assert [label for label, _, _ in mem._layers] == ["project", "profile", "native"]
    out = mem.recall_outcome("kafka consumer lag", stamp=False)
    assert out.headers[0] == "[native] [kafka-lag] (reference) kafka consumer lag runbook"
    assert out.candidates == 2


def test_no_native_argument_means_no_layer(bed):
    project, _ = bed
    labels = [label for label, _, _ in Memory.layered(start=project)._layers]
    assert labels == ["project", "profile"]
    assert [label for label, _, _ in Memory.layered(start=project, native="  ")._layers] == [
        "project",
        "profile",
    ]


def test_the_tool_recall_writes_nothing_into_the_native_directory(bed):
    project, native = bed
    store = project / ".bantamkit" / "memory"
    MemoryStore(store).save("project", "kafka-notes", "kafka notes", "b")
    _native(native, "kafka-lag", "kafka consumer lag runbook")
    # bantamkit's own shape, dated as 0.35.x dated it: a WRITABLE layer would repair it.
    (native / "old-shape.md").write_text(
        "---\nname: old-shape\ndescription: kafka broker\ntype: project\ncreated: '2026-01-01'\n"
        "last_recalled: '2026-01-02'\nlinks: []\n---\n\nb\n",
        encoding="utf-8",
    )
    before = _state(native)
    mem = Memory.layered(start=project, native=native)
    mem.recall("kafka broker lag")
    mem.recall("kafka-lag")
    assert _state(native) == before
    assert mem.repaired == 0
    ledger = UsageLedger(Path.home(), store).path.read_text(encoding="utf-8")
    uses = [(e["fact"], e["kind"]) for e in map(json.loads, ledger.splitlines())]
    assert ("kafka-lag", "recall_hit") in uses and ("kafka-lag", "body_read") in uses
    assert ("old-shape", "recall_hit") in uses


def test_a_name_a_bantamkit_layer_holds_never_answers_from_native(bed):
    project, native = bed
    _store(project).save("project", "deploy", "how we deploy", "real")
    _native(native, "deploy", "deploy deploy deploy runbook", body="export copy")
    mem = Memory.layered(start=project, native=native)
    out = mem.recall_outcome("deploy runbook", stamp=False)
    assert out.headers == ("[project] [deploy] (project) how we deploy",)
    assert "export copy" not in out.reply
    # The copy counts in no statistic: the native pool holds nothing once it is shadowed.
    pool = NativeStore(native).pool(query_terms("deploy"), shadow={"deploy"})
    assert (pool.n, pool.df, pool.names) == (0, {"deploy": 0}, [])


def test_a_native_file_that_does_not_parse_is_skipped_and_named(bed):
    project, native = bed
    _native(native, "gc-pauses", "garbage collector pauses", "feedback")
    (native / "broken.md").write_text("no frontmatter, garbage collector\n", encoding="utf-8")
    out = Memory.layered(start=project, native=native).recall_outcome("garbage collector")
    assert out.headers == ("[native] [gc-pauses] (feedback) garbage collector pauses",)
    assert [(s["layer"], s["file"]) for s in out.skipped] == [("native", "broken.md")]
    assert "MEMORY" not in out.reply


def test_a_native_directory_that_is_not_there_is_silent(bed, tmp_path):
    project, _ = bed
    MemoryStore(project / ".bantamkit" / "memory").save("project", "x-fact", "own subject", "b")
    mem = Memory.layered(start=project, native=tmp_path / "nowhere")
    out = mem.recall_outcome("own subject", stamp=False)
    assert (out.status, out.unreadable, out.skipped) == ("answered", 0, ())
    assert mem._unreadable_layers() == []


def test_pool_without_equals_the_files_pool_of_the_rest(bed):
    _, native = bed
    for i, d in enumerate(["kafka lag", "kafka broker lag", "zookeeper", "lag lag kafka"]):
        _native(native, f"n{i}", d)
    q = query_terms("kafka lag")
    s = NativeStore(native)
    got = s.pool(q, shadow={"n1"})
    want = pool_of([f for f in s.candidates() if f.name != "n1"], q)
    assert (got.n, got.total, got.df) == (want.n, want.total, want.df)
    # The rows that hold a term, and their weights, are the files' rows renumbered.
    held = sorted({got.names[got.segs[t][j]] for t in q for j in range(0, len(got.segs[t]), 3)})
    assert held == want.names
    same = pool_without(got, set())
    assert same is got


def test_layered_for_eval_takes_a_native_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_INDEX_DIR", str(tmp_path / "index"))
    native = tmp_path / "native"
    _native(native, "kafka-lag", "kafka consumer lag runbook")
    a = Memory.layered_for_eval(tmp_path / "p", tmp_path / "q")
    b = Memory.layered_for_eval(tmp_path / "p", tmp_path / "q", native=native)
    assert [f.name for f in a.inject_candidates("kafka lag")] == []
    assert [f.name for f in b.rank_all("kafka lag")] == ["kafka-lag"]


def _hook(home: Path, cwd: Path, payload: dict, extra: dict | None = None):
    env = dict(os.environ, PYTHONPATH=str(SRC), HOME=str(home), USERPROFILE=str(home))
    env.pop("BANTAMKIT_MEMORY_DIR", None)
    env.pop("CLAUDE_COWORK_MEMORY_PATH_OVERRIDE", None)
    env.update(extra or {})
    return subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", "--hook"],
        capture_output=True,
        cwd=str(cwd),
        env=env,
        input=json.dumps({"cwd": str(cwd), **payload}).encode("utf-8"),
        timeout=120,
    )


def test_the_hook_reads_the_native_layer_from_the_transcript_branch(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    _store(cwd).save("project", "kafka-notes", "kafka group notes", "b")
    native = tmp_path / "t" / "memory"
    _native(native, "kafka-lag", "kafka consumer lag runbook", "reference")
    (native / "MEMORY.md").write_text("# Memory index\n", encoding="utf-8")
    before = _state(native)
    prompt = {"hook_event_name": "UserPromptSubmit", "prompt": "kafka consumer lag again"}
    extra = {"BANTAMKIT_INDEX_DIR": str(tmp_path / "index")}
    transcript = str(tmp_path / "t" / "s.jsonl")
    done = _hook(home, cwd, {**prompt, "session_id": "a", "transcript_path": transcript}, extra)
    ctx = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "[native] [kafka-lag] (reference) kafka consumer lag runbook" in ctx
    plain = _hook(home, cwd, {**prompt, "session_id": "b"}, extra)
    assert "[native]" not in json.loads(plain.stdout)["hookSpecificOutput"]["additionalContext"]
    assert _state(native) == before
    assert not (home / ".bantamkit" / "usage").exists()


def test_the_mcp_server_takes_branch_two_only(tmp_path, monkeypatch):
    from argparse import Namespace

    from bantamkit.mcpserver import _build_memory

    home = tmp_path / "home"
    native = tmp_path / "auto"
    _native(native, "kafka-lag", "kafka consumer lag runbook")
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"autoMemoryDirectory": str(native)}), encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("CLAUDE_COWORK_MEMORY_PATH_OVERRIDE", raising=False)
    args = Namespace(k=3, index_budget=8000, store=None, start=str(tmp_path))
    # No MEMORY.md: the candidate is refused, so there is no layer.
    assert [label for label, _, _ in _build_memory(args)._layers][-1] != "native"
    (native / "MEMORY.md").write_text("# Memory index\n", encoding="utf-8")
    mem = _build_memory(args)
    assert mem._layers[-1][0] == "native" and mem._layers[-1][1].root == native
