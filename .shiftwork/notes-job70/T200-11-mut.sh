#!/bin/bash
# usage: T200-11-mut.sh <ID> <suite...> -- copy the tree, apply mutation <ID> with mut.py, build, run the suites
set -u
REPO=/Users/kktest/Documents/Claude/Projects/bantamkit
HERE=$S/mut11
ID=$1; shift
M=$HERE/copy-$ID; CT=$HERE/ct-$ID; FH=$HERE/home-$ID
rm -rf "$M" "$CT" "$FH"; mkdir -p "$CT" "$FH"
rsync -a --exclude .git --exclude .venv --exclude runtime-ts/node_modules --exclude runtime-ts/dist --exclude .shiftwork "$REPO/" "$M/"
ln -s "$REPO/runtime-ts/node_modules" "$M/runtime-ts/node_modules"
"$REPO/.venv/bin/python" "$REPO/.shiftwork/notes-job70/T200-11-mut.py" "$M" "$ID" || exit 2
(cd "$M/runtime-ts" && npm run build >/dev/null 2>&1) || { echo BUILD FAILED; exit 3; }
for s in "$@"; do
  echo "== suite $s"
  (cd "$M" && HOME=$FH USERPROFILE=$FH TMPDIR=$CT BANTAMKIT_RETENTION=off BANTAMKIT_INDEX_DIR=$FH/index \
     PYTHONPATH=$M/runtime-py/src BANTAMKIT_CONFORMANCE_PYTHON=$REPO/.venv/bin/python \
     node tools/conformance/run.mjs --suite "$s" 2>&1 | grep -E "✖|^(PASS|FAIL)")
done
echo "== unit py"
(cd "$M" && HOME=$FH USERPROFILE=$FH TMPDIR=$CT BANTAMKIT_RETENTION=off BANTAMKIT_INDEX_DIR=$FH/index PYTHONPATH=$M/runtime-py/src \
   "$REPO/.venv/bin/python" -m pytest -q -p no:cacheprovider runtime-py/tests/test_touch_log.py 2>&1 | grep -E "^FAILED|passed|failed")
echo "== unit node"
(cd "$M/runtime-ts" && HOME=$FH USERPROFILE=$FH TMPDIR=$CT BANTAMKIT_RETENTION=off BANTAMKIT_INDEX_DIR=$FH/index node --test test/touch-log.test.mjs 2>&1 | grep -E "^not ok|^ℹ (pass|fail)")
