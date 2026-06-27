# Completed Spec — SPEC-057: Shared Spaces in the File Browser

Lets users browse and operate on a shared connection's files with the same file browser they use
for their own space. The Files sidebar lists the user's **spaces** — personal first, then active
shared connections — and selecting one points the browser at that space's bucket + root prefix.
Frontend-only: the file-browser services are already `bucket`-parameterized and the SPEC-056
membership-slot grants already authorize the shared S3 paths. Delivered in one PR.

## What was completed?

- **`useFileSpace` (NEW, `features/file-browser/useFileSpace.ts`):** active-space state derived from
  `useConnections` (SPEC-052) and synced to the `?space=` route param. Resolves the requested space
  to a usable `Connection` (else the personal space), derives a `FileSpaceTarget`
  (`{id, bucket, rootPrefix, kind, label}`), and exposes `selectSpace` (sets `?space=`, drops
  `?prefix=`) + `fellBack`/`dismissFellBack`. Selection and deep-linking are one URL mechanism; a
  gone/revoked/not-yet-active space reconciles to personal purely during render — the file-side
  analogue of SPEC-047's `useActiveDatabase` (FR-002/004/005).
- **`Sidebar`:** now a **Spaces** list (mirrors the Query schema rail's `DatabaseList`) — personal
  first (labelled with the username), active shared A–Z, `provisioning`/`failed` shown disabled with
  `connectionStatusLabel`; `aria-current` + sr-only "(current space)" highlight; a "Manage
  connections →" link to the Connections tab (FR-001).
- **`FilesPage`:** wires `useConnections` + `useFileSpace`, renders the Sidebar, derives every
  `FileBrowser` prop from the active `FileSpaceTarget` (keyed on the space id so switching resets
  navigation), and shows the fall-back `Banner`. `ensurePrefixMarker` stays **personal-only** (the
  pipeline provisions a shared space's marker).
- **Protections carry over for free (FR-003):** the marker hide (`markerKey`), the picker locks
  (`athenaresults/` + `user_settings/`), the listing hide, and the delete/move/copy marker guard
  are all `rootPrefix`/`markerKey`-driven, so threading the shared space's root + marker key applies
  them at `{name}/…`. Move/copy stay within the selected space (same bucket).
- **Decision (asked + recorded):** the personal space's root breadcrumb crumb now reads the
  **username** (consistent with the sidebar entry + the spec data model), reversing SPEC-013's
  "My Files" crumb. The user picked this.

## What changed from earlier specs?

- **`Sidebar`** (SPEC-035): props changed from none → `{connections, activeSpaceId, onSelectSpace}`;
  the static "My Files" link became the data-driven Spaces list.
- **`FileBrowser`** (SPEC-013): the `username` prop is now the **space root-prefix owner** (the
  username for personal, the shared-space name for a shared space) — it feeds the marker guard and
  the modify-controls gate. No service signatures changed (the spec's "no new service shapes").
- **No IAM/infra change** — shared-space S3 access is the SPEC-050/056 membership-slot grants.

## Verification

`npm run lint` / `format:check` / `test` green (693 tests). Coverage: `useFileSpace` (default
personal, shared target, unknown/provisioning → personal+`fellBack`, loading suppression,
`selectSpace`/`dismissFellBack`, null-username/unconfigured-bucket → null target); `Sidebar`
(lists personal+shared, `aria-current`, disabled pending, select callback, manage link); `FilesPage`
(personal + shared `?space=`/`?prefix=` targeting, marker key + username per space, fallback notice)
+ route-level axe a11y. Browser verification deferred — the authenticated/shared flow needs Cognito
+ seeded shared connections (no local AWS); ships with the app bundle.
