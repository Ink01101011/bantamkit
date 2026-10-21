"""J72-28 (#207 amendment 3, plan Task 4, Q10): the PRODUCT's inject reproduces the probe's G6 lists.

Not a look: nothing is scored. The product under test is the bantamkit-207q worktree (asserted).

Modes
  load  write every frozen fact's J72-19 queries (th + en) into the product sidecar of the store copy that holds it,
        `queries.write_entries(queries.sidecar_path(Path.home(), store.root), {name: (th + en, fact_sha(file))})`,
        keyed by `gen_kw.key` over the file (probe20.py's fmap). Asserts: every q2d key lands in a frozen store; no
        name in one store gets two different query lists; every pooled row the product resolves to a file with a q2d
        row reads back exactly that row's queries from the sidecar.
  dev   for the 60 dev prompts: head = prompt + "\\n" + prev1 when len(prompt) < 80 and prev1 (prev1 = J72-12 prev
        [-1][:500]), else None; `Memory.layered_for_eval(...).inject_candidates(prompt, head=head)` must equal
        probe20 `inject["G6-G5-l1.0"]` (cache/J72-20-results.json) on 60/60. Then the product's own
        `hookadapter._previous_prompt(<transcript>, prompt)` (read-only on ~/.claude/projects) is compared to
        J72-12's prev1, per prompt, with a disagreement class (never tuned on).
  gold  append the reproduction line to gold-looks.jsonl FIRST (refuses a second one), then the same on the 50 gold
        prompts with goldlook22.py's prev rule; must equal J72-22-gold-inject-G6.json on 50/50.
Every mode writes `$S/fid-<mode>.json` (private, scratch) for fidelity28.mjs: id, native, prompt, head, expected.
On a mismatch: prints the first differing id (never its text) and both name lists, exits 1.
usage: cd $S && $R/.venv/bin/python -I $P/J72-28-scripts/fidelity28.py {load|dev|gold} P S
"""
import json
import sys
import time
from pathlib import Path

MODE, P, S = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
assert MODE in ("load", "dev", "gold")
N = P.parent / "notes-job68"
PROJECTS = Path("/Users/kktest/.claude/projects")
LOOKS = P / "gold-looks.jsonl"
CUT, SHORT = 500, 80
WORKTREE = Path("/Users/kktest/Documents/Claude/Projects/bantamkit-207q")


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


if MODE == "gold":  # BEFORE any gold file is read (orchestrator ruling on Open question 6)
    looks = jl(LOOKS)
    if any(x.get("unit") == "J72-28" and x.get("kind") == "reproduction" for x in looks):
        raise SystemExit("J72-28 reproduction line already logged: refusing a second one")
    start = [x for x in looks if x.get("unit") == "J72-22" and x.get("event") == "look-start"]
    assert len(start) == 1, len(start)
    with LOOKS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "unit": "J72-28", "kind": "reproduction",
                            "of": "J72-22 look 6", "policy": start[0]["policy"],
                            "note": "fidelity check, not a look; scores nothing"}) + "\n")

import bantamkit

assert Path(bantamkit.__file__).resolve().is_relative_to(WORKTREE), bantamkit.__file__
sys.path.insert(0, str(P / "J72-11-scripts"))
sys.path.insert(0, str(WORKTREE))
import gen_kw
from bantamkit import hookadapter
from bantamkit.memory import queries
from bantamkit.memory.component import Memory
from bantamkit.memory.native import NativeStore
from bantamkit.memory.retrieval import query_terms

stores = S / "stores"
slug_list = gen_kw.slugs(stores, P / "dev-prompts.jsonl")
fmap = {}
for layer, p, name, desc, kws, body in gen_kw.facts(stores, slug_list):
    fmap[str(p.resolve())] = (layer, name, gen_kw.key(name, desc, kws, body), p)
Q2D = {}
for q in sorted(P.glob("cache/J72-19-q2d.q*.jsonl")):
    for r in jl(q):
        assert r["key"] not in Q2D, r["key"]
        Q2D[r["key"]] = r
mems = {}


def mem(nk):
    if nk not in mems:
        d = stores / "automem" / nk if nk else None
        mems[nk] = Memory.layered_for_eval(project=stores / "project", profile=stores / "profile", engine="v2",
                                           native=d if d is not None and d.is_dir() else None)
    return mems[nk]


def rows_of(m):  # every row the product pools, resolved to (store root, name, source)
    out = []
    shadow = set()
    for _, store, _ in m._layers:
        pool = (store.pool(query_terms("x"), skipped=[], shadow=shadow, every_row=True)
                if isinstance(store, NativeStore) else store.pool(query_terms("x"), skipped=[], every_row=True))
        if not isinstance(store, NativeStore):
            shadow.update(pool.all_names())
        for j in range(len(pool.names)):
            f = store.resolve(pool, j)
            out.append((str(store.root), pool.names[j], str(f.source) if f and f.source else None))
    return out


