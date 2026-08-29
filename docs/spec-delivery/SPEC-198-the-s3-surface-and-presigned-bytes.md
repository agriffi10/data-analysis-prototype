# Completed Spec — SPEC-198: The S3 Surface & Presigned Bytes

## What was completed?

Every remaining S3 call the browser made now goes through a route, and the file **bytes** stopped
travelling through the SDK: an upload is a presigned `PUT`, a download a presigned `GET`. Four
modules imported `@aws-sdk/client-s3`, `-lib-storage` or `-s3-request-presigner` before this spec;
none does now, and the three packages are out of `package.json`.

Delivered in two PRs: the server-side surface first (inert — nothing called it), then the browser
switchover and the retirement together.

- **`lambdas/api/`** — `spaces.py` (claims → bucket + root, refusing before any AWS call),
  `protected.py` (the marker rule and the per-bucket archive rule, plus the two containment rules a
  key and a prefix need), `s3_config.py`'s caps, and the routes: `objects_list`, `objects_head`,
  `objects_content`, `objects_mutate`, `objects_free_name`, `objects_presign`.
- **`apps/portal/src/lib/`** — `objectSpace.ts` (the one `(bucket, key) → SpaceRef` adapter, which
  is what lets nineteen call sites keep `bucket` in their signatures), `serviceResult.ts`'s
  `fromApiFailure`, `test/apiMock.ts` (programs `apiRequest` **by route id**, never by call order).
- **`fileBrowser.service.ts`** — 1064 lines to 620, no AWS import, four functions gone.
- **`s3Client.ts`, `s3Errors.ts`, the dev-unauth path and five `VITE_*` variables** — deleted.

## The disposition of all nineteen `fileBrowser.service.ts` exports

The artefact SPEC-199 and SPEC-200 copy. "We moved the code" is exactly the claim nobody can check a
year later.

| Export | Disposition |
|---|---|
| `listFiles` | **ported** → `objects.list`; the local sort and the `FileListPage` shape unchanged |
| `ensurePrefixMarker` | **ported** → `objects.writeContent`, and **two calls became one**: the route's own `Conflict` is the "already there" answer |
| `isPrefixMarkerKey` | **unchanged** (pure) |
| `deleteObject` | **ported** → `objects.delete`; the marker refusal still costs no request |
| `copyObject` | **ported** → `objects.copy`; the collision `HeadObject` moved inside the route |
| `moveObject` | **ported** → `objects.move`, **one** route performing copy-then-delete |
| `getDownloadUrl` | **ported** → `objects.downloadUrl`; RFC 6266 escaping and the credential clamp moved server-side. `expiresInSeconds` **removed** — no caller passed it, and the window is the signer's to decide |
| `objectExists` | **ported** → `objects.exists` |
| `folderExists` | **ported** → `objects.exists` with `target: 'prefix'`. It could not use `objects.list`: that route drops the prefix's own marker and every `DO_NOT_DELETE.txt`, so an empty folder would have reported itself deleted |
| `uploadFile` | **rewritten** — `objects.uploadUrl` + `XMLHttpRequest`. Same signature |
| `createFolder` | **ported** → `objects.writeContent`, two calls to one |
| `getObjectMetadata` | **ported** → `objects.metadata`; the route gained `storageClass` and `userMetadata` because the details panel renders both |
| `uploadPercent`, `validateLeafName`, `validateFolderName` | **unchanged** (pure) |
| `__resetPrefixMarkerCache` | **unchanged** |
| `deleteObjects`, `deleteFolder`, `moveFolder`, `copyFolder` | **DELETED** — Arc A's plane owns them |
| — | **added:** `firstFreeName`, one call replacing a 999-probe loop |

## Three things that were not mechanical

**The upload had to be `XMLHttpRequest`.** `fetch` fires no upload-progress event, so a `fetch`
implementation uploads correctly and leaves the bar at 0% until it jumps to 100% — a shipped feature
deleted by a transport choice, with every "the upload succeeded" test green. The assertion is on an
**intermediate** value, and it was mutation-tested by listening on `xhr` instead of `xhr.upload`:
exactly one test reddens.

**The four folder functions could not be ported and could not survive.** Their listing is recursive,
which is the object-count loop Arc A moved off the browser; and they depended on it, so the port
deleted rather than rewrote them. The accepted consequence (2026-08-28) is now sharper than the spec
recorded it: with `asyncFileOperations` **off**, a folder copy, move or delete is refused **per
item** with a `PlaneRequired` code, and the files beside it still go through. `deleteObjects` went
with them, so a multi-file delete is a loop of single deletes — which is what copy and move already
were. Written into the `GATED_SURFACES` comment and the rename/move/copy/delete guide.

**The feature-flag document needed a route of its own, and the spec did not expect that.**
`_config/feature-flags.json` belongs to no user and to no shared space, so `spaces.resolve` refuses
it — correctly. Left on the object surface every flag read would have answered 403 and fallen back
to the compiled-in all-on defaults, which is **indistinguishable from a healthy environment**.
SPEC-197 hit the same wall with `_directory/usernames.json` and solved it the same way, so
`GET /v1/feature-flags` is that precedent applied. FR-003 AC6's count is therefore **six** unedited
`s3Json` consumers, not seven, and `featureFlags.service.ts` is the seventh — edited, and its key
constant now pinned against the Python route's own by a test that reads the Python.

## Two smaller corrections to the spec, made during the build

- **`InvalidDestination` lost its rule.** Its only producers were `moveFolder` and `copyFolder`'s
  "a folder cannot be moved into itself" refusals. The destination picker already refuses that at
  the affordance with its own wording, so the code has no producer left; FR-010's five passthrough
  codes are four.
- **FR-002 AC5's Help claim was checked and did not hold.** The rename/move/copy/delete guide
  described only the plane path, not a flag-off one, so there was nothing to correct — a sentence
  was **added** naming what a refusal looks like instead.

## What is owed

Phase 5's live checks. They need a signed-in session, two accounts and a multi-GiB file, and none of
them can be run offline. They are written up as runnable steps in `docs/testing/e2e.md` and recorded
in `docs/testing/owed.md` — including FR-005 AC8 (the expiry is evaluated at request receipt, not at
completion), which is the premise the whole single-`PUT` design rests on.
