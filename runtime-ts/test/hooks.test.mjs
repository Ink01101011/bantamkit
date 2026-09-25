/**
 * The hook adapter's PreCompact arm: the CHANNEL, and the checkpoint it steers from.
 *
 * WHY THIS FILE EXISTS. `tools/hooks/bantamkit-hook.mjs` shipped a PreCompact arm at
 * b3625d9 that emitted `{hookSpecificOutput:{hookEventName:"PreCompact", …}}`. The host has
 * no `"PreCompact"` member in that discriminated union, so every real compaction answered
 * `Hook JSON output validation failed`, the result was marked not-succeeded, and the
 * steering text was dropped. Nothing caught it, because nothing had ever RUN the hook — the
 * arm was only ever read. So the tests here are process-level on purpose: they feed the
 * adapter a real PreCompact payload on stdin and judge its stdout the way the host does.
 *
 * THE ORACLE IS THE HOST BINARY, not this file's opinion. Both facts below were extracted
 * from `~/.local/share/claude/versions/2.1.259`:
 *
 *   1. the dispatcher `fK` builds the summariser's instructions as
 *      `newCustomInstructions: C.length>0 ? C.join("\n\n") : undefined` where
 *      `C = results.filter(r => r.succeeded && !r.blocked && r.output.trim().length>0)
 *                  .map(r => r.output.trim())` — i.e. the hook's own trimmed STDOUT;
 *   2. `HOOK_EVENT_UNION` below is every `hookEventName:x("…")` literal in that build.
 *      `"PreCompact"` is absent, which is exactly the bug.
 *
 * Re-derive both with:
 *   strings -a <binary> | grep -oE 'hookEventName:[a-zA-Z_$]+\("[A-Za-z]+"\)' | sort -u
 *   strings -a <binary> | awk '/function fK\(e,n,r,o,f=Td\)/{...}'
 *
 * NOTHING HERE TOUCHES THE REAL HOME OR THE REAL REPO. Every run gets a scratch HOME (so
 * the hook's ledger and log land in the scratch) and a scratch cwd holding its own
 * `.shiftwork`, so the assertions do not move when a real job clocks a unit in or out.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, utimesSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(packageRoot);
const HOOK = process.env.BANTAMKIT_HOOK_PATH || join(repoRoot, 'tools', 'hooks', 'bantamkit-hook.mjs');

/** Every `hookSpecificOutput.hookEventName` the host 2.1.259 accepts. No "PreCompact". */
const HOOK_EVENT_UNION = new Set([
  'CwdChanged', 'Elicitation', 'ElicitationResult', 'FileChanged', 'MessageDisplay',
  'Notification', 'PermissionDenied', 'PermissionRequest', 'PostModelSwitch',
  'PostToolBatch', 'PostToolUse', 'PostToolUseFailure', 'PreModelSwitch', 'PreToolUse',
  'SessionStart', 'Setup', 'Stop', 'SubagentStart', 'SubagentStop', 'UserPromptExpansion',
  'UserPromptSubmit', 'WorktreeCreate',
]);

const scratch = mkdtempSync(join(tmpdir(), 'bk-hooks-'));
after(() => rmSync(scratch, { recursive: true, force: true }));

let n = 0;
function newHome() {
  const home = join(scratch, `home-${n++}`);
  mkdirSync(home, { recursive: true });
  return home;
}
function newCwd() {
  const cwd = join(scratch, `cwd-${n++}`);
  mkdirSync(cwd, { recursive: true });
  return cwd;
}

/** A checkpoint shaped like `assets/schemas/shiftwork-checkpoint.json` requires. */
function checkpoint(cursor, units) {
  return {
    version: 1,
    job: { id: 'probe', goal: 'g', done_definition: 'd' },
    plan: {
      cursor,
      units: units.map((u) => ({
        id: u.id,
        title: u.title ?? `title of ${u.id}`,
        brief_path: `.shiftwork/briefs/${u.id}.md`,
        status: u.status,
        role: 'implementer',
        depends_on: [],
        verify: 'v',
      })),
    },
    state: {},
    history: [],
    retro: [],
    handoff: {},
  };
}

function writeCheckpoint(cwd, name, doc, mtimeSeconds) {
  const dir = join(cwd, '.shiftwork');
  mkdirSync(dir, { recursive: true });
  const file = join(dir, name);
  writeFileSync(file, typeof doc === 'string' ? doc : JSON.stringify(doc, null, 2));
  if (mtimeSeconds != null) utimesSync(file, mtimeSeconds, mtimeSeconds);
  return file;
}

/** Run the adapter the way the host does: JSON on stdin, judge exit code and stdout. */
function runHook(payload, { home = newHome(), cwd = newCwd(), env = {} } = {}) {
  const r = spawnSync(process.execPath, [HOOK], {
    input: JSON.stringify({ cwd, session_id: 'probe-session', ...payload }),
    encoding: 'utf8',
    env: { ...process.env, HOME: home, USERPROFILE: home, ...env },
  });
  return { ...r, cwd, home };
}

function preCompact(opts = {}) {
  return runHook(
    {
      hook_event_name: 'PreCompact',
      trigger: 'manual',
      transcript_path: join(scratch, 'transcript.jsonl'),
      custom_instructions: null,
      ...opts.payload,
    },
    opts,
  );
}

/**
 * The host's own acceptance rule, applied to a hook's stdout: output that does not start
 * with `{` is plain text and always accepted; output that does must parse as a JSON object,
 * and any `hookSpecificOutput.hookEventName` must be a member of the union.
 */
function hostWouldAccept(stdout) {
  const out = stdout.trim();
  if (!out.startsWith('{')) return { accepted: true, why: 'plain text' };
  let doc;
  try { doc = JSON.parse(out); } catch { return { accepted: false, why: 'starts with { but is not JSON' }; }
  if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) return { accepted: false, why: 'not a JSON object' };
  const hso = doc.hookSpecificOutput;
  if (hso && typeof hso === 'object') {
    if (!('hookEventName' in hso)) return { accepted: false, why: 'hookSpecificOutput is missing required field "hookEventName"' };
    if (!HOOK_EVENT_UNION.has(hso.hookEventName)) {
      return { accepted: false, why: `hookSpecificOutput.hookEventName: expected one of ${[...HOOK_EVENT_UNION].join(' | ')}` };
    }
  }
  return { accepted: true, why: 'valid envelope' };
}

// ------------------------------------------------------------------ the channel
test('PreCompact output is accepted by the host, and reaches it as plain stdout', () => {
  const r = preCompact();
  assert.equal(r.status, 0, `exit ${r.status}; stderr: ${r.stderr}`);
  assert.equal(r.stderr, '', 'a hook that writes to stderr is rendered as an error');

  const verdict = hostWouldAccept(r.stdout);
  assert.ok(verdict.accepted, `host would reject this output — ${verdict.why}\noutput was: ${r.stdout}`);

  // `fK` keeps only results whose trimmed stdout is non-empty; an empty one steers nothing.
  assert.ok(r.stdout.trim().length > 0, 'empty stdout is dropped from newCustomInstructions');
  assert.ok(!r.stdout.trim().startsWith('{'), 'PreCompact steering must not be a JSON envelope');
  assert.match(r.stdout, /Preserve verbatim/);
});

test('the rejected envelope is not what we emit — the union is the oracle', () => {
  // Guards the oracle itself: had the arm kept emitting the old shape, this is the message
  // the host printed. The assertion is that `hostWouldAccept` really does reject it.
  const old = JSON.stringify({ hookSpecificOutput: { hookEventName: 'PreCompact', additionalContext: 'x' } });
  const verdict = hostWouldAccept(old);
  assert.equal(verdict.accepted, false);
  assert.match(verdict.why, /expected one of/);
  assert.ok(!HOOK_EVENT_UNION.has('PreCompact'));
});

// ------------------------------------------------------------ the shiftwork line
test('an open checkpoint steers, whatever its filename, and names the cursor unit', () => {
  const cwd = newCwd();
  writeCheckpoint(cwd, 'checkpoint-somejob.json', checkpoint('R5', [
    { id: 'R4', status: 'done' },
    { id: 'R5', status: 'todo', title: 'the unit the cursor points at' },
  ]));
  const r = preCompact({ cwd });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /checkpoint-somejob\.json/, 'a named checkpoint must be found');
  assert.match(r.stdout, /cursor "R5"/, 'the cursor lives at plan.cursor, not at the top level');
  assert.match(r.stdout, /the unit the cursor points at/, 'the line must name the unit, not just the id');
});

test('a stale closed checkpoint.json does not win over the open named one', () => {
  const cwd = newCwd();
  // The closed one is written LAST, so recency alone would pick it. Openness comes first.
  writeCheckpoint(cwd, 'checkpoint-live.json', checkpoint('L2', [
    { id: 'L1', status: 'done' },
    { id: 'L2', status: 'in_progress', title: 'live work' },
  ]), 1_000_000);
  writeCheckpoint(cwd, 'checkpoint.json', checkpoint('H3', [
    { id: 'H3', status: 'done', title: 'finished long ago' },
  ]), 2_000_000);
  const r = preCompact({ cwd });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /checkpoint-live\.json/);
  assert.match(r.stdout, /cursor "L2"/);
  assert.ok(!/cursor "H3"/.test(r.stdout), 'a checkpoint with no open unit must not steer');
  assert.ok(!/finished long ago/.test(r.stdout));
});

test('among several open checkpoints the most recently written wins, deterministically', () => {
  const cwd = newCwd();
  writeCheckpoint(cwd, 'checkpoint-old.json', checkpoint('O1', [{ id: 'O1', status: 'todo' }]), 1_000_000);
  writeCheckpoint(cwd, 'checkpoint-new.json', checkpoint('N1', [{ id: 'N1', status: 'todo' }]), 3_000_000);
  const first = preCompact({ cwd }).stdout;
  const second = preCompact({ cwd }).stdout;
  assert.match(first, /checkpoint-new\.json/);
  assert.ok(!/checkpoint-old\.json/.test(first));
  assert.equal(first, second, 'the same tree must steer the same way twice');
});

// --------------------------------------------------------------- steering degrades
test('no .shiftwork at all still leaves a working hook', () => {
  const r = preCompact();
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stderr, '');
  assert.ok(hostWouldAccept(r.stdout).accepted);
  assert.match(r.stdout, /Preserve verbatim/);
  assert.ok(!/shiftwork checkpoint/.test(r.stdout));
});

test('a malformed or wrong-shaped checkpoint is skipped, never thrown on', () => {
  const cwd = newCwd();
  writeCheckpoint(cwd, 'checkpoint-truncated.json', '{"plan": {"cursor": "X"');
  writeCheckpoint(cwd, 'checkpoint-empty.json', '');
  writeCheckpoint(cwd, 'checkpoint-noplan.json', { version: 1, job: {} });
  writeCheckpoint(cwd, 'checkpoint-nounits.json', { version: 1, plan: { cursor: 'X', units: [] } });
  const r = preCompact({ cwd });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stderr, '');
  assert.ok(hostWouldAccept(r.stdout).accepted);
  assert.match(r.stdout, /Preserve verbatim/);
  assert.ok(!/shiftwork checkpoint/.test(r.stdout), 'nothing valid on disk must not produce a steering line');
});

test('a cursor pointing at no unit still steers, and says so', () => {
  const cwd = newCwd();
  writeCheckpoint(cwd, 'checkpoint-dangling.json', checkpoint('GHOST', [{ id: 'A1', status: 'todo' }]));
  const r = preCompact({ cwd });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /cursor "GHOST"/);
  assert.match(r.stdout, /not present in plan\.units/);
});

// -------------------------------------------------- the arms that DO use the envelope
test('SessionStart still uses the hookSpecificOutput envelope, and it is a valid one', () => {
  const r = runHook({ hook_event_name: 'SessionStart', source: 'startup' });
  assert.equal(r.status, 0, r.stderr);
  const verdict = hostWouldAccept(r.stdout);
  assert.ok(verdict.accepted, verdict.why);
  assert.match(r.stdout, /"hookEventName":"SessionStart"/);
});

