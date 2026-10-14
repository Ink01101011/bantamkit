/**
 * `bantamkit-mcp --hook`: the hook adapter, reached from the SHIPPED CLI.
 *
 * WHY THIS FILE EXISTS. The adapter worked, and it was unreachable from the product. It lived
 * in `tools/hooks/bantamkit-hook.mjs`, and `tools/` is not in the npm package: measured with
 * `npm pack --dry-run` at 0.35.3, the tarball carries 174 files, `package.json` declares
 * `files: ["dist","assets"]`, and `grep -i hook` over the printed manifest matches NOTHING.
 * So an operator who installed bantamkit the only way it is published — `npx bantamkit-mcp` —
 * had no hook adapter on disk at all, and the registration line `docs/hooks.md` gives could
 * not be written without a checkout. `--hook` is the surface that closes that, and this file
 * is the gate on it.
 *
 * THE CONTRACT, and it is deliberately narrow so that it can be compared across runtimes:
 * one JSON object in on stdin, AT MOST ONE JSON object out on stdout, exit 0 ALWAYS. Every
 * assertion below judges stdout the way the host does and judges the exit code the way the
 * host does — a hook that throws is rendered to the user as an error on their screen, so the
 * "always 0" half is not a nicety.
 *
 * THE TESTS ARE PROCESS-LEVEL ON PURPOSE, for `hooks.test.mjs`'s reason: the PreCompact
 * channel defect shipped because the arm had only ever been READ. These feed `dist/cli.js`
 * a real payload on stdin.
 *
 * NOTHING HERE TOUCHES THE REAL HOME. Every run gets a scratch HOME (so the adapter's ledger
 * and log land in the scratch) and a scratch cwd.
 */
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const CLI = join(packageRoot, 'dist', 'cli.js');

const scratch = mkdtempSync(join(tmpdir(), 'bk-hookflag-'));
after(() => rmSync(scratch, { recursive: true, force: true }));

let n = 0;
function newDir(prefix) {
  const dir = join(scratch, `${prefix}-${n++}`);
  mkdirSync(dir, { recursive: true });
  return dir;
}

/** `bantamkit-mcp --hook` with `payload` on stdin, over a scratch HOME and a scratch cwd. */
function runHook(payload, { home = newDir('home'), cwd = newDir('cwd'), env = {}, input } = {}) {
  const r = spawnSync(process.execPath, [CLI, '--hook'], {
    input: input ?? JSON.stringify({ cwd, session_id: 'probe-session', ...payload }),
    encoding: 'utf8',
    env: { ...process.env, HOME: home, USERPROFILE: home, ...env },
  });
  return { ...r, cwd, home };
}

function runCli(args, env = {}) {
  return spawnSync(process.execPath, [CLI, ...args], {
    encoding: 'utf8',
    input: '',
    env: { ...process.env, ...env },
  });
}

test('directory reads are never ledgered or refused', () => {
  const home = newDir('home');
  const cwd = newDir('cwd');
  const target = join(cwd, 'a.txt');
  writeFileSync(target, 'alpha');
  const payload = file => ({ hook_event_name: 'PreToolUse', tool_name: 'Read', tool_input: { file_path: file } });
  runHook(payload(target), { home, cwd });
  const ledger = join(home, '.bantamkit', 'hooks', 'ledger-probe-session.json');
  const before = readFileSync(ledger, 'utf8');

  for (let attempt = 0; attempt < 2; attempt++) {
    const result = runHook(payload(cwd), { home, cwd });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, '', 'a failed directory read has no reusable content');
    assert.equal(readFileSync(ledger, 'utf8'), before);
  }
});

// ------------------------------------------------------------------ the parser surface

test('--hook is on the parser and in the help table', () => {
  const r = runCli(['-h'], { COLUMNS: '80' });
  assert.equal(r.status, 0);
  assert.equal(r.stderr, '');
  assert.match(r.stdout, /\[--hook\]/, 'the usage line names the flag');
  assert.match(r.stdout, /^ {2}--hook {2,}/m, 'the option table carries a row for it');
});

