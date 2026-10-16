#!/bin/bash
# usage: rvmut.sh <unit> <ID> <suite...> -- rsync the review worktree at 0d33d03, apply <unit>'s mutation <ID>, build, run suites
set -u
REPO=${S:?set S to a scratch dir}/rv
HERE=${S:?set S to a scratch dir}/mut
U=$1; ID=$2; shift 2
M=$HERE/copy-$U-$ID; CT=$HERE/ct-$U-$ID; FH=$HERE/home-$U-$ID
rm -rf "$M" "$CT" "$FH"; mkdir -p "$CT" "$FH"
rsync -a --exclude .git --exclude .venv --exclude runtime-ts/node_modules --exclude runtime-ts/dist --exclude .shiftwork "$REPO/" "$M/"
ln -s "$REPO/runtime-ts/node_modules" "$M/runtime-ts/node_modules"
"$REPO/.venv/bin/python" "$REPO/.shiftwork/notes-job70/$U-mut.py" "$M" "$ID" || { echo "MUTATION MISSED $U $ID"; exit 2; }
(cd "$M/runtime-ts" && npm run build >/dev/null 2>&1) || { echo BUILD FAILED; exit 3; }
for s in "$@"; do
  echo "== $U $ID suite $s"
  (cd "$M" && HOME=$FH USERPROFILE=$FH TMPDIR=$CT BANTAMKIT_RETENTION=off BANTAMKIT_INDEX_DIR=$FH/index      PYTHONPATH=$M/runtime-py/src BANTAMKIT_CONFORMANCE_PYTHON=$REPO/.venv/bin/python      node tools/conformance/run.mjs --suite "$s" 2>&1 | grep -E "^(PASS|FAIL)")
done
rm -rf "$M" "$CT" "$FH"
