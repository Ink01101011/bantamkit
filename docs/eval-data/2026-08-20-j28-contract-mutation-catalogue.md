# The contract surface's must-be-red catalogue — committed, rerunnable, and calibrated

**Measured 2026-08-20 (J28), `RB-P89`.** Program:
`docs/eval-data/2026-08-20-j28-contract-mutation-catalogue.py`. Layer: **Measurement**, with one
change outside it declared in §7. Every figure below was measured against
`assets/contracts/default.yaml` with `runtime-py/tests` as the suite, on the worktree tree
(`bantamkit.__file__` proven in §9), `-p no:randomly` throughout. **Two trees are involved and
every number below says which:**

    BEFORE   640c6b0    `main`'s tip when this unit started; the node §7 fixes is unfixed here
    AFTER    0ba46f5    640c6b0 plus this unit's one-node change to `runtime-py/tests/test_agent.py`

The §5 table and its three numbers are the AFTER tree. §7's re-derivation of `RB-P89`'s own
`4` and `5` is the BEFORE tree, because `5` is a figure about the defect.

## 1. Why this exists at all: the catalogue was never committed

Every provenance comment in `docs/eval.md` that quotes a laundering measurement attributes it to
*"a Z2 mutation script over a `git archive c2cfb89` tree"*. **That script was never committed and
does not exist.** So the program's central anti-laundering discipline — section S's class, section
T's procedure, four instances — has in practice been a procedure someone re-improvises each time,
and nothing in the repository can be re-run to check any of it.

`RB-P89` is what that costs. `c2cfb89`'s `M5` reworded `tool_argument_types` (the frame) and
never reworded `tool_argument_type` (the item), so a node that reddens **only** on the item was
invisible to a catalogue that had been re-run with every column's membership checked. The
procedure was blind by construction: it checks that a NEW case does not appear in an EXISTING
column, and never checks that the MUTATION is as wide as the surface the column claims to pin.

**The deliverable here is therefore the program, not the number.** The numbers are what it says
today; the program is what makes tomorrow's number checkable.

## 2. What it measures, and how a verdict is reached

For each top-level string of the contract asset: reword that string and only that string, copy
the whole asset pack to a temporary directory, run the entire suite against it, and diff the
failing-node set against the unmutated baseline.

| verdict | meaning |
|---|---|
| `PINNED-BY-NAME` | at least one newly-red node's **name** declares it asserts wording |
| `LAUNDERING` | nodes went red and **not one** declares wording — every red is a node whose name promises a different claim |
| `UNPINNED` | nothing went red; the string can be reworded into anything and the suite stays green |
| `BROKEN` | the tree did not collect; not evidence about anything, and exits non-zero |
| `EXCLUDED` | the mutation is a no-op on this key; measured by nothing and said so |

"Names wording" is a **fixed predicate on the node name** — it contains one of `verbatim`,
`bytes`, `golden`, `wording`, `phrasing` — applied identically to all 34 keys. This closes, for
this one surface, the loophole `2026-08-14-pinning-harness-false-positives.md` filed and could
not close: *"`pins` is chosen by the person writing the claim ... the attack direction: derive
`pins` mechanically ... so the author does not get to choose."* There is no per-string pin list
here to choose. The cost is that the predicate is crude, and §6 says what that costs.

## 3. Coverage — stated, because an unmeasured check is not a passed one

**MUTATED.** All 34 top-level keys of `assets/contracts/default.yaml` are attempted. 32 produce a
real mutant under `--mode prose`; 7 of those are re-measured under `--mode whole`.

**NOT MUTATED, and laundering under each is UNMEASURED:**

| not mutated | why |
|---|---|
| `name: default` | the pack's identifier, not a sentence any model reads. Rewording it is an identity change, not a rewording. |
| `document_error` under `--mode prose` | it is the `error: ` marker plus `{detail}` and nothing else, so a prose rewording is a no-op. **`--mode whole` measures it: 6 new red.** |
| the placeholder NAMES (`{tool}`, `{problems}`, …) | a renamed placeholder is a `KeyError` at format time — a crash, not a rewording, and it would report `BROKEN` rather than a pin. |
| the YAML comments | not loaded, so nothing can assert on them. (`--calibrate` mutates one deliberately, as its negative control.) |
| every asset outside `contracts/default.yaml` | the tool schemas, profiles and skills are a different surface and this program does not touch them. |
| `runtime-ts` | this runs `runtime-py/tests` only. The TypeScript suite is not covered. |

