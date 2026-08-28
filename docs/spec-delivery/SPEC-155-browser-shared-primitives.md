# Completed Spec — SPEC-155: Browser Shared Primitives & Component Decomposition

Reuse and structure work from the 2026-08-05 audit, deliberately separated from behaviour change.
Six phases across four PRs: #383 (lib/ primitives), #384 (shared components), #385 (feature
consolidation), and one PR for phases 4–6.

## What was completed?

**One implementation where there had been several.**

- **`lib/s3Json.ts`** — `readJsonDocument` / `writeJsonDocument` behind all **seven**
  `user_settings/`-style readers and both writers. `parse` must be total; `onMissing` says what a
  404 means *here*. (FR-001)
- **`components/FormDialog.tsx`** — the body/footer chrome, Cancel/primary pair, busy state and
  focus-on-mount that eleven dialogs re-authored. (FR-002)
- **One `BulkOperationState`** + `<OperationFeedback>` for delete/move/copy, replacing three copies
  of a four-block stanza and three differently-named count fields. (FR-003)
- **A page shell** — `useClientPager`, `SegmentedFilter`, `RefreshIconButton`, `Banner`'s `retry`.
  (FR-004)
- **`features/query/` stops being a shared layer** — `Toast` → `components/`, the catalog-identifier
  rule → `lib/catalogIdentifier.ts`, and a new **`features/connections/`** holding `Connection`,
  `isConnectionUsable`, `useConnections`, `connectionStatusLabel`, `Sidebar` and `SpacesList`. An
  ESLint rule now bans `features/**` under `src/components/**`. (FR-005)
- **Smaller primitives** — `lib/s3Url.ts`, `lib/format.ts`, `lib/env.ts`, `NO_KEY`, `spaceBuckets()`,
  `useFileDownload`, one clamped breadcrumbs/parent-of, a depth-dispatching `useEscapeKey` +
  `EscapeLayer`, `AbortSignal` threading, and the icon consolidation. (FR-006)
- **Two carried fixes** — the download `Content-Disposition` filename is RFC 6266-escaped, and the
  ungated production console logs go through `logBackgroundFailure`. (FR-007)
- **`toUserText`** beside `toUserMessage`, removing the manual `{code, message}` rebuilds. (FR-008)
- **Decomposition** (FR-009): `QueryWorkspace.tsx` **1770 → 727** lines and `FileBrowser.tsx`
  **1101 → 516**, one extraction per commit.
  - Query: `useTabRuns` (+ `TabExecutionPoller`), `useRunDdl`, `useMobileQuerySurface`,
    `useSaveResults`, `useTableActions`, `QueryToolbar`, `QueryResultsRegion`, `QueryDialogs`.
  - Files: `useFileBrowserDialogs`, `FileBrowserDialogs`, `useSharedSpaceAccessRecovery`,
    `FileListTable` / `FileListMobile`, `SelectionToolbar`.

Four `decisions/` entries: the `components/ → features/` rule, `FormDialog`'s Enter-to-submit
semantics, Escape layering, and the byte-formatter unit ceiling.

### User-visible changes (all deliberate)

The spec forbids user-visible change except where called out. Five landed, each on purpose:

1. **`formatSize` reaches TB.** A 3 TB object read `3072.0 GB` in the file browser and `3.0 TB` in
   the query status bar. FR-007's decision; recorded in `decisions/`.
2. **`formatRelativeTime`'s beyond-a-week fallback is pinned en-US** — `Jan 15, 2026` instead of the
   locale-default `1/15/2026`. Affects query history, saved queries, notifications, data-quality runs.
3. **Notification filter labels** render `All`/`Unread` instead of the raw `all`/`unread` under CSS
   `capitalize`; the accessible name now matches the visible label.
4. **One refresh glyph.** The connections toolbar and the schema rail's database node swap their
   two-path glyph for the shared four-path one; `LandingPage`'s tick picks up `strokeLinecap="round"`.
5. **Modals draw focus by construction.** `FormDialog` focuses `autoFocusRef` → a self-focusing child
   → the first focusable control, so dialogs that used to open with focus on the panel now open on
   their first control. `DestinationPicker` claims focus for Copy/Move only — **not** in
   `SaveResultsDialog`, which remounts the picker on every Save-to change and would steal focus
   mid-interaction.

### Deliberate deviations

- **FR-005 AC4 is met by rule + a two-file allowlist, not by zero violations.** `Header.tsx` and
  `ProtectedLayout.tsx` are app chrome — wiring features into the shell is what they are for — and
  are named in `eslint.config.js`. Tests are exempt (they mount real features by design). Three
  files that *were* on that list (`Sidebar`, `SpacesList`, `UsernameCombobox`/`UsernameChipsField`)
  were moved into features instead. Reasoning and the two residuals are in `decisions/`.
