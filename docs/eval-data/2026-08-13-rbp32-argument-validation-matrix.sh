#!/bin/sh
# RB-P32 argument-validation matrix — the runner that produced
# docs/eval-data/2026-08-13-rbp32-argument-validation-matrix.md.
#
#   sh docs/eval-data/2026-08-13-rbp32-argument-validation-matrix.sh "$PWD" /tmp/rbp32
#
# Layer: Measurement. Every status is /bin/sh's own $?, with no PYTEST_* key in the
# child's environment. No probe and no scripted critic: not one case below reaches a
# client, so this runs the SHIPPED `-m bantamkit.criticreplay` end to end.
set -u
REPO=$1; WORK=$2
PY="$REPO/.venv/bin/python"
RUBRIC="$REPO/assets/rubrics/task-completion.yaml"
mkdir -p "$WORK/emptydir"
printf 'not a rubric at all\n' > "$WORK/notrubric.yaml"
printf 'name: x\nthreshold: 5\nprompt: "no slots here"\nschema: {}\n' > "$WORK/noslots.yaml"

BK_OUT="$WORK/out.txt"; BK_ERR="$WORK/err.txt"; export BK_OUT BK_ERR
run() {  # $1 label, rest = argv after `-m bantamkit.criticreplay`
  L=$1; shift
  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
    /bin/sh -c '{ "$@" >"$BK_OUT" 2>"$BK_ERR"; echo "status=$?"; }' sh \
    "$PY" -m bantamkit.criticreplay "$@" > "$WORK/st.txt"
  printf '%s|%s|%s|%s\n' "$L" "$(sed -n 's/^status=//p' "$WORK/st.txt")" \
    "$(wc -c < "$BK_OUT" | tr -d ' ')" "$(head -1 "$BK_ERR" | cut -c1-90)"
}
OK="--base-url http://x --model m --transcripts $WORK/emptydir"

echo 'case|status|stdout_bytes|first stderr line'
# --- A. argparse's own parsing, before any line of this module runs ---
run 'A1 unknown flag'                 --not-a-flag
run 'A2 missing required --base-url'  --rubric "a=$RUBRIC" --transcripts "$WORK/emptydir" --model m
run 'A3 missing required --rubric'    --base-url http://x --model m --transcripts "$WORK/emptydir"
run 'A4 --replays abc (type=int)'     --rubric "a=$RUBRIC" $OK --replays abc
run 'A5 --timeout abc (type=float)'   --rubric "a=$RUBRIC" $OK --timeout abc
run 'A6 --identity-replays abc'       --rubric "a=$RUBRIC" $OK --identity-replays abc
run 'A7 --guard nope (choices)'       --rubric "a=$RUBRIC" $OK --guard nope
run 'A8 --model with no value'        --rubric "a=$RUBRIC" --base-url http://x --transcripts "$WORK/emptydir" --model
# --- B. this module's own validation, via its ONE parser.error call site (:1897) ---
run 'B1 --replays 0'                  --rubric "a=$RUBRIC" $OK --replays 0
run 'B2 --replays -3'                 --rubric "a=$RUBRIC" $OK --replays -3
run 'B3 --identity-replays 0'         --rubric "a=$RUBRIC" $OK --identity-replays 0
# --- C. this module's own validation, inside main's try, via PerturbationError ---
run 'C1 --rubric SPEC (no LABEL=)'    --rubric "$RUBRIC" $OK
run 'C2 --rubric =SPEC (empty label)' --rubric "=$RUBRIC" $OK
run 'C3 --rubric LABEL= (empty spec)' --rubric 'a=' $OK
run 'C4 --rubric a=git:HEAD'          --rubric 'a=git:HEAD' $OK
run 'C5 --rubric missing file'        --rubric "a=$WORK/nope.yaml" $OK
run 'C6 --rubric not a rubric'        --rubric "a=$WORK/notrubric.yaml" $OK
run 'C7 --rubric no {task}/{output}'  --rubric "a=$WORK/noslots.yaml" $OK
run 'C8 --rubric git bad ref'         --rubric 'a=git:no-such-ref:x.yaml' $OK
run 'C9 --manifest missing'           --rubric "a=$RUBRIC" $OK --manifest "$WORK/nope.yaml"
run 'C10 --transcripts missing dir'   --rubric "a=$RUBRIC" --base-url http://x --model m --transcripts "$WORK/nodir"
run 'C11 --transcripts empty dir'     --rubric "a=$RUBRIC" $OK
run 'C12 --task names no task'        --rubric "a=$RUBRIC" $OK --task nope
