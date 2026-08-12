"""The perturbation bar (RB-P14): family construction, admissibility, and the decision rule.

Offline only. Every model call in here is a fake — the acceptance run against a live
model is a separate, deliberately fresh-eyed pass (spec §10).
"""

from __future__ import annotations

import json
import re
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
    """§3.3 step 3: an instance a reader cannot check at a glance is not defensible.

    The predecessor of this test asserted the shipped anchors have no `". "` and no
    trailing `.` — which pins the ACCIDENT that all three happen to anchor on
    sub-sentence fragments, not the rule. "One sentence per instance" admits a whole
    sentence; what it forbids is an instance that runs past a sentence boundary, and
    the boundary can be a newline, because the template is hard-wrapped.
    """
    for point in manifest.points:
        if point.point_class != "paraphrase":
            continue
        assert point.op == "replace" and len(point.replace) == 1, point.id
        for op in point.replace:
            assert not criticreplay._spans_a_sentence_boundary(op["from"]), point.id
            assert not criticreplay._spans_a_sentence_boundary(op["to"]), point.id


# §3.3 step 3, guard 2 — the two tables, over all 22 frozen prompts, as LITERAL data.
#
# Guard 2 forbids a word "the point adds or removes" from appearing in the cell. The
# spec says that twice, in two sentences that do not agree, and the user's ruling
# (2026-08-12) is that both readings are computed and reported and NEITHER is called
# wrong. These two dicts are the tables each reading produces. They are derived from the
# spec's wording and from the frozen prompt texts — NOT by calling the function under
# test — because a golden table written by calling the implementation pins the author's
# method, which is exactly how this guard came to be under-reported twice.
#
# WHOLE-TEXT (§3.3's operative Test sentence: "the symmetric difference of the base and
# perturbed word sets must be disjoint from the task prompt's word set"). The word sets
# are of the whole template, so a word the edit removes from one clause but which still
# occurs elsewhere in the template is not in the difference:
#
#   P1  "You are a reviewer checking whether" -> "...who checks whether".
#       `checking` occurs only there, `who`/`checks` are new  -> {checking, checks, who}
#   P2  "the information the task asks for" -> "the information the task requests".
#       `asks` survives in "what the task asks for is missing the required content";
#       `for` survives in "Do NOT deduct points for formatting"          -> {requests}
#   P3  "present and right" -> "present and correct".
#       `correct` already occurs in "present and correct" in the opening -> {right}
#
# SUBSTITUTION-PAIR (§3.3 step 4's form: the instance IS the `from` -> `to` pair, so the
# words it moves are the pair's symmetric difference, whatever the rest of the template
# still says):
#
#   P1 -> {checking, checks, who}   P2 -> {asks, for, requests}   P3 -> {right, correct}
#
# The frozen prompts that contain those words:
#   who       recall-oncall ("who is on-call"), recall-oncall-rotation
#   for       nav-release-bundle, recall-cache-ttl, recall-env-endpoint, recall-oncall,
#             recall-oncall-rotation, recall-org-quota
#   requests  recall-org-quota ("requests-per-minute"). Reachable since the tokenizer
#             stopped treating a hyphen as word-internal (C2): under whole-text this is
#             P2's ONLY violation, and it is the row M1's committed screen recorded.
#   right     nav-prod-port ("follow the documentation to the right file")
#   asks / checking / checks / correct  — none of the 22
WHOLE_TEXT_TABLE = {
    "P1-reviewer-relative": {
        "recall-oncall": ["who"],
        "recall-oncall-rotation": ["who"],
    },
    "P2-asks-requests": {"recall-org-quota": ["requests"]},
    "P3-right-correct": {"nav-prod-port": ["right"]},
}

SUBSTITUTION_PAIR_TABLE = {
    "P1-reviewer-relative": {
        "recall-oncall": ["who"],
        "recall-oncall-rotation": ["who"],
    },
    "P2-asks-requests": {
        "nav-release-bundle": ["for"],
        "recall-cache-ttl": ["for"],
        "recall-env-endpoint": ["for"],
        "recall-oncall": ["for"],
        "recall-oncall-rotation": ["for"],
        "recall-org-quota": ["for", "requests"],
    },
    "P3-right-correct": {"nav-prod-port": ["right"]},
}

# What the run's decision rule acts on: tainted if EITHER reading flags it.
UNION_TABLE = {
    "P1-reviewer-relative": {
        "recall-oncall": ["who"],
        "recall-oncall-rotation": ["who"],
    },
    "P2-asks-requests": {
        "nav-release-bundle": ["for"],
        "recall-cache-ttl": ["for"],
        "recall-env-endpoint": ["for"],
        "recall-oncall": ["for"],
        "recall-oncall-rotation": ["for"],
        "recall-org-quota": ["for", "requests"],
    },
    "P3-right-correct": {"nav-prod-port": ["right"]},
}


def _frozen_prompts() -> dict[str, str]:
    return {
        path.stem: yaml.safe_load(path.read_text())["prompt"]
        for path in sorted((ASSETS / "evals" / "tasks").glob("*.yaml"))
    }


def _measured_tables(manifest) -> dict[str, dict[str, dict[str, list[str]]]]:
    base = _shipped_template()
    tables: dict[str, dict[str, dict[str, list[str]]]] = {r: {} for r in criticreplay.READINGS}
    for name, prompt in _frozen_prompts().items():
        for point in manifest.points:
            hit = criticreplay.shared_token_violations(point, prompt, base)
            for reading, words in hit.items():
                if words:
                    tables[reading].setdefault(point.id, {})[name] = words
    return tables


def test_the_frozen_suite_is_still_the_twenty_two_prompts_these_tables_cover():
    assert len(_frozen_prompts()) == 22


def test_guard_two_whole_text_reading_over_every_frozen_task_prompt(manifest):
    """The reading an independent reviewer derived from §3.3's Test sentence alone.

    It matches the table already committed in M1's pre-registered screen. Under it `P2`
    violates via the added word `requests` on `recall-org-quota` only — `asks` and `for`
    both survive elsewhere in the template, so neither leaves the critic's input.
    """
    assert _measured_tables(manifest)["whole-text"] == WHOLE_TEXT_TABLE


