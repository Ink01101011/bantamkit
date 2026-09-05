# bantamkit

Harness primitives that lift small-model agents: a per-person memory store, JSON
validation, shift-work accounting, a document reader, and a skill-catalogue
auditor — served to any MCP host over stdio.

This is the **Python** distribution. There is a second, independent
implementation of the same surface on npm as
[`bantamkit-mcp`](https://www.npmjs.com/package/bantamkit-mcp), written in pure
Node. The two share a memory store on disk and are held to the same answers by a
conformance suite, so you can install whichever one your host makes easy. What
the two do *not* agree on is written down in
[`docs/porting.md`](https://github.com/Ink01101011/bantamkit/blob/main/docs/porting.md)
and summarised at the bottom of this page.

## Install and run

```bash
pipx run --spec "bantamkit[mcp]" bantamkit-mcp --assets-root
```

or into an environment you keep:

```bash
pip install "bantamkit[mcp]"
bantamkit-mcp --help
```

The `[mcp]` extra pulls the MCP SDK. Without it you still get the library and the
operator CLI, but not the server.

The uv equivalent is `uvx --from "bantamkit[mcp]" bantamkit-mcp`. uv is not
installed on the machine this README was measured on, so unlike every other
command here that one is the documented form rather than a measured one.

### As an MCP server

```json
{
  "mcpServers": {
    "bantamkit": {
      "command": "pipx",
      "args": ["run", "--spec", "bantamkit[mcp]", "bantamkit-mcp"]
    }
  }
}
```

Point `--start` at a directory to choose where project-store discovery begins, or
`--store` at a single path to disable layering entirely. Do not reach for
`--store` by reflex: the default is layered, and the layering is most of the
value.

## What it serves

Eleven tools, measured off a wheel installed into an empty virtualenv:

| tool | what it does |
|---|---|
| `memory_save` | store one durable fact, deduped and budgeted |
| `memory_recall` | retrieve facts matching a query |
| `memory_compact` | archive the stalest facts to fit the index budget |
| `validate_json` | validate a document against a JSON Schema |
| `bantamkit_read` | read a document — text, office formats, pdf |
| `skill_audit` | audit a skill catalogue for findings |
| `shiftwork_clock_in` | open a unit of work and get its brief |
| `shiftwork_clock_out` | close a unit with status and accounting |
| `shiftwork_status` | report the open cursor |
| `bantamkit_status` | report store health against its budget |
| `build_identity` | report the fingerprint of the source on disk |

`build_identity` describes the tree on disk, not the code currently executing —
useful precisely when a machine carries two installs under one name.

## Requirements

Python 3.11 or newer. Three runtime dependencies — `httpx`, `jsonschema`,
`pyyaml` — plus `mcp` under the `[mcp]` extra.

## The asset pack

Contracts, schemas, eval tasks, rubrics and tool manifests ship inside the
package and are located at import time:

```bash
bantamkit-mcp --assets-root
```

It prints the resolved directory and its file count. A build that cannot find the
pack fails rather than producing an artifact without it — that refusal is
deliberate, because the silent version of it shipped once.

`BANTAMKIT_ASSETS` overrides the location.

## The operator CLI

Memory-store maintenance is a separate surface from the agent-facing tools, and
it is not served over MCP:

```bash
python -m bantamkit.memory status     # index size, budget, headroom, archives
python -m bantamkit.memory lint       # exit 1 if malformed or over budget
python -m bantamkit.memory compact    # archive the stalest facts
python -m bantamkit.memory archive <name>
python -m bantamkit.memory restore <name>
```

`archive` moves a fact out of the store without deleting it; `restore` brings it
back by name.

## Sharing a store with the Node server

Both distributions read and write the same on-disk format, so one store can be
served by either. That is also why a surface present in one and absent from the
other is not merely a coverage gap — it is a way for two servers to disagree
about one person's data. Every feature lands in both implementations in the same
change, and a conformance case compares the two answers before it counts as
ported.

## Where the two implementations differ, on purpose

- **This side reads pdf, `.doc` and `.rtf`; the Node side refuses them by name.**
  PDF is read by a stdlib reader written for this project; real OLE2 `.doc` and
  `.rtf` go through `/usr/bin/textutil`, a macOS built-in that is probed at every
  call and refused by name where it is absent.
- **The operator CLI is spelled differently**, and it shows in help text and
  error messages: `python -m bantamkit.memory` here against `bantamkit-memory`
  there. There is no third spelling — a pure-npm install has no Python in it, and
  CPython does not install that console script.
- **`build_id` hashes the executing tree**, and the two runtimes are two trees, so
  it differs by construction. `assets_digest` is identical, and that is the one
  that carries meaning.

Each of these is recorded in the divergence table with a conformance case pinning
the wording, so the difference cannot drift unnoticed.

## Development

```bash
git clone https://github.com/Ink01101011/bantamkit
cd bantamkit
python -m venv .venv && .venv/bin/pip install -e "runtime-py[dev,mcp]"
.venv/bin/python -m pytest runtime-py/tests -q
.venv/bin/ruff check runtime-py
```

The cross-runtime gate needs Node:

```bash
node tools/conformance/run.mjs --all
```

## Links

- Source: https://github.com/Ink01101011/bantamkit
- The Node distribution: https://www.npmjs.com/package/bantamkit-mcp
- Install notes: [`docs/install.md`](https://github.com/Ink01101011/bantamkit/blob/main/docs/install.md)
- What the two runtimes disagree about: [`docs/porting.md`](https://github.com/Ink01101011/bantamkit/blob/main/docs/porting.md)

MIT.
