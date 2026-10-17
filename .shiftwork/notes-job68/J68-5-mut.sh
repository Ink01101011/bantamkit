#!/bin/bash
# usage: mut.sh ID FILE OLD NEW SUITE...   (OLD must occur exactly once in FILE)
set -e
SP=$S/j685
source $SP/env.sh
ID=$1; F=$2; OLD=$3; NEW=$4; shift 4
M=$SP/mut/$ID; rm -rf $M; mkdir -p $M
rsync -a --exclude .git --exclude .venv --exclude runtime-ts/node_modules --exclude runtime-ts/dist --exclude .shiftwork /Users/kktest/Documents/Claude/Projects/bantamkit/ $M/
ln -s /Users/kktest/Documents/Claude/Projects/bantamkit/runtime-ts/node_modules $M/runtime-ts/node_modules
python3 - "$M/$F" "$OLD" "$NEW" <<'PY'
import sys
p,o,n=sys.argv[1:]; s=open(p).read(); assert s.count(o)==1,(o,s.count(o)); open(p,'w').write(s.replace(o,n))
PY
(cd $M/runtime-ts && npm run build >/dev/null 2>&1)
for S in "$@"; do
  PYTHONPATH=$M/runtime-py/src BANTAMKIT_CONFORMANCE_PYTHON=/Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python node $M/tools/conformance/run.mjs --suite $S 2>&1 | grep -E "^  ✖|^(PASS|FAIL):" | sed "s/^/[$ID $S] /"
done