def test_guard_two_substitution_pair_reading_over_every_frozen_task_prompt(manifest):
    """The reading the manifest's own P2 justification prose implies.

    Under it the preposition `for` violates on six tasks, because the instance is the
    `from` -> `to` pair and the pair drops `for` whatever the rest of the template says.
    """
    assert _measured_tables(manifest)["substitution-pair"] == SUBSTITUTION_PAIR_TABLE


def test_the_two_readings_disagree_on_p2_which_is_why_both_are_reported(manifest):
    """The whole reason the user ruled 'report both': the readings disagree, on P2.

    Neither is wrong. `for` is flagged by substitution-pair and not by whole-text
    because it survives elsewhere in the template; both are defensible readings of the
    same spec section, in two different sentences of it.
    """
    tables = _measured_tables(manifest)
    assert tables["whole-text"].get("P2-asks-requests") != tables["substitution-pair"].get(
        "P2-asks-requests"
    )
    assert tables["whole-text"]["P1-reviewer-relative"] == tables["substitution-pair"][
        "P1-reviewer-relative"
    ]


def test_the_union_of_both_readings_is_what_the_decision_rule_acts_on(manifest):
    """Pinned as its own table: the set a run treats as tainted on the frozen suite."""
    tables = _measured_tables(manifest)
    union: dict[str, dict[str, list[str]]] = {}
    for reading in criticreplay.READINGS:
        for point, hits in tables[reading].items():
            for task, words in hits.items():
                merged = set(union.setdefault(point, {}).get(task, [])) | set(words)
                union[point][task] = sorted(merged)
    assert union == UNION_TABLE


def test_both_tables_reproduce_under_a_tokenizer_written_from_the_spec_not_the_module(
    manifest,
):
    """The reviewer's objection, made mechanical.

    A golden table produced by calling `shared_token_violations` pins whatever that
    function happens to do. This re-derives both tables with a tokenizer written from
    §3.3's own words — "tokenize on word boundaries" — that shares no code with the
    module, and requires the literal tables above to come out of it too. It is also
    what caught C2: a tokenizer that reads `requests-per-minute` as three words finds
    `requests` where the module's found nothing.
    """
    spec_words = lambda text: set(re.findall(r"[a-z]+", text.lower()))  # noqa: E731
    base = _shipped_template()
    tables: dict[str, dict[str, dict[str, list[str]]]] = {"whole-text": {}, "substitution-pair": {}}
    for point in manifest.points:
        perturbed = criticreplay.apply_point(point, base)
        if perturbed is None:
            continue
        moved = {"whole-text": spec_words(base) ^ spec_words(perturbed), "substitution-pair": set()}
        for op in point.replace:
            moved["substitution-pair"] |= spec_words(op["from"]) ^ spec_words(op["to"])
        for name, prompt in _frozen_prompts().items():
            for reading, words in moved.items():
                shared = sorted(words & spec_words(prompt))
                if shared:
                    tables[reading].setdefault(point.id, {})[name] = shared
    assert tables["whole-text"] == WHOLE_TEXT_TABLE
    assert tables["substitution-pair"] == SUBSTITUTION_PAIR_TABLE


# C2. Every hyphenated compound that occurs in a frozen task prompt. A tokenizer that
# treats the hyphen as word-internal reads each of these as ONE token, so a point that
# adds or removes `requests`, `call`, `svc`, `per`, `minute` or `billing` shares a word
# with the cell and the guard reports clean. That is a FALSE NEGATIVE — the direction
# guard 2 exists to prevent — and it is true under both readings.
HYPHENATED_IN_THE_FROZEN_SUITE = {
    "INV-42": ("extract-invoice",),
    "billing-svc": ("nav-prod-port",),
    "on-call": ("recall-oncall",),
    "requests-per-minute": ("recall-org-quota",),
}


def test_the_hyphenated_compounds_this_covers_are_the_whole_frozen_inventory():
    """Derived from the prompts, not asserted about them: a new compound fails here."""
    found: dict[str, set[str]] = {}
    for name, text in _frozen_prompts().items():
        for compound in re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+", text):
            found.setdefault(compound, set()).add(name)
    assert {k: tuple(sorted(v)) for k, v in sorted(found.items())} == (
        HYPHENATED_IN_THE_FROZEN_SUITE
    )


def test_a_hyphen_does_not_hide_the_words_inside_a_compound(manifest):
    """C2: the guard must see `requests` in `requests-per-minute`."""
    for compound in HYPHENATED_IN_THE_FROZEN_SUITE:
        expected = {part for part in compound.lower().split("-") if part[:1].isalpha()}
        assert criticreplay._words(compound) == expected, compound
    quota = _frozen_prompts()["recall-org-quota"]
    assert {"requests", "per", "minute"} <= criticreplay._words(quota)


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


class RetryOnceCritic(ScriptedCritic):
    """Unparseable on the very first call, so `structured()` retries exactly once."""

    def chat(self, messages, tools=None, response_format=None):
        response = super().chat(messages, tools, response_format=response_format)
        if len(self.calls) == 1:
            return Response(
                message=Message(role="assistant", content="not json"), usage=Usage(100, 20)
            )
        return response


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
        "calls", "guard_violations", "guard_readings",
    }
    assert row["guard_violations"] == []
    assert row["guard_readings"] == {"whole-text": [], "substitution-pair": []}
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


def test_a_retried_request_shows_up_as_more_wire_calls_than_rows(rig):
    """`requests` counts rows; a `structured()` retry only moves `wire_calls`.

    Without this the tokens column can inflate while `requests` stays put, and a reader
    cannot tell a retry from a more expensive prompt (N4's minor 4).
    """
    client = RetryOnceCritic(lambda p: 9)
    result = criticreplay.run(
        client, rig["variants"], rig["manifest"], rig["cases"], model=client.model
    )
    summary = criticreplay.summarize(result, rig["manifest"].sha256)
    assert summary["requests"] == len(result.rows)
    assert summary["wire_calls"] == summary["requests"] + 1
    retried = [r for r in result.rows if r.calls == 2]
    assert len(retried) == 1
    assert all(r.calls == 1 for r in result.rows if r is not retried[0])


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


