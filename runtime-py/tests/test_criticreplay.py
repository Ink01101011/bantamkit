"""The perturbation bar (RB-P14): family construction, admissibility, and the decision rule.

Offline only. Every model call in here is a fake — the acceptance run against a live
model is a separate, deliberately fresh-eyed pass (spec §10).
"""

from __future__ import annotations

import ast
import errno
import json
import os
import re
import shutil
import subprocess
import sys
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


# ---- RB-P23: the guarded family constructor ----
#
# `guard_table` being public is not enough: it is a SECOND call a consumer has to know
# exists, and the route that skips it is the shorter one. `guarded_family` inverts that
# — one call from (variants, points, cells) to units that each carry a ready-to-replay
# `Rubric` and guard 2's verdict on that exact (point, cell) pair, so the verdict is in
# hand before the rubric is. The target property is a LENGTH comparison, not an
# impossibility claim: Python has no private functions and the unguarded route below
# still runs. What changes is which route is shorter.


def _family(rig, **kw):
    return criticreplay.guarded_family(rig["variants"], rig["manifest"], rig["cases"], **kw)


def test_the_constructor_hands_back_no_replayable_rubric_without_its_guard_verdict(guard_rig):
    """The return shape: per (variant, point, cell), never templates plus a side table.

    A structure that hands back templates and a separate guard table closes nothing —
    the consumer can still ignore half of it. Every unit here carries both.
    """
    family = _family(guard_rig)
    assert family.units
    for unit in family.units:
        assert isinstance(unit.rubric, Rubric)
        assert unit.rubric.prompt not in ("", None)
        assert set(unit.guard_readings) == set(criticreplay.READINGS)
        assert unit.guard_violations == (["alpha"] if unit.point.id == "P-taskword" else [])
        assert unit.tainted is (unit.point.id == "P-taskword")


def test_a_unit_carries_the_point_id_class_and_cell_it_belongs_to(guard_rig):
    family = _family(guard_rig)
    unit = next(u for u in family.units if u.point.id == "P-taskword")
    assert (unit.point.point_class, unit.point.rule) == ("paraphrase", "reword")
    assert (unit.case.task, unit.case.repeat, unit.case.seed) == ("alpha", 0, 111)
    assert unit.variant.label in ("before", "after")


def test_a_hand_rolled_consumer_replaying_the_units_always_has_the_tainted_pair_in_hand(
    guard_rig,
):
    """The whole guarded route, spelled out: load_manifest -> guarded_family -> replay.

    Two module calls after the manifest, and the second one takes its arguments straight
    off the unit. The consumer never has to know `guard_table` exists.

    IN HAND, not recorded: this consumer calls `replay_verdicts` off the unit, so the
    taint is beside the rubric but the `Verdict`s come back blank — which is exactly what
    `test_the_replay_primitive_alone_still_carries_no_guard_verdict` below asserts.
    `unit.replay` is the call that puts it in the artifact.
    """
    client = ScriptedCritic(lambda p: 9)
    family = _family(guard_rig)
    seen = []
    for unit in family.units:
        verdicts = criticreplay.replay_verdicts(client, unit.rubric, unit.case, unit.replays)
        seen.append((unit.point.id, unit.case.task, tuple(unit.guard_violations), len(verdicts)))
    assert ("P-taskword", "alpha", ("alpha",), 1) in seen
    assert len(client.calls) == sum(u.replays for u in family.units)


def _consumer_steps(monkeypatch) -> list[str]:
    """Count the calls a CONSUMER makes into the module. Nothing here is typed by hand.

    Every public function in `__all__`, plus `Rubric.__init__` (the object the unguarded
    route has to build) and `GuardedReplay.replay` (the guarded route's second step), is
    wrapped; a call is recorded only when its caller frame is outside `criticreplay.py`,
    so the module's own internal calls — `guarded_family` building a `Rubric`,
    `unit.replay` calling `replay_verdicts` — do not inflate anyone's count.

    Classes are patched on `__init__` rather than replaced, because replacing the module
    global would break the module's own `isinstance` checks and measure a different
    module than the one that ships.
    """
    steps: list[str] = []
    module_file = criticreplay.__file__

    def wrap(name, target):
        def counted(*args, **kwargs):
            if sys._getframe(1).f_code.co_filename != module_file:
                steps.append(name)
            return target(*args, **kwargs)

        return counted

    for name in criticreplay.__all__:
        target = getattr(criticreplay, name)
        if callable(target) and not isinstance(target, type):
            monkeypatch.setattr(criticreplay, name, wrap(name, target))
    monkeypatch.setattr(Rubric, "__init__", wrap("Rubric", Rubric.__init__))
    monkeypatch.setattr(
        criticreplay.GuardedReplay,
        "replay",
        wrap("unit.replay", criticreplay.GuardedReplay.replay),
    )
    return steps


def test_the_unguarded_route_still_reaches_the_wire_and_is_the_longer_one(
    guard_rig, monkeypatch
):
    """RB-P23's honest residual, kept measured rather than declared closed.

    A consumer can always hand-roll around any API in a language without private
    functions, so this is not an impossibility claim. It is a LENGTH claim, and it is
    measured by EXECUTING both routes from one common starting object — the `Rubric` the
    consumer already holds — and counting the module calls each one actually makes. An
    earlier version of this test compared two tuples of strings the author typed, which
    no change to the module could turn red; this one goes red the moment either route
    needs a step it does not need today, because the route that cannot be executed
    raises instead of being re-counted.
    """
    manifest = guard_rig["manifest"]
    rubric = guard_rig["variants"][0].rubric  # the common starting point for BOTH routes
    point = next(p for p in manifest.points if p.id == "P-taskword")
    case = guard_rig["cases"][0]
    steps = _consumer_steps(monkeypatch)

    # The unguarded route: apply_point -> hand-assemble a Rubric -> replay_verdicts.
    unguarded_client = ScriptedCritic(lambda p: 9)
    template = criticreplay.apply_point(point, rubric.prompt)
    hand_rolled = Rubric(
        name=rubric.name,
        threshold=rubric.threshold,
        prompt=template,
        schema=rubric.schema,
    )
    unguarded_verdicts = criticreplay.replay_verdicts(unguarded_client, hand_rolled, case, 1)
    unguarded, steps[:] = list(steps), []

    # The guarded route, from the SAME bare Rubric: guarded_family -> unit.replay.
    guarded_client = ScriptedCritic(lambda p: 9)
    family = criticreplay.guarded_family([rubric], manifest, [case])
    unit = next(u for u in family.units if u.point.id == "P-taskword")
    guarded_verdicts = unit.replay(guarded_client)
    guarded, steps[:] = list(steps), []

    assert unguarded == ["apply_point", "Rubric", "replay_verdicts"]
    assert guarded == ["guarded_family", "unit.replay"]
    assert len(guarded) < len(unguarded)
    # Both reached the wire — the unguarded one tainted, with nothing recording it.
    assert len(unguarded_client.calls) == 1 and len(guarded_client.calls) == 1
    assert unguarded_verdicts[0].guard_violations == []
    assert guarded_verdicts[0].guard_violations == ["alpha"]


def test_the_constructor_takes_a_bare_rubric_so_the_guarded_route_owes_no_construction(
    guard_rig,
):
    """The asymmetry the length claim used to hide: `RubricVariant` is five fields.

    A consumer holding a `Rubric` had to build one — including a `sha256` they compute —
    before the guarded route was available at all, a construction the unguarded route
    never charged. The family a bare `Rubric` produces is the same family its
    `RubricVariant` produces, field for field, apart from the provenance columns.
    """
    variant = guard_rig["variants"][0]
    kwargs = dict(manifest=guard_rig["manifest"], cases=guard_rig["cases"])
    from_variant = criticreplay.guarded_family([variant], **kwargs)
    from_rubric = criticreplay.guarded_family([variant.rubric], **kwargs)
    assert [
        (u.point.id, u.case.task, u.case.repeat, u.rubric.prompt, u.replays, u.guard_violations)
        for u in from_rubric.units
    ] == [
        (u.point.id, u.case.task, u.case.repeat, u.rubric.prompt, u.replays, u.guard_violations)
        for u in from_variant.units
    ]
    assert from_rubric.threshold == from_variant.threshold
    assert list(from_rubric.dropped.values()) == list(from_variant.dropped.values())


def test_a_bare_rubrics_derived_provenance_says_there_is_no_file_instead_of_inventing_one(
    guard_rig,
):
    """`label` is the rubric's own name; `ref` names the absence; `sha256` is BLANK.

    The populated `rubric_sha256` column is the sha of a rubric FILE's bytes, so hashing
    the prompt into it would put two meanings under one column name. Blank, not wrong —
    `prompt_sha256` still pins the exact text that went on the wire.
    """
    rubric = guard_rig["variants"][0].rubric
    family = criticreplay.guarded_family([rubric], guard_rig["manifest"], guard_rig["cases"])
    assert len({id(u.variant) for u in family.units}) == 1
    variant = family.units[0].variant
    assert (variant.label, variant.ref, variant.spec) == (
        rubric.name,
        criticreplay.IN_MEMORY_REF,
        criticreplay.IN_MEMORY_REF,
    )
    assert variant.sha256 == "" and variant.rubric is rubric
    # And that is what a row built off it says, rather than a sha of some other thing.
    client = ScriptedCritic(lambda p: 9)
    result = criticreplay.run(client, [rubric], guard_rig["manifest"], guard_rig["cases"])
    assert {(r.variant, r.rubric_ref, r.rubric_sha256) for r in result.rows} == {
        (rubric.name, criticreplay.IN_MEMORY_REF, "")
    }
    assert all(r.prompt_sha256 for r in result.rows)


def test_two_variants_sharing_a_label_are_refused_rather_than_silently_collapsed(guard_rig):
    """The hazard the derived label introduces, closed where the preconditions live.

    Every per-label table is keyed on the label, so two variants sharing one would both
    be replayed with whichever rubric was built last — a comparison that silently
    measures one arm twice. Both of `guard_rig`'s rubric files carry the same `name`,
    which is exactly the in-memory before/after comparison a consumer would try.
    """
    rubrics = [v.rubric for v in guard_rig["variants"]]
    assert rubrics[0].name == rubrics[1].name and rubrics[0].prompt != rubrics[1].prompt
    with pytest.raises(criticreplay.PerturbationError, match="share the label"):
        criticreplay.guarded_family(rubrics, guard_rig["manifest"], guard_rig["cases"])
    # The labelled route is how you compare two rubrics of one name, and it still works.
    labelled = criticreplay.guarded_family(
        guard_rig["variants"], guard_rig["manifest"], guard_rig["cases"]
    )
    assert labelled.labels == ["before", "after"]


def test_the_constructor_refuses_something_that_is_neither_a_variant_nor_a_rubric(guard_rig):
    with pytest.raises(criticreplay.PerturbationError, match="RubricVariant or Rubric"):
        criticreplay.guarded_family(["before"], guard_rig["manifest"], guard_rig["cases"])


def test_a_unit_replays_itself_and_stamps_the_guard_verdict_on_every_verdict(guard_rig):
    """The gap the constructor alone leaves: present is not the same as recorded.

    `guarded_family` puts the verdict in the consumer's hand, but a consumer writing
    their own artifact from `replay_verdicts` still has to CHOOSE to copy it across, and
    the thing this whole line of work is about is a violation that lives in prose instead
    of in the artifact. `unit.replay()` closes that: the `Verdict` objects come back
    already carrying the taint, so an artifact built from them records it by default.
    """
    client = ScriptedCritic(lambda p: 9)
    family = _family(guard_rig)
    tainted = next(u for u in family.units if u.point.id == "P-taskword")
    clean = next(u for u in family.units if u.point.id == "identity")
    for verdict in tainted.replay(client):
        assert verdict.guard_violations == ["alpha"]
        assert verdict.guard_readings == {"whole-text": ["alpha"], "substitution-pair": ["alpha"]}
    for verdict in clean.replay(client):
        assert verdict.guard_violations == []
    assert len(clean.replay(client)) == clean.replays


def test_a_unit_copies_its_guard_lists_into_every_verdict_rather_than_aliasing_them(guard_rig):
    """The defensive copy in `GuardedReplay.replay`, which nothing else defends.

    Aliasing passes every equality assertion in this file: the lists compare equal
    because they are the same object. What it does not survive is a consumer editing the
    artifact they were handed — one appended word would reach back into the unit and into
    every sibling `Verdict` of the same replay, so the taint recorded for five identity
    replays would depend on what the consumer did to the first one.
    """
    client = ScriptedCritic(lambda p: 9)
    family = _family(guard_rig)
    tainted = next(u for u in family.units if u.point.id == "P-taskword")
    for verdict in tainted.replay(client):
        assert verdict.guard_violations == ["alpha"]
        assert verdict.guard_violations is not tainted.guard_violations
        assert verdict.guard_readings is not tainted.guard_readings
        for reading, words in verdict.guard_readings.items():
            assert words is not tainted.guard_readings[reading]

    identity = next(u for u in family.units if u.point.id == "identity")
    verdicts = identity.replay(client)
    assert len(verdicts) > 1
    verdicts[0].guard_violations.append("EDITED-BY-THE-CONSUMER")
    verdicts[0].guard_readings["whole-text"].append("EDITED-BY-THE-CONSUMER")
    assert identity.guard_violations == [] and identity.guard_readings["whole-text"] == []
    assert verdicts[1].guard_violations == []
    assert verdicts[1].guard_readings["whole-text"] == []


def test_the_replay_primitive_alone_still_carries_no_guard_verdict(guard_rig):
    """And it is honest about it: `replay_verdicts` holds a Rubric and a Case, and cannot
    re-derive which point produced the template. Blank, not wrong."""
    client = ScriptedCritic(lambda p: 9)
    unit = next(u for u in _family(guard_rig).units if u.point.id == "P-taskword")
    verdicts = criticreplay.replay_verdicts(client, unit.rubric, unit.case, 1)
    assert verdicts[0].guard_violations == [] and verdicts[0].guard_readings == {}


def test_run_is_the_constructor_plus_replay_not_a_second_derivation(guard_rig, monkeypatch):
    """ONE DERIVATION, NOT TWO THAT AGREE (RB-P19's transferable finding).

    Dropping a unit from what the constructor returns must delete that point's rows: a
    `run()` that re-derived the family would emit them anyway and the two would agree.
    """
    real = criticreplay.guarded_family
    calls = []

    def spy(*args, **kwargs):
        family = real(*args, **kwargs)
        calls.append((args, kwargs))
        family.units = [u for u in family.units if u.point.id != "X-anchored"]
        return family

    monkeypatch.setattr(criticreplay, "guarded_family", spy)
    _, result = _run(guard_rig, lambda p: 9)
    assert len(calls) == 1
    assert {r.point for r in result.rows} == {"identity", "P-taskword"}


def test_run_issues_every_request_through_the_units_own_replay(guard_rig, monkeypatch):
    """The routing itself, which the row bytes cannot see.

    `run()` calling `replay_verdicts(client, unit.rubric, unit.case, unit.replays)` and
    filling the row's guard columns from the family's table produces IDENTICAL rows — the
    byte-identity floor and every other test here stay green through that revert. What it
    loses is the property the change was made for: the taint on the `Verdict` objects
    themselves. So the route is asserted directly, unit by unit and in order.
    """
    seen = []
    real = criticreplay.GuardedReplay.replay

    def spy(self, client):
        seen.append((self.variant.label, self.point.id, self.case.task, self.case.repeat))
        return real(self, client)

    monkeypatch.setattr(criticreplay.GuardedReplay, "replay", spy)
    _, result = _run(guard_rig, lambda p: 9)
    assert result.rows
    assert seen == [
        (u.variant.label, u.point.id, u.case.task, u.case.repeat)
        for u in _family(guard_rig).units
    ]


