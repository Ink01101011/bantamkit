"""#257 prep probe, re-runnable: how often a wide batch hands two units the same file.

Reads every `.shiftwork/*.json` checkpoint in a repo, gives each unit the tracked paths
under `runtime-py/src`, `runtime-ts/src`, `tools/` and `assets/` that its brief names, and
batches each graph with `workplan.plan` twice: by `depends_on` alone, and with those paths
as `touches`. Prints the table the spec opens with.

The inferred `touches` are an ESTIMATE, which is why the runtime never infers them: a
missing brief undercounts and a brief that only reads a file overcounts. Both bounds are
printed. Usage:

    .venv/bin/python tools/eval/touches_probe.py [repo]
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime-py" / "src"))

from bantamkit import workplan

ROOTS = ("runtime-py/src/", "runtime-ts/src/", "tools/", "assets/")


def tracked(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", *ROOTS], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    )
    # Longest first, so `shiftwork.py` inside `bantamkit/shiftwork.py` is not also counted.
    return sorted(out.stdout.split(), key=len, reverse=True)


def named(brief: str, paths: list[str]) -> list[str]:
    return [path for path in paths if path in brief]


def main() -> int:
    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    paths = tracked(repo)
    checkpoints = units = missing = 0
    plain = held_batches = wide = contended = 0
    contended_in: set[str] = set()
    for file in sorted((repo / ".shiftwork").glob("*.json")):
        try:
            document = json.loads(file.read_text(encoding="utf-8"))
            plan_units = document["plan"]["units"]
        except (ValueError, KeyError, TypeError):
            continue
        checkpoints += 1
        nodes = []
        for unit in plan_units:
            units += 1
            brief_path = repo / unit.get("brief_path", "")
            try:
                brief = brief_path.read_text(encoding="utf-8")
            except OSError:
                missing += 1
                brief = ""
            nodes.append(
                {"id": unit["id"], "depends_on": unit.get("depends_on") or [],
                 "touches": named(brief, paths)}
            )
        bare = workplan.plan([{k: v for k, v in n.items() if k != "touches"} for n in nodes])
        held = workplan.plan(nodes)
        if "batches" not in bare or "batches" not in held:
            continue
        files = {n["id"]: set(n["touches"]) for n in nodes}
        plain += len(bare["batches"])
        held_batches += len(held["batches"])
        for batch in bare["batches"]:
            if len(batch) < 2:
                continue
            wide += 1
            seen: set[str] = set()
            if any(seen & files[i] or seen.update(files[i]) for i in batch):
                contended += 1
                contended_in.add(file.name)
    straight = units
    print(f"checkpoints / units                  {checkpoints} / {units}")
    print(f"briefs missing from disk (undercount) {missing}")
    print(f"batches, depends_on only              {plain} ({straight - plain} serial steps saved)")
    print(f"batches wider than 1                  {wide}")
    print(f"  of those naming one file twice      {contended} in {len(contended_in)} checkpoints")
    print(f"batches with touches                  {held_batches} (+{held_batches - plain} steps)")
    saved = straight - plain
    kept = straight - held_batches
    print(f"width kept                            {kept} of {saved} saved steps"
          + (f" ({100 * kept // saved} %)" if saved else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
