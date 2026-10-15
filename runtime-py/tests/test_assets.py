"""The asset loaders take a BARE name (job66/#145).

`runtime-ts/test/assets.test.mjs` holds the twin of this test; the two sentences are compared
across runtimes by `node tools/conformance/run.mjs --suite validate` (`asset-load/*`).
"""

from __future__ import annotations

import pytest

from bantamkit.assets import AssetNotFound, load_schema, load_skill, load_tool, load_tool_asset

NOT_BARE = ["../outside", "../../outside", "..\\outside", "a/b", "..", "C:outside", "x\0"]


@pytest.fixture
def pack(tmp_path, monkeypatch):
    root = tmp_path / "pack"
    for d in ("tools", "schemas", "skills"):
        (root / d).mkdir(parents=True)
    (root / "tools" / "x.json").write_text(
        '{"name": "x", "description": "d", "parameters": {}}', encoding="utf-8"
    )
    (root / "schemas" / "x.json").write_text('{"type": "object"}', encoding="utf-8")
    (root / "skills" / "x.md").write_text("x\n", encoding="utf-8")
    for d in (root, tmp_path):
        (d / "outside.json").write_text('{"leaked": true}', encoding="utf-8")
        (d / "outside.md").write_text("secret notes\n", encoding="utf-8")
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(root))
    return root


@pytest.mark.parametrize(
    ("kind", "load"), [("tool", load_tool), ("schema", load_schema), ("skill", load_skill)]
)
def test_every_loader_refuses_a_name_that_is_not_bare(pack, kind, load):
    load("x")  # a bare name still loads
    for name in NOT_BARE:
        with pytest.raises(AssetNotFound) as caught:
            load(name)
        assert str(caught.value) == f"{kind} asset name is not a bare name: {name}"


def test_a_tool_name_cannot_reach_another_kind_of_asset(pack):
    # Before #145 this read the SCHEMA as a tool asset.
    with pytest.raises(AssetNotFound) as caught:
        load_tool_asset("../schemas/x")
    assert str(caught.value) == "tool asset name is not a bare name: ../schemas/x"
