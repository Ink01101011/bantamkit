/**
 * Wire this server into an MCP host's configuration — `--install <host>`.
 *
 * The Node half of `runtime-py/src/bantamkit/hostinstall.py`, sentence for sentence. Read
 * that file for WHY each decision is what it is; this header records only what porting it
 * cost.
 *
 * EVERY OPERATOR-VISIBLE STRING IS COMPARED BYTE FOR BYTE against the reference, so two
 * things that look like implementation detail are not:
 *
 *   1. The JSON in the conflict message goes through `dumpJson(fromJs(...), {sortKeys})`,
 *      never `JSON.stringify`. Python writes `{"args": [], "command": "OLD"}` and
 *      `JSON.stringify` writes `{"args":[],"command":"OLD"}` — same object, different
 *      bytes, and the separators are the whole difference.
 *   2. The file is written with the same helper at `indent: 2`, which also reproduces
 *      `ensure_ascii`. A home directory with a non-ASCII name would otherwise make the two
 *      runtimes write different bytes for the same install.
 *
 * WHAT IS RULED DIFFERENT, and it is one field: the COMMAND. This side records
 * `npx -y bantamkit-mcp`; the reference records its own console script. The thing installed
 * should be the thing that answers, and neither side should send a host looking for the
 * other's runtime. `docs/porting.md` carries the row.
 */
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';

import { dumpJson, fromJs } from './pyjson.js';

/** The four hosts, in the order they print in `--help`. */
export const HOSTS = ['claude', 'claude-desktop', 'copilot', 'cursor'] as const;
export type Host = (typeof HOSTS)[number];

/** The entry name written into every host. */
export const ENTRY = 'bantamkit';

/** A refusal, carrying the sentence the operator should read. Never a stack. */
export class InstallError extends Error {}

const dumps = (value: unknown, indent: number | null = null, sortKeys = false): string =>
  dumpJson(fromJs(value), { indent, sortKeys });

/**
 * The file `--install <host>` would write, on THIS platform.
 *
 * Resolved from `homedir()` and `APPDATA` and nothing else — point `HOME`/`USERPROFILE` at a
 * temporary directory and every path moves with it, which is what makes the tests possible.
 *
 * `claude` has no entry here: its arm shells out to `claude mcp add` and never names a path.
 */
export function hostConfigPath(host: Host): string {
  const home = homedir();
  const appdata = process.env.APPDATA;
  const roaming = appdata !== undefined && appdata !== '' ? appdata : join(home, 'AppData', 'Roaming');
  if (host === 'claude-desktop') {
    if (process.platform === 'darwin') {
      return join(home, 'Library', 'Application Support', 'Claude', 'claude_desktop_config.json');
    }
    if (process.platform === 'win32') return join(roaming, 'Claude', 'claude_desktop_config.json');
    return join(home, '.config', 'Claude', 'claude_desktop_config.json');
  }
  if (host === 'copilot') {
    if (process.platform === 'darwin') {
      return join(home, 'Library', 'Application Support', 'Code', 'User', 'mcp.json');
    }
    if (process.platform === 'win32') return join(roaming, 'Code', 'User', 'mcp.json');
    return join(home, '.config', 'Code', 'User', 'mcp.json');
  }
  if (host === 'cursor') return join(home, '.cursor', 'mcp.json');
  throw new InstallError(`no configuration file is written for ${host}`);
}

/** `servers` in VS Code, `mcpServers` everywhere else — the word that silently loses entries. */
export function configKey(host: Host): string {
  return host === 'copilot' ? 'servers' : 'mcpServers';
}

/** The server entry, in the shape the host expects. `type` only where the host documents it. */
export function entryFor(host: Host, command: string, args: string[]): Record<string, unknown> {
  return host === 'copilot'
    ? { type: 'stdio', command, args: [...args] }
    : { command, args: [...args] };
}

function readConfig(path: string): Record<string, unknown> {
  if (!existsSync(path)) return {};
  let text: string;
  try {
    text = readFileSync(path, 'utf8');
  } catch (e) {
    throw new InstallError(`cannot read ${path}: ${(e as Error).message}`);
  }
  if (text.trim() === '') return {};
  let loaded: unknown;
  try {
    loaded = JSON.parse(text);
  } catch (e) {
    // The reference reports CPython's message, line and column. `JSON.parse` gives neither
    // the same wording nor a position, so this is a RULED difference rather than a silent
    // one: both refuse, both name the file, and the reason after the colon differs.
    throw new InstallError(
      `${path} is not valid JSON, so this refuses to touch it: ${(e as Error).message}`,
    );
  }
  if (loaded === null || typeof loaded !== 'object' || Array.isArray(loaded)) {
    const kind = Array.isArray(loaded) ? 'list' : loaded === null ? 'NoneType' : typeof loaded;
    throw new InstallError(`${path} holds ${kind}, not an object; refusing to touch it`);
  }
  return loaded as Record<string, unknown>;
}

