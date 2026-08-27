#!/usr/bin/env node
// The token ledger: what a session ACTUALLY cost, read off the host's own transcripts.
//
//   node tools/ledger/token-ledger.mjs                 # this cwd's project, last 7 days
//   node tools/ledger/token-ledger.mjs --days 30
//   node tools/ledger/token-ledger.mjs --all           # every project under ~/.claude/projects
//   node tools/ledger/token-ledger.mjs --json          # machine-readable, one object
//
// WHY. Every token figure in this repo and in the community hook tools is chars/4. The host
// writes the API's `usage` block on every assistant record in
// `~/.claude/projects/<cwd-slug>/<session>.jsonl`, so the real denominator has been on disk
// the whole time. This reads it and attributes what can be attributed honestly:
//
//   REAL   input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens
//          — deduped by `requestId`, because one API response is written as several
//          assistant lines (text, tool_use, …) that all carry the SAME usage block; summing
//          them naively overcounts by the number of content blocks.
//   REAL   tool calls by name, and the BYTES of each tool_result.
//   REAL   repeated Reads: same file_path (+offset/limit) read again in one session, and the
//          bytes those repeats returned — the exact population the PreToolUse read gate in
//          `tools/hooks` refuses. Before/after that hook is measured on this number.
//   EST.   tokens for any byte figure = bytes/4, and is labelled `est` wherever printed.
//
// Pure Node, no dependencies, read-only. Subagent transcripts under `<session>/subagents/`
// are counted in the session they belong to; the host keys them by the same sessionId.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const args = process.argv.slice(2);
const flag = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };
const DAYS = Number(flag('--days', 7));
const ALL = args.includes('--all');
const JSON_OUT = args.includes('--json');
const ROOT = path.join(os.homedir(), '.claude', 'projects');
const since = Date.now() - DAYS * 86400e3;

function slugOf(cwd) { return cwd.replace(/[\\/:]/g, '-'); }
const dirs = ALL
  ? fs.readdirSync(ROOT).map((d) => path.join(ROOT, d))
  : [path.join(ROOT, slugOf(flag('--cwd', process.cwd())))];

const sessions = new Map(); // sessionId → accumulator
function acc(id, cwd) {
  if (!sessions.has(id)) sessions.set(id, {
    session: id, cwd, first: null, last: null, requests: 0,
    input: 0, cacheWrite: 0, cacheRead: 0, output: 0,
    tools: {}, // name → {calls, resultBytes}
    reads: new Map(), repeatReads: 0, repeatReadBytes: 0,
    memorySaves: 0, recalls: 0,
  });
  return sessions.get(id);
}

