"""J72-17 step 1: mine usage events used(fact, turn) from the transcript corpus, read-only.

Prompt test = J72-12 prev.py / J72-16 ctx.py (mine_silver's _NOT_A_PROMPT/_user_text, main chain only), WITHOUT the
time cut, so turn boundaries are the same everywhere; the leakage rule in learn17.py filters by time. Top-level
transcripts only (<project>/<session>.jsonl), as dev_sample. A turn = the main-chain records from one prompt up to
the next prompt. Fact names = the union of the frozen stores' row names (cache/dev-rows.json natives).
  U1  a main-chain tool_use whose name ends with `memory_recall`, whose input query names the fact (bounded exact
      match) or whose tool_result names it in a recall header line `[<layer>] [<name>]`.
  U2  U1, or the name appears (bounded exact match) in the turn's assistant text blocks or any tool_use input.
  U3  U2 restricted to names in the turn's UserPromptSubmit hook_additional_context recall block
      (`[bantamkit recall ...` header, lines `[<layer>] [<name>] ...`).
Bounded exact match: the name, not preceded or followed by [A-Za-z0-9_-].
Each event row: session (file stem), sid (record sessionId), uuid, project, ts, prompt, u1/u2/u3 name lists, inj.
Also writes the dev prompts' timestamps (first occurrence, prev.py's position rule, the prompt record's timestamp).
usage: python -I mine17.py PROJECTS_DIR NOTES72 OUT_EVENTS.jsonl OUT_DEVTS.jsonl
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "/Users/kktest/Documents/Claude/Projects/bantamkit")
from tools.eval.recall.mine_silver import _NOT_A_PROMPT, _user_text

PROJECTS, P, OUT, OUTD = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
rows = json.loads((P / "cache/dev-rows.json").read_text(encoding="utf-8"))
NAMES = {r["name"] for v in rows["natives"].values() for r in v}
SLUGS = {n for n in NAMES if re.fullmatch(r"[A-Za-z0-9_-]+", n)}
ODD = [re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(n) + r"(?![A-Za-z0-9_-])") for n in sorted(NAMES - SLUGS)]
ODDN = sorted(NAMES - SLUGS)
TOK = re.compile(r"[A-Za-z0-9_-]+")
HDR = re.compile(r"^\[[^\]\n]+\] \[([^\]\n]+)\]", re.MULTILINE)


def names_in(text):
    out = set(TOK.findall(text)) & SLUGS
    for n, rx in zip(ODDN, ODD):
        if n in text and rx.search(text):
            out.add(n)
    return out


def is_prompt(rec):
    if not isinstance(rec, dict) or rec.get("isSidechain") or rec.get("isMeta") or rec.get("type") != "user":
        return None
    msg = rec.get("message") or {}
    if not isinstance(msg, dict):
        return None
    x = _user_text(msg)
    if x is None or not x.strip() or x.lstrip().startswith(_NOT_A_PROMPT):
        return None
    return x.strip()


def blocks(rec):
    c = (rec.get("message") or {}).get("content") if isinstance(rec.get("message"), dict) else None
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def result_text(b):
    c = b.get("content")
    if isinstance(c, str):
        s = c
    elif isinstance(c, list):
        s = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
    else:
        return ""
    try:  # MCP results arrive as {"result": "..."} JSON text
        j = json.loads(s)
        if isinstance(j, dict) and isinstance(j.get("result"), str):
            return j["result"]
    except (json.JSONDecodeError, ValueError):
        pass
    return s


def close(turn, out):
    if turn is None:
        return
    u1 = set(turn["u1"]) & NAMES
    u2 = (u1 | turn["u2"]) & NAMES
    inj = turn["inj"] & NAMES
    u3 = u2 & inj
    out.append({k: turn[k] for k in ("session", "sid", "uuid", "project", "ts", "prompt")} |
               {"u1": sorted(u1), "u2": sorted(u2), "u3": sorted(u3), "inj": sorted(inj)})


def mine(t, out):
    turn, recall_ids = None, set()
    for raw in t.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or rec.get("isSidechain"):
            continue
        x = is_prompt(rec)
        if x is not None:
            close(turn, out)
            turn = {"session": t.stem, "sid": rec.get("sessionId"), "uuid": rec.get("uuid"),
                    "project": t.parent.name, "ts": str(rec.get("timestamp", "")), "prompt": x,
                    "u1": set(), "u2": set(), "inj": set()}
            continue
        if turn is None:
            continue
        ty = rec.get("type")
        if ty == "assistant":
            for b in blocks(rec):
                if b.get("type") == "text":
                    turn["u2"] |= names_in(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    inp = json.dumps(b.get("input"), ensure_ascii=False)
                    turn["u2"] |= names_in(inp)
                    if str(b.get("name", "")).endswith("memory_recall"):
                        recall_ids.add(b.get("id"))
                        q = (b.get("input") or {}).get("query") if isinstance(b.get("input"), dict) else None
                        if isinstance(q, str):
                            turn["u1"] |= names_in(q)
        elif ty == "user":
            for b in blocks(rec):
                if b.get("type") == "tool_result" and b.get("tool_use_id") in recall_ids:
                    turn["u1"] |= set(HDR.findall(result_text(b)))
        elif ty == "attachment":
            a = rec.get("attachment") or {}
            if a.get("type") == "hook_additional_context":
                c = a.get("content")
                s = c if isinstance(c, str) else "\n".join(map(str, c or []))
                for part in s.split("\n\n"):
                    if part.startswith("[bantamkit recall"):
                        turn["inj"] |= set(HDR.findall(part))
    close(turn, out)


def first_ts(t, prompt):
    for raw in t.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and str(rec.get("timestamp", "")) <= "2026-10-15T12:11" and is_prompt(rec) == prompt:
            return str(rec["timestamp"]), rec.get("sessionId")
    raise AssertionError("dev prompt not found")


if __name__ == "__main__":
    ev = []
    for t in sorted(PROJECTS.glob("*/*.jsonl")):
        mine(t, ev)
    with OUT.open("w", encoding="utf-8") as f:
        for e in ev:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    dev = [json.loads(x) for x in (P / "dev-prompts.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    with OUTD.open("w", encoding="utf-8") as f:
        for r in dev:
            ts, sid = first_ts(PROJECTS / r["project"] / f"{r['session']}.jsonl", r["prompt"])
            f.write(json.dumps({"id": r["id"], "ts": ts, "sid": sid}) + "\n")
    st = {"turns": len(ev), "turns_with_inj": sum(1 for e in ev if e["inj"])}
    for u in ("u1", "u2", "u3"):
        st[u + "_turns"] = sum(1 for e in ev if e[u])
        st[u + "_pairs"] = sum(len(e[u]) for e in ev)
        st[u + "_facts"] = len({n for e in ev for n in e[u]})
    print(json.dumps(st))
