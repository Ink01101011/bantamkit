/** First skill installed after MCP initialization, using the same live server (#242). */
import { join } from 'node:path';
export const name = 'skill-late-mcp';
export const summary = 'late project and user skills are recalled without restarting stdio MCP';
export async function run(ctx) {
  const cases = [];
  for (const root of ['project', 'user']) {
    const answers = {};
    for (const side of ['py', 'node']) {
      answers[side] = ctx.runPython(join(ctx.repoRoot, 'tools/conformance/ref/skill_late_mcp.py'), {
        bed: join(ctx.scratch, `late-mcp-${root}-${side}`), root,
        command: side === 'py' ? ctx.python : process.execPath,
        args: side === 'py' ? ['-m', 'bantamkit.mcpserver'] : [join(ctx.runtimeTs, 'dist/cli.js')],
      });
      cases.push({ name: `${root}: ${side} literal`, kind: 'json',
        expected: { absent_before: true, present_after: true, error: false }, actual: answers[side] });
    }
    cases.push({ name: `${root}: parity`, kind: 'json', expected: answers.py, actual: answers.node });
  }
  return { cases, notes: [] };
}
