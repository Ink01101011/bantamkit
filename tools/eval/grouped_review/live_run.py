"""#310 live grouped-review evaluation: one matched live job per (case, repeat, arm).

Authors, repairers and integrators are Codex ``exec`` agents writing real code in the
arm's own copy of the fixture; reviewers are fresh read-only Codex contexts with the
#307 settings. Every unit is a real Shiftwork unit in a per-arm checkpoint driven over
MCP stdio (``node runtime-ts/dist/cli.js``): clock-in before each model call, clock-out
with accounting after it. Planning and dispatch are this deterministic code: zero model
tokens, recorded as such. Design: docs/superpowers/specs/2026-11-13-grouped-review-live-eval-design.md.

Missing usage is unknown (None), never zero. ``summarize_live`` recomputes everything
from runs.jsonl; ``adoption`` can never be ``adopt`` because the five scenarios of the
frozen protocol are not run here.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import glob
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"grouped_live_run_{name}", HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


live_cases = _load("live_cases")
run_eval = _load("run_eval")
codex_adapter = _load("codex_adapter")

ROOT = codex_adapter.ROOT
MODEL = codex_adapter.MODEL
SCHEMA_PATH = ROOT / "assets/schemas/shiftwork-checkpoint.json"
MAX_REPAIR_ROUNDS = 2
BUDGET_GATE_TOKENS = 12_000_000
FULL_RUN_JOBS = 18
SMOKE_CASE = "mixed-fork-join"
ARMS = ("per-task", "grouped")
AGENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PLANNER_DISPATCH = {
    "model_tokens": 0,
    "label": "deterministic harness code (planner and dispatcher); no model call, exact zero",
}
AUTHOR_SETTINGS = {
    "model": MODEL,
    "reasoning_effort": "medium",
    "sandbox": "workspace-write (arm workspace)",
    "shell": True,
    "disabled": ["apps", "multi_agent"],
    "web_search": "disabled",
}
REVIEW_SETTINGS = {**codex_adapter.SETTINGS, "model": MODEL, "sandbox": "read-only"}
LIMITS = [
    "Core execution modes only; the five scenarios of the frozen protocol were not run, "
    "so adoption beyond review-only guidance cannot be decided from these data.",
    "Planner and dispatcher are deterministic harness code with zero model tokens in both "
    "arms; a real orchestrator spends tokens this harness does not.",
    "Seeds are mutations of live author output, so the seeded criterion can differ between "
    "arms; the missed-defect comparison is per seeded unit, both arms having a seed.",
    "Small samples (three repeats per mode) support limited pilot guidance only.",
    "Arm order is counterbalanced by repeat, but three repeats give a 2:1 order imbalance "
    "per mode (two repeats run per-task first, one runs grouped first).",
    "Seeds are loud mutations (a seeded criterion fails outright), so the missed-defect "
    "threshold has little power against subtle defects a grouped reviewer might miss.",
    "The mixed-fork-join contract seed (unit K) is reviewed by its own gate reviewer in both "
    "arms, so catching it says nothing about grouping.",
    "A harness censor (Codex failure, MCP refusal, unexpected exception, access-audit hit) "
    "voids the whole pair, which is rerun once; a pair censored twice is inconclusive, never "
    "a pass or a fail. Voided attempts are kept with their spend.",
    "The access audit reads command text only, so a read made inside a script the author "
    "runs (for example a Python file that opens a path) is invisible to it.",
    "Seeds removed before review are left out of the comparison; in the grouped "
    "native-chain arm the one parent session can silently fix its own earlier seed, which "
    "then drops out of the comparison instead of counting as caught or missed.",
    "Isolated adjudication replaces other units' files by the reference, so a downstream "
    "finding caused by an upstream seed that is still present is judged false; that only "
    "happens in the grouped arm, where the upstream seed survives until the group review.",
    "In grouped sequential-delegates the repairs A2 and C2 can run concurrently after one "
    "group rejection, while the per-task arm never runs two repairs at once.",
    "Write attribution hashes the workspace at every author-call and seed boundary; inside "
    "a span where two calls run at once, a change no file_change event names is credited "
    "to the one running unit that owns the file, so a shell write to a concurrently running "
    "owner's file in that span is not seen as a conflict.",
]
HARNESS_MODEL = "harness-no-model"
HUMAN_INTERVENTIONS_LABEL = "unattended; any manual action voids the arm"
# Path components an author must never touch: the hidden judge, the reference
# implementation and the run's own output.
FORBIDDEN_NAME = re.compile(
    r"live_fixtures|runs\.jsonl|oracle\.py|(?:^|[/\s'\"=])(?:oracle|reference|arms|calls)/"
    r"|/(?:oracle|reference|arms|calls)(?:$|[\s'\";|&)])"
)
# A path only when a name character follows the slash: `/ 100` (division), `//`
# (floor division) and a bare `/` are not paths here (QW round 2, finding 1).
ABS_PATH = re.compile(
    r"(?:^|(?<=[\s'\"=:(<>]))(~/[^\s'\";|&<>()`]*|~(?=[\s'\";|&<>()`]|$)"
    r"|/[A-Za-z0-9_.~-][^\s'\";|&<>()`]*)"
)
# Everything after `://` is a URL, never a local path; `file://` keeps its path.
URL = re.compile(r"\b(?!file://)[A-Za-z][A-Za-z0-9+.-]*://[^\s'\";|&<>()`]*")
# A bare `/` (or `/.`, `/*`) is the filesystem root only as an argument of these.
FS_COMMAND = re.compile(
    r"(?:^|(?<=[\s;&|(`'\"]))(find|ls|grep|rg|du|cat|tree|cd)(?=[\s'\"]|$)([^;&|\n]*)"
)
ROOT_ARG = re.compile(r"""(?:^|(?<=\s))['"]?/[.*]?['"]?(?=\s|$)""")
RECURSIVE = re.compile(r"(?:^|\s)(?:-[A-Za-z]*[rR][A-Za-z]*|--recursive|--dereference-recursive)"
                       r"(?=\s|$)")
SYSTEM_PREFIXES = (
    "/bin/", "/usr/", "/sbin/", "/etc/", "/private/etc/", "/opt/homebrew/", "/System/",
    "/Library/", "/dev/null", "/dev/stdout", "/dev/stderr", "/dev/stdin", "/dev/tty",
)

AUTHOR_PROMPT = (
    "You are an author agent. Your working directory is a small Python package "
    "workspace. Do exactly the work in the clocked Shiftwork brief below. Edit only "
    "the files you own (named in the brief), and stay inside this directory. You may "
    "run the fast check the brief names. End with a short summary of what you changed.\n"
)
REPAIR_PROMPT = (
    "You are repairing your earlier work after an independent review. Fix every "
    "reviewer finding quoted verbatim in the clocked Shiftwork brief below, keeping all "
    "acceptance criteria satisfied. Edit only the files you own (named in the brief), "
    "stay inside this directory, and run the fast check. End with a short summary.\n"
)
INTEGRATION_PROMPT = (
    "You are the integration recheck after an upstream repair. Re-run every fast check "
    "listed in the clocked Shiftwork brief below. If one fails, repair the listed files "
    "so it passes again without changing the repaired upstream behaviour. Stay inside "
    "this directory. End with a short summary of the checks and any change.\n"
)
REVIEW_PROMPT = (
    "Review only the request in this clocked brief. Do not use tools, read files, or "
    "infer defects from stage labels. Return findings only for units in membership, each "
    "naming one of that unit's acceptance-criterion IDs. Echo reviewer_context_id exactly "
    "and give, for every member, its exact supplied revision and every criterion ID you "
    "checked. Use findings: [] only when no defect remains.\n"
)
REVIEW_INSTRUCTIONS = (
    "Independently review every unit in membership against each of its acceptance "
    "criteria, using context_files (the integrated workspace files at the exact reviewed "
    "revision). Report concrete defects as {unit, criterion, detail}. Evidence binds "
    "{unit, revision, criteria} to the supplied revision."
)
PROMPTS = {
    "author": AUTHOR_PROMPT,
    "repair": REPAIR_PROMPT,
    "integration": INTEGRATION_PROMPT,
    "review": REVIEW_PROMPT,
    "review_instructions": REVIEW_INSTRUCTIONS,
}

# --- the tuning comparison (job84, docs/superpowers/specs/2026-11-13-grouped-review-
# tuning-design.md). Nothing below changes a #310 arm: a variant with no levers runs the
# exact plans, prompts and argv of the #310 run.
TUNING_DESIGN = "docs/superpowers/specs/2026-11-13-grouped-review-tuning-design.md"
TUNING_LEVERS = ("T1", "T2", "T3", "T4")
VARIANTS = {
    "per-task": {"arm": "per-task", "levers": ()},
    "grouped": {"arm": "grouped", "levers": ()},
    "baseline-grouped": {"arm": "grouped", "levers": ()},
    "tuned-grouped": {"arm": "grouped", "levers": TUNING_LEVERS},
    # The RR comparison (reviewer thread resume): both arms carry T1, T2 and T4; only the
    # second adds RR (RR_DESIGN, *Frozen comparison design*). T3 is not a lever here: RR
    # delivers a re-review as a delta turn in the reviewer's own thread.
    "repair-tuned": {"arm": "grouped", "levers": ("T1", "T2", "T4")},
    "repair-tuned-rr": {"arm": "grouped", "levers": ("T1", "T2", "T4", "RR")},
    # The AB comparison (batched author prompt): rr-base is exactly repair-tuned-rr's
    # configuration; rr-batched adds the one lever AB (BATCH_DESIGN, *Arms*).
    "rr-base": {"arm": "grouped", "levers": ("T1", "T2", "T4", "RR")},
    "rr-batched": {"arm": "grouped", "levers": ("T1", "T2", "T4", "RR", "AB")},
}
COMPARISONS = {"310": ARMS, "tuning": ("baseline-grouped", "tuned-grouped"),
               "rr": ("repair-tuned", "repair-tuned-rr"),
               "batch": ("rr-base", "rr-batched")}
TUNING_VARIANTS = COMPARISONS["tuning"]
RR_VARIANTS = COMPARISONS["rr"]
BATCH_VARIANTS = COMPARISONS["batch"]
TUNING_JOBS = 12
TUNING_REPEATS = 2
DEFAULT_REPEATS = {"310": 3, "tuning": TUNING_REPEATS}
RR_DESIGN = "docs/superpowers/specs/2026-11-13-reviewer-thread-resume-draft.md"
RR_JOBS = 8
RR_REPEATS = 2
RR_CASES = ("native-chain", "sequential-delegates")
RR_CAP_MARGIN = 400_000
BATCH_DESIGN = "docs/superpowers/specs/2026-11-13-batched-author-design.md"
BATCH_JOBS = 8
BATCH_REPEATS = 2
BATCH_CASES = RR_CASES
BATCH_CAP_MARGIN = 400_000
# At most two resumes per thread: the repair cap (MAX_REPAIR_ROUNDS) already bounds it.
MAX_RESUMES = 2
# T1: no --output-schema, so the shape is spelled out here. The fixed text comes first
# (the #310 reviewer prompt, unchanged, then the shape) and the variable data last.
TUNED_REVIEW_PROMPT = REVIEW_PROMPT + (
    "Reply with exactly one JSON object and nothing else: no prose, no code fence. Its "
    'shape is {"reviewer_context_id": string, "findings": [{"unit": string, '
    '"criterion": string, "detail": string}], "evidence": [{"unit": string, '
    '"revision": string, "criteria": [string]}]}, with exactly one evidence row per '
    "member.\n"
)
# T2: one tools-disabled call returns whole files; the harness writes only owned paths.
PATCH_PROMPT = (
    "You are repairing your earlier work after an independent review. You have no tools: "
    "do not try to run commands or read files. Fix every reviewer finding quoted verbatim "
    "in the clocked Shiftwork brief below, keeping all acceptance criteria satisfied, by "
    "returning the complete corrected text of the files you change. The current text of "
    "every file you own follows the brief. Reply with exactly one JSON object and nothing "
    'else: no prose, no code fence. Its shape is {"files": [{"path": string, "content": '
    "string}]}: each path exactly as named under Files you own, each content the whole "
    "new file. Any other path makes the whole answer invalid.\n"
)
# T3: the re-review request carries the previous findings and per-member change flags.
DELTA_INSTRUCTIONS = (
    "This is a re-review. previous_findings are the last review's findings of this group, "
    "verbatim. Re-check in full, against every criterion, each member whose "
    "changed_since_last_review is true and each member that consumes one of them. For a "
    "member whose changed_since_last_review is false you may reuse the previous review's "
    'evidence: add "reused" to its evidence row, naming the reused evidence and why it '
    "remains valid. A new finding on an unchanged member is allowed, but its detail must "
    "say why the earlier review missed it. Evidence must still name every member, with "
    "its exact supplied revision and every criterion ID."
)
TUNING_PROMPTS = {
    "review_t1": TUNED_REVIEW_PROMPT,
    "repair_patch_t2": PATCH_PROMPT,
    "repair_fallback_t2": REPAIR_PROMPT,
    "review_delta_instructions_t3": DELTA_INSTRUCTIONS,
}
# RR: the re-review turn resumed in the reviewer's own thread. The previous request and the
# reviewer's own previous answer are already in that thread, so only the changed files, the
# new context id, every member's revision and fast check and the change flags are sent.
# The wording is the P0 probe's (rr_probe.py), which is what was measured.
RR_DELTA_PROMPT = (
    "RE-REVIEW of the same group, in this same conversation. Your previous request and your "
    "previous answer above still hold for anything not listed as changed. Only the files "
    "below changed; the text of every other file is exactly as in the previous request. "
    + DELTA_INSTRUCTIONS + " Reply with exactly one JSON object and nothing else, in the "
    "same shape as before, echoing the new reviewer_context_id.\n\nRE-REVIEW DELTA:\n"
)
RR_PROMPTS = {"review_rr_delta_turn": RR_DELTA_PROMPT}
# AB: the batching paragraph of probe B, verbatim from BATCH_DESIGN. It goes between
# AUTHOR_PROMPT (which ends in a newline) and the brief view, on every author call of the
# batched arm and on no other call.
AB_PARAGRAPH = (
    "Work in as few tool steps as you can: do not explore or re-read files you "
    "already have in this prompt; write each file you own completely in a single "
    "edit; then run the fast check once. Only if it fails, fix and run it again.\n"
)
BATCH_PROMPTS = {"author_batching_paragraph_ab": AB_PARAGRAPH}
BATCH_LIMITS = [
    "n = 2 per mode: a better verdict supports the batching paragraph in these scopes "
    "only, not a general claim.",
    "The seeds are loud, so both arms are likely to catch all of them; the seed gate has "
    "little power, as in #310.",
    "Fewer exploratory steps could hide a quality cost that the oracle does not test; only "
    "the gates guard against it.",
    "Author cache misses are server-side noise. The comparison is paired but cannot remove "
    "that noise.",
    "The paragraph sits between AUTHOR_PROMPT and the brief view, as the design's arm table "
    "says; probe B measured it appended at the end of the prompt, so the effect size may "
    "differ from the probe's.",
]
TUNING_LIMITS = [
    "Two repeats per mode is a small sample: a better verdict supports tuning the host's "
    "guidance in these scopes only, not a general claim.",
    "Patch-mode repair changes how native-chain repairs: a fresh tools-free call replaces "
    "the parent session. That is part of what is being tested.",
    "The seeds are loud, so both arms are likely to catch all of them; the seed gate has "
    "little power, as in #310.",
    "T1 removes the output schema: answer validity rests on the prompt and the harness "
    "check, so invalid answers are counted and reported.",
    "Reviewer-call cost reflects T1 and T3 together and repair-call cost T2 and T4 "
    "together; the levers inside each pair are not separated, and two repeats cannot rank "
    "them.",
]
RR_LIMITS = [
    "Two repeats per mode is a small sample: a better verdict supports resuming the "
    "reviewer's own thread for re-reviews in these scopes only, not a general claim.",
    "The seeds are loud, so both arms are likely to catch all of them; the seed gate has "
    "little power, as in #310. Anchoring on the reviewer's own earlier approval shows only "
    "through the gates.",
    "The P0 probe that cleared RR ran on one group only.",
    "A re-review resumes the reviewer's own thread, which overrides the #310 design's "
    "literal 'fresh context' wording for RR runs only (maintainer ruling 2026-11-13); an "
    "author never shares that thread.",
    "The base arm's Codex cache hit is not reliable: in the tuning run 4 of 9 baseline "
    "reviewer calls read 0 cached. Per-call cache reads are recorded so the result can "
    "say so; the base arm is not changed.",
]


class ArmStopped(Exception):
    """A refusal or failure that ends an arm as failed/censored."""


class ShiftworkRefusal(ArmStopped):
    def __init__(self, tool: str, value: dict):
        super().__init__(f"{tool}: {value.get('result')}: {value.get('reason')}")
        self.escalate = value.get("result") == "escalate"


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
        if "__pycache__" in path.parts:
            continue
        h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        h.update(path.read_bytes() + b"\0")
    return h.hexdigest()


# --- usage ------------------------------------------------------------------------


def parse_usage(raw: str) -> dict | None:
    """Usage of one Codex call: every ``turn.completed`` once, categories separate.

    None when the call reported no usage, an incomplete row or an invalid value:
    unknown, never zero.
    """
    try:
        totals = codex_adapter.extract_usage(raw)
    except ValueError:
        return None
    if not totals:
        return None
    turns = 0
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "turn.completed":
            turns += 1
    return {
        "uncached_input": totals["input_tokens"],
        "cache_read": totals["cache_read_input_tokens"],
        "output": totals["output_tokens"],
        "turns": turns,
    }


def sum_usage(usages: list) -> dict | None:
    """Sum known usages; any unknown member makes the sum unknown."""
    total = {"uncached_input": 0, "cache_read": 0, "output": 0, "turns": 0}
    for usage in usages:
        if usage is None:
            return None
        for key in total:
            total[key] += usage[key]
    return total


def usage_tokens(usage: dict | None, include_cache: bool = True) -> int | None:
    if usage is None:
        return None
    return (
        usage["uncached_input"]
        + usage["output"]
        + (usage["cache_read"] if include_cache else 0)
    )


def clock_accounting(usage: dict | None, duration_ms: int, note: str) -> dict:
    """Shiftwork's line: ``tokens`` excludes cache reads; unknown is a flagged sentinel."""
    if usage is None:
        return {
            "tokens": 0,
            "estimate": True,
            "duration_ms": duration_ms,
            "model": MODEL,
            "note": "usage unknown (no complete turn.completed usage); 0 is a sentinel, "
            "not free work. " + note,
        }
    return {
        "tokens": usage["uncached_input"] + usage["output"],
        "cache_read_tokens": usage["cache_read"],
        "duration_ms": duration_ms,
        "model": MODEL,
        "note": note,
    }


def thread_ids(raw: str) -> list[str]:
    ids = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "thread.started":
            if isinstance(event.get("thread_id"), str):
                ids.append(event["thread_id"])
    return ids


def _events(raw: str):
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def turn_usages(raw: str) -> list:
    """Every ``turn.completed`` usage row exactly as Codex reported it (per call)."""
    return [e.get("usage") for e in _events(raw) if e.get("type") == "turn.completed"]


# Codex `exec resume` reports the SESSION's running total in ``turn.completed``, not the
# call's own usage (measured 2026-11-13: identical "OK" turns reported output 5, 10, 15).
REQUIRED_USAGE = ("input_tokens", "cached_input_tokens", "output_tokens")


