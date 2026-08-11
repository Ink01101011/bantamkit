"""The perturbation bar (RB-P14): family construction, admissibility, and the decision rule.

Offline only. Every model call in here is a fake — the acceptance run against a live
model is a separate, deliberately fresh-eyed pass (spec §10).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from bantamkit import criticreplay
from bantamkit.client import Message, Response, Usage
from bantamkit.critique import Rubric

SRC = Path(__file__).resolve().parents[1] / "src" / "bantamkit"
ASSETS = Path(__file__).resolve().parents[2] / "assets"

# §10's three acceptance variants. A-asfiled is byte-identical to the shipped rubric
# asset (verified below), so A and B need no git; C exists only in history.
ATTEMPTED_REF = "e57f1a6"


def _shipped_template() -> str:
    return yaml.safe_load((ASSETS / "rubrics" / "task-completion.yaml").read_text())["prompt"]


def _attempted_template() -> str | None:
    """C-attempted's template, or None where the git object is unavailable."""
    try:
        raw = subprocess.run(
            ["git", "show", f"{ATTEMPTED_REF}:assets/rubrics/task-completion.yaml"],
            capture_output=True,
            text=True,
            cwd=ASSETS.parent,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return yaml.safe_load(raw)["prompt"]


def variant_templates() -> dict[str, str]:
    base = _shipped_template()
    templates = {"A-asfiled": base, "B-nonewline": base[:-1]}
    attempted = _attempted_template()
    if attempted is not None:
        templates["C-attempted"] = attempted
    return templates


@pytest.fixture(scope="module")
def manifest():
    return criticreplay.load_manifest(rubric_name="task-completion")


# ---- the shipped manifest (spec §3, §4.1; success criteria 3, 4, 5) ----


def test_manifest_ships_twelve_points_including_identity_and_the_null_control(manifest):
    ids = [p.id for p in manifest.points]
    assert len(ids) == 12, ids
    assert len(set(ids)) == 12
    assert "identity" in ids and "W1-trailing-newline" in ids
    assert [p.point_class for p in manifest.points].count("identity") == 1


def test_manifest_family_has_the_five_w_three_o_three_p_shape(manifest):
    by_class = {}
    for point in manifest.points:
        by_class.setdefault(point.point_class, []).append(point.id)
    assert sorted(by_class) == ["identity", "order", "paraphrase", "whitespace"]
    assert len(by_class["whitespace"]) == 5
    assert len(by_class["order"]) == 3
    assert len(by_class["paraphrase"]) == 3


def test_manifest_carries_the_full_requirement_inventory(manifest):
    """§3.3 step 1: the inventory ships in the manifest, not in someone's head."""
    assert len(manifest.requirement_inventory) == 11
    joined = " ".join(manifest.requirement_inventory).lower()
    for fragment in ("formatting", "phrasing", "hedging", "verbosity", "refus", "9-10", "0-4"):
        assert fragment in joined


def test_every_paraphrase_point_carries_a_written_justification(manifest):
    """§3.3 step 4."""
    for point in manifest.points:
        if point.point_class == "paraphrase":
            assert point.justification, point.id
            assert len(point.justification.split()) >= 4


def test_whitespace_points_are_whitespace_normalized_equal_to_the_base(manifest):
    """§3.1's admissibility predicate — the whole definition of class W."""
    for label, base in variant_templates().items():
        for point in manifest.points:
            if point.point_class != "whitespace":
                continue
            new = criticreplay.apply_point(point, base)
            if new is None:
                continue
            assert criticreplay.normalize_whitespace(new) == criticreplay.normalize_whitespace(
                base
            ), f"{point.id} on {label} is not whitespace-preserving"


def test_whitespace_family_has_a_lengthening_and_a_shortening_point(manifest):
    """§3.1: the family must not be systematically biased in one direction."""
    base = _shipped_template()
    deltas = {}
    for point in manifest.points:
        if point.point_class == "whitespace":
            new = criticreplay.apply_point(point, base)
            if new is not None:
                deltas[point.id] = len(new) - len(base)
    assert any(d > 0 for d in deltas.values()), deltas
    assert any(d < 0 for d in deltas.values()), deltas


def test_every_point_renders_a_prompt_distinct_from_the_base_and_from_every_other(manifest):
    """Success criterion 5. A point that changed nothing is a bug, not a data point."""
    case = criticreplay.Case(
        task="nav-prod-port", repeat=0, seed=1, prompt="TASK TEXT", output='{"port": 9443}'
    )
    for label, base in variant_templates().items():
        seen = {criticreplay.render_prompt(base, case): "base"}
        for point in manifest.points:
            new = criticreplay.apply_point(point, base)
            if new is None:
                continue
            prompt = criticreplay.render_prompt(new, case)
            if point.id == "identity":
                assert prompt in seen
                continue
            assert prompt not in seen, f"{point.id} on {label} collides with {seen.get(prompt)}"
            seen[prompt] = point.id


def test_no_point_disturbs_the_frozen_schema_and_band_literals(manifest):
    """§3.3 step 3: schema keys, JSON braces and band digits are byte-frozen."""
    frozen = ('"score"', '"feedback"', "9-10", "5-8", "0-4", "{{", "}}")
    for base in variant_templates().values():
        for point in manifest.points:
            new = criticreplay.apply_point(point, base)
            if new is None:
                continue
            for literal in frozen:
                assert new.count(literal) == base.count(literal), (point.id, literal)


def test_paraphrase_points_change_no_negation_quantifier_or_modal(manifest):
    """§3.3 step 3: the frozen keyword list. 'should not' for 'do NOT' changes force."""
    for base in variant_templates().values():
        for point in manifest.points:
            if point.point_class != "paraphrase":
                continue
            new = criticreplay.apply_point(point, base)
            if new is None:
                continue
            for word in criticreplay.FROZEN_KEYWORDS:
                assert new.count(word) == base.count(word), (point.id, word)


def test_paraphrase_points_edit_exactly_one_sentence(manifest):
    """§3.3 step 3: an instance a reader cannot check at a glance is not defensible."""
    for point in manifest.points:
        if point.point_class != "paraphrase":
            continue
        assert point.op == "replace" and len(point.replace) == 1, point.id
        for op in point.replace:
            assert op["from"].count(". ") == 0, point.id
            assert not op["from"].strip().endswith("."), point.id


def test_shared_token_guard_is_violated_only_by_p3_on_the_acceptance_cell(manifest):
    """§3.3 step 3, guard 2 — and a SPEC DEFECT pinned here rather than papered over.

    The guard is "no added or removed word may appear in the cell's {task}". P3 removes
    `right`, and `nav-prod-port`'s task prompt contains "follow the documentation to the
    right file". The spec's own justification for P3 checks only the *added* word
    (`correct`). P3 ships as specified (the brief forbids silently improving the spec);
    this test pins the violation so it stays visible and cannot silently grow.
    """
    task_prompt = yaml.safe_load((ASSETS / "evals" / "tasks" / "nav-prod-port.yaml").read_text())[
        "prompt"
    ]
    violations = {
        point.id: criticreplay.shared_token_violations(point, task_prompt)
        for point in manifest.points
        if criticreplay.shared_token_violations(point, task_prompt)
    }
    assert violations == {"P3-right-correct": ["right"]}


def test_materialization_matches_a_recomputation_from_the_rubric_texts(manifest):
    """§4.1: the whole family is materialized and committed, auditable without a run."""
    templates = variant_templates()
    recomputed = criticreplay.materialize_manifest(manifest.points, templates)
    for label in templates:
        assert label in manifest.materialized_variants, label
        for point in manifest.points:
            assert point.variants[label] == recomputed[point.id][label], (point.id, label)


def test_materialization_covers_all_three_acceptance_variants(manifest):
    """C-attempted is materialized even where this checkout cannot resolve its git object."""
    assert sorted(manifest.materialized_variants) == [
        "A-asfiled",
        "B-nonewline",
        "C-attempted",
    ]
    for point in manifest.points:
        assert sorted(point.variants) == ["A-asfiled", "B-nonewline", "C-attempted"], point.id


def test_w1_is_not_applicable_to_b_nonewline_and_the_manifest_says_so(manifest):
    """Paired dropping's one real case in the acceptance run (§4.1)."""
    w1 = next(p for p in manifest.points if p.id == "W1-trailing-newline")
    assert w1.variants["B-nonewline"]["applicable"] is False
    assert w1.variants["A-asfiled"]["applicable"] is True
    assert criticreplay.apply_point(w1, _shipped_template()[:-1]) is None


def test_b_nonewline_identity_equals_a_asfiled_w1_bytes(manifest):
    """Gate 1's free cross-check, offline: same prompt bytes reached by two routes."""
    base = _shipped_template()
    w1 = next(p for p in manifest.points if p.id == "W1-trailing-newline")
    identity = next(p for p in manifest.points if p.id == "identity")
    assert criticreplay.apply_point(w1, base) == criticreplay.apply_point(identity, base[:-1])


def test_shipped_rubric_asset_still_reproduces_the_sa3_prompt_sha():
    """Gate 0's precondition, checked without a model: the assembled bytes are right."""
    task_prompt = yaml.safe_load((ASSETS / "evals" / "tasks" / "nav-prod-port.yaml").read_text())[
        "prompt"
    ]
    case = criticreplay.Case(
        task="nav-prod-port", repeat=0, seed=2331795949, prompt=task_prompt,
        output='{"port": 9443}',
    )
    base = _shipped_template()
    asfiled = criticreplay.render_prompt(base, case)
    assert criticreplay.sha256_text(asfiled) == (
        "8fb6c98412f14a892f51b3f4d0d895bc872de4805185f62c3c2fdb3403ce7eeb"
    )
    assert criticreplay.sha256_text(criticreplay.render_prompt(base[:-1], case)) == (
        "3e3a55af8168dbc4e29b085cb67e873805f17f5adc224789c10aa5e581b9fbac"
    )


# ---- the transformation engine (§4.1) ----


def _point(**kw):
    kw.setdefault("point_class", "whitespace")
    kw.setdefault("rule", "r")
    return criticreplay.Point(**kw)


def test_identity_point_returns_the_base_untouched():
    point = _point(id="identity", point_class="identity", op="identity")
    assert criticreplay.apply_point(point, "abc\n") == "abc\n"


def test_missing_anchor_is_not_applicable_never_a_silent_no_op():
    point = _point(id="p", op="replace", replace=[{"from": "zzz", "to": "yyy"}])
    assert criticreplay.apply_point(point, "abc") is None


def test_a_transformation_that_changes_nothing_is_an_error():
    """§4.1: 'a transformation that changes nothing is an error, not a point'."""
    point = _point(id="p", op="replace", replace=[{"from": "abc", "to": "abc"}])
    with pytest.raises(criticreplay.PerturbationError, match="no-op"):
        criticreplay.apply_point(point, "abc")


def test_an_ambiguous_anchor_is_an_error():
    point = _point(id="p", op="replace", replace=[{"from": "ab", "to": "xy"}])
    with pytest.raises(criticreplay.PerturbationError, match="occurs 2"):
        criticreplay.apply_point(point, "ab ab")


def test_replace_all_is_position_independent():
    point = _point(
        id="p", op="replace", replace=[{"from": ". ", "to": ".  ", "occurrences": "all"}]
    )
    assert criticreplay.apply_point(point, "one. two. three") == "one.  two.  three"


def test_swap_exchanges_two_declared_sentences():
    point = _point(id="p", point_class="order", op="swap", swap={"a": "AAA", "b": "BBB"})
    assert criticreplay.apply_point(point, "x AAA y BBB z") == "x BBB y AAA z"


def test_swap_is_not_applicable_when_one_side_is_absent():
    point = _point(id="p", point_class="order", op="swap", swap={"a": "AAA", "b": "BBB"})
    assert criticreplay.apply_point(point, "x AAA y") is None


def test_strip_trailing_newline_is_not_applicable_without_one():
    point = _point(id="p", op="strip-trailing-newline")
    assert criticreplay.apply_point(point, "abc\n") == "abc"
    assert criticreplay.apply_point(point, "abc") is None


def test_append_trailing_newline_lengthens():
    point = _point(id="p", op="append-trailing-newline")
    assert criticreplay.apply_point(point, "abc\n") == "abc\n\n"


def test_unified_diff_marks_a_missing_trailing_newline():
    diff = criticreplay.unified_diff("abc\n", "abc", "base", "W1")
    assert "\\ No newline at end of file" in diff


# ---- layer guards (spec §6.4; success criterion 2) ----


def test_criticreplay_is_the_only_reader_of_the_perturbation_assets():
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "criticreplay.py":
            continue
        assert "perturbations" not in path.read_text(), (
            f"{path.name} reads the perturbation manifest — it is Measurement input, "
            "not a Contract asset, and criticreplay.py is its only reader"
        )


def test_no_product_module_imports_criticreplay():
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "criticreplay.py":
            continue
        assert "criticreplay" not in path.read_text(), path.name


def test_the_perturbation_manifest_lives_under_assets_evals():
    assert (ASSETS / "evals" / "perturbations" / "task-completion.yaml").is_file()
    assert not (ASSETS / "perturbations").exists()


def test_frozen_suite_tasks_are_read_only_here():
    source = (SRC / "criticreplay.py").read_text()
    for verb in ("write_text(", "mkdir(", "unlink(", "open(\"w\")"):
        assert f"tasks{verb}" not in source


# ---- cells come from P8 transcripts, byte-exact (§6.2) ----


def _transcript(dirpath: Path, config: str, task: str, repeat: int, seed: int, output: str):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / f"{config}--{task}--r{repeat}.json").write_text(
        json.dumps(
            {
                "task": task,
                "config": config,
                "repeat": repeat,
                "passed": True,
                "outcome": "pass",
                "seed": seed,
                "output": output,
                "messages": [],
            }
        )
    )


