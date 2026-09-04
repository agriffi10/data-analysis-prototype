# Spec: Save Query Results to Workspace

**ID:** SPEC-049
**Status:** Completed
**Last Updated:** 2026-06-22
**Depends On:** SPEC-034 (`runQuery` result routing to `{username}/athenaresults/`, `QueryStatus.outputLocation`, `getResultCsvUrl`/`parseS3Url`), SPEC-039 (`copyObject`, `DestinationPicker`, collision warn-and-confirm), SPEC-044 (`Toast`, `/files?prefix=` deep-link), SPEC-035 (`QueryStatusBar`), SPEC-026 (dialog pattern), SPEC-028 (Button/Input)

> **Design:** Needs a design pass. Replaces the **Download CSV** affordance in the `QueryStatusBar` (`design-system.md` §6) with a **Save results** action that opens a destination/filename modal reusing the SPEC-039 `DestinationPicker`, and confirms with the SPEC-044 `Toast`.

## Overview

When a query succeeds, the user should be able to keep its **full** result set in their own file space — not just the rows currently loaded in the browser. Today the status bar offers a "Download CSV" button that presigns the raw Athena result object. This spec **replaces** that with a **Save results to my files** action: the user is prompted for a destination **folder** (within their own space) and a **file name**, and the complete result set is written there as a CSV. They can then download, move, rename, or share it like any other file via the file browser. Because Athena already writes the *entire* result set to the user's `{username}/athenaresults/{id}.csv`, "save" is a fast **server-side S3 copy** of that object into the chosen location — guaranteeing all rows, with no dependence on the browser's paginated view.

## Scope

### In Scope

- **Rename/replace** the `QueryStatusBar` action from "Download CSV" to **Save results** (label e.g. "Save results to my files"); it appears only when the active query **SUCCEEDED** and produced a result object (a row-returning query with an `outputLocation`)

  > **SUPERSEDED 2026-09-04.** The **SUCCEEDED** half is retired. The condition never inspected the
  > execution state, so once a batch could display an earlier statement's result tab it reported
  > "savable" into a branch that rendered only on success — unreachable over complete, already-billed
  > rows. The button now appears beside a **FAILED** or **CANCELLED** verdict too, whenever the
  > displayed result is row-returning. The result-object half stands. Every other statement of the
  > retired rule in this file is marked in place — both acceptance criteria and Phase 1's
  > checkpoint — so no unmarked copy of it is left to read as live.
