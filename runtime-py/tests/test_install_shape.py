"""Install-shape self-diagnosis, offline: which shape is running, and whether it can be updated.

THE DEFECT THIS FILE IS BUILT FOR IS MEASURED, NOT IMAGINED (`docs/roadmap-agent-stack.md`
AS-7). A Claude Desktop entry sat on 0.25.0 from 2026-08-24 through five releases and
nothing in the config, the logs or any tool reply said so — and its `package.json` declared
`"bantamkit-mcp": "file:/private/tmp/.../scratchpad/bantamkit-mcp-0.25.0.tgz"`, a local
tarball in a temp directory that no longer existed. `npm update` there is a no-op BY
CONSTRUCTION. That is a purely LOCAL fact: the origin path is written down by the installer
and either exists or does not.

WHAT IS ASSERTED HERE AND WHAT DELIBERATELY IS NOT. Every shape below is built as a REAL
`.dist-info` directory on disk — real `METADATA`, real `RECORD`, real `direct_url.json` —
and discovered through `importlib.metadata.distributions(path=[...])`, the same discovery
the server runs. Nothing is mocked, because a mock here would assert this module's own
implementation back at itself: the whole question is what pip actually writes down, and
only a directory can answer it.

NO NODE HERE ASSERTS A FACT ABOUT THIS MACHINE (`RB-P14` gate 2, the rule
`test_build_identity.py` states at length). The machine's own install is read once, in
`test_the_real_install_answers_within_the_vocabulary`, and only for properties that hold on
EVERY shape — a laptop's editable checkout, a CI wheel and a user's `pip install bantamkit`
all satisfy it. The shape-by-shape nodes are built in `tmp_path`.

NO NETWORK, AND IT IS ASSERTED RATHER THAN CLAIMED:
`test_no_path_this_unit_added_can_reach_the_network` collects every global name the new
functions touch from the module's own AST and checks it against a list. AS-7(b) — comparing
the running version against a registry — is a different unit and is gated behind this one
shipping.
"""

from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

import pytest

from bantamkit.mcpserver import (
    INSTALL_SHAPES,
    Install,
    _derive_install,
    _install_once,
    _install_source_condition,
    _Undetermined,
    build_identity,
    current_install,
)

# --------------------------------------------------------------------------- the fixtures


def _write_dist(
    site: Path,
    *,
    version: str = "0.25.0",
    direct_url: dict | None = None,
    name: str = "bantamkit",
) -> Path:
    """One real `.dist-info` directory, the way an installer leaves it.

    `RECORD` and `METADATA` are written because `importlib.metadata` reads them, and a
    fixture that skipped them would be discovered as a distribution with no name — which is
    a case the resolver handles, but not the case any of these nodes is about.
    """
    dist_info = site / f"{name}-{version}.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8"
    )
    (dist_info / "RECORD").write_text(f"{name}/__init__.py,,\n", encoding="utf-8")
    (dist_info / "INSTALLER").write_text("pip\n", encoding="utf-8")
    if direct_url is not None:
        (dist_info / "direct_url.json").write_text(json.dumps(direct_url), encoding="utf-8")
    return dist_info


def _write_package(root: Path) -> Path:
    """The importable tree an install puts on disk. Returns the `__init__.py` that runs."""
    package = root / "bantamkit"
    package.mkdir(parents=True)
    init = package / "__init__.py"
    init.write_text('__version__ = "0.25.0"\n', encoding="utf-8")
    return init


def _derive(package_file: Path, site: Path) -> Install:
    """Run the resolver over REAL discovery, exactly as the server runs it."""
    return _derive_install(package_file, metadata.distributions(path=[str(site)]))


# ------------------------------------------------------------------- shape by shape


def test_a_wheel_from_an_index_is_a_registry_install(tmp_path):
    """No `direct_url.json` is the PEP 610 signal for "came from an index".

    pip writes that file only for a direct URL or a local path. Its ABSENCE beside a
    dist-info that owns the running files is therefore positive evidence, not a gap — and
    it is the one shape with a registry to be reinstalled from, which is why `--update`
    (J46-29) has to be able to tell it from the other four.
    """
    site = tmp_path / "site-packages"
    site.mkdir()
    init = _write_package(site)
    _write_dist(site)

    install = _derive(init, site)

    assert install.shape == "registry"
    assert install.source is None
    assert "no origin path" in install.source_reason


