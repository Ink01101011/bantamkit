#!/usr/bin/env python3
"""Shift-work driver: spawn clock-in/clock-out sessions until the job stops.

Dumb by construction. The driver holds zero work knowledge: it never reads
`job.goal`, never opens a brief, never interprets prose. It reads exactly the
machine-checkable fields — `version`, `handoff.open_questions`, unit `status`,
`plan.cursor`, `plan.units[].role` (dispatch) and `state.external[].until_cmd`
(wait) — and treats everything else as opaque bytes. All intelligence lives
inside sessions. If a proposed feature needs judgment, it belongs in a session.

Four terminal loop exits: SUCCESS (0), ESCALATE (10), BUDGET (20), STALLED
(30). Exit 40 is not a loop outcome — it is the startup refusal when another
live driver already holds `driver.lock`.

v1 simplifications, both forced by the stdlib-only rule (PyYAML is not stdlib):

* **The checkpoint file must be JSON.** The contract is YAML for humans and the
  shipped JSON Schema validates the parsed document either way, but sessions
  driven by this script write a `.json` checkpoint so the driver can read it
  with `json` alone.
* **The driver config is JSON too** (`driver.json`, not `driver.yaml`).

Usage:

    python tools/shiftwork/driver.py --checkpoint .shiftwork/checkpoint.json \
        --config tools/shiftwork/driver.json

State lives beside the checkpoint: `driver-state.json` (retry counters, session
seq — never inside the checkpoint), `driver.lock`, `driver-log.jsonl`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

EXIT_SUCCESS = 0
EXIT_ESCALATE = 10
EXIT_BUDGET = 20
EXIT_STALLED = 30
EXIT_LOCKED = 40

CONTRACT_VERSION = 1
POLL_INITIAL_SECONDS = 30
POLL_MAX_SECONDS = 300
TERMINAL_UNIT_STATUS = frozenset({"done", "dropped"})
ROLES = ("planner", "implementer", "reviewer")

# Constant, never templated per unit: prompt-cacheable, testable, and the
# checkpoint stays the single source of truth (the driver cannot smuggle state
# in via the prompt). `<path>` is substituted once per job, not per session.
CLOCK_IN_PROMPT = (
    "Clock in. Read the checkpoint at `<path>` and the artifacts it lists. "
    "Execute ONLY the unit at `plan.cursor` per its brief. Run its `verify`. "
    "Update the checkpoint (atomic temp-file + rename, keeping it JSON), set "
    "`next_action`, and "
    "clock out. If blocked, set the unit blocked with a reason and fill "
    "`open_questions` instead of improvising."
)

# The message is appended as the final argv entry AND written to stdin, so both
# argv-style and pipe-style notifiers work with one config field.
DEFAULT_NOTIFY_CMD = [
    "osascript",
    "-e",
    "on run argv",
    "-e",
    'display notification (item 1 of argv) with title "shift-work driver"',
    "-e",
    "end run",
    "--",
]

DEFAULT_ROLES = {
    "planner": {"model": "opus", "allowed_tools": ["Read", "Grep", "Glob", "Write"]},
    "implementer": {
        "model": "haiku",
        "allowed_tools": ["Read", "Grep", "Glob", "Edit", "Write", "Bash"],
    },
    "reviewer": {"model": "sonnet", "allowed_tools": ["Read", "Grep", "Glob"]},
}


class CheckpointError(Exception):
    """The checkpoint is unusable. Never a reason to write to it."""


def clock_in_prompt(checkpoint_path: Path | str) -> str:
    return CLOCK_IN_PROMPT.replace("<path>", str(checkpoint_path))


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@dataclass
class RoleConfig:
    model: str
    allowed_tools: list[str] = field(default_factory=list)
    max_turns: int = 40


@dataclass
class Config:
    """Layer-4 profile data living with the driver; sessions never pick a model."""

    roles: dict[str, RoleConfig] = field(default_factory=dict)
    max_sessions: int = 20
    max_wall_clock_seconds: int = 4 * 3600
    max_retries: int = 3
    session_timeout_seconds: int = 30 * 60
    external_timeout_seconds: int = 60 * 60
    notify_cmd: list[str] = field(default_factory=lambda: list(DEFAULT_NOTIFY_CMD))
    dangerously_skip_permissions: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        raw_roles = dict(DEFAULT_ROLES)
        raw_roles.update(data.get("roles") or {})
        roles = {
            name: RoleConfig(
                model=spec["model"],
                allowed_tools=list(spec.get("allowed_tools") or []),
                max_turns=int(spec.get("max_turns", 40)),
            )
            for name, spec in raw_roles.items()
        }
        notify = data.get("notify_cmd", DEFAULT_NOTIFY_CMD)
        if isinstance(notify, str):
            notify = notify.split()
        defaults = cls()
        return cls(
            roles=roles,
            max_sessions=int(data.get("max_sessions", defaults.max_sessions)),
            max_wall_clock_seconds=int(
                data.get("max_wall_clock_seconds", defaults.max_wall_clock_seconds)
            ),
            max_retries=int(data.get("max_retries", defaults.max_retries)),
            session_timeout_seconds=int(
                data.get("session_timeout_seconds", defaults.session_timeout_seconds)
            ),
            external_timeout_seconds=int(
                data.get("external_timeout_seconds", defaults.external_timeout_seconds)
            ),
            notify_cmd=list(notify),  # an explicit [] disables notification
            dangerously_skip_permissions=bool(
                data.get("dangerously_skip_permissions", False)
            ),
        )

    @classmethod
    def load(cls, path: Path | None) -> Config:
        if path is None:
            return cls.from_dict({})
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass
class Checkpoint:
    """Only the fields the driver is allowed to know about."""

    cursor: str
    units: list[dict]
    open_questions: list
    external: list[dict]

    def unit(self, unit_id: str) -> dict | None:
        for u in self.units:
            if u.get("id") == unit_id:
                return u
        return None

    def all_units_terminal(self) -> bool:
        return all(u.get("status") in TERMINAL_UNIT_STATUS for u in self.units)


def parse_checkpoint(text: str) -> Checkpoint:
    """Minimal structural check (stdlib). Full JSON-Schema validation is a session's job."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise CheckpointError(f"not parseable as JSON: {e}") from e
    if not isinstance(data, dict):
        raise CheckpointError("top level is not a mapping")
    if data.get("version") != CONTRACT_VERSION:
        raise CheckpointError(f"unknown contract version: {data.get('version')!r}")
    plan = data.get("plan")
    handoff = data.get("handoff")
    if not isinstance(plan, dict) or not isinstance(handoff, dict):
        raise CheckpointError("plan and handoff must both be mappings")
    cursor = plan.get("cursor")
    units = plan.get("units")
    questions = handoff.get("open_questions")
    if not isinstance(cursor, str) or not cursor:
        raise CheckpointError("plan.cursor must be a non-empty string")
    if not isinstance(units, list) or not all(isinstance(u, dict) for u in units):
        raise CheckpointError("plan.units must be a list of mappings")
    if not isinstance(questions, list):
        raise CheckpointError("handoff.open_questions must be a list")
    state = data.get("state") or {}
    external = state.get("external") or []
    if not isinstance(external, list):
        raise CheckpointError("state.external must be a list")
    return Checkpoint(
        cursor=cursor,
        units=units,
        open_questions=questions,
        external=[e for e in external if isinstance(e, dict)],
    )


