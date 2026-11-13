"""Live-evaluation fixtures for #310: three core-mode cases, fast checks, hidden oracles.

Each case is a small stdlib-only Python package. ``base`` is what an agent workspace
starts from (package skeleton plus the visible fast checks); ``reference`` holds one
correct implementation per author task; ``oracle`` holds the hidden criterion tests.
Only ``base`` is ever copied into a workspace. The oracle runs in a separate process
from a scratch cwd with the workspace on ``sys.path`` and bytecode writing disabled,
so nothing from it reaches or is left in the workspace.

Seeding is deterministic: ordered AST-level mutation operators are applied to one
unit's files, site by site, and the first mutant that still passes that unit's fast
check but newly fails the hidden oracle on at least one of that unit's criteria is
kept. Seeding judges the unit in isolation: every other unit's files are overlaid
with the reference in a scratch copy, so an upstream defect is never credited.
"""

from __future__ import annotations

import ast
import copy
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURES = Path(__file__).resolve().with_name("live_fixtures")
ORACLE_RUNNER = FIXTURES / "oracle_runner.py"
FAST_CHECK_TIMEOUT = 30
ORACLE_TIMEOUT = 30
CRITERION_TIMEOUT = 10


def _check(unit_id: str) -> list[str]:
    return [sys.executable, "-I", "-B", f"checks/check_{unit_id}.py"]


def _unit(unit_id, kind, path, depends_on, task, criteria, seed=False) -> dict:
    return {
        "id": unit_id,
        "kind": kind,
        "task": task,
        "files": [path],
        "depends_on": depends_on,
        "criteria": [{"id": cid, "text": text} for cid, text in criteria],
        "fast_check": _check(unit_id),
        "seed": seed,
    }


def _native_chain() -> list[dict]:
    return [
        _unit(
            "A",
            "author",
            "ledgerkit/money.py",
            [],
            "Create ledgerkit/money.py with `parse_amount(text: str) -> int` that turns a "
            "human-written money amount into integer cents. Ignore surrounding whitespace, "
            "thousands commas and a `$` sign (a leading minus may come before or after the "
            "`$`). Use exact decimal arithmetic, never binary floats, and round to the "
            "nearest cent with halves rounded away from zero. Raise ValueError for an "
            "empty or blank string, anything that is not a number, and NaN or infinity. "
            "Run `python checks/check_A.py` to confirm the shape.",
            [
                ("A-format", "Commas, `$`, surrounding whitespace and a leading minus "
                 "are accepted; whole and fractional amounts become exact cents."),
                ("A-rounding", "Sub-cent amounts round half away from zero using exact "
                 "decimal arithmetic (2.675 -> 268 cents, -0.125 -> -13)."),
                ("A-invalid", "Empty, blank, non-numeric, NaN and infinite inputs raise "
                 "ValueError."),
            ],
            seed=True,
        ),
        _unit(
            "B",
            "author",
            "ledgerkit/lines.py",
            ["A"],
            "Create ledgerkit/lines.py with `line_total(quantity: int, unit_price: str, "
            "discount_pct: int = 0) -> int`, the line's price in cents. Parse unit_price "
            "with `ledgerkit.money.parse_amount`. The gross is quantity times the unit "
            "price in cents; the discount is gross x discount_pct / 100 rounded to the "
            "nearest cent with halves away from zero (exact decimal arithmetic); return "
            "gross minus discount. Raise ValueError when quantity is not positive or "
            "discount_pct is outside 0..100 inclusive. Run `python checks/check_B.py`.",
            [
                ("B-total", "Gross is quantity x parse_amount(unit_price) in cents."),
                ("B-discount", "The discount is a whole percent of the gross, rounded "
                 "half away from zero before it is subtracted; 100 percent gives 0."),
                ("B-validation", "Non-positive quantity and a discount outside 0..100 "
                 "raise ValueError."),
            ],
        ),
        _unit(
            "C",
            "author",
            "ledgerkit/invoice.py",
            ["B"],
            "Create ledgerkit/invoice.py with `invoice_summary(lines, tax_rate_pct) -> "
            "dict`. `lines` is any iterable of `(quantity, unit_price, discount_pct)` "
            "tuples; price each with `ledgerkit.lines.line_total` and add them into the "
            "subtotal. `tax_rate_pct` is a percentage given as an int, a float or a "
            "numeric string (e.g. 7.5 or \"7.5\"); tax is subtotal x rate / 100 rounded "
            "to the nearest cent with halves away from zero, using exact decimal "
            "arithmetic on the rate's written value. Return exactly "
            "`{\"subtotal\": ..., \"tax\": ..., \"total\": subtotal + tax}` in cents. "
            "Run `python checks/check_C.py`.",
            [
                ("C-totals", "Subtotal sums line_total over every line; total is "
                 "subtotal plus tax; fractional and string rates are honoured."),
                ("C-tax-rounding", "Tax rounds half away from zero to the cent."),
                ("C-empty", "No lines gives zeros; any iterable of lines is accepted."),
            ],
            seed=True,
        ),
    ]


