# Spec: S3 File Listing

**ID:** SPEC-001  
**Status:** Completed  
**Last Updated:** 2026-05-21  
**Depends On:** None (no auth in this phase)

---

## Overview

Build the core file listing capability: connect to an S3 bucket, retrieve the list of objects, and display them in a UI component. This is the foundational data layer that all other file operations (upload, download, delete) will build on.

Authentication is explicitly **out of scope** for this spec. The S3 client will be configured with static credentials via environment variables for local development.

---

## Scope

### In Scope

- S3 client initialization and configuration (`src/lib/s3Client.ts`)
- Service function to list objects in a bucket with optional prefix (folder) filtering
- TypeScript types for S3 file/folder objects
- React hook to manage listing state (loading, error, data)
- `FileBrowser` UI component that renders the file list
- Support for "folder" navigation (S3 common prefixes as virtual folders)
- Empty state handling (no files in bucket/prefix)
- Error state handling (SDK errors surfaced to UI)
- Unit tests for the service function and hook

### Out of Scope

- File upload
- File download
- File deletion
- Authentication / Cognito integration
- Pagination beyond a single `ListObjectsV2`
- File metadata display beyond name, size, and last modified
- Search or filtering within the file list

---

## Functional Requirements

### FR-001: S3 Client Initialization

**Description:** A singleton S3 client must be created from environment variables and reusable across all service calls.  

**Acceptance Criteria:**
- [ ] `src/lib/s3Client.ts` exports a single `S3Client` instance
- [ ] Client reads `VITE_AWS_REGION`, `VITE_AWS_ACCESS_KEY_ID`, `VITE_AWS_SECRET_ACCESS_KEY` from env
- [ ] `.env.example` documents all three variables
- [ ] Client is not re-instantiated on every call

### FR-002: List Files Service Function
**Description:** A service function that calls `ListObjectsV2` and returns a normalized list of files and folders.  
**Acceptance Criteria:**
- [ ] `src/features/file-browser/fileBrowser.service.ts` exports `listFiles(bucket: string, prefix?: string): Promise<ServiceResult<FileList>>`
- [ ] Returns both file objects and common prefixes (virtual folders) in a single response
- [ ] Files include: `key`, `name` (last path segment), `size` (bytes), `lastModified` (Date), `type: 'file'`
- [ ] Folders include: `prefix`, `name` (folder segment), `type: 'folder'`
- [ ] On SDK error, returns `{ success: false, error: { message, code } }` — does not throw
- [ ] Folders are sorted before files; both groups sorted alphabetically by name

### FR-003: File Listing Hook
**Description:** A React hook that manages the async state of the file listing.  
**Acceptance Criteria:**
- [ ] `useFileBrowser(bucket: string, prefix?: string)` exported from `src/features/file-browser/useFileBrowser.ts`
- [ ] Returns `{ files, folders, isLoading, error, refresh }`
- [ ] Fetches on mount and when `prefix` changes
- [ ] `refresh()` re-fetches without changing prefix
- [ ] `isLoading` is `true` during fetch, `false` otherwise
- [ ] `error` is `null` on success, `string` on failure

### FR-004: FileBrowser Component
**Description:** A UI component that renders the file/folder list returned by the hook.  
**Acceptance Criteria:**
- [ ] `src/features/file-browser/FileBrowser.tsx` renders the list using `useFileBrowser`
- [ ] Shows a loading spinner while `isLoading` is true
- [ ] Shows an error message if `error` is non-null
- [ ] Shows an empty state message if both `files` and `folders` are empty
- [ ] Renders folders first, then files
- [ ] Each folder row is clickable and updates the current prefix (drill-down navigation)
- [ ] Each file row shows: icon, name, size (human-readable, e.g. "1.2 MB"), last modified date
- [ ] A breadcrumb shows the current path and allows navigating up to any ancestor prefix

---

## Data Model

```ts
// src/types/s3.types.ts

export type S3FileItem = {
  type: 'file';
  key: string;        // full S3 key, e.g. "documents/report.pdf"
  name: string;       // display name, e.g. "report.pdf"
  size: number;       // bytes
  lastModified: Date;
};

export type S3FolderItem = {
  type: 'folder';
  prefix: string;     // full S3 prefix, e.g. "documents/"
  name: string;       // display name, e.g. "documents"
};

export type S3Item = S3FileItem | S3FolderItem;

export type FileList = {
  files: S3FileItem[];
  folders: S3FolderItem[];
};
```

---

## Environment Variables

Add to `.env.example`:
```
VITE_AWS_REGION=us-east-1
VITE_AWS_ACCESS_KEY_ID=your-access-key-id
VITE_AWS_SECRET_ACCESS_KEY=your-secret-access-key
VITE_S3_BUCKET_NAME=your-bucket-name
```

> ⚠️ These static credentials are for local development only. Cognito Identity Pool credentials replace this entirely in SPEC-002.

---

## File & Folder Structure

After this spec is complete, the following paths should exist:

```
src/
├── lib/
│   └── s3Client.ts
├── types/
│   └── s3.types.ts
├── features/
│   └── file-browser/
│       ├── index.ts
│       ├── FileBrowser.tsx
│       ├── FileBrowser.test.tsx
│       ├── useFileBrowser.ts
│       ├── useFileBrowser.test.ts
│       └── fileBrowser.service.ts
│       └── fileBrowser.service.test.ts
.env.example
```

---

## Implementation Phases

### Phase 1: Types, client, and service layer

- Create `src/types/s3.types.ts` with `S3FileItem`, `S3FolderItem`, `S3Item`, `FileList`
- Create `src/lib/s3Client.ts` with singleton `S3Client`
- Create `src/features/file-browser/fileBrowser.service.ts` with `listFiles()`
- Add `.env.example` entries
- Write unit tests for `listFiles()` (mock the S3Client)

**Checkpoint:** `npm run test` passes for `fileBrowser.service.test.ts`. Service returns correctly shaped `FileList` for a mock S3 response. Error path returns `{ success: false }` without throwing.

---

### Phase 2: Hook
- Create `src/features/file-browser/useFileBrowser.ts`
- Write unit tests for the hook using `@testing-library/react`

**Checkpoint:** `npm run test` passes for `useFileBrowser.test.ts`. Hook correctly reflects loading, error, and data states.

---

### Phase 3: FileBrowser component
- Create `src/features/file-browser/FileBrowser.tsx`
- Implement folder drill-down and breadcrumb navigation
- Create `src/features/file-browser/index.ts` barrel export
- Write basic render tests for loading, error, empty, and populated states

**Checkpoint:** `npm run dev` renders a `<FileBrowser bucket={import.meta.env.VITE_S3_BUCKET_NAME} />` in `App.tsx` that displays real files from the configured S3 bucket, folder drill-down works, breadcrumb navigates back up.

---

## Open Questions

- [ ] Should folder size (sum of contained objects) be shown? Requires recursive calls — defer decision to later spec.
- [ ] Is there a maximum number of objects expected per prefix? Affects whether pagination (SPEC-003) is urgent.
- [ ] Confirm bucket name: one global bucket with per-user prefixes, or one bucket per user?
