# Spec: Shared Spaces in the File Browser

**ID:** SPEC-057
**Status:** Draft
**Last Updated:** 2026-06-21
**Depends On:** SPEC-052 (`useConnections` returns personal + shared; status/role), SPEC-050 (shared bucket), SPEC-056 (membership-slot S3 perms incl. shared delete-denies), SPEC-013 (authenticated file browser + prefix model), SPEC-015→020 + SPEC-039 (file operations — all already `bucket`-parameterized), SPEC-035 (app shell / `Sidebar`), SPEC-044 (`/files?prefix=` deep-link)

> **Reference:** `docs/shared-spaces-architecture.md` §3/§5. The **Files** surface lists the user's personal space and
> their shared connections in **one** list; selecting a shared space browses `dat-prod-shared-space/{name}/` with the
> same file browser. Per the user's model: "My Files would have alice, marketing_data, sales…". Managing connections
> (create/delete/members) is the separate **Connections** tab (SPEC-052/053/054); this spec is **consumption** only.

## Overview

Let users browse and operate on a shared connection's files the same way they do their own. The file-browser sidebar
lists the user's **spaces** — their personal space (`alice`) plus each **active** shared connection (`marketing_data`,
`sales_2026`, …) — in one list. Selecting a space points the browser at that space's **bucket + root prefix**:
personal → the user-space bucket at `{username}/`; shared → `dat-prod-shared-space/{name}/`. Every existing file
operation (list, upload, create-folder, download, metadata, delete, move, rename, copy) then works within that root,
governed entirely by IAM — the `username` tag for the personal space, the **membership-slot tag** (SPEC-056) for a
shared space. Shared files are a single shared copy (everyone with access sees the same objects). The file-browser
services are already `bucket`-parameterized, so this is largely wiring the selected space's bucket/prefix through —
plus the sidebar list and the protections that already exist (the prefix marker and the delete-denied `athenaresults/`).

## Scope

### In Scope

- **Spaces list in the file-browser sidebar:** replace the single "My Files" entry with a **Spaces** list sourced from
  `useConnections` (SPEC-052): the personal space first (labelled with the `username`), then **active** shared
  connections (A–Z). `provisioning`/`failed` shared connections appear **disabled** with their status (the
  shared-surface status primitive, design-system §7); the active space is highlighted
- **Space selection sets the browser target:** selecting a space sets the file browser's `{ bucket, rootPrefix }` —
  personal → `{ user-space bucket, "{username}/" }` (unchanged default); shared → `{ dat-prod-shared-space, "{name}/" }`.
  Breadcrumbs are rooted at the selected space; navigation stays within it
- **All file operations work within the selected space**, reusing the existing services (which already take a `bucket`
  arg) — list/upload/create-folder/download/metadata/delete/move/rename/copy — now passing the selected space's bucket
  + prefixes. Move/rename/copy remain **within a single space** (same-bucket, as SPEC-019/039)
- **Protections carry over:** the prefix **marker** (`DO_NOT_DELETE.txt`, SPEC-014 pattern) and the **delete-denied
  `athenaresults/`** (SPEC-056) are honored in shared spaces exactly as in the personal space; the UI hides/blocks
  those as it does today
