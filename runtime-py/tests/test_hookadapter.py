"""`bantamkit-mcp --hook` on the PYTHON runtime: the flag, the dispatch, and two arms.

WHY THIS FILE EXISTS. CLAUDE.md's rule is that a feature lands in both runtimes or it does
not land, and `--hook` landed in `runtime-ts` first (J62-2): measured at that HEAD,
`node tools/conformance/run.mjs --suite cli` reported 21 failures, every one of them the same
eight bytes -- python printing `[--mcp-report]` where node prints `[--hook] [--mcp-report]`.
A flag on one parser and not the other is not a coverage gap, it is the two runtimes
disagreeing about what the product is. This file is the Python half's gate.

THE CONTRACT, deliberately narrow so the two runtimes can be compared: ONE JSON object in on
stdin, AT MOST ONE JSON object out on stdout, exit 0 ALWAYS. Every assertion below judges
stdout the way the host does and the exit code the way the host does -- a hook that exits
non-zero or lets a traceback reach stderr is rendered by Claude Code as an error on the
user's screen, which is the one thing this surface may not do.

THE TESTS ARE PROCESS-LEVEL ON PURPOSE, the same reason `runtime-ts/test/hookadapter.test.mjs`
gives: the PreCompact channel defect shipped because the arm had only ever been READ. These
feed `python -m bantamkit.mcpserver --hook` a real payload on a real stdin.

NOTHING HERE TOUCHES THE REAL HOME OR A REAL STORE. Every run gets a scratch `HOME` (so the
adapter's log and ledger land in the scratch) and a scratch cwd, and `BANTAMKIT_MEMORY_DIR`
is cleared from the child's environment so no ambient pin can answer for a store under
`tmp_path`.

SCOPE. J62-3 landed the parser surface, the dispatch table, the failure posture and the
SessionStart and UserPromptSubmit arms, and pinned that dispatch RECOGNISED the five it had
not ported. J62-3B landed those five -- PreToolUse[Read] (sections 5), PostToolUse's usage
log (6) and memory_save compaction (7), PreCompact (8), PostCompact (9) and Stop with the
dream preview beside it (10) -- plus the `tokens` promotion on the store (11). The
recognition case is kept and its asserted set shrank to empty rather than being deleted.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


def _env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.pop("BANTAMKIT_MEMORY_DIR", None)
    return env


def _run_cli(argv: list[str], *, home: Path, cwd: Path, env_extra: dict[str, str] | None = None):
    env = _env(home)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", *argv],
        capture_output=True,
        cwd=str(cwd),
        env=env,
        input=b"",
        timeout=120,
    )


def _run_hook(
    payload: dict | None = None,
    *,
    home: Path,
    cwd: Path,
    raw: bytes | None = None,
    session: str | None = "probe-session",
    env_extra: dict[str, str] | None = None,
):
    """`--hook` with one payload on stdin, over a scratch HOME and a scratch cwd."""
    if raw is None:
        body: dict = {"cwd": str(cwd)}
        if session is not None:
            body["session_id"] = session
        body.update(payload or {})
        raw = json.dumps(body).encode("utf-8")
    env = _env(home)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", "--hook"],
        capture_output=True,
        cwd=str(cwd),
        env=env,
        input=raw,
        timeout=120,
    )


def _bed(tmp_path: Path, name: str) -> tuple[Path, Path]:
    home = tmp_path / name / "home"
    cwd = tmp_path / name / "cwd"
    home.mkdir(parents=True)
    cwd.mkdir(parents=True)
    return home, cwd


def _log_lines(home: Path) -> list[dict]:
    log = home / ".bantamkit" / "hooks" / "hook-log.jsonl"
    text = log.read_text(encoding="utf-8").strip()
    return [json.loads(line) for line in text.splitlines() if line]


def _save(store: Path, type_: str, name: str, description: str, body: str) -> None:
    from bantamkit.memory.component import Memory

    Memory(store=store).save(type_, name, description, body)


# --- 1. the parser surface --------------------------------------------------------------


def test_hook_is_on_the_parser_and_in_the_help_table(tmp_path):
    """The flag exists on THIS runtime's parser and prints in THIS runtime's `-h`.

    `runtime-ts/test/hookadapter.test.mjs` pins the same two facts on the other side; the
    conformance `cli` suite compares the two outputs byte for byte.
    """
    home, cwd = _bed(tmp_path, "help")
    done = _run_cli(["-h"], home=home, cwd=cwd, env_extra={"COLUMNS": "80"})

    assert done.returncode == 0
    assert done.stderr == b""
    text = done.stdout.decode()
    assert "[--hook]" in text, "the usage block names the flag"
    assert any(line.startswith("  --hook") for line in text.splitlines()), text


def test_the_pinned_first_usage_line_is_byte_identical_at_columns_80(tmp_path):
    """Registering after `--index-budget` leaves the PINNED line alone.

    This same string is asserted in `test_mcpserver.py`, `test_mcpreport.py`,
    `test_selfupdate.py`, `runtime-ts/test/cli-surface.test.mjs` and as a THROWING
    precondition in `tools/conformance/suites/cli.mjs`. A flag registered any earlier moves
    it and turns a differential suite into a re-baselining one.
    """
    home, cwd = _bed(tmp_path, "usage")
    done = _run_cli(["-h"], home=home, cwd=cwd, env_extra={"COLUMNS": "80"})

    first = done.stdout.decode().splitlines()[0]
    assert first == "usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES]"


def test_the_help_sentence_is_the_one_the_other_runtime_prints(tmp_path):
    """One sentence, spelled once. The conformance suite compares these bytes."""
    home, cwd = _bed(tmp_path, "sentence")
    done = _run_cli(["-h"], home=home, cwd=cwd, env_extra={"COLUMNS": "200"})

    assert "run as a Claude Code hook: one JSON event on stdin, then exit" in done.stdout.decode()


def test_hook_defaults_off_so_a_bare_invocation_still_serves(tmp_path):
    """The production invocation passes no arguments. It must not become a hook."""
    sys.path.insert(0, str(SRC))
    from bantamkit.mcpserver import _parse_args

    assert _parse_args([]).hook is False
    assert _parse_args(["--hook"]).hook is True


def test_the_event_comes_from_stdin_and_never_from_argv(tmp_path):
    """The flag is BARE. A second spelling of the event on the command line would be a
    second thing to keep in step with the host, and the registration would need seven
    commands instead of one."""
    home, cwd = _bed(tmp_path, "positional")
    done = _run_cli(["--hook", "SessionStart"], home=home, cwd=cwd)

    assert done.returncode == 2, done


_WITHOUT_SDK = (
    "import runpy, sys; sys.modules['mcp'] = None; sys.modules['pydantic'] = None; "
    "runpy.run_module('bantamkit.mcpserver', run_name='__main__', alter_sys=True)"
)


@pytest.mark.parametrize(
    ("flag", "stdin"),
    [
        ("--hook", b'{"hook_event_name": "PostCompact", "session_id": "s"}'),
        ("--statusline", b"{}"),
        ("--mcp-report", b""),
    ],
)
def test_the_host_registered_arms_run_without_the_mcp_extra(tmp_path, flag, stdin):
    """job66/#173: a plain `pip install bantamkit` has no `mcp` and no `pydantic`.

    `--hook`, `--statusline` and `--mcp-report` build no server, so they must run there; the
    SDK check used to sit before `_parse_args()` and answered all three `exit 1` with the
    install hint on every host event. `sys.modules[...] = None` is what an absent package looks
    like to an import. The bare server is the control: it still refuses, with the hint.
    """
    home, cwd = _bed(tmp_path, flag.strip("-"))
    run = lambda argv, raw: subprocess.run(  # noqa: E731
        [sys.executable, "-c", _WITHOUT_SDK, *argv],
        capture_output=True,
        cwd=str(cwd),
        env=_env(home),
        input=raw,
        timeout=120,
    )
    done = run([flag], stdin)
    assert done.returncode == 0, done.stderr
    assert b"needs the MCP extra" not in done.stderr

    control = run([], b"")
    assert control.returncode == 1
    assert b'needs the MCP extra: pip install "bantamkit[mcp]"' in control.stderr


# --- 2. the contract --------------------------------------------------------------------


def test_session_start_emits_exactly_one_json_object_and_exits_zero(tmp_path):
    home, cwd = _bed(tmp_path, "sessionstart")
    done = _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)

    assert done.returncode == 0, done.stderr
    out = done.stdout.decode()
    parsed = json.loads(out)  # a concatenation of two objects would raise here
    assert parsed["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "[bantamkit] Toolbox is live" in parsed["hookSpecificOutput"]["additionalContext"]
    assert out.strip() == out, "nothing trails the object either"
    assert done.stderr == b""


def test_the_adapter_logs_its_decision_under_the_scratch_home(tmp_path):
    home, cwd = _bed(tmp_path, "logged")
    _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)

    first = _log_lines(home)[0]
    assert first["event"] == "SessionStart"
    assert first["source"] == "startup"
    assert first["cwd"] == str(cwd)
    assert first["bytes"] > 0
    assert "ms" in first and "ts" in first


def test_a_payload_that_is_not_json_writes_nothing_and_still_exits_zero(tmp_path):
    home, cwd = _bed(tmp_path, "notjson")
    done = _run_hook(home=home, cwd=cwd, raw=b"not json")

    assert done.returncode == 0, done.stderr
    assert done.stdout == b""
    assert done.stderr == b""
    assert any(line["event"] == "parse-error" for line in _log_lines(home))


def test_an_event_the_adapter_does_not_serve_writes_nothing_and_exits_zero(tmp_path):
    home, cwd = _bed(tmp_path, "unknown")
    done = _run_hook({"hook_event_name": "WorktreeCreate"}, home=home, cwd=cwd)

    assert done.returncode == 0
    assert done.stdout == b""
    assert any(line.get("action") == "ignored" for line in _log_lines(home))


def test_an_arm_this_unit_did_not_port_is_recognised_and_degrades_visibly(tmp_path):
    """THE ASSERTED SET IS NOW EMPTY, and the test is kept for exactly that reason.

    J62-3 named the five arms it had not ported (`UNPORTED_EVENTS`) so that "bantamkit
    serves this event and has not ported it yet" and "this event is none of bantamkit's
    business" were two different lines in the log, and this case asserted that exact set of
    five. J62-3B landed all five, so the set the case asserts SHRANK to nothing -- it was
    not deleted, because deleting the gate as the last item leaves it is how a shrinking
    gate stops being able to fail. It can still fail: an arm quietly moved back into
    `UNPORTED_EVENTS`, or a sixth one added there, puts `action: "unported"` back on the log
    and this case goes red.

    The five must now be SERVED, which means each of them takes a real branch with a real
    action name -- never the `ignored` default either, because that is the other way a port
    could disappear without anything going red.
    """
    home, cwd = _bed(tmp_path, "unported")
    events = ("PreToolUse", "PostToolUse", "PreCompact", "PostCompact", "Stop")
    for event in events:
        done = _run_hook({"hook_event_name": event}, home=home, cwd=cwd)
        assert done.returncode == 0, (event, done.stderr)

    lines = _log_lines(home)
    unported = {line["event"] for line in lines if line.get("action") == "unported"}
    assert unported == set(), unported
    ignored = {line["event"] for line in lines if line.get("action") == "ignored"}
    assert ignored & set(events) == set(), ignored

    from bantamkit import hookadapter

    assert getattr(hookadapter, "UNPORTED_EVENTS", ()) == (), "the to-do list must be empty"


def test_an_empty_stdin_is_an_empty_object_not_a_crash(tmp_path):
    """`{}` parses, carries no event name, and takes the `ignored` arm. Exit 0."""
    home, cwd = _bed(tmp_path, "empty")
    done = _run_hook(home=home, cwd=cwd, raw=b"")

    assert done.returncode == 0, done.stderr
    assert done.stdout == b""
    assert done.stderr == b""


def test_a_json_array_on_stdin_is_not_an_event(tmp_path):
    """The contract is one JSON OBJECT. An array is not one, and it is not a crash either."""
    home, cwd = _bed(tmp_path, "array")
    done = _run_hook(home=home, cwd=cwd, raw=b"[1,2,3]")

    assert done.returncode == 0, done.stderr
    assert done.stdout == b""


# --- 3. SessionStart --------------------------------------------------------------------


def test_the_profile_index_is_injected_with_a_header_that_counts_it(tmp_path):
    home, cwd = _bed(tmp_path, "profile")
    _save(
        home / ".bantamkit" / "memory",
        "feedback",
        "measure-it",
        "every claim needs a rerunnable probe",
        "Count from printed output, never from grepping the source.",
    )

    done = _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)

    ctx = json.loads(done.stdout.decode())["hookSpecificOutput"]["additionalContext"]
    # AMENDED job65 (#188): this pinned "1 facts". The issue is the newer ruling -- one fact
    # is "1 fact" -- and both runtimes now say so (conformance `hook-degrade`).
    assert "[bantamkit profile memory — 1 fact learned across projects]" in ctx
    assert "- [[measure-it]] (feedback) — every claim needs a rerunnable probe" in ctx
    assert _log_lines(home)[0]["profileFacts"] == 1
    assert _log_lines(home)[0]["profileInjected"] == 1


def test_a_project_store_beside_the_cwd_is_injected_too(tmp_path):
    home, cwd = _bed(tmp_path, "project")
    _save(
        cwd / ".bantamkit" / "memory",
        "project",
        "the-project-fact",
        "what this checkout is for",
        "A body nobody reads at SessionStart.",
    )

    done = _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)

    ctx = json.loads(done.stdout.decode())["hookSpecificOutput"]["additionalContext"]
    # AMENDED job65 (#188): this pinned "1 facts"; one fact is "1 fact" now.
    assert "[bantamkit project memory — 1 fact]" in ctx
    assert "- [[the-project-fact]] (project) — what this checkout is for" in ctx
    line = _log_lines(home)[0]
    assert line["projectFacts"] == 1
    assert line["projectInjected"] == 1
    assert line["dropRule"] == (
        "durable types first, then most recently recalled (else created) first, then name"
    )


def test_the_capped_block_discloses_what_it_dropped_instead_of_dropping_it_silently(tmp_path):
    """The cap is in BYTES and the drop is by rule, not by alphabet.

    A block that simply truncated would say "20 facts" above 15 of them. The header counts
    what is IN the block, and the disclosure line names how many are missing and where they
    can be read.
    """
    home, cwd = _bed(tmp_path, "capped")
    store = home / ".bantamkit" / "memory"
    for i in range(40):
        # Every description is lexically DISJOINT from every other, or `store.save` refuses
        # the second one as a duplicate (`DUPLICATE_JACCARD = 0.5` over name+description
        # tokens) and this bed would hold ten facts while claiming forty.
        _save(
            store,
            "project",
            f"fact-{i:02d}",
            " ".join(f"word{i:02d}x{j:02d}" for j in range(12)),
            "body",
        )
    assert len(list((store / "facts").glob("*.md"))) == 40, "the bed itself must hold 40"

    done = _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)

    ctx = json.loads(done.stdout.decode())["hookSpecificOutput"]["additionalContext"]
    header = ctx.splitlines()[0]
    assert " of 40 facts learned across projects]" in header, header
    assert "not shown — the block is capped at 3000 bytes" in ctx
    assert "kept by rule: durable types first" in ctx
    line = _log_lines(home)[0]
    assert 0 < line["profileInjected"] < 40
    assert len(line["profileDropped"]) == 40 - line["profileInjected"]


def test_source_compact_clears_the_read_ledger_so_earlier_reads_are_not_refused(tmp_path):
    home, cwd = _bed(tmp_path, "compactsource")
    ledger = home / ".bantamkit" / "hooks" / "ledger-probe-session.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"reads": {"a": {"sig": "s"}}}), encoding="utf-8")

    done = _run_hook({"hook_event_name": "SessionStart", "source": "compact"}, home=home, cwd=cwd)

    assert done.returncode == 0
    assert not ledger.exists(), "context was rebuilt, so the ledger must not refuse old reads"


def test_a_startup_session_leaves_the_read_ledger_alone(tmp_path):
    """The pair. Only `source: compact` clears it -- a constant unlink would pass the test
    above and destroy a live session's ledger on every start."""
    home, cwd = _bed(tmp_path, "startupledger")
    ledger = home / ".bantamkit" / "hooks" / "ledger-probe-session.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"reads": {"a": {"sig": "s"}}}), encoding="utf-8")

    _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)

    assert ledger.exists()


