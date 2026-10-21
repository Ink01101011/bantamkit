. $S/env.sh
cd $R
: > $S/bench.jsonl
for rep in 1 2; do for v in B A1; do
  N=30 node tools/eval/recall/bench_embed.mjs $v-r$rep --store $S/v/$v/stores/project --cli $S/ts/runtime-ts/dist/cli.js >> $S/bench.jsonl 2>>$S/bench.err
done; done
echo BENCHDONE >> $S/bench.jsonl
