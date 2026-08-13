#!/bin/sh
# RB-P18 — whether a run's recorded payload sha can be COMPARED with a payload sha some
# other writer recorded, read off a real run's rows and summary by a checker that does not
# import the module. The runner that produced
# docs/eval-data/2026-08-14-rbp18-payload-recipe.md.
#
#   sh docs/eval-data/2026-08-14-rbp18-payload-recipe.sh "$PWD" /tmp/rbp18
#
# BEFORE column:
#   git checkout 9ed1886 -- runtime-py/src/bantamkit/criticreplay.py
#   sh docs/eval-data/2026-08-14-rbp18-payload-recipe.sh "$PWD" /tmp/rbp18-before
#   git checkout 6b82c5d -- runtime-py/src/bantamkit/criticreplay.py   # by SHA, not HEAD
#   git diff HEAD --exit-code                                          # tree byte-exact
#
# Layer: Measurement. Statuses are /bin/sh's own $?, with no PYTEST_* key in the child's
# environment. RB-P28 is open, so the suite is NOT the evidence for this claim: the nodes
# in test_criticreplay.py are regression guards and this file is the measurement.
#
# WHAT IS BEING MEASURED. Two committed record families disagree on `payload_sha256` for
# the same request. The question is not "are they equal" — they are frozen and they are
# not — but "can a reader holding both DECIDE whether the requests differed". The answer
# is measured as: how many of the two frozen families a SINGLE run made today reproduces.
# One family reproduced means the other family's value still corresponds to nothing this
# tool can produce, and the reader is guessing. Two means the reader can place any frozen
# value in a named column.
#
# THE CHECKER IS INDEPENDENT OF THE THING IT CHECKS. It imports json and pathlib and never
# imports bantamkit. It reads the frozen values out of the committed artifacts, reads the
# fresh run's `--json` rows and `--summary`, and compares. It also normalizes the frozen
# `payload_sha256` shapes itself (str or list) rather than calling the module's reader, so
# the arity finding is not the module agreeing with itself.
#
# THE ONE PLACE THE RE-DERIVATION BLOCK DOES IMPORT THE MODULE, and why that is honest.
# The wire body cannot be rebuilt without the module's prompt rendering and schema
# instruction — those ARE the request. What that block must not do is trust the module's
# HASHING, and it does not: it calls json.dumps and hashlib itself, twice, and never calls
# _payload_sha or _payload_shas. The rendering is independently anchored anyway, by the
# rebuilt `prompt_sha256` equalling the committed 8fb6c984… on every cell — a field the
# block does not choose.
#
# THE CRITIC IS A HASH. rbp16_effect_probe.py is the shipped main() with the client
# constructor replaced by score = sha256(prompt|seed) % 11 — L2's harness, reused
# unchanged. The payload sha does not depend on the response, so the critic cannot affect
# what is measured here; it is used because it is the shipped CLI in a real process.
#
# NOTHING HERE INVENTS A CELL. The cells are the committed acceptance cells: the rubrics
# are `git:d2f78b7` and `git:e57f1a6`, the task prompt is the frozen asset, the answer is
# SA3's own `answer_replayed`, the model is SA3's own `model` and the seeds are the
# committed seeds. assets/ is not touched.
set -u
REPO=$1; WORK=$2
PY="$REPO/.venv/bin/python"; PROBE="$REPO/runtime-py/tests/rbp16_effect_probe.py"
rm -rf "$WORK"; mkdir -p "$WORK/transcripts"
cd "$REPO" || exit 1

DATA=docs/eval-data
SA3=$DATA/2026-08-11-sa3-14b-nav-prod-port-critic-replay.json
BAR=$DATA/2026-08-11-pb14-14b-nav-prod-port-perturbation.jsonl
A=git:d2f78b7:assets/rubrics/task-completion.yaml
C=git:e57f1a6:assets/rubrics/task-completion.yaml

