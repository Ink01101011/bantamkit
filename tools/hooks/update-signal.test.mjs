/**
 * The stale-install signal: the SessionStart line, the detached probe, and the 24 h TTL.
 *
 *   node --test 'tools/hooks/*.test.mjs'
 *
 * THE QUOTED GLOB, NOT `node --test tools/hooks/`. On Node 25.2.1 a positional argument is
 * resolved as a module rather than walked as a directory, so the bare-directory form dies with
 * `Cannot find module …/tools/hooks` before any test runs — and it does the same for
 * `tools/ledger`, which predates this file, so it is the runner's spelling that changed and not
 * anything here. The glob form runs the same files on every version.
 *
 * WHAT THESE PIN, and why every one of them drives a real process rather than a function.
 * `tools/hooks/bantamkit-hook.mjs` shipped a PreCompact arm that no test had ever RUN, and the
 * host rejected every one of its outputs for a year (see `runtime-ts/test/hooks.test.mjs`). So
 * the line here is judged the way the host judges it — JSON on stdin, `additionalContext` off
 * stdout — and the probe is judged by the bytes it leaves on disk, not by reading its source.
 *
 * NOTHING HERE TOUCHES THE OPERATOR'S HOME, AND THAT IS ENFORCED RATHER THAN INTENDED. Every
 * path in both programs hangs off `os.homedir()`, which reads `HOME` / `USERPROFILE` on every
 * call, so a test that forgot to redirect them would write a fabricated update record into the
 * operator's own `~/.bantamkit/` — which is not hypothetical: J57-3 found exactly that in the
 * conformance harness on this job and had to delete a bogus record off this machine. `run()`
 * and `probe()` below are the ONLY two ways this file starts either program, and both assert
 * the redirection before they spawn anything.
 *
 * NOTHING HERE REACHES A REAL REGISTRY EITHER. Both registry URLs are seams, and the default
 * for every run below is `127.0.0.1:1` — a refused connection, immediately — so a test that
 * means to exercise the network has to say so by pointing at the local server this file starts.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import {
  existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync,
} from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const HOOK = join(HERE, 'bantamkit-hook.mjs');
const PROBE = join(HERE, 'update-probe.mjs');
const PACKAGE = 'bantamkit-mcp';

/** A port nothing listens on: every connect is refused at once. The default for every run. */
const REFUSED = 'http://127.0.0.1:1/';

/**
 * RFC 5737 TEST-NET-1. Routed to the default gateway and dropped there, so a connect HANGS
 * until the timeout instead of failing fast — which is the only way to time a probe that is
 * genuinely still working against a hook that has already returned. A refused port would make
 * the detachment test pass even if the spawn were synchronous.
 */
const BLACKHOLE = 'http://192.0.2.1:8080/';

// `realpathSync` because the hook resolves its own HOME through `realpathSync.native` (J47-7),
// and on macOS `mkdtemp` hands back `/var/...` for a directory the kernel calls `/private/var/
// ...`. Without this the paths the hook PRINTS would not equal the paths this file builds.
const scratch = realpathSync(mkdtempSync(join(tmpdir(), 'bk-update-')));
after(() => rmSync(scratch, { recursive: true, force: true }));

let counter = 0;

/** A scratch HOME. Asserts it is not the operator's, because that is the whole risk here. */
function newHome({ bantamkit = true } = {}) {
  const home = join(scratch, `home-${counter++}`);
  mkdirSync(home, { recursive: true });
  assert.notEqual(home, homedir(), 'the scratch HOME must not be the operator home');
  if (bantamkit) mkdirSync(join(home, '.bantamkit'), { recursive: true });
  return home;
}

function newCwd() {
  const cwd = join(scratch, `cwd-${counter++}`);
  mkdirSync(cwd, { recursive: true });
  return cwd;
}

const recordFile = (home) => join(home, '.bantamkit', 'update-check.json');
const manifestFile = (home) => join(home, '.bantamkit', 'mcp', 'node_modules', PACKAGE, 'package.json');

