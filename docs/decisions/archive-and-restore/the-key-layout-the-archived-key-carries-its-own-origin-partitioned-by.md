---
type: Decision
title: "The key layout: the archived key carries its own origin, partitioned by space kind"
description: "Vault keys are `{kind}/{name}/archive/{uuid}/…` and encode their origin; the kind segment must stay, and the browser-supplied uuid is validated as v4 and lowercased before any concatenation."
---

`personal/{username}/archive/{uuid}/…` and `shared/{space}/archive/{uuid}/…` in the archive bucket;
`{root}archive/{uuid}/receipt.txt` in the space's own bucket.

**The archived key encodes its origin**, so `origin_key` reconstructs the source with no lookup at
all. That is what lets SPEC-170 rebuild every restore destination from one `ListObjectsV2` over the
archive prefix: **the receipt is a report, not a record**, exactly as SPEC-143 judges a table by
its shape rather than by the marker it also writes. The manifest exists only as a cross-check that
can fire when something is already wrong.

**The leading kind segment is the entire fix for a real collision.** Receipts live in each space's
own bucket, where the two namespaces cannot meet; the archive bucket is the first place they do.
The space create refuses a name a pool user holds, but sign-up does not consult the shared-space
registry and names that collided before that check remain, so a user `alice` and a space `alice` can
still both exist. Flat, they would share one archive prefix, and since SPEC-170 authorizes a restore
by *space* and then reads whatever sits at that prefix, a member of space `alice` could restore user
`alice`'s archived files into the shared space. Refusing to create a shared space whose name matches
an existing username was rejected here as this layout's fix, and is now built for access reasons
(SPEC-248); it is still not this layout's fix, because it cannot repair names that already exist and
does not guard sign-up.

The `{uuid}` is browser-supplied and becomes a path segment in two buckets, so it is validated as a
UUID v4 **before it is ever concatenated**, at every builder rather than once at the front door, and
**lowercased** — S3 keys are case-sensitive, and a re-submitted id in different case would open a
second archive under a name that reads identically in every message and every listing.

## History

### 2026-11-17

- **Changed:** Shared-space creation now refuses a username (SPEC-248), which this entry had rejected as its fix; the kind segment stays, because sign-up and pre-existing names can still collide.

### 2026-08-12

- **Settled:** entered the register.
