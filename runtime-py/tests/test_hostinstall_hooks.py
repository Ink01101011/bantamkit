"""`--install-hooks` / `--remove-hooks`: the seven entries, and the consent that gates them.

THE FILE UNDER TEST IS THE USER'S OWN `~/.claude/settings.json`, so every case here points
`Path.home()` — and, for the cases that spawn a real process, `HOME`/`USERPROFILE` — at a
scratch directory BEFORE the module resolves a path, and asserts the redirection rather than
believing it. A test that reached the real file would register seven hooks on the machine it
was measuring, which is the exact thing RULING Q3.3 exists to stop a PROGRAM doing without
being asked.

NO CASE BELOW THE PTY SECTION NEEDS A TERMINAL. The three-state consent gate takes `ask` as a
seam: a callable for "there is a terminal, here is the answer", and `None` for "there is
none". `mcpserver.py` supplies the real one off `sys.stdin.isatty()`; nothing in this file
does, which is what makes the refusing states testable at all.

THE TWO REFUSING STATES ARE ASSERTED ON THE BYTES, NOT ON THE EXCEPTION. "It raised" is
satisfied by a program that wrote the file and then raised. Every refusal case below reads
the settings file before and after and compares bytes, and asserts that no `.backup-` sibling
appeared.

This is the Python half of `runtime-ts/test/hostinstall-hooks.test.mjs`, case for case.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from bantamkit import hostinstall

SRC = Path(__file__).resolve().parents[1] / "src"

# The pty section is POSIX-only: Windows has no `pty` module and no terminal a test can fork.
posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="the driver forks a pty; win32 has no pty module"
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home nobody lives in, asserted rather than believed."""
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setattr(hostinstall, "_home", lambda: root)
    assert str(hostinstall.claude_settings_path()).startswith(str(root)), (
        "claude_settings_path() escaped the scratch home; this test would edit a real file"
    )
    return root


# A hook entry nobody named bantamkit wrote. It must survive everything in this file.
FOREIGN = {
    "matcher": "Bash",
    "hooks": [{"type": "command", "command": "/opt/acme/audit.sh", "timeout": 5}],
}


