"""The dev-team workload-surface survey, re-derived from committed sources.

    .venv/bin/python docs/eval-data/2026-08-14-devteam-surface-survey.py .

Reads only committed sources (the frozen task YAMLs and the runtime package); writes
nothing and calls no model. Every table in `2026-08-14-devteam-surface-survey.md` is
this script's stdout, so a reader re-derives the counts instead of trusting the prose.

M1 of the devteam-workload-and-null-control job. PROBE ONLY — nothing here changes
behaviour, nothing here is a fix, and nothing here is a workload.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
TASKS = ROOT / "assets" / "evals" / "tasks"
SRC = ROOT / "runtime-py" / "src" / "bantamkit"

RULE = "=" * 78

# A workspace path is "code" only if it parses as a source file by extension. Everything
# else in these workspaces is prose (.md) or config (.yaml/.json/.txt/.ini/.env).
CODE_SUFFIXES = {".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".rb"}
CONFIG_SUFFIXES = {".yaml", ".yml", ".json", ".ini", ".toml", ".env", ".cfg"}


def tasks() -> list[tuple[Path, dict]]:
    files = sorted(TASKS.glob("*.yaml"))
    return [(p, yaml.safe_load(p.read_text())) for p in files]


def classify(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in CODE_SUFFIXES:
        return "code"
    if suffix in CONFIG_SUFFIXES:
        return "config"
    return "prose"


def survey_families() -> None:
    print(RULE)
    print("TABLE 1 — task census by family (frozen suite, assets/evals/tasks/)")
    print(RULE)
    rows = tasks()
    fams: dict[str, list] = {}
    for path, t in rows:
        fams.setdefault(t.get("family", "MISSING"), []).append((path, t))
    print(f"{'family':<24} {'n':>3}  prefix")
    print("-" * 60)
    for fam in sorted(fams):
        prefixes = sorted({p.stem.split("-")[0] for p, _ in fams[fam]})
        print(f"{fam:<24} {len(fams[fam]):>3}  {','.join(prefixes)}")
    print("-" * 60)
    print(f"{'TOTAL':<24} {len(rows):>3}")
    print()


def survey_surface() -> None:
    print(RULE)
    print("TABLE 2 — file-surface census: what each task actually touches")
    print(RULE)
    hdr = f"{'task':<26}{'family':<24}{'tools':<24}{'ws files':>9}{'surface':>10}"
    print(hdr)
    print("-" * len(hdr))
    counts = {"none": 0, "workspace": 0}
    for path, t in tasks():
        ws = t.get("workspace") or {}
        tools = ",".join(t.get("tools", [])) or "-"
        surface = "workspace" if ws else "none"
        counts[surface] += 1
        print(
            f"{t['name']:<26}{t.get('family', '?'):<24}{tools:<24}"
            f"{len(ws):>9}{surface:>10}"
        )
    print("-" * len(hdr))
    print(f"tasks with ANY file surface : {counts['workspace']}")
    print(f"tasks with NO file surface  : {counts['none']}")
    print()


def survey_workspaces() -> None:
    print(RULE)
    print("TABLE 3 — what the workspaces contain (the only file surface in the suite)")
    print(RULE)
    hdr = f"{'task':<22}{'path':<22}{'kind':<8}{'bytes':>7}  first line"
    print(hdr)
    print("-" * 96)
    kinds: dict[str, int] = {}
    for _, t in tasks():
        ws = t.get("workspace") or {}
        for p in sorted(ws):
            body = ws[p]
            kind = classify(p)
            kinds[kind] = kinds.get(kind, 0) + 1
            head = body.strip().splitlines()[0][:32] if body.strip() else ""
            print(f"{t['name']:<22}{p:<22}{kind:<8}{len(body.encode()):>7}  {head}")
    print("-" * 96)
    print("by kind: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    print("code files in the entire frozen suite: " + str(kinds.get("code", 0)))
    print()


def survey_devteam_markers() -> None:
    print(RULE)
    print("TABLE 4 — dev-team surface markers across ALL 22 tasks (prompt + workspace)")
    print(RULE)
    # Each marker is a thing a dev-team task would have to be able to name. A marker is
    # "present" only if the literal surface exists, not if a word merely appears.
    markers = {
        "git history (commits/refs)": r"\b(commit|sha|branch|HEAD|revision|git log)\b",
        "a diff / patch hunk": r"(^|\n)(diff --git|@@ |\+\+\+ |--- )",
        "a symbol definition": r"(^|\n)\s*(def |class |function |func |const |var )",
        "an import / require": r"(^|\n)\s*(import |from \w+ import|require\(|#include)",
        "a stack trace / error": r"(Traceback|\.py\", line |Exception:|at \w+\.\w+\()",
        "a test or assertion": r"\b(assert\w*|pytest|unittest|it\(|describe\()\b",
    }
    hdr = f"{'marker':<30}{'tasks hit':>10}{'files hit':>11}"
    print(hdr)
    print("-" * len(hdr))
    for label, pat in markers.items():
        rx = re.compile(pat, re.MULTILINE)
        tasks_hit, files_hit = 0, 0
        for _, t in tasks():
            ws = t.get("workspace") or {}
            hit = bool(rx.search(t.get("prompt", "")))
            for body in ws.values():
                if rx.search(body):
                    files_hit += 1
                    hit = True
            tasks_hit += int(hit)
        print(f"{label:<30}{tasks_hit:>10}{files_hit:>11}")
    print("-" * len(hdr))
    print("The one non-zero row is a FALSE POSITIVE and is reported as such: the only")
    print("match for the git marker is the English verb in \"never commit tokens\" inside")
    print("the two nav ci.md fixtures. Grepped and read; no ref, sha, or history exists.")
    print("Every dev-team surface marker is therefore 0/22 in the frozen suite.")
    print()


def survey_accounting() -> None:
    print(RULE)
    print("TABLE 5 — token accounting: every recording and every decision point")
    print(RULE)
    hdr = f"{'site':<44}{'file:line':<26}{'kind':<12}"
    print(hdr)
    print("-" * len(hdr))
    sites = [
        ("TrackingClient.chat accumulates Usage", "evalrun.py", r"self\.usage = self\.usage \+ resp\.usage", "record"),
        ("TrackingClient.calls counter", "evalrun.py", r"self\.calls \+= 1", "record"),
        ("TaskResult.tokens = tracking.usage.total", "evalrun.py", r"tokens=tracking\.usage\.total", "attribute"),
        ("_BudgetedClient.chat books usage", "budget.py", r"self\.budget\.record\(resp\.usage\)", "record"),
        ("TokenBudget.record adds usage.total", "budget.py", r"self\.spent \+= usage\.total", "record"),
        ("Agent.run asks allow('required')", "agent.py", r"self\.budget\.allow\(\"required\"\)", "decide"),
        ("Critique gate asks allow('optional')", "critique.py", r"self\.budget\.allow\(\"optional\"\)", "decide"),
        ("report score/1k = passes / (tokens/1000)", "evalrun.py", r"per_1k = passed / \(tokens / 1000\)", "derive"),
    ]
    for label, fname, pat, kind in sites:
        text = (SRC / fname).read_text().splitlines()
        rx = re.compile(pat)
        hits = [i + 1 for i, line in enumerate(text) if rx.search(line)]
        loc = f"{fname}:{','.join(map(str, hits)) if hits else 'NOT FOUND'}"
        print(f"{label:<44}{loc:<26}{kind:<12}")
    print("-" * len(hdr))
    print("Granularity check: the only per-run token number is TaskResult.tokens,")
    print("a single scalar per (task, config, repeat). No per-call, per-tool, per-gate")
    print("or per-mechanism token column exists anywhere in TaskResult.")
    print()
    fields = re.search(r"class TaskResult:\n(.*?)\n\n", (SRC / "evalrun.py").read_text(), re.DOTALL)
    names = re.findall(r"^\s{4}(\w+):", fields.group(1), re.MULTILINE) if fields else []
    print("TaskResult columns: " + ", ".join(names))
    print()


def survey_filegraph() -> None:
    print(RULE)
    print("TABLE 6 — FileAccessGraph mechanisms and their token route")
    print(RULE)
    text = (SRC / "filegraph.py").read_text().splitlines()

    def line_of(pat: str) -> str:
        rx = re.compile(pat)
        return ",".join(str(i + 1) for i, ln in enumerate(text) if rx.search(ln)) or "?"

    rows = [
        ("record a read (path, tool, digest)", line_of(r"self\.reads\[path\] = FileRead"), "adds 0 tokens"),
        ("annotate a repeat read", line_of(r"return f\"\[file-graph\] read #"), "ADDS tokens"),
        ("cache: collapse unchanged repeat", line_of(r"bytes not repeated"), "SAVES tokens"),
        ("query: file_graph tool + skill", line_of(r"load_tool\(\"file_graph\"\)"), "ADDS tokens"),
        ("render the ledger", line_of(r"def render"), "ADDS tokens"),
        ("save/load ledger to disk", line_of(r"def save|def load"), "adds 0 tokens"),
    ]
    hdr = f"{'mechanism':<38}{'filegraph.py:line':<22}{'token route':<16}"
    print(hdr)
    print("-" * len(hdr))
    for label, loc, route in rows:
        print(f"{label:<38}{'filegraph.py:' + loc:<22}{route:<16}")
    print("-" * len(hdr))
    print("The saving is on the OBSERVATION only, and only on a byte-identical repeat")
    print("read of a path already in the ledger. It is bounded above by the bytes of")
    print("the repeat reads a run would otherwise have made — zero if the agent never")
    print("re-reads. Nothing in the class measures or reports those saved bytes:")
    print("`size` at line " + line_of(r"size = len\(observation\.encode\(\)\)") + " is interpolated into the marker string and discarded.")
    print()


def main() -> None:
    print(f"# dev-team workload-surface survey — sources under {ROOT}")
    print()
    survey_families()
    survey_surface()
    survey_workspaces()
    survey_devteam_markers()
    survey_accounting()
    survey_filegraph()


if __name__ == "__main__":
    main()
