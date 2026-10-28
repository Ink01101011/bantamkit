/**
 * The detached Retention child (#204, J69-6): `node retention-child.js <cwd> <home>`.
 *
 * `storage/retention.ts`'s `maybeSpawn` starts it `detached`, `stdio: 'ignore'`, and never
 * waits; it ships in `dist/` so an npm install can run it, and `tools/storage/retention-child.mjs`
 * is the checkout's entry to the same file. Silent, always exit 0. The reference is
 * `python -m bantamkit.storage.retention <cwd> <home>`.
 */
import { childMain } from './retention.js';

process.exitCode = await childMain(process.argv.slice(2));
