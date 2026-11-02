---
type: Decision
title: "The dev-unauth path is retired (SPEC-198, supersedes SPEC-002)"
description: "**The dev-unauth path is RETIRED** — it worked by calling S3 unsigned from the browser, and no unsigned call is left. The `VITE_` allowlist is now `lib/env.ts` alone; local dev points the SPA at an API."
---

`VITE_S3_DEV_UNAUTH=true` browsed a read-only public test bucket with **unsigned** S3 requests, so a
developer needed no AWS account. It worked by having the browser call S3 directly, which is the
thing this arc removes: after the port there is no unsigned call left for it to make.

Gone with it: `lib/s3Client.ts` (and `devS3Client`, `getS3Client`, `CHECKSUM_OPTS`,
`REQUEST_HANDLER`), `lib/s3Errors.ts` (its last caller went with them), `ProtectedLayout`'s auth-gate
bypass, `FilesPage`'s read-only target, and five variables — `VITE_S3_DEV_UNAUTH`,
`VITE_S3_BUCKET_NAME`, `VITE_S3_ROOT_PREFIX`, `VITE_AWS_ACCESS_KEY_ID`,
`VITE_AWS_SECRET_ACCESS_KEY`.

**The guard that protected it was deleted only once the grep was clean**, and in that order for a
reason: `support.test.ts`'s block was two layers, and the load-bearing one globbed every non-test
module and asserted **set equality** between the modules naming the flag and its three-site registry.
Removing two sites and leaving one turns that red. It was deleted because its **subject** is gone,
not because it was weak — and the `runtimeConfig` allowlist that named five modules permitted to read
`import.meta.env.VITE_` is now one, `lib/env.ts`, which is the remaining fallback table.

**Local development is now: point the SPA at an API.** `.env.example` and the README say so, rather
than leaving the story implied by the absence of the old one. Presigned uploads and downloads redeem
from `http://localhost:5173`, which both buckets' CORS allowlists still name — and that entry stays
for exactly this reason, not because of the path this entry retires.

## History

### 2026-08-29

- **Settled:** SPEC-198, supersedes SPEC-002.
