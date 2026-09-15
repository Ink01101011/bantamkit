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
 * `<absolute node> <absolute .../dist/cli.js>`; the reference records its own console script.
 * The thing installed should be the thing that answers, and neither side should send a host
 * looking for the other's runtime. `docs/porting.md` carries the row.
 *
 * JOB51 CHANGED THIS SIDE'S COMMAND, AND THE REASON IS A MEASUREMENT. It used to be
 * `npx -y bantamkit-mcp`. On npm 11.6.2, with a WARM cache and the network cut (proxies pointed
 * at a closed port, which leaves the cache key alone), that command — pinned, unpinned or
 * `@latest` — hung silently past 45 s with zero bytes on stdout, so a host reports a handshake
 * timeout. A kept `npm install --prefix` launched as `<abs node> <abs dist/cli.js>` answered in
 * 0.11 s under a GUI-shaped PATH (`/usr/bin:/bin:/usr/sbin:/sbin`), where that install's own
 * `.bin/bantamkit-mcp` shim exits 127 (`env: node: No such file or directory`). The user ruled
 * (2026-09-15): `--install` makes a one-time kept install under `~/.bantamkit`, and the host
 * launches it without the network. See `thisCommand`.
 */
import { spawnSync } from 'node:child_process';
import {
  chmodSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { currentInstall, Undetermined } from './mcp/identity.js';
import { compareVersions, keptCli, keptManifest, keptPrefix, PACKAGE, runInstaller, shlexJoin } from './npminstall.js';
import { dumpJson, fromJs } from './pyjson.js';

export { keptCli, keptPrefix };

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

/**
 * `type(x).__name__` for the values `json.loads` can return.
 *
 * The reference prints CPython's type name and this sentence is compared byte for byte, so
 * `typeof` is wrong in five of the six cases: `string`/`str`, `number`/`int`, `boolean`/`bool`.
 * The first version of this translated only `list` and `NoneType` — and both unit tests used
 * `[1, 2, 3]`, the ONE input where the two vocabularies happen to agree, so neither suite
 * could see it. Review measured `"hello"` and `5`.
 *
 * `int` vs `float` follows `json`'s own split: a JSON number with no fraction and no exponent
 * is decoded by `int`, everything else by `float`.
 */
function pyTypeName(value: unknown): string {
  if (value === null) return 'NoneType';
  if (Array.isArray(value)) return 'list';
  if (typeof value === 'string') return 'str';
  if (typeof value === 'boolean') return 'bool';
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
  return typeof value;
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
    throw new InstallError(`${path} holds ${pyTypeName(loaded)}, not an object; refusing to touch it`);
  }
  return loaded as Record<string, unknown>;
}

