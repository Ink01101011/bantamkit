/**
 * `--install <host>`: the file it writes, and everything it refuses to destroy.
 *
 * The Node half of `runtime-py/tests/test_hostinstall.py`, test for test. Every case points
 * `HOME`/`USERPROFILE` at a scratch directory before the module resolves a path, because this
 * module writes to real configuration files and a test that reached one would edit the
 * machine it was measuring.
 *
 * `os.homedir()` reads the environment on every call on every platform this ships to, so the
 * redirection is total — but it is asserted below rather than assumed, because a test whose
 * isolation is a belief is a test that eventually writes to somebody's Cursor config.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, isAbsolute, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const CMD = '/opt/bantamkit/bin/bantamkit-mcp';

/** Run `body` with HOME pointed at a fresh scratch directory, then put the world back. */
async function withHome(body) {
  const root = mkdtempSync(join(tmpdir(), 'bk-hostinstall-'));
  const previous = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  process.env.HOME = root;
  process.env.USERPROFILE = root;
  try {
    // The isolation, asserted rather than believed.
    assert.equal(homedir(), root, 'homedir() did not follow HOME; this test would edit a real config');
    const hostinstall = await import('../dist/hostinstall.js');
    await body(hostinstall, root);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    rmSync(root, { recursive: true, force: true });
  }
}

const readJson = (path) => JSON.parse(readFileSync(path, 'utf8'));
const backupsIn = (path) => readdirSync(dirname(path)).filter((n) => n.includes('.backup-'));

test('the key is servers for VS Code and mcpServers for the other three', async () => {
  // A correct server under the wrong key is not an error anywhere: the host reads the key it
  // knows, finds nothing, and says nothing. This is the whole reason the command exists.
  const { configKey } = await import('../dist/hostinstall.js');
  assert.equal(configKey('copilot'), 'servers');
  assert.equal(configKey('cursor'), 'mcpServers');
  assert.equal(configKey('claude-desktop'), 'mcpServers');
});

test('VS Code gets a type field and the others do not', async () => {
  const { entryFor } = await import('../dist/hostinstall.js');
  assert.deepEqual(entryFor('copilot', CMD, []), { type: 'stdio', command: CMD, args: [] });
  assert.deepEqual(entryFor('cursor', CMD, ['-y', 'x']), { command: CMD, args: ['-y', 'x'] });
});

test('a first install creates the file and the directory', async () => {
  await withHome(async (h) => {
    const report = h.install('cursor', CMD, []);
    const path = h.hostConfigPath('cursor');
    assert.deepEqual(readJson(path), { mcpServers: { bantamkit: { command: CMD, args: [] } } });
    assert.match(report, /installed bantamkit into cursor/);
    assert.ok(!report.includes('backup'));
    assert.deepEqual(backupsIn(path), []);
  });
});

test('a second identical install changes nothing and says so', async () => {
  await withHome(async (h) => {
    h.install('cursor', CMD, []);
    const path = h.hostConfigPath('cursor');
    const before = readFileSync(path);
    const report = h.install('cursor', CMD, []);
    assert.ok(report.startsWith('bantamkit is already installed in cursor and matches'));
    assert.deepEqual(readFileSync(path), before);
    assert.deepEqual(backupsIn(path), []);
  });
});

test("someone else's servers and unrelated keys survive", async () => {
  await withHome(async (h) => {
    const path = h.hostConfigPath('cursor');
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(
      path,
      JSON.stringify({
        mcpServers: { 'someone-else': { command: 'keep-me', args: ['--important'] } },
        unrelatedTopLevelKey: { keep: 'this too' },
      }),
    );
    h.install('cursor', CMD, []);
    const written = readJson(path);
    assert.deepEqual(written.mcpServers['someone-else'], { command: 'keep-me', args: ['--important'] });
    assert.deepEqual(written.unrelatedTopLevelKey, { keep: 'this too' });
    assert.equal(written.mcpServers.bantamkit.command, CMD);
  });
});

test('a different existing entry is refused and the file is untouched', async () => {
  await withHome(async (h) => {
    h.install('cursor', 'OLD', []);
    const path = h.hostConfigPath('cursor');
    const before = readFileSync(path);
    assert.throws(
      () => h.install('cursor', CMD, []),
      (e) =>
        e instanceof h.InstallError &&
        e.message.includes('"command": "OLD"') &&
        e.message.includes(CMD) &&
        e.message.includes('re-run with --force to replace it'),
    );
    assert.deepEqual(readFileSync(path), before);
  });
});

