. $S/env.sh
for mq in "bge-m3 Q0" "qwen3-embedding:0.6b Q3" "snowflake-arctic-embed2 Q4"; do
  set -- $mq
  $S/../j721/npvenv/bin/python $S/dev_embed.py $P/dev-prompts.jsonl $1 $2 $C >> $S/embed.log 2>&1 || echo "FAIL $1" >> $S/embed.log
done
echo EMBEDDONE >> $S/embed.log
