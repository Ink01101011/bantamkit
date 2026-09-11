/**
 * recall-strings — the sentences the binding layer produces, Python against Node.
 *
 * THE PROPERTY: for every binding situation, Node returns the BYTE-IDENTICAL string Python
 * returns. Not the same meaning. These are what an agent acts on when its memory appears
 * empty, and job37 exists because "empty" and "unreadable" were once the same answer, so a
 * one-word difference here is the defect and not a cosmetic one.
 *
 * BOTH REGISTRATIONS RUN. `.mcp.json` and the user-scope config invoke the server with no
 * `--store`, so production is `Memory.layered` and its recall lines carry a `[project] ` tag
 * the `--store` form never emits. Every scenario below names which registration it is, and
 * the two forms are exercised over the same fixtures.
 *
 * HOW A SCENARIO WORKS, and it is `store.mjs`'s shape on purpose: one spec is materialised
 * twice, into `py/` and `node/`, so both sides start from the same bytes; `HOME` and
 * `BANTAMKIT_MEMORY_DIR` are set to paths inside each side's own bed, so the profile layer
 * and the pin are per-side and NEITHER SIDE CAN REACH THE OPERATOR'S REAL STORE. Then the
 * answers are compared as exact strings and the whole tree as bytes — a scenario that
 * answers correctly while stamping a fact in a read-only grant fails on the tree.
 *
 * The bed is realpath'd first: `_resolved_base` resolves before it walks, and on macOS
 * `/var` is a symlink, so an unresolved bed would have every message naming a path the
 * scrubber below could not find.
 */
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  readlinkSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { userInfo } from 'node:os';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'recall-strings';
export const summary = 'the binding layer: every sentence an empty recall can produce';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'layers_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');
const TODAY = '2026-08-23';

/** One answer, rendered as the one string a comparison can point at. */
const answer = (value) => {
  if (Array.isArray(value)) return value.map(unb64).join(', ');
  if (value && typeof value === 'object' && value.error) {
    return `${value.error.type}: ${unb64(value.error.message)}`;
  }
  return typeof value === 'string' ? unb64(value) : JSON.stringify(value);
};

/**
 * Take the side's own bed out of a message before comparing.
 *
 * The two sides run in `py/` and `node/`, and every one of these sentences PRINTS a path, so
 * an un-scrubbed comparison would fail on the one difference the harness itself created. The
 * path is not dropped: it becomes a marker, so a message naming the WRONG path still differs.
 */
const scrub = (text, root) => {
  // BOTH spellings: `str(OSError)` prints the path through `%r`, which escapes a backslash,
  // so on Windows the bed also appears doubled. Off Windows the two are the same string.
  const escaped = root.split('\\').join('\\\\');
  return text.split(root).join('<ROOT>').split(escaped).join('<ROOT>');
};

// -------------------------------------------------------------------------- fixtures

const factFile = (n, { description = `about ${n}`, type = 'project', created = '2026-08-01', last = 'null', links = '[]', body = 'b' } = {}) =>
  `---\nname: ${n}\ndescription: ${description}\ntype: ${type}\ncreated: ` +
  `${created === null ? 'null' : `'${created}'`}\nlast_recalled: ${last}\nlinks: ${links}\n---\n\n${body}\n`;

/** A store at `path`, as bytes rather than as a call into the code under test. */
function storeSpec(path, facts = {}) {
  const spec = { dirs: [`${path}/facts`, `${path}/archive`], files: {} };
  for (const [n, description] of Object.entries(facts)) {
    spec.files[`${path}/facts/${n}.md`] = factFile(n, { description });
  }
  return spec;
}

/** Merge fixture fragments; later ones win per key. */
function merge(...parts) {
  const out = { dirs: [], files: {}, symlinks: [], modes: {} };
  for (const part of parts) {
    out.dirs.push(...(part.dirs ?? []));
    Object.assign(out.files, part.files ?? {});
    out.symlinks.push(...(part.symlinks ?? []));
    Object.assign(out.modes, part.modes ?? {});
  }
  return out;
}

/** Materialise one spec at `root`. `{ROOT}` in a file body becomes this side's own bed. */
function materialise(root, spec) {
  mkdirSync(root, { recursive: true });
  for (const dir of spec.dirs ?? []) mkdirSync(join(root, dir), { recursive: true });
  for (const [path, content] of Object.entries(spec.files ?? {})) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), Buffer.from(content.split('{ROOT}').join(root), 'utf8'));
  }
  for (const [link, target] of spec.symlinks ?? []) {
    mkdirSync(dirname(join(root, link)), { recursive: true });
    symlinkSync(target.split('{ROOT}').join(root), join(root, link));
  }
}

/**
 * Apply one fixture spec's modes to a bed, or put them back.
 *
 * platform-checked: BOTH BEDS GET THE SAME CALL FROM THE SAME SPEC — `applyModes` is invoked
 * once per side (`for (const side of ['py', 'node'])`) with one `spec`, so a platform that
 * ignores the mode removes the restriction from the reference's tree and the port's tree
 * identically. That is the property this suite's comparison rests on, and it holds on every
 * platform because it is a property of the harness rather than of the filesystem.
 *
 * WHAT IS NOT CLAIMED, and it is not claimed because it is not measured: whether the
 * resulting comparison still has teeth on Windows. It does not — an unrestricted bed answers
 * a question nobody asked — and this repository has no Windows run to show it with, because
 * Actions is off on this account. `recall-strings.mjs` shows the shape that would measure it:
 * a probe that tries the denied operation, and a `notes.push('NOT MEASURED: ...')` when the
 * mode was not honoured. Registered rather than written here, because a sentence asserting
 * Windows behaviour nobody has run is the thing this gate's own docstring warns about.
 */