test('force replaces the entry and leaves a dated backup of what was there', async () => {
  await withHome(async (h) => {
    h.install('cursor', 'OLD', []);
    const path = h.hostConfigPath('cursor');
    const report = h.install('cursor', CMD, [], true);
    assert.equal(readJson(path).mcpServers.bantamkit.command, CMD);
    const backups = backupsIn(path);
    assert.equal(backups.length, 1);
    assert.match(report, /  backup : /);
    // The backup is the file as it WAS, not a copy of what replaced it.
    assert.deepEqual(readJson(join(dirname(path), backups[0])).mcpServers.bantamkit, {
      command: 'OLD',
      args: [],
    });
  });
});

test('a file that is not JSON is refused rather than replaced', async () => {
  // Somebody's configuration, mid-edit. Overwriting destroys the only copy.
  await withHome(async (h) => {
    const path = h.hostConfigPath('cursor');
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, '{ "mcpServers": { broken\n');
    const before = readFileSync(path);
    assert.throws(
      () => h.install('cursor', CMD, []),
      (e) => e.message.includes('is not valid JSON, so this refuses to touch it'),
    );
    assert.deepEqual(readFileSync(path), before);
  });
});

test('a JSON file that is not an object is refused', async () => {
  await withHome(async (h) => {
    const path = h.hostConfigPath('cursor');
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, '[1, 2, 3]');
    assert.throws(
      () => h.install('cursor', CMD, []),
      (e) => e.message.includes('not an object; refusing to touch it'),
    );
  });
});

test('a servers block that is not an object is refused', async () => {
  await withHome(async (h) => {
    const path = h.hostConfigPath('cursor');
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify({ mcpServers: ['not', 'a', 'dict'] }));
    assert.throws(() => h.install('cursor', CMD, []), (e) => e instanceof h.InstallError);
  });
});

test('an empty file is an empty config, not a parse error', async () => {
  // A zero-byte file is what a host leaves when it has been started and never configured.
  await withHome(async (h) => {
    const path = h.hostConfigPath('cursor');
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, '');
    h.install('cursor', CMD, []);
    assert.equal(readJson(path).mcpServers.bantamkit.command, CMD);
  });
});

test('claude is not written by us and has no path', async () => {
  // `~/.claude.json` is the host's file, carrying state that is not MCP configuration.
  await withHome(async (h) => {
    assert.throws(() => h.hostConfigPath('claude'), (e) => e instanceof h.InstallError);
  });
});

test('the written JSON escapes non-ASCII so both runtimes write the same bytes', async () => {
  // `dumpJson` reproduces `json.dumps`'s `ensure_ascii`, which the reference leaves at its
  // default. A home directory with a non-ASCII name would otherwise split the two runtimes.
  await withHome(async (h) => {
    h.install('cursor', '/opt/ก/bantamkit-mcp', []);
    const raw = readFileSync(h.hostConfigPath('cursor'), 'utf8');
    assert.ok(raw.includes('\\u0e01'));
    assert.ok(!raw.includes('ก'));
  });
});

// --- J51-4: the recorded command is an absolute node and an absolute cli.js --------------------
//
// CHANGED EXPECTATION. Until job51 this block pinned `thisCommand()` to `npx -y bantamkit-mcp`.
// Measured on npm 11.6.2 with a WARM cache and the network cut, that command hangs silently past
// 45 s with zero bytes on stdout, pinned or not; a kept install launched as
// `<abs node> <abs dist/cli.js>` answered in 0.11 s under a GUI-shaped PATH. The user ruled for
// the kept install, so the pin moved with the ruling rather than being deleted.

const VERSION = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')).version;
const OWN_CLI = fileURLToPath(new URL('../dist/cli.js', import.meta.url));

/** The kept prefix, spelled as a LITERAL here so the exported one is checked against something. */
const keptPrefixIn = (home) => join(home, '.bantamkit', 'mcp');
const keptCliIn = (home) => join(keptPrefixIn(home), 'node_modules', 'bantamkit-mcp', 'dist', 'cli.js');

/** What `npm install --prefix` leaves behind, as far as this module reads it. */
function seedKept(home, version) {
  const cli = keptCliIn(home);
  mkdirSync(dirname(cli), { recursive: true });
  writeFileSync(join(dirname(dirname(cli)), 'package.json'), JSON.stringify({ name: 'bantamkit-mcp', version }));
  writeFileSync(cli, '');
  return cli;
}

