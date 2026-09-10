"""The reference side of the install-shape comparison: one answer per constructed fixture.

Every fixture is a REAL `.dist-info` directory built by the suite and discovered through
`importlib.metadata.distributions(path=[...])` — the same discovery `_install_once` runs on
the machine. Nothing is mocked, because the whole question is what pip writes down.

WHY THIS SCRIPT EXISTS RATHER THAN A `wire.mjs` SESSION. `build_identity` on a live server
answers about the install THAT SERVER IS, and the harness's two sides are not installed
alike: the reference runs from an editable install of `runtime-py`, the port from the
checkout. Comparing those two answers compares two ENVIRONMENTS, not two implementations —
which is what made `wire/build_identity: the unavailable list agrees` red at `c9372ca` with
no code difference behind it. Here both sides are handed the same constructed shape, so a
difference is a difference in the code.
"""

from __future__ import annotations

import json
import sys
from importlib import metadata
from pathlib import Path

from bantamkit.mcpserver import (
    INSTALL_SHAPES,
    _derive_install,
    _install_source_condition,
    _Undetermined,
)


def answer(scenario: dict) -> dict:
    """One fixture's whole answer: the shape, the origin, the refusal, and the condition."""
    running = Path(scenario["py"]["running"])
    site = scenario["py"]["site"]
    try:
        install = _derive_install(running, metadata.distributions(path=[site]))
    except _Undetermined as exc:
        return {"refused": True, "refusal": str(exc)}
    condition = _install_source_condition(install)
    return {
        "refused": False,
        "shape": install.shape,
        "source": install.source,
        "source_reason": install.source_reason,
        # The same expression `build_identity` uses, and it is a SEPARATE fact from the
        # condition: `null` is a check that could not be made, which neither side reports as
        # a missing origin. `Path.exists()` swallows exactly the errnos in
        # `pathlib._ignore_error`; the port's `originStat` reproduces that set by name.
        "source_exists": None if install.source is None else _exists(install.source),
        "condition": None if condition is None else {"key": condition.key, "sentence": condition.sentence},
    }


def _exists(source: str) -> bool | None:
    try:
        return Path(source).exists()
    except OSError:
        return None


def main() -> int:
    payload = json.loads(sys.stdin.read())
    print(
        json.dumps(
            {
                "shapes": list(INSTALL_SHAPES),
                "answers": {s["id"]: answer(s) for s in payload["scenarios"]},
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