function writeConfig(path: string, data: Record<string, unknown>): void {
  mkdirSync(dirname(path), { recursive: true });
  const tmp = `${path}.bantamkit-tmp`;
  try {
    writeFileSync(tmp, `${dumps(data, 2)}\n`, 'utf8');
    renameSync(tmp, path);
  } catch (e) {
    rmSync(tmp, { force: true });
    throw new InstallError(`cannot write ${path}: ${(e as Error).message}`);
  }
}

/** `date.today().isoformat()` — the LOCAL date, which is what the reference takes. */
function today(): string {
  const now = new Date();
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function backup(path: string): string | null {
  if (!existsSync(path)) return null;
  const target = `${path}.backup-${today()}`;
  try {
    copyFileSync(path, target);
  } catch (e) {
    throw new InstallError(`cannot back up ${path}: ${(e as Error).message}`);
  }
  return target;
}

function installViaClaudeCli(command: string, args: string[]): string[] {
  const argv = ['mcp', 'add', ENTRY, '-s', 'user', '--', command, ...args];
  const done = spawnSync('claude', argv, { encoding: 'utf8' });
  if (done.error) {
    const code = (done.error as NodeJS.ErrnoException).code;
    if (code === 'ENOENT') {
      throw new InstallError(
        'the `claude` command is not on PATH, so this cannot register with Claude Code. ' +
          'Install Claude Code, or add the entry by hand — `docs/install.md` gives the shape.',
      );
    }
    throw new InstallError(`could not run claude: ${done.error.message}`);
  }
  if (done.status !== 0) {
    const detail = (done.stderr || done.stdout || '').trim();
    throw new InstallError(
      `\`claude mcp add\` failed (exit ${done.status})${detail ? `\n${detail}` : ''}`,
    );
  }
  return argv;
}

/** Register this server with `host`. Returns the report to print; throws `InstallError`. */
export function install(host: Host, command: string, args: string[], force = false): string {
  if (!(HOSTS as readonly string[]).includes(host)) {
    throw new InstallError(`unknown host '${host}'; choose one of: ${HOSTS.join(', ')}`);
  }

  if (host === 'claude') {
    const argv = installViaClaudeCli(command, args);
    return `installed bantamkit into claude\n  ran    : claude ${argv.join(' ')}`;
  }

  const path = hostConfigPath(host);
  const key = configKey(host);
  const wanted = entryFor(host, command, args);

  const data = readConfig(path);
  const raw = data[key];
  if (raw !== undefined && (raw === null || typeof raw !== 'object' || Array.isArray(raw))) {
    throw new InstallError(`${path} has a '${key}' that is not an object; refusing to touch it`);
  }
  const servers = (raw ?? {}) as Record<string, unknown>;

  const existing = servers[ENTRY];
  if (existing !== undefined && dumps(existing, null, true) === dumps(wanted, null, true)) {
    return `bantamkit is already installed in ${host} and matches\n  file   : ${path}`;
  }
  if (existing !== undefined && !force) {
    throw new InstallError(
      `${host} already has a bantamkit entry with different settings\n` +
        `  file    : ${path}\n` +
        `  current : ${dumps(existing, null, true)}\n` +
        `  proposed: ${dumps(wanted, null, true)}\n` +
        '  re-run with --force to replace it',
    );
  }

  const copied = backup(path);
  servers[ENTRY] = wanted;
  data[key] = servers;
  writeConfig(path, data);

  const lines = [
    `installed bantamkit into ${host}`,
    `  file   : ${path}`,
    `  key    : ${key}`,
    `  command: ${command} ${args.join(' ')}`.replace(/\s+$/, ''),
  ];
  if (copied !== null) lines.push(`  backup : ${copied}`);
  return lines.join('\n');
}

/**
 * What a host should run to get THIS server.
 *
 * `npx -y bantamkit-mcp` and not this process's own path, and the two are not the same
 * thing: a global install, an `npx` cache entry and a checkout all have different paths,
 * while the published name resolves the same everywhere. `-y` because `npx` historically
 * prompts before installing a package it has not seen, and stdin here is the JSON-RPC
 * channel — a prompt that ate one frame would look like a server that lost a request.
 */
export function thisCommand(): { command: string; args: string[] } {
  return { command: 'npx', args: ['-y', 'bantamkit-mcp'] };
}
