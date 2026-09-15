/**
 * `bantamkit-mcp --update` on the Node side: what it prints, what it refuses, what it never runs.
 *
 * NOT ONE NODE IN THIS FILE REACHES A REGISTRY OR RUNS AN INSTALLER. A test that asked
 * `registry.npmjs.org` would fail on a plane and pass for the wrong reason off a cache, and a
 * test that ran `npm install -g bantamkit-mcp@latest` would rewrite the developer's own machine
 * mid-suite. `update` therefore takes both as options with real defaults — `fetch` and
 * `installer` — and every arm below is exercised through a substitute. The npm command is
 * CAPTURED and asserted on; it is never executed.
 *
 * TWO NODES DO OPEN A SOCKET, AND BOTH ARE LOOPBACK. `fetchIndex`'s whole contract with
 * `update` is which exception it throws, and that contract is about what Node's own `fetch`
 * does — so it is pinned against a local server that accepts and never answers, and against a
 * local port with nothing on it. Neither sends a byte off this machine, and stubbing them would
 * have asserted this file's guess about undici back at itself, which is the half that matters.
 *
 * THE VERSION PAIRS ARE CHOSEN TO BE AWKWARD ON PURPOSE, and they are the reference's. `0.30.0`
 * against `0.30.0` is the pair every implementation agrees on including a wrong one, so it is
 * here as the floor and not as the proof. The pairs that decide anything are `0.9.0` against
 * `0.10.0` (where a string compare says the index is BEHIND), `0.30.0` against `0.30.10` (the
 * same defect one component further in), an index that really IS behind, and a prerelease —
 * where this implementation is deliberately wrong and has to be wrong the SAME WAY as the
 * reference.
 */
