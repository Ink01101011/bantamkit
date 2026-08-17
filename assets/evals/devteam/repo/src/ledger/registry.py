"""Handler registry. Resolved once at import time by the service entry point."""

HANDLERS = {
    "settle": "ledger.settle:settle_batch",
    "post": "ledger.posting:post_entry",
    "report": "ledger.report:build_report",
}
