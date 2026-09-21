/**
 * A — the one-way export of bantamkit fact descriptions into Claude Code's OWN auto-memory
 * directory, and the resolver that finds that directory without recomputing the host's slug.
 *
 * WHY THIS FILE EXISTS, in two halves.
 *
 * 1. THE DEBT. `nativeMemoryExists` used to answer "does the host have an auto-memory store
 *    for this cwd" with `cwd.replace(/[\\/:]/g,'-')` — an incomplete reimplementation of the
 *    host's slug, on the hook path. S0 (`.shiftwork/notes-job62/S0-prep-probe.md`) dumped the
 *    real resolver out of `2.1.278`: four branches, a 200-character cap with a base36 hash
 *    suffix, and a key that is the CANONICALIZED GIT WORKTREE ROOT, not the cwd. Every one of
 *    those three is missing from the old rule, and job62 runs inside a worktree, which is
 *    exactly the case the old rule gets wrong. The fix is not a better slug — it is to stop
 *    computing one and read the answer back instead.
 *
 * 2. THE EXPORT. RULING Q1.2/Q1.3/Q1.5 of `.shiftwork/notes-job62/S1-delivery-path.md`. A
 *    learns the directory by OBSERVATION WITH VERIFICATION (env override, then
 *    `autoMemoryDirectory` from `<home>/.claude/settings.json`, then
 *    `dirname(transcript_path)/memory`, each of the last two accepted only when it holds a
 *    readable `MEMORY.md`), exports NOTHING when no branch answers, and writes a name only
 *    when that name is ABSENT. It never rewrites an entry, never deletes one, and never
 *    creates the directory or `MEMORY.md`.
 *
 * THE TESTS ARE PROCESS-LEVEL, for `hooks.test.mjs`'s reason: an arm that has only ever been
 * READ is how the PreCompact channel defect shipped. Each case feeds `dist/cli.js --hook` a
 * real payload on stdin.
 *
 * NOTHING HERE TOUCHES THE REAL HOME. Every run gets a scratch HOME **and** a scratch
 * USERPROFILE, and `runHook` ASSERTS the adapter followed it — the hook log has to be under
 * the scratch home — before any case looks at what was written. That assertion is not a
 * style note: J62-5 lost the operator's real `~/.claude/settings.json` to a probe that set
 * only `COLUMNS`/`LINES`.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import {
  appendFileSync,
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { MemoryStore } from '../dist/memory/store.js';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const CLI = join(packageRoot, 'dist', 'cli.js');

const scratch = mkdtempSync(join(tmpdir(), 'bk-nativeexport-'));
after(() => {
  // A case deliberately drops a directory to 0o500; put it back or the rm fails. POSIX only —
  // on Windows that case does not run at all (`process.platform`, in the case itself), because
  // `chmod` there honours only the read-only bit and cannot make a directory unwritable.
  if (process.platform !== 'win32') {
    try {
      chmodSync(join(scratch, 'ro-native'), 0o700);
    } catch {
      /* the case may not have run */
    }
  }
  rmSync(scratch, { recursive: true, force: true });
});

let n = 0;
function newDir(prefix) {
  const dir = join(scratch, `${prefix}-${n++}`);
  mkdirSync(dir, { recursive: true });
  return dir;
}

/** A project store under `cwd` holding `facts`, written through the store itself. */
function seedStore(cwd, facts) {
  const root = join(cwd, '.bantamkit', 'memory');
  const store = new MemoryStore(root);
  for (const f of facts) store.save(f.type, f.name, f.description, f.body ?? 'body');
  return root;
}

/** A native auto-memory directory that the resolver's branches 2 and 3 will ACCEPT. */
function seedNative(dir, index = '# Memory index\n\n## Project\n\n') {
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'MEMORY.md'), index);
  return dir;
}

