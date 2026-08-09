"""Shift-work: the checkpoint schema asset, its loader, and the driver loop."""

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from bantamkit.assets import AssetNotFound, load_schema
from bantamkit.contract import schema_error

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIFTWORK = REPO_ROOT / "tools" / "shiftwork"
EXAMPLE = SHIFTWORK / "example-checkpoint.json"

sys.path.insert(0, str(SHIFTWORK))
import driver as shiftwork  # noqa: E402  (repo tool, not a package on the wheel)


@pytest.fixture
def schema():
    return load_schema("shiftwork-checkpoint")


@pytest.fixture
def example():
    return json.loads(EXAMPLE.read_text())


# --- load_schema -----------------------------------------------------------


def test_load_schema_returns_parsed_dict(schema):
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["version"]["const"] == 1


def test_load_schema_missing_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    with pytest.raises(AssetNotFound, match="schema asset not found"):
        load_schema("shiftwork-checkpoint")


def test_shipped_schema_is_a_valid_2020_12_schema(schema):
    jsonschema.Draft202012Validator.check_schema(schema)


# --- the example checkpoint validates --------------------------------------


def test_example_checkpoint_validates(schema, example):
    assert schema_error(json.dumps(example), schema) is None


def test_example_carries_the_two_driver_deltas(example):
    """role (model dispatch) and until_cmd (machine-checkable wait) are why v1 exists."""
    assert {u["role"] for u in example["plan"]["units"]} == {"implementer", "reviewer"}
    process = next(e for e in example["state"]["external"] if e["kind"] == "process")
    assert "until_cmd" in process


def test_replanning_needs_no_schema_change(schema, example):
    """A planner unit is just a unit — that is the whole re-plan mechanism."""
    ckpt = copy.deepcopy(example)
    ckpt["plan"]["units"].append(
        {
            "id": "U9",
            "title": "Re-cut remaining units after QA failures",
            "brief_path": ".shiftwork/briefs/U9.md",
            "status": "todo",
            "role": "planner",
            "depends_on": [],
            "verify": "test -f .shiftwork/briefs/U10.md",
        }
    )
    assert schema_error(json.dumps(ckpt), schema) is None


# --- mutations are rejected ------------------------------------------------


def mutate(example, path, value):
    ckpt = copy.deepcopy(example)
    node = ckpt
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return ckpt


def test_wrong_major_version_rejected(schema, example):
    assert schema_error(json.dumps(mutate(example, ["version"], 2)), schema) is not None


def test_missing_cursor_rejected(schema, example):
    ckpt = copy.deepcopy(example)
    del ckpt["plan"]["cursor"]
    assert schema_error(json.dumps(ckpt), schema) is not None


def test_bad_status_enum_rejected(schema, example):
    ckpt = mutate(example, ["plan", "units", 1, "status"], "in-progress")
    assert schema_error(json.dumps(ckpt), schema) is not None


def test_bad_role_enum_rejected(schema, example):
    ckpt = mutate(example, ["plan", "units", 1, "role"], "qa")
    assert schema_error(json.dumps(ckpt), schema) is not None


def test_non_list_open_questions_rejected(schema, example):
    ckpt = mutate(example, ["handoff", "open_questions"], "none")
    assert schema_error(json.dumps(ckpt), schema) is not None


def test_bad_external_kind_rejected(schema, example):
    ckpt = mutate(example, ["state", "external", 1, "kind"], "webhook")
    assert schema_error(json.dumps(ckpt), schema) is not None


def test_unknown_top_level_key_rejected(schema, example):
    """The checkpoint is an index, not a journal: strays are a smell, not a feature."""
    assert schema_error(json.dumps(mutate(example, ["journal"], [])), schema) is not None


def test_history_entries_allow_extra_annotation(schema, example):
    """history/retro are the free-text space — extra keys there must stay legal."""
    ckpt = copy.deepcopy(example)
    ckpt["history"][0]["seq"] = 4
    assert schema_error(json.dumps(ckpt), schema) is None


