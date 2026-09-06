# U7 — correction to (z)'s "lands on top of the link" prediction

`docs/roadmap-toolbox.md` row 8, (z), predicts `restore`'s forward move "lands on top
of the link" the way `archive`'s did before `d239480`, by analogy: "the same guard hole
`archive`'s dangling-symlink fix closed, one directory over."

**Measured on `runtime-py` at the point U7 first implemented (z): the prediction does
not hold, for a reason specific to `restore` and absent from `archive`.**

`restore`'s destination guard is `_reachable(destination, ...)`, which is
`Path.exists()` and follows symlinks — so a dangling symlink at `facts/<name>.md`
reports absent, exactly as predicted, and the "already live" refusal is skipped.
But `restore`, unlike `archive`, pre-reads the *entire* `facts/` directory with
`_facts()` **before** the forward move (its own docstring: "a read that makes the
move never happen"). That pre-read's listing (`_listing`, `os.scandir` + `fnmatch`)
matches the dangling symlink's name against `*.md` and includes it regardless of what
it resolves to; `_facts()` then calls `path.read_text()` on that same entry and raises
a bare `FileNotFoundError` — three lines before `source.replace(destination)` (nee
`source.rename(destination)`) is ever reached.

So on `runtime-py` as first fixed, the forward move never met the occupied entry at
all: the pre-read intercepted it one syscall earlier and by a different door. The
`rename` → `replace` conversion made alongside this reading had no state on this
codebase that demonstrated it RED — it belonged in the same "no state tells the two
calls apart" bucket `d239480` already puts the two rollbacks in (`docs/porting.md`
line ~370), once actually measured instead of assumed by symmetry with `archive`.

**Since superseded by a second finding, from the coordinator's parity check
(2026-09-06):** `runtime-ts`, built from the same register entry independently by U8,
added its own `lexists` check at the guard and refused with "already live" — which
this note's author agrees is also inaccurate (a dangling link is precisely a fact that
is not live) — while `runtime-py` was still answering the incidental `FileNotFoundError`
dressed up as "a filesystem error stopped the move" (also inaccurate: no move was
attempted). Two runtimes, two different reasons, two different sentences — a parity
break. Resolved by widening `restore`'s destination guard to check `os.path.lexists`
explicitly and refuse **before** `_facts()`'s pre-read ever runs, with a new sentence
naming what is actually there:

    facts/<name>.md already exists but cannot be read as a fact; refusing to restore over it

This IS now a deliberate, guarded refusal on `runtime-py`, reachable and demonstrated
(`test_restore_refuses_a_dangling_symlink_destination_instead_of_crashing_on_it`,
`runtime-py/tests/test_memory.py`). `runtime-ts` is to mirror this exact sentence
(U8, coordinated 2026-09-06) rather than keep "already live".

**Net correction to (z):** the "lands on top of the link" mechanism the entry predicts
was never the reachable one for `restore` on `runtime-py` — the guard's blind spot is
real, but what met it first was `_facts()`'s pre-read, not the move. `archive` is
unaffected: its own destination guard has no pre-read ahead of it, `Path.replace`
still silently replaces a dangling symlink there, on the terms review round 5 and
`d239480` already set, and this fix does not touch `archive`
(`test_archive_still_replaces_a_dangling_symlink_after_the_restore_guard_change`).

Filed here per the coordinator's instruction rather than edited into
`docs/roadmap-toolbox.md` directly — that file was amended concurrently for a
different reason while this unit was running, and U15 owns its register closes.

— U7, 2026-09-06
