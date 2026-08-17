#!/usr/bin/env python3
"""THE COMPACTION CORPUS — bantamkit's own transcripts, characterised. Numbers only.

    .venv/bin/python docs/eval-data/2026-08-17-compaction-corpus-survey.py .
    .venv/bin/python docs/eval-data/2026-08-17-compaction-corpus-survey.py . --check

U3 of job `compaction-measured`. Writes `2026-08-17-compaction-corpus.jsonl`, one row per
corpus transcript; `--check` regenerates and compares **NAMED COLUMNS**, never bytes and
never whole lines (bar §9, RB-P46). It runs no arm, invokes no summarizer, computes no
delta and computes no saving. It characterises the corpus and nothing else.

THE USER'S FENCE, MECHANICAL RATHER THAN PROMISED. The corpus is bantamkit transcripts
only, and every committed row carries numbers and statistics only. No transcript excerpt,
no prompt text, no filename from any project reaches the artifact: `transcript_id` is
`sha256(<path relative to the transcript root>)[:16]` and `fence_violations()` re-reads
the rendered artifact and fails the run if any value contains a path separator, a `.jsonl`
suffix or a home-directory prefix. The fence is checked on the bytes that would be
committed, not asserted about them.

WHY THERE IS A CUTOFF, AND WHY IT IS THAT ONE. The corpus is a live directory: the user's
next session appends to it, and this program's own session was appending to it while this
program was written. So a statistic over "the directory as it is" is false by tomorrow,
and a byte-identity reproduction check over one is a check that must eventually be made
green by regenerating the evidence it protects — the RB-P46 failure mode one level out.
Every number here is therefore a function of the lines timestamped **strictly before**
`CUTOFF_UTC`, which is the commit instant of the pre-registered bar
(`2026-08-17-compaction-bar-preregistration.md`, f48335c, 2026-08-17T23:29:52+07:00).
Two consequences, both wanted:

  * the numbers are append-only-stable. A new session, a resumed session and this
    program's own transcript all land after the cutoff and cannot move a committed row,
    so `--check` stays green without anything being regenerated;
  * the corpus is exactly what was already on disk when the bar was frozen. The bar's §0
    claim 1 — that no transcript was opened to write it — cannot be falsified
    retroactively by U3's reads, because nothing U3 caused to be recorded is in the
    corpus.

A transcript that straddles the cutoff is carried TRUNCATED, flagged
`truncated_at_cutoff`, because dropping it would make the corpus depend on when a session
happened to end.

WHAT `model_calls` IS HERE, AND WHY THE LINE COUNT IS NOT IT. A Claude Code transcript
writes ONE LINE PER CONTENT BLOCK: an assistant reply carrying a thinking block and three
`tool_use` blocks is four lines with the same `message.id`, the same `requestId` and the
SAME `usage` object repeated verbatim on each. So `grep -c '"type":"assistant"'` counts
content blocks, not model calls, and summing `usage` over lines multiplies the recorded
token totals by the same factor. `model_calls` here is the number of distinct
`requestId`s over assistant lines whose `message.model` is a real model;
`model_calls_by_message_id` is the same quantity derived independently from
`message.id`, committed beside it so the two derivations can disagree in public.
Synthetic assistant messages (`message.model == "<synthetic>"`, no `requestId`, all-zero
usage) are host-generated error notices, not model calls, and are counted in their own
column instead of being folded into either.

THE TOKEN FACTOR IS FITTED, NOT PICKED. The bar (§10.3) refuses the mechanism's own
`Math.ceil(text.length / 4)` and requires a factor MEASURED from the corpus's own recorded
usage. These transcripts do carry per-call usage, so the fallback of §10.3(4) is not
taken. Within one transcript the prompt grows by append, so across its calls

    recorded_prompt_tokens(i)  =  preamble_tokens  +  payload_bytes_before(i) / bpt

is a straight line in the payload bytes, and ORDINARY LEAST SQUARES over the calls
recovers BOTH unknowns: the slope gives the bytes-per-token factor and the intercept gives
the fixed cost — the system prompt, the tool schemas and the project instructions, which
are billed on every call and appear NOWHERE in the transcript. `r2` is committed beside
them, so a bad fit is visible rather than averaged away. The fit is restricted to the
calls before the transcript's first host-level compaction boundary, because a boundary
breaks the append-only premise the fit rests on.

TWO BYTE DEFINITIONS ARE FITTED, AND WHAT THAT MEASURED IS NOT WHAT WAS EXPECTED. The
first draft of this program fitted `payload` bytes — message content plus host-injected
attachments — and its intercept came out NEGATIVE on most transcripts (median about −5,200
tokens), which is not a fixed cost any endpoint could have billed. The draft's diagnosis
was that the two definitions would BRACKET the factor from above and below. **They do
not.** Measured, the two fitted slopes agree to four decimal places at the median (1.8284
against 1.8289) and the entire difference lands in the intercept, which moves by about
30,000 tokens. So the attachment bytes are a near-CONSTANT offset — injected once and not
re-sent — and the byte definition turns out to be nearly irrelevant to the FACTOR while
being decisive for the FIXED COST. Both fits stay committed because that agreement is
itself the evidence, and a survey that had kept only the definition it preferred could not
show it.

`messages_only` is the PRIMARY for one reason that is not about which number is nicer: it
is the byte definition U4's reconstruction will actually produce, since a replay rebuilds
turns from `message.content`. Its intercept is positive (median 25,350 tokens) and is
corroborated INDEPENDENTLY by `preamble_tokens_first_call_bound`, which uses only the
first call and the intercept-free factor and lands at a median of 26,516 — two derivations
of the same fixed cost, 4.6% apart, neither derived from the other.

`bytes_per_prompt_token_incremental_median` is committed beside both fits as a THIRD
estimate that assumes nothing about the intercept: per call, (Δ bytes since the previous
call) ÷ (Δ recorded prompt tokens), taking the median over the calls. A constant fixed
cost cancels in a difference, so this estimator survives a contaminated intercept, and
where it disagrees with the fitted slope the disagreement is on the record instead of
inside an average.

`bytes_per_output_token` is committed as an independent, assumption-free second estimate:
an assistant message's own content bytes over its own recorded `output_tokens`, same call,
no fit and no prefix reconstruction. It is a DIFFERENT quantity — model prose and code
against a prompt dominated by tool output — and the two are expected to differ. Both are
reported; neither is blended into the other.

WHAT THIS PROGRAM DOES NOT DO. It does not reconstruct a prefix, so it does not produce
bar §8's `prefix_bytes`. It does not apply §10.2's boundary schedule, so it does not
produce `boundaries` or `post_boundary_calls` — applying the schedule is U4's, and a
corpus survey that computed how many boundaries would fire would be an arm wearing a
survey's name. `host_precompacted_boundaries` (§8 column 17, outcome U-4) IS counted
here, because it is a property of the recording and can only be measured on the recording.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ARTIFACT = "2026-08-17-compaction-corpus.jsonl"
RULE = "=" * 78

# The commit instant of the pre-registered bar, in UTC. See the module docstring: the
# corpus is what was already recorded when the bar was frozen. Changing this constant
# changes the corpus and is a dated declaration, not a tweak.
CUTOFF_UTC = "2026-08-17T16:29:52.000Z"

# The repository whose transcripts are in scope. The user's fence, as a constant.
BANTAMKIT_ROOT = "/Users/kktest/Documents/Claude/Projects/bantamkit"

# The mechanism's own shipped defaults, as pinned in the bar's §10.1 source-constant table
# (`compaction-mcp` at 0a15cff, `src/config.ts:98-99`): 60 percent of 128,000. A SOURCE
# CONSTANT, not a design choice made here, and used here for nothing but description.
THRESHOLD_T = 60 * 128_000 // 100

# Where Claude Code records transcripts. Overridable so the pytest node can drive this
# program over a synthetic fixture directory instead of over the real corpus — which is
# what keeps every node a statement about the INSTRUMENT rather than about the world
# (RB-P14 Gate 2).
DEFAULT_TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"

# Columns added to a row AFTER the artifact was committed. Empty at first commit; an
# UNDECLARED new key turns `--check` red, which is what stops the declaration from being
# a hole (RB-P46, and the shape U1 shipped as ADDITIVE_KEYS_THE_ARTIFACT_PREDATES in
# 2026-08-17-devteam-instrument-validation-run.py).
ADDITIVE_KEYS_THE_ARTIFACT_PREDATES: tuple[str, ...] = ()

# A `cwd` value and a timestamp, lifted without parsing the whole line. Cheap because the
# classification pass reads every byte of a 549 MB tree and only the purity verdict comes
# out of it. `\s*` after the colon is not decoration: the first draft required the host's
# compact `"cwd":"…"` exactly, and the synthetic fixture in
# `runtime-py/tests/test_compaction_corpus_survey.py` — written with `json.dumps`, which
# emits `"cwd": "…"` — classified as EMPTY. A whitespace change in the host's writer would
# have silently emptied the corpus instead of failing.
_CWD_RE = re.compile(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"')
_TIMESTAMP_RE = re.compile(r'"timestamp"\s*:\s*"([^"]*)"')

# The fence, as patterns rather than as a promise. Applied to every string that would be
# committed, including inside nested objects.
_FENCE_PATTERNS = ("/", "\\", ".jsonl", "/Users/", "~/")


def _is_bantamkit_cwd(cwd: str) -> bool:
    return cwd == BANTAMKIT_ROOT or cwd.startswith(BANTAMKIT_ROOT + "/")


def _under_cutoff(timestamp: str | None) -> bool:
    """Lexicographic on the recorded ISO-8601 Z timestamp — the recorded format is fixed.

    A line with no timestamp is NOT under the cutoff and never enters a statistic. Those
    lines are bookkeeping the host writes outside the message stream (`mode`, `ai-title`,
    `pr-link`, `file-history-snapshot`), they carry no content that would cross the wire,
    and they are counted by kind in `untimestamped_lines_by_type` rather than dropped
    silently — bar §1.2 requires every skipped kind enumerated with its count, and a
    survey that hid them would hand U4 an unenumerated skip.
    """
    return isinstance(timestamp, str) and timestamp < CUTOFF_UTC


def classify_tree(root: Path) -> tuple[list[tuple[Path, int, int, int]], int]:
    """One cheap pass: per file, (path, bantamkit cwd lines, other cwd lines, distinct).

    No `json.loads`. Only lines under the cutoff are classified, so a file whose only
    bantamkit work happened after the bar was frozen is not in the universe.
    """
    rows: list[tuple[Path, int, int, int]] = []
    unreadable = 0
    for path in sorted(root.rglob("*.jsonl")):
        here = other = 0
        seen: set[str] = set()
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    match = _CWD_RE.search(line)
                    if match is None:
                        continue
                    stamp = _TIMESTAMP_RE.search(line)
                    if not _under_cutoff(stamp.group(1) if stamp else None):
                        continue
                    cwd = match.group(1)
                    seen.add(cwd)
                    if _is_bantamkit_cwd(cwd):
                        here += 1
                    else:
                        other += 1
        except OSError:
            unreadable += 1
            continue
        if here or other:
            rows.append((path, here, other, len(seen)))
    return rows, unreadable


def _content_bytes(content) -> int:
    """UTF-8 bytes of a message's CONTENT, by a declared rule and no other.

    Content only: no role, no envelope, no JSON punctuation. Text and thinking by their
    text; a `tool_use` by its serialised input; a `tool_result` by its own content,
    recursively. Anything else contributes 0 and is visible as a kind in
    `content_block_kinds`, so an unaccounted block type is a number a reader can see
    rather than a silent zero.
    """
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content.encode("utf-8"))
    if isinstance(content, list):
        return sum(_content_bytes(block) for block in content)
    if not isinstance(content, dict):
        return 0
    kind = content.get("type")
    if kind == "text":
        return len(str(content.get("text", "")).encode("utf-8"))
    if kind == "thinking":
        return len(str(content.get("thinking", "")).encode("utf-8"))
    if kind == "tool_use":
        return len(json.dumps(content.get("input", {}), sort_keys=True).encode("utf-8"))
    if kind == "tool_result":
        return _content_bytes(content.get("content"))
    return 0


def _attachment_bytes(attachment) -> int:
    """An attachment's own serialised bytes.

    Attachments are host-injected content — reminders, file bodies, hook output — that is
    billed on the call it rides but is not part of any `message.content`. Serialised
    length is a declared over-estimate of its wire cost and an under-estimate of nothing;
    it is kept in its own column so the fit can be run with it and without it.
    """
    if attachment is None:
        return 0
    return len(json.dumps(attachment, sort_keys=True).encode("utf-8"))


def _ols(points: list[tuple[float, float]]) -> tuple[float, float, float] | None:
    """Least squares on (x, y). Returns (slope, intercept, r2), or None if degenerate.

    Written out rather than imported: the package's dependencies are `httpx`,
    `jsonschema` and `pyyaml`, and a committed field program that needs a numeric stack
    to be re-run is a program that stops being re-run.
    """
    n = len(points)
    if n < 3:
        return None
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in points)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    if sxx == 0:
        return None
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    syy = sum((y - mean_y) ** 2 for _, y in points)
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in points)
    r2 = 1.0 - residual / syy if syy else 1.0
    return slope, intercept, r2


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def survey_transcript(path: Path, transcript_id: str) -> dict:
    """Every committed column for one transcript, from its lines under the cutoff."""
    line_types: dict[str, int] = {}
    untimestamped: dict[str, int] = {}
    block_kinds: dict[str, int] = {}
    versions: set[str] = set()
    models: set[str] = set()
    branches: set[str] = set()

    lines_total = 0
    lines_under = 0
    assistant_lines = 0
    synthetic_lines = 0
    user_lines = 0
    tool_result_lines = 0
    sidechain_lines = 0
    truncated = False

    request_ids: set[str] = set()
    message_ids: set[str] = set()
    host_boundaries = 0
    host_summaries = 0
    host_pre_tokens = 0

    prompt_total = 0
    input_total = 0
    cache_read_total = 0
    cache_creation_total = 0
    output_total = 0
    prompt_peak = 0
    prompt_first: int | None = None
    prompt_last: int | None = None

    message_bytes = 0
    attachment_bytes = 0
    assistant_bytes = 0

    # Regression state: payload bytes seen so far, and one point per model call. A call's
    # x is the payload that PRECEDED it, which is the prefix the endpoint was billed for.
    running_messages = 0
    running_payload = 0
    fit_messages: list[tuple[float, float]] = []
    fit_payload: list[tuple[float, float]] = []
    incremental_messages: list[float] = []
    incremental_payload: list[float] = []
    boundary_seen = False
    accounted: set[str] = set()
    per_call: dict[str, dict[str, int]] = {}

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            lines_total += 1
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                line_types["UNPARSEABLE"] = line_types.get("UNPARSEABLE", 0) + 1
                continue
            if not isinstance(event, dict):
                line_types["NOT_AN_OBJECT"] = line_types.get("NOT_AN_OBJECT", 0) + 1
                continue
            kind = str(event.get("type", "MISSING_TYPE"))
            stamp = event.get("timestamp")
            if not _under_cutoff(stamp if isinstance(stamp, str) else None):
                if isinstance(stamp, str):
                    truncated = True
                else:
                    untimestamped[kind] = untimestamped.get(kind, 0) + 1
                continue

            lines_under += 1
            line_types[kind] = line_types.get(kind, 0) + 1
            if isinstance(event.get("version"), str):
                versions.add(event["version"])
            if isinstance(event.get("gitBranch"), str) and event["gitBranch"]:
                branches.add(event["gitBranch"])
            if event.get("isSidechain") is True:
                sidechain_lines += 1
            if event.get("subtype") == "compact_boundary":
                host_boundaries += 1
                boundary_seen = True
                meta = event.get("compactMetadata") or {}
                if isinstance(meta.get("preTokens"), int):
                    host_pre_tokens += meta["preTokens"]
            if event.get("isCompactSummary") is True:
                host_summaries += 1

            if kind == "attachment":
                size = _attachment_bytes(event.get("attachment"))
                attachment_bytes += size
                running_payload += size
                continue

            message = event.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        name = str(block.get("type", "MISSING"))
                        block_kinds[name] = block_kinds.get(name, 0) + 1
            elif isinstance(content, str):
                block_kinds["STRING"] = block_kinds.get("STRING", 0) + 1
            size = _content_bytes(content)
            message_bytes += size
            running_messages += size
            running_payload += size

            if kind == "user":
                user_lines += 1
                if event.get("toolUseResult") is not None:
                    tool_result_lines += 1
                continue
            if kind != "assistant":
                continue

            assistant_lines += 1
            model = message.get("model")
            if model == "<synthetic>":
                synthetic_lines += 1
                continue
            if isinstance(model, str):
                models.add(model)
            assistant_bytes += size
            message_id = message.get("id")
            request_id = event.get("requestId")
            if isinstance(message_id, str):
                message_ids.add(message_id)
            if isinstance(request_id, str):
                request_ids.add(request_id)

            # Usage is accounted ONCE PER MESSAGE ID, by the MAXIMUM over the message's
            # lines. Not by the first line, and this is a correction rather than a
            # preference: the PROMPT fields are repeated verbatim on every line of one
            # reply, but `output_tokens` is a STREAMING value — the lines of one message
            # carry 3, 3, 3, 2478, and only the last is the message's total. Taking the
            # first line's value under-counted output tokens by more than an order of
            # magnitude and made `bytes_per_output_token` read 17.6 B/token at the median,
            # which is what surfaced it. Max is correct for both kinds of field: constant
            # across lines for the prompt, monotone across lines for the output.
            key = message_id if isinstance(message_id, str) else f"line:{lines_total}"
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            got_input = int(usage.get("input_tokens") or 0)
            got_read = int(usage.get("cache_read_input_tokens") or 0)
            got_creation = int(usage.get("cache_creation_input_tokens") or 0)
            got_output = int(usage.get("output_tokens") or 0)
            prompt = got_input + got_read + got_creation
            if key in accounted:
                previous = per_call[key]
                per_call[key] = {
                    "input": max(previous["input"], got_input),
                    "read": max(previous["read"], got_read),
                    "creation": max(previous["creation"], got_creation),
                    "output": max(previous["output"], got_output),
                }
                continue
            accounted.add(key)
            per_call[key] = {
                "input": got_input,
                "read": got_read,
                "creation": got_creation,
                "output": got_output,
            }
            if prompt_first is None:
                prompt_first = prompt
            prompt_last = prompt
            if prompt and not boundary_seen:
                # x is the payload that preceded this call; this line's own content is
                # the reply, which the endpoint had not been sent.
                point_m = (float(running_messages - size), float(prompt))
                point_p = (float(running_payload - size), float(prompt))
                if fit_messages:
                    delta_tokens = point_m[1] - fit_messages[-1][1]
                    if delta_tokens > 0:
                        incremental_messages.append(
                            (point_m[0] - fit_messages[-1][0]) / delta_tokens
                        )
                        incremental_payload.append(
                            (point_p[0] - fit_payload[-1][0]) / delta_tokens
                        )
                fit_messages.append(point_m)
                fit_payload.append(point_p)

    for call in per_call.values():
        input_total += call["input"]
        cache_read_total += call["read"]
        cache_creation_total += call["creation"]
        output_total += call["output"]
        prompt = call["input"] + call["read"] + call["creation"]
        prompt_total += prompt
        prompt_peak = max(prompt_peak, prompt)

    fit_m = _ols(fit_messages)
    fit_p = _ols(fit_payload)
    inc_m = _median(incremental_messages)
    inc_p = _median(incremental_payload)
    # The fixed cost the transcript does not contain, bounded at the FIRST call with the
    # transcript's own intercept-free factor. Signed and unclamped: a negative value is a
    # measurement that the byte definition over-counts, not a zero.
    preamble_bound = (
        prompt_first - fit_messages[0][0] / inc_m
        if prompt_first is not None and fit_messages and inc_m
        else None
    )
    model_calls = len(request_ids)
    row = {
        "transcript_id": transcript_id,
        "kind": "sidechain" if sidechain_lines and sidechain_lines == lines_under else "session",
        "truncated_at_cutoff": truncated,
        "cc_versions": sorted(versions),
        "models_recorded": sorted(models),
        # A COUNT, not the names. The first draft committed `sorted(branches)` and
        # `fence_violations()` turned the run red on it: a branch name like
        # `feat/compaction-measured` carries a `/`, and more to the point a branch name is
        # neither a number nor a statistic. The fence found that in this program's own
        # design rather than in a review, which is the whole reason it is mechanical.
        "git_branches_recorded_count": len(branches),
        "lines_total": lines_total,
        "lines_under_cutoff": lines_under,
        "line_types": dict(sorted(line_types.items())),
        "untimestamped_lines_by_type": dict(sorted(untimestamped.items())),
        "content_block_kinds": dict(sorted(block_kinds.items())),
        "assistant_lines": assistant_lines,
        "model_calls": model_calls,
        "model_calls_by_message_id": len(message_ids),
        "synthetic_assistant_lines": synthetic_lines,
        "assistant_lines_per_model_call": _round(
            assistant_lines / model_calls if model_calls else None, 4
        ),
        "user_lines": user_lines,
        "tool_result_lines": tool_result_lines,
        "host_precompacted_boundaries": host_boundaries,
        "host_compact_summary_messages": host_summaries,
        "host_compact_pre_tokens_total": host_pre_tokens,
        "recorded_prompt_tokens_total": prompt_total,
        "recorded_input_tokens_total": input_total,
        "recorded_cache_read_tokens_total": cache_read_total,
        "recorded_cache_creation_tokens_total": cache_creation_total,
        "recorded_output_tokens_total": output_total,
        "recorded_prompt_tokens_peak": prompt_peak,
        "recorded_prompt_tokens_first_call": prompt_first,
        "recorded_prompt_tokens_last_call": prompt_last,
        "message_content_bytes": message_bytes,
        "attachment_bytes": attachment_bytes,
        "assistant_content_bytes": assistant_bytes,
        "bytes_per_output_token": _round(
            assistant_bytes / output_total if output_total else None, 4
        ),
        "fit_calls": len(fit_messages),
        # PRIMARY: the byte definition a replay reconstruction produces.
        "bytes_per_prompt_token_messages_only": _round(
            1.0 / fit_m[0] if fit_m and fit_m[0] else None, 4
        ),
        "fit_intercept_tokens_messages_only": _round(fit_m[1] if fit_m else None, 1),
        "fit_r2_messages_only": _round(fit_m[2] if fit_m else None, 6),
        # UPPER BRACKET: message content plus host-injected attachment bytes.
        "bytes_per_prompt_token_payload": _round(1.0 / fit_p[0] if fit_p and fit_p[0] else None, 4),
        "fit_intercept_tokens_payload": _round(fit_p[1] if fit_p else None, 1),
        "fit_r2_payload": _round(fit_p[2] if fit_p else None, 6),
        # Intercept-free, so a contaminated fixed cost cannot move it.
        "bytes_per_prompt_token_incremental_median": _round(inc_m, 4),
        "bytes_per_prompt_token_incremental_median_payload": _round(inc_p, 4),
        "incremental_points": len(incremental_messages),
        "preamble_tokens_first_call_bound": _round(preamble_bound, 1),
    }
    return row


def build_rows(transcript_root: Path) -> tuple[list[dict], dict]:
    """The corpus rows, plus the selection census every exclusion is counted in."""
    classified, unreadable = classify_tree(transcript_root)
    pure, mixed, outside = [], [], []
    for path, here, other, distinct in classified:
        if here and not other:
            pure.append((path, distinct))
        elif here:
            mixed.append((path, here, other, distinct))
        else:
            outside.append(path)

    rows: list[dict] = []
    zero_call = 0
    for path, _ in pure:
        digest = hashlib.sha256(str(path.relative_to(transcript_root)).encode()).hexdigest()
        row = survey_transcript(path, digest[:16])
        if row["model_calls"] == 0:
            zero_call += 1
            continue
        rows.append(row)
    rows.sort(key=lambda r: r["transcript_id"])

    census = {
        "files_in_universe": len(classified),
        "files_unreadable": unreadable,
        "excluded_outside_the_fence": len(outside),
        "excluded_mixed_cwd": len(mixed),
        "excluded_mixed_cwd_bantamkit_lines": sum(m[1] for m in mixed),
        "excluded_mixed_cwd_other_lines": sum(m[2] for m in mixed),
        "excluded_zero_model_calls": zero_call,
        "corpus_transcripts": len(rows),
    }
    return rows, census


def render(rows: list[dict]) -> str:
    return "".join(json.dumps(row) + "\n" for row in rows)


def fence_violations(text: str) -> list[str]:
    """The user's fence, enforced on the bytes that would be committed.

    Every string anywhere in every row — keys, values, nested objects — is checked for a
    path separator, a `.jsonl` suffix or a home-directory prefix. A filename leaking into
    the artifact is the one failure mode this unit was told bites hardest, so it is
    detected on the rendered text rather than argued about.
    """
    problems: list[str] = []

    def walk(node, where: str) -> None:
        if isinstance(node, str):
            for pattern in _FENCE_PATTERNS:
                if pattern in node:
                    problems.append(f"{where}: {pattern!r} appears in a committed string")
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(key, f"{where}.{key}")
                walk(value, f"{where}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{where}[{index}]")

    for index, line in enumerate(text.splitlines()):
        if line.strip():
            walk(json.loads(line), f"row {index}")
    return problems


def compare_on_committed_keys(
    committed_text: str, regenerated: list[dict]
) -> tuple[list[str], list[str]]:
    """NAMED COLUMNS, row for row, matched by `transcript_id`. Never bytes of the file.

    The bar's §9 in the form RB-P46 forced: the row count is exact; a committed
    transcript that is no longer on disk fails; every key the committed row carries is
    compared by its serialised bytes, so `200` against `200.0` fails; a key on the
    regenerated side that the committed row lacks fails unless it is DECLARED in
    `ADDITIVE_KEYS_THE_ARTIFACT_PREDATES`; a committed key deleted from the row fails,
    because it becomes an undeclared key on the regenerated side; and the committed keys
    reordered among themselves fail.

    Matched by `transcript_id` rather than by position because the corpus is a directory
    and its iteration order is not a property this artifact should be asserting. The
    cutoff is what makes the matching total: nothing recorded after the bar was frozen
    can join the corpus, so a regenerated row with no committed counterpart is a real
    failure and not the corpus growing.
    """
    problems: list[str] = []
    committed_lines = [line for line in committed_text.splitlines() if line.strip()]
    if len(committed_lines) != len(regenerated):
        problems.append(
            f"row count: committed {len(committed_lines)}, regenerated {len(regenerated)}"
        )
        return problems, []

    by_id = {row["transcript_id"]: row for row in regenerated}
    added: list[str] = []
    for index, line in enumerate(committed_lines):
        committed = json.loads(line)
        committed_keys = list(committed)
        regen = by_id.get(committed.get("transcript_id"))
        if regen is None:
            problems.append(
                f"row {index}: the committed transcript is not in the regenerated corpus"
            )
            continue
        residual = [
            key
            for key in regen
            if key in committed_keys or key not in ADDITIVE_KEYS_THE_ARTIFACT_PREDATES
        ]
        for key in regen:
            if key not in committed_keys and key not in added:
                added.append(key)
        if residual != committed_keys:
            problems.append(
                f"row {index}: the regenerated keys are not the committed keys plus "
                f"declared additions, so this is not an additive change"
            )
            problems.append(f"    committed keys:          {committed_keys}")
            problems.append(f"    regenerated, undeclared: {residual}")
            continue
        for key in committed_keys:
            got = json.dumps(regen[key])
            want = json.dumps(committed[key])
            if got != want:
                problems.append(f"row {index}: column {key!r} differs")
                problems.append(f"    committed:   {want}")
                problems.append(f"    regenerated: {got}")
    return problems, added


def _quantiles(values: list[float]) -> dict[str, float]:
    """min / p25 / median / p75 / max, by the nearest-rank rule, stated rather than assumed."""
    if not values:
        return {}
    ordered = sorted(values)
    n = len(ordered)

    def at(fraction: float) -> float:
        return ordered[min(n - 1, max(0, round(fraction * (n - 1))))]

    return {
        "n": n,
        "min": ordered[0],
        "p25": at(0.25),
        "median": (
            ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
        ),
        "p75": at(0.75),
        "max": ordered[-1],
        "sum": sum(ordered),
    }


def _print_distribution(label: str, values: list[float], digits: int = 0) -> None:
    stats = _quantiles(values)
    if not stats:
        print(f"  {label:44s} (no values)")
        return
    fmt = f"{{:.{digits}f}}"
    print(
        f"  {label:44s} n={stats['n']:<5} min={fmt.format(stats['min']):>12} "
        f"p25={fmt.format(stats['p25']):>12} med={fmt.format(stats['median']):>12} "
        f"p75={fmt.format(stats['p75']):>12} max={fmt.format(stats['max']):>12} "
        f"sum={fmt.format(stats['sum']):>16}"
    )


def report(rows: list[dict], census: dict) -> None:
    print(RULE)
    print("SELECTION CENSUS — every exclusion with its count")
    print(RULE)
    for key, value in census.items():
        print(f"  {key:44s} {value:>12}")
    print()

    print(RULE)
    print("model_calls DERIVED PROPERLY, AGAINST THE LINE-LEVEL APPROXIMATION")
    print(RULE)
    proper = sum(r["model_calls"] for r in rows)
    by_msg = sum(r["model_calls_by_message_id"] for r in rows)
    lines = sum(r["assistant_lines"] for r in rows)
    synth = sum(r["synthetic_assistant_lines"] for r in rows)
    print(f"  assistant LINES (the approximation)         {lines:>12}")
    print(f"  model_calls, distinct requestId             {proper:>12}")
    print(f"  model_calls, distinct message.id            {by_msg:>12}")
    print(f"  the two derivations agree                   {proper == by_msg!s:>12}")
    print(f"  synthetic assistant lines (not calls)       {synth:>12}")
    if proper:
        print(f"  divergence, lines minus calls               {lines - proper:>12}")
        print(f"  divergence, lines / calls                   {lines / proper:>12.4f}")
        print(f"  the approximation OVERSTATES calls by       {lines / proper - 1:>11.2%}")
    print()
    _print_distribution("assistant lines per transcript", [r["assistant_lines"] for r in rows])
    _print_distribution("model_calls per transcript", [r["model_calls"] for r in rows])
    _print_distribution(
        "lines per call, per transcript",
        [r["assistant_lines_per_model_call"] for r in rows if r["assistant_lines_per_model_call"]],
        3,
    )
    print()

    print(RULE)
    print("HOST-LEVEL COMPACTION ALREADY IN THE RECORDINGS — bar §5.4 outcome U-4")
    print(RULE)
    with_boundary = [r for r in rows if r["host_precompacted_boundaries"]]
    print(f"  transcripts with >=1 host boundary          {len(with_boundary):>12}")
    print(f"  transcripts with 0                          {len(rows) - len(with_boundary):>12}")
    print(f"  host boundaries, total                      "
          f"{sum(r['host_precompacted_boundaries'] for r in rows):>12}")
    print(f"  host compact-summary messages, total        "
          f"{sum(r['host_compact_summary_messages'] for r in rows):>12}")
    print(f"  Σ recorded preTokens at those boundaries    "
          f"{sum(r['host_compact_pre_tokens_total'] for r in rows):>12}")
    print("  U-4 fires on the whole run only if EVERY transcript is non-zero. Reported,")
    print("  not interpreted: the interpretation is U4's and it needs the arms.")
    print()

    print(RULE)
    print("THE TOKEN FACTOR, FITTED FROM RECORDED USAGE — bar §10.3, fallback NOT taken")
    print(RULE)
    usage_rows = [r for r in rows if r["recorded_prompt_tokens_total"]]
    print(f"  transcripts carrying per-call usage         {len(usage_rows):>12} of {len(rows)}")
    print("  the §10.3(4) UNMEASURED-IN-TOKENS fallback is NOT taken: usage is present")
    fitted = [r for r in rows if r["bytes_per_prompt_token_messages_only"] is not None]
    print(f"  transcripts with a usable fit (>=3 calls)   {len(fitted):>12}")
    print()
    print("  PRIMARY — messages_only, the byte definition a replay reconstruction produces:")
    _print_distribution(
        "bytes_per_prompt_token_messages_only",
        [r["bytes_per_prompt_token_messages_only"] for r in fitted],
        4,
    )
    _print_distribution("  its fit r2", [r["fit_r2_messages_only"] for r in fitted], 6)
    _print_distribution(
        "  its fit intercept, tokens",
        [r["fit_intercept_tokens_messages_only"] for r in fitted],
        1,
    )
    _print_distribution(
        "  intercept-free incremental median",
        [
            r["bytes_per_prompt_token_incremental_median"]
            for r in rows
            if r["bytes_per_prompt_token_incremental_median"] is not None
        ],
        4,
    )
    print()
    print("  UPPER BRACKET — payload, message content plus host-injected attachments:")
    _print_distribution(
        "bytes_per_prompt_token_payload",
        [r["bytes_per_prompt_token_payload"] for r in fitted],
        4,
    )
    _print_distribution("  its fit r2", [r["fit_r2_payload"] for r in fitted], 6)
    _print_distribution(
        "  its fit intercept, tokens (SIGNED)",
        [r["fit_intercept_tokens_payload"] for r in fitted],
        1,
    )
    print("  A negative intercept is a measurement, not a defect to clamp: serialised")
    print("  attachment bytes over-count what crossed the wire. Note what the two fits")
    print("  agree on and what they do not — the SLOPES agree to four decimals and the")
    print("  whole difference lands in the intercept, so the attachment bytes are a")
    print("  near-constant offset. The byte definition barely moves the factor and")
    print("  decides the fixed cost.")
    print()
    _print_distribution(
        "preamble tokens, first-call bound (SIGNED)",
        [
            r["preamble_tokens_first_call_bound"]
            for r in rows
            if r["preamble_tokens_first_call_bound"] is not None
        ],
        1,
    )
    print("  The fixed per-call cost that is billed and is in NO transcript: system")
    print("  prompt, tool schemas, project instructions. U4's reconstruction cannot")
    print("  produce it and must add it as a declared constant or report without it.")
    print()
    _print_distribution(
        "bytes_per_output_token (independent estimate)",
        [r["bytes_per_output_token"] for r in rows if r["bytes_per_output_token"]],
        4,
    )
    print("  A DIFFERENT quantity and not blended into the prompt factor: an output is")
    print("  model prose and code, a prompt is dominated by tool output.")
    print()
    primary = _quantiles([r["bytes_per_prompt_token_messages_only"] for r in fitted])
    if primary:
        print("  AGAINST THE MECHANISM'S OWN ESTIMATOR, which the bar refuses as an axis")
        print("  (§10.3, source constant `Math.ceil(text.length / 4)` at src/session.ts:10):")
        print(f"    the mechanism assumes                       {4.0:>12.4f} B/token (ASCII)")
        print(f"    this corpus measures, median                {primary['median']:>12.4f} B/token")
        print(f"    so it UNDER-counts prompt tokens by         "
              f"{4.0 / primary['median']:>12.4f} x")
        print("  Reported as one measured ratio, not as a correction factor to apply: the")
        print("  bar's axis is the measured factor, and the mechanism's estimate is never")
        print("  the axis. This line exists because §10.3 refuses `chars/4` on two grounds")
        print("  and this is the size of the first one, on this corpus.")
        print()

    print(RULE)
    print("THE CORPUS, AS DISTRIBUTIONS")
    print(RULE)
    _print_distribution("lines under cutoff", [r["lines_under_cutoff"] for r in rows])
    _print_distribution("user lines", [r["user_lines"] for r in rows])
    _print_distribution("tool-result lines", [r["tool_result_lines"] for r in rows])
    _print_distribution("message content bytes", [r["message_content_bytes"] for r in rows])
    _print_distribution("attachment bytes", [r["attachment_bytes"] for r in rows])
    _print_distribution("assistant content bytes", [r["assistant_content_bytes"] for r in rows])
    _print_distribution("recorded prompt tokens, Σ over calls",
                        [r["recorded_prompt_tokens_total"] for r in rows])
    _print_distribution("recorded prompt tokens, peak call",
                        [r["recorded_prompt_tokens_peak"] for r in rows])
    _print_distribution("recorded output tokens, Σ", [r["recorded_output_tokens_total"] for r in rows])
    print()
    print("  Recorded prompt tokens are input_tokens + cache_creation_input_tokens +")
    print("  cache_read_input_tokens, the three fields the whole prompt is split across.")
    print("  `recorded_input_tokens_total` alone is the UNCACHED remainder and is not the")
    print("  prompt: Σ over the corpus is "
          f"{sum(r['recorded_input_tokens_total'] for r in rows)} against a prompt Σ of "
          f"{sum(r['recorded_prompt_tokens_total'] for r in rows)}.")
    print()
    kinds: dict[str, int] = {}
    for row in rows:
        for key, value in row["line_types"].items():
            kinds[key] = kinds.get(key, 0) + value
    skipped: dict[str, int] = {}
    for row in rows:
        for key, value in row["untimestamped_lines_by_type"].items():
            skipped[key] = skipped.get(key, 0) + value
    print("  Event kinds under the cutoff (bar §1.2 wants every kind enumerated):")
    for key, value in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"    {key:36s} {value:>12}")
    print("  Untimestamped lines, by kind — outside every statistic here, enumerated:")
    for key, value in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print(f"    {key:36s} {value:>12}")
    print()
    sessions = [r for r in rows if r["kind"] == "session"]
    print(f"  transcripts by kind: session={len(sessions)} "
          f"sidechain={len(rows) - len(sessions)}")
    print(f"  transcripts truncated at the cutoff: "
          f"{sum(1 for r in rows if r['truncated_at_cutoff'])}")
    versions: dict[str, int] = {}
    for row in rows:
        for value in row["cc_versions"]:
            versions[value] = versions.get(value, 0) + 1
    print(f"  Claude Code versions across the corpus: {dict(sorted(versions.items()))}")
    print()

    print(RULE)
    print("THE CORPUS AGAINST THE MECHANISM'S OWN THRESHOLD — DESCRIPTIVE, NOT A SCHEDULE")
    print(RULE)
    print(f"  T = COMPACTION_PROACTIVE_PCT x COMPACTION_TOKEN_BUDGET = {THRESHOLD_T} tokens")
    print("  (both read from source at bar §10.1; NOT tuned to this corpus, NOT chosen here)")
    print()
    print("  Two readings of bar §10.2 give two different corpora, and this program does")
    print("  not choose between them — applying a schedule is U4's. The arithmetic:")
    reach = [r for r in rows if r["recorded_prompt_tokens_peak"] >= THRESHOLD_T]
    print("    reading A — T as LIVE-WINDOW occupancy, the mechanism's own meaning:")
    print(f"      transcripts whose PEAK recorded prompt reaches T   {len(reach):>8} of {len(rows)}")
    print(f"      transcripts that never reach it (bar U-2)          {len(rows) - len(reach):>8}")
    _print_distribution("      peak prompt tokens / T",
                        [r["recorded_prompt_tokens_peak"] / THRESHOLD_T for r in rows], 4)
    print("    reading B — T as CUMULATIVE re-send, the words of §10.2 as written:")
    _print_distribution("      Σ prompt tokens / T  (= boundaries implied)",
                        [r["recorded_prompt_tokens_total"] / THRESHOLD_T for r in rows], 2)
    print("  The two readings differ by orders of magnitude on the same corpus. That is a")
    print("  question about the bar, and the bar is committed, so it is ESCALATED and not")
    print("  edited. Nothing in this program depends on the answer.")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The compaction corpus survey.")
    parser.add_argument("repo_root", nargs="?", default=".", type=Path)
    parser.add_argument(
        "--transcript-root",
        type=Path,
        default=None,
        help="where transcripts live; defaults to ~/.claude/projects",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate and compare NAMED COLUMNS with the committed artifact; writes nothing",
    )
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    transcript_root = (args.transcript_root or DEFAULT_TRANSCRIPT_ROOT).resolve()
    out = root / "docs" / "eval-data" / ARTIFACT

    print(RULE)
    print("THE COMPACTION CORPUS — bantamkit transcripts only, numbers only")
    print(RULE)
    print(f"pytest in sys.modules: {'pytest' in sys.modules}   (must be False)")
    if "pytest" in sys.modules:
        print("FATAL: pytest is imported. This program is the evidence, not a node.")
        return 2
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    print(f"repo root:             {root}")
    print(f"git HEAD:              {head or 'unknown'}")
    print(f"cutoff (UTC):          {CUTOFF_UTC}   (the bar's commit instant, f48335c)")
    print(f"mode:                  {'--check (writes nothing)' if args.check else 'write'}")
    print("runs no arm:           no compaction, no summarizer, no delta, no saving")
    print()

    if not transcript_root.is_dir():
        print(f"FAILED — no transcript root at {transcript_root}")
        return 1

    rows, census = build_rows(transcript_root)
    if not rows:
        # A survey that found nothing writes an empty artifact and reports success, which
        # is the shape of failure RB-P41 is about one directory over. Zero rows here means
        # the classification found no bantamkit transcript at all, and that is a broken
        # instrument, not an empty corpus.
        print(f"FAILED — no transcript classified into the corpus under {transcript_root}.")
        print(f"         census: {census}")
        return 1
    text = render(rows)

    violations = fence_violations(text)
    print(RULE)
    print("THE USER'S FENCE, CHECKED ON THE RENDERED BYTES")
    print(RULE)
    print(f"  rows rendered                              {len(rows):>12}")
    print(f"  fence violations                           {len(violations):>12}")
    for problem in violations:
        print(f"    {problem}")
    print()
    if violations:
        print("FAILED — a committed row would carry a path, a filename or a home prefix.")
        return 1

    report(rows, census)

    if args.check:
        if not out.exists():
            print(f"FAILED — {ARTIFACT} is not there, so there is nothing to check against.")
            return 1
        problems, added = compare_on_committed_keys(out.read_text(), rows)
        print(RULE)
        if problems:
            print(f"FAILED — {ARTIFACT} does not reproduce on its named columns.")
            for problem in problems[:40]:
                print(f"  {problem}")
            if len(problems) > 40:
                print(f"  ... and {len(problems) - 40} more")
            return 1
        print(f"OK — {ARTIFACT} reproduces on every named column, {len(rows)} rows.")
        if added:
            print(f"     declared additive columns seen: {', '.join(added)}")
        print(RULE)
        return 0

    out.write_text(text)
    print(RULE)
    print(f"WROTE {ARTIFACT} — {len(text)} B, {len(rows)} rows.")
    print(RULE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
