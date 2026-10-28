"""The skill drafter (#206 Task 6): bundle, prompt, gate, and the X5 chain.

A cluster in `skill-proposals.json` becomes a SKILL.md draft here, and a draft is kept only
if it passes the GATE. Nothing in this module installs anything: the installer (Task 7)
takes a passing draft from here.

THE BUNDLE is built from the proposals record alone (`bundle`), so X4 holds by construction:
the miner never put a tool result into the record, and the bundle copies only named fields
of it (ids, the user's prompt cut to `EVIDENCE_PROMPT_CHARS` code points, tool names, paths,
the signal booleans, the pitfall notes). A key the record grows later does not leak into a
prompt, because nothing here copies a record whole.

THE PROMPT is two fixed constants (`DRAFT_SYSTEM`, `DRAFT_INSTRUCTIONS`) plus the bundle as
indented, key-sorted JSON. The two runtimes send the same bytes; the `skill-draft`
conformance suite pins them per side by hash.

THE GATE (`gate`) lists every reason, in a fixed order:
  1. `skillfile.parse_skill`'s refusal (then nothing else can be judged), or every
     `skillfile.validate` sentence;
  2. `a skill named <repr> already exists at <path>`, for each skills root that holds the name
     (the host's project and user roots, then bantamkit's project and user roots);
  3. `trigger phrase <repr> is shared with <skill>`, through #205's `audit_roots(check="phrase")`
     over the gatherer's roots, bantamkit's skills roots and a temp root holding the draft;
  4. per `## Steps` item, `step <n> cites no evidence id` or
     `step <n> cites <id>, which is not in the evidence`.

THE X5 CHAIN (`draft`) walks its drafters in order. A drafter that cannot be reached (a
transport or API error, sampling refused, no sampling capability, no answer text) is listed
in `unreachable` and passed over. The FIRST drafter that answers ends the walk, whether its
draft passes the gate or fails it (plan reading R11: a failed draft is discarded and logged,
it does not fall through). The host agent never drafts: it ends the walk with the
instructions, the bundle and the target root for the agent to write with its own tools.
Every walk is one line in `<home>/.bantamkit/skill-drafts.jsonl`: never the draft text,
never the bundle.

`runtime-ts/src/skilldraft.ts` is the port (async where the client is).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bantamkit.skillaudit import KIND_SHARED_PHRASE, audit_roots
from bantamkit.skillfile import (
    SKILL_FILE,
    SkillDoc,
    SkillFileError,
    parse_skill,
    project_skills_root,
    render,
    skills_root,
    validate,
)
from bantamkit.skillhost import select_adapter
from bantamkit.storage.logsegment import LogSegment

EVIDENCE_PROMPT_CHARS = 500
DRAFTS_LOG = "skill-drafts.jsonl"
LLM_URL_ENV = "BANTAMKIT_LLM_URL"
LLM_MODEL_ENV = "BANTAMKIT_LLM_MODEL"
DRAFTER_SAMPLING = "sampling"
DRAFTER_HOST = "host agent"
DRAFTER_ENDPOINT = "endpoint"

#: The directory the draft is audited under. A leading hyphen is not a valid skill name, so
#: no installed skill can hold it and the audit's bare-name dedupe can never drop the draft.
DRAFT_DIR = "-draft"

#: `gather` scans the host's transcripts for usage counts the gate does not need. A "now" so
#: far ahead puts every transcript before the cutoff, so that walk stats files and reads none.
_NO_USAGE_MS = 2**53 - 1

DRAFT_SYSTEM = (
    "You turn evidence of repeated, successful work into one Agent Skill. "
    "You answer with the text of one SKILL.md file and nothing else."
)

DRAFT_INSTRUCTIONS = """\
Write one SKILL.md in the Agent Skills format (agentskills.io/specification) for the work in
the evidence bundle below. The bundle holds a user's own requests, the tools used in order,
the files touched, and whether each piece of work succeeded.

The format:
- Start with a frontmatter block between two lines of three hyphens, holding exactly two keys,
  name and description. Leave metadata out: bantamkit adds it.
- name: 1-64 characters of a-z, 0-9 and single inner hyphens, in action or gerund form, for
  example fixing-windows-encoding. Never a generic word such as helper or utils.
