---
name: tool-call-batching-is-already-spent
description: where the agent's tool calls actually go and why cutting them 5x is not
  available - Bash is 96 percent and already carries 14.5 commands per call
type: project
created: '2026-08-22'
last_recalled: '2026-09-12'
links:
- shiftwork-unit-cost-is-linear-in-tool-calls
- project-token-levers-measured-on-real-corpus
---

Measured 2026-08-22 over 67 subagent transcripts from this session, 8,846 JSON lines, by counting tool_use blocks directly rather than estimating. TOOL MIX: 3,029 tool_use blocks total - Bash 2,907 = 96.0 percent, Edit 77 = 2.5, Write 21 = 0.7, Read 11 = 0.4, everything else (ToolSearch, all mcp__bantamkit__*, Agent) 13 combined. Read is FOUR TENTHS OF ONE PERCENT: units read files through Bash, not through the Read tool. WHAT THE BASH CALLS LOOK LIKE: 96 percent already chain with &&, ; or |; median command length 339 characters, mean 898, max 43,817; splitting on the chain operators gives 42,162 segments, i.e. 14.5 commands PER CALL (inflated by Python heredocs, whose lines - import, assert, def, return, from - appear in the verb census, but the shell verbs alone still dominate: grep 1,444, git 1,194, sed 984, head 976, python 949, tail 868, cat 471). CONSEQUENCE FOR THE 80 PERCENT TARGET, and it closes the question rather than deferring it: cutting 826 unit-logged calls to 165 needs a 5x reduction, and THE BATCHING LEVER IS ALREADY SPENT - calls are not one-command-per-idea, they average 14.5 chained commands and 339 characters. tools/mutmatrix (merged cab5d05) collapses a mutation sweep from about 3.5 calls per mutation to one per unit, worth 114 of the 661 calls that must go = 17 percent of the gap, and it is the LARGEST single mechanical batching win available because mutation work was only 34 of the recorded operations. The remaining 83 percent is not a batching problem: it is iteration count - how many times a unit has to look again - and there is no mechanical lever for it. Do not promise fleet-wide 80 percent from tool-call reduction. The measured document-turn figure (94.77 percent via the reader, median 99.545) is the one that clears the bar, and it clears it for a different reason.
