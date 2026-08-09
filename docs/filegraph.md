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
to `agent.tools` bypass the graph — the one documented gap.

## The three mechanisms

Each is independently toggleable:

- **`annotate`** — a repeat read gets a one-line prefix:
  `[file-graph] read #2 of config.yaml via read_file — unchanged since
  your last read` (or `CHANGED`). First reads pass through byte-identical.
- **`cache`** (verify-on-repeat) — the real handler runs on *every* call;
  when the fresh content hashes identical to the previous read, the
  observation is replaced with a short marker instead of repeating the
  content. What is saved is model tokens, not disk I/O — the marker can
  never be stale, because it is only issued after re-reading.
- **`query`** — registers a `file_graph` tool returning the ledger
  (`path — N read(s) via tool, unchanged|changed`) plus a system-prompt
  snippet telling the model to consult it before re-reading.

## Persistence (opt-in)

`graph.save(path)` / `graph.load(path)` round-trip the ledger as JSON.
The core lifecycle is per-run; persistence is API only — no cross-session
uplift is claimed or measured yet. Only resume a saved ledger together with the transcript it was built against — restored entries collapse repeat reads to markers a fresh model has never seen the content behind.

## Measured

See [Eval → Current results](eval.md#current-results): the `graph` config
is `bare` + `FileAccessGraph` on the file-nav task family, with ablation
configs (`graph-annotate`, `graph-cache`) used during calibration to
attribute which mechanism moves the number.