def test_a_local_archive_records_the_path_it_was_installed_from(tmp_path):
    """The measured shape: `pip install ./bantamkit-0.25.0.tar.gz`, npm's `file:` tarball.

    The files are COPIED into site-packages, so the package imports perfectly while the
    archive it came from may be long gone. That is what makes this a refusal-shaped local
    check and not a guess.
    """
    site = tmp_path / "site-packages"
    site.mkdir()
    init = _write_package(site)
    archive = tmp_path / "scratchpad" / "bantamkit-0.25.0.tar.gz"
    archive.parent.mkdir()
    archive.write_bytes(b"not really a tarball, but really a file")
    _write_dist(site, direct_url={"url": archive.as_uri(), "archive_info": {}})

    install = _derive(init, site)

    assert install.shape == "local-file"
    assert install.source == str(archive)


def test_an_editable_install_is_linked_to_the_tree_it_still_reads(tmp_path):
    """`pip install -e`, and npm's `file:` pointing at a DIRECTORY. The source stays live.

    The distinguishing fact is not the flag in `direct_url.json` alone — it is that the
    running file is INSIDE the recorded directory while the dist-info is somewhere else
    entirely. Both are asserted, because either one alone would also match a shape it is
    not.
    """
    site = tmp_path / "site-packages"
    site.mkdir()
    checkout = tmp_path / "runtime-py"
    init = _write_package(checkout / "src")
    _write_dist(site, direct_url={"url": checkout.as_uri(), "dir_info": {"editable": True}})

    install = _derive(init, site)

    assert install.shape == "linked"
    assert install.source == str(checkout)
    assert Path(install.source) in init.parents


def test_a_tree_no_installer_recorded_is_a_checkout(tmp_path):
    """`PYTHONPATH=runtime-py/src`: importable, and no distribution claims it."""
    init = _write_package(tmp_path / "src")
    site = tmp_path / "site-packages"
    site.mkdir()

    install = _derive(init, site)

    assert install.shape == "checkout"
    assert install.source is None
    assert "no installer recorded" in install.source_reason


def test_a_dist_info_that_describes_a_DIFFERENT_tree_does_not_claim_this_one(tmp_path):
    """Two bantamkits under one name — the situation `RB-P84` filed, from the other side.

    A `bantamkit-0.30.0.dist-info` sitting in some site-packages is not evidence about the
    bytes that were imported: a checkout earlier on `sys.path` shadows it. The resolver
    matches a distribution to the RUNNING FILE and otherwise walks past it, so the answer
    here is `checkout` and not the installed dist's shape. Without this the detector would
    hand `--update` a registry route for code no registry can replace.
    """
    site = tmp_path / "site-packages"
    site.mkdir()
    _write_package(site)  # the installed copy, which is NOT what is running
    _write_dist(site, version="0.30.0")
    running = _write_package(tmp_path / "checkout" / "src")

    install = _derive(running, site)

    assert install.shape == "checkout"


def test_an_origin_that_is_neither_an_index_nor_a_path_is_underivable(tmp_path):
    """`pip install git+https://…` — a real shape, and NOT one of the five words.

    Reporting it as `registry` would send an update at a registry that never had it, and
    reporting it as `checkout` would claim a git tree that is not on this disk. `RB-P51`'s
    rule is the answer: a fact that cannot be derived is named as underivable, with the
    reason, and never rounded to the nearest value.
    """
    site = tmp_path / "site-packages"
    site.mkdir()
    init = _write_package(site)
    _write_dist(
        site,
        direct_url={
            "url": "https://github.com/Ink01101011/bantamkit",
            "vcs_info": {"vcs": "git", "commit_id": "0" * 40},
        },
    )

    with pytest.raises(_Undetermined) as raised:
        _derive(init, site)

    assert "https://github.com/Ink01101011/bantamkit" in str(raised.value)