# ---- the shared-token guard in the RUN path (§3.3 step 3, guard 2; RB-P19) ----

# `alpha`'s task prompt is "ALPHA PROMPT" and its answer is "OUT", so `P-taskword`
# moves a word into the cell's {task} and `P-outword` moves one into its {output}.
GUARD_POINTS = [
    {"id": "identity", "class": "identity", "rule": "identity", "op": "identity"},
    {
        "id": "X-anchored",
        "class": "whitespace",
        "rule": "double-space",
        "op": "replace",
        "replace": [{"from": "ONE. ", "to": "ONE.  "}],
    },
    {
        "id": "P-taskword",
        "class": "paraphrase",
        "rule": "reword",
        "op": "replace",
        "replace": [{"from": "TWO", "to": "ALPHA"}],
        "justification": "moves the shared token ALPHA, which is in the cell's task",
    },
]

OUTWORD_POINT = {
    "id": "P-outword",
    "class": "paraphrase",
    "rule": "reword",
    "op": "replace",
    "replace": [{"from": "TWO", "to": "OUT"}],
    "justification": "moves the shared token OUT, which is the cell's whole answer",
}


@pytest.fixture
def guard_rig(asset_tree, tmp_path):
    """One cell whose {task} shares a word with a paraphrase point's edit."""
    manifest_path = _write_manifest(asset_tree, points=GUARD_POINTS)
    before = _write_rubric(tmp_path, "before", BASE_PROMPT)
    after = _write_rubric(tmp_path, "after", CHANGED_PROMPT)
    transcripts = tmp_path / "transcripts"
    _transcript(transcripts, "critique", "alpha", 0, 111, "OUT")
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


def test_a_guard_violating_point_still_runs_but_every_row_carries_the_reason(guard_rig):
    """The target property: a run cannot apply a violating point to a cell SILENTLY.

    Not an abort. Eight of the twenty screened cells violate, `nav-prod-port` among
    them, so a hard error would make the canonical cell of this line of work unrunnable
    — a regression, not a stricter guard. The point runs; the row says so.
    """
    client, result = _run(guard_rig, lambda p: 9)
    assert [r.point for r in result.rows if r.guard_violations] != []
    for row in result.rows:
        assert row.guard_violations == (["alpha"] if row.point == "P-taskword" else [])
    assert result.guard == {("alpha", 0): {"P-taskword": ["alpha"]}}
    assert result.guard_mode == "warn"


def test_the_guard_reads_the_cells_output_as_well_as_its_task(asset_tree, tmp_path):
    """§3.3 guard 2 is "the cell's `{task}` OR `{output}`" — the run path checks both.

    `shared_token_violations` takes one text and stays the offline primitive the frozen
    22-prompt table is pinned against; the run path has the whole cell and checks it.
    """
    manifest = criticreplay.load_manifest(
        _write_manifest(asset_tree, points=[*GUARD_POINTS[:2], OUTWORD_POINT])
    )
    variant = criticreplay.parse_rubric_arg(f"v={_write_rubric(tmp_path, 'v', BASE_PROMPT)}")
    transcripts = tmp_path / "t"
    _transcript(transcripts, "critique", "alpha", 0, 111, "OUT")
    result = criticreplay.run(
        ScriptedCritic(lambda p: 9), [variant], manifest,
        criticreplay.load_cases(transcripts), model="m",
    )
    assert result.guard == {("alpha", 0): {"P-outword": ["out"]}}


def test_guard_error_mode_refuses_before_a_single_request_goes_out(guard_rig):
    """The strict reading, available and opt-in: fail loud, spend nothing."""
    client = ScriptedCritic(lambda p: 9)
    with pytest.raises(criticreplay.PerturbationError, match="shared-token guard"):
        criticreplay.run(
            client, guard_rig["variants"], guard_rig["manifest"], guard_rig["cases"],
            model="m", guard="error",
        )
    assert client.calls == []


def test_guard_mode_error_names_every_violating_point_and_cell(guard_rig):
    client = ScriptedCritic(lambda p: 9)
    with pytest.raises(criticreplay.PerturbationError) as excinfo:
        criticreplay.run(
            client, guard_rig["variants"], guard_rig["manifest"], guard_rig["cases"],
            model="m", guard="error",
        )
    message = str(excinfo.value)
    assert "P-taskword" in message and "alpha" in message and "r0" in message


def test_an_unknown_guard_mode_is_refused(guard_rig):
    with pytest.raises(criticreplay.PerturbationError, match="guard mode"):
        criticreplay.run(
            ScriptedCritic(lambda p: 9), guard_rig["variants"], guard_rig["manifest"],
            guard_rig["cases"], model="m", guard="explode",
        )


def test_summary_reports_the_guard_dropped_family_beside_the_full_one(guard_rig):
    """Machine-readable in the committed artifact, not prose in docs/eval.md.

    `pass_rate` stays the full family so a run remains comparable with the committed
    anchor set's `expect_pass_rate`; `guard_dropped` is the same statistic recomputed
    with the tainted points removed, in the shape the anchor set already records.
    """
    _, result = _run(guard_rig, lambda p: 9)
    summary = criticreplay.summarize(result, guard_rig["manifest"].sha256)
    cell = summary["cells"][0]
    assert cell["guard_violations"] == {"P-taskword": ["alpha"]}
    stats = cell["variants"]["before"]
    assert stats["pass_rate"] == "3/3"
    assert stats["guard_violations"] == {"P-taskword": ["alpha"]}
    assert stats["guard_dropped"]["pass_rate"] == "2/2"
    assert stats["guard_dropped"]["family_size"] == 2
    assert summary["guard"]["mode"] == "warn"
    assert summary["guard"]["violations"] == [
        {
            "task": "alpha",
            "repeat": 0,
            "point": "P-taskword",
            "words": ["alpha"],
            "readings": {"whole-text": ["alpha"], "substitution-pair": ["alpha"]},
        }
    ]
    assert json.dumps(summary)


