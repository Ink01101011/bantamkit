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
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';

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

test('this side registers npx and never a path from this machine', async () => {
  // The ruled divergence, pinned from this side so it cannot drift into "whatever ran".
  const { thisCommand } = await import('../dist/hostinstall.js');
  assert.deepEqual(thisCommand(), { command: 'npx', args: ['-y', 'bantamkit-mcp'] });
});