class DriverLock:
    """One driver per checkpoint. A lock whose pid is dead is taken over."""

    def __init__(self, path: Path, *, pid: int, now=time.time, is_alive=pid_alive):
        self.path = Path(path)
        self.pid = pid
        self.now = now
        self.is_alive = is_alive
        self.held = False

    def acquire(self) -> str | None:
        """Return None when acquired, else the refusal reason.

        The create is atomic (O_EXCL), so two drivers starting at the same
        instant cannot both win: exactly one create succeeds and the loser
        takes the refusal path below. Read-then-write would let both pass.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._create():
            return None
        owner = self._read_owner()
        if owner is not None and owner != self.pid and self.is_alive(owner):
            # Fails safe on pid reuse: if the recorded pid was recycled by an
            # unrelated live process the lock reads as held, so we refuse a
            # legitimate takeover. Refusing costs a rerun; guessing wrong the
            # other way runs two drivers on one checkpoint.
            return f"another driver (pid {owner}) already holds {self.path}"
        # Holder is dead (or the lock is unreadable): clear it and retry the
        # atomic create exactly once. A driver that wins that race between our
        # unlink and our create keeps the lock, and we refuse.
        self.path.unlink(missing_ok=True)
        if self._create():
            return None
        return f"another driver (pid {self._read_owner()}) already holds {self.path}"

    def _create(self) -> bool:
        """Atomically create the lock with our pid. False if it already exists."""
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps({"pid": self.pid, "started": self.now()}))
        self.held = True
        return True

    def release(self) -> None:
        if not self.held:
            return
        if self._read_owner() == self.pid:
            self.path.unlink(missing_ok=True)
        self.held = False

    def _read_owner(self) -> int | None:
        try:
            return int(json.loads(self.path.read_text(encoding="utf-8"))["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            return None


class Driver:
    def __init__(
        self,
        checkpoint_path: Path | str,
        config: Config,
        *,
        state_path: Path | str | None = None,
        lock_path: Path | str | None = None,
        log_path: Path | str | None = None,
        runner=subprocess.run,
        sleep=time.sleep,
        clock=time.monotonic,
        now=time.time,
        pid: int | None = None,
        is_alive=pid_alive,
        out=sys.stderr,
    ):
        self.checkpoint_path = Path(checkpoint_path)
        self.config = config
        here = self.checkpoint_path.parent
        self.state_path = Path(state_path or here / "driver-state.json")
        self.lock_path = Path(lock_path or here / "driver.lock")
        self.log_path = Path(log_path or here / "driver-log.jsonl")
        self.runner = runner
        self.sleep = sleep
        self.clock = clock
        self.now = now
        self.pid = pid if pid is not None else os.getpid()
        self.is_alive = is_alive
        self.out = out
        self.prompt = clock_in_prompt(self.checkpoint_path)

    # -- entry point --------------------------------------------------------

    def run(self) -> int:
        lock = DriverLock(
            self.lock_path, pid=self.pid, now=self.now, is_alive=self.is_alive
        )
        refusal = lock.acquire()
        if refusal:
            # A refusal is as silent as a terminal exit otherwise: same notify.
            message = f"shift-work refused to start: {refusal}"
            self._say(message)
            self._notify(message)
            return EXIT_LOCKED
        try:
            return self._loop()
        finally:
            lock.release()

    # -- the loop -----------------------------------------------------------

    def _loop(self) -> int:
        started = self.clock()
        state = self._load_state()
        while True:
            try:
                ckpt = parse_checkpoint(self.checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, CheckpointError) as e:
                # Never overwrite a checkpoint we could not read.
                return self._finish(EXIT_ESCALATE, f"checkpoint unusable: {e}", state)

            if ckpt.open_questions:
                first = ckpt.open_questions[0]
                return self._finish(EXIT_ESCALATE, f"open question: {first}", state)
            if ckpt.all_units_terminal():
                return self._finish(EXIT_SUCCESS, "all units done or dropped", state)
            if state["sessions"] >= self.config.max_sessions:
                return self._finish(
                    EXIT_BUDGET, f"session cap reached ({state['sessions']})", state
                )
            elapsed = self.clock() - started
            if elapsed >= self.config.max_wall_clock_seconds:
                return self._finish(
                    EXIT_BUDGET, f"wall-clock cap reached ({int(elapsed)}s)", state
                )

            unit = ckpt.unit(ckpt.cursor)
            if unit is None:
                return self._finish(
                    EXIT_ESCALATE, f"cursor {ckpt.cursor} names no unit", state
                )
            role = unit.get("role")
            role_config = self.config.roles.get(role)
            if role_config is None:
                return self._finish(
                    EXIT_ESCALATE, f"unit {ckpt.cursor} has unknown role {role!r}", state
                )

            waited = self._wait_for_externals(ckpt)
            if waited is not None:
                return self._finish(EXIT_ESCALATE, waited, state)

            before = self._digest()
            exit_code, duration = self._spawn(role_config)
            after = self._digest()
            progressed = before != after

            state["seq"] += 1
            state["sessions"] += 1
            self._log(
                seq=state["seq"],
                cursor=ckpt.cursor,
                role=role,
                exit_code=exit_code,
                duration=duration,
                progressed=progressed,
            )

            if progressed:
                # Trust the checkpoint even on a non-zero session exit.
                state["retries"][ckpt.cursor] = 0
            else:
                # A clean exit without a clock-out write is still no progress.
                tries = state["retries"].get(ckpt.cursor, 0) + 1
                state["retries"][ckpt.cursor] = tries
                if tries > self.config.max_retries:
                    return self._finish(
                        EXIT_STALLED,
                        f"no progress on {ckpt.cursor} after {tries} sessions",
                        state,
                    )
            self._save_state(state)

    # -- waiting ------------------------------------------------------------

    def _wait_for_externals(self, ckpt: Checkpoint) -> str | None:
        """Poll unmet `until_cmd`s with exponential backoff. Return None to proceed."""
        delay = POLL_INITIAL_SECONDS
        waited = 0
        while True:
            pending = [
                e
                for e in ckpt.external
                if e.get("status") == "running"
                and e.get("until_cmd")
                and not self._condition_met(e["until_cmd"])
            ]
            if not pending:
                return None
            if waited >= self.config.external_timeout_seconds:
                refs = ", ".join(str(e.get("ref")) for e in pending)
                return f"external wait timed out after {waited}s: {refs}"
            self.sleep(delay)
            waited += delay
            delay = min(delay * 2, POLL_MAX_SECONDS)

    def _condition_met(self, until_cmd: str) -> bool:
        try:
            done = self.runner(until_cmd, shell=True, capture_output=True)
        except OSError:
            return False
        return getattr(done, "returncode", 1) == 0

    # -- sessions -----------------------------------------------------------

    def _session_command(self, role_config: RoleConfig) -> list[str]:
        cmd = [
            "claude",
            "-p",
            self.prompt,
            "--model",
            role_config.model,
            "--max-turns",
            str(role_config.max_turns),
        ]
        if self.config.dangerously_skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        else:
            cmd += ["--permission-mode", "acceptEdits"]
        if role_config.allowed_tools:
            cmd += ["--allowedTools", ",".join(role_config.allowed_tools)]
        return cmd

    def _spawn(self, role_config: RoleConfig) -> tuple[int, float]:
        cmd = self._session_command(role_config)
        start = self.clock()
        try:
            done = self.runner(cmd, timeout=self.config.session_timeout_seconds)
            code = int(getattr(done, "returncode", 0) or 0)
        except subprocess.TimeoutExpired:
            code = -1
        except OSError as e:
            self._say(f"could not spawn session: {e}")
            code = -1
        return code, self.clock() - start

    def _digest(self) -> str:
        try:
            return hashlib.sha256(self.checkpoint_path.read_bytes()).hexdigest()
        except OSError:
            return ""

    # -- state, log, notify -------------------------------------------------

    def _load_state(self) -> dict:
        state = {"seq": 0, "sessions": 0, "retries": {}}
        try:
            stored = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return state
        if isinstance(stored, dict):
            state["seq"] = int(stored.get("seq", 0))
            state["sessions"] = int(stored.get("sessions", 0))
            retries = stored.get("retries")
            if isinstance(retries, dict):
                state["retries"] = {str(k): int(v) for k, v in retries.items()}
        return state

    def _save_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.state_path)

    def _log(self, *, seq, cursor, role, exit_code, duration, progressed) -> None:
        """One line per session — the experiment's measurement instrument."""
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.now())),
            "seq": seq,
            "cursor": cursor,
            "role": role,
            "exit": exit_code,
            "duration": round(duration, 3),
            "progressed": progressed,
        }
        if exit_code != 0 and progressed:
            record["anomaly"] = "non-zero exit but checkpoint advanced"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def _finish(self, code: int, reason: str, state: dict) -> int:
        self._save_state(state)
        name = {
            EXIT_SUCCESS: "SUCCESS",
            EXIT_ESCALATE: "ESCALATE",
            EXIT_BUDGET: "BUDGET",
            EXIT_STALLED: "STALLED",
        }.get(code, str(code))
        message = f"shift-work {name}: {reason}"
        self._say(message)
        self._notify(message)
        return code

    def _notify(self, message: str) -> None:
        if not self.config.notify_cmd:
            return
        try:
            self.runner(
                [*self.config.notify_cmd, message],
                input=message,
                text=True,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as e:
            self._say(f"notify_cmd failed: {e}")

    def _say(self, message: str) -> None:
        if self.out is not None:
            print(message, file=self.out)


def build_driver(args: argparse.Namespace) -> Driver:
    config = Config.load(Path(args.config) if args.config else None)
    return Driver(
        args.checkpoint,
        config,
        state_path=args.state,
        lock_path=args.lock,
        log_path=args.log,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Shift-work driver: cycle clock-in/clock-out sessions.",
    )
    parser.add_argument("--checkpoint", required=True, help="path to the JSON checkpoint")
    parser.add_argument("--config", help="driver config JSON (defaults are built in)")
    parser.add_argument("--state", help="override driver-state.json path")
    parser.add_argument("--lock", help="override driver.lock path")
    parser.add_argument("--log", help="override driver-log.jsonl path")
    return build_driver(parser.parse_args(argv)).run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