> **Superseded (2026-08-09):** the import is gone. `invalidateListing` moved to
> `features/file-browser/invalidateListing.ts` and the ESLint rule widened to `src/lib/**` and
> `src/hooks/**`. The mock count below was also wrong — **two** test files mocked the module by
> path, not six; the rest merely imported it. Record: `decisions/`.

- **`lib/queryClient.ts` still imports `features/file-browser/fileBrowserKeys`** — the same inversion
  one layer lower, and not covered by the rule. Six test files mock that module by path, so moving
  it would change tests this spec requires to pass unchanged. Named in `decisions/` as the next
  notch.
- **FR-009's "~500 lines" for `QueryWorkspace` was not reached** (727). Every named extraction
  shipped, plus two the spec did not name (`useTableActions`, `QueryResultsRegion`) because the
  remaining JSX was mostly those. Going further would have meant inventing seams the audit did not
  find.
- **FR-006 names `RefreshIcon` as moving to `components/icons.tsx`;** the glyph is unified but lives
  in `RefreshIconButton`, its only consumer.
- **`FolderRowIcon`/`FileRowIcon` (20-grid) were NOT unified** with the 24-grid `FolderIcon`, and
  `TrashLidIcon` not with `TrashIcon` — different artwork, and unifying moves pixels.
- **FR-003's AC7 ("hook tests pass unchanged") conflicts with its own AC1** (the count-field rename).
  `FileBrowser.test.tsx` is untouched; three hook tests changed expected literals only.
- **`useClientPager.tsx` is the only `use*.tsx` in `src/hooks/`** — it returns the pager label as
  JSX. Moving the label into `Pager` was left for whoever touches `Pager`.
- **`sharedSpaceBucket()` was kept with no caller** (every site wanted the `spaceBuckets()` pair).
  FR-006 asks for it and it has a test. **`isPortalConfigured()` also has no consumer** — its natural
  one is `FilesPage.tsx`'s hand-rolled "VITE_S3_USER_SPACE_BUCKET is not set" banner, and wiring it
  changes what a misconfigured deployment renders, so it belongs to a spec that owns that surface.

## What changed from earlier specs?

- **`useSavedQueries` now invalidates after seeding** (FR-001 AC4's required decision): it adopted
  `useQueryHistory`'s behaviour rather than the reverse. Costs one extra `GetObject` per save, and a
  transient failure on that refetch can surface an error in `SavedQueriesPanel` after a save that
  succeeded — the same trade `useQueryHistory` already made.
- **`Drawer`'s `closeOnEscape` prop is GONE** (no consumer; superseded by depth-based Escape
  dispatch). A busy `Modal` now **swallows** Escape instead of letting it dismiss the layer beneath.
- **`expiresAt` removed from `DownloadUrl`** — no reader.
- **Background statement polling stops when the workspace unmounts**, and says nothing when it does
  (`ABANDONED_CODE`, deliberately *not* `'Cancelled'` — that code belongs to an upload rule reading
  "Upload cancelled.").
- **`parseS3Url` widened** what `query.service` and `QueryWorkspace.tablePrefix` accept: it trims and
  accepts `undefined`, so a whitespace-padded Glue `LOCATION` now parses where it used to disable
  View source files / Refresh. The username prefix guard is unchanged — **not** an isolation change.
- `fileBrowser.format.formatDate` returns `''` instead of `"Invalid Date"` for an unparseable Date
  (unreachable today; `lastModified` defaults to `new Date(0)`).
- `userSpaceBucket()` returns `undefined` where it used to return `''` for an empty-string env var.
  Every consumer branches on truthiness.
- Unauthenticated copy now reports "You must be signed in to copy files."
- `SPEC-052`'s `connectionStatusLabel` and `SPEC-047/052`'s `useConnections` moved to
  `features/connections/`; `SPEC-146/147`'s `UsernameCombobox`/`UsernameChipsField` moved to
  `features/user-directory/`; `SPEC-085/099`'s `Sidebar`/`SpacesList` moved to
  `features/connections/`. Import paths only.

## Verification

Prettier, ESLint (`--max-warnings 0`, including the new import rule and a guard-the-guard probe
confirming it fires), `npm run build` (`tsc -b`) and the full suite — **1655 tests across 68 files,
passing unchanged** at every phase, which is the spec's own test for behaviour preservation. Each
phase was reviewed in a fresh context (correctness + spec conformance) before merge; the Phase-4
review drove the allowlist reduction above.

Nothing is deferred to deploy: this spec ships no infra and no Lambda code.

**Help & guides sweep: no change owed.** The five user-visible changes are formatting and chrome —
a unit ceiling, a date fallback, two filter labels, one glyph and dialog focus. `helpContent.ts`
documents none of them; its notifications guide already names the **All** / **Unread** controls by
their visible labels, which is what those filters now render literally.
