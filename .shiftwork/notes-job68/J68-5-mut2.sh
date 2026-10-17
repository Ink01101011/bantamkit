#!/bin/bash
# usage: mut2.sh ID "FILE|||OLD|||NEW" ["FILE|||OLD|||NEW" ...] -- SUITE...   (each OLD exactly once)
set -e
SP=$S/j685
source $SP/env.sh
ID=$1; shift
M=$SP/mut/$ID; rm -rf $M; mkdir -p $M
rsync -a --exclude .git --exclude .venv --exclude runtime-ts/node_modules --exclude runtime-ts/dist --exclude .shiftwork /Users/kktest/Documents/Claude/Projects/bantamkit/ $M/
ln -s /Users/kktest/Documents/Claude/Projects/bantamkit/runtime-ts/node_modules $M/runtime-ts/node_modules
while [ "$1" != "--" ]; do
  python3 - "$M" "$1" <<'PY'
import sys
m, spec = sys.argv[1:]
f, o, n = spec.split("|||")
p = m + "/" + f; s = open(p).read(); assert s.count(o) == 1, (f, o, s.count(o)); open(p, "w").write(s.replace(o, n))
PY
  shift
done
shift
(cd $M/runtime-ts && npm run build >/dev/null 2>&1)
for S in "$@"; do
  BANTAMKIT_CONFORMANCE_PYTHON=/Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python node $M/tools/conformance/run.mjs --suite $S 2>&1 | grep -E "^  ✖|^(PASS|FAIL):" | sed "s/^/[$ID $S] /"
done