@pytest.fixture
def asset_tree(tmp_path, monkeypatch):
    root = tmp_path / "assets"
    (root / "evals" / "tasks").mkdir(parents=True)
    (root / "evals" / "perturbations").mkdir(parents=True)
    # structured() resolves its retry budget from the profile assets, so a synthetic
    # asset root still needs the real contract/profile pack beside the fake tasks.
    for pack in ("profiles", "contracts"):
        shutil.copytree(ASSETS / pack, root / pack)
    (root / "evals" / "tasks" / "alpha.yaml").write_text(
        yaml.safe_dump({"name": "alpha", "family": "f", "prompt": "ALPHA PROMPT"})
    )
    (root / "evals" / "tasks" / "beta.yaml").write_text(
        yaml.safe_dump({"name": "beta", "family": "f", "prompt": "BETA PROMPT"})
    )
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(root))
    return root


def test_load_cases_reads_task_seed_and_byte_exact_output(asset_tree, tmp_path):
    dirpath = tmp_path / "transcripts"
    _transcript(dirpath, "critique", "alpha", 0, 111, '{"port": 9443}')
    cases = criticreplay.load_cases(dirpath)
    assert len(cases) == 1
    assert cases[0].task == "alpha" and cases[0].seed == 111 and cases[0].repeat == 0
    assert cases[0].output == '{"port": 9443}'
    assert cases[0].prompt == "ALPHA PROMPT"


