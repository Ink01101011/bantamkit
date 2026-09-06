"""The repo map: what the scanner sees, what it refuses to hide, and what the port must copy.

Every node here is a rule `runtime-ts` has to reproduce. The two that are NOT about output
are `test_no_float_summation_or_rounding_in_the_source` and
`test_the_module_renders_no_raw_float`, and they exist because the port contract's hardest
half is arithmetic that looks fine until two runtimes disagree in the sixteenth digit.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from bantamkit.repomap import (
    DEFAULT_BUDGET,
    ITERATIONS,
    MAX_DEFINITIONS_PER_FILE,
    MAX_FILE_BYTES,
    OMIT_BUDGET,
    OMIT_NO_DEFINITIONS,
    OMIT_PER_FILE_CAP,
    OMIT_SIZE_CAP,
    OMIT_UNKNOWN_LANGUAGE,
    OMIT_UNREACHABLE,
    OMIT_UNREADABLE,
    SCORE_SCALE,
    Definition,
    build_graph,
    language_of,
    pagerank,
    reference_names,
    repo_map,
    scan_definitions,
    select_definitions,
    strip_noncode,
    walk_sources,
)

REPO = Path(__file__).resolve().parents[2]


def names(defs) -> list[str]:
    return [d.name for d in defs]


def omissions(result) -> dict[str, int]:
    return {o.subject: o.count for o in result.omissions}


def facts(result, subject: str) -> dict[str, int]:
    for o in result.omissions:
        if o.subject == subject:
            return dict(o.facts)
    raise AssertionError(f"no {subject} omission in {omissions(result)}")


# --------------------------------------------------------------------------------------
# language_of


@pytest.mark.parametrize(
    "path,expected",
    [
        ("a.py", "python"),
        ("a.pyi", "python"),
        ("a.ts", "ecma"),
        ("a.mjs", "ecma"),
        ("a.cjs", "ecma"),
        ("a.tsx", "ecma"),
        ("A.PY", "python"),
        ("a.md", None),
        ("a.json", None),
        ("Makefile", None),
        (".gitignore", None),
        # The dot belongs to the DIRECTORY, so the file has no suffix at all.
        ("dir.py/README", None),
        ("dir.py\\README", None),
    ],
)
def test_language_of_dispatches_on_suffix_and_refuses_the_rest(path, expected):
    assert language_of(path) == expected


# --------------------------------------------------------------------------------------
# strip_noncode


def test_python_docstring_is_stripped_and_line_numbers_survive():
    source = '"""\ndef not_a_def():\n    pass\n"""\ndef real():\n    pass\n'
    stripped = strip_noncode(source, "python")
    assert len(stripped) == len(source.split("\n"))
    assert "not_a_def" not in "".join(stripped)
    found = scan_definitions(source, "python", "a.py")
    assert names(found) == ["real"]
    assert found[0].line == 5


def test_a_one_line_python_docstring_does_not_swallow_the_rest_of_the_file():
    source = 'x = 1\n"""one liner"""\ndef after():\n    pass\n'
    assert names(scan_definitions(source, "python", "a.py")) == ["x", "after"]


def test_the_opening_python_delimiter_is_the_only_one_that_closes_it():
    source = "'''\n\"\"\"\ndef hidden():\n    pass\n'''\ndef seen():\n    pass\n"
    assert names(scan_definitions(source, "python", "a.py")) == ["seen"]


def test_a_python_hash_comment_hides_a_definition_shaped_line():
    source = "# def commented():\nCONST = 1\n"
    assert names(scan_definitions(source, "python", "a.py")) == ["CONST"]


def test_an_ecma_block_comment_is_stripped_across_lines():
    source = "/*\nfunction hidden() {}\n*/\nfunction seen() {}\n"
    found = scan_definitions(source, "ecma", "a.ts")
    assert names(found) == ["seen"]
    assert found[0].line == 4


def test_an_ecma_line_comment_hides_a_definition_shaped_line():
    assert names(scan_definitions("// function hidden() {}\nclass Seen {}\n", "ecma", "a.ts")) == [
        "Seen"
    ]


def test_carriage_returns_do_not_change_the_scan():
    unix = "def a():\n    pass\ndef b():\n    pass\n"
    assert scan_definitions(unix.replace("\n", "\r\n"), "python", "a.py") == scan_definitions(
        unix, "python", "a.py"
    )
    assert scan_definitions(unix.replace("\n", "\r"), "python", "a.py") == scan_definitions(
        unix, "python", "a.py"
    )


# --------------------------------------------------------------------------------------
# scan_definitions


def test_python_definitions_are_taken_at_any_indentation():
    source = (
        "class Outer:\n    def method(self):\n        pass\n"
        "\n    async def coro(self):\n        pass\n"
    )
    found = scan_definitions(source, "python", "a.py")
    assert [(d.kind, d.name, d.line) for d in found] == [
        ("class", "Outer", 1),
        ("def", "method", 2),
        ("def", "coro", 5),
    ]


def test_a_python_constant_counts_only_at_column_zero():
    source = "TOP = 1\nANNOTATED: int = 2\nclass C:\n    inner = 3\n"
    assert names(scan_definitions(source, "python", "a.py")) == ["TOP", "ANNOTATED", "C"]


def test_a_python_comparison_is_not_a_definition():
    assert scan_definitions("value == other\n", "python", "a.py") == ()


@pytest.mark.parametrize(
    "line,expected",
    [
        ("function plain() {}", ("function", "plain")),
        ("export function exported() {}", ("function", "exported")),
        ("export default async function both() {}", ("function", "both")),
        ("class Shape {}", ("class", "Shape")),
        ("export interface Wire {}", ("interface", "Wire")),
        ("export type Alias = string;", ("type", "Alias")),
        ("const NAME = 1;", ("const", "NAME")),
        ("let mutable = 1;", ("let", "mutable")),
        ("var old = 1;", ("var", "old")),
        ("export enum Colour {}", ("enum", "Colour")),
        ("const $dollar = 1;", ("const", "$dollar")),
    ],
)
def test_ecma_top_level_declaration_forms(line, expected):
    found = scan_definitions(line + "\n", "ecma", "a.ts")
    assert [(d.kind, d.name) for d in found] == [expected]


def test_an_indented_ecma_declaration_is_a_local_and_is_not_a_definition():
    source = "function outer() {\n  const local = 1;\n  class Inner {}\n}\n"
    assert names(scan_definitions(source, "ecma", "a.ts")) == ["outer"]


def test_a_non_ascii_identifier_is_invisible_to_the_scanner():
    # Declared, not accidental: `tokens()` is ASCII-only for the same reason, and a port
    # that "fixed" this on one side would diverge on every file that used one.
    assert scan_definitions("def \u00e9t\u00e9():\n    pass\n", "python", "a.py") == ()


# --------------------------------------------------------------------------------------
# reference_names


def test_references_skip_short_names_and_comment_text():
    source = "# unlikelycommentword\nab = cd + longname\n"
    found = reference_names(source, "python")
    assert "longname" in found
    assert "unlikelycommentword" not in found
    assert "ab" not in found and "cd" not in found


# --------------------------------------------------------------------------------------
# build_graph


def defs_of(mapping: dict[str, list[tuple[int, str, str]]]):
    return {
        path: tuple(Definition(path, line, kind, name) for line, kind, name in rows)
        for path, rows in mapping.items()
    }


def test_a_uniquely_defined_name_makes_an_edge_and_a_shared_one_does_not():
    definitions = defs_of(
        {
            "a.py": [(1, "def", "onlyhere")],
            "b.py": [(1, "def", "shared")],
            "c.py": [(1, "def", "shared")],
            "d.py": [],
        }
    )
    references = {
        "a.py": set(),
        "b.py": set(),
        "c.py": set(),
        "d.py": {"onlyhere", "shared"},
    }
    edges = build_graph(definitions, references)
    assert edges == {"d.py": {"a.py": 1}}


def test_a_file_never_makes_an_edge_to_itself():
    definitions = defs_of({"a.py": [(1, "def", "selfname")], "b.py": []})
    references = {"a.py": {"selfname"}, "b.py": set()}
    assert build_graph(definitions, references) == {}


def test_the_weight_counts_distinct_names_not_mentions():
    definitions = defs_of({"a.py": [(1, "def", "alpha"), (2, "def", "beta")], "b.py": []})
    references = {"a.py": set(), "b.py": {"alpha", "beta"}}
    assert build_graph(definitions, references) == {"b.py": {"a.py": 2}}


def test_a_name_referenced_by_more_than_an_eighth_of_the_files_makes_no_edge():
    # Twenty files. `popular` is mentioned by nine of them: 9 > 8 clears the floor and
    # 9 * 8 > 20 * 1 clears the fraction, so it makes no edge. `rarename` is mentioned by
    # one and keeps its edge.
    definitions = defs_of({"a.py": [(1, "const", "popular"), (2, "const", "rarename")]})
    references: dict[str, set[str]] = {"a.py": set()}
    for i in range(20):
        definitions.setdefault(f"f{i}.py", ())
        references[f"f{i}.py"] = {"popular"} if i < 9 else set()
    references["f0.py"] = {"popular", "rarename"}
    assert build_graph(definitions, references) == {"f0.py": {"a.py": 1}}


def test_the_frequency_floor_keeps_a_small_tree_from_rejecting_every_name():
    # Below `REFERENCE_DF_MAX_DEN` files an eighth of the tree is less than one file. The
    # floor is what stops that from emptying the map; without it a three-file project
    # produced no edges at all.
    definitions = defs_of({"core.py": [(1, "class", "Engine")], "caller.py": []})
    references = {"core.py": {"Engine"}, "caller.py": {"Engine"}}
    assert build_graph(definitions, references) == {"caller.py": {"core.py": 1}}


# --------------------------------------------------------------------------------------
# pagerank


def _total(values: list[float]) -> float:
    # Deliberately a loop and not `sum()`: CPython 3.12 compensates float `sum()` and JS
    # does not, so a test that used `sum()` would be checking a number the port cannot
    # produce.
    out = 0.0
    for v in values:
        out += v
    return out


def test_with_no_edges_the_score_is_the_personalisation_vector():
    nodes = ["a.py", "b.py", "c.py"]
    scores = pagerank(nodes, {}, ["b.py"])
    assert scores == [0.0, 1.0, 0.0]


def test_with_no_focus_and_no_edges_the_score_is_uniform():
    nodes = ["a.py", "b.py", "c.py", "d.py"]
    assert pagerank(nodes, {}, []) == [0.25, 0.25, 0.25, 0.25]


def test_mass_is_conserved():
    nodes = ["a.py", "b.py", "c.py", "d.py"]
    edges = {"a.py": {"b.py": 2, "c.py": 1}, "b.py": {"c.py": 1}, "c.py": {"a.py": 3}}
    total = _total(pagerank(nodes, edges, ["a.py"]))
    assert abs(total - 1.0) < 1e-12


def test_the_focus_reaches_what_it_references():
    nodes = ["a.py", "b.py", "c.py"]
    edges = {"a.py": {"b.py": 1}}
    scores = pagerank(nodes, edges, ["a.py"])
    assert scores[1] > 0.0, "b is referenced by the focus"
    assert scores[2] == 0.0, "c is unreachable from the focus"


def test_a_focus_that_is_not_a_node_falls_back_to_uniform():
    nodes = ["a.py", "b.py"]
    assert pagerank(nodes, {}, ["absent.py"]) == [0.5, 0.5]


def test_the_iteration_has_reached_its_fixed_point_by_the_pinned_count():
    # The 60 is a LITERAL on purpose. Comparing `ITERATIONS` against `ITERATIONS + 20`
    # passes for any value of `ITERATIONS`, so it would prove nothing about the pinned
    # one — measured: a mutant setting `ITERATIONS = 3` survived that version of this
    # test. The residual bound is `2 * damping ** iterations`, so 30 is where the
    # docstring's argument says the vector must already be exact.
    nodes = [f"f{i}.py" for i in range(12)]
    edges = {nodes[i]: {nodes[(i + 1) % 12]: 1, nodes[(i + 5) % 12]: 2} for i in range(12)}
    assert ITERATIONS == 30, "the port contract pins this number, not merely its use"
    assert pagerank(nodes, edges, [nodes[0]], iterations=ITERATIONS) == pagerank(
        nodes, edges, [nodes[0]], iterations=60
    )


def test_the_pinned_damping_is_what_orders_a_two_hop_node_against_a_weak_neighbour():
    # A hub the focus leans on (weight 10), a weak direct neighbour (weight 5), and a node
    # reachable only THROUGH the hub. At the pinned 0.20 the weak neighbour outranks the
    # two-hop node; at the canonical 0.85 they swap. Without this the tuned constant was
    # pinned by nothing at all and a mutant restoring 0.85 survived the whole suite.
    nodes = ["a_hub.py", "b_deep.py", "c_weak.py", "f_focus.py"]
    edges = {"f_focus.py": {"a_hub.py": 10, "c_weak.py": 5}, "a_hub.py": {"b_deep.py": 1}}
    scores = pagerank(nodes, edges, ["f_focus.py"])
    assert scores[2] > scores[1], "at DAMPING=0.20 the direct neighbour wins"
    loose = pagerank(nodes, edges, ["f_focus.py"], damping=0.85)
    assert loose[1] > loose[2], "and at 0.85 it does not — the constant is load-bearing"


def test_an_empty_node_list_ranks_nothing():
    assert pagerank([], {}, []) == []


# --------------------------------------------------------------------------------------
# select_definitions


def test_selection_prefers_a_type_then_reach_then_the_earlier_line():
    definitions = (
        Definition("a.py", 1, "const", "EARLY"),
        Definition("a.py", 2, "def", "helper"),
        Definition("a.py", 3, "class", "Subject"),
        Definition("a.py", 4, "def", "popular"),
    )
    references = {"EARLY": 99, "helper": 1, "Subject": 1, "popular": 50}
    chosen = select_definitions(definitions, references, 2)
    assert names(chosen) == ["Subject", "popular"], "the class and the reached callable"
    assert [d.line for d in chosen] == [3, 4], "and rendered in source order"


def test_the_chosen_block_is_rendered_in_source_order_not_choice_order():
    # The choice puts the class first; the render puts line 1 first. A fixture where those
    # two agree cannot tell them apart, and the first one here did not.
    definitions = (
        Definition("a.py", 1, "def", "early_callable"),
        Definition("a.py", 9, "class", "LateType"),
        Definition("a.py", 20, "const", "TAIL"),
    )
    chosen = select_definitions(definitions, {}, 2)
    assert names(chosen) == ["early_callable", "LateType"]
    assert [d.line for d in chosen] == [1, 9]


def test_selection_returns_everything_when_it_fits_or_when_unlimited():
    definitions = (Definition("a.py", 1, "def", "one"), Definition("a.py", 2, "def", "two"))
    assert select_definitions(definitions, {}, 5) == definitions
    assert select_definitions(definitions, {}, 0) == definitions


# --------------------------------------------------------------------------------------
# repo_map over a built tree


def build_tree(root: Path) -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "core.py").write_text(
        '"""Docstring mentioning nothing."""\n\nclass CoreEngine:\n    def churn(self):\n'
        "        return 1\n\n    def _private_helper(self):\n        return 2\n",
        encoding="utf-8",
    )
    (root / "pkg" / "caller.py").write_text(
        "from pkg.core import CoreEngine\n\n\ndef drive():\n"
        "    engine = CoreEngine()\n    return engine.churn()\n",
        encoding="utf-8",
    )
    (root / "pkg" / "stranger.py").write_text(
        "def unrelatedthing():\n    return 0\n", encoding="utf-8"
    )
    (root / "notes.md").write_text("# not source\n", encoding="utf-8")
    (root / "data.json").write_text("{}\n", encoding="utf-8")


def test_the_map_ranks_what_the_focus_reaches_and_names_the_rest(tmp_path):
    build_tree(tmp_path)
    result = repo_map(tmp_path, focus=["pkg/caller.py"])
    assert result.nodes == 3
    assert [e.path for e in result.ranked] == ["pkg/core.py"]
    assert "pkg/caller.py" not in result.text, "the focus file is not spent on itself"
    assert "CoreEngine" in result.text
    counts = omissions(result)
    assert counts[OMIT_UNKNOWN_LANGUAGE] == 2, "notes.md and data.json are named, not dropped"
    assert counts[OMIT_UNREACHABLE] == 1, "stranger.py is unreachable from the focus"


def test_an_empty_focus_ranks_the_whole_tree(tmp_path):
    build_tree(tmp_path)
    result = repo_map(tmp_path, focus=[])
    assert {e.path for e in result.ranked} == {
        "pkg/core.py",
        "pkg/caller.py",
        "pkg/stranger.py",
    }
    assert result.focus == ()


def test_a_file_that_is_not_utf8_is_counted_and_does_not_raise(tmp_path):
    (tmp_path / "good.py").write_text("def fine():\n    pass\n", encoding="utf-8")
    (tmp_path / "bad.py").write_bytes(b"def broken():\n    x = '\xff\xfe'\n")
    result = repo_map(tmp_path)
    counts = omissions(result)
    assert counts[OMIT_UNREADABLE] == 1
    assert "bad.py" not in result.text
    assert result.nodes == 1


def test_a_file_over_the_size_cap_is_counted_and_not_scanned(tmp_path):
    (tmp_path / "small.py").write_text("def fine():\n    pass\n", encoding="utf-8")
    (tmp_path / "huge.py").write_text(
        "x = 1\n" + "# pad\n" * (MAX_FILE_BYTES // 6), encoding="utf-8"
    )
    result = repo_map(tmp_path)
    counts = omissions(result)
    assert counts[OMIT_SIZE_CAP] == 1
    assert facts(result, OMIT_SIZE_CAP)["cap_bytes"] == MAX_FILE_BYTES
    assert result.nodes == 1


def test_a_source_file_holding_no_definition_is_counted(tmp_path):
    (tmp_path / "a.py").write_text("def real():\n    pass\n", encoding="utf-8")
    (tmp_path / "empty.py").write_text("# nothing but a comment\n", encoding="utf-8")
    assert omissions(repo_map(tmp_path))[OMIT_NO_DEFINITIONS] == 1


def test_the_per_file_cap_is_counted_with_the_limit_that_caused_it(tmp_path):
    (tmp_path / "wide.py").write_text(
        "".join(f"def name{i}():\n    pass\n" for i in range(MAX_DEFINITIONS_PER_FILE + 3)),
        encoding="utf-8",
    )
    result = repo_map(tmp_path)
    assert omissions(result)[OMIT_PER_FILE_CAP] == 3
    assert facts(result, OMIT_PER_FILE_CAP)["per_file"] == MAX_DEFINITIONS_PER_FILE


def test_a_budget_too_small_reports_what_it_could_not_carry(tmp_path):
    build_tree(tmp_path)
    result = repo_map(tmp_path, budget=0)
    assert result.listing_bytes == 0
    assert result.files_rendered == 0
    detail = facts(result, OMIT_BUDGET)
    assert detail["budget_bytes"] == 0
    assert omissions(result)[OMIT_BUDGET] == len(result.ranked)
    assert result.text.startswith("# omitted:")


def test_the_listing_never_exceeds_the_budget(tmp_path):
    build_tree(tmp_path)
    # EVERY budget, not every seventh: an off-by-one in the fill only shows at a byte
    # where a line lands exactly on the boundary, and a step of 7 stepped over them. A
    # mutant loosening the comparison to `> budget + 1` survived the sparser sweep.
    for budget in range(0, 300):
        result = repo_map(tmp_path, budget=budget)
        assert result.listing_bytes <= budget, budget


def test_the_omission_footer_is_not_charged_to_the_budget(tmp_path):
    # The rule this pins: a budget that could suppress the disclosure of what it dropped
    # would be the defect the footer exists to close.
    build_tree(tmp_path)
    result = repo_map(tmp_path, budget=40)
    assert result.listing_bytes <= 40
    assert len(result.text.encode("utf-8")) > 40
    assert result.text.split("\n")[-1].startswith("# omitted:")


def test_the_footer_names_every_subject_in_the_pinned_order(tmp_path):
    build_tree(tmp_path)
    (tmp_path / "empty.py").write_text("# nothing\n", encoding="utf-8")
    result = repo_map(tmp_path, focus=["pkg/caller.py"], budget=30)
    footer = result.text.split("\n")[-1]
    subjects = [field.split("=")[0] for field in footer[len("# omitted: ") :].split(" ")]
    assert subjects == sorted(
        subjects,
        key=[
            OMIT_UNKNOWN_LANGUAGE,
            OMIT_UNREADABLE,
            OMIT_SIZE_CAP,
            OMIT_NO_DEFINITIONS,
            OMIT_UNREACHABLE,
            OMIT_PER_FILE_CAP,
            OMIT_BUDGET,
        ].index,
    )


def test_a_clean_tree_has_no_footer_at_all(tmp_path):
    (tmp_path / "a.py").write_text("def alpha():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def beta():\n    return alpha\n", encoding="utf-8")
    result = repo_map(tmp_path, budget=DEFAULT_BUDGET)
    assert "# omitted" not in result.text
    assert result.omissions == ()


# --------------------------------------------------------------------------------------
# determinism — the port contract


def test_a_tie_in_the_rank_is_broken_by_path(tmp_path):
    # Three files identical but for their names, all referenced once by the focus: the
    # scores are equal to the last bit, so ONLY the by-path tie-break decides the order.
    (tmp_path / "zulu.py").write_text("def zuluthing():\n    pass\n", encoding="utf-8")
    (tmp_path / "alpha.py").write_text("def alphathing():\n    pass\n", encoding="utf-8")
    (tmp_path / "mike.py").write_text("def mikething():\n    pass\n", encoding="utf-8")
    (tmp_path / "focus.py").write_text(
        "def go():\n    return zuluthing, alphathing, mikething\n", encoding="utf-8"
    )
    result = repo_map(tmp_path, focus=["focus.py"])
    units = {e.rank_units for e in result.ranked}
    assert len(units) == 1, "the three scores must actually tie for this to test anything"
    assert [e.path for e in result.ranked] == ["alpha.py", "mike.py", "zulu.py"]


def test_the_rendered_map_carries_no_raw_float(tmp_path):
    # Trap (8): `repr(1.0)` is '1.0' in CPython and '1' in JS, `1e-07` vs `1e-7`. A score
    # in the text would make the two runtimes disagree byte for byte on a correct answer.
    build_tree(tmp_path)
    result = repo_map(tmp_path, focus=["pkg/caller.py"])
    for line in result.text.split("\n"):
        assert "." not in line.replace(".py", "").replace(".md", "").replace(".json", ""), line
    assert all(isinstance(e.rank_units, int) for e in result.ranked)


def test_rank_units_is_a_floor_of_the_scaled_score():
    # Trap (9): CPython's `round` is banker's and JS's is half-up, so the quantisation has
    # to be a floor. A three-file fixture could not tell the two apart — every score there
    # happened to round down — so this runs over the repository's own package, where
    # hundreds of scores make the distinction certain, and ASSERTS that it is certain.
    result = repo_map(REPO / "runtime-py" / "src" / "bantamkit", focus=["memory/dream.py"])
    scaled = [entry.score * SCORE_SCALE for entry in result.ranked]
    assert any(math.floor(v) != round(v) for v in scaled), (
        "this fixture cannot distinguish floor from round and so cannot test it"
    )
    for entry, value in zip(result.ranked, scaled, strict=True):
        assert entry.rank_units == math.floor(value)


def test_no_float_summation_or_rounding_in_the_source():
    # A source guard in the shape `test_layers.py::test_core_purity` already uses, and it
    # is a guard rather than a proof: `sum()` over floats is COMPENSATED in CPython 3.12
    # and is not in JS (`sum([0.1, 0.2, 0.3, 1e16, -1e16])` is 0.6 here and 0.0 from a
    # loop), and `round()` is banker's here and half-up there. Neither difference shows up
    # in any output this suite can compare, so nothing but reading the source catches a
    # reintroduction.
    source = (REPO / "runtime-py" / "src" / "bantamkit" / "repomap.py").read_text(encoding="utf-8")
    start = source.index("def pagerank(")
    loop = source[start : source.index("\ndef ", start + 1)]
    body = loop.split('"""')[2]
    body = "\n".join(
        line for line in body.split("\n") if not line.lstrip().startswith(("#", "*", "-"))
    )
    assert "sum(" not in body, "float accumulation in pagerank must be a written-out loop"
    assert "round(" not in body, "round() disagrees between CPython and JS"
    assert "fsum" not in body, "math.fsum has no JS counterpart at all"
    assert "**" not in body, "no exponentiation: CPython and JS disagree on its edge cases"


