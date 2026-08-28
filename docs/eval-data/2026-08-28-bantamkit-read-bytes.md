# 2026-08-28 — what one `bantamkit_read` puts on the wire, in bytes

Roadmap row 8's metric is "mean `tool_result` tokens per read of a pdf/docx". This is that
number's denominator, measured on the real files under `~/Downloads` on 2026-08-28 at
`c2eef2d`: every `.xlsx` and `.pdf` there (6 and 41 by name; one of the 41 `.pdf`s is a
docx by sniff and is counted as one), plus one docx built from `docs/hooks.md` because the
folder holds no `.docx`. Three arms:

- **(a) Python server** — `bantamkit_read(path)` for the manifest, then
  `bantamkit_read(path, part=<first part as the manifest names it>, offset=0)` for the first
  page, over stdio the way `tools/conformance/suites/wire.mjs` drives a session.
- **(b) Node server** — the same two calls, for the kinds it reads (docx, xlsx); pdf is
  refused there until job44 ports `pdfread`.
- **(c) host `Read`** — what Claude Code's own `Read` tool hands the model for one xlsx and one
  pdf, read off this session's transcript by the ledger method (`tools/ledger/token-ledger.mjs`:
  `tool_result` bytes, and the `usage` delta of the assistant turn that followed).

Bytes are the UTF-8 length of the `text` the host hands the model as the `tool_result`.
**No token figure is derived from bytes.** `tools/ledger/token-ledger.mjs` has no tokenizer —
its only conversion is the `bytes/4` it labels `est` — and bytes/4 is not allowed here. The
only token numbers below are the real `usage` deltas in (c).

## Commands

```
cd runtime-ts && npm run build && cd ..
find ~/Downloads -maxdepth 1 \( -iname '*.xlsx' -o -iname '*.pdf' \) -print0 | sort -z \
  | xargs -0 node tools/ledger/read-bytes.mjs --json <scratch>/docs/hooks.docx > read-bytes.json 2> tally.err   # stderr: the refusal tally
```

`tools/ledger/read-bytes.mjs` is the driver (Python: `.venv/bin/python -m bantamkit.mcpserver`
with `PYTHONPATH=runtime-py/src`; Node: `runtime-ts/dist/cli.js`; both with `HOME` and
`--store` in a scratch directory). The docx was built with `zipfile` from the 16 paragraphs
of `docs/hooks.md` (3,410 bytes). Arm (c) was two `Read` calls from this session and
`~/.claude/projects/<slug>/<session>/subagents/agent-acd86fe4ecc3c6e40.jsonl`.

## Result — per kind (Python arm; Node identical where it reads)

Re-measured 2026-08-28 at F4 (branch `feat/bantamkit-read-tool`, after c8a62aa) with the
refusal tally fixed: the first run of `read-bytes.mjs` tested `manifest.isError`, which is
never true for a READER refusal (both servers answer those as a normal reply starting
`error: `), so a refused page was averaged in as a page. **One read was a refusal:**
`step test.xlsx`'s first sheet, `"Result  onborad"`, has 0 rows, so `offset: 0` is past its
end and the 87-byte reply is `refused-offset`, on both servers. No manifest was refused
(48 of 48 served). The script now prints the tally to stderr:

```
refusals: python {"files":48,"refusedManifest":0,"refusedPage":1,"read":47}; node {"files":7,"refusedManifest":0,"refusedPage":1,"read":6}
```

Manifest columns are over the files whose manifest was served (all), page and
manifest+page columns over the files whose page was served. Medians are the upper median
(`sorted[n//2]`), the convention the first run used.

| kind | n | read to a page | refused (manifest / page) | raw bytes mean / median | manifest bytes mean / median (min–max) | page-0 bytes mean / median (min–max) | manifest+page mean / median | reader ms mean / median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| pdf | 40 | 40 | 0 / 0 | 3,282,814 / 855,702 | 14,823 / 2,297 (317–357,083) | 1,945 / 1,932 (254–3,343) | 16,768 / 4,270 | 1,462 / 83 |
| xlsx | 6 | 5 | 0 / 1 | 9,067,242 / 16,959,476 | 6,078 / 1,303 (1,037–29,879) | 2,649 / 2,714 (1,113–3,356) | 9,735 / 3,929 | 14 / 10 |
| docx | 2 | 2 | 0 / 0 | 167,301 / 327,809 | 1,115 / 1,305 (925–1,305) | 1,652 / 1,902 (1,403–1,902) | 2,768 / 3,207 | 8 / 10 |
| pdf without `21_Day_Challenge.pdf` | 39 | 39 | 0 / 0 | — | 6,047 / — | — | 8,036 / — | 278 / — |

