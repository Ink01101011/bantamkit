/**
 * Which install shape is running — the Node half of AS-7(a), and the half that would have
 * caught the incident.
 *
 * THE MEASURED DEFECT IS A NODE DEFECT. `docs/roadmap-agent-stack.md` AS-7 records a Claude
 * Desktop entry that sat on 0.25.0 through five releases while its dependency was declared
 * `"bantamkit-mcp": "file:/private/tmp/.../scratchpad/bantamkit-mcp-0.25.0.tgz"` — a tarball
 * in a temp directory that no longer exists. `npm update` there is a no-op BY CONSTRUCTION,
 * and nothing in the config, the logs or any tool reply said either half. That configuration
 * is still on this machine, four times over, under `~/.npm/_npx/`; the fixture below is it,
 * rebuilt from npm's own records so the assertion does not depend on somebody's cache.
 *
 * EVERY FIXTURE IS REAL DIRECTORY STATE AND NOTHING HERE IS STUBBED. The whole question this
 * surface answers is "what did npm actually write down", so a test that patched `readFileSync`
 * or handed `deriveInstall` a fabricated lockfile object would be asserting its own stub back
 * at itself. Each shape below is a real `node_modules` tree with a real
 * `.package-lock.json`, a real symlink where npm makes one, and a real (or really absent)
 * tarball — and the field values were MEASURED against npm 11.6.2 before they were written
 * here, not recalled:
 *
 *   tarball      `{"resolved": "file:../bantamkit-mcp-9.9.9.tgz"}` — `file:` then a RAW path,
 *                relative to the directory that owns `node_modules`, percent-encoding NOT
 *                applied (measured with a space in the directory name, which is the case that
 *                actually turns up).
 *   `file:` dir  `{"resolved": "../src", "link": true}` — no `file:` prefix at all on a link
 *                entry, and the package directory itself is a symlink.
 *   registry     `{"resolved": "https://registry.npmjs.org/…/-.tgz"}`.
 *   global       NO `.package-lock.json` anywhere in `<prefix>/lib/node_modules` — measured on
 *                this machine's own global tree — and npm 7+ writes no `_resolved` into the
 *                installed `package.json` either, so an absence is all there is.
 *   npx          the cache project's own `package.json` carries `"_npx": {"packages": [...]}`,
 *                written by npm itself. That marker is why the Node side can answer
 *                `ephemeral` where the Python side refuses to: it is a record, not a guess at
 *                a cache directory's name.
 */
import assert from 'node:assert/strict';
import { createHook } from 'node:async_hooks';
import { chmodSync, mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import net from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, test } from 'node:test';

import {
  INSTALL_SHAPES,
  Undetermined,
  buildIdFor,
  buildIdentity,
  currentInstall,
  deriveInstall,
  originStat,
} from '../dist/mcp/identity.js';
import { installSourceCondition } from '../dist/mcp/status.js';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const ASSETS = join(dirname(packageRoot), 'assets');

// `realpathSync`: `os.tmpdir()` is not canonical — a `/var` symlink on macOS, the 8.3 short
// name on Windows CI. Every assertion below compares absolute paths, so a non-canonical root
// would fail for a reason that has nothing to do with what is being tested.
const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-install-test-')));
after(() => rmSync(scratch, { recursive: true, force: true }));

let seq = 0;
const room = () => {
  const dir = join(scratch, `r${(seq += 1)}`);
  mkdirSync(dir, { recursive: true });
  return dir;
};

const writeJson = (path, value) => {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
};

/** A package tree: `package.json` beside a `dist/` holding the file that would be running. */
function packageTree(root, version = '0.25.0') {
  writeJson(join(root, 'package.json'), { name: 'bantamkit-mcp', version });
  const running = join(root, 'dist', 'mcp', 'identity.js');
  mkdirSync(dirname(running), { recursive: true });
  writeFileSync(running, '// the file that is running\n', 'utf8');
  writeFileSync(join(root, 'dist', 'cli.js'), '// the bin\n', 'utf8');
  return running;
}

