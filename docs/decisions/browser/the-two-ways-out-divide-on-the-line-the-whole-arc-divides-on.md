---
type: Decision
title: "The two ways out divide on the line the whole arc divides on"
description: "**Client state is computed in the browser; billed work is not.** A selection aggregate issues **zero** executions, and says which page it counted."
---

Copy takes the **cell selection**, which exists only in the browser: `renderCopy` is a pure function
over the rows already fetched, so copying — in any of six formats, with any options, however many
times — starts no execution and scans no bytes. Export copies the **execution's own results object**
with a server-side `CopyObject`, so what leaves is every row the statement returned rather than the
25 in the grid, again with no second query and no second bill.

That is why **exporting a selection is out of scope** rather than merely unbuilt. A partial export
would need either a second query — the one thing this feature spends ten specs avoiding — or a
client-side re-serialization of rows that are not all loaded, which is the scale lie the whole arc
was designed around. And it is why copy's formats are clipboard-only: the results object is Athena's
CSV, and converting it would mean reading it back through the browser.

Both surfaces say the asymmetry out loud, because it is not inferable. The advanced copy dialog
states that only the loaded page is copied and points at Save results… for the rest; the grid's status line
says `N cells selected on this page` every time it says anything, which is SPEC-182's rule for Calc
applied to the same fact.

A selection aggregate issues **zero** executions, and says which page it counted: client state is computed in the browser, billed work is not.

## History

### 2026-08-14

- **Settled:** entered the register.