def test_session_start_writes_nothing_outside_the_scratch_home_and_cwd(tmp_path):
    """A hook that created a store in whatever directory it was spawned in would be the
    `--assets-root` discipline broken: nothing here may bring a store into existence."""
    home, cwd = _bed(tmp_path, "nowrite")
    _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)

    assert not (cwd / ".bantamkit").exists(), "no store was asked for, so none is created"
    assert sorted(p.name for p in (home / ".bantamkit").iterdir()) == ["hooks"]


# --- 4. UserPromptSubmit ----------------------------------------------------------------


def test_a_matching_prompt_injects_recall_HEADERS_and_not_bodies(tmp_path):
    home, cwd = _bed(tmp_path, "prompt")
    _save(
        cwd / ".bantamkit" / "memory",
        "reference",
        "conformance-gate",
        "the gate is zero failures, never a total",
        "THE BODY, which costs ~1.5 KB a fact and must not be injected.",
    )

    done = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "what is the conformance gate here"},
        home=home,
        cwd=cwd,
    )

    assert done.returncode == 0, done.stderr
    ctx = json.loads(done.stdout.decode())["hookSpecificOutput"]["additionalContext"]
    assert "[bantamkit recall — memories that match this prompt" in ctx
    assert "[conformance-gate] (reference) the gate is zero failures, never a total" in ctx
    assert "THE BODY" not in ctx, "the body is what makes this arm expensive; only headers go"

    line = _log_lines(home)[0]
    assert line["event"] == "UserPromptSubmit"
    assert line["action"] == "inject"
    assert line["hits"] == 1
    assert line["session"] == "probe-session"
    assert [x["name"] for x in line["injected"]] == ["conformance-gate"]
    assert line["injected"][0]["score"] >= 1
    assert line["dropped"] == 0


def test_an_injection_leaves_every_fact_file_byte_and_mtime_identical(tmp_path, monkeypatch):
    """AN INJECTION IS NOT A RECALL (job64, J64-1). Until this job the arm went through
    `Memory.recall_outcome` with the component's default `stamp`, so every automatic
    injection dated up to three facts `last_recalled: <today>` and rewrote their files —
    25 of 42 facts in one real store carried one day's date, and every rule keyed on that
    field (compaction's stalest-first, the SessionStart drop rule, the Stop dream's
    `size + mtime` fingerprint) was reading injection traffic. The control at the end is the
    explicit path on the SAME bed, which must still stamp: without it a bed whose recall
    never reached the file would pass this test for the wrong reason."""
    home, cwd = _bed(tmp_path, "nostamp")
    store = cwd / ".bantamkit" / "memory"
    _save(store, "reference", "conformance-gate", "the gate is zero failures, never a total", "b")
    _save(store, "project", "unrelated", "a fact sharing no token with that prompt", "body")

    def state() -> dict[str, tuple[bytes, int]]:
        facts = sorted((store / "facts").glob("*.md"))
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in facts}

    before = state()
    assert b"last_recalled: null" in before["conformance-gate.md"][0]

    done = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "what is the conformance gate here"},
        home=home,
        cwd=cwd,
    )

    assert done.returncode == 0, done.stderr
    line = _log_lines(home)[0]
    assert (line["action"], line["hits"]) == ("inject", 1), "the arm must have READ the store"
    ctx = json.loads(done.stdout.decode())["hookSpecificOutput"]["additionalContext"]
    assert "[conformance-gate]" in ctx
    assert state() == before, "an injection rewrote a fact file, or moved its mtime"

    from bantamkit.memory.usage import UsageLedger

    ledger = UsageLedger(home, store).path
    assert not ledger.exists(), "an injection wrote a usage event (#199: the hook writes nothing)"

    # CONTROL: the explicit path, on the same bed, still stamps — and only the hit. #199 D5:
    # the stamp is a `recall_hit` in the usage ledger, and NO fact file moves. WAS:
    # `last_recalled` was dated in conformance-gate.md.
    from bantamkit.memory.component import Memory

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    Memory(store=store).recall("what is the conformance gate here")
    assert state() == before
    events = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines()]
    assert [(e["fact"], e["kind"]) for e in events] == [("conformance-gate", "recall_hit")]


def test_the_prompt_is_logged_as_a_fingerprint_and_never_as_text(tmp_path):
    """THE LOG PERSISTS TO DISK AND THE PROMPTS ARE THE USER'S. A sha256 and two sizes;
    no substring of the prompt at any length."""
    import hashlib

    home, cwd = _bed(tmp_path, "fingerprint")
    _save(
        cwd / ".bantamkit" / "memory",
        "reference",
        "conformance-gate",
        "the gate is zero failures",
        "body",
    )
    prompt = "what is the conformance gate SENTINELWORD here"

    _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": prompt}, home=home, cwd=cwd
    )

    raw = (home / ".bantamkit" / "hooks" / "hook-log.jsonl").read_text(encoding="utf-8")
    assert "SENTINELWORD" not in raw
    fp = json.loads(raw.splitlines()[0])["prompt"]
    assert fp["sha256"] == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert fp["chars"] == len(prompt)
    assert fp["bytes"] == len(prompt.encode("utf-8"))


def test_a_short_prompt_or_a_slash_command_is_skipped_before_a_store_is_touched(tmp_path):
    home, cwd = _bed(tmp_path, "skip")
    _save(cwd / ".bantamkit" / "memory", "reference", "a-fact", "a description", "body")

    for prompt in ("hi", "/compact now please"):
        done = _run_hook(
            {"hook_event_name": "UserPromptSubmit", "prompt": prompt}, home=home, cwd=cwd
        )
        assert done.returncode == 0
        assert done.stdout == b"", prompt

    actions = [line.get("reason") for line in _log_lines(home)]
    assert actions == ["short-or-command", "short-or-command"], actions


def test_a_prompt_that_matches_nothing_injects_nothing(tmp_path):
    home, cwd = _bed(tmp_path, "nomatch")
    done = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "a prompt about nothing at all"},
        home=home,
        cwd=cwd,
    )

    assert done.returncode == 0
    assert done.stdout == b""
    line = _log_lines(home)[0]
    assert line["action"] == "none"
    assert line["status"] != "answered"


def test_the_injected_block_is_capped_in_bytes_and_the_log_counts_what_left(tmp_path):
    """`injected` is read back off the emitted block, not off what recall picked: a header
    the cap dropped never reached the model, and a log that claimed it would poison the
    question "was an injected name later used"."""
    home, cwd = _bed(tmp_path, "promptcap")
    store = cwd / ".bantamkit" / "memory"
    for i in range(3):
        # They must all MATCH the prompt and none of them may be a duplicate of another, so
        # each shares the query's words and is otherwise disjoint (`DUPLICATE_JACCARD`).
        _save(
            store,
            "reference",
            f"conformance-gate-{i}",
            "the conformance gate is zero failures never a total "
            + " ".join(f"filler{i}n{j:02d}" for j in range(20)),
            "body",
        )
    assert len(list((store / "facts").glob("*.md"))) == 3, "the bed itself must hold 3"

    done = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "what is the conformance gate here"},
        home=home,
        cwd=cwd,
    )

    ctx = json.loads(done.stdout.decode())["hookSpecificOutput"]["additionalContext"]
    assert len(ctx.encode("utf-8")) <= 700
    line = _log_lines(home)[0]
    assert line["hits"] == 3
    assert line["dropped"] == line["hits"] - len(line["injected"])
    assert line["dropped"] > 0


# --- 4b. UserPromptSubmit — what this context was shown is not shown again (job64, J64-2) --
#
# Measured 2026-09-25 over a week of the real log: 333 of 598 injections repeated a name
# injected earlier in the same session, because the arm never read the session ledger. The
# bed is the conformance suite's `inject-dedupe` bed, so a number pinned here is the number
# pinned there. Every test below went RED with the seen-set forced empty on this side
# (`seen = {}` in `_user_prompt_submit`); counts in `.shiftwork/notes-job64/J64-2.md`.

_DEDUPE_FACTS = [
    (
        "project",
        "deployment-rollback",
        "the deployment path rollback procedure for the staging cluster",
    ),
    ("project", "staging-cluster-notes", "wiring notes kept about the staging cluster nodes"),
    ("project", "rollback-runbook", "runbook steps when a rollback of the deployment is needed"),
    ("reference", "unrelated-alpha", "nothing shared here at all"),
    ("reference", "unrelated-beta", "still nothing in common with anything"),
]
#: Hits the three `deployment`/`rollback`/`staging` facts, in `_A_NAMES` order.
_PROMPT_A = "deployment path rollback procedure for the staging cluster"
#: Hits `unrelated-alpha` first and then two of A's three, measured through `Memory.layered`
#: on this bed -- so after A it is the MIXED case: one unseen header, two seen.
_PROMPT_C = "nothing shared here at all about the staging cluster"
# #199 D3: the order is BM25F's now -- `staging-cluster-notes` (shorter, and `staging` and
# `cluster` are rarer than `rollback`) outranks `rollback-runbook`. WAS: v1 overlap scores
# 8, 3, 3, the tie broken by name.
_A_NAMES = ["deployment-rollback", "staging-cluster-notes", "rollback-runbook"]


def _dedupe_bed(tmp_path: Path, name: str, facts=_DEDUPE_FACTS) -> tuple[Path, Path]:
    home, cwd = _bed(tmp_path, name)
    for type_, fact, description in facts:
        _save(cwd / ".bantamkit" / "memory", type_, fact, description, "body")
    return home, cwd


def _prompt(
    home: Path, cwd: Path, text: str, *, session="probe-session", transcript="/t/main.jsonl"
):
    done = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": text, "transcript_path": transcript},
        home=home,
        cwd=cwd,
        session=session,
    )
    assert done.returncode == 0, done.stderr
    return done


def _prompt_records(home: Path) -> list[dict]:
    return [x for x in _log_lines(home) if x["event"] == "UserPromptSubmit"]


def test_a_name_this_context_was_shown_is_not_injected_again_and_the_record_says_why(tmp_path):
    """(a) The same prompt twice in one context: the second time NOTHING leaves, and the
    record is not a silent `none` -- it names what was withheld."""
    home, cwd = _dedupe_bed(tmp_path, "dedupe-same")
    first = _prompt(home, cwd, _PROMPT_A)
    second = _prompt(home, cwd, _PROMPT_A)

    assert first.stdout != b""
    assert second.stdout == b"", "every picked header was already in the window"
    one, two = _prompt_records(home)
    assert one["action"] == "inject"
    assert one["suppressed"] == []
    assert two["action"] == "suppress"
    assert two["suppressed"] == _A_NAMES
    assert two["hits"] == 3
    assert two["session"] == "probe-session"
    assert set(two["prompt"]) == {"sha256", "chars", "bytes"}, "the fingerprint, never text"
    ledger = _ledger(home)
    assert list(ledger["injected"]["/t/main.jsonl"]) == _A_NAMES, "seen = what LEFT, by name"
    assert ledger["reads"] == {}, "the read ledger is untouched by an injection"


# (job64, J64-8, the J64-7 blocker) `constructor` is the one `Object.prototype` key `NAME_RE`
# admits. The port's seen-set is a plain JSON object, and a membership test written with `in`
# found the prototype's `constructor` on a FRESH context, so the two runtimes disagreed on the
# first prompt over the same store. This side's dict never had the defect; the test is the
# reference half of the per-side pin, green before and after the port's fix
# (`.shiftwork/notes-job64/J64-8.md`).
_CTOR_FACTS = [
    ("project", "constructor", "the widget constructor rollout checklist for staging"),
    (
        "project",
        "widget-rollout-notes",
        "notes on the widget rollout timing for the staging window",
    ),
    ("reference", "unrelated-alpha", "nothing shared here at all"),
]
#: Hits `constructor` then `widget-rollout-notes`, and not `unrelated-alpha` (measured).
_PROMPT_CTOR = "the widget constructor rollout checklist for staging"
_CTOR_NAMES = ["constructor", "widget-rollout-notes"]


def test_a_fact_named_constructor_is_injected_first_and_suppressed_second(tmp_path):
    """(g) A fact whose name is an `Object.prototype` member is shown to a fresh context like
    any other, and withheld only once it has actually been shown."""
    home, cwd = _dedupe_bed(tmp_path, "dedupe-constructor", _CTOR_FACTS)
    first = _prompt(home, cwd, _PROMPT_CTOR)
    second = _prompt(home, cwd, _PROMPT_CTOR)

    assert first.stdout != b""
    assert second.stdout == b"", "both picked headers were already in the window"
    one, two = _prompt_records(home)
    assert one["action"] == "inject"
    assert one["hits"] == 2
    assert [x["name"] for x in one["injected"]] == _CTOR_NAMES
    assert one["suppressed"] == [], "nothing withheld from a context that had been shown nothing"
    assert two["action"] == "suppress"
    assert two["hits"] == 2
    assert two["suppressed"] == _CTOR_NAMES
    ledger = _ledger(home)
    assert list(ledger["injected"]["/t/main.jsonl"]) == _CTOR_NAMES, "seen = what LEFT, by name"


