# Spec: Shared-Space Query Results Routing & Save

**ID:** SPEC-055
**Status:** Completed
**Last Updated:** 2026-06-27
**Depends On:** SPEC-052 (shared connections selectable in the workspace), SPEC-050 (shared bucket), SPEC-056 (membership-slot S3 perms incl. results-prefix + delete-deny), SPEC-047 (per-tab selected database), SPEC-034 (`runQuery` `OutputLocation`, history `database`), SPEC-049 (Save results to workspace), SPEC-039 (`copyObject`, `DestinationPicker`)

> **Reference:** `docs/shared-spaces-architecture.md` §5 — results for a shared-DB query route to
> `dat-prod-shared-space/{name}/athenaresults/{username}/` (each member under their own sub-prefix, delete-denied)
> so collaborators can see each other's outputs. Personal-DB queries are unchanged (SPEC-034).

## Overview

Make the query workspace fully usable against a shared connection. Two changes: (1) **results routing** — when the
workspace's active database (SPEC-047, workspace-global) is a **shared** database, `runQuery` writes results to the shared space
(`dat-prod-shared-space/{name}/athenaresults/{username}/`) instead of the user's personal `athenaresults/`, so other
members can find them; (2) **save results** — the SPEC-049 "Save results to my files" flow learns to save **from** a
shared-space result and to optionally save **into** the shared space (a folder there) as well as into the user's own
space. Schema browsing, Create view (SPEC-048), and the table options menu (SPEC-044) already operate on the active
tab's database, so they work against a shared DB once it's selectable (SPEC-052) — this spec just covers where result
bytes land and how they're saved.

## Scope

### In Scope

- **Results routing by connection kind:** `runQuery` computes its `OutputLocation` from the active workspace connection (SPEC-047, workspace-global) —
  personal → `s3://<user-space>/{username}/athenaresults/` (SPEC-034, unchanged); shared → `s3://dat-prod-shared-space/{name}/athenaresults/{username}/`
- **History `database`** records the shared DB name (already a field, SPEC-034); the result `outputLocation` reflects
  the shared path
- **Save results (SPEC-049) from a shared result:** derive the source object from the shared `outputLocation` and
  `copyObject` it; the **destination picker** offers the user's own space **and** the shared spaces the user can
  write to (member of), excluding each space's protected `athenaresults/`
- **Permissions reliance:** writing results to `dat-prod-shared-space/{name}/athenaresults/{username}/` and copying out
  rely on the SPEC-050 membership-slot S3 grants (object CRUD under the space, delete-denied on `athenaresults/`); no
  new IAM in this spec
- **Same-bucket vs cross-bucket copy for Save:** a save within the **same** bucket is a normal `CopyObject`; saving a
  **shared** result into the **user-space** bucket (or vice-versa) is a **cross-bucket** `CopyObject` — confirm the
  service supports a distinct source/dest bucket (SPEC-039 `copyObject` is same-bucket; extend or add a variant)

### Out of Scope

- **Selecting** a shared connection / the selector itself (SPEC-047/052) — assumed present
- **Schema/DDL/Create-view/table-menu** behavior on a shared DB — those already follow the active workspace database
  (SPEC-047/048/044); no change needed beyond the DB being selectable
- **Per-member results isolation _within_ a space** beyond the `{username}/` sub-prefix + delete-deny (members can
  read each other's results — that's the point; they just can't delete)
- **History/saved-queries storage location** — those stay in the user's **personal** `user_settings/` JSON stores
  (history is per-user, not shared) regardless of the queried DB; only result **CSV bytes** route to the shared
  `athenaresults/` (FR-001)
- Any **infra** change (SPEC-050 already granted the shared results-prefix perms + delete-deny)

---

## Functional Requirements

### FR-001: Route results by connection kind

#### Acceptance Criteria:

- [ ] `runQuery` (or its caller in `QueryWorkspace`) selects the `OutputLocation` from the **active workspace**
  connection (SPEC-047): personal → `{username}/athenaresults/` in the user-space bucket (SPEC-034, unchanged); shared (name
  `S`) → `dat-prod-shared-space/{S}/athenaresults/{username}/`
- [ ] The shared output path always includes the caller's `{username}/` segment (so the SPEC-050 membership-slot +
  `${aws:PrincipalTag/username}` sub-scope permits the write and the delete-deny applies)
- [ ] The recorded history entry's `database` is the shared DB name and its `outputLocation` is the shared path; a
  personal query is byte-for-byte unchanged from today

### FR-002: Results read/paginate from the shared location

#### Acceptance Criteria:

- [ ] `getQueryResults`/the results table read the same way regardless of location (Athena `GetQueryResults` is
  location-agnostic) — verify no code assumes the personal prefix for displaying results