- description: at most 1024 characters, third person. What the skill does in half a
  sentence, then Use when... with the words a user would type. No steps in the description:
  an agent that reads a workflow there follows it and skips the body.
- The body after the frontmatter is at most 500 lines, with these four sections in this order:
  ## When to use
  ## Steps
  ## Pitfalls
  ## Example
- ## Steps is a numbered list. Every step cites at least one evidence id from the bundle in
  square brackets, for example [job72/C3] or [s1a2b3c4#2].
- ## Pitfalls names the mistakes in the bundle's pitfalls, each citing its evidence id.
- Use only what the bundle holds. Never invent an evidence id, a file or a command.

Answer with the SKILL.md text only: no preamble, no explanation, no code fence around it."""

_LONE_SURROGATE = re.compile("[\ud800-\udfff]")
# Python's `\s` and JavaScript's differ; the two runtimes spell the same explicit set.
_ITEM = re.compile(r"[ \t]{0,3}(?:[-*+]|[0-9]{1,9}[.)])(?:[ \t]|$)")
_CITE = re.compile(r"\[([^\[\] \t\r\n\f\v]+)\](?!\()")
_HEADING_BREAK = re.compile(r"#{1,2}(?:[ \t]|$)")
_FENCE_OPEN = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\n")
_EDGE_WS = " \t\r\n"
#: `skillfile`'s name rule: only a name that is one is looked up as a directory.
_SAFE_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


# --------------------------------------------------------------------------------- bundle


def _clean(s: str) -> str:
    """A lone surrogate becomes U+FFFD, so the prompt encodes as UTF-8 on both runtimes."""
    return _LONE_SURROGATE.sub("\ufffd", s)


def _str(v: Any) -> str:
    return _clean(v) if isinstance(v, str) else ""


def _strs(v: Any) -> list[str]:
    return [_clean(x) for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _signals(v: Any) -> dict[str, bool]:
    if not isinstance(v, dict):
        return {}
    return {_clean(k): v[k] for k in sorted(v) if isinstance(k, str) and isinstance(v[k], bool)}


def bundle(cluster: Mapping[str, Any]) -> dict[str, Any]:
    """The evidence bundle for one proposals record, built from named fields only (X4)."""
    evidence = []
    for e in cluster.get("evidence") or []:
        if not isinstance(e, dict):
            continue
        evidence.append(
            {
                "id": _str(e.get("id")),
                "paths": _strs(e.get("paths")),
                "prompt": _clean(_str(e.get("prompt"))[:EVIDENCE_PROMPT_CHARS]),
                "signals": _signals(e.get("signals")),
                "tools": _strs(e.get("tools")),
            }
        )
    pitfalls = []
    for p in cluster.get("pitfalls") or []:
        if isinstance(p, dict):
            failure = p.get("failure")
            failure = _clean(failure) if isinstance(failure, str) else None
            pitfalls.append({"failure": failure, "id": _str(p.get("id"))})
    return {
        "cluster": _str(cluster.get("id")),
        "evidence": evidence,
        "keywords": _strs(cluster.get("keywords")),
        "level": _str(cluster.get("level")),
        "pitfalls": pitfalls,
        "steps": _strs(cluster.get("steps")),
    }


def bundle_json(b: Mapping[str, Any]) -> str:
    return json.dumps(b, ensure_ascii=False, indent=2, sort_keys=True)


def prompt(b: Mapping[str, Any]) -> tuple[str, str]:
    """`(system, user)`: the exact two messages every drafter that drafts is sent."""
    user = f"{DRAFT_INSTRUCTIONS}\n\nThe evidence bundle:\n\n```json\n{bundle_json(b)}\n```\n"
    return DRAFT_SYSTEM, user


def evidence_ids(b: Mapping[str, Any]) -> set[str]:
    ids = {e["id"] for e in b.get("evidence", []) if isinstance(e, dict)}
    ids |= {p["id"] for p in b.get("pitfalls", []) if isinstance(p, dict)}
    ids.discard("")
    return ids


def unfence(answer: str) -> str:
    """The answer with surrounding blank space cut, and one code fence around it all removed."""
    text = _clean(answer).replace("\r\n", "\n").strip(_EDGE_WS)
    m = _FENCE_OPEN.match(text)
    if m is not None and text.endswith("\n```"):
        text = text[m.end() : -len("\n```")].strip(_EDGE_WS)
    return text


# ----------------------------------------------------------------------------------- gate


@dataclass(frozen=True)
class GateResult:
    ok: bool
    reasons: list[str]
    doc: SkillDoc | None


def _steps(body: str) -> list[str]:
    """The `## Steps` items: list items, or every non-blank line when there is no list."""
    lines = body.split("\n")
    section: list[str] | None = None
    for i, line in enumerate(lines):
        if line.rstrip(" \t") == "## Steps":
            section = []
            for nxt in lines[i + 1 :]:
                if _HEADING_BREAK.match(nxt):
                    break
                section.append(nxt)
            break
    if not section:
        return []
    items: list[str] = []
    started = False
    for line in section:
        if _ITEM.match(line):
            items.append(line)
            started = True
        elif started:
            items[-1] += "\n" + line
    if items:
        return items
    return [line for line in section if line.strip(" \t")]


def _citations(body: str, ids: set[str]) -> list[str]:
    out: list[str] = []
    for n, item in enumerate(_steps(body), start=1):
        cited: list[str] = []
        for m in _CITE.finditer(item):
            if m.group(1) not in cited:
                cited.append(m.group(1))
        if not cited:
            out.append(f"step {n} cites no evidence id")
            continue
        out.extend(
            f"step {n} cites {c}, which is not in the evidence" for c in cited if c not in ids
        )
    return out


def _real(p: str) -> str:
    return os.path.realpath(p)


def _bantamkit_roots(home: str | Path, cwd: str | None) -> list[tuple[str, str]]:
    """`[(label, path)]` of bantamkit's own skills roots: the project's, then the user's."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    candidates = []
    if cwd is not None:
        candidates.append(("bantamkit-project", str(project_skills_root(cwd))))
    candidates.append(("bantamkit-user", str(skills_root(home))))
    for label, p in candidates:
        if _real(p) in seen:
            continue
        seen.add(_real(p))
        out.append((label, p))
    return out


def _collisions(
    name: str,
    host_roots: Sequence[tuple[str, str]],
    own: Sequence[tuple[str, str]],
    itself: str | None = None,
) -> list[str]:
    if _SAFE_NAME.fullmatch(name) is None:
        return []  # validate names it; a name that is not one is no path to look up
    out = []
    for label, root in [*host_roots, *own]:
        if label == "plugins":
            continue  # a plugin skill is namespaced `<plugin>:<name>`; it never collides
        target = os.path.join(root, name)
        if itself is not None and _real(target) == itself:
            continue  # the skill being improved, or a link that resolves to it
        if os.path.lexists(target):
            out.append(f"a skill named {name!r} already exists at {target}")
    return out


def _shared(
    doc: SkillDoc, roots: list[tuple[str, str]], gathered: Any, itself: str | None = None
) -> list[str]:
    tmp = tempfile.mkdtemp(prefix="bantamkit-draft-")
    try:
        d = os.path.join(tmp, DRAFT_DIR)
        os.mkdir(d)
        # What the installer would write (`render`), so a key the X9 shape drops (a `router:`
        # line, say) cannot take the draft out of the phrase index.
        text = _clean(render(SkillDoc(doc.name, doc.description, {}, "")))
        with open(os.path.join(d, SKILL_FILE), "wb") as fh:
            fh.write(text.encode("utf-8"))
        result = audit_roots(
            [*roots, ("draft", tmp)],
            enabled=list(gathered.enabled),
            check="phrase",
            versions=gathered.versions,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = []
    for f in result.findings:
        if f.kind != KIND_SHARED_PHRASE or DRAFT_DIR not in f.skills:
            continue
        out.extend(
            f"trigger phrase {f.detail!r} is shared with {s}"
            for s in f.skills
            if s != DRAFT_DIR and s != itself
        )
    return out


def gate(
    text: str,
    b: Mapping[str, Any],
    home: str | Path,
    cwd: str | None,
    own: str | Path | None = None,
) -> GateResult:
    """Every reason `text` may not be kept, in the fixed order; `ok` when there is none.

    `own` is the directory of the installed skill `text` would become a new version of
    (Task 10a): that skill is not a collision with itself (nor is a link resolving to it), and
    its own trigger phrases, or a skill directory of its name, are not shared with it.
    """
    # A lone surrogate is U+FFFD before any reader sees it: PyYAML refuses one raw and the
    # port's reader takes it, so a raw one would be a different verdict per runtime.
    text = _clean(text)
    try:
        doc = parse_skill(text)
    except SkillFileError as e:
        return GateResult(False, [str(e)], None)
    reasons = validate(doc)
    gathered = select_adapter(home).gather(home, cwd, _NO_USAGE_MS)
    host_roots = list(gathered.roots)
    own_roots = _bantamkit_roots(home, cwd)
    itself = _real(str(own)) if own is not None else None
    reasons += _collisions(doc.name, host_roots, own_roots, itself)
    audit = host_roots + [(label, p) for label, p in own_roots if os.path.isdir(p)]
    reasons += _shared(doc, audit, gathered, os.path.basename(itself) if itself else None)
    reasons += _citations(doc.body, evidence_ids(b))
    return GateResult(not reasons, reasons, doc)


# ------------------------------------------------------------------------------- drafters


class Unreachable(Exception):
    """The drafter could not be asked, or gave no answer text."""


class SamplingDrafter:
    """MCP sampling, inside the server only. `send(system, user)` returns the answer text;
    `None` means the client did not declare the `sampling` capability."""

    label = DRAFTER_SAMPLING

    def __init__(self, send: Callable[[str, str], str] | None) -> None:
        self.send = send

    def ask(self, system: str, user: str) -> str:
        if self.send is None:
            raise Unreachable("the client did not declare sampling")
        answer = self.send(system, user)
        if not isinstance(answer, str):
            raise Unreachable("sampling gave no text")
        return answer


def endpoint_config() -> tuple[str, str] | None:
    """`(url, model)` when `BANTAMKIT_LLM_URL` and `BANTAMKIT_LLM_MODEL` are both set."""
    url = os.environ.get(LLM_URL_ENV, "").strip(_EDGE_WS)
    model = os.environ.get(LLM_MODEL_ENV, "").strip(_EDGE_WS)
    return (url, model) if url and model else None


class EndpointDrafter:
    """A configured OpenAI-compatible endpoint (`client.OpenAICompatible`)."""

    def __init__(
        self,
        url: str | None = None,
        model: str | None = None,
        *,
        max_retries: int = 3,
        transport: Any = None,
    ) -> None:
        if url is None or model is None:
            cfg = endpoint_config()
            url, model = cfg if cfg is not None else ("", "")
        self.url = url
        self.model = model
        self.max_retries = max_retries
        self.transport = transport

    @property
    def label(self) -> str:
        return f"{DRAFTER_ENDPOINT} {self.model}"

    def ask(self, system: str, user: str) -> str:
        from bantamkit.client import Message, OpenAICompatible

        if not self.url or not self.model:
            raise Unreachable("no endpoint is configured")
        with OpenAICompatible(
            self.url, self.model, max_retries=self.max_retries, transport=self.transport
        ) as c:
            messages = [Message(role="system", content=system), Message(role="user", content=user)]
            r = c.chat(messages)
        if not isinstance(r.message.content, str):
            raise Unreachable("the endpoint gave no text")
        return r.message.content


class HostAgentDrafter:
    """Never drafts. Ends the walk with what the host agent needs to draft it itself."""

    label = DRAFTER_HOST


def target_root(cluster: Mapping[str, Any], home: str | Path) -> str:
    """Where the skill goes (X3/X7): the project's `.bantamkit/skills` for a project-level
    cluster with a known top, else the user's."""
    top = cluster.get("top")
    if cluster.get("level") == "project" and isinstance(top, str) and top:
        return str(project_skills_root(top))
    return str(skills_root(home))


def default_chain(
    send: Callable[[str, str], str] | None = None, host_agent: bool = True
) -> list[Any]:
    """Sampling when the client declared it, the endpoint when configured, then the host agent."""
    chain: list[Any] = []
    if send is not None:
        chain.append(SamplingDrafter(send))
    if endpoint_config() is not None:
        chain.append(EndpointDrafter())
    if host_agent:
        chain.append(HostAgentDrafter())
    return chain


def active_drafter(sampling: bool) -> str:
    """`sampling` | `endpoint <model>` | `host agent`, for the status line."""
    if sampling:
        return DRAFTER_SAMPLING
    cfg = endpoint_config()
    return f"{DRAFTER_ENDPOINT} {cfg[1]}" if cfg is not None else DRAFTER_HOST


# ---------------------------------------------------------------------------------- draft


@dataclass(frozen=True)
class DraftOutcome:
    drafter: str | None
    ok: bool
    text: str | None
    reasons: list[str]
    unreachable: list[str]
    #: The host agent's hand-off: `{instructions, bundle, target}`. None for every other end.
    handoff: dict[str, Any] | None = field(default=None)

    def log_line(self, ts: str, cluster: str) -> dict[str, Any]:
        return {
            "ts": ts,
            "cluster": cluster,
            "drafter": self.drafter,
            "ok": self.ok,
            "reasons": list(self.reasons),
            "unreachable": list(self.unreachable),
        }


def drafts_log(home: str | Path) -> Path:
    return Path(home) / ".bantamkit" / DRAFTS_LOG


def draft(
    cluster: Mapping[str, Any],
    chain: Sequence[Any],
    home: str | Path,
    cwd: str | None,
    now: str,
) -> DraftOutcome:
    """Walk `chain` for one proposals record; log the outcome; never write a skill."""
    b = bundle(cluster)
    system, user = prompt(b)
    unreachable: list[str] = []
    outcome: DraftOutcome | None = None
    for d in chain:
        if isinstance(d, HostAgentDrafter):
            handoff = {
                "bundle": b,
                "instructions": DRAFT_INSTRUCTIONS,
                "target": target_root(cluster, home),
            }
            outcome = DraftOutcome(d.label, False, None, [], unreachable, handoff)
            break
        try:
            answer = d.ask(system, user)
        except Exception:  # noqa: BLE001 — every failure to answer is "unreachable" (R11)
            unreachable.append(d.label)
            continue
        text = unfence(answer)
        g = gate(text, b, home, cwd)
        outcome = DraftOutcome(d.label, g.ok, text if g.ok else None, g.reasons, unreachable)
        break
    if outcome is None:
        outcome = DraftOutcome(None, False, None, [], unreachable)
    LogSegment(drafts_log(home)).append(outcome.log_line(now, b["cluster"]))
    return outcome


def prompt_sha256(b: Mapping[str, Any]) -> str:
    """SHA-256 of the UTF-8 system message, a NUL, and the user message: the per-side literal."""
    system, user = prompt(b)
    return hashlib.sha256(f"{system}\0{user}".encode()).hexdigest()


# ---------------------------------------------------------------- improvement (Task 10b)
#
# A drafter tunes a live skill's DESCRIPTION only (X10's low-risk edits): it is sent the skill
# as it stands, the counts behind the tune and the X4 bundle, and only the description of its
# answer is kept (`splice_description`), spliced into the skill bantamkit already holds, so a
# drafter can never change a step, a pitfall or a metadata key. The result passes the same gate
# as a new skill (with `own`, so the skill does not collide with itself).

TUNE_NARROW = "narrow"
TUNE_WIDEN = "widen"
TUNE_KINDS = (TUNE_NARROW, TUNE_WIDEN)

IMPROVE_SYSTEM = (
    "You improve the description of one Agent Skill from evidence of how it was used. "
    "You answer with the text of one SKILL.md file and nothing else."
)

IMPROVE_NARROW = (
    "The skill below was put in front of sessions that did not use it: its description matches "
    "requests it does not serve. Rewrite its description so it names the work in the evidence "
    "more precisely, and drop the words that drew the other requests."
)

IMPROVE_WIDEN = (
    "Work the skill below covers was done without it: its description missed those requests. "
    "Rewrite its description so it also matches the words of the requests in the evidence."
)

IMPROVE_TAIL = (
    "Change only the description. Keep the name, the metadata and the body exactly as they are. "
    "The description stays at most 1024 characters, third person, ending with Use when... and "
    "no steps. Answer with the whole SKILL.md text only: no preamble, no explanation, no code "
    "fence around it."
)


def improve_bundle(
    cluster: Mapping[str, Any] | None, cluster_id: str, ids: Sequence[str]
) -> dict[str, Any]:
    """The bundle an improvement is gated and drafted against: the cluster's record when the
    proposals file still holds it, plus an empty entry for every id the skill already cites
    (`ids`), so a step that cited a piece now out of the miner's window still passes."""
    if cluster is not None:
        b = bundle(cluster)
    else:
        b = {
            "cluster": _clean(cluster_id),
            "evidence": [],
            "keywords": [],
            "level": "",
            "pitfalls": [],
            "steps": [],
        }
    have = evidence_ids(b)
    for i in ids:
        if isinstance(i, str) and i and _clean(i) not in have:
            have.add(_clean(i))
            b["evidence"].append(
                {"id": _clean(i), "paths": [], "prompt": "", "signals": {}, "tools": []}
            )
    return b


def improve_prompt(
    kinds: Sequence[str], skill_text: str, b: Mapping[str, Any], counts: Mapping[str, int]
) -> tuple[str, str]:
    """`(system, user)` for a description tune; `kinds` in `TUNE_KINDS` order."""
    parts = [IMPROVE_NARROW] if TUNE_NARROW in kinds else []
    if TUNE_WIDEN in kinds:
        parts.append(IMPROVE_WIDEN)
    parts.append(IMPROVE_TAIL)
    c = {k: counts.get(k, 0) for k in ("false_fires", "injects", "misses")}
    user = (
        "\n\n".join(parts)
        + f"\n\nThe counts: {c['injects']} injections, {c['false_fires']} of them in a session "
        f"that never used it; {c['misses']} pieces of its work done without it.\n\n"
        f"The skill now:\n\n```markdown\n{_clean(skill_text)}```\n\n"
        f"The evidence bundle:\n\n```json\n{bundle_json(b)}\n```\n"
    )
    return IMPROVE_SYSTEM, user


def splice_description(answer: str, skill_text: str) -> str:
    """`skill_text` with the description of `answer` (a SKILL.md); SkillFileError when the
    answer has none to take."""
    got = parse_skill(unfence(answer))
    doc = parse_skill(_clean(skill_text))
    return render(SkillDoc(doc.name, got.description, doc.metadata, doc.body))


def improve_check(
    answer: str, skill_text: str, b: Mapping[str, Any], home: str | Path, cwd: str | None, own: Any
) -> tuple[str | None, list[str]]:
    """`(spliced text, [])` when the answer's description, in the skill, passes the gate;
    `(None, reasons)` otherwise."""
    try:
        text = splice_description(answer, skill_text)
    except SkillFileError as e:
        return None, [str(e)]
    g = gate(text, b, home, cwd, own=own)
    return (text if g.ok else None), g.reasons


def improve(
    kinds: Sequence[str],
    skill_text: str,
    b: Mapping[str, Any],
    counts: Mapping[str, int],
    chain: Sequence[Any],
    home: str | Path,
    cwd: str | None,
    now: str,
    own: Any,
) -> DraftOutcome:
    """The X5 walk for a description tune (as `draft`): the first drafter that answers ends it,
    pass or fail; the host agent ends it with the prompt to answer. One drafts-log line."""
    system, user = improve_prompt(kinds, skill_text, b, counts)
    unreachable: list[str] = []
    outcome: DraftOutcome | None = None
    for d in chain:
        if isinstance(d, HostAgentDrafter):
            handoff = {"bundle": b, "instructions": user, "target": str(own)}
            outcome = DraftOutcome(d.label, False, None, [], unreachable, handoff)
            break
        try:
            answer = d.ask(system, user)
        except Exception:  # noqa: BLE001 — every failure to answer is "unreachable" (R11)
            unreachable.append(d.label)
            continue
        text, reasons = improve_check(answer, skill_text, b, home, cwd, own)
        outcome = DraftOutcome(d.label, text is not None, text, reasons, unreachable)
        break
    if outcome is None:
        outcome = DraftOutcome(None, False, None, [], unreachable)
    LogSegment(drafts_log(home)).append(outcome.log_line(now, b["cluster"]))
    return outcome
