"""Deterministic ledger of file reads: which paths, via which tool, and whether they changed."""

from __future__ import annotations

import hashlib
import json
import posixpath
from dataclasses import asdict, dataclass
from pathlib import Path

from bantamkit.agent import Agent, ToolDef
from bantamkit.assets import load_skill, load_tool
from bantamkit.textutil import truncate


@dataclass
class FileRead:
    path: str
    tool: str
    digest: str
    count: int = 1
    changed: bool = False


@dataclass
class ReadAccounting:
    """Per-run counters for the read ledger, so a run can report what the ledger saw.

    One instance per `FileAccessGraph`, and the graph is constructed once per run, so
    the grain is per run by construction. Every byte field is measured AFTER the loop's
    own truncation (see `FileAccessGraph._context_len`): these count bytes that reach
    the transcript, not bytes a handler happened to hold.

    `reader_calls` counts every invocation of a wrapped reader, including the ones the
    ledger cannot see; `unrecorded_reader_calls` is exactly that carve-out — the path
    argument was absent, or the observation carried the harness-wide `error:` failure
    convention, both of which return before `_record` runs. So `reader_calls` is the
    honest attempt count and `recorded_reader_calls` is the one that reconciles with
    `reads`: `recorded_reader_calls == sum(r.count for r in reads.values())`. A rate
    whose numerator comes from the ledger (`repeat_reader_calls`, `collapsed_calls`)
    must use `recorded_reader_calls` as its denominator.
    """

    reader_calls: int = 0
    unrecorded_reader_calls: int = 0
    repeat_reader_calls: int = 0
    collapsed_calls: int = 0
    # SIGNED. `collapsed_bytes` is bytes-removed-minus-bytes-added, so it goes negative
    # when the marker is longer than the observation it replaced; `annotate_marker_bytes`
    # is bytes-added. Neither is clamped: a floor at zero would report a cost as a
    # break-even and bias the run total in the mechanism's favour.
    collapsed_bytes: int = 0
    annotate_marker_bytes: int = 0
    # `query`'s cost splits into a per-request constant (the tool schema in every
    # request plus the skill in the system prompt, counted once here — multiply by the
    # run's model-call count for the re-send-weighted figure) and the observations the
    # `file_graph` tool actually returned. Kept apart because they are weighted
    # differently; `query_bytes` is their sum and is what a run reports.
    query_setup_bytes: int = 0
    query_render_bytes: int = 0

    @property
    def recorded_reader_calls(self) -> int:
        return self.reader_calls - self.unrecorded_reader_calls

    @property
    def query_bytes(self) -> int:
        return self.query_setup_bytes + self.query_render_bytes


