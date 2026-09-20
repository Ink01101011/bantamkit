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
import { bantamkitDirFor, ensureBantamkitGitignore } from './memory/store.js';
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
  // THE THIRD `.bantamkit` CREATOR (J54-3), and the one that creates the most of it: npm makes
  // a missing `--prefix` itself, so this line — not `MemoryStore`, not `EventLog` — is what
  // brings `<homedir>/.bantamkit` into existence on a machine that has never saved a memory.
  // Measured on the machine this was found on: 28 MB of install tree under a `~/.bantamkit`
  // with no `.gitignore`, every byte of it untracked in a `$HOME` that is a git repository.
  //
  // Checked BEFORE npm runs, per user ruling #2, for the reason both other creators check it
  // before their own mkdir: afterwards the directory exists either way and the question
  // "did THIS call create it" is unanswerable. A `~/.bantamkit` that was already there —
  // holding an older kept install, a memory store, or an ignore file the operator deleted on
  // purpose — is left exactly as it is.
  const bantamkitDir = bantamkitDirFor(prefix);
  const bantamkitDirExistedBefore = bantamkitDir !== null && existsSync(bantamkitDir);
  const [code, output] = (options.installer ?? runInstaller)(command);
  // BEFORE THE REFUSALS, AND THAT ORDER IS MEASURED, not tidy. A `npm install --prefix` that
  // FAILS still leaves the prefix behind: measured 2026-09-18 with `npm_config_offline=true`
  // against an empty cache — exit 1, and `<home>/.bantamkit/mcp` there afterwards. A refusal
  // that returned first would leave exactly the directory this closes over: made by bantamkit's
  // own command, holding nothing anybody asked for, and visible to git. The helper never
  // creates `bantamkitDir` itself, so an installer that made nothing writes nothing here.
  if (bantamkitDir !== null) ensureBantamkitGitignore(bantamkitDir, !bantamkitDirExistedBefore);
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

/*
 * ============================================================================================
 * `--install-hooks` / `--remove-hooks` — the SEVEN hook entries in `~/.claude/settings.json`
 * ============================================================================================
 *
 * THIS IS THE ONE SURFACE IN THIS PROGRAM THAT ASKS BEFORE IT WRITES, AND THAT IS A RULING,
 * not a style. `--install` writes a file that exists to hold server entries; this writes the
 * user's own settings file and registers a command that runs on EVERY tool call. The stronger
 * write gets the stronger gate (S1 RULING Q3.3).
 *
 * `tools/hooks/install.mjs` is the ANTI-PATTERN this replaces, not the template. It writes the
 * same seven entries unconditionally: no plan, no question, no backup. Everything below is the
 * same data with a gate and `--install`'s existing write discipline around it.
 *
 * THE THREE-STATE GATE LIVES HERE AND THE TERMINAL DOES NOT. `ask` is a seam: a function when
 * there is a terminal to ask at, `null` when there is none. `cli.ts` supplies the real one off
 * `process.stdin.isTTY` — the same signal `typedBareAtATerminal` uses and for the same reason.
 * Keeping the seam here is what makes the two REFUSING states testable without a pty, and a
 * refusal nothing can test is a refusal nobody has seen work.
 *
 *   ask is a function        -> print the plan, ask, and honour the answer
 *   yes is true              -> print the plan and proceed; `--yes` is written-down consent
 *   ask is null and no --yes -> HookConsentUnavailable. Nothing is printed, nothing is written.
 *
 * WHAT IS NOT WRITTEN HERE, EVER: `BANTAMKIT_DREAM_TIMEOUT_MS`. It is a TEST seam, and a seam
 * that reaches a user's settings file stops being one.
 */

/**
 * The seven events, their matchers, and the ORDER RULING Q3.4 prints them in.
 *
 * The data is `tools/hooks/install.mjs:22–32`; the order is the ruled `events :` line, which
 * is not that file's order. Both runtimes iterate this list, so it also decides the key order
 * of a freshly written `hooks` object and therefore the bytes on disk.
 *
 * `PostToolUse` IS MATCHER-LESS AND MUST STAY THAT WAY. Its arm logs a usage event for EVERY
 * tool call and runs the `memory_save` half only when the tool was that one. A second, narrower
 * entry beside it would fire the save half twice.
 */
export const HOOK_EVENTS: readonly (readonly [string, string | null])[] = [
  ['SessionStart', 'startup|resume|clear|compact'],
  ['PreToolUse', 'Read'],
  ['PostToolUse', null],
  ['UserPromptSubmit', null],
  ['PreCompact', null],
  ['PostCompact', null],
  ['Stop', null],
];

