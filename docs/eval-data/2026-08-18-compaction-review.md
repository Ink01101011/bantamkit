# Adversarial review of the compaction measurement

**Dated 2026-08-18. U5 of job `compaction-measured`. Status: REVIEWED, NOTHING FIXED.**

This unit was commissioned to break the result, not to appreciate it. It fixes nothing:
every finding below is filed with a demonstrating command, an attack direction and a
layer, and U6 closes the **Criticals only**. Mixing review and repair would destroy the
before/after evidence, so no committed artifact, program or document was edited by this
unit — `git diff` on everything under `docs/eval-data/` except this file is empty at the
review commit.

The subjects are the bar
([`2026-08-17-compaction-bar-preregistration.md`](2026-08-17-compaction-bar-preregistration.md),
`f48335c`, amended at `e94d960`), the corpus
([`2026-08-17-compaction-corpus.md`](2026-08-17-compaction-corpus.md), `6c1a05b`) and
U4's arms
([`2026-08-18-compaction-arms-measurement.md`](2026-08-18-compaction-arms-measurement.md)
and its field program, `581f6b6`…`3ac1273`).

**Three orchestrator probes ran before this review and their findings were treated as a
floor, not as settled.** Two of the five commissioned attacks — A1, the anchor seam, and
A3, the null control — had no adversary before this unit. A3 is where the new Criticals
came from.

---

## 0. The result of the review, in one place

**Three new Criticals**, all in the **instrument and its disclosure**, none of which
changes a committed number:

| id | one line | changes a verdict? |
|---|---|---|
| **C-U5-1** | bar §1.2's VOID check is a **theorem**, not a measurement: the two byte counters it compares are the same function, so the loss class it names cannot turn it red — and 821,174 B of real recorded content (2.76%) is invisible to it | no (150 B inside the headline set); yes to stratum B's published boundary count |
| **C-U5-2** | `CHK-NO-POOLING` prints *"no cross-stratum figure exists"* in a run whose **own first section prints six of them**, and whose committed §2 table publishes the same ones | no |
| **C-U5-3** | Amendment B rules `T` by *"the mechanism's own meaning"* and then applies a window composition **the mechanism's own source excludes**; five defensible instantiations of reading A span **16 to 107** reachers and the applied one is the most permissive of all five | no — R1 still fires under every one |

**Four Majors, four Lows.** Findings the probes filed that **did not reproduce at HEAD**
are listed in §5 rather than repeated.

**Verdict on Amendment B (§6): the RULING is SOUND, the AMENDMENT AS A SPECIFICATION is
UNDER-DETERMINED, and its bolded direction-of-cost sentence is UNSOUND as written.**

**The two attacks with no prior adversary came out opposite ways.** A1 — the job's known
open seam — is **closed negative and measured**: the anchor lists never moved, the run
provably happened after they were frozen, and the stop-list is worth 1.63% of the anchor
set. A3 — the null control — is where C-U5-1 came from.

**No finding argues a null result into a positive.** The −80% target is refuted, the arms
are a TRADE, stratum B is UNMEASURED, and this review leaves all three exactly where U4
put them.

---

## 1. What was run