def test_a_different_session_is_not_suppressed_by_what_another_was_shown(tmp_path):
    """(b) Sessions do not see each other's seen-sets."""
    home, cwd = _dedupe_bed(tmp_path, "dedupe-session")
    _prompt(home, cwd, _PROMPT_A, session="one", transcript="/t/one.jsonl")
    other = _prompt(home, cwd, _PROMPT_A, session="two", transcript="/t/two.jsonl")

    assert other.stdout != b""
    assert [x["action"] for x in _prompt_records(home)] == ["inject", "inject"]
    assert list(_ledger(home, "two")["injected"]) == ["/t/two.jsonl"]


def test_a_compaction_forgets_what_was_shown_so_it_is_injected_again(tmp_path):
    """(c) After PostCompact the window was rebuilt from a summary and the headers are gone,
    so re-injecting is correct, not a leak. The suppress in the middle is the control: without
    it a hook that never suppressed would pass this test."""
    home, cwd = _dedupe_bed(tmp_path, "dedupe-compact")
    _prompt(home, cwd, _PROMPT_A)
    assert _prompt(home, cwd, _PROMPT_A).stdout == b""
    _run_hook({"hook_event_name": "PostCompact"}, home=home, cwd=cwd)
    again = _prompt(home, cwd, _PROMPT_A)

    assert again.stdout != b""
    assert [x["action"] for x in _prompt_records(home)] == ["inject", "suppress", "inject"]


def test_only_the_unseen_headers_are_injected_when_some_were_shown_before(tmp_path):
    """(d) The mixed case: the seen headers are DROPPED, the budget is not refilled, and the
    record's arithmetic closes: `hits == injected + dropped + suppressed`."""
    home, cwd = _dedupe_bed(tmp_path, "dedupe-mixed")
    _prompt(home, cwd, _PROMPT_A)
    mixed = _prompt(home, cwd, _PROMPT_C)

    ctx = json.loads(mixed.stdout.decode())["hookSpecificOutput"]["additionalContext"]
    assert "[unrelated-alpha]" in ctx
    for name in _A_NAMES:
        assert f"[{name}]" not in ctx, f"{name} was already in the window"
    rec = _prompt_records(home)[1]
    assert rec["action"] == "inject"
    assert [x["name"] for x in rec["injected"]] == ["unrelated-alpha"]
    assert rec["suppressed"] == ["staging-cluster-notes", "deployment-rollback"]
    assert rec["hits"] == 3, "the store was still asked for three; two were withheld, not refilled"
    assert rec["dropped"] == 0
    assert rec["hits"] == len(rec["injected"]) + rec["dropped"] + len(rec["suppressed"])
    seen = _ledger(home)["injected"]["/t/main.jsonl"]
    assert sorted(seen) == sorted([*_A_NAMES, "unrelated-alpha"]), "what just left is seen now too"


def test_clear_forgets_what_was_shown_and_startup_does_not(tmp_path):
    """(e) `/clear` empties the window like a compaction; `startup` is the control, since a
    constant reset on SessionStart would pass the `clear` half alone. `clear` touches ONLY the
    seen-set: the read entries in the same file survive it."""
    home, cwd = _dedupe_bed(tmp_path, "dedupe-clear")
    target = cwd / "a.txt"
    target.write_text("alpha", encoding="utf-8")
    _run_hook(_read_payload(target, transcript="/t/main.jsonl"), home=home, cwd=cwd)
    _prompt(home, cwd, _PROMPT_A)
    _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)
    assert _prompt(home, cwd, _PROMPT_A).stdout == b"", "startup is not a rebuilt window"
    _run_hook({"hook_event_name": "SessionStart", "source": "clear"}, home=home, cwd=cwd)

    after_clear = _ledger(home)
    assert "injected" not in after_clear
    assert len(after_clear["reads"]) == 1, "the reads are the read ledger's business, not clear's"
    assert _prompt(home, cwd, _PROMPT_A).stdout != b""
    assert [x["action"] for x in _prompt_records(home)] == ["inject", "suppress", "inject"]


def test_clear_with_no_ledger_creates_none(tmp_path):
    home, cwd = _bed(tmp_path, "dedupe-clear-none")
    done = _run_hook({"hook_event_name": "SessionStart", "source": "clear"}, home=home, cwd=cwd)

    assert done.returncode == 0
    assert not (home / ".bantamkit" / "hooks" / "ledger-probe-session.json").exists()


def test_a_subagent_transcript_keeps_its_own_seen_set_in_the_parents_ledger(tmp_path):
    """(f) A subagent shares the parent's `session_id` and so the parent's ledger FILE
    (J64-0, Q3 step 11), but its window never held the parent's headers -- so it is keyed by
    `transcript_path`, like `reads`. And the parent is still suppressed afterwards."""
    home, cwd = _dedupe_bed(tmp_path, "dedupe-subagent")
    _prompt(home, cwd, _PROMPT_A, transcript="/t/parent.jsonl")
    child = _prompt(home, cwd, _PROMPT_A, transcript="/t/child.jsonl")
    parent_again = _prompt(home, cwd, _PROMPT_A, transcript="/t/parent.jsonl")

    assert child.stdout != b"", "the subagent's window never held the parent's headers"
    assert parent_again.stdout == b""
    assert [x["action"] for x in _prompt_records(home)] == ["inject", "inject", "suppress"]
    assert sorted(_ledger(home)["injected"]) == ["/t/child.jsonl", "/t/parent.jsonl"]


# --- 5. PreToolUse[Read] — the filegraph over the operator's own reads --------------------


def _ledger(home: Path, session: str = "probe-session") -> dict:
    path = home / ".bantamkit" / "hooks" / f"ledger-{session}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _read_payload(file: Path, *, transcript: str = "/t/parent.jsonl", **extra) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "transcript_path": transcript,
        "tool_input": {"file_path": str(file), **extra},
    }


def test_a_first_read_is_recorded_and_never_refused(tmp_path):
    """The gate costs nothing on a read it has not seen: no stdout, one ledger entry."""
    home, cwd = _bed(tmp_path, "read-first")
    target = cwd / "a.txt"
    target.write_text("alpha", encoding="utf-8")

    done = _run_hook(_read_payload(target), home=home, cwd=cwd)

    assert done.returncode == 0, done.stderr
    assert done.stdout == b"", "a first read is never refused"
    line = _log_lines(home)[0]
    assert line == {**line, "event": "PreToolUse", "action": "record", "file": str(target)}
    assert line["size"] == 5
    assert len(_ledger(home)["reads"]) == 1


def test_an_identical_repeat_read_of_an_unchanged_file_is_refused_exactly_once(tmp_path):
    """REFUSES ONCE. The second identical call is denied; the third goes through, so
    nothing the model genuinely needs can be hard-blocked."""
    home, cwd = _bed(tmp_path, "read-repeat")
    target = cwd / "a.txt"
    target.write_text("alpha", encoding="utf-8")
    payload = _read_payload(target)

    first = _run_hook(payload, home=home, cwd=cwd)
    second = _run_hook(payload, home=home, cwd=cwd)
    third = _run_hook(payload, home=home, cwd=cwd)

    assert first.stdout == b""
    out = json.loads(second.stdout.decode())["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    assert str(target) in out["permissionDecisionReason"]
    assert "unchanged on disk (same mtime and size)" in out["permissionDecisionReason"]
    assert "fires only once per unchanged file" in out["permissionDecisionReason"]
    assert third.stdout == b"", "the refusal fires once; the repeat after it goes through"
    actions = [line["action"] for line in _log_lines(home)]
    assert actions == ["record", "refuse", "allow-after-refuse-or-change"], actions


def test_directory_reads_are_never_ledgered_or_refused(tmp_path):
    home, cwd = _bed(tmp_path, "read-directory")
    target = cwd / "a.txt"
    target.write_text("alpha", encoding="utf-8")
    _run_hook(_read_payload(target), home=home, cwd=cwd)
    before = _ledger(home)

    for _ in range(2):
        done = _run_hook(_read_payload(cwd), home=home, cwd=cwd)
        assert done.returncode == 0, done.stderr
        assert done.stdout == b"", "a failed directory read has no reusable content"
        assert _ledger(home) == before


def test_a_file_that_changed_on_disk_re_arms_the_gate(tmp_path):
    """mtime+size is the signature. An edit between the two reads is a different file."""
    home, cwd = _bed(tmp_path, "read-changed")
    target = cwd / "a.txt"
    target.write_text("alpha", encoding="utf-8")
    payload = _read_payload(target)

    _run_hook(payload, home=home, cwd=cwd)
    target.write_text("alpha and then some", encoding="utf-8")
    second = _run_hook(payload, home=home, cwd=cwd)

    assert second.stdout == b"", "the file changed, so the earlier read is not reusable"
    assert [line["action"] for line in _log_lines(home)] == [
        "record",
        "allow-after-refuse-or-change",
    ]


def test_a_subagent_transcript_is_never_refused_for_the_parents_read(tmp_path):
    """The CONTEXT dimension. A subagent has its own transcript and has not seen the
    parent's read, so refusing it would deny content that context never held."""
    home, cwd = _bed(tmp_path, "read-subagent")
    target = cwd / "a.txt"
    target.write_text("alpha", encoding="utf-8")

    _run_hook(_read_payload(target, transcript="/t/parent.jsonl"), home=home, cwd=cwd)
    child = _run_hook(_read_payload(target, transcript="/t/child.jsonl"), home=home, cwd=cwd)

    assert child.stdout == b""
    assert len(_ledger(home)["reads"]) == 2, "two contexts, two entries"


def test_the_offset_and_limit_are_part_of_the_key_not_of_the_file(tmp_path):
    """A partial read of the same file is a different read, and the refusal says which."""
    home, cwd = _bed(tmp_path, "read-offset")
    target = cwd / "a.txt"
    target.write_text("alpha", encoding="utf-8")
    payload = _read_payload(target, offset=10, limit=5)

    _run_hook(_read_payload(target), home=home, cwd=cwd)
    other = _run_hook(payload, home=home, cwd=cwd)
    again = _run_hook(payload, home=home, cwd=cwd)

    assert other.stdout == b"", "a different slice of the file is a different read"
    reason = json.loads(again.stdout.decode())["hookSpecificOutput"]["permissionDecisionReason"]
    assert "(offset 10, limit 5)" in reason, reason


def test_a_tool_that_is_not_read_is_not_the_filegraphs_business(tmp_path):
    """Only `Read` reaches the arm. A Bash call is recorded as a usage event and nothing
    else -- no ledger entry, no refusal, ever."""
    home, cwd = _bed(tmp_path, "read-othertool")
    metrics = tmp_path / "read-othertool" / "metrics"

    done = _run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        },
        home=home,
        cwd=cwd,
        env_extra={"TOOL_METRICS_DIR": str(metrics)},
    )

    assert done.returncode == 0
    assert done.stdout == b""
    assert not (home / ".bantamkit" / "hooks" / "ledger-probe-session.json").exists()


def test_a_missing_file_lets_read_produce_its_own_error(tmp_path):
    """The hook does not pre-empt the tool's own diagnostic."""
    home, cwd = _bed(tmp_path, "read-missing")

    done = _run_hook(_read_payload(cwd / "nope.txt"), home=home, cwd=cwd)

    assert done.returncode == 0
    assert done.stdout == b""
    assert not (home / ".bantamkit" / "hooks" / "ledger-probe-session.json").exists()


def test_an_unchanged_file_is_refused_once_and_then_every_repeat_goes_through(tmp_path):
    """#166 (job65, J65-4). The allowed retry used to write `refused: False` back, which
    re-armed the gate: six reads went allow, deny, allow, deny, allow, deny while the
    refusal told the model it "fires only once per unchanged file". The docs' sentence
    holds now: one refusal, then every identical repeat goes through until an edit re-arms
    it. RED on the pre-fix adapter at 64ae11d: `allow,deny,allow,deny,allow,deny`."""
    home, cwd = _bed(tmp_path, "read-once")
    target = cwd / "a.txt"
    target.write_text("alpha", encoding="utf-8")
    payload = _read_payload(target)

    def read() -> str:
        return "deny" if _run_hook(payload, home=home, cwd=cwd).stdout else "allow"

    decisions = [read() for _ in range(6)]
    target.write_text("alpha and then some", encoding="utf-8")
    after_edit = [read() for _ in range(3)]

    assert decisions == ["allow", "deny", "allow", "allow", "allow", "allow"], decisions
    assert after_edit == ["allow", "deny", "allow"], after_edit
    assert [line["action"] for line in _log_lines(home)] == [
        "record",
        "refuse",
        *(["allow-after-refuse-or-change"] * 4),
        "allow-after-refuse-or-change",  # the edit: a new signature is a new read
        "refuse",
        "allow-after-refuse-or-change",
    ]
    (record,) = _ledger(home)["reads"].values()
    assert record["refused"] is True, "the refusal stays spent until the signature changes"
    assert record["count"] == 9, "the count is cumulative across signature changes"


def test_a_directory_is_never_ledgered_and_its_retry_is_never_refused(tmp_path):
    """#190 (job65, J65-4). A directory stats fine, so it was ledgered and the second Read
    refused with "use the content from that earlier read" -- content the host never
    produced, because the first Read failed with EISDIR. Not a regular file: not
    ledgered, like a missing path. RED at 64ae11d: the second run emitted a deny."""
    home, cwd = _bed(tmp_path, "read-directory")
    (cwd / "sub").mkdir()

    first = _run_hook(_read_payload(cwd / "sub"), home=home, cwd=cwd)
    second = _run_hook(_read_payload(cwd / "sub"), home=home, cwd=cwd)

    assert first.returncode == 0 and second.returncode == 0
    assert first.stdout == b"" and second.stdout == b"", "a directory read is never refused"
    hooks = home / ".bantamkit" / "hooks"
    assert not (hooks / "ledger-probe-session.json").exists(), "never ledgered"
    # Like a missing path, nothing is logged either: the arm returns before its log line.
    assert not (hooks / "hook-log.jsonl").exists()


def test_parallel_reads_of_distinct_files_lose_no_ledger_entry(tmp_path):
    """#167 (job65, J65-4). One hook PROCESS per tool call, and a parallel tool block fires
    them at once: twenty processes each read the ledger, add one entry and write the whole
    file back, and the last writer wins. Measured at 64ae11d over 20 files: 16 of 20
    entries survived on this side, 6 of 20 on the port. The read-modify-write now runs
    under `<ledger>.lock` and writes through a rename, so all 20 land and no lock is left."""
    home, cwd = _bed(tmp_path, "read-parallel")
    files = [cwd / f"p{i}.txt" for i in range(20)]
    for i, f in enumerate(files):
        f.write_text(f"{i}\n", encoding="utf-8")
    env = _env(home)
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "bantamkit.mcpserver", "--hook"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            env=env,
        )
        for _ in files
    ]
    bodies = [
        json.dumps({"cwd": str(cwd), "session_id": "probe-session", **_read_payload(f)})
        for f in files
    ]
    outs = [
        p.communicate(input=b.encode("utf-8"), timeout=120)
        for p, b in zip(procs, bodies, strict=True)
    ]

    assert [p.returncode for p in procs] == [0] * 20
    assert all(out == b"" for out, _err in outs), "distinct files: nothing is refused"
    assert len(_ledger(home)["reads"]) == 20, "every parallel read is ledgered"
    hooks = home / ".bantamkit" / "hooks"
    assert not (hooks / "ledger-probe-session.json.lock").exists(), "the lock is released"
    assert [n for n in os.listdir(hooks) if n.endswith(".tmp")] == [], "no temp file is left"


