/**
 * The git repository a hook or a recall runs in (#200). Finding it costs stats, never a
 * subprocess. Port of `runtime-py/src/bantamkit/touch/repo.py`; `touch-log` compares the two.
 *
 * `findRepo` walks up from a directory for `.git`: a directory, or a file `gitdir: <path>` (a
 * linked worktree or a submodule). `relPath` makes a path repo-relative with `/` separators on
 * every OS, or `null` outside the toplevel. `git` is the one way this package runs git: argv,
 * no shell, `GIT_OPTIONAL_LOCKS=0`, `LC_ALL=C`, no terminal prompt, `core.quotepath=off`, a
 * `GIT_TIMEOUT_MS` bound, and `null` for every failure. `gitOnPath` answers whether a `git` on
 * PATH can actually run: a stat walk finds it, then `git --version` runs it once and the answer
 * is kept on disk for `GIT_PROBE_TTL_S` (the PostToolUse arm's 2 ms budget cannot pay a spawn
 * per call), so "no git" records nothing (spec, Error handling). `repoId` hashes the toplevel
 * with its drive letter upper-cased, so the two runtimes name one repository the same on
 * Windows whatever case each one's realpath gives (#208).
 *
 * `realpath` is `os.path.realpath`: a path that does not exist (yet) resolves its parent and
 * keeps the rest, as the reference does, so a missing cwd or file is never a divergence.
 */
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import { pyStrip } from '../pysem.js';
import { writeOver } from '../storage/logsegment.js';

export const GIT_TIMEOUT_MS = 2000;
export const GIT_PATHEXT_DEFAULT = '.COM;.EXE;.BAT;.CMD'; // Windows' own default when PATHEXT is unset
export const GIT_PROBE_TTL_S = 600; // how long a `git --version` answer kept on disk stays good
export const GIT_PROBE_FILE = 'git-probe.json';
// A no-shell spawn runs only these on Windows: a `git.cmd` / `git.bat` needs `cmd.exe` (#208).
const WIN_SPAWNABLE = ['.exe', '.com'];
const GIT_ENV = { GIT_OPTIONAL_LOCKS: '0', LC_ALL: 'C', GIT_TERMINAL_PROMPT: '0' };

export interface Repo {
  /** realpath of the toplevel */
  readonly top: string;
  /** the repository's git directory (a worktree's own, for a linked worktree) */
  readonly gitdir: string;
  /** repoId(top) */
  readonly id: string;
}

/** `top` with a leading `X:` drive letter upper-cased; any other path unchanged (#208). */
function driveUpper(top: string): string {
  return /^[A-Za-z]:/.test(top) ? top[0]!.toUpperCase() + top.slice(1) : top;
}

/**
 * The `<repo-id>`: sha256 of the realpath'd toplevel, drive letter upper-cased, 16 hex. Port of
 * `repo_id`. `top` is already a realpath (`findRepo` makes it one), so on POSIX this is
 * `sha16(top)` and no existing id moves; on Windows `c:\x` and `C:\x` are one repository
 * (#208 item 8).
 */
export function repoId(top: string): string {
  return createHash('sha256').update(driveUpper(top), 'utf8').digest('hex').slice(0, 16);
}

function realpath(p: string): string {
  const abs = path.resolve(p);
  try {
    return fs.realpathSync.native(abs);
  } catch {
    const parent = path.dirname(abs);
    if (parent === abs) return abs;
    return path.join(realpath(parent), path.basename(abs));
  }
}

function kind(p: string): 'dir' | 'file' | '' {
  try {
    const st = fs.statSync(p);
    return st.isDirectory() ? 'dir' : st.isFile() ? 'file' : '';
  } catch {
    return '';
  }
}

const GIT_FOUND = new Map<string, boolean>();

/**
 * `<d>/<n>` with the PATH entry `d` exactly as written: never normalized (#208 N1). Port of
 * `_entry_join`. One separator (this OS's) goes between them unless `d` already ends with one
 * (`/` on POSIX, `/` or `\` on Windows). `/usr//bin`, `./bin` and `a/../bin` are kept as
 * spelled, which is what the kernel resolves when it runs the path, and the candidate string
 * (so the `git-probe.json` key) is the same in both runtimes: `path.join` normalized here and
 * Python's `os.path.join` did not, so the two wrote different keys for one git.
 */
function entryJoin(d: string, n: string): string {
  const ends = process.platform === 'win32' ? ['/', '\\'] : ['/'];
  return ends.some((e) => d.endsWith(e)) ? d + n : d + path.sep + n;
}