**Mutation shape.** `word -> word[0] + "q" + word[1:]` over every alphabetic run of the literal
text; placeholders and backslash escapes untouched, so every mutant still loads and still
formats. It is not a synonym swap and is strictly more sensitive than one: a node asserting ANY
word of the sentence reddens. A string with no alphabetic run has its **punctuation** rewritten
instead — `evidence_line` is `"{name}({arguments}) -> {observation}"` and its punctuation is the
whole of what it says, so skipping it would have left the one all-structure string unmeasured.

`--mode prose` leaves a leading `error: ` marker alone; `--mode whole` rewords it too. The two
modes differ on exactly the 7 strings that carry the marker and are byte-identical elsewhere.
**`prose` is the shape `M5` had**, and §5 is why that is not an assumption.

## 4. Calibration — the instrument measured against answers known by hand

    python3 docs/eval-data/2026-08-20-j28-contract-mutation-catalogue.py --calibrate

| id | mutation | expected | measured |
|---|---|---|---|
| `CAL-RED` | reword `schema_instruction`, pinned by `test_layers.py::test_schema_instruction_bytes` | `PINNED-BY-NAME` | **`PINNED-BY-NAME`, 8 new red** |
| `CAL-GREEN` | reword a yaml **comment** and no string at all | `UNPINNED` | **`UNPINNED`, 0 new red** |

Both known answers came back; the run exits 0, and exits 1 if either flips. `CAL-GREEN` is the
control the pinning harness lost on 2026-08-14: without it, an instrument that reports every
string pinned cannot be told from a detector stuck on, and the whole of §5 would be unreadable.

## 5. The three numbers, at `0ba46f5`

    PYTHONPATH=$PWD/runtime-py/src python3 \
      docs/eval-data/2026-08-20-j28-contract-mutation-catalogue.py --jobs 5

| key | verdict | new red | of which name wording | of which do not |
|---|---|---:|---:|---:|
| `name` | EXCLUDED | 0 | 0 | 0 |
| `schema_instruction` | PINNED-BY-NAME | 8 | 1 | 7 |
| `schema_retry` | PINNED-BY-NAME | 4 | 1 | 3 |
| `critique_feedback` | PINNED-BY-NAME | 2 | 1 | 1 |
| `parse_error` | PINNED-BY-NAME | 5 | 1 | 4 |
| `validation_error` | PINNED-BY-NAME | 1 | 1 | 0 |
| `json_answer_retry` | PINNED-BY-NAME | 5 | 1 | 4 |
| `loop_note` | PINNED-BY-NAME | 1 | 1 | 0 |
| `loop_warn` | PINNED-BY-NAME | 1 | 1 | 0 |
| `evidence_line` | PINNED-BY-NAME | 8 | 1 | 7 |
| `evidence_no_observation` | **LAUNDERING** | 2 | **0** | 2 |
| `evidence_empty` | PINNED-BY-NAME | 4 | 1 | 3 |
| `document_manifest_empty` | PINNED-BY-NAME | 2 | 1 | 1 |
| `document_manifest_part` | PINNED-BY-NAME | 4 | 1 | 3 |
| `document_manifest_header_row` | PINNED-BY-NAME | 2 | 1 | 1 |
| `document_manifest_first_row` | PINNED-BY-NAME | 2 | 1 | 1 |
| `document_manifest_last_row` | PINNED-BY-NAME | 2 | 1 | 1 |
| `document_page_header` | PINNED-BY-NAME | 3 | 1 | 2 |
| `document_page_next` | PINNED-BY-NAME | 2 | 1 | 1 |
| `document_page_end` | PINNED-BY-NAME | 2 | 1 | 1 |
| `document_page_truncated` | PINNED-BY-NAME | 2 | 1 | 1 |
| `document_unknown` | PINNED-BY-NAME | 2 | 1 | 1 |
| `document_offset_past_end` | PINNED-BY-NAME | 2 | 1 | 1 |
| `document_error` | EXCLUDED (see §3) | 0 | 0 | 0 |
| `document_paste_preamble` | PINNED-BY-NAME | 1 | 1 | 0 |
| `document_paste_part` | PINNED-BY-NAME | 3 | 1 | 2 |
| `document_paste_complete` | PINNED-BY-NAME | 2 | 1 | 1 |
| `document_paste_truncated` | PINNED-BY-NAME | 2 | 1 | 1 |
| `document_paste_none` | PINNED-BY-NAME | 2 | 1 | 1 |
| `tool_failed` | PINNED-BY-NAME | 5 | 1 | 4 |
| `tool_arguments` | PINNED-BY-NAME | 2 | 1 | 1 |
| `tool_arguments_none` | PINNED-BY-NAME | 2 | 1 | 1 |
| `tool_argument_types` | PINNED-BY-NAME | 4 | 4 | 0 |
| `tool_argument_type` | PINNED-BY-NAME | 4 | 4 | 0 |

    pinned by at least one node that NAMES its reason      31 of 32
    pinned ONLY by nodes that promise a different claim      1 of 32     evidence_no_observation
    pinned by NOTHING AT ALL                                 0 of 32
    broken mutants                                           0