/**
 * `bantamkit-mcp --hook` over a scratch HOME/USERPROFILE and a scratch cwd.
 *
 * `BANTAMKIT_MEMORY_DIR` and `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` are DELETED from the
 * inherited environment unless a case sets them: both are resolver inputs, and a case that
 * silently read the operator's own value would be measuring this machine, not the code.
 */
function runHook(payload, { home = newDir('home'), cwd = newDir('cwd'), env = {} } = {}) {
  const base = { ...process.env, HOME: home, USERPROFILE: home };
  delete base['BANTAMKIT_MEMORY_DIR'];
  delete base['CLAUDE_COWORK_MEMORY_PATH_OVERRIDE'];
  const r = spawnSync(process.execPath, [CLI, '--hook'], {
    input: JSON.stringify({ cwd, session_id: 'native-export-probe', ...payload }),
    encoding: 'utf8',
    env: { ...base, ...env },
  });
  // THE HOME ASSERTION, and it fires before any case reads a byte it wrote.
  const log = join(home, '.bantamkit', 'hooks', 'hook-log.jsonl');
  assert.ok(existsSync(log), `the adapter did not follow HOME=${home}: no log at ${log}`);
  const records = readFileSync(log, 'utf8')
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line));
  const record = records.find((x) => x.event === 'SessionStart' && x.bytes !== undefined) ?? null;
  return { ...r, cwd, home, records, record };
}

/** A SessionStart payload whose `transcript_path` sits beside `<t>/memory`. */
function transcriptIn(dir) {
  return join(dir, 'session.jsonl');
}

// ------------------------------------------------------------------- the resolver

test('branch 1: the env override IS the directory, with no MEMORY.md anywhere', () => {
  // RULING Q1.2(1): `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` beats everything in the host too,
  // so A accepts it unverified. This directory holds no `MEMORY.md` and is still the answer.
  const dir = newDir('override-native');
  const r = runHook(
    { hook_event_name: 'SessionStart', source: 'startup' },
    { env: { CLAUDE_COWORK_MEMORY_PATH_OVERRIDE: dir } },
  );
  assert.equal(r.status, 0);
  assert.equal(r.record.nativeBranch, 'env');
  assert.equal(r.record.nativeDir, dir);
  assert.deepEqual(r.record.nativeTried, []);
});

test('branch 2: autoMemoryDirectory from <home>/.claude/settings.json, when it holds MEMORY.md', () => {
  const home = newDir('home');
  const dir = seedNative(newDir('settings-native'));
  mkdirSync(join(home, '.claude'), { recursive: true });
  writeFileSync(join(home, '.claude', 'settings.json'), JSON.stringify({ autoMemoryDirectory: dir }));
  const r = runHook({ hook_event_name: 'SessionStart', source: 'startup' }, { home });
  assert.equal(r.record.nativeBranch, 'settings');
  assert.equal(r.record.nativeDir, dir);
  assert.deepEqual(r.record.nativeTried, ['env']);
});

test('branch 2 is a CANDIDATE: a settings directory with no MEMORY.md is rejected, not used', () => {
  // Three higher-precedence sources exist in the host that A cannot read (policySettings,
  // flagSettings, and the env var), so `userSettings` is never taken on its word.
  const home = newDir('home');
  const bare = newDir('settings-bare'); // exists, but no MEMORY.md
  mkdirSync(join(home, '.claude'), { recursive: true });
  writeFileSync(join(home, '.claude', 'settings.json'), JSON.stringify({ autoMemoryDirectory: bare }));
  const r = runHook({ hook_event_name: 'SessionStart', source: 'startup' }, { home });
  assert.equal(r.record.nativeBranch, 'unknown');
  assert.equal(r.record.nativeDir, null);
  assert.deepEqual(r.record.nativeTried, ['env', 'settings', 'transcript']);
});

