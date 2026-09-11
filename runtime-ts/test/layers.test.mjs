/**
 * The binding layer and the component on top of it: the shapes, pinned locally.
 *
 * The Python differential lives in `tools/conformance/suites/recall-strings.mjs`; this file
 * is the fast loop and the place where a behaviour is written down in words. Every literal
 * sentence asserted here was MEASURED out of the reference first (`layers_ref.py`), never
 * transcribed from the source by eye.
 *
 * NOTHING HERE TOUCHES A REAL STORE. Each test gets a throwaway root under the OS temp
 * directory and, where the profile layer is involved, its own `HOME` — `Memory.layered`
 * appends `Path.home()/.bantamkit/memory` and would otherwise recall against, and STAMP,
 * the operator's own facts.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  countFacts,
  discoverProjectStore,
  loadGrants,
  MEMORY_DIR_ENV,
  resolveProjectStore,
} from '../dist/memory/layers.js';
import { layerLabel, Memory, normalizeName, profileStore } from '../dist/memory/component.js';
import { MemoryValidationError, RECALL_MIN_SCORE_RATIO } from '../dist/memory/store.js';

/**
 * `os.stat`'s strerror for a path that is not there.
 *
 * `os.stat` goes through the WIN32 API, so on Windows CPython carries a `winerror` and the
 * sentence is the Win32 one; `open()` goes through the C runtime and keeps the POSIX one.
 * Both are the reference, each on its own platform. MEASURED, run 32646521489.
 */
const notFound = () =>
  (process.platform === 'win32'
    ? 'The system cannot find the file specified'
    : 'No such file or directory');

const TODAY = '2026-08-23';
/**
 * A throwaway bed, REALPATH'd. `/var` is a symlink to `/private/var` on macOS and
 * `_resolved_base` resolves before it walks, so a bed handed over unresolved would have the
 * test asserting a path the reference never prints.
 */
const fresh = () => realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-layers-')));

const factFile = (name, description = `about ${name}`, body = 'b') =>
  `---\nname: ${name}\ndescription: ${description}\ntype: project\ncreated: '2026-08-01'\n` +
  `last_recalled: null\nlinks: []\n---\n\n${body}\n`;

/** A store on disk, without going through `MemoryStore` — the fixture is bytes, not a call. */
function mkstore(root, facts = {}) {
  mkdirSync(join(root, 'facts'), { recursive: true });
  mkdirSync(join(root, 'archive'), { recursive: true });
  for (const [name, description] of Object.entries(facts)) {
    writeFileSync(join(root, 'facts', `${name}.md`), factFile(name, description));
  }
  return root;
}