function writeRecord(home, doc) {
  const file = recordFile(home);
  writeFileSync(file, typeof doc === 'string' ? doc : `${JSON.stringify(doc, null, 2)}\n`);
  return file;
}

/** The kept install the hook compares: `<home>/.bantamkit/mcp/node_modules/<pkg>/package.json`. */
function installKept(home, version) {
  const file = manifestFile(home);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify({ name: PACKAGE, version }, null, 2)}\n`);
  return file;
}

function stamp(msAgo) {
  return new Date(Date.now() - msAgo).toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/** A record naming `latest` on both registries, written `msAgo` milliseconds ago. */
function record(latest, msAgo) {
  return {
    checked_at: stamp(msAgo),
    npm: { package: PACKAGE, latest },
    pypi: { distribution: 'bantamkit', latest },
  };
}

/**
 * The environment BOTH programs run under. Assembled in one place so the two redirections and
 * the two URL seams cannot be set for one spawn and forgotten for another.
 */
function environment(home, extra) {
  const env = {
    ...process.env,
    HOME: home,
    USERPROFILE: home,
    BANTAMKIT_UPDATE_NPM_URL: REFUSED,
    BANTAMKIT_UPDATE_PYPI_URL: REFUSED,
    ...extra,
  };
  assert.equal(env.HOME, home, 'HOME must point at the scratch home');
  assert.equal(env.USERPROFILE, home, 'USERPROFILE must point at the scratch home (Windows)');
  assert.notEqual(env.HOME, homedir(), 'HOME must not be the operator home');
  return env;
}

/**
 * Start a program, feed it `input`, and resolve with what it did. NEVER `spawnSync`.
 *
 * THAT IS NOT A STYLE CHOICE. The fake registry below runs on THIS process's event loop, and a
 * `spawnSync` here blocks it — so a probe spawned by the hook could not be served, and timed
 * out against a server that was listening the whole time. Measured: every fetch took the full
 * 10038 ms. Everything that waits in this file waits asynchronously for that reason.
 */
function launch(program, args, { input, env } = {}) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const child = spawn(program, args, { env, stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (d) => { stdout += d; });
    child.stderr.on('data', (d) => { stderr += d; });
    child.on('error', reject);
    // `close` waits for the pipes as well as the exit — and a DETACHED grandchild holds
    // neither, because it is given `stdio: 'ignore'`. So `elapsed` is the hook's own time, not
    // its child's, which is exactly the number the detachment test judges.
    child.on('close', (status) => {
      resolve({ status, stdout, stderr, elapsed: Date.now() - started });
    });
    if (input !== undefined) child.stdin.end(input);
    else child.stdin.end();
  });
}

/** Run the hook the way the host does: JSON on stdin, judge exit code and stdout. */
async function run(payload, { home = newHome(), cwd = newCwd(), env } = {}) {
  const r = await launch(process.execPath, [HOOK], {
    input: JSON.stringify({ cwd, session_id: `probe-${counter++}`, ...payload }),
    env: environment(home, env),
  });
  return { ...r, home, cwd };
}

/** One SessionStart, with its injected context parsed out and its log line in hand. */
async function sessionStart(options = {}) {
  const r = await run({ hook_event_name: 'SessionStart', source: 'startup' }, options);
  assert.equal(r.status, 0, `exit ${r.status}; stderr: ${r.stderr}`);
  assert.equal(r.stderr, '', 'a hook that writes to stderr is rendered as an error');
  const out = JSON.parse(r.stdout);
  return { ...r, ctx: out.hookSpecificOutput.additionalContext, log: lastLog(r.home, 'SessionStart') };
}

function lastLog(home, event) {
  const file = join(home, '.bantamkit', 'hooks', 'hook-log.jsonl');
  const lines = readFileSync(file, 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  const hit = lines.filter((l) => l.event === event && 'updateProbe' in l);
  assert.ok(hit.length > 0, `no ${event} log line carrying updateProbe in ${file}`);
  return hit[hit.length - 1];
}

/** Run the probe directly and WAIT for it — the one context in which waiting is correct. */
async function probe(home, extra) {
  const r = await launch(process.execPath, [PROBE], { env: environment(home, extra) });
  assert.equal(r.status, 0, `probe exit ${r.status}`);
  assert.equal(r.stdout, '', 'the probe must never write to stdout');
  assert.equal(r.stderr, '', 'the probe must never write to stderr');
  return r;
}

const sleep = (ms) => new Promise((done) => { setTimeout(done, ms); });

/** Poll until `fn()` is truthy or the budget runs out. Returns what it saw, or `null`. */
async function waitFor(fn, budgetMs = 15000) {
  const deadline = Date.now() + budgetMs;
  for (;;) {
    let seen = null;
    try { seen = fn(); } catch { seen = null; }
    if (seen) return seen;
    if (Date.now() > deadline) return null;
    await sleep(50);
  }
}

// ---- a registry that answers instantly, so "the probe writes" is not a network test --------

let origin = '';
let npmHits = 0;
let pypiHits = 0;
const SERVED = '9.9.9';
let server;

before(async () => {
  server = createServer((req, res) => {
    if (req.url.startsWith('/npm')) {
      npmHits += 1;
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ name: PACKAGE, version: SERVED }));
      return;
    }
    if (req.url.startsWith('/pypi')) {
      pypiHits += 1;
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ info: { name: 'bantamkit', version: SERVED } }));
      return;
    }
    res.writeHead(404).end('{}');
  });
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  origin = `http://127.0.0.1:${server.address().port}`;
});
after(() => server && server.close());