Everything below reads committed evidence. **No arm was re-run, no second model was run,
and no field program was invoked with the argument list that rewrites an artifact**
(U4's F10): `--reconstruct` and `--arms` call `write_rows` and were never invoked. The
acceptance path (`cmd_report`, the no-flag and `--mutate` invocations) writes nothing.

```
.venv/bin/python -m pytest runtime-py/tests -q          # 932 passed, 2 xfailed
.venv/bin/ruff check runtime-py tools/pinharness tools/devteam docs/eval-data
cd runtime-py && ruff check .
.venv/bin/ruff check --config runtime-py/pyproject.toml examples
.venv/bin/python tools/devteam/build_tasks.py check     # OK — 8 tasks
.venv/bin/python docs/eval-data/2026-08-18-compaction-arms-field-measurement.py
                                                        # exit 0, 20 checks, 0 red, 0 escalations
```

---

## 2. CRITICALS — U6 closes these and only these

### C-U5-1 — the null control's VOID check cannot detect the loss it names, and 2.76% of the corpus is invisible to it

**Layer:** `docs/eval-data/` — the field program, plus a dated amendment for the one
published figure it touches. **Attack direction:** A3, the null control as
information-removing. **This is the check bar §1.2 calls load-bearing and U4 §2 calls
"the single failure this unit was most exposed to".**

The reconciliation compares `recorded_content_bytes` (the corpus survey's
`_content_bytes`) against `reconstructed_content_bytes` (the field program's
`_render_content`). The program's own docstring states the purpose:

> *"A block type this function does not handle renders as the empty string while the
> survey's counter still counts its bytes, so an unhandled block type turns the VOID check
> RED rather than silently shrinking the null control's prefix. That is the whole reason
> the two are computed by different code paths over the same input."*

**That is false.** The two functions dispatch on exactly the same type set — `None`, a
string, a list, a non-dict, then `text` / `thinking` / `tool_use` / `tool_result` — and
both return zero bytes for everything else. An unhandled block type contributes **0 on
both sides**. Equality is a theorem about the two functions, not a measurement of the
reconstruction. Two different code paths, one behaviour.

```
.venv/bin/python - <<'PY'
import importlib.util, sys
from pathlib import Path
D = Path("docs/eval-data")
def load(n, m):
    s = importlib.util.spec_from_file_location(m, D / n)
    mod = importlib.util.module_from_spec(s); sys.modules[m] = mod; s.loader.exec_module(mod)
    return mod
survey = load("2026-08-17-compaction-corpus-survey.py", "_s")
arms = load("2026-08-18-compaction-arms-field-measurement.py", "_a")
for label, content in [
    ("unhandled top-level block", [{"type": "image", "source": {"data": "X" * 5000}}]),
    ("unhandled block nested in tool_result",
     [{"type": "tool_result", "content": [{"type": "image", "source": {"data": "Y" * 5000}}]}]),
]:
    rec = survey._content_bytes(content)
    rcn = len(arms._render_content(content, survey).encode("utf-8"))
    print(f"{label:40s} recorded={rec} reconstructed={rcn} -> delta {rcn-rec}")
PY
```

→ `delta 0` on both. A 5,000-byte block vanishes from the null control's prefix and the
VOID check reports a perfect reconciliation.

**And it is not hypothetical on this corpus.** Scanning the 207 in-scope transcripts for
block kinds neither counter handles, under the same cutoff rule the reconstruction uses:

| | |
|---|---|
| unhandled blocks, **nested inside `tool_result` content** | `tool_reference` ×52, `image` ×2 |
| their serialised bytes | **821,174 B** |
| share of the 29,776,563 B the reconciliation reports as perfectly carried | **2.7578%** |
| transcripts affected | **22 of 207** |

They are invisible three ways at once: not in `reconstruction_byte_delta` (equal on both
sides), not in `skipped_event_kinds` (they are blocks, not events), and not in the corpus
survey's `content_block_kinds`, which enumerates **top-level blocks only** and therefore
never descends into the `tool_result` content that `_content_bytes` itself recurses into.

**U4's corroboration is not independent.** §2 offers as its first corroboration that
`29,776,563` "is exactly U3's committed `message content bytes` Σ, computed by a different
program from a different pass". It is the same function — the field program imports the
survey module and calls `survey._content_bytes` — so the agreement is guaranteed and
carries no information about dropped content.

**What it costs, measured rather than asserted, because a Critical that overstates its own
blast radius is the failure mode on this side.** Inside the 24 informative sampled
transcripts that carry every arm figure, the invisible content totals **150 bytes across 3
transcripts** (0.0123%, 0.0139%, 0.0342% of their own recorded content). **No arm figure
in this job is materially affected and the TRADE verdict is untouched.** One figure is:
the 819,869 B block sits in the single **stratum-B** transcript, whose published R1 ceiling
(−88.9910% / −93.3403%) and boundary count (**12**) are computed from a prefix short by
that amount. An upper-bound correction — all of it present at the peak — puts stratum B at
**18** boundaries, which also makes §5.4's "a stratum-B arm run costs 12 × 9 = 108 calls"
an under-estimate.

**Closure shape (not applied here).** The property to hold is that *a content block whose
type neither counter models must be able to turn the reconciliation red* — the two sides
must stop being the same function. Bar §9(5) forbids regenerating the committed rows, so
the affected published figures close by a dated amendment, not by an edit.

---

### C-U5-2 — the acceptance command prints six cross-stratum figures and then certifies that none exists

**Layer:** `docs/eval-data/` — the field program's report path and the measurement
document's §2. **Attack direction:** A2, pooling. **Same root cause as the inherited C2 and
closable with it.**

`CHK-NO-POOLING` reads, at HEAD:

```
[PASS] CHK-NO-POOLING: every headline, floor and verdict is per stratum;
       no cross-stratum figure exists (Amendment A — the user's ruling, 'ห้าม pool เป็นเลขเดียว')
```

Earlier in the same run — the first section printed, before any per-stratum figure — the
section headed *"THE NULL CONTROL, bar §1.2 — the load-bearing check"* prints `recorded_content_bytes 29,776,563 vs
reconstructed_content_bytes 29,776,563`, `recorded_events 25,393`, `reconstructed_turns
17,051`, `anchors_total 11,616`, `total skipped 1,123` and `carried + skipped = 26,516`.
Every one is a sum over all 207 transcripts, which is both strata. The committed
measurement document publishes the same six in its §2 table. The section immediately
below them is titled *"PER STRATUM (never pooled)"*, so the distinction was in the author's
hands at the moment the pooled table was written.

```
.venv/bin/python docs/eval-data/2026-08-18-compaction-arms-field-measurement.py \
  | sed -n '5,9p;/CHK-NO-POOLING/p'

.venv/bin/python - <<'PY'
import json
from pathlib import Path
D = Path("docs/eval-data")
b0 = [json.loads(l) for l in (D / "2026-08-18-compaction-b0-null-control.jsonl").read_text().splitlines()]
ok = [r for r in b0 if r.get("reconstruction") == "OK"]
for col in ("recorded_content_bytes", "recorded_events", "reconstructed_turns", "anchors_total"):
    a = sum(r[col] for r in ok if r["stratum"] == "A")
    b = sum(r[col] for r in ok if r["stratum"] == "B")
    print(f"{col:28s} printed(pooled)={a+b:>12,d}  A={a:>12,d}  B={b:>9,d}  B={100.0*b/(a+b):5.2f}%")
PY
```

→ stratum B contributes 5.66% / 4.41% / 4.22% / 4.73% of the four published totals, and
**23.34%** of the pooled `prefix_bytes_total` (1,324,636,566), which is the shape
Amendment A forbade by name: one n=1 transcript dominating a sum over 206 others.

Whether Amendment A's prohibition reaches *instrument-integrity* totals as well as
headlines is genuinely arguable. **The finding does not depend on which reading wins:**
the check's own sentence — "no cross-stratum figure exists" — is false as printed under
either.

**This is C2 measured from the output side, and it is worse than the consumer count
suggests.** Auditing every named check's *condition* rather than every policy key's
consumers:

| | |
|---|---|
| named checks whose condition reads **no measured data at all**, only the policy dict | **9 of 20** |
| `--mutate` modes that change **nothing** in the printed report except the check's own line and the final banner | **11 of 14** |
| the three that do change a printed figure | `void-reconstruction` (4 lines), `fidelity-floor-wrong-grain` (8), `all-on-vs-all-off` (13) |

```
P=docs/eval-data/2026-08-18-compaction-arms-field-measurement.py
.venv/bin/python $P > /tmp/base.txt
for m in pool-strata borrow-floor clamp-byte-columns sum-anchor-losses \
         net-summarizer-tokens upper-bound-as-saving pick-a-grain \
         zero-floor-always-valid omit-fixed-cost; do
  .venv/bin/python $P --mutate $m > /tmp/m.txt
  echo "$m: $(diff <(grep -v '^  \[' /tmp/base.txt) <(grep -v '^  \[' /tmp/m.txt) | grep -c '^[<>]') non-check lines differ"
done
```

→ `2` for every one of the nine, and the two are the run's own summary banner.

Two consequences the inherited C2 does not state:

1. **The exit-2 detector cannot catch this by construction.** U4's F6 made exit 2 mean "the
   mutation failed to falsify the check it names". A tautological mutation *does* turn its
   named check red, so it exits 1 — the intended, correct-looking code. The instrument
   built to detect a mutation that proves nothing is blind to exactly this class.
2. **`upper_bound_as_saving` belongs on the vacuous list and is not on it.** Its only
   consumer is the condition of `CHK-UPPER-BOUND-IS-NOT-A-SAVING`. The inherited C2 names
   five keys; the check-side count is nine.

---

### C-U5-3 — Amendment B applies a composition of `T` that the source it argues from excludes, and it is the most permissive of five

**Layer:** the bar's §12 — a further dated Amendment C, never an edit. **Attack direction:**
A5, the orchestrator's own ruling. **This supersedes the inherited H-A5-3 (High,
"under-determined") with a stronger claim: not merely undeclared, but contrary to the cited
source, and demonstrably the cheapest of every alternative.**

