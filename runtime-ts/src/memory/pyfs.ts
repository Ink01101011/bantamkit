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
 *
 * REGISTERED AND NOT DONE — N8's review found five things in this file and N10 fixed two of
 * them. The two were WRONG ANSWERS: `pyDecodeUtf8` ate a UTF-8 BOM its own validator had
 * just accepted, and `OSError.__str__`/the symlink-loop `RuntimeError` spelled `%r` as a
 * hand-written pair of apostrophes. The other three are CONSOLIDATION — one question with
 * two spellings, both of them right — and they are listed here rather than half-started:
 *
 *   - TWO ERRNO TABLES. `STRERROR` (errno name -> the C library's sentence) and
 *     `OSERROR_SUBCLASS` (errno name -> the exception class CPython picks) are separate
 *     objects keyed on the same thing, and `STRERROR_NAMES` — which the conformance suite
 *     reads to check the wordings against the running Python — covers only the first. An
 *     errno added to one and not the other is silently uncovered. Nothing measured is wrong
 *     today: the `strerror table` case passes on all 19 entries.
 *   - `normcase` AND `PyRuntimeError` ARE EXPORTED WITH NO CALLER OUTSIDE THIS FILE. Both
 *     are used inside it; the export is surface nobody asked for.
 *
 * FOUR PATH PARSERS became one, and N11 closed that one because it had stopped being a
 * consolidation and started being wrong. `parsePath`, `lastSeparator` and `resolveWindows`
 * each re-decided where a separator and a drive letter are; the Windows readings they agreed
 * on were the POSIX ones. There is now a single `ntpath`/`PureWindowsPath` model —
 * `ntSplitRoot`, `parseWindowsPath`, `ntJoin`, `winFormat` and the `win*` functions over
 * them — and every Windows arm is a one-line dispatch to it.
 *
 * WHY THE WINDOWS ARMS ARE EXPORTED SEPARATELY FROM THE PLATFORM DISPATCH. They are pure
 * path algebra, and CPython computes it the same way on every operating system, so exporting
 * the flavour explicitly turns "measurable only on a GitHub runner" into "measurable on the
 * laptop that wrote it". The `ntpath.splitroot and PureWindowsPath parsing` case in
 * `tools/conformance/suites/store.mjs` drives them against a running CPython on every
 * platform, and it caught a wrong answer (`///a` reported absolute) before a CI cycle was
 * spent on it. What still cannot be measured off Windows is the DISPATCH — the
 * `process.platform === 'win32'` line itself — and the calls that touch the real filesystem
 * (`resolveWindows`, `scandirShape`).
 *
 * Also registered, in `store.ts` rather than here: the `ValueError` arms `_facts` catches
 * and this port reaches by a different route. Owner: whichever unit consolidates `pyfs`.
 */
import {
  appendFileSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  readlinkSync,
  realpathSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { constants as osConstants, homedir, userInfo } from 'node:os';

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
 * WINDOWS IS COVERED BY A SECOND TABLE, NOT BY THIS ONE. `os.scandir` on Windows raises an
 * `OSError` whose `strerror` comes from the Win32 message table by way of `winerror`, not
 * from the CRT — "The directory name is invalid" where POSIX says "Not a directory". That
 * table is `WINERROR` below, and which of the two a given call uses is `OSErrorOrigin`:
 * anything that goes through the Win32 API reads `WINERROR`, and `open()` — which goes
 * through the C runtime — reads this one.
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
 * `os.strerror` for one errno NAME — the table alone, with no Windows arm in front of it.
 *
 * The conformance case that checks these wordings used to read them back through
 * `asPyOSError`, which now answers with the WIN32 message on Windows for exactly the codes
 * the table also carries. Reading the table directly keeps that case measuring the thing its
 * name says, and leaves the winerror wordings to the `winerror table` case beside it.
 */
export function pyStrerror(code: string): string | undefined {
  return STRERROR[code];
}

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
 * `str(OSError)` is `[Errno {errno}] {strerror}: {filename!r}`, and that text is not
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
  /** `OSError.filename2` — set by the two-path syscalls, and PRINTED when it is. */
  readonly filename2: string | null;
  /**
   * `OSError.winerror`, which exists ONLY on Windows and CHANGES `__str__`.
   *
   * CPython carries both numbers for a call that went through the Win32 API: the translated
   * POSIX `errno` and the raw Win32 code. `OSError.__str__` prefers the latter and prints
   * `[WinError %d] <the Win32 message>`. `null` here means "this OSError has no winerror",
   * which is every OSError on POSIX and every OSError CPython raises on Windows out of the
   * C runtime rather than out of the Win32 API — see `asPyOSError`'s `origin`.
   */
  readonly winerror: number | null;

  constructor(
    errno: number,
    code: string,
    strerror: string,
    filename: string | null,
    filename2: string | null = null,
    winerror: number | null = null,
  ) {
    // `OSError.__str__` is `"[Errno %S] %S: %R"`, or `"[Errno %S] %S: %R -> %R"` when there
    // are two (`Objects/exceptions.c`). `%R` is `repr`, NOT a hand-written pair of
    // apostrophes. WAS the latter, and N8 measured the difference: a path holding a `'`, a
    // newline or a tab produced a sentence CPython does not print — `pyRepr` switches to
    // double quotes for the first and escapes the other two. That sentence is quoted
    // verbatim into what `component.Memory` and shiftwork's clock-out put before a model.
    const where =
      filename === null
        ? ''
        : filename2 === null
          ? `: ${pyRepr(filename)}`
          : `: ${pyRepr(filename)} -> ${pyRepr(filename2)}`;
    // `Objects/exceptions.c`, `OSError_str`: the winerror arm comes FIRST, and when it fires
    // the number printed is the Win32 one and the sentence is the Win32 one. There is no
    // spelling of `str(OSError)` that shows both.
    const head = winerror === null ? `[Errno ${errno}]` : `[WinError ${winerror}]`;
    super(`${head} ${strerror}${where}`);
    this.name = OSERROR_SUBCLASS[code] ?? 'OSError';
    this.errno = errno;
    this.code = code;
    this.strerror = strerror;
    this.filename = filename;
    this.filename2 = filename2;
    this.winerror = winerror;
  }
}

/**
 * The number CPython would print, which is NOT the number libuv hands over.
 *
 * `err.errno` is a libuv status, and on POSIX libuv reuses the platform's own errno so the
 * magnitude is right by accident. On Windows it does not: libuv has its own space starting
 * at -4096, so `ENOENT` arrives as **-4058** and `EISDIR` as **-4068** where CPython prints
 * `[Errno 2]` and `[Errno 21]`. MEASURED on windows-latest, run 32644269451: five test
 * nodes reported `[Errno 4058] No such file or directory` for a sentence the reference
 * renders `[Errno 2] ...`, and that sentence is quoted verbatim into what shiftwork's
 * clock-out and `component.Memory` put in front of a model.
 *
 * `os.constants.errno` is the platform's own `errno.h` table — 2/21/13 on Windows exactly
 * as on POSIX — so keying on the CODE NAME gives CPython's number on every platform. The
 * libuv magnitude stays as the fallback for a code the table does not carry, because a
 * number that is merely wrong beats no number at all in a message a human has to search
 * for. Cross-checked against the reference by the `oserror` cases in
 * tools/conformance/suites/store.mjs.
 *
 * The `winerror` half of the same question is `WINERROR` and `winerrorFor` below.
 */
function pyErrno(e: { code?: string; errno?: number } | undefined): number {
  const named = e?.code === undefined ? undefined : (osConstants.errno as Record<string, number | undefined>)[e.code];
  return named ?? Math.abs(e?.errno ?? 0);
}

interface NodeFsError extends Error {
  errno?: number;
  code?: string;
  path?: string;
  dest?: string;
  syscall?: string;
}

// ---------------------------------------------------------------------------- winerror

/**
 * The Win32 message table, as `FormatMessageW` renders it and as CPython then TRIMS it.
 *
 * `PyErr_SetExcFromWindowsErrWithFilename` strips every trailing character that is `<= ' '`
 * or `'.'`, so `The system cannot find the file specified.\r\n` reaches a reader without the
 * period. Four of these are MEASURED against the reference on windows-latest, run
 * 32646521489 (2, 3, 183, 267); the rest are the table entries the same syscalls can reach,
 * and the `winerror table` case in `tools/conformance/suites/store.mjs` asks the running
 * CPython for every one of them on a Windows runner rather than trusting this list.
 */
const WINERROR: Record<number, string> = {
  1: 'Incorrect function',
  2: 'The system cannot find the file specified',
  3: 'The system cannot find the path specified',
  5: 'Access is denied',
  15: 'The system cannot find the drive specified',
  32: 'The process cannot access the file because it is being used by another process',
  80: 'The file exists',
  87: 'The parameter is incorrect',
  123: 'The filename, directory name, or volume label syntax is incorrect',
  145: 'The directory is not empty',
  183: 'Cannot create a file when that file already exists',
  206: 'The filename or extension is too long',
  267: 'The directory name is invalid',
  1920: 'The file cannot be accessed by the system',
  1921: 'The name of the file cannot be resolved by the system',
};

/** The winerrors this port claims to render in CPython's words. The suite reads it. */
export const WINERROR_NUMBERS: readonly number[] = Object.keys(WINERROR).map(Number);

/** One Win32 wording, as CPython trims it. The `winerror table` case checks every entry. */
export function pyWinStrerror(winerror: number): string | undefined {
  return WINERROR[winerror];
}

/** `ERROR_CANT_RESOLVE_FILENAME` — pathlib's `_WINERROR_CANT_RESOLVE_FILENAME`. */
const WINERROR_CANT_RESOLVE_FILENAME = 1921;

/**
 * Which SHAPE of Windows call produced an error, because CPython's answer depends on it.
 *
 * `os.stat`, `os.scandir`, `os.mkdir`, `os.replace` and `os.unlink` go through the Win32 API
 * and raise an OSError with `winerror` SET. `open()` does NOT: it goes through the C runtime,
 * which fills in `errno` alone, and `str()` of that error is the ordinary `[Errno %d]` form
 * with the CRT's own POSIX wording. MEASURED, run 32646521489: opening a directory for write
 * is `[Errno 13] Permission denied` on CPython-for-Windows — not `[WinError 5]`, and not the
 * `[Errno 21] Is a directory` libuv reports. Getting this split wrong renders the right
 * number in the wrong sentence.
 */
export type OSErrorOrigin = 'win32' | 'crt' | 'scandir';

/**
 * libuv's code -> the Win32 error CPython would have carried, or `null` for "no winerror".
 *
 * THE MAPPING IS MANY-TO-ONE IN THE DIRECTION THAT LOSES INFORMATION, which is why this
 * cannot be a plain table. libuv translates every Win32 error into one POSIX-shaped code, so
 * `ERROR_FILE_NOT_FOUND` (2) and `ERROR_PATH_NOT_FOUND` (3) both arrive as `ENOENT` and the
 * distinction Windows drew has to be RE-DERIVED. Win32 picks 3 whenever the component that
 * failed was needed AS A DIRECTORY and 2 when only the final name was missing, so the probe
 * is exactly that: which of the components is not there.
 *
 * Verified against the reference for both arms on run 32646521489 — `os.replace` onto a
 * missing destination DIRECTORY is 3, `os.replace` of a missing source FILE beside an
 * existing directory is 2. `exists` is injected so the derivation is a pure function with a
 * node that goes red on a laptop.
 */
export function winerrorFor(
  code: string,
  origin: OSErrorOrigin,
  path: string | null,
  dest: string | null,
  exists: (candidate: string) => boolean,
): number | null {
  if (origin === 'crt') return null;
  switch (code) {
    case 'ENOENT': {
      // A directory-listing call uses the NAMED path as a directory, so a missing leaf is
      // already a missing directory component there; every other call needs only its parent.
      if (origin === 'scandir') return path !== null && exists(path) ? 2 : 3;
      // A two-name call opens the SOURCE first, so a missing source is 2 even when the
      // destination's directory is missing too. MEASURED both ways round on run 32646521489:
      // an existing source into a missing destination directory is 3, a missing source
      // beside an existing one is 2.
      if (dest !== null) {
        if (path !== null && !exists(path)) return 2;
        if (!exists(pyParent(dest))) return 3;
        return 2;
      }
      if (path !== null && !exists(pyParent(path))) return 3;
      return 2;
    }
    case 'ENOTDIR':
      return 267;
    case 'EEXIST':
      return 183;
    case 'EACCES':
    case 'EPERM':
      return 5;
    case 'ENOTEMPTY':
      return 145;
    case 'ELOOP':
      return WINERROR_CANT_RESOLVE_FILENAME;
    case 'EINVAL':
      return 87;
    case 'ENAMETOOLONG':
      return 206;
    case 'EBUSY':
      return 32;
    default:
      // No claim rather than a fabricated one: an unmapped code keeps the `[Errno %d]` form,
      // which is visibly a difference instead of a plausible-looking wrong sentence.
      return null;
  }
}

/**
 * The C runtime's answer where it is NOT libuv's, for the calls `open()` makes.
 *
 * One entry, and it is measured: opening a directory for writing is `EISDIR` to libuv and
 * `EACCES` to the Windows CRT, so CPython prints `[Errno 13] Permission denied` for the
 * `.tmp` that shiftwork's clock-out could not write. Everything else the CRT can raise here
 * — ENOENT, EACCES, EEXIST, EINVAL — already agrees with libuv in both number and wording.
 */
export function crtCode(code: string): string {
  return code === 'EISDIR' ? 'EACCES' : code;
}

/**
 * A Node `fs` rejection, restated as the `OSError` CPython would have raised.
 *
 * An errno outside the table keeps libuv's own lowercase wording rather than a fabricated
 * one — a wrong capital letter in a sentence a model reads is worse than a visibly
 * different one, and the table is the thing the conformance suite can check.
 *
 * `origin` says which of CPython's two error paths the call would have taken on Windows;
 * off Windows it changes nothing, because there is only one path there.
 */
export function asPyOSError(
  error: unknown,
  fallbackPath?: string,
  fallbackDest?: string,
  origin: OSErrorOrigin = 'win32',
): PyOSError {
  const e = error as NodeFsError;
  const windows = process.platform === 'win32';
  const code = windows && origin === 'crt' ? crtCode(e?.code ?? 'EUNKNOWN') : (e?.code ?? 'EUNKNOWN');
  const errno = pyErrno({ code, errno: e?.errno });
  const filename = e?.path ?? fallbackPath ?? null;
  const filename2 = e?.dest ?? fallbackDest ?? null;
  const winerror = windows ? winerrorFor(code, origin, filename, filename2, pyLexists) : null;
  const strerror =
    (winerror === null ? STRERROR[code] : WINERROR[winerror]) ??
    STRERROR[code] ??
    `${code}: ${e?.message ?? 'unknown error'}`;
  return new PyOSError(errno, code, strerror, filename, filename2, winerror);
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
 *
 * `ignoreBOM: true` IS THE DEFAULT SPELLING BACKWARDS, and it is the point. `TextDecoder`
 * defaults `ignoreBOM` to FALSE, which means "treat a leading EF BB BF as a byte-order mark
 * and DROP it". CPython's utf-8 codec has no such rule — `b'\xef\xbb\xbf'.decode('utf-8')`
 * is `'\ufeff'`, one character, and `utf-8-sig` is the codec that strips it. The validator
 * above already accepted EF BB BF as an ordinary three-byte sequence, so this module was
 * checking one thing and returning another: N8 measured a BOM'd checkpoint that CPython
 * REFUSES (`json.loads` answers `Unexpected UTF-8 BOM (decode using utf-8-sig)`) and that
 * this port parsed and then WROTE. Every text read in the package now comes through here,
 * `assets.ts` included, so there is one UTF-8 decode and not two with opposite answers.
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
  return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
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
    throw asPyOSError(e, path, undefined, 'crt');
  }
  return pyDecodeUtf8(raw).replace(/\r\n?/g, '\n');
}

