#!/bin/bash
# J67-8: does a recall's last_recalled stamp keep a hand-written frontmatter key and comment? Both runtimes.
# usage: bash stamp-probe.sh <repo>
R=$1
for side in node py; do
  W=$(mktemp -d); export HOME=$W/home USERPROFILE=$W/home; mkdir -p $HOME
  [ "$HOME" = "$W/home" ] || { echo "HOME redirect failed"; exit 1; }
  M=$W/p/.bantamkit/memory; mkdir -p $M/facts
  printf -- "---\nname: deploy-steps\ndescription: how we deploy to production\ntype: project\n# owner: ops team\npriority: high\ncreated: '2026-10-01'\nlast_recalled: '2026-10-01'\nlinks: []\n---\n\nRun make deploy.\n" > $M/facts/deploy-steps.md
  printf -- "- [[deploy-steps]] (project) — how we deploy to production\n" > $M/index.md
  if [ $side = node ]; then
    (cd $W/p && node --input-type=module -e "const m=await import('$R/runtime-ts/dist/index.js'); const mem=new m.Memory('$M'); console.log(mem.recall('deploy production').split('\n')[0])")
  else
    (cd $W/p && $R/.venv/bin/python -I -c "from bantamkit.memory import Memory; print(Memory('$M').recall('deploy production').splitlines()[0])")
  fi
  echo "== $side after recall:"; cat $M/facts/deploy-steps.md | sed -n 2,9p
  rm -rf $W
done
