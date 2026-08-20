# `mcpdrift` — the state it found, and the disagreements it was shown firing on

**2026-08-21. Every figure here was measured at `9a7b886` with the checker as committed
in this branch.** The rule is `docs/mcp.md#one-name-two-endpoints`; the mechanism is
`tools/mcpdrift/mcpdrift.py`; the logic guard is `runtime-py/tests/test_mcpdrift.py`.
This file is a record. It is amend-only (`tools/amendguard/ledger.json` →
`docs/eval-data/*.md`).

Nothing under `~/.local/share/bantamkit/` was modified, `~/.claude.json` and `.mcp.json`
were not modified, no `git tag`, no live model call. The two throwaway venvs below were
built from the LOCAL git object store (`git+file://`), never over the network, and live
in a scratch directory outside the repository.

## 1. The state today

```
$ cd /Users/kktest/Documents/Claude/Projects/bantamkit
$ python tools/mcpdrift/mcpdrift.py check
VERDICT AGREE  endpoints=2
  endpoint user:/Users/kktest/.local/share/bantamkit/venv/bin/bantamkit-mcp
    version '0.25.0'
    recall(k=1) returned 3 fact(s)
  endpoint project:/Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/bantamkit-mcp
    version '0.25.0'
    recall(k=1) returned 3 fact(s)
$ echo $?
0
```

**18 surfaces compared per endpoint, 0 differing** (`--json` → `len(surfaces)` = 18,
`differing` = `[]`): `server_name`, `server_version`, `capabilities`, `instructions`,
`tool_names`, six `tool_schema[…]`, six `behaviour[…]`, and
`behaviour[recall_k1_fact_count]`.

This is also the run that doubles as the **null control**, and it is a real one rather
than a self-comparison: the two endpoints are separate virtual environments, installed by
different mechanisms — user scope is a non-editable wheel install from a git ref, project
scope is an editable `.pth` install serving `runtime-py/src` — and the checker calls them
identical. A checker that were merely always-red could not produce this row.

`AGREE` today is a statement about today. The user-scope install is **pinned** to whatever
`main` was when it was installed; the project-scope `.venv` is **editable** and tracks
HEAD. They agree because the user-scope install was refreshed on 2026-08-20, hours before
this measurement, and they will drift again on the next merge to `main`.

## 2. CAL-1 — the real stale build (`v0.13.0`, `9436cf7`)

The build that was live under this name for eleven days, rebuilt from the local object
store into a throwaway venv:

```
$ python -m venv /tmp/stale-venv
$ /tmp/stale-venv/bin/pip install \
    "bantamkit[mcp] @ git+file:///Users/kktest/Documents/Claude/Projects/bantamkit@v0.13.0#subdirectory=runtime-py"
$ python tools/mcpdrift/mcpdrift.py check \
    --endpoint "head=<repo>/.venv/bin/bantamkit-mcp" \
    --endpoint "stale-v0.13.0=/tmp/stale-venv/bin/bantamkit-mcp"
VERDICT DIFFER  endpoints=2
  head            version '0.25.0'   recall(k=1) returned 3 fact(s)
  stale-v0.13.0   version '0.13.0'   recall(k=1) returned 1 fact(s)
  DIFFERING SURFACES (3):
    server_version                 0.25.0 / 0.13.0
    behaviour[recall_k1]           45b825775848 / 8fd4b3d69c39
    behaviour[recall_k1_fact_count]  3 / 1
$ echo $?
1
```

**Three of eighteen surfaces differ across twelve minor versions, and that is the
finding.** `instructions`, every `tool_schema`, `capabilities`, `tool_names`, the
`validate_json` contract wording, the `shiftwork_status` answer and the SDK's
wrong-argument-type error are all **byte-identical** between `v0.13.0` and `v0.25.0`.
This corroborates `RB-P84`'s independently measured 6864 identical protocol bytes and
sharpens it: after the version string, the `RB-P1` k-floor is the *only* thing that
distinguishes the two builds on any surface probed here.