/**
 * `io.TextIOWrapper`'s outgoing newline translation, which is `newline=None`'s whole effect.
 *
 * THIS REVERSES N2's RULING, and the reason it was reversed is worth more than the ruling
 * was. N2 wrote LF on every platform, arguing that CRLF "already disagrees with the store's
 * own arithmetic" and that reproducing it "would make the same Fact emit different bytes on
 * two machines". Both halves describe the REFERENCE, not a defect being avoided: CPython's
 * `_check_index_budget` counts the LF string it just built while `write_text` puts CRLF on
 * the disk, and CPython already emits different bytes for the same Fact on Windows and on
 * macOS. A port that "fixes" that is not byte-compatible with the thing it stands beside —
 * and byte-compatibility is the product, because the Python server and this one read and
 * write the SAME store on the SAME machine. MEASURED, run 32646521489: 83 conformance cases
 * differed by exactly this, one byte per line, in files both runtimes had just written.
 *
 * The arithmetic does not move. Python counts the in-memory LF text and so does this port;
 * only the bytes leaving through `write` are translated, which is where CPython does it too.
 *
 * The translation is unconditional on `\n`, INCLUDING the `\n` of a `\r\n`: CPython emits
 * `\r\r\n` for a string that already held a CRLF, and so does this.
 */
