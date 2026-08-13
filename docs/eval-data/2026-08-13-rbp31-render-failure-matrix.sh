#!/bin/sh
# RB-P31 render-failure matrix — the runner that produced
# docs/eval-data/2026-08-13-rbp31-render-failure-matrix.md.
#
#   sh docs/eval-data/2026-08-13-rbp31-render-failure-matrix.sh "$PWD" /tmp/rbp31
#
# Layer: Measurement. Every status here is /bin/sh's own $?, echoed to a file on the
# side, in an environment with no PYTEST_* key in it — RB-P28 is open and a green run of
# the suite is not evidence about the shipped behaviour. Nothing is patched: the only
# substitution is cli_exit_status_probe.py's scripted critic, which is the shipped main()
# with the client constructor replaced.
set -u
REPO=$1; WORK=$2
PY="$REPO/.venv/bin/python"; PROBE="$REPO/runtime-py/tests/cli_exit_status_probe.py"
RUBRIC="$REPO/assets/rubrics/task-completion.yaml"
RO_FILE="$WORK/readonly-target"   # fd 1 is duped from THIS, opened O_RDONLY

mkrig() {  # $1 outdir  $2 cells  $3 clean|guard
  "$PY" - "$1" "$2" "$3" <<'PY'
import json, sys, pathlib
root = pathlib.Path(sys.argv[1]); n = int(sys.argv[2]); mode = sys.argv[3]
TASK = "recall-db-port"                      # a task in the FROZEN suite; read-only here
t = root / "transcripts"; t.mkdir(parents=True, exist_ok=True)
clean = "The answer is 42 because the sum of the parts equals it."
guard = "The facts are present and right, so the answer is correct."   # trips guard 2
for i in range(n):
    (t / f"critique--{TASK}--r{i}.json").write_text(json.dumps({
        "task": TASK, "config": "critique", "repeat": i, "passed": True,
        "outcome": "pass", "seed": 1000 + i,
        "output": guard if mode == "guard" else clean, "messages": [],
    }))
PY
}

# $1 label $2 cells $3 clean|guard $4 live|epipe|ebadf-file|ebadf-devnull|closed $5 ok|unwritable
cell() {
  L=$1; N=$2; RIG=$3; MODE=$4; SUM=$5
  D="$WORK/$L"; rm -rf "$D"; mkdir -p "$D"; mkrig "$D" "$N" "$RIG"
  if [ "$SUM" = unwritable ]; then mkdir -p "$D/ro"; chmod 555 "$D/ro"
    S_LIVE="$D/ro/live.json"; S_DARK="$D/ro/dark.json"
  else S_LIVE="$D/live.json"; S_DARK="$D/dark.json"; fi

  # (a) the SAME argv with a live reader on stdout: the control the dark run is diffed
  #     against, so "it measured" is a claim about bytes and not about an exit code.
  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
    BK_OUT="$D/table.txt" /bin/sh -c '{ "$@" >"$BK_OUT"; echo "status=$?" >&2; }' sh \
    "$PY" "$PROBE" --base-url http://x --model fake-14b --rubric "before=$RUBRIC" \
    --transcripts "$D/transcripts" --json "$D/live.jsonl" --summary "$S_LIVE" 2>"$D/live.err"
  LIVE_STATUS=$(sed -n 's/^status=//p' "$D/live.err")
  TBYTES=$(wc -c < "$D/table.txt" | tr -d ' ')

  # (b) the dark run: same argv, stdout broken in the named way, stderr always live
  set -- "$PY" "$PROBE" --base-url http://x --model fake-14b --rubric "before=$RUBRIC" \
      --transcripts "$D/transcripts" --json "$D/dark.jsonl" --summary "$S_DARK"
  case $MODE in
    live)  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
             /bin/sh -c '{ "$@" >/dev/null; echo "status=$?" >&2; }' sh "$@" 2>"$D/dark.err" ;;
    epipe) env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
             /bin/sh -c '{ "$@"; echo "status=$?" >&2; } | true' sh "$@" 2>"$D/dark.err" ;;
    ebadf-file) env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
             /bin/sh -c '{ "$@"; echo "status=$?" >&2; } 1>&0' sh "$@" <"$RO_FILE" 2>"$D/dark.err" ;;
    ebadf-devnull) env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
             /bin/sh -c '{ "$@"; echo "status=$?" >&2; } 1>&0' sh "$@" </dev/null 2>"$D/dark.err" ;;
    closed) env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
             /bin/sh -c '{ "$@"; echo "status=$?" >&2; } 1>&-' sh "$@" 2>"$D/dark.err" ;;
  esac
  STATUS=$(sed -n 's/^status=//p' "$D/dark.err")
  ROWS=$(wc -l < "$D/dark.jsonl" 2>/dev/null | tr -d ' '); [ -z "$ROWS" ] && ROWS=MISSING
  if [ -f "$S_DARK" ]; then SUMM=$(wc -c < "$S_DARK" | tr -d ' '); else SUMM=MISSING; fi
  JIDENT=no; SIDENT=no
  cmp -s "$D/dark.jsonl" "$D/live.jsonl" 2>/dev/null && JIDENT=yes
  if [ "$SUM" = unwritable ]; then
    [ ! -f "$S_DARK" ] && [ ! -f "$S_LIVE" ] && SIDENT="both-absent"
  else
    cmp -s "$S_DARK" "$S_LIVE" 2>/dev/null && SIDENT=yes
  fi
  RAISED=$(grep -o 'line 19[0-9][0-9], in main' "$D/dark.err" | tail -1)
  EXC=$(grep -E '^(OSError|AttributeError|BrokenPipeError)' "$D/dark.err" | head -1)
  IGN=no; grep -q 'Exception ignored' "$D/dark.err" && IGN=yes
  printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s ignored=%s\n' \
    "$MODE" "$N" "$TBYTES" "$RIG/$SUM" "$LIVE_STATUS" "$STATUS" "$ROWS" "$SUMM" \
    "$JIDENT" "$SIDENT" "$RAISED" "$EXC" "$IGN"
  [ "$SUM" = unwritable ] && chmod 755 "$D/ro" 2>/dev/null
  return 0
}

mkdir -p "$WORK"; printf 'read-only target\n' > "$RO_FILE"
# The axis. CPython gives fd 1 a BufferedWriter of os.fstat(1).st_blksize bytes, so
# "larger than stdout's buffer" is a property of WHAT FD 1 IS, not of this tool.
"$PY" - "$RO_FILE" <<'PY'
import io, os, sys
sys.stderr.write("io.DEFAULT_BUFFER_SIZE=%d\n" % io.DEFAULT_BUFFER_SIZE)
sys.stderr.write("st_blksize(regular file)=%d\n" % os.stat(sys.argv[1]).st_blksize)
sys.stderr.write("st_blksize(/dev/null)=%d\n" % os.stat("/dev/null").st_blksize)
r, w = os.pipe(); sys.stderr.write("st_blksize(pipe)=%d\n" % os.fstat(w).st_blksize)
PY
echo 'mode|cells|table_bytes|earned_rig|live_status|dark_status|rows|summary_bytes|jsonl_identical|summary_identical|raised_at|exception'
for MODE in live epipe ebadf-file ebadf-devnull closed; do
  for N in 1 120 250; do
    cell "$MODE-n$N-clean"  "$N" clean "$MODE" ok
    cell "$MODE-n$N-guard"  "$N" guard "$MODE" ok
    cell "$MODE-n$N-unwrit" "$N" clean "$MODE" unwritable
  done
done