# --- 6. PostToolUse — the usage events log -----------------------------------------------


def _events(metrics: Path) -> list[dict]:
    text = (metrics / "events.jsonl").read_text(encoding="utf-8").strip()
    return [json.loads(line) for line in text.splitlines() if line]


def test_every_tool_call_appends_one_usage_event_line(tmp_path):
    """The durable copy behind the transcript: one line per tool call, whatever the tool."""
    home, cwd = _bed(tmp_path, "usage")
    metrics = tmp_path / "usage" / "metrics"

    done = _run_hook(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Skill",
            "tool_use_id": "tu-1",
            "tool_input": {"skill": "artifact-design"},
        },
        home=home,
        cwd=cwd,
        env_extra={"TOOL_METRICS_DIR": str(metrics)},
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout == b""
    record = _events(metrics)[0]
    assert record["tool"] == "Skill"
    assert record["server"] == "builtin"
    assert record["detail"] == "artifact-design"
    assert record["session"] == "probe-session"
    assert record["tool_use_id"] == "tu-1"
    assert record["project"] == str(cwd).replace("/", "-")


def test_the_server_field_names_the_mcp_server_and_the_agent_detail_defaults(tmp_path):
    home, cwd = _bed(tmp_path, "usage-server")
    metrics = tmp_path / "usage-server" / "metrics"
    extra = {"TOOL_METRICS_DIR": str(metrics)}

    _run_hook(
        {"hook_event_name": "PostToolUse", "tool_name": "mcp__bantamkit__memory_recall"},
        home=home,
        cwd=cwd,
        env_extra=extra,
    )
    _run_hook(
        {"hook_event_name": "PostToolUse", "tool_name": "Agent", "tool_input": {}},
        home=home,
        cwd=cwd,
        env_extra=extra,
    )

    records = _events(metrics)
    assert records[0]["server"] == "bantamkit"
    assert records[1]["server"] == "builtin"
    assert records[1]["detail"] == "general-purpose"


def test_the_usage_log_is_never_pruned_when_no_transcript_is_found(tmp_path):
    """A walk that found nothing is an unreadable projects dir, not a machine with no
    transcripts. Pruning on that reading would delete the whole log."""
    home, cwd = _bed(tmp_path, "usage-prune-skip")
    metrics = tmp_path / "usage-prune-skip" / "metrics"
    metrics.mkdir(parents=True)
    filler = json.dumps({"session": "gone", "pad": "x" * 200}) + "\n"
    (metrics / "events.jsonl").write_text(filler * 25_000, encoding="utf-8")
    before = (metrics / "events.jsonl").stat().st_size
    assert before > 4_000_000, "the bed must actually sit above the cap"

    _run_hook(
        {"hook_event_name": "PostToolUse", "tool_name": "Bash"},
        home=home,
        cwd=cwd,
        env_extra={"TOOL_METRICS_DIR": str(metrics)},
    )

    assert (metrics / "events.jsonl").stat().st_size > before
    skipped = [line for line in _log_lines(home) if line.get("action") == "prune-skipped"]
    assert skipped and skipped[0]["reason"] == "no transcripts found"


def test_above_the_cap_a_line_whose_transcript_still_exists_is_dropped(tmp_path):
    """A line whose session still has a transcript is redundant BY CONSTRUCTION: the
    reader only ever reads the sessions whose transcript the host deleted."""
    home, cwd = _bed(tmp_path, "usage-prune")
    metrics = tmp_path / "usage-prune" / "metrics"
    metrics.mkdir(parents=True)
    projects = home / ".claude" / "projects" / "some-project"
    projects.mkdir(parents=True)
    (projects / "live.jsonl").write_text("{}\n", encoding="utf-8")
    live = json.dumps({"session": "live", "pad": "x" * 200}) + "\n"
    dead = json.dumps({"session": "deleted-session", "pad": "y" * 200}) + "\n"
    (metrics / "events.jsonl").write_text((live * 20_000) + (dead * 5), encoding="utf-8")
    before = (metrics / "events.jsonl").stat().st_size
    assert before > 4_000_000, "the bed must actually sit above the cap"

    _run_hook(
        {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "live"},
        home=home,
        cwd=cwd,
        env_extra={"TOOL_METRICS_DIR": str(metrics)},
    )

    kept = _events(metrics)
    assert {record["session"] for record in kept} == {"deleted-session"}
    assert len(kept) == 5
    pruned = [line for line in _log_lines(home) if line.get("action") == "prune"]
    # `before` on the log line is the size the PRUNE saw, which is after this call's own
    # line was appended -- the arm appends first and prunes second, so the two numbers
    # differ by exactly one record and asserting them equal was a bed defect, not a code one.
    assert pruned and pruned[0]["before"] > before
    assert pruned[0]["after"] < before


# --- 7. PostToolUse[memory_save] — the automatic compaction ------------------------------


def _index_bytes(store: Path) -> int:
    from bantamkit.memory.store import MemoryStore

    return len(MemoryStore(store, create=False).index_text().encode("utf-8"))


def _register(cwd: Path, *args: str) -> None:
    """A project-scope `.mcp.json` in the scratch cwd. No host config is touched."""
    (cwd / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"bantamkit": {"command": "bantamkit-mcp", "args": list(args)}}}),
        encoding="utf-8",
    )


def _save_payload() -> dict:
    return {"hook_event_name": "PostToolUse", "tool_name": "mcp__bantamkit__memory_save"}


def test_a_save_below_the_band_is_counted_and_nothing_is_compacted(tmp_path):
    home, cwd = _bed(tmp_path, "save-below")
    store = cwd / ".bantamkit" / "memory"
    _save(store, "project", "a-fact", "a description of the fact", "body")
    _register(cwd, "--index-budget", str(_index_bytes(store) * 10))

    done = _run_hook(_save_payload(), home=home, cwd=cwd)

    assert done.returncode == 0, done.stderr
    assert done.stdout == b"", "below the band nothing is emitted"
    line = [x for x in _log_lines(home) if x["event"] == "PostToolUse"][0]
    assert line["action"] == "saved"
    assert line["budgetSource"] == "configured"
    assert line["budgetScope"] == "project"
    assert _ledger(home)["saved"] == 1


def test_a_save_at_the_band_auto_compacts_and_says_so_on_stdout(tmp_path):
    """The user ruled compaction AUTOMATIC (2026-08-24). At >=90% of the budget the arm
    compacts to 80% and tells the session, in one object, what it did."""
    home, cwd = _bed(tmp_path, "save-band")
    store = cwd / ".bantamkit" / "memory"
    for i in range(6):
        _save(
            store,
            "project",
            f"fact-{i:02d}",
            " ".join(f"word{i:02d}x{j:02d}" for j in range(8)),
            "body",
        )
    assert len(list((store / "facts").glob("*.md"))) == 6, "the bed itself must hold 6"
    budget = _index_bytes(store)
    _register(cwd, "--index-budget", str(budget))

    done = _run_hook(_save_payload(), home=home, cwd=cwd)

    assert done.returncode == 0, done.stderr
    ctx = json.loads(done.stdout.decode())["hookSpecificOutput"]
    assert ctx["hookEventName"] == "PostToolUse"
    target = int(0.8 * budget)
    assert ctx["additionalContext"].startswith(
        f"[bantamkit] memory index was {budget}/{budget} B; auto-compacted to ≤{target} B."
    ), ctx["additionalContext"]
    line = [x for x in _log_lines(home) if x["event"] == "PostToolUse"][0]
    assert line["action"] == "auto-compact"
    assert line["budget"] == budget
    assert line["target"] == target
    assert line["reserve"] == budget - target
    assert line["exit"] == 0
    assert _index_bytes(store) <= target
    assert list((store / "archive").glob("*.md")), "the stalest facts really moved"


def test_the_band_is_measured_against_the_configured_budget_not_the_default(tmp_path):
    """The winning entry is the whole answer. With nothing configured the default applies,
    and a six-fact store is nowhere near it -- so the same bed that compacts above does
    not compact here."""
    home, cwd = _bed(tmp_path, "save-default")
    store = cwd / ".bantamkit" / "memory"
    for i in range(6):
        _save(
            store,
            "project",
            f"fact-{i:02d}",
            " ".join(f"word{i:02d}x{j:02d}" for j in range(8)),
            "body",
        )

    done = _run_hook(_save_payload(), home=home, cwd=cwd)

    assert done.stdout == b""
    line = [x for x in _log_lines(home) if x["event"] == "PostToolUse"][0]
    assert line["action"] == "saved"
    assert line["budgetSource"] == "default"
    assert line["budgetScope"] is None


# --- 8. PreCompact — steering for the summariser ------------------------------------------


def _seed_ledger(home: Path, files: list[Path], *, transcript: str = "/t/parent.jsonl") -> None:
    path = home / ".bantamkit" / "hooks" / "ledger-probe-session.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    reads = {
        f"{transcript}|{file}||": {
            "sig": "0|0",
            "at": "2026-09-20T00:00:00.000Z",
            "count": 1,
            "refused": False,
            "transcript": transcript,
            "file": str(file),
        }
        for file in files
    }
    path.write_text(json.dumps({"reads": reads}), encoding="utf-8")


def _precompact(home: Path, cwd: Path):
    return _run_hook(
        {"hook_event_name": "PreCompact", "trigger": "auto", "transcript_path": "/t/parent.jsonl"},
        home=home,
        cwd=cwd,
    )


def test_precompact_steering_is_plain_text_and_never_starts_with_a_brace(tmp_path):
    """THE CHANNEL IS PLAIN STDOUT. The host's PreCompact union has no member for the
    `hookSpecificOutput` envelope, so emitting one made it DROP the steering entirely."""
    home, cwd = _bed(tmp_path, "precompact-plain")

    done = _precompact(home, cwd)

    assert done.returncode == 0, done.stderr
    out = done.stdout.decode()
    assert out, "the fixed tail is never cut, so there is always something to say"
    assert not out.startswith("{"), out[:40]
    assert "Preserve verbatim: every number the user was shown" in out
    assert out.strip() == out


def test_precompact_lists_the_files_this_transcript_read(tmp_path):
    home, cwd = _bed(tmp_path, "precompact-files")
    _seed_ledger(home, [cwd / "one.py", cwd / "two.py"])

    out = _precompact(home, cwd).stdout.decode()

    assert "Files already read in this context" in out
    assert f"- {cwd / 'one.py'}" in out
    assert f"- {cwd / 'two.py'}" in out
    line = [x for x in _log_lines(home) if x["event"] == "PreCompact"][0]
    assert line["ledgerFiles"] == 2
    assert line["listed"] == 2
    assert line["trigger"] == "auto"
    assert line["bytes"] == len(out.encode("utf-8"))