def test_load_cases_filters_by_task(asset_tree, tmp_path):
    dirpath = tmp_path / "transcripts"
    _transcript(dirpath, "critique", "alpha", 0, 111, "a")
    _transcript(dirpath, "critique", "beta", 0, 222, "b")
    assert [c.task for c in criticreplay.load_cases(dirpath, tasks=["beta"])] == ["beta"]


def test_load_cases_rejects_two_transcripts_that_disagree_about_one_cell(asset_tree, tmp_path):
    """Success criterion 6: a {task}/{output} region that differs for the same cell."""
    dirpath = tmp_path / "transcripts"
    _transcript(dirpath, "critique", "alpha", 0, 111, "answer one")
    _transcript(dirpath, "full", "alpha", 0, 111, "answer two")
    with pytest.raises(criticreplay.PerturbationError, match="disagree"):
        criticreplay.load_cases(dirpath)


def test_load_cases_requires_a_pinned_seed(asset_tree, tmp_path):
    dirpath = tmp_path / "transcripts"
    _transcript(dirpath, "critique", "alpha", 0, 111, "a")
    path = dirpath / "critique--alpha--r0.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "seed": None}))
    with pytest.raises(criticreplay.PerturbationError, match="seed"):
        criticreplay.load_cases(dirpath)


