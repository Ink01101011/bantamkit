"""Perturbation bar: score one critic over a family of meaning-preserving prompt edits.

RB-P14. A one-cell bar cannot tell a mechanism from a perturbation — deleting a single
semantically null byte from a rubric reproduced an entire pass signature. This module
replays the critic alone, at a pinned seed, over a small declared family of
meaning-preserving edits *to the rubric template*, and reports the pass rate with its
spread, so a rubric edit has to beat the noise band it lives in.

Layer: Measurement. It reads Contract assets (rubrics) and the frozen suite read-only,
calls Transport (`client.py`) and Core (`structured()`), and adds nothing to either.

Two constraints that are not optional (spec §6.1):

- **`CritiqueGate` is bypassed.** Its verdict memo keys on exact prompt bytes, so N
  replays of one point would collapse into one model call and one repeated verdict —
  silently destroying the spread this instrument exists to measure.
- **Requests go through `structured()`.** A hand-built `response_format` request on the
  as-filed rubric scored 9 where the committed replay record has 5. Request
  construction is load-bearing, which is why the reproduction gate comes first.

Not a whole-suite sweeper: its job is validating one change's attribution on a named
cell or a small task set.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

import yaml

from bantamkit.assets import assets_root
from bantamkit.client import BantamError, Message, ModelClient, OpenAICompatible
from bantamkit.critique import Rubric
from bantamkit.evalrun import TrackingClient
from bantamkit.structured import structured

__all__ = [
    "GUARD_MODES",
    "Case",
    "Manifest",
    "PerturbationError",
    "Point",
    "ReplayRow",
    "RubricVariant",
    "RunResult",
    "Verdict",
    "apply_point",
    "cell_guard_violations",
    "load_cases",
    "load_manifest",
    "main",
    "materialize_manifest",
    "normalize_whitespace",
    "parse_rubric_arg",
    "render_prompt",
    "replay_scores",
    "replay_verdicts",
    "run",
    "summarize",
]

BAR = "perturbation"

# §3.3 step 3, guard 3. "should not" for "do NOT" changes the force of a directive, so a
# paraphrase that moves any of these is a requirement edit wearing a paraphrase's clothes.
FROZEN_KEYWORDS = (
    "ONLY",
    "NOT",
    "never",
    "every",
    "any",
    "must",
    "should",
    "even when",
    "instead",
)

# The point classes §3 admits. `identity` is a mandatory member, not a perturbation class.
CLASSES = ("identity", "whitespace", "order", "paraphrase")

# What a run does when a point violates §3.3's shared-token guard on a cell. See
# `_guard_table` for why `warn` is the default and `error` is not.
GUARD_MODES = ("warn", "error")

NO_NEWLINE = "\\ No newline at end of file"

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


class PerturbationError(BantamError):
    """The instrument cannot report a number it would be able to defend."""


# ---- small helpers ----


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def normalize_whitespace(text: str) -> str:
    """§3.1's admissibility predicate, one half of it: collapse runs and strip.

    Two strings are in class W of each other iff their normalizations are
    byte-identical. Mechanical and checkable by anyone; nothing else is class W.
    """
    return " ".join(text.split())


def _diff_lines(text: str) -> list[str]:
    """Lines for a unified diff, with git's explicit missing-trailing-newline marker.

    Without the marker a trailing-newline edit — the null control, the whole reason this
    module exists — diffs as no change at all, because both sides have identical lines.
    """
    lines = text.splitlines()
    if not text.endswith("\n"):
        lines.append(NO_NEWLINE)
    return lines


def unified_diff(base: str, new: str, from_label: str = "base", to_label: str = "point") -> str:
    if base == new:
        return ""
    return "\n".join(
        difflib.unified_diff(
            _diff_lines(base),
            _diff_lines(new),
            fromfile=from_label,
            tofile=to_label,
            n=1,
            lineterm="",
        )
    )


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


# ---- the manifest (§3, §4.1) ----


@dataclass
class Point:
    id: str
    point_class: str  # `class` in the manifest and in the JSONL row; not a Python name
    rule: str
    op: str
    replace: list[dict] = field(default_factory=list)
    swap: dict | None = None
    justification: str | None = None
    variants: dict = field(default_factory=dict)


@dataclass
class Manifest:
    rubric: str
    requirement_inventory: list[str]
    points: list[Point]
    materialized_variants: dict
    sha256: str
    path: Path


def default_manifest_path(rubric_name: str) -> Path:
    """`assets/evals/perturbations/<rubric-name>.yaml`.

    Measurement *input*, not a Contract asset: no product code path loads it, and
    `test_layers.py`'s golden byte-identity guard over contract strings does not extend
    to it. It lives under `assets/evals/` because that is already where measurement
    input lives (`tasks/`, `fixtures/`), and a test asserts this module is its only
    reader.
    """
    return assets_root() / "evals" / "perturbations" / f"{rubric_name}.yaml"


def load_manifest(path: Path | None = None, rubric_name: str | None = None) -> Manifest:
    if path is None:
        if rubric_name is None:
            raise PerturbationError("load_manifest needs a path or a rubric name")
        path = default_manifest_path(rubric_name)
    path = Path(path)
    if not path.is_file():
        raise PerturbationError(f"perturbation manifest not found: {path}")
    raw = path.read_text()
    data = yaml.safe_load(raw)
    points = []
    for entry in data["points"]:
        if entry["class"] not in CLASSES:
            raise PerturbationError(f"point '{entry['id']}' has unknown class {entry['class']!r}")
        points.append(
            Point(
                id=entry["id"],
                point_class=entry["class"],
                rule=entry["rule"],
                op=entry["op"],
                replace=entry.get("replace") or [],
                swap=entry.get("swap"),
                justification=entry.get("justification"),
                variants=entry.get("variants") or {},
            )
        )
    ids = [p.id for p in points]
    if len(set(ids)) != len(ids):
        raise PerturbationError(f"duplicate point ids in {path}")
    return Manifest(
        rubric=data["rubric"],
        requirement_inventory=list(data["requirement_inventory"]),
        points=points,
        materialized_variants=data.get("materialized_variants") or {},
        sha256=sha256_text(raw),
        path=path,
    )


def apply_point(point: Point, template: str) -> str | None:
    """Apply one declared, text-anchored transformation to one template.

    Returns the perturbed template, or `None` when the point's anchor is absent from
    this variant (§4.1: `applicable: false`, which paired dropping then handles). Never
    a silent no-op — a transformation that fires and changes nothing is an error, not a
    point, and so is an anchor that matches in more places than it claims.
    """
    new = _transform(point, template)
    if new is None:
        return None
    if new == template and point.op != "identity":
        raise PerturbationError(
            f"point '{point.id}' is a no-op on a variant whose anchor it matched — "
            "a transformation that changes nothing is an error, not a point"
        )
    return new


def _transform(point: Point, template: str) -> str | None:
    if point.op == "identity":
        return template
    if point.op == "strip-trailing-newline":
        return template[:-1] if template.endswith("\n") else None
    if point.op == "append-trailing-newline":
        return template + "\n"
    if point.op == "replace":
        new = template
        for op in point.replace:
            found, new = _replace_once(point.id, new, op)
            if not found:
                return None
        return new
    if point.op == "swap":
        return _swap(point.id, template, point.swap or {})
    raise PerturbationError(f"point '{point.id}' has unknown op {point.op!r}")


def _replace_once(point_id: str, template: str, op: dict) -> tuple[bool, str]:
    anchor, replacement = op["from"], op["to"]
    count = template.count(anchor)
    if count == 0:
        return False, template
    if op.get("occurrences", 1) != "all" and count != 1:
        raise PerturbationError(
            f"point '{point_id}' anchor occurs {count} times but claims one — "
            "an ambiguous anchor silently perturbs the wrong place"
        )
    return True, template.replace(anchor, replacement)


_SENTINEL = "\x00bantamkit-swap\x00"


def _swap(point_id: str, template: str, swap: dict) -> str | None:
    a, b = swap["a"], swap["b"]
    if a not in template or b not in template:
        return None
    for side in (a, b):
        if template.count(side) != 1:
            raise PerturbationError(
                f"point '{point_id}' swap anchor occurs {template.count(side)} times but "
                "claims one"
            )
    if _SENTINEL in template:
        raise PerturbationError(f"point '{point_id}': template contains the swap sentinel")
    return template.replace(a, _SENTINEL).replace(b, a).replace(_SENTINEL, b)


def shared_token_violations(point: Point, text: str) -> list[str]:
    """§3.3 step 3, guard 2, against one text: the words this point moves that appear in it.

    RB-P4's measured mechanism was literal matching against a token copied from the task
    prompt, so a paraphrase that changes the shared-token surface is changing the
    mechanism under test.

    The primitive. It takes one text so the offline table over all 22 frozen task
    prompts can be pinned against it directly; `cell_guard_violations` is what the run
    path calls, because the guard the spec writes is about the whole cell.
    """
    changed: set[str] = set()
    for op in point.replace:
        changed |= _words(op["from"]) ^ _words(op["to"])
    return sorted(changed & _words(text))


def cell_guard_violations(point: Point, case: Case) -> list[str]:
    """The same guard against a whole cell: §3.3's `{task}` **or** `{output}`.

    Checking `{task}` alone is how this guard was under-implemented; the spec names both
    surfaces, and a run holds both. Measured on the committed M1 transcripts the
    `{output}` half adds nothing today (zero extra violations over 20 cells), which is
    the point: a guard is not allowed to be right only by luck.
    """
    return sorted(
        set(shared_token_violations(point, case.prompt))
        | set(shared_token_violations(point, case.output))
    )


def materialize_manifest(points: list[Point], templates: dict[str, str]) -> dict:
    """Per point, per variant: applicability, the resulting template sha, and a diff.

    The whole family is materialized so a reader audits the exact bytes without
    re-running anything, and so a rule change shows up as a manifest diff.
    """
    out: dict[str, dict] = {}
    for point in points:
        out[point.id] = {}
        for label, base in templates.items():
            new = apply_point(point, base)
            if new is None:
                out[point.id][label] = {"applicable": False}
            else:
                out[point.id][label] = {
                    "applicable": True,
                    "sha256": sha256_text(new),
                    "diff": unified_diff(new=new, base=base, from_label=label, to_label=point.id),
                }
    return out


# ---- rubric variants (§6.2) ----


@dataclass
class RubricVariant:
    label: str
    spec: str
    ref: str
    rubric: Rubric
    sha256: str


def parse_rubric_arg(arg: str) -> RubricVariant:
    """`LABEL=SPEC`, where SPEC is a path or `git:<ref>:<path>`.

    The git form exists because the acceptance test needs rubrics that live only in
    history. `load_rubric` is name-only and has no path hook, so the parsed `Rubric` is
    passed around as an instance.
    """
    label, sep, spec = arg.partition("=")
    if not sep or not label or not spec:
        raise PerturbationError(f"--rubric wants LABEL=SPEC, got {arg!r}")
    if spec.startswith("git:"):
        _, ref, path = spec.split(":", 2)
        raw = _git_show(ref, path)
        source = ref
    else:
        path = Path(spec)
        if not path.is_file():
            raise PerturbationError(f"rubric not found: {spec}")
        raw = path.read_text()
        source = spec
    return RubricVariant(
        label=label, spec=spec, ref=source, rubric=_parse_rubric(raw, spec), sha256=sha256_text(raw)
    )


def _git_show(ref: str, path: str) -> str:
    try:
        return subprocess.run(
            ["git", "show", f"{ref}:{path}"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise PerturbationError(f"cannot read git:{ref}:{path}: {e}") from e


def _parse_rubric(raw: str, where: str) -> Rubric:
    data = yaml.safe_load(raw)
    try:
        rubric = Rubric(
            name=data["name"],
            threshold=int(data["threshold"]),
            prompt=data["prompt"],
            schema=data["schema"],
        )
    except (KeyError, TypeError, ValueError) as e:
        raise PerturbationError(f"{where} is not a rubric: {e}") from e
    missing = [slot for slot in ("{task}", "{output}") if slot not in rubric.prompt]
    if missing:
        raise PerturbationError(f"{where} prompt missing placeholder(s): {', '.join(missing)}")
    return rubric


# ---- cells, taken byte-exact from P8 transcripts (§6.2) ----


@dataclass
class Case:
    task: str
    repeat: int
    seed: int
    prompt: str  # the frozen suite's task prompt, read-only
    output: str  # the answer, byte-exact from the transcript


def load_cases(
    transcripts_dir: Path, tasks: list[str] | None = None, tasks_dir: Path | None = None
) -> list[Case]:
    """One cell per (task, repeat), fed from P8 transcripts rather than hand-copied strings.

    That is what makes "byte-identical answer" true by construction instead of by
    assertion. The task *prompt* is loaded read-only from the frozen suite; a
    transcript that carries no answer is skipped, and two transcripts that disagree
    about one cell are a hard error rather than a coin toss.
    """
    tasks_dir = Path(tasks_dir) if tasks_dir else assets_root() / "evals" / "tasks"
    wanted = set(tasks) if tasks else None
    cells: dict[tuple[str, int], tuple[Case, str]] = {}
    for path in sorted(Path(transcripts_dir).glob("*.json")):
        data = json.loads(path.read_text())
        name = data["task"]
        if wanted is not None and name not in wanted:
            continue
        if data.get("output") is None:
            continue
        if data.get("seed") is None:
            raise PerturbationError(
                f"{path.name} records no seed; the bar reports seeded numbers only"
            )
        case = Case(
            task=name,
            repeat=int(data["repeat"]),
            seed=int(data["seed"]),
            prompt=_task_prompt(tasks_dir, name),
            output=data["output"],
        )
        key = (case.task, case.repeat)
        seen = cells.get(key)
        if seen is not None and (seen[0].prompt, seen[0].output) != (case.prompt, case.output):
            raise PerturbationError(
                f"transcripts {seen[1]} and {path.name} disagree about cell {key}: the "
                "{task}/{output} region must be identical for every variant of a cell"
            )
        if seen is None:
            cells[key] = (case, path.name)
    return [case for case, _ in cells.values()]


def _task_prompt(tasks_dir: Path, name: str) -> str:
    path = Path(tasks_dir) / f"{name}.yaml"
    if not path.is_file():
        raise PerturbationError(f"task asset not found: {path}")
    return yaml.safe_load(path.read_text())["prompt"]


def render_prompt(template: str, case: Case) -> str:
    """The critic's literal input: the template, then `{task}`/`{output}` interpolated.

    Perturbation runs on the template only and interpolation happens afterwards from
    read-only sources, which is what makes the frozen-suite invariant mechanical: a
    perturbation cannot reach `{task}` or `{output}`.
    """
    return template.format(task=case.prompt, output=case.output)


# ---- the replay primitive (§6.1, §8) ----


@dataclass
class Verdict:
    score: int
    feedback: str
    tokens_in: int
    tokens_out: int
    calls: int
    prompt_sha256: str
    payload_sha256: str


def _payload_sha(model: str, seed: int | None, messages: list[Message], response_format) -> str:
    """The wire body's sha, assembled the way `OpenAICompatible.chat` assembles it.

    Recorded beside `prompt_sha256` because they answer different questions: the prompt
    sha proves which text the critic read, the payload sha proves the whole request —
    seed and `response_format` included — was the one intended. `e57f1a6` changes the
    rubric *schema*, so two variants can differ in what goes on the wire as
    `response_format` and not only in prose.
    """
    payload: dict = {"model": model, "messages": [m.to_wire() for m in messages]}
    if seed is not None:
        payload["seed"] = seed
    if response_format is not None:
        payload["response_format"] = response_format
    return sha256_text(json.dumps(payload, ensure_ascii=False))


class _PayloadSpy:
    """Captures the first request `structured()` actually sends, changing nothing.

    Reading the payload off the real call rather than rebuilding it keeps the recorded
    sha honest: a second spelling of the request would make "same request" unfalsifiable,
    which is exactly the failure §6.1 warns about.
    """

    def __init__(self, inner, model: str, seed: int | None):
        self.inner = inner
        self.model = model
        self.seed = seed
        self.payload_sha256: str | None = None

    @property
    def _response_format_unsupported(self) -> bool:
        return self.inner._response_format_unsupported

    def chat(self, messages, tools=None, response_format=None):
        if self.payload_sha256 is None:
            self.payload_sha256 = _payload_sha(self.model, self.seed, messages, response_format)
        return self.inner.chat(messages, tools, response_format=response_format)


def replay_verdicts(
    client: ModelClient, rubric: Rubric, case: Case, replays: int = 1
) -> list[Verdict]:
    """Re-issue one pinned critic request `replays` times and keep every verdict.

    `CritiqueGate` is deliberately not involved. Its memo keys on exact prompt bytes and
    would return one bought verdict N times, which is the one thing this instrument must
    never do. `structured()` is, because request construction is load-bearing.
    """
    if replays < 1:
        raise PerturbationError(f"replays must be >= 1, got {replays}")
    if hasattr(client, "seed"):
        client.seed = case.seed
    prompt = render_prompt(rubric.prompt, case)
    prompt_sha = sha256_text(prompt)
    model = getattr(client, "model", "")
    seed = getattr(client, "seed", None)
    verdicts = []
    for _ in range(replays):
        tracking = TrackingClient(client)
        spy = _PayloadSpy(tracking, model, seed)
        data = structured(spy, prompt, rubric.schema)
        verdicts.append(
            Verdict(
                score=int(data["score"]),
                feedback=str(data.get("feedback") or ""),
                tokens_in=tracking.usage.prompt_tokens,
                tokens_out=tracking.usage.completion_tokens,
                calls=tracking.calls,
                prompt_sha256=prompt_sha,
                payload_sha256=spy.payload_sha256 or "",
            )
        )
    return verdicts


def replay_scores(client: ModelClient, rubric: Rubric, case: Case, replays: int = 1) -> list[int]:
    """RB-P15's standing check, reduced to the number it asks for: N scores at one seed.

    The `identity` point is one call to this. Nothing extra is needed to *compute* the
    within-cell replay spread — only the plumbing around it (§8).
    """
    return [v.score for v in replay_verdicts(client, rubric, case, replays)]


# ---- the run (§6.3) ----

_ROW_KEYS = (
    "bar", "variant", "rubric_ref", "rubric_sha256", "manifest_sha256", "task", "seed",
    "repeat", "model", "point", "class", "rule", "replay", "prompt_sha256", "payload_sha256",
    "score", "threshold", "passed", "feedback", "tokens_in", "tokens_out", "calls",
    "guard_violations",
)


@dataclass
class ReplayRow:
    bar: str
    variant: str
    rubric_ref: str
    rubric_sha256: str
    manifest_sha256: str
    task: str
    seed: int
    repeat: int
    model: str
    point: str
    point_class: str  # emitted as `class`, which is not a Python identifier
    rule: str
    replay: int
    prompt_sha256: str
    payload_sha256: str
    score: int
    threshold: int
    passed: bool
    feedback: str
    tokens_in: int
    tokens_out: int
    calls: int  # wire calls behind this one row: 1, or more if `structured()` retried
    # §3.3 guard 2's verdict for THIS (point, cell): the shared words, or empty. The row
    # is the artifact a later reader has; a violation that lives only in prose is how
    # this one got under-reported twice.
    guard_violations: list[str] = field(default_factory=list)

    def row(self) -> dict:
        data = dict(vars(self))
        data["class"] = data.pop("point_class")
        return {key: data[key] for key in _ROW_KEYS}


@dataclass
class RunResult:
    rows: list[ReplayRow]
    dropped: dict[str, list[str]]
    selected: list[str]
    labels: list[str]
    threshold: int
    cells: list[Case]
    # (task, repeat) -> {point id: shared words}. Empty when every point is clean.
    guard: dict[tuple[str, int], dict[str, list[str]]] = field(default_factory=dict)
    guard_mode: str = "warn"


def run(
    client: ModelClient,
    variants: list[RubricVariant],
    manifest: Manifest,
    cases: list[Case],
    *,
    replays: int = 1,
    identity_replays: int = 5,
    identity_only: bool = False,
    model: str = "",
    guard: str = "warn",
    on_row: Callable[[ReplayRow], None] | None = None,
) -> RunResult:
    if guard not in GUARD_MODES:
        raise PerturbationError(f"unknown guard mode {guard!r}; expected one of {GUARD_MODES}")
    if not variants:
        raise PerturbationError("nothing to replay: no rubric variants")
    if not cases:
        raise PerturbationError("nothing to replay: no cells")
    thresholds = {v.rubric.threshold for v in variants}
    if len(thresholds) != 1:
        raise PerturbationError(
            f"variants disagree on threshold ({sorted(thresholds)}); pass rates across two "
            "different decision points are not comparable"
        )
    threshold = thresholds.pop()
    points = [p for p in manifest.points if p.point_class == "identity" or not identity_only]
    selected = [p.id for p in points]
    guard_table = _guard_table(points, cases, guard)

    templates: dict[str, dict[str, str]] = {}
    dropped: dict[str, list[str]] = {}
    for variant in variants:
        templates[variant.label], dropped[variant.label] = _variant_family(
            variant, points, manifest
        )

    model = model or getattr(client, "model", "")
    rows: list[ReplayRow] = []
    for variant in variants:
        for case in cases:
            for point in points:
                template = templates[variant.label].get(point.id)
                if template is None:
                    continue
                perturbed = Rubric(
                    name=variant.rubric.name,
                    threshold=threshold,
                    prompt=template,
                    schema=variant.rubric.schema,
                )
                for index, verdict in enumerate(
                    replay_verdicts(
                        client,
                        perturbed,
                        case,
                        identity_replays if point.point_class == "identity" else replays,
                    )
                ):
                    row = ReplayRow(
                        bar=BAR,
                        variant=variant.label,
                        rubric_ref=variant.ref,
                        rubric_sha256=variant.sha256,
                        manifest_sha256=manifest.sha256,
                        task=case.task,
                        seed=case.seed,
                        repeat=case.repeat,
                        model=model,
                        point=point.id,
                        point_class=point.point_class,
                        rule=point.rule,
                        replay=index,
                        prompt_sha256=verdict.prompt_sha256,
                        payload_sha256=verdict.payload_sha256,
                        score=verdict.score,
                        threshold=threshold,
                        passed=verdict.score >= threshold,
                        feedback=verdict.feedback,
                        tokens_in=verdict.tokens_in,
                        tokens_out=verdict.tokens_out,
                        calls=verdict.calls,
                        guard_violations=list(
                            guard_table.get((case.task, case.repeat), {}).get(point.id, [])
                        ),
                    )
                    rows.append(row)
                    if on_row is not None:
                        on_row(row)
    return RunResult(
        rows=rows,
        dropped=dropped,
        selected=selected,
        labels=[v.label for v in variants],
        threshold=threshold,
        cells=list(cases),
        guard=guard_table,
        guard_mode=guard,
    )


def _guard_table(
    points: list[Point], cases: list[Case], mode: str
) -> dict[tuple[str, int], dict[str, list[str]]]:
    """§3.3 guard 2 for every (point, cell), decided before a single request goes out.

    **`warn` is the default, and a hard error is the wrong default.** Eight of the
    twenty M1-screened cells violate this guard, `nav-prod-port` — the canonical cell of
    this whole line of work — among them, and two of the twelve committed anchor cells.
    A run that aborts on a violation makes those cells unrunnable, which is a regression
    dressed as a stricter guard: the status quo at least produced measurements.

    What the status quo failed to do was make the violation impossible to miss, so that
    is what is enforced instead. The violating point still runs; every row it produces
    carries the shared words; the summary reports the family recomputed without it; and
    attribution is credited only if the separation survives dropping it (`_compare`).
    `error` is available for callers who want the strict reading, and it refuses here,
    before any spend.
    """
    table: dict[tuple[str, int], dict[str, list[str]]] = {}
    for case in cases:
        for point in points:
            words = cell_guard_violations(point, case)
            if words:
                table.setdefault((case.task, case.repeat), {})[point.id] = words
    if table and mode == "error":
        named = "; ".join(
            f"{task} r{repeat}: {pid} shares {words}"
            for (task, repeat), hits in sorted(table.items())
            for pid, words in sorted(hits.items())
        )
        raise PerturbationError(
            f"shared-token guard (spec §3.3 step 3, guard 2) violated on {len(table)} cell(s) "
            f"— {named}. Re-run with the default guard mode to measure them anyway, with "
            "every violating row and the guard-dropped family recorded."
        )
    return table


def _variant_family(
    variant: RubricVariant, points: list[Point], manifest: Manifest
) -> tuple[dict[str, str], list[str]]:
    family: dict[str, str] = {}
    dropped: list[str] = []
    seen: dict[str, str] = {}
    for point in points:
        template = apply_point(point, variant.rubric.prompt)
        if template is None:
            dropped.append(point.id)
            continue
        collision = seen.get(template)
        if collision is not None:
            raise PerturbationError(
                f"points '{collision}' and '{point.id}' produce the same template on variant "
                f"'{variant.label}' — a point that changed nothing measures nothing"
            )
        seen[template] = point.id
        family[point.id] = template
        _check_materialization(manifest, variant.label, point, template)
    return family, dropped


def _check_materialization(manifest: Manifest, label: str, point: Point, template: str) -> None:
    """Where the manifest already materialized this label, the bytes must still match.

    A manifest that has drifted from the rubric it describes would let a reader audit
    one family while the run measured another.
    """
    recorded = point.variants.get(label)
    if not recorded or not recorded.get("applicable"):
        return
    if recorded.get("sha256") != sha256_text(template):
        raise PerturbationError(
            f"point '{point.id}' on variant '{label}' does not match the manifest's "
            f"materialized sha — {manifest.path} has drifted from the rubric it describes"
        )


# ---- the decision rule (§7) ----


def summarize(result: RunResult, manifest_sha256: str) -> dict:
    threshold = result.threshold
    by_cell: dict[tuple[str, int], dict[str, dict[str, list[ReplayRow]]]] = {}
    for row in result.rows:
        cell = by_cell.setdefault((row.task, row.repeat), {})
        cell.setdefault(row.variant, {}).setdefault(row.point, []).append(row)

    cells = []
    for case in result.cells:
        key = (case.task, case.repeat)
        per_variant = by_cell.get(key, {})
        violations = result.guard.get(key, {})
        block = {
            "task": case.task,
            "repeat": case.repeat,
            "seed": case.seed,
            "guard_violations": dict(violations),
            "variants": {
                label: _variant_stats(
                    per_variant.get(label, {}),
                    [p for p in result.selected if p not in result.dropped[label]],
                    threshold,
                    violations,
                )
                for label in result.labels
            },
            "comparisons": [
                _compare(result, per_variant, a, b, threshold, key, violations)
                for a, b in combinations(result.labels, 2)
            ],
        }
        cells.append(block)

    return {
        "bar": BAR,
        "threshold": threshold,
        "manifest_sha256": manifest_sha256,
        "guard": {
            "rule": "spec §3.3 step 3, guard 2 — no word a point adds or removes may "
            "appear in the cell's {task} or {output}",
            "mode": result.guard_mode,
            "violations": [
                {"task": task, "repeat": repeat, "point": pid, "words": words}
                for (task, repeat), hits in sorted(result.guard.items())
                for pid, words in sorted(hits.items())
            ],
        },
        # `requests` is the row count — one row per (variant, cell, point, replay).
        # `wire_calls` is what actually went out: they differ exactly when `structured()`
        # retried, which would otherwise inflate `tokens_total` invisibly.
        "requests": len(result.rows),
        "wire_calls": sum(r.calls for r in result.rows),
        "tokens_total": sum(r.tokens_in + r.tokens_out for r in result.rows),
        "variants": [
            {
                "label": label,
                "rubric_ref": next(r.rubric_ref for r in result.rows if r.variant == label),
                "rubric_sha256": next(r.rubric_sha256 for r in result.rows if r.variant == label),
                "dropped_rules": result.dropped[label],
            }
            for label in result.labels
            if any(r.variant == label for r in result.rows)
        ],
        "cells": cells,
    }


def _variant_stats(
    point_rows: dict[str, list[ReplayRow]],
    family: list[str],
    threshold: int,
    violations: dict[str, list[str]],
) -> dict:
    """One (variant, cell) block, plus the same statistic with tainted points removed.

    `pass_rate` stays the FULL family so a run remains comparable with every committed
    number, including the anchor set's `expect_pass_rate`. `guard_dropped` is the
    recomputation a reader would otherwise have to do by hand — and did, in prose, in
    `docs/eval.md`, because the artifacts could not carry it.
    """
    stats = _family_stats(point_rows, family, threshold)
    hits = {pid: words for pid, words in violations.items() if pid in family}
    stats["guard_violations"] = hits
    stats["guard_dropped"] = (
        _family_stats(point_rows, [pid for pid in family if pid not in hits], threshold)
        if hits
        else None
    )
    return stats


def _family_stats(
    point_rows: dict[str, list[ReplayRow]], family: list[str], threshold: int
) -> dict:
    """One (variant, cell) block. A point passes only if every one of its replays does."""
    scores = [row.score for pid in family for row in point_rows.get(pid, [])]
    passed = sum(
        1 for pid in family if point_rows.get(pid) and all(r.passed for r in point_rows[pid])
    )
    identity = [row.score for row in point_rows.get("identity", [])]
    low, high = (min(scores), max(scores)) if scores else (0, 0)
    return {
        "pass_rate": f"{passed}/{len(family)}",
        "passed": passed,
        "family_size": len(family),
        "score_min": low,
        "score_max": high,
        "spread": high - low,
        "margin_zero": sum(
            1
            for pid in family
            if any(abs(r.score - threshold) <= 1 for r in point_rows.get(pid, []))
        ),
        "identity_scores": identity,
        "identity_spread": (max(identity) - min(identity)) if identity else 0,
        # min and max straddling the threshold: the family cannot tell pass from fail.
        "fragile": bool(scores) and low < threshold <= high,
    }


def _compare(
    result: RunResult,
    per_variant: dict[str, dict[str, list[ReplayRow]]],
    a: str,
    b: str,
    threshold: int,
    cell: tuple[str, int],
    violations: dict[str, list[str]],
) -> dict:
    """Paired dropping, then the separation rule. F is post-drop and reported explicitly.

    Guard dropping is a second, cell-scoped drop on top of paired dropping, and it gates
    attribution: a separation carried by a point that shares a token with the cell is
    RB-P4's measured mechanism, not evidence about the edit. So `attributable` now
    requires the separation to survive removing the tainted points. It never removes a
    cell from the run — when everything is tainted, `guard_verdict` is `undefined` and
    nothing is credited, which is the honest answer, not an abort.
    """
    family = [
        pid
        for pid in result.selected
        if pid not in result.dropped[a] and pid not in result.dropped[b]
    ]
    dropped_rules = [
        {"rule": pid, "variant": label}
        for pid in result.selected
        if pid not in family
        for label in (a, b)
        if pid in result.dropped[label]
    ]
    rows_a, rows_b = per_variant.get(a, {}), per_variant.get(b, {})
    present_a = {pid for pid in family if rows_a.get(pid)}
    present_b = {pid for pid in family if rows_b.get(pid)}
    if present_a != present_b:
        raise PerturbationError(
            f"post-drop rule-id sets differ for '{a}' and '{b}' on cell {cell}: "
            f"{sorted(present_a ^ present_b)} — refusing to report across mismatched families"
        )
    stats_a = _family_stats(rows_a, family, threshold)
    stats_b = _family_stats(rows_b, family, threshold)
    verdict = _separation(stats_a, stats_b, len(family))
    guard_family = [pid for pid in family if pid not in violations]
    guard_verdict = _separation(
        _family_stats(rows_a, guard_family, threshold),
        _family_stats(rows_b, guard_family, threshold),
        len(guard_family),
    )
    fragile = [label for label, s in ((a, stats_a), (b, stats_b)) if s["fragile"]]
    return {
        "a": a,
        "b": b,
        "verdict": verdict,
        "family_size": len(family),
        "dropped_rules": dropped_rules,
        "a_pass_rate": stats_a["pass_rate"],
        "b_pass_rate": stats_b["pass_rate"],
        "fragile": fragile,
        "guard_verdict": guard_verdict,
        "guard_family_size": len(guard_family),
        "guard_dropped_rules": [
            {"rule": pid, "reason": "shared-token", "words": violations[pid]}
            for pid in family
            if pid in violations
        ],
        # §7 rule 2: a fragile family voids attribution on this cell even if rule 1
        # fires. RB-P19 adds the third: so does a separation that only the
        # shared-token-violating points carried.
        "attributable": (
            verdict == "distinguishable" and guard_verdict == "distinguishable" and not fragile
        ),
    }


def _separation(stats_a: dict, stats_b: dict, size: int) -> str:
    """§7 rule 1, on whichever family it is handed."""
    if size == 0:
        return "undefined"
    if (stats_a["passed"] == size and stats_b["passed"] == 0) or (
        stats_b["passed"] == size and stats_a["passed"] == 0
    ):
        return "distinguishable"
    if stats_a["passed"] == stats_b["passed"]:
        return "indistinguishable"
    return "inconclusive"


def format_table(summary: dict) -> str:
    lines = [
        "| variant | task | repeat | seed | pass | min | max | spread | margin0 "
        "| identity | fragile |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for cell in summary["cells"]:
        for label, stats in cell["variants"].items():
            lines.append(
                f"| {label} | {cell['task']} | {cell['repeat']} | {cell['seed']} | "
                f"{stats['pass_rate']} | {stats['score_min']} | {stats['score_max']} | "
                f"{stats['spread']} | {stats['margin_zero']} | "
                f"{','.join(str(s) for s in stats['identity_scores'])} | {stats['fragile']} |"
            )
    guard = summary["guard"]
    if guard["violations"]:
        lines += ["", f"GUARD VIOLATIONS ({guard['mode']} mode) — {guard['rule']}:"]
        for hit in guard["violations"]:
            lines.append(
                f"- {hit['task']} r{hit['repeat']}: {hit['point']} shares "
                f"{', '.join(hit['words'])} with the cell — dropped from the "
                "guard-clean family, attribution void unless the separation survives it"
            )
        for cell in summary["cells"]:
            for label, stats in cell["variants"].items():
                if stats["guard_dropped"]:
                    lines.append(
                        f"  {label} {cell['task']} r{cell['repeat']}: "
                        f"{stats['pass_rate']} full -> "
                        f"{stats['guard_dropped']['pass_rate']} guard-clean"
                    )
    lines += ["", "Pairwise (post-drop family):"]
    for cell in summary["cells"]:
        for comparison in cell["comparisons"]:
            dropped = ", ".join(
                f"{d['rule']} (absent from {d['variant']})" for d in comparison["dropped_rules"]
            )
            lines.append(
                f"- {cell['task']} r{cell['repeat']}: {comparison['a']} "
                f"{comparison['a_pass_rate']} vs {comparison['b']} {comparison['b_pass_rate']} "
                f"-> {comparison['verdict']} (F={comparison['family_size']}"
                + (f"; dropped {dropped}" if dropped else "")
                + ")"
                + ("" if comparison["attributable"] or comparison["verdict"] != "distinguishable"
                   else f" — attribution VOID: fragile {comparison['fragile']}")
            )
    lines += [
        "",
        f"requests: {summary['requests']}  wire calls: {summary['wire_calls']}  "
        f"tokens: {summary['tokens_total']}  manifest: {summary['manifest_sha256'][:12]}",
    ]
    return "\n".join(lines)


# ---- CLI (§6.2) ----


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m bantamkit.criticreplay",
        description=(
            "Perturbation bar: replay one critic over a family of meaning-preserving "
            "edits to its own prompt and report the pass rate with its spread."
        ),
    )
    parser.add_argument(
        "--rubric",
        action="append",
        required=True,
        metavar="LABEL=SPEC",
        help="repeatable; SPEC is a path or git:<ref>:<path>",
    )
    parser.add_argument(
        "--manifest", type=Path, help="perturbation manifest (default: by rubric name)"
    )
    parser.add_argument(
        "--transcripts", type=Path, required=True, help="directory of P8 transcripts (the cells)"
    )
    parser.add_argument("--task", action="append", help="repeatable; restrict to these tasks")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--replays", type=int, default=1, help="replays per perturbation point")
    parser.add_argument("--identity-replays", type=int, default=5)
    parser.add_argument("--identity-only", action="store_true", help="RB-P15's standing check")
    parser.add_argument(
        "--guard",
        choices=GUARD_MODES,
        default="warn",
        help=(
            "what to do when a point shares a moved word with a cell (spec §3.3 guard 2): "
            "'warn' measures it and records the violation on every row and in the summary "
            "(default); 'error' refuses before any request"
        ),
    )
    parser.add_argument("--json", type=Path, help="append one JSON line per replay to this file")
    parser.add_argument("--summary", type=Path, help="write the summary JSON here")
    args = parser.parse_args(argv)
    if args.replays < 1 or args.identity_replays < 1:
        parser.error("--replays and --identity-replays must be >= 1")

    jsonl = None
    try:
        variants = [parse_rubric_arg(spec) for spec in args.rubric]
        manifest = load_manifest(args.manifest, rubric_name=variants[0].rubric.name)
        cases = load_cases(args.transcripts, tasks=args.task)
        if not cases:
            raise PerturbationError(
                f"no transcripts with answers in {args.transcripts}"
                + (f" for task(s) {args.task}" if args.task else "")
            )
        client = OpenAICompatible(
            base_url=args.base_url, model=args.model, timeout=args.timeout
        )
        sink = None
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            jsonl = args.json.open("a")

            def sink(row: ReplayRow) -> None:
                jsonl.write(json.dumps(row.row()) + "\n")
                jsonl.flush()  # a killed run keeps its partials

        result = run(
            client,
            variants,
            manifest,
            cases,
            replays=args.replays,
            identity_replays=args.identity_replays,
            identity_only=args.identity_only,
            model=args.model,
            guard=args.guard,
            on_row=sink,
        )
        summary = summarize(result, manifest.sha256)
    except BantamError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    finally:
        if jsonl is not None:
            jsonl.close()

    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, indent=2) + "\n")
    print(format_table(summary))


if __name__ == "__main__":
    main()