test('the pinned FIRST usage line is byte-identical at COLUMNS=80', () => {
  // P7 of `.shiftwork/notes-job61/S1-delivery-path.md`: registering after `--index-budget`
  // leaves this line alone. It is pinned in `test/cli-surface.test.mjs`, in the reference's
  // `test_mcpserver.py`, and as a THROWING precondition in `tools/conformance/suites/cli.mjs`,
  // so a flag that moves it turns a differential suite into a re-baselining one.
  const r = runCli(['-h'], { COLUMNS: '80' });
  assert.equal(
    r.stdout.split('\n')[0],
    'usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES]',
  );
});

// ------------------------------------------------------------------- the hook contract

test('SessionStart emits exactly one JSON object and exits 0', () => {
  const r = runHook({ hook_event_name: 'SessionStart', source: 'startup' });
  assert.equal(r.status, 0);
  const parsed = JSON.parse(r.stdout);
  assert.equal(parsed.hookSpecificOutput.hookEventName, 'SessionStart');
  assert.match(parsed.hookSpecificOutput.additionalContext, /\[bantamkit\] Toolbox is live/);
  // AT MOST ONE object: `JSON.parse` of a concatenation of two would have thrown above, and
  // this pins the other half — nothing trailing the object either.
  assert.equal(r.stdout.trim(), r.stdout);
});

test('the adapter logs its decision under the scratch HOME, not the real one', () => {
  const r = runHook({ hook_event_name: 'SessionStart', source: 'startup' });
  const log = join(r.home, '.bantamkit', 'hooks', 'hook-log.jsonl');
  assert.ok(existsSync(log), `expected a hook log at ${log}`);
  const first = JSON.parse(readFileSync(log, 'utf8').trim().split('\n')[0]);
  assert.equal(first.event, 'SessionStart');
  assert.equal(first.source, 'startup');
});

test('a payload that is not JSON writes nothing and still exits 0', () => {
  const r = runHook({}, { input: 'not json' });
  assert.equal(r.status, 0);
  assert.equal(r.stdout, '');
});

test('an event the adapter does not serve writes nothing and exits 0', () => {
  const r = runHook({ hook_event_name: 'WorktreeCreate' });
  assert.equal(r.status, 0);
  assert.equal(r.stdout, '');
  const log = readFileSync(join(r.home, '.bantamkit', 'hooks', 'hook-log.jsonl'), 'utf8');
  assert.match(log, /"action":"ignored"/);
});

test('PreCompact steering is PLAIN text — it never starts with a brace', () => {
  // The host takes stdout that starts with `{` as JSON and rejects it for PreCompact, because
  // its `hookSpecificOutput` union has no `"PreCompact"` member. `hooks.test.mjs` carries the
  // full argument; what belongs here is that the flag reaches the SAME arm.
  const r = runHook({ hook_event_name: 'PreCompact', trigger: 'auto' });
  assert.equal(r.status, 0);
  assert.ok(!r.stdout.startsWith('{'), `PreCompact stdout must not start with {: ${r.stdout.slice(0, 80)}`);
  assert.match(r.stdout, /Preserve verbatim:/);
});

test('--hook consumes stdin, so no argv-shaped payload is needed', () => {
  // The event comes from `hook_event_name` in the payload and from nowhere else: the flag is
  // bare, with no metavar, and a second spelling of the event on the command line would be a
  // second thing to keep in step with the host.
  const r = runCli(['--hook', 'SessionStart']);
  assert.equal(r.status, 2, 'a positional after --hook is an argv error, not a second spelling');
});

// ------------------------------------------------------- PreToolUse Read: the read ledger
// (job65, J65-4). The in-process half of #166, #167 and #190; the conformance `hooks`
// suite's `read-ledger` block is the process half, compared against the reference.

const readPayload = (file, extra = {}) => ({
  hook_event_name: 'PreToolUse',
  tool_name: 'Read',
  transcript_path: '/t/parent.jsonl',
  tool_input: { file_path: file, ...extra },
});
const hookLog = (home) =>
  readFileSync(join(home, '.bantamkit', 'hooks', 'hook-log.jsonl'), 'utf8')
    .split('\n')
    .filter(Boolean)
    .map((l) => JSON.parse(l));
const ledgerOf = (home) => JSON.parse(readFileSync(join(home, '.bantamkit', 'hooks', 'ledger-probe-session.json'), 'utf8'));