def test_load_cases_skips_runs_with_no_answer(asset_tree, tmp_path):
    dirpath = tmp_path / "transcripts"
    _transcript(dirpath, "critique", "alpha", 0, 111, "a")
    path = dirpath / "critique--alpha--r0.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "output": None}))
    assert criticreplay.load_cases(dirpath) == []


# ---- rubric variants (§6.2) ----


def test_rubric_spec_accepts_a_filesystem_path(tmp_path):
    path = tmp_path / "r.yaml"
    path.write_text((ASSETS / "rubrics" / "task-completion.yaml").read_text())
    variant = criticreplay.parse_rubric_arg(f"before={path}")
    assert variant.label == "before" and variant.rubric.name == "task-completion"
    assert variant.ref == str(path)
    assert variant.rubric.threshold == 7


def test_rubric_spec_accepts_a_git_ref():
    variant = criticreplay.parse_rubric_arg(
        "A-asfiled=git:d2f78b7:assets/rubrics/task-completion.yaml"
    )
    assert variant.ref == "d2f78b7"
    assert variant.rubric.prompt == _shipped_template()


def test_rubric_spec_rejects_a_missing_label():
    with pytest.raises(criticreplay.PerturbationError, match="LABEL=SPEC"):
        criticreplay.parse_rubric_arg("assets/rubrics/task-completion.yaml")


def test_rubric_spec_rejects_a_rubric_without_placeholders(tmp_path):
    path = tmp_path / "r.yaml"
    path.write_text(
        yaml.safe_dump({"name": "x", "threshold": 7, "prompt": "no slots", "schema": {}})
    )
    with pytest.raises(criticreplay.PerturbationError, match="placeholder"):
        criticreplay.parse_rubric_arg(f"x={path}")


# ---- the replay itself (§6.1: bypass CritiqueGate, go through structured()) ----


class ScriptedCritic:
    """A fake critic whose verdict is a pure function of the prompt bytes.

    Carries the two attributes the harness duck-types on (`seed`, the
    `response_format` capability memo) so the constrained-decoding tier is exercised
    offline exactly as it would be on the wire.
    """

    def __init__(self, scorer, model="fake-14b"):
        self.scorer = scorer
        self.model = model
        self.seed = None
        self._response_format_unsupported = False
        self.calls = []

    def chat(self, messages, tools=None, response_format=None):
        prompt = next(m.content for m in messages if m.role == "user")
        self.calls.append(
            {"messages": list(messages), "seed": self.seed, "response_format": response_format}
        )
        verdict = {"reasoning": "r", "score": self.scorer(prompt), "feedback": "f"}
        return Response(
            message=Message(role="assistant", content=json.dumps(verdict)), usage=Usage(100, 20)
        )


