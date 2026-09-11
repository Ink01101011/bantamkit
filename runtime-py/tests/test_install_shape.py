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


# The functions AS-7(a) added, and the module-level names they are allowed to touch. Both
# lists are data so that `_names_reached_by` — the scanner below — can be run against the real
# module AND against four hand-written samples in `test_the_network_gate_sees_every_shape_a_
# person_would_write`. A scanner nobody has shown to be RED on anything is not a gate.
_AS7_FUNCTIONS = frozenset({
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
})
_AS7_ALLOWED = frozenset({
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
})


def _module_level_names(tree) -> set[str]:
    """The names a module binds at top level, from its AST alone.

    Used only when no live module is available — the real node below passes
    `vars(mcpserver)`, which is strictly better because it also sees names a star-import or
    a conditional block brings in. This exists so the four-row proof can feed the scanner a
    sample that is a string rather than an importable module.
    """
    import ast

    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _names_reached_by(source: str, functions, module_globals=None) -> set[str]:
    """Every name the named top-level functions can reach OUT of their own bodies.

    THREE KINDS, and the second and third were added on 2026-09-11 because the first alone
    was measurably blind (J46-13 measured it; this unit closes it):

      1. A MODULE GLOBAL the body mentions — `urllib.request.urlopen(...)` where the module
         imported `urllib.request` at the top. Collected by walking to the root of every
         attribute chain and keeping the `Name` if the module binds it.

      2. A FUNCTION-LOCAL `import` — `def f(): import urllib.request; urllib.request.urlopen()`.
         This binds NOTHING at module level, so kind 1 sees a local variable it does not
         recognise and says nothing. **This is the shape a person actually writes when adding
         one network call to an otherwise offline module**, which is exactly what AS-7(b) is,
         so a gate blind to it goes green on the very change it exists to notice. The MODULE
         being imported is recorded (`urllib.request`, not the bound name `urllib`), because
         the allowlist is a list of things this code may touch and `urllib.request` is what
         was touched.

      3. A DYNAMIC import — `__import__("urllib.request")` or `importlib.import_module(...)`.
         Neither binds a module global and neither is an `ast.Import`. The string argument is
         recorded when it is a literal; when it is not, the unreadable call itself is recorded
         under a name that can never be allowlisted, because a gate cannot reason about it.

    COMMENTS AND DOCSTRINGS ARE DELIBERATELY INVISIBLE. This node's own docstring names
    `urllib.request`, and the first version of it failed on itself. An AST carries no
    comments, and a `Str` is not a `Name` — so the prose stays green and the call goes red,
    which is the whole reason this is a parse and not a `grep`.
    """
    import ast

    tree = ast.parse(source)
    if module_globals is None:
        module_globals = _module_level_names(tree)
    wanted = set(functions)
    seen: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in wanted:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Import):
                for alias in inner.names:
                    seen.add(alias.name)
                continue
            if isinstance(inner, ast.ImportFrom):
                seen.add(inner.module or ".")
                continue
            if isinstance(inner, ast.Call):
                target = inner.func
                is_dunder = isinstance(target, ast.Name) and target.id == "__import__"
                is_importlib = (
                    isinstance(target, ast.Attribute)
                    and target.attr in {"import_module", "__import__"}
                )
                if is_dunder or is_importlib:
                    first = inner.args[0] if inner.args else None
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        seen.add(first.value)
                    else:
                        seen.add("a dynamic import whose argument is not a literal")
                    continue
            root = inner
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in module_globals:
                seen.add(root.id)
    return seen


def test_no_path_this_unit_added_can_reach_the_network(monkeypatch):
    """AS-7(a)'s whole virtue is that it needs no network, so this is structural, not prose.

    Every name the new functions can reach out of their own bodies is collected from the
    module's own AST and checked against a list. A comment mentioning the request module does
    not trip it and a real call does — which is the wrong way round for a substring scan, and
    was: the first version of this node failed on its own docstring. AS-7(b), the registry
    comparison, is a separate unit for exactly this reason.

    The scanner is `_names_reached_by`, and the four shapes it must and must not see are
    proved one test down. Read that one before trusting this one.
    """
    import ast

    from bantamkit import mcpserver

    source = Path(mcpserver.__file__).read_text(encoding="utf-8")
    seen = _names_reached_by(source, _AS7_FUNCTIONS, set(vars(mcpserver)))
    tree = ast.parse(source)

    assert _AS7_FUNCTIONS <= {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}, (
        "a function this node claims to cover was renamed or removed"
    )
    assert seen <= _AS7_ALLOWED, (
        f"a new name reached the offline diagnosis path: {sorted(seen - _AS7_ALLOWED)}"
    )


