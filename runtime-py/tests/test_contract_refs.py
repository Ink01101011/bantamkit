"""The one-resource rule and the dialects on the reference side (job65, #125 and #126).

`jsonschema` resolves a `$ref` against a base URI and a registry; the Node port resolves it
inside the one resource a caller schema is. So that the two never disagree, `contract.py`
narrows the reference to the same rule BEFORE `jsonschema.validate` runs, and answers the
narrowing as a sentence rather than letting `_WrappedReferencingError` escape. These tests pin
the sentences; `tools/conformance/suites/validate.mjs` (`drafts/`) compares them with the port.
"""

from __future__ import annotations

import pytest

from bantamkit.contract import _unsupported_schema, schema_error

D3 = "http://json-schema.org/draft-03/schema#"
D4 = "http://json-schema.org/draft-04/schema#"
D7 = "http://json-schema.org/draft-07/schema#"
D2019 = "https://json-schema.org/draft/2019-09/schema"
NON_LOCAL = (
    'the reference "https://example.com/x.json" cannot be resolved: only references into '
    'this schema ("#", "#/..." and "#name") are supported'
)
DRAFT3 = (
    f"the schema's $schema \"{D3}\" names draft 3, which this validator does not support "
    "(draft-04, draft-06, draft-07, 2019-09 and 2020-12 are)"
)


def at(where: str, detail: str) -> str:
    return f"JSON does not match schema at '{where}': {detail}"


def test_local_ref_and_unevaluated_answer_as_before():
    # #125's own rows — the reference already answered these; the pre-scan must not touch them.
    defs = {"$ref": "#/$defs/x", "$defs": {"x": {"type": "string"}}}
    assert schema_error('{"a": 1}', defs) == at("root", "{'a': 1} is not of type 'string'")
    assert (
        schema_error('{"a": 1}', {"$ref": "#/$defs/x", "$defs": {"x": {"type": "object"}}}) is None
    )
    assert schema_error('{"a": 1}', {"type": "object", "unevaluatedProperties": False}) == at(
        "root", "Unevaluated properties are not allowed ('a' was unexpected)"
    )
    assert schema_error("[1]", {"unevaluatedItems": False}) == at(
        "root", "Unevaluated items are not allowed (1 was unexpected)"
    )
    assert _unsupported_schema(defs) is None


@pytest.mark.parametrize(
    ("schema", "sentence"),
    [
        ({"properties": {"a": {"$ref": "https://example.com/x.json"}}}, NON_LOCAL),
        # Eager, not on first use: the branch is never reached and it is refused anyway.
        ({"properties": {"zz": {"$ref": "https://example.com/x.json"}}}, NON_LOCAL),
        (
            {"properties": {"a": {"$ref": "other.json#/x"}}},
            'the reference "other.json#/x" cannot be resolved: only references into this '
            'schema ("#", "#/..." and "#name") are supported',
        ),
        (
            {
                "$defs": {"x": {"$id": "https://example.com/x", "type": "string"}},
                "properties": {"a": {"$ref": "#/$defs/x"}},
            },
            'the schema declares "$id" at $defs/x; references are only resolved in a schema '
            "with a single resource",
        ),
        (
            {
                "$schema": D4,
                "definitions": {"x": {"id": "https://example.com/x", "type": "string"}},
                "properties": {"a": {"$ref": "#/definitions/x"}},
            },
            'the schema declares "id" at definitions/x; references are only resolved in a '
            "schema with a single resource",
        ),
        ({"$schema": D3, "type": "string"}, DRAFT3),
        ({"properties": {"a": {"$schema": D3, "type": "string"}}}, DRAFT3),
    ],
)
def test_the_pre_scan_answers_one_sentence(schema, sentence):
    assert _unsupported_schema(schema) == sentence
    assert schema_error('{"a": 1}', schema) == sentence


@pytest.mark.parametrize(
    ("schema", "sentence"),
    [
        (
            {"properties": {"a": {"$ref": "#/$defs/nope"}}},
            'the reference "#/$defs/nope" points at nothing in this schema',
        ),
        (
            {"properties": {"a": {"$ref": "#nope"}}},
            'the reference "#nope" names no anchor in this schema',
        ),
        # `$anchor` is not a draft-7 keyword, so the anchor is not there to find.
        (
            {
                "$schema": D7,
                "definitions": {"x": {"$anchor": "foo", "type": "string"}},
                "properties": {"a": {"$ref": "#foo"}},
            },
            'the reference "#foo" names no anchor in this schema',
        ),
    ],
)
def test_a_missing_target_is_found_lazily_and_answered(schema, sentence):
    # Not the pre-scan's business — `referencing` raises when validation reaches the keyword…
    assert _unsupported_schema(schema) is None
    assert schema_error('{"a": 1}', schema) == sentence
    # …so the same pointer in a branch the instance never reaches is simply valid.
    unreached = {"properties": {"zz": next(iter(schema["properties"].values()))}}
    assert schema_error('{"a": 1}', unreached) is None


def test_the_rule_is_structural():
    # An embedded `$id` with no reference anywhere is a plain subschema.
    assert schema_error(
        '{"a": 1}',
        {"$defs": {"x": {"$id": "https://example.com/x"}}, "properties": {"a": {"type": "string"}}},
    ) == at("a", "1 is not of type 'string'")
    # A ROOT `$id` is the one resource's own name, not a second resource.
    root = {
        "$id": "https://example.com/root",
        "$defs": {"x": {"type": "string"}},
        "properties": {"a": {"$ref": "#/$defs/x"}},
    }
    assert schema_error('{"a": 1}', root) == at("a", "1 is not of type 'string'")
    assert schema_error('{"a": "s"}', root) is None
    # A PROPERTY named `$ref` is not a reference.
    named = {"properties": {"$ref": {"type": "string"}}}
    assert schema_error('{"$ref": 1}', named) == at("$ref", "1 is not of type 'string'")
    assert schema_error('{"$ref": "https://x"}', named) is None
    assert _unsupported_schema(named) is None


def test_126_the_dialect_is_the_references_own_dispatch():
    dep = {"dependencies": {"a": ["b"]}}
    assert schema_error('{"a": 1}', {"$schema": D7, **dep}) == at(
        "root", "'b' is a dependency of 'a'"
    )
    assert schema_error('{"a": 1, "b": 2}', {"$schema": D7, **dep}) is None
    assert schema_error('{"a": 1}', {"$schema": D2019, **dep}) is None
    assert schema_error('{"a": 1}', dep) is None
    d4 = {"$schema": D4, "properties": {"a": {"maximum": 1, "exclusiveMaximum": True}}}
    assert schema_error('{"a": 2}', d4) == at("a", "2 is greater than or equal to the maximum of 1")
    assert schema_error('{"a": 0}', d4) is None
    tup = {
        "$schema": D7,
        "properties": {"a": {"items": [{"type": "integer"}, {"type": "integer"}]}},
    }
    assert schema_error('{"a": [1, "x"]}', tup) == at("a/1", "'x' is not of type 'integer'")
    assert schema_error('{"a": [1, 2, "x"]}', tup) is None
