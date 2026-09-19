---
name: reference-two-bantamkit-mcp-builds
description: two bantamkit MCP servers under one name - which venv answers, why the
  version string lies, and why a worktree gets neither
type: reference
created: '2026-08-22'
last_recalled: '2026-09-11'
links:
- project-bantamkit-program-backlog
- reference-rbp53-silent-window-clamp
- project-shift-2026-08-19-night
---

Two `bantamkit` MCP servers are registered under one name on this machine: user
scope at ~/.local/share/bantamkit/venv/bin/bantamkit-mcp (named by
~/.claude.json, installed 2026-08-10), project scope at .venv/bin/bantamkit-mcp
(named by the repo's TRACKED .mcp.json). Both are live child processes of the
same client. `claude mcp list` prints [Conflicting scopes] and PROJECT SCOPE WINS
THE NAME.

CURRENT STATE (2026-08-21): both builds are at 0.25.0 and both return 3 facts for
recall(k=1). The earlier claim that the repo build advertises 0.3.0 is STALE - PR
#41 fixed it.

DATED CORRECTION, measured 2026-08-19 against real stdio `initialize` handshakes,
before PR #41. Superseded by the line above, kept because it is the evidence that
the version field cannot be trusted:
- The user-scope install was bantamkit 0.13.0; the project-scope build was running
  v0.25.0 source.
- THE VERSION FIELD WAS INVERTED. The 0.13.0 install truthfully advertised
  `0.13.0`; the build running v0.25.0 source advertised `0.3.0`, because `.venv`
  is an EDITABLE install whose `dist-info` was written 2026-08-08 and never
  rewritten while the code kept tracking HEAD.
- `tools/list`, `instructions` and every asset behind both resource templates were
  BYTE-IDENTICAL. Only a defect separated them: `memory_recall(k=1)` returned at
  most 1 fact on 0.13.0 and up to 3 on HEAD (the RB-P1 k-floor fix). A live k=1
  call in the repo returned 2 facts, unreachable for 0.13.0, so the repo's
  project-scope server answered there - consistent with
  `.claude/settings.local.json` carrying `enabledMcpjsonServers: ["bantamkit"]`.
- At that date, which scope wins IN GENERAL was recorded as UNESTABLISHED:
  `claude mcp list` printed the user-scope path while emitting [Conflicting
  scopes]. The 2026-08-21 reading above supersedes it, but both readings come from
  the same ambiguous output, so treat "project scope wins" as a reading and not a
  guarantee.

DO NOT DISCRIMINATE ON THE VERSION STRING. It has lied once already in this
program (a v0.25.0 build advertised 0.3.0). Across twelve minor versions only 3 of
18 probed surfaces differ - after the version string, the RB-P1 k-floor defect is
the only discriminator on any surface probed.

HOW TO CHECK, don't guess:
  .venv/bin/python tools/mcpdrift/mcpdrift.py check
Exit 0 AGREE / 0 SINGLE / 1 DIFFER / 2 ERROR / 3 UNDETERMINED. UNDETERMINED is
deliberately NOT the same as AGREE.

ORDERING MATTERS IF THIS IS EVER FIXED: refresh both builds BEFORE resolving the
scope collision. `claude mcp remove bantamkit -s project` edits a tracked file
and, done first, hands the bantamkit repo's orchestration to the stale user-scope
build. As of 2026-08-19 sessions with cwds outside the repo ran the 0.13.0 build
and the k-floor defect was live for them; the 2026-08-21 reading has both builds
at 0.25.0, so that specific exposure is closed - the ordering rule is not.

WORKTREE TRAP (RB-P96): .mcp.json is TRACKED and the command is RELATIVE, so a git
worktree has no .venv and the project-scope endpoint does not exist there.
`claude mcp list` from a worktree reads "Failed to connect - ENOENT posix_spawn",
from the canonical checkout "Connected", same row. [Conflicting scopes] prints in
BOTH and says nothing about which is reachable. So a subagent working in a
worktree may have NO bantamkit MCP tools at all.

Reinstall path that works:
  git+https://github.com/Ink01101011/bantamkit@main#subdirectory=runtime-py

Links: [[project-bantamkit-program-backlog]], [[reference-rbp53-silent-window-clamp]], [[project-shift-2026-08-19-night]].