/** An installer double: records every argv it is handed and answers with `effect(argv)`. */
function recorder(effect) {
  const calls = [];
  const fn = (argv) => {
    calls.push([...argv]);
    return effect(argv);
  };
  fn.calls = calls;
  return fn;
}

const mustNotInstall = recorder(() => {
  throw new Error('the installer ran on a branch that must stay offline');
});

test('the kept prefix is exported once and lives at <home>/.bantamkit/mcp', async () => {
  await withHome(async (h, root) => {
    assert.equal(h.keptPrefix(), keptPrefixIn(root));
    assert.equal(h.keptCli(), keptCliIn(root));
  });
});

test('ephemeral with no kept install: npm runs once into the kept prefix, then the entry names it', async () => {
  await withHome(async (h, root) => {
    const path = h.hostConfigPath('cursor');
    const installer = recorder(() => {
      // The config is not touched before the kept install exists.
      assert.ok(!existsSync(path), 'a host config was written before the kept install was made');
      seedKept(root, VERSION);
      return [0, 'added 95 packages'];
    });
    h.installSelf('cursor', false, { shape: () => 'ephemeral', installer });
    assert.deepEqual(installer.calls, [
      ['npm', 'install', '--prefix', keptPrefixIn(root), `bantamkit-mcp@${VERSION}`],
    ]);
    assert.deepEqual(readJson(path).mcpServers.bantamkit, { command: process.execPath, args: [keptCliIn(root)] });
  });
});

test('ephemeral with a kept install at this version: npm never runs, same entry', async () => {
  // A second `--install` for another host must work with no network at all.
  await withHome(async (h, root) => {
    seedKept(root, VERSION);
    h.installSelf('copilot', false, { shape: () => 'ephemeral', installer: mustNotInstall });
    assert.deepEqual(readJson(h.hostConfigPath('copilot')).servers.bantamkit, {
      type: 'stdio',
      command: process.execPath,
      args: [keptCliIn(root)],
    });
    assert.deepEqual(mustNotInstall.calls, []);
  });
});

test('ephemeral with a kept install at an OLDER version: npm runs', async () => {
  await withHome(async (h, root) => {
    seedKept(root, '0.0.1');
    const installer = recorder(() => {
      seedKept(root, VERSION);
      return [0, ''];
    });
    h.installSelf('cursor', false, { shape: () => 'ephemeral', installer });
    assert.equal(installer.calls.length, 1);
    assert.equal(installer.calls[0].at(-1), `bantamkit-mcp@${VERSION}`);
    assert.deepEqual(readJson(h.hostConfigPath('cursor')).mcpServers.bantamkit.args, [keptCliIn(root)]);
  });
});

// J51-9a (review F1). `--install` from a stale npx cache must never move a NEWER kept install
// back: the operator ran `--update` to a later release, and every host already launches that
// kept install. The pair is mixed-digit on purpose — as strings `'0.10.0' < '0.9.0'`, so an
// equality check and a string comparison both run npm here, and only a numeric order passes.
test('ephemeral with a kept install at a NEWER version: npm never runs, the kept install is recorded', async () => {
  await withHome(async (h, root) => {
    seedKept(root, '0.10.0');
    const installer = recorder(() => {
      seedKept(root, '0.9.0');
      return [0, ''];
    });
    h.installSelf('cursor', false, { shape: () => 'ephemeral', installer, version: '0.9.0' });
    assert.deepEqual(installer.calls, [], 'npm ran and would have downgraded the kept install');
    assert.deepEqual(readJson(h.hostConfigPath('cursor')).mcpServers.bantamkit, {
      command: process.execPath,
      args: [keptCliIn(root)],
    });
    assert.equal(readJson(join(dirname(dirname(keptCliIn(root))), 'package.json')).version, '0.10.0');
  });
});

test('ephemeral with a kept install whose version is not dotted numbers: kept, never replaced, no stack trace', async () => {
  // `compareVersions` is total: a non-numeric component sorts after every number in its
  // position, so a version this module cannot read as numbers ranks ABOVE the running one.
  // The kept install is left alone rather than overwritten with something that may be older.
  await withHome(async (h, root) => {
    seedKept(root, 'not-a-version');
    const installer = recorder(() => [0, '']);
    const { command, args } = h.thisCommand({ shape: () => 'ephemeral', installer, version: '0.9.0' });
    assert.deepEqual(installer.calls, []);
    assert.deepEqual({ command, args }, { command: process.execPath, args: [keptCliIn(root)] });
  });
});

