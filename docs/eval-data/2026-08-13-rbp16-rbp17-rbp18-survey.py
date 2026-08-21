"""The three RB-P16/RB-P17/RB-P18 surveys, re-derived from the committed artifacts.

    .venv/bin/python docs/eval-data/2026-08-13-rbp16-rbp17-rbp18-survey.py .

Reads only committed evidence and this repo's git history; writes nothing. Every table
in `2026-08-13-rbp16-rbp17-rbp18-survey.md` is this script's stdout, so a reader
re-derives the numbers instead of trusting the prose beside them.

L1 of the RB-P16/17/18 job. PROBE ONLY — nothing here changes behaviour, and nothing
here is a fix.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
DATA = ROOT / "docs" / "eval-data"
sys.path.insert(0, str(ROOT / "runtime-py" / "src"))

from bantamkit.agent import response_format_for
from bantamkit.client import Message
from bantamkit.contract import schema_instruction
from bantamkit.criticreplay import (
    Case,
    _parse_rubric,
    _payload_sha,
    render_prompt,
    sha256_text,
)

RULE = "=" * 78


def summaries() -> list[tuple[Path, dict]]:
    """Every committed summary that carries a §7 `comparisons` block."""
    out = []
    for path in sorted(DATA.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        if '"comparisons"' not in text:
            continue
        out.append((path, json.loads(text)))
    return out


# ---- survey 1: the verdict band (RB-P16) ----


def verdict_rows() -> list[dict]:
    rows = []
    for path, summary in summaries():
        for cell in summary["cells"]:
            for comp in cell["comparisons"]:
                a_pass, size_a = (int(x) for x in comp["a_pass_rate"].split("/"))
                b_pass, size_b = (int(x) for x in comp["b_pass_rate"].split("/"))
                diff = Fraction(a_pass, size_a) - Fraction(b_pass, size_b)
                rows.append(
                    {
                        "run": path.name,
                        "task": cell["task"],
                        "repeat": cell["repeat"],
                        "a": comp["a"],
                        "b": comp["b"],
                        "verdict": comp["verdict"],
                        "a_pass_rate": comp["a_pass_rate"],
                        "b_pass_rate": comp["b_pass_rate"],
                        "family_size": comp["family_size"],
                        "count_diff": a_pass - b_pass,
                        "rate_diff": diff,
                        "sign": 0 if diff == 0 else (1 if diff > 0 else -1),
                        "attributable": comp["attributable"],
                        "fragile": comp["fragile"],
                        # Which of §7's rules DECIDED `attributable`, in the order
                        # `_compare` applies them: rule 1 (separation), then rule 2
                        # (fragility voids it), then RB-P19's third (the separation
                        # must survive dropping the shared-token points).
                        "decided_by": (
                            "rule 1: not F/F vs 0/F"
                            if comp["verdict"] != "distinguishable"
                            else "rule 2: fragile family"
                            if comp["fragile"]
                            else "RB-P19: separation did not survive the guard drop"
                            if comp.get("guard_verdict", "distinguishable") != "distinguishable"
                            else "rules 1+2+guard all passed"
                        ),
                    }
                )
    return rows


def survey_verdicts() -> list[dict]:
    rows = verdict_rows()
    print(RULE)
    print("SURVEY 1 (RB-P16) — every §7 comparison in every committed summary")
    print(RULE)
    print(
        f"{'run':46} {'task':14} {'r':>1} {'a vs b':26} {'verdict':18} "
        f"{'a':>6} {'b':>6} {'F':>2} {'Δn':>3} {'Δrate':>9} {'sgn':>3} attr"
    )
    for row in rows:
        print(
            f"{row['run'][:46]:46} {row['task']:14} {row['repeat']:1} "
            f"{row['a'] + ' vs ' + row['b']:26} {row['verdict']:18} "
            f"{row['a_pass_rate']:>6} {row['b_pass_rate']:>6} {row['family_size']:2} "
            f"{row['count_diff']:3} {float(row['rate_diff']):+9.4f} {row['sign']:+3} "
            f"{row['attributable']}"
        )

    band = [row for row in rows if row["verdict"] == "inconclusive"]
    spans = sorted(abs(row["rate_diff"]) for row in band)
    print()
    print(f"cells with a comparison: {len(rows)} over {len({r['run'] for r in rows})} runs")
    print(f"  inconclusive       : {sum(1 for r in rows if r['verdict'] == 'inconclusive')}")
    print(f"  indistinguishable  : {sum(1 for r in rows if r['verdict'] == 'indistinguishable')}")
    print(f"  distinguishable    : {sum(1 for r in rows if r['verdict'] == 'distinguishable')}")
    print(f"  attributable       : {sum(1 for r in rows if r['attributable'])}")
    print(f"|Δrate| over the band: {[str(s) for s in spans]}")
    print(f"  min {float(spans[0]):.4f} ({spans[0]})   max {float(spans[-1]):.4f} ({spans[-1]})")
    print(f"|Δn| over the band   : {sorted(abs(r['count_diff']) for r in band)}")
    print()
    print("which §7 rule decided `attributable`:")
    decisions: dict[str, int] = {}
    for row in rows:
        decisions[row["decided_by"]] = decisions.get(row["decided_by"], 0) + 1
    for reason, count in sorted(decisions.items(), key=lambda kv: -kv[1]):
        print(f"  {count:2} cells  {reason}")

    print()
    print("sign agreement, per (run, variant pair):")
    pairs: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        pairs.setdefault((row["run"], f"{row['a']} vs {row['b']}"), []).append(row)
    for (run, pair), group in pairs.items():
        signs = [row["sign"] for row in group]
        nonzero = {s for s in signs if s}
        print(
            f"  {run[:46]:46} {pair:26} signs={signs} "
            f"all-agree={len(set(signs)) == 1} nonzero-agree={len(nonzero) <= 1} "
            f"verdicts={[row['verdict'] for row in group]}"
        )
    return rows


def survey_report_discriminability(rows: list[dict]) -> None:
    """What the summary reports about two cells of ONE pair whose gaps differ 2.5x."""
    print()
    print(RULE)
    print("SURVEY 1b (RB-P16) — is the band's REPORT a function of the effect size?")
    print(RULE)
    path = DATA / "2026-08-11-pb14-14b-nav-prod-port-perturbation-summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    picked = {}
    for cell in summary["cells"]:
        for comp in cell["comparisons"]:
            if (comp["a"], comp["b"]) == ("A-asfiled", "C-attempted") and cell["repeat"] in (0, 1):
                picked[cell["repeat"]] = comp
    stripped = {
        repeat: {k: v for k, v in comp.items() if k not in ("a_pass_rate", "b_pass_rate")}
        for repeat, comp in picked.items()
    }
    for repeat, comp in picked.items():
        gap = Fraction(*(int(x) for x in comp["a_pass_rate"].split("/"))) - Fraction(
            *(int(x) for x in comp["b_pass_rate"].split("/"))
        )
        print(f"  r{repeat}: {comp['a_pass_rate']} vs {comp['b_pass_rate']}  |Δ| = {abs(gap)}")
    print(f"  reports identical once the two fractions are removed: {stripped[0] == stripped[1]}")
    print(f"    r0 {json.dumps(stripped[0], sort_keys=True)}")
    print(f"    r1 {json.dumps(stripped[1], sort_keys=True)}")


def survey_point_level_agreement() -> None:
    """`indistinguishable` is equal COUNTS. Do the two variants pass the same points?"""
    print()
    print(RULE)
    print("SURVEY 1c (RB-P16) — does `indistinguishable` mean the variants agree?")
    print(RULE)
    path = DATA / "2026-08-11-pb14-14b-nav-prod-port-perturbation.jsonl"
    passed: dict[tuple[int, str], dict[str, bool]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        passed.setdefault((row["repeat"], row["variant"]), {})[row["point"]] = row["passed"]
    print(f"{'cell':6} {'F':>2} {'B':>4} {'C':>4} {'agree':>5}  B-only / C-only")
    for repeat in sorted({r for r, _ in passed}):
        b, c = passed[(repeat, "B-nonewline")], passed[(repeat, "C-attempted")]
        family = sorted(set(b) & set(c))
        b_pass = {p for p in family if b[p]}
        c_pass = {p for p in family if c[p]}
        print(
            f"r{repeat:<5} {len(family):2} {len(b_pass):4} {len(c_pass):4} "
            f"{len(b_pass & c_pass):5}  {sorted(b_pass - c_pass)} / {sorted(c_pass - b_pass)}"
        )


# ---- survey 2: provenance (RB-P17) ----


def git_object_exists(ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", f"{ref}^{{commit}}"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def survey_provenance() -> None:
    print()
    print(RULE)
    print("SURVEY 2 (RB-P17) — every `rubric_ref` in every committed summary")
    print(RULE)
    refs: dict[str, dict] = {}
    for path, summary in summaries():
        for variant in summary.get("variants", []):
            entry = refs.setdefault(
                variant["rubric_ref"],
                {"runs": set(), "labels": set(), "shas": set()},
            )
            entry["runs"].add(path.name)
            entry["labels"].add(variant["label"])
            entry["shas"].add(variant["rubric_sha256"])
    for ref, entry in sorted(refs.items()):
        in_repo = (ROOT / ref).is_file() if not ref.startswith("/") else False
        recovered = None
        if in_repo:
            recovered = sha256_text((ROOT / ref).read_text(encoding="utf-8"))
        verdict = (
            "resolvable today (repo-relative path)"
            if in_repo and recovered in entry["shas"]
            else "a bare git ref: the OBJECT resolves, the PATH is not recorded"
            if git_object_exists(ref)
            else "a path that no longer resolves from this repo"
        )
        print(f"  ref        : {ref}")
        print(f"  labels     : {sorted(entry['labels'])}")
        print(f"  rubric_sha : {sorted(s[:12] for s in entry['shas'])}")
        print(f"  runs       : {len(entry['runs'])}  {sorted(entry['runs'])}")
        print(f"  -> {verdict}")
        print()

    print("re-verification of the claim RB-P17 rests on:")
    raw = subprocess.run(
        ["git", "-C", str(ROOT), "show", "d2f78b7:assets/rubrics/task-completion.yaml"],
        capture_output=True,
        text=True,
        check=True, encoding="utf-8",
    ).stdout
    template = _parse_rubric(raw, "git:d2f78b7").prompt
    print(f"  git:d2f78b7:assets/rubrics/task-completion.yaml file sha256 = {sha256_text(raw)}")
    print(f"  its `prompt` template sha256 (A-asfiled base)             = {sha256_text(template)}")
    stripped = template.removesuffix("\n")
    print(f"  the same, minus one trailing newline (B-nonewline base)   = {sha256_text(stripped)}")
    print("  manifest materialized_variants.B-nonewline.base_sha256    = d1f32ad294...")

    print()
    print("the spec forms `--rubric LABEL=SPEC` admits today, and the rule ids `derive:` would need:")
    manifest = DATA.parent.parent / "assets" / "evals" / "perturbations" / "task-completion.yaml"
    import yaml

    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    print(f"  manifest: {manifest.relative_to(ROOT)}  points: {len(data['points'])}")
    for point in data["points"]:
        b = point["variants"].get("B-nonewline", {})
        a = point["variants"].get("A-asfiled", {})
        print(
            f"    {point['id']:30} rule={point['rule']:30} "
            f"A->{a.get('sha256', '')[:12] or '(n/a)':12} B-applicable={b.get('applicable')}"
        )


# ---- survey 3: the payload field (RB-P18) ----


def survey_payload() -> None:
    print()
    print(RULE)
    print("SURVEY 3 (RB-P18) — every `payload_sha256` recipe, re-measured")
    print(RULE)
    sa3 = json.loads((DATA / "2026-08-11-sa3-14b-nav-prod-port-critic-replay.json").read_text(
        encoding="utf-8"
    ))
    bar_rows = [
        json.loads(line)
        for line in (DATA / "2026-08-11-pb14-14b-nav-prod-port-perturbation.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    identity = {(r["variant"], r["repeat"]): r for r in bar_rows if r["point"] == "identity"}
    model = sa3["model"]
    print(
        f"{'variant':12} {'ref':8} {'r':>1} {'seed':>11} {'prompt_sha':13} "
        f"{'bar recipe':13} {'SA3 recipe':13} bar-row  SA3-row"
    )
    for ref, label in (("d2f78b7", "A-asfiled"), ("e57f1a6", "C-attempted")):
        raw = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{ref}:assets/rubrics/task-completion.yaml"],
            capture_output=True,
            text=True,
            check=True, encoding="utf-8",
        ).stdout
        rubric = _parse_rubric(raw, f"git:{ref}")
        for repeat, seed in ((0, 2331795949), (1, 4094558621), (2, 634446002)):
            case = Case(
                task=sa3["task"],
                repeat=repeat,
                seed=seed,
                prompt=sa3["task_prompt"],
                output=sa3["answer_replayed"],
            )
            prompt = render_prompt(rubric.prompt, case)
            response_format = response_format_for(rubric.schema)
            messages = [
                Message(role="system", content=schema_instruction(rubric.schema)),
                Message(role="user", content=prompt),
            ]
            bar = _payload_sha(model, seed, messages, response_format)
            payload: dict = {
                "model": model,
                "messages": [m.to_wire() for m in messages],
                "seed": seed,
                "response_format": response_format,
            }
            # The ONE difference between the two recipes, recovered by search: SA3
            # serialized the SAME dict with `sort_keys=True`.
            sa3_recipe = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            row = identity.get((label, repeat))
            sa3_committed = sorted(
                {v["payload_sha256"][0] for v in sa3["replay_verdicts"]
                 if v["ref"] == ref and v["repeat"] == repeat}
            )
            print(
                f"{label:12} {ref:8} {repeat:1} {seed:11} {sha256_text(prompt)[:12]:13} "
                f"{bar[:12]:13} {sa3_recipe[:12]:13} "
                f"{row is not None and row['payload_sha256'] == bar}    "
                f"{sa3_committed == [sa3_recipe]}"
            )
    print()
    print("recipes, verbatim:")
    print("  bar (criticreplay._payload_sha, runtime-py/src/bantamkit/criticreplay.py):")
    print("      sha256(json.dumps({model, messages, seed, response_format},")
    print("                        ensure_ascii=False))            # INSERTION order")
    print("  SA3 (scratchpad sa3_one.py / sa3_ws.py, no longer in any tree):")
    print("      sha256(json.dumps(<the same dict>,")
    print("                        ensure_ascii=False, sort_keys=True))   # SORTED keys")


def main() -> None:
    rows = survey_verdicts()
    survey_report_discriminability(rows)
    survey_point_level_agreement()
    survey_provenance()
    survey_payload()


if __name__ == "__main__":
    main()
