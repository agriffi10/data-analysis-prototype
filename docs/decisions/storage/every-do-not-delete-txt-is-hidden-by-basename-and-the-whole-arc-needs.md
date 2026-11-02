---
type: Decision
title: "Every `DO_NOT_DELETE.txt` is hidden by BASENAME, and the whole arc needs no IaC change (SPEC-173)"
description: "Any object whose last segment is `DO_NOT_DELETE.txt` is hidden at any depth in either bucket, because both bucket policies deny deleting that basename anywhere; that Deny is why the saved-queries arc needs no IaC change, and a live refused delete is still owed."
---

**Decision (2026-08-11).** `useFileBrowser` hid one exact key, supplied by its caller. It now hides
any object whose last path segment is `DO_NOT_DELETE.txt`, at any depth, in either bucket — and the
`markerKey` parameter is **deleted**, along with the prop threaded through `DestinationPicker`,
`MoveDialog`, `CopyDialog`, `FileBrowserDialogs`, `FilesPage` and `StartQualityCheckDialog`. A
source sweep asserts no caller passes one; `DestinationPicker`'s props stopped being a union as a
result.

**The reasoning generalises further than this folder.** Both bucket policies deny
`s3:DeleteObject` on a wildcard resource ending in the marker's own basename, and `*` in an S3
resource ARN matches `/` — so *any* object with that name, anywhere in either bucket, is already
undeletable. Showing one offers an action this application's own IAM refuses, which is the
SPEC-150 FR-007 mistake waiting to happen. That same reading is what lets the whole
saved-queries-in-spaces arc ship **no `.tf` or `.tftpl` change**: the marker at
`{root}saved_queries/DO_NOT_DELETE.txt` is covered at that depth and any other, and every read,
write, list and delete the store needs is already granted by `UserPrefixObjects` /
`SharedSpaceObjects` and their listing statements.

**It is the arc's load-bearing premise, so it is pinned and it owes a live check.** A test reads
the two `.tftpl` files and asserts each `Deny` still ends in `/*/DO_NOT_DELETE.txt`, so a later IAM
edit that narrows the wildcard fails in a local `pytest lambdas/` run rather than in production
— CI no longer runs pytest (`docs/process/ci-and-deploy-traps.md`), so the guard is only as good as the pre-push run. But a passing test over a
template is not a refusal: **a real delete of a real marker, refused, is owed** (SPEC-173 FR-009),
in both a personal and a shared space. Until it is run the reading is corroborated, not discharged
— the same class of evidence that had SPEC-144 FR-001 reversed mid-build.

The saved-queries marker gets its **own body text**: `PREFIX_MARKER_BODY` says the file keeps "your
personal storage space" active, which is wrong in a shared space and wrong about what this folder
is. It reuses `PREFIX_MARKER_FILENAME` exactly, and a test says so, because the IAM protection keys
on that basename.

## History

### 2026-08-11

- **Settled:** SPEC-173.
