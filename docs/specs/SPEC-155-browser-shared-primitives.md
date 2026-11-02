---
type: Spec
id: SPEC-155
title: "Browser Shared Primitives & Component Decomposition"
description: "Extracts shared browser primitives (S3 JSON reader, dialog footer, focus-on-mount, feedback stanza, pager) and splits QueryWorkspace and FileBrowser into smaller units for developers, with no user-visible change."
spec_status: Completed
depends_on: [SPEC-150, SPEC-154, SPEC-106, SPEC-095]
arc: audit-remediation
arc_order: 6
---

**Dependency notes:** SPEC-150 (its FR-004/FR-005/FR-009 change the same `lib/` files this spec refactors — land 150 first), SPEC-154 (the journey tests that make the decomposition in Phase 5 safe), SPEC-106 (`toUserMessage`, whose call-site ergonomics FR-008 addresses), SPEC-095 (the responsive rules any extracted component must keep)
> **Reference:** from the 2026-08-05 codebase audit. This is the reuse and structure work, deliberately separated from behaviour change so a reviewer can read a diff and know nothing user-visible moved.
>
> **The prerequisite is not negotiable.** Phase 5 decomposes two components of 1772 and 1300 lines. That is only safe on top of SPEC-154's journey tests — today `QueryWorkspace` has genuinely good coverage but `FileBrowser`'s upload and collision paths do not, and those are exactly the paths a decomposition would break silently. **If SPEC-154 has not landed, stop before Phase 5** and ship Phases 1–4, which stand alone.
>
> **Every extraction here is behaviour-preserving.** The test for this spec is that the existing suite passes unchanged, not that new tests were written to match new behaviour. Where a duplicate pair differs, the difference is a finding: FR-001 in particular must decide, per site, which of the two variants is correct rather than silently picking one — `useSavedQueries` seeds its cache without invalidating while `useQueryHistory` invalidates, and one of those is a latent bug.
>
> **The audit found compliance genuinely strong**, so this spec should not read as a rebuke: zero `any`, no service throws, no `error.message` rendered, default exports confined to `routes/`, all AWS clients in `src/lib/`, all 21 dialogs composing `Modal`, one clipboard implementation, and correct ListObjectsV2 pagination everywhere. What follows is duplication that accreted, not rules that were broken.

## Overview

The portal's shared layer is good where it exists and thin where it does not. `Modal`, `ConfirmDialog`, `Banner`, `Pager`, `CopyButton`, `serviceResult`, `errorMessages`, `credentialRetry` and `enqueueFifo` are all well-designed and used consistently. The gaps are the places where a second, third or sixth feature needed the same thing and copied it instead.

Six services read a JSON document from S3 with the same twelve lines — credential retry, `GetObjectCommand`, `transformToString`, parse, treat not-found as empty, wrap the error — differing only in the parse function and the failure wording. Eleven dialogs re-author the same footer layout as a literal class string, nine repeat the same focus-on-mount effect, and two have already drifted into a variant. Three operations in the file browser render the same four-block feedback stanza. Two pages implement the same clamped client-side pager, identical down to the screen-reader span, with a comment in one that says it copies the other.

Two components have grown past the point where a reader can hold them: `QueryWorkspace.tsx` at 1772 lines with 25 `useState` and 8 `useRef`, and `FileBrowser.tsx` at 1300. Their seams are not vague — the whole batch-run state machine is one identifiable ~450-line unit, and two 40-line handlers in `QueryWorkspace` are the same function written twice.

The outcome is a smaller surface to change when a rule changes: one place to fix a 404-equivalent error name, one place to change dialog chrome, one bulk-operation feedback component instead of three copies.

---

## Scope

### In Scope

- **`lib/s3Json.ts`** — one read/write pair for the six `user_settings/`-style JSON documents.
- **`components/FormDialog.tsx`** — the body/footer chrome and focus-on-mount the 11 dialogs re-author.
- **One `BulkOperationState`** and one feedback component for delete/move/copy.
- **A shared page shell** — client pager, segmented filter, refresh button, `Banner` retry.
- **Moving `features/query/`'s shared exports** to where they belong.
- **Smaller primitive gaps**: S3 URL parsing, breadcrumbs, bucket helpers, per-file download, formatters, the Escape-key stack, `AbortSignal` threading, env validation, the `__none__` sentinel, icons.
- **Decomposing `QueryWorkspace.tsx` and `FileBrowser.tsx`** along named seams.
- **Two one-line correctness carries** that live in these files: the unescaped download filename, and the ungated production console logs.

