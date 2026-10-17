"""Build the judge pool for gold: per prompt, every name ANY engine view injects (pool-injections.json) that is not
already one of that prompt's 5 gold candidates (gold-candidates.jsonl). Writes pool-judge-targets.jsonl in the shape of
calib-F-targets.jsonl, candidates shuffled by random.Random(20261017) so position says nothing about the engine, and
copies calib-F-examples.jsonl to pool-judge-examples.jsonl byte for byte. Prompts with an empty pool get no row.
usage (from the repo root): python3 .shiftwork/notes-job68/J68-17-pool.py .shiftwork/notes-job68
Copy rule, reverse-engineered from calib-F-targets.jsonl and SELF-CHECKED below (every calib-F candidate rebuilt
identically): every stores/**/<name>.md (sorted path order, index.md excluded), description = the frontmatter
`description:` LINE with surrounding quotes stripped (a folded continuation is not read, as in the original), body =
text after the closing `---`, stripped, first 2000 chars; identical {description, body} copies collapsed."""
import glob, json, random, shutil, sys
from pathlib import Path
N = Path(sys.argv[1])

def copy_of(p):
    lines = open(p, encoding="utf-8").read().split("\n")
    end = lines.index("---", 1)
    desc = next(x[12:].strip().strip("'\"") for x in lines[1:end] if x.startswith("description:"))
    return {"description": desc, "body": "\n".join(lines[end + 1:]).strip()[:2000]}

files, by_fm = {}, {}
for p in sorted(glob.glob(str(N / "stores" / "**" / "*.md"), recursive=True)):
    if Path(p).name not in ("index.md", "MEMORY.md"):
        files.setdefault(Path(p).stem, []).append(p)
        head = open(p, encoding="utf-8").read().split("\n")[:40]
        fm = next((x[5:].strip().strip("'\"") for x in head if x.startswith("name:")), None)
        if fm:
            by_fm.setdefault(fm, []).append(p)

def copies(name):
    paths = files.get(name) or by_fm.get(name)
    if not paths:
        raise SystemExit(f"no store copy of {name}")
    out = []
    for p in paths:
        c = copy_of(p)
        if c not in out:
            out.append(c)
    return out

# self-check: the rule must rebuild calib-F-targets.jsonl's copies exactly
for line in open(N / "calib-F-targets.jsonl", encoding="utf-8"):
    for c in json.loads(line)["candidates"]:
        assert copies(c["name"]) == c["copies"], c["name"]

inj = json.load(open(N / "pool-injections.json", encoding="utf-8"))
cand = {r["id"]: set(r["candidates"]) for r in map(json.loads, open(N / "gold-candidates.jsonl", encoding="utf-8"))}
rng = random.Random(20261017)
rows, sizes = [], {}
for r in map(json.loads, open(N / "gold-labels.jsonl", encoding="utf-8")):
    i = r["id"]
    assert set(r["positives"]) <= cand[i], i
    pool = sorted({n for names in inj[str(i)].values() for n in names} - cand[i])
    rng.shuffle(pool)
    sizes[i] = len(pool)
    if pool:
        rows.append({"id": i, "prompt": r["prompt"], "candidates": [{"name": n, "copies": copies(n)} for n in pool]})
with open(N / "pool-judge-targets.jsonl", "w", encoding="utf-8") as f:
    for row in rows:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
shutil.copyfile(N / "calib-F-examples.jsonl", N / "pool-judge-examples.jsonl")
print(json.dumps({"total": sum(sizes.values()), "rows": len(rows), "per_id": sizes}))
