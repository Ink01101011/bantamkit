"""Behavioural tests for the #310 live fixtures: real subprocess checks, no model calls."""

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("grouped_live_cases", HERE / "live_cases.py")


def load():
    assert SPEC.origin and Path(SPEC.origin).exists(), "live_cases.py is missing"
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
    return module


lc = load()
CASES = {case["id"]: case for case in lc.live_cases()}
CASE_IDS = ["native-chain", "sequential-delegates", "mixed-fork-join"]
SEEDED = [(cid, u["id"]) for cid in CASE_IDS for u in CASES[cid]["units"] if u["seed"]]


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def all_criteria(case):
    return [c["id"] for u in case["units"] for c in u["criteria"]]


def test_case_shapes_topologies_and_seed_placement():
    assert [c["id"] for c in lc.live_cases()] == CASE_IDS
    topology = {
        "native-chain": {"A": [], "B": ["A"], "C": ["B"]},
        "sequential-delegates": {"A": [], "B": ["A"], "C": ["B"]},
        "mixed-fork-join": {"K": [], "B": ["K"], "C": ["K"], "I": ["B", "C"]},
    }
    for cid, case in CASES.items():
        assert case["mode"] == cid
        assert {u["id"]: u["depends_on"] for u in case["units"]} == topology[cid]
        authors = [u for u in case["units"] if u["kind"] == "author"]
        expected_seeds = {authors[0]["id"], authors[-1]["id"]}
        assert {u["id"] for u in case["units"] if u["seed"]} == expected_seeds
        assert {u["kind"] for u in case["units"]} <= {"author", "integration"}
        for unit in case["units"]:
            assert unit["task"] and unit["files"] and unit["criteria"]
            assert all(c["id"].startswith(unit["id"] + "-") and c["text"]
                       for c in unit["criteria"])
            assert isinstance(unit["fast_check"], list)
            assert unit["fast_check"][0] == sys.executable
        ids = all_criteria(case)
        assert len(ids) == len(set(ids)), "criterion ids must be unique within a case"
    packages = {Path(u["files"][0]).parts[0] for c in CASES.values() for u in c["units"]}
    assert len(packages) == 3, "the three cases must not share a package"
    assert CASES["mixed-fork-join"]["units"][-1]["kind"] == "integration"


@pytest.mark.parametrize("cid", CASE_IDS)
def test_oracle_criteria_match_case_criteria(cid, tmp_path):
    case = CASES[cid]
    ws = lc.make_workspace(case, tmp_path / "ws", reference=True)
    got = lc.run_hidden_oracle(case, ws)
    assert got["error"] is None
    assert list(got["results"]) == all_criteria(case)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_passes_every_fast_check_and_criterion(cid, tmp_path):
    case = CASES[cid]
    ws = lc.make_workspace(case, tmp_path / "ws", reference=True)
    for unit in case["units"]:
        check = lc.run_fast_check(case, unit["id"], ws)
        assert check["passed"], check["output"]
    got = lc.run_hidden_oracle(case, ws)
    assert got["error"] is None
    assert got["results"] == {cid_: True for cid_ in all_criteria(case)}, got["details"]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_base_alone_fails_every_fast_check_and_criterion(cid, tmp_path):
    case = CASES[cid]
    ws = lc.make_workspace(case, tmp_path / "ws")
    for unit in case["units"]:
        assert not lc.run_fast_check(case, unit["id"], ws)["passed"]
    got = lc.run_hidden_oracle(case, ws)
    assert got["error"] is None
    assert got["results"] == {cid_: False for cid_ in all_criteria(case)}


@pytest.mark.parametrize(("cid", "uid"), SEEDED)
def test_seed_qualifies_on_reference(cid, uid, tmp_path):
    case = CASES[cid]
    unit = next(u for u in case["units"] if u["id"] == uid)
    ws = lc.make_workspace(case, tmp_path / "ws", reference=True)
    before = lc.revision(ws, unit["files"])
    seed = lc.seed_defect(case, uid, ws)
    assert seed["applied"], seed
    assert seed["operator"] in {name for name, _ in lc.OPERATORS}
    assert seed["criterion"] in [c["id"] for c in unit["criteria"]]
    assert seed["before_sha"] == before
    assert seed["after_sha"] == lc.revision(ws, unit["files"]) != before
    assert seed["diff"].startswith(f"--- a/{unit['files'][0]}")
    assert lc.run_fast_check(case, uid, ws)["passed"], "a seed must survive the fast check"
    oracle = lc.run_hidden_oracle(case, ws, [seed["criterion"]])
    assert oracle["error"] is None
    assert oracle["results"] == {seed["criterion"]: False}, "the keyed criterion must fail"