def test_a_path_with_a_space_survives_the_file_url_round_trip(tmp_path):
    """`Path.as_uri()` percent-encodes; a detector that did not decode would report a lie.

    Not a hypothetical on the machine this defect was found on: the dangling path AS-7
    quotes lives under `/private/tmp/.../scratchpad`, and a person's own directories are
    where spaces live. The assertion is round-trip against `pathlib`'s own encoder rather
    than against a literal, so it holds on Windows drive letters too.
    """
    site = tmp_path / "site packages"
    site.mkdir()
    init = _write_package(site)
    archive = tmp_path / "my downloads" / "bantamkit 0.25.0.tar.gz"
    archive.parent.mkdir()
    archive.write_bytes(b"x")
    assert "%20" in archive.as_uri()
    _write_dist(site, direct_url={"url": archive.as_uri(), "archive_info": {}})

    assert _derive(init, site).source == str(archive)


def test_every_shape_this_runtime_can_answer_is_in_the_shared_vocabulary(tmp_path):
    """The closed set is the contract `runtime-ts` copies. A sixth word is a divergence.

    `ephemeral` is in the vocabulary and is NOT in this list, and that is the deliberate
    difference `docs/porting.md` carries: `npx` is a cache directory a Node server can
    recognise, while a `pipx run` / `uvx` environment is indistinguishable from a venv
    without pattern-matching cache directory names — which would be a guess, so this
    runtime does not make it.
    """
    site = tmp_path / "site-packages"
    site.mkdir()
    init = _write_package(site)
    _write_dist(site)
    registry = _derive(init, site).shape

    archive = tmp_path / "a.tar.gz"
    archive.write_bytes(b"x")
    site2 = tmp_path / "s2"
    site2.mkdir()
    init2 = _write_package(site2)
    _write_dist(site2, direct_url={"url": archive.as_uri(), "archive_info": {}})
    local = _derive(init2, site2).shape

    site3 = tmp_path / "s3"
    site3.mkdir()
    tree = tmp_path / "tree"
    init3 = _write_package(tree / "src")
    _write_dist(site3, direct_url={"url": tree.as_uri(), "dir_info": {"editable": True}})
    linked = _derive(init3, site3).shape

    checkout = _derive(_write_package(tmp_path / "bare"), site3).shape

    answered = {registry, local, linked, checkout}
    assert answered == {"registry", "local-file", "linked", "checkout"}
    assert answered < set(INSTALL_SHAPES)
    assert "ephemeral" in INSTALL_SHAPES


# --------------------------------------------------------- the condition, on real state


def test_the_condition_fires_on_a_source_that_is_gone_and_clears_when_it_returns(tmp_path):
    """Constructed from directory state, then watched — `docs/status.md`'s own rule.

    Both directions are asserted in ONE node on purpose: a condition that only ever fires
    is a condition nobody can trust, and the pair is what proves it is reading the disk
    rather than the shape word.
    """
    archive = tmp_path / "scratchpad" / "bantamkit-mcp-0.25.0.tgz"
    archive.parent.mkdir()
    archive.write_bytes(b"x")
    install = Install(shape="local-file", source=str(archive))

    assert _install_source_condition(install) is None

    archive.unlink()

    condition = _install_source_condition(install)
    assert condition is not None
    assert condition.key == "install-source-missing"
    assert str(archive) in condition.sentence

    archive.write_bytes(b"x")
    assert _install_source_condition(install) is None


def test_the_condition_names_a_remedy_that_does_something(tmp_path):
    """J46-4 spent a unit deleting a remedy that exited 0 having changed nothing.

    A dangling origin cannot be repaired in place BY CONSTRUCTION — that is the whole
    finding — so the sentence must not send anyone at an update command run where the
    install lives. Reinstalling by NAME from a registry is the one action that replaces it.
    """
    gone = tmp_path / "gone.tar.gz"
    condition = _install_source_condition(Install(shape="local-file", source=str(gone)))

    assert condition is not None
    assert "reinstall" in condition.sentence
    assert "update" not in condition.sentence.split("—")[1]


def test_a_shape_with_no_origin_path_has_nothing_to_be_missing():
    """`registry` and `checkout` record no path, so the check does not invent one."""
    for shape in ("registry", "checkout"):
        assert _install_source_condition(Install(shape=shape, source=None)) is None
    assert _install_source_condition(None) is None


