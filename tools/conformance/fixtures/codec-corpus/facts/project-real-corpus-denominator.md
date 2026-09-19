---
name: project-real-corpus-denominator
description: what is actually in ~/Downloads and ~/Documents/Claude/Projects - the
  file counts a reader must cover, and the fact that video is one file and audio is
  zero
type: project
created: '2026-08-21'
last_recalled: '2026-09-18'
links:
- feedback-a-reader-is-a-program-not-a-prompt
- project-two-docread-defects-found-by-census
- project-bantamkit-program-backlog
---

Measured 2026-08-21 over the two corpora the user named. Exclusions applied at any depth: `node_modules .venv venv .git __pycache__ dist build .next target site-packages .cache`. Regular files only.

**THE DENOMINATOR — 48,618 files / 2,390,298,731 bytes combined.**
- `~/Downloads` = **98 files / 263,482,257 B** (no vendor dirs present, raw == excluded).
- `~/Documents/Claude/Projects` = **48,520 files / 2,126,816,474 B** after exclusion. Raw is **3,434,113 files / 68.67 GB** — **98.59% of that tree is build/vendor noise.** Any census that skips the exclusion list is measuring `node_modules`.

**THE FINDING THAT REFRAMES THE GOAL: video is 1 file, audio is 0 files.**
- Video = exactly **one** `.mov`, 11,873,189 B, a screen recording in `~/Downloads`.
- Audio = **zero** files. No `audio/*` sniff anywhere, no file with any of 15 media extensions.
- Images = **1,298 files / 43,289,401 B** (46 in Downloads, 1,252 in Projects after removing 69 `image/x-tga` sniffer false positives — extension-less base64-named cache blobs, not images).

So "read video/voice, 100%" over these corpora is a claim about **one file**. The real uncovered mass is **~5,166 binary files**: SQLite `.db` (151), `.tar.zst` turbo-cache (146, 873 MB), `.zip` (455 MB), PNG, and 3,547 extension-less `application/octet-stream`.

**Coverage by the readers as they ship today (2026-09-05)** (bucketed by running bantamkit's own `sniff()` over all 48,618 files, 9.5 s):

| corpus | covered | plain text/code | uncovered binary |
|---|---|---|---|
| Downloads (98) | 38 (38.78%) | 9 (9.18%) | 51 (52.04%) |
| Projects (48,520) | 76 (0.16%) | 43,329 (89.30%) | 5,115 (10.54%) |

Combined: covered **0.23%**, text **89.14%**, uncovered binary **10.63%**. By bytes the Downloads picture inverts — covered 62.37% of bytes, because the 29 PDFs and 4 xlsx are large.

`SUPPORTED = ("xlsx","docx","pdf","html","mhtml")` plus `("doc","rtf")` via `/usr/bin/textutil`. Dispatch is a **container sniff, never the suffix**; `SUFFIX_KINDS` exists only to report suffix/byte disagreement in a refusal. One `.pdf` in Downloads is really a `.docx`, and one `.doc` sniffs as `message/rfc822`.

See [[project-two-docread-defects-found-by-census]], [[feedback-a-reader-is-a-program-not-a-prompt]].
