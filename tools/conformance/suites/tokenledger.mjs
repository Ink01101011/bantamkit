/**
 * tokenledger — the transcript ledger, Python against Node, byte for byte.
 *
 * THE PROPERTY: over the same corpus of transcripts and the same arguments, Node emits the
 * BYTE-IDENTICAL JSON document Python emits, and where they refuse, the byte-identical
 * refusal. That document is not a diagnostic — `token_ledger` hands the model `as_json()`
 * verbatim — so a caller reading `totals` before and after a change, or reading `omissions` to
 * decide whether a small total is real, is reading these exact bytes.
 *
 * WHAT IT READS, AND WHY IT CANNOT BE PERTURBED BY A SESSION RUNNING WHILE IT RUNS
 * -------------------------------------------------------------------------------
 * `tools/ledger/fixtures/token-ledger/projects`, committed, plus corpora this file writes into
 * the harness scratch directory. It NEVER reads `~/.claude/projects`, and this is the whole
 * design constraint of the unit: the scripts under `tools/ledger/` read the host's live
 * transcripts, and J46-1 measured that two runs of one tool on one day disagree because the
 * session in between added a call. A differential over a live corpus is a case that will go
 * red for a reason nobody caused and will then be "fixed" by weakening it. So `read()` takes
 * `root` from the caller — exactly as `skill_audit` takes its own — the fixture is a frozen
 * tree in git, and the answer is a function of bytes that only a commit can change.
 *
 * WHAT IS COMPARED
 *   1. `read()` over the committed corpus and over five scratch corpora, in fourteen
 *      configurations: bare, priced against the SHIPPED table (which is the refusal, and the
 *      normal answer today), priced against a table that HAS rates, priced against a table
 *      that will not load, the four argument refusals, an empty corpus, a corpus of nothing
 *      but omissions, and the 2**53 ceiling. The whole `as_json()` string is the case, so key
 *      order, two-space indent and `ensure_ascii=False` are under test and not merely the
 *      numbers — the fixture's Thai `cwd` and its two non-BMP session ids are what make
 *      `ensure_ascii=False` a claim these cases can check at all.
 *   2. The WALK ORDER, as a sequence, over the committed corpus and over a scratch tree whose
 *      names sort one way by code point and the other by UTF-16 code unit. The order is
 *      otherwise visible in the answer only through which copy of a duplicated `requestId`
 *      won, which is one bit; comparing the sequence is what makes "sorted at every level"
 *      something the harness can see. `！a.jsonl` (U+FF01) and `𝄞a.jsonl` (U+1D11E) are the
 *      pair: code point puts `！` first, `.sort()` puts the astral name first because its lead
 *      surrogate is 0xD834.
 *   3. The REFUSALS, as sentences AND as the class that raised them. `TokenLedgerError` and
 *      `PriceTableError` reach the caller through one handler and print the same way, so a
 *      port that raised the other one would be invisible in the message alone.
 *   4. The constants, and then the constants AGAIN as typed literals.
 *
 * AND WHERE A DIFFERENTIAL IS STRUCTURALLY BLIND, THERE IS A LITERAL. Measured EIGHT times in
 * job46: a mutation applied to BOTH runtimes at once reddens ZERO differential cases. This
 * ledger is full of rules a symmetric edit could delete — the `requestId` dedupe, the walk
 * sort, the omission subjects — and two runtimes that both stopped deduping would agree
 * perfectly on a wrong number. So `literalCases` below pins the omission vocabulary, the
 * corpus's headline counts, and the accounting identity `lines == requests + sum(counts)`
 * against TYPED constants, once per side.
 *
 * THE HEADLINE COUNTS ARE A PROPERTY OF THE COMMITTED FIXTURE and move only when it moves.
 * They are spelled here rather than derived, because deriving them from the same walk that
 * produced them would assert nothing.
 */
import { chmodSync, mkdirSync, symlinkSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'tokenledger';
export const summary = 'the transcript ledger: one JSON document, the same bytes on both sides';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'tokenledger_ref.py');
const CORPUS = join(repoRoot, 'tools', 'ledger', 'fixtures', 'token-ledger', 'projects');
const SHIPPED = join(repoRoot, 'assets', 'pricing', 'default.json');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

/** One `usage` block, all four classes, as the host writes it. */
const usage = (o) => ({
  input_tokens: 0,
  cache_creation_input_tokens: 0,
  cache_read_input_tokens: 0,
  output_tokens: 0,
  ...o,
});

