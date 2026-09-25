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


def test_an_injection_leaves_every_fact_file_byte_and_mtime_identical(tmp_path):
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

    # CONTROL: the explicit path, on the same bed, still stamps — and only the hit.
    from bantamkit.memory.component import Memory

    Memory(store=store).recall("what is the conformance gate here")
    after = state()
    assert b"last_recalled: '" in after["conformance-gate.md"][0]
    assert after["conformance-gate.md"] != before["conformance-gate.md"]
    assert after["unrelated.md"] == before["unrelated.md"]


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
#: Hits the three `deployment`/`rollback`/`staging` facts, in this order (scores 8, 3, 3).
_PROMPT_A = "deployment path rollback procedure for the staging cluster"
#: Hits `unrelated-alpha` first and then two of A's three, measured through `Memory.layered`
#: on this bed -- so after A it is the MIXED case: one unseen header, two seen.
_PROMPT_C = "nothing shared here at all about the staging cluster"
_A_NAMES = ["deployment-rollback", "rollback-runbook", "staging-cluster-notes"]


def _dedupe_bed(tmp_path: Path, name: str) -> tuple[Path, Path]:
    home, cwd = _bed(tmp_path, name)
    for type_, fact, description in _DEDUPE_FACTS:
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
    fingerprint; (b) a body edit and (c) a new fact each produce a preview. The three (a)
    steps are checked to have really rewritten the file, or a skip would prove nothing."""
    from bantamkit.memory.component import Memory

    home, cwd = _bed(tmp_path, "stop-dream-redate")
    _two_layers(home, cwd)
    project = cwd / ".bantamkit" / "memory"
    _save(project, "project", "recalled-often", "the fact the operator recalls every turn", "body")
    fact = project / "facts" / "recalled-often.md"
    transcript = _transcript(cwd, tool_uses=1)

    _stop(home, cwd, transcript)  # S1: the first look previews
    fp1 = _dream_fingerprint(home)

    # (a1) an explicit recall dates the fact: null -> today, bytes AND mtime move.
    bytes_before, mtime_before = fact.read_bytes(), fact.stat().st_mtime_ns
    assert "recalled-often" in Memory(store=project).recall("operator recalls every turn")
    assert fact.read_bytes() != bytes_before and fact.stat().st_mtime_ns != mtime_before
    assert "last_recalled: '" in fact.read_text(encoding="utf-8"), "the recall dated it"
    _stop(home, cwd, transcript)  # S2
    # (a2) the same line re-dated to another day -- what tomorrow's recall writes.
    fact.write_text(
        re.sub(
            r"^last_recalled: .*$",
            "last_recalled: '2020-01-01'",
            fact.read_text(encoding="utf-8"),
            flags=re.M,
        ),
        encoding="utf-8",
    )
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
