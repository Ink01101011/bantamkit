/**
 * The realpath the hot index names its files by (`sha16`) and records as a head's `source`.
 *
 * Moved out of `hotindex.ts` unchanged (#316 G4, J90-2) so that module can be compiled by
 * `tools/ts2py` while this one stays an ADAPTER: the reference's `hotindex.sha16` and
 * `HotIndex.real` are `os.path.realpath`, which this does NOT reproduce for a path through a
 * dangling symlink (`os.path.realpath` follows the link to its missing target; `realpathSync`
 * refuses the link and this keeps it as spelled). J90-2 found that difference and left it as it
 * stands on both sides for the orchestrator to rule on: the generated Python keeps
 * `os.path.realpath` through the adapter, Node keeps this.
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