import assert from 'node:assert/strict';
import { createHook } from 'node:async_hooks';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import net from 'node:net';
import { homedir, tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { keptCli, keptManifest, keptPrefix } from '../dist/npminstall.js';
import {
  AHEAD,
  COMPARISON,
  DEFAULT_TIMEOUT_SECONDS,
  INDEX_URL,
  IndexTimeout,
  NO_OUTPUT,
  NO_ROUTE,
  NOT_JSON,
  NO_VERSION_FIELD,
  PACKAGE,
  PROGRAM,
  ROUTES,
  UP_TO_DATE,
  UpdateRefused,
  compareVersions,
  fetchIndex,
  fill,
  installEnvironment,
  latestFromIndexPayload,
  runUpdate,
  shlexJoin,
  update,
  upgradeCommand,
} from '../dist/selfupdate.js';
import { INSTALL_SHAPES, currentInstall } from '../dist/mcp/identity.js';

const SRC = dirname(dirname(fileURLToPath(import.meta.url)));
const CLI = join(SRC, 'dist', 'cli.js');

/**
 * The built CLI as a SUBPROCESS, the way `test/cli-surface.test.mjs` drives it. `cli.ts` is a
 * script with top-level `await` that opens a server, so it cannot be imported to be asked about
 * its parser — and a second copy of the parser here would be the defect the `cli` suite exists
 * to catch. `COLUMNS`, `LINES` and `BANTAMKIT_ASSETS` are scrubbed for the reason the
 * conformance harness scrubs them: otherwise a developer's terminal size is an input.
 */
function runCli(argv, columns) {
  const env = { ...process.env };
  delete env.COLUMNS;
  delete env.LINES;
  delete env.BANTAMKIT_ASSETS;
  if (columns !== undefined) env.COLUMNS = String(columns);
  return spawnSync(process.execPath, [CLI, ...argv], { input: '', env, encoding: 'utf8' });
}

/** What `registry.npmjs.org/bantamkit-mcp/latest` answers, reduced to the field that is read. */
const payload = (version) => JSON.stringify({ name: PACKAGE, version });

/** A stub index that answers one version and records that it was asked. */
function stubFetch(version) {
  const calls = [];
  const fetch = async (url, timeout) => {
    calls.push([url, timeout]);
    return payload(version);
  };
  fetch.calls = calls;
  return fetch;
}

const throwingFetch = (error) => async () => {
  throw error;
};
const bodyFetch = (text) => async () => text;

const installerMustNotRun = (command) => {
  throw new assert.AssertionError({ message: `an installer ran when nothing should have: ${command}` });
};

function recordingInstaller(code = 0, output = 'added 1 package in 902ms') {
  const commands = [];
  const installer = (command) => {
    commands.push([...command]);
    return [code, output];
  };
  installer.commands = commands;
  return installer;
}

/** A fixed environment, so a rendered command is the product's and not this checkout's path. */
const ENV = { root: '/opt/x', global: false };
const REGISTRY = { shape: 'registry', source: '/does/not/matter' };
const SHAPELESS = ['local-file', 'linked', 'checkout', 'ephemeral'];

async function refusal(fn) {
  try {
    await fn();
  } catch (e) {
    if (!(e instanceof UpdateRefused)) throw e;
    return e.message;
  }
  throw new Error('nothing was refused');
}

const rooms = [];
after(() => {
  for (const dir of rooms) rmSync(dir, { recursive: true, force: true });
});

/** A scratch directory that is really on disk and is really removed when the file is done. */
function room() {
  const dir = mkdtempSync(join(tmpdir(), 'bk-update-'));
  rooms.push(dir);
  return dir;
}

// ============================================================ the answers that change nothing

test('the same version says up to date, runs no installer, and is the sentence the user asked for', async () => {
  const fetch = stubFetch('0.30.0');
  const report = await update('0.30.0', REGISTRY, { fetch, installer: installerMustNotRun, environment: ENV });

  // THE PER-SIDE LITERAL, and it is spelled out rather than built from the constants. J46-28
  // measured on this branch that reverting the bare-help branch on ONE side reddens 4
  // conformance cases and on BOTH reddens only 3 — a differential goes back to passing when
  // both sides move together. So the sentence is pinned as TEXT here, where only this runtime
  // can change it.
  assert.equal(
    report,
    'bantamkit-mcp 0.30.0 is installed; the package index has 0.30.0.\nup to date.',
  );
  assert.deepEqual(fetch.calls, [[INDEX_URL, DEFAULT_TIMEOUT_SECONDS]]);
});

test('an index BEHIND the installed version installs nothing and says so', async () => {
  const report = await update('0.31.0', REGISTRY, {
    fetch: stubFetch('0.30.0'),
    installer: installerMustNotRun,
    environment: ENV,
  });

  assert.equal(
    report,
    'bantamkit-mcp 0.31.0 is installed; the package index has 0.30.0.\n' +
      'the installed version is ahead of the package index; there is nothing to update to.',
  );
});

test('the index being behind is decided numerically, not alphabetically', async () => {
  // `'0.9.0' > '0.10.0'` as strings, so an implementation that compared text would report the
  // index as BEHIND here and do nothing. This is the pair that catches it.
  const installer = recordingInstaller();
  const report = await update('0.9.0', REGISTRY, { fetch: stubFetch('0.10.0'), installer, environment: ENV });

  assert.ok(report.includes('updated bantamkit-mcp from 0.9.0 to 0.10.0.'), report);
  assert.equal(installer.commands.length, 1);
});

// ============================================================ the comparison rule, exactly

test('compareVersions orders the pairs the sentences depend on', () => {
  const pairs = [
    ['0.30.0', '0.30.0', 0],
    ['0.30', '0.30.0', 0, 'the shorter side is zero-padded, so these are one release'],
    ['0.29.0', '0.30.0', -1],
    ['0.31.0', '0.30.0', 1],
    ['0.9.0', '0.10.0', -1, 'the numeric rule, where a string compare inverts the answer'],
    ['0.30.0', '0.30.10', -1, 'the same defect one component further in'],
    ['0.30.10', '0.30.0', 1],
    ['1.0.0', '0.99.99', 1],
  ];
  for (const [left, right, want, why] of pairs) {
    assert.equal(compareVersions(left, right), want, `${left} vs ${right}${why ? ` — ${why}` : ''}`);
  }
});

test('a prerelease sorts AFTER its release, which is wrong by semver and right by the reference', () => {
  // PINNED, NOT FIXED, and the pin is the point. `runtime-py`'s `_version_key` docstring gives
  // the reason: no prerelease has ever been published to either registry, PEP 440 would be a
  // much larger thing to reproduce byte for byte, and what matters is that both runtimes are
  // wrong in the SAME direction. A correct semver comparison HERE would be a divergence, not
  // an improvement — it would make one runtime install a release over a prerelease and the
  // other refuse, from one command line.
  assert.equal(compareVersions('0.31.0', '0.31.0rc1'), -1);
  assert.equal(compareVersions('0.31.0rc1', '0.31.0'), 1);
  assert.equal(compareVersions('1.0.0rc1', '1.0.0rc2'), -1, 'two prereleases still order by text');
});

// ============================================================ the answer that changes something

test('a newer index runs the upgrade command, and the command is captured rather than run', async () => {
  const installer = recordingInstaller();
  const report = await update('0.29.0', REGISTRY, { fetch: stubFetch('0.30.0'), installer, environment: ENV });

  assert.deepEqual(installer.commands, [['npm', 'install', '--prefix', '/opt/x', 'bantamkit-mcp@latest']]);
  assert.equal(
    report,
    'bantamkit-mcp 0.29.0 is installed; the package index has 0.30.0.\n' +
      'updating from the package index: npm install --prefix /opt/x bantamkit-mcp@latest\n' +
      'the command printed:\n' +
      'added 1 package in 902ms\n' +
      'updated bantamkit-mcp from 0.29.0 to 0.30.0.\n' +
      'restart the server: a running bantamkit-mcp keeps serving the code it loaded at startup, ' +
      'so bantamkit_status will report 0.29.0 until the host reconnects.',
  );
});

test('an installer that printed nothing still reports in one shape', async () => {
  const report = await update('0.29.0', REGISTRY, {
    fetch: stubFetch('0.30.0'),
    installer: recordingInstaller(0, '   \n  '),
    environment: ENV,
  });
  assert.ok(report.includes(`the command printed:\n${NO_OUTPUT}\n`), report);
});

test('an installer that failed refuses and hands back what the command said', async () => {
  const message = await refusal(() =>
    update('0.29.0', REGISTRY, {
      fetch: stubFetch('0.30.0'),
      installer: recordingInstaller(7, 'npm ERR! code EACCES'),
      environment: ENV,
    }),
  );
  assert.equal(
    message,
    'the update command exited 7: npm install --prefix /opt/x bantamkit-mcp@latest\n' +
      'bantamkit-mcp 0.29.0 is still installed; nothing was changed.\n' +
      'the command printed:\n' +
      'npm ERR! code EACCES',
  );
});

// ============================================================ the shapes this flag will not touch

for (const shape of SHAPELESS) {
  test(`a ${shape} install refuses, names the real route, and runs nothing`, async () => {
    const message = await refusal(() =>
      update('0.29.0', { shape, source: '/tmp/an-origin' }, {
        fetch: stubFetch('0.30.0'),
        installer: installerMustNotRun,
        environment: ENV,
      }),
    );
    assert.ok(
      message.startsWith(
        'bantamkit-mcp 0.29.0 is installed and the package index has 0.30.0, but this is a ' +
          `${shape} install, which --update will not touch. `,
      ),
      message,
    );
    assert.equal(message.split('\n').length, 1, 'a one-line refusal, like every --install refusal');
    assert.ok(!message.includes('{'), 'an unsubstituted placeholder reached the operator');
  });
}

test('the four routes are four DIFFERENT sentences, and they cover INSTALL_SHAPES exactly', () => {
  // The parametrised node above checks each shape's refusal against its own shape word, which
  // is interpolated from the same argument — so a `ROUTES` whose four values were ONE string
  // would be green four times over. This is the vacuity it cannot see.
  const rendered = SHAPELESS.map((shape) =>
    fill(ROUTES[shape], {
      source: '/tmp/an-origin',
      package: PACKAGE,
      command: 'npm install --global bantamkit-mcp@latest',
      installed: '0.29.0',
      latest: '0.30.0',
      shape,
    }),
  );
  assert.equal(new Set(rendered).size, SHAPELESS.length, rendered.join('\n'));
  assert.ok(!('registry' in ROUTES), '`registry` is the shape this flag DOES update; a route for it is unreachable text');
  assert.deepEqual(
    [...new Set([...Object.keys(ROUTES), 'registry'])].sort(),
    [...INSTALL_SHAPES].sort(),
    '`ROUTES` plus `registry` must cover `INSTALL_SHAPES` exactly — a shape with no row falls ' +
      'through to the no-route-recorded refusal, which is guess-free but is not an answer',
  );
});

test('what --update says under npx is true of the CACHE, not of a fresh resolve', () => {
  // `README.md#silent-version-float` measured it: `npx -y bantamkit-mcp` resolves `latest` ONCE
  // and caches it, so two people with byte-identical config can be running builds resolved
  // weeks apart. The reference's `ephemeral` row says "the next run fetches {latest} by
  // itself", which is true of a `pipx run` environment and FALSE here — this is the one route
  // that is a correction rather than a translation, and the assertion is that it stays one.
  const rendered = fill(ROUTES['ephemeral'], {
    source: '',
    package: PACKAGE,
    command: 'npm install --global bantamkit-mcp@latest',
    installed: '0.29.0',
    latest: '0.30.0',
    shape: 'ephemeral',
  });
  assert.ok(rendered.includes('the next run serves the same cached 0.29.0'), rendered);
  assert.ok(rendered.includes('bantamkit-mcp@latest'), rendered);
  assert.ok(!rendered.includes('0.30.0'), 'the npx cache does not fetch the latest version by itself');
});

test('the two shapes with a recorded origin print that origin', async () => {
  for (const shape of ['local-file', 'linked']) {
    const message = await refusal(() =>
      update('0.29.0', { shape, source: '/tmp/where-it-came-from' }, {
        fetch: stubFetch('0.30.0'),
        installer: installerMustNotRun,
        environment: ENV,
      }),
    );
    assert.ok(message.includes('/tmp/where-it-came-from'), shape);
  }
});

test('a shape word this table has never heard of refuses rather than guessing', async () => {
  const message = await refusal(() =>
    update('0.29.0', { shape: 'something-new', source: '' }, {
      fetch: stubFetch('0.30.0'),
      installer: installerMustNotRun,
      environment: ENV,
    }),
  );
  assert.ok(
    message.includes('There is no recorded update route for a something-new install'),
    message,
  );
});

// ============================================================ the network, refused by name

test('unreachable and garbage are two different refusals', async () => {
  const offline = await refusal(() =>
    update('0.29.0', REGISTRY, {
      fetch: throwingFetch(new Error('getaddrinfo ENOTFOUND registry.npmjs.org')),
      installer: installerMustNotRun,
      environment: ENV,
    }),
  );
  const garbage = await refusal(() =>
    update('0.29.0', REGISTRY, {
      fetch: bodyFetch('<html>captive portal</html>'),
      installer: installerMustNotRun,
      environment: ENV,
    }),
  );

  assert.equal(
    offline,
    'the package index could not be reached: getaddrinfo ENOTFOUND registry.npmjs.org; ' +
      '--update needs the network, and nothing was changed.',
  );
  assert.equal(
    garbage,
    'the package index answered, but not with a version for bantamkit-mcp: ' +
      'the response is not JSON; nothing was changed.',
  );
  assert.notEqual(offline, garbage);
});

for (const [body, why] of [
  ['<html>login</html>', NOT_JSON],
  ['', NOT_JSON],
  ['{}', NO_VERSION_FIELD],
  ['[]', NO_VERSION_FIELD],
  ['null', NO_VERSION_FIELD],
  ['{"version": 30}', NO_VERSION_FIELD],
  ['{"version": "  "}', NO_VERSION_FIELD],
  ['{"info": {"version": "0.30.0"}}', NO_VERSION_FIELD],
]) {
  test(`a body of ${JSON.stringify(body)} is refused by name rather than installed`, async () => {
    const message = await refusal(() =>
      update('0.29.0', REGISTRY, { fetch: bodyFetch(body), installer: installerMustNotRun, environment: ENV }),
    );
    assert.equal(
      message,
      `the package index answered, but not with a version for bantamkit-mcp: ${why}; nothing was changed.`,
    );
  });
}

test("PyPI's own JSON path is not this registry's, and reading it would answer nothing", () => {
  // The one place divergence #1 is observable from inside this file: the reference reads
  // `info.version` and this reads the top level. A body shaped like PyPI's is a body with no
  // version in it HERE — which is the refusal above, not a silent `undefined`.
  assert.equal(latestFromIndexPayload(payload('0.30.0')), '0.30.0');
  assert.throws(() => latestFromIndexPayload('{"info": {"version": "0.30.0"}}'), UpdateRefused);
});

test('a timeout is its own refusal and names the number of seconds as an integer', async () => {
  const message = await refusal(() =>
    update('0.30.0', REGISTRY, {
      fetch: throwingFetch(new IndexTimeout('The operation was aborted due to timeout')),
      installer: installerMustNotRun,
      environment: ENV,
    }),
  );
  // `10` and not `10.0`. The reference spells that out in `_seconds` precisely so this sentence
  // is byte-identical rather than one character divergent — and a one-character divergence
  // costs a `docs/porting.md` row and a ruling for nothing.
  assert.equal(
    message,
    'the package index did not answer within 10 seconds; --update needs the network, and ' +
      'nothing was changed.',
  );
});

test('the timeout in the sentence is the one the caller passed, and it reached the fetch', async () => {
  const seen = [];
  const message = await refusal(() =>
    update('0.30.0', REGISTRY, {
      fetch: async (_url, timeout) => {
        seen.push(timeout);
        throw new IndexTimeout('t');
      },
      installer: installerMustNotRun,
      timeout: 2.5,
      environment: ENV,
    }),
  );
  assert.deepEqual(seen, [2.5]);
  assert.ok(message.includes('within 2.5 seconds'), message);
});

test('a timeout is not swallowed by the unreachable arm — the premise, and the order', async () => {
  // THE NODE ANALOGUE OF `issubclass(TimeoutError, OSError)`. There the two `except` clauses are
  // ordered because a timeout IS an OSError; here `IndexTimeout` IS an `Error`, so the same
  // reversal has the same effect: every timeout would read as "could not be reached", which
  // names the wrong problem and sends the operator to check a network that is working.
  assert.ok(new IndexTimeout('x') instanceof Error, 'the premise this node exists for');

  // AND THE PLATFORM'S OWN HALF OF IT, measured on this interpreter: what `AbortSignal.timeout`
  // hands back is a DOMException — which is ALSO `instanceof Error`. That is why `fetchIndex`
  // tests the timeout first and translates it, rather than letting a generic Error catch win.
  const signal = AbortSignal.timeout(1);
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(signal.reason.name, 'TimeoutError');
  assert.ok(signal.reason instanceof Error, 'a DOMException is an Error, so order decides this');

  const message = await refusal(() =>
    update('0.30.0', REGISTRY, {
      fetch: throwingFetch(new IndexTimeout('boom')),
      installer: installerMustNotRun,
      environment: ENV,
    }),
  );
  assert.ok(message.startsWith('the package index did not answer within'), message);
});

// ============================================================ where an npm install would point

test('installEnvironment reads a RECORD: a package.json beside node_modules means --prefix', () => {
  const root = room();
  const project = join(root, 'project');
  mkdirSync(join(project, 'node_modules', PACKAGE, 'dist'), { recursive: true });
  writeFileSync(join(project, 'package.json'), '{"name":"host"}', 'utf8');

  const env = installEnvironment(join(project, 'node_modules', PACKAGE, 'dist', 'selfupdate.js'));
  assert.deepEqual(env, { root: project, global: false });
  assert.deepEqual(upgradeCommand(env), ['npm', 'install', '--prefix', project, 'bantamkit-mcp@latest']);
});

test('no package.json beside node_modules is the GLOBAL tree, and --prefix there is destructive', () => {
  // MEASURED 2026-09-11 with npm 11.6.2, and this is why the discriminator exists rather than a
  // hardcoded `--global`. `npm install --prefix <dir> <pkg>` into a directory that has no
  // `package.json` PRUNES every sibling package — a two-package fixture came back with one. The
  // real global tree on this machine is exactly that shape:
  // `/Users/kktest/.local/share/mise/installs/node/25.2.1/lib` holds `node_modules` with
  // `@shopify`, `eas-cli` and `npm` in it and no `package.json` beside it. Getting this
  // backwards would make `--update` delete a developer's other global CLIs.
  const root = room();
  const lib = join(root, 'prefix', 'lib');
  mkdirSync(join(lib, 'node_modules', PACKAGE, 'dist'), { recursive: true });

  const env = installEnvironment(join(lib, 'node_modules', PACKAGE, 'dist', 'selfupdate.js'));
  assert.deepEqual(env, { root: lib, global: true });
  assert.deepEqual(upgradeCommand(env), ['npm', 'install', '--global', 'bantamkit-mcp@latest']);
});

test('the no-node_modules arm of installEnvironment cannot be reached from a registry install', () => {
  // It is total rather than throwing, and the answer it gives is the global command, which
  // needs no root. That arm is UNREACHABLE from the only shape that runs an installer, and the
  // pairing is asserted rather than left as a comment: `deriveInstall` answers `registry` only
  // from inside a `node_modules`, and this repo's own running copy is a `checkout`, which is a
  // shape `--update` refuses before it ever builds a command.
  const root = room();
  mkdirSync(join(root, 'tree', 'dist'), { recursive: true });
  assert.deepEqual(installEnvironment(join(root, 'tree', 'dist', 'selfupdate.js')), { root: '', global: true });
  assert.equal(currentInstall().shape, 'checkout');
});

test('shlexJoin quotes the way shlex.quote does, so the printed command can be pasted back', () => {
  assert.equal(shlexJoin(['npm', 'install', '--global', 'bantamkit-mcp@latest']), 'npm install --global bantamkit-mcp@latest');
  assert.equal(shlexJoin(['npm', 'install', '--prefix', '/tmp/a b']), "npm install --prefix '/tmp/a b'");
  assert.equal(shlexJoin(['x', "it's"]), `x 'it'"'"'s'`);
  assert.equal(shlexJoin(['x', '']), "x ''");
  assert.equal(shlexJoin(['/usr/local/lib']), '/usr/local/lib', 'a plain path is not quoted');
});

test('fill throws on a missing key rather than leaking a placeholder', () => {
  assert.equal(fill(COMPARISON, { program: PROGRAM, installed: '1', latest: '2' }), 'bantamkit-mcp 1 is installed; the package index has 2.');
  assert.throws(() => fill(COMPARISON, { program: PROGRAM }), /no value for \{installed\}/);
});

// ============================================================ no network, proved by running

test('every offline arm of --update opens no network handle, and the census can see one', async () => {
  // THE IDIOM `test/install-shape.test.mjs` ESTABLISHED, and not a substring scan: a grep for
  // `fetch` trips on a comment and misses `globalThis[['fe','tch'].join('')]`, which is exactly
  // the wrong way round. This watches the process — every async resource Node creates for a
  // socket, a DNS lookup or a TLS handshake — and then PROVES the watch can see one.
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

  hook.enable();
  try {
    const arms = [
      () => update('0.30.0', REGISTRY, { fetch: stubFetch('0.30.0'), installer: installerMustNotRun }),
      () => update('0.31.0', REGISTRY, { fetch: stubFetch('0.30.0'), installer: installerMustNotRun }),
      () => update('0.29.0', REGISTRY, { fetch: stubFetch('0.30.0'), installer: recordingInstaller() }),
      () => update('0.29.0', REGISTRY, { fetch: bodyFetch('nope'), installer: installerMustNotRun }),
      () => update('0.29.0', REGISTRY, { fetch: throwingFetch(new IndexTimeout('t')), installer: installerMustNotRun }),
      () => update('0.29.0', REGISTRY, { fetch: throwingFetch(new Error('down')), installer: installerMustNotRun }),
      ...SHAPELESS.map((shape) => () =>
        update('0.29.0', { shape, source: '/tmp/x' }, { fetch: stubFetch('0.30.0'), installer: installerMustNotRun })),
      () => runUpdate(() => {}, () => {}, '0.30.0', '/tmp/pkg', { fetch: stubFetch('0.30.0'), installer: installerMustNotRun }),
      // J51-5: the kept-install arm reads a manifest off disk and still opens nothing.
      () => withHome(async () => {
        seedKept('0.29.0');
        await runUpdate(() => {}, () => {}, '0.20.0', '/tmp/pkg', {
          install: () => ({ shape: 'ephemeral', source: null }),
          fetch: stubFetch('0.30.0'),
          installer: recordingInstaller(),
        });
      }),
    ];
    for (const arm of arms) {
      try {
        await arm();
      } catch (e) {
        if (!(e instanceof UpdateRefused)) throw e;
      }
    }
    installEnvironment();
    compareVersions('0.30.0', '0.30.10');
    await drain();
    assert.deepEqual(seen, [], `a network handle was opened: ${seen.join(', ')}`);
    assert.equal(fetched, 0, 'the global fetch was called on an offline arm');

    // THE CONTROL, and it is the half that makes the assertion above worth anything. A local
    // connect to a closed port sends nothing anywhere and still creates the handles this census
    // is watching for. If this stops firing, every assertion above is vacuous.
    const socket = net.connect({ host: '127.0.0.1', port: 1 });
    socket.on('error', () => {});
    await drain();
    socket.destroy();
    assert.ok(seen.length > 0, 'the census cannot see a socket, so its silence above means nothing');
  } finally {
    hook.disable();
    globalThis.fetch = realFetch;
  }
});

// ============================================================ one importer, one detector

test('cli.ts is the ONLY module in src/ that reaches this one', () => {
  // AS-7(b) was explicit that a dependency-free toolbox must not grow a network call on a path
  // a host reaches, and the user asked for a FLAG rather than a background checker. So the
  // claim is not "we didn't do that" — it is that exactly one module imports `selfupdate` at
  // all, and it is the one the flag lives in. The reference makes the same claim over
  // `mcpserver.py`'s AST; here the unit is the module, because that is what an import is.
  const reaching = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (entry.name.endsWith('.ts') && entry.name !== 'selfupdate.ts') {
        if (/from '\.[^']*selfupdate\.js'/.test(readFileSync(path, 'utf8'))) reaching.push(entry.name);
      }
    }
  };
  walk(join(SRC, 'src'));
  assert.deepEqual(reaching.sort(), ['cli.ts'], `modules importing selfupdate: ${reaching}`);

  // RED-PROOF, on a sample rather than by mutating the tree: the same matcher against the line
  // `server.ts` would have to grow for this gate to be pointed at nothing.
  assert.ok(/from '\.[^']*selfupdate\.js'/.test("import { update } from '../selfupdate.js';"));
  assert.ok(!/from '\.[^']*selfupdate\.js'/.test('// selfupdate.js is never imported here'));
});