def seed(path: Path, text: str) -> bytes:
    """A settings file that is not ours, written byte-exactly so a comparison means something."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path.read_bytes()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def backups_in(path: Path) -> list[str]:
    if not path.parent.exists():
        return []
    return sorted(p.name for p in path.parent.iterdir() if ".backup-" in p.name)


class Recorder:
    """A `tell` that records every line the gate printed."""

    def __init__(self) -> None:
        self.said: list[str] = []

    def __call__(self, text: str) -> None:
        self.said.append(text)

    @property
    def text(self) -> str:
        return "".join(self.said)


def refuse(_message: str):
    def fail(*_args, **_kwargs):
        raise AssertionError(_message)

    return fail


# ------------------------------------------------------------------ the fixed data


def test_the_seven_events_and_their_matchers_are_the_fixed_data_in_the_ruled_order():
    assert [event for event, _ in hostinstall.HOOK_EVENTS] == [
        "SessionStart",
        "PreToolUse",
        "PostToolUse",
        "UserPromptSubmit",
        "PreCompact",
        "PostCompact",
        "Stop",
    ]
    matchers = dict(hostinstall.HOOK_EVENTS)
    assert matchers["SessionStart"] == "startup|resume|clear|compact"
    assert matchers["PreToolUse"] == "Read"
    # MATCHER-LESS ON PURPOSE. The PostToolUse arm logs a usage event for EVERY tool call and
    # runs the memory_save half only when the tool was that one; a second, narrower entry
    # beside it would fire the save half twice.
    assert matchers["PostToolUse"] is None
    assert len(hostinstall.HOOK_EVENTS) == 7


def test_the_settings_path_is_dot_claude_settings_json_and_nothing_else(home):
    assert hostinstall.claude_settings_path() == home / ".claude" / "settings.json"


# ------------------------------------------------------------------ the happy path


def test_a_first_install_writes_seven_entries_after_asking_and_reports_what_it_did(home):
    path = hostinstall.claude_settings_path()
    asked = []
    tell = Recorder()

    def ask():
        asked.append(1)
        return True

    report = hostinstall.install_hooks(tell=tell, ask=ask)

    assert len(asked) == 1, "it must ask exactly once"
    hooks = read_json(path)["hooks"]
    assert list(hooks) == [
        "SessionStart",
        "PreToolUse",
        "PostToolUse",
        "UserPromptSubmit",
        "PreCompact",
        "PostCompact",
        "Stop",
    ]
    for event, entries in hooks.items():
        assert len(entries) == 1, event
        assert entries[0]["hooks"][0]["type"] == "command"
        assert entries[0]["hooks"][0]["timeout"] == 10
        assert entries[0]["hooks"][0]["command"].endswith(" --hook")
    assert report.startswith("installed bantamkit hooks into ")
    # The plan went out BEFORE the question, so it is recorded whether or not it was read.
    assert "bantamkit would add 7 hook entries to " in tell.text


def test_the_plan_is_the_ruled_five_lines_in_the_ruled_order(home):
    path = hostinstall.claude_settings_path()
    seed(path, "{}\n")
    tell = Recorder()

    hostinstall.install_hooks(tell=tell, ask=lambda: True)

    plan = tell.text.split("\n")
    assert plan[0] == f"bantamkit would add 7 hook entries to {path}"
    assert plan[1] == (
        "  events : SessionStart PreToolUse PostToolUse UserPromptSubmit "
        "PreCompact PostCompact Stop"
    )
    assert plan[2].startswith("  command: ")
    assert plan[2].endswith(" --hook")
    assert plan[3] == f"  backup : {path}.backup-{date.today().isoformat()}"
    assert plan[4] == (
        "Existing hooks are left byte-for-byte; only bantamkit's own entries are replaced."
    )


def test_there_is_no_backup_line_in_the_plan_when_there_is_no_file_to_back_up(home):
    tell = Recorder()
    hostinstall.install_hooks(tell=tell, ask=lambda: True)
    assert "backup :" not in tell.text


def test_a_second_identical_install_changes_nothing_says_so_and_never_asks(home):
    path = hostinstall.claude_settings_path()
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)
    before = path.read_bytes()

    report = hostinstall.install_hooks(
        tell=refuse("a no-op install printed a plan"),
        ask=refuse("a no-op install asked for consent"),
    )

    assert report == f"bantamkit hooks are already installed in {path} and match"
    assert path.read_bytes() == before
    assert backups_in(path) == []


def test_yes_writes_with_no_terminal_at_all_and_never_asks(home):
    path = hostinstall.claude_settings_path()
    tell = Recorder()

    report = hostinstall.install_hooks(tell=tell, yes=True, ask=None)

    assert report.startswith("installed bantamkit hooks into ")
    assert len(read_json(path)["hooks"]) == 7
    # The plan is still printed: it is what the person is consenting to in advance.
    assert "bantamkit would add 7 hook entries to " in tell.text


# ------------------------------------------------------- the two states that write NOTHING


def test_no_terminal_and_no_yes_refuses_with_the_ruled_sentence_and_leaves_the_file_unchanged(
    home,
):
    path = hostinstall.claude_settings_path()
    before = seed(path, json.dumps({"hooks": {"PreToolUse": [FOREIGN]}}, indent=2) + "\n")
    tell = Recorder()

    with pytest.raises(hostinstall.HookConsentUnavailable) as caught:
        hostinstall.install_hooks(tell=tell, ask=None)

    assert str(caught.value) == (
        "--install-hooks writes your ~/.claude/settings.json and needs a terminal to ask.\n"
        "There is no terminal here, so nothing was written. Re-run it at a prompt, or pass\n"
        "--yes to say yes in advance."
    )
    assert path.read_bytes() == before, "the refusal wrote to the settings file"
    assert backups_in(path) == [], "the refusal took a backup, so it was about to write"
    assert tell.text == "", "the refusal printed a plan for a write it was never going to do"


@pytest.mark.parametrize("answer", ["no", "", "yes", "YES", "n", "N", " "])
def test_answering_anything_but_y_writes_nothing_and_says_so(home, answer):
    path = hostinstall.claude_settings_path()
    before = seed(path, json.dumps({"hooks": {"PreToolUse": [FOREIGN]}}, indent=2) + "\n")

    with pytest.raises(hostinstall.HookDeclined) as caught:
        hostinstall.install_hooks(
            tell=lambda _text: None, ask=lambda: answer.strip() in ("y", "Y")
        )

    assert str(caught.value) == "no hooks were written"
    assert path.read_bytes() == before, "a declined install wrote to the settings file"
    assert backups_in(path) == [], "a declined install took a backup"


@pytest.mark.parametrize("answer", ["y", "Y"])
def test_answering_y_is_the_only_thing_that_writes(home, answer):
    path = hostinstall.claude_settings_path()
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: answer in ("y", "Y"))
    assert len(read_json(path)["hooks"]) == 7


# -------------------------------------------------------------- somebody else's hooks


def test_a_foreign_hook_entry_survives_an_install_byte_for_byte(home):
    path = hostinstall.claude_settings_path()
    seed(
        path,
        json.dumps({"model": "opus", "hooks": {"PreToolUse": [FOREIGN]}}, indent=2) + "\n",
    )

    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)

    after = read_json(path)
    assert after["model"] == "opus", "an unrelated settings key was dropped"
    assert after["hooks"]["PreToolUse"][0] == FOREIGN, "the foreign entry was rewritten"
    assert len(after["hooks"]["PreToolUse"]) == 2, "ours was not appended beside it"
    assert after["hooks"]["PreToolUse"][1]["matcher"] == "Read"


def test_an_existing_bantamkit_entry_is_replaced_never_duplicated(home):
    path = hostinstall.claude_settings_path()
    seed(
        path,
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/old/path/to/bantamkit-mcp --hook",
                                    "timeout": 10,
                                }
                            ]
                        }
                    ]
                }
            },
            indent=2,
        )
        + "\n",
    )

    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)

    stop = read_json(path)["hooks"]["Stop"]
    assert len(stop) == 1, "the stale bantamkit entry was kept beside the new one"
    assert "/old/path/to/" not in json.dumps(stop)


def test_the_backup_holds_the_bytes_that_were_there_before_the_write(home):
    path = hostinstall.claude_settings_path()
    before = seed(path, json.dumps({"hooks": {"PreToolUse": [FOREIGN]}}, indent=2) + "\n")

    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)

    copies = backups_in(path)
    assert len(copies) == 1, copies
    assert (path.parent / copies[0]).read_bytes() == before


def test_a_settings_file_that_does_not_parse_is_never_overwritten(home):
    path = hostinstall.claude_settings_path()
    before = seed(path, '{ "hooks": ')

    with pytest.raises(hostinstall.InstallError) as caught:
        hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)

    assert str(caught.value).startswith(
        f"{path} is not valid JSON, so this refuses to touch it: "
    )
    assert path.read_bytes() == before
    assert backups_in(path) == []


def test_a_hooks_key_that_is_not_an_object_is_refused_by_name(home):
    path = hostinstall.claude_settings_path()
    before = seed(path, json.dumps({"hooks": ["nope"]}, indent=2) + "\n")

    with pytest.raises(hostinstall.InstallError) as caught:
        hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)

    assert str(caught.value) == (
        f"{path} has a 'hooks' that is not an object; refusing to touch it"
    )
    assert path.read_bytes() == before


def test_one_event_whose_value_is_not_a_list_is_refused_by_name(home):
    path = hostinstall.claude_settings_path()
    before = seed(path, json.dumps({"hooks": {"Stop": {"nope": 1}}}, indent=2) + "\n")

    with pytest.raises(hostinstall.InstallError) as caught:
        hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)

    assert str(caught.value) == (
        f"{path} has a 'hooks.Stop' that is not a list; refusing to touch it"
    )
    assert path.read_bytes() == before


# ------------------------------------------------------------------------- --remove-hooks
#
# THE GATE IS INSTALL'S GATE SINCE THE USER'S RULING OF 2026-09-20. RULING Q3.7 exempted this
# flag; the user overturned that after `--remove-hooks` rewrote the operator's real
# `~/.claude/settings.json` with no terminal, no `--yes` and exit 0. Every case below is the
# `--install-hooks` case above it with the verb changed, which is the point: two flags that
# rewrite one file do not get two consent stories.


def test_remove_hooks_takes_out_only_what_bantamkit_wrote(home):
    path = hostinstall.claude_settings_path()
    seed(
        path,
        json.dumps({"model": "opus", "hooks": {"PreToolUse": [FOREIGN]}}, indent=2) + "\n",
    )
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)

    report = hostinstall.remove_hooks(tell=lambda _text: None, ask=lambda: True)

    after = read_json(path)
    assert after["model"] == "opus"
    assert after["hooks"] == {"PreToolUse": [FOREIGN]}, "the foreign entry did not survive"
    assert report.startswith(f"removed bantamkit hooks from {path}")


def test_remove_hooks_asks_exactly_once_and_honours_yes(home):
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)
    asked = []

    def ask():
        asked.append(1)
        return True

    hostinstall.remove_hooks(tell=lambda _text: None, ask=ask)
    assert asked == [1], f"--remove-hooks asked {len(asked)} times"


def test_remove_hooks_with_yes_never_asks_even_without_a_terminal(home):
    path = hostinstall.claude_settings_path()
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)

    report = hostinstall.remove_hooks(ask=None, yes=True, tell=lambda _text: None)

    assert report.startswith(f"removed bantamkit hooks from {path}")
    assert read_json(path)["hooks"] == {}


def test_the_removal_plan_is_four_lines_in_the_ruled_order(home):
    path = hostinstall.claude_settings_path()
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)
    tell = Recorder()

    hostinstall.remove_hooks(tell=tell, ask=lambda: True)

    # FOUR LINES, NOT FIVE. There is no `command:` line: `remove_hooks` never resolves one,
    # and printing one would name something the write will not touch. `backup :` is
    # UNCONDITIONAL here -- the gate is only reached when an entry is actually coming out.
    assert tell.text == (
        f"bantamkit would remove 7 hook entries from {path}\n"
        f"  events : {hostinstall._EVENT_NAMES}\n"
        f"  backup : {path}.backup-{date.today().isoformat()}\n"
        "Existing hooks are left byte-for-byte; only bantamkit's own entries are removed.\n"
    )


def test_the_removal_plan_names_only_the_events_that_lose_an_entry(home):
    path = hostinstall.claude_settings_path()
    rendered = hostinstall.hook_command("/opt/bantamkit/bin/bantamkit-mcp", [])
    seed(
        path,
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [FOREIGN],
                    "Stop": [
                        {"hooks": [{"type": "command", "command": rendered, "timeout": 10}]}
                    ],
                }
            },
            indent=2,
        )
        + "\n",
    )
    tell = Recorder()

    hostinstall.remove_hooks(tell=tell, ask=lambda: True)

    # ENTRIES, NOT EVENTS, on the first line; and only `Stop` loses anything.
    assert tell.text.splitlines()[0] == f"bantamkit would remove 1 hook entries from {path}"
    assert tell.text.splitlines()[1] == "  events : Stop"


def test_remove_hooks_with_no_terminal_and_no_yes_refuses_and_writes_nothing(home):
    path = hostinstall.claude_settings_path()
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)
    before = path.read_bytes()
    backups_before = backups_in(path)
    tell = Recorder()

    with pytest.raises(hostinstall.HookConsentUnavailable) as caught:
        hostinstall.remove_hooks(ask=None, tell=tell)

    assert str(caught.value) == (
        "--remove-hooks rewrites your ~/.claude/settings.json and needs a terminal to ask.\n"
        "There is no terminal here, so nothing was written. Re-run it at a prompt, or pass\n"
        "--yes to say yes in advance."
    )
    # NOTHING IS PRINTED ON THIS PATH. The plan describes a write that is not going to happen.
    assert tell.text == "", tell.text
    # THE BYTES, NOT THE EXCEPTION: "it raised" is satisfied by a program that wrote and then
    # raised.
    assert path.read_bytes() == before, "a refused removal rewrote the settings file"
    assert backups_in(path) == backups_before, "a refused removal took a backup"


def test_the_two_refusals_come_from_one_template_and_differ_only_in_flag_and_verb(home):
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)
    with pytest.raises(hostinstall.HookConsentUnavailable) as removal:
        hostinstall.remove_hooks(ask=None, tell=lambda _text: None)
    # A second, non-matching install is the state that reaches install's gate.
    path = hostinstall.claude_settings_path()
    doc = read_json(path)
    doc["hooks"].pop("Stop")
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(hostinstall.HookConsentUnavailable) as install:
        hostinstall.install_hooks(ask=None, tell=lambda _text: None)

    assert str(removal.value).replace("--remove-hooks rewrites", "--install-hooks writes") == (
        str(install.value)
    ), "the two refusals are no longer one template"


@pytest.mark.parametrize("answer", ["no", "", "yes", "YES", "n", "N", " "])
def test_a_declined_removal_at_a_terminal_writes_nothing(home, answer):
    path = hostinstall.claude_settings_path()
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)
    before = path.read_bytes()
    backups_before = backups_in(path)
    tell = Recorder()

    with pytest.raises(hostinstall.HookDeclined) as caught:
        hostinstall.remove_hooks(ask=lambda: answer in ("y", "Y"), tell=tell)

    assert str(caught.value) == "no hooks were removed"
    # The plan WAS printed -- the person had to see what they were declining -- and nothing
    # after it.
    assert tell.text.startswith("bantamkit would remove ")
    assert path.read_bytes() == before, "a declined removal wrote to the settings file"
    assert backups_in(path) == backups_before, "a declined removal took a backup"


def test_remove_hooks_on_a_file_with_no_bantamkit_hooks_changes_nothing_and_says_so(home):
    path = hostinstall.claude_settings_path()
    before = seed(path, json.dumps({"hooks": {"PreToolUse": [FOREIGN]}}, indent=2) + "\n")

    # THE NO-OP RETURNS BEFORE THE GATE, which is why `ask` may be `None` here and why `tell`
    # is one that fails if it is called at all: there is no write to consent to, so a teardown
    # script that runs this twice does not start refusing.
    report = hostinstall.remove_hooks(
        ask=refuse("a no-op removal asked for consent"),
        tell=refuse("a no-op removal printed a plan"),
    )

    assert report == f"no bantamkit hooks are installed in {path}"
    assert path.read_bytes() == before, "a no-op removal rewrote the settings file"
    assert backups_in(path) == [], "a no-op removal took a backup"


def test_remove_hooks_with_no_settings_file_at_all_writes_nothing(home):
    path = hostinstall.claude_settings_path()

    report = hostinstall.remove_hooks(
        ask=refuse("a no-op removal asked for consent"),
        tell=refuse("a no-op removal printed a plan"),
    )

    assert report == f"no bantamkit hooks are installed in {path}"
    assert not path.exists(), "--remove-hooks created the file it had nothing to remove from"
    assert not (home / ".claude").exists(), "--remove-hooks created ~/.claude"


def test_remove_hooks_still_takes_the_dated_backup(home):
    path = hostinstall.claude_settings_path()
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)
    before = path.read_bytes()

    hostinstall.remove_hooks(tell=lambda _text: None, ask=lambda: True)

    copies = backups_in(path)
    assert len(copies) == 1, copies
    assert (path.parent / copies[0]).read_bytes() == before


def test_an_event_left_with_no_entries_loses_its_key_rather_than_holding_an_empty_list(home):
    path = hostinstall.claude_settings_path()
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)
    hostinstall.remove_hooks(tell=lambda _text: None, ask=lambda: True)
    assert read_json(path)["hooks"] == {}


# ------------------------------------------------------- the real CLI, in a scratch HOME


def run_cli(argv, root: Path, stdin=subprocess.DEVNULL):
    """The real process, with HOME redirected in its ENVIRONMENT — no import-time trust.

    PYTHONPATH is set explicitly: without it the child imports whatever `bantamkit` the
    interpreter has installed, which in a worktree is the OTHER checkout's source.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["HOME"] = str(root)
    env["USERPROFILE"] = str(root)
    env.pop("BANTAMKIT_ASSETS", None)
    return subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        stdin=stdin,
    )