export function toCrlf(text: string): string {
  return text.replace(/\n/g, '\r\n');
}

/** The same translation, gated the way CPython gates it: `#ifdef MS_WINDOWS`. */
export function pyNewlineOut(text: string): string {
  return process.platform === 'win32' ? toCrlf(text) : text;
}

/** `os.linesep` as one string — the line terminator a text-mode write actually emits. */
export const PY_LINESEP: string = process.platform === 'win32' ? '\r\n' : '\n';

/** `Path.write_text(text, encoding="utf-8")`, newline translation included. */
export function pyWriteText(path: string, text: string): void {
  try {
    writeFileSync(path, pyNewlineOut(text), 'utf8');
  } catch (e) {
    throw asPyOSError(e, path, undefined, 'crt');
  }
}

/**
 * `path.open("a", encoding="utf-8").write(text)` — the accounting log's append.
 *
 * Same newline translation as `pyWriteText`, for the same reason. One `appendFileSync` is
 * one `open(O_APPEND)/write/close`, which is what CPython's `with` block does, so a line is
 * never interleaved with another process's.
 */
export function pyAppendText(path: string, text: string): void {
  try {
    appendFileSync(path, pyNewlineOut(text), 'utf8');
  } catch (e) {
    throw asPyOSError(e, path, undefined, 'crt');
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
    throw asPyOSError(scandirShape(e, directory), directory, undefined, 'scandir');
  }
}

/**
 * The one place libuv and CPython make DIFFERENT SYSCALLS, not just different sentences.
 *
 * `os.scandir(p)` on Windows is `FindFirstFileW(p + "\\*")`, so `p` is a DIRECTORY COMPONENT
 * of the name being opened; a dangling FILE symlink there is `ERROR_DIRECTORY` (267) and
 * CPython raises `NotADirectoryError`. libuv opens a handle on `p` itself instead, follows
 * the reparse point, finds nothing and reports `ENOENT`. MEASURED, run 32646521489: for the
 * same dangling `facts` symlink the reference says "The directory name is invalid" and this
 * port said "No such file or directory (a path exists there)", and `count_facts` answered
 * `0` where the reference raised. That is not a wording difference — an answer of 0 sends a
 * caller down the success branch — so the SHAPE is restated here and the sentence follows.
 *
 * The probe is `lexists`, not `exists`: the whole point is a name that IS there while what
 * it names is not. `reference-windows-dangling-symlink-two-shapes` is the same finding from
 * the other side, and this is the second shape it predicted.
 */