def test_a_clean_cell_reports_no_guard_drop_at_all(rig):
    _, result = _run(rig, lambda p: 9)
    summary = criticreplay.summarize(result, rig["manifest"].sha256)
    stats = summary["cells"][0]["variants"]["before"]
    assert stats["guard_violations"] == {}
    assert stats["guard_dropped"] is None
    assert summary["guard"]["violations"] == []
    assert summary["cells"][0]["comparisons"][0]["guard_family_size"] == 3


def test_the_guard_clean_verdict_is_reported_beside_the_full_family_verdict(guard_rig):
    """The whole sign of a difference came from a point that shares a token with the cell.

    `after` fails on the guard-violating point and nowhere else: the full family reads
    3/3 vs 2/3, `inconclusive`. Drop the tainted point and both families are unanimous —
    the guard-clean evidence says `indistinguishable`. That is the RB-P4 mechanism in
    miniature, and it is now a field in the artifact rather than something a reader has
    to notice.

    Note what §7 rule 1 makes true here: because `distinguishable` is all-versus-none,
    dropping a point can never turn a real separation into a false one — it can only
    shrink F, and in the limit empty it. So `guard_verdict` bites on `inconclusive` and
    on the fully-tainted cell; on a `distinguishable` cell its work is to publish the
    smaller F the separation actually rests on.
    """
    _, result = _run(guard_rig, lambda p: 2 if "ONE. ALPHA CHANGED" in p else 9)
    summary = criticreplay.summarize(result, guard_rig["manifest"].sha256)
    comparison = summary["cells"][0]["comparisons"][0]
    assert comparison["guard_dropped_rules"] == [
        {"rule": "P-taskword", "reason": "shared-token", "words": ["alpha"]}
    ]
    assert (comparison["a_pass_rate"], comparison["b_pass_rate"]) == ("3/3", "2/3")
    assert comparison["verdict"] == "inconclusive"
    assert comparison["family_size"] == 3
    assert comparison["guard_verdict"] == "indistinguishable"
    assert comparison["guard_family_size"] == 2
    assert comparison["attributable"] is False


def test_guard_dropping_leaves_the_verdict_alone_when_it_is_not_load_bearing(guard_rig):
    """The other side of the same rule: a separation the tainted point did not carry."""
    _, result = _run(guard_rig, lambda p: 2 if "CHANGED" in p else 9)
    comparison = criticreplay.summarize(result, guard_rig["manifest"].sha256)["cells"][0][
        "comparisons"
    ][0]
    assert comparison["verdict"] == "distinguishable"
    assert comparison["guard_verdict"] == "distinguishable"
    assert comparison["attributable"] is True


def test_a_cell_whose_whole_family_violates_reports_undefined_and_still_runs(
    asset_tree, tmp_path
):
    """The pathological case named in the brief: dropping everything credits nothing.

    It does not abort, and it does not silently report a pass rate over tainted points
    — the guard-clean family is empty, so the comparison is `undefined` and
    `attributable` is False.
    """
    manifest = criticreplay.load_manifest(_write_manifest(asset_tree, points=[GUARD_POINTS[2]]))
    variants = [
        criticreplay.parse_rubric_arg(f"a={_write_rubric(tmp_path, 'a', BASE_PROMPT)}"),
        criticreplay.parse_rubric_arg(f"b={_write_rubric(tmp_path, 'b', CHANGED_PROMPT)}"),
    ]
    transcripts = tmp_path / "t"
    _transcript(transcripts, "critique", "alpha", 0, 111, "OUT")
    result = criticreplay.run(
        ScriptedCritic(lambda p: 9), variants, manifest,
        criticreplay.load_cases(transcripts), model="m",
    )
    assert len(result.rows) == 2  # it ran
    summary = criticreplay.summarize(result, manifest.sha256)
    stats = summary["cells"][0]["variants"]["a"]
    assert stats["pass_rate"] == "1/1" and stats["guard_dropped"]["pass_rate"] == "0/0"
    comparison = summary["cells"][0]["comparisons"][0]
    assert comparison["guard_family_size"] == 0
    assert comparison["guard_verdict"] == "undefined"
    assert comparison["attributable"] is False


def test_the_table_names_the_guard_drop_so_a_reader_cannot_miss_it(guard_rig):
    _, result = _run(guard_rig, lambda p: 9)
    table = criticreplay.format_table(criticreplay.summarize(result, guard_rig["manifest"].sha256))
    assert "GUARD" in table
    assert "P-taskword" in table and "alpha" in table


# ---- guard 2's TWO readings, reported side by side (the user's ruling, 2026-08-12) ----
#
# `gamma`'s prompt is "TWO STEP GAMMA" and the template says TWO twice, so the point's
# edit removes `TWO` from the anchor while `TWO` survives elsewhere in the template.
# substitution-pair flags it; whole-text does not. That is the disagreement in
# miniature, and it is the same disagreement the shipped `P2-asks-requests` has.
SURVIVOR_PROMPT = "TWO GAMMA. ONE TWO\nT:{task}\nA:{output}\n"
SURVIVOR_POINT = {
    "id": "P-survivor",
    "class": "paraphrase",
    "rule": "reword",
    "op": "replace",
    "replace": [{"from": "ONE TWO", "to": "ONE THREE"}],
    "justification": "removes TWO from the anchor, but TWO survives elsewhere in the template",
}
# The mirror case. The substitution lands INSIDE a word, so the pair's word sets are
# {ght} / {sk} and the pair reading sees nothing the cell could share; the whole-text
# reading sees `bright` leave and `brisk` arrive, and the cell says BRISK.
INWORD_PROMPT = "A BRIGHT answer. ONE\nT:{task}\nA:{output}\n"
INWORD_POINT = {
    "id": "P-inword",
    "class": "paraphrase",
    "rule": "reword",
    "op": "replace",
    "replace": [{"from": "IGHT", "to": "ISK"}],
    "justification": "a substitution that lands inside a word, invisible to the pair reading",
}


