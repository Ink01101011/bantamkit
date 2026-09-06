/**
 * A module-load hook that COUNTS real `docread.extract` calls in a running server process.
 *
 * job44 U5, register entry (i). The claim being tested is "paging through one unchanged
 * document parses it once", and the only honest evidence for it is a count of the parses —
 * not a reading of the cache, and not a stopwatch. The reference (`runtime-py`) counts by
 * monkeypatching `docread.extract` from the test; an ES module namespace is read-only from
 * the importer's side, so the equivalent seam here is a `load` hook that appends a wrapper to
 * `dist/docread.js` as it is loaded. A function declaration is a MUTABLE binding inside its
 * own module and module exports are LIVE, so reassigning `extract` there is seen by
 * `server.js`'s `docread.extract(path)` — which is the call the count is about.
 *
 * The wrapper writes one line per call to stderr rather than keeping a number, because the
 * server under test is a separate PROCESS: the test drives it over stdio and reads the lines
 * back. Nothing about the server's own behaviour changes — `extract` still runs, still
 * returns the same `Document`, still raises the same refusals.
 */
const FOOTER = `
;{
  const __bkOriginalExtract = extract;
  extract = function (...a) {
    process.stderr.write("BK-EXTRACT " + a[0] + "\\n");
    return __bkOriginalExtract.apply(this, a);
  };
}
`;

export async function load(url, context, nextLoad) {
  const result = await nextLoad(url, context);
  if (!url.endsWith('/dist/docread.js')) {
    return result;
  }
  const source = typeof result.source === 'string' ? result.source : Buffer.from(result.source).toString('utf8');
  return { ...result, shortCircuit: true, source: source + FOOTER };
}
