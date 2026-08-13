#!/bin/sh
# K4B/C2 — two --rubric values that share a LABEL: the number a real shell reads, and
# what the module SPENDS before it says so. The runner that produced
# docs/eval-data/2026-08-13-k4b-c2-duplicate-rubric-label.md.
#
#   sh docs/eval-data/2026-08-13-k4b-c2-duplicate-rubric-label.sh "$PWD" /tmp/k4b-c2
#
# BEFORE column:
#   git checkout 3981efd -- runtime-py/src/bantamkit/criticreplay.py
#   sh docs/eval-data/2026-08-13-k4b-c2-duplicate-rubric-label.sh "$PWD" /tmp/k4b-c2-before
#   git checkout HEAD -- runtime-py/src/bantamkit/criticreplay.py
#
# Layer: Measurement. Statuses are /bin/sh's own $?, with no PYTEST_* key in the child's
# environment. No probe and no scripted critic: no case here reaches a client, so this is
# the shipped `python -m bantamkit.criticreplay` end to end.
#
# THE SPEND IS MEASURED, NOT REASONED. `git` on PATH is replaced by a shim that logs every
# invocation and then execs the real one, so "two `git show` subprocesses before it
# noticed the duplicate" is a line count and not a reading of the source.
#
# THE RIG IS POPULATED, AND THAT IS NOT A DETAIL. The first version of this runner used an
# EMPTY --transcripts directory, and every pre-fix case reported 1 with `no transcripts
# with answers` on stderr: the run refused in `load_cases` and never reached
# `guarded_family`'s duplicate-label rule at all. The number was right and the ATTRIBUTION
# was wrong, which is the same mistake in miniature as the one C2 is about. So the rig
# below has a real cell in it and every case gets far enough for the rule under test to be
# the rule that fires - checked by the stderr column, not assumed.
#
# It therefore runs `cli_exit_status_probe.py`, the shipped main() with only the client
# constructor replaced: a populated rig means a case that PASSES the rule goes to the wire,
# and a control whose number depends on the network is not a control.
set -u
REPO=$1; WORK=$2
PY="$REPO/.venv/bin/python"; PROBE="$REPO/runtime-py/tests/cli_exit_status_probe.py"
RUBRIC="$REPO/assets/rubrics/task-completion.yaml"
GITSPEC="git:HEAD:assets/rubrics/task-completion.yaml"
mkdir -p "$WORK/emptydir" "$WORK/bin"
cp "$RUBRIC" "$WORK/r1.yaml"; cp "$RUBRIC" "$WORK/r2.yaml"
"$PY" - "$WORK" <<'PY'
import json, sys, pathlib
t = pathlib.Path(sys.argv[1]) / "transcripts"; t.mkdir(parents=True, exist_ok=True)
(t / "critique--recall-db-port--r0.json").write_text(json.dumps({
    "task": "recall-db-port", "config": "critique", "repeat": 0, "passed": True,
    "outcome": "pass", "seed": 1000,
    "output": "The facts are present and right, so the answer is correct.",
    "messages": [],
}))
PY
REALGIT=$(command -v git)
printf '#!/bin/sh\necho "git $*" >> "$BK_GITLOG"\nexec %s "$@"\n' "$REALGIT" > "$WORK/bin/git"
chmod +x "$WORK/bin/git"

BK_OUT="$WORK/out.txt"; BK_ERR="$WORK/err.txt"; BK_GITLOG="$WORK/gitlog.txt"
export BK_OUT BK_ERR BK_GITLOG
run() {  # $1 label, rest = argv after `-m bantamkit.criticreplay`
  L=$1; shift
  : > "$BK_GITLOG"
  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
    PATH="$WORK/bin:$PATH" \
    /bin/sh -c '{ "$@" >"$BK_OUT" 2>"$BK_ERR"; echo "status=$?"; }' sh \
    "$PY" "$PROBE" "$@" > "$WORK/st.txt"
  TB=no; grep -q '^Traceback' "$BK_ERR" && TB=yes
  printf '%s|%s|%s|%s|%s|%s\n' "$L" "$(sed -n 's/^status=//p' "$WORK/st.txt")" \
    "$(wc -c < "$BK_OUT" | tr -d ' ')" \
    "$(grep -c 'git show' "$BK_GITLOG" | tr -d ' ')" "$TB" \
    "$(head -1 "$BK_ERR" | cut -c1-72)"
  cd "$REPO" || exit 1
}
OK="--base-url http://x --model fake-14b --transcripts $WORK/transcripts"

cd "$REPO" || exit 1
echo 'case|status|stdout_bytes|git_show_calls|traceback|first stderr line'
run 'D1 two --rubric on disk sharing a label' --rubric "a=$WORK/r1.yaml" --rubric "a=$WORK/r2.yaml" $OK
run 'D2 two git: --rubric sharing a label'    --rubric "a=$GITSPEC" --rubric "a=$GITSPEC" $OK
run 'D3 three sharing two labels'             --rubric "a=$WORK/r1.yaml" --rubric "a=$WORK/r2.yaml" --rubric "b=$WORK/r1.yaml" --rubric "b=$WORK/r2.yaml" $OK
# Controls. These must NOT move: distinct labels still run, and a shape error in one of a
# duplicated pair is still reported by the rule that owns it.
run 'D4 CONTROL distinct labels, git+disk'    --rubric "a=$GITSPEC" --rubric "b=$WORK/r2.yaml" $OK
run 'D5 CONTROL duplicate label, one malformed' --rubric "a=$WORK/r1.yaml" --rubric "a=" $OK
run 'D6 CONTROL one --rubric that is not on disk' --rubric "a=$WORK/nope.yaml" $OK
run 'D7 CONTROL empty --transcripts, distinct labels' --rubric "a=$WORK/r1.yaml" --base-url http://x --model fake-14b --transcripts "$WORK/emptydir"
