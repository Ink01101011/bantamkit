#!/bin/bash
# J69-8: re-run every scripted mutation of J69-1, J69-3..J69-7 against the CURRENT tree. Throwaway HOME for all.
set -u
export HOME=$S/j698/remut-home USERPROFILE=$S/j698/remut-home BANTAMKIT_RETENTION=off BANTAMKIT_INDEX_DIR=$S/j698/remut-idx
mkdir -p $HOME $BANTAMKIT_INDEX_DIR
cd $S
echo "#### J69-1 M1"; python3 $S/mut/mutate.py M1-node-fold-le runtime-ts/src/storage/logsegment.ts "row.ts < olderThan" "row.ts <= olderThan"
echo "#### J69-4"; bash $S/mut4/run-all.sh
for id in M0 M1 M2 M3 M4 M5 M6 M7 M8 M9 M10 M11; do echo "#### J69-3 $id"; bash $S/j693/mut/mut.sh $id storage-index; done
for id in C0 C1 C2 C4 C7; do echo "#### J69-5 $id"; bash $S/j695/mut/mut.sh $id storage-cold; done
for id in C3 C5 C6; do echo "#### J69-5 $id"; bash $S/j695/mut/mut.sh $id storage-cold wire; done
for id in R0 R1 R2 R3 R4 R5 R6 R7 R8 R11 R12 R13 R14; do echo "#### J69-6 $id"; bash $S/j696/mut/mut.sh $id storage-retention; done
for id in R9 R10; do echo "#### J69-6 $id"; bash $S/j696/mut/mut.sh $id storage-retention wire; done
for id in T0 T1 T2 T3 T4 T5 T7 T8 T9 T10 T11; do echo "#### J69-7 $id"; bash /Users/kktest/Documents/Claude/Projects/bantamkit/.shiftwork/notes-job69/J69-7-mut.sh $id storage-tiers; done
echo "#### J69-7 T6"; bash /Users/kktest/Documents/Claude/Projects/bantamkit/.shiftwork/notes-job69/J69-7-mut.sh T6 storage-tiers wire
echo REMUT-DONE
