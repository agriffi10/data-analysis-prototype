# Completed Spec - File Metadata Panel

## What was completed from this spec?

Users can now inspect a single file's details without leaving the browser. Each
file row exposes a **Details** action that opens a read-only side drawer backed by
one `HeadObject` call (no body transfer). Delivered in a single phase (small,
read-only spec).

**FR-001 — Metadata service:**
- `getObjectMetadata({ bucket, key })` in `fileBrowser.service.ts` issues
  `HeadObjectCommand` via the authenticated client and returns
  `ServiceResult<ObjectMetadata>`. Maps `ContentLength→size`,
  `ContentType→contentType` (default `application/octet-stream`),
  `LastModified→lastModified`, `ETag→etag`, `StorageClass→storageClass`
  (default `"STANDARD"` when S3 omits it), and `Metadata→userMetadata` (`{}` when
  none).
- A NotFound/404 is surfaced as a clear `ServiceResult` error
  (`code: 'NotFound'`, "This file no longer exists."), not a throw. Credential
  expiry is retried once via the existing `withAuthenticatedClient` wrapper. Never
  throws.
- New `ObjectMetadata` type in `fileBrowser.types.ts`; new
  `fileBrowserKeys.metadata(bucket, key)` query key.

**FR-002 — Metadata panel UI:**
- `useObjectMetadata(bucket, key | null)` — `useQuery` wrapper keyed per object,
  disabled when no file is selected.
- `MetadataPanel.tsx` — a non-blocking drawer (`role="dialog"`,
  `aria-modal="false"`, no backdrop) showing display name, user-relative path
  (root prefix stripped, so the username is never shown — SPEC-013), size
  (human-readable **and** exact bytes), content type, locale last-modified, ETag
  (quotes stripped for display), storage class, and custom `x-amz-meta-*` pairs —
  with a "No custom metadata" empty state. Loading and inline-error states; closing
  and reopening refetches (a fresh query observer mounts on the same key).
  Dismissible via close button and Escape.
- `FileBrowser.tsx` — per-file **Details** action wired to a `detailsFile` state
  that conditionally mounts the panel. Folders use `FolderRow` (no action) and the
  prefix marker is already filtered out of `files`, so neither exposes Details.

## What has changed?

- **No new dependencies, no new env vars, no IaC change.** `HeadObject` is already
  authorized by the `s3:GetObject` grant from SPEC-013, and the pattern was already
  in use by `objectExists` (SPEC-016).
- **Frontend only.** Additive to the file browser — the existing download/upload/
  create-folder behavior is untouched. The `FileRow` signature gained an `onDetails`
  prop; no other component contract changed.

## Verification

- **Unit/build**: 142 tests pass; `lint` and `build` (incl. `tsc` typecheck) clean.
  Coverage: `getObjectMetadata` (full field mapping, `StorageClass`/`Metadata`
  defaults, 404→error, expiry retry); `MetadataPanel` (loading, inline error,
  data fields, size human+bytes, relative path, ETag stripping, custom-metadata
  pairs vs. empty state, close button, Escape, non-blocking dialog); `FileBrowser`
  Details action (present on files, absent on folders, opens/closes the drawer).
- **Live signed-in checkpoint**: deferred to PR review — the `/files` browser sits
  behind the Cognito auth gate (SPEC-008) and `getObjectMetadata` is
  authenticated-only (no dev-unauth fallback), so the happy-path drawer render
  requires an interactive sign-in. The drawer's open/close/Escape, all render
  states, and the service's 404/expiry paths are unit-covered.

### Follow-ups / notes

- **Metadata editing** (content type / custom metadata) is explicitly out of scope
  — in S3 it's a copy-over-self operation, a possible future spec.
- Object **tags** (`GetObjectTagging`) and ACLs are out of scope (ACLs disabled by
  `BucketOwnerEnforced`, SPEC-010).
- Folder / aggregate-size metadata is out of scope.
