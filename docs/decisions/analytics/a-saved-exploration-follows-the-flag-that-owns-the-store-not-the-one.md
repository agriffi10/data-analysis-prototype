---
type: Decision
title: "A saved exploration follows the flag that owns the STORE, not the one that owns the screen (SPEC-183)"
description: "Saving an exploration writes the rendered SQL in exactly one `PutObject`, with no sidecar; the control is gated on `query`, not `dataExplorer`, and removed with that flag, and a failed exploration is refused."
---

An exploration can be saved as a `.sql` file through SPEC-177's generalized flow. The body written
is the **rendered** SQL — the exact string `useExploration` handed `StartQueryExecution`, not a
second rendering of the description — because what the user is looking at is what the file should
reproduce, and saving the bare `SELECT *` would produce a file that reopens as something they did
not save. `SaveExplorationDialog` is a thin host over `SaveQueryDialog`: every rule about names,
destinations, collisions and in-place replacement stays in `useSaveQuery`, which is what SPEC-177's
`{sql, link}` signature was for.

**The gate is `query`, not `dataExplorer`, and the registry is what found it.** Registering the
control under `dataExplorer` reads naturally — it is a Data Explorer control on a Data Explorer
surface — and the walking test failed it immediately, because there was no gate to find: `/explore`
already hides the whole workspace, so the row asserted nothing. The right question is not which
screen a control is on but which feature it belongs to, and this is the exact mirror of SPEC-179's
**Explore data** on the Query rail. With `query` off there is no editor to open a `.sql` file in and
SPEC-173's `saved_queries` folder has already left both the file browser and the destination picker,
so a file written from here lands somewhere the user cannot see, open or delete — the failure
"Create table" is on the `query` list for. The control is **removed** with the flag rather than
disabled: a `disabledReason` would explain a state the user has no way to change.

**A save mints a link even though a load cannot.** *(Since SPEC-247 a load can: reopening a view
from the personal folder links the tab to its file.)* `ExplorationTab.savedQuery` is written by
`setTabSavedQuery` on success, **by tab id** — the write is async and a tab switch behind it would
link the wrong tab, whose next re-save would then replace a file it has nothing to do with. Without
it, every SPEC-175 rule about in-place replacement would be vacuously satisfied by a predicate that
is permanently false. It does **not** rename the tab: a Query workspace tab IS its buffer, so a save
renames it; an exploration tab is named for the source it is exploring, which a save does not
change. Restored all-four-fields-or-none, so a document written before this spec restores the tab
without a link rather than being discarded (SPEC-182's precedent).

**A FAILED exploration is refused, and it is the case that has teeth.** The obvious refusal —
"there is no statement" — is keyed on a null `sql`, and a failed apply has a perfectly good one: the
statement Athena rejected. Meanwhile `ExplorationResultsRegion` has deliberately fallen back to the
LAST GOOD execution's rows (SPEC-181), so the grid on screen belongs to a different query. Saving
there writes the rejected statement under a name whose rows the user was reading from somewhere
else, and the file then fails to open in the Query workspace this decision promises it opens in. It
is **not** the suspended state and cannot be folded into it: SPEC-181 suspends only on a *history
step* onto a known-bad statement, so the FIRST failure is exactly the window in which Save is
offered. It is checked first, and worded apart, because something did run.

**The sidecar stays rejected.** A JSON document beside the `.sql` file, carrying the exploration's
view state so a saved exploration could reload as an exploration, would reintroduce exactly the JSON
store SPEC-173 deleted — plus a second artifact to keep in sync with a file users can freely rename,
edit, copy or delete from the file browser. The guard is a count: a save issues **exactly one
`PutObject`**, asserted over a space whose folder marker already exists, so the number is a statement
about sidecars rather than about folder creation.

**Loading a `.sql` file as a source was descoped during build (2026-08-13, user decision) and is
deferred to a later spec.** The `sql` arm of `ExplorationSource` stays as SPEC-178 left it,
unreachable; nothing was half-built for it. *(Since SPEC-242 the arm is reachable — a Query result
opens one — and loading a file is still deferred; see
[its entry](a-statement-handed-to-the-data-explorer-runs-again-and-a-result-it.md).)* One thing that arc will have to face first:
`splitSqlStatements` lives in `features/query/query.sql.ts`, which `features/data-explorer/` may not
import (SPEC-176's sibling rule), and the refusals a wrapped subquery needs are built on it. The
answer is to move the lexer down into `lib/sql.ts`, whose own docstring already claims language
rules rather than feature domain — not to write a second one.

## History

### 2026-08-13

- **Settled:** SPEC-183.
- **Changed:** Loading a `.sql` file as a source was descoped during build and deferred to a later spec.
