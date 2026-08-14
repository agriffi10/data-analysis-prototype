# Completed Spec — SPEC-183: Saving an Exploration as a Saved Query

## What was completed?

An exploration can be saved as a `.sql` file, into a space of the user's choosing, through the
Query workspace's own save path — SPEC-177's generalized flow, reused rather than reimplemented.

- **A `Save as query` control** on the exploration toolbar, carrying a `disabledReason` when there
  is no statement to write (a description that could not render, or one SPEC-181 has suspended).
- **`SaveExplorationDialog`** — a thin host over `SaveQueryDialog` and its Replace confirm. Every
  rule about names, destinations, collisions and in-place replacement stays in `useSaveQuery`.
- **`ExplorationTab.savedQuery`** — the link a successful save leaves behind, validated and
  normalised on restore, written through the new `useExplorationTabs.setTabSavedQuery`.
- **Two `GATED_SURFACES` rows** — the control under **`query`**, its destination selector under
  `sharedWorkspaces`.

The body written is `useExploration.sql` — the exact string `StartQueryExecution` was handed, not a
second rendering of the description. No IaC, no IAM, no new AWS call: the write is
`writeSavedQuery`, which SPEC-173 already shipped.

### Scope change taken during build

**The spec's loading half was removed, and the spec was rewritten before any code was written.**
As filed, SPEC-183 also loaded a `.sql` file as a `{kind: 'sql'}` exploration source, with the two
refusals a wrapped subquery needs. That half is deferred to a later spec, at the user's direction.
Nothing was built for it and nothing was left half-built: the `sql` arm of `ExplorationSource`
stays exactly as SPEC-178 left it, unreachable.

Two consequences worth carrying:

- **`splitSqlStatements` did not have to move.** FR-002 named it, and it lives in
  `features/query/query.sql.ts` — which `features/data-explorer/` may not import (SPEC-176's
  sibling rule). The fix would have been to move the lexer down into `lib/sql.ts`, whose own
  docstring already claims language rules. Worth remembering when the load spec is written; it is
  the one piece of shared ground that arc has not yet moved.
- **`isLinkedSavedQuery` is still a live predicate here**, because a *save* mints a link even
  though a load cannot. Without that, every SPEC-175 rule about in-place replacement would have
  been vacuously satisfied by a predicate that was permanently false.

## The decision worth carrying

**The save control follows `query`, not `dataExplorer` — and the registry is what found it.**

The first cut registered it under `dataExplorer`, which read naturally: it is a Data Explorer
control on a Data Explorer surface. The walking test failed it immediately, because there was no
gate to find — `/explore` already hides the whole workspace, so the row asserted nothing.

That failure was the useful one. The right question is not *which screen is it on* but *which
feature does it belong to*, and this is the exact mirror of SPEC-179's **Explore data** on the
Query rail: a capability of one feature living on another's surface. With `query` off there is no
editor to open a `.sql` file in, and SPEC-173's `saved_queries` folder has already left both the
file browser and the destination picker — so a file written from here would land somewhere the
user cannot see, open or delete. That is precisely the failure "Create table" is on the `query`
list for. The control is **removed** with the flag, not disabled: a `disabledReason` would explain
a state the user has no way to change.

## Deliberate deviations

- **A save does not rename the tab.** The Query workspace's does, because a query tab *is* its
  buffer — its label has no other meaning. An exploration tab is named for the source it is
  exploring, which a save does not change.
- **Mounting is the open state.** `useSaveQuery` carries an `open` flag for a host that lives as
  long as its workspace; here the workspace mounts the dialog when the user asks and unmounts it
  when they are done, so the form shows while no collision is pending and the confirm shows when
  one is. Reading the hook's flag as well would give one dialog two sources of truth.
- **The tab id and the SQL are captured at the gesture**, not read live while the dialog is up.
  This is structural rather than a fix for a reachable bug: the dialog is modal and focus-trapped,
  so nothing can change the active tab behind it today. Capturing is what keeps that a property of
  *this* code rather than of `Modal` — and it is deliberately **not** claimed as a tested guard,
  because no test in this suite can reach the state it defends against.
