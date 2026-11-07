#!/usr/bin/env bash
#
# tools/release/test_run_lanes.sh -- the concurrent verify lanes in publish.sh (#293).
#
# Phase 6 verifies npm and PyPI at once through `run_lanes`. A real publish cannot be rerun to
# test it, so the lane runner is read OUT OF publish.sh (the bytes that run, as
# test_version_map.sh does) and driven with stand-in lanes that sleep, fail and spawn children.
#
#   bash tools/release/test_run_lanes.sh     # exit 0 and "PASS n" when every case holds

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLISH="${PUBLISH_SH:-$SCRIPT_DIR/publish.sh}"

DEFS="$(mktemp -d)"
trap 'rm -rf "$DEFS"' EXIT
{
  for fn in say ok bad stop_lanes run_lanes; do
    body="$(awk -v fn="$fn" '$0 ~ "^"fn"\\(\\)" {on=1} on {print} on && (/^}/ || /^[a-z_]+\(\) +\{.*\}$/) {exit}' "$PUBLISH")"
    if [ -z "$body" ]; then
      printf 'FAIL  %s() is not defined in %s\n' "$fn" "$PUBLISH" >&2
      exit 1
    fi
    printf '%s\n' "$body"
  done
  printf 'LANE_PIDS=""\n'
} >"$DEFS/lanes.sh"

PASS=0
FAIL=0
check() { # description, condition-exit-status
  if [ "$2" -eq 0 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); printf 'FAIL  %s\n' "$1" >&2; fi
}

# Each case runs in a fresh bash so one case's traps and globals cannot leak into the next.
run_case() { # script body -> stdout+stderr of a bash that sourced the lane runner
  bash -c "set -euo pipefail; source '$DEFS/lanes.sh'; cleanup() { :; }; trap cleanup EXIT; LANE_HEARTBEAT_S=1000; W='$DEFS'; $1" 2>&1
}

# 1. The lanes run AT ONCE: two 3 s lanes end in well under the 6 s a sequence would take.
start=$SECONDS
out="$(run_case 'a() { sleep 3; echo A-done; }; b() { sleep 3; echo B-done; }
  run_lanes "lane-a" a "$W/a.log" "lane-b" b "$W/b.log"; echo "failed=[$LANES_FAILED]"')"
took=$((SECONDS - start))
check "two 3 s lanes took ${took}s, not concurrent" "$([ "$took" -lt 5 ]; echo $?)"
check "both lanes verified" "$(printf '%s' "$out" | grep -q 'ok      lane-a verified' && printf '%s' "$out" | grep -q 'ok      lane-b verified'; echo $?)"
check "no lane failed" "$(printf '%s' "$out" | grep -qx 'failed=\[\]'; echo $?)"
check "each lane's log is printed" "$(printf '%s' "$out" | grep -q '^A-done$' && printf '%s' "$out" | grep -q '^B-done$'; echo $?)"

# 2. One failing lane does not stop the other, and LANES_FAILED names only the failure.
out="$(run_case 'fast_fail() { echo "boom"; exit 1; }; slow_ok() { sleep 2; echo survived > "$W/marker"; }
  run_lanes "npm" fast_fail "$W/f.log" "PyPI" slow_ok "$W/s.log"; echo "failed=[$LANES_FAILED]"')"
check "the slow lane ran to the end after the other failed" "$([ "$(cat "$DEFS/marker" 2>/dev/null)" = survived ]; echo $?)"
check "LANES_FAILED is exactly the failed lane" "$(printf '%s' "$out" | grep -qx 'failed=\[npm\]'; echo $?)"
check "the failure is reported with its exit status" "$(printf '%s' "$out" | grep -q 'FAILED  npm (exit 1)'; echo $?)"
check "the failed lane's log is printed" "$(printf '%s' "$out" | grep -q '^boom$'; echo $?)"

# 3. A lane that dies through `die`-style `exit 1` mid-function is a failure, not a hang; two
#    failures are both named, in the order they ended.
out="$(run_case 'f1() { exit 1; }; f2() { sleep 1; exit 3; }
  run_lanes "first" f1 "$W/1.log" "second" f2 "$W/2.log"; echo "failed=[$LANES_FAILED]"')"
check "both failures named in finish order" "$(printf '%s' "$out" | grep -qx 'failed=\[first, second\]'; echo $?)"
check "a non-1 exit status is reported as itself" "$(printf '%s' "$out" | grep -q 'FAILED  second (exit 3)'; echo $?)"

# 4. Logs are printed in the order lanes FINISH, whole, never interleaved.
out="$(run_case 'slow() { echo slow-1; sleep 2; echo slow-2; }; fast() { echo fast-1; echo fast-2; }
  run_lanes "slow" slow "$W/sl.log" "fast" fast "$W/fa.log"')"