def _rubric(prompt, threshold=7):
    return Rubric(
        name="task-completion",
        threshold=threshold,
        prompt=prompt,
        schema={
            "type": "object",
            "required": ["score", "feedback"],
            "properties": {"score": {"type": "integer"}, "feedback": {"type": "string"}},
        },
    )


def _case(task="alpha", repeat=0, seed=111):
    return Case(task=task, repeat=repeat, seed=seed, prompt="TASK", output="OUT")


Case = criticreplay.Case


def test_replay_issues_one_request_per_replay_and_never_memoizes_a_verdict():
    """§6.1: CritiqueGate's prompt-bytes memo would collapse N replays into one call."""
    client = ScriptedCritic(lambda p: 9)
    scores = criticreplay.replay_scores(client, _rubric("T:{task} A:{output}\n"), _case(), 5)
    assert scores == [9, 9, 9, 9, 9]
    assert len(client.calls) == 5


def test_replay_pins_the_cells_seed_on_the_client():
    client = ScriptedCritic(lambda p: 9)
    criticreplay.replay_scores(client, _rubric("T:{task} A:{output}"), _case(seed=2331795949), 2)
    assert [c["seed"] for c in client.calls] == [2331795949, 2331795949]


def test_replay_goes_through_structured_not_a_hand_rolled_request():
    """§6.1: request construction is load-bearing — a hand-built probe scored 9 for 5."""
    from bantamkit.agent import response_format_for
    from bantamkit.contract import schema_instruction

    rubric = _rubric("T:{task} A:{output}")
    client = ScriptedCritic(lambda p: 9)
    criticreplay.replay_scores(client, rubric, _case(), 1)
    sent = client.calls[0]["messages"]
    assert sent[0].role == "system" and sent[0].content == schema_instruction(rubric.schema)
    assert sent[1].role == "user" and sent[1].content == "T:TASK A:OUT"
    assert client.calls[0]["response_format"] == response_format_for(rubric.schema)


def test_replay_reports_tokens_per_replay():
    client = ScriptedCritic(lambda p: 9)
    verdicts = criticreplay.replay_verdicts(client, _rubric("T:{task} A:{output}"), _case(), 2)
    assert [(v.tokens_in, v.tokens_out) for v in verdicts] == [(100, 20), (100, 20)]
    assert all(v.calls == 1 for v in verdicts)


# ---- the run and the decision rule (§7) ----


TINY_POINTS = [
    {"id": "identity", "class": "identity", "rule": "identity", "op": "identity"},
    {
        "id": "W1-trailing-newline",
        "class": "whitespace",
        "rule": "strip-trailing-newline",
        "op": "strip-trailing-newline",
    },
    {
        "id": "X-anchored",
        "class": "whitespace",
        "rule": "double-space",
        "op": "replace",
        "replace": [{"from": "ONE. ", "to": "ONE.  "}],
    },
]


def _write_manifest(root: Path, points=None, rubric="task-completion") -> Path:
    path = root / "evals" / "perturbations" / f"{rubric}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "rubric": rubric,
                "requirement_inventory": ["only one thing is required"],
                "points": points if points is not None else TINY_POINTS,
            },
            sort_keys=False,
        )
    )
    return path


def _write_rubric(root: Path, name: str, prompt: str, threshold: int = 7) -> Path:
    path = root / f"{name}.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "task-completion",
                "threshold": threshold,
                "prompt": prompt,
                "schema": {
                    "type": "object",
                    "required": ["score", "feedback"],
                    "properties": {
                        "score": {"type": "integer"},
                        "feedback": {"type": "string"},
                    },
                },
            },
            sort_keys=False,
        )
    )
    return path


BASE_PROMPT = "ONE. TWO\nT:{task}\nA:{output}\n"
CHANGED_PROMPT = "ONE. TWO CHANGED\nT:{task}\nA:{output}\n"
# The two `identity` prompts, rendered. Scorers key on these exactly: every other point
# in the tiny family also ends "A:OUT", so a suffix test would score them all alike.
BEFORE_IDENTITY = "ONE. TWO\nT:ALPHA PROMPT\nA:OUT\n"
AFTER_IDENTITY = "ONE. TWO CHANGED\nT:ALPHA PROMPT\nA:OUT\n"