/** The first `git` the stat walk finds on `pth`, or null. Port of `_git_candidate`. */
function gitCandidate(pth: string, ext: string, win: boolean): string | null {
  const names = win
    ? (ext || GIT_PATHEXT_DEFAULT)
        .split(';')
        .filter((e) => e && WIN_SPAWNABLE.includes(e.toLowerCase()))
        .map((e) => `git${e}`)
    : ['git'];
  for (const d of pth.split(win ? ';' : ':')) {
    if (!d) continue;
    for (const n of names) {
      const c = entryJoin(d, n);
      try {
        if (!fs.statSync(c).isFile()) continue;
        if (!win) fs.accessSync(c, fs.constants.X_OK);
        return c;
      } catch {
        continue;
      }
    }
  }
  return null;
}

function probeKey(cand: string): string | null {
  try {
    const st = fs.statSync(cand, { bigint: true });
    return createHash('sha256').update([cand, `${st.mtimeNs}:${st.size}`].join('\0'), 'utf8').digest('hex').slice(0, 16);
  } catch {
    return null;
  }
}

function probeCached(stateDir: string, key: string): boolean | null {
  const f = path.join(stateDir, GIT_PROBE_FILE);
  try {
    const age = (Date.now() - fs.statSync(f).mtimeMs) / 1000;
    // abs: a file written this millisecond can read as a hair in the future
    if (!(Math.abs(age) < GIT_PROBE_TTL_S)) return null;
    const v: unknown = JSON.parse(fs.readFileSync(f).toString('utf8'));
    if (typeof v === 'object' && v !== null && !Array.isArray(v)) {
      const o = v as Record<string, unknown>;
      if (o['key'] === key && typeof o['ok'] === 'boolean') return o['ok'];
    }
  } catch {
    /* no cache */
  }
  return null;
}

/** `<cand> --version` exits 0 within `GIT_TIMEOUT_MS`: no shell, no stdin, no window. */
function gitRuns(cand: string): boolean {
  try {
    const r = spawnSync(cand, ['--version'], { env: { ...process.env, ...GIT_ENV }, timeout: GIT_TIMEOUT_MS, windowsHide: true, stdio: 'ignore' });
    return !r.error && !r.signal && r.status === 0;
  } catch {
    return false;
  }
}

/**
 * Whether a `git` on PATH can run: found by a stat walk, then run once (#200 B2, #208). Port of
 * `git_on_path`. `gitCandidate` finds the first `git` (POSIX `<dir>/git`, a regular file this
 * user may execute; Windows `<dir>/git<ext>` per `PATHEXT` extension, `GIT_PATHEXT_DEFAULT` when
 * unset or empty, `.exe`/`.com` only: a no-shell spawn cannot run a `git.cmd`); none is false
 * with no spawn. The candidate runs as `<candidate> --version` and must exit 0 within
 * `GIT_TIMEOUT_MS`. The answer is kept in `<stateDir>/git-probe.json` (`{"key","ok"}`, `key`
 * the sha256 of the candidate and its `mtime_ns:size`) while the file is under
 * `GIT_PROBE_TTL_S` old. A simulated platform never spawns. Cached per process, keyed by the
 * PATH and PATHEXT it read.
 */
export function gitOnPath(p: string | null = null, pathext: string | null = null, windows: boolean | null = null, stateDir: string | null = null): boolean {
  const real = process.platform === 'win32';
  const win = windows === null ? real : windows;
  const pth = p === null ? (process.env['PATH'] ?? '') : p;
  const ext = pathext === null ? (process.env['PATHEXT'] ?? '') : pathext;
  const key = JSON.stringify([pth, win ? ext : '', win]);
  const hit = GIT_FOUND.get(key);
  if (hit !== undefined) return hit;
  const cand = gitCandidate(pth, ext, win);
  let found: boolean;
  if (cand === null || win !== real) {
    found = cand !== null;
  } else {
    const pk = probeKey(cand);
    const cached = stateDir === null || pk === null ? null : probeCached(stateDir, pk);
    if (cached !== null) {
      found = cached;
    } else {
      found = gitRuns(cand);
      if (stateDir !== null && pk !== null) {
        try {
          fs.mkdirSync(stateDir, { recursive: true });
          writeOver(path.join(stateDir, GIT_PROBE_FILE), Buffer.from(JSON.stringify({ key: pk, ok: found }), 'utf8'));
        } catch {
          /* no cache: the next call spawns again */
        }
      }
    }
  }
  GIT_FOUND.set(key, found);
  return found;
}

