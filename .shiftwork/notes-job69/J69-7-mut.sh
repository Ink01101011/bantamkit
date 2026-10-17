#!/bin/bash
# usage: J69-7-mut.sh <ID> <suite...>  -- rsync the tree, apply one mutation, build, run the suites
# with a throwaway HOME/TMPDIR (never the operator's), BANTAMKIT_RETENTION=off (run.mjs sets it too).
set -u
REPO=/Users/kktest/Documents/Claude/Projects/bantamkit
HERE=$S/j697/mut
ID=$1; shift
M=$HERE/copy-$ID; CT=$HERE/ct-$ID; FH=$HERE/home-$ID
rm -rf "$M" "$CT" "$FH"; mkdir -p "$CT" "$FH"
rsync -a --exclude .git --exclude .venv --exclude runtime-ts/node_modules --exclude runtime-ts/dist --exclude .shiftwork "$REPO/" "$M/"
ln -s "$REPO/runtime-ts/node_modules" "$M/runtime-ts/node_modules"
"$REPO/.venv/bin/python" "$REPO/.shiftwork/notes-job69/J69-7-mut.py" "$M" "$ID" || exit 2
(cd "$M/runtime-ts" && npm run build >/dev/null 2>&1) || { echo BUILD FAILED; exit 3; }
for s in "$@"; do
  echo "== $ID suite $s"
  (cd "$M" && HOME=$FH USERPROFILE=$FH TMPDIR=$CT BANTAMKIT_RETENTION=off PYTHONPATH=$M/runtime-py/src BANTAMKIT_CONFORMANCE_PYTHON=$REPO/.venv/bin/python node tools/conformance/run.mjs --suite "$s" 2>&1 | grep -E "✖|^(PASS|FAIL)")
done