def test_history_beyond_five_entries_rejected(schema, example):
    """The ring buffer is structural: a journal in `history` is a rejected file."""
    ckpt = copy.deepcopy(example)
    entry = ckpt["history"][0]
    six = [dict(entry, unit=f"U{i}") for i in range(6)]
    assert schema_error(json.dumps(mutate(example, ["history"], six)), schema) is not None
    assert schema_error(json.dumps(mutate(example, ["history"], six[:5])), schema) is None


# --- driver: harness -------------------------------------------------------


class Done:
    def __init__(self, returncode=0):
        self.returncode = returncode


class FakeRunner:
    """Stands in for subprocess.run: shell probes, scripted sessions, notifications."""

    def __init__(self, sessions=(), until_results=()):
        self.sessions = list(sessions)
        self.until_results = list(until_results)
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if isinstance(cmd, str):  # until_cmd runs with shell=True
            code = self.until_results.pop(0) if self.until_results else 0
            return Done(code)
        if cmd and cmd[0] == "claude":
            behavior = self.sessions.pop(0) if self.sessions else None
            return Done(behavior() or 0 if callable(behavior) else 0)
        return Done(0)  # notify_cmd

    @property
    def sessions_run(self):
        return [c for c in self.calls if not isinstance(c, str) and c[0] == "claude"]

    @property
    def notifications(self):
        return [c for c in self.calls if not isinstance(c, str) and c[0] == "notify"]


class FakeClock:
    def __init__(self, step=1.0):
        self.t = 0.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


def base_checkpoint():
    ckpt = json.loads(EXAMPLE.read_text())
    ckpt["plan"]["units"] = [u for u in ckpt["plan"]["units"] if u["id"] in {"U1", "U3"}]
    ckpt["state"]["external"] = []
    return ckpt


def make_driver(tmp_path, ckpt, *, sessions=(), until=(), alive=False, **config):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(ckpt) if isinstance(ckpt, dict) else ckpt)
    runner = FakeRunner(sessions=sessions, until_results=until)
    sleeps = []
    config.setdefault("notify_cmd", ["notify"])
    driver = shiftwork.Driver(
        path,
        shiftwork.Config.from_dict(config),
        runner=runner,
        sleep=sleeps.append,
        clock=FakeClock(),
        now=lambda: 1770000000.0,
        pid=4242,
        is_alive=lambda pid: alive,
        out=None,
    )
    return SimpleNamespace(driver=driver, path=path, runner=runner, sleeps=sleeps, dir=tmp_path)


def edit(path, **changes):
    """Return a session behavior that mutates the checkpoint (i.e. clocks out)."""

    def behave():
        ckpt = json.loads(path.read_text())
        if changes.get("finish"):
            for unit in ckpt["plan"]["units"]:
                unit["status"] = "done"
        if changes.get("note"):
            ckpt["handoff"]["next_action"] = changes["note"]
        if changes.get("escalate"):
            ckpt["handoff"]["open_questions"] = [changes["escalate"]]
        path.write_text(json.dumps(ckpt))
        return changes.get("code", 0)

    return behave


def noop(code=0):
    """A session that exits without writing the checkpoint — no progress."""
    return lambda: code


def log_lines(harness):
    log = harness.dir / "driver-log.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def driver_state(harness):
    return json.loads((harness.dir / "driver-state.json").read_text())


# --- driver: exits ---------------------------------------------------------


def test_success_when_all_units_terminal(tmp_path):
    ckpt = base_checkpoint()
    for unit in ckpt["plan"]["units"]:
        unit["status"] = "dropped"
    h = make_driver(tmp_path, ckpt)
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert h.runner.sessions_run == []
    assert h.runner.notifications  # the driver always notifies on a terminal exit


def test_success_after_a_session_finishes_the_job(tmp_path):
    h = make_driver(tmp_path, base_checkpoint())
    h.runner.sessions = [edit(h.path, finish=True)]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert len(h.runner.sessions_run) == 1
    assert driver_state(h)["sessions"] == 1


def test_escalate_on_open_questions(tmp_path):
    ckpt = base_checkpoint()
    ckpt["handoff"]["open_questions"] = ["Which layer owns SCHEMA_INSTRUCTION?"]
    h = make_driver(tmp_path, ckpt)
    assert h.driver.run() == shiftwork.EXIT_ESCALATE
    assert h.runner.sessions_run == []


