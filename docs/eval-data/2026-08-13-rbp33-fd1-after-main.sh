#!/bin/sh
# RB-P33 — what a process's fd 1 and its `sys.stdout` ARE once `main()` has handled a
# lost stdout. The runner that produced
# docs/eval-data/2026-08-13-rbp33-fd1-after-main.md.
#
#   sh docs/eval-data/2026-08-13-rbp33-fd1-after-main.sh "$PWD" /tmp/rbp33
#
# To reproduce the BEFORE column — the `os.dup2(devnull, 1)` recovery v0.19.0 shipped —
# put that module back and run it again:
#
#   git checkout 5538624 -- runtime-py/src/bantamkit/criticreplay.py
#   sh docs/eval-data/2026-08-13-rbp33-fd1-after-main.sh "$PWD" /tmp/rbp33-before
#   git checkout HEAD -- runtime-py/src/bantamkit/criticreplay.py
#
# Layer: Measurement. RB-P33 is the one claim in this contract a SHELL cannot read: it is
# about what an IN-PROCESS caller sees after `main` returns, and `main` is exported in
# `__all__` precisely so callers can do that. So the driver calls `main` in-process, and
# every fact it reports is read from the process itself — `os.fstat(1)` against the fd
# that was installed, a real write to `sys.stdout`, and a real child that inherits fd 1 —
# never from a return value and never from a mock. The environment carries no PYTEST_*
# key, because RB-P28 is open and a green suite is not evidence about shipped behaviour.
set -u
REPO=$1; WORK=$2
PY="$REPO/.venv/bin/python"
RUBRIC="$REPO/assets/rubrics/task-completion.yaml"

mkdir -p "$WORK"; printf 'read-only target\n' > "$WORK/readonly-target"

cat > "$WORK/driver.py" <<'PY'
"""Call the shipped `main()` with a doomed fd 1, then ask the PROCESS what is left."""
import json
import os
import subprocess
import sys

from bantamkit import criticreplay
from bantamkit.client import Message, Response, Usage


class _Scripted:  # the only substitution, as in cli_exit_status_probe.py
    def __init__(self, model="fake-14b"):
        self.model = model
        self.seed = None
        self._response_format_unsupported = False

    def chat(self, messages, tools=None, response_format=None):
        return Response(
            message=Message(
                role="assistant",
                content=json.dumps({"reasoning": "r", "score": 9, "feedback": "f"}),
            ),
            usage=Usage(100, 20),
        )


mode, work, rubric = sys.argv[1], sys.argv[2], sys.argv[3]
root = os.path.join(work, "rig-" + mode)
transcripts = os.path.join(root, "transcripts")
os.makedirs(transcripts, exist_ok=True)
for i in range(2):
    with open(os.path.join(transcripts, "critique--recall-db-port--r%d.json" % i), "w") as f:
        json.dump({
            "task": "recall-db-port", "config": "critique", "repeat": i,
            "passed": True, "outcome": "pass", "seed": 1000 + i,
            "output": "The answer is 42 because the sum of the parts equals it.",
            "messages": [],
        }, f)

report = os.path.join(work, "report-" + mode + ".txt")  # neither fd 1 nor fd 2

if mode == "epipe":
    read_end, write_end = os.pipe()
    os.close(read_end)  # the reader is gone BEFORE the first byte; no race to lose
    doomed = write_end
else:
    doomed = os.open(os.path.join(work, "readonly-target"), os.O_RDONLY)
installed = os.fstat(doomed)
os.dup2(doomed, 1)
os.close(doomed)

criticreplay.OpenAICompatible = lambda **kw: _Scripted(kw.get("model", "fake-14b"))
try:
    criticreplay.main([
        "--base-url", "http://x", "--model", "fake-14b",
        "--rubric", "before=" + rubric, "--transcripts", transcripts,
        "--json", os.path.join(root, "rows.jsonl"),
        "--summary", os.path.join(root, "summary.json"),
    ])
    status = "0 (returned)"
except SystemExit as e:
    status = str(e.code if isinstance(e.code, int) else 0)
except BaseException as e:  # noqa: BLE001 - what ESCAPED main is the finding
    status = "ESCAPED %s" % type(e).__name__

now = os.fstat(1)
same = "yes" if (now.st_dev, now.st_ino) == (installed.st_dev, installed.st_ino) else "NO"
try:
    sys.stdout.write("a caller's write after main\n")
    sys.stdout.flush()
    nxt = "SILENT SUCCESS"
except BaseException as e:  # noqa: BLE001 - the class is the answer
    nxt = "raises %s" % type(e).__name__
child = subprocess.run(  # noqa: S603 - fd 1 is inherited on purpose; that IS the measurement
    ["/bin/sh", "-c", "echo a child that inherited fd 1"], stderr=subprocess.DEVNULL, check=False
).returncode
rows = os.path.join(root, "rows.jsonl")
wrote = sum(1 for _ in open(rows)) if os.path.exists(rows) else "MISSING"
with open(report, "w") as f:
    f.write("%s|%s|%s|%s|%s|%s\n" % (mode, status, same, nxt, child, wrote))
PY

echo 'mode|status|fd1_is_the_fd_installed|next_write_to_sys_stdout|child_sh_returncode|jsonl_rows'
for MODE in epipe ebadf; do
  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
    "$PY" "$WORK/driver.py" "$MODE" "$WORK" "$RUBRIC" 2>"$WORK/driver-$MODE.err"
  cat "$WORK/report-$MODE.txt" 2>/dev/null || echo "$MODE|DRIVER FAILED, see $WORK/driver-$MODE.err"
done