def test_the_real_cli_with_no_terminal_and_no_yes_exits_2_and_writes_nothing(tmp_path):
    root = tmp_path / "home"
    path = root / ".claude" / "settings.json"
    before = seed(path, json.dumps({"hooks": {"PreToolUse": [FOREIGN]}}, indent=2) + "\n")

    done = run_cli(["--install-hooks"], root)

    assert done.returncode == 2, done.stdout + done.stderr
    assert done.stderr == (
        "--install-hooks writes your ~/.claude/settings.json and needs a terminal to ask.\n"
        "There is no terminal here, so nothing was written. Re-run it at a prompt, or pass\n"
        "--yes to say yes in advance.\n"
    )
    assert done.stdout == ""
    assert path.read_bytes() == before, "the CLI wrote to the file it refused to touch"
    assert backups_in(path) == []


def test_the_real_cli_with_yes_writes_the_seven_entries_and_exits_0(tmp_path):
    root = tmp_path / "home"
    root.mkdir()

    done = run_cli(["--install-hooks", "--yes"], root)

    assert done.returncode == 0, done.stdout + done.stderr
    path = root / ".claude" / "settings.json"
    hooks = read_json(path)["hooks"]
    assert len(hooks) == 7
    # The command recorded is THIS tree's, absolute, and it carries `--hook`.
    command = hooks["Stop"][0]["hooks"][0]["command"]
    assert "bantamkit.mcpserver" in command, command
    assert command.endswith(" --hook"), command
    assert done.stdout.startswith(f"installed bantamkit hooks into {path}")
    assert "bantamkit would add 7 hook entries to " in done.stderr