for (const dir of dirs) {
  // `<project>/<session>.jsonl` is the main transcript; `<project>/<session>/subagents/*.jsonl`
  // are the subagents' — 128 of 140 files under this repo's slug are nested, so a flat read
  // misses the workers, which is where most Reads happen.
  const files = [];
  const walk = (d) => { let es = []; try { es = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
    for (const e of es) { const q = path.join(d, e.name); if (e.isDirectory()) walk(q); else if (e.name.endsWith('.jsonl')) files.push(q); } };
  walk(dir);
  for (const p of files) {
    if (fs.statSync(p).mtimeMs < since) continue;
    const seenReq = new Set();
    const pendingRead = new Map(); // tool_use id → read key
    const nameOf = new Map();      // tool_use id → tool name
    for (const line of fs.readFileSync(p, 'utf8').split('\n')) {
      if (!line) continue;
      let r; try { r = JSON.parse(line); } catch { continue; }
      const sid = r.sessionId; if (!sid) continue;
      const s = acc(sid, r.cwd);
      if (r.timestamp) { s.first = s.first ?? r.timestamp; s.last = r.timestamp; }
      if (r.type === 'assistant') {
        const u = r.message?.usage;
        if (u && r.requestId && !seenReq.has(r.requestId)) {
          seenReq.add(r.requestId); s.requests += 1;
          s.input += u.input_tokens || 0; s.cacheWrite += u.cache_creation_input_tokens || 0;
          s.cacheRead += u.cache_read_input_tokens || 0; s.output += u.output_tokens || 0;
        }
        for (const b of r.message?.content || []) {
          if (b.type !== 'tool_use') continue;
          const t = (s.tools[b.name] ??= { calls: 0, resultBytes: 0 }); t.calls += 1;
          nameOf.set(b.id, b.name);
          if (b.name === 'mcp__bantamkit__memory_save') s.memorySaves += 1;
          if (b.name === 'mcp__bantamkit__memory_recall') s.recalls += 1;
          if (b.name === 'Read' && b.input?.file_path) {
            const key = `${b.input.file_path}|${b.input.offset ?? ''}|${b.input.limit ?? ''}`;
            pendingRead.set(b.id, key);
          }
        }
      } else if (r.type === 'user') {
        for (const b of r.message?.content || []) {
          if (!b || b.type !== 'tool_result') continue;
          const bytes = Buffer.byteLength(typeof b.content === 'string' ? b.content : JSON.stringify(b.content ?? ''));
          const name = nameOf.get(b.tool_use_id) ?? null;
          const key = pendingRead.get(b.tool_use_id);
          if (key) {
            const n = (s.reads.get(key) || 0) + 1; s.reads.set(key, n);
            if (n > 1) { s.repeatReads += 1; s.repeatReadBytes += bytes; }
            (s.tools.Read ??= { calls: 0, resultBytes: 0 }).resultBytes += bytes;
          } else if (name && s.tools[name]) s.tools[name].resultBytes += bytes;
          else (s.tools['(unattributed)'] ??= { calls: 0, resultBytes: 0 }).resultBytes += bytes;
        }
      }
    }
  }
}

const rows = [...sessions.values()].filter((s) => s.requests > 0).sort((a, b) => (a.first || '').localeCompare(b.first || ''));
const tot = rows.reduce((t, s) => {
  for (const k of ['requests', 'input', 'cacheWrite', 'cacheRead', 'output', 'repeatReads', 'repeatReadBytes', 'memorySaves', 'recalls']) t[k] = (t[k] || 0) + s[k];
  for (const [n, v] of Object.entries(s.tools)) { const x = (t.tools[n] ??= { calls: 0, resultBytes: 0 }); x.calls += v.calls; x.resultBytes += v.resultBytes; }
  return t;
}, { tools: {} });
const est = (bytes) => Math.round(bytes / 4);

if (JSON_OUT) {
  console.log(JSON.stringify({ days: DAYS, sessions: rows.map((s) => ({ ...s, reads: undefined })), total: tot, tokensFromBytesAreEstimates: true }, null, 1));
  process.exit(0);
}
const k = (n) => (n / 1000).toFixed(1) + 'k';
console.log(`token ledger — ${rows.length} sessions, last ${DAYS} days, ${ALL ? 'all projects' : dirs[0]}`);
console.log('session   requests  input(fresh)  cache_write  cache_read   output   repeatReads(est tok)  saves recalls');
for (const s of rows) {
  console.log(`${s.session.slice(0, 8)}  ${String(s.requests).padStart(8)}  ${k(s.input).padStart(12)}  ${k(s.cacheWrite).padStart(11)}  ${k(s.cacheRead).padStart(10)}  ${k(s.output).padStart(7)}   ${String(s.repeatReads).padStart(4)} (${k(est(s.repeatReadBytes))})${' '.repeat(8)}${String(s.memorySaves).padStart(3)} ${String(s.recalls).padStart(6)}`);
}
console.log(`TOTAL     ${String(tot.requests).padStart(8)}  ${k(tot.input).padStart(12)}  ${k(tot.cacheWrite).padStart(11)}  ${k(tot.cacheRead).padStart(10)}  ${k(tot.output).padStart(7)}   ${String(tot.repeatReads).padStart(4)} (${k(est(tot.repeatReadBytes))})${' '.repeat(8)}${String(tot.memorySaves).padStart(3)} ${String(tot.recalls).padStart(6)}`);
const prompt = tot.input + tot.cacheWrite + tot.cacheRead;
console.log(`\nprompt tokens sent (real): ${k(prompt)} — cache_read ${(100 * tot.cacheRead / prompt).toFixed(1)}%, cache_write ${(100 * tot.cacheWrite / prompt).toFixed(1)}%, fresh ${(100 * tot.input / prompt).toFixed(1)}%`);
console.log(`repeated Read results: ${tot.repeatReads} calls, ${k(tot.repeatReadBytes)} B ≈ ${k(est(tot.repeatReadBytes))} tok est — the population the PreToolUse read gate refuses`);
console.log('\ntool                                   calls   result bytes   est tok');
for (const [n, v] of Object.entries(tot.tools).sort((a, b) => b[1].resultBytes - a[1].resultBytes).slice(0, 15)) {
  console.log(`${n.padEnd(38)} ${String(v.calls).padStart(6)}   ${k(v.resultBytes).padStart(12)}   ${k(est(v.resultBytes)).padStart(7)}`);
}
