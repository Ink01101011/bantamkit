/**
 * `assetsRoot()` and the four loaders, against `runtime-py/src/bantamkit/assets.py`.
 *
 * Arms 2 and 3 are tested by BUILDING THE LAYOUT, not by reading the source and
 * agreeing with it. Each arm copies the real build output (`dist/assets.js` +
 * `dist/errors.js`) into a temp directory shaped like the situation that arm serves, and
 * imports it from there. That is the only way the `../..` level count in arm 3 can be
 * proved: a wrong count does not throw, it silently resolves to a DIFFERENT checkout's
 * pack — the same silent-wrong-source class the sh launcher's `PYTHONPATH` comment is
 * about.
 */
import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { test } from 'node:test';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoPack = join(dirname(packageRoot), 'assets');
const dist = join(packageRoot, 'dist');

/**
 * Plant `dist/assets.js` at `<base>/<distRel>` and import it from there.
 *
 * The whole of `dist/` is copied rather than a hand-listed two files. `assets.js` reads
 * text through `memory/pyfs.js` — one UTF-8 decode for the package, not a second spelling
 * beside it — and a list that has to be edited whenever an import is added is a list that
 * fails as `ERR_MODULE_NOT_FOUND` in a test about directory arms.
 *
 * THE `package.json` IS PART OF THE LAYOUT, not a workaround for one interpreter.
 * `dist/*.js` is ESM and the only thing that says so is `"type": "module"` in the package
 * root beside `dist/` — which is exactly where the real package keeps it. Omitting it made
 * this fixture lean on Node's module-syntax DETECTION instead, and that is version-gated.
 * MEASURED, same tree, four interpreters, `node --test test/assets.test.mjs`:
 *
 *   v18.20.8  5 pass / 5 fail   SyntaxError: Cannot use import statement outside a module
 *   v20.20.2  10 pass / 0 fail
 *   v22.22.3  10 pass / 0 fail
 *   v25.2.1   10 pass / 0 fail
 *
 * So the thing that did not run on the declared `engines` floor was the FIXTURE, not the
 * product: the shipped package has carried its own `package.json` all along, and the
 * conformance suite (4,462 cases) passes unchanged on v18.20.8. Writing the manifest here
 * makes the fixture resemble the layout it claims to be testing. The arm-3 level count is
 * untouched — `assetsRoot` counts directories up from `import.meta.url` and never looks
 * for a manifest, which is why arm 3 still distinguishes `repo/assets` from the decoy.
 */
async function moduleAt(base, distRel) {
  const target = join(base, distRel);
  mkdirSync(target, { recursive: true });
  cpSync(dist, target, { recursive: true });
  writeFileSync(join(dirname(target), 'package.json'), '{"type":"module"}\n');
  return import(pathToFileURL(join(target, 'assets.js')).href);
}

function scratch(name) {
  // `realpathSync`: `os.tmpdir()` is not canonical — a `/var` symlink on macOS, the 8.3
  // short name on Windows CI. See the note in test/store.test.mjs.
  return realpathSync.native(mkdtempSync(join(tmpdir(), `bk-${name}-`)));
}

