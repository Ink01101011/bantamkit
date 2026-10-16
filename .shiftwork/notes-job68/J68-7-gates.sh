#!/bin/bash
source $S/env.sh
cd /Users/kktest/Documents/Claude/Projects/bantamkit
.venv/bin/ruff check runtime-py tools > $S/g-ruff.log 2>&1
.venv/bin/python -m pytest tools/eval/recall -q > $S/g-eval.log 2>&1
(cd runtime-ts && npm run build > $S/g-build.log 2>&1 && npm test 2>&1 | grep -E "^not ok|ℹ (tests|pass|fail)|^✖" > $S/g-npm.log)
.venv/bin/python -m pytest runtime-py/tests -q -p no:randomly 2>&1 | grep -E "^FAILED|^ERROR|passed|failed" > $S/g-pytest.log &
node tools/conformance/run.mjs --all 2>&1 | grep -E "^  ✖|^(PASS|FAIL):" > $S/g-conf.log &
wait
echo DONE > $S/g-done