test('an unknown event and unparseable stdin are both silent and exit 0', () => {
  const r = runHook({ hook_event_name: 'NoSuchEvent' });
  assert.equal(r.status, 0);
  assert.equal(r.stdout, '');
  assert.equal(r.stderr, '');
  // Both variables, always: `os.homedir()` reads $HOME on POSIX and %USERPROFILE% on
  // Windows, and this payload reaches `main()`'s catch, which APPENDS a parse-error line to
  // `<home>/.bantamkit/hooks/hook-log.jsonl`. With HOME alone that append lands in the
  // operator's real home on every Windows run, against this file's own header claim.
  const badHome = newHome();
  const bad = spawnSync(process.execPath, [HOOK], { input: 'not json', encoding: 'utf8', env: { ...process.env, HOME: badHome, USERPROFILE: badHome } });
  assert.equal(bad.status, 0);
  assert.equal(bad.stdout, '');
  assert.equal(bad.stderr, '');
});

// ------------------------------------------------------------------ the ledger half
/**
 * The other half of roadmap #9, and the half that shipped with NO coverage at all: the file
 * list PreCompact derives from the read ledger. Measured before these cases existed — delete
 * the whole `if (files.length)` block, or the count cap, and the file still passed 10/10.
 *
 * The ledger is NEVER written by hand here. Every case seeds it by running the adapter's own
 * `PreToolUse`/`Read` arm, the same process the host runs, so what is pinned is the PROPERTY
 * ("a file this transcript read is listed; one it did not read is not") and not the on-disk
 * shape of the ledger, which these cases never name.
 */

/** Record one Read in the ledger the way the host does: one hook process, one payload. */
function seedRead(file, { home, cwd, transcript, sessionId = 'probe-session' }) {
  const r = spawnSync(process.execPath, [HOOK], {
    input: JSON.stringify({
      hook_event_name: 'PreToolUse',
      tool_name: 'Read',
      cwd,
      session_id: sessionId,
      transcript_path: transcript,
      tool_input: { file_path: file },
    }),
    encoding: 'utf8',
    env: { ...process.env, HOME: home, USERPROFILE: home },
  });
  assert.equal(r.status, 0, `seeding a read must never fail: ${r.stderr}`);
  return r;
}

/** Make `count` real files under `cwd` (the arm stats them) and record a read of each. */
function seedReads(count, opts) {
  const files = [];
  for (let i = 0; i < count; i += 1) {
    const file = join(opts.cwd, `read-${String(i).padStart(3, '0')}.txt`);
    writeFileSync(file, `body ${i}`);
    seedRead(file, opts);
    files.push(file);
  }
  return files;
}

/** The adapter's own measurement channel, `<home>/.bantamkit/hooks/hook-log.jsonl`. */
function hookLog(home, event) {
  const lines = readFileSync(join(home, '.bantamkit', 'hooks', 'hook-log.jsonl'), 'utf8')
    .split('\n').filter(Boolean).map((l) => JSON.parse(l));
  return event ? lines.filter((r) => r.event === event) : lines;
}

/** The `- <path>` lines of the "Files already read" block. */
function listedFiles(stdout) {
  return stdout.split('\n').filter((l) => l.startsWith('- ')).map((l) => l.slice(2));
}

test('PreCompact lists the files THIS transcript read, taken from the ledger', () => {
  const home = newHome();
  const cwd = newCwd();
  const transcript = join(cwd, 'parent.jsonl');
  const files = seedReads(3, { home, cwd, transcript });

  const r = preCompact({ home, cwd, payload: { transcript_path: transcript } });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /Files already read in this context/, 'the ledger half must steer at all');
  for (const f of files) assert.ok(r.stdout.includes(f), `${f} was read in this transcript and must be listed`);
  assert.deepEqual(listedFiles(r.stdout).sort(), [...files].sort());
});

test('a file only a SUBAGENT read is not reported to the parent as read in this context', () => {
  const home = newHome();
  const cwd = newCwd();
  const parent = join(cwd, 'parent.jsonl');
  const child = join(cwd, 'subagent.jsonl');

  const mine = join(cwd, 'seen-by-parent.txt');
  const theirs = join(cwd, 'seen-by-subagent-only.txt');
  writeFileSync(mine, 'a');
  writeFileSync(theirs, 'b');
  seedRead(mine, { home, cwd, transcript: parent });
  seedRead(theirs, { home, cwd, transcript: child });

  // The refusal arm already keys on the transcript ("a subagent has its own transcript and
  // is never refused for the parent's read", docs/hooks.md:28). The steering must agree with
  // it: telling the parent's summariser not to re-read a file the parent never saw hands the
  // rebuilt context a false premise that survives the PostCompact ledger reset.
  const r = preCompact({ home, cwd, payload: { transcript_path: parent } });
  assert.equal(r.status, 0, r.stderr);
  assert.ok(r.stdout.includes(mine), 'the parent read this one');
  assert.ok(!r.stdout.includes(theirs), 'only the subagent read this one — the parent has never seen its content');
  assert.deepEqual(listedFiles(r.stdout), [mine]);

  // and symmetrically, from the subagent's own compaction
  const s = preCompact({ home, cwd, payload: { transcript_path: child } });
  assert.deepEqual(listedFiles(s.stdout), [theirs]);
});

test('the file list is capped by count, however many the ledger holds', () => {
  const home = newHome();
  const cwd = newCwd();
  const transcript = join(cwd, 'parent.jsonl');
  seedReads(45, { home, cwd, transcript });

  const r = preCompact({ home, cwd, payload: { transcript_path: transcript } });
  assert.equal(r.status, 0, r.stderr);
  assert.ok(listedFiles(r.stdout).length <= 40, `listed ${listedFiles(r.stdout).length} paths; the cap is 40`);

  // Path length varies by platform, so the byte budget below could be what binds in stdout.
  // The adapter's own log separates the two bounds, and THIS is the one that pins the count.
  const rec = hookLog(home, 'PreCompact').at(-1);
  assert.equal(rec.ledgerFiles, 45, 'all 45 reads belong to this transcript');
  assert.equal(rec.capped, 40, 'the count cap must bind at 40 before any byte budget does');
});

test('PreCompact stdout stays inside its byte budget, and the tail always survives the cut', () => {
  const home = newHome();
  const cwd = newCwd();
  const transcript = join(cwd, 'parent.jsonl');
  // Long names, so 40 of them alone would run past the budget the host echoes to the user.
  for (let i = 0; i < 40; i += 1) {
    const file = join(cwd, `${'deep-directory-name-that-makes-this-path-long'.repeat(3)}-${i}.txt`);
    writeFileSync(file, 'x');
    seedRead(file, { home, cwd, transcript });
  }
  writeCheckpoint(cwd, 'checkpoint-live.json', checkpoint('U1', [
    { id: 'U1', status: 'todo', title: 'a title '.repeat(400) },
  ]));

  const r = preCompact({ home, cwd, payload: { transcript_path: transcript } });
  assert.equal(r.status, 0, r.stderr);
  const bytes = Buffer.byteLength(r.stdout);
  assert.ok(bytes <= 4000, `PreCompact stdout was ${bytes} B; the host echoes every byte of it to the user on every compaction`);
  // The cut must land on the file list, never on the two lines that carry the instruction.
  assert.match(r.stdout, /Preserve verbatim/, 'the tail is what the steering is FOR');
  assert.match(r.stdout, /Open shiftwork checkpoint/, 'the open unit must survive the cut too');
  assert.ok(listedFiles(r.stdout).length > 0, 'the budget must trim the list, not delete it');
});

test('the log records the bytes actually written, not the bytes considered', () => {
  const home = newHome();
  const cwd = newCwd();
  const transcript = join(cwd, 'parent.jsonl');
  seedReads(2, { home, cwd, transcript });
  const r = preCompact({ home, cwd, payload: { transcript_path: transcript } });
  const rec = hookLog(home, 'PreCompact').at(-1);
  assert.equal(rec.bytes, Buffer.byteLength(r.stdout), 'this log is the repo\'s measurement of record; it must not assert bytes the process never wrote');
  assert.equal(rec.listed, listedFiles(r.stdout).length);
});

test('the steering never starts with { — for every shape of input the arm accepts', () => {
  // `emitText` used to carry an unreachable leading-`{` refusal that would have DROPPED the
  // whole steering with no trace. The refusal is gone; this is the property it was guarding,
  // pinned where it can actually go red — if a later edit ever puts a user-controlled string
  // first, the host would JSON-parse it and reject the output the way it did at b3625d9.
  const home = newHome();
  const cwd = newCwd();
  const transcript = join(cwd, 'parent.jsonl');
  const brace = join(cwd, '{braces}.txt');
  writeFileSync(brace, 'x');
  seedRead(brace, { home, cwd, transcript });
  writeCheckpoint(cwd, '{odd}.json', checkpoint('{C}', [{ id: '{C}', status: 'todo', title: '{a title}' }]));

  for (const payload of [{ transcript_path: transcript }, {}]) {
    const r = preCompact({ home, cwd, payload });
    assert.equal(r.status, 0, r.stderr);
    assert.ok(!r.stdout.trim().startsWith('{'), `steering must reach the host as plain text: ${r.stdout.slice(0, 80)}`);
    assert.ok(hostWouldAccept(r.stdout).accepted);
    // …and it must still be THERE. Refusing to emit is not a way to satisfy the line above:
    // `fK` drops an empty result, so a silent drop and a rejected envelope cost the same.
    assert.match(r.stdout, /Preserve verbatim/, 'the steering must survive, not be suppressed');
    assert.match(r.stdout, /\{odd\}\.json/, 'the user-controlled strings must reach the summariser');
  }
});

test('a .shiftwork over the scan budget still steers, and the log says what it skipped', () => {
  const home = newHome();
  const cwd = newCwd();
  // Every filler is CLOSED and NEWER than the open one, which is the only arrangement that
  // makes the scan walk: newest-first stops at the first OPEN checkpoint, so when the live
  // one is newest (the ordinary case, and what the cases above cover) exactly one file is
  // ever read. `.shiftwork` is never pruned — measured on this repo 2026-09-04, 133,472 B
  // across 6 files, 11 KB of it added by one session — and before the budget every one of
  // them was read and JSON-parsed on every compaction.
  const filler = checkpoint('D1', [{ id: 'D1', status: 'done', title: 'x'.repeat(200_000) }]);
  writeCheckpoint(cwd, 'checkpoint-live.json', checkpoint('L9', [{ id: 'L9', status: 'todo', title: 'the open unit' }]), 1_000_000);
  for (let i = 0; i < 12; i += 1) writeCheckpoint(cwd, `checkpoint-archive-${i}.json`, filler, 9_000_000 + i);

  const r = preCompact({ home, cwd });
  assert.equal(r.status, 0, r.stderr);
  const rec = hookLog(home, 'PreCompact').at(-1);
  assert.ok(rec.cpSkipped > 0, `the scan must stop on a budget, not read all 13: skipped ${rec.cpSkipped}`);
  assert.ok(rec.cpBytes <= 1_000_000 + 4_000_000, `the aggregate read is bounded: ${rec.cpBytes} B`);

  // What the bound COSTS, stated rather than hidden: a live checkpoint buried under more
  // than a megabyte of newer archived ones is not reached, and the rest of the steering
  // still goes out. The hook stays quiet and correct; the log says how many it skipped.
  assert.ok(!/Open shiftwork checkpoint/.test(r.stdout), 'a checkpoint past the scan budget must not be reported as found');
  assert.match(r.stdout, /Preserve verbatim/, 'the rest of the steering must survive a spent budget');
});

// ------------------------------------------------------ postSave's --index-budget denominator
/**
 * `postSave` (`PostToolUse` on `mcp__bantamkit__memory_save`) used to open `Memory.layered(cwd)`
 * with no `indexBudget`, which always falls back to the DEFAULT — so under a real
 * `--index-budget N` the 90% band was measured against the wrong denominator
 * (`docs/roadmap-toolbox.md`, registered 2026-08-28, never fixed until now). The fix reads the
 * same three scopes `tools/mcpdrift/mcpdrift.py`'s `discover()` reads for a project's
 * `bantamkit` registration — user (`~/.claude.json` `.mcpServers`), local (that file's
 * `.projects[<cwd>].mcpServers`), and project (`<cwd>/.mcp.json`).
 *
 * **CORRECTED 2026-09-06 (job44, unit F4). The first fix resolved the three scopes wrongly and
 * one of the cases below used to pin the wrong answer.** It gathered the DISTINCT values across
 * all three and logged `skip-ambiguous-budget` whenever it found more than one — which is the
 * NORMAL configuration, not an ambiguous one, so a project-scope override beside a user-scope
 * default silently stopped automatic compaction for that project. Claude Code resolves the same
 * three by PRECEDENCE, `local > project > user`, connecting once to the highest-precedence
 * definition and NEVER merging fields across scopes
 * (https://code.claude.com/docs/en/mcp, "MCP installation scopes", read 2026-09-06).
 *
 * The `refuses to auto-compact when scopes disagree` case is therefore GONE rather than
 * relaxed, and what replaced it asserts more, not less: each of the three scopes wins over the
 * ones below it (the very configuration that case declared unresolvable now has to produce the
 * right denominator AND compact), the local scope — which nothing exercised before — is read,
 * and the whole-entry rule is pinned by the one shape that separates it from a per-flag search:
 * a winning entry with no `--index-budget` means the DEFAULT even when a lower scope names a
 * number.
 */