/**
 * Block comments and whole-line `//` comments, removed — and NOTHING ELSE.
 *
 * The gate below is a scan for identifiers, and a scan that read the prose too would be the
 * over-eager half of the vacuity pair: this module's own docstrings EXPLAIN why it does not
 * derive a shape, naming `deriveInstall` and `INSTALL_SHAPES` to say so, and a gate that
 * reddened on the explanation is one the next person deletes. A trailing `//` inside a string
 * is deliberately left alone, which is why only a comment that OWNS its line is cut.
 */
function code(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

test('the install shape comes from currentInstall and from nowhere else', () => {
  // AS-7(a)'s answer, used — not a second detector written beside it. `currentInstall()` was
  // shipped at `c9372ca` as a module-level function taking no arguments and touching no server
  // state precisely so this flag could ask it, and a second copy of a derived answer is the
  // defect the `cli` suite exists to catch.
  const source = code(readFileSync(join(SRC, 'src', 'selfupdate.ts'), 'utf8'));
  assert.ok(source.includes('currentInstall'), 'the flag no longer asks the detector at all');
  for (const forbidden of ['deriveInstall', 'INSTALL_SHAPES', 'package-lock', '_npx']) {
    assert.ok(
      !source.includes(forbidden),
      `\`${forbidden}\` appears in selfupdate.ts's CODE, which is a second install-shape derivation`,
    );
  }

  // RED-PROOF ON A SAMPLE, watched rather than asserted from the shape of the regex. The first
  // is the mutation this gate exists for — a second derivation written beside the first — and
  // the second is the prose that must stay green, because a gate that reddens on a comment is
  // deleted by whoever hits it next.
  assert.ok(code("const shape = deriveInstall(here, null).shape;").includes('deriveInstall'));
  assert.ok(!code("  // deriveInstall is never called here\n").includes('deriveInstall'));
  assert.ok(!code("/** never calls deriveInstall */\n").includes('deriveInstall'));
});

// ============================================================ the flag, on the CLI

test('--update is in the generated help without moving the pinned first line', () => {
  // `test/cli-surface.test.mjs` and the `cli` conformance suite both pin the first line of the
  // 80-column usage. Registering `--update` before `--mcp-report` would have moved it and
  // turned a differential suite into a re-baselining one; the flag being present is the cheap
  // half of this assertion and the first line is the rest.
  const help = runCli(['-h'], 80);
  assert.equal(help.status, 0);
  assert.equal(help.stderr, '');
  assert.equal(
    help.stdout.split('\n')[0],
    'usage: bantamkit-mcp [-h] [--assets-root] [--k K] [--index-budget BYTES]',
  );
  assert.ok(
    help.stdout.includes('  --update              check the package index and update this install if it'),
    help.stdout,
  );
  // It takes NO argument — `[--update]` and never `[--update SOMETHING]` — which is what makes
  // it a `store_true` on the wire rather than only in the spec object.
  assert.ok(/\[--update\]/.test(help.stdout), help.stdout);
  assert.ok(!/--update [A-Z]/.test(help.stdout), help.stdout);
});

test('--update is rejected an argument, which is the other half of store_true', () => {
  // A `store` action would have swallowed `x` and served; a `store_true` refuses it as an
  // unrecognised positional, exit 2, on stderr. That is argparse's own answer and it is the
  // cheapest proof that the action kind on this side matches the reference's.
  const r = runCli(['--update', 'x'], 80);
  assert.equal(r.status, 2);
  assert.equal(r.stdout, '');
  assert.ok(r.stderr.includes('unrecognized arguments: x'), r.stderr);
});

test('the report goes to stdout with a trailing LF and exit 0 — the per-side literal', async () => {
  const out = [];
  const err = [];
  const code = await runUpdate(
    (t) => out.push(t),
    (t) => err.push(t),
    '0.30.0',
    '/tmp/pkg',
    { fetch: stubFetch('0.30.0'), installer: installerMustNotRun, environment: ENV },
  );

  assert.equal(code, 0);
  assert.equal(
    out.join(''),
    'bantamkit-mcp 0.30.0 is installed; the package index has 0.30.0.\nup to date.\n',
  );
  assert.equal(err.join(''), '');
});

test('a refusal goes to stderr with the error prefix and exit 1 — the per-side literal', async () => {
  // Exit 1 and not 0: a `--update` that changed nothing must not look like one that did. This
  // is the J46-4 defect by name, and the no-route arm is the one it would have bitten. The
  // shape here is NOT constructed — it is `currentInstall()`'s own answer for this repo, which
  // is `checkout`, so this node also pins that the flag asks the detector rather than guessing.
  const out = [];
  const err = [];
  const code = await runUpdate(
    (t) => out.push(t),
    (t) => err.push(t),
    '0.29.0',
    '/tmp/the-running-package',
    { fetch: stubFetch('0.30.0'), installer: installerMustNotRun, environment: ENV },
  );

  assert.equal(code, 1);
  assert.equal(out.join(''), '');
  assert.equal(
    err.join(''),
    'error: bantamkit-mcp 0.29.0 is installed and the package index has 0.30.0, but this is a ' +
      'checkout install, which --update will not touch. It is running out of a source tree at ' +
      '/tmp/the-running-package that no installer recorded: update that tree where it was ' +
      'cloned, with git pull, and rebuild it — dist/ is build output, so a pull alone changes ' +
      'nothing.\n',
  );
});

test('the running package directory stands in for a shape that records no origin', async () => {
  // `checkout` carries no recorded origin, so the directory the code is executing from is what
  // the route names — which is not a guess: it is the tree the route tells the operator to
  // `git pull`, and `cli.ts` hands it in as `dirname(fileURLToPath(import.meta.url))`.
  const err = [];
  await runUpdate(() => {}, (t) => err.push(t), '0.29.0', '/somewhere/dist', {
    fetch: stubFetch('0.30.0'),
    installer: installerMustNotRun,
    environment: ENV,
  });
  assert.ok(err.join('').includes('a source tree at /somewhere/dist that no installer recorded'), err.join(''));
  assert.equal(currentInstall().source, null, 'a checkout records no origin, which is why it stands in');
});

test('AHEAD and UP_TO_DATE are the constants the reference defines, byte for byte', () => {
  // The last line of defence against a well-meaning edit on ONE side. These four strings are
  // the ones with no divergence licence at all, pinned here as text.
  assert.equal(UP_TO_DATE, 'up to date.');
  assert.equal(AHEAD, 'the installed version is ahead of the package index; there is nothing to update to.');
  assert.equal(COMPARISON, '{program} {installed} is installed; the package index has {latest}.');
  assert.equal(PROGRAM, 'bantamkit-mcp', 'the COMMAND is the same word on both sides; the package name is not');
});

// ============================================================ an npx cache, and the install it kept
//
// J51-5. `--install` on an `npx` cache leaves a kept install at `keptPrefix()` (J51-4), and that
// is what every host launches. So an operator who types `npx -y bantamkit-mcp@latest --update`
// is asking about THAT install, not about the cache they happen to be running from. These arms
// drive `runUpdate` through its `install` seam with HOME at a scratch directory, so the kept
// install found is the fixture's and never the developer's own.

/** HOME and USERPROFILE at a fresh scratch directory for `body`, then the world put back. */
async function withHome(body) {
  const home = room();
  const previous = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  process.env.HOME = home;
  process.env.USERPROFILE = home;
  try {
    assert.equal(homedir(), home, 'homedir() did not follow HOME; this test would read a real kept install');
    await body(home);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

/**
 * A kept install as `npm install --prefix` leaves one: the package's own manifest, its `cli.js`,
 * and — unless told otherwise — the `package.json` npm writes at the prefix. Every path comes from
 * `npminstall.ts`, never respelled here.
 */
function seedKept(version, { prefixManifest = true } = {}) {
  const prefix = keptPrefix();
  mkdirSync(dirname(keptCli(prefix)), { recursive: true });
  writeFileSync(keptManifest(prefix), JSON.stringify({ name: PACKAGE, version }), 'utf8');
  writeFileSync(keptCli(prefix), '', 'utf8');
  if (prefixManifest) {
    writeFileSync(join(prefix, 'package.json'), JSON.stringify({ dependencies: { [PACKAGE]: `^${version}` } }), 'utf8');
  }
  return prefix;
}

const EPHEMERAL = () => ({ shape: 'ephemeral', source: null });

/** `runUpdate` as the CLI calls it, from an `npx` cache, with both streams and the exit code. */
async function runFrom(install, running, options) {
  const out = [];
  const err = [];
  const code = await runUpdate((t) => out.push(t), (t) => err.push(t), running, '/tmp/the-npx-cache/dist', {
    install,
    environment: ENV,
    ...options,
  });
  return { code, out: out.join(''), err: err.join('') };
}

test('an npx cache with an OLDER kept install updates the kept install, by its version and its prefix', async () => {
  await withHome(async (home) => {
    const prefix = seedKept('0.32.1');
    assert.ok(prefix.startsWith(home), prefix);
    const fetch = stubFetch('0.33.0');
    const installer = recordingInstaller();

    const r = await runFrom(EPHEMERAL, '0.29.0', { fetch, installer });

    assert.deepEqual(installer.commands, [['npm', 'install', '--prefix', prefix, 'bantamkit-mcp@latest']]);
    assert.deepEqual(fetch.calls, [[INDEX_URL, DEFAULT_TIMEOUT_SECONDS]], 'still exactly one index request');
    assert.equal(r.code, 0);
    assert.equal(r.err, '');
    assert.equal(
      r.out,
      'bantamkit-mcp 0.32.1 is installed; the package index has 0.33.0.\n' +
        `updating from the package index: npm install --prefix ${shlexJoin([prefix])} bantamkit-mcp@latest\n` +
        'the command printed:\n' +
        'added 1 package in 902ms\n' +
        'updated bantamkit-mcp from 0.32.1 to 0.33.0.\n' +
        'restart the server: a running bantamkit-mcp keeps serving the code it loaded at startup, ' +
        'so bantamkit_status will report 0.32.1 until the host reconnects.\n',
    );
    assert.ok(!r.out.includes('0.29.0'), 'the running cache version leaked into a report about the kept install');
  });
});

test('an npx cache with an EQUAL kept install says up to date and runs nothing', async () => {
  await withHome(async () => {
    seedKept('0.33.0');
    // The running cache is 0.29.0, so an answer about the cache would be a refusal, not this.
    const r = await runFrom(EPHEMERAL, '0.29.0', { fetch: stubFetch('0.33.0'), installer: installerMustNotRun });
    assert.equal(r.code, 0);
    assert.equal(r.err, '');
    assert.equal(r.out, 'bantamkit-mcp 0.33.0 is installed; the package index has 0.33.0.\nup to date.\n');
  });
});

test('an npx cache with NO kept install refuses exactly as before, by the ROUTES.ephemeral sentence', async () => {
  await withHome(async (home) => {
    // A `.bantamkit` that holds a memory store and no `mcp` is not a kept install.
    mkdirSync(join(home, '.bantamkit', 'memory'), { recursive: true });
    const r = await runFrom(EPHEMERAL, '0.29.0', { fetch: stubFetch('0.30.0'), installer: installerMustNotRun });
    const route = fill(ROUTES['ephemeral'], { installed: '0.29.0', package: PACKAGE });
    assert.equal(r.code, 1);
    assert.equal(r.out, '');
    assert.equal(
      r.err,
      `error: ${fill(NO_ROUTE, { program: PROGRAM, installed: '0.29.0', latest: '0.30.0', shape: 'ephemeral', route })}\n`,
    );
    assert.ok(
      r.err.includes('the next run serves the same cached 0.29.0 unless the host command line asks for bantamkit-mcp@latest.'),
      r.err,
    );
  });
});

test('a kept install whose npm run fails is the command-failed refusal, naming the kept prefix and version', async () => {
  await withHome(async () => {
    const prefix = seedKept('0.32.1');
    const r = await runFrom(EPHEMERAL, '0.29.0', {
      fetch: stubFetch('0.33.0'),
      installer: recordingInstaller(1, 'npm ERR! code ENOTFOUND'),
    });
    assert.equal(r.code, 1);
    assert.equal(r.out, '');
    assert.equal(
      r.err,
      `error: the update command exited 1: npm install --prefix ${shlexJoin([prefix])} bantamkit-mcp@latest\n` +
        'bantamkit-mcp 0.32.1 is still installed; nothing was changed.\n' +
        'the command printed:\n' +
        'npm ERR! code ENOTFOUND\n',
    );
  });
});

test('the kept prefix is a --prefix tree by installEnvironment, and one without npm\'s package.json is never --global', async () => {
  await withHome(async () => {
    // THE SAFETY `installEnvironment` EXISTS FOR, asserted on the kept prefix rather than assumed:
    // npm writes a package.json there, so it is a prefix install and its siblings are not pruned.
    const prefix = seedKept('0.32.1');
    const env = installEnvironment(keptCli(prefix));
    assert.deepEqual(env, { root: prefix, global: false });
    assert.deepEqual(upgradeCommand(env), ['npm', 'install', '--prefix', prefix, 'bantamkit-mcp@latest']);
  });
  await withHome(async () => {
    // A kept manifest with NO package.json beside node_modules reads as the global tree, and
    // `npm install --global` would update something other than the kept install. So it is not
    // treated as one: the refusal is today's, about the running cache, and nothing runs.
    const prefix = seedKept('0.32.1', { prefixManifest: false });
    assert.equal(installEnvironment(keptCli(prefix)).global, true);
    const r = await runFrom(EPHEMERAL, '0.29.0', { fetch: stubFetch('0.33.0'), installer: installerMustNotRun });
    assert.equal(r.code, 1);
    assert.ok(r.err.startsWith('error: bantamkit-mcp 0.29.0 is installed and the package index has 0.33.0, but this is a ephemeral install'), r.err);
  });
});

test('a kept install changes nothing for any shape that is not an npx cache', async () => {
  await withHome(async () => {
    seedKept('0.32.1');
    const installer = recordingInstaller();
    const registry = await runFrom(() => ({ shape: 'registry', source: null }), '0.29.0', {
      fetch: stubFetch('0.33.0'),
      installer,
    });
    assert.equal(registry.code, 0);
    assert.deepEqual(installer.commands, [['npm', 'install', '--prefix', '/opt/x', 'bantamkit-mcp@latest']]);
    assert.ok(registry.out.startsWith('bantamkit-mcp 0.29.0 is installed; the package index has 0.33.0.\n'), registry.out);

    for (const shape of ['local-file', 'linked', 'checkout']) {
      const r = await runFrom(() => ({ shape, source: '/tmp/an-origin' }), '0.29.0', {
        fetch: stubFetch('0.33.0'),
        installer: installerMustNotRun,
      });
      assert.equal(r.code, 1, shape);
      assert.ok(
        r.err.startsWith(`error: bantamkit-mcp 0.29.0 is installed and the package index has 0.33.0, but this is a ${shape} install`),
        r.err,
      );
    }
  });
});

// ============================================================ the platform's own failures

test('fetchIndex maps a real hang to IndexTimeout and a real refusal to a plain Error', async () => {
  // LOOPBACK, AND NOTHING LEAVES THIS MACHINE. Stubbing undici here would assert this file's
  // guess about undici back at itself, and the guess is the entire contract.
  const server = net.createServer(() => {});
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  try {
    await assert.rejects(
      () => fetchIndex(`http://127.0.0.1:${port}/latest`, 0.2),
      (e) => e instanceof IndexTimeout,
      'a server that accepts and never answers is a TIMEOUT',
    );
  } finally {
    server.close();
  }

  await assert.rejects(
    () => fetchIndex('http://127.0.0.1:49999/latest', 5),
    (e) => {
      assert.ok(!(e instanceof IndexTimeout), 'a closed port is not a timeout');
      // `TypeError: fetch failed` is what Node throws and it names nothing. The CAUSE is the
      // sentence worth printing, and this asserts the operator gets that one.
      assert.ok(/ECONNREFUSED/.test(e.message), `the cause did not reach the message: ${e.message}`);
      return true;
    },
  );
});

/*
 * THE TWO LOOPBACK NODES SIT LAST ON PURPOSE, AND MOVING THEM IS A REAL BREAKAGE.
 *
 * `fetch` leaves a connection pool behind it, and undici settles that pool asynchronously —
 * a TCPWRAP can be created after the promise these two nodes await has already resolved.
 * Run them ABOVE the no-network census and the census attributes those handles to the
 * offline arms and reddens: measured here, `a network handle was opened: TCPWRAP,
 * TCPCONNECTWRAP`, on a run where nothing in `--update`'s offline half had touched a socket.
 *
 * The alternative — draining and clearing the census before the arms — was refused: a gate
 * that erases its own evidence to stay green is one nobody can trust afterwards. Ordering
 * costs nothing and keeps `assert.deepEqual(seen, [])` meaning exactly what it says.
 */