### Out of Scope

- **Any user-visible behaviour change.** If a screen looks or behaves differently, the change is wrong. The one deliberate exception is the `formatBytes` unit-ceiling decision in FR-007, which is called out as a decision precisely because it *is* visible.
- **Python layer consolidation** — SPEC-156.
- **New features, new routes, new services.**
- **Rewriting `Modal`, `ConfirmDialog`, `Banner` or `Pager`.** `FormDialog` composes `Modal`; it does not replace it.
- **Changing the responsive strategy.** SPEC-095's one-tree rule holds; an extraction that produces a `*Mobile`/`*Desktop` twin is wrong.
- **Adopting a state library.** Context + `useReducer` and TanStack Query remain the model.
- **Type-level ratchets** (`noUncheckedIndexedAccess`) — its own decision.

---

## Functional Requirements

### FR-001: One S3 JSON document reader and writer

#### Description

`savedQueries.service.ts:35`, `queryHistory.service.ts:41`, `notifications.service.ts:72`, `sharedSpaces.service.ts:126`, `dataQualityReport.service.ts:57` and `dataQualityRuns.service.ts:48` share one skeleton. (A **seventh** — `userDirectory.service.ts` — shipped in SPEC-147 after this audit named the first six, and was converted with them.) `writeStore` (`savedQueries:50`) and `writeHistory` (`queryHistory:57`) are byte-equivalent apart from key and message.

#### Acceptance Criteria

- [x] `lib/s3Json.ts` exports `readJsonDocument<T>({bucket, key, parse, onMissing, fallbackMessage})` and `writeJsonDocument({bucket, key, value, fallbackMessage})`, both returning `ServiceResult` and neither throwing. (The option is `onMissing`, not `whenMissing` as first drafted — it matches the repo's `on*` callback convention, including this spec's own `onWriteSuccess`.)
- [x] All **seven** readers and both writers are expressed through it; each service retains only its key builder, its `parse`/validity predicate and its wording.
- [ ] Not-found still yields the empty document, not an error, for every reader that does so today.
- [ ] The **cache-reconcile asymmetry is resolved explicitly**: `useQueryHistory` invalidates after seeding while `useSavedQueries` does not (leaving the cache unreconciled against S3 after a read-modify-write). Decide which is correct, apply it to both, and record the decision. Do not preserve the difference by accident.
- [ ] Every existing service test passes **unchanged**. New tests cover `s3Json` directly.
- [ ] `lib/enqueueFifo.ts` is the shape precedent; `s3Json` follows its API conventions.

### FR-002: One form-dialog chrome

#### Description

The footer class string `flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4` appears verbatim in 11 dialogs, the body wrapper `px-5 pb-4 pt-5` in 13, and `useEffect(() => {inputRef.current?.focus()}, [])` in 9. `CopyDialog` and `DestinationPicker` already carry a drifted `-mx-5 -mb-4 mt-4` variant.

#### Acceptance Criteria

- [ ] `components/FormDialog.tsx` composes `Modal` and owns title, body wrapper, footer layout, the Cancel/primary pair, `busy`/`busyLabel`/`submitDisabled`, Enter-to-submit and focus-on-mount via an `autoFocusRef`.
- [ ] Its prop API mirrors `ConfirmDialog`'s conventions so the two read as siblings.
- [ ] At least the nine name-prompt dialogs are migrated, each reduced to its validation rule plus its input.
- [ ] The two drifted variants are reconciled to the shared chrome or keep their difference with a one-line reason.
- [ ] Focus behaviour, focus trapping and Escape handling are unchanged — asserted by the existing dialog tests passing unchanged, plus `vitest-axe` on `FormDialog` itself.
- [ ] No dialog's rendered text or control order changes.

### FR-003: One bulk-operation feedback surface

#### Description

