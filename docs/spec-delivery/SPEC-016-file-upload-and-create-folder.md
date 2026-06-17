# Completed Spec - File Upload (managed, auto-multipart + progress) + Create Folder

## What was completed from this spec?

The browser is now a writable filesystem: users upload files (any size, with a
live progress bar) and create folders, into the folder they're viewing, with
overwrite protection. Delivered in three phases.

**Phase 1 — IaC (merged #33, corrected by #34):**
- **FR-005** — the SPEC-013 portal-role policy gained `s3:AbortMultipartUpload` +
  `s3:ListMultipartUploadParts` (object-level, prefix-scoped). `Create/Upload/
  CompleteMultipartUpload` ride on the existing `s3:PutObject`.
  `s3:ListBucketMultipartUploads` was deliberately **dropped** — it doesn't
  support the `s3:prefix` condition key (always `implicitDeny`, verified via
  `simulate-principal-policy`), `lib-storage` doesn't use it, and granting it
  bucket-wide would leak other users' in-progress upload keys.
- **FR-006** — an `abort_incomplete_multipart_upload` lifecycle rule (7 days) on
  the user-space bucket (first lifecycle rule on it) so interrupted uploads leave
  no billable orphaned parts. No deploy-role change needed (it already holds
  `s3:*` on the bucket).

**Phase 2 — Service layer (merged #35):**
- `objectExists` (HEAD → bool, 404→false), `uploadFile` (managed
  `@aws-sdk/lib-storage` `Upload`: single request ≤5 MiB part size, automatic
  multipart above; `onProgress`; `AbortSignal` cancel; size cap; collision guard;
  one creds-refresh retry; never throws), `createFolder` (zero-byte `{prefix}{name}/`
  marker, `application/x-directory`). `validateFolderName` + `uploadPercent` helpers.
  Types/constants in `fileBrowser.types.ts`; `VITE_MAX_UPLOAD_BYTES` documented.

**Phase 3 — UI (merged #36):**
- `useFileUpload` (progress %, collision warn-and-confirm orchestration, listing
  invalidation on success), `UploadDropzone` (picker + drag-and-drop + progress
  bar), `CreateFolderDialog`, `CollisionPrompt` (Overwrite / Rename / Cancel).
  `FileBrowser` gained a `writable` prop; the dev-unauth browser stays read-only.

## What has changed?

- **New dependency**: `@aws-sdk/lib-storage`. New env var `VITE_MAX_UPLOAD_BYTES`
  (optional, default 5 GiB).
- **Infra**: portal-role policy (multipart actions) + user-space bucket lifecycle
  rule. **Also fixed a latent SPEC-013 bug** uncovered here: the user-space bucket
  policy denied the *deploy role* `s3:ListBucket`, so `tofu` refresh reported the
  bucket as "deleted" and every infra plan proposed a destructive recreate. Fixed
  by excepting `dat-deploy-role` in the bucket policy (it already holds `s3:*`),
  which required a one-time break-glass `put-bucket-policy` to escape the refresh
  deadlock. See [[deploy-role-iam-gotchas]].
- **Frontend**: write operations wired into the file browser; the SPEC-001/002
  read-only behavior is preserved when `writable` is false.

### Post-merge fixes (browser/runtime)

- **`global` ReferenceError (#37):** `lib-storage` pulls transitive deps that
  reference Node's `global`, crashing the bundle at load. Fixed with Vite
  `define: { global: 'globalThis' }`.
- **Multipart CRC32 checksum (#38):** AWS SDK v3 defaults
  `requestChecksumCalculation` to `WHEN_SUPPORTED`, which broke browser multipart
  (`CompleteMultipartUpload` rejected: "checksum … missing for part 1"). Set both
  `requestChecksumCalculation` and `responseChecksumValidation` to `WHEN_REQUIRED`
  on the S3 clients. Small (single-`PutObject`) uploads were unaffected.

## Verification

- **Unit/build**: 125 tests pass; `lint`/`build` clean across all phases. Coverage:
  `objectExists`, `uploadPercent` (incl. zero-byte), `validateFolderName`,
  `uploadFile` (upload/progress/collision/size-cap/abort/no-creds), `createFolder`,
  the `useFileUpload` orchestration (collision overwrite + rename for file and
  folder, error, in-flight progress), and write-control gating + dialogs.
- **IaC (live)**: lifecycle rule confirmed via `get-bucket-lifecycle-configuration`;
  multipart actions confirmed prefix-isolated via `simulate-principal-policy`
  (alice allowed / bob denied); infra plans/applies clean (no recreate).
- **Live, deployed app (2026-06-15)**: uploading **both small and large (>5 MiB,
  multipart) files** succeeds with an advancing progress bar and the files persist
  — confirmed by the user after the `global` and checksum fixes deployed.

### Follow-ups / notes

- **Benign 404 on first upload of a new name:** the collision pre-check
  (`objectExists` → `HeadObject`) returns 404 for a not-yet-existing key, which the
  app handles as "no collision." Browsers log the 404 even though it's handled.
  Could be swapped for a `ListObjectsV2` existence check to keep the console clean
  (deferred — cosmetic only).
- **SPEC-015 download** can now be exercised against user-written data (the
  presigned-download path was code-complete + unit-verified; its live check rides
  along here).
- Multi-file **upload queue** + per-file **cancel UI** remain **SPEC-020** (built
  on this spec's `uploadFile`).

## Later changes

- **Upload moved into a right slide-over drawer (PR #55).** The `UploadDropzone` delivered here is
  no longer always-mounted above the file list. A primary **Upload** button in the file-browser
  toolbar now opens a `UploadDrawer` (420px right slide-over) that hosts the dropzone, the
  `CollisionPrompt`, and the write-error banner. The drawer auto-opens whenever a collision is
  pending or an upload is in progress (so neither is trapped behind the scrim); create-folder
  errors still render inline when the drawer is closed. `useFileUpload`, `UploadDropzone`,
  `CreateFolderDialog`, and `CollisionPrompt` behaviour are unchanged — only their placement moved.