/** Run `body` with these environment variables, and put the environment back. */
function withEnv(vars, body) {
  const before = new Map(Object.keys(vars).map((k) => [k, process.env[k]]));
  for (const [k, v] of Object.entries(vars)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  try {
    return body();
  } finally {
    for (const [k, v] of before) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

/** No ambient pin, and a HOME nobody's real facts live under. The conftest guard, here. */
const sandboxed = (home, body) =>
  withEnv({ [MEMORY_DIR_ENV]: undefined, HOME: home, USERPROFILE: home }, body);

/** A `Memory` whose clock is frozen, so a stamping recall does not race midnight. */
const frozen = (over = {}) => ({ today: () => TODAY, ...over });

// --------------------------------------------------------------------------- count_facts

test('count_facts counts what the store reads: dotfiles in, .txt out, a directory in', () => {
  const root = mkstore(join(fresh(), 's'), { plain: 'd' });
  writeFileSync(join(root, 'facts', '.hidden.md'), factFile('hidden'));
  writeFileSync(join(root, 'facts', 'notes.txt'), 'ignored\n');
  writeFileSync(join(root, 'facts', 'plain.md.tmp'), 'ignored\n');
  mkdirSync(join(root, 'facts', 'adir.md'));
  assert.equal(countFacts(root), 3);
});

test('an absent facts/ is 0 and not an error — nothing is stored there and that is readable', () => {
  const root = join(fresh(), 'no-facts');
  mkdirSync(root);
  assert.equal(countFacts(root), 0);
});

test('a facts/ that is a plain file raises rather than counting 0', () => {
  const root = join(fresh(), 'file-facts');
  mkdirSync(root);
  writeFileSync(join(root, 'facts'), 'not a directory\n');
  assert.throws(() => countFacts(root), (e) => e.name === 'NotADirectoryError' && e.code === 'ENOTDIR');
});

/**
 * THE DEFERRED DEFECT, REPRODUCED ON PURPOSE. DO NOT "FIX" THIS.
 *
 * `layers.count_facts` catches only `FileNotFoundError` and maps it to 0, while
 * `MemoryStore._fact_paths` keys "first run" on `os.path.lexists` and therefore RAISES on
 * the same shape. The two layers disagree, and runtime-py pins that with an unconditional
 * `xfail(strict=True)` on `test_a_dangling_facts_symlink_is_unreadable_to_both_layers`.
 * A port that quietly did the right thing here would disagree with production.
 *
 * WHEN PYTHON IS FIXED THIS GOES RED, and that is the point: the conformance case
 * `count_facts: a dangling facts symlink is 0 — THE DEFERRED DEFECT` compares this 0
 * against the reference's, so the day `count_facts` grows the `lexists` check its Python
 * side becomes an error and the case fails. This local node fails with it, because the
 * reference's xfail turns XPASS and somebody has to come here and take both off.
 *
 * On POSIX a symlink has no type. On Windows there are TWO shapes and only one of them is
 * this one — `symlink_to(t, target_is_directory=True)` gives ENOENT and this behaviour,
 * while the bare `symlink_to(t)` gives ENOTDIR and the layers AGREE. Not measurable here.
 */
test('a dangling facts/ symlink counts 0 while the store raises — the deferred defect', () => {
  const bed = fresh();
  const root = join(bed, 'dangling');
  mkdirSync(root);
  symlinkSync(join(bed, 'nowhere-at-all'), join(root, 'facts'));
  // NOW MEASURED, and the docstring above was right about the split: `symlinkSync` with no
  // type makes a FILE reparse point on Windows, `FindFirstFileW` on `facts\*` is
  // ERROR_DIRECTORY, and `count_facts` RAISES there — so the deferred defect does not
  // exist on that platform and the two layers agree. Run 32646521489.
  const windows = process.platform === 'win32';
  if (windows) {
    assert.throws(() => countFacts(root), (e) => e.name === 'NotADirectoryError');
  } else {
    assert.equal(countFacts(root), 0, 'count_facts catches FileNotFoundError and only that');
  }

  const binding = resolveProjectStore(root);
  assert.equal(binding.state, 'designated', 'the walk does not even see this as a store');

  const parent = join(bed, 'p');
  mkstore(join(parent, '.bantamkit', 'memory'));
  rmSync(join(parent, '.bantamkit', 'memory', 'facts'), { recursive: true });
  symlinkSync(join(bed, 'nowhere-at-all'), join(parent, '.bantamkit', 'memory', 'facts'));
  if (windows) {
    assert.throws(() => resolveProjectStore(parent), /memory store is unreadable/);
  } else {
    assert.equal(resolveProjectStore(parent).state, 'empty', 'the binding layer says empty');
  }
});

// ------------------------------------------------------------------------------- binding

test('the three states are three values, and the walk reports where it started', () => {
  const bed = fresh();
  const full = join(bed, 'full');
  mkstore(join(full, '.bantamkit', 'memory'), { a: 'd' });
  const empty = join(bed, 'empty');
  mkstore(join(empty, '.bantamkit', 'memory'));
  const none = join(bed, 'none');
  mkdirSync(none);

  const p = resolveProjectStore(full);
  assert.deepEqual([p.state, p.factCount, p.origin], ['populated', 1, 'walk']);
  assert.equal(p.searchedFrom, full);
  assert.equal(p.path, join(full, '.bantamkit', 'memory'));
  assert.equal(resolveProjectStore(empty).state, 'empty');

  const d = resolveProjectStore(none);
  assert.deepEqual([d.state, d.factCount, d.origin], ['designated', 0, 'walk']);
  assert.equal(d.path, join(none, '.bantamkit', 'memory'));
  assert.equal(readdirSync(none).length, 0, 'designating creates nothing');
});

test('the walk climbs to the nearest ancestor store and stops at the closest one', () => {
  const bed = fresh();
  mkstore(join(bed, '.bantamkit', 'memory'));
  const mid = join(bed, 'mid');
  mkstore(join(mid, '.bantamkit', 'memory'));
  const deep = join(mid, 'a', 'b');
  mkdirSync(deep, { recursive: true });
  assert.equal(discoverProjectStore(deep), join(mid, '.bantamkit', 'memory'));
  assert.equal(discoverProjectStore(join(bed, 'other')), join(bed, '.bantamkit', 'memory'));
});

/**
 * `Path.is_dir()` swallows only `_IGNORED_ERRNOS`, and EACCES is not one of them — MEASURED
 * against CPython, where `discover_project_store` through a `0o000` ancestor raises
 * PermissionError rather than skipping the candidate. `existsSync` answers `false` there and
 * would bind a different store in silence, which is why `pyIsDir` re-raises.
 */
test('the walk RAISES through an ancestor it cannot traverse', (t) => {
  const bed = fresh();
  const locked = join(bed, 'locked');
  mkdirSync(join(locked, 'x', 'y'), { recursive: true });
  chmodSync(locked, 0o000);
  let honoured = true;
  try {
    readdirSync(locked);
    honoured = false;
  } catch {
    /* the mode bits were honoured */
  }
  try {
    if (!honoured) {
      t.diagnostic('NOT MEASURED: this platform listed a 0o000 directory anyway (root?)');
      return;
    }
    for (const call of [discoverProjectStore, resolveProjectStore]) {
      assert.throws(() => call(join(locked, 'x', 'y')), (e) =>
        e.name === 'PermissionError' &&
        e.message === `[Errno 13] Permission denied: '${join(locked, 'x', 'y', '.bantamkit', 'memory')}'`);
    }
  } finally {
    chmodSync(locked, 0o755);
  }
});

test('resolve never disagrees with discover about the path', () => {
  const bed = fresh();
  mkstore(join(bed, 'p', '.bantamkit', 'memory'), { a: 'd' });
  for (const start of [bed, join(bed, 'p'), join(bed, 'p', 'x', 'y')]) {
    assert.equal(resolveProjectStore(start).path, discoverProjectStore(start));
  }
});

test('a store whose facts/ cannot be listed is never called empty', (t) => {
  const root = mkstore(join(fresh(), 'p', '.bantamkit', 'memory'), { a: 'd' });
  chmodSync(join(root, 'facts'), 0o000);
  let honoured = true;
  try {
    readdirSync(join(root, 'facts'));
    honoured = false;
  } catch {
    /* the mode bits were honoured */
  }
  try {
    if (!honoured) {
      t.diagnostic('NOT MEASURED: this platform listed facts/ at 0o000 anyway (root?)');
      return;
    }
    assert.throws(
      () => resolveProjectStore(join(root, '..', '..')),
      (e) =>
        e instanceof MemoryValidationError &&
        e.message ===
          `memory store is unreadable: ${join(root, 'facts')}: Permission denied; a store that ` +
            'could not be listed is not a store with nothing in it, and answering ' +
            "'empty' here is the conflation this binding exists to end",
    );
  } finally {
    chmodSync(join(root, 'facts'), 0o755);
  }
});

// ----------------------------------------------------------------------------- the pin

test('the pin outranks the walk and reports origin=pin with no searched_from', () => {
  const bed = fresh();
  const own = mkstore(join(bed, 'p', '.bantamkit', 'memory'), { a: 'd' });
  const elsewhere = mkstore(join(bed, 'elsewhere'), { b: 'd', c: 'd' });
  withEnv({ [MEMORY_DIR_ENV]: elsewhere }, () => {
    const b = resolveProjectStore(join(bed, 'p'));
    assert.deepEqual([b.path, b.state, b.factCount, b.origin, b.searchedFrom],
      [elsewhere, 'populated', 2, 'pin', null]);
    assert.equal(discoverProjectStore(join(bed, 'p')), elsewhere);
  });
  assert.equal(resolveProjectStore(join(bed, 'p')).path, own);
});

test('a blank pin is not a pin', () => {
  const bed = fresh();
  const own = mkstore(join(bed, 'p', '.bantamkit', 'memory'));
  for (const blank of ['', ' ', '\t\n']) {
    withEnv({ [MEMORY_DIR_ENV]: blank }, () => {
      assert.equal(resolveProjectStore(join(bed, 'p')).path, own);
    });
  }
});

test('a relative pin raises, and the message quotes it the way Python does', () => {
  withEnv({ [MEMORY_DIR_ENV]: 'relative/path' }, () => {
    assert.throws(() => resolveProjectStore(fresh()), (e) =>
      e.message ===
        "pinned memory store must be an absolute path, got 'relative/path' " +
          '(BANTAMKIT_MEMORY_DIR=relative/path); a relative pin is resolved against a cwd ' +
          'the MCP host chose, which is what the pin exists to override');
  });
});

test('a pin at nothing raises and creates nothing; a pin at a file says it is not a directory', () => {
  const bed = fresh();
  const missing = join(bed, 'missing');
  withEnv({ [MEMORY_DIR_ENV]: missing }, () => {
    assert.throws(() => resolveProjectStore(bed), (e) =>
      e.message ===
        `pinned memory store is unreachable: ${missing}: ${notFound()} ` +
          `(BANTAMKIT_MEMORY_DIR=${missing}); nothing was created`);
  });
  assert.equal(readdirSync(bed).length, 0);

  const file = join(bed, 'pinfile');
  writeFileSync(file, 'x');
  withEnv({ [MEMORY_DIR_ENV]: file }, () => {
    assert.throws(() => resolveProjectStore(bed), (e) =>
      e.message ===
        `pinned memory store is not a directory: ${file} (BANTAMKIT_MEMORY_DIR=${file})`);
  });
});

test('the pin expands ~ itself, because an MCP host passes env with no shell to do it', () => {
  const bed = fresh();
  const home = join(bed, 'home');
  const store = mkstore(join(home, 'mem'));
  sandboxed(home, () =>
    withEnv({ [MEMORY_DIR_ENV]: '~/mem' }, () => {
      assert.equal(resolveProjectStore(bed).path, store);
    }));
});

// ---------------------------------------------------------------------------- the grants

test('a missing, empty or null config yields no grants', () => {
  const bed = fresh();
  const store = mkstore(join(bed, '.bantamkit', 'memory'));
  const config = join(bed, '.bantamkit', 'config.yaml');
  assert.deepEqual(loadGrants(store), []);
  for (const text of ['', '\n', '# just a comment\n', 'other: keys\n', '---\nextra_stores: []\n']) {
    writeFileSync(config, text);
    assert.deepEqual(loadGrants(store), [], JSON.stringify(text));
  }
});

test('grants resolve relative to the config, in every spelling PyYAML accepts', () => {
  const bed = fresh();
  const store = mkstore(join(bed, '.bantamkit', 'memory'));
  const config = join(bed, '.bantamkit', 'config.yaml');
  const target = mkstore(join(bed, 'granted'));
  for (const text of [
    'extra_stores:\n- ../granted\n',
    'extra_stores:\n  - ../granted\n',
    'extra_stores: [../granted]\n',
    "extra_stores:\n- '../granted'\n",
    'extra_stores: ["../granted"]\n',
    '# a comment first\nextra_stores:\n- ../granted\n',
  ]) {
    writeFileSync(config, text);
    assert.deepEqual(loadGrants(store), [target], JSON.stringify(text));
  }
});

test('a config that is wrong is surfaced, never silently dropped', () => {
  const bed = fresh();
  const store = mkstore(join(bed, '.bantamkit', 'memory'));
  const config = join(bed, '.bantamkit', 'config.yaml');
  const invalid = (text, tail) => {
    writeFileSync(config, text);
    assert.throws(() => loadGrants(store), (e) =>
      e instanceof MemoryValidationError && e.message === `invalid memory config ${config}: ${tail}`,
      JSON.stringify(text));
  };
  invalid('- a\n- b\n', 'expected a mapping');
  invalid('just a scalar\n', 'expected a mapping');
  invalid('extra_stores: 3\n', 'extra_stores must be a list of paths');
  invalid('extra_stores:\n- 3\n', 'extra_stores must be a list of paths');

  writeFileSync(config, 'extra_stores:\n- ./nope\n');
  assert.throws(() => loadGrants(store), (e) =>
    e.message === `granted store does not exist: ${join(bed, '.bantamkit', 'nope')} (from ${config})`);

  rmSync(config);
  mkdirSync(config);
  assert.throws(() => loadGrants(store), (e) =>
    e.message === `invalid memory config ${config}: not a file`);
});

// -------------------------------------------------------------------------- the component

test('normalize_name bends the model spelling to the store contract', () => {
  assert.deepEqual(
    ['  A_Fact Name ', 'already-fine', 'MiXeD_case', 'a  b', '', '_'].map(normalizeName),
    ['a-fact-name', 'already-fine', 'mixed-case', 'a--b', '', '-'],
  );
  assert.equal(normalizeName(null), null, 'a non-string is handed on so store validation speaks');
});

test('the layer label is the project directory, not the store directory', () => {
  assert.deepEqual(
    ['/a/b/.bantamkit/memory', '/a/b/memory', '/memory', '/a/.bantamkit/memory/'].map(layerLabel),
    ['b', 'memory', 'memory', 'a'],
  );
});

test('the profile store follows HOME, which is what a host can actually set', () => {
  const home = fresh();
  sandboxed(home, () => assert.equal(profileStore(), join(home, '.bantamkit', 'memory')));
});

test('--store: a hit carries no layer tag, and layered prepends one', () => {
  const bed = fresh();
  const home = join(bed, 'home');
  mkdirSync(home);
  const direct = mkstore(join(bed, 'direct'), { 'probe-fact-one': 'a probe fact about widgets' });
  sandboxed(home, () => {
    assert.equal(
      new Memory(direct, frozen()).recall('probe fact widgets'),
      '[probe-fact-one] (project) a probe fact about widgets\nb',
    );
    const project = join(bed, 'companyB');
    mkstore(join(project, '.bantamkit', 'memory'), { 'x-fact': 'd one' });
    assert.equal(
      Memory.layered(project, frozen()).recall('d one'),
      '[project] [x-fact] (project) d one\nb',
    );
  });
});

test('layered binds project, then the grants, then the profile', () => {
  const bed = fresh();
  const home = join(bed, 'home');
  mkstore(join(home, '.bantamkit', 'memory'));
  const project = join(bed, 'companyA');
  mkstore(join(project, '.bantamkit', 'memory'));
  mkstore(join(bed, 'shared'));
  writeFileSync(join(project, '.bantamkit', 'config.yaml'), 'extra_stores:\n- ../../shared\n');
  sandboxed(home, () => {
    assert.deepEqual(Memory.layered(project, frozen()).layerLabels(), ['project', 'extra:shared', 'profile']);
  });
});

// ---------------------------------------------------- one directory is one layer (J47-2)
//
// The Node twin of `test_memory_dream.py`'s two nodes of the same name, landed for the
// reference by J47-1 (0844ccb). `resolveProjectStore` WALKS UP from the cwd, so a session
// with no `.bantamkit` anywhere above it resolves `~/.bantamkit/memory` — the profile store
// — as its PROJECT store, and `layered` used to push that same directory a second time as
// "profile". `dream` was then handed one directory twice: every fact collided with itself,
// was merged into itself, and the "profile copy" archived was the same file. It archived 20
// of 20 of the user's real facts on 2026-09-10. `dreamOutcome` itself needs no change: not
// pushing the duplicate layer routes into the `no-profile-layer` outcome that already exists.

test('one directory is one layer when the walk lands on the profile store', () => {
  const home = fresh();
  const work = join(home, 'work');
  mkdirSync(work, { recursive: true });
  const profile = mkstore(join(home, '.bantamkit', 'memory'), {
    'alpha-routing-rule': 'how the alpha router picks a shard',
  });

  sandboxed(home, () => {
    const memory = Memory.layered(work, frozen());
    const outcome = memory.dreamOutcome(false);

    assert.equal(memory.store.root, profile, 'the walk landed on the profile store itself');
    assert.equal(outcome.status, 'no-profile-layer');
    assert.deepEqual([outcome.merged, outcome.consumed], [0, 0]);
    assert.deepEqual(readdirSync(join(profile, 'facts')), ['alpha-routing-rule.md']);
    assert.equal(readdirSync(join(profile, 'archive')).length, 0, 'nothing was consumed');
    assert.deepEqual(memory.layerLabels(), ['project']);
  });
});

test('one directory is one layer through a symlinked home', () => {
  // The Stop hook's `samePath` needed `fs.realpathSync` rather than `path.resolve` for
  // exactly this shape — macOS `/var` vs `/private/var` — and that is the case this pins:
  // without resolving symlinks, the walk's spelling and `profileStore()`'s spelling of one
  // directory compare unequal as strings and the guard would let the self-merge through.
  const bed = fresh();
  const real = join(bed, 'real-home');
  mkdirSync(join(real, 'work'), { recursive: true });
  const link = join(bed, 'linked-home');
  symlinkSync(real, link, 'dir');
  const profile = mkstore(join(link, '.bantamkit', 'memory'), {
    'beta-timezone': 'which timezone the operator works in',
  });

  sandboxed(link, () => {
    const memory = Memory.layered(join(real, 'work'), frozen());
    const outcome = memory.dreamOutcome(false);

    assert.notEqual(memory.store.root, profile, 'the two spellings really differ as strings');
    assert.equal(outcome.status, 'no-profile-layer');
    assert.deepEqual(readdirSync(join(profile, 'facts')), ['beta-timezone.md']);
    assert.equal(readdirSync(join(profile, 'archive')).length, 0);
  });
});

test('one directory is one layer when HOME is spelled through a symlink AND a `..`', () => {
  // J47-3B. The two nodes above pass with `fs.realpathSync`, and this one does not:
  // `realpathSync` hands its argument to `path.resolve` FIRST, which pops `..` lexically —
  // before the symlink in front of it has been resolved. `os.path.realpath` and the kernel
  // pop it AFTER. So `<bed>/link/..` is `<bed>/deep` to the reference and `<bed>` to Node,
  // and one directory is bound as two layers: the 2026-09-10 self-merge, still live.
  const bed = fresh();
  const deep = join(bed, 'deep');
  mkdirSync(join(deep, 'real'), { recursive: true });
  mkdirSync(join(deep, 'work'), { recursive: true });
  symlinkSync(join(deep, 'real'), join(bed, 'link'), 'dir');
  // Spelled by hand, not with `join`: `join` would normalise the `..` away and the bed
  // would stop being the bed. `os.path.isdir` on it is True — the kernel reads it as `deep`.
  const home = `${join(bed, 'link')}/..`;
  const profile = mkstore(join(deep, '.bantamkit', 'memory'), {
    'gamma-deploy-rule': 'which branch the deploy watches',
  });

  sandboxed(home, () => {
    const memory = Memory.layered(join(deep, 'work'), frozen());
    const outcome = memory.dreamOutcome(false);

    assert.equal(memory.store.root, profile, 'the walk landed on the profile store itself');
    assert.deepEqual(memory.layerLabels(), ['project']);
    assert.equal(outcome.status, 'no-profile-layer');
    assert.deepEqual([outcome.merged, outcome.consumed], [0, 0]);
    assert.deepEqual(readdirSync(join(profile, 'facts')), ['gamma-deploy-rule.md']);
    assert.equal(readdirSync(join(profile, 'archive')).length, 0, 'nothing was consumed');
  });
});

// ------------------------------------------------------------- the four nothings, verbatim

test('a populated store that misses says so, and makes no claim about the binding', () => {
  const bed = fresh();
  const home = join(bed, 'home');
  mkdirSync(home);
  const project = join(bed, 'p');
  mkstore(join(project, '.bantamkit', 'memory'), { a: 'a description' });
  sandboxed(home, () => {
    assert.equal(
      Memory.layered(project, frozen()).recall('nothing-shares-this'),
      'no memories matched. Try different words, or proceed without.',
    );
  });
});

test('an empty store bound as its own says which binding, and how to move it', () => {
  const bed = fresh();
  const home = join(bed, 'home');
  mkdirSync(home);
  const project = join(bed, 'companyA');
  const store = mkstore(join(project, '.bantamkit', 'memory'));
  sandboxed(home, () => {
    assert.equal(
      Memory.layered(project, frozen()).recall('anything'),
      'no memories to search: nothing is saved in any layer bound here. The project store ' +
        `${store} is empty; it is ${project}'s own store, bound without the walk leaving ` +
        'that directory. That is a binding, not a search result — if your facts are in ' +
        'another store, set BANTAMKIT_MEMORY_DIR to its absolute path and restart; ' +
        'otherwise save a memory to start this one.',
    );
  });
});

test('a walk that climbed says it climbed, and from where', () => {
  const bed = fresh();
  const home = join(bed, 'home');
  mkdirSync(home);
  const project = join(bed, 'companyA');
  const store = mkstore(join(project, '.bantamkit', 'memory'));
  const deep = join(project, 'sub', 'deeper');
  mkdirSync(deep, { recursive: true });
  sandboxed(home, () => {
    assert.equal(
      Memory.layered(deep, frozen()).recall('anything'),
      'no memories to search: nothing is saved in any layer bound here. The project store ' +
        `${store} is empty; it was bound by walking up from ${deep}, which has no store of ` +
        'its own. That is a binding, not a search result — if your facts are in another ' +
        'store, set BANTAMKIT_MEMORY_DIR to its absolute path and restart; otherwise save ' +
        'a memory to start this one.',
    );
  });
});

test('a store nobody had says it was created for this session', () => {
  const bed = fresh();
  const home = join(bed, 'home');
  mkdirSync(home);
  const project = join(bed, 'lonely');
  mkdirSync(project);
  sandboxed(home, () => {
    assert.equal(
      Memory.layered(project, frozen()).recall('anything'),
      'no memories to search: nothing is saved in any layer bound here. No memory store ' +
        `existed at or above ${project}, so the empty ${join(project, '.bantamkit', 'memory')} ` +
        'was created for this session. That is a binding, not a search result — if your ' +
        'facts are in another store, set BANTAMKIT_MEMORY_DIR to its absolute path and ' +
        'restart; otherwise save a memory to start this one.',
    );
  });
});

test('a pinned empty store blames the pin, not the walk', () => {
  const bed = fresh();
  const home = join(bed, 'home');
  mkdirSync(home);
  const pinned = mkstore(join(bed, 'pinned'));
  sandboxed(home, () =>
    withEnv({ [MEMORY_DIR_ENV]: pinned }, () => {
      assert.equal(
        Memory.layered(bed, frozen()).recall('anything'),
        'no memories to search: nothing is saved in any layer bound here. The project ' +
          `store ${pinned} is empty; BANTAMKIT_MEMORY_DIR pinned it. That is a binding, ` +
          'not a search result — if your facts are in another store, set ' +
          'BANTAMKIT_MEMORY_DIR to its absolute path and restart; otherwise save a memory ' +
          'to start this one.',
      );
    }));
});

test('when the bound store IS the profile layer, the advice inverts', () => {
  const bed = fresh();
  const home = join(bed, 'home');
  const store = mkstore(join(home, '.bantamkit', 'memory'));
  const project = join(home, 'a-project');
  mkdirSync(project);
  sandboxed(home, () => {
    assert.equal(
      Memory.layered(project, frozen()).recall('anything'),
      'no memories to search: nothing is saved in any layer bound here. The project store ' +
        `${store} is empty; it was bound by walking up from ${project}, which has no store ` +
        'of its own. That is a binding, not a search result — if your facts are in another ' +
        'store, set BANTAMKIT_MEMORY_DIR to its absolute path and restart. Do NOT save ' +
        `here to start it: ${store} is also the profile layer, so a memory saved there ` +
        'answers for every project on this machine that has no store of its own — give ' +
        'this project a store of its own instead.',
    );
  });
});

/**
 * THE W5 PAIR. One unreadable grant, two sentences — and the wrong one tells the operator
 * to stop looking. Both are reproduced because both are what production says today.
 */
test('an unlistable grant is named as unreadable; a dangling one is not — the deferred defect', (t) => {
  const bed = fresh();
  const home = join(bed, 'home');
  mkdirSync(home);
  const build = (label, shape) => {
    const project = join(bed, label);
    const store = mkstore(join(project, '.bantamkit', 'memory'));
    const grant = join(bed, `granted-${label}`);
    mkdirSync(grant);
    writeFileSync(join(project, '.bantamkit', 'config.yaml'), `extra_stores:\n- ${grant}\n`);
    if (shape === 'mode') {
      mkdirSync(join(grant, 'facts'));
      chmodSync(join(grant, 'facts'), 0o311);
    } else {
      symlinkSync(join(bed, 'nowhere-at-all'), join(grant, 'facts'));
    }
    return { project, store, grant };
  };

  const unlistable = build('mode', 'mode');
  let honoured = true;
  try {
    readdirSync(join(unlistable.grant, 'facts'));
    honoured = false;
  } catch {
    /* honoured */
  }
  try {
    if (honoured) {
      sandboxed(home, () => {
        assert.equal(
          Memory.layered(unlistable.project, frozen()).recall('anything'),
          'no memories matched, and that is not evidence there are none: ' +
            `${unlistable.grant} could not be read. The project store ${unlistable.store} is ` +
            `empty; it is ${unlistable.project}'s own store, bound without the walk leaving ` +
            'that directory. That is a binding, not a search result — if your facts are in ' +
            'another store, set BANTAMKIT_MEMORY_DIR to its absolute path and restart; ' +
            'otherwise save a memory to start this one.',
        );
      });
    } else {
      t.diagnostic('NOT MEASURED: this platform listed a 0o311 directory anyway (root?)');
    }
  } finally {
    chmodSync(join(unlistable.grant, 'facts'), 0o755);
  }

  const dangling = build('dangling', 'dangling');
  const tail = `The project store ${dangling.store} is empty; it is ${dangling.project}'s ` +
    'own store, bound without the walk leaving that directory. That is a binding, not a ' +
    'search result — if your facts are in another store, set BANTAMKIT_MEMORY_DIR to its ' +
    'absolute path and restart; otherwise save a memory to start this one.';
  sandboxed(home, () => {
    assert.equal(
      Memory.layered(dangling.project, frozen()).recall('anything'),
      // W5's PAIR IS A POSIX PAIR. On Windows the bare symlink is a FILE reparse point,
      // `count_facts` raises NotADirectoryError, and the grant IS named as unreadable —
      // so the two sentences converge and the wrong one is not said. Measured against the
      // reference on run 32646521489; on POSIX the pair still stands.
      process.platform === 'win32'
        ? 'no memories matched, and that is not evidence there are none: ' +
          `${dangling.grant} could not be read. ${tail}`
        : `no memories to search: nothing is saved in any layer bound here. ${tail}`,
      'count_facts maps the dangling symlink to 0 on POSIX, so the layer is not unreadable',
    );
  });
});

// -------------------------------------------------------------------------------- saving

test('save answers with the store contract, in the words the model reads', () => {
  const bed = fresh();
  const home = join(bed, 'home');
  mkdirSync(home);
  const mem = new Memory(join(bed, 'store'), frozen());
  assert.equal(mem.save('project', 'Fact_0', 'w0a w0b w0c w0d', 'body'), "saved 'fact-0'");
  assert.equal(
    mem.save('project', 'probe', 'w0a w0b w0c w0d', 'body'),
    "similar memory 'fact-0' already exists — save under that SAME name to update it, " +
      'or skip. Do not rename to force a copy.',
  );
  assert.equal(
    mem.save('notes', 'x', 'd', 'b'),
    "error: invalid type 'notes'; must be one of ['feedback', 'project', 'reference', 'user']",
  );
});

test('a budget refusal names a remedy the model actually has', () => {
  const mem = new Memory(join(fresh(), 'store'), frozen({ indexBudget: 10 }));
  assert.equal(
    mem.save('project', 'a', 'a long description', 'b'),
    'error: memory index is 41 bytes, budget is 10: run compact() or tersen descriptions. ' +
      'Nothing was saved and retrying will not help — shorten the description, or save ' +
      'under the name of an existing memory to replace it. Or call `memory_compact` to ' +
      'archive the stalest facts and free room — nothing is deleted.',
  );
});

/** Six descriptions far enough apart that the dedupe nudge does not swallow them. */
const DISTINCT = [
  'how the widget cache is invalidated on deploy',
  'which team owns the payments api and where its runbook lives',
  'the staging database credentials rotate every friday at noon',
  'why the nightly build skips the integration suite on windows',
  'the customer prefers tabs over spaces in every generated file',
  'where the grafana dashboard for queue depth is bookmarked',
];

test('compact archives the stalest facts and the reply is the only place the model learns which', () => {
  const root = join(fresh(), 'store');
  const roomy = new Memory(root, frozen({ indexBudget: 1000 }));
  for (const [i, description] of DISTINCT.entries()) {
    assert.ok(roomy.save('project', `fact-${i}`, description, 'b').startsWith('saved '));
  }
  // The same store reopened at a budget it is already over — the state a refusal finds it in.
  const mem = new Memory(root, frozen({ indexBudget: 300 }));
  const first = mem.compactOutcome();
  assert.equal(first.status, 'archived');
  assert.ok(first.archived >= 1);
  assert.ok(first.indexBefore > first.indexAfter);
  assert.equal(first.budget, 300);
  assert.equal(
    first.reply.split('\n')[0],
    `archived ${first.archived} memories; the index went from ${first.indexBefore} to ${first.indexAfter} ` +
      `bytes against a 300-byte budget, leaving ${300 - first.indexAfter} bytes of headroom. These moved to ` +
      `${join(root, 'archive')} and are NOT deleted — they can be restored by name:`,
  );
  const moved = readdirSync(join(root, 'archive')).filter((n) => n.endsWith('.md')).sort();
  assert.equal(moved.length, first.archived);
  assert.deepEqual(
    first.reply.split('\n').slice(1),
    moved.map((n) => `- ${n.slice(0, -3)} (project) — ${DISTINCT[Number(n.slice(5, -3))]}`),
  );
  const second = mem.compactOutcome();
  assert.equal(second.status, 'nothing-archived');
  assert.equal(second.archived, 0);
  assert.equal(second.reply, mem.compact(), 'a third call answers the same prose');
  assert.match(second.reply, /^nothing archived: the index is \d+ bytes against a 300-byte budget, already at or under the \d+-byte compaction target\.$/);
});

test('a negative reserve is floored to zero in the store, not the handler', () => {
  // The manifest's `minimum: 0` is advisory; the ONLY clamp is `MemoryStore.compact`'s
  // `max(0, min(reserve, budget // 2))` (the handler's second floor was dropped in 6b966e5).
  // `-5` therefore answers exactly what `0` answers: a target AT the budget, nothing archived.
  const mem = new Memory(join(fresh(), 'store'), frozen({ indexBudget: 1000 }));
  assert.ok(mem.save('project', 'fact-a', 'alpha topic here', 'a').startsWith('saved '));
  assert.ok(mem.save('project', 'fact-b', 'beta topic there', 'b').startsWith('saved '));
  const negative = mem.store.compact(-5);
  const zero = mem.store.compact(0);
  assert.deepEqual(negative, zero);
  assert.equal(negative.reserve, 0);
  assert.equal(negative.target, 1000);
  assert.deepEqual(negative.archived, []);
  assert.equal(mem.compact(-5), mem.compact(0));
});

test('a profile-layer fact survives a compaction of the project store', () => {
  /**
   * Only the writable project layer is compacted. `Memory.layered` wires grants and the
   * profile store into `_layers` and leaves `store` as the project store alone, so
   * `compactOutcome` — which reaches `store` and nothing else — cannot see them.
   *
   * NON-VACUOUS BY CONSTRUCTION. `layered` opens the profile store at the default budget
   * and `indexBudget` is readonly, so the reference's move (drop the profile budget to 1)
   * is not available here; instead the profile store is built OVER the default 24000-byte
   * budget on disk before `layered` opens it — 400 facts whose index lines run past 60
   * bytes each. A compaction that reached the profile layer WOULD archive there. Proved
   * 2026-08-28 by making `compactOutcome` also call `compact` on every read-only layer
   * (in `dist/`, then reverted): this test went red at the `facts/` count — `223 !== 401`,
   * 178 profile facts archived — and green again once the loop was gone.
   */
  const bed = fresh();
  const home = join(bed, 'home');
  const profile = join(home, '.bantamkit', 'memory');
  const crowd = Object.fromEntries(
    Array.from({ length: 400 }, (_, i) => [
      `crowd-fact-${String(i).padStart(3, '0')}`,
      `crowd lesson number ${i} about a wholly distinct subject on this machine`,
    ]),
  );
  mkstore(profile, { 'profile-fact': 'a lesson that belongs to every project on this machine', ...crowd });
  const project = join(bed, 'repo');
  mkdirSync(join(project, '.bantamkit', 'memory'), { recursive: true });
  sandboxed(home, () => {
    const roomy = Memory.layered(project, frozen({ indexBudget: 1000 }));
    assert.notEqual(roomy.store.root, profile);
    assert.deepEqual(roomy.layerLabels(), ['project', 'profile']);
    for (const [i, description] of DISTINCT.entries()) {
      assert.ok(roomy.save('project', `fact-${i}`, description, 'b').startsWith('saved '));
    }
    // Reopened over its budget, beside a profile store over ITS budget.
    const mem = Memory.layered(project, frozen({ indexBudget: 300 }));
    const profileStore = mem.layers[mem.layers.length - 1][1];
    assert.equal(profileStore.root, profile);
    const profileIndex = Buffer.byteLength(profileStore.indexText(), 'utf8');
    assert.ok(profileIndex > profileStore.indexBudget, `profile index ${profileIndex} must exceed its ${profileStore.indexBudget}-byte budget for this test to mean anything`);
    const outcome = mem.compactOutcome();
    assert.equal(outcome.status, 'archived');
    assert.ok(existsSync(join(profile, 'facts', 'profile-fact.md')));
    assert.equal(readdirSync(join(profile, 'facts')).filter((n) => n.endsWith('.md')).length, 401);
    assert.equal(readdirSync(join(profile, 'archive')).filter((n) => n.endsWith('.md')).length, 0);
    assert.ok(!outcome.reply.includes('profile-fact'));
    assert.match(mem.recall('lesson every project machine'), /\[profile\] \[profile-fact\]/);
  });
});

test('k is the model asking for more, never for less than the store default', () => {
  const bed = fresh();
  const root = mkstore(join(bed, 's'), { 'fact-a': 'shared token', 'fact-b': 'shared token', 'fact-c': 'shared token' });
  const mem = new Memory(root, frozen());
  assert.equal(mem.recall('shared', 1).split('\n\n').length, 3, 'k=1 is raised to the default 3');
  assert.equal(mem.recall('shared', 2).split('\n\n').length, 3);
});

test('a corrupt read-only layer is skipped; the project layer failing is a real error', (t) => {
  const bed = fresh();
  const home = join(bed, 'home');
  mkdirSync(home);
  const project = join(bed, 'p');
  const store = mkstore(join(project, '.bantamkit', 'memory'), { a: 'shared token' });
  const grant = mkstore(join(bed, 'granted'));
  writeFileSync(join(grant, 'facts', 'broken.md'), 'no frontmatter at all\n');
  writeFileSync(join(project, '.bantamkit', 'config.yaml'), `extra_stores:\n- ${grant}\n`);
  sandboxed(home, () => {
    assert.match(Memory.layered(project, frozen()).recall('shared'), /^\[project\] \[a\] /);
    writeFileSync(join(store, 'facts', 'broken.md'), 'no frontmatter at all\n');
    assert.throws(() => Memory.layered(project, frozen()).recall('shared'), MemoryValidationError);
  });
  t.diagnostic('the grant raised inside recall and was skipped; the project layer was not');
});

// ------------------------------------- roadmap #6: the precision gate, from the component
//
// The same four nodes `runtime-py/tests/test_memory_component.py` holds under the same
// heading. The store-level arithmetic is pinned in `store.test.mjs`; what these add is the
// LAYERED behaviour, which no store-level node can see: the ratio is measured per layer,
// against each layer's own top hit, and a bad ratio comes back as the argument error it is
// rather than as an `unreadable` count.

test('the gate default changes no layered recall', () => {
  // The no-op proof at the surface every caller actually uses.
  assert.equal(RECALL_MIN_SCORE_RATIO, 0.0);
  const bed = fresh();
  const home = join(bed, 'home');
  mkstore(join(home, '.bantamkit', 'memory'), { gamma: 'alpha oscar papa quebec' });
  const project = join(bed, 'companyA');
  mkstore(join(project, '.bantamkit', 'memory'), {
    alpha: 'alpha bravo charlie delta',
    weak: 'alpha xray yankee zulu',
  });
  sandboxed(home, () => {
    const mem = Memory.layered(project, frozen({ k: 9 }));
    const plain = mem.recallOutcome('alpha bravo charlie delta');
    assert.equal(plain.returned, 3);
    assert.equal(mem.recallOutcome('alpha bravo charlie delta', null, 0.0).reply, plain.reply);
    assert.equal(
      mem.recallOutcome('alpha bravo charlie delta', null, RECALL_MIN_SCORE_RATIO).reply,
      plain.reply,
    );
  });
});

test('the gate is measured per layer and never across layers', () => {
  // A profile fact does not have to out-score the project store's top hit.
  //
  // Project scores 4 and 1; profile scores 1. At `minRatio=1.0` the project layer keeps only
  // its own best — so `weak` goes — while `gamma` survives, because 1 is the best score in
  // the store that holds it. A gate applied to the MERGED list would have dropped `gamma`
  // too, and this is the assertion that tells them apart.
  const bed = fresh();
  const home = join(bed, 'home');
  mkstore(join(home, '.bantamkit', 'memory'), { gamma: 'alpha oscar papa quebec' });
  const project = join(bed, 'companyA');
  mkstore(join(project, '.bantamkit', 'memory'), {
    alpha: 'alpha bravo charlie delta',
    weak: 'alpha xray yankee zulu',
  });
  sandboxed(home, () => {
    const out = Memory.layered(project, frozen({ k: 9 })).recallOutcome(
      'alpha bravo charlie delta',
      null,
      1.0,
    );
    assert.equal(out.returned, 2);
    assert.ok(out.reply.includes('[alpha]') && out.reply.includes('[gamma]'));
    assert.ok(!out.reply.includes('[weak]'));
  });
});

test('a bad ratio surfaces as the error it is, not as an unreadable layer', () => {
  // The writable project layer is reached FIRST, so the range check re-raises out of it
  // instead of being caught by the read-only-layer arm and counted as a corrupt grant.
  const bed = fresh();
  const home = join(bed, 'home');
  mkdirSync(home, { recursive: true });
  const project = join(bed, 'companyA');
  mkstore(join(project, '.bantamkit', 'memory'), { alpha: 'alpha bravo' });
  sandboxed(home, () => {
    assert.throws(
      () => Memory.layered(project, frozen()).recallOutcome('alpha', null, 1.5),
      (e) => {
        assert.ok(e instanceof MemoryValidationError);
        assert.equal(e.message, 'recall min-score ratio must be between 0.0 and 1.0');
        return true;
      },
    );
  });
});

test('Memory.recall passes the ratio through to the outcome', () => {
  // `Memory.recall` is the string half of `recallOutcome`; the gate must reach it.
  const root = mkstore(join(fresh(), 'm'), {
    alpha: 'alpha bravo charlie delta',
    weak: 'alpha xray yankee zulu',
  });
  const mem = new Memory(root, frozen({ k: 9 }));
  assert.ok(mem.recall('alpha bravo charlie delta').includes('[weak]'));
  assert.ok(!mem.recall('alpha bravo charlie delta', null, 1.0).includes('[weak]'));
});
