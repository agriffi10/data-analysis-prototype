---
type: Decision
title: "The explorer shows a table and nothing else, and a saved view still records the retired choice (2026-09-28)"
description: "The explorer shows rows only as a table; a save still writes the retired `presentation` key as `null`, and the reader takes it off a copy before the strict check when it holds `null`, `grid`, `record` or `text`, refusing any other value."
---

**Record and Text are gone (Andrew, 2026-09-28, on an outside review).** Nobody needs the
explorer's rows as anything but a table, so the Grid/Record/Text control and both other views were
removed — phones included, where Record used to open by default: a phone scrolls the table sideways
and reads a whole value in the Value panel. This supersedes FR-007's mobile default and the Record
and Text claims marked in `docs/decisions/browser/` and in this area's earlier decisions.

**The retired `presentation` key stays in what a save writes, as `null`.** A page loaded before a
deploy runs the old strict reader, which refuses a view line without the key, so dropping it would
make every save unreadable there and after a revert. The reader takes the key off a COPY before the
strict comparison, and only when it holds `null`, `grid`, `record` or `text` — the values some build
wrote — so a view saved in Record opens as the table and any other value is still refused whole. A
line with no such key is accepted too, where the old reader refused it; that is what lets a later
build stop writing the key once no page from before this change can still be open.
The session store needs nothing: its normaliser builds the presentation key by key, so the retired
`presentation` and `recordRowIndex` drop on read.

**The Options menu is ordered by use.** Colors and Transformers moved to a last group of their own —
the same review read them as clutter, and both only change how values look — and **Open in Query**
joined Save as query and Create view…, under the same `query` flag. It repeats the *Generated SQL*
button rather than moving it, and is refused only when there is no statement: a failed one still
opens, because fixing it in Query is the point. It is a second row in `gatedSurfaces.ts`, since the
walk keys on names and the accessible name is already the disclosure button's.

## History

### 2026-09-28

- **Settled:** entered the register.
- **Changed:** Record and Text views were removed, superseding FR-007's mobile default of Record.