/**
 * A real install: `<project>/node_modules/bantamkit-mcp`, with npm's hidden lockfile.
 *
 * `entry: null` writes NO `.package-lock.json` at all, which is the global-install shape
 * measured on this machine. `npx: true` adds the `_npx` marker npm writes into the cache
 * project's own `package.json`.
 */
function installed(project, { entry, npx = false } = {}) {
  const running = packageTree(join(project, 'node_modules', 'bantamkit-mcp'));
  if (entry) {
    writeJson(join(project, 'node_modules', '.package-lock.json'), {
      name: 'proj',
      lockfileVersion: 3,
      requires: true,
      packages: { 'node_modules/bantamkit-mcp': entry },
    });
  }
  writeJson(
    join(project, 'package.json'),
    npx
      ? { dependencies: { 'bantamkit-mcp': 'file:../x.tgz' }, _npx: { packages: ['./x.tgz'] } }
      : { name: 'proj', version: '1.0.0' },
  );
  return running;
}

// ============================================================ the closed vocabulary

test('the five words are the five words, spelled and ordered as runtime-py spells them', () => {
  assert.deepEqual([...INSTALL_SHAPES], ['registry', 'local-file', 'linked', 'checkout', 'ephemeral']);
});

// ============================================================ every shape, from real state

test('a registry install is the ABSENCE of a local origin, and says so without a path', () => {
  const running = installed(room(), {
    entry: {
      version: '0.30.0',
      resolved: 'https://registry.npmjs.org/bantamkit-mcp/-/bantamkit-mcp-0.30.0.tgz',
      integrity: 'sha512-deadbeef',
    },
  });
  const install = deriveInstall(running, null);
  assert.equal(install.shape, 'registry');
  assert.equal(install.source, null);
  assert.match(install.sourceReason, /^a registry install records no origin path on this machine/);
  assert.match(install.sourceReason, /Reinstall by name to move it\.$/);
});

test('a global install records nothing at all, and the absence is still positive evidence', () => {
  // MEASURED, not assumed: `<npm prefix -g>/lib/node_modules` on this machine holds three
  // packages and NO `.package-lock.json`, and npm 7+ writes no `_resolved` into the installed
  // `package.json` either. A real directory under `node_modules` that is not a symlink and
  // carries no `file:` record is a registry install by elimination — the two alternatives both
  // leave a trace, and this one leaves none.
  const install = deriveInstall(installed(room(), {}), null);
  assert.equal(install.shape, 'registry');
  assert.equal(install.source, null);
});

test('a `file:` tarball is local-file, and the recorded path is resolved against the project', () => {
  const project = room();
  const tarball = join(project, 'pack', 'bantamkit-mcp-0.25.0.tgz');
  mkdirSync(dirname(tarball), { recursive: true });
  writeFileSync(tarball, 'not really a tarball', 'utf8');
  const running = installed(project, {
    entry: { version: '0.25.0', resolved: 'file:pack/bantamkit-mcp-0.25.0.tgz' },
  });
  const install = deriveInstall(running, null);
  assert.equal(install.shape, 'local-file');
  assert.equal(install.source, tarball);
  assert.equal(installSourceCondition(install), null, 'a tarball that is still there is not a problem');
});

test('npm writes the recorded path RAW, so a space in it survives to the condition', () => {
  // Measured against npm 11.6.2: `npm i "<dir with a space>/x.tgz"` records
  // `"resolved": "file:../my dir/x.tgz"` — no percent-encoding. Decoding it as a URL would
  // corrupt any real filename containing a literal `%`, so only the `file://` URL form is
  // decoded and this bare form is not. A person's own directory name is the case that turns up.
  const project = room();
  const tarball = join(project, 'my dir', 'bantamkit-mcp-0.25.0.tgz');
  mkdirSync(dirname(tarball), { recursive: true });
  writeFileSync(tarball, 'x', 'utf8');
  const install = deriveInstall(
    installed(project, { entry: { resolved: 'file:my dir/bantamkit-mcp-0.25.0.tgz' } }),
    null,
  );
  assert.equal(install.source, tarball);
  assert.equal(installSourceCondition(install), null);
});

