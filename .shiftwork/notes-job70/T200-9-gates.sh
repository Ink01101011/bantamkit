#!/bin/bash
S=${S:?set S to a scratch dir}
cd $S/rv
export HOME=$S/gh USERPROFILE=$S/gh BANTAMKIT_INDEX_DIR=$S/gh/index BANTAMKIT_RETENTION=off TMPDIR=$S/ct
echo "== pytest"; .venv/bin/python -m pytest runtime-py/tests -q 2>&1 | tail -4
echo "== ruff"; .venv/bin/ruff check runtime-py tools 2>&1 | tail -2
echo "== npm test"; (cd runtime-ts && npm test 2>&1 | grep -E "^ℹ (tests|pass|fail) ")
echo "== conformance --all"; BANTAMKIT_CONFORMANCE_PYTHON=$S/rv/.venv/bin/python node tools/conformance/run.mjs --all 2>&1 | grep -E "✖|^(PASS|FAIL)" | tail -20
