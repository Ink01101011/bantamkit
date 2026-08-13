# What fraction of the exit-status contract is actually PINNED — measured either side of K5

**Job:** `rbp31-rbp32-status-truth`, units K5 + orchestrator. **Layer:** Measurement.
**Instrument:** `tools/pinharness/pinned.py` with `tools/pinharness/contract-ledger.json`.
**Measured:** 2026-08-13 on this machine (darwin 25.5.0, CPython 3.12.13, APFS).

A claim is **PINNED when a mutation that makes it false turns at least one node red.**
Anything else is a sentence the suite would keep green while it became a lie. The
numbers are reported in two groups on purpose: **behaviour-pinned** (the claim is about
what the tool DOES) is the number that matters; **prose-pinned** (deleting or reversing
the committed SENTENCE is caught) is weaker, because a prose guard can be green while the
behaviour it describes is broken — K4 demonstrated exactly that.

Re-run, from the repo root:

```sh
.venv/bin/python tools/pinharness/pinned.py . 3981efd tools/pinharness/calibration.json
.venv/bin/python tools/pinharness/pinned.py . HEAD tools/pinharness/contract-ledger.json \
    --out /tmp/ledger.md
```

## 1. Calibration first, because an instrument nobody checked is not evidence

`calibration.json` is two mutations whose answer was already known by hand at `3981efd`.
Both reproduced, which is what licenses believing anything below:

| id | expected at `3981efd` | measured | what it is |
|---|---|---|---|
| CAL-RED | red | **red** | restoring the old unqualified epilog claim alone — the roster node catches it |
| CAL-GREEN | green | **green** | K4's I7: the same restoration **plus** renaming both `parser.error` mentions |

CAL-GREEN comes back **PINNED at `ff58237`**, and that is the fix landing rather than the
calibration passing — calibration is always run on `3981efd`.

## 2. The two hazards the harness refuses to run without

Both bit for real in this job before the harness existed:

1. **A `git worktree` does not isolate this suite.** `bantamkit` is installed editable
   against the MAIN repo, so pytest inside a worktree imports the main tree's module and
   every in-process node silently tests unmutated source. `PYTHONPATH` is pinned to the
   worktree's `runtime-py/src` and a self-test asserts the pin reached the child before
   any measurement is believed.
2. **A `.replace()` that matched nothing looks exactly like a fix that works.** Every
   mutation asserts its anchor is present **exactly once** and that the file changed;
   two of the orchestrator's own hand edits no-oped that way and produced meaningless
   green runs.

## 3. The matrix, before (`b0d4cce`, 764 nodes) and after (`ff58237`, 767 nodes)

