/**
 * The git repository a hook or a recall runs in (#200). Finding it costs stats, never a
 * subprocess. Port of `runtime-py/src/bantamkit/touch/repo.py`; `touch-log` compares the two.
 *
 * `findRepo` walks up from a directory for `.git`: a directory, or a file `gitdir: <path>` (a
 * linked worktree or a submodule). `relPath` makes a path repo-relative with `/` separators on
 * every OS, or `null` outside the toplevel. `git` is the one way this package runs git: argv,
 * no shell, `GIT_OPTIONAL_LOCKS=0`, `LC_ALL=C`, no terminal prompt, `core.quotepath=off`, a
 * `GIT_TIMEOUT_MS` bound, and `null` for every failure. `gitOnPath` answers whether a `git`
 * executable is on PATH by stats alone (the PostToolUse arm may not spawn), so "no git" records
 * nothing (spec, Error handling).
 *
 * `realpath` is `os.path.realpath`: a path that does not exist (yet) resolves its parent and
 * keeps the rest, as the reference does, so a missing cwd or file is never a divergence.
 */
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import { pyStrip } from '../pysem.js';
import { sha16 } from '../storage/hotindex.js';

export const GIT_TIMEOUT_MS = 2000;
export const GIT_PATHEXT_DEFAULT = '.COM;.EXE;.BAT;.CMD'; // Windows' own default when PATHEXT is unset
const GIT_ENV = { GIT_OPTIONAL_LOCKS: '0', LC_ALL: 'C', GIT_TERMINAL_PROMPT: '0' };

export interface Repo {
  /** realpath of the toplevel */
  readonly top: string;
  /** the repository's git directory (a worktree's own, for a linked worktree) */
  readonly gitdir: string;
  /** sha16(top) */
  readonly id: string;
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
 * Whether a `git` executable is on PATH, by a stat walk: never a subprocess (#200, B2). Port of
 * `git_on_path`. Each non-empty `PATH` entry in order: on POSIX `<dir>/git` must be a regular
 * file this user may execute; on Windows `<dir>/git<ext>` for each non-empty `PATHEXT`
 * extension (`GIT_PATHEXT_DEFAULT` when unset or empty) must be a regular file. Cached per
 * process, keyed by the PATH and PATHEXT it read.
 */
export function gitOnPath(p: string | null = null, pathext: string | null = null, windows: boolean | null = null): boolean {
  const win = windows === null ? process.platform === 'win32' : windows;
  const pth = p === null ? (process.env['PATH'] ?? '') : p;
  const ext = pathext === null ? (process.env['PATHEXT'] ?? '') : pathext;
  const key = JSON.stringify([pth, win ? ext : '', win]);
  const hit = GIT_FOUND.get(key);
  if (hit !== undefined) return hit;
  const names = win ? (ext || GIT_PATHEXT_DEFAULT).split(';').filter((e) => e).map((e) => `git${e}`) : ['git'];
  let found = false;
  outer: for (const d of pth.split(win ? ';' : ':')) {
    if (!d) continue;
    for (const n of names) {
      const c = path.join(d, n);
      try {
        if (!fs.statSync(c).isFile()) continue;
        if (!win) fs.accessSync(c, fs.constants.X_OK);
        found = true;
        break outer;
      } catch {
        continue;
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
      if (k === 'dir') return { top: here, gitdir: dot, id: sha16(here) };
      if (k === 'file') {
        const first = (fs.readFileSync(dot).toString('utf8').split('\n')[0] ?? '').trim();
        if (first.startsWith('gitdir:')) {
          const raw = first.slice('gitdir:'.length).trim();
          const gd = path.isAbsolute(raw) ? raw : path.join(here, raw);
          return { top: here, gitdir: realpath(gd), id: sha16(here) };
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
