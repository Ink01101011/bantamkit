#!/bin/bash
# J66-4 mutation rounds, on a COPY of the tree. Usage: mutate.sh <name>
S=/private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/e68fe0f2-f473-42b2-bbe2-f1e1e7188209/scratchpad/J66-4
REPO=/Users/kktest/Documents/Claude/Projects/bantamkit
T=$S/tree-$1
rsync -a --delete --exclude .git --exclude .venv --exclude .shiftwork $REPO/ $T/
SV=$T/runtime-ts/dist/mcp/server.js
TR=$T/runtime-ts/dist/mcp/transport.js
SDK=$T/runtime-py/src/mcp   # shadows the venv's `mcp` for the reference server (wire_ref.py sets PYTHONPATH)
case $1 in
  m1-no-schema) sed -i '' 's/=== true || !schema.safeParse(request).success)$/=== true)/' $SV ;;
  m2-no-gate) sed -i '' 's/else if (!accepted \&\& !INIT_EXEMPT.has(method))$/else if (false)/' $SV ;;
  m3-gate-late) sed -i '' 's/^                accepted = true;$/                setImmediate(() => { accepted = true; });/' $SV ;;
  m4-no-decode) sed -i '' 's/const name = raw.replace(/const name = raw; void raw.replace(/' $SV ;;
  m5-no-security) sed -i '' 's/if (name.includes(.\\0.) || climbs(name) || isAbsolutePath(name))$/if (false)/' $SV ;;
  m6-no-nulldrop) sed -i '' 's/^                    if (value === null)$/                    if (false)/' $SV ;;
  m7-no-meta-retry) sed -i '' 's/if (retry === undefined || !retry.success) {/if (true) {/' $TR ;;
  m8-meta-lax) sed -i '' 's/paramsRefused = !referenceTakesMeta(/paramsRefused = false \&\& !referenceTakesMeta(/' $TR ;;
  m9-py-gate-off) cp -R $REPO/.venv/lib/python3.12/site-packages/mcp $SDK; sed -i '' 's/_INIT_EXEMPT: frozenset\[str\] = frozenset({"ping"})/_INIT_EXEMPT: frozenset[str] = frozenset({"ping", "tools\/call", "tools\/list", "resources\/list", "resources\/templates\/list", "resources\/read", "prompts\/list", "prompts\/get"})/' $SDK/server/runner.py ;;
  m10-both-gate-off) cp -R $REPO/.venv/lib/python3.12/site-packages/mcp $SDK; sed -i '' 's/_INIT_EXEMPT: frozenset\[str\] = frozenset({"ping"})/_INIT_EXEMPT: frozenset[str] = frozenset({"ping", "tools\/call", "tools\/list", "resources\/list", "resources\/templates\/list", "resources\/read", "prompts\/list", "prompts\/get"})/' $SDK/server/runner.py; sed -i '' 's/else if (!accepted \&\& !INIT_EXEMPT.has(method))$/else if (false)/' $SV ;;
esac
(cd $REPO && diff runtime-ts/dist/mcp/server.js $SV; diff runtime-ts/dist/mcp/transport.js $TR; [ -d $SDK ] && diff .venv/lib/python3.12/site-packages/mcp/server/runner.py $SDK/server/runner.py) > $S/mut-$1.diff
TMPDIR=/private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/816b6ac2-f242-40ab-adc3-6f7b3bd8e138/scratchpad/cleantmp/ node $T/tools/conformance/run.mjs --suite wire --python $REPO/.venv/bin/python > $S/mut-$1.log 2>&1
echo "$1: diff $(grep -c '^[<>]' $S/mut-$1.diff) lines; $(grep -E '^(PASS|FAIL)' $S/mut-$1.log | tail -1)"
