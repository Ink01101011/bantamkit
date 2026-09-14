/**
 * The npm spawner and the kept-install location, shared by `--install` and `--update`.
 *
 * WHY THIS IS ITS OWN MODULE. `selfupdate.ts` owns the one network request in this runtime, and
 * `test/selfupdate.test.mjs` pins that `cli.ts` is the ONLY module in `src/` importing it. Job51
 * made `--install` spawn npm too (the kept install below), and the brief was to SHARE the spawner
 * rather than write a second one. Moving it here lets `hostinstall.ts` use it without reaching
 * `selfupdate.ts`; `selfupdate.ts` re-exports all three names, so its surface is unchanged.
 *
 * Nothing here touches the network by itself. `runInstaller` spawns whatever argv it is handed,
 * and only the two operator-typed flags hand it one.
 */
import { spawnSync } from 'node:child_process';
import { homedir } from 'node:os';
import { join } from 'node:path';

/** The npm package this install would upgrade. Divergent by construction (`DISTRIBUTION`). */
export const PACKAGE = 'bantamkit-mcp';

/**
 * Where `--install` keeps the one-time install a host launches: `<homedir>/.bantamkit/mcp`.
 *
 * DEFINED ONCE, HERE, because two flags must agree on it byte for byte: `--install` makes it and
 * records its `cli.js`, and `--update` from an `npx` cache patches it in place. A second spelling
 * of this path would be a second place for the two to disagree about a user's install.
 *
 * `homedir()` and nothing else — `HOME` on POSIX, `USERPROFILE` on Windows — so pointing those at
 * a scratch directory moves it, which is what makes the tests possible.
 */
export function keptPrefix(home: string = homedir()): string {
  return join(home, '.bantamkit', 'mcp');
}

/** The `dist/cli.js` inside the kept install — what a host is told to run with node. */
export function keptCli(prefix: string = keptPrefix()): string {
  return join(prefix, 'node_modules', PACKAGE, 'dist', 'cli.js');
}

/** The `package.json` inside the kept install, whose `version` says whether it is current. */
export function keptManifest(prefix: string = keptPrefix()): string {
  return join(prefix, 'node_modules', PACKAGE, 'package.json');
}

/**
 * `shlex.join`: `shlex.quote` each word and space them.
 *
 * Hand-rolled from CPython's own rule — `_find_unsafe = re.compile(r'[^\w@%+=:,./-]', re.ASCII)`
 * — because the rendered command is printed to the operator by `UPDATING`, by `COMMAND_FAILED`
 * and by the `local-file` route, and a prefix path with a space in it is the normal case on
 * macOS and on Windows. Single quotes, with an embedded `'` closed and reopened the way
 * `shlex.quote` does it, so the line can be pasted back into a shell unchanged.
 */
export function shlexJoin(command: readonly string[]): string {
  return command
    .map((word) => {
      if (word === '') return "''";
      if (/^[\w@%+=:,./-]+$/.test(word)) return word;
      return `'${word.replace(/'/g, `'"'"'`)}'`;
    })
    .join(' ');
}

/**
 * Run the installer, capture what it said, return both.
 *
 * CAPTURED RATHER THAN INHERITED so the report has one shape whether or not anybody is
 * watching, and so a test can inject a substitute and assert on the command WITHOUT a real
 * install ever running. On the `--install` path this also keeps npm's progress off stdout,
 * which is the operator's report and nothing else.
 *
 * THE ONE PLACE THIS IS NOT THE REFERENCE'S BEHAVIOUR: `stderr=STDOUT` genuinely interleaves
 * the two streams in the order they happened, and `spawnSync` has no fd-dup, so the two pipes
 * are concatenated instead — stdout, then stderr. npm writes its progress to stderr and its
 * result to stdout, so an operator reading a failure still gets both, in two blocks rather than
 * one. The installer's own words are never compared across runtimes; the sentences around them
 * are.
 *
 * `shell: true` ON WINDOWS ONLY, the idiom `hostinstall.installViaClaudeCli` established for
 * the same reason: npm is a `npm.cmd` batch shim there and `spawnSync` returns ENOENT for a
 * batch file without a shell. Arguments are quoted because `cmd.exe` gets a string.
 */
export function runInstaller(command: readonly string[]): [number, string] {
  const [program, ...args] = command;
  const win = process.platform === 'win32';
  const quoted = win ? args.map((a) => (/[\s"^&|<>]/.test(a) ? `"${a.replace(/"/g, '\\"')}"` : a)) : args;
  const done = spawnSync(program ?? '', quoted, { encoding: 'utf8', shell: win });
  if (done.error) {
    // A missing `npm` is not a stack trace: it is a command that failed, and `COMMAND_FAILED`
    // is the sentence that says so and hands back what went wrong. 127 is the shell's own
    // code for "command not found", so the number means something to the person reading it.
    return [127, done.error.message];
  }
  return [done.status ?? 1, `${done.stdout ?? ''}${done.stderr ?? ''}`];
}
