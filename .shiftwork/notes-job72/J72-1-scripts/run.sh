. /private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/bd0487cc-ca79-4278-8b01-22f5d90dd0cf/scratchpad/j721/env.sh
cd /Users/kktest/Documents/Claude/Projects/bantamkit
mkdir -p /private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/bd0487cc-ca79-4278-8b01-22f5d90dd0cf/scratchpad/j721/off/st && rsync -a /Users/kktest/Documents/Claude/Projects/bantamkit/.shiftwork/notes-job68/stores/project/ /private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/bd0487cc-ca79-4278-8b01-22f5d90dd0cf/scratchpad/j721/off/st/
: > /private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/bd0487cc-ca79-4278-8b01-22f5d90dd0cf/scratchpad/j721/off/latency.jsonl
for rep in 1 2 3 4; do for v in beta1 head lazynet noawait both; do
  N=30 node /private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/bd0487cc-ca79-4278-8b01-22f5d90dd0cf/scratchpad/j721/off/bench_embed.mjs $v --store /private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/bd0487cc-ca79-4278-8b01-22f5d90dd0cf/scratchpad/j721/off/st --cli /private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/bd0487cc-ca79-4278-8b01-22f5d90dd0cf/scratchpad/j721/off/$v/runtime-ts/dist/cli.js >> /private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/bd0487cc-ca79-4278-8b01-22f5d90dd0cf/scratchpad/j721/off/latency.jsonl 2>>/private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/bd0487cc-ca79-4278-8b01-22f5d90dd0cf/scratchpad/j721/off/err.log
done; done
echo BENCHDONE
