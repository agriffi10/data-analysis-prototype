---
type: Decision
title: "A link in a grid is not a tab stop, and the app must not manufacture backtracking"
description: "A link in `role=\"grid\"` carries `tabIndex={-1}` with a focusable copy in the Value panel, and runs of `%` in a `LIKE` pattern collapse to one wildcard, or the regex backtracks catastrophically."
---

Two review findings that generalise beyond this spec.

**`role="grid"` promises ONE tab stop**, which is why every cell but the cursor carries
`tabIndex={-1}` — so a URL transformer's anchor is `tabIndex={-1}` too, or a hundred rows put a
hundred stops inside the grid and Tab walks the column instead of leaving. The **Value panel
carries a focusable copy of the link**, which is what makes that cost a keyboard user nothing, and
the Record view (since removed, [`docs/decisions/analytics/`](../analytics/the-explorer-shows-a-table-and-nothing-else-and-a-saved-view-still.md)) — which already wraps every value in a button — renders the text without an anchor
at all, because an anchor inside a button is nested interactive content. No axe case had rendered a
transformed cell, which is how a `nested-interactive` violation reached review; the file walked
both views, and the fix was verified by reverting it (both since removed with the Record view).

**A wildcard translated one for one manufactures catastrophic backtracking.** Mapping each `%` in a
`LIKE` pattern to its own `[\s\S]*` makes adjacent wildcards nested unbounded quantifiers:
`%%%%%%%%x` against a 60-character value measured at **31.7 s**, in a `useMemo` that runs once per
cell. A length cap bounds the input, not the runtime — and `%%%` is not a hostile regex, it is what
a user types believing it is a wildcard. Runs of `%` collapse to one: identical matches, 0 ms.

## History

### 2026-09-28

- **Changed:** The Record view, which rendered the text without an anchor, was removed with the table-only explorer.

### 2026-08-14

- **Settled:** entered the register.
