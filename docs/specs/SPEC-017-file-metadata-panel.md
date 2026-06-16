# Spec: File Metadata Panel

**ID:** SPEC-017
**Status:** Completed
**Last Updated:** 2026-06-11
**Depends On:** SPEC-013 (read access to own prefix), SPEC-015 (TanStack Query data foundation)

## Overview

Let users inspect the details of one of their files without leaving the browser
— size, content type, last-modified time, ETag, storage class, and any custom
metadata stored on the object. The data comes from a single `HeadObject` call
(no body transfer) and is shown in a read-only side panel. This is a small,
read-only spec that rounds out the "view file" half of the filesystem
experience.

## Scope

### In Scope

- A `getObjectMetadata` service backed by `HeadObject`
- A read-only metadata panel (drawer) opened from a file's row
- Display of: display name, path relative to the user root, size (human-readable + exact bytes), content type, last modified, ETag, storage class, and user-defined metadata key/value pairs
- TanStack Query caching of the head request, keyed per object

### Out of Scope

- **Editing** metadata or content type (in S3 this is a copy-over-self operation — a possible future spec)
- Object tags (`GetObjectTagging`) and ACLs (ACLs are disabled by `BucketOwnerEnforced`, SPEC-010)
- Folder metadata / aggregate folder size
- Any IAM change — `HeadObject` is authorized by the `s3:GetObject` grant from SPEC-013

---

## Functional Requirements

### FR-001: Metadata Service

#### Description:

Fetch the metadata of a single object via `HeadObject`.

#### Acceptance Criteria:

- [ ] `getObjectMetadata({ bucket, key })` issues `HeadObject` with the client from `getS3Client()` and returns `ServiceResult<ObjectMetadata>`
- [ ] Maps `ContentLength` → `size`, `ContentType` → `contentType`, `LastModified` → `lastModified`, `ETag` → `etag`, `StorageClass` → `storageClass` (defaulting to `"STANDARD"` when absent), and `Metadata` → `userMetadata` (record of string→string)
- [ ] A NotFound (404) returns a `ServiceResult` error with a clear message, not a throw
- [ ] Credential-expiry triggers one transparent retry via `getS3Client(true)`
- [ ] Unit tests cover the happy path, the field mapping (including missing `StorageClass`), and the not-found path

### FR-002: Metadata Panel UI

#### Description:

A drawer shows the metadata for the selected file.

#### Acceptance Criteria:

- [ ] Each file row exposes a "Details" action that opens a side drawer for that file; folders and the hidden marker expose no Details action
- [ ] The drawer fetches via TanStack Query (key includes bucket + key) and shows a loading state, then the fields from FR-001
- [ ] Size is shown both human-readable (e.g. "1.4 MB") and as exact bytes; `lastModified` is shown in the user's locale
- [ ] When `userMetadata` is empty, the panel shows a "No custom metadata" empty state rather than an empty section
- [ ] A fetch error renders inline in the drawer (not a crash); closing and reopening retries
- [ ] The drawer is dismissible (close button + Escape) and does not block the rest of the browser

---

## Data Model

```ts
// src/features/file-browser/fileBrowser.types.ts (additions)

export type ObjectMetadata = {
  key: string;
  contentType: string;
  size: number;                       // bytes (ContentLength)
  lastModified: Date;
  etag: string;
  storageClass: string;               // "STANDARD" when S3 omits it
  userMetadata: Record<string, string>; // x-amz-meta-* pairs
};
```

---

## API / Interface Contract

```ts
// src/features/file-browser/fileBrowser.service.ts (addition)
getObjectMetadata(params: {
  bucket: string;
  key: string;
}): Promise<ServiceResult<ObjectMetadata>>;
```

## Environment Variables

None new.

## File & Folder Structure

```
apps/portal/src/features/file-browser/
├── fileBrowser.service.ts        ← + getObjectMetadata
├── fileBrowser.service.test.ts   ← + metadata tests
├── useObjectMetadata.ts          ← NEW: useQuery wrapper, keyed per object
├── MetadataPanel.tsx             ← NEW: read-only drawer
├── MetadataPanel.test.tsx        ← NEW
└── FileBrowser.tsx               ← + per-file "Details" action
```

## Implementation Phases

### Phase 1: Service + hook + panel (single phase — small spec)

- `getObjectMetadata`, `useObjectMetadata`, `MetadataPanel`, and the row action (FR-001, FR-002)

#### Checkpoint

Signed in, clicking "Details" on a file opens a drawer showing correct size/type/last-modified/ETag/storage class; an object with `x-amz-meta-*` shows those pairs while one without shows the empty state; the drawer closes with Escape. `npm run test` and `npm run lint` pass.

## Open Questions

None — read-only `HeadObject`; metadata **editing** is explicitly out of scope.
