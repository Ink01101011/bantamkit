"""The operator's half of the lifecycle position: `python -m bantamkit.memory`.

`docs/memory.md` states, as a design decision, that `lint`, `archived` and
`restore` are **not** agent tools — "lifecycle is an operator decision, not a
model decision" — and the thirteen-tool surface holds to it; `compact` is the one
exception since job42 (`memory_compact`, the on-refusal path the model reaches
itself). That position is only coherent if the operator can actually make the
decision. Measured
2026-08-21, they could not: `index_budget` appeared on no argument parser, and
the four lifecycle ops were reachable only by importing `MemoryStore` and calling
them from Python. A design that hands lifecycle to an operator and gives the
operator no lever is not a position, it is an omission.

Why a separate entry point rather than a flag on `bantamkit-mcp`: that process
speaks the MCP protocol over stdout, so anything a lifecycle report printed there
would corrupt the wire. Lifecycle needs a stream it owns. `python -m` is also the
invocation this repo already treats as the one a host reaches for when the
console script is not on PATH (see the `__main__` guard in `mcpserver.py`), and
it adds no packaging surface and no dependency.

Scope is deliberately the writable project layer only. `Memory.layered()` also
mounts read-only grants and the profile store, and `MemoryStore.compact()`
touches neither; resolving through `discover_project_store` keeps the CLI unable
to archive a store it does not own, rather than merely unlikely to.

Exit codes: 0 success, 1 an operational failure the operator must act on (over
budget, malformed fact, refused restore), 2 argparse usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bantamkit.client import BantamError
from bantamkit.memory.layers import discover_project_store
from bantamkit.memory.store import (
    DEFAULT_INDEX_BUDGET,
    MemoryBudgetExceeded,
    MemoryStore,
    MemoryValidationError,
)

#: The one place this CLI's own name is spelled, and `runtime-ts` has the same constant
#: under the same name (`PROG` in `src/memory/cli.ts`) holding `bantamkit-memory`. The
#: `memorycli` conformance suite compares the two CLIs after substituting one for the
#: other, so everything downstream of it -- the usage line, every `...: error:` prefix,
#: the sentence `main` prints for a store it could not read, and the two remediation
#: lines that name a command for the operator to RUN -- has to move with it or the two
#: halves drift apart one string at a time.
#:
#: One remediation line in this runtime is NOT downstream of this constant and cannot be
#: without the MCP server importing this module: the `index-budget-low` sentence in
#: `mcpserver.py` spells the same command as a literal. It is held to this value from the
#: outside instead, by `tests/test_status_surface.py`'s
#: `test_the_index_remedy_names_the_command_this_install_actually_provides`.
_PROG = "python -m bantamkit.memory"


def _lf_utf8(stream: object) -> None:
    """Make one of this process's text streams write LF and UTF-8 on every platform.

    `sys.stdout` and `sys.stderr` are text streams opened with `newline=None`, which
    translates every `\n` to `os.linesep` on the way out: a no-op on macOS and Linux, and
    CRLF on Windows. Their encoding is the locale's, which on Windows is a code page, not
    UTF-8. So the same command run on the same store printed different BYTES on Windows than
    it did here, and the port -- whose `process.stdout.write` emits LF and UTF-8 everywhere
    -- was byte-identical to this CLI on one operating system and not on the other.

    `mcpserver.py`'s `_print_assets_root`, `_print_mcp_report` and `_print_status_line` each
    solve their own half of this by writing through `sys.stdout.buffer`, and that is the
    established idiom in this repository. It CANNOT be the idiom here, and the reason is
    measured rather than assumed: on Windows' defaults, reproduced on macOS with
    `TextIOWrapper(..., encoding="cp1252", newline="\r\n")`, `-h` emits 16 CRLFs and
    `status --nope` emits 3 -- and every one of them is written by `argparse`, into
    `sys.stdout`/`sys.stderr` by name, from a frame no call site in this module owns. A sweep
    of the `print()` calls below would have fixed the 6 CRLFs of `status` and left the 16 of
    `-h`. The stream is the thing that translates, so the stream is the thing to fix.

    Guarded on `reconfigure` rather than on a type, because `sys.stdout` is not always a
    `TextIOWrapper`: `pytest`'s capture, a `StringIO` and a closed-stdout `pythonw` all reach
    this line, and a stream that cannot be reconfigured is one that was never doing platform
    translation in the first place.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", newline="\n")


