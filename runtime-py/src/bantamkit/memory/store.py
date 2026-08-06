"""Memory correctness layer: the agent never writes files directly — only these ops."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from bantamkit.client import BantamError

VALID_TYPES = {"user", "feedback", "project", "reference"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DUPLICATE_JACCARD = 0.5


class MemoryValidationError(BantamError):
    pass


class MemoryBudgetExceeded(BantamError):
    pass


@dataclass
class Fact:
    name: str
    description: str
    type: str
    body: str
    links: list[str]
    last_recalled: str | None


@dataclass
class SaveResult:
    status: str  # "saved" | "duplicate"
    name: str
    similar: str | None = None


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class MemoryStore:
    def __init__(
        self,
        root: str | Path,
        index_budget: int = 4096,
        k: int = 3,
        today: Callable[[], str] | None = None,
    ):
        self.root = Path(root)
        self.index_budget = index_budget
        self.k = k
        self._today = today or (lambda: date.today().isoformat())
        (self.root / "facts").mkdir(parents=True, exist_ok=True)
        (self.root / "archive").mkdir(parents=True, exist_ok=True)

    # ---- ops ----

    def save(
        self, type: str, name: str, description: str, body: str, links: tuple[str, ...] = ()
    ) -> SaveResult:
        if type not in VALID_TYPES:
            raise MemoryValidationError(
                f"invalid type '{type}'; must be one of {sorted(VALID_TYPES)}"
            )
        if not NAME_RE.match(name or ""):
            raise MemoryValidationError(f"invalid name '{name}'; must match {NAME_RE.pattern}")
        if not (description or "").strip():
            raise MemoryValidationError("description must be a non-empty line")

        new_tokens = _tokens(f"{name} {description}")
        for fact in self._facts():
            if fact.name == name:
                continue  # same name = update, not duplicate
            if (
                _jaccard(new_tokens, _tokens(f"{fact.name} {fact.description}"))
                >= DUPLICATE_JACCARD
            ):
                return SaveResult(status="duplicate", name=name, similar=fact.name)

        fact = Fact(
            name=name,
            description=description.strip(),
            type=type,
            body=body,
            links=list(links),
            last_recalled=None,
        )
        path = self._fact_path(name)
        existed = path.read_text() if path.exists() else None
        self._write_fact(fact)
        try:
            self._check_index_budget()
        except MemoryBudgetExceeded:
            if existed is None:
                path.unlink()
            else:
                path.write_text(existed)
            self._rebuild_index()
            raise
        self._rebuild_index()
        return SaveResult(status="saved", name=name)

    def recall(self, query: str, k: int | None = None) -> list[Fact]:
        k = k if k is not None else self.k
        q = _tokens(query)
        scored = []
        for fact in self._facts():
            score = len(q & _tokens(f"{fact.name} {fact.description}"))
            if score > 0:
                scored.append((score, fact))
        scored.sort(key=lambda pair: (-pair[0], pair[1].name))
        hits = [fact for _, fact in scored[:k]]
        for fact in hits:
            fact.last_recalled = self._today()
            self._write_fact(fact)
        return hits

    def lint(self) -> None:
        for fact in self._facts():  # raises MemoryValidationError on malformed frontmatter
            if fact.type not in VALID_TYPES:
                raise MemoryValidationError(f"fact '{fact.name}' has invalid type '{fact.type}'")
        self._check_index_budget()

    def compact(self) -> list[str]:
        # archive never/least-recently-recalled first until the index fits
        facts = sorted(self._facts(), key=lambda f: (f.last_recalled or "", f.name))
        archived: list[str] = []
        for fact in facts:
            try:
                self._check_index_budget()
                break
            except MemoryBudgetExceeded:
                path = self._fact_path(fact.name)
                path.rename(self.root / "archive" / path.name)
                archived.append(fact.name)
        self._check_index_budget()
        self._rebuild_index()
        return archived

    def index_text(self) -> str:
        return "".join(f"- [[{f.name}]] ({f.type}) — {f.description}\n" for f in self._facts())

    # ---- internals ----

    def _fact_path(self, name: str) -> Path:
        return self.root / "facts" / f"{name}.md"

    def _facts(self) -> list[Fact]:
        facts = []
        for path in sorted((self.root / "facts").glob("*.md")):
            text = path.read_text()
            try:
                _, front, body = text.split("---\n", 2)
                meta = yaml.safe_load(front)
                if not isinstance(meta, dict):
                    raise MemoryValidationError(
                        f"malformed fact file {path.name}: frontmatter is not a mapping"
                    )
                facts.append(
                    Fact(
                        name=meta["name"],
                        description=meta["description"],
                        type=meta["type"],
                        body=body.strip(),
                        links=list(meta.get("links") or []),
                        last_recalled=meta.get("last_recalled"),
                    )
                )
            except (ValueError, KeyError, yaml.YAMLError) as e:
                raise MemoryValidationError(f"malformed fact file {path.name}: {e}") from e
        return facts

    def _write_fact(self, fact: Fact) -> None:
        meta = {
            "name": fact.name,
            "description": fact.description,
            "type": fact.type,
            "last_recalled": fact.last_recalled,
            "links": fact.links,
        }
        text = (
            "---\n"
            + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
            + "---\n\n"
            + fact.body.strip()
            + "\n"
        )
        path = self._fact_path(fact.name)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(text)
        tmp.replace(path)

    def _rebuild_index(self) -> None:
        (self.root / "index.md").write_text(self.index_text())

    def _check_index_budget(self) -> None:
        size = len(self.index_text().encode())
        if size > self.index_budget:
            raise MemoryBudgetExceeded(
                f"memory index is {size} bytes, budget is {self.index_budget}: "
                f"run compact() or tersen descriptions"
            )
