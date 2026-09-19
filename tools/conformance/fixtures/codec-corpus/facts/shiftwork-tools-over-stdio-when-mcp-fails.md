---
name: shiftwork-tools-over-stdio-when-mcp-fails
description: bantamkit MCP shows as failed to connect at session start but the shiftwork
  policy still has to run - drive the real tools over stdio instead of abandoning
  the protocol
type: reference
created: '2026-09-18'
last_recalled: null
links:
- feedback-clock-in-before-spawning-not-after
- mcp-endpoints-npm-except-the-repo
- reference-two-bantamkit-mcp-builds
---

When a Claude Code session reports `bantamkit` in the failed-to-connect list, the server itself is usually fine: `printf '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' | /Users/kktest/Documents/Claude/Projects/bantamkit/tools/bantamkit-mcp-node` answers with serverInfo 0.34.2. The failure is the host's launch, not the binary, and `claude mcp list` can show it Connected at the same time.

There is NO CLI for shiftwork - `bantamkit-mcp --help` lists only --assets-root/--mcp-report/--statusline/--update/--install/--store/--start. So the only way to honour the CLAUDE.md shift-work policy in such a session is to speak MCP stdio yourself: spawn the launcher, send initialize + notifications/initialized + tools/call, read the line whose id matches. A ~30-line node script does it; shiftwork state lives in the checkpoint file on disk, so a fresh process per call is correct and stateless.

This matters because the policy is not optional and the alternative - spawning agents unclocked - is the exact failure [[feedback-clock-in-before-spawning-not-after]] was written about. Also confirmed in passing: bantamkit is defined in three scopes on this machine (user npx, project tools/bantamkit-mcp, local tools/bantamkit-mcp-node), see [[mcp-endpoints-npm-except-the-repo]].