- [ ] A member can run a shared-DB query and see its results; a non-member cannot select the connection (SPEC-052) so
  cannot run against it (defense-in-depth: the membership-slot IAM denies the shared path anyway)

### FR-003: Save results from a shared-space result

#### Acceptance Criteria:

- [ ] The SPEC-049 **Save results** action derives the source key from the (possibly shared) `outputLocation` via
  `parseS3Url` (exported by SPEC-049) and copies it; it works whether the result lives in the personal or a shared `athenaresults/`
- [ ] The destination picker offers the **user's own space** and any **shared spaces the user is a member of** (writable),
  each excluding its protected `athenaresults/` folder; choosing a destination writes `{dest}/{filename}.csv`
- [ ] Collision warn-and-confirm (SPEC-039/049) applies at the chosen destination; success Toast + "view in Files"
  deep-link resolve to the correct bucket/prefix (shared or personal)

### FR-004: Cross-bucket copy support

#### Acceptance Criteria:

- [ ] Saving a result whose **source bucket differs from the destination bucket** (e.g. a shared result saved into the
  user's own space) performs a **cross-bucket** `CopyObject`; the file-browser copy service is extended (or a variant
  added) to accept distinct source/dest buckets while keeping the same-bucket path unchanged
- [ ] The copy respects the membership-slot/`username` permissions on both ends (read the shared source under the
  member's slot; write the personal/shared dest under the appropriate grant); a permission failure surfaces an error
  Toast and writes nothing

### FR-005: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: routing picks the shared `…/{name}/athenaresults/{username}/`
  path for a shared connection and the personal path otherwise (and history records the right `database`/location);
  results display works from a shared location; Save derives the source from a shared `outputLocation`, lists
  personal + member-of shared destinations (excluding `athenaresults/`), and performs a same- or cross-bucket copy
  with collision confirm; a permission error writes nothing and shows an error Toast

---

## Data Model

No new persisted types. Touches:

```ts
// Output-location selection (FR-001)
function resultOutputLocation(conn: Connection, username: string): string {
  return conn.kind === 'shared'
    ? `s3://dat-prod-shared-space/${conn.database}/athenaresults/${username}/`
    : `s3://${USER_SPACE_BUCKET}/${username}/athenaresults/`;   // SPEC-034
}

// Copy service (FR-004) — allow distinct buckets
copyObject({ sourceBucket, sourceKey, destBucket, destKey, username, overwrite }): Promise<ServiceResult<{ destKey }>>;
// (same-bucket callers keep working; add destBucket defaulting to sourceBucket if cleaner)
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── query.service.ts            ← runQuery output-location chooses personal vs shared (FR-001)
├── query.service.test.ts
└── QueryWorkspace.tsx          ← pass the active connection to the run + save flows
apps/portal/src/features/shared-spaces/  (or file-browser)
└── (destination options)       ← Save picker offers personal + member-of shared spaces (FR-003)
apps/portal/src/features/file-browser/
├── fileBrowser.service.ts      ← copyObject gains cross-bucket source/dest (FR-004)
└── fileBrowser.service.test.ts
```

## Implementation Phases

### Phase 1: Routing

- Output-location selection by connection kind; history/location recording; verify results display from a shared
  location (FR-001, FR-002)

#### Checkpoint

Running a query on a selected shared connection writes results under
`dat-prod-shared-space/{name}/athenaresults/{username}/` and displays them; a personal query is unchanged; history
records the shared DB + location. `npm run test` + `npm run lint` pass.

### Phase 2: Save (incl. cross-bucket) + destinations

- Save derives source from the shared `outputLocation`; destination picker offers personal + member-of shared spaces;
  cross-bucket `copyObject`; collision + Toast + Files deep-link (FR-003, FR-004)

#### Checkpoint

Save results from a shared-DB query into (a) the user's own space and (b) a shared space the user belongs to — both
land the full CSV (cross-bucket copy where buckets differ), with collision confirm and a working "view in Files"
link; a permission failure writes nothing. `npm run test` + `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-21, user decision):** shared-DB query results route to the **shared prefix**
  (`…/{name}/athenaresults/{username}/`, delete-denied) so collaborators can see outputs (`shared-spaces-architecture.md` §5).
- [x] **Resolved (2026-06-21):** **history and saved queries stay personal** (in the user's own `user_settings/`),
  even for shared-DB queries — they're a private log, not shared state.
- [x] **Resolved (2026-06-21, default):** Save results may target the **user's own space or any shared space the user
  belongs to**; `copyObject` is extended to support **cross-bucket** copies. Flag if Save should be restricted to the
  user's own space only.
