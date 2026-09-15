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

/**
 * The dotted-version order `--update` compares with, moved here from `selfupdate.ts` in J51-9a
 * so `--install` can refuse to lower a kept install without importing that module. Moved, not
 * copied: there is one comparator, and `selfupdate.ts` re-exports it.
 */
type Part = readonly [number, number, string];

/**
 * A dotted version as something orderable, deterministically, without claiming PEP 440.
 *
 * THE REFERENCE'S RULE, REPRODUCED EXACTLY, INCLUDING THE PART THAT IS WRONG. Split on `.`; a
 * component that is all digits sorts as a NUMBER, anything else sorts as a STRING after every
 * number in that position. So `0.9.0 < 0.10.0` — the thing a plain string compare gets wrong,
 * and the reason this exists — and `0.31.0 < 0.31.0rc1`, which is WRONG BY SEMVER AND BY PEP
 * 440 and is kept anyway.
 *
 * A CORRECT COMPARISON HERE WOULD BE A DIVERGENCE, NOT AN IMPROVEMENT. `_version_key`'s
 * docstring in the reference gives the reason: bantamkit has never published a prerelease to
 * either registry, and implementing PEP 440 there in order to reproduce it here would be a
 * second, larger thing to keep byte-identical in service of a case neither index can currently
 * return. What matters is that both runtimes are wrong in the SAME direction, which a
 * conformance case can pin and a reader can check. If a prerelease is ever published, this is
 * the function to fix — in both runtimes, in one job.
 *
 * `/^\d+$/` is ASCII-only, where CPython's `str.isdigit()` is not. That narrowing is the safe
 * direction: the strings `str.isdigit()` accepts and `int()` then REFUSES (superscripts, for
 * one) raise in the reference and sort as strings here, and no registry can answer with one.
 */
function versionKey(version: string): Part[] {
  return version.split('.').map((part): Part => (/^\d+$/.test(part) ? [0, Number(part), ''] : [1, 0, part]));
}

const PAD: Part = [0, 0, ''];

function comparePart(left: Part, right: Part): number {
  if (left[0] !== right[0]) return left[0] < right[0] ? -1 : 1;
  if (left[1] !== right[1]) return left[1] < right[1] ? -1 : 1;
  if (left[2] === right[2]) return 0;
  return left[2] < right[2] ? -1 : 1;
}

/**
 * -1 when the index is ahead, 0 when they agree, 1 when the installed version is ahead.
 *
 * The shorter of the two is padded with numeric zeros, so `0.30` and `0.30.0` agree — which is
 * what a person means by them and what both registries would print for one release.
 */
export function compareVersions(installed: string, latest: string): number {
  const left = versionKey(installed);
  const right = versionKey(latest);
  const width = Math.max(left.length, right.length);
  for (let i = 0; i < width; i += 1) {
    const order = comparePart(left[i] ?? PAD, right[i] ?? PAD);
    if (order !== 0) return order;
  }
  return 0;
}
