"""Run hidden-oracle criteria against a workspace and print JSON results.

Usage: python -I -B oracle_runner.py <oracle.py> <workspace> [criterion ...]

The harness runs this from a scratch cwd; the workspace is only put on sys.path,
so nothing from the oracle is copied into it and nothing is written there.
"""

from __future__ import annotations

import importlib.util
import json
import sys


def main(argv: list[str]) -> int:
    oracle_path, workspace, *wanted = argv
    sys.dont_write_bytecode = True
    sys.path.insert(0, workspace)
    spec = importlib.util.spec_from_file_location("_hidden_oracle", oracle_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    criteria = module.CRITERIA
    unknown = [cid for cid in wanted if cid not in criteria]
    if unknown:
        print(json.dumps({"error": f"unknown criteria: {', '.join(unknown)}"}))
        return 2
    results: dict[str, bool] = {}
    details: dict[str, str] = {}
    for cid in wanted or list(criteria):
        try:
            criteria[cid]()
        except Exception as exc:  # noqa: BLE001 - any failure means the criterion fails
            results[cid] = False
            details[cid] = f"{type(exc).__name__}: {exc}"[:500]
        else:
            results[cid] = True
    print(json.dumps({"results": results, "details": details}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