def _positive(text: str) -> int:
    """A budget of 0 or less silently makes every save fail; refuse it at the edge."""
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=_PROG,
        description=(
            "Operator lifecycle for a bantamkit memory store: inspect, lint, "
            "compact, archive and restore. Not an agent surface."
        ),
    )
    subs = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser) -> argparse.ArgumentParser:
        stores = sub.add_mutually_exclusive_group()
        stores.add_argument("--store", help="memory store path (skips project discovery)")
        stores.add_argument(
            "--start", help="directory to start project-store discovery from (default: cwd)"
        )
        sub.add_argument(
            "--budget",
            type=_positive,
            default=DEFAULT_INDEX_BUDGET,
            metavar="BYTES",
            help=f"index byte budget (default: {DEFAULT_INDEX_BUDGET})",
        )
        return sub

    common(subs.add_parser("status", help="index size, budget, headroom, archive count"))
    common(subs.add_parser("lint", help="exit 1 if the store is malformed or over budget"))
    compact = common(subs.add_parser("compact", help="archive the stalest facts"))
    compact.add_argument(
        "--reserve",
        type=_positive,
        default=None,
        metavar="BYTES",
        help="headroom to leave below the budget (default: the largest index line kept)",
    )
    common(subs.add_parser("archived", help="list what compaction has moved out"))
    archive = common(subs.add_parser("archive", help="move one named fact out"))
    archive.add_argument("name", help="name of the fact to archive")
    restore = common(subs.add_parser("restore", help="move an archived fact back"))
    restore.add_argument("name", help="name of the archived fact")

    return parser.parse_args(argv)


def _open(args: argparse.Namespace) -> MemoryStore:
    if args.store is not None:
        if not args.store:
            raise SystemExit("--store requires a non-empty path")
        root = Path(args.store)
    else:
        root = discover_project_store(args.start)
    return MemoryStore(root, index_budget=args.budget)


def _size(store: MemoryStore) -> int:
    return len(store.index_text().encode())


def _cmd_status(store: MemoryStore, args: argparse.Namespace) -> int:
    size = _size(store)
    print(f"store: {store.root}")
    print(f"facts: {len(store._facts())}")
    print(f"index: {size} bytes")
    print(f"budget: {store.index_budget}")
    print(f"headroom: {store.index_budget - size}")
    print(f"archived: {len(store.archived())}")
    return 0


def _cmd_lint(store: MemoryStore, args: argparse.Namespace) -> int:
    try:
        store.lint()
    except MemoryBudgetExceeded:
        # Not the store's own message: that one names `compact()`, which is a Python
        # call and the wrong remedy to hand someone holding a shell.
        where = f"--store {store.root}"
        print(
            f"lint: FAIL — index is {_size(store)} bytes, budget is {store.index_budget}\n"
            f"  try: {_PROG} compact {where} "
            f"--budget {store.index_budget}",
            file=sys.stderr,
        )
        return 1
    except MemoryValidationError as e:
        print(f"lint: FAIL — {e}", file=sys.stderr)
        return 1
    print(f"lint: ok — {len(store._facts())} facts, {_size(store)}/{store.index_budget} bytes")
    return 0


def _cmd_compact(store: MemoryStore, args: argparse.Namespace) -> int:
    before = _size(store)
    result = store.compact(reserve=args.reserve)
    print(f"compacted {len(result.archived)} fact(s)")
    print(
        f"index: {before} -> {result.index_after} bytes "
        f"(budget {result.budget}, target {result.target}, "
        f"reserve {result.reserve}, headroom {result.headroom})"
    )
    if not result.archived:
        print("nothing to archive — the index is already at or below the target")
        return 0
    # `archive/` is on disk and nothing reads it back on its own, so the names have to
    # land here or the operator never learns what left.
    print(f"archived -> {result.archive_dir}")
    for fact in result.archived:
        print(f"  {fact.name} ({fact.type}, {fact.index_bytes} bytes)")
    print(f"restore one with: {_PROG} restore <name> --store {store.root}")
    return 0


