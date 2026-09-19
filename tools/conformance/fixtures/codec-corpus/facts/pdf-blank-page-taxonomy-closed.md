---
name: pdf-blank-page-taxonomy-closed
description: why a pdf page reads blank in bantamkit and how the omission names which
  of four reasons - the whitespace case was 7 of 10 on the real corpus
type: project
created: '2026-08-22'
last_recalled: '2026-09-15'
links:
- project-media-corpus-is-empty
- project-docread-coverage-measured
---

Merged d19ac9e (PR #66), register section AI, RB-P103. docread._pdf_refusal had chosen between FOUR reasons a PDF yields no text since J25-D3; the page-grain unread-page omission 79 lines below named THREE. Measured over 30 real PDFs (512 parts, 10 blank pages across 6 files): no-operator 3, mapped-and-WHITESPACE 7, unmapped 0, no-character 0. Mechanism: in pdfread show(), a run whose chars all map to whitespace increments vouched, appends to pieces, then fails text.strip(), so no _Run is appended. Fix uses vouched as discriminator and replaces the count/what overload with a facts tuple. Coverage 502/512 = 98.05%. Residual filed unclosed: docread._pdf_refusal and contract._omission_line have identical branch orders but are two pieces of code, and nothing in the suite fails if a future edit moves one and not the other.
