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
import { mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from 'node:fs';
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
function runHook(payload, { home = newHome(), cwd = newCwd() } = {}) {
  const r = spawnSync(process.execPath, [HOOK], {
    input: JSON.stringify({ cwd, session_id: 'probe-session', ...payload }),
    encoding: 'utf8',
    env: { ...process.env, HOME: home, USERPROFILE: home },
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
  const bad = spawnSync(process.execPath, [HOOK], { input: 'not json', encoding: 'utf8', env: { ...process.env, HOME: newHome() } });
  assert.equal(bad.status, 0);
  assert.equal(bad.stdout, '');
  assert.equal(bad.stderr, '');
});