const MEMORY_DIST = join(repoRoot, 'runtime-ts', 'dist', 'memory');

/**
 * Seed real facts through the real `Memory.save`, never by hand-writing a fact file.
 *
 * The duplicate gate (`DUPLICATE_JACCARD = 0.5`, `store.ts:97`) scores on the TOKENS of
 * `name + description` alone — body is never part of that check, and `indexText` is built
 * from name/type/description too, never body (`store.ts:913-926`), so a fixture only needs
 * a distinct, budget-sized description per fact; a shared filler body would make every fact
 * a near-duplicate of the last one on NAME+DESCRIPTION grounds even though bytes differ.
 * Each fact's description repeats ONE stem unique to that fact index, so cross-fact token
 * sets never intersect and every save actually lands.
 */
async function seedFacts(store, count, targetBytesPerFact) {
  const { Memory } = await import(join(MEMORY_DIST, 'component.js'));
  const m = new Memory(store);
  const stems = ['alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot', 'golf', 'hotel', 'india', 'juliet'];
  for (let i = 0; i < count; i += 1) {
    const stem = `${stems[i % stems.length]}${i}`;
    let description = '';
    while (Buffer.byteLength(description) < targetBytesPerFact) description += `${stem} `;
    const outcome = m.saveOutcome('project', stem, description.trim(), 'body');
    assert.equal(outcome.status, 'saved', `fixture fact ${i} must actually save: ${outcome.reply}`);
  }
}

function postToolUseSave(opts = {}) {
  return runHook({ hook_event_name: 'PostToolUse', tool_name: 'mcp__bantamkit__memory_save' }, opts);
}

/**
 * One registration entry as the host would hold it. An ARRAY is `args` alone (the shape every
 * `--index-budget` case passes); an OBJECT is spread over the entry so a case can name `env`
 * — the field the store pin lives in — without every older case growing a wrapper.
 */
function registrationEntry(command, spec) {
  return Array.isArray(spec) ? { command, args: spec } : { command, ...spec };
}

function mcpJsonArgs(cwd, spec) {
  writeFileSync(join(cwd, '.mcp.json'), JSON.stringify({ mcpServers: { bantamkit: registrationEntry('tools/bantamkit-mcp', spec) } }));
}

function claudeJsonUserArgs(home, args) {
  writeFileSync(join(home, '.claude.json'), JSON.stringify({ mcpServers: { bantamkit: { command: 'npx', args } } }));
}

/**
 * Both `~/.claude.json` scopes at once, because they live in ONE file: `user` is the top-level
 * `.mcpServers`, `local` is `.projects[<cwd>].mcpServers`. Pass `[]` for an entry that exists
 * and configures no flag — that shape is the whole-entry rule's witness — and omit the key
 * entirely for a scope that registers nothing.
 */
function claudeJsonScopes(home, { user, local, cwd } = {}) {
  const doc = {};
  if (user !== undefined) doc.mcpServers = { bantamkit: registrationEntry('npx', user) };
  if (local !== undefined) doc.projects = { [cwd]: { mcpServers: { bantamkit: registrationEntry('npx', local) } } };
  writeFileSync(join(home, '.claude.json'), JSON.stringify(doc));
}

