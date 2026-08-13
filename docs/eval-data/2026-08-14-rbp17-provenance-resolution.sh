#!/bin/sh
# RB-P17 — whether a run's recorded provenance can be RESOLVED from this repository
# alone, read off a real run's summary JSON by a checker that does not import the module.
# The runner that produced docs/eval-data/2026-08-14-rbp17-provenance-resolution.md.
#
#   sh docs/eval-data/2026-08-14-rbp17-provenance-resolution.sh "$PWD" /tmp/rbp17
#
# BEFORE column:
#   git checkout 32773f9 -- runtime-py/src/bantamkit/criticreplay.py
#   sh docs/eval-data/2026-08-14-rbp17-provenance-resolution.sh "$PWD" /tmp/rbp17-before
#   git checkout fccc637 -- runtime-py/src/bantamkit/criticreplay.py   # by SHA, not HEAD
#
# Layer: Measurement. Statuses are /bin/sh's own $?, with no PYTEST_* key in the child's
# environment. RB-P28 is open, so the suite is NOT the evidence for this claim: the nodes
# in test_criticreplay.py are regression guards and this file is the measurement.
#
# THE CHECKER IS INDEPENDENT OF THE THING IT CHECKS. It imports json, hashlib, subprocess
# and yaml, and never imports bantamkit. It takes each `rubric_ref` the run recorded and
# tries to recover the rubric from THIS REPOSITORY: `git show` for a git spec, and for a
# `derive:` spec it reads the manifest as YAML and re-implements the declared `op` from
# the manifest's own words. Asking the module to resolve a ref the module wrote would be
# the run agreeing with itself.
#
# THE CRITIC IS A HASH. rbp16_effect_probe.py is the shipped main() with the client
# constructor replaced by score = sha256(prompt|seed) % 11 — L2's harness, reused
# unchanged, so nothing about the critic was chosen after this claim was written.
#
# NOTHING HERE INVENTS A RUBRIC. The variants are the two the committed acceptance run
# used: A-asfiled is git:d2f78b7:assets/rubrics/task-completion.yaml, and B-nonewline is
# that rubric with the frozen manifest's W1-trailing-newline applied. assets/ is not
# touched. B0 is the SAME rubric materialized to a file under $WORK, which is the shape
# the committed runs recorded — the control that shows the checker can say no.
set -u
REPO=$1; WORK=$2
PY="$REPO/.venv/bin/python"; PROBE="$REPO/runtime-py/tests/rbp16_effect_probe.py"
rm -rf "$WORK"; mkdir -p "$WORK/transcripts"
cd "$REPO" || exit 1

MANIFEST=assets/evals/perturbations/task-completion.yaml
BASE=git:d2f78b7:assets/rubrics/task-completion.yaml
DERIVE="derive:$MANIFEST:W1-trailing-newline:$BASE"

# ---- the fact the whole fix rests on, re-derived here rather than cited ----
echo '## re-derivation'
"$PY" - "$REPO" <<'PY'
import hashlib, pathlib, subprocess, sys, yaml
repo = pathlib.Path(sys.argv[1])
def h(s): return hashlib.sha256(s.encode()).hexdigest()[:12]
raw = subprocess.run(["git", "-C", str(repo), "show",
                      "d2f78b7:assets/rubrics/task-completion.yaml"],
                     capture_output=True, text=True, check=True).stdout
tpl = yaml.safe_load(raw)["prompt"]
man = yaml.safe_load((repo / "assets/evals/perturbations/task-completion.yaml").read_text())
mv = man["materialized_variants"]
print(f"A-asfiled   file sha256   = {h(raw)}")
print(f"A-asfiled   template      = {h(tpl)}   manifest base_sha256 = "
      f"{mv['A-asfiled']['base_sha256'][:12]}")
print(f"minus one trailing \\n     = {h(tpl[:-1])}   manifest base_sha256 = "
      f"{mv['B-nonewline']['base_sha256'][:12]}   (B-nonewline)")
w1 = next(p for p in man["points"] if p["id"] == "W1-trailing-newline")
print(f"W1 applicable to A        = {w1['variants']['A-asfiled']['applicable']} "
      f"-> {w1['variants']['A-asfiled']['sha256'][:12]}")
print(f"W1 applicable to B        = {w1['variants']['B-nonewline']['applicable']} "
      "  (its own fixed point: the rule names no variant here)")
PY
echo

