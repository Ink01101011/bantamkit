#!/usr/bin/env node
// Register (or remove) the bantamkit hook adapter in `~/.claude/settings.json`, user scope.
//
//   node tools/hooks/install.mjs            # add / refresh the six entries
//   node tools/hooks/install.mjs --remove   # take them out again, nothing else touched
//
// Idempotent: every existing entry whose command mentions `bantamkit-hook` is replaced, every
// other hook the operator has is left byte-for-byte. Writes an absolute path to THIS checkout,
// so a second checkout registers a second path — same rule as `claude mcp add` with an
// absolute launcher. Pure Node; works on Windows (the command is `node <abs path>`).

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HOOK = path.join(HERE, 'bantamkit-hook.mjs');
const SETTINGS = path.join(os.homedir(), '.claude', 'settings.json');
const remove = process.argv.includes('--remove');

const ENTRIES = [
  ['SessionStart', 'startup|resume|clear|compact'],
  ['UserPromptSubmit', null],
  ['PreToolUse', 'Read'],
  // MATCHER-LESS, and it must stay that way: the PostToolUse arm logs a usage event for
  // EVERY tool call and then runs the memory_save half only when the tool was that one.
  // A second, narrower entry beside this one would fire the save half twice.
  ['PostToolUse', null],
  ['PreCompact', null],
  ['PostCompact', null],
  ['Stop', null],
];

let settings = {};
try { settings = JSON.parse(fs.readFileSync(SETTINGS, 'utf8')); } catch { /* fresh file */ }
const hooks = settings.hooks ?? (settings.hooks = {});
const isOurs = (entry) => JSON.stringify(entry).includes('bantamkit-hook');

for (const [event, matcher] of ENTRIES) {
  const kept = (hooks[event] ?? []).filter((e) => !isOurs(e));
  if (!remove) {
    const entry = { hooks: [{ type: 'command', command: `node ${JSON.stringify(HOOK).slice(1, -1)}`, timeout: 10 }] };
    if (matcher) entry.matcher = matcher;
    kept.push(entry);
  }
  if (kept.length) hooks[event] = kept; else delete hooks[event];
}

fs.mkdirSync(path.dirname(SETTINGS), { recursive: true });
fs.writeFileSync(SETTINGS, JSON.stringify(settings, null, 2) + '\n');
console.log(`${remove ? 'removed' : 'registered'} bantamkit hooks in ${SETTINGS}`);
for (const [event] of ENTRIES) console.log(`  ${event}: ${(hooks[event] ?? []).filter(isOurs).length ? 'on' : 'off'}`);
console.log('restart Claude Code (or /hooks) for the change to load; log: ~/.bantamkit/hooks/hook-log.jsonl');
