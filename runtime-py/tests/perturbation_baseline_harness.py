"""The perturbation bar's whole offline output, as one deterministic artifact.

This exists so a refactor of `criticreplay` can be held to byte identity against a
baseline produced by the code it replaces, rather than against a re-run of itself.
It is written against the module's PUBLIC surface as of `f8404ab` — `load_manifest`,
`parse_rubric_arg`, `Case`, `run`, `summarize`, `format_table` — so the same file
runs against an older checkout unchanged.

Regenerate a baseline from any commit without touching the working tree:

    git worktree add /tmp/base <ref>
    BANTAMKIT_ASSETS=$PWD/assets PYTHONPATH=/tmp/base/runtime-py/src \\
      .venv/bin/python runtime-py/tests/perturbation_baseline_harness.py out.json

The critic is a pure function of the prompt bytes and the seed, so nothing here
touches a network or a clock.

Not collected by pytest (the filename is deliberately not `test_*`);
`test_criticreplay.py` imports `produce` and compares it to `data/`.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import yaml

from bantamkit.assets import assets_root
from bantamkit.client import Message, Response, Usage

# The three cells are the ones the committed anchor set's `--guard error` first pass
# names, so the baseline's guard tables are populated rather than empty, and the two
# readings of guard 2 disagree inside it (`P2-asks-requests`).
CELLS = (
    ("nav-prod-port", 0, 2331795949, "The production port is 8443."),
    ("recall-oncall-rotation", 1, 4094558621, "Rota: who is on-call for billing-svc."),
    ("recall-org-quota", 0, 634446002, "The org quota is 6000 requests-per-minute."),
)


class ScriptedCritic:
    """A fake critic whose verdict is a pure function of the prompt bytes and the seed."""

    def __init__(self, model: str = "fake-14b"):
        self.model = model
        self.seed = None
        self._response_format_unsupported = False
        self.calls = 0

    def chat(self, messages, tools=None, response_format=None):
        prompt = next(m.content for m in messages if m.role == "user")
        self.calls += 1
        digest = hashlib.sha256(f"{prompt}|{self.seed}".encode()).hexdigest()
        score = int(digest[:8], 16) % 11
        return Response(
            message=Message(
                role="assistant",
                content=json.dumps({"score": score, "feedback": digest[:6]}),
            ),
            usage=Usage(100 + score, 20 + score),
        )


def _variants(criticreplay, assets: Path, workdir: Path) -> list:
    """The shipped rubric, and §10's B-nonewline variant of it (the null control's edit).

    Labels the shipped manifest does not materialize, so `_check_materialization` stays
    out of the way and the family is the manifest's own twelve points.
    """
    raw = yaml.safe_load((assets / "rubrics" / "task-completion.yaml").read_text(encoding="utf-8"))
    workdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for label, prompt in (("L1", raw["prompt"]), ("L2", raw["prompt"][:-1])):
        path = workdir / f"{label}.yaml"
        path.write_text(
            yaml.safe_dump({**raw, "prompt": prompt}, sort_keys=False), encoding="utf-8"
        )
        paths.append(criticreplay.parse_rubric_arg(f"{label}={path}"))
    return paths


# On the SHIPPED twelve-point family the union of guard 2's two readings happens to
# equal the substitution-pair table (docs/eval.md, RB-P19), and the frozen family cannot
# produce a counter-example: whole-text can only exceed substitution-pair when a
# substitution lands inside a word, and none of the twelve does. So a baseline built from
# the frozen assets alone cannot see a refactor that dropped the union and kept one
# reading. This synthetic family closes that: `P-survivor` is flagged by
# substitution-pair only, `P-inword` by whole-text only, and the union is strictly bigger
# than either. Nothing here touches `assets/` — the manifest is built in memory.
SYNTHETIC_PROMPT = "TWO GAMMA. A BRIGHT answer. ONE TWO\nT:{task}\nA:{output}\n"
SYNTHETIC_SCHEMA = {
    "type": "object",
    "required": ["score", "feedback"],
    "properties": {"score": {"type": "integer"}, "feedback": {"type": "string"}},
}


def _synthetic(criticreplay, workdir: Path) -> dict:
    point = criticreplay.Point
    manifest = criticreplay.Manifest(
        rubric="synthetic",
        requirement_inventory=["one thing is required"],
        points=[
            point(id="identity", point_class="identity", rule="identity", op="identity"),
            point(
                id="P-survivor", point_class="paraphrase", rule="reword", op="replace",
                replace=[{"from": "ONE TWO", "to": "ONE THREE"}],
                justification="TWO leaves the anchor but survives elsewhere in the template",
            ),
            point(
                id="P-inword", point_class="paraphrase", rule="reword", op="replace",
                replace=[{"from": "IGHT", "to": "ISK"}],
                justification="a substitution that lands inside a word",
            ),
        ],
        materialized_variants={},
        sha256=criticreplay.sha256_text(SYNTHETIC_PROMPT),
        path=Path("<synthetic>"),
    )
    path = Path(workdir) / "synthetic.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "synthetic",
                "threshold": 7,
                "prompt": SYNTHETIC_PROMPT,
                "schema": SYNTHETIC_SCHEMA,
            },
            sort_keys=False,
        ), encoding="utf-8"
    )
    variants = [criticreplay.parse_rubric_arg(f"S={path}")]
    cases = [
        criticreplay.Case(
            task="gamma", repeat=0, seed=13, prompt="TWO STEP GAMMA", output="BRISK"
        )
    ]
    rows: list[dict] = []
    client = ScriptedCritic()
    result = criticreplay.run(
        client, variants, manifest, cases,
        replays=1, identity_replays=2, model=client.model, guard="warn",
        on_row=lambda row: rows.append(row.row()),
    )
    return {
        "rows": rows,
        "summary": criticreplay.summarize(result, manifest.sha256),
        "wire_calls": client.calls,
    }


# ---- scrubbing the working directory out of the artifact ----
#
# THIS IS SCRUBBED ON THE PARSED STRUCTURE, NOT ON THE SERIALIZED TEXT, AND THAT IS THE
# WHOLE POINT (2026-08-21). It used to be one line:
#
#     json.loads(json.dumps(artifact).replace(str(Path(workdir).resolve()), "<workdir>"))
#
# `json.dumps` escapes a backslash as `\\`, so on Windows the needle `C:\Users\...`
# does not occur in the haystack `C:\\Users\\...`. The replace matched nothing, raised
# nothing, warned nothing, and the byte-identity floor then failed on an absolute path in
# `rubric_ref` — measured `'C:\\Users\\runneradmin\\AppData\\...\\rubrics\\L1.yaml'` against a
# fixture that says `'<workdir>/L1.yaml'`. A text-level replace over JSON compares a
# needle in source encoding to a haystack in JSON encoding; every escape json.dumps
# applies (`\\`, `\"`, `\uXXXX`) is another way for that comparison to be silently
# wrong. Walking the object and replacing in string leaves compares data to data, so the
# escaping layer is not in the loop at all. That closes the class, not the instance.

_TOKEN = "<workdir>"
_WINDOWS_ROOT = re.compile(r"^[A-Za-z]:|\\")


class WorkdirScrubFoundNothing(RuntimeError):
    """The scrub ran over the artifact and matched nothing anywhere.

    A SILENT NO-OP IS THE ACTUAL DEFECT the one-line version had, so this is an error and
    not a warning. `produce` always writes L1, L2 and synthetic.yaml under `workdir` and
    every row records the path it parsed, so zero matches means the scrub stopped working
    -- never that there was nothing to scrub.
    """


def workdir_roots(workdir) -> tuple[str, ...]:
    """The root strings to look for, longest first.

    Both the resolved and the unresolved spelling: `rubric_ref` records `str(path)` as
    handed to `parse_rubric_arg`, which is NOT resolved, while the old scrub only ever
    looked for the resolved form. They coincide on this machine; on Windows a short
    (`RUNNER~1`) tmp path and its long form do not, which is a second way for the same
    one line to match nothing. Longest first so a root that is a prefix of another cannot
    shadow it.
    """
    raw = str(Path(workdir))
    roots = {raw, str(Path(workdir).resolve())}
    return tuple(sorted(roots, key=len, reverse=True))


def _flavours(root: str):
    r"""Windows path semantics only when the ROOT is Windows-shaped.

    Chosen from the root rather than from `os.name` for two reasons. It keeps POSIX
    behaviour byte-exactly POSIX -- `PureWindowsPath` is case-insensitive and treats `/`
    and `\` as the same character, so letting it near a POSIX root would scrub
    `/a/RUBRICS/L1.yaml` under root `/a/rubrics`, which is a different directory. And it
    lets the Windows condition be constructed and MEASURED from a POSIX machine by
    handing this function a Windows-shaped root, rather than inferred.
    """
    return PureWindowsPath if _WINDOWS_ROOT.search(root) else PurePosixPath


def scrub_leaf(text: str, roots: tuple[str, ...]) -> tuple[str, int]:
    r"""One string leaf -> (scrubbed, number of root occurrences removed).

    TWO BRANCHES, AND THEY ARE NOT THE SAME RULE.

    (1) The leaf IS a path under a root. Then it is relocated as a path: the root is
    discarded and the RELATIVE remainder is re-rendered with `as_posix()`. Separator
    normalisation therefore applies to the relative tail and to nothing else -- the
    fixture's `<workdir>/L1.yaml` falls out of `as_posix()` rather than out of a global
    `replace("\\", "/")` over the artifact. A global normalisation would corrupt any
    value that legitimately contains a backslash: a regex (`\\d+`), an escaped string in
    prose, or a Windows path that is DATA rather than the workdir. None of those can
    reach this branch, because none of them is a path under the workdir.

    (2) The leaf merely CONTAINS a root -- an embedded mention inside prose, say. Then
    the root substring is replaced and the rest of the leaf is left byte-exact, with NO
    separator normalisation, because outside a path this function cannot know whether a
    backslash is a separator or an escape. `<workdir>\file` is honest there; a guessed
    `/` would not be. Cost, stated: on Windows an embedded mention keeps a backslash
    join, so a fixture that pinned one would need to say so. The artifact this harness
    produces has no such leaf -- every workdir-bearing leaf is a whole path -- and the
    hit count below is what makes it visible if that ever changes.
    """
    for root in roots:
        flavour = _flavours(root)
        try:
            rel = flavour(text).relative_to(flavour(root))
        except ValueError:
            continue
        tail = rel.as_posix()
        return (_TOKEN if tail == "." else f"{_TOKEN}/{tail}"), 1
    hits = 0
    for root in roots:
        for spelling in (root, root.replace("\\", "/")):
            if spelling and spelling in text:
                hits += text.count(spelling)
                text = text.replace(spelling, _TOKEN)
    return text, hits


def scrub_workdir(artifact, workdir) -> tuple[object, int]:
    """Walk the artifact and scrub `workdir` out of every string leaf AND every dict key.

    Keys are scrubbed too: the old text-level replace covered them by accident of being
    text, and a path can perfectly well be a key.
    """
    roots = workdir_roots(workdir)
    total = 0

    def walk(node):
        nonlocal total
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if isinstance(key, str):
                    key, hits = scrub_leaf(key, roots)
                    total += hits
                out[key] = walk(value)
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, tuple):
            return [walk(v) for v in node]
        if isinstance(node, str):
            node, hits = scrub_leaf(node, roots)
            total += hits
            return node
        return node

    return walk(artifact), total


def produce(criticreplay, workdir: Path, assets: Path | None = None) -> dict:
    assets = Path(assets) if assets else assets_root()
    manifest = criticreplay.load_manifest(rubric_name="task-completion")
    variants = _variants(criticreplay, assets, Path(workdir))
    cases = [
        criticreplay.Case(
            task=task,
            repeat=repeat,
            seed=seed,
            prompt=yaml.safe_load(
                (assets / "evals" / "tasks" / f"{task}.yaml").read_text(encoding="utf-8")
            )[
                "prompt"
            ],
            output=output,
        )
        for task, repeat, seed, output in CELLS
    ]

    rows: list[dict] = []
    client = ScriptedCritic()
    result = criticreplay.run(
        client, variants, manifest, cases,
        replays=1, identity_replays=2, model=client.model, guard="warn",
        on_row=lambda row: rows.append(row.row()),
    )
    summary = criticreplay.summarize(result, manifest.sha256)

    identity_rows: list[dict] = []
    identity_client = ScriptedCritic()
    identity_result = criticreplay.run(
        identity_client, variants, manifest, cases,
        replays=1, identity_replays=3, identity_only=True, model=identity_client.model,
        on_row=lambda row: identity_rows.append(row.row()),
    )

    error_client = ScriptedCritic()
    try:
        criticreplay.run(error_client, variants, manifest, cases, model="m", guard="error")
        refusal = "DID NOT REFUSE"
    except criticreplay.PerturbationError as e:
        refusal = str(e)

    artifact = {
        "rows": rows,
        "summary": summary,
        "table": criticreplay.format_table(summary),
        "wire_calls": client.calls,
        "dropped": dict(sorted(result.dropped.items())),
        "selected": result.selected,
        "identity_only": {
            "rows": identity_rows,
            "summary": criticreplay.summarize(identity_result, manifest.sha256),
            "wire_calls": identity_client.calls,
        },
        "guard_error_refusal": refusal,
        "guard_error_wire_calls": error_client.calls,
        "synthetic": _synthetic(criticreplay, Path(workdir)),
    }
    # `rubric_ref` is the path the variant was parsed from, so it carries wherever this
    # ran. Scrubbing it is the only thing between the artifact and byte identity, and it
    # is done on the whole blob so nothing can hide a path in a field this file forgot.
    scrubbed, hits = scrub_workdir(json.loads(json.dumps(artifact)), workdir)
    if not hits:
        raise WorkdirScrubFoundNothing(
            "the workdir scrub matched nothing in the artifact; roots tried: "
            + repr(workdir_roots(workdir))
        )
    return scrubbed


def serialize(artifact: dict) -> str:
    return json.dumps(artifact, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    from bantamkit import criticreplay as module

    out = Path(sys.argv[1])
    out.write_text(serialize(produce(module, out.parent / "_harness_rubrics")), encoding="utf-8")
    print(f"wrote {out} from {module.__file__}")
