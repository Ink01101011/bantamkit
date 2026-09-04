#!/usr/bin/env node
// The usage ledger: which tools, skills and agents were ACTUALLY invoked, across every session.
//
//   node tools/ledger/tool-usage.mjs                      # all projects, all time, by tool
//   node tools/ledger/tool-usage.mjs --group skill        # by skill (Skill's `skill` input)
//   node tools/ledger/tool-usage.mjs --group agent        # by agent (Agent's `subagent_type`)
//   node tools/ledger/tool-usage.mjs --group server       # by MCP server, builtins as `builtin`
//   node tools/ledger/tool-usage.mjs --since 7d           # 7d / 12h / 2w / YYYY-MM-DD
//   node tools/ledger/tool-usage.mjs --json
//
// WHY. `token-ledger.mjs` answers what a session cost. This answers what was ever REACHED FOR
// — the denominator you need before claiming a skill, tool or MCP server earns the context it
// occupies. A skill's description is loaded into every session; its body is not. Deciding
// whether that description pays for itself needs a call count, and the count has been on disk
// the whole time.
//
// TWO CORRECTIONS this makes over a naive scan, both measured on this machine:
//
//   DEDUPE BY tool_use id. A resumed session repeats earlier `tool_use` blocks verbatim, so
//   the same call is written to two files. Counting lines inflates the total; counting
//   distinct ids does not. Ported from tool-metrics' `dedupe_by_id`.
//
//   COUNT SUBAGENT TRANSCRIPTS. Besides `<project>/<session>.jsonl` the host writes
//   `<project>/<session>/subagents/*.jsonl` and deeper. A flat readdir misses most of them —
//   128 of 140 files under this repo's own slug are nested.
//
// NOT ported from tool-metrics, deliberately: its on-disk cache and GC layer. The full scan
// of 813 transcripts runs in about a second here, so the cache would buy nothing and would
// add a staleness mode to reason about. Revisit if the corpus grows an order of magnitude.
//
// Pure Node, no dependencies, read-only. Never writes under ~/.claude.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const args = process.argv.slice(2);
const flag = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };
const GROUP = flag('--group', 'tool');
const JSON_OUT = args.includes('--json');
const PROJECT = flag('--project', null);
const ROOT = path.join(os.homedir(), '.claude', 'projects');

const GROUPS = ['tool', 'server', 'project', 'skill', 'agent'];
if (!GROUPS.includes(GROUP)) {
  console.error(`--group must be one of ${GROUPS.join(', ')}`);
  process.exit(2);
}

// `--since` accepts the same spellings tool-metrics accepted, so a reader can carry a command
// over unchanged: 7d / 12h / 2w, or an absolute YYYY-MM-DD.
function parseSince(value) {
  if (!value) return null;
  const rel = /^(\d+)([hdw])$/.exec(value);
  if (rel) {
    const n = Number(rel[1]);
    const ms = { h: 3600e3, d: 86400e3, w: 7 * 86400e3 }[rel[2]];
    return Date.now() - n * ms;
  }
  const abs = Date.parse(value);
  if (Number.isNaN(abs)) { console.error(`--since: cannot read ${value}`); process.exit(2); }
  return abs;
}
const SINCE = parseSince(flag('--since', null));

// `<project>/<session>.jsonl` is the main transcript; `<project>/<session>/subagents/*.jsonl`
// are the subagents' — same walk as token-ledger.mjs, for the same reason.
function walk(dir, out) {
  let entries = [];
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return out; }
  for (const e of entries) {
    const q = path.join(dir, e.name);
    if (e.isDirectory()) walk(q, out);
    else if (e.name.endsWith('.jsonl')) out.push(q);
  }
  return out;
}

function serverOf(tool) {
  if (!tool.startsWith('mcp__')) return 'builtin';
  const parts = tool.split('__');
  return parts.length >= 3 ? parts[1] : 'builtin';
}

// The grouping key. `skill` and `agent` read the tool's own input, so they are only defined
// for the tool that carries them; every other call is left out of those groupings rather than
// bucketed as "other", which would drown the rows that answer the question.
function keyOf(ev) {
  switch (GROUP) {
    case 'tool': return ev.tool;
    case 'server': return ev.server;
    case 'project': return ev.project;
    case 'skill': return ev.tool === 'Skill' ? (ev.detail || null) : null;
    case 'agent': return ev.tool === 'Agent' ? (ev.detail || null) : null;
    default: return null;
  }
}

