---
name: feedback-prescribe-the-property-not-the-mechanism
description: why a fix I hand a subagent should state the property to hold rather
  than the comparison to write, and why a tolerance rule needs an attacker
type: feedback
created: '2026-08-22'
last_recalled: '2026-09-11'
links: []
---

When handing a subagent a fix, state **the property that must hold** and **the
attack it must survive** — not the comparison to write. A prescribed mechanism
carries my untested assumptions into someone else's commit.

**Why: measured on 2026-08-17, on my own instruction.** I told a unit to repair a
reproduction check so that "a row that gained a new **trailing** key still
verifies" and to compare on "the **committed file's own key set**". I later
implemented both readings literally and ran them:

- **strict prefix** ("trailing") → **RED on the honest case.** The new field was
  trailing on the dataclass but the row's writer appends three more keys after
  `asdict()`, so in the serialized order the addition lands mid-list. *Position is
  not a contract.*
- **intersection** ("the committed file's own key set") → **PASSED an attacker who
  DELETES a key from a committed row**, because a deletion merely shrinks the
  reference set. My own wording green-lit exactly the mutation of committed
  evidence the instruction existed to prevent.

The unit measured both, refused both, and shipped a third rule: additions must
appear in a **dated declaration** and the residual key list must equal the
committed list in order — so the permission is *enumerated*, never inferred.

**How to apply:**
1. Write the fix as an invariant plus the falsifying cases it must fail on. "Must
   exit 0 here, must exit 1 when a committed value changes, a key is deleted, a row
   is dropped, or an undeclared key appears" — let the unit choose the mechanism.
2. **Test any tolerance rule against an attacker, not a use case.** Tolerance
   stated over a set is tolerance in *both* directions; "ignore what's missing"
   always also means "permit deletion".
3. Tell units explicitly that a brief's "do X" is a **hypothesis**, and that
   measuring X false is doing the job, not resisting it. Say it in the brief.
4. When a unit contradicts me, **implement my own words literally and run them**
   before defending them. That is what settled this in minutes.

See [[feedback-real-probe-only]], [[project-bantamkit-program-backlog]].