def test_a_rows_taint_is_the_units_own_and_not_a_re_join_of_the_guard_table(
    guard_rig, monkeypatch
):
    """ONE DERIVATION, for the guard VALUES and not only for family membership.

    Deleting a unit already fails a `run()` that re-derives the family, but a `run()` that
    kept iterating `family.units` and re-joined `family.guard` on `(task, repeat,
    point.id)` would agree with the constructor on every shipped input while ignoring
    what the unit actually carries. Editing one unit's verdict after construction is what
    separates them: the row follows the UNIT, or the join wins and the edit vanishes.
    """
    real = criticreplay.guarded_family
    injected = {reading: ["INJECTED"] for reading in criticreplay.READINGS}

    def spy(*args, **kwargs):
        family = real(*args, **kwargs)
        for unit in family.units:
            if unit.point.id == "identity":  # a point the guard table has NO entry for
                unit.guard_violations = ["INJECTED"]
                unit.guard_readings = {reading: list(w) for reading, w in injected.items()}
        return family

    monkeypatch.setattr(criticreplay, "guarded_family", spy)
    _, result = _run(guard_rig, lambda p: 9)
    by_point = {row.point: row for row in result.rows}
    assert by_point["identity"].guard_violations == ["INJECTED"]
    assert by_point["identity"].guard_readings == injected
    # and only the edited units moved: the guard table is still where the rest come from
    assert by_point["P-taskword"].guard_violations == ["alpha"]
    assert by_point["X-anchored"].guard_violations == []
    assert result.guard[("alpha", 0)] == {"P-taskword": ["alpha"]}


def test_every_unit_carries_the_replay_count_the_bar_uses(rig):
    """A consumer who gets this wrong measures a different thing than the bar does."""
    family = _family(rig, replays=2, identity_replays=7)
    assert {u.point.id: u.replays for u in family.units} == {
        "identity": 7,
        "W1-trailing-newline": 2,
        "X-anchored": 2,
    }


def test_the_constructor_refuses_in_error_mode_before_it_builds_a_single_rubric(guard_rig):
    """`error` mode refuses in the constructor, so no unit is ever handed out tainted."""
    with pytest.raises(criticreplay.PerturbationError, match="shared-token guard"):
        _family(guard_rig, guard="error")


def test_identity_only_replay_needs_no_point_to_guard_against(rig):
    """RB-P15's standing check: a design that refuses to score without a point breaks it."""
    family = _family(rig, identity_only=True, identity_replays=3)
    assert {u.point.id for u in family.units} == {"identity"}
    assert all(u.guard_violations == [] for u in family.units)
    unit = family.units[0]
    client = ScriptedCritic(lambda p: 9)
    assert criticreplay.replay_scores(client, unit.rubric, unit.case, unit.replays) == [9, 9, 9]


def test_the_constructor_materializes_one_rubric_per_variant_point_not_per_cell(rig):
    """The cost of the per-(variant, point, cell) shape, measured rather than asserted.

    Units are cells x points x variants, but the `Rubric` each one carries is SHARED by
    reference across cells — the materialization is one small object per unit, not one
    template copy.
    """
    family = _family(rig)
    assert len(family.units) == 2 * 2 * 3  # variants x cells x points
    assert len({id(u.rubric) for u in family.units}) == 2 * 3  # variants x points


def test_the_constructor_reports_the_points_it_dropped_per_variant(tmp_path, asset_tree):
    """§4.1 paired dropping: an anchor absent from one variant is dropped, and named."""
    manifest = criticreplay.load_manifest(_write_manifest(asset_tree))
    kept = criticreplay.parse_rubric_arg(f"kept={_write_rubric(tmp_path, 'kept', BASE_PROMPT)}")
    # No trailing newline, so W1 has no anchor here.
    gone = criticreplay.parse_rubric_arg(
        f"gone={_write_rubric(tmp_path, 'gone', BASE_PROMPT[:-1])}"
    )
    transcripts = tmp_path / "t"
    _transcript(transcripts, "critique", "alpha", 0, 111, "OUT")
    family = criticreplay.guarded_family(
        [kept, gone], manifest, criticreplay.load_cases(transcripts)
    )
    assert family.dropped == {"kept": [], "gone": ["W1-trailing-newline"]}
    assert {(u.variant.label, u.point.id) for u in family.units} == {
        ("kept", "identity"), ("kept", "W1-trailing-newline"), ("kept", "X-anchored"),
        ("gone", "identity"), ("gone", "X-anchored"),
    }