@pytest.fixture
def rig(asset_tree, tmp_path):
    """One tiny rubric pair, one manifest, two cells — everything the run loop needs."""
    manifest_path = _write_manifest(asset_tree)
    before = _write_rubric(tmp_path, "before", BASE_PROMPT)
    after = _write_rubric(tmp_path, "after", CHANGED_PROMPT)
    transcripts = tmp_path / "transcripts"
    _transcript(transcripts, "critique", "alpha", 0, 111, "OUT")
    _transcript(transcripts, "critique", "alpha", 1, 222, "OUT")
    return {
        "manifest": criticreplay.load_manifest(manifest_path),
        "variants": [
            criticreplay.parse_rubric_arg(f"before={before}"),
            criticreplay.parse_rubric_arg(f"after={after}"),
        ],
        "cases": criticreplay.load_cases(transcripts),
        "transcripts": transcripts,
        "before": before,
        "after": after,
    }


def _run(rig, scorer, **kw):
    client = ScriptedCritic(scorer)
    result = criticreplay.run(
        client, rig["variants"], rig["manifest"], rig["cases"], model=client.model, **kw
    )
    return client, result


def test_run_emits_one_row_per_variant_cell_point_replay(rig):
    _, result = _run(rig, lambda p: 9, replays=1, identity_replays=5)
    # 2 variants x 2 cells x (2 perturbation points x 1 + identity x 5)
    assert len(result.rows) == 2 * 2 * (2 + 5)
    identity = [r for r in result.rows if r.point == "identity"]
    assert len(identity) == 2 * 2 * 5
    assert sorted({r.replay for r in identity}) == [0, 1, 2, 3, 4]


def test_identity_only_runs_only_the_identity_point(rig):
    """RB-P15's standing check: the same module, one flag (§8)."""
    _, result = _run(rig, lambda p: 9, identity_only=True, identity_replays=3)
    assert {r.point for r in result.rows} == {"identity"}
    assert len(result.rows) == 2 * 2 * 3


def test_rows_carry_the_columns_the_spec_names(rig):
    _, result = _run(rig, lambda p: 9)
    row = result.rows[0].row()
    assert set(row) == {
        "bar", "variant", "rubric_ref", "rubric_sha256", "manifest_sha256", "task", "seed",
        "repeat", "model", "point", "class", "rule", "replay", "prompt_sha256",
        "payload_sha256", "score", "threshold", "passed", "feedback", "tokens_in", "tokens_out",
    }
    assert row["bar"] == "perturbation" and row["threshold"] == 7
    assert row["class"] in ("identity", "whitespace", "order", "paraphrase")
    assert json.dumps(row)  # JSONL-writable


def test_prompt_and_payload_shas_are_recorded_separately(rig):
    _, result = _run(rig, lambda p: 9)
    row = result.rows[0]
    assert row.prompt_sha256 != row.payload_sha256
    assert len(row.prompt_sha256) == 64 and len(row.payload_sha256) == 64


def test_run_drops_a_rule_whose_anchor_is_absent_from_a_variant(tmp_path, asset_tree):
    manifest = criticreplay.load_manifest(_write_manifest(asset_tree))
    kept = criticreplay.parse_rubric_arg(f"kept={_write_rubric(tmp_path, 'k', BASE_PROMPT)}")
    # no trailing newline in the template -> W1's anchor is absent
    unterminated = _write_rubric(tmp_path, "l", "ONE. TWO\nT:{task}\nA:{output}")
    lost = criticreplay.parse_rubric_arg(f"lost={unterminated}")
    transcripts = tmp_path / "t"
    _transcript(transcripts, "critique", "alpha", 0, 111, "OUT")
    client = ScriptedCritic(lambda p: 9)
    result = criticreplay.run(
        client, [kept, lost], manifest, criticreplay.load_cases(transcripts), model="m"
    )
    assert result.dropped == {"kept": [], "lost": ["W1-trailing-newline"]}
    summary = criticreplay.summarize(result, manifest.sha256)
    comparison = summary["cells"][0]["comparisons"][0]
    assert comparison["family_size"] == 2
    assert comparison["dropped_rules"] == [{"rule": "W1-trailing-newline", "variant": "lost"}]
    assert summary["cells"][0]["variants"]["kept"]["pass_rate"] == "3/3"


def test_summary_reports_pass_rate_spread_margin_zero_and_fragility(rig):
    # identity fails at 5, everything else passes at 9 -> min and max straddle threshold 7
    _, result = _run(rig, lambda p: 5 if p == BEFORE_IDENTITY else 9)
    summary = criticreplay.summarize(result, rig["manifest"].sha256)
    cell = summary["cells"][0]["variants"]["before"]
    assert cell["pass_rate"] == "2/3"
    assert (cell["score_min"], cell["score_max"], cell["spread"]) == (5, 9, 4)
    assert cell["identity_scores"] == [5, 5, 5, 5, 5]
    assert cell["identity_spread"] == 0
    assert cell["fragile"] is True
    assert cell["margin_zero"] == 0