- A **Save-results modal**: a **destination folder** picker (reuse SPEC-039 `DestinationPicker`, scoped to the user's own space, excluding the protected `athenaresults/` folder) + a **file name** input with a sensible default (e.g. `query-results-{YYYYMMDD-HHmm}`)
- **Save = server-side copy of the complete result object:** `copyObject` from the query's `{username}/athenaresults/{id}.csv` (parsed from `QueryStatus.outputLocation`) to `{username}/{destPrefix}/{filename}.csv` — captures **all** rows regardless of UI pagination
- **`.csv` extension** appended/normalized automatically; **file-name validation** (reuse the file-browser leaf-name validation) with inline errors
- **Collision handling:** if the destination key already exists, the SPEC-039 warn-and-confirm (Overwrite / cancel) applies before writing
- **Success feedback:** a Toast confirming the save with a path, and a link/affordance to **view it in Files** (deep-link `/files?prefix={destPrefix}`, SPEC-044); failure shows an error Toast
- Listing **invalidation** for the destination prefix so the file appears immediately if the user navigates there (reuse `invalidateListing`)

### Out of Scope

- **Formats other than CSV** (no XLSX/JSON/Parquet export) — Athena's native result object is CSV; other formats are future work
- A **client-side** CSV builder from `GetQueryResults` pages — unnecessary and slower; the raw result object is already the complete set (see Resolved). (Fallback only if a future query path lacks a copyable result object — not in v1)
- **Saving into another user's or a shared space** — destination is the user's own space only (shared-space result placement is a shared-spaces-arc decision)
- **Downloading directly** to the browser (the prior behavior) — saving to the workspace is the chosen model; the user downloads from the file browser afterward (existing SPEC-015 download)
- Saving results for **DDL / no-result** queries (nothing to save) — the action is hidden/disabled there
- Any **IAM / infra** change — read of the user's own `athenaresults/{id}.csv` (`GetObject`) and write to the user's own prefix (`PutObject` via `CopyObject`) are both already granted (SPEC-013); the `athenaresults/` delete-deny is irrelevant (we never delete, only copy out)

---

## Functional Requirements

### FR-001: Replace the status-bar action

#### Description:

The status bar offers "Save results" instead of "Download CSV".

#### Acceptance Criteria:

- [ ] The `QueryStatusBar` shows a **Save results** button (label "Save results to my files"; the old "Download CSV" button and its `onDownloadCsv` handler are removed)
- [ ] It renders **only** when the active query is `SUCCEEDED` **and** has a result object (`outputLocation` present and the query returned rows / is not a pure DDL statement); otherwise it is absent

  > **SUPERSEDED 2026-09-04 (see FR-001).** Not `SUCCEEDED`-only. It renders whenever the displayed
  > result is row-returning and a verdict is showing, **FAILED** and **CANCELLED** included.
- [ ] The button is keyboard-focusable with the standard focus ring and an accessible label

### FR-002: Save-results modal (destination + name)

#### Acceptance Criteria:

- [ ] Clicking **Save results** opens a modal (SPEC-026 pattern) with: a **destination folder** picker (SPEC-039 `DestinationPicker`, the user's own space, excluding `athenaresults/`), a **file name** `Input` defaulted to `query-results-{YYYYMMDD-HHmm}`, and **Save**/**Cancel**
- [ ] The file name is validated (reuse the file-browser leaf-name validation); an invalid name shows an inline error and disables **Save**; a `.csv` extension is **normalized** (added if missing; not duplicated if the user typed it)
- [ ] **Save** is disabled until a destination is chosen and the name is valid; Cancel/Escape closes with no write

### FR-003: Save = full-result server-side copy

#### Description:

Saving copies the complete Athena result object into the chosen location.

#### Acceptance Criteria:

- [ ] On confirm, the source key is derived from the active query's `QueryStatus.outputLocation` (`s3://{bucket}/{username}/athenaresults/{id}.csv`, parsed with the existing `parseS3Url`); the destination is `{username}/{destPrefix}/{filename}.csv`
- [ ] The save is a single **`copyObject`** (SPEC-039) within the user-space bucket — it copies the **entire** result set (all rows Athena wrote), independent of how many pages the results table loaded
- [ ] On success the destination listing is invalidated (`invalidateListing`) so the new file appears when the user browses there
- [ ] The action shows progress / disables Save while the copy is in flight

### FR-004: Collision handling

#### Acceptance Criteria:

- [ ] If the destination key already exists (`objectExists`, SPEC-039), the SPEC-039 **warn-and-confirm** (Overwrite / Cancel) is shown before the copy; confirming overwrites, cancelling returns to the modal with the name editable
- [ ] No silent overwrite ever occurs (versioning is off — architecture Known Constraints)

### FR-005: Feedback + view in Files

#### Acceptance Criteria:

- [ ] On **success** a **Toast** confirms the save and names the location, with an affordance to **view in Files** that deep-links the file browser to the destination (`/files?prefix={destPrefix}`, SPEC-044)
- [ ] On **failure** (copy/permission error) an **error Toast** surfaces the message; nothing is written and the modal handling per design (default: stays open with the error)

### FR-006: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: the button shows only for a succeeded row-returning query and is gone for DDL/no-result/failed; the modal validates + normalizes the `.csv` name and requires a destination; confirm derives the source key from `outputLocation` and issues a single `copyObject` to `{username}/{destPrefix}/{filename}.csv`; collision triggers the overwrite confirm; success invalidates the destination listing and shows a Toast with a Files deep-link; the error path shows an error Toast and writes nothing

  > **SUPERSEDED 2026-09-04 (see FR-001).** "Shows only for a succeeded row-returning query and is
  > gone for … failed" is retired on BOTH halves — the tests now assert the opposite for a failed
  > batch still displaying an earlier statement's result. The DDL / no-result absences stand.

---

## Data Model

No new persisted types. Reuses SPEC-039 `copyObject`/`objectExists`, SPEC-034 `QueryStatus.outputLocation` + `parseS3Url`, and the file-browser path/validation helpers.

```ts
// Derivation (FR-003) — note: parseS3Url is currently private in query.service.ts; export it.
const { bucket, key: sourceKey } = parseS3Url(status.outputLocation); // …/athenaresults/{id}.csv
const destKey = `${username}/${destPrefix}${normalizeCsvName(filename)}`;
await copyObject({ bucket, sourceKey, destKey, username, overwrite });
```

## API / Interface Contract

```ts
// Reuses existing services; no new service signature required.
// QueryStatusBar prop change:
type QueryStatusBarProps = {
  // …existing (status, isInFlight, startedAt, rowCount, hasMoreRows)…
  onSaveResults: () => void;   // replaces onDownloadCsv (FR-001)
};

// Save handler (QueryWorkspace): open modal → on confirm, parse outputLocation → copyObject → toast.
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── QueryStatusBar.tsx          ← "Download CSV" → "Save results to my files" (onSaveResults)
├── QueryStatusBar.test.tsx
├── SaveResultsDialog.tsx       ← NEW: destination picker (SPEC-039) + filename input + validation
├── SaveResultsDialog.test.tsx  ← NEW
├── query.service.ts            ← export/relocate `parseS3Url` (currently a private fn) so the Save flow can import it; remove/retire getResultCsvUrl if unused after this change (see Open Q)
└── QueryWorkspace.tsx          ← Save-results flow: parse outputLocation → copyObject → collision → Toast + Files link
```

## Implementation Phases

### Phase 1: Button swap + modal + copy

- Replace the status-bar action; build `SaveResultsDialog` (destination + validated name); wire confirm → derive source from `outputLocation` → `copyObject` → invalidate destination (FR-001–FR-003)

#### Checkpoint

`npm run dev`: run a `SELECT` that returns rows → **Save results to my files** appears; choosing a folder + name writes `{name}.csv` into the user's space (verify the row count matches the *full* query, not just the loaded page); the button is absent for a DDL or failed query. `npm run test` + `npm run lint` pass.

> **SUPERSEDED 2026-09-04 (see FR-001).** Absent for a DDL query, but **not** for a failed one when
> an earlier statement's result is the grid on screen.

### Phase 2: Collision + feedback

- SPEC-039 overwrite confirm on an existing destination; success/error Toast; "view in Files" deep-link (FR-004, FR-005)

#### Checkpoint

Saving onto an existing file prompts Overwrite/Cancel; a successful save shows a Toast with a working "view in Files" link landing on the destination folder; a forced error shows an error Toast and writes nothing. `npm run test` + `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-21, user decision):** the action **saves the full result set to the user's workspace** (folder + filename prompt), replacing the direct download; users download from Files afterward.
- [x] **Resolved (2026-06-21):** "all results" is guaranteed by **copying Athena's complete result object** (`{id}.csv`) server-side, not by re-paginating `GetQueryResults` in the browser.
- [x] **Resolved (2026-06-21):** destination is the **user's own space** only; `athenaresults/` is excluded from the picker.
- [x] **Resolved (2026-06-21, default):** default filename is `query-results-{YYYYMMDD-HHmm}.csv`; when the active tab is **linked to a saved query** (SPEC-043) the default is `{savedQueryName}-{YYYYMMDD-HHmm}.csv` (sanitized to the leaf-name rule). Flag for a different pattern.
- [x] **Resolved (2026-06-21, default):** `getResultCsvUrl` is **removed** as dead code once the download action is gone (no other caller). Flag if it should be retained as a service-layer utility.
