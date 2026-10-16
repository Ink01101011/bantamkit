#!/bin/bash
# usage: privacy.sh <sha> -- every .shiftwork path any #200 commit touched, at <sha>: UUIDs, memory fact names, quoted prompt-ish strings
cd /Users/kktest/Documents/Claude/Projects/bantamkit
SHA=${1:-0d33d03}; T=$(mktemp)
NAMES=$(mktemp); ls ~/.claude/projects/-Users-kktest-Documents-Claude-Projects-bantamkit/memory/ | sed -n 's/\.md$//p' | grep -v '^MEMORY$' > $NAMES
for f in $(for c in $(git log --format=%h --grep='#200' $SHA); do git show --name-only --format= $c -- .shiftwork; done | sort -u); do
  git show "$SHA:$f" > $T 2>/dev/null || { echo "$f (absent at $SHA)"; continue; }
  u=$(grep -cE "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" $T)
  n=$(grep -oFf $NAMES $T | sort -u | tr '\n' ' ')
  echo "$f uuid_lines=$u fact_names=[${n}]"
done; rm -f $T $NAMES