def test_margin_zero_counts_points_within_one_of_threshold(rig):
    _, result = _run(rig, lambda p: 8)
    summary = criticreplay.summarize(result, rig["manifest"].sha256)
    assert summary["cells"][0]["variants"]["before"]["margin_zero"] == 3


def test_a_family_that_never_crosses_the_threshold_is_not_fragile(rig):
    _, result = _run(rig, lambda p: 9)
    summary = criticreplay.summarize(result, rig["manifest"].sha256)
    assert summary["cells"][0]["variants"]["before"]["fragile"] is False


def test_pairwise_verdict_is_indistinguishable_when_pass_rates_are_equal(rig):
    _, result = _run(rig, lambda p: 9)
    summary = criticreplay.summarize(result, rig["manifest"].sha256)
    comparison = summary["cells"][0]["comparisons"][0]
    assert comparison["a"] == "before" and comparison["b"] == "after"
    assert comparison["verdict"] == "indistinguishable"
    assert comparison["family_size"] == 3


def test_pairwise_verdict_is_distinguishable_only_on_all_versus_none(rig):
    _, result = _run(rig, lambda p: 2 if "CHANGED" in p else 9)
    summary = criticreplay.summarize(result, rig["manifest"].sha256)
    comparison = summary["cells"][0]["comparisons"][0]
    assert comparison["verdict"] == "distinguishable"
    assert (comparison["a_pass_rate"], comparison["b_pass_rate"]) == ("3/3", "0/3")
    assert comparison["attributable"] is True


def test_pairwise_verdict_is_inconclusive_when_neither_family_is_unanimous(rig):
    _, result = _run(rig, lambda p: 2 if p == AFTER_IDENTITY else 9)
    comparison = criticreplay.summarize(result, rig["manifest"].sha256)["cells"][0][
        "comparisons"
    ][0]
    assert comparison["verdict"] == "inconclusive"
    assert comparison["attributable"] is False


def test_fragility_voids_attribution_even_when_separation_fires(rig):
    """§7 rule 2: a fragile family voids attribution on that cell even if rule 1 fires.

    `after` fails at every point (0/F, so rule 1 fires against `before`'s F/F) but its
    identity replays straddle the threshold, so its min and max straddle it too. The
    separation is real and the attribution is still void.
    """
    flip = iter([9, 5] * 100)

    def scorer(prompt):
        if prompt == AFTER_IDENTITY:
            return next(flip)
        return 2 if "CHANGED" in prompt else 9

    _, result = _run(rig, scorer)
    summary = criticreplay.summarize(result, rig["manifest"].sha256)
    cell = summary["cells"][0]
    assert cell["variants"]["after"]["fragile"] is True
    assert cell["variants"]["after"]["identity_spread"] == 4
    comparison = cell["comparisons"][0]
    assert (comparison["a_pass_rate"], comparison["b_pass_rate"]) == ("3/3", "0/3")
    assert comparison["verdict"] == "distinguishable"
    assert comparison["fragile"] == ["after"]
    assert comparison["attributable"] is False


def test_every_cell_is_reported_individually_never_pooled(rig):
    """§7 rule 3: averaging across cells hides one cell carrying the whole result."""
    _, result = _run(rig, lambda p: 9)
    summary = criticreplay.summarize(result, rig["manifest"].sha256)
    assert [(c["task"], c["repeat"], c["seed"]) for c in summary["cells"]] == [
        ("alpha", 0, 111),
        ("alpha", 1, 222),
    ]


def test_mismatched_post_drop_rule_sets_are_a_hard_error(rig):
    """§10 step 2 / success criterion 6: never report across mismatched families."""
    _, result = _run(rig, lambda p: 9)
    result.rows = [r for r in result.rows if not (r.variant == "after" and r.point == "X-anchored")]
    with pytest.raises(criticreplay.PerturbationError, match="post-drop"):
        criticreplay.summarize(result, rig["manifest"].sha256)


def test_variants_with_different_thresholds_are_refused(tmp_path, asset_tree):
    manifest = criticreplay.load_manifest(_write_manifest(asset_tree))
    a = criticreplay.parse_rubric_arg(f"a={_write_rubric(tmp_path, 'a', BASE_PROMPT, 7)}")
    b = criticreplay.parse_rubric_arg(f"b={_write_rubric(tmp_path, 'b', BASE_PROMPT, 8)}")
    transcripts = tmp_path / "t"
    _transcript(transcripts, "critique", "alpha", 0, 111, "OUT")
    with pytest.raises(criticreplay.PerturbationError, match="threshold"):
        criticreplay.run(
            ScriptedCritic(lambda p: 9), [a, b], manifest,
            criticreplay.load_cases(transcripts), model="m",
        )