function writeConfig(path: string, data: Record<string, unknown>): void {
  mkdirSync(dirname(path), { recursive: true });
  const tmp = `${path}.bantamkit-tmp`;
  // The mode of the file being replaced, carried onto its replacement. A host config holds
  // API keys in per-server `env` blocks, and a user who chmod'ed theirs to 0600 had it come
  // back 0644, because a fresh temp file gets the process umask. Measured on both runtimes
  // before this line existed.
  const mode = existsSync(path) ? statSync(path).mode & 0o7777 : null;
  try {
    writeFileSync(tmp, `${dumps(data, 2)}\n`, 'utf8');
    if (mode !== null) chmodSync(tmp, mode);
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
  // `shell: true` ON WINDOWS ONLY. An npm-installed `claude` is a `claude.cmd` shim, and
  // `spawnSync` refuses to launch a batch file without a shell — it returns ENOENT, which
  // this function would report as "not on PATH", the one message guaranteed to send someone
  // looking in the wrong place. The reference has no such problem: `shutil.which` honours
  // PATHEXT and `CreateProcess` runs the shim. Arguments are quoted because `shell: true`
  // hands the string to `cmd.exe`, and a path with a space is the normal case on Windows.
  const win = process.platform === 'win32';
  const quoted = win ? argv.map((a) => (/[\s"^&|<>]/.test(a) ? `"${a.replace(/"/g, '\\"')}"` : a)) : argv;
  const done = spawnSync('claude', quoted, { encoding: 'utf8', shell: win });
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

/** The seams `thisCommand` takes, so no test ever reaches npm or the network. */
export interface CommandOptions {
  /** The install shape. Default: `currentInstall().shape` — never a second detector. */
  readonly shape?: () => string;
  /** Runs an argv and returns `[exit code, output]`. Default: `npminstall.runInstaller`. */
  readonly installer?: (command: string[]) => [number, string];
  /** This process's version. Default: the `package.json` this build ships with. */
  readonly version?: string;
}

function ownVersion(): string {
  return (JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')) as { version: string })
    .version;
}

/** The kept install's version, or `null` when there is no readable manifest with one. */
function keptVersion(prefix: string): string | null {
  try {
    const manifest = JSON.parse(readFileSync(keptManifest(prefix), 'utf8')) as { version?: unknown };
    return typeof manifest.version === 'string' ? manifest.version : null;
  } catch {
    return null;
  }
}

/** The installer's last non-blank line — stderr's, when npm wrote any, since it is appended last. */
function lastLine(output: string): string {
  const lines = output.split(/\r?\n/).map((l) => l.trim()).filter((l) => l !== '');
  return lines.length === 0 ? 'it printed nothing' : (lines[lines.length - 1] ?? '');
}

/**
 * What a host should run to get THIS server: `<absolute node> <absolute dist/cli.js>`.
 *
 * NOT `npx -y bantamkit-mcp` ANY MORE — see the module header for the measurement: with a warm
 * cache and no network that command hangs silently, so a host that launches it offline sees a
 * handshake timeout. Not a bare `node` either, because a GUI host's PATH need not have one, and
 * not a `.bin` shim, whose `#!/usr/bin/env node` fails the same way (measured: exit 127).
 * `process.execPath` is the node binary running THIS process, which is known to work.
 *
 * WHICH `cli.js` DEPENDS ON THE INSTALL SHAPE, and the shape is `currentInstall()`'s answer:
 *
 *   - `ephemeral` (an `npx` cache): this process's own `cli.js` lives in a cache npm may discard,
 *     so the recorded one is the KEPT install at `keptPrefix()`. If its manifest already reports
 *     this version OR A NEWER ONE and its `cli.js` is there, nothing runs — a second `--install`
 *     for another host works offline, and a stale `npx` cache never moves a kept install that
 *     `--update` took further back to its own version (J51-9a). Otherwise `npm install --prefix <kept> bantamkit-mcp@<this version>`
 *     runs once, through the same spawner `--update` uses, and the `cli.js` is confirmed after.
 *     npm creates a missing prefix directory itself (measured, npm 11.6.2), so nothing is made
 *     here first and a failed install leaves no empty directory of this module's making.
 *   - every other shape (`registry`, `local-file`, `linked`, `checkout`) is already kept, so it
 *     is this process's own `dist/cli.js`.
 *
 * Every failure is an `InstallError` thrown BEFORE any host configuration is read or written.
 */
export function thisCommand(options: CommandOptions = {}): { command: string; args: string[] } {
  let shape: string;
  try {
    shape = (options.shape ?? ((): string => currentInstall().shape))();
  } catch (e) {
    if (!(e instanceof Undetermined)) throw e;
    throw new InstallError(
      `--install could not tell how this install was made, so it will not guess which copy a host should launch: ${e.message}`,
    );
  }
  const node = process.execPath;
  if (shape !== 'ephemeral') {
    return { command: node, args: [fileURLToPath(new URL('./cli.js', import.meta.url))] };
  }

  const version = options.version ?? ownVersion();
  const prefix = keptPrefix();
  const cli = keptCli(prefix);
  const kept = keptVersion(prefix);
  // NEVER LOWER THE KEPT INSTALL (J51-9a). An `npx` cache can be older than the kept install —
  // `--update` moved the kept install on, and this cache was filled weeks ago — and every host
  // already launches the kept one, so installing THIS version over it would move them all back.
  // A kept version at or above this one is recorded as it is. `compareVersions` is total: a
  // component that is not all digits sorts after every number, so a version it cannot read as
  // numbers counts as newer and is left alone rather than overwritten. A blank one is no version.
  if (kept !== null && kept.trim() !== '' && compareVersions(kept, version) >= 0 && existsSync(cli)) {
    return { command: node, args: [cli] };
  }

  const command = ['npm', 'install', '--prefix', prefix, `${PACKAGE}@${version}`];
  const rendered = shlexJoin(command);
  const [code, output] = (options.installer ?? runInstaller)(command);
  const refused = `could not make the kept install at ${prefix}, so no host configuration was changed: ${rendered} exited ${code}`;
  if (code !== 0) throw new InstallError(`${refused}: ${lastLine(output)}`);
  if (!existsSync(cli)) throw new InstallError(`${refused} but left no ${cli}`);
  return { command: node, args: [cli] };
}

/**
 * `--install <host>` whole: resolve the command (making the kept install if this is an `npx`
 * cache), THEN touch the host. The order is the property: a refusal from npm leaves the host's
 * file byte-unchanged with no backup, because `install` has not been reached.
 */
export function installSelf(host: Host, force = false, options: CommandOptions = {}): string {
  if (!(HOSTS as readonly string[]).includes(host)) {
    throw new InstallError(`unknown host '${host}'; choose one of: ${HOSTS.join(', ')}`);
  }
  const { command, args } = thisCommand(options);
  return install(host, command, args, force);
}
