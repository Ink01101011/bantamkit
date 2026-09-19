---
name: feedback-must-run-on-windows-not-just-macos
description: the user requires bantamkit to work on Windows too, not only macOS -
  so a platform-only converter route is a backend, never the design
type: feedback
created: '2026-08-21'
last_recalled: '2026-09-14'
links:
- feedback-a-reader-is-a-program-not-a-prompt
- project-media-route-zero-install-on-macos
- feedback-ship-it-working-and-measured
---

Ruled by the user 2026-08-21: *"อย่าลืมเรื่อง device ว่าไม่ใช่แค่ macOS นะ ต้อง Windows ใช้ได้ด้วยนะ"*

**The rule.** Any capability shipped here must run on Windows as well as macOS. A platform-specific tool is permitted only as an **optional backend behind a portable interface**, never as the design.

**Why this bites right now (2026-09-11).** A probe measured a zero-install media route on this machine — Apple's AVFoundation for exact-timestamp frame extraction and Speech.framework for on-device ASR, both reachable because full Xcode is installed. It is genuinely the cheapest route *here* and it is 100% unavailable on Windows. Shipping it as *the* reader would mean the feature does not exist for half the target.

**How to apply — the shape the converter must take:**
1. **A portable core that always works**: stdlib only. ISO-BMFF/RIFF container parsing, track inventory, codecs, duration, dimensions, language, chapter atoms. Identical output on every OS, no external process.
2. **Backends, probed at runtime and ranked**, each answering the same interface: macOS (AVFoundation + Speech via a compiled helper, `qlmanage`, `afconvert`, `textutil`, `mdls`), Windows (Media Foundation / `Windows.Media.SpeechRecognition`, or PowerShell shells), and the cross-platform fallback (`ffmpeg` + `whisper.cpp` when present on PATH).
3. **A stated refusal when no backend is available** — naming the missing capability and the platform, never a silent empty result. The refusal itself must be portable and identical in shape.
4. **Capability reporting is part of the output**, so a caller can tell "this file has no speech" from "this machine cannot transcribe".

**Test consequence:** a node that only passes on macOS is a platform-conditional node and must be marked as such. Coverage claimed on macOS is NOT coverage; the portable core is what a coverage number may be quoted over.

See [[feedback-a-reader-is-a-program-not-a-prompt]], [[project-media-route-zero-install-on-macos]].
