#!/bin/sh
# RB-P16 — what a §7 verdict REPORTS, read off a real run's stdout and summary JSON by a
# checker that does not import the module. The runner that produced
# docs/eval-data/2026-08-14-rbp16-effect-size-report.md.
#
#   sh docs/eval-data/2026-08-14-rbp16-effect-size-report.sh "$PWD" /tmp/rbp16
#
# BEFORE column:
#   git checkout abc2a34 -- runtime-py/src/bantamkit/criticreplay.py
#   sh docs/eval-data/2026-08-14-rbp16-effect-size-report.sh "$PWD" /tmp/rbp16-before
#   git checkout HEAD -- runtime-py/src/bantamkit/criticreplay.py
#
# Layer: Measurement. Statuses are /bin/sh's own $?, with no PYTEST_* key in the child's
# environment. RB-P28 is open, so the suite is NOT the evidence for this claim: the nodes
# in test_criticreplay.py are regression guards and this file is the measurement.
#
# THE CHECKER IS INDEPENDENT OF THE THING IT CHECKS. It imports json and re, never
# bantamkit, and it recomputes the difference ITSELF from the two `a_pass_rate` /
# `b_pass_rate` strings the run recorded. So "the report carries the difference" is a
# comparison between two derivations, not a re-read of one — asking the module for the
# number it printed would be the run agreeing with itself.
#
# THE CRITIC IS A HASH, NOT A SCORER WRITTEN TO PROVE A POINT. `rbp16_effect_probe.py` is
# the shipped main() with the client constructor replaced by score = sha256(prompt|seed)
# % 11 — the baseline harness's function, fixed before its gaps were looked at. The band
# below is whatever this rubric pair and these three committed cells produce.
#
# THE RUBRIC PAIR IS THE COMMITTED NULL CONTROL'S SHAPE. `A` is the shipped
# assets/rubrics/task-completion.yaml; `B` is the same file with one trailing newline
# removed from its `prompt` — RB-P14's B-nonewline edit. Nothing here is invented, and
# `assets/` is not touched.
set -u
REPO=$1; WORK=$2
PY="$REPO/.venv/bin/python"; PROBE="$REPO/runtime-py/tests/rbp16_effect_probe.py"
rm -rf "$WORK"; mkdir -p "$WORK/transcripts" "$WORK/empty"
cd "$REPO" || exit 1

