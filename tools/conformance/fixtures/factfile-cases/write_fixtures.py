"""Write the previous-release fact files in this directory, through each release's own API.

    python3 -m venv /tmp/v0.35.9 && /tmp/v0.35.9/bin/pip install bantamkit==0.35.9
    /tmp/v0.35.9/bin/python -I write_fixtures.py <scratch-store-dir> <this-dir>/0.35.9

Run with the interpreter of the RELEASE being recorded, never the repo venv: the point is the
bytes that release's `MemoryStore.save` (and, for releases that stamp, `recall`) put on disk.
Each call is fed only what that release's `save` accepts (`outcome`/`status` from 0.36,
`keywords` from 0.37), so a release that refuses a value records the refusal in
`written.json` instead of a file. `today` is pinned so the dates are reproducible; the file
mtimes are not part of the fixture. ts2py-codec.mjs reads the result; it never runs this.
"""

from __future__ import annotations

import inspect
import json
import shutil
import sys
from pathlib import Path

from bantamkit import __version__
from bantamkit.memory.store import MemoryStore

FACTS = [
    (
        "project",
        "plain-fact",
        "a plain description with nothing special in it",
        "Body line one.\n\nBody line two.",
        (),
    ),
    (
        "feedback",
        "colon-in-description",
        "rule: never deploy on a friday afternoon",
        "Why: the on-call rota is thin.",
        (),
    ),
    (
        "reference",
        "number-lookalike",
        "12",
        "A description that YAML would read as an int if unquoted.",
        (),
    ),
    (
        "project",
        "date-lookalike",
        "2026-08-23",
        "A description that YAML would read as a date if unquoted.",
        (),
    ),
    (
        "user",
        "bool-lookalike",
        "yes",
        "A description that YAML 1.1 would read as a bool if unquoted.",
        (),
    ),
    (
        "project",
        "unicode-thai",
        "ภาษาไทย ปนกับ ascii — em dash และ emoji 🐔 อยู่ในคำอธิบายเดียวกัน",
        "เนื้อหา\n\nbody",
        (),
    ),
    (
        "project",
        "long-wrap",
        " ".join(["wrapping"] * 22) + " past the eightieth column twice over",
        "The description is long enough that PyYAML folds it.",
        (),
    ),
    (
        "feedback",
        "quotes-and-hash",
        "it's a 'quoted' value with a # hash and \"double\" quotes",
        "Body with --- inside\n---\nstill body",
        (),
    ),
    (
        "project",
        "with-links",
        "a fact that links to three others by name",
        "Linked.",
        ("plain-fact", "long-wrap", "a: b"),
    ),
    ("reference", "leading-indicator", "- starts with a dash and a space", "Body.   \n\n", ()),
]


def main() -> None:
    store_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    shutil.rmtree(store_dir, ignore_errors=True)
    store = MemoryStore(store_dir, today=lambda: "2026-01-02")
    params = inspect.signature(MemoryStore.save).parameters
    written = []
    for i, (type_, name, description, body, links) in enumerate(FACTS):
        kwargs = {}
        if "outcome" in params and type_ in ("feedback", "project") and i % 2 == 1:
            kwargs["outcome"] = "error" if i % 4 == 1 else "success"
        if "status" in params and name == "with-links":
            kwargs["status"] = "done"
        if "keywords" in params and i % 3 == 0:
            kwargs["keywords"] = ("deploy", "ภาษาไทย", "2026")
        try:
            store.save(type_, name, description, body, links, **kwargs)
            written.append({"name": name, "saved": True, "kwargs": sorted(kwargs)})
        except Exception as exc:  # noqa: BLE001 - a refusal is recorded, not hidden
            written.append({"name": name, "saved": False, "error": f"{type(exc).__name__}: {exc}"})
    # A release that stamps `last_recalled` on a recall hit does so here; one that no longer
    # stamps leaves the files as saved. Either way this is what that release leaves on disk.
    try:
        store.recall("plain description deploy friday", k=3)
        recalled = True
    except Exception as exc:  # noqa: BLE001
        recalled = f"{type(exc).__name__}: {exc}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted((store_dir / "facts").glob("*.md")):
        shutil.copyfile(path, out_dir / path.name)
    (out_dir / "written.json").write_text(
        json.dumps(
            {
                "bantamkit": __version__,
                "python": sys.version.split()[0],
                "facts": written,
                "recall": recalled,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
