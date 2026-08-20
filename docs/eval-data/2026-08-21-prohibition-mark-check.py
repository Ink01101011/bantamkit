#!/usr/bin/env python3
"""RB-P94. Does a published result table carry the prohibitions its bar attached to the figures?

`RB-P87` (Amendment 3 §C.5) ends with a reporting limb: *"where a run publishes a descriptive
figure from an arm that any clause VOIDs or forbids comparing, the figure carries that mark in
the table that prints it."* That limb is a sentence, and a sentence is enforced by a reader who
already knows to go and look. `RB-P94` is what that costs, measured on this program's own
record: `docs/eval.md:8302` prints the J10 run's `3b` `paste` column as `2` / `4` / `0` — six
passes from the only arm of 432 rows whose prompt was truncated — and the four sentences that
forbid comparing them are in a DIFFERENT DOCUMENT (`2026-08-20-document-read-bar.md`, §5, §6.4,
§7.5, §8/§9). A number lifted out of a table carries its own digits and nothing else.

WHAT THIS MEASURES

Given (a) a bar carrying a machine-readable **prohibition index** and (b) a document containing
a **result table**, resolve every printed figure to its `(tier, arm, stratum)` and report every
figure that a prohibition COVERS and whose `mark` is NOT present where the figure is printed —
in the figure's own table cell, in its row label, or in its column header. Each figure is one of:

  UNMARKED     a prohibition covers it and its mark appears nowhere on the figure, the row or
               the column. This is `RB-P94`. Reported per prohibition, never in aggregate.
  MARKED       every prohibition covering it has its mark where the figure is printed.
  UNCOVERED    no prohibition selects it.

A prohibition with `scope=table` covers the table as a whole and is checked against the table's
CAPTION — its heading and the lines between the heading and the first table row.

The verdict for a figure is a set membership test over selectors the BAR declared, not a
judgement this program makes. Nothing here reads prose: an index entry is the unit of
prohibition, and a prohibition nobody wrote into the index is invisible (see COVERAGE).

THE INDEX GRAMMAR (an HTML comment in the bar, so it is markdown-invisible)

    <!-- prohibition-index v1
    P-CMP | scope=cell | tier=3b | arm=paste | stratum=* | mark=UNMEASURED window | source=...
    P-TIER | scope=table | mark=descriptive | source=...
    -->

`tier` / `arm` / `stratum` take `*` or a comma-separated list. `mark` is the literal text that
must travel with the figure; matching is case-insensitive substring, because a mark that has to
be spelled exactly is a mark that will be reworded and lost.

THE TABLE SHAPE IT READS

The first markdown table after the named heading. Column 0 keys the row and its first token is
the tier; every other header cell names a stratum. Where a header cell holds a `/`-separated
list of arm names before a comma (``` `bare` / `paste` / `reader`, small ```), each data cell in
that table is a `/`-separated tuple in that same order. A table it cannot resolve is reported
as unparseable and exits non-zero — never as zero findings, which would be a detector stuck off.

COVERAGE — what is NOT measured, so this is not read as wider than it is

  NOT   whether the index is COMPLETE. This checks the prohibitions a bar declares. One written
        in prose and left out of the index is UNMEASURED here. That is why `D-6` puts the index
        before the results: an index written afterwards is written by somebody who already knows
        which figures are awkward.
  NOT   whether a mark is ADEQUATE. Presence of the literal text is the whole test; a mark that
        is present and misleading passes.
  NOT   prose anywhere. No sentence is parsed, no prohibition is inferred, no vocabulary of
        "prohibition words" exists in this file. Such a vocabulary would report whatever its
        author arranged it to report.
  NOT   more than one table per run. One named section, one table.
  NOT   `runtime-ts`, any `.jsonl`, or any figure outside the named table.

RUN IT (from the repository root; no arguments needed for the committed pair, ~0.1s)

    python3 docs/eval-data/2026-08-21-prohibition-mark-check.py
    ... --calibrate   run only the three known answers; exits non-zero if any fails
    ... --strict      exit 1 when there is at least one finding
    ... --index FILE --doc FILE --section "V.1 The result"
    ... --json FILE   write the per-figure records

`--calibrate` is the reason any output here may be read. An instrument that grades a record may
not grade itself, so it is measured against three answers known by hand:

    CAL-FIRE              the three `3b`/`paste` figures of §V.1 (2, 4, 0) read UNMARKED under
                          `P-CMP`, and they are the ONLY cell findings  ->  this is `RB-P94`
    CAL-QUIET-NOT-COVERED the nine `4b`/`7b`/`14b` `paste` figures read UNCOVERED  ->  an
                          instrument that flagged a whole column fails here
    CAL-QUIET-MARKED      the six `3b` `bare`/`reader` figures ARE covered (by `P-POOL`) and
                          read MARKED, because the row label says "never pooled"

CAL-QUIET-MARKED is the detector-stuck-on control, and it is not hypothetical: the `RB-P94`
register entry says the 3b figures are printed *"with no mark"* and that *"Nothing on the row
says so."* The row label is `3b (declared floor, never pooled)`. An instrument built to agree
with the entry would flag all nine 3b figures and would be wrong on six of them. All three
answers must come back or the run exits non-zero.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = REPO / "docs" / "eval-data" / "2026-08-20-document-read-bar.md"
DEFAULT_DOC = REPO / "docs" / "eval.md"
DEFAULT_SECTION = "V.1 The result"

_INDEX_OPEN = "<!-- prohibition-index v1"
_SEPARATOR = re.compile(r"^:?-{2,}:?$")


class Unparseable(Exception):
    """The instrument could not resolve its input. Never reported as zero findings."""


def _clean(text: str) -> str:
    """Strip the markdown emphasis a figure or a header is dressed in, keep the value."""
    return text.replace("`", "").replace("*", "").strip()


def parse_index(text: str) -> list[dict]:
    """The prohibitions the bar declares, in declaration order.

    Nothing is inferred: a line inside the block is a prohibition and a line outside it is not,
    so the bar chooses what this program enforces and this program chooses nothing.
    """
    start = text.find(_INDEX_OPEN)
    if start < 0:
        raise Unparseable(f"no {_INDEX_OPEN!r} block")
    end = text.find("-->", start)
    if end < 0:
        raise Unparseable("prohibition-index block is not closed")
    body = text[start + len(_INDEX_OPEN) : end]
    out: list[dict] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        fields = [f.strip() for f in line.split("|")]
        entry = {"id": fields[0], "scope": "cell", "tier": "*", "arm": "*", "stratum": "*"}
        for field in fields[1:]:
            if "=" not in field:
                raise Unparseable(f"{entry['id']}: field {field!r} is not key=value")
            key, value = field.split("=", 1)
            entry[key.strip()] = value.strip()
        if "mark" not in entry:
            raise Unparseable(f"{entry['id']}: no mark= — a prohibition with nothing to carry")
        if entry["scope"] not in ("cell", "table"):
            raise Unparseable(f"{entry['id']}: scope={entry['scope']!r} is not cell or table")
        out.append(entry)
    if not out:
        raise Unparseable("prohibition-index block is empty")
    return out


def parse_table(text: str, section: str) -> dict:
    """The first markdown table under the named heading, with its caption.

    The heading is matched by name rather than by line number on purpose: a line number in a
    file three other units may be appending to is a pin that rots, and a pin that rots reports
    the wrong table rather than no table.
    """
    lines = text.splitlines()
    head = next(
        (i for i, ln in enumerate(lines) if ln.lstrip().startswith("#") and section in ln), None
    )
    if head is None:
        raise Unparseable(f"no heading contains {section!r}")
    start = next(
        (i for i in range(head + 1, len(lines)) if lines[i].lstrip().startswith("|")), None
    )
    if start is None:
        raise Unparseable(f"no markdown table after {section!r}")
    stop = start
    while stop < len(lines) and lines[stop].lstrip().startswith("|"):
        stop += 1
    caption = "\n".join([lines[head]] + lines[head + 1 : start])

    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    header = cells(lines[start])
    rows = [cells(ln) for ln in lines[start + 1 : stop]]
    if rows and all(_SEPARATOR.match(_clean(c)) for c in rows[0]):
        rows = rows[1:]
    if not rows:
        raise Unparseable(f"the table under {section!r} has no data rows")

    arms: list[str] = []
    strata: list[str] = []
    for cell in header[1:]:
        arms_part, _, stratum = cell.rpartition(",")
        if "/" in arms_part and not arms:
            arms = [_clean(a) for a in arms_part.split("/")]
        strata.append(_clean(stratum or arms_part))

    figures = []
    for row in rows:
        if len(row) != len(header):
            raise Unparseable(f"row {row[0]!r} has {len(row)} cells, header has {len(header)}")
        label = row[0]
        tier = _clean(label).split()[0] if _clean(label) else ""
        for col, cell in enumerate(row[1:]):
            parts = [p.strip() for p in cell.split("/")] if arms else [cell]
            if arms and len(parts) != len(arms):
                raise Unparseable(
                    f"row {label!r} column {strata[col]!r}: {len(parts)} figures, {len(arms)} arms"
                )
            for k, part in enumerate(parts):
                figures.append(
                    {
                        "tier": tier,
                        "arm": arms[k] if arms else "",
                        "stratum": strata[col],
                        "figure": _clean(part),
                        "printed_context": f"{part} {label} {header[col + 1]} {strata[col]}",
                    }
                )
    return {"caption": caption, "header": header, "arms": arms, "strata": strata,
            "figures": figures}


def _selects(selector: str, value: str) -> bool:
    return selector == "*" or value in [s.strip() for s in selector.split(",")]


def analyse(index: list[dict], table: dict) -> dict:
    """Resolve every figure against every prohibition. No prohibition is aggregated away."""
    records = []
    for fig in table["figures"]:
        covered, unmarked = [], []
        for pro in index:
            if pro["scope"] != "cell":
                continue
            if not all(
                _selects(pro[k], fig[k]) for k in ("tier", "arm", "stratum")
            ):
                continue
            covered.append(pro["id"])
            if pro["mark"].lower() not in fig["printed_context"].lower():
                unmarked.append(pro["id"])
        verdict = "UNCOVERED" if not covered else ("UNMARKED" if unmarked else "MARKED")
        records.append({**{k: fig[k] for k in ("tier", "arm", "stratum", "figure")},
                        "covered": covered, "unmarked": unmarked, "verdict": verdict})
    table_findings = [
        pro["id"]
        for pro in index
        if pro["scope"] == "table" and pro["mark"].lower() not in table["caption"].lower()
    ]
    return {"records": records, "table_findings": table_findings}


def render(index: list[dict], table: dict, result: dict, doc: Path, section: str) -> str:
    findings = [r for r in result["records"] if r["verdict"] == "UNMARKED"]
    by_verdict = {v: sum(1 for r in result["records"] if r["verdict"] == v)
                  for v in ("UNMARKED", "MARKED", "UNCOVERED")}
    out = [
        f"# Prohibition marks — `{doc.name}` §{section}",
        "",
        (f"{len(index)} prohibitions declared; {len(result['records'])} figures resolved "
         f"({len(table['arms']) or 1} arms × {len(table['strata'])} strata × "
         f"{len(result['records']) // max(1, (len(table['arms']) or 1) * len(table['strata']))}"
         " rows)."),
        "",
        "| figure | tier | arm | stratum | verdict | covered by | unmarked under |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in result["records"]:
        out.append(
            f"| `{r['figure']}` | {r['tier']} | {r['arm'] or '—'} | {r['stratum']} | "
            f"{r['verdict']} | {', '.join(r['covered']) or '—'} | "
            f"{', '.join(r['unmarked']) or '—'} |"
        )
    out += [
        "",
        "## The findings",
        "",
        (f"- figures a prohibition covers and whose mark is not where they are printed: "
         f"**{by_verdict['UNMARKED']}**"),
        f"- figures covered and marked: **{by_verdict['MARKED']}**",
        f"- figures no prohibition covers: **{by_verdict['UNCOVERED']}**",
        f"- table-scope prohibitions with no mark in the caption: "
        f"**{len(result['table_findings'])}**"
        + (f" ({', '.join(result['table_findings'])})" if result["table_findings"] else ""),
        "",
    ]
    if findings:
        out.append("Every unmarked figure, with the sentence it does not carry:")
        sources = {p["id"]: p.get("source", "—") for p in index}
        for r in findings:
            out.append(
                f"- `{r['figure']}` at ({r['tier']}, {r['arm']}, {r['stratum']}) — "
                f"{', '.join(r['unmarked'])}: {sources[r['unmarked'][0]]}"
            )
    else:
        out.append("No figure is printed without a mark a declared prohibition requires.")
    out.append("")
    return "\n".join(out)


def calibrate(result: dict) -> int:
    """Three answers known by hand. Any failure exits non-zero and no table is believed."""
    records = {(r["tier"], r["arm"], r["stratum"]): r for r in result["records"]}
    checks: list[tuple[str, bool, str]] = []

    fired = sorted(
        (r["tier"], r["arm"], r["stratum"], r["figure"])
        for r in result["records"]
        if r["verdict"] == "UNMARKED"
    )
    expected = [
        ("3b", "paste", "large-IN", "4"),
        ("3b", "paste", "large-OUT", "0"),
        ("3b", "paste", "small", "2"),
    ]
    under_p_cmp = all(
        records[(t, a, s)]["unmarked"] == ["P-CMP"] for t, a, s, _ in expected if (t, a, s) in records
    )
    checks.append(
        ("CAL-FIRE", fired == expected and under_p_cmp,
         f"the 3b paste column reads UNMARKED under P-CMP and is the only cell finding; got {fired}")
    )

    quiet = [
        records.get((tier, "paste", stratum))
        for tier in ("4b", "7b", "14b")
        for stratum in ("small", "large-IN", "large-OUT")
    ]
    checks.append(
        ("CAL-QUIET-NOT-COVERED",
         len(quiet) == 9 and all(r is not None and r["verdict"] == "UNCOVERED" for r in quiet),
         "the nine compared-tier paste figures are covered by nothing")
    )

    marked = [
        records.get((tier, arm, stratum))
        for tier in ("3b",)
        for arm in ("bare", "reader")
        for stratum in ("small", "large-IN", "large-OUT")
    ]
    checks.append(
        ("CAL-QUIET-MARKED",
         len(marked) == 6
         and all(r is not None and r["verdict"] == "MARKED" and r["covered"] == ["P-POOL"]
                 for r in marked),
         "the six 3b bare/reader figures are covered by P-POOL and carry its mark on the row")
    )

    bad = 0
    for name, ok, what in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}: {what}")
        bad += 0 if ok else 1
    print(f"{len(checks) - bad} of {len(checks)} known answers correct")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", default=str(DEFAULT_INDEX), help="the bar carrying the index")
    ap.add_argument("--doc", default=str(DEFAULT_DOC), help="the document with the result table")
    ap.add_argument("--section", default=DEFAULT_SECTION, help="the heading naming the table")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--strict", action="store_true", help="exit 1 when there is any finding")
    ap.add_argument("--json")
    args = ap.parse_args()

    index_path, doc_path = Path(args.index), Path(args.doc)
    try:
        index = parse_index(index_path.read_text())
        table = parse_table(doc_path.read_text(), args.section)
    except (OSError, Unparseable) as exc:
        print(f"unparseable: {exc}", file=sys.stderr)
        return 2

    result = analyse(index, table)
    if args.calibrate:
        print(f"index {index_path.name}  doc {doc_path.name}  section {args.section}")
        return calibrate(result)

    print(render(index, table, result, doc_path, args.section))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2) + "\n")
    findings = sum(1 for r in result["records"] if r["verdict"] == "UNMARKED")
    findings += len(result["table_findings"])
    return 1 if (args.strict and findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
