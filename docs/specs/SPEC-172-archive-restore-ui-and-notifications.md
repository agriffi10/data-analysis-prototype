# Spec: Archive & Restore — File-Browser UI, the Receipt Surface & Notifications

**ID:** SPEC-172
**Status:** Completed
**Last Updated:** 2026-08-10
**Depends On:** SPEC-168 → SPEC-171 (the plane), SPEC-155 (`FormDialog`, the Escape registry), SPEC-058→061 (notifications), SPEC-074 (Help & guides), SPEC-095/099 (responsive)

## Overview

Four specs of privileged machinery and no way to reach it. This spec puts **Archive** on the
selection toolbar beside Copy, Move and Delete; puts **Restore Archived Data** on the files toolbar;
makes the `archive/` folder behave like the read-only thing IAM already says it is; and delivers
every outcome to the notifications inbox — including the two refusals a user is most likely to hit
and the one that arrives hours later.

The archive dialog carries more weight than a normal confirm. Archiving is the only action in this
portal that **deletes the user's data and cannot be undone in the same sitting** — getting it back
takes hours and is billed. So the dialog says what will be deleted, how much of it there is, and how
long a restore takes, and it is the one place in the app where the confirm is not the default focus.

The other half of the spec is smaller but is the reason SPEC-168 deferred it. IAM now denies writes
under `archive/`, and the browser has no counterpart. Today nothing gates the Upload button or **New
folder** on the current prefix at all, so a user who navigates into `archive/` and uploads gets a bare
`AccessDenied` for a rule this application wrote. That mirror is built here.

## Scope

### In Scope

- **Archive** as a selection-toolbar action, plus the per-item entry in both details panels.
- The **archive confirm dialog**: what will be deleted, the size and count, the restore-takes-hours
  warning, and the non-default confirm.
- The **Restore Archived Data** toolbar button and its `FormDialog` taking a pasted archive id.
- The **`archive/` read-only mirror**: locked as a paste destination, undeletable, and — new — Upload
  and New folder disabled while inside it, with an explanation rather than a denial.
- The **enqueue services and hooks** for both modes, on the shared FIFO skeleton.
- The **notification producer** for every terminal outcome of both planes, with deep links.
- Help & guides content, responsive behaviour and axe coverage.

### Out of Scope

- In-browser preview of the receipt. The receipt is a **plain text file the user downloads and reads
  themselves** — the intended surface, not a workaround. It lists like any other file and downloads
  through the existing path; the project's no-preview rule is untouched. The archive ids are readable
  without opening anything, because the folder names *are* the ids.
- An archive browser, an archive index, or a picker that lists previous archives. The user finds the
  id from the `archive/` folder in their own space — the folder names **are** the ids. A cross-space
  archive index is a directory-shaped disclosure of the kind SPEC-158 declined.
- Restoring to a chosen location, or restoring part of an archive — SPEC-170 Out of Scope.
- Progress reporting during a restore. The notification says it started and a second one says it
  finished; there is no live progress surface, matching every other control plane.
- A separate feature flag. Archive is a **Files sub-surface**, not one of the four primary features
  SPEC-162 names, so it inherits the Files flag through SPEC-163's registry rather than gaining its
  own — the registry entry is an acceptance criterion below if 163 has landed.

---

## Functional Requirements

### FR-001: The Archive entry point

#### Description:

There is no context menu in the file browser — rows carry an always-visible **Details** button and
nothing else. A per-item action therefore has exactly two homes, and archiving needs both.

#### Acceptance Criteria:

- [ ] `SelectionToolbar` gains an **Archive** action beside Copy / Move / Delete, rendered under the
      same `canModify && hasContent` condition and labelled from tablet up, icon-only on mobile, like
      its siblings.
- [ ] Unlike the data-quality action, Archive takes the **whole selection**, not the first selected
      item — archiving a set is the normal case.
- [ ] `MetadataPanel` (file) and `FolderDetailsPanel` (folder) each gain an Archive action, so a
      single item can be archived without first selecting it.
- [ ] The action is absent for a read-only space and absent inside `archive/` itself.
- [ ] Selecting a protected root — `athenaresults/`, `user_settings/`, `_data-quality-reports/`,
      `shared_tables/`, `archive/` — disables Archive with an explanation. This mirrors SPEC-168
      FR-005's server-side refusal list; the two lists are asserted equal by a test, because a
      divergence shows up as a request the browser sends and the plane refuses.
