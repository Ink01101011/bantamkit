---
name: project-backlog-public-install-for-mcp
description: CLOSED 2026-09-05 - bantamkit is installable from npm and PyPI, the host
  configs are documented, and what the recommendation got wrong
type: project
created: '2026-08-21'
last_recalled: '2026-09-15'
links:
- npm-publish-0-26-0-blocked-on-login
- every-change-ships-to-npm-not-just-to-main
- public-install-is-pure-node-by-ruling
- merge-authorized-standing-tag-withheld
---

**CLOSED 2026-09-05.** Requested 2026-08-21: *"ทำให้ mcp สามารถ install ผ่าน npx/npm หรือ package management ตัวสาธารณะด้วย เพื่อให้สามารถเอาไปใช้กับ copilot/claude หรืออื่นๆได้"*. Both halves are live.

- **npm** `bantamkit-mcp` — 0.26.0 then 0.27.0. Pure Node, one dependency, no Python.
- **PyPI** `bantamkit` — 0.27.0, first ever Python release.

Both were installed cold from their public registry after publishing and both serve 11 tools reporting the right version. `npx -y bantamkit-mcp` and `pipx run --spec "bantamkit[mcp]" bantamkit-mcp` are the two one-liners.

**The 2026-08-21 recommendation was wrong on order and on mechanism.** It argued PyPI first, then an npm launcher shim over it. What actually shipped is two INDEPENDENT implementations — `runtime-ts` is a real Node server, not a wrapper that bootstraps Python — so there is no shim to keep in sync and no bootstrap that can fail on a machine without a suitable interpreter. The npm side went first because it was the one that existed.

**What the backlog never mentioned and turned out to matter most: a package page is not the same as an installable package.** `runtime-py` had no README and `pyproject.toml` declared no `readme`, so the first PyPI release would have had a permanently blank project page — PyPI writes that page once per version and never allows a re-upload. Caught by `twine check`'s `long_description missing` warning BEFORE publishing, which is the only reason 0.27.0 has a page at all.

**Host configuration is the other half of "usable by copilot/claude", and it is now documented per host** in all three READMEs: Claude Code (`claude mcp add bantamkit -s user -- npx -y bantamkit-mcp`), Claude Desktop (`claude_desktop_config.json`, key `mcpServers`), GitHub Copilot in VS Code (`.vscode/mcp.json`, key **`servers`**), Cursor (`.cursor/mcp.json`, key `mcpServers`). The key differs only in VS Code and that is the detail worth remembering.

**Blockers listed in 2026-08-21 and how each resolved:** names were free on both indexes; the sdist→wheel round trip was already gated by `test_packaging.py`; the RB-P45 two-installs hazard is unaddressed and still real for anyone installing both halves; cross-platform is unchanged — the media route stays macOS-only and refuses by name elsewhere.
