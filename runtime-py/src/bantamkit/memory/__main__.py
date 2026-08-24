"""The operator's half of the lifecycle position: `python -m bantamkit.memory`.

`docs/memory.md` states, as a design decision, that `lint`, `compact`, `archived`
and `restore` are **not** agent tools — "lifecycle is an operator decision, not a
model decision" — and two nodes hold the seven-tool surface to it. That position
is only coherent if the operator can actually make the decision. Measured
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

from bantamkit.memory.layers import discover_project_store
from bantamkit.memory.store import (
    DEFAULT_INDEX_BUDGET,
    MemoryBudgetExceeded,
    MemoryStore,
    MemoryValidationError,
)


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
        prog="python -m bantamkit.memory",
        description=(
            "Operator lifecycle for a bantamkit memory store: inspect, lint, "
            "compact and restore. Not an agent surface."
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
            f"  try: python -m bantamkit.memory compact {where} "
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
    print(f"restore one with: python -m bantamkit.memory restore <name> --store {store.root}")
    return 0


def _cmd_archived(store: MemoryStore, args: argparse.Namespace) -> int:
    names = store.archived()
    print(f"archived facts: {len(names)} ({store.root / 'archive'})")
    for name in names:
        print(f"  {name}")
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
    print(f"restored '{args.name}' — index now {_size(store)}/{store.index_budget} bytes")
    return 0


_COMMANDS = {
    "status": _cmd_status,
    "lint": _cmd_lint,
    "compact": _cmd_compact,
    "archived": _cmd_archived,
    "restore": _cmd_restore,
}


def main(argv: list[str] | None = None) -> int:
    # BEFORE `_parse_args`, because `-h` and every usage error are written by argparse
    # straight into these two streams and never come back through this frame.
    _lf_utf8(sys.stdout)
    _lf_utf8(sys.stderr)
    args = _parse_args(argv)
    return _COMMANDS[args.command](_open(args), args)


if __name__ == "__main__":
    raise SystemExit(main())
