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
import { mkdirSync, writeFileSync } from 'node:fs';
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
