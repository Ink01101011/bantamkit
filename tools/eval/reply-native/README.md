# reply-native eval (#292)

Drives `claude -p` over 5 arms × 6 sequences × repeats and scores the result against the
predeclared bar in `docs/superpowers/specs/2026-11-07-reply-native-design.md`.

```bash
cd runtime-ts && npm run build && cd ..          # the user-scope hook runs this checkout
python3 -I tools/eval/reply-native/run_eval.py --out <dir> --reps 3 [--arms OFF,A2] [--seqs S3]
.venv/bin/python tools/eval/reply-native/score.py <dir>/turns.jsonl <dir>/labels.jsonl
```

- `sequences.json`: the six sequences.
- `run_eval.py`: one fresh scratch project per session. Every arm except G passes
  `--disallowedTools Skill`, and every arm passes an empty `--strict-mcp-config`. It appends one
  record per turn to `<dir>/turns.jsonl`.
- `score.py`: joins the turns with `labels.jsonl`, which the agent writes per turn
  (`reply_lang_ok`, `drift_vs_off`, `thinking_english`), and prints PASS, FAIL or DROPPED for each
  line of the bar. It exits 0 only when every line passes.

The arms can run concurrently, one process per `--arms` value, each with its own `--out`. The
2026-11-08 run and its result are in the spec's *Results* section.
