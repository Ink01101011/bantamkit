"""The project-scope MCP endpoint, EXECUTED AS THE PROGRAM `.mcp.json` NAMES.

WHAT WAS UNCOVERED, AND IT IS NOT A THIN GAP. `test_mcpserver.py` carries 31 nodes and
two of them spawn a real stdio server and complete a real handshake. Both spawn
`sys.executable`: `-c "from bantamkit.mcpserver import main; main()"` and
`-m bantamkit.mcpserver`. Those are MODULE ENTRY POINTS, and no host runs either one. A
host runs the string in `.mcp.json`, which is `tools/bantamkit-mcp` -- a POSIX `sh`
script that, before `main()` is ever reached, locates a checkout from `$0`, locates a
dependency root by reading `.git` and `.git/worktrees/<name>/commondir` by hand, picks an
interpreter out of two candidate venvs or `PATH`, and sets `PYTHONPATH` and
`PYTHONSAFEPATH`. Every one of those steps can fail on a machine where both entry-point
nodes are green, and each failure reaches the client as `CONNECTION_CLOSED` with no cause
attached. Measured 2026-08-22, before this file existed:

    $ grep -rln "bantamkit-mcp" runtime-py/tests/
    runtime-py/tests/test_mcpdrift.py

and that one match is `test_mcpdrift.py` writing the STRING into a synthetic `.mcp.json`
fixture to test the config reader. It never executes the artefact either.

WHY THE HANDSHAKE IS THE ASSERTION AND "IT STARTED" IS NOT. The prototype this launcher
replaced fell through to a bare `python3`, imported nothing, and died on a transitive
dependency -- a process that starts, prints a traceback to stderr and closes stdout is
indistinguishable from a healthy one until somebody asks it a question. `RB-P96` and the
`mcpdrift` read timeout are both that shape. So this file asks.

WHY IT ALSO ASKS *WHICH BUILD ANSWERED*. This machine can resolve `bantamkit` three ways:
the worktree's own `runtime-py/src` (via the launcher's `PYTHONPATH`), the MAIN
checkout's `runtime-py/src` (via the venv's `_editable_impl_bantamkit.pth`), and a
`site-packages/bantamkit/` directory that carries an asset pack. `importlib.metadata`
reports `0.3.0` for that install while `__version__` reads `0.25.0`, so the version
string cannot arbitrate and has already lied here once (`RB-P45`). `build_identity`
exists for exactly this question (`RB-P84`), and the answer this file asserts against is
derived from the TREE -- the directory the launcher must have imported, the number of
`.py` files actually on disk in it, and a content digest -- never from a version string.

WHAT A GREEN HERE DOES NOT COVER. The launcher's dependency-root half. On this machine
the worktree carries a `.venv` symlink, so `$here/.venv/bin/python` is found on the first
candidate and `$root` is never consulted for the interpreter. A worktree with no `.venv`
at all exercises a branch this node does not reach; that is `mcpreach`'s territory and it
is stated here rather than implied.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from conftest import ON_WINDOWS, WINDOWS_SKIP_TOKEN

pytest.importorskip("mcp")

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

import bantamkit  # noqa: E402
from bantamkit.mcpserver import build_identity  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "runtime-py" / "src"
PACKAGE = SRC / "bantamkit"
MCP_JSON = REPO / ".mcp.json"

# The command string as SHIPPED, read from the tracked config rather than restated. A
# node that hardcodes the path stops describing the endpoint the moment `.mcp.json`
# moves, and `.mcp.json` moving is precisely the `RB-P96` regression.
ENDPOINT_COMMAND: str = json.loads(MCP_JSON.read_text(encoding="utf-8"))["mcpServers"][
    "bantamkit"
]["command"]
ENDPOINT = (REPO / ENDPOINT_COMMAND).resolve()

# A handshake that never returns is the failure mode `mcpdrift` was bitten by: a launcher
# that spawns and then answers nothing hangs the caller instead of failing it. Bounded, so
# this node reports rather than wedges a suite.
HANDSHAKE_TIMEOUT_S = 60.0

_WINDOWS_EXECUTABLE_SUFFIXES = (".exe", ".cmd", ".bat", ".com", ".ps1")

NO_WINDOWS_ENDPOINT = (
    ON_WINDOWS
    and ENDPOINT.suffix.lower() not in _WINDOWS_EXECUTABLE_SUFFIXES
    and not any(
        ENDPOINT.with_name(ENDPOINT.name + suffix).exists()
        for suffix in _WINDOWS_EXECUTABLE_SUFFIXES
    )
)
"""True while the configured endpoint is a thing Windows cannot `CreateProcess`.

