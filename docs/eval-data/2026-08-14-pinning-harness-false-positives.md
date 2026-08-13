# The pinning harness certified claims it never checked

**Measured 2026-08-14 (L6).** Ledger:
`tools/pinharness/false-pinning-reproduction.json`, committed beside the harness.
Layer: Measurement.

**AN INSTRUMENT THAT GRADES EVIDENCE MAY NOT GRADE ITSELF**, so this is the
instrument measured against answers known by hand, exactly as `calibration.json`
is. It is not part of any pinning number.

## What was wrong

`pinned.py:216` was `pinned = rc != 0`. That relates no claim to its mutation and
no killer to its claim, so two whole classes of nothing read as PINNED.

## The three claims

| id | what it is | what it should read |
|---|---|---|
| `ZZMOON` | *"every summary a run writes states the current phase of the moon, and the phase is read from an ephemeris"* — a feature that does not exist — with a mutation that breaks an `import` | not a PINNED |
| `ZZCROSS` | a real sentence, cited for **RB-P18**, whose mutation lands in **RB-P16**'s `format_table` | not a PINNED |
| `ZZCTRL` | control: a real RB-P18 claim with a real RB-P18 mutation | PINNED, or this file measures nothing |

## Result

| harness | ZZMOON | ZZCROSS | ZZCTRL | headline |
|---|---|---|---|---|
| `993b680` (pre-fix) | **PINNED**, killed by `nothing` | **PINNED** | PINNED | **behaviour-pinned 3/3 (100%)** |
| this fix | **BROKEN** | **FALSE-PINNED** | PINNED | behaviour-pinned 1/3 (33%), rc 1 |

`ZZCROSS`'s four killers under the fixed harness, none of them a node it named:

    test_the_rbp16_additions_the_floor_strips_are_present_and_loaded
    test_a_fresh_runs_verdict_carries_its_effect_size_in_the_summary_and_in_the_table
    test_an_indistinguishable_cell_reports_the_points_the_two_variants_disagree_on
    test_OUTSIDE_pytest_a_fresh_runs_verdict_carries_its_effect_size

All four are RB-P16 nodes. `0/4` named. The old harness printed `PINNED` for
RB-P18 on that row.

`ZZMOON`'s mutation gives `rc != 0` with **zero `FAILED` lines** — a tree that
does not collect. The old harness printed `PINNED` and a killed-by of `nothing`
**on the same row**, which is the reading a human would have caught and the
number never did.

## The four verdicts that replaced the two

- **PINNED** — a node this claim NAMED went red. Narrower than "something went red".
- **FALSE-PINNED** — nodes went red and not one of them is named. The claim is not pinned.
- **UNPINNED** — nothing went red.
- **BROKEN** — the tree did not collect. Not evidence about anything; exits non-zero.

Every claim now carries `pins`, and every `pins` entry is checked against the
node ids the unmutated tree actually collects before any result is believed — a
renamed test would otherwise turn a whole ledger FALSE-PINNED for the wrong
reason.

**Running this file exits 1 on purpose**: `ZZMOON` is a broken mutation, and a
broken mutation is a hard error whichever ledger it appears in.

## What this does not fix, filed rather than closed

`pins` is checked as a **substring** of a failing node id, and it is chosen by
the person writing the claim. Two failure modes remain open:

1. **A pin named too widely** (`test_closed_pipe_` covers five nodes) counts a
   kill by any of them. That is deliberate for a family that is one claim, and it
   is a loophole for a claim that names a family it does not own.
2. **A pin named after the fact.** Nothing here stops an author from measuring
   the killers first and then writing them into `pins`. The check is only as good
   as the discipline of naming the nodes from the claim's SUBJECT. The attack
   direction: derive `pins` mechanically — e.g. from the section a node lives in
   and the problem id its docstring cites — so the author does not get to choose.