def _reading_rig(asset_tree, tmp_path, prompt, point, task, task_prompt, output):
    (asset_tree / "evals" / "tasks" / f"{task}.yaml").write_text(
        yaml.safe_dump({"name": task, "family": "f", "prompt": task_prompt})
    )
    manifest = criticreplay.load_manifest(
        _write_manifest(asset_tree, points=[GUARD_POINTS[0], point])
    )
    variant = criticreplay.parse_rubric_arg(f"v={_write_rubric(tmp_path, 'v', prompt)}")
    transcripts = tmp_path / "t"
    _transcript(transcripts, "critique", task, 0, 111, output)
    return criticreplay.run(
        ScriptedCritic(lambda p: 9), [variant], manifest,
        criticreplay.load_cases(transcripts), model="m",
    ), manifest


def test_a_word_the_edit_removes_but_the_template_keeps_splits_the_two_readings(
    asset_tree, tmp_path
):
    """Both readings are computed, named, and disagree — and neither is dropped."""
    result, _ = _reading_rig(
        asset_tree, tmp_path, SURVIVOR_PROMPT, SURVIVOR_POINT, "gamma", "TWO STEP GAMMA", "OUT"
    )
    assert result.guard_readings["substitution-pair"] == {("gamma", 0): {"P-survivor": ["two"]}}
    assert result.guard_readings["whole-text"] == {}
    assert result.guard == {("gamma", 0): {"P-survivor": ["two"]}}


def test_a_substitution_inside_a_word_is_seen_only_by_the_whole_text_reading(
    asset_tree, tmp_path
):
    """The mirror: whole-text is not a subset of substitution-pair either.

    This is why the decision rule is the union rather than a choice: each reading is
    blind somewhere the other is not, and under-detection is the failure this guard
    exists to prevent.
    """
    result, _ = _reading_rig(
        asset_tree, tmp_path, INWORD_PROMPT, INWORD_POINT, "gamma", "A BRISK TASK", "OUT"
    )
    assert result.guard_readings["whole-text"] == {("gamma", 0): {"P-inword": ["brisk"]}}
    assert result.guard_readings["substitution-pair"] == {}
    assert result.guard == {("gamma", 0): {"P-inword": ["brisk"]}}


def test_every_row_carries_both_readings_by_name_beside_the_union(asset_tree, tmp_path):
    """Machine-readable in the committed JSONL, per point and per cell, by name."""
    result, _ = _reading_rig(
        asset_tree, tmp_path, SURVIVOR_PROMPT, SURVIVOR_POINT, "gamma", "TWO STEP GAMMA", "OUT"
    )
    tainted = [r for r in result.rows if r.point == "P-survivor"]
    assert tainted
    for row in tainted:
        assert row.guard_violations == ["two"]
        assert row.row()["guard_readings"] == {
            "whole-text": [],
            "substitution-pair": ["two"],
        }
    for row in result.rows:
        if row.point != "P-survivor":
            assert row.row()["guard_readings"] == {"whole-text": [], "substitution-pair": []}


def test_the_summary_names_both_readings_the_decision_rule_and_calls_neither_wrong(
    asset_tree, tmp_path
):
    result, manifest = _reading_rig(
        asset_tree, tmp_path, SURVIVOR_PROMPT, SURVIVOR_POINT, "gamma", "TWO STEP GAMMA", "OUT"
    )
    summary = criticreplay.summarize(result, manifest.sha256)
    guard = summary["guard"]
    assert sorted(guard["readings"]) == ["substitution-pair", "whole-text"]
    assert "union" in guard["decision_rule"]
    assert "NEITHER is wrong" in guard["rule"]
    assert guard["by_reading"]["substitution-pair"] == [
        {"task": "gamma", "repeat": 0, "point": "P-survivor", "words": ["two"]}
    ]
    assert guard["by_reading"]["whole-text"] == []
    assert guard["violations"][0]["words"] == ["two"]
    assert guard["violations"][0]["readings"] == {
        "whole-text": [],
        "substitution-pair": ["two"],
    }
    cell = summary["cells"][0]
    assert cell["guard_readings"] == {
        "whole-text": {},
        "substitution-pair": {"P-survivor": ["two"]},
    }
    assert cell["variants"]["v"]["guard_readings"] == {
        "whole-text": {},
        "substitution-pair": {"P-survivor": ["two"]},
    }
    assert json.dumps(summary)


def test_the_printed_table_shows_both_readings_for_every_violation(asset_tree, tmp_path):
    result, manifest = _reading_rig(
        asset_tree, tmp_path, SURVIVOR_PROMPT, SURVIVOR_POINT, "gamma", "TWO STEP GAMMA", "OUT"
    )
    table = criticreplay.format_table(criticreplay.summarize(result, manifest.sha256))
    assert "whole-text: (none)" in table
    assert "substitution-pair: two" in table
    assert "union" in table


def test_guard_error_mode_names_the_reading_that_flagged(asset_tree, tmp_path):
    """The strict reading still refuses before any spend, and says which reading fired."""
    (asset_tree / "evals" / "tasks" / "gamma.yaml").write_text(
        yaml.safe_dump({"name": "gamma", "family": "f", "prompt": "TWO STEP GAMMA"})
    )
    manifest = criticreplay.load_manifest(
        _write_manifest(asset_tree, points=[GUARD_POINTS[0], SURVIVOR_POINT])
    )
    variant = criticreplay.parse_rubric_arg(f"v={_write_rubric(tmp_path, 'v', SURVIVOR_PROMPT)}")
    transcripts = tmp_path / "t"
    _transcript(transcripts, "critique", "gamma", 0, 111, "OUT")
    client = ScriptedCritic(lambda p: 9)
    with pytest.raises(criticreplay.PerturbationError) as excinfo:
        criticreplay.run(
            client, [variant], manifest, criticreplay.load_cases(transcripts),
            model="m", guard="error",
        )
    message = str(excinfo.value)
    assert "substitution-pair=['two']" in message and "whole-text=[]" in message
    assert client.calls == []


