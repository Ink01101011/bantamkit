/**
 * skillhost (#205 Task 2): the same nodes as runtime-py/tests/test_skillhost.py.
 * `tools/conformance/suites/skill-host.mjs` compares the two runtimes. Every path is under a
 * fresh temp directory: nothing here reads a real home.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const H = await import('../dist/skillhost.js');
const { parseNow } = await import('../dist/storage/retention.js');

const NOW_MS = parseNow('2026-10-16T00:00:00.000Z');
const DAY = 86_400_000;

const tmp = () => fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'skillhost-')));
const counts = (scan) => Object.fromEntries([...scan.counts.entries()].sort());

function use(id, skill, ts = '2026-10-15T00:00:00.000Z') {
  const block = { type: 'tool_use', name: 'Skill', input: { skill } };
  if (id !== null) block.id = id;
  return JSON.stringify({ timestamp: ts, message: { content: [block] } });
}

function typed(name, uuid = null, ts = '2026-10-15T00:00:00.000Z', extra = {}) {
  const rec = {
    type: 'user',
    timestamp: ts,
    message: {
      role: 'user',
      content: `<command-name>/${name}</command-name>\n<command-message>${name}</command-message>\n<command-args></command-args>`,
    },
    ...extra,
  };
  if (uuid !== null) rec.uuid = uuid;
  return JSON.stringify(rec);
}

function write(p, lines, ageDays = 1) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const bufs = lines.map((x) => (Buffer.isBuffer(x) ? x : Buffer.from(x, 'utf8')));
  fs.writeFileSync(p, Buffer.concat([Buffer.concat(bufs.flatMap((b, i) => (i ? [Buffer.from('\n'), b] : [b]))), Buffer.from('\n')]));
  const t = (NOW_MS - ageDays * DAY) / 1000;
  fs.utimesSync(p, t, t);
}

test('dedupe by id, subagents counted, old lines dropped', () => {
  const projects = path.join(tmp(), 'projects');
  write(path.join(projects, 'p1', 's1.jsonl'), [
    use('t1', 'beta:b1'),
    use(null, 'solo'),
    use('t3', 'alpha:a1', '2026-09-01T00:00:00.000Z'),
    '{"bad "Skill" "tool_use"',
    Buffer.concat([Buffer.from([0xff]), Buffer.from(' "Skill" "tool_use"')]),
    '{"text": "Skill without the block type"}',
  ]);
  write(path.join(projects, 'p1', 's2.jsonl'), [use('t1', 'beta:b1'), use(null, 'solo')]);
  write(path.join(projects, 'p1', 's1', 'subagents', 'agent-a.jsonl'), [use('t4', 'beta:b1')]);
  write(path.join(projects, 'p2', 'old.jsonl'), [use('t9', 'alpha:a2')], 40);
  const got = H.countSkillUsage(projects, NOW_MS);
  assert.deepEqual(counts(got), { 'beta:b1': 2, solo: 2 });
  assert.deepEqual([got.transcripts, got.unreadable, got.skippedLines, got.spanDays], [3, 0, 2, 30]);
});

test('span is the oldest seen, in days', () => {
  const projects = path.join(tmp(), 'projects');
  write(path.join(projects, 'p', 's.jsonl'), [use('t1', 'x', '2026-10-04T00:00:00.000Z')], 0);
  assert.equal(H.countSkillUsage(projects, NOW_MS).spanDays, 12);
});

test('no transcripts is span zero', () => {
  const got = H.countSkillUsage(path.join(tmp(), 'missing'), NOW_MS);
  assert.deepEqual([counts(got), got.spanDays, got.transcripts], [{}, 0, 0]);
});

test('a BOM line is skipped, not parsed', () => {
  const projects = path.join(tmp(), 'projects');
  write(path.join(projects, 'p', 's.jsonl'), [Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from(use('t1', 'solo'))])]);
  const got = H.countSkillUsage(projects, NOW_MS);
  assert.deepEqual([counts(got), got.skippedLines], [{}, 1]);
});

// ---------------------------------------------------------- Amendment A2: typed commands

test('both shapes count one call each', () => {
  const projects = path.join(tmp(), 'projects');
  write(path.join(projects, 'p', 's.jsonl'), [use('t1', 'solo'), typed('alpha:a1', 'u1')]);
  const got = H.countSkillUsage(projects, NOW_MS, 30, new Set(['solo', 'alpha:a1']));
  assert.deepEqual(counts(got), { 'alpha:a1': 1, solo: 1 });
  assert.equal(got.summary().calls, 2);
});

test('a command is counted only when it names a known skill', () => {
  const projects = path.join(tmp(), 'projects');
  const toolResult = JSON.stringify({
    type: 'user',
    timestamp: '2026-10-15T00:00:00.000Z',
    message: { role: 'user', content: [{ type: 'tool_result', content: '<command-name>/solo</command-name>' }] },
  });
  const toolInput = JSON.stringify({
    type: 'assistant',
    timestamp: '2026-10-15T00:00:00.000Z',
    message: { role: 'assistant', content: [{ type: 'tool_use', name: 'Bash', id: 'b1', input: { command: '<command-name>/solo</command-name>' } }] },
  });
  write(path.join(projects, 'p', 's.jsonl'), [
    typed('clear', 'u0'),
    typed('solo', 'u1'),
    typed('solo', 'u1'),
    typed('solo'),
    typed('solo', 'u2', undefined, { isMeta: true }),
    typed('solo', 'u3', '2026-09-01T00:00:00.000Z'),
    toolResult,
    toolInput,
  ]);
  assert.deepEqual(counts(H.countSkillUsage(projects, NOW_MS, 30, new Set(['solo']))), { solo: 2 });
  assert.deepEqual(counts(H.countSkillUsage(projects, NOW_MS)), {});
});

test('knownSkills spells ids as the audit does', () => {
  const base = tmp();
  const cache = path.join(base, 'cache');
  fs.mkdirSync(path.join(cache, 'mk', 'alpha', '1.0.0', 'skills', 'a1'), { recursive: true });
  fs.writeFileSync(path.join(cache, 'mk', 'alpha', '1.0.0', 'skills', 'a1', 'SKILL.md'), 'x');
  fs.mkdirSync(path.join(cache, 'mk', 'alpha', '1.0.0', 'skills', 'notaskill'));
  const local = path.join(base, 'skills');
  fs.mkdirSync(path.join(local, 'solo'), { recursive: true });
  fs.writeFileSync(path.join(local, 'solo', 'SKILL.md'), 'x');
  assert.deepEqual([...H.knownSkills([cache, local])].sort(), ['alpha:a1', 'solo']);
});

// ---------------------------------------------------------------------------- the adapters

function claudeHome(base) {
  const home = path.join(base, 'home');
  const cwd = path.join(base, 'proj');
  fs.mkdirSync(path.join(home, '.claude', 'plugins', 'cache', 'mk', 'alpha', '1.0.0', 'skills'), { recursive: true });
  fs.mkdirSync(path.join(home, '.claude', 'skills'), { recursive: true });
  fs.mkdirSync(path.join(cwd, '.claude', 'skills'), { recursive: true });
  fs.writeFileSync(
    path.join(home, '.claude', 'settings.json'),
    JSON.stringify({ enabledPlugins: { 'alpha@mk': true, 'beta@mk': true, 'gamma@mk': false } }),
  );
  fs.writeFileSync(path.join(cwd, '.claude', 'settings.local.json'), JSON.stringify({ enabledPlugins: { 'beta@mk': false } }));
  fs.writeFileSync(
    path.join(home, '.claude', 'plugins', 'installed_plugins.json'),
    JSON.stringify({
      version: 2,
      plugins: {
        'alpha@mk': [
          { scope: 'user', installPath: path.join(home, '.claude/plugins/cache/mk/alpha/1.0.0') },
          { scope: 'project', projectPath: cwd, installPath: '/x/mk/alpha/2.0.0' },
        ],
      },
    }),
  );
  return [home, cwd];
}

test('Claude Code gather', () => {
  const [home, cwd] = claudeHome(tmp());
  const adapter = H.selectAdapter(home);
  assert.equal(adapter.host, 'claude-code');
  const g = adapter.gather(home, cwd, NOW_MS);
  assert.deepEqual(g.roots.map(([l]) => l), ['plugins', 'project', 'user']);
  assert.deepEqual(g.enabled, ['alpha@mk']);
  assert.deepEqual(g.sources, { 'alpha@mk': path.join(home, '.claude', 'settings.json') });
  assert.deepEqual(g.versions, { 'alpha@mk': '2.0.0' });
  assert.equal(g.usage.spanDays, 0);
});

test('gather counts a typed skill from its roots', () => {
  const [home, cwd] = claudeHome(tmp());
  fs.mkdirSync(path.join(cwd, '.claude', 'skills', 'proj'));
  fs.writeFileSync(path.join(cwd, '.claude', 'skills', 'proj', 'SKILL.md'), 'x');
  write(path.join(home, '.claude', 'projects', 'p', 's.jsonl'), [typed('proj', 'u1'), typed('compact', 'u2')]);
  const g = H.selectAdapter(home).gather(home, cwd, NOW_MS);
  assert.deepEqual(counts(g.usage), { proj: 1 });
});

test('project root dropped when it is the user root', () => {
  const [home] = claudeHome(tmp());
  const g = H.selectAdapter(home).gather(home, home, NOW_MS);
  assert.deepEqual(g.roots.map(([l]) => l), ['plugins', 'user']);
});

test('Null adapter', () => {
  const base = tmp();
  const adapter = H.selectAdapter(base);
  assert.equal(adapter.host, 'none');
  const g = adapter.gather(base, null, NOW_MS);
  assert.deepEqual([g.roots, g.enabled, g.versions, g.sources, g.usage], [[], [], null, {}, null]);
  assert.equal(g.asDict().usage, null);
});

test('gather writes nothing', () => {
  const base = tmp();
  const [home, cwd] = claudeHome(base);
  const snap = () =>
    fs
      .readdirSync(base, { recursive: true })
      .map((rel) => [rel, fs.lstatSync(path.join(base, rel), { bigint: true }).mtimeNs.toString()])
      .sort();
  const before = snap();
  H.selectAdapter(home).gather(home, cwd, NOW_MS);
  assert.deepEqual(snap(), before);
});
