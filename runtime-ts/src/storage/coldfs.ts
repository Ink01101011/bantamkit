/**
 * The reads `coldindex.ts` makes, through one object a test swaps `readFileSync` on to count the
 * files a query opens (`test/storage-coldindex.test.mjs`).
 *
 * Moved out of `coldindex.ts` unchanged (#316 G4, J90-3) so that module can be compiled by
 * `tools/ts2py` while this one stays an ADAPTER: the Python counterpart is the same object over
 * the builtin `open(path, encoding="utf-8")` the reference's `_read_json` called, which is what
 * `pyReadText` ports (strict UTF-8, universal newlines), so the Python test's `builtins.open` spy
 * still sees every read. Strict UTF-8: a segment holding a byte that is not UTF-8 is refused
 * (`ColdIndexError`), not served with U+FFFD in a doc (J90-1F #10).
 */
import { pyReadText } from '../memory/pyfs.js';

export const coldFs = { readFileSync: (p: string): string => pyReadText(p) };

/**
 * The text a `ColdIndexError` quotes for a read that failed: the error's own message (#316 G4,
 * J90-3: moved here from coldindex.ts's `errMessage`, unchanged). An ADAPTER, because a JSON
 * syntax error's message is the parser's own wording: V8's here, CPython's `json` on the
 * reference, which the Python counterpart keeps (`str(e)`; an `OSError` as CPython's `str(e)`,
 * which `PyOSError.message` already is here). Pinned per side in `--suite storage-cold`.
 */
export function coldErrorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