def test_a_file_only_a_subagent_read_is_not_reported_to_the_parent(tmp_path):
    """The summary would otherwise carry a false premise the PostCompact reset cannot undo."""
    home, cwd = _bed(tmp_path, "precompact-subagent")
    path = home / ".bantamkit" / "hooks" / "ledger-probe-session.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "reads": {
                    f"/t/parent.jsonl|{cwd / 'mine.py'}||": {
                        "sig": "0|0",
                        "at": "x",
                        "count": 1,
                        "refused": False,
                        "transcript": "/t/parent.jsonl",
                        "file": str(cwd / "mine.py"),
                    },
                    f"/t/child.jsonl|{cwd / 'theirs.py'}||": {
                        "sig": "0|0",
                        "at": "x",
                        "count": 1,
                        "refused": False,
                        "transcript": "/t/child.jsonl",
                        "file": str(cwd / "theirs.py"),
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    out = _precompact(home, cwd).stdout.decode()

    assert "mine.py" in out
    assert "theirs.py" not in out, "the parent never saw the subagent's read"


def test_an_open_checkpoint_steers_and_names_the_cursor_unit(tmp_path):
    home, cwd = _bed(tmp_path, "precompact-cp")
    shiftwork = cwd / ".shiftwork"
    shiftwork.mkdir()
    (shiftwork / "checkpoint-job62.json").write_text(
        json.dumps(
            {
                "plan": {
                    "cursor": "J62-3B",
                    "units": [
                        {"id": "J62-3", "status": "done", "title": "the core"},
                        {"id": "J62-3B", "status": "in_progress", "title": "the five arms"},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    out = _precompact(home, cwd).stdout.decode()

    assert "Open shiftwork checkpoint" in out
    assert "checkpoint-job62.json" in out
    assert 'cursor "J62-3B" → unit J62-3B (in_progress) — the five arms.' in out
    assert "Preserve unit status and the next unit to clock in." in out
    line = [x for x in _log_lines(home) if x["event"] == "PreCompact"][0]
    assert line["cursor"] == "J62-3B"
    assert line["cpScanned"] == 1


def test_a_closed_checkpoint_does_not_steer_at_all(tmp_path):
    """Open means: at least one unit is neither `done` nor `dropped`."""
    home, cwd = _bed(tmp_path, "precompact-closed")
    shiftwork = cwd / ".shiftwork"
    shiftwork.mkdir()
    (shiftwork / "checkpoint.json").write_text(
        json.dumps(
            {"plan": {"cursor": "H3", "units": [{"id": "H3", "status": "done"}]}}
        ),
        encoding="utf-8",
    )
    (shiftwork / "broken.json").write_text("{not json", encoding="utf-8")

    out = _precompact(home, cwd).stdout.decode()

    assert "shiftwork checkpoint" not in out
    line = [x for x in _log_lines(home) if x["event"] == "PreCompact"][0]
    assert line["checkpoint"] is None
    assert line["cpScanned"] == 2, "the malformed file was read and skipped, not thrown on"


def test_precompact_stdout_stays_inside_its_byte_budget_and_the_tail_survives(tmp_path):
    """The FIXED lines are never cut; the file list absorbs the whole trim."""
    home, cwd = _bed(tmp_path, "precompact-cap")
    _seed_ledger(home, [cwd / ("d" * 300) / f"file-{i:03d}.py" for i in range(60)])

    out = _precompact(home, cwd).stdout.decode()

    assert len(out.encode("utf-8")) <= 4000
    assert "Preserve verbatim: every number the user was shown" in out
    line = [x for x in _log_lines(home) if x["event"] == "PreCompact"][0]
    assert line["ledgerFiles"] == 60
    assert line["capped"] == 40, "the count cap is applied before the byte cap"
    assert 0 < line["listed"] < 40, "the byte cap then trimmed the list further"


# --- 9. PostCompact -----------------------------------------------------------------------


def test_postcompact_resets_the_read_ledger(tmp_path):
    """Context was just rebuilt, so every earlier read is gone from it."""
    home, cwd = _bed(tmp_path, "postcompact")
    _seed_ledger(home, [cwd / "one.py"])
    ledger = home / ".bantamkit" / "hooks" / "ledger-probe-session.json"
    assert ledger.exists()

    done = _run_hook({"hook_event_name": "PostCompact"}, home=home, cwd=cwd)

    assert done.returncode == 0
    assert done.stdout == b""
    assert not ledger.exists()
    line = [x for x in _log_lines(home) if x["event"] == "PostCompact"][0]
    assert line["action"] == "ledger-reset"


def test_postcompact_with_no_ledger_is_not_an_error(tmp_path):
    home, cwd = _bed(tmp_path, "postcompact-none")

    done = _run_hook({"hook_event_name": "PostCompact"}, home=home, cwd=cwd)

    assert done.returncode == 0
    assert done.stderr == b""


# --- 10. Stop — the save nudge, and the dream preview beside it ---------------------------


def _transcript(cwd: Path, *, tool_uses: int, saved: bool = False) -> Path:
    path = cwd / "transcript.jsonl"
    body = "".join('{"type": "tool_use"}\n' for _ in range(tool_uses))
    if saved:
        body += '{"name": "mcp__bantamkit__memory_save"}\n'
    path.write_text(body, encoding="utf-8")
    return path


def _stop(home: Path, cwd: Path, transcript: Path, **extra):
    return _run_hook(
        {"hook_event_name": "Stop", "transcript_path": str(transcript), **extra},
        home=home,
        cwd=cwd,
    )


def test_stop_nudges_once_when_the_session_did_work_and_saved_nothing(tmp_path):
    home, cwd = _bed(tmp_path, "stop-nudge")
    transcript = _transcript(cwd, tool_uses=25)

    first = _stop(home, cwd, transcript)
    second = _stop(home, cwd, transcript)

    assert first.returncode == 0, first.stderr
    decision = json.loads(first.stdout.decode())
    assert decision["decision"] == "block"
    assert "made 25 tool calls and saved no memory" in decision["reason"]
    assert "This nudge fires once per session." in decision["reason"]
    assert second.stdout == b"", "once per session"
    assert _ledger(home)["stopNudged"] is True


def test_a_session_that_saved_a_memory_is_not_nudged(tmp_path):
    home, cwd = _bed(tmp_path, "stop-saved")
    transcript = _transcript(cwd, tool_uses=25, saved=True)

    done = _stop(home, cwd, transcript)

    assert done.stdout == b""
    line = [x for x in _log_lines(home) if x.get("action") == "pass"][0]
    assert line["saved"] is True
    assert line["toolUses"] == 25


def test_the_tool_call_floor_is_tested_AT_the_floor_and_not_near_it(tmp_path):
    """A session that did no real work has nothing durable to have learned -- and the
    boundary is where that claim can be wrong.

    THE PAIR IS THE POINT, and it is here because the first version of this case was not.
    It drove 19 calls and 25 calls, which is "near the floor", and a mutation moving
    `STOP_NUDGE_MIN_TOOL_CALLS` from 20 to 21 ran the whole suite GREEN: both inputs were on
    the same side of both numbers. 19 and 20 are the only two inputs that pin WHICH number
    the floor is.
    """
    home, cwd = _bed(tmp_path, "stop-floor")
    quiet = _run_hook(
        {"hook_event_name": "Stop", "transcript_path": str(_transcript(cwd, tool_uses=19))},
        home=home,
        cwd=cwd,
        session="below",
    )
    busy = _run_hook(
        {"hook_event_name": "Stop", "transcript_path": str(_transcript(cwd, tool_uses=20))},
        home=home,
        cwd=cwd,
        session="at",
    )

    assert quiet.stdout == b"", "19 is below the floor"
    line = [x for x in _log_lines(home) if x.get("action") == "pass"][0]
    assert line["toolUses"] == 19
    assert line["saved"] is False
    assert json.loads(busy.stdout.decode())["decision"] == "block", "20 IS the floor"
    assert "made 20 tool calls" in json.loads(busy.stdout.decode())["reason"]


def test_stop_hook_active_is_not_re_entered(tmp_path):
    """The host sets it when the stop hook's own block is being handled. Nudging there
    would be an infinite handback."""
    home, cwd = _bed(tmp_path, "stop-active")
    transcript = _transcript(cwd, tool_uses=25)

    done = _stop(home, cwd, transcript, stop_hook_active=True)

    assert done.returncode == 0
    assert done.stdout == b""


def test_a_stop_with_no_transcript_on_disk_is_silent_and_exits_zero(tmp_path):
    home, cwd = _bed(tmp_path, "stop-notranscript")

    done = _stop(home, cwd, cwd / "gone.jsonl")

    assert done.returncode == 0
    assert done.stdout == b""
    assert done.stderr == b""


def _two_layers(home: Path, cwd: Path) -> None:
    """One fact by the same name in BOTH layers -- what a dream would consolidate."""
    for store in (home / ".bantamkit" / "memory", cwd / ".bantamkit" / "memory"):
        _save(store, "project", "shared-name", "a description both layers carry", "body")


def test_the_dream_arm_previews_and_never_emits_so_the_nudge_stays_the_only_voice(tmp_path):
    """RULING 2026-09-12 (J50-2A): the automatic trigger runs the dream in DRY RUN only.
    Two JSON objects on one stdout is not a protocol, so this arm reports to the log."""
    home, cwd = _bed(tmp_path, "stop-dream")
    _two_layers(home, cwd)
    transcript = _transcript(cwd, tool_uses=25)

    done = _stop(home, cwd, transcript)

    parsed = json.loads(done.stdout.decode())  # a concatenation would raise here
    assert parsed["decision"] == "block"
    preview = [x for x in _log_lines(home) if x.get("action") == "dream-preview"][0]
    assert preview["dryRun"] is True
    assert preview["storeMoved"] is False
    assert "merged" not in preview, "a preview may never carry a field named `merged`"
    assert preview["wouldMerge"] >= 1
    profile = home / ".bantamkit" / "memory" / "facts"
    assert len(list(profile.glob("*.md"))) == 1, "a preview moves nothing"


def test_an_unchanged_store_does_not_dream_a_second_time(tmp_path):
    """`Stop` fires every turn; a dream on every turn is a cost with no benefit."""
    home, cwd = _bed(tmp_path, "stop-dream-gate")
    _two_layers(home, cwd)
    transcript = _transcript(cwd, tool_uses=1)

    _stop(home, cwd, transcript)
    _stop(home, cwd, transcript)

    actions = [
        x.get("action")
        for x in _log_lines(home)
        if str(x.get("action", "")).startswith("dream")
    ]
    assert actions == ["dream-preview", "dream-skip"], actions
    skip = [x for x in _log_lines(home) if x.get("action") == "dream-skip"][0]
    assert skip["reason"] == "unchanged"


def _dream_actions(home: Path) -> list[str]:
    """Every dream record's action, with the skip reason attached: `dream-skip/unchanged`."""
    return [
        x["action"] + (f"/{x['reason']}" if x.get("reason") else "")
        for x in _log_lines(home)
        if str(x.get("action", "")).startswith("dream")
    ]


def _dream_fingerprint(home: Path) -> str:
    state = home / ".bantamkit" / "hooks" / "dream-state.json"
    return json.loads(state.read_text(encoding="utf-8"))["fingerprint"]


def test_the_store_fingerprint_masks_only_the_last_recalled_line(tmp_path):
    """job64 / J64-3. Every recall rewrites `last_recalled:` and the mtime, and until this
    unit the fingerprint was `name + size + mtimeMs`, so a session of recalls re-armed the
    preview on every Stop (measured: 103 of 236 previews in a week said the identical
    `wouldMerge 14`). Size is not a usable signal either: J64-0 measured a same-day re-stamp
    moving the mtime ALONE. So the fingerprint reads content, with that one line left out --
    and EVERY other field, the body, the name and a body line spelled like the key still move
    it. MUTATION (2026-09-25): the stat fields put back on both sides turn this red on the
    first `==` below; count in `.shiftwork/notes-job64/J64-3.md`."""
    from bantamkit.hookadapter import _fact_content_digest, _store_fingerprint

    root = tmp_path / "store"
    facts = root / "facts"
    facts.mkdir(parents=True)
    text = (
        "---\nname: a\ndescription: d\ntype: project\ncreated: '2026-08-01'\n"
        "last_recalled: null\nlinks: []\n---\n\nbody\n"
    )
    (facts / "a.md").write_text(text, encoding="utf-8")
    fp = _store_fingerprint([str(root)])

    (facts / "a.md").write_text(
        text.replace("last_recalled: null", "last_recalled: '2026-09-25'"), encoding="utf-8"
    )
    assert _store_fingerprint([str(root)]) == fp, "a recall's date is not content"
    now = os.stat(facts / "a.md").st_mtime_ns
    os.utime(facts / "a.md", ns=(now + 10**9, now + 10**9))
    assert _store_fingerprint([str(root)]) == fp, "a touch is not content"

    for field, new in (
        ("description: d", "description: e"),
        ("type: project", "type: feedback"),
        ("created: '2026-08-01'", "created: '2026-08-02'"),
        ("links: []", "links: [b]"),
        ("\nbody\n", "\nanother body\n"),
    ):
        (facts / "a.md").write_text(text.replace(field, new), encoding="utf-8")
        assert _store_fingerprint([str(root)]) != fp, f"{field!r} is content"
    (facts / "a.md").write_text(text + "last_recalled: in the body\n", encoding="utf-8")
    assert _store_fingerprint([str(root)]) != fp, "only the FRONTMATTER line is masked"
    (facts / "a.md").write_text(text, encoding="utf-8")
    assert _store_fingerprint([str(root)]) == fp, "the original bytes, back to the original"
    os.rename(facts / "a.md", facts / "b.md")
    assert _store_fingerprint([str(root)]) != fp, "a rename is a change"

    # A Windows-written file carries `\r\n`; the mask still finds the line, and the bytes
    # themselves (with their `\r`) are what is hashed, so the two spellings differ.
    crlf = text.replace("\n", "\r\n").encode()
    dated = crlf.replace(b"last_recalled: null", b"last_recalled: '2026-09-25'")
    assert _fact_content_digest(crlf) == _fact_content_digest(dated)
    assert _fact_content_digest(crlf) != _fact_content_digest(text.encode())


def test_re_dating_a_fact_does_not_re_arm_the_dream_gate_but_a_content_change_does(tmp_path):
    """The same property through the hook: (a) an explicit recall, a re-dating of the line
    and a bare touch each leave the next Stop a `dream-skip unchanged` with the SAME stored
    fingerprint; (b) a body edit and (c) a new fact each produce a preview. The (a2) and
    (a3) steps are checked to have really rewritten the file, or a skip would prove nothing.

    #199 D5: (a1) an explicit recall no longer writes the file at all -- the use is a ledger
    event -- so it is checked to leave bytes and mtime alone. WAS: it dated `last_recalled`,
    and was the first of three rewrites. (a2) is what an older runtime's recall still writes.
    """
    from bantamkit.memory.component import Memory

    home, cwd = _bed(tmp_path, "stop-dream-redate")
    _two_layers(home, cwd)
    project = cwd / ".bantamkit" / "memory"
    _save(project, "project", "recalled-often", "the fact the operator recalls every turn", "body")
    fact = project / "facts" / "recalled-often.md"
    transcript = _transcript(cwd, tool_uses=1)

    _stop(home, cwd, transcript)  # S1: the first look previews
    fp1 = _dream_fingerprint(home)

    # (a1) an explicit recall writes nothing to the fact: bytes AND mtime stay (#199 D5).
    bytes_before, mtime_before = fact.read_bytes(), fact.stat().st_mtime_ns
    assert "recalled-often" in Memory(store=project).recall("operator recalls every turn")
    assert fact.read_bytes() == bytes_before and fact.stat().st_mtime_ns == mtime_before
    _stop(home, cwd, transcript)  # S2
    # (a2) the same line re-dated to another day -- what an older runtime's recall writes.
    fact.write_text(
        re.sub(
            r"^last_recalled: .*$",
            "last_recalled: '2020-01-01'",
            fact.read_text(encoding="utf-8"),
            flags=re.M,
        ),
        encoding="utf-8",
    )
    assert fact.read_bytes() != bytes_before, "the re-dating rewrote the file"
    _stop(home, cwd, transcript)  # S3
    # (a3) the mtime alone -- a same-day re-stamp (J64-0 Q4).
    later = fact.stat().st_mtime_ns + 10**9
    os.utime(fact, ns=(later, later))
    _stop(home, cwd, transcript)  # S4
    assert _dream_fingerprint(home) == fp1, "three re-datings, one fingerprint"

    # (b) a body edit through the store (same name = update)
    Memory(store=project).save(
        "project", "recalled-often", "the fact the operator recalls every turn", "a new body"
    )
    assert "a new body" in fact.read_text(encoding="utf-8")
    _stop(home, cwd, transcript)  # S5
    fp5 = _dream_fingerprint(home)
    assert fp5 != fp1, "a body edit is a change"
    # (c) a fact added
    _save(project, "project", "brand-new", "written after the last look", "body")
    _stop(home, cwd, transcript)  # S6
    assert _dream_fingerprint(home) != fp5, "a new fact is a change"

    assert _dream_actions(home) == [
        "dream-preview",
        "dream-skip/unchanged",
        "dream-skip/unchanged",
        "dream-skip/unchanged",
        "dream-preview",
        "dream-preview",
    ]


def test_a_cwd_whose_project_store_is_the_profile_store_does_not_dream_with_itself(tmp_path):
    """Measured on the user's real store: one directory bound as two layers archived 20 of
    20 facts. The guard refuses BEFORE a child process is spawned."""
    from bantamkit.memory.layers import resolve_project_store

    home, _ = _bed(tmp_path, "stop-dream-single")
    # The cwd must sit INSIDE the home with no `.bantamkit` of its own, so the walk up
    # lands on the PROFILE store -- one directory bound as both layers. A cwd beside the
    # home instead of under it makes the walk find nothing and the guard never fire, which
    # is a bed that cannot test what it claims.
    cwd = home / "somewhere" / "deep"
    cwd.mkdir(parents=True)
    profile = home / ".bantamkit" / "memory"
    _save(profile, "project", "only-fact", "a description", "body")
    assert resolve_project_store(cwd).path.resolve() == profile.resolve(), "the bed's shape"
    transcript = _transcript(cwd, tool_uses=1)

    _stop(home, cwd, transcript)

    skip = [x for x in _log_lines(home) if x.get("action") == "dream-skip"][0]
    assert skip["reason"] == "single-layer"
    assert len(list((profile / "facts").glob("*.md"))) == 1
    # `archive/` EXISTS but is empty: this runtime's `MemoryStore(create=True)` makes the
    # directory when the bed saves its first fact, so its presence says nothing. What says
    # nothing was consumed is that no fact file is in it.
    assert list((profile / "archive").glob("*.md")) == [], "nothing was consumed"


def test_a_slow_dream_is_killed_by_the_timeout_instead_of_eating_the_session(tmp_path):
    """The host kills the WHOLE hook at 10 s, so the child's bound has to sit under that.
    A pass that times out must NOT record the fingerprint: the next Stop tries again."""
    home, cwd = _bed(tmp_path, "stop-dream-slow")
    _two_layers(home, cwd)
    transcript = _transcript(cwd, tool_uses=1)

    done = _run_hook(
        {"hook_event_name": "Stop", "transcript_path": str(transcript)},
        home=home,
        cwd=cwd,
        env_extra={"BANTAMKIT_DREAM_TIMEOUT_MS": "1"},
    )

    assert done.returncode == 0, done.stderr
    assert done.stderr == b""
    failed = [x for x in _log_lines(home) if x.get("action") == "dream-failed"][0]
    assert failed["timedOut"] is True
    assert not (home / ".bantamkit" / "hooks" / "dream-state.json").exists()


# --- 11. `tokens` is public API on the store ---------------------------------------------


def test_tokens_is_public_api_on_the_memory_store(tmp_path):
    """The Node runtime has exported `tokens` from `memory/store.ts` since it was written;
    the Python half kept it underscored, so the hook adapter had to import a private name
    across a layer boundary to score an injected header. One name, both runtimes."""
    from bantamkit.memory import store as store_module

    assert hasattr(store_module, "tokens"), "the promoted name"
    assert store_module.tokens("Alpha-Beta gamma!") == {"alpha", "beta", "gamma"}
    assert not hasattr(store_module, "_tokens"), "the private spelling is gone, not aliased"


# --- job65, J65-8: #119, #188, #168, #169, #192 ---------------------------------------------
# The in-process half; the conformance `hooks` suite's `hook-degrade` block is the process
# half, compared against the port. Each test names the pre-fix behaviour it was red on.


def _session_ctx(done) -> str:
    return json.loads(done.stdout.decode())["hookSpecificOutput"]["additionalContext"]


def test_119_one_broken_profile_fact_costs_that_file_and_every_block_still_renders(tmp_path):
    """RED before job65: SessionStart printed 0 bytes -- the profile block raised past the arm."""
    home, cwd = _bed(tmp_path, "broken-profile")
    profile = home / ".bantamkit" / "memory"
    _save(profile, "feedback", "prof-ok", "shared words profile fact", "body")
    _save(cwd / ".bantamkit" / "memory", "project", "ok-fact", "shared words project fact", "b")
    (profile / "facts" / "broken.md").write_text("", encoding="utf-8")

    done = _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)

    assert done.returncode == 0, done.stderr
    ctx = _session_ctx(done)
    assert "[bantamkit profile memory — 1 fact learned across projects]" in ctx
    assert "[[prof-ok]]" in ctx and "[[ok-fact]]" in ctx
    assert "[bantamkit] Toolbox is live" in ctx
    assert "[1 fact file not read — not a valid fact: broken.md;" in ctx
    line = [x for x in _log_lines(home) if x["event"] == "SessionStart"][-1]
    assert [s["file"] for s in line["profileSkipped"]] == ["broken.md"]
    assert line["profileSkipped"][0]["reason"].startswith("malformed fact file broken.md")


def test_119_one_broken_project_fact_does_not_silence_user_prompt_submit(tmp_path):
    """RED before job65: UserPromptSubmit printed 0 bytes and logged an `error`."""
    home, cwd = _bed(tmp_path, "broken-project")
    _save(home / ".bantamkit" / "memory", "feedback", "prof-ok", "shared words profile fact", "b")
    store = cwd / ".bantamkit" / "memory"
    _save(store, "project", "ok-fact", "shared words project fact", "b")
    (store / "facts" / "zz-bad.md").write_text("---\nname: zz-bad\n", encoding="utf-8")

    done = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "shared words fact please"},
        home=home,
        cwd=cwd,
    )

    assert done.returncode == 0, done.stderr
    ctx = _session_ctx(done)
    assert "[ok-fact]" in ctx and "[prof-ok]" in ctx
    line = _log_lines(home)[-1]
    assert line["action"] == "inject"
    assert [(s["layer"], s["file"]) for s in line["skipped"]] == [("project", "zz-bad.md")]


def test_168_an_unparseable_stdin_is_logged_as_size_and_digest_never_text(tmp_path):
    """RED before job65: the record carried `raw`, the first 200 characters of the prompt."""
    import hashlib

    home, cwd = _bed(tmp_path, "parse-error")
    raw = b'{"hook_event_name":"UserPromptSubmit","prompt":"my secret password is hunter2 and'

    done = _run_hook(home=home, cwd=cwd, raw=raw)

    assert done.returncode == 0 and done.stdout == b""
    line = _log_lines(home)[-1]
    assert {k: v for k, v in line.items() if k not in ("ts", "ms")} == {
        "event": "parse-error",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    assert b"hunter2" not in (home / ".bantamkit" / "hooks" / "hook-log.jsonl").read_bytes()


def _tool_use(name: str, **tool_input) -> str:
    message = {"content": [{"type": "tool_use", "name": name, "input": tool_input}]}
    return json.dumps({"type": "assistant", "message": message})


def test_169_neither_a_read_nor_an_unmirrored_write_under_memory_is_a_save(tmp_path):
    """RED before job65: the Read below set `saved: true` and silenced the nudge."""
    home, cwd = _bed(tmp_path, "stop-read")
    bash = [_tool_use("Bash") for _ in range(30)]
    outcomes = {}
    tails = {
        "read": _tool_use("Read", file_path="/repo/docs/memory/notes.md"),
        "write": _tool_use("Write", file_path="/h/.claude/projects/p/memory/f.md", content="x"),
        "multiedit": _tool_use("MultiEdit", file_path="/h/memory/f.md", edits=[]),
    }
    for label, tail in tails.items():
        transcript = cwd / f"t-{label}.jsonl"
        transcript.write_text("\n".join([*bash, tail]) + "\n", encoding="utf-8")
        done = _stop(home, cwd, transcript, session_id=f"stop-{label}")
        outcomes[label] = (_log_lines(home)[-1]["action"], done.stdout != b"")
    assert outcomes == {
        "read": ("nudge", True),
        # #228: a native write is no longer a save by itself; only the mirror's ledger is.
        "write": ("nudge", True),
        "multiedit": ("nudge", True),
    }


@pytest.mark.skipif(
    sys.platform == "win32" or getattr(os, "getuid", lambda: -1)() == 0,
    reason="root reads a mode-000 file, and win32 modes are advisory",
)
def test_192_a_file_the_hook_may_not_read_is_never_ledgered_or_refused(tmp_path):
    """RED before job65: the second Read of a chmod-000 file was denied."""
    home, cwd = _bed(tmp_path, "locked")
    locked = cwd / "locked.txt"
    locked.write_text("secret", encoding="utf-8")
    locked.chmod(0o000)
    try:
        payload = _read_payload(locked)
        runs = [_run_hook(payload, home=home, cwd=cwd) for _ in range(2)]
    finally:
        locked.chmod(0o644)
    assert [r.stdout for r in runs] == [b"", b""]
    assert not (home / ".bantamkit" / "hooks" / "ledger-probe-session.json").exists()


# ---------------------------------------------- #170: the args --store pin (job67, J67-5)
# The server reads `--store` off its argv and it outranks `BANTAMKIT_MEMORY_DIR` there; the hook
# read the winning entry's `env` only, so every args spelling had it injecting from the walk's
# store while the server served X. The conformance `hooks` suite's `store-pin-args` block
# compares the same spellings across both runtimes.


def _ladder_store(store: Path, name: str) -> Path:
    _save(store, "project", name, f"{name} explains the release ladder", "body")
    return store


def _user_entry(home: Path, entry: dict) -> None:
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"bantamkit": {"command": "npx", **entry}}}), encoding="utf-8"
    )