def reported_total(rows: list) -> tuple[dict | None, str | None]:
    """The running total a call reported: every numeric field of its last
    ``turn.completed`` row, raw. None with a reason for no row or an incomplete or
    invalid row anywhere in the call."""
    if not rows:
        return None, "no turn.completed usage"
    for row in rows:
        if not isinstance(row, dict) or any(
            type(row.get(k)) is not int or row[k] < 0 for k in REQUIRED_USAGE
        ):
            return None, "incomplete or invalid turn.completed usage"
    last = {k: v for k, v in rows[-1].items() if type(v) is int}
    if any(v < 0 for v in last.values()):
        return None, "negative turn.completed usage"
    return last, None


def summed_rows(rows: list) -> dict | None:
    """A fresh call's own raw figures: its rows summed field by field, as parse_usage."""
    total: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            return None
        for key, value in row.items():
            if type(value) is int:
                total[key] = total.get(key, 0) + value
    return total or None


def call_delta(reported: dict | None, previous: dict | None) -> tuple[dict | None, str | None]:
    """A resumed call's own raw figures: its reported total minus the previous call's
    reported total on the same thread, field by field. Unknown (None, with a reason) when
    there is no earlier total or any required field falls, which a true cumulative
    counter never does (so output falling below the earlier output is caught here). A
    field reported only now has no baseline: its delta is None, the usage stays known."""
    if reported is None:
        return None, "the resumed call reported no complete total"
    if previous is None:
        return None, "resumed call with no earlier reported total on its thread"
    delta: dict[str, int | None] = {}
    for key in sorted(set(reported) | set(previous)):
        if key not in reported:
            if key in REQUIRED_USAGE:
                return None, f"{key} missing from the resumed total"
            continue
        if key not in previous:
            delta[key] = None
            continue
        diff = reported[key] - previous[key]
        if diff < 0:
            return None, (f"{key} fell from {previous[key]} to {reported[key]}: "
                          "not a cumulative total")
        delta[key] = diff
    return delta, None


def usage_of_raw(raw: dict | None, turns: int) -> tuple[dict | None, str | None]:
    """The harness's usage categories from one call's own raw figures. Reasoning stays
    inside output (#307); cache writes are recorded raw on the call, not counted here."""
    if raw is None:
        return None, None
    if any(type(raw.get(k)) is not int for k in REQUIRED_USAGE):
        return None, "incomplete per-call usage"
    if raw["cached_input_tokens"] > raw["input_tokens"]:
        return None, "cached input exceeds input in the per-call usage"
    return {
        "uncached_input": raw["input_tokens"] - raw["cached_input_tokens"],
        "cache_read": raw["cached_input_tokens"],
        "output": raw["output_tokens"],
        "turns": turns,
    }, None


def cache_writes(call: dict) -> bool:
    """Whether a call reported a nonzero ``cache_write_input_tokens`` anywhere."""
    return any(
        isinstance(src, dict) and (src.get("cache_write_input_tokens") or 0) > 0
        for src in (call.get("reported_cumulative"), call.get("usage_raw"))
    )


def event_items(raw: str) -> list[dict]:
    """The items of a call's events, last state per item id (started then completed)."""
    items: dict[str, dict] = {}
    order: list[str] = []
    for n, event in enumerate(_events(raw)):
        item = event.get("item")
        if not isinstance(item, dict) or not str(event.get("type", "")).startswith("item."):
            continue
        key = str(item.get("id", f"#{n}"))
        if key not in items:
            order.append(key)
        items[key] = item
    return [items[k] for k in order]


def _inside(path: Path, roots: list[Path]) -> bool:
    return any(path == r or r in path.parents for r in roots)


def _roots(path: Path) -> list[Path]:
    path = Path(path)
    return list(dict.fromkeys([Path(os.path.abspath(path)), path.resolve()]))


def root_argument(command: str) -> str | None:
    """``filesystem root`` when a bare ``/`` is an argument of a filesystem command
    (``grep`` only when recursive); a ``/`` anywhere else is arithmetic, not a path."""
    for name, args in FS_COMMAND.findall(command):
        if name == "grep" and not RECURSIVE.search(args):
            continue
        if ROOT_ARG.search(args):
            return "filesystem root"
    return None


TOOL_STEP_TYPES = ("command_execution", "file_change")


def tool_steps(items: list[dict]) -> int:
    """Tool steps of one call: its completed command_execution and file_change items."""
    return sum(item.get("type") in TOOL_STEP_TYPES for item in items)


def audit_items(items: list[dict], workspace: Path) -> list[dict]:
    """Access-audit hits of one author call: a command or file change that names a path
    outside the workspace (system tool prefixes aside), climbs out of it, or names the
    hidden judge, the reference or the run output."""
    roots = _roots(workspace)
    hits = []
    for item in items:
        kind = item.get("type")
        if kind == "command_execution":
            command = str(item.get("command", ""))
            if FORBIDDEN_NAME.search(command):
                hits.append({"item": kind, "reason": "names a forbidden path", "text": command})
                continue
            text = URL.sub(" ", command).replace("file://", " ")
            reason = root_argument(text)
            if reason:
                hits.append({"item": kind, "reason": reason, "text": command})
                continue
            for token in ABS_PATH.findall(text):
                if token.startswith("~"):
                    hits.append({"item": kind, "reason": "home path", "text": command})
                    break
                if token.startswith(SYSTEM_PREFIXES) or not _names_real_path(token):
                    continue
                if not _inside(Path(os.path.normpath(token)), roots):
                    hits.append({"item": kind, "reason": f"outside workspace: {token}",
                                 "text": command})
                    break
            else:
                for token in re.findall(r"[^\s'\";|&<>()`]*\.\.[^\s'\";|&<>()`]*", text):
                    target = Path(os.path.normpath(roots[0] / token))
                    if not _inside(target, roots):
                        hits.append({"item": kind, "reason": f"climbs out: {token}",
                                     "text": command})
                        break
        elif kind == "file_change":
            for change in item.get("changes") or []:
                raw = str(change.get("path", "")) if isinstance(change, dict) else ""
                path = Path(raw) if os.path.isabs(raw) else roots[0] / raw
                if FORBIDDEN_NAME.search(raw) or not _inside(
                    Path(os.path.normpath(path)), roots
                ):
                    hits.append({"item": kind, "reason": "file change outside workspace",
                                 "text": raw})
    return hits


def changed_paths(items: list[dict], workspace: Path) -> list[str]:
    """Workspace-relative paths a call's ``file_change`` items name (attribution aid)."""
    roots = _roots(workspace)
    found = []
    for item in items:
        if item.get("type") != "file_change":
            continue
        for change in item.get("changes") or []:
            raw = str(change.get("path", "")) if isinstance(change, dict) else ""
            path = Path(os.path.normpath(Path(raw) if os.path.isabs(raw) else roots[0] / raw))
            for root in roots:
                if _inside(path, [root]) and path != root:
                    found.append(path.relative_to(root).as_posix())
                    break
    return sorted(set(found))


def file_hashes(root: Path) -> dict[str, str]:
    """sha256 of every workspace file (``__pycache__`` aside), keyed by relative path.

    A file that vanishes between listing and reading (a sibling's temp file) is skipped.
    """
    hashes = {}
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts or not path.is_file() or path.is_symlink():
            continue
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            continue
        hashes[path.relative_to(root).as_posix()] = hashlib.sha256(data).hexdigest()
    return hashes


def seed_claims(loop_ran: bool, unit_files: list[str]) -> list[str]:
    """Files a seed window owns: all of its unit's files once the mutant loop ran."""
    return list(unit_files) if loop_ran else []


def _names_real_path(token: str) -> bool:
    """True when the token's first absolute component exists on this machine.

    `/def`, `/count` and `/2` (sed/awk addresses, spaced division) name nothing on disk;
    `/tmp`, `/var` and `/Users` do (QW round 3, H2).
    """
    first = token.split("/", 2)[1] if token.startswith("/") else ""
    if not first:
        return False
    head = "/" + first
    if any(ch in first for ch in "*?["):
        return bool(glob.glob(head))
    return os.path.lexists(head)


def diff_hashes(before: dict, after: dict) -> list[str]:
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def prompt_view(clocked: dict) -> dict:
    """What an agent sees of a clock-in: no brief path, no file list, no handoff (its
    next_action names absolute paths and goes stale), upstream outcomes only."""
    unit = {k: v for k, v in clocked.get("unit", {}).items() if k != "brief_path"}
    if "attempts" in unit:
        # Attempt notes and produced refs name call dirs, arms and job ids: status and
        # outcome only (QW round 2, finding 6).
        unit["attempts"] = [
            {"status": a.get("status"), "outcome": a.get("outcome")}
            for a in unit["attempts"] or [] if isinstance(a, dict)
        ]
    return {
        "result": clocked.get("result"),
        "unit": unit,
        "role": clocked.get("role"),
        "invariants": clocked.get("invariants", []),
        "do_not": clocked.get("do_not", []),
        "upstream": [
            {"unit": u.get("unit"), "title": u.get("title"), "status": u.get("status"),
             "outcome": (u.get("last") or {}).get("outcome")}
            for u in clocked.get("upstream", []) if isinstance(u, dict)
        ],
        "prior_attempts": [
            {"status": a.get("status"), "outcome": a.get("outcome")}
            for a in clocked.get("prior_attempts", []) if isinstance(a, dict)
        ],
    }


def merge_intervals(intervals: list) -> list[list[float]]:
    merged: list[list[float]] = []
    for start, end in sorted(i for i in intervals if i[1] > i[0]):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def only_in(first: list, second: list, limit: float | None = None) -> float:
    """Length of ``first``'s union not covered by ``second``'s union, up to ``limit``."""
    total = 0.0
    cover = merge_intervals(second)
    for start, end in merge_intervals(first):
        if limit is not None:
            end = min(end, limit)
        if end <= start:
            continue
        span = end - start
        for c_start, c_end in cover:
            span -= max(0.0, min(end, c_end) - max(start, c_start))
        total += span
    return total


def parse_patch(raw: str, owned: list[str]) -> tuple[list[dict] | None, str | None]:
    """A T2 patch answer: ``{"files": [{"path", "content"}]}`` naming only owned files.

    Returns (files, None) or (None, reason). Any path the unit does not own rejects the
    whole answer, so nothing at all is written for it."""
    events = list(_events(raw))
    if any(e.get("type") in ("turn.failed", "error") for e in events):
        return None, "Codex turn failed"
    items = [e.get("item") for e in events if e.get("type") == "item.completed"]
    items = [i for i in items if isinstance(i, dict)]
    if any(i.get("type") in ("command_execution", "mcp_tool_call", "file_change",
                             "web_search") for i in items):
        return None, "patch call used a tool"
    messages = [i.get("text") for i in items if i.get("type") == "agent_message"]
    if not messages or not isinstance(messages[-1], str):
        return None, "no patch answer"
    try:
        answer = json.loads(messages[-1])
    except ValueError:
        return None, "patch answer is not JSON"
    files = answer.get("files") if isinstance(answer, dict) else None
    if not isinstance(files, list) or not files:
        return None, "patch answer has no files list"
    seen = set()
    for row in files:
        if (not isinstance(row, dict) or set(row) != {"path", "content"}
                or not isinstance(row["path"], str) or not isinstance(row["content"], str)):
            return None, "patch file row is not {path, content}"
        if row["path"] not in owned:
            return None, f"patch names a file the unit does not own: {row['path']}"
        if row["path"] in seen:
            return None, f"patch names {row['path']} twice"
        seen.add(row["path"])
    return [{"path": r["path"], "content": r["content"]} for r in files], None


def call_spend(call: dict) -> int | None:
    """Raw tokens a call spent, for the budget: its usage incl. cache reads when known;
    else its reported running total (input + output, never less than the call's own);
    None when the call reported nothing at all."""
    known = usage_tokens(call.get("usage"))
    if known is not None:
        return known
    reported = call.get("reported_cumulative")
    if isinstance(reported, dict) and all(
        type(reported.get(k)) is int for k in ("input_tokens", "output_tokens")
    ):
        return reported["input_tokens"] + reported["output_tokens"]
    return None


def stop_kind_of(record: dict) -> str | None:
    """``harness`` | ``protocol`` | None (accepted, oracle green or unknown)."""
    if "stop_kind" in record:
        return record["stop_kind"]
    if not record["accepted"] or record["quality"].get("quality_failure") is True:
        return "protocol"
    return None


# --- plans ------------------------------------------------------------------------


def _units(case: dict) -> dict[str, dict]:
    return {u["id"]: u for u in case["units"]}


def gated_units(case: dict) -> list[str]:
    """Fork/join keeps the contract gate in both arms: the root units of a case with an
    integration unit get their own reviewer before any consumer runs."""
    if not any(u["kind"] == "integration" for u in case["units"]):
        return []
    return [u["id"] for u in case["units"] if not u["depends_on"]]


def author_brief(unit: dict) -> str:
    criteria = "\n".join(f"- {c['id']}: {c['text']}" for c in unit["criteria"])
    return (
        f"{unit['task']}\n\nAcceptance criteria:\n{criteria}\n\n"
        f"Files you own: {', '.join(unit['files'])}\n"
        f"Fast check: python checks/check_{unit['id']}.py\n"
    )


def reviewer_brief(case: dict, members: list[str]) -> str:
    return (
        f"Review units {', '.join(members)} of fixture case {case['id']} against every "
        "acceptance criterion. You authored none of them. The harness supplies the exact "
        "integrated files, revisions and fast-check results with this brief when the "
        "unit is clocked in; use only those."
    )