test('a `file:` directory dependency is linked, through the symlink npm actually makes', () => {
  const root = room();
  const source = join(root, 'src');
  const running = packageTree(source);
  const project = join(root, 'proj');
  mkdirSync(join(project, 'node_modules'), { recursive: true });
  symlinkSync(source, join(project, 'node_modules', 'bantamkit-mcp'), 'dir');
  writeJson(join(project, 'node_modules', '.package-lock.json'), {
    packages: { 'node_modules/bantamkit-mcp': { resolved: '../src', link: true } },
  });
  writeJson(join(project, 'package.json'), { name: 'proj' });

  // This is what Node hands the server: `import.meta.url` is REALPATHED (measured), so the
  // running file names the source tree and the node_modules ancestor is gone from it. What
  // survives is the entry path, which Node does NOT resolve — also measured.
  const entry = join(project, 'node_modules', 'bantamkit-mcp', 'dist', 'cli.js');
  const install = deriveInstall(running, entry);
  assert.equal(install.shape, 'linked');
  assert.equal(install.source, source);
  assert.equal(installSourceCondition(install), null, 'the tree being read is by definition there');
});

test('a linked install is still linked when the symlink is NOT resolved (--preserve-symlinks)', () => {
  const root = room();
  const source = join(root, 'src');
  packageTree(source);
  const project = join(root, 'proj');
  mkdirSync(join(project, 'node_modules'), { recursive: true });
  symlinkSync(source, join(project, 'node_modules', 'bantamkit-mcp'), 'dir');
  writeJson(join(project, 'node_modules', '.package-lock.json'), {
    packages: { 'node_modules/bantamkit-mcp': { resolved: '../src', link: true } },
  });
  writeJson(join(project, 'package.json'), { name: 'proj' });
  const running = join(project, 'node_modules', 'bantamkit-mcp', 'dist', 'mcp', 'identity.js');
  const install = deriveInstall(running, null);
  assert.equal(install.shape, 'linked');
  assert.equal(install.source, source);
});

test('a symlinked package directory is linked even when no lockfile records it', () => {
  // The fallback the absence-is-evidence branch must not swallow: a link is a positive trace,
  // so a missing `.package-lock.json` beside one is not evidence of a registry install.
  const root = room();
  const source = join(root, 'src');
  packageTree(source);
  const project = join(root, 'proj');
  mkdirSync(join(project, 'node_modules'), { recursive: true });
  symlinkSync(source, join(project, 'node_modules', 'bantamkit-mcp'), 'dir');
  writeJson(join(project, 'package.json'), { name: 'proj' });
  const running = join(project, 'node_modules', 'bantamkit-mcp', 'dist', 'mcp', 'identity.js');
  const install = deriveInstall(running, null);
  assert.equal(install.shape, 'linked');
  assert.equal(install.source, source);
});

test('an origin that cannot be STATTED is not an origin that is gone', (t) => {
  // `existsSync` answers `false` for a permission error, which would report a deleted tarball
  // where the truth is a directory nobody may read. The reference returns no condition for one,
  // and so does this: `present` is `null`, and only `false` fires.
  //
  // platform-checked: PORTABLE, and the skip below is the mechanism. Windows honours only the
  // read-only bit, so `chmodSync(dir, 0o000)` changes nothing a stat has to obey and the stat
  // SUCCEEDS there — which is precisely the `present === true` arm, so this test skips itself on
  // Windows and asserts nothing about it. It is not marked POSIX-only because the arm that
  // matters (`present === false`, the regression) is still a FAILURE on every platform.
  // THE SKIP IS NARROW ON PURPOSE. An earlier draft bailed out whenever `present` was anything
  // but `null`, which meant the `false` a regression produces ALSO passed silently — measured:
  // the mutation that reports every errno as "gone" stayed green through it. It now skips only
  // where the stat genuinely SUCCEEDED (root, or a filesystem that ignores the mode, which is
  // Windows), and `false` is a failure. `chmod 0o000` really does return EACCES here.
  const locked = join(room(), 'locked');
  mkdirSync(locked, { recursive: true });
  const buried = join(locked, 'bantamkit-mcp-0.25.0.tgz');
  writeFileSync(buried, 'x', 'utf8');
  chmodSync(locked, 0o000);
  let present;
  try {
    ({ present } = originStat(buried));
  } finally {
    chmodSync(locked, 0o755);
  }
  if (present === true) {
    t.skip('this filesystem let the stat through a 0o000 directory, so there is nothing to deny');
    return;
  }
  assert.equal(present, null, 'a stat that was DENIED was reported as an origin that is gone');
  assert.equal(installSourceCondition({ shape: 'local-file', source: buried, sourceReason: '' }), null);
});