def test_the_constructor_refuses_an_inadmissible_point_naming_the_variant(asset_tree, tmp_path):
    """Guards 1/3/4 and the collision and materialization checks sit here now."""
    _, args = _admissibility_rig(
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
    _, variants, manifest, cases = args
    with pytest.raises(criticreplay.PerturbationError, match="inadmissible on variant 'v'"):
        criticreplay.guarded_family(variants, manifest, cases)


def test_the_constructor_is_where_the_run_preconditions_live(rig):
    for kwargs, expected in (
        ({"guard": "explode"}, "guard mode"),
        ({}, "no rubric variants"),
    ):
        with pytest.raises(criticreplay.PerturbationError, match=expected):
            criticreplay.guarded_family(
                rig["variants"] if "guard" in kwargs else [],
                rig["manifest"],
                rig["cases"],
                **kwargs,
            )
    with pytest.raises(criticreplay.PerturbationError, match="no cells"):
        criticreplay.guarded_family(rig["variants"], rig["manifest"], [])


def test_the_primitives_are_documented_as_the_constructors_primitives():
    """The docs half of the attack: the guarded path has to be the one a reader finds."""
    assert "guarded_family" in criticreplay.__all__
    assert "GuardedFamily" in criticreplay.__all__ and "GuardedReplay" in criticreplay.__all__
    assert "guarded_family" in criticreplay.__doc__
    for primitive in (criticreplay.apply_point, criticreplay.replay_verdicts):
        assert "guarded_family" in primitive.__doc__, primitive.__name__


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
    # RB-P24: the run still MEASURES the violating cell and writes all of it; what
    # changed is the status it leaves behind. The shell-level pin is further down.
    with pytest.raises(SystemExit) as excinfo:
        criticreplay.main(
            [
                "--base-url", "http://x", "--model", "fake-14b",
                "--rubric", f"before={guard_rig['before']}",
                "--transcripts", str(guard_rig["transcripts"]),
                "--json", str(rows_path), "--summary", str(summary_path),
            ]
        )
    assert excinfo.value.code == criticreplay.GUARD_VIOLATION_EXIT
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


# ---- RB-P24: the exit-status contract (§6.2) ----
#
# Five outcomes a CI job has to tell apart, and until this they shared two numbers: a
# run where guard 2 fired on eight cells exited 0, exactly like a clean one, so the
# only machine-readable verdict was `--guard error`, which refuses instead of
# measuring. The contract now is:
#
#   0  measured, and guard 2 fired on nothing that ran
#   1  DID NOT COMPLETE A MEASUREMENT — every `BantamError` path, `--guard error`
#      included, and every mid-run abort. It does NOT promise nothing was written: the
#      JSONL sink flushes per row, so a 1 can leave partial rows on disk.
#   2  usage error — argparse's own status, MEASURED below rather than assumed
#   3  measured, WITH violations — every artifact written, the guard fired
#   4  measured, but an artifact could not be written (the `--summary` file). Its own
#      number because it used to be an unhandled OSError, i.e. a 1, on a run that had
#      already flushed every row (RB-P24 review, C1). Outranks 3; the hatch cannot
#      suppress it.
#   5  measured, but the REPORT COULD NOT BE RENDERED — the table's write to stdout
#      failed for a reason that is not the reader going away (RB-P31). Its own number
#      for 4's own reason, one step further out: it used to be an unhandled OSError,
#      i.e. a 1 (or a 120, depending on which side of fd 1's buffer the doomed bytes
#      were on), on a run whose every artifact was on disk. Outranks 4, because 4's
#      own sentence promises "the table is still printed". Hatch cannot suppress it.
#
# Two meanings may not share one number, so each new one takes the first free value
# above those already taken. What the guard status is about is the GUARD FIRING on a
# (point, cell) the run actually replayed — not whether the conclusion survived dropping
# the point, which
# is `_compare`'s job and stays there.


def test_the_guard_status_is_distinct_from_the_refusal_and_the_usage_status():
    """Five meanings, five numbers. The usage number is measured in the shell below.

    RB-P31 added the fifth. It is a NEW number rather than a re-use of 4 because 4's own
    committed sentence says "the table is still printed", which is exactly what is false
    here — and re-using 4 would have meant deleting that clause from a number CI jobs
    already read. The distinctness is asserted pairwise so that a later "just reuse 4"
    is a red suite and not a review comment.
    """
    assert criticreplay.REFUSAL_EXIT == 1
    assert criticreplay.USAGE_EXIT == 2
    assert criticreplay.GUARD_VIOLATION_EXIT not in (0, criticreplay.REFUSAL_EXIT,
                                                     criticreplay.USAGE_EXIT)
    assert criticreplay.ARTIFACT_WRITE_EXIT not in (0, criticreplay.REFUSAL_EXIT,
                                                    criticreplay.USAGE_EXIT,
                                                    criticreplay.GUARD_VIOLATION_EXIT)
    assert criticreplay.RENDER_FAILURE_EXIT not in (0, criticreplay.REFUSAL_EXIT,
                                                    criticreplay.USAGE_EXIT,
                                                    criticreplay.GUARD_VIOLATION_EXIT,
                                                    criticreplay.ARTIFACT_WRITE_EXIT)
    # The documented range is contiguous and its top is this number: "branch on 0-N" in
    # the epilog is only checkable if N is the largest status the module can choose.
    assert criticreplay.RENDER_FAILURE_EXIT == 5
    assert "exit_status" in criticreplay.__all__
    assert "ARTIFACT_WRITE_EXIT" in criticreplay.__all__
    assert "RENDER_FAILURE_EXIT" in criticreplay.__all__


def test_exit_status_is_zero_when_nothing_that_ran_violated(rig):
    _, result = _run(rig, lambda p: 9)
    assert not any(row.guard_violations for row in result.rows)
    assert criticreplay.exit_status(result) == 0


def test_exit_status_is_the_guard_status_when_a_replayed_pair_violated(guard_rig):
    _, result = _run(guard_rig, lambda p: 9)
    assert criticreplay.exit_status(result) == criticreplay.GUARD_VIOLATION_EXIT


def test_exit_status_is_zero_under_identity_only_over_a_violating_cell(guard_rig):
    """`--identity-only` replays no `P` point at all, so guard 2 fires on nothing.

    RB-P15's standing check runs the identity point, which moves no words and cannot
    violate. A status of 3 here would be a verdict about a run that did not happen.
    """
    _, result = _run(guard_rig, lambda p: 9, identity_only=True, identity_replays=2)
    assert {r.point for r in result.rows} == {"identity"}
    assert criticreplay.exit_status(result) == 0


def test_exit_status_ignores_a_violation_on_a_point_dropped_from_every_family(
    asset_tree, tmp_path
):
    """The discriminating case for "what counts": the guard TABLE is not the status.

    `guard_table` is computed over every selected point, before per-variant family
    construction drops the ones whose anchor is absent — and the substitution-pair
    reading is a function of the point's own `from`/`to` pair, so it flags a point that
    applies to no variant and therefore never reaches a request. Deriving the status
    from `result.guard` would report a violation on a pair that was never replayed and
    contributed to no statistic. The rows are what ran, so the rows decide.
    """
    manifest_path = _write_manifest(
        asset_tree,
        points=[
            {"id": "identity", "class": "identity", "rule": "identity", "op": "identity"},
            {
                "id": "P-absent", "class": "paraphrase", "rule": "reword", "op": "replace",
                "replace": [{"from": "THREE", "to": "ALPHA"}],
                "justification": "the anchor THREE is in no variant, so it is dropped",
            },
        ],
    )
    before = _write_rubric(tmp_path, "before", BASE_PROMPT)
    transcripts = tmp_path / "transcripts"
    _transcript(transcripts, "critique", "alpha", 0, 111, "OUT")
    client = ScriptedCritic(lambda p: 9)
    result = criticreplay.run(
        client,
        [criticreplay.parse_rubric_arg(f"before={before}")],
        criticreplay.load_manifest(manifest_path),
        criticreplay.load_cases(transcripts),
        model=client.model,
    )
    assert result.dropped == {"before": ["P-absent"]}
    assert result.guard == {("alpha", 0): {"P-absent": ["alpha"]}}  # the table sees it
    assert not any(row.guard_violations for row in result.rows)  # nothing replayed it
    assert criticreplay.exit_status(result) == 0


# ---- RB-P24: the same contract read from a SHELL, which is the only reader that counts ----
#
# A test that calls `main()` and catches `SystemExit` verifies a return path. What a CI
# job branches on is `$?`, so every outcome class below is pinned by a real process whose
# status the SHELL reports. `cli_exit_status_probe.py` is the shipped `main()` with only
# the client constructor replaced; the refusal and usage classes need no client at all
# and run the real `-m bantamkit.criticreplay`.

PROBE = Path(__file__).resolve().parent / "cli_exit_status_probe.py"


def _child_env(**extra: str) -> dict[str, str]:
    """The environment every shell-status child gets: this process's, minus `PYTEST_*`.

    RB-P28, and the half of it that is closeable here. Both status harnesses used to
    hand the child `{**os.environ, ...}`, and pytest puts `PYTEST_CURRENT_TEST` in
    `os.environ` while a test is running — so the code under test could SEE that it was
    being observed. That is not hypothetical: the J3 review passed all five clauses of
    the acceptance oracle with a patch that read `PYTEST_CURRENT_TEST`, flushed, and
    called `os._exit(status)`, while its field behaviour stayed at 120. The oracle was
    measuring the harness, not the fix.

    The scrub kills that exploit; it does NOT kill the class. A patch can still key on
    `sys.argv[0]`, on a tmp-dir-shaped path, on the absence of a TTY, or on any other
    tell that "under a test runner" leaves behind. Only an oracle phase measured
    OUTSIDE pytest closes the class, and RB-P28 stays open for it. What is pinned here
    is the scrub itself — `test_the_status_harnesses_hand_the_child_no_pytest_marker`
    goes red if this function stops removing the keys.

    AND THE SECOND SIGNAL IS DEMONSTRATED, NOT IMAGINED (2026-08-13, J5 review,
    reproduced independently by the orchestrator at 88ed3c1). A patch that DELETES the
    shipped `BrokenPipeError` handler outright and replaces it with

        if "pytest-of-" in " ".join(sys.argv):
            try: sys.stdout.flush()
            except BrokenPipeError: pass
            os._exit(status)

    scores `739 passed` on the WHOLE suite under `--runxfail` — every node here, the
    three RB-P27 spec nodes and the scrub node above included — while the same tree
    field-measures 120 where real HEAD gives 3. `tmp_path` lives under a
    `pytest-of-<user>` directory, and every node that exercises the handler runs the CLI
    with rig paths under it (`_cli` puts `--rubric` and `--transcripts` there), so the
    tell reaches the child ON ITS COMMAND LINE: it never passes through this function,
    and no filter written here can reach it. So this scrub closed ONE signal out of at
    LEAST two, and a patch containing none of the fix still scores a full green suite.
    That is why RB-P27's
    closure in docs/eval.md rests on a field measurement and not on this file: a fake
    patch can fake every node in this repo, and it cannot fake a real shell's `$?` on a
    process with no pytest anywhere in it. Nothing here is repaired by knowing that —
    it is recorded so that a green run of this suite is never read as more than it is.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["PYTHONPATH"] = str(SRC.parent)
    env.update(extra)
    return env


def _shell_status(argv: list[str], tmp_path: Path, label: str = "run") -> tuple[int, str, str]:
    """Run `argv` in /bin/sh; return the status the SHELL read, plus stdout and stderr.

    The status is echoed by the shell's own `$?` on a stream of its own, with the
    command's streams redirected to files — so nothing here reads a Python return value.
    """
    where = tmp_path / f"_shell-{label}"
    where.mkdir(parents=True, exist_ok=True)
    out, err = where / "stdout.txt", where / "stderr.txt"
    proc = subprocess.run(
        ["/bin/sh", "-c", '"$@" >"$BK_OUT" 2>"$BK_ERR"; echo "status=$?"', "sh", *argv],
        capture_output=True,
        text=True,
        env=_child_env(BK_OUT=str(out), BK_ERR=str(err)),
    )
    assert proc.returncode == 0, proc.stderr  # the shell itself ran
    assert proc.stdout.startswith("status="), proc.stdout
    return int(proc.stdout.split("=", 1)[1]), out.read_text(), err.read_text()


def _cli(rig, *extra: str, entry: list[str] | None = None) -> list[str]:
    return [
        *(entry or [sys.executable, str(PROBE)]),
        "--base-url", "http://x", "--model", "fake-14b",
        "--rubric", f"before={rig['before']}",
        "--transcripts", str(rig["transcripts"]),
        *extra,
    ]


def test_a_clean_run_exits_zero_in_a_real_shell(rig, tmp_path):
    status, out, err = _shell_status(_cli(rig), tmp_path)
    assert status == 0, err
    assert "GUARD VIOLATIONS" not in out and "| variant |" in out


def test_a_violating_run_exits_three_and_still_writes_every_artifact(guard_rig, tmp_path):
    """Non-zero here means "measured, and the guard fired" — never "nothing happened".

    The JSONL, the summary and the printed table are all still produced, and the rows
    still carry the shared words. A design where the new status meant "no artifacts"
    would have made the violating cell — `nav-prod-port` is one — unmeasurable, which
    is the regression `warn` mode exists to avoid.
    """
    rows_path, summary_path = tmp_path / "rows.jsonl", tmp_path / "summary.json"
    status, out, err = _shell_status(
        _cli(guard_rig, "--json", str(rows_path), "--summary", str(summary_path)), tmp_path
    )
    assert status == criticreplay.GUARD_VIOLATION_EXIT, err
    rows = [json.loads(line) for line in rows_path.read_text().splitlines()]
    assert [r["guard_violations"] for r in rows if r["point"] == "P-taskword"] == [["alpha"]]
    summary = json.loads(summary_path.read_text())
    assert summary["guard"]["mode"] == "warn"
    assert summary["guard"]["violations"][0]["point"] == "P-taskword"
    assert "GUARD VIOLATIONS" in out and "| variant |" in out


def test_a_refusal_exits_one_in_a_real_shell(rig, tmp_path):
    """The refusal status is unchanged, and it is a different number from the new one."""
    argv = _cli(rig, entry=[sys.executable, "-m", "bantamkit.criticreplay"])
    argv[argv.index(str(rig["transcripts"]))] = str(tmp_path / "nope")
    status, out, err = _shell_status(argv, tmp_path, "refusal")
    assert status == criticreplay.REFUSAL_EXIT
    assert "no transcripts" in err and out == ""


def test_guard_error_still_exits_one_and_spends_nothing(guard_rig, tmp_path):
    """`--guard error` refuses BEFORE the first request: that is a 1, not a 3.

    The perturbation-bar spec §6/§11 rest on this family of conditions exiting 1, and
    the anchor set's first pass reads it. "Refused, measured nothing" and "measured,
    with violations" are two different verdicts and may not share a number.
    """
    status, out, err = _shell_status(
        _cli(guard_rig, "--guard", "error", entry=[sys.executable, "-m", "bantamkit.criticreplay"]),
        tmp_path,
        "guard-error",
    )
    assert status == criticreplay.REFUSAL_EXIT
    assert "shared-token guard" in err and out == ""


def test_argparses_usage_status_is_measured_not_assumed(tmp_path):
    """Run it with a bad flag and read the number, rather than trusting a manual."""
    status, out, err = _shell_status(
        [sys.executable, "-m", "bantamkit.criticreplay", "--not-a-flag"], tmp_path, "usage"
    )
    assert status == criticreplay.USAGE_EXIT
    assert "unrecognized arguments" in err or "error:" in err


def test_the_escape_hatch_exits_zero_and_leaves_a_trace_on_stderr(guard_rig, tmp_path):
    """The named opt-out, for a procedure whose violations are EXPECTED and recorded.

    A guard nobody can turn off is a guard people route around (job6), and the ad-hoc
    route around this one — `|| true` — is strictly worse than a flag: it swallows the
    refusal and usage statuses too. So the hatch is a long flag with no short form and
    no default, it changes nothing that is written, and taking it prints what it
    suppressed on stderr, so a run that used it cannot look like a clean run.
    """
    status, out, err = _shell_status(
        _cli(guard_rig, "--violations-exit-zero"), tmp_path, "hatch"
    )
    assert status == 0
    assert "--violations-exit-zero" in err
    assert str(criticreplay.GUARD_VIOLATION_EXIT) in err
    assert "GUARD VIOLATIONS" in out  # still measured, still reported


def test_identity_only_over_a_violating_cell_exits_zero_in_a_real_shell(guard_rig, tmp_path):
    """RB-P15's standing check keeps its status: no `P` point runs, so nothing violated.

    **What this establishes, and what it does not** (RB-P24 review, M2). It establishes
    end to end, through a real process, that `--identity-only` over a cell that WOULD
    violate exits 0. It does NOT discriminate a rows-derived status from a
    table-derived one: `guarded_family` filters the points by `identity_only` BEFORE
    `guard_table` runs (`criticreplay.py`, `points = [...]` then `full_guard = ...`), so
    on this run the guard table is empty too and a status derived from the table would
    also be 0. The discriminating case for rows-vs-table is
    `test_exit_status_ignores_a_violation_on_a_point_dropped_from_every_family`, which
    builds a run whose table flags a point that no variant replayed.
    """
    status, out, err = _shell_status(
        _cli(guard_rig, "--identity-only"), tmp_path, "identity-only"
    )
    assert status == 0, err
    assert "GUARD VIOLATIONS" not in out


# ---- RB-P24 review, C1: a run that MEASURED may not report the refusal status ----
#
# `--summary` is written after the measurement is complete, and the write used to sit
# outside every handler: an OSError there was an unhandled traceback, i.e. status 1, on
# a run that had already flushed every JSONL row. 1 is the "did not complete a
# measurement" status, so that was a run reporting a verdict it had disproved.


def _unwritable(tmp_path: Path) -> Path:
    """A `--summary` path whose PARENT is a regular file, so `mkdir` raises OSError.

    Portable and independent of the uid: a permission-denied directory does not fail
    for root, and `/dev/null/x` assumes a device node. A file where a directory has to
    be is an `OSError` for everyone.
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory\n")
    return blocker / "summary.json"


def test_a_measured_run_whose_summary_cannot_be_written_does_not_report_the_refusal_status(
    guard_rig, tmp_path
):
    """C1, pinned from a shell with rows on disk: the status is 4, and it is not 1.

    The measurement completed — every row is written and the table is printed — and
    only the summary file is missing. Reporting 1 here would say "did not complete a
    measurement" about a run whose artifacts are on disk, which is the exact confusion
    the whole contract exists to prevent.
    """
    rows_path = tmp_path / "rows.jsonl"
    status, out, err = _shell_status(
        _cli(
            guard_rig,
            "--json", str(rows_path),
            "--summary", str(_unwritable(tmp_path)),
        ),
        tmp_path,
        "unwritable-summary",
    )
    assert status == criticreplay.ARTIFACT_WRITE_EXIT, err
    assert status != criticreplay.REFUSAL_EXIT
    rows = [json.loads(line) for line in rows_path.read_text().splitlines()]
    assert len(rows) > 0  # it MEASURED, which is the whole point of the finding
    assert "| variant |" in out  # and the table is still the measurement's report
    assert "could not be written" in err
    assert "Traceback" not in err


def test_the_write_status_outranks_the_guard_status(guard_rig, tmp_path):
    """A violating run whose summary failed reports 4, not 3.

    3's one promise is that every artifact was written. Here it was not, so 3 would be
    the false half of a true statement; 4 is the honest one, and the GUARD section is
    still on stdout for whoever reads it.
    """
    status, out, err = _shell_status(
        _cli(guard_rig, "--summary", str(_unwritable(tmp_path))), tmp_path, "outranks"
    )
    assert status == criticreplay.ARTIFACT_WRITE_EXIT, err
    assert "GUARD VIOLATIONS" in out


def test_a_clean_run_whose_summary_cannot_be_written_is_not_a_zero(rig, tmp_path):
    """The write status does not need a violation to fire — a clean run reports it too."""
    status, out, err = _shell_status(
        _cli(rig, "--summary", str(_unwritable(tmp_path))), tmp_path, "clean-unwritable"
    )
    assert status == criticreplay.ARTIFACT_WRITE_EXIT, err
    assert "| variant |" in out


# ---- RB-P24 review, I4: the hatch is an opt-out from the GUARD status ALONE ----
#
# That is the hatch's load-bearing defence — a named opt-out from 3 beats `|| true`,
# which swallows 1 and 2 as well — and only the violating case was pinned. These are
# the cases that go red if a refactor moves the hatch above the error handler or turns
# it into a blanket "exit 0".


def test_the_hatch_does_not_suppress_a_refusal(rig, tmp_path):
    argv = _cli(
        rig, "--violations-exit-zero", entry=[sys.executable, "-m", "bantamkit.criticreplay"]
    )
    argv[argv.index(str(rig["transcripts"]))] = str(tmp_path / "nope")
    status, out, err = _shell_status(argv, tmp_path, "hatch-refusal")
    assert status == criticreplay.REFUSAL_EXIT
    assert "no transcripts" in err


def test_the_hatch_does_not_suppress_guard_error(guard_rig, tmp_path):
    status, out, err = _shell_status(
        _cli(
            guard_rig,
            "--guard", "error",
            "--violations-exit-zero",
            entry=[sys.executable, "-m", "bantamkit.criticreplay"],
        ),
        tmp_path,
        "hatch-guard-error",
    )
    assert status == criticreplay.REFUSAL_EXIT
    assert "shared-token guard" in err


def test_the_hatch_does_not_suppress_a_usage_error(tmp_path):
    status, out, err = _shell_status(
        [sys.executable, "-m", "bantamkit.criticreplay", "--violations-exit-zero", "--not-a-flag"],
        tmp_path,
        "hatch-usage",
    )
    assert status == criticreplay.USAGE_EXIT


def test_the_hatch_does_not_suppress_an_unwritable_summary(guard_rig, tmp_path):
    """The hatch says "these violations are expected", never "this run wrote its files"."""
    status, out, err = _shell_status(
        _cli(guard_rig, "--violations-exit-zero", "--summary", str(_unwritable(tmp_path))),
        tmp_path,
        "hatch-unwritable",
    )
    assert status == criticreplay.ARTIFACT_WRITE_EXIT, err
    assert "--violations-exit-zero" in err  # it did suppress the guard status
    assert "could not be written" in err


# ---- RB-P24 review, M1: the epilog is part of the contract, so it is pinned ----


def test_help_prints_the_exit_status_contract(tmp_path):
    """`--help` is where a caller reads the statuses; without this the epilog is undefended."""
    status, out, err = _shell_status(
        [sys.executable, "-m", "bantamkit.criticreplay", "--help"], tmp_path, "help"
    )
    assert status == 0
    assert "exit status (RB-P24)" in out
    for value in (
        criticreplay.REFUSAL_EXIT,
        criticreplay.USAGE_EXIT,
        criticreplay.GUARD_VIOLATION_EXIT,
        criticreplay.ARTIFACT_WRITE_EXIT,
        criticreplay.RENDER_FAILURE_EXIT,
    ):
        assert f"\n  {value}  " in out, f"status {value} is not in the epilog"
    assert "did not complete a measurement" in out
    # RB-P27. The range advice is part of the contract too, and the v0.18.0 wording was
    # wrong about the one case it named. The epilog must state BOTH halves of what
    # replaced it: that a lost stdout on the run path keeps the earned status, and that
    # `--help` and a written-to stderr still leave the range. A patch that quietly
    # upgrades this to a blanket promise of coverage is red here.
    assert "no longer leaves the range" in out and "it EARNED" in out
    assert "--help" in out and "stderr lost while the run was writing to it" in out
    assert "did not run to completion" not in out  # the sentence RB-P27 disproved
    # RB-P31, and this block CHANGED when the defect was fixed rather than when the prose
    # was tidied. At v0.19.0 the epilog disclosed an OPEN defect — a stdout failure that
    # is not a gone reader (EBADF, stderr live) leaving the range at 120, or reporting 1
    # above stdout's buffer — and this node pinned the disclosure so it could not be
    # dropped without fixing the behaviour. The behaviour IS fixed, so what the epilog
    # must now say is the pair of things RB-P24's rule requires of any status change:
    # what happens now, and what still does not.
    #
    # WHAT HAPPENS NOW: the two arms exist and report DIFFERENT numbers, and the epilog
    # has to say which is which — an epilog that said only "a lost stdout keeps the
    # earned status" would be describing a fix that swallows a real loss.
    assert "RB-P31" in out and "EBADF" in out
    assert "NOT the reader going away" in out
    assert "reports the status it EARNED" in out
    assert f"reports {criticreplay.RENDER_FAILURE_EXIT} instead of claiming a clean" in out
    assert "the table is not in it" in out  # what a reader must DO with a 5
    # WHAT STILL DOES NOT: the out-of-range list stays open, `--help` and a written-to
    # stderr are still outside it, and ENOSPC is handled by class rather than by a field
    # measurement. A patch that re-closes the list, or that quietly upgrades the arm into
    # a blanket promise of coverage, is red here.
    assert "OPEN rather than exhaustive" in out
    assert "ENOSPC" in out and "NOT been measured in the field" in out
    # RB-P33. The recovery's own side effect is part of the contract because a caller
    # cannot discover it by reading anything else.
    assert "sys.stdout is replaced by a sink that RAISES" in out
    assert "fd 1 itself is left exactly as it was found" in out
    # K4B/C1. The class the arm was missing is named in the contract, because a caller
    # who reads "fd 1 read-only (EBADF)" and infers "so the fd is the axis" is exactly
    # the reader who set PYTHONIOENCODING and got a traceback.
    assert "PYTHONIOENCODING" in out and "UnicodeEncodeError" in out
    # Why the report is ASCII, stated as what it actually buys: stderr is
    # `backslashreplace`, so the STATUS would survive a non-ASCII byte and the SENTENCE
    # would not. A contract that claimed the stronger thing would be claiming something
    # K4B measured and disproved.
    assert "stderr's own error handler" in out and "backslashreplace" in out
    # K4B/M4. Four prose blocks were deletable with a green suite and this is the one a
    # reader ACTS on: what the artifacts of a 5 are worth. The property is measured in
    # `test_a_stdout_that_cannot_encode_the_table_...`; the sentence is pinned here.
    assert "BYTE-IDENTICAL to what the same argv leaves with a" in out
    # K4B/M1. 4's promise was "The table is still printed", full stop, which is false in
    # the cell where the reader of stdout had already gone — and 5's whole case for
    # outranking 4 is built on that promise, so it has to be stated accurately.
    assert "unless the READER of stdout had already gone" in out
    # K4B/I7. The roster is contract text, and a roster the user cannot read is not one.
    assert _SHAPE_ROSTER in out
    # K4B/M3. Not this module's to fix, and therefore exactly the kind of thing that gets
    # re-filed as a defect of the arm above unless the contract says where it happens.
    assert "init_sys_streams before main" in out


def test_this_modules_own_validation_errors_are_argparses_number(tmp_path):
    """M3: `parser.error` is argparse's exit path, so a bad `--replays` is a 2, not a 1."""
    status, out, err = _shell_status(
        [
            sys.executable, "-m", "bantamkit.criticreplay",
            "--rubric", "a=x", "--transcripts", str(tmp_path),
            "--base-url", "http://x", "--model", "m", "--replays", "0",
        ],
        tmp_path,
        "replays-zero",
    )
    assert status == criticreplay.USAGE_EXIT
    assert "--replays and --identity-replays must be >= 1" in err


# ---- RB-P27 lever (2): with no reader on stdout, a completed run keeps the status it EARNED ----
#
# Filed at docs/eval.md, RB-P27 case (a): with the reader of its stdout gone, a violating
# run COMPLETES — all 32 JSONL rows and a summary carrying both guard violations are on
# disk — and the shell reads 120, the interpreter's number for "flushing stdout at
# shutdown failed". Not 3, not 4, and outside the tool's own range, which is the one case
# where the v0.18.0 epilog's advice ("treat anything outside 0-4 as *did not run to
# completion*") is wrong about a run that demonstrably did.
#
# These are the EXECUTABLE SPEC for the fix, and they were WRITTEN BEFORE IT (f5e38b0,
# three non-strict `xfail` nodes). The handler landed in v0.19.0 and the markers came off;
# the measured pre-fix status they were written against is kept in
# `_CLOSED_PIPE_PREFIX_STATUS` and each node still asserts against it, because the number
# the fix was written to move is evidence and does not get erased by the fix.
#
# METHOD. RB-P24's rule is that a status claim is read from a real `$?`, so the closed-pipe
# harness keeps the shell: `/bin/sh` runs the CLI and echoes its own `$?` to a FILE, and
# the whole shell's stdout is a pipe with NO reader. The read end is closed BEFORE the
# child is spawned, so there is no window in which a reader exists and no race to lose —
# every write to fd 1 fails with EPIPE from the first byte. That is a reader that is
# actually gone (`... | head -1` once `head` has exited), not a mock and not a patched
# `sys.stdout`, which would measure what a function returns rather than what a process
# leaves behind.

_CLOSED_PIPE_PREFIX_STATUS = 120
"""What the shell read on c7d0b72 (v0.18.0), measured 2026-08-12, for all three cases.

    .venv/bin/python -m pytest runtime-py/tests/test_criticreplay.py -q -k closed_pipe \
        --runxfail

The number is the same 120 for a run that earned 0, one that earned 3 and one that
earned 4 — which is the finding: the shutdown failure erases the verdict. That is the
PRE-FIX measurement and it stays here as such; the three nodes below now assert the
earned status AND that it is no longer this number, so the fix is pinned against the
thing it was written to move rather than against a number chosen afterwards.

Reproduce the pre-fix reading at any time: `git stash` the handler, or check out
`c7d0b72`, and run the command above. The equivalent measurement OUTSIDE pytest — which
is what RB-P28 says the spec alone cannot substitute for — is the field command recorded
in RB-P27's closure in `docs/eval.md`.
"""


def _closed_pipe_status(argv: list[str], tmp_path: Path, label: str) -> tuple[int, str]:
    """Run `argv` with stdout wired to a pipe that has no read end. Return `$?` and stderr.

    The status is the shell's own `$?`, written to a file on the side, exactly as
    `_shell_status` does it — nothing here reads a Python return value. stderr is a file
    too, so the interpreter's shutdown complaint (if any) is readable.
    """
    where = tmp_path / f"_pipe-{label}"
    where.mkdir(parents=True, exist_ok=True)
    err, status_file = where / "stderr.txt", where / "status.txt"
    read_fd, write_fd = os.pipe()
    os.close(read_fd)  # the reader is gone before the child exists: no race, no window
    try:
        proc = subprocess.Popen(
            ["/bin/sh", "-c", '"$@" 2>"$BK_ERR"; echo "status=$?" >"$BK_STATUS"', "sh", *argv],
            stdout=write_fd,
            env=_child_env(BK_ERR=str(err), BK_STATUS=str(status_file)),
        )
    finally:
        os.close(write_fd)
    assert proc.wait() == 0  # the shell itself ran to the end of its command list
    text = status_file.read_text()
    assert text.startswith("status="), text
    return int(text.split("=", 1)[1]), err.read_text()


_DUMP_PYTEST_KEYS = (
    "import os, sys; "
    "sys.{stream}.write(repr(sorted(k for k in os.environ if k.startswith('PYTEST_'))))"
)


def test_the_status_harnesses_hand_the_child_no_pytest_marker(tmp_path):
    """RB-P28's closeable half, PINNED — a test that goes red, not a comment (`_child_env`).

    The child is asked to report its own `PYTEST_*` keys, through BOTH harnesses, and the
    answer has to be the empty list. The parent assertion is what makes this
    non-vacuous: `PYTEST_CURRENT_TEST` IS in this process's environment right now, so an
    empty list downstream is the scrub working and not the variable being absent. Delete
    the filter in `_child_env` and both halves go red.

    The closed-pipe half reports on STDERR because its stdout is a pipe with no reader —
    the one stream that harness leaves readable.
    """
    assert "PYTEST_CURRENT_TEST" in os.environ  # the thing being scrubbed exists here

    status, out, err = _shell_status(
        [sys.executable, "-c", _DUMP_PYTEST_KEYS.format(stream="stdout")], tmp_path, "envscrub"
    )
    assert status == 0, err
    assert out == "[]", out

    status, err = _closed_pipe_status(
        [sys.executable, "-c", _DUMP_PYTEST_KEYS.format(stream="stderr")], tmp_path, "envscrub"
    )
    assert status == 0, err
    assert err == "[]", err


def test_closed_pipe_clean_run_still_exits_zero(rig, tmp_path):
    """Earned 0. A lost stdout may DOWNGRADE to a status the run had; it may not invent one."""
    status, err = _closed_pipe_status(_cli(rig), tmp_path, "clean")
    assert status == 0, err
    assert status != _CLOSED_PIPE_PREFIX_STATUS  # what c7d0b72 read here


def test_closed_pipe_violating_run_still_exits_three_and_writes_the_same_bytes(
    guard_rig, tmp_path
):
    """Earned 3 — and the artifacts are BYTE-IDENTICAL to the same run with a live reader.

    Two properties in one test on purpose. The status is the finding; the byte comparison
    is what stops the fix from being "exit 3 somehow" — the run must still have measured,
    and losing the reader of the table may not change one byte of the JSONL or the summary.
    The open-pipe run is `_shell_status`, i.e. the already-pinned RB-P24 path, so the
    earned status is read from an INDEPENDENT run rather than asserted from this file.
    """
    live_rows, live_summary = tmp_path / "live.jsonl", tmp_path / "live.json"
    live_status, out, _ = _shell_status(
        _cli(guard_rig, "--json", str(live_rows), "--summary", str(live_summary)),
        tmp_path,
        "p27-live",
    )
    assert live_status == criticreplay.GUARD_VIOLATION_EXIT  # what the run EARNS
    assert "GUARD VIOLATIONS" in out

    dark_rows, dark_summary = tmp_path / "dark.jsonl", tmp_path / "dark.json"
    status, err = _closed_pipe_status(
        _cli(guard_rig, "--json", str(dark_rows), "--summary", str(dark_summary)),
        tmp_path,
        "violating",
    )
    assert status == live_status, err
    assert status != 0  # a handler that swallowed everything into a 0 fails here
    assert status != _CLOSED_PIPE_PREFIX_STATUS  # what c7d0b72 read here
    assert dark_summary.read_bytes() == live_summary.read_bytes()
    assert dark_rows.read_bytes() == live_rows.read_bytes()


def test_closed_pipe_unwritable_summary_still_exits_four(guard_rig, tmp_path):
    """Earned 4, and 4 IS reachable in this harness — so the spec covers three earned values.

    4 outranks 3 (RB-P24), and the write failure is reported on stderr, which still has a
    reader. So this is also the case that distinguishes "downgrade to the earned status"
    from "exit 3 whenever the guard fired".
    """
    rows_path = tmp_path / "rows.jsonl"
    status, err = _closed_pipe_status(
        _cli(guard_rig, "--json", str(rows_path), "--summary", str(_unwritable(tmp_path))),
        tmp_path,
        "unwritable",
    )
    assert status == criticreplay.ARTIFACT_WRITE_EXIT, err
    assert status != _CLOSED_PIPE_PREFIX_STATUS  # what c7d0b72 read here
    assert "could not be written" in err
    assert len(rows_path.read_text().splitlines()) > 0  # it measured


# The controls. These pass on c7d0b72 and must keep passing after the fix: they are what
# catches a handler that buys the three tests above by swallowing genuine failures.


def test_closed_pipe_refusal_is_still_a_refusal(rig, tmp_path):
    """Control: a run that never measured writes nothing to stdout, so it is 1 either way.

    A handler that reported an "earned" status for a run that refused — or that turned an
    unhandled error into 0 because stdout happened to be broken — is red here.
    """
    argv = _cli(rig, entry=[sys.executable, "-m", "bantamkit.criticreplay"])
    argv[argv.index(str(rig["transcripts"]))] = str(tmp_path / "nope")
    status, err = _closed_pipe_status(argv, tmp_path, "refusal")
    assert status == criticreplay.REFUSAL_EXIT
    assert "no transcripts" in err


def test_closed_pipe_usage_error_is_still_the_usage_status(tmp_path):
    """Control: argparse's number survives a dead stdout, because it writes to stderr."""
    status, err = _closed_pipe_status(
        [sys.executable, "-m", "bantamkit.criticreplay", "--not-a-flag"], tmp_path, "usage"
    )
    assert status == criticreplay.USAGE_EXIT


@pytest.mark.parametrize(
    "boom",
    [
        pytest.param(RuntimeError("format_table is broken"), id="not-an-OSError"),
        pytest.param(OSError(errno.ENOSPC, "No space left on device"), id="OSError-not-EPIPE"),
    ],
)
def test_a_non_pipe_failure_around_the_table_print_is_not_downgraded(boom, rig, monkeypatch):
    """Control, and the direct answer to "what if the handler swallows a genuine error?".

    STILL BITES AFTER RB-P31, and what it bites on MOVED — read this before assuming it
    is the same node. Before RB-P31, `format_table(summary)` was evaluated INSIDE the
    shipped `try` and both raisers reached the caller only because `except
    BrokenPipeError` refused them; the docstring said hoisting the call out of the `try`
    "would make this control pass for a reason that has nothing to do with the handler".
    RB-P31 widened the arm to `OSError`, so that reading is no longer available: an
    `OSError` raised inside the `try` is now converted to `RENDER_FAILURE_EXIT` on
    purpose. The hoist is therefore not a way around this control, it IS the decision
    this control now pins — a failure to BUILD the table is a bug in the module and must
    keep its traceback, and only the WRITE may be converted into a status.

    So: move `format_table(summary)` back inside the `try` and the `OSError-not-EPIPE`
    case goes red, because a module bug would then be laundered into a documented
    "measured, but the report could not be rendered". The `not-an-OSError` case is red
    either way and stays as the cheaper canary.

    The complementary half — a non-OSError raised BY THE WRITE, which is inside the arm's
    reach — is `test_a_non_oserror_at_the_table_write_is_not_downgraded` below. Between
    them the arm is pinned on both sides: nothing wider than `OSError`, and nothing
    earlier than the write.

    In-process on purpose: this is about which exception propagates out of `main`, not
    about a status a shell reads. The status contract itself is never pinned this way
    (RB-P24).
    """
    monkeypatch.setattr(criticreplay, "OpenAICompatible", lambda **kw: ScriptedCritic(lambda p: 9))

    def explode(_summary):
        raise boom

    monkeypatch.setattr(criticreplay, "format_table", explode)
    argv = _cli(rig)[2:]  # the same flags, minus the `python probe.py` entry point
    with pytest.raises(type(boom)):
        criticreplay.main(argv)


class _RaisingStdout:
    """A `sys.stdout` whose `write` raises. The only way to fail the WRITE in-process.

    Deliberately not a mock of the handler: `print` calls `write` on whatever `sys.stdout`
    is bound to, so this fails the same call the field rigs fail, one layer up. The field
    measurement of the same class is `_readonly_stdout_status`, and it is what the
    acceptance rests on — this is a regression guard for the shapes a real fd cannot make
    portably (`ENOSPC` needs `/dev/full`, which macOS does not have; K1 said so and did
    not fabricate one).
    """

    def __init__(self, boom: BaseException) -> None:
        self.boom = boom

    def write(self, _text: str) -> int:
        raise self.boom

    def flush(self) -> None:
        return None


def test_a_non_oserror_at_the_table_write_is_not_downgraded(rig, monkeypatch):
    """The arm is `except OSError`, not `except Exception` — pinned where it can be widened.

    Its sibling above raises from `format_table`, which now sits OUTSIDE the `try`, so it
    cannot see a widening of the arm itself. This one raises from inside the `try`, at the
    write, which is the only place the arm reaches. Change `except OSError` to `except
    Exception` and this goes red: a genuine bug at the write would otherwise be reported
    as "measured, but the report could not be rendered", i.e. as a clean measurement of a
    run whose failure was never diagnosed.
    """
    monkeypatch.setattr(criticreplay, "OpenAICompatible", lambda **kw: ScriptedCritic(lambda p: 9))
    boom = RuntimeError("the write itself is broken")
    monkeypatch.setattr(sys, "stdout", _RaisingStdout(boom))
    with pytest.raises(RuntimeError):
        criticreplay.main(_cli(rig)[2:])


def test_a_non_unicode_valueerror_at_the_table_write_is_not_downgraded(rig, monkeypatch):
    """K4B/C1's control: the widening is pinned exactly where it STOPS.

    The arm caught `OSError` and nothing else, and the node above justified that on "a
    non-`OSError` at the write is a bug in this module". K4 disproved the generalisation
    with the one realistic counter-example — `UnicodeEncodeError`, which is a
    `ValueError` and is a property of the CALLER'S STDOUT exactly as `EBADF` is a
    property of the caller's fd — so the arm is now `except (OSError,
    UnicodeEncodeError)`.

    A widening argued from a counter-example needs a node at the new edge, or the next
    reader has only the sibling above (a `RuntimeError`, which `except ValueError` would
    still let through). This raises a BARE `ValueError` from the write: the direct
    superclass of the class that WAS added, and the cheapest mutation that turns the new
    line into "any ValueError is the caller's fault". Change the arm to `except (OSError,
    ValueError)` — or to `except Exception` — and this goes red while every field cell
    stays green, which is the point: no field measurement can reach this, because a
    shell cannot make a real stdout raise a bare `ValueError`.
    """
    monkeypatch.setattr(criticreplay, "OpenAICompatible", lambda **kw: ScriptedCritic(lambda p: 9))
    boom = ValueError("I/O operation on closed file")
    monkeypatch.setattr(sys, "stdout", _RaisingStdout(boom))
    with pytest.raises(ValueError) as exc:
        criticreplay.main(_cli(rig)[2:])
    assert exc.value is boom  # it propagated, it was not converted into a status


def test_an_enospc_failure_at_the_table_write_reports_the_render_failure_status(
    rig, monkeypatch, capsys
):
    """ENOSPC, the cell K1 could NOT construct in the field, as a regression guard only.

    Read the label: this is a SIMULATION and it is not evidence about the shipped
    behaviour (RB-P28). macOS has no `/dev/full`, so K1 filed ENOSPC as a gap rather than
    fabricating a number for it, and that gap is still open — what this node buys is that
    the arm is keyed on `OSError` as a class rather than on `EBADF`, so the errno the
    field CAN produce is not the only one the code handles. The EBADF and closed-fd cells
    of the same class ARE field-measured, in
    `docs/eval-data/2026-08-13-rbp31-render-failure-matrix.md`.
    """
    monkeypatch.setattr(criticreplay, "OpenAICompatible", lambda **kw: ScriptedCritic(lambda p: 9))
    boom = OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(sys, "stdout", _RaisingStdout(boom))
    with pytest.raises(SystemExit) as exc:
        criticreplay.main(_cli(rig)[2:])
    assert exc.value.code == criticreplay.RENDER_FAILURE_EXIT
    assert "could not be rendered" in capsys.readouterr().err


def test_a_lost_stdout_raises_on_the_next_write_instead_of_swallowing_it(rig, monkeypatch):
    """RB-P33's requirement, pinned: after `main`, silence is the one option not available.

    v0.19.0 recovered from a lost stdout with `os.dup2(devnull, 1)`, which left this
    process's fd 1 pointing at the null device for the rest of its life — so every later
    write, including a child's, silently succeeded into nothing, and an in-process caller
    (`main` is in `__all__`, and `cli_exit_status_probe.py` calls it) could not discover
    the loss. The replacement rebinds `sys.stdout` and leaves fd 1 alone; a write after
    `main` re-raises the original failure.

    Two assertions, and the second is the one RB-P33 actually asked for: the recovery
    happened at all, and it did not turn into a silent sink.
    """
    monkeypatch.setattr(criticreplay, "OpenAICompatible", lambda **kw: ScriptedCritic(lambda p: 9))
    boom = OSError(errno.EBADF, "Bad file descriptor")
    monkeypatch.setattr(sys, "stdout", _RaisingStdout(boom))
    with pytest.raises(SystemExit):
        criticreplay.main(_cli(rig)[2:])

    assert isinstance(sys.stdout, criticreplay._LostStdout)
    sys.stdout.flush()  # the finalization flush's own call: it must NOT raise
    with pytest.raises(OSError) as exc:
        sys.stdout.write("a caller that keeps writing must be told, not lied to")
    assert exc.value is boom


def test_a_lost_pipe_also_raises_on_the_next_write_instead_of_swallowing_it(rig, monkeypatch):
    """K4B/I6: RB-P33's no-silent-sink property for the OTHER arm, which had no node.

    `_LostStdout` is ONE recovery for two arms, and only the `OSError` arm's use of it
    was pinned — so replacing the `BrokenPipeError` arm's `sys.stdout = _LostStdout(e)`
    with a swallowing sink (a `write` that returns the length and lies) scored 748/748
    (K4, demonstrated). That is the exact defect RB-P33 was filed for, re-introducible in
    the arm nobody was watching, and it is worse here than in its sibling: this arm
    DOWNGRADES to the earned status, so a caller who kept writing would get a clean
    number AND silence.

    Same two assertions as its sibling, and the second is the one RB-P33 asked for. The
    earned status is 0 on this rig, so `main` returns rather than raising `SystemExit` —
    which is itself the EPIPE arm's contract (a lost reader may downgrade, never invent).
    """
    monkeypatch.setattr(criticreplay, "OpenAICompatible", lambda **kw: ScriptedCritic(lambda p: 9))
    boom = BrokenPipeError(errno.EPIPE, "Broken pipe")
    monkeypatch.setattr(sys, "stdout", _RaisingStdout(boom))
    criticreplay.main(_cli(rig)[2:])  # earned 0, and a gone reader may not change that

    assert isinstance(sys.stdout, criticreplay._LostStdout)
    sys.stdout.flush()  # the finalization flush's own call: it must NOT raise
    with pytest.raises(BrokenPipeError) as exc:
        sys.stdout.write("a caller that keeps writing must be told, not lied to")
    assert exc.value is boom


# ---- What the handler does NOT cover, measured rather than assumed ----
#
# The v0.19.0 contract claims coverage for exactly one thing: the run path's own write to
# stdout — the table print, its flush, and the interpreter's shutdown flush behind it. It
# says in the same breath that a lost stdout OUTSIDE that write, and a lost stderr the run
# actually writes to, still leave the range. These two nodes are what make that half of
# the sentence a claim rather than a hedge: if a later change extends the handler, they go
# red and the contract prose has to be corrected with them.


def _closed_stderr_status(argv: list[str], tmp_path: Path, label: str) -> tuple[int, str]:
    """`_closed_pipe_status`'s twin, with the dead pipe on STDERR and stdout on a file.

    Same method, same guarantee — the read end is closed before the child exists, so
    every write to fd 2 fails with EPIPE from the first byte — and the same independent
    reader: the status is `/bin/sh`'s own `$?`, echoed to a file on the side. Written as
    its own function rather than as a flag on `_closed_pipe_status` so that the harness
    the RB-P27 spec is measured with stays exactly the one that measured the pre-fix 120.
    """
    where = tmp_path / f"_pipe-err-{label}"
    where.mkdir(parents=True, exist_ok=True)
    out, status_file = where / "stdout.txt", where / "status.txt"
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    try:
        proc = subprocess.Popen(
            ["/bin/sh", "-c", '"$@" >"$BK_OUT"; echo "status=$?" >"$BK_STATUS"', "sh", *argv],
            stderr=write_fd,
            env=_child_env(BK_OUT=str(out), BK_STATUS=str(status_file)),
        )
    finally:
        os.close(write_fd)
    assert proc.wait() == 0
    text = status_file.read_text()
    assert text.startswith("status="), text
    return int(text.split("=", 1)[1]), out.read_text()


def test_help_with_no_reader_on_stdout_is_still_the_interpreters_number(tmp_path):
    """UNCOVERED, and named as uncovered in the contract: argparse's own write to stdout.

    `--help` renders the epilog and exits before `main` reaches its table print, so the
    RB-P27 handler is not on that path at all and the shutdown flush is what the shell
    sees. Measured, not assumed. A change that covers this may delete this node — and
    must then also correct the sentence in `_EXIT_CONTRACT` that this node pins.
    """
    status, _ = _closed_pipe_status(
        [sys.executable, "-m", "bantamkit.criticreplay", "--help"], tmp_path, "help"
    )
    assert status == _CLOSED_PIPE_PREFIX_STATUS


def test_a_refusal_whose_stderr_has_no_reader_leaves_the_range(rig, tmp_path):
    """UNCOVERED, and named as uncovered in the contract: a lost STDERR the run writes to.

    The refusal path's `error: …` goes to stderr, so with no reader there the interpreter's
    shutdown flush fails on fd 2 and the refusal status is erased exactly as the table
    print's used to be. The handler is about stdout and does not reach this.

    The companion measurement, deliberately NOT asserted as a contract promise because it
    is a property of buffering rather than of this tool: a run that writes NOTHING to
    stderr survives a dead stderr with its earned status intact (there is nothing to
    flush). `docs/eval.md`'s RB-P27 closure records both numbers.
    """
    argv = _cli(rig, entry=[sys.executable, "-m", "bantamkit.criticreplay"])
    argv[argv.index(str(rig["transcripts"]))] = str(tmp_path / "nope")
    status, _ = _closed_stderr_status(argv, tmp_path, "refusal")
    assert status == _CLOSED_PIPE_PREFIX_STATUS
    assert status != criticreplay.REFUSAL_EXIT  # the number the run would otherwise report


# ---- RB-P31: a render failure that is NOT a gone reader, at BOTH sides of the buffer ----
#
# Filed at docs/eval.md, RB-P31, and CLOSED by the second arm added here. At 5538624 the
# RB-P27 handler converted `BrokenPipeError` and nothing else, deliberately, and the price
# was that any OTHER failure of the run path's own write to stdout escaped `main`
# untouched on a run that MEASURED — every JSONL row and the summary on disk,
# byte-identical to the same run with a live reader — and the shell read a number that
# said the opposite. It now reports `RENDER_FAILURE_EXIT`: measured, and the report is
# gone. Two arms, two numbers, because the two situations are not the same situation —
# see the module comment's `#   5` block for the argument, and the block above
# `_RBP31_XFAIL` for why these three nodes assert a different number than K1 wrote.
#
# THE AXIS IS THE BUFFER, AND THE BUFFER IS A PROPERTY OF FD 1, NOT OF THIS TOOL. Which
# wrong number the shell reads depends on whether the failing write went through
# `BufferedWriter`'s buffer or straight past it, and that buffer is `os.fstat(1).st_blksize`
# — 4096 for a regular file here, 16384 for a pipe, 65536 for `/dev/null`. Measured
# 2026-08-13 in a real shell (docs/eval-data/2026-08-13-rbp31-render-failure-matrix.md):
#
#   table+newline <= the buffer  ->  the bytes sit in the buffer, `flush()` raises, the
#                                    interpreter's shutdown flush raises AGAIN, and the
#                                    status becomes 120
#   table+newline  > the buffer  ->  the write goes straight to the fd and raises with an
#                                    empty buffer behind it, shutdown has nothing left to
#                                    fail on, and the uncaught OSError's own 1 stands
#
# 1 is the worse half: that is REFUSAL_EXIT, "did not complete a measurement", on a run
# that completed — the RB-P24 defect class, alive one line from where RB-P24 fixed it.
#
# THIS IS WHY THE SPEC IS WRITTEN AT TWO SIZES. The three RB-P27 nodes above pinned 120
# because 120 is what the SMALL table read; the same pre-fix tree read 1 at a table over
# the pipe's 16384 (measured on c7d0b72, in the artifact). A single-size node pins half a
# defect, and a fix fitted to one cell of the matrix fixes one cell of it.

_RBP31_PREFIX_STATUS = {
    "below-buffer": 120,
    "above-buffer": criticreplay.REFUSAL_EXIT,
    "closed": criticreplay.REFUSAL_EXIT,
}
"""What a real shell read at 5538624 (v0.19.0), measured 2026-08-13, earned status 3.

Field commands and the full 45-cell matrix are in
`docs/eval-data/2026-08-13-rbp31-render-failure-matrix.md`; the numbers there are read
from `/bin/sh` in an environment with no `PYTEST_*` key in it, because RB-P28 is open and
a green run of THIS file is not evidence about the shipped behaviour.
"""

# K1 WROTE THESE THREE NODES AS `xfail`s ASSERTING `status == live_status`, i.e. that a
# render failure would DOWNGRADE to the earned status the way EPIPE does. K2 OVERTURNED
# THAT, and the nodes below now pin `RENDER_FAILURE_EXIT` instead. The argument, in full,
# is in the module comment's `#   5` block; the short form is that EPIPE downgrades
# because NOBODY WAS READING, so the table's absence costs no one anything, while every
# cell of this matrix has a live stderr and a reader who wanted the report and did not
# get it. Reporting 0 there would say "measured, clean" about a run whose report nobody
# received, which is the exact sentence the RB-P27 handler's own comment refuses.
#
# K1's spec was a hypothesis written before the design existed and overturning it with an
# argument is the honest move; what would not have been is relaxing it to pin nothing.
# So the three nodes still pin a NUMBER, still read it from a real shell's `$?`, still
# assert the byte identity FIRST and unchanged, and still assert the pre-fix numbers are
# gone. The one thing that changed is which number is correct, and why.
_RBP31_XFAIL = pytest.mark.xfail(
    reason=(
        "RB-P31 was open at 5538624: a stdout write that fails on the run path for a "
        "reason other than a gone reader is not converted by the RB-P27 handler, so a "
        "run that measured — rows and summary on disk, byte-identical to a live-reader "
        "run — reports 120 below fd 1's buffer and REFUSAL_EXIT above it, and "
        "REFUSAL_EXIT unconditionally when fd 1 is closed outright. NO LONGER APPLIED "
        "to the three nodes below (the fix landed and they assert RENDER_FAILURE_EXIT); "
        "kept because the wording is the record of what they were written against, and "
        "re-applying it is how a reader re-checks them against a pre-fix tree."
    ),
)


def _wide_guard_rig(asset_tree, tmp_path, cells: int) -> dict:
    """`guard_rig` with `cells` cells instead of one, so the table can be made to straddle.

    Same manifest, same rubric pair, same violating point — only the number of (task,
    repeat) cells changes, because the table is one line per (cell, variant) plus the
    GUARD section's lines per violating pair. Nothing here touches the shipped assets.
    """
    _write_manifest(asset_tree, points=GUARD_POINTS)
    transcripts = tmp_path / f"transcripts-{cells}"
    for repeat in range(cells):
        _transcript(transcripts, "critique", "alpha", repeat, 100 + repeat, "OUT")
    return {
        "before": _write_rubric(tmp_path, "before", BASE_PROMPT),
        "transcripts": transcripts,
    }


_RBP31_SMALL_CELLS = 1
_RBP31_LARGE_CELLS = 40


def _readonly_stdout_status(argv, tmp_path, label: str) -> tuple[int, str, int]:
    """Run `argv` with fd 1 a dup of a READ-ONLY fd. Return `$?`, stderr, and fd 1's buffer.

    A read-only fd is the cheapest render failure that is NOT a gone reader: every write
    to fd 1 fails with `EBADF`, and stderr stays live throughout, so this is a report that
    could not be rendered rather than a reader that walked away. The fd is opened here and
    handed to the child as its stdout, so nothing is patched and no exception is injected.

    The status is `/bin/sh`'s own `$?`, echoed to a file on the side — RB-P24's rule.
    The third return value is `os.fstat(1).st_blksize`, which IS the `BufferedWriter`
    size CPython gives that fd and therefore the axis this spec is written across.
    """
    where = tmp_path / f"_ro-{label}"
    where.mkdir(parents=True, exist_ok=True)
    target = where / "readonly-target"
    target.write_text("fd 1 is a dup of a READ-ONLY fd on this file\n")
    err, status_file = where / "stderr.txt", where / "status.txt"
    ro_fd = os.open(target, os.O_RDONLY)
    try:
        blksize = os.fstat(ro_fd).st_blksize
        proc = subprocess.Popen(
            ["/bin/sh", "-c", '"$@" 2>"$BK_ERR"; echo "status=$?" >"$BK_STATUS"', "sh", *argv],
            stdout=ro_fd,
            env=_child_env(BK_ERR=str(err), BK_STATUS=str(status_file)),
        )
    finally:
        os.close(ro_fd)
    assert proc.wait() == 0  # the shell itself ran to the end of its command list
    text = status_file.read_text()
    assert text.startswith("status="), text
    return int(text.split("=", 1)[1]), err.read_text(), blksize


def _no_stdout_status(argv, tmp_path, label: str) -> tuple[int, str]:
    """`_readonly_stdout_status`'s twin with fd 1 CLOSED outright (`1>&-`), not redirected.

    A different failure again, and the one with no `OSError` in it at all: CPython leaves
    `sys.stdout` as `None` when fd 1 is invalid at startup, `print` to a `None` stdout is
    a silent no-op, and the explicit `sys.stdout.flush()` raises `AttributeError`. So the
    handler never sees an exception it could convert, whatever it is narrowed to.
    """
    where = tmp_path / f"_nofd1-{label}"
    where.mkdir(parents=True, exist_ok=True)
    err, status_file = where / "stderr.txt", where / "status.txt"
    proc = subprocess.run(
        [
            "/bin/sh", "-c",
            '{ "$@" 2>"$BK_ERR"; echo "status=$?" >"$BK_STATUS"; } 1>&-', "sh", *argv,
        ],
        env=_child_env(BK_ERR=str(err), BK_STATUS=str(status_file)),
    )
    assert proc.returncode == 0
    text = status_file.read_text()
    assert text.startswith("status="), text
    return int(text.split("=", 1)[1]), err.read_text()


def test_the_two_render_failure_rigs_straddle_the_measured_stdout_buffer(
    asset_tree, tmp_path
):
    """NOT an xfail. The fixture guard the two nodes below depend on, and it must stay green.

    An `xfail` that fails because its rig drifted pins nothing (the RB-P28 lesson applied
    to this file's own fixtures). The two status nodes below claim to sit on OPPOSITE
    sides of fd 1's `BufferedWriter`, and that is a property of the rig, the filesystem
    and the table's width — none of which this file controls. So the straddle is asserted
    HERE, where a drift is a red suite rather than a silently mis-aimed `xfail`.

    Both rigs also have to EARN 3, read from an independent live-reader run, or the status
    nodes would be pinning a downgrade that was never a downgrade.
    """
    _, _, blksize = _readonly_stdout_status(
        [sys.executable, "-c", "pass"], tmp_path, "blksize"
    )
    assert blksize > 0

    for label, cells, side in (
        ("small", _RBP31_SMALL_CELLS, "below"),
        ("large", _RBP31_LARGE_CELLS, "above"),
    ):
        rig = _wide_guard_rig(asset_tree, tmp_path, cells)
        status, out, err = _shell_status(_cli(rig), tmp_path, f"straddle-{label}")
        assert status == criticreplay.GUARD_VIOLATION_EXIT, err  # what the run EARNS
        assert "GUARD VIOLATIONS" in out
        written = len(out.encode())  # `print` writes the table AND its newline
        if side == "below":
            assert written <= blksize, (
                f"the {label} rig writes {written} bytes, which no longer fits fd 1's "
                f"{blksize}-byte buffer — the below-buffer node is aimed at the wrong cell"
            )
        else:
            assert written > blksize, (
                f"the {label} rig writes {written} bytes, which now fits fd 1's "
                f"{blksize}-byte buffer — the above-buffer node is aimed at the wrong cell"
            )


def test_a_render_failure_below_the_buffer_reports_the_render_failure_status(
    asset_tree, tmp_path
):
    """Earned 3, table smaller than fd 1's buffer. A real shell read 120 at 5538624.

    The table print buffers, `flush()` raises `EBADF`, the buffer keeps the bytes, and
    the interpreter's shutdown flush fails on them again — which replaced the earned
    status with the interpreter's number exactly as RB-P27 found for `EPIPE`. The fix
    neutralises that second flush by rebinding `sys.stdout`, so the number this run
    chooses is the number the shell reads.

    K1 wrote this node asserting `status == live_status`; see the block above for why it
    now asserts `RENDER_FAILURE_EXIT` instead. Everything before the status assertion is
    K1's, byte for byte: the run has to have MEASURED before its status means anything.
    """
    rig = _wide_guard_rig(asset_tree, tmp_path, _RBP31_SMALL_CELLS)
    live_rows, live_summary = tmp_path / "live-s.jsonl", tmp_path / "live-s.json"
    live_status, out, _ = _shell_status(
        _cli(rig, "--json", str(live_rows), "--summary", str(live_summary)),
        tmp_path,
        "p31-live-small",
    )
    assert live_status == criticreplay.GUARD_VIOLATION_EXIT
    assert "GUARD VIOLATIONS" in out

    dark_rows, dark_summary = tmp_path / "dark-s.jsonl", tmp_path / "dark-s.json"
    status, err, _ = _readonly_stdout_status(
        _cli(rig, "--json", str(dark_rows), "--summary", str(dark_summary)),
        tmp_path,
        "small",
    )
    assert "Bad file descriptor" in err  # the failure really is EBADF, not EPIPE
    assert dark_rows.read_bytes() == live_rows.read_bytes()  # it MEASURED
    assert dark_summary.read_bytes() == live_summary.read_bytes()
    assert live_status == criticreplay.GUARD_VIOLATION_EXIT  # what the run EARNED
    assert status == criticreplay.RENDER_FAILURE_EXIT, err
    assert status != _RBP31_PREFIX_STATUS["below-buffer"]  # what 5538624 read here
    assert "could not be rendered" in err  # and it says so, on the stream that survived


def test_a_render_failure_above_the_buffer_reports_the_render_failure_status(
    asset_tree, tmp_path
):
    """Earned 3, table LARGER than fd 1's buffer. A real shell read 1 at 5538624.

    The other side of the axis, and the half the RB-P27 nodes never covered. Here the
    write bypasses the buffer, so the shutdown flush had nothing left to fail on and the
    uncaught `OSError`'s own status stood — and that status was `REFUSAL_EXIT`, on a run
    whose rows and summary are byte-identical to the live-reader run asserted below.
    That is a run that measured reporting that it refused: the RB-P24 defect class, and
    the reason this node exists at a second size rather than trusting the first.

    Same amendment as its sibling: K1 pinned `live_status`, K2 pins
    `RENDER_FAILURE_EXIT`, with the argument in the block above.
    """
    rig = _wide_guard_rig(asset_tree, tmp_path, _RBP31_LARGE_CELLS)
    live_rows, live_summary = tmp_path / "live-l.jsonl", tmp_path / "live-l.json"
    live_status, out, _ = _shell_status(
        _cli(rig, "--json", str(live_rows), "--summary", str(live_summary)),
        tmp_path,
        "p31-live-large",
    )
    assert live_status == criticreplay.GUARD_VIOLATION_EXIT
    assert "GUARD VIOLATIONS" in out

    dark_rows, dark_summary = tmp_path / "dark-l.jsonl", tmp_path / "dark-l.json"
    status, err, _ = _readonly_stdout_status(
        _cli(rig, "--json", str(dark_rows), "--summary", str(dark_summary)),
        tmp_path,
        "large",
    )
    assert "Bad file descriptor" in err
    assert dark_rows.read_bytes() == live_rows.read_bytes()
    assert dark_summary.read_bytes() == live_summary.read_bytes()
    assert live_status == criticreplay.GUARD_VIOLATION_EXIT  # what the run EARNED
    assert status == criticreplay.RENDER_FAILURE_EXIT, err
    assert status != _RBP31_PREFIX_STATUS["above-buffer"]  # what 5538624 read here
    assert "could not be rendered" in err


def test_a_closed_stdout_does_not_turn_a_measured_run_into_a_refusal(asset_tree, tmp_path):
    """fd 1 CLOSED outright. A real shell read 1 at 5538624, at BOTH table sizes.

    Not in RB-P31 as filed, found while running its matrix, and the worst cell in it: no
    buffer is involved, so there was no size at which this was anything but `REFUSAL_EXIT`
    on a run with every artifact on disk. It is also the cell no `except OSError` arm
    around the print can reach — the exception is an `AttributeError` from
    `sys.stdout.flush()` on a `None` stdout, and `print` itself never raised. The fix
    therefore READS the state (`sys.stdout is None`) rather than catching anything, and
    that branch is what this node pins: delete it and this cell alone goes back to 1.

    The node keeps its name, because the name is still the claim — a measured run may not
    report a refusal. What it asserts is now the positive number, not the earned one.
    """
    rig = _wide_guard_rig(asset_tree, tmp_path, _RBP31_SMALL_CELLS)
    live_rows, live_summary = tmp_path / "live-c.jsonl", tmp_path / "live-c.json"
    live_status, _, _ = _shell_status(
        _cli(rig, "--json", str(live_rows), "--summary", str(live_summary)),
        tmp_path,
        "p31-live-closed",
    )
    assert live_status == criticreplay.GUARD_VIOLATION_EXIT

    dark_rows, dark_summary = tmp_path / "dark-c.jsonl", tmp_path / "dark-c.json"
    status, err = _no_stdout_status(
        _cli(rig, "--json", str(dark_rows), "--summary", str(dark_summary)),
        tmp_path,
        "closed",
    )
    assert dark_rows.read_bytes() == live_rows.read_bytes()
    assert dark_summary.read_bytes() == live_summary.read_bytes()
    assert live_status == criticreplay.GUARD_VIOLATION_EXIT  # what the run EARNED
    assert status == criticreplay.RENDER_FAILURE_EXIT, err
    assert status != _RBP31_PREFIX_STATUS["closed"]  # what 5538624 read here
    assert status != criticreplay.REFUSAL_EXIT  # the RB-P24 rule, said in its own words
    assert "could not be rendered" in err


# ---- K4B/C1: the render arm was one class too narrow, and one env var reached past it ----
#
# The table's GUARD section always carries U+2014 and U+00A7, so a stdout wrapped in a
# codec that cannot represent them makes `print(table)` raise `UnicodeEncodeError` — a
# `ValueError`, NOT an `OSError`. At 3981efd that escaped the arm, printed a traceback and
# the shell read REFUSAL_EXIT on a run whose rows and summary were byte-identical to the
# same argv on a live stdout that earned 3. That is the RB-P24 defect class, and it was
# the PR's own headline ("a run that measured stops reporting a refusal") being false as
# shipped. Field-measured before and after in
# docs/eval-data/2026-08-13-k4b-c1-stdout-encoding-matrix.md; these nodes are the
# regression guard, never the evidence (RB-P28 is open).
#
# `PYTHONIOENCODING` is the instrument because it is the caller's, not this module's: it
# changes nothing inside the process except the codec CPython wraps fd 1 in, which is
# exactly the claim the fix rests on — the codec is a property of the stdout the caller
# handed us, in the way EBADF is a property of the fd they handed us.

_C1_PREFIX_STATUS = criticreplay.REFUSAL_EXIT
"""What a real shell read at 3981efd, measured 2026-08-13, for every cell below.

Both codecs, both table sizes, and every rung of the ladder (`--violations-exit-zero`,
an unwritable `--summary`): status 1, 0 bytes on stdout, a `UnicodeEncodeError`
traceback on stderr, and artifacts byte-identical to the live-stdout run that earned 3.
The number is REFUSAL_EXIT and the run had measured, which is the whole finding.
"""


def _encoding_stdout_status(
    argv: list[str], tmp_path: Path, label: str, encoding: str
) -> tuple[int, bytes, bytes]:
    """Run `argv` with stdout wrapped in `encoding`. Return `$?`, stdout bytes, stderr bytes.

    Nothing is patched and no exception is injected: `PYTHONIOENCODING` is read by
    CPython while it builds `sys.stdout`, so the failure happens in the real
    `TextIOWrapper` on a real fd, at the same `write` call the field's EBADF cells fail.
    fd 1 here is a perfectly good file — that is the point of the cell. The status is
    `/bin/sh`'s own `$?`, echoed to a file on the side (RB-P24's rule).

    Both streams come back as BYTES, because whether stderr's own bytes survive the same
    codec is one of the things under test.
    """
    where = tmp_path / f"_enc-{label}"
    where.mkdir(parents=True, exist_ok=True)
    out, err, status_file = where / "stdout.txt", where / "stderr.txt", where / "status.txt"
    proc = subprocess.run(
        [
            "/bin/sh", "-c",
            '"$@" >"$BK_OUT" 2>"$BK_ERR"; echo "status=$?" >"$BK_STATUS"', "sh", *argv,
        ],
        env=_child_env(
            BK_OUT=str(out), BK_ERR=str(err), BK_STATUS=str(status_file),
            PYTHONIOENCODING=encoding,
        ),
    )
    assert proc.returncode == 0  # the shell itself ran to the end of its command list
    text = status_file.read_text()
    assert text.startswith("status="), text
    return int(text.split("=", 1)[1]), out.read_bytes(), err.read_bytes()


@pytest.mark.parametrize("encoding", ["latin-1", "ascii"])
@pytest.mark.parametrize(
    "cells", [_RBP31_SMALL_CELLS, _RBP31_LARGE_CELLS], ids=["small-table", "large-table"]
)
def test_a_stdout_that_cannot_encode_the_table_reports_the_render_failure_status(
    asset_tree, tmp_path, encoding, cells
):
    """K4B/C1, pinned at both codecs and both table sizes. A real shell read 1 at 3981efd.

    Everything before the status assertion is the RB-P31 shape and it is load-bearing:
    the run has to have MEASURED, and "it measured" is a claim about BYTES against an
    independent live-stdout run, not about an exit code. The status assertion is then
    the finding — a report that could not be rendered is 5, and it is not the refusal
    status.

    THE SIZE AXIS IS CARRIED OVER RATHER THAN ASSUMED AWAY. RB-P31's defect had two
    numbers on either side of fd 1's `BufferedWriter`, so a fix fitted to one cell fixed
    one cell. This class has one number at both sizes for a mechanical reason worth
    writing down — the encode fails BEFORE any byte reaches the buffer, so there is
    nothing left for the finalization flush to re-fail on and no 120 half — but "we
    reasoned it away" is what RB-P31 was filed for, so both sizes are measured.

    THE STDERR ASSERTION IS ABOUT LEGIBILITY, AND K4B GOT THAT WRONG FIRST TIME. The
    report explaining a codec failure is written to a stream wrapped in the codec that
    just failed, so the obvious claim is that an em dash in it would turn a reported 5
    into an unreported traceback. Measured: it would not. CPython gives `sys.stderr` the
    `backslashreplace` handler and keeps it there even under
    `PYTHONIOENCODING=ascii:strict`, so a non-ASCII character is escaped rather than
    raised — and `backslashreplace` output is itself ASCII, which is why asserting
    "the bytes are ASCII" pinned NOTHING (the mutation that put an em dash back survived
    it). What it costs is the sentence, delivered as `COMPLETE \\u2014 the` in the one
    report whose job is to say where the measurement went. So the delivered text is
    compared against the literal, and that is the assertion that bites.
    """
    rig = _wide_guard_rig(asset_tree, tmp_path, cells)
    live_rows, live_summary = tmp_path / "live-e.jsonl", tmp_path / "live-e.json"
    live_status, out, _ = _shell_status(
        _cli(rig, "--json", str(live_rows), "--summary", str(live_summary)),
        tmp_path,
        f"c1-live-{cells}",
    )
    assert live_status == criticreplay.GUARD_VIOLATION_EXIT  # what the run EARNS
    assert "GUARD VIOLATIONS" in out

    dark_rows, dark_summary = tmp_path / "dark-e.jsonl", tmp_path / "dark-e.json"
    status, stdout_bytes, stderr_bytes = _encoding_stdout_status(
        _cli(rig, "--json", str(dark_rows), "--summary", str(dark_summary)),
        tmp_path,
        f"{encoding}-{cells}",
        encoding,
    )
    assert dark_rows.read_bytes() == live_rows.read_bytes()  # it MEASURED
    assert dark_summary.read_bytes() == live_summary.read_bytes()
    assert stdout_bytes == b""  # and the table is nowhere, which is what 5 says
    assert status == criticreplay.RENDER_FAILURE_EXIT, stderr_bytes
    assert status != _C1_PREFIX_STATUS  # what 3981efd read here
    assert status != criticreplay.REFUSAL_EXIT  # the RB-P24 rule, in its own words

    stderr_bytes.decode("ascii")  # nothing here needed a codec the caller did not have
    err = stderr_bytes.decode()
    assert b"Traceback" not in stderr_bytes, err  # reported, not raised
    assert "could not be rendered" in err
    assert "codec can't encode" in err  # and it names the real reason
    # The delivered sentence against the literal, which is what `backslashreplace` would
    # break and what an ASCII-bytes check would not: `COMPLETE:` becomes `COMPLETE —`
    # the moment one em dash goes back into this message.
    assert "The measurement is COMPLETE: the JSONL rows" in err
    assert "\\u" not in err.split("The measurement is COMPLETE")[1], err
    # K4B/M4. The `5` line's byte-identity promise is prose that no node held, and it is
    # the sentence a reader acts on. Asserted HERE, beside the two byte comparisons that
    # make it true, so the claim and its evidence go red together.
    assert "same bytes a run with a live stdout would have left" in err


@pytest.mark.parametrize("encoding", ["latin-1", "ascii"])
def test_the_hatch_does_not_suppress_a_render_failure_from_a_codec(
    asset_tree, tmp_path, encoding
):
    """K4B/I3, the codec half: `--violations-exit-zero` is an opt-out from 3 ALONE.

    The epilog has said that about 5 since RB-P31 and nothing measured it: K4 moved the
    hatch below the render-failure assignment and the suite scored 748/748 while the
    field measured 0 on a run whose report went nowhere — a clean-looking status for a
    run nobody could read. The hatch's own defence is that it is narrower than `|| true`;
    an opt-out that also swallowed a lost report would not be.
    """
    rig = _wide_guard_rig(asset_tree, tmp_path, _RBP31_SMALL_CELLS)
    status, stdout_bytes, stderr_bytes = _encoding_stdout_status(
        _cli(rig, "--violations-exit-zero"), tmp_path, f"hatch-{encoding}", encoding
    )
    err = stderr_bytes.decode()
    assert status == criticreplay.RENDER_FAILURE_EXIT, err
    assert status != 0  # the number the hatch WOULD have produced
    assert "--violations-exit-zero" in err  # it did suppress the guard status
    assert "could not be rendered" in err  # and it did not suppress this one
    assert stdout_bytes == b""


def test_the_hatch_does_not_suppress_a_render_failure_from_a_dead_fd(asset_tree, tmp_path):
    """K4B/I3, the EBADF half, so the claim is pinned on the class the field can make.

    Same property as its sibling above through a completely different failure — a
    read-only fd rather than a codec — because the hatch is checked against `status`
    before either arm's assignment, and a mutation that reordered them would be caught by
    whichever of these ran. Neither is redundant: the codec cell is the one a caller can
    produce with an environment variable, the fd cell is the one RB-P31 was filed on.
    """
    rig = _wide_guard_rig(asset_tree, tmp_path, _RBP31_SMALL_CELLS)
    status, err, _ = _readonly_stdout_status(
        _cli(rig, "--violations-exit-zero"), tmp_path, "hatch-ebadf"
    )
    assert status == criticreplay.RENDER_FAILURE_EXIT, err
    assert status != 0
    assert "--violations-exit-zero" in err
    assert "could not be rendered" in err


def test_the_render_failure_status_outranks_the_unwritable_summary_status(
    asset_tree, tmp_path
):
    """K4B/I2: 5 outranks 4, measured. Inverting the ladder scored 748/748 (K4).

    The two rungs had never been made to fire on the SAME run, so the order between them
    was a sentence in the epilog and nothing else: swap the last two `if` blocks in
    `main` and the field reports 4 on a run whose report is gone, while the suite stays
    green. This is the cell that decides it — an unwritable `--summary` AND a stdout that
    cannot be written — and the answer is 5 for 4's own reason: 4's promise is "the table
    is still printed", and here it is not.

    Both reasons are still on stderr. Outranking is about the STATUS, never about
    suppressing the other failure's explanation.
    """
    rig = _wide_guard_rig(asset_tree, tmp_path, _RBP31_SMALL_CELLS)
    rows_path = tmp_path / "both-rungs.jsonl"
    status, err, _ = _readonly_stdout_status(
        _cli(rig, "--json", str(rows_path), "--summary", str(_unwritable(tmp_path))),
        tmp_path,
        "outranks-four",
    )
    assert status == criticreplay.RENDER_FAILURE_EXIT, err
    assert status != criticreplay.ARTIFACT_WRITE_EXIT  # the rung below, which fired too
    assert "could not be written" in err  # 4's reason
    assert "could not be rendered" in err  # 5's reason
    assert len(rows_path.read_text().splitlines()) > 0  # and it MEASURED


@pytest.mark.parametrize("encoding", ["latin-1", "ascii"])
def test_the_render_failure_status_outranks_the_unwritable_summary_from_a_codec(
    asset_tree, tmp_path, encoding
):
    """K4B/I2 again through the codec, which is also where the ASCII rule earns its keep.

    Two stderr reports on a stream wrapped in the failing codec, one of them naming an
    unencodable path is not attempted here — what is attempted is that BOTH messages get
    out and the status is the higher rung. If either message had a non-ASCII character in
    it, this cell would report by traceback and the 5 would be lost.
    """
    rig = _wide_guard_rig(asset_tree, tmp_path, _RBP31_SMALL_CELLS)
    status, _, stderr_bytes = _encoding_stdout_status(
        _cli(rig, "--summary", str(_unwritable(tmp_path))),
        tmp_path,
        f"outranks-{encoding}",
        encoding,
    )
    stderr_bytes.decode("ascii")
    err = stderr_bytes.decode()
    assert status == criticreplay.RENDER_FAILURE_EXIT, err
    assert status != criticreplay.ARTIFACT_WRITE_EXIT
    assert "could not be written" in err and "could not be rendered" in err


def test_an_unwritable_summary_does_not_promise_a_table_that_went_nowhere(
    guard_rig, tmp_path
):
    """K4B/M1: the summary-failure sentence was FALSE in the EPIPE cell, and is now not.

    It used to read "The measurement itself is the table, printed after this line unless
    a render failure is reported too". In this cell the reader of stdout is gone, so the
    table is printed NOWHERE, no render failure is reported (a gone reader downgrades,
    it does not raise a report), the status is 4 — and the sentence tells a reader to go
    and read a table that does not exist anywhere.

    The correction is measured here rather than proof-read: this is the exact cell, and
    what it asserts is that the stderr text does not make the promise. `--json` is on so
    the sentence's one surviving promise — the rows are on disk — is checked too.
    """
    rows_path = tmp_path / "epipe-rows.jsonl"
    status, err = _closed_pipe_status(
        _cli(guard_rig, "--json", str(rows_path), "--summary", str(_unwritable(tmp_path))),
        tmp_path,
        "m1-epipe-unwritable",
    )
    assert status == criticreplay.ARTIFACT_WRITE_EXIT, err
    assert "could not be written" in err
    assert "could not be rendered" not in err  # a gone reader raises no render failure
    assert "printed after this line" not in err  # the false promise, gone
    assert "IF STDOUT TOOK IT" in err  # and what replaced it says what it cannot promise
    assert len(rows_path.read_text().splitlines()) > 0


def test_a_non_transcript_json_is_refused_rather_than_delivered_as_a_traceback(
    rig, tmp_path
):
    """K4B/M2: right number, wrong delivery — the shape RB-P32 fixed for `git:HEAD`.

    A `.json` in `--transcripts` that is not a transcript used to raise an uncaught
    `KeyError: 'task'` out of `load_cases`, so the user got a raw traceback and the
    interpreter's 1 where every other world-dependent refusal gets `error: ...` and the
    same 1. `--transcripts` is world, so 1 was never the wrong number; "reported by
    traceback" was the defect, and it is the one RB-P32 named when it moved `git:HEAD`.

    Refusing rather than skipping is the choice being pinned: a silently skipped file is
    a cell missing from a run whose numbers are then quietly about fewer cells.
    """
    transcripts = tmp_path / "mixed"
    transcripts.mkdir()
    for path in Path(rig["transcripts"]).glob("*.json"):
        shutil.copy(path, transcripts / path.name)
    (transcripts / "notes.json").write_text('{"note": "not a transcript"}\n')
    argv = _cli(rig, entry=[sys.executable, "-m", "bantamkit.criticreplay"])
    argv[argv.index(str(rig["transcripts"]))] = str(transcripts)
    status, out, err = _shell_status(argv, tmp_path, "m2-nontranscript")
    assert status == criticreplay.REFUSAL_EXIT, err
    assert "Traceback" not in err, err
    assert "is not a transcript" in err and "notes.json" in err
    assert out == ""


def test_fd_one_on_a_directory_never_reaches_this_module(tmp_path):
    """K4B/M3, and it is NOT this module's defect — written down so it is not re-filed.

    With fd 1 pointing at a directory, CPython cannot build `sys.stdout` at all: it dies
    in `init_sys_streams` with `IsADirectoryError`, prints `Fatal Python error`, and the
    shell reads 1. `main` does not exist yet, no arm here is on that path, and no change
    to the render arm can reach it — the same shape as `--help` with no reader, one layer
    lower.

    It is pinned rather than merely mentioned so the claim cannot go stale: if a future
    CPython (or a future entry point) lets the interpreter start with fd 1 on a
    directory, this goes red and the contract sentence that names it has to be corrected
    with it.
    """
    where = tmp_path / "_fd1-dir"
    where.mkdir()
    err, status_file = where / "stderr.txt", where / "status.txt"
    dir_fd = os.open(where, os.O_RDONLY)
    try:
        proc = subprocess.run(
            ["/bin/sh", "-c", '"$@" 2>"$BK_ERR"; echo "status=$?" >"$BK_STATUS"', "sh",
             sys.executable, "-m", "bantamkit.criticreplay", "--help"],
            stdout=dir_fd,
            env=_child_env(BK_ERR=str(err), BK_STATUS=str(status_file)),
        )
    finally:
        os.close(dir_fd)
    assert proc.returncode == 0
    text = status_file.read_text()
    assert text.startswith("status="), text
    complaint = err.read_text()
    assert "init_sys_streams" in complaint, complaint  # it died BEFORE main existed
    assert int(text.split("=", 1)[1]) == 1
    assert "could not be rendered" not in complaint  # nothing here chose that number


# ---- RB-P32: what a command-line syntax error reports, and what the docs say it reports ----
#
# Filed at docs/eval.md, RB-P32. Two committed sentences describe what `2` covers and
# they do not describe the same set:
#
#   the epilog (`_EXIT_CONTRACT`, user-visible under `--help`):
#     "2  usage error (argparse's number, including this module's own validations)"
#   the module comment (criticreplay.py, the `#   2` block):
#     "argparse also owns this module's own `parser.error` validations"
#
# The measured behaviour matches the comment, not the epilog. Measured 2026-08-13 from a
# real shell (docs/eval-data/2026-08-13-rbp32-argument-validation-matrix.md): eleven
# command lines exit 2 — eight argparse's own, three from this module's SINGLE
# `parser.error` call site — and twelve exit 1 through `main`'s `except BantamError`,
# four of which are pure typos with nothing on disk consulted.
#
# WHICH NUMBER IS RIGHT WAS NOT PINNED WHEN THESE NODES WERE WRITTEN, deliberately: the
# spec above was authored before the decision, and pinning a number then would have been a
# decision smuggled in as a test. RB-P32 IS NOW CLOSED and the decision is USAGE_EXIT for
# every argument-SHAPE error — an argv malformed on its face can never work anywhere, so
# nothing ran and nothing was written, while a 1 also means "a measurement died halfway
# and its artifacts are partial", which is the opposite instruction to a CI job. The
# argument is in the `#   2` block of criticreplay.py; the four cases that moved from 1 to
# 2 are named there and measured either side of the change in
# docs/eval-data/2026-08-13-rbp32-argument-validation-matrix{,-after}.md.
#
# So these two nodes stop being an executable spec and become regression guards, and the
# first one now pins the number as well as the consistency. THE CASE LIST MAY GROW AND MAY
# NOT SHRINK: it is keyed by `_RBP32_PREFIX_STATUSES`, the pre-fix record, and dropping a
# case from it would turn this node green by deleting the evidence rather than by fixing
# anything. `git:` shape case 8 below is a case the pre-fix record did not have — the same
# uncaught-`ValueError` defect as `git:HEAD` one segment further in — and it is added, not
# swapped in.

_RBP32_PREFIX_STATUSES = {
    "--replays 0": 2,
    "--identity-replays 0": 2,
    "--guard nope": 2,
    "--rubric SPEC (no LABEL=)": 1,
    "--rubric =SPEC (empty label)": 1,
    "--rubric LABEL= (empty spec)": 1,
    "--rubric a=git:HEAD (too few segments)": 1,
    # AMENDED 2026-08-13 (K4B/C2). Measured at 3981efd, not at 5538624 — the case is
    # K4's and it reads the same 1 on both trees, because the rule it trips
    # (`guarded_family`'s duplicate-label check) did not move in RB-P32. It is added
    # with its own provenance rather than folded into the sentence above, because a
    # record whose dates drift is a record nobody can re-run.
    "--rubric a=X --rubric a=Y (labels collide)": 1,
}
"""What a real shell read at 5538624, measured 2026-08-13. Seven pure command-line typos.

Every one of them is malformed on its face: no file is opened, no manifest is read, no
request is made, and nothing is written. Three report 2 and four report 1, and the line
between them is exactly which function the author reached for — `parser.error` above
`main`'s `try`, `raise PerturbationError` inside it.

The `git:HEAD` case does not even reach `main`'s handler: `spec.split(":", 2)` unpacks
into three names, so it raises an uncaught `ValueError` and the 1 is the interpreter's,
printed as a traceback rather than as `error: ...`.

AMENDED 2026-08-13 by K4B with an eighth entry measured at 3981efd (K4's C2): two
`--rubric` values sharing a LABEL. It is a shape error by RB-P32's own definition — the
labels are the text left of the first `=` in the typed strings and collide on every
machine — and it reported 1, from inside `main`'s `try`, on an argv the world had
supplied everything for. Its own before/after is
docs/eval-data/2026-08-13-k4b-c2-duplicate-rubric-label.md.
"""

_RBP32_FIELD_CASE_FLOOR = 9
"""How many argument-shape command lines the node below must MEASURE, and why it is here.

K4B/I5. The anti-shrink guard was keyed on `_RBP32_PREFIX_STATUSES`, the very record it
protects: it asked whether every case in the record was measured, so DELETING a case
from the record and from the node's `cases` together left it green and deleted the
evidence instead of fixing anything (K4 demonstrated it at 748/748). A guard needs an
anchor OUTSIDE the thing it guards, so this is one — a count that neither the record nor
the case list can move.

It is a floor, not an equality: the case list may grow, and it has, twice (`a=git:` in
K3, the label collision in K4B). Raising it is an ordinary edit; LOWERING it is a claim
that a measured field case stopped being worth measuring, and it belongs in a commit
message where someone has to read it. What it does not stop is a three-place mutation
that edits this number too — that is stated rather than papered over, and the second,
independent anchor is
`test_every_shape_rule_flag_is_the_usage_status_in_the_field`, which derives its cases
from the CODE and cannot be silenced by editing any list at all.
"""

def _shape_error_argv(tmp_path: Path, *flags: str) -> list[str]:
    """A command line that is complete except for the shape error in `flags`."""
    return [
        sys.executable, "-m", "bantamkit.criticreplay",
        "--base-url", "http://x", "--model", "m", "--transcripts", str(tmp_path),
        *flags,
    ]


def test_every_argument_shape_error_reports_the_same_number(tmp_path):
    """One number for every argument-shape error, and it is the usage number (RB-P32).

    "Argument shape" is meant narrowly and every case here satisfies it: the string the
    user typed is malformed on its face, no path is resolved, no asset is read, no
    request leaves the process and no artifact exists afterwards. At 5538624 a shell
    read 2 three times and 1 four times, and that 1 is the same number a run that died
    on request 40 of 80 reports with 39 rows on disk — one number for two situations a
    CI job has to answer in opposite ways.

    Now it pins the number too, because RB-P32 is closed: `USAGE_EXIT`, argued in the
    `#   2` block of criticreplay.py. Read from a real shell's `$?`, never from a return
    value, and the suite is not the evidence for the closure — the field matrix is.
    """
    rubric = str(ASSETS / "rubrics" / "task-completion.yaml")
    cases = {
        "--replays 0": _shape_error_argv(tmp_path, "--rubric", f"a={rubric}", "--replays", "0"),
        "--identity-replays 0": _shape_error_argv(
            tmp_path, "--rubric", f"a={rubric}", "--identity-replays", "0"
        ),
        "--guard nope": _shape_error_argv(
            tmp_path, "--rubric", f"a={rubric}", "--guard", "nope"
        ),
        "--rubric SPEC (no LABEL=)": _shape_error_argv(tmp_path, "--rubric", rubric),
        "--rubric =SPEC (empty label)": _shape_error_argv(tmp_path, "--rubric", f"={rubric}"),
        "--rubric LABEL= (empty spec)": _shape_error_argv(tmp_path, "--rubric", "a="),
        "--rubric a=git:HEAD (too few segments)": _shape_error_argv(
            tmp_path, "--rubric", "a=git:HEAD"
        ),
        # Grown, not swapped: the same defect as the case above, one segment further in.
        "--rubric a=git: (empty ref and path)": _shape_error_argv(
            tmp_path, "--rubric", "a=git:"
        ),
        # K4B/C2. Grown again, and this one was a defect rather than a gap: it is
        # decidable from the typed strings alone and was refused from INSIDE the run.
        "--rubric a=X --rubric a=Y (labels collide)": _shape_error_argv(
            tmp_path, "--rubric", f"a={rubric}", "--rubric", f"a={rubric}"
        ),
    }
    measured = {}
    for index, (label, argv) in enumerate(cases.items()):
        status, out, err = _shell_status(argv, tmp_path, f"shape-{index}")
        measured[label] = status
        assert out == "", f"{label} printed to stdout on a run that never measured: {err}"
        assert "Traceback" not in err, f"{label} reported by traceback, not by status: {err}"
    missing = set(_RBP32_PREFIX_STATUSES) - set(measured)
    assert not missing, (
        f"cases dropped from the pre-fix record: {sorted(missing)}. The list may grow; a "
        "case leaves it only with a measured reason, and 'it made this node pass' is not one"
    )
    # K4B/I5: the anchor that is not the record. See `_RBP32_FIELD_CASE_FLOOR`.
    assert len(measured) >= _RBP32_FIELD_CASE_FLOOR, (
        f"{len(measured)} shape cases measured, and {_RBP32_FIELD_CASE_FLOOR} have been "
        "measured in the field. The guard above cannot see a case deleted from BOTH the "
        "record and this list; this can."
    )
    assert len(set(measured.values())) == 1, (
        f"argument-shape errors report {sorted(set(measured.values()))}, not one number: "
        f"{measured} (measured pre-fix: {_RBP32_PREFIX_STATUSES})"
    )
    assert set(measured.values()) == {criticreplay.USAGE_EXIT}, (
        f"{measured}: RB-P32 chose the usage status for every argument-shape error, "
        "because a 1 also means 'a measurement was attempted and its artifacts are "
        "partial' and a malformed command line can leave no artifact at all"
    )


# ---- K4B/I7: the prose about `2` is checked against the CODE, not against more prose ----
#
# WHAT WAS HERE BEFORE AND WHY IT IS GONE. RB-P32 shipped
# `test_the_epilog_and_the_module_comment_agree_about_what_the_usage_status_covers`: two
# literal substring tests joined by `and` — "the epilog claims ALL of this module's
# validations" and "the comment says `parser.error`" — asserting that both were never
# true at once. It bit on the real regression K3 was fixing, and K4 then silenced it in
# one edit: rename BOTH `parser.error` mentions inside the `#   2` block and the
# conjunction is false whatever the epilog says, after which the old false epilog sentence
# can be restored VERBATIM and the tree is back to the exact prose RB-P32 was filed
# against, with a green suite. A check that a rename can silence is checking the spelling
# of the code, not what the code does.
#
# WHAT REPLACED IT, and it is a rebuild rather than a patch. The set of this module's own
# shape rules is DERIVED FROM THE CODE — every `parser.error` reachable above `main`'s
# `try`, and the `--flag` names the messages it is handed can carry — and both committed
# rosters must be exactly that set. Then a rename changes nothing (the derivation walks
# the AST for a call to `.error`, not for the text "parser.error"), deleting a roster is
# red (the node requires one in each place), and adding a shape rule without saying so is
# red. Its companion below closes the loop the other way, in the field: every flag on the
# roster measures 2 from a real shell, and every module rule that is NOT on it measures 1
# — which is what pins the RB-P32 line on its `1` side, where nothing had ever asserted
# anything (K4B/I4).

_SHAPE_ROSTER = "shape rules (exact set): "
"""The marker both committed rosters carry, so a machine can find the claim in the prose.

Deliberately one literal in both places rather than a clever parse of English: the two
sentences it lives in are user-visible contract text, and the alternative — deriving the
set from free prose — is what produced a check that could not tell "these flags report 2"
from "this flag is an example of a 1", both of which the `#   2` block says.
"""

_FLAG = re.compile(r"--[a-z][a-z0-9-]*")


def _returned_strings(function: ast.FunctionDef) -> list[str]:
    """Every string constant reachable from a `return` in `function`.

    `return`s only, never the whole body: a docstring that MENTIONS a flag is prose, and
    a derivation that read it would pick up `--transcripts` from a sentence explaining
    why `--transcripts` is not a shape rule.
    """
    out: list[str] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Return) and node.value is not None:
            out += [
                sub.value
                for sub in ast.walk(node.value)
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
            ]
    return out


