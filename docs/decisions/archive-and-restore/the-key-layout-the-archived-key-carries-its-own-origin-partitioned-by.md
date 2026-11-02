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
Shared-space names are made unique against the shared-space registry only — **nothing anywhere
checks a proposed space name against the User Pool** — so a user `alice` and a space `alice` can
both exist today. Flat, they would share one archive prefix, and since SPEC-170 authorizes a restore
by *space* and then reads whatever sits at that prefix, a member of space `alice` could restore user
`alice`'s archived files into the shared space. The alternative fix — refusing to create a shared
space whose name matches an existing username — is **rejected**: it changes a shipped, unrelated
control plane, it cannot repair names that already exist, and it would make space creation depend on
the User Pool for a reason unrelated to space creation.

The `{uuid}` is browser-supplied and becomes a path segment in two buckets, so it is validated as a
UUID v4 **before it is ever concatenated**, at every builder rather than once at the front door, and
**lowercased** — S3 keys are case-sensitive, and a re-submitted id in different case would open a
second archive under a name that reads identically in every message and every listing.

## History

### 2026-08-12

- **Settled:** entered the register.
