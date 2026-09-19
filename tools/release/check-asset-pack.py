#!/usr/bin/env python3
"""Compare the asset pack INSIDE a built artifact, byte for byte, against the checkout.

WHY THIS EXISTS, MEASURED (job56, unit J56-4). The packaging gates on both sides compare
asset *names*: `runtime-py/tests/test_packaging.py` asserts `shipped >= expected` over
relative paths, and `runtime-ts/test/packaging.test.mjs` pins a filename list. A pack with
the right filenames and the wrong bytes satisfies both. J56-4 built exactly that wheel --
one manifest carrying a description and an input schema that no commit in the tree carries
-- and measured the result: the build was green, `python -m build` said nothing, the
packaging gate passed, and the installed server advertised the stale description and the
stale schema over real stdio with no error at all. Names are not enough; hash them.

The SHORT version of the same hazard is loud (the server refuses to start, naming the
missing file) and both gates already catch it. It is the CONTENT-stale version that is
silent, and silence is what this script is for.

This is a release-time check rather than a suite check on purpose: it asks a BUILT
ARTIFACT what it contains, which no local test can do -- every local path reads the
checkout, and the checkout is by definition in agreement with itself.

Usage:

    check-asset-pack.py ARCHIVE PREFIX REPO_ASSETS [--also MEMBER=REPO_FILE]...

  ARCHIVE      .tgz / .tar.gz / .whl / .zip -- an artifact as it would be uploaded
  PREFIX       where the pack lives inside it, e.g. `package/assets`,
               `bantamkit-0.35.1.dist-info/..`-free `bantamkit/assets`, or
               `bantamkit-0.35.1/_assets`
  REPO_ASSETS  the checkout's pack, i.e. `<repo>/assets`
  --also       one extra member to compare against one repo file, e.g.
               `--also package/LICENSE=LICENSE`; repeatable

Exit status: 0 when every file matches byte for byte, 1 on any missing, extra or
differing member, 2 on a usage or read error. Every difference is named; a count alone
would not tell a releaser what to do next.
"""

from __future__ import annotations

import hashlib
import sys
import tarfile
import zipfile
from pathlib import Path


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_members(archive: Path) -> dict[str, bytes]:
    """Every regular file in the archive, keyed by its member path as stored."""
    name = archive.name.lower()
    members: dict[str, bytes] = {}
    if name.endswith((".tgz", ".tar.gz")):
        with tarfile.open(archive, "r:gz") as tar:
            for info in tar.getmembers():
                if not info.isfile():
                    continue
                handle = tar.extractfile(info)
                if handle is None:
                    continue
                members[info.name] = handle.read()
    elif name.endswith((".whl", ".zip")):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                members[info.filename] = zf.read(info)
    else:
        print(f"check-asset-pack: unsupported archive type: {archive}", file=sys.stderr)
        raise SystemExit(2)
    return members


def _repo_files(root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = path.read_bytes()
    return out


def main(argv: list[str]) -> int:
    positional: list[str] = []
    also: list[tuple[str, str]] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--also":
            i += 1
            if i >= len(argv) or "=" not in argv[i]:
                print("check-asset-pack: --also needs MEMBER=REPO_FILE", file=sys.stderr)
                return 2
            member, _, repo_file = argv[i].partition("=")
            also.append((member, repo_file))
        elif arg in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            positional.append(arg)
        i += 1

    if len(positional) != 3:
        print(
            "usage: check-asset-pack.py ARCHIVE PREFIX REPO_ASSETS [--also MEMBER=REPO_FILE]...",
            file=sys.stderr,
        )
        return 2

    archive = Path(positional[0])
    prefix = positional[1].strip("/")
    repo_assets = Path(positional[2])

    if not archive.is_file():
        print(f"check-asset-pack: no such archive: {archive}", file=sys.stderr)
        return 2
    if not repo_assets.is_dir():
        print(f"check-asset-pack: no such asset pack: {repo_assets}", file=sys.stderr)
        return 2

    members = _read_members(archive)
    shipped = {
        name[len(prefix) + 1 :]: data
        for name, data in members.items()
        if name.startswith(prefix + "/")
    }
    expected = _repo_files(repo_assets)

    # A prefix that matches nothing is a hard stop, not a pass: an empty comparison would
    # report "0 differences" over an artifact carrying no pack at all, which is the worse
    # of the two defects this script exists to find.
    if not shipped:
        print(
            f"check-asset-pack: FAIL -- nothing in {archive.name} lives under `{prefix}/`.\n"
            f"  The artifact ships no asset pack there, or the prefix is wrong.",
            file=sys.stderr,
        )
        return 1

    missing = sorted(set(expected) - set(shipped))
    extra = sorted(set(shipped) - set(expected))
    differing = sorted(
        rel
        for rel in set(expected) & set(shipped)
        if _digest(expected[rel]) != _digest(shipped[rel])
    )

    for member, repo_file in also:
        repo_path = repo_assets.parent / repo_file if not Path(repo_file).is_absolute() else Path(repo_file)
        if member not in members:
            missing.append(f"[also] {member}")
        elif not repo_path.is_file():
            print(f"check-asset-pack: --also source not a file: {repo_path}", file=sys.stderr)
            return 2
        elif _digest(members[member]) != _digest(repo_path.read_bytes()):
            differing.append(f"[also] {member} vs {repo_path}")

    label = f"{archive.name} :: {prefix}/"
    if not missing and not extra and not differing:
        print(f"check-asset-pack: OK -- {len(shipped)} files under {label} are byte-identical to {repo_assets}")
        return 0

    print(f"check-asset-pack: FAIL -- {label} disagrees with {repo_assets}", file=sys.stderr)
    for rel in missing:
        print(f"  missing from the artifact : {rel}", file=sys.stderr)
    for rel in extra:
        print(f"  in the artifact only      : {rel}", file=sys.stderr)
    for rel in differing:
        print(f"  SAME NAME, DIFFERENT BYTES: {rel}", file=sys.stderr)
    print(
        "  A pack whose filenames are right and whose bytes are not is the silent failure\n"
        "  this check exists for: the server starts, serves the right tool names, and\n"
        "  advertises a description or a schema no commit carries.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
