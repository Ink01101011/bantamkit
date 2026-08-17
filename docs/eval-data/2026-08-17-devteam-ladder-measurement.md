# The four-rung ladder, measured at a real endpoint

M4 of job `devteam-workload-and-null-control`, dated **2026-08-17**.

Three units built the instrument. This one measures. The bar this is graded against
was committed **first**, at `51ccb69`:
[`2026-08-17-devteam-bar-preregistration.md`](2026-08-17-devteam-bar-preregistration.md),
amended-never-rewritten; this unit's amendment is **A5**, a pure append. The ruler is
[`2026-08-17-devteam-accounting-grain.md`](2026-08-17-devteam-accounting-grain.md)
(M3.5) and the null control is
[`2026-08-17-devteam-null-control.md`](2026-08-17-devteam-null-control.md) (M3).

---

## 0. PRE-DECLARATION — committed before any arm ran

**This section is committed in its own commit, before the run, and is not edited
afterwards.** The bar exists because RB-P4 was withdrawn twice for a bar written
after the numbers; a model chosen after seeing which one flatters the target is the
same defect one level down. So the model, the endpoint, the command, the repeat
count and the output paths are fixed here, in advance, and the commit that contains
them contains no number.

### 0.1 The model, and why this one

| field | value |
|---|---|
| endpoint | `http://localhost:11434/v1` (Ollama, OpenAI-compatible chat-completions) |
| **model** | **`qwen3:4b-instruct`** |
| digest | `0edcdef34593` (`/api/tags`, 4.0B, Q4_K_M) |
| repeats | **3** (bar §2 requires R ≥ 3) |
| arms | `graph-off`, `graph-annotate`, `graph-cache`, `graph` — bar §1.1's A0/A1/A2/A3 |
| tasks | `assets/evals/devteam/tasks` (8 tasks, M2's committed surface, untouched) |
| unit of record | one row per (task, config, repeat) — bar §2 |
| rows expected | 8 × 4 × 3 = **96** |

**Why `qwen3:4b-instruct` and not one of the other four models on this machine.**
It is the repo's committed reference model at `--repeats 3` (`docs/eval.md`, the
2026-08-09 sweep), and it is the model the `−0.05%` / `+4.92%` isolated-cache ladder
ran on. That ladder is the single most relevant prior result to Δ%(A2−A1), and a
figure measured on a different model would not be comparable to it. The choice is
therefore fixed by the existing record, not by this unit's preference.

**If a second model is added, its reason is stated here before its numbers exist**,
in a dated append to this section, and it is reported as a separate table — never
merged into the primary. No second model is declared as of this commit.

### 0.2 The exact command

```
.venv/bin/python -m bantamkit.evalrun \
    --base-url http://localhost:11434/v1 --model qwen3:4b-instruct \
    --config graph-off --config graph-annotate --config graph-cache --config graph \
    --tasks assets/evals/devteam/tasks --repeats 3 \
    --json docs/eval-data/2026-08-17-devteam-ladder-<arm>.jsonl
```

One JSONL per arm under `docs/eval-data/`, per bar §2, each carrying `seed`.

### 0.3 Declared before the run: what will be reported whatever the numbers say

- **All three adjacent-pair deltas** — Δ(A1−A0), Δ(A2−A1), Δ(A3−A2) — per task and
  suite-wide, with the headline being Δ%(A2−A1). No all-on-versus-all-off number,
  ever (bar §1.4).
- **Score beside every token figure**, never replaced by a ratio (bar §4). Nothing
  derived from `score/1k tok` (`evalrun.py:713`).
- **The full outcome distribution, including every failure.** A failed run is data:
  the per-task central value is the median across repeats (bar §2) precisely so one
  long-tail run does not become the measurement. No row is dropped.
- **The realised repeat-read count under A0, per task, from this run's own rows** —
  bar §5 R3 is defined on realised behaviour, and this is the first time it is
  evaluated on a real model's trajectory rather than the scripted reference walk.
- **The measured noise floor (bar §3.2), and whether it is degenerate.** The rule is
  derived from the data; on a deterministic client the spread is 0 and the rule
  reduces to "any non-zero delta counts", which is a rule with the data removed. If
  the floor comes out 0 or implausibly small, that is reported as such and no
  §3.2-satisfied effect is claimed on it.
- **Suite-wide figures reported BESIDE the informative-subset figures**, both
  labelled, neither replacing the other. At the reference walk six of eight tasks
  realise zero repeats and are UNINFORMATIVE under §5 R3; a suite average over a set
  whose majority is structurally silent is not a measurement of the mechanism.

### 0.4 Declared before the run: what would make this unit stop rather than report

If proceeding would require substituting a surrogate for something the bar names, or
reporting a number the bar forbids, this unit stops and hands the question back. The
workload asset is not touched: if a task would have to change for a number to look
better, that is said and the run stops.