test('#166: an unchanged file is refused once, then every identical repeat goes through until an edit', () => {
  // The allowed retry used to write `refused: false` back, which re-armed the gate: six
  // reads went allow, deny, allow, deny, allow, deny while the refusal told the model it
  // "fires only once per unchanged file". RED at 64ae11d: `allow,deny,allow,deny,allow,deny`.
  const home = newDir('home');
  const cwd = newDir('cwd');
  const target = join(cwd, 'a.txt');
  writeFileSync(target, 'alpha');
  const read = () => (runHook(readPayload(target), { home, cwd }).stdout ? 'deny' : 'allow');
  const decisions = Array.from({ length: 6 }, read);
  writeFileSync(target, 'alpha and then some');
  const afterEdit = Array.from({ length: 3 }, read);
  assert.deepEqual(decisions, ['allow', 'deny', 'allow', 'allow', 'allow', 'allow']);
  assert.deepEqual(afterEdit, ['allow', 'deny', 'allow']);
  assert.deepEqual(
    hookLog(home).map((l) => l.action),
    ['record', 'refuse', ...Array(4).fill('allow-after-refuse-or-change'), 'allow-after-refuse-or-change', 'refuse', 'allow-after-refuse-or-change'],
  );
  const [record] = Object.values(ledgerOf(home).reads);
  assert.equal(record.refused, true, 'the refusal stays spent until the signature changes');
  assert.equal(record.count, 9, 'the count is cumulative across signature changes');
});

test('#190: a directory is never ledgered and its retry is never refused', () => {
  // A directory stats fine, so it was ledgered and the second Read refused with "use the
  // content from that earlier read" — content the host never produced, because the first
  // Read failed with EISDIR. RED at 64ae11d: the second run emitted a deny.
  const home = newDir('home');
  const cwd = newDir('cwd');
  const dir = join(cwd, 'sub');
  mkdirSync(dir);
  const first = runHook(readPayload(dir), { home, cwd });
  const second = runHook(readPayload(dir), { home, cwd });
  assert.equal(first.status, 0);
  assert.equal(second.status, 0);
  assert.equal(first.stdout, '');
  assert.equal(second.stdout, '', 'a directory read is never refused');
  const hooks = join(home, '.bantamkit', 'hooks');
  assert.ok(!existsSync(join(hooks, 'ledger-probe-session.json')), 'never ledgered');
  // Like a missing path, nothing is logged either: the arm returns before its log line.
  assert.ok(!existsSync(join(hooks, 'hook-log.jsonl')));
});

test('#167: twenty parallel reads of twenty files lose no ledger entry', async () => {
  // One hook PROCESS per tool call, and a parallel tool block fires them at once: twenty
  // processes each read the ledger, add one entry and write the whole file back, and the
  // last writer wins. Measured at 64ae11d over 20 files: 6 of 20 survived on this side,
  // 16 of 20 on the reference. The read-modify-write now runs under `<ledger>.lock` and
  // writes through a rename, so all 20 land, no lock is left, no temp file either.
  const home = newDir('home');
  const cwd = newDir('cwd');
  const files = Array.from({ length: 20 }, (_, i) => join(cwd, `p${i}.txt`));
  files.forEach((f, i) => writeFileSync(f, `${i}\n`));
  const results = await Promise.all(
    files.map(
      (f) =>
        new Promise((resolve) => {
          const p = spawn(process.execPath, [CLI, '--hook'], { cwd, env: { ...process.env, HOME: home, USERPROFILE: home } });
          let stdout = '';
          p.stdout.on('data', (d) => (stdout += d));
          p.on('close', (status) => resolve({ status, stdout }));
          p.stdin.end(JSON.stringify({ cwd, session_id: 'probe-session', ...readPayload(f) }));
        }),
    ),
  );
  assert.deepEqual(results.map((r) => r.status), Array(20).fill(0));
  assert.deepEqual(results.map((r) => r.stdout), Array(20).fill(''), 'distinct files: nothing is refused');
  assert.equal(Object.keys(ledgerOf(home).reads).length, 20, 'every parallel read is ledgered');
  const hooks = join(home, '.bantamkit', 'hooks');
  assert.ok(!existsSync(join(hooks, 'ledger-probe-session.json.lock')), 'the lock is released');
  assert.deepEqual(readdirSync(hooks).filter((n) => n.endsWith('.tmp')), [], 'no temp file is left');
});