if MODE == "load":
    roots = {"project": mem("")._layers[0][1].root, "profile": mem("")._layers[1][1].root}
    for s in slug_list:
        roots[f"native:{s}"] = mem(s)._layers[-1][1].root
    entries, landed, clash, clash_keys = {}, set(), {}, set()
    for src, (layer, name, k, p) in fmap.items():
        if k not in Q2D:
            continue
        qs = Q2D[k]["th"] + Q2D[k]["en"]
        e = entries.setdefault(layer, {})
        if name in e and e[name][0] != qs:  # Open question 8: two files, one name, one sidecar entry
            clash[layer] = clash.get(layer, 0) + 1
            clash_keys.add(k)
            continue
        e[name] = (qs, queries.fact_sha(p))
        landed.add(k)
    for layer, e in entries.items():
        queries.write_entries(queries.sidecar_path(Path.home(), roots[layer]), e)
    readback = {"rows": 0, "rows_src_with_q2d": 0, "rows_sidecar_equal": 0, "rows_no_src": 0, "rows_clash_key": 0}
    for nk in [""] + slug_list:
        m = mem(nk)
        sides = {str(st.root): queries.read_sidecar(queries.sidecar_path(Path.home(), st.root)) for _, st, _ in
                 m._layers}
        for root, name, src in rows_of(m):
            readback["rows"] += 1
            hit = fmap.get(str(Path(src).resolve())) if src else None
            readback["rows_no_src"] += src is None
            if hit and hit[2] in Q2D:
                readback["rows_src_with_q2d"] += 1
                readback["rows_clash_key"] += hit[2] in clash_keys
                readback["rows_sidecar_equal"] += sides[root].get(name) == Q2D[hit[2]]["th"] + Q2D[hit[2]]["en"]
    cov = {"q2d_rows": len(Q2D), "q2d_keys_landed": len(landed), "name_clashes": clash,
           "sidecars": {k: len(v) for k, v in sorted(entries.items())},
           "sidecar_files": len(list((Path.home() / ".bantamkit" / queries.QUERIES_DIR).glob("*.json"))), **readback}
    print("LOAD", json.dumps(cov))
    # every q2d key lands, except a clash key; a clash key must not be a row the product pools
    assert cov["q2d_keys_landed"] + len(clash_keys - landed) == len(Q2D), cov
    assert readback["rows_clash_key"] == 0, readback
    assert readback["rows_sidecar_equal"] == readback["rows_src_with_q2d"], readback
    sys.exit(0)

# ---------------- dev / gold: the product's inject vs the probe's G6 lists ----------------
rows = json.loads((P / ("cache/dev-rows.json" if MODE == "dev" else "cache/rows.json")).read_text(encoding="utf-8"))
items = {it["key"]: it for it in rows["items"] if MODE == "dev" or it["set"] == "gold"}
assert all(it["native"] == "" or it["native"] in slug_list for it in items.values())
transcript = {}
if MODE == "dev":
    qs = jl(P / "dev-prompts.jsonl")
    prev = {r["id"]: r["prev"] for r in jl(P / "cache/J72-12-prev.jsonl")}
    ref = {int(k): v for k, v in
           json.loads((P / "cache/J72-20-results.json").read_text(encoding="utf-8"))["inject"]["G6-G5-l1.0"].items()}
    for r in qs:
        transcript[r["id"]] = PROJECTS / r["project"] / f"{r['session']}.jsonl"
else:
    sys.path.insert(0, str(P / "J72-22-scripts"))
    qs = jl(N / "gold-labels.jsonl")
    silver = jl(N / "silver.jsonl")
    slugs = json.loads((N / "session-slug.json").read_text(encoding="utf-8"))
    by_text = {}
    for r in silver:
        by_text.setdefault(r["prompt"], []).append(r["session"])
    from tools.eval.recall.mine_silver import _NOT_A_PROMPT, _user_text

    def prompts_of(t):  # goldlook22.py / J72-12 prev.py, verbatim in effect
        out = []
        for raw in t.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rr = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(rr, dict) or rr.get("isSidechain") or rr.get("isMeta") or rr.get("type") != "user":
                continue
            msg = rr.get("message") or {}
            if not isinstance(msg, dict):
                continue
            x = _user_text(msg)
            if x is None or not x.strip() or x.lstrip().startswith(_NOT_A_PROMPT):
                continue
            if str(rr.get("timestamp", "")) > "2026-10-15T12:11":
                continue
            out.append(x.strip())
        return out

    prev = {}
    for r in qs:
        ss = by_text.get(r["prompt"], [])
        prev[r["id"]] = []
        if not ss:
            continue
        t = PROJECTS / slugs.get(ss[0], "") / f"{ss[0]}.jsonl"
        if not t.is_file():
            continue
        transcript[r["id"]] = t
        ps = prompts_of(t)
        if r["prompt"] in ps:
            prev[r["id"]] = ps[:ps.index(r["prompt"])]
    ref = {int(k): v for k, v in json.loads((P / "J72-22-gold-inject-G6.json").read_text(encoding="utf-8")).items()}