const served = () => ({
  BANTAMKIT_UPDATE_NPM_URL: `${origin}/npm`,
  BANTAMKIT_UPDATE_PYPI_URL: `${origin}/pypi`,
});

// ---------------------------------------------------------------- the line, five states ----

/** The sentence, spelled here independently of the constant so a silent edit to it goes red. */
function expectedLine(home, installed, latest) {
  return `[bantamkit] ${PACKAGE} ${installed} at ${manifestFile(home)} is running; `
    + `the package index has ${latest} — run \`${PACKAGE} --update\`, then reconnect the host.`;
}

test('the stale state produces exactly one line, and it names the install it compared', async () => {
  const home = newHome();
  installKept(home, '0.35.1');
  writeRecord(home, record('0.36.0', 60_000));

  const r = await sessionStart({ home });
  const want = expectedLine(home, '0.35.1', '0.36.0');
  const occurrences = r.ctx.split(want).length - 1;
  assert.equal(occurrences, 1, `expected exactly one:\n  ${want}\ngot context:\n${r.ctx}`);
  assert.equal(r.log.updateState, 'available');
  assert.equal(r.log.updateBytes, Buffer.byteLength(want));
  // Last, so the one conditional line is the last thing the agent reads.
  assert.ok(r.ctx.endsWith(want), 'the update line must be the final part of the block');
});

for (const [name, setup, state] of [
  ['never', (home) => { installKept(home, '0.35.1'); }, 'never'],
  ['current', (home) => { installKept(home, '0.35.1'); writeRecord(home, record('0.35.1', 60_000)); }, 'current'],
  ['ahead', (home) => { installKept(home, '0.36.0'); writeRecord(home, record('0.35.1', 60_000)); }, 'ahead'],
  ['unreadable', (home) => { installKept(home, '0.35.1'); writeRecord(home, 'not json at all'); }, 'unreadable'],
]) {
  test(`the ${name} state produces no line`, async () => {
    const home = newHome();
    setup(home);
    const r = await sessionStart({ home });
    assert.equal(r.log.updateState, state);
    assert.equal(r.log.updateBytes, 0, `the ${name} state injected bytes`);
    assert.ok(!r.ctx.includes('the package index has'), `the ${name} state injected a line:\n${r.ctx}`);
    // The rest of the block is untouched by all of this.
    assert.ok(r.ctx.includes('[bantamkit] Toolbox is live'), 'the standing toolbox line is gone');
  });
}

