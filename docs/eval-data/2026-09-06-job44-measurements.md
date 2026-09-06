# 2026-09-06 — job44 U11: the (m) hole in the refusal tally, and three rows that had a promise instead of a number

Everything below was measured on 2026-09-06 on the development machine (darwin 25.5.0),
repo at branch `fix/job44-register-drain`, baseline commit `f484c70`. Every number carries
the command that produced it and the corpus it was read from. Where a number could not be
honestly obtained, the row says so and says what a future session would have to turn on.

`docs/ledger.md` is the contract this obeys: **bytes stay bytes**. A figure derived from
bytes is written `est` (bytes/4) and is never called tokens. A token figure comes from
`usage.input_tokens` + `usage.cache_read_input_tokens` + `usage.cache_creation_input_tokens`,
deduped by `requestId`.

The probe scripts for the transcript measurements are throwaway and live outside the repo at
`/private/tmp/claude-501/-Users-kktest-Documents-Claude-Projects-bantamkit/3a7fcb78-73be-4145-9349-e63b61a3ac1f/scratchpad/`
(`probe4.py`, `probe5.py`). They are reproduced inline below so no line here depends on that
directory surviving.

---

## Part 1 — (m): a document that was counted in `files` and in no bucket

### The defect

`tools/ledger/read-bytes.mjs` tallied each read into one of three predicates written
independently of each other:

```js
refusedManifest: seen.filter((r) => r.refused).length,
refusedPage:     seen.filter((r) => !r.refused && r.pageRefused).length,
read:            seen.filter((r) => !r.refused && r.pageRefused === false).length,
```

A **zero-part document** — a manifest that is not a refusal but names no part — carries
`refused: false` and `pageRefused: null`. `null` is neither truthy nor `=== false`, so such a
document was counted in `files` and in none of the three buckets: the ledger's refusal count
neither counted it nor named it.