test('branch 3: dirname(transcript_path)/memory — the slug the host itself computed', () => {
  const t = newDir('transcript');
  const dir = seedNative(join(t, 'memory'));
  const r = runHook({
    hook_event_name: 'SessionStart',
    source: 'startup',
    transcript_path: transcriptIn(t),
  });
  assert.equal(r.record.nativeBranch, 'transcript');
  assert.equal(r.record.nativeDir, dir);
  assert.deepEqual(r.record.nativeTried, ['env', 'settings']);
});

test('branch 3 is a CANDIDATE too: a transcript with no memory/MEMORY.md beside it is rejected', () => {
  const t = newDir('transcript-bare');
  const r = runHook({
    hook_event_name: 'SessionStart',
    source: 'startup',
    transcript_path: transcriptIn(t),
  });
  assert.equal(r.record.nativeBranch, 'unknown');
  assert.deepEqual(r.record.nativeTried, ['env', 'settings', 'transcript']);
});

test('UNKNOWN exports nothing and creates nothing — no mkdir, no fallback slug', () => {
  // RULING Q1.3. A directory at a slug the host does not resolve to is a store nobody reads
  // and nobody prunes, so the honest answer to "I do not know the path" is silence.
  const cwd = newDir('cwd');
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  const r = runHook({ hook_event_name: 'SessionStart', source: 'startup' }, { cwd });
  assert.equal(r.status, 0);
  assert.equal(r.record.nativeBranch, 'unknown');
  assert.equal(r.record.nativeExported, undefined, 'no export ran at all');
  assert.ok(
    !existsSync(join(r.home, '.claude', 'projects')),
    'A must not create a directory under ~/.claude/projects',
  );
});

test('THE DEBT: a directory at the OLD slug is not the answer — the resolver does not recompute', () => {
  // This is the case the replaced `cwd.replace(/[\\/:]/g,'-')` got wrong, driven from the
  // outside. The old-slug directory is built EXACTLY as the old code would have addressed it
  // and given a real `MEMORY.md`; the resolver must still answer `unknown`, and — the
  // observable consequence — SessionStart must still inject the project index, which the old
  // code suppressed on the strength of that directory.
  const home = newDir('home');
  const cwd = newDir('cwd');
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  const oldSlug = cwd.replace(/[\\/:]/g, '-');
  seedNative(join(home, '.claude', 'projects', oldSlug, 'memory'));
  const r = runHook({ hook_event_name: 'SessionStart', source: 'startup' }, { home, cwd });
  assert.equal(r.record.nativeBranch, 'unknown');
  const ctx = JSON.parse(r.stdout).hookSpecificOutput.additionalContext;
  assert.match(ctx, /\[bantamkit project memory — 1 facts\]/);
  assert.equal(r.record.projectInjected, 1);
});

// --------------------------------------------------------------------- the export

test('an absent name is written as a valid auto-memory file: name, description, metadata.type', () => {
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  const dir = seedNative(join(t, 'memory'));
  seedStore(cwd, [
    { type: 'project', name: 'alpha', description: 'the first fact' },
    { type: 'feedback', name: 'beta', description: 'the second   fact\nwrapped' },
  ]);
  const r = runHook(
    { hook_event_name: 'SessionStart', source: 'startup', transcript_path: transcriptIn(t) },
    { cwd },
  );
  assert.equal(r.status, 0);
  assert.equal(r.record.nativeBranch, 'transcript');
  assert.equal(r.record.nativeExported, 2);
  assert.equal(r.record.nativeFiles, 2);

  const alpha = readFileSync(join(dir, 'alpha.md'), 'utf8');
  assert.match(alpha, /^---\nname: alpha\ndescription: "the first fact"\nmetadata:\n/);
  assert.match(alpha, /^ {2}node_type: memory$/m);
  assert.match(alpha, /^ {2}type: project$/m);
  assert.match(alpha, /^ {2}source: bantamkit$/m);
  assert.match(alpha, /mcp__bantamkit__memory_recall/);

  // Whitespace is normalised to single spaces, so a wrapped description stays ONE YAML line.
  const beta = readFileSync(join(dir, 'beta.md'), 'utf8');
  assert.match(beta, /^description: "the second fact wrapped"$/m);
  assert.match(beta, /^ {2}type: feedback$/m);
});

