#!/bin/sh
# K4B/C1 — a stdout whose CODEC cannot represent the table, and the number a real shell
# reads. The runner that produced
# docs/eval-data/2026-08-13-k4b-c1-stdout-encoding-matrix.md.
#
#   sh docs/eval-data/2026-08-13-k4b-c1-stdout-encoding-matrix.sh "$PWD" /tmp/k4b-c1
#
# To reproduce the BEFORE column, put the pre-fix module back and run it again:
#
#   git checkout 3981efd -- runtime-py/src/bantamkit/criticreplay.py
#   sh docs/eval-data/2026-08-13-k4b-c1-stdout-encoding-matrix.sh "$PWD" /tmp/k4b-c1-before
#   git checkout HEAD -- runtime-py/src/bantamkit/criticreplay.py
#
# Layer: Measurement. Every status is /bin/sh's own $?, echoed on a stream of its own, in
# an environment with no PYTEST_* key in it — RB-P28 is open and a green run of the suite
# is not evidence about the shipped behaviour. Nothing is patched: the only substitution
# is cli_exit_status_probe.py's scripted critic, which is the shipped main() with the
# client constructor replaced, and PYTHONIOENCODING is read by CPython while it builds
# sys.stdout, before any line of this module runs.
set -u
REPO=$1; WORK=$2
PY="$REPO/.venv/bin/python"; PROBE="$REPO/runtime-py/tests/cli_exit_status_probe.py"
RUBRIC="$REPO/assets/rubrics/task-completion.yaml"

mkrig() {  # $1 outdir  $2 cells
  "$PY" - "$1" "$2" <<'PY'
import json, sys, pathlib
root = pathlib.Path(sys.argv[1]); n = int(sys.argv[2])
TASK = "recall-db-port"                      # a task in the FROZEN suite; read-only here
t = root / "transcripts"; t.mkdir(parents=True, exist_ok=True)
guard = "The facts are present and right, so the answer is correct."   # trips guard 2
for i in range(n):
    (t / f"critique--{TASK}--r{i}.json").write_text(json.dumps({
        "task": TASK, "config": "critique", "repeat": i, "passed": True,
        "outcome": "pass", "seed": 1000 + i, "output": guard, "messages": [],
    }))
PY
}

# $1 label  $2 cells  $3 encoding  $4 plain|hatch|unwritable
cell() {
  L=$1; N=$2; ENC=$3; RUNG=$4
  D="$WORK/$L"; rm -rf "$D"; mkdir -p "$D"; mkrig "$D" "$N"
  EXTRA=""; S_LIVE="$D/live.json"; S_DARK="$D/dark.json"
  case $RUNG in
    hatch)      EXTRA="--violations-exit-zero" ;;
    unwritable) printf 'a file where a directory has to be\n' > "$D/blocker"
                S_LIVE="$D/blocker/live.json"; S_DARK="$D/blocker/dark.json" ;;
  esac

  # (a) the control: the SAME argv on a live UTF-8 stdout. The dark run's artifacts are
  #     diffed against these, so "it measured" is a claim about bytes, not an exit code.
  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
    PYTHONIOENCODING=utf-8 BK_OUT="$D/table.txt" \
    /bin/sh -c '{ "$@" >"$BK_OUT"; echo "status=$?" >&2; }' sh \
    "$PY" "$PROBE" --base-url http://x --model fake-14b --rubric "before=$RUBRIC" \
    --transcripts "$D/transcripts" --json "$D/live.jsonl" --summary "$S_LIVE" $EXTRA \
    2>"$D/live.err"
  LIVE_STATUS=$(sed -n 's/^status=//p' "$D/live.err")
  TBYTES=$(wc -c < "$D/table.txt" | tr -d ' ')

  # (b) the dark run: same argv, stdout wrapped in a codec that cannot take the table.
  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
    PYTHONIOENCODING="$ENC" BK_OUT="$D/dark.txt" \
    /bin/sh -c '{ "$@" >"$BK_OUT"; echo "status=$?" >&2; }' sh \
    "$PY" "$PROBE" --base-url http://x --model fake-14b --rubric "before=$RUBRIC" \
    --transcripts "$D/transcripts" --json "$D/dark.jsonl" --summary "$S_DARK" $EXTRA \
    2>"$D/dark.err"
  STATUS=$(sed -n 's/^status=//p' "$D/dark.err")
  OBYTES=$(wc -c < "$D/dark.txt" | tr -d ' ')
  ROWS=$(wc -l < "$D/dark.jsonl" 2>/dev/null | tr -d ' '); [ -z "$ROWS" ] && ROWS=MISSING
  JIDENT=no; cmp -s "$D/dark.jsonl" "$D/live.jsonl" && JIDENT=yes
  SIDENT=no
  if [ "$RUNG" = unwritable ]; then
    [ ! -f "$S_DARK" ] && [ ! -f "$S_LIVE" ] && SIDENT="both-absent"
  else
    cmp -s "$S_DARK" "$S_LIVE" && SIDENT=yes
  fi
  TB=no; grep -q '^Traceback' "$D/dark.err" && TB=yes
  # Did this module's own report reach stderr AS WRITTEN? backslashreplace escapes rather
  # than raises, so "the bytes are ASCII" is not the question - "COMPLETE:" is.
  SENT=no; grep -q 'The measurement is COMPLETE: the JSONL rows' "$D/dark.err" && SENT=yes
  NONASCII=$(LC_ALL=C grep -c '[^ -~	]' "$D/dark.err" | tr -d ' ')
  printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
    "$ENC" "$N" "$TBYTES" "$RUNG" "$LIVE_STATUS" "$STATUS" "$OBYTES" "$ROWS" \
    "$JIDENT" "$SIDENT" "$TB" "$SENT/$NONASCII"
  return 0
}

mkdir -p "$WORK"
"$PY" -c 'import sys; sys.stderr.write("python=%s\n" % sys.version.split()[0])'
echo 'encoding|cells|table_bytes|rung|live_status|dark_status|stdout_bytes|rows|jsonl_identical|summary_identical|traceback|report_as_written/non_ascii_lines'
for ENC in utf-8 latin-1 ascii; do
  for N in 1 40; do
    for RUNG in plain hatch unwritable; do
      cell "$ENC-n$N-$RUNG" "$N" "$ENC" "$RUNG"
    done
  done
done
