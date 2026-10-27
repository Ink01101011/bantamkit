/**
 * The SessionStart-line fixtures (#205 Task 5), shared by `skillreport.test.mjs` and
 * `hookadapter.test.mjs`. The same values as `runtime-py/tests/test_skillreport.py`.
 */
import fs from 'node:fs';
import path from 'node:path';

const R = await import('../dist/skillreport.js');

export const rec = (findings, span = 30, surfaced = []) => ({
  version: 1, ts: 't', host: 'claude-code', roots: [], skills: 1, catalogue_bytes: 1,
  findings, omissions: [], proposals: [],
  usage: { calls: 0, counts: {}, span_days: span, transcripts: 1, unreadable: 0, skipped_lines: 0 },
  surfaced: [...surfaced],
});
export const HIGH = { kind: 'shared-trigger-phrase', severity: 'high', skills: ['alpha:a1', 'beta:b2'], detail: 'deploy the thing' };
export const never = (s) => ({ kind: 'never-invoked', severity: 'low', skills: [s], detail: '0 calls' });
export const FULL = [HIGH, never('alpha:a1'), never('alpha:a2'), never('beta:b2'), never('proj')];
export const LINE =
  '[bantamkit] skill audit: 5 new — shared-trigger-phrase: alpha:a1, beta:b2; ' +
  'alpha:a1 30 days without a call; alpha:a2 30 days without a call; +2 more — ' +
  '/mcp__bantamkit__skill_audit has the report.';
export function put(home, record) {
  fs.mkdirSync(path.dirname(R.statePath(home)), { recursive: true });
  fs.writeFileSync(R.statePath(home), JSON.stringify(record));
}