test('an absent kept install produces no line, however stale the record is', async () => {
  const home = newHome();
  writeRecord(home, record('99.0.0', 60_000));
  assert.ok(!existsSync(manifestFile(home)), 'the bed must have no kept install');

  const r = await sessionStart({ home });
  assert.equal(r.log.updateState, null, 'with nothing to compare there is no state');
  assert.equal(r.log.updateBytes, 0);
  assert.ok(!r.ctx.includes('the package index has'), `injected a line with no install:\n${r.ctx}`);
});

// ------------------------------------------------------------------------ the probe --------

test('the probe writes the record both readers expect, byte for byte', async () => {
  const home = newHome();
  await probe(home, served());

  const bytes = readFileSync(recordFile(home), 'utf8');
  assert.ok(bytes.endsWith('\n'), 'the record ends in exactly one newline');
  const parsed = JSON.parse(bytes);
  // AMENDED 2026-09-21 (job62, J62-13): each entry carries its own `checked_at` — when THAT
  // registry answered. The record's own stamp survives and means "a writer refreshed the
  // record as a whole", which both registries answering is.
  assert.deepEqual(parsed.npm, { package: PACKAGE, latest: SERVED, checked_at: parsed.npm.checked_at });
  assert.deepEqual(parsed.pypi, { distribution: 'bantamkit', latest: SERVED, checked_at: parsed.pypi.checked_at });
  assert.match(parsed.npm.checked_at, STAMP_SHAPE);
  assert.match(parsed.pypi.checked_at, STAMP_SHAPE);
  assert.match(parsed.checked_at, STAMP_SHAPE, 'the `--update` writer\'s stamp');
  // The serialization `selfupdate.recordUpdate` pins: `JSON.stringify(payload, null, 2)` + "\n".
  assert.equal(bytes, `${JSON.stringify(parsed, null, 2)}\n`);
  assert.ok(npmHits > 0 && pypiHits > 0, 'both registries were asked');
});

/** `YYYY-MM-DDTHH:MM:SSZ` — `selfupdate.STAMP` on both sides. */
const STAMP_SHAPE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

// ---- ONE registry answers and the other does not (J62-13) -----------------------------
//
// THE SHAPE NOTHING HERE COVERED. Until this unit every probe test drove both registries the
// same way — both answering or both failing — so the partial success, which is the ordinary
// case on a network that blocks one host, was never run. What it did: stamp the RECORD's
// `checked_at`, the fallback dating every entry without one of its own. So the runtime
// reading the half that did NOT answer said `is current as of <today>` about a number weeks
// old, and the 24 h TTL below went quiet for the whole interval instead of retrying.
//
// Both arms are asserted in BOTH directions — npm answering and pypi answering — because a
// writer that stamped only the key it happens to be asked for first would pass one of them.

for (const [answered, failed] of [['npm', 'pypi'], ['pypi', 'npm']]) {
  test(`only ${answered} answers: its entry is stamped, ${failed}'s and the record's are not`, async () => {
    const home = newHome();
    const seeded = record('0.30.0', 25 * 3600_000);   // 25 h old: outside the TTL, and not `now`
    writeRecord(home, seeded);

    await probe(home, {
      ...served(),
      [`BANTAMKIT_UPDATE_${failed.toUpperCase()}_URL`]: REFUSED,
    });

    const parsed = JSON.parse(readFileSync(recordFile(home), 'utf8'));
    assert.equal(parsed[answered].latest, SERVED, `${answered} answered and was not recorded`);
    assert.match(parsed[answered].checked_at, STAMP_SHAPE, `${answered} was not stamped`);
    // THE ENTRY THAT DID NOT ANSWER IS UNTOUCHED — version AND the absence of a stamp, so it
    // keeps falling back to the record's, which is when it was actually last confirmed.
    assert.deepEqual(parsed[failed], seeded[failed], `${failed} was rewritten`);
    // AND THE RECORD'S OWN STAMP DID NOT MOVE. This is the assertion the whole unit exists
    // for: a partial success is not a check of the record as a whole.
    assert.equal(parsed.checked_at, seeded.checked_at, 'a partial probe moved the record stamp');
  });
}