def test_the_real_cli_remove_hooks_with_no_terminal_exits_2_and_writes_nothing(tmp_path):
    root = tmp_path / "home"
    root.mkdir()
    assert run_cli(["--install-hooks", "--yes"], root).returncode == 0
    path = root / ".claude" / "settings.json"
    before = path.read_bytes()
    backups_before = backups_in(path)

    done = run_cli(["--remove-hooks"], root)

    assert done.returncode == 2, done.stdout + done.stderr
    assert done.stderr == (
        "--remove-hooks rewrites your ~/.claude/settings.json and needs a terminal to ask.\n"
        "There is no terminal here, so nothing was written. Re-run it at a prompt, or pass\n"
        "--yes to say yes in advance.\n"
    )
    assert done.stdout == ""
    assert path.read_bytes() == before, "the CLI rewrote the file it refused to touch"
    assert backups_in(path) == backups_before


def test_the_real_cli_remove_hooks_with_yes_exits_0_and_prints_the_plan_on_stderr(tmp_path):
    root = tmp_path / "home"
    root.mkdir()
    assert run_cli(["--install-hooks", "--yes"], root).returncode == 0

    done = run_cli(["--remove-hooks", "--yes"], root)

    assert done.returncode == 0, done.stdout + done.stderr
    assert read_json(root / ".claude" / "settings.json")["hooks"] == {}
    assert "bantamkit would remove 7 hook entries from " in done.stderr
    assert done.stdout.startswith("removed bantamkit hooks from ")


