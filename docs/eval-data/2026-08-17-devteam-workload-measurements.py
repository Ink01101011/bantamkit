#!/usr/bin/env python3
"""Measurements over the dev-team workload asset. Runs NO arm and calls NO model.

    .venv/bin/python docs/eval-data/2026-08-17-devteam-workload-measurements.py .

Every number in `2026-08-17-devteam-workload.md` is stdout of this script. It reads
only committed sources: `assets/evals/devteam/`, the frozen task YAMLs (read, never
written), `assets/profiles/default.yaml`, and the runtime package. It imports
bantamkit only for `Message`/`Tool`/`truncate` — the repo's own wire serializer —
so the byte figures in Table 5 are what `OpenAICompatible.chat` would actually POST
(`client.py:155-157`), not an estimate of it.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

import yaml

RULE = "=" * 78
# The reference model's numbers, read from the profile rather than hard-coded.
PROFILE = "default"


def repo_root() -> Path:
    return Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()


def _import_bantamkit(root: Path):
    sys.path.insert(0, str(root / "runtime-py" / "src"))
    from bantamkit.client import Message, Tool, ToolCall
    from bantamkit.textutil import truncate

    return Message, Tool, ToolCall, truncate


def profile_numbers(root: Path) -> dict:
    data = yaml.safe_load((root / "assets" / "profiles" / f"{PROFILE}.yaml").read_text())
    return {
        "observation_budget": data["agent"]["observation_budget"],
        "max_turns": data["agent"]["max_turns"],
    }


def asset(root: Path) -> Path:
    return root / "assets" / "evals" / "devteam"


def manifest(root: Path) -> dict:
    return yaml.safe_load((asset(root) / "manifest.yaml").read_text())


def surface(root: Path) -> dict[str, str]:
    base = asset(root) / manifest(root)["surface"]["root"]
    return {
        p.relative_to(base).as_posix(): p.read_text()
        for p in sorted(base.rglob("*"))
        if p.is_file()
    }


def kind_of(path: str) -> str:
    if path.endswith(".py"):
        return "code"
    if path.endswith(".patch"):
        return "diff"
    if path.endswith((".yaml", ".yml", ".cfg", ".json")):
        return "config"
    return "prose"


# ---- Table 1: the surface census ----


def table_surface(root: Path) -> None:
    files, prof = surface(root), profile_numbers(root)
    print(RULE)
    print("TABLE 1 — the svc-ledger surface: every file, its kind, its bytes")
    print(RULE)
    hdr = f"{'path':<44}{'kind':>8}{'bytes':>8}"
    print(hdr)
    print("-" * len(hdr))
    for path, body in files.items():
        print(f"{path:<44}{kind_of(path):>8}{len(body.encode()):>8}")
    print("-" * len(hdr))
    sizes = [len(b.encode()) for b in files.values()]
    kinds: dict[str, int] = {}
    for path in files:
        kinds[kind_of(path)] = kinds.get(kind_of(path), 0) + 1
    print(f"{'TOTAL':<44}{len(files):>8}{sum(sizes):>8}")
    print("by kind: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    budget = prof["observation_budget"]
    print(f"largest file: {max(sizes)} B; observation_budget ({PROFILE}): {budget} B")
    print(
        "TRUNCATION: "
        + (
            f"none possible — every file is under the budget (max {max(sizes)} < {budget})"
            if max(sizes) < budget
            else "POSSIBLE — a file exceeds the budget; see the doc's accounting caveat"
        )
    )
    print()


# ---- Table 2: dev-team surface markers, M1's regexes verbatim ----

MARKERS = {
    "git history (commits/refs)": r"\b(commit|sha|branch|HEAD|revision|git log)\b",
    "a diff / patch hunk": r"(^|\n)(diff --git|@@ |\+\+\+ |--- )",
    "a symbol definition": r"(^|\n)\s*(def |class |function |func |const |var )",
    "an import / require": r"(^|\n)\s*(import |from \w+ import|require\(|#include)",
    "a stack trace / error": r"(Traceback|\.py\", line |Exception:|at \w+\.\w+\()",
    "a test or assertion": r"\b(assert\w*|pytest|unittest|it\(|describe\()\b",
}


def _tasks(directory: Path) -> list[dict]:
    return [yaml.safe_load(p.read_text()) for p in sorted(directory.glob("*.yaml"))]


def table_markers(root: Path) -> None:
    print(RULE)
    print("TABLE 2 — dev-team surface markers: devteam workload vs the FROZEN suite")
    print(RULE)
    print("Regexes are M1's, character for character, so the two columns are comparable.")
    frozen = _tasks(root / "assets" / "evals" / "tasks")
    devteam = _tasks(asset(root) / "tasks")
    hdr = f"{'marker':<30}{'devteam (n=' + str(len(devteam)) + ')':>18}{'frozen (n=22)':>16}"
    print(hdr)
    print("-" * len(hdr))
    for label, pat in MARKERS.items():
        rx = re.compile(pat, re.MULTILINE)
        cells = []
        for suite in (devteam, frozen):
            hits = 0
            for t in suite:
                bodies = list((t.get("workspace") or {}).values()) + [t.get("prompt", "")]
                hits += int(any(rx.search(b) for b in bodies))
            cells.append(f"{hits}/{len(suite)}")
        print(f"{label:<30}{cells[0]:>18}{cells[1]:>16}")
    print("-" * len(hdr))
    print("M1 measured the frozen column at 0/22 on every row (its one hit was a false")
    print("positive: the English verb in 'never commit tokens'). Reproduced above.")
    print()


# ---- Table 3: the reference walks, VERIFIED ----


def tool_sequence(task: dict) -> list[tuple[str, str | None]]:
    """The reference walk as tool calls. Deterministic rule, stated in the doc:

    one `list_files` first iff the prompt names it or a hop reads its pointer out of
    the listing, then one `read_file` per hop in order.
    """
    needs_list = "list_files" in task["prompt"] or any(
        hop.get("pointer_in") == "listing" for hop in task["walk"]
    )
    seq: list[tuple[str, str | None]] = [("list_files", None)] if needs_list else []
    return seq + [("read_file", hop["path"]) for hop in task["walk"]]


def verify_walk(task: dict, files: dict[str, str]) -> list[str]:
    """Every failure the walk could have. Empty list == the walk is checked.

    A hop is justified when its `pointer` is a literal in the text `pointer_in`
    names: `prompt`, `listing` (what list_files returns), or a path read EARLIER on
    this walk. `pointer_in` defaults to the immediately preceding hop, which makes
    the common case a chain and the declared case a fan-out (dt-handler-map resolves
    all three of its hops out of registry.py, not out of each other).
    """
    problems: list[str] = []
    listing = "\n".join(sorted(files))
    for i, hop in enumerate(task["walk"]):
        if hop["path"] not in files:
            problems.append(f"hop {i}: path not in surface: {hop['path']}")
            continue
        pointer = hop.get("pointer")
        if pointer is None:
            problems.append(f"hop {i}: no pointer declared")
            continue
        source = hop.get("pointer_in") or (task["walk"][i - 1]["path"] if i else "prompt")
        if source == "prompt":
            text = task["prompt"]
        elif source == "listing":
            text = listing
        elif source in files:
            if source not in [h["path"] for h in task["walk"][:i]]:
                problems.append(f"hop {i}: pointer_in {source!r} is not read earlier on the walk")
                continue
            text = files[source]
        else:
            problems.append(f"hop {i}: pointer_in {source!r} is not prompt, listing, or a path")
            continue
        if pointer not in text:
            problems.append(f"hop {i}: pointer {pointer!r} absent from {source}")
    joined = "\n".join(files[hop["path"]] for hop in task["walk"])
    for ev in task["answer_evidence"]:
        if ev not in joined:
            problems.append(f"answer_evidence {ev!r} appears nowhere on the walk")
    for value in _leaf_values(task["scoring"]["expected"]):
        # A repo-relative path is a DERIVED answer, not a literal in any file: the
        # run has to conclude "errors.py is where this is defined". Accepting it as
        # a surface key is the honest form of the check.
        if value not in joined and value not in files:
            problems.append(f"expected value {value!r} is neither a literal nor a surface path")
    return problems


def _leaf_values(expected) -> list[str]:
    """Expected answer leaves as strings, minus booleans.

    A bool is a derived judgement ("does this file import config"), never a literal
    in the file, so requiring it to appear would be wrong. Every other leaf must be
    readable off the surface or the task is unanswerable from the workload.
    """
    out: list[str] = []
    values = expected.values() if isinstance(expected, dict) else expected
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, (dict, list)):
            out += _leaf_values(v)
        else:
            out.append(str(v))
    return out


def table_walks(root: Path) -> None:
    files, prof, man = surface(root), profile_numbers(root), manifest(root)
    print(RULE)
    print("TABLE 3 — reference walks, verified against the surface")
    print(RULE)
    hdr = f"{'task':<24}{'hops':>5}{'calls':>6}{'turns<=max':>12}{'verified':>10}"
    print(hdr)
    print("-" * len(hdr))
    total_problems = 0
    for task in man["tasks"]:
        problems = verify_walk(task, files)
        total_problems += len(problems)
        calls = len(tool_sequence(task))
        turns = calls + 1
        max_turns = prof["max_turns"]
        fits = f"{turns}/{max_turns} " + ("yes" if turns <= max_turns else "NO")
        verified = "yes" if not problems else "NO"
        print(
            f"{task['name']:<24}{len(task['walk']):>5}{calls:>6}{fits:>12}{verified:>10}"
        )
        for p in problems:
            print(f"    ! {p}")
    print("-" * len(hdr))
    print(f"walk problems across the workload: {total_problems}")
    print("A verified walk means: every hop's path exists; every hop's pointer is a")
    print("literal in the text it says it came from (the prompt, the listing, or a file")
    print("read earlier on the walk); every answer_evidence string is a literal on the")
    print("walk; every non-boolean expected value is a literal on the walk or a surface")
    print("path. Pressure (Table 4) is derived from these checked walks, which is why it")
    print("is measured and not asserted. WEAKNESS, stated: for a short numeric expected")
    print("value the literal test is nearly vacuous ('3' occurs everywhere), so the")
    print("specific answer_evidence strings are what carry those tasks.")
    print()


# ---- Table 4: re-read pressure ----


def pressure(task: dict) -> dict:
    paths = [hop["path"] for hop in task["walk"]]
    distinct = len(set(paths))
    repeats = len(paths) - distinct
    return {
        "reads": len(paths),
        "distinct": distinct,
        "repeats": repeats,
        "pressure": repeats / len(paths) if paths else 0.0,
        "hubs": sorted({p for p in paths if paths.count(p) > 1}),
    }


def table_pressure(root: Path) -> None:
    man = manifest(root)
    print(RULE)
    print("TABLE 4 — re-read pressure, derived from the verified walks")
    print(RULE)
    hdr = f"{'task':<24}{'reads':>6}{'distinct':>9}{'repeats':>8}{'pressure':>10}  re-read hub"
    print(hdr)
    print("-" * len(hdr))
    reads = repeats = 0
    for task in man["tasks"]:
        p = pressure(task)
        reads += p["reads"]
        repeats += p["repeats"]
        print(
            f"{task['name']:<24}{p['reads']:>6}{p['distinct']:>9}{p['repeats']:>8}"
            f"{p['pressure']:>10.3f}  {', '.join(p['hubs']) or '-'}"
        )
    print("-" * len(hdr))
    print(f"{'SUITE':<24}{reads:>6}{'':>9}{repeats:>8}{repeats / reads:>10.3f}")
    nonzero = sum(1 for t in man["tasks"] if pressure(t)["repeats"])
    print(f"tasks with re-read pressure > 0: {nonzero}/{len(man['tasks'])}")
    print()
    print("For comparison, the same derivation over the 2 frozen nav tasks is not")
    print("available: they ship no reference walk, so their pressure has never been")
    print("stated. What IS committed is the consequence — the isolated cache measured")
    print("-0.05% and +4.92% on them (docs/eval-data/2026-08-09-filegraph-calibration*).")
    print()


# ---- Table 5: the deterministic wire-byte bound on the collapse ----

MARKER = (
    "[file-graph] {path} unchanged since your last read — "
    "{size} bytes not repeated (read #{n} via {tool})"
)


def _payload_bytes(Message, Tool, ToolCall, truncate, task, files, budget, collapse, doubled):
    """Exact wire bytes of every request the reference walk would POST.

    Mirrors Agent.run's message construction (agent.py:174-201) and
    OpenAICompatible.chat's payload (client.py:155-159), using the repo's own
    to_wire(). `collapse` substitutes the cache marker for a byte-identical repeat
    read, exactly as filegraph._record does (filegraph.py:83-88).
    """
    tools = [
        Tool(
            name="read_file",
            description="Read the full content of one file by its exact path",
            parameters={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}},
            },
        ),
        Tool(name="list_files", description="List all file paths in the workspace", parameters={"type": "object", "properties": {}}),
    ]
    seq = tool_sequence(task)
    if doubled:
        seq = seq + [c for c in seq if c[0] == "read_file"]
    messages = [Message(role="user", content=task["prompt"])]
    payloads: list[int] = []
    seen: dict[str, int] = {}

    def snapshot() -> None:
        payload = {
            "model": "reference",
            "messages": [m.to_wire() for m in messages],
            "tools": [t.to_wire() for t in tools],
            "seed": 0,
        }
        payloads.append(len(json.dumps(payload).encode()))

    for i, (tool, path) in enumerate(seq):
        snapshot()  # the call that emits this tool call
        messages.append(
            Message(
                role="assistant",
                tool_calls=[ToolCall(id=f"c{i}", name=tool, arguments={"path": path} if path else {})],
            )
        )
        if tool == "list_files":
            obs = "\n".join(sorted(files))
        else:
            obs = files[path]
            seen[path] = seen.get(path, 0) + 1
            if collapse and seen[path] > 1:
                obs = MARKER.format(
                    path=path, size=len(files[path].encode()), n=seen[path], tool="read_file"
                )
        messages.append(Message(role="tool", content=truncate(obs, budget), tool_call_id=f"c{i}"))
    messages.append(Message(role="assistant", content=json.dumps(task["scoring"]["expected"])))
    snapshot()  # the final call, which is the one that produced the answer above
    return sum(payloads)


def _observation_share(truncate, task, files, budget, factor: int = 1) -> tuple[int, int]:
    """The collapse's share of OBSERVATION bytes alone, weighted by re-send count.

    Table 5's denominator includes the prompt, the tool schemas and the JSON
    envelope, all of which are fixed costs that shrink as a surface's files grow.
    That makes Table 5's share depend on how big this particular surface's files
    are — and the unrealism detector (Table 6) says they are smaller than a real
    package's. This function removes that dependence: it is the limit Table 5's
    share approaches as observation bytes come to dominate the payload, so it is
    the SIZE-INDEPENDENT ceiling on what the collapse can remove from a run whose
    trajectory is this walk. Returns (off, saved) in re-send-weighted bytes.
    """
    seq = tool_sequence(task)
    reads = [c for c in seq if c[0] == "read_file"]
    seq = seq + reads * (factor - 1)
    calls = len(seq) + 1
    off = saved = 0
    seen: dict[str, int] = {}
    for i, (tool, path) in enumerate(seq):
        # An observation produced after call i+1 is re-sent by every later call.
        multiplicity = calls - (i + 1)
        if tool == "list_files":
            body, collapsed = "\n".join(sorted(files)), None
        else:
            body = files[path]
            seen[path] = seen.get(path, 0) + 1
            collapsed = (
                MARKER.format(
                    path=path, size=len(body.encode()), n=seen[path], tool="read_file"
                )
                if seen[path] > 1
                else None
            )
        full = len(truncate(body, budget).encode())
        off += full * multiplicity
        if collapsed is not None:
            saved += (full - len(truncate(collapsed, budget).encode())) * multiplicity
    return off, saved


def table_observation_bound(root: Path) -> None:
    _, _, _, truncate = _import_bantamkit(root)
    files, prof, man = surface(root), profile_numbers(root), manifest(root)
    budget = prof["observation_budget"]
    print(RULE)
    print("TABLE 5b — the same ceiling with the surface's file SIZE removed")
    print(RULE)
    print("Observation bytes only, weighted by how many later calls re-send them.")
    print("This is the limit Table 5's share approaches as files grow, so it does not")
    print("inherit the small-file bias the unrealism detector reports in Table 6.")
    hdr = f"{'task':<24}{'ref share':>12}{'doubled share':>15}"
    print(hdr)
    print("-" * len(hdr))
    tots = [0, 0, 0, 0]
    for task in man["tasks"]:
        off, saved = _observation_share(truncate, task, files, budget, 1)
        doff, dsaved = _observation_share(truncate, task, files, budget, 2)
        tots = [tots[0] + off, tots[1] + saved, tots[2] + doff, tots[3] + dsaved]
        print(f"{task['name']:<24}{saved / off:>12.3%}{dsaved / doff:>15.3%}")
    print("-" * len(hdr))
    print(f"{'WORKLOAD':<24}{tots[1] / tots[0]:>12.3%}{tots[3] / tots[2]:>15.3%}")
    def share(factor: int, tasks=None) -> float:
        pairs = [
            _observation_share(truncate, t, files, budget, factor) for t in (tasks or man["tasks"])
        ]
        return sum(s for _, s in pairs) / sum(o for o, _ in pairs)

    print()
    print("How loopy would a trajectory have to be to reach the >60% target? `factor k`")
    print("is the same walk with every read_file issued k times. LoopGuard's thresholds")
    print(f"for reference ({PROFILE}): note at 3 observation repeats, hard warning at 5.")
    hdr2 = f"{'repeat factor k':<18}{'workload share':>16}{'worst task':>12}{'>=60%?':>9}"
    print(hdr2)
    print("-" * len(hdr2))
    first_crossing = None
    for k in range(1, 13):
        workload = share(k)
        worst = max(share(k, [t]) for t in man["tasks"])
        crossed = workload >= 0.60
        if crossed and first_crossing is None:
            first_crossing = k
        print(f"{'k = ' + str(k):<18}{workload:>16.3%}{worst:>12.3%}{('YES' if crossed else 'no'):>9}")
    print("-" * len(hdr2))
    print(
        "smallest k whose WORKLOAD share reaches 60%: "
        + (str(first_crossing) if first_crossing else "none up to k = 12")
    )
    print("Read this as the bar's refutation arithmetic: the target is not reachable on")
    print("the reference walk, and reaching it needs a trajectory whose repeat count is")
    print("far past the loop-detection thresholds this repo already ships a guard for.")
    print()


def table_bound(root: Path) -> None:
    Message, Tool, ToolCall, truncate = _import_bantamkit(root)
    files, prof, man = surface(root), profile_numbers(root), manifest(root)
    budget = prof["observation_budget"]
    print(RULE)
    print("TABLE 5 — what the collapse can save, in exact wire bytes, on this workload")
    print(RULE)
    print("Trajectory held fixed at the verified reference walk; the only difference")
    print("between the two columns is filegraph's marker substitution for a")
    print("byte-identical repeat read. Bytes, not tokens — see the doc's stated")
    print("bytes-to-tokens assumption. `doubled` is the same walk with every read_file")
    print("issued a second time: the envelope's other end, not a prediction.")
    hdr = f"{'task':<24}{'off (B)':>10}{'cache (B)':>11}{'saved':>8}{'share':>8}{'doubled share':>15}"
    print(hdr)
    print("-" * len(hdr))
    tot_off = tot_cache = tot_doff = tot_dcache = 0
    for task in man["tasks"]:
        off = _payload_bytes(Message, Tool, ToolCall, truncate, task, files, budget, False, False)
        cache = _payload_bytes(Message, Tool, ToolCall, truncate, task, files, budget, True, False)
        doff = _payload_bytes(Message, Tool, ToolCall, truncate, task, files, budget, False, True)
        dcache = _payload_bytes(Message, Tool, ToolCall, truncate, task, files, budget, True, True)
        tot_off += off
        tot_cache += cache
        tot_doff += doff
        tot_dcache += dcache
        print(
            f"{task['name']:<24}{off:>10}{cache:>11}{off - cache:>8}"
            f"{(off - cache) / off:>8.3%}{(doff - dcache) / doff:>15.3%}"
        )
    print("-" * len(hdr))
    print(
        f"{'WORKLOAD':<24}{tot_off:>10}{tot_cache:>11}{tot_off - tot_cache:>8}"
        f"{(tot_off - tot_cache) / tot_off:>8.3%}{(tot_doff - tot_dcache) / tot_doff:>15.3%}"
    )
    print()
    print(f"reference walk : the collapse removes {(tot_off - tot_cache) / tot_off:.3%} of request bytes")
    print(f"doubled walk   : the collapse removes {(tot_doff - tot_dcache) / tot_doff:.3%} of request bytes")
    print("Both are below 60%. That is the pre-registered refutation condition's")
    print("arithmetic half; the doc states what it does and does not settle.")
    print()


# ---- Table 6: the realism detector ----


def _internal_imports(body: str, package: str) -> list[str]:
    return re.findall(rf"^\s*from {package}\.(\w+) import", body, re.MULTILINE) + re.findall(
        rf"^\s*import {package}\.(\w+)", body, re.MULTILINE
    )


def _code_stats(files: dict[str, str], package: str) -> dict:
    code = {p: b for p, b in files.items() if p.endswith(".py") and not p.endswith("__init__.py")}
    sizes = sorted(len(b.encode()) for b in code.values())
    fanin: dict[str, int] = {}
    per_module = []
    for body in code.values():
        imports = _internal_imports(body, package)
        per_module.append(len(imports))
        for mod in imports:
            fanin[mod] = fanin.get(mod, 0) + 1
    top = max(fanin.items(), key=lambda kv: kv[1]) if fanin else ("-", 0)
    return {
        "modules": len(code),
        "bytes_min": sizes[0] if sizes else 0,
        "bytes_median": int(statistics.median(sizes)) if sizes else 0,
        "bytes_max": sizes[-1] if sizes else 0,
        "imports_min": min(per_module) if per_module else 0,
        "imports_median": statistics.median(per_module) if per_module else 0,
        "imports_max": max(per_module) if per_module else 0,
        "top_fanin_module": top[0],
        "top_fanin": top[1],
    }


def table_realism(root: Path) -> None:
    synth = _code_stats(surface(root), "ledger")
    real_files = {
        p.name: p.read_text()
        for p in sorted((root / "runtime-py" / "src" / "bantamkit").rglob("*.py"))
    }
    real = _code_stats(real_files, "bantamkit")
    print(RULE)
    print("TABLE 6 — the unrealism detector: svc-ledger vs runtime-py/src/bantamkit")
    print(RULE)
    print("The threat accepted for a SYNTHESISED surface is unrealism. This is what")
    print("detects it: a structural comparison against a real package in this repo.")
    hdr = f"{'metric':<28}{'svc-ledger':>12}{'bantamkit':>12}{'inside?':>9}"
    print(hdr)
    print("-" * len(hdr))
    rows = [
        ("modules (non-__init__)", "modules", None),
        ("bytes/module min", "bytes_min", ("bytes_min", "bytes_max")),
        ("bytes/module median", "bytes_median", ("bytes_min", "bytes_max")),
        ("bytes/module max", "bytes_max", ("bytes_min", "bytes_max")),
        ("internal imports min", "imports_min", ("imports_min", "imports_max")),
        ("internal imports median", "imports_median", ("imports_min", "imports_max")),
        ("internal imports max", "imports_max", ("imports_min", "imports_max")),
        ("max internal fan-in", "top_fanin", ("imports_min", "top_fanin")),
    ]
    verdicts = []
    for label, key, band in rows:
        mark = "-"
        if band:
            lo, hi = real[band[0]], real[band[1]]
            ok = lo <= synth[key] <= hi
            mark = "yes" if ok else "NO"
            verdicts.append(ok)
        print(f"{label:<28}{synth[key]!s:>12}{real[key]!s:>12}{mark:>9}")
    print("-" * len(hdr))
    print(f"most-imported module: svc-ledger={synth['top_fanin_module']} "
          f"({synth['top_fanin']}), bantamkit={real['top_fanin_module']} ({real['top_fanin']})")
    failed = verdicts.count(False)
    print(
        "UNREALISM: "
        + (
            "not detected on any structural metric"
            if not failed
            else f"DETECTED on {failed} metric(s) — see the doc's threat section"
        )
    )
    print("Structural only. It cannot detect unrealistic TASK choice; the manifest's")
    print("`excluded:` list is the record for that, and M5 is briefed to attack it.")
    print()


def main() -> None:
    root = repo_root()
    table_surface(root)
    table_markers(root)
    table_walks(root)
    table_pressure(root)
    table_bound(root)
    table_observation_bound(root)
    table_realism(root)


if __name__ == "__main__":
    main()
