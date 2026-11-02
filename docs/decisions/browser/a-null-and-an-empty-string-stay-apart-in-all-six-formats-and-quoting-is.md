---
type: Decision
title: "A NULL and an empty string stay apart in all six formats, and quoting is what disambiguates the WORD"
description: "Copy keeps NULL and the empty string apart in all six formats; in a delimited format only `quoteValues` tells a NULL from the text `NULL`, and it is disabled in JSON, SQL and XML."
---

FR-001 AC4 costs nothing in the three formats that have a null of their own — JSON emits `null`, SQL
emits the keyword, XML gets an explicit `null="true"` attribute rather than an empty element. The
delimited formats and Markdown have no such thing, so a NULL renders as the token `NULL` and an
empty string renders as nothing at all. Those two are always distinguishable.

What is **not** distinguishable in a delimited format is a NULL from a cell whose text is literally
`NULL`, and that is the honest limit rather than a defect: `quoteValues` is the answer, since a
quoted `"NULL"` is a value and a bare `NULL` is an absence. The dialog says so beside the control.

`quoteValues` is **inert** in JSON, SQL and XML, whose values are already delimited by the format —
so the checkbox is disabled there with its reason next to it, rather than offered as a control that
silently changes nothing. Two smaller rules fall out of the same reasoning: CSV still quotes what
the *format* requires (an unescaped comma is not ambiguous CSV, it is CSV with an extra column),
and a Markdown table keeps its header row with column names off, because a table without one renders
as a paragraph of pipes in every dialect.

## History

### 2026-08-14

- **Settled:** entered the register.