It is reachable, and in `runtime-py`'s reader exactly one container reaches it — `extract_html`,
`extract_text`, `extract_mhtml`, `extract_pdf` and the textutil path all end in `_nonempty` or
`_refuse`, and `extract_docx` always builds exactly one part. `contract.py`'s `render_document_manifest`
returns `document_manifest_empty` (38 B, no `error: ` prefix) the moment a document has zero
parts, and `docread._nonempty` **deliberately exempts `.xlsx`** from the emptiness refusal
("a declared-but-empty sheet is a real part with no rows and J10's row counts are committed
measurements"). So a workbook that declares no `<sheet>` produces a manifest, not a refusal,
and there is no part to ask a page for.

### The corpus, and why the document had to be derived

Real `.xlsx` files under `~/Downloads` and `~/Documents/Claude/Projects` on 2026-09-06:
**3**, of which zero-sheet workbooks: **0**.

```
python3 - <<'EOF'
import os, zipfile, re
roots = [os.path.expanduser('~/Downloads'), os.path.expanduser('~/Documents/Claude/Projects')]
xs = []
for root in roots:
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in ('.git', 'node_modules', '.venv')]
        xs += [os.path.join(dp, f) for f in fn
               if f.lower().endswith('.xlsx') and not f.startswith('~$')]
zero = [p for p in xs if len(re.findall(
    r'<sheet\b', zipfile.ZipFile(p).read('xl/workbook.xml').decode('utf-8', 'replace'))) == 0]
print('xlsx files:', len(xs), ' zero-sheet:', len(zero))
EOF
# → xlsx files: 3  zero-sheet: 0
```

So the zero-part document was **derived from a real one** rather than mocked: every byte of
`~/Downloads/CI Result.xlsx` (8,664,227 B, 1 declared sheet, a workbook this machine actually
holds) with its `<sheets>` element emptied, which is the one edit that produces the condition.

```
python3 - <<'EOF'
import zipfile, re
src = "/Users/kktest/Downloads/CI Result.xlsx"; dst = "<scratch>/zero-sheet.xlsx"
with zipfile.ZipFile(src) as z, zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as o:
    wb = z.read('xl/workbook.xml').decode('utf-8')
    new = re.sub(r'<sheets>.*?</sheets>', '<sheets/>', wb, flags=re.S)
    assert new != wb
    for n in z.namelist():
        o.writestr(n, new.encode('utf-8') if n == 'xl/workbook.xml' else z.read(n))
EOF
```

Result: 8,241,373 B. **Both servers answer it with a 38 B manifest and no `error:` prefix** —
`refused: false`, `part: null` — which is the condition, on the wire, from the real readers.

### The tally, before and after

Command (identical in both runs; run `npm run build` in `runtime-ts` first; `empty.md` is
`: > <scratch>/empty.md`, a 0-byte file, the manifest-refusal control):

```
node tools/ledger/read-bytes.mjs <scratch>/zero-sheet.xlsx "$HOME/Downloads/CI Result.xlsx" <scratch>/empty.md
```

The `refusals:` line is written to **stderr**, so `--json` stdout stays one document. The
per-file `ms` columns are wall-clock and will differ on a rerun; nothing else will.

**BEFORE** (`tools/ledger/read-bytes.mjs` at `f484c70`) — the three files are a zero-part
workbook, a workbook that reads to a page, and a 0-byte `.md` that is refused at the manifest:

```
refusals: python {"files":3,"refusedManifest":1,"refusedPage":0,"read":1}; node {"files":3,"refusedManifest":1,"refusedPage":0,"read":1}
```

`1 + 0 + 1 = 2`, against `files: 3`. One document is in no bucket, and nothing in the output
says which.

**AFTER**:

```
xlsx	8241373	py no-part(38)	6 ms	node no-part(38)	11 ms	<scratch>/zero-sheet.xlsx
xlsx	8664227	py 1618 + 1904	10 ms	node 1618 + 1904	12 ms	/Users/kktest/Downloads/CI Result.xlsx
md	0	py refused(184)	5 ms	node refused(184)	1 ms	<scratch>/empty.md
refusals: python {"files":3,"refusedManifest":1,"noPart":1,"refusedPage":0,"read":1}; node {"files":3,"refusedManifest":1,"noPart":1,"refusedPage":0,"read":1}
```

`1 + 1 + 0 + 1 = 3 = files`, on both servers, and the per-file line names the case
(`no-part(38)`) instead of printing `38 + -`.

The property is now structural rather than incidental: the three independent predicates were
replaced by one total classifier (`bucket(r)`), so `files` equals the sum of the buckets by
construction and a fourth condition cannot fall between them again.

**Scope note.** This is a change to a measurement tool in `tools/`, not to a runtime surface:
neither `runtime-py/src` nor `runtime-ts/src` is touched, no CLI flag, MCP tool, error
sentence, default or observable behaviour changes, and there is nothing here for
`tools/conformance/run.mjs` to compare. The two-runtimes rule is not engaged; the evidence is
the before/after above, which is rerunnable.

**One thing this uncovered and did NOT fix** (it is `contract.py` / `contract.ts`, which other
units own): `render_document_manifest` returns `document_manifest_empty` — *"no documents are
attached to this task"* — for a document that very much is attached and simply has no parts.
For the derived workbook above, both servers say that sentence about an 8.2 MB file the caller
just named. That is a wording defect one layer below this tool, on both runtimes equally.

---

## Part 2 — the three rows

### Corpus, once, for all three

`~/.claude/projects/**/*.jsonl`, read on 2026-09-06: **851 transcripts, 767 MB**, records
spanning **2026-05-27T10:14:55Z … 2026-09-05T19:50:25Z**. Subagent transcripts under
`<session>/subagents/` are included — they are most of the files.

```
find ~/.claude/projects -name '*.jsonl' | wc -l && du -sh ~/.claude/projects
```

Two secondary sources, both used only as cross-checks:

* `~/Documents/Claude/Projects/bantamkit/.bantamkit/memory/events/mcp.jsonl` — bantamkit's own
  event log, **on** in the host config (`BANTAMKIT_EVENT_LOG: "on"`). It is live and still
  appending, so it is quoted with the moment it was read: at 2026-09-06T02:5xZ it held **439
  records, 48,242 B**, spanning 2026-08-24T20:55:47Z … 2026-09-05T20:00:17Z, with **no `.1`
  generation on disk** — nothing has rotated out (the cap is 1 MiB), so it is complete for its
  window. The `memory_save` counts quoted under #7 were identical across two reads an hour
  apart.
* `~/Library/Caches/claude-cli-nodejs/*/mcp-logs-bantamkit/*.jsonl` — the host's own MCP log,
  10 project directories.

`~/.claude/tool-metrics/events.jsonl` was **not** used as a denominator anywhere: it
self-prunes above 4 MB and drops lines whose session still has a transcript, so it is not a
complete history.

---

### #8 — tokens per `bantamkit_read` call → **NOT MEASURABLE. n = 1.**

**The tool has been called once.** Not once a week — once, in the entire history on this
machine. Three independent sources agree:

| source | `bantamkit_read` calls | window |
|---|---|---|
| transcripts (`tool_use` blocks, deduped by id) | **1** | 2026-05-27 … 2026-09-05 |
| bantamkit event log (`outcome: manifest`) | **1** | 2026-08-24 … 2026-09-05 |
| host MCP log (`Calling MCP tool: bantamkit_read`) | **1** | 10 project dirs |

```
grep -rho "Calling MCP tool: [a-z_]*" ~/Library/Caches/claude-cli-nodejs/*/mcp-logs-bantamkit/*.jsonl | sort | uniq -c | sort -rn
python3 -c "
import json,collections
c=collections.Counter()
for l in open('/Users/kktest/Documents/Claude/Projects/bantamkit/.bantamkit/memory/events/mcp.jsonl'):
    d=json.loads(l); c[(d['tool'],d['outcome'])]+=1
print(c)"
```

The one call, in full — 2026-09-03T17:35:06.840Z, transcript
`~/.claude/projects/-Users-kktest-Documents-Claude-Projects-bantamkit/93518a46-1fab-489c-a738-b55f0dd50060.jsonl`,
`tool_use` `toolu_01FuZSgdSeXyNS6UfGZVv2r3`:

* argument: a 504-row `.py` file (a text container, not a pdf/docx/xlsx — so it is not even in
  the population row 8 asks about);
* `tool_result`: **404 B**;
* it was **batched** with `bantamkit_status` in one assistant turn (`req_011CegueXbe9uDfEWvYpNzxc`),
  so the prompt delta that follows it — `96,763 − 94,264 − 2,082 = 417` real tokens — covers
  **two** tool results and attributes to neither.

So: no median, no mean, no per-kind figure. A single observation, of the wrong container kind,
that cannot be cleanly attributed. **The row stays open, and the reason is not that the
transcripts lack `usage` — it is that the model never calls the tool.**

**What a future session would have to turn on.** Nothing needs enabling; the tool is
registered, available and answering. The same server answered **1,039** calls in the same
corpus — re-measured here rather than quoted from `docs/ledger.md`:

```
python3 - <<'PY'
import json, os, collections
ROOT = os.path.expanduser('~/.claude/projects'); seen, c = set(), collections.Counter()
for dp, dn, fn in os.walk(ROOT):
  for f in fn:
    if not f.endswith('.jsonl'): continue
    raw = open(os.path.join(dp, f), encoding='utf-8', errors='replace').read()
    if 'mcp__bantamkit__' not in raw: continue
    for line in raw.split('\n'):
        if not line: continue
        try: r = json.loads(line)
        except Exception: continue
        if r.get('type') != 'assistant': continue
        for b in ((r.get('message') or {}).get('content') or []):
            if isinstance(b, dict) and b.get('type') == 'tool_use' \
               and str(b.get('name','')).startswith('mcp__bantamkit__') and b['id'] not in seen:
                seen.add(b['id']); c[b['name']] += 1
print(sum(c.values()), c.most_common())
PY
```

| tool | calls | | tool | calls |
|---|---|---|---|---|
| `shiftwork_clock_in` | 395 | | `build_identity` | 9 |
| `shiftwork_clock_out` | 393 | | `validate_json` | 3 |
| `memory_save` | 143 | | **`bantamkit_read`** | **1** |
| `memory_recall` | 47 | | `bantamkit_status` | 1 |
| `shiftwork_status` | 46 | | `skill_audit` | 1 |

(`memory_compact` is absent from that list — see #7. And note the corpus grows while you read
it: this unit's own session added two `shiftwork_*` calls between two runs an hour apart, which
is why a denominator here is a reading with a timestamp and not a constant.)

What is missing is a
*population*: n reads of real pdf/docx/xlsx documents, made by a host session with `usage` on
the record. Either (a) drive the reads deliberately — a scripted session that reads the 47
documents `docs/eval-data/2026-08-28-bantamkit-read-bytes.md` already measured in bytes, one
per assistant turn with **no other tool call in that turn**, then read the deltas back; or
(b) leave the row closed as "the byte figure is the measurement, and tokens per call is not
answerable while the call count is 1".

**The method works and is worth keeping** — it just has nothing to point at here. Prompt
growth attributable to one tool call, over the same 851 transcripts, request pairs where the
first request emitted exactly one `tool_use`:

| tool | n | median real tokens | median `tool_result` bytes |
|---|---|---|---|
| Bash | 29,353 | 764 | 664 |
| Read | 1,227 | 1,561 | 2,443 |
| Edit | 2,626 | 274 | 198 |
| `mcp__bantamkit__shiftwork_clock_in` | 371 | 1,577 | 4,116 |
| `mcp__bantamkit__memory_save` | 114 | 58 | 57 |

Read these as an **upper bound on the tool_result alone**: the delta also carries the host's
injected `<system-reminder>` blocks and the turn's framing. The floor is visible in the last
row — a 57 B result costs 58 tokens — so roughly 50–90 tokens of that delta is per-turn
overhead, not payload. The one thing it settles is that **bytes/4 is not a safe stand-in**:
for `Read`, 2,443 B/4 = 611 `est` against 1,561 real.

---

### #9 — post-compaction re-reads of files already read pre-compaction → **MEASURED**

**41.2 %.** Over all **45** compaction boundaries in the corpus, **5,212** file reads happened
after a boundary and **2,149** of them re-read a path that had already been read before that
same boundary, in the same context.

The unit is one transcript file: a `compact_boundary` record is written into the context that
was compacted, and a subagent's reads live in a different context, so per-file is the right
denominator for "did the rebuilt context read this again".

**Both reading channels are counted, and that is what makes the number honest.** A counter
that matches only the `Read` tool sees 588 post-boundary reads and 115 re-reads; it also sees
**zero** post-boundary `Read` calls at every one of the 12 boundaries after 2026-08-27,
because auto mode routes reads through `cat` / `sed -n` / `head` / `tail`. Reported that way
the rate "falls" 115/588 = 19.6 % → 0/0, and the fall is a change of *channel*, not of
behaviour. (That 19.6 % is a coincidence of digits with the delivered arm's figure below —
different population, different denominator.) Adding
the Bash channel (10,981 of 37,541 Bash `tool_use` blocks in the corpus, not deduped by id,
are a whole-file or line-range
read) restores the population.

#### The arms, and the natural control the repo's own history supplied

`b3625d9` (2026-08-27T15:42Z) shipped the PreCompact steering on `hookSpecificOutput` — an
envelope this host build has no PreCompact member for. The host answered *"Hook JSON output
validation failed"* and **dropped the text**. `eabda96` (2026-09-03T18:27Z) moved it to plain
stdout. The transcript records which of the two happened at each compaction, verbatim, so the
arms are decided by evidence rather than by install date:

| arm | boundaries | post-boundary reads | re-reads | rate |
|---|---|---|---|---|
| no steering echo in the transcript (pre-hook, and 2 later) | 34 | 4,741 | 1,976 | **41.7 %** |
| steering **rejected** by the host (hook ran, model never saw it) | 8 | 359 | 151 | **42.1 %** |
| steering **delivered** to the summariser | 3 | 112 | 22 | **19.6 %** |

Unsteered (the first two arms pooled) 41.7 % vs steered 19.6 %: two-proportion **z = 4.69,
p < 0.001**.

**Do not read that as "the steering works."** Three facts in the same table refuse the causal
claim:

1. The rejected arm is the control the hook's own bug handed us, and it is the sharpest fact
   here: for 8 compactions the hook ran, logged its work, and its output was discarded — and
   the re-read rate (42.1 %) is indistinguishable from having no hook at all (41.7 %).
2. At the 3 delivered boundaries the steering listed 5, 3 and 10 files (the counts in
   `~/.bantamkit/hooks/hook-log.jsonl` and the counts recoverable from the transcript echo
   agree exactly). **Of the 22 re-reads that still happened, 0 were of a file the steering
   named.** The mechanism the list provides did not touch a single one of them.
3. Only 0, 1 and 1 of those listed files had been read in the compacted context at all. The
   hook's read ledger is fed by a `PreToolUse` matcher on **`Read`**, so it lists what the
   session's `Read` calls touched — including its subagents' — while the context being
   compacted reads through Bash. The list is largely about a different set of files.

So: n = 3 steered boundaries, a difference that is statistically real and mechanistically
unexplained, in an arm small enough that two sessions' habits could produce it.

**What the re-reads cost.** Of the 2,149 re-reads, 603 carry a `tool_result` this probe can
attribute to a single path (a Bash call that read exactly one file, or a `Read`); those 603
returned **1,304,414 B** (≈ 326,103 tok `est`). The other 1,546 were multi-path Bash calls
whose bytes cannot be split per path. So 1.3 MB is a **floor**, over 28 % of the population.

**What a future session would have to turn on** to make this row conclusive:

* the hook's read ledger must see the Bash channel (a `PreToolUse` matcher on `Bash`, parsing
  the command), or the list it hands the summariser will keep describing files the context did
  not read;
