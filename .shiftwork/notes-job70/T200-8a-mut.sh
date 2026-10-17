#!/bin/bash
# usage: T200-8a-mut.sh <ID> -- copy tools/ to a scratch tree, apply one exact replace, run the eval tests
set -u
REPO=/Users/kktest/Documents/Claude/Projects/bantamkit
HERE=$S/tmut
ID=$1; C=$HERE/copy-$ID; H=$HERE/home-$ID
rm -rf "$C" "$H"; mkdir -p "$C" "$H"
rsync -a --exclude __pycache__ "$REPO/tools" "$C/"
case $ID in
  M1) F=tools/eval/recall/score_touch.py;       OLD='str(r.get("ts", "")) < cut';   NEW='str(r.get("ts", "")) <= cut or True';;
  M2) F=tools/eval/recall/mine_touch_silver.py; OLD='if hit is not None and main and prompts:'; NEW='if hit is not None and prompts:';;
  M3) F=tools/eval/recall/mine_touch_silver.py; OLD='row["positives"] = sorted(set(row.pop("hits")) & linked)'; NEW='row["positives"] = sorted(set(row.pop("hits")))';;
  M4) F=tools/eval/recall/tune_context.py;      OLD='if p["precision_at_inject"] >= base]'; NEW='if True]';;
  M5) F=tools/eval/recall/mine_touch_silver.py; OLD='sub = path.parent / session / "subagents"'; NEW='sub = path.parent / session / "nosubagents"';;
  M6) F=tools/eval/recall/build_via_gold.py;    OLD='        if fact not in names:'; NEW='        if False:';;
  *) echo "unknown $ID"; exit 2;;
esac
"$REPO/.venv/bin/python" - "$C/$F" "$OLD" "$NEW" <<'PY' || exit 2
import sys
p, old, new = sys.argv[1:]
s = open(p, encoding="utf-8").read()
if old not in s:
    sys.exit(f"mutation text not found in {p}")
open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
PY
cd "$C" && HOME=$H USERPROFILE=$H BANTAMKIT_INDEX_DIR=$H/index BANTAMKIT_RETENTION=off \
  "$REPO/.venv/bin/python" -m pytest tools/eval/recall/test_eval_touch.py -q -p no:cacheprovider 2>&1 | tail -1
