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
 *   2. The file is written through `hostJsonText`, which reproduces the reference's
 *      `json.dumps(data, indent=<the file's own unit>, ensure_ascii=False)` (#118): the user's
 *      Thai text stays Thai, their 4-space or tab indent stays theirs, and the two runtimes
 *      still write identical bytes — `install-host-text` in the install suite compares them.
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
  lstatSync,
  mkdirSync,
  readFileSync,
  readlinkSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { currentInstall, Undetermined } from './mcp/identity.js';
import { bantamkitDirFor, ensureBantamkitGitignore } from './memory/store.js';
import { compareVersions, keptCli, keptManifest, keptPrefix, PACKAGE, runInstaller, shlexJoin } from './npminstall.js';
import { dumpJson, fromJs, parseJson, PyJSONDecodeError, type PyValue } from './pyjson.js';

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
 * THE HOST FILE IS HELD AS THE REFERENCE HOLDS IT (#118): a tagged `PyValue` from
 * `parseJson`, never a `JSON.parse` object. The difference is the user's own data: through a
 * JS number `12345678901234567890` becomes `1.2345678901234567e+19`, `1.0` becomes `1`, and
 * `1e400` becomes `Infinity` and is written back as that bare word, which no JSON parser —
 * Cursor's included — will read. Through a JS object an integer-like key such as `"9"` moves
 * to the front. A `Map` of `PyValue`s keeps the int/float split, the arbitrary precision and
 * the key order the file had, so `dumpJson` writes back the bytes `json.dumps` writes.
 */
type PyDict = { readonly t: 'dict'; readonly v: Map<string, PyValue> };
const pyDict = (entries?: Iterable<readonly [string, PyValue]>): PyDict => ({ t: 'dict', v: new Map(entries) });

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
 * Since #118 the value is tagged by the same split `json` makes — a JSON number with no
 * fraction and no exponent is `int`, everything else `float` — so the tag IS the name.
 */
function pyTypeName(value: PyValue): string {
  switch (value.t) {
    case 'null':
      return 'NoneType';
    case 'bool':
      return 'bool';
    case 'int':
      return 'int';
    case 'float':
      return 'float';
    case 'str':
      return 'str';
    case 'list':
      return 'list';
    case 'dict':
      return 'dict';
  }
}

/**
 * The first non-finite float in `value`, with where it sits, or `null`. Depth-first, in
 * document order, so both runtimes name the same number when a file holds two.
 */
function nonFiniteIn(value: PyValue, trail: readonly (string | number)[]): { where: string; value: number } | null {
  if (value.t === 'float' && !Number.isFinite(value.v)) return { where: whereIs(trail), value: value.v };
  if (value.t === 'dict') {
    for (const [key, item] of value.v) {
      const found = nonFiniteIn(item, [...trail, key]);
      if (found !== null) return found;
    }
  } else if (value.t === 'list') {
    for (const [index, item] of value.v.entries()) {
      const found = nonFiniteIn(item, [...trail, index]);
      if (found !== null) return found;
    }
  }
  return null;
}

/** `mcpServers.other.huge`, `servers.list[2]`: keys joined by `.`, indexes in brackets. */
function whereIs(trail: readonly (string | number)[]): string {
  let out = '';
  for (const segment of trail) {
    if (typeof segment === 'number') out += `[${segment}]`;
    else out += out === '' ? segment : `.${segment}`;
  }
  return out === '' ? 'the top level' : out;
}

function readConfig(path: string): PyDict {
  if (!existsSync(path)) return pyDict();
  let text: string;
  try {
    text = readFileSync(path, 'utf8');
  } catch (e) {
    throw new InstallError(`cannot read ${path}: ${(e as Error).message}`);
  }
  if (text.trim() === '') return pyDict();
  let loaded: PyValue;
  try {
    loaded = parseJson(text);
  } catch (e) {
    if (!(e instanceof PyJSONDecodeError)) throw e;
    // The reference reports CPython's message, line and column, and so does this parser —
    // the ruling that once covered V8's `Unexpected token …` wording retired with #118.
    throw new InstallError(
      `${path} is not valid JSON, so this refuses to touch it: ${e.msg} (line ${e.lineno}, column ${e.colno})`,
    );
  }
  if (loaded.t !== 'dict') {
    throw new InstallError(`${path} holds ${pyTypeName(loaded)}, not an object; refusing to touch it`);
  }
  // A NUMBER JSON CANNOT CARRY IS REFUSED HERE, before anything is planned (#118). `1e400`
  // decodes to `Infinity` and `dumpJson` — faithful to `json.dumps` — would write it back as
  // that bare word, which no JSON parser accepts: the host then cannot read ANY of its
  // servers, and the next run of this very command refuses its own output. The literals
  // `NaN`/`Infinity` that CPython's decoder tolerates take the same door.
  const found = nonFiniteIn(loaded, []);
  if (found !== null) {
    const spelled = dumpJson({ t: 'float', v: found.value });
    throw new InstallError(`${path} has a number at ${found.where} that JSON cannot carry (${spelled}); refusing to touch it`);
  }
  return loaded;
}

/**
 * Where the bytes land: the file ITSELF, through any symlink (#136).
 *
 * A dotfiles user keeps `~/.cursor/mcp.json` as a link into a repository. Writing a temp file
 * beside the LINK and renaming it onto the link's name replaces the link with a detached
 * regular file: the repository copy never gets the entry and the next sync reverts it without
 * a word. `realpathSync` wants the target to exist; a link whose target is not there yet is
 * followed by hand (the reference's `os.path.realpath` is non-strict), so the write creates
 * the target and the link stays a link either way.
 */
function writeTarget(path: string): string {
  try {
    return realpathSync(path);
  } catch {
    // ENOENT: a fresh file, or a link whose target does not exist yet.
  }
  let at = path;
  for (let hops = 0; hops < 40; hops += 1) {
    let link: string;
    try {
      if (!lstatSync(at).isSymbolicLink()) return at;
      link = readlinkSync(at);
    } catch {
      return at;
    }
    at = resolve(dirname(at), link);
  }
  return at;
}

/**
 * Write the whole document, atomically, leaving no half-file behind on a crash — and atomic
 * ONTO THE REAL FILE: the temp file is made beside `writeTarget(path)` and renamed onto it, so
 * a symlinked config is written through rather than swapped for a regular file.
 */
function writeConfig(path: string, data: PyValue): void {
  mkdirSync(dirname(path), { recursive: true });
  const target = writeTarget(path);
  if (target !== path) mkdirSync(dirname(target), { recursive: true });
  const tmp = `${target}.bantamkit-tmp`;
  // The mode of the file being replaced, carried onto its replacement. A host config holds
  // API keys in per-server `env` blocks, and a user who chmod'ed theirs to 0600 had it come
  // back 0644, because a fresh temp file gets the process umask. Measured on both runtimes
  // before this line existed.
  const mode = existsSync(target) ? statSync(target).mode & 0o7777 : null;
  try {
    writeFileSync(tmp, `${hostJsonText(data, detectedIndent(target))}\n`, 'utf8');
    if (mode !== null) chmodSync(tmp, mode);
    renameSync(tmp, target);
  } catch (e) {
    rmSync(tmp, { force: true });
    throw new InstallError(`cannot write ${path}: ${(e as Error).message}`);
  }
}

/**
 * The indent unit the file already uses: a tab, or N spaces; two for a new file (#118).
 *
 * Read off the FIRST line that starts with whitespace and has something after it. A JSON
 * string cannot hold a raw newline, so every line start is structural and that line is a
 * depth-one member. A file with no such line (absent, empty, all on one line) gets two
 * spaces, which is what this writer always used. The reference's `_detected_indent` applies
 * the same rule to the same text.
 *
 * Lines break where Python's universal newlines break them — `\r\n`, a bare `\r`, or `\n` —
 * because the reference reads through `Path.read_text`, which translates all three. Splitting
 * on `\n` alone saw a classic-Mac (CR-only) file as one line, fell back to two spaces, and so
 * wrote different bytes from the reference and lost the file's indent (#118, review J66-12 B1).
 */
function detectedIndent(path: string): string {
  let text: string;
  try {
    text = readFileSync(path, 'utf8');
  } catch {
    return '  ';
  }
  for (const line of text.split(/\r\n|\r|\n/)) {
    if ((line[0] !== ' ' && line[0] !== '\t') || !/[^ \t\r]/.test(line)) continue;
    if (line[0] === '\t') return '\t';
    return ' '.repeat(line.length - line.replace(/^ +/, '').length);
  }
  return '  ';
}

/**
 * The host file's text: the user's indent unit, non-ASCII as literal UTF-8 (#118) — the
 * bytes the reference's `json.dumps(data, indent=<unit>, ensure_ascii=False)` writes.
 *
 * Built from `dumpJson`'s `ensure_ascii` output at indent 2, which is already CPython's in
 * every other respect, by two rewrites that cannot touch a string's meaning:
 *   - indentation: every line start in that output is structural (a string holds no raw
 *     newline), and its leading spaces are exactly 2 × depth, so they become unit × depth;
 *   - escapes: each `\uXXXX` at 0x7f or above goes back to the character itself — a valid
 *     surrogate PAIR as one astral character — which is what `ensure_ascii=False` writes
 *     (it escapes only `"`, `\` and C0). A LONE surrogate stays escaped: UTF-8 cannot carry
 *     it, and the reference writes it back the same way. A `\\` pair is consumed first, so
 *     the text `ก` inside a string (an escaped backslash) is never mistaken for one.
 */
function hostJsonText(data: PyValue, indent: string): string {
  const ascii = dumpJson(data, { indent: 2 });
  const unescaped = ascii.replace(
    /\\u(d[89ab][0-9a-f]{2})\\u(d[c-f][0-9a-f]{2})|\\u([0-9a-f]{4})|\\[^u]/g,
    (whole, high?: string, low?: string, single?: string) => {
      if (high !== undefined && low !== undefined) {
        return String.fromCharCode(parseInt(high, 16), parseInt(low, 16));
      }
      if (single === undefined) return whole;
      const unit = parseInt(single, 16);
      if (unit < 0x7f || (unit >= 0xd800 && unit <= 0xdfff)) return whole;
      return String.fromCharCode(unit);
    },
  );
  if (indent === '  ') return unescaped;
  return unescaped.replace(/^((?: {2})+)/gm, (lead: string) => indent.repeat(lead.length / 2));
}

/** `date.today().isoformat()` — the LOCAL date, which is what the reference takes. */
function today(): string {
  const now = new Date();
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** `os.path.lexists`: there is SOMETHING at this name, a dangling link included. */
function lexists(path: string): boolean {
  try {
    lstatSync(path);
    return true;
  } catch {
    return false;
  }
}

/**
 * The name the next backup of `path` gets: the first one that is not taken.
 *
 * `<name>.backup-<date>` when nothing holds that name, then `<name>.backup-<date>.1`, `.2`,
 * ... on the same day. The plan lines print this same name before the write, so what the
 * plan says and what the write does are one computation.
 */
function backupTarget(path: string): string {
  const stamp = today();
  let candidate = `${path}.backup-${stamp}`;
  for (let n = 1; lexists(candidate); n += 1) candidate = `${path}.backup-${stamp}.${n}`;
  return candidate;
}

/**
 * Copy the file aside before changing it. Returns the copy, or `null` if there was none.
 *
 * Dated, so a person looking at their own config directory a week later can tell when it
 * happened — and NEVER OVERWRITTEN (#138). Until job65 a second run on the same day wrote the
 * same `<name>.backup-<date>` on purpose, "rather than growing a pile nobody prunes"; the
 * README's undo promise is that the backup restores the file as it was BEFORE bantamkit
 * touched it, and the second run was overwriting exactly that copy with the first run's
 * output. A pile of dated copies is the price of an undo that works; the counter suffix is
 * the price of keeping the documented name for the first one.
 *
 * `copyFileSync` follows a symlink on the source, so the copy holds the REAL file's bytes and
 * sits beside the path the report names.
 */
function backup(path: string): string | null {
  if (!existsSync(path)) return null;
  const target = backupTarget(path);
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
  const raw = data.v.get(key);
  if (raw !== undefined && raw.t !== 'dict') {
    throw new InstallError(`${path} has a '${key}' that is not an object; refusing to touch it`);
  }
  const servers: PyDict = raw ?? pyDict();

  // MEMBERSHIP, not a null test: `"bantamkit": null` is an entry (`PY_NONE`, not `undefined`).
  const existing = servers.v.get(ENTRY);
  if (existing !== undefined && dumpJson(existing, { sortKeys: true }) === dumps(wanted, null, true)) {
    return `bantamkit is already installed in ${host} and matches\n  file   : ${path}`;
  }
  if (existing !== undefined && !force) {
    throw new InstallError(
      `${host} already has a bantamkit entry with different settings\n` +
        `  file    : ${path}\n` +
        `  current : ${dumpJson(existing, { sortKeys: true })}\n` +
        `  proposed: ${dumps(wanted, null, true)}\n` +
        '  re-run with --force to replace it',
    );
  }

  const copied = backup(path);
  servers.v.set(ENTRY, fromJs(wanted));
  data.v.set(key, servers);
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
 * BOTH FLAGS TAKE IT. RULING Q3.7 used to exempt `--remove-hooks` on the reasoning that taking
 * back out what bantamkit put in is not a write to somebody else's configuration. THE USER
 * OVERTURNED THAT ON 2026-09-20, and the reason is on disk: earlier the same day an
 * unsandboxed probe let the abbreviation `--remove` resolve to the newly-added
 * `--remove-hooks`, and it ran against the operator's REAL `~/.claude/settings.json` with no
 * terminal, no `--yes` and exit 0 — 256 lines / 9031 bytes / 12 hook-event keys / 18 matcher
 * blocks became 188 / 6980 / 10 / 11, with `PreCompact` and `PostCompact` gone. The file it
 * rewrites is the same file either way, so the gate is the same gate either way: an operator
 * who has learned one of these two flags must not be surprised by the other.
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

/**
 * THE REFUSAL, FOR BOTH FLAGS, FROM ONE TEMPLATE.
 *
 * Written as a function rather than twice as a literal so the two flags CANNOT grow two
 * different consent stories by drift: the only thing either one may vary is its own name and
 * the verb for what it is about to do to the file. The `--install-hooks` string this produces
 * is byte-identical to the one that shipped before `--remove-hooks` joined it.
 */
function consentUnavailable(flag: string, verb: string): HookConsentUnavailable {
  return new HookConsentUnavailable(
    `${flag} ${verb} your ~/.claude/settings.json and needs a terminal to ask.\n` +
      'There is no terminal here, so nothing was written. Re-run it at a prompt, or pass\n' +
      '--yes to say yes in advance.',
  );
}

/** The seams the two hook flags take. Nothing here reaches a terminal or the network. */
export interface HookOptions extends CommandOptions {
  /** Consent. A function when there is a terminal; `null` when there is none. */
  readonly ask?: (() => boolean) | null;
  /** `--yes`: the written-down consent that stands in for the terminal. */
  readonly yes?: boolean;
  /** Where the plan and the question go. Default: nowhere — `cli.ts` sends them to stderr. */
  readonly tell?: (text: string) => void;
}

/**
 * THE OWNERSHIP MARKER, AND IT IS THE WHOLE OF THE ANSWER TO "is this entry ours".
 *
 * WRITTEN ON THE INNER HOOK OBJECT, not on the entry, and that placement is MEASURED rather
 * than assumed (J62-22, Claude Code 2.1.278, extracted from the binary at the `edit_hook`
 * implementation). The host parses a hook with a non-strict zod union and then, on a `/hooks`
 * edit, puts back every key the parse dropped:
 *
 *     function R(e,o){let t=o,a={};
 *       if(h(e)){let n=gSe().safeParse(e);
 *         if(n.success){for(let i of Object.keys(e))if(!(i in n.data)&&!A.has(i))a[i]=e[i]; …}}
 *       let r={...a,...t}; …}                 // A = {"__proto__","constructor","prototype"}
 *
 * That loop is unknown-key preservation written on purpose, and the deny-list it consults holds
 * only the three prototype-pollution names. The surrounding entry is preserved too, but only
 * incidentally (`(d??[]).map((f)=>…?{...f,hooks:[...f.hooks]}:f)` — a raw spread), so the key
 * goes where the host has code that means to keep it.
 *
 * AND THE HOOK STILL FIRES WITH IT THERE. Measured live, not reasoned from the schema: two
 * sandboxed HOMEs, identical settings but for this key, `claude -p` pointed at a dead
 * localhost so the session starts and the model call cannot leave the machine — SessionStart
 * and UserPromptSubmit fired twice on BOTH sides. The control matters: the same probe run
 * through `claude mcp list` fires nothing on either side, and would have "passed" vacuously.
 *
 * PRESENCE IS THE TEST AND THE VALUE IS NEVER READ. A future release may want to write a
 * different value here; if the value were part of the test, that release would orphan every
 * entry the previous one wrote — which is the exact bug this marker exists to end.
 */
export const HOOK_MARKER_KEY = 'bantamkit';
/** What we write today. Informational only — {@link HOOK_MARKER_KEY}'s presence decides. */
export const HOOK_MARKER_VALUE = 'hook';

/** One entry, in the shape Claude Code reads. `matcher` first, and only where there is one. */
function hookEntry(matcher: string | null, command: string): Record<string, unknown> {
  const entry: Record<string, unknown> = {};
  if (matcher !== null) entry['matcher'] = matcher;
  entry['hooks'] = [
    { type: 'command', command, timeout: HOOK_TIMEOUT, [HOOK_MARKER_KEY]: HOOK_MARKER_VALUE },
  ];
  return entry;
}

/** The `hooks` object as this module holds it: event -> its entries, in the file's order. */
type HookTable = Map<string, PyValue[]>;

/** `{"event": [...]}` as a `PyValue`, for the one comparison and the one write that need it. */
const asPyValue = (table: HookTable): PyValue =>
  ({ t: 'dict', v: new Map([...table].map(([event, entries]) => [event, { t: 'list', v: entries }])) });

/** The `str` behind a key, or `undefined` when the key is absent or holds something else. */
const strAt = (dict: PyDict, key: string): string | undefined => {
  const value = dict.v.get(key);
  return value !== undefined && value.t === 'str' ? value.v : undefined;
};

/**
 * The two command spellings bantamkit ever wrote, for entries that predate the marker.
 *
 *   1. `tools/hooks/install.mjs` wrote `node <abs>/tools/hooks/bantamkit-hook.mjs`, and its own
 *      ownership test was the literal `bantamkit-hook`. That token is in the FILENAME, so it is
 *      there whatever the checkout is called — this arm is path-independent and stays exact.
 *   2. This module, before the marker, wrote `<interpreter> <entry point> --hook`. Recognising
 *      it needs the command to name bantamkit, which is the defect itself: on an install path
 *      that does not carry the word, such an entry says nothing about who wrote it and NO
 *      entry-local test can claim it. `--install-hooks` never shipped (it is new in 0.35.4), so
 *      that population is bounded to this repository's own development checkouts; `docs/hooks.md`
 *      says so and says to delete those by hand.
 *
 * BOTH ARMS ARE NARROWER THAN THE TEST THEY REPLACE, ON PURPOSE. The old one asked whether the
 * entry's JSON happened to contain `bantamkit` anywhere, so a matcher, a `statusMessage` or a
 * third-party script with the word in its filename was claimed as ours and deleted.
 */
function isLegacyOurs(hook: PyDict): boolean {
  if (strAt(hook, 'type') !== 'command') return false;
  const command = strAt(hook, 'command');
  if (command === undefined || !command.includes('bantamkit')) return false;
  return command.includes('bantamkit-hook') || command === '--hook' || command.endsWith(' --hook');
}

/** ONE inner hook object: ours by marker, or by one of the two legacy spellings. */
function isOurHook(hook: PyValue): boolean {
  return hook.t === 'dict' && (hook.v.has(HOOK_MARKER_KEY) || isLegacyOurs(hook));
}

/**
 * RULING Q3.6's idempotence rule, RE-DECIDED ON THE ENTRY ALONE (J62-22).
 *
 * It used to read `dumps(entry, null, true).includes('bantamkit')` — does this entry's JSON
 * happen to contain the product's name. On this machine every checkout is called `bantamkit*`,
 * so the entry's own command carried the word and the test looked correct. MEASURED from an
 * install tree whose path does not: three `--install-hooks --yes` left TWENTY-ONE entries
 * instead of seven, and `--remove-hooks --yes` then answered `no bantamkit hooks are installed`
 * on BOTH runtimes — hook entries in a user's settings that neither runtime could ever take
 * back out, growing by seven on every reinstall. An npm install under another name, a Docker
 * image that copies `dist/` to `/app/dist/`, and any vendored build all reach it.
 *
 * Ownership is now a property of the ENTRY and of nothing else: our marker, or one of the two
 * shapes we wrote before the marker existed. Where any binary lives is not consulted.
 */
function isOurs(entry: PyValue): boolean {
  if (entry.t !== 'dict') return false;
  const hooks = entry.v.get('hooks');
  if (hooks === undefined || hooks.t !== 'list') return false;
  return hooks.v.some(isOurHook);
}

/**
 * `entry` with bantamkit's own command objects taken out, and how many came out.
 *
 * THE UNIT OF OWNERSHIP IS THE COMMAND OBJECT, NOT THE MATCHER BLOCK (#129). `isOurs` answers
 * "does this block hold one of ours", and dropping the whole block on that answer deleted a
 * user's `notify-send` that shared the block with ours — after a plan that had just promised
 * their hooks were left byte for byte. So: a block that is not ours comes back untouched (the
 * same object, nothing removed); a block that holds ours loses ONLY those objects and keeps
 * every other key it had; and a block left with no hooks at all is `null`, because
 * `{"matcher": ..., "hooks": []}` is an artefact nobody wrote.
 */
function withoutOurs(entry: PyValue): [PyValue | null, number] {
  if (!isOurs(entry) || entry.t !== 'dict') return [entry, 0];
  const hooks = entry.v.get('hooks');
  if (hooks === undefined || hooks.t !== 'list') return [entry, 0];
  const kept = hooks.v.filter((hook) => !isOurHook(hook));
  const removed = hooks.v.length - kept.length;
  if (kept.length === 0) return [null, removed];
  const trimmed = pyDict(entry.v);
  trimmed.v.set('hooks', { t: 'list', v: kept });
  return [trimmed, removed];
}

/** The `hooks` object, validated. Refuses by name rather than crashing on somebody's file. */
function readHooks(path: string, data: PyDict): HookTable {
  const raw = data.v.get('hooks');
  if (raw === undefined) return new Map();
  if (raw.t !== 'dict') {
    throw new InstallError(`${path} has a 'hooks' that is not an object; refusing to touch it`);
  }
  const hooks: HookTable = new Map();
  for (const [event, entries] of raw.v) {
    if (entries.t !== 'list') {
      throw new InstallError(`${path} has a 'hooks.${event}' that is not a list; refusing to touch it`);
    }
    hooks.set(event, [...entries.v]);
  }
  return hooks;
}

/**
 * The `hooks` object this run wants, built from whatever is there now, the events that change,
 * and how many of OUR command objects came out.
 *
 * ONE PASS OVER THE SEVEN EVENTS AND NOTHING ELSE: every event keeps its non-bantamkit hooks in
 * their existing order and their existing blocks, ours is appended after them, and an event
 * left with none loses its key rather than holding an empty list — `install.mjs`'s rule, kept
 * because a settings file full of empty arrays is a worse artefact than one with nothing in
 * it. A block is dropped only when taking ours out of it leaves it empty (`withoutOurs`).
 *
 * Events outside the seven are not read, not reordered and not removed.
 */
function plannedHooks(
  current: HookTable,
  command: string,
  remove: boolean,
): { hooks: HookTable; touched: string[]; removed: number } {
  const hooks: HookTable = new Map(current);
  const touched: string[] = [];
  let removed = 0;
  for (const [event, matcher] of HOOK_EVENTS) {
    const before = hooks.get(event) ?? [];
    const kept: PyValue[] = [];
    let removedHere = 0;
    for (const entry of before) {
      const [trimmed, count] = withoutOurs(entry);
      removedHere += count;
      if (trimmed !== null) kept.push(trimmed);
    }
    removed += removedHere;
    if (remove) {
      if (removedHere > 0) touched.push(event);
    } else {
      kept.push(fromJs(hookEntry(matcher, command)));
      touched.push(event);
    }
    if (kept.length > 0) hooks.set(event, kept);
    else hooks.delete(event);
  }
  return { hooks, touched, removed };
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
  if (existsSync(path)) lines.push(`  backup : ${backupTarget(path)}`);
  lines.push("Existing hooks are left byte-for-byte; only bantamkit's own entries are replaced.");
  return `${lines.join('\n')}\n`;
}

/**
 * The same plan for the other direction: what is about to come OUT, and out of what.
 *
 * FOUR LINES, NOT FIVE. There is no `command:` line because `removeHooks` never resolves one —
 * see its own note — and printing one would be the plan naming something the write will not
 * touch. The `backup :` line is UNCONDITIONAL here, where `hookPlan`'s is guarded: the gate is
 * only reached when at least one entry is actually coming out, and an entry cannot be in a
 * file that does not exist.
 *
 * `events :` NAMES ONLY THE EVENTS THAT LOSE SOMETHING, not all seven, which is the honest
 * answer to "what will this do to my file" when only some of ours are there. The count on the
 * first line is entries, not events, for the same reason.
 */
function removalPlan(path: string, events: readonly string[], entries: number): string {
  return (
    [
      `bantamkit would remove ${entries} hook entries from ${path}`,
      `  events : ${events.join(' ')}`,
      `  backup : ${backupTarget(path)}`,
      "Existing hooks are left byte-for-byte; only bantamkit's own entries are removed.",
    ].join('\n') + '\n'
  );
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
 * same detected indent and literal non-ASCII through `hostJsonText` (#118) — so the bytes this
 * leaves and the bytes `--install` leaves are produced by one function (RULING Q3.5).
 */
export function installHooks(options: HookOptions = {}): string {
  const { command, args } = thisCommand(options);
  const rendered = hookCommand(command, args);
  const path = claudeSettingsPath();
  const data = readConfig(path);
  const current = readHooks(path, data);
  const { hooks } = plannedHooks(current, rendered, false);

  if (dumpJson(asPyValue(hooks), { sortKeys: true }) === dumpJson(asPyValue(current), { sortKeys: true })) {
    return `bantamkit hooks are already installed in ${path} and match`;
  }

  const tell = options.tell ?? ((): void => {});
  const yes = options.yes ?? false;
  const ask = options.ask ?? null;
  if (!yes) {
    if (ask === null) {
      // NOTHING IS PRINTED HERE. The plan describes a write that is not going to happen, and
      // the refusal is the whole message.
      throw consentUnavailable('--install-hooks', 'writes');
    }
    tell(hookPlan(path, rendered));
    if (!ask()) throw new HookDeclined('no hooks were written');
  } else {
    tell(hookPlan(path, rendered));
  }

  const copied = backup(path);
  data.v.set('hooks', asPyValue(hooks));
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
 * `--remove-hooks`: take out what bantamkit wrote, and nothing else — AFTER asking.
 *
 * THE GATE IS `installHooks`' GATE, deliberately identical: a TTY answer, or `--yes`, or a
 * refusal at exit 2 with nothing written. RULING Q3.7 exempted this flag; the user overturned
 * that on 2026-09-20 after this exact flag, unsandboxed and unasked, rewrote the operator's
 * real settings file. The module header above carries the measurement. Two flags that rewrite
 * one file do not get two consent stories.
 *
 * THE ORDER IS `installHooks`' ORDER, minus the step it does not have:
 *
 *   1. read and validate the settings file — a file that does not parse is reported, never
 *      overwritten;
 *   2. NOTHING-TO-REMOVE RETURNS HERE, BEFORE THE GATE, which is the mirror of install's
 *      already-installed no-op and matters for the same reason: there is no write to consent
 *      to, so a second `--remove-hooks` stays exit 0 with no terminal and no `--yes`, and a
 *      teardown script that runs it twice does not suddenly start refusing;
 *   3. print the plan, then the gate;
 *   4. dated backup, then one atomic write.
 *
 * `thisCommand` IS STILL NOT CALLED. Removal does not need to know what a host should launch,
 * and calling it would put an `npx` cache's kept install between an operator and the ability
 * to undo. That is also why the plan this prints has no `command:` line.
 */
export function removeHooks(options: HookOptions = {}): string {
  const path = claudeSettingsPath();
  const data = readConfig(path);
  const current = readHooks(path, data);
  const { hooks, touched, removed: entries } = plannedHooks(current, '', true);

  if (touched.length === 0) return `no bantamkit hooks are installed in ${path}`;

  // `entries` counts OUR COMMAND OBJECTS, not events and not matcher blocks: an event can hold
  // more than one of ours if somebody hand-edited the file, and a block that also holds a
  // user's hook stays while ours leaves it (#129) — the plan has to say what is actually going.

  const tell = options.tell ?? ((): void => {});
  const yes = options.yes ?? false;
  const ask = options.ask ?? null;
  if (!yes) {
    if (ask === null) {
      // NOTHING IS PRINTED HERE, the same as install: the plan describes a write that is not
      // going to happen, and the refusal is the whole message.
      throw consentUnavailable('--remove-hooks', 'rewrites');
    }
    tell(removalPlan(path, touched, entries));
    if (!ask()) throw new HookDeclined('no hooks were removed');
  } else {
    tell(removalPlan(path, touched, entries));
  }

  const copied = backup(path);
  data.v.set('hooks', asPyValue(hooks));
  writeConfig(path, data);

  const lines = [`removed bantamkit hooks from ${path}`, `  events : ${touched.join(' ')}`];
  if (copied !== null) lines.push(`  backup : ${copied}`);
  lines.push('restart Claude Code (or run /hooks) for this to take effect');
  return lines.join('\n');
}

/**
 * Whether the settings file at `path` carries one of bantamkit's own hooks (#204, S2).
 *
 * Read exactly as `installHooks` reads it — `readConfig`, `readHooks`, ownership by `isOurs` —
 * but as an OBSERVATION: the capability tiers ask it, and a file this module would refuse to
 * touch (not JSON, not an object, a `hooks` of the wrong shape, unreadable, not UTF-8) answers
 * false rather than throwing. A missing tier is silent, never an error. The reference's
 * `has_bantamkit_hooks`; its `read_text` refuses bytes that are not UTF-8, so this does too.
 */
export function hasBantamkitHooks(path: string): boolean {
  try {
    if (existsSync(path)) new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(readFileSync(path));
    const hooks = readHooks(path, readConfig(path));
    for (const entries of hooks.values()) if (entries.some(isOurs)) return true;
    return false;
  } catch {
    return false;
  }
}