const line = (o) => `${JSON.stringify(o)}\n`;

/** A priced table. Not a real rate — a round arithmetic bed, sourced to this file. */
const RATED = JSON.stringify({
  schema_version: 1,
  currency: 'USD',
  unit: 'micro_usd_per_million_tokens',
  rates: {
    'a-model': {
      recorded: '2026-09-11',
      source: 'the conformance suite, which is not a price source',
      input_tokens: 3000000,
      output_tokens: 15000000,
      cache_read_input_tokens: 300000,
      cache_creation_input_tokens: 3750000,
    },
  },
});

/**
 * The committed corpus's headline, as typed constants. A differential cannot see a rule that
 * was deleted from both sides; these can. Every number here is a count of something in
 * `tools/ledger/fixtures/token-ledger/projects` and moves only when that tree does.
 */
const CORPUS_HEADLINE = {
  transcripts: 5,
  lines: 19,
  requests: 7,
  sessions: 3,
  totals: {
    input_tokens: 22,
    cache_creation_input_tokens: 201,
    cache_read_input_tokens: 3155,
    output_tokens: 52,
  },
  omissions: [
    ['undecodable-file', 1],
    ['unparsed-line', 2],
    ['not-an-object', 1],
    ['no-session-id', 1],
    ['not-an-assistant-record', 1],
    ['no-usage', 1],
    ['malformed-usage', 2],
    ['no-request-id', 1],
    ['duplicate-request', 2],
  ],
  // The identity, arithmetic done by hand: 7 + (1+2+1+1+1+1+2+1+2) = 7 + 12 = 19.
  omitted: 12,
  sidechain_requests: 1,
};

const CONSTANTS = {
  OMISSION_ORDER: [
    'undecodable-file',
    'unparsed-line',
    'not-an-object',
    'no-session-id',
    'not-an-assistant-record',
    'no-usage',
    'malformed-usage',
    'no-request-id',
    'duplicate-request',
  ],
  TRANSCRIPT_SUFFIX: '.jsonl',
  subjects: {
    OMIT_UNDECODABLE: 'undecodable-file',
    OMIT_UNPARSED: 'unparsed-line',
    OMIT_NOT_OBJECT: 'not-an-object',
    OMIT_NO_SESSION: 'no-session-id',
    OMIT_NOT_ASSISTANT: 'not-an-assistant-record',
    OMIT_NO_USAGE: 'no-usage',
    OMIT_MALFORMED_USAGE: 'malformed-usage',
    OMIT_NO_REQUEST_ID: 'no-request-id',
    OMIT_DUPLICATE_REQUEST: 'duplicate-request',
  },
};

/**
 * The rules a differential is structurally blind to, pinned as literals against EACH side
 * separately. MEASURED, J45-8 and eight times since: mutants applied to both runtimes at once
 * redden ZERO differential cases.
 */
function literalCases(pySide, nodeSide, label, expected) {
  return [
    { name: `${label} — python`, kind: 'json', expected, actual: pySide },
    { name: `${label} — node`, kind: 'json', expected, actual: nodeSide },
  ];
}

/** The headline a document carries, read back out of it, so a literal can be asserted on it. */
function headlineOf(doc) {
  return {
    transcripts: doc.transcripts,
    lines: doc.lines,
    requests: doc.requests,
    sessions: doc.sessions.length,
    totals: doc.totals,
    omissions: doc.omissions.map((o) => [o.subject, o.count]),
    omitted: doc.omissions.reduce((t, o) => t + o.count, 0),
    sidechain_requests: doc.sessions.reduce((t, s) => t + s.sidechain_requests, 0),
  };
}