def _cmd_archived(store: MemoryStore, args: argparse.Namespace) -> int:
    names = store.archived()
    print(f"archived facts: {len(names)} ({store.root / 'archive'})")
    for name in names:
        print(f"  {name}")
    return 0


def _cmd_archive(store: MemoryStore, args: argparse.Namespace) -> int:
    try:
        store.archive(args.name)
    except MemoryValidationError as e:
        print(f"archive failed: {e}", file=sys.stderr)
        return 1
    except OSError:
        # `roadmap-toolbox.md` row 8 (y): two entrances -- `archive/` refusing the write
        # and `index.md` being a directory -- used to let a raw `PermissionError` or
        # `IsADirectoryError` unwind through `main` as a CPython traceback. Both leave
        # `archive()` having changed nothing (the second via its own rollback), so this
        # sentence is true regardless of which OS exception reached it; see
        # `docs/porting.md:333-336` for the precedent this follows and why neither this
        # nor `restore`'s twin below is a `ruling:` case.
        print(
            f"archive failed: a filesystem error stopped the move of '{args.name}'; "
            f"nothing under {store.root} changed",
            file=sys.stderr,
        )
        return 1
    print(f"archived '{args.name}' — index now {_size(store)}/{store.index_budget} bytes")
    return 0


def _cmd_restore(store: MemoryStore, args: argparse.Namespace) -> int:
    try:
        store.restore(args.name)
    except MemoryBudgetExceeded:
        print(
            f"restore failed: '{args.name}' would put the index over the budget of "
            f"{store.index_budget} bytes. Nothing changed — raise --budget or compact first.",
            file=sys.stderr,
        )
        return 1
    except MemoryValidationError as e:
        print(f"restore failed: {e}", file=sys.stderr)
        return 1
    except OSError:
        # Same two entrances as `archive`'s catch above, mirrored on `restore`, plus the
        # dangling-symlink guard hole (z) also opens: `_facts()`'s pre-read reaches the
        # same `FileNotFoundError` one syscall before the guard's blind spot would ever
        # let the move run. All of them leave the store exactly as `restore` found it.
        print(
            f"restore failed: a filesystem error stopped the move of '{args.name}'; "
            f"nothing under {store.root} changed",
            file=sys.stderr,
        )
        return 1
    print(f"restored '{args.name}' — index now {_size(store)}/{store.index_budget} bytes")
    return 0


_COMMANDS = {
    "status": _cmd_status,
    "lint": _cmd_lint,
    "compact": _cmd_compact,
    "archived": _cmd_archived,
    "archive": _cmd_archive,
    "restore": _cmd_restore,
}


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand and return its exit code. The exit code is the ONLY channel.

    `status`, `compact` and `archived` catch nothing of their own -- there is no
    remediation to offer for a store that cannot be read, only a report -- so before
    this clause a `MemoryValidationError` out of `_listing` unwound all the way through
    CPython, which printed a two-stage traceback carrying interpreter absolute paths and
    line numbers from inside `store.py`. Exit 1 either way; the difference is entirely in
    what the operator is handed, and a stack trace names this repository's files rather
    than the store the operator asked about.

    `BantamError` and nothing wider, exactly as `runtime-ts/src/memory/cli.ts` has it: a
    bug in bantamkit is still a traceback, because that one IS a report for a maintainer.
    What is caught here is the class of failures that are ABOUT the operator's store --
    unreadable, unlistable, malformed -- and every one of them already carries a sentence
    that names the directory and says what the consequence would have been. The prefix is
    this CLI's own `prog`, so the line reads as the program speaking rather than as an
    error string from nowhere, and it is byte-identical to the port's after the one
    substitution the conformance suite makes.

    `SystemExit` is deliberately not caught: argparse's usage errors are exit 2 and
    `_open`'s empty-`--store` refusal is its own sentence already on stderr.
    """
    # BEFORE `_parse_args`, because `-h` and every usage error are written by argparse
    # straight into these two streams and never come back through this frame.
    _lf_utf8(sys.stdout)
    _lf_utf8(sys.stderr)
    args = _parse_args(argv)
    try:
        return _COMMANDS[args.command](_open(args), args)
    except BantamError as e:
        print(f"{_PROG}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