test('a tree no installer put anywhere is a checkout, and carries NO source', () => {
  const install = deriveInstall(packageTree(join(room(), 'runtime-ts')), null);
  assert.equal(install.shape, 'checkout');
  assert.equal(install.source, null);
  assert.equal(
    install.sourceReason,
    'no installer recorded this tree, so there is no origin path to check — the source IS ' +
      '`package_path`, and it is updated where it was cloned.',
  );
  assert.equal(installSourceCondition(install), null);
});

test('an entry reached through SOMEBODY ELSE\'s node_modules does not make a checkout linked', () => {
  // The trap this guards: a checkout has its own `node_modules` for devDependencies, so
  // "the entry path contains the segment node_modules" is not the question. The question is
  // whether it contains `node_modules/bantamkit-mcp`, which is the link npm would have made.
  const root = room();
  const running = packageTree(join(root, 'runtime-ts'));
  const other = join(root, 'runtime-ts', 'node_modules', 'typescript', 'bin', 'tsc');
  mkdirSync(dirname(other), { recursive: true });
  writeFileSync(other, '// not us\n', 'utf8');
  assert.equal(deriveInstall(running, other).shape, 'checkout');
});

test('an npx cache is ephemeral — from the marker npm writes, not from a directory name', () => {
  const project = room();
  const tarball = join(project, 'x.tgz');
  writeFileSync(tarball, 'x', 'utf8');
  const running = installed(project, { entry: { resolved: 'file:x.tgz' }, npx: true });
  const install = deriveInstall(running, null);
  assert.equal(install.shape, 'ephemeral');
  // The shape is the ENVIRONMENT and the source is the ORIGIN; they are two axes and this
  // install has both. Collapsing them would have lost exactly the fact AS-7 was filed about.
  assert.equal(install.source, tarball);
});

test('an npx cache filled from the registry is ephemeral with no origin path to check', () => {
  const install = deriveInstall(
    installed(room(), {
      entry: { resolved: 'https://registry.npmjs.org/bantamkit-mcp/-/bantamkit-mcp-0.30.0.tgz' },
      npx: true,
    }),
    null,
  );
  assert.equal(install.shape, 'ephemeral');
  assert.equal(install.source, null);
  assert.match(install.sourceReason, /^an ephemeral install records no origin path on this machine/);
});

// ============================================================ the incident itself

test('THE INCIDENT: an npx cache whose `file:` tarball is gone names the path that is gone', () => {
  // `~/.npm/_npx/227dc99689421cd5/package.json` on this machine, rebuilt: the dependency is a
  // tarball under a session scratchpad five releases old, and that directory was cleaned up
  // long ago. Nothing said so for five releases. This is the assertion that would have.
  const project = room();
  const gone = join(
    project, 'private', 'tmp', 'claude-501', 'session', 'scratchpad', 'bantamkit-mcp-0.25.0.tgz',
  );
  const running = installed(project, {
    entry: { version: '0.25.0', resolved: `file:${'private/tmp/claude-501/session/scratchpad/bantamkit-mcp-0.25.0.tgz'}` },
    npx: true,
  });
  const install = deriveInstall(running, null);
  assert.equal(install.shape, 'ephemeral');
  assert.equal(install.source, gone);

  const condition = installSourceCondition(install);
  assert.equal(condition.key, 'install-source-missing');
  assert.equal(
    condition.sentence,
    `this server was installed from ${gone}, which no longer exists, so nothing can be ` +
      'refreshed in place there — reinstall bantamkit by name from a package registry and ' +
      'restart the server.',
  );
  // THE PRODUCT NAME, NOT THE PACKAGE ID. `git_commit` already diverged once on a noun; the
  // reference says `bantamkit` and so does this.
  assert.ok(!condition.sentence.includes('bantamkit-mcp by name'), condition.sentence);
  // AND THE REMEDY IS NOT AN UPDATE RUN. A dangling origin cannot be refreshed in place by
  // construction, so naming a command that would exit 0 having changed nothing is the J46-4
  // defect. Nothing here says `update`.
  assert.ok(!/update/i.test(condition.sentence), condition.sentence);
});