- **Routing/deep-link:** the file route encodes the selected space so a link reopens it — extend the SPEC-044
  `/files?prefix=` to `/files?space={name}&prefix={key}` (absent `space` → the personal space; the SPEC-044 "View
  source files" deep-link continues to target the personal space unless a `space` is given)
- **Graceful fallback:** if the selected shared space disappears (left/deleted/revoked) the browser falls back to the
  **personal** space with a non-blocking notice (mirrors SPEC-047's query-side fallback)

### Out of Scope

- **Managing** connections — create/delete spaces + member management are the **Connections** tab (SPEC-052/053/054);
  this spec only browses
- **Cross-space** move/copy (dragging a file from one space's bucket to another) — move/copy stay within a single
  space in v1 (the `copyObject` cross-bucket variant added in SPEC-055 is for saving query results, not general
  file-browser moves); note as future
- **Query** behavior (SPEC-047/055) and the shared **Glue** database — this is the S3 file surface only
- Any **IAM/infra** change — shared-space S3 access is the SPEC-056 membership-slot grants (object CRUD under
  `dat-prod-shared-space/${aws:PrincipalTag/shared_space_k}/*`, delete-denied on its `athenaresults/` + marker); the
  personal space is unchanged (SPEC-013)
- **Per-space upload limits / settings** differing from the personal space (same `VITE_MAX_UPLOAD_BYTES`, etc.)

---

## Functional Requirements

### FR-001: Spaces list in the sidebar

#### Acceptance Criteria:

- [ ] The file-browser sidebar shows a **Spaces** list from `useConnections` (SPEC-052): the **personal** space first
  (labelled with the `username`), then **active** shared connections A–Z; the selected space is highlighted
  (`accent-soft`), keyboard-navigable, selection conveyed by text/state (not color-only)
- [ ] `provisioning`/`failed` shared connections render **disabled** with their status (not selectable); a
  personal-only user (no shared connections) sees just their own space (no empty/awkward group)
- [ ] The standalone "Shared Connections" management group is **not** here — management is the Connections tab
  (SPEC-052); this list is for **browsing** (an "Add connection" affordance, if shown, links to the Connections tab)

### FR-002: Space selection → browser target

#### Acceptance Criteria:

- [ ] Selecting a space sets the browser's `{ bucket, rootPrefix }`: personal → `{ <user-space bucket>, "{username}/" }`;
  shared `S` → `{ dat-prod-shared-space, "{S}/" }`
- [ ] Breadcrumbs are **rooted at the selected space** (the space name is the root crumb; navigation stays within the
  space's root prefix); switching spaces resets to that space's root
- [ ] The default on load is the **personal** space (unchanged from today); the file listing, pagination, and empty
  states behave exactly as SPEC-013/037 within the selected root

### FR-003: File operations within a shared space

#### Acceptance Criteria:

- [ ] List / upload / create-folder / download / metadata / delete / move / rename / copy all operate within the
  selected space by passing its `bucket` + prefixes to the existing services (SPEC-015→020, 039) — **no new service
  shapes** (the services already accept `bucket`)
- [ ] In a shared space these calls are authorized by the **membership-slot** IAM (SPEC-056); a user who is not a
  member cannot select the space (it isn't in their list) and the IAM denies the path regardless (defense-in-depth)
- [ ] The **prefix marker** and **`athenaresults/` delete-deny** are honored in shared spaces (the UI refuses to delete
  the marker and the space's `athenaresults/`, as it does for the personal space); move/copy destination pickers
  exclude the protected folders (as SPEC-039)
- [ ] Move/rename/copy stay **within the selected space** (same bucket); the destination picker is scoped to that
  space's tree

### FR-004: Routing / deep-link

#### Acceptance Criteria:

- [ ] The file route encodes the space: `/files?space={name}&prefix={key}` opens that space at `{key}`; **absent**
  `space` → the personal space (so existing links + the SPEC-044 "View source files" deep-link are unchanged)
- [ ] A `space` the user can't access (not in their `useConnections`) falls back to the personal space with a
  non-blocking notice (no crash, no stuck invalid target)

### FR-005: Fallback when a space vanishes

#### Acceptance Criteria:

- [ ] If the currently-browsed shared space disappears from `useConnections` (left/deleted/revoked, e.g. after a
  Refresh-connections), the browser falls back to the **personal** space with a non-blocking notice; any in-flight
  operation against the gone space surfaces a clean error, not a crash

### FR-006: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: the sidebar lists personal + active shared spaces (pending/
  failed disabled); selecting a shared space targets `{ dat-prod-shared-space, "{name}/" }` and roots breadcrumbs
  there; file operations pass the selected `bucket`/prefix to the existing services; the marker + `athenaresults/`
  protections apply in a shared space; `/files?space=&prefix=` opens the right space (absent `space` → personal); an
  inaccessible/vanished space falls back to personal with a notice

---

## Data Model

No new persisted types. The file browser gains a small **active-space** notion derived from a `Connection`
(SPEC-047/052):

```ts
type FileSpaceTarget = {
  bucket: string;        // user-space bucket | 'dat-prod-shared-space'
  rootPrefix: string;    // '{username}/' | '{name}/'
  kind: 'personal' | 'shared';
  label: string;         // username | shared name (root breadcrumb)
};
// Derived: personal → { bucket: USER_SPACE_BUCKET, rootPrefix: `${username}/` , kind:'personal' }
//          shared   → { bucket: 'dat-prod-shared-space', rootPrefix: `${name}/`, kind:'shared' }
```

## File & Folder Structure

```
apps/portal/src/features/file-browser/
├── FileBrowser.tsx              ← consume the selected space target (bucket + rootPrefix); root breadcrumbs at the space
├── useFileSpace.ts              ← NEW: active-space state from useConnections (default personal) + ?space= route sync
├── useFileSpace.test.ts         ← NEW
└── (services unchanged)         ← already bucket-parameterized (SPEC-015→020, 039)
apps/portal/src/components/
└── Sidebar.tsx                  ← Spaces list (personal + active shared) from useConnections; disabled pending/failed
```

## Implementation Phases

### Phase 1: Spaces list + space target

- `useFileSpace` (active space from `useConnections`, default personal, `?space=` sync); Sidebar Spaces list; root the
  browser at the selected space's bucket/prefix + breadcrumbs (FR-001, FR-002, FR-004)

#### Checkpoint

`npm run dev`: the sidebar lists the personal space + (seeded) active shared spaces; selecting a shared one roots the
browser at `dat-prod-shared-space/{name}/` and breadcrumbs read from the space; the personal space is the default and
unchanged; `/files?space=…&prefix=…` opens the right place. Tests/lint pass.

### Phase 2: Operations + protections + fallback

- Pass the selected `bucket`/prefixes through every file operation; honor the marker + `athenaresults/` protections in
  shared spaces; fallback when a space vanishes (FR-003, FR-005)

#### Checkpoint

In a shared space (as a member) upload/download/create-folder/delete/move/copy all work and respect the marker +
`athenaresults/` delete-deny; move/copy stay within the space; leaving/deleting the space (then Refresh) falls the
browser back to personal with a notice. Tests/lint pass.

## Open Questions

- [x] **Resolved (2026-06-21, user decision):** the Files surface lists the personal space **and** shared connections
  in **one** list; selecting a shared space browses it with the same file browser.
- [x] **Resolved (2026-06-21):** managing connections is the separate **Connections** tab (SPEC-052); this spec is
  browsing/consumption only.
- [x] **Resolved (2026-06-21, default):** move/copy stay **within a single space** in v1 (no cross-space/cross-bucket
  file moves); flag if cross-space copy is wanted (would reuse the SPEC-055 cross-bucket `copyObject`).
- [x] **Resolved (2026-06-21, default):** the route encodes the space as `/files?space={name}` (absent → personal), so
  the SPEC-044 deep-link stays valid. Flag if a path-style route (`/files/{space}/…`) is preferred.