def test_seed_skips_a_mutant_the_fast_check_catches(tmp_path):
    """The first oracle-failing mutant (100 -> 101) is caught by a stronger local check."""
    case = CASES["native-chain"]
    ws = lc.make_workspace(case, tmp_path / "ws", reference=True)
    check = ws / "checks" / "check_A.py"
    check.write_text(
        check.read_text(encoding="utf-8")
        + 'assert parse_amount("1") == 100, "one dollar is 100 cents"\n',
        encoding="utf-8",
    )
    seed = lc.seed_defect(case, "A", ws)
    assert seed["applied"]
    assert "* 101" not in seed["diff"]
    assert lc.run_fast_check(case, "A", ws)["passed"]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_fast_checks_catch_missing_and_misshapen_code(cid, tmp_path):
    case = CASES[cid]
    for unit in case["units"]:
        rel = unit["files"][0]
        missing = lc.make_workspace(case, tmp_path / f"missing-{unit['id']}", reference=True)
        (missing / rel).unlink()
        assert not lc.run_fast_check(case, unit["id"], missing)["passed"], (unit["id"], "missing")

        broken = lc.make_workspace(case, tmp_path / f"import-{unit['id']}", reference=True)
        path = broken / rel
        path.write_text("import no_such_module_xyz\n" + path.read_text(encoding="utf-8"),
                        encoding="utf-8")
        assert not lc.run_fast_check(case, unit["id"], broken)["passed"], (unit["id"], "import")

        shaped = lc.make_workspace(case, tmp_path / f"shape-{unit['id']}", reference=True)
        path = shaped / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
        func.args.args.append(ast.arg(arg="extra_param"))
        path.write_text(ast.unparse(tree) + "\n", encoding="utf-8")
        result = lc.run_fast_check(case, unit["id"], shaped)
        assert not result["passed"], (unit["id"], "signature", result["output"])


@pytest.mark.parametrize("cid", CASE_IDS)
def test_oracle_is_unreachable_from_a_base_workspace(cid, tmp_path):
    case = CASES[cid]
    base = Path(case["base_dir"])
    hidden = {Path(case["oracle_dir"]).name, Path(case["reference_dir"]).name, "live_fixtures"}
    for path in base.rglob("*"):
        assert not path.is_symlink(), path
        if path.is_file() and "__pycache__" not in path.parts:
            text = path.read_text(encoding="utf-8")
            for word in hidden:
                assert word not in text, f"{path} names {word}"
            assert "../" not in text and "..\\" not in text, f"{path} has a relative escape"
    ws = lc.make_workspace(case, tmp_path / "ws")
    names = {p.name for p in ws.rglob("*")}
    assert "oracle.py" not in names and "oracle_runner.py" not in names
    assert not (ws / "reference").exists() and not (ws / "oracle").exists()


@pytest.mark.parametrize("cid", CASE_IDS)
def test_oracle_and_fast_checks_leave_no_artifacts(cid, tmp_path):
    case = CASES[cid]
    ws = lc.make_workspace(case, tmp_path / "ws", reference=True)
    before = snapshot(ws)
    lc.run_hidden_oracle(case, ws)
    for unit in case["units"]:
        lc.run_fast_check(case, unit["id"], ws)
    assert snapshot(ws) == before


def test_oracle_criteria_subset_and_unknown_criterion(tmp_path):
    case = CASES["sequential-delegates"]
    ws = lc.make_workspace(case, tmp_path / "ws", reference=True)
    got = lc.run_hidden_oracle(case, ws, ["C-limit", "A-level"])
    assert got == {"results": {"C-limit": True, "A-level": True}, "error": None, "details": {}}
    bad = lc.run_hidden_oracle(case, ws, ["Z-nope"])
    assert bad["results"] == {} and "Z-nope" in bad["error"]


def test_seed_without_a_qualifying_mutant_restores_and_reports(tmp_path):
    case = CASES["mixed-fork-join"]
    ws = lc.make_workspace(case, tmp_path / "ws", reference=True)
    path = ws / "stockplan" / "merge.py"
    # A version whose fast check already fails: no mutant can pass it.
    path.write_text(path.read_text(encoding="utf-8").replace("first, second", "first, other")
                    .replace("*second", "*other"), encoding="utf-8")
    original = path.read_bytes()
    seed = lc.seed_defect(case, "C", ws)
    assert seed["applied"] is False and seed["operator"] is None and seed["criterion"] is None
    assert seed["before_sha"] == seed["after_sha"]
    assert path.read_bytes() == original
    absent = lc.make_workspace(case, tmp_path / "absent")
    assert lc.seed_defect(case, "K", absent)["applied"] is False