def _shape_rule_flags_from_the_code() -> tuple[set[str], int]:
    """The flags this module's own shape rules name, read off the AST. Also the site count.

    "Reachable above `main`'s `try`" is taken literally: the statements of `main` up to
    the `try`, which is the structural fact RB-P32 rests on — a rule up there has resolved
    no path and opened no file, so it is entitled to say "this argv can never work". A
    `parser.error` handed a name is followed one hop to the function that supplied it, so
    the rubric rules (whose messages are built in `rubric_arg_shape_problem` and
    `rubric_label_collision_problem`) count as much as the inline one.
    """
    tree = ast.parse((SRC / "criticreplay.py").read_text())
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    above: list[ast.stmt] = []
    for statement in functions["main"].body:
        if isinstance(statement, ast.Try):
            break
        above.append(statement)
    else:  # pragma: no cover - a `main` with no `try` is a different module
        raise AssertionError("main() no longer has a `try`, so 'above it' means nothing")

    supplier: dict[str, str] = {}
    for statement in above:
        for node in ast.walk(statement):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        supplier[target.id] = node.value.func.id

    messages: list[str] = []
    sites = 0
    for statement in above:
        for node in ast.walk(statement):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "error"
                and node.args
            ):
                continue
            sites += 1
            argument = node.args[0]
            if isinstance(argument, ast.Name) and argument.id in supplier:
                messages += _returned_strings(functions[supplier[argument.id]])
            else:
                messages += [
                    sub.value
                    for sub in ast.walk(argument)
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                ]
    return {flag for message in messages for flag in _FLAG.findall(message)}, sites


