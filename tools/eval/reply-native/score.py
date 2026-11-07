"""Score the reply-native eval against the spec's predeclared bar (#292)."""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict

turns = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
labels = {(r["session_id"], r["turn"]): r for r in map(json.loads, open(sys.argv[2], encoding="utf-8"))}
by_arm: dict[str, list[dict]] = defaultdict(list)
for t in turns:
    t["label"] = labels[(t["session_id"], t["turn"])]
    by_arm[t["arm"]].append(t)


def thai(t):
    from bantamkit.replynative import classify
    return classify(t["prompt"]) == "th"


rows = {}
for arm, ts in by_arm.items():
    wrong = sum(not t["label"]["reply_lang_ok"] for t in ts) / len(ts)
    drift = sum(t["label"]["drift_vs_off"] == "wrong" for t in ts) / len(ts)
    th = [t for t in ts if thai(t)]
    judged = [t for t in th if t["label"]["thinking_english"] is not None]
    follow = (sum(t["label"]["thinking_english"] for t in judged) / len(judged)) if judged else None
    med_out_th = statistics.median(t["output_tokens"] for t in th) if th else None
    per_session = defaultdict(int)
    for t in ts:
        per_session[t["session_id"]] += (t["output_tokens"] or 0) + (t["input_tokens"] or 0) + (t["cache_read_input_tokens"] or 0)
    rows[arm] = {"wrong_lang": wrong, "drift_wrong": drift, "follow": follow,
                 "median_out_thai": med_out_th, "median_session_total": statistics.median(per_session.values())}
print(json.dumps(rows, indent=2))
bar = []
for a in ("A2", "A3"):
    r = rows[a]
    bar.append((f"{a} wrong-lang <= OFF and E", r["wrong_lang"] <= rows["OFF"]["wrong_lang"] and r["wrong_lang"] <= rows["E"]["wrong_lang"]))
    bar.append((f"{a} drift <= OFF", r["drift_wrong"] <= rows["OFF"]["drift_wrong"]))
    if any(x["follow"] is not None for x in rows.values()):
        bar.append((f"{a} follow >= 0.90", r["follow"] is not None and r["follow"] >= 0.90))
    else:
        # The transcripts carry no thinking text (only its signature), so measure 3 cannot be
        # judged; the plan drops it from the gate rather than inferring it from the reply.
        print(f"DROPPED {a} follow >= 0.90 (no thinking text in any transcript)")
    bar.append((f"{a} session total < G", r["median_session_total"] < rows["G"]["median_session_total"]))
    bar.append((f"{a} median Thai output < OFF", r["median_out_thai"] < rows["OFF"]["median_out_thai"]))
bar.append(("A2 beats E (wrong-lang lower, or equal with lower session total)",
            rows["A2"]["wrong_lang"] < rows["E"]["wrong_lang"]
            or (rows["A2"]["wrong_lang"] == rows["E"]["wrong_lang"]
                and rows["A2"]["median_session_total"] < rows["E"]["median_session_total"])))
for name, ok in bar:
    print(("PASS " if ok else "FAIL ") + name)
sys.exit(0 if all(ok for _, ok in bar) else 1)
