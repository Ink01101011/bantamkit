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
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { createHook } from 'node:async_hooks';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
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
  IndexTimeout,
  NO_INSTALLED_VERSION,
  NO_OUTPUT,
  NO_RECORDED_ROUTE,
  NO_ROUTE,
  NOT_INSTALLED,
  NOT_JSON,
  NO_VERSION_FIELD,
  PACKAGE,
  PROGRAM,
  ROUTES,
  UP_TO_DATE,
  UpdateRefused,
  article,
  compareVersions,
  fetchIndex,
  fill,
  indexCommand,
  installEnvironment,
  latestFromIndexPayload,
  packageRoot,
  readInstalledVersion,
  runUpdate,
  shlexJoin,
  recordUpdate,
  update,
  upgradeCommand,
} from '../dist/selfupdate.js';
import { updateCommand, updateLine, updateStatus } from '../dist/updatecheck.js';
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

/** What `npm view bantamkit-mcp@latest --json` answers, reduced to the field that is read. */
const payload = (version) => JSON.stringify({ name: PACKAGE, version });

/** A stub index that answers one version and records the command it was handed. */
function stubFetch(version) {
  const calls = [];
  const fetch = async (command, timeout) => {
    calls.push([command, timeout]);
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

/**
 * The `installedVersion` seam answering that the tree now reports `version`. Every success arm
 * hands one in (J65-19, #128): `update` reads the manifest back before it prints `updated`, and
 * a recording installer writes nothing, so the honest default would refuse every arm.
 */
const landed = (version) => () => version;

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
/**
 * The article each shape word takes, TYPED rather than computed by `article`: "a ephemeral
 * install" shipped in every release up to 0.35.7 (#177), and an expectation built from the
 * function under test would have been green over it.
 */
const ARTICLES = { 'local-file': 'a', linked: 'a', checkout: 'a', ephemeral: 'an' };

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

/**
 * EVERY NODE IN THIS FILE RUNS WITH HOME AT A SCRATCH DIRECTORY, and it is set once here
 * rather than per node.
 *
 * `update` now writes `<homedir>/.bantamkit/update-check.json` out of the answer it already
 * fetched, so a node that calls it with a stub `fetch` and the developer's real HOME would
 * write the developer's real record — with a version number that came from a fixture. That is
 * the defect this redirection exists to make impossible, and it is file-wide rather than
 * per-node so a node added later gets it without knowing to ask. `withHome` below still saves
 * and restores around its own arms, and now restores to THIS home rather than to a real one.
 *
 * The `.bantamkit` directory is made, because the writer refuses to create one and a home
 * without it would make every write arm vacuously green; the arms that assert the refusal
 * build their own bare home.
 */
const FILE_HOME = room();
mkdirSync(join(FILE_HOME, '.bantamkit'), { recursive: true });
process.env.HOME = FILE_HOME;
process.env.USERPROFILE = FILE_HOME;
assert.equal(homedir(), FILE_HOME, 'homedir() did not follow HOME; this file would write a real record');

/** The record as it stands, parsed. */
const readRecordFile = (home = FILE_HOME) =>
  JSON.parse(readFileSync(join(home, '.bantamkit', 'update-check.json'), 'utf8'));

/** No record at all, so each arm starts from the state it means to start from. */
function clearRecord(home = FILE_HOME) {
  rmSync(join(home, '.bantamkit', 'update-check.json'), { force: true, recursive: true });
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
  assert.deepEqual(fetch.calls, [[indexCommand(ENV), DEFAULT_TIMEOUT_SECONDS]]);
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
  const report = await update('0.9.0', REGISTRY, { fetch: stubFetch('0.10.0'), installer, environment: ENV, installedVersion: landed('0.10.0') });

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
  const report = await update('0.29.0', REGISTRY, { fetch: stubFetch('0.30.0'), installer, environment: ENV, installedVersion: landed('0.30.0') });

  // `@0.30.0` AND NOT `@latest` (J65-19, #128): the version this flag compared is the version
  // npm is told to install, so a mirror behind the index that answered, or a dist-tag moved
  // between the two calls, cannot make line 5 of the report a lie.
  assert.deepEqual(installer.commands, [['npm', 'install', '--prefix', '/opt/x', 'bantamkit-mcp@0.30.0']]);
  assert.equal(
    report,
    'bantamkit-mcp 0.29.0 is installed; the package index has 0.30.0.\n' +
      'updating from the package index: npm install --prefix /opt/x bantamkit-mcp@0.30.0\n' +
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
    installedVersion: landed('0.30.0'),
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
    'the update command exited 7: npm install --prefix /opt/x bantamkit-mcp@0.30.0\n' +
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
        'bantamkit-mcp 0.29.0 is installed and the package index has 0.30.0, but this is ' +
          `${ARTICLES[shape]} ${shape} install, which --update will not touch. `,
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
  assert.deepEqual(env, { root: project, global: false, exact: false });
  assert.deepEqual(upgradeCommand(env, '0.30.0'), ['npm', 'install', '--prefix', project, 'bantamkit-mcp@0.30.0']);
  assert.deepEqual(indexCommand(env), ['npm', 'view', '--prefix', project, 'bantamkit-mcp@latest', '--json', '--fetch-retries=0']);
});

test('an EXACT pin in the prefix manifest is kept exact: --save-exact, and only then', () => {
  // npm rewrites `"0.35.7"` to `"^0.35.7"` on `npm install <pkg>@<v>` unless told otherwise
  // (observed in #128). The record of what the operator pinned is theirs, not npm's.
  const root = room();
  const exact = join(root, 'exact');
  const caret = join(root, 'caret');
  for (const [project, spec] of [[exact, '0.29.0'], [caret, '^0.29.0']]) {
    mkdirSync(join(project, 'node_modules', PACKAGE, 'dist'), { recursive: true });
    writeFileSync(join(project, 'package.json'), JSON.stringify({ dependencies: { [PACKAGE]: spec } }), 'utf8');
  }
  const pinned = installEnvironment(join(exact, 'node_modules', PACKAGE, 'dist', 'selfupdate.js'));
  assert.deepEqual(pinned, { root: exact, global: false, exact: true });
  assert.deepEqual(upgradeCommand(pinned, '0.30.0'), ['npm', 'install', '--prefix', exact, '--save-exact', 'bantamkit-mcp@0.30.0']);
  const ranged = installEnvironment(join(caret, 'node_modules', PACKAGE, 'dist', 'selfupdate.js'));
  assert.deepEqual(ranged, { root: caret, global: false, exact: false });
  assert.deepEqual(upgradeCommand(ranged, '0.30.0'), ['npm', 'install', '--prefix', caret, 'bantamkit-mcp@0.30.0']);
  // The view command never carries it: `--save-exact` is about what npm writes, and a view writes nothing.
  assert.ok(!indexCommand(pinned).includes('--save-exact'));
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
  assert.deepEqual(env, { root: lib, global: true, exact: false });
  assert.deepEqual(upgradeCommand(env, '0.30.0'), ['npm', 'install', '--global', 'bantamkit-mcp@0.30.0']);
  assert.deepEqual(indexCommand(env), ['npm', 'view', '--global', 'bantamkit-mcp@latest', '--json', '--fetch-retries=0']);
});

test('the no-node_modules arm of installEnvironment cannot be reached from a registry install', () => {
  // It is total rather than throwing, and the answer it gives is the global command, which
  // needs no root. That arm is UNREACHABLE from the only shape that runs an installer, and the
  // pairing is asserted rather than left as a comment: `deriveInstall` answers `registry` only
  // from inside a `node_modules`, and this repo's own running copy is a `checkout`, which is a
  // shape `--update` refuses before it ever builds a command.
  const root = room();
  mkdirSync(join(root, 'tree', 'dist'), { recursive: true });
  assert.deepEqual(installEnvironment(join(root, 'tree', 'dist', 'selfupdate.js')), { root: '', global: true, exact: false });
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

    const r = await runFrom(EPHEMERAL, '0.29.0', { fetch, installer, installedVersion: landed('0.33.0') });

    assert.deepEqual(installer.commands, [['npm', 'install', '--prefix', prefix, 'bantamkit-mcp@0.33.0']]);
    assert.deepEqual(
      fetch.calls,
      [[['npm', 'view', '--prefix', prefix, 'bantamkit-mcp@latest', '--json', '--fetch-retries=0'], DEFAULT_TIMEOUT_SECONDS]],
      'still exactly one index request, and it is asked of the KEPT prefix, where the install will point',
    );
    assert.equal(r.code, 0);
    assert.equal(r.err, '');
    assert.equal(
      r.out,
      'bantamkit-mcp 0.32.1 is installed; the package index has 0.33.0.\n' +
        `updating from the package index: npm install --prefix ${shlexJoin([prefix])} bantamkit-mcp@0.33.0\n` +
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
      `error: ${fill(NO_ROUTE, { program: PROGRAM, installed: '0.29.0', latest: '0.30.0', article: 'an', shape: 'ephemeral', route })}\n`,
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
      `error: the update command exited 1: npm install --prefix ${shlexJoin([prefix])} bantamkit-mcp@0.33.0\n` +
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
    assert.deepEqual(env, { root: prefix, global: false, exact: false });
    assert.deepEqual(upgradeCommand(env, '0.33.0'), ['npm', 'install', '--prefix', prefix, 'bantamkit-mcp@0.33.0']);
  });
  await withHome(async () => {
    // A kept manifest with NO package.json beside node_modules reads as the global tree, and
    // `npm install --global` would update something other than the kept install. So it is not
    // treated as one: the refusal is today's, about the running cache, and nothing runs.
    const prefix = seedKept('0.32.1', { prefixManifest: false });
    assert.equal(installEnvironment(keptCli(prefix)).global, true);
    const r = await runFrom(EPHEMERAL, '0.29.0', { fetch: stubFetch('0.33.0'), installer: installerMustNotRun });
    assert.equal(r.code, 1);
    // "an ephemeral", not "a ephemeral" — the article follows the shape word (#177).
    assert.ok(r.err.startsWith('error: bantamkit-mcp 0.29.0 is installed and the package index has 0.33.0, but this is an ephemeral install'), r.err);
  });
});

test('a kept install changes nothing for any shape that is not an npx cache', async () => {
  await withHome(async () => {
    seedKept('0.32.1');
    const installer = recordingInstaller();
    const registry = await runFrom(() => ({ shape: 'registry', source: null }), '0.29.0', {
      fetch: stubFetch('0.33.0'),
      installer,
      installedVersion: landed('0.33.0'),
    });
    assert.equal(registry.code, 0);
    assert.deepEqual(installer.commands, [['npm', 'install', '--prefix', '/opt/x', 'bantamkit-mcp@0.33.0']]);
    assert.ok(registry.out.startsWith('bantamkit-mcp 0.29.0 is installed; the package index has 0.33.0.\n'), registry.out);

    for (const shape of ['local-file', 'linked', 'checkout']) {
      const r = await runFrom(() => ({ shape, source: '/tmp/an-origin' }), '0.29.0', {
        fetch: stubFetch('0.33.0'),
        installer: installerMustNotRun,
      });
      assert.equal(r.code, 1, shape);
      assert.ok(
        r.err.startsWith(`error: bantamkit-mcp 0.29.0 is installed and the package index has 0.33.0, but this is ${ARTICLES[shape]} ${shape} install`),
        r.err,
      );
    }
  });
});

// ============================================================ the platform's own failures

// ============================================================ the install, read back (J65-19, #128)

test('an installer that exits 0 and leaves the old version behind is a refusal, not a success', async () => {
  // MEASURED 2026-10-13 (#128): with the index stubbed to 9.9.9 and an `npm` on PATH that
  // recorded its argv and changed nothing, 0.35.7 printed `updated bantamkit-mcp from 0.35.7 to
  // 9.9.9.` and exited 0 with 0.35.7 still on disk. The success line is read off the tree now.
  const installer = recordingInstaller(0, 'changed 1 package in 1s');
  const message = await refusal(() =>
    update('0.29.0', REGISTRY, { fetch: stubFetch('0.30.0'), installer, environment: ENV, installedVersion: landed('0.29.0') }),
  );
  assert.equal(installer.commands.length, 1, 'the installer ran once; the refusal is about what it left');
  assert.equal(
    message,
    'the update command exited 0 but did not install 0.30.0: npm install --prefix /opt/x bantamkit-mcp@0.30.0\n' +
      'bantamkit-mcp now reports 0.29.0, not 0.30.0; the tree the command names did not take the update.\n' +
      'the command printed:\n' +
      'changed 1 package in 1s',
  );
});

test('an installer that exits 0 and leaves no readable manifest is the same refusal, naming the absence', async () => {
  const message = await refusal(() =>
    update('0.29.0', REGISTRY, { fetch: stubFetch('0.30.0'), installer: recordingInstaller(0, '   '), environment: ENV, installedVersion: landed(null) }),
  );
  assert.ok(message.includes(`bantamkit-mcp now reports ${NO_INSTALLED_VERSION}, not 0.30.0;`), message);
  assert.ok(message.endsWith(`the command printed:\n${NO_OUTPUT}`), message);
  // The default seam on a root with no node_modules is that absence, and on one with a manifest
  // it is the manifest's version — read off the disk, which is what makes the line above true.
  assert.equal(readInstalledVersion(ENV), null);
  const root = room();
  mkdirSync(join(root, 'node_modules', PACKAGE), { recursive: true });
  writeFileSync(join(root, 'node_modules', PACKAGE, 'package.json'), JSON.stringify({ name: PACKAGE, version: '0.30.0' }), 'utf8');
  assert.equal(readInstalledVersion({ root, global: false }), '0.30.0');
  const report = await update('0.29.0', REGISTRY, { fetch: stubFetch('0.30.0'), installer: recordingInstaller(), environment: { root, global: false } });
  assert.ok(report.includes('updated bantamkit-mcp from 0.29.0 to 0.30.0.'), report);
});

test('the manifest is compared by the version rule, so 0.30 on disk is the 0.30.0 that was compared', async () => {
  const report = await update('0.29.0', REGISTRY, { fetch: stubFetch('0.30.0'), installer: recordingInstaller(), environment: ENV, installedVersion: landed('0.30') });
  assert.ok(report.includes('updated bantamkit-mcp from 0.29.0 to 0.30.0.'), report);
});

// ============================================================ the article, and the tree the route names (#177)

test('the article follows the shape word: an ephemeral install, a checkout install, an unknown vowel-initial one', async () => {
  assert.equal(article('ephemeral'), 'an');
  assert.equal(article('checkout'), 'a');
  assert.equal(article('Orphan'), 'an', 'case does not change the sound');
  const message = await refusal(() =>
    update('0.29.0', { shape: 'ephemeral', source: '' }, { fetch: stubFetch('0.30.0'), installer: installerMustNotRun, environment: ENV }),
  );
  assert.ok(message.includes(' but this is an ephemeral install, '), message);
  assert.ok(!message.includes(' a ephemeral '), message);
  const unknown = await refusal(() =>
    update('0.29.0', { shape: 'orphan', source: '' }, { fetch: stubFetch('0.30.0'), installer: installerMustNotRun, environment: ENV }),
  );
  assert.ok(unknown.includes(' but this is an orphan install, '), unknown);
  assert.ok(unknown.endsWith(fill(NO_RECORDED_ROUTE, { article: 'an', shape: 'orphan' })), unknown);
  assert.equal(NO_RECORDED_ROUTE, 'There is no recorded update route for {article} {shape} install, so --update will not guess one.');
});

test('a checkout names the package root above dist/, which is the tree the route says to pull', async () => {
  // `cli.ts` hands in `dirname(import.meta.url)`, which is `dist/`; the manifest this build
  // reads its version from sits one level up, and THAT directory is the source tree. A
  // directory with no manifest above it stands in as itself, so nothing is invented.
  const root = room();
  mkdirSync(join(root, 'tree', 'dist'), { recursive: true });
  writeFileSync(join(root, 'tree', 'package.json'), JSON.stringify({ name: PACKAGE, version: '0.29.0' }), 'utf8');
  assert.equal(packageRoot(join(root, 'tree', 'dist')), join(root, 'tree'));
  assert.equal(packageRoot('/no/such/dist'), '/no/such/dist');
  const err = [];
  await runUpdate(() => {}, (t) => err.push(t), '0.29.0', join(root, 'tree', 'dist'), {
    install: () => ({ shape: 'checkout', source: null }),
    fetch: stubFetch('0.30.0'),
    installer: installerMustNotRun,
    environment: ENV,
  });
  assert.ok(err.join('').includes(`a source tree at ${join(root, 'tree')} that no installer recorded`), err.join(''));
  assert.ok(!err.join('').includes(`${join(root, 'tree', 'dist')} that`), 'the route named dist/ as the tree');
});

// ============================================================ the platform's own failures

/** A command that is a Node one-liner, so these arms run the same on every platform. */
const nodeCommand = (script) => [process.execPath, '-e', script];

test('fetchIndex maps a real hang to IndexTimeout, a real failure to its summary, and no program to its spawn error', async () => {
  // THE CONTRACT IS WHAT `spawnSync` DOES, measured rather than stubbed: a child that never
  // exits is killed at the deadline and comes back as `ETIMEDOUT`, which is the one fact that
  // becomes the timeout refusal — every other failure is a plain `Error` carrying the sentence
  // the operator should read, in the order `fetchIndex`'s docstring gives.
  await assert.rejects(
    () => fetchIndex(nodeCommand('setInterval(() => {}, 1000)'), 0.3),
    (e) => e instanceof IndexTimeout,
    'a command that never answers is a TIMEOUT',
  );
  await assert.rejects(
    () => fetchIndex(nodeCommand('process.stdout.write(JSON.stringify({error:{code:"ECONNREFUSED",summary:"request to http://127.0.0.1:1/bantamkit-mcp failed, reason: connect ECONNREFUSED 127.0.0.1:1"}})); process.exit(1)'), 5),
    (e) => {
      assert.ok(!(e instanceof IndexTimeout), 'a refused registry is not a timeout');
      assert.equal(e.message, 'request to http://127.0.0.1:1/bantamkit-mcp failed, reason: connect ECONNREFUSED 127.0.0.1:1');
      return true;
    },
  );
  await assert.rejects(
    () => fetchIndex(nodeCommand('process.stdout.write(JSON.stringify({error:{code:"E404"}})); process.exit(1)'), 5),
    (e) => e.message === 'E404',
  );
  await assert.rejects(
    () => fetchIndex(nodeCommand('process.stderr.write("\\nnpm error something went wrong\\n"); process.exit(1)'), 5),
    (e) => e.message === 'npm error something went wrong',
  );
  await assert.rejects(() => fetchIndex(nodeCommand('process.exit(3)'), 5), (e) => e.message === 'exit 3');
  await assert.rejects(
    () => fetchIndex(['/no/such/program/anywhere'], 5),
    (e) => !(e instanceof IndexTimeout) && /ENOENT/.test(e.message),
  );
  // And the body of a command that answers is handed back whole, for the real parser to judge.
  assert.equal(await fetchIndex(nodeCommand('process.stdout.write("{\\"version\\":\\"0.30.0\\"}")'), 5), '{"version":"0.30.0"}');
});

test('the real npm, asked through indexCommand, honours npm_config_registry — measured against a loopback registry (#135)', async () => {
  // THE MEASUREMENT #135 ASKED FOR. The 0.35.7 `fetch` asked `registry.npmjs.org` whatever npm
  // was configured for; this spawns the actual `npm` on PATH with `npm_config_registry` pointed
  // at a server THIS test runs on 127.0.0.1, and asserts that the registry it asked is that
  // one and that the document it answered is the one `latestFromIndexPayload` reads. Nothing
  // leaves this machine. A machine with no `npm` on PATH says so and measures nothing.
  //
  // THE REGISTRY IS A CHILD PROCESS, NOT AN IN-PROCESS SERVER: `fetchIndex` is `spawnSync`,
  // which blocks this event loop for as long as npm runs, so a server on this loop could never
  // answer it — measured here as `spawnSync npm ETIMEDOUT` after 30 s on the first version of
  // this node, with the registry sitting one `await` away the whole time.
  const probe = spawnSync('npm', ['--version'], { encoding: 'utf8', shell: process.platform === 'win32' });
  if (probe.error || probe.status !== 0) {
    console.log(`# npm is not on PATH here (${probe.error?.code ?? `exit ${probe.status}`}); the loopback measurement did not run`);
    return;
  }
  const root = room();
  const askedLog = join(root, 'asked.log');
  const portFile = join(root, 'port');
  writeFileSync(
    join(root, 'registry.mjs'),
    [
      "import http from 'node:http';",
      "import fs from 'node:fs';",
      `const pkg = ${JSON.stringify(PACKAGE)};`,
      "const doc = { name: pkg, 'dist-tags': { latest: '9.9.9' }, versions: { '9.9.9': { name: pkg, version: '9.9.9', dist: { tarball: 'http://127.0.0.1:1/none.tgz' } } } };",
      'const server = http.createServer((req, res) => {',
      `  fs.appendFileSync(${JSON.stringify(askedLog)}, req.url + '\\n');`,
      "  if (req.url.startsWith('/' + pkg)) { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(doc)); return; }",
      "  res.statusCode = 404; res.end('{\"error\":\"not found\"}');",
      '});',
      `server.listen(0, '127.0.0.1', () => fs.writeFileSync(${JSON.stringify(portFile)}, String(server.address().port)));`,
      '',
    ].join('\n'),
    'utf8',
  );
  const registry = spawn(process.execPath, [join(root, 'registry.mjs')], { stdio: 'ignore' });
  try {
    for (let waited = 0; !existsSync(portFile) && waited < 100; waited += 1) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.ok(existsSync(portFile), 'the loopback registry never came up');
    const port = readFileSync(portFile, 'utf8').trim();
    writeFileSync(join(root, 'package.json'), '{"name":"host"}', 'utf8');
    const previous = { registry: process.env.npm_config_registry, cache: process.env.npm_config_cache };
    process.env.npm_config_registry = `http://127.0.0.1:${port}/`;
    process.env.npm_config_cache = join(root, 'npm-cache');
    try {
      const body = await fetchIndex(indexCommand({ root, global: false }), 30);
      assert.equal(latestFromIndexPayload(body), '9.9.9');
    } finally {
      for (const [key, value] of [['npm_config_registry', previous.registry], ['npm_config_cache', previous.cache]]) {
        if (value === undefined) delete process.env[key];
        else process.env[key] = value;
      }
    }
    const asked = readFileSync(askedLog, 'utf8').split('\n').filter((l) => l !== '');
    assert.ok(asked.some((u) => u.startsWith(`/${PACKAGE}`)), `the loopback registry was never asked for the package: ${asked.join(', ')}`);
  } finally {
    registry.kill();
  }
});

/*
 * THE LOOPBACK NODE SITS LAST ON PURPOSE, AND MOVING IT IS A REAL BREAKAGE.
 *
 * It opens a real server, and the no-network census above attributes any handle it can see
 * to the offline arms: measured in the `fetch` era, `a network handle was opened: TCPWRAP,
 * TCPCONNECTWRAP`, on a run where nothing in `--update`'s offline half had touched a socket.
 *
 * The alternative — draining and clearing the census before the arms — was refused: a gate
 * that erases its own evidence to stay green is one nobody can trust afterwards. Ordering
 * costs nothing and keeps `assert.deepEqual(seen, [])` meaning exactly what it says.
 */

// ============================================================ the record this flag leaves behind
//
// `--update` is the only thing in this toolbox that may reach the network, and it is therefore
// the only thing that can know what the registry holds. `bantamkit_status` prints a line from a
// RECORD instead of asking anybody, so the number in that record has to come from here. Every
// node below drives the flag through its existing `fetch` seam and then reads the file: no
// second network call exists to be tested, which is the property. The port of
// `runtime-py/tests/test_selfupdate.py`'s section of the same name.

test('a successful fetch writes the record the status line reads, from ONE fetch', async () => {
  clearRecord();
  const fetch = stubFetch('0.31.0');

  await update('0.30.0', REGISTRY, { fetch, installer: recordingInstaller(), environment: ENV, installedVersion: landed('0.31.0') });

  assert.equal(fetch.calls.length, 1, JSON.stringify(fetch.calls));
  // AMENDED 2026-09-21 (job62, J62-13): the entry carries a third field now — its own
  // `checked_at`, the day npm answered — so this compares field by field. The stamp's SHAPE
  // is the assertable part; its value is a clock.
  const written = readRecordFile().npm;
  assert.equal(written.package, PACKAGE);
  assert.equal(written.latest, '0.31.0');
  assert.match(written.checked_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
  assert.deepEqual(Object.keys(written).sort(), ['checked_at', 'latest', 'package']);
});

test('the record written here is the one updatecheck reads back', async () => {
  clearRecord();
  await update('0.30.0', REGISTRY, { fetch: stubFetch('0.31.0'), installer: recordingInstaller(), environment: ENV, installedVersion: landed('0.31.0') });

  assert.equal(
    updateLine('0.30.0'),
    'update: bantamkit-mcp 0.30.0 is running; the package index has 0.31.0 — run ' +
      `\`${updateCommand()}\`, then reconnect the host.`, // job66/#171
  );
  assert.equal(updateStatus('0.31.0').state, 'current');
});

test("the other runtime's key is left exactly as it was found", async () => {
  writeFileSync(
    join(FILE_HOME, '.bantamkit', 'update-check.json'),
    JSON.stringify({
      checked_at: '2020-01-01T00:00:00Z',
      npm: { package: PACKAGE, latest: '0.29.0' },
      pypi: { distribution: 'bantamkit', latest: '0.29.0' },
      'a-key-nobody-here-owns': ['kept'],
    }),
    'utf8',
  );

  await update('0.30.0', REGISTRY, { fetch: stubFetch('0.31.0'), installer: recordingInstaller(), environment: ENV, installedVersion: landed('0.31.0') });

  const written = readRecordFile();
  // npm and PyPI are two registries that can disagree at one version number — job56 shipped a
  // day where they did — so a Node `--update` that helpfully filled in `pypi` would be
  // publishing a number it never asked for.
  assert.deepEqual(written.pypi, { distribution: 'bantamkit', latest: '0.29.0' });
  assert.deepEqual(written['a-key-nobody-here-owns'], ['kept']);
  assert.equal(written.npm.latest, '0.31.0');
  // AMENDED 2026-09-21 (job62, J62-13), AND THIS ASSERTION IS INVERTED. It used to be
  // `assert.notEqual(..., '2020-01-01T00:00:00Z')` — this writer moved the record's stamp.
  // That stamp is the fallback dating every entry WITHOUT one of its own, so moving it
  // re-dated the untouched `pypi` number by a check that never asked PyPI: the reference
  // reading this very record would then have said `is current as of <today>` about a number
  // from 2020. "Left exactly as found" was true of the entry's bytes and false of the fact
  // about it. The record's stamp stays put now, and `--update` stamps its own entry.
  assert.equal(written.checked_at, '2020-01-01T00:00:00Z');
  assert.equal(
    updateStatus('0.29.0', 'pypi').line,
    'update: bantamkit-mcp 0.29.0 is current as of 2020-01-01.',
  );
});

test('a machine with no .bantamkit directory is not given one', async () => {
  // `<homedir>/.bantamkit` is made by an install. A flag that created it would also be a flag
  // that could create one in the wrong place, and a `.bantamkit` under a cwd is a MEMORY STORE
  // — the J54-3 defect class. The cwd is checked too, for the same reason.
  const bare = room();
  const workdir = room();
  const previousCwd = process.cwd();
  const previousHome = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  process.env.HOME = bare;
  process.env.USERPROFILE = bare;
  process.chdir(workdir);
  try {
    const report = await update('0.30.0', REGISTRY, {
      fetch: stubFetch('0.31.0'),
      installer: recordingInstaller(),
      environment: ENV,
      installedVersion: landed('0.31.0'),
    });
    assert.ok(report.startsWith('bantamkit-mcp 0.30.0 is installed; the package index has 0.31.0.'), report);
    assert.ok(report.includes('updated bantamkit-mcp from 0.30.0 to 0.31.0.'), report);
    assert.deepEqual(readdirSync(bare), []);
    assert.deepEqual(readdirSync(workdir), []);
  } finally {
    process.chdir(previousCwd);
    process.env.HOME = previousHome.HOME;
    process.env.USERPROFILE = previousHome.USERPROFILE;
  }
});

test('a write that cannot land does not turn a good update into a failure', async () => {
  // The install already happened. A DIRECTORY is put where the record goes, which is a shape
  // `renameSync` refuses on every platform.
  clearRecord();
  mkdirSync(join(FILE_HOME, '.bantamkit', 'update-check.json'), { recursive: true });
  try {
    const report = await update('0.30.0', REGISTRY, {
      fetch: stubFetch('0.31.0'),
      installer: recordingInstaller(),
      environment: ENV,
      installedVersion: landed('0.31.0'),
    });
    assert.ok(report.includes('updated bantamkit-mcp from 0.30.0 to 0.31.0.'), report);
    assert.equal(recordUpdate('0.31.0'), false);
    assert.equal(updateLine('0.30.0'), 'update: the update record could not be read.');
  } finally {
    clearRecord();
  }
});

test('a refused shape still records what the index said', async () => {
  // The fetch succeeded, so the number is true — whatever the flag then decides to do. A
  // checkout has no registry route and `--update` refuses it, but the operator is owed the
  // number: `bantamkit_status` can now tell them they are five releases behind.
  clearRecord();
  await assert.rejects(
    () =>
      update('0.30.0', { shape: 'checkout', source: '/some/checkout' }, {
        fetch: stubFetch('0.31.0'),
        installer: installerMustNotRun,
        environment: ENV,
      }),
    UpdateRefused,
  );

  assert.equal(readRecordFile().npm.latest, '0.31.0');
});

test('a fetch that never answered writes no record, and does not clobber a stale one', async () => {
  writeFileSync(
    join(FILE_HOME, '.bantamkit', 'update-check.json'),
    JSON.stringify({ checked_at: '2020-01-01T00:00:00Z', npm: { package: PACKAGE, latest: '0.29.0' } }),
    'utf8',
  );

  await assert.rejects(
    () =>
      update('0.30.0', REGISTRY, {
        fetch: throwingFetch(new IndexTimeout('timed out')),
        installer: installerMustNotRun,
        environment: ENV,
      }),
    UpdateRefused,
  );

  assert.deepEqual(readRecordFile(), {
    checked_at: '2020-01-01T00:00:00Z',
    npm: { package: PACKAGE, latest: '0.29.0' },
  });
});

test('an unreadable record is replaced rather than merged into', async () => {
  // There is nothing in it to preserve, and leaving it would leave the line unreadable.
  writeFileSync(join(FILE_HOME, '.bantamkit', 'update-check.json'), '<html>captive portal</html>', 'utf8');

  await update('0.30.0', REGISTRY, { fetch: stubFetch('0.31.0'), installer: recordingInstaller(), environment: ENV, installedVersion: landed('0.31.0') });

  assert.equal(readRecordFile().npm.latest, '0.31.0');
  assert.equal(updateStatus('0.31.0').state, 'current');
});

test('the record is these bytes', () => {
  // The two runtimes write the SAME file, one key each, and a reader on either side has to be
  // able to read what the other wrote. That makes the serialization a contract and not an
  // implementation detail — the reference pins the identical shape for its own key.
  //
  // AMENDED 2026-09-21 (job62, J62-13). The stamp moved INSIDE the entry and there is no
  // record-level one: `--update` holds one registry's answer by construction, and the
  // record's `checked_at` means "a writer refreshed the whole record". A record this writer
  // creates therefore cannot say when it was refreshed as a whole — which is exactly what
  // makes the hook's 24 h TTL treat it as due and send the probe that fills the other half.
  clearRecord();
  assert.equal(recordUpdate('0.31.0', '2026-09-19T21:04:11Z'), true);

  assert.equal(
    readFileSync(join(FILE_HOME, '.bantamkit', 'update-check.json'), 'utf8'),
    '{\n' +
      '  "npm": {\n' +
      '    "package": "bantamkit-mcp",\n' +
      '    "latest": "0.31.0",\n' +
      '    "checked_at": "2026-09-19T21:04:11Z"\n' +
      '  }\n' +
      '}\n',
  );
});

test('the stamp is UTC and shaped the way the reader slices it', () => {
  // `YYYY-MM-DDTHH:MM:SSZ` — not `.000Z`, which is what `toISOString()` alone would give, and
  // not `+00:00`, which is what the reference's `isoformat()` would.
  // AMENDED 2026-09-21 (job62, J62-13): read off the ENTRY, which is where this writer puts
  // its stamp now. `recordUpdate` writes no record-level `checked_at` at all.
  clearRecord();
  assert.equal(recordUpdate('0.31.0'), true);
  const record = readRecordFile();
  assert.equal(Object.prototype.hasOwnProperty.call(record, 'checked_at'), false);
  const written = record.npm.checked_at;
  assert.match(written, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/, written);
  assert.equal(updateStatus('0.31.0').state, 'current');
});

test('the writer leaves no temporary file behind', () => {
  // Temp-file-and-rename, and the temp file is gone either way. A reader that saw half a record
  // would print `could not be read` over a good update; a writer that littered would fill
  // `.bantamkit` with them.
  clearRecord();
  for (let i = 0; i < 3; i += 1) assert.equal(recordUpdate('0.31.0'), true);
  assert.deepEqual(readdirSync(join(FILE_HOME, '.bantamkit')).sort(), ['update-check.json']);
});