**The figure nobody had measured is zero, and it is zero for one reason.** Every string but
`evidence_no_observation` is reached by a `*_bytes` golden in `test_layers.py`, and for **29 of
the 32 that golden is the ONLY node that names its reason** — 2 strings have four such nodes
(`tool_argument_types` and `tool_argument_type`) and 1 has none. The floor holds because someone
wrote those goldens, not because the suite is broadly wording-aware. Delete the `*_bytes` nodes
from the killer sets and re-derive the same three numbers off the same run and the table reads
**2 pinned, 26 laundering, 4 pinned by nothing at all**. That counterfactual is arithmetic over
this run's recorded killers, not a second measurement.

**`evidence_no_observation` is the one string the goldens miss.** `test_render_evidence_bytes`
covers `evidence_line` and `evidence_empty`, not the no-observation case, so the string's only
killers are `test_render_evidence_missing_observation` and
`test_render_evidence_observation_before_call_does_not_pair` — two nodes whose names promise
claims about pairing and about a missing observation, not about phrasing. **Filed, not fixed:
this unit owns `RB-P89`'s node, not this one**, and the fix is the same one line of naming.

**The second number worth having: 26 of the 32 strings redden at least one node that does not
name its reason — 48 distinct nodes in all.** Being `PINNED-BY-NAME` does not make a string free
of laundering; it means the laundering is not the only thing holding it. Each of those 48 is an
`RB-P89`-shaped instance by the mechanical predicate. §6 is why that is a ceiling and not a
count of defects. The full list is regenerated by the command above.

## 6. What this instrument does NOT establish

- **The predicate is crude in one direction.** `test_no_documents_at_all_says_so` reddens on
  `document_manifest_empty` and its name arguably does promise the wording; the predicate reads
  it as laundering because `says_so` is not one of five tokens. **48 is an upper bound on the
  laundering class, not a count of defects.** What it is not is author-chosen, which is the
  property `2026-08-14` asked for and could not get.
- **It is crude in the other direction too.** A node named `..._bytes` that asserts nothing about
  wording would be counted as naming its reason. Nothing here inspects a node's body.
- **A rewording is one mutation shape.** A string can be pinned against rewording and unpinned
  against a placeholder rename, a truncation, or a swap of two strings for each other. §3 says
  which of those are unmeasured; all of them are.
- **`0 of 32` is a statement about `runtime-py/tests` at `0ba46f5` and about nothing else.**

## 7. `RB-P89`'s own instance, re-derived — and the node fixed

The register's `4` and `5` are claims. Both reproduce **exactly**, under `--mode prose`, against
`c2cfb89`'s node set as it stands at **`640c6b0`** — the BEFORE tree, with the node unfixed:

    tool_argument_types  (frame)  reworded    4 new red    4 name wording, 0 do not
      test_agent.py::test_a_schema_fragment_in_a_declared_argument_reads_as_the_contract_sentence_verbatim
      test_agent.py::test_dispatch_names_the_argument_verbatim_when_a_string_will_not_convert_to_its_type
      test_agent.py::test_every_wrong_typed_declared_argument_is_named_in_one_sentence_verbatim
      test_layers.py::test_tool_argument_types_bytes

    tool_argument_type   (item)   reworded    5 new red    4 name wording, 1 does NOT
      the same four, plus
      test_agent.py::test_a_wrong_typed_declared_argument_is_reported_rather_than_dropped

Three `_verbatim` nodes plus the byte golden, and a fifth on the item, exactly as filed.

**One correction to the entry's reading, not to its numbers.** The entry says the four are
*"three `verbatim` + the byte golden"* — true, but the third `verbatim` node is
`test_dispatch_names_the_argument_verbatim_when_a_string_will_not_convert_to_its_type`, which
lives 450 lines above the `RB-P86` block and is not one of the two the entry quotes.

**Why `prose` and not `whole` is the mode that re-derives `4`.** (Measured on the BEFORE tree;
neither of the two extra nodes touches the item string, so the count is 6 on either tree.) Under `--mode whole`, which
rewords the leading `error: ` marker too, the frame reddens **6**, not 4 — the extra two are
`test_document_tools.py::test_document_read_answers_the_thirteen_calls_the_3b_actually_made_in_its_own_words`
and `test_memory_component.py::test_malformed_k_still_becomes_an_error_observation`, both of
which assert `startswith("error: ")`. That the entry's number is 4 and not 6 is **evidence about
the lost script**: `M5` preserved the marker. The mode is not a guess.

