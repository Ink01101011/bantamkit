---
name: public-install-is-pure-node-by-ruling
description: the user ruled the bantamkit MCP must be a pure node npx install with
  no python at runtime, which overturns the pypi-uvx-first recommendation, and what
  the port actually costs
type: project
created: '2026-08-22'
last_recalled: '2026-09-19'
links:
- project-backlog-public-install-for-mcp
- project-bantamkit-pending-user-decisions
- feedback-must-run-on-windows-not-just-macos
- memory-budget-precondition-discharged
---

RULED BY THE USER 2026-08-22, overturning my PyPI-first recommendation in [[project-backlog-public-install-for-mcp]]. Their words: "เป้าหมายในการ publish คือทีมฉันใช้ node npx ก็ควรใช้แค่ npx แล้วรัน node แทน pipe/uv". So: `npx` runs NODE. No Python at runtime, no uv/pipx bootstrap, no thin shim over a Python package. Do not re-argue it.

WHY THE SHIM ROUTE WAS REJECTED, measured on this machine 2026-08-22: `uv` and `uvx` are NOT INSTALLED; `pipx` 1.11.1, `node` v25.2.1, `npx` 11.6.2, `python3` 3.12.13 via mise. A Node shim over the Python package therefore needs its own Python bootstrap on a machine that has no uv, which is the failure the user is refusing to ship to a team.

WHAT THE PYTHON PACKAGE ALREADY DOES, so the port has a working oracle to copy: a clean venv outside the repo (`pip install "runtime-py[mcp]"`) gives console script `bantamkit-mcp`, a real stdio handshake from an unrelated cwd, 7 tools (build_identity, memory_recall, memory_save, shiftwork_clock_in/out/status, validate_json), and the asset pack resolving INSIDE site-packages. Version agrees 0.25.0 both ways there, so the local 0.3.0-vs-0.25.0 mismatch is a repo-venv artifact and NOT a packaging defect - it would not have shipped.

PORT SURFACE, measured: runtime-ts holds exactly ONE tracked file, so there is no head start. The 7 tools need ~1,846 lines across mcpserver.py 421, memory/store.py 434, client.py 329, shiftwork.py 212, memory/component.py 197, structured.py 125, memory/layers.py 67, assets.py 49, plus contract.py uncounted. docread and pdfread are NOT needed - the heaviest modules are out of scope. Asset pack is 78 files but the server needs only skills/tools/rubrics/schemas/profiles, about 16; the other 62 are eval fixtures npm must not carry.

THE NEW RISK NOBODY MEASURES YET: two implementations of one behaviour, in a program whose whole discipline is measured-before-written with demonstrated-red nodes. Parity between Node and Python is unmeasured by anything. Mitigation to build with the port, not after: a conformance suite driven from the shared asset pack, gated the same way job33 gates store divergence.

PREREQUISITE, not parallel work: [[project-memory-store-binding-defect]] must land first. A teammate installing fresh gets `memory_recall -> "no memories matched. Try different words, or proceed without."` when the truth is that no store exists at all - measured live in the clean-venv probe. Shipping that to a team teaches them the tool is useless on day one.

SCOPE LINE: prepare means no publish. Nothing is pushed to npm or PyPI and nothing is tagged - tag has never been authorized on this repo, see [[project-bantamkit-pending-user-decisions]].