const applyModes = (root, spec, on) => {
  for (const [path, mode] of Object.entries(spec.modes ?? {})) {
    chmodSync(join(root, path), on ? mode : 0o755);
  }
};

/**
 * Every path under `root`, with what it is and what it holds.
 *
 * A local walker rather than `store.mjs`'s: that one is private to its module and this suite
 * must not edit it. The shape is deliberately the same — symlink targets and directory
 * entries in, not just file bytes — so a port that answered correctly while stamping a fact
 * into a read-only grant still fails.
 */
function manifest(root) {
  const lines = [];
  const walk = (dir) => {
    let entries;
    try {
      entries = readdirSync(dir);
    } catch (e) {
      lines.push(`${relative(root, dir) || '.'}\tUNREADABLE\t${e.code}`);
      return;
    }
    for (const entry of entries.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))) {
      const full = join(dir, entry);
      const rel = relative(root, full);
      const st = lstatSync(full);
      if (st.isSymbolicLink()) lines.push(`${rel}\tlink\t${scrub(readlinkSync(full), root)}`);
      else if (st.isDirectory()) {
        lines.push(`${rel}\tdir`);
        walk(full);
      } else {
        const bytes = readFileSync(full);
        lines.push(`${rel}\tfile\t${bytes.length}\t${scrub(bytes.toString('utf8'), root)}`);
      }
    }
  };
  walk(root);
  return `${lines.join('\n')}\n`;
}

// ------------------------------------------------------------------------ call shapes

const recall = (query, k = null) => ({ op: 'recall', args: [b64(query), k] });
const save = (type, n, description, body, links = []) => ({
  op: 'save',
  args: [b64(type), b64(n), b64(description), b64(body), links.map(b64)],
});
const layersOp = () => ({ op: 'layers' });

