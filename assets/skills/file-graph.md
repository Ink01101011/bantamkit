# File-access graph

A ledger of every file you read is kept for you automatically. Before
reading any file, call the `file_graph` tool to see what you already read
and whether it changed. Never re-read a file the ledger lists as
unchanged — use what you already saw. Re-reads of unchanged files return a
short `[file-graph]` marker instead of the content.