@pytest.mark.parametrize(
    "spelling",
    ["space", "equals", "outranks-env", "last-wins"],
)
def test_170_args_store_pin_binds_x_and_outranks_env(tmp_path, spelling):
    home, cwd = _bed(tmp_path, spelling)
    _ladder_store(cwd / ".bantamkit" / "memory", "walk-fact")
    args_store = _ladder_store(tmp_path / "pinned-args", "args-fact")
    env_store = _ladder_store(tmp_path / "pinned-env", "env-fact")
    entry = {
        "space": {"args": ["--store", str(args_store)]},
        "equals": {"args": [f"--store={args_store}"]},
        "outranks-env": {
            "args": ["--store", str(args_store)],
            "env": {"BANTAMKIT_MEMORY_DIR": str(env_store)},
        },
        "last-wins": {"args": ["--store", str(env_store), f"--store={args_store}"]},
    }[spelling]
    _user_entry(home, entry)
    s = _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)
    assert s.returncode == 0, s.stderr
    out = s.stdout.decode("utf-8")
    assert "args-fact" in out
    assert "walk-fact" not in out and "env-fact" not in out
    rec = [r for r in _log_lines(home) if r.get("event") == "SessionStart"][-1]
    assert rec["storeScope"] == "user"
    u = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "walk me through the release ladder"},
        home=home,
        cwd=cwd,
    )
    assert u.returncode == 0, u.stderr
    out = u.stdout.decode("utf-8")
    assert "args-fact" in out
    assert "walk-fact" not in out and "env-fact" not in out


def test_170_relative_store_resolves_against_cwd_and_empty_store_pins_nothing(tmp_path):
    home, cwd = _bed(tmp_path, "rel")
    _ladder_store(cwd / ".bantamkit" / "memory", "walk-fact")
    _ladder_store(cwd / "rel" / "store", "rel-fact")
    env_store = _ladder_store(tmp_path / "pinned-env", "env-fact")
    _user_entry(home, {"args": ["--store", os.path.join("rel", "store")]})
    r = _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home, cwd=cwd)
    assert r.returncode == 0, r.stderr
    assert "rel-fact" in r.stdout.decode("utf-8")
    assert "walk-fact" not in r.stdout.decode("utf-8")
    home2, _ = _bed(tmp_path, "empty")
    _user_entry(home2, {"args": ["--store="], "env": {"BANTAMKIT_MEMORY_DIR": str(env_store)}})
    e = _run_hook({"hook_event_name": "SessionStart", "source": "startup"}, home=home2, cwd=cwd)
    assert e.returncode == 0, e.stderr
    assert "env-fact" in e.stdout.decode("utf-8")


# ------------------------------------------------------------- #200 Task 1: the touch log


def test_post_tool_use_records_edit_and_never_bash(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for tool, ti in [
        ("Edit", {"file_path": str(r / "src" / "a.py")}),
        ("Bash", {"command": "cat src/a.py"}),
        ("Read", {"file_path": str(r / "src" / "a.py")}),
    ]:
        done = _run_hook(
            {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": ti},
            home=home,
            cwd=r,
            session="s1",
        )
        assert done.returncode == 0 and done.stdout == b""
    log = next((home / ".bantamkit" / "touch").glob("*.jsonl"))
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    # Seq 3 for the Read: the Bash call between them is counted, not recorded.
    assert [(x["op"], x["path"], x["seq"]) for x in lines] == [
        ("edit", "src/a.py", 1),
        ("read", "src/a.py", 3),
    ]


def test_post_tool_use_outside_a_repo_records_nothing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    plain = tmp_path / "plain"
    plain.mkdir()
    _run_hook(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(plain / "a.py")},
        },
        home=home,
        cwd=plain,
        session="s1",
    )
    assert not (home / ".bantamkit" / "touch").exists()
    assert not (home / ".bantamkit" / "hooks" / "ledger-s1.seq.json").exists()


def test_post_tool_use_unwritable_touch_log_is_a_logged_miss(tmp_path):
    home = tmp_path / "home"
    (home / ".bantamkit").mkdir(parents=True)
    (home / ".bantamkit" / "touch").write_text("a file, not a dir", encoding="utf-8")
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    done = _run_hook(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": str(r / "x")},
        },
        home=home,
        cwd=r,
        session="s1",
    )
    assert done.returncode == 0 and done.stdout == b"" and done.stderr == b""
    misses = [x for x in _log_lines(home) if x.get("touch") == "miss"]
    assert misses == [{**misses[0], "event": "PostToolUse", "touch": "miss", "tool": "Read"}]


# ------------------------------------------------------------- #200 Task 3: bash-turn


def test_stop_records_a_bash_turn_write_once_and_never_an_edited_file(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / "a.txt").write_text("1\n", encoding="utf-8")

    def hook(payload):
        done = _run_hook(payload, home=home, cwd=r, session="s1")
        assert done.returncode == 0, done.stderr
        return done

    # A PostToolUse before the turn opens, so the turn's `from` is not 0.
    hook({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}})
    hook({"hook_event_name": "UserPromptSubmit", "prompt": "hi"})  # short: the skip still opens
    hook(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(r / "a.txt")},
        }
    )
    (r / "b.txt").write_text("by bash\n", encoding="utf-8")
    (r / "a.txt").write_text("again, longer\n", encoding="utf-8")
    hook({"hook_event_name": "Stop"})
    log = next((home / ".bantamkit" / "touch").glob("*.jsonl"))
    rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    turns = [x for x in rows if x.get("via") == "bash-turn"]
    assert [(x["op"], x["path"], x["from"], x["seq"]) for x in turns] == [("write", "b.txt", 1, 2)]
    before = log.read_bytes()
    hook({"hook_event_name": "Stop", "stop_hook_active": True})
    assert log.read_bytes() == before


def test_stop_outside_a_repo_or_without_a_turn_records_nothing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    plain = tmp_path / "plain"
    plain.mkdir()
    for p in ({"hook_event_name": "UserPromptSubmit", "prompt": "hi"}, {"hook_event_name": "Stop"}):
        assert _run_hook(p, home=home, cwd=plain, session="s1").returncode == 0
    assert not (home / ".bantamkit" / "touch").exists()
    assert not (home / ".bantamkit" / "hooks" / "ledger-s1.turn.json").exists()
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / "x.txt").write_text("x\n", encoding="utf-8")
    assert _run_hook({"hook_event_name": "Stop"}, home=home, cwd=r, session="s2").returncode == 0
    assert not (home / ".bantamkit" / "touch").exists()


# --------------------------------------------- #200 Task 5: w_context and the via admission