@pytest.mark.parametrize(("cid", "uid"), SEEDED)
def test_seed_and_revision_are_deterministic(cid, uid, tmp_path):
    case = CASES[cid]
    first = lc.seed_defect(case, uid, lc.make_workspace(case, tmp_path / "a", reference=True))
    second = lc.seed_defect(case, uid, lc.make_workspace(case, tmp_path / "b", reference=True))
    assert first == second


def test_revision_is_order_independent_and_content_sensitive(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_bytes(b"x = 1\n")
    (tmp_path / "pkg" / "b.py").write_bytes(b"y = 2\n")
    one = lc.revision(tmp_path, ["pkg/a.py", "pkg/b.py"])
    assert one == lc.revision(tmp_path, ["pkg/b.py", "pkg/a.py"])
    assert one != lc.revision(tmp_path, ["pkg/a.py"])
    assert one != lc.revision(tmp_path, ["pkg/a.py", "pkg/b.py", "pkg/c.py"])
    (tmp_path / "pkg" / "b.py").write_bytes(b"y = 3\n")
    assert one != lc.revision(tmp_path, ["pkg/a.py", "pkg/b.py"])


def _python_sources():
    yield HERE / "live_cases.py"
    yield from sorted((HERE / "live_fixtures").rglob("*.py"))


def test_sources_are_portable():
    """pathlib only, argv lists via sys.executable, explicit UTF-8 on text I/O."""
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "path":
                assert not (isinstance(node.value, ast.Name) and node.value.id == "os"), (
                    f"{path}:{node.lineno} uses os.path")
            if not isinstance(node, ast.Call):
                continue
            keywords = {k.arg: k.value for k in node.keywords}
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(
                node.func, "id", None)
            if name in {"read_text", "write_text", "open"}:
                assert "encoding" in keywords, f"{path}:{node.lineno} {name} without encoding"
            if "shell" in keywords:
                raise AssertionError(f"{path}:{node.lineno} passes shell=")
            if name in {"run", "Popen", "check_output", "call"} and node.args:
                assert not isinstance(node.args[0], ast.Constant), (
                    f"{path}:{node.lineno} runs a string command")
            if name == "run" and "text" in keywords:
                assert "encoding" in keywords, f"{path}:{node.lineno} text run without encoding"


def _defective_a(case, root):
    """Reference A with an author defect (HALF_EVEN) and a harmless constant (QW probe)."""
    ws = lc.make_workspace(case, root, reference=True)
    money = ws / "ledgerkit" / "money.py"
    src = money.read_text(encoding="utf-8")
    src = src.replace('"""Parse human-written money amounts into integer cents."""',
                      '"""Parse."""\n\nMAX_LOG_LINES = 5')
    src = src.replace("ROUND_HALF_UP))", "ROUND_HALF_EVEN))").replace(
        "import ROUND_HALF_UP,", "import ROUND_HALF_EVEN, ROUND_HALF_UP,")
    money.write_text(src, encoding="utf-8")
    assert "MAX_LOG_LINES = 5" in money.read_text(encoding="utf-8")
    return ws


def test_seed_on_already_defective_code_credits_only_a_new_defect(tmp_path):
    case = CASES["native-chain"]
    ws = _defective_a(case, tmp_path / "ws")
    criteria = [c["id"] for c in lc._unit_of(case, "A")["criteria"]]
    before = lc.run_hidden_oracle(case, ws, criteria)["results"]
    assert before["A-rounding"] is False and before["A-format"] is True
    seed = lc.seed_defect(case, "A", ws)
    assert seed["applied"], seed
    assert "MAX_LOG_LINES" not in seed["diff"], "a no-op mutant must not qualify"
    assert "A-rounding" not in seed["failing"], "an author's own defect is not the seed's"
    assert seed["criterion"] == seed["failing"][0]
    assert seed["baseline_failing"] == ["A-rounding"]
    after = lc.run_hidden_oracle(case, ws, criteria)["results"]
    for cid in seed["failing"]:
        assert before[cid] is True and after[cid] is False


def test_seed_refuses_when_the_baseline_oracle_errors(tmp_path, monkeypatch):
    case = CASES["native-chain"]
    ws = lc.make_workspace(case, tmp_path / "ws", reference=True)
    files = lc._unit_of(case, "A")["files"]
    before = lc.revision(ws, files)
    monkeypatch.setattr(lc, "run_hidden_oracle",
                        lambda *a, **k: {"results": {}, "error": "runner died", "details": {}})
    seed = lc.seed_defect(case, "A", ws)
    assert seed["applied"] is False and seed["failing"] == [] and seed["criterion"] is None
    assert "runner died" in seed["reason"]
    assert seed["before_sha"] == seed["after_sha"] == before


def test_seed_reports_why_when_every_criterion_already_fails(tmp_path):
    case = CASES["native-chain"]
    ws = lc.make_workspace(case, tmp_path / "ws")  # base: nothing implemented
    seed = lc.seed_defect(case, "A", ws)
    assert seed["applied"] is False and seed["reason"]


@pytest.mark.parametrize("cookie", [True, False])
def test_non_utf8_author_file_never_raises(cookie, tmp_path):
    case = CASES["native-chain"]
    ws = lc.make_workspace(case, tmp_path / "ws", reference=True)
    money = ws / "ledgerkit" / "money.py"
    head = b"# -*- coding: latin-1 -*-\n" if cookie else b""
    money.write_bytes(head + b"# caf\xe9\n" + money.read_bytes())
    original = money.read_bytes()
    files = lc._unit_of(case, "A")["files"]
    sha = lc.revision(ws, files)
    seed = lc.seed_defect(case, "A", ws)
    assert seed["applied"] is False and seed["reason"]
    assert seed["before_sha"] == seed["after_sha"] == sha
    assert money.read_bytes() == original


def test_grouped_chain_seeds_downstream_unit_on_its_own_criteria(tmp_path):
    """Grouped arm: A is seeded and unreviewed when C is authored; C must still seed,
    credited only with C's own newly failing criteria, judged with A and B as reference."""
    case = CASES["native-chain"]
    ws = lc.make_workspace(case, tmp_path / "ws", reference=True)
    seed_a = lc.seed_defect(case, "A", ws)
    assert seed_a["applied"]
    a_file = ws / seed_a["file"]
    a_bytes = a_file.read_bytes()
    c_criteria = [c["id"] for c in lc._unit_of(case, "C")["criteria"]]
    # The shared workspace fails C's criteria because of A's seed alone.
    assert any(v is False for v in lc.run_hidden_oracle(case, ws, c_criteria)["results"].values())
    before = lc.unit_criteria_status(case, ws, "C")
    assert before["error"] is None and all(before["results"][c] for c in c_criteria)
    seed_c = lc.seed_defect(case, "C", ws)
    assert seed_c["applied"], seed_c
    assert seed_c["baseline_failing"] == []
    assert seed_c["file"] == lc._unit_of(case, "C")["files"][0]
    assert set(seed_c["failing"]) <= set(c_criteria) and seed_c["failing"]
    after = lc.unit_criteria_status(case, ws, "C")
    assert [c for c in c_criteria if after["results"][c] is False] == seed_c["failing"]
    assert a_file.read_bytes() == a_bytes, "seeding C never touches A"


def test_isolated_oracle_leaves_workspace_byte_identical_and_ignores_others(tmp_path):
    case = CASES["mixed-fork-join"]
    ws = lc.make_workspace(case, tmp_path / "ws", reference=True)
    k_file = ws / lc._unit_of(case, "K")["files"][0]
    k_file.write_text("raise SystemExit('broken upstream')\n", encoding="utf-8")
    link = ws / "outside-link"
    target = tmp_path / "outside.txt"
    target.write_text("untouched", encoding="utf-8")
    link.symlink_to(target)
    before = snapshot(ws)
    for uid in ("B", "C", "I"):
        status = lc.unit_criteria_status(case, ws, uid)
        assert status["error"] is None, status
        assert all(status["results"].values()), (uid, status["results"])
    k_status = lc.unit_criteria_status(case, ws, "K")
    assert k_status["error"] or not all(k_status["results"].values())
    assert snapshot(ws) == before
    assert target.read_text(encoding="utf-8") == "untouched"
    assert not list(ws.rglob("__pycache__"))
    # The default stays the acceptance oracle on the workspace as it is.
    whole = lc.run_hidden_oracle(case, ws)
    assert whole["error"] or not all(whole["results"].values())
