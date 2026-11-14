---
type: Decision
title: "The origins are admitted additively, and narrowed only at the cutover (SPEC-193)"
description: "A new origin is admitted beside the old one on every allowlist and narrowed only at the cutover. Cognito's callback and logout lists, the API's CORS and both buckets' CORS now name one deployed origin each; `localhost:5173` on the callback list and bucket CORS is dev, kept under Next.js by pinning `next dev` to that port. The API's CORS has never admitted it, so `npm run dev` cannot call the API: do NOT widen the production API's CORS for it."
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

**The development origin did not move with the dev server.** Next's dev server defaults to port
3000, and `npm run dev` runs `next dev --port 5173`, so `http://localhost:5173`, which the callback
list and both buckets' CORS already admit, is still where a developer signs in, and no list changed
when the portal moved to Next.js. A sign-in through the Hosted UI returns to it (live, 2026-11-13).
**The API's CORS has never admitted it**, under Vite or now, so a page served by `npm run dev` signs
in and then cannot call the API: the file listing shows a network error. Do not widen the
production API's CORS to fix that. SPEC-257's same-origin `/api/` pass-through removes the
cross-origin call, and with it the gap.

Detail: `spec-delivery/SPEC-193`.

## History

### 2026-11-13

- **Changed:** SPEC-255. The development origin stays `localhost:5173`, because the dev script pins
  Next's port, so no allowlist changed. Recorded that the API's CORS never admitted it, so `npm run
  dev` signs in but cannot call the API until SPEC-257's same-origin pass-through.

### 2026-08-26

- **Settled:** SPEC-193.