def test_summary_records_requests_tokens_total_and_the_manifest_sha(rig):
    client, result = _run(rig, lambda p: 9)
    summary = criticreplay.summarize(result, rig["manifest"].sha256)
    assert summary["requests"] == len(client.calls) == 28
    assert summary["tokens_total"] == 28 * 120
    assert summary["manifest_sha256"] == rig["manifest"].sha256
    assert summary["bar"] == "perturbation"


def test_routine_before_after_profile_costs_at_most_96_requests(asset_tree, tmp_path):
    """Success criterion 9, on the shipped 12-point family: 2 variants x 3 cells."""
    real = ASSETS / "evals" / "perturbations" / "task-completion.yaml"
    (asset_tree / "evals" / "perturbations" / "task-completion.yaml").write_text(real.read_text())
    manifest = criticreplay.load_manifest(rubric_name="task-completion")
    base = _shipped_template()
    variants = [
        criticreplay.parse_rubric_arg(f"before={_write_rubric(tmp_path, 'b', base)}"),
        criticreplay.parse_rubric_arg(f"after={_write_rubric(tmp_path, 'a', base + chr(10))}"),
    ]
    transcripts = tmp_path / "t"
    for repeat, seed in enumerate((2331795949, 4094558621, 634446002)):
        _transcript(transcripts, "critique", "alpha", repeat, seed, '{"port": 9443}')
    client = ScriptedCritic(lambda p: 9)
    result = criticreplay.run(
        client, variants, manifest, criticreplay.load_cases(transcripts), model="m"
    )
    summary = criticreplay.summarize(result, manifest.sha256)
    assert summary["requests"] == 96
    assert all(len(c["comparisons"]) == 1 for c in summary["cells"])


# ---- CLI (§6.2, §6.3) ----


def test_cli_help_runs(capsys):
    with pytest.raises(SystemExit) as excinfo:
        criticreplay.main(["--help"])
    assert excinfo.value.code == 0
    assert "--identity-only" in capsys.readouterr().out


def test_cli_writes_jsonl_rows_and_a_summary(rig, tmp_path, monkeypatch, capsys):
    client = ScriptedCritic(lambda p: 9)
    monkeypatch.setattr(criticreplay, "OpenAICompatible", lambda **kw: client)
    rows_path, summary_path = tmp_path / "rows.jsonl", tmp_path / "summary.json"
    criticreplay.main(
        [
            "--base-url", "http://x", "--model", "fake-14b",
            "--rubric", f"before={rig['before']}", "--rubric", f"after={rig['after']}",
            "--transcripts", str(rig["transcripts"]),
            "--json", str(rows_path), "--summary", str(summary_path),
        ]
    )
    rows = [json.loads(line) for line in rows_path.read_text().splitlines()]
    assert len(rows) == 28 and rows[0]["bar"] == "perturbation"
    summary = json.loads(summary_path.read_text())
    assert summary["cells"][0]["comparisons"][0]["verdict"] == "indistinguishable"
    out = capsys.readouterr().out
    assert "before" in out and "pass" in out


def test_cli_restricts_to_named_tasks(rig, tmp_path, monkeypatch):
    _transcript(rig["transcripts"], "critique", "beta", 0, 333, "OUT")
    client = ScriptedCritic(lambda p: 9)
    monkeypatch.setattr(criticreplay, "OpenAICompatible", lambda **kw: client)
    rows_path = tmp_path / "rows.jsonl"
    criticreplay.main(
        [
            "--base-url", "http://x", "--model", "m",
            "--rubric", f"before={rig['before']}",
            "--transcripts", str(rig["transcripts"]), "--task", "beta",
            "--json", str(rows_path),
        ]
    )
    rows = [json.loads(line) for line in rows_path.read_text().splitlines()]
    assert {r["task"] for r in rows} == {"beta"}


def test_cli_exits_non_zero_on_a_perturbation_error(rig, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(criticreplay, "OpenAICompatible", lambda **kw: object())
    with pytest.raises(SystemExit) as excinfo:
        criticreplay.main(
            [
                "--base-url", "http://x", "--model", "m",
                "--rubric", f"before={rig['before']}",
                "--transcripts", str(tmp_path / "nope"),
            ]
        )
    assert excinfo.value.code == 1
    assert "no transcripts" in capsys.readouterr().err


def test_cli_rejects_a_replay_count_below_one(rig, monkeypatch):
    monkeypatch.setattr(criticreplay, "OpenAICompatible", lambda **kw: object())
    with pytest.raises(SystemExit):
        criticreplay.main(
            [
                "--base-url", "http://x", "--model", "m",
                "--rubric", f"before={rig['before']}",
                "--transcripts", str(rig["transcripts"]), "--replays", "0",
            ]
        )