/** The per-entry `timeout`, in seconds, carried from `tools/hooks/install.mjs`. */
export const HOOK_TIMEOUT = 10;

/**
 * The only file these two flags touch: `~/.claude/settings.json`, user scope.
 *
 * RULING Q3.8 — hooks are a Claude Code concept, `--install-hooks` takes no host argument, and
 * the other three hosts in `HOSTS` get nothing. Resolved from `homedir()` and nothing else, so
 * pointing `HOME` at a scratch directory moves it, which is what makes the tests possible.
 */
export function claudeSettingsPath(): string {
  return join(homedir(), '.claude', 'settings.json');
}

/** The one command all seven entries run. The event arrives on stdin, never in argv. */
export function hookCommand(command: string, args: readonly string[]): string {
  return shlexJoin([command, ...args, '--hook']);
}

/** There is no terminal to ask at and `--yes` was not given. Exit 2, and nothing was written. */
export class HookConsentUnavailable extends Error {}

/** The person was asked and did not say yes. Exit 1, and nothing was written. */
export class HookDeclined extends Error {}

/** The seams the two hook flags take. Nothing here reaches a terminal or the network. */
export interface HookOptions extends CommandOptions {
  /** Consent. A function when there is a terminal; `null` when there is none. */
  readonly ask?: (() => boolean) | null;
  /** `--yes`: the written-down consent that stands in for the terminal. */
  readonly yes?: boolean;
  /** Where the plan and the question go. Default: nowhere — `cli.ts` sends them to stderr. */
  readonly tell?: (text: string) => void;
}

/** One entry, in the shape Claude Code reads. `matcher` first, and only where there is one. */
function hookEntry(matcher: string | null, command: string): Record<string, unknown> {
  const entry: Record<string, unknown> = {};
  if (matcher !== null) entry['matcher'] = matcher;
  entry['hooks'] = [{ type: 'command', command, timeout: HOOK_TIMEOUT }];
  return entry;
}

/**
 * RULING Q3.6's idempotence rule, and the whole of it: an entry is OURS when its JSON mentions
 * `bantamkit`. Every other hook the operator has is left byte-for-byte.
 *
 * `dumps` rather than `JSON.stringify` for the reason the module header gives — the two write
 * different separators — and `sortKeys` so the same entry renders the same way whatever order
 * its keys arrived in.
 */
function isOurs(entry: unknown): boolean {
  return dumps(entry, null, true).includes('bantamkit');
}

/** The `hooks` object, validated. Refuses by name rather than crashing on somebody's file. */
function readHooks(path: string, data: Record<string, unknown>): Record<string, unknown[]> {
  const raw = data['hooks'];
  if (raw === undefined) return {};
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new InstallError(`${path} has a 'hooks' that is not an object; refusing to touch it`);
  }
  const hooks: Record<string, unknown[]> = {};
  for (const [event, entries] of Object.entries(raw as Record<string, unknown>)) {
    if (!Array.isArray(entries)) {
      throw new InstallError(`${path} has a 'hooks.${event}' that is not a list; refusing to touch it`);
    }
    hooks[event] = [...entries];
  }
  return hooks;
}

/**
 * The `hooks` object this run wants, built from whatever is there now.
 *
 * ONE PASS OVER THE SEVEN EVENTS AND NOTHING ELSE: every event keeps its non-bantamkit entries
 * in their existing order, ours is appended after them, and an event left with none loses its
 * key rather than holding an empty list — `install.mjs`'s rule, kept because a settings file
 * full of empty arrays is a worse artefact than one with nothing in it.
 *
 * Events outside the seven are not read, not reordered and not removed.
 */
function plannedHooks(
  current: Record<string, unknown[]>,
  command: string,
  remove: boolean,
): { hooks: Record<string, unknown[]>; touched: string[] } {
  const hooks: Record<string, unknown[]> = { ...current };
  const touched: string[] = [];
  for (const [event, matcher] of HOOK_EVENTS) {
    const before = hooks[event] ?? [];
    const kept = before.filter((entry) => !isOurs(entry));
    if (remove) {
      if (kept.length !== before.length) touched.push(event);
    } else {
      kept.push(hookEntry(matcher, command));
      touched.push(event);
    }
    if (kept.length > 0) hooks[event] = kept;
    else delete hooks[event];
  }
  return { hooks, touched };
}

const EVENT_NAMES = HOOK_EVENTS.map(([event]) => event).join(' ');

/**
 * RULING Q3.4's plan, printed before any question and before any write.
 *
 * THE `backup :` LINE IS OMITTED WHEN THERE IS NO FILE TO BACK UP, which is `--install`'s own
 * report discipline (`backup` returns `null` and the line does not print). The ruled template
 * shows the line because the ordinary case has a file; printing a backup path for a file that
 * does not exist would be the plan stating something the write will not do.
 */
