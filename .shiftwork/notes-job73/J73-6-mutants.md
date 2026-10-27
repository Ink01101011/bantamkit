# J73-6 mutant proof (plan Task 6 step 5)

Run 2026-10-21 on a separate worktree `/tmp/j73-mut` at bebf3d2 (its own `.venv` via
`pip install -e "runtime-py[dev,mcp]"`, its own `npm ci && npm run build`), one mutant at a
time applied to BOTH runtimes, `node tools/conformance/run.mjs --suite memorycli`, then
`git checkout -- .` and a rebuild. The clean tree afterwards: `PASS: 458 cases ... 0 failures`.
Worktree removed after.

## (a) list_facts ignores `outcome` (store.py + store.ts)
```
  ✖ memorycli/list-outcome-error/stdout-lines@1: the listing as a literal on each side
  ✖ memorycli/list-outcome-success/stdout-lines@1: the listing as a literal on each side
FAIL: 458 cases, 247 byte-identical, 21 exact-string, 190 structural, 33 ruled-different, 2 failures
      first difference at byte 17 of 313 (python) / 725 (node)
      python : "{\"node\":[\"facts: 2 (<BED>/facts)\",\"bad-one\\tfeedback\\terror\\tactive\\tlesson about zeta failed\",\"old-keeper\\tfeedback\\terror\\tdone\\ta memory-keeper lesson\"],\"python\":[\"facts: 2 (<BED>/facts)\",\"bad-one\\tfeedback\\terror\\tactive\\tlesson about zeta failed\",\"old-keeper\\tfeedback\\terror\\tdone\\ta memory-keeper lesson\"]}"
      node   : "{\"node\":[\"facts: 6 (<BED>/facts)\",\"bad-one\\tfeedback\\terror\\tactive\\tlesson about zeta failed\",\"f-word\\tfeedback\\t-\\tactive\\tclose issues when done\",\"good-one\\tfeedback\\tsuccess\\tactive\\tlesson about zeta worked\",\"old-keeper\\tfeedback\\terror\\tdone\\ta memory-keeper lesson\",\"p-done\\tproject\\t-\\tdone\\ta finished thing\",\"p-live\\tproject\\t-\\tactive\\ta live thing\… (+407 chars)
```

## (b) merge writes the new fact on a dry run (save runs unconditionally; archive only on --apply)
```
  ✖ memorycli/merge-dry/tree-unchanged: the bed is byte for byte the fixture, as a literal on each side
FAIL: 458 cases, 247 byte-identical, 21 exact-string, 190 structural, 33 ruled-different, 1 failures
```

## (c) a done-word counts on `feedback` as well as `project`
```
  ✖ memorycli/candidates-dry/stdout-lines@1: the listing as a literal on each side
  ✖ memorycli/candidates-apply/archived-names: what archive/ holds afterwards, as a literal on each side
  ✖ memorycli/candidates-apply-stops-midway/archived-names: what archive/ holds afterwards, as a literal on each side
  ✖ memorycli/candidates-apply-stops-midway/step-1-refusal: the sentence past the prog, as a literal on each side
FAIL: 458 cases, 247 byte-identical, 21 exact-string, 190 structural, 33 ruled-different, 4 failures
      first difference at byte 30 of 379 (python) / 511 (node)
      python : "{\"node\":[\"archive candidates: 2 (<BED>/facts)\",\"old-keeper\\tstatus: done\\ta memory-keeper lesson\",\"p-done\\tstatus: done\\ta finished thing\",\"dry run; rerun with --apply to archive these 2\"],\"python\":[\"archive candidates: 2 (<BED>/facts)\",\"old-keeper\\tstatus: done\\ta memory-keeper lesson\",\"p-done\\tstatus: done\\ta finished thing\",\"dry run; rerun with --apply to archive the… (+9 chars)
      node   : "{\"node\":[\"archive candidates: 3 (<BED>/facts)\",\"f-word\\tdone-word 'done' in description\\tclose issues when done\",\"old-keeper\\tstatus: done\\ta memory-keeper lesson\",\"p-done\\tstatus: done\\ta finished thing\",\"dry run; rerun with --apply to archive these 3\"],\"python\":[\"archive candidates: 3 (<BED>/facts)\",\"f-word\\tdone-word 'done' in description\\tclose issues when done\",\"ol… (+149 chars)
```

## (d) extra: merge's duplicate exemption for the consumed facts removed (the J73-6 fix)

The pre-check in `merge` still passes, `save` answers `duplicate`, and the second guard
refuses (exit 1, nothing archived) — so the pre-fix silent archive cannot come back unless
both guards go. The literals that see it:
```
  ✖ memorycli/merge-apply-resembling-originals/archived-names: what archive/ holds afterwards, as a literal on each side
  ✖ memorycli/merge-apply-resembling-originals/factsPresent: facts/<name>.md exists, as a literal on each side
  ✖ memorycli/merge-apply-resembling-originals/exit-codes: the status each step must end with, as a literal on each side
FAIL: 458 cases, 247 byte-identical, 21 exact-string, 190 structural, 33 ruled-different, 3 failures
```
