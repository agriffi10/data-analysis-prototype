---
type: Decision
title: "Reuse required a MOVE, and the move closed a live flag defect"
description: "`useSaveResults` lives in `features/catalog/` and takes its destinations as a parameter, so each view passes a gated list; Export's refusal is judged on the results location, not the grid."
---

`useSaveResults` lived in `features/query/`, which `features/data-explorer/` may not import
(SPEC-176's sibling clause). "Reuse it unchanged" was therefore unreachable from where it sat, and
the two alternatives were a second implementation of a path with a collision round-trip in it, or the
move SPEC-176 and SPEC-177 already established. It went to `features/catalog/` — which owns the
Athena execution and results layer, and the results object is exactly that — with its body untouched,
`SaveResultsDialog` and `normalizeCsvName` with it, and `features/query/query.format.ts` deleted
because nothing else was in it.

**One thing about the hook did change, and it is why the move was worth more than the reuse.** It
built its own destination list from an unfiltered `useQuerySpaces()`, while every saved-query surface
beside it used a view-gated list — so with `sharedWorkspaces` off, the Query workspace's Save-results
dialog had been offering a colleague's space as a **write target**, unregistered and unnoticed since
SPEC-055. The destinations are now a **parameter** (SPEC-174's shape, and SPEC-177's), both views
hand it a gated list, and both instances have their own `GATED_SURFACES` row — SPEC-175's finding
that each selector instance needs one, applied to the instance that had been missing.

Export's refusal is judged on the **results location**, not on the grid: Athena reports it only for a
SUCCEEDED execution, so "nothing has finished running" and "there is nothing to export" are one fact
rather than two that can drift. A failed apply leaves the last good execution's rows on screen while
that field has already moved on, which is the case a rows-based test would get wrong.

## History

### 2026-08-14

- **Settled:** entered the register.