def test_escalate_when_a_session_raises_an_open_question(tmp_path):
    h = make_driver(tmp_path, base_checkpoint())
    h.runner.sessions = [edit(h.path, escalate="head_sha moved under us")]
    assert h.driver.run() == shiftwork.EXIT_ESCALATE
    assert len(h.runner.sessions_run) == 1


def test_escalate_on_unparseable_checkpoint_without_overwriting(tmp_path):
    h = make_driver(tmp_path, "{not json at all")
    before = h.path.read_bytes()
    assert h.driver.run() == shiftwork.EXIT_ESCALATE
    assert h.path.read_bytes() == before
    assert h.runner.sessions_run == []


def test_escalate_on_unknown_major_version(tmp_path):
    ckpt = base_checkpoint()
    ckpt["version"] = 2
    h = make_driver(tmp_path, ckpt)
    assert h.driver.run() == shiftwork.EXIT_ESCALATE


def test_escalate_on_dangling_cursor(tmp_path):
    ckpt = base_checkpoint()
    ckpt["plan"]["cursor"] = "U99"
    h = make_driver(tmp_path, ckpt)
    assert h.driver.run() == shiftwork.EXIT_ESCALATE


def test_budget_exit_on_session_cap(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_sessions=1)
    h.runner.sessions = [edit(h.path, note="partial work landed")]
    assert h.driver.run() == shiftwork.EXIT_BUDGET
    assert len(h.runner.sessions_run) == 1


def test_budget_exit_on_wall_clock_cap(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_wall_clock_seconds=1)
    assert h.driver.run() == shiftwork.EXIT_BUDGET
    assert h.runner.sessions_run == []


def test_stalled_after_max_retries_of_no_progress(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_retries=2)
    h.runner.sessions = [noop(), noop(), noop(), noop()]
    assert h.driver.run() == shiftwork.EXIT_STALLED
    assert len(h.runner.sessions_run) == 3  # max_retries + 1
    assert driver_state(h)["retries"] == {"U3": 3}


def test_clean_exit_without_clock_out_counts_as_a_retry(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_retries=0)
    h.runner.sessions = [noop(0)]
    assert h.driver.run() == shiftwork.EXIT_STALLED
    assert log_lines(h)[0]["exit"] == 0
    assert log_lines(h)[0]["progressed"] is False


def test_hash_delta_resets_the_retry_counter(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_retries=1)
    h.runner.sessions = [
        noop(),  # retries[U3] = 1
        edit(h.path, note="landed half the unit"),  # progress -> reset
        noop(),  # retries[U3] = 1 again, not 2
        edit(h.path, finish=True),
    ]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert len(h.runner.sessions_run) == 4


def test_non_zero_exit_with_progress_is_trusted_and_flagged(tmp_path):
    h = make_driver(tmp_path, base_checkpoint())
    h.runner.sessions = [edit(h.path, finish=True, code=1)]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert log_lines(h)[0]["anomaly"]


def test_session_timeout_counts_as_no_progress(tmp_path):
    def timeout():
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    h = make_driver(tmp_path, base_checkpoint(), max_retries=0)
    h.runner.sessions = [timeout]
    assert h.driver.run() == shiftwork.EXIT_STALLED
    assert log_lines(h)[0]["exit"] == -1


# --- driver: waiting on externals ------------------------------------------


def running_external(ckpt, until_cmd="grep -q DONE sweep.log"):
    ckpt["state"]["external"] = [
        {"kind": "process", "ref": "pid 13031", "until_cmd": until_cmd, "status": "running"}
    ]
    return ckpt


def test_until_cmd_polls_with_backoff_then_proceeds(tmp_path):
    h = make_driver(tmp_path, running_external(base_checkpoint()), until=[1, 1, 0])
    h.runner.sessions = [edit(h.path, finish=True)]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert h.sleeps == [30, 60]  # 30s -> exponential, capped at 300s
    assert len(h.runner.sessions_run) == 1


