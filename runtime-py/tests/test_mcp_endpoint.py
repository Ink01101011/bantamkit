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

WHAT A GREEN HERE DOES NOT COVER, AND WHO COVERS IT: NOBODY. The launcher's
dependency-root half. On this machine the worktree carries a `.venv` symlink, so
`$here/.venv/bin/python` is found on the first candidate and `$root` is never consulted
for the interpreter. A worktree with no `.venv` at all exercises a branch this node does
not reach. MEASURED 2026-08-23 rather than reasoned about: against a `git archive HEAD`
copy given the two-file worktree layout the launcher parses by hand (a `.git` FILE
holding `gitdir:`, and a `commondir` beside it), inverting the launcher's
`[ "$label" = "gitdir:" ]` test collapses `--which`'s `deps_root=` from the main checkout
to the worktree itself -- and this file still reports `2 passed`. The whole `commondir`
reader can be wrong without one node in the suite noticing.

An earlier revision of this docstring deferred that gap to `mcpreach`. It does not exist:

    $ git log --all --oneline --diff-filter=A -- '*mcpreach*'
    $ git ls-tree -r --name-only origin/main | grep -i mcpreach

both empty -- the path has never been added on any ref in this repository's history. It
WAS cited as a real command anyway, by `tools/bantamkit-mcp:47` ("`--which` ...
`tools/mcpreach/mcpreach.py` reads it") and by `docs/mcp.md:154`, which documented a
five-value exit-code interface for it -- `2 FOREIGN` being precisely the silent
wrong-checkout failure this file exists to catch. So the endpoint's own documentation
pointed an operator at vaporware for the one check it called "not a thing to reason
about". Both citations are gone as of 2026-08-24; the paragraphs below are the record of
why, and the closing note at the end says what replaced them.

IT IS NOT AN UNOWNED GAP, WHICH IS WHAT AN EARLIER REVISION OF THIS PARAGRAPH CALLED IT.
`docs/eval.md:10949` -- in `AD.1 RB-P96 -- FIXED (2026-08-21, PR #58, 927b2a8)`, the very
section that shipped this launcher -- records the decision in writing:

    **Not shipped, deliberately:** the unit's half-built `tools/mcpreach/` checker was
    uncommitted and had **never been seen to fire**. A check nobody has watched go red is
    not a check, so it was set aside rather than merged.

That is a reasoned decision with a named owner, and it inverts the conclusion. What is
open is not an absent checker but a THREE-FILE CONTRADICTION about one: `docs/eval.md`
says deliberately withheld, while `docs/mcp.md:154` presents the same program as the
runnable answer with five documented exit codes and `tools/bantamkit-mcp:47` says it reads
`--which`. Two of the three document a program the third says was consciously not
shipped, and the contradiction is not inert. Measured 2026-08-23, running the command
`docs/mcp.md:154` gives an operator verbatim:

    $ .venv/bin/python tools/mcpreach/mcpreach.py check
    can't open file '.../tools/mcpreach/mcpreach.py': [Errno 2] No such file or directory
    $ echo $?
    2

and `2` is the value that same page documented as `FOREIGN`, "it launched, but it is
serving a DIFFERENT checkout's source". A missing file and the silent wrong-checkout
failure are the same exit code to anything scripting the documented interface.

CLOSED 2026-08-24, and this file is half of what closed it. `docs/mcp.md` no longer
documents `mcpreach`; it now points an operator at `--which` on either launcher for the
resolution half and at THIS FILE, by name and by node, for the half that requires asking
the endpoint a question -- which is the half `--which` cannot do and the half `2 FOREIGN`
was reaching for. `tools/bantamkit-mcp:47` no longer claims a program consumer for
`--which`. The three files agree, and `runtime-py/tests/test_doc_commands_gate.py` is
what keeps them agreeing: it is red if any fenced shell block in a tracked `.md` names a
`tools/` program that is not in the tree. It deliberately does NOT key on the mention, so
the four prose citations of `tools/mcpreach/mcpreach.py` that exist to record its absence
-- including the ones above -- stay writable.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
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

THAT EXPIRY IS MEASURED, NOT ASSERTED. 2026-08-23, on `git archive HEAD` copies, with
`conftest.ON_WINDOWS` forced true and the test modules reloaded so every condition and
every `skipif` mark re-executes as a Windows runner would build them -- then the roster
node called directly. Four scratch trees:

    tree                                    NO_WINDOWS_ENDPOINT   roster node
    --------------------------------------  --------------------  -----------
    as shipped                              True                  PASS
    + tools/bantamkit-mcp.cmd               False                 FAIL
    + .cmd, .mcp.json repointed at it       False                 FAIL
    + tools/bantamkit-mcp.ps1               False                 FAIL

Rows two and three are the claim, confirmed on both routes: the day a Windows launcher
lands, this stops skipping and the roster goes red until someone edits it. Row four is a
known imprecision -- `CreateProcess` cannot run a `.ps1` directly, so that suffix flips
the gate for a form Windows still cannot spawn. It is left in deliberately: the failure
it produces is LOUD (the roster reddens, and the node below runs and fails WinError 193)
rather than a silent skip, and a `.ps1` appearing beside the launcher is a fair signal
that someone is mid-way through shipping the Windows endpoint. Erring toward noise is
the correct direction for a gate whose whole purpose is to not outlive its excuse.
"""


# A child that reports its own environment and exits. Spawned through the SAME
# `stdio_client` with the SAME `env=`, because the question is what THIS SDK hands a
# child, and that is not readable off `env=` -- see the node below.
# Written to a sibling and renamed into place, NOT straight to `sys.argv[1]`. The reader
# below polls for the file to appear, and `json.dump` writes through a buffered stream:
# measured 2026-08-23, this child's environment serializes to 7,602 bytes against an
# 8,192-byte default buffer, so today it lands in one `write()` and the poll cannot see a
# partial file. 590 bytes of margin is not a contract. A larger environment -- a CI runner
# is the obvious case, and whether any of ours crosses it is UNMEASURED -- splits the dump
# into several syscalls and the poll starts reading truncated JSON, reddening this node
# with a `JSONDecodeError` that says nothing about what it guards. `os.replace` is atomic,
# so the name either does not exist or names a complete file.
_ENV_DUMP_SOURCE = (
    "import json,os,sys;"
    "p=sys.argv[1];tmp=p+'.part';"
    "json.dump(dict(os.environ), open(tmp, 'w', encoding='utf-8'));"
    "os.replace(tmp, p)"
)


def _environment_the_sdk_hands_a_child(env: dict[str, str], scratch: Path) -> dict[str, str]:
    """The child's ACTUAL environment, read out of a child this SDK really spawned.

    Not `get_default_environment() | env` restated here -- though be precise about why,
    because an earlier revision of this docstring overclaimed. That form calls the SDK's
    own function, so it WOULD have caught the drift that motivated this guard. What it
    could not catch is the class beyond the allow-list: the merge being reordered or
    removed, `env=` being ignored, or a platform-specific process path injecting its own
    environment. This spawns through the same `stdio_client` with the same `env=` and asks
    the child, so it measures the end state instead of a model of how the end state is
    computed. `sys.executable` rather
    than the endpoint on purpose -- the subject is how the SDK builds a child's
    environment, and the launcher would overwrite the one key in question.

    The child writes and exits; `stdio_client` never gets a handshake and does not need
    one. The poll is bounded by the same timeout as the real one, so a child that never
    writes reports instead of wedging the suite.
    """
    dump = scratch / "child-environment.json"

    async def run() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", _ENV_DUMP_SOURCE, str(dump)],
            cwd=str(REPO),
            env=env,
        )
        async with stdio_client(params) as (_read, _write):
            async with asyncio.timeout(HANDSHAKE_TIMEOUT_S):
                while not (dump.is_file() and dump.stat().st_size):
                    await asyncio.sleep(0.02)

    asyncio.run(run())
    return json.loads(dump.read_text(encoding="utf-8"))


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
    host would hand it. A host does not export `PYTHONPATH` either, so this is also the
    truer invocation.

    AND THE ABSENCE IS CONTRACTED RATHER THAN ASSUMED, because `env=` does not deliver
    it. `mcp/client/stdio.py:128` spawns with `env=get_default_environment() |
    (server.env or {})` -- a MERGE, not a substitution -- so any key the SDK carries in
    `DEFAULT_INHERITED_ENV_VARS` reaches the child however this node builds `env=`. On
    posix that list is `HOME LOGNAME PATH SHELL TERM USER`, and `PYTHONPATH` not being on
    it is the ONLY reason the deletion above holds. Measured 2026-08-23, one line of
    upstream drift appended to that list before this file was collected:

        DEFAULT_INHERITED_ENV_VARS   child's PYTHONPATH   node, before / after the guard
        ---------------------------  -------------------  -----------------------------
        as installed                 absent               2 passed / 2 passed
        + "PYTHONPATH"               PRESENT              2 passed / 1 failed  <- caught

    The `before` column is the defect, and it is worse in combination. Delete the
    launcher's own `PYTHONPATH` line as well -- the r2 mutation two tables down, the one
    this node exists to catch -- and the pair reads `1 failed` without the drift and
    `2 passed` WITH it, before the guard; `1 failed` both ways after. One upstream line
    was enough to retire the only node in the suite that can see a launcher which stopped
    setting `PYTHONPATH`. `_environment_the_sdk_hands_a_child` reads the environment out
    of a child THIS SDK spawned with THIS `env=`, so the guard moves with the SDK's real
    behaviour -- allow-list, merge order, or the merge itself going away -- rather than
    restating line 128 and hoping it stays put.

    WHAT THIS NODE ACTUALLY CATCHES, mutation by mutation. 2026-08-23, each against a
    fresh `git archive HEAD` copy with the `.venv` symlink restored, launcher corrupted
    the way a real one could rot. The point of the last three rows is that they are GREEN,
    and the set is priced rather than complete -- row five was found by review, after the
    first four had been written up as though they were the whole of it:

        mutation of tools/bantamkit-mcp              outcome     caught by
        -------------------------------------------  ----------  --------------------
        shebang -> `#!/bin/shh`                      1 failed    spawn, FileNotFoundError
        `PYTHONPATH=$here/...` -> `$root/...`        1 failed    package_path
        `PYTHONSAFEPATH=1` deleted                   2 passed    NOTHING
        `[ "$label" = "gitdir:" ]` inverted          2 passed    NOTHING
        trailing `"$@"` dropped from `exec`          2 passed    NOTHING

    ROW ONE reports `FileNotFoundError: [Errno 2] ... 'tools/bantamkit-mcp'`, and the
    errno is a lie worth knowing about: the file is present and `+x`: it is `/bin/shh`
    that is missing. The sibling node above stays GREEN on this mutation, because
    `os.access(X_OK)` is true of a script whose interpreter does not exist. Only actually
    spawning it tells them apart, which is why "it is executable" is not the assertion.

    ROW TWO is the one the launcher's own header calls "worse than the ENOENT it
    replaces, because it fails silently and plausibly", and it was reproduced against a
    fabricated-but-faithful worktree layout so `$root` names a different tree. The child
    handshakes, serves `bantamkit`, reports the same `version` (`0.25.0`), the same
    `code_files` (23) and -- both trees being the same archive -- a BYTE-IDENTICAL
    `code_digest`. Every assertion in this node passes except `package_path`. So
    `package_path` is not one check among four here; on a same-content wrong checkout it
    is the ONLY one with any discriminating power, and deleting it would leave a node
    that cannot tell two checkouts apart at all.

    ROW THREE is green because the defence is untested, not because the line is dead.
    `PYTHONSAFEPATH` stops the client's cwd being prepended ahead of `PYTHONPATH`, and no
    `bantamkit/` sits at this repository's root, so nothing contests the path. Plant a
    complete one there (sources plus an `assets/` tree, or the server dies at startup on
    `AssetNotFound` and reddens this node for the wrong reason) and the same mutation
    goes `1 failed` on `package_path`, serving a decoy that reported `version
    6.6.6-DECOY`. The precondition, not the guard, is what this tree is missing.

    ROW FOUR is the dependency-root half, and the module docstring above prices it.

    ROW FIVE swallows the host's entire argv: `exec "$py" -c '...' "$@"` with the trailing
    `"$@"` gone. Every assertion in this node still passes, because none of them is about
    what the server was ASKED for -- and this node's own isolation argument, four
    paragraphs up, is exactly that. With argv forwarded the server binds the `--store` it
    was handed; without it `_build_memory` falls through to `Memory.layered(start=None)`,
    which is `--start` semantics, and `discover_project_store` walks up from the client's
    `cwd`. Measured 2026-08-23 on the same two archive copies, by opening the same session
    this node opens and then asking the server to WRITE:

        launcher            where the saved fact landed
        ------------------  --------------------------------------------------
        as shipped          <the --store this node passed>/facts/f2-argv-probe.md
        `"$@"` dropped      <cwd>/.bantamkit/memory/facts/f2-argv-probe.md

    In row two the asked-for store was never created at all, and `cwd` is the checkout.
    So the launcher can be silently writing memory INTO the repository it was launched
    from and this node reports `2 passed`. It stays unclosed here on purpose: nothing on
    the wire reports the bound store -- `build_identity` is location-of-code, not
    location-of-store -- so closing it is a `runtime-py/src` change, not a test-layer one.

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

    # The deletion above is a REQUEST, not a guarantee: the SDK merges. Contract the
    # absence against a child it actually spawned, or the one node that can catch a
    # launcher which stopped setting `PYTHONPATH` is one upstream line from passing
    # forever. See "AND THE ABSENCE IS CONTRACTED" above.
    child_env = _environment_the_sdk_hands_a_child(env, tmp_path)
    assert "PYTHONPATH" not in child_env, (
        "the SDK handed the child a PYTHONPATH this node deleted, so the launcher's own "
        "PYTHONPATH line is no longer what puts this checkout on the child's path and "
        "the assertions below can no longer tell two checkouts apart: "
        f"PYTHONPATH={child_env['PYTHONPATH']!r}"
    )

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
