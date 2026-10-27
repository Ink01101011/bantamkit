/**
 * Memory lifecycle (#219 #220 #221), the Node half: `outcome` and `status` on a fact, the
 * `outcome` filter on recall, `listFacts`, `candidatesDone`, `merge`, and the `list`,
 * `candidates` and `merge` subcommands. Every literal is copied from
 * `runtime-py/tests/test_memory_lifecycle.py`; a sentence spelled differently here is a
 * parity bug, not a style choice.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

import { MemoryStore } from '../dist/memory/store.js';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const CLI = join(packageRoot, 'dist', 'memory', 'cli.js');

function run(argv, columns = 200) {
  const env = { ...process.env };
  for (const key of ['COLUMNS', 'LINES', 'BANTAMKIT_ASSETS', 'BANTAMKIT_MEMORY_DIR']) delete env[key];
  env.COLUMNS = String(columns);
  const r = spawnSync(process.execPath, [CLI, ...argv], { input: '', env, encoding: 'utf8' });
  return { stdout: r.stdout, stderr: r.stderr, exit: r.status };
}

function makeStore() {
  const root = join(mkdtempSync(join(tmpdir(), 'bk-life-')), 'mem');
  return new MemoryStore(root, { indexBudget: 100_000, today: () => '2026-10-21' });
}
const factText = (store, name) => readFileSync(join(store.root, 'facts', `${name}.md`), 'utf8');
const names = (facts) => facts.map((f) => f.name);

test('outcome and status round-trip and are written after links', () => {
  const store = makeStore();
  store.save('feedback', 'lesson-a', 'a lesson about alpha', 'body', [], [], 'error', 'done');
  const text = factText(store, 'lesson-a');
  const [links, outcome, status] = ['links: []\n', 'outcome: error\n', 'status: done\n'].map((k) => text.indexOf(k));
  assert.ok(links < outcome && outcome < status);
  const [fact] = store.recall('lesson alpha');
  assert.deepEqual([fact.outcome, fact.status], ['error', 'done']);
});

test('a fact saved without the new fields is byte-identical to before', () => {
  const store = makeStore();
  store.save('project', 'plain-fact', 'a plain description', 'body');
  const text = factText(store, 'plain-fact');
  assert.ok(!text.includes('outcome') && !text.includes('status'));
  assert.equal(
    text,
    "---\nname: plain-fact\ndescription: a plain description\ntype: project\n" +
      "created: '2026-10-21'\nlast_recalled: null\nlinks: []\n---\n\nbody\n",
  );
});

test('status active is never written', () => {
  const store = makeStore();
  store.save('project', 'p', 'a description', 'b', [], [], null, 'active');
  assert.ok(!factText(store, 'p').includes('status'));
});

test('an unknown outcome or status is refused with the sentence, and nothing is written', () => {
  for (const [outcome, status, sentence] of [
    ['meh', null, "invalid outcome 'meh'; must be one of ['error', 'success']"],
    [null, 'gone', "invalid status 'gone'; must be one of ['active', 'done']"],
  ]) {
    const store = makeStore();
    assert.throws(() => store.save('project', 'p', 'a description', 'b', [], [], outcome, status), {
      message: sentence,
    });
    assert.throws(() => factText(store, 'p'));
  }
});

test('outcome is refused on user and reference facts', () => {
  const store = makeStore();
  assert.throws(() => store.save('reference', 'r', 'a description', 'b', [], [], 'success'), {
    message:
      "invalid outcome 'success' for type 'reference'; outcome is only for feedback and project facts",
  });
});

test('memory-keeper metadata is read as an alias and not rewritten', () => {
  const store = makeStore();
  store.ensureDirs();
  const raw =
    '---\nname: old-lesson\n' +
    'description: an old lesson about gamma\nmetadata:\n  type: feedback\n  loop: error\n  status: done\n---\n\nbody\n';
  const path = join(store.root, 'facts', 'old-lesson.md');
  writeFileSync(path, raw, 'utf8');
  const [fact] = store.recall('old lesson gamma', null, false);
  assert.deepEqual([fact.type, fact.outcome, fact.status], ['feedback', 'error', 'done']);
  assert.equal(readFileSync(path, 'utf8'), raw);
});

test('alias values outside the enums read as absent; archived reads as done', () => {
  const store = makeStore();
  store.ensureDirs();
  writeFileSync(
    join(store.root, 'facts', 'r.md'),
    '---\nname: r\ndescription: a reflexion pattern about delta\ntype: feedback\n' +
      'metadata:\n  loop: reflexion\n  status: archived\n---\n\nbody\n',
    'utf8',
  );
  const [fact] = store.recall('reflexion pattern delta', null, false);
  assert.equal(fact.outcome, null);
  assert.equal(fact.status, 'done');
});

test('recall with outcome keeps only matching hits', () => {
  const store = makeStore();
  store.save('feedback', 'bad-one', 'lesson zeta pipeline crashed', 'b', [], [], 'error');
  store.save('feedback', 'good-one', 'lesson zeta rollout shipped', 'b', [], [], 'success');
  store.save('feedback', 'plain-one', 'lesson zeta weekly sync agenda', 'b');
  assert.deepEqual(names(store.recall('lesson zeta', 5, true, 0, undefined, 'error')), ['bad-one']);
  assert.deepEqual(names(store.recall('lesson zeta', 5, true, 0, undefined, 'success')), ['good-one']);
  assert.equal(store.recall('lesson zeta', 5).length, 3);
});

test('listFacts filters and sorts by name', () => {
  const store = makeStore();
  store.save('feedback', 'b-err', 'about b', 'b', [], [], 'error');
  store.save('feedback', 'a-ok', 'about a', 'b', [], [], 'success');
  store.save('project', 'c-done', 'about c', 'b', [], [], null, 'done');
  assert.deepEqual(names(store.listFacts()), ['a-ok', 'b-err', 'c-done']);
  assert.deepEqual(names(store.listFacts(null, 'error')), ['b-err']);
  assert.deepEqual(names(store.listFacts('project', null, 'done')), ['c-done']);
  assert.deepEqual(names(store.listFacts(null, null, 'active')), ['a-ok', 'b-err']);
});

test('the list subcommand prints one line per fact', () => {
  const store = makeStore();
  store.save('feedback', 'b-err', 'about b', 'b', [], [], 'error');
  store.save('project', 'c-done', 'about c', 'b', [], [], null, 'done');
  assert.deepEqual(run(['list', '--store', store.root]), {
    stdout:
      `facts: 2 (${join(store.root, 'facts')})\n` +
      'b-err\tfeedback\terror\tactive\tabout b\n' +
      'c-done\tproject\t-\tdone\tabout c\n',
    stderr: '',
    exit: 0,
  });
  assert.equal(
    run(['list', '--outcome', 'error', '--store', store.root]).stdout,
    `facts: 1 (${join(store.root, 'facts')})\nb-err\tfeedback\terror\tactive\tabout b\n`,
  );
});

test('the list subcommand refuses an unknown filter value as usage', () => {
  assert.equal(run(['list', '--outcome', 'meh', '--store', tmpdir()]).exit, 2);
});

test('candidates: reasons in order, and feedback done-words do not count', () => {
  const store = makeStore();
  store.save('project', 'p-done', 'a thing', 'b', [], [], null, 'done');
  store.save('project', 'p-word', 'the release was Shipped yesterday', 'b');
  store.save('feedback', 'f-word', 'close issues with comment when done', 'b');
  store.save('project', 'p-old', 'an old project note', 'b');
  store.save('project', 'p-both', 'merged and closed', 'b', [], [], null, 'done');
  const path = join(store.root, 'facts', 'p-old.md');
  writeFileSync(path, readFileSync(path, 'utf8').replace("'2026-10-21'", "'2026-01-01'"), 'utf8');
  assert.deepEqual(
    store.candidatesDone().map(([f, r]) => [f.name, r]),
    [
      ['p-both', 'status: done'],
      ['p-done', 'status: done'],
      ['p-word', "done-word 'shipped' in description"],
    ],
  );
  const got = store.candidatesDone(30, '2026-10-21').map(([f, r]) => [f.name, r]);
  assert.deepEqual(got.find(([n]) => n === 'p-old'), ['p-old', 'older than 30d (created 2026-01-01)']);
  assert.ok(got.every(([n]) => n !== 'f-word'));
});

test('the candidates subcommand is a dry run unless --apply', () => {
  const store = makeStore();
  store.save('project', 'p-done', 'a thing', 'b', [], [], null, 'done');
  store.save('project', 'p-live', 'another unrelated matter entirely', 'b');
  const before = readdirSync(join(store.root, 'facts')).sort();
  assert.equal(
    run(['candidates', '--store', store.root]).stdout,
    `archive candidates: 1 (${join(store.root, 'facts')})\n` +
      'p-done\tstatus: done\ta thing\n' +
      'dry run; rerun with --apply to archive these 1\n',
  );
  assert.deepEqual(readdirSync(join(store.root, 'facts')).sort(), before);
  const applied = run(['candidates', '--apply', '--store', store.root]);
  assert.equal(applied.exit, 0);
  assert.deepEqual(store.archived(), ['p-done']);
  assert.match(applied.stdout.trimEnd().split('\n').at(-1), /^archived 1 — index now /);
});

function mergeStore() {
  const store = makeStore();
  store.save('feedback', 'l-one', 'kappa lesson about retries', 'one', [], [], 'error');
  store.save('feedback', 'l-two', 'second lesson regarding cache invalidation', 'two', ['l-one']);
  store.save('feedback', 'l-three', 'third lesson on naming of branches', 'three');
  store.save('project', 'pointer', 'points at a lesson', 'p', ['l-two', 'elsewhere']);
  return store;
}

test('merge: a dry run writes nothing and apply writes then archives', () => {
  const store = mergeStore();
  const snapshot = Object.fromEntries(
    readdirSync(join(store.root, 'facts')).map((n) => [n, readFileSync(join(store.root, 'facts', n), 'utf8')]),
  );
  const argv = [
    'merge', '--names', 'l-one', 'l-two', 'l-three', '--name', 'kappa-pattern', '--type', 'feedback',
    '--description', 'the kappa pattern', '--body', 'always kappa', '--store', store.root,
  ];
  const dry = run(argv);
  assert.equal(dry.exit, 0);
  assert.ok(dry.stdout.startsWith('consumes:\n  l-one\tfeedback\tkappa lesson about retries\n'));
  assert.ok(dry.stdout.includes('produces:\n---\nname: kappa-pattern\n'));
  assert.ok(dry.stdout.includes('Sources: l-one, l-two, l-three\n'));
  assert.ok(dry.stdout.includes('links pointing at consumed facts:\n  pointer -> l-two\n'));
  assert.ok(dry.stdout.endsWith('dry run; rerun with --apply to write\n'));
  assert.deepEqual(
    Object.fromEntries(
      readdirSync(join(store.root, 'facts')).map((n) => [n, readFileSync(join(store.root, 'facts', n), 'utf8')]),
    ),
    snapshot,
  );
  assert.equal(run([...argv, '--apply']).exit, 0);
  assert.deepEqual(store.archived(), ['l-one', 'l-three', 'l-two']);
  const [fact] = store.recall('kappa pattern', null, false);
  assert.equal(fact.body, 'always kappa\n\nSources: l-one, l-two, l-three');
  assert.deepEqual(fact.links, []);
});

test('merge refusals carry the sentences', () => {
  for (const [list, target, sentence] of [
    [['l-one', 'nope'], 'x', 'merge needs at least two distinct live facts; missing: nope'],
    [['l-one', 'l-one'], 'x', 'merge needs at least two distinct live facts; missing: none'],
    [['l-one', 'l-two'], 'l-one', "cannot merge into 'l-one': it is one of the facts being merged"],
    [['l-one', 'l-two'], 'pointer', "cannot merge into 'pointer': a fact of that name exists"],
  ]) {
    assert.throws(() => mergeStore().merge(list, target, 'feedback', 'd', 'b'), { message: sentence });
  }
});

test('merge refuses an archived target name', () => {
  const store = mergeStore();
  store.archive('pointer');
  assert.throws(() => store.merge(['l-one', 'l-two'], 'pointer', 'feedback', 'd', 'b'), {
    message: "cannot merge into 'pointer': a fact of that name exists",
  });
});

test('merge usage errors: a required body group, a required option, a bad choice', () => {
  const base = ['merge', '--names', 'a', 'b', '--name', 'x', '--type', 'feedback', '--description', 'd'];
  const store = mergeStore();
  let r = run([...base, '--store', store.root]);
  assert.equal(r.exit, 2);
  assert.match(r.stderr, /bantamkit-memory merge: error: one of the arguments --body --body-file is required\n$/);
  r = run([...base, '--body', 'q', '--body-file', 'z']);
  assert.match(r.stderr, /error: argument --body-file: not allowed with argument --body\n$/);
  r = run(['merge']);
  assert.match(r.stderr, /error: the following arguments are required: --names, --name, --type, --description\n$/);
  r = run(['merge', '--names']);
  assert.match(r.stderr, /error: argument --names: expected at least one argument\n$/);
});

// ---- J73-6 review findings (literals copied from test_memory_lifecycle.py) ----------------

test('merge apply lands when the new fact resembles the facts it consumes', () => {
  const store = makeStore();
  store.save('feedback', 'bad-one', 'zeta lesson failed', 'b', [], [], 'error');
  store.save('feedback', 'good-one', 'zeta rollout worked', 'b', [], [], 'success');
  store.merge(['bad-one', 'good-one'], 'zeta-lesson', 'feedback', 'zeta lesson failed', 'z', null, null, true);
  assert.deepEqual(store.archived(), ['bad-one', 'good-one']);
  assert.deepEqual(names(store.listFacts()), ['zeta-lesson']);
});

test('merge refuses a new fact that duplicates an unconsumed one, and archives nothing', () => {
  const store = makeStore();
  store.save('feedback', 'l-one', 'first lesson on retries', 'b');
  store.save('feedback', 'l-two', 'second lesson on caching', 'b');
  store.save('project', 'zeta-notes', 'notes about the zeta pipeline', 'b');
  for (const apply of [false, true]) {
    assert.throws(
      () => store.merge(['l-one', 'l-two'], 'zeta-pipeline', 'feedback', 'notes about the zeta pipeline', 'z', null, null, apply),
      { message: "cannot merge into 'zeta-pipeline': it duplicates the live fact 'zeta-notes'" },
    );
  }
  assert.deepEqual(store.archived(), []);
  assert.deepEqual(names(store.listFacts()), ['l-one', 'l-two', 'zeta-notes']);
});

test('a fact whose type key is null is still read as 0.36.1 read it', () => {
  const store = makeStore();
  mkdirSync(join(store.root, 'facts'), { recursive: true });
  writeFileSync(
    join(store.root, 'facts', 't.md'),
    '---\nname: t\ndescription: a null type\ntype:\nmetadata:\n  type: feedback\n---\n\nb\n',
    'utf8',
  );
  const skipped = [];
  const facts = store.facts(undefined, skipped);
  assert.deepEqual([facts.map((f) => [f.name, f.type]), skipped], [[['t', null]], []]);
});

for (const created of ["'20260101'", "'2026-W01-1'", "'2026-1-01'"]) {
  test(`candidates age reads only a YYYY-MM-DD created (${created})`, () => {
    const store = makeStore();
    mkdirSync(join(store.root, 'facts'), { recursive: true });
    writeFileSync(
      join(store.root, 'facts', 'c.md'),
      `---\nname: c\ndescription: odd created\ntype: user\ncreated: ${created}\n---\n\nb\n`,
      'utf8',
    );
    assert.deepEqual(store.candidatesDone(3, '2026-10-21'), []);
  });
}