class FileAccessGraph:
    """Records every declared file-read tool call; annotates repeats, collapses
    unchanged repeats to a short marker (verify-on-repeat), and exposes the map
    as a `file_graph` tool. The write path never involves a model."""

    def __init__(
        self,
        readers: dict[str, str] | None = None,
        annotate: bool = True,
        cache: bool = True,
        query: bool = True,
    ):
        self.readers = dict(readers or {})
        self.annotate = annotate
        self.cache = cache
        self.query = query
        self.reads: dict[str, FileRead] = {}
        self.accounting = ReadAccounting()
        # Learned from the agent at `setup`. `None` means "no budget known", in which
        # case the byte columns fall back to the untruncated length.
        self.observation_budget: int | None = None

    def _context_len(self, text: str) -> int:
        """Bytes `text` occupies in the transcript, i.e. after the loop truncates it.

        The loop applies `truncate(..., observation_budget)` to whatever this component
        returns (`agent.py:198`), so the raw length of an observation is NOT the number
        of bytes it costs the context, and the difference of two raw lengths is not the
        number of bytes a collapse removed. Above the budget the marker's saving is
        capped at the budget; below it the two agree exactly.
        """
        if self.observation_budget is None:
            return len(text.encode())
        return len(truncate(text, self.observation_budget).encode())

    def setup(self, agent: Agent) -> None:
        # Read before anything is wrapped: the accounting must know the budget the loop
        # will apply after this component returns, or every byte column overstates.
        self.observation_budget = agent.observation_budget
        agent.tools[:] = [self._wrap(td) for td in agent.tools]
        original = agent.register_tool

        def register_and_wrap(tooldef: ToolDef) -> None:
            original(self._wrap(tooldef))

        # Instance-level override so readers registered after use(graph) are still wrapped.
        agent.register_tool = register_and_wrap
        if self.query:
            tool = load_tool("file_graph")
            skill = load_skill("file-graph")
            agent.register_tool(ToolDef(tool=tool, handler=self.render))
            agent.add_system(skill)
            self.accounting.query_setup_bytes = len(json.dumps(tool.to_wire()).encode()) + len(
                skill.encode()
            )

    def _wrap(self, tooldef: ToolDef) -> ToolDef:
        path_arg = self.readers.get(tooldef.tool.name)
        if path_arg is None:
            return tooldef
        inner, tool_name = tooldef.handler, tooldef.tool.name

        def handler(**kwargs):
            self.accounting.reader_calls += 1
            observation = str(inner(**kwargs))
            raw = kwargs.get(path_arg)
            # `error:` is the harness-wide failure convention (Agent._dispatch emits it too),
            # so genuine file content starting with "error:" is invisible to the ledger.
            # Counted rather than dropped: a run that asks ten times for a path that does
            # not exist records zero reads, and a denominator that hides that is a lie.
            if raw is None or observation.startswith("error:"):
                self.accounting.unrecorded_reader_calls += 1
                return observation
            return self._record(tool_name, posixpath.normpath(str(raw)), observation)

        return ToolDef(tool=tooldef.tool, handler=handler)

    def _record(self, tool: str, path: str, observation: str) -> str:
        digest = hashlib.sha256(observation.encode()).hexdigest()
        prior = self.reads.get(path)
        if prior is None:
            self.reads[path] = FileRead(path=path, tool=tool, digest=digest)
            return observation
        prior.count += 1
        self.accounting.repeat_reader_calls += 1
        prior.tool = tool
        unchanged = prior.digest == digest
        prior.changed = prior.changed or not unchanged
        prior.digest = digest
        if unchanged and self.cache:
            size = len(observation.encode())
            marker = (
                f"[file-graph] {path} unchanged since your last read — "
                f"{size} bytes not repeated (read #{prior.count} via {tool})"
            )
            # `size` above is the model-facing wording and stays as it is. The COLUMN is
            # measured differently on purpose: it is what the transcript stops carrying,
            # marker included and truncation applied, so it never overstates the saving
            # on an observation the loop would have cut down anyway.
            #
            # SIGNED, and not clamped at zero: this marker runs about 100 bytes (98 for a
            # path like `a.txt`, 103 for `notes/a.md`), so collapsing a file smaller than
            # that ADDS bytes to the transcript. A column that floored
            # the difference at 0 would report a saving of zero where the truth is a
            # cost, and the sum over a run would be biased upward by exactly the cases
            # the mechanism handles worst.
            self.accounting.collapsed_calls += 1
            self.accounting.collapsed_bytes += self._context_len(observation) - self._context_len(
                marker
            )
            return marker
        if self.annotate:
            note = "unchanged since your last read" if unchanged else "CHANGED since your last read"
            annotated = (
                f"[file-graph] read #{prior.count} of {path} via {tool} — {note}\n{observation}"
            )
            # Signed for the same reason, though from the other side: the prefix is pure
            # addition below the budget, and above it the loop's truncation can eat part
            # of the observation instead, which is a content loss the byte count would
            # otherwise report as free.
            self.accounting.annotate_marker_bytes += self._context_len(
                annotated
            ) - self._context_len(observation)
            return annotated
        return observation

    def render(self) -> str:
        if not self.reads:
            rendered = "no files read yet"
        else:
            rendered = "\n".join(
                f"{r.path} — {r.count} read(s) via {r.tool}, "
                f"{'changed' if r.changed else 'unchanged'}"
                for r in self.reads.values()
            )
        self.accounting.query_render_bytes += self._context_len(rendered)
        return rendered

    def save(self, path: str | Path) -> None:
        payload = json.dumps([asdict(r) for r in self.reads.values()])
        Path(path).write_text(payload, encoding="utf-8")

    def load(self, path: str | Path) -> None:
        """Restore a saved ledger. Precondition: only resume a ledger together with the
        transcript it was built against — restored entries collapse repeat reads to markers,
        which a model that never saw the original content cannot act on."""
        for entry in json.loads(Path(path).read_text(encoding="utf-8")):
            self.reads[entry["path"]] = FileRead(**entry)