def _roster(text: str) -> set[str] | None:
    for line in text.splitlines():
        if _SHAPE_ROSTER in line:
            return set(_FLAG.findall(line.split(_SHAPE_ROSTER, 1)[1]))
    return None


def test_the_usage_status_names_exactly_the_shape_rules_the_code_has():
    """RB-P32's second half, rebuilt so that renaming things cannot answer it (K4B/I7).

    Three claims, and each is about the CODE rather than about the other sentence:

    1. the derivation finds something — a `main` with no `parser.error` above its `try`
       would make the whole RB-P32 argument vacuous, so a floor is asserted on both the
       call sites and the flags;
    2. the epilog's `2` block carries a roster and it is exactly the derived set;
    3. the module comment's `#   2` block carries a roster and it is exactly the derived
       set.

    Every mutation K4 used on the node this replaces is now red: renaming `parser.error`
    in either block changes nothing here, restoring the old unqualified epilog sentence
    deletes the roster (2 fails), and adding a shape rule for a new flag without naming
    it fails 2 and 3 together.
    """
    derived, sites = _shape_rule_flags_from_the_code()
    assert sites >= 2, f"only {sites} parser.error call sites above main's try"
    assert len(derived) >= 2, f"the derivation found {derived}, which cannot be right"
    assert "--rubric" in derived  # the flag RB-P32 and K4B both moved cases for

    epilog_block = re.search(
        rf"^  {criticreplay.USAGE_EXIT}  (.*?)(?=^  \d  |\Z)",
        criticreplay._EXIT_CONTRACT,
        re.S | re.M,
    )
    assert epilog_block, "the epilog no longer has a line for the usage status"
    comment_block = re.search(
        rf"^#   {criticreplay.USAGE_EXIT}  (.*?)(?=^#   \d  )",
        (SRC / "criticreplay.py").read_text(),
        re.S | re.M,
    )
    assert comment_block, "the module comment no longer has a block for the usage status"

    for where, block in (("epilog", epilog_block), ("module comment", comment_block)):
        roster = _roster(block.group(1))
        assert roster is not None, (
            f"the {where}'s {criticreplay.USAGE_EXIT} block no longer carries a "
            f"'{_SHAPE_ROSTER}' line. That line IS the claim; prose around it is not a "
            "substitute, because prose in this block also names flags that report "
            f"{criticreplay.REFUSAL_EXIT}."
        )
        assert roster == derived, (
            f"the {where} says this module's shape rules are {sorted(roster)}, and the "
            f"code's own `parser.error` calls above main's try name {sorted(derived)}. "
            "Fix the sentence and the behaviour together — that is the whole of RB-P32."
        )