Amendment B rules that `T` is live-window occupancy *"which is the mechanism's own
meaning"*, and grounds that in `src/config.ts:98-99` at `0a15cff`. Read at the same commit,
the mechanism's own definition of occupancy is:

```
src/session.ts  recomputeUsage:  s.estTokensUsed =
    turns.reduce(tokensEst) + Σ estimateTokens(summaries) + estimateTokens(persistentRules)
```

Turns, summaries and persistent rules. **Nothing else.** The host's system prompt, tool
definitions and attachments are not in it. The applied composition is
`bytes / 1.8284 + FIXED_PER_CALL_TOKENS`, and that constant is 25,350.2 tokens — **33.01%
of `T`** — of exactly the host overhead the mechanism never counts. Under the amendment's
own stated criterion the constant is out.

Five defensible instantiations of "reading A", each differing only in what is in the window
or which shipped window fraction is the trigger — `nowPct = 85` is pinned in the bar's own
§10.1 table and §10.2 chose `proactivePct = 60` without argument:

| composition of "reading A" | reaches `T` | UNINFORMATIVE U-2, stratum A |
|---|---|---|
| **applied**: bytes ÷ 1.8284 **+ 25,350.2** | **107 / 207** | **100** |
| U3's recorded-peak counter (the bar's §10.3(3) witness) | 102 / 207 | 105 |
| constant-out — the mechanism's own `recomputeUsage` composition | **70 / 207** | **137** |
| `nowPct = 85` (`T` = 108,800), applied counter | 66 / 207 | 141 |
| the mechanism's own `chars/4` counter | **16 / 207** | **191** |