test('a plain `file:` install whose tarball is gone fires the same condition', () => {
  const project = room();
  const running = installed(project, { entry: { resolved: 'file:pack/gone.tgz' } });
  const install = deriveInstall(running, null);
  assert.equal(install.shape, 'local-file');
  assert.match(installSourceCondition(install).sentence, /which no longer exists/);
});

// ============================================================ what it refuses to guess

test('an origin that is neither a path nor a remote tarball is REFUSED, not rounded', () => {
  const running = installed(room(), {
    entry: { resolved: 'git+ssh://git@github.com/Ink01101011/bantamkit.git#0f0e410' },
  });
  assert.throws(
    () => deriveInstall(running, null),
    (error) => {
      assert.ok(error instanceof Undetermined, `${error.constructor.name} is not Undetermined`);
      assert.equal(
        error.message,
        'this install records its origin as git+ssh://git@github.com/Ink01101011/bantamkit.git' +
          '#0f0e410, which is neither a package index nor a path on this machine, so its shape ' +
          'is not one of registry, local-file, linked, checkout, ephemeral. A git or http ' +
          'origin is updated by reinstalling from that same URL.',
      );
      return true;
    },
  );
});

test('a refused shape is REPORTED by build_identity, never a sixth word and never a crash', () => {
  const running = installed(room(), { entry: { resolved: 'github:Ink01101011/bantamkit' } });
  let raised;
  try {
    deriveInstall(running, null);
  } catch (error) {
    raised = error;
  }
  assert.ok(raised instanceof Undetermined);
  assert.ok(!INSTALL_SHAPES.includes(raised.message));
});

// ============================================================ shape is LOCATION, not identity

