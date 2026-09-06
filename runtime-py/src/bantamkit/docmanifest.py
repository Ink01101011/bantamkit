"""One rendering of a `docread.Document` as a manifest — for every caller that has one.

Register entries (b) and (h), `docs/roadmap-toolbox.md` row 8. The entry dict
`{document, kind, index, part, row_count, rows, omissions}` that `contract.document_manifest`
takes was built by hand in `evalrun._document_tools` and again in `mcpserver.bantamkit_read`,
with no shared helper and no test that the two produced the same bytes for the same file. They
did not: the eval harness answered a zero-row part with `document_offset_past_end`, whose
sentence reads `numbered 0 to -1`, while the MCP server answered `"<part>" in <path> has no
rows`. One runtime disagreeing with itself about a file is not a two-runtime divergence and
costs no `docs/porting.md` row — it just had to stop.

**Why this is its own module and not a function on either caller.** `evalrun` is the
measurement harness and `mcpserver` is Layer 5; making either import the other to reach a
shared renderer would put the eval harness behind the MCP SDK's import, or the server behind
`yaml` and the whole eval config surface. `docread` itself is the other candidate and is the
better one on paper — but the entry dict is the *contract layer's* input shape, not the
reader's, and `docread` is deliberately ignorant of who renders it. So the adapter between the
two sits here: it imports `docread` for nothing at all (it reads attributes off whatever it is
handed) and `contract` for the sentences, which is the direction the layer rule allows.

The sentences are `contract`'s, with ONE exception this module inherited rather than chose:
`document_no_rows` builds its text here, exactly as `mcpserver` built it inline before. It is
not in `assets/contracts/default.yaml` beside every other model-facing sentence in this
repository, and the port spells it a third time in `runtime-ts/src/mcp/server.ts`. Moving it
into the contract asset is a two-runtime contract change and is registered, not done here.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from bantamkit.contract import document_error, document_manifest

__all__ = [
    "document_no_rows",
    "manifest_entries",
    "package_entries",
    "render_manifest",
]


def manifest_entries(document: str, doc: Any) -> list[dict]:
    """The PART-grain entries for one document, keyed by the label the caller uses.

    `document` is the caller's name for the file — a path on the MCP surface, a fixture name
    in the eval harness — and it is the only thing about this rendering that legitimately
    differs between the two. Everything else is a fact about the bytes.
    """
    return [
        {
            "document": document,
            "kind": doc.kind,
            "index": part.index,
            "part": part.name,
            "row_count": part.row_count,
            "rows": part.rows,
            "omissions": [o.as_dict() for o in part.omissions],
        }
        for part in doc.parts
    ]


def package_entries(document: str, doc: Any) -> list[dict]:
    """The DOCUMENT-grain entries: what the container holds that belongs to no part.

    Empty when the document has no such omissions, because `contract.document_manifest`
    renders an entry without them byte-for-byte as it did before the disclosure existed —
    which is what keeps the committed `document-read` rows where they are.
    """
    if not doc.omissions:
        return []
    return [{"document": document, "omissions": [o.as_dict() for o in doc.omissions]}]


def render_manifest(documents: Iterable[tuple[str, Any]]) -> str:
    """The manifest for one or many (label, `Document`) pairs, as one observation."""
    parts: list[dict] = []
    package: list[dict] = []
    for document, doc in documents:
        parts.extend(manifest_entries(document, doc))
        package.extend(package_entries(document, doc))
    return document_manifest(parts, package)


def document_no_rows(part: str, document: str) -> str:
    """The refusal for a part that has no rows at all — NOT an offset past the end.

    `document_offset_past_end` over a zero-row part prints `numbered 0 to -1`, a range with
    no members, and it says "offset N is past the end" about an offset of 0, which is not
    past anything. No offset can be in range here, so the reply states that fact instead.

    This exact string is pinned ON THE WIRE for both runtimes by
    `tools/conformance/suites/wire.mjs` (`read: id 12`), which asserts it as a literal on each
    side precisely so that both sides drifting back together would still fail. Changing it is
    a two-runtime change plus that case; it is why this is the sentence that survived (b)/(h)
    rather than the eval harness's.
    """
    return document_error(f'"{part}" in {document} has no rows')