```
.venv/bin/python - <<'PY'
import json
from pathlib import Path
rows = [json.loads(l) for l in Path(
    "docs/eval-data/2026-08-18-compaction-b0-null-control.jsonl").read_text().splitlines()]
ok = [r for r in rows if r.get("reconstruction") == "OK"]
BPT, FIX, T = 1.8284, 25350.2, 76800
for r in ok:
    r["peak_bytes"] = (r["live_window_peak_tokens"] - FIX) * BPT
def reach(f, T=T):
    a = sum(1 for r in ok if r["stratum"] == "A" and f(r) >= T)
    return f"A {a}/206 reach, {206-a} U-2 | pooled {a + sum(1 for r in ok if r['stratum']=='B' and f(r)>=T)}/207"
print("applied      ", reach(lambda r: r["live_window_peak_tokens"]))
print("constant-out ", reach(lambda r: r["peak_bytes"] / BPT))
print("chars/4      ", reach(lambda r: r["peak_bytes"] / 4.0))
print("nowPct=85    ", reach(lambda r: r["live_window_peak_tokens"], 108800))
PY
```

**The applied composition maximises the informative set against every alternative — by up
to 6.7×.** Amendment B's bolded claim that reading A is "the **expensive** reading" is true
only against reading B. *Inside* reading A, every undisclosed degree of freedom was
resolved in the direction that leaves the most transcripts informative, and none of them
is named in the amendment.

**What it does NOT cost, measured, because this finding must not be allowed to look like a
result change it is not.** R1 fires under every composition. On the subsets that survive
each alternative (indicative: computed under the applied schedule, since re-running the
schedule would rewrite a committed artifact and is forbidden here):

| informative set | n | median ceiling with the constant | reaching −80% |
|---|---|---|---|
| applied | 104 | −42.6107% | 1 |
| constant-out reachers | 69 | **−48.6465%** | 1 |
| `nowPct = 85` reachers | 65 | **−49.1159%** | 1 |

**The −80% target is refuted under all three.** C-U5-3 is a disclosure Critical, not a
verdict change, and Amendment C should say so in the same breath as it declares the
composition.

**Both readings of the composition are defensible** — the applied one is the *host's* live
window, the other is the *mechanism's* — which is precisely why the bar's own discipline
applies: a figure that depends on a choice the pre-registration did not make is escalated
and declared, never picked silently.

---

## 3. Majors

### M-U5-1 — the without-constant figure is promised "beside every with-constant one" and is never printed for the arms

**Layer:** `docs/eval-data/`. U4 §1.2 declares of the fixed per-call cost: *"the
without-constant figure is printed beside every with-constant one"*. It is, for R1. It is
**not** for the arms: §5.1 and the acceptance output carry only the with-constant
percentage, though `context_tokens_sent_no_fixed` is committed on all 600 rows.