def test_the_map_is_byte_stable_across_runs(tmp_path):
    build_tree(tmp_path)
    first = repo_map(tmp_path, focus=["pkg/caller.py"])
    second = repo_map(tmp_path, focus=["pkg/caller.py"])
    assert first.text == second.text
    assert [e.rank_units for e in first.ranked] == [e.rank_units for e in second.ranked]


# --------------------------------------------------------------------------------------
# walk_sources


def test_the_walk_skips_the_named_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "keep.py").write_text("x = 1\n", encoding="utf-8")
    for skipped in ("node_modules", ".venv", "__pycache__", ".git"):
        (tmp_path / skipped).mkdir()
        (tmp_path / skipped / "drop.py").write_text("x = 1\n", encoding="utf-8")
    assert walk_sources(tmp_path) == ["src/keep.py"]


def test_the_walk_returns_files_it_has_no_dialect_for(tmp_path):
    # J45-10 read `walk_sources`' first docstring line as "every path this scanner has a
    # dialect for" and measured it false: 1968 returned against 278 with a language. The
    # two tests around this one could not tell, because both build a tree whose every
    # file is `.py` -- green under either reading. This one is the input that CAN fail:
    # the walk must hand `_scan_tree` the unknown file so it can be counted as an
    # omission, because a path dropped here is a path no omission line ever names.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "keep.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# no dialect for this\n", encoding="utf-8")
    (tmp_path / "src" / "data.bin").write_bytes(b"\x00\x01\x02")
    assert walk_sources(tmp_path) == ["README.md", "src/data.bin", "src/keep.py"]


def test_the_walk_does_not_follow_a_directory_symlink(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "a.py").write_text("x = 1\n", encoding="utf-8")
    try:
        os.symlink(tmp_path / "real", tmp_path / "loop", target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - unprivileged Windows
        pytest.skip("this host does not allow creating a directory symlink")
    assert walk_sources(tmp_path) == ["real/a.py"]


# --------------------------------------------------------------------------------------
# the repository's own sources


def test_the_map_over_this_repositorys_python_package_finds_its_own_modules():
    root = REPO / "runtime-py" / "src" / "bantamkit"
    result = repo_map(root, focus=["memory/dream.py"], budget=DEFAULT_BUDGET)
    assert result.nodes > 20
    assert result.edges > 0
    listed = [e.path for e in result.ranked]
    assert "memory/store.py" in listed[:3], listed[:5]
    assert "memory/dream.py" not in listed
    assert result.listing_bytes <= DEFAULT_BUDGET
    assert result.damping > 0.0 and result.iterations == ITERATIONS
