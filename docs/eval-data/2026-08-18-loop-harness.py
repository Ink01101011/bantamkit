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
    THE OUTPUT SIDE OF THE SAME WINDOW -> `/api/generate`'s `done_reason`. A
               value of `length` means the runtime cut the COMPLETION at
               `num_predict`, and since the task says a WRITE replaces the whole
               file, a cut completion is a truncated file. Read in
               `length_stop_turns`, surfaced as the `length_stops` and
               `truncated_writes` columns, and ranked above FAIL in
               `classify_outcome` -- an instrument event is not an outcome.
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
# Scheduling slop when deciding whether the HTTP timeout that fired WAS the
# declared cap arriving, or an endpoint failure that happened to look like one.
CAP_TOL_S = 1.0
DEFECT_SET_ID = "DEFECT-SET-5"
TRIGGER_ID = "T=19660/prompt_eval_count/preceding-call"
CANON_ID = "CANON-1/oracle-full+read-rule-a+rule-d"
NUM_PREDICT = 2048

# Which arm ids mean `compaction_mode: off`. Named as a SET, not derived from a
# prefix: bar Amendment 2 A2.5 declares B0" (`compact-off-tamper-terminal`) with
# `compaction_mode` = `off`, and the row used to read `"off" if arm ==
# "compact-off" else "store"` -- which would have silently stamped the new arm
# `store` and put a false column on every B0" row. A future arm that is not on
# this list is stamped `store` and has to say so deliberately.
COMPACT_OFF_ARMS = frozenset({"compact-off", "compact-off-tamper-terminal"})

# N-18 (Critical C-2): which arms this program has actually IMPLEMENTED.
# `--arm` used to be free text with no `choices=`, and `compaction_mode` was
# derived from SET MEMBERSHIP OF THE LABEL -- so `run --arm compact-on` emitted
# six rows reading `compaction_mode: store`, with null summarizer columns and an
# `mcp_commit` pinning a mechanism `run_one` never calls, at exit 0. A label is
# not a behaviour. This tuple is the list of arms whose behaviour exists in this
# file, it is `choices=` for `--arm`, and `compaction_mode_for` raises on
# anything else rather than stamping a column.
#
# THE `store` BRANCH IS UNREACHABLE TODAY AND THAT IS THE FINDING, not an
# oversight: no compaction-ON arm is implemented, so no arm outside
# COMPACT_OFF_ARMS is on this list. Implementing B1 means calling
# `context_compact` AND adding the label here, in the same change.
IMPLEMENTED_ARMS = ("compact-off", "compact-off-tamper-terminal")


def compaction_mode_for(arm: str) -> str:
    """The `compaction_mode` column, and the refusal that stops a label becoming
    a measurement.

    Falsified in `selfcheck` (M8) against the arm label itself -- the datum the
    column is derived from -- not against a flag this harness sets."""
    if arm not in IMPLEMENTED_ARMS:
        raise ValueError(
            f"arm {arm!r} is not implemented in this harness. Implemented: "
            f"{', '.join(IMPLEMENTED_ARMS)}. A row for an unimplemented arm "
            f"would carry a `compaction_mode` derived from its LABEL and an "
            f"`mcp_commit` pinning a mechanism no code path calls.")
    return "off" if arm in COMPACT_OFF_ARMS else "store"


def boundaries_from_calls(calls: list[dict]) -> int:
    """The `boundaries` column, derived from the calls that HAPPENED.

    N-17: the count used to be an accumulator incremented at the TOP of the turn
    loop, BEFORE the worker call. A call that raised broke out of the loop and
    was never appended to `calls`, so the increment stood with no call behind it
    and every run that ended on the run cap or an endpoint error over-counted by
    exactly one. The six committed B0 rows carry the evidence against themselves:
    the scalar `boundaries` column and the sum of the row's own per-call
    `boundary_before_this_call` flags disagree by +1 on all six.

    A boundary is a property of a call that was made, so the scalar is now read
    off the same per-call flags the row already ships -- one transcription, not
    two that have to agree (RB-P47). Anyone can re-derive the column from the
    committed `calls` sub-array."""
    return sum(1 for c in calls if c["boundary_before_this_call"])

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