function withoutEnv(fn) {
  const saved = process.env.BANTAMKIT_ASSETS;
  delete process.env.BANTAMKIT_ASSETS;
  try {
    return fn();
  } finally {
    if (saved === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = saved;
  }
}

test('arm 1: BANTAMKIT_ASSETS wins verbatim, even when it does not exist', async () => {
  const mod = await moduleAt(scratch('arm1'), 'dist');
  const saved = process.env.BANTAMKIT_ASSETS;
  process.env.BANTAMKIT_ASSETS = '/nowhere/at/all';
  try {
    // Python does no existence check on this arm. A wrong override must fail naming
    // itself, not fall through to a pack the operator did not ask for.
    assert.equal(mod.assetsRoot(), '/nowhere/at/all');
  } finally {
    if (saved === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = saved;
  }
});

test('arm 2: the packaged pack sits one level above dist/ — the arm npx uses', async () => {
  const base = scratch('arm2');
  mkdirSync(join(base, 'assets'), { recursive: true });
  writeFileSync(join(base, 'assets', 'marker'), 'packaged\n');
  const mod = await moduleAt(base, 'dist');
  withoutEnv(() => {
    assert.equal(readFileSync(join(mod.assetsRoot(), 'marker'), 'utf8'), 'packaged\n');
  });
});

test('arm 3: the repo pack is TWO levels above dist/, not one and not three', async () => {
  // <base>/repo/assets            <- the pack a dev checkout has
  // <base>/repo/runtime-ts/dist/  <- where the build output actually lands
  // <base>/assets                 <- a decoy one level too far up: this is what a wrong
  //                                  count finds, and finding it must NOT happen.
  const base = scratch('arm3');
  mkdirSync(join(base, 'assets'), { recursive: true });
  writeFileSync(join(base, 'assets', 'marker'), 'too-far-up\n');
  mkdirSync(join(base, 'repo', 'assets'), { recursive: true });
  writeFileSync(join(base, 'repo', 'assets', 'marker'), 'repo\n');
  const mod = await moduleAt(base, join('repo', 'runtime-ts', 'dist'));
  withoutEnv(() => {
    assert.equal(readFileSync(join(mod.assetsRoot(), 'marker'), 'utf8'), 'repo\n');
  });
});

test('arm 3 beats arm 2 only when nothing is vendored under runtime-ts/', async () => {
  const base = scratch('arm23');
  mkdirSync(join(base, 'repo', 'assets'), { recursive: true });
  writeFileSync(join(base, 'repo', 'assets', 'marker'), 'repo\n');
  mkdirSync(join(base, 'repo', 'runtime-ts', 'assets'), { recursive: true });
  writeFileSync(join(base, 'repo', 'runtime-ts', 'assets', 'marker'), 'vendored\n');
  const mod = await moduleAt(base, join('repo', 'runtime-ts', 'dist'));
  withoutEnv(() => {
    assert.equal(readFileSync(join(mod.assetsRoot(), 'marker'), 'utf8'), 'vendored\n');
  });
});

test('arm 4: nothing found raises AssetNotFound with Python\'s message, verbatim', async () => {
  const mod = await moduleAt(scratch('arm4'), join('a', 'b', 'c', 'dist'));
  withoutEnv(() => {
    assert.throws(
      () => mod.assetsRoot(),
      (e) =>
        e instanceof mod.AssetNotFound &&
        e.message === 'no assets directory found; set BANTAMKIT_ASSETS',
    );
  });
});

// ---------------------------------------------------------------- the four loaders

const real = await import(pathToFileURL(join(dist, 'assets.js')).href);

function withPack(root, fn) {
  const saved = process.env.BANTAMKIT_ASSETS;
  process.env.BANTAMKIT_ASSETS = root;
  try {
    return fn();
  } finally {
    if (saved === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = saved;
  }
}

test('loadToolAsset returns the manifest VERBATIM, loadTool narrows to three keys', () => {
  withPack(repoPack, () => {
    const full = real.loadToolAsset('memory_recall');
    assert.deepEqual(full, JSON.parse(readFileSync(join(repoPack, 'tools', 'memory_recall.json'), 'utf8')));
    assert.ok('surfaces' in full, 'the fixture no longer exercises the verbatim property');
    const narrow = real.loadTool('memory_recall');
    assert.deepEqual(Object.keys(narrow), ['name', 'description', 'parameters']);
    assert.equal(narrow.name, full.name);
    assert.equal(narrow.description, full.description);
    assert.deepEqual(narrow.parameters, full.parameters);
  });
});

test('loadSchema parses a schema asset', () => {
  withPack(repoPack, () => {
    const schema = real.loadSchema('shiftwork-checkpoint');
    assert.equal(typeof schema, 'object');
    assert.ok('$schema' in schema || 'type' in schema);
  });
});

test('loadSkill returns skill text', () => {
  withPack(repoPack, () => {
    const text = real.loadSkill('memory');
    assert.equal(text, readFileSync(join(repoPack, 'skills', 'memory.md'), 'utf8'));
  });
});

test('each loader names the path it could not find', () => {
  const empty = scratch('empty');
  withPack(empty, () => {
    assert.throws(() => real.loadToolAsset('nope'), {
      name: 'AssetNotFound',
      message: `tool asset not found: ${join(empty, 'tools', 'nope.json')}`,
    });
    assert.throws(() => real.loadSchema('nope'), {
      name: 'AssetNotFound',
      message: `schema asset not found: ${join(empty, 'schemas', 'nope.json')}`,
    });
    assert.throws(() => real.loadSkill('nope'), {
      name: 'AssetNotFound',
      message: `skill asset not found: ${join(empty, 'skills', 'nope.md')}`,
    });
  });
});

test('a CRLF asset reads back LF, the way Python text mode does', () => {
  // `Path.read_text()` applies universal-newline translation; `readFileSync(p,'utf8')`
  // does not. Without the explicit translation the two runtimes hand the model different
  // bytes for the same file on disk. Cross-checked by running BOTH runtimes over the
  // same fixture: CPython's `load_skill` and this one both return 'one\ntwo\nthree\nfour\n'.
  const root = scratch('crlf');
  mkdirSync(join(root, 'skills'), { recursive: true });
  writeFileSync(join(root, 'skills', 'crlf.md'), 'one\r\ntwo\rthree\nfour\n');
  withPack(root, () => {
    assert.equal(real.loadSkill('crlf'), 'one\ntwo\nthree\nfour\n');
  });
});
