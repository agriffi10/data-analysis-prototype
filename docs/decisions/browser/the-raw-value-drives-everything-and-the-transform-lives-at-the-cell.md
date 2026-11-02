---
type: Decision
title: "The raw value drives everything, and the transform lives at the cell"
description: "`transformCell` runs only at the cell, so filters, colour rules, Calc and copy all read the raw row; NULL and the empty string are returned untransformed."
---

`transformCell` is called at the cell and nowhere upstream, so a filter, a colour rule, Calc and
copy all read the raw row — a transformed value reaching any of them is a silent wrong answer
rather than a visible one. The Calc assertion uses a **hex** transformer deliberately: `10` renders
as `3130`, which is itself a plain number, so a Calc reading the rendering would answer a wrong
number rather than fail visibly. NULL and the empty string are returned untransformed, because both
are absences the grid already names in words.

**The Text view stays raw** (superseded 2026-09-28: the Text view was removed, [`docs/decisions/analytics/`](../analytics/the-explorer-shows-a-table-and-nothing-else-and-a-saved-view-still.md)) — no colours, no transformers. It is the drag-select-and-copy surface,
and its whole promise is that what is on screen is what is copied.

## History

### 2026-09-28

- **Changed:** The Text view, which stayed raw with no colours or transformers, was removed.

### 2026-08-14

- **Settled:** entered the register.