test('a partial probe leaves the record DUE, so the next session retries the half that failed', async () => {
  // The consequence of the assertion above, judged where an operator would see it: the hook's
  // 24 h TTL reads exactly that field. Before J62-13 this reported `fresh` and the failed half
  // waited a full day; a machine running `--update` more often than daily waited forever.
  const home = newHome();
  installKept(home, '0.35.1');
  writeRecord(home, record('0.30.0', 25 * 3600_000));

  await probe(home, { ...served(), BANTAMKIT_UPDATE_PYPI_URL: REFUSED });

  const after = await sessionStart({ home, env: { ...served(), BANTAMKIT_UPDATE_PYPI_URL: REFUSED } });
  assert.equal(after.log.updateProbe, 'spawned', 'the record was treated as fresh after a partial probe');
});

test('the probe keeps what it did not fetch and leaves no temp file behind', async () => {
  const home = newHome();
  writeRecord(home, { ...record('0.1.0', 0), extra: { kept: true } });

  await probe(home, served());

  const parsed = JSON.parse(readFileSync(recordFile(home), 'utf8'));
  assert.deepEqual(parsed.extra, { kept: true }, 'an unrelated key was dropped');
  assert.equal(parsed.npm.latest, SERVED);
  const leftovers = readdirSync(join(home, '.bantamkit')).filter((n) => n.startsWith('.update-check-'));
  assert.deepEqual(leftovers, [], 'a temp file survived the write');
});

test('the probe leaves the previous record byte-identical when both registries fail', async () => {
  const home = newHome();
  // 25 h OLD, NOT `now`. With a fresh stamp this assertion cannot fail: a probe that wrongly
  // rewrote the record would land on the same `checked_at` second and produce the same bytes.
  // Measured — the mutation "write even when both registries failed" passed this test GREEN
  // until the age was moved off zero.
  const before = `${JSON.stringify(record('0.30.0', 25 * 3600_000), null, 2)}\n`;
  writeFileSync(recordFile(home), before);

  await probe(home, {
    BANTAMKIT_UPDATE_NPM_URL: BLACKHOLE,
    BANTAMKIT_UPDATE_PYPI_URL: BLACKHOLE,
    BANTAMKIT_UPDATE_TIMEOUT_MS: '300',
  });

  assert.equal(readFileSync(recordFile(home), 'utf8'), before, 'a failed probe rewrote the record');
  const leftovers = readdirSync(join(home, '.bantamkit')).filter((n) => n.startsWith('.update-check-'));
  assert.deepEqual(leftovers, [], 'a failed probe left a temp file');
});

test('the probe creates neither the directory nor the file when ~/.bantamkit is absent', async () => {
  const home = newHome({ bantamkit: false });
  await probe(home, served());
  assert.ok(!existsSync(join(home, '.bantamkit')), 'the probe created the toolbox directory');
  assert.deepEqual(readdirSync(home), [], 'the probe created something in an empty home');
});

// -------------------------------------------------------------------------- the TTL --------

