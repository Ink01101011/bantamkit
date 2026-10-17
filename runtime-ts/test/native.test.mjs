/**
 * Claude Code's auto-memory as the read-only `[native]` recall layer (#199 J68-11, ruling A+B).
 *
 * The port's half of `runtime-py/tests/test_memory_native.py`. The differential lives in
 * `tools/conformance/suites/recall-strings.mjs` (the component), `hooks.mjs` (the transcript
 * branch) and `wire.mjs` (the MCP server's branch 2). Every test gets its own HOME.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { Memory } from '../dist/memory/component.js';
import { NativeStore } from '../dist/memory/native.js';
import { queryTerms } from '../dist/memory/retrieval.js';
import { MemoryStore, poolOf, poolWithout } from '../dist/memory/store.js';

const nativeFact = (dir, name, description, type = 'project', body = 'nb') => {
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    join(dir, `${name}.md`),
    `---\nname: ${name}\ndescription: "${description}"\nmetadata:\n  node_type: memory\n  type: ${type}\n---\n\n${body}\n`,
  );
};

const state = (dir) =>
  Object.fromEntries(
    readdirSync(dir)
      .sort()
      .map((n) => [n, [readFileSync(join(dir, n), 'utf8'), statSync(join(dir, n)).mtimeMs]]),
  );

/** A project and a host directory under a fresh HOME; the env is put back afterwards. */
function withBed(fn) {
  const root = mkdtempSync(join(tmpdir(), 'bk-native-'));
  const home = join(root, 'home');
  mkdirSync(home);
  const before = [process.env.HOME, process.env.USERPROFILE];
  process.env.HOME = home;
  process.env.USERPROFILE = home;
  try {
    const project = join(root, 'companyA');
    mkdirSync(project);
    const native = join(root, 'host', 'memory');
    mkdirSync(native, { recursive: true });
    writeFileSync(join(native, 'MEMORY.md'), '# Memory index\n\n- [kafka](kafka.md) — kafka\n');
    return fn({ root, home, project, native, store: join(project, '.bantamkit', 'memory') });
  } finally {
    [process.env.HOME, process.env.USERPROFILE] = before;
  }
}

test('the native layer is last and its hits are tagged', () =>
  withBed(({ project, native, store }) => {
    new MemoryStore(store).save('project', 'kafka-notes', 'kafka notes', 'b');
    nativeFact(native, 'kafka-lag', 'kafka consumer lag runbook', 'reference');
    const mem = Memory.layered(project, { native });
    assert.deepEqual(mem.layerLabels(), ['project', 'profile', 'native']);
    const out = mem.recallOutcome('kafka consumer lag', null, 0, false);
    assert.equal(out.headers[0], '[native] [kafka-lag] (reference) kafka consumer lag runbook');
    assert.equal(out.candidates, 2);
  }));

test('no native option means no layer', () =>
  withBed(({ project }) => {
    assert.deepEqual(Memory.layered(project).layerLabels(), ['project', 'profile']);
    assert.deepEqual(Memory.layered(project, { native: '  ' }).layerLabels(), ['project', 'profile']);
  }));

test('the tool recall writes nothing into the native directory', () =>
  withBed(({ project, native, store }) => {
    new MemoryStore(store).save('project', 'kafka-notes', 'kafka notes', 'b');
    nativeFact(native, 'kafka-lag', 'kafka consumer lag runbook');
    writeFileSync(
      join(native, 'old-shape.md'),
      "---\nname: old-shape\ndescription: kafka broker\ntype: project\ncreated: '2026-01-01'\n" +
        "last_recalled: '2026-01-02'\nlinks: []\n---\n\nb\n",
    );
    const before = state(native);
    const mem = Memory.layered(project, { native });
    mem.recall('kafka broker lag');
    mem.recall('kafka-lag');
    assert.deepEqual(state(native), before);
    assert.equal(mem.repaired, 0);
  }));

test('a name a bantamkit layer holds never answers from native', () =>
  withBed(({ project, native, store }) => {
    new MemoryStore(store).save('project', 'deploy', 'how we deploy', 'real');
    nativeFact(native, 'deploy', 'deploy deploy deploy runbook', 'project', 'export copy');
    const out = Memory.layered(project, { native }).recallOutcome('deploy runbook', null, 0, false);
    assert.deepEqual(out.headers, ['[project] [deploy] (project) how we deploy']);
    const pool = new NativeStore(native).pool(queryTerms('deploy'), undefined, new Set(['deploy']));
    assert.deepEqual([pool.n, [...pool.df], pool.names], [0, [['deploy', 0]], []]);
  }));

test('a native file that does not parse is skipped and named', () =>
  withBed(({ project, native }) => {
    nativeFact(native, 'gc-pauses', 'garbage collector pauses', 'feedback');
    writeFileSync(join(native, 'broken.md'), 'no frontmatter, garbage collector\n');
    const out = Memory.layered(project, { native }).recallOutcome('garbage collector');
    assert.deepEqual(out.headers, ['[native] [gc-pauses] (feedback) garbage collector pauses']);
    assert.deepEqual(
      out.skipped.map((s) => [s.layer, s.file]),
      [['native', 'broken.md']],
    );
  }));

test('a native directory that is not there is silent', () =>
  withBed(({ root, project, store }) => {
    new MemoryStore(store).save('project', 'x-fact', 'own subject', 'b');
    const out = Memory.layered(project, { native: join(root, 'nowhere') }).recallOutcome('own subject', null, 0, false);
    assert.deepEqual([out.status, out.unreadable, out.skipped], ['answered', 0, []]);
  }));

test('poolWithout equals the files pool of the rest', () =>
  withBed(({ native }) => {
    ['kafka lag', 'kafka broker lag', 'zookeeper', 'lag lag kafka'].forEach((d, i) => nativeFact(native, `n${i}`, d));
    const q = queryTerms('kafka lag');
    const s = new NativeStore(native);
    const got = s.pool(q, undefined, new Set(['n1']));
    const want = poolOf(s.candidates().filter((f) => f.name !== 'n1'), q);
    assert.deepEqual([got.n, got.total, [...got.df]], [want.n, want.total, [...want.df]]);
    const held = new Set();
    for (const t of q) for (let j = 0; j < got.segs.get(t).length; j += 3) held.add(got.names[got.segs.get(t)[j]]);
    assert.deepEqual([...held].sort(), want.names);
    assert.equal(poolWithout(got, new Set()), got);
  }));

test('layeredForEval takes a native copy', () =>
  withBed(({ root, native }) => {
    nativeFact(native, 'kafka-lag', 'kafka consumer lag runbook');
    const a = Memory.layeredForEval(join(root, 'p'), join(root, 'q'));
    const b = Memory.layeredForEval(join(root, 'p'), join(root, 'q'), 'v2', native);
    assert.deepEqual(a.injectCandidates('kafka lag'), []);
    assert.deepEqual(b.rankAll('kafka lag').map((f) => f.name), ['kafka-lag']);
  }));