test('the index line is appended under a section A owns, and nothing already there is touched', () => {
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  const seeded = '# Memory index\n\n## Project\n\n- [host-fact](host-fact.md) — the host wrote this\n';
  const dir = seedNative(join(t, 'memory'), seeded);
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  const r = runHook(
    { hook_event_name: 'SessionStart', source: 'startup', transcript_path: transcriptIn(t) },
    { cwd },
  );
  const index = readFileSync(join(dir, 'MEMORY.md'), 'utf8');
  assert.ok(index.startsWith(seeded), 'every byte the host wrote is still there, in order');
  assert.match(index, /\n## bantamkit\n/);
  assert.match(index, /\n- \[alpha\]\(alpha\.md\) — the first fact\n/);
  assert.equal(r.record.nativeIndexLines, 1);
});

test('a name already in the index gets no second line, and its file is not rewritten', () => {
  // RULING Q1.5: write a name only when it is ABSENT. The two halves are checked
  // independently — the file's absence gates the file, the index line's absence gates the
  // line — so a dream that removes one and keeps the other leaves A doing exactly one thing.
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  const dir = seedNative(
    join(t, 'memory'),
    '# Memory index\n\n- [alpha](alpha.md) — a description the host reworded\n',
  );
  writeFileSync(join(dir, 'alpha.md'), 'SENTINEL — written by something that is not bantamkit\n');
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  const r = runHook(
    { hook_event_name: 'SessionStart', source: 'startup', transcript_path: transcriptIn(t) },
    { cwd },
  );
  assert.equal(
    readFileSync(join(dir, 'alpha.md'), 'utf8'),
    'SENTINEL — written by something that is not bantamkit\n',
    'an entry A did not just create is never rewritten',
  );
  const index = readFileSync(join(dir, 'MEMORY.md'), 'utf8');
  assert.equal(index.match(/\]\(alpha\.md\)/g).length, 1, 'exactly one index line names alpha');
  assert.equal(r.record.nativeExported, 0);
  // A name already there is a QUIET skip, not a failed write. The `wx` flag on the write is a
  // second guard against the race between the check and the write; this assertion is what
  // keeps the FIRST guard — `lexists` — from being quietly deleted in favour of it, because
  // without it an already-present name would end the run with an EEXIST instead of skipping.
  assert.equal(r.record.nativeError, undefined, 'a present name costs no error');
});

test('a second run writes nothing new — and neither run reads back its own writes as state', () => {
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  const dir = seedNative(join(t, 'memory'));
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  const payload = {
    hook_event_name: 'SessionStart',
    source: 'startup',
    transcript_path: transcriptIn(t),
  };
  const first = runHook(payload, { cwd });
  assert.equal(first.record.nativeExported, 1);
  const after1 = readFileSync(join(dir, 'MEMORY.md'), 'utf8');
  const second = runHook(payload, { cwd });
  assert.equal(second.record.nativeExported, 0);
  assert.equal(readFileSync(join(dir, 'MEMORY.md'), 'utf8'), after1, 'the index is byte-unchanged');

  // …and when the host's dream removes both halves, the THIRD run puts them back. A is
  // correct when everything it wrote is gone, which is the property job59 measured it needs.
  rmSync(join(dir, 'alpha.md'));
  writeFileSync(join(dir, 'MEMORY.md'), '# Memory index\n');
  const third = runHook(payload, { cwd });
  assert.equal(third.record.nativeExported, 1);
  assert.ok(existsSync(join(dir, 'alpha.md')));
});