`FileBrowser.tsx:819-938` renders the same four-block stanza three times — dismissible error `Banner`, `OperationSummaryBanner` over mapped errors, a `role="status"` progress line, and a `BatchOverwritePrompt`. `useMove.ts:35-49` and `useCopy.ts:40-53` already expose near-identical surfaces.

#### Acceptance Criteria

- [ ] One `BulkOperationState` type covers delete, move and copy. The real differences are `errors[].key` vs `errors[].item` and `movedCount`/`copiedCount`/`deletedCount` — normalise the error field and use a single `count`.
- [ ] `useDelete`, `useMove` and `useCopy` return that shape.
- [ ] One `<OperationFeedback op={…} pastVerb=… failVerb=… />` renders all three cases; the ~120 lines of JSX reduce accordingly.
- [ ] Every message a user currently sees is preserved verbatim, including partial-failure counts and per-item messages.
- [ ] `useCopy`'s `username!` non-null assertions (`:118,131,214,227`) are replaced with the explicit narrow-and-error pattern `useMove.ts:84-87` already uses.
- [ ] Existing `FileBrowser` and hook tests pass unchanged.

### FR-004: One page shell for the list pages

#### Description

`NotificationsPage.tsx:41-69` and `DataQualityPage.tsx:64-89` implement identical clamped pager arithmetic, an identical `<Pager>` invocation **down to the `sr-only` span**, identical `FilterTabs`, identical refresh `IconButton` + spinner, and an identical "Try again" link-button. `DataQualityPage.tsx:70` documents the copy.

#### Acceptance Criteria

- [ ] `hooks/useClientPager.ts` returns `{pageItems, pagerProps, resetToFirst}` and both pages use it.
- [ ] `components/SegmentedFilter.tsx` is generic over the option list and replaces both `FilterTabs`, preserving `role="group"` and `aria-pressed`.
- [ ] `components/RefreshIconButton.tsx` replaces both refresh buttons, with **one** spinner glyph.
- [ ] `Banner` gains a `retry` prop replacing both hand-rolled "Try again" buttons.
- [ ] Both pages' rendered output, keyboard behaviour and axe results are unchanged.

### FR-005: `features/query/` stops being a shared layer

#### Description

Arrows point the wrong way: `components/ToastProvider.tsx:2` and `components/Sidebar.tsx:3` import from `features/query/`; five sibling features import `CATALOG_IDENTIFIER_RE`, `Connection`, `isConnectionUsable` and `useConnections` from it.

#### Acceptance Criteria

- [ ] `features/query/Toast.tsx` moves to `components/Toast.tsx`; `components/` no longer imports from any feature.
- [ ] `CATALOG_IDENTIFIER_RE`/`CATALOG_IDENTIFIER_RULE` move to `lib/catalogIdentifier.ts`.
- [ ] The connections domain (`Connection`, `isConnectionUsable`, `useConnections`, `connectionStatus`) moves to `features/connections/`.
- [ ] No `components/**` file imports from `features/**` afterwards. Asserted by a lint rule or a test, not by inspection.
- [ ] Pure moves plus import updates — no logic changes.
- [ ] `component-inventory` rows follow the files to their new area.

### FR-006: The smaller primitive gaps

#### Acceptance Criteria