* `hook-log.jsonl` records `listed` as a **count**. It happens to be recoverable from the
  transcript echo today only because the host displays the steering back to the user; logging
  the list itself would make "was this re-read a file we named" answerable without that;
* more delivered boundaries. Three is a signal, not a result.

#### Rerun

```
python3 - <<'PY'
import json, os, re, shlex, datetime
ROOT = os.path.expanduser('~/.claude/projects')
READERS = {'cat','head','tail','sed','bat','less','more','nl'}
SPLIT = re.compile(r'&&|\|\||[;\n|]')
MARK = 'Files already read in this context'
PATHLINE = re.compile(r'- (/[^\n\\"]+)')
def secs(t): return datetime.datetime.fromisoformat(t.replace('Z','+00:00')).timestamp()
def bash_paths(cmd, cwd):
    out = []
    if '<<' in cmd: cmd = cmd.split('<<')[0]
    for seg in SPLIT.split(cmd):
        try: toks = shlex.split(seg.strip())
        except ValueError: continue
        while toks and re.fullmatch(r'\w+=.*', toks[0]): toks.pop(0)
        if not toks: continue
        prog = os.path.basename(toks[0])
        if prog not in READERS: continue
        rest = [t for t in toks[1:] if not t.startswith('-')]
        if prog == 'sed': rest = rest[1:]
        out += [os.path.normpath(os.path.join(cwd or '/', os.path.expanduser(t)))
                for t in rest if not any(c in t for c in '*?$`')]
    return out