def test_guard_table_is_public_so_a_hand_rolled_loop_can_call_it(asset_tree, tmp_path):
    """I6: guard 2 needs a cell, so it cannot ride inside `apply_point` — it ships as
    one public call instead, and `run()` uses the same one."""
    (asset_tree / "evals" / "tasks" / "gamma.yaml").write_text(
        yaml.safe_dump({"name": "gamma", "family": "f", "prompt": "TWO STEP GAMMA"})
    )
    manifest = criticreplay.load_manifest(
        _write_manifest(asset_tree, points=[GUARD_POINTS[0], SURVIVOR_POINT])
    )
    transcripts = tmp_path / "t"
    _transcript(transcripts, "critique", "gamma", 0, 111, "OUT")
    table = criticreplay.guard_table(
        manifest.points, criticreplay.load_cases(transcripts), {"v": SURVIVOR_PROMPT}
    )
    assert table == {
        ("gamma", 0): {"P-survivor": {"whole-text": [], "substitution-pair": ["two"]}}
    }
    assert criticreplay.guard_union(table[("gamma", 0)]["P-survivor"]) == ["two"]
    assert "guard_table" in criticreplay.__all__


# ---- the byte-identity floor: the whole offline run, against `f8404ab` ----
#
# The baseline in `data/` was produced by running `perturbation_baseline_harness.py`
# against a `git worktree` of `f8404ab` — the commit before the guarded-family
# refactor — NOT by re-running the refactored code and freezing its answer. That
# distinction is the whole value of the file: a golden expectation computed by the
# thing it checks pins the author's method, not the behaviour (RB-P19's transferable
# finding). It covers the JSONL rows, the summary dict, the printed guard sections,
# the identity-only path and the zero-spend `--guard error` refusal.

BASELINE = Path(__file__).resolve().parent / "data" / "f8404ab-perturbation-baseline.json"


def test_the_whole_offline_run_is_byte_identical_to_f8404ab(tmp_path):
    from perturbation_baseline_harness import produce, serialize

    expected = json.loads(BASELINE.read_text())
    produced = produce(criticreplay, tmp_path / "rubrics")
    for section in (
        "rows", "summary", "table", "identity_only", "guard_error_refusal", "synthetic",
    ):
        assert produced[section] == expected[section], section
    assert serialize(produced) == BASELINE.read_text()


def test_the_baseline_covers_a_populated_guard_table_and_a_zero_spend_refusal():
    """A floor that measured nothing would pass any refactor."""
    expected = json.loads(BASELINE.read_text())
    assert len(expected["rows"]) == 75
    assert len(expected["summary"]["guard"]["violations"]) >= 3
    readings = {r["point"]: r["readings"] for r in expected["summary"]["guard"]["violations"]}
    # The two readings disagree inside the baseline, so a refactor that collapsed them
    # into one could not pass it.
    assert readings["P2-asks-requests"]["whole-text"] != (
        readings["P2-asks-requests"]["substitution-pair"]
    )
    assert expected["guard_error_wire_calls"] == 0
    assert expected["guard_error_refusal"].startswith("shared-token guard")
    assert expected["dropped"] == {"L1": [], "L2": ["W1-trailing-newline"]}
    # And the union rule is load-bearing in the synthetic section, which the frozen
    # family cannot make it: there, union == substitution-pair by coincidence.
    synthetic = {
        v["point"]: v for v in expected["synthetic"]["summary"]["guard"]["violations"]
    }
    assert synthetic["P-survivor"]["readings"] == {
        "whole-text": [], "substitution-pair": ["two"]
    }
    assert synthetic["P-inword"]["readings"] == {
        "whole-text": ["brisk"], "substitution-pair": []
    }


# ---- the guard's three siblings in the RUN path (§3.3 step 3, guards 1, 3, 4) ----
#
# Guard 2 was defined-but-uncalled; so was guard 3's `FROZEN_KEYWORDS`, which lived in
# the run module and was read only by a test. Guards 1 and 4 had no definition at all.
# All three are properties of the POINT, independent of any cell, so unlike guard 2 they
# do not admit a per-cell drop: a point that moves a band digit is not meaning-preserving
# on any cell and there is nothing to salvage. They are refused at family construction,
# before any request.

GUARDED_PROMPT = (
    'Judge ONLY the answer. Score 9-10 = good; 5-8 = partial; 0-4 = bad.\n'
    'T:{task}\nA:{output}\nReturn {{"score": 1}}\n'
)


def _admissibility_rig(asset_tree, tmp_path, point):
    manifest = criticreplay.load_manifest(
        _write_manifest(asset_tree, points=[GUARD_POINTS[0], point])
    )
    variant = criticreplay.parse_rubric_arg(f"v={_write_rubric(tmp_path, 'v', GUARDED_PROMPT)}")
    transcripts = tmp_path / "t"
    _transcript(transcripts, "critique", "alpha", 0, 111, "OUT")
    client = ScriptedCritic(lambda p: 9)
    return client, (client, [variant], manifest, criticreplay.load_cases(transcripts))


def test_run_refuses_a_point_that_moves_a_frozen_contract_literal(asset_tree, tmp_path):
    """Guard 1. Band digits and schema keys are byte-frozen, in every class."""
    client, args = _admissibility_rig(
        asset_tree, tmp_path,
        {
            "id": "O-endash", "class": "order", "rule": "reorder", "op": "replace",
            "replace": [{"from": "Score 9-10", "to": "Score 9–10"}],
        },
    )
    with pytest.raises(criticreplay.PerturbationError, match="frozen contract literal"):
        criticreplay.run(*args, model="m")
    assert client.calls == []


def test_run_refuses_a_paraphrase_that_moves_a_frozen_keyword(asset_tree, tmp_path):
    """Guard 3 — whose keyword list already lived in this module, read only by a test."""
    client, args = _admissibility_rig(
        asset_tree, tmp_path,
        {
            "id": "P-lowercase-only", "class": "paraphrase", "rule": "reword",
            "op": "replace", "replace": [{"from": "Judge ONLY", "to": "Judge only"}],
            "justification": "changes the force of a directive, which is not a paraphrase",
        },
    )
    with pytest.raises(criticreplay.PerturbationError, match="frozen keyword"):
        criticreplay.run(*args, model="m")
    assert client.calls == []


