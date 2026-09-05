"""bantamkit as an MCP server: memory + validation over stdio, one instance per person."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Annotated, Any

import bantamkit
from bantamkit import __version__, docread, shiftwork, skillaudit
from bantamkit.assets import AssetNotFound, assets_root, load_skill, load_tool_asset
from bantamkit.client import BantamError
from bantamkit.contract import (
    bantamkit_read_unknown_part,
    document_error,
    document_manifest,
    document_offset_past_end,
    document_page,
    schema_error,
    schema_retry_feedback,
    tool_failed,
)
from bantamkit.eventlog import EventLog
from bantamkit.mcpreport import build_report as build_mcp_report
from bantamkit.mcpreport import resolve_event_log_path
from bantamkit.memory import DEFAULT_INDEX_BUDGET, Memory
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

#: Percent of the index budget that has to be SPENT before the store is called degraded.
#:
#: 90 and not 100 because the useful moment is before the refusal, not after it: at 100%
#: the next `memory_save` has already failed and the operator has already seen the error.
#: An INTEGER percent, compared by cross-multiplication below, so the two runtimes cannot
#: land on opposite sides of the line through a float they rounded differently.
INDEX_PRESSURE_PERCENT = 90


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


def degraded_conditions(memory: Memory, log: EventLog) -> list[Condition]:
    """Everything wrong right now, worst first. Empty list means healthy.

    ORDER IS SEVERITY AND IT IS LOAD-BEARING, because the footer shows the first one: a
    pack that vanished breaks every asset-backed surface; an unreadable layer makes recall
    ANSWER WRONGLY rather than fail; a full index refuses the next save; a broken event log
    costs diagnostics only.

    EVERY CONDITION IS OBSERVED, NOT INFERRED — no heartbeat, no timer, no last-seen
    timestamp. Each one is a state a test can construct and then watch this report: delete
    the pack, make a layer's `facts/` a file, build a store whose index already exceeds
    nine tenths of its budget, point the log at an unwritable path. A condition that
    cannot be constructed is not claimed.

    THE COST, because this runs on every tool call: one `stat` for the index, one `is_dir`
    for the pack, one `scandir` per memory layer (two to four), and a field read for the
    log. No fact file is opened and no index is parsed.
    """
    found = (
        _asset_pack_condition(),
        _unreadable_layer_condition(memory),
        _index_pressure_condition(memory),
        _event_log_condition(log),
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
_NO_JSON_UNWRAP = frozenset({"bantamkit_read"})


# `assets/tools/bantamkit_read.json` `offset.maximum` — Number.MAX_SAFE_INTEGER, the largest
# integer a JSON parser on the Node side reads back unchanged.
OFFSET_MAXIMUM = 9007199254740991


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

    def shiftwork_clock_in(checkpoint: str) -> dict[str, Any]:
        return _noted_dict(
            _record_result(log, "shiftwork_clock_in", lambda: shiftwork.clock_in(checkpoint))
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
            try:
                doc = docread.extract(path)
            except (docread.DocumentReadError, OSError) as exc:
                log.record("bantamkit_read", "refused-unreadable")
                return _noted(document_error(exc))
            detail: dict[str, Any] = {"kind": doc.kind, "parts": len(doc.parts)}
            if part is None:
                reply = document_manifest(
                    [
                        {
                            "document": path,
                            "kind": doc.kind,
                            "index": p.index,
                            "part": p.name,
                            "row_count": p.row_count,
                            "rows": p.rows,
                            "omissions": [o.as_dict() for o in p.omissions],
                        }
                        for p in doc.parts
                    ],
                    [{"document": path, "omissions": [o.as_dict() for o in doc.omissions]}]
                    if doc.omissions
                    else [],
                )
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
                return _noted(document_error(f'"{target.name}" in {path} has no rows'))
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

    # The served surface, in one place, read out of the asset pack. Adding a tool here
    # without an asset raises AssetNotFound at startup — the manifest cannot drift behind
    # the server, because the server cannot start without it.
    #
    # `bantamkit_status` went LAST rather than first, `memory_compact` after it rather
    # than beside `memory_save` where a reader would look for it, `bantamkit_read`
    # after that and `skill_audit` after that. Registration order IS the served order
    # (`test_tool_manifest.py::test_the_golden_records_the_order_the_wire_actually_
    # serves`), and appending is the only edit that leaves the others where every
    # existing declaration says they are.
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
        _from_manifest(bantamkit_read, "bantamkit_read"),
        _from_manifest(skill_audit, "skill_audit"),
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
    stores = parser.add_mutually_exclusive_group()
    stores.add_argument("--store", help="single memory store path (disables layering)")
    stores.add_argument(
        "--start", help="directory to start project-store discovery from (default: cwd)"
    )
    return parser.parse_args(argv)


def _build_memory(args: argparse.Namespace) -> Memory:
    if args.k < 1:
        raise SystemExit("--k must be >= 1")
    if args.index_budget < 1:
        raise SystemExit("--index-budget must be >= 1")
    if args.store is not None:
        if not args.store:
            raise SystemExit("--store requires a non-empty path")
        return Memory(store=args.store, k=args.k, index_budget=args.index_budget)
    return Memory.layered(start=args.start, k=args.k, index_budget=args.index_budget)


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


def main() -> None:
    if MCPServer is None:
        raise SystemExit(_INSTALL_HINT)
    args = _parse_args()
    # Before `_build_memory`, which touches the filesystem, and before the server exists at
    # all -- the Node arm returns from `main` here too, ahead of `new RawStdioTransport()`.
    if args.assets_root:
        _print_assets_root()
        return
    if args.mcp_report:
        _print_mcp_report(args)
        return
    if args.statusline:
        _print_status_line(args)
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