test('the TTL suppresses a second run inside 24 h and allows one after', async () => {
  const fresh = newHome();
  const stale = newHome();
  installKept(fresh, '0.35.1');
  installKept(stale, '0.35.1');
  // 23 h old: inside the window. 25 h old: outside it. Same record otherwise.
  writeRecord(fresh, record('0.35.1', 23 * 3600_000));
  const before = readFileSync(recordFile(fresh), 'utf8');
  writeRecord(stale, record('0.35.1', 25 * 3600_000));

  const a = await sessionStart({ home: fresh, env: served() });
  assert.equal(a.log.updateProbe, 'fresh', 'a 23 h old record must not be re-probed');
  await sleep(400);
  assert.equal(readFileSync(recordFile(fresh), 'utf8'), before, 'a suppressed probe still wrote');

  const b = await sessionStart({ home: stale, env: served() });
  assert.equal(b.log.updateProbe, 'spawned', 'a 25 h old record must be re-probed');
  const written = await waitFor(() => {
    const parsed = JSON.parse(readFileSync(recordFile(stale), 'utf8'));
    return parsed.npm.latest === SERVED ? parsed : null;
  });
  assert.ok(written, 'the spawned probe never wrote the record');
});

test('a record with no usable checked_at is treated as due, not as fresh', async () => {
  const home = newHome();
  installKept(home, '0.35.1');
  writeRecord(home, { npm: { package: PACKAGE, latest: '0.35.1' }, checked_at: 'whenever' });
  const r = await sessionStart({ home });
  assert.equal(r.log.updateProbe, 'spawned');
});

// ------------------------------------------------------------------ the spawn is detached ---

test('SessionStart returns without waiting for the probe it spawned', async () => {
  const home = newHome();
  installKept(home, '0.35.1');
  // No record at all: the TTL cannot suppress, so a probe IS spawned on this run. Both URLs
  // point into the black hole with the REAL 10 s timeout — no timeout seam here on purpose, so
  // a hook that waited would have to wait the full bound.
  const r = await sessionStart({ home, env: { BANTAMKIT_UPDATE_NPM_URL: BLACKHOLE, BANTAMKIT_UPDATE_PYPI_URL: BLACKHOLE } });

  assert.equal(r.log.updateProbe, 'spawned', 'nothing was spawned, so nothing was detached');
  console.log(`      measured: SessionStart returned in ${r.elapsed} ms against a 10000 ms probe`);
  assert.ok(r.elapsed < 3000, `SessionStart took ${r.elapsed} ms — it waited on the network`);
  // And the probe really was still working: it cannot have finished against the black hole in
  // the time the hook took, so the record it would have written is still absent.
  assert.ok(!existsSync(recordFile(home)), 'the probe finished before the hook returned');
});

test('the black hole really hangs, so the timing above measures detachment', async () => {
  // THE CONTROL. Without this, the test above would pass just as well against an address that
  // fails instantly, which is the shape that would hide a synchronous spawn.
  const home = newHome();
  const started = Date.now();
  const child = spawn(process.execPath, [PROBE], {
    stdio: 'ignore',
    env: environment(home, {
      BANTAMKIT_UPDATE_NPM_URL: BLACKHOLE,
      BANTAMKIT_UPDATE_PYPI_URL: BLACKHOLE,
      BANTAMKIT_UPDATE_TIMEOUT_MS: '2000',
    }),
  });
  const code = await waitFor(() => (child.exitCode === null ? null : { code: child.exitCode }), 20000);
  const elapsed = Date.now() - started;
  console.log(`      measured: a probe against ${BLACKHOLE} took ${elapsed} ms to give up`);
  assert.ok(code, 'the control probe never exited');
  assert.ok(elapsed > 1500, `the black hole answered in ${elapsed} ms — it is not black-holed`);
  assert.ok(!existsSync(recordFile(home)), 'the control probe wrote a record');
});

// ------------------------------------------------------------------- nothing cwd-relative ---

test('no .bantamkit is ever created relative to the cwd', async () => {
  const home = newHome();
  const cwd = newCwd();
  installKept(home, '0.35.1');
  writeRecord(home, record('0.36.0', 60_000));

  const r = await sessionStart({ home, cwd });
  assert.ok(r.ctx.includes('the package index has'), 'the bed did not reach the stale state');
  assert.ok(!existsSync(join(cwd, '.bantamkit')), 'a cwd-relative .bantamkit was created');
  assert.deepEqual(readdirSync(cwd), [], 'the hook wrote into the cwd');
});
