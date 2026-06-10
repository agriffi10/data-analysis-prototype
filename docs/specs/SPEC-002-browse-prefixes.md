# Spec: Browse Prefixes — File Browser Against Test Bucket

**ID:** SPEC-002  
**Status:** Completed 
**Last Updated:** 2026-05-23  
**Depends On:** SPEC-001

---

## Overview

This spec completes the local development file-browsing experience by wiring the `FileBrowser` component built in SPEC-001 to a real, publicly accessible S3 bucket. It introduces a configurable root prefix so the browser can be pointed at a specific subtree of the bucket rather than always starting at the bucket root. Navigation above the configured root is blocked.

Authentication and user-scoping are explicitly deferred. This spec operates entirely with the static credential model from SPEC-001 (or no credentials if the bucket allows public anonymous reads). The result is a fully functional, locally runnable file browser that exercises the complete folder navigation and file listing UX against real S3 data.

---

## Scope

### In Scope

- `VITE_S3_ROOT_PREFIX` environment variable: optional prefix the browser starts at and cannot navigate above
- Breadcrumb root clamping: the breadcrumb never exposes path segments above the configured root prefix
- App-level wiring: `App.tsx` renders `FileBrowser` driven entirely by env vars (`VITE_S3_BUCKET_NAME`, `VITE_S3_ROOT_PREFIX`)
- Optional anonymous S3 client: if no `VITE_AWS_ACCESS_KEY_ID` is set, the S3 client falls back to unsigned (anonymous) requests for publicly accessible buckets
- `.env.example` updated to document the new variable and anonymous fallback

### Out of Scope

- Authentication (Cognito, Amplify, STS) — deferred to a future spec
- Per-user prefix scoping — deferred to the same auth spec
- Upload, download, or deletion
- Filtering of dot-prefixed folders (`.config/` etc.) — no user prefix concept exists yet, so no hidden folders to manage
- Any changes to the service function, hook, or component beyond what is needed for root clamping and client fallback

---

## Functional Requirements

### FR-001: Configurable Root Prefix

#### Description:
The app must support an optional environment variable that sets the starting prefix for the file browser. When set, the browser opens at that prefix and cannot navigate above it.

#### Acceptance Criteria:
- [ ] `VITE_S3_ROOT_PREFIX` is read from the environment (empty string if not set, meaning browser starts at bucket root)
- [ ] `FileBrowser` is rendered in `App.tsx` with `prefix` initialised to `VITE_S3_ROOT_PREFIX` (or `''` if unset)
- [ ] When a root prefix is set, the breadcrumb does not render any ancestor segments above it — the root prefix label is the leftmost clickable crumb
- [ ] Clicking the leftmost breadcrumb crumb navigates back to the root prefix, not the bucket root
- [ ] The root prefix is treated as a fixed floor: no keyboard shortcut, button, or breadcrumb click can navigate above it

---

### FR-002: Anonymous S3 Client Fallback

#### Description:
If the bucket is publicly accessible (no credentials required), the app should work without any `VITE_AWS_*` credential variables set. The S3 client falls back to unsigned requests when credentials are absent.

#### Acceptance Criteria:
- [ ] If `VITE_AWS_ACCESS_KEY_ID` is not set (or is an empty string), `s3Client.ts` creates the `S3Client` with no `credentials` field (SDK anonymous/unsigned mode)
- [ ] If `VITE_AWS_ACCESS_KEY_ID` is set, `s3Client.ts` behaves exactly as it did in SPEC-001 (static credentials)
- [ ] The fallback logic is a simple conditional at client construction — no runtime switching or re-instantiation
- [ ] A comment in `s3Client.ts` notes that this anonymous mode is for development against public buckets only; production uses auth credentials obtained via STS (future spec)

---

### FR-003: App Wiring via Environment Variables

#### Description:
`App.tsx` must render the file browser using only environment variables for configuration — no hardcoded bucket names or prefixes.

