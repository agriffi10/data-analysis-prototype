---
type: Decision
title: "The origins are admitted additively, and narrowed only at the cutover (SPEC-193)"
description: "A new origin is admitted beside the old one on every allowlist and narrowed only at the cutover. Cognito's callback and logout lists, the API's CORS and both buckets' CORS now name one deployed origin each; `localhost:5173` on the callback list and bucket CORS is dev."
---

The Cognito app client's callback and logout lists, CloudFront's `connect-src`, and the API's CORS
list each gained the new origin **beside** the existing one. Nothing was removed.

An allowlist naming one origin makes the other a rollback that cannot be exercised. The narrowing
belonged to the spec that retired the distribution, deliberately last, and **SPEC-202 did it in the
same merge as the destroy** — after the rollback had been rehearsed against the container origin
while both were still admitted. Each addition was verified to have removed nothing, because a
"replace" where an "add" was intended applies green and is invisible until the day it is needed.

**The three lists are now one origin each** (plus `localhost:5173` on the callback list and both
bucket CORS rules, which is dev, not a second deployed origin): Cognito's callback and logout lists,
the API's CORS `allow_origins`, and both buckets' CORS. The container's `connect-src` is the fourth
list of the same kind and narrowed in the merge before, since it is served from the image rather
than from an allowlist.

Detail: `spec-delivery/SPEC-193`.

## History

### 2026-08-26

- **Settled:** SPEC-193.
