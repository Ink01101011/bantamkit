/**
 * Capability tiers and the storage lines of `bantamkit_status` (#204, S2; job69 J69-7): the
 * same nodes as runtime-py/tests/test_storage_tiers.py. `storage-tiers` conformance compares
 * the two runtimes over an MCP-only host profile.
 *
 * Every test runs inside `bed()`, which points HOME/USERPROFILE at a scratch directory and
 * clears the native override for its duration, so nothing here reads the operator's home.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';

const T = await import('../dist/storage/tiers.js');
const { Memory } = await import('../dist/memory/component.js');
const { FAMILIES, SHARDS } = await import('../dist/storage/index.js');

const OURS = { matcher: '', hooks: [{ type: 'command', command: 'x --hook', bantamkit: 'hook' }] };
const THEIRS = { matcher: '', hooks: [{ type: 'command', command: 'notify-send hi' }] };
const KEYS = ['HOME', 'USERPROFILE', 'CLAUDE_COWORK_MEMORY_PATH_OVERRIDE', 'BANTAMKIT_RETENTION', 'BANTAMKIT_INDEX_DIR'];

function bed(fn) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'tiers-')));
  const home = path.join(base, 'home');
  fs.mkdirSync(path.join(home, '.bantamkit'), { recursive: true });
  const saved = Object.fromEntries(KEYS.map((k) => [k, process.env[k]]));
  process.env.HOME = home;
  process.env.USERPROFILE = home;
  delete process.env.CLAUDE_COWORK_MEMORY_PATH_OVERRIDE;
  process.env.BANTAMKIT_RETENTION = 'off';
  process.env.BANTAMKIT_INDEX_DIR = path.join(base, 'idx');
  try {
    return fn({ base, home });
  } finally {
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
    fs.rmSync(base, { recursive: true, force: true });
  }
}

const settings = (p, data) => {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, typeof data === 'string' ? data : JSON.stringify(data));
};

test('the MCP-only profile is core only', () =>
  bed(({ base, home }) => {
    assert.deepEqual(T.tiers(home, path.join(base, 'cwd')), { core: true, hook: false, host_data: false });
  }));

test('a user-scope bantamkit hook turns the hook tier on', () =>
  bed(({ base, home }) => {
    settings(path.join(home, '.claude', 'settings.json'), { hooks: { SessionStart: [OURS] } });
    assert.equal(T.tiers(home, base).hook, true);
  }));

test("a project-scope hook counts and someone else's does not", () =>
  bed(({ base, home }) => {
    const cwd = path.join(base, 'proj');
    settings(path.join(cwd, '.claude', 'settings.json'), { hooks: { Stop: [THEIRS] } });
    assert.equal(T.hookTier(home, cwd), false);
    settings(path.join(cwd, '.claude', 'settings.local.json'), { hooks: { Stop: [THEIRS, OURS] } });
    assert.equal(T.hookTier(home, cwd), true);
    assert.equal(T.hookTier(home, null), false);
  }));

for (const text of ['{not json', '[]', '{"hooks": 5}', '{"hooks": {"Stop": 5}}', '﻿' + JSON.stringify({ hooks: { Stop: [OURS] } }), '']) {
  test(`a settings file hostinstall would refuse is a tier that is off: ${JSON.stringify(text).slice(0, 30)}`, () =>
    bed(({ base, home }) => {
      settings(path.join(home, '.claude', 'settings.json'), text);
      assert.equal(T.hookTier(home, base), false);
    }));
}

test('settings that are not UTF-8 are off, not a crash', () =>
  bed(({ base, home }) => {
    const p = path.join(home, '.claude', 'settings.json');
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, Buffer.concat([Buffer.from('{"hooks": {"Stop": [{"hooks": [{"bantamkit": "hook", "c": "'), Buffer.from([0xff]), Buffer.from('"}]}]}}')]));
    assert.equal(T.hookTier(home, base), false);
  }));

test('settings that are a directory are off', () =>
  bed(({ base, home }) => {
    fs.mkdirSync(path.join(home, '.claude', 'settings.json'), { recursive: true });
    assert.equal(T.hookTier(home, base), false);
  }));

test('host data follows the native resolver', () =>
  bed(({ base, home }) => {
    const native = path.join(base, 'native');
    fs.mkdirSync(native);
    settings(path.join(home, '.claude', 'settings.json'), { autoMemoryDirectory: native });
    assert.equal(T.hostDataTier(home), false);
    fs.writeFileSync(path.join(native, 'MEMORY.md'), '# index\n');
    assert.equal(T.hostDataTier(home), true);
    fs.unlinkSync(path.join(native, 'MEMORY.md'));
    process.env.CLAUDE_COWORK_MEMORY_PATH_OVERRIDE = path.join(base, 'anything');
    assert.equal(T.hostDataTier(home), true);
  }));

test('tierLine spells each tier', () => {
  assert.equal(T.tierLine({ core: true, hook: true, host_data: false }), 'storage: core on; hooks on; host data off');
});

const memoryIn = (base) => {
  const root = path.join(base, 'store');
  fs.mkdirSync(path.join(root, 'facts'), { recursive: true });
  const mem = new Memory(root);
  mem.save('project', 'tier-probe', 'a probe for the tiers', 'body');
  return mem;
};

test('the index line is persisted with the bytes on disk', () =>
  bed(({ base }) => {
    const mem = memoryIn(base);
    const [line, ...rest] = T.indexLines(mem);
    assert.deepEqual(rest, []);
    const idx = mem.store.index();
    const files = [idx.path];
    for (const f of FAMILIES) for (let i = 0; i < SHARDS; i += 1) files.push(idx.shardPath(f, i));
    const held = files.reduce((s, p) => s + (fs.existsSync(p) ? fs.statSync(p).size : 0), 0);
    assert.ok(held > 0);
    assert.equal(line, `index facts project: 1 doc, ${held} bytes, persisted`);
  }));

test('an unwritable index dir is reported in-memory', () =>
  bed(({ base }) => {
    const blocker = path.join(base, 'not-a-dir');
    fs.writeFileSync(blocker, 'x');
    process.env.BANTAMKIT_INDEX_DIR = path.join(blocker, 'idx');
    const mem = memoryIn(base);
    assert.deepEqual(T.indexLines(mem), ['index facts project: 1 doc, 0 bytes, in-memory']);
    assert.ok(mem.recall('tiers probe').length > 0);
  }));

test('a layer without facts has no index line', () =>
  bed(({ base }) => {
    assert.deepEqual(T.indexLines(new Memory(path.join(base, 'nothing'))), []);
  }));

test('log lines count bytes, segments and skipped', () =>
  bed(({ home }) => {
    const hooks = path.join(home, '.bantamkit', 'hooks');
    fs.mkdirSync(hooks);
    const live = path.join(hooks, 'hook-log.jsonl');
    fs.writeFileSync(live, '{"event":"A"}\nnot json\n');
    const seg = path.join(hooks, 'hook-log.jsonl.1.gz');
    fs.writeFileSync(seg, zlib.gzipSync(Buffer.from('{"event":"B"}\n')));
    const usage = path.join(home, '.bantamkit', 'usage');
    fs.mkdirSync(usage);
    fs.writeFileSync(path.join(usage, 'abc.jsonl'), '{"ts":"2026-10-01T00:00:00Z"}\n');
    fs.writeFileSync(path.join(usage, 'ignored.txt'), 'x');
    const total = fs.statSync(live).size + fs.statSync(seg).size;
    assert.deepEqual(T.logLines(home), [
      `logs: hook-log ${total} (1 rotated, 1 skipped)`,
      'logs: usage/abc 30 (0 rotated, 0 skipped)',
    ]);
  }));

test('no log is logs: none', () =>
  bed(({ home }) => {
    assert.deepEqual(T.logLines(home), ['logs: none']);
  }));

test('the retention line reads the record', () =>
  bed(({ home }) => {
    delete process.env.BANTAMKIT_RETENTION;
    assert.equal(T.retentionLine(home), 'retention: last ran never; refused 0');
    const record = { ran_at: '2026-10-16T01:40:13.095Z', report: { refused: [{ path: 'p', reason: 'r' }] } };
    fs.writeFileSync(path.join(home, '.bantamkit', 'retention.json'), JSON.stringify(record));
    assert.equal(T.retentionLine(home), 'retention: last ran 2026-10-16T01:40:13.095Z; refused 1');
    process.env.BANTAMKIT_RETENTION = 'off';
    assert.equal(T.retentionLine(home), 'retention: off; last ran 2026-10-16T01:40:13.095Z; refused 1');
    fs.writeFileSync(path.join(home, '.bantamkit', 'retention.json'), '{');
    assert.equal(T.retentionLine(home), 'retention: off; last ran never; refused 0');
  }));

test('statusLines never throws on an unreadable home', () =>
  bed(({ base, home }) => {
    fs.rmdirSync(path.join(home, '.bantamkit'));
    fs.writeFileSync(path.join(home, '.bantamkit'), 'a file where a directory belongs');
    assert.deepEqual(T.statusLines(new Memory(path.join(base, 's')), home, base), [
      'storage: core on; hooks off; host data off',
      'logs: none',
      'touch: none', // AMENDED job70 T200-1 (#200): the `touch:` line, between logs and retention
      'retention: off; last ran never; refused 0',
    ]);
  }));
