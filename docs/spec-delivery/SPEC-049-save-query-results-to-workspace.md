# Completed Spec — SPEC-049: Save Query Results to Workspace

## What was completed?

- **Replaced "Download CSV"** in `QueryStatusBar` with **"Save results to my files"**. It renders only
  for a `SUCCEEDED`, row-returning query (`canSaveResults` = succeeded + an `outputLocation` + the
  result has columns) — absent for DDL / no-result / failed. The old `onDownloadCsv` handler and the
  dead `getResultCsvUrl` service (no other caller) are removed.
- **`SaveResultsDialog`** (new) — a destination + filename modal: the SPEC-039 `DestinationPicker`
  scoped to the user's own space (the protected `athenaresults/` folder is already excluded by the
  picker) + a validated **File name** input (reuses the file-browser leaf-name validation;
  `.csv` normalized via the new `normalizeCsvName` in `query.format.ts` — added if missing, never
  doubled). Default name = `query-results-{YYYYMMDD-HHmm}`, or `{savedQueryName}-{stamp}` (sanitized)
  when the active tab is linked to a saved query. Save is disabled until the name is valid
  (`DestinationPicker` gained a `confirmDisabled` gate).
- **Save = a full-result server-side copy:** the source key is parsed from the query's
  `QueryStatus.outputLocation` (`parseS3Url`, now exported) and a single **`copyObject`** (SPEC-039)
  writes `{destPrefix}{filename}.csv` within the user-space bucket — all rows Athena wrote, independent
  of the loaded page. **Collision** (`copyObject` returns `Collision`) raises a warn-and-confirm
  Overwrite dialog before re-copying with `overwrite:true`; cancel returns to the modal. On success the
  destination listing is invalidated (`invalidateListing`) and a success **Toast** (extended with an
  optional inline action) offers **"View in Files"** → `/files?prefix={destPrefix}` (SPEC-044). Errors
  show an error Toast and write nothing.

## What changed from earlier specs?

- **SPEC-035 `QueryStatusBar`**: `onDownloadCsv` → `onSaveResults` + `canSaveResults`.
  **SPEC-044 `Toast`**: optional `action` (auto-dismiss suppressed while an action is offered).
  **SPEC-039 `DestinationPicker`**: optional `confirmDisabled`. **`query.service`**: `parseS3Url`
  exported, `getResultCsvUrl` removed. The save-results bucket is read at render (env), not module load.
- No IAM/infra change — reading the user's own `athenaresults/{id}.csv` (`GetObject`) and writing to
  their own prefix (`PutObject` via `CopyObject`) are already granted (SPEC-013); we only copy, never
  delete, so the `athenaresults/` delete-deny is irrelevant.

## Verification

`npm run lint`, `npm run build`, and `npm run test` (**596 pass**, +10: `QueryStatusBar` gating +
Save-results click; `parseS3Url`; `normalizeCsvName`; `SaveResultsDialog` save-to-root/subfolder,
invalid-name-disables-Save, athenaresults excluded; `QueryWorkspace` offers Save for a row-returning
success, full-object copy + Files-link toast, collision→overwrite, error path writes nothing) all green
locally. Live `/query` checkpoint deferred to deploy. No new dependency, no IAM change.