| pair | printed | never printed |
|---|---|---|
| B1 − B0 | −40.1421% | **−58.9356%** |
| B2 − B1 | −22.7575% | −42.1513% |
| B3 − B2 | −7.9204% | −19.5665% |

```
.venv/bin/python - <<'PY'
import json, statistics, collections
from pathlib import Path
D = Path("docs/eval-data")
rows = [json.loads(l) for l in (D / "2026-08-18-compaction-arms.jsonl").read_text().splitlines()]
b0 = [json.loads(l) for l in (D / "2026-08-18-compaction-b0-null-control.jsonl").read_text().splitlines()]
inf = {r["transcript_id"] for r in b0 if r.get("reconstruction") == "OK"
       and not r["uninformative_u2"] and not r["uninformative_u1"]}
per = collections.defaultdict(lambda: collections.defaultdict(list))
for r in rows:
    if r["transcript_id"] in inf:
        per[r["transcript_id"]][r["arm"]].append(r)
for y, x in (("B1", "B0"), ("B2", "B1"), ("B3", "B2")):
    for col, tag in (("context_tokens_sent_with_fixed", "with"), ("context_tokens_sent_no_fixed", "no ")):
        p = []
        for t, a in per.items():
            cy = statistics.median([r[col] for r in a[y]]); cx = statistics.median([r[col] for r in a[x]])
            p.append(100.0 * (cy - cx) / cx)
        print(f"{y}-{x} {tag} fixed: median {statistics.median(p):9.4f}%")
PY
```

The direction is honest — the printed figure is the smaller saving — but the omission is
against the unit's own declaration, and the check that names the claim
(`CHK-FIXED-COST-DECLARED`) tests only that the two **R1 ceiling** columns exist on the B0
rows. It cannot see the arms at all.

### M-U5-2 — anchor retention is, on this data, the compression ratio wearing a fidelity name

**Layer:** `docs/eval-data/` — a limitation, not a number. **Attack direction:** A4.

The bar states anchor retention is a proxy biased in both directions. It does not state
what this measurement shows: retention here is close to what a *size-matched* block would
score by itself.

| | |
|---|---|
| median installed-block bytes ÷ bytes it replaced, over the 24 informative | **0.034865** |
| median anchor retention (B1) | **0.054795** |
| median per-transcript quotient of the two | **1.213×** |
| retention in the low-compression-ratio half / high half | **0.018591 / 0.064120** |

Retention tracks the size ratio across the halves and sits only ~1.2× above it. So on this
corpus the fidelity axis carries little information the token axis does not already carry,
and the TRADE verdict is close to arithmetically forced: a block cannot be made this small
without losing literal strings roughly in proportion. That does not make the TRADE wrong —
it is the correct reading of bar §4 — but it bounds what the TRADE *means*, and the bound
belongs beside it.

### M-U5-3 — 1,314 events are skipped before the skip is counted, and bar §1.2 makes an unenumerated skip a VOID trigger

**Layer:** `docs/eval-data/`. **Attack direction:** A3. **Reading-dependent — escalate,
do not pick.**

`reconstruct()` applies the cutoff guard and `continue`s **before** the `skipped[]`
bookkeeping, so events past the cutoff never enter `skipped_event_kinds`.
`CHK-EVERY-SKIPPED-KIND-ENUMERATED` passes while:

| | |
|---|---|
| events dropped by the cutoff guard, unenumerated | **1,314** |
| of which carried kinds (`user` 126, `assistant` 218) | **344** |
| content bytes inside them | **553,877** |
| enumerated skips, for comparison | 1,123 |

Bar §1.2: *"if any skipped kind is unenumerated, the run is VOID"*. Two honest readings —
that the transcript **is** the pre-cutoff window (U3's declared corpus rule, in which case
nothing was skipped), or that the transcript is the file (in which case 1,314 skips are
unenumerated and §1.2 fires). Both arms see the same truncated input either way, so no
delta is biased. The count also **grows** with the live directory, which is the property
U3's live-column exemption exists to make loud, and here it is silent.

### M-U5-4 — the fidelity floor is taken over one arm where the token floor is taken over two

**Layer:** `docs/eval-data/`. Bar §3.1 departure 1 makes the token floor the **max over
both arms X and Y**, and §3.2 says the fidelity floor has "the same shape". The program
computes the fidelity floor from arm **Y only**.

| pair | floor as computed (Y only) | max over both arms | ratio |
|---|---|---|---|
| B1 − B0 | 0.001472 | 0.001472 | 1.000× |
| B2 − B1 | 0.011034 | 0.011034 | 1.000× |
| B3 − B2 | **0.009446** | **0.011034** | **1.168×** |

