# Completed Spec - User Prefix Marker (DO_NOT_DELETE.txt)

## What was completed from this spec?

Every user's prefix is now guaranteed to physically exist in the user-space
bucket. On the first authenticated load of `/files`, the app writes a marker
object at `{username}/DO_NOT_DELETE.txt` — idempotently, best-effort, and
invisibly. This closes the 010→014 arc: a brand-new (or fully emptied) user
space is no longer an implied-only prefix that vanishes from console tooling.

Delivered as a single phase covering all three FRs:

- **FR-001 — idempotent creation** (`fileBrowser.service.ts`, `FilesPage.tsx`):
  `ensurePrefixMarker({ bucket, username })` does `HeadObject` → on 404
  `PutObject` (`text/plain` body from the spec) → never overwrites an existing
  marker. A module-level `Set` guard (set synchronously before the first
  `await`) ensures **at most one HEAD per session** regardless of navigation or
  StrictMode double-invokes; a fresh page load resets it, so a failed attempt
  retries next session. Shares SPEC-013's expiry-retry pattern via a new
  `withAuthenticatedClient` helper and never throws (returns `ServiceResult`).
  Fired from a `FilesPage` `useEffect` gated on `user`; non-blocking and
  `console.warn`-only on failure (the browser renders regardless), and skipped
  on the dev-unauth path.
- **FR-002 — hidden from listing** (`useFileBrowser.ts`, `FileBrowser.tsx`):
  a new optional `markerKey` is threaded `FilesPage → FileBrowser →
  useFileBrowser` and filtered by **exact key**, so a like-named
  `DO_NOT_DELETE.txt` inside a subfolder still displays.
- **FR-003 — service-layer delete guard** (`fileBrowser.service.ts`):
  `isPrefixMarkerKey()` predicate + `deleteObject()` that rejects the marker
  with a `ProtectedObject` `ServiceResult` error before any S3 call. Commented
  as UI-layer defense in depth only — the authoritative protection is the IAM
  deny on `*/DO_NOT_DELETE.txt` in SPEC-013 FR-001's role policy. SPEC-018's
  recursive delete can reuse both.

A new `fileBrowser.constants.ts` holds `PREFIX_MARKER_FILENAME`,
`PREFIX_MARKER_BODY`, and `prefixMarkerKey(username)` as the single source of
truth for the marker key, re-exported via the feature barrel.

## What has changed?

- **New file**: `apps/portal/src/features/file-browser/fileBrowser.constants.ts`.
- **`fileBrowser.service.ts`**: added `ensurePrefixMarker`, `deleteObject`,
  `isPrefixMarkerKey`, the `withAuthenticatedClient` helper, and a test-only
  cache reset. `listFiles` is unchanged (it keeps its own dev-unauth fallback;
  the new auth-only operations don't need one).
- **`useFileBrowser.ts` / `FileBrowser.tsx`**: new `markerKey` parameter/prop
  for the listing filter. Existing `FileBrowser` tests updated for the added
  (third) `useFileBrowser` argument.
- **`FilesPage.tsx`**: fires `ensurePrefixMarker` on authenticated load and
  passes `markerKey` to the browser.
- **`index.ts`**: barrel now exports the marker constants/helpers and
  `deleteObject`/`isPrefixMarkerKey`.
- **No infra/IaC change**: `PutObject`/`HeadObject` on the user's own prefix and
  the `*/DO_NOT_DELETE.txt` delete-deny were all delivered in SPEC-013; the
  user-space bucket CORS already allows `HEAD`/`PUT` from the app origins
  (SPEC-010). No deploy-role change. No new env vars.

## Verification

- **Unit tests** — 74 pass; `tsc`/`lint`/`build` clean. New cases cover marker
  create (HEAD→PUT), no-overwrite when present, once-per-session guard,
  expiry-retry, the `deleteObject` guard (rejects marker, deletes normal keys),
  `isPrefixMarkerKey`, and the exact-key listing filter (root hidden, subfolder
  like-named file shown).
- **Live checkpoint (local dev server against `dat-prod-user-space`, signed-in
  test user)** — confirmed end to end: a fresh user's first `/files` load writes
  `{username}/DO_NOT_DELETE.txt` (one HEAD + one PUT in the network tab); the
  marker does not appear in the browser; second load / navigation issues no
  further PUT (and no repeat HEAD); deleting the marker via CLI and reloading
  recreates it; a subfolder `DO_NOT_DELETE.txt` displays normally.

### Follow-ups / notes

- **Folders (SPEC-016)** keep their prefixes alive with zero-byte `{prefix}/`
  placeholder objects (already auto-hidden by `listFiles`' `Key !== prefix`
  filter) — the `DO_NOT_DELETE.txt` marker is a one-off at the user's root, not
  one per folder.
- **No backfill for users who never sign in** — creation is lazy/app-side by
  design (no backend). Pre-SPEC-014 users get their marker the first time they
  load `/files`.
- **"Invisible" is client-side only** — S3 has no hidden-object attribute; the
  marker is filtered from the app listing but remains visible (intentionally,
  self-documenting) to AWS console / external tooling.