def _sequential_delegates() -> list[dict]:
    return [
        _unit(
            "A",
            "author",
            "logscan/parse.py",
            [],
            "Create logscan/parse.py with `parse_line(line: str) -> dict | None`. A "
            "well-formed line, after stripping surrounding whitespace, is "
            "`<timestamp> <level> <component>: <message>` separated by single spaces, "
            "where timestamp is `YYYY-MM-DDTHH:MM:SSZ` (UTC), level is one of DEBUG, "
            "INFO, WARN, ERROR in any letter case, and component is non-empty with no "
            "spaces. The message is everything after the first `: ` and may itself "
            "contain colons. Return `{\"ts\": timezone-aware UTC datetime, \"level\": "
            "upper-case level, \"component\": str, \"message\": stripped str}`; return "
            "None for any line that is not well formed (never raise). Run "
            "`python checks/check_A.py`.",
            [
                ("A-fields", "All four fields are extracted; ts is a UTC-aware datetime; "
                 "the message keeps any later colons and is stripped."),
                ("A-level", "Level is matched case-insensitively and returned upper "
                 "case; unknown levels give None."),
                ("A-invalid", "Blank lines, missing parts, a missing `: `, an empty "
                 "component or a bad timestamp give None."),
            ],
            seed=True,
        ),
        _unit(
            "B",
            "author",
            "logscan/window.py",
            ["A"],
            "Create logscan/window.py with `count_by_window(records, minutes: int) -> "
            "dict[str, int]`. Records are dicts shaped like `logscan.parse.parse_line` "
            "output. Windows are `minutes` long and aligned to midnight of the record's "
            "own day; a record exactly on a boundary starts the new window. Key each "
            "window by its start formatted `YYYY-MM-DDTHH:MMZ` and return counts with "
            "keys in chronological order whatever the input order. Raise ValueError "
            "unless minutes is positive and divides 1440 exactly. Run "
            "`python checks/check_B.py`.",
            [
                ("B-boundary", "Windows align to midnight; a record exactly on a "
                 "boundary belongs to the window that starts there."),
                ("B-order", "Keys are window starts in chronological order regardless "
                 "of input order, across days."),
                ("B-validation", "minutes that is not positive or does not divide 1440 "
                 "raises ValueError."),
            ],
        ),
        _unit(
            "C",
            "author",
            "logscan/report.py",
            ["B"],
            "Create logscan/report.py with `top_components(records, level: str, limit: "
            "int = 3) -> list[tuple[str, int]]`. Records are dicts shaped like "
            "`logscan.parse.parse_line` output. Count records per component, only for "
            "the given level (matched case-insensitively against the record's upper-case "
            "level). Return at most `limit` `(component, count)` pairs, highest count "
            "first and equal counts in ascending component name order; limit 0 gives an "
            "empty list. Run `python checks/check_C.py`.",
            [
                ("C-filter", "Only records at the requested level count; the level "
                 "argument is case-insensitive."),
                ("C-ranking", "Pairs are ordered by count descending, then component "
                 "name ascending."),
                ("C-limit", "At most `limit` pairs are returned, default 3, and 0 "
                 "gives none."),
            ],
            seed=True,
        ),
    ]


