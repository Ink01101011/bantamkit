"""Apply one J69-7 mutation to a copy: python J69-7-mut.py <copy> <ID>."""
import sys
from pathlib import Path

root, mid = Path(sys.argv[1]), sys.argv[2]
PY = "runtime-py/src/bantamkit/storage/tiers.py"
TS = "runtime-ts/src/storage/tiers.ts"
PY_MCP = "runtime-py/src/bantamkit/mcpserver.py"
TS_STATUS = "runtime-ts/src/mcp/status.ts"
M = {
    "T0": [],
    # Node: the hook tier reads the user scope only (project settings ignored)
    "T1": [(TS, "  if (cwd !== null) {\n", "  if (cwd !== null && cwd === '\\u0000') {\n")],
    # Python: the host-data tier never consults the native resolver
    "T2": [(PY, "        return native_memory_dir(str(home)) is not None", "        return False")],
    # Node: a log's skipped count is never read
    "T3": [(TS, "    seg.read();\n", "")],
    # Python: an unwritable index dir is reported persisted
    "T4": [(PY, '        where = "persisted" if idx.persisted else "in-memory"', '        where = "persisted"')],
    # Node: the retention line drops the opt-out
    "T5": [(TS, "  return `retention: ${enabled() ? '' : 'off; '}last ran", "  return `retention: ${''}last ran")],
    # SYMMETRIC: both sides drop every index line
    "T6": [(PY, "        out.append(f\"index facts {kind}: {_plural(docs, 'doc')}, {held} bytes, {where}\")", "        pass"),
           (TS, "    out.push(`index facts ${kind}: ${plural(docs, 'doc')}, ${held} bytes, ${idx.persisted ? 'persisted' : 'in-memory'}`);", "")],
    # Node: tier 2 absent BREAKS tier 1 -- the per-call condition path throws without a hook
    "T7": [(TS_STATUS, "export function degradedConditions(memory: Memory, log: EventLog): Condition[] {\n",
            "export function degradedConditions(memory: Memory, log: EventLog): Condition[] {\n"
            "  if (!statusLines(memory, homedir(), currentCwd())[0]!.includes('hooks on')) throw new Error('no hook tier');\n")],
    # Python: one served tool goes missing
    "T8": [(PY_MCP, '        _from_manifest(work_plan, "work_plan"),\n', "")],
    # SYMMETRIC: both sides report the hook tier off whatever the settings say
    "T9": [(PY, "    return any(has_bantamkit_hooks(p) for p in settings_paths(home, cwd))", "    return False"),
           (TS, "  return settingsPaths(home, cwd).some((p) => hasBantamkitHooks(p));", "  return false;")],
    # Node: one served tool goes missing
    "T10": [("runtime-ts/src/mcp/server.ts", "  'work_plan',\n  'shiftwork_plan',\n", "  'shiftwork_plan',\n")],
    # Python: an unwritable index directory FAILS the caller instead of taking the slow path
    "T11": [("runtime-py/src/bantamkit/storage/hotindex.py",
             "        except OSError:\n            self.persisted = False\n            self._head_stat = None\n            return\n",
             "        except OSError:\n            self.persisted = False\n            self._head_stat = None\n            raise\n")],
}
for rel, old, new in M[mid]:
    p = root / rel
    s = p.read_text(encoding="utf-8")
    if s.count(old) != 1:
        sys.exit(f"{mid}: {rel}: anchor found {s.count(old)} times: {old!r}")
    p.write_text(s.replace(old, new), encoding="utf-8")
print(f"{mid}: applied {len(M[mid])} edit(s)")
