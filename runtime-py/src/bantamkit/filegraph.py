"""Deterministic ledger of file reads: which paths, via which tool, and whether they changed."""

from __future__ import annotations

import hashlib
import json
import posixpath
from dataclasses import asdict, dataclass
from pathlib import Path

from bantamkit.agent import Agent, ToolDef
from bantamkit.assets import load_skill, load_tool


@dataclass
class FileRead:
    path: str
    tool: str
    digest: str
    count: int = 1
    changed: bool = False


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

    def setup(self, agent: Agent) -> None:
        agent.tools[:] = [self._wrap(td) for td in agent.tools]
        original = agent.register_tool

        def register_and_wrap(tooldef: ToolDef) -> None:
            original(self._wrap(tooldef))

        # Instance-level override so readers registered after use(graph) are still wrapped.
        agent.register_tool = register_and_wrap
        if self.query:
            agent.register_tool(ToolDef(tool=load_tool("file_graph"), handler=self.render))
            agent.add_system(load_skill("file-graph"))

    def _wrap(self, tooldef: ToolDef) -> ToolDef:
        path_arg = self.readers.get(tooldef.tool.name)
        if path_arg is None:
            return tooldef
        inner, tool_name = tooldef.handler, tooldef.tool.name

        def handler(**kwargs):
            observation = str(inner(**kwargs))
            raw = kwargs.get(path_arg)
            # `error:` is the harness-wide failure convention (Agent._dispatch emits it too),
            # so genuine file content starting with "error:" is invisible to the ledger.
            if raw is None or observation.startswith("error:"):
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
        prior.tool = tool
        unchanged = prior.digest == digest
        prior.changed = prior.changed or not unchanged
        prior.digest = digest
        if unchanged and self.cache:
            size = len(observation.encode())
            return (
                f"[file-graph] {path} unchanged since your last read — "
                f"{size} bytes not repeated (read #{prior.count} via {tool})"
            )
        if self.annotate:
            note = "unchanged since your last read" if unchanged else "CHANGED since your last read"
            return f"[file-graph] read #{prior.count} of {path} via {tool} — {note}\n{observation}"
        return observation

    def render(self) -> str:
        if not self.reads:
            return "no files read yet"
        return "\n".join(
            f"{r.path} — {r.count} read(s) via {r.tool}, {'changed' if r.changed else 'unchanged'}"
            for r in self.reads.values()
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps([asdict(r) for r in self.reads.values()]))

    def load(self, path: str | Path) -> None:
        """Restore a saved ledger. Precondition: only resume a ledger together with the
        transcript it was built against — restored entries collapse repeat reads to markers,
        which a model that never saw the original content cannot act on."""
        for entry in json.loads(Path(path).read_text()):
            self.reads[entry["path"]] = FileRead(**entry)
