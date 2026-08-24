#!/bin/sh
# The Claude Code `statusLine` adapter. Contract: `docs/statusline.md`.
#
# CLAUDE CODE ONLY. `statusLine` is a key in `~/.claude/settings.json`; Claude Desktop, the
# Copilot CLI and both VS Code extensions have no such surface. This is not a sixth host and
# it does not generalise.
#
# WHAT THE HOST DOES WITH THIS. It runs the command on its own redraw path, pipes a JSON
# object describing the session on stdin, and renders the FIRST line of stdout in the bar.
# So three things are true at once and all three are properties, not preferences:
#
#   1. IT MUST BE CHEAP. It never starts an MCP server, never opens a transport and never
#      builds a memory store. It reads at most one file: bantamkit's own event log.
#   2. IT MUST NEVER FAIL LOUDLY. No traceback, no stderr, no empty line -- an empty line
#      makes the bar flicker between one row and none. Every arm below ends in one line on
#      stdout and `exit 0`. UNKNOWN IS A STATE TO RENDER, NOT AN ERROR TO RAISE.
#   3. THE HOST'S STDIN IS UNTRUSTED AND IS NEVER PARSED. It is drained to `/dev/null` and
#      nothing from it reaches the runtime, so no host text can appear in the rendered line.
#      This is the same rule `docs/mcpreport.md` is under, and for the same measured reason:
#      the host has already persisted an argument value to disk inside an exception string.
#
# WHY THERE IS A WRAPPER AT ALL, AND WHY IT IS NOT REGISTERED AS `node .../cli.js`.
# `runtime-ts/dist/` is BUILD OUTPUT and is gitignored, so a fresh clone, a fresh worktree
# and one `rm -rf runtime-ts/dist` all produce a registration pointing at a file that is not
# there. Node answers that with `ERR_MODULE_NOT_FOUND` and a stack trace on stderr -- which
# is exactly the shape job39 measured on the packaged `bin` and exactly what a redraw path
# must not reproduce. Every failure here renders instead.
#
# WHICH RUNTIME IT SHELLS, AND WHY THAT DOES NOT BREAK THE PURE-NODE RULING. It shells NODE,
# never Python. `runtime-ts` is the shipped product and `bantamkit-mcp --statusline` is a
# flag on the single bin `package.json` declares, so an operator with nothing but
# `npx bantamkit-mcp` installed can register exactly the same surface. The Python half
# exists and is byte-identical -- `tools/conformance/suites/statusline.mjs` runs both as
# processes and compares them -- but nothing at runtime here needs it.
#
# POSIX `sh` only. On Windows use `bantamkit-statusline.cmd` beside this file.

set -u

# The unknown state, spelled here as well as in both runtimes ON PURPOSE. This arm is
# reached exactly when the runtime could not be asked at all, so it cannot come from the
# runtime. It is the same three-token shape `render()` produces so the bar never changes
# grammar: name, state, separator, reason.
UNAVAILABLE='bantamkit Unknown ⚪ · statusline adapter unavailable'

render() {
    printf '%s\n' "$1"
    exit 0
}

# THE HOST'S PAYLOAD, DRAINED. Not read, not parsed, not passed on. Draining rather than
# ignoring keeps the host from seeing EPIPE on a bar redraw. The `-t 0` guard is not
# cosmetic: without it, running this by hand in a terminal blocks forever on a `cat` waiting
# for a payload no person is going to type.
[ -t 0 ] || cat >/dev/null 2>&1

# `$0`'s grandparent -- the checkout this adapter was registered out of, so a worktree's
# registration answers from the worktree. Same rule as `tools/bantamkit-mcp-node`.
here=$(CDPATH= cd -- "$(dirname -- "$0")/../.." 2>/dev/null && pwd) || render "$UNAVAILABLE"

cli="$here/runtime-ts/dist/cli.js"
[ -f "$cli" ] || render "$UNAVAILABLE"

command -v node >/dev/null 2>&1 || render "$UNAVAILABLE"

# stderr to /dev/null is belt AND braces: `--statusline` is total and writes none, and if a
# future change ever makes it write some, the bar still must not show it.
line=$(node "$cli" --statusline 2>/dev/null) || line=''

# An empty stdout is a failure the exit status did not report -- a killed process, a build
# that loaded and printed nothing. It renders as unavailable rather than as a blank bar.
[ -n "$line" ] || render "$UNAVAILABLE"

render "$line"
