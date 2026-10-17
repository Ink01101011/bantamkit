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
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
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

// ------------------------------------------------- job65, J65-8: #119, #188, #168, #169, #192
// The in-process half; the conformance `hooks` suite's `hook-degrade` block is the process
// half, compared against the reference. Each test names the pre-fix behaviour it was red on.

const factText = (name, description, type = 'project') =>
  `---\nname: ${name}\ndescription: ${description}\ntype: ${type}\ncreated: '2026-10-13'\nlast_recalled: null\nlinks: []\n---\n\nbody of ${name}\n`;
function seedFacts(store, facts) {
  mkdirSync(join(store, 'facts'), { recursive: true });
  for (const [name, description, type] of facts) writeFileSync(join(store, 'facts', `${name}.md`), factText(name, description, type));
  writeFileSync(
    join(store, 'index.md'),
    facts.map(([name, description, type = 'project']) => `- [[${name}]] (${type}) — ${description}\n`).sort().join(''),
  );
}
const contextOf = (r) => JSON.parse(r.stdout).hookSpecificOutput.additionalContext;

test('#119/#188: one broken profile fact costs that file; every block still renders and "1 fact" is singular', () => {
  // RED before job65: SessionStart printed 0 bytes (the profile block threw past the arm), and
  // a one-fact store said "1 facts".
  const home = newDir('home');
  const cwd = newDir('cwd');
  const profile = join(home, '.bantamkit', 'memory');
  seedFacts(profile, [['prof-ok', 'shared words profile fact', 'feedback']]);
  seedFacts(join(cwd, '.bantamkit', 'memory'), [['ok-fact', 'shared words project fact'], ['ok-two', 'release checklist steps']]);
  writeFileSync(join(profile, 'facts', 'broken.md'), '');
  const r = runHook({ hook_event_name: 'SessionStart', source: 'startup' }, { home, cwd });
  assert.equal(r.status, 0);
  const ctx = contextOf(r);
  assert.ok(ctx.includes('[bantamkit profile memory — 1 fact learned across projects]'), ctx);
  assert.ok(ctx.includes('[bantamkit project memory — 2 facts]'), ctx);
  assert.ok(ctx.includes('[[prof-ok]]') && ctx.includes('[[ok-fact]]'));
  assert.ok(ctx.includes('[bantamkit] Toolbox is live'));
  assert.ok(ctx.includes('[1 fact file not read — not a valid fact: broken.md;'), ctx);
  const line = hookLog(home).filter((l) => l.event === 'SessionStart').at(-1);
  assert.deepEqual(line.profileSkipped.map((s) => s.file), ['broken.md']);
  assert.match(line.profileSkipped[0].reason, /^malformed fact file broken\.md/);
});

test('#119: one broken project fact does not silence UserPromptSubmit', () => {
  // RED before job65: 0 bytes and an `error` record.
  const home = newDir('home');
  const cwd = newDir('cwd');
  seedFacts(join(home, '.bantamkit', 'memory'), [['prof-ok', 'shared words profile fact', 'feedback']]);
  const store = join(cwd, '.bantamkit', 'memory');
  seedFacts(store, [['ok-fact', 'shared words project fact']]);
  writeFileSync(join(store, 'facts', 'zz-bad.md'), '---\nname: zz-bad\n');
  const r = runHook({ hook_event_name: 'UserPromptSubmit', prompt: 'shared words fact please' }, { home, cwd });
  assert.equal(r.status, 0);
  const ctx = contextOf(r);
  assert.ok(ctx.includes('[ok-fact]') && ctx.includes('[prof-ok]'), ctx);
  const line = hookLog(home).at(-1);
  assert.equal(line.action, 'inject');
  assert.deepEqual(line.skipped.map((s) => [s.layer, s.file]), [['project', 'zz-bad.md']]);
});

test('#168: an unparseable stdin is logged as its size and digest, never its text', () => {
  // RED before job65: the record carried `raw`, the first 200 characters of the prompt.
  const home = newDir('home');
  const input = '{"hook_event_name":"UserPromptSubmit","prompt":"my secret password is hunter2 and';
  const r = runHook({}, { home, input });
  assert.equal(r.status, 0);
  assert.equal(r.stdout, '');
  const { ts: _ts, ms: _ms, ...rest } = hookLog(home).at(-1);
  assert.deepEqual(rest, {
    event: 'parse-error',
    bytes: Buffer.byteLength(input),
    sha256: createHash('sha256').update(input, 'utf8').digest('hex'),
  });
  assert.ok(!readFileSync(join(home, '.bantamkit', 'hooks', 'hook-log.jsonl'), 'utf8').includes('hunter2'));
});

test('#169: a Read under memory/ is not a save; a Write or MultiEdit there is', () => {
  // RED before job65: the Read set `saved: true` and silenced the nudge.
  const home = newDir('home');
  const cwd = newDir('cwd');
  const toolUse = (name, input = {}) => JSON.stringify({ type: 'assistant', message: { content: [{ type: 'tool_use', name, input }] } });
  const bash = Array.from({ length: 30 }, () => toolUse('Bash'));
  const tails = {
    read: toolUse('Read', { file_path: '/repo/docs/memory/notes.md' }),
    write: toolUse('Write', { file_path: '/h/.claude/projects/p/memory/f.md', content: 'x' }),
    multiedit: toolUse('MultiEdit', { file_path: '/h/memory/f.md', edits: [] }),
  };
  const outcomes = {};
  for (const [label, tail] of Object.entries(tails)) {
    const transcript = join(cwd, `t-${label}.jsonl`);
    writeFileSync(transcript, [...bash, tail].join('\n') + '\n');
    const r = runHook({ hook_event_name: 'Stop', transcript_path: transcript, session_id: `stop-${label}` }, { home, cwd });
    outcomes[label] = [hookLog(home).at(-1).action, r.stdout !== ''];
  }
  assert.deepEqual(outcomes, { read: ['nudge', true], write: ['pass', false], multiedit: ['pass', false] });
});

test(
  '#192: a file the hook may not read is never ledgered and its retry is never refused',
  { skip: process.platform === 'win32' || process.getuid?.() === 0 ? 'root reads a mode-000 file; win32 modes are advisory' : false },
  () => {
    // RED before job65: the second Read of a chmod-000 file was denied.
    const home = newDir('home');
    const cwd = newDir('cwd');
    const locked = join(cwd, 'locked.txt');
    writeFileSync(locked, 'secret');
    chmodSync(locked, 0o000);
    let runs;
    try {
      runs = [runHook(readPayload(locked), { home, cwd }), runHook(readPayload(locked), { home, cwd })];
    } finally {
      chmodSync(locked, 0o644);
    }
    assert.deepEqual(runs.map((r) => r.stdout), ['', '']);
    assert.ok(!existsSync(join(home, '.bantamkit', 'hooks', 'ledger-probe-session.json')));
  },
);
