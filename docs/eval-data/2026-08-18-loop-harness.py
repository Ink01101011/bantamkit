"""The J7 loop harness: drive a local worker through a real repair task, and count.

U2 of job `compaction-in-the-loop`. The bar is
`docs/eval-data/2026-08-18-loop-bar-preregistration.md`, committed at `c323664`
BEFORE this file existed. Nothing here may amend it; a number that seems to
demand a bar change is an escalation, not an edit.

WHAT THIS IS
    Bar section 7(1): "There is no harness. Nothing in bantamkit drives an agent
    loop over ollama against a foreign worktree." This is that harness, and the
    SAME driving route serves every arm -- one flag differs between rungs, never
    the route.

WHAT IT DOES NOT DO
  * It writes NOTHING unless `--write PATH` is given (RB-P49: two committed field
    programs overwrite their own committed .jsonl under a bare invocation and
    exit 0. Here the read-only mode is the default and the destructive one is
    flagged).
  * It never commits, stages, pushes or tags anything in the workload repo. It
    restores the worktree with `git checkout -f -- .` plus `git clean -fd`,
    neither of which writes an object or moves a ref.
  * It reports no token count and no duration it did not read off the endpoint.
    Every token figure is ollama's own `prompt_eval_count` / `eval_count` from
    `/api/generate`; every duration is either ollama's own nanosecond field or a
    monotonic clock around the HTTP call, and says which.

THE ROUTE, NAMED BESIDE EVERY TOKEN FIGURE (invariant 14, as U1 corrected it)
    WORKER  -> `POST /api/generate`, field `prompt_eval_count`. U1 measured this
               is a TRUE TOTAL and is unaffected by KV caching (4,124 -> 4,124 on
               an identical re-send, +4 per appended line).
    SUMMARIZER (B1+, not this unit's arm) -> the mechanism's own
               `POST /v1/chat/completions`, field `usage.prompt_tokens`, which is
               CLAMPED TO THE WINDOW and is never a prompt size (RB-P53). The
               output-side detector in `clamp_verdict` below treats
               `usage.prompt_tokens == num_ctx` as VOID.

CANON-1, AND THE ONE PLACE THIS FILE COULD NOT APPLY THE BAR AS WRITTEN
    Bar section 10.4 says CANON-1 is applied "to every tool output before it
    enters the agent's context", and its rule (b) sorts "the lines preceding the
    first ` FAIL ` header". A file READ has no ` FAIL ` header, so the literal
    reading sorts the whole file, and an agent that can only see sorted source
    cannot repair it -- the task would be unreachable for an instrument reason
    and every arm would tie at 0/6 (bar section 6 U-3). The alternative reading,
    "no header means nothing to sort", contradicts bar section 2.4's own measured
    row, where the PASSING oracle output -- which has no ` FAIL ` header either --
    goes from 3 distinct sha to 1 under CANON-1.
    The two readings cannot both hold. This file therefore records the scope it
    used in `canon_id` on every row, applies all three rules to ORACLE output
    (the case section 2.4 measured), and applies rule (a) only to READ and LIST
    output -- where rule (a) was MEASURED to be a no-op: zero matches for all
    three of its patterns across all 22 implementation files at the pinned
    commit. The contradiction is reported to the orchestrator as escalation-class
    and is not resolved here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request

RULE = "=" * 78

ENDPOINT = "http://127.0.0.1:11434"
# The real packnplan checkout, ONLY ever read from: the two node_modules
# symlinks point into it. Never committed to, never staged, never dirtied.
REAL_REPO = os.environ.get("J7_REAL_REPO", "")

# ---------------------------------------------------------------- declared config
# Bar section 10.6. Frozen there; quoted here, never chosen here.
WORKLOAD_COMMIT = "81ac1a10e2230661ce10745a3a64f4da1d3819f2"
MCP_COMMIT = "0a15cff65c5c847af07b43de3b67d726433a4ca3"
WORKER_MODEL = "qwen2.5:7b-instruct"
WORKER_TEMPERATURE = 0.0
WORKER_SEED = 7
WORKER_NUM_CTX = 32768
SUMMARIZER_MODEL = "bk-j7-qwen2.5-14b-ctx32768"
SUMMARIZER_NUM_CTX = 32768
SUMMARIZER_BLOB = (
    "sha256-2049f5674b1e92b4464e5729975c9689fcfbf0b0e4443ccf10b5339f370f9a54"
)
TOKEN_BUDGET = 32768
PROACTIVE_PCT = 60
T_BOUNDARY = TOKEN_BUDGET * PROACTIVE_PCT // 100  # 19660, bar section 10.2
TURN_CAP = 40
RUN_CAP_S = 20 * 60
DEFECT_SET_ID = "DEFECT-SET-5"
TRIGGER_ID = "T=19660/prompt_eval_count/preceding-call"
CANON_ID = "CANON-1/oracle-full+read-rule-a"
NUM_PREDICT = 2048

# Bar section 1.2, table. Each verified to occur exactly once at the pinned commit.
DEFECT_SET_5 = [
    ("D1", "src/expense/split/split.ts", "/ 10000n;", "/ 1000n;"),
    (
        "D2",
        "src/expense/settle/settle.ts",
        "const pay = d.amt < c.amt ? d.amt : c.amt;",
        "const pay = d.amt < c.amt ? c.amt : d.amt;",
    ),
    ("D3", "src/date/date.ts", "return value.slice(0, 10);", "return value.slice(0, 8);"),
    ("D4", "src/trip/travelMode/travelMode.ts", "distanceKm < 1.5", "distanceKm <= 1.5"),
    (
        "D5",
        "src/place/openingHours/openingHours.ts",
        "if (candidate >= openMinutes && candidate < closeMinutes) return true;",
        "if (candidate > openMinutes && candidate < closeMinutes) return true;",
    ),
]

# Bar section 1.2, verbatim. Fixed now, identical in every arm.
TASK = (
    "`packages/shared` has failing tests. Make the package's test suite pass. "
    "Do not edit any `*.test.ts` file."
)

# Bar section 10.6: "the agent gets exactly: read a file, write a file, list
# files, run the ORACLE. A different roster is a different experiment."
PREAMBLE = f"""You are repairing a TypeScript package. Work inside `packages/shared`.