test('A never deletes: a file it did not write survives an export', () => {
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  const dir = seedNative(join(t, 'memory'));
  writeFileSync(join(dir, 'someone-elses.md'), 'not ours\n');
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  runHook(
    { hook_event_name: 'SessionStart', source: 'startup', transcript_path: transcriptIn(t) },
    { cwd },
  );
  assert.equal(readFileSync(join(dir, 'someone-elses.md'), 'utf8'), 'not ours\n');
});

test('A never creates MEMORY.md: under the env override with none, files land and no index does', () => {
  const cwd = newDir('cwd');
  const dir = newDir('override-native'); // exists, no MEMORY.md — branch 1 takes it unverified
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  const r = runHook(
    { hook_event_name: 'SessionStart', source: 'startup' },
    { cwd, env: { CLAUDE_COWORK_MEMORY_PATH_OVERRIDE: dir } },
  );
  assert.ok(existsSync(join(dir, 'alpha.md')));
  assert.ok(!existsSync(join(dir, 'MEMORY.md')), 'A does not write the host index into existence');
  assert.equal(r.record.nativeIndexLines, 0);
  assert.equal(r.record.nativeIndex, 'absent');
});

test('A never mkdirs: the env override naming a directory that is not there writes nothing', () => {
  const cwd = newDir('cwd');
  const missing = join(scratch, 'not-created-by-a');
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  const r = runHook(
    { hook_event_name: 'SessionStart', source: 'startup' },
    { cwd, env: { CLAUDE_COWORK_MEMORY_PATH_OVERRIDE: missing } },
  );
  assert.equal(r.status, 0);
  assert.ok(!existsSync(missing), 'the directory is still not there');
  assert.equal(r.record.nativeExported, 0);
  assert.ok(r.record.nativeError, 'the failure is logged rather than thrown');
});

test('a directory that is not writable costs one log line, not an error on the screen', (ctx) => {
  // WINDOWS CANNOT CONSTRUCT THIS, and saying so is the point of the guard rather than a
  // convenience. `chmod` on Windows honours only the read-only bit, which does not stop a
  // write INTO a directory, so `0o500` there would leave the export succeeding and this case
  // would assert the opposite of what it means. `process.platform`, not a bare `t.skip`, is
  // what the platform gate accepts — and the reason is the same one the gate gives.
  if (process.platform === 'win32') {
    ctx.skip('chmod cannot make a directory unwritable on Windows; the refusal path needs its own fixture there');
    return;
  }
  const cwd = newDir('cwd');
  const t = join(scratch, 'ro-native-parent');
  mkdirSync(t, { recursive: true });
  const dir = seedNative(join(scratch, 'ro-native'));
  writeFileSync(join(t, 'x'), ''); // keep the parent around for `after`
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  chmodSync(dir, 0o500);
  const r = runHook(
    { hook_event_name: 'SessionStart', source: 'startup' },
    { cwd, env: { CLAUDE_COWORK_MEMORY_PATH_OVERRIDE: dir } },
  );
  chmodSync(dir, 0o700);
  assert.equal(r.status, 0);
  assert.equal(r.stdout.startsWith('{'), true, 'the arm still emits its one JSON object');
  assert.equal(r.record.nativeExported, 0);
  assert.ok(r.record.nativeError, `expected a logged error, got ${JSON.stringify(r.record)}`);
  assert.ok(!existsSync(join(dir, 'alpha.md')));
});