rows = []
for dp, dn, fn in os.walk(ROOT):
  for f in sorted(fn):
    if not f.endswith('.jsonl'): continue
    p = os.path.join(dp, f)
    raw = open(p, encoding='utf-8', errors='replace').read()
    if 'compact_boundary' not in raw: continue
    recs = []
    for line in raw.split('\n'):
        if line:
            try: recs.append(json.loads(line))
            except Exception: pass
    reads, bnds, steer = [], [], []
    for i, r in enumerate(recs):
        if r.get('type') == 'system' and r.get('subtype') == 'compact_boundary':
            bnds.append((i, r)); continue
        s = json.dumps(r)
        if MARK in s:
            block = s.split(MARK, 1)[1].split('Preserve verbatim')[0]
            steer.append((PATHLINE.findall(block),
                          'Hook JSON output validation failed' not in s and 'hookSpecificOutput' not in s,
                          r.get('timestamp')))
        if r.get('type') != 'assistant': continue
        for b in ((r.get('message') or {}).get('content') or []):
            if not isinstance(b, dict) or b.get('type') != 'tool_use': continue
            nm, inp = b.get('name'), (b.get('input') or {})
            if nm == 'Read' and isinstance(inp.get('file_path'), str):
                reads.append((i, os.path.normpath(os.path.expanduser(inp['file_path']))))
            elif nm == 'mcp__bantamkit__bantamkit_read' and isinstance(inp.get('path'), str):
                reads.append((i, os.path.normpath(os.path.expanduser(inp['path']))))
            elif nm == 'Bash' and isinstance(inp.get('command'), str):
                reads += [(i, q) for q in bash_paths(inp['command'], r.get('cwd'))]
    for bi, br in bnds:
        best = None
        for ls, dl, sts in steer:
            if not (sts and br.get('timestamp')): continue
            g = abs(secs(sts) - secs(br['timestamp']))
            if g <= 300 and (best is None or g < best[0]): best = (g, ls, dl)
        pre = {q for i, q in reads if i < bi}
        post = [q for i, q in reads if i > bi]
        L = {os.path.normpath(x) for x in (best[1] if best else [])}
        rows.append({'ts': br.get('timestamp'), 'delivered': best[2] if best else None,
                     'listed': len(L), 'post': len(post),
                     'rereads': sum(1 for q in post if q in pre),
                     'of_listed': sum(1 for q in post if q in L)})
