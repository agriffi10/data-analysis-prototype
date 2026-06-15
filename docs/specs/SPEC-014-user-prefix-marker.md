# Spec: User Prefix Marker — DO_NOT_DELETE.txt on First Login

**ID:** SPEC-014
**Status:** Completed
**Last Updated:** 2026-06-15
**Depends On:** SPEC-011 (STS credentials), SPEC-013 (write access to own prefix), SPEC-008 (`/files` route)

> **Note:** Last spec in the 010→014 arc — the app can only write the marker once it has scoped write credentials (SPEC-013).

## Overview

Ensure every user's prefix physically exists in the user-space bucket by writing a marker object at `{username}/DO_NOT_DELETE.txt` (e.g. `dat-prod-user-space/alice/DO_NOT_DELETE.txt`) the first time they load the files page. S3 prefixes only exist while at least one object lives under them — without a marker, a brand-new (or fully emptied) user space is invisible to console tooling and any future per-prefix automation. The app creates the marker idempotently on load, hides it from the file listing, and protects it from deletion through the UI.

## Scope

### In Scope

- First-load check-and-create of `{username}/DO_NOT_DELETE.txt` (idempotent, best-effort)
- Marker content: short explanatory text (what it is, why not to delete it)
- Marker hidden from the file browser listing
- Marker excluded from any future delete operations at the service layer (defensive, even though delete UI doesn't exist yet)
- Unit tests for the check/create/filter logic

### Out of Scope

- Backend/Lambda-based creation (deliberate decision: app-side on first login)
- Backfilling markers for users who never log in (no mechanism exists without a backend; acceptable)
- Server-side protection of the marker — **handled by SPEC-013 FR-001**, which includes an IAM deny for `s3:DeleteObject` on `*/DO_NOT_DELETE.txt` (resolved 2026-06-10)
- `.config/connections.json` bootstrapping (future Connection Manager spec)

---

## Functional Requirements

### FR-001: Idempotent Marker Creation

#### Description:

On authenticated load of the files page, the app guarantees the marker exists.

#### Acceptance Criteria:

- [ ] After auth and credential acquisition, the app issues `HeadObject` on `{username}/DO_NOT_DELETE.txt`; on 404/NotFound it issues `PutObject` with the explanatory text body (`text/plain`)
- [ ] Runs at most once per session (in-memory flag) — no repeated HEADs on navigation
- [ ] Existing marker is never overwritten (HEAD-then-PUT, not unconditional PUT)
- [ ] Failure is non-blocking and silent to the user beyond a console warning: the file browser loads normally even if marker creation fails (it will retry next session)
- [ ] Logic lives in the auth/file feature service layer using `ServiceResult` — no S3 calls in components

### FR-002: Marker Hidden from Listing

#### Description:

The marker is plumbing, not user content.

#### Acceptance Criteria:

- [ ] `DO_NOT_DELETE.txt` at the user's root prefix is filtered out of the file browser listing
- [ ] The filter applies only to the exact root-level key — a user's own file named `DO_NOT_DELETE.txt` inside a subfolder is still shown
- [ ] Filter is unit-tested

### FR-003: Marker Protected at the Service Layer

#### Description:

Future delete functionality must not remove the marker accidentally.

#### Acceptance Criteria:

- [ ] The S3 service layer rejects delete requests targeting `{username}/DO_NOT_DELETE.txt` with a descriptive `ServiceResult` error
- [ ] Unit-tested, with a comment noting this is UI-layer defense only (IAM-level protection is an open question)

---

## Data Model

```ts
// Marker constants — src/features/file-browser/fileBrowser.constants.ts (or similar)
export const PREFIX_MARKER_FILENAME = 'DO_NOT_DELETE.txt';
export const PREFIX_MARKER_BODY =
  'This file keeps your personal storage space active. Deleting it may cause ' +
  'your folder to disappear from administrative tooling. It is hidden from ' +
  'your file browser and can be ignored.';
```

---

## API / Interface Contract

```ts
// src/features/file-browser/fileBrowser.service.ts (addition)
ensurePrefixMarker(params: {
  bucket: string;
  username: string;
}): Promise<ServiceResult<{ created: boolean }>>;
```

## Environment Variables

None new.

## File & Folder Structure

```
apps/portal/src/features/file-browser/
├── fileBrowser.service.ts        ← + ensurePrefixMarker, delete guard
├── fileBrowser.service.test.ts   ← + marker tests
├── fileBrowser.constants.ts      ← NEW (or fold into types file)
└── useFileBrowser.ts             ← listing filter
```

## Implementation Phases

### Phase 1: Marker creation + filtering

- FR-001, FR-002, FR-003 in one pass (small spec)

#### Checkpoint

Fresh test user signs in → `aws s3 ls s3://dat-prod-user-space/<username>/` shows `DO_NOT_DELETE.txt`; the file browser does not show it; second page load issues no PUT (network tab). Deleting the marker via CLI and reloading recreates it. A subfolder file named `DO_NOT_DELETE.txt` displays normally. `npm run test` passes.

## Open Questions

- [x] **Resolved (2026-06-10):** yes — the IAM deny is part of SPEC-013 FR-001's policy template. The service-layer guard here (FR-003) becomes defense in depth.
- [x] **Resolved (2026-06-10):** marker body copy as drafted in the Data Model section.