- [ ] **One `lib/s3Url.ts`** `parseS3Url(url): {bucket, key} | null`. `query.service.ts:265`, `tableRefresh.location.ts:17` and the inline copy at `QueryWorkspace.tsx:903` all use it; `parseTableLocation` becomes it plus a trailing-slash normaliser.
- [ ] **Breadcrumbs and parent-of** move into `fileBrowser.paths.ts` as one clamped implementation; `DestinationPicker`'s `parentOf` is deleted in favour of the existing `parentPrefix`. The two clamps must agree — a test asserts the picker cannot climb above where the browser can.
- [ ] **`lib/userSpace.ts` gains `sharedSpaceBucket()` and `spaceBuckets()`**; both duplicate definitions and the three inline env reads are removed, including the local shadow at `QueryWorkspace.tsx:157`.
- [ ] **`useFileDownload`** replaces the two per-file download implementations and their identical error literal (`FileBrowser.tsx:606` == `MetadataPanel.tsx:86`).
- [ ] **`lib/format.ts`** holds `formatRelativeTime`, `formatCount`, `formatDurationMs` and one absolute-date formatter; the three date formatters with two identical option sets collapse. Domain-specific helpers stay where they are.
- [ ] **`useEscapeKey` maintains a listener stack** and dispatches only to the innermost enabled handler, so nested dialogs are correct by construction. The two `closeOnEscape` opt-outs may then be removed, and a test covers a nested dialog closing only its top layer — the case `Modal`'s `dismissible` currently cannot express without also disabling backdrop dismiss.
- [ ] **`AbortSignal` is threaded** into the listing and polling paths via `send({abortSignal})`, and `runStatementToCompletion` checks it each loop — it currently polls ~36 s after navigation. `uploadFile:875`'s `abort` listener is removed on completion.

  > **Superseded 2026-08-29 by SPEC-198 FR-001 AC8, for the LISTING half only.** `send({abortSignal})`
  > aborted the request on the wire: navigating out of a folder mid-listing stopped the S3 call. The
  > listing now goes through the API, and a Lambda invocation cannot be cancelled — so the signal
  > stops the browser waiting, the listing completes server-side, and the answer is discarded. The
  > behaviour change is accepted; silently keeping the old claim was the defect. The polling half
  > (`runStatementToCompletion`) is unaffected and still checks the signal each loop, and
  > `uploadFile`'s abort listener is still removed on completion — over `XMLHttpRequest` now, where
  > `xhr.abort()` genuinely does stop the transfer.
- [ ] **The presigned-URL `expiresAt` field is either consumed or removed.** `fileBrowser.service.ts:758` returns it in `DownloadUrl` and no caller reads it (`FileBrowser.tsx:601`, `MetadataPanel.tsx:83` use only `.url`). Separately, `:707-717` clamps `expiresIn` to the remaining credential TTL and floors it at `0` — documented and specified (SPEC-034), and reaching `0` requires Amplify to return already-expired credentials, so this is a hardening nit rather than a live defect: if a floor is added, force `getS3Client(true)` and re-measure below it rather than signing a dead URL.
- [ ] **`lib/env.ts`** validates the required `VITE_*` set once and exposes typed getters plus a configured flag, following `lib/amplify.ts:20`'s pattern, so a missing var fails loudly rather than as a generic SDK error.
- [ ] **`NO_KEY`** replaces the `'__none__'` string literal at all 8 sites.
- [ ] **Icons** — `PencilIcon`, `DownloadIcon`, `TrashIcon`, `RefreshIcon`, `PlayIcon`, `SaveIcon`, `EyeIcon` move into `components/icons.tsx`; the byte-identical `PencilIcon` duplicate, the local `CheckIcon`/`FolderIcon`/`FileIcon` re-declarations, the `*FeatureIcon` aliases and the three divergent refresh spinners are removed.
- [ ] **`logBackgroundFailure(scope, e)`** replaces the seven fire-and-forget `.catch(e => console.warn(...))` sites in `QueryWorkspace`, giving them one consistent tag.

### FR-007: Two carried correctness fixes and one decision

#### Acceptance Criteria

