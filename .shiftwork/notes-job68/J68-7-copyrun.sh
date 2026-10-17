#!/bin/bash
# usage: copyrun.sh ID [ratio]  -- rsync copy of the tree, optionally GATE_RATIO=<ratio> in BOTH runtimes; all four gates
set -u
S=$S
R=/Users/kktest/Documents/Claude/Projects/bantamkit
source $S/env.sh
ID=$1; RAT=${2:-}; M=$S/mut/$ID
test ! -e "$M" || { echo "$M exists"; exit 1; }
mkdir -p "$M" $S/cleantmp
rsync -a --exclude .git --exclude .venv --exclude runtime-ts/node_modules --exclude runtime-ts/dist --exclude .shiftwork $R/ "$M"/
ln -s $R/runtime-ts/node_modules "$M"/runtime-ts/node_modules
if [ -n "$RAT" ]; then
  sed -i '' "s/^GATE_RATIO = 0.0$/GATE_RATIO = $RAT/" "$M"/runtime-py/src/bantamkit/memory/retrieval.py
  sed -i '' "s/^export const GATE_RATIO = 0.0;$/export const GATE_RATIO = $RAT;/" "$M"/runtime-ts/src/memory/retrieval.ts
  grep -n "^GATE_RATIO\|^export const GATE_RATIO" "$M"/runtime-py/src/bantamkit/memory/retrieval.py "$M"/runtime-ts/src/memory/retrieval.ts
fi
(cd "$M"/runtime-ts && npm run build >/dev/null 2>&1) || echo BUILD FAILED
(cd "$M" && PYTHONPATH="$M"/runtime-py/src $R/.venv/bin/python -m pytest runtime-py/tests -q -p no:randomly 2>&1 | grep -E "^FAILED|^ERROR|passed|failed" | tail -80) > $S/$ID-pytest.log
(cd "$M"/runtime-ts && npm test 2>&1 | grep -E "^not ok|ℹ (tests|pass|fail)|^✖" | head -80) > $S/$ID-npm.log
(cd "$M" && PYTHONPATH="$M"/runtime-py/src BANTAMKIT_CONFORMANCE_PYTHON=$R/.venv/bin/python node tools/conformance/run.mjs --all 2>&1 | grep -E "^  ✖|^(PASS|FAIL):" | head -150) > $S/$ID-conf.log
echo DONE > $S/$ID-done
