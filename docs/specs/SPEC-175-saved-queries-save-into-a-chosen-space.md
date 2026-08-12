# Spec: Saved Queries — Saving into a Chosen Space

**ID:** SPEC-175
**Status:** Draft
**Last Updated:** 2026-08-11
**Depends On:** SPEC-173 (the store and the folder), SPEC-174 (the space selector and the load surface), SPEC-163 (the gated-surface registry)

## Overview

SPEC-174 let a user load a saved query from any space they belong to, but every save still landed in their own. This spec closes the loop: saving a query starts by choosing where it goes — the user's own space, or any shared space they are an active member of — and writes a `.sql` file there that every member of that space can then find and run. It is the half of the feature that makes a shared space's `saved_queries/` folder ever contain anything.

## Scope

### In Scope

- A destination-space picker on the Save-query dialog, reusing SPEC-174's control.
- **Every** Save prompting for a file name, a linked tab's included — pre-filled, never skipped.
- Writing the editor buffer as `{space}/saved_queries/{name}.sql` in the chosen space.
- Collision handling against the real key in the chosen space — a HEAD, not a scan of a list that is now paginated and may belong to a different space.
- Re-saving a linked tab in place, including a tab linked to a shared space's query.
- Saving a linked tab into a *different* space as a new file, and re-linking the tab to it.
- Write-failure handling, including a shared space the user can no longer write to.
- The no-writable-space refusal, made reachable rather than disabled.
- The Help guide update.

### Out of Scope

- Moving or copying a saved query between spaces as an operation of its own. Choosing a different space on save creates a second file and leaves the first alone — FR-005.
- Renaming a saved query in place. Saving under a new name creates a new file; the old one is deleted from the load list (SPEC-174 FR-005), by the user, deliberately.
- Auto-save, drafts, or versioning of saved queries. A file is written by an explicit, prompted Save and by nothing else (SPEC-173 FR-010) — no keystroke, blur, tab switch, run, close or unload writes anything.
- A "save without prompting" shortcut or a remembered "don't ask again". FR-004 is unconditional.
- Any change to the store, the folder or its protections — all SPEC-173.
- Notifying a space's members that a query was saved there. There is no notification for this feature.

---

## Functional Requirements

### FR-001: The destination-space picker

#### Description:

The Save dialog gains a space control above the name field, listing `useQuerySpaces()` — personal first, then each active shared space. The default is the tab's own space when the tab is linked to a saved query, and otherwise the space remembered by SPEC-174's `useSavedQuerySpace`: one memory of "the space I am working in", shared by save and load, rather than two that can disagree.

A successful save updates that memory, so the next save and the next load both open where the user last was.

#### Acceptance Criteria:

- [ ] The dialog renders a labelled space control listing exactly the spaces `useQuerySpaces()` returns, personal first.
- [ ] For an unlinked tab the control defaults to the space `useSavedQuerySpace` resolves — including its fallback to personal for an unknown or unreachable stored id.
- [ ] For a linked tab the control defaults to that tab's `savedQuery.spaceId`, even when the remembered space is a different one.
- [ ] For a linked tab whose space is no longer in the list (membership revoked), the control falls back to personal and the dialog does not error.
- [ ] A successful save writes the chosen space id to the shared session memory; reopening the dialog on an unlinked tab defaults to it.
- [ ] A cancelled save changes the remembered space not at all.

### FR-002: Writing the file

#### Description:

Submitting writes the active tab's buffer to `{space.rootPrefix}saved_queries/{name}.sql` through `writeSavedQuery`, after ensuring the target space's `saved_queries/` folder marker exists. The name is validated before any request by `validateSavedQueryName`, and its message is rendered inline on the field rather than as a toast.

The `.sql` suffix is appended, or left alone if the user typed it — a user who types `report.sql` gets `report.sql`, not `report.sql.sql`.

#### Acceptance Criteria:

- [ ] Submitting issues `ensureSavedQueriesFolder` for the chosen space and then a `PutObject` on `{rootPrefix}saved_queries/{name}.sql` whose body is the active tab's SQL.
- [ ] Saving into a shared space targets the shared-space bucket and that space's prefix.
- [ ] A name failing `validateSavedQueryName` shows the message on the field, keeps the dialog open, and issues **no** S3 request.
- [ ] `report`, `report.sql` and `report.SQL` all produce exactly one key ending `.sql`, never a doubled suffix.
- [ ] The name field's validation runs on submit; the submit control is **not** disabled in its place (SPEC-167: a refusal must be reachable, or the message is dead code an "it's disabled" test passes over).
- [ ] A failure of `ensureSavedQueriesFolder` does not block the write — the `PutObject` creates the prefix on its own.
- [ ] On success the dialog closes, a toast confirms the save naming the query and the space, and the tab is linked to the new file.
- [ ] The active tab's label becomes the saved query's name **without the `.sql` extension**, via `savedQueryName(key)` — so a user who types `report.sql` gets a tab labelled `report`, matching what SPEC-174's list and its Open would show for the same file.