def test_the_real_cli_remove_hooks_with_nothing_to_remove_exits_0_with_no_terminal(tmp_path):
    # THE NO-OP IS BEFORE THE GATE, so a teardown script that runs this twice does not start
    # refusing. Measured on the SECOND removal, which is the one with nothing of ours left.
    root = tmp_path / "home"
    root.mkdir()
    assert run_cli(["--install-hooks", "--yes"], root).returncode == 0
    assert run_cli(["--remove-hooks", "--yes"], root).returncode == 0
    path = root / ".claude" / "settings.json"
    before = path.read_bytes()

    done = run_cli(["--remove-hooks"], root)

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout == f"no bantamkit hooks are installed in {path}\n"
    assert done.stderr == ""
    assert path.read_bytes() == before


def test_the_real_cli_refuses_yes_without_install_hooks(tmp_path):
    root = tmp_path / "home"
    root.mkdir()

    done = run_cli(["--yes"], root)

    assert done.returncode == 1, done.stdout + done.stderr
    # NAMES BOTH FLAGS since 2026-09-20: naming only one would send an operator who mistyped
    # `--remove-hooks` looking for a flag they already had.
    assert done.stderr == "--yes is only meaningful with --install-hooks or --remove-hooks\n"
    assert not (root / ".claude").exists()


