#!/bin/bash
# usage: mutate.sh <label> <python-old> <python-new>
J=/private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/e68fe0f2-f473-42b2-bbe2-f1e1e7188209/scratchpad/j11; M=$J/mut
cp $J/factfile.pristine.ts $M/runtime-ts/src/memory/factfile.ts
/Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python -c "
import sys;p=sys.argv[1];s=open(p).read();o=sys.argv[2];n=sys.argv[3]
assert s.count(o)==1,'mutation anchor not unique/absent';open(p,'w').write(s.replace(o,n))" $M/runtime-ts/src/memory/factfile.ts "$2" "$3" || exit 1
(cd $M/runtime-ts && npx tsc -p tsconfig.json >/dev/null 2>&1)
echo "== $1"
(cd $M && TMPDIR=/private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/816b6ac2-f242-40ab-adc3-6f7b3bd8e138/scratchpad/cleantmp/ node tools/conformance/run.mjs --suite codec 2>&1 | grep -E '^  ✖|^(PASS|FAIL)' | sed 's/^  ✖ codec\//   red: /' | grep -E "^(PASS|FAIL)")
cp $J/factfile.pristine.ts $M/runtime-ts/src/memory/factfile.ts