export function findRepo(cwd: string): Repo | null {
  let here: string;
  try {
    here = realpath(cwd);
  } catch {
    return null;
  }
  for (;;) {
    const dot = path.join(here, '.git');
    try {
      const k = kind(dot);
      if (k === 'dir') return { top: here, gitdir: dot, id: repoId(here) };
      if (k === 'file') {
        const first = (fs.readFileSync(dot).toString('utf8').split('\n')[0] ?? '').trim();
        if (first.startsWith('gitdir:')) {
          const raw = first.slice('gitdir:'.length).trim();
          const gd = path.isAbsolute(raw) ? raw : path.join(here, raw);
          return { top: here, gitdir: realpath(gd), id: repoId(here) };
        }
      }
    } catch {
      return null;
    }
    const parent = path.dirname(here);
    if (parent === here) return null;
    here = parent;
  }
}

export function relPath(repo: Repo, p: string): string | null {
  let rel: string;
  try {
    rel = path.relative(repo.top, realpath(p));
  } catch {
    return null;
  }
  if (rel === '' || rel === '..' || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) return null;
  return rel.split(path.sep).join('/');
}

export function git(repo: Repo, args: string[], timeoutMs: number = GIT_TIMEOUT_MS): string | null {
  try {
    const r = spawnSync('git', ['-c', 'core.quotepath=off', ...args], {
      cwd: repo.top,
      env: { ...process.env, ...GIT_ENV },
      timeout: timeoutMs,
      windowsHide: true,
      encoding: 'buffer',
      maxBuffer: 64 * 1024 * 1024,
    });
    if (r.error || r.signal || r.status !== 0) return null;
    return r.stdout.toString('utf8');
  } catch {
    return null;
  }
}

// ------------------------------------------------------- T200-2: files, renames, head print

/** The tracked files, repo-relative (`git ls-files -z`); `null` when git fails. */
export function lsFiles(repo: Repo): string[] | null {
  const out = git(repo, ['ls-files', '-z']);
  return out === null ? null : out.split('\0').filter((p) => p !== '');
}

/**
 * old -> new for every rename in HEAD's history, the newest rename of a path winning; chains
 * are left as hops for `resolveRef`. The `i + 2 < f.length` guard is strict on purpose: a cut
 * last record (git killed by the timeout) is skipped, never read past the end. `null` when git
 * fails, which includes a repo with no commit yet. A `Map`, so a path named `__proto__` is a key.
 */
export function renames(repo: Repo): Map<string, string> | null {
  const out = git(repo, ['log', '--format=', '--name-status', '-M', '-z', '--diff-filter=R', 'HEAD']);
  if (out === null) return null;
  const f = out.split('\0').filter((x) => x !== '');
  const map = new Map<string, string>();
  let i = 0;
  while (i < f.length) {
    if (f[i]!.startsWith('R') && i + 2 < f.length) {
      // newest first: the first rename seen of a path is its latest
      if (!map.has(f[i + 1]!)) map.set(f[i + 1]!, f[i + 2]!);
      i += 3;
    } else {
      i += 1;
    }
  }
  return map;
}

/**
 * sha16 of `HEAD`'s text, the loose ref it names (or `packed-refs`' `mtime_ns:size`), and
 * `<gitdir>/index`'s `mtime_ns:size`, read from files, never a subprocess. A linked worktree's
 * refs live in the common dir its `commondir` names. `mtime_ns` is the exact bigint.
 */
export function headPrint(repo: Repo): string {
  const stat = (p: string): string => {
    try {
      const st = fs.statSync(p, { bigint: true });
      return `${st.mtimeNs}:${st.size}`;
    } catch {
      return '-';
    }
  };
  const read = (p: string): string => {
    try {
      return pyStrip(fs.readFileSync(p).toString('utf8'));
    } catch {
      return '-';
    }
  };
  let common = repo.gitdir;
  const cd = read(path.join(repo.gitdir, 'commondir'));
  if (cd !== '-') common = realpath(path.resolve(repo.gitdir, cd));
  const head = read(path.join(repo.gitdir, 'HEAD'));
  let ref = '';
  if (head.startsWith('ref: ')) {
    ref = read(path.join(common, ...head.slice(5).split('/')));
    if (ref === '-') ref = `packed:${stat(path.join(common, 'packed-refs'))}`;
  }
  const key = [head, ref, stat(path.join(repo.gitdir, 'index'))].join('\0');
  return createHash('sha256').update(key, 'utf8').digest('hex').slice(0, 16);
}