| id | kind | pinned @ `b0d4cce` | pinned @ `ff58237` | claim | killed by (after) |
|---|---|---|---|---|---|
| B01 | behaviour | yes | yes | EPIPE (the reader went away) keeps the status the run EARNED, and never invents one | `test_closed_pipe_clean_run_still_exits_zero`, `test_closed_pipe_violating_run_still_exits_three_and_writes_the_same_bytes`, `test_closed_pipe_unwritable_summary_still_exits_four` (+2) |
| B02 | behaviour | yes | yes | after a lost stdout the next write RAISES; silence is the one option not available (RB-P33, both arms) | `test_a_lost_pipe_also_raises_on_the_next_write_instead_of_swallowing_it` |
| B03 | behaviour | yes | yes | fd 1 closed before the process started (sys.stdout is None, print a silent no-op) reports 5 | `test_a_closed_stdout_does_not_turn_a_measured_run_into_a_refusal` |
| B04 | behaviour | yes | yes | a render failure from the DESCRIPTOR (EBADF, ENOSPC) reports 5, never the refusal status | `test_an_enospc_failure_at_the_table_write_reports_the_render_failure_status`, `test_a_lost_stdout_raises_on_the_next_write_instead_of_swallowing_it`, `test_a_render_failure_below_the_buffer_reports_the_render_failure_status` (+3) |
| B05 | behaviour | yes | yes | a render failure from the CODEC (UnicodeEncodeError) reports 5 — K4's C1 | `test_a_stdout_that_cannot_encode_the_table_reports_the_render_failure_status[small-table-latin-1]`, `test_a_stdout_that_cannot_encode_the_table_reports_the_render_failure_status[small-table-ascii]`, `test_a_stdout_that_cannot_encode_the_table_reports_the_render_failure_status[large-table-latin-1]` (+5) |
| B06 | behaviour | yes | yes | the arm is NOT a bare except: a genuine bug at the write keeps its traceback | `test_a_non_oserror_at_the_table_write_is_not_downgraded`, `test_a_non_unicode_valueerror_at_the_table_write_is_not_downgraded` |
| B07 | behaviour | yes | yes | the line is drawn at UnicodeEncodeError, not at ValueError | `test_a_non_unicode_valueerror_at_the_table_write_is_not_downgraded` |
| B08 | behaviour | yes | yes | format_table is evaluated OUTSIDE the try: a failure to BUILD the table is a bug and propagates | `test_a_non_pipe_failure_around_the_table_print_is_not_downgraded[OSError-not-EPIPE]` |
| B09 | behaviour | yes | yes | 5 OUTRANKS 4: a run that could write neither the summary nor the table reports 5 | `test_the_render_failure_status_outranks_the_unwritable_summary_status`, `test_the_render_failure_status_outranks_the_unwritable_summary_from_a_codec[latin-1]`, `test_the_render_failure_status_outranks_the_unwritable_summary_from_a_codec[ascii]` |
| B10 | behaviour | yes | yes | 4 OUTRANKS 3: an unwritable summary beats the guard status | `test_a_measured_run_whose_summary_cannot_be_written_does_not_report_the_refusal_status`, `test_the_write_status_outranks_the_guard_status`, `test_a_clean_run_whose_summary_cannot_be_written_is_not_a_zero` (+3) |
| B11 | behaviour | yes | yes | --violations-exit-zero cannot suppress 5 — the hatch is an opt-out from 3 alone | `test_the_hatch_does_not_suppress_a_render_failure_from_a_codec[latin-1]`, `test_the_hatch_does_not_suppress_a_render_failure_from_a_codec[ascii]`, `test_the_hatch_does_not_suppress_a_render_failure_from_a_dead_fd` |
| B12 | behaviour | yes | yes | --violations-exit-zero cannot suppress 4 either | `test_the_hatch_does_not_suppress_an_unwritable_summary` |
| B13 | behaviour | yes | yes | --replays 0 / --identity-replays 0 are argument-SHAPE rules and report 2 | `test_cli_rejects_a_replay_count_below_one`, `test_this_modules_own_validation_errors_are_argparses_number`, `test_every_argument_shape_error_reports_the_same_number` (+2) |
| B14 | behaviour | yes | yes | a malformed --rubric spec is a shape rule and reports 2 (RB-P32's four moved cases) | `test_every_argument_shape_error_reports_the_same_number`, `test_every_shape_rule_flag_is_the_usage_status_in_the_field` |
| B15 | behaviour | yes | yes | a duplicated --rubric LABEL is a shape rule and reports 2 — K4's C2 | `test_every_argument_shape_error_reports_the_same_number` |
| B16 | behaviour | yes | yes | a WORLD-dependent failure stays 1: --rubric naming a missing file is not a usage error | `test_every_shape_rule_flag_is_the_usage_status_in_the_field` |
| P01 | prose | **NO** | yes | the epilog and the module comment describe the SAME set — K4's I7, the full three-edit restoration | `test_no_sentence_about_the_usage_status_claims_all_of_this_modules_validations` |
| P02 | prose | yes | yes | the shape-rule roster in the epilog names exactly the rules the code has | `test_the_usage_status_names_exactly_the_shape_rules_the_code_has` |
| P03 | prose | **NO** | yes | 4's own sentence promises 'the table is still printed' — the reason 5 outranks it | `test_the_render_failure_block_quotes_a_promise_the_write_status_block_still_makes` |
| P04 | prose | **NO** | yes | the epilog discloses the four cases RB-P32 moved from 1 to 2 | `test_the_epilog_discloses_the_behaviour_change_with_the_count_the_field_record_measured` |
| P05 | prose | yes | yes | the module comment's copy of the roster names the same set as the epilog's | `test_the_usage_status_names_exactly_the_shape_rules_the_code_has` |

|   | | **before** | **after** |
|---|---|---|---|
| behaviour | | **16/16 (100%)** | **16/16 (100%)** |
| prose | | 2/5 (40%) | **5/5 (100%)** |
| overall | | 18/21 (86%) | **21/21 (100%)** |

Each of the three misses at `b0d4cce` was verified by applying the mutation and watching
a **fully green 764-node suite** come back — not inferred from the absence of a node.

## 4. What this does NOT measure

- **The ledger is the denominator.** 21 claims is what one reader wrote down; a claim
  nobody entered is not counted as unpinned, it is invisible. The number is "of the
  claims in this file", never "of the contract".
- **A prose guard is not a behaviour guard.** P01, P03 and P04 are now red under their
  mutations, which means the SENTENCES cannot be silently reversed. The behaviour each
  describes is pinned separately, by the B-rows, and RB-P28 says why neither is the
  proof: every acceptance in this job is a field measurement.
- **One mutation per claim.** A claim is pinned against the mutation in the ledger, not
  against every mutation that would falsify it. `_RBP32_FIELD_CASE_FLOOR`'s own residual
  is exactly this shape — a three-place edit still passes — and it is filed, not papered
  over.