### FR-003: Collisions are resolved against the key, not against a list

#### Description:

Today the dialog detects a name collision by scanning the in-memory saved-queries array, case-insensitively. That is no longer sound: the list is paginated, so the colliding query may not be loaded, and it may belong to a space the dialog is not saving into. The collision is therefore resolved where the truth is — `writeSavedQuery` HEAD-checks the exact key and returns a `Collision` failure, and the dialog turns that into the existing Replace confirm.

This changes behaviour in one visible way, deliberately: S3 keys are case-sensitive, so `Report` and `report` are now two different saved queries where they used to collide. The alternative — a case-insensitive pre-check — would have to list the entire folder on every save to be correct, and would still be wrong the moment two members save at once.

#### Acceptance Criteria:

- [ ] Saving under a name whose key does not exist writes without any prompt.
- [ ] Saving under a name whose key exists in the chosen space raises the Replace confirm naming the query and the space; cancelling issues no `PutObject` and leaves the dialog open.
- [ ] Confirming Replace re-issues the write with `overwrite: true` and succeeds.
- [ ] The collision check is a HEAD on the exact key — a test asserts the dialog does **not** list the folder to decide.
- [ ] Saving `Report` into a space already holding `report.sql` writes a second file and raises no prompt; a test pins this as the deliberate case-sensitivity change.
- [ ] A collision on a key in a *different* space from the one chosen does not prompt.

### FR-004: Save always prompts for a file name

#### Description:

**Every** Save opens the dialog and asks for a name — a linked tab included. There is no silent write-back path, because a saved query is a file and the moment a user is about to overwrite one they should be told which one, in which space, before it happens rather than after.

For a linked tab the dialog is *pre-filled*, not skipped: the name field carries the linked query's name, selected so a keystroke replaces it, and the space control opens on the tab's own space (FR-001). Submitting it unchanged is the ordinary in-place re-save — and that specific case does **not** raise the Replace confirm on top of the prompt, because the file being overwritten is the one the user is looking at the name of. Changing either the name or the space makes it a different key and FR-003 applies.

This is a change from SPEC-043, where a linked tab's Save wrote straight through with no dialog at all.

#### Acceptance Criteria:

- [ ] Save on an **unlinked** tab opens the dialog with an empty name field focused.
- [ ] Save on a **linked** tab opens the dialog with the linked query's name pre-filled and selected, and the space control on that tab's space.
- [ ] No path writes without the dialog having been submitted — a test asserts that invoking Save issues no `PutObject` until submit, for both linked and unlinked tabs.
- [ ] Submitting a linked tab's pre-filled name and space unchanged writes with `overwrite: true`, raises **no** Replace confirm, and issues exactly one `PutObject`.
- [ ] The tab stays linked to the same key; its label is unchanged.
- [ ] A linked tab whose underlying file was deleted (SPEC-174 FR-005) re-creates it on submit, and the tab is linked to it again.
- [ ] A linked tab submitted under a **different** name follows FR-003 — a new key, with a Replace confirm only if that key exists.
- [ ] The keyboard path is unchanged: Enter submits from the name field only (`submitOnEnterRef`), never from the space control.

### FR-005: Saving into a different space is a new file

#### Description:

Choosing a space other than the tab's own is *Save as* into that space: it writes a new file there, leaves the original untouched, and re-links the tab to the new file. Nothing is moved and nothing is deleted — a saved query a colleague may already be running does not disappear because someone copied it elsewhere.

#### Acceptance Criteria:

- [ ] A linked tab saved into a different space issues one `PutObject` into the new space and **no** `DeleteObject` anywhere.
- [ ] The original file is still present in its own space afterwards.
- [ ] The tab's link points at the new space's key after the save.
- [ ] If the new space already holds that name, the Replace confirm appears for **that** space's file, and confirming replaces it and leaves the original space's file untouched.
- [ ] The toast names the space the query was saved into.

### FR-006: Write failures

#### Description:

A write can fail for reasons the dialog must distinguish from a collision — most realistically a shared space whose membership was revoked mid-session, which returns `AccessDenied`. The dialog stays open with the buffer and the chosen space intact so the user can pick another destination, and the message is the mapped one.

#### Acceptance Criteria:

- [ ] A failed `PutObject` keeps the dialog open, keeps the typed name and the chosen space, and renders the mapped message (`toUserMessage`) inline — never raw AWS text (SPEC-106).
- [ ] An `AccessDenied` write into a shared space renders a message about the space, and the space control stays interactive so another destination can be chosen.
- [ ] The tab's link is unchanged after a failed save.
- [ ] No toast claims success on a failed write.
- [ ] The submit control is locked while a write is in flight, and unlocks on both outcomes.

### FR-007: The no-writable-space refusal, and it is reachable

#### Description:

If `useQuerySpaces()` returns nothing — the user-space bucket is unconfigured — Save opens the dialog and the dialog explains why it cannot save, rather than the toolbar rendering a disabled button. SPEC-167 records exactly this failure in the send dialog: a `submitDisabled` made an inline refusal banner dead code, and the test asserting "the button is disabled" passed straight over the acceptance criterion.