def test_the_three_flags_are_in_dash_h_with_their_ruled_sentences(tmp_path):
    root = tmp_path / "home"
    root.mkdir()

    done = run_cli(["-h"], root)

    assert done.returncode == 0, done.stderr
    help_text = " ".join(done.stdout.split())
    assert (
        "--install-hooks add bantamkit's hook entries to ~/.claude/settings.json, then exit"
        in help_text
    ), done.stdout
    assert (
        "--remove-hooks take bantamkit's hook entries back out of ~/.claude/settings.json, "
        "then exit" in help_text
    ), done.stdout
    assert (
        "--yes with --install-hooks or --remove-hooks, say yes in advance instead of being "
        "asked" in help_text
    ), done.stdout


def test_mcp_report_before_install_hooks_prints_a_report_and_writes_no_settings_file(tmp_path):
    # DISPATCH ORDER IS REGISTRATION ORDER, the rule every flag on this parser follows.
    root = tmp_path / "home"
    root.mkdir()

    done = run_cli(["--mcp-report", "--install-hooks", "--yes"], root)

    assert done.returncode == 0, done.stderr
    assert not (root / ".claude" / "settings.json").exists()


# ------------------------------------------------ the one branch a seam cannot reach: a tty

"""
THE `ask` SEAM COVERS EVERY CASE ABOVE AND COVERS THE READER IN NONE OF THEM. The Node half
shipped a defect for the length of one build for exactly that reason: its reader threw
`EAGAIN` on a terminal's non-blocking fd 0 and every seam-driven case stayed green. CPython's
`sys.stdin.readline()` blocks, so that particular defect cannot reproduce here — but the
route that FOUND it is the route this section takes anyway, because no case above can reach
`_ask_at_the_terminal` at all.
"""

PTY_DRIVER = r"""
import os, pty, select, sys, time
answer, home, src, flag = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
pid, fd = pty.fork()
if pid == 0:
    os.environ['HOME'] = home
    os.environ['USERPROFILE'] = home
    os.environ['PYTHONPATH'] = src
    os.environ.pop('BANTAMKIT_ASSETS', None)
    os.execv(sys.executable, [sys.executable, '-m', 'bantamkit.mcpserver', flag])
out, sent = b'', False
while True:
    ready, _, _ = select.select([fd], [], [], 30)
    if not ready:
        break
    try:
        chunk = os.read(fd, 4096)
    except OSError:
        break
    if not chunk:
        break
    out += chunk
    if not sent and b'[y/N]' in out:
        time.sleep(0.1)
        os.write(fd, answer.encode() + b'\n')
        sent = True
_, status = os.waitpid(pid, 0)
sys.stdout.write(out.decode('utf8', 'replace'))
sys.stdout.write('\nEXIT %d\n' % os.waitstatus_to_exitcode(status))
"""


