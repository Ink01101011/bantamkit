"""`tools/bantamkit-mcp --which`, executed.

THE PARITY GAP THIS CLOSES. `runtime-ts/test/launcher.test.mjs` runs the Node
launcher's `--which` on a bare checkout and on a hand-built worktree, and its
worktree node says in as many words that inverting the launcher's
`[ "$label" = "gitdir:" ]` test "collapses `deps_root` onto the worktree — the
mutation `test_mcp_endpoint.py` reports NOTHING catching on the Python side.
Here it is red." That sentence was true: `git grep '"--which"' runtime-py/tests`
found only PROSE about the flag, never an execution of it, so the Python
launcher's half of the two-halves split was documented in three files and
executed by none. job40's C2 named the gap and refused to widen its own unit to
close it.

WHAT IS ACTUALLY UNDER TEST is the resolution, not the printing: `checkout` is
`$0`'s grandparent and must be the WORKTREE, while `deps_root` follows
`.git` -> `gitdir:` -> `commondir` back to the MAIN checkout. Getting that
backwards is the failure the launcher's own header calls "worse than the ENOENT
it replaces, because it fails silently and plausibly" — a unit editing
`runtime-py/src` in a worktree gets answered by the main checkout's editable
install.

The two-file worktree layout is built BY HAND, exactly as the Node test builds
it, because the launcher parses it by hand too: it reads `.git` and `commondir`
with the shell builtin `read` precisely so it still answers when `git` is not on
`PATH`. Driving it with a real `git worktree` would test `git`.

`--which` is the only surface where this is observable without starting a
server, and it uses `find_spec`, which does not execute the package — so these
nodes need no venv, no dependencies and no build.

WHAT EACH NODE IS WORTH, measured 2026-08-25 by running these three functions
against MUTATED COPIES of the launcher in a scratch directory — never against
the tree, which a live unit holds:

  * `[ "$label" = "gitdir:" ]` INVERTED  -> worktree RED, decoy RED, bare green
  * the label test DELETED (`:`)         -> decoy RED, worktree green, bare green

The two mutations redden different nodes, which is why both nodes are here: with
the test deleted the worktree case still resolves correctly by accident, because
`read` has already put the path in `gitdir` and nothing downstream re-checks it.
The bare-checkout node reddens under neither and is a smoke node by admission —
it asserts that a checkout with no `.git` at all keeps both halves in one place
and that a missing package prints rather than crashes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[2] / "tools" / "bantamkit-mcp"

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "PRICED, not portability debt: `tools/bantamkit-mcp` is `#!/bin/sh` and Windows "
        "has no POSIX shell to run it. That the shipped endpoint is unrunnable there is "
        "RB-P101, an open backlog item with its own job, and skipping here records it "
        "rather than hiding it — the Node launcher, which IS runnable on Windows, is "
        "covered by runtime-ts/test/launcher.test.mjs on every cell of the matrix."
    ),
)


def _checkout(root: Path, name: str) -> Path:
    """A checkout carrying nothing but the launcher — all a fresh clone or worktree has."""
    directory = root / name
    (directory / "tools").mkdir(parents=True)
    target = directory / "tools" / "bantamkit-mcp"
    shutil.copy2(LAUNCHER, target)
    target.chmod(0o755)
    return directory


def _worktree_of(main: Path, root: Path, name: str) -> Path:
    """The two-file layout `git worktree` writes, built by hand."""
    worktree = _checkout(root, name)
    gitdir = main / ".git" / "worktrees" / name
    gitdir.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    return worktree


def _which(directory: Path) -> dict[str, str]:
    """`key=value` lines from `--which`, as a map."""
    result = subprocess.run(
        [str(directory / "tools" / "bantamkit-mcp"), "--which"],
        capture_output=True,
        text=True,
        # NAMED, and `test_encoding_gate.py` is what made it named: `text=True` alone
        # decodes through `locale.getpreferredencoding()`, which is a code page on
        # Windows. The launcher's `--which` prints paths, and a path outside that code
        # page would come back mojibake or raise.
        encoding="utf-8",
        input="",
        check=False,
    )
    assert result.returncode == 0, (
        f"--which exited {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    facts: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            facts[key] = value
    return facts


def test_which_answers_on_a_checkout_that_has_never_been_built(tmp_path: Path) -> None:
    """No `.venv`, no `runtime-py/src`, no dependencies — it still answers."""
    directory = _checkout(tmp_path, "bare")
    facts = _which(directory)
    assert facts["checkout"] == str(directory)
    # No `.git` file and `git rev-parse` cannot answer from a directory that is not a
    # repository, so the launcher keeps `root=$here`: the two halves are the same place.
    assert facts["deps_root"] == str(directory)
    assert Path(facts["python"]).name.startswith("python")
    # `source=` is whatever `find_spec` sees through the interpreter that was found, which
    # depends on the machine. It is asserted to be PRESENT and not to be a crash — the
    # launcher catches BaseException and prints "unresolvable: ..." rather than dying.
    assert "source" in facts
    assert not facts["source"].startswith("unresolvable:")


def test_a_worktree_takes_code_from_itself_and_deps_root_from_commondir(
    tmp_path: Path,
) -> None:
    """The node the Node suite has and this side did not.

    Inverting the launcher's `[ "$label" = "gitdir:" ]` leaves `gitdir` empty, so
    `commondir` is never read and `root` stays `$here` — `deps_root` collapses onto the
    worktree and the split silently stops existing. That mutation is red here.
    """
    main = _checkout(tmp_path, "main")
    (main / ".git").mkdir()
    worktree = _worktree_of(main, tmp_path, "wt")

    facts = _which(worktree)

    # CODE comes from the checkout the launcher was spawned out of: the worktree.
    assert facts["checkout"] == str(worktree)
    # DEPENDENCIES come from the main checkout, reached through `commondir`.
    assert facts["deps_root"] == str(main)
    # The whole point of the split, stated so a collapse cannot pass:
    assert facts["deps_root"] != facts["checkout"]


def test_a_git_file_that_is_not_a_gitdir_pointer_is_ignored(tmp_path: Path) -> None:
    """`[ "$label" = "gitdir:" ]` is a guard, and this is what it guards against.

    A `.git` file whose first word is anything else must NOT be followed. Without the
    label test the launcher would take the SECOND field of an arbitrary file as a path,
    and `deps_root` would name a directory nobody chose.

    The decoy is what makes this node bite. Pointing at `/somewhere/else` proves nothing:
    the very next test is `[ -f "$gitdir/commondir" ]`, which fails for any path that
    happens not to exist, so the guard could be deleted and the case would still pass. So
    the decoy directory HOLDS a `commondir`, and it names a real directory — everything
    downstream of the label test succeeds. The label test is then the only thing standing
    between this checkout and a `deps_root` of somebody else's tree.
    """
    directory = _checkout(tmp_path, "notapointer")
    decoy = tmp_path / "decoy" / ".git"
    (decoy / "worktrees" / "x").mkdir(parents=True)
    hijacked = tmp_path / "decoy"
    (decoy / "worktrees" / "x" / "commondir").write_text("../..\n", encoding="utf-8")
    (directory / ".git").write_text(
        f"nonsense {decoy / 'worktrees' / 'x'}\n", encoding="utf-8"
    )

    facts = _which(directory)

    assert facts["checkout"] == str(directory)
    assert facts["deps_root"] == str(directory)
    assert facts["deps_root"] != str(hijacked)