#### Acceptance Criteria:

- [ ] With no spaces available, the Save control still opens the dialog.
- [ ] The dialog renders an explanatory banner and no space control; submit is unavailable **because there is nothing to submit**, and the banner is present in the DOM and asserted by a test.
- [ ] No S3 request is issued in that state.
- [ ] A test renders this state and asserts the banner text, not the disabled attribute.

### FR-008: Help and the flag

#### Description:

The `save-query` guide is rewritten for the shipped flow: choose a space, name the query, replace-if-it-exists, and where the file lands. No new `GATED_SURFACES` row is needed — every surface here lives inside `/query`, which the registry gates as a route, and the guide lives in the `query` help section, which it gates whole. That is verified rather than assumed.

#### Acceptance Criteria:

- [ ] The `save-query` guide describes picking a space, the `.sql` file's location, and that a shared space's saved queries are visible to every member — matching the shipped UI exactly (SPEC-074 FR-005).
- [ ] With `query` off, `/help` shows the guide not at all, and `/query` renders the unavailable page — each asserted after the page settles, never inside `waitFor` (SPEC-163).
- [ ] `GATED_SURFACES` gains no duplicate row.
- [ ] `vitest-axe` reports no violations for the dialog with the space control, for its Replace confirm, and for its no-space banner state — each against the **driven container**, not a fresh render.
- [ ] The space control has a visible, programmatically associated label, and Enter submits from the name field only (`submitOnEnterRef` — SPEC-155: implicit submission is suppressed and one field submits).

---

## Data Model

No new persisted shape. The dialog's result becomes space-aware:

```ts
// apps/portal/src/features/query/SaveQueryDialog.tsx

/** What the dialog reports on submit. `overwrite` is set only after the Replace confirm. */
export type SaveQueryRequest = {
  space: QuerySpace;
  name: string;
  overwrite: boolean;
};
```

---

## API / Interface Contract

```ts
// apps/portal/src/features/query/SaveQueryDialog.tsx — props
type Props = {
  /** '' for a new save; the linked query's name on re-save. */
  initialName: string;
  spaces: QuerySpace[];
  /** The space the control opens on — the tab's own, else the remembered one. */
  initialSpace: QuerySpace | null;
  /** The active tab's link, if any; its key is re-saved in place without a prompt. */
  linked?: SavedQueryLink;
  /** Inline error to render on the field (validation or a mapped write failure). */
  error?: string | null;
  busy: boolean;
  onSave: (request: SaveQueryRequest) => void;
  onCancel: () => void;
};

// apps/portal/src/features/query/useSaveQuery.ts
export type UseSaveQueryResult = {
  open: boolean;
  openDialog: () => void;
  closeDialog: () => void;
  busy: boolean;
  error: string | null;
  /** Set when the write returned `Collision`; drives the Replace confirm. */
  collision: {space: QuerySpace; name: string} | null;
  save: (request: SaveQueryRequest) => void;
  confirmReplace: () => void;
  cancelReplace: () => void;
};
/** Owns the whole save path: validation, the write, the collision round-trip, the link and the toast. */
export function useSaveQuery(params: {
  username: string;
  spaces: QuerySpace[];
  activeTab: QueryTab;
  onLinked: (link: SavedQueryLink) => void;
  toast: ToastApi;
}): UseSaveQueryResult;
```

## Environment Variables

None.

## File & Folder Structure

```
apps/portal/src/features/query/
├── SaveQueryDialog.tsx           # + space control, inline error, no-space banner
├── SaveQueryDialog.test.tsx
├── useSaveQuery.ts               # the save path extracted from QueryWorkspace
├── useSaveQuery.test.ts
├── SavedQuerySpaceSelect.tsx     # reused from SPEC-174, unchanged
├── QueryWorkspace.tsx            # wires useSaveQuery; drops the in-memory collision scan
├── QueryDialogs.tsx              # the Replace confirm moves onto the collision result
└── saveQuery.a11y.test.tsx

apps/portal/src/features/help/helpContent.ts   # rewritten save-query guide
```

## Implementation Phases

### Phase 1: The picker and the write

- `SaveQueryDialog` gains the space control, the inline error and the no-space banner.
- `useSaveQuery`: validation, `ensureSavedQueriesFolder`, `writeSavedQuery`, the toast, the tab link and label.
- The shared space memory updated on success.

### Phase 2: Collisions and re-save

- The `Collision` round-trip replacing the in-memory name scan; the Replace confirm driven by it.
- The always-prompt rule: the pre-filled dialog for a linked tab, the no-double-confirm case, and the "no write before submit" assertions.
- Save-as into another space; the deleted-original re-create.
- The case-sensitivity pin.

### Phase 3: Failures, help and a11y

- Write failures, including revoked shared-space membership, and the locked-while-busy submit.
- The rewritten `save-query` guide.
- The gating assertions and the axe passes against driven containers.
