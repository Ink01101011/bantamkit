"""J72-11 step 1: bilingual (Thai + English) keywords per fact, written from the fact's own text only.

Input per fact: name, description, current keywords, body (body cut to BODY_MAX chars). Never a prompt.
Model: local ollama, temperature 0, seed 0, JSON format, fixed PROMPT below. Cache: one JSONL row per
(name, sha1 of the fact text, model), appended as each fact finishes, so a rerun resumes.
usage: .venv/bin/python -I gen_kw.py STORES_DIR CACHE.jsonl MODEL DEV_PROMPTS.jsonl [--limit N] [--only name,name]
STORES_DIR holds project/facts, profile/facts, automem/<slug>/ (frozen copies; read only).
"""
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

import yaml

OLLAMA = "http://127.0.0.1:11434/api/chat"
BODY_MAX = 2000
PROMPT = """You write search keywords for one note in a developer's personal memory store.
The developer is a Thai speaker who asks questions in Thai, often mixed with English technical words.
Read the note and write the keywords a person would type to find this note later.

Rules:
- Write 5 to 12 English keywords or short phrases (1 to 4 words each).
- Write 5 to 12 Thai keywords or short phrases (natural Thai, as a Thai developer would type them; keep
  English technical terms such as product names, file names or commands in English inside the Thai phrase
  when a Thai speaker would).
- Cover the topic, synonyms, and how a user would ask about it.
- Use only what the note says. Do not invent facts.
- Answer with JSON only: {"en": ["..."], "th": ["..."]}

NOTE
name: {name}
description: {description}
keywords: {keywords}
body:
{body}
"""


def slugs(stores: Path, dev_prompts: Path):
    """The auto-memory dirs the dev prompts reach (J72-5 dev_extract's native_of_slug), sorted."""
    ps = {json.loads(x)["project"] for x in dev_prompts.read_text(encoding="utf-8").splitlines() if x.strip()}
    return sorted(s for s in ps if s and (stores / "automem" / s).is_dir())


def facts(stores: Path, slug_list):
    dirs = [("project", stores / "project/facts"), ("profile", stores / "profile/facts")]
    dirs += [(f"native:{s}", stores / "automem" / s) for s in slug_list]
    for layer, d in dirs:
        for p in sorted(d.glob("*.md")):
            if p.name == "MEMORY.md":
                continue
            text = p.read_text(encoding="utf-8")
            try:
                _, front, body = text.split("---\n", 2)
                meta = yaml.safe_load(front)
            except (ValueError, yaml.YAMLError):
                continue
            if not isinstance(meta, dict) or not isinstance(meta.get("name"), str):
                continue
            desc = meta.get("description")
            if not isinstance(desc, str):
                desc = str((meta.get("metadata") or {}).get("description", "")) if isinstance(
                    meta.get("metadata"), dict) else ""
            kws = meta.get("keywords") if isinstance(meta.get("keywords"), list) else []
            yield layer, p, meta["name"], desc, [str(k) for k in kws], body.strip()


def key(name, desc, kws, body):
    h = hashlib.sha1(json.dumps([name, desc, kws, body], ensure_ascii=False).encode()).hexdigest()
    return f"{name}\t{h}"


def ask(model, text):
    req = json.dumps({"model": model, "stream": False, "format": "json",
                      "options": {"temperature": 0, "seed": 0, "num_ctx": 8192},
                      "messages": [{"role": "user", "content": text}]}).encode()
    r = urllib.request.Request(OLLAMA, data=req, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=600) as f:
        return json.loads(f.read())["message"]["content"]


def clean(xs):
    out, seen = [], set()
    for x in xs if isinstance(xs, list) else []:
        if isinstance(x, str) and (s := " ".join(x.split())) and s.lower() not in seen and len(s) <= 80:
            seen.add(s.lower())
            out.append(s)
    return out[:12]


def main():
    stores, cache, model = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    sl = slugs(stores, Path(sys.argv[4]))
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    done = set()
    if cache.exists():
        for line in cache.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["key"], r["model"]))
    n = 0
    with cache.open("a", encoding="utf-8") as out:
        for layer, p, name, desc, kws, body in facts(stores, sl):
            if only is not None and name not in only:
                continue
            k = key(name, desc, kws, body)
            if (k, model) in done:
                continue
            if limit is not None and n >= limit:
                break
            text = (PROMPT.replace("{name}", name).replace("{description}", desc)
                    .replace("{keywords}", ", ".join(kws)).replace("{body}", body[:BODY_MAX]))
            t = time.time()
            raw = ask(model, text)
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                obj = {}
            row = {"key": k, "name": name, "layer": layer, "file": p.name, "model": model,
                   "en": clean(obj.get("en")), "th": clean(obj.get("th")), "raw_ok": bool(obj),
                   "ms": round((time.time() - t) * 1000)}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            done.add((k, model))
            n += 1
            print(n, layer, name, row["ms"], len(row["en"]), len(row["th"]), flush=True)


if __name__ == "__main__":
    main()