Deliberately NOT `sys.platform == "win32"`. `tools/bantamkit-mcp` is `#!/bin/sh` and
Windows has no shebang, so today this is true there -- but the day someone ships a
`tools/bantamkit-mcp.cmd`, or points `.mcp.json` at one, this goes FALSE on Windows and
`test_criticreplay.py::test_the_windows_only_skips_do_not_fire_on_this_platform` reddens
on the Windows runner until this entry is struck from its roster. A skip that expires
when its cause is fixed is the only kind that cannot outlive the defect it excuses.
"""


def _package_py_files() -> list[Path]:
    """The `.py` files `_code_fingerprint` would count, enumerated FROM DISK.

    Same two exclusions as the implementation, restated here on purpose: this list is
    what the node compares the server's answer against, so deriving it by calling the
    implementation would make the comparison say only that a function equals itself.
    """
    packed_assets = PACKAGE / "assets"
    return sorted(
        p
        for p in PACKAGE.rglob("*.py")
        if "__pycache__" not in p.parts and not p.is_relative_to(packed_assets)
    )


def test_the_command_in_mcp_json_names_a_file_present_in_every_checkout():
    """`RB-P96` as a node: a TRACKED config must not name an UNTRACKED path.

    `.mcp.json` ships in the repository, so every clone and every `git worktree` receives
    the same command string, and the client resolves it against the project directory.
    The string it used to carry was `.venv/bin/bantamkit-mcp`. A worktree has no `.venv`,
    so from a worktree that endpoint was `ENOENT ... posix_spawn` -- printed beside a
    `[Conflicting scopes]` warning that appears in the healthy case too and therefore
    says nothing about which endpoint is reachable. This program runs implementation
    units in worktrees by policy, so the blast radius was "the subagent has no bantamkit
    tools", diagnosed as a scope warning.

    THIS NODE RUNS ON EVERY PLATFORM, including the one its sibling below cannot be put
    into: the property is about what the repository contains, not about `exec`. It is
    what a Windows runner still measures here.

    `.venv` is named explicitly rather than checked by asking `git`, so the node needs no
    subprocess and no `git` on `PATH` -- and `.venv` is the exact component whose absence
    from a worktree caused the outage.
    """
    configured = Path(ENDPOINT_COMMAND)
    assert not configured.is_absolute(), ENDPOINT_COMMAND
    assert ".venv" not in configured.parts, ENDPOINT_COMMAND
    assert ENDPOINT.is_relative_to(REPO), (ENDPOINT, REPO)
    assert ENDPOINT.is_file(), ENDPOINT
    assert os.access(ENDPOINT, os.X_OK), ENDPOINT


@pytest.mark.skipif(
    NO_WINDOWS_ENDPOINT,
    reason=(
        "`.mcp.json` names `tools/bantamkit-mcp`, a `#!/bin/sh` script; Windows has no "
        "shebang and `CreateProcess` refuses it with WinError 193, before the server is "
        f"reached. This run therefore {WINDOWS_SKIP_TOKEN}: that the endpoint string a "
        "Windows host would actually spawn completes an MCP `initialize` and serves the "
        "build sitting in the checkout it was launched from -- so on Windows the "
        "project-scope registration is unmeasured end to end, and whether the launcher's "
        "checkout-vs-dependency-root split survives a Windows path layout at all is "
        "unknown rather than known-broken. The Windows launcher is deferred by the user, "
        "not overlooked."
    ),
)
def test_the_endpoint_as_configured_serves_and_names_this_checkout_as_its_source(tmp_path):
    """Spawn the string `.mcp.json` carries, from the project directory, and interrogate it.

    THE INVOCATION IS THE HOST'S, not a convenient rewrite of it: the relative command
    verbatim, `cwd` set to the project directory the client would resolve it against, and
    nothing prepended. `--store` rather than `--start`, because `--start` walks ancestors
    looking for `.bantamkit/memory` and from a worktree that walk climbs out of the
    repository entirely; a node that reads whatever store this machine happens to have is
    asserting a fact about the machine.

    `env=` IS PASSED EXPLICITLY, and for the reason written out at length at
    `test_mcpserver.py:365` and pointed at again from `:419` -- `StdioServerParameters`
    otherwise defaults to `get_default_environment()`, which hands the child a short
    allow-list rather than this process's environment. That reasoning is not restated
    here. What IS stated here is the half that INVERTS for this node, because the subject
    is different: those two nodes spawn `sys.executable` and must ADD `PYTHONPATH` to
    reach the checkout, whereas this node spawns the artefact whose own job is to set
    `PYTHONPATH` from `$0` -- so `PYTHONPATH` is DELETED here rather than added.

    THE DELETION IS THE LOAD-BEARING HALF, AND `env=` IS NOT. Three runs, 2026-08-22,
    each against a `git archive HEAD` copy of this tree carrying this file, launcher
    mutated by hand where noted:

        launcher            node passes                     result
        ------------------  ------------------------------  ---------------
        as shipped          env= with PYTHONPATH deleted     2 passed
        PYTHONPATH deleted  env= with PYTHONPATH deleted     1 failed  <- caught
        PYTHONPATH deleted  env= with SRC prepended          2 passed  <- BLIND
        as shipped          no env= at all                   2 passed
        PYTHONPATH deleted  no env= at all                   1 failed  <- caught

    Copy the sibling's `env["PYTHONPATH"] = str(SRC) + ...` line in and row three is what
    you get: the checkout is on the child's path whatever the launcher does, `--which`
    reports the OTHER checkout as the source, and this node still goes green. Dropping
    `env=` entirely, by contrast, changes no outcome at all -- `get_default_environment()`
    strips `PYTHONPATH`, so it produces this node's precondition by accident. `env=` is
    kept anyway, and the honest reason is not "otherwise the wrong build answers": it is
    that the launcher's own discovery reads `PATH` for `git` and for its `python3`
    fallback, and an operator's `BANTAMKIT_*` overrides are part of the environment a
    host would hand it. What this node contracts for is one named absence, not an
    allow-list the SDK is free to change under it. A host does not export `PYTHONPATH`
    either, so this is also the truer invocation.

    WHICH BUILD ANSWERED, and why the version string is not the answer. Three
    resolutions are live in this venv -- the worktree's `runtime-py/src`, the main
    checkout's `runtime-py/src` reachable through `_editable_impl_bantamkit.pth`, and a
    `site-packages/bantamkit/` whose dist-info reads `0.3.0` against a `__version__` of
    `0.25.0`. Two of the three would satisfy `version == bantamkit.__version__`, which is
    why that assertion is absent. `package_path` is asserted instead, against a path
    derived from THIS FILE's location, and `code_files`/`code_digest` against the tree on
    disk at that path. What that catches, concretely: strike `PYTHONPATH` from the
    launcher and it answers from the main checkout -- same name, same version, same tool
    list, different bytes -- and `package_path` names the other directory. That is
    `RB-P55`/`RB-P70` reaching through the shipped launcher, and it is the failure the
    launcher's own header calls "worse than the ENOENT it replaces, because it fails
    silently and plausibly".

    The in-process guard is first for a reason: it establishes that the process doing the
    asserting is itself running the worktree's source, without which a digest comparison
    would be two unknowns agreeing.
    """
    assert Path(bantamkit.__file__).resolve() == PACKAGE / "__init__.py", (
        "this pytest process did not import the checkout under test; run it with "
        "PYTHONPATH=runtime-py/src, or the comparison below compares two strangers"
    )

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    async def scenario(store: Path) -> dict:
        params = StdioServerParameters(
            command=ENDPOINT_COMMAND,
            args=["--store", str(store)],
            cwd=str(REPO),
            env=env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                async with asyncio.timeout(HANDSHAKE_TIMEOUT_S):
                    init = await session.initialize()
                    assert init.server_info.name == "bantamkit"
                    # Asking it something is the point: a launcher that spawns and then
                    # answers nothing passes every check that only watches for a process.
                    answer = await session.call_tool("build_identity", {})
                    assert not answer.is_error, answer
                    return json.loads("".join(part.text for part in answer.content))

    identity = asyncio.run(scenario(tmp_path / "store"))

    # LOCATION: the launcher imported the tree this file lives in, not one of the other
    # two `bantamkit` resolutions this interpreter can reach.
    assert identity["package_path"] == str(PACKAGE), identity

    # CONTENT: and the tree it imported is the one on disk right now. `code_files` is
    # counted from disk by this file; `code_digest` is compared against the same
    # computation performed in this process, which the guard above pinned to this tree.
    # Neither is a literal, because a hardcoded digest co-moves with every file in the
    # package and gets re-baselined into meaninglessness (`test_build_identity.py`).
    assert identity["code_files"] == len(_package_py_files()), identity
    assert identity["code_digest"] == build_identity()["code_digest"], identity
    assert identity["code_digest"].startswith("sha256:"), identity