def test_run_refuses_a_paraphrase_that_spans_two_sentences(asset_tree, tmp_path):
    """Guard 4: an instance a reader cannot check at a glance is not defensible."""
    client, args = _admissibility_rig(
        asset_tree, tmp_path,
        {
            "id": "P-two-sentences", "class": "paraphrase", "rule": "reword",
            "op": "replace",
            "replace": [{"from": "the answer. Score 9-10", "to": "the reply. Score 9-10"}],
            "justification": "spans a sentence boundary",
        },
    )
    with pytest.raises(criticreplay.PerturbationError, match="one sentence"):
        criticreplay.run(*args, model="m")
    assert client.calls == []


def test_run_refuses_a_paraphrase_expressed_as_anything_but_one_substitution(
    asset_tree, tmp_path
):
    """§3.3 step 4: each P point is ONE literal from -> to pair."""
    client, args = _admissibility_rig(
        asset_tree, tmp_path,
        {
            "id": "P-swapped", "class": "paraphrase", "rule": "reword", "op": "swap",
            "swap": {"a": "good", "b": "bad"},
            "justification": "a swap is not a substitution pair",
        },
    )
    with pytest.raises(criticreplay.PerturbationError, match="one sentence"):
        criticreplay.run(*args, model="m")
    assert client.calls == []


# ---- I3 and I4: the two guards that aborted runs on legitimate input ----
#
# Both were written from the spec with no measured defect behind them, and since
# `3420384` they can stop a run. Guard 4 was INVERTED on the real template, which is
# hard-wrapped: it flagged on `". "` and a trailing `.`, so an anchor that is exactly one
# complete sentence raised, and an anchor genuinely spanning two sentences across a
# newline returned clean. Guard 3 counted SUBSTRINGS, so `every` "moved" into
# `everything` and a keyword reordered inside the instance did not move at all.

ONE_SENTENCE_ANCHOR = "Judge ONLY whether the information the task asks for is present and correct."


def _paraphrase(anchor, replacement, pid="P-probe"):
    return criticreplay.Point(
        id=pid, point_class="paraphrase", rule="reword", op="replace",
        replace=[{"from": anchor, "to": replacement}], justification="probe",
    )


def test_guard_four_admits_an_anchor_that_is_exactly_one_complete_sentence():
    """I4: this anchor is one complete sentence — exactly what guard 4 demands.

    It is the shipped template's first line, verbatim. Under the old predicate its
    trailing `.` raised `PerturbationError` and aborted the whole run.
    """
    base = _shipped_template()
    assert ONE_SENTENCE_ANCHOR in base
    point = _paraphrase(ONE_SENTENCE_ANCHOR, ONE_SENTENCE_ANCHOR.replace("Judge", "Assess"))
    perturbed = criticreplay.apply_point(point, base)
    assert criticreplay.point_admissibility_violations(point, base, perturbed) == []


def test_guard_four_refuses_an_anchor_spanning_two_sentences_across_a_newline():
    """I4, the other half: the template is hard-wrapped, so `". "` never appears there.

    Under the old predicate this anchor — two whole sentences — returned CLEAN.
    """
    base = "Judge the answer.\nBe brief about it.\nT:{task}\nA:{output}\n"
    point = _paraphrase(
        "Judge the answer.\nBe brief about it", "Judge the reply.\nBe brief about it"
    )
    perturbed = criticreplay.apply_point(point, base, check=False)
    problems = criticreplay.point_admissibility_violations(point, base, perturbed)
    assert any("more than one sentence" in p for p in problems), problems


def test_guard_four_refuses_a_replacement_that_splits_one_sentence_into_two():
    """The `to` side is an instance too: a paraphrase may not add a sentence boundary."""
    base = "Judge the answer well today.\nT:{task}\nA:{output}\n"
    point = _paraphrase("the answer well today", "the answer. Consider it well today")
    perturbed = criticreplay.apply_point(point, base, check=False)
    problems = criticreplay.point_admissibility_violations(point, base, perturbed)
    assert any("more than one sentence" in p for p in problems), problems


def test_guard_three_does_not_fire_on_a_frozen_keyword_inside_a_longer_word():
    """I3: `every` is a frozen keyword; `everything` is not a use of it.

    Substring counting aborted this run claiming the keyword `every` had moved.
    """
    base = "Score it, even when the answer explains itself.\nT:{task}\nA:{output}\n"
    point = _paraphrase("explains itself", "explains everything")
    perturbed = criticreplay.apply_point(point, base)
    assert criticreplay.point_admissibility_violations(point, base, perturbed) == []


def test_guard_three_refuses_a_keyword_reordered_inside_the_instance():
    """I3, the other half: a real scope change that substring counting reports clean.

    "Judge ONLY whether" -> "Judge whether ONLY" moves what `ONLY` scopes over, and the
    count of `ONLY` in the template is identical before and after.
    """
    base = "Judge ONLY whether it is right.\nT:{task}\nA:{output}\n"
    point = _paraphrase("Judge ONLY whether", "Judge whether ONLY")
    perturbed = criticreplay.apply_point(point, base, check=False)
    assert perturbed.count("ONLY") == base.count("ONLY")
    problems = criticreplay.point_admissibility_violations(point, base, perturbed)
    assert any("frozen keyword" in p for p in problems), problems


def test_guard_three_still_admits_a_paraphrase_beside_a_keyword_it_leaves_in_place():
    """The rule is scope, not proximity: rewording the verb `NOT` governs is allowed."""
    base = "Do NOT deduct points for formatting.\nT:{task}\nA:{output}\n"
    point = _paraphrase("Do NOT deduct points", "Do NOT subtract points")
    perturbed = criticreplay.apply_point(point, base)
    assert criticreplay.point_admissibility_violations(point, base, perturbed) == []


