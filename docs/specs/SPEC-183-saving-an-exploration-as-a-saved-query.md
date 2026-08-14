# Spec: Saving an Exploration as a Saved Query

**ID:** SPEC-183
**Status:** Completed
**Last Updated:** 2026-08-13
**Depends On:** SPEC-177, SPEC-178, SPEC-181

## Overview

An exploration can be saved as a `.sql` file, into a space of the user's choosing, through the
same flow the Query workspace uses — SPEC-177's generalized save. What is written is the
exploration's **rendered** SQL: the filters, the expression, the ordering and the grouping, as
the statement that produced the rows on screen.

There is one store, so the file lands in the same `saved_queries/` folder the Query workspace
reads, appears in its saved-queries panel, and opens there into an editor tab.

**Loading a `.sql` file as an exploration source is deferred.** The `sql` arm of SPEC-178's
source union stays unreachable, and with it the wrapped-subquery refusals a loaded file would
need. That is a scope decision taken during build (2026-08-13), not a rejection: the arc's
argument for the union — that a saved file is a SOURCE rather than a view state, because it
cannot be reverse-engineered into a table plus filters without a SQL parser — is unchanged, and
a later spec can deliver the load surface without touching anything here.

The asymmetry that motivated the deferral is still worth stating, because it is what a load
surface would have to own: **a saved exploration would reload as a query, not as an
exploration**, its filters baked into the SQL rather than returning as editable chips. The
alternative — a sidecar JSON carrying the view state — is rejected outright and stays rejected:
SPEC-173 settled that a saved query is a `.sql` **file** in an ordinary folder, and a sidecar
would reintroduce exactly the JSON store that spec deleted, plus a second artifact to keep in
sync with a file users can freely rename, edit or delete from the file browser.

## Scope

### In Scope

- Saving an exploration's **rendered** SQL as a `.sql` file, into a chosen space.
- A registry row for the save control under **`query`** — the flag that owns the store, not
  the one that owns the screen — and one for its destination selector under
  `sharedWorkspaces`.
- The link a successful save leaves on the tab, so a re-save replaces in place exactly as the
  Query workspace's does.

### Out of Scope

- **Loading a `.sql` file as an exploration source** — deferred to a later spec, along with the
  multi-statement and non-`SELECT` refusals a wrapped subquery requires.
- **Any new store, format, sidecar or metadata.** Nothing is written but a `.sql` file.
- **Migrating or rewriting existing saved queries.**
- **Editing the loaded SQL.** The Data Explorer has no SQL editor; a file that needs editing
  belongs in the Query workspace, which is one click away.
- **`SavedQueriesPanel`** — the Query workspace's own rail panel, untouched.
- Changing any SPEC-173/174/175 rule.

---

## Functional Requirements

### FR-001: Saving an exploration

#### Description:

Saving writes the exploration's **rendered** SQL — filters, expression, ordering and grouping
included — through SPEC-177's generalized save flow.

Rendered rather than source, because what the user is looking at is what the file should
reproduce. Saving the bare `SELECT *` would produce a file that reopens as something the user
did not save.

#### Acceptance Criteria:

- [ ] The saved body is the string `renderExplorationSql` produced for the **currently displayed**
      execution — read from the same place the execution used, never re-derived.
- [ ] The save dialog is SPEC-177's, asking for a name and a destination space.
- [ ] Every SPEC-175 rule holds: every save prompts; an unchanged re-save is confirmed once;
      `isLinkedSavedQuery` is the single predicate behind the dialog's promise and the host's
      `overwrite`; choosing another space is a copy; a write failure keeps the dialog open with
      the mapped message inline.
