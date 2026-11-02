---
type: Decision
title: "A column filter shows as a chip, and the generated SQL is edited in Query on a copy (SPEC-243)"
description: "Each top-level filter item shows as a remove-only chip beside **Filter rows…**, and the generated SQL is edited only through **Open in Query**, which hands a new tab an unrun copy; nothing is ever read back into filters."
---

Three testers hit the same wall: a filter set from a column's menu changed the SQL but never
appeared in the *Filter expression* box, so there was nothing on screen to build on, and the SQL
itself could not be edited.

**Chips, not text written into the box.** Writing a menu filter into the expression as SQL would
make the box a mixture of what the user typed and what the app wrote, and the app could then no
longer tell them apart — the menu could not find or replace its own filter. So each column filter
is a chip beneath the box, worded by `filterChipLabel` with the menu's operator label, quoted
exactly when the renderer quotes it (the same `operatorUsesValueKind` test), and a list named in
the renderer's order. A chip only removes; editing stays in the menu and *Order and filter*, which
already edit it, and the shared `Chip` stays remove-only for the recipient lists it also serves.
Removing one is one `apply`, and focus passes to the next chip, the previous one, or the input,
since the button it was on is gone. Chips follow array order, so an edit moves a chip to the end,
and so does *Order and filter*'s apply for list filters, which it re-sets whole.

**No two-way editing; the edit happens in Query on a copy.** Reading arbitrary SQL back into
filters, sorts and groupings means parsing it, and whatever the parser did not cover would be lost
without a word. **Open in Query** hands the statement the disclosure shows to a new Query tab
through `lib/routeHandoff.ts`, by SPEC-242's rules for a hand-off, unrun, as re-opening a history
entry is, and nothing comes back.

**On a phone the statement always shows** (Andrew, 2026-09-21). The Query page below `tablet` has
no editor and no tab strip, so the receiver also opens the read-only view. It opens a tab too while
there is room, so the statement waits in the editor at a wider width, but it never raises the
tab-limit dialog there: that dialog asks the user to close a tab, which a phone cannot do, and at
the cap it would have shown nothing at all.

**Rejected.** Writing filters into the expression box; a SQL parser to read an edit back; chips
that edit; running the statement on arrival in Query; on a phone, opening no tab, as *View DDL*
does — this statement is meant to be edited, and the editor exists only at a wider width.

> **Superseded (SPEC-251, 2026-09-28) — the expression box, and chips by column.** There is no box
> any more: the chips sit beside **Filter rows…**, one per top-level item, a group worded in its
> brackets, and focus after a removal is found by position and falls back to that button. Chips
> remove and nothing else, and no SQL is read back, as this entry decided. See [the SPEC-251 entry](a-filter-is-conditions-and-groups-built-by-pointing-and-the-expression.md).

## History

### 2026-09-28

- **Changed:** The expression box went: chips sit beside **Filter rows…**, one per top-level item, and focus after a removal is found by position.

### 2026-09-21

- **Settled:** SPEC-243.