for label, sel in [('ALL', lambda r: True), ('no echo', lambda r: r['delivered'] is None),
                   ('REJECTED', lambda r: r['delivered'] is False),
                   ('DELIVERED', lambda r: r['delivered'] is True)]:
    rs = [r for r in rows if sel(r)]
    tp, tr = sum(r['post'] for r in rs), sum(r['rereads'] for r in rs)
    print(f"{label:10s} boundaries={len(rs):3d} post_reads={tp:5d} rereads={tr:5d} "
          f"pct={100*tr/tp if tp else float('nan'):.1f}%  rereads_of_listed="
          f"{sum(r['of_listed'] for r in rs)}")
PY
```

---

### #7 — refused-budget `memory_save` calls per week → **MEASURED, and the row's premise is refuted**

Over the whole transcript corpus, `memory_save` was called **143** times (`tool_use` blocks,
deduped by id), between **2026-08-17T14:31:50Z and 2026-09-05T19:46:56Z** — a **19.22-day**
window. Outcomes, classified off the `tool_result` text (the MCP result is a JSON envelope, so
the markers are matched anywhere in it, not at the start):

| outcome | marker | n |
|---|---|---|
| saved | `"result": "saved …` | 136 |
| **refused-budget** | `Nothing was saved and retrying will not help` | **5** |
| error / validation | `Error executing tool memory_save` | 2 |

