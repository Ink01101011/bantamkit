# The pinning number, re-measured after the counter got honest

**Measured 2026-08-14 (L6).** Harness: `tools/pinharness/pinned.py`, ledger
`tools/pinharness/contract-ledger.json`, calibration
`tools/pinharness/calibration-head.json`. Layer: Measurement.

## The number that is withdrawn

**`31/31` is withdrawn and is not cited anywhere.** It was produced by a harness
whose whole verdict was `pinned = rc != 0`, which relates no claim to its
mutation and no killer to its claim. Reproduced by hand, not argued: on that
harness a claim reading *"every summary a run writes states the current phase of
the moon, and the phase is read from an ephemeris"* — a feature that does not
exist — with a mutation that breaks an `import`, measured **PINNED,
behaviour-pinned 1/1 (100%)**, with a killed-by of `nothing` on the same row.
`31/31` meant "31 hand-written mutations each turned **≥ 0** nodes red".
Detail: `2026-08-14-pinning-harness-false-positives.md`.

## What was measured instead

| sweep | ledger | result |
|---|---|---|
| `3070d9c`, first sweep under the fixed harness | the same **31** claims, `pins` written from each claim's SUBJECT | **PINNED 30, FALSE-PINNED 1, UNPINNED 0, BROKEN 0** — 30/31 |
| `8cd6078` (HEAD) | **34** claims: N11, N12, N13 added by this unit | **PINNED 34, FALSE-PINNED 0, UNPINNED 0, BROKEN 0** — behaviour 29/29, prose 5/5 |

**The number dropped, and then it came back, and the second half of that sentence
is the weaker claim of the two.** What dropped was real: `B16` read FALSE-PINNED.
What brought it back was **not** a re-scoping of `B16` — it was inspection.
`B16`'s only killer was `test_every_shape_rule_flag_is_the_usage_status_in_the_field`,
whose `_world_rule_field_cases` carries `--rubric a=<a path that is not there>` as
its load-bearing member and whose docstring cites K4's I4, which is `B16`'s own
committed note. That node is entitled to pin `B16` and the first pin list simply
did not list it. The correction is recorded in the claim's note rather than made
silently.

**And that is exactly the loophole this instrument still has.** `pins` is chosen
by the author, and nothing stops an author reading the killers first and writing
them in. `B16` is a documented instance of the discipline being applied *after*
the measurement, defensible on the node's own docstring and no stronger than
that. **So `34/34` should be read as "34 mutations each turned a node the claim
named red, with the naming done by hand" — not as a fact about coverage.** The
attack direction is in `2026-08-14-pinning-harness-false-positives.md`: derive
`pins` mechanically from the section a node lives in and the problem id its
docstring cites, so the author does not get to choose.

## What the new column shows

`of which NAMED` is the count of a mutation's killers that the claim named, over
the total that went red. It is the number the old harness threw away:

| claim | named / total killers | reading |
|---|---|---|
| `N01` | **1 / 8** | eight nodes notice a constant `effect`; exactly one of them runs outside pytest, and only that one is entitled to pin the acceptance |
| `N02` | 1 / 3 | same |
| `N03` | 1 / 4 | same |
| `B10` | 1 / 6 | five of the six killers are about neighbouring rungs of the status ladder |
| `B05` | 8 / 8 | the codec arm is named by everything that catches it |

The three ACCEPTANCE claims name **only** their out-of-process node, on purpose.
RB-P28 is open, and the in-process nodes are measurably green under a patch that
reverts the fix in the field — see
`2026-08-14-rbp28-acceptance-pins-outside-pytest.md`. Under the old rule each of
those three would have counted a kill by any of its 3–8 in-process guards, which
is precisely the reading that made the fix-nothing patch invisible.

## Calibration at HEAD, which is a separate instrument reading

`calibration.json` calibrates at `3981efd` and has **stopped calibrating at
HEAD**: `CAL-GREEN` was consumed by the fix it was a control for and now reads
PINNED there, leaving a positive control and no negative one. An instrument with
only a positive control cannot distinguish "everything is pinned" from "the
detector is stuck on". `calibration-head.json` is the pair that works at HEAD:

| id | expected | measured |
|---|---|---|
| `CAL-HEAD-RED` — the guard arm stops reporting the guard status | PINNED | **PINNED** |
| `CAL-HEAD-GREEN` — a MEASURED FACT reversed inside a docstring | UNPINNED | **UNPINNED** |

Both known answers came back. That is what licenses reading the `34/34` above at
all, and a `--out` run that flips either exits non-zero.

## Three findings this sweep produced, filed and not fixed

1. **The exit-status contract's status VALUES are not pinned.** Mutating
   `GUARD_VIOLATION_EXIT = 3` to `7` leaves 797 of 799 nodes green. Every node
   that names the status names the **constant**, so it moves with it, and the
   epilog renders it through an f-string so the prose moves too. The only two
   nodes that notice are the two RB-P28 probes added today, which happen to
   assert `status in (0, 3)` with a literal. Committed evidence and CI jobs mean
   **3**. Attack direction: assert the literal values in
   `test_the_guard_status_is_distinct_from_the_refusal_and_the_usage_status`, and
   field-check the number against what the committed records carry.
2. **`pins` can be named after the measurement.** Above, and in the
   false-positives record.
3. **A pin named as a family prefix** (`test_closed_pipe_`, five nodes) counts a
   kill by any member. Deliberate where the family is one claim; a loophole where
   it is not.