- **The `sharedWorkspaces` gate is applied at the view**, reusing the list the workspace already
  filters for the source picker (SPEC-174's precedent, repeated) — the hook and the service never
  learn about flags.

## The rejected alternative

**A sidecar JSON carrying the exploration's view state, so a saved exploration could reload as an
exploration.** Rejected, and it stays rejected for the deferred load spec too. SPEC-173 settled
that a saved query is a `.sql` **file** in an ordinary folder; a sidecar reintroduces exactly the
JSON store that spec deleted, and adds a second artifact to keep in sync with a file users can
freely rename, edit, copy or delete from the file browser. The accepted loss is that filters come
back baked into the SQL rather than as editable chips. FR-004's assertion is the guard: a save
issues **exactly one `PutObject`**, counted over a space whose folder marker already exists — so
the count is a statement about sidecars rather than about folder creation.

## What review changed

A fresh-context review found one user-reachable defect and several claims stronger than their
proofs.

- **`Save as query` stayed live after a FAILED execution, and wrote the statement Athena had just
  rejected.** The refusal was keyed on `sql === null`, but a failed apply still *has* a rendered
  statement — while `ExplorationResultsRegion` has deliberately fallen back to the LAST GOOD
  execution's rows (SPEC-181). So the user saved one query under a name whose grid was showing
  another's rows, and the file then failed to open in the Query workspace this spec promises it
  opens in. It is not the same state as `suspended`: SPEC-181 suspends only on a *history step*
  onto a known-bad statement, so the first failure was exactly the window in which Save was
  offered. `failed` is now checked first, with its own wording, and the test drives the real
  expression bar to a real failure.
- **Two claims were softened to what is actually proved.** The gesture-time capture of
  `{tabId, sql}` is structural, not a tested guard — the modal makes the state it defends against
  unreachable, and the review confirmed reverting both halves left the suite green. And FR-001
  AC1's "never re-derived" is guaranteed by `SaveExplorationDialogProps.sql: string`, not by the
  test that reads as its assertion: a second `renderExplorationSql` call over the same description
  is byte-identical, so no equality check could ever catch it. The prop is the guard; the test
  still catches the *stated* risk (saving the bare `SELECT *`).
- **`queryControls.suspended` in the refusal was dead code.** The workspace already passes
  `useExploration` nothing while suspended, so `sql` is null for that reason too — deleting the
  clause changed no test. Removed, with the upstream invariant named where the refusal is built.
- **Axe assertions were missing** for both new surfaces; the dialog and the Replace confirm are
  now asserted over `document.body`, the driven tree, so axe sees them open.
- Three doc corrections: FR-002 AC1 said the control is "unavailable with a `disabledReason`" when
  no exploration is open, where it is in fact **absent** (the region does not mount); the registry
  recipe's comment overstated the same thing; and the spec file is renamed to match its title, so
  one spec no longer goes by three names.

## Verification

`npm run format`, `npm run lint`, `npm run build` and the full Vitest suite green locally —
**2423 tests, 112 files, exit 0**. One new test file, `saveExploration.test.tsx` (16 cases): the
rendered-SQL body compared against the string `runQuery` was actually given, the one-`PutObject`
count (mutation-checked by the reviewer: a fire-and-forget sidecar write reddens 7 of them), the
zero-additional-execution count, the extension-lowercasing at this second caller, the Replace
confirm and the in-place re-save, the mapped inline write failure, the link's round trip through
`sessionStorage`, all three refusal states, and the two axe passes.

**FR-005's interchange is asserted at the STORE, not by mounting the Query workspace.** SPEC-176's
sibling rule forbids one feature's test importing the other, tests included — so the assertion
feeds the object this save wrote back through `listSavedQueries` and `readSavedQuery`, the two
functions the workspace's panel is built on. What the panel does with a `SavedQuery` is SPEC-174's,
already covered.

## Live checks owed

**None of its own.** No infra, no IAM, no AWS call the app did not already make. What no test can
see rides SPEC-185's Safari pass: the toolbar wrapping at 400px now that it carries a tenth
control, and the save dialog over the grid at that width.

## Help & guides

**No change, deliberately.** SPEC-185 writes the Data Explorer's Help content and gains the
`dataExplorer` guide row there, once the feature is shipped end to end (SPEC-074 FR-005).
