"""T200-11 mutations: `python T200-11-mut.py <copy root> <ID>` (run by T200-11-mut.sh)."""
import sys
from pathlib import Path

PY = "runtime-py/src/bantamkit/touch/log.py"
TS = "runtime-ts/src/touch/log.ts"
PY_AGE = (PY, "        if total <= budget:\n            break\n", "        break\n")
TS_AGE = (TS, "    if (total <= budget) break;", "    break;")
PY_REV = (PY, 'key=lambda i: (rows[i]["ts"], rows[i]["path"])):', 'key=lambda i: (rows[i]["ts"], rows[i]["path"]), reverse=True):')
TS_REV = (TS, ".sort((a, b) => cmpCodepoint(rows[a]!['ts'] as string, rows[b]!['ts'] as string) || cmpCodepoint(rows[a]!['path'] as string, rows[b]!['path'] as string));",
          ".sort((a, b) => cmpCodepoint(rows[b]!['ts'] as string, rows[a]!['ts'] as string) || cmpCodepoint(rows[b]!['path'] as string, rows[a]!['path'] as string));")
PY_ALL = (PY, "    if kept_size > TOUCH_LOG_FOLD_TARGET_BYTES:\n", "    if False:\n")
TS_ALL = (TS, "  if (keptSize > TOUCH_LOG_FOLD_TARGET_BYTES) {", "  if (false) {")
PY_TOCAP = (PY, "_age(touch_reducer(old), TOUCH_LOG_FOLD_TARGET_BYTES - kept_size)", "_age(touch_reducer(old), TOUCH_LOG_CAP_BYTES - kept_size)")
TS_TOCAP = (TS, "age(touchReducer(old), TOUCH_LOG_FOLD_TARGET_BYTES - keptSize)", "age(touchReducer(old), TOUCH_LOG_CAP_BYTES - keptSize)")
PY_HELD = (PY, "                if not held:\n                    return False\n", "")
TS_HELD = (TS, "        if (!held) return false;\n", "")
PY_RAISE = (PY, "        except Exception:  # noqa: BLE001 - the bound is an enhancement; the line is written\n            return False\n",
            "        except Exception:  # noqa: BLE001\n            raise\n")
TS_RAISE = (TS, "    } catch {\n      return false; // the bound is an enhancement; the line is written", "    } catch (e) {\n      throw e;")
M = {
    # control: the tree as it is.
    "N0": [],
    # P1 one-sided: folded rows never age out.
    "N1": [TS_AGE],
    "N2": [PY_AGE],
    # P1 SYMMETRIC: both age the NEWEST first.
    "N3": [PY_REV, TS_REV],
    # P1 SYMMETRIC: neither folds the whole file when the newer half alone is over the target.
    "N4": [PY_ALL, TS_ALL],
    # P2 one-sided: Node ages only down to the cap (the next append folds again).
    "N5": [TS_TOCAP],
    # P2 SYMMETRIC: both age only down to the cap.
    "N6": [PY_TOCAP, TS_TOCAP],
    # P2 one-sided: Node folds once over the TARGET, so every append after a fold rewrites.
    "N7": [(TS, "if (ok && seg.size > TOUCH_LOG_CAP_BYTES) this.bound();", "if (ok && seg.size > TOUCH_LOG_FOLD_TARGET_BYTES) this.bound();"),
           (TS, "if (data.length <= TOUCH_LOG_CAP_BYTES) return false;", "if (data.length <= TOUCH_LOG_FOLD_TARGET_BYTES) return false;")],
    # P3 one-sided: the fold runs unlocked when the wait runs out.
    "N8": [PY_HELD],
    "N9": [TS_HELD],
    # P3 SYMMETRIC.
    "N10": [PY_HELD, TS_HELD],
    # P4 one-sided / SYMMETRIC: an error inside bound escapes.
    "N11": [TS_RAISE],
    "N12": [PY_RAISE, TS_RAISE],
    # the pre-fix behaviour on one side (no aging, no whole-file fold, folds unlocked): the race tests.
    "N13": [PY_HELD, PY_AGE, PY_ALL],
    "N14": [TS_HELD, TS_AGE, TS_ALL],
}
root, mid = Path(sys.argv[1]), sys.argv[2]
for f, old, new in M[mid]:
    p = root / f
    s = p.read_text(encoding="utf-8")
    if s.count(old) != 1:
        print(f"MISS {mid} {f}: {old[:60]!r}")
        sys.exit(2)
    p.write_text(s.replace(old, new), encoding="utf-8")