test('ephemeral with a kept install at a NEWER version but no cli.js: npm runs, as with no kept install', async () => {
  await withHome(async (h, root) => {
    rmSync(seedKept(root, '0.10.0'));
    const installer = recorder(() => {
      seedKept(root, '0.9.0');
      return [0, ''];
    });
    h.installSelf('cursor', false, { shape: () => 'ephemeral', installer, version: '0.9.0' });
    assert.deepEqual(installer.calls, [['npm', 'install', '--prefix', keptPrefixIn(root), 'bantamkit-mcp@0.9.0']]);
  });
});

test('ephemeral with a kept install reporting a BLANK version: npm runs, as with no readable version', async () => {
  await withHome(async (h, root) => {
    seedKept(root, '   ');
    const installer = recorder(() => {
      seedKept(root, '0.9.0');
      return [0, ''];
    });
    h.installSelf('cursor', false, { shape: () => 'ephemeral', installer, version: '0.9.0' });
    assert.equal(installer.calls.length, 1);
  });
});

test('npm failing is a refusal naming prefix, command and exit; the config is byte-unchanged', async () => {
  await withHome(async (h, root) => {
    const path = h.hostConfigPath('cursor');
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify({ mcpServers: { 'someone-else': { command: 'keep-me', args: [] } } }));
    const before = readFileSync(path);
    const installer = recorder(() => [1, 'npm http fetch GET\nnpm error code ETIMEDOUT\n']);
    assert.throws(
      () => h.installSelf('cursor', false, { shape: () => 'ephemeral', installer }),
      (e) =>
        e instanceof h.InstallError &&
        e.message.includes(keptPrefixIn(root)) &&
        e.message.includes(`npm install --prefix ${keptPrefixIn(root)} bantamkit-mcp@${VERSION}`) &&
        e.message.includes('exited 1') &&
        e.message.includes('npm error code ETIMEDOUT') &&
        !e.message.includes('npm http fetch GET'),
    );
    assert.deepEqual(readFileSync(path), before);
    assert.deepEqual(backupsIn(path), []);
  });
});

test('npm exiting 0 without leaving the cli.js is the same refusal, not a half-install', async () => {
  await withHome(async (h, root) => {
    const installer = recorder(() => [0, 'up to date']);
    assert.throws(
      () => h.installSelf('cursor', false, { shape: () => 'ephemeral', installer }),
      (e) => e instanceof h.InstallError && e.message.includes(keptCliIn(root)) && e.message.includes('exited 0'),
    );
    assert.ok(!existsSync(h.hostConfigPath('cursor')));
  });
});

for (const shape of ['registry', 'local-file', 'linked', 'checkout']) {
  test(`a ${shape} install is already kept: npm never runs, the entry is this process's own cli.js`, async () => {
    await withHome(async (h) => {
      h.installSelf('cursor', false, { shape: () => shape, installer: mustNotInstall });
      assert.deepEqual(readJson(h.hostConfigPath('cursor')).mcpServers.bantamkit, {
        command: process.execPath,
        args: [OWN_CLI],
      });
      assert.deepEqual(mustNotInstall.calls, []);
    });
  });
}

test('the default shape is currentInstall()’s, and this tree is a checkout', async () => {
  await withHome(async (h) => {
    h.installSelf('cursor', false, { installer: mustNotInstall });
    assert.deepEqual(readJson(h.hostConfigPath('cursor')).mcpServers.bantamkit, {
      command: process.execPath,
      args: [OWN_CLI],
    });
    assert.ok(existsSync(OWN_CLI));
  });
});

test('an install shape that cannot be derived is a refusal, not a guessed command', async () => {
  const { Undetermined } = await import('../dist/mcp/identity.js');
  await withHome(async (h) => {
    const shape = () => {
      throw new Undetermined('this install records its origin as git+https://example/x');
    };
    assert.throws(
      () => h.installSelf('cursor', false, { shape, installer: mustNotInstall }),
      (e) => e instanceof h.InstallError && e.message.includes('git+https://example/x'),
    );
    assert.ok(!existsSync(h.hostConfigPath('cursor')));
  });
});