def test_a_live_linked_source_is_not_a_problem(tmp_path):
    """An editable install pointed at a tree that is still there is healthy, not degraded."""
    tree = tmp_path / "runtime-py"
    tree.mkdir()
    assert _install_source_condition(Install(shape="linked", source=str(tree))) is None


# ------------------------------------------------------- the wire, and this machine


def test_build_identity_reports_the_three_fields_consistently_with_each_other():
    """Machine-independent: whatever this install is, the three fields must agree.

    A path that is reported must be checkable, and a path that is not reported must leave
    `install_source_exists` underivable rather than `false` — which would read as "your
    install is broken" on a perfectly healthy registry install.
    """
    identity = build_identity()
    shape = identity["install_shape"]
    source = identity["install_source"]
    exists = identity["install_source_exists"]

    if isinstance(shape, dict):
        assert isinstance(source, dict) and isinstance(exists, dict)
        assert "install_shape" in identity["unavailable"]
        return

    assert shape in INSTALL_SHAPES
    if isinstance(source, dict):
        assert isinstance(exists, dict), "no path was reported, so nothing can be checked"
        assert {"install_source", "install_source_exists"} <= set(identity["unavailable"])
    else:
        assert Path(source).is_absolute()
        assert exists is Path(source).exists()


def test_the_real_install_answers_within_the_vocabulary():
    """The one node that reads this machine, and it asserts no shape in particular."""
    try:
        install = current_install()
    except _Undetermined as exc:
        assert str(exc)
        return
    assert install.shape in INSTALL_SHAPES
    if install.source is None:
        assert install.source_reason
    else:
        assert Path(install.source).is_absolute()


def test_sys_path_is_walked_once_per_process_and_not_once_per_tool_call(monkeypatch):
    """`docs/status.md` promises what the degraded check costs. Discovery is not on that list.

    COUNTED THROUGH THE REAL FUNCTION, not replaced by one: the wrapper below increments and
    then calls `importlib.metadata.distributions` itself, so the answer under test is the
    answer the server would have got. Object identity would have passed for reasons other
    than the property — this fails if the memo is removed, which is the only thing that
    matters here.
    """
    calls: list[int] = []
    real = metadata.distributions

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(metadata, "distributions", counting)
    _install_once.cache_clear()
    try:
        first = current_install()
    except _Undetermined:
        pytest.skip("this install's shape is underivable here; the memo is not reachable")
    second = current_install()
    build_identity()

    assert calls == [1]
    assert second is first


def test_no_path_this_unit_added_can_reach_the_network(monkeypatch):
    """AS-7(a)'s whole virtue is that it needs no network, so this is structural, not prose.

    Every global name the new functions touch is collected from the module's own AST and
    checked against a list. A comment mentioning `urllib.request` does not trip it and a
    real `urlopen(...)` does — which is the wrong way round for a substring scan, and was:
    the first version of this node failed on its own docstring. AS-7(b), the registry
    comparison, is a separate unit for exactly this reason.
    """
    import ast

    from bantamkit import mcpserver

    added = {
        "_normalized_project_name",
        "_file_url_path",
        "_direct_url_record",
        "_dist_owns",
        "_derive_install",
        "_is_within",
        "_running_package_file",
        "_install_once",
        "current_install",
        "_install_source_condition",
        "_current_install_or_none",
    }
    allowed = {
        "Install",
        "Iterable",
        "INSTALL_SHAPES",
        "Condition",
        "Path",
        "_Undetermined",
        "_derive_install",
        "_direct_url_record",
        "_dist_owns",
        "_file_url_path",
        "_install_once",
        "_is_within",
        "_normalized_project_name",
        "_running_package_file",
        "bantamkit",
        "current_install",
        "json",
        "lru_cache",
        "metadata",
        "unquote",
    }
    tree = ast.parse(Path(mcpserver.__file__).read_text(encoding="utf-8"))
    globals_of_module = set(vars(mcpserver))
    seen: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in added:
            continue
        for inner in ast.walk(node):
            root = inner
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in globals_of_module:
                seen.add(root.id)

    assert added <= {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}, (
        "a function this node claims to cover was renamed or removed"
    )
    assert seen <= allowed, f"a new global reached the offline diagnosis path: {seen - allowed}"
