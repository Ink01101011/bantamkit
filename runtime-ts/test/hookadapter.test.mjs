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
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
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