test('the claude arm hands `claude mcp add` the same absolute pair', { skip: process.platform === 'win32' }, async () => {
  const { chmodSync } = await import('node:fs');
  await withHome(async (h, root) => {
    const bin = join(root, 'bin');
    mkdirSync(bin, { recursive: true });
    const seen = join(root, 'argv.txt');
    writeFileSync(join(bin, 'claude'), `#!/bin/sh\nfor a in "$@"; do printf '%s\\n' "$a"; done > '${seen}'\nexit 0\n`);
    chmodSync(join(bin, 'claude'), 0o755);
    const previousPath = process.env.PATH;
    process.env.PATH = `${bin}:${previousPath}`;
    try {
      const installer = recorder(() => {
        seedKept(root, VERSION);
        return [0, ''];
      });
      h.installSelf('claude', false, { shape: () => 'ephemeral', installer });
      assert.deepEqual(readFileSync(seen, 'utf8').split('\n').slice(0, -1), [
        'mcp', 'add', 'bantamkit', '-s', 'user', '--', process.execPath, keptCliIn(root),
      ]);
    } finally {
      process.env.PATH = previousPath;
    }
  });
});

test('--install on the real CLI records the absolute node and this tree’s cli.js, never npx', () => {
  const root = mkdtempSync(join(tmpdir(), 'bk-hostinstall-cli-'));
  try {
    const r = spawnSync(process.execPath, [OWN_CLI, '--install', 'cursor'], {
      input: '',
      encoding: 'utf8',
      env: { ...process.env, HOME: root, USERPROFILE: root },
    });
    assert.equal(r.status, 0, r.stderr);
    const entry = readJson(join(root, '.cursor', 'mcp.json')).mcpServers.bantamkit;
    assert.deepEqual(entry, { command: process.execPath, args: [OWN_CLI] });
    assert.ok(isAbsolute(entry.command) && isAbsolute(entry.args[0]));
    assert.ok(r.stdout.includes(`  command: ${process.execPath} ${OWN_CLI}`), r.stdout);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// --- the five things review found that no test could see ------------------------------------

for (const [payload, name] of [
  ['"hello"', 'str'],
  ['5', 'int'],
  ['5.5', 'float'],
  ['true', 'bool'],
  ['null', 'NoneType'],
]) {
  test(`the refusal names CPython's type for JSON ${payload}`, async () => {
    // `[1, 2, 3]` was the only input the first pair of tests used, and it was the wrong one:
    // `list` is the ONE type name the two languages spell the same, so a port answering
    // `string`, `number` and `boolean` passed both suites. Review measured it.
    await withHome(async (h) => {
      const path = h.hostConfigPath('cursor');
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, payload);
      assert.throws(
        () => h.install('cursor', CMD, []),
        (e) => e.message.includes(`holds ${name}, not an object`),
      );
    });
  });
}

test('a null entry is present and is not replaced without force', async () => {
  // `"bantamkit": null` is an ENTRY. The reference used `.get() is not None` at first and
  // rewrote the file where this side refused — one config, two outcomes.
  await withHome(async (h) => {
    const path = h.hostConfigPath('cursor');
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify({ mcpServers: { bantamkit: null } }));
    const before = readFileSync(path);
    assert.throws(
      () => h.install('cursor', CMD, []),
      (e) => e.message.includes('current : null'),
    );
    assert.deepEqual(readFileSync(path), before);
    h.install('cursor', CMD, [], true);
    assert.equal(readJson(path).mcpServers.bantamkit.command, CMD);
  });
});

test('the file’s mode survives the replace', { skip: process.platform === 'win32' }, async () => {
  // A host config carries API keys in per-server `env`; 0600 must not come back 0644. The
  // write is a temp file plus a rename and a fresh temp file gets the process umask.
  const { chmodSync, statSync } = await import('node:fs');
  await withHome(async (h) => {
    const path = h.hostConfigPath('cursor');
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify({ mcpServers: {} }));
    chmodSync(path, 0o600);
    h.install('cursor', CMD, []);
    assert.equal(statSync(path).mode & 0o777, 0o600);
  });
});

