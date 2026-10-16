#!/bin/bash
# usage: gates.sh <outdir>
set -u
SP=$S/j698
O=$1; mkdir -p $O/home $O/idx $O/tmp $O/ct
unset BANTAMKIT_INDEX_DIR BANTAMKIT_RETENTION; export HOME=$O/home USERPROFILE=$O/home TMPDIR=$O/tmp/; mkdir -p $O/home/.bantamkit/hooks; echo "{}" > $O/home/.bantamkit/hooks/ledger-canary.json; touch -t 202609160000 $O/home/.bantamkit/hooks/ledger-canary.json
R=/Users/kktest/Documents/Claude/Projects/bantamkit
cd $R/runtime-ts && npm run build > $O/build.txt 2>&1; echo "build=$?" >> $O/build.txt
cd $R && .venv/bin/ruff check runtime-py tools > $O/ruff.txt 2>&1
cd $R/runtime-ts && npm test > $O/npm.txt 2>&1
cd $R && .venv/bin/python -m pytest runtime-py/tests -q -p no:randomly > $O/pytest.txt 2>&1
cd $R && TMPDIR=$O/ct/ node tools/conformance/run.mjs --all > $O/conf.txt 2>&1
find $O/home -type f > $O/canary-files.txt
echo DONE > $O/done