Only B3−B2 moves, no verdict changes (retention 0.061 against a non-inferiority bar of
0.989 or 0.991), and the direction is harsher on the mechanism. Filed because the bar's two
floor definitions are not the same shape and one of them will matter on a corpus where
retention is not two orders of magnitude below its floor.

---

## 4. Lows

- **L-U5-1 — the frozen anchor data contains substantial dead weight.** The `screaming`
  class contributes **0.00%** of the anchor set: its regex requires an underscore, so every
  token it matches is already matched by `snake`, which precedes it in the alternation.
  And **29 of 35** stop-list entries never fire — the 20-odd bare words (`TODO`, `ERROR`,
  `JSON` …) cannot match *any* class, again because every class that could take them
  requires an underscore or a dot. "Frozen as data, auditable" delivers a smaller audit
  surface than its size suggests. Direction: this is *evidence against* tuning — a tuned
  list fires.
- **L-U5-2 — retention is scored by substring containment.** `_retained_anchors` tests
  `anchor in installed`, so an anchor counts as retained when it occurs inside a longer
  string. Direction: generous to the mechanism; immaterial at retention 0.055.
- **L-U5-3 — the amendments carry line-number pins into an amend-only artifact.**
  Amendment B cites `…compaction-corpus.md:403` and `:404`; both still resolve at HEAD, and
  they cannot be repaired by edit if they ever stop. **Binding on U6:** any amendment to the
  corpus document must append at the end, or Amendment B's pins break irreparably.
- **L-U5-4 — the fidelity axis's own free parameter cannot be audited from the committed
  evidence.** Recomputing retention under a different anchor class list needs the installed
  block *text*, which is not committed and could not be without breaching the user's fence.
  A reviewer can verify the lists did not move and can measure their effect on
  `anchors_total` (§5) but cannot re-derive retention. That is an inherent limitation of
  the fence, worth recording rather than a defect to fix.

---

## 5. Inherited findings: confirmed, refined, and not reproduced

### Confirmed at HEAD, by my own commands

- **C2 (five vacuous mutation keys).** `pool_strata`, `clamp_bytes`, `sum_anchor_losses`,
  `net_summarizer_into_saving` and `fixed_cost_declared` each have exactly one consumer,
  the condition of the check that names them. Extended by C-U5-2 to nine checks and eleven
  mutations.
- **C1 / C-A5-1.** The bar's Amendment B states *"only 102 of 207 transcripts ever reach
  `T`, so 105 of 207 are UNINFORMATIVE under U-2"*. Applied: **107 reach, 100 U-2, 2 U-1,
  105 informative pooled**. The stated UNINFORMATIVE count is numerically the applied
  *informative* count — a spot-check confirms a number meaning the opposite. Pooled across
  strata, in the commit that introduced the pooling prohibition.
  **One extra precision for Amendment C**, measured here: `105` is exactly right as
  **stratum A's U-2 count under U3's recorded-peak counter** (A: 101 reach / 105 U-2;
  B: 1/1). It is wrong only as a figure over a 207 denominator. Amendment C can therefore
  keep the number and fix the denominator and the stratum, rather than retracting it.
- **C-A5-2.** The bolded direction-of-cost sentence states the direction on `n` only.
  C-U5-3 extends it: within reading A, every undisclosed degree of freedom also runs the
  other way.
- **M-A5-4.** The corpus document's *"the median transcript gets 18 boundaries across 26
  model calls"* is internally consistent as arithmetic (26/18 = 1.44) but **18 is a rounded
  median of a ratio, not a boundary count** — under §10.2's "first call index" rule the
  count is `floor(17.98) = 17`, and the median of a ratio is not the ratio of medians.
- **A2's cluster dependence.** Reproduced exactly and independently by grouping on the
  recorded session identifier: stratum A is 4 clusters sized **138 / 31 / 27 / 10**, largest
  67.0%, Kish `n_eff` at ρ=1 = **2.04**; the 50-sample gives **2.01**.
