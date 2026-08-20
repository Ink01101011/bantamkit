#!/usr/bin/env python3
"""J29: the question check had no floor, so a task could say nothing and ask anything (RB-P91).

BEFORE and AFTER, from one command, against the real harness.

The BEFORE is not a paraphrase of the pre-fix checker and is not a second transcription of the
rule (RB-P47). It is the committed module itself, fetched with
`git show <BEFORE_SHA>:runtime-py/src/bantamkit/evalrun.py` and imported under its own name.
BEFORE_SHA is the commit this branch was cut from — the harness exactly as it stood when the
register entry was filed. The AFTER is the working-tree copy of the same path, imported the same
way, so the two columns differ in nothing but the file under test.

Every task below is MATERIALISED for real by the harness's own generator and then put through
the harness's own `check_expected_against_corpus` and `check_question_against_prompt`. Nothing
here re-implements a rule.

WHAT IS MEASURED, and each section is a clause of the property RB-P91 states:

  CENSUS     The cost side of the entry, re-derived rather than quoted: how many committed tasks
             declare a `document_setup:`, how many of those carry a question address, and how
             many tasks outside that set declare a corpus at all. A floor that broke a committed
             task would be a different trade than the entry describes.

  CONTROL    The nine committed `document-read` tasks, unmodified, must be ACCEPTED by both
             columns. If a control moves, no refusal below is attributable to the change.

  RB-P90     The already-closed half: a prompt naming a row the corpus does not hold, with the
             question address still declared. REFUSED in both columns — the new clauses must not
             be what closes it, or the AFTER column would be reporting an old win as a new one.

  EVASION    The two shapes the entry measured ACCEPTED. Take the same defect as RB-P90 and
             delete the question address, or rename it `unasked_`. Both must move
             ACCEPTED -> REFUSED, and each must move on the clause that names it.

  COUNT      The task a floor that merely COUNTED question labels would admit: one real question
             address the prompt does name, and a prompt that goes on to ask about a row the
             corpus does not hold. ACCEPTED -> REFUSED, which is the argument for stating the
             clause on the prompt rather than on the label set.

  DELIBERATE The case that must SURVIVE: a prompt that addresses no single row, saying so with
             `unasked_`. ACCEPTED in both columns. A guard that refused this would have closed
             the hole by banning a legitimate task.

Run:  PYTHONPATH=runtime-py/src BANTAMKIT_ASSETS=assets \\
        python docs/eval-data/2026-08-20-j29-question-floor-probe.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
BEFORE_SHA = "640c6b0"
MODULE_PATH = "runtime-py/src/bantamkit/evalrun.py"
TASKS_DIR = REPO / "assets" / "evals" / "document" / "tasks"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def before_module(tmp: Path):
    """The committed pre-change harness, fetched from git rather than described."""
    blob = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{BEFORE_SHA}:{MODULE_PATH}"],
        capture_output=True, text=True, check=True,
    ).stdout
    path = tmp / "evalrun_before.py"
    path.write_text(blob)
    return load_module("evalrun_before", path)


def verdict(module, task: dict, workdir: Path) -> str:
    """ACCEPTED, or REFUSED plus the class that refused. Exactly what `run_task` would do."""
    try:
        fixtures = module.materialise_documents(task, workdir, "bare")
        module.check_expected_against_corpus(task, fixtures)
        module.check_question_against_prompt(task, fixtures)
    except module.EvalConfigError as exc:
        return f"REFUSED ({type(exc).__name__})"
    return "ACCEPTED"


def committed(name: str = "doc-small-137") -> dict:
    return yaml.safe_load((TASKS_DIR / f"{name}.yaml").read_text())


def ask_a_row_the_corpus_does_not_hold(task: dict) -> dict:
    task["prompt"] = task["prompt"].replace("SKU-000137", "SKU-999999")
    return task


def rb_p90() -> dict:
    return ask_a_row_the_corpus_does_not_hold(committed())


def evasion_omit() -> dict:
    task = ask_a_row_the_corpus_does_not_hold(committed())
    del task["document_setup"][0]["answers"]["question_sku"]
    return task


def evasion_rename() -> dict:
    task = ask_a_row_the_corpus_does_not_hold(committed())
    answers = task["document_setup"][0]["answers"]
    answers["unasked_question_sku"] = answers.pop("question_sku")
    return task


def count_evasion() -> dict:
    """One real question address the prompt names, and a question the corpus cannot answer."""
    task = committed()
    answers = task["document_setup"][0]["answers"]
    answers["question_region"] = answers.pop("question_sku").replace("A", "B")
    task["prompt"] = "In the east region, what is the units value for SKU-999999?"
    task["scoring"] = {"kind": "contains", "expected": ["7726"]}
    return task


def deliberate() -> dict:
    """A prompt that addresses no single row, saying so in the label. Must stay expressible."""
    task = committed()
    answers = task["document_setup"][0]["answers"]
    answers["unasked_question_sku"] = answers.pop("question_sku")
    task["prompt"] = "What is the largest units value anywhere on the sheet?"
    task["scoring"] = {"kind": "contains", "expected": ["7726"]}
    return task


CASES = [
    ("CONTROL    doc-small-137, unmodified", committed, "ACCEPTED", "ACCEPTED"),
    ("RB-P90     prompt asks SKU-999999, question_sku declared", rb_p90, "REFUSED", "REFUSED"),
    ("EVASION 1  ... and question_sku deleted", evasion_omit, "ACCEPTED", "REFUSED"),
    ("EVASION 2  ... and question_sku renamed unasked_", evasion_rename, "ACCEPTED", "REFUSED"),
    ("COUNT      one question address, prompt still asks SKU-999999", count_evasion,
     "ACCEPTED", "REFUSED"),
    ("DELIBERATE aggregation prompt, cell declared unasked_", deliberate,
     "ACCEPTED", "ACCEPTED"),
]


def census() -> list[str]:
    """The cost side of the deferral, re-derived from the committed task files."""
    tasks = {p: yaml.safe_load(p.read_text())
             for p in sorted((REPO / "assets" / "evals").rglob("tasks/*.yaml"))}
    with_corpus = {p: t for p, t in tasks.items() if t.get("document_setup")}
    asked = {
        p for p, t in with_corpus.items()
        for e in t["document_setup"]
        if any(not label.startswith(("expected_", "unasked_"))
               for label in (e.get("answers") or {}))
    }
    traces = {p for p, t in tasks.items() if (t.get("scoring") or {}).get("kind") == "tool_trace"}
    return [
        f"committed task files                       : {len(tasks)}",
        f"  declaring a document_setup:              : {len(with_corpus)}",
        f"  of those, carrying a question address    : {len(asked)}",
        f"  declaring a corpus but no question addr  : {len(with_corpus) - len(asked)}",
        f"tool_trace tasks                           : {len(traces)}",
        f"  of those, declaring a document_setup:    : {len(traces & set(with_corpus))}",
    ]


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        before = before_module(tmp)
        after = load_module("evalrun_after", REPO / MODULE_PATH)

        print(f"BEFORE {BEFORE_SHA}:{MODULE_PATH}")
        print(f"AFTER  {after.__file__}\n")

        print("CENSUS (re-derived, at this worktree)")
        for line in census():
            print(f"  {line}")

        print("\nCONTROL: the nine committed tasks, unmodified")
        bad = 0
        for i, path in enumerate(sorted(TASKS_DIR.glob("*.yaml"))):
            task = yaml.safe_load(path.read_text())
            b = verdict(before, task, tmp / f"nine-b-{i}")
            a = verdict(after, task, tmp / f"nine-a-{i}")
            flag = "" if (b, a) == ("ACCEPTED", "ACCEPTED") else "   <-- MOVED"
            bad += bool(flag)
            print(f"  {path.stem:<22} before={b:<28} after={a}{flag}")

        print("\n{:<58} {:<28} {}".format("CASE", "BEFORE", "AFTER"))
        for i, (label, make, want_before, want_after) in enumerate(CASES):
            b = verdict(before, make(), tmp / f"case-b-{i}")
            a = verdict(after, make(), tmp / f"case-a-{i}")
            ok = b.startswith(want_before) and a.startswith(want_after)
            bad += not ok
            print("{:<58} {:<28} {}{}".format(label, b, a, "" if ok else "   <-- UNEXPECTED"))

        print("\nTHE MESSAGE EACH EVASION NOW GETS")
        for label, make in (("EVASION 1", evasion_omit), ("EVASION 2", evasion_rename),
                            ("COUNT", count_evasion)):
            task = make()
            fixtures = after.materialise_documents(task, tmp / f"msg-{label}", "bare")
            try:
                after.check_question_against_prompt(task, fixtures)
            except after.UnaskedAnswerError as exc:
                print(f"  {label}: {exc}\n")

        print("OK" if not bad else f"{bad} UNEXPECTED VERDICT(S)")
        return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
