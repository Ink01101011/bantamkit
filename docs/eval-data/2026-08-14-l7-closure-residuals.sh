#!/bin/sh
# L7 closure residuals — the three things this job MEASURED and did not fix, plus the
# three invariants a closure unit has to re-verify at its own HEAD rather than cite.
#
#   sh docs/eval-data/2026-08-14-l7-closure-residuals.sh "$PWD"
#
# Layer: Measurement. RB-P28 is OPEN, so a green suite is not the evidence for anything
# here. Cases A and B run outside pytest with no PYTEST_* key in the child's environment;
# case C is a suite run used the only way a suite can be used as evidence — as the thing a
# mutation is supposed to turn red, with the count of survivors as the measurement.
#
# THE MUTATION HAZARD, AS L6 REFINED IT. A scratch COPY of runtime-py/src is NOT enough
# for the OUTSIDE_pytest nodes: `_child_env` hardcodes PYTHONPATH to the REPO's src, so
# the child always imports the repo tree and a patched copy is invisible. Case C therefore
# patches the REAL tree. It refuses to start on a dirty tree, restores by an EXPLICIT sha
# and asserts `git diff HEAD --exit-code` before it prints a result. A run that cannot
# restore is a failed run and says so.
#
# WHAT EACH CASE MEASURES
#   A  RB-P17 residual (L5's M1->M3, LIVE at HEAD). The `derive:` form's manifest segment
#      and its git base are resolved against the PROCESS CWD, not against this repository.
#      `parse_rubric_arg`'s docstring says a reader "who has ONLY this repository and one
#      row" can recover the bytes — "No argv, no machine, no /private/tmp". Measured: the
#      identical repo-relative ref that resolves from the repo root RAISES from any other
#      directory. C3's `_repo_relative` fix is a SHAPE rule on the string and does not
#      touch resolution, so it did not close this.
#   B  L5's M1 (FIXED by L7). `payload_shas_recorded` in `__all__`, before and after.
#   C  RB-P34 (NEW, filed by L7). The exit-status contract's status VALUES are not pinned:
#      GUARD_VIOLATION_EXIT 3 -> 7 leaves the suite green but for the nodes that assert a
#      LITERAL status, because every other node NAMES the constant and moves with it.
set -u

REPO=${1:-$PWD}
PY="$REPO/.venv/bin/python"
SRC="$REPO/runtime-py/src"
FILE="$REPO/runtime-py/src/bantamkit/criticreplay.py"
SPEC='B=derive:assets/evals/perturbations/task-completion.yaml:W1-trailing-newline:git:d2f78b7:assets/rubrics/task-completion.yaml'
GITSPEC='A=git:d2f78b7:assets/rubrics/task-completion.yaml'

echo "repo: $REPO"
echo "head: $(cd "$REPO" && git rev-parse HEAD)"
echo

echo "=== A. RB-P17 residual: the derive: form resolves against the PROCESS CWD ==="
resolve() {
    # $1 = cwd to stand in, $2 = spec. No PYTEST_* key: env -i with only what is needed.
    ( cd "$1" && env -i PATH="$PATH" HOME="$HOME" PYTHONPATH="$SRC" \
        BANTAMKIT_ASSETS="$REPO/assets" "$PY" -c '
import sys
from bantamkit.criticreplay import parse_rubric_arg
try:
    v = parse_rubric_arg(sys.argv[1])
    print("RESOLVED", (v.template_sha256 or v.sha256)[:12])
except Exception as e:
    print("RAISED", type(e).__name__ + ":", e)
' "$2" )
}
echo "A1 derive: from the repo root      -> $(resolve "$REPO" "$SPEC")"
echo "A2 derive: from /                  -> $(resolve / "$SPEC")"
echo "A3 git:    from the repo root      -> $(resolve "$REPO" "$GITSPEC")"
echo "A4 git:    from /                  -> $(resolve / "$GITSPEC")"
echo

echo "=== B. L5's M1: the RB-P18 reader in the published surface ==="
for REF in 6c27ebe HEAD; do
    (cd "$REPO" && git show "$REF:runtime-py/src/bantamkit/criticreplay.py" > /tmp/l7-all-$REF.py)
    echo "B $REF -> $("$PY" - "/tmp/l7-all-$REF.py" <<'EOF'
import ast, sys
tree = ast.parse(open(sys.argv[1]).read())
node = next(
    n for n in tree.body
    if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "__all__"
)
names = [e.value for e in node.value.elts]
print(f"{len(names)} entries, payload_shas_recorded present: {'payload_shas_recorded' in names}")
EOF
)"
done
echo

echo "=== C. RB-P34: the contract's status VALUES are not pinned ==="
cd "$REPO" || exit 1
if ! git diff HEAD --quiet; then
    echo "C REFUSED: the tree is dirty. This case patches the REAL tree; refusing." >&2
    exit 1
fi
SHA=$(git rev-parse HEAD)
COUNT=$(grep -c '^GUARD_VIOLATION_EXIT = 3$' "$FILE")
if [ "$COUNT" != "1" ]; then
    echo "C REFUSED: anchor occurs $COUNT times, not once. A replace that matched nothing" >&2
    echo "  looks exactly like a fix that works." >&2
    exit 1
fi
echo "C0 baseline  -> $("$PY" -m pytest runtime-py/tests -q 2>&1 | tail -1)"
"$PY" - "$FILE" <<'EOF'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); s = p.read_text()
assert s.count("\nGUARD_VIOLATION_EXIT = 3\n") == 1
p.write_text(s.replace("\nGUARD_VIOLATION_EXIT = 3\n", "\nGUARD_VIOLATION_EXIT = 7\n"))
EOF
echo "C1 3 -> 7    -> $("$PY" -m pytest runtime-py/tests -q 2>&1 | tail -1)"
echo "C2 killers   ->"
"$PY" -m pytest runtime-py/tests -q 2>&1 | grep '^FAILED' | sed 's/^/     /'
git checkout "$SHA" -- "$FILE"
if git diff HEAD --exit-code >/dev/null; then
    echo "C3 restored  -> tree byte-exact at $SHA"
else
    echo "C3 RESTORE FAILED at $SHA — this run is not evidence" >&2
    exit 1
fi
