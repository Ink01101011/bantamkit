"""Differential: recall answers of one tree's runtime-py over random stores, one JSON line each.

    python diff_old_new.py <runtime-py/src> <stores-dir> <seed> <count>   (HOME, BANTAMKIT_INDEX_DIR set by caller)
Stores are generated deterministically from the seed (same files for both trees).
"""
import json, os, random, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from bantamkit.memory.store import MemoryStore
from bantamkit.memory.component import Memory
from bantamkit.memory.usage import UsageLedger

NOW = "2026-10-16T12:00:00Z"
MemoryStore.__init__.__defaults__  # noqa
_orig_init = MemoryStore.__init__
def _init(self, *a, **kw):
    kw.setdefault("now", lambda: NOW)
    _orig_init(self, *a, **kw)
MemoryStore.__init__ = _init

VOCAB = ["release", "tag", "context", "window", "budget", "fact", "lesson", "hook", "recall",
         "ปล่อยเวอร์ชัน", "กินบริบท", "อากาศ", "42", "7", "alpha", "beta", "gamma", "Café", "naïve",
         "SUPERSEDED", "CLOSED", "REFUTED", "release-tag", "日本語", "x", "the", "and"]
TYPES = ["project", "feedback", "user", "reference", "weird", "Project"]

def words(r, lo, hi):
    return " ".join(r.choice(VOCAB) for _ in range(r.randint(lo, hi)))

def make(root: Path, r: random.Random, n: int):
    (root / "facts").mkdir(parents=True, exist_ok=True)
    names = []
    for i in range(n):
        kind = r.random()
        if kind < 0.05:
            name = str(r.randint(1, 30)); nm = name  # numeric string name, quoted
            nm = f"'{name}'"
        elif kind < 0.08 and names:
            name = r.choice(names); nm = name  # duplicate name in a second file
        elif kind < 0.10:
            name = str(r.randint(1, 30)); nm = name  # loose: an int name
        else:
            name = "-".join(r.choice(["rel", "tag", "ctx", "win", "a", "b", "z", "é", "日"]) for _ in range(r.randint(1, 3))) + f"-{i}"
            nm = name
        names.append(name)
        desc = words(r, 0, 8)
        if r.random() < 0.15:
            desc = r.choice(["SUPERSEDED ", "CLOSED: ", "  REFUTED ", "CLOSEDé "]) + desc
        kws = [words(r, 1, 2) for _ in range(r.randint(0, 3))]
        kwtext = "keywords:\n" + "".join(f"- {json.dumps(k, ensure_ascii=False)}\n" for k in kws) if kws else ""
        text = (f"---\nname: {nm}\ndescription: {json.dumps(desc, ensure_ascii=False)}\ntype: {r.choice(TYPES)}\n"
                f"created: '2026-10-15'\nlinks: []\n{kwtext}---\n\nbody {i}\n")
        (root / "facts" / f"f{i:04d}-{r.randint(0,9)}.md").write_text(text, encoding="utf-8")
    return names

def main():
    src, base, seed, count = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
    home = Path(os.environ["HOME"])
    for c in range(count):
        r = random.Random(seed * 1000 + c)
        proj, prof = base / f"s{c}" / "proj", base / f"s{c}" / "prof"
        if not proj.exists():
            make(proj, r, r.randint(0, 40))
            make(prof, r, r.randint(0, 25))
        # usage: deterministic per store, appended by this runtime's own ledger
        ur = random.Random(seed * 7 + c)
        led = UsageLedger(home, proj)
        cand = [p.stem for p in (proj / "facts").glob("*.md")]
        for _ in range(ur.randint(0, 12)):
            nm = ur.choice(["rel-1", "tag-2", "a-3", "7", "x"] + [str(ur.randint(1, 30))])
            led.append(nm, ur.choice(["recall_hit", "body_read"]), f"2026-10-{ur.randint(1, 16):02d}T10:00:00Z")
        qr = random.Random(seed * 13 + c)
        for _ in range(6):
            q = words(qr, 1, 6)
            k = qr.choice([1, 3, 5, 8, 50])
            row = {"s": c, "q": q, "k": k}
            try:
                row["idx"] = [str(f.name) for f in MemoryStore(proj, create=False).recall(q, k=k, stamp=False)]
            except Exception as e:  # noqa
                row["idx"] = f"ERR {type(e).__name__}: {e}"
            slow = MemoryStore(proj, create=False); slow._indexed = lambda: None
            try:
                row["files"] = [str(f.name) for f in slow.recall(q, k=k, stamp=False)]
            except Exception as e:  # noqa
                row["files"] = f"ERR {type(e).__name__}: {e}"
            try:
                mem = Memory.layered_for_eval(proj, prof)
                row["all"] = [str(f.name) for f in mem.rank_all(q, 50)]
                row["inj"] = [str(f.name) for f in mem.inject_candidates(q)]
            except Exception as e:  # noqa
                row["all"] = f"ERR {type(e).__name__}: {e}"
            print(json.dumps(row, ensure_ascii=False), flush=True)

main()