function hookPlan(path: string, command: string): string {
  const lines = [
    `bantamkit would add ${HOOK_EVENTS.length} hook entries to ${path}`,
    `  events : ${EVENT_NAMES}`,
    `  command: ${command}`,
  ];
  if (existsSync(path)) lines.push(`  backup : ${path}.backup-${today()}`);
  lines.push('Existing hooks are left byte-for-byte; only entries naming bantamkit are replaced.');
  return `${lines.join('\n')}\n`;
}

/**
 * `--install-hooks`: the seven entries, in ONE write, AFTER asking.
 *
 * THE ORDER IS THE PROPERTY, and it is `installSelf`'s order for `installSelf`'s reason:
 *
 *   1. resolve the command — on an `npx` cache this makes the kept install, and npm failing
 *      there is an `InstallError` thrown before the settings file has been opened at all;
 *   2. read and validate the settings file — a file that does not parse is reported, never
 *      overwritten;
 *   3. ALREADY-INSTALLED-AND-MATCHING RETURNS HERE, before the gate. There is no write to
 *      consent to, so a second `--install-hooks` is a no-op at exit 0 whether or not anybody
 *      is at a terminal, which is what makes it safe in a setup script;
 *   4. print the plan, then the gate;
 *   5. dated backup, then one atomic write.
 *
 * The write itself is `writeConfig` — the same temp-file replace, the same carried mode, the
 * same `indent: 2` through `dumps` — so the bytes this leaves and the bytes `--install` leaves
 * are produced by one function (RULING Q3.5).
 */
export function installHooks(options: HookOptions = {}): string {
  const { command, args } = thisCommand(options);
  const rendered = hookCommand(command, args);
  const path = claudeSettingsPath();
  const data = readConfig(path);
  const current = readHooks(path, data);
  const { hooks } = plannedHooks(current, rendered, false);

  if (dumps(hooks, null, true) === dumps(current, null, true)) {
    return `bantamkit hooks are already installed in ${path} and match`;
  }

  const tell = options.tell ?? ((): void => {});
  const yes = options.yes ?? false;
  const ask = options.ask ?? null;
  if (!yes) {
    if (ask === null) {
      // NOTHING IS PRINTED HERE. The plan describes a write that is not going to happen, and
      // the refusal is the whole message.
      throw new HookConsentUnavailable(
        '--install-hooks writes your ~/.claude/settings.json and needs a terminal to ask.\n' +
          'There is no terminal here, so nothing was written. Re-run it at a prompt, or pass\n' +
          '--yes to say yes in advance.',
      );
    }
    tell(hookPlan(path, rendered));
    if (!ask()) throw new HookDeclined('no hooks were written');
  } else {
    tell(hookPlan(path, rendered));
  }

  const copied = backup(path);
  data['hooks'] = hooks;
  writeConfig(path, data);

  const lines = [
    `installed bantamkit hooks into ${path}`,
    `  events : ${EVENT_NAMES}`,
    `  command: ${rendered}`,
  ];
  if (copied !== null) lines.push(`  backup : ${copied}`);
  lines.push('restart Claude Code (or run /hooks) for this to take effect');
  return lines.join('\n');
}

/**
 * `--remove-hooks`: take out what bantamkit wrote, and nothing else.
 *
 * NO CONSENT PROMPT (RULING Q3.7). Removing what bantamkit added is not a write to somebody
 * else's configuration in the sense the ruling is about. It still takes the dated backup, it
 * still touches only entries naming bantamkit, and a file with none of ours is left
 * byte-unchanged with no backup taken.
 *
 * `thisCommand` IS NOT CALLED. Removal does not need to know what a host should launch, and
 * calling it would put an `npx` cache's kept install between an operator and the ability to
 * undo. `options` still takes the same shape so the two flags read the same way.
 */
export function removeHooks(options: HookOptions = {}): string {
  void options;
  const path = claudeSettingsPath();
  const data = readConfig(path);
  const current = readHooks(path, data);
  const { hooks, touched } = plannedHooks(current, '', true);

  if (touched.length === 0) return `no bantamkit hooks are installed in ${path}`;

  const copied = backup(path);
  data['hooks'] = hooks;
  writeConfig(path, data);

  const lines = [`removed bantamkit hooks from ${path}`, `  events : ${touched.join(' ')}`];
  if (copied !== null) lines.push(`  backup : ${copied}`);
  lines.push('restart Claude Code (or run /hooks) for this to take effect');
  return lines.join('\n');
}
