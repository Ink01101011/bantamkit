#!/usr/bin/env python3
"""AS-4's gate: does ranking documents beat naming the file, on this machine's real work?

Builds NO retriever, NO scorer, NO index. It measures two things:

  Arm N (naming, the baseline)  -- from the transcripts' own behaviour: how many tool
      calls an agent actually spent between a user prompt and opening a concrete file.

  Arm R's CEILING (no prototype) -- BM25 assigns a non-zero score only to documents
      sharing at least one query term, so `grep -l` for the union of the query's terms
      returns exactly BM25's non-zero-score set. Its recall is therefore an UPPER BOUND
      on any lexical ranker's recall at any k. If the bound is low, AS-4 is refuted
      without anything being built.

Rerun:  .venv/bin/python docs/eval-data/2026-09-10-job46-as4-probe.py <transcript-dir>
The query set is derived from the operator's own transcripts and is NOT committed --
see the .md beside this file for why. Aggregate numbers only.
"""
import collections
import glob
import json
import os
import re
import statistics as st
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TXDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/.claude/projects/-Users-kktest-Documents-Claude-Projects-bantamkit")

# --- injected blocks that are NOT user-typed text -----------------------------------
SR = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
CMD = re.compile(r"<(command-[a-z-]+|task-notification|local-command-[a-z-]+"
                 r"|user-prompt-submit-hook|bash-stdout|bash-stderr|bash-input)>.*?</\1>", re.DOTALL)
ET = re.compile(r"<(bash-stdout|bash-stderr|bash-input|command-[a-z-]+)\s*/?>")
BASHREAD = re.compile(r"(?:\bcat\b|\bsed -n\b|\bhead\b|\btail\b|\bless\b)"
                      r"[^|;&]*?((?:/|\./|[A-Za-z0-9_.-]+/)[A-Za-z0-9_./-]+\.[A-Za-z0-9]+)")
TOK = re.compile(r"[a-z0-9]+")          # memory_recall's _tokens(), verbatim: ASCII-only
THAI = re.compile(r"[฀-๿]")
THRUN = re.compile(r"[฀-๿]+")
STOP = {"the", "a", "an", "of", "to", "in", "on", "and", "or", "is", "are",
        "be", "it", "this", "that", "for", "with", "as", "at", "by", "from"}


