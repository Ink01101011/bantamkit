/**
 * Retention's detached child, started (#204, S4; job69 J69-6).
 *
 * Moved out of `retention.ts`'s `maybeSpawn` unchanged (#316 G4, J90-3) so that module can be
 * compiled by `tools/ts2py` while this one stays an ADAPTER onto CPython: the reference starts
 * `python -m bantamkit.storage.retention <cwd> <home>` with `subprocess.Popen`, detached and
 * silent (`bantamkit.storage.retention.maybe_spawn`), as this starts `retention-child.js`.
 *
 * `detached` + `stdio: 'ignore'` + `.unref()`, the update probe's pattern. False when the child
 * script is not there (the caller answers `failed`); a spawn that throws throws.
 */
import { spawn } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CHILD = path.join(HERE, 'retention-child.js');

export function spawnRetentionChild(cwd: string, home: string): boolean {
  if (!fs.existsSync(CHILD)) return false;
  // THE HOME GOES ON THE COMMAND LINE: the child acts on the home the caller judged the TTL on.
  const child = spawn(process.execPath, [CHILD, cwd, home], { detached: true, stdio: 'ignore' });
  child.on('error', () => undefined);
  child.unref();
  return true;
}
