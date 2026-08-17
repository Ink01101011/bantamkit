# File-access graph

`FileAccessGraph` keeps a deterministic ledger of every file the agent
reads: which path, via which tool, how many times, and whether the content
changed between reads. The write path is plain Python — no model is
involved — so its correctness is pinned by offline tests, not calibrated.

## Attach it

```python
from bantamkit import Agent, FileAccessGraph

graph = FileAccessGraph(readers={"read_file": "path"})
agent = Agent(client=client, tools=[read_file_tool]).use(graph)
```

`readers` maps tool name → the argument holding the file path. Only
declared readers are tracked; tools registered after `use(graph)` are
still wrapped (registration is intercepted), but tools appended directly
to `agent.tools` bypass the graph. Observations starting with `error:`
(the harness-wide failure convention) are also never recorded — genuine
file content beginning with that prefix is invisible to the ledger.

## The three mechanisms

Each is independently toggleable:

- **`annotate`** — a repeat read gets a one-line prefix:
  `[file-graph] read #2 of config.yaml via read_file — unchanged since
  your last read` (or `CHANGED`). First reads pass through
  byte-identical. With `cache` also on (the default), the unchanged case
  collapses to the cache marker instead — the prefix form appears on
  changed content, or when `cache=False`.
- **`cache`** (verify-on-repeat) — the real handler runs on *every* call;
  when the fresh content hashes identical to the previous read, the
  observation is replaced with a short marker instead of repeating the
  content. What is saved is model tokens, not disk I/O — the marker can
  never be stale, because it is only issued after re-reading.
- **`query`** — registers a `file_graph` tool returning the ledger
  (`path — N read(s) via tool, unchanged|changed`; *changed* is sticky —
  it means changed at least once, not changed on the last read) plus a
  system-prompt
  snippet telling the model to consult it before re-reading.

## Persistence (opt-in)

`graph.save(path)` / `graph.load(path)` round-trip the ledger as JSON.
The core lifecycle is per-run; persistence is API only — no cross-session
uplift is claimed or measured yet. Only resume a saved ledger together
with the transcript it was built against — restored entries collapse
repeat reads to markers a fresh model has never seen the content behind.

## Measured

See [Eval → Current results](eval.md#current-results): the `graph` config
is `bare` + `FileAccessGraph` on tasks with workspace file tools (the
file-nav candidate family), with ablation
configs (`graph-annotate`, `graph-cache`) used during calibration to
attribute which mechanism moves the number.

### What the repeat machinery needs, and when it gets nothing

`annotate` and `cache` both act **only** on a repeat read, and `cache`
collapses only a **byte-identical** one. So their entire opportunity set
is reads whose content the request already carries — and on a surface
where the agent never re-reads a file, both are inert by construction,
not by degree.

**Measured, on a dev-repo-shaped surface (2026-08-17).** Across an 8-task
repo workload at the ~4B class, the model realised **0** byte-identical
repeat reads on **8 of 8** tasks in all 24 `graph-off` runs, against a
verified reference walk's 3. The consequence is exact: `graph-off`,
`graph-annotate` and `graph-cache` are **identical on every one of 16
columns across all 24 rows** — four configurations, two distinguishable
rungs. Two things follow, and neither is a limitation of this
implementation:

- **A bigger model is not a route to a non-zero repeat delta.** A
  collapsible repeat is a redundant read, so a stronger model should
  realise fewer of them.
- **The workload could not have shown otherwise.** Strip every repeat hop
  from all eight declared walks and all eight still solve the tasks, at
  re-read pressure `0/30`. No task on that surface *requires* a second
  read, so there was no repeat for the mechanism to find.

On such a surface the only mechanism with anything to do is `query`, and
it **cost `+73.367%` tokens** against `graph-cache` — roughly half of
that from the longer conversation the tool induced rather than from the
tool's own bytes — while moving pass-set points in both directions. Read
it as a trade, and note that `query_bytes` is a per-request constant plus
render, so it is re-sent every model call.

**No token saving is claimed here or anywhere else for this component.**
`cache` saves *observation* bytes, never disk I/O — the inner reader runs
first, unconditionally, on every call. And the saving can be negative:
the collapse marker measures **98-103 B**, so collapsing an observation
smaller than that **adds** bytes (measured: a 5 B observation under
`notes/a.md` collapses to a 103 B marker, for `-98`). That is not a
corner case on a surface whose median file is **392 B**, under 4x the
marker. `collapsed_bytes` and `annotate_marker_bytes` are therefore
**signed and never clamped at zero** — a floor there would report a cost
as break-even and bias the run total in the mechanism's favour.

The full record, the pre-registered bar it was measured against, and the
nine findings it left open:
[Eval → M](eval.md#m-2026-08-17-v0220--the-dev-team-workload-surface-and-what-it-could-not-show).