def _world_rule_field_cases(tmp_path: Path, rubric: str) -> dict[str, list[str]]:
    """Module rules that are NOT shape rules: they consult the world, so they are a 1.

    Each one is well formed on its face and names something this machine did not supply,
    which is the other side of RB-P32's line. `--rubric a=<a path that is not there>` is
    the load-bearing member: `--rubric` IS on the shape roster, so a reader who took the
    roster to mean "everything about --rubric is a 2" would be wrong, and until K4B
    nothing anywhere asserted that this case is a 1 (K4's I4 — moving it to 2 scored
    748/748).
    """
    empty = tmp_path / "empty-transcripts"
    empty.mkdir(exist_ok=True)
    base = [
        sys.executable, "-m", "bantamkit.criticreplay",
        "--base-url", "http://x", "--model", "m",
    ]
    return {
        "--rubric a=<a path that is not there>": [
            *base, "--transcripts", str(empty), "--rubric", f"a={tmp_path / 'gone.yaml'}",
        ],
        "--transcripts <a directory with no transcripts>": [
            *base, "--transcripts", str(empty), "--rubric", f"a={rubric}",
        ],
        "--manifest <a path that is not there>": [
            *base, "--transcripts", str(empty), "--rubric", f"a={rubric}",
            "--manifest", str(tmp_path / "gone-manifest.yaml"),
        ],
    }