def _mixed_fork_join() -> list[dict]:
    return [
        _unit(
            "K",
            "author",
            "stockplan/contract.py",
            [],
            "Create stockplan/contract.py, the contract every other stockplan module "
            "uses. Define a frozen dataclass `Item` with fields in this order: `sku: "
            "str`, `qty: int`, `reorder_at: int`. Define `validate_item(item: Item) -> "
            "Item` that returns the same item object when it is valid and raises "
            "ValueError when sku is empty or has leading/trailing whitespace, or when "
            "qty or reorder_at is negative (zero is valid). Run "
            "`python checks/check_K.py`.",
            [
                ("K-fields", "Item is a frozen, hashable dataclass with fields sku, "
                 "qty, reorder_at in that order."),
                ("K-validate", "validate_item returns the item itself when valid and "
                 "raises ValueError for a blank or padded sku or a negative qty or "
                 "reorder_at; zero is valid."),
            ],
            seed=True,
        ),
        _unit(
            "B",
            "author",
            "stockplan/reorder.py",
            ["K"],
            "Create stockplan/reorder.py with `needs_reorder(items) -> list[str]`. Check "
            "each Item with `stockplan.contract.validate_item` (let its ValueError "
            "propagate) and return the skus whose qty is at or below reorder_at, sorted "
            "in plain string order. Run `python checks/check_B.py`.",
            [
                ("B-threshold", "An item is due when qty <= reorder_at (equal counts as "
                 "due)."),
                ("B-order", "Skus are returned in plain sorted string order; an invalid "
                 "item raises ValueError."),
            ],
        ),
        _unit(
            "C",
            "author",
            "stockplan/merge.py",
            ["K"],
            "Create stockplan/merge.py with `merge_counts(first, second) -> list[Item]` "
            "combining two warehouses' Item lists. Validate every input item with "
            "`stockplan.contract.validate_item`. Items with the same sku become one Item "
            "whose qty is the sum of their qtys and whose reorder_at is the largest of "
            "their reorder_at values. Return the merged Items sorted by sku. Run "
            "`python checks/check_C.py`.",
            [
                ("C-sum", "Quantities of the same sku are summed across both lists."),
                ("C-reorder-max", "The merged reorder_at is the largest seen for that "
                 "sku."),
                ("C-order-validate", "Output is sorted by sku, empty inputs give an "
                 "empty list, and an invalid item raises ValueError."),
            ],
            seed=True,
        ),
        _unit(
            "I",
            "integration",
            "stockplan/plan.py",
            ["B", "C"],
            "Create stockplan/plan.py with `restock_plan(first, second, multiple: int = "
            "2) -> dict[str, int]`. Merge the two warehouses with "
            "`stockplan.merge.merge_counts`, find due skus with "
            "`stockplan.reorder.needs_reorder`, and for each due sku order "
            "`reorder_at * multiple - qty` units of the merged item. Leave out skus "
            "that are not due and skus whose order would be zero or less. Run "
            "`python checks/check_I.py`.",
            [
                ("I-plan", "Due skus get reorder_at x multiple minus merged qty, using "
                 "the merged counts from both warehouses."),
                ("I-skip", "Skus that are not due, or whose order would be zero or "
                 "less, are absent."),
            ],
        ),
    ]


CASES = (
    ("native-chain", "native-chain", _native_chain),
    ("sequential-delegates", "sequential-delegates", _sequential_delegates),
    ("mixed-fork-join", "mixed-fork-join", _mixed_fork_join),
)


def live_cases() -> list[dict]:
    """Return fresh case dicts; callers may mutate their copy freely."""
    cases = []
    for case_id, mode, build in CASES:
        root = FIXTURES / case_id
        cases.append(
            {
                "id": case_id,
                "mode": mode,
                "base_dir": str(root / "base"),
                "oracle_dir": str(root / "oracle"),
                "reference_dir": str(root / "reference"),
                "units": build(),
            }
        )
    return cases


def _unit_of(case: dict, unit_id: str) -> dict:
    for unit in case["units"]:
        if unit["id"] == unit_id:
            return unit
    raise KeyError(f"case {case['id']} has no unit {unit_id}")


