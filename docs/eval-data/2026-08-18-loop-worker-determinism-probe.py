"""Does ollama's `seed` actually pin an LLM worker's output? A methodological probe.

U1 of job `compaction-in-the-loop`. **This is not the harness and it does not run the
goal task.** It exists to answer one question the bar of
`2026-08-18-loop-bar-preregistration.md` cannot answer by assumption:

    J2's null control was EXACTLY deterministic on all 22 outcome columns, and that
    single fact licensed every number it reported. J7's null control is an LLM doing
    work. Is it pinnable at all?

Invariant 9 handed to this job says "if the null control varies the harness is
nondeterministic and every delta is contaminated". Applied literally to an LLM that
rule kills the job on contact. It may not be ignored and it may not be waved away —
it has to be MEASURED and then either upheld or replaced in writing. This program is
the measurement.

WHAT IT DOES NOT DO
  * It never touches packnplan-mono, never opens a worktree, never runs a goal task.
  * It writes NOTHING unless `--write PATH` is given. Bare invocation prints and exits.
    (RB-P49: two committed field programs overwrite their own committed .jsonl and
    exit 0 under a bare invocation. The default mode here is read-only, and the
    destructive mode is the flagged one.)
  * It never reports a token count or a duration it did not read off the endpoint.
    ollama returns `prompt_eval_count`, `eval_count` and nanosecond durations per
    response; every number below is one of those or is derived from them and says so.

THE CONDITIONS, and why each is here rather than the obvious one
  A  temp=0, no seed          the shipped-default question: is greedy alone enough?
  B  temp=0, seed fixed       the claim under test
  C  temp=0.2, seed fixed     J2's summarizer temperature, seeded
  D  temp=0.2, no seed        the unpinned baseline; expected to vary, and if it does
                              NOT vary the probe is uninformative because the prompt
                              was too easy to be a discriminator (see NOTE-TAUTOLOGY)
  E  temp=0, seed fixed, but the model is UNLOADED between calls (`ollama stop`)
                              a long arm evicts the model; determinism that only holds
                              inside one resident load is not determinism for a run
  F  temp=0, seed fixed, LONG prompt (~4k tokens of filler)
                              batching/numerics degrade with prompt length, and the
                              arms of this job differ from each other precisely by
                              prompt length. Determinism measured only on a short
                              prompt would be measured off the axis that matters.

NOTE-TAUTOLOGY (RB-P47). Two signals are compared per condition and they are NOT two
transcriptions of one rule: `sha256(response)` and `eval_count`. An input that makes
them disagree: any two samples of the same length that differ in one token — sha
differs, eval_count matches. That case is reported explicitly as `sha-only`. And
condition D is the discriminator for the probe as a whole: if D does not vary, the
prompt cannot distinguish pinned from unpinned and the probe reports UNINFORMATIVE
rather than "seed works".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "http://127.0.0.1:11434"
RULE = "=" * 78

# A neutral prompt. Deliberately NOT the goal task (the brief forbids running it) and
# deliberately not trivial: a one-word answer would be pinned by the vocabulary rather
# than by the seed.
PROMPT = (
    "Write a TypeScript function `chunk<T>(xs: T[], n: number): T[][]` that splits an "
    "array into consecutive chunks of length n, with the final chunk shorter if the "
    "array does not divide evenly. Throw a RangeError if n is not a positive integer. "
    "Reply with the function and two sentences explaining the edge cases."
)

# ~4k tokens of filler for condition F. Generated arithmetically so it is reproducible
# from this file alone and carries no other project's text.
FILLER_UNIT = (
    "Line {i}: the null control is the same orchestration with compaction off, not the "
    "absence of orchestration; a floor and the statistic it gates share a grain.\n"
)


def long_prompt(lines: int = 220) -> str:
    body = "".join(FILLER_UNIT.format(i=i) for i in range(lines))
    return (
        "Below is a log. Ignore it entirely except to confirm you received it.\n\n"
        + body
        + "\n\n"
        + PROMPT
    )


def call(model: str, prompt: str, temperature: float, seed: int | None,
         num_predict: int, num_ctx: int) -> dict:
    options: dict = {
        "temperature": temperature,
        "num_predict": num_predict,
        "num_ctx": num_ctx,
    }
    if seed is not None:
        options["seed"] = seed
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options,
    }).encode()
    req = urllib.request.Request(
        ENDPOINT + "/api/generate", data=payload,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=900) as resp:
        body = json.loads(resp.read().decode())
    wall_s = time.monotonic() - t0
    text = body.get("response", "")
    return {
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "chars": len(text),
        # Read off the endpoint, never self-estimated (invariant 14).
        "prompt_eval_count": body.get("prompt_eval_count"),
        "eval_count": body.get("eval_count"),
        "total_duration_ns": body.get("total_duration"),
        "load_duration_ns": body.get("load_duration"),
        # Wall-clock measured by a monotonic clock around the HTTP call, not estimated.
        "wall_s": round(wall_s, 3),
    }


def unload(model: str) -> None:
    subprocess.run(["ollama", "stop", model], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ps_context() -> str:
    out = subprocess.run(
        ["ollama", "ps"], check=False, capture_output=True, text=True, encoding="utf-8"
    )
    return out.stdout.strip()


CONDITIONS = [
    # name, temperature, seed, unload_between, long
    ("A temp=0 no-seed      ", 0.0, None, False, False),
    ("B temp=0 seed=7       ", 0.0, 7, False, False),
    ("C temp=0.2 seed=7     ", 0.2, 7, False, False),
    ("D temp=0.2 no-seed    ", 0.2, None, False, False),
    ("E temp=0 seed=7 cold  ", 0.0, 7, True, False),
    ("F temp=0 seed=7 long  ", 0.0, 7, False, True),
]


def run_model(model: str, repeats: int, num_predict: int, num_ctx: int) -> dict:
    results: dict[str, list[dict]] = {}
    for name, temp, seed, cold, is_long in CONDITIONS:
        prompt = long_prompt() if is_long else PROMPT
        rows = []
        for r in range(repeats):
            if cold:
                unload(model)
            rows.append(call(model, prompt, temp, seed, num_predict, num_ctx))
            print(f"    {name} r{r} sha={rows[-1]['sha256'][:12]} "
                  f"eval={rows[-1]['eval_count']} prompt_eval="
                  f"{rows[-1]['prompt_eval_count']} wall={rows[-1]['wall_s']}s",
                  flush=True)
        results[name] = rows
    return results


def verdict(rows: list[dict]) -> str:
    shas = {r["sha256"] for r in rows}
    evals = {r["eval_count"] for r in rows}
    if len(shas) == 1 and len(evals) == 1:
        return "IDENTICAL"
    if len(shas) > 1 and len(evals) == 1:
        return f"sha-only ({len(shas)} distinct sha, 1 distinct eval_count)"
    return f"VARIES ({len(shas)} distinct sha, {len(evals)} distinct eval_count)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", nargs="+",
                    default=["qwen2.5:7b-instruct", "qwen2.5:14b-instruct"])
    ap.add_argument("--repeats", type=int, default=4)
    ap.add_argument("--num-predict", type=int, default=220)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--write", metavar="PATH", default=None,
                    help="write the rows as JSON to PATH. Absent = writes nothing.")
    args = ap.parse_args()

    print(RULE)
    print("SEED-DETERMINISM PROBE — ollama. Reads the endpoint's own counters only.")
    print(f"mode: {'write ' + args.write if args.write else '--- (writes nothing)'}")
    print(RULE)
    try:
        with urllib.request.urlopen(ENDPOINT + "/api/version", timeout=10) as r:
            ver = json.loads(r.read().decode())["version"]
    except (urllib.error.URLError, OSError) as exc:
        print(f"UNMEASURED — ollama endpoint unreachable: {exc}")
        return 2
    print(f"ollama version {ver}   repeats={args.repeats} "
          f"num_predict={args.num_predict} num_ctx={args.num_ctx}")

    all_rows: dict[str, dict] = {}
    for model in args.models:
        print(f"\n  model {model}")
        all_rows[model] = run_model(model, args.repeats, args.num_predict, args.num_ctx)

    print("\n" + RULE)
    print("VERDICTS")
    print(RULE)
    uninformative = []
    for model, res in all_rows.items():
        print(f"\n  {model}")
        for name in res:
            print(f"    {name}  {verdict(res[name])}")
        if verdict(res["D temp=0.2 no-seed    "]) == "IDENTICAL":
            uninformative.append(model)

    print("\n" + RULE)
    if uninformative:
        print("PROBE UNINFORMATIVE for: " + ", ".join(uninformative))
        print("  Condition D (unpinned) did not vary, so this prompt cannot")
        print("  distinguish pinned from unpinned. Nothing here licenses a claim that")
        print("  the seed did the pinning.")
    else:
        print("Condition D varied on every model: the prompt discriminates, so the")
        print("other conditions' IDENTICAL verdicts are about the settings, not the")
        print("prompt.")
    print(RULE)
    print("ollama ps at exit (CONTEXT column is the resident window, measured):")
    print(ps_context())

    if args.write:
        with open(args.write, "w", encoding="utf-8") as fh:
            json.dump({"ollama_version": ver, "args": vars(args),
                       "rows": all_rows}, fh, indent=2)
        print(f"\nwrote {args.write}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
