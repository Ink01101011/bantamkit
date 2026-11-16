/**
 * The realpath the hot index names its files by (`sha16`) and records as a head's `source`.
 *
 * Moved out of `hotindex.ts` unchanged (#316 G4, J90-2) so that module can be compiled by
 * `tools/ts2py` while this one stays an ADAPTER. J90-2 found the reference's `os.path.realpath`
 * answering differently for a path through a dangling symlink (it follows the link to its missing
 * target; `realpathSync.native` refuses the link and this keeps it as spelled); the orchestrator
 * ruled for this function's answer, so since J90-3 the Python adapter (`node_realpath`) is this
 * function ported: `path.resolve`, `realpath(3)`, and the parent where it throws.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';

/** `os.path.realpath`, which resolves what exists and keeps the rest (as `usage.ts` did). */
export function nodeRealpath(p: string): string {
  const abs = path.resolve(p);
  try {
    return fs.realpathSync.native(abs);
  } catch {
    const parent = path.dirname(abs);
    if (parent === abs) return abs;
    return path.join(nodeRealpath(parent), path.basename(abs));
  }
}
