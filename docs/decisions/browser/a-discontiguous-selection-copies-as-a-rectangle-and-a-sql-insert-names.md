---
type: Decision
title: "A discontiguous selection copies as a rectangle, and a SQL INSERT names a placeholder"
description: "A discontiguous selection copies as its bounding rectangle with blanks, a copied `INSERT` names the placeholder `\"results\"`, and copy reads the raw row, never a transformed value."
---

A selection with gaps copies as its **bounding rectangle**, with the unselected cells blank. Packing
the selected cells together would silently move values into columns they were never in — a paste
that is wrong in a way nobody can see, where a hole is wrong in a way anybody can. It is stated in
the dialog rather than left to be discovered.

The `INSERT` names `"results"`, deliberately not the source table. These rows are what a filter, an
ordering and possibly a `GROUP BY` produced, so an INSERT naming the source would be valid, runnable
and wrong. Values go through `lib/sql.ts`'s `sqlLiteral` — the **Trino/DML** escaper that doubles
the quote, never `cpcommon.ddl.literal`'s backslash form (SPEC-178's rule; the wrong one fails
silently). XML puts the column name in an **attribute**: an Athena column name is not required to be
a valid XML name, and deriving element names from one produces documents that do not parse.

The copy reads the **raw row**, never `cellText` and never SPEC-184's `transformCell` — a
URL-transformed column pasted into a spreadsheet has to carry its value, not its link text. The test
that proves it uses a **hex** transformer on SPEC-182's precedent, because a URL transformer keeps
the raw value as its link text and the assertion could not have failed.

## History

### 2026-08-14

- **Settled:** entered the register.