# ---- the runs ----
BK_OUT="$WORK/out.txt"; BK_ERR="$WORK/err.txt"
export BK_OUT BK_ERR
run() {  # $1 label, rest = argv after the probe
  L=$1; shift
  S="$WORK/$L-summary.json"; rm -f "$S"
  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
    /bin/sh -c '{ "$@" >"$BK_OUT" 2>"$BK_ERR"; echo "status=$?"; }' sh \
    "$PY" "$PROBE" --summary "$S" "$@" > "$WORK/st.txt"
  ST=$(sed -n 's/^status=//p' "$WORK/st.txt")
  cp "$BK_ERR" "$WORK/$L-err.txt"
  "$PY" - "$L" "$ST" "$S" "$REPO" "$WORK/$L-err.txt" <<'PY'
import hashlib, json, pathlib, subprocess, sys, yaml
label, status, summary_path, repo_s, err_path = sys.argv[1:6]
repo = pathlib.Path(repo_s)


def template(ref):
    """The rubric a recorded ref names, from this repo alone. None = nothing."""
    if ref.startswith("derive:"):
        parts = ref.split(":", 3)
        if len(parts) < 4:
            return None
        _, manifest_spec, rule_id, base = parts
        man = repo / manifest_spec
        if not man.is_file():
            return None
        point = next(
            (p for p in yaml.safe_load(man.read_text())["points"] if p["id"] == rule_id),
            None,
        )
        base_tpl = template(base)
        if point is None or base_tpl is None:
            return None
        if point["op"] == "strip-trailing-newline":
            return base_tpl[:-1] if base_tpl.endswith("\n") else None
        if point["op"] == "append-trailing-newline":
            return base_tpl + "\n"
        if point["op"] == "identity":
            return base_tpl
        return None
    if ref.startswith("git:") and ref.count(":") >= 2:
        _, git_ref, path = ref.split(":", 2)
        shown = subprocess.run(["git", "-C", str(repo), "show", f"{git_ref}:{path}"],
                               capture_output=True, text=True)
        return yaml.safe_load(shown.stdout)["prompt"] if shown.returncode == 0 else None
    if not ref.startswith("/") and (repo / ref).is_file():
        return yaml.safe_load((repo / ref).read_text())["prompt"]
    return None


total = resolved = named_rubric = 0
refs = []
p = pathlib.Path(summary_path)
if p.is_file():
    for v in json.loads(p.read_text())["variants"]:
        total += 1
        ref = v["rubric_ref"]
        refs.append(ref if len(ref) < 34 else ref[:14] + "..." + ref[-17:])
        # The recorded RUBRIC sha, if the record has one at all. Pre-fix there is no
        # such column, so this counts how many rows can even state what was read.
        tpl_sha = v.get("rubric_template_sha256", "")
        named_rubric += bool(tpl_sha)
        got = template(ref)
        if got is not None and hashlib.sha256(got.encode()).hexdigest() == tpl_sha:
            resolved += 1
else:
    refs = [pathlib.Path(err_path).read_text().strip().splitlines()[-1][:46] or "-"]
print(f"{label}|{status}|{total}|{resolved}/{total if total else 0}|"
      f"{named_rubric}/{total if total else 0}|{' , '.join(refs) or '-'}")
PY
  cd "$REPO" || exit 1
}

# The cells the committed baseline harness names, with the committed seeds.
"$PY" - "$WORK" "$REPO" <<'PY'
import json, pathlib, sys, yaml
work, repo = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
raw = yaml.safe_load((repo / "assets/rubrics/task-completion.yaml").read_text())
# B0: the null control MATERIALIZED TO A FILE, which is what the committed runs did.
(work / "b-nonewline.yaml").write_text(
    yaml.safe_dump({**raw, "prompt": raw["prompt"][:-1]}, sort_keys=False))
for task, repeat, seed, out in (
    ("nav-prod-port", 0, 2331795949, "The production port is 8443."),
    ("recall-org-quota", 0, 634446002, "The org quota is 6000 requests-per-minute."),
):
    (work / "transcripts" / f"critique--{task}--r{repeat}.json").write_text(json.dumps({
        "task": task, "config": "critique", "repeat": repeat, "passed": True,
        "outcome": "pass", "seed": seed, "output": out, "messages": [],
    }))
PY

OK="--base-url http://x --model fake-14b --transcripts $WORK/transcripts"

echo 'case|status|variants|resolved|names_rubric|recorded rubric_ref'
run 'E1-git-and-derive'  --rubric "A-asfiled=$BASE" --rubric "B-nonewline=$DERIVE" $OK
run 'E2-derive-alone'    --rubric "B-nonewline=$DERIVE" $OK
# CONTROLS. B0 is the committed runs' own shape: the null control as a loose file under
# a working directory. It must NOT resolve — a checker that resolved it would be
# measuring nothing. C1/C2 are refusals and must stay refusals, not gain a report.
run 'B0-CONTROL-materialized-file' --rubric "A-asfiled=$BASE" \
    --rubric "B-nonewline=$WORK/b-nonewline.yaml" $OK
run 'C1-CONTROL-derive-of-a-derive' --rubric "A-asfiled=$BASE" \
    --rubric "B=derive:$MANIFEST:W1-trailing-newline:$DERIVE" $OK
run 'C2-CONTROL-rule-not-in-manifest' --rubric "A-asfiled=$BASE" \
    --rubric "B=derive:$MANIFEST:W9-nope:$BASE" $OK
