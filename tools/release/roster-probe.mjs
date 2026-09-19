#!/usr/bin/env node
/**
 * Drive an MCP server over REAL stdio and check the roster it advertises.
 *
 * WHAT IT IS FOR. `tools/conformance/npx-cold-start.mjs` asks this question of a tarball
 * this checkout just packed. Nothing asked it of the artifact that actually reached a
 * registry, and job56 is what that costs: `bantamkit-mcp@0.35.0` went to npm advertising
 * fewer tools than its own source declares, and every local gate stayed green because every
 * local gate rebuilds before it looks. This probe is pointed at an INSTALLED artifact --
 * one `npm install`ed from the registry, or one `pip install`ed into a throwaway venv --
 * so the thing under test is the thing the user will actually run.
 *
 * WHAT IT COMPARES AGAINST. `MCP_TOOLS` in `runtime-ts/src/mcp/server.ts`, parsed with the
 * same regex `npx-cold-start.mjs` uses, because that declaration is what `build_server`
 * maps straight onto `tools/list`. Names AND order. A parse that finds nothing is a hard
 * stop (exit 2), never a silent pass -- an empty expectation makes the check vacuous
 * instead of failing, which is the defect it exists to prevent.
 *
 * The server is launched from a fresh temporary directory, never from the checkout, so a
 * published artifact cannot accidentally read the repository it was built from.
 *
 * Usage:
 *   node tools/release/roster-probe.mjs [--label TEXT] [--timeout-ms N] -- CMD [ARGS...]
 *
 * Exit: 0 when the served roster equals MCP_TOOLS in that order, 1 on any disagreement or
 * on a server that never answered, 2 on a usage or parse error.
 */
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = dirname(dirname(here));
const servedDecl = join(repoRoot, 'runtime-ts', 'src', 'mcp', 'server.ts');

const argv = process.argv.slice(2);
let label = 'published artifact';
let timeoutMs = 120_000;
let command = [];
let i = 0;
while (i < argv.length) {
  const arg = argv[i];
  if (arg === '--label') {
    label = argv[i + 1] ?? label;
    i += 2;
  } else if (arg === '--timeout-ms') {
    timeoutMs = Number(argv[i + 1]);
    i += 2;
  } else if (arg === '--') {
    command = argv.slice(i + 1);
    break;
  } else {
    command = argv.slice(i);
    break;
  }
}
if (command.length === 0) {
  console.error('usage: node tools/release/roster-probe.mjs [--label TEXT] -- CMD [ARGS...]');
  process.exit(2);
}

const EXPECTED = (() => {
  const src = readFileSync(servedDecl, 'utf8');
  const block = /export const MCP_TOOLS = \[([\s\S]*?)\] as const;/.exec(src);
  if (!block) {
    console.error(
      `roster-probe: cannot find \`export const MCP_TOOLS = [...] as const;\` in\n  ${servedDecl}\n` +
        'The probe derives its expectation from that declaration and will not fall back to a\n' +
        'typed list. If the declaration moved, point this at where it went.',
    );
    process.exit(2);
  }
  const names = [...block[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
  if (names.length === 0) {
    console.error(`roster-probe: MCP_TOOLS in ${servedDecl} parsed to an empty list.`);
    process.exit(2);
  }
  return names;
})();

const neutralCwd = mkdtempSync(join(tmpdir(), 'bk-roster-'));
const [cmd, ...args] = command;
const child = spawn(cmd, args, {
  stdio: ['pipe', 'pipe', 'pipe'],
  cwd: neutralCwd,
  env: process.env,
});

let buf = '';
let stderr = '';
let answered = false;
const served = [];

child.stderr.on('data', (d) => {
  stderr += d.toString();
});

child.stdout.on('data', (d) => {
  buf += d.toString();
  let nl;
  while ((nl = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (!line) continue;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      continue;
    }
    if (msg.id === 1 && msg.result) {
      child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' })}\n`);
      child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} })}\n`);
    }
    if (msg.id === 2) {
      if (msg.result) for (const t of msg.result.tools ?? []) served.push(t.name);
      answered = true;
      child.stdin.end();
      child.kill('SIGTERM');
    }
  }
});

child.on('error', (e) => {
  console.error(`roster-probe: could not launch ${cmd}: ${e.message}`);
  process.exit(1);
});

const timer = setTimeout(() => {
  console.error(`roster-probe: ${label} did not answer tools/list within ${timeoutMs} ms.`);
  if (stderr) console.error(`  its stderr:\n${stderr}`);
  child.kill('SIGKILL');
  process.exit(1);
}, timeoutMs);

child.on('close', () => {
  clearTimeout(timer);
  if (!answered) {
    console.error(`roster-probe: ${label} closed before answering tools/list.`);
    if (stderr) console.error(`  its stderr:\n${stderr}`);
    process.exit(1);
  }
  const same = served.length === EXPECTED.length && served.every((n, i) => n === EXPECTED[i]);
  if (same) {
    console.log(`roster-probe: OK -- ${label} advertises the tools MCP_TOOLS declares, in that order.`);
    console.log(`  served: ${served.join(', ')}`);
    process.exit(0);
  }
  console.error(`roster-probe: FAIL -- ${label} does not advertise what MCP_TOOLS declares.`);
  console.error(`  expected: ${EXPECTED.join(', ')}`);
  console.error(`  served  : ${served.join(', ') || '(nothing)'}`);
  const missing = EXPECTED.filter((n) => !served.includes(n));
  const extra = served.filter((n) => !EXPECTED.includes(n));
  if (missing.length) console.error(`  missing : ${missing.join(', ')}`);
  if (extra.length) console.error(`  extra   : ${extra.join(', ')}`);
  process.exit(1);
});

child.stdin.write(
  `${JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: {
      protocolVersion: '2025-06-18',
      capabilities: {},
      clientInfo: { name: 'bantamkit-release-roster-probe', version: '0' },
    },
  })}\n`,
);
