#!/bin/bash
# usage: mut.sh <ID> <check...>; check = a conformance suite name, or py:<test file>, or node:<test file>
set -u
REPO=/Users/kktest/Documents/Claude/Projects/bantamkit
HERE=$S/j698/mut
ID=$1; shift
M=$HERE/copy-$ID; CT=$HERE/ct-$ID; FH=$HERE/home-$ID
rm -rf "$M" "$CT" "$FH"; mkdir -p "$CT" "$FH" "$FH/idx"
rsync -a --exclude .git --exclude .venv --exclude runtime-ts/node_modules --exclude runtime-ts/dist --exclude .shiftwork "$REPO/" "$M/"
ln -s "$REPO/runtime-ts/node_modules" "$M/runtime-ts/node_modules"
"$REPO/.venv/bin/python" "$HERE/mut.py" "$M" "$ID" || exit 2
(cd "$M/runtime-ts" && npm run build >/dev/null 2>&1) || { echo BUILD FAILED; exit 3; }
export HOME=$FH USERPROFILE=$FH BANTAMKIT_RETENTION=off BANTAMKIT_INDEX_DIR=$FH/idx
for s in "$@"; do
  echo "== $ID $s"
  case "$s" in
    py:*) (cd "$M" && PYTHONPATH=$M/runtime-py/src "$REPO/.venv/bin/python" -m pytest -q -p no:cacheprovider "${s#py:}" 2>&1 | tail -1) ;;
    node:*) (cd "$M/runtime-ts" && node --test "${s#node:}" 2>&1 | grep -E '^ℹ (pass|fail)|^not ok') ;;
    *) (cd "$M" && TMPDIR=$CT PYTHONPATH=$M/runtime-py/src BANTAMKIT_CONFORMANCE_PYTHON=$REPO/.venv/bin/python node tools/conformance/run.mjs --suite "$s" 2>&1 | grep -E "✖|^(PASS|FAIL)") ;;
  esac
done