def test_backoff_is_capped(tmp_path):
    h = make_driver(tmp_path, running_external(base_checkpoint()), until=[1] * 8 + [0])
    h.runner.sessions = [edit(h.path, finish=True)]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert h.sleeps == [30, 60, 120, 240, 300, 300, 300, 300]


def test_until_cmd_that_never_succeeds_escalates(tmp_path):
    h = make_driver(
        tmp_path,
        running_external(base_checkpoint()),
        until=[1] * 10,
        external_timeout_seconds=30,
    )
    assert h.driver.run() == shiftwork.EXIT_ESCALATE
    assert h.runner.sessions_run == []


def test_settled_external_is_not_waited_on(tmp_path):
    ckpt = base_checkpoint()
    ckpt["state"]["external"] = [{"kind": "pr", "ref": "#12", "status": "open"}]
    h = make_driver(tmp_path, ckpt)
    h.runner.sessions = [edit(h.path, finish=True)]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert h.sleeps == []


# --- driver: lock, log, dispatch -------------------------------------------


def test_second_driver_refuses_to_start(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), alive=True)
    (tmp_path / "driver.lock").write_text(json.dumps({"pid": 999, "started": 1.0}))
    assert h.driver.run() == shiftwork.EXIT_LOCKED
    assert h.runner.sessions_run == []
    assert json.loads((tmp_path / "driver.lock").read_text())["pid"] == 999


def test_lock_refusal_notifies_naming_the_holder(tmp_path):
    """A refusal that only prints to stderr is invisible to whoever walked away."""
    h = make_driver(tmp_path, base_checkpoint(), alive=True)
    (tmp_path / "driver.lock").write_text(json.dumps({"pid": 999, "started": 1.0}))
    assert h.driver.run() == shiftwork.EXIT_LOCKED
    message = h.runner.notifications[0][-1]
    assert message.startswith("shift-work refused to start:")
    assert "pid 999" in message


def test_lock_acquisition_is_atomic(tmp_path):
    """Two drivers racing on a free lock: exactly one wins, no read-then-write gap."""
    lock = tmp_path / "driver.lock"
    first = shiftwork.DriverLock(lock, pid=1001, now=lambda: 1.0, is_alive=lambda pid: True)
    second = shiftwork.DriverLock(lock, pid=1002, now=lambda: 2.0, is_alive=lambda pid: True)
    assert first.acquire() is None
    assert "pid 1001" in second.acquire()
    assert second.held is False
    assert json.loads(lock.read_text())["pid"] == 1001
    second.release()  # a loser must never delete the winner's lock
    assert lock.exists()


def test_stale_lock_is_taken_over(tmp_path):
    ckpt = base_checkpoint()
    for unit in ckpt["plan"]["units"]:
        unit["status"] = "done"
    h = make_driver(tmp_path, ckpt, alive=False)  # pid 999 is dead
    (tmp_path / "driver.lock").write_text(json.dumps({"pid": 999, "started": 1.0}))
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert not (tmp_path / "driver.lock").exists()  # released on exit


def test_one_log_line_per_session(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_retries=1)
    h.runner.sessions = [noop(), edit(h.path, finish=True)]
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    lines = log_lines(h)
    assert len(lines) == 2
    assert [line["seq"] for line in lines] == [1, 2]
    assert {line["cursor"] for line in lines} == {"U3"}
    assert lines[0]["role"] == "implementer"
    assert lines[1]["progressed"] is True
    assert set(lines[0]) >= {"ts", "seq", "cursor", "role", "exit", "duration", "progressed"}


def test_role_selects_model_and_allowed_tools(tmp_path):
    ckpt = base_checkpoint()
    ckpt["plan"]["units"][1]["role"] = "reviewer"
    h = make_driver(tmp_path, ckpt)
    h.runner.sessions = [edit(h.path, finish=True)]
    h.driver.run()
    cmd = h.runner.sessions_run[0]
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    assert cmd[cmd.index("--allowedTools") + 1] == "Read,Grep,Glob"
    assert "--permission-mode" in cmd and "acceptEdits" in cmd
    assert "--dangerously-skip-permissions" not in cmd


