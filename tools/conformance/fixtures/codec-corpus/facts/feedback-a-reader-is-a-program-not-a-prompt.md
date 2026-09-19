---
name: feedback-a-reader-is-a-program-not-a-prompt
description: the user's ruling on how files must reach an agent - a program digests
  and converts first, never hand the raw bytes to the model and make it read them
type: feedback
created: '2026-08-21'
last_recalled: '2026-09-19'
links:
- feedback-real-probe-only
- feedback-prescribe-the-property-not-the-mechanism
- feedback-ship-it-working-and-measured
- project-j2-compaction-measured-result
---

Ruled by the user 2026-08-21, in their words: *"ฉันคิดว่าเรื่องการอ่านไฟล์ต้องทำ program ขึ้นมาช่วยย่อยหรือแปลงให้ agent อ่านหรือเข้าใจ ไม่ใช่ยัดไปใส่ agent แล้วบังคับให้อ่านออก"*

**The rule.** Any file an agent must understand goes through a PROGRAM that digests or converts it into text the agent can read. The agent is never handed the raw artifact — no base64 blob, no binary paste, no "here are 60 frames, figure it out". Conversion is a deterministic, re-runnable step that lives in code.

**Why:** three reasons, and they compound.
1. **Tokens.** The conversion is the token lever. A program that turns a 4 MB xlsx into 3 KB of extracted meaning is an unconditional reduction on ingestion, with none of the fidelity trade that killed the compaction arms ([[project-j2-compaction-measured-result]]).
2. **Verifiability.** A program's output can be pinned, diffed, mutated and reddened by a test node. A model's reading of a blob can only be re-asked, and it answers differently each time.
3. **Honesty.** A program can REFUSE — "this page yielded no characters, and here is why" — which is the provenance rule the PDF reader already enforces (anything not vouched for is counted, not emitted). A model handed a blob will produce plausible text for a page it could not read.

**How to apply.** When a format is unreadable, the deliverable is a converter, not a better prompt. A model may be used INSIDE the program as one conversion step (e.g. frames → description), but its input must already be something a program prepared, and its output is a recorded artifact like any other. If no converter is possible, the program returns a stated refusal naming the missing capability — never a guess.

Corollary for the media work: "read video" decomposes into a program that extracts structure and audio, and only then, if needed, a model step. It is not "give the video to a vision model".

See [[feedback-real-probe-only]], [[feedback-prescribe-the-property-not-the-mechanism]], [[feedback-ship-it-working-and-measured]].