**What moved against the first run, and by how much:** xlsx page-0 bytes mean 2,222 → 2,649
(+427) and min 87 → 1,113, because the 87-byte refusal left the page column; xlsx
manifest+page mean 8,300 → 9,735 (+1,435) over 5 files instead of 6, median 3,929 unchanged;
xlsx manifest mean/median 6,078 / 1,303 unchanged (the manifest WAS served) but its min is
now stated as 1,037 (`step test.xlsx`) — the first run's 1,037 was that same file. Every pdf
number is unchanged (no pdf read was a refusal; the 317-byte `CV_Pattanapol.pdf` manifest
is a served manifest of a pdf with almost no text, not a refusal). docx raw bytes moved
(165,610 / 327,809 → 167,301 / 327,809) only because the rebuilt `hooks.docx` is stored
rather than deflated (6,793 bytes on disk against 3,410; same 16 paragraphs, and its
manifest and page came back at the same 925 and 1,403 bytes on both servers). Reader ms
differ by run-to-run variance only (pdf mean 1,458 → 1,462; the 87 MB pdf 47,549 → 47,650).

Node arm: all 6 xlsx and the built docx came back **byte-identical** to Python for both calls
(manifest and page-0 bytes equal on every file, and the one page refusal is the same 87-byte
sentence on both; the script routes by extension, so the `.pdf`-named docx was not sent to
Node). Node ms on the re-run: 5 on the docx, 7–63 on xlsx.

## Result — arm (c), the host's `Read`