# ---- the fact the whole fix rests on, re-derived here rather than cited ----
echo '## re-derivation: the two committed recipes, on all six (variant, seed) cells'
PYTHONPATH="$REPO/runtime-py/src" "$PY" - "$REPO" <<'PY'
import hashlib, json, pathlib, subprocess, sys
repo = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(repo / "runtime-py/src"))
from bantamkit.agent import response_format_for
from bantamkit.contract import schema_instruction
from bantamkit.criticreplay import Case, _parse_rubric, render_prompt

data = repo / "docs/eval-data"
sa3 = json.loads((data / "2026-08-11-sa3-14b-nav-prod-port-critic-replay.json").read_text())
bar = [json.loads(x) for x in
       (data / "2026-08-11-pb14-14b-nav-prod-port-perturbation.jsonl").read_text().splitlines()]
identity = {(r["variant"], r["repeat"]): r for r in bar if r["point"] == "identity"}
h = lambda s: hashlib.sha256(s.encode()).hexdigest()

print(f"{'variant':12} {'r':>1} {'seed':>11} {'prompt':13} {'ensure_ascii':13} "
      f"{'+sort_keys':13} ==bar ==SA3")
allok = True
for ref, label in (("d2f78b7", "A-asfiled"), ("e57f1a6", "C-attempted")):
    raw = subprocess.run(["git", "-C", str(repo), "show",
                          f"{ref}:assets/rubrics/task-completion.yaml"],
                         capture_output=True, text=True, check=True).stdout
    rubric = _parse_rubric(raw, f"git:{ref}")
    for repeat, seed in ((0, 2331795949), (1, 4094558621), (2, 634446002)):
        case = Case(task=sa3["task"], repeat=repeat, seed=seed,
                    prompt=sa3["task_prompt"], output=sa3["answer_replayed"])
        prompt = render_prompt(rubric.prompt, case)
        # The payload the module puts on the wire, assembled here and hashed HERE.
        payload = {
            "model": sa3["model"],
            "messages": [{"role": "system", "content": schema_instruction(rubric.schema)},
                         {"role": "user", "content": prompt}],
            "seed": seed,
            "response_format": response_format_for(rubric.schema),
        }
        ins = h(json.dumps(payload, ensure_ascii=False))
        srt = h(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        row = identity.get((label, repeat))
        frozen_sa3 = sorted({s for e in sa3["replay_verdicts"]
                             if e["ref"] == ref and e["repeat"] == repeat
                             for s in ([e["payload_sha256"]]
                                       if isinstance(e["payload_sha256"], str)
                                       else e["payload_sha256"])})
        a = row is not None and row["payload_sha256"] == ins
        b = frozen_sa3 == [srt]
        allok = allok and a and b and row["prompt_sha256"] == h(prompt)
        print(f"{label:12} {repeat:1} {seed:11} {h(prompt)[:12]:13} {ins[:12]:13} "
              f"{srt[:12]:13} {str(a):5} {b}")
print(f"all six cells reproduce, prompt_sha256 included: {allok}")
PY
echo

echo '## census: what SHAPE `payload_sha256` is, over every committed artifact'
"$PY" - "$REPO" <<'PY'
import collections, json, pathlib, sys
data = pathlib.Path(sys.argv[1]) / "docs/eval-data"
census = collections.Counter()
files = collections.defaultdict(set)


def walk(obj, name):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "payload_sha256":
                census[type(v).__name__] += 1
                files[type(v).__name__].add(name)
            walk(v, name)
    elif isinstance(obj, list):
        for x in obj:
            walk(x, name)


for p in sorted(data.glob("*")):
    if p.is_dir() or p.suffix not in (".json", ".jsonl"):
        continue
    text = p.read_text(errors="ignore")
    if "payload_sha256" not in text:
        continue
    if p.suffix == ".jsonl":
        for line in text.splitlines():
            if line.strip():
                walk(json.loads(line), p.name)
    else:
        walk(json.loads(text), p.name)
for shape in sorted(census):
    print(f"{shape:5} {census[shape]:5} occurrences in {len(files[shape]):2} artifact(s)")
print("distinct shapes under ONE field name:", len(census))
PY
echo

# ---- the runs ----
BK_OUT="$WORK/out.txt"; BK_ERR="$WORK/err.txt"
export BK_OUT BK_ERR
run() {  # $1 label, $2 repeat under test, rest = argv after the probe
  L=$1; R=$2; shift 2
  S="$WORK/$L-summary.json"; J="$WORK/$L-rows.jsonl"; rm -f "$S" "$J"
  env -u PYTEST_CURRENT_TEST -u PYTEST_VERSION PYTHONPATH="$REPO/runtime-py/src" \
    /bin/sh -c '{ "$@" >"$BK_OUT" 2>"$BK_ERR"; echo "status=$?"; }' sh \
    "$PY" "$PROBE" --summary "$S" --json "$J" "$@" > "$WORK/st.txt"
  ST=$(sed -n 's/^status=//p' "$WORK/st.txt")
  cp "$BK_ERR" "$WORK/$L-err.txt"
  "$PY" - "$L" "$ST" "$R" "$S" "$J" "$REPO" "$WORK/$L-err.txt" <<'PY'
import json, pathlib, sys
label, status, repeat_s, summary_path, rows_path, repo_s, err_path = sys.argv[1:8]
repeat = int(repeat_s)
repo = pathlib.Path(repo_s)
data = repo / "docs/eval-data"

# THE FROZEN VALUES, read from the committed artifacts by this checker. `payload_sha256`
# is normalized HERE, from its two shapes, rather than by the module's reader.
sa3 = json.loads((data / "2026-08-11-sa3-14b-nav-prod-port-critic-replay.json").read_text())
bar = [json.loads(x) for x in
       (data / "2026-08-11-pb14-14b-nav-prod-port-perturbation.jsonl").read_text().splitlines()]
REF = {"A-asfiled": "d2f78b7", "C-attempted": "e57f1a6"}


def shas(value):
    return (value,) if isinstance(value, str) else tuple(value)


bar_frozen = {(r["variant"], r["repeat"]): shas(r["payload_sha256"])
              for r in bar if r["point"] == "identity"}
sa3_frozen = {}
for entry in sa3["replay_verdicts"]:
    sa3_frozen.setdefault(entry["ref"], {}).setdefault(entry["repeat"], set()).update(
        shas(entry["payload_sha256"]))

rows_file, summary_file = pathlib.Path(rows_path), pathlib.Path(summary_path)
bar_hits = sa3_hits = cells = 0
recipes = identity_named = 0
labels = []
if rows_file.is_file():
    fresh = [r for r in (json.loads(x) for x in rows_file.read_text().splitlines())
             if r["point"] == "identity" and r["replay"] == 0 and r["repeat"] == repeat]
    for row in fresh:
        label_ = row["variant"]
        labels.append(label_)
        cells += 1
        if row.get("payload_sha256") in bar_frozen.get((label_, repeat), ()):
            bar_hits += 1
        canonical = row.get("payload_canonical_sha256", "")
        if canonical and canonical in sa3_frozen.get(REF.get(label_, ""), {}).get(repeat, set()):
            sa3_hits += 1
if summary_file.is_file():
    block = json.loads(summary_file.read_text()).get("payload_sha256_recipes", {})
    recipes = len(block.get("recipes", {}))
    identity_named = int(block.get("cross_record_identity") == "prompt_sha256")
if not cells and not recipes:
    labels = [pathlib.Path(err_path).read_text().strip().splitlines()[-1][:40] or "-"]
print(f"{label}|{status}|{cells}|{bar_hits}/{cells or 0}|{sa3_hits}/{cells or 0}|"
      f"{recipes}|{identity_named}|{','.join(sorted(set(labels))) or '-'}")
PY
  cd "$REPO" || exit 1
}

# One transcript per repeat, carrying SA3's own answer and the committed seed.
"$PY" - "$WORK" "$REPO" <<'PY'
import json, pathlib, sys
work, repo = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
sa3 = json.loads((repo / "docs/eval-data"
                  / "2026-08-11-sa3-14b-nav-prod-port-critic-replay.json").read_text())
for repeat, seed in ((0, 2331795949), (1, 4094558621)):
    (work / "transcripts" / f"critique--nav-prod-port--r{repeat}.json").write_text(json.dumps({
        "task": sa3["task"], "config": "critique", "repeat": repeat, "passed": True,
        "outcome": "pass", "seed": seed, "output": sa3["answer_replayed"], "messages": [],
    }))
PY

MODEL=$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['model'])" "$SA3")
OK="--transcripts $WORK/transcripts --base-url http://x --model $MODEL"

