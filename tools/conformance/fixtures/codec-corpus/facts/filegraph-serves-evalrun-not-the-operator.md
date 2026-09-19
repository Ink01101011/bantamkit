---
name: filegraph-serves-evalrun-not-the-operator
description: why the graph tool cannot help the agent doing the work - it is wired
  to evalrun's own Agent and there is no path from it to Claude Code tool calls
type: project
created: '2026-08-22'
last_recalled: '2026-09-19'
links:
- project-graphify-measured-net
- seven-tools-audited-by-running-them
---

Checked 2026-08-22 against the user's ruling that a tool counts as working only if it genuinely helps the agent do its job. FileAccessGraph is INSTANTIATED IN EXACTLY ONE PLACE: evalrun.py:1723, with readers={'read_file': 'path'} - the eval harness's own workspace tool. Its setup(agent) attaches to bantamkit's Agent class. The operator agent (Claude Code) uses Read/Grep/Bash, which are not that Agent and do not pass through that hook, so there is NO PATH from filegraph to the reads that actually cost tokens in a working session. This is a structural fact, not a defect. WHAT IT DOES DO, where it is wired, and both halves must be kept apart: cache/annotate pays only on a repeat and is NET POSITIVE - minus 3.014 percent context on the scripted reference walk, worst realised case 0, never a loss, break-even file size 99-105 bytes against a surface median of 392. query is a 649 byte constant in EVERY request whether used or not - plus 21.63 percent on the same walk, and plus 73.367 percent at the live endpoint, where RB-P39 splits it into x1.3667 more turns by x1.3830 bigger turns so 49.1 percent of the cost is the trajectory query induced rather than the apparatus. CONSEQUENCE: 'graph works 100 percent' under the helps-the-operator reading is NOT reachable by fixing filegraph. It would need a different thing - a read ledger over the operator's own tool calls - and the operator cannot instrument its own harness from inside. Report filegraph's cost split honestly and stop treating its retrieval story as a pending measurement; render() emits one line per path, 'path - N read(s) via tool, changed|unchanged', with no content, no line numbers and no search.