| file | raw bytes | host `Read` tool_result | `usage` delta of the next turn (real tokens) |
|---|---:|---|---:|
| `AP1827-40109_Export_27-08-2026.xlsx` | 12,184 | refused: 167 bytes, `This tool cannot read binary files…` | 817 (includes the tool_use and 17 output tokens of the turn before) |
| `Supakit_Kitjanabumrungsak_CV.pdf`, 2 pages | 89,446 | 80-byte text stub; the file itself travels as a PDF document block (base64, 119,390 bytes in the transcript's `toolUseResult`) and the model sees every page as text plus a page image | 5,995 |

So the host either refuses the binary (xlsx: nothing usable, ~0.8 K tokens for the round trip)
or ships the whole PDF (2 pages ≈ 6 K real tokens). The same two files through
`bantamkit_read`: xlsx 29,879 + 3,350 bytes, pdf 830 + 3,335 bytes. For the pdf that is 4,165
bytes of text against a 6 K-token document block; a token figure for those 4,165 bytes needs a
real `usage` reading of a session that calls `bantamkit_read` through the host, which none has
yet (the tool is not registered on this machine's Claude Code until PR merge).

## What the numbers say

1. **The page is bounded, the manifest is not.** Page-0 bytes never exceed 3,356 on any kind —
   the 3,072-byte ceiling plus the continuation line. The manifest lists every part, one line
   each, so it scales with the part count: `21_Day_Challenge.pdf` (87 MB, 241 pages) returns a
   **357,083-byte manifest**, and the 12 KB Jira export returns a 29,879-byte one because its
   single header row has 100+ columns and the manifest prints the header row whole. That is
   the row-8 follow-up: cap the manifest (part lines paged like rows, header row truncated to
   the ceiling) before "mean bytes per read" can be called small on every file.
2. **Against raw size** the read is 0.5 % of the pdf bytes and 0.09 % of the xlsx bytes in
   aggregate, but that ratio is the wrong headline: the host never hands raw xlsx bytes to the
   model at all, and for pdf it hands a document block whose token cost is the API's, not the
   file's byte length.
3. **The reader's time** is 83 ms median on pdf, 10 ms on xlsx; the 87 MB pdf takes 47.5 s for
   its manifest (every page is opened to count rows) — the same cap fixes that.
4. **Sniff over extension.** One `.pdf` in `~/Downloads` is a docx; the reader named it
   `(docx) part 0 "document"` rather than failing the pdf parser.

## Per file

Re-run at F4; `refused (N)` marks a reply that starts `error: ` and its byte length.

| kind | raw bytes | manifest (py) | page 0 (py) | manifest (node) | page 0 (node) | py ms | node ms | file |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| docx | 6793 | 925 | 1403 | 925 | 1403 | 7 | 5 | hooks.docx |
| docx | 327809 | 1305 | 1902 | — | — | 10 | — | ข้อความบนปุ่มแสดงไม่ครบถ้วน โดยมีข้อความบางส่วนถูกตัดหาย IPAD ในรายการที่อยู่ในสถานะ.pdf |
| pdf | 600111 | 4915 | 2002 | — | — | 59 | — | หน้า CI และหน้า Review overall แสดงข้อมูลไม่ถูกต้อง.pdf |
| pdf | 855702 | 3811 | 1142 | — | — | 71 | — | ทำรายการ MA ปฏิเสธ Consent แล้วข้อมูลใน DB ไม่อัพเดท เป็นข้อมูลล่าสุด.pdf |
| pdf | 5003977 | 21419 | 2388 | — | — | 343 | — | [#AP1827-38919] [SIT_R.SEP26_MA JU][MA][Maker] ไม่สามารถแก้ไขข้อมูล Stakeholder ได้ เมื่อ Status เป็น _ถูกปฏิเสธ_.pdf |
| pdf | 1436898 | 14054 | 2227 | — | — | 186 | — | [#AP1827-39995] [SIT_R.SEP26_MA JU]MA][Physical Flow][App Form] เอกสารคำขอเปลี่ยนแปลงข้อมูล (กรณีนิติบุคคล) แสดงกล่องลายมือชื่อไม.pdf |
| pdf | 1558238 | 14576 | 3113 | — | — | 243 | — | [#AP1827-40109] [Document][SIT_R.SEP26_MA JU][MA][Physical flow] นิติบุคคล subtype 35.นิติบุคคลอาคารชุด เพิ่มบุคคลติด watchlist ระบบไม่แสดงเอกส.pdf |
| pdf | 87734326 | 357083 | 254 | — | — | 47650 | — | 21_Day_Challenge.pdf |
| pdf | 2997409 | 25524 | 1337 | — | — | 1082 | — | AP1827-[STB] _ [Application form] แบบคำขอเปลี่ยนแปลงข้อมูล (กรณีนิติบุคคล) - Sep 2026-200826-093733.pdf |
| pdf | 2111966 | 17604 | 1678 | — | — | 796 | — | AP1827-[STB] _ [MA] Juristic Stakeholder - Sep 2026-240826-110624.pdf |
| pdf | 2111985 | 17604 | 1678 | — | — | 800 | — | AP1827-[STB] _ [MA] Juristic Stakeholder - Sep 2026-260826-081501.pdf |
| xlsx | 1742310 | 1826 | 1113 | 1826 | 1113 | 10 | 7 | AP1827-38636 Retest 052 หมอก.xlsx |
| pdf | 167885 | 740 | 1883 | — | — | 39 | — | AP1827-38922.pdf |
| pdf | 482005 | 2167 | 1303 | — | — | 43 | — | AP1827-38936.pdf |
| pdf | 891509 | 2661 | 1881 | — | — | 72 | — | AP1827-38968.pdf |
| pdf | 321266 | 1518 | 2752 | — | — | 38 | — | AP1827-39087.pdf |
| pdf | 912177 | 2297 | 2553 | — | — | 65 | — | AP1827-39389.pdf |
| pdf | 2228638 | 2463 | 1297 | — | — | 83 | — | AP1827-39993.pdf |
| pdf | 2028281 | 2114 | 1955 | — | — | 78 | — | AP1827-40098.pdf |
| pdf | 2094447 | 7523 | 1585 | — | — | 121 | — | AP1827-40099.pdf |
| xlsx | 12184 | 29879 | 3350 | 29879 | 3350 | 11 | 10 | AP1827-40109_Export_27-08-2026.xlsx |
| pdf | 438551 | 722 | 2984 | — | — | 64 | — | Approved_Timesheet_July_2026_Supakit_Kitjanabumrungsak_(SCB).pdf |
| pdf | 221764 | 8759 | 3343 | — | — | 602 | — | crypto_agreement.pdf |
| pdf | 470027 | 11445 | 3329 | — | — | 1362 | — | customer_agreement.pdf |
| pdf | 81766 | 629 | 2900 | — | — | 90 | — | CV - Supakit Kitjanabumrungsak.pdf |
| pdf | 1141345 | 317 | 2241 | — | — | 128 | — | CV_Pattanapol.pdf |
| pdf | 442509 | 772 | 1722 | — | — | 51 | — | Defect_Apr 2026 RELEASE_SIT_AP1827-38933.pdf |
| xlsx | 105048 | 1303 | 3356 | 1303 | 3356 | 32 | 63 | Draft_Timesheet_August_2026_Supakit Kitjanabumrungsak(SCB).xlsx |
| xlsx | 16959476 | 1215 | 2714 | 1215 | 2714 | 10 | 13 | FCD View Signature_047 ส้ม (1).xlsx |
| xlsx | 16959476 | 1207 | 2710 | 1207 | 2710 | 9 | 15 | FCD View Signature_047 ส้ม.xlsx |
| pdf | 37305 | 1439 | 2084 | — | — | 141 | — | put_v1_support_docmgnt_signatures (1) (1) (1).pdf |
| pdf | 37305 | 1423 | 2080 | — | — | 132 | — | put_v1_support_docmgnt_signatures (1) (1).pdf |
| pdf | 520851 | 1050 | 2057 | — | — | 53 | — | SIT_MAJU_Approval Submit_004_AP1827-39690.pdf |
| pdf | 343227 | 2392 | 1450 | — | — | 35 | — | SIT_MAJU_Approval Submit_023_AP1827-36857.pdf |
| pdf | 703844 | 1473 | 1286 | — | — | 47 | — | SIT_MAJU_Approver KYC_AP1827-39017.pdf |
| pdf | 829230 | 1250 | 2206 | — | — | 69 | — | SIT_MAJU_hysical Flow_043_AP1827-40077.pdf |
| pdf | 652828 | 2105 | 2264 | — | — | 67 | — | SIT_MAJU_Physical_038_AP1827-39194.pdf |
| pdf | 893752 | 1760 | 1932 | — | — | 78 | — | SIT_MAJU_Reconcile_ERM_EDS_027_AP1827-38920.pdf |
| pdf | 873659 | 1771 | 1932 | — | — | 76 | — | SIT_MAJU_Reconcile_ERM_EDS_027_AP1827-38921.pdf |
| pdf | 500514 | 2008 | 1983 | — | — | 41 | — | SIT_MAJU_Stakeholder070_AP1827-39276.pdf |
| pdf | 602230 | 1101 | 1782 | — | — | 36 | — | SIT_TC_JuristicMA_CI_020AP1827-35937 .pdf |
| pdf | 751373 | 1319 | 1411 | — | — | 42 | — | SIT_TC_JuristicMA_Event Log_027 - 28 AP1827-36687.pdf |
| xlsx | 18624955 | 1037 | refused (87) | 1037 | refused (87) | 10 | 18 | step test.xlsx |
| pdf | 2145675 | 12453 | 1113 | — | — | 844 | — | submission-juma-acct-signature-190826-035623.pdf |
| pdf | 2145675 | 12453 | 1113 | — | — | 856 | — | submission-juma-acct-signature-190826-042849.pdf |
| pdf | 2225982 | 13009 | 1113 | — | — | 877 | — | submission-juma-acct-signature-190826-103139.pdf |
| pdf | 1626868 | 14372 | 1113 | — | — | 916 | — | submission-juma-acct-signature-210826-033014.pdf |
| pdf | 89446 | 830 | 3335 | — | — | 115 | — | Supakit_Kitjanabumrungsak_CV.pdf |