- [ ] If SPEC-163 has landed, both entry points are registered in its surface registry and covered by
      its walking test — the cross-feature entry point being missed is exactly what that registry
      exists to catch.

### FR-002: The archive confirm dialog

#### Acceptance Criteria:

- [ ] The dialog names what will be archived: the item count for a selection, or the folder path for
      a single folder, using the same wording the delete confirm uses for consistency.
- [ ] It states plainly that the data **will be removed from this space**, and that restoring takes
      **several hours**. Both facts are user-visible consequences of decisions recorded in SPEC-168
      FR-002 and SPEC-171 FR-001; neither can be inferred from the button label.
- [ ] The confirm control is **not** the autofocused element and Enter does not submit the dialog.
      `FormDialog` suppresses implicit submission and submits only from `submitOnEnterRef` (SPEC-155);
      this dialog sets no such ref. The reasoning — a keystroke should not delete a folder — is
      recorded in the component.
- [ ] Escape cancels through the depth-ordered registry (SPEC-155), and the dialog is busy-locked
      while the enqueue is in flight so Escape cannot close a half-submitted request.
- [ ] On success the dialog closes, the selection clears, a toast confirms the request was **started**
      — never that it completed — and the listing is invalidated through
      `features/file-browser/invalidateListing`.
- [ ] On failure the dialog stays open and renders `submitError` through `toUserMessage`; raw AWS
      text never reaches it (SPEC-106).

### FR-003: Restore Archived Data

#### Acceptance Criteria:

- [ ] A **Restore Archived Data** button sits in the file browser's primary toolbar, gated on
      `writable` like its neighbours, and mount-gated into the mobile action bar rather than
      CSS-hidden (SPEC-099 FR-005).
- [ ] It opens a `FormDialog` with a single text input for the archive id, an explanation of where to
      find one (the `archive/` folder), and the confirm as the submit action.
- [ ] The input is **validated client-side as a UUID** before enqueue, with an inline error naming
      what a valid id looks like. The server validates it again before building any key (SPEC-170
      FR-002) — the client check exists to save the user an hours-late notification, not to be the
      boundary.
- [ ] The dialog states that a restore takes several hours and that the user will be notified.
- [ ] Enter submits from the id field — this is the single-field case `submitOnEnterRef` is for, and
      the opposite call from FR-002 for the opposite reason.
- [ ] The dialog restores into the **space the user is currently browsing**, and says which one. The
      space comes from the route, matching SPEC-113's rule and SPEC-170 FR-001.
- [ ] On success the dialog closes with a toast saying the restore has started.

### FR-004: The `archive/` folder is read-only in the UI

#### Description:

IAM denies writes under `archive/` (SPEC-168 FR-006). Without a UI counterpart every attempt produces
a bare `AccessDenied` for a rule this app authored — the situation `isUndeletableRootFolder` exists to
prevent for `athenaresults/`.

#### Acceptance Criteria:

- [ ] `archive` is added to `PICKER_LOCKED_FOLDERS` (never a paste destination) and to
      `UNDELETABLE_ROOT_FOLDERS` (never destroyed), matching at the space root only via the existing
      `isRootFolderNamed` helper, so a nested `alice/backups/archive/` stays an ordinary folder.
- [ ] `archive` is **not** added to `HIDDEN_BROWSER_FOLDERS`. The folder must be visible: it is where
      the user reads their archive ids and downloads receipts.
- [ ] `protectedFolders.ts`'s header comment — which argues the lists are deliberately not unioned —
      is honoured: each addition is justified against that list's own question, and the two lists
      `archive` does *not* join are left alone.
- [ ] **New:** Upload and New folder are disabled while the current prefix is at or inside the
      space's `archive/` root, with a short explanation rather than a disabled control with no
      reason. No such prefix-based write gate exists today; this is the first, and it is built as a
      reusable predicate (`isWriteLockedPrefix`) rather than a special case, because the next
      read-only prefix will want it.
- [ ] Rename and Move are likewise unavailable for items inside `archive/`.
- [ ] Download and Details remain fully available for receipts.
- [ ] A test asserts the UI gate and the IAM Deny agree on the same prefix: the browser must not offer
      a write the policy refuses, and must not refuse one it permits.

### FR-005: The enqueue services and hooks