def make_workspace(case: dict, dest, reference: bool = False) -> Path:
    """Copy ``base_dir`` to a new ``dest``; optionally add every reference unit file."""
    dest = Path(dest)
    shutil.copytree(case["base_dir"], dest, ignore=shutil.ignore_patterns("__pycache__"))
    if reference:
        source = Path(case["reference_dir"])
        for unit in case["units"]:
            for rel in unit["files"]:
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / rel, target)
    return dest


def revision(workspace, files) -> str:
    """sha256 over the sorted relative paths and their bytes; a missing file is marked."""
    root = Path(workspace)
    h = hashlib.sha256()
    for rel in sorted(Path(f).as_posix() for f in files):
        path = root / rel
        h.update(rel.encode("utf-8") + b"\0")
        if path.is_file():
            data = path.read_bytes()
            h.update(b"present\0" + str(len(data)).encode("ascii") + b"\0" + data)
        else:
            h.update(b"missing\0")
    return h.hexdigest()


def run_fast_check(case: dict, unit_id: str, workspace) -> dict:
    """Run the unit's visible fast check with cwd=workspace."""
    unit = _unit_of(case, unit_id)
    try:
        proc = subprocess.run(
            unit["fast_check"],
            cwd=Path(workspace),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=FAST_CHECK_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"passed": False, "output": f"fast check timed out after {FAST_CHECK_TIMEOUT}s"}
    return {"passed": proc.returncode == 0, "output": proc.stdout + proc.stderr}


def _oracle_call(case: dict, workspace: Path, criteria: list[str], timeout: float) -> dict:
    oracle = Path(case["oracle_dir"]) / "oracle.py"
    argv = [sys.executable, "-I", "-B", str(ORACLE_RUNNER), str(oracle), str(workspace)]
    with tempfile.TemporaryDirectory(prefix="oracle-cwd-") as scratch:
        proc = subprocess.run(
            [*argv, *criteria],
            cwd=scratch,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"error": f"oracle runner exit {proc.returncode}: {proc.stderr.strip()[-500:]}"}
    if proc.returncode != 0 and "error" not in payload:
        payload["error"] = f"oracle runner exit {proc.returncode}"
    return payload


def _isolated_copy(case: dict, workspace: Path, unit_id: str, dest: Path) -> Path:
    """Copy ``workspace`` to ``dest`` and overlay the reference for every file that
    ``unit_id`` does not own. Symlinks are copied as links and unlinked before an
    overlay, so no write ever follows a link back into the workspace."""
    own = {Path(f).as_posix() for f in _unit_of(case, unit_id)["files"]}
    shutil.copytree(workspace, dest, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    reference = Path(case["reference_dir"])
    for unit in case["units"]:
        for rel in unit["files"]:
            if Path(rel).as_posix() in own:
                continue
            target = dest / rel
            if target.is_symlink() or target.exists():
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(reference / rel, target)
    return dest


def run_hidden_oracle(case: dict, workspace, criteria=None, isolate_unit=None) -> dict:
    """Run hidden criteria against ``workspace``; never writes into it.

    ``results`` maps each evaluated criterion to pass/fail. On a runner error the
    outcome is unknown, so ``results`` is empty and ``error`` says why. A timeout of
    the whole run falls back to one process per criterion, a timed-out criterion
    failing.

    With ``isolate_unit`` the oracle runs on a scratch copy of the workspace, outside
    it and removed afterwards, in which every file owned by another unit is that
    case's reference implementation: the result then judges only that unit's own
    code. The default (``None``) judges the workspace as it is, the acceptance oracle.
    """
    workspace = Path(workspace).resolve()
    if isolate_unit is not None:
        with tempfile.TemporaryDirectory(prefix="oracle-isolated-") as scratch:
            copy_root = _isolated_copy(case, workspace, isolate_unit, Path(scratch) / "ws")
            return run_hidden_oracle(case, copy_root, criteria)
    wanted = list(criteria) if criteria is not None else []
    try:
        payload = _oracle_call(case, workspace, wanted, ORACLE_TIMEOUT)
    except subprocess.TimeoutExpired:
        ids = wanted or [c["id"] for unit in case["units"] for c in unit["criteria"]]
        results: dict[str, bool] = {}
        details: dict[str, str] = {}
        for cid in ids:
            try:
                one = _oracle_call(case, workspace, [cid], CRITERION_TIMEOUT)
            except subprocess.TimeoutExpired:
                results[cid], details[cid] = False, f"timed out after {CRITERION_TIMEOUT}s"
                continue
            if one.get("error"):
                return {"results": {}, "error": one["error"], "details": {}}
            results.update(one["results"])
            details.update(one.get("details", {}))
        return {"results": results, "error": None, "details": details}
    if payload.get("error"):
        return {"results": {}, "error": payload["error"], "details": {}}
    return {"results": payload["results"], "error": None, "details": payload.get("details", {})}


def unit_criteria_status(case: dict, workspace, unit_id: str, criteria=None) -> dict:
    """Judge ``unit_id``'s criteria (default: all of them) on its own code alone.

    Same shape as ``run_hidden_oracle``: ``results`` {criterion: bool}, ``error``
    (``None``, or why the outcome is unknown, with ``results`` empty) and
    ``details``. Every other unit's files are the reference, so a defect elsewhere
    in the workspace (an upstream seed, another author's bug) cannot fail or pass
    these criteria. ``workspace`` is never written.
    """
    wanted = [c["id"] for c in _unit_of(case, unit_id)["criteria"]] if criteria is None \
        else list(criteria)
    return run_hidden_oracle(case, workspace, wanted, isolate_unit=unit_id)


# --- deterministic mutation seeding -------------------------------------------------

_BOUNDARY = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt}
_NEGATE = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In,
           ast.Is: ast.IsNot, ast.IsNot: ast.Is}
