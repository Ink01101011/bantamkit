#!/bin/bash
# probe.sh -- Task 9 Step 2 properties measurable on macOS, both runtimes, at the review worktree (0d33d03)
set -u
RV=${S:?set S to a scratch dir}/rv; P=${S:?set S to a scratch dir}/probe; rm -rf $P; mkdir -p $P/home $P/ct
export HOME=$P/home USERPROFILE=$P/home BANTAMKIT_INDEX_DIR=$P/home/index BANTAMKIT_RETENTION=off TMPDIR=$P/ct
GIT=$(command -v git)
BED=$P/bed; mkdir -p $BED/src; cd $BED && git init -q && echo x > src/a.py && git add . && git -c user.email=a@b -c user.name=a commit -qm init
NODE_HOOK="node $RV/tools/hooks/bantamkit-hook.mjs"
PY_HOOK="$RV/.venv/bin/python -c 'from bantamkit.hookadapter import run_hook; run_hook()'"
ev() { printf '{"hook_event_name":"%s","session_id":"%s","cwd":"%s","tool_name":"%s","tool_input":{"file_path":"%s"},"prompt":"%s","transcript_path":"%s"}' "$1" "$2" "$3" "$4" "$5" "$6" "$P/t.jsonl"; }
: > $P/t.jsonl
for side in node py; do
  [ $side = node ] && H=$NODE_HOOK || H=$PY_HOOK
  S1=par-$side
  # 1. 20 parallel PostToolUse Read processes against one session
  for i in $(seq 1 20); do ev PostToolUse $S1 $BED Read $BED/src/a.py "" | eval $H >/dev/null 2>&1 & done; wait
  echo "[$side] parallel: seq file = $(cat $HOME/.bantamkit/hooks/ledger-$S1.seq.json)"
  $RV/.venv/bin/python -I -c "import json,glob,sys;r=[json.loads(l) for f in glob.glob('$HOME/.bantamkit/touch/*.jsonl') for l in open(f)];s=sorted(x['seq'] for x in r if x.get('session')=='$S1');print('[$side] parallel: lines',len(s),'seqs 1..20 no gap',s==list(range(1,21)))"
done
# 2. a .git FILE worktree
cd $BED && git worktree add -q $P/wt 2>/dev/null
for side in node py; do
  [ $side = node ] && H=$NODE_HOOK || H=$PY_HOOK
  ev PostToolUse wt-$side $P/wt Read $P/wt/src/a.py "" | eval $H >/dev/null 2>&1
  $RV/.venv/bin/python -I -c "import json,glob,hashlib,os;top=os.path.realpath('$P/wt');rid=hashlib.sha256(top.encode()).hexdigest()[:16];f='$HOME/.bantamkit/touch/'+rid+'.jsonl';r=[json.loads(l) for l in open(f)] if os.path.exists(f) else [];print('[$side] worktree: log for sha16(wt) exists',os.path.exists(f),[ (x['op'],x['path']) for x in r if x['session']=='wt-$side'])"
done
# 3. git absent from PATH: every hook exits 0; what is written
NOGIT=$P/nogitbin; mkdir -p $NOGIT; ln -sf $(command -v node) $NOGIT/node
for side in node py; do
  [ $side = node ] && H=$NODE_HOOK || H=$PY_HOOK
  S3=nogit-$side; rc=""
  for e in "SessionStart" "UserPromptSubmit" "PostToolUse" "Stop"; do
    ev $e $S3 $BED Read $BED/src/a.py "a prompt long enough to recall" | PATH=$NOGIT eval $H >$P/out-$side-$e.txt 2>&1; rc="$rc $e=$?"
  done
  echo "[$side] no git on PATH: exits$rc"
  $RV/.venv/bin/python -I -c "import json,glob;r=[json.loads(l) for f in glob.glob('$HOME/.bantamkit/touch/*.jsonl') for l in open(f)];print('[$side] no git: touch lines for this session',[(x['op'],x.get('path')) for x in r if x.get('session')=='$S3'])"
  ls $HOME/.bantamkit/hooks/ | grep -c "ledger-$S3.turn.json" | sed "s/^/[$side] no git: turn files = /"
done
grep -c '"touch":"miss"' $HOME/.bantamkit/hooks/hook-log.jsonl | sed 's/^/touch misses logged: /'
grep -c '"event":"error"' $HOME/.bantamkit/hooks/hook-log.jsonl | sed 's/^/hook error records: /'