/** The Node side of one scenario, shaped exactly like `layers_ref.py`'s answer. */
async function runNode(mod, request, env) {
  const before = new Map(Object.keys(env).map((k) => [k, process.env[k]]));
  for (const [k, v] of Object.entries(env)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  const encode = (e) => ({ error: { type: e?.name ?? 'Error', message: b64(String(e?.message ?? e)) } });
  const guard = (fn) => {
    try {
      return fn();
    } catch (e) {
      return encode(e);
    }
  };
  try {
    const options = { today: () => request.today };
    if (request.k !== null) options.k = request.k;
    if (request.index_budget !== null) options.indexBudget = request.index_budget;
    let mem;
    try {
      mem =
        request.registration === 'layered'
          ? mod.Memory.layered(request.start === null ? null : unb64(request.start), options)
          : new mod.Memory(unb64(request.root), options);
    } catch (e) {
      return { results: [encode(e)] };
    }
    const results = [];
    for (const call of request.calls) {
      if (call.op === 'recall') {
        const [query, k] = call.args;
        results.push(guard(() => b64(mem.recall(unb64(query), k))));
      } else if (call.op === 'save') {
        const [type, n, description, body, links] = call.args;
        results.push(
          guard(() => b64(mem.save(unb64(type), unb64(n), unb64(description), unb64(body), links.map(unb64)))),
        );
      } else if (call.op === 'layers') {
        results.push(mem.layerLabels().map(b64));
      } else {
        throw new Error(`unknown call op ${call.op}`);
      }
    }
    return { results };
  } finally {
    for (const [k, v] of before) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

// -------------------------------------------------------------------------- scenarios

/**
 * Each entry is one call list against one fixture, under one registration.
 *
 * `home` and `pin` are relative to the side's own bed and become `HOME` and
 * `BANTAMKIT_MEMORY_DIR`. `home` defaults to `home/`, which the fixture leaves empty, so
 * every layered scenario has a profile layer that exists and is not anybody's real store.
 */
function scenarios() {
  const populated = storeSpec('companyB/.bantamkit/memory', { 'x-fact': 'd one' });
  const emptyOwn = storeSpec('companyA/.bantamkit/memory');
  const homeStore = storeSpec('home/.bantamkit/memory');

  return [
    // ---- the hit, under both registrations -------------------------------------------
    ['--store: a hit carries no layer tag',
      storeSpec('direct', { 'probe-fact-one': 'a probe fact about widgets and gears' }),
      { registration: 'store', root: 'direct' },
      [recall('probe fact widgets')]],
    ['layered: a hit is tagged with the layer it came from',
      merge(populated, homeStore),
      { registration: 'layered', start: 'companyB' },
      [layersOp(), recall('d one')]],
    ['layered: a hit from the profile layer, tagged as such',
      merge(storeSpec('companyA/.bantamkit/memory'), storeSpec('home/.bantamkit/memory', { 'p-fact': 'profile subject' })),
      { registration: 'layered', start: 'companyA' },
      [recall('profile subject')]],
    ['layered: a grant layer is labelled by its project directory',
      merge(emptyOwn, homeStore, storeSpec('shared', { 'g-fact': 'granted subject' }), {
        files: { 'companyA/.bantamkit/config.yaml': 'extra_stores:\n- ../../shared\n' },
      }),
      { registration: 'layered', start: 'companyA' },
      [layersOp(), recall('granted subject')]],

    // ---- the four nothings ------------------------------------------------------------
    ['--store: an empty store named outright makes the no-binding claim',
      storeSpec('direct'),
      { registration: 'store', root: 'direct' },
      [recall('anything')]],
    ['--store: a populated store that misses says only that',
      storeSpec('direct', { 'probe-fact-one': 'a probe fact' }),
      { registration: 'store', root: 'direct' },
      [recall('nothing-shares-this')]],
    ['layered: a populated store that misses says only that',
      merge(populated, homeStore),
      { registration: 'layered', start: 'companyB' },
      [recall('nothing-shares-this')]],
    ['layered: an empty store that is the start directory\'s own',
      merge(emptyOwn, homeStore),
      { registration: 'layered', start: 'companyA' },
      [recall('anything')]],
    ['layered: the walk climbed, and says from where',
      merge(emptyOwn, homeStore, { dirs: ['companyA/sub/deeper'] }),
      { registration: 'layered', start: 'companyA/sub/deeper' },
      [recall('anything')]],
    ['layered: nothing existed anywhere, so a store was designated',
      merge(homeStore, { dirs: ['lonely/proj'] }),
      { registration: 'layered', start: 'lonely/proj' },
      [recall('anything')]],
    // J48-3. THE SAME DESIGNATION, over a directory NOTHING CAN BE CREATED UNDER — which is
    // what every GUI MCP host hands this program, because it launches its child with cwd `/`.
    // Until job48 the project layer was built eagerly, so this fixture was not a scenario at
    // all: it was a crash out of `mkdir` before `Memory.layered` returned, and the client saw
    // CONNECTION_CLOSED. Four claims in one call list, and each of them is a thing the fix
    // promised: the construction SUCCEEDS, both layers are bound, the recall is ANSWERED out
    // of the profile layer, and the write that finally needs the directory refuses BY NAME
    // instead of raising `OSError` at whoever is listening. The tree case beside it says the
    // designated root is still absent afterwards.
    //
    // `0o555` AND A PROBE, not `0o555` and a hope: see `sealedProbe` in `run`. A platform or a
    // uid that creates directories there anyway skips this scenario with a note rather than
    // reporting four green cases over a bed that denies nothing.
    ['layered: the designated root cannot be created, so it is not — and the server still answers',
      merge(storeSpec('home/.bantamkit/memory', { 'p-fact': 'profile subject' }),
        { dirs: ['sealed/proj'], modes: { 'sealed/proj': 0o555 } }),
      { registration: 'layered', start: 'sealed/proj' },
      [layersOp(), recall('profile subject'), recall('anything'), save('project', 'newfact', 'a subject nothing shares', 'body')],
      'denied-creation'],
    ['layered: the pin is named as the reason',
      merge(emptyOwn, homeStore, storeSpec('pinned')),
      { registration: 'layered', start: 'companyA', pin: 'pinned' },
      [recall('anything')]],
    ['layered: the bound store IS the profile layer, so the advice inverts',
      merge(homeStore, { dirs: ['home/a-project'] }),
      { registration: 'layered', start: 'home/a-project' },
      [recall('anything')]],
    ['layered: an unlistable grant is named, and the binding is still diagnosed',
      merge(emptyOwn, homeStore, { dirs: ['granted/facts'], modes: { 'granted/facts': 0o311 } }, {
        files: { 'companyA/.bantamkit/config.yaml': 'extra_stores:\n- ../../granted\n' },
      }),
      { registration: 'layered', start: 'companyA' },
      [recall('anything')]],
    // THE DEFERRED DEFECT, END TO END. The same unreadable grant, shaped as a dangling
    // symlink instead of a mode bit: `count_facts` maps it to 0, the layer is NOT reported
    // unreadable, and the operator is told to stop looking. Reproduced, not fixed.
    ['layered: a dangling grant is NOT named — the deferred count_facts defect, end to end',
      merge(emptyOwn, homeStore, { dirs: ['granted'], symlinks: [['granted/facts', '{ROOT}/nowhere-at-all']] }, {
        files: { 'companyA/.bantamkit/config.yaml': 'extra_stores:\n- ../../granted\n' },
      }),
      { registration: 'layered', start: 'companyA' },
      [recall('anything')]],
    ['layered: an unreadable PROJECT store raises out of the binding, before any recall',
      merge(storeSpec('companyA/.bantamkit/memory', { a: 'd' }), homeStore, {
        modes: { 'companyA/.bantamkit/memory/facts': 0o000 },
      }),
      { registration: 'layered', start: 'companyA' },
      [recall('anything')]],
    ['layered: a corrupt grant is skipped and a corrupt project layer is not',
      merge(storeSpec('companyA/.bantamkit/memory', { a: 'shared token' }), homeStore,
        storeSpec('granted'), {
          files: {
            'granted/facts/broken.md': 'no frontmatter at all\n',
            'companyA/.bantamkit/config.yaml': 'extra_stores:\n- ../../granted\n',
          },
        }),
      { registration: 'layered', start: 'companyA' },
      [recall('shared')]],

    // ---- saving ------------------------------------------------------------------------
    ['--store: the save replies, including the duplicate and the type refusal',
      storeSpec('direct'),
      { registration: 'store', root: 'direct' },
      [
        save('project', 'Fact_0', 'w0a w0b w0c w0d', 'body'),
        save('project', 'probe', 'w0a w0b w0c w0d', 'body'),
        save('notes', 'x', 'd', 'b'),
        save('project', 'Bad Name!', 'd', 'b'),
        save('project', 'x', '   \n', 'b'),
      ]],
    ['--store: a budget refusal names a remedy the model has',
      storeSpec('direct'),
      { registration: 'store', root: 'direct', index_budget: 10 },
      [save('project', 'a', 'a long description', 'b')]],
    ['layered: a save lands in the project layer and the grant is untouched',
      merge(emptyOwn, homeStore, storeSpec('shared', { 'g-fact': 'granted subject' }), {
        files: { 'companyA/.bantamkit/config.yaml': 'extra_stores:\n- ../../shared\n' },
      }),
      { registration: 'layered', start: 'companyA' },
      [save('project', 'new_fact', 'a subject nothing else shares', 'body'), recall('granted subject')]],
    ['layered: k is raised to the default, never lowered',
      merge(storeSpec('companyA/.bantamkit/memory', {
        'fact-a': 'shared token', 'fact-b': 'shared token', 'fact-c': 'shared token',
      }), homeStore),
      { registration: 'layered', start: 'companyA', k: 3 },
      [recall('shared', 1)]],

    // ---- the pin's own refusals, through the component ---------------------------------
    ['layered: a relative pin refuses the whole construction',
      merge(emptyOwn, homeStore),
      { registration: 'layered', start: 'companyA', pinLiteral: 'relative/path' },
      [recall('anything')]],
    ['layered: a pin at nothing refuses and creates nothing',
      merge(emptyOwn, homeStore),
      { registration: 'layered', start: 'companyA', pin: 'missing-entirely' },
      [recall('anything')]],
    ['layered: a pin at a file says it is not a directory',
      merge(emptyOwn, homeStore, { files: { pinfile: 'x' } }),
      { registration: 'layered', start: 'companyA', pin: 'pinfile' },
      [recall('anything')]],
    ['layered: a ~ pin is expanded by the resolver, because no shell will',
      merge(emptyOwn, storeSpec('home/mem', { 'h-fact': 'pinned subject' })),
      { registration: 'layered', start: 'companyA', pinLiteral: '~/mem' },
      [recall('pinned subject')]],
    ['layered: a blank pin is not a pin',
      merge(storeSpec('companyA/.bantamkit/memory', { a: 'own subject' }), homeStore),
      { registration: 'layered', start: 'companyA', pinLiteral: '   ' },
      [recall('own subject')]],
  ];
}

/** The config documents `load_grants` is asked to read. Outcome must match, not just text. */
const CONFIGS = [
  ['missing', null],
  ['empty', ''],
  ['a single newline', '\n'],
  ['comments only', '# a comment\n\n# another\n'],
  ['no extra_stores key', 'other: keys\n'],
  ['an empty flow list', 'extra_stores: []\n'],
  ['a block sequence', 'extra_stores:\n- ../granted\n'],
  ['an indented block sequence', 'extra_stores:\n  - ../granted\n'],
  ['a flow sequence', 'extra_stores: [../granted]\n'],
  ['a single-quoted item', "extra_stores:\n- '../granted'\n"],
  ['a double-quoted item', 'extra_stores: ["../granted"]\n'],
  ['two items, one repeated', 'extra_stores:\n- ../granted\n- ../granted\n'],
  ['an absolute item', 'extra_stores:\n- {ROOT}/granted\n'],
  ['a document start marker', '---\nextra_stores: []\n'],
  ['a comment before the key', '# leading\nextra_stores:\n- ../granted\n'],
  ['a trailing comment', 'extra_stores: [] # why\n'],
  ['other keys around it', 'k: v\nextra_stores:\n- ../granted\nz: 1\n'],
  ['a sequence document', '- a\n- b\n'],
  ['a scalar document', 'just a scalar\n'],
  ['extra_stores is an int', 'extra_stores: 3\n'],
  ['extra_stores is null', 'extra_stores:\n'],
  ['extra_stores is a string', 'extra_stores: ../granted\n'],
  ['an item that is an int', 'extra_stores:\n- 3\n'],
  ['an item that is a bool', 'extra_stores:\n- true\n'],
  ['a path that is not there', 'extra_stores:\n- ./nope\n'],
  ['a path that is a file', 'extra_stores:\n- ../afile\n'],
  ['a key with no space after the colon', 'extra_stores:3\n'],
  ['a BOM-free unicode path', 'extra_stores:\n- ../ตัวอย่าง\n'],
];

// ------------------------------------------------------------------------------- run

/**
 * platform-checked: this body chmods `locked` to `0o000` and then PROBES whether the mode was
 * honoured — `readdirSync` inside a `try`, and a `notes.push('NOT MEASURED: this platform
 * listed a 0o000 directory anyway (root?)')` when it was not. That probe is the platform
 * statement; the marker is what makes it visible to the gate, which could not see the
 * `chmodSync(join(...), 0o000)` spelling until 2026-09-11.
 */
/**
 * Does a `0o555` directory in THIS scratch tree actually deny creation?
 *
 * `applyModes` above already says, in as many words, that a mode-restricted bed is not a wall
 * on Windows and is not a wall for root, and that what was missing was "a probe that tries the
 * denied operation, and a `notes.push('NOT MEASURED: ...')` when the mode was not honoured".
 * J48-3 needed one, so this is it. It is a claim about the directory in front of it and never
 * about `process.platform`, because nobody here has a Windows run to type a claim from.
 */
function sealedProbe(scratch) {
  const dir = join(scratch, 'sealed-probe');
  mkdirSync(dir, { recursive: true });
  chmodSync(dir, 0o555);
  try {
    mkdirSync(join(dir, 'can-anything-be-made-here'));
    rmSync(join(dir, 'can-anything-be-made-here'), { recursive: true, force: true });
    return { denies: false, why: 'the 0o555 mode was not honoured — this platform or this uid creates directories there anyway' };
  } catch (e) {
    return { denies: true, why: `mkdir inside it was refused with ${e?.code ?? 'an error carrying no code'}` };
  } finally {
    chmodSync(dir, 0o755);
  }
}

/**
 * THE TWO SENTENCES job48 CONTRACTED, typed here rather than taken from either runtime.
 *
 * Both of these are produced by BOTH runtimes today, byte for byte — J48-2 compared them by
 * sha256 rather than by eye — so every differential over them is green whatever they say, and
 * stays green if both sides change together. That is not a hypothetical: reverting job48
 * symmetrically left `--all` printing its baseline summary unchanged, 0 failures, while both
 * CLIs went back to refusing to start from cwd `/`. A literal is the only thing in this
 * repository that can notice a symmetric change, and job47 established the second half of the
 * lesson too — an existing literal must not be assumed to cover a new spelling, so these are
 * new cases and not an edit to an old one.
 *
 * `<ROOT>` is `scrub`'s marker for the side's own bed, so the path is compared and not dropped.
 */
const DESIGNATED_TAIL = (from, root) =>
  `No memory store existed at or above ${from}, so ${root} was designated for this session; ` +
  'nothing was created there. That is a binding, not a search result — if your facts are in ' +
  'another store, set BANTAMKIT_MEMORY_DIR to its absolute path and restart; otherwise save a ' +
  'memory to start this one.';

/** What `memory_recall` says when the walk designated a root and nothing is saved anywhere. */
const DESIGNATED_FROM_NOTHING =
  'no memories to search: nothing is saved in any layer bound here. ' +
  DESIGNATED_TAIL('<ROOT>/lonely/proj', '<ROOT>/lonely/proj/.bantamkit/memory');

/**
 * The four answers the sealed scenario must give, in order.
 *
 * [0] BOTH LAYERS ARE BOUND. The construction did not fail, which is the whole fix.
 * [1] THE PROFILE LAYER ANSWERS. A server that starts and then cannot recall anything would
 *     satisfy [0] and be useless; this is the case that says the operator's facts still reach
 *     the model from a cwd their host chose and they never saw.
 * [2] THE AMENDED SENTENCE, in situ. It used to read "so the empty <root> was created for this
 *     session", which became FALSE when nothing was created — a sentence sending an operator
 *     to look for a directory that is not there. Pinned whole rather than as a fragment,
 *     because the remedy after it ("otherwise save a memory to start this one") is the half
 *     that is now literally true and a fragment would not hold it.
 * [3] THE WRITE REFUSES BY NAME. The sentence lands at the write that needed the directory,
 *     carries `self.root` and no errno — one cwd gives CPython EROFS(30) where Node reports
 *     ENOENT(-2) for the same denial, and Linux gives EACCES for both — and it is a refusal
 *     rather than an `OSError` reaching whoever was listening.
 */
const SEALED_ANSWERS = [
  'project, profile',
  '[profile] [p-fact] (project) profile subject\nb',
  `no memories matched. Try different words, or proceed without. ${DESIGNATED_TAIL('<ROOT>/sealed/proj', '<ROOT>/sealed/proj/.bantamkit/memory')}`,
  'error: memory store could not be created: <ROOT>/sealed/proj/.bantamkit/memory; the directory ' +
    'is not there and this filesystem would not make it, so nothing was written',
];

export async function run(ctx) {
  const mod = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'component.js')).href);
  const layers = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'layers.js')).href);
  const pyfs = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'pyfs.js')).href);
  const cases = [];
  const notes = [];
  const scratch = realpathSync(ctx.scratch);

  // -------------------------------------------------------------- the scenarios
  const sealed = sealedProbe(scratch);
  if (!sealed.denies) {
    notes.push(
      'the designated-root-cannot-be-created scenario: NOT MEASURED HERE — ' +
        `${sealed.why}. Its four claims and the two pinned sentences below it are not reported ` +
        'rather than reported as passes nobody earned; every other scenario is measured here.',
    );
  }
  /** Each scenario's rendered answers, kept so a literal below can pin one against a constant. */
  const answersByLabel = new Map();
  let n = 0;
  let layeredCount = 0;
  for (const [label, spec, options, calls, requires] of scenarios()) {
    if (requires === 'denied-creation' && !sealed.denies) continue;
    n += 1;
    if (options.registration === 'layered') layeredCount += 1;
    const bed = join(scratch, `r${String(n).padStart(2, '0')}`);
    const roots = {};
    for (const side of ['py', 'node']) {
      roots[side] = join(bed, side);
      materialise(roots[side], merge(spec, { dirs: [options.home ?? 'home'] }));
      applyModes(roots[side], spec, true);
    }
    const envFor = (root) => ({
      HOME: join(root, options.home ?? 'home'),
      USERPROFILE: join(root, options.home ?? 'home'),
      BANTAMKIT_MEMORY_DIR:
        options.pin !== undefined ? join(root, options.pin) : (options.pinLiteral ?? undefined),
    });
    const request = (root) => ({
      op: 'memory',
      registration: options.registration,
      root: options.root === undefined ? null : b64(join(root, options.root)),
      start: options.start === undefined ? null : b64(join(root, options.start)),
      today: TODAY,
      k: options.k ?? null,
      index_budget: options.index_budget ?? null,
      calls,
    });
    const py = ctx.runPython(REF, request(roots.py), {
      ...envFor(roots.py),
      ...(envFor(roots.py).BANTAMKIT_MEMORY_DIR === undefined ? { BANTAMKIT_MEMORY_DIR: '' } : {}),
    });
    const nd = await runNode(mod, request(roots.node), envFor(roots.node));
    for (const side of ['py', 'node']) applyModes(roots[side], spec, false);

    const arms = Math.max(py.results.length, nd.results.length);
    // A MISSING ARM IS DATA, NOT A CRASH, and this is a defect J48-3 found by mutating rather
    // than by reading. `Math.max` is here precisely because the two sides can return different
    // numbers of results — a construction that raises on ONE runtime produces a single encoded
    // error where the other produced four answers — and until now the shorter side's missing
    // entries reached `scrub` as `undefined` and took the whole suite down with
    // `TypeError: Cannot read properties of undefined (reading 'split')`, from inside `run()`,
    // where every other case in the file goes unreported and the failure arrives as a stack
    // trace instead of as a named case. `cli.mjs`'s `framesOf` makes the same argument about
    // an unparsable line: the thing that went wrong is the answer, so it travels as one.
    const armOf = (results, i, root) =>
      i < results.length
        ? scrub(answer(results[i]), root)
        : `NO ANSWER: this side returned ${results.length} result(s) and the other returned ${arms}`;
    const rendered = { py: [], node: [] };
    for (let i = 0; i < arms; i += 1) {
      rendered.py.push(armOf(py.results, i, roots.py));
      rendered.node.push(armOf(nd.results, i, roots.node));
      cases.push({
        name: `${label} [${i}]`,
        kind: 'string',
        expected: rendered.py[i],
        actual: rendered.node[i],
      });
    }
    answersByLabel.set(label, rendered);
    cases.push({
      name: `${label} — tree`,
      kind: 'bytes',
      expected: manifest(roots.py),
      actual: manifest(roots.node),
    });
  }
  // ---- THE LITERALS. Everything above is a differential and a differential is satisfied by
  // two runtimes that are wrong in the same way — measured on this very change, not supposed:
  // reverting job48 on BOTH runtimes left `--all` printing its baseline summary character for
  // character while both CLIs went back to refusing to start from cwd `/`. These two compare
  // each side against text typed into this file instead.
  const designated = answersByLabel.get('layered: nothing existed anywhere, so a store was designated');
  cases.push({
    name: 'PINNED PER SIDE: the designated sentence, whole, against this file',
    kind: 'json',
    expected: { python: [DESIGNATED_FROM_NOTHING], node: [DESIGNATED_FROM_NOTHING] },
    actual: { python: designated.py, node: designated.node },
  });
  const sealedAnswers = answersByLabel.get(
    'layered: the designated root cannot be created, so it is not — and the server still answers',
  );
  if (sealedAnswers !== undefined) {
    cases.push({
      name: 'PINNED PER SIDE: bound, answered from the profile layer, and the write refused by name',
      kind: 'json',
      expected: { python: SEALED_ANSWERS, node: SEALED_ANSWERS },
      actual: { python: sealedAnswers.py, node: sealedAnswers.node },
    });
  }

  notes.push(
    `${n} scenarios compared, ${layeredCount} under Memory.layered (the registration ` +
      'production runs) and the rest under the --store form',
  );

  // ------------------------------------------------------- the config battery
  // The OUTCOME is compared, not only the message: a reader that refused a document PyYAML
  // loads would be a behavioural difference, not a wording one.
  const cfgBed = join(scratch, 'grants');
  const cfgRoots = {};
  for (const side of ['py', 'node']) {
    cfgRoots[side] = join(cfgBed, side);
    materialise(cfgRoots[side], merge(storeSpec('.bantamkit/memory'), storeSpec('granted'),
      storeSpec('ตัวอย่าง'), { files: { afile: 'x\n' } }));
  }
  for (const [label, text] of CONFIGS) {
    const answers = {};
    for (const side of ['py', 'node']) {
      const config = join(cfgRoots[side], '.bantamkit', 'config.yaml');
      if (text === null) rmSync(config, { force: true }); // "missing" means missing
      else writeFileSync(config, text.split('{ROOT}').join(cfgRoots[side]));
      if (side === 'py') {
        const out = ctx.runPython(REF, {
          op: 'grants',
          stores: [b64(join(cfgRoots.py, '.bantamkit', 'memory'))],
        }, { HOME: cfgRoots.py, BANTAMKIT_MEMORY_DIR: '' });
        answers.py = out.grants[0];
      } else {
        try {
          answers.node = layers
            .loadGrants(join(cfgRoots.node, '.bantamkit', 'memory'))
            .map((p) => b64(p));
        } catch (e) {
          answers.node = { error: { type: e?.name ?? 'Error', message: b64(String(e?.message)) } };
        }
      }
    }
    const render = (value, root) =>
      scrub(
        Array.isArray(value) ? `grants: ${value.map(unb64).join(' | ')}` : answer(value),
        root,
      );
    cases.push({
      name: `load_grants: ${label}`,
      kind: 'string',
      expected: render(answers.py, cfgRoots.py),
      actual: render(answers.node, cfgRoots.node),
    });
  }
  notes.push(`${CONFIGS.length} config documents read by both readers, outcome compared`);

  // ---------------------------------------------------------------- the primitives
  // Each of these is a rule the binding depends on, compared on its own because a scenario
  // that happens not to reach one would let it rot unnoticed.

  const probeEnv = { HOME: join(scratch, 'probe-home'), BANTAMKIT_MEMORY_DIR: '' };
  materialise(join(scratch, 'probe-home'), { dirs: ['.bantamkit/memory'] });

  const shapes = join(scratch, 'shapes');
  materialise(shapes, merge(storeSpec('populated', { a: 'd', b: 'd' }), storeSpec('empty'), {
    dirs: ['nofacts', 'dangling', 'filefacts', 'dotted/facts', 'dirfact/facts/x.md'],
    files: {
      'dotted/facts/.hidden.md': factFile('hidden'),
      'dotted/facts/notes.txt': 'x\n',
      'dotted/facts/plain.md.tmp': 'x\n',
      'filefacts/facts': 'not a directory\n',
    },
    symlinks: [['dangling/facts', '{ROOT}/nowhere-at-all']],
  }));
  const countRoots = ['populated', 'empty', 'nofacts', 'dangling', 'filefacts', 'dotted', 'dirfact']
    .map((r) => join(shapes, r));
  const pyCounts = ctx.runPython(REF, { op: 'count_facts', roots: countRoots.map(b64) }, probeEnv).counts;
  cases.push({
    // THE DEFERRED DEFECT IS PINNED HERE. `dangling` is 0 on both sides today because
    // `count_facts` catches FileNotFoundError and nothing wider, while the STORE raises on
    // the same shape (`store.mjs`, "facts is a dangling symlink"). The day runtime-py fixes
    // it, the Python side of this case becomes an error, this case goes red, and the port's
    // deliberate reproduction has to be revisited rather than discovered.
    name: 'count_facts over seven shapes — including the dangling symlink, THE DEFERRED DEFECT',
    kind: 'json',
    expected: pyCounts.map((c) => (typeof c === 'number' ? c : `${c.error.type}`)),
    actual: countRoots.map((root) => {
      try {
        return layers.countFacts(root);
      } catch (e) {
        return e?.name ?? 'Error';
      }
    }),
  });

  const bindingBed = join(scratch, 'bindings');
  materialise(bindingBed, merge(
    storeSpec('full/.bantamkit/memory', { a: 'd' }),
    storeSpec('empty/.bantamkit/memory'),
    { dirs: ['none', 'full/deep/deeper', 'empty/.bantamkit/memory/facts/sub.md', 'locked/x/y'] },
  ));
  // `locked` is 0o000 for the length of this probe: `Path.is_dir()` swallows only
  // `_IGNORED_ERRNOS`, so the WALK ITSELF raises PermissionError through an ancestor it
  // cannot traverse. That refutes `_pinned_store`'s docstring, which says the walk lives
  // with an unreadable candidate, and it is the arm `existsSync` would answer `false` to.
  const starts = ['full', 'empty', 'none', 'full/deep/deeper', 'locked/x/y']
    .map((s) => join(bindingBed, s));
  chmodSync(join(bindingBed, 'locked'), 0o000);
  let locked = true;
  try {
    readdirSync(join(bindingBed, 'locked'));
    locked = false;
  } catch {
    /* the mode bits were honoured */
  }
  if (!locked) {
    notes.push('NOT MEASURED: this platform listed a 0o000 directory anyway (root?), so the ' +
      'walk-through-EACCES arm compared two successes rather than two raises');
  }
  const pyBindings = ctx.runPython(REF, { op: 'resolve', starts: starts.map(b64) }, probeEnv).bindings;
  cases.push({
    name: 'resolve_project_store: path, state, count, searched_from, origin',
    kind: 'json',
    expected: pyBindings.map((b) => (b.error
      ? `${b.error.type}: ${unb64(b.error.message).split(bindingBed).join('<BED>')}`
      : {
      path: unb64(b.path).split(bindingBed).join('<BED>'),
      state: b.state,
      fact_count: b.fact_count,
      searched_from: b.searched_from === null ? null : unb64(b.searched_from).split(bindingBed).join('<BED>'),
      origin: b.origin,
    })),
    actual: starts.map((start) => {
      try {
        const b = layers.resolveProjectStore(start);
        return {
          path: b.path.split(bindingBed).join('<BED>'),
          state: b.state,
          fact_count: b.factCount,
          searched_from: b.searchedFrom === null ? null : b.searchedFrom.split(bindingBed).join('<BED>'),
          origin: b.origin,
        };
      } catch (e) {
        return `${e?.name}: ${String(e?.message).split(bindingBed).join('<BED>')}`;
      }
    }),
  });
  const pyPaths = ctx.runPython(REF, { op: 'discover', starts: starts.map(b64) }, probeEnv).paths;
  const nodePaths = starts.map((s) => {
    try {
      return layers.discoverProjectStore(s).split(bindingBed).join('<BED>');
    } catch (e) {
      return `${e?.name}: ${String(e?.message).split(bindingBed).join('<BED>')}`;
    }
  });
  chmodSync(join(bindingBed, 'locked'), 0o755);
  cases.push({
    name: 'discover_project_store never disagrees with resolve about the path',
    kind: 'json',
    expected: pyPaths.map((p) =>
      p.error
        ? `${p.error.type}: ${unb64(p.error.message).split(bindingBed).join('<BED>')}`
        : unb64(p).split(bindingBed).join('<BED>')),
    actual: nodePaths,
  });

  const names = ['  A_Fact Name ', 'already-fine', 'MiXeD_case', 'a  b', '', '_', 'ΑΣ', 'İstanbul',
    'ẞ', ' padded ', 'ﬁle_name', 'ΣΟΦΟΣ', 'a b'];
  cases.push({
    name: 'normalize_name over the strip and lowercase boundary',
    kind: 'json',
    expected: ctx.runPython(REF, { op: 'normalize', names: names.map(b64) }, probeEnv)
      .names.map((x) => (x === null ? null : unb64(x))),
    actual: names.map((x) => mod.normalizeName(x)),
  });

  const labelRoots = ['/a/b/.bantamkit/memory', '/a/b/memory', '/memory', '/a/.bantamkit/memory/',
    'relative/.bantamkit/memory', '/.bantamkit/memory'];
  cases.push({
    name: '_layer_label names the project directory, not the store directory',
    kind: 'json',
    expected: ctx.runPython(REF, { op: 'labels', roots: labelRoots.map(b64) }, probeEnv)
      .labels.map(unb64),
    actual: labelRoots.map((r) => mod.layerLabel(r)),
  });

  cases.push({
    name: '_profile_store follows HOME',
    kind: 'string',
    expected: unb64(ctx.runPython(REF, { op: 'profile' }, probeEnv).profile),
    actual: (() => {
      const before = process.env.HOME;
      process.env.HOME = probeEnv.HOME;
      try {
        return mod.profileStore();
      } finally {
        process.env.HOME = before;
      }
    })(),
  });

  // `~<the current user>` is in the list because without it `first.startsWith('~')` and
  // `first === '~'` are indistinguishable — a mutation sweep found exactly that survivor.
  const expanders = ['~', '~/mem', '/abs', 'rel', '', '~/', 'a/~', '/~/x',
    `~${userInfo().username}/mem`];
  cases.push({
    name: 'Path(raw).expanduser() — the pin arrives with no shell to expand it',
    kind: 'json',
    expected: ctx.runPython(REF, { op: 'expanduser', raws: expanders.map(b64) }, probeEnv)
      .expanded.map((e) => (e.error ? `${e.error.type}: ${unb64(e.error.message)}` : unb64(e))),
    actual: expanders.map((raw) => {
      const before = process.env.HOME;
      process.env.HOME = probeEnv.HOME;
      try {
        return pyfs.pyExpanduser(raw);
      } catch (e) {
        return `${e?.name}: ${e?.message}`;
      } finally {
        process.env.HOME = before;
      }
    }),
  });

  const parentPaths = ['/a/b/c', '/', 'a/b', '.', '/a/b/../c', '//a/b', 'a'];
  cases.push({
    name: 'PurePath.parents — what the walk iterates',
    kind: 'json',
    expected: ctx.runPython(REF, { op: 'parents', raws: parentPaths.map(b64) }, probeEnv)
      .parents.map((row) => row.map(unb64)),
    actual: parentPaths.map((p) => pyfs.pyParents(p)),
  });

  const linkBed = join(scratch, 'links');
  materialise(linkBed, {
    dirs: ['real/sub'],
    files: { afile: 'x\n' },
    symlinks: [['link', '{ROOT}/real'], ['dang', '{ROOT}/nowhere'], ['loop', '{ROOT}/loop']],
  });
  const resolvables = ['real', 'link', 'link/sub/..', 'dang', 'nope/x', 'afile/sub', 'real/../real', 'loop']
    .map((p) => join(linkBed, p));
  cases.push({
    name: 'Path.resolve(): symlinks, a missing tail, a file as a directory, and the loop',
    kind: 'json',
    expected: ctx.runPython(REF, { op: 'resolve_path', raws: resolvables.map(b64) }, probeEnv)
      .resolved.map((r) => (r.error ? `${r.error.type}: ${unb64(r.error.message).split(linkBed).join('<BED>')}`
        : unb64(r).split(linkBed).join('<BED>'))),
    actual: resolvables.map((p) => {
      try {
        return pyfs.pyResolve(p).split(linkBed).join('<BED>');
      } catch (e) {
        return `${e?.name}: ${String(e?.message).split(linkBed).join('<BED>')}`;
      }
    }),
  });

  // ------------------------------------------------------------------ ruled to differ
  // Both of these are required to DIFFER, and a ruling whose case starts matching fails.

  const otherUser = ['~root/mem', '~nobody-here/mem'];
  cases.push({
    name: 'RULED: ~someone-else needs a passwd lookup Node does not have',
    kind: 'json',
    expected: ctx.runPython(REF, { op: 'expanduser', raws: otherUser.map(b64) }, probeEnv)
      .expanded.map((e) => (e.error ? `${e.error.type}: ${unb64(e.error.message)}` : unb64(e))),
    actual: otherUser.map((raw) => {
      try {
        return pyfs.pyExpanduser(raw);
      } catch (e) {
        return `${e?.name}: ${e?.message}`;
      }
    }),
    ruling:
      'Python asks the passwd database and resolves any account on the machine (measured: ' +
      '`~root` -> `/var/root`). Node has no getpwnam, so `pyExpanduser` resolves `~` and ' +
      '`~<the current user>` and raises the same RuntimeError Python raises for an unknown ' +
      'user for everything else. Reproducing it means a subprocess (dscl/getent) at runtime ' +
      'inside a package whose whole point is that it is pure Node, for a spelling of ' +
      'BANTAMKIT_MEMORY_DIR nothing has ever used. The `~` and `~/mem` arms — the ones an ' +
      'operator actually writes — are pinned as EXACT in the case above.',
  });

  const badYaml = join(scratch, 'bad-yaml');
  const badRoots = {};
  for (const side of ['py', 'node']) {
    badRoots[side] = join(badYaml, side);
    materialise(badRoots[side], storeSpec('.bantamkit/memory'));
    writeFileSync(join(badRoots[side], '.bantamkit', 'config.yaml'), 'extra_stores: [unclosed\n');
  }
  const pyBad = ctx.runPython(REF, {
    op: 'grants',
    stores: [b64(join(badRoots.py, '.bantamkit', 'memory'))],
  }, { HOME: badRoots.py, BANTAMKIT_MEMORY_DIR: '' }).grants[0];
  let nodeBad;
  try {
    layers.loadGrants(join(badRoots.node, '.bantamkit', 'memory'));
    nodeBad = 'no error';
  } catch (e) {
    nodeBad = `${e?.name}: ${e?.message}`;
  }
  cases.push({
    name: 'RULED: a config outside the reader\'s language, and PyYAML\'s scanner diagnostics',
    kind: 'string',
    expected: scrub(pyBad.error ? `${pyBad.error.type}: ${unb64(pyBad.error.message)}` : String(pyBad), badRoots.py),
    actual: scrub(nodeBad, badRoots.node),
    ruling:
      'PyYAML answers a malformed document with a ScannerError carrying line/column marks ' +
      'and a rendered snippet; `load_grants` interpolates that into `invalid memory config ' +
      '{path}: {e}`. This port answers with its own reason after the IDENTICAL prefix. ' +
      'Matching would mean porting PyYAML\'s scanner diagnostics — larger than the whole ' +
      'memory package — for a string no runtime-py test pins. The prefix, and every ' +
      'document whose OUTCOME differs (a mapping or not, a list of paths or not), are ' +
      'pinned exactly by the config battery above; only the reason after the colon differs.',
  });

  return { cases, notes };
}