def arm_tickets(case: dict, arm: str) -> list[dict]:
    """The shiftwork_draft tickets of one arm. Reviewers carry ``reviews`` ⊆ ``depends_on``."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm}")
    gated = gated_units(case)
    tickets = []

    def author(unit: dict, deps: list[str]) -> None:
        tickets.append(
            {
                "id": unit["id"],
                "title": f"Author {unit['id']}: {', '.join(unit['files'])}",
                "role": "implementer",
                "depends_on": deps,
                "touches": list(unit["files"]),
                "verify": f"python checks/check_{unit['id']}.py",
                "data_shape": "Python module files named in the brief",
                "brief": author_brief(unit),
            }
        )

    def reviewer(rid: str, members: list[str]) -> None:
        tickets.append(
            {
                "id": rid,
                "title": f"Review {', '.join(members)}",
                "role": "reviewer",
                "depends_on": list(members),
                "reviews": list(members),
                "verify": "harness: no findings, full criterion coverage, bound revision, "
                "fast checks green",
                "data_shape": "JSON verdict: findings and per-unit revision/criteria evidence",
                "brief": reviewer_brief(case, members),
            }
        )

    if arm == "per-task":
        for unit in case["units"]:
            author(unit, [f"QA_{d}" for d in unit["depends_on"]])
            reviewer(f"QA_{unit['id']}", [unit["id"]])
        return tickets
    for unit in case["units"]:
        author(unit, [f"QA_{d}" if d in gated else d for d in unit["depends_on"]])
        if unit["id"] in gated:
            reviewer(f"QA_{unit['id']}", [unit["id"]])
    reviewer("R", [u["id"] for u in case["units"] if u["id"] not in gated])
    return tickets


def context_mode(case: dict, unit_kind: str, base: str | None) -> str:
    """``parent`` (one resumed session) or ``delegate`` (fresh process) per the design."""
    if case["mode"] == "native-chain":
        return "parent"
    if case["mode"] == "mixed-fork-join" and unit_kind == "author":
        # The parent authors the contract (a root) and the integration; the branches are
        # concurrent fresh delegates. Repairs outside native mode are fresh delegates.
        unit = _units(case)[base]
        return "parent" if unit["kind"] == "integration" or not unit["depends_on"] else "delegate"
    return "delegate"


def upstream_closure(case: dict, ids: list[str]) -> list[str]:
    by = _units(case)
    seen: list[str] = []
    stack = list(ids)
    while stack:
        uid = stack.pop()
        if uid in seen:
            continue
        seen.append(uid)
        stack.extend(by[uid]["depends_on"])
    return [u["id"] for u in case["units"] if u["id"] in seen]


def downstream_closure(case: dict, ids: list[str]) -> list[str]:
    result: set[str] = set()
    changed = True
    while changed:
        changed = False
        for unit in case["units"]:
            if unit["id"] in result:
                continue
            if any(d in ids or d in result for d in unit["depends_on"]):
                result.add(unit["id"])
                changed = True
    return [u["id"] for u in case["units"] if u["id"] in result]


# --- review assessment ------------------------------------------------------------


def assess_review(request: dict, response: dict | None, error: str | None) -> dict:
    """Approval = no findings + full coverage + bound revision + fast checks green."""
    if response is None:
        return {"approved": False, "findings": [], "reasons": [error or "no reviewer answer"]}
    reasons: list[str] = []
    units = {u["id"]: u for u in request["units"]}
    criteria = {uid: [c["id"] for c in u["criteria"]] for uid, u in units.items()}
    if response.get("reviewer_context_id") != request["reviewer_context_id"]:
        reasons.append("reviewer context not bound")
    findings = []
    raw = response.get("findings")
    for finding in raw if isinstance(raw, list) else []:
        if (
            isinstance(finding, dict)
            and finding.get("unit") in criteria
            and finding.get("criterion") in criteria[finding["unit"]]
            and isinstance(finding.get("detail"), str)
            and finding["detail"].strip()
        ):
            findings.append(
                {"unit": finding["unit"], "criterion": finding["criterion"],
                 "detail": finding["detail"]}
            )
        else:
            reasons.append("finding outside membership or criteria")
    if not isinstance(raw, list):
        reasons.append("findings is not a list")
    evidence = response.get("evidence") if isinstance(response.get("evidence"), list) else []
    for uid, unit in units.items():
        rows = [e for e in evidence if isinstance(e, dict) and e.get("unit") == uid]
        if (
            len(rows) != 1
            or rows[0].get("revision") != unit["revision"]
            or not isinstance(rows[0].get("criteria"), list)
            or set(rows[0]["criteria"]) != set(criteria[uid])
        ):
            reasons.append(f"incomplete or stale evidence for {uid}")
        if unit["fast_check_passed"] is not True:
            reasons.append(f"fast check red for {uid}")
    return {
        "approved": not findings and not reasons,
        "findings": findings,
        "reasons": sorted(set(reasons)),
    }


def convergence_findings(prior: dict | None, revisions: dict, findings: list) -> list:
    """RR's convergence figure: the findings of one review that name a member whose
    revision is unchanged since the same reviewer unit's previous answered review (its
    ``revisions``). None when there was no previous review: nothing to converge from."""
    if prior is None:
        return []
    return [f for f in findings if prior["revisions"].get(f["unit"]) == revisions.get(f["unit"])]


# --- the host ---------------------------------------------------------------------


class Host:
    """One MCP session, the output directory and the Codex command for a whole run."""

    def __init__(self, out: Path, codex_bin: list[str], author_timeout: float,
                 review_timeout: float):
        self.out = out
        self.codex_bin = list(codex_bin)
        self.author_timeout = author_timeout
        self.review_timeout = review_timeout
        self.client = None
        self.lock = asyncio.Lock()
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.response_schema = out / "response-schema.json"
        self.codex_env_sha: str | None = None
        # No prompt may name the repository or the run output (QW finding 4).
        self.secret_paths = sorted(
            {str(p) for root in (ROOT, out) for p in _roots(root)}, key=len, reverse=True
        )

    def leaks(self, text: str) -> list[str]:
        return [p for p in self.secret_paths if p in text]

    async def tool(self, name: str, args: dict) -> dict:
        async with self.lock:
            result = await self.client.call_tool(name, args)
        value = result.structured_content
        if value is None:
            value = json.loads(next(c.text for c in result.content if c.type == "text"))
        if value.get("result") in ("error", "escalate"):
            raise ShiftworkRefusal(name, value)
        return value

    def argv(self, kind: str, workspace: Path, mode: str, resume: str | None,
             schema: bool = True, effort: str = "medium", persist: bool = False) -> list[str]:
        """``schema=False`` is T1 (reviewer without --output-schema); ``effort`` is T4 on
        repair calls; ``kind="patch"`` is T2's tools-disabled fresh call. ``persist`` is
        RR: a reviewer session that is not --ephemeral, so it can be resumed; a reviewer
        ``resume`` is that thread, resumed with tools disabled and a read-only sandbox.
        The defaults are the #310 argv exactly."""
        common = [
            "--json", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
            "--model", MODEL, "-c", f'model_reasoning_effort="{effort}"',
            "-c", 'web_search="disabled"',
        ]
        no_tools = ["--disable", "shell_tool", "--disable", "unified_exec", "--disable", "apps",
                    "--disable", "multi_agent"]
        if kind == "review" and resume is not None:
            # `exec resume` has no --sandbox: the sandbox is a config override and the
            # working root is the process cwd (the reviewer cwd), as for author resumes.
            return [*self.codex_bin, "exec", "resume", *common, *no_tools,
                    "-c", 'sandbox_mode="read-only"', resume, "-"]
        if kind == "review":
            return [
                *self.codex_bin, "exec", *common, *([] if persist else ["--ephemeral"]),
                "--sandbox", "read-only", *no_tools,
                *(["--output-schema", str(self.response_schema)] if schema else []), "-",
            ]
        if kind == "patch":
            # Fresh, never a resume: the patch call sees only its prompt.
            return [*self.codex_bin, "exec", *common, "--ephemeral", "--sandbox", "read-only",
                    *no_tools, "-"]
        author = ["--disable", "apps", "--disable", "multi_agent"]
        if resume is not None:
            # `exec resume` has no --sandbox/--cd: the sandbox is a config override and
            # the working root is the process cwd (run_contained's cwd).
            return [
                *self.codex_bin, "exec", "resume", *common, *author,
                "-c", 'sandbox_mode="workspace-write"', resume, "-",
            ]
        return [
            *self.codex_bin, "exec", *common, *author, "--sandbox", "workspace-write",
            "-C", str(workspace), *(["--ephemeral"] if mode == "delegate" else []), "-",
        ]

    def call(self, call_id: str, argv: list[str], prompt: str, cwd: Path, timeout: float,
             extra: dict) -> dict:
        directory = self.out / "calls" / call_id
        directory.mkdir(parents=True)
        (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
        (directory / "argv.json").write_text(json.dumps(argv, indent=2) + "\n", encoding="utf-8")
        started, started_at = time.monotonic(), now()
        stdout, stderr, error, returncode = "", "", None, None
        leaked = self.leaks(prompt)
        if leaked:
            # Never sent: a prompt naming the repo or the output dir would hand the agent
            # the oracle's location. A harness censor, not a model outcome.
            error = "prompt names an absolute repository or output path; not sent"
        else:
            try:
                done = run_eval.run_contained(argv, prompt, str(cwd), timeout)
                stdout, stderr, returncode = done.stdout, done.stderr, done.returncode
                if returncode:
                    error = f"codex exited {returncode}"
            except subprocess.TimeoutExpired as exc:
                stdout = run_eval._decode(exc.stdout)
                stderr = run_eval._decode(exc.stderr)
                error = f"timeout after {timeout}s"
            except OSError as exc:
                error = f"process error: {exc}"
        elapsed_ms = int((time.monotonic() - started) * 1000)
        threads = thread_ids(stdout)
        items = event_items(stdout)
        call = {
            "id": call_id,
            **extra,
            "started_at": started_at,
            "stopped_at": now(),
            "elapsed_ms": elapsed_ms,
            "returncode": returncode,
            "error": error,
            "usage": parse_usage(stdout),
            # Raw rows; Arm.model splits a resumed call's running total by thread.
            "turn_usages": turn_usages(stdout),
            "item_types": sorted({str(i.get("type")) for i in items}),
            "thread_id": threads[0] if threads else None,
            "artifact_dir": str(directory.relative_to(self.out)),
        }
        (directory / "events.jsonl").write_text(stdout, encoding="utf-8")
        (directory / "stderr.txt").write_text(stderr, encoding="utf-8")
        (directory / "call.json").write_text(json.dumps(call, indent=2) + "\n", encoding="utf-8")
        call["stdout"] = stdout
        call["items"] = items
        return call


class Arm:
    """One matched live job: a case, a repeat and an arm, with its own checkpoint.

    The arm's workspace is an opaque temporary directory outside the repository and the
    run output; it is copied into the output only after the arm stops.
    """

    def __init__(self, host: Host, case: dict, arm: str, repeat: int, order: int, smoke: bool,
                 attempt: int = 0):
        # ``arm`` is a variant name: a #310 arm (per-task, grouped) or a tuning variant
        # (baseline-grouped, tuned-grouped). The plan shape is the variant's arm.
        if arm not in VARIANTS:
            raise ValueError(f"unknown arm {arm}")
        self.variant = arm
        self.levers = set(VARIANTS[arm]["levers"])
        self.host, self.case, self.arm = host, case, VARIANTS[arm]["arm"]
        self.repeat, self.order, self.smoke, self.attempt = repeat, order, smoke, attempt
        self.counts = {"delta_skipped_after_error": 0,
                       "patch_calls": 0, "patch_invalid_answers": 0, "patch_red_checks": 0,
                       "fallbacks": 0}
        # The RR comparison's extra counts (both of its arms, so they compare); a #310 or
        # tuning record has none of these keys.
        self.batch_comparison = arm in BATCH_VARIANTS
        self.rr_comparison = arm in RR_VARIANTS or self.batch_comparison
        if self.rr_comparison:
            self.counts.update(resume_fallbacks=0, fresh_after_error=0, resume_capped=0)
        # RR: per reviewer unit, the thread its last review left behind and what that
        # thread has seen (revisions and context-file text), so a re-review can be a delta.
        self.rr_state: dict[str, dict] = {}
        self.job_id = (f"{case['id']}-r{repeat}-{self.variant}"
                       + (f"-a{attempt}" if attempt else "")
                       + ("-smoke" if smoke else ""))
        self.dir = host.out / "arms" / self.job_id
        self.scratch: list[Path] = []
        self.workspace: Path | None = None
        self.review_cwd: Path | None = None
        self.checkpoint = self.dir / "shiftwork" / "checkpoint.json"
        self.briefs = self.dir / "shiftwork" / "briefs"
        self.case_units = _units(case)
        self.units: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.reviews: list[dict] = []
        self.seeds: list[dict] = []
        self.trace: list[dict] = []
        self.rounds: dict[str, int] = {}
        self.round_kinds: list[dict] = []
        self.repairs_of: dict[str, list[str]] = {}
        self.plan_edits: list[str] = []
        self.parent_thread: str | None = None
        # Last reported running total per thread (None: unknown, so the next resumed
        # call on that thread cannot be split).
        self.thread_totals: dict[str, dict | None] = {}
        self.parent_busy = False
        self.fast_checks: dict[str, list[dict]] = {}
        self.escalations = 0
        self.audit_hits: list[dict] = []
        # Write attribution (QW round 2, finding 3): the workspace is hashed at every
        # author-call and seed boundary; each span between two boundaries knows which
        # writers were active in it.
        self.write_lock = threading.Lock()
        self.ws_hashes: dict[str, str] = {}
        self.ws_t = 0.0
        self.active_writers: set[str] = set()
        self.writers: dict[str, dict] = {}
        self.write_spans: list[dict] = []
        self.harness_windows: list[dict] = []
        self.harness_ms = {"seeding": 0, "adjudication": 0}
        self.usage_unknown: list[dict] = []
        self.errors: list[dict] = []
        self.t0 = 0.0

    def clock(self) -> float:
        return (time.monotonic() - self.t0) * 1000

    # trace -------------------------------------------------------------------
    def mark(self, event: str, unit: str | None = None, **extra) -> dict:
        row = {
            "event": event,
            "unit": unit,
            "t_ms": int(self.clock()),
            "ts": now(),
            **extra,
        }
        self.trace.append(row)
        return row

    def read_checkpoint(self) -> dict:
        return json.loads(self.checkpoint.read_text(encoding="utf-8"))

    # setup -------------------------------------------------------------------
    def make_dirs(self) -> None:
        """Opaque temp dirs outside the repo and the output dir (QW finding 4)."""
        for name in ("workspace", "review_cwd"):
            path = Path(tempfile.mkdtemp(prefix="glr-"))
            self.scratch.append(path)
            for forbidden in (ROOT, self.host.out):
                if any(_inside(p, _roots(forbidden)) for p in _roots(path)):
                    raise ArmStopped(f"temp dir {path} is inside {forbidden}")
            setattr(self, name, path / "w" if name == "workspace" else path)
        live_cases.make_workspace(self.case, self.workspace)
        self.ws_hashes, self.ws_t = file_hashes(self.workspace), self.clock()

    def boundary(self, actor: str | None, starting: bool, info: dict | None = None) -> dict:
        """Hash the workspace, close the span since the last boundary (with the writers
        active in it), then start or end ``actor``. Returns the hashes taken."""
        with self.write_lock:
            t = self.clock()
            hashes = file_hashes(self.workspace)
            changed = diff_hashes(self.ws_hashes, hashes)
            if changed:
                self.write_spans.append({"window_ms": [self.ws_t, t],
                                         "active": sorted(self.active_writers),
                                         "changed": changed})
            self.ws_hashes, self.ws_t = hashes, t
            if actor is not None and starting:
                self.writers[actor] = {**(info or {}), "window_ms": [t, None]}
                self.active_writers.add(actor)
            elif actor is not None:
                self.writers[actor]["window_ms"][1] = t
                self.active_writers.discard(actor)
            return hashes

    async def draft(self) -> None:
        tickets = arm_tickets(self.case, self.arm)
        for ticket in tickets:
            kind = "reviewer" if ticket["role"] == "reviewer" else "author"
            self.units[ticket["id"]] = {
                "id": ticket["id"],
                "kind": kind,
                "base": ticket["id"] if kind == "author" else None,
                "files": list(ticket.get("touches", [])),
                "members": list(ticket.get("reviews", [])),
                "round": 0,
            }
        await self.host.tool(
            "shiftwork_draft",
            {
                "checkpoint": str(self.checkpoint),
                "briefs_dir": str(self.briefs),
                "write": True,
                "job": {
                    "id": self.job_id,
                    "goal": f"Implement fixture case {self.case['id']} with independent review "
                    f"({self.arm} arm).",
                    "done_definition": "Every reviewer approves the exact integrated revision.",
                    "constraints": [
                        "Authors work only inside the arm workspace and edit only the files "
                        "they own.",
                        "Reviewers use only the supplied request; no tools or files.",
                    ],
                    # HARNESS_MODEL: an integration recheck whose fast checks are green
                    # makes no model call and says so.
                    "roles": {"implementer": [MODEL, HARNESS_MODEL], "reviewer": [MODEL]},
                },
                "repo": {"branch": "live-eval-fixture", "head_sha": "not-a-git-revision",
                         "dirty": False},
                "tickets": tickets,
            },
        )
        self.mark("draft", None, units=[t["id"] for t in tickets])

    # dispatch ------------------------------------------------------------------
    def mode_of(self, uid: str) -> str:
        unit = self.units[uid]
        if unit["kind"] == "reviewer":
            return "review"
        if unit["kind"] == "author":
            return context_mode(self.case, "author", unit["base"])
        return context_mode(self.case, unit["kind"], unit["base"])

    def fail(self, where: str, exc: BaseException) -> str:
        self.errors.append({"where": where, "type": type(exc).__name__, "error": str(exc),
                            "traceback": traceback.format_exc()[-4000:]})
        return f"{where}: {type(exc).__name__}: {exc}"

    async def run(self) -> dict:
        self.t0 = time.monotonic()
        started_at = now()
        stop_reason, stop_kind, accepted_at_ms, accepted_at = None, None, None, None
        in_flight: dict[asyncio.Task, str] = {}
        pending: list[dict] = []
        try:
            self.make_dirs()
            await self.draft()
        except Exception as exc:  # noqa: BLE001 - any setup failure censors the arm
            stop_reason, stop_kind = self.fail("setup", exc), "harness"
        while True:
            try:
                if stop_reason is None and pending and not in_flight:
                    for edit in pending:
                        await self.replan(edit)
                    pending.clear()
                if stop_reason is None and not pending:
                    plan = await self.host.tool(
                        "shiftwork_plan", {"checkpoint": str(self.checkpoint)}
                    )
                    status = {u["id"]: u["status"]
                              for u in self.read_checkpoint()["plan"]["units"]}
                    busy = set(in_flight.values())
                    for uid in plan["ready"]:
                        # A blocked reviewer is graph-ready; only a planner edit resumes it.
                        if status.get(uid) != "todo" or uid in busy:
                            continue
                        if self.mode_of(uid) == "parent":
                            if self.parent_busy:
                                continue
                            self.parent_busy = True
                        in_flight[asyncio.create_task(self.run_unit(uid))] = uid
                        busy.add(uid)
            except Exception as exc:  # noqa: BLE001 - planner/MCP failure is a harness censor
                stop_reason = stop_reason or self.fail("planner", exc)
                stop_kind = stop_kind or "harness"
                pending.clear()
            if not in_flight:
                break
            finished, _ = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
            for task in finished:
                uid = in_flight.pop(task)
                if self.mode_of(uid) == "parent":
                    self.parent_busy = False
                outcome = task.result()
                if outcome.get("escalate"):
                    self.escalations += 1
                if outcome.get("error"):
                    stop_reason = stop_reason or f"{uid}: {outcome['error']}"
                    stop_kind = stop_kind or "harness"
                    continue
                if outcome.get("approved"):
                    accepted_at_ms = self.clock()
                    accepted_at = now()
                if outcome.get("rejected") and stop_reason is None:
                    self.rounds[uid] = self.rounds.get(uid, 0) + 1
                    self.round_kinds.append({"reviewer": uid, "round": self.rounds[uid],
                                             "kind": outcome["round_kind"]})
                    if self.rounds[uid] > MAX_REPAIR_ROUNDS:
                        stop_reason = (
                            f"{uid} rejected after {MAX_REPAIR_ROUNDS} repair rounds: "
                            "failed/censored"
                        )
                        stop_kind = "protocol"
                    else:
                        pending.append(
                            {"reviewer": uid, "round": self.rounds[uid],
                             "findings": outcome["findings"]}
                        )
        stop_ms = self.clock()
        try:
            statuses = {u["id"]: u["status"] for u in self.read_checkpoint()["plan"]["units"]}
        except (OSError, ValueError, KeyError):
            statuses = {}
        accepted = stop_reason is None and bool(statuses) and all(
            s == "done" for s in statuses.values()
        )
        if stop_reason is None and not accepted:
            stop_reason, stop_kind = "plan ended with units not done", "harness"
        try:
            return self.record(started_at, accepted, stop_reason, stop_kind, stop_ms,
                               accepted_at_ms, accepted_at)
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        for path in self.scratch:
            shutil.rmtree(path, ignore_errors=True)

    # one unit --------------------------------------------------------------------
    async def run_unit(self, uid: str) -> dict:
        """Never raises: any failure inside a unit is a harness censor of this arm."""
        try:
            return await self._run_unit(uid)
        except ShiftworkRefusal as exc:
            return {"error": str(exc), "escalate": exc.escalate}
        except Exception as exc:  # noqa: BLE001
            return {"error": self.fail(f"unit {uid}", exc)}

    async def _run_unit(self, uid: str) -> dict:
        unit = self.units[uid]
        clocked = await self.host.tool(
            "shiftwork_clock_in", {"checkpoint": str(self.checkpoint), "unit_id": uid}
        )
        self.mark("clock_in", uid)
        brief = Path(clocked["unit"]["brief_path"]).read_text(encoding="utf-8")
        call_id = f"{self.job_id}-{len(self.calls):03d}-{uid}"
        view = json.dumps(prompt_view(clocked), ensure_ascii=False)
        if unit["kind"] == "reviewer":
            return await self.review(uid, view, brief, call_id)
        return await self.author(uid, view, brief, call_id)

    def owned(self, uid: str) -> list[str]:
        unit = self.units[uid]
        if unit["kind"] == "integration":
            return sorted({f for c in unit["consumers"] for f in self.case_units[c]["files"]})
        return list(self.case_units[unit["base"]]["files"])

    def _author_call(self, call_id, uid, argv, prompt, timeout, extra) -> tuple[dict, list, list]:
        before = self.boundary(call_id, True, {"kind": "call", "call": call_id, "unit": uid,
                                               "owned": self.owned(uid), "event_paths": []})
        try:
            call = self.host.call(call_id, argv, prompt, self.workspace, timeout, extra)
        finally:
            after = self.boundary(call_id, False)
        return call, before, diff_hashes(before, after)

    def patch_target(self, rel: str) -> Path | None:
        """T2: where the harness may read or write an owned file, or None. The harness runs
        unsandboxed, so a symlink anywhere on the path (left by a shell-mode author) or a
        path resolving outside the workspace would let a patch read or overwrite a file
        outside it; such a path is refused."""
        root = self.workspace.resolve()
        node = self.workspace
        for part in Path(rel).parts:
            node = node / part
            if node.is_symlink():
                return None
        target = self.workspace / rel
        try:
            target.resolve().relative_to(root)
        except ValueError:
            return None
        return target

    def _patch_call(self, call_id, uid, argv, prompt, timeout, extra) -> tuple[dict, list, list]:
        """T2: the tools-disabled call runs in the empty review cwd; the harness writes
        its owned files inside the same write boundary, so the write is this repair
        unit's, hashed as any author call's."""
        owned = self.owned(uid)
        before = self.boundary(call_id, True, {"kind": "call", "call": call_id, "unit": uid,
                                               "owned": owned, "event_paths": []})
        applied = {"valid": False, "reason": None, "written": []}
        try:
            call = self.host.call(call_id, argv, prompt, self.review_cwd, timeout, extra)
            if not call["error"]:
                files, reason = parse_patch(call["stdout"], owned)
                unsafe = sorted(r["path"] for r in files or [] if self.patch_target(r["path"]) is None)
                if files is None:
                    applied["reason"] = reason
                elif unsafe:
                    applied["reason"] = f"unsafe path (symlink or outside workspace): {unsafe[0]}"
                else:
                    for row in files:
                        target = self.patch_target(row["path"])
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(row["content"], encoding="utf-8")
                    applied.update(valid=True, written=sorted(r["path"] for r in files))
        finally:
            after = self.boundary(call_id, False)
        call["patch"] = applied
        return call, before, diff_hashes(before, after)

    def effort_of(self, uid: str, kind: str) -> str:
        """T4: low reasoning effort on repair calls only (patch and fallback)."""
        if "T4" in self.levers and kind != "review" and self.units[uid]["kind"] == "repair":
            return "low"
        return "medium"

    async def model(self, uid: str, call_id: str, prompt: str, kind: str,
                    tag: dict | None = None, review_thread: str | None = None) -> dict:
        mode = "patch" if kind == "patch" else self.mode_of(uid)
        resume = self.parent_thread if mode == "parent" and self.parent_thread else None
        if kind == "review":
            resume = review_thread  # RR: the reviewer's own thread, never an author's
        argv = self.host.argv(kind, self.workspace, mode, resume,
                              schema="T1" not in self.levers, effort=self.effort_of(uid, kind),
                              persist=kind == "review" and "RR" in self.levers)
        timeout = self.host.review_timeout if kind == "review" else self.host.author_timeout
        extra = {"unit": uid, "kind": self.units[uid]["kind"], "context": mode,
                 "resumed": resume is not None, **(tag or {})}
        self.mark("model_start", uid, call=call_id, context=mode, resumed=resume is not None)
        start = self.clock()
        if kind == "review":
            call = await asyncio.to_thread(
                self.host.call, call_id, argv, prompt, self.review_cwd, timeout, extra
            )
            changed = []
        elif kind == "patch":
            call, _, changed = await asyncio.to_thread(
                self._patch_call, call_id, uid, argv, prompt, timeout, extra
            )
        else:
            call, _, changed = await asyncio.to_thread(
                self._author_call, call_id, uid, argv, prompt, timeout, extra
            )
        end = self.clock()
        self.mark("model_end", uid, call=call_id)
        call["window_ms"] = [start, end]
        if kind != "review":
            hits = audit_items(call["items"], self.workspace)
            call["audit_hits"] = hits
            self.audit_hits += [{"call": call_id, "unit": uid, **h} for h in hits]
            named = (call["patch"]["written"] if kind == "patch"
                     else changed_paths(call["items"], self.workspace))
            self.writers[call_id].update(changed=changed, event_paths=named)
        self.account(call, uid, resume)
        # The cost metric (maintainer ruling 2026-11-13): uncached input + output; the raw
        # total with cache reads beside it.
        call["tokens_excl_cache"] = usage_tokens(call["usage"], include_cache=False)
        call["tokens"] = usage_tokens(call["usage"])
        if self.batch_comparison and kind != "review":
            call["tool_steps"] = tool_steps(call["items"])
        if mode == "parent" and self.parent_thread is None and call["thread_id"]:
            self.parent_thread = call["thread_id"]
        if mode == "parent" and call["thread_id"] is None:
            call["thread_id"] = self.parent_thread
        if kind == "review" and review_thread is not None and call["thread_id"] is None:
            call["thread_id"] = review_thread
        self.calls.append({k: v for k, v in call.items() if k not in ("stdout", "items")})
        self.units[uid].setdefault("calls", []).append(call_id)
        if call["thread_id"]:
            self.units[uid].setdefault("threads", []).append(call["thread_id"])
        return call

    def account(self, call: dict, uid: str, resume: str | None) -> None:
        """Per-call usage. A fresh call's is its own report (unchanged). A resumed call
        reports its session's running total, so its usage is that total minus the
        previous call's on the same thread; unknown (None, reason recorded) when there is
        no earlier total or a field falls. Raw totals stay beside the per-call figures."""
        rows = call["turn_usages"]
        reported, why = reported_total(rows)
        call["reported_cumulative"] = reported
        if resume is None:
            call["usage_raw"] = summed_rows(rows) if call["usage"] is not None else None
            if call["usage"] is None:
                why = why or "no complete turn.completed usage"
        else:
            raw = None
            if reported is not None:
                raw, why = call_delta(reported, self.thread_totals.get(resume))
            call["usage_raw"] = raw
            usage, bad = usage_of_raw(raw, len(rows))
            call["usage"] = usage
            why = why or bad
        if call["usage"] is None:
            call["usage_unknown_reason"] = why
            self.usage_unknown.append({"call": call["id"], "unit": uid, "reason": why})
        thread = resume if resume is not None else call["thread_id"]
        if thread:
            # A total that could not be trusted is no baseline for the next resumed call.
            self.thread_totals[thread] = reported if call["usage"] is not None else None

    async def clock_out(self, uid: str, status: str, call: dict | None, outcome: str,
                        notes: str, produced: list[dict], accounting: dict | None = None) -> None:
        agent = call.get("thread_id") if call else None
        await self.host.tool(
            "shiftwork_clock_out",
            {
                "checkpoint": str(self.checkpoint),
                "unit_id": uid,
                "status": status,
                "history_entry": {"unit": uid, "outcome": outcome, "notes": notes[:2000],
                                  **({"produced": produced} if produced else {})},
                # Never leave a stale next_action (it named a brief path) behind.
                "handoff_patch": {"next_action": f"{uid} clocked out {status}; dispatch the "
                                  "units shiftwork_plan reports ready."},
                "accounting": accounting or clock_accounting(
                    call["usage"], call["elapsed_ms"],
                    f"codex exec {call['context']} call {call['id']}"
                    + (f"; {call['usage_unknown_reason']}"
                       if call.get("usage_unknown_reason") else ""),
                ),
                **({"agent_id": agent} if agent and AGENT_ID.match(agent) else {}),
            },
        )
        self.mark("clock_out", uid, status=status, call=call["id"] if call else None)

    def scrub(self, text: str, root: Path | None = None) -> str:
        """The checked root (workspace or a review snapshot) becomes ``.``; any other
        repository or output path becomes ``<harness>``. Longest path first, so a
        snapshot under the output dir never leaves its arm, job id or ``snapshots/``."""
        local = {str(p) for r in {self.workspace, root} if r is not None for p in _roots(r)}
        swaps = [(p, ".") for p in local] + [
            (p, "<harness>") for p in self.host.secret_paths if p not in local
        ]
        for path, label in sorted(swaps, key=lambda s: len(s[0]), reverse=True):
            text = text.replace(path, label)
        return text

    def fast_check(self, base: str, root: Path, label: str) -> dict:
        result = live_cases.run_fast_check(self.case, base, root)
        row = {"unit": base, "label": label, "passed": result["passed"],
               "output": self.scrub(result["output"], root)[-1500:], "ts": now()}
        self.fast_checks.setdefault(base, []).append(row)
        return row

    def seed(self, base: str, uid: str, check_passed: bool) -> dict:
        actor = f"seed-{base}-{len(self.harness_windows)}"
        start = self.clock()
        self.boundary(actor, True, {"kind": "seed", "unit": base, "claims": []})
        try:
            if check_passed:
                seed = live_cases.seed_defect(self.case, base, self.workspace)
            else:
                seed = {"applied": False, "unit": base, "failing": [], "baseline_failing": [],
                        "criterion": None, "reason": "fast check red; no seed"}
        finally:
            self.boundary(actor, False)
            end = self.clock()
            self.harness_ms["seeding"] += end - start
            self.harness_windows.append({"what": f"seed {base}", "actor": actor,
                                         "window_ms": [start, end], "changed": []})
        # Once its mutant loop ran, the seed claims every file of its unit: seed_defect
        # writes trial mutants only there, and a concurrent boundary may catch one even
        # when no mutant was kept (QW round 3, H1). Other changes belong to author calls.
        claims = seed_claims(check_passed, self.case_units[base]["files"])
        self.writers[actor]["claims"] = claims
        self.harness_windows[-1]["changed"] = claims
        seed.update(key=[seed["unit"], seed["criterion"]] if seed["applied"] else None,
                    status="applied" if seed["applied"] else "unavailable",
                    seen_by=None, caught=None, presence=None)
        self.seeds.append(seed)
        self.mark("seed", uid, applied=seed["applied"])
        return seed

    async def author(self, uid: str, view: str, brief: str, call_id: str) -> dict:
        unit = self.units[uid]
        checked = [unit["base"]] if unit["kind"] != "integration" else unit["consumers"]
        if unit["kind"] == "integration":
            # Deterministic first: the dependents' fast checks. All green means no model
            # call at all (exact zero tokens); a model call only for a red check.
            start = time.monotonic()
            first = [await asyncio.to_thread(self.fast_check, base, self.workspace, uid)
                     for base in checked]
            if all(c["passed"] for c in first):
                unit["i2_path"] = "deterministic"
                return await self.finish_author(
                    uid, None, first, checked,
                    accounting={
                        "tokens": 0,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "model": HARNESS_MODEL,
                        "note": "integration recheck: dependents' fast checks green, no model "
                        "call; exact zero tokens",
                    },
                )
            unit["i2_path"] = "model"
            red = [c["unit"] for c in first if not c["passed"]]
            brief += "\nFast checks red before this call: " + ", ".join(red) + "\n"
        if unit["kind"] == "repair" and "T2" in self.levers:
            return await self.patch_repair(uid, view, brief, call_id)
        preamble = {"author": AUTHOR_PROMPT, "repair": REPAIR_PROMPT,
                    "integration": INTEGRATION_PROMPT}[unit["kind"]]
        if unit["kind"] == "author" and "AB" in self.levers:
            preamble += AB_PARAGRAPH
        prompt = preamble + view + "\n\n" + brief
        call = await self.model(uid, call_id, prompt, "author")
        if call["error"] or call["audit_hits"]:
            error = call["error"] or (
                f"access audit: {call['audit_hits'][0]['reason']}"
            )
            await self.clock_out(uid, "blocked", call, f"author call failed: {error}"[:200],
                                 "", [])
            return {"error": error}
        checks = [
            await asyncio.to_thread(self.fast_check, base, self.workspace, uid) for base in checked
        ]
        base_unit = self.case_units.get(unit["base"] or "")
        if unit["kind"] == "author" and base_unit and base_unit["seed"]:
            await asyncio.to_thread(self.seed, unit["base"], uid, checks[0]["passed"])
        return await self.finish_author(uid, call, checks, checked)

    async def patch_repair(self, uid: str, view: str, brief: str, call_id: str) -> dict:
        """T2: one fresh tools-disabled call answers whole owned files; the harness writes
        them and runs the fast check. An invalid answer or a red check is followed by
        exactly ONE fallback repair in shell mode (the #310 path), counted and labelled.
        Each call is clocked in and out on its own, as every other model call."""
        unit = self.units[uid]
        base = unit["base"]
        texts = {}
        for rel in self.owned(uid):
            path = self.patch_target(rel)
            texts[rel] = (path.read_text(encoding="utf-8", errors="replace")
                          if path is not None and path.is_file() else None)
        prompt = (PATCH_PROMPT + view + "\n\n" + brief
                  + "\n\nOWNED FILES (current text):\n" + json.dumps(texts, ensure_ascii=False))
        self.counts["patch_calls"] += 1
        call = await self.model(uid, call_id, prompt, "patch", tag={"repair_mode": "patch"})
        if call["error"] or call["audit_hits"]:
            error = call["error"] or f"access audit: {call['audit_hits'][0]['reason']}"
            await self.clock_out(uid, "blocked", call, f"patch call failed: {error}"[:200],
                                 "", [])
            return {"error": error}
        patch = call["patch"]
        if patch["valid"]:
            checks = [await asyncio.to_thread(self.fast_check, base, self.workspace, uid)]
            if checks[0]["passed"]:
                unit["repair_path"] = "patch"
                return await self.finish_author(uid, call, checks, [base])
            self.counts["patch_red_checks"] += 1
            reason = "fast check red after the patch"
        else:
            self.counts["patch_invalid_answers"] += 1
            reason = f"invalid patch answer: {patch['reason']}"
        unit["repair_path"], unit["fallback_reason"] = "fallback-shell", reason
        # By id: a concurrent unit may have appended its own call since.
        next(c for c in self.calls if c["id"] == call["id"])["fallback_reason"] = reason
        # The patch call is handed back with its own accounting; the unit stays open.
        await self.clock_out(uid, "in_progress", call, f"patch repair: {reason}"[:200],
                             f"written: {', '.join(patch['written']) or 'nothing'}", [])
        self.counts["fallbacks"] += 1
        clocked = await self.host.tool(
            "shiftwork_clock_in", {"checkpoint": str(self.checkpoint), "unit_id": uid}
        )
        self.mark("clock_in", uid)
        brief = Path(clocked["unit"]["brief_path"]).read_text(encoding="utf-8")
        view = json.dumps(prompt_view(clocked), ensure_ascii=False)
        fallback_id = f"{self.job_id}-{len(self.calls):03d}-{uid}"
        call = await self.model(uid, fallback_id, REPAIR_PROMPT + view + "\n\n" + brief,
                                "author", tag={"repair_mode": "fallback-shell",
                                               "fallback_reason": reason})
        if call["error"] or call["audit_hits"]:
            error = call["error"] or f"access audit: {call['audit_hits'][0]['reason']}"
            await self.clock_out(uid, "blocked", call, f"fallback repair failed: {error}"[:200],
                                 "", [])
            return {"error": error}
        checks = [await asyncio.to_thread(self.fast_check, base, self.workspace, uid)]
        return await self.finish_author(uid, call, checks, [base])

    async def finish_author(self, uid, call, checks, checked, accounting=None) -> dict:
        unit = self.units[uid]
        files = sorted({f for base in checked for f in self.case_units[base]["files"]})
        rev = live_cases.revision(self.workspace, files)
        unit["revision"] = rev
        notes = "; ".join(
            f"fast check {c['unit']}: {'passed' if c['passed'] else 'FAILED'}" for c in checks
        ) + f"; revision {rev}"
        await self.clock_out(
            uid, "done", call, "author work finished", notes,
            [{"kind": "revision", "ref": rev}] + [{"kind": "file", "ref": f} for f in files],
            accounting=accounting,
        )
        return {"done": True}

    def review_request(self, uid: str, snapshot: Path) -> tuple[dict, dict]:
        """The reviewer's request, and this review's own fast-check rows by unit."""
        members = [m for m in self.units[uid]["members"] if self.units[m]["kind"] == "author"]
        context = upstream_closure(self.case, members)
        # T3: a re-review carries the previous review's findings and, per member, whether
        # its revision changed since then. Acceptance (assess_review) is unchanged.
        previous = next((r for r in reversed(self.reviews) if r["unit"] == uid), None)
        # A previous round whose answer was invalid left no evidence to reuse, so the
        # next review is a full one (counted as delta_skipped_after_error).
        if "T3" in self.levers and previous is not None and not previous["valid_answer"]:
            self.counts["delta_skipped_after_error"] += 1
            previous = None
        delta = "T3" in self.levers and previous is not None
        units = []
        checks = {}
        for mid in members:
            base = self.case_units[mid]
            check = checks[mid] = self.fast_check(mid, snapshot, f"review {uid}")
            units.append(
                {
                    "id": mid,
                    "task": base["task"],
                    "criteria": base["criteria"],
                    "files": base["files"],
                    "revision": live_cases.revision(snapshot, base["files"]),
                    "fast_check_passed": check["passed"],
                }
            )
            if delta:
                units[-1]["changed_since_last_review"] = (
                    units[-1]["revision"] != previous["revisions"].get(mid)
                )
        files = {}
        for cid in context:
            for rel in self.case_units[cid]["files"]:
                path = snapshot / rel
                # Author output may be any bytes; a bad byte must not abort the arm.
                files[rel] = (path.read_text(encoding="utf-8", errors="replace")
                              if path.is_file() else None)
        request = {
            "reviewer_context_id": "reviewer-" + uuid.uuid4().hex,
            "case_id": self.case["id"],
            "membership": members,
            "shiftwork_reviews": self.units[uid]["members"],
            "units": units,
            "context_files": files,
            "instructions": REVIEW_INSTRUCTIONS,
        }
        if delta:
            request["previous_findings"] = previous["repair_findings"]
            request["instructions"] = REVIEW_INSTRUCTIONS + " " + DELTA_INSTRUCTIONS
        return request, checks

    def rr_thread(self, uid: str, index: int) -> str | None:
        """RR: the thread this review resumes, or None for a fresh full review. A fresh
        review is counted by why: a reviewer-error round before it (the next review starts
        a new thread), a first review that left no thread to resume, or the resume cap."""
        if "RR" not in self.levers or index == 0:
            return None
        state = self.rr_state.get(uid)
        if state is None:
            self.counts["fresh_after_error"] += 1
        elif state["thread"] is None:
            self.counts["resume_fallbacks"] += 1
        elif state["resumes"] >= MAX_RESUMES:
            self.counts["resume_capped"] += 1
        else:
            return state["thread"]
        return None

    @staticmethod
    def rr_delta(request: dict, state: dict) -> dict:
        """The re-review turn: the new context id, every member's revision and fast check
        with its change flag, and the text of each context file that changed since the
        thread last saw it (a changed member's files and any changed upstream file)."""
        return {
            "reviewer_context_id": request["reviewer_context_id"],
            "membership": request["membership"],
            "units": [
                {"id": u["id"], "revision": u["revision"],
                 "fast_check_passed": u["fast_check_passed"],
                 "changed_since_last_review": u["revision"] != state["revisions"].get(u["id"])}
                for u in request["units"]
            ],
            "changed_files": {rel: text for rel, text in request["context_files"].items()
                              if state["files"].get(rel, object()) != text},
        }

    async def review(self, uid: str, view: str, brief: str, call_id: str) -> dict:
        index = sum(1 for r in self.reviews if r["unit"] == uid)
        snapshot = self.dir / "snapshots" / f"{uid}-{index}"
        await asyncio.to_thread(
            shutil.copytree, self.workspace, snapshot,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        request, checks = await asyncio.to_thread(self.review_request, uid, snapshot)

        def full_prompt(view: str, brief: str) -> str:
            return (
                (TUNED_REVIEW_PROMPT if "T1" in self.levers else REVIEW_PROMPT) + view
                + "\n\n" + brief + "\n\nREVIEW REQUEST:\n"
                + json.dumps(request, ensure_ascii=False)
            )

        thread = self.rr_thread(uid, index)
        state = self.rr_state.get(uid)
        delta = None
        tag = ({"review_index": index, "review_mode": "resumed" if thread else "fresh"}
               if self.rr_comparison else None)
        if thread is not None:
            delta = self.rr_delta(request, state)
            prompt = RR_DELTA_PROMPT + json.dumps(delta, ensure_ascii=False)
        else:
            prompt = full_prompt(view, brief)
        call = await self.model(uid, call_id, prompt, "review", tag=tag, review_thread=thread)
        self.write_review_request(call, request, delta)
        resumed, fallback = thread is not None, None
        if thread is not None and (call["error"] or not call["turn_usages"]):
            # The resume failed at the harness level (nonzero exit, timeout, unsent prompt
            # or no turn.completed): the call is handed back with its own accounting and
            # exactly ONE fresh full review follows, counted.
            fallback = call["error"] or "no turn.completed"
            self.counts["resume_fallbacks"] += 1
            await self.clock_out(uid, "in_progress", call,
                                 f"reviewer resume failed: {fallback}"[:200], "", [])
            clocked = await self.host.tool(
                "shiftwork_clock_in", {"checkpoint": str(self.checkpoint), "unit_id": uid}
            )
            self.mark("clock_in", uid)
            brief = Path(clocked["unit"]["brief_path"]).read_text(encoding="utf-8")
            view = json.dumps(prompt_view(clocked), ensure_ascii=False)
            call = await self.model(
                uid, f"{self.job_id}-{len(self.calls):03d}-{uid}", full_prompt(view, brief),
                "review", tag={"review_index": index, "review_mode": "fresh-fallback",
                               "fallback_reason": fallback},
            )
            self.write_review_request(call, request, None)
            resumed = False
        if call["error"]:
            # A Codex exit, timeout or unsent prompt says nothing about the work: harness.
            await self.clock_out(uid, "blocked", call,
                                 f"reviewer call failed: {call['error']}"[:200], "", [])
            return {"error": f"reviewer call failed: {call['error']}"}
        response, error = None, None
        raw = (self.host.out / call["artifact_dir"] / "events.jsonl").read_text(
            encoding="utf-8", errors="replace"
        )
        try:
            response = codex_adapter.normalize_events(raw, MODEL)
        except (ValueError, KeyError, TypeError) as exc:
            error = f"invalid reviewer answer: {exc}"
        verdict = assess_review(request, response, error)
        # Repair findings, merged per finding: the model's findings plus a harness finding
        # for EVERY red fast check, so a model finding on a unit never hides that unit's
        # red check output from its repair brief (QW round 2, finding 10).
        harness = [
            {"unit": u["id"], "criterion": "fast-check", "source": "harness",
             "detail": "Fast check failed: " + checks[u["id"]]["output"]}
            for u in request["units"] if not u["fast_check_passed"]
        ]
        findings = verdict["findings"] + harness
        round_kind = None if verdict["approved"] else (
            "rejection" if findings else "reviewer-error"
        )
        rr_fields = {}
        if self.rr_comparison:
            # Convergence: model findings on a member whose revision is unchanged since
            # this reviewer unit's previous review (its previous answered review).
            prior = next((r for r in reversed(self.reviews)
                          if r["unit"] == uid and r["valid_answer"]), None)
            revisions = {u["id"]: u["revision"] for u in request["units"]}
            converged = convergence_findings(prior, revisions, verdict["findings"])
            rr_fields = {
                "resumed": resumed, "thread_id": call["thread_id"],
                "resume_fallback": fallback,
                "calls": [c["id"] for c in self.calls
                          if c["unit"] == uid and c.get("review_index") == index],
                "convergence_findings": len(converged),
                "convergence_detail": converged,
                **({"changed_members": sorted(
                    u["id"] for u in delta["units"] if u["changed_since_last_review"]
                )} if resumed else {}),
            }
        self.reviews.append(
            {
                "unit": uid,
                "index": index,
                "call": call["id"],
                "t_ms": int(self.clock()),
                "snapshot": str(snapshot.relative_to(self.host.out)),
                "reviewer_context_id": request["reviewer_context_id"],
                "membership": request["membership"],
                "shiftwork_reviews": request["shiftwork_reviews"],
                "revisions": {u["id"]: u["revision"] for u in request["units"]},
                "fast_checks": {u["id"]: u["fast_check_passed"] for u in request["units"]},
                "evidence": response.get("evidence") if response else None,
                "valid_answer": response is not None,
                **({"delta": True, "changed_members": sorted(
                    u["id"] for u in request["units"] if u["changed_since_last_review"]
                )} if "previous_findings" in request else {}),
                "error": error,
                **verdict,
                "repair_findings": findings,
                "round_kind": round_kind,
                "adjudication": None,
                **rr_fields,
            }
        )
        if "RR" in self.levers:
            if round_kind == "reviewer-error":
                self.rr_state.pop(uid, None)  # the next review is fresh, on a new thread
            else:
                self.rr_state[uid] = {
                    "thread": call["thread_id"],
                    "resumes": (state["resumes"] + 1) if resumed else 0,
                    "revisions": {u["id"]: u["revision"] for u in request["units"]},
                    "files": request["context_files"],
                }
        status = "done" if verdict["approved"] else "blocked"
        notes = (
            "approved" if verdict["approved"]
            else f"rejected ({round_kind}): {len(verdict['findings'])} model findings, "
            f"{len(harness)} fast-check findings; {', '.join(verdict['reasons'])}"
        )
        await self.clock_out(
            uid, status, call, "review approved" if verdict["approved"] else "review rejected",
            notes, [{"kind": "review", "ref": call["artifact_dir"]}],
        )
        if verdict["approved"]:
            return {"approved": True}
        return {"rejected": True, "findings": findings, "round_kind": round_kind}

    def write_review_request(self, call: dict, request: dict, delta: dict | None) -> None:
        directory = self.host.out / call["artifact_dir"]
        (directory / "request.json").write_text(json.dumps(request, indent=2) + "\n",
                                                encoding="utf-8")
        if delta is not None:
            (directory / "delta.json").write_text(json.dumps(delta, indent=2) + "\n",
                                                  encoding="utf-8")

    # after the arm: judge seeds and findings on the saved snapshots -------------------
    def seed_presence(self, seed: dict, snapshot: Path) -> dict:
        """Is the seed still in the reviewed revision? Exact bytes first, then the
        unit-isolated oracle on the seed's newly failing criteria."""
        files = self.case_units[seed["unit"]]["files"]
        if live_cases.revision(snapshot, files) == seed["after_sha"]:
            return {"presence": "present", "still_failing": list(seed["failing"]),
                    "by": "bytes"}
        oracle = live_cases.unit_criteria_status(self.case, snapshot, seed["unit"],
                                                 seed["failing"])
        if oracle["error"]:
            return {"presence": "unknown", "still_failing": [], "by": "oracle",
                    "error": oracle["error"]}
        still = [c for c in seed["failing"] if oracle["results"].get(c) is False]
        return {"presence": "present" if still else "removed-before-review",
                "still_failing": still, "by": "oracle"}

    def adjudicate(self) -> None:
        """Seeds are judged at the first valid review that covered them, only if still
        present there; every other finding by the unit-isolated oracle at the reviewed
        revision. Runs after the arm, so it is never inside the accepted latency."""
        start = time.monotonic()
        for seed in self.seeds:
            if not seed["applied"]:
                continue
            review = next((r for r in self.reviews if r["valid_answer"]
                           and seed["unit"] in r["membership"]), None)
            if review is None:
                seed["status"] = "never-reviewed"
                continue
            seed["seen_by"] = f"{review['unit']}#{review['index']}"
            presence = self.seed_presence(seed, self.host.out / review["snapshot"])
            seed.update(presence=presence["presence"], presence_check=presence)
            if presence["presence"] != "present":
                seed["status"] = ("removed-before-review"
                                  if presence["presence"] == "removed-before-review"
                                  else "presence-unknown")
                continue
            hits = [f for f in review["findings"] if f["unit"] == seed["unit"]
                    and f["criterion"] in presence["still_failing"]]
            seed["caught"] = bool(hits)
            seed["caught_criteria"] = sorted({f["criterion"] for f in hits})
            seed["status"] = "caught" if hits else "missed"
            review.setdefault("_seed_keys", set()).update(
                (f["unit"], f["criterion"]) for f in hits
            )
        for review in self.reviews:
            keyed = review.pop("_seed_keys", set())
            rows = []
            snapshot = self.host.out / review["snapshot"]
            for finding in review["findings"]:
                key = (finding["unit"], finding["criterion"])
                if key in keyed:
                    rows.append({**key_dict(key), "verdict": "true", "source": "seed"})
                    continue
                oracle = live_cases.unit_criteria_status(
                    self.case, snapshot, finding["unit"], [finding["criterion"]]
                )
                result = oracle["results"].get(finding["criterion"])
                rows.append(
                    {**key_dict(key), "source": "oracle",
                     "verdict": "unknown" if oracle["error"] or result is None
                     else ("false" if result else "true")}
                )
            review["adjudication"] = rows
        self.harness_ms["adjudication"] += (time.monotonic() - start) * 1000

    # replan ----------------------------------------------------------------------
    async def replan(self, edit: dict) -> None:
        """Planner edit: repair units X2 (+ integration recheck I2), reviewer back to todo."""
        reviewer, rnd, findings = edit["reviewer"], edit["round"], edit["findings"]
        before_text = self.checkpoint.read_text(encoding="utf-8")
        doc = json.loads(before_text)
        units = {u["id"]: u for u in doc["plan"]["units"]}
        repaired = []
        for base in dict.fromkeys(f["unit"] for f in findings):
            rid = f"{base}2-r{rnd}"
            prev = (self.repairs_of.get(base) or [base])[-1]
            mine = [f for f in findings if f["unit"] == base]
            text = (
                author_brief(self.case_units[base])
                + "\nReviewer findings (verbatim):\n"
                + json.dumps(mine, indent=2, ensure_ascii=False) + "\n"
            )
            repaired.append((rid, base, prev, text))
        consumers = [
            c for c in downstream_closure(self.case, [r[1] for r in repaired])
            if units.get(c, {}).get("status") == "done" and c not in [r[1] for r in repaired]
        ]
        new_units, added = [], []
        for rid, base, prev, text in repaired:
            path = self.briefs / f"{rid}.md"
            path.write_text(f"# {rid} — Repair {base}\n\n{text}", encoding="utf-8")
            new_units.append(
                {"id": rid, "title": f"Repair {base} after {reviewer} round {rnd}",
                 "brief_path": str(path), "status": "todo", "role": "implementer",
                 "depends_on": [prev], "verify": f"python checks/check_{base}.py",
                 "touches": list(self.case_units[base]["files"])}
            )
            self.units[rid] = {"id": rid, "kind": "repair", "base": base, "round": rnd,
                               "files": list(self.case_units[base]["files"]), "members": []}
            self.repairs_of.setdefault(base, []).append(rid)
            added.append(rid)
        if consumers:
            iid = f"I2-{reviewer}-r{rnd}"
            files = [f for c in consumers for f in self.case_units[c]["files"]]
            checks = "\n".join(f"- {c}: python checks/check_{c}.py" for c in consumers)
            text = (
                f"# {iid} — Integration recheck after {reviewer} round {rnd}\n\n"
                f"Upstream units {', '.join(r[1] for r in repaired)} were repaired. These "
                f"dependents consumed the changed artifact; re-run their fast checks:\n"
                f"{checks}\n\nFiles you own: {', '.join(files)}\n\n"
                "Reviewer findings that caused the repair (verbatim):\n"
                + json.dumps(findings, indent=2, ensure_ascii=False) + "\n"
            )
            path = self.briefs / f"{iid}.md"
            path.write_text(text, encoding="utf-8")
            new_units.append(
                {"id": iid, "title": f"Integration recheck after {reviewer} round {rnd}",
                 "brief_path": str(path), "status": "todo", "role": "implementer",
                 "depends_on": [r[0] for r in repaired] + consumers,
                 "verify": "; ".join(f"python checks/check_{c}.py" for c in consumers),
                 "touches": files}
            )
            self.units[iid] = {"id": iid, "kind": "integration", "base": None, "round": rnd,
                               "consumers": consumers, "files": files, "members": []}
            added.append(iid)
        target = units[reviewer]
        invalidated = sorted(
            {c["id"] for r in repaired for c in self.case_units[r[1]]["criteria"]}
            | {c["id"] for u in consumers for c in self.case_units[u]["criteria"]}
        )
        with Path(target["brief_path"]).open("a", encoding="utf-8") as brief:
            brief.write(
                f"\n## Replan round {rnd}\n\nAdded to reviews and depends_on: "
                f"{', '.join(added) or 'none (fresh review only)'}. Invalidated criteria: "
                f"{', '.join(invalidated) or 'none'}. The previous verdict does not carry "
                "over: review the new exact revisions supplied at clock-in, every member, "
                "every criterion.\n"
            )
        target["status"] = "todo"
        target["depends_on"] = list(dict.fromkeys(target["depends_on"] + added))
        target["reviews"] = list(dict.fromkeys(target.get("reviews", []) + added))
        self.units[reviewer]["members"] = list(target["reviews"])
        self.units[reviewer]["round"] = rnd
        index = [u["id"] for u in doc["plan"]["units"]].index(reviewer)
        doc["plan"]["units"][index:index] = new_units
        rationale = (
            f"replan {reviewer} round {rnd}: findings -> {', '.join(added) or 'fresh review'}; "
            f"{reviewer} back to todo with them in depends_on and reviews"
        )
        doc["history"] = (doc.get("history") or [])[-4:] + [
            {"unit": reviewer, "outcome": rationale[:200]}
        ]
        doc["handoff"]["next_action"] = (
            f"Run {', '.join(added)} then re-review {reviewer}." if added
            else f"Re-review {reviewer}."
        )
        candidate = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        edit_dir = self.dir / "plan-edits" / f"{reviewer}-r{rnd}"
        edit_dir.mkdir(parents=True)
        (edit_dir / "before.json").write_text(before_text, encoding="utf-8")
        (edit_dir / "after.json").write_text(candidate, encoding="utf-8")
        (edit_dir / "rationale.json").write_text(
            json.dumps({"rationale": rationale, "findings": findings, "added": added}, indent=2)
            + "\n", encoding="utf-8"
        )
        valid = await self.host.tool("validate_json", {"output": candidate,
                                                       "schema": self.host.schema})
        if not valid.get("valid"):
            raise ArmStopped(f"schema refused the replan: {valid.get('feedback')}")
        tmp = self.checkpoint.with_name(self.checkpoint.name + ".replan.tmp")
        tmp.write_text(candidate, encoding="utf-8")
        os.replace(tmp, self.checkpoint)
        try:
            await self.host.tool("shiftwork_plan", {"checkpoint": str(self.checkpoint)})
        except ArmStopped:
            self.checkpoint.write_text(before_text, encoding="utf-8")
            raise
        self.plan_edits.append(str(edit_dir.relative_to(self.host.out)))
        self.mark("plan_edit", reviewer, round=rnd, added=added)

    # record ----------------------------------------------------------------------
    def unit_usage(self, uid: str) -> dict | None:
        calls = [c for c in self.calls if c["unit"] == uid]
        return sum_usage([c["usage"] for c in calls]) if calls else sum_usage([])

    def record(self, started_at, accepted, stop_reason, stop_kind, stop_ms, accepted_ms,
               accepted_at):
        try:
            self.adjudicate()
        except Exception as exc:  # noqa: BLE001 - unjudged seeds make the arm unusable
            stop_reason = stop_reason or self.fail("adjudication", exc)
            stop_kind, accepted = "harness", False
        final = {"results": {}, "error": "no workspace", "details": {}}
        failures = classify_failures({}, [], [], self.case, None)
        if self.workspace is not None and self.workspace.is_dir():
            try:
                final = live_cases.run_hidden_oracle(self.case, self.workspace)
                failing = sorted(c for c, ok in final["results"].items() if not ok)
                failures = classify_failures(
                    self.case_units, failing, self.seeds, self.case, self.workspace
                )
                shutil.copytree(self.workspace, self.dir / "workspace",
                                ignore=shutil.ignore_patterns("__pycache__"))
            except Exception as exc:  # noqa: BLE001
                final = {"results": {}, "error": self.fail("final oracle", exc), "details": {}}
                failures = classify_failures({}, [], [], self.case, None)
        failing = sorted(c for c, ok in final["results"].items() if not ok)
        quality_failure = None if final["error"] else bool(failing)
        if accepted:
            stop_kind = "protocol" if quality_failure is True else None
        adjudicated = [row for r in self.reviews for row in r["adjudication"] or []]
        units = []
        for uid, unit in self.units.items():
            units.append(
                {"id": uid, "kind": unit["kind"], "base": unit["base"], "round": unit["round"],
                 "members": unit["members"], "files": unit["files"],
                 "context": self.mode_of(uid), "calls": unit.get("calls", []),
                 "threads": unit.get("threads", []), "revision": unit.get("revision"),
                 "usage": self.unit_usage(uid),
                 **({"i2_path": unit["i2_path"]} if "i2_path" in unit else {}),
                 **{k: unit[k] for k in ("repair_path", "fallback_reason") if k in unit}}
            )
        kinds = {}
        for kind in ("author", "repair", "integration", "reviewer"):
            calls = [c for c in self.calls if c["kind"] == kind]
            kinds[kind] = sum_usage([c["usage"] for c in calls])
        review_usage = kinds["reviewer"]
        total_usage = sum_usage([c["usage"] for c in self.calls])
        rework_calls = [c for c in self.calls if c["kind"] in ("repair", "integration")]
        if self.workspace is not None and self.workspace.is_dir() and self.ws_hashes:
            self.boundary(None, False)  # any change after the last writer: unattributed
        writes = attribute_writes(
            self.write_spans, self.writers,
            {f for u in self.case_units.values() for f in u["files"]},
        )
        model_windows = [c["window_ms"] for c in self.calls if "window_ms" in c]
        harness_windows = [h["window_ms"] for h in self.harness_windows]
        excluded = (only_in(harness_windows, model_windows, accepted_ms)
                    if accepted and accepted_ms is not None else 0.0)
        record = {
            "case_id": self.case["id"],
            "mode": self.case["mode"],
            "repeat": self.repeat,
            "attempt": self.attempt,
            "arm": self.arm,
            "variant": self.variant,
            "levers": sorted(self.levers),
            "order": self.order,
            "smoke": self.smoke,
            "job_id": self.job_id,
            "started_at": started_at,
            "accepted_at": accepted_at if accepted else None,
            "stopped_at": now(),
            "accepted": accepted,
            "status": "accepted" if accepted else "failed/censored",
            "stop_kind": stop_kind,
            "stop_reason": stop_reason,
            # Wall time minus harness-only work (seeding while no model call ran).
            "elapsed_to_accepted_ms": int(accepted_ms - excluded) if accepted else None,
            "elapsed_to_accepted_wall_ms": int(accepted_ms) if accepted else None,
            "elapsed_to_stop_ms": int(stop_ms),
            "harness_ms": {
                "seeding": int(self.harness_ms["seeding"]),
                "adjudication_after_arm": int(self.harness_ms["adjudication"]),
                "excluded_from_accepted_latency": int(excluded),
            },
            "checkpoint": str(self.checkpoint.relative_to(self.host.out)),
            "workspace": str((self.dir / "workspace").relative_to(self.host.out)),
            "workspace_tmp": str(self.workspace) if self.workspace else None,
            "codex_env_sha256": self.host.codex_env_sha,
            "units": units,
            "calls": self.calls,
            "reviews": self.reviews,
            "repair_rounds": dict(self.rounds),
            "rework": {
                "units": [u for u, x in self.units.items() if x["kind"] in ("repair",
                                                                         "integration")],
                "rounds": sum(self.rounds.values()),
                "rejection_rounds": sum(r["kind"] == "rejection" for r in self.round_kinds),
                "reviewer_error_rounds": sum(r["kind"] == "reviewer-error"
                                             for r in self.round_kinds),
                "round_kinds": self.round_kinds,
                "usage": sum_usage([c["usage"] for c in rework_calls]),
            },
            "plan_edits": self.plan_edits,
            "escalations": self.escalations,
            "human_interventions": 0,
            "human_interventions_label": HUMAN_INTERVENTIONS_LABEL,
            "planner_dispatch": PLANNER_DISPATCH,
            "usage": {"review": review_usage, "total": total_usage, "by_kind": kinds},
            # Why a call's usage is unknown; resumed calls are split by thread delta.
            "usage_unknown": self.usage_unknown,
            "cache_write": {
                "label": "calls reporting nonzero cache_write_input_tokens; the #307 rule "
                         "assumed this category does not occur",
                "calls": [c["id"] for c in self.calls if cache_writes(c)],
            },
            "review_tokens": usage_tokens(review_usage),
            "total_tokens": usage_tokens(total_usage),
            "review_tokens_excl_cache": usage_tokens(review_usage, include_cache=False),
            "total_tokens_excl_cache": usage_tokens(total_usage, include_cache=False),
            # Per kind: the cost metric (uncached input + output) and the raw total.
            "kind_tokens_excl_cache": {k: usage_tokens(u, include_cache=False)
                                       for k, u in kinds.items()},
            "kind_tokens": {k: usage_tokens(u) for k, u in kinds.items()},
            "tuning": {
                **self.counts,
                "reviewer_invalid_answers": sum(not r["valid_answer"] for r in self.reviews),
                "delta_reviews": sum(bool(r.get("delta")) for r in self.reviews),
                **({"resumed_reviews": sum(bool(r.get("resumed")) for r in self.reviews),
                    "convergence_findings": sum(r.get("convergence_findings", 0)
                                                for r in self.reviews)}
                   if self.rr_comparison else {}),
                "repair_modes": {
                    mode: sum_usage([c["usage"] for c in self.calls
                                     if c.get("repair_mode") == mode])
                    for mode in ("patch", "fallback-shell")
                },
            },
            "fast_checks": self.fast_checks,
            "access_audit": {"hits": self.audit_hits, "clean": not self.audit_hits},
            "writes": writes,
            "harness_errors": self.errors,
            "quality": {
                "seeds": self.seeds,
                "seeded_caught": sum(s["caught"] is True for s in self.seeds),
                "seeded_missed": sum(s["caught"] is False for s in self.seeds),
                "seed_unavailable": sum(not s["applied"] for s in self.seeds),
                "seed_removed_before_review": sum(
                    s["status"] == "removed-before-review" for s in self.seeds
                ),
                "seed_not_judged": sum(
                    s["status"] in ("never-reviewed", "presence-unknown") for s in self.seeds
                ),
                "true_findings": sum(r["verdict"] == "true" for r in adjudicated),
                "false_findings": sum(r["verdict"] == "false" for r in adjudicated),
                "unknown_findings": sum(r["verdict"] == "unknown" for r in adjudicated),
                "final_oracle": {"results": final["results"], "error": final["error"],
                                 "failing": failing},
                # Final-oracle failures split by the unit-isolated oracle (QW round 2,
                # finding 7): only a criterion that still fails on its own unit's code, and
                # is not that unit's surviving seed, is an author defect.
                "author_defects_missed": failures["author_defects_missed"],
                "final_failures": failures,
                "quality_failure": quality_failure if accepted else None,
            },
            "trace": self.trace,
        }
        if self.rr_comparison:
            record.update(self.rr_record())
        if self.batch_comparison:
            record.update(self.batch_record())
        record["observations"] = observations(self.case, record)
        return record

    def batch_record(self) -> dict:
        """The AB comparison's extra figures: the author calls' tool steps (completed
        command_execution and file_change items), per call and in total, and the
        author-only cost (uncached input + output, and the raw total)."""
        calls = [c for c in self.calls if c["kind"] == "author"]
        usage = sum_usage([c["usage"] for c in calls])
        steps = [{"call": c["id"], "unit": c["unit"], "tool_steps": c.get("tool_steps")}
                 for c in calls]
        return {
            "author_calls": len(calls),
            "author_tool_steps": steps,
            "author_tool_steps_total": (None if any(s["tool_steps"] is None for s in steps)
                                        else sum(s["tool_steps"] for s in steps)),
            "author_tokens_excl_cache": usage_tokens(usage, include_cache=False),
            "author_tokens": usage_tokens(usage),
        }

    def rr_record(self) -> dict:
        """The RR comparison's extra figures: re-review-only cost, the counts, and every
        reviewer call's own cache read (the base arm's Codex cache hit is not reliable, so
        the result must be able to show it call by call)."""
        calls = [c for c in self.calls if c["kind"] == "reviewer"]
        later = sum_usage([c["usage"] for c in calls if c.get("review_index", 0) >= 1])
        first = sum_usage([c["usage"] for c in calls if c.get("review_index", 0) == 0])
        return {
            "rereview_tokens_excl_cache": usage_tokens(later, include_cache=False),
            "rereview_tokens": usage_tokens(later),
            "first_review_tokens_excl_cache": usage_tokens(first, include_cache=False),
            "first_review_tokens": usage_tokens(first),
            "reviewer_cache": [
                {"call": c["id"], "review_index": c.get("review_index"),
                 "review_mode": c.get("review_mode"), "resumed": c["resumed"],
                 "uncached_input": (c["usage"] or {}).get("uncached_input"),
                 "cache_read": (c["usage"] or {}).get("cache_read"),
                 "output": (c["usage"] or {}).get("output")}
                for c in calls
            ],
            "reviewer_zero_cache_calls": sum(
                (c["usage"] or {}).get("cache_read") == 0 for c in calls),
        }


def classify_failures(units: dict, failing: list[str], seeds: list[dict], case: dict,
                      workspace: Path | None) -> dict:
    """Attribute each final-oracle failure with the unit-isolated oracle.

    ``caused_by_other_units``: passes on its own unit's code with every other unit at the
    reference (a seed side effect or another author's defect upstream).
    ``seeded_still_failing``: fails in isolation and is a newly failing criterion of that
    unit's applied seed. ``author_defects_missed``: fails in isolation otherwise.
    ``unknown``: the isolated oracle could not say. Never a guess.
    """
    result = {"label": "final-oracle failures attributed by the unit-isolated oracle",
              "author_defects_missed": [], "seeded_still_failing": [],
              "caused_by_other_units": [], "unknown": []}
    owner = {c["id"]: uid for uid, u in units.items() for c in u["criteria"]}
    seeded = {(s["unit"], c) for s in seeds if s.get("applied") for c in s.get("failing", [])}
    by_unit: dict[str | None, list[str]] = {}
    for criterion in failing:
        by_unit.setdefault(owner.get(criterion), []).append(criterion)
    for uid, criteria in by_unit.items():
        if uid is None:
            result["unknown"] += criteria
            continue
        oracle = live_cases.unit_criteria_status(case, workspace, uid, criteria)
        for criterion in criteria:
            alone = None if oracle["error"] else oracle["results"].get(criterion)
            if alone is None:
                result["unknown"].append(criterion)
            elif alone:
                result["caused_by_other_units"].append(criterion)
            elif (uid, criterion) in seeded:
                result["seeded_still_failing"].append(criterion)
            else:
                result["author_defects_missed"].append(criterion)
    return {k: sorted(v) if isinstance(v, list) else v for k, v in result.items()}


def _overlap(a: list, b: list) -> bool:
    """Half-open windows; an end never recorded (None) is still open."""
    inf = float("inf")
    return a[0] < (inf if b[1] is None else b[1]) and b[0] < (inf if a[1] is None else a[1])


def attribute_writes(spans: list[dict], writers: dict[str, dict], owned: set[str]) -> dict:
    """Who wrote what, from workspace hashes taken at every author-call and seed boundary.

    ``spans``: {window_ms, active (writer ids), changed (files)} between two boundaries.
    ``writers``: id -> {kind: call|seed, unit, window_ms, call: owned, event_paths;
    seed: claims (the one file it mutated, or nothing)}. ``owned``: every unit's files.

    A file changed in a span goes to the active calls whose file_change events name it;
    else to an active seed that claims it (harness, not an author write); else to the one
    active call if only one ran (so a shell write to another unit's file in a call's own
    span is that call's); else to the one active call that owns it. Anything else is
    ``unattributed``; it makes ``conflict_free`` unknown only when some unit owns it.
    """
    calls = {k: w for k, w in writers.items() if w.get("kind") == "call"}
    written: dict[str, dict[str, str]] = {k: {} for k in calls}
    harness, unattributed = [], []
    for span in spans:
        active = [a for a in span["active"] if a in calls]
        seeds = [a for a in span["active"] if writers.get(a, {}).get("kind") == "seed"]
        for f in span["changed"]:
            namers = [a for a in active if f in calls[a].get("event_paths", [])]
            claimers = [a for a in seeds if f in writers[a].get("claims", [])]
            owners = [a for a in active if f in calls[a]["owned"]]
            if namers:
                for a in namers:
                    written[a].setdefault(f, "event")
            elif claimers:
                harness += [{"writer": a, "file": f} for a in claimers]
            elif len(active) == 1:
                written[active[0]].setdefault(f, "only-writer")
            elif len(owners) == 1:
                written[owners[0]].setdefault(f, "owner")
            else:
                unattributed.append({"file": f, "window_ms": span["window_ms"],
                                     "active": span["active"], "owned_by_a_unit": f in owned})
    rows = []
    for a, w in calls.items():
        files = sorted(written[a])
        rows.append({"call": a, "unit": w["unit"], "window_ms": w["window_ms"],
                     "changed": w.get("changed", []), "written": files,
                     "basis": {f: written[a][f] for f in files},
                     "unowned": [f for f in files if f not in w["owned"]]})
    conflicts = []
    ids = list(calls)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            wa, wb = calls[a], calls[b]
            if wa["unit"] == wb["unit"] or not _overlap(wa["window_ms"], wb["window_ms"]):
                continue
            fa, fb = set(written[a]), set(written[b])
            shared = (fa & fb) | (fa & set(wb["owned"])) | (fb & set(wa["owned"]))
            if shared:
                conflicts.append({"calls": [a, b], "files": sorted(shared)})
    unknown = any(u["owned_by_a_unit"] for u in unattributed)
    return {
        "calls": rows,
        "spans": spans,
        "unowned": [{"call": r["call"], "unit": r["unit"], "file": f}
                    for r in rows for f in r["unowned"]],
        "harness": harness,
        "unattributed": unattributed,
        "conflicts": conflicts,
        "conflict_free": False if conflicts else (None if unknown else True),
    }


def key_dict(key: tuple[str, str]) -> dict:
    return {"unit": key[0], "criterion": key[1]}


# --- observations -------------------------------------------------------------------


def observations(case: dict, record: dict) -> dict:
    """The frozen case table's approval/coverage observations, from the record alone."""
    units = {u["id"]: u for u in record["units"]}
    authors = [u for u in record["units"] if u["kind"] != "reviewer"]
    reviewers = [u for u in record["units"] if u["kind"] == "reviewer"]
    author_threads = {t for u in authors for t in u["threads"]}
    review_threads = [t for u in reviewers for t in u["threads"]]
    contexts = [r["reviewer_context_id"] for r in record["reviews"]]
    separate = (
        None if len(review_threads) < sum(len(u["calls"]) for u in reviewers)
        else not (author_threads & set(review_threads)) and len(set(contexts)) == len(contexts)
    )
    approved = {}
    for review in record["reviews"]:
        if review["approved"]:
            for mid in review["membership"]:
                approved[mid] = review
    criteria = {u["id"]: {c["id"] for c in u["criteria"]} for u in case["units"]}
    coverage = all(
        mid in approved
        and any(
            isinstance(e, dict) and e.get("unit") == mid and set(e.get("criteria", []))
            == criteria[mid]
            for e in approved[mid]["evidence"] or []
        )
        for mid in criteria
    )
    first = {}
    done = {}
    for row in record["trace"]:
        if row["event"] == "clock_in":
            first.setdefault(row["unit"], row["t_ms"])
        if row["event"] == "clock_out" and row.get("status") == "done":
            done[row["unit"]] = row["t_ms"]
    gated = gated_units(case)
    consumers = [u["id"] for u in case["units"] if set(u["depends_on"]) & set(gated)]
    contract = all(
        f"QA_{g}" in done and all(c in first and done[f"QA_{g}"] <= first[c] for c in consumers)
        for g in gated
    )
    integration_first = all(
        all(m in done and done[m] <= first[r["id"]] for m in r["members"]
            if units[m]["kind"] == "author")
        for r in reviewers if r["id"] in first
    )
    checks = record["fast_checks"]
    obs = {
        "separate_reviewer": separate,
        "equivalent_coverage": coverage,
        "full_chain_evidence": all(units[u["id"]]["revision"] for u in case["units"]),
        "contribution_attribution": all(u["threads"] for u in authors if u["calls"]),
        "per_unit_checks_retained": all(u["id"] in checks for u in case["units"]),
        "contract_approval_before_consumers": contract if gated else None,
        "integration_before_review": integration_first,
        # From the real writes (hashes around each author call), not declared files.
        "conflicting_writes_deferred": record["writes"]["conflict_free"],
    }
    required = {
        "native-chain": ["separate_reviewer", "equivalent_coverage"],
        "sequential-delegates": ["full_chain_evidence", "contribution_attribution",
                                 "per_unit_checks_retained"],
        "mixed-fork-join": ["contract_approval_before_consumers", "integration_before_review",
                            "conflicting_writes_deferred"],
    }.get(case["mode"], [])
    obs["required"] = required
    values = [obs[k] for k in required]
    obs["holds"] = None if None in values else all(values)
    return obs


# --- summary ------------------------------------------------------------------------


def distribution(values: list) -> dict:
    known = [v for v in values if v is not None]
    return {
        "sample_size": len(known),
        "unknown_or_censored": len(values) - len(known),
        "median": statistics.median(known) if known else None,
        "range": [min(known), max(known)] if known else None,
    }


def saving(baseline, grouped):
    """1 - grouped / per-task, only for an observed nonzero baseline; else unknown."""
    if baseline is None or grouped is None or baseline == 0:
        return None
    return 1 - grouped / baseline


JUDGED = ("caught", "missed")


def seed_units(record: dict) -> dict:
    return {s["unit"]: s for s in record["quality"]["seeds"]}


def seed_judged(seed: dict) -> bool:
    """Judged at a review that saw it still present (hand-built records: applied)."""
    if "status" in seed and seed["status"] not in ("applied", "unavailable"):
        return seed["status"] in JUDGED
    return bool(seed.get("applied")) and seed.get("caught") is not None


def pair_summary(case_id: str, repeat: int, per: dict | None, grouped: dict | None) -> dict:
    present = [r for r in (per, grouped) if r]
    harness = any(stop_kind_of(r) == "harness" for r in present)
    pair = {"case_id": case_id, "repeat": repeat,
            "attempt": max((r.get("attempt", 0) for r in present), default=0),
            "harness_censored": harness,
            "complete": bool(per and grouped) and not harness}
    for key in ("review_tokens", "total_tokens", "review_tokens_excl_cache",
                "total_tokens_excl_cache"):
        name = key.replace("_tokens", "_saving")
        pair[name] = saving(per[key], grouped[key]) if pair["complete"] else None
    if pair["complete"]:
        p, g = seed_units(per), seed_units(grouped)
        both = sorted(u for u in set(p) & set(g) if seed_judged(p[u]) and seed_judged(g[u]))
        per_caught = {u for u in both if p[u]["caught"] is True}
        grouped_caught = {u for u in both if g[u]["caught"] is True}
        removed = sorted(u for u in set(p) | set(g) if "removed-before-review" in (
            p.get(u, {}).get("status"), g.get(u, {}).get("status")))
        pair["seeds"] = {
            "compared_units": both,
            "excluded_unavailable": sorted((set(p) | set(g)) - set(both) - set(removed)),
            "excluded_removed_before_review": removed,
            "per_task_caught": sorted(per_caught),
            "grouped_caught": sorted(grouped_caught),
            "grouped_missed_caught_by_per_task": sorted(per_caught - grouped_caught),
        }
        pair["both_accepted"] = per["accepted"] and grouped["accepted"]
    else:
        pair["seeds"] = None
        pair["both_accepted"] = False
    return pair


def cohort(records: list[dict]) -> dict:
    quality = [r["quality"] for r in records]
    return {
        "sample_size": len(records),
        "accepted": sum(r["accepted"] for r in records),
        "failed_or_censored": sum(not r["accepted"] for r in records),
        "harness_censored": sum(stop_kind_of(r) == "harness" for r in records),
        "protocol_stops": sum(stop_kind_of(r) == "protocol" for r in records),
        "quality_failures": sum(q["quality_failure"] is True for q in quality),
        **{
            key: distribution([r[key] for r in records])
            for key in ("review_tokens", "total_tokens", "review_tokens_excl_cache",
                        "total_tokens_excl_cache", "elapsed_to_accepted_ms",
                        "elapsed_to_stop_ms")
        },
        "rework_rounds": distribution([r["rework"]["rounds"] for r in records]),
        "reviewer_error_rounds": sum(r["rework"].get("reviewer_error_rounds", 0)
                                     for r in records),
        "rework_units": distribution([len(r["rework"]["units"]) for r in records]),
        "escalations": sum(r["escalations"] for r in records),
        "human_interventions": sum(r["human_interventions"] for r in records),
        "human_interventions_label": HUMAN_INTERVENTIONS_LABEL,
        "quality": {
            key: sum(q.get(key, 0) for q in quality)
            for key in ("seeded_caught", "seeded_missed", "seed_unavailable",
                        "seed_removed_before_review", "seed_not_judged", "true_findings",
                        "false_findings", "unknown_findings")
        },
        "author_defects_missed": sum(len(q["author_defects_missed"]) for q in quality),
    }


def mode_verdict(per: list[dict], grouped: list[dict], pairs: list[dict]) -> dict:
    """The frozen thresholds for one execution-mode cohort; None is inconclusive.

    Design, *Harness censors and the rerun rule*: the checks run on clean pairs only
    (both arms of a still-censored pair are left out). The verdict is fail if any check
    is false there, since a missing pair cannot rescue a failed threshold; otherwise
    inconclusive if any pair is still censored or any check is unknown; else pass.
    """
    censored_keys = {(p["case_id"], p["repeat"]) for p in pairs if p["harness_censored"]}
    per = [r for r in per if (r["case_id"], r["repeat"]) not in censored_keys]
    grouped = [r for r in grouped if (r["case_id"], r["repeat"]) not in censored_keys]
    checks: dict[str, bool | None] = {}
    complete = [p for p in pairs if p["complete"]]
    if not complete:
        checks["grouped_misses_none_caught_by_per_task"] = None
    elif any(p["seeds"]["grouped_missed_caught_by_per_task"] for p in complete):
        checks["grouped_misses_none_caught_by_per_task"] = False
    elif len(complete) < len(pairs):
        checks["grouped_misses_none_caught_by_per_task"] = None
    else:
        checks["grouped_misses_none_caught_by_per_task"] = True
    clean_per = [r for r in per if stop_kind_of(r) != "harness"]
    clean_grp = [r for r in grouped if stop_kind_of(r) != "harness"]
    per_tot = [r["total_tokens"] for r in clean_per]
    grp_tot = [r["total_tokens"] for r in clean_grp]
    if not per_tot or not grp_tot or None in per_tot or None in grp_tot:
        checks["median_total_tokens_decrease"] = None
    else:
        checks["median_total_tokens_decrease"] = statistics.median(grp_tot) < statistics.median(
            per_tot
        )
    per_lat = [r["elapsed_to_accepted_ms"] for r in clean_per if r["accepted"]]
    grp_lat = [r["elapsed_to_accepted_ms"] for r in clean_grp if r["accepted"]]
    if not per_lat or not grp_lat:
        checks["median_accepted_latency_not_increase"] = None
    else:
        checks["median_accepted_latency_not_increase"] = statistics.median(
            grp_lat
        ) <= statistics.median(per_lat)
    arms = per + grouped
    clean = clean_per + clean_grp
    if not arms:
        checks["approval_coverage_holds"] = None
    elif any(stop_kind_of(r) == "protocol" or r["quality"]["quality_failure"] is True
             or r["observations"]["holds"] is False for r in clean):
        checks["approval_coverage_holds"] = False
    elif len(clean) < len(arms) or any(
        r["quality"]["quality_failure"] is None or r["observations"]["holds"] is None
        for r in clean
    ):
        checks["approval_coverage_holds"] = None
    else:
        checks["approval_coverage_holds"] = True
    values = list(checks.values())
    censored = [f"{p['case_id']}#r{p['repeat']}" for p in pairs if p["harness_censored"]]
    if False in values:
        result = "fail"
    elif censored or None in values:
        result = "inconclusive"
    else:
        result = "pass"
    return {"checks": checks, "result": result, "harness_censored_pairs": censored}


def final_attempts(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split records into the final attempt of each (case, repeat) and voided attempts."""
    last: dict[tuple, int] = {}
    for r in records:
        key = (r["case_id"], r["repeat"])
        last[key] = max(last.get(key, 0), r.get("attempt", 0))
    final = [r for r in records if r.get("attempt", 0) == last[(r["case_id"], r["repeat"])]]
    voided = [r for r in records if r.get("attempt", 0) != last[(r["case_id"], r["repeat"])]]
    return final, voided


def summarize_live(records: list[dict]) -> dict:
    matched, voided = final_attempts([r for r in records if not r.get("smoke")])
    smoke, smoke_voided = final_attempts([r for r in records if r.get("smoke")])
    pairs = []
    for case_id, repeat in sorted({(r["case_id"], r["repeat"]) for r in matched}):
        arms = {r["arm"]: r for r in matched if r["case_id"] == case_id and r["repeat"] == repeat}
        pairs.append(pair_summary(case_id, repeat, arms.get("per-task"), arms.get("grouped")))
    modes = {}
    for case_id in sorted({r["case_id"] for r in matched}):
        per = [r for r in matched if r["case_id"] == case_id and r["arm"] == "per-task"]
        grp = [r for r in matched if r["case_id"] == case_id and r["arm"] == "grouped"]
        mine = [p for p in pairs if p["case_id"] == case_id]
        modes[case_id] = {
            "per-task": cohort(per),
            "grouped": cohort(grp),
            "pairs": len(mine),
            **{
                key: distribution([p[key] for p in mine])
                for key in ("review_saving", "total_saving", "review_saving_excl_cache",
                            "total_saving_excl_cache")
            },
            "verdict": mode_verdict(per, grp, mine),
        }
    results = [m["verdict"]["result"] for m in modes.values()]
    if "fail" in results:
        adoption, note = "blocked", "A core-mode threshold failed; adoption is blocked."
    elif len(results) == 3 and all(r == "pass" for r in results):
        adoption = "pending-scenarios"
        note = ("Core modes pass; adoption beyond review-only guidance waits for the five "
                "scenarios, which were not run.")
    else:
        adoption, note = "inconclusive", "Not every core mode has a conclusive pass."
    void = voided + smoke_voided
    void_tokens = [r["total_tokens"] for r in void]
    summary = {
        "adoption": adoption,
        "adoption_note": note,
        "limitations": LIMITS,
        "run_count": len(matched),
        "planner_dispatch": PLANNER_DISPATCH,
        "human_interventions_label": HUMAN_INTERVENTIONS_LABEL,
        "pairs": pairs,
        "modes": modes,
        "review_saving": distribution([p["review_saving"] for p in pairs]),
        "total_saving": distribution([p["total_saving"] for p in pairs]),
        "voided_attempts": {
            "label": "harness-censored attempts, rerun once; kept with their spend",
            "records": [
                {"job_id": r["job_id"], "attempt": r.get("attempt", 0),
                 "stop_kind": stop_kind_of(r), "stop_reason": r.get("stop_reason"),
                 "total_tokens": r["total_tokens"]}
                for r in void
            ],
            "total_tokens": None if None in void_tokens else sum(void_tokens),
        },
        # The #307 rule assumed no cache writes; any nonzero report is flagged here.
        "cache_write": {
            "nonzero": any((r.get("cache_write") or {}).get("calls") for r in records),
            "jobs": sorted({f"{r['job_id']}/{c}" for r in records
                            for c in (r.get("cache_write") or {}).get("calls", [])}),
        },
    }
    if smoke:
        totals = [r["total_tokens"] for r in smoke]
        pair_total = None if None in totals else sum(totals)
        censored = sum(stop_kind_of(r) == "harness" for r in smoke)
        # A projection only from a whole, uncensored pair: a censored arm stopped early
        # (or never ran) and would understate the spend (QW round 2, finding 2).
        whole = sorted(r["arm"] for r in smoke) == sorted(ARMS) and not censored
        projected = (pair_total / len(smoke) * FULL_RUN_JOBS
                     if whole and pair_total is not None else None)
        summary["smoke"] = {
            "label": "smoke data; not merged into the matched sample",
            "jobs": len(smoke),
            "harness_censored": censored,
            "projection_basis": "both smoke arms ran and neither was harness-censored"
            if whole else "none: the smoke pair is incomplete or harness-censored",
            "tokens_measured": pair_total,
            "projected_tokens_for_18_jobs": projected,
            "budget_gate_tokens": BUDGET_GATE_TOKENS,
            "exceeds_gate": None if projected is None else projected > BUDGET_GATE_TOKENS,
            "records": [
                {"job_id": r["job_id"], "status": r["status"],
                 "stop_kind": stop_kind_of(r), "total_tokens": r["total_tokens"],
                 "review_tokens": r["review_tokens"]}
                for r in smoke
            ],
        }
    return summary


# --- the tuning summary (TUNING_DESIGN, *Design and gates*) -------------------------------

TUNING_METRICS = {
    # name: (reader, cost metric?) -- uncached input + output is the ruled cost metric.
    "uncached_plus_output": lambda r: r.get("total_tokens_excl_cache"),
    "raw_total": lambda r: r.get("total_tokens"),
    "review_uncached_plus_output": lambda r: r.get("review_tokens_excl_cache"),
    "review_raw": lambda r: r.get("review_tokens"),
    "repair_uncached_plus_output": lambda r: (r.get("kind_tokens_excl_cache") or {}).get("repair"),
    "repair_raw": lambda r: (r.get("kind_tokens") or {}).get("repair"),
}
TUNING_COUNTS = ("patch_calls", "patch_invalid_answers", "patch_red_checks", "fallbacks",
                 "reviewer_invalid_answers", "delta_reviews")
# The RR comparison reads the same figures plus the re-review-only cost; T3's delta count
# gives way to the resume counts.
RR_METRICS = {
    **TUNING_METRICS,
    "rereview_uncached_plus_output": lambda r: r.get("rereview_tokens_excl_cache"),
    "rereview_raw": lambda r: r.get("rereview_tokens"),
}
RR_COUNTS = ("patch_calls", "patch_invalid_answers", "patch_red_checks", "fallbacks",
             "reviewer_invalid_answers", "resumed_reviews", "resume_fallbacks",
             "fresh_after_error", "resume_capped", "convergence_findings")


# The AB comparison reads the RR figures plus the author-only cost and the author tool steps.
BATCH_METRICS = {
    **RR_METRICS,
    "author_uncached_plus_output": lambda r: r.get("author_tokens_excl_cache"),
    "author_raw": lambda r: r.get("author_tokens"),
    "author_tool_steps": lambda r: r.get("author_tool_steps_total"),
}


def rejection_stop(record: dict) -> bool:
    """A protocol stop by the rejection cap (not an accepted arm whose oracle failed)."""
    return not record["accepted"] and stop_kind_of(record) == "protocol"


def tuning_pair(case_id: str, repeat: int, base: dict | None, tuned: dict | None,
                metrics: dict = TUNING_METRICS) -> dict:
    """One (case, repeat) pair; the seed comparison is #310's, baseline in the per-task
    seat and tuned in the grouped seat."""
    p310 = pair_summary(case_id, repeat, base, tuned)
    pair = {k: p310[k] for k in ("case_id", "repeat", "attempt", "harness_censored",
                                 "complete")}
    pair["arms_present"] = sorted(r["variant"] for r in (base, tuned) if r)
    for name, read in metrics.items():
        pair[f"{name}_saving"] = saving(read(base), read(tuned)) if pair["complete"] else None
    if pair["complete"]:
        s = p310["seeds"]
        pair["seeds"] = {
            "compared_units": s["compared_units"],
            "excluded_unavailable": s["excluded_unavailable"],
            "excluded_removed_before_review": s["excluded_removed_before_review"],
            "baseline_caught": s["per_task_caught"],
            "tuned_caught": s["grouped_caught"],
            "tuned_missed_caught_by_baseline": s["grouped_missed_caught_by_per_task"],
        }
        pair["extra_protocol_stop"] = rejection_stop(tuned) and not rejection_stop(base)
    else:
        pair["seeds"] = None
        pair["extra_protocol_stop"] = None
    return pair


def tuning_cohort(records: list[dict], metrics: dict = TUNING_METRICS,
                  counts: tuple = TUNING_COUNTS) -> dict:
    quality = [r["quality"] for r in records]
    return {
        "sample_size": len(records),
        "accepted": sum(r["accepted"] for r in records),
        "harness_censored": sum(stop_kind_of(r) == "harness" for r in records),
        "rejection_cap_stops": sum(rejection_stop(r) for r in records),
        "quality_failures": sum(q.get("quality_failure") is True for q in quality),
        **{name: distribution([read(r) for r in records])
           for name, read in metrics.items()},
        "by_kind_uncached_plus_output": {
            kind: distribution([(r.get("kind_tokens_excl_cache") or {}).get(kind)
                                for r in records])
            for kind in ("author", "repair", "integration", "reviewer")
        },
        "elapsed_to_accepted_ms": distribution([r.get("elapsed_to_accepted_ms")
                                                for r in records]),
        **{key: sum((r.get("tuning") or {}).get(key, 0) for r in records)
           for key in counts},
        "false_findings": sum(q.get("false_findings", 0) for q in quality),
        "seeded_caught": sum(q.get("seeded_caught", 0) for q in quality),
        "seeded_missed": sum(q.get("seeded_missed", 0) for q in quality),
    }


def tuning_verdict(base: list[dict], tuned: list[dict], pairs: list[dict]) -> dict:
    """The frozen gates for one mode. Any gate false: fail (a censored or missing pair
    cannot rescue it). Else a pair still censored after the one rerun, a missing arm or an
    unknown gate or saving: inconclusive. Else better when the median paired saving on
    uncached + output is above 0."""
    complete = [p for p in pairs if p["complete"]]
    keys = {(p["case_id"], p["repeat"]) for p in complete}
    base = [r for r in base if (r["case_id"], r["repeat"]) in keys]
    tuned = [r for r in tuned if (r["case_id"], r["repeat"]) in keys]
    whole = len(complete) == len(pairs)
    gates: dict[str, bool | None] = {}

    def paired(bad: bool) -> bool | None:
        if not complete:
            return None
        return False if bad else (True if whole else None)

    gates["no_seed_missed_that_baseline_caught"] = paired(
        any(p["seeds"]["tuned_missed_caught_by_baseline"] for p in complete))
    if any(r["quality"].get("quality_failure") is True for r in tuned):
        gates["no_quality_failure"] = False
    elif not tuned or any(r["accepted"] and r["quality"].get("quality_failure") is None
                          for r in tuned):
        gates["no_quality_failure"] = None
    else:
        gates["no_quality_failure"] = True if whole else None
    gates["no_extra_protocol_stop"] = paired(any(p["extra_protocol_stop"] for p in complete))
    if complete:
        more = (sum(r["quality"].get("false_findings", 0) for r in tuned)
                > sum(r["quality"].get("false_findings", 0) for r in base))
        gates["false_findings_not_more"] = paired(more)
    else:
        gates["false_findings_not_more"] = None
    base_lat = [r["elapsed_to_accepted_ms"] for r in base if r["accepted"]]
    tuned_lat = [r["elapsed_to_accepted_ms"] for r in tuned if r["accepted"]]
    if not base_lat or not tuned_lat:
        gates["median_accepted_latency_not_higher"] = None
    else:
        gates["median_accepted_latency_not_higher"] = paired(
            statistics.median(tuned_lat) > statistics.median(base_lat))
    savings = [p["uncached_plus_output_saving"] for p in complete]
    median_saving = (None if not savings or None in savings else statistics.median(savings))
    censored = [f"{p['case_id']}#r{p['repeat']}" for p in pairs if p["harness_censored"]]
    missing = [f"{p['case_id']}#r{p['repeat']}" for p in pairs
               if not p["complete"] and not p["harness_censored"]]
    values = list(gates.values())
    if False in values:
        result = "fail"
    elif censored or missing or None in values or median_saving is None:
        result = "inconclusive"
    elif median_saving > 0:
        result = "better"
    else:
        # Every gate holds but nothing was saved: the design names no verdict for it.
        result = "not-better"
    return {"gates": gates, "median_saving_uncached_plus_output": median_saving,
            "result": result, "harness_censored_pairs": censored,
            "incomplete_pairs": missing}


TUNING_SPEC = {
    "comparison": "tuning", "variants": TUNING_VARIANTS, "design": TUNING_DESIGN,
    "limits": TUNING_LIMITS, "jobs": TUNING_JOBS, "metrics": TUNING_METRICS,
    "counts": TUNING_COUNTS, "smoke_spend_counts": False,
}
RR_SPEC = {
    "comparison": "rr", "variants": RR_VARIANTS, "design": RR_DESIGN,
    "limits": RR_LIMITS, "jobs": RR_JOBS, "metrics": RR_METRICS,
    "counts": RR_COUNTS, "smoke_spend_counts": True,
}
BATCH_SPEC = {
    "comparison": "batch", "variants": BATCH_VARIANTS, "design": BATCH_DESIGN,
    "limits": BATCH_LIMITS, "jobs": BATCH_JOBS, "metrics": BATCH_METRICS,
    "counts": RR_COUNTS, "smoke_spend_counts": True, "cap_margin": BATCH_CAP_MARGIN,
}


def summarize_tuning(records: list[dict], budget_tokens: int | None = None) -> dict:
    """The tuning comparison recomputed from runs.jsonl: baseline-grouped vs tuned-grouped
    per mode, paired by (case, repeat), with the #310 rerun rule (final attempt only;
    voided attempts kept with their spend) and smoke kept apart."""
    return summarize_pairs(records, TUNING_SPEC, budget_tokens)


def summarize_rr(records: list[dict], budget_tokens: int | None = None) -> dict:
    """The RR comparison (repair-tuned vs repair-tuned-rr), by the tuning machinery: the
    same gates, verdicts and rerun rule. Its smoke projection is the larger smoke job x 8,
    and that projection plus the smoke's own spend must fit the budget (RR_DESIGN)."""
    return summarize_pairs(records, RR_SPEC, budget_tokens)


def summarize_batch(records: list[dict], budget_tokens: int | None = None) -> dict:
    """The AB comparison (rr-base vs rr-batched), by the tuning machinery: the same gates,
    verdicts, rerun rule and smoke projection (larger smoke job x 8, plus the smoke's own
    spend, must fit the budget; BATCH_DESIGN), with author-only cost and author tool
    steps among the reported metrics."""
    return summarize_pairs(records, BATCH_SPEC, budget_tokens)


def summarize_pairs(records: list[dict], spec: dict, budget_tokens: int | None = None) -> dict:
    names, jobs = spec["variants"], spec["jobs"]
    records = [r for r in records if r.get("variant") in names]
    matched, voided = final_attempts([r for r in records if not r.get("smoke")])
    smoke, smoke_voided = final_attempts([r for r in records if r.get("smoke")])
    pairs = []
    for case_id, repeat in sorted({(r["case_id"], r["repeat"]) for r in matched}):
        arms = {r["variant"]: r for r in matched
                if r["case_id"] == case_id and r["repeat"] == repeat}
        pairs.append(tuning_pair(case_id, repeat, arms.get(names[0]), arms.get(names[1]),
                                 spec["metrics"]))
    modes = {}
    for case_id in sorted({r["case_id"] for r in matched}):
        base = [r for r in matched if r["case_id"] == case_id and r["variant"] == names[0]]
        tuned = [r for r in matched if r["case_id"] == case_id and r["variant"] == names[1]]
        mine = [p for p in pairs if p["case_id"] == case_id]
        modes[case_id] = {
            names[0]: tuning_cohort(base, spec["metrics"], spec["counts"]),
            names[1]: tuning_cohort(tuned, spec["metrics"], spec["counts"]),
            "pairs": len(mine),
            **{f"{name}_saving": distribution([p[f"{name}_saving"] for p in mine])
               for name in spec["metrics"]},
            "verdict": tuning_verdict(base, tuned, mine),
        }
    void = voided + smoke_voided
    void_tokens = [r.get("total_tokens") for r in void]
    summary = {
        "comparison": spec["comparison"],
        "design": spec["design"],
        "cost_metric": "uncached input + output (maintainer ruling 2026-11-13); raw totals "
                       "including cache reads reported alongside",
        "limitations": spec["limits"],
        "run_count": len(matched),
        "pairs": pairs,
        "modes": modes,
        "verdicts": {m: v["verdict"]["result"] for m, v in modes.items()},
        "counts": {variant: {key: sum((r.get("tuning") or {}).get(key, 0) for r in matched
                                      if r["variant"] == variant) for key in spec["counts"]}
                   for variant in names},
        "voided_attempts": {
            "label": "harness-censored attempts, rerun once; kept with their spend",
            "records": [{"job_id": r["job_id"], "attempt": r.get("attempt", 0),
                         "stop_kind": stop_kind_of(r), "stop_reason": r.get("stop_reason"),
                         "total_tokens": r.get("total_tokens")} for r in void],
            "total_tokens": None if None in void_tokens else sum(void_tokens),
        },
        "cache_write": {
            "nonzero": any((r.get("cache_write") or {}).get("calls") for r in records),
            "jobs": sorted({f"{r['job_id']}/{c}" for r in records
                            for c in (r.get("cache_write") or {}).get("calls", [])}),
        },
    }
    if smoke:
        totals = [r.get("total_tokens") for r in smoke]
        pair_total = None if None in totals else sum(totals)
        censored = sum(stop_kind_of(r) == "harness" for r in smoke)
        whole = sorted(r["variant"] for r in smoke) == sorted(names) and not censored
        # Pessimistic: every job is projected at the larger smoke job (mixed-fork-join is
        # the only mode the smoke runs); the mean projection is reported beside it.
        projected = (max(totals) * jobs
                     if whole and pair_total is not None else None)
        mean_projected = (pair_total / len(smoke) * jobs
                          if whole and pair_total is not None else None)
        summary["smoke"] = {
            "label": "smoke data; not merged into the matched sample",
            "jobs": len(smoke),
            "harness_censored": censored,
            "projection_basis": "both smoke variants ran and neither was harness-censored"
            if whole else "none: the smoke pair is incomplete or harness-censored",
            "tokens_measured": pair_total,
            f"projected_tokens_for_{jobs}_jobs": projected,
            "projection_rule": "largest smoke job x jobs (pessimistic)",
            f"mean_projected_tokens_for_{jobs}_jobs": mean_projected,
            "budget_tokens": budget_tokens,
            "fits_budget": (None if projected is None or budget_tokens is None
                            else projected <= budget_tokens),
            "records": [{"job_id": r["job_id"], "status": r["status"],
                         "stop_kind": stop_kind_of(r), "total_tokens": r.get("total_tokens"),
                         "total_tokens_excl_cache": r.get("total_tokens_excl_cache")}
                        for r in smoke],
        }
        if spec["smoke_spend_counts"]:
            # RR_DESIGN: the projection plus the smoke's own spend must fit the budget; the
            # run's cap is what remains after the smoke, less a margin.
            smoke_summary = summary["smoke"]
            margin = spec.get("cap_margin", RR_CAP_MARGIN)
            smoke_summary["projection_rule"] = (
                f"largest smoke job x {jobs} (pessimistic); with the smoke's own spend it "
                "must fit the budget")
            smoke_summary["projected_plus_smoke_tokens"] = (
                None if projected is None else projected + pair_total)
            smoke_summary["fits_budget"] = (
                None if projected is None or budget_tokens is None
                else projected + pair_total <= budget_tokens)
            smoke_summary["run_cap_after_smoke"] = (
                None if pair_total is None or budget_tokens is None
                else budget_tokens - pair_total - margin)
            smoke_summary["run_cap_margin"] = margin
    return summary


def summarize(records: list[dict], budget_tokens: int | None = None) -> dict:
    """The summary a runs.jsonl recomputes to: tuning or RR when its records are those
    comparison's variants, else #310's."""
    if any(r.get("variant") in BATCH_VARIANTS for r in records):
        return summarize_batch(records, budget_tokens)
    if any(r.get("variant") in RR_VARIANTS for r in records):
        return summarize_rr(records, budget_tokens)
    if any(r.get("variant") in TUNING_VARIANTS for r in records):
        return summarize_tuning(records, budget_tokens)
    return summarize_live(records)


# --- the run --------------------------------------------------------------------------


def schedule(cases: list[dict], repeats: int, smoke: bool,
             comparison: str = "310") -> list[tuple[dict, int, str, int]]:
    """Jobs one at a time; arm order counterbalanced by repeat (even: the comparison's
    first arm first: per-task in #310, baseline-grouped in the tuning comparison)."""
    names = COMPARISONS[comparison]
    if smoke:
        cases = [c for c in cases if c["id"] == SMOKE_CASE]
        repeats = 1
    jobs = []
    for case in cases:
        for repeat in range(repeats):
            arms = names if repeat % 2 == 0 else tuple(reversed(names))
            for order, arm in enumerate(arms):
                jobs.append((case, repeat, arm, order))
    return jobs


@contextlib.contextmanager
def isolated_codex_home(auth_source: Path, out: Path):
    """Run Codex under a temporary CODEX_HOME holding only a symlink to the real auth file.

    User ruling 2026-11-13 (#310): `--ignore-user-config` still loads the user's
    ~/.codex/skills and app connectors, and no feature flag stops it (measured), so an
    author read a personal SKILL.md and the access audit censored the arm. The link is
    never a copy and nothing under the real home is written. On exit the environment is
    restored, the session rollouts are copied into ``out/codex-sessions`` (the link is
    not), and the temporary home is removed; removing a symlink never touches its target.
    """
    auth_source = Path(auth_source).expanduser()
    if not auth_source.is_file():
        raise ValueError(f"no Codex auth file at {auth_source}; log in to Codex first")
    previous = os.environ.get("CODEX_HOME")
    home = Path(tempfile.mkdtemp(prefix="codex-home-")).resolve()
    try:
        (home / "auth.json").symlink_to(auth_source.resolve())
        os.environ["CODEX_HOME"] = str(home)
        yield home
    finally:
        if previous is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = previous
        sessions = home / "sessions"
        if sessions.is_dir():
            shutil.copytree(sessions, Path(out) / "codex-sessions", symlinks=True,
                            dirs_exist_ok=True)
        shutil.rmtree(home, ignore_errors=True)


def codex_environment(codex_bin: list[str], cwd: Path) -> dict:
    """What both arms run under, read-only: CLI version, effective features, the
    CODEX_HOME path and a digest of its skills directory. Nothing under CODEX_HOME is
    copied, moved or written; credentials are never read."""

    def probe(args: list[str]) -> str:
        try:
            done = run_eval.run_contained([*codex_bin, *args], "", str(cwd), 30)
            return (done.stdout or done.stderr).strip() or f"exit {done.returncode}"
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"unknown: {exc}"

    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    skills = home / "skills"
    try:
        digest = tree_digest(skills) if skills.is_dir() else None
    except OSError as exc:
        digest = f"unreadable: {exc}"
    # `codex features list` has no --ignore-user-config (codex-cli 0.167.1), so it cannot
    # reproduce the runs' config exactly: it is probed with each arm role's --disable flags
    # and labelled as such (QW round 2, finding 8).
    author_probe = ["features", "list", "--disable", "apps", "--disable", "multi_agent"]
    review_probe = [*author_probe, "--disable", "shell_tool", "--disable", "unified_exec"]
    env = {
        "codex_cli_version": probe(["--version"]),
        "features": {
            "label": "effective features as `codex features list` reports them WITH the "
            "user's config.toml applied (the subcommand has no --ignore-user-config) and each "
            "role's --disable flags; every exec run also passes --ignore-user-config, so the "
            "runs may differ from this listing wherever config.toml sets a feature",
            "author": {"argv": author_probe, "output": probe(author_probe)},
            "review": {"argv": review_probe, "output": probe(review_probe)},
        },
        "codex_home": str(home),
        "skills_dir": str(skills),
        "skills_digest": digest,
    }
    env["sha256"] = sha256_text(json.dumps(env, sort_keys=True))
    return env


def metadata(out: Path, cases: list[dict], repeats: int, smoke: bool, codex_bin: list[str],
             author_timeout: float, review_timeout: float, env: dict,
             comparison: str = "310", budget_tokens: int | None = None) -> dict:
    meta = _metadata(out, cases, repeats, smoke, codex_bin, author_timeout, review_timeout,
                     env)
    # Keys added only off the #310 default, so its metadata stays as it was.
    if comparison != "310":
        meta.update(
            comparison=comparison,
            design={"rr": RR_DESIGN, "batch": BATCH_DESIGN}.get(comparison, TUNING_DESIGN),
            variants={v: {"arm": VARIANTS[v]["arm"], "levers": list(VARIANTS[v]["levers"])}
                      for v in COMPARISONS[comparison]},
            tuning_prompts=TUNING_PROMPTS,
            tuning_limitations=TUNING_LIMITS,
        )
        if comparison in ("rr", "batch"):
            meta.update(rr_prompts=RR_PROMPTS, rr_limitations=RR_LIMITS,
                        rr_max_resumes_per_thread=MAX_RESUMES)
        if comparison == "batch":
            meta.update(batch_prompts=BATCH_PROMPTS, batch_limitations=BATCH_LIMITS)
    if budget_tokens is not None:
        meta["budget_tokens"] = budget_tokens
    return meta


def _metadata(out: Path, cases: list[dict], repeats: int, smoke: bool, codex_bin: list[str],
              author_timeout: float, review_timeout: float, env: dict) -> dict:
    harness = {
        name: sha256_text((HERE / f"{name}.py").read_text(encoding="utf-8"))
        for name in ("live_run", "live_cases", "run_eval", "codex_adapter")
    }
    return {
        "started_at": now(),
        "run": "smoke" if smoke else "full",
        "repeats": 1 if smoke else repeats,
        "codex_command": codex_bin,
        "codex_cli_version": env["codex_cli_version"],
        "codex_environment": env,
        "model": MODEL,
        "author_settings": AUTHOR_SETTINGS,
        "review_settings": REVIEW_SETTINGS,
        "timeouts": {"author": author_timeout, "review": review_timeout},
        "max_repair_rounds": MAX_REPAIR_ROUNDS,
        "rerun_rule": "a harness censor voids the pair; rerun once in the same order; "
        "censored twice is inconclusive" + ("; smoke: no rerun" if smoke else ""),
        "host": platform.platform(),
        "python": platform.python_version(),
        "shiftwork_runtime": str(ROOT / "runtime-ts/dist/cli.js"),
        "harness_sha256": harness,
        "fixture_digests": {
            c["id"]: {part: tree_digest(Path(c[f"{part}_dir"])) for part in
                      ("base", "oracle", "reference")}
            for c in cases
        },
        "cases": [
            {"id": c["id"], "mode": c["mode"], "units": c["units"],
             "plans": {arm: arm_tickets(c, arm) for arm in ARMS}}
            for c in cases
        ],
        "prompts": PROMPTS,
        "response_schema": codex_adapter.response_schema(),
        "planner_dispatch": PLANNER_DISPATCH,
        "human_interventions": HUMAN_INTERVENTIONS_LABEL,
        "limitations": LIMITS,
    }


def crashed_record(arm: Arm, exc: BaseException) -> dict:
    """The record of an arm whose own bookkeeping failed: a harness censor, spend unknown."""
    arm.cleanup()
    return {
        "case_id": arm.case["id"], "mode": arm.case["mode"], "repeat": arm.repeat,
        "attempt": arm.attempt, "arm": arm.arm, "variant": arm.variant,
        "levers": sorted(arm.levers), "order": arm.order, "smoke": arm.smoke,
        "job_id": arm.job_id, "accepted": False, "status": "failed/censored",
        "stop_kind": "harness", "stop_reason": f"arm crashed: {type(exc).__name__}: {exc}",
        "harness_errors": [{"where": "arm", "type": type(exc).__name__, "error": str(exc),
                            "traceback": traceback.format_exc()[-4000:]}],
        "elapsed_to_accepted_ms": None, "elapsed_to_stop_ms": None,
        "review_tokens": None, "total_tokens": None, "review_tokens_excl_cache": None,
        "total_tokens_excl_cache": None, "calls": arm.calls,
        "rework": {"rounds": 0, "units": []}, "escalations": arm.escalations,
        "human_interventions": 0, "human_interventions_label": HUMAN_INTERVENTIONS_LABEL,
        "quality": {"seeds": [], "quality_failure": None, "author_defects_missed": []},
        "observations": {"holds": None},
    }


def pairs_of(jobs: list) -> list[list]:
    grouped: dict[tuple, list] = {}
    for job in jobs:
        grouped.setdefault((job[0]["id"], job[1]), []).append(job)
    return list(grouped.values())


def record_spend(record: dict) -> tuple[int, int]:
    """(raw tokens a job spent, calls whose spend is unknown) from its calls."""
    spent, unknown = 0, 0
    for call in record.get("calls") or []:
        value = call_spend(call)
        if value is None:
            unknown += 1
        else:
            spent += value
    return spent, unknown


class Budget:
    """The run's token cap (raw tokens incl. cache reads, this run only), checked before
    each job: the next job is projected at the largest job spend seen so far in the run,
    and the run stops cleanly when spend + projection would cross the cap, or when a call's
    spend could not be measured at all (the cap could no longer be kept)."""

    def __init__(self, cap: int):
        self.cap = cap
        self.spent = 0
        self.largest = 0
        self.jobs = 0
        self.unknown_calls = 0
        self.stopped: dict | None = None

    def allows(self, job_id: str) -> bool:
        if self.stopped is not None:
            return False
        if self.unknown_calls:
            self.stopped = {"before_job": job_id, "reason": "a call's spend is unknown, so the "
                            "cap can no longer be kept"}
        elif self.spent + self.largest > self.cap:
            self.stopped = {"before_job": job_id, "reason": (
                f"spent {self.spent} + projected next job {self.largest} > cap {self.cap}")}
        return self.stopped is None

    def add(self, record: dict) -> None:
        spent, unknown = record_spend(record)
        self.spent += spent
        self.largest = max(self.largest, spent)
        self.unknown_calls += unknown
        self.jobs += 1

    def state(self) -> dict:
        return {"label": "raw Codex tokens incl. cache reads spent by this run; the next job "
                         "is projected at the largest job so far",
                "cap": self.cap, "spent": self.spent, "jobs_run": self.jobs,
                "largest_job": self.largest, "unknown_spend_calls": self.unknown_calls,
                "stopped": self.stopped is not None, "stop": self.stopped}


async def _run(out: Path, cases: list[dict], repeats: int, smoke: bool, codex_bin: list[str],
               author_timeout: float, review_timeout: float, env_sha: str,
               comparison: str = "310", budget: Budget | None = None) -> list[dict]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    host = Host(out, codex_bin, author_timeout, review_timeout)
    host.codex_env_sha = env_sha
    host.response_schema.write_text(json.dumps(codex_adapter.response_schema()), encoding="utf-8")
    params = StdioServerParameters(
        command="node", args=[str(ROOT / "runtime-ts/dist/cli.js")], cwd=str(ROOT)
    )
    records = []
    async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        host.client = client
        with (out / "runs.jsonl").open("a", encoding="utf-8") as stream:
            for pair in pairs_of(schedule(cases, repeats, smoke, comparison)):
                # Rerun rule: a harness censor voids the pair; one rerun, same arm order.
                for attempt in range(1 if smoke else 2):
                    censored = False
                    for case, repeat, arm_name, order in pair:
                        arm = Arm(host, case, arm_name, repeat, order, smoke, attempt)
                        if budget is not None and not budget.allows(arm.job_id):
                            return records
                        try:
                            record = await arm.run()
                        except Exception as exc:  # noqa: BLE001 - never abort the run
                            record = crashed_record(arm, exc)
                        records.append(record)
                        if budget is not None:
                            budget.add(record)
                        stream.write(json.dumps(record) + "\n")
                        stream.flush()
                        if record["stop_kind"] == "harness":
                            # The pair is void either way; its other arm would be spend
                            # with no use.
                            censored = True
                            break
                    if not censored:
                        break
    return records


def run_live(out, cases: list[dict] | None = None, repeats: int | None = None,
             smoke: bool = False, codex_bin: list[str] | None = None,
             author_timeout: float = 900, review_timeout: float = 300,
             codex_auth: Path | None = None, comparison: str = "310",
             budget_tokens: int | None = None) -> dict:
    """With ``codex_auth`` (the CLI passes ~/.codex/auth.json), every Codex call runs under
    an isolated CODEX_HOME linking only that file; see isolated_codex_home.

    ``comparison="tuning"`` pairs baseline-grouped vs tuned-grouped (TUNING_DESIGN);
    ``"rr"`` pairs repair-tuned vs repair-tuned-rr (RR_DESIGN), by default over
    native-chain and sequential-delegates. ``repeats`` defaults to 3 for #310 and 2 for
    tuning and rr. ``budget_tokens`` caps this run's
    raw spend (see Budget); the summary is written either way."""
    if comparison not in COMPARISONS:
        raise ValueError(f"unknown comparison {comparison}; one of {', '.join(COMPARISONS)}")
    if budget_tokens is not None and (type(budget_tokens) is not int or budget_tokens < 1):
        raise ValueError("budget_tokens must be a positive integer")
    if comparison in ("tuning", "rr", "batch") and not smoke and budget_tokens is None:
        raise ValueError(f"a {comparison} run needs budget_tokens (the design's budget stop)")
    if repeats is None:
        repeats = (RR_REPEATS if comparison == "rr" else BATCH_REPEATS if comparison == "batch"
                   else DEFAULT_REPEATS[comparison])
    run = {"comparison": comparison, "budget_tokens": budget_tokens}
    if codex_auth is None:
        return _run_live(out, cases, repeats, smoke, codex_bin, author_timeout,
                         review_timeout, None, **run)
    out_path = Path(out).resolve()
    # Sessions are copied into the run's own output after it ends; a refused run has
    # made no Codex call, so it leaves no sessions to copy.
    if os.name != "posix":
        raise ValueError("isolated Codex home needs /usr/bin/env (POSIX); pass "
                         "codex_auth=None to use the shared home")
    with isolated_codex_home(codex_auth, out_path) as home:
        # Codex also reads ~/.agents/skills through HOME (measured 2026-11-13), so only
        # the Codex processes see HOME = the isolated home; the harness and its MCP
        # server keep the real HOME.
        isolated_bin = ["/usr/bin/env", f"HOME={home}", f"CODEX_HOME={home}",
                        *(codex_bin or ["codex"])]
        return _run_live(out, cases, repeats, smoke, isolated_bin, author_timeout,
                         review_timeout, home, **run)


def _run_live(out, cases, repeats, smoke, codex_bin, author_timeout, review_timeout,
              isolated_home: Path | None, comparison: str = "310",
              budget_tokens: int | None = None) -> dict:
    if type(repeats) is not int or repeats < 1 or author_timeout <= 0 or review_timeout <= 0:
        raise ValueError("repeats and timeouts must be positive")
    codex_bin = list(codex_bin or ["codex"])
    if not codex_bin or any(not isinstance(x, str) or not x for x in codex_bin):
        raise ValueError("codex_bin must be a nonempty argv prefix")
    out = Path(out).resolve()
    if _inside(out, _roots(ROOT)):
        raise ValueError(f"output directory {out} is inside the repository; run output "
                         "lives outside it and only the publish step copies records in")
    scratch_root = Path(tempfile.gettempdir()).resolve()
    if _inside(scratch_root, _roots(ROOT)) or _inside(scratch_root, [out]):
        raise ValueError(f"temporary directory {scratch_root} is inside the repository or "
                         "the output directory; arm workspaces would be reachable")
    out.mkdir(parents=True, exist_ok=False)
    if cases is None:
        cases = live_cases.live_cases()
        if comparison in ("rr", "batch") and not smoke:
            cases = [c for c in cases if c["id"] in RR_CASES]
    else:
        cases = copy.deepcopy(cases)
    env = codex_environment(codex_bin, out)
    env["codex_home_isolated"] = (
        {"isolated": True, "contents": "auth.json symlink only (user ruling 2026-11-13)",
         "sessions_copied_to": "codex-sessions"}
        if isolated_home is not None else {"isolated": False}
    )
    env["sha256"] = sha256_text(json.dumps({k: v for k, v in env.items() if k != "sha256"},
                                           sort_keys=True))
    meta = metadata(out, cases, repeats, smoke, codex_bin, author_timeout, review_timeout, env,
                    comparison, budget_tokens)
    (out / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    budget = Budget(budget_tokens) if budget_tokens is not None else None
    try:
        asyncio.run(
            _run(out, cases, repeats, smoke, codex_bin, author_timeout, review_timeout,
                 env["sha256"], comparison, budget)
        )
    finally:
        # Whatever happened, the summary is what runs.jsonl recomputes to.
        runs = out / "runs.jsonl"
        records = read_runs(out) if runs.exists() else []
        summary = (summarize_tuning(records, budget_tokens) if comparison == "tuning"
                   else summarize_rr(records, budget_tokens) if comparison == "rr"
                   else summarize_batch(records, budget_tokens) if comparison == "batch"
                   else summarize_live(records))
        if budget is not None:
            # The watcher's own state is not in runs.jsonl: written beside it.
            summary["budget"] = budget.state()
            (out / "budget.json").write_text(json.dumps(summary["budget"], indent=2) + "\n",
                                             encoding="utf-8")
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n",
                                          encoding="utf-8")
    return summary


def read_runs(path: Path) -> list[dict]:
    source = path / "runs.jsonl" if path.is_dir() else path
    return [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="new output directory (must not exist)")
    parser.add_argument("--repeats", type=int, default=None,
                        help="repeats per case (default: 3 for 310, 2 for tuning)")
    parser.add_argument("--smoke", action="store_true",
                        help="mixed-fork-join repeat 0, both arms, plus a full-run projection "
                        "(18 jobs for 310, 12 for tuning, 8 for rr)")
    parser.add_argument("--comparison", choices=sorted(COMPARISONS), default="310",
                        help="310: per-task vs grouped (default); tuning: baseline-grouped vs "
                        "tuned-grouped (T1-T4); rr: repair-tuned vs repair-tuned-rr "
                        "(reviewer thread resume); batch: rr-base vs rr-batched (batched "
                        "author prompt)")
    parser.add_argument("--budget-tokens", type=int, default=None,
                        help="cap on this run's raw Codex tokens; checked before each job, "
                        "the run stops cleanly when the next job would cross it")
    parser.add_argument("--cases", nargs="*",
                        help="case ids (default: all three; rr: native-chain and "
                        "sequential-delegates, or mixed-fork-join with --smoke)")
    parser.add_argument("--codex", default='["codex"]', help="JSON argv prefix for Codex")
    parser.add_argument("--author-timeout", type=float, default=900)
    parser.add_argument("--review-timeout", type=float, default=300)
    parser.add_argument("--shared-codex-home", action="store_true",
                        help="use the real CODEX_HOME (loads personal skills); default "
                        "isolates it with an auth.json symlink")
    parser.add_argument("--summarize", type=Path,
                        help="existing runs.jsonl or output directory; print recomputed summary")
    args = parser.parse_args()
    if args.summarize:
        print(json.dumps(summarize(read_runs(args.summarize), args.budget_tokens), indent=2))
        return
    if not args.out:
        parser.error("--out is required unless --summarize is given")
    cases = live_cases.live_cases()
    if args.comparison in ("rr", "batch") and not args.cases and not args.smoke:
        cases = [c for c in cases if c["id"] in RR_CASES]
    if args.cases:
        unknown = set(args.cases) - {c["id"] for c in cases}
        if unknown:
            parser.error(f"unknown cases: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in args.cases]
    auth = None if args.shared_codex_home else Path.home() / ".codex" / "auth.json"
    summary = run_live(args.out, cases, args.repeats, args.smoke, json.loads(args.codex),
                       args.author_timeout, args.review_timeout, codex_auth=auth,
                       comparison=args.comparison, budget_tokens=args.budget_tokens)
    print(json.dumps(summary, indent=2))
    if args.smoke and args.comparison in ("tuning", "rr", "batch"):
        smoke = summary.get("smoke", {})
        jobs = (RR_JOBS if args.comparison == "rr" else BATCH_JOBS if args.comparison == "batch"
                else TUNING_JOBS)
        print(
            f"projection: {smoke.get(f'projected_tokens_for_{jobs}_jobs')} tokens for "
            f"{jobs} jobs (budget {args.budget_tokens}; fits: "
            f"{smoke.get('fits_budget')})",
            file=sys.stderr,
        )
    elif args.smoke:
        smoke = summary.get("smoke", {})
        print(
            f"projection: {smoke.get('projected_tokens_for_18_jobs')} tokens for "
            f"{FULL_RUN_JOBS} jobs (gate {BUDGET_GATE_TOKENS}; exceeds: "
            f"{smoke.get('exceeds_gate')})",
            file=sys.stderr,
        )
    if summary.get("budget", {}).get("stopped"):
        print(f"budget stop: {summary['budget']['stop']['reason']}", file=sys.stderr)


if __name__ == "__main__":
    main()
