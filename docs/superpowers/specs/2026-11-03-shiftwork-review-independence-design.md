# Shift-work review independence: a reviewing unit cannot share a role with the work it reviews

Date: 2026-11-03. Status: proposed. Chain: 6 of 8 (small, independent; needed by
investigation, #264, and experimentation, #265). Borrowed from `ex-workflow`'s "independence
is by role id" (validator, replay worker and conclusion reviewer may not have done the work),
as specification only (route B).

## The problem

The code-fix template has a reviewer unit after the implementer, but nothing checks that it
is a different role, or that it runs after the work it reviews. A plan that names the
implementer as its own reviewer validates and runs.

## Decisions

**D1 — the field.** `plan.units[].reviews`: optional array of unit ids.

**D2 — the rule, checked where the graph is read** (`shiftwork_plan`, `clock_in`,
`clock_out` on the mutated document), first fault wins:
1. a reviewed id that no unit declares: `unit <id> reviews <r>, which no unit declares`;
2. a reviewed id not in the unit's `depends_on` (a review runs after the work):
   `unit <id> reviews <r> but does not depend on it`;
3. same role: `unit <id> reviews <r> in the same role <role>; a review needs another role`.

**D3 — with `job.roles` declared**, the reviewer's model is still checked by AS-2 as today; no
model-independence rule (a different role may use the same model).

## Surfaces

Layer 2: schema. Layer 5: both `shiftwork` modules (one shared check). Docs and the code-fix
template (`tools/shiftwork/example-codefix-checkpoint.json` gains `reviews`).

## Gates

Conformance (shiftwork suite): a valid reviewer plans as before; each D2 sentence per side as
a literal, from all three entry points; a `follow_ups` (#260) reviewer is checked too.

## Grouped review pilot (#307)

Added 2026-11-11. The preceding specification describes #263, implemented in
both runtimes. This extension is a **proposed planner/host policy**, not a new
runtime guarantee. Delivery and empirical results belong to
[issue #307](https://github.com/Ink01101011/bantamkit/issues/307).

### Goal and scope

Use one independent QA unit for related tasks producing one outcome. Keep each
task's execution, fast verification, attempts and accounting. Choose execution
mode separately from review scope. The checkpoint remains the sole task-state
record; briefs and referenced evidence explain decisions.

**Out of scope:** runtime/schema changes, automatic grouping, executor-identity
enforcement and automatic evidence invalidation. The issue's 20–60% savings is
an untested hypothesis. The historical
[DAG probe](../../../tools/conformance/fixtures/codec-corpus/facts/exflow-as-shiftwork-dag-measured.md)
counts theoretical serial steps, not accepted-QA latency or grouped-review cost.

### Alternatives and grouping decision

| Approach | Benefit | Limit | Decision |
| --- | --- | --- | --- |
| Explicit groups using existing fields | Boundaries follow shared acceptance criteria; no migration | Host must check coverage | Pilot first |
| Graph suggestions confirmed by planner | Reduce repetitive planning | Edges miss outcome and approval boundaries | Evaluate after explicit pilot |
| Automatic runtime grouping | Potentially less host work | New enforcement in both runtimes before evidence | Separate future proposal |

Group tasks when they share an outcome and criteria and can be checked on one
integrated revision. A chain describes order, not necessarily a review boundary.
Split at contract freezes, irreversible actions, investigation/replay and
candidate-validation gates, or when combined scope exceeds reviewer capacity.

For `A → C → D → F`, R directly names every member in both arrays, including
transitive dependencies. These are unit fragments, not complete checkpoints;
ordinary title, brief, status and verify fields are still required.

```json
{"id":"R","role":"reviewer","depends_on":["A","C","D","F"],"reviews":["A","C","D","F"]}
```

For fork/join work, K defines the shared contract, QK approves it, B/C consume
it, I integrates branches, R reviews the integrated outcome, and E consumes the
approved result. Do not make work wait for QA of its own future output.

```json
{"id":"QK","role":"reviewer","depends_on":["K"],"reviews":["K"]}
{"id":"B","role":"implementer","depends_on":["QK"]}
{"id":"C","role":"implementer","depends_on":["QK"]}
{"id":"I","role":"implementer","depends_on":["B","C"]}
{"id":"R","role":"reviewer","depends_on":["B","C","I"],"reviews":["B","C","I"]}
{"id":"E","role":"implementer","depends_on":["R"]}
```

### Execution and evidence

Record execution-mode and grouping rationale in existing briefs. Each member
retains a fast `verify` check and a clock-out. Member `done` means its work is
complete; group approval may still be pending.

| Mode | Host behavior before R |
| --- | --- |
| Inline/native | Parent executes and clocks each unit, omitting `agent_id`; use a separate reviewer context if parent contributed |
| Sequential delegates | Clock in, dispatch returned brief verbatim, close each unit as dependencies clear |
| Parallel delegates | Dispatch named ready units, respect `touches` and chosen concurrency cap, close in finish order, then run I |
| Mixed | Attribute parent/delegate contributions separately and join evidence at I |

The reviewer brief names membership, stable acceptance-criterion IDs, grouping
rationale and earlier approval boundaries; base and exact integrated revision
(or immutable artifact digests); required assumptions and source revisions;
per-member successful attempts, artifacts and fast-check results; integration
checks; and contributor identities covering parent, delegates and integration.
Explain why the reviewer contributed to none of those outputs. Role or agent-ID
differences alone do not establish independence. If identity/contribution cannot
be established, use another independent reviewer context or a human before approval.

Findings map to units or shared criteria, with severity, fixes, checks and a
verdict bound to exact membership and revision. Record compact results and
references in `history_entry.notes`/`produced`, which become attempts. Keep
full evidence in referenced artifacts: notes have a 2000-code-point limit,
three attempts are retained per unit, and history has five entries. Preserve
ledger/evidence artifacts for comparison. These conventions add no checkpoint keys.

### Approval and repair protocol

These are host obligations. Runtime checks graph structure and roles, not
approval prose, contributor independence or revision freshness. `blocked` can
be graph-ready; `dropped` satisfies a dependency. Neither `ready` nor all-terminal
`success` is proof of QA approval.

1. Before R, reconcile all required members with evidence. Missing evidence holds
   QA. A dropped member requires an explicit scope-owner decision to restore or
   replace work, or revise membership/criteria with recorded rationale. Dropping
   R is never approval.
2. Accept by clocking R out `done` only with complete coverage and passing
   integration checks on the bound revision. Before E, compare its membership,
   revision and assumptions with that verdict again. Pause dispatch when sources
   change; no automatic freshness hook exists.
3. Reject by clocking R out `blocked`, naming affected units/criteria. E keeps
   depending on R. Never clock rejected QA out `done`: that would release E.
   Pause dispatch for a serialized planner replan.
4. Preserve original completed units and unaffected siblings. Add fresh repair
   D2 depending on D and integration/recheck I2 depending on D2 and the required
   sibling outputs. Recheck transitive consumers of changed artifacts, including
   contract consumers when the contract changes. Fixes must not depend on R,
   which would form a cycle when R depends on fixes.
5. In the replan set R to `todo`, add D2/I2 to both R arrays while retaining the
   original members, and keep E depending on R. Update R's brief with new
   revision, invalidated criteria and evidence requirements. This is a planner
   edit: `follow_ups` appends units but cannot rewire existing review dependencies.
   Pause/drain in-flight writers before editing; preserve attempts and ledger;
   schema-validate the candidate and require `shiftwork_plan` acceptance before
   resuming. Keep a before/after plan artifact and handoff/history rationale.
6. Run repairs/checks and independently review the resulting revision. Issue a
   fresh whole-group verdict naming reused evidence and why it remains valid.
   Repeat until accepted or stopped by scope/budget decision. If E already ran,
   stop its consumers and reconcile effects; later QA cannot undo an effect.

Retry a transient failure with unchanged inputs/artifacts by clocking that unit
out `todo` within budget, preserving successful siblings. Changed output invokes
rework and evidence invalidation. On resume inspect attempts, ledger and current
revisions. Reconcile a durable receipt or idempotency key before replaying an
external effect; Shiftwork does not promise exactly-once execution.

Choose approval requirements from the strictest still-valid risk assessment.
Once a decision is pending, later lower-risk evidence cannot silently relax it.
Record effective requirements and sources; changing them needs an explicit
scope-owner decision and fresh review of affected criteria. These are proposed
pilot policies inspired by the issue's pinned ex-workflow inspection, not claims
that BantamKit enforces ex-workflow policies.

Under budget/reviewer pressure cap new dispatch and record why otherwise-ready
units wait (overlap, budget, reviewer capacity). Keep required checks; escalate a
scope decision if they cannot fit. Runtime wallclock budgets sum recorded unit
durations, which is different from elapsed time when units overlap.

### Matched evaluation and adoption criteria

Compare per-task and grouped review using identical tasks, criteria, base
fixtures, reviewer model/settings, fast checks and final independent oracle.
Use isolated copies; neither arm sees the other's findings. Seed defects with
an independently prepared answer key. Counterbalance order and repeat each case
three times. Publish paired results, medians, ranges and sample sizes, with
fixture IDs, revisions, prompts, host/model versions, raw usage and timestamps.

| Case | Required observations in both arms |
| --- | --- |
| Native chain | Separate reviewer; equivalent coverage with per-task reviews versus one R |
| Sequential delegates | Full-chain evidence, contribution attribution, per-unit checks retained |
| Parallel/mixed fork/join | Contract approval before consumers, integration before R, conflicting writes deferred |
| Branch failure | Retry transient failure only; preserve sibling; changed output rechecks integration |
| Evidence faults | Missing attempt, dropped member, stale source/approval and ambiguous handoff hold approval |
| Risk decision | Later lower-risk evidence cannot silently relax pending requirements |
| Budget/reviewer bottleneck | Deferral reasons; checks preserved; scope escalation counted |
| Investigation/experimentation | Existing replay/conclusion and independent candidate-validation gates preserved; validation rerun on integrated revision |

Measure review tokens separately from total tokens. Total includes planner,
dispatch, integration, retries, rework and final checks. Count rejected reviews
and repair reviews in review cost. Record rework, escalations, human interventions,
true/false findings and missed defects against the answer key. Measure elapsed
time from job start through accepted QA with host timestamps. Unapproved or timed
out runs are failed/censored observations; report time to stop separately.

Use host-reported usage and actual model per unit. Inline usage may be
inseparable from parent context: label estimates and report native totals
separately from delegated totals. Missing usage is unknown, never zero. Count every actual usage event, including repeated context processed by each
child; exclude only duplicate attribution of the same event. Include parent
overhead once per actual event. Record cached usage separately with the same
inclusion rules for both arms. Ledger duration
sums work; it does not measure parallel job latency.

For each pair with observed nonzero baseline spend:

```text
review saving = 1 - grouped review tokens / per-task review tokens
total saving  = 1 - grouped total tokens  / per-task total tokens
```

Freeze these pilot thresholds before running: all approval/coverage scenarios
hold; grouped review misses no defect caught by per-task review under the same
oracle; median total tokens decreases and median accepted-QA latency does not
increase in each execution-mode cohort. Report review savings even if total cost
loses. Gate/quality failures block adoption regardless of savings. Small samples
support only limited pilot guidance, not a general efficiency claim.

Publish paired data and limits here before changing the decision. If thresholds
pass, adopt planner guidance in tested scopes. If grouping is repetitive, evaluate
planner-confirmed suggestions on held-out chains and fork/joins. Any runtime or
schema enforcement needs a later proposal with both-runtime conformance cases.

### Evaluation record — 2026-11-11

Source baseline: `4c8874b9`. Inspect `reviewsRefusal` / `_reviews_refusal`, graph
readiness, clock-in upstream attempts, clock-out follow-ups/attempt retention,
and `assets/schemas/shiftwork-checkpoint.json`. Structural probes and conformance
checks establish representability and current limits, not review quality or savings.

Full-workflow matched-work runs have **not been performed**. The implemented
review-only replay below measures a limited component; full-workflow total
savings, live author/recovery costs and general defect coverage remain unknown.
Decision: retain explicit groups as a pilot policy; do not adopt automatic
grouping or claim that full-workflow savings are confirmed.


Verification on 2026-11-11:

- `cd runtime-ts && npm run build`: passed.
- `node tools/conformance/run.mjs --suite shiftwork`: 2875 cases passed,
  0 failures (1780 byte-identical, 1095 structural; 1 ruled difference).
- The probe below: 10 structural cases passed with equal Python/Node responses.
  In particular, dropped members and a blocked reviewer still appear ready;
  the repair graph keeps E waiting until fresh QA is marked done.
- Independent document review identified an accounting ambiguity: actual repeated
  child context usage must count, while duplicate attribution of the same usage
  event must not. The evaluation protocol above includes that distinction.

Reproduce the structural probe by saving this block to `/tmp/issue307-probe.py`
and running `.venv/bin/python /tmp/issue307-probe.py` from the repository root
(after the Node build). It writes only disposable checkpoints, calls the real
planner in each runtime and asserts readiness/refusal parity. It does not execute
work, establish reviewer independence, or simulate token savings.

```python
import copy,json,pathlib,subprocess,tempfile
from bantamkit import shiftwork as sw
root=pathlib.Path.cwd()
base=json.loads((root/'tools/shiftwork/example-codefix-checkpoint.json').read_text())
node_code="""import {planBatches} from './runtime-ts/dist/shiftwork.js'; import {toJs} from './runtime-ts/dist/pyjson.js'; console.log(JSON.stringify(toJs(planBatches(process.argv[1]))));"""
def unit(id,deps=(),role='implementer',reviews=None,status='todo'):
    u=dict(id=id,title=id,brief_path='brief.md',status=status,role=role,depends_on=list(deps),verify='true')
    if reviews is not None:u['reviews']=reviews
    return u
cases=[]
chain=[unit('A'),unit('C',['A']),unit('D',['C']),unit('F',['D']),unit('R',['A','C','D','F'],'reviewer',['A','C','D','F']),unit('E',['R'])]
cases.append(('chain',chain,['A']))
finished=copy.deepcopy(chain)
for u in finished[:4]:u['status']='done'
cases.append(('all-members-complete',finished,['R']))
dropped=copy.deepcopy(finished);dropped[1]['status']='dropped'
cases.append(('dropped-still-ready',dropped,['R']))
blocked=copy.deepcopy(finished);blocked[4]['status']='blocked'
cases.append(('blocked-review-still-ready',blocked,['R']))
repair=copy.deepcopy(blocked);repair[4]['status']='todo';repair[4]['depends_on']+=['D2','I2'];repair[4]['reviews']+=['D2','I2'];repair += [unit('D2',['D']),unit('I2',['D2','F'])]
cases.append(('repair-awaits-fix',repair,['D2']))
repair_done=copy.deepcopy(repair)
for u in repair_done:
    if u['id'] in ('D2','I2'):u['status']='done'
cases.append(('repair-ready-for-fresh-review',repair_done,['R']))
accepted=copy.deepcopy(repair_done);accepted[4]['status']='done'
cases.append(('accepted-releases-consumer',accepted,['E']))
fork=[unit('K'),unit('QK',['K'],'reviewer',['K']),unit('B',['QK']),unit('C',['QK']),unit('I',['B','C']),unit('R',['B','C','I'],'reviewer',['B','C','I']),unit('E',['R'])]
for u in fork[:2]:u['status']='done'
cases.append(('approved-contract-parallel-branches',fork,['B','C']))
join=copy.deepcopy(fork)
for u in join[2:4]:u['status']='done'
cases.append(('branches-need-integration',join,['I']))
invalid=copy.deepcopy(chain);invalid[4]['role']='implementer'
cases.append(('same-role-refused',invalid,None))
with tempfile.TemporaryDirectory(prefix='issue307-') as tmp:
    for name,units,ready in cases:
        doc=copy.deepcopy(base);doc['plan']={'cursor':next((u['id'] for u in units if u['status'] not in ('done','dropped')),units[-1]['id']),'units':units}
        path=pathlib.Path(tmp)/'checkpoint.json';path.write_text(json.dumps(doc))
        py=sw.plan_batches(str(path))
        ts=json.loads(subprocess.check_output(['node','--input-type=module','-e',node_code,str(path)],text=True,cwd=root))
        assert py==ts,(name,py,ts)
        if ready is None:assert py['result']=='error' and 'same role' in py['reason'],py
        else:assert py['ready']==ready,(name,py)
        print(name+': PASS '+json.dumps(py.get('ready',py.get('reason'))))
print('10 structural cases; Python/Node responses equal')
```


### Implementation plan — 2026-11-11

Continue in `docs/307-grouped-shiftwork-reviews`. Scope is measurement tooling,
not a shipped runtime feature. Execution is H → P → R: H implements and tests
an isolated replay harness, P runs and documents the pilot, R independently
reviews the complete result. Each unit includes implement, verify and review.
The job checkpoint is `.shiftwork/issue307/checkpoint.json`.

- [x] H: add `tools/eval/grouped_review/run_eval.py` and
  `tools/eval/grouped_review/test_run_eval.py`. Test first: paired scheduling,
  raw usage aggregation with unknowns, missing/stale evidence, contributor
  identity, repair verdicts, timeout/error persistence, and non-adoption with
  incomplete evidence. Run `.venv/bin/python -m pytest
  tools/eval/grouped_review/test_run_eval.py -q`; review scope and code quality.
- [x] P: use isolated fixture replays for native chain, delegated chain and mixed
  fork/join; run paired reviewer calls with counterbalanced order and three
  repeats when a host is available. Publish raw records and summary limits in
  `docs/eval-data/2026-11-11-grouped-review-pilot.json` and this document. Verify
  independently recomputed totals, no missing-usage-as-zero and no automatic
  adoption. Synthetic task replay measures review cost, not complete live-agent
  workflow savings; full workflow totals remain unknown.
- [ ] R: trace the final code and evaluate results against #307 and this policy,
  fix important findings, run the focused tests and repository checks, and
  record the independent verdict.

**Out of scope:** changes to `runtime-py`, `runtime-ts`, shared assets/schema,
production host dispatch policy, auto-grouping, publishing or closing #307
without the full matched-work evidence required above.


### Running the implemented replay harness

`tools/eval/grouped_review/run_eval.py` executes matched review-only replay;
`codex_adapter.py` supplies a real isolated reviewer and host-reported usage.
The adapter calls `shiftwork_draft`, `shiftwork_clock_in` and
`shiftwork_clock_out` over MCP stdio for every reviewer context. Its receipt
records completed **review execution**, not an approval that releases production
work. The harness separately decides acceptance from exact artifact/criterion
coverage, contributor context, no final findings and the deterministic oracle.
These are measurement fixtures, not a production host-policy implementation.

Both arms receive the same complete integrated context. Per-task review names
one member at a time; grouped review names all three. Each arm reviews the
seeded revision, then freshly reviews predetermined repaired fixtures. The
reviewer does not receive the oracle answer key. Author IDs and intended native,
delegated and mixed topology labels are synthetic; no implementation agents are
being benchmarked. Final approval cannot be inferred from merely finishing a call.

The included adapter requires the repository venv with MCP dependencies, a Node
build, and a logged-in Codex CLI with access to `gpt-6.1-sol`. It uses medium
reasoning, fresh contexts, read-only sandboxing, and disabled shell/apps/agent
features. It records the CLI-selected model/settings rather than a self-reported
model answer. Provider-internal routing is not independently observable. It
never changes the user's config. Generic adapters may be supplied as an argv
array; they receive JSON on stdin and return JSON on stdout. Their orchestration,
identity and actual usage reporting remain adapter obligations.

From the repository root, after `cd runtime-ts && npm run build` and returning
to the root, run this with `.venv/bin/python`:

```python
from pathlib import Path
from tools.eval.grouped_review.run_eval import run_pilot

root = Path.cwd()
run_pilot(
    root / '.shiftwork/grouped-review-run',
    [str(root / '.venv/bin/python'),
     str(root / 'tools/eval/grouped_review/codex_adapter.py'),
     '--clock-dir', str(root / '.shiftwork/grouped-review-receipts')],
    repeats=3,
    timeout=120,
)
```

The output directory must not exist. The default three cases and three repeats
make 72 reviewer calls. Commands run in fresh scratch directories, so executable
and adapter paths must be absolute. `metadata.json` freezes fixtures, command,
harness digest and host versions; `calls/` retains each request, raw adapter
stdout/stderr and normalized event; `runs.jsonl` retains accepted and failed arms;
`summary.json` records paired savings and per-mode distributions. MCP receipts
and raw Codex events live under `--clock-dir`. CLI `--summarize` recomputes results:

```sh
.venv/bin/python tools/eval/grouped_review/run_eval.py \
  --summarize .shiftwork/grouped-review-run
.venv/bin/python -m pytest tools/eval/grouped_review -q
```

Token normalization counts each Codex `input_tokens + output_tokens` event once.
Codex cached input is a subset of its input total: subtract it from uncached
input and retain it separately as cache reads. There is no additional separate
cache-creation category in that event. The four normalized categories therefore
sum to the raw total without double counting. Shiftwork's ledger excludes cache
reads from `tokens` and stores them in `cache_read_tokens`; the replay report
includes them in review tokens and preserves all categories. These totals must
not be compared without that inclusion rule. Missing usage stays unknown in the
report; a failed adapter's zero-estimate ledger sentinel does not mean free work.

Full-workflow tokens and savings are always unknown in this replay. Predetermined
repairs do not measure model-authored rework, approval negotiation, scheduling,
or author/planner/integration cost. `adoption: inconclusive` remains explicit
even if every small fixture passes and review tokens decrease.


### Measured reviewer replay results — 2026-11-11

Published [raw records, host usage events and summary](../../eval-data/2026-11-11-grouped-review-pilot.json).
Codex CLI `0.167.1`, CLI-selected `gpt-6.1-sol`, medium reasoning, three repeats
per case, nine matched pairs, 18 accepted arms and 72 fresh reviewer contexts.
Each arm reviewed the same seeded and predetermined repaired artifacts.

| Intended topology (synthetic) | Per-task review tokens, median | Grouped review tokens, median | Paired review saving, median | Replay accepted latency, per-task / grouped |
| --- | ---: | ---: | ---: | ---: |
| native-chain | 96,672 | 33,991 | 64.8% | 62.2s / 28.1s |
| delegated-chain | 95,517 | 34,116 | 64.3% | 63.6s / 26.3s |
| mixed-fork-join | 98,081 | 33,981 | 65.9% | 60.0s / 26.6s |

Across pairs, median review-token saving was **65.3%**, range **63.8–67.2%**.
Both arms caught all three seeded defects in every case/repeat, with no keyed
false findings or final findings; the fixed deterministic checks passed. The
grouped findings were manually checked against the small fixture code as well
as matched by unit/criterion key. Key matching alone is not a general semantic
finding-quality oracle. Every one of the 72 normalized totals was independently
checked against raw Codex input/output usage and its MCP ledger receipt.

Three case workflows ran concurrently, with arms sequential within each pair
and counterbalanced order by repeat. Repository verification also ran on the
host; these latency observations are not an isolated scheduler benchmark.
The default single-process reproduction above runs cases sequentially; preserve
the recorded concurrency when comparing latency. Fixed CLI/context overhead
dominates these tiny snippets, and cached tokens are included without price
weighting. The result is a count of tokens, not a dollar-cost comparison.

Two setup calls are excluded from matched samples: one sandbox initialization
failure (usage unknown) and one successful adapter smoke test (15,816 tokens).
The benchmark consumed 1,179,502 reviewer tokens including cache reads; this
excludes setup and development/orchestration costs and is not total job spend.

**Decision: inconclusive for adoption.** This replay demonstrates a working
measurement path and lower review-token overhead on these fixtures. It does
not validate actual inline/delegated author execution, approval negotiation,
risk/budget recovery, model-authored repair or broad defect coverage. Full-job
token/latency/quality claims remain unestablished, and the full policy scenarios
must still pass before adopting guidance beyond the tested review-only scope.
No automatic grouping or runtime/schema enforcement is proposed.

Offline verification of the published report (run with `.venv/bin/python`):

```python
import json
from pathlib import Path
from tools.eval.grouped_review.run_eval import summarize

report = json.loads(Path('docs/eval-data/2026-11-11-grouped-review-pilot.json').read_text())
assert summarize(report['records']) == report['summary']
for run in report['records']:
    for call in run['calls']:
        events = report['raw_host_events'][call['id']]['codex_events']
        raw = sum(e['usage']['input_tokens'] + e['usage']['output_tokens']
                  for e in events if e['type'] == 'turn.completed')
        assert raw == call['review_tokens'] == sum(call['usage'].values())
```


### Handoff at maintainer stop request — 2026-11-11

Implementation and reviewer replay are recorded, but **the harness is not yet
approved for shipping**. Independent final review validated the summary, 72 raw
usage/cache/ledger reconciliations, 72 unique host contexts and sampled findings.
Two Important findings remain for the next implementer:

1. **Descendant cleanup on timeout:** `run_eval.invoke` uses `subprocess.run`;
   its timeout kills only the adapter, potentially leaving the Codex descendant
   active. A benign child writing a marker after a 200ms timeout reproduced it.
   Terminate the whole process group or coordinate cancellation and MCP cleanup;
   add a regression proving no descendant survives and no next call overlaps it.
2. **Preserve known failed-call cost:** `codex_adapter.normalize_events` rejects
   failed/tool-using/malformed answers before extracting usage; `review` records
   an unknown zero-estimate ledger, and `invoke` skips JSON usage on nonzero exit.
   Separate usage extraction from response validity and propagate a failed-call
   envelope carrying known usage while retaining error/blocked status. A raw
   completed event with input=100, cached=40 and output=8 must retain 108 report
   tokens (68 ledger tokens plus 40 cache-read tokens) even with invalid JSON.

These findings do not invalidate the published successful-call measurements.
Preserve their `executed_source` snapshots and hashes. Current code includes
post-run explicit UTF-8 declarations and formatting; it is not byte-identical to
that executed snapshot. Do not overwrite historical provenance with current code.

Latest verification: focused harness + encoding gate **446 passed, 2 skipped**;
local-HTTP tests rerun outside the socket-restricted sandbox **44 passed**;
Shiftwork conformance **2875 passed, 0 failures**; repository Ruff and diff checks
passed. The earlier complete Python run reported 5051 passed with three new-file
encoding gate failures and six local-socket failures/errors; those paths were
rechecked as above. A fresh complete Python run has not been performed after
the portability correction. No runtime/schema changes, commit, push or PR.

The maintainer requested stopping here and handing the remaining work to Claude.
The local checkpoint is `.shiftwork/issue307/checkpoint.json`; H/P/H2 are done,
and R is blocked on the two Important findings. Resume with fixes and fresh
independent review. Full live-workflow evaluation and an adoption decision remain
outside the completed review-only replay; #307 must not be marked complete merely
because this benchmark shows fewer reviewer tokens.

### Fixes after the handoff — 2026-11-11

Both Important findings above are addressed in the harness only (no runtime,
schema or published-data change; the pilot's `executed_source` snapshots and
hashes are untouched and remain the provenance of the 72 measured calls).
Independent review of unit R ran three more rounds. Rounds 2 and 3 each blocked
on a Windows containment gap, which led to the next fix below. Round 4 approved
with Minor findings only.

1. **Descendant cleanup.** `run_eval.run_contained` replaces `subprocess.run`.
   - *POSIX (measured on macOS):* the adapter leads a new session, and its whole
     process group is killed on timeout, on any error, and after a normal or
     nonzero exit. A process that deliberately leaves the group (`setsid`) is
     outside the guarantee. It can no longer hang a call, because reading pipes
     after the kill is bounded by `DRAIN_SECONDS`. If the adapter itself exited
     before the deadline and only a straggler held the pipe, its own exit status
     and printed output stand rather than being reported as a timeout.
   - *Windows (reasoned, never executed on Windows):* the adapter is created
     `CREATE_SUSPENDED`, its own handle is assigned to a Job Object, and only then
     is it resumed (`NtResumeProcess`). Nothing, not even a venv `python.exe`
     launcher, runs before it is inside the job. `TerminateJobObject` kills every
     member on the same three paths. A terminate that fails raises rather than
     passing silently. The job also carries `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`,
     so its members die if the harness itself is killed first. Any failure while
     jailing kills the suspended adapter and closes its pipes, and a failing kill
     cannot mask the jailing error. The call sequence and failure paths are tested against
     stubbed `kernel32`/`ntdll`. The drain bound and partial timeout output are
     POSIX-only. On Windows they rely on the job holding every pipe holder: once
     the job is terminated the pipes reach EOF and printed output is kept, unless
     something outside the job holds a pipe.
2. **Known failed-call cost.** `codex_adapter.extract_usage` reads usage
   independently of answer validity. A failed review clocks out `blocked` with
   that usage in the ledger, and `main` prints a `{status: blocked, error, model,
   settings, usage, receipts}` envelope and exits 1. `run_eval.invoke` keeps the
   envelope's usage on a nonzero exit while the call stays failed and unapproved.
   Raw input 100 / cached 40 / output 8 with an invalid answer keeps 108 report
   tokens and a 68 + 40 cache-read ledger line, not an estimate. Missing usage
   still stays unknown.

Verification:
- Harness tests: 60 passed, up from 41 at the maintainer's handoff. That count
  includes the Minor hardening added after round 4 approved, reviewed as unit R2.
  A terminate that fails falls back to closing the KILL_ON_JOB_CLOSE job, so the
  adapter's own result is kept. A jailing failure closes the job before a bounded
  wait. A test pins the x64 job-limit layout.
- Every new behavioural regression test was checked red against the earlier
  code: the pilot's executed snapshots, or the previous fix round.
- The full Python suite passed 5114 with 0 failures (58 skipped, 3 xfailed)
  after the Windows suspended-start fix.
- Ruff and diff checks are clean.
- No Windows host or CI has run any of this.

Still open, as before: full live-workflow evaluation and the adoption decision.
#307 is not complete, and nothing here claims full-workflow savings.

### Decision — design closed by scope split (2026-11-11)

The maintainer closed #307's design scope. The *Implementation plan* above had
listed closing #307 without full matched-work evidence as out of scope; this
decision supersedes that line. The efficiency question is not answered. It
moves out of #307, and nothing below claims full-workflow savings.

1. **Adopted: explicit groups as planner guidance.** A planner may group related
   units under one reviewer when they share an outcome and acceptance criteria and
   can be checked together on one integrated revision. List every member in both
   the reviewer's `reviews` and its `depends_on`. Split a group at any point that
   needs approval before downstream work. Keep fast checks per unit. Use a
   separate reviewer context when the parent session authored the work. This is
   guidance only: no runtime or schema behaviour changes, automatic grouping is
   not adopted, and the measured evidence is the review-only replay
   (review-token median saving 65.3% on synthetic fixtures; see *Measured
   reviewer replay results* above and
   `docs/eval-data/2026-11-11-grouped-review-pilot.json`).
2. **Implementation, #309:** the correctness gap does not depend on savings, so it
   proceeds now. A reviewer whose `reviews` names a `dropped` unit still becomes
   ready and can be approved without anyone deciding to shrink its scope. The
   structural probe in *Evaluation record* answers `dropped-still-ready: ["R"]`
   with equal Python and Node responses. It was rerun on `main` at e0968c0c on
   2026-11-11. #309 will hold such a reviewer until the scope decision is
   explicit, in both runtimes with conformance cases; until it lands, the gap
   remains. `blocked` reviewers staying ready is intended
   (retryable) and unchanged.
3. **Evaluation, #310:** the full live-workflow matched evaluation, run against the
   frozen thresholds in *Matched evaluation and adoption criteria*. Only its
   result can widen the guidance in (1) or justify any further runtime or schema
   proposal.

### Live core-mode evaluation results — 2026-11-13 (#310)

Published [records, raw host events and summary](../../eval-data/2026-11-13-grouped-review-live-core.json).
Design: [`2026-11-13-grouped-review-live-eval-design.md`](2026-11-13-grouped-review-live-eval-design.md).
The frozen thresholds above are applied unchanged.

Scope: the three core execution modes only (native chain, sequential delegates,
parallel/mixed fork/join). The five scenarios (branch failure, evidence faults,
risk decision, budget/reviewer bottleneck, investigation) were **not run**.
Authors, repairers and reviewers are live Codex CLI `0.167.1` agents
(`gpt-6.1-sol`, medium reasoning) under an isolated Codex home. Planner and
dispatcher are deterministic harness code, zero model tokens in both arms.
Every unit is a real Shiftwork unit in a per-arm checkpoint. 18 arms ran one at a
time from 09:21:19 to 10:03:54 UTC: 3 modes × 2 arms × 3 repeats, arm order
counterbalanced by repeat. Harness commit `c81be51c`; the executed sha256s of
`live_run.py`, `live_cases.py`, `run_eval.py` and `codex_adapter.py` equal the
files at that commit.

Hygiene: 0 harness-censored arms, no voided attempts, no unknown usage, the
access audit clean and no write conflicts in all 18 arms. No escalations and no
human interventions. No call reported a nonzero `cache_write_input_tokens`.

| Mode | Arm | Total tokens, median (range) | Review tokens, median (range) | Accepted latency, median (range) | Accepted |
| --- | --- | ---: | ---: | ---: | ---: |
| native-chain | per-task | 350,424 (329,303–355,243) | 70,186 (69,641–70,208) | 156.4s (151.2–163.1) | 3/3 |
| native-chain | grouped | 314,703 (301,983–316,997) | 30,412 (30,338–30,526) | 129.6s (128.2–132.2) | 3/3 |
| sequential-delegates | per-task | 356,395 (342,181–371,250) | 69,471 (69,329–69,548) | 159.6s (157.6–160.4) | 3/3 |
| sequential-delegates | grouped | 317,218 (303,595–361,610) | 30,072 (29,980–45,904) | 126.8s (118.4–135.2), n=2 | 2/3 |
| mixed-fork-join | per-task | 384,304 (366,316–385,018) | 78,390 (75,212–81,536) | 125.7s (122.0–144.7) | 3/3 |
| mixed-fork-join | grouped | 360,618 (360,058–376,390) | 56,180 (54,656–56,260) | 132.8s (127.6–137.3) | 3/3 |

Token totals include cache reads, unweighted; they are counts, not dollars. The
stopped sequential-delegates grouped arm is in the token columns (spend to stop)
but not in latency; its time to stop was 169.1s.

Paired savings (frozen formulas, three pairs per mode):

| Mode | Review saving, median (range) | Total saving, median (range) |
| --- | ---: | ---: |
| native-chain | 56.5% (56.4–56.7%) | 10.8% (4.4–13.8%) |
| sequential-delegates | 56.8% (33.8–56.8%) | 7.3% (2.6–14.8%) |
| mixed-fork-join | 28.3% (27.3–31.0%) | 6.2% (−2.8–6.5%) |
| all nine pairs | 56.4% (27.3–56.8%) | 6.5% (−2.8–14.8%) |

The 33.8% sequential-delegates pair is the one whose grouped arm stopped. Without
cache reads, median total saving is 41.7%, 35.2% and 6.6% by mode (mixed-fork-join
range −42.6% to 32.1%).

Quality: every arm had two seeds and all 36 were caught at their first review.
Grouped review missed no seed that per-task review caught. In the fork/join mode
the contract seed (K) is caught by the QK gate in both arms, so only seed C
tests grouping there. The final hidden oracle passed 9/9 criteria in all 18 arms,
including on the stopped arm's last revision. There were 36 true findings and 2
false findings by the oracle rule. Both false findings were in the stopped arm
(below). Rework rounds: per-task arms always took 2, one per seeded unit.
Grouped native-chain and sequential-delegates arms took 1, both seeds in one
rejection, except the stopped arm with 3. Grouped fork/join took 2, QK then R.

Per-mode threshold verdicts:

| Mode | No grouped miss | Median total decreases | Latency not increased | Approval/coverage holds | Verdict |
| --- | --- | --- | --- | --- | --- |
| native-chain | yes | yes | yes | yes | **pass** |
| sequential-delegates | yes | yes | yes | **no** | **fail** |
| mixed-fork-join | yes | yes | **no** | yes | **fail** |

**Sequential delegates, repeat 2, grouped.** R rejected three times. The cap of
two repair rounds was reached, a protocol stop that counts against the threshold.
The hidden oracle was run on each reviewed snapshot afterwards, whole and per unit:

1. Review 0 found both seeds (A-fields: no strip before matching; C-filter:
   negated level comparison). Both were true. The oracle failed A-fields and all
   three C criteria, which is the failing set the seeding step recorded for those
   two seeds. Repairs A2-r1 and C2-r1 fixed both. At the next snapshot the oracle
   passes 9/9.
2. Review 1 found A-invalid: `re.IGNORECASE` covers the whole pattern, so a
   lower-case `t`/`z` timestamp is accepted. That is true of the code; the
   snapshot accepts `2026-01-01t00:00:00z INFO app: hello`. Task A fixes the
   format as `YYYY-MM-DDTHH:MM:SSZ`, so it deviates from the written task. The
   hidden oracle does not test it and passes, so the frozen rule scores it false.
   The flag was already present at review 0, which did not raise it. Repair A2-r2
   scoped the flag to the level, and the probe then returns None. The last
   review snapshot of every other sequential-delegates arm rejects that line.
3. Review 2 found B-order: `strftime('%Y')` might not zero-pad years below 1000
   "on Unix platforms". `window.py` was byte-identical across all three reviews.
   On the host that ran the oracle (macOS), the snapshot sorts `0999-12-31` before
   `1000-01-01` correctly. The oracle passes, so the finding is scored false. Other
   platforms were not tested.

So R did not keep rejecting one real defect that repairs failed to fix. Every
finding it raised was repaired by the next round. Each later round raised a new
finding on code that had not changed since review 0. One was a real but
oracle-untested deviation from the task. The other did not reproduce on the
evaluation host. The arm stopped on reviewer non-convergence, not on a missed or
unfixed defect. The frozen protocol counts that as an approval failure. The
per-task arm of the same repeat was accepted in 160.4s.

**Mixed fork/join latency.** Paired accepted latencies, per-task / grouped:
repeat 0 144.7s / 137.3s, repeat 1 125.7s / 132.8s, repeat 2 122.0s / 127.6s.
Repeat 1 ran grouped first, the others per-task first. The grouped median is
7.1s (5.6%) higher. That is smaller than the per-task arm's own run-to-run range
of 22.8s (grouped: 9.7s). One of the three pairs went the other way; excluding it (repeat 0), grouped
was slower in both remaining pairs, by 7.1s and 5.6s. After B∥C,
per-task runs QA_B∥QA_C, C2, QA_C, I, QA_I. Grouped runs I, R, C2, R. Each group
review took 8.6–12.5s, against 5.6–9.8s for a per-task QA_B, QA_C or QA_I review. The data do
not show grouping is slower in this mode. They also do not show it is not
slower, and the frozen threshold, applied as frozen, fails.

Spend. Every Codex token #310 spent, cache reads included:

| Item | Tokens |
| --- | ---: |
| resume-usage probe | 58,587 |
| skills probe (3 calls) | 59,618 |
| isolated-home probes (3 calls) | 46,553 |
| censored first smoke arm | 73,964 |
| valid smoke pair (366,722 + 374,041) | 740,763 |
| matched run (18 arms) | 6,253,606 |
| **total** | **7,233,091** |

The three probe figures come from the job's checkpoint history notes; their raw
events are not published. The smoke figures and the run are recomputed from raw
rows by the check below. Smoke data are outside the matched sample.

Limits: three repeats per mode support limited pilot guidance only. Three repeats
leave a 2:1 order imbalance per mode. Seeds are loud mutations, so the
missed-defect check has little power against subtle defects. Single host, single
model, one reviewer setting. A real orchestrator spends planner and dispatch
tokens that this harness does not. Elapsed time is host wall clock with jobs run
one at a time; seeding time is excluded from accepted latency. The full list is
the `limitations` field in the published summary. For a resumed parent call,
`calls/<id>/call.json` on disk reports the session's cumulative usage. The
published per-call usage is the per-thread delta. The raw last row is kept as
`reported_cumulative`. No fresh call had more than one `turn.completed` row.
All 170 calls had exactly one.

Published file, 2,183,434 bytes: run metadata, the 18 records, the summary, every
Codex event, argv, prompt and stderr per call, and the smoke usage rows. Not
published: Codex session rollouts and any auth material. Also not published: arm
workspaces and snapshots, and the on-disk `call.json`. Absolute paths and the
local user name are replaced by `$REPO`, `$RUN`, `$EVAL`, `$HOME`, `$TMPDIR` and
`$USER`.

Open harness items, none affecting these numbers:

1. A timeout leaves the next resumed call on that thread with no baseline, so it
   becomes unknown too. Such a pair is voided anyway. None occurred.
2. `call.json` shows cumulative usage for resumed calls; publish from records.
3. The cache-write flag would repeat on later resumed calls of a thread, because
   it reads the cumulative row. No nonzero value occurred.
4. A clock-out note gives a stale hard-coded reason.
5. A fresh parent call with more than one `turn.completed` row would be summed
   while later resumes subtract its last row. None occurred.
6. A comment in `live_run.py` says `Arm.model` and means `Arm.account`.
7. The sequential-delegates oracle does not test the timestamp's letter case.

**Decision: blocked.** native-chain passes every core-mode threshold.
sequential-delegates fails approval/coverage (one grouped arm stopped at the
rejection cap). mixed-fork-join fails latency. A failing mode blocks adoption for
that mode, so grouped review is not adopted for sequential delegates or mixed
fork/join. For native chain, the best this job can record is "core mode passes;
adoption beyond review-only guidance waits for the scenarios". The scenarios were
not run, so no mode can be adopted beyond the review-only guidance in
*Decision — design closed by scope split* item 1. That guidance stands
unchanged. Grouped review used a median 56.4% fewer review tokens across the
nine pairs, and median total saving was 6.5%. These savings are reported as the
protocol requires and do not override the gate failures. No runtime or schema
change is proposed.

Offline verification of the published report (run from the repo root with `.venv/bin/python`):

```python
import json
from pathlib import Path
from tools.eval.grouped_review.live_run import summarize_live

report = json.loads(Path('docs/eval-data/2026-11-13-grouped-review-live-core.json')
                    .read_text(encoding='utf-8'))
assert summarize_live(report['records']) == report['summary']
F = ('input_tokens', 'cached_input_tokens', 'output_tokens')


def check(run, rows_of):
    last, total, review = {}, 0, 0
    for call in run['calls']:
        rows = rows_of(call)
        if call['resumed']:  # cumulative: this call's last row minus the thread's previous
            own = {k: rows[-1][k] - last[call['thread_id']][k] for k in F}
        else:                # fresh: its own rows
            own = {k: sum(r[k] for r in rows) for k in F}
        last[call['thread_id']] = rows[-1]
        u = call['usage']
        assert (u['uncached_input'], u['cache_read'], u['output']) == (
            own['input_tokens'] - own['cached_input_tokens'],
            own['cached_input_tokens'], own['output_tokens'])
        n = u['uncached_input'] + u['cache_read'] + u['output']
        total += n
        review += n if call['kind'] == 'reviewer' else 0
    assert (total, review) == (run['total_tokens'], run['review_tokens'])


events = report['raw_host_events']
for run in report['records']:
    check(run, lambda c: [e['usage'] for e in events[c['id']]['codex_events']
                          if e['type'] == 'turn.completed'])
for name in ('smoke', 'smoke2'):
    for run in report['setup_spend'][name]['runs']:
        check(run, lambda c: c['turn_completed'])
spend = report['total_codex_spend']
assert spend['matched_run'] == sum(r['total_tokens'] for r in report['records']) == 6253606
assert spend['smoke_censored_arm'] + spend['smoke2_pair'] == sum(
    r['total_tokens'] for n in ('smoke', 'smoke2') for r in report['setup_spend'][n]['runs'])
assert spend['total'] == sum(spend['probes'].values()) + spend['smoke_censored_arm'] \
    + spend['smoke2_pair'] + spend['matched_run'] == 7233091
```
