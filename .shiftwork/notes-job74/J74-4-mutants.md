# J74-4 — mutant proof for the native memory mirror (#228)

Worktree `/tmp/j74-mut` cut from `e17d371` (its own `.venv` + `npm ci && npm run build`).
Each mutant applied to BOTH runtimes (except g, which is Node-only by construction), Node
rebuilt, then `node tools/conformance/run.mjs --suite hooks`, `node --test
test/hookadapter.test.mjs` and `pytest runtime-py/tests/test_hookadapter.py` were run, then the
mutant was reverted with `git checkout`. Unmutated control after the loop: `PASS: 247 cases, ...
8 ruled-different, 0 failures`. Driver: `scratchpad/j74-4/mutate.py` (session scratch).

| mutant | hooks suite | Node unit (red) | Python unit (red) |
|---|---|---|---|
| a. `mirrorLinks`/`_mirror_links` return `[]` | 2 red: `native-mirror: PINNED PER SIDE: three facts, and the edited lesson is the one on disk with every link rule applied` — the reference, — the port | `a native write is mirrored into the project store` | `test_a_native_write_is_mirrored_into_the_project_store` |
| b. stub guard removed | 8 red: `native-mirror: PINNED PER SIDE:` the eight payloads give seven records; a mirrored record carries the postSave budget fields…; three facts…; three mirrors bump the ledger… (each — the reference, — the port) | `the export stub is never imported back` | `test_the_export_stub_is_never_imported_back` |
| c. a Write/Edit/MultiEdit of `memory/*.md` in the transcript counts as saved again (the deleted `transcriptWroteMemory`) | 2 red: `hook-degrade: PINNED PER SIDE (#169, amended #228): only a memory_save silences the Stop nudge …` — the reference, — the port | `#169: neither a Read nor an unmirrored Write under memory/ is a save`, `Stop nudges after a native write that was not mirrored` | `test_169_neither_a_read_nor_an_unmirrored_write_under_memory_is_a_save`, `test_stop_nudges_after_a_native_write_that_was_not_mirrored` |
| d. the mirror logs its record directly instead of through `compactIfNeeded`/`_compact_if_needed` | 2 red: `native-mirror: PINNED PER SIDE: a mirrored record carries the postSave budget fields, a skip carries its reason` — the reference, — the port | `a native write is mirrored into the project store` | `test_a_native_write_is_mirrored_into_the_project_store` |
| e. the J74-4 no-keys fix reverted (Python `or not meta`, Node `Object.keys(meta).length === 0`) | 2 red: `native-mirror-edges: the mirror records (minus ts/ms/bytes), side to side`; `native-mirror-edges: PINNED PER SIDE (J74-4): …` — the reference (the port still refuses `{}` by #120, so its literal stays green) | `a frontmatter with no keys is a frontmatter skip` | `test_a_frontmatter_with_no_keys_is_a_frontmatter_skip` |
| f. CRLF read raw on both sides (Python `newline=""`, Node no translation) — SYMMETRIC | 2 red: `native-mirror-edges: PINNED PER SIDE (J74-4): …` — the reference, — the port (both differentials stay green: the symmetric case only a literal sees) | `a CRLF native file is mirrored as Python reads it` | `test_a_crlf_native_file_is_mirrored_as_python_reads_it` |
| g. Node only: `pyRealpath` → `realDir` (the pre-J74-4 code) | 3 red: `native-mirror-edges: every byte the mirror wrote, side to side`; `… the mirror records (minus ts/ms/bytes), side to side`; `… PINNED PER SIDE (J74-4): …` — the port | `a path spelled in another case is not the native directory`, `a path that does not exist resolves through a link the way realpath does` | — (Python unchanged) |

Deviation from the plan's prediction for (a): the plan expected the side-to-side facts and
records cases to redden. They cannot: the mutant is applied to both sides, so both drop the
links identically and the differential stays green. The per-side lesson literal is what sees it.
