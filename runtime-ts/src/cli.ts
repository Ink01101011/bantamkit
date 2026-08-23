#!/usr/bin/env node
/**
 * The `bantamkit-mcp` entry point: the stdio MCP server, and four flags.
 *
 * N1 shipped this file as a refusal — exit 69 rather than a stub that pretended to be a
 * server — because stdout is the JSON-RPC channel and anything printed there reaches a host
 * as a malformed frame instead of as "not wired yet". THE REFUSAL IS RETIRED HERE, and it has
 * to be: the production invocation passes NO arguments at all (`.mcp.json` and the user-scope
 * config both call the launcher bare), so the bare form is the one that must serve. What the
 * refusal was protecting is kept and is now checked directly — `test/server.test.mjs` asserts
 * that every line a real session put on stdout parses as a JSON-RPC frame, that stdout never
 * ends mid-line, and that a clean session writes nothing to stderr either.
 *
 * PRODUCTION RUNS LAYERED. No `--store` means `Memory.layered`, which prepends `[project] `
 * to a recall line; a build validated only against `--store` would ship a recall string the
 * real deployment never produces.
 *
 * `--assets-root` stays. It is the arm-2 (packaged) resolution running inside a real install,
 * so `npx`/`npm i -g` can be checked end to end without speaking the protocol. It is also the
 * only path in this file that writes to stdout without being a frame, and it exits before a
 * transport is ever started.
 *
 * The prep probe refuted the sh launcher's `--which`: it has no consumer anywhere in the
 * repository or its history (`tools/mcpreach/mcpreach.py` has never existed on any ref), so
 * no Node `--which` is budgeted here.
 */
import { readFileSync, readdirSync } from 'node:fs';

import { assetsRoot } from './assets.js';
import { BantamError } from './errors.js';
import { Memory } from './memory/component.js';
import { DEFAULT_INDEX_BUDGET } from './memory/store.js';
import { buildServer } from './mcp/server.js';
import { RawStdioTransport } from './mcp/transport.js';

const USAGE = 'usage: bantamkit-mcp [-h] [--k K] [--index-budget BYTES] [--store STORE | --start START]';

/** `argparse.ArgumentParser.error`: usage on stderr, exit 2. Never stdout. */
class ArgvError extends Error {}
/** `SystemExit("...")`: the message on stderr, exit 1. */
class Refusal extends Error {}

export interface Options {
  k: number;
  indexBudget: number;
  store: string | null;
  start: string | null;
  assetsRoot: boolean;
  help: boolean;
}

/**
 * `_parse_args`, arm for arm, including the mutually exclusive group.
 *
 * `type=int` in argparse rejects anything `int()` rejects and reports it as an ARGUMENT error
 * (exit 2), which is a different exit from the `--k must be >= 1` refusal below (exit 1):
 * one is a malformed command line, the other is a command line that parsed and then asked
 * for something impossible.
 */
export function parseArgs(argv: readonly string[]): Options {
  const options: Options = {
    k: 3,
    indexBudget: DEFAULT_INDEX_BUDGET,
    store: null,
    start: null,
    assetsRoot: false,
    help: false,
  };
  const asInt = (flag: string, text: string | undefined): number => {
    if (text === undefined) throw new ArgvError(`argument ${flag}: expected one argument`);
    if (!/^\s*[+-]?\d+(?:_\d+)*\s*$/.test(text)) {
      throw new ArgvError(`argument ${flag}: invalid int value: '${text}'`);
    }
    return Number(text.trim().replace(/_/g, ''));
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]!;
    switch (arg) {
      case '-h':
      case '--help':
        options.help = true;
        break;
      case '--assets-root':
        options.assetsRoot = true;
        break;
      case '--k':
        options.k = asInt('--k', argv[(i += 1)]);
        break;
      case '--index-budget':
        options.indexBudget = asInt('--index-budget', argv[(i += 1)]);
        break;
      case '--store':
      case '--start': {
        const value = argv[(i += 1)];
        if (value === undefined) throw new ArgvError(`argument ${arg}: expected one argument`);
        if (options.store !== null || options.start !== null) {
          const held = options.store !== null ? '--store' : '--start';
          throw new ArgvError(`argument ${arg}: not allowed with argument ${held}`);
        }
        if (arg === '--store') options.store = value;
        else options.start = value;
        break;
      }
      default:
        throw new ArgvError(`unrecognized arguments: ${argv.slice(i).join(' ')}`);
    }
  }
  return options;
}

/** `_build_memory`, including the two refusals argparse cannot express. */
function buildMemory(options: Options): Memory {
  if (options.k < 1) throw new Refusal('--k must be >= 1');
  if (options.indexBudget < 1) throw new Refusal('--index-budget must be >= 1');
  const shared = { k: options.k, indexBudget: options.indexBudget };
  if (options.store !== null) {
    if (options.store === '') throw new Refusal('--store requires a non-empty path');
    return new Memory(options.store, shared);
  }
  return Memory.layered(options.start, shared);
}

/**
 * The version this build declares — the same bytes npm packs the tarball from.
 *
 * `RB-P45`'s defect has no Node analogue to fall back from: there is no installed dist-info
 * that can go stale, because `package.json` IS the install record and it ships in the package.
 */
function version(): string {
  return (JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')) as { version: string }).version;
}

async function main(argv: readonly string[]): Promise<number> {
  const options = parseArgs(argv);
  if (options.help) {
    process.stderr.write(`${USAGE}\n`);
    return 0;
  }
  if (options.assetsRoot) {
    const root = assetsRoot();
    let files = 0;
    for (const entry of readdirSync(root, { withFileTypes: true, recursive: true })) {
      if (entry.isFile()) files += 1;
    }
    process.stdout.write(`${root}\n${files} files\n`);
    return 0;
  }
  const memory = buildMemory(options);
  const wire = new RawStdioTransport();
  const server = buildServer(memory, wire, version());
  await server.connect(wire);
  // `asyncio.run(server.run_stdio_async())` returns when the client closes stdin. Here the
  // process stays alive on the stdin listener until the transport closes, which is what an
  // EOF on stdin means: the host has gone.
  await new Promise<void>((resolve) => {
    wire.onclose = () => resolve();
    process.stdin.on('end', () => void wire.close());
  });
  return 0;
}

try {
  process.exitCode = await main(process.argv.slice(2));
} catch (error) {
  if (error instanceof ArgvError) {
    process.stderr.write(`${USAGE}\nbantamkit-mcp: error: ${error.message}\n`);
    process.exitCode = 2;
  } else if (error instanceof Refusal) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  } else if (error instanceof BantamError) {
    process.stderr.write(`bantamkit-mcp: ${error.message}\n`);
    process.exitCode = 1;
  } else {
    throw error;
  }
}