VIA_PROMPT = "explain the gateway rollout plan please"
VIA_LINE = "[project] [fa] (project) notes about src/a.py [via a.py]"


def _via_bed(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A git repo tracking src/a.py; its store holds `fa` (names the file, does not match
    the prompt) and `gate-fact` (matches the prompt)."""
    home = tmp_path / "home"
    home.mkdir()
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    (r / "src" / "a.py").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    subprocess.run(["git", "-C", str(r), "add", "src/a.py"], check=True)
    # A commit: `renames` reads `git log`, and a repo with no HEAD has no graph (T200-4).
    subprocess.run(
        ["git", "-C", str(r), "-c", "user.email=t@t", "-c", "user.name=t", "-c",
         "commit.gpgsign=false", "commit", "-qm", "one"],
        check=True,
    )
    store = r / ".bantamkit" / "memory"
    _save(store, "project", "fa", "notes about src/a.py", "kept short")
    _save(store, "project", "gate-fact", "gateway rollout plan details", "the plan")
    return home, r, store


def _via_ctx(done) -> list[str]:
    assert done.returncode == 0, done.stderr
    if not done.stdout:
        return []
    out = json.loads(done.stdout)
    return out["hookSpecificOutput"]["additionalContext"].split("\n")


def _post(home, r, tool, ti, env_extra=None):
    done = _run_hook(
        {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": ti},
        home=home,
        cwd=r,
        session="s1",
        env_extra=env_extra,
    )
    assert done.returncode == 0, done.stderr


def _ups(home, r, env_extra=None, session="s1"):
    return _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": VIA_PROMPT},
        home=home,
        cwd=r,
        session=session,
        env_extra=env_extra,
    )


def _store_bytes(store: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted((store / "facts").glob("*.md"))}


def _usage_files(home: Path) -> dict[str, bytes]:
    root = home / ".bantamkit" / "usage"
    if not root.exists():
        return {}
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_via_line_after_an_edit_once_and_the_hook_writes_no_fact_or_usage(tmp_path):
    home, r, store = _via_bed(tmp_path)
    on = {"BANTAMKIT_VIA": "on"}
    _post(home, r, "Edit", {"file_path": str(r / "src" / "a.py")}, on)
    facts, usage = _store_bytes(store), _usage_files(home)
    lines = _via_ctx(_ups(home, r, on))
    assert lines[1:] == ["[project] [gate-fact] (project) gateway rollout plan details", VIA_LINE]
    assert _store_bytes(store) == facts, "a via fact is never stamped or repaired"
    assert _usage_files(home) == usage, "the hook writes no usage ledger line (#199)"
    rec = [x for x in _log_lines(home) if x.get("event") == "UserPromptSubmit"][-1]
    assert rec["via"] == "fa" and rec["context"] == 1
    assert [x["name"] for x in rec["injected"]] == ["gate-fact", "fa"]
    assert rec["injected"][1]["score"] == 0, "the [via ...] label is not scored"
    # Already in the window: the seen-set suppresses it on the next prompt.
    assert _via_ctx(_ups(home, r, on)) == []


def test_via_off_by_default_and_by_the_switch(tmp_path):
    home, r, _store = _via_bed(tmp_path)
    _post(home, r, "Edit", {"file_path": str(r / "src" / "a.py")})
    # Not `on`/`off`: the module default, VIA_ON = False.
    lines = _via_ctx(_ups(home, r, {"BANTAMKIT_VIA": "unset-means-default"}))
    assert VIA_LINE not in lines and len(lines) == 2
    rec = [x for x in _log_lines(home) if x.get("event") == "UserPromptSubmit"][-1]
    # T200-10: with W_CONTEXT 0 and via off no context is built, so none is counted (it was
    # `rec["context"] == 1`, the dead work the reviewer named; the reply is unchanged).
    assert "via" not in rec and "context" not in rec
    lines = _via_ctx(_ups(home, r, {"BANTAMKIT_VIA": "off"}, session="s2"))
    assert VIA_LINE not in lines


def test_via_on_by_the_module_default_unless_the_switch_says_off(tmp_path, monkeypatch, capsys):
    import io

    from bantamkit import hookadapter
    from bantamkit.touch import context as tc

    home, r, _store = _via_bed(tmp_path)
    _post(home, r, "Edit", {"file_path": str(r / "src" / "a.py")})
    monkeypatch.setattr(tc, "VIA_ON", True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("BANTAMKIT_MEMORY_DIR", raising=False)
    monkeypatch.chdir(r)

    def ups(session: str) -> list[str]:
        raw = json.dumps(
            {"hook_event_name": "UserPromptSubmit", "prompt": VIA_PROMPT, "cwd": str(r),
             "session_id": session}
        ).encode("utf-8")
        hookadapter.run_hook(io.BytesIO(raw))
        out = capsys.readouterr().out
        return json.loads(out)["hookSpecificOutput"]["additionalContext"].split("\n") if out else []

    monkeypatch.delenv("BANTAMKIT_VIA", raising=False)
    assert ups("s1")[1:].count(VIA_LINE) == 1
    monkeypatch.setenv("BANTAMKIT_VIA", "off")
    # A fresh transcript key: nothing seen yet, so only the switch can withhold the line.
    _post(home, r, "Edit", {"file_path": str(r / "src" / "a.py")})
    lines = ups("s1-other")
    assert VIA_LINE not in lines


def test_via_absent_when_the_edit_is_21_calls_back(tmp_path):
    home, r, _store = _via_bed(tmp_path)
    on = {"BANTAMKIT_VIA": "on"}
    _post(home, r, "Edit", {"file_path": str(r / "src" / "a.py")}, on)
    for _ in range(21):
        _post(home, r, "Bash", {"command": "ls"}, on)
    lines = _via_ctx(_ups(home, r, on))
    assert lines[1:] == ["[project] [gate-fact] (project) gateway rollout plan details"]
    rec = [x for x in _log_lines(home) if x.get("event") == "UserPromptSubmit"][-1]
    assert "context" not in rec and "via" not in rec


# --- T200-10: the reviewer's blockers ----------------------------------------------------


def test_no_git_on_path_records_nothing(tmp_path):
    """Spec Error handling: "No git, or not inside a repo | Nothing is recorded" (B2)."""
    home, r, _store = _via_bed(tmp_path)
    nogit = tmp_path / "nogit"
    nogit.mkdir()
    _post(home, r, "Read", {"file_path": str(r / "src" / "a.py")}, {"PATH": str(nogit)})
    _post(home, r, "Edit", {"file_path": str(r / "src" / "a.py")}, {"PATH": str(nogit)})
    assert not (home / ".bantamkit" / "touch").exists()
    assert not (home / ".bantamkit" / "hooks" / "ledger-s1.seq.json").exists()
    # The control: git reachable through a symlink in a PATH directory records both.
    link = tmp_path / "gitlink"
    link.mkdir()
    (link / "git").symlink_to(shutil.which("git"))
    _post(home, r, "Read", {"file_path": str(r / "src" / "a.py")}, {"PATH": str(link)})
    (log,) = (home / ".bantamkit" / "touch").glob("*.jsonl")
    assert [json.loads(x)["op"] for x in log.read_text(encoding="utf-8").splitlines()] == ["read"]


def test_ups_builds_no_context_while_it_cannot_move_the_reply(tmp_path, monkeypatch, capsys):
    """W_CONTEXT 0 and via off: no touch-log read, no graph, the same reply bytes (T200-10)."""
    import io

    from bantamkit import hookadapter
    from bantamkit.memory import retrieval

    assert retrieval.W_CONTEXT == 0.0
    home, r, _store = _via_bed(tmp_path)
    for session in ("s1", "s2"):  # each prompt's own session has the Edit in its window
        done = _run_hook(
            {"hook_event_name": "PostToolUse", "tool_name": "Edit",
             "tool_input": {"file_path": str(r / "src" / "a.py")}},
            home=home, cwd=r, session=session,
        )
        assert done.returncode == 0, done.stderr
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("BANTAMKIT_MEMORY_DIR", raising=False)
    monkeypatch.delenv("BANTAMKIT_VIA", raising=False)
    monkeypatch.chdir(r)
    graph = home / ".bantamkit" / "graph"

    def ups(session: str) -> str:
        raw = json.dumps(
            {"hook_event_name": "UserPromptSubmit", "prompt": VIA_PROMPT, "cwd": str(r),
             "session_id": session}
        ).encode("utf-8")
        hookadapter.run_hook(io.BytesIO(raw))
        return capsys.readouterr().out

    skipped = ups("s1")
    assert skipped and not graph.exists(), "the inert state builds no graph"
    # Force the build only (the gate's own `via_enabled`; the recall's stays off): the
    # context is built, the graph written, and the reply is byte for byte the same.
    monkeypatch.setattr(hookadapter, "via_enabled", lambda: True)
    built = ups("s2")
    assert len(list(graph.glob("*.json"))) == 1
    assert built == skipped
    recs = [x for x in _log_lines(home) if x.get("event") == "UserPromptSubmit"]
    assert "context" not in recs[-2] and recs[-1]["context"] == 1


# --- #207 amendment 3: the short-prompt session head (Q3) and the queries nudge (Q8) --------

from bantamkit import hookadapter as H  # noqa: E402


def _TEXT(text):  # noqa: N802 - a record-builder, spelled like the block it builds
    return {"type": "text", "text": text}


def _rec(text=None, *, content=None, **kw):
    r = {"type": "user", "message": {"content": text if content is None else content}, **kw}
    return json.dumps(r, ensure_ascii=False)


def test_the_head_constants():
    assert (H.HEAD_SHORT, H.HEAD_CUT, H.TAIL_BYTES) == (80, 500, 262144)


def test_previous_prompt_rules(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(
        "\n".join(
            [
                _rec("first prompt"),
                _rec("side", isSidechain=True),
                _rec("meta", isMeta=True),
                _rec("<command-name>/clear</command-name>"),
                _rec("[Request interrupted by user]"),
                _rec(content=[{"type": "tool_result", "content": "x"}]),
                json.dumps({"type": "assistant", "message": {"content": "hi"}}),
                _rec(content=[_TEXT("  second "), _TEXT("part")]),
                "not json",
                _rec("current"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert H._previous_prompt(str(t), "current") == "second \npart"
    assert H._previous_prompt(str(t), "  current ") == "second \npart"  # compared stripped
    assert H._previous_prompt(str(t), "other") == "current"


def test_previous_prompt_drops_every_trailing_copy_of_the_current_prompt(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join([_rec("before"), _rec("now"), _rec(" now ")]) + "\n", encoding="utf-8")
    assert H._previous_prompt(str(t), "now") == "before"
    t.write_text("\n".join([_rec("now"), _rec("before")]) + "\n", encoding="utf-8")
    assert H._previous_prompt(str(t), "now") == "before"  # not yet written: the last one


def test_previous_prompt_drops_the_partial_first_line_of_the_tail(tmp_path):
    t = tmp_path / "t.jsonl"
    head = _rec("x" * (H.TAIL_BYTES + 10))  # this whole line straddles the 256 KiB boundary
    t.write_text(head + "\n" + _rec("kept") + "\n", encoding="utf-8")
    assert H._previous_prompt(str(t), "now") == "kept"
    t.write_text(head + "\n", encoding="utf-8")
    assert H._previous_prompt(str(t), "now") == ""
    # the cut line is dropped even when what is left of it parses: the tail starts EXACTLY at
    # a record's `{`, but the line began earlier (junk ahead of it), so it is not a record
    ghost = _rec("g" * (H.TAIL_BYTES - 1 - len(_rec(""))))
    assert len(ghost.encode("utf-8")) == H.TAIL_BYTES - 1
    t.write_text("junk" + ghost + "\n", encoding="utf-8")
    assert H._previous_prompt(str(t), "now") == ""
    # a prompt that starts before the tail is not read, even when its line ends inside it
    t.write_text(_rec("y" * 100) + "\n" + "z" * (H.TAIL_BYTES - 10) + "\n", encoding="utf-8")
    assert H._previous_prompt(str(t), "now") == ""


def test_previous_prompt_never_raises(tmp_path):
    assert H._previous_prompt(str(tmp_path / "missing.jsonl"), "x") == ""
    assert H._previous_prompt(str(tmp_path), "x") == ""  # a directory
    assert H._previous_prompt("", "x") == ""
    t = tmp_path / "bad.jsonl"
    t.write_bytes(b"\xff\xfe\n" + _rec("ok").encode("utf-8") + b"\n")
    assert H._previous_prompt(str(t), "x") == "ok"


def test_head_query_only_for_short_prompts(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(_rec("p" * 600) + "\n", encoding="utf-8")
    assert H._head_query("ok?", str(t)) == "ok?\n" + "p" * 500
    assert H._head_query("x" * 79, str(t)) is not None
    assert H._head_query("x" * 80, str(t)) is None
    assert H._head_query("\U0001F414" * 79, str(t)) is not None  # 79 code points, 158 UTF-16 units
    assert H._head_query("\U0001F414" * 80, str(t)) is None
    assert H._head_query("ok?", str(tmp_path / "none.jsonl")) is None
    assert H._head_query("ok?", "") is None


def test_a_short_prompt_borrows_the_previous_prompt_for_its_recall(tmp_path):
    home, cwd = _bed(tmp_path, "head")
    _save(
        cwd / ".bantamkit" / "memory",
        "reference",
        "conformance-gate",
        "the gate is zero failures, never a total",
        "body",
    )
    t = tmp_path / "head" / "t.jsonl"
    t.write_text(_rec("what does the conformance gate demand") + "\n", encoding="utf-8")
    prompt = "and how do I run that?"
    with_head = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "transcript_path": str(t)},
        home=home,
        cwd=cwd,
    )
    assert with_head.returncode == 0, with_head.stderr
    ctx = json.loads(with_head.stdout.decode())["hookSpecificOutput"]["additionalContext"]
    assert "[conformance-gate]" in ctx
    without = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": prompt}, home=home, cwd=cwd,
        session="another-session",
    )
    assert without.returncode == 0, without.stderr
    assert without.stdout == b""
    missing = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": prompt,
         "transcript_path": str(tmp_path / "nope.jsonl")},
        home=home, cwd=cwd, session="third-session",
    )
    assert missing.returncode == 0 and missing.stdout == b"" and missing.stderr == b""


_NUDGE = (
    "[bantamkit] 1 of 1 facts have no likely-prompt queries yet; call "
    "mcp__bantamkit__memory_queries with {} to list them and write their queries."
)


def test_session_start_nudges_while_a_fact_has_no_queries(tmp_path, monkeypatch):
    home, cwd = _bed(tmp_path, "nudge")
    start = {"hook_event_name": "SessionStart", "source": "startup"}

    def ctx() -> str:
        done = _run_hook(start, home=home, cwd=cwd)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout.decode())["hookSpecificOutput"]["additionalContext"]

    assert "likely-prompt queries" not in ctx()  # zero facts: no line
    store = cwd / ".bantamkit" / "memory"
    _save(store, "project", "the-project-fact", "what this checkout is for", "body")
    got = ctx()
    assert _NUDGE in got
    assert got.index("[bantamkit] Toolbox is live") < got.index(_NUDGE)
    from bantamkit.memory.component import Memory

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    w = Memory(store).queries_write([{"name": "the-project-fact", "queries": ["what is it"]}])
    assert w["result"] == "written"
    assert "likely-prompt queries" not in ctx()


# --- 7b. PostToolUse[Write|Edit|MultiEdit] — the native memory mirror (#228) -------------


def _native_bed(tmp_path: Path, label: str) -> tuple[Path, Path, Path, Path]:
    """home, cwd, native dir (dirname(transcript)/memory), transcript path."""
    home, cwd = _bed(tmp_path, label)
    host = tmp_path / f"{label}-host"
    native = host / "memory"
    native.mkdir(parents=True)
    (native / "MEMORY.md").write_text("# Memory index\n", encoding="utf-8")
    transcript = host / "session.jsonl"
    transcript.write_text("", encoding="utf-8")
    return home, cwd, native, transcript


def _native_fact(
    name: str = "lesson-one",
    description: str = '"a lesson — with an em dash"',
    type_: str = "feedback",
    body: str = "The lesson.\n\n**Why:** because [[other-fact]] said so.\n",
    extra_meta: str = "",
    links: str = "links:\n- first-link\n",
) -> str:
    return (
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n  node_type: memory\n"
        f"  type: {type_}\n{extra_meta}{links}---\n\n{body}"
    )


def _write_payload(file: Path, transcript: Path, tool: str = "Write") -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "tool_input": {"file_path": str(file), "content": "x"},
        "transcript_path": str(transcript),
    }


def _mirror_lines(home: Path) -> list[dict]:
    return [x for x in _log_lines(home) if str(x.get("action", "")).startswith("mirror")]


def test_a_native_write_is_mirrored_into_the_project_store(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-write")
    store = cwd / ".bantamkit" / "memory"
    _save(store, "project", "seed", "a seed fact so the store exists", "body")
    file = native / "lesson-one.md"
    file.write_text(_native_fact(), encoding="utf-8")

    done = _run_hook(_write_payload(file, transcript), home=home, cwd=cwd)

    assert done.returncode == 0, done.stderr
    assert done.stdout == b"", "the mirror emits nothing to the host"
    line = _mirror_lines(home)[0]
    assert line["action"] == "mirrored"
    assert line["name"] == "lesson-one"
    assert line["nativeBranch"] == "transcript"
    assert line["file"] == str(file)
    assert line["budgetSource"] == "default"
    text = (store / "facts" / "lesson-one.md").read_text(encoding="utf-8")
    assert "type: feedback" in text
    assert "description: a lesson — with an em dash" in text
    assert "- first-link" in text and "- other-fact" in text
    assert "The lesson." in text
    assert file.read_text(encoding="utf-8") == _native_fact(), "the native file is untouched"
    ledger_file = home / ".bantamkit" / "hooks" / "ledger-probe-session.json"
    ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert ledger["saved"] == 1


def test_an_edit_replaces_the_mirrored_fact_rather_than_duplicating_it(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-edit")
    store = cwd / ".bantamkit" / "memory"
    file = native / "lesson-one.md"
    file.write_text(_native_fact(), encoding="utf-8")
    _run_hook(_write_payload(file, transcript), home=home, cwd=cwd)
    file.write_text(_native_fact(body="The lesson, revised.\n"), encoding="utf-8")

    _run_hook(_write_payload(file, transcript, tool="Edit"), home=home, cwd=cwd)

    facts = sorted(p.name for p in (store / "facts").iterdir())
    assert facts == ["lesson-one.md"]
    assert "revised" in (store / "facts" / "lesson-one.md").read_text(encoding="utf-8")
    assert [x["action"] for x in _mirror_lines(home)] == ["mirrored", "mirrored"]


def test_the_export_stub_is_never_imported_back(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-stub")
    file = native / "stub.md"
    file.write_text(_native_fact(name="stub", extra_meta="  source: bantamkit\n"), encoding="utf-8")

    _run_hook(_write_payload(file, transcript), home=home, cwd=cwd)

    line = _mirror_lines(home)[0]
    assert (line["action"], line["reason"]) == ("mirror-skipped", "export-stub")
    assert not (cwd / ".bantamkit" / "memory" / "facts").exists() or not list(
        (cwd / ".bantamkit" / "memory" / "facts").iterdir()
    )


def test_a_name_is_normalised_and_an_unusable_one_is_skipped(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-name")
    good = native / "Weird.Name_1.md"
    good.write_text(_native_fact(name="Weird.Name_1"), encoding="utf-8")
    bad = native / "escape.md"
    bad.write_text(_native_fact(name="../escape"), encoding="utf-8")

    _run_hook(_write_payload(good, transcript), home=home, cwd=cwd)
    _run_hook(_write_payload(bad, transcript), home=home, cwd=cwd)

    lines = _mirror_lines(home)
    assert (lines[0]["action"], lines[0]["name"]) == ("mirrored", "weird-name-1")
    assert (lines[1]["action"], lines[1]["reason"]) == ("mirror-skipped", "name")
    assert "name" not in lines[1]


def test_an_unknown_type_becomes_project_and_an_empty_body_is_skipped(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-type")
    typed = native / "odd-type.md"
    typed.write_text(_native_fact(name="odd-type", type_="lesson"), encoding="utf-8")
    empty = native / "no-body.md"
    empty.write_text(_native_fact(name="no-body", body=""), encoding="utf-8")

    _run_hook(_write_payload(typed, transcript), home=home, cwd=cwd)
    _run_hook(_write_payload(empty, transcript), home=home, cwd=cwd)

    lines = _mirror_lines(home)
    assert lines[0]["action"] == "mirrored"
    odd = cwd / ".bantamkit" / "memory" / "facts" / "odd-type.md"
    assert "type: project" in odd.read_text(encoding="utf-8")
    assert (lines[1]["action"], lines[1]["reason"]) == ("mirror-skipped", "body")


def test_memory_md_and_files_outside_the_native_dir_are_not_mirrored(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-outside")
    elsewhere = cwd / "docs" / "memory"
    elsewhere.mkdir(parents=True)
    note = elsewhere / "notes.md"
    note.write_text(_native_fact(name="notes"), encoding="utf-8")
    plain = cwd / "README.md"
    plain.write_text("# readme\n", encoding="utf-8")

    _run_hook(_write_payload(native / "MEMORY.md", transcript), home=home, cwd=cwd)
    _run_hook(_write_payload(note, transcript), home=home, cwd=cwd)
    _run_hook(_write_payload(plain, transcript), home=home, cwd=cwd)

    lines = _mirror_lines(home)
    assert len(lines) == 1, lines
    assert (lines[0]["action"], lines[0]["reason"]) == ("mirror-skipped", "not-native")
    assert not (cwd / ".bantamkit" / "memory").exists()


def test_a_budget_refusal_is_logged_and_the_store_is_unchanged(tmp_path):
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-refused")
    store = cwd / ".bantamkit" / "memory"
    _save(store, "project", "seed", "a seed fact so the store exists", "body")
    _register(cwd, "--index-budget", "64")
    before = sorted(p.name for p in (store / "facts").iterdir())
    file = native / "lesson-one.md"
    file.write_text(_native_fact(), encoding="utf-8")

    done = _run_hook(_write_payload(file, transcript), home=home, cwd=cwd)

    assert done.returncode == 0, done.stderr
    line = _mirror_lines(home)[0]
    assert line["action"] == "mirror-refused"
    assert line["reason"]
    assert sorted(p.name for p in (store / "facts").iterdir()) == before
    assert not (home / ".bantamkit" / "hooks" / "ledger-probe-session.json").exists() or json.loads(
        (home / ".bantamkit" / "hooks" / "ledger-probe-session.json").read_text(encoding="utf-8")
    ).get("saved", 0) == 0


def test_stop_nudges_after_a_native_write_that_was_not_mirrored(tmp_path):
    home, cwd = _bed(tmp_path, "stop-native")
    transcript = tmp_path / "stop-native.jsonl"
    tool_use = lambda name, inp: json.dumps(  # noqa: E731
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]},
        }
    )
    lines = [tool_use("Bash", {"command": "ls"}) for _ in range(20)]
    fact = "/home/u/.claude/projects/p/memory/fact.md"
    lines.append(tool_use("Write", {"file_path": fact, "content": "x"}))
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")

    done = _run_hook(
        {"hook_event_name": "Stop", "transcript_path": str(transcript)},
        home=home,
        cwd=cwd,
        session="stop-native",
    )

    assert b'"decision":"block"' in done.stdout or b'"decision": "block"' in done.stdout
    assert [x for x in _log_lines(home) if x["event"] == "Stop"][-1]["action"] == "nudge"


# --- J74-4: divergences found by running both hooks over one bed (#228) --------------------


def test_a_crlf_native_file_is_mirrored_as_python_reads_it(tmp_path):
    # Text mode translates `\r\n` and a lone `\r` to `\n` before the `---\n` split; the port
    # read the bytes raw and skipped the file as `frontmatter`.
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-crlf")
    file = native / "crlf.md"
    file.write_bytes(
        b"---\r\nname: crlf\r\ndescription: windows line ends\r\n---\r\n"
        b"\r\nbody one\r\nbody two\rthree\r\n"
    )

    _run_hook(_write_payload(file, transcript), home=home, cwd=cwd)

    line = _mirror_lines(home)[0]
    assert (line["action"], line["name"]) == ("mirrored", "crlf")
    text = (cwd / ".bantamkit" / "memory" / "facts" / "crlf.md").read_bytes()
    assert b"\r" not in text
    assert b"body one\nbody two\nthree\n" in text


def test_a_frontmatter_with_no_keys_is_a_frontmatter_skip(tmp_path):
    # `{}` is a dict to PyYAML and was a `description` skip here, while the port refuses it
    # (#120's empty flow mapping) as `frontmatter`; an empty or comment-only frontmatter is
    # `None` to PyYAML. All three are one rule now: no keys, no fact.
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-nokeys")
    files = []
    for label, front in (("braces", "{}\n"), ("empty", ""), ("comment", "# only a comment\n")):
        file = native / f"{label}.md"
        file.write_text(f"---\n{front}---\n\nbody\n", encoding="utf-8")
        files.append(file)

    for file in files:
        _run_hook(_write_payload(file, transcript), home=home, cwd=cwd)

    skipped = [(x["action"], x["reason"]) for x in _mirror_lines(home)]
    assert skipped == [("mirror-skipped", "frontmatter")] * 3


def test_a_falsy_or_non_scalar_description_is_a_description_skip(tmp_path):
    # `false` and `0` are falsy to Python and were mirrored by the port as 'False' and '0';
    # a list or a mapping was mirrored on both sides under two different spellings
    # (`str()` vs `String()`). None of them is a description.
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-desc")
    shapes = {
        "d-false": "description: false\n",
        "d-zero": "description: 0\n",
        "d-block": "description:\n- a\n- b\n",
        "d-flow": "description: [a, b]\n",
        "d-map": "description:\n  a: 1\n",
    }
    for name, front in shapes.items():
        text = f"---\nname: {name}\n{front}---\n\nbody\n"
        (native / f"{name}.md").write_text(text, encoding="utf-8")

    for name in shapes:
        _run_hook(_write_payload(native / f"{name}.md", transcript), home=home, cwd=cwd)

    assert [(x["action"], x["reason"], x["name"]) for x in _mirror_lines(home)] == [
        ("mirror-skipped", "description", name) for name in shapes
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_a_path_that_does_not_exist_resolves_through_a_link_the_way_realpath_does(
    tmp_path,
):
    # `os.path.realpath` resolves the existing prefix of a missing path; the port's
    # `realpathSync` threw and fell back to `path.resolve`, which kept the link, so the
    # same Edit was `frontmatter` here and `not-native` there.
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    real = tmp_path / "real"
    (real / "memory").mkdir(parents=True)
    home.mkdir()
    cwd.mkdir()
    (real / "memory" / "MEMORY.md").write_text("# index\n", encoding="utf-8")
    transcript = real / "session.jsonl"
    transcript.write_text("", encoding="utf-8")
    (tmp_path / "link").symlink_to(real)

    missing = tmp_path / "link" / "memory" / "nosuch" / "gone.md"
    _run_hook(
        _write_payload(missing, transcript, tool="Edit"),
        home=home,
        cwd=cwd,
    )

    skipped = [(x["action"], x["reason"]) for x in _mirror_lines(home)]
    assert skipped == [("mirror-skipped", "frontmatter")]


def test_a_path_spelled_in_another_case_is_not_the_native_directory(tmp_path):
    # `os.path.realpath` never folds case; the port's `realpathSync.native` does on a
    # case-insensitive volume (APFS, NTFS), so the port mirrored a path the reference did not.
    home, cwd, native, transcript = _native_bed(tmp_path, "mirror-case")
    file = native / "cased.md"
    file.write_text(_native_fact(name="cased"), encoding="utf-8")
    spelled = Path(str(file).replace("mirror-case-host", "MIRROR-CASE-HOST"))
    if not spelled.exists():
        pytest.skip("case-sensitive volume: the other spelling is a different path")

    _run_hook(_write_payload(spelled, transcript), home=home, cwd=cwd)

    skipped = [(x["action"], x["reason"]) for x in _mirror_lines(home)]
    assert skipped == [("mirror-skipped", "not-native")]


# --- #205 Task 5: the skill-audit SessionStart line ----------------------------------------


def test_session_start_names_a_new_finding_once_and_then_adds_zero_bytes(tmp_path):
    """The bar (spec): with nothing new, SessionStart adds 0 bytes. Run it with no record, then
    twice over one record: the first carries the line LAST, the second equals the first run."""
    from test_skillreport import FULL, LINE, _put, _rec

    home, cwd = _bed(tmp_path, "skillline")
    start = {"hook_event_name": "SessionStart", "source": "startup"}
    ctx = lambda o: o["hookSpecificOutput"]["additionalContext"]  # noqa: E731
    plain = json.loads(_run_hook(start, home=home, cwd=cwd).stdout)
    assert _log_lines(home)[-1]["skillAuditBytes"] == 0
    _put(home, _rec(FULL))
    first = json.loads(_run_hook(start, home=home, cwd=cwd).stdout)
    assert ctx(first) == ctx(plain) + "\n\n" + LINE
    assert _log_lines(home)[-1]["skillAuditBytes"] == len(LINE.encode("utf-8"))
    again = json.loads(_run_hook(start, home=home, cwd=cwd).stdout)
    assert ctx(again) == ctx(plain)
    assert _log_lines(home)[-1]["skillAuditBytes"] == 0
