#!/bin/zsh
# J69-9 F5 mutations, run on an rsync copy. Usage: J69-9-mut.sh <scratch dir>
set -u
S=$1; M=$S/mut; rm -rf $M; mkdir -p $M
REPO=/Users/kktest/Documents/Claude/Projects/bantamkit
rsync -a --exclude .venv --exclude .git --exclude runtime-ts/node_modules $REPO/ $M/tree/
ln -s $REPO/runtime-ts/node_modules $M/tree/runtime-ts/node_modules
cd $M/tree/runtime-ts
FILES=(test/store.test.mjs test/storage-recall-index.test.mjs test/retrieval.test.mjs test/storage-coldindex.test.mjs)
run(){ F=$M/fake-$1; rm -rf $F; mkdir -p $F
  env -u BANTAMKIT_INDEX_DIR -u BANTAMKIT_RETENTION -u BANTAMKIT_TEST_SANDBOX HOME=$F USERPROFILE=$F node --test $FILES 2>&1 | grep -E '^ℹ (pass|fail)'
  echo "$1 fake-home entries: $(find $F -mindepth 1 | wc -l)"; }
run guarded
cp test/_sandbox.mjs $M/_sandbox.orig
sed -i '' "/^import '.\/_sandbox.mjs';$/d" $FILES
run unguarded
echo "== M1"; node --test test/test-sandbox.test.mjs 2>&1 | grep -E '^ℹ (pass|fail)'
echo "== M2"; sed -i '' 's/^if (!process.env\[SANDBOX_ENV\]) {/if (false) {/' test/_sandbox.mjs
env -u BANTAMKIT_TEST_SANDBOX node --test test/test-sandbox.test.mjs 2>&1 | grep -E '^ℹ (pass|fail)'
echo "== M3"; sed -i '' 's/^if (false) {/if (true) {/' test/_sandbox.mjs
node --test test/test-sandbox.test.mjs 2>&1 | grep -E '^ℹ (pass|fail)'
echo "== M4"; cp $M/_sandbox.orig test/_sandbox.mjs; sed -i '' '/process.env.USERPROFILE = home;/d' test/_sandbox.mjs
node --test test/test-sandbox.test.mjs 2>&1 | grep -E '^ℹ (pass|fail)'