#### Acceptance Criteria:

- [ ] `features/archive/archive.service.ts` exposes `enqueueArchive(req)` and `enqueueRestore(req)`,
      both built on `lib/enqueueFifo.ts`'s `enqueueFifoRequest` — reading `VITE_ARCHIVE_QUEUE_URL` at
      **call time** (a module-level const breaks `vi.stubEnv`), fetching the ID token, retrying
      through `withCredentialRetry`, and returning `ServiceResult` without throwing.
- [ ] `MessageGroupId` is computed as each spec requires — the SHA-256 of the space root for archive
      (SPEC-168 FR-004), of the archive root for restore (SPEC-170 FR-001) — and a test asserts the
      two differ, because using one for both would serialize unrelated work.
      > **Note on SPEC-170 FR-001:** that AC writes the restore's canonical string as
      > `{archiveBucket}/{archiveRoot}`. The browser cannot produce it — SPEC-168 keeps the archive
      > bucket's name out of the SPA entirely and a test enforces the absence — and the bucket adds
      > no discrimination, since it is one constant across every restore. The archive ROOT alone is
      > used, and its `personal/`/`shared/` segment already makes it unique. `decisions/` carries
      > the reasoning; `docs/testing/e2e.md` was corrected to match.
- [ ] The body carries the ID token and **never a username**; the actor is derived server-side.
- [ ] Success means *enqueued*, not done — the hooks expose a pending state and never a completion.
- [ ] The feature lives at `src/features/archive/` with the standard barrel, and imports nothing from
      other features; the `components/` may-not-import-`features/` rule (SPEC-155) is not weakened to
      accommodate it.

### FR-006: The notification producer

#### Acceptance Criteria:

- [ ] Every terminal outcome of both modes produces exactly one notification: `archived`,
      `archive_failed`, `restore_started`, `restored`, `restore_incomplete`, `restore_timed_out`,
      `archive_not_found`, `archive_incomplete`, `destination_occupied`.
- [ ] `restore_started` exists because the user is about to wait hours. It states the expected
      duration and that a second notification will follow — it is the only "started" notification in
      the app, and the reason is recorded.
- [ ] `archived` names the object count, the total size and **the archive id**, since that id is what
      a future restore needs.
- [ ] `destination_occupied` reproduces SPEC-170 FR-005's sampled key list and its "there may be
      more" caveat verbatim through `arcommon.messages` — the browser renders the message, it does
      not compose one.
- [ ] `restore_incomplete` carries SPEC-171 FR-004's three facts, including that re-requesting will
      report a conflict against what already landed.
- [ ] The optional `link` points at the file browser at the relevant folder — the `archive/` folder
      for `archived`, the restored path for `restored` — and passes `isSafeInAppPath` (SPEC-061). A
      link that cannot be built is omitted, never guessed.
      > **Amended in build:** `restored` links to the **space root**, not "the restored path". A
      > restore puts every object back where it came from, which for any selection of more than one
      > folder is several places at once — there is no single restored path, and picking the first
      > would send the user to a folder holding part of what they asked for. Reasoning in
      > `decisions/`; the `archived` link is unchanged.