def clean(t):
    t = SR.sub(" ", t); t = CMD.sub(" ", t); t = ET.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def corpus():
    out = subprocess.run(
        ["find", ".", "(", "-name", "node_modules", "-o", "-name", ".venv", "-o",
         "-name", ".git", "-o", "-name", "__pycache__", "-o", "-name", "dist", "-o",
         "-name", ".pytest_cache", "-o", "-name", ".ruff_cache", ")", "-prune", "-o",
         "-type", "f", "-print"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False).stdout
    return [l[2:] for l in out.split("\n") if l.startswith("./")]


def pairs():
    """A discovery query = a user-typed prompt whose next concrete act was opening a file.
    The ground-truth target is that file -- chosen by the transcript, not by the author."""
    res, stats = [], collections.Counter()
    for fp in sorted(glob.glob(os.path.join(TXDIR, "*.jsonl"))):
        recs = []
        with open(fp, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        recs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # a truncated tail line is not a user turn
        stats["lines"] += len(recs)

        def isu(o):
            if o.get("type") != "user" or o.get("isMeta"): return False
            c = (o.get("message") or {}).get("content")
            if isinstance(c, str): return True
            if isinstance(c, list):
                return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
            return False

        for i, o in enumerate(recs):
            if not isu(o): continue
            stats["user_turns"] += 1
            c = (o.get("message") or {}).get("content")
            text = clean(c if isinstance(c, str) else "\n".join(
                b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"))
            if not text or "This session is being continued" in text[:100]: continue
            stats["typed"] += 1
            calls, tgt = 0, None
            for j in range(i + 1, len(recs)):
                n = recs[j]
                if isu(n): break
                if n.get("type") != "assistant": continue
                for b in ((n.get("message") or {}).get("content") or []):
                    if not isinstance(b, dict) or b.get("type") != "tool_use": continue
                    inp, nm = b.get("input") or {}, b.get("name")
                    calls += 1
                    if nm in ("Read", "Edit", "Write") and isinstance(inp.get("file_path"), str):
                        tgt = inp["file_path"]
                    elif nm == "Bash" and isinstance(inp.get("command"), str):
                        m = BASHREAD.search(inp["command"])
                        if m: tgt = m.group(1)
                    if tgt: break
                if tgt: break
            if tgt:
                stats["discovery"] += 1
                res.append({"query": text, "target": tgt, "calls_to_open": calls})
    return res, stats


def main():
    files = corpus(); fset = set(files)
    mem = os.path.expanduser(
        "~/.claude/projects/-Users-kktest-Documents-Claude-Projects-bantamkit/memory")
    P, stats = pairs()
    print(f"transcripts {len(glob.glob(os.path.join(TXDIR,'*.jsonl')))} files, "
          f"{stats['lines']} records")
    print(f"user turns {stats['user_turns']} -> user-typed {stats['typed']} "
          f"-> discovery queries {stats['discovery']}")
    print(f"corpus C1 = {len(files)} working-tree files")

    def cls(t):
        if t.startswith(("/tmp", "/private/tmp")) or "/scratchpad" in t: return "transient"
        rel = t[len(REPO) + 1:] if t.startswith(REPO + "/") else t.lstrip("./")
        if rel in fset: return "repo"
        if t.startswith(mem): return "memory"
        return "outside" if os.path.isabs(t) else "gone"

    thai = sum(1 for x in P if THAI.search(x["query"]))
    print(f"queries containing Thai: {thai}/{len(P)} = {100*thai/len(P):.1f}%")

    # ---- Arm N: the naming baseline, measured from real behaviour -------------------
    n = [x["calls_to_open"] for x in P]
    print(f"\nARM N (naming): tool calls prompt->open  median {st.median(n):g}  "
          f"mean {st.mean(n):.2f}  max {max(n)}")
    print(f"  opened on the first tool call: {sum(1 for v in n if v==1)}/{len(n)} = "
          f"{100*sum(1 for v in n if v==1)/len(n):.1f}%   <=3 calls: "
          f"{100*sum(1 for v in n if v<=3)/len(n):.1f}%")

    # ---- Arm R's ceiling: grep-any-term over the same corpus ------------------------
    rows = []
    for x in P:
        rel = (x["target"][len(REPO) + 1:] if x["target"].startswith(REPO + "/")
               else x["target"].lstrip("./"))
        k = cls(x["target"])
        toks = [t for t in set(TOK.findall(x["query"].lower())) if len(t) >= 2 and t not in STOP]
        cand, hit = set(), None
        if k == "repo":
            if toks:
                pat = "|".join(rf"\b{re.escape(t)}\b" for t in toks)
                r = subprocess.run(
                    ["grep", "-l", "-i", "-E", pat, "--"] + files, cwd=REPO,
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", check=False)
                cand = {l for l in r.stdout.splitlines() if l in fset}
            hit = rel in cand
        runs = [t for t in THRUN.findall(x["query"]) if len(t) >= 3]
        bridge = None
        if k == "repo" and runs:
            try:
                with open(os.path.join(REPO, rel), encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
                bridge = any(t in body for t in runs)
            except OSError:
                bridge = False  # target vanished between enumeration and read
        rows.append({"class": k, "ntok": len(toks), "cand": len(cand), "hit": hit,
                     "bridge": bridge, "thai_runs": len(runs)})

    print("\ntarget class:", dict(collections.Counter(r["class"] for r in rows)))
    rep = [r for r in rows if r["class"] == "repo"]
    h = [r for r in rep if r["hit"]]
    print("\nARM R CEILING (grep-any-term recall, upper bound on any lexical ranker)")
    print(f"  {len(h)}/{len(rep)} = {100*len(h)/len(rep):.1f}%   "
          f"zero ASCII tokens: {sum(1 for r in rep if r['ntok']==0)} "
          f"({100*sum(1 for r in rep if r['ntok']==0)/len(rep):.1f}%)")
    print(f"  ASCII tokens per query: median {st.median([r['ntok'] for r in rep]):g}")
    if h:
        ch = [r["cand"] for r in h]
        print(f"  candidate set on the hits: median {st.median(ch):.0f} "
              f"({100*st.median(ch)/len(files):.1f}% of corpus)  max {max(ch)} "
              f"({100*max(ch)/len(files):.1f}%)")
    br = [r for r in rep if r["thai_runs"]]
    if br:
        print(f"\nTHAI BRIDGE: {len(br)}/{len(rep)} queries carry a Thai run >=3 chars; "
              f"{sum(1 for r in br if r['bridge'])} ({100*sum(1 for r in br if r['bridge'])/len(br):.1f}%) "
              f"have it present in their target file")
    print(f"\nEND-TO-END: {len(h)}/{len(P)} = {100*len(h)/len(P):.1f}% of real discovery "
          f"queries are even reachable by lexical retrieval over this corpus")


if __name__ == "__main__":
    main()