- **A4's MAJOR-4.** No byte column except `trim_removed_bytes` is ever negative in 600 rows;
  `offload_digest_bytes` and `offload_body_bytes` are per-transcript accumulations of
  non-negative magnitudes, so the declared cost ("a digest can be larger than the small
  output it replaces") remains untestable against this artifact.
- **`rehydrated_bytes` is 0 on all 600 rows** — the recall axis is UNMEASURED, not
  "no benefit".

### Refined in the mechanism's favour

- **A2's `n_eff` on the set that actually carries the headline.** The probe's 2.01 is for
  the 50-transcript sample. The **24 informative** transcripts — the set behind every arm
  figure — cluster **9 / 7 / 4 / 4**, largest 37.5%, **`n_eff` at ρ=1 = 3.56**. Still a 6.7×
  gap from the quoted n, and still unstated anywhere, but materially better than 2.01 for
  the figure that matters.

### Did NOT reproduce at HEAD

1. **A4's MAJOR-1 (the fidelity floor grain mismatch, 59×–147×).** Fixed by U4 at `fb72a59`.
   The headline floor at HEAD is the range across repeat sets of the median across
   transcripts — **0.001472** — which is bar §3.2's shape. The probe's proposed "correct"
   floor (1.96 × a Monte-Carlo sd) is a *different* statistic from the one the bar
   pre-registered; U4's implementation is bar-compliant and the probe's is not the standard
   to hold it to.
2. **"`threshold_t` … used to build the schedule"** (ORCHESTRATOR-VERIFIED's C2 table).
   At HEAD *and* at `581f6b6`, `policy["threshold_t"]`'s only consumer is the condition of
   `CHK-THRESHOLD-NOT-RETUNED`; the schedule is built from the module constant. The check is
   still real — its second conjunct compares `schedule_id` on all 207 committed rows — but
   the stated reason is not the one that makes it real.
3. **"`borrow_floor` is NOT vacuous — 2026-08-18-compaction-arms-field-measurement.py:1608 really lets stratum B borrow."** True as a
   static reading and **inert on the committed evidence**: the site is inside
   `if stratum == "B"`, and stratum B has **no arm rows at all**, so the branch is
   unreachable. `--mutate borrow-floor` changes nothing in the printed report but its own
   check line, exactly like the five keys C2 calls vacuous. The same applies to
   `pick_grain` (0 grain disagreements) and `zero_floor_is_always_valid` (0 zero floors):
   their non-check consumers exist but are dead on this data.

---

## 6. Verdict on Amendment B

**The ruling is SOUND. The amendment as a specification is UNDER-DETERMINED. Its bolded
direction-of-cost sentence is UNSOUND as written.**

**Sound, and re-verified at source by me rather than inherited** (`compaction-mcp` at
`0a15cff`, the commit the bar pins):

- `src/register.ts:55` compares `estTokensUsed / tokenBudget` — a **ratio to the budget**,
  so the budget is a window budget and a window fraction is what `proactivePct` is.
- `src/session.ts` `recomputeUsage` sums the **live turn list** plus summaries plus rules,
  and is recomputed rather than accumulated.
- `src/compact.ts:89` sets `session.turns = pinned` and recomputes, so occupancy **falls**
  at a boundary. A cumulative sum cannot fall. This is a **disproof** of reading B, not an
  argument against it.
- `git grep -n estTokensUsed 0a15cff -- src`: 10 hits, **no accumulator anywhere**.

There is no third *reading* — no other quantity in the mechanism that `T` could denote.
Reading B is not merely expensive, it is degenerate as a schedule.

**Under-determined**, and this is C-U5-3: "reading A" fixes the *quantity* and leaves the
*counter*, the *composition* and the *window fraction* open. Five defensible instantiations
span 16 to 107 reachers. The applied one is the most permissive of the five, and is the one
the amendment's own semantic criterion argues against.

**Unsound as written** in one sentence: *"THE DIRECTION OF THE COST IS STATED"* states the
direction on `n` and on nothing else. On the verdict axis reading A refutes the target on
both ceilings where reading B would not, and on the composition axis every open choice went
the cheap way. The claim that the direction *has been* stated is what makes it unsound
rather than merely incomplete.

**What this means for the job's headline: nothing.** The ruling stands, R1 fires under
every alternative composition, and −80% is refuted at every grain and every counter this
review could construct. **The orchestrator did not get the ruling wrong. It got the
disclosure wrong**, and the fix is a dated Amendment C, not a re-tune.

---

## 7. What I tried to break and could not

Named, because this is what tells U6 and U7 where the evidence is actually load-bearing.

**A1 — the anchor seam. Closed negative, and this is the strongest negative in the review.**

1. **The lists never moved, across every commit of the file, not just the first and last.**
   ```
   P=docs/eval-data/2026-08-18-compaction-arms-field-measurement.py
   for REV in 581f6b6 fb72a59 bce27eb 3ac1273 HEAD; do
     git show $REV:$P | sed -n '/^ANCHOR_MIN_LENGTH/,/^_ANCHOR_RE/p' | shasum -a 256
   done
   ```
   → `810d9ade…56a` five times.
2. **The run provably happened after the freeze — an ordering check the unit did not make.**
   The lists were committed at `581f6b6`, `2026-08-18 08:10:57`; the 600 rows at `4d7bd21`,
   `19:38:07`. The gap is **11 h 27 m** and the measured run is **20,913.7 s = 5.81 h**
   (`wall_clock_s` summed over the committed rows). The run fits inside the window with
   5.6 h to spare, so no part of it can have preceded the freeze.
3. **The committed anchor counts regenerate from the frozen lists exactly.** Re-extracting
   on the 24 informative sampled transcripts: **0 of 24** disagree with the committed
   `anchors_total`.
4. **The stop-list is not load-bearing.** It removes **48 of 2,942** anchors — **1.63%** —
   and only **6 of its 35** entries ever fire (`json.loads`, `json.dumps`, `README.md`,
   `sys.argv`, `pyproject.toml`, `package.json`; none bantamkit-specific). Retention is
   0.0548 against a non-inferiority bar of 0.9985; a 1.63% perturbation of the denominator
   cannot approach it. **Even a maximally adversarial stop-list, within the shape this one
   has, could not have flipped the TRADE verdict.**
5. The class list is dominated by `snake` (34.52% of the anchor set), `qualified` (31.00%)
   and `hexlike` (10.02%); `path` 3.87%, `numeric_unit` 0.24%, `screaming` 0.00%. Generic
   classes, generic shares.

**A3 — beyond C-U5-1.** B0's determinism (0 of 50 with a non-zero repeat spread) and the
mechanism-driven-vs-arithmetic route agreement (50 of 50) both hold and are real checks over
real columns. `recorded_events` 25,393 + skipped 1,123 = 26,516, matching U3's committed
line count, reproduces from my own independent pass.

**A4 — the summarizer.** The 4,096-token truncation cannot rescue the token axis for the
mechanism: `summary_bytes` is bounded by the summarizer's `max_tokens`, and B1's total
summary output across the informative set is 97,837 B — **53,510 tokens at the declared
factor, 0.064% of the 83,275,100-token pooled saving**. Whatever the summarizer was shown,
the saving comes from the collapse and not from the summary's quality or its size.

**Immutability and drift.** `git diff 6c1a05b HEAD` on the corpus rows is empty;
`git diff 581f6b6 HEAD` on the null-control rows is empty; `git diff 4d7bd21 HEAD` on the
arms rows is empty. The live-column exemption is still exactly two names and the survey has
not changed since `eab98cf`. `schedule_id`, `mcp_commit` and `model` are uniform across all
600 rows.

**The published numbers reproduce.** −40.1421% / −22.7575% / −7.9204% recomputed from the
committed rows by my own script; total `wall_clock_s` 20,913.7; 600 rows = 50 × 4 × 3 with
no ragged cell.

**Mutations.** All 14 exit 1. **None leaves everything green**, so no claim in the report is
pinned to nothing — the defect is that eleven are pinned to a flag rather than to a
measurement, which is C-U5-2, not that the pins are absent.

**No overclaim from sidechains to agent sessions**, and B2/B3 are labelled CONDITIONAL
everywhere they appear. **No pytest node was added by U4**, and the RB-P41 guard picks the
new programs up by glob, so the field-program coverage did not regress.

---

## 8. Gates, and the accounting

| gate | result |
|---|---|
| `.venv/bin/python -m pytest runtime-py/tests -q` | **932 passed, 2 xfailed** |
| `.venv/bin/ruff check runtime-py tools/pinharness tools/devteam docs/eval-data` | clean |
| `cd runtime-py && ruff check .` | clean |
| `.venv/bin/ruff check --config runtime-py/pyproject.toml examples` | clean |
| `.venv/bin/python tools/devteam/build_tasks.py check` | OK — 8 tasks |
| acceptance, no flags | exit 0, 20 checks, 0 red, 0 escalations |
| all 14 `--mutate` modes | exit 1 |

**Accounting: UNMEASURED.** No token counter and no wall-clock counter is exposed to this
unit, and bar-adjacent discipline forbids a self-estimate. U3 and U4 reported measured
figures from counters available to them; none is available here, and reporting a guess
because two earlier units reported a number would be worse than reporting nothing.

**Model: `claude-opus-5[1m]`.** One model, no second model run, no arm re-run.