test('the export is BOUNDED: at most 2000 bytes are appended to the host index per run', () => {
  // The index bytes are the ones that mean something — they are what the host injects. Six
  // facts with 400-character descriptions make each line 427 B, so four fit (1708 B) and the
  // fifth would pass 2000; the run stops there and the rest go on a later session.
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  const dir = seedNative(join(t, 'memory'));
  const facts = [];
  for (let i = 0; i < 6; i += 1) {
    // EVERY WORD DISTINCT PER FACT, and that is not decoration: `MemoryStore.save` refuses a
    // near-duplicate by token overlap, so six facts sharing a description save as ONE and the
    // case would measure the dedupe rather than the budget. Exactly 400 ASCII characters.
    const words = Array.from({ length: 20 }, (_, k) => `q${i}z${k}`).join(' ');
    facts.push({ type: 'project', name: `fact-${i}`, description: words.padEnd(400, 'x').slice(0, 400) });
  }
  seedStore(cwd, facts);
  assert.equal(new MemoryStore(join(cwd, '.bantamkit', 'memory')).internals().facts().length, 6);
  const r = runHook(
    { hook_event_name: 'SessionStart', source: 'startup', transcript_path: transcriptIn(t) },
    { cwd },
  );
  assert.equal(r.record.nativeIndexLines, 4);
  assert.equal(r.record.nativeIndexBytes, 4 * 427);
  assert.ok(r.record.nativeIndexBytes <= 2000);
  const index = readFileSync(join(dir, 'MEMORY.md'), 'utf8');
  assert.equal(index.match(/^- \[fact-\d\]/gm).length, 4);
});

test('the export is BOUNDED: at most 10 names leave per hook run', () => {
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  const dir = seedNative(join(t, 'memory'));
  const facts = [];
  for (let i = 0; i < 14; i += 1) {
    // Distinct words again, for the dedupe reason the index-bytes case above gives:
    // `description: "number ${i}"` shares the token `number` with all thirteen others and
    // three of the fourteen were REFUSED as near-duplicates, which the assertion below caught.
    facts.push({
      type: 'project',
      name: `fact-${String(i).padStart(2, '0')}`,
      description: Array.from({ length: 4 }, (_, k) => `t${i}w${k}`).join(' '),
    });
  }
  seedStore(cwd, facts);
  // 14 really are on disk — otherwise a cap of 10 would be met by a store that only held 10.
  assert.equal(new MemoryStore(join(cwd, '.bantamkit', 'memory')).internals().facts().length, 14);
  const r = runHook(
    { hook_event_name: 'SessionStart', source: 'startup', transcript_path: transcriptIn(t) },
    { cwd },
  );
  assert.equal(r.record.nativeExported, 10);
  assert.equal(r.record.nativeFiles, 10);
});

test('a fact name that is not a safe filename is skipped, not joined into a path', () => {
  // `MemoryStore.save` enforces `^[a-z0-9][a-z0-9-]*$`, but `facts()` does NOT revalidate on
  // READ — measured: a hand-written `facts/*.md` whose frontmatter says `name: ../escape`
  // parses and is handed out with that name. So the guard is reachable, and this drives it.
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  const dir = seedNative(join(t, 'memory'));
  const root = seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  writeFileSync(
    join(root, 'facts', 'weird.md'),
    "---\nname: ../escape\ndescription: traversal probe\ntype: project\ncreated: '2026-09-20'\n---\n\nbody\n",
  );
  const r = runHook(
    { hook_event_name: 'SessionStart', source: 'startup', transcript_path: transcriptIn(t) },
    { cwd },
  );
  assert.equal(r.status, 0);
  assert.deepEqual(r.record.nativeSkipped, ['../escape']);
  assert.equal(r.record.nativeExported, 1, 'alpha still went, the traversal name did not');
  assert.ok(!existsSync(join(dirname(dir), 'escape.md')), 'nothing escaped the directory');
});

test('the export replaces the project index — it is not injected on top of it', () => {
  // The old `nativeMemoryExists` suppressed the project block whenever the host had a store
  // for this cwd. That behaviour is KEPT, now keyed on the resolver: the export IS the
  // delivery, so injecting the same facts again would be paying twice.
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  seedNative(join(t, 'memory'));
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  const r = runHook(
    { hook_event_name: 'SessionStart', source: 'startup', transcript_path: transcriptIn(t) },
    { cwd },
  );
  const ctx = JSON.parse(r.stdout).hookSpecificOutput.additionalContext;
  assert.ok(!/bantamkit project memory/.test(ctx), 'no project block when the export ran');
  assert.equal(r.record.projectInjected, undefined);
});

