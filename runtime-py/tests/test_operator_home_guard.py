"""#339: the session guard in conftest sees a new name under the operator's index and usage dirs."""

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from conftest import operator_home_names


def test_the_guard_lists_new_names_and_only_names(tmp_path):
    home = tmp_path / "home"
    (home / ".bantamkit" / "usage").mkdir(parents=True)
    (home / ".bantamkit" / "usage" / "old.jsonl").write_text("a", encoding="utf-8")
    before = operator_home_names(home)
    assert before == {".bantamkit/usage/old.jsonl"}
    # growth of an existing ledger is not a leak
    (home / ".bantamkit" / "usage" / "old.jsonl").write_text("grown", encoding="utf-8")
    assert operator_home_names(home) == before
    (home / ".bantamkit" / "index").mkdir()
    (home / ".bantamkit" / "index" / "abc.json").write_text("{}", encoding="utf-8")
    assert operator_home_names(home) - before == {".bantamkit/index/abc.json"}


@pytest.mark.parametrize("runner", ["pytest", "node"])
@pytest.mark.parametrize("different_homes", [False, True])
def test_a_session_that_leaks_into_the_operator_home_exits_red(tmp_path, runner, different_homes):
    """Both guards use the runtime's native home even when HOME and USERPROFILE differ."""
    op = tmp_path / "op"
    op.mkdir()
    suite = tmp_path / "suite"
    suite.mkdir()
    tests = Path(__file__).parent
    (suite / "conftest.py").write_text(
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location(\n"
        f"    'guard_conftest', {str(tests / 'conftest.py')!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "sys.modules['guard_conftest'] = m\n"
        "spec.loader.exec_module(m)\n"
        "pytest_sessionfinish = m.pytest_sessionfinish\n",
        encoding="utf-8",
    )
    (suite / "test_leak.py").write_text(textwrap.dedent(f"""
        import os
        def test_leak():
            d = {str(op / '.bantamkit' / 'index')!r}
            os.makedirs(d)
            open(os.path.join(d, 'leaked.json'), 'w', encoding='utf-8').write('{{}}')
    """), encoding="utf-8")
    other = tmp_path / "other-home"
    other.mkdir()
    env = {**os.environ, "HOME": str(op), "USERPROFILE": str(op)}
    if different_homes:
        env["HOME" if sys.platform == "win32" else "USERPROFILE"] = str(other)
    env.pop("BANTAMKIT_CONFORMANCE_OPERATOR_HOME", None)
    env.pop("BANTAMKIT_CONFORMANCE_SCRATCH_HOME", None)
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(suite)]
    if runner == "node":
        node = shutil.which("node")
        if not node:
            pytest.skip("Node is required to exercise the conformance runner's leak guard")
        shutil.copy2(tests.parents[1] / "tools" / "conformance" / "run.mjs", suite / "run.mjs")
        (suite / "suites").mkdir()
        (suite / "suites" / "leak.mjs").write_text(
            "import { mkdirSync, writeFileSync } from 'node:fs';\n"
            "import { join } from 'node:path';\n"
            "export const name = 'leak';\n"
            "export async function run() {\n"
            "  const root = join(process.env.LEAK_HOME, '.bantamkit', 'index');\n"
            "  mkdirSync(root, { recursive: true });\n"
            "  writeFileSync(join(root, 'leaked.json'), '{}');\n"
            "  return { cases: [], notes: [] };\n"
            "}\n",
            encoding="utf-8",
        )
        env["LEAK_HOME"] = str(op)
        command = [node, str(suite / "run.mjs"), "--suite", "leak", "--python", sys.executable]
    r = subprocess.run(command,
                       capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(suite))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "OPERATOR HOME LEAK" in r.stderr and ".bantamkit/index/leaked.json" in r.stderr
