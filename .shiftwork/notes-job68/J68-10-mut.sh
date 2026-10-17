#!/bin/bash
# usage: mut.sh ID SUITE FILE OLD NEW [FILE OLD NEW ...]   (each OLD occurs exactly once in FILE)
set -e
S=$S
R=/Users/kktest/Documents/Claude/Projects/bantamkit
ID=$1; SUITE=$2; shift 2
M=$S/mut/$ID; rm -rf $M; mkdir -p $M $S/mhome/$ID $S/mtmp/$ID
rsync -a --exclude .git --exclude .venv --exclude runtime-ts/node_modules --exclude runtime-ts/dist --exclude .shiftwork $R/ $M/
ln -s $R/runtime-ts/node_modules $M/runtime-ts/node_modules
while [ $# -gt 0 ]; do
python3 - "$M/$1" "$2" "$3" <<'PY'
import sys
p,o,n=sys.argv[1:]; s=open(p).read(); assert s.count(o)==1,(o,s.count(o)); open(p,'w').write(s.replace(o,n))
PY
shift 3; done
(cd $M/runtime-ts && npm run build >/dev/null 2>&1)
HOME=$S/mhome/$ID USERPROFILE=$S/mhome/$ID BANTAMKIT_INDEX_DIR=$S/mhome/$ID/index BANTAMKIT_RETENTION=off TMPDIR=$S/mtmp/$ID/ \
PYTHONPATH=$M/runtime-py/src BANTAMKIT_CONFORMANCE_PYTHON=$R/.venv/bin/python node $M/tools/conformance/run.mjs --suite $SUITE 2>&1 | grep -E "^  ✖|^(PASS|FAIL):" | sed "s/^/[$ID] /"
