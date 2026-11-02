---
type: Decision
title: "The receipt's paths name the ROOTS, and the expansion keeps what every other plane drops"
description: "Receipt paths name the space root and archive root, never the selection; the expansion keeps zero-byte placeholders and hidden or underscore segments, and an empty expansion is a refusal."
---

The spec's illustrative receipt shows a selected folder as the original path. That would be wrong
for the key layout this arc shipped: `archived_key` keeps every object's path relative to the SPACE
root, so naming the selection pairs it with an archive prefix that does not correspond to it — and
a 200-item selection has no single original path at all. Rooted at the space root and the archive
root, the two lines are exact inverses of each other for every object, for every selection.

The expansion's ignore predicate is this plane's own, and it **keeps** what
`cpcommon.s3_listing.is_ignored` drops: zero-byte folder placeholders (an archived empty folder has
to come back, and nothing else in the plan records that it existed) and hidden or underscore-
prefixed segments (those are ignored because *Athena* ignores them, which says nothing about a
byte-for-byte copy of a user's own folder). It excludes only prefix markers and the portal-managed
root folders. An empty expansion is a REFUSAL, never a success: a receipt claiming zero files
archived is worse than a refusal, and an empty archive prefix is indistinguishable at restore time
from one whose objects have vanished.

## History

### 2026-08-12

- **Settled:** entered the register.