assert set(ref) == {r["id"] for r in qs}, "reference ids differ"

same, first, head_used, dump = 0, None, 0, []
agree = {}


def is_prompt(raw, prompt):  # the eval's main-chain prompt test on one record, equal to `prompt` stripped
    try:
        rr = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(rr, dict) or rr.get("isSidechain") or rr.get("isMeta") or rr.get("type") != "user":
        return False
    msg = rr.get("message")
    x = hookadapter._user_text(msg) if isinstance(msg, dict) else None
    return isinstance(x, str) and x.strip() == prompt.strip() and not x.lstrip().startswith(hookadapter._NOT_A_PROMPT)
for r in qs:
    i, nk, prompt = r["id"], items[r["id"]]["native"], r["prompt"]
    p1 = prev[i][-1][:CUT] if prev[i] else ""
    head = f"{prompt}\n{p1}" if len(prompt) < SHORT and p1 else None
    head_used += head is not None
    got = [f.name for f in mem(nk).inject_candidates(prompt, head=head)]
    same += got == ref[i]
    if got != ref[i] and first is None:
        first = (i, got, ref[i])
    dump.append({"id": i, "native": nk, "prompt": prompt, "head": head, "expected": ref[i]})
    # the product's own head extraction (Open question 1), short prompts only, never used for scoring. The transcript
    # is cut where the hook would have read it: just before the prompt's first main-chain record ("before": the host
    # has not written it yet) and just after it ("after": it has). The whole file is also read, for reference only
    # (the session went on past the prompt, so its tail is not what the hook saw).
    if len(prompt) < SHORT and i in transcript and transcript[i].is_file():
        lines = transcript[i].read_bytes().split(b"\n")
        k = next((j for j, ln in enumerate(lines) if is_prompt(ln, prompt)), None)
        views = {"whole": transcript[i]}
        if k is not None:
            for tag, cut in (("before", k), ("after", k + 1)):
                t = S / "cleantmp" / f"cut-{tag}.jsonl"
                t.write_bytes(b"\n".join(lines[:cut]) + b"\n")
                views[tag] = t
        for tag, t in views.items():
            a = agree.setdefault(tag, {"compared": 0, "equal": 0, "both_empty": 0, "classes": {}})
            mine = hookadapter._previous_prompt(str(t), prompt)[:CUT]
            a["compared"] += 1
            if mine == p1:
                a["equal"] += 1
                a["both_empty"] += not mine
                continue
            size = t.stat().st_size
            if not p1:
                c = "eval_none_product_some"
            elif not mine:
                # where the eval's previous prompt record starts, in bytes, against the tail's first byte
                cut_lines = t.read_bytes().split(b"\n")
                offs, o = [], 0
                for ln in cut_lines:
                    offs.append(o)
                    o += len(ln) + 1
                at = [offs[j] for j, ln in enumerate(cut_lines) if is_prompt(ln, prev[i][-1])]
                beyond = bool(at) and at[-1] < size - hookadapter.TAIL_BYTES
                c = "product_none_prev_beyond_tail" if beyond else "product_none_other"
            elif mine in [x[:CUT] for x in prev[i]]:
                c = "product_took_an_earlier_prompt"
            else:
                c = "product_took_a_prompt_the_eval_does_not_list"
            a["classes"][c] = a["classes"].get(c, 0) + 1
        agree["no_cut_found"] = agree.get("no_cut_found", 0) + (k is None)
        if "before" in views:  # informational: the inject with the product's own head, never a gate
            mh = hookadapter._head_query(prompt, str(views["before"]))
            g2 = [f.name for f in mem(nk).inject_candidates(prompt, head=mh)]
            agree["inject_equal_with_product_head_short"] = agree.get("inject_equal_with_product_head_short", 0) + (
                g2 == ref[i])
(S / f"fid-{MODE}.json").write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")
print(MODE.upper(), json.dumps({"prompts": len(qs), "inject_equal": same, "head_used": head_used,
                                "prev_agreement": agree}))
if first is not None:
    print("FIRST MISMATCH id", first[0], "product", first[1], "probe", first[2])
    sys.exit(1)
