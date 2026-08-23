/**
 * The filesystem calls the memory store makes, with CPython's answers rather than libuv's.
 *
 * WHY THIS EXISTS AS ITS OWN MODULE
 * ---------------------------------
 * `store._listing` is the code job37 spent five units closing, and the whole of that fix is
 * a DECISION taken on the result of a failed directory scan: something at the path means
 * "unreadable", nothing at the path means "empty". Reproducing the decision needs three
 * things Node's `fs` does not hand you — a `strerror` in the C library's words rather than
 * libuv's, an `lexists` that answers `false` for every error and not just ENOENT, and a
 * `Path.exists()` that swallows exactly the errnos `pathlib` swallows. They are here rather
 * than inside `store.ts` because `layers.count_facts` makes the SAME syscalls and a
 * DELIBERATELY DIFFERENT decision on them, so the next unit needs the primitives without
 * inheriting the store's ruling.
 *
 * Nothing here invents a policy. Every function names the CPython call it stands in for.
 */
import {
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';

// ------------------------------------------------------------------------------ errno

/**
 * `os.strerror(errno)` for the errnos a directory scan, a `mkdir` or a file write can
 * actually produce. Keyed on the errno NAME, not the number: ELOOP is 62 on macOS and 40 on
 * Linux, so a table keyed on the number would be wrong on one of the two CI platforms.
 *
 * Every wording here is glibc's AND BSD's — verified identical for this set by the
 * `strerror table` case in `tools/conformance/suites/store.mjs`, which asks the running
 * Python for `os.strerror` of each entry. Adding a key without adding it to that case is
 * how this quietly becomes a guess.
 *
 * WINDOWS IS NOT COVERED AND THE PORT SAYS SO. `os.scandir` on Windows raises an `OSError`
 * whose `strerror` comes from the Win32 message table by way of `winerror`, not from the
 * CRT — "Access is denied" where POSIX says "Permission denied" — so on Windows the
 * sentence `_unreadable` builds differs between the runtimes in its middle clause. The path
 * and the consequence, which are what send a reader to the right place, are identical.
 */
const STRERROR: Record<string, string> = {
  E2BIG: 'Argument list too long',
  EACCES: 'Permission denied',
  EBADF: 'Bad file descriptor',
  EEXIST: 'File exists',
  EFAULT: 'Bad address',
  EINVAL: 'Invalid argument',
  EIO: 'Input/output error',
  EISDIR: 'Is a directory',
  ELOOP: 'Too many levels of symbolic links',
  EMFILE: 'Too many open files',
  ENAMETOOLONG: 'File name too long',
  ENFILE: 'Too many open files in system',
  ENOENT: 'No such file or directory',
  ENOMEM: 'Cannot allocate memory',
  ENOSPC: 'No space left on device',
  ENOTDIR: 'Not a directory',
  ENOTEMPTY: 'Directory not empty',
  EPERM: 'Operation not permitted',
  EROFS: 'Read-only file system',
};

/** The errno names this port claims to render in CPython's words. The suite reads it. */
export const STRERROR_NAMES: readonly string[] = Object.keys(STRERROR);

/**
 * CPython's `errnomap`, for the errnos this module can raise.
 *
 * `OSError.__new__` picks a SUBCLASS from the errno, and the class name is what a caller
 * sees and what `component.Memory` puts in front of a person. A single `PyOSError` name
 * would be a difference with no reason behind it, so the name follows the errno the way
 * CPython's does. Anything not listed stays `OSError`, which is also CPython's default.
 */
const OSERROR_SUBCLASS: Record<string, string> = {
  EACCES: 'PermissionError',
  EAGAIN: 'BlockingIOError',
  ECHILD: 'ChildProcessError',
  EEXIST: 'FileExistsError',
  EINTR: 'InterruptedError',
  EISDIR: 'IsADirectoryError',
  ENOENT: 'FileNotFoundError',
  ENOTDIR: 'NotADirectoryError',
  EPERM: 'PermissionError',
  EPIPE: 'BrokenPipeError',
  ESRCH: 'ProcessLookupError',
};

/**
 * An `OSError` as Python prints one.
 *
 * `str(OSError)` is `[Errno {errno}] {strerror}: '{filename}'`, and that text is not
 * decoration: `_ensure_dirs` lets a `FileExistsError` out of `save` unconverted, and
 * `component.Memory.save` turns whatever comes out into the sentence a model reads.
 * `errno` is the platform number, which is what Python prints and what libuv already
 * gives us as the magnitude of `err.errno`.
 */
export class PyOSError extends Error {
  readonly errno: number;
  readonly code: string;
  readonly strerror: string;
  readonly filename: string | null;

  constructor(errno: number, code: string, strerror: string, filename: string | null) {
    super(
      filename === null
        ? `[Errno ${errno}] ${strerror}`
        : `[Errno ${errno}] ${strerror}: '${filename}'`,
    );
    this.name = OSERROR_SUBCLASS[code] ?? 'OSError';
    this.errno = errno;
    this.code = code;
    this.strerror = strerror;
    this.filename = filename;
  }
}

interface NodeFsError extends Error {
  errno?: number;
  code?: string;
  path?: string;
  syscall?: string;
}

/**
 * A Node `fs` rejection, restated as the `OSError` CPython would have raised.
 *
 * An errno outside the table keeps libuv's own lowercase wording rather than a fabricated
 * one — a wrong capital letter in a sentence a model reads is worse than a visibly
 * different one, and the table is the thing the conformance suite can check.
 */
export function asPyOSError(error: unknown, fallbackPath?: string): PyOSError {
  const e = error as NodeFsError;
  const code = e?.code ?? 'EUNKNOWN';
  const errno = Math.abs(e?.errno ?? 0);
  const strerror = STRERROR[code] ?? `${code}: ${e?.message ?? 'unknown error'}`;
  return new PyOSError(errno, code, strerror, e?.path ?? fallbackPath ?? null);
}

// -------------------------------------------------------------------------- utf-8 text

/** `UnicodeDecodeError`, which is a `ValueError` in Python and is NOT an `OSError`. */
export class PyUnicodeDecodeError extends Error {
  readonly start: number;
  readonly end: number;
  readonly reason: string;

  constructor(bytes: Uint8Array, start: number, end: number, reason: string) {
    const where =
      end - start === 1
        ? `byte 0x${bytes[start]!.toString(16).padStart(2, '0')} in position ${start}`
        : `bytes in position ${start}-${end - 1}`;
    super(`'utf-8' codec can't decode ${where}: ${reason}`);
    this.name = 'UnicodeDecodeError';
    this.start = start;
    this.end = end;
    this.reason = reason;
  }
}

/** How many continuation bytes follow a lead byte, and what the second one may be. */
function leadInfo(b: number): { length: number; lo: number; hi: number } | null {
  if (b < 0x80) return { length: 1, lo: 0, hi: 0 };
  if (b >= 0xc2 && b <= 0xdf) return { length: 2, lo: 0x80, hi: 0xbf };
  if (b === 0xe0) return { length: 3, lo: 0xa0, hi: 0xbf };
  if (b >= 0xe1 && b <= 0xec) return { length: 3, lo: 0x80, hi: 0xbf };
  if (b === 0xed) return { length: 3, lo: 0x80, hi: 0x9f }; // no surrogates
  if (b >= 0xee && b <= 0xef) return { length: 3, lo: 0x80, hi: 0xbf };
  if (b === 0xf0) return { length: 4, lo: 0x90, hi: 0xbf }; // no overlongs
  if (b >= 0xf1 && b <= 0xf3) return { length: 4, lo: 0x80, hi: 0xbf };
  if (b === 0xf4) return { length: 4, lo: 0x80, hi: 0x8f }; // no > U+10FFFF
  return null;
}

/**
 * `bytes.decode("utf-8")` with `errors="strict"`, including the message.
 *
 * `TextDecoder` without `fatal` substitutes U+FFFD, which would let a corrupt fact file
 * through and have `_stamp` write the substitution back over the original bytes — a
 * silent, destructive divergence rather than a loud one. `fatal: true` raises, but with a
 * `TypeError` whose text says nothing about where. `_facts` reads OUTSIDE its `try`, so
 * this message is what a model sees for a binary file in `facts/`, verbatim.
 *
 * The three reasons and the reported span are CPython's, derived by running its decoder
 * over 220 sequences and matched against all of them (the `utf-8 decode` cases in the
 * conformance suite re-run that comparison).
 */
export function pyDecodeUtf8(bytes: Uint8Array): string {
  let i = 0;
  while (i < bytes.length) {
    const b = bytes[i]!;
    const info = leadInfo(b);
    if (info === null) throw new PyUnicodeDecodeError(bytes, i, i + 1, 'invalid start byte');
    if (info.length === 1) {
      i += 1;
      continue;
    }
    for (let j = 1; j < info.length; j += 1) {
      const at = i + j;
      if (at >= bytes.length) {
        throw new PyUnicodeDecodeError(bytes, i, i + j, 'unexpected end of data');
      }
      const c = bytes[at]!;
      const lo = j === 1 ? info.lo : 0x80;
      const hi = j === 1 ? info.hi : 0xbf;
      if (c < lo || c > hi) {
        throw new PyUnicodeDecodeError(bytes, i, i + j, 'invalid continuation byte');
      }
    }
    i += info.length;
  }
  return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
}

/**
 * `Path.read_text(encoding="utf-8")`: strict UTF-8 AND universal-newline translation.
 *
 * The translation half is N2's `decodeFactBytes`, re-derived nowhere: this reads the bytes,
 * decodes them strictly, and hands the string to the same fold. A CRLF fact file therefore
 * parses in both runtimes, which is the property the codec suite already measures.
 */
export function pyReadText(path: string): string {
  let raw: Buffer;
  try {
    raw = readFileSync(path);
  } catch (e) {
    throw asPyOSError(e, path);
  }
  return pyDecodeUtf8(raw).replace(/\r\n?/g, '\n');
}

/**
 * `Path.write_text(text, encoding="utf-8")`, minus the newline translation.
 *
 * N2's ruling, applied to `index.md` and to every fact file: Python opens with
 * `newline=None`, so on Windows it writes CRLF while `_check_index_budget` counts the LF
 * string it just built. This port writes LF everywhere, which is the only way the budget
 * arithmetic and the bytes on disk can agree on all platforms. See `store.indexText`.
 */
export function pyWriteText(path: string, text: string): void {
  try {
    writeFileSync(path, text, 'utf8');
  } catch (e) {
    throw asPyOSError(e, path);
  }
}

// ------------------------------------------------------------------------- path probes

/**
 * `os.path.lexists(path)` — `lstat` without following, and FALSE for every error.
 *
 * Not `lstatSync(p, {throwIfNoEntry: false})`: that returns `undefined` for ENOENT but
 * still throws for EACCES on the parent, and `lexists` catches `(OSError, ValueError)`
 * wholesale. This is the middle arm of the `_listing` three-way, so getting the error
 * behaviour wrong turns an unreadable store back into an empty one.
 */
export function pyLexists(path: string): boolean {
  try {
    lstatSync(path);
    return true;
  } catch {
    return false;
  }
}

/**
 * `Path.exists()` — swallows exactly `pathlib._IGNORED_ERRNOS` and re-raises the rest.
 *
 * ENOENT, ENOTDIR, EBADF and ELOOP really do mean "nothing is there"; EACCES means "I was
 * not allowed to look", and `save`'s `path.exists()` before `_write_fact` must raise on it
 * rather than answer `False` and overwrite. `existsSync` answers `false` for all of them.
 */
const IGNORED = new Set(['ENOENT', 'ENOTDIR', 'EBADF', 'ELOOP']);

export function pyExists(path: string): boolean {
  try {
    statSync(path);
    return true;
  } catch (e) {
    if (IGNORED.has((e as NodeFsError)?.code ?? '')) return false;
    throw asPyOSError(e, path);
  }
}

// ------------------------------------------------------------------------- directories

/**
 * `Path.mkdir(parents=True, exist_ok=True)`.
 *
 * `exist_ok` suppresses `FileExistsError` only when the path is a DIRECTORY: CPython
 * re-raises when a regular file sits there, which is exactly how `save` fails on a store
 * whose `facts/` is a file — before the listing, with a bare `FileExistsError`
 * (`test_a_facts_path_that_is_not_a_directory_is_unreadable_not_empty` says so). Node's
 * recursive `mkdirSync` raises EEXIST there too; this only restates the error.
 */
export function pyMkdirParents(path: string): void {
  try {
    mkdirSync(path, { recursive: true });
  } catch (e) {
    throw asPyOSError(e, path);
  }
}

/**
 * `os.scandir(directory)` reduced to names, raising the way CPython does.
 *
 * The caller decides what a failure MEANS — that decision is `store._listing`'s and
 * `layers.count_facts` makes a different one from the same syscall.
 */
export function pyScandirNames(directory: string): string[] {
  try {
    return readdirSync(directory);
  } catch (e) {
    throw asPyOSError(e, directory);
  }
}

/**
 * `fnmatch.fnmatch(name, "*.md")`, which is the match `pathlib.glob` performs.
 *
 * Two things it is not: it is not "ends with .md" on Windows, where `os.path.normcase`
 * lowercases first and `FACT.MD` is therefore a fact; and it has no dotfile or
 * directory-entry special case, so `.hidden.md` counts and a DIRECTORY called `x.md`
 * counts. `_listing`'s docstring makes not changing the counted set an explicit
 * requirement, so this deliberately keeps every oddity.
 */
export function matchesMd(name: string): boolean {
  return normcase(name).endsWith('.md');
}

/** `os.path.normcase` — identity off Windows, `s.replace('/', '\\').lower()` on it. */
export function normcase(name: string): string {
  return process.platform === 'win32' ? name.replace(/\//g, '\\').toLowerCase() : name;
}

// -------------------------------------------------------------------------- comparison

/**
 * Python's `<` on `str`, which is CODEPOINT order. JS compares UTF-16 code units.
 *
 * They disagree for every astral character: `['\u{1F414}.md', '！.md'].sort()` puts the
 * chicken first because its lead surrogate is 0xD83D, and Python puts it last because
 * 0x1F414 > 0xFF01. `_fact_paths` sorts, `recall` breaks score ties on the name, and the
 * index is written in that order — so a single astral fact name is enough to make two
 * `index.md` files that differ.
 */
export function cmpCodepoint(a: string, b: string): number {
  const x = [...a];
  const y = [...b];
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i += 1) {
    const p = x[i]!.codePointAt(0)!;
    const q = y[i]!.codePointAt(0)!;
    if (p !== q) return p < q ? -1 : 1;
  }
  return x.length - y.length;
}

/**
 * `sorted(directory / name for name in names)` — sorting `Path`s, not strings.
 *
 * `PurePath` compares `_parts_normcase` tuples. Every path here shares a parent, so the
 * comparison reduces to the last component; what survives is the CASE FOLD, which
 * `_parts_normcase` applies on Windows and nowhere else. Ties under that fold keep listing
 * order, because both runtimes sort stably.
 */
export function sortedPathNames(names: readonly string[]): string[] {
  return [...names].sort((a, b) => cmpCodepoint(normcase(a), normcase(b)));
}

// ----------------------------------------------------------------------- path building

/**
 * `PurePath.__truediv__` and `str(Path)`, for the shapes a store root can take.
 *
 * Not `path.join`: `join('/a/b/..', 'facts')` collapses to `/a/facts` while
 * `str(Path('/a/b/..') / 'facts')` keeps `/a/b/../facts`. Both open the same file, but the
 * store PRINTS this path in the sentence a model reads for an unreadable store, and a port
 * whose error names a different path than the reference's is a difference nobody put in
 * writing. Empty and `.` components are dropped, `..` is kept, and the anchor survives —
 * which is `PurePath`'s parsing, not a normalization.
 *
 * On Windows the separator is `\` and `/` is also accepted as one; drive-relative paths
 * (`C:foo`) and UNC roots are outside what a store root has ever been and are not modelled.
 */
export function pyJoin(...parts: string[]): string {
  const win = process.platform === 'win32';
  const sep = win ? '\\' : '/';
  const split = (s: string): string[] => (win ? s.split(/[\\/]/) : s.split('/'));
  let anchor = '';
  const out: string[] = [];
  for (const [i, part] of parts.entries()) {
    const pieces = split(part);
    if (i === 0 && pieces[0] === '') {
      // A leading separator. Exactly two is a root `PurePosixPath` keeps verbatim; one,
      // or three or more, collapse to one.
      let leading = 0;
      while (pieces[leading] === '') leading += 1;
      anchor = leading === 2 && pieces.length > 2 ? `${sep}${sep}` : sep;
      pieces.splice(0, leading);
    } else if (i === 0 && win && /^[A-Za-z]:$/.test(pieces[0] ?? '')) {
      anchor = `${pieces.shift()}${sep}`;
      while (pieces[0] === '') pieces.shift();
    }
    for (const piece of pieces) if (piece !== '' && piece !== '.') out.push(piece);
  }
  if (out.length === 0) return anchor === '' ? '.' : anchor;
  return anchor + out.join(sep);
}

/**
 * `PurePath.with_suffix(suffix)` on the LAST component.
 *
 * `_write_fact` writes `path.with_suffix(".md.tmp")`, and the rule is not "append": a name
 * whose last component already has a suffix has that suffix REPLACED, while a component
 * that is all leading dots has one appended. `facts/a.b.md` -> `facts/a.b.md.tmp`, and the
 * degenerate `facts/.md` (a fact whose frontmatter name is empty) -> `facts/.md.md.tmp`.
 */
export function pyWithSuffix(path: string, suffix: string): string {
  const cut = process.platform === 'win32'
    ? Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
    : path.lastIndexOf('/');
  const head = path.slice(0, cut + 1);
  const name = path.slice(cut + 1);
  // `PurePath.suffix`: the last dot counts only when it is neither the first character nor
  // the last one, so `.md` has no suffix and `a.` has none either.
  const dot = name.lastIndexOf('.');
  const stem = dot > 0 && dot < name.length - 1 ? name.slice(0, dot) : name;
  return `${head}${stem}${suffix}`;
}

/** `Path.unlink()` and `Path.replace(target)`, with CPython's error text. */
export function pyUnlink(path: string): void {
  try {
    unlinkSync(path);
  } catch (e) {
    throw asPyOSError(e, path);
  }
}

export function pyReplace(source: string, target: string): void {
  try {
    renameSync(source, target);
  } catch (e) {
    throw asPyOSError(e, source);
  }
}

/** `date.fromtimestamp(path.stat().st_mtime).isoformat()` — LOCAL, like `date.today()`. */
export function pyMtimeDate(path: string): string {
  let ms: number;
  try {
    ms = statSync(path).mtimeMs;
  } catch (e) {
    throw asPyOSError(e, path);
  }
  const when = new Date(ms);
  const pad = (n: number, w = 2): string => String(n).padStart(w, '0');
  return `${pad(when.getFullYear(), 4)}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
}
