"""Apply one J69-6 mutation to a copy: python mut.py <copy> <ID>."""
import sys
from pathlib import Path

root, mid = Path(sys.argv[1]), sys.argv[2]
PY = "runtime-py/src/bantamkit/storage/retention.py"
TS = "runtime-ts/src/storage/retention.ts"
PY_MCP = "runtime-py/src/bantamkit/mcpserver.py"
TS_MCP = "runtime-ts/src/mcp/server.ts"
TS_DROP = (TS_MCP, "const query = search === undefined || search.t === 'null' ? null : asText(search);", "const query = null;")
PY_DROP = (PY_MCP, "                if search is None\n", "                if True\n")
M = {
    "R0": [],
    # plan: Node deletes before verifying
    "R1": [(TS, "    const dataOut = bundleBytes(bundle);\n",
            "    const dataOut = bundleBytes(bundle);\n    for (const p of files) fs.rmSync(p, { force: true });\n")],
    # plan: Python treats an open job as closed
    "R2": [(PY, '    return all(isinstance(u, dict) and u.get("status") in _CLOSED for u in units)', "    return True")],
    # plan, symmetric: the 7-day windows moved to 6 on both sides
    "R3": [(PY, "LEDGER_DAYS = 7\n", "LEDGER_DAYS = 6\n"), (PY, "JOB_DAYS = 7\n", "JOB_DAYS = 6\n"),
           (TS, "export const LEDGER_DAYS = 7;", "export const LEDGER_DAYS = 6;"), (TS, "export const JOB_DAYS = 7;", "export const JOB_DAYS = 6;")],
    # Python: a ledger exactly 7 days old is deleted (>= -> >)
    "R4": [(PY, "        if st is None or st.st_mtime_ns >= cutoff:", "        if st is None or st.st_mtime_ns > cutoff:")],
    # Node: the hook-log fold forgets `tool`
    "R5": [(TS, "    if (typeof tool === 'string') key = `${key}/${tool}`;", "    if (typeof tool === 'string') key = `${key}`;")],
    # Node: search is ANY term, not every term
    "R6": [(TS, "        if ([...want].every((t) => toks.has(t))) {", "        if ([...want].some((t) => toks.has(t))) {")],
    # Python: the TTL is inclusive at exactly 24 h
    "R7": [(PY, "    return not 0 <= age < TTL_S * 1000", "    return not 0 <= age <= TTL_S * 1000")],
    # Node: opt-out ignored
    "R8": [(TS, "  return !OFF.has((process.env[RETENTION_ENV] ?? '').trim().toLowerCase());", "  return true;")],
    # Node: the MCP handler drops `search`
    "R9": [TS_DROP],
    # symmetric: both MCP handlers drop `search`
    "R10": [TS_DROP, PY_DROP],
    # Node: the usage fold is computed at `now`, not at the cutoff
    "R11": [(TS, "(seg) => seg.foldLines(usageCutoff, (pairs) => reduceUsage(pairs, usageCutoff))",
             "(seg) => seg.foldLines(usageCutoff, (pairs) => reduceUsage(pairs, isoS(nowMs)))")],
    # Node: every log is rotated, idle or not
    "R12": [(TS, "    if (idle && seg.rotate(0)) report.rotated.push(p);", "    if (seg.rotate(0)) report.rotated.push(p);")],
    # Python: compact ignores the keep predicate (no prune)
    "R13": [(PY, "            if cold.compact(keep) is not None:", "            if cold.compact(None) is not None:")],
    # Python: a FILE where the archive dir goes is not a failure (write skipped, delete anyway)
    "R14": [(PY, '''            except OSError:
                report["refused"].append({"path": str(sw / name), "reason": "archive write failed"})
                continue''', '''            except OSError:
                pass''')],
}
for rel, a, b in M[mid]:
    p = root / rel
    s = p.read_text(encoding="utf-8")
    assert s.count(a) == 1, (mid, rel, s.count(a))
    p.write_text(s.replace(a, b), encoding="utf-8")
print("applied", mid)