- [ ] One dedup token **per outcome**, not per verb (the data-quality rule).
- [ ] Every message is a literal, `echo=` is not used, and no message carries a file's contents
      (SPEC-127's field rule).

### FR-007: Help, responsive and accessibility

#### Acceptance Criteria:

- [ ] `helpContent.ts` gains a guide covering: what archiving does, that it removes data from the
      space, that restoring takes hours, where to find an archive id, how to restore, and what to do
      when a restore is refused because the destination is occupied. It documents only what is
      shipped and wired end to end (SPEC-074 FR-005).
- [ ] Both dialogs reflow on **one** tree with only `tablet:` / `desktop:` breakpoints; no
      `*Mobile`/`*Desktop` twin is introduced (SPEC-095).
- [ ] `useIsMobile` is used for mount-gating only, never for styling.
- [ ] Both dialogs have `vitest-axe` coverage asserted **against the driven container** — the open
      dialog with focus in it, not a re-render of the closed state.
- [ ] A journey test performs the whole archive flow — select, open, confirm, enqueue — and the whole
      restore flow, against a mocked service boundary only (SPEC-154's discipline: render real hooks
      and children, mock the AWS boundary).

---

## API / Interface Contract

```ts
// src/features/archive/archive.service.ts
// Amended in build to ServiceResult<void>: the caller MINTS the request id (it is the FIFO
// deduplication id, so it must be per-submit), which means handing it back is echoing an
// argument. Every other plane's enqueue has the same shape.
enqueueArchive(req: ArchiveRequest): Promise<ServiceResult<void>>;
enqueueRestore(req: RestoreRequest): Promise<ServiceResult<void>>;
```

```ts
// src/types/archive.types.ts
export type ArchiveSpace = { kind: 'personal' | 'shared'; name: string };

export type ArchiveRequest = {
  requestId: string;                       // UUID v4; becomes the archive's permanent id
  space: ArchiveSpace;
  items: { kind: 'file' | 'folder'; key: string }[];
};

export type RestoreRequest = {
  requestId: string;                       // this run
  space: ArchiveSpace;                     // from the route, not from the archive
  archiveId: string;                       // pasted by the user; UUID-validated before enqueue
};
```

## Environment Variables

Add to `apps/portal/.env.example`:
```
VITE_ARCHIVE_QUEUE_URL=https://sqs.<region>.amazonaws.com/<account>/<project>-prod-archive-requests.fifo
```

## File & Folder Structure

```
src/
├── features/
│   └── archive/
│       ├── index.ts
│       ├── ArchiveButton.tsx            (+ .test.tsx)
│       ├── ArchiveDialog.tsx            (+ .test.tsx)
│       ├── RestoreArchiveButton.tsx     (+ .test.tsx)
│       ├── RestoreArchiveDialog.tsx     (+ .test.tsx)
│       ├── useArchive.ts                (+ .test.ts)
│       └── archive.service.ts           (+ .test.ts)
├── features/file-browser/
│   ├── protectedFolders.ts              (archive added to two of the four lists)
│   └── writeLockedPrefix.ts             (+ .test.ts — the new reusable predicate)
├── types/
│   └── archive.types.ts
```

## Implementation Phases

### Phase 1: Services, types and the enqueue surface

- `archive.types.ts`, `archive.service.ts` on `enqueueFifoRequest`, the two group-id derivations, the
  hook, and the env var through `.env.example` / `deploy-app.yml` / the repo variable.

### Phase 2: The archive flow

- `ArchiveButton` in `SelectionToolbar` and both details panels, `ArchiveDialog` with the
  non-default confirm, the protected-root disable, and the registry entry if SPEC-163 has landed.

### Phase 3: The restore flow and the read-only mirror

- `RestoreArchiveButton` + dialog with client-side UUID validation; `protectedFolders.ts` additions;
  `isWriteLockedPrefix` and the Upload / New folder / Rename / Move gates.

### Phase 4: Notifications

- The producer for all nine outcomes, the links through `isSafeInAppPath`, the per-outcome dedup
  tokens.

### Phase 5: Verification

- Journey tests for both flows, axe against the driven containers, and the test asserting the
  browser's protected-root list equals the plane's.
- **Live check (owed), Safari, at 400px and desktop:** archive a folder from a personal space through
  the UI and confirm the toast, the notification, the `archive/{uuid}/` folder appearing, and the
  receipt downloading and reading correctly. Navigate into `archive/` and confirm Upload, New folder,
  Rename, Move and Delete are all unavailable **with an explanation** and that no `AccessDenied`
  reaches the user. Paste the id into Restore Archived Data, confirm the `restore_started`
  notification, and confirm the terminal notification arrives hours later with a working link. Then
  re-create one restored file and submit again to see `destination_occupied` name it in the
  notification. Repeat the archive and restore once in a **shared space** as a non-owner member,
  which is the membership rule SPEC-168 FR-005 and SPEC-170 FR-002 both specify and which no unit
  test exercises against real Cognito tags.

### Phase 6: Completion ritual

- Delivery doc, INDEX status, `apps/portal/info/component-inventory/file-browser-feature.md` rows for the new
  components and `isWriteLockedPrefix`, a new `apps/portal/info/component-inventory/archive-feature.md` with a router
  row (a whole new area appeared), a `decisions/` entry (the non-default confirm, the folder-names-
  are-ids surface instead of an archive index, the first prefix-based write gate), one Key Decisions
  line, and the **Help & guides** update. Prune CLAUDE.md's Current work of the whole arc.