def test_skip_permissions_only_behind_explicit_opt_in(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), dangerously_skip_permissions=True)
    h.runner.sessions = [edit(h.path, finish=True)]
    h.driver.run()
    cmd = h.runner.sessions_run[0]
    assert "--dangerously-skip-permissions" in cmd
    assert "--permission-mode" not in cmd


def test_unknown_role_escalates(tmp_path):
    ckpt = base_checkpoint()
    ckpt["plan"]["units"][1]["role"] = "qa"
    h = make_driver(tmp_path, ckpt)
    assert h.driver.run() == shiftwork.EXIT_ESCALATE


def test_clock_in_prompt_is_constant_and_carries_no_unit_state(tmp_path):
    ckpt = base_checkpoint()
    h = make_driver(tmp_path, ckpt, max_retries=1)
    h.runner.sessions = [noop(), edit(h.path, finish=True)]
    h.driver.run()
    prompts = {cmd[cmd.index("-p") + 1] for cmd in h.runner.sessions_run}
    assert len(prompts) == 1
    prompt = prompts.pop()
    assert str(h.path) in prompt
    assert "U3" not in prompt
    assert prompt == shiftwork.CLOCK_IN_PROMPT.replace("<path>", str(h.path))
    # v1 reads the checkpoint with `json` alone, so the prompt must say so.
    assert "keeping it JSON" in prompt


def test_notify_cmd_receives_the_terminal_message(tmp_path):
    ckpt = base_checkpoint()
    ckpt["handoff"]["open_questions"] = ["ask the user"]
    h = make_driver(tmp_path, ckpt)
    h.driver.run()
    assert h.runner.notifications[0][-1].startswith("shift-work ESCALATE:")


def test_retry_counters_live_outside_the_checkpoint(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_retries=0)
    h.runner.sessions = [noop()]
    h.driver.run()
    assert "retries" not in h.path.read_text()
    assert driver_state(h)["retries"] == {"U3": 1}


def test_driver_resumes_from_persisted_state(tmp_path):
    h = make_driver(tmp_path, base_checkpoint(), max_sessions=2)
    (tmp_path / "driver-state.json").write_text(
        json.dumps({"seq": 5, "sessions": 2, "retries": {"U3": 1}})
    )
    assert h.driver.run() == shiftwork.EXIT_BUDGET
    assert h.runner.sessions_run == []


# --- driver: config --------------------------------------------------------


def test_shipped_driver_config_covers_every_role(schema):
    config = shiftwork.Config.load(SHIFTWORK / "driver.json")
    unit = schema["properties"]["plan"]["properties"]["units"]["items"]
    roles = set(unit["properties"]["role"]["enum"])
    assert set(config.roles) >= roles
    assert config.dangerously_skip_permissions is False


def test_config_defaults_apply_without_a_file():
    config = shiftwork.Config.load(None)
    assert set(config.roles) == {"planner", "implementer", "reviewer"}
    assert config.max_retries == 3


def test_empty_notify_cmd_disables_notification(tmp_path):
    ckpt = base_checkpoint()
    for unit in ckpt["plan"]["units"]:
        unit["status"] = "done"
    h = make_driver(tmp_path, ckpt, notify_cmd=[])
    assert h.driver.run() == shiftwork.EXIT_SUCCESS
    assert h.runner.calls == []


def test_main_runs_end_to_end_without_spawning(tmp_path):
    """CLI smoke: an already-finished job needs no session, so no real subprocess runs."""
    ckpt = base_checkpoint()
    for unit in ckpt["plan"]["units"]:
        unit["status"] = "done"
    (tmp_path / "checkpoint.json").write_text(json.dumps(ckpt))
    (tmp_path / "driver.json").write_text(json.dumps({"notify_cmd": []}))
    code = shiftwork.main(
        [
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            "--config",
            str(tmp_path / "driver.json"),
        ]
    )
    assert code == shiftwork.EXIT_SUCCESS
    assert (tmp_path / "driver-state.json").exists()
    assert not (tmp_path / "driver.lock").exists()