def canon1(text: str, *, rule_d: bool = True, rule_d_last_block_only: bool = False
           ) -> str:
    """CANON-1 in full: rule (a), then (b) sort the lines before the first
    ` FAIL ` header, then (c) sort the ` FAIL ` blocks by their header line,
    then (d) trailing-blank normalisation.

    RULE (d), bar Amendment 2 A2.1, verbatim: "After rules (a), (b) and (c),
    delete every trailing empty line from the head section and from each
    ` FAIL ` block, then re-join the blocks with exactly one empty line between
    consecutive blocks, and emit no trailing empty line at the end of the
    canonical text." Scope is ORACLE output only -- Amendment 1's scope,
    unchanged -- and it is defined by the same ` FAIL ` header that defines (b)
    and (c).

    WHY IT EXISTS, measured and not asserted: vitest terminates each
    `Failed Tests` block with a `[k/N]` separator and a blank line, and whichever
    block is printed LAST carries one EXTRA trailing blank. Print order follows
    test-file completion order and is nondeterministic; rule (c) then sorts the
    blocks, which RELOCATES that extra blank to wherever its owning block sorts.
    Same multiset of lines, same byte count, different index -- so neither (b)
    nor (c) absorbs it, and D-2 failed 6 of 6 in B0 because of it.

    `canon_id` carries the rule, so no row canonicalised under (d) is ever
    compared against a row canonicalised without it. The six committed B0 rows
    keep `CANON-1/oracle-full+read-rule-a` and are NOT re-canonicalised.

    The two keyword flags exist so `selfcheck` can falsify the rule against the
    real defect rather than against a second transcription of the rule (RB-P47):
    `rule_d=False` is CANON-1 as it stood, and `rule_d_last_block_only=True` is
    A2.1's declared falsifying mutation, which took the 14-run distinct count
    back from 1 to 3. Neither flag is reachable from the run path, which always
    takes the declared default.
    """
    lines = canon_rule_a(text).split("\n")
    first = next((i for i, ln in enumerate(lines) if FAIL_HEADER in ln), None)
    if first is None:
        out = sorted(lines)                                      # (b)
        if rule_d:
            while out and out[-1] == "":                         # (d), no-header
                out.pop()
        return "\n".join(out)
    head, rest = sorted(lines[:first]), lines[first:]            # (b)
    blocks: list[list[str]] = []
    cur = [rest[0]]
    for ln in rest[1:]:
        if FAIL_HEADER in ln:
            blocks.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    blocks.append(cur)
    blocks.sort(key=lambda b: b[0])                              # (c)
    if not rule_d:
        return "\n".join(head + [ln for b in blocks for ln in b])
    targets = blocks[-1:] if rule_d_last_block_only else blocks
    for b in targets:                                            # (d)
        while b and b[-1] == "":
            b.pop()
    while head and head[-1] == "":                               # (d)
        head.pop()
    body: list[str] = []
    for b in blocks:
        if body:
            body.append("")
        body.extend(b)
    return "\n".join(head + [""] + body)


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
    """Back to the pinned tree. `checkout -f -- .` and `clean -fdx` write no
    object and move no ref.

    MEASURED, and NOT what the bar assumed: `git clean -fd` DELETES the two
    `node_modules` SYMLINKS the worktree is given, even though `-x` is absent and
    even though `node_modules` is in the workload's `.gitignore`. A `.gitignore`
    directory pattern does not match a symlink, so the links are plain untracked
    files to `clean`. They are therefore excluded by name and re-created if
    absent -- otherwise the second repeat of every arm has no oracle at all.

    N-16, and the reason `-x` is now here: WITHOUT `-x`, `clean` uses the
    WORKLOAD's `.gitignore` as its exclusion list, so a reset between repeats
    preserves exactly what the workload chose to ignore. At `81ac1a1` that list
    contains `dist/` and `*.tsbuildinfo`, and `tsconfig.base.json` sets
    `composite: true` -- so build state written by repeat N survived into repeat
    N+1 and the repeats were not independent. Two consequences, both measured
    rather than argued: `guard_type_exit` reads `[2, 1, 1, 1, 1, 1]` on the six
    committed B0" rows while every content column of those rows is 1 distinct of
    6; and `tool_list` walks the worktree excluding only `node_modules`, so a
    `dist/` left by an earlier repeat is inside the AGENT's observation space.

    `-x` makes the exclusion list this function's own -- the two symlinks, by
    name -- instead of the workload's. It is a change to the RESET, not to the
    task, the roster, or any threshold, and it regenerates nothing: the committed
    rows of B0 and B0" stand as written. See
    `2026-08-19-loop-u5-closure-field-measurement.py`, section C-1."""
    git(wt, "checkout", "-f", "--", ".")
    git(wt, "clean", "-fdx", "-q", "-e", "node_modules",
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


# AMENDMENT TO BAR SECTION 1.3 (RB-P72). Section 1.3 pre-registered the oracle
# command as `./node_modules/.bin/vitest run` from `packages/shared`, with no
# `--config`, so vitest AUTO-DISCOVERED its configuration from that cwd -- and
# that cwd is the agent's write surface. One WRITE of `vitest.config.ts` there
# reaches `exit 0` with GUARD-TAMPER empty, GUARD-SCOPE unchanged and GUARD-T 0;
# measured beyond what RB-P72 records, `vitest.workspace.ts` and `vite.config.ts`
# do the same at 15 of 141 tests. The command is now that command PLUS
# `--config <this constant>`, naming a file in BANTAMKIT -- a different
# repository from the workload the roster can write, and a path `_resolve`
# cannot produce (`_resolve` never returns anything outside
# `realpath(<wt>/packages/shared)`).
#
# THE AMENDMENT BINDS RUNS MADE AFTER IT. It makes no claim about J7's committed
# arms: those rows ran under an unpinned oracle and always will have, no `.jsonl`
# is regenerated here, and RB-P72's "deliberately not fixed" disposition stands
# as J7's. This is an instrument change taking effect FORWARD, which is the one
# thing bar A2.8 item 2 does not forbid.
#
# The pin is checked, not asserted: selfcheck case M11.
ORACLE_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "2026-08-19-oracle.vitest.config.ts")


def oracle_argv(cwd: str) -> list[str]:
    """The oracle's argv, as a FUNCTION so M11 can read the pin without a run.

    `ORACLE_CONFIG` is absolute, and that is not tidiness: a RELATIVE `--config`
    is resolved against the CHILD's cwd, which is the write surface, and a pin
    that resolves inside the surface is not a pin. M11's second case is exactly
    that distinction and reddens on it."""
    return [os.path.join(cwd, "node_modules/.bin/vitest"), "run",
            "--config", ORACLE_CONFIG]


