---
type: Decision
title: "The restore's FIFO group id hashes the archive ROOT, not the bucket and the root"
description: "The restore's FIFO group id is the digest of `{kind}/{name}/archive/{archiveId}/`, without the bucket, derived by the API; it groups one archive's restores and orders only their starts."
---

SPEC-170 FR-001 specifies the digest of `{archiveBucket}/{archiveRoot}` and left it owed to this
spec, which is the producer. The browser cannot produce it: SPEC-168 decided the browser has **no
relationship with that bucket** — no CORS, no `connect-src` entry, zero portal-role statements — ~~and
`test_archive_bucket_isolation.py` asserts the SPA's build env learns the archive QUEUE and nothing
else about the plane.~~ **— superseded:** that assertion went in the 2026-08-28 suite cut, and
SPEC-200 retired the fact — the SPA's configuration now names nothing of the plane, not even its
queue, because the restore is enqueued through the API, which derives this group id by the same rule.
`test_archive_bucket_isolation.py` asserts that neither space's portal-role template names the
archive bucket and that the browser's archive enqueue grant is retired.

Including it would also buy nothing. The group id's one job here is ~~that two restores of ONE
archive serialize~~ **— superseded 2026-09-15: that the restores of ONE archive share a group, which
orders their starts and does not serialize them, since the Pipe starts executions
`FIRE_AND_FORGET` ([the entry below](the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is.md)) —**
and the archive root's own leading `personal/`/`shared/` segment — the segment SPEC-168
added precisely because a user and a shared space can share a name — already makes it globally
unique. The bucket is one constant across every restore this app can make.

So the canonical string is `{kind}/{name}/archive/{archiveId}/`, mirroring `arcommon.paths.
archive_root`, and `docs/testing/e2e.md`'s hand-crafted command was corrected to
match so the live check exercises the rule ~~the browser reproduces~~ **— superseded by SPEC-200:**
the API reproduces (`apicommon.fifo`). A test pins the derivation and
names SPEC-168's browser isolation — not the test — as the decision to re-open if it ever fails.

## History

### 2026-11-17

- **Changed:** The reason for the kind segment is restated: the space create now checks the User Pool, but a user and a space can still share a name through sign-up (SPEC-248).

### 2026-09-15

- **Changed:** The group id's job is restated: it orders the starts of one archive's restores and does not serialize them, since the Pipe starts executions `FIRE_AND_FORGET`.

### 2026-08-28

- **Changed:** The isolation test's assertion that the SPA build learns the archive queue went in the suite cut; separately SPEC-200 retired the fact, enqueuing restores through the API.

### 2026-08-12

- **Settled:** entered the register.