function scandirShape(error: unknown, directory: string): unknown {
  const e = error as NodeFsError;
  if (process.platform !== 'win32') return error;
  if (!scandirIsNotADirectory(e?.code ?? '', () => pyLexists(directory))) return error;
  return { ...e, code: 'ENOTDIR', errno: undefined };
}

/** The decision inside `scandirShape`, without the platform gate, so a laptop can fail it. */
export function scandirIsNotADirectory(code: string, lexists: () => boolean): boolean {
  return code === 'ENOENT' && lexists();
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

/**
 * `sorted(paths)` when the paths are NESTED — the case `sortedPathNames` above cannot cover.
 *
 * `PurePath.__lt__` compares the `_parts_normcase` TUPLE, and a tuple comparison stops at
 * the first component that differs; it never sees the separator. Sorting the same paths as
 * STRINGS does see it, and `-` (0x2D) sorts before `/` (0x2F), so the two orders are
 * opposite for a pair like `a/b` and `a-b`:
 *
 *     sorted([Path("assets/a/b"), Path("assets/a-b")]) -> ['assets/a/b', 'assets/a-b']
 *     sorted(["assets/a/b", "assets/a-b"])             -> ['assets/a-b', 'assets/a/b']
 *
 * N3 measured that this does not bite `_fact_paths`, whose paths are all siblings of one
 * directory. It DOES bite `mcpserver._tree_digest`, which walks a nested tree and folds the
 * order straight into `assets_digest` — a digest computed in string order over the shipped
 * pack is a different digest, silently, and `build_identity` exists precisely to be
 * trustworthy about that. A shorter tuple sorts first when it is a prefix of the longer one,
 * which is `[] < ['b']` and needs no special case.
 */
export function sortedPathParts(paths: readonly (readonly string[])[]): string[][] {
  return paths
    .map((p) => [...p])
    .sort((a, b) => {
      const n = Math.min(a.length, b.length);
      for (let i = 0; i < n; i += 1) {
        const order = cmpCodepoint(normcase(a[i]!), normcase(b[i]!));
        if (order !== 0) return order;
      }
      return a.length - b.length;
    });
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
  if (process.platform === 'win32') return winStr(ntJoin(...parts));
  let anchor = '';
  const out: string[] = [];
  for (const part of parts) {
    // A leading separator, or a drive: `parsePath` is that reading, shared with `pyParents`
    // and `pyExpanduser` so the four cannot disagree about what a path is made of.
    const parsed = parsePath(part);
    // An ANCHORED later part replaces everything before it — `PurePath('/a', '/b')` is
    // `/b`. `load_grants` is where it fires: `config.parent / entry` with an absolute
    // `entry` is the entry, and joining them instead builds a path under the config that
    // never existed. The store never passes an absolute second part, so this arm was
    // unreachable until the binding layer arrived.
    if (parsed.anchor !== '') {
      anchor = parsed.anchor;
      out.length = 0;
    }
    out.push(...parsed.parts);
  }
  return renderPath(anchor, out);
}

/**
 * `PurePath`'s parsing of ONE path string: its anchor and its `_tail` components.
 *
 * Empty and `.` components are dropped, `..` is kept, and exactly two leading separators are
 * a root `PurePosixPath` keeps verbatim while one — or three or more — collapse to one.
 */
interface ParsedPath {
  anchor: string;
  parts: string[];
}

function parsePath(path: string): ParsedPath {
  if (process.platform === 'win32') {
    const { drive, root, tail } = parseWindowsPath(path);
    return { anchor: drive + root, parts: tail };
  }
  const pieces = path.split('/');
  let anchor = '';
  // `''.split('/')` is `['']`, which is not a leading separator: `str(PurePath(''))` is `.`
  // and has no anchor. Measured against CPython through `Path('').expanduser()`.
  if (path !== '' && pieces[0] === '') {
    let leading = 0;
    while (pieces[leading] === '') leading += 1;
    anchor = leading === 2 && pieces.length > 2 ? '//' : '/';
    pieces.splice(0, leading);
  }
  return { anchor, parts: pieces.filter((piece) => piece !== '' && piece !== '.') };
}

// --------------------------------------------------------------------- ntpath, on Windows

/**
 * `ntpath.splitroot` — drive, root, and the rest, ported branch for branch.
 *
 * The old spelling of `parsePath` counted leading separators the way `PurePosixPath` does,
 * and that reading is WRONG ON WINDOWS in the direction that changes an answer: `//a/b` is
 * not "a root and two components", it is a UNC share whose whole text is the drive, with no
 * parents at all and nothing for `_walk_to_store` to iterate. MEASURED against CPython 3.12
 * on run 32646521489 — `PureWindowsPath('//a/b').parents` is `[]` and this port answered
 * `['\\\\a', '\\\\']`, which is a walk over two directories that do not exist.
 *
 * The result is spelled with the CALLER's separators, not normalised ones, exactly as
 * `ntpath.splitroot` returns slices of its argument.
 */
export function ntSplitRoot(path: string): [string, string, string] {
  const norm = path.replace(/\//g, '\\');
  if (norm.startsWith('\\')) {
    if (norm.startsWith('\\\\')) {
      // `\\?\UNC\` is eight characters of prefix before the server name starts.
      const start = norm.slice(0, 8).toUpperCase() === '\\\\?\\UNC\\' ? 8 : 2;
      const index = norm.indexOf('\\', start);
      if (index === -1) return [path, '', ''];
      const index2 = norm.indexOf('\\', index + 1);
      if (index2 === -1) return [path, '', ''];
      return [path.slice(0, index2), path.slice(index2, index2 + 1), path.slice(index2 + 1)];
    }
    return ['', path.slice(0, 1), path.slice(1)];
  }
  if (norm.slice(1, 2) === ':') {
    if (norm.slice(2, 3) === '\\') return [path.slice(0, 2), path.slice(2, 3), path.slice(3)];
    return [path.slice(0, 2), '', path.slice(2)];
  }
  return ['', '', path];
}

/**
 * `PurePath._parse_path` under the Windows flavour: drive, root and the `_tail` components.
 *
 * The `drv_parts` arm is not decoration. `splitroot` hands back a bare `\\server\share` with
 * an EMPTY root, and pathlib puts the root back on when the drive names a real share (four
 * pieces) or a `\\?\UNC\server\share` (six) — which is why `//a/b` prints with a trailing
 * separator and `//a` does not.
 */
export function parseWindowsPath(path: string): { drive: string; root: string; tail: string[] } {
  if (path === '') return { drive: '', root: '', tail: [] };
  const normalised = path.replace(/\//g, '\\');
  const [drive, splitRoot, rest] = ntSplitRoot(normalised);
  let root = splitRoot;
  if (root === '' && drive.startsWith('\\') && !drive.endsWith('\\')) {
    const pieces = drive.split('\\');
    // `drv_parts[2] not in '?.'` is a SUBSTRING test in Python, and the empty string is a
    // substring of everything: `///a` splits to a third piece of `''`, the test is therefore
    // False, and the path keeps its empty root and stays RELATIVE. Spelling it as two
    // character comparisons made `///a` absolute — caught on a laptop by the case below,
    // which is the entire reason that case exists.
    if (pieces.length === 4 && !'?.'.includes(pieces[2]!)) root = '\\';
    else if (pieces.length === 6) root = '\\';
  }
  return { drive, root, tail: rest.split('\\').filter((piece) => piece !== '' && piece !== '.') };
}

/**
 * `ntpath.join` — what `PurePath.__truediv__` actually feeds the parser.
 *
 * `PurePath('//a') / 'facts'` is `\\a\facts\`, not `\\a\facts`, because the join produces
 * `//a\facts` and the RE-PARSE reads all of it as a share. Nothing else reproduces that.
 */
export function ntJoin(...parts: string[]): string {
  const separators = '\\/';
  let [drive, root, tail] = ntSplitRoot(parts[0] ?? '');
  for (const part of parts.slice(1)) {
    const [partDrive, partRoot, partTail] = ntSplitRoot(part);
    if (partRoot !== '') {
      if (partDrive !== '' || drive === '') drive = partDrive;
      root = partRoot;
      tail = partTail;
      continue;
    }
    if (partDrive !== '' && partDrive !== drive) {
      if (partDrive.toLowerCase() !== drive.toLowerCase()) {
        drive = partDrive;
        root = partRoot;
        tail = partTail;
        continue;
      }
      drive = partDrive;
    }
    if (tail !== '' && !separators.includes(tail[tail.length - 1]!)) tail += '\\';
    tail += partTail;
  }
  // A separator has to appear between a bare UNC share and a relative remainder.
  if (tail !== '' && root === '' && drive !== '' && !`:${separators}`.includes(drive[drive.length - 1]!)) {
    return `${drive}\\${tail}`;
  }
  return drive + root + tail;
}

/**
 * `PurePath._format_parsed_parts` under the Windows flavour — `str(PureWindowsPath)`.
 *
 * Exported, and every Windows arm below goes through it, so the flavour has exactly ONE
 * implementation and the conformance suite can drive it against `PureWindowsPath` from a
 * laptop instead of from a runner.
 */
export function winFormat(drive: string, root: string, tail: readonly string[]): string {
  if (drive !== '' || root !== '') return drive + root + tail.join('\\');
  // An anchorless path whose FIRST component would itself parse as a drive gets a `.` in
  // front, so `PureWindowsPath('a', 'C:x')` does not print as a drive-relative path.
  if (tail.length > 0 && ntSplitRoot(tail[0]!)[0] !== '') return ['.', ...tail].join('\\');
  return tail.join('\\') || '.';
}

/** `str(PureWindowsPath(path))`. */
export function winStr(path: string): string {
  const { drive, root, tail } = parseWindowsPath(path);
  return winFormat(drive, root, tail);
}

/** `PureWindowsPath.parents`. `//a/b` is a share and has NONE. */
export function winParents(path: string): string[] {
  const { drive, root, tail } = parseWindowsPath(path);
  const out: string[] = [];
  for (let n = tail.length - 1; n >= 0; n -= 1) out.push(winFormat(drive, root, tail.slice(0, n)));
  return out;
}

/** `PureWindowsPath.name`. */
export function winName(path: string): string {
  const { tail } = parseWindowsPath(path);
  return tail.length === 0 ? '' : tail[tail.length - 1]!;
}

/** `PureWindowsPath.is_absolute()` — `bool(drive and root)`, so a bare `//a` is NOT one. */
export function winIsAbsolute(path: string): boolean {
  const { drive, root } = parseWindowsPath(path);
  return drive !== '' && root !== '';
}

/** `PureWindowsPath.with_suffix`, which rebuilds the path in the flavour's own spelling. */
export function winWithSuffix(path: string, suffix: string): string {
  const { drive, root, tail } = parseWindowsPath(path);
  if (tail.length === 0) return winFormat(drive, root, tail);
  const name = tail[tail.length - 1]!;
  const dot = suffixDot(name);
  const stem = dot === -1 ? name : name.slice(0, dot);
  return winFormat(drive, root, [...tail.slice(0, -1), `${stem}${suffix}`]);
}

/** `str(PurePath)` for an already-parsed path: the empty path prints as `.`, as Python's does. */
function renderPath(anchor: string, parts: readonly string[]): string {
  if (parts.length === 0) return anchor === '' ? '.' : anchor;
  return anchor + parts.join('/');
}

/**
 * `PurePath.parents` — `_walk_to_store` iterates `(base, *base.parents)` and stops at `/`.
 *
 * The tail is not the anchor: `/a/b` yields `/a` then `/` and stops, while `a/b` yields `a`
 * then `.` — a relative start walks to the CWD-relative dot and no further, which is why
 * `_resolved_base` resolves before walking. `/` and `.` have no parents at all.
 */
export function pyParents(path: string): string[] {
  if (process.platform === 'win32') return winParents(path);
  const { anchor, parts } = parsePath(path);
  const out: string[] = [];
  for (let n = parts.length - 1; n >= 0; n -= 1) out.push(renderPath(anchor, parts.slice(0, n)));
  return out;
}

/** `PurePath.parent`. `/`'s parent is `/` and `.`'s is `.`, as in Python. */
export function pyParent(path: string): string {
  const parents = pyParents(path);
  if (parents.length > 0) return parents[0]!;
  if (process.platform === 'win32') {
    const { drive, root } = parseWindowsPath(path);
    return winFormat(drive, root, []);
  }
  return renderPath(parsePath(path).anchor, []);
}

/** `PurePath.name` — the last component, or `''` for a bare anchor. */
export function pyName(path: string): string {
  if (process.platform === 'win32') return winName(path);
  const { parts } = parsePath(path);
  return parts.length === 0 ? '' : parts[parts.length - 1]!;
}

/**
 * `PurePath.is_absolute()`.
 *
 * On Windows a root without a drive is NOT absolute (`PureWindowsPath('/a')` is relative to
 * the current drive), which is why this is not "starts with a separator". `_pinned_store`
 * raises on a relative pin, so getting this wrong there would accept a pin the reference
 * refuses, or refuse one it accepts.
 */
export function pyIsAbsolute(path: string): boolean {
  if (process.platform !== 'win32') return parsePath(path).anchor !== '';
  return winIsAbsolute(path);
}

// -------------------------------------------------------------------------- home and ~

/**
 * `RuntimeError`, which `Path.expanduser()` and `Path.resolve()` raise. NOT an `OSError`, so
 * nothing that catches `OSError` catches it — `_pinned_store`'s `except OSError` included.
 */
export class PyRuntimeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RuntimeError';
  }
}

/**
 * `Path.home()`, which is `os.path.expanduser('~')`.
 *
 * `$HOME` FIRST, and only then the passwd database — verified by overriding it. That order
 * is what lets the tests and the conformance harness point the profile layer somewhere that
 * is not the operator's own facts; a port that read the uid's home directly would recall
 * against, and STAMP, the real store on every run.
 *
 * An empty `HOME` is still a set `HOME` in Python (the test is `'HOME' not in os.environ`),
 * and `''.rstrip('/') or '/'` makes it `/`. `os.homedir()` falls back to the passwd entry
 * there instead, so the rule is spelled out rather than delegated.
 *
 * On Windows Python reads `USERPROFILE`, then `HOMEDRIVE`+`HOMEPATH`; `os.homedir()` reads
 * `USERPROFILE` and then the API. The first arm is the same, and it is the one a host sets.
 */
export function pyHome(): string {
  if (process.platform === 'win32') {
    const profile = process.env['USERPROFILE'];
    const drive = process.env['HOMEDRIVE'];
    const tail = process.env['HOMEPATH'];
    const raw = profile ?? (drive !== undefined && tail !== undefined ? drive + tail : homedir());
    return raw.replace(/[\\/]+$/, '') || '\\';
  }
  const home = process.env['HOME'];
  const raw = home !== undefined ? home : homedir();
  return raw.replace(/\/+$/, '') || '/';
}

/**
 * `Path(raw).expanduser()`.
 *
 * Only a FIRST component beginning with `~` expands, and only when the path has no anchor;
 * `/~/x` and `a/~` are left alone. An MCP host passes `env` verbatim with no shell, so the
 * tilde arrives literal and this is the only thing that expands it — see `_pinned_store`.
 *
 * RULING — `~someone-else`. Python asks the passwd database and resolves any account on the
 * machine (measured: `~root` -> `/var/root`). Node has no `getpwnam`, so this resolves `~`
 * and `~<the current user>` and raises Python's own `RuntimeError` for anything else, where
 * Python would have answered a path. Reproducing it means shelling out to `dscl`/`getent` at
 * runtime — a subprocess, in a pure-Node package, for a spelling of the pin nothing has ever
 * used. Carried as a must-differ case in `tools/conformance/suites/recall-strings.mjs`, so
 * it is re-measured on every run rather than remembered.
 */
export function pyExpanduser(path: string): string {
  const { anchor, parts } = parsePath(path);
  const first = parts[0];
  if (anchor !== '' || first === undefined || !first.startsWith('~')) {
    return renderPath(anchor, parts);
  }
  let home: string | null = null;
  const user = first.slice(1);
  if (user === '') home = pyHome();
  else {
    try {
      const info = userInfo();
      if (info.username === user) home = info.homedir.replace(/\/+$/, '') || '/';
    } catch {
      home = null; // no passwd entry at all; Python raises here too
    }
  }
  if (home === null) throw new PyRuntimeError('Could not determine home directory.');
  return pyJoin(home, ...parts.slice(1));
}

/** `Path.cwd()`. */
export function pyCwd(): string {
  return process.cwd();
}

// --------------------------------------------------------------------------- resolution

/**
 * `Path.resolve()` with `strict=False`: `posixpath.realpath`, then pathlib's ELOOP check.
 *
 * WHY NOT `fs.realpathSync`: it is strict. `_resolved_base` resolves a START DIRECTORY that
 * may not exist, and `load_grants` resolves a granted path precisely in order to then ask
 * whether it exists. Python resolves as far as the filesystem goes and appends the rest
 * verbatim — measured, `<bed>/nope/x` resolves to itself, and so does `<0o000-dir>/x/y`.
 *
 * `..` is applied to the path resolved SO FAR, not lexically to the input, so through a
 * symlinked directory it lands in the target's parent. That is what makes a symlinked
 * worktree bind the store beside its real checkout.
 *
 * A symlink LOOP is the one failure that is not swallowed: non-strict `realpath` returns the
 * unresolved path, `Path.resolve` then stats it, gets ELOOP, and raises
 * `RuntimeError("Symlink loop from %r" % e.filename)`. The `%r` is `repr`, not a pair of
 * apostrophes — the second spelling of the `OSError.__str__` bug N8 found, and fixed the
 * same way. Measured against CPython here.
 *
 * WINDOWS IS AN APPROXIMATION AND SAYS SO. `ntpath.realpath` goes through
 * `GetFinalPathNameByHandle` and returns forms this cannot reproduce; there this resolves
 * what it can natively and falls back to the lexical form. NOT MEASURED — no Windows runner
 * has run this port.
 */
export function pyResolve(path: string): string {
  if (process.platform === 'win32') return resolveWindows(path);
  const [resolved] = joinRealpath('', pyJoin(path), new Map<string, string | null>());
  const absolute = posixAbspath(resolved);
  try {
    statSync(absolute);
  } catch (e) {
    // pathlib's `check_eloop`: only a symlink loop is promoted; every other error is ignored.
    if ((e as NodeFsError)?.code === 'ELOOP') {
      throw new PyRuntimeError(`Symlink loop from ${pyRepr((e as NodeFsError).path ?? absolute)}`);
    }
  }
  return absolute;
}

/** `posixpath._joinrealpath`, ported statement for statement including the `seen` protocol. */
function joinRealpath(
  path: string,
  rest: string,
  seen: Map<string, string | null>,
): [string, boolean] {
  let current = path;
  let remaining = rest;
  if (remaining.startsWith('/')) {
    remaining = remaining.slice(1);
    current = '/';
  }
  while (remaining !== '') {
    const at = remaining.indexOf('/');
    const name = at === -1 ? remaining : remaining.slice(0, at);
    remaining = at === -1 ? '' : remaining.slice(at + 1);
    if (name === '' || name === '.') continue;
    if (name === '..') {
      if (current !== '') {
        const [head, tail] = posixSplit(current);
        current = head;
        if (tail === '..') current = posixJoin(posixJoin(current, '..'), '..');
      } else {
        current = '..';
      }
      continue;
    }
    const newpath = posixJoin(current, name);
    let isLink = false;
    try {
      isLink = lstatSync(newpath).isSymbolicLink();
    } catch {
      isLink = false; // non-strict: every OSError means "not a link", and the walk goes on
    }
    if (!isLink) {
      current = newpath;
      continue;
    }
    if (seen.has(newpath)) {
      const cached = seen.get(newpath)!;
      if (cached !== null) {
        current = cached;
        continue;
      }
      return [posixJoin(newpath, remaining), false]; // a loop; non-strict leaves it alone
    }
    seen.set(newpath, null);
    const [resolved, ok] = joinRealpath(current, readlinkSync(newpath), seen);
    if (!ok) return [posixJoin(resolved, remaining), false];
    current = resolved;
    seen.set(newpath, current);
  }
  return [current, true];
}

/** `posixpath.split`: the head keeps its trailing separator only when it is the root. */
function posixSplit(path: string): [string, string] {
  const cut = path.lastIndexOf('/');
  if (cut === -1) return ['', path];
  const head = path.slice(0, cut + 1);
  return [head === '/' ? head : head.replace(/\/+$/, ''), path.slice(cut + 1)];
}

/** `posixpath.join` for two components. */
function posixJoin(a: string, b: string): string {
  if (b.startsWith('/')) return b;
  if (a === '' || a.endsWith('/')) return a + b;
  return `${a}/${b}`;
}

/** `posixpath.abspath` = `normpath(join(getcwd(), path))`. Two leading slashes survive. */
function posixAbspath(path: string): string {
  const joined = path.startsWith('/') ? path : posixJoin(process.cwd(), path);
  const leading = /^\/\/(?!\/)/.test(joined) ? '//' : joined.startsWith('/') ? '/' : '';
  const out: string[] = [];
  for (const piece of joined.split('/')) {
    if (piece === '' || piece === '.') continue;
    if (piece === '..' && leading !== '') {
      if (out.length > 0 && out[out.length - 1] !== '..') out.pop();
      continue;
    }
    if (piece === '..' && out.length > 0 && out[out.length - 1] !== '..') {
      out.pop();
      continue;
    }
    out.push(piece);
  }
  return leading + out.join('/') || '.';
}

/**
 * The Windows arm of `pyResolve` — `ntpath.realpath(strict=False)` and pathlib's ELOOP check.
 *
 * SWALLOWING THE FAILURE WAS THE DEFECT. This used to answer `realpathSync.native` or, on any
 * error at all, the lexical path — which is neither of the two things CPython does. MEASURED
 * on run 32646521489, both halves: a DANGLING symlink resolves to its TARGET on the reference
 * (`<bed>\dang` -> `<bed>\nowhere`) and this port answered `<bed>\dang`; and a self-referential
 * symlink raises `RuntimeError("Symlink loop from %r")` on the reference while this port
 * raised nothing and returned a path. A missing raise is worse than a wrong sentence: the
 * caller takes the success branch.
 *
 * Both come out of `ntpath._getfinalpathname_nonstrict`, which is ported below: when the OS
 * cannot resolve a name it FOLLOWS THE LINK ITSELF with `readlink` before giving up, and only
 * then walks up a component. The loop survives that walk — `_readlink_deep` stops when it
 * revisits a name — and is caught afterwards by the `stat` that `Path.resolve` runs precisely
 * so that non-strict resolution still raises on a cycle.
 */
function resolveWindows(path: string): string {
  const absolute = pyIsAbsolute(path) ? path : ntJoin(process.cwd(), path);
  let resolved: string;
  try {
    resolved = realpathSync.native(absolute);
  } catch {
    resolved = getFinalPathNameNonStrict(absolute);
  }
  resolved = pyJoin(resolved);
  try {
    statSync(resolved);
  } catch (e) {
    // `check_eloop`: `errno == ELOOP or winerror == 1921`. libuv folds
    // `ERROR_CANT_RESOLVE_FILENAME` into `UV_ELOOP`, so the one code covers both tests.
    if ((e as NodeFsError)?.code === 'ELOOP') {
      throw new PyRuntimeError(`Symlink loop from ${pyRepr((e as NodeFsError).path ?? resolved)}`);
    }
  }
  return resolved;
}

/** `ntpath._readlink_deep` — follow the chain by hand, stopping the first time a name repeats. */
function readlinkDeep(start: string): string {
  const seen = new Set<string>();
  let path = start;
  while (!seen.has(normcase(path))) {
    seen.add(normcase(path));
    let target: string;
    try {
      target = readlinkSync(path);
    } catch {
      break; // not a link, or unreadable: what we have is the answer
    }
    path = pyIsAbsolute(target) ? target : ntJoin(ntDirname(path), target);
  }
  return path;
}

/** `ntpath._getfinalpathname_nonstrict` — as much of the target as the OS will resolve. */
function getFinalPathNameNonStrict(start: string): string {
  let path = start;
  let tail = '';
  while (path !== '') {
    try {
      const got = realpathSync.native(path);
      return tail === '' ? got : ntJoin(got, tail);
    } catch {
      /* every allowed winerror; the walk goes on */
    }
    const followed = readlinkDeep(path);
    if (followed !== path) return tail === '' ? followed : ntJoin(followed, tail);
    const [head, name] = ntSplit(path);
    if (head !== '' && name === '') return head + tail;
    tail = tail === '' ? name : ntJoin(name, tail);
    path = head;
  }
  return tail;
}

/** `ntpath.split` — the head keeps its trailing separators only where they are the root. */
function ntSplit(path: string): [string, string] {
  const [drive, root, rest] = ntSplitRoot(path);
  let cut = rest.length;
  while (cut > 0 && !'\\/'.includes(rest[cut - 1]!)) cut -= 1;
  const name = rest.slice(cut);
  let head = rest.slice(0, cut);
  head = head.replace(/[\\/]+$/, '') || head;
  return [drive + root + head, name];
}

/** `ntpath.dirname`. */
function ntDirname(path: string): string {
  return ntSplit(path)[0];
}

// -------------------------------------------------------------------------- stat probes

/**
 * `Path.is_dir()` — and it RE-RAISES, which is the half that matters.
 *
 * `pathlib` swallows only `_IGNORED_ERRNOS`; `EACCES` is not one of them, so a candidate
 * inside a directory the process cannot traverse raises `PermissionError` out of the WALK
 * itself. MEASURED against CPython 3.12 here: `_walk_to_store` through a `0o000` ancestor
 * raises rather than skipping the candidate, which refutes the claim in `_pinned_store`'s
 * docstring that the walk "lives with" an unreadable candidate. `existsSync` and
 * `statSync(p, {throwIfNoEntry: false})` both answer `false` there and would bind a
 * different store in silence.
 */
export function pyIsDir(path: string): boolean {
  try {
    return statSync(path).isDirectory();
  } catch (e) {
    if (IGNORED.has((e as NodeFsError)?.code ?? '')) return false;
    throw asPyOSError(e, path);
  }
}

/** `Path.is_file()`, with the same swallow set as `pyIsDir`. */
export function pyIsFile(path: string): boolean {
  try {
    return statSync(path).isFile();
  } catch (e) {
    if (IGNORED.has((e as NodeFsError)?.code ?? '')) return false;
    throw asPyOSError(e, path);
  }
}

/**
 * `os.stat(p)` reduced to "is it a directory", unguarded.
 *
 * `_pinned_store` uses `os.stat` rather than `is_dir()` on purpose: a pin is a single path
 * the operator named out loud, so an unreadable one gets the accurate reason instead of
 * being reported as a typo.
 */
export function pyStatIsDir(path: string): boolean {
  try {
    return statSync(path).isDirectory();
  } catch (e) {
    throw asPyOSError(e, path);
  }
}

// --------------------------------------------------------------------------------- repr

/**
 * `repr(str)`, which `_pinned_store` interpolates with `{raw!r}` for a relative pin.
 *
 * Python quotes with `'` unless the value contains a `'` and no `"`; it escapes `\\`, the
 * quote, `\t`, `\n`, `\r`, and every codepoint that is not `str.isprintable()` — that is,
 * everything in a `C*` category and every separator except the space itself. JS spells the
 * same predicate `\p{C}` / `\p{Z}` under the `u` flag, so this is the rule rather than a
 * table. The escapes are `\xNN` below U+0100, `\uNNNN` below U+10000, `\UNNNNNNNN` above.
 *
 * The one place it can drift is a codepoint whose category changed between CPython 3.12's
 * Unicode 15.0 and the ICU this Node was built against: a newly assigned character is `Cn`
 * (not printable, escaped) for Python and assigned (printable, raw) here. A pin path made of
 * brand-new codepoints is the only input that reaches it.
 */
export function pyRepr(value: string): string {
  const quote = value.includes("'") && !value.includes('"') ? '"' : "'";
  let out = quote;
  for (const ch of value) {
    if (ch === '\\') out += '\\\\';
    else if (ch === quote) out += `\\${ch}`;
    else if (ch === '\t') out += '\\t';
    else if (ch === '\n') out += '\\n';
    else if (ch === '\r') out += '\\r';
    else if (ch === ' ' || !/^(?:\p{C}|\p{Z})$/u.test(ch)) out += ch;
    else {
      const cp = ch.codePointAt(0)!;
      if (cp < 0x100) out += `\\x${cp.toString(16).padStart(2, '0')}`;
      else if (cp < 0x10000) out += `\\u${cp.toString(16).padStart(4, '0')}`;
      else out += `\\U${cp.toString(16).padStart(8, '0')}`;
    }
  }
  return out + quote;
}

/**
 * `repr(float)`.
 *
 * CPython formats with `PyOS_double_to_string(v, 'r', 0, Py_DTSF_ADD_DOT_0)`: the shortest
 * decimal that round-trips, rendered in scientific notation when the decimal point falls at
 * or left of position -4 or right of position 16, and with a forced `.0` otherwise. JS
 * agrees on the DIGITS (`toExponential()` with no argument is also shortest-round-trip) and
 * on nothing else: it switches to scientific at 1e21 and 1e-7, writes `10000000000000000`
 * where Python writes `1e+16`, and never pads the exponent to two digits.
 */
export function pyFloatRepr(x: number): string {
  if (Number.isNaN(x)) return 'nan';
  if (x === Infinity) return 'inf';
  if (x === -Infinity) return '-inf';
  const negative = x < 0 || Object.is(x, -0);
  const [mantissa, exponent] = Math.abs(x).toExponential().split('e') as [string, string];
  const digits = mantissa.replace('.', '');
  const decpt = Number(exponent) + 1; // digits[0] sits just left of position `decpt`
  const sign = negative ? '-' : '';
  if (decpt <= -4 || decpt > 16) {
    const head = digits.slice(0, 1);
    const tail = digits.slice(1).replace(/0+$/, '');
    const e = decpt - 1;
    const eSign = e < 0 ? '-' : '+';
    return `${sign}${head}${tail ? `.${tail}` : ''}e${eSign}${String(Math.abs(e)).padStart(2, '0')}`;
  }
  if (decpt <= 0) return `${sign}0.${'0'.repeat(-decpt)}${digits}`;
  if (decpt >= digits.length) return `${sign}${digits}${'0'.repeat(decpt - digits.length)}.0`;
  return `${sign}${digits.slice(0, decpt)}.${digits.slice(decpt)}`;
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
  // `with_suffix` rebuilds a `PurePath`, so the answer comes back in the flavour's own
  // spelling: `PureWindowsPath('/f/a.md').with_suffix('.md.tmp')` is `\f\a.md.tmp`, with the
  // separators the CALLER wrote replaced. MEASURED against CPython 3.12; slicing the input
  // string kept `/f/a.md.tmp`, which is a path the reference never prints.
  if (process.platform === 'win32') return winWithSuffix(path, suffix);
  const { anchor, parts } = parsePath(path);
  if (parts.length === 0) return renderPath(anchor, parts);
  const name = parts[parts.length - 1]!;
  const dot = suffixDot(name);
  const stem = dot === -1 ? name : name.slice(0, dot);
  return renderPath(anchor, [...parts.slice(0, -1), `${stem}${suffix}`]);
}

/**
 * `PurePath.suffix`: the last dot counts only when it is neither the first character of the
 * name nor the last one, so `.md` has no suffix and `a.` has none either.
 */
function suffixDot(name: string): number {
  const dot = name.lastIndexOf('.');
  return dot > 0 && dot < name.length - 1 ? dot : -1;
}

/**
 * `PurePath.suffix` as a value, which `shiftwork.clock_out` needs on its own:
 * `path.with_suffix(path.suffix + ".tmp")` turns `cp.json` into `cp.json.tmp` and a
 * suffix-less `cp` into `cp.tmp`, and the two arms are only distinguishable by reading the
 * suffix first.
 */
export function pySuffix(path: string): string {
  const dot = suffixDot(pyName(path));
  return dot === -1 ? '' : pyName(path).slice(dot);
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
    // TWO filenames: `os.replace` sets `filename2`, so `str(e)` is `... : 'src' -> 'dst'`.
    throw asPyOSError(e, source, target);
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
