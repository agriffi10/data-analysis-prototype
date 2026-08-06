# SPEC-155 — build progress and what Phase 6 owes

**Status: phases 1–3 merged, phases 4–6 remain.** Pick up from `main`.

| Phase | State |
|---|---|
| 1 — `lib/` primitives (FR-001, part of FR-006) | Merged — #383 (`94397fa`) |
| 2 — shared components (FR-002, FR-004, FR-006 icons) | Merged — #384 (`9eff2f1`) |
| 3 — feature consolidation (FR-003, rest of FR-006, FR-007, FR-008) | Merged — #385 (`bc6efb8`) |
| 4 — module boundaries (FR-005) | **Next** |
| 5 — decomposition (FR-009) | Not started — re-measure the seams first; both target files have shrunk (FileBrowser lost ~150 lines to FR-003) |
| 6 — completion ritual | Not started — everything below is its input |

**How each phase ran, and should keep running:** build → fresh-context review (two agents:
correctness + spec-conformance) → fix what it finds → commit → PR → merge on green → confirm
`main`. Every phase's review found something real, twice something a user would have hit.

---

## Owed at Phase 6

## Behaviour changes to record in the delivery doc
1. **`useSavedQueries` now invalidates after seeding** (FR-001 AC4's required decision).
   Adopted `useQueryHistory`'s behaviour in both. Costs one extra `GetObject` per save;
   a transient failure on that refetch can surface an error in `SavedQueriesPanel` after
   a save that succeeded — the same trade `useQueryHistory` already makes.
2. **USER-VISIBLE: `formatRelativeTime`'s beyond-a-week fallback** is now `"Jan 15, 2026"`
   (en-US, pinned) instead of the locale-default `"1/15/2026"`. Affects query history,
   saved queries, notifications, data-quality runs. Flag it the way FR-007 demands for
   the byte ceiling — a visible change, accepted deliberately.
3. `fileBrowser.format.formatDate` returns `''` instead of `"Invalid Date"` for an
   unparseable Date. Unreachable today (`lastModified` defaults to `new Date(0)`).
4. `parseS3Url` as seen from `query.service` now trims and accepts `undefined`; the old
   `query.service.parseS3Url` did neither. Only widens what Save-results accepts.
   Same widening at `QueryWorkspace.tablePrefix` — a whitespace-padded Glue LOCATION now
   parses where it used to disable View source files / Refresh. The username prefix guard
   is unchanged, so this is not an isolation change.
5. `userSpaceBucket()` returns `undefined` where it used to return `''` for an
   empty-string env var. Every consumer branches on truthiness; no user-visible effect.

## Component-inventory rows
**New** (foundations.md): `s3Json`, `s3Url`, `format`, `env`, `queryKeys` (`NO_KEY`).
**Stale, need editing:**
- `query-feature.md:76` — `formatBytes / formatDurationMs / formatRelativeTime | query.format.ts`;
  only `formatBytes` is still there.
- `foundations.md:24` — the `userSpaceBucket()` / `userSettingsKey()` row needs
  `sharedSpaceBucket()` + `spaceBuckets()`.
- `user-directory-feature.md:12` — says `getUserDirectory()` reads "via `withCredentialRetry`
  + `GetObjectCommand`"; it goes through `readJsonDocument` now.
- The six reader rows in `notifications-feature.md:9`, `shared-spaces-feature.md:10`,
  `query-feature.md:20,34`, `data-quality-feature.md:12,17` are still accurate — confirm,
  don't rewrite.

## Spec edits owed
- FR-001 AC1 names the option `whenMissing`; the code uses `onMissing` (matches the repo's
  `on*` callback convention, incl. the new `onWriteSuccess`). Move the spec, not the code.
- FR-001 says six readers; seven were converted (`userDirectory.service.ts` shipped in
  SPEC-147, after the audit named the first six).

## Deliberately deferred, not forgotten
- `isPortalConfigured()` has no consumer. Its natural one is `FilesPage.tsx:174`'s
  hand-rolled "VITE_S3_USER_SPACE_BUCKET is not set" banner — wiring it changes what a
  misconfigured deployment renders, so it belongs in a phase that owns that surface.
- `sharedSpaceBucket()` has no caller (every site wanted the `spaceBuckets()` pair). FR-006
  asks for it; it now has a test. Delete it at Phase 6 if nothing has picked it up.

---

# Phase 2 additions

## Behaviour changes to record
6. **Modals draw focus by construction.** `FormDialog` focuses `autoFocusRef` → a
   self-focusing child → the first focusable control. Dialogs that used to open with
   focus on the panel now open on their first control.
7. **`DestinationPicker` claims focus** (opt-in `autoFocus`, Copy/Move only, deferred
   until the listing settles). NOT passed by `SaveResultsDialog`, which remounts the
   picker on every Save-to change and would otherwise steal focus mid-interaction.
8. **USER-VISIBLE: notifications filter labels** render `All`/`Unread` instead of the raw
   `all`/`unread` + CSS `capitalize`. Accessible name changes with them (an improvement —
   it now matches the visible label).
9. **USER-VISIBLE: one refresh glyph.** The connections toolbar and the schema rail's
   database node swap their two-path glyph for the shared four-path one.
10. `LandingPage`'s tick picks up `strokeLinecap="round"` from the shared `CheckIcon`.

## Component-inventory rows owed
- shared components: `FormDialog`, `SegmentedFilter`, `RefreshIconButton`; amend `Banner`
  (new `retry`/`retryLabel`) and the icons row (`PencilIcon`, `DownloadIcon`, `TrashIcon`,
  `TrashLidIcon`, `FolderRowIcon`, `FileRowIcon`, `PlayIcon`, `SaveIcon`, `EyeIcon`,
  `DatabaseRowIcon`).
- shared hooks: `useClientPager`.

## decisions.md candidate (one, and only one)
**Dialog Enter-to-submit semantics.** The portal's form dialogs are real `<form>`s, but
implicit submission is suppressed and Enter submits from ONE designated field
(`submitOnEnterRef`, defaulting to `autoFocusRef`). Adopting the form naively handed
Enter-to-submit to every input in it — a partition-key row mid-edit filed the table build,
verified before the fix. Cross-cutting, easy to get wrong, and nowhere else to live.

## Deviations to note in the delivery doc
- FR-006 names `RefreshIcon` as moving to `components/icons.tsx`; the glyph is unified but
  lives in `RefreshIconButton` (its only consumer).
- `useClientPager.tsx` is the only `use*.tsx` in `src/hooks/` — it returns the pager label
  as JSX. The alternative (move the label into `Pager`) was left for whoever touches `Pager`.
- `FolderRowIcon`/`FileRowIcon` (20-grid) deliberately NOT unified with the 24-grid
  `FolderIcon`; `TrashLidIcon` deliberately NOT unified with `TrashIcon`. Different
  artwork, and unifying moves pixels.

---

# Phase 3 additions

## Behaviour changes to record
11. **USER-VISIBLE: `formatSize` reaches TB.** A 3 TB object read "3072.0 GB" in the file
    browser and "3.0 TB" in the query status bar. FR-007's ceiling decision.
12. **Escape now dispatches by TREE DEPTH**, not per-component opt-out. `Drawer`'s
    `closeOnEscape` prop is GONE (no consumer, and nothing to remember); a busy `Modal`
    now SWALLOWS Escape instead of letting it dismiss the layer beneath.
13. The download `Content-Disposition` filename is escaped (RFC 6266 quoted-string).
14. `expiresAt` removed from `DownloadUrl` — no reader.
15. Background statement polling stops when the workspace unmounts, and says nothing
    when it does (`ABANDONED_CODE`, deliberately NOT `'Cancelled'` — that code belongs
    to an upload rule reading "Upload cancelled.").
16. Unauthenticated copy reports "You must be signed in to copy files."

## Component-inventory rows owed
- file-browser: `OperationFeedback`, `useFileDownload`, `BulkOperationState`/
  `BulkOperationError`; amend the `fileBrowser.paths.ts` row (`buildBreadcrumbs`,
  `BreadcrumbItem`) and the `OperationSummaryBanner` row (`count` is the field now).
- shared hooks: rewrite the `useEscapeKey` row for depth-based layering; add
  `useEscapeBlock` and `hooks/escapeLayerContext.ts`.
- shared components: `EscapeLayer`; amend `Drawer` (prop removed) and `Modal`.
- foundations: `toUserText` and `logBackgroundFailure` beside `toUserMessage`.

## decisions.md candidates
- **Escape layering** — supersedes the per-component `closeOnEscape` gate. Note it sits
  beside CLAUDE.md's settled line about `stopPropagation` and `useEscapeKey`; the digest
  must not contradict it.
- **The `formatSize`/`formatBytes` ceiling** (the spec names this one explicitly).
- Optionally: the abandoned-poll contract — a `ServiceResult` the UI deliberately never
  renders.

## Deviations to note
- FR-006 names `RefreshIcon` as moving to `components/icons.tsx`; it lives in
  `RefreshIconButton` (its only consumer).
- FR-003's AC7 ("hook tests pass unchanged") conflicts with its own AC1 (the rename).
  `FileBrowser.test.tsx` is untouched; three hook tests changed expected literals only.