**5 / (19.22 / 7) = 1.82 refused-budget saves per week** over the full window.

That headline is misleading, and the per-call dates say why. All five are inside a single
**20.8-hour** span in one session:

```
2026-08-21T14:33:22.772Z    2026-08-21T17:32:00.850Z    2026-08-22T05:08:44.447Z
2026-08-22T09:24:17.654Z    2026-08-22T10:22:16.134Z
```

Since 2026-08-22T10:22:16Z there have been **113 further `memory_save` calls and 0 refusals**,
over 14.39 days: **0.00 per week**. The bantamkit event log agrees independently over its own
window (2026-08-24 onward): 97 `memory_save` records, all `outcome: saved`, no
`refused-budget`, no `duplicate`, no `refused-validation`.

**The row's success measure reads zero. Its stated cause did not cause it.**
`memory_compact` — which the row credits as "the model's on-refusal path" — shipped
`9fc8607` 2026-08-27T23:07+07:00 (runtime-py) and `39c5a74` 2026-08-28T04:56+07:00 (runtime-ts,
PR #80), which is **five days after the last refusal**. And it has been called **zero times**:
across all 851 transcripts the only `mcp__bantamkit__memory_*` calls are 143 `memory_save` and
47 `memory_recall`; the host MCP log lists `memory_save`, `memory_recall`, `shiftwork_*`,
`build_identity`, `skill_audit`, `bantamkit_status` and `bantamkit_read` — and no
`memory_compact`. The tool is registered and available; it has never been reached for.

So the honest reading is: refused-budget saves went to zero on 2026-08-22, before the tool
that was supposed to drive them there existed, and whatever freed the index that day is not in
evidence here. **Whether `memory_compact` earns its place is untested, not confirmed** — a
tool with 0 invocations has demonstrated nothing, and this row must not be closed as though it
had.

#### Rerun

```
python3 - <<'PY'
import json, os, re, collections, datetime
ROOT = os.path.expanduser('~/.claude/projects')
seen, out, ts = set(), collections.Counter(), []
def cls(t):
    if 'Nothing was saved and retrying will not help' in t: return 'refused-budget'
    if 'Do not rename to force a copy' in t: return 'duplicate'
    if re.search(r'"result"\s*:\s*"saved ', t) or t.strip().startswith('saved '): return 'saved'
    return 'error/validation'
for dp, dn, fn in os.walk(ROOT):
  for f in fn:
    if not f.endswith('.jsonl'): continue
    raw = open(os.path.join(dp, f), encoding='utf-8', errors='replace').read()
    if 'memory_save' not in raw: continue
    name = {}
    for line in raw.split('\n'):
        if not line: continue
        try: r = json.loads(line)
        except Exception: continue
        if r.get('type') == 'assistant':
            for b in ((r.get('message') or {}).get('content') or []):
                if isinstance(b, dict) and b.get('type') == 'tool_use':
                    name[b['id']] = b['name']
                    if b['name'] == 'mcp__bantamkit__memory_save' and b['id'] not in seen:
                        seen.add(b['id']); ts.append(r.get('timestamp'))
        elif r.get('type') == 'user':
            for b in ((r.get('message') or {}).get('content') or []):
                if isinstance(b, dict) and b.get('type') == 'tool_result' \
                   and name.get(b.get('tool_use_id')) == 'mcp__bantamkit__memory_save':
                    c = b.get('content')
                    t = c if isinstance(c, str) else (''.join(x.get('text','') for x in c
                        if isinstance(x, dict)) if isinstance(c, list) else json.dumps(c or ''))
                    out[cls(t)] += 1
ts = sorted(x for x in ts if x)
d = (datetime.datetime.fromisoformat(ts[-1].replace('Z','+00:00'))
     - datetime.datetime.fromisoformat(ts[0].replace('Z','+00:00'))).total_seconds()/86400
print(len(seen), 'calls', ts[0], '..', ts[-1], f'{d:.2f} days', dict(out))
print('refused-budget/week =', out['refused-budget'] / (d/7))
PY
```

---

## What this unit did not measure, and will not claim

* **A "% saved" for any of the three rows.** #8 has no population, #9 has an effect with no
  demonstrated mechanism and n = 3, #7's number is zero for a reason that is not the one the
  row assumes. None of them supports a savings claim.
* **The re-read cost above 1.3 MB.** Multi-path Bash calls return one `tool_result` for
  several files; splitting it per path would be an assumption, not a measurement.
* **Anything from `~/.claude/tool-metrics/events.jsonl`.** It self-prunes; it is not a
  denominator.
* **Any figure through an ollama `/v1` endpoint.** `usage.prompt_tokens` there reports the
  context window, not the prompt. Nothing above touches that path.