@posix_only
@pytest.mark.parametrize(
    ("answer", "writes"), [("y", True), ("Y", True), ("n", False), ("", False)]
)
def test_at_a_real_terminal_only_y_writes(tmp_path, answer, writes):
    root = tmp_path / "home"
    path = root / ".claude" / "settings.json"
    before = seed(
        path,
        json.dumps({"model": "opus", "hooks": {"PreToolUse": [FOREIGN]}}, indent=2) + "\n",
    )
    driver = tmp_path / "drive.py"
    driver.write_text(PTY_DRIVER, encoding="utf-8")

    done = subprocess.run(
        [sys.executable, str(driver), answer, str(root), str(SRC), "--install-hooks"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert done.returncode == 0, f"the pty driver itself failed: {done.stderr}"
    out = done.stdout

    assert "Write these hook entries? [y/N]" in out, out
    if writes:
        assert "\nEXIT 0\n" in out, out
        assert len(read_json(path)["hooks"]) == 7, out
        assert read_json(path)["hooks"]["PreToolUse"][0] == FOREIGN
        assert read_json(path)["model"] == "opus"
    else:
        assert "no hooks were written" in out, out
        assert "\nEXIT 1\n" in out, out
        assert path.read_bytes() == before, "a terminal refusal wrote to the settings file"
        assert backups_in(path) == [], "a terminal refusal took a backup"


@posix_only
@pytest.mark.parametrize(
    ("answer", "removes"), [("y", True), ("Y", True), ("n", False), ("", False)]
)
def test_at_a_real_terminal_only_y_removes(tmp_path, answer, removes):
    """The same four answers, driving `--remove-hooks` at a real terminal.

    The seam cases above cannot see this path at all: they never reach
    `_ask_at_the_terminal`, so nothing but a pty proves that the QUESTION the removal asks is
    the removal's question and that the reader honours the same four keystrokes.
    """
    root = tmp_path / "home"
    root.mkdir()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["HOME"] = str(root)
    env["USERPROFILE"] = str(root)
    env.pop("BANTAMKIT_ASSETS", None)
    path = root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"model": "opus", "hooks": {"PreToolUse": [FOREIGN]}}, indent=2) + "\n",
        encoding="utf-8",
    )
    installed = subprocess.run(
        [sys.executable, "-m", "bantamkit.mcpserver", "--install-hooks", "--yes"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        stdin=subprocess.DEVNULL,
    )
    assert installed.returncode == 0, installed.stderr
    assert str(path).startswith(str(root)), "the child escaped the scratch home"
    before = path.read_bytes()
    driver = tmp_path / "drive.py"
    driver.write_text(PTY_DRIVER, encoding="utf-8")

    done = subprocess.run(
        [sys.executable, str(driver), answer, str(root), str(SRC), "--remove-hooks"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert done.returncode == 0, f"the pty driver itself failed: {done.stderr}"
    out = done.stdout

    assert "Remove these hook entries? [y/N]" in out, out
    if removes:
        assert "\nEXIT 0\n" in out, out
        assert read_json(path)["hooks"] == {"PreToolUse": [FOREIGN]}, out
        assert read_json(path)["model"] == "opus"
    else:
        assert "no hooks were removed" in out, out
        assert "\nEXIT 1\n" in out, out
        assert path.read_bytes() == before, "a terminal refusal rewrote the settings file"


# ==================================================================================================
# OWNERSHIP IS A PROPERTY OF THE ENTRY, NOT OF WHERE THE BINARY SITS  (J62-22)
# ==================================================================================================
#
# `_is_ours` used to be `"bantamkit" in json.dumps(entry)`. Every checkout on the machine this
# was written on is called `bantamkit*`, so an entry's own command carried the word and the test
# looked right. From an install tree whose path does not -- an npm install under another name, a
# Docker image with `dist/` at `/app/dist/`, a vendored build -- three `--install-hooks --yes`
# left TWENTY-ONE entries instead of seven and `--remove-hooks --yes` then said `no bantamkit
# hooks are installed`, on BOTH runtimes.
#
# THE REFERENCE COULD NEVER REACH THE DUPLICATION ITSELF and that is worth saying out loud:
# `this_command()` returns a `bantamkit-mcp*` console script or `<python> -m bantamkit.mcpserver`,
# so the word is in the reference's command whatever path it was installed at. What the reference
# COULD do, and did, was fail to remove an entry the PORT wrote from a neutral path -- into the
# same `~/.claude/settings.json` both runtimes share. These tests are over the entries.

# What 0.35.4 writes from an install path that carries no `bantamkit` anywhere.
NEUTRAL_MARKED = {
    "type": "command",
    "command": "/opt/vendor/bin/node /opt/vendor/app/dist/cli.js --hook",
    "timeout": 10,
    "bantamkit": "hook",
}
# What `tools/hooks/install.mjs` wrote, and what is in real settings files today. No marker.
LEGACY_ADAPTER = {
    "type": "command",
    "command": "node /srv/checkouts/toolbox/tools/hooks/bantamkit-hook.mjs",
    "timeout": 10,
}


def test_every_entry_this_writes_carries_the_marker_and_presence_is_the_whole_test(home):
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)

    hooks = read_json(hostinstall.claude_settings_path())["hooks"]
    assert len(hooks) == 7
    for event, entries in hooks.items():
        for entry in entries:
            for hook in entry["hooks"]:
                assert hook[hostinstall.HOOK_MARKER_KEY] == hostinstall.HOOK_MARKER_VALUE, event

    # THE VALUE IS NEVER READ. A release that wrote a different one must not orphan what this
    # one wrote, so ownership must survive any value at all -- including a falsy one.
    for value in ["hook", "", "0.99.0", 0, False, None, {"v": 1}]:
        hook = {"type": "command", "command": "/x/y", hostinstall.HOOK_MARKER_KEY: value}
        entry = {"hooks": [hook]}
        assert hostinstall._is_ours(entry), value


def test_an_entry_written_from_a_path_that_does_not_say_bantamkit_is_still_ours(home):
    """The defect, at the level it is decided. The old test answered False for this entry."""
    assert "bantamkit" not in NEUTRAL_MARKED["command"]
    assert hostinstall._is_ours({"matcher": "Read", "hooks": [NEUTRAL_MARKED]})
    # ... and the superseded test really did miss it, which is why this is not a tautology.
    assert "bantamkit" in json.dumps({"hooks": [NEUTRAL_MARKED]}), "only because of the marker key"
    assert "bantamkit" not in json.dumps(
        {"hooks": [{k: v for k, v in NEUTRAL_MARKED.items() if k != "bantamkit"}]}
    ), "strip the marker and the old substring test has nothing left to find"


def test_the_legacy_tools_hooks_adapter_is_still_recognised_and_removable(home):
    """BACKWARD COMPATIBILITY. These entries are in real settings files right now."""
    path = hostinstall.claude_settings_path()
    seed(
        path,
        json.dumps(
            {"model": "opus", "hooks": {"Stop": [{"hooks": [LEGACY_ADAPTER]}, FOREIGN]}}, indent=2
        )
        + "\n",
    )

    report = hostinstall.remove_hooks(tell=lambda _text: None, yes=True)

    after = read_json(path)
    assert after["hooks"] == {"Stop": [FOREIGN]}, "the legacy adapter entry was orphaned"
    assert report.startswith(f"removed bantamkit hooks from {path}")


def test_removal_takes_out_a_neutral_path_entry_the_other_runtime_wrote(home):
    """ONE settings file, two runtimes. The port writes it; the reference must take it back out."""
    path = hostinstall.claude_settings_path()
    seed(
        path,
        json.dumps({"hooks": {"PostToolUse": [{"hooks": [NEUTRAL_MARKED]}, FOREIGN]}}, indent=2)
        + "\n",
    )

    hostinstall.remove_hooks(tell=lambda _text: None, yes=True)

    assert read_json(path)["hooks"] == {"PostToolUse": [FOREIGN]}


def test_reinstalling_over_marked_entries_another_build_wrote_leaves_seven_not_fourteen(home):
    """IDEMPOTENCE, the other half of the same defect -- the half the `21` came from."""
    path = hostinstall.claude_settings_path()
    seed(
        path,
        json.dumps(
            {
                "hooks": {
                    event: [
                        {"hooks": [NEUTRAL_MARKED]}
                        if matcher is None
                        else {"matcher": matcher, "hooks": [NEUTRAL_MARKED]}
                    ]
                    for event, matcher in hostinstall.HOOK_EVENTS
                }
            },
            indent=2,
        )
        + "\n",
    )

    hostinstall.install_hooks(tell=lambda _text: None, yes=True)

    hooks = read_json(path)["hooks"]
    assert sum(len(entries) for entries in hooks.values()) == 7, "the stale entries were duplicated"
    commands = [h["command"] for entries in hooks.values() for e in entries for h in e["hooks"]]
    assert NEUTRAL_MARKED["command"] not in commands, "a foreign build's entry survived"
    assert len(set(commands)) == 1, "seven events, one command"


@pytest.mark.parametrize(
    ("label", "entry"),
    [
        (
            "a matcher that happens to say bantamkit",
            {
                "matcher": "bantamkit",
                "hooks": [{"type": "command", "command": "/opt/acme/audit.sh"}],
            },
        ),
        (
            "a script the operator named after us",
            {
                "hooks": [
                    {"type": "command", "command": "/home/dev/bin/backup-bantamkit-notes.sh"}
                ]
            },
        ),
        (
            "a statusMessage that mentions us",
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "/opt/acme/lint.sh",
                        "statusMessage": "linting for bantamkit",
                    }
                ]
            },
        ),
        (
            "a third-party tool with its own --hook flag",
            {"hooks": [{"type": "command", "command": "/opt/acme/acmetool --hook"}]},
        ),
        (
            "a prompt hook quoting our docs",
            {"hooks": [{"type": "prompt", "prompt": "is this bantamkit-hook safe?"}]},
        ),
    ],
)
def test_a_foreign_entry_is_not_claimed_however_it_mentions_us(home, label, entry):
    """NOT WIDENING. The first three were CLAIMED AND DELETED by the superseded test."""
    assert not hostinstall._is_ours(entry), label


@pytest.mark.parametrize(
    "entry",
    ["not an object", None, 42, [], {}, {"hooks": "not a list"}, {"hooks": [None, 7, "x"]}],
)
def test_ownership_never_raises_on_a_hand_edited_file(home, entry):
    """Somebody else's settings file is input, not a contract. It answers False, it never throws."""
    assert hostinstall._is_ours(entry) is False