export async function run(ctx) {
  const tokenledger = await import(
    pathToFileURL(join(ctx.runtimeTs, 'dist', 'tokenledger.js')).href
  );
  const pricing = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'pricing.js')).href);
  const cases = [];
  const notes = [];

  const bed = join(ctx.scratch, 'tokenledger');
  mkdirSync(bed, { recursive: true });
  const write = (base, body) => {
    const p = join(bed, base);
    mkdirSync(dirname(p), { recursive: true });
    writeFileSync(p, body);
    return p;
  };

  // ------------------------------------------------------------------ the scratch corpora

  // An EMPTY corpus. Every counter zero, `omissions` empty, and the document still whole —
  // the arm a suite of only-interesting inputs never reaches.
  const empty = join(bed, 'empty');
  mkdirSync(empty, { recursive: true });

  // A corpus of NOTHING BUT omissions: no request survives, so `requests` is 0 while `lines`
  // is not. This is the case that proves "your transcripts hold no usage" is distinguishable
  // from "I read nothing at all", which is the point of the accounting identity.
  const onlyOmissions = join(bed, 'omissions-only');
  write('omissions-only/a.jsonl', ['{', '[]', line({ type: 'assistant' }).trim()].join('\n') + '\n');

  // The 2**53 ceiling: two records at MAX_SAFE_INT each. Python's `int` keeps going and a JS
  // `number` rounds, so the place the two would part company is a refusal on both sides.
  const MAX = 9007199254740991;
  const ceiling = join(bed, 'ceiling');
  write(
    'ceiling/a.jsonl',
    line({ type: 'assistant', sessionId: 's', requestId: 'q1', message: { usage: usage({ input_tokens: MAX }) } }) +
      line({ type: 'assistant', sessionId: 's', requestId: 'q2', message: { usage: usage({ input_tokens: 1 }) } }),
  );

  // The walk-order bed. `！a.jsonl` (U+FF01) and `𝄞a.jsonl` (U+1D11E) hold the SAME
  // `requestId`, so the order is not merely reported — it decides which file's copy is
  // counted and which is the `duplicate-request`. A `.sort()` here answers the other one.
  const astral = join(bed, 'astral');
  const dup = (cwd) =>
    line({ type: 'assistant', sessionId: 's', cwd, requestId: 'q1', timestamp: '2026-09-10T00:00:00.000Z', message: { usage: usage({ output_tokens: 1 }) } });
  write('astral/！a.jsonl', dup('/w/fullwidth'));
  write('astral/\u{1D11E}a.jsonl', dup('/w/clef'));
  write('astral/nested/！b.jsonl', '');
  write('astral/nested/\u{1D11E}b.jsonl', '');

  // #150: a leading UTF-8 BOM, on the FIRST line, before a record that is otherwise whole.
  // The ruling is "unparsed on both sides": the host never writes a BOM, so a line carrying
  // one is not the host's line and is named as an omission. Line 2 is a clean record, so the
  // file still counts one request and the BOM is visible as exactly one `unparsed-line`.
  const bomBed = join(bed, 'bom');
  const rec = (requestId) =>
    line({ type: 'assistant', sessionId: 's', requestId, timestamp: '2026-10-15T00:00:00.000Z', message: { usage: usage({ output_tokens: 1 }) } });
  write('bom/-p/s.jsonl', `\uFEFF${rec('q1')}${rec('q2')}`);

  // #151: one real transcript, a directory symlink to its own parent (a loop), and a symlink
  // to the transcript FILE. The loop is skipped — neither walked nor read — and the file link
  // is read, so it is the one `duplicate-request`. Following the loop counted the transcript
  // once per level until ELOOP (33 on macOS). Windows may refuse to make a symlink without
  // privilege; then the bed has no links and its cases are not built (a note says so).
  const loopBed = join(bed, 'symlink-loop');
  write('symlink-loop/-p/s.jsonl', rec('q1'));
  let loopBuilt = true;
  try {
    symlinkSync('..', join(loopBed, '-p', 'up'), 'dir');
    symlinkSync('s.jsonl', join(loopBed, '-p', 'alias.jsonl'), 'file');
  } catch (err) {
    loopBuilt = false;
    notes.push(`symlink-loop bed not built (${err?.code ?? err}); #151 cases skipped on this host`);
  }

  const rated = write('rated.json', RATED);
  const broken = write('broken.json', '{"schema_version": 1,');
  const missingTable = join(bed, 'no-such-table.json');
  const aFile = join(CORPUS, '-proj-a', 's1.jsonl');

  // ------------------------------------------------------------------ read()

  const READ_CASES = [
    ['the committed corpus', { root: CORPUS }],
    // The DEFAULT table path, which honours `$BANTAMKIT_PRICES`. It stays a differential and
    // never a literal: both runtimes read the same environment, so they must agree whatever it
    // says, but what it says is the operator's and not this suite's to assert.
    ['the committed corpus, priced by the DEFAULT table', { root: CORPUS, model: 'a-model' }],
    ['the committed corpus, priced by the SHIPPED table', { root: CORPUS, model: 'a-model', prices: SHIPPED }],
    ['the committed corpus, priced by the shipped table under a non-ASCII name', { root: CORPUS, model: 'ครับ', prices: SHIPPED }],
    ['the committed corpus, priced by a table that HAS the rate', { root: CORPUS, model: 'a-model', prices: rated }],
    ['the committed corpus, a model the rated table does not price', { root: CORPUS, model: 'other', prices: rated }],
    ['the committed corpus, a price table that will not parse', { root: CORPUS, model: 'a-model', prices: broken }],
    ['the committed corpus, a price table that is not there', { root: CORPUS, model: 'a-model', prices: missingTable }],
    ['an empty corpus', { root: empty }],
    ['an empty corpus, priced', { root: empty, model: 'a-model', prices: rated }],
    ['a corpus of nothing but omissions', { root: onlyOmissions }],
    ['the 2**53 ceiling', { root: ceiling }],
    ['the astral walk bed', { root: astral }],
    ['a BOM before the first record (#150)', { root: bomBed }],
    ...(loopBuilt ? [['a directory symlink loop and a file symlink (#151)', { root: loopBed }]] : []),

    // The four argument refusals.
    ['an empty root', { root: '' }],
    ['a root that is not there', { root: join(bed, 'no-such-corpus') }],
    ['a root that is a file', { root: aFile }],
    ['an empty model', { root: CORPUS, model: '' }],

    // The order-of-checks contract: BOTH wrong, and the ROOT fault is what is named — the
    // corpus is what a caller would have to fix first, and a price table is not consulted at
    // all until there is something to price.
    ['an empty root AND an empty model', { root: '', model: '' }],
  ];

  const pyRead = ctx.runPython(REF, {
    op: 'read',
    cases: READ_CASES.map(([, c]) => ({
      root: c.root,
      model: c.model === undefined ? null : b64(c.model),
      prices: c.prices ?? null,
    })),
  }).out;

  READ_CASES.forEach(([label, c], i) => {
    let actual;
    try {
      const ledger = tokenledger.read(c.root, { model: c.model ?? null, prices: c.prices ?? null });
      actual = { json: b64(tokenledger.asJson(ledger)) };
    } catch (err) {
      const type =
        err instanceof tokenledger.TokenLedgerError
          ? 'TokenLedgerError'
          : err instanceof pricing.PriceTableError
            ? 'PriceTableError'
            : `unexpected:${err?.constructor?.name}`;
      actual = { error: { type, message: b64(err.message) } };
    }
    cases.push({ name: `read: ${label}`, kind: 'json', expected: pyRead[i], actual });
  });

  // The document itself, as a STRING, for the two corpora whose bytes carry non-ASCII. `kind:
  // 'json'` above already compares the base64, but a string case is what `--require-exact-
  // strings` can see and what a reader of a failure gets a diff of.
  for (const [label, root] of [['the committed corpus', CORPUS], ['the astral walk bed', astral]]) {
    const i = READ_CASES.findIndex(([l]) => l === label);
    cases.push({
      name: `document: ${label}`,
      kind: 'string',
      expected: unb64(pyRead[i].json),
      actual: tokenledger.asJson(tokenledger.read(root)),
    });
  }

  // ------------------------------------------------------------------ the walk order

  for (const [label, root] of [
    ['the committed corpus', CORPUS],
    ['names that sort apart in UTF-16', astral],
    ['an empty tree', empty],
    ...(loopBuilt ? [['a directory symlink loop (#151)', loopBed]] : []),
  ]) {
    const py = ctx.runPython(REF, { op: 'walk', root }).out.map(unb64);
    cases.push({
      name: `walk: ${label}`,
      kind: 'json',
      expected: py,
      actual: tokenledger.walk(root).map(([, rel]) => rel),
    });
  }

  // ------------------------------------------------------------------ the constants

  const pyConst = ctx.runPython(REF, { op: 'constants' });
  const ndConst = {
    OMISSION_ORDER: [...tokenledger.OMISSION_ORDER],
    TRANSCRIPT_SUFFIX: tokenledger.TRANSCRIPT_SUFFIX,
    subjects: {
      OMIT_UNDECODABLE: tokenledger.OMIT_UNDECODABLE,
      OMIT_UNPARSED: tokenledger.OMIT_UNPARSED,
      OMIT_NOT_OBJECT: tokenledger.OMIT_NOT_OBJECT,
      OMIT_NO_SESSION: tokenledger.OMIT_NO_SESSION,
      OMIT_NOT_ASSISTANT: tokenledger.OMIT_NOT_ASSISTANT,
      OMIT_NO_USAGE: tokenledger.OMIT_NO_USAGE,
      OMIT_MALFORMED_USAGE: tokenledger.OMIT_MALFORMED_USAGE,
      OMIT_NO_REQUEST_ID: tokenledger.OMIT_NO_REQUEST_ID,
      OMIT_DUPLICATE_REQUEST: tokenledger.OMIT_DUPLICATE_REQUEST,
    },
  };
  cases.push({ name: 'the constants agree', kind: 'json', expected: pyConst, actual: ndConst });
  cases.push(...literalCases(pyConst, ndConst, 'the omission vocabulary is what it is', CONSTANTS));

  // ------------------------------------------------------------------ the literals

  const at = (label) => {
    const i = READ_CASES.findIndex(([l]) => l === label);
    if (i < 0) throw new Error(`no read case named ${label}`);
    return pyRead[i];
  };
  const pyDoc = JSON.parse(unb64(at('the committed corpus').json));
  const ndDoc = JSON.parse(tokenledger.asJson(tokenledger.read(CORPUS)));
  cases.push(
    ...literalCases(
      headlineOf(pyDoc),
      headlineOf(ndDoc),
      'the committed corpus counts what it counts',
      CORPUS_HEADLINE,
    ),
  );

  // The shipped table is EMPTY, so a priced call over the real asset is a REFUSAL. This is the
  // normal answer a user gets today and it is asserted as a literal on both sides, because a
  // differential between two runtimes reading one file cannot see a rate pasted into it.
  const REFUSAL = {
    unavailable:
      "no rate recorded for model 'a-model' -- add one with its date and source, or point BANTAMKIT_PRICES at a table that has it",
  };
  const pyPriced = JSON.parse(unb64(at('the committed corpus, priced by the SHIPPED table').json));
  const ndPriced = JSON.parse(
    tokenledger.asJson(tokenledger.read(CORPUS, { model: 'a-model', prices: SHIPPED })),
  );
  cases.push(
    ...literalCases(
      pyPriced.cost,
      ndPriced.cost,
      'the shipped price table answers the refusal, for every model',
      REFUSAL,
    ),
  );

  // #150 and #151 as LITERALS, per side: both are absolute properties, and a differential is
  // blind to the same regression landing in both runtimes (tolerating the BOM on both sides,
  // or following the loop on both, would agree perfectly).
  const countsOf = (doc) => ({
    transcripts: doc.transcripts,
    lines: doc.lines,
    requests: doc.requests,
    omissions: doc.omissions.map((o) => [o.subject, o.count, o.what]),
  });
  const ndRead = (root) => JSON.parse(tokenledger.asJson(tokenledger.read(root)));
  cases.push(
    ...literalCases(
      countsOf(JSON.parse(unb64(at('a BOM before the first record (#150)').json))),
      countsOf(ndRead(bomBed)),
      'a leading BOM is one unparsed line on both sides (#150)',
      { transcripts: 1, lines: 2, requests: 1, omissions: [['unparsed-line', 1, '-p/s.jsonl:1']] },
    ),
  );
  if (loopBuilt) {
    cases.push(
      ...literalCases(
        countsOf(JSON.parse(unb64(at('a directory symlink loop and a file symlink (#151)').json))),
        countsOf(ndRead(loopBed)),
        'a directory symlink is not followed, a file symlink is read (#151)',
        { transcripts: 2, lines: 2, requests: 1, omissions: [['duplicate-request', 1, '-p/s.jsonl:1']] },
      ),
    );
  }

  // ------------------------------------------------------------------ J88-1 (#316 G2)
  //
  // Line shapes and roots the corpus above never reached, compared as `as_json()` CODE UNITS
  // (base64 of UTF-8 cannot carry a lone surrogate) with ANY exception reported by its type, so
  // an input that makes one side raise something the MCP handler does not catch is a red case
  // and not a dead harness. The agreeing beds come first; the inputs on which the hand-written
  // runtimes disagreed follow (J88-1F ruled each as Node; J88-2's generation closed them, so each
  // is an ordinary agreeing case now, `(G2: was ruled as Node)`). Each keeps its companion (the
  // refusal bit where one side used to refuse), and the counts are pinned PER SIDE as literals:
  // both sides now run one source, so only a literal can see a change to tokenledger.ts.
  const units = (s) => Array.from({ length: s.length }, (_, i) => s.charCodeAt(i));
  const ndUnits = (root) => {
    try {
      return { units: units(tokenledger.asJson(tokenledger.read(root))) };
    } catch (err) {
      return { error: { type: err?.constructor?.name ?? 'thrown', units: units(String(err?.message ?? err)) } };
    }
  };
  const REC = (o) => JSON.stringify({ type: 'assistant', sessionId: 's', requestId: 'q', message: { usage: usage({ input_tokens: 1 }) }, ...o });
  const g2 = join(bed, 'j88');
  const bedOf = (nameOf, body) => {
    write(`j88/${nameOf}/a.jsonl`, body);
    return join(g2, nameOf);
  };
  const AGREE = [
    ['a U+0085 (NEL) between two records is not a line break', bedOf('nel', `${REC({ requestId: 'q1' })}\u0085${REC({ requestId: 'q2' })}\n`)],
    ['a U+2028 after a record is not a line break', bedOf('ls', `${REC({ requestId: 'q1' })}\u2028\n${REC({ requestId: 'q2' })}\n`)],
    ['a form feed after a record is not JSON whitespace', bedOf('ff', `${REC({ requestId: 'q1' })}\f\n`)],
    ['counts spelled 7.0, -0, 1e2 and 0.0e0 are counts', bedOf('spelled', '{"type":"assistant","sessionId":"s","requestId":"q","message":{"usage":{"input_tokens":7.0,"cache_creation_input_tokens":-0,"cache_read_input_tokens":1e2,"output_tokens":0.0e0}}}\n')],
    ['true, 7.5, -1, "1", 1e400 and 2**53+1 are not counts', bedOf('notcounts', [
      ['true', 'q1'], ['7.5', 'q2'], ['-1', 'q3'], ['"1"', 'q4'], ['1e400', 'q5'], ['9007199254740993', 'q6'], ['9007199254740991', 'q7'],
    ].map(([v, q]) => `{"type":"assistant","sessionId":"s","requestId":"${q}","message":{"usage":{"input_tokens":${v},"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0}}}`).join('\n') + '\n')],
    ['a __proto__ key on the record and in its message', bedOf('proto', '{"__proto__":{"type":"user"},"type":"assistant","sessionId":"s","requestId":"q","message":{"__proto__":{"usage":null},"usage":{"input_tokens":1,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0}}}\n')],
    ['a duplicate key keeps its last value', bedOf('dupkey', '{"type":"user","type":"assistant","sessionId":"x","sessionId":"s","requestId":"q","message":{"usage":{"input_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0,"input_tokens":2}}}\n')],
    ['isSidechain must be the boolean true', bedOf('sidechain', [`${REC({ requestId: 'q1', isSidechain: 'true' })}`, `${REC({ requestId: 'q2', isSidechain: 1 })}`, `${REC({ requestId: 'q3', isSidechain: true })}`].join('\n') + '\n')],
    // Two stamps only, so `first` and `last` are both decided by the U+FF5A / U+1F600 pair: by code
    // point U+FF5A is first, by UTF-16 unit the astral one (lead surrogate 0xD83D) would be.
    ['timestamps compare by code point (U+FF5A below U+1F600)', bedOf('stamps', [
      REC({ requestId: 'q1', timestamp: '2026-\u{1F600}' }), REC({ requestId: 'q2', timestamp: '2026-\uff5a' }),
    ].join('\n') + '\n')],
    ['an escaped surrogate PAIR in a session id is one astral character', bedOf('pair', `${REC({}).replace('"sessionId":"s"', '"sessionId":"\\ud83d\\ude00"')}\n`)],
    ['a nested object 500 deep is not a record', bedOf('deep500', `${'['.repeat(500)}${']'.repeat(500)}\n${REC({})}\n`)],
  ];
  // A directory named like a transcript is walked, and an upper-case suffix is not read.
  write('j88/shapes/x.jsonl/a.jsonl', `${REC({ requestId: 'q1' })}\n`);
  write('j88/shapes/b.JSONL', `${REC({ requestId: 'q2' })}\n`);
  AGREE.push(['a directory named x.jsonl is walked, b.JSONL is not read', join(g2, 'shapes')]);
  AGREE.push(['a root spelled with a trailing slash', `${join(g2, 'shapes')}/`]);
  AGREE.push(['a root spelled with a doubled slash', join(g2, 'shapes').replace(/\/j88\//, '/j88//')]);

  // [label, root, what the hand-written runtimes did apart before G2]
  const DIVERGE = [
    ['CRLF line endings', bedOf('crlf', `${REC({ requestId: 'q1' })}\r\n\r\n${REC({ requestId: 'q2' })}\r\n`),
      "read_text() is universal-newline text mode, so Python sees `\\r\\n` as `\\n` and the blank `\\r\\n` line as empty (lines 2); Node splits on `\\n` alone and counts the lone `\\r` as an unparsed line (lines 3)"],
    ['a lone CR between two records', bedOf('cr', `${REC({ requestId: 'q1' })}\r${REC({ requestId: 'q2' })}\n`),
      'universal newlines make the lone `\\r` a line break on Python (2 requests); Node reads one unparsed line (0 requests)'],
    ['a line nested 100000 deep', bedOf('deep', `${'['.repeat(100000)}${']'.repeat(100000)}\n${REC({})}\n`),
      "Python's json.loads raises RecursionError, which read() does not catch (nor does the MCP handler, which catches TokenLedgerError, PriceTableError and OSError); JSON.parse reads an array and Node counts a not-an-object"],
    ['a lone surrogate in a session id and a cwd', bedOf('lone', `${REC({}).replace('"sessionId":"s"', '"sessionId":"\\ud800","cwd":"\\udfff"')}\n`),
      'json.dumps(ensure_ascii=False) writes the lone surrogate RAW into as_json() (a str no UTF-8 encoder accepts); JSON.stringify escapes it as the six characters `\\ud800`'],
    ['a root whose name is longer than NAME_MAX', join(g2, 'x'.repeat(300)),
      "Path.exists() raises OSError(ENAMETOOLONG); existsSync answers false and Node refuses `no such directory: ...` as a TokenLedgerError (both refuse: the companion)"],
  ];
  const canChmod = process.platform !== 'win32' && process.getuid?.() !== 0;
  if (canChmod) {
    // A subdirectory readable but not searchable: its listing works and every stat inside fails.
    write('j88/noexec/sub/a.jsonl', `${REC({})}\n`);
    chmodSync(join(g2, 'noexec', 'sub'), 0o644);
    DIVERGE.push(['a subdirectory that can be listed but not searched', join(g2, 'noexec'),
      "Path.is_dir() raises PermissionError(EACCES) out of _walk and read() raises it; statSync's throw is caught, the child is taken for a file and Node counts one undecodable-file"]);
  } else notes.push('J88-1: the EACCES subdirectory bed is not built on this host (Windows or root)');

  let pyUnits;
  let ndAll;
  try {
    pyUnits = ctx.runPython(REF, { op: 'read_units', roots: [...AGREE, ...DIVERGE].map(([, r]) => r) }).out;
    ndAll = [...AGREE, ...DIVERGE].map(([, r]) => ndUnits(r));
  } finally {
    // Searchable again, so the harness can remove its scratch directory.
    if (canChmod) chmodSync(join(g2, 'noexec', 'sub'), 0o755);
  }
  AGREE.forEach(([label], i) => {
    cases.push({ name: `J88-1 read: ${label}`, kind: 'json', expected: pyUnits[i], actual: ndAll[i] });
  });
  const refuses = (v) => 'error' in v;
  const FAMILY = {
    'CRLF line endings': 'CR and CRLF line ends',
    'a lone CR between two records': 'CR and CRLF line ends',
    'a line nested 100000 deep': 'a line nested 100000 deep',
    'a lone surrogate in a session id and a cwd': 'lone surrogates',
    'a root whose name is longer than NAME_MAX': 'a root past NAME_MAX',
    'a subdirectory that can be listed but not searched': 'an unsearchable subdirectory',
  };
  DIVERGE.forEach(([label], j) => {
    const i = AGREE.length + j;
    cases.push({ name: `J88-1 read: ${label} (G2: was ruled as Node, "${FAMILY[label]}")`, kind: 'json', expected: pyUnits[i], actual: ndAll[i] });
  });
  // Companions: for each divergent input, the part the two still agree on.
  const at88 = (label) => AGREE.length + DIVERGE.findIndex(([l]) => l === label);
  const docOf = (v) => JSON.parse(String.fromCharCode(...v.units));
  {
    const i = at88('CRLF line endings');
    cases.push({ name: 'J88-1 read: CRLF line endings — both count the two requests', kind: 'json',
      expected: refuses(pyUnits[i]) ? pyUnits[i] : { requests: docOf(pyUnits[i]).requests, totals: docOf(pyUnits[i]).totals },
      actual: refuses(ndAll[i]) ? ndAll[i] : { requests: docOf(ndAll[i]).requests, totals: docOf(ndAll[i]).totals } });
    const n = at88('a root whose name is longer than NAME_MAX');
    cases.push({ name: 'J88-1 read: a root longer than NAME_MAX — both refuse', kind: 'json', expected: refuses(pyUnits[n]), actual: refuses(ndAll[n]) });
    const l = at88('a lone surrogate in a session id and a cwd');
    const counts = (v) => (refuses(v) ? v : (({ units: u }) => {
      const t = String.fromCharCode(...u);
      return { requests: /"requests": (\d+)/.exec(t)?.[1], sessions: (t.match(/"session":/g) ?? []).length };
    })(v));
    cases.push({ name: 'J88-1 read: a lone surrogate session id — both count one request in one session', kind: 'json', expected: counts(pyUnits[l]), actual: counts(ndAll[l]) });
  }
  // Literals per side for two agreeing beds a symmetric edit could move.
  const countsOf88 = (v) => (refuses(v) ? v : (({ lines, requests, totals, omissions }) => ({ lines, requests, input_tokens: totals.input_tokens, omissions: omissions.map((o) => [o.subject, o.count]) }))(docOf(v)));
  const spelled = AGREE.findIndex(([l]) => l.startsWith('counts spelled'));
  const notCounts = AGREE.findIndex(([l]) => l.startsWith('true, 7.5'));
  cases.push(
    ...literalCases(countsOf88(pyUnits[spelled]), countsOf88(ndAll[spelled]), 'J88-1: 7.0, -0, 1e2 and 0.0e0 count as 7, 0, 100, 0',
      { lines: 1, requests: 1, input_tokens: 7, omissions: [] }),
    ...literalCases(countsOf88(pyUnits[notCounts]), countsOf88(ndAll[notCounts]), 'J88-1: only 2**53-1 of the seven spellings is a count',
      { lines: 7, requests: 1, input_tokens: 9007199254740991, omissions: [['malformed-usage', 6]] }),
  );
  // The answer over each input J88-1F ruled as Node, which J88-2's generation made Python's too.
  {
    const nodeView = (v) => (refuses(v) ? { refuses: v.error.type } : countsOf88(v));
    const want = {
      // `\n` alone ends a line: the blank `\r` between the two records is one unparsed line.
      'CRLF line endings': { lines: 3, requests: 2, input_tokens: 2, omissions: [['unparsed-line', 1]] },
      'a lone CR between two records': { lines: 1, requests: 0, input_tokens: 0, omissions: [['unparsed-line', 1]] },
      // JSON.parse reads the deep array; it is a line that is not an object, never a raise.
      'a line nested 100000 deep': { lines: 2, requests: 1, input_tokens: 1, omissions: [['not-an-object', 1]] },
      'a lone surrogate in a session id and a cwd': { lines: 1, requests: 1, input_tokens: 1, omissions: [] },
      'a root whose name is longer than NAME_MAX': { refuses: 'TokenLedgerError' },
      'a subdirectory that can be listed but not searched': { lines: 1, requests: 0, input_tokens: 0, omissions: [['undecodable-file', 1]] },
    };
    const labels = DIVERGE.map(([l]) => l);
    cases.push(
      ...literalCases(
        labels.map((l) => [l, nodeView(pyUnits[at88(l)])]),
        labels.map((l) => [l, nodeView(ndAll[at88(l)])]),
        'G2 counts over the inputs J88-1F ruled as Node',
        labels.map((l) => [l, want[l]]),
      ),
    );
  }

  notes.push(
    `corpus: ${CORPUS_HEADLINE.transcripts} transcripts, ${CORPUS_HEADLINE.lines} lines, ` +
      `${CORPUS_HEADLINE.requests} requests, ${CORPUS_HEADLINE.omitted} omitted, ` +
      `${CORPUS_HEADLINE.sessions} sessions — frozen in git, never ~/.claude`,
  );
  notes.push(
    `cost over the shipped table: ${Object.keys(ndPriced.cost)[0]} — the refusal is the default answer`,
  );

  return { cases, notes };
}
