"""Schema-enforced extraction without an agent loop.

structured() extracts JSON from the reply (tolerating fences and prose),
validates it against the schema, and re-prompts with the exact validation
error on failure — up to max_retries attempts.
"""

import json
import os

from bantamkit import OpenAICompatible, structured

client = OpenAICompatible(
    base_url=os.environ.get("BANTAMKIT_BASE_URL", "http://localhost:11434/v1"),
    model=os.environ.get("BANTAMKIT_MODEL", "qwen3:4b-instruct"),
)

invoice = structured(
    client,
    'Extract the invoice as JSON with keys "vendor" (string), "total" (integer), '
    'and "currency" (string). Text: "Invoice #841 from Initech: 3 chairs, total 462 USD."',
    schema={
        "type": "object",
        "required": ["vendor", "total", "currency"],
        "properties": {
            "vendor": {"type": "string"},
            "total": {"type": "integer"},
            "currency": {"type": "string"},
        },
    },
)
print(json.dumps(invoice, indent=2))