def test_every_shape_rule_flag_is_the_usage_status_in_the_field(tmp_path):
    """The companion to the roster check, and the half a shell reads (K4B/I7, I4).

    The node above proves the two committed rosters describe the code. This one proves
    the code describes the machine, from a real `$?` with no pytest marker in the
    environment: every flag the roster names has a shape error that reports
    `USAGE_EXIT`, and every module rule the roster does NOT name reports `REFUSAL_EXIT`.

    THE CASE DICT IS KEYED ON THE DERIVED SET, not written beside it. Add a shape rule
    for a new flag and this node fails until someone measures it — which is K3's own
    declared gap ("nothing enforces that a NEW flag's shape rule goes above the `try`")
    closed from the other end: it cannot silently be added and left unmeasured either.
    """
    rubric = str(ASSETS / "rubrics" / "task-completion.yaml")
    derived, _ = _shape_rule_flags_from_the_code()
    shape_cases = {
        "--replays": _shape_error_argv(tmp_path, "--rubric", f"a={rubric}", "--replays", "0"),
        "--identity-replays": _shape_error_argv(
            tmp_path, "--rubric", f"a={rubric}", "--identity-replays", "0"
        ),
        "--rubric": _shape_error_argv(tmp_path, "--rubric", "a="),
    }
    assert set(shape_cases) == derived, (
        f"the code's shape rules name {sorted(derived)} and this node measures "
        f"{sorted(shape_cases)}. A shape rule with no field case is a contract sentence "
        "with nothing behind it."
    )
    for index, (flag, argv) in enumerate(sorted(shape_cases.items())):
        status, out, err = _shell_status(argv, tmp_path, f"roster-{index}")
        assert status == criticreplay.USAGE_EXIT, f"{flag}: {status}, {err}"
        assert out == "", f"{flag} wrote to stdout on a run that never measured"
        assert "Traceback" not in err, f"{flag} reported by traceback: {err}"

    world = sorted(_world_rule_field_cases(tmp_path, rubric).items())
    for index, (label, argv) in enumerate(world):
        status, out, err = _shell_status(argv, tmp_path, f"world-{index}")
        assert status == criticreplay.REFUSAL_EXIT, (
            f"{label} reports {status}. It is well formed on its face and names something "
            "this machine did not supply, so the same argv succeeds once the world "
            f"changes — that is {criticreplay.REFUSAL_EXIT}, and moving it to "
            f"{criticreplay.USAGE_EXIT} would tell a CI job to edit a command line that "
            "is not wrong."
        )
        assert out == ""
        assert "Traceback" not in err, f"{label} reported by traceback: {err}"