order="$(printf '%s\n' "$out" | grep -E '^(slow|fast)-[12]$' | tr '\n' ' ')"
check "fast lane's whole log before slow lane's (got: $order)" "$([ "$order" = 'fast-1 fast-2 slow-1 slow-2 ' ]; echo $?)"

# 5. The heartbeat names the lanes still running.
out="$(run_case 'LANE_HEARTBEAT_S=1; q() { :; }; l() { sleep 3; }
  run_lanes "quick" q "$W/q.log" "long" l "$W/l.log"')"
check "heartbeat names the lane still running" "$(printf '%s' "$out" | grep -q 'still verifying after [0-9]*s: long$'; echo $?)"

# 6. An interrupt ends every lane AND the children a lane spawned (a lane is a process group),
#    then the script's own cleanup still runs.
rm -f "$DEFS/child.pid" "$DEFS/cleaned"
bash -c "set -euo pipefail; source '$DEFS/lanes.sh'; cleanup() { touch '$DEFS/cleaned'; }; trap cleanup EXIT
  LANE_HEARTBEAT_S=1000
  spawner() { sleep 60 & echo \$! > '$DEFS/child.pid'; wait; }
  idle() { sleep 60; }
  run_lanes 'spawner' spawner '$DEFS/sp.log' 'idle' idle '$DEFS/id.log'" >/dev/null 2>&1 &
runner=$!
for _ in $(seq 1 50); do [ -s "$DEFS/child.pid" ] && break; sleep 0.1; done
child="$(cat "$DEFS/child.pid" 2>/dev/null || true)"
check "the stand-in lane spawned its child" "$([ -n "$child" ]; echo $?)"
kill -TERM "$runner"
wait "$runner" 2>/dev/null || true
sleep 0.5
check "the lane's own child is gone after TERM" "$( [ -n "$child" ] && ! kill -0 "$child" 2>/dev/null; echo $?)"
check "cleanup still ran after TERM" "$([ -e "$DEFS/cleaned" ]; echo $?)"
[ -n "$child" ] && kill "$child" 2>/dev/null || true

# 7. A real Ctrl-C: SIGINT to the runner's whole process group while the main loop sleeps.
#    `&` from a non-interactive shell starts the runner with SIGINT IGNORED, which would make
#    this pass for the wrong reason, so perl resets it to default and gives the runner its own
#    group before exec.
rm -f "$DEFS/child.pid" "$DEFS/cleaned"
perl -e '$SIG{INT}="DEFAULT"; setpgrp(0,0); exec @ARGV' bash -c "set -euo pipefail; source '$DEFS/lanes.sh'; cleanup() { touch '$DEFS/cleaned'; }; trap cleanup EXIT
  LANE_HEARTBEAT_S=1000
  spawner() { sleep 60 & echo \$! > '$DEFS/child.pid'; wait; }
  idle() { sleep 60; }
  run_lanes 'spawner' spawner '$DEFS/sp.log' 'idle' idle '$DEFS/id.log'" >/dev/null 2>&1 &
runner=$!
for _ in $(seq 1 50); do [ -s "$DEFS/child.pid" ] && break; sleep 0.1; done
child="$(cat "$DEFS/child.pid" 2>/dev/null || true)"
sleep 0.3
kill -INT -- "-$runner" 2>/dev/null || true
for _ in $(seq 1 50); do kill -0 "$runner" 2>/dev/null || break; sleep 0.1; done
check "the runner ended on SIGINT to its group" "$(! kill -0 "$runner" 2>/dev/null; echo $?)"
sleep 0.5
check "the lane's own child is gone after SIGINT" "$( [ -n "$child" ] && ! kill -0 "$child" 2>/dev/null; echo $?)"
check "cleanup still ran after SIGINT" "$([ -e "$DEFS/cleaned" ]; echo $?)"
[ -n "$child" ] && kill "$child" 2>/dev/null || true
kill -KILL -- "-$runner" 2>/dev/null || true

# 8. A lane that ENDS but leaves a child behind in its group: the child is stopped when the lane
#    is reaped, not left running after the scratch directory is gone.
rm -f "$DEFS/orphan.pid"
out="$(run_case 'leaver() { sleep 60 & echo $! > "$W/orphan.pid"; echo left; }
  run_lanes "leaver" leaver "$W/l.log"; echo "failed=[$LANES_FAILED]"')"
orphan="$(cat "$DEFS/orphan.pid" 2>/dev/null || true)"
sleep 0.3
check "the lane left a child to test against" "$([ -n "$orphan" ]; echo $?)"
check "the finished lane's leftover child is stopped" "$( [ -n "$orphan" ] && ! kill -0 "$orphan" 2>/dev/null; echo $?)"
[ -n "$orphan" ] && kill "$orphan" 2>/dev/null || true

printf 'PASS %d\n' "$PASS"
if [ "$FAIL" -gt 0 ]; then
  printf 'FAIL %d\n' "$FAIL" >&2
  exit 1
fi