## 3. CAL-2 — the decisive one: same version string, different build

`RB-P45` is the reason CAL-1 is not sufficient. The version string has lied here before,
so a checker that would only have caught CAL-1 has caught nothing durable. This arm holds
`__version__` fixed at `0.25.0` and reverts the `RB-P1` k-floor alone:

```
$ git archive HEAD | tar -x -C /tmp/mutant-src            # HEAD source, untouched tree
$ # in /tmp/mutant-src/runtime-py/src/bantamkit/memory/component.py, one line:
$ #   -  budget = self.k if k is None else max(k, self.k)
$ #   +  budget = self.k if k is None else k          # MUTANT: k-floor reverted
$ /tmp/mutant-venv/bin/pip install "/tmp/mutant-src/runtime-py[mcp]"
$ /tmp/mutant-venv/bin/python -c "import bantamkit; print(bantamkit.__version__)"
0.25.0

$ python tools/mcpdrift/mcpdrift.py check \
    --endpoint "head=<repo>/.venv/bin/bantamkit-mcp" \
    --endpoint "mutant-same-version=/tmp/mutant-venv/bin/bantamkit-mcp"
VERDICT DIFFER  endpoints=2
  head                  version '0.25.0'   recall(k=1) returned 3 fact(s)
  mutant-same-version   version '0.25.0'   recall(k=1) returned 1 fact(s)
  DIFFERING SURFACES (2):
    behaviour[recall_k1]
    behaviour[recall_k1_fact_count]    3 / 1
$ echo $?
1
```

**Both endpoints advertise `0.25.0`; the checker is red anyway, and `server_version` is
not among the surfaces that made it red.** That property is pinned in CI without any of
these venvs by `test_a_behavioural_difference_under_one_version_string_is_red`.

## 4. The checker's own guard, and what fires it

`runtime-py/tests/test_mcpdrift.py` — 16 nodes, all over synthetic MCP servers the test
file writes and executes, none reading `~/.claude.json`, none asserting a version any
endpoint on this machine reports. Five mutations of the checker were applied and reverted
one at a time at `9a7b886`; each turned nodes red, so no node here is decorative:

| mutation to `tools/mcpdrift/mcpdrift.py` | red |
|---|---|
| compare only `server_version` | 5 |
| empty discovery returns `AGREE` instead of `UNDETERMINED` | 1 |
| a failed handshake is not treated as `ERROR` | 2 |
| the child inherits `BANTAMKIT_ASSETS` and the real `HOME` | 1 |
| the fixture is seeded with fewer facts than the recall floor | 2 |

## 5. What the checker found that was not being looked for

Run from a **git worktree** of this repository, `mcpdrift check` exits `2 ERROR`:

```
cannot launch .venv/bin/bantamkit-mcp: [Errno 2] No such file or directory
```

The tracked `.mcp.json` carries a **relative** command, `.venv/bin/bantamkit-mcp`, which
is resolved against the project directory. A worktree has no `.venv`, so the
project-scope endpoint does not exist there — and the client agrees. `claude mcp list`
from the worktree at `9a7b886`:

```
bantamkit: .venv/bin/bantamkit-mcp  - ✘ Failed to connect — ENOENT: ENOENT: no such
file or directory, posix_spawn '.venv/bin/bantamkit-mcp'
[Conflicting scopes]
├ Server "bantamkit" is defined in multiple scopes with different endpoints: user
  (/Users/kktest/.local/share/bantamkit/venv/bin/bantamkit-mcp), project
  (.venv/bin/bantamkit-mcp).
```

From the canonical checkout the same row reads `✔ Connected`. So the project scope wins
the name in both places, and in a worktree the thing it wins with is not there.
**Not fixed here** — it is a change to a tracked config file with consequences for every
other checkout, and this unit's mandate was the detector. It is written up for the
register in the hand-back.
