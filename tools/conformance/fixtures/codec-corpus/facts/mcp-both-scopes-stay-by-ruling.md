---
name: mcp-both-scopes-stay-by-ruling
description: why bantamkit is registered at both user and project scope and must not
  be trimmed to one, and how to tell a live MCP connection from the build on disk
type: project
created: '2026-09-05'
last_recalled: '2026-09-18'
links:
- reference-two-bantamkit-mcp-builds
- project-build-identity-describes-disk-not-process
- skill-audit-built-three-designs-refuted
---

RULED by the user 2026-09-05: leave BOTH bantamkit MCP registrations in place. `claude mcp list` warns that the name resolves to two endpoints — user scope `tools/bantamkit-mcp-node` (Node) and project scope `tools/bantamkit-mcp` (Python, from the tracked `.mcp.json`) — and the warning is cosmetic here: probed by piping `tools/list` into each launcher, both advertise the same 11 tools.

DO NOT "clean up" the project scope. `.mcp.json` is tracked and was added deliberately by 927b2a8 to fix a measured failure: its `command` resolves against the PROJECT directory, so it exists in every checkout AND every git worktree, while the user-scope entry points at the main checkout only. Without it a subagent running in a worktree had NO bantamkit tools at all — and CLAUDE.md requires multi-unit work to be orchestrated through the `shiftwork_*` tools that registration serves. It also prevents a worse shape: the venv's editable install resolves `bantamkit` to the MAIN checkout, so a unit editing `runtime-py/src` in a worktree would be answered by somebody else's copy of the file it just changed.

A LIVE CONNECTION IS NOT THE BUILD ON DISK. The host learns the tool list when it connects, so a tool added mid-session is absent from the running connection even though a fresh launch serves it. `build_identity` does NOT settle this — it fingerprints the source on disk, so it reported `assets_files: 87` (skill_audit's asset included) while the live connection still offered ten tools. The evidence that answers the question is the tool list the host actually holds; the fix is `/mcp` -> reconnect, which is cheap and needs no restart.