echo 'case|status|cells|reproduces bar-frozen|reproduces SA3-frozen|recipes named|identity named|variants'
run 'E1-the-spec-cell'   0 --rubric "A-asfiled=$A" $OK
run 'E2-both-variants'   0 --rubric "A-asfiled=$A" --rubric "C-attempted=$C" $OK
# CONTROL. A checker that reported "reproduced" for any run would be measuring nothing.
# r1 is a different seed, so it must reproduce r1's frozen pair and NOT r0's: the run
# below is scored against r1 (and the same run scored against r0 is the line after it).
run 'C1-CONTROL-r1-vs-r1' 1 --rubric "A-asfiled=$A" $OK
"$PY" - "$WORK/C1-CONTROL-r1-vs-r1-rows.jsonl" "$REPO" <<'PY'
import json, pathlib, sys
rows_file, repo = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
data = repo / "docs/eval-data"
bar = [json.loads(x) for x in
       (data / "2026-08-11-pb14-14b-nav-prod-port-perturbation.jsonl").read_text().splitlines()]
sa3 = json.loads((data / "2026-08-11-sa3-14b-nav-prod-port-critic-replay.json").read_text())
r0_bar = next(r["payload_sha256"] for r in bar
              if r["point"] == "identity" and r["variant"] == "A-asfiled" and r["repeat"] == 0)
