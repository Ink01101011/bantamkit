"""#339: the session guard in conftest sees a new name under the operator's index and usage dirs."""

import subprocess
import sys
import textwrap
from pathlib import Path

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


def test_a_session_that_leaks_into_the_operator_home_exits_red(tmp_path):
    """Runs a child pytest, HOME at a fake operator home, whose one node leaks a head."""
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
    env = {"PATH": "/usr/bin:/bin", "HOME": str(op), "USERPROFILE": str(op)}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(suite)],
                       capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(suite))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "OPERATOR HOME LEAK" in r.stderr and ".bantamkit/index/leaked.json" in r.stderr