- [ ] `savedQueryName` still lowercases a typed extension while the stem stays case-sensitive
      (SPEC-175's correction) — asserted here too, because this is a second caller.
- [ ] The destination selector is a second instance of the `sharedWorkspaces` choice and gets
      **its own registry row**, as SPEC-175 found it needed one — this one offers a colleague's
      space as a write target.
- [ ] Saving issues no Athena execution.

### FR-002: There is nothing to save until something has run

#### Description:

The control is available exactly when there is a statement to write, and says why when there
is not.

#### Acceptance Criteria:

- [ ] With a description that could not be rendered, the control is unavailable and carries a
      `disabledReason` (SPEC-172's `Button.disabledReason`: `aria-disabled`, so the reason is in
      the tab order rather than hover-only).
- [ ] A suspended description (SPEC-181 FR-006) has run nothing, so there is nothing to save and
      the same refusal applies.
- [ ] **A FAILED execution is refused too, and this is the case with teeth.** A failed apply
      still HAS a rendered statement — the one Athena rejected — while the region has fallen
      back to the LAST GOOD execution's rows, so a save there writes one query under a name
      whose grid is showing another's, and the file fails to open in the workspace FR-005
      promises it opens in. It is worded apart from the other two, because something did run.
- [ ] With no exploration open the control is **absent**, not refused: the results region does
      not mount at all, and the source picker is on screen instead.
- [ ] Every refusal is user text (SPEC-106): none of them quotes an `ExplorationRenderError`,
      whose message names a column for an operator.

### FR-003: The tab remembers what it was saved as

#### Description:

A successful save links the tab to the file it wrote, so the next save behaves as the Query
workspace's does.

#### Acceptance Criteria:

- [ ] After a save, the tab carries the written file's `{spaceId, bucket, key, name}`.
- [ ] Re-saving under the same name into the same space writes through with no second confirm
      (SPEC-175 FR-004); any other key takes the HEAD-and-confirm path.
- [ ] The link survives a session restore, and a stored document that predates it — or carries a
      malformed one — restores the tab without it rather than being discarded (SPEC-182's
      precedent for an added field).
- [ ] The tab's LABEL is not changed by a save. It names the source being explored; the file it
      was written to is a different fact, and the Query workspace's rename-on-save is a
      behaviour of a tab whose whole identity is its buffer.

### FR-004: Nothing but the file is written

#### Acceptance Criteria:

- [ ] No sidecar, manifest or metadata object is written — asserted by counting `PutObject`
      calls on a save: exactly one, over a space whose folder marker already exists.
- [ ] The delivery doc records the rejected sidecar alternative and why.

### FR-005: A file saved here opens in the Query workspace

#### Description:

There is one store, so a file written from the Data Explorer is an ordinary saved query.

#### Acceptance Criteria:

- [ ] A file saved from the Data Explorer appears in the Query workspace's saved-queries panel
      and opens into an editor tab.
- [ ] It is written at the key SPEC-173's `savedQueryKey` produces, with the same content type,
      through the same `writeSavedQuery` — the Data Explorer adds no writer of its own.
- [ ] The Query workspace's panel is untouched by this spec.
- [ ] **The control follows the `query` flag**, and is REMOVED with it rather than refused.
      It is the exact mirror of SPEC-179's *Explore data* on the Query rail: a saved-queries
      capability living on a Data Explorer surface. With `query` off there is no editor to
      open a `.sql` file in and the `saved_queries` folder has already left both the file
      browser and the destination picker (SPEC-173), so a file written there would be a dead
      end the user cannot see — the failure "Create table" is on that list for.

---

## Data Model

No new persisted types in S3. One optional field on the session's tab document:

```ts
export type ExplorationTab = {
  // …
  /** The `.sql` file this tab was last saved to, if any. What a re-save replaces. */
  savedQuery?: SavedQueryLink;
};
```

`SavedQueryLink` is `features/saved-queries/`'s own type — the lower layer both features import.

---

## API / Interface Contract

```ts
/**
 * Hosts the save flow for the active exploration: SPEC-177's dialog, its collision
 * confirm, and the write.
 */
export function SaveExplorationDialog(props: {
  /** The statement that produced the rows on screen; the body written. */
  sql: string;
  spaces: QuerySpace[];
  defaultSpace: QuerySpace | null;
  link: SavedQueryLink | undefined;
  onSaved: (query: SavedQuery) => void;
  onClose: () => void;
}): JSX.Element;
```

---

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── SaveExplorationDialog.tsx      # thin host over SPEC-177's SaveQueryDialog
└── saveExploration.test.tsx
```

---

## Implementation Phases

### Phase 1: The link on the tab

- `ExplorationTab.savedQuery`, its validation and its normalisation in `explorationTabs.ts`,
  and the tabs action that writes it.

### Phase 2: The save

- `SaveExplorationDialog` over SPEC-177's flow, mounted by the workspace; the toolbar control
  and its refusal.
- The registry rows for the surface and its destination selector.

### Phase 3: The assertions

- The rendered-SQL body, the single-`PutObject` count, the no-execution count, the SPEC-175
  rules at this second caller, and the Query-workspace interchange.