"$PY" - "$WORK" "$REPO" <<'PY'
import json, pathlib, sys, yaml
work, repo = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
raw = yaml.safe_load((repo / "assets/rubrics/task-completion.yaml").read_text())
(work / "A.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
(work / "B.yaml").write_text(yaml.safe_dump({**raw, "prompt": raw["prompt"][:-1]},
                                            sort_keys=False))
# The three cells the committed baseline harness names, with the committed seeds.
for task, repeat, seed, out in (
    ("nav-prod-port", 0, 2331795949, "The production port is 8443."),
    ("recall-oncall-rotation", 1, 4094558621, "Rota: who is on-call for billing-svc."),
    ("recall-org-quota", 0, 634446002, "The org quota is 6000 requests-per-minute."),
):
    (work / "transcripts" / f"critique--{task}--r{repeat}.json").write_text(json.dumps({
        "task": task, "config": "critique", "repeat": repeat, "passed": True,
        "outcome": "pass", "seed": seed, "output": out, "messages": [],
    }))
PY

BK_OUT="$WORK/out.txt"; BK_ERR="$WORK/err.txt"
export BK_OUT BK_ERR
run() {  # $1 label, rest = argv after the probe
  L=$1; shift
  S="$WORK/$L-summary.json"; rm -f "$S"
  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
    /bin/sh -c '{ "$@" >"$BK_OUT" 2>"$BK_ERR"; echo "status=$?"; }' sh \
    "$PY" "$PROBE" --summary "$S" "$@" > "$WORK/st.txt"
  ST=$(sed -n 's/^status=//p' "$WORK/st.txt")
  cp "$BK_OUT" "$WORK/$L-out.txt"
  "$PY" - "$L" "$ST" "$WORK/$L-out.txt" "$S" <<'PY'
import json, pathlib, re, sys
label, status, out_path, summary_path = sys.argv[1:5]
text = pathlib.Path(out_path).read_text()
effect_lines = [ln for ln in text.splitlines() if ln.startswith("    effect: ")]
p = pathlib.Path(summary_path)
comparisons, carries, coll_all, coll_s7, ties = 0, 0, 0, 0, "-"
# TWO collapse columns, because one of them is honest and weak and the other is sharp
# and narrower, and reporting only the flattering one would be the thing this project
# keeps filing bugs about. `collapse_all` is the whole comparison dict minus the two
# pass-rate fractions — it includes CELL-SCOPED guard bookkeeping (`guard_dropped_rules`,
# `guard_family_size`), which differs between cells for reasons that have nothing to do
# with the verdict, so on most rigs it never collapses even pre-fix. `collapse_s7` is
# only what §7's own rule produces about the pair. That is the tuple RB-P16 is about.
S7 = ("a", "b", "verdict", "family_size", "dropped_rules", "fragile", "attributable",
      "effect", "guard_verdict")
if p.is_file():
    summary = json.loads(p.read_text())
    seen_all, seen_s7, tie_counts = set(), set(), []
    for cell in summary["cells"]:
        for c in cell["comparisons"]:
            comparisons += 1
            # Recomputed HERE, from the two recorded fractions, without the module.
            pa = int(c["a_pass_rate"].split("/")[0])
            pb = int(c["b_pass_rate"].split("/")[0])
            delta = pa - pb
            blob = json.dumps(
                {k: v for k, v in c.items() if k not in ("a_pass_rate", "b_pass_rate")},
                sort_keys=True,
            )
            s7 = json.dumps({k: c[k] for k in S7 if k in c}, sort_keys=True)
            # Does the report say the difference, anywhere in it, without the reader
            # subtracting the fractions himself?
            if re.search(rf"(?<![0-9]){abs(delta)}(?![0-9])", blob) and (
                delta == 0 or re.search(r'"sign":\s*-?1', blob)
            ):
                carries += 1
            coll_all += blob in seen_all
            coll_s7 += s7 in seen_s7
            seen_all.add(blob)
            seen_s7.add(s7)
            if c["verdict"] == "indistinguishable":
                m = re.search(r'"disagreeing_points":\s*(\d+)', blob)
                tie_counts.append(m.group(1) if m else "unstated")
    ties = ",".join(tie_counts) or "-"
print(f"{label}|{status}|{comparisons}|{carries}|{coll_all}|{coll_s7}|"
      f"{len(effect_lines)}|{ties}")
PY
  cd "$REPO" || exit 1
}
OK="--base-url http://x --model fake-14b --transcripts $WORK/transcripts"
AB="--rubric A=$WORK/A.yaml --rubric B=$WORK/B.yaml"

echo 'case|status|comparisons|carry_delta|collapse_all|collapse_s7|effect_lines|tie_disagreements'
run 'E1-two-variants-three-cells'   $AB $OK
run 'E2-violations-exit-zero'       $AB $OK --violations-exit-zero
run 'E3-identity-only'              $AB $OK --identity-only
# Controls. These must NOT move: a run with nothing to compare must not invent a
# comparison, the zero-spend refusal must stay zero-spend, and a refusal must stay a
# refusal rather than gain a report.
run 'C1-CONTROL-single-variant'     --rubric "A=$WORK/A.yaml" $OK
run 'C2-CONTROL-guard-error'        $AB $OK --guard error
run 'C3-CONTROL-empty-transcripts'  $AB --base-url http://x --model fake-14b \
                                    --transcripts "$WORK/empty"