test('install_shape is not folded into build_id, recomputed from the five named inputs', () => {
  const previous = process.env.BANTAMKIT_ASSETS;
  process.env.BANTAMKIT_ASSETS = ASSETS;
  try {
    const identity = Object.fromEntries(buildIdentity('0.30.0', '1.30.0'));
    assert.ok(INSTALL_SHAPES.includes(identity.install_shape), JSON.stringify(identity.install_shape));
    const inputs = {
      runtime: identity.runtime,
      server_name: identity.server_name,
      version: identity.version,
      code_digest: identity.code_digest,
      assets_digest: identity.assets_digest,
    };
    // Byte for byte, from the four named inputs plus `runtime` — the same recomputation the
    // reference does over `identity_inputs`. Folding a sixth in reddens the first assertion;
    // the second says which sixth, so the mutation cannot pass by moving the hash somewhere.
    assert.equal(identity.build_id, buildIdFor(inputs));
    assert.notEqual(identity.build_id, buildIdFor({ ...inputs, install_shape: identity.install_shape }));
  } finally {
    if (previous === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = previous;
  }
});

test('the three fields are reported together, and an absent origin is named rather than dropped', () => {
  const previous = process.env.BANTAMKIT_ASSETS;
  process.env.BANTAMKIT_ASSETS = ASSETS;
  try {
    const identity = Object.fromEntries(buildIdentity('0.30.0', '1.30.0'));
    for (const field of ['install_shape', 'install_source', 'install_source_exists']) {
      assert.ok(field in identity, field);
    }
    // This test file runs out of the checkout, so the shape here is `checkout` and the two
    // origin fields are RB-P51 refusals carrying a reason — never `null`, never `""`.
    assert.equal(identity.install_shape, 'checkout');
    assert.match(identity.install_source.unavailable, /no installer recorded this tree/);
    assert.equal(
      identity.install_source_exists.unavailable,
      'a checkout install records no origin path, so there is nothing here to check for.',
    );
    assert.ok(identity.unavailable.includes('install_source'));
    assert.ok(identity.unavailable.includes('install_source_exists'));
  } finally {
    if (previous === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = previous;
  }
});

test('currentInstall answers from the running location, with no arguments and no server', () => {
  const install = currentInstall();
  assert.equal(install.shape, 'checkout');
  assert.equal(currentInstall(), install, 'derived once per process, not once per call');
});

// ============================================================ no network, proved by running

test('nothing added here opens a network handle, and the census can see one when it happens', async () => {
  // NOT A SUBSTRING SCAN. A grep for `fetch` or `http` is the vacuous version of this test: a
  // comment mentioning `node:https` trips it and `globalThis[['fe','tch'].join('')]` does not,
  // which is exactly the wrong way round. This watches the process instead — every async
  // resource Node creates for a socket, a DNS lookup or a TLS handshake — and then PROVES the
  // watch can see one by opening a socket on purpose, so its silence means something.
  const NETWORK = new Set([
    'TCPWRAP', 'TCPCONNECTWRAP', 'TCPSERVERWRAP', 'UDPWRAP', 'UDPSENDWRAP', 'TLSWRAP',
    'GETADDRINFOREQWRAP', 'GETNAMEINFOREQWRAP', 'QUERYWRAP', 'DNSCHANNEL',
    'HTTPCLIENTREQUEST', 'HTTPINCOMINGMESSAGE',
  ]);
  const drain = () => new Promise((resolve) => setTimeout(resolve, 60));
  const seen = [];
  const hook = createHook({ init(_id, type) { if (NETWORK.has(type)) seen.push(type); } });

  const realFetch = globalThis.fetch;
  let fetched = 0;
  globalThis.fetch = () => { fetched += 1; throw new Error('fetch was called'); };
  const previous = process.env.BANTAMKIT_ASSETS;
  process.env.BANTAMKIT_ASSETS = ASSETS;

  hook.enable();
  try {
    // Every branch of the derivation, over real trees, plus both public entry points.
    const project = room();
    writeFileSync(join(project, 'here.tgz'), 'x', 'utf8');
    const trees = [
      [installed(room(), { entry: { resolved: 'https://registry.npmjs.org/x/-/x-1.tgz' } }), null],
      [installed(project, { entry: { resolved: 'file:here.tgz' }, npx: true }), null],
      [installed(room(), { entry: { resolved: 'file:gone.tgz' } }), null],
      [installed(room(), { entry: { resolved: 'git+https://example.invalid/x.git' } }), null],
      [packageTree(join(room(), 'runtime-ts')), null],
    ];
    for (const [running, entry] of trees) {
      try {
        installSourceCondition(deriveInstall(running, entry));
      } catch (error) {
        if (!(error instanceof Undetermined)) throw error;
      }
    }
    currentInstall();
    buildIdentity('0.30.0', '1.30.0');
    await drain();
    assert.deepEqual(seen, [], `a network handle was opened: ${seen.join(', ')}`);
    assert.equal(fetched, 0, 'fetch was called');

    // THE CONTROL, and it is the half that makes the assertion above worth anything. A local
    // connect to a closed port sends nothing anywhere and still creates the handles this
    // census is watching for. If this stops firing, every assertion above is vacuous.
    const socket = net.connect({ host: '127.0.0.1', port: 1 });
    socket.on('error', () => {});
    await drain();
    socket.destroy();
    assert.ok(seen.length > 0, 'the census saw no handle even for a real socket, so it proves nothing');
    assert.throws(() => globalThis.fetch('https://example.invalid'), /fetch was called/);
  } finally {
    hook.disable();
    globalThis.fetch = realFetch;
    if (previous === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = previous;
  }
});