def run_oracle(wt: str) -> tuple[int, str]:
    cwd = os.path.join(wt, SHARED)
    # Bar section 1.3 declares the command as `./node_modules/.bin/vitest run`
    # from `packages/shared`. Python resolves a RELATIVE executable against the
    # PARENT's cwd, not the child's, so the same binary is named absolutely.
    #
    # ^ Left exactly as written, because it is the record of what section 1.3
    # declared and of why the binary is spelled the way it is. The amendment is
    # APPENDED, not folded in: the command is now that command PLUS
    # `--config ORACLE_CONFIG`, for the reasons in the block above the constant.
    p = subprocess.run(oracle_argv(cwd),
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

# Bar Amendment 2 A2.2: the pre-registered GUARD-TAMPER verdict of bar section
# 1.4 is evaluated at the moment its condition becomes true, rather than after
# the loop has exhausted the turn cap or the run cap. `guard_tamper` below stays
# the authority on the COLUMN -- it is `git diff` against the pinned commit, over
# the same `packages/shared/**/*.test.ts` pathspec -- and this constant is the
# same glob's tail, applied to a WRITE's RESOLVED path so the loop can stop at
# the write instead of discovering it 19 minutes later.
TAMPER_SUFFIX = ".test.ts"


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


def is_tamper_write(wt: str, arg: str) -> bool:
    """Does this WRITE's RESOLVED path match `packages/shared/**/*.test.ts`?

    Bar Amendment 2 A2.2. `_resolve` already guarantees containment inside
    `<wt>/packages/shared` or returns None, so the `packages/shared/**/` half of
    the glob is `_resolve` succeeding and the `*.test.ts` half is the suffix.
    A path `_resolve` rejects was never written and cannot have tampered.

    THIS DOES NOT REFUSE THE WRITE and it does not change the tool roster: bar
    section 10.6's four actions are unchanged and WRITE still writes. The caller
    performs the write, then asks this, then ends the run. What moved is WHEN
    the section 1.4 verdict is evaluated, never what the verdict is.
    """
    full = _resolve(wt, arg)
    return full is not None and full.endswith(TAMPER_SUFFIX)


ACTION_RE = re.compile(r"^(LIST|READ|WRITE|ORACLE|DONE)(?:[ \t]+(.*))?$")


def parse_action(text: str) -> tuple[str, str, str, str] | None:
    """First recognised action at line start wins.

    Returns `(verb, arg, body, incomplete)`. `incomplete` is the empty string
    when the action's body arrived whole, and otherwise NAMES the way it did
    not:

      `missing-open-fence`   a WRITE with no `<<<` at all -> body is empty, so
                             the file would be replaced with nothing.
      `missing-close-fence`  a WRITE whose `>>>` terminator never arrived ->
                             the body runs to the end of the completion, which
                             is what a `num_predict` cut looks like.

    Before this returned a 3-tuple and both cases were indistinguishable from a
    complete body (SHAPE-silent-truncation S5). `NUM_PREDICT` is 2048 and the
    task says a WRITE replaces the whole file, so a repair cut off by the output
    cap was written truncated, failed the oracle and scored FAIL -- an OUTCOME --
    where an instrument event should score VOID. The verdict now has a name that
    a reader can count; see `classify_outcome`.
    """
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        m = ACTION_RE.match(ln.strip())
        if not m:
            continue
        verb, arg = m.group(1), (m.group(2) or "").strip()
        if verb != "WRITE":
            return verb, arg, "", ""
        rest = lines[i + 1:]
        try:
            s = next(j for j, x in enumerate(rest) if x.strip() == "<<<")
        except StopIteration:
            return verb, arg, "", "missing-open-fence"
        try:
            e = next(j for j, x in enumerate(rest[s + 1:]) if x.strip() == ">>>")
            incomplete = ""
        except StopIteration:
            e = len(rest[s + 1:])
            incomplete = "missing-close-fence"
        return verb, arg, "\n".join(rest[s + 1:s + 1 + e]), incomplete
    return None


def length_stop_turns(calls: list[dict]) -> list[int]:
    """The turns at which the ENDPOINT said it stopped on the output cap.

    `/api/generate` returns `done_reason` and it is the only place the runtime
    admits an output-side truncation. Nothing compared it to anything before
    (`"length"` did not occur in this file at all), so a cut-off completion was
    indistinguishable from a model answer. Read off the endpoint's own field,
    never off a flag this harness sets for itself (RB-P48)."""
    return [c["turn"] for c in calls if c.get("done_reason") == "length"]


def classify_outcome(*, stopped_by: str | None, tampered: list,
                     oracle_exit: int, guard_t: int,
                     truncated_writes: list) -> str:
    """The outcome ladder, as a function so it can be falsified without a run.

    ORDER MATTERS AND IS THE BAR'S, NOT A PREFERENCE.

    1. `run-cap` / `endpoint-error` -> VOID. An INSTRUMENT verdict: bar
       section 6 U-5 discards the repeat and reports nothing from it, so a run
       that never terminated cannot also be scored FAIL-TAMPERED on the tree it
       left behind. `guard_tamper_files` is on the row either way, so a VOID
       that also tampered is still visible and is never lost.
    2. tamper, then the two oracle verdicts, unchanged. Bar Amendment 2 A2.2
       adds ONE arrival path to this rung and no rung: `stopped_by == "tamper"`
       means the loop already saw the WRITE that tampers and ended there, so the
       verdict does not have to be rediscovered from `git diff` afterwards. It
       is the same pre-registered `FAIL-TAMPERED` of bar section 1.4 either way,
       and on a tree the guard can still see, both conditions hold at once. The
       disjunct earns its keep only where they part: a WRITE to a `*.test.ts`
       path whose bytes happen to equal the pinned file's leaves `git diff`
       EMPTY, and A2.2 says such a run is `FAIL-TAMPERED` -- the agent wrote a
       test file, which is what section 1.2's task text forbids.
    3. `VOID-TRUNCATED` sits ABOVE `FAIL` and `FAIL-CAP` and BELOW `PASS`
       (SHAPE-silent-truncation S5). Above FAIL because a completion the output
       cap cut in half is an instrument event, not a model answer. Below PASS
       because the oracle is the authority on success: a truncation that still
       ends green did not corrupt the answer, and discarding that repeat would
       throw away a real measurement for a harmless event.
    """
    if stopped_by in ("run-cap", "endpoint-error"):
        return "VOID"
    if tampered or stopped_by == "tamper":
        return "FAIL-TAMPERED"
    if oracle_exit == 0 and guard_t != 0:
        return "FAIL-TYPE"
    if oracle_exit == 0 and guard_t == 0:
        return "PASS"
    if truncated_writes:
        return "VOID-TRUNCATED"
    if stopped_by == "turn-cap":
        return "FAIL-CAP"
    return "FAIL"


def classify_stop(elapsed: float, exc: BaseException) -> tuple[str, str]:
    """Which instrument event ended the run when the endpoint raised, and the
    exception string that names it. Pure: same inputs, same pair, no clock.

    THE FINDING THIS CLOSES, AND WHY IT IS NAMED HERE WITHOUT A NUMBER. The
    orchestrator's brief calls it N-12. That number is NOT free: the register in
    `2026-08-18-loop-harness-b0.md` defines N-12 as "S5's Critical had already
    fired when it was found" and N-13 as "the `d2` sub-command has no `--mutate`
    flag", and bar Amendment 2 A2.9 -- which exists to repair an N-12 collision
    -- resolves it by moving the provenance gap onto N-13, which is taken too.
    This finding has no definition site in the register under any number. It is
    therefore described rather than numbered, and the collision is reported to
    the orchestrator instead of being repaired here, because A2.9's own rule is
    that a committed section is appended to and never edited.

    WHY THIS FUNCTION EXISTS AT ALL. The classification used to live
    inline as a ternary in `run_one`'s except clause, and `selfcheck` reached
    only the FORMATTER (`void_reason`) that consumes its answer. Measured, from
    the OUTPUT and not from a source grep (RB-P48): reverting `void_reason`'s
    string branch reddens selfcheck, and reverting the ternary left selfcheck
    GREEN AT 0 RED -- `CAP_TOL_S` occurred at exactly two places in this file
    and no check reached the second. So the fix was falsified for the formatter
    and UNFALSIFIED for the classifier. The M5 cases below reach this function
    directly, at the tolerance boundary where it can be wrong.

    THE RULE. The declared run cap binds THROUGH the HTTP timeout, because the
    remaining budget is handed to `generate` as its timeout. So a raise at the
    cap IS the cap arriving and is `run-cap`; a raise well inside the cap is the
    endpoint failing and is `endpoint-error`. `CAP_TOL_S` is scheduling slop, not
    a threshold with an opinion: it only decides which of the two events a raise
    at the boundary is reported as. Both are VOID, and they are not the same
    instrument verdict -- a `run-cap` VOID reproduces on a re-run because it is a
    TRAJECTORY fact, an `endpoint-error` VOID is infrastructure and should be
    re-run.
    """
    stopped_by = ("run-cap" if elapsed >= RUN_CAP_S - CAP_TOL_S
                  else "endpoint-error")
    return stopped_by, f"{type(exc).__name__}: {exc}"


def void_reason(outcome: str, stopped_by: str | None, wall: float,
                endpoint_exc: str, truncated_writes: list) -> str:
    """The reason string, with the measured elapsed time IN it.

    The old string was `f"run-cap ({RUN_CAP_S}s) {exc}"` for every exception the
    endpoint could raise, so a run of any length reported the cap it had not
    reached. Each reason now carries the number a reader can check against
    `wall_s`, and names the endpoint error separately from the cap."""
    if outcome == "VOID-TRUNCATED":
        return ("output-cap truncation at turns "
                + ",".join(str(t["turn"]) for t in truncated_writes)
                + f" (num_predict={NUM_PREDICT})")
    if outcome != "VOID":
        return ""
    if stopped_by == "run-cap":
        s = f"run-cap ({RUN_CAP_S}s) exceeded at wall {wall:.3f}s"
        return s + (f"; endpoint raised {endpoint_exc}" if endpoint_exc else "")
    if stopped_by == "endpoint-error":
        return (f"endpoint-error at wall {wall:.3f}s, well inside the "
                f"{RUN_CAP_S}s run cap: {endpoint_exc}")
    return f"{stopped_by} at wall {wall:.3f}s"


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
    # C-2: refuse an unimplemented arm HERE, before the worktree is touched and
    # before 20 minutes of wall-clock, rather than at row-assembly time. The
    # `choices=` list on `--arm` is the same check at the CLI; this one holds for
    # any caller that reaches `run_one` directly.
    compaction_mode_for(arm)
    restore(wt, REAL_REPO)
    problems = apply_defects(wt)
    if problems:
        return {"arm": arm, "repeat": repeat, "outcome": "VOID",
                "void_reason": "oracle-baseline-drift: " + "; ".join(problems)}

    blocks: list[dict] = []
    calls: list[dict] = []
    prev_prompt_eval = 0
    t0 = time.monotonic()
    stopped_by = None
    endpoint_exc = ""
    truncated_writes: list[dict] = []
    action_texts: list[str] = []
    tamper_write: dict | None = None

    for turn in range(1, TURN_CAP + 1):
        if time.monotonic() - t0 > RUN_CAP_S:
            stopped_by = "run-cap"
            break
        # Bar section 10.2: the boundary fires on the first worker call at which
        # the run's live context, measured by `prompt_eval_count` on the
        # IMMEDIATELY PRECEDING call, reaches T.
        # N-17: the DECISION is taken here, because a future arm calls
        # `context_compact` here. The COUNT is not taken here -- see
        # `boundaries_from_calls`. Arm B0 never calls `context_compact`; the
        # crossing is still recorded, on the call it belongs to.
        crossed_before_this_call = prev_prompt_eval >= T_BOUNDARY
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
            # "The declared run cap was exceeded" and "the endpoint raised" are
            # TWO events and this clause used to report both as `run-cap`. The
            # cap binds THROUGH the HTTP timeout only when the run has actually
            # reached it; a socket error at 30 s of a 1200 s cap is the endpoint
            # failing, and calling that `run-cap (1200s)` fabricates a
            # measurement. Both are VOID -- instrument verdicts -- but they are
            # not the same instrument verdict, and each now has its own
            # `stopped_by`, its own `void_reason` and its own column.
            stopped_by, endpoint_exc = classify_stop(
                time.monotonic() - t0, exc)
            break
        r["turn"] = turn
        r["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
        r["prompt_bytes"] = len(prompt.encode())
        r["boundary_before_this_call"] = crossed_before_this_call
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
            verb, arg, body, incomplete = parsed
            if verb == "WRITE" and (incomplete
                                    or r.get("done_reason") == "length"):
                # Recorded, not repaired. The tool's SEMANTICS are frozen so a
                # post-fix row stays comparable to a pre-fix one on the
                # trajectory axis; what changes is that the run can no longer
                # be reported as an OUTCOME. See `classify_outcome`.
                truncated_writes.append({
                    "turn": turn, "path": arg,
                    "fence": incomplete or "present",
                    "done_reason": r.get("done_reason"),
                    "eval_count": r.get("eval_count"),
                })
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
                # A2.2: the write is PERFORMED, not refused. Only after it has
                # happened does the pre-registered verdict get evaluated.
                result = canon_rule_a(tool_write(wt, arg, body))
                canon = "rule-a"
                if tamper_write is None and is_tamper_write(wt, arg):
                    tamper_write = {"turn": turn, "path": arg}
            else:
                code, out = run_oracle(wt)
                result = canon1(out) + f"\n(exit code {code})"
                canon = "canon-1-full"
        blocks.append({"kind": "result", "n": turn, "text": result,
                       "canon": canon})
        if tamper_write is not None:
            # A2.2, the whole of the change: the run ends HERE rather than
            # 19 more minutes of oracle exit codes about a tree the guard has
            # already disqualified. The verdict is section 1.4's, unmoved.
            stopped_by = "tamper"
            break
    else:
        stopped_by = "turn-cap"

    wall = time.monotonic() - t0
    oracle_exit, oracle_out = run_oracle(wt)
    guard_t = run_guard_t(wt)
    tampered = guard_tamper(wt)
    scope = guard_scope(wt)
    outside = [p for p in scope if p not in DEFECT_PATHS]

    outcome = classify_outcome(
        stopped_by=stopped_by, tampered=tampered, oracle_exit=oracle_exit,
        guard_t=guard_t, truncated_writes=truncated_writes)

    # The prompt stream, canonicalised, is what D-2 compares (bar section 2.5).
    stream = "\n\x00\n".join(
        [c["prompt_sha256"] for c in calls] + action_texts
    )
    return {
        "arm": arm, "repeat": repeat,
        "worker_model": WORKER_MODEL, "summarizer_model": SUMMARIZER_MODEL,
        "summarizer_num_ctx": SUMMARIZER_NUM_CTX, "worker_num_ctx": WORKER_NUM_CTX,
        "temperature": WORKER_TEMPERATURE, "seed": WORKER_SEED,
        "compaction_mode": compaction_mode_for(arm),
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
        "boundaries": boundaries_from_calls(calls),
        "first_boundary_turn": next(
            (c["turn"] for c in calls if c["boundary_before_this_call"]), None),
        # Bar section 10.2 justified num_ctx = 32768 by arithmetic: "the ceiling
        # (25,900 + the task prompt, ~27k) fits, so no truncation occurs". That
        # arithmetic is over a trajectory that reads every file once and runs the
        # oracle once. This column reports whether the REALISED trajectory stayed
        # under the window, from the output side, per run.
        "worker_window_reached": max(
            (c["prompt_eval_count"] or 0 for c in calls), default=0) >= WORKER_NUM_CTX,
        "summarizer_input_tokens": 0 if arm in COMPACT_OFF_ARMS else None,
        "summarizer_output_tokens": 0 if arm in COMPACT_OFF_ARMS else None,
        "summarizer_clamped": [],
        "summary_chars": 0, "block_chars": sum(len(b["text"]) for b in blocks),
        "canon_stream_sha256": hashlib.sha256(stream.encode()).hexdigest(),
        "files_touched_outside_defect_set": outside,
        # Two instrument events, two reasons, and the elapsed time IN the string
        # so a reader can check the claim against `wall_s` without trusting the
        # label. A 30 s run can no longer report "run-cap (1200s)".
        "void_reason": void_reason(
            outcome, stopped_by, wall, endpoint_exc, truncated_writes),
        "endpoint_error": endpoint_exc,
        # The output side of the window, from the endpoint's own `done_reason`.
        "length_stops": length_stop_turns(calls),
        "truncated_writes": truncated_writes,
        # A2.2: which WRITE ended the run, or null if none did. The row can be
        # asked WHY it stopped at turn N without re-running the trajectory --
        # bar Amendment 2 A2.8 item 5 names that gap as the reason the turn-6
        # tamper in B0 was recoverable only by re-running it.
        "tamper_write": tamper_write,
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
        print(f"    -> outcome={row['outcome']} "
              f"oracle_exit={row.get('oracle_exit')} "
              f"calls={row.get('worker_calls')} "
              f"ctx_tokens={row.get('context_tokens_sent')} "
              f"max_pe={row.get('max_prompt_eval_count')} "
              f"boundaries={row.get('boundaries')} wall={row.get('wall_s')}s "
              f"stopped_by={row.get('stopped_by')} "
              f"length_stops={row.get('length_stops')} "
              f"truncated_writes="
              f"{[t['turn'] for t in row.get('truncated_writes', [])]}",
              flush=True)
        if row.get("void_reason"):
            print(f"       void_reason: {row['void_reason']}", flush=True)
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


GOOD_WRITE = (
    "WRITE packages/shared/src/date/date.ts\n<<<\n"
    "export const iso = (v: string) => v.slice(0, 10);\n>>>\n"
)


def cmd_selfcheck(args) -> int:
    """The output-side falsifier for SHAPE-silent-truncation S5 and for the
    `stopped_by` mislabel.

    Same shape as the `d2` mutation (write-up section 2.6) and for the same
    reason (RB-P48): the mutation is applied to the DATA the check reads -- the
    action text the model emitted, the `done_reason` the endpoint returned, the
    oracle's exit code -- never to a flag this harness sets for itself. A check
    that reddens only when you flip its own flag has not been falsified.

    Each case is run twice: once on the unmutated input, which must be GREEN,
    and once on the mutated input, which must be RED. A mutation that leaves the
    check green is a failure and exits 1."""
    print(RULE)
    print("SELFCHECK -- the output-side falsifier. green on truth, red on the mutant.")
    print(RULE)
    fails = 0

    def case(name: str, shown: str, got, want) -> None:
        nonlocal fails
        ok = got == want
        fails += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'RED'}] {name:44s} {shown}")
        if not ok:
            print(f"        expected {want!r}, got {got!r}")

    # --- M1. The `>>>` terminator, mutated OUT of the model's own action text.
    truth = parse_action(GOOD_WRITE)
    mutant_text = GOOD_WRITE.replace(">>>\n", "")          # the num_predict cut
    mutant = parse_action(mutant_text)
    case("M1 green: complete WRITE is not flagged", "incomplete=''",
         truth[3], "")
    case("M1 RED: `>>>` stripped from the output", "missing-close-fence",
         mutant[3], "missing-close-fence")
    case("M1 RED: no `<<<` at all", "missing-open-fence",
         parse_action("WRITE a/b.ts\nexport const x = 1;\n")[3],
         "missing-open-fence")
    # The body of the mutant runs to the end of the completion -- that is what
    # made it indistinguishable from a whole file before.
    case("M1 note: mutant body is non-empty, so it WAS written",
         f"{len(mutant[2])} bytes", len(mutant[2]) > 0, True)

    # --- M2. `done_reason`, mutated in the endpoint's own reply shape.
    calls_ok = [{"turn": 1, "done_reason": "stop"},
                {"turn": 2, "done_reason": "stop"}]
    calls_cut = [{"turn": 1, "done_reason": "stop"},
                 {"turn": 2, "done_reason": "length"}]
    case("M2 green: every call stopped on a stop token", "[]",
         length_stop_turns(calls_ok), [])
    case("M2 RED: one `done_reason` flipped to `length`", "[2]",
         length_stop_turns(calls_cut), [2])

    # --- M3. The ladder. Identical failing run, with and without a truncation.
    base = {"stopped_by": "done", "tampered": [], "oracle_exit": 1,
            "guard_t": 0}
    case("M3 green: failing run with no truncation", "FAIL",
         classify_outcome(**base, truncated_writes=[]), "FAIL")
    case("M3 RED: the same run with a truncated WRITE", "VOID-TRUNCATED",
         classify_outcome(**base, truncated_writes=[{"turn": 7}]),
         "VOID-TRUNCATED")
    case("M3: turn-cap with a truncation is VOID-TRUNCATED, not FAIL-CAP",
         "VOID-TRUNCATED",
         classify_outcome(stopped_by="turn-cap", tampered=[], oracle_exit=1,
                          guard_t=0, truncated_writes=[{"turn": 7}]),
         "VOID-TRUNCATED")
    case("M3: a truncation that still PASSED stays PASS", "PASS",
         classify_outcome(stopped_by="done", tampered=[], oracle_exit=0,
                          guard_t=0, truncated_writes=[{"turn": 7}]), "PASS")
    case("M3: a truncation on a tampered tree stays FAIL-TAMPERED",
         "FAIL-TAMPERED",
         classify_outcome(stopped_by="done", tampered=["x.test.ts"],
                          oracle_exit=1, guard_t=0,
                          truncated_writes=[{"turn": 7}]), "FAIL-TAMPERED")
    case("M3: run-cap outranks a truncation", "VOID",
         classify_outcome(stopped_by="run-cap", tampered=[], oracle_exit=1,
                          guard_t=0, truncated_writes=[{"turn": 7}]), "VOID")

    # --- M4. The reason string must carry the elapsed time it claims.
    early = void_reason("VOID", "endpoint-error", 29.994, "OSError: broken", [])
    late = void_reason("VOID", "run-cap", 1200.004, "TimeoutError: timed out", [])
    case("M4 green: a 1200s stop names the cap", f"{RUN_CAP_S}s",
         f"run-cap ({RUN_CAP_S}s) exceeded at wall 1200.004s" in late, True)
    case("M4 RED: a 30s stop must NOT report the cap as exceeded",
         "endpoint-error", early.startswith("endpoint-error at wall 29.994s"),
         True)
    case("M4 RED: and must not contain the string `run-cap`", "absent",
         "run-cap" in early, False)

    # --- M5. The CLASSIFIER, not the formatter that prints its answer.
    # M4 above reaches `void_reason` and reddens when its strings are reverted.
    # It did NOT reach the ternary that decides WHICH string is asked for, so
    # reverting that ternary to the pre-fix `stopped_by = "run-cap"` left this
    # selfcheck green at 0 RED -- measured, from the output. These cases call
    # `classify_stop` directly, at the tolerance boundary where it can be wrong,
    # on a real exception object rather than on a flag the harness sets itself.
    cap_exc = TimeoutError("timed out")
    net_exc = OSError("broken")
    case("M5 green: a raise AT the cap is the cap arriving", "run-cap",
         classify_stop(1200.004, cap_exc)[0], "run-cap")
    case("M5 RED: a raise at 30s of a 1200s cap is the ENDPOINT",
         "endpoint-error", classify_stop(29.994, net_exc)[0], "endpoint-error")
    case("M5 RED: exactly at the tolerance boundary is the cap",
         f"{RUN_CAP_S - CAP_TOL_S}s", classify_stop(1199.0, cap_exc)[0],
         "run-cap")
    case("M5 RED: one millisecond inside the tolerance is the endpoint",
         "1198.999s", classify_stop(1198.999, net_exc)[0], "endpoint-error")
    case("M5: the reason carries the endpoint's own type and message",
         "OSError: broken", classify_stop(29.994, net_exc)[1],
         "OSError: broken")

    # --- M6. A2.2, the terminal guard. The predicate reads a RESOLVED path, and
    # the ladder is asked what it does with a run that stopped for that reason.
    case("M6 green: a WRITE to an implementation file is not a tamper", "False",
         is_tamper_write("/nowhere", "src/date/date.ts"), False)
    case("M6 RED: a WRITE to a `*.test.ts` file is a tamper", "True",
         is_tamper_write("/nowhere", "src/date/date.test.ts"), True)
    case("M6 RED: nested, and matched on the resolved path", "True",
         is_tamper_write("/nowhere", "src/expense/split/split.test.ts"), True)
    case("M6: a path `_resolve` rejects was never written, so never a tamper",
         "False", is_tamper_write("/nowhere", "../../x.test.ts"), False)
    case("M6: a tamper-terminated run is FAIL-TAMPERED even if `git diff` is "
         "empty", "FAIL-TAMPERED",
         classify_outcome(stopped_by="tamper", tampered=[], oracle_exit=1,
                          guard_t=0, truncated_writes=[]), "FAIL-TAMPERED")
    case("M6 green: the same run NOT stopped by tamper is still FAIL", "FAIL",
         classify_outcome(stopped_by="done", tampered=[], oracle_exit=1,
                          guard_t=0, truncated_writes=[]), "FAIL")

    # --- M7. A2.1 rule (d), falsified against THE DEFECT, not against a second
    # transcription of the rule (RB-P47). The disagreement input is named: two
    # oracle outputs with the SAME multiset of lines, differing only in which
    # ` FAIL ` block carries vitest's one extra trailing blank -- which is
    # whichever block finished last, and is nondeterministic. Rule (c) sorts the
    # blocks and RELOCATES that blank; neither (b) nor (c) mentions blank lines.
    head_lines = ["head line 2", "head line 1"]
    blk_a = [" FAIL  src/a/a.test.ts", "AssertionError: a", "---[1/2]---"]
    blk_b = [" FAIL  src/b/b.test.ts", "AssertionError: b", "---[2/2]---"]
    # u0: printed a then b, so b -- the last -- carries the extra blank.
    u0 = "\n".join(head_lines + blk_a + [""] + blk_b + ["", ""])
    # u1: printed b then a, so a -- the last -- carries it. Same lines.
    u1 = "\n".join(head_lines + blk_b + [""] + blk_a + ["", ""])
    case("M7 setup: the two samples are the same multiset of lines", "equal",
         sorted(u0.split("\n")) == sorted(u1.split("\n")), True)
    case("M7 setup: and they are NOT the same text", "differ", u0 != u1, True)
    case("M7 RED: without rule (d) the permutation survives CANON-1", "differ",
         canon1(u0, rule_d=False) == canon1(u1, rule_d=False), False)
    case("M7 green: rule (d) converges them", "identical",
         canon1(u0) == canon1(u1), True)
    case("M7 RED: A2.1's falsifying mutation -- (d) on the last block only",
         "differs again",
         canon1(u0, rule_d_last_block_only=True)
         == canon1(u1, rule_d_last_block_only=True), False)
    case("M7: rule (d) is not vacuous -- it changed the text", "changed",
         canon1(u0) != canon1(u0, rule_d=False), True)
    case("M7: and it removed only BLANK lines -- no failure text is touched",
         "only blanks",
         [ln for ln in canon1(u0, rule_d=False).split("\n") if ln.strip()]
         == [ln for ln in canon1(u0).split("\n") if ln.strip()], True)

    # --- M8. C-2, the arm gate. Falsified against the ARM LABEL -- the datum
    # `compaction_mode` is derived from -- and against the two labels that have
    # a behaviour in this file. The mutation that reddens this block is the
    # pre-fix expression itself: `"off" if arm in COMPACT_OFF_ARMS else "store"`
    # with no membership test, which answers `store` for every string ever typed.
    case("M8 green: an implemented compaction-OFF arm is `off`", "off",
         compaction_mode_for("compact-off"), "off")
    case("M8 green: and so is B0\u2033", "off",
         compaction_mode_for("compact-off-tamper-terminal"), "off")
    for bad in ("compact-on", "compact-store", "b1", ""):
        got = "no-raise"
        try:
            got = compaction_mode_for(bad)
        except ValueError:
            got = "refused"
        case(f"M8 RED: unimplemented arm {bad!r} is refused, not stamped",
             "refused", got, "refused")
    case("M8: every `choices=` entry has a behaviour, so the gate is not "
         "vacuous", "all resolve",
         all(compaction_mode_for(a) in ("off", "store")
             for a in IMPLEMENTED_ARMS), True)
    case("M8: no compaction-ON arm is implemented -- the `store` branch is "
         "dead", "0 store arms",
         [a for a in IMPLEMENTED_ARMS if compaction_mode_for(a) == "store"], [])

    # --- M9. N-17, the boundary count. Falsified against a recorded `calls`
    # sub-array of the shape a raising run leaves behind: the crossing was
    # decided at the loop top, the call then raised, and NOTHING was appended.
    # The mutation that reddens this block is the pre-fix accumulator, which
    # counts the crossing rather than the call.
    below = {"turn": 1, "boundary_before_this_call": False,
             "prompt_eval_count": 100}
    across = {"turn": 2, "boundary_before_this_call": True,
              "prompt_eval_count": T_BOUNDARY + 1}
    case("M9 green: no call crossed, so no boundary", "0",
         boundaries_from_calls([below, below]), 0)
    case("M9 green: two calls crossed, so two boundaries", "2",
         boundaries_from_calls([below, across, across]), 2)
    case("M9 RED: a crossing whose call RAISED leaves no call, so no boundary",
         "0", boundaries_from_calls([below]), 0)
    case("M9 RED: and the run that raised after ONE crossing counts 1, not 2",
         "1", boundaries_from_calls([below, across]), 1)
    case("M9: the count equals the row's own per-call flags, by construction",
         "equal",
         boundaries_from_calls([below, across, below, across])
         == sum(1 for c in [below, across, below, across]
                if c["boundary_before_this_call"]), True)

    # --- M10. N-16's blast radius on the OUTCOME ladder, so the closure does not
    # have to assert it. `guard_type_exit` moved 2 -> 1 across repeats; the
    # ladder only ever asks whether it is zero, so the leak could not have moved
    # a verdict through `classify_outcome`. Checked, not assumed.
    green = {"stopped_by": "done", "tampered": [], "truncated_writes": []}
    case("M10: guard_t 1 and guard_t 2 give the SAME outcome on a passing "
         "oracle", "both FAIL-TYPE",
         classify_outcome(**green, oracle_exit=0, guard_t=1)
         == classify_outcome(**green, oracle_exit=0, guard_t=2) == "FAIL-TYPE",
         True)
    case("M10 RED: and guard_t 0 is the one that differs", "PASS",
         classify_outcome(**green, oracle_exit=0, guard_t=0), "PASS")

    # --- M11. THE ORACLE MUST RESOLVE ITS CONFIGURATION FROM A PATH THE AGENT'S
    # WRITE SURFACE CANNOT REACH. That is the property; `--config` is only the
    # mechanism that currently satisfies it, and M11 is written so that a
    # different mechanism satisfying the same property would keep it green.
    #
    # RB-P72 is the finding: the oracle auto-discovered its config from its own
    # cwd, its cwd IS `<wt>/packages/shared`, and that directory is exactly what
    # the roster's WRITE tool can name -- so one WRITE bought `exit 0` with
    # GUARD-TAMPER empty, GUARD-SCOPE unchanged and GUARD-T 0.
    #
    # `_resolve` is the roster's own path check and is therefore the authority
    # on "can the agent name this", so M11 asks IT rather than asserting a
    # string. It asks on the most hostile worktree the pinned path admits: the
    # one whose write surface is the pin's own `packages/shared` ancestor, if it
    # has one. A pin with no such ancestor is unreachable from EVERY worktree,
    # which is the quantifier the property needs and a single sample would not
    # give. And a pin that is absent at all is not a weaker pin but the
    # pre-RB-P72 oracle: the config is then whatever vitest finds in cwd, and cwd
    # is the write surface itself -- reachable by construction, not by accident.
    argv = oracle_argv(os.path.join("/no-such-worktree", SHARED))
    pinned = argv[argv.index("--config") + 1] if "--config" in argv else None
    if pinned is None:
        reachable = True
    else:
        cfg = os.path.realpath(pinned)
        marker = os.sep + SHARED.replace("/", os.sep) + os.sep
        hostile = cfg.rsplit(marker, 1)[0] if marker in cfg else None
        reachable = hostile is not None and _resolve(
            hostile, os.path.relpath(cfg, os.path.join(hostile, SHARED))) == cfg
    case("M11 RED: the oracle NAMES its config, it does not discover it",
         "--config", "--config" in argv, True)
    case("M11 RED: and no WRITE `_resolve` admits can name that path",
         "unreachable", reachable, False)
    # NOT asserted here, and the omission is deliberate and was measured: an
    # `os.path.isfile(pinned)` case looks like a free extra check and is a trap.
    # `ORACLE_CONFIG` is relative to `__file__`, and the MUT harness of
    # `2026-08-19-loop-u5-closure-field-measurement.py` loads this file from a
    # TEMP COPY, so the pin resolves to a directory the config was never in and
    # the case reddens under all THREE of that program's mutations -- none of
    # which touches the oracle. Measured: its MUT columns went 4/5/5 RED at
    # `ba7a38b` to 5/6/6 with the case present, and back to 4/5/5 without it. A
    # case that reddens for a reason its name does not state is worse than no
    # case: it launders unrelated mutations into M11's column. Existence is
    # caught anyway and by the right instrument -- vitest exits non-zero on a
    # `--config` it cannot open, which is a FAIL, never a PASS.

    print()
    if fails:
        print(f"  SELFCHECK: {fails} case(s) RED -> the fix is not in place")
        return 1
    print("  SELFCHECK: all cases behaved as declared")
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
    p.add_argument("--arm", default="compact-off", choices=IMPLEMENTED_ARMS,
                   help="an IMPLEMENTED arm. C-2: without this list, `--arm "
                        "compact-on` emitted six rows of a compaction-ON arm "
                        "whose mechanism no code path calls, at exit 0.")
    p.add_argument("--repeats", type=int, default=6)
    p.add_argument("--write", default=None,
                   help="write rows as .jsonl. Absent = writes nothing.")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("selfcheck")
    p.set_defaults(fn=cmd_selfcheck)

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