r0_sa3 = {s for e in sa3["replay_verdicts"] if e["ref"] == "d2f78b7" and e["repeat"] == 0
          for s in ([e["payload_sha256"]] if isinstance(e["payload_sha256"], str)
                    else e["payload_sha256"])}
hits = 0
if rows_file.is_file():
    for row in (json.loads(x) for x in rows_file.read_text().splitlines()):
        if row["point"] == "identity" and row["replay"] == 0 and row["repeat"] == 1:
            hits += int(row.get("payload_sha256") == r0_bar)
            hits += int(row.get("payload_canonical_sha256", "") in r0_sa3
                        and bool(row.get("payload_canonical_sha256", "")))
print(f"C2-CONTROL-r1-vs-r0|-|1|{hits} of 2 must be 0|{hits} of 2 must be 0|-|-|a seed that "
      "differs must not reproduce r0")
PY
echo

echo '## the still-open arity defect, unchanged by this fix and measured on both columns'
"$PY" - "$REPO" <<'PY'
import json, pathlib, sys
data = pathlib.Path(sys.argv[1]) / "docs/eval-data"
sa3 = json.loads((data / "2026-08-11-sa3-14b-nav-prod-port-critic-replay.json").read_text())
bar = [json.loads(x) for x in
       (data / "2026-08-11-pb14-14b-nav-prod-port-perturbation.jsonl").read_text().splitlines()]
row = next(r for r in bar
           if r["point"] == "identity" and r["variant"] == "A-asfiled" and r["repeat"] == 0)
entry = next(e for e in sa3["replay_verdicts"] if e["ref"] == "d2f78b7" and e["repeat"] == 0)
print(f"bar type={type(row['payload_sha256']).__name__:4}  "
      f"SA3 type={type(entry['payload_sha256']).__name__:4}  "
      f"naive == -> {row['payload_sha256'] == entry['payload_sha256']}")
lengths = {len(e["payload_sha256"]) for e in sa3["replay_verdicts"]}
print(f"SA3 list lengths across all {len(sa3['replay_verdicts'])} entries: {sorted(lengths)} "
      "-- the cardinality IS that file's claim, so it may not be flattened away")
PY
