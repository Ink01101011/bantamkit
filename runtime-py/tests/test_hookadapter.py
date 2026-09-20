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

SCOPE OF THIS UNIT (J62-3): the parser surface, the dispatch table, the failure posture, and
the SessionStart and UserPromptSubmit arms. The other six arms are J62-3B's; what is pinned
here is that dispatch RECOGNISES them and degrades visibly -- one log line naming the event,
nothing on stdout, exit 0 -- rather than crashing or silently succeeding differently.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
):
    """`--hook` with one payload on stdin, over a scratch HOME and a scratch cwd."""
    if raw is None:
        body: dict = {"cwd": str(cwd)}
        if session is not None:
            body["session_id"] = session
        body.update(payload or {})
        raw = json.dumps(body).encode("utf-8")
    return subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", "--hook"],
        capture_output=True,
        cwd=str(cwd),
        env=_env(home),
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
    """J62-3B lands PreToolUse / PostToolUse / PreCompact / PostCompact / Stop.

    Until it does, dispatch must KNOW those names: one log line that says the event was
    recognised and not served, nothing on stdout, exit 0. The alternative -- letting them
    fall into the `ignored` arm -- would make a missing port indistinguishable from an event
    that is none of bantamkit's business, which is the state J62-3B has to find.
    """
    home, cwd = _bed(tmp_path, "unported")
    for event in ("PreToolUse", "PostToolUse", "PreCompact", "PostCompact", "Stop"):
        done = _run_hook({"hook_event_name": event}, home=home, cwd=cwd)
        assert done.returncode == 0, (event, done.stderr)
        assert done.stdout == b"", (event, done.stdout)

    seen = {line["event"]: line.get("action") for line in _log_lines(home)}
    assert seen == {
        "PreToolUse": "unported",
        "PostToolUse": "unported",
        "PreCompact": "unported",
        "PostCompact": "unported",
        "Stop": "unported",
    }, seen


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
    assert "[bantamkit profile memory — 1 facts learned across projects]" in ctx
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
    assert "[bantamkit project memory — 1 facts]" in ctx
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