def test_the_network_gate_sees_every_shape_a_person_would_write():
    """The four rows J46-13 measured, run — two that must be RED and two that must be GREEN.

    A gate is only worth its docstring if someone has watched it fail. Before 2026-09-11 rows
    3 and 4 were GREEN, measured, and rows 3 and 4 are precisely how the next change to this
    module will be written: J46-29 and J46-30 add a network call to this codebase on purpose,
    and a gate that goes green on their shape would be cited as evidence that it did not.

    Rows 1 and 2 are here for the opposite failure. A gate that reddens on a COMMENT has been
    over-tightened, and the next person it annoys will delete it — so the comment row is as
    load-bearing as the call rows.
    """
    guarded = {"_derive_install"}

    module_level = (
        "import urllib.request\n"
        "def _derive_install():\n"
        "    return urllib.request.urlopen('https://pypi.org/simple/bantamkit/').read()\n"
    )
    a_comment = (
        "def _derive_install():\n"
        "    # urllib.request would reach the network, so nothing here calls it\n"
        "    return 'offline'\n"
    )
    function_local = (
        "def _derive_install():\n"
        "    import urllib.request\n"
        "    return urllib.request.urlopen('https://pypi.org/simple/bantamkit/').read()\n"
    )
    dunder = (
        "def _derive_install():\n"
        "    fetch = __import__('urllib.request', fromlist=['urlopen'])\n"
        "    return fetch.urlopen('https://pypi.org/simple/bantamkit/').read()\n"
    )

    rows = [
        ("module-level import + urlopen()", module_level, True),
        ("a comment naming the request module", a_comment, False),
        ("function-local import + the same urlopen()", function_local, True),
        ("__import__(...) + the same urlopen()", dunder, True),
    ]
    verdicts = {}
    for label, sample, must_be_red in rows:
        reached = _names_reached_by(sample, guarded)
        escaped = reached - _AS7_ALLOWED
        verdicts[label] = (sorted(escaped), must_be_red)
        if must_be_red:
            assert escaped, (
                f"{label}: the gate saw {sorted(reached)} and let all of it through. This shape "
                "reaches the network and the gate must go red on it."
            )
        else:
            assert not escaped, (
                f"{label}: the gate reddened on {sorted(escaped)}. Prose is not a call, and a "
                "gate that refuses a comment gets deleted by the next person who writes one."
            )

    # The two red rows must go red for the RIGHT name, not incidentally. Without this a
    # scanner that reported every identifier would satisfy the assertions above.
    must_name_the_module = (
        "function-local import + the same urlopen()",
        "__import__(...) + the same urlopen()",
    )
    for label in must_name_the_module:
        escaped, _ = verdicts[label]
        assert "urllib.request" in escaped, (
            f"{label}: the gate went red but named {escaped}; it must name the module that was "
            "imported, because that is the string a reader has to judge against the allowlist."
        )


def test_the_network_gate_reads_a_dynamic_import_it_cannot_evaluate_as_a_refusal():
    """`__import__(name)` where `name` is a variable: unreadable, therefore never allowed.

    The literal form is caught by reading the literal. The computed form has no literal to
    read, and the only two honest answers are "refuse" and "give up". A gate that gave up here
    would hand anyone who wanted it a one-line bypass of the previous test.
    """
    sample = (
        "def _derive_install():\n"
        "    name = 'urllib' + '.request'\n"
        "    return __import__(name).urlopen('https://pypi.org/').read()\n"
    )
    reached = _names_reached_by(sample, {"_derive_install"})
    assert reached - _AS7_ALLOWED, "a dynamic import the gate cannot read must not pass it"