- [ ] `fileBrowser.service.ts:754` escapes or percent-encodes the download filename rather than interpolating it into `filename="${…}"` — S3 permits `"` in a key.
- [ ] The ungated production console logs are wrapped in the dev-only discipline `errorMessages.ts:196-207` already documents: `FilesPage.tsx:67`, `useDataQualityRuns.ts:103` and the seven `QueryWorkspace` sites (subsumed by FR-006's `logBackgroundFailure`).
- [ ] **The `formatSize`/`formatBytes` unit ceiling is decided, not merged by default.** `fileBrowser.format.ts:2-4` says the two are "deliberately not merged", and the divergence is defensible on `undefined` handling — but the *unit ceiling* is not: 3 TB renders as "3072.0 GB" in the file browser and "3.0 TB" in the query status bar. Either unify the ceiling (a visible change, recorded as such) or record why the browser caps at GB. Silently keeping both is not an outcome.

### FR-008: `toUserMessage` call-site ergonomics

#### Description

40+ sites write `toUserMessage(x).message`, and six rebuild the argument by hand (`OperationSummaryBanner.tsx:36`, `useMove.ts:145`, `useCopy.ts:150`, `QueryWorkspace.tsx:531,1122,1167,1194`).

#### Acceptance Criteria

- [ ] `toUserText(error): string` is exported beside `toUserMessage` and accepts `{code?, message?}`-shaped input directly, removing the manual rebuilds.
- [ ] `toUserMessage` is retained for `ErrorBanner.tsx:23`, the only consumer that wants `title`.
- [ ] No rendered message changes.

### FR-009: `QueryWorkspace` and `FileBrowser` are decomposed

#### Description

The seams are named, not speculative.

#### Acceptance Criteria

**QueryWorkspace** (1772 → target under ~500 lines for the container):

- [ ] `useTabRuns` owns `runs`/`runsRef`/`updateRuns`, `statuses`, `runErrors`, `dismissed`, `submittingTabsRef`, `TabExecutionPoller`, `handleStatus`/`handleFinalize`, `submitBatch`, `handleStop` and `dropRunState` — the whole batch state machine, ~450 lines.
- [ ] `useMobileQuerySurface` owns the mobile view state, its handlers and the render-phase reset.
- [ ] `useSaveResults` owns the save-results dialog, overwrite prompt and default name.
- [ ] `<QueryToolbar>` and `<QueryDialogs>` are extracted.
- [ ] **`handleCreateView` and `handleDropConfirm` are unified.** They are the same 40-line function twice (`:1078-1117` vs `:1119-1162`): run statement → append history entry → on success invalidate schema and toast, else toast the mapped error. One `runDdl({sql, database, describe})` replaces both, including their separate in-flight flags.

**FileBrowser** (1300; `FileBrowserContent` 767):

- [ ] `useFileBrowserDialogs` owns the nine dialog flags and their open/confirm handlers; `<FileBrowserDialogs>` owns their mounts.
- [ ] `useFileDownload` (FR-006) and `<OperationFeedback>` (FR-003) are consumed here.
- [ ] `useSharedSpaceAccessRecovery` owns the access-denied detection and refresh.
- [ ] `<FileListTable>` / `<FileListMobile>` own the row rendering and column constants — **without** creating a `*Mobile`/`*Desktop` twin of the same tree (SPEC-095).

**Both:**

- [ ] The existing test suites pass **unchanged**, including SPEC-154's journey tests.
- [ ] No user-visible behaviour, wording, focus order or keyboard behaviour changes.
- [ ] Each extraction is its own commit, so a regression bisects to one seam.

---

## Implementation Phases

### Phase 1: `lib/` primitives

- FR-001 (`s3Json`, including the reconcile decision), FR-006's `s3Url`, bucket helpers, `format`, `NO_KEY`, `env`.
- Land before SPEC-150's `lib/` changes are stale — coordinate if 150 is in flight.

### Phase 2: Shared components

- FR-002 (`FormDialog`), FR-004 (page shell), FR-006's icons.

### Phase 3: Feature-level consolidation

- FR-003 (bulk operation feedback), FR-006's breadcrumbs, `useFileDownload`, `useEscapeKey` stack, `AbortSignal`.
- FR-007 and FR-008.

### Phase 4: Module boundaries

- FR-005 (`features/query/` exports move; the `components/ → features/` lint rule).

### Phase 5: Decomposition — **requires SPEC-154**

- FR-009, `QueryWorkspace` first (its coverage is stronger), then `FileBrowser`.
- One extraction per commit. **Do not start if SPEC-154 has not landed** — see the Reference note.

### Phase 6: Completion

- Completion ritual per `CLAUDE.md`.
- `component-inventory` rows for `FormDialog`, `OperationFeedback`, `SegmentedFilter`, `RefreshIconButton`, `ErrorBoundary`'s neighbours, `useClientPager`, `useFileDownload`, `s3Json`, `s3Url`, `format`, `env` — each in the file matching its path, per the ritual's rule.
- FR-005's dependency direction and FR-007's byte-formatting decision are the two candidates for a `decisions/` entry; the rest are refactors and are not.