test('the claude arm prints a command someone can re-run', { skip: process.platform === 'win32' }, async () => {
  // Nothing tested this arm at all, because it shells out. A stub on PATH is enough to pin
  // what it prints — and the reference printed `mcp add bantamkit ...` without the verb.
  const { chmodSync } = await import('node:fs');
  await withHome(async (h, root) => {
    const bin = join(root, 'bin');
    mkdirSync(bin, { recursive: true });
    writeFileSync(join(bin, 'claude'), '#!/bin/sh\nexit 0\n');
    chmodSync(join(bin, 'claude'), 0o755);
    const previousPath = process.env.PATH;
    process.env.PATH = `${bin}:${previousPath}`;
    try {
      const report = h.install('claude', CMD, ['--flag']);
      assert.equal(
        report.split('\n')[1],
        `  ran    : claude mcp add bantamkit -s user -- ${CMD} --flag`,
      );
    } finally {
      process.env.PATH = previousPath;
    }
  });
});

test('the claude arm reports the host’s own failure', { skip: process.platform === 'win32' }, async () => {
  const { chmodSync } = await import('node:fs');
  await withHome(async (h, root) => {
    const bin = join(root, 'bin');
    mkdirSync(bin, { recursive: true });
    writeFileSync(join(bin, 'claude'), "#!/bin/sh\necho 'no such scope' >&2\nexit 3\n");
    chmodSync(join(bin, 'claude'), 0o755);
    const previousPath = process.env.PATH;
    process.env.PATH = `${bin}:${previousPath}`;
    try {
      assert.throws(
        () => h.install('claude', CMD, []),
        (e) => e.message.includes('`claude mcp add` failed (exit 3)') && e.message.includes('no such scope'),
      );
    } finally {
      process.env.PATH = previousPath;
    }
  });
});

// --- the Windows arm, which is the only code on this branch that was never run -------------
//
// `installViaClaudeCli` passes `shell: true` on win32 because an npm-installed `claude` is a
// `claude.cmd` shim and `spawnSync` cannot launch a batch file without one — it returns
// ENOENT, which this module would report as "not on PATH", the one message guaranteed to send
// someone looking in the wrong place.
//
// That whole paragraph was REASONED, not measured: it was written on a Mac. The two tests
// above that exercise the arm are skipped on win32 because their stub is a `#!/bin/sh` script,
// so a Windows CI run would have skipped exactly the thing in question and reported green.
// These two are the mirror image — they run ONLY on Windows, against a real `.cmd`.

const winOnly = { skip: process.platform !== 'win32' };

test('a claude.cmd shim is launched rather than reported as missing', winOnly, async () => {
  await withHome(async (h, root) => {
    const bin = join(root, 'bin');
    mkdirSync(bin, { recursive: true });
    // `@echo off` so the shim's own echo does not become the output under test.
    writeFileSync(join(bin, 'claude.cmd'), '@echo off\r\nexit /b 0\r\n');
    const previousPath = process.env.PATH;
    process.env.PATH = `${bin};${previousPath}`;
    try {
      const report = h.install('claude', CMD, ['--flag']);
      assert.equal(
        report.split('\n')[1],
        `  ran    : claude mcp add bantamkit -s user -- ${CMD} --flag`,
      );
    } finally {
      process.env.PATH = previousPath;
    }
  });
});

test('a path with a space survives the shell on Windows', winOnly, async () => {
  // The quoting is the half most likely to be wrong: `cmd.exe` scans `"` to toggle its own
  // quoting state while the child parses argv by C-runtime rules, and those are two different
  // sets of rules. `C:\Program Files\...` is the normal case on Windows, not an edge one, so
  // if the escaping is wrong this is where it shows.
  await withHome(async (h, root) => {
    const bin = join(root, 'bin');
    mkdirSync(bin, { recursive: true });
    // The shim writes its own arguments out, so the assertion is about what ARRIVED, not just
    // about the exit code — a shell that mangled the quoting would still exit 0.
    writeFileSync(join(bin, 'claude.cmd'), `@echo off\r\necho %* > "${join(root, 'seen.txt')}"\r\nexit /b 0\r\n`);
    const previousPath = process.env.PATH;
    process.env.PATH = `${bin};${previousPath}`;
    const spaced = 'C:\\Program Files\\bantamkit\\bantamkit-mcp.exe';
    try {
      h.install('claude', spaced, []);
      const seen = readFileSync(join(root, 'seen.txt'), 'utf8');
      assert.ok(
        seen.includes(spaced),
        `the shim received ${JSON.stringify(seen)}, which does not contain the spaced path`,
      );
    } finally {
      process.env.PATH = previousPath;
    }
  });
});
