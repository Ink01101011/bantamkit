/**
 * The detached Retention child's body, `<cwd> <home>` (#204, S4; job69 J69-6; #205 A3; #206).
 *
 * Moved out of `retention.ts` (#316 G4, J90-3): the sweep half (`childSweep`: claim the day under
 * the lock, run, record) is compiled by `tools/ts2py` with the rest of `retention.ts`; this async
 * half runs the daily skill audit and the experience miner after it, under the same claimed day,
 * and is NOT compiled. The miner may draft through an endpoint, so it is async here; the
 * reference's `child_main` (`bantamkit.storage.retention`, over the generated `childSweep`) calls
 * `skillreport.daily` and `skillmine.daily`, both synchronous, in the same order. Silent; always 0.
 *
 * #205 Amendment A3: it wakes when the sweep OR the skill audit is on and claims the day either
 * way. The sweep runs only when `BANTAMKIT_RETENTION` is not off; with it off the child deletes,
 * moves or rewrites NOTHING but `retention.json`'s claim and `skill-audit.json` (`skill-host`'s
 * `child` snapshot case). The audit runs after the sweep, under the same stamp, only when
 * `BANTAMKIT_SKILL_AUDIT` is not off; anything it or the miner throws is swallowed (the Python
 * shim's `child_main` catches every `Exception` alike since J90-3F; it caught only `OSError`).
 *
 * #206 Task 8: the experience miner (`skillmine.daily`) runs after the audit, under the same
 * switch and stamp. With the sweep off the only files the child may then change are the claim,
 * `skill-audit.json`, `skill-proposals.json`, `skill-miner-cache.json`, `skills-state.json`,
 * `skill-drafts.jsonl`, and paths under `~/.bantamkit/skills`, `~/.bantamkit/skill-backups` and
 * `<project>/.bantamkit/skills` (`skill-miner`'s snapshot case).
 */
import { daily as dailySkillAudit } from '../skillreport.js';
import { childSweep } from './retention.js';

/**
 * The audit the child runs, through one object a test swaps `daily` on (J90-3F: to show that an
 * audit that throws anything costs neither the sweep nor the child's exit, the Python shim's
 * `child_main` patched through `bantamkit.skillreport.daily`).
 */
export const childAudit = { daily: dailySkillAudit };

export async function childMain(argv: readonly string[], now: string | null = null): Promise<number> {
  const stamp = childSweep(argv, now);
  if (stamp === null) return 0;
  try {
    childAudit.daily(argv[1]!, argv[0]!, stamp);
    // #206 Task 8: the experience miner after the audit, under the same claimed day. Imported
    // here, not at the top, so a hook that only imports this module never loads the miner.
    const { daily: dailyMiner } = await import('../skillmine.js');
    await dailyMiner(argv[1]!, argv[0]!, stamp);
  } catch {
    /* silent: retried at the next day's TTL */
  }
  return 0;
}
