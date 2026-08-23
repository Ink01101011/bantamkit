#!/usr/bin/env node
/**
 * The `bantamkit-mcp` entry point.
 *
 * NOT A SERVER YET. Unit N1 of job38 ships the package and the asset resolver only; the
 * stdio MCP server and the seven tools land in later units. Until then this refuses
 * rather than starting, because stdout is the JSON-RPC channel and a stub that printed
 * anything there would reach a host as a malformed frame instead of as "not wired yet".
 *
 * `--assets-root` prints the pack this build resolved and exits. That is deliberately
 * the ONE thing it can do: it is the arm-2 (packaged) resolution running inside a real
 * install, so `npx`/`npm i -g` can be checked end to end without a server.
 *
 * The prep probe refuted the sh launcher's `--which`: it has no consumer anywhere in the
 * repository or its history (`tools/mcpreach/mcpreach.py` has never existed on any ref),
 * so no Node `--which` is budgeted here.
 */
import { readdirSync } from 'node:fs';

import { assetsRoot } from './assets.js';
import { BantamError } from './errors.js';

function main(argv: string[]): number {
  if (argv.includes('--assets-root')) {
    const root = assetsRoot();
    let files = 0;
    for (const entry of readdirSync(root, { withFileTypes: true, recursive: true })) {
      if (entry.isFile()) files += 1;
    }
    process.stdout.write(`${root}\n${files} files\n`);
    return 0;
  }
  process.stderr.write(
    'bantamkit-mcp: the Node MCP server is not wired yet (job38 unit N1 ships the\n' +
      '  package and the asset pack only). Use --assets-root to check this install.\n',
  );
  return 69;
}

try {
  process.exitCode = main(process.argv.slice(2));
} catch (error) {
  if (error instanceof BantamError) {
    process.stderr.write(`bantamkit-mcp: ${error.message}\n`);
    process.exitCode = 1;
  } else {
    throw error;
  }
}
