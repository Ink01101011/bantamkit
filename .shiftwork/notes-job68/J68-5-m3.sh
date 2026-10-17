#!/bin/bash
set -e
SP=$S/j685
source $SP/env.sh
M=$SP/mut/M3-sym-feedback-1.0; rm -rf $M; mkdir -p $M
rsync -a --exclude .git --exclude .venv --exclude runtime-ts/node_modules --exclude runtime-ts/dist --exclude .shiftwork /Users/kktest/Documents/Claude/Projects/bantamkit/ $M/
ln -s /Users/kktest/Documents/Claude/Projects/bantamkit/runtime-ts/node_modules $M/runtime-ts/node_modules
python3 - $M <<'PY'
import sys
m=sys.argv[1]
for f,o,n in ((m+'/runtime-py/src/bantamkit/memory/retrieval.py','"feedback": 1.3','"feedback": 1.0'),(m+'/runtime-ts/src/memory/retrieval.ts',"['feedback', 1.3]","['feedback', 1.0]")):
    s=open(f).read(); assert s.count(o)==1; open(f,'w').write(s.replace(o,n))
PY
(cd $M/runtime-ts && npm run build >/dev/null 2>&1)
for S in recall-retrieval recall-strings; do
  BANTAMKIT_CONFORMANCE_PYTHON=/Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python node $M/tools/conformance/run.mjs --suite $S 2>&1 | grep -E "^  ✖|^(PASS|FAIL):" | sed "s/^/[M3 $S] /"
done