_ARITH = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Add, ast.Div: ast.Mult,
          ast.FloorDiv: ast.Mult, ast.Mod: ast.FloorDiv}
_BOOL = {ast.And: ast.Or, ast.Or: ast.And}


def _swap_compare(table):
    def sites(tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for index, op in enumerate(node.ops):
                    if type(op) in table:
                        new = copy.deepcopy(node)
                        new.ops[index] = table[type(op)]()
                        yield node, f"({ast.unparse(new)})"
    return sites


def _constant_shift(tree):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and type(node.value) is int):
            yield node, str(node.value + 1)


def _arith_swap(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and type(node.op) in _ARITH:
            new = copy.deepcopy(node)
            new.op = _ARITH[type(node.op)]()
            yield node, f"({ast.unparse(new)})"


def _boolop_swap(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and type(node.op) in _BOOL:
            new = copy.deepcopy(node)
            new.op = _BOOL[type(node.op)]()
            yield node, f"({ast.unparse(new)})"


def _drop_not(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            yield node, f"({ast.unparse(node.operand)})"


def _negate_condition(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.While)):
            yield node.test, f"(not ({ast.unparse(node.test)}))"
        elif isinstance(node, ast.comprehension):
            for cond in node.ifs:
                yield cond, f"(not ({ast.unparse(cond)}))"


def _drop_method_call(tree):
    """``x.strip()`` -> ``x``: a zero-argument method call returns its receiver."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and not node.args and not node.keywords):
            yield node, f"({ast.unparse(node.func.value)})"


# Fixed order. Within an operator, sites are visited in source order.
OPERATORS = (
    ("compare-boundary", _swap_compare(_BOUNDARY)),
    ("compare-negate", _swap_compare(_NEGATE)),
    ("constant-shift", _constant_shift),
    ("arith-swap", _arith_swap),
    ("boolop-swap", _boolop_swap),
    ("drop-not", _drop_not),
    ("negate-condition", _negate_condition),
    ("drop-method-call", _drop_method_call),
)


def _line_offsets(source: bytes) -> list[int]:
    offsets, total = [0], 0
    for line in source.splitlines(keepends=True):
        total += len(line)
        offsets.append(total)
    return offsets


def _mutants(source: bytes):
    """Yield (operator, mutated bytes) in a fixed order.

    A source that is not valid UTF-8, or does not parse, yields none: byte offsets
    from the AST are UTF-8 offsets, so splicing any other encoding could corrupt it.
    """
    try:
        source.decode("utf-8")
        tree = ast.parse(source)
    except (UnicodeDecodeError, SyntaxError, ValueError):
        return
    offsets = _line_offsets(source)
    for name, sites in OPERATORS:
        found = []
        for node, replacement in sites(tree):
            start = offsets[node.lineno - 1] + node.col_offset
            end = offsets[node.end_lineno - 1] + node.end_col_offset
            found.append((start, end, replacement))
        for start, end, replacement in sorted(found, key=lambda s: (s[0], s[1])):
            mutated = source[:start] + replacement.encode("utf-8") + source[end:]
            if mutated == source:
                continue
            try:
                ast.parse(mutated)
            except (SyntaxError, ValueError):
                continue
            yield name, mutated


def _seed_result(unit_id: str, root: Path, files, before_sha: str, *, baseline_failing,
                 reason=None, applied=None) -> dict:
    result = {
        "applied": False,
        "operator": None,
        "criterion": None,
        "failing": [],
        "baseline_failing": list(baseline_failing),
        "reason": reason,
        "unit": unit_id,
        "file": None,
        "before_sha": before_sha,
        "after_sha": revision(root, files),
        "diff": "",
    }
    if applied is not None:
        result.update(applied, applied=True, reason=None)
    return result


def seed_defect(case: dict, unit_id: str, workspace) -> dict:
    """Apply the first qualifying mutant to the unit's files, or restore and report none.

    Every oracle run here is unit-isolated (``unit_criteria_status``): other units'
    files are the reference, so an upstream defect (an unreviewed earlier seed) is
    never mistaken for this unit's. The fast check runs on the real workspace.
    The hidden oracle first runs on the unmutated code; ``baseline_failing`` lists
    the unit's criteria that already fail there. A mutant qualifies only if the
    unit's fast check still passes and at least one criterion that PASSED on the
    baseline now fails: a defect the author already left is never credited to the
    seed. ``failing`` lists only those newly failing criteria, ``criterion`` the
    first of them in the unit's criterion order. If the baseline oracle errors,
    nothing is seeded and ``reason`` says why (unknown, never a guess).
    """
    unit = _unit_of(case, unit_id)
    root = Path(workspace)
    files = unit["files"]
    criteria = [c["id"] for c in unit["criteria"]]
    before_sha = revision(root, files)
    baseline = unit_criteria_status(case, root, unit_id, criteria)
    if baseline["error"]:
        return _seed_result(unit_id, root, files, before_sha, baseline_failing=[],
                            reason=f"baseline oracle error: {baseline['error']}")
    baseline_failing = [cid for cid in criteria if baseline["results"].get(cid) is not True]
    passing = [cid for cid in criteria if baseline["results"].get(cid) is True]
    if not passing:
        return _seed_result(unit_id, root, files, before_sha,
                            baseline_failing=baseline_failing,
                            reason="no criterion passes before seeding")
    for rel in files:
        path = root / rel
        if not path.is_file():
            continue
        original = path.read_bytes()
        kept = None
        try:
            for operator, mutated in _mutants(original):
                path.write_bytes(mutated)
                if not run_fast_check(case, unit_id, root)["passed"]:
                    continue
                oracle = unit_criteria_status(case, root, unit_id, passing)
                if oracle["error"]:
                    continue
                failing = [cid for cid in passing if oracle["results"].get(cid) is False]
                if failing:
                    kept = (operator, mutated, failing)
                    break
        finally:
            if kept is None:
                path.write_bytes(original)
        if kept is not None:
            operator, mutated, failing = kept
            diff = "".join(
                difflib.unified_diff(
                    original.decode("utf-8", errors="replace").splitlines(keepends=True),
                    mutated.decode("utf-8", errors="replace").splitlines(keepends=True),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                )
            )
            return _seed_result(unit_id, root, files, before_sha,
                                baseline_failing=baseline_failing,
                                applied={"operator": operator, "criterion": failing[0],
                                         "failing": failing, "file": rel, "diff": diff})
    return _seed_result(unit_id, root, files, before_sha, baseline_failing=baseline_failing,
                        reason="no mutant passes the fast check and newly fails a criterion")
