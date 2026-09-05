"""`--install <host>`: the file it writes, and everything it refuses to destroy.

EVERY TEST HERE POINTS `Path.home()` AT `tmp_path`. That is not tidiness — this module
writes to real configuration files, and a test that reached one would edit the machine it
was measuring. `hostinstall.host_config_path` derives every path from `Path.home()` and
nothing else, which is what makes the redirection total.
"""

import json

import pytest

from bantamkit import hostinstall


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home nobody lives in."""
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setattr(hostinstall, "_home", lambda: root)
    return root


CMD = "/opt/bantamkit/bin/bantamkit-mcp"


def test_the_key_is_servers_for_vs_code_and_mcpservers_for_the_other_three():
    """The one word that silently loses an entry.

    A correct server under the wrong key is not an error anywhere: the host reads the key it
    knows, finds nothing, and says nothing. This is the whole reason the command exists, so
    it is pinned as a fact rather than left to the writer of each arm.
    """
    assert hostinstall.config_key("copilot") == "servers"
    assert hostinstall.config_key("cursor") == "mcpServers"
    assert hostinstall.config_key("claude-desktop") == "mcpServers"


def test_vs_code_gets_a_type_field_and_the_others_do_not():
    """`type: "stdio"` is in VS Code's documented example and in no other host's."""
    assert hostinstall.entry_for("copilot", CMD, []) == {
        "type": "stdio",
        "command": CMD,
        "args": [],
    }
    assert hostinstall.entry_for("cursor", CMD, ["-m", "x"]) == {
        "command": CMD,
        "args": ["-m", "x"],
    }


def test_a_first_install_creates_the_file_and_the_directory(home):
    report = hostinstall.install("cursor", CMD, [])
    path = hostinstall.host_config_path("cursor")

    assert path.exists()
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written == {"mcpServers": {"bantamkit": {"command": CMD, "args": []}}}
    assert "installed bantamkit into cursor" in report
    # Nothing to back up on a first install, so no backup line and no stray file.
    assert "backup" not in report
    assert list(path.parent.glob("*.backup-*")) == []


def test_a_second_identical_install_changes_nothing_and_says_so(home):
    hostinstall.install("cursor", CMD, [])
    path = hostinstall.host_config_path("cursor")
    before = path.read_bytes()

    report = hostinstall.install("cursor", CMD, [])

    assert report.startswith("bantamkit is already installed in cursor and matches")
    assert path.read_bytes() == before
    assert list(path.parent.glob("*.backup-*")) == []


def test_someone_elses_servers_and_unrelated_keys_survive(home):
    """The merge, and the reason this cannot be a file-write.

    A host's configuration is shared: Claude Desktop's carries `preferences` beside its
    servers, and a VS Code user's `servers` block routinely holds several. Measured on the
    machine this was written on, both files already held entries this command did not put
    there.
    """
    path = hostinstall.host_config_path("cursor")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "mcpServers": {"someone-else": {"command": "keep-me", "args": ["--important"]}},
                "unrelatedTopLevelKey": {"keep": "this too"},
            }
        ),
        encoding="utf-8",
    )

    hostinstall.install("cursor", CMD, [])

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["mcpServers"]["someone-else"] == {"command": "keep-me", "args": ["--important"]}
    assert written["unrelatedTopLevelKey"] == {"keep": "this too"}
    assert written["mcpServers"]["bantamkit"]["command"] == CMD


def test_a_different_existing_entry_is_refused_and_the_file_is_untouched(home):
    hostinstall.install("cursor", "OLD", [])
    path = hostinstall.host_config_path("cursor")
    before = path.read_bytes()

    with pytest.raises(hostinstall.InstallError) as caught:
        hostinstall.install("cursor", CMD, [])

    message = str(caught.value)
    # Both values, because the operator's next decision is which one they wanted.
    assert '"command": "OLD"' in message
    assert CMD in message
    assert "re-run with --force to replace it" in message
    assert path.read_bytes() == before


def test_force_replaces_the_entry_and_leaves_a_dated_backup(home):
    hostinstall.install("cursor", "OLD", [])
    path = hostinstall.host_config_path("cursor")

    report = hostinstall.install("cursor", CMD, [], force=True)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["mcpServers"]["bantamkit"]["command"] == CMD
    backups = list(path.parent.glob("*.backup-*"))
    assert len(backups) == 1
    assert "backup : " in report
    # The backup is the file as it was, not a copy of what replaced it.
    assert json.loads(backups[0].read_text(encoding="utf-8"))["mcpServers"]["bantamkit"] == {
        "command": "OLD",
        "args": [],
    }


def test_a_file_that_is_not_json_is_refused_rather_than_replaced(home):
    """Somebody's configuration, mid-edit. Overwriting it destroys the only copy."""
    path = hostinstall.host_config_path("cursor")
    path.parent.mkdir(parents=True)
    path.write_text('{ "mcpServers": { broken\n', encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(hostinstall.InstallError) as caught:
        hostinstall.install("cursor", CMD, [])

    assert "is not valid JSON, so this refuses to touch it" in str(caught.value)
    assert path.read_bytes() == before


def test_a_json_file_that_is_not_an_object_is_refused(home):
    path = hostinstall.host_config_path("cursor")
    path.parent.mkdir(parents=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(hostinstall.InstallError) as caught:
        hostinstall.install("cursor", CMD, [])

    assert "not an object; refusing to touch it" in str(caught.value)


def test_a_servers_block_that_is_not_an_object_is_refused(home):
    path = hostinstall.host_config_path("cursor")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": ["not", "a", "dict"]}), encoding="utf-8")

    with pytest.raises(hostinstall.InstallError):
        hostinstall.install("cursor", CMD, [])


def test_an_empty_file_is_treated_as_an_empty_config_not_as_a_parse_error(home):
    """A zero-byte file is what a host leaves when it has been started and never configured."""
    path = hostinstall.host_config_path("cursor")
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")

    hostinstall.install("cursor", CMD, [])

    assert json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["bantamkit"]["command"] == CMD


def test_claude_is_not_written_by_us_and_has_no_path(home):
    """`~/.claude.json` is the host's file, carrying state that is not MCP configuration."""
    with pytest.raises(hostinstall.InstallError):
        hostinstall.host_config_path("claude")


def test_the_written_json_escapes_non_ascii_so_both_runtimes_write_the_same_bytes(home):
    """`ensure_ascii` is left at its default ON PURPOSE.

    `runtime-ts`'s `dumpJson` reproduces `json.dumps` including this, so a home directory
    with a non-ASCII name — a Thai or Japanese Windows username — would otherwise make the
    two runtimes write different bytes for the same install.
    """
    hostinstall.install("cursor", "/opt/ก/bantamkit-mcp", [])
    raw = hostinstall.host_config_path("cursor").read_text(encoding="utf-8")

    assert "\\u0e01" in raw
    assert "ก" not in raw
