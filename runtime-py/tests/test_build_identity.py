"""`build_identity`: two builds under one version string, told apart BY A CALLER.

WHAT THIS GUARDS, AND WHY IT IS NOT `test_mcpdrift.py`.

`tools/mcpdrift/mcpdrift.py` closes `RB-P84`'s "nothing notices" half from OUTSIDE: it
tells a PERSON that two endpoints registered under one name differ, by probing what they
DO. This file guards the other half — that an AGENT MID-CALL can read which build
answered it — and the two are not substitutes. mcpdrift's own stated limit is that it is
bounded by what it probes: two builds differing on a path no probe touches are reported
as agreeing. `build_identity` is bounded by nothing smaller than the bytes.

THE NODE THIS FILE EXISTS FOR IS
`test_two_builds_under_one_version_string_are_told_apart_over_the_protocol`. It rebuilds
`mcpdrift`'s CAL-2 arm without pip and without a venv: two source trees whose
`__version__` is byte-identical at `0.25.0`, one with the `RB-P1` k-floor reverted, each
launched as a REAL stdio subprocess and asked over the wire who it is. Before this change
the honest answer to "which build answered me" was the version string, and CAL-2 is the
case where the version string cannot answer it. `test_two_copies_of_one_build_at_two_paths_
are_one_build` is the control that keeps this from being an always-red instrument: two
installs of one build at two different paths must read as ONE build, which is why
`build_id` is computed from content and never from location.

NO NODE HERE ASSERTS A FACT ABOUT THIS MACHINE (`RB-P14` gate 2). Every tree is written
by this file into `tmp_path`; nothing reads `~/.claude.json`, no real install is named,
and no digest is hardcoded — the fingerprints are compared against each other, never
against a literal, because a literal digest is a golden that co-moves with every file in
the package and would be re-baselined into meaninglessness within a week.

COST. Five server subprocesses across the whole file (one shared pristine arm plus one
per mutation), each a real `initialize` + `tools/call` over stdio. No network, no pip, no
model call. Nothing skips: what these nodes need, they build.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

import bantamkit  # noqa: E402
from bantamkit.assets import assets_root  # noqa: E402
from bantamkit.mcpserver import build_identity, build_server  # noqa: E402
from bantamkit.memory import Memory  # noqa: E402

PACKAGE_SRC = Path(bantamkit.__file__).resolve().parent
ASSET_SRC = assets_root()

PROTOCOL_VERSION = "2024-11-05"

# Every field the tool promises. Asserted as a SET, because the property `RB-P51` asks
# for is that a fact which could not be derived is REPORTED as underivable rather than
# dropped — and a field that vanishes in the install case is exactly the drop. A new
# field is a deliberate edit here, not a silent widening.
FIELDS = {
    "server_name",
    "version",
    "build_id",
    "code_digest",
    "code_files",
    "package_path",
    "assets_digest",
    "assets_files",
    "assets_root",
    "assets_root_from_env",
    "git_commit",
    "interpreter",
    "python_version",
    "python_implementation",
    "mcp_sdk_version",
    "unavailable",
}


# ------------------------------------------------------------------ a real stdio caller


class _Session:
    """One stdio MCP session: real subprocess, real JSON-RPC, no mocks.

    Written here rather than imported from `tools/mcpdrift/mcpdrift.py` on purpose. That
    file is an operator's instrument with its own fixture discipline and its own reasons
    to change; a guard on `mcpserver.py` that broke when the drift checker was refactored
    would be reporting on the wrong thing.
    """

    def __init__(self, import_path: Path, cwd: Path, home: Path):
        env = {k: v for k, v in os.environ.items() if k != "BANTAMKIT_ASSETS"}
        # Stripped for mcpdrift's reason: an inherited override would point every tree at
        # ONE asset pack, and the asset half of the fingerprint could never fire.
        env["HOME"] = str(home)
        env["PYTHONPATH"] = str(import_path)
        self.proc = subprocess.Popen(
            [sys.executable, "-c", "from bantamkit.mcpserver import main; main()"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            cwd=str(cwd),
            env=env,
        )
        self._id = 0

    def request(self, method: str, params: dict) -> dict:
        self._id += 1
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
            + "\n"
        )
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise OSError(f"{method}: the server closed stdout without answering")
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if parsed.get("id") == self._id:
                return parsed

    def notify(self, method: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def close(self) -> None:
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
            self.proc.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


def _tree(root: Path, name: str) -> Path:
    """A CHECKOUT-shaped build: package under `runtime-py/src`, pack at the tree root.

    The layout matters: `assets_root()` falls back to `<package>/../../../assets`, so the
    pack must sit at the tree root for a tree to be a build rather than half of one.
    Returns the tree; its import path is `<tree>/runtime-py/src`.
    """
    tree = root / name
    (tree / "runtime-py" / "src").mkdir(parents=True)
    shutil.copytree(
        PACKAGE_SRC,
        tree / "runtime-py" / "src" / "bantamkit",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(ASSET_SRC, tree / "assets", ignore=shutil.ignore_patterns("__pycache__"))
    return tree


def _import_path(tree: Path) -> Path:
    return tree / "runtime-py" / "src"


def _wheel_shaped(root: Path, name: str) -> Path:
    """A WHEEL-shaped build of the same content: pack INSIDE the package.

    This is the layout `RB-P85` pins (`bantamkit/assets/` inside the installed package)
    and the one the user-scope install on a developer machine actually has, while the
    project-scope editable install has the checkout shape. Returns the import path.
    """
    pkgroot = root / name / "pkgroot"
    pkgroot.mkdir(parents=True)
    shutil.copytree(
        PACKAGE_SRC, pkgroot / "bantamkit", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(
        ASSET_SRC, pkgroot / "bantamkit" / "assets", ignore=shutil.ignore_patterns("__pycache__")
    )
    return pkgroot


def _identity_of(import_path: Path, tmp_path: Path) -> dict:
    """Launch that build as a server and ask it, over the wire, who it is."""
    label = import_path.parent.name
    home = tmp_path / f"home-{label}"
    cwd = tmp_path / f"cwd-{label}"
    home.mkdir(exist_ok=True)
    cwd.mkdir(exist_ok=True)
    session = _Session(import_path, cwd, home)
    try:
        init = session.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test_build_identity", "version": "1"},
            },
        )
        assert "result" in init, init
        session.notify("notifications/initialized")
        answer = session.request("tools/call", {"name": "build_identity", "arguments": {}})
        result = answer["result"]
        assert not result.get("isError"), result
        identity = json.loads("".join(p.get("text", "") for p in result["content"]))
    finally:
        session.close()
    identity["_server_version"] = (init["result"]["serverInfo"] or {}).get("version")
    # RB-P55, asserted rather than hoped: an editable install can resolve `bantamkit` to
    # a checkout that is not the tree under test, and every comparison below would then
    # be one build compared with itself and would agree. The child says which tree it
    # loaded, and this is the only place that answer is allowed to be wrong.
    assert identity["package_path"].startswith(str(import_path)), (
        f"the child loaded {identity['package_path']}, not the build under test at "
        f"{import_path}; the arms are not independent and every comparison here is vacuous"
    )
    return identity


@pytest.fixture(scope="module")
def pristine(tmp_path_factory) -> dict:
    """One untouched arm, launched once, that every mutation below is compared against."""
    root = tmp_path_factory.mktemp("pristine")
    return _identity_of(_import_path(_tree(root, "A")), root)


# ------------------------------------------------------------- the advertised surface


def test_the_tool_is_listed_and_takes_no_arguments(tmp_path):
    """It is a TOOL, so the model that just got an answer can ask who answered it.

    A resource would be host-facing and an `initialize` field is read once at handshake,
    which is the gap RB-P84 names — the tool-calling agent never sees either.
    """

    import asyncio

    async def scenario():
        async with Client(build_server(Memory(store=tmp_path / "store"))) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert "build_identity" in tools
            assert not tools["build_identity"].input_schema.get("properties")
            assert not tools["build_identity"].input_schema.get("required")

    asyncio.run(scenario())


def test_every_promised_field_is_present():
    assert set(build_identity()) == FIELDS


def test_git_commit_is_a_stated_refusal_and_never_reads_as_a_value():
    """The one fact this surface will not report, reported AS not reported.

    A commit read from a checkout's HEAD describes the tree, not the imported bytes — an
    edited working copy serves different code under an unchanged sha — and an installed
    wheel has no repository at all. Either way the field would be a value that is
    sometimes a lie. It is present, it is an object rather than a string so no caller can
    read it as a sha, and the reason travels with it.
    """
    identity = build_identity()
    assert isinstance(identity["git_commit"], dict)
    assert "unavailable" in identity["git_commit"]
    assert identity["git_commit"]["unavailable"].strip()
    assert "git_commit" in identity["unavailable"]


def test_the_digests_covered_the_files_that_are_really_there():
    """Vacuity: a digest over zero files is a constant that agrees with every other one."""
    identity = build_identity()
    # Same two exclusions the surface documents, restated independently here: derived
    # bytecode, and a pack that sits inside the package only in a wheel-shaped install.
    packed = PACKAGE_SRC / "assets"
    expected_code = len(
        [
            p
            for p in PACKAGE_SRC.rglob("*.py")
            if "__pycache__" not in p.parts and not p.is_relative_to(packed)
        ]
    )
    expected_assets = len([p for p in assets_root().rglob("*") if p.is_file()])
    assert identity["code_files"] == expected_code > 1
    assert identity["assets_files"] == expected_assets > 1


def test_an_empty_asset_pack_is_unavailable_and_takes_build_id_with_it(tmp_path, monkeypatch):
    """A build that cannot see its pack has no identity — it does not have a shorter one.

    Hashing three inputs where four were promised would produce a `build_id` that agrees
    with every other build that lost the same input, which is `RB-P51`'s defect wearing a
    hex string. The field is withheld and says which input went missing.
    """
    empty = tmp_path / "no-pack"
    empty.mkdir()
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(empty))
    identity = build_identity()
    assert identity["assets_root_from_env"] is True
    assert isinstance(identity["assets_digest"], dict)
    assert isinstance(identity["build_id"], dict)
    assert "assets_digest" in identity["build_id"]["unavailable"]
    assert {"assets_digest", "assets_files", "assets_root", "build_id"} <= set(
        identity["unavailable"]
    )
    # And the code half is untouched: one missing input does not blank the answer.
    assert isinstance(identity["code_digest"], str)


# ------------------------------------------------------------------ THE acceptance node


def test_two_builds_under_one_version_string_are_told_apart_over_the_protocol(
    pristine, tmp_path
):
    """CAL-2, rebuilt: same `__version__`, one reverted k-floor, told apart by a caller.

    Both trees declare `0.25.0`, both answer `initialize` with `0.25.0`, and the
    `serverInfo.version` a host reads at handshake cannot separate them. `build_id` can,
    and the assertion that it was not the version that fired is part of the node — a
    surface that quietly regressed to reporting the version would pass everything else
    here and fail this.
    """
    tree = _tree(tmp_path, "kfloor-reverted")
    component = tree / "runtime-py" / "src" / "bantamkit" / "memory" / "component.py"
    source = component.read_text()
    floored = "budget = self.k if k is None else max(k, self.k)"
    assert floored in source, "the RB-P1 k-floor moved; this mutation no longer means CAL-2"
    component.write_text(source.replace(floored, "budget = self.k if k is None else k", 1))

    mutant = _identity_of(_import_path(tree), tmp_path)

    assert mutant["version"] == pristine["version"]
    assert mutant["_server_version"] == pristine["_server_version"] == pristine["version"]
    assert mutant["build_id"] != pristine["build_id"]
    assert mutant["code_digest"] != pristine["code_digest"]
    # The asset pack is untouched, so the half that did not change must not move. A
    # fingerprint where every field moves whenever anything moves names nothing.
    assert mutant["assets_digest"] == pristine["assets_digest"]
    assert mutant["unavailable"] == pristine["unavailable"]


def test_a_change_no_behavioural_probe_could_see_is_still_a_different_build(pristine, tmp_path):
    """One comment line — no wording, no schema, no answer changes anywhere.

    This is the case mcpdrift is bounded away from by construction: nothing it calls
    returns a different byte. Identity is over the source, so it fires anyway.
    """
    tree = _tree(tmp_path, "comment-only")
    target = tree / "runtime-py" / "src" / "bantamkit" / "textutil.py"
    target.write_text(target.read_text() + "\n# a comment that changes no behaviour\n")

    mutant = _identity_of(_import_path(tree), tmp_path)

    assert mutant["version"] == pristine["version"]
    assert mutant["code_digest"] != pristine["code_digest"]
    assert mutant["build_id"] != pristine["build_id"]


def test_an_asset_only_change_moves_the_build_id_on_its_own(pristine, tmp_path):
    """The asset half, shown firing alone: same code, different pack, different build.

    `RB-P84` measured `contracts/default.yaml` as the one asset that differed between the
    two live builds while no resource template exposed it — an asset pack that is not in
    the fingerprint is a way for two builds to differ invisibly.
    """
    tree = _tree(tmp_path, "asset-only")
    contract = tree / "assets" / "contracts" / "default.yaml"
    assert contract.is_file(), "the asset this node edits moved; pick another and say so"
    contract.write_text(contract.read_text() + "\n# edited by test_build_identity\n")

    mutant = _identity_of(_import_path(tree), tmp_path)

    assert mutant["code_digest"] == pristine["code_digest"]
    assert mutant["assets_digest"] != pristine["assets_digest"]
    assert mutant["build_id"] != pristine["build_id"]


# ---------------------------------------------------------------------------- the control


def test_two_copies_of_one_build_at_two_paths_are_one_build(pristine, tmp_path):
    """The control. Without it, everything above is satisfied by an always-red instrument.

    Two independent trees, two separate subprocesses, two different `package_path`s — and
    ONE `build_id`. That is why identity is computed from content and location is reported
    beside it rather than folded into it: the same build installed twice is one build, and
    a fingerprint that said otherwise would call every machine's user-scope and
    project-scope installs different builds on the day they were refreshed from the same
    commit.
    """
    twin = _identity_of(_import_path(_tree(tmp_path, "twin")), tmp_path)

    assert twin["package_path"] != pristine["package_path"]
    assert twin["assets_root"] != pristine["assets_root"]
    assert twin["build_id"] == pristine["build_id"]
    for field in ("version", "code_digest", "code_files", "assets_digest", "assets_files"):
        assert twin[field] == pristine[field], field


def test_one_build_in_two_install_shapes_is_one_build(pristine, tmp_path):
    """The control that FOUND A DEFECT, and it is the reason it is here.

    This project installs as two shapes: a wheel, where the asset pack sits INSIDE the
    package (`RB-P85`), and an editable checkout, where it sits beside the repository
    root. That is not hypothetical — it is exactly the pair registered under one name on
    a developer machine, user scope a wheel and project scope editable.

    The first version of this surface walked `<package>/**/*.py` with no exclusion. The
    asset pack carries eleven `.py` files of its own (`assets/evals/devteam/repo/`), so
    the wheel shape counted 33 source files and the checkout shape 22 — and the two
    reported DIFFERENT `build_id`s for byte-identical content. A fingerprint that calls
    one build two builds is worse than none: it is an alarm that fires on the normal
    state of the machine it was written for, and it would have been believed once.

    Both arms below hold identical content; only the shape differs.
    """
    wheel = _identity_of(_wheel_shaped(tmp_path, "wheelish"), tmp_path)

    assert wheel["package_path"] != pristine["package_path"]
    assert wheel["assets_root"].startswith(wheel["package_path"])
    assert not pristine["assets_root"].startswith(pristine["package_path"])
    assert wheel["code_files"] == pristine["code_files"]
    assert wheel["assets_files"] == pristine["assets_files"]
    assert wheel["code_digest"] == pristine["code_digest"]
    assert wheel["assets_digest"] == pristine["assets_digest"]
    assert wheel["build_id"] == pristine["build_id"]
