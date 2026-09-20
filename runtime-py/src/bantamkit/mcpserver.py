"""bantamkit as an MCP server: memory + validation over stdio, one instance per person."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import stat as stat_module
import sys
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from pathlib import Path
from typing import Annotated, Any, NoReturn, TextIO
from urllib.parse import unquote

import bantamkit
from bantamkit import (
    __version__,
    docmanifest,
    docread,
    hookadapter,
    hostinstall,
    repomap,
    selfupdate,
    shiftwork,
    skillaudit,
    tokenledger,
    updatecheck,
    workplan,
)
from bantamkit.assets import AssetNotFound, assets_root, load_skill, load_tool_asset
from bantamkit.client import BantamError
from bantamkit.contract import (
    bantamkit_read_unknown_part,
    document_error,
    document_offset_past_end,
    document_page,
    schema_error,
    schema_retry_feedback,
    tool_failed,
)
from bantamkit.eventlog import EventLog
from bantamkit.mcpreport import build_report as build_mcp_report
from bantamkit.mcpreport import resolve_event_log_path
from bantamkit.memory import DEFAULT_INDEX_BUDGET, INDEX_PRESSURE_PERCENT, Memory
from bantamkit.pricing import PriceTableError
from bantamkit.statusline import status_line

try:
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ResourceError
    from mcp.server.mcpserver.tools import Tool as SDKTool
    from mcp.server.mcpserver.utilities.func_metadata import FuncMetadata
    from pydantic import Field
except ImportError:  # surfaced as a clear SystemExit in main()
    MCPServer = None  # type: ignore[assignment]
    Field = None  # type: ignore[assignment]
    FuncMetadata = object  # type: ignore[assignment,misc]
    ResourceError = None  # type: ignore[assignment]
    SDKTool = None  # type: ignore[assignment]

_INSTALL_HINT = 'bantamkit-mcp needs the MCP extra: pip install "bantamkit[mcp]"'

SERVER_NAME = "bantamkit"


def _version() -> str:
    """The version this checkout declares — never the one the last install recorded.

    RB-P45: `metadata.version("bantamkit")` reads the installed dist-info, and a *stale*
    editable install is not a `PackageNotFoundError`, so the old body could not fall back
    — it returned a confidently wrong number. `__version__` is the same bytes hatchling
    builds the wheel from, is already imported by the time this module exists, and has no
    failure mode to fall back from.
    """
    return __version__


class _Undetermined(Exception):
    """A build fact that could not be derived, carrying WHY. Never becomes a value."""


def _unavailable(reason: str) -> dict[str, str]:
    """The shape an underivable fact takes on the wire.

    `RB-P51`'s rule is that "could not determine" must never read as a value. A sentinel
    string (`""`, `"unknown"`, `"none"`) is the defect that rule names: it sits in a
    field typed as a path or a digest and a caller comparing fields reads it as one. An
    object cannot — every derivable field here is a string, an int or a bool, so a caller
    that got a dict knows it got no answer, and the key it must read is the reason.

    What this does NOT buy, said plainly: two servers that both failed to derive the same
    fact carry the same object and compare equal on it. Unavailability is visible, not
    discriminating. That is why `build_id` refuses to exist at all when one of its inputs
    is unavailable, instead of hashing the failure text into something that looks like an
    identity and agrees with every other failure.
    """
    return {"unavailable": reason}


def _tree_digest(root: Path, files: list[Path]) -> str:
    """sha256 over (relative path, size, bytes) of every file, in sorted path order.

    Paths are folded in so that moving a file is a different build, and sizes so that a
    concatenation cannot be re-partitioned into the same stream. The digest is over the
    CONTENT and its layout under `root` — never over `root` itself — which is the whole
    reason two installs of one build at two different paths fingerprint identically while
    one edited line anywhere does not.
    """
    running = hashlib.sha256()
    for path in files:
        payload = path.read_bytes()
        running.update(path.relative_to(root).as_posix().encode("utf-8"))
        running.update(b"\0%d\0" % len(payload))
        running.update(payload)
    return "sha256:" + running.hexdigest()


def _code_fingerprint() -> tuple[str, int, Path]:
    """Fingerprint the source the interpreter imported this package from.

    `bantamkit.__file__` is the same resolution the import system already performed, so
    this reads the tree that is actually serving the call — not a checkout that happens
    to be nearby, which is exactly the confusion `RB-P55` names inside a worktree.

    TWO EXCLUSIONS, AND THE SECOND WAS MEASURED RATHER THAN REASONED. `__pycache__`
    because bytecode is derived, and a build must not fingerprint differently before and
    after its first import. `<package>/assets/` because THE ASSET PACK LIVES INSIDE THE
    PACKAGE IN A WHEEL and beside the repository root in a checkout (`RB-P85`,
    `docs/install.md`, `assets_root()`), while carrying eleven `.py` files of its own
    (`assets/evals/devteam/repo/`): a walk that swept them in counted 22 files from an
    editable checkout and 33 from a wheel-shaped install OF IDENTICAL CONTENT, and
    reported the two as different builds. That is the false positive this whole surface
    exists to avoid — a machine's user-scope wheel and project-scope editable install of
    one commit are ONE build. The pack is fingerprinted in full by `_assets_fingerprint`,
    so nothing goes unmeasured; it is measured once, under the field that names it.
    """
    located = getattr(bantamkit, "__file__", None)
    if not located:
        raise _Undetermined("bantamkit has no __file__; the running code is not on disk")
    root = Path(located).resolve().parent
    packed_assets = root / "assets"
    files = sorted(
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and not p.is_relative_to(packed_assets)
    )
    if not files:
        # A digest over nothing is a constant, and two servers that both computed one
        # would agree — the vacuity this whole surface exists to prevent.
        raise _Undetermined(f"no .py source found under {root}")
    try:
        return _tree_digest(root, files), len(files), root
    except OSError as exc:
        raise _Undetermined(f"unreadable source under {root}: {exc}") from None


def _pack_files(root: Path) -> list[Path]:
    """The pack as SHIPPED: every file except the bytecode caches an interpreter left in it.

    ONE spelling of the rule, because there are TWO walks over this directory — the digest
    behind `build_identity` and the count `--assets-root` prints — and a rule spelled twice
    is a rule that gets fixed once. That is not hypothetical: the first version of this fix
    excluded `__pycache__` from the digest alone, and a `pip install` then had one process
    contradicting itself, `build_identity` answering 87 files while `--assets-root` printed
    98 for the pack it had just loaded.

    Bytecode is derived. `_code_fingerprint` has said so since it was written; this is the
    same sentence applied to the pack, which carries eleven `.py` fixture files of its own.

    The membership test is over the path RELATIVE to `root`, so a pack that happens to live
    somewhere under a directory named `__pycache__` is walked rather than emptied.
    """
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.relative_to(root).parts
    )


def _assets_fingerprint() -> tuple[str, int, Path]:
    """Fingerprint the asset pack this build would load.

    Every file, not just the ones some loader knows about: `assets_root()` is a directory
    the server reads at call time, and a pack carrying an extra or an edited file is a
    different pack whether or not today's code opens it. `contracts/default.yaml` is the
    reason — `RB-P84` measured it as the one asset that differed between two live builds
    while no resource template exposed it, so it was invisible on every probed surface.

    EXCEPT bytecode caches, and that exception is the whole point of this field. The pack
    ships `.py` fixture files, so `pip install` byte-compiles them into `__pycache__` on the
    way in and the digest of an INSTALLED pack stopped matching the digest of the identical
    npm pack — measured on the published 0.27.0 artifacts, `sha256:fa8372f6…` over 98 files
    against `sha256:d47dcf4b…` over 87, and deleting `__pycache__` from the wheel's pack
    reproduced the npm digest byte for byte. `cross_runtime` tells the caller to compare
    `assets_digest` across runtimes; without this rule that instruction returned a false
    "different" on every real install. It was worse than cross-runtime: the digest was not
    stable for ONE install either, because it changed the first time anything imported a
    fixture. The pack is what was SHIPPED, never what an interpreter later wrote beside it.

    The rule lives in `_pack_files`, which `--assets-root` shares, and is spelled the same
    way in `runtime-ts`.
    """
    try:
        root = assets_root()
    except AssetNotFound as exc:
        raise _Undetermined(f"assets_root() could not resolve a pack: {exc}") from None
    files = _pack_files(root)
    if not files:
        raise _Undetermined(f"asset pack at {root} contains no files")
    try:
        return _tree_digest(root, files), len(files), root
    except OSError as exc:
        raise _Undetermined(f"unreadable asset under {root}: {exc}") from None


# ---------------------------------------------------------------------------------------
# WHICH INSTALL SHAPE IS RUNNING — offline, from this server's own location.
#
# THE DEFECT, AND IT IS MEASURED (`docs/roadmap-agent-stack.md` AS-7). A Claude Desktop
# entry sat on 0.25.0 from 2026-08-24 through five releases with nothing in the config, the
# logs or any tool reply saying so — and its `package.json` declared the dependency as
# `file:/private/tmp/.../scratchpad/bantamkit-mcp-0.25.0.tgz`, a local tarball in a temp
# directory that no longer existed. An update run where that install lives is a no-op BY
# CONSTRUCTION, and nothing anywhere said which of those two things was wrong.
#
# WHY THIS IS A REFUSAL AND NOT A LOOKUP. The origin is written down by the installer, on
# this disk, in `direct_url.json` (PEP 610). Whether that path still exists is a `stat`.
# NO NETWORK IS TOUCHED ON ANY PATH BELOW — comparing the running version against a
# registry is AS-7(b), a separate unit, gated behind this one, and deliberately opt-in
# because an offline toolbox must not grow a network call in its health check.
#
# AMENDED 2026-09-11, J46-31: AS-7(b) HAS SHIPPED, as `--update`, and the first sentence
# above is still exactly true — that is the point of recording it here. The registry
# comparison lives in `selfupdate.py`, reached only from the flag, never from any path
# below and never from `bantamkit_status`. The clause that is now dated is "gated behind
# this one": the user reversed AS-7 on 2026-09-11 and the gate was overridden rather than
# met. "Deliberately opt-in" survived the reversal intact and is the reason `--update` is a
# CLI flag and not an MCP tool — see the ruling appended to AS-7.
#
# SHAPE IS LOCATION, NEVER IDENTITY. It is reported for the same reason `package_path` and
# `interpreter` are — it is what a person acts on — and it is kept OUT of `build_id` for
# the same reason they are: one build installed two ways is ONE build, and
# `test_build_identity.py` recomputes the hash from its four named inputs to prove it.
# ---------------------------------------------------------------------------------------

#: The closed vocabulary, spelled the same way in both runtimes, and it answers ONE
#: question: what would updating this install even mean?
#:
#:   registry     came from a package index (PyPI here, npm there). Reinstall by name.
#:   local-file   came from a path on THIS machine — an archive or a directory whose
#:                contents were copied in. The path is recorded and may be gone.
#:   linked       a directory on this machine is still the source being read: an editable
#:                install here, a `file:`/`npm link` symlink there. Update that tree.
#:   checkout     no installer recorded this tree at all; it is on the import path. Git.
#:   ephemeral    a temporary environment discarded after the run. Nothing to update.
#:
#: `ephemeral` IS IN THE VOCABULARY AND THIS RUNTIME NEVER ANSWERS IT, which is a deliberate
#: divergence carried in `docs/porting.md`: `npx` leaves a cache directory a Node server can
#: recognise, while a `pipx run` or `uvx` environment is not distinguishable from an
#: ordinary venv without pattern-matching cache directory names — a guess, and this surface
#: does not guess. The word is declared here anyway so that a consumer of either runtime
#: handles ONE set of five, rather than two sets it has to reconcile.
INSTALL_SHAPES = ("registry", "local-file", "linked", "checkout", "ephemeral")


@dataclass(frozen=True)
class Install:
    """Where the running code came from, and the origin path it can still be checked against.

    `source` is `None` for the two shapes that HAVE no origin path rather than for the ones
    whose path could not be read — `source_reason` carries which, in the operator's words,
    and `build_identity` turns it into the `{"unavailable": ...}` shape `RB-P51` requires.
    A shape that could not be derived at all is an `_Undetermined`, never a sixth word.
    """

    shape: str
    source: str | None = None
    source_reason: str = ""


def _normalized_project_name(name: str) -> str:
    """PEP 503 normalisation, hand-rolled: `Bantam_Kit.Extra` and `bantam-kit-extra` are one.

    Spelled out rather than imported because the only consumer is the comparison below and
    a regex here would be a second place `re` has to be right about a name pip already
    canonicalised on the way in.
    """
    out: list[str] = []
    for char in name.strip().lower():
        replacement = "-" if char in "-_." else char
        if replacement == "-" and out and out[-1] == "-":
            continue
        out.append(replacement)
    return "".join(out).strip("-")


def _file_url_path(url: str) -> Path | None:
    """A `file:` URL as a path on this machine, or `None` when it names neither.

    THE INVERSE OF `Path.as_uri()`, AND WINDOWS IS WHY IT IS WRITTEN OUT. `file:///C:/x`
    carries a leading slash before the drive letter that is not part of the path, and the
    encoder percent-escapes anything a URL cannot hold — a space in a person's own
    directory name being the case that actually turns up. `urllib.request.url2pathname`
    does this correctly and drags `http.client` and `socket` in behind it; this surface is
    offline by rule, so the ten lines are cheaper than the import.

    A `file://` URL with a real authority (`file://otherhost/share`) names a path on a
    machine that is not this one, so it is not a local origin and the caller is told so.
    """
    if not url.startswith("file://"):
        return None
    rest = url[len("file://") :]
    if rest.startswith("localhost/"):
        rest = rest[len("localhost") :]
    if not rest.startswith("/"):
        return None
    path = unquote(rest)
    if len(path) > 2 and path[1].isalpha() and path[2] == ":":
        path = path[1:]  # `/C:/x` is `C:/x`; POSIX paths never match this shape
    return Path(path)


def _dist_owns(dist: metadata.Distribution, running: Path) -> bool:
    """Did THIS distribution put the file that is running on disk?

    The question a dist-info's mere existence cannot answer. Two bantamkits under one name
    is the situation `RB-P84` filed, and a checkout earlier on `sys.path` shadows an
    installed wheel completely — so a `bantamkit-0.30.0.dist-info` in some site-packages is
    not evidence about the bytes that were imported. Matching on the resolved file is.
    """
    try:
        located = Path(str(dist.locate_file("bantamkit/__init__.py"))).resolve()
    except (OSError, ValueError):
        return False
    return located == running


def _direct_url_record(dist: metadata.Distribution) -> str | None:
    """`direct_url.json` as the installer wrote it, or `None` when there is none.

    THE ONE-LINE INDIRECTION IS DELIBERATE AND IT IS NOT A DODGE OF THE ENCODING GATE.
    `test_encoding_gate.py` flags every `.read_text(` that does not name an encoding, and
    it is right to: `Path.read_text` falls back to `locale.getencoding()`, which is UTF-8
    on this machine and cp1252 on a Windows runner — the defect that gate exists for.
    `importlib.metadata.Distribution.read_text` is a DIFFERENT function under the same
    name: it takes a metadata-file name, accepts no `encoding` at all (passing one is a
    `TypeError`), and decodes UTF-8 itself, which is what PEP 610 requires of this file.
    The gate matches on the attribute name alone and cannot see the difference, and its
    pragma is pinned at a single use by `test_the_pragma_is_used_exactly_once` — which
    belongs to the node that proves the gate bites and is not available to borrow. Binding
    the method first says what is being called instead of looking like the defect. The
    better fix is to teach the gate the signature; that is a change to the gate, which is
    not this unit's to make.
    """
    read_metadata_file = dist.read_text
    try:
        return read_metadata_file("direct_url.json")
    except OSError:
        return None


def _derive_install(
    package_file: Path, dists: Iterable[metadata.Distribution]
) -> Install:
    """The whole diagnosis, over a running file and a set of distributions. Pure and offline.

    Taken as ARGUMENTS rather than read from the process so that every shape can be built
    as a real `.dist-info` directory in a test and discovered through
    `metadata.distributions(path=[...])` — the same discovery the server runs. A mock here
    would assert this function's own reasoning back at it, and the entire question is what
    pip actually writes down.
    """
    running = package_file.resolve()
    for dist in dists:
        try:
            name = dist.metadata["Name"]
        except (KeyError, OSError):
            continue
        if not name or _normalized_project_name(str(name)) != "bantamkit":
            continue
        raw = _direct_url_record(dist)
        if raw is None:
            # PEP 610 writes that file for a direct URL or a local path and for nothing
            # else, so its ABSENCE beside a dist-info that owns the running files is
            # positive evidence of an index install — not a missing fact.
            if _dist_owns(dist, running):
                return Install(
                    "registry",
                    None,
                    "a registry install records no origin path on this machine: PEP 610 "
                    "writes `direct_url.json` only for a direct URL or a local path, and "
                    "this install has none. Reinstall by name to move it.",
                )
            continue
        try:
            direct = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(direct, dict):
            continue
        url = str(direct.get("url", ""))
        recorded = _file_url_path(url)
        editable = bool(dict(direct.get("dir_info") or {}).get("editable"))
        if editable:
            # The dist-info lives in site-packages while the code is read from the tree the
            # URL names, so ownership is containment, not equality.
            if recorded is not None and _is_within(running, recorded):
                return Install("linked", str(recorded))
            continue
        if not _dist_owns(dist, running):
            continue
        if recorded is None:
            raise _Undetermined(
                f"this install records its origin as {url or 'an empty URL'}, which is "
                "neither a package index nor a path on this machine, so its shape is not "
                f"one of {', '.join(INSTALL_SHAPES)}. A git or http origin is updated by "
                "reinstalling from that same URL."
            )
        return Install("local-file", str(recorded))
    return Install(
        "checkout",
        None,
        "no installer recorded this tree, so there is no origin path to check — the "
        "source IS `package_path`, and it is updated where it was cloned.",
    )


def _is_within(child: Path, parent: Path) -> bool:
    """`child` under `parent`, tolerating a `parent` that is a symlink or does not exist."""
    for candidate in (parent, parent.resolve()):
        try:
            if child.is_relative_to(candidate):
                return True
        except (OSError, ValueError):
            continue
    return False


def _running_package_file() -> Path:
    located = getattr(bantamkit, "__file__", None)
    if not located:
        raise _Undetermined("bantamkit has no __file__; the running code is not on disk")
    return Path(located)


@lru_cache(maxsize=1)
def _install_once() -> tuple[Install | None, _Undetermined | None]:
    """Derived ONCE, because the bytes that were imported cannot change under a process.

    `degraded_conditions` runs on every tool call and `docs/status.md` promises what that
    costs: one `stat`, one `is_dir`, one `scandir` per memory layer. Walking `sys.path` for
    distributions is none of those. So the SHAPE is memoised and only the EXISTENCE of the
    recorded path is re-read — which is the half that can actually change while a server
    is running, and the half the measured defect is about.

    The failure is memoised too. An exception is a derivation that has already been done
    and would be done identically a second time; `lru_cache` alone does not cache one.
    """
    try:
        return _derive_install(_running_package_file(), metadata.distributions()), None
    except _Undetermined as exc:
        return None, exc


def current_install() -> Install:
    """Which install shape is running. Importable, and NOT owned by the status path.

    Deliberately a module-level function taking no arguments and touching no server state:
    the `--update` flag planned as J46-29 has to be shape-aware — two of the five shapes
    have no registry route at all — and it must be able to ask this question from the CLI,
    before a memory store or a transport exists, without building an MCP server to do it.
    """
    install, exc = _install_once()
    if install is None:
        raise exc if exc is not None else _Undetermined("the install shape was not derived")
    return install


def build_identity() -> dict[str, Any]:
    """What this build can honestly say about itself, over the protocol.

    `RB-P84`: two `bantamkit` endpoints are registered under one name on a developer
    machine, both are spawned, and their advertised surfaces were byte-identical over
    6864 bytes. `tools/mcpdrift/mcpdrift.py` closes that from OUTSIDE — it tells a person
    two endpoints differ. This closes the other half: an agent holding a tool result can
    ask which build produced it, mid-call, without reading the server's filesystem.

    THE FIELD THAT IS THE ANSWER IS `build_id`, and it is deliberately computed from
    content alone — server name, declared version, code digest, asset digest. `version`
    is echoed but is not identity: it moves on release bumps, it has already lied in this
    program (`RB-P45`, a `v0.25.0` checkout advertising `0.3.0`), and refreshing a pinned
    install from HEAD leaves both endpoints reading one number while one keeps drifting
    forward. `package_path`, `assets_root` and `interpreter` are LOCATION, reported
    because they are what a person acts on, and kept out of `build_id` because two
    installs of one build at two paths are one build.

    WHAT IS REFUSED, and it is a refusal rather than a gap: no commit. See `git_commit`.

    WHAT THIS DOES NOT COVER, stated so the gap is visible rather than implied: the
    dependency tree. `mcp_sdk_version` is reported for the one SDK that shapes every
    answer on this wire, and nothing else is — two builds whose `pydantic` differs
    fingerprint identically here. `tools/mcpdrift/mcpdrift.py`'s `recall_bad_arg_type`
    probe is the surface that catches that, and it is a person's instrument, not this one.
    """
    identity: dict[str, Any] = {"server_name": SERVER_NAME, "version": _version()}

    try:
        digest, count, root = _code_fingerprint()
        identity["code_digest"] = digest
        identity["code_files"] = count
        identity["package_path"] = str(root)
    except _Undetermined as exc:
        for field_name in ("code_digest", "code_files", "package_path"):
            identity[field_name] = _unavailable(str(exc))

    try:
        digest, count, root = _assets_fingerprint()
        identity["assets_digest"] = digest
        identity["assets_files"] = count
        identity["assets_root"] = str(root)
    except _Undetermined as exc:
        for field_name in ("assets_digest", "assets_files", "assets_root"):
            identity[field_name] = _unavailable(str(exc))

    # Location, never identity: `BANTAMKIT_ASSETS` redirects the pack, so whether the
    # root was chosen by the operator or resolved by the package is a fact a caller
    # comparing two endpoints needs. A bool, so it is never confusable with a missing one.
    identity["assets_root_from_env"] = bool(os.environ.get("BANTAMKIT_ASSETS"))

    # Location too, and the same rule: which install SHAPE is running says what updating
    # this server would even mean, and says nothing about which build it is. A `file:`
    # install whose tarball was deleted answers `local-file` with a path that no longer
    # exists — the measured defect AS-7 filed — and `install_source_exists` is the bit
    # that says so. No network is consulted for any of the three.
    try:
        install = current_install()
        identity["install_shape"] = install.shape
        if install.source is None:
            identity["install_source"] = _unavailable(install.source_reason)
            identity["install_source_exists"] = _unavailable(
                f"a {install.shape} install records no origin path, so there is nothing "
                "here to check for."
            )
        else:
            identity["install_source"] = install.source
            try:
                identity["install_source_exists"] = Path(install.source).exists()
            except OSError as exc:
                identity["install_source_exists"] = _unavailable(
                    f"the recorded origin path could not be checked: {exc}"
                )
    except _Undetermined as exc:
        for field_name in ("install_shape", "install_source", "install_source_exists"):
            identity[field_name] = _unavailable(str(exc))

    identity["git_commit"] = _unavailable(
        "refused, not missing. An installed wheel carries no repository at all, and "
        "reading a checkout's HEAD would describe the TREE rather than the bytes that "
        "were imported — an edited working copy serves different code under an unchanged "
        "sha, which is precisely the confusion RB-P84 filed. A commit reported that way "
        "would be a value that is sometimes a lie; `code_digest` is derived from the "
        "bytes themselves and cannot be."
    )

    identity["interpreter"] = sys.executable or _unavailable(
        "sys.executable is empty; this interpreter cannot name its own binary"
    )
    identity["python_version"] = platform.python_version()
    identity["python_implementation"] = platform.python_implementation()
    try:
        # The SDK's OWN version, from the only source there is for a third-party dist.
        # This is NOT a rollback of RB-P45: bantamkit's version still comes from
        # `__version__` (see `_version`), this number is never used for it, and it is
        # kept OUT of `build_id` for the same reason RB-P45 gives — an editable install's
        # dist-info can be stale, so it is reported as environment, not as identity.
        identity["mcp_sdk_version"] = metadata.version("mcp")
    except metadata.PackageNotFoundError:
        identity["mcp_sdk_version"] = _unavailable(
            "no installed distribution metadata for `mcp`; the SDK is importable but "
            "not pip-recorded, so its version is not knowable here"
        )

    identity_inputs = ("server_name", "version", "code_digest", "assets_digest")
    inputs = {key: identity[key] for key in identity_inputs}
    missing = sorted(key for key, value in inputs.items() if isinstance(value, dict))
    if missing:
        identity["build_id"] = _unavailable(
            "computed from server_name, version, code_digest and assets_digest; could "
            f"not derive {', '.join(missing)}. A build_id short of an input would agree "
            "with every other build that lost the same input, so none is reported."
        )
    else:
        canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
        identity["build_id"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    identity["unavailable"] = sorted(
        key
        for key, value in identity.items()
        if isinstance(value, dict) and "unavailable" in value
    )
    return identity


# ---------------------------------------------------------------------------------------
# `bantamkit_status`, the degraded footer, and the conditions both are built from.
#
# WHY A TOOL RESULT AND NOT A NOTIFICATION, MEASURED BEFORE ANY OF THIS WAS WRITTEN.
# The request this answers is "let me SEE that the server is alive", and the obvious
# implementation — push a line at the host — does not exist. Claude Code's own binary
# carries the sentence `modern protocol revision with no unsolicited notification path`,
# and its proprietary `claude/channel` capability is gated six ways, one of which is
# `provider !== "firstParty"` — which rules out Copilot on its own. bantamkit's host log
# says the same thing from the running side: `"protocolEra":"modern"` in every
# `Connection established` record and ten `Channel notifications skipped: server did not
# declare claude/channel capability`. So the only surface every host is guaranteed to
# render is a TOOL RESULT, and that is what all three pieces here are.
#
# THE THREE PIECES AND WHO EACH ONE IS FOR:
#   * `bantamkit_status` — a tool. The MODEL can call it, so an agent mid-conversation can
#     answer "is this thing working" without the operator leaving the transcript.
#   * a same-named PROMPT — `prompts/list` was empty on both runtimes. A prompt is what a
#     PERSON invokes. The operator asking whether their server is alive is the person.
#   * the FOOTER — one line appended to the OTHER tools' results, and only when something
#     is wrong. Never on a healthy call: a footer on every result is noise, noise trains
#     the reader to stop reading, and the one time it matters it is then invisible.
#
# `docs/status.md` is the contract. Both runtimes emit these bytes.
# ---------------------------------------------------------------------------------------

#: The tool AND the prompt answer to this one name. Deliberately the same word: the
#: operator who read `bantamkit_status` in a footer must find it in their prompt menu
#: without translating, and a model that read it in a prompt must find the tool.
STATUS_NAME = "bantamkit_status"

#: What the prompt says after the report. The report is the payload; this is the one line
#: that tells the model what the person wanted with it, and it asks for a RELAY rather
#: than an interpretation — the operator invoked this to read the server's own words.
STATUS_PROMPT_TAIL = (
    "Show me that report as it stands. If it says Degraded, tell me which of the problems "
    "above you would deal with first and why; if it says Active, say so in one line and "
    "stop."
)

#: The prompt and resource-template counts `status_report` prints, named here because the
#: SDK offers no public count of either and reaching into its managers is exactly the
#: private-attribute habit `_from_manifest` exists to have ended. They are PINNED AGAINST
#: THE WIRE by `test_status_surface.py`, which drives a real `prompts/list` and
#: `resources/templates/list` and fails if a registration is added or removed without
#: moving these — so they are a declaration, not a guess.
SERVED_PROMPTS = 1
SERVED_RESOURCE_TEMPLATES = 2

#: `INDEX_PRESSURE_PERCENT` is re-exported here, where it used to be DEFINED, so that
#: `from bantamkit.mcpserver import INDEX_PRESSURE_PERCENT` keeps working. It moved down to
#: `memory/store.py` in job46 (J46-4): `MemoryStore.compact` is the remedy the sentence
#: below names, and it cannot clear a warning whose line it cannot see. The comment that
#: says why the number is 90 moved with it.


@dataclass(frozen=True)
class Condition:
    """One thing that is wrong, carried in the two forms the two surfaces need.

    `key` is an ASCII token from a closed set, which is the ONLY form that may reach the
    event log (`docs/eventlog.md`'s metadata-only rule); nothing here writes one today,
    and the field exists so that a future record cannot be tempted to log the prose.
    `sentence` is what a person reads. It never carries a tool argument, a memory body, a
    validated output, or a grant NAME — a layer's KIND is reportable, its name is not.
    """

    key: str
    sentence: str


def _plural(count: int, word: str) -> str:
    """`1 prompt` / `2 prompts`. Spelled once so the two runtimes cannot disagree twice."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _index_bytes(memory: Memory) -> int | None:
    """The size of the writable store's `index.md` on disk, or `None` if it has none.

    THE STAT, NOT THE PARSE, and the difference is the reason this can run on every tool
    call. `Memory.index_accounting()` re-derives the index by reading every fact file —
    the docstring there says so, and the event log only calls it when a log is actually
    enabled. A footer that has to decide on EVERY call cannot pay that, so this reads the
    rendered artefact the store itself keeps up to date (`MemoryStore._rebuild_index`
    writes it on every save) with one `stat`.

    What that trade costs, said plainly: a store whose facts were edited on disk behind
    the server's back has a stale `index.md`, and this reports the stale size. The
    condition is a WARNING that the budget is nearly spent, not the budget check itself —
    `MemoryStore._check_index_budget` is still the thing that refuses a save, and it still
    measures the parse. The two cannot disagree about a store only bantamkit has written.

    ABSENT IS 0 AND UNREADABLE IS `None`, and the two are split on the errno rather than
    collapsed. A store that has never been saved to has no `index.md` and really does
    spend nothing of its budget; a store whose directory refuses a `stat` has an unknown
    index, and reporting that as 0 would claim infinite headroom at exactly the moment
    there may be none — the same slander `Memory.index_accounting` refuses to commit.
    """
    try:
        return (memory.store.root / "index.md").stat().st_size
    except FileNotFoundError:
        return 0
    except OSError:
        return None


def _asset_pack_condition() -> Condition | None:
    """Is the pack this build loads still there?

    `build_server` raises `AssetNotFound` at startup for a tool without a manifest, so a
    server that is RUNNING resolved its pack once. It can still lose it afterwards — an
    upgrade that replaces the directory, a `BANTAMKIT_ASSETS` pointed at a scratch tree
    that gets cleaned up — and the failure is quiet: the tool descriptions were read at
    startup and keep being served, while `resources/read` and every later `load_skill`
    have nothing behind them.

    Deliberately no path in the sentence. `assets_root()` resolves to DIFFERENT paths in
    the two runtimes by construction (`_print_assets_root` says why at length), so a path
    here would make the one line of this surface that cannot be compared across them, to
    buy what `--assets-root` prints on demand.
    """
    try:
        root = assets_root()
    except AssetNotFound:
        return Condition(
            "asset-pack-missing",
            "the asset pack cannot be resolved at all, so skills, rubrics and tool "
            "descriptions have nothing behind them — reinstall the package, or point "
            "BANTAMKIT_ASSETS at a real pack and restart the server.",
        )
    if not root.is_dir():
        return Condition(
            "asset-pack-missing",
            "the asset pack is gone from where this server resolved it, so skills, "
            "rubrics and tool descriptions can no longer be re-read — run "
            "`bantamkit-mcp --assets-root` to see where it is looking, then restart.",
        )
    return None


def _unreadable_layer_condition(memory: Memory) -> Condition | None:
    """A memory layer that could not be LISTED — which is not a layer that held nothing.

    This is the sharpest of the four, because it is the one whose damage is a wrong ANSWER
    rather than a missing one: `Memory._nothing_to_report` already refuses to say "nothing
    is saved" when a layer is unreadable, but that sentence only reaches a person who
    happened to run an empty recall. The footer says it on every call.

    KIND, NEVER NAME. A layer's label is `project`, `extra:<grant name>` or `profile`, and
    the grant name is the operator's own words for somebody's directory. The kind is the
    part that is reportable; the split is here rather than at the call site so there is
    exactly one place it can be got wrong.

    It reads `Memory._layers` and `Memory._fact_count` through their private names on
    purpose. A public accessor would be the right shape and would be a change to the
    MEMORY layer, which this unit is not authorised to make (job39 invariant 4). Nothing
    is re-implemented: `_fact_count` is the same counter `_unreadable_layers` uses, so
    "unreadable" means here exactly what it means to recall.
    """
    unreadable = [
        label
        for label, store, _writable in memory._layers
        if memory._fact_count(store.root) is None
    ]
    if not unreadable:
        return None
    kinds = sorted({label.split(":", 1)[0] for label in unreadable})
    return Condition(
        "memory-layer-unreadable",
        f"{_plural(len(unreadable), 'memory layer')} could not be read "
        f"({_plural(len(kinds), 'kind')}: {', '.join(kinds)}), so an empty recall is not "
        "evidence that nothing is saved — check that those store directories exist and "
        "are readable.",
    )


def _index_pressure_condition(memory: Memory) -> Condition | None:
    """The index is nearly as big as the budget that has to hold it."""
    size = _index_bytes(memory)
    budget = memory.store.index_budget
    if size is None or size * 100 < INDEX_PRESSURE_PERCENT * budget:
        return None
    return Condition(
        "index-budget-low",
        f"the memory index is {size} bytes of a {budget}-byte budget, so the next save "
        "is close to being refused — archive or shorten facts with "
        "`python -m bantamkit.memory compact`.",
    )


def _event_log_condition(log: EventLog) -> Condition | None:
    """The log was asked for and a record has already been lost.

    Only reachable when the operator turned it on: `write_failed` is set inside `record`'s
    `except OSError` and a disabled log returns before any I/O. So this never fires for
    the default configuration, which is off.
    """
    if not (log.enabled and log.write_failed):
        return None
    return Condition(
        "event-log-unwritable",
        "the event log is switched on but a write to it has already failed, so tool "
        "outcomes are going unrecorded — check the path in BANTAMKIT_EVENT_LOG and "
        "whether its directory is writable.",
    )


def _install_source_condition(install: Install | None) -> Condition | None:
    """This install came from a path on this machine, and that path is gone.

    THE ONE CONDITION THAT NAMES A PATH, and the exception is deliberate. Every other
    sentence here refuses one because `assets_root()` resolves differently in the two
    runtimes by construction, so a path would be an uncomparable value bought for nothing.
    This path is not the server's own location — it is the origin THE INSTALLER WROTE DOWN,
    it is the entire actionable content of the finding (AS-7's measured case is a tarball
    under a `/private/tmp/.../scratchpad` that no longer exists), and a sentence saying
    "something is missing" without saying what would be a sentence nobody can act on.

    THE REMEDY IS THE ONE THAT ACTUALLY MOVES SOMETHING. J46-4 spent a unit removing a
    condition whose remedy exited 0 having changed nothing, and this is exactly the shape
    that invites another: an update run where a dangling `file:` install lives is a no-op
    BY CONSTRUCTION. So the sentence sends the reader at a reinstall BY NAME from a
    registry, which replaces the install rather than trying to refresh it in place.

    THE DERIVED HALF IS MEMOISED AND THIS HALF IS NOT: the shape cannot change under a
    running process, the path's existence can, and it is the one that has to be read now.
    """
    if install is None or install.source is None:
        return None
    try:
        if Path(install.source).exists():
            return None
    except OSError:
        return None
    return Condition(
        "install-source-missing",
        f"this server was installed from {install.source}, which no longer exists, so "
        "nothing can be refreshed in place there — reinstall bantamkit by name from a "
        "package registry and restart the server.",
    )


def _current_install_or_none() -> Install | None:
    """The shape, or nothing. A shape that could not be derived is a REPORTED gap.

    `build_identity` is where that gap is named, with its reason. It is not a degraded
    condition: an install this code cannot classify is not, on that evidence, an install
    that is broken, and a footer on every tool call saying otherwise would be the noise
    `degraded_notice` exists to avoid.
    """
    try:
        return current_install()
    except _Undetermined:
        return None


def degraded_conditions(memory: Memory, log: EventLog) -> list[Condition]:
    """Everything wrong right now, worst first. Empty list means healthy.

    ORDER IS SEVERITY AND IT IS LOAD-BEARING, because the footer shows the first one: a
    pack that vanished breaks every asset-backed surface; an unreadable layer makes recall
    ANSWER WRONGLY rather than fail; a full index refuses the next save; a broken event log
    costs diagnostics only; and a dangling install origin costs nothing AT ALL right now —
    the server is serving correctly, and what is broken is the next attempt to update it.
    That is why it is last despite being the one that went unnoticed for five releases
    (`docs/roadmap-agent-stack.md` AS-7): severity here is what is failing, not what has
    been failing longest.

    EVERY CONDITION IS OBSERVED, NOT INFERRED — no heartbeat, no timer, no last-seen
    timestamp. Each one is a state a test can construct and then watch this report: delete
    the pack, make a layer's `facts/` a file, build a store whose index already exceeds
    nine tenths of its budget, point the log at an unwritable path. A condition that
    cannot be constructed is not claimed.

    THE COST, because this runs on every tool call: one `stat` for the index, one `is_dir`
    for the pack, one `scandir` per memory layer (two to four), a field read for the log,
    and one `exists` for the install origin. No fact file is opened, no index is parsed,
    and `sys.path` is NOT walked for distributions — `_install_once` does that once per
    process, because the bytes that were imported cannot change under a running one.
    """
    found = (
        _asset_pack_condition(),
        _unreadable_layer_condition(memory),
        _index_pressure_condition(memory),
        _event_log_condition(log),
        _install_source_condition(_current_install_or_none()),
    )
    return [condition for condition in found if condition is not None]


def degraded_notice(conditions: list[Condition]) -> str:
    """The one line other tools' results carry when something is wrong. `""` when nothing is.

    THE EMPTY STRING FOR A HEALTHY SERVER IS THE WHOLE POINT, and it is checked in a pair:
    `test_status_surface.py` asserts the notice is present on a degraded call AND absent on
    a healthy one, because only the pair proves it is conditional. A footer on every result
    is noise, and noise trains a reader to skip it — at which point the one time it matters
    it is invisible. That is what the operator asked for in their own words
    ("ร่วม footer เฉพาะตอนผิดปกติ ด้วย") and it is the property to protect.

    ONE SHAPE, ALWAYS, including for a single condition — a count of 1 reads fine, and a
    second shape is a second thing for the port to get right. The worst condition is spelt
    out because a bare count is not actionable; the rest are a number and a pointer,
    because this is a FOOTER on somebody else's answer and has no licence to become the
    answer.
    """
    if not conditions:
        return ""
    return (
        f"⚠️ bantamkit degraded ({len(conditions)}): {conditions[0].sentence} "
        "Call `bantamkit_status` for the full report."
    )


def status_report(
    memory: Memory,
    log: EventLog,
    conditions: list[Condition],
    tools: int,
    prompts: int,
    templates: int,
) -> str:
    """The whole answer `bantamkit_status` returns — prose, for a person, in a transcript.

    THE FIRST LINE IS THE ANSWER and it is the line the operator asked for by name:
    `bantamkit Active 🟢`, or `bantamkit Degraded 🟠` when `conditions` is non-empty. A
    reader who stops after eight characters has still learned the thing they came for.

    THE ONE FIELD THAT IS NOT COMPARABLE ACROSS RUNTIMES is `build`. It is `build_id`,
    which is a fingerprint of the running source, and the two runtimes fingerprint two
    different trees by construction — `docs/porting.md`'s divergence table already rules
    exactly this for `build_identity`. It is here anyway because "which bantamkit" is half
    the question this tool exists to answer: two endpoints registered under one name is
    the situation RB-P84 filed, and a version string cannot tell them apart.

    NO ARGUMENT VALUE CAN REACH THIS. It takes none, and every input above is server
    state; `test_status_surface.py` asserts the absence positively with a sentinel.
    """
    identity = build_identity()
    build = identity["build_id"]
    facts = memory._fact_count(memory.store.root)
    size = _index_bytes(memory)
    budget = memory.store.index_budget
    lines = [
        f"bantamkit {'Degraded 🟠' if conditions else 'Active 🟢'}",
        f"version {identity['version']}, build "
        + (build if isinstance(build, str) else "unavailable"),
        f"serving {_plural(tools, 'tool')}, {_plural(prompts, 'prompt')}, "
        f"{_plural(templates, 'resource template')}",
        "memory: "
        + (
            "the project store could not be read"
            if facts is None
            else f"{_plural(facts, 'fact')} in the project store"
        )
        + ", index "
        + ("unreadable" if size is None else str(size))
        + f" of {budget} bytes",
        f"event log: {'on' if log.enabled else 'off'}",
        # THE UPDATE LINE IS NOT A CONDITION, and that is the ruling of 2026-09-19 rather
        # than an omission. A newer version existing is not a fault: the server is serving
        # correctly, and `degraded_notice`'s docstring above is the operator's own reason —
        # a footer on every result is noise, and noise trains a reader to skip it. So this
        # never flips line 1, never enters `degraded_conditions`, and never rides another
        # tool's reply. It also means the record is opened ONLY here, when someone asked for
        # a report, and not on the per-call path whose cost `docs/status.md` documents.
        #
        # `updatecheck` opens one file and asks nobody anything — AS-7(3) is intact, and
        # `test_selfupdate.py::test_only_the_update_flag_reaches_this_module_from_the_server`
        # still holds, because the name this reaches is `updatecheck` and not `selfupdate`.
        updatecheck.update_line(str(identity["version"])),
    ]
    if conditions:
        lines.append(f"{_plural(len(conditions), 'problem')}:")
        lines.extend(f"- {condition.sentence}" for condition in conditions)
    return "\n".join(lines)


class _ArgMetadata(FuncMetadata):  # type: ignore[misc,valid-type]
    """The SDK's argument metadata, with the JSON pre-parse switched off where Node has none.

    Before validating, `FuncMetadata.pre_parse_json` runs `json.loads` over every string
    argument whose annotation is not exactly `str` (so `str | None` and `int | None`
    qualify) to unwrap a JSON-encoded list or object some hosts send. The Node SDK does no
    such thing, and `bantamkit_read` is the one tool on this surface whose arguments are
    not plain `str`, so it was the one tool whose two halves could read the same call
    differently. Measured on the wire (job43 F2, then review round 2): a 4301-digit `part`
    reached the model as `isError: Exceeds the limit (4300 digits) for integer string
    conversion` — `json.loads` hit CPython's integer-string cap before the handler ran;
    `part="null"` was unwrapped to `None` and served the MANIFEST where Node refuses an
    unknown part named `null`; `part="[1]"` became a list and a pydantic `string_type`
    error where Node says `no part named [1]`; `offset="null"` paged from row 0 where
    Node's `pyargs` refuses it as `int_parsing`.

    THE PROPERTY: for `bantamkit_read`, no argument is JSON-unwrapped — a string is the
    string that was sent. Pydantic's own lax coercion stays (`offset="5"` → 5), because
    Node's `pyargs` does the same. `unwrap_json` is `False` for that tool alone: the other
    nine take plain `str` (plus `list`/`dict` fields the SDK unwraps by design, e.g.
    `memory_save.links`), and for them the per-key loop below is the one change: a
    `ValueError` the SDK's own loop would have let escape — `json.loads` on a 4301-digit
    integer string hits CPython's digit cap — now leaves that key as the string it was, so
    `memory_save(links="[" + "1"*4301 + "]")` is pydantic's `list_type` validation frame
    instead of an `isError` carrying `Exceeds the limit (4300 digits)` (measured, review
    round 3). That is the frame Node already printed, so it is a parity gain, not a
    behaviour the nine keep.
    """

    unwrap_json: bool = True

    def pre_parse_json(self, data: dict[str, Any]) -> dict[str, Any]:
        if not self.unwrap_json:
            return data
        out = data.copy()
        for key, value in data.items():
            try:
                out[key] = super().pre_parse_json({key: value})[key]
            except ValueError:
                out[key] = value
        return out


# Tools whose arguments reach the handler exactly as sent — see `_ArgMetadata`.
# DORMANT — `bantamkit_read` left the roster (job50 I5, 2026-09-12), so no served tool is
# in this set today and `unwrap_json` is `True` for all twelve. The entry stays so that
# restoring the roster line restores the property with it.
_NO_JSON_UNWRAP = frozenset({"bantamkit_read"})


# `assets/tools/bantamkit_read.json` `offset.maximum` — Number.MAX_SAFE_INTEGER, the largest
# integer a JSON parser on the Node side reads back unchanged.
#
# The asset is the published contract and this is the number the SIGNATURE enforces, so the
# two are tied by a test that reads the asset off disk rather than by a fourth copy of the
# literal: `tests/test_document_manifest_parity.py` compares this constant, the served schema
# and the handler's own refusal against `assets/tools/bantamkit_read.json`. The same test ties
# `docread.PAGE_MAX_ROWS` (the row clamp below), `docread.DEFAULT_ROW_LIMIT` and
# `docread.PAGE_MAX_BYTES` to the same file, including the sentence in the `limit` description
# that prints two of them. Register entries (c) and (l), `docs/roadmap-toolbox.md` row 8. It is
# a test rather than a runtime read because `_from_manifest` already loads the asset at
# `build_server` time and a MODULE-level load would make importing this module fail wherever
# the asset pack is not on disk — the failure mode a packaging mistake would then have is "the
# server will not import" rather than "the server refuses to register a tool".
OFFSET_MAXIMUM = 9007199254740991


@dataclass
class _DocumentCache:
    """The last `docread.extract` result this server produced, and what it was OF.

    DORMANT — its one user, `bantamkit_read`, left the roster (job50 I5, 2026-09-12); kept
    with the handler so the roster line can come back without re-deriving the cache.

    Register entry (i): `bantamkit_read` re-parsed the whole document on EVERY call, so a
    caller paging a 12,001-row sheet in 200-row pages parsed the workbook once per page —
    paging was O(N^2) in the row window. Measured on this machine over a 1,538,280-byte
    12,001-row xlsx: 64 tool calls, **64** parses, 3.075 s for the walk.

    ONE entry, deliberately. A single entry evicts whenever two callers alternate between two
    documents, and that case then costs exactly one parse per call — which is what the code
    this replaced cost for EVERY case, so the cache cannot make any caller slower than it was
    (`tests/test_document_manifest_parity.py` measures the alternating walk and pins the
    count). What more entries would cost is resident memory: a `Document` holds its whole
    rendering as Python strings, bounded per document by `docread.TEXT_MAX_BYTES` and
    `docread.XLSX_MAX_TEXT_BYTES` (16 MiB each, U1), and every extra entry multiplies that
    ceiling by one. Bounding the server's resident set is worth more than the alternating
    case, which is not made worse.

    **The key is (realpath, size, mtime_ns), and it has one hole — stated, not implied.** A
    rewrite that lands inside a single filesystem timestamp tick AND leaves the byte count
    unchanged is indistinguishable from no rewrite at all, and would be served from the stale
    parse. `mtime_ns` is nanosecond-SHAPED and not nanosecond-GRAINED: what it reports is
    whatever the filesystem stored, which on HFS+ is one second and on APFS/ext4 is finer but
    not unbounded. The alternative — hashing the bytes — would re-read the file this cache
    exists to avoid re-reading, which is the whole cost on the large documents that motivate
    it. So the hole stays, and the test that proves the key works changes the SIZE rather than
    racing the clock, because a test that raced it would be measuring the filesystem.

    `realpath` and not the path as given: two callers reaching one file by different relative
    paths, or through a symlink, are reading the same bytes and should share the parse.
    """

    key: tuple[str, int, int] | None = None
    doc: Any = None

    def get(self, key: tuple[str, int, int] | None) -> Any:
        """The cached document for `key`, or `None` — a `None` key never matches."""
        if key is None or key != self.key:
            return None
        return self.doc

    def put(self, key: tuple[str, int, int] | None, doc: Any) -> None:
        if key is None:
            return
        self.key, self.doc = key, doc


def _document_key(path: str) -> tuple[str, int, int] | None:
    """What identifies the bytes at `path` — or `None`, which means "do not cache".

    `stat` FOLLOWS symlinks, which is the same file the reader is about to open.

    **A PATH THIS FUNCTION CANNOT KEY MUST NOT CHANGE WHAT THE CALLER READS.** Keying is an
    optimisation and nothing else: it runs BEFORE `docread.extract`, so anything it raises
    pre-empts the reader and speaks in the wrong voice — a syscall's words instead of the
    reader's. Everything it cannot key is simply not cached, and `extract` then refuses in its
    own sentence exactly as it did before this cache existed.

    That promise was false for one class of path when the cache first landed, and the two
    runtimes disagreed because of it (found by U3 on `wire/read-round2: id 6`): `os.stat`
    raises `ValueError: stat: embedded null character in path` for `"a\\x00b"`, NOT `OSError`,
    so the `ValueError` escaped and the SDK turned it into `isError: true` where `runtime-ts`
    answered `error: no such file: ...` with `isError: false`.

    **The set is `(OSError, ValueError)`, and it is a predicate rather than a patch.** Those
    are the two ways a path fails to reach the filesystem, and between them they name all of
    it: `OSError` is *the OS was asked and refused* (ENOENT, EACCES, ELOOP, ENAMETOOLONG), and
    `ValueError` is *the string cannot be handed to the OS at all* — the embedded null, and
    `UnicodeEncodeError` (a `ValueError` subclass) for a path the filesystem encoding rejects.

    It is deliberately NOT the bare `except Exception` that `runtime-ts`'s `documentKey` gets
    from a bare `catch {}`. Widening to match it would buy no parity — for every path either
    side can fail on, both return "do not cache" and both then let the reader speak, which is
    the only thing observable — and it would cost the thing a cache most needs: a real bug in
    the keying would degrade to "never cache anything" and stay silent forever, which looks
    exactly like a cache that is working. A defect in here should still be loud.

    Both calls are inside the guard, not just the `stat`. `os.path.realpath` raises the same
    `ValueError` on the same input (measured: `lstat: embedded null character in path`), so a
    guard around the `stat` alone would only be correct for as long as `stat` happens to be
    the call that fails first.
    """
    try:
        stat = os.stat(path)
        return (os.path.realpath(path), stat.st_size, stat.st_mtime_ns)
    except (OSError, ValueError):
        return None


def _from_manifest(fn: Callable[..., Any], name: str) -> Any:
    """Bind one handler to its manifest entry — description, BOTH schemas, and the surface.

    The asset pack under `assets/tools/` is the tool contract for every runtime that
    serves this surface, so the schema has to arrive WITH the registration rather than be
    corrected onto it afterwards. Until this function existed, `build_server` registered
    each handler by decorator (description from a Python constant, schema derived from the
    signature) and then reached through a private attribute of the SDK's tool manager to
    overwrite two of the schemas after the fact. The served bytes were right, but only for
    as long as that attribute stayed reachable under that name: an SDK that renamed it
    would have gone back to advertising whatever the Python signature says, silently, and
    a port to a second runtime would have had to re-read Python to learn the contract.

    `MCPServer(..., tools=[...])` is the public seam. The object handed to the constructor
    already carries the manifest's description and schema, so registration and truth are
    one step. `from_function` still derives `fn_metadata` from the signature, and that is
    what validates arguments at CALL time; the signatures mirror the manifest. Only what
    is ADVERTISED changes hands here, and it now has exactly one source.

    `output_schema` goes through the same seam by a different route. It is not a field on
    the SDK's `Tool`; it is a `cached_property` returning `fn_metadata.output_schema`, and
    `MCPServer.list_tools` copies it straight onto the wire's `outputSchema`. Putting the
    manifest's value in the instance dict is what a `cached_property` reads first, so the
    override lands — and it lands on the ADVERTISEMENT ONLY, because the call path
    (`FuncMetadata.convert_result`) consults `fn_metadata`, which is untouched. That is
    the same division `parameters` already has: the manifest says what is promised, the
    signature still says what is enforced.

    The `surfaces` check is what makes that field load-bearing. `assets/tools/` serves the
    eval agent too, and a manifest entry that does not claim `mcp` must not become a tool
    on this server — otherwise the field is a comment, and a port that trusts it would
    serve a different set of tools than this runtime does.
    """
    asset = load_tool_asset(name)
    if "mcp" not in asset["surfaces"]:
        raise BantamError(
            f"tool asset {name!r} does not claim the mcp surface: {asset['surfaces']}"
        )
    tool = SDKTool.from_function(fn, name=asset["name"], description=asset["description"])
    return tool.model_copy(
        update={
            "parameters": asset["parameters"],
            "output_schema": asset["output_schema"],
            "fn_metadata": _ArgMetadata(
                **dict(tool.fn_metadata), unwrap_json=name not in _NO_JSON_UNWRAP
            ),
        }
    )


@contextmanager
def _record_raise(log: EventLog, tool: str) -> Iterator[None]:
    """Record the TYPE of anything that escapes, then let it escape unchanged.

    The host already logs that a tool failed and how long it took; what it cannot say is
    which exception the component threw — and the one place it tried, it leaked an
    argument value doing it (`eventlog.py`'s docstring, measured). So: `type(exc).__name__`
    and nothing else, via `EventLog.raised`, which has no other input available to it.

    `BaseException` rather than `Exception` deliberately. A `KeyboardInterrupt` or a
    `SystemExit` out of a handler is exactly the shape whose cause is hardest to
    reconstruct afterwards, the record costs one line, and the `raise` is unconditional
    — nothing here decides whether the tool fails, only whether the failure was written
    down. `EventLog.record` swallows its own `OSError`, so this cannot mask the original.
    """
    try:
        yield
    except BaseException as exc:
        log.raised(tool, exc)
        raise


def _record_result(log: EventLog, tool: str, call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run a shiftwork handler and record its `result` — the register's OWN verdict.

    Every `shiftwork` entry point answers a dict whose `result` key is the decision it
    made: `brief`, `escalate`, `success`, `ok`, `status`, `error`. `clock_in` returning
    `escalate` is the sharp case — the register's whole stop-and-ask contract, invisible
    in the host's log because the tool call succeeded. Reading the key is reading the
    decision; nothing here inspects a `reason` string, which is prose and can carry a
    checkpoint path.

    `raised` is the outcome for an ESCAPING EXCEPTION and is spelled differently from
    `error` on purpose: `result: "error"` is a refusal the register composed and returned
    normally, and collapsing the two would lose the only distinction between a checkpoint
    that was rejected and a handler that fell over.
    """
    with _record_raise(log, tool):
        answer = call()
    log.record(tool, str(answer.get("result", "unknown")))
    return answer


#: The last paragraph of every `repo_map` reply, refusal excepted. FIXED AND MANDATORY.
#:
#: DORMANT — `repo_map` left the roster (job50 I5, 2026-09-12). The tail, the empty-listing
#: sentence and `repo_map_reply` below stay with the handler: a roster decision, not a
#: deletion of working code.
#:
#: Roadmap row 10's build gate was "build only after #4 shows discovery tokens dominate",
#: and #4 REFUTED it: discovery is 0.114 % of real prompt tokens because 97.8 % of the
#: bill is `cache_read`. The feature ships on an explicit ruling to build it anyway, as a
#: PRECISION feature. A surface that let a caller believe the map is a token saving would
#: say the one thing the measurement forbids, so the refutation travels with every answer
#: rather than living only in a doc nobody reads at call time.
#:
#: The second sentence is the budget's unit, for the same reason: `DEFAULT_BUDGET = 4000`
#: is "1 K tokens" only at the char/4 convention, whose error bar is unmeasured because
#: measuring it needs the tokenizer the pure-node ruling forbids. Bytes are what is
#: enforced, so bytes are what the reply says.
REPO_MAP_TAIL = (
    "This is a precision pass, not a token saving: this feature's build gate was REFUTED "
    "by measurement — discovery is 0.114% of real prompt tokens, because 97.8% of the "
    "bill is cache_read — so a map does not make a session cheaper. What it buys is the "
    "right file found sooner.\n"
    "The budget above is UTF-8 BYTES of listing, not tokens: neither runtime carries a "
    "model tokenizer and this tool will not pretend to one."
)

#: What a listing says when there is nothing to list. An empty string with two blank lines
#: around it is not an answer, and "0 files" is already on the header line — this names the
#: reason, which is the same discipline the omission footer is built on.
REPO_MAP_EMPTY = "(nothing listed: no file under this root scanned into a definition)"


def repo_map_reply(result: repomap.RepoMap) -> str:
    """The `repo_map` tool's prose, byte for byte, from the structured result.

    Split out of the handler so the two runtimes have ONE shape to reproduce rather than a
    format string embedded in a `case`, and so the `repomap` conformance suite can compare
    the rendered reply without standing up a server. No float is ever rendered here — see
    `repomap`'s trap (8); every number on the header line is an int.
    """
    focus = (
        ", ".join(result.focus)
        if result.focus
        else "(none) — plain centrality over the whole tree"
    )
    head = (
        f"repo map: {result.nodes} files scanned, {result.definitions} definitions, "
        f"{result.edges} edges.\n"
        f"focus: {focus}\n"
        f"budget: {result.budget} UTF-8 bytes; listing {result.listing_bytes} bytes; "
        f"rendered {result.files_rendered} files, "
        f"{result.definitions_rendered} definitions."
    )
    body = result.text if result.text else REPO_MAP_EMPTY
    return f"{head}\n\n{body}\n\n{REPO_MAP_TAIL}"


def build_server(memory: Memory, log: EventLog | None = None) -> Any:
    """Assemble the MCP server around one Memory instance (the per-person state).

    `log` is the event-log sink (`docs/eventlog.md`), resolved from `BANTAMKIT_EVENT_LOG`
    when the caller does not supply one and DISABLED unless that variable asks for it.
    It is a parameter and not only an environment read so that a test can inject a fixed
    clock and a scratch path without setting a process-wide variable — the same seam
    `runtime-ts` needs for its half of the conformance case.

    EVERY HANDLER BELOW RECORDS FROM A DECISION, NEVER FROM ITS REPLY. `memory_save`
    reads `SaveOutcome.status`, `memory_recall` reads `RecallOutcome.status`, the three
    shiftwork tools read the register's own `result` key, `validate_json` reads the
    `valid` bool it is about to return, and `build_identity` reads the length of the
    `unavailable` list it computed. Not one of them looks at the words. That is the
    property `test_eventlog.py::test_the_record_does_not_move_when_the_reply_wording_
    does` holds: change a reply's wording and the record must be byte-identical.

    THE DEGRADED FOOTER IS APPLIED AFTER THE RECORD, EVERY TIME. A footer is a rendering
    decision about somebody else's answer; the record is the decision the component made.
    Folding one into the other would put a filesystem observation into a line a
    conformance case byte-compares, and would make the log move when nothing the tool did
    moved. `_noted` and `_noted_dict` below therefore run last, on the way out.
    """
    if MCPServer is None:
        raise SystemExit(_INSTALL_HINT)
    if log is None:
        log = EventLog.from_env(memory.store.root)
    # Per SERVER, not per process: two servers in one interpreter (every test module here
    # builds several) must not answer each other's files, and the entry dies with the server
    # rather than outliving it in a module global.
    cache = _DocumentCache()

    def _notice() -> str:
        """The footer for right now — recomputed per call, never cached.

        A cache would be the one thing that could make this lie: a condition that cleared
        (or arrived) between two calls has to be visible on the next one, and the whole
        probe is a handful of `stat`s. It is also what keeps two servers over one store
        from disagreeing about the state of it.
        """
        return degraded_notice(degraded_conditions(memory, log))

    def _noted(reply: str) -> str:
        """A prose reply, plus the footer if there is one. Byte-identical when healthy."""
        notice = _notice()
        return f"{reply}\n\n{notice}" if notice else reply

    def _noted_dict(answer: dict[str, Any]) -> dict[str, Any]:
        """A structured reply, plus the footer if there is one, under one reserved key.

        A JSON result has no margin to write in: the rendered text of these tools IS the
        serialised object, so a sentence appended to it would stop being parseable. The
        footer therefore arrives as `bantamkit_degraded`, LAST in the key order and only
        when it exists — every one of these tools advertises
        `additionalProperties: true`, so a key that comes and goes is inside the contract
        it already declares. A healthy call is byte-identical to what it was before this
        surface existed, which is the same guarantee `_noted` gives for prose.
        """
        notice = _notice()
        return {**answer, "bantamkit_degraded": notice} if notice else answer

    def memory_save(
        type: str, name: str, description: str, body: str, links: list[str] | None = None
    ) -> str:
        with _record_raise(log, "memory_save"):
            outcome = memory.save_outcome(type, name, description, body, links)
        if log.enabled:
            # Only when a log is actually on: `index_accounting` re-parses `facts/`, and
            # a diagnostic must not put that on the path of an operator who did not ask
            # for one. Headroom is left to the reader rather than stored — it is
            # `budget - index_bytes`, and a derived field is a second thing to keep true.
            index_bytes, budget = memory.index_accounting()
            detail: dict[str, Any] = {"budget": budget}
            if index_bytes is not None:
                detail["index_bytes"] = index_bytes
            log.record("memory_save", outcome.status, detail)
        return _noted(outcome.reply)

    def memory_recall(query: str, k: int | None = None) -> str:
        if k is not None:
            k = max(1, min(k, 5))  # the advertised schema's bounds; clients may ignore it
        with _record_raise(log, "memory_recall"):
            outcome = memory.recall_outcome(query, k)
        detail = {
            "budget": outcome.budget,
            "candidates": outcome.candidates,
            "layers": outcome.layers,
            "reached": outcome.reached,
            "returned": outcome.returned,
            "unreadable": outcome.unreadable,
        }
        if outcome.source is not None:
            detail["source"] = outcome.source
        log.record("memory_recall", outcome.status, detail)
        return _noted(outcome.reply)

    def memory_compact(reserve: int | None = None) -> str:
        """The model's half of compaction; the hook (`docs/hooks.md`) is the automatic half.

        `memory_save`'s refused-budget reply names this tool, so it acts on exactly the
        store that refused: `Memory.compact_outcome` reaches `memory.store` — the
        writable project layer — and never a grant or the profile layer. The status is
        the store's own decision (`archived` when the archive list is non-empty,
        `nothing-archived` otherwise), never a match on the reply.
        """
        # No floor here: `MemoryStore.compact` clamps `reserve` to `[0, budget // 2]`
        # itself, so a negative value from a client that ignored the schema is already
        # handled where the arithmetic lives, and a second clamp would be a second thing
        # to keep equal across the two runtimes.
        with _record_raise(log, "memory_compact"):
            outcome = memory.compact_outcome(reserve)
        log.record(
            "memory_compact",
            outcome.status,
            {
                "archived": outcome.archived,
                "budget": outcome.budget,
                "index_after": outcome.index_after,
                "index_before": outcome.index_before,
            },
        )
        return _noted(outcome.reply)

    def memory_dream(dry_run: bool | None = None) -> str:
        """Consolidate what the project and the machine-wide profile layer both hold.

        `dry_run` DEFAULTS TO TRUE and the default lives HERE rather than in the
        component: a client that omits the argument gets `None` through pydantic's
        `bool | None = None`, and turning that into the safe answer is this handler's
        job. It is the only tool on this surface that writes into the user's home
        directory, and the only one whose effect is machine-wide — a fact archived out
        of the profile store stops answering for every other project on this machine
        with no store of its own — so the short call is the preview.

        The status is a decision the pass already made (`DreamResult.applied`,
        `.over_budget`, `.changes`), never a match on the reply.
        """
        with _record_raise(log, "memory_dream"):
            outcome = memory.dream_outcome(True if dry_run is None else bool(dry_run))
        log.record(
            "memory_dream",
            outcome.status,
            {
                "absolutised": outcome.absolutised,
                "consumed": outcome.consumed,
                "dry_run": outcome.dry_run,
                "merged": outcome.merged,
            },
        )
        return _noted(outcome.reply)

    def validate_json(output: str, schema: dict[str, Any]) -> dict[str, Any]:
        with _record_raise(log, "validate_json"):
            error = schema_error(output, schema)
        if error is None:
            log.record("validate_json", "valid")
            return _noted_dict({"valid": True, "feedback": None})
        log.record("validate_json", "invalid")
        return _noted_dict(
            {
                "valid": False,
                "feedback": schema_retry_feedback(error),
            }
        )

    def shiftwork_clock_in(checkpoint: str, unit_id: str | None = None) -> dict[str, Any]:
        # job60/D1: `unit_id` is optional here because it is optional in the asset, and the
        # signature is what `_from_manifest` binds as `fn_metadata` — i.e. what validates
        # the CALL. The advertised schema is the asset's; a signature that did not accept
        # the argument would advertise a property every host call carrying it then bounced.
        return _noted_dict(
            _record_result(
                log, "shiftwork_clock_in", lambda: shiftwork.clock_in(checkpoint, unit_id)
            )
        )

    def shiftwork_clock_out(
        checkpoint: str,
        unit_id: str,
        status: str,
        handoff_patch: dict[str, Any],
        history_entry: dict[str, Any],
        accounting: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _noted_dict(
            _record_result(
                log,
                "shiftwork_clock_out",
                lambda: shiftwork.clock_out(
                    checkpoint, unit_id, status, handoff_patch, history_entry, accounting
                ),
            )
        )

    def shiftwork_status(checkpoint: str) -> dict[str, Any]:
        return _noted_dict(
            _record_result(log, "shiftwork_status", lambda: shiftwork.status(checkpoint))
        )

    def work_plan(nodes: list[dict[str, Any]]) -> dict[str, Any]:
        # `result` is added HERE and not in `workplan.plan`, which is Layer 1 and answers
        # the computation (`batches`, `sequence`, `width`) rather than a wire shape. The
        # wire shape is the tool asset's, so the verdict key is put on at the seam that
        # serves it — the same division `plan_batches` uses one layer down. A refusal
        # already carries its own `result` and passes through untouched, because
        # `_record_result` reads that key to write the register's verdict to the log.
        def answered() -> dict[str, Any]:
            plan = workplan.plan(nodes)
            return plan if plan.get("result") == "error" else {"result": "plan", **plan}

        return _noted_dict(_record_result(log, "work_plan", answered))

    def shiftwork_plan(checkpoint: str) -> dict[str, Any]:
        return _noted_dict(
            _record_result(log, "shiftwork_plan", lambda: shiftwork.plan_batches(checkpoint))
        )

    # A TOOL and not a resource or an `initialize` field, because the gap RB-P84 names is
    # an AGENT MID-CALL: the host reads `serverInfo` once at handshake and the
    # tool-calling model never sees it, and `resources/read` is a host-facing surface
    # most clients never expose to the model at all. A tool is in `tools/list`, so the
    # model that just received a `memory_recall` answer can ask who answered it.
    def build_identity_tool() -> dict[str, Any]:
        with _record_raise(log, "build_identity"):
            identity = build_identity()
        # The COUNT of underivable fields, not the fields and not the digests. A code
        # digest is by construction different in the two runtimes — they fingerprint two
        # different trees (`docs/porting.md`'s divergence table says so about `build_id`)
        # — so putting one in a record that a conformance case byte-compares would make
        # the record unportable to buy nothing the tool's own reply does not already say.
        log.record(
            "build_identity",
            "partial" if identity["unavailable"] else "complete",
            {"unavailable": len(identity["unavailable"])},
        )
        return _noted_dict(identity)

    def bantamkit_status() -> str:
        """The one surface every host renders, answering "is this thing working".

        NO FOOTER ON THIS ONE, and the omission is the design rather than an oversight:
        the report already carries every condition in full, and a footer would repeat the
        worst of them three lines below itself.

        NOTHING IS RECORDED IN THE EVENT LOG EITHER. Every other handler records the
        decision its component made; this one makes no decision — it observes. A record
        would be a second, worse copy of a state the log's own reader can see, and its
        `outcome` would have to be the health verdict, which moves with the filesystem
        rather than with anything the call did. `_record_raise` still wraps the body, so
        a handler that FALLS OVER is still written down.
        """
        with _record_raise(log, "bantamkit_status"):
            return status_report(
                memory,
                log,
                degraded_conditions(memory, log),
                len(tools),
                SERVED_PROMPTS,
                SERVED_RESOURCE_TEMPLATES,
            )

    def bantamkit_read(
        path: str,
        part: str | None = None,
        offset: Annotated[int, Field(le=OFFSET_MAXIMUM)] | None = None,
        limit: int | None = None,
    ) -> str:
        """The reader on the MCP surface (job43): `docread` digests, `contract` words it.

        DORMANT — NOT REGISTERED since job50 I5 (user ruling, 2026-09-12): `bantamkit_read`
        left the roster because the transcript corpus showed it was never called. The
        reader (`docread`, `docmanifest`, `contract`) and its tests are untouched; this
        handler, its document cache and `OFFSET_MAXIMUM` are kept, unregistered, so the
        roster line can return without a rewrite.

        The eval pair (`evalrun._document_tools`) already renders a manifest, a page and
        every refusal from these two modules, and this handler makes the SAME calls with
        the path standing in for the document name, so the two surfaces print the same
        bytes for the same file. Three sentences are this tool's own — the continuation
        line names `bantamkit_read`, an unknown part is a fact about the file, and so is
        a part with no rows (`document_error` over `"{part}" in {path} has no rows`).

        THE RECORD IS A DECISION, NEVER A REPLY. `manifest` and `page` are the branch
        taken; `refused-unreadable` is `extract` raising (a missing file, a directory, a
        container this reader has no extractor for, an `OSError` the filesystem threw —
        all of them reach the model as a `document_error` sentence in the reader's own
        words, never as an exception on the wire); `refused-unknown-part` and
        `refused-offset` are the two argument refusals — the latter also when the part has
        no rows at all, where NO offset can be in range and the sentence says so instead of
        "numbered 0 to -1" (review round 3). `detail` carries the container
        kind (a token from `docread`'s closed set), the part count, and the rows and
        UTF-8 bytes the reply carries — never the path, never a part name, never a row.

        `limit` is clamped to the advertised `[1, 200]` and `offset` to `>= 0` the way
        `memory_recall` clamps `k`: the schema says so, and a client may ignore it. The
        one bound NOT clamped is `offset`'s `maximum` (`OFFSET_MAXIMUM`, 2**53 - 1): a
        clamp would silently read a different row than the one asked for, and the Node
        port cannot even carry the number — `JSON.parse` has already rounded it — so both
        sides refuse it with the schema refusal they already share. It is bound in the
        SIGNATURE (`Field(le=...)`), which is what `from_function` validates at call time;
        the advertised schema still comes from the manifest alone (`_from_manifest`).
        """
        start = 0 if offset is None else max(0, offset)
        rows = docread.DEFAULT_ROW_LIMIT
        if limit is not None:
            rows = max(1, min(limit, docread.PAGE_MAX_ROWS))
        with _record_raise(log, "bantamkit_read"):
            key = _document_key(path)
            doc = cache.get(key)
            if doc is None:
                try:
                    doc = docread.extract(path)
                except (docread.DocumentReadError, OSError) as exc:
                    log.record("bantamkit_read", "refused-unreadable")
                    return _noted(document_error(exc))
                cache.put(key, doc)
            detail: dict[str, Any] = {"kind": doc.kind, "parts": len(doc.parts)}
            if part is None:
                reply = docmanifest.render_manifest([(path, doc)])
                detail.update(rows=sum(p.row_count for p in doc.parts), bytes=doc.text_bytes)
                log.record("bantamkit_read", "manifest", detail)
                return _noted(reply)
            try:
                target = doc.part(part)
            except docread.DocumentReadError:
                log.record("bantamkit_read", "refused-unknown-part", detail)
                return _noted(bantamkit_read_unknown_part(part, path, [p.name for p in doc.parts]))
            if target.row_count == 0:
                log.record("bantamkit_read", "refused-offset", detail)
                return _noted(docmanifest.document_no_rows(target.name, path))
            if start >= target.row_count:
                log.record("bantamkit_read", "refused-offset", detail)
                return _noted(document_offset_past_end(target.name, start, target.row_count))
            got = docread.page(doc, part, start, rows, docread.PAGE_MAX_BYTES)
            detail.update(rows=len(got.rows), bytes=len(got.text.encode()))
            log.record("bantamkit_read", "page", detail)
            return _noted(
                document_page(
                    document=path,
                    part=got.part,
                    offset=got.offset,
                    rows=list(got.rows),
                    row_count=got.total_rows,
                    next_offset=got.next_offset,
                    truncated_bytes=got.truncated_bytes,
                    next_key="bantamkit_read_page_next",
                )
            )

    def skill_audit(
        root: str,
        enabled: list[str] | None = None,
        usage: dict[str, int] | None = None,
        check: str | None = None,
        budget: int | None = None,
        versions: dict[str, str] | None = None,
    ) -> str:
        """The catalogue auditor on the MCP surface: `skillaudit` measures, this serves it.

        THE REPLY IS A JSON DOCUMENT AND NOT PROSE, which is the one thing that makes this
        handler shaped differently from `bantamkit_read` next door. The reader answers a
        person reading a transcript, so `contract` words it; this answers a caller that has
        to compare `catalogue_bytes` against a budget it set and act on the ids in
        `findings[].skills`. A sentence would have to be parsed back. So `Audit.as_json` is
        the reply verbatim, and the only strings this layer authors are the refusals.

        THE REFUSALS ARE ARGUMENT FAILURES, ALL THREE OF THEM, so they go through
        `tool_failed` — an unknown `check`, a negative `budget`, a `root` that is not a
        directory. Nothing about the CONTENT of the tree refuses: a file that will not
        decode, a block that will not parse and a plugin that is switched off are recorded
        as omissions and counted. An audit that refused because one of twenty-six files is
        malformed would have said nothing about the other twenty-five.

        `check` defaults HERE rather than in the signature's default so that the one
        spelling of the default lives in `skillaudit.audit`, and `None` and an absent
        argument reach it as the same thing.

        `versions` is the third caller-supplied host fact beside `enabled` and `usage`: the
        version directory the host actually serves, per `<plugin>@<marketplace>`. It is
        passed straight through, and an absent map is the byte-order fallback.

        THE RECORD IS A DECISION, NEVER A REPLY, and it holds no free text: `audited`
        carries the four counts the host cannot see (skills, catalogue bytes, findings,
        omissions) and `refused` carries nothing at all. `root` is a path the operator
        typed and `findings[].skills` are the names of their skills; neither is a decision
        this handler made, so neither is written down.
        """
        with _record_raise(log, "skill_audit"):
            try:
                result = skillaudit.audit(
                    root,
                    enabled=enabled,
                    usage=usage,
                    check="all" if check is None else check,
                    budget=budget,
                    versions=versions,
                )
            except (skillaudit.SkillAuditError, OSError) as exc:
                log.record("skill_audit", "refused")
                return _noted(tool_failed("skill_audit", exc))
            log.record(
                "skill_audit",
                "audited",
                {
                    "skills": result.skills,
                    "bytes": result.catalogue_bytes,
                    "findings": len(result.findings),
                    "omissions": len(result.omissions),
                },
            )
            return _noted(result.as_json())

    def repo_map(
        root: str,
        focus: list[str] | None = None,
        budget: int | None = None,
    ) -> str:
        """The ranked definition map on the MCP surface: `repomap` measures, this serves it.

        DORMANT — NOT REGISTERED since job50 I5 (user ruling, 2026-09-12): `repo_map` left
        the roster because the transcript corpus showed it was never called. The engine
        (`repomap.py`) and its tests are untouched; this handler is kept, unregistered, so
        the roster line can return without a rewrite.

        THE THREE REFUSALS LIVE HERE AND NOT IN `repomap.py`, and that is deliberate.
        `repo_map()` over a root that does not exist answers an EMPTY map on both runtimes
        — `os.walk` yields nothing for a missing directory and `walkSources`' `readdirSync`
        catch does the same — which is the right answer for a library and the wrong one for
        a tool: a caller who typed the path wrong would be told the tree holds no source.
        So the argument checks are the SURFACE's, the way `bantamkit_read`'s
        `refused-offset` is, and the engine J45-9/J45-10 proved byte-identical is not
        touched by this unit.

        `focus` names the files the caller already has open; they are excluded from the
        listing. A focus entry that is not a scanned source is IGNORED, not refused —
        `repo_map` documents that, and refusing would make the tool useless the moment a
        caller named a file the scanner has no dialect for.

        THE LAST PARAGRAPH IS FIXED AND MANDATORY. Row 10's build gate was refuted by
        measurement (0.114 % of real prompt tokens) and the feature ships on an explicit
        ruling to build it anyway; a surface that let a caller believe the map is a saving
        would be the one sentence this whole feature is not allowed to say.

        THE RECORD IS A DECISION AND HOLDS NO PATH. `root` is what the operator typed and
        `focus` is the name of the file they are editing; neither is a decision this
        handler made, so neither is written down. The counts are.
        """
        with _record_raise(log, "repo_map"):
            names = [str(f) for f in (focus or [])]
            wanted = repomap.DEFAULT_BUDGET if budget is None else int(budget)
            base = Path(root)
            if not root:
                log.record("repo_map", "refused")
                return _noted(
                    tool_failed(
                        "repo_map", "root must not be empty; name the directory to map"
                    )
                )
            if wanted < 0:
                log.record("repo_map", "refused")
                return _noted(
                    tool_failed("repo_map", f"budget must not be negative; got {wanted}")
                )
            # `Path.exists()` and `Path.is_dir()` both SWALLOW the not-here errno family
            # (ENOENT, ENOTDIR, ELOOP, EBADF) and re-raise anything else, so a dangling
            # symlink and `a-file.py/sub` are both "no such directory" while a permission
            # failure flies to `_record_raise` rather than being dressed up as a missing
            # tree. Node's `statSync` arm reproduces exactly that split; there is no
            # `except OSError` here because `repomap.repo_map` raises none — its walk and
            # its reads each already resolve a failure into a counted Omission.
            if not base.exists():
                log.record("repo_map", "refused")
                return _noted(tool_failed("repo_map", f"no such directory: {root}"))
            if not base.is_dir():
                log.record("repo_map", "refused")
                return _noted(
                    tool_failed("repo_map", f"{root} is a file, not a directory to map")
                )
            result = repomap.repo_map(base, focus=names, budget=wanted)
        log.record(
            "repo_map",
            "mapped",
            {
                "definitions": result.definitions,
                "edges": result.edges,
                "files_rendered": result.files_rendered,
                "listing_bytes": result.listing_bytes,
                "nodes": result.nodes,
            },
        )
        return _noted(repo_map_reply(result))

    def token_ledger(
        root: str,
        model: str | None = None,
        prices: str | None = None,
    ) -> str:
        """The transcript ledger on the MCP surface: `tokenledger` measures, this serves it.

        THE REPLY IS A JSON DOCUMENT AND NOT PROSE, the same shape and for the same reason as
        `skill_audit` above: a caller comparing `totals` before and after a change, or
        deciding whether `omissions` explain a total that looks too small, has to read
        numbers rather than parse a sentence back out of English. `Ledger.as_json` is the
        reply verbatim and the only strings this layer authors are the refusals.

        THE FOUR REFUSALS ARE ARGUMENT FAILURES — an empty `root`, a `root` that is missing,
        a `root` that is a file, an empty `model` — so they go through `tool_failed`.
        Nothing about the CONTENT of the tree refuses: a transcript that will not decode, a
        line that will not parse and a record with no usage are omissions and are counted. A
        ledger that refused because one of eight hundred transcripts is truncated would have
        told the operator nothing about the other seven hundred and ninety-nine.

        `PriceTableError` is caught here BESIDE `TokenLedgerError` and is not the same kind
        of thing: it is an operator configuration fault reached only when `model` names a
        price table that will not load. It is still an argument failure from the CALLER's
        side — it names the path they passed — so it is refused with the same wording
        machinery rather than crashing the request.

        THE RECORD IS A DECISION, NEVER A REPLY. `read` carries the four counts the host
        cannot see (transcripts, lines, requests, sessions) and `refused` carries nothing at
        all. `root` is a path the operator typed and `sessions[].cwd` are their own working
        directories; neither is a decision this handler made, so neither is written down.
        And no token count is recorded either: the event log is a record of what this server
        DID, and the numbers are the reply.
        """
        with _record_raise(log, "token_ledger"):
            try:
                result = tokenledger.read(root, model=model, prices=prices)
            except (tokenledger.TokenLedgerError, PriceTableError, OSError) as exc:
                log.record("token_ledger", "refused")
                return _noted(tool_failed("token_ledger", exc))
            log.record(
                "token_ledger",
                "read",
                {
                    "transcripts": result.transcripts,
                    "lines": result.lines,
                    "requests": result.requests,
                    "sessions": len(result.sessions),
                },
            )
            return _noted(result.as_json())

    # The served surface, in one place, read out of the asset pack. Adding a tool here
    # without an asset raises AssetNotFound at startup — the manifest cannot drift behind
    # the server, because the server cannot start without it.
    #
    # `bantamkit_status` went LAST rather than first, `memory_compact` after it rather
    # than beside `memory_save` where a reader would look for it, `skill_audit` after
    # that, `memory_dream` after that and `token_ledger` after that. Registration order
    # IS the served order
    # (`test_tool_manifest.py::test_the_golden_records_the_order_the_wire_actually_
    # serves`), and appending is the only edit that leaves the others where every
    # existing declaration says they are.
    #
    # `bantamkit_read` (tenth) and `repo_map` (thirteenth) LEFT this list on the user's
    # ruling of 2026-09-12 (job50, I5): measured over the transcript corpus, neither was
    # called — auto-mode routes discovery and reading through Bash — and every request
    # re-sent their descriptions. Their assets claim NO surface now (`"surfaces": []`),
    # so putting either name back here without also restoring `"mcp"` to its asset is
    # refused by `_from_manifest` at startup. The handlers below are DORMANT, not gone:
    # a roster decision, not a deletion of working code.
    tools = [
        _from_manifest(memory_save, "memory_save"),
        _from_manifest(memory_recall, "memory_recall"),
        _from_manifest(validate_json, "validate_json"),
        _from_manifest(shiftwork_clock_in, "shiftwork_clock_in"),
        _from_manifest(shiftwork_clock_out, "shiftwork_clock_out"),
        _from_manifest(shiftwork_status, "shiftwork_status"),
        _from_manifest(build_identity_tool, "build_identity"),
        _from_manifest(bantamkit_status, "bantamkit_status"),
        _from_manifest(memory_compact, "memory_compact"),
        _from_manifest(skill_audit, "skill_audit"),
        _from_manifest(memory_dream, "memory_dream"),
        _from_manifest(token_ledger, "token_ledger"),
        _from_manifest(work_plan, "work_plan"),
        _from_manifest(shiftwork_plan, "shiftwork_plan"),
    ]

    server = MCPServer(
        SERVER_NAME,
        instructions=load_skill("memory"),
        version=_version(),
        tools=tools,
    )

    # THE PROMPT, AND WHY IT IS NOT A DUPLICATE OF THE TOOL ABOVE.
    #
    # `prompts/list` was EMPTY on both runtimes while both advertised `hasPrompts: true`,
    # so this is a new surface rather than an addition to one. A tool is what the MODEL
    # can call; a prompt is what a PERSON can invoke — in Claude Code it is a slash
    # command in the operator's own menu. The person wanting to know whether their server
    # is alive is the operator, and until now the only way for them to ask was to talk a
    # model into asking for them.
    #
    # IT CARRIES THE ANSWER, not an instruction to go and get it. `prompts/get` runs
    # server-side, so the report is already in the message the host inserts: the operator
    # sees it with no tool round trip, and it is true as of the moment they asked.
    @server.prompt(
        name=STATUS_NAME,
        title="bantamkit status",
        description=(
            "Is bantamkit actually working? Inserts the running server's own status "
            "report — active or degraded, its version and build fingerprint, the memory "
            "store it is bound to, whether the event log is on, and every degraded "
            "condition in full. Invoke it when you want the server to answer for itself "
            "rather than ask a model to go and check."
        ),
    )
    def bantamkit_status_prompt() -> str:
        conditions = degraded_conditions(memory, log)
        report = status_report(
            memory, log, conditions, len(tools), SERVED_PROMPTS, SERVED_RESOURCE_TEMPLATES
        )
        return f"{report}\n\n{STATUS_PROMPT_TAIL}"

    @server.resource("bantamkit://skills/{name}")
    def skill_resource(name: str) -> str:
        # A skill that pairs with a tool is served on that tool's surfaces and no other. The
        # pairing is the one `filegraph.py` spells: `load_tool("file_graph")` beside
        # `load_skill("file-graph")` — the skill's name with `-` for `_`. `file-graph` is the
        # eval agent's system-prompt snippet telling it to call `file_graph`, a tool whose
        # asset claims only `agent`; handing that text to an MCP client sends it to a tool
        # `tools/list` does not carry and `tools/call` refuses as unknown (job60 row 46).
        # Same sentence and same error code on both runtimes; `tools/conformance/suites/
        # instructions.mjs` reads every skill on disk over `resources/read` and resolves the
        # tools it names against `tools/list`.
        paired = name.replace("-", "_")
        try:
            asset = load_tool_asset(paired)
        except AssetNotFound:
            asset = None
        if asset is not None and "mcp" not in asset["surfaces"]:
            raise ResourceError(
                f"skill asset {name} is not served here: it pairs with tool {paired}, "
                f"whose asset claims surfaces {asset['surfaces']}, not mcp"
            )
        try:
            return load_skill(name)
        except AssetNotFound:
            raise ResourceError(f"unknown skill asset: {name}") from None

    @server.resource("bantamkit://rubrics/{name}")
    def rubric_resource(name: str) -> str:
        path = assets_root() / "rubrics" / f"{name}.yaml"
        if not path.is_file():
            raise ResourceError(f"unknown rubric asset: {name}")
        return path.read_text(encoding="utf-8")

    return server


def _build_parser() -> argparse.ArgumentParser:
    """The parser, as an object, so something other than `parse_args` can render its help.

    Extracted from `_parse_args` for exactly one caller: the bare-at-a-terminal branch in
    `main`, which prints THE HELP `-h` PRINTS and must not be able to drift from it. A
    second hand-written copy of a generated string is the defect `runtime-ts/src/cli.ts`'s
    header records having already shipped once; the way to not have it here is to have one
    parser and two callers, not two strings.
    """
    parser = argparse.ArgumentParser(
        prog="bantamkit-mcp",
        description="bantamkit MCP server (stdio): per-person memory + JSON validation.",
    )
    # POSITION IS WIRE-VISIBLE. argparse prints optionals in the order they were added, so
    # this line -- not any format string -- decides where `[--assets-root]` sits in the
    # generated usage, and the Node formatter has to reproduce that. It goes FIRST, beside
    # the `-h` argparse adds for us, because those two share a property nothing below them
    # has: they print and return 0 without a memory store, a transport, or a server. Every
    # flag after them configures a server that is actually going to run.
    parser.add_argument(
        "--assets-root",
        action="store_true",
        help="print the resolved asset pack root and its file count, then exit",
    )
    parser.add_argument("--k", type=int, default=3, help="default recall budget (default: 3)")
    # The index is loaded into every prompt, so its ceiling is a deployment decision.
    # It had no flag: 4096 was reachable only by editing `store.py`, which made
    # `docs/memory.md`'s "lifecycle is an operator decision" true of the design and
    # false of the deployment. Lifecycle ACTIONS stay off this process — it speaks MCP
    # over stdout — and live on `python -m bantamkit.memory`.
    parser.add_argument(
        "--index-budget",
        type=int,
        default=DEFAULT_INDEX_BUDGET,
        metavar="BYTES",
        help=f"memory index byte budget (default: {DEFAULT_INDEX_BUDGET})",
    )
    # THE HOOK ADAPTER, AND IT IS A FLAG FOR THE REASON `--mcp-report` GIVES BELOW, ONLY
    # HARDER. `runtime-ts/package.json` declares exactly one bin, so anything hung off a
    # second entry point is unreachable in the pure-npx install that is the shipped product
    # -- and the hook adapter was, literally: it lived in `tools/hooks/bantamkit-hook.mjs`,
    # and MEASURED at 0.35.3 with `npm pack --dry-run` the tarball is 174 files under
    # `files: ["dist","assets"]` with not one of them matching `hook`. An operator who
    # installed bantamkit the only way it is published had no adapter on disk to register.
    #
    # POSITION IS WIRE-VISIBLE AND IT IS MEASURED, the same as every flag below it. At the
    # 80-column fallback argparse breaks the usage after `[--index-budget BYTES]`, and that
    # first line is pinned in `test_mcpserver.py`, in `test_mcpreport.py`, in
    # `test_selfupdate.py`, in `runtime-ts/test/cli-surface.test.mjs` and as a THROWING
    # precondition in `tools/conformance/suites/cli.mjs`. Registered HERE -- the first flag
    # AFTER `--index-budget` -- it grows the SECOND usage line only. Registering it earlier
    # would move the pinned line and turn a differential suite into a re-baselining one, and
    # it is the same position `runtime-ts/src/cli.ts` registers it at because the two `-h`
    # outputs are compared byte for byte.
    #
    # BARE, WITH NO METAVAR, AND THE EVENT COMES FROM STDIN. The host sends one JSON object
    # carrying `hook_event_name`, which is what the adapter dispatches on; a second spelling
    # of the event on the command line would be a second thing to keep in step with the
    # host, and the registration in `~/.claude/settings.json` would have to carry seven
    # different commands instead of one.
    #
    # THE CONTRACT IS DELIBERATELY NARROW, WHICH IS WHAT MAKES IT GATEABLE: one JSON object
    # in on stdin, at most one JSON object out on stdout, exit 0 ALWAYS.
    parser.add_argument(
        "--hook",
        action="store_true",
        help="run as a Claude Code hook: one JSON event on stdin, then exit",
    )
    # WHY THIS IS A FLAG ON THIS PROCESS AND NOT A NEW ENTRY POINT.
    # `memory/__main__.py` argues lifecycle needs a stream it owns, because this process
    # speaks MCP over stdout. True of a RUNNING server; not true of a flag that prints and
    # returns before any transport exists -- `--assets-root` above is the precedent. And it
    # is decisive here rather than merely convenient: `runtime-ts/package.json` declares
    # exactly one bin, `bantamkit-mcp`, so anything hung off `python -m ...` is unreachable
    # in a pure-npx install, which is the shipped product.
    #
    # POSITION IS DELIBERATE AND IT IS NOT BESIDE `-h`. `--assets-root` sits first because
    # it needs NOTHING; this one honours `--store`/`--start` to find the event log, so it
    # reads after the flags it consumes. The second reason is measured: the first line of
    # the wrapped usage is pinned in two places -- this repo's
    # `test_assets_root_appears_in_the_generated_help_in_the_documented_position` and the
    # `cli` conformance suite's reference precondition -- and at the 80-column fallback the
    # line breaks after `[--index-budget BYTES]`. Adding here leaves that line byte-identical;
    # adding before it would move it and turn a differential suite into a re-baselining one.
    parser.add_argument(
        "--mcp-report",
        action="store_true",
        help="print an analysis of the host MCP log joined with bantamkit's event log, then exit",
    )
    # THE SAME THREE ARGUMENTS AS `--mcp-report`, and the same place for the same reason.
    # It prints and returns before a transport exists; the single Node bin makes a flag the
    # only reachable surface in the shipped npx install, which is what a `statusLine`
    # registration has to name; and it honours `--store`/`--start` to find the event log, so
    # it belongs after the flags it consumes and before the store group. Registering it here
    # leaves the FIRST line of the 80-column usage -- the pinned one -- byte-identical and
    # grows only the second.
    parser.add_argument(
        "--statusline",
        action="store_true",
        help="print one status line for a host status bar, then exit",
    )
    # THE ONE FLAG ON THIS PARSER THAT TOUCHES THE NETWORK, and the placement is what keeps
    # that from spreading. `--assets-root` sits beside `-h` because it needs nothing; this
    # one needs the most of any flag here, so it does NOT go there — and the second reason is
    # the same measured one the comment above gives: the first line of the 80-column usage is
    # pinned in `test_assets_root_appears_in_the_generated_help_in_the_documented_position`,
    # in `test_mcpreport.py`, and in the `cli` conformance suite, and a flag added before
    # `--mcp-report` would move it and turn a differential suite into a re-baselining one.
    # Registered here it grows the SECOND usage line only.
    #
    # DEFAULTS OFF, like every other flag on this parser, which is the whole of AS-7(3): the
    # network is reached when a person asks for it by name and on no other path. There is no
    # startup check, nothing on `bantamkit_status`, and no background poller.
    parser.add_argument(
        "--update",
        action="store_true",
        help="check the package index and update this install if it differs, then exit",
    )
    # THE SAME PLACE AND THE SAME REASON AS THE TWO ABOVE. It prints and returns before a
    # transport exists, so it belongs with the flags that need no server; and it is placed
    # after `--statusline` rather than beside `-h` so that the FIRST line of the 80-column
    # usage — pinned by
    # `test_assets_root_appears_in_the_generated_help_in_the_documented_position` and by the
    # `cli` conformance suite — stays byte-identical. The choices render long enough to take
    # a line of their own; that line is below the pinned one.
    parser.add_argument(
        "--install",
        choices=hostinstall.HOSTS,
        help="wire this server into a host's MCP configuration, then exit",
    )
    # Paired with `--install` and useless without it, which the parser checks rather than
    # the help text claiming it. It exists because this command NEVER prompts: an overwrite
    # is exactly when a program wants to ask, and asking needs a TTY that neither Claude
    # Code's `!` channel nor CI has.
    parser.add_argument(
        "--force",
        action="store_true",
        help="with --install, replace an existing bantamkit entry",
    )
    stores = parser.add_mutually_exclusive_group()
    stores.add_argument("--store", help="single memory store path (disables layering)")
    stores.add_argument(
        "--start", help="directory to start project-store discovery from (default: cwd)"
    )
    return parser


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


def _typed_bare_at_a_terminal(
    argv: list[str] | None = None, stdin: TextIO | None = None
) -> bool:
    """True when a PERSON typed `bantamkit-mcp` with nothing after it. Never for a host.

    WHY THERE IS A DISCRIMINATION HERE AT ALL. Typing the command at a prompt used to open
    a stdio JSON-RPC server and block: no output, no prompt back, Ctrl-C the only way out.
    To a person that is indistinguishable from a hang, and it is what the user asked to be
    fixed on 2026-09-11 -- "เพิ่ม task set default when call bantamkit-mcp only ให้แสดงเหมือน --help".

    WHY IT IS NOT SIMPLY "NO ARGUMENTS -> PRINT HELP". The bare invocation IS the
    production launch path. Both registrations on this machine pass an empty `args`:

        $ cat .mcp.json
        {"mcpServers":{"bantamkit":{"command":"tools/bantamkit-mcp","args":[]}}}
        $ # user scope, ~/.claude.json
        bantamkit  {"type":"stdio","command":".../tools/bantamkit-mcp-node","args":[], ...}

    and `runtime-ts/src/cli.ts`'s header says the same in its own words, as the reason an
    earlier refusal on the bare form was retired: "the production invocation passes NO
    arguments at all ... so the bare form is the one that must serve." A literal reading of
    the request would therefore break every MCP host here, including the bantamkit server
    this repository's own policy orchestrates through.

    SO THE SIGNAL IS `stdin.isatty()`, AND IT IS THE ONLY SIGNAL. A host wires stdin to a
    pipe or a socket; a person at a keyboard has a terminal on it. Deliberately NOT
    `stdout.isatty()`: stdout is the JSON-RPC channel and a host may redirect the two
    streams differently, so a tty on stdout says nothing about who is asking. Deliberately
    not a flag either -- a flag to opt out means the bare form is no longer bare, and the
    bare form is the one under discussion.

    AND THE EMPTY ARGV IS A SCOPE, NOT A SECOND SIGNAL. What the user asked for is the
    command "only" -- with nothing after it. `bantamkit-mcp --store /tmp/x` typed at a
    terminal is an operator explicitly asking for a configured server, and it keeps
    getting one; hand-driving the line-delimited protocol at a prompt stays possible. The
    two conditions do different jobs: `argv` says WHICH invocation is in scope, `isatty`
    says WHO is on the other end of it. `runtime-ts/src/cli.ts` holds the same pair.

    `isatty()` on a closed stream raises `ValueError`, and `sys.stdin` is `None` under a
    GUI launcher with no console. Neither is a person at a terminal, and neither may be
    allowed to take down the serving path, so both answer False.
    """
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        return False
    stream = sys.stdin if stdin is None else stdin
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except ValueError:
        return False


def _build_memory(args: argparse.Namespace) -> Memory:
    if args.k < 1:
        raise SystemExit("--k must be >= 1")
    if args.index_budget < 1:
        raise SystemExit("--index-budget must be >= 1")
    if args.store is not None:
        if not args.store:
            raise SystemExit("--store requires a non-empty path")
        _check_store_flag(args.store)
        return Memory(store=args.store, k=args.k, index_budget=args.index_budget)
    return Memory.layered(start=args.start, k=args.k, index_budget=args.index_budget)


def _check_store_flag(raw: str) -> None:
    """`--store` may name a store that is missing, never one that is not a store.

    THIS CHECK IS RESTORED, NOT INVENTED, and the distinction is the point. Until the
    project layer was built lazily there WAS a `--store` validation, and it was entirely
    accidental: the constructor ran `mkdir(parents=True)`, so a `--store` pointing at a
    regular file or at a path under a directory that does not exist took the process down
    with an `OSError` traceback out of `pathlib`. `test_statusline.py::
    test_the_flag_returns_before_anything_a_server_would_touch` depends on it -- it arms
    `--store <a regular file>` as a trap and shows `--statusline` walking past it -- and a
    lazy layer disarms the trap by making that same argv exit 0. The honest way to keep
    that test true is to mean the refusal on purpose.

    IT IS `layers._pinned_store`'s CHECK MINUS ONE ARM, and the missing arm is deliberate
    and measured. The pin refuses a path that is not there ("nothing was created"); this
    flag does NOT, and must not, for two reasons that are both already pinned elsewhere in
    this repository:

    - The sibling CLI's identical flag is contracted to CREATE one. `tools/conformance/
      suites/memorycli.mjs` carries `status-creates-a-missing-store`, `--store {BED}/nowhere`
      over an empty bed, whose whole job is to say the two runtimes create the same two
      directories there. Refusing a missing `--store` here would put two flags of the same
      name, in two programs of the same product, in direct contradiction.
    - "Missing" is no longer a broken state anywhere in this program. The walk designates a
      project store without creating it, and the first save brings it into existence or
      refuses by name (`store._ensure_dirs`). A `--store` at a path that is not there is
      that same designated state, reached by being told instead of by searching. MEASURED:
      requiring existence here reddened 14 tests that have nothing to do with this defect
      -- `test_tool_manifest.py` ×7, `test_mcpserver.py` ×6, `test_mcp_endpoint.py` -- every
      one of them a fixture naming a store under `tmp_path` it never made, because that is
      what this flag has always meant.

    What is left is the arm the accident actually covered and the only one it covered: a
    `--store` that names something which EXISTS and is NOT A DIRECTORY. That is not a store
    and never becomes one -- `mkdir` under it is ENOTDIR on both runtimes and on every
    platform, the one row of the errno table where they already agree -- so it is refused
    here, by name, before a transport exists.

    `FileNotFoundError` and not an errno comparison: the absent case is selected by the
    exception CPython raises for it, which `runtime-ts`' `pyfs` shim raises under the same
    name. Every other `stat` failure -- a permission wall on the parent, a symlink loop --
    is a real fault about a path the operator named, and it keeps the pin's sentence.

    `os.stat` rather than `Path.is_dir()`, and that too is `_pinned_store`'s reasoning:
    `is_dir()` swallows `PermissionError` and answers False, which would report an
    operator's real store as a typo. A single named path gets the accurate reason.

    `SystemExit` and not `MemoryValidationError`, so that both halves of this flag's
    refusal family read the same way on the terminal: `--store requires a non-empty path`
    is already bare on stderr at exit 1, and the port spells both as `Refusal`.
    """
    # NOT `expanduser()`, unlike the pin. `Memory(store=...)` builds `Path(root)` from this
    # string verbatim, so expanding here would check one path and serve another: `--store
    # ~/x` left unexpanded by the shell would pass a check against the home directory and
    # then build a store in a directory literally named `~`. The check must stat the path
    # the store is going to be.
    store = Path(raw)
    try:
        info = os.stat(store)
    except FileNotFoundError:
        return  # designated, not broken: the first save makes it or refuses by name
    except OSError as e:
        raise SystemExit(
            f"--store is unreachable: {store}: {e.strerror}; nothing was created"
        ) from e
    if not stat_module.S_ISDIR(info.st_mode):
        raise SystemExit(f"--store is not a directory: {store}")


def _run_hook(args: argparse.Namespace) -> None:
    """`--hook`: one JSON event on stdin, at most one JSON object on stdout, EXIT 0 ALWAYS.

    DISPATCH ORDER IS REGISTRATION ORDER, which is the rule the flags around it already
    follow and the reason `--mcp-report --install cursor` prints a report and writes
    nothing. `--hook` is registered directly after `--index-budget`, so it is checked
    directly after `--assets-root` -- the same order `runtime-ts/src/cli.ts` checks it in.

    EXIT 0 ALWAYS, AND THAT IS THE CONTRACT, not a convenience. A hook that exits non-zero
    or lets a traceback reach stderr is rendered by the host as an error on the USER'S
    SCREEN, so every failure is logged into `~/.bantamkit/hooks/hook-log.jsonl` and
    swallowed. This is the one arm in this file whose refusal path is a log line rather than
    a sentence, and the `except` is deliberately wide for that reason: `main` catches
    `BantamError` and exits 1, which is right for every other surface here and wrong for
    this one.

    `SystemExit` and `KeyboardInterrupt` are NOT swallowed -- they are not failures of the
    adapter, and a hook that ignored an interrupt would be a process the operator cannot
    stop.

    It returns before `_build_memory` for the same reason every flag around it does: the
    adapter binds whatever store the winning MCP registration pins, from the cwd the HOST
    sent in the payload -- not from whatever directory the hook process was spawned in. It
    takes `args` for the signature every `_run_*` here has and reads nothing off it, because
    the payload is the entire input contract.
    """
    del args  # the event, the cwd and the session all arrive on stdin
    try:
        hookadapter.run_hook()
    except Exception as e:  # noqa: BLE001 - see the docstring: exit 0 is the contract
        hookadapter.log_hook_failure(e)


def _print_mcp_report(args: argparse.Namespace) -> None:
    """`--mcp-report`: the joined report on stdout, then return. No transport, no server.

    Same discipline as `_print_assets_root`: written through `sys.stdout.buffer`, because
    `sys.stdout` is a text stream with newline translation and on Windows `print` would
    emit CRLF where Node's `process.stdout.write` emits LF.

    NOTHING HERE IS WRITTEN. `mcpreport` opens the host's log read-only, creates no
    directory under its root, and `resolve_event_log_path` designates a store path without
    bringing a store into existence. The report is an observation, not a session.
    """
    text = build_mcp_report(
        dict(os.environ),
        resolve_event_log_path(dict(os.environ), store=args.store, start=args.start),
    )
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def _print_status_line(args: argparse.Namespace) -> None:
    """`--statusline`: exactly one line on stdout, then return. Never stderr, never a raise.

    Written through `sys.stdout.buffer` for the same two reasons `_print_mcp_report` is:
    `print` would emit CRLF on Windows where Node emits LF and the conformance suite
    compares these bytes, and the line carries U+1F7E2 / U+1F7E0 / U+26AA, which a Windows
    console's default code page cannot encode -- `sys.stdout` would raise
    `UnicodeEncodeError` where this writes UTF-8.

    `status_line` is total, so there is no failure arm here to write. That is the point of
    the surface: this runs on a host's redraw path with nobody watching, and a traceback
    where a status bar should be is the one output it may not produce.
    """
    text = status_line(dict(os.environ), store=args.store, start=args.start)
    sys.stdout.buffer.write(f"{text}\n".encode())
    sys.stdout.buffer.flush()


def _print_assets_root() -> None:
    """`--assets-root`: two lines on stdout, then return -- no store, no transport, no server.

    THE TWO RUNTIMES PRINT DIFFERENT PATHS ON PURPOSE. Do not "fix" that. Python resolves
    the repo-root `assets/` (or the copy packaged inside `bantamkit/`); Node resolves
    `runtime-ts/assets/`, which `scripts/sync-assets.mjs` vendors at prepack time. The two
    trees are byte-identical file for file, but they live at different paths by
    construction and always will, so line 1 is NOT comparable across runtimes. What IS
    comparable, and what the conformance case pins: exactly two lines, the shape
    `<root>\\n<count> files\\n`, the same COUNT on both sides, exit 0, stdout not stderr,
    empty stderr, and no transport started.

    Written through `sys.stdout.buffer` rather than `print`, because `sys.stdout` is a text
    stream with newline translation: on Windows `print` would emit CRLF where Node's
    `process.stdout.write` emits LF, and a byte-comparing conformance runner would call
    that a divergence. UTF-8 is what Node's `Buffer.from(string)` uses, so the encoding
    matches too.
    """
    root = assets_root()
    files = len(_pack_files(root))
    sys.stdout.buffer.write(f"{root}\n{files} files\n".encode())
    sys.stdout.buffer.flush()


def _run_install(args: argparse.Namespace) -> None:
    """`--install <host>`: register this server, print what happened, return.

    Written through `sys.stdout.buffer` for the reason `_print_assets_root` gives: on
    Windows `print` emits CRLF where Node's `process.stdout.write` emits LF, and a
    byte-comparing conformance runner would read that as a divergence.

    A refusal goes to stderr and exits 1. It is not an exception the operator has to read a
    traceback for: every `InstallError` carries the sentence that says what to do next.
    """
    command, extra = hostinstall.this_command()
    try:
        report = hostinstall.install(args.install, command, extra, force=args.force)
    except hostinstall.InstallError as exc:
        sys.stderr.buffer.write(f"error: {exc}\n".encode())
        sys.stderr.buffer.flush()
        raise SystemExit(1) from None
    sys.stdout.buffer.write(f"{report}\n".encode())
    sys.stdout.buffer.flush()


def _run_update() -> None:
    """`--update`: ask the package index, act on the answer, print what happened, return.

    THE SENTENCES ARE NOT HERE. Every string this can print is a named constant in
    `selfupdate`, because `runtime-ts` copies them byte for byte and a second spelling in a
    second module is exactly the drift the two-runtime rule exists to stop. This function
    owns three things and nothing else: where the shape comes from, which stream each
    outcome is written to, and the exit code.

    STDOUT + EXIT 0 IS ONLY FOR AN ANSWER THAT IS ALREADY TRUE — up to date, the index
    behind, or an update that actually ran. Everything else is `error: <sentence>` on
    stderr and exit 1, including the install shapes this flag will not touch: an operator
    who typed `--update` asked for an update, and a command that exits 0 having changed
    nothing is the J46-4 defect by name. Exit 1 rather than 2 because argparse already owns
    2 for a usage error, and `--update` on a parser that declares it is not one.

    THE SHAPE IS `current_install()`'s ANSWER AND NOT A SECOND DETECTOR. AS-7(a) shipped
    that at `da97b52` as a module-level function taking no arguments and touching no server
    state, explicitly so this flag could ask it before a store or a transport exists. A
    second copy of a derived answer is the defect the `cli` suite exists to catch.

    `_Undetermined` — a `pip install git+https://…` origin, which is neither an index nor a
    path on this machine — is a refusal and not a fallback. Its own message already names
    the route ("reinstalling from that same URL"), so it is quoted rather than paraphrased.

    Written through `sys.stdout.buffer`/`sys.stderr.buffer` for the reason
    `_print_assets_root` gives: on Windows `print` emits CRLF where Node's
    `process.stdout.write` emits LF, and a byte-comparing conformance runner would read
    that as a divergence belonging to the writer rather than to the product.
    """
    try:
        install = current_install()
    except _Undetermined as exc:
        _refuse_update(selfupdate.SHAPE_UNKNOWN.format(reason=exc))
    # `source` is `None` for the two shapes that HAVE no recorded origin rather than for one
    # whose path could not be read — `registry`, where the route is this flag itself, and
    # `checkout`, whose tree IS the thing to update and which J46-11 deliberately left
    # without a `source` because finding a repo root without git would be a guess. The
    # running package directory is not a guess: it is where the code being executed lives.
    source = install.source or str(_running_package_file().resolve().parent)
    try:
        report = selfupdate.update(_version(), selfupdate.Origin(install.shape, source))
    except selfupdate.UpdateRefused as exc:
        _refuse_update(str(exc))
    sys.stdout.buffer.write(f"{report}\n".encode())
    sys.stdout.buffer.flush()


def _refuse_update(sentence: str) -> NoReturn:
    """One refusal writer, so every `--update` arm exits the same way on the same stream."""
    sys.stderr.buffer.write(f"error: {sentence}\n".encode())
    sys.stderr.buffer.flush()
    raise SystemExit(1)


def main() -> None:
    """Dispatch one invocation, and hand a refusal to the operator as a SENTENCE.

    THIS ARM IS A PARITY DEFECT BEING CLOSED, not a nicety. `runtime-ts/src/cli.ts` has
    caught `BantamError` at its top level and written `bantamkit-mcp: <message>` at exit 1
    since it was written, and `bantamkit/memory/__main__.py` was handed the same defect and
    fixed the same way for the operator memory CLI. This CLI never got it, so the identical
    refusal -- `BANTAMKIT_MEMORY_DIR=/nope/pinned`, one sentence that already names the
    directory and says nothing was created -- was one clean line on Node and a two-stage
    CPython traceback on Python, carrying this repository's absolute paths and line numbers
    in place of the store the operator asked about. Nothing covered it, so the suite was
    green over it.

    `BantamError` AND NOTHING WIDER, in `__main__.py`'s own words: a bug in bantamkit is
    still a traceback, because that one IS a report for a maintainer. What is caught is the
    class of failures that are ABOUT the operator's store, and every one of them already
    carries a sentence that names the directory and says what the consequence would have
    been -- including `_ensure_dirs`' new one, which is the whole reason a cwd of `/` is now
    a refused write rather than a dead process.

    `SystemExit` is deliberately not caught: argparse's usage errors are exit 2, and this
    file's own flag refusals are already their own sentence on stderr.

    Written through `sys.stderr.buffer`, like every other refusal in this file, so the line
    ends LF on Windows too and cannot drift from the port's `process.stderr.write`.
    """
    if MCPServer is None:
        raise SystemExit(_INSTALL_HINT)
    args = _parse_args()
    try:
        _dispatch(args)
    except BantamError as e:
        sys.stderr.buffer.write(f"bantamkit-mcp: {e}\n".encode())
        sys.stderr.buffer.flush()
        raise SystemExit(1) from e


def _dispatch(args: argparse.Namespace) -> None:
    # Before `_build_memory`, which touches the filesystem, and before the server exists at
    # all -- the Node arm returns from `main` here too, ahead of `new RawStdioTransport()`.
    if args.assets_root:
        _print_assets_root()
        return
    if args.hook:
        _run_hook(args)
        return
    if args.mcp_report:
        _print_mcp_report(args)
        return
    if args.statusline:
        _print_status_line(args)
        return
    if args.update:
        _run_update()
        return
    if args.install:
        _run_install(args)
        return
    # `--force` alone is a typo with a plausible reading -- somebody meant to install and
    # dropped the flag that says where. Refusing names the missing half instead of starting
    # a server that ignores it.
    if args.force:
        raise SystemExit("--force is only meaningful with --install")
    # A PERSON TYPED IT. `_typed_bare_at_a_terminal` carries the whole argument; what
    # belongs here is only that this sits BEFORE `_build_memory`, which is what creates a
    # store. Somebody who typed a command to see what it does has not asked for a
    # `.bantamkit/memory` directory in whatever cwd they were standing in, and the flags
    # above return before a transport for the same class of reason.
    #
    # AMENDMENT 2026-09-12 (job48, J48-1). "which is what creates a store" is no longer
    # true of the sentence's own words: the project layer is built `create=False`, so
    # `_build_memory` designates a path and creates nothing until a save. The guard stays
    # exactly where it is, for what remains of the reason -- a person typing a command to
    # see what it does has not asked for a walk up their filesystem either -- and it stays
    # because the ORDER is the contract the port shares, not because it is the last thing
    # standing between a bare invocation and a mkdir.
    #
    # STDOUT AND EXIT 0, i.e. byte-for-byte what `-h` does on this platform, because the
    # request was "ให้แสดงเหมือน --help" -- show it the way `--help` shows it. `print_help`
    # is the same call argparse's own `-h` action makes, so the two cannot diverge: fix
    # the stream or the newlines for one and the other follows. The alternative reading --
    # stderr and exit 2, "a bare invocation is a usage error" -- is refused because this
    # is not an error: it is the documented answer to the documented request, and the exit
    # code is only ever read by a shell a human is standing at. Nothing non-interactive
    # can reach this line at all.
    if _typed_bare_at_a_terminal():
        _build_parser().print_help()
        return
    server = build_server(_build_memory(args))
    asyncio.run(server.run_stdio_async())


# `python -m bantamkit.mcpserver` is the invocation a host config reaches for when the
# console script is not on PATH. Without this guard the module imported fine, defined
# `main`, and exited 0 with nothing on either stream; the client saw CONNECTION_CLOSED,
# which names the symptom and not the cause. Measured 2026-08-21 before this line:
# `.venv/bin/python -m bantamkit.mcpserver` -> exit 0, stdout 0 bytes, stderr 0 bytes.
if __name__ == "__main__":
    main()
