---
name: project-build-identity-describes-disk-not-process
description: build_identity reports the fingerprint of the source on disk, not the
  code actually executing, so a long-lived MCP server whose checkout moved under it
  reports a build_id it is not running
type: project
created: '2026-08-22'
last_recalled: '2026-09-15'
links: []
---

**Found 2026-08-22 by ordinary use, not by looking for it.** Candidate register
finding; not yet filed.

## The observation

PR #63 merged `DEFAULT_INDEX_BUDGET = 4096 → 24_000` to main (`4c04281`). After
the merge, a live `memory_save` through the running MCP server was still refused
with **"index is 4131 bytes, budget is 4096"** — twice.

- On disk: `runtime-py/src/bantamkit/memory/store.py:32` → `DEFAULT_INDEX_BUDGET = 24_000`,
  and importing it fresh reports `24000`.
- The running server: enforces **4096**.
- The running server's reported `code_digest`:
  `sha256:831bdb6be2b1da9e945cf2358fdb3f97f5973ad38bee97adc6dbeffea98609e2`, 23 files.
- `_code_fingerprint()` computed against the tree **right now (2026-09-11)**: the **same digest**,
  same 23 files.

Alternative explanation ruled out: no `--index-budget` appears in `.mcp.json`, in
`~/.claude.json`, or in the `tools/bantamkit-mcp` launcher, and `args` is `[]`. The
4096 can only be the old default baked into the running process at import time.

## The claim

`build_identity` re-reads the filesystem at call time, so `code_digest` and therefore
`build_id` describe **the bytes on disk**, not **the bytes that are executing**. A
long-lived server whose checkout moved under it reports the *new* fingerprint while
running the *old* code, and nothing in the answer says so.

## Why this matters more than a stale-process annoyance

It contradicts the function's own stated reason for refusing to report a commit
(`mcpserver.py:185-210`):

> an edited working copy serves different code under an unchanged sha, which is
> precisely the confusion RB-P84 filed. A commit reported that way would be a value
> that is sometimes a lie; `code_digest` is derived from the bytes themselves and
> cannot be.

`code_digest` **is** sometimes a lie, by the same mechanism the docstring names — it
just moves in the opposite direction (the sha stays still while code changes; here the
digest moves while code stays still). The tool exists so an agent holding a tool result
can ask which build produced it. In this state it answers with a build that did not
produce it.

## Practical consequence right now (2026-09-11)

The memory budget fix is **on main but not in effect**. It needs an MCP server restart.
Until then `memory_save` keeps refusing at 4096, and the store consolidation
(merged index measures 8863 B) cannot be validated through the MCP tools.

## Not yet established

- Whether `assets_digest` has the same property (probably — same call-time read).
- Whether a fix is even possible: the honest fingerprint would have to come from the
  imported modules (`sys.modules[...].__file__` bytes read at import, or a digest
  captured at startup), which is a different measurement, not a repair of this one.
- Whether any test covers "server started, source changed, identity asked".

Related: [[reference-two-bantamkit-mcp-builds]], [[project-windows-ci-measured-failures]].


## Second data point, 2026-08-22 — the digest moved twice while the process stood still

Probed rather than asserted, at the end of a long session:

    memory_save -> "memory index is 4135 bytes, budget is 4096: run compact()
                    or tersen descriptions. Nothing was saved..."

So the running server STILL enforces 4096, although `DEFAULT_INDEX_BUDGET = 24_000`
landed on main in #63 hours earlier. Meanwhile `build_identity` reports:

    earlier this session : code_digest sha256:831bdb6b...   (server enforced 4096)
    now                  : code_digest sha256:b9a90e6f...   (server enforces 4096)

**Two different fingerprints, one unchanged running process.** The digest moved
because `d19ac9e` and `059840c` changed `runtime-py/src/bantamkit` on disk; the
code answering the call never changed at all. `version` also still reads `0.25.0`,
so nothing in the response distinguishes the live process from the tree.

That is the exact inverse of the case the docstring refuses `git_commit` for. It
says a commit "would be a value that is sometimes a lie; `code_digest` is derived
from the bytes themselves and cannot be." It is derived from the bytes **on disk**,
which for a long-lived server are not the bytes that were imported. A sha that
stands still while code changes and a digest that moves while code stands still are
the same defect from opposite ends.

**Practical consequence, unchanged and now doubly evidenced:** memory consolidation
([[project-memory-consolidation-ruling]]) cannot proceed. Its precondition is the
24000 budget, and at a live 4096 the merged 8863 B index would make the first
`save()` raise while `compact()` renames ~24 facts into `archive/`. The refusal
above is structured and safe — nothing was written — but the remedy it suggests
(`compact()`) is the destructive one the ruling exists to avoid. **The fix is an MCP
server restart, which the agent cannot perform.**