test('only the PROJECT layer is exported — the profile store stays out of a project directory', () => {
  // The native directory is keyed on the host's project root, so a cross-project fact in it
  // would be copied into every project's store; and the profile index is injected on every
  // session anyway, so exporting it buys nothing. Named here so a later unit cannot widen it
  // by accident.
  const home = newDir('home');
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  const dir = seedNative(join(t, 'memory'));
  const profile = join(home, '.bantamkit', 'memory');
  new MemoryStore(profile).save('user', 'profile-only', 'a cross-project fact', 'body');
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  const r = runHook(
    { hook_event_name: 'SessionStart', source: 'startup', transcript_path: transcriptIn(t) },
    { home, cwd },
  );
  assert.ok(existsSync(join(dir, 'alpha.md')));
  assert.ok(!existsSync(join(dir, 'profile-only.md')), 'the profile layer is not exported');
  assert.equal(r.record.nativeExported, 1);
});

test('the export runs on SessionStart and on no other event', () => {
  // One resolution per session, at the one event that carries `transcript_path` and already
  // had to resolve the directory for the injection decision.
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  const dir = seedNative(join(t, 'memory'));
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  const r = runHook(
    { hook_event_name: 'UserPromptSubmit', prompt: 'a prompt long enough to be scored', transcript_path: transcriptIn(t) },
    { cwd },
  );
  assert.equal(r.status, 0);
  assert.ok(!existsSync(join(dir, 'alpha.md')), 'UserPromptSubmit exports nothing');
  const stop = runHook(
    { hook_event_name: 'Stop', transcript_path: transcriptIn(t) },
    { cwd },
  );
  assert.equal(stop.status, 0);
  assert.ok(!existsSync(join(dir, 'alpha.md')), 'Stop exports nothing either');
});

// --------------------------------------------------- appending, at the end of the file

test('the ## bantamkit heading is written once and never a second time', () => {
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  const dir = seedNative(join(t, 'memory'));
  seedStore(cwd, [
    { type: 'project', name: 'alpha', description: 'the first fact' },
    { type: 'project', name: 'gamma', description: 'the third fact' },
  ]);
  const payload = {
    hook_event_name: 'SessionStart',
    source: 'startup',
    transcript_path: transcriptIn(t),
  };
  runHook(payload, { cwd });
  // a new fact appears in bantamkit between the two sessions
  new MemoryStore(join(cwd, '.bantamkit', 'memory')).save(
    'project',
    'delta',
    'the fourth fact',
    'body',
  );
  runHook(payload, { cwd });
  const index = readFileSync(join(dir, 'MEMORY.md'), 'utf8');
  assert.equal(index.match(/^## bantamkit$/gm).length, 1);
  assert.match(index, /\n- \[delta\]\(delta\.md\) — the fourth fact\n/);
});

test('an index that does not end in a newline still gets a well-formed line', () => {
  const cwd = newDir('cwd');
  const t = newDir('transcript');
  const dir = seedNative(join(t, 'memory'), '# Memory index');
  appendFileSync(join(dir, 'MEMORY.md'), ''); // no trailing newline
  seedStore(cwd, [{ type: 'project', name: 'alpha', description: 'the first fact' }]);
  runHook(
    { hook_event_name: 'SessionStart', source: 'startup', transcript_path: transcriptIn(t) },
    { cwd },
  );
  const index = readFileSync(join(dir, 'MEMORY.md'), 'utf8');
  assert.ok(index.startsWith('# Memory index\n'), 'a newline was inserted, the line was not glued on');
  assert.match(index, /\n- \[alpha\]\(alpha\.md\) — the first fact\n$/);
});