def test_a_run_is_not_aborted_by_a_paraphrase_anchored_on_one_whole_sentence(
    asset_tree, tmp_path
):
    """The end of the abort: the same probe, through `run()`, spends and reports."""
    client, args = _admissibility_rig(
        asset_tree, tmp_path,
        {
            "id": "P-whole-sentence", "class": "paraphrase", "rule": "reword",
            "op": "replace",
            "replace": [{"from": "Judge ONLY the answer.", "to": "Judge ONLY the reply."}],
            "justification": "exactly one complete sentence, which is what guard 4 demands",
        },
    )
    result = criticreplay.run(*args, model="m")
    assert {r.point for r in result.rows} == {"identity", "P-whole-sentence"}
    assert client.calls


# ---- I6: the guards a LIBRARY consumer gets, without going through `run()` ----
#
# `apply_point`, `replay_verdicts` and `replay_scores` are in `__all__`, and until now
# all four guards lived in `run()`'s helpers. `3420384` closed the `--manifest` hole; a
# consumer with a hand-rolled manifest calling the primitives directly still got zero
# guards, which is the same case that commit claimed to close.


def test_apply_point_refuses_an_inadmissible_point_without_going_through_run():
    """Guards 1, 3 and 4 are properties of the POINT, so they ride with the transform.

    `apply_point` is the only public route from a `Point` to a template. A consumer who
    never calls `run()` now cannot get an inadmissible template out of this module by
    accident.
    """
    base = "Judge the answer.\nBe brief about it.\nT:{task}\nA:{output}\n"
    point = _paraphrase(
        "Judge the answer.\nBe brief about it", "Judge the reply.\nBe brief about it"
    )
    with pytest.raises(criticreplay.PerturbationError, match="one sentence"):
        criticreplay.apply_point(point, base)


def test_apply_point_refuses_a_point_that_moves_a_frozen_contract_literal():
    """Guard 1, on the same public route, in every class."""
    base = "Score 9-10 = good.\nT:{task}\nA:{output}\n"
    point = criticreplay.Point(
        id="O-endash", point_class="order", rule="reorder", op="replace",
        replace=[{"from": "Score 9-10", "to": "Score 9–10"}],
    )
    with pytest.raises(criticreplay.PerturbationError, match="frozen contract literal"):
        criticreplay.apply_point(point, base)


def test_apply_point_check_false_is_the_documented_deliberate_bypass():
    """A consumer with a good reason still has a way through — a named one.

    The guards must not become impossible to bypass on purpose; what they must stop is
    bypassing them by not knowing they exist.
    """
    base = "Judge the answer.\nBe brief about it.\nT:{task}\nA:{output}\n"
    point = _paraphrase(
        "Judge the answer.\nBe brief about it", "Judge the reply.\nBe brief about it"
    )
    template = criticreplay.apply_point(point, base, check=False)
    assert template is not None and "Judge the reply." in template
    assert criticreplay.point_admissibility_violations(point, base, template) != []


def test_materialize_manifest_refuses_an_inadmissible_family():
    """The offline audit route is the same route: a bad manifest cannot be materialized."""
    base = "Score 9-10 = good.\nT:{task}\nA:{output}\n"
    point = criticreplay.Point(
        id="O-endash", point_class="order", rule="reorder", op="replace",
        replace=[{"from": "Score 9-10", "to": "Score 9–10"}],
    )
    with pytest.raises(criticreplay.PerturbationError, match="frozen contract literal"):
        criticreplay.materialize_manifest([point], {"v": base})


def test_run_still_names_the_variant_when_a_point_is_inadmissible(asset_tree, tmp_path):
    """`_variant_family` keeps its own richer message: which variant, not just which point."""
    client, args = _admissibility_rig(
        asset_tree, tmp_path,
        {
            "id": "P-two-sentences", "class": "paraphrase", "rule": "reword",
            "op": "replace",
            "replace": [
                {"from": "Judge ONLY the answer. Score", "to": "Judge ONLY the reply. Score"}
            ],
            "justification": "spans a sentence boundary",
        },
    )
    with pytest.raises(criticreplay.PerturbationError, match="inadmissible on variant 'v'"):
        criticreplay.run(*args, model="m")
    assert client.calls == []


def test_the_shipped_manifest_passes_all_three_cell_independent_guards(manifest):
    """The floor: wiring these in must not make the committed family inadmissible."""
    for label, base in variant_templates().items():
        for point in manifest.points:
            new = criticreplay.apply_point(point, base)
            if new is None:
                continue
            assert criticreplay.point_admissibility_violations(point, base, new) == [], (
                point.id,
                label,
            )


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


def test_cli_exposes_the_guard_mode_and_defaults_to_warn(guard_rig, tmp_path, monkeypatch, capsys):
    client = ScriptedCritic(lambda p: 9)
    monkeypatch.setattr(criticreplay, "OpenAICompatible", lambda **kw: client)
    rows_path, summary_path = tmp_path / "rows.jsonl", tmp_path / "summary.json"
    criticreplay.main(
        [
            "--base-url", "http://x", "--model", "fake-14b",
            "--rubric", f"before={guard_rig['before']}",
            "--transcripts", str(guard_rig["transcripts"]),
            "--json", str(rows_path), "--summary", str(summary_path),
        ]
    )
    rows = [json.loads(line) for line in rows_path.read_text().splitlines()]
    assert [r["guard_violations"] for r in rows if r["point"] == "P-taskword"] == [["alpha"]]
    summary = json.loads(summary_path.read_text())
    assert summary["guard"]["mode"] == "warn"
    assert summary["guard"]["violations"][0]["point"] == "P-taskword"
    assert "GUARD" in capsys.readouterr().out


def test_cli_guard_error_exits_non_zero_without_running_the_cell(
    guard_rig, tmp_path, monkeypatch, capsys
):
    client = ScriptedCritic(lambda p: 9)
    monkeypatch.setattr(criticreplay, "OpenAICompatible", lambda **kw: client)
    with pytest.raises(SystemExit) as excinfo:
        criticreplay.main(
            [
                "--base-url", "http://x", "--model", "m",
                "--rubric", f"before={guard_rig['before']}",
                "--transcripts", str(guard_rig["transcripts"]), "--guard", "error",
            ]
        )
    assert excinfo.value.code == 1
    assert "shared-token guard" in capsys.readouterr().err
    assert client.calls == []


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