**The fix.** `test_a_wrong_typed_declared_argument_is_reported_rather_than_dropped`'s last line
was `assert "offset must be type integer, not type object" in observation` — the item string
asserted verbatim inside a node whose name promises a claim about dropping. It now asserts the
claim its name makes, in three parts, none of them the asset's phrasing: the handler never runs,
its default never reaches the model, and the argument the call got wrong is **named back**
(`offset` is data off the call and off the schema). The verbatim assertions stay exactly where
their names say they are — the two `_verbatim` nodes and `test_tool_argument_types_bytes`, all of
which already assert the full rendered sentence and so already pin the item string.

**After the fix, re-measured at `0ba46f5` with the same command:** `tool_argument_type` reads
**4 new red, 4 naming wording, 0 not** — the same four as the frame. **The item's laundering
column is empty, and its pinning is unchanged.** That is the whole of the effect: one node
removed from the laundering set (44 -> 43 before the `evidence_line` fallback added five more),
nothing added, no test weakened, nothing green that was red.

## 8. Non-vacuity: the fixed node reddens on the defect its NAME promises

A node that stops reddening under a rewording has to still redden under the thing it claims to
guard, or the fix is laundering of a different kind. **Deliberate defect**, applied to a copy of
`runtime-py/src` and never to the tree: in `Agent._dispatch`, replace

    mistyped = mistyped_arguments(arguments, parameters)
    if mistyped:
        return tool_argument_types(tc.name, mistyped)

with the pre-`RB-P86` behaviour the node's name is about —

    for _bad, _e, _a in mistyped_arguments(arguments, parameters):
        arguments.pop(_bad, None)      # DELIBERATE DEFECT: drop instead of report

`PYTHONPATH=<mutated src> pytest runtime-py/tests/test_agent.py -q -p no:randomly` -> **5 failed,
68 passed**, and the node is one of the five, on its first assertion:

    FAILED test_a_wrong_typed_declared_argument_is_reported_rather_than_dropped
    >  assert seen == {}, "the handler must not run at all"
    E  AssertionError: the handler must not run at all
    E  assert {'offset': 0} == {}

The handler ran on a default the model never asked for. That is the sentence the node's name
makes, and it is now the sentence that reddens it.

**And the catalogue itself is shown to work by the same event**: run at `640c6b0` it reports this
node under `tool_argument_type`'s laundering column; run at `0ba46f5` it does not, and reports
nothing else different. A catalogue that reports nothing is decoration; this one reported
the defect the register filed, and then reported its removal.

## 9. `bantamkit.__file__`, and the trap it disarms

    /private/tmp/.../wt-j28/runtime-py/src/bantamkit/__init__.py

The program sets `BANTAMKIT_ASSETS` to a **temporary copy** of the pack and `PYTHONPATH` to the
worktree's `src`, and locates both from its own `__file__` rather than from the cwd. This matters
more here than anywhere: a mutation written into one tree's asset while pytest reads another's
reports every mutation inert, and the conclusion would be that the entire surface is unpinned —
`0 of 32` in the wrong column, with nothing in the output to say so. The `CAL-RED` control in §4
is what makes that failure loud rather than silent.

## 10. One figure the program now refuses to misreport

The table's header line carries the commit the program read from `git rev-parse HEAD`, and the
AFTER runs above were made with the fix present in the tree but not yet committed — so the
generated header said `640c6b0` while the tree was not `640c6b0`. **That is the defect this whole
program exists to make checkable, committed into the program itself.** It now appends `-dirty`
when `git status --porcelain` is non-empty, so a table can no longer be headed with a commit it
was not measured at.

The change touches `docs/eval-data/` only — no test, no asset — so §5's table is unaffected by
it, and that was checked rather than assumed: the full sweep was re-run on the commit carrying
this section and every row, every verdict and all three numbers came back identical, with the
header now reading that commit rather than `0ba46f5`. A commit cannot name its own hash, which is
why §5 stays attributed to the tree where the measured content last changed.

## 11. Layers

The catalogue and this record are **Measurement**. The one change outside it is
`runtime-py/tests/test_agent.py`, which is **core tests** — and that split is `RB-P89`'s own
instruction: the entry filed the node `NOT FIXED HERE` *"and the reason is ownership, not effort:
the node lives in `runtime-py/tests/test_agent.py` and this section owns `docs/eval.md`. ... it
belongs to the layer that holds the node."* This unit holds that layer, so it lands here.
**`assets/contracts/default.yaml` is not touched** — no Layer 2 change was needed, and every
mutation this program makes is to a temporary copy.