TASK: {TASK}

You act by emitting EXACTLY ONE action, then the line @@END. You will then be
shown the result and asked for the next action. Never emit two actions at once.
Never write anything after @@END.

The four actions, and nothing else exists:

LIST <dir>
@@END

READ <file>
@@END

WRITE <file>
<<<
the complete new contents of the file
>>>
@@END

ORACLE
@@END

DONE
@@END

Paths are relative to `packages/shared`, e.g. `src/date/date.ts`.
ORACLE runs the package's test suite and shows you its output.
WRITE replaces the whole file, so emit the whole file.
DONE ends the run; emit it only when ORACLE reports every test passing.
"""


# ------------------------------------------------------------------------ CANON-1
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
DUR = re.compile(r"\b\d+(?:\.\d+)?m?s\b")
TS = re.compile(r"\b\d{2}:\d{2}:\d{2}\b")
IDX = re.compile(r"\[\d+/\d+\]")
FAIL_HEADER = " FAIL "


def canon_rule_a(text: str) -> str:
    """Rule (a): scrub durations, HH:MM:SS timestamps and [k/N] failure indices."""
    t = ANSI.sub("", text)
    t = DUR.sub("<DUR>", t)
    t = TS.sub("<TS>", t)
    t = IDX.sub("[<K>/<N>]", t)
    return t


def canon1(text: str) -> str:
    """CANON-1 in full: rule (a), then (b) sort the lines before the first
    ` FAIL ` header, then (c) sort the ` FAIL ` blocks by their header line."""
    lines = canon_rule_a(text).split("\n")
    first = next((i for i, ln in enumerate(lines) if FAIL_HEADER in ln), None)
    if first is None:
        return "\n".join(sorted(lines))
    head = sorted(lines[:first])
    rest = lines[first:]
    blocks: list[list[str]] = []
    cur = [rest[0]]
    for ln in rest[1:]:
        if FAIL_HEADER in ln:
            blocks.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    blocks.append(cur)
    blocks.sort(key=lambda b: b[0])
    return "\n".join(head + [ln for b in blocks for ln in b])


# ------------------------------------------------------------------------ endpoint
def ollama_version() -> str:
    with urllib.request.urlopen(ENDPOINT + "/api/version", timeout=10) as r:
        return json.loads(r.read().decode())["version"]


def generate(model: str, prompt: str, *, temperature: float, seed: int | None,
             num_ctx: int, num_predict: int, stop: list[str] | None = None,
             timeout: float = 1800) -> dict:
    """One worker call. `/api/generate` -- the route whose `prompt_eval_count` U1
    measured to be an honest total."""
    options: dict = {
        "temperature": temperature,
        "num_ctx": num_ctx,
        "num_predict": num_predict,
    }
    if seed is not None:
        options["seed"] = seed
    if stop:
        options["stop"] = stop
    payload = json.dumps(
        {"model": model, "prompt": prompt, "stream": False, "options": options}
    ).encode()
    req = urllib.request.Request(
        ENDPOINT + "/api/generate", data=payload,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())
    wall = time.monotonic() - t0
    text = body.get("response", "")
    return {
        "route": "/api/generate",
        "response": text,
        "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "prompt_eval_count": body.get("prompt_eval_count"),
        "eval_count": body.get("eval_count"),
        "prompt_eval_duration_ns": body.get("prompt_eval_duration"),
        "eval_duration_ns": body.get("eval_duration"),
        "load_duration_ns": body.get("load_duration"),
        "total_duration_ns": body.get("total_duration"),
        "wall_s": round(wall, 3),
        "done_reason": body.get("done_reason"),
    }


def chat_v1(model: str, prompt: str, *, max_tokens: int = 8,
            temperature: float = 0.2) -> dict:
    """The mechanism's OWN route. Its `usage.prompt_tokens` is the clamped
    counter of RB-P53 and is only ever read through `clamp_verdict`."""
    payload = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": prompt}],
         "max_tokens": max_tokens, "temperature": temperature, "stream": False}
    ).encode()
    req = urllib.request.Request(
        ENDPOINT + "/v1/chat/completions", data=payload,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=1800) as resp:
        body = json.loads(resp.read().decode())
    return {
        "route": "/v1/chat/completions",
        "usage": body.get("usage"),
        "finish_reason": body["choices"][0].get("finish_reason"),
        "wall_s": round(time.monotonic() - t0, 3),
    }


def clamp_verdict(usage_prompt_tokens: int | None, num_ctx: int) -> str:
    """Bar section 6 U-6 declaration 2, from the OUTPUT side: a reported prompt
    size exactly equal to the window is a clamp, never a token count."""
    if usage_prompt_tokens is None:
        return "UNMEASURED"
    return "VOID-CLAMPED" if usage_prompt_tokens == num_ctx else "OK"


# ------------------------------------------------------------------------ worktree
def git(wt: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", wt, *args], capture_output=True,
                          text=True, check=check)


SHARED = "packages/shared"
NODE_LINKS = ("node_modules", SHARED + "/node_modules")


def restore(wt: str, real_repo: str | None = None) -> None:
    """Back to the pinned tree. `checkout -f -- .` and `clean -fd` write no object
    and move no ref.

    MEASURED, and NOT what the bar assumed: `git clean -fd` DELETES the two
    `node_modules` SYMLINKS the worktree is given, even though `-x` is absent and
    even though `node_modules` is in the workload's `.gitignore`. A `.gitignore`
    directory pattern does not match a symlink, so the links are plain untracked
    files to `clean`. They are therefore excluded by name and re-created if
    absent -- otherwise the second repeat of every arm has no oracle at all."""
    git(wt, "checkout", "-f", "--", ".")
    git(wt, "clean", "-fd", "-q", "-e", "node_modules",
        "-e", SHARED + "/node_modules")
    if real_repo:
        for rel in NODE_LINKS:
            link = os.path.join(wt, rel)
            if not os.path.exists(link):
                os.symlink(os.path.join(real_repo, rel), link)


def apply_defects(wt: str) -> list[str]:
    """Bar section 6 U-5(5): if any pattern does not occur exactly once, VOID."""
    problems = []
    for did, rel, a, b in DEFECT_SET_5:
        path = os.path.join(wt, "packages/shared", rel)
        with open(path, encoding="utf-8") as fh:
            t = fh.read()
        n = t.count(a)
        if n != 1:
            problems.append(f"{did}:{rel}: pattern occurs {n} times, expected 1")
            continue
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(t.replace(a, b))
    return problems


def run_oracle(wt: str) -> tuple[int, str]:
    cwd = os.path.join(wt, SHARED)
    # Bar section 1.3 declares the command as `./node_modules/.bin/vitest run`
    # from `packages/shared`. Python resolves a RELATIVE executable against the
    # PARENT's cwd, not the child's, so the same binary is named absolutely.
    p = subprocess.run([os.path.join(cwd, "node_modules/.bin/vitest"), "run"],
                       check=False, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def run_guard_t(wt: str) -> int:
    cwd = os.path.join(wt, SHARED)
    p = subprocess.run([os.path.join(wt, "node_modules/.bin/tsc"), "--noEmit"],
                       check=False, cwd=cwd, capture_output=True, text=True)
    return p.returncode


def guard_tamper(wt: str) -> list[str]:
    p = git(wt, "diff", "--name-only", WORKLOAD_COMMIT, "--",
            "packages/shared/**/*.test.ts")
    return [ln for ln in p.stdout.splitlines() if ln.strip()]


def guard_scope(wt: str) -> list[str]:
    p = git(wt, "diff", "--name-only", WORKLOAD_COMMIT)
    return [ln for ln in p.stdout.splitlines() if ln.strip()]


DEFECT_PATHS = {SHARED + "/" + rel for _, rel, _, _ in DEFECT_SET_5}


# ------------------------------------------------------------------------ the tools
SAFE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _resolve(wt: str, rel: str) -> str | None:
    if not rel or not SAFE.match(rel) or ".." in rel.split("/"):
        return None
    base = os.path.realpath(os.path.join(wt, SHARED))
    full = os.path.realpath(os.path.join(base, rel))
    if not (full == base or full.startswith(base + os.sep)):
        return None
    return full


def tool_list(wt: str, arg: str) -> str:
    full = _resolve(wt, arg or ".")
    if full is None or not os.path.isdir(full):
        return f"ERROR: not a directory: {arg}"
    out = []
    for root, dirs, files in os.walk(full):
        dirs[:] = sorted(d for d in dirs if d != "node_modules")
        rel = os.path.relpath(root, os.path.join(wt, SHARED))
        for f in sorted(files):
            out.append(os.path.normpath(os.path.join(rel, f)))
    return "\n".join(out) if out else "(empty)"


def tool_read(wt: str, arg: str) -> str:
    full = _resolve(wt, arg)
    if full is None or not os.path.isfile(full):
        return f"ERROR: not a file: {arg}"
    with open(full, encoding="utf-8") as fh:
        return fh.read()


def tool_write(wt: str, arg: str, content: str) -> str:
    full = _resolve(wt, arg)
    if full is None:
        return f"ERROR: bad path: {arg}"
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(content)
    return f"OK: wrote {len(content)} bytes to {arg}"


ACTION_RE = re.compile(r"^(LIST|READ|WRITE|ORACLE|DONE)(?:[ \t]+(.*))?$")


def parse_action(text: str) -> tuple[str, str, str] | None:
    """First recognised action at line start wins. Returns (verb, arg, body)."""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        m = ACTION_RE.match(ln.strip())
        if not m:
            continue
        verb, arg = m.group(1), (m.group(2) or "").strip()
        if verb != "WRITE":
            return verb, arg, ""
        rest = lines[i + 1:]
        try:
            s = next(j for j, x in enumerate(rest) if x.strip() == "<<<")
        except StopIteration:
            return verb, arg, ""
        try:
            e = next(j for j, x in enumerate(rest[s + 1:]) if x.strip() == ">>>")
        except StopIteration:
            e = len(rest[s + 1:])
        return verb, arg, "\n".join(rest[s + 1:s + 1 + e])
    return None


# ------------------------------------------------------------------------- the loop
def render(blocks: list[dict]) -> str:
    parts = [PREAMBLE]
    for b in blocks:
        if b["kind"] == "action":
            parts.append(f"\n--- ACTION {b['n']} ---\n{b['text']}\n@@END")
        elif b["kind"] == "result":
            parts.append(f"\n--- RESULT {b['n']} ---\n{b['text']}")
        else:  # summary, for B1+
            parts.append(f"\n--- SUMMARY OF EARLIER WORK ---\n{b['text']}")
    parts.append("\n--- ACTION {n} ---\n".format(n=len(
        [b for b in blocks if b["kind"] == "action"]) + 1))
    return "".join(parts)


def run_one(wt: str, arm: str, repeat: int, *, verbose: bool = False) -> dict:
    """One (arm, repeat). B0 = `compact-off`: the full orchestration with
    `context_compact` never called (bar section 3.1). Boundaries are COUNTED in
    every arm and ACTED ON in none of them here -- U3 runs the ladder."""
    restore(wt, REAL_REPO)
    problems = apply_defects(wt)
    if problems:
        return {"arm": arm, "repeat": repeat, "outcome": "VOID",
                "void_reason": "oracle-baseline-drift: " + "; ".join(problems)}

    blocks: list[dict] = []
    calls: list[dict] = []
    boundaries = 0
    prev_prompt_eval = 0
    t0 = time.monotonic()
    stopped_by = None
    timeout_exc = ""
    action_texts: list[str] = []

    for turn in range(1, TURN_CAP + 1):
        if time.monotonic() - t0 > RUN_CAP_S:
            stopped_by = "run-cap"
            break
        # Bar section 10.2: the boundary fires on the first worker call at which
        # the run's live context, measured by `prompt_eval_count` on the
        # IMMEDIATELY PRECEDING call, reaches T.
        if prev_prompt_eval >= T_BOUNDARY:
            boundaries += 1
            # arm B0 never calls context_compact; the count is still recorded.
        prompt = render(blocks)
        # Bar section 10.6 declares "run cap 20 minutes wall-clock per run ->
        # exceeding it is VOID". Checked only BETWEEN calls it cannot fire, because
        # a single worker call past the window costs minutes; the remaining budget
        # is therefore the HTTP timeout, so the declared cap is the one that binds.
        remaining = RUN_CAP_S - (time.monotonic() - t0)
        try:
            r = generate(WORKER_MODEL, prompt,
                         temperature=WORKER_TEMPERATURE, seed=WORKER_SEED,
                         num_ctx=WORKER_NUM_CTX, num_predict=NUM_PREDICT,
                         stop=["@@END"], timeout=remaining)
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            stopped_by = "run-cap"
            timeout_exc = f"{type(exc).__name__}: {exc}"
            break
        r["turn"] = turn
        r["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
        r["prompt_bytes"] = len(prompt.encode())
        r["boundary_before_this_call"] = prev_prompt_eval >= T_BOUNDARY
        calls.append(r)
        prev_prompt_eval = r["prompt_eval_count"] or 0

        action_text = r["response"].strip()
        action_texts.append(action_text)
        blocks.append({"kind": "action", "n": turn, "text": action_text})
        parsed = parse_action(action_text)
        if verbose:
            head = action_text.split("\n")[0][:70]
            print(f"      t{turn:02d} pe={r['prompt_eval_count']} "
                  f"ev={r['eval_count']} {r['wall_s']}s :: {head}", flush=True)

        if parsed is None:
            result = ("ERROR: no action recognised. Emit exactly one of "
                      "LIST/READ/WRITE/ORACLE/DONE followed by @@END.")
            canon = CANON_ID + "/error"
        else:
            verb, arg, body = parsed
            if verb == "DONE":
                stopped_by = "done"
                break
            if verb == "LIST":
                result = canon_rule_a(tool_list(wt, arg))
                canon = "rule-a"
            elif verb == "READ":
                result = canon_rule_a(tool_read(wt, arg))
                canon = "rule-a"
            elif verb == "WRITE":
                result = canon_rule_a(tool_write(wt, arg, body))
                canon = "rule-a"
            else:
                code, out = run_oracle(wt)
                result = canon1(out) + f"\n(exit code {code})"
                canon = "canon-1-full"
        blocks.append({"kind": "result", "n": turn, "text": result,
                       "canon": canon})
    else:
        stopped_by = "turn-cap"

    wall = time.monotonic() - t0
    oracle_exit, oracle_out = run_oracle(wt)
    guard_t = run_guard_t(wt)
    tampered = guard_tamper(wt)
    scope = guard_scope(wt)
    outside = [p for p in scope if p not in DEFECT_PATHS]

    if tampered:
        outcome = "FAIL-TAMPERED"
    elif stopped_by == "run-cap":
        outcome = "VOID"
    elif oracle_exit == 0 and guard_t != 0:
        outcome = "FAIL-TYPE"
    elif oracle_exit == 0 and guard_t == 0:
        outcome = "PASS"
    elif stopped_by == "turn-cap":
        outcome = "FAIL-CAP"
    else:
        outcome = "FAIL"

    # The prompt stream, canonicalised, is what D-2 compares (bar section 2.5).
    stream = "\n\x00\n".join(
        [c["prompt_sha256"] for c in calls] + action_texts
    )
    return {
        "arm": arm, "repeat": repeat,
        "worker_model": WORKER_MODEL, "summarizer_model": SUMMARIZER_MODEL,
        "summarizer_num_ctx": SUMMARIZER_NUM_CTX, "worker_num_ctx": WORKER_NUM_CTX,
        "temperature": WORKER_TEMPERATURE, "seed": WORKER_SEED,
        "compaction_mode": "off" if arm == "compact-off" else "store",
        "recall_mode": "lexical", "mcp_commit": MCP_COMMIT,
        "workload_commit": WORKLOAD_COMMIT, "defect_set_id": DEFECT_SET_ID,
        "trigger_id": TRIGGER_ID, "canon_id": CANON_ID,
        "worker_route": "/api/generate",
        "oracle_exit": oracle_exit, "guard_type_exit": guard_t,
        "guard_tamper_files": tampered, "outcome": outcome,
        "stopped_by": stopped_by,
        "context_tokens_sent": sum(c["prompt_eval_count"] or 0 for c in calls),
        "eval_tokens_total": sum(c["eval_count"] or 0 for c in calls),
        "prompt_eval_duration_ns": sum(c["prompt_eval_duration_ns"] or 0
                                       for c in calls),
        "eval_duration_ns": sum(c["eval_duration_ns"] or 0 for c in calls),
        "load_duration_ns_max": max((c["load_duration_ns"] or 0 for c in calls),
                                    default=0),
        "worker_calls": len(calls),
        "max_prompt_eval_count": max((c["prompt_eval_count"] or 0 for c in calls),
                                     default=0),
        "boundaries": boundaries,
        "first_boundary_turn": next(
            (c["turn"] for c in calls if c["boundary_before_this_call"]), None),
        # Bar section 10.2 justified num_ctx = 32768 by arithmetic: "the ceiling
        # (25,900 + the task prompt, ~27k) fits, so no truncation occurs". That
        # arithmetic is over a trajectory that reads every file once and runs the
        # oracle once. This column reports whether the REALISED trajectory stayed
        # under the window, from the output side, per run.
        "worker_window_reached": max(
            (c["prompt_eval_count"] or 0 for c in calls), default=0) >= WORKER_NUM_CTX,
        "summarizer_input_tokens": 0 if arm == "compact-off" else None,
        "summarizer_output_tokens": 0 if arm == "compact-off" else None,
        "summarizer_clamped": [],
        "summary_chars": 0, "block_chars": sum(len(b["text"]) for b in blocks),
        "canon_stream_sha256": hashlib.sha256(stream.encode()).hexdigest(),
        "files_touched_outside_defect_set": outside,
        "void_reason": "" if outcome != "VOID" else (
            f"run-cap ({RUN_CAP_S}s) {timeout_exc}".strip()),
        "wall_s": round(wall, 3),
        "oracle_tail": canon1(oracle_out).split("\n")[-6:],
        "calls": [{k: v for k, v in c.items() if k != "response"} for c in calls],
    }


# ----------------------------------------------------------------- sub-commands
def cmd_check_oracle(args) -> int:
    wt = args.worktree
    print(RULE)
    print("ORACLE BASELINE -- bar section 1.3 and section 6 U-5(5)")
    print(RULE)
    restore(wt, REAL_REPO)
    code, out = run_oracle(wt)
    tail = [ln for ln in canon_rule_a(out).split("\n") if "Test Files" in ln
            or ln.strip().startswith("Tests")]
    print(f"  pristine  ORACLE exit={code}  {' | '.join(t.strip() for t in tail)}")
    print(f"  pristine  GUARD-T exit={run_guard_t(wt)}")
    ok_pristine = code == 0
    problems = apply_defects(wt)
    if problems:
        print("  PATTERN CHECK FAILED: " + "; ".join(problems))
        return 1
    print(f"  {DEFECT_SET_ID}: all 5 patterns occurred exactly once")
    code2, out2 = run_oracle(wt)
    tail2 = [ln for ln in canon_rule_a(out2).split("\n") if "Test Files" in ln
             or ln.strip().startswith("Tests")]
    print(f"  defected  ORACLE exit={code2}  {' | '.join(t.strip() for t in tail2)}")
    print(f"  defected  GUARD-T exit={run_guard_t(wt)}")
    print(f"  GUARD-TAMPER: {guard_tamper(wt) or 'empty'}")
    print(f"  GUARD-SCOPE : {len(guard_scope(wt))} files")
    restore(wt, REAL_REPO)
    ok = ok_pristine and code2 == 1
    print(f"\n  VERDICT: {'baseline holds' if ok else 'BASELINE DRIFT -> VOID'}")
    return 0 if ok else 1


def cmd_canon(args) -> int:
    """CANON-1's own self-test, and the measurement that rule (a) is a no-op on
    source. Runs the oracle N times in each state and counts distinct sha."""
    wt = args.worktree
    print(RULE)
    print("CANON-1 -- bar section 2.4 / 10.4")
    print(RULE)
    for state in ("passing", "failing"):
        restore(wt, REAL_REPO)
        if state == "failing":
            apply_defects(wt)
        raw, canon = set(), set()
        for _ in range(args.repeats):
            _, out = run_oracle(wt)
            raw.add(hashlib.sha256(out.encode()).hexdigest())
            canon.add(hashlib.sha256(canon1(out).encode()).hexdigest())
        print(f"  {state:8s} raw {len(raw)} distinct of {args.repeats}   "
              f"CANON-1 {len(canon)} distinct of {args.repeats}")
    restore(wt, REAL_REPO)
    src = os.path.join(wt, SHARED, "src")
    impl, hits = 0, 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for f in files:
            if f.endswith(".ts") and not f.endswith(".test.ts"):
                impl += 1
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    t = fh.read()
                hits += len(DUR.findall(t)) + len(TS.findall(t)) + len(IDX.findall(t))
    print(f"\n  rule (a) on the {impl} implementation files: {hits} matches "
          f"of all three patterns combined")
    print("  (a no-op on READ output, measured -- not assumed)")
    return 0


def cmd_d1(args) -> int:
    """D-1, bar section 2.5: identical prompt bytes + identical sampling options
    + identical load state must give identical completion bytes. Checked FIRST,
    on the ACTUAL worker configuration, at the declared repeat count."""
    print(RULE)
    print("D-1 MODEL DETERMINISM -- required; failure is VOID")
    print(f"  {WORKER_MODEL}  temp={WORKER_TEMPERATURE} seed={WORKER_SEED} "
          f"num_ctx={WORKER_NUM_CTX}  route=/api/generate  repeats={args.repeats}")
    print(RULE)
    # The prompt is the harness's OWN turn-1 prompt: D-1 measured off the axis
    # that matters would be D-1 measured on the wrong prompt.
    prompt = render([])
    rows = []
    for i in range(args.repeats):
        r = generate(WORKER_MODEL, prompt, temperature=WORKER_TEMPERATURE,
                     seed=WORKER_SEED, num_ctx=WORKER_NUM_CTX,
                     num_predict=NUM_PREDICT, stop=["@@END"])
        rows.append(r)
        print(f"    r{i} sha={r['response_sha256'][:12]} "
              f"prompt_eval={r['prompt_eval_count']} eval={r['eval_count']} "
              f"load_ns={r['load_duration_ns']} wall={r['wall_s']}s", flush=True)
    shas = {r["response_sha256"] for r in rows}
    evals = {r["eval_count"] for r in rows}
    pes = {r["prompt_eval_count"] for r in rows}
    ok = len(shas) == 1 and len(evals) == 1 and len(pes) == 1
    print(f"\n  distinct response sha256 : {len(shas)}")
    print(f"  distinct eval_count       : {len(evals)}")
    print(f"  distinct prompt_eval_count: {len(pes)}")
    print(f"  D-1: {'HOLDS' if ok else 'FAILS -> the run is VOID'}")
    if args.write:
        with open(args.write, "w", encoding="utf-8") as fh:
            json.dump({"check": "D-1", "model": WORKER_MODEL, "rows": rows}, fh,
                      indent=2)
        print(f"  wrote {args.write}")
    return 0 if ok else 1


def cmd_window(args) -> int:
    """The window fix, proven from the OUTPUT side: a prompt longer than the old
    window must come back with a `prompt_tokens` that is NOT the window."""
    print(RULE)
    print("THE WINDOW -- bar section 6 U-6, RB-P53. Route /v1/chat/completions.")
    print(RULE)
    filler = "".join(
        f"Line {i}: a floor and the statistic it gates share a grain.\n"
        for i in range(args.lines))
    prompt = ("Below is a log. Reply with the single word OK.\n\n" + filler
              + "\nReply with the single word OK.")
    print(f"  prompt bytes: {len(prompt.encode())}")
    honest = generate(WORKER_MODEL, prompt, temperature=0.0, seed=7,
                      num_ctx=WORKER_NUM_CTX, num_predict=4)
    print(f"  /api/generate on {WORKER_MODEL}: prompt_eval_count="
          f"{honest['prompt_eval_count']}  (the honest counter, for scale)")
    for model, ctx in ((args.base, 4096), (args.derived, SUMMARIZER_NUM_CTX)):
        r = chat_v1(model, prompt)
        pt = (r["usage"] or {}).get("prompt_tokens")
        print(f"  {model:32s} usage.prompt_tokens={pt} "
              f"finish={r['finish_reason']} wall={r['wall_s']}s "
              f"-> {clamp_verdict(pt, ctx)}")
    return 0


def cmd_clamp(args) -> int:
    """RB-P53 one route over. The bar (section 10.3) and invariant 14 both name
    `/api/generate`'s `prompt_eval_count` as THE honest counter and `/v1`'s
    `usage.prompt_tokens` as the clamped one. This measures both counters at
    several windows on ONE fixed prompt, from the OUTPUT side.

    The disagreement input that makes this not a tautology (RB-P47): a prompt
    that FITS. If the two counters only ever agreed with the window they would be
    two transcriptions of one rule; at a window the prompt fits inside, an honest
    counter must report the prompt and a clamped one must report the prompt too.
    The rule is therefore tested where it can be false."""
    filler = "".join(
        f"Line {i}: a floor and the statistic it gates share a grain.\n"
        for i in range(args.lines))
    prompt = ("Below is a log. Reply with the single word OK.\n\n" + filler
              + "\nReply with the single word OK.")
    print(RULE)
    print("COUNTER CLAMP -- both routes, one prompt, several windows")
    print(f"  prompt bytes: {len(prompt.encode())}   model: {args.model}")
    print(RULE)
    print("  route                  num_ctx   reported   == window?  verdict")
    for ctx in args.windows:
        r = generate(args.model, prompt, temperature=0.0, seed=7,
                     num_ctx=ctx, num_predict=2)
        n = r["prompt_eval_count"]
        print(f"  /api/generate          {ctx:7d}   {n:8d}   "
              f"{'YES' if n == ctx else 'no':10s}  {clamp_verdict(n, ctx)}"
              f"   ({r['wall_s']}s)")
    for model, ctx in ((args.base, 4096), (args.derived, SUMMARIZER_NUM_CTX)):
        r = chat_v1(model, prompt)
        n = (r["usage"] or {}).get("prompt_tokens")
        print(f"  /v1/chat/completions   {ctx:7d}   {n:8d}   "
              f"{'YES' if n == ctx else 'no':10s}  {clamp_verdict(n, ctx)}"
              f"   ({r['wall_s']}s)  [{model}]")
    return 0


def cmd_run(args) -> int:
    wt = args.worktree
    print(RULE)
    print(f"ARM {args.arm}  repeats={args.repeats}  worker={WORKER_MODEL} "
          f"T={T_BOUNDARY}")
    print(f"mode: {'write ' + args.write if args.write else '--- (writes nothing)'}")
    print(RULE)
    rows = []
    for rep in range(args.repeats):
        print(f"  repeat {rep}", flush=True)
        row = run_one(wt, args.arm, rep, verbose=True)
        rows.append(row)
        print(f"    -> outcome={row['outcome']} oracle_exit={row['oracle_exit']} "
              f"calls={row['worker_calls']} ctx_tokens={row['context_tokens_sent']} "
              f"max_pe={row['max_prompt_eval_count']} "
              f"boundaries={row['boundaries']} wall={row['wall_s']}s", flush=True)
        if args.write:
            with open(args.write, "w", encoding="utf-8") as fh:
                fh.writelines(json.dumps(r) + "\n" for r in rows)
    restore(wt, REAL_REPO)
    print("\n" + RULE)
    print("SUMMARY")
    for r in rows:
        print(f"  r{r['repeat']}  {r['outcome']:14s} calls={r['worker_calls']:3d} "
              f"ctx={r['context_tokens_sent']:7d} max_pe={r['max_prompt_eval_count']:6d} "
              f"boundaries={r['boundaries']}  stream_sha="
              f"{r.get('canon_stream_sha256', '')[:12]}")
    streams = {r.get("canon_stream_sha256") for r in rows}
    print(f"\n  D-2 (prompt-stream determinism): {len(streams)} distinct of "
          f"{len(rows)} -> {'HOLDS' if len(streams) == 1 else 'FAILS -> VOID'}")
    reached = sum(1 for r in rows if r.get("boundaries", 0) >= 1)
    print(f"  boundaries >= 1 in {reached} of {len(rows)} repeats "
          f"(bar section 6 U-2 floor: 4 of 6)")
    print(f"  max prompt_eval_count over all repeats: "
          f"{max((r['max_prompt_eval_count'] for r in rows), default=0)} "
          f"against T={T_BOUNDARY}")
    if args.write:
        print(f"\n  wrote {args.write}")
    return 0


def cmd_d2(args) -> int:
    with open(args.rows, encoding="utf-8") as fh:
        rows = [json.loads(ln) for ln in fh if ln.strip()]
    streams = {}
    for r in rows:
        streams.setdefault(r["canon_stream_sha256"], []).append(r["repeat"])
    print(RULE)
    print(f"D-2 PROMPT-STREAM DETERMINISM of {args.rows}")
    print(RULE)
    for sha, reps in streams.items():
        print(f"  {sha[:16]}  repeats {reps}")
    ok = len(streams) == 1
    print(f"\n  {len(streams)} distinct of {len(rows)} -> "
          f"{'D-2 HOLDS' if ok else 'D-2 FAILS -> VOID'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    wt_default = os.environ.get("J7_WORKTREE", "")

    p = sub.add_parser("check-oracle")
    p.add_argument("--worktree", default=wt_default, required=not wt_default)
    p.set_defaults(fn=cmd_check_oracle)

    p = sub.add_parser("canon")
    p.add_argument("--worktree", default=wt_default, required=not wt_default)
    p.add_argument("--repeats", type=int, default=3)
    p.set_defaults(fn=cmd_canon)

    p = sub.add_parser("d1")
    p.add_argument("--repeats", type=int, default=6)
    p.add_argument("--write", default=None)
    p.set_defaults(fn=cmd_d1)

    p = sub.add_parser("window")
    p.add_argument("--lines", type=int, default=1200)
    p.add_argument("--base", default="qwen2.5:14b-instruct")
    p.add_argument("--derived", default=SUMMARIZER_MODEL)
    p.set_defaults(fn=cmd_window)

    p = sub.add_parser("clamp")
    p.add_argument("--lines", type=int, default=1200)
    p.add_argument("--model", default=WORKER_MODEL)
    p.add_argument("--windows", type=int, nargs="+", default=[2048, 8192, 32768])
    p.add_argument("--base", default="qwen2.5:14b-instruct")
    p.add_argument("--derived", default=SUMMARIZER_MODEL)
    p.set_defaults(fn=cmd_clamp)

    p = sub.add_parser("run")
    p.add_argument("--worktree", default=wt_default, required=not wt_default)
    p.add_argument("--arm", default="compact-off")
    p.add_argument("--repeats", type=int, default=6)
    p.add_argument("--write", default=None,
                   help="write rows as .jsonl. Absent = writes nothing.")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("d2")
    p.add_argument("--rows", required=True)
    p.set_defaults(fn=cmd_d2)

    args = ap.parse_args()
    if args.cmd in {"check-oracle", "canon", "run"} and not os.path.exists(
            os.path.join(args.worktree or "", ".git")):
        print("UNMEASURED -- --worktree must be a git worktree of the workload")
        return 2
    if args.cmd in {"d1", "window", "clamp", "run"}:
        try:
            print(f"ollama version {ollama_version()}   "
                  f"cmd: {shlex.join(sys.argv)}")
        except (urllib.error.URLError, OSError) as exc:
            print(f"UNMEASURED -- ollama endpoint unreachable: {exc}")
            return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
