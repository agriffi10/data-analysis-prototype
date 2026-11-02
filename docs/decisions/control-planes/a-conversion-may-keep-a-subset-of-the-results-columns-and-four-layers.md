---
type: Decision
title: "A conversion may keep a subset of the result's columns, and four layers refuse a list that is not one (results conversion)"
description: "A conversion names the columns it keeps by result POSITION, and the API, validate-authorize, describe-results and the converter each refuse a bad list, because a wrong list writes a file rather than failing; `convertsFor` alone decides copy or convert."
---

Hiding a column in the Data Explorer used to change what the grid drew and nothing else, so *Save
results to my files* wrote every hidden column into the file. A request may now name the result
POSITIONS to keep, in the order the file is to carry them (SPEC-239). The alternatives were
re-running a narrowed `SELECT`, which is a second billed scan of the same data, and saving
everything with a note saying so.

**Positions, not names.** The plane already refuses a result whose column names collide once
case-folded, so a position is unambiguous where a name would need that refusal to hold at both
ends — and the browser is the only party that can resolve one, because it is the only one that
knows what the grid is drawing.

**Four layers refuse a list that is not one, and the fourth is not redundant.** The API bounds its
LENGTH, which is the field that makes the request chain's worst case unmeasurable while it is
unbounded. validate-authorize proves the shape — a non-empty list of distinct, non-negative whole
numbers — in an order that is itself load-bearing: `set` hashes its input, so a list holding a list
has to be caught by the element check before the duplicate check asks, and `min` raises on an empty
one. describe-results applies the upper bound, being the first state that knows how wide the result
is. And the converter re-checks before it indexes, because **every way the list can be wrong writes
a FILE rather than failing**: Python indexes from the end, so `[-1]` wrote the LAST column and
reported success; a repeat collapses in the schema dict and writes a file a column short; an empty
list writes a Parquet file of no columns, and it uploads. "Upstream refuses it" is the
refusal-that-denies-nobody argument running backwards — the converter is where the file is written,
and it fails loudly there, as the header check does for the same class of divergence.

**A CSV conversion is what a subset costs.** The CSV Athena wrote is still copied whenever the file
wanted is that object, which is instant and bills nothing; a column choice is the one thing a copy
cannot produce, so `csv` became a fourth writer rather than a fourth reason to re-run a query. It
types nothing — every column is read as text and written back — so the file carries the characters
Athena wrote and only the quoting differs. It cannot count its rows the way its neighbours do: the
Parquet footer is not available to it and the JSON writer's newline count is right only because
JSON escapes an embedded newline, which a CSV carries raw.

**The routing predicate is one function, asked by the button as well as the save.** `convertsFor`
decides copy-or-convert for both of `useSaveResults`' submission points and for the dialog's
primary label, so what the button says and what the save does cannot disagree. The overwrite prompt
carries the list for the same reason it carries the format.

**Three states the browser must keep apart**, and collapsing any two is a live defect: a list means
some columns; `null` means every column in the result's own order, which includes the window before
a result has landed; an empty list means no column of the result is on screen, which is the one
case a save cannot be made from. Reading the third as the second refuses a save that is about to
be fine; reading the second as the third saves the wrong file.

## History

### 2026-09-20

- **Settled:** entered the register.
