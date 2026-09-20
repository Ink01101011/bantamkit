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
        "Existing hooks are left byte-for-byte; only entries naming bantamkit are replaced."
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


def test_remove_hooks_takes_out_only_what_bantamkit_wrote(home):
    path = hostinstall.claude_settings_path()
    seed(
        path,
        json.dumps({"model": "opus", "hooks": {"PreToolUse": [FOREIGN]}}, indent=2) + "\n",
    )
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)

    report = hostinstall.remove_hooks(tell=refuse("--remove-hooks printed a plan"))

    after = read_json(path)
    assert after["model"] == "opus"
    assert after["hooks"] == {"PreToolUse": [FOREIGN]}, "the foreign entry did not survive"
    assert report.startswith(f"removed bantamkit hooks from {path}")


def test_remove_hooks_never_asks_for_consent(home):
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)
    hostinstall.remove_hooks(
        ask=refuse("--remove-hooks asked for consent"), tell=lambda _text: None
    )


def test_remove_hooks_on_a_file_with_no_bantamkit_hooks_changes_nothing_and_says_so(home):
    path = hostinstall.claude_settings_path()
    before = seed(path, json.dumps({"hooks": {"PreToolUse": [FOREIGN]}}, indent=2) + "\n")

    report = hostinstall.remove_hooks(ask=None, tell=lambda _text: None)

    assert report == f"no bantamkit hooks are installed in {path}"
    assert path.read_bytes() == before, "a no-op removal rewrote the settings file"
    assert backups_in(path) == [], "a no-op removal took a backup"


def test_remove_hooks_with_no_settings_file_at_all_writes_nothing(home):
    path = hostinstall.claude_settings_path()

    report = hostinstall.remove_hooks(ask=None, tell=lambda _text: None)

    assert report == f"no bantamkit hooks are installed in {path}"
    assert not path.exists(), "--remove-hooks created the file it had nothing to remove from"
    assert not (home / ".claude").exists(), "--remove-hooks created ~/.claude"


def test_remove_hooks_still_takes_the_dated_backup(home):
    path = hostinstall.claude_settings_path()
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)
    before = path.read_bytes()

    hostinstall.remove_hooks(tell=lambda _text: None)

    copies = backups_in(path)
    assert len(copies) == 1, copies
    assert (path.parent / copies[0]).read_bytes() == before


def test_an_event_left_with_no_entries_loses_its_key_rather_than_holding_an_empty_list(home):
    path = hostinstall.claude_settings_path()
    hostinstall.install_hooks(tell=lambda _text: None, ask=lambda: True)
    hostinstall.remove_hooks(tell=lambda _text: None)
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


def test_the_real_cli_remove_hooks_needs_no_yes_and_exits_0(tmp_path):
    root = tmp_path / "home"
    root.mkdir()
    assert run_cli(["--install-hooks", "--yes"], root).returncode == 0

    done = run_cli(["--remove-hooks"], root)

    assert done.returncode == 0, done.stdout + done.stderr
    assert read_json(root / ".claude" / "settings.json")["hooks"] == {}


def test_the_real_cli_refuses_yes_without_install_hooks(tmp_path):
    root = tmp_path / "home"
    root.mkdir()

    done = run_cli(["--yes"], root)

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stderr == "--yes is only meaningful with --install-hooks\n"
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
        "--yes with --install-hooks, say yes in advance instead of being asked" in help_text
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
answer, home, src = sys.argv[1], sys.argv[2], sys.argv[3]
pid, fd = pty.fork()
if pid == 0:
    os.environ['HOME'] = home
    os.environ['USERPROFILE'] = home
    os.environ['PYTHONPATH'] = src
    os.environ.pop('BANTAMKIT_ASSETS', None)
    os.execv(sys.executable, [sys.executable, '-m', 'bantamkit.mcpserver', '--install-hooks'])
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
        [sys.executable, str(driver), answer, str(root), str(SRC)],
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