test('postSave measures the 90% band against a configured --index-budget, not the default', async () => {
  const cwd = newCwd();
  const home = newHome();
  // Six facts of ~300 B each: nowhere near 90% of the DEFAULT 24000-byte budget, well over
  // 90% of a configured 1500-byte one.
  await seedFacts(join(cwd, '.bantamkit', 'memory'), 6, 300);
  mcpJsonArgs(cwd, ['--index-budget', '1500']);

  const r = postToolUseSave({ cwd, home });
  assert.equal(r.status, 0, r.stderr);
  const rec = hookLog(home, 'PostToolUse').find((l) => l.action === 'auto-compact' || l.action === 'saved');
  assert.ok(rec, 'postSave must log a saved-or-compacted decision');
  assert.equal(rec.budget, 1500, 'indexAccounting must be measured against the CONFIGURED budget, not the default 24000 — this is the bug this case pins');
  assert.equal(rec.action, 'auto-compact', 'this index is over 90% of the configured 1500-byte budget and must trigger the automatic half');
  assert.match(r.stdout, /"additionalContext":"\[bantamkit\] memory index was \d+\/1500 B/);
  // WHAT THE ARM ACTUALLY ASKS `compact` FOR, added 2026-09-10 (job46, J46-6) because
  // NOTHING PINNED IT. Every case in this file matched on `action` alone, so the arm could
  // have asked for any target at all and all 28 tests would still have passed — which is how
  // job46's change to the DEFAULT reserve silently moved this arm's real aim from
  // `0.8 * budget - largest line` to `0.9 * 0.8 * budget - largest line` with no test
  // noticing. The aim is now named as a RESERVE against the real budget, so it is exact and
  // it is decidable here: 80% of 1500 is 1200, the reserve is the 300 bytes above it, and
  // `compact`'s target is `budget - reserve` = 1200 — the same number the message prints.
  //
  // THE ASSERTION IS ON THE CLI'S OWN ACCOUNTING LINE AND NOT ON THE LOG RECORD, and the
  // difference is the whole point. `rec.target` and `rec.reserve` are computed in the hook
  // before the spawn and are logged whatever argv is actually sent — MEASURED: reverting the
  // argv to the pre-J46-6 `--budget <target>` left all three log fields identical and this
  // test green. `compact` echoes the budget and the target IT was given, so that line is the
  // only thing here that can tell the two spellings apart. 80% of 1500 is 1200, and the arm
  // asks for it as `--budget 1500 --reserve 300` so that the DEFAULT reserve — which job46
  // moved — cannot move this aim again.
  assert.equal(rec.budget, 1500, 'indexAccounting is measured against the configured budget');
  assert.equal(rec.target, 1200, '80% of the configured budget');
  assert.equal(rec.reserve, 300, 'the aim, expressed as headroom under the real budget');
  const accounting = /index: \d+ -> \d+ bytes \(budget (\d+), target (\d+), reserve (\d+),/.exec(r.stdout);
  assert.ok(accounting, `compact must echo its accounting; got ${JSON.stringify(r.stdout.slice(0, 400))}`);
  assert.deepEqual(
    accounting.slice(1, 4).map(Number),
    [1500, 1200, 300],
    'compact must be told the REAL budget and asked for the aim as a reserve — a `--budget 1200` with a default reserve lands somewhere else',
  );
  assert.match(r.stdout, /auto-compacted to ≤1200 B/);
});

test('postSave still assumes the default budget when nothing configures --index-budget anywhere it looks', async () => {
  const cwd = newCwd();
  const home = newHome();
  await seedFacts(join(cwd, '.bantamkit', 'memory'), 6, 300); // same fixture, no override anywhere
  const r = postToolUseSave({ cwd, home });
  assert.equal(r.status, 0, r.stderr);
  const rec = hookLog(home, 'PostToolUse').find((l) => l.action === 'saved' || l.action === 'auto-compact');
  assert.ok(rec);
  assert.equal(rec.budget, 24000);
  assert.equal(rec.budgetSource, 'default');
  assert.equal(rec.action, 'saved', 'this index is nowhere near 90% of the true default budget');
});

// The three precedence cases. Each puts a WRONG number in every scope below the one under
// test, so a hook that fell through to a lower scope — or that collected values across scopes
// the way the first fix did — cannot pass by accident: 9000 and 24000 are both far enough
// above this fixture's index that the 90% band would not trip, so picking the wrong scope
// changes `action` and not merely `budget`.
test('project scope beats user scope — the configuration the old ambiguity refusal broke', async () => {
  const cwd = newCwd();
  const home = newHome();
  await seedFacts(join(cwd, '.bantamkit', 'memory'), 6, 300);
  mcpJsonArgs(cwd, ['--index-budget', '1500']);        // project scope: the override
  claudeJsonUserArgs(home, ['--index-budget', '9000']); // user scope: the machine-wide default

  const r = postToolUseSave({ cwd, home });
  assert.equal(r.status, 0, r.stderr);
  const skipped = hookLog(home, 'PostToolUse').find((l) => l.action === 'skip-ambiguous-budget');
  assert.equal(skipped, undefined, 'a project override beside a user default is configured, not ambiguous');
  const rec = hookLog(home, 'PostToolUse').find((l) => l.action === 'auto-compact' || l.action === 'saved');
  assert.equal(rec.budget, 1500, 'project scope outranks user scope');
  assert.equal(rec.budgetScope, 'project');
  assert.equal(rec.action, 'auto-compact', 'this is the failure the register named: compaction must NOT silently stop here');
});

test('local scope beats both project and user scope', async () => {
  const cwd = newCwd();
  const home = newHome();
  await seedFacts(join(cwd, '.bantamkit', 'memory'), 6, 300);
  mcpJsonArgs(cwd, ['--index-budget', '9000']);
  claudeJsonScopes(home, { cwd, user: ['--index-budget', '9000'], local: ['--index-budget', '1500'] });

  const r = postToolUseSave({ cwd, home });
  assert.equal(r.status, 0, r.stderr);
  const rec = hookLog(home, 'PostToolUse').find((l) => l.action === 'auto-compact' || l.action === 'saved');
  assert.equal(rec.budget, 1500, 'local scope outranks project and user');
  assert.equal(rec.budgetScope, 'local');
  assert.equal(rec.action, 'auto-compact');
});

test('a lone local-scope --index-budget is read — the scope nothing exercised before', async () => {
  const cwd = newCwd();
  const home = newHome();
  await seedFacts(join(cwd, '.bantamkit', 'memory'), 6, 300);
  claudeJsonScopes(home, { cwd, local: ['--index-budget', '1500'] });

  const r = postToolUseSave({ cwd, home });
  assert.equal(r.status, 0, r.stderr);
  const rec = hookLog(home, 'PostToolUse').find((l) => l.action === 'auto-compact' || l.action === 'saved');
  assert.equal(rec.budget, 1500, '.projects[<cwd>].mcpServers is a scope this hook must read');
  assert.equal(rec.budgetSource, 'configured');
  assert.equal(rec.budgetScope, 'local');
});

// The whole-entry rule, and the ONLY shape that separates it from a per-flag search across
// scopes. Claude Code never merges fields across scopes, so the local entry — which registers
// no `--index-budget` — is the entry the session launched, and the answer is the DEFAULT. A
// hook that searched scope by scope for the flag would find the user scope's 1500 and compact
// against a denominator no live server is using.
test('the winning entry is the whole answer: a local entry with no --index-budget means the default', async () => {
  const cwd = newCwd();
  const home = newHome();
  await seedFacts(join(cwd, '.bantamkit', 'memory'), 6, 300);
  claudeJsonScopes(home, { cwd, user: ['--index-budget', '1500'], local: [] });

  const r = postToolUseSave({ cwd, home });
  assert.equal(r.status, 0, r.stderr);
  const rec = hookLog(home, 'PostToolUse').find((l) => l.action === 'auto-compact' || l.action === 'saved');
  assert.equal(rec.budget, 24000, 'the local entry names no budget, so the default is what the launched server uses');
  assert.equal(rec.budgetSource, 'default');
  assert.equal(rec.budgetScope, null);
  assert.equal(rec.action, 'saved', 'against the true default this index is nowhere near the 90% band');
});

test('a lone user-scope --index-budget (no project override) is read too', async () => {
  const cwd = newCwd();
  const home = newHome();
  await seedFacts(join(cwd, '.bantamkit', 'memory'), 6, 300);
  claudeJsonUserArgs(home, ['--index-budget', '1500']);
  const r = postToolUseSave({ cwd, home });
  assert.equal(r.status, 0, r.stderr);
  const rec = hookLog(home, 'PostToolUse').find((l) => l.action === 'auto-compact' || l.action === 'saved');
  assert.equal(rec.budget, 1500);
  assert.equal(rec.budgetSource, 'configured');
});

// The `UserPromptSubmit` recall arm opens `Memory.layered` too, but only calls
// `recallOutcome` — never `indexAccounting` — so a configured `--index-budget` cannot change
// what it injects. Confirmed rather than assumed: a huge configured budget must not suppress
// or alter a recall hit.
test('UserPromptSubmit recall is unaffected by a configured --index-budget', async () => {
  const cwd = newCwd();
  const home = newHome();
  const { Memory } = await import(join(MEMORY_DIST, 'component.js'));
  new Memory(join(cwd, '.bantamkit', 'memory')).saveOutcome(
    'project', 'deploy-flag', 'how the deploy flag works', 'run make deploy',
  );
  mcpJsonArgs(cwd, ['--index-budget', '1']); // absurdly small, would refuse a save if this arm read it
  const r = runHook(
    { hook_event_name: 'UserPromptSubmit', prompt: 'how does the deploy flag work here' },
    { cwd, home },
  );
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /"hookEventName":"UserPromptSubmit"/);
  assert.match(r.stdout, /deploy-flag/);
});

// ------------------------------------------- the store the winning registration pins (J50-1)
//
// `discoverProjectStore`, `resolveProjectStore` and `Memory.layered` all resolve the project
// store through `pinnedStore()`, which reads `process.env.BANTAMKIT_MEMORY_DIR`
// (`runtime-ts/src/memory/layers.ts`). The SERVER sees a registration's `env` because the
// host merges it into the server's process; the HOOK is launched by the host and never
// receives it. So a registration that pinned the store had the hook injecting from the store
// the walk finds while the server saved into the pinned one — a latent split, closed by
// reading `env.BANTAMKIT_MEMORY_DIR` off the winning entry with the same
// `local > project > user` walk `--index-budget` already uses, and applying it to the hook's
// own environment so the ONE shared resolution sees what the server sees.
//
// Each case puts a DIFFERENT, populated store in every place the hook could wrongly bind —
// the walk's own `<cwd>/.bantamkit/memory` and every lower scope's pin — each holding a fact
// whose NAME is unique to that store and whose description matches the same prompt, so a
// wrong binding changes WHICH name reaches stdout, never whether one does.

async function storeWithFact(dir, name) {
  const { Memory } = await import(join(MEMORY_DIST, 'component.js'));
  const outcome = new Memory(dir).saveOutcome('project', name, `${name} explains the release ladder`, 'body');
  assert.equal(outcome.status, 'saved', `fixture fact ${name} must save: ${outcome.reply}`);
  return dir;
}

/** A registration whose `env` pins the store, and configures nothing else. */
function pinEntry(dir) {
  return { args: [], env: { BANTAMKIT_MEMORY_DIR: dir } };
}

function sessionStart(opts) {
  return runHook({ hook_event_name: 'SessionStart', source: 'startup' }, opts);
}

function promptAboutTheLadder(opts) {
  return runHook({ hook_event_name: 'UserPromptSubmit', prompt: 'walk me through the release ladder' }, opts);
}

test('SessionStart and UserPromptSubmit inject from the store the winning registration pins, not the one the walk finds', async () => {
  const cwd = newCwd();
  const home = newHome();
  await storeWithFact(join(cwd, '.bantamkit', 'memory'), 'walk-fact');
  const pinned = await storeWithFact(join(scratch, `pinned-${n++}`), 'pinned-fact');
  claudeJsonScopes(home, { cwd, local: pinEntry(pinned) });

  const s = sessionStart({ cwd, home });
  assert.equal(s.status, 0, s.stderr);
  assert.match(s.stdout, /pinned-fact/, 'SessionStart must inject the index of the store the server would write into');
  assert.doesNotMatch(s.stdout, /walk-fact/, 'the store the walk finds is not the one the session launched');
  const rec = hookLog(home, 'SessionStart').find((l) => l.source === 'startup');
  assert.equal(rec.storeScope, 'local', 'the log names the scope whose entry pinned the store');

  const u = promptAboutTheLadder({ cwd, home });
  assert.equal(u.status, 0, u.stderr);
  assert.match(u.stdout, /pinned-fact/, 'recall must read the pinned store too');
  assert.doesNotMatch(u.stdout, /walk-fact/);
});

test('the pin follows --index-budget precedence: local beats project beats user', async () => {
  const cwd = newCwd();
  const home = newHome();
  await storeWithFact(join(cwd, '.bantamkit', 'memory'), 'walk-fact');
  const userStore = await storeWithFact(join(scratch, `pinned-${n++}`), 'user-fact');
  const projectStore = await storeWithFact(join(scratch, `pinned-${n++}`), 'project-fact');
  const localStore = await storeWithFact(join(scratch, `pinned-${n++}`), 'local-fact');
  mcpJsonArgs(cwd, pinEntry(projectStore));
  claudeJsonScopes(home, { cwd, user: pinEntry(userStore), local: pinEntry(localStore) });

  const s = sessionStart({ cwd, home });
  assert.equal(s.status, 0, s.stderr);
  assert.match(s.stdout, /local-fact/);
  for (const wrong of ['project-fact', 'user-fact', 'walk-fact']) assert.doesNotMatch(s.stdout, new RegExp(wrong));
  assert.equal(hookLog(home, 'SessionStart')[0].storeScope, 'local');
});

test('project scope pins over user scope', async () => {
  const cwd = newCwd();
  const home = newHome();
  await storeWithFact(join(cwd, '.bantamkit', 'memory'), 'walk-fact');
  const userStore = await storeWithFact(join(scratch, `pinned-${n++}`), 'user-fact');
  const projectStore = await storeWithFact(join(scratch, `pinned-${n++}`), 'project-fact');
  mcpJsonArgs(cwd, pinEntry(projectStore));
  claudeJsonScopes(home, { cwd, user: pinEntry(userStore) });

  const s = sessionStart({ cwd, home });
  assert.equal(s.status, 0, s.stderr);
  assert.match(s.stdout, /project-fact/);
  for (const wrong of ['user-fact', 'walk-fact']) assert.doesNotMatch(s.stdout, new RegExp(wrong));
  assert.equal(hookLog(home, 'SessionStart')[0].storeScope, 'project');
});

// The whole-entry rule, applied to `env` exactly as it is applied to `args`: the host never
// merges fields across scopes, so a winning entry that names no pin means the walk, even
// when a lower scope pins — that lower entry is not what the session launched.
test('a winning entry with no pin means the walk, even when a lower scope pins', async () => {
  const cwd = newCwd();
  const home = newHome();
  await storeWithFact(join(cwd, '.bantamkit', 'memory'), 'walk-fact');
  const userStore = await storeWithFact(join(scratch, `pinned-${n++}`), 'user-fact');
  claudeJsonScopes(home, { cwd, user: pinEntry(userStore), local: [] });

  const s = sessionStart({ cwd, home });
  assert.equal(s.status, 0, s.stderr);
  assert.match(s.stdout, /walk-fact/);
  assert.doesNotMatch(s.stdout, /user-fact/);
  assert.equal(hookLog(home, 'SessionStart')[0].storeScope, null);
});

// A pin the server would refuse at construction (`docs/memory.md`, "Pinning the store") is
// refused by the hook through the same code, in the same sentence — and the hook stays a
// hook: exit 0, the profile half still injected, and the refusal on the log rather than on
// the host's screen.
test('a pin the server would refuse does not crash the hook, and the log carries the server\'s own sentence', async () => {
  const cwd = newCwd();
  const home = newHome();
  await storeWithFact(join(cwd, '.bantamkit', 'memory'), 'walk-fact');
  claudeJsonScopes(home, { cwd, local: pinEntry(join(scratch, 'no-such-store')) });

  const s = sessionStart({ cwd, home });
  assert.equal(s.status, 0, s.stderr);
  assert.doesNotMatch(s.stdout, /walk-fact/, 'a refused pin is not silently downgraded to the walk — the server would not do that either');
  const rec = hookLog(home, 'SessionStart').find((l) => l.warn);
  assert.ok(rec, 'the refusal is logged');
  assert.match(rec.warn, /pinned memory store is unreachable/);
});

// ------------------------------------ the session header counts what ARRIVED (J50-2E)
//
// `SessionStart` wrote its header from the store's fact COUNT and its body from what survived
// `capLines(…, SESSION_INJECT_MAX)`, which drops whole lines. Reproduced on this machine's
// 20-fact profile store, 2026-09-12: the header said 20, the body carried 15 (2,943 B; line
// 16 would have reached 3,155), and the log said `profileFacts: 20` — nothing said five facts
// never reached the model, and WHICH five was decided by the index's alphabetical order.
// The cases pin the property the fix holds: the header's number is the number of fact lines
// in the block; a drop is disclosed in the block and named in the log; no disclosure fires
// when nothing was dropped; and the drop follows a stated rule, not the alphabet. Every
// fixture is seeded through the real `Memory.save`, so dates come from the store's own
// `today` seam and `last_recalled` from a real recall, never from a hand-written file.

const profileDir = (home) => join(home, '.bantamkit', 'memory');

/** One injected index block: header, its fact lines, and the disclosure line if any. */
function indexBlock(stdout, kind) {
  const ctx = JSON.parse(stdout).hookSpecificOutput.additionalContext;
  const block = ctx.split('\n\n').find((b) => b.startsWith(`[bantamkit ${kind} memory — `));
  assert.ok(block, `a ${kind} block was injected`);
  const lines = block.split('\n');
  const header = lines[0].match(/^\[bantamkit (?:profile|project) memory — (\d+)(?: of (\d+))? facts/);
  assert.ok(header, `the header has the announced shape: ${lines[0]}`);
  const facts = lines.slice(1).filter((l) => l.startsWith('- [['));
  const disclosure = lines.slice(1).filter((l) => /not shown/.test(l));
  const names = facts.map((l) => l.match(/^- \[\[([^\]]+)\]\]/)[1]);
  return { shown: Number(header[1]), total: header[2] === undefined ? null : Number(header[2]), facts, disclosure, names, factBytes: Buffer.byteLength(facts.join('\n')) };
}

function storedNames(dir) {
  return readdirSync(join(dir, 'facts')).filter((f) => f.endsWith('.md')).map((f) => f.replace(/\.md$/, '')).sort();
}

test('the SessionStart header counts the facts in the block, and a drop is disclosed there and named in the log', async () => {
  const home = newHome();
  await seedFacts(profileDir(home), 30, 180); // ~6.3 kB of index against a 3,000 B cap
  const s = sessionStart({ home });
  assert.equal(s.status, 0, s.stderr);
  const b = indexBlock(s.stdout, 'profile');
  assert.ok(b.facts.length > 0 && b.facts.length < 30, `the fixture must actually exceed the cap (got ${b.facts.length} of 30)`);
  assert.equal(b.shown, b.facts.length, 'the header counts the fact lines that are IN the block');
  assert.equal(b.total, 30, 'and says how many the store holds');
  assert.ok(b.factBytes <= 3000, `the fact lines stay inside the cap: ${b.factBytes}`);
  assert.equal(b.disclosure.length, 1, 'exactly one disclosure line');
  assert.match(b.disclosure[0], new RegExp(`^\\[${30 - b.facts.length} of 30 not shown`));
  const rec = hookLog(home, 'SessionStart')[0];
  assert.equal(rec.profileFacts, 30, 'the store count keeps its old meaning');
  assert.equal(rec.profileInjected, b.facts.length);
  assert.deepEqual([...b.names, ...rec.profileDropped].sort(), storedNames(profileDir(home)), 'shown + dropped is exactly the store — nothing counted twice, nothing lost');
  assert.equal(typeof rec.dropRule, 'string', 'the log names the rule the drop followed');
});

test('a store under the cap: the header is the store count, and no disclosure fires', async () => {
  const home = newHome();
  await seedFacts(profileDir(home), 3, 60);
  const s = sessionStart({ home });
  assert.equal(s.status, 0, s.stderr);
  const b = indexBlock(s.stdout, 'profile');
  assert.equal(b.facts.length, 3);
  assert.equal(b.shown, 3);
  assert.equal(b.total, null, 'no "of N" when nothing was dropped');
  assert.equal(b.disclosure.length, 0, 'a disclosure that fires when nothing was dropped is its own bug');
  const rec = hookLog(home, 'SessionStart')[0];
  assert.equal(rec.profileFacts, 3);
  assert.equal(rec.profileInjected, 3);
  assert.deepEqual(rec.profileDropped, []);
});

// The rule, one half per judged fact. Alphabetical order would keep `aa-…` and `ab-…` and
// drop `zz-…`; created-only order would drop `ac-…`. Each assertion below is red under one of
// those and green under the stated rule, so a regression to either shows up by name.
test('what is dropped follows the stated rule, not the alphabet: durable types first, then the most recently recalled', async () => {
  const home = newHome();
  const dir = profileDir(home);
  const { Memory } = await import(join(MEMORY_DIST, 'component.js'));
  const save = (today, type, name, stem) => {
    let description = '';
    while (Buffer.byteLength(description) < 180) description += `${stem} `;
    const o = new Memory(dir, { today: () => today }).saveOutcome(type, name, description.trim(), 'body');
    assert.equal(o.status, 'saved', `fixture fact ${name} must save: ${o.reply}`);
  };
  for (let i = 0; i < 14; i += 1) save('2026-05-01', 'feedback', `mm-filler-${i}`, `filler${i}`);
  save('2026-09-01', 'project', 'aa-project-newest', 'projectnew');          // alphabet-first, newest, DECAYING type
  save('2026-01-01', 'feedback', 'ab-feedback-oldest', 'feedbackold');       // alphabet-second, oldest evidence
  save('2026-01-01', 'feedback', 'ac-feedback-old-but-recalled', 'recalledold');
  save('2026-09-01', 'feedback', 'zz-feedback-newest', 'feedbacknew');       // alphabet-last, newest
  // A real recall stamps `last_recalled` on the old fact, and that stamp outranks `created`.
  new Memory(dir, { today: () => '2026-09-12' }).recall('recalledold');

  const s = sessionStart({ home });
  assert.equal(s.status, 0, s.stderr);
  const b = indexBlock(s.stdout, 'profile');
  const rec = hookLog(home, 'SessionStart')[0];
  assert.ok(rec.profileDropped.length >= 3, `the fixture must drop at least the three judged facts (dropped ${rec.profileDropped.length})`);
  assert.ok(b.names.includes('zz-feedback-newest'), 'the newest durable fact is kept although the alphabet would drop it');
  assert.ok(b.names.includes('ac-feedback-old-but-recalled'), 'a recent recall outranks an old created date');
  assert.ok(rec.profileDropped.includes('ab-feedback-oldest'), 'the stalest durable fact goes before any filler');
  assert.ok(rec.profileDropped.includes('aa-project-newest'), 'a decaying type goes before every durable one, whatever its date or name');
  assert.match(rec.dropRule, /recalled/, 'the log names the rule in words');
  assert.deepEqual([...b.names, ...rec.profileDropped].sort(), storedNames(dir));
});

test('the project block gets the same header, disclosure and log fields', async () => {
  const home = newHome();
  const cwd = newCwd();
  await seedFacts(join(cwd, '.bantamkit', 'memory'), 30, 180);
  const s = sessionStart({ home, cwd });
  assert.equal(s.status, 0, s.stderr);
  const b = indexBlock(s.stdout, 'project');
  assert.ok(b.facts.length < 30, 'the fixture must exceed the cap');
  assert.equal(b.shown, b.facts.length);
  assert.equal(b.total, 30);
  assert.equal(b.disclosure.length, 1);
  const rec = hookLog(home, 'SessionStart')[0];
  assert.equal(rec.projectFacts, 30);
  assert.equal(rec.projectInjected, b.facts.length);
  assert.deepEqual([...b.names, ...rec.projectDropped].sort(), storedNames(join(cwd, '.bantamkit', 'memory')));
});

// --------------------------------------------- the injection record roadmap #6 measures on
//
// Roadmap #6 gates injection on a SCORE and then asks whether an injected name was later
// used. Neither question can be asked of the record the arm used to write: `hits` and `bytes`
// say how many and how big, never WHICH or AT WHAT SCORE, and with no session id the record
// cannot be joined to the transcript that would say what happened next. The 488 records that
// predate this shape are unanswerable for exactly that reason, which is why the fields below
// are asserted rather than assumed. `tools/ledger/injection-precision.mjs` is the consumer.

/** Facts built for one query, with a controlled number of query tokens in each. */
async function seedScored(store, facts) {
  const { Memory } = await import(join(MEMORY_DIST, 'component.js'));
  const m = new Memory(store);
  for (const [name, description] of facts) {
    const outcome = m.saveOutcome('project', name, description, 'body');
    assert.equal(outcome.status, 'saved', `fixture fact ${name} must save: ${outcome.reply}`);
  }
}

function injectRecord(home) {
  const recs = hookLog(home, 'UserPromptSubmit').filter((r) => r.action === 'inject');
  assert.equal(recs.length, 1, 'exactly one injection was made');
  return recs[0];
}

test('the injection record names WHICH facts were injected and at what score', async () => {
  const cwd = newCwd();
  const home = newHome();
  // Query tokens: {the, deploy, flag, ships, tonight}. `pinned` shares deploy+flag+ships = 3,
  // `middling` shares deploy+flag = 2, `thin` shares deploy = 1. Distinct on purpose: a score
  // this file merely copied out of the reply would not be able to tell them apart.
  await seedScored(join(cwd, '.bantamkit', 'memory'), [
    ['pinned', 'deploy flag ships wombat wombat'],
    ['middling', 'deploy flag narwhal narwhal narwhal'],
    ['thin', 'deploy pangolin pangolin pangolin pangolin'],
  ]);
  const r = runHook({ hook_event_name: 'UserPromptSubmit', prompt: 'the deploy flag ships tonight' }, { cwd, home });
  assert.equal(r.status, 0, r.stderr);

  const rec = injectRecord(home);
  assert.deepEqual(rec.injected.map((i) => i.name), ['pinned', 'middling', 'thin']);
  assert.deepEqual(rec.injected.map((i) => i.score), [3, 2, 1],
    'the score is |tokens(name + " " + description) ∩ tokens(prompt)|, the store\'s own formula');
  assert.deepEqual(rec.injected.map((i) => i.layer), ['project', 'project', 'project']);
  assert.deepEqual(rec.injected.map((i) => i.type), ['project', 'project', 'project']);
  assert.equal(rec.session, 'probe-session', 'without this the record joins to no transcript');

  // The scores must EXPLAIN the order the store returned, not merely sit beside it. The sort
  // key is `(-score, name)`, so a logged score that disagreed with the ranking would be a
  // number about some other computation.
  const scores = rec.injected.map((i) => i.score);
  assert.deepEqual(scores, [...scores].sort((a, b) => b - a),
    'the store ranks by descending score; a logged score that does not is not that score');
});

test('an injection leaves every fact file byte- and mtime-identical; the explicit path still stamps', async () => {
  // AN INJECTION IS NOT A RECALL (job64, J64-1). Until this job the arm went through
  // `Memory.recallOutcome` with the component's default `stamp`, so every automatic
  // injection dated up to three facts `last_recalled: <today>` and rewrote their files — 25
  // of 42 facts in one real store carried one day's date, and every rule keyed on that field
  // (compaction's stalest-first, the SessionStart drop rule, the Stop dream's `size + mtimeMs`
  // fingerprint) was reading injection traffic. The control at the end is the explicit path
  // on the SAME bed, which must still stamp: without it a bed whose recall never reached the
  // file would pass for the wrong reason.
  const cwd = newCwd();
  const home = newHome();
  const store = join(cwd, '.bantamkit', 'memory');
  await seedScored(store, [
    ['pinned', 'deploy flag ships wombat wombat'],
    ['unrelated', 'a fact sharing no token with that prompt'],
  ]);
  const state = () => {
    const out = {};
    for (const n of factNames(store)) {
      const p = join(store, 'facts', n);
      out[n] = { bytes: readFileSync(p, 'utf8'), mtimeNs: String(statSync(p, { bigint: true }).mtimeNs) };
    }
    return out;
  };
  const before = state();
  assert.match(before['pinned.md'].bytes, /^last_recalled: null$/m);

  const r = runHook({ hook_event_name: 'UserPromptSubmit', prompt: 'the deploy flag ships tonight' }, { cwd, home });
  assert.equal(r.status, 0, r.stderr);
  const rec = injectRecord(home);
  assert.equal(rec.hits, 1, 'the arm must have READ the store');
  assert.match(r.stdout, /\[pinned\]/);
  assert.deepEqual(state(), before, 'an injection rewrote a fact file, or moved its mtime');

  // CONTROL: the explicit path, on the same bed, still stamps — and only the hit.
  const { Memory } = await import(join(MEMORY_DIST, 'component.js'));
  new Memory(store).recall('the deploy flag ships tonight');
  const after = state();
  assert.match(after['pinned.md'].bytes, /^last_recalled: '\d{4}-\d{2}-\d{2}'$/m);
  assert.notDeepEqual(after['pinned.md'], before['pinned.md']);
  assert.deepEqual(after['unrelated.md'], before['unrelated.md']);
});

test('no prompt text reaches the log — a digest, two sizes, and a closed field set', async () => {
  const cwd = newCwd();
  const home = newHome();
  await seedScored(join(cwd, '.bantamkit', 'memory'), [['pinned', 'deploy flag ships wombat wombat']]);
  // A nonce no fact contains, so anything that echoed the prompt would carry it. The rest of
  // the prompt is fact vocabulary, so the injection still fires.
  const nonce = 'zqxjkvw7788nonce';
  const prompt = `the deploy flag ships tonight ${nonce}`;
  const r = runHook({ hook_event_name: 'UserPromptSubmit', prompt }, { cwd, home });
  assert.equal(r.status, 0, r.stderr);

  const raw = readFileSync(join(home, '.bantamkit', 'hooks', 'hook-log.jsonl'), 'utf8');
  assert.ok(!raw.includes(nonce), 'no substring of the prompt may reach the log');
  assert.ok(!raw.includes(prompt), 'and certainly not the whole prompt');

  const rec = injectRecord(home);
  assert.equal(rec.prompt.sha256, createHash('sha256').update(prompt, 'utf8').digest('hex'),
    'the digest is of the real prompt — otherwise this test would pass on a record that ignored it');
  assert.equal(rec.prompt.chars, prompt.length);
  assert.equal(rec.prompt.bytes, Buffer.byteLength(prompt));
  assert.deepEqual(Object.keys(rec.prompt).sort(), ['bytes', 'chars', 'sha256'],
    'the prompt object is CLOSED: a field added here is a field that could carry text');
  // `suppressed` joined the set 2026-09-25 (job64, J64-2): fact NAMES this context was already
  // shown and was not shown again — the same strings `injected[].name` already carries.
  assert.deepEqual(Object.keys(rec).sort(),
    ['action', 'bytes', 'dropped', 'event', 'hits', 'injected', 'ms', 'prompt', 'session', 'source', 'suppressed', 'ts'].sort(),
    'the record is closed too — every string field here is ours, none is the user\'s');
  for (const inj of rec.injected) {
    assert.deepEqual(Object.keys(inj).sort(), ['layer', 'name', 'score', 'type']);
  }
});

test('a header the byte cap dropped is NOT logged as injected', async () => {
  const cwd = newCwd();
  const home = newHome();
  // Three matching facts whose headers cannot all fit PROMPT_INJECT_MAX = 700 B. Observed on
  // the real log the day this shipped: `dropped: 1` on both instrumented records, so a `hits`
  // of 3 was overstating what reached the model by a third. "Was an INJECTED name later used"
  // is unanswerable if a name the model never saw is counted as injected.
  const filler = (w) => `${w} `.repeat(40).trim();
  await seedScored(join(cwd, '.bantamkit', 'memory'), [
    ['bulky-alpha', `deploy flag ships ${filler('wombat')}`],
    ['bulky-bravo', `deploy flag ${filler('narwhal')}`],
    ['bulky-charlie', `deploy ${filler('pangolin')}`],
  ]);
  const r = runHook({ hook_event_name: 'UserPromptSubmit', prompt: 'the deploy flag ships tonight' }, { cwd, home });
  assert.equal(r.status, 0, r.stderr);

  const rec = injectRecord(home);
  const ctx = JSON.parse(r.stdout).hookSpecificOutput.additionalContext;
  assert.equal(rec.hits, 3, 'three headers were picked');
  assert.ok(rec.injected.length < 3, 'but they cannot all fit 700 B — the fixture is sized so the cap bites');
  assert.equal(rec.dropped, rec.hits - rec.injected.length);
  for (const inj of rec.injected) {
    assert.ok(ctx.includes(`[${inj.name}]`), `${inj.name} is logged as injected and must be in what left the process`);
  }
  for (const name of ['bulky-alpha', 'bulky-bravo', 'bulky-charlie']) {
    if (rec.injected.some((i) => i.name === name)) continue;
    assert.ok(!ctx.includes(`[${name}]`), `${name} was dropped by the cap and must not appear in the context`);
  }
});

// ------------------- what this context was shown is not shown again (job64, J64-2)
//
// Measured 2026-09-25 over a week of the real log: 333 of 598 injections repeated a name
// injected earlier in the same session, because the arm never read the session ledger. The
// bed is the conformance suite's `inject-dedupe` bed, so a number pinned here is the number
// pinned there. Every test below went RED with the seen-set forced empty on this side
// (`const seen = {}` in `userPromptSubmit`); counts in `.shiftwork/notes-job64/J64-2.md`.

const DEDUPE_FACTS = [
  ['project', 'deployment-rollback', 'the deployment path rollback procedure for the staging cluster'],
  ['project', 'staging-cluster-notes', 'wiring notes kept about the staging cluster nodes'],
  ['project', 'rollback-runbook', 'runbook steps when a rollback of the deployment is needed'],
  ['reference', 'unrelated-alpha', 'nothing shared here at all'],
  ['reference', 'unrelated-beta', 'still nothing in common with anything'],
];
/** Hits the three `deployment`/`rollback`/`staging` facts, in this order (scores 8, 3, 3). */
const PROMPT_A = 'deployment path rollback procedure for the staging cluster';
/** Hits `unrelated-alpha` first and then two of A's three — the MIXED case after A. */
const PROMPT_C = 'nothing shared here at all about the staging cluster';
const A_NAMES = ['deployment-rollback', 'rollback-runbook', 'staging-cluster-notes'];

async function dedupeBed() {
  const cwd = newCwd();
  const home = newHome();
  const { Memory } = await import(join(MEMORY_DIST, 'component.js'));
  const m = new Memory(join(cwd, '.bantamkit', 'memory'));
  for (const [type, name, description] of DEDUPE_FACTS) {
    const o = m.saveOutcome(type, name, description, 'body');
    assert.equal(o.status, 'saved', `fixture fact ${name} must save: ${o.reply}`);
  }
  return { cwd, home };
}
function promptIn(bed, text, { session = 'probe-session', transcript = '/t/main.jsonl' } = {}) {
  const r = runHook(
    { hook_event_name: 'UserPromptSubmit', prompt: text, transcript_path: transcript, session_id: session },
    bed,
  );
  assert.equal(r.status, 0, r.stderr);
  return r;
}
const promptRecords = (home) => hookLog(home, 'UserPromptSubmit');
const ledgerOf = (home, session = 'probe-session') =>
  JSON.parse(readFileSync(join(home, '.bantamkit', 'hooks', `ledger-${session}.json`), 'utf8'));

test('(a) a name this context was shown is not injected again, and the record says why', async () => {
  const bed = await dedupeBed();
  const first = promptIn(bed, PROMPT_A);
  const second = promptIn(bed, PROMPT_A);

  assert.notEqual(first.stdout, '');
  assert.equal(second.stdout, '', 'every picked header was already in the window');
  const [one, two] = promptRecords(bed.home);
  assert.equal(one.action, 'inject');
  assert.deepEqual(one.suppressed, []);
  assert.equal(two.action, 'suppress');
  assert.deepEqual(two.suppressed, A_NAMES);
  assert.equal(two.hits, 3);
  assert.equal(two.session, 'probe-session');
  assert.deepEqual(Object.keys(two.prompt).sort(), ['bytes', 'chars', 'sha256'], 'the fingerprint, never text');
  const ledger = ledgerOf(bed.home);
  assert.deepEqual(Object.keys(ledger.injected['/t/main.jsonl']), A_NAMES, 'seen = what LEFT, by name');
  assert.deepEqual(ledger.reads, {}, 'the read ledger is untouched by an injection');
});

test('(b) a different session is not suppressed by what another was shown', async () => {
  const bed = await dedupeBed();
  promptIn(bed, PROMPT_A, { session: 'one', transcript: '/t/one.jsonl' });
  const other = promptIn(bed, PROMPT_A, { session: 'two', transcript: '/t/two.jsonl' });

  assert.notEqual(other.stdout, '');
  assert.deepEqual(promptRecords(bed.home).map((r) => r.action), ['inject', 'inject']);
  assert.deepEqual(Object.keys(ledgerOf(bed.home, 'two').injected), ['/t/two.jsonl']);
});

test('(c) a compaction forgets what was shown, so it is injected again', async () => {
  // The suppress in the middle is the control: a hook that never suppressed would pass the
  // rest of this test.
  const bed = await dedupeBed();
  promptIn(bed, PROMPT_A);
  assert.equal(promptIn(bed, PROMPT_A).stdout, '');
  runHook({ hook_event_name: 'PostCompact' }, bed);
  const again = promptIn(bed, PROMPT_A);

  assert.notEqual(again.stdout, '');
  assert.deepEqual(promptRecords(bed.home).map((r) => r.action), ['inject', 'suppress', 'inject']);
});

test('(d) only the unseen headers are injected when some were shown before', async () => {
  const bed = await dedupeBed();
  promptIn(bed, PROMPT_A);
  const mixed = promptIn(bed, PROMPT_C);

  const ctx = JSON.parse(mixed.stdout).hookSpecificOutput.additionalContext;
  assert.ok(ctx.includes('[unrelated-alpha]'));
  for (const name of A_NAMES) assert.ok(!ctx.includes(`[${name}]`), `${name} was already in the window`);
  const rec = promptRecords(bed.home)[1];
  assert.equal(rec.action, 'inject');
  assert.deepEqual(rec.injected.map((x) => x.name), ['unrelated-alpha']);
  assert.deepEqual(rec.suppressed, ['staging-cluster-notes', 'deployment-rollback']);
  assert.equal(rec.hits, 3, 'the store was still asked for three; two were withheld, not refilled');
  assert.equal(rec.dropped, 0);
  assert.equal(rec.hits, rec.injected.length + rec.dropped + rec.suppressed.length);
  const seen = Object.keys(ledgerOf(bed.home).injected['/t/main.jsonl']).sort();
  assert.deepEqual(seen, [...A_NAMES, 'unrelated-alpha'].sort(), 'what just left is seen now too');
});

test('(e) clear forgets what was shown and startup does not; clear leaves the reads alone', async () => {
  const bed = await dedupeBed();
  const target = join(bed.cwd, 'a.txt');
  writeFileSync(target, 'alpha');
  runHook(
    { hook_event_name: 'PreToolUse', tool_name: 'Read', transcript_path: '/t/main.jsonl', tool_input: { file_path: target } },
    bed,
  );
  promptIn(bed, PROMPT_A);
  runHook({ hook_event_name: 'SessionStart', source: 'startup' }, bed);
  assert.equal(promptIn(bed, PROMPT_A).stdout, '', 'startup is not a rebuilt window');
  runHook({ hook_event_name: 'SessionStart', source: 'clear' }, bed);

  const afterClear = ledgerOf(bed.home);
  assert.ok(!('injected' in afterClear));
  assert.equal(Object.keys(afterClear.reads).length, 1, 'the reads are the read ledger\'s business, not clear\'s');
  assert.notEqual(promptIn(bed, PROMPT_A).stdout, '');
  assert.deepEqual(promptRecords(bed.home).map((r) => r.action), ['inject', 'suppress', 'inject']);
});

test('clear with no ledger creates none', () => {
  const r = runHook({ hook_event_name: 'SessionStart', source: 'clear' });
  assert.equal(r.status, 0, r.stderr);
  assert.ok(!existsSync(join(r.home, '.bantamkit', 'hooks', 'ledger-probe-session.json')));
});

test('(f) a subagent transcript keeps its own seen-set in the parent\'s ledger', async () => {
  // Same `session_id`, so the same FILE (J64-0, Q3 step 11); its own window, so its own
  // key — like `reads`. And the parent is still suppressed afterwards.
  const bed = await dedupeBed();
  promptIn(bed, PROMPT_A, { transcript: '/t/parent.jsonl' });
  const child = promptIn(bed, PROMPT_A, { transcript: '/t/child.jsonl' });
  const parentAgain = promptIn(bed, PROMPT_A, { transcript: '/t/parent.jsonl' });

  assert.notEqual(child.stdout, '', 'the subagent\'s window never held the parent\'s headers');
  assert.equal(parentAgain.stdout, '');
  assert.deepEqual(promptRecords(bed.home).map((r) => r.action), ['inject', 'inject', 'suppress']);
  assert.deepEqual(Object.keys(ledgerOf(bed.home).injected).sort(), ['/t/child.jsonl', '/t/parent.jsonl']);
});

// ------------------------------------------------------- Stop -> dream (J46-14, row 5)
//
// `memory_dream`'s MECHANISM shipped in job45; its TRIGGER did not, and until this change
// the string `dream` did not occur in `tools/hooks/bantamkit-hook.mjs` at all. The arm under
// test fires the consolidation from `Stop` — NOT from the `SessionEnd` the row's spec named,
// because the user's registration does not carry `SessionEnd` and an arm there would be
// inert. See the arm's own header for the re-derived event list.
//
// THESE TESTS ASSERT WHAT THE PASS DID, NOT THAT AN ARM RAN. J46-6 measured 28 tests in this
// file matching on `action` alone, which let the hook's real arithmetic move with nothing
// red; and its own first repair of that was itself vacuous because the fields it checked were
// computed before the spawn. So every assertion below is on the consolidation's OUTCOME —
// `status`, `merged`, `changes` — and, where it matters, on the store on disk.

/** A fact file in `<root>/facts`, in the shape `MemoryStore` writes. */
function seedFact(root, name, { description, body, type = 'feedback', created = '2026-08-01' }) {
  const facts = join(root, 'facts');
  mkdirSync(facts, { recursive: true });
  writeFileSync(
    join(facts, `${name}.md`),
    `---\nname: ${name}\ndescription: ${description}\ntype: ${type}\ncreated: '${created}'\nlast_recalled: '${created}'\nlinks: []\n---\n\n${body}\n`,
  );
}

/**
 * A project layer and a profile layer sharing `shared-ruling`, with DIFFERENT bodies so the
 * merge is a real union and not the trivial identical case.
 */
function seedTwoLayers({ home, cwd }) {
  const project = join(cwd, '.bantamkit', 'memory');
  const profile = join(home, '.bantamkit', 'memory');
  seedFact(project, 'shared-ruling', {
    description: 'the project half of a ruling that exists in both layers',
    body: 'The project copy says the gate is a conformance case.',
  });
  seedFact(profile, 'shared-ruling', {
    description: 'the profile half of a ruling that exists in both layers',
    body: 'The profile copy says a ruling costs a divergence row.',
  });
  seedFact(project, 'project-only-fact', {
    description: 'a fact only the project layer holds',
    body: 'Nothing in the profile layer answers to this name.',
  });
  seedFact(profile, 'profile-only-fact', {
    description: 'a fact only the profile layer holds',
    body: 'Nothing in the project layer answers to this name.',
  });
  return { project, profile };
}

function stopPayload() {
  return { hook_event_name: 'Stop', transcript_path: join(scratch, 'transcript.jsonl') };
}

/** Every record this arm wrote, in order. `action` is one of dream-preview / dream-skip / dream-failed. */
function dreamRecords(home) {
  return hookLog(home, 'Stop').filter((r) => String(r.action).startsWith('dream'));
}

function factNames(root) {
  try {
    return readdirSync(join(root, 'facts')).filter((n) => n.endsWith('.md')).sort();
  } catch { return []; }
}

/** Every fact in `<root>/facts`, name -> bytes, so "still live" means BYTE-IDENTICAL and not
 *  merely "a file of that name still exists" (a union rewrite keeps the name and moves the bytes). */
function factBytes(root) {
  const out = {};
  for (const n of factNames(root)) out[n] = readFileSync(join(root, 'facts', n), 'utf8');
  return out;
}

// THE RULING OF 2026-09-12 (J50-2A): THE AUTOMATIC TRIGGER NEVER WRITES.
//
// J45 bounded the machine-wide cost of the cross-layer merge by defaulting `dry_run` to
// TRUE — a real merge was something somebody asked for. J46-14 wired the dream to `Stop`
// with `dry_run=false`, and that mitigation stopped existing: every session ending inside a
// project whose store shares a name with the profile store silently archived the profile
// copy. Measured on the user's machine: 14 of 20 profile facts in `archive/`, and a restore
// of 4 consumed again at the very next Stop.
//
// The property, stated as the test asserts it: after any number of Stops the set of live
// facts in EVERY store is exactly what it was before, byte for byte, and nothing is archived.
// The Stop dream still RUNS — it previews, and the log says what it WOULD merge — but a real
// merge is a deliberate `memory_dream` call and nothing else.
test('Stop never writes: a duplicate the two layers share is still live in BOTH after the dream', () => {
  const home = newHome(); const cwd = newCwd();
  const { project, profile } = seedTwoLayers({ home, cwd });
  writeFileSync(join(scratch, 'transcript.jsonl'), '{"type":"tool_use"}\n');
  const projectBefore = factBytes(project);
  const profileBefore = factBytes(profile);
  assert.ok('shared-ruling.md' in projectBefore && 'shared-ruling.md' in profileBefore, 'the bed shares a name');

  // Three Stops, not one: the first is the pass that used to write, and the two after it are
  // the gate's own skips — a trigger that re-armed on its own dry run would write on the second.
  for (let i = 0; i < 3; i++) {
    const r = runHook(stopPayload(), { home, cwd });
    assert.equal(r.status, 0, r.stderr);
  }

  assert.deepEqual(factBytes(project), projectBefore, 'the project layer is byte-identical');
  assert.deepEqual(factBytes(profile), profileBefore, 'the profile layer is byte-identical: the duplicate is NOT consumed');
  assert.equal(existsSync(join(profile, 'archive')), false, 'nothing was archived out of the profile store');
  assert.equal(existsSync(join(project, 'archive')), false, 'nothing was archived out of the project store');

  // …and the early-warning value is kept: the pass ran, and it said what it would do.
  const [rec] = dreamRecords(home);
  assert.equal(rec.action, 'dream-preview', 'a dry run is a different action, not a `dream` with a flag');
  assert.equal(rec.dryRun, true);
  assert.equal(rec.status, 'previewed');
  assert.equal(rec.wouldMerge, 1, 'exactly the one name both layers hold');
  assert.equal(rec.wouldConsume, 1);
  assert.equal(rec.merged, undefined, 'no field a reader could mistake for a count of merges that happened');
  assert.equal(rec.consumed, undefined);
});

// Until J50-2A this test was "Stop consolidates the duplicate the two layers share, and
// reports what it merged", and it asserted the profile copy GONE from disk. That was the
// behaviour the user ruled out on 2026-09-12; the test above pins the ruling, and this one
// keeps what J46-6 wanted from the original — the OUTCOME fields are the pass's real
// arithmetic, read off the child's stdout, not computed before the spawn.
test('Stop previews the duplicate the two layers share, and reports what it WOULD merge', () => {
  const home = newHome(); const cwd = newCwd();
  const { project, profile } = seedTwoLayers({ home, cwd });
  writeFileSync(join(scratch, 'transcript.jsonl'), '{"type":"tool_use"}\n');

  assert.deepEqual(factNames(project), ['project-only-fact.md', 'shared-ruling.md']);
  assert.deepEqual(factNames(profile), ['profile-only-fact.md', 'shared-ruling.md']);

  const r = runHook(stopPayload(), { home, cwd });
  assert.equal(r.status, 0, r.stderr);

  const [rec] = dreamRecords(home);
  // The OUTCOME, not merely that the arm ran.
  assert.equal(rec.action, 'dream-preview');
  assert.equal(rec.dryRun, true);
  assert.equal(rec.status, 'previewed');
  assert.equal(rec.wouldMerge, 1, 'exactly the one name both layers hold');
  assert.equal(rec.wouldConsume, 1);
  assert.ok(rec.changes >= 1, `changes should count the merge it would make, got ${rec.changes}`);
  assert.equal(rec.storeMoved, false, 'the fingerprint after the pass is the fingerprint before it');
  assert.ok(rec.indexProjected >= rec.indexBefore, 'a union only ever grows the project index');

  // …and the store on disk did NOT move: both copies are still where they were, and the
  // project copy holds ONLY its own claim.
  assert.deepEqual(factNames(profile), ['profile-only-fact.md', 'shared-ruling.md'], 'the profile duplicate is NOT consumed');
  assert.deepEqual(factNames(project), ['project-only-fact.md', 'shared-ruling.md']);
  const kept = readFileSync(join(project, 'facts', 'shared-ruling.md'), 'utf8');
  assert.match(kept, /the gate is a conformance case/, 'the project claim is untouched');
  assert.doesNotMatch(kept, /a ruling costs a divergence row/, 'the profile claim was NOT unioned in');
});

test('an unchanged store does not dream a second time, and the skip is cheap', () => {
  const home = newHome(); const cwd = newCwd();
  seedTwoLayers({ home, cwd });
  writeFileSync(join(scratch, 'transcript.jsonl'), '{"type":"tool_use"}\n');

  runHook(stopPayload(), { home, cwd });
  runHook(stopPayload(), { home, cwd });
  runHook(stopPayload(), { home, cwd });

  const records = dreamRecords(home);
  assert.equal(records.length, 3, 'the arm reports on every Stop');
  assert.equal(records.filter((r) => r.action === 'dream-preview').length, 1,
    'the preview itself runs exactly once for one change to the store — a dry run advances the marker');
  for (const skipped of records.slice(1)) {
    assert.equal(skipped.action, 'dream-skip');
    assert.equal(skipped.reason, 'unchanged');
  }
});

// job64 / J64-3. Every recall rewrites `last_recalled:` and the mtime, and until this unit the
// fingerprint was `name + size + mtimeMs`, so a session of recalls re-armed the preview on
// every Stop (measured: 103 of 236 previews in a week said the identical `wouldMerge 14`).
// Size is not a usable signal either: J64-0 measured a same-day re-stamp moving the mtime
// ALONE. So the fingerprint reads content with that one line left out. The three (a) steps
// are checked to have really rewritten the file, or a skip would prove nothing. MUTATION
// (2026-09-25): the stat fields put back on both sides turn this red at S2; count in
// `.shiftwork/notes-job64/J64-3.md`.
test('re-dating a fact does not re-arm the dream gate, and a content change does', async () => {
  const home = newHome(); const cwd = newCwd();
  const { project } = seedTwoLayers({ home, cwd });
  writeFileSync(join(scratch, 'transcript.jsonl'), '{"type":"tool_use"}\n');
  const { Memory } = await import(join(MEMORY_DIST, 'component.js'));
  const m = new Memory(project, { today: () => '2026-09-25' });
  m.saveOutcome('project', 'recalled-often', 'the fact the operator recalls every turn', 'body');
  const fact = join(project, 'facts', 'recalled-often.md');
  const fingerprint = () => JSON.parse(readFileSync(join(home, '.bantamkit', 'hooks', 'dream-state.json'), 'utf8')).fingerprint;
  const actions = () => dreamRecords(home).map((r) => r.action + (r.reason ? `/${r.reason}` : ''));

  runHook(stopPayload(), { home, cwd }); // S1: the first look previews
  const fp1 = fingerprint();

  // (a1) an explicit recall dates the fact: null -> today, bytes AND mtime move.
  const bytesBefore = readFileSync(fact, 'utf8'); const mtimeBefore = statSync(fact).mtimeMs;
  assert.match(m.recall('operator recalls every turn'), /recalled-often/);
  assert.notEqual(readFileSync(fact, 'utf8'), bytesBefore, 'the recall rewrote the file');
  assert.notEqual(statSync(fact).mtimeMs, mtimeBefore, 'the recall moved the mtime');
  assert.match(readFileSync(fact, 'utf8'), /^last_recalled: '2026-09-25'$/m, 'the recall dated it');
  runHook(stopPayload(), { home, cwd }); // S2
  // (a2) the same line re-dated to another day — what tomorrow's recall writes.
  writeFileSync(fact, readFileSync(fact, 'utf8').replace(/^last_recalled: .*$/m, "last_recalled: '2020-01-01'"));
  runHook(stopPayload(), { home, cwd }); // S3
  // (a3) the mtime alone — a same-day re-stamp (J64-0 Q4).
  const later = new Date(statSync(fact).mtimeMs + 1000);
  utimesSync(fact, later, later);
  runHook(stopPayload(), { home, cwd }); // S4
  assert.equal(fingerprint(), fp1, 'three re-datings, one fingerprint');

  // (b) a body edit through the store (same name = update)
  m.saveOutcome('project', 'recalled-often', 'the fact the operator recalls every turn', 'a new body');
  assert.match(readFileSync(fact, 'utf8'), /a new body/);
  runHook(stopPayload(), { home, cwd }); // S5
  const fp5 = fingerprint();
  assert.notEqual(fp5, fp1, 'a body edit is a change');
  // (c) a fact added
  seedFact(project, 'brand-new', { description: 'written after the last look', body: 'new.' });
  runHook(stopPayload(), { home, cwd }); // S6
  assert.notEqual(fingerprint(), fp5, 'a new fact is a change');

  assert.deepEqual(actions(), [
    'dream-preview',
    'dream-skip/unchanged',
    'dream-skip/unchanged',
    'dream-skip/unchanged',
    'dream-preview',
    'dream-preview',
  ]);
});

test('a change to either layer re-arms the gate, and the second preview reports the duplicate again', () => {
  const home = newHome(); const cwd = newCwd();
  const { project, profile } = seedTwoLayers({ home, cwd });
  writeFileSync(join(scratch, 'transcript.jsonl'), '{"type":"tool_use"}\n');

  runHook(stopPayload(), { home, cwd });
  const after = readFileSync(join(project, 'facts', 'shared-ruling.md'), 'utf8');

  // A save in the PROFILE layer — the machine-wide one another project's session can touch.
  seedFact(profile, 'a-new-profile-fact', { description: 'written after the first dream', body: 'new.' });
  runHook(stopPayload(), { home, cwd });

  const records = dreamRecords(home);
  const ran = records.filter((r) => r.action === 'dream-preview');
  assert.equal(ran.length, 2, 'the change re-armed the gate');
  // THE ACCEPTED COST OF THE RULING, PINNED: nothing consumed the duplicate, so the second
  // preview finds it again. Before J50-2A this pass reported `nothing-to-consolidate` because
  // the first one had archived the profile copy.
  assert.equal(ran[1].status, 'previewed', 'the duplicate accumulates until somebody asks');
  assert.equal(ran[1].wouldMerge, 1);
  assert.equal(ran[1].storeMoved, false);
  assert.equal(readFileSync(join(project, 'facts', 'shared-ruling.md'), 'utf8'), after,
    'the project fact is byte-identical after a second pass');
  assert.deepEqual(factNames(profile), ['a-new-profile-fact.md', 'profile-only-fact.md', 'shared-ruling.md']);
});

test('a real merge is a deliberate call, and it re-arms the gate by moving a file', () => {
  const home = newHome(); const cwd = newCwd();
  const { project, profile } = seedTwoLayers({ home, cwd });
  writeFileSync(join(scratch, 'transcript.jsonl'), '{"type":"tool_use"}\n');

  runHook(stopPayload(), { home, cwd });
  assert.equal(dreamRecords(home)[0].status, 'previewed');

  // What `memory_dream` with `dry_run=false` does — the ONE caller allowed to write — run in
  // a child from the test's own HOME/cwd, exactly as the hook spawns its preview.
  const script = `(async () => {
    const { Memory } = await import(${JSON.stringify(join(packageRoot, 'dist', 'memory', 'component.js'))});
    const o = Memory.layered(process.argv[1]).dreamOutcome(false);
    process.stdout.write(JSON.stringify({ status: o.status, consumed: o.consumed }));
  })().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });`;
  const merge = spawnSync(process.execPath, ['-e', script, cwd], { encoding: 'utf8', env: { ...process.env, HOME: home, USERPROFILE: home } });
  assert.equal(merge.status, 0, merge.stderr);
  assert.deepEqual(JSON.parse(merge.stdout), { status: 'consolidated', consumed: 1 });
  assert.deepEqual(factNames(profile), ['profile-only-fact.md'], 'the deliberate call consumed the duplicate');
  const mergedBytes = readFileSync(join(project, 'facts', 'shared-ruling.md'), 'utf8');
  assert.match(mergedBytes, /a ruling costs a divergence row/, 'the deliberate merge unioned the profile claim in');

  // The move re-armed the gate on its own: the next Stop previews a clean store, and touches
  // nothing the deliberate call wrote.
  runHook(stopPayload(), { home, cwd });
  const ran = dreamRecords(home).filter((r) => r.action === 'dream-preview');
  assert.equal(ran.length, 2, 'the deliberate merge re-armed the gate');
  assert.equal(ran[1].status, 'nothing-to-consolidate');
  assert.equal(ran[1].wouldMerge, 0);
  assert.equal(ran[1].storeMoved, false);
  assert.equal(readFileSync(join(project, 'facts', 'shared-ruling.md'), 'utf8'), mergedBytes,
    'the preview after a deliberate merge leaves its result byte-identical');
});

// The two ways this arm can fail are DIFFERENT CODE PATHS and both are covered: the project
// store decides whether the arm can resolve a store at all (in-process, before any spawn),
// and the profile store is only ever read by the CHILD. Breaking the project store therefore
// exercises `unresolved-store` and breaking the profile store exercises `dream-failed` —
// a single "broken store" test would have proved only whichever one it happened to hit.
test('a project store that cannot be resolved is logged and skipped, not thrown', () => {
  const home = newHome(); const cwd = newCwd();
  const { project } = seedTwoLayers({ home, cwd });
  writeFileSync(join(scratch, 'transcript.jsonl'), '{"type":"tool_use"}\n');
  rmSync(join(project, 'facts'), { recursive: true, force: true });
  writeFileSync(join(project, 'facts'), 'not a directory');

  const r = runHook(stopPayload(), { home, cwd });
  assert.equal(r.status, 0, 'an unresolvable store must not fail the hook');
  assert.ok(hostWouldAccept(r.stdout).accepted, hostWouldAccept(r.stdout).why);

  const [rec] = dreamRecords(home);
  assert.equal(rec.action, 'dream-skip');
  assert.equal(rec.reason, 'unresolved-store');
  assert.ok(rec.error && rec.error.length > 0, 'the reason is reported, not swallowed silently');
  assert.equal(existsSync(join(home, '.bantamkit', 'hooks', 'dream-state.json')), false);
});

test('a pass that fails in the child is logged, does not throw, and does not record the fingerprint', () => {
  const home = newHome(); const cwd = newCwd();
  const { profile } = seedTwoLayers({ home, cwd });
  writeFileSync(join(scratch, 'transcript.jsonl'), '{"type":"tool_use"}\n');
  // The PROFILE layer is read only by the child, so this raises inside the spawned pass.
  rmSync(join(profile, 'facts'), { recursive: true, force: true });
  writeFileSync(join(profile, 'facts'), 'not a directory');

  const r = runHook(stopPayload(), { home, cwd });
  assert.equal(r.status, 0, 'a failing consolidation must not fail the hook');
  assert.ok(hostWouldAccept(r.stdout).accepted, hostWouldAccept(r.stdout).why);

  const [rec] = dreamRecords(home);
  assert.equal(rec.action, 'dream-failed');
  assert.notEqual(rec.exit, 0, 'the child really did fail');
  assert.ok(rec.error && rec.error.length > 0, 'the failure is reported, not swallowed silently');
  // The marker must NOT advance: the next Stop has to try again rather than treat an
  // unconsolidated store as already dreamt.
  assert.equal(existsSync(join(home, '.bantamkit', 'hooks', 'dream-state.json')), false);
});

test('a slow pass is killed by the timeout instead of eating the session', () => {
  const home = newHome(); const cwd = newCwd();
  seedTwoLayers({ home, cwd });
  writeFileSync(join(scratch, 'transcript.jsonl'), '{"type":"tool_use"}\n');

  // A 1 ms bound is shorter than any real pass, so a real child is really killed here — this
  // is the bound doing its job, not a stub standing in for it.
  const r = runHook(stopPayload(), { home, cwd, env: { BANTAMKIT_DREAM_TIMEOUT_MS: '1' } });
  assert.equal(r.status, 0, 'the hook survives a pass it had to kill');
  assert.ok(hostWouldAccept(r.stdout).accepted);

  const [rec] = dreamRecords(home);
  assert.equal(rec.action, 'dream-failed');
  // platform-checked: PORTABLE, and this assertion is the mechanism. `spawnSync` reports a
  // timeout kill as an `ETIMEDOUT` error on every platform, so `timedOut` means the same
  // thing on Windows as here. The POSIX signal name is deliberately NOT asserted: on Windows
  // the kill is `TerminateProcess`, there is no such signal to read, and a test that demanded
  // one would either fail there or have to be skipped — which would leave the timeout bound
  // unproven on the platform this repo is required to support.
  assert.equal(rec.timedOut, true, 'the child was killed by the bound, not merely slow');
  assert.equal(existsSync(join(home, '.bantamkit', 'hooks', 'dream-state.json')), false,
    'a killed pass leaves the gate armed');
});

test('the dream arm never emits, so the Stop nudge stays the only voice on stdout', () => {
  const home = newHome(); const cwd = newCwd();
  seedTwoLayers({ home, cwd });
  // 20+ tool calls and no save: the nudge fires on the same Stop the dream does.
  writeFileSync(join(scratch, 'transcript.jsonl'), '{"type":"tool_use"}\n'.repeat(30));

  const r = runHook(stopPayload(), { home, cwd });
  assert.equal(r.status, 0);
  const out = r.stdout.trim();
  assert.doesNotThrow(() => JSON.parse(out), 'stdout must be ONE JSON object, not two concatenated');
  const parsed = JSON.parse(out);
  assert.equal(parsed.decision, 'block', 'the nudge still owns the answer to the host');
  // …and the dream preview still happened on that same Stop.
  assert.equal(dreamRecords(home)[0].status, 'previewed');
});

// THE REGRESSION THIS ARM CAUSED ONCE, AND MUST NEVER CAUSE AGAIN.
//
// `resolveProjectStore` WALKS UP from the cwd. A session running outside any project
// therefore resolves `~/.bantamkit/memory` — the PROFILE store — as its "project" store, and
// `Memory.layered` binds that one directory as BOTH layers. `dream` then merges the store
// with itself: every fact matches itself by name and the "profile copy" (the same file) is
// archived, emptying `facts/`.
//
// This happened to the user's real profile store on 2026-09-10 while this arm was being
// written, because the live hook registration points at the working-tree file: a real `Stop`
// consolidated 20 of 20 facts into the archive. The tell was `indexBefore == indexAfter`,
// two layers reporting one number because they were one store.
test('a cwd outside any project does not merge the profile store with itself', () => {
  const home = newHome();
  // No `.bantamkit` anywhere above this cwd EXCEPT the one in home: the walk lands on the
  // profile store, which is exactly the shape that emptied the real store.
  const cwd = join(home, 'somewhere', 'deep');
  mkdirSync(cwd, { recursive: true });
  const profile = join(home, '.bantamkit', 'memory');
  seedFact(profile, 'a-profile-fact', { description: 'the only copy there is', body: 'Keep me.' });
  seedFact(profile, 'another-profile-fact', { description: 'also the only copy', body: 'Keep me too.' });
  writeFileSync(join(scratch, 'transcript.jsonl'), '{"type":"tool_use"}\n');

  const r = runHook(stopPayload(), { home, cwd });
  assert.equal(r.status, 0);

  const [rec] = dreamRecords(home);
  assert.equal(rec.action, 'dream-skip');
  assert.equal(rec.reason, 'single-layer', 'the arm must recognise one directory bound twice');

  // The property that actually matters: the facts are STILL THERE and nothing was archived.
  assert.deepEqual(factNames(profile), ['a-profile-fact.md', 'another-profile-fact.md']);
  assert.equal(existsSync(join(profile, 'archive')), false, 'nothing was consumed');
});

// ------------------------------------------------- the census AS-1(a) answered, as a gate
//
// `docs/roadmap-agent-stack.md` AS-1(a) asked for one event stream or the written reason
// there is more than one. The written reason is `docs/eventlog.md`'s "Four streams, not one"
// section, and its load-bearing claim is a CENSUS: these are the streams, there are no
// others. A census in prose goes stale the first time an arm starts writing somewhere new,
// and nothing would say so — which is the whole failure AS-1(a) is about.
//
// So the census is checked against the RUN, not against the source. This fires the hook for
// every event the user's registration actually sends (`docs/hooks.md`), then walks the
// scratch HOME and asks what `.jsonl` files ARE THERE. Grepping the adapter for path
// expressions would pass on a stream that a helper builds and would miss one an import
// writes; the filesystem cannot be talked around.
//
// `.jsonl` and not every file: `dream-state.json` and `ledger-<session>.json` are
// read-modify-write STATE, not append-only streams, and AS-1(a) is about streams. A new
// stream that arrived as `.json` would slip past — noted here rather than guarded, because
// an append log in this project is a `.jsonl` by convention and widening the glob to catch
// the state files would make this test fail on every legitimate change to them.
test('every JSONL stream the hook writes is named in docs/eventlog.md', () => {
  const home = newHome();
  const cwd = newCwd();
  writeFileSync(join(scratch, 'transcript.jsonl'), '{"type":"tool_use"}\n');
  const events = [
    { hook_event_name: 'SessionStart', source: 'startup' },
    { hook_event_name: 'UserPromptSubmit', prompt: 'how does the deploy flag work here' },
    { hook_event_name: 'PreToolUse', tool_name: 'Read', tool_input: { file_path: join(cwd, 'README.md') } },
    { hook_event_name: 'PostToolUse', tool_name: 'Read', tool_input: {}, tool_use_id: 't1' },
    { hook_event_name: 'PreCompact', trigger: 'manual', transcript_path: join(scratch, 'transcript.jsonl'), custom_instructions: null },
    { hook_event_name: 'PostCompact' },
    stopPayload(),
  ];
  writeFileSync(join(cwd, 'README.md'), 'a file for the read ledger\n');
  for (const payload of events) {
    const r = runHook(payload, { home, cwd });
    assert.equal(r.status, 0, `${payload.hook_event_name}: ${r.stderr}`);
  }

  const streams = [];
  const walk = (dir, rel) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      if (e.isDirectory()) walk(join(dir, e.name), `${rel}${e.name}/`);
      else if (e.name.endsWith('.jsonl')) streams.push(`~/${rel}${e.name}`);
    }
  };
  walk(home, '');
  streams.sort();

  // Non-vacuity: a walk that found nothing would pass the loop below without reading a
  // thing. These two are the census as `docs/eventlog.md` prints it; a third that is
  // documented is welcome, an undocumented one is the failure.
  assert.deepEqual(
    streams.filter((s) => s === '~/.bantamkit/hooks/hook-log.jsonl' || s === '~/.claude/tool-metrics/events.jsonl'),
    ['~/.bantamkit/hooks/hook-log.jsonl', '~/.claude/tool-metrics/events.jsonl'],
    'both streams the census names must actually be written by a real run',
  );

  // The census is the TABLE, not the page. A first cut of this test asked whether the path
  // appeared anywhere in `docs/eventlog.md` and a deliberate mutation of the table row left
  // it GREEN, because the same path also sits inside a `wc -lc` line in the census's own
  // reproduce block. That is the identical defect as this unit's checkpoint verify
  // (`grep -q injection docs/eventlog.md`), reproduced by accident: a substring search cannot
  // tell a documented decision from an incidental mention. So this reads the row.
  const rows = readFileSync(join(repoRoot, 'docs', 'eventlog.md'), 'utf8')
    .split('\n')
    .filter((l) => /^\|\s*\d+\s*\|/.test(l))          // `| 2 | **the hook log** | \`path\` | … |`
    .map((l) => l.split('|').map((c) => c.trim()));
  const census = new Set(rows.map((cells) => (cells[3] || '').replace(/^`|`$/g, '')));
  assert.ok(census.size >= 4, `the census table did not parse — found ${census.size} rows, expected 4`);

  for (const stream of streams) {
    assert.ok(census.has(stream),
      `the hook writes ${stream} and the census table in docs/eventlog.md does not list it — `
      + "AS-1(a)'s written answer is now wrong. Add a row naming the question it answers, or stop writing it.");
  }
});