#### Acceptance Criteria:
- [ ] `App.tsx` renders `<FileBrowser bucket={import.meta.env.VITE_S3_BUCKET_NAME} prefix={import.meta.env.VITE_S3_ROOT_PREFIX ?? ''} />`
- [ ] `VITE_S3_BUCKET_NAME` and `VITE_S3_ROOT_PREFIX` are documented in `.env.example`
- [ ] If `VITE_S3_BUCKET_NAME` is not set, the app renders a clear configuration error message rather than a broken UI

---

## Data Model

No new types. Existing `s3.types.ts` from SPEC-001 is unchanged.

---

## Environment Variables

Updated `.env.example`:
```
# S3 bucket for local development / testing
VITE_S3_BUCKET_NAME=your-test-bucket-name

# Optional: start the browser at this prefix instead of the bucket root
# Example: VITE_S3_ROOT_PREFIX=some-folder/
VITE_S3_ROOT_PREFIX=

# AWS credentials — required if the bucket is NOT publicly accessible
# If left blank, the S3 client uses anonymous (unsigned) requests
VITE_AWS_REGION=us-east-1
VITE_AWS_ACCESS_KEY_ID=
VITE_AWS_SECRET_ACCESS_KEY=
```

---

## File & Folder Structure

Only existing files are modified — no new files:

```
src/
├── lib/
│   └── s3Client.ts         ← MODIFIED: anonymous fallback when credentials absent
├── features/
│   └── file-browser/
│       └── FileBrowser.tsx ← MODIFIED: breadcrumb root clamping
└── App.tsx                 ← MODIFIED: driven by VITE_S3_BUCKET_NAME + VITE_S3_ROOT_PREFIX
.env.example                ← MODIFIED: documents VITE_S3_ROOT_PREFIX and anonymous fallback
```

---

## Implementation Phases

### Phase 1: Anonymous client fallback and root prefix wiring

- Update `src/lib/s3Client.ts`: conditional credentials — static if env vars present, anonymous if absent
- Update `src/App.tsx`: read `VITE_S3_BUCKET_NAME` and `VITE_S3_ROOT_PREFIX` from env; pass to `FileBrowser`; render config error if bucket name is missing
- Update `.env.example`

#### Checkpoint
Run `npm run dev` with `VITE_S3_BUCKET_NAME` pointing at a real test bucket and `VITE_AWS_ACCESS_KEY_ID` left blank. If the bucket allows public reads, the file browser loads and lists files. With credentials set, it also works. With `VITE_S3_BUCKET_NAME` unset, a configuration error message renders instead of a broken UI.

---

### Phase 2: Breadcrumb root clamping

- Update `FileBrowser.tsx`: accept an optional `rootPrefix` prop (defaults to the initial `prefix` prop value); breadcrumb renders only segments at or below `rootPrefix`; the leftmost crumb navigates to `rootPrefix` not `''`
- Update `FileBrowser.test.tsx`: add test cases for root clamping — breadcrumb does not show segments above root; clicking leftmost crumb navigates to root prefix not bucket root
- Update `App.tsx` to pass `rootPrefix={import.meta.env.VITE_S3_ROOT_PREFIX ?? ''}` to `FileBrowser`

#### Checkpoint
`npm run test` passes including new root clamping tests. `npm run dev` with `VITE_S3_ROOT_PREFIX=some-folder/` set: browser opens inside `some-folder/`, breadcrumb shows only that prefix and descendants, and no navigation above it is possible.

---

## Open Questions

- [ ] Should `VITE_S3_ROOT_PREFIX` be required to end with `/`, or should the app normalise it? Recommend the app normalises (appends `/` if missing and non-empty) to avoid user error.
- [ ] If the anonymous S3 client gets an `AccessDenied` error (bucket is not public and no creds are set), what should the error message say? Recommend a specific message: "Access denied — set VITE_AWS_ACCESS_KEY_ID or make the bucket publicly readable."