// The events log the PostToolUse hook appends to. Default matches where tool-metrics writes,
// so this reads a machine's existing history rather than starting an empty one.
const EVENTS = flag('--events', path.join(os.homedir(), '.claude', 'tool-metrics', 'events.jsonl'));
function readEvents() {
  if (args.includes('--no-events')) return [];
  try { return fs.readFileSync(EVENTS, 'utf8').split('\n').filter((l) => l.trim()); } catch { return []; }
}

let dirs = [];
try {
  dirs = fs.readdirSync(ROOT, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name);
} catch {
  console.error(`no transcripts: ${ROOT} is not readable`);
  process.exit(1);
}
if (PROJECT) dirs = dirs.filter((d) => d.includes(PROJECT));

const seenIds = new Set();     // tool_use id → already counted
const counts = new Map();      // group key → calls
const sessions = new Set();    // session files that contributed a counted call
const onDisk = new Set();      // session ids that still have a transcript
let scanned = 0, skipped = 0, total = 0, recovered = 0;

function record(ev) {
  total += 1;
  const key = keyOf(ev);
  if (key === null) return;
  counts.set(key, (counts.get(key) ?? 0) + 1);
}

for (const project of dirs) {
  for (const file of walk(path.join(ROOT, project), [])) {
    scanned += 1;
    onDisk.add(path.basename(file, '.jsonl'));
    let text;
    try { text = fs.readFileSync(file, 'utf8'); } catch { skipped += 1; continue; }
    for (const line of text.split('\n')) {
      if (!line.includes('"tool_use"')) continue;
      let rec;
      try { rec = JSON.parse(line); } catch { continue; }
      if (SINCE !== null) {
        const ts = Date.parse(rec.timestamp ?? '');
        if (!Number.isNaN(ts) && ts < SINCE) continue;
      }
      const content = rec.message?.content;
      if (!Array.isArray(content)) continue;
      for (const block of content) {
        if (block?.type !== 'tool_use' || !block.name) continue;
        // The id is the dedupe key: a resumed session rewrites the same block verbatim.
        if (block.id) {
          if (seenIds.has(block.id)) continue;
          seenIds.add(block.id);
        }
        const input = block.input && typeof block.input === 'object' ? block.input : {};
        const ev = {
          tool: block.name,
          server: serverOf(block.name),
          project,
          detail: block.name === 'Skill' ? String(input.skill ?? '')
            : block.name === 'Agent' ? String(input.subagent_type || 'general-purpose')
              : '',
        };
        sessions.add(file);
        record(ev);
      }
    }
  }
}

// A transcript can be deleted while the calls it recorded still matter. The PostToolUse hook
// appends one line per call to an events log, so those sessions are still countable — but ONLY
// the sessions with no transcript left, or every call in a live session would be counted twice.
// Measured here: 4 of 110 logged sessions were gone, holding 9 skill calls.
for (const line of readEvents()) {
  let ev;
  try { ev = JSON.parse(line); } catch { continue; }
  if (!ev?.tool || !ev.session || onDisk.has(ev.session)) continue;
  if (SINCE !== null) {
    const ts = Date.parse(ev.ts ?? '');
    if (!Number.isNaN(ts) && ts < SINCE) continue;
  }
  if (PROJECT && !String(ev.project ?? '').includes(PROJECT)) continue;
  recovered += 1;
  sessions.add(ev.session);
  record({
    tool: ev.tool,
    server: ev.server || serverOf(ev.tool),
    project: ev.project ?? '',
    detail: ev.detail ?? '',
  });
}

const rows = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));

if (JSON_OUT) {
  console.log(JSON.stringify({
    group: GROUP, total, sessions: sessions.size, transcripts: scanned, unreadable: skipped,
    recovered_from_events: recovered,
    rows: rows.map(([key, calls]) => ({ key, calls })),
  }, null, 1));
} else {
  const grouped = rows.reduce((n, [, c]) => n + c, 0);
  console.log(`tool usage — ${total} calls, ${sessions.size} sessions, ${scanned} transcripts (group: ${GROUP})`);
  if (recovered) console.log(`${recovered} calls recovered from the events log for sessions with no transcript left`);
  if (grouped !== total) console.log(`${grouped} of them carry a ${GROUP}; the rest are other tools`);
  if (skipped) console.log(`${skipped} transcripts unreadable`);
  console.log();
  const width = rows.reduce((w, [k]) => Math.max(w, k.length), 0);
  for (const [key, calls] of rows) console.log(`  ${key.padEnd(width)}  ${String(calls).padStart(5)}`);
  if (!rows.length) console.log('  (nothing recorded)');
}
